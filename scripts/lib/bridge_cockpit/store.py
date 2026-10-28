# SPDX-License-Identifier: MIT
"""Persistent web state under state_dir: state.json (hidden rows, team runs) and view.json.

The mod keeps its own hidden rows and team runs in its `$.store`; the web keeps
these separately (documented, not synced: contract section 13). Every write is
atomic (tmp file + os.replace). Also the small file helpers the other modules share:
atomic JSON writes, log files rotated at 1 MB, and the chat archive (chats/<name>-YYYY-MM.jsonl), where a
conversation goes when it leaves its list, so no chat is ever dropped, and which the page reads back for the
questions of the last days (read_archive). And the click origin log (usage.jsonl, append_clicks): which control was
used from which place, never what it was about, for scripts/cockpit-usage.py.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .model import SETTLE_OUTCOMES, iso_date
from .settled import SettledStore

LOG_MAX_BYTES = 1024 * 1024
RUNS_SEEN_MAX = 300         # the newest workflow runs marked as checked; an older run has long left the files view
SESSION_LINKS_MAX = 300      # the newest links of sessions to tasks; an older one has long been resumed or forgotten
REFUSED_PER_SESSION = 8      # the tasks a session was said not to work on ("Not this task"), the newest kept
# the click origin log: at this size usage.jsonl becomes usage.jsonl.1, so both together stay under half a megabyte;
# a batch from the page holds at most CLICKS_MAX events, each counted up to CLICK_N_MAX
CLICKS_MAX_BYTES = 256 * 1024
CLICKS_MAX = 60
CLICK_N_MAX = 999
CLICK_KINDS = ("click", "verb")
# what a field may hold: a name from the page's code (an area of the explain overlay, a class or data-u of a
# control), never words, an item key (no colon) or a path (no slash). A page id is the profile's own, as /api/seen
# takes it, but without a colon either
CLICK_NAME_RE = re.compile(r"^@?[A-Za-z][A-Za-z0-9_-]{0,47}(\.[A-Za-z][A-Za-z0-9_-]{0,47}){0,2}\Z")
CLICK_PAGE_RE = re.compile(r"^[^\s/\\:\x00-\x1f\x7f]{1,64}\Z")
CLICK_VERB_RE = re.compile(r"^[a-z][a-z0-9_]{0,47}\Z")


def atomic_write_text(path: Path, text: str, mode: int | None = None) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        if mode is not None:
            os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_json(path: Path, data: Any, mode: int | None = None) -> None:
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, separators=(",", ":")), mode)


def read_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def archive_conv(state_dir: Path, name: str, conv: dict, why: str, now_ms: int) -> None:
    """Append one conversation, whole, to the archive file of the month it leaves its list (local time);
    raises OSError when it cannot be kept, and the caller then keeps the conversation in its list. At
    least once: should the list file fail to save afterwards, the conversation comes back after a
    restart and a second removal archives it again."""
    folder = Path(state_dir) / "chats"
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = folder / f"{name}-{time.strftime('%Y-%m', time.localtime(now_ms / 1000))}.jsonl"
    line = json.dumps({"at_ms": now_ms, "why": why, "conv": conv}, ensure_ascii=False, separators=(",", ":"))
    with _log_lock:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def read_archive(state_dir: Path, name: str, since_ms: int, now_ms: int) -> list[dict]:
    """The rows archive_conv wrote from `since_ms` on, oldest first: the files of the months between then and
    `now_ms` (local time), a line that cannot be read skipped. Read only."""
    folder = Path(state_dir) / "chats"
    months, at = [], since_ms
    while True:
        month = time.strftime("%Y-%m", time.localtime(at / 1000))
        if month not in months:
            months.append(month)
        if at >= now_ms:
            break
        at = min(now_ms, at + 86_400_000 * 28)
    rows: list[dict] = []
    for month in months:
        try:
            lines = (folder / f"{name}-{month}.jsonl").read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and isinstance(row.get("conv"), dict) and isinstance(row.get("at_ms"), int) and row["at_ms"] >= since_ms:
                rows.append(row)
    return rows


_log_lock = threading.Lock()


def append_log(path: Path, line: str, max_bytes: int = LOG_MAX_BYTES) -> None:
    """Append one line; at max_bytes the file becomes <name>.1 (one backup)."""
    path = Path(path)
    with _log_lock:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and path.stat().st_size >= max_bytes:
                os.replace(path, path.with_name(path.name + ".1"))
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(line.rstrip("\n") + "\n")
        except OSError:
            pass


def clean_clicks(events: Any, verbs: Any = None) -> list[dict]:
    """The events of one batch as usage.jsonl keeps them: {kind, page, view, area, control, verb, n}, each field a
    name or "-". A field the page should not have sent (a title, a text) is left out; an event whose page, view,
    area or control is no name, or whose verb is none the server knows (`verbs`), is dropped whole. ValueError for
    a batch that is no list or longer than CLICKS_MAX."""
    if not isinstance(events, list) or len(events) > CLICKS_MAX:
        raise ValueError(f"events must be a list of up to {CLICKS_MAX}")
    out = []
    for ev in events:
        if not isinstance(ev, dict) or ev.get("kind") not in CLICK_KINDS:
            continue
        row = {"kind": ev["kind"]}
        for name, pattern in (("page", CLICK_PAGE_RE), ("view", CLICK_NAME_RE), ("area", CLICK_NAME_RE),
                              ("control", CLICK_NAME_RE), ("verb", CLICK_VERB_RE)):
            value = ev.get(name)
            if value is None or value == "-":
                row[name] = "-"
            elif isinstance(value, str) and pattern.match(value):
                row[name] = value
            else:
                break
        else:
            if row["page"] == "-" or (row["verb"] != "-" and verbs is not None and row["verb"] not in verbs):
                continue
            n = ev.get("n", 1)
            row["n"] = min(n, CLICK_N_MAX) if isinstance(n, int) and not isinstance(n, bool) and n > 0 else 1
            out.append(row)
    return out


def append_clicks(path: Path, events: Any, now_ms: float, verbs: Any = None, max_bytes: int = CLICKS_MAX_BYTES) -> int:
    """One batch of the page's clicks into the click origin log (usage.jsonl), stamped to the minute, rotated at
    max_bytes like every log here; how many events were kept"""
    rows = clean_clicks(events, verbs)
    if rows:
        at = dt.datetime.fromtimestamp(now_ms / 1000).isoformat(timespec="minutes")
        append_log(path, "\n".join(json.dumps({"at": at, **r}, separators=(",", ":")) for r in rows), max_bytes)
    return len(rows)


class WebStore:
    """state.json: {"v": 1, "hidden": {row_key: "YYYY-MM-DD"}, "dismissed": {row_key: {outcome, at, title}},
    "team_runs": {slug: {team, roles, at}}}. A dismissed row (done or not doing, from a source the web
    cannot close, like a GitHub issue) stays out of the briefing until "show again"; no date brings it back.

    With `settled_dir` (the server passes work/cockpit/settled/, settled.py), hidden and dismissed rows are
    shared through git: every hide, dismiss and "show again" is also one new file there, reading merges
    that record with the legacy keys here (the record decides every key it knows), and the legacy entries
    are copied in once at start. The legacy keys are still written, so an older version reads them after a
    downgrade. Without it (tests, a caller of its own) the store is what it was: state.json only."""

    def __init__(self, state_dir: Path, clock: Callable[[], float], settled_dir: Path | None = None):
        self.state_dir = Path(state_dir)
        self.path = self.state_dir / "state.json"
        self.view_path = self.state_dir / "view.json"
        self.clock = clock
        self.lock = threading.Lock()
        data = read_json(self.path)
        data = data if isinstance(data, dict) else {}
        hidden = data.get("hidden") if isinstance(data.get("hidden"), dict) else {}
        runs = data.get("team_runs") if isinstance(data.get("team_runs"), dict) else {}
        self._hidden = {k: v for k, v in hidden.items() if isinstance(k, str) and isinstance(v, str)}
        gone = data.get("dismissed") if isinstance(data.get("dismissed"), dict) else {}
        self._dismissed = {k: v for k, v in gone.items()
                           if isinstance(k, str) and isinstance(v, dict) and v.get("outcome") in SETTLE_OUTCOMES}
        tiles = data.get("home_tiles")
        # the start page's own choice of tiles and shelves; None until one was made
        self._home = [x for x in tiles if isinstance(x, str)] if isinstance(tiles, list) else None
        seen, pins = data.get("home_seen"), data.get("pins")
        # what the chooser offered when the choice was made: a tile it did not offer yet gets its default
        self._seen = [x for x in seen if isinstance(x, str)] if isinstance(seen, list) else None
        self._pins = [x for x in pins if isinstance(x, str)] if isinstance(pins, list) else []
        # the first-run tour: {how: finished|skipped, v: the page's tour version, at: date}; None until it ended
        tour = data.get("tour")
        ok = (isinstance(tour, dict) and tour.get("how") in ("finished", "skipped") and isinstance(tour.get("v"), int)
              and not isinstance(tour.get("v"), bool) and tour["v"] >= 0 and isinstance(tour.get("at"), str))
        self._tour = {"how": tour["how"], "v": tour["v"], "at": tour["at"]} if ok else None
        self._runs = {k: v for k, v in runs.items()
                      if isinstance(v, dict) and isinstance(v.get("team"), str) and isinstance(v.get("roles"), list)}
        links = data.get("session_links") if isinstance(data.get("session_links"), dict) else {}
        # which task a Claude session works on: {session id: {task, name, cwd, at_ms, how}}, how is "tab" (the
        # session runs in a task tab, BRIDGE_TAB_SLUG) or "hand" (linked on the Sessions page). Kept after the
        # session ends, so the task can go on in it (claude --resume, only on this machine).
        self._links = {k: v for k, v in links.items()
                       if isinstance(k, str) and isinstance(v, dict) and isinstance(v.get("task"), str)}
        # "Not this task": {session id: {slug: at_ms}}, a session the page shall not take for work on that task,
        # neither from its transcript (sessions.infer) nor from its tab (server.link_tab_sessions)
        refused = data.get("session_refused") if isinstance(data.get("session_refused"), dict) else {}
        self._refused = {sid: {s: int(at) for s, at in v.items() if isinstance(s, str) and isinstance(at, (int, float))}
                         for sid, v in refused.items() if isinstance(sid, str) and isinstance(v, dict)}
        # the workflow runs whose result was checked in the files view: {run id: at_ms}
        seen_runs = data.get("runs_seen") if isinstance(data.get("runs_seen"), dict) else {}
        self._runs_seen = {k: v for k, v in seen_runs.items() if isinstance(k, str) and isinstance(v, (int, float))}
        # findings marked seen ("Seen", or the close of their inbox item): {finding key: {fp, day, note, inbox}},
        # shared like a hide (settled.py); and the inbox items whose close was already read for one
        acks = data.get("acks") if isinstance(data.get("acks"), dict) else {}
        self._acks = {k: v for k, v in acks.items() if isinstance(k, str) and isinstance(v, dict) and isinstance(v.get("fp"), str)}
        read = data.get("acks_read")
        self._acks_read = [x for x in read if isinstance(x, str)] if isinstance(read, list) else []
        self.prune()
        self.settled = SettledStore(settled_dir, clock) if settled_dir is not None else None
        if self.settled is not None:
            try:
                self.settled.migrate(self._hidden, self._dismissed)
            except OSError:
                pass        # read only or no room: the legacy keys still count, the next start tries again

    def today(self) -> str:
        return iso_date(self.clock())

    def _save(self) -> None:
        atomic_write_json(self.path, {"v": 1, "hidden": self._hidden, "dismissed": self._dismissed,
                                      "team_runs": self._runs, "home_tiles": self._home, "home_seen": self._seen,
                                      "pins": self._pins, "session_links": self._links, "tour": self._tour,
                                      "runs_seen": self._runs_seen, "session_refused": self._refused,
                                      # only once there is one: a store without findings marked seen reads as before
                                      **({"acks": self._acks, "acks_read": self._acks_read}
                                         if self._acks or self._acks_read else {})})

    def prune(self) -> bool:
        """Drop hidden entries whose date has come (hidden while date > today)."""
        today = self.today()
        with self.lock:
            gone = [k for k, v in self._hidden.items() if v <= today]
            for k in gone:
                del self._hidden[k]
            if gone:
                self._save()
            return bool(gone)

    def home_tiles(self) -> list | None:
        with self.lock:
            return None if self._home is None else list(self._home)

    def set_home_tiles(self, ids: list, seen: list | None = None) -> None:
        with self.lock:
            self._home = list(ids)
            if seen is not None:
                self._seen = list(seen)
            self._save()

    def home(self) -> dict:
        with self.lock:
            return {"tiles": None if self._home is None else list(self._home),
                    "seen": None if self._seen is None else list(self._seen), "pins": list(self._pins)}

    def tour(self) -> dict | None:
        with self.lock:
            return None if self._tour is None else dict(self._tour)

    def set_tour(self, how: str | None, v: int = 0) -> None:
        """The first-run tour ended (finished or skipped), or None to offer it again"""
        with self.lock:
            self._tour = None if how is None else {"how": how, "v": v, "at": iso_date(self.clock())}
            self._save()

    def pin(self, key: str, on: bool) -> None:
        """A row pinned to the start page, or taken off it; the order is the order of pinning"""
        with self.lock:
            if on and key not in self._pins:
                self._pins.append(key)
            elif not on and key in self._pins:
                self._pins.remove(key)
            else:
                return
            self._save()

    def _merged(self) -> tuple[dict, dict]:
        """(hidden, dismissed): the shared record for every key it knows, the legacy keys for the rest."""
        hidden, dismissed = dict(self._hidden), json.loads(json.dumps(self._dismissed))
        if self.settled is None:
            return hidden, dismissed
        known, shared_hidden, shared_dismissed = self.settled.state(self.today())
        hidden = {k: v for k, v in hidden.items() if k not in known} | shared_hidden
        dismissed = {k: v for k, v in dismissed.items() if k not in known} | shared_dismissed
        return hidden, dismissed

    def _share(self, write: Callable[[SettledStore], None]) -> None:
        """A hide or dismiss into the shared record. A failed write is not fatal: the legacy key holds the
        decision on this machine, and the next start copies it in (the record does not know the key)."""
        if self.settled is not None:
            try:
                write(self.settled)
            except OSError:
                pass

    def hidden(self) -> dict:
        with self.lock:
            return self._merged()[0]

    def hide(self, key: str, until: str, title: str = "") -> None:
        with self.lock:
            self._hidden[key] = until
            self._save()
            self._share(lambda s: s.hide(key, until, title))

    def unhide(self, key: str) -> bool:
        with self.lock:
            hidden, dismissed = self._merged()
            if key not in hidden and key not in dismissed:
                return False
            if self.settled is not None and self.settled.knows(key):
                self.settled.unsettle(key)      # a record, not a deletion: merge-safe (settled.py)
            self._hidden.pop(key, None)
            self._dismissed.pop(key, None)
            self._save()
            return True

    def dismissed(self) -> dict:
        with self.lock:
            return self._merged()[1]

    def dismiss(self, key: str, outcome: str, title: str) -> None:
        with self.lock:
            self._dismissed[key] = {"outcome": outcome, "at": iso_date(self.clock()), "title": title[:200]}
            self._hidden.pop(key, None)
            self._save()
            if outcome in SETTLE_OUTCOMES:      # another outcome never outlived a restart here; it is not shared
                self._share(lambda s: s.dismiss(key, outcome, title))

    def team_runs(self) -> dict:
        with self.lock:
            return json.loads(json.dumps(self._runs))

    def set_team_run(self, slug: str, run: dict | None) -> None:
        with self.lock:
            if run is None:
                self._runs.pop(slug, None)
            else:
                self._runs[slug] = run
            self._save()

    def session_links(self) -> dict:
        with self.lock:
            return json.loads(json.dumps(self._links))

    def link_session(self, sid: str, task: str, name: str, cwd: str, how: str) -> bool:
        """True when it changed. A link by hand is never replaced by one a tab suggests."""
        with self.lock:
            old = self._links.get(sid)
            if old and (old.get("how") == "hand" and how == "tab" or (old.get("task") == task and old.get("how") == how)):
                if old.get("name") != name and name:
                    old["name"] = name[:120]
                    self._save()
                return False
            self._links[sid] = {"task": task, "name": name[:120], "cwd": cwd[:400], "at_ms": int(self.clock()),
                                "how": how}
            for drop in sorted(self._links, key=lambda k: self._links[k].get("at_ms", 0))[:-SESSION_LINKS_MAX]:
                del self._links[drop]
            self._save()
            return True

    def session_refused(self) -> dict:
        with self.lock:
            return {sid: dict(v) for sid, v in self._refused.items()}

    def refuse_session(self, sid: str, slug: str) -> None:
        """A session is not work on this task: kept with the newest REFUSED_PER_SESSION per session and the
        newest SESSION_LINKS_MAX sessions"""
        with self.lock:
            mine = self._refused.setdefault(sid, {})
            mine[slug] = int(self.clock())
            for drop in sorted(mine, key=lambda s: mine[s])[:-REFUSED_PER_SESSION]:
                del mine[drop]
            newest = lambda k: max(self._refused[k].values(), default=0)  # noqa: E731
            for drop in sorted(self._refused, key=newest)[:-SESSION_LINKS_MAX]:
                del self._refused[drop]
            self._save()

    def unrefuse_session(self, sid: str, slug: str) -> bool:
        """A refusal taken back (the session is linked to that task by hand); True when there was one"""
        with self.lock:
            mine = self._refused.get(sid) or {}
            if slug not in mine:
                return False
            del mine[slug]
            if not mine:
                self._refused.pop(sid, None)
            self._save()
            return True

    def acks(self) -> dict:
        """The findings marked seen: the shared record for every key it knows, this machine's for the rest"""
        with self.lock:
            acks = json.loads(json.dumps(self._acks))
            if self.settled is None:
                return acks
            known, shared = self.settled.acks()
            return {k: v for k, v in acks.items() if k not in known} | shared

    def ack(self, key: str, fp: str, note: str = "", inbox: str = "") -> None:
        """A finding marked seen as it stands now (fp): calm until its fingerprint changes"""
        with self.lock:
            self._acks[key] = {"fp": fp, "day": iso_date(self.clock()), "note": str(note)[:400], "inbox": inbox}
            if inbox:
                self.read_inbox(inbox)
            self._save()
            self._share(lambda s: s.ack(key, fp, note, inbox))

    def unack(self, key: str) -> bool:
        """The "show again" of a finding: it counts again; True when it was marked"""
        with self.lock:
            had = key in self._acks
            if self.settled is not None:
                known, shared = self.settled.acks()
                had = key in shared or (had and key not in known)    # the record decides every key it knows
                if key in shared:
                    self.settled.unack(key)      # a record, not a deletion (settled.py)
            self._acks.pop(key, None)
            self._save()
            return had

    def acks_read(self) -> set:
        with self.lock:
            read = set(self._acks_read)
        return read | {v.get("inbox") for v in self.acks().values() if v.get("inbox")}

    def read_inbox(self, item_id: str) -> None:
        """An inbox item whose close was read for a finding, so an undo is not taken back by it (lock held)"""
        if item_id not in self._acks_read:
            self._acks_read = [*self._acks_read, item_id][-RUNS_SEEN_MAX:]

    def mark_inbox_read(self, item_id: str) -> None:
        with self.lock:
            self.read_inbox(item_id)
            self._save()

    def runs_seen(self) -> dict:
        with self.lock:
            return dict(self._runs_seen)

    def run_seen(self, run: str) -> None:
        """Mark a workflow run as checked: its result no longer waits in the files view"""
        with self.lock:
            self._runs_seen[run] = int(self.clock())
            for drop in sorted(self._runs_seen, key=lambda k: self._runs_seen[k])[:-RUNS_SEEN_MAX]:
                del self._runs_seen[drop]
            self._save()

    def unlink_session(self, sid: str) -> bool:
        with self.lock:
            if self._links.pop(sid, None) is None:
                return False
            self._save()
            return True

    # view.json: stale while revalidate
    def save_view(self, view: dict, language: str | None = None) -> None:
        try:
            atomic_write_json(self.view_path, {"v": 1, "view": view, "language": language})
        except OSError:
            pass

    def load_view(self, language: str | None = None) -> dict | None:
        """Today's last view, unless it was written in another language (the words in it are the briefing's)."""
        data = read_json(self.view_path)
        if isinstance(data, dict) and language and data.get("language") not in (None, language):
            return None
        view = data.get("view") if isinstance(data, dict) else None
        if not isinstance(view, dict) or not isinstance(view.get("collected_ms"), (int, float)):
            return None
        if not isinstance(view.get("buckets"), list):
            return None
        return view if iso_date(view["collected_ms"]) == self.today() else None
