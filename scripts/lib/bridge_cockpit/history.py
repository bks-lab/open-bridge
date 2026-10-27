# SPDX-License-Identifier: MIT
"""What the dashboard did, and how to take it back.

Every action that closes, drops, settles or hides something records one entry: when, which verb, and
per item its row key, title, kind (task, inbox, other), what was done, and the inverse where one
exists (a closed task reopens with `task.py reopen`, a closed or dropped inbox item with `inbox.py
reopen`, a dismissed or hidden row shows again). The page lists the entries by day with an "undo"
button; an item that was taken back says so. Kept as one JSON list in the state dir (history.json,
mode 600), the newest MAX_ENTRIES. On first use the history is filled from the older audit.log, for
the items that can still be found: a close whose item is still closed can be taken back from here,
one that was opened again since (by hand, or before this file existed) shows as already taken back.
"""
from __future__ import annotations

import datetime as dt
import re
import threading
import uuid
from pathlib import Path
from typing import Any

import yaml

from .store import atomic_write_json, read_json

MAX_ENTRIES = 500
KINDS = ("task", "inbox", "other")
UNDO_VERBS = ("task_reopen", "inbox_reopen", "unhide", "to_task_undo", "task_unmerge")
REOPEN_AS = ("doing", "backlog", "review")     # task.py REOPEN_STATUSES: what a closed task can come back as
AUDIT_RE = re.compile(r"^(\S+) (settle|task_close|done|drop) (\S+) exits=\S+ ok=true$")


def undo_for(kind: str, key: str, ident: str | None, status: str | None = None) -> dict | None:
    """The inverse of closing an item of this kind: the verb and its arguments. A task comes back with the
    status it had before the close; without one (an older entry, an unreadable STATUS.md) it reopens as doing."""
    if kind == "task" and ident:
        return {"verb": "task_reopen", "args": {"slug": ident, **({"as": status} if status in REOPEN_AS else {})}}
    if kind == "inbox" and ident:
        return {"verb": "inbox_reopen", "args": {"id": ident}}
    if kind == "other":
        return {"verb": "unhide", "args": {"key": key}}
    return None


def item(key: str, title: str, kind: str, did: str, ident: str | None = None, status: str | None = None,
         work_kind: str | None = None) -> dict:
    """One line of the history; a task's carries whether it was a task or a stream, so the page names it"""
    out = {"key": key, "title": str(title)[:200], "kind": kind, "did": did, "ident": ident,
           "undo": undo_for(kind, key, ident, status), "undone_ms": None}
    if kind == "task" and work_kind in ("task", "stream"):
        out["work_kind"] = work_kind
    return out


class History:
    def __init__(self, state_dir: Path, clock):
        self.path = Path(state_dir) / "history.json"
        self.clock = clock
        self.lock = threading.Lock()
        data = read_json(self.path)
        self.entries: list[dict] = [e for e in data if isinstance(e, dict) and isinstance(e.get("items"), list)] \
            if isinstance(data, list) else []
        self.fresh = not self.path.exists()

    def _save(self) -> None:
        try:
            atomic_write_json(self.path, self.entries[-MAX_ENTRIES:], mode=0o600)
        except OSError:
            pass

    def add(self, verb: str, items: list[dict], at_ms: float | None = None, backfilled: bool = False,
            by: str | None = None) -> str | None:
        """One entry; `by` says who decided when it was not the person's own click (a suggestion, a batch, the
        instruction line), kept on the entry for the Activity tab, acted on nowhere"""
        if not items:
            return None
        entry = {"id": "h" + uuid.uuid4().hex[:10], "at_ms": int(self.clock() if at_ms is None else at_ms),
                 "verb": verb, "items": items, "backfilled": backfilled}
        if isinstance(by, str) and by:
            entry["by"] = by
        with self.lock:
            self.entries.append(entry)
            self.entries.sort(key=lambda e: e["at_ms"])
            del self.entries[:-MAX_ENTRIES]
            self._save()
        return entry["id"]

    def open_undo(self, verb: str, args: dict) -> dict | None:
        """The newest item not yet taken back whose undo is exactly `verb` with `args`: an undo the server
        handed out itself, so a made-up one finds nothing"""
        with self.lock:
            for entry in reversed(self.entries):
                for it in entry["items"]:
                    undo = it.get("undo") or {}
                    if not it.get("undone_ms") and undo.get("verb") == verb and undo.get("args") == args:
                        return it
        return None

    def mark(self, it: dict) -> None:
        with self.lock:
            it["undone_ms"] = int(self.clock())
            self._save()

    def mark_where(self, match: dict) -> dict | None:
        """The newest item not yet taken back whose fields are `match`; returns it, marked (an item without an
        undo of its own that goes with one that has it: the kept task's side of a merge)"""
        with self.lock:
            for entry in reversed(self.entries):
                for it in entry["items"]:
                    if not it.get("undone_ms") and all(it.get(k) == v for k, v in match.items()):
                        it["undone_ms"] = int(self.clock())
                        self._save()
                        return it
        return None

    def mark_undone(self, verb: str, ident: str) -> dict | None:
        """The newest item not yet taken back whose undo is `verb` on `ident`; returns it, marked."""
        with self.lock:
            for entry in reversed(self.entries):
                for it in entry["items"]:
                    undo = it.get("undo") or {}
                    if it.get("undone_ms") or undo.get("verb") != verb:
                        continue
                    if ident in (undo.get("args") or {}).values():
                        it["undone_ms"] = int(self.clock())
                        self._save()
                        return it
        return None

    def state(self, limit: int = 200) -> list[dict]:
        with self.lock:
            return [dict(e) for e in reversed(self.entries[-limit:])]

    # ------------------------------------------------------------ backfill from audit.log

    def backfill(self, root: Path, audit: Path) -> int:
        """Entries for the closes audit.log names whose items are still closed; only once."""
        if not self.fresh or not audit.is_file():
            return 0
        self.fresh = False
        added = 0
        for line in audit.read_text(encoding="utf-8", errors="replace").splitlines():
            m = AUDIT_RE.match(line.strip())
            if not m:
                continue
            at, verb, subject = m.groups()
            try:
                at_ms = dt.datetime.fromisoformat(at).timestamp() * 1000
            except ValueError:
                continue
            items = [x for x in (_closed_item(root, key) for key in subject.split(",")) if x]
            if items and self.add(verb, items, at_ms=at_ms, backfilled=True):
                added += 1
        if not added:
            self._save()        # the file exists now: no second backfill
        return added


def _closed_item(root: Path, key: str) -> dict | None:
    kind, _, ident = key.partition(":")
    if kind == "task" and re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", ident):
        live = next((root / "work" / k / ident / "STATUS.md" for k in ("tasks", "streams")
                     if (root / "work" / k / ident / "STATUS.md").is_file()), None)
        found = [live] if live else sorted((root / "work" / "done").glob(f"*/{ident}/STATUS.md"))
        if not found:
            return None
        title = ident
        outcome = "done"
        fm = {}
        try:
            text = found[-1].read_text(encoding="utf-8")
            fm = yaml.safe_load(text.split("---", 2)[1]) if text.lstrip().startswith(("---", "#")) and "---" in text else {}
            heading = re.search(r"^# (.+)$", text.split("---", 2)[2] if text.count("---") >= 2 else "", re.M)
            title = str((fm or {}).get("title") or (heading.group(1).strip() if heading else "") or ident)
            outcome = {"declined": "declined", "merged": "merged"}.get((fm or {}).get("outcome"), "done")
        except (OSError, yaml.YAMLError, IndexError):
            pass
        stream = (live.parent.parent.name == "streams") if live else (fm or {}).get("was_stream") is True \
            if isinstance(fm, dict) else False
        out = item(key, title, "task", "done" if live else outcome, ident, work_kind="stream" if stream else "task")
        if live:                    # opened again since: already taken back, when the file last changed
            out["undone_ms"] = int(live.stat().st_mtime * 1000)
        return out
    if kind == "inbox" and re.fullmatch(r"[0-9]{8}-[0-9]{4}-[a-z0-9][a-z0-9-]{0,119}", ident):
        folder = root / "work" / "inbox" / ident
        if not (folder / "item.yaml").is_file():
            return None
        try:
            data = yaml.safe_load((folder / "item.yaml").read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            return None
        closed_as, reopened = None, False
        for path in sorted((folder / "events").glob("*.yaml")):
            try:
                verb = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("verb")
            except (OSError, yaml.YAMLError):
                continue
            if verb in ("close", "executed", "drop", "reject"):
                closed_as, reopened = ("dropped" if verb in ("drop", "reject") else "done"), False
            elif verb == "reopen" and closed_as:
                reopened = True
        if closed_as is None:
            return None
        out = item(key, str(data.get("summary") or ident), "inbox", closed_as, ident)
        if reopened:                # opened again since: already taken back
            out["undone_ms"] = int(max(p.stat().st_mtime for p in (folder / "events").glob("*.yaml")) * 1000)
        return out
    return None
