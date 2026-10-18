# SPDX-License-Identifier: MIT
"""A2A agents in the cockpit: the peers this Bridge may ask, and a conversation with each.

The peers are the files of infra/a2a-peers/ (skills/a2a reads the same ones). The page lists them with
what their agent card says they can do; the card is public, fetched in the background and kept for
CARD_TTL seconds, and no token ever reaches the page. A message goes out only on the user's click,
through `skills/a2a/scripts/a2a.py ask --json`, which resolves the peer's token itself
(skills/secrets run), so the value never passes through this process. A follow up continues the
peer's A2A context. A peer that holds a task (it waits for its owner's approval) answers with a
state that is not final; the turn then shows as waiting and `get` reads it again later, without
sending anything new. Each message runs on a thread of its own; the page gets the state as the
`agents` event. Conversations are kept in the state dir (agents.json).
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable

SCRIPT = "skills/a2a/scripts/a2a.py"
PEERS_DIR = Path("infra") / "a2a-peers"
CARD_TTL = 300
CARD_TIMEOUT = 8
WAIT = "90"                 # seconds a2a.py waits for a held task before it answers with its state
ASK_TIMEOUT = 150
MAX_CONVS = 30
MAX_TURNS = 40
FINAL = {"completed", "failed", "canceled", "rejected"}
PEER_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}\Z")
CONV_RE = re.compile(r"^g[0-9a-f]{10}\Z")
CONTEXT_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}\Z")
TASK_RE = CONTEXT_RE
MODES = ("question", "task")
# a task says what is expected back; a question goes out as typed
TASK_FRAME = {
    "de": "Auftrag: {text}\n\nBitte erledige das im Rahmen dessen, was du darfst, und sag am Ende kurz, "
          "was du getan hast und was offen bleibt.",
    "en": "Task: {text}\n\nPlease do this within what you are allowed to do, and say briefly at the end "
          "what you did and what is still open.",
}


def argv_ok(argv: list[str], python: str, script: str) -> bool:
    """The two shapes the runner lets through for a2a.py: ask (optionally in a context) and get."""
    if len(argv) < 5 or argv[0] != python or argv[1] != script:
        return False
    rest = argv[2:]
    if rest[:1] == ["get"]:
        return len(rest) == 4 and rest[1] == "--json" and bool(PEER_RE.match(rest[2])) and bool(TASK_RE.match(rest[3]))
    if rest[:4] != ["ask", "--json", "--wait", WAIT]:
        return False
    rest = rest[4:]
    if rest[:1] == ["--context"]:
        if len(rest) < 2 or not CONTEXT_RE.match(rest[1]):
            return False
        rest = rest[2:]
    return len(rest) == 3 and bool(PEER_RE.match(rest[0])) and rest[1] == "--"


def _https(url: Any) -> str | None:
    return url[:300] if isinstance(url, str) and url.startswith("https://") else None


def _strs(value: Any, cap: int, size: int = 60) -> list[str]:
    return [str(x)[:size] for x in value or [] if isinstance(x, str) and x.strip()][:cap] if isinstance(value, list) else []


def summarize_card(card: Any) -> dict:
    """What the page shows of an agent card: who, which version, where and how it is reached, what it
    takes and gives, which skills with their examples. Links only when https; of the security schemes
    only their names, never a hint at a value."""
    if not isinstance(card, dict):
        return {}
    skills = []
    for sk in card.get("skills") or []:
        if not isinstance(sk, dict):
            continue
        skills.append({"id": str(sk.get("id") or "")[:60], "name": str(sk.get("name") or sk.get("id") or "")[:80],
                       "description": str(sk.get("description") or "")[:1200], "tags": _strs(sk.get("tags"), 8, 30),
                       "examples": _strs(sk.get("examples"), 6, 200)})
    face = next((i for i in card.get("supportedInterfaces") or [] if isinstance(i, dict)), {})
    caps = card.get("capabilities") if isinstance(card.get("capabilities"), dict) else {}
    prov = card.get("provider") if isinstance(card.get("provider"), dict) else {}
    schemes = card.get("securitySchemes") if isinstance(card.get("securitySchemes"), dict) else {}
    return {"name": str(card.get("name") or "")[:120], "description": str(card.get("description") or "")[:1200],
            "version": str(card.get("version") or "")[:30] or None,
            "protocol": str(face.get("protocolVersion") or card.get("protocolVersion") or "")[:12] or None,
            "binding": str(face.get("protocolBinding") or card.get("preferredTransport") or "")[:20] or None,
            "endpoint": _https(face.get("url") or card.get("url")),
            "provider": {"name": str(prov.get("organization") or "")[:120] or None, "url": _https(prov.get("url"))}
            if prov else None,
            "docs": _https(card.get("documentationUrl")),
            "streaming": caps.get("streaming") is True, "push": caps.get("pushNotifications") is True,
            "input": _strs(card.get("defaultInputModes"), 6), "output": _strs(card.get("defaultOutputModes"), 6),
            "auth": [str(k)[:40] for k in schemes][:4],
            "skills": skills[:16]}


def fetch_card(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "bridge-cockpit/agents"})
    with urllib.request.urlopen(req, timeout=CARD_TIMEOUT) as r:   # noqa: S310 - https card urls from the peer files
        return json.loads(r.read().decode("utf-8"))


class Agents:
    def __init__(self, app: Any, fetch: Callable[[str], dict] = fetch_card):
        self.app = app
        self.fetch = fetch
        self.lock = threading.Lock()
        self.cards: dict[str, dict] = {}
        self.refreshing = False
        self.convs: dict[str, dict] = {}
        self.path = Path(app.state_dir) / "agents.json" if getattr(app, "state_dir", None) else None
        self.load()

    # ------------------------------------------------------------ peers and cards

    def peers(self) -> dict[str, dict]:
        """The peer files: a name that is a slug and matches its file, an https card url; `_` files skipped."""
        import yaml
        out = {}
        folder = Path(self.app.root) / PEERS_DIR
        for path in sorted(folder.glob("*.yaml")) if folder.is_dir() else []:
            if path.name.startswith("_"):
                continue
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
            except (OSError, yaml.YAMLError):
                continue
            if not isinstance(data, dict) or data.get("name") != path.stem or not PEER_RE.match(path.stem):
                continue
            url = data.get("card_url")
            if not isinstance(url, str) or not url.startswith("https://"):
                continue
            out[path.stem] = data
        return out

    def refresh_cards(self, block: bool = False) -> None:
        """Fetch the cards that are older than CARD_TTL, on a thread unless `block`."""
        with self.lock:
            if self.refreshing:
                return
            self.refreshing = True

        def work() -> None:
            try:
                now = time.time()
                for pid, peer in self.peers().items():
                    with self.lock:
                        old = self.cards.get(pid)
                    if old and now - old["at"] < CARD_TTL:
                        continue
                    try:
                        card, err = summarize_card(self.fetch(peer["card_url"])), None
                    except Exception as exc:  # noqa: BLE001 - an unreachable card is a state, not a crash
                        card, err = (old or {}).get("card") or {}, str(exc)[:160]
                    with self.lock:
                        self.cards[pid] = {"at": now, "card": card, "error": err}
            finally:
                with self.lock:
                    self.refreshing = False
                self.app.broadcast("agents", self.state())

        if block:
            work()
        else:
            threading.Thread(target=work, name="bridge-cockpit-cards", daemon=True).start()

    def peer_out(self, pid: str, peer: dict) -> dict:
        usage = peer.get("usage") if isinstance(peer.get("usage"), dict) else {}
        cached = self.cards.get(pid) or {}
        mine = sorted((c for c in self.convs.values() if c["peer"] == pid), key=lambda c: c.get("last_ms") or 0)
        last = (mine[-1].get("last_ms") if mine else None) or None
        # reachable as far as the last call says: a refusal or a failure counts until a call goes through
        turn = mine[-1]["turns"][-1] if mine and mine[-1]["turns"] else {}
        failed = turn.get("error") if turn.get("error") and turn.get("error") != "interrupted" else None
        reach = ("refused" if failed and re.search(r"\b40[13]\b|refused", failed) else "failed" if failed
                 else "unreachable" if cached.get("error") else "ok" if cached.get("card") else "unknown")
        return {"reach": reach, "last_error": failed,
                "id": pid, "summary": str(peer.get("summary") or ""), "owner": str(peer.get("owner") or "") or None,
                "network": peer.get("network") if peer.get("network") in ("tailnet", "public") else None,
                "needs_token": peer.get("auth") == "bearer",
                "usage": {"allowed": [str(x) for x in usage.get("allowed") or []][:6],
                          "human_gate": str(usage.get("human_gate") or "") or None},
                "card": cached.get("card") or None, "card_error": cached.get("error"),
                "card_at_ms": int(cached["at"] * 1000) if cached.get("at") else None, "last_ms": last}

    def state(self) -> dict:
        peers = self.peers()
        with self.lock:
            out = [self.peer_out(pid, p) for pid, p in peers.items()]
            convs = sorted(self.convs.values(), key=lambda c: c.get("last_ms") or 0, reverse=True)
            return {"peers": out, "convs": json.loads(json.dumps(convs))}

    # ------------------------------------------------------------ conversations

    def load(self) -> None:
        if self.path is None:
            return
        from .store import read_json
        data = read_json(self.path)
        for c in data if isinstance(data, list) else []:
            if not isinstance(c, dict) or not isinstance(c.get("id"), str) or not CONV_RE.match(c["id"]):
                continue
            if not isinstance(c.get("turns"), list) or not c["turns"]:
                continue
            if c.get("running"):
                c["running"] = False
                last = c["turns"][-1]
                if isinstance(last, dict) and last.get("a") is None and not last.get("error") and not last.get("waiting"):
                    last["error"] = "interrupted"
            self.convs[c["id"]] = c

    def save(self) -> None:
        """Called under the lock."""
        if self.path is None:
            return
        from .store import atomic_write_json
        try:
            atomic_write_json(self.path, sorted(self.convs.values(), key=lambda c: c["started_ms"]), mode=0o600)
        except OSError as exc:
            self.app.log_error(f"agents: not kept: {exc!r}")

    def lang(self) -> str:
        lang = str(getattr(self.app.cfg, "language", "de"))[:2]
        return lang if lang in TASK_FRAME else "en"

    def argv(self, *rest: str) -> list[str]:
        return [self.app.runner.python, self.app.runner.script(SCRIPT), *rest]

    def start(self, peer: str, text: str, mode: str = "question", conv: str | None = None) -> str:
        """Send in a new conversation, or go on in `conv`; returns the conversation id at once."""
        if mode not in MODES:
            raise ValueError("unknown mode")
        if peer not in self.peers():
            raise KeyError("no such peer")
        now = int(self.app.clock())
        with self.lock:
            if conv is not None:
                c = self.convs.get(conv)
                if c is None or c["peer"] != peer:
                    raise KeyError("no such conversation")
                if c["running"]:
                    raise RuntimeError("this conversation is still waiting for its answer")
                if len(c["turns"]) >= MAX_TURNS:
                    raise RuntimeError("this conversation is long enough, start a new one")
            else:
                conv = "g" + uuid.uuid4().hex[:10]
                c = {"id": conv, "peer": peer, "started_ms": now, "last_ms": now, "context_id": None, "turns": [],
                     "running": False}
                self.convs[conv] = c
                for old in sorted(self.convs.values(), key=lambda x: x["started_ms"])[:-MAX_CONVS]:
                    if old["running"]:
                        continue
                    if not self._archive(old, "overflow", now):
                        break             # the archive is down: keep them all, try again at the next start
                    del self.convs[old["id"]]
            sent = TASK_FRAME[self.lang()].format(text=text) if mode == "task" else text
            c["turns"].append({"q": text, "mode": mode, "a": None, "state": None, "task_id": None, "waiting": False,
                               "at_ms": now, "answered_ms": None, "error": None})
            c["running"], c["last_ms"] = True, now
            context = c["context_id"]
            self.save()
        ctx = ["--context", context] if context and CONTEXT_RE.match(context) else []
        self._spawn(conv, self.argv("ask", "--json", "--wait", WAIT, *ctx, peer, "--", sent))
        return conv

    def poll(self, conv: str) -> None:
        """Read a waiting turn's task again."""
        with self.lock:
            c = self.convs.get(conv)
            if c is None:
                raise KeyError("no such conversation")
            last = c["turns"][-1]
            if c["running"] or not last.get("waiting") or not last.get("task_id") or not TASK_RE.match(last["task_id"]):
                raise RuntimeError("nothing is waiting in this conversation")
            c["running"] = True
            self.save()
        self._spawn(conv, self.argv("get", "--json", c["peer"], last["task_id"]), polling=True)

    def forget(self, conv: str) -> None:
        """Take a conversation off the list into the archive; nothing goes to the agent."""
        with self.lock:
            c = self.convs.get(conv)
            if c is None:
                raise KeyError("no such conversation")
            if c["running"]:
                raise RuntimeError("this conversation is still waiting for its answer")
            if not self._archive(c, "removed", int(self.app.clock())):
                raise RuntimeError("the archive cannot be written, the conversation stays")
            del self.convs[conv]
            self.save()
        self.app.broadcast("agents", self.state())

    def _archive(self, c: dict, why: str, now: int) -> bool:
        """Called under the lock: True when the conversation is kept in the archive (or there is no state dir)."""
        if self.path is None:
            return True
        from .store import archive_conv
        try:
            archive_conv(self.path.parent, "agents", c, why, now)
            return True
        except OSError as exc:
            self.app.log_error(f"agents: not archived: {exc!r}")
            return False

    def _spawn(self, conv: str, argv: list[str], polling: bool = False) -> None:
        threading.Thread(target=self._run, args=(conv, argv, polling), name="bridge-cockpit-a2a", daemon=True).start()
        self.app.broadcast("agents", self.state())

    def _run(self, conv: str, argv: list[str], polling: bool = False) -> None:
        app = self.app
        try:
            run = app.run(argv, ASK_TIMEOUT)
            answer = None
            for line in reversed((run.out or "").strip().splitlines()):
                try:
                    data = json.loads(line)
                except ValueError:
                    continue
                if isinstance(data, dict) and "state" in data:
                    answer = data
                    break
            with self.lock:
                c = self.convs.get(conv)
                if c is None:
                    return
                turn = c["turns"][-1]
                if answer is None:
                    err = (run.err or run.out or "no answer").strip().splitlines()[-1:] or ["no answer"]
                    turn["error"] = app.scrub(err[0]).removeprefix("a2a: ")[:300]
                    turn["waiting"] = False
                else:
                    state = str(answer.get("state") or "")
                    turn["state"] = state or None
                    turn["task_id"] = answer.get("task_id") if isinstance(answer.get("task_id"), str) else turn["task_id"]
                    text = str(answer.get("text") or "").strip()
                    turn["a"] = text[:20000] if text else turn["a"]
                    turn["waiting"] = state not in FINAL
                    turn["error"] = None if state in FINAL - {"failed", "rejected"} or turn["waiting"] else \
                        (text[:300] or state)
                    if state in ("failed", "rejected"):
                        turn["a"] = None
                    turn["answered_ms"] = int(app.clock()) if state in FINAL else None
                    ctx_id = answer.get("context_id")
                    if isinstance(ctx_id, str) and CONTEXT_RE.match(ctx_id):
                        c["context_id"] = ctx_id
        except Exception as exc:  # noqa: BLE001 - a failed message must never leave `running` set
            app.log_error(f"agents: {exc!r}")
            with self.lock:
                c = self.convs.get(conv)
                if c:
                    c["turns"][-1]["error"] = str(exc)[:300]
        finally:
            with self.lock:
                if conv in self.convs:
                    c = self.convs[conv]
                    c["running"] = False
                    # "last contact" is a message or an answer; looking again at a held one is neither
                    if not polling or not c["turns"][-1].get("waiting"):
                        c["last_ms"] = int(app.clock())
                    self.save()
            app.broadcast("agents", self.state())
