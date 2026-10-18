# SPDX-License-Identifier: MIT
"""Relay of the cockpit: questions from the page into the Claude Code control session.

Each file has exactly one writer (the mod has no rename, lock or delete):
  relay/inbox/<id>.json            the server (tmp file + os.replace)
  relay/done/<id>.json             the mod of the target session
  relay/heartbeat/<session>.json   the mod of that session, every 5 s
The server picks the target from fresh heartbeats (younger than 15 s) and names it in
the record, so two sessions never race for one question. Every file of the three carries `mac`,
an HMAC-SHA256 keyed by `relay.key` in a 0700 directory OUTSIDE the Bridge (default
~/.local/state/bridge-cockpit, or $BRIDGE_COCKPIT_KEY_DIR), over a message that names its kind:
  inbox      `inbox|id|target_session|expires_ms|text`
  heartbeat  `heartbeat|session|at_ms|busy|surface`   (busy 1 or 0, surface '' when null)
  done       `done|id|status|at_ms|answer`            (answer '' when null)
The free text always comes last. The mod submits only records it can verify, and the server reads
only heartbeats and done files it can verify, so a process that can merely write into the repo can
neither hand the control session a prompt, nor pose as the control session, nor answer for it.
Status of a record = the
status of its done file, else `queued`; queued past its expiry shows `expired`,
submitted for longer than 30 min shows `stuck`. Rules: contract sections 6.1 to 6.3.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import os
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .store import atomic_write_json, read_json
from .text import TABLES

RELAY_ID_RE = re.compile(r"^\d{8}T\d{6}-[0-9a-f]{8}\Z")
SESSION_RE = re.compile(r"^[A-Za-z0-9-]{8,64}\Z")
KINDS = ("row", "info", "follow_up", "overview", "plan_day", "evening", "free")
DONE_STATUSES = {"submitted", "answered", "aborted", "error", "expired", "stuck", "rejected"}
ANSWERED = {"answered", "aborted", "error"}
HEARTBEAT_FRESH_MS = 15000
EXPIRES_MS = 600000
STUCK_MS = 30 * 60000
OFFLINE_KEEP_MS = 3600000
FILE_KEEP_S = 24 * 3600
HEARTBEAT_KEEP_S = 3600
RECORDS_SHOWN = 20
ANSWER_MAX = 20000
KEY_FILE = "relay.key"
KEY_RE = re.compile(r"^[0-9a-f]{64}\Z")


def default_key_dir() -> Path:
    """Where relay.key lives: $BRIDGE_COCKPIT_KEY_DIR, else ~/.local/state/bridge-cockpit (never inside a Bridge)."""
    env = os.environ.get("BRIDGE_COCKPIT_KEY_DIR")
    return Path(env) if env else Path.home() / ".local" / "state" / "bridge-cockpit"


def load_key(key_dir: Path) -> str:
    """The relay key (64 hex characters), created once with mode 0600 in a 0700 directory."""
    key_dir = Path(key_dir)
    key_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(key_dir, 0o700)
    path = key_dir / KEY_FILE
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, "w", encoding="ascii") as handle:
            handle.write(secrets.token_hex(32) + "\n")
    key = path.read_text(encoding="ascii").strip()
    if not KEY_RE.match(key):
        raise ValueError(f"{path} does not hold a relay key; delete it to get a new one")
    os.chmod(path, 0o600)
    return key


def _mac(key: str, *parts: object) -> str | None:
    """None when the message does not encode as UTF-8 (a lone surrogate from JSON): unverifiable, never a crash."""
    try:
        message = "|".join(str(p) for p in parts).encode("utf-8")
    except UnicodeEncodeError:
        return None
    return hmac.new(key.encode("ascii"), message, hashlib.sha256).hexdigest()


def relay_mac(key: str, rid: str, session: str, expires_ms: int, text: str) -> str | None:
    """The inbox record's mac; the mod computes the same (hooks/relay.ts relayMac)."""
    return _mac(key, "inbox", rid, session, expires_ms, text)


def heartbeat_mac(key: str, session: str, at_ms: int, busy: bool, surface: str | None) -> str | None:
    """The heartbeat's mac, as the mod signs it (hooks/relay.ts heartbeatMac).

    in_flight and mod_version are not signed: a future reader of them would trust unsigned data.
    """
    return _mac(key, "heartbeat", session, at_ms, 1 if busy else 0, surface or "")


def done_mac(key: str, rid: str, status: str, at_ms: int, answer: str | None) -> str | None:
    """The done file's mac, as the mod signs it (hooks/relay.ts doneMac).

    session and turn_id are not signed (a future reader of them would trust unsigned data), and an
    answer of None signs like '', so a writer may swap the two; both show no answer.
    """
    return _mac(key, "done", rid, status, at_ms, answer or "")


def _is_int(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _mac_ok(data: dict, want: str | None) -> bool:
    mac = data.get("mac")
    return want is not None and isinstance(mac, str) and hmac.compare_digest(mac, want)


def new_relay_id(now_ms: float) -> str:
    stamp = dt.datetime.fromtimestamp(now_ms / 1000, tz=dt.timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"{stamp}-{secrets.token_hex(4)}"


def unframe(text: str, rid: str) -> str:
    for table in TABLES.values():
        prefix = table["relay_frame"].format(id=rid, text="")
        if text.startswith(prefix):
            return text[len(prefix):]
    return text


class Relay:
    def __init__(self, state_dir: Path, cfg: Any, clock: Callable[[], float], tx: dict, key: str | None = None):
        self.base = Path(state_dir) / "relay"
        self.inbox = self.base / "inbox"
        self.done = self.base / "done"
        self.heartbeat_dir = self.base / "heartbeat"
        for d in (self.base, self.inbox, self.done, self.heartbeat_dir):
            d.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(d, 0o700)
            except OSError:
                pass
        # without a key file (tests, a read-only Relay) a random one: records it writes verify nowhere
        self.key = key or secrets.token_hex(32)
        self.cfg = cfg
        self.clock = clock
        self.tx = tx
        self.lock = threading.RLock()
        self.records: dict[str, dict] = {}
        self.last_status: dict[str, str] = {}
        self.last_online: tuple | None = None
        self.rebuild()

    # ------------------------------------------------------------ records

    def rebuild(self) -> None:
        with self.lock:
            for path in sorted(self.inbox.glob("*.json")):
                rid = path.stem
                data = read_json(path)
                if not RELAY_ID_RE.match(rid) or not isinstance(data, dict) or data.get("id") != rid:
                    continue
                text = data.get("text") if isinstance(data.get("text"), str) else ""
                self.records[rid] = {
                    "id": rid, "kind": data.get("kind") if data.get("kind") in KINDS else "free",
                    "created_ms": int(data.get("created_ms") or 0), "expires_ms": int(data.get("expires_ms") or 0),
                    "preview": unframe(text, rid)[:200], "text": text, "offline": None,
                }
            for rec in self.records.values():
                self.last_status[rec["id"]] = self.status_of(rec)

    def read_done(self, rid: str) -> dict | None:
        data = read_json(self.done / f"{rid}.json")
        if not isinstance(data, dict) or data.get("id") != rid or data.get("status") not in DONE_STATUSES:
            return None
        # only the mod holds the key: a done file it did not sign never sets a status or an answer
        at, answer = data.get("at_ms"), data.get("answer")
        if not _is_int(at) or not (answer is None or isinstance(answer, str)):
            return None
        if not _mac_ok(data, done_mac(self.key, rid, data["status"], at, answer)):
            return None
        return data

    def status_of(self, rec: dict, now: float | None = None) -> str:
        now = self.clock() if now is None else now
        if rec.get("offline"):
            return rec["offline"]
        done = self.read_done(rec["id"])
        if done:
            status = done["status"]
            at = done.get("at_ms") if isinstance(done.get("at_ms"), (int, float)) else 0
            if status == "submitted" and now - at > STUCK_MS:
                return "stuck"
            return status
        return "expired" if now > rec["expires_ms"] else "queued"

    def record_json(self, rec: dict, now: float | None = None) -> dict:
        status = self.status_of(rec, now)
        answer = None
        answered_ms = None
        if not rec.get("offline"):
            done = self.read_done(rec["id"])
            if done and done["status"] in ANSWERED:
                answer = done.get("answer")[:ANSWER_MAX] if isinstance(done.get("answer"), str) else None
                answered_ms = int(done["at_ms"]) if isinstance(done.get("at_ms"), (int, float)) else None
        return {"id": rec["id"], "kind": rec["kind"], "created_ms": rec["created_ms"], "status": status,
                "preview": rec["preview"], "answer": answer, "answered_ms": answered_ms}

    def get(self, rid: str) -> dict | None:
        with self.lock:
            rec = self.records.get(rid)
            return dict(rec) if rec else None

    # ------------------------------------------------------------ target

    def heartbeats(self, now: float) -> list[dict]:
        fresh = []
        try:
            entries = list(os.scandir(self.heartbeat_dir))
        except OSError:
            return []
        for entry in entries:
            if not entry.name.endswith(".json"):
                continue
            session = entry.name[:-5]
            if not SESSION_RE.match(session):
                continue
            data = read_json(Path(entry.path))
            if not isinstance(data, dict) or data.get("session") != session:
                continue
            at, surface, busy = data.get("at_ms"), data.get("surface"), data.get("busy")
            if not _is_int(at) or now - at >= HEARTBEAT_FRESH_MS:
                continue
            if not (surface is None or isinstance(surface, str)) or not isinstance(busy, bool):
                continue
            # a heartbeat the mod did not sign (a copy of the control tab's surface under another
            # session id, a newer at_ms) is never a target
            if not _mac_ok(data, heartbeat_mac(self.key, session, at, busy, surface)):
                continue
            fresh.append({"session": session, "surface": surface, "busy": busy, "at_ms": at})
        fresh.sort(key=lambda h: h["at_ms"], reverse=True)
        return fresh

    def target(self, control_tab: dict | None, cmux_ok: bool, now: float | None = None) -> tuple[dict | None, str | None]:
        now = self.clock() if now is None else now
        if not self.cfg.relay:
            return None, "disabled"
        fresh = self.heartbeats(now)
        if not fresh:
            return None, "no_heartbeat"
        names = {n for n in ((control_tab or {}).get("id"), (control_tab or {}).get("ref")) if n}
        if cmux_ok and self.cfg.control and names:
            # the surface a session heartbeats is its terminal's name for the tab: cmux's surface id,
            # or $TMUX_PANE (%3), which the tmux driver gives as the tab's id and ref
            match = [h for h in fresh if h["surface"] in names]
            return (match[0], None) if match else (None, "no_control")
        if len(fresh) == 1:
            return fresh[0], None
        if cmux_ok and self.cfg.control:
            return None, "no_control"
        return None, "ambiguous"

    def state(self, control_tab: dict | None, cmux_ok: bool, with_records: bool = True) -> dict:
        now = self.clock()
        target, reason = self.target(control_tab, cmux_ok, now)
        session = None
        if target:
            session = {"id_short": target["session"][:8],
                       "surface_ok": bool(control_tab and target["surface"]
                                         and target["surface"] in (control_tab.get("id"), control_tab.get("ref"))),
                       "busy": target["busy"], "at_ms": target["at_ms"]}
        out = {"enabled": bool(self.cfg.relay), "online": target is not None, "reason": reason, "session": session}
        if with_records:
            with self.lock:
                recs = sorted(self.records.values(), key=lambda r: (r["created_ms"], r["id"]), reverse=True)
                out["records"] = [self.record_json(r, now) for r in recs[:RECORDS_SHOWN]]
        return out

    # ------------------------------------------------------------ ask

    def ask(self, kind: str, prompt: str, control_tab: dict | None, cmux_ok: bool) -> tuple[dict, bool]:
        """Queue a framed prompt for the target session; (record, online)."""
        now = self.clock()
        rid = new_relay_id(now)
        framed = self.tx["relay_frame"].format(id=rid, text=prompt)
        target, _reason = self.target(control_tab, cmux_ok, now)
        rec = {"id": rid, "kind": kind, "created_ms": int(now), "expires_ms": int(now) + EXPIRES_MS,
               "preview": prompt[:200], "text": framed, "offline": None if target else "offline"}
        if target:
            atomic_write_json(self.inbox / f"{rid}.json", {
                "v": 1, "id": rid, "created_ms": rec["created_ms"], "expires_ms": rec["expires_ms"],
                "target_session": target["session"], "kind": kind, "text": framed, "chars": len(framed),
                "mac": relay_mac(self.key, rid, target["session"], rec["expires_ms"], framed)})
        with self.lock:
            self.records[rid] = rec
            self.last_status[rid] = self.status_of(rec, now)
        return self.record_json(rec, now), target is not None

    def mark_sent_to_tab(self, rid: str) -> dict | None:
        with self.lock:
            rec = self.records.get(rid)
            if not rec:
                return None
            rec["offline"] = "sent_to_tab"
            self.last_status[rid] = "sent_to_tab"
            return self.record_json(rec)

    # ------------------------------------------------------------ scan and cleanup

    def scan(self, control_tab: dict | None, cmux_ok: bool) -> tuple[list[dict], dict | None]:
        """Records whose status changed, and the relay state when online/target changed."""
        now = self.clock()
        changed = []
        with self.lock:
            for rid, rec in list(self.records.items()):
                if rec.get("offline") and now - rec["created_ms"] > OFFLINE_KEEP_MS:
                    del self.records[rid]
                    self.last_status.pop(rid, None)
                    continue
                status = self.status_of(rec, now)
                if self.last_status.get(rid) != status:
                    self.last_status[rid] = status
                    changed.append(self.record_json(rec, now))
        state = self.state(control_tab, cmux_ok, with_records=False)
        key = (state["online"], state["reason"], state["session"]["id_short"] if state["session"] else None,
               state["session"]["busy"] if state["session"] else None)
        state_changed = None
        if key != self.last_online:
            self.last_online = key
            state_changed = state
        return changed, state_changed

    def cleanup(self) -> None:
        now = time.time()
        for directory, keep in ((self.inbox, FILE_KEEP_S), (self.done, FILE_KEEP_S), (self.heartbeat_dir, HEARTBEAT_KEEP_S)):
            try:
                entries = list(os.scandir(directory))
            except OSError:
                continue
            for entry in entries:
                try:
                    if entry.is_file() and now - entry.stat().st_mtime > keep:
                        os.unlink(entry.path)
                except OSError:
                    pass
        with self.lock:
            for rid, rec in list(self.records.items()):
                if not rec.get("offline") and not (self.inbox / f"{rid}.json").exists():
                    del self.records[rid]
                    self.last_status.pop(rid, None)
