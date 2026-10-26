# SPDX-License-Identifier: MIT
"""The return channel: what became of a row handed to an agent tab ("do it", "advise", "collect context").

Every start is kept in <state_dir>/launches.json (row key, item, title, mode, when), so the page can follow
it after a restart: the newest start of a row replaces the one before, and a week later it drops out.

Where a start stands is read from what the Bridge already has, nothing is asked of the tab:

- started   no tab for it yet, within the first minutes
- working   its tab works
- asks      its tab waits for you: a dialog the terminal reports (needs-you), or a question on its screen
            (asks.py: a question mark, numbered options, or words typed in its prompt)
- idle      its tab stopped working and the words read off its screen ask nothing, or it is back at its
            shell: still, most likely through (a screen not read keeps it at asks)
- result    it left an answer: a filed inbox item (the tab's `filed_by`), a note on its inbox item
            written after the start (work/inbox/<id>/events/<UTC stamp>-...-note.yaml), or a note on its
            task since the day of the start, after the cockpit's own start line of that day, that begins
            with the result head ("Result:", "Ergebnis:")
- done      its inbox item was ended after the start (closed, executed, dropped, rejected), or its task
            moved to work/done/
- lost      no tab, no answer, and the start is a while ago

The return channel also writes to the item itself, so the task's notes and the inbox item's events carry it
for every other reader (the briefing, other sessions, a later look back): one line when it starts, and one
when it ends with an answer or without a word. What the agent wrote itself (a note on, or the close of, its
inbox item) is not written again, nor a task's close, which is its own record.
"""
from __future__ import annotations

import datetime as dt
import re
import threading
from pathlib import Path
from typing import Callable

import yaml

from .store import atomic_write_json, read_json
from .text import TABLES

try:
    from ..inbox_verbs import TERMINAL
except ImportError:  # loaded as a top-level package (tests that put scripts/lib on the path)
    from inbox_verbs import TERMINAL  # type: ignore[no-redef]

KEEP_MS = 7 * 24 * 3600 * 1000
KEEP_MAX = 60
SHOW_MAX = 12
GRACE_MS = 3 * 60 * 1000        # a start without a tab counts as starting this long
INBOX_ID_RE = re.compile(r"^\d{8}-\d{4}-[a-z0-9-]{1,80}\Z")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,80}\Z")
STAMP_RE = re.compile(r"^(\d{8}T\d{6}Z)")
ANSWER_VERBS = ("note", "close", "executed", "failed")
MODES = ("go", "report", "context")
PICK_FIELDS = ("model", "effort", "routed_by")


class Launches:
    def __init__(self, state_dir: Path, clock: Callable[[], float]):
        self.path = Path(state_dir) / "launches.json"
        self.clock = clock
        self.lock = threading.Lock()
        data = read_json(self.path)
        items = data.get("launches") if isinstance(data, dict) else None
        self._items: list = [x for x in items if isinstance(x, dict) and isinstance(x.get("key"), str)] if isinstance(items, list) else []

    def all(self) -> list:
        with self.lock:
            return [dict(x) for x in self._items]

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.path, {"v": 1, "launches": self._items})

    def record(self, entries: list) -> None:
        """Keep the starts that ran: [{key, item, title, mode, model?, effort?, routed_by?}], newest first"""
        now = self.clock()
        with self.lock:
            for e in entries:
                if not (isinstance(e.get("key"), str) and isinstance(e.get("item"), str)):
                    continue
                self._items = [x for x in self._items if x["key"] != e["key"]]
                self._items.insert(0, {"key": e["key"], "item": e["item"], "title": str(e.get("title") or e["item"])[:200],
                                       "mode": e.get("mode") if e.get("mode") in MODES else "go", "at_ms": now,
                                       # what the agent started with, when the cockpit chose it (launch.py)
                                       **{k: e[k] for k in PICK_FIELDS if isinstance(e.get(k), str)}})
            self._items = [x for x in self._items if now - float(x.get("at_ms") or 0) < KEEP_MS][:KEEP_MAX]
            self._save()

    def mark(self, key: str, stage: str) -> bool:
        """True once per start and stage: whether that stage is still to be written to the item's log"""
        with self.lock:
            for x in self._items:
                if x["key"] == key:
                    done = x.setdefault("logged", [])
                    if stage in done:
                        return False
                    done.append(stage)
                    self._save()
                    return True
            return False

    def forget(self, key: str) -> bool:
        """Take a start out of the return channel"""
        with self.lock:
            before = len(self._items)
            self._items = [x for x in self._items if x["key"] != key]
            if len(self._items) == before:
                return False
            self._save()
            return True


def _stamp_ms(name: str) -> float | None:
    m = STAMP_RE.match(name)
    if not m:
        return None
    return dt.datetime.strptime(m.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc).timestamp() * 1000


def inbox_answers(root: Path, item: str, since_ms: float) -> list:
    """The note, close, executed and failed events of an inbox item after a moment, oldest first"""
    if not INBOX_ID_RE.match(item):
        return []
    folder = Path(root) / "work" / "inbox" / item / "events"
    if not folder.is_dir():
        return []
    out = []
    for path in sorted(folder.glob("*.yaml")):
        at = _stamp_ms(path.name)
        if at is None or at < since_ms:
            continue
        try:
            ev = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if isinstance(ev, dict) and ev.get("verb") in ANSWER_VERBS:
            text = ev.get("text") or ev.get("note") or ""
            if ev["verb"] == "note" and str(text).strip().startswith(OWN_HEADS):
                continue   # the cockpit's own start and "no word" lines, in any language, are no answer
            out.append({"verb": ev["verb"], "text": str(text).strip()[:600], "at_ms": at})
    return out


NOTE_RE = re.compile(r"^- (\d{4}-\d{2}-\d{2}): (.+)$")


def _task_files(root: Path, slug: str) -> list:
    work = Path(root) / "work"
    return [work / "tasks" / slug / "STATUS.md", work / "streams" / slug / "STATUS.md",
            *sorted(work.glob(f"done/*/{slug}/STATUS.md"))]


def task_result(root: Path, slug: str, since_ms: float) -> dict | None:
    """The newest result line on a task's notes (task.py note: `- YYYY-MM-DD: <text>`) dated on or after the
    day of the start and after the cockpit's own start line of that day, if it wrote one (a note carries a day
    only: a result line of an earlier start that day stands before it), as {kind: note, text}; at_ms stays None"""
    if not SLUG_RE.match(slug):
        return None
    since = dt.date.fromtimestamp(since_ms / 1000).isoformat()
    for path in _task_files(root, slug):
        try:
            body = path.read_text(encoding="utf-8")
        except OSError:
            continue
        found = re.search(r"^## Notes\s*$(.*?)(?=^## |\Z)", body, flags=re.M | re.S)
        lines = [NOTE_RE.match(ln.strip()) for ln in (found.group(1).splitlines() if found else [])]
        notes = [m.group(2).strip() for m in lines if m and m.group(1) >= since]
        starts = [i for i, text in enumerate(notes) if text in START_LINES]
        hits = [text for text in notes[starts[-1] + 1 if starts else 0:] if text.startswith(RESULT_HEADS)]
        if hits:
            return {"kind": "note", "text": hits[-1][:600], "key": None, "at_ms": None}
    return None


def _asks(tab: dict) -> bool:
    """Whether a tab that stopped working asks something: a dialog the terminal reports, or a question read off
    its screen (asks.py). Only last words read that ask nothing, or a shell its agent left, make it idle:
    nothing read (no screens, the questions off, not read yet) may ask, as model.is_idle has it"""
    if tab.get("state") == "shell":
        return False
    ask = tab.get("ask")
    if tab.get("state") == "needs-you" or not ask:
        return True
    return bool(ask.get("yes_no") or ask.get("options") or ask.get("draft"))


def task_done(root: Path, slug: str) -> bool:
    if not SLUG_RE.match(slug):
        return False
    return any(Path(root, "work", "done").glob(f"*/{slug}/STATUS.md"))


# the verbs that end an item (inbox.py owns them) and the one that takes an end back
EVENT_VERB_RE = re.compile(r"-(" + "|".join(sorted([*TERMINAL, "reopen"])) + r")\.yaml\Z")


def _last_end(root: Path, item: str) -> tuple[bool, float | None]:
    """(ended, when) of an inbox item from its event names: ended while its last end (closed, executed,
    dropped or rejected) is not followed by a reopen; `when` is None when that name carries no stamp"""
    if not INBOX_ID_RE.match(item):
        return False, None
    folder = Path(root) / "work" / "inbox" / item / "events"
    try:
        ends = [(m.group(1), p.name) for p in sorted(folder.iterdir()) if (m := EVENT_VERB_RE.search(p.name))]
    except OSError:
        return False, None
    if not ends or ends[-1][0] == "reopen":
        return False, None
    return True, _stamp_ms(ends[-1][1])


def ended_at(root: Path, item: str) -> float | None:
    """When an inbox item was ended and not reopened since, in ms; None while it is open, and None as well
    when its end carries no readable time: "closed at an unknown moment" never counts as closed after a start"""
    ended, at = _last_end(root, item)
    return at if ended else None


_ended_at = ended_at   # the older private name


def inbox_settled(root: Path, item: str) -> bool:
    """An inbox item that is ended, and not reopened since: read from its event names, whenever it was"""
    return _last_end(root, item)[0]


def tab_settled(root: Path, tab: dict) -> str | None:
    """Whether a tab has nothing left to do, and why: its inbox item is settled ("item") or its task moved to
    work/done/ ("task"). Read from the Bridge, never from the tab"""
    item, slug = tab.get("item"), tab.get("slug")
    if isinstance(item, str) and item and inbox_settled(root, item):
        return "item"
    if isinstance(slug, str) and slug and task_done(root, slug):
        return "task"
    return None


def _tab_for(item: str, tabs: list) -> dict | None:
    mine = [t for t in tabs if not t.get("is_control") and (t.get("slug") == item or t.get("item") == item)]
    order = {"needs-you": 0, "waiting": 1, "working": 2, "shell": 3}
    mine.sort(key=lambda t: order.get(t.get("state"), 4))
    return mine[0] if mine else None


def build(launches: list, tabs: list, rows: dict, root: Path, now: float) -> list:
    """Where each start stands, newest first, at most SHOW_MAX"""
    out = []
    for x in launches[:SHOW_MAX]:
        item, at = x["item"], float(x.get("at_ms") or 0)
        tab = _tab_for(item, tabs or [])
        result, done = None, False
        if tab and tab.get("filed_by"):
            filed = rows.get(tab["filed_by"]) or {}
            result = {"kind": "filed", "text": filed.get("title") or tab["filed_by"], "key": tab["filed_by"], "at_ms": None}
        if INBOX_ID_RE.match(item):
            ended = ended_at(root, item)
            done = ended is not None and ended >= at     # closed, executed, dropped or rejected since the start
            for ev in inbox_answers(root, item, at):
                if ev["text"] or not result:
                    result = {"kind": ev["verb"], "text": ev["text"], "key": None, "at_ms": ev["at_ms"]}
        else:
            done = task_done(root, item)
            if not result:
                result = task_result(root, item, at)
        if done:
            stage = "done"
        elif result:
            stage = "result"
        elif tab and tab.get("state") == "working":
            stage = "working"
        elif tab:
            stage = "asks" if _asks(tab) else "idle"
        elif now - at < GRACE_MS:
            stage = "started"
        else:
            stage = "lost"
        out.append({"key": x["key"], "item": item, "title": x.get("title") or item, "mode": x.get("mode", "go"), "at_ms": at,
                    "stage": stage, "in_briefing": x["key"] in rows,
                    "tab": {"ref": tab["ref"], "state": tab.get("state"), "since_ms": tab.get("since_ms"),
                            "last": str(tab.get("last") or "")[:300]} if tab else None,
                    "result": result})
    return out


LINES = {code: TABLES[code]["returns"] for code in TABLES}   # the words live in text.py
OWN_HEADS = tuple(f"{w['head']}:" for w in LINES.values())
RESULT_HEADS = tuple(f"{w['result']}:" for w in LINES.values())
START_LINES = frozenset(f"{w['head']}: {w['start'].format(mode=w['mode'].get(mode, mode))}"
                         for w in LINES.values() for mode in MODES)


def _words(lang: str) -> dict:
    return LINES["de" if str(lang).startswith("de") else "en"]


def start_line(mode: str, lang: str) -> str:
    w = _words(lang)
    return f"{w['head']}: {w['start'].format(mode=w['mode'].get(mode, mode))}"


def log_line(r: dict, lang: str) -> tuple[str, str, str] | None:
    """(task|inbox, id, text) to write for a start's stage, or None when nothing new is to be said"""
    w = _words(lang)
    item, stage, result = r["item"], r["stage"], r.get("result") or {}
    kind = "inbox" if INBOX_ID_RE.match(item) else "task"
    if stage == "lost":
        return kind, item, f"{w['head']}: {w['lost']}"
    if stage == "result" and result.get("kind") == "filed":
        return kind, item, f"{w['head']}: {w['filed'].format(text=' '.join(str(result.get('text') or '').split())[:160], key=result.get('key'))}"
    return None
