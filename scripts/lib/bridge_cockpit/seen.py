# SPDX-License-Identifier: MIT
"""Read marks of Work through (cockpit.flow.seen): which open point the person has already looked at.

One rule: read means out of sight until something new happens to the point or its revisit day comes, whichever is
first. The mark is the cockpit's own state; the task or the inbox item itself is never changed by it.

The mark. `seen.json` in the state folder keeps, per row key (the key the flow view uses: task:<slug>,
inbox:<id>, ref:<owner/repo#n>, ...), {at, m, until, unread}: when it was read (the cockpit's clock, ms), the
movement markers of the row as they stood then (`m`, below), the revisit day the person set (Revisit ▾; none: the
interval of its kind, cockpit.flow.seen.revisit_days, counted from `at`), and whether the person marked it unread
again (Mark unread, key U). Beside it the keys the person keeps in focus (a doing task in focus counts as active).
The marks stay on this machine: a mark is written on every open, and the shared record of settled.py writes one file
per decision, so marks there would add a file to git on every click. A second machine starts with its own marks.

The markers. A point turns unread again on real movement since it was read. What moved is read from what the
server already has, never by running the Activity feed per row: each marker is a time in ms, compared with the one
the mark kept (later is new).

| marker | row | from |
|---|---|---|
| file  | a task or stream | the mtime of its STATUS.md (a note, a status change, any edit of the file) |
| doc   | a task or stream | the newest mtime of its deliverables/ folder and the entries right inside it |
| log   | a task or stream | the newest row of work/log.md that names the task: its context cell, `work/tasks/<slug>`, `work/streams/<slug>`, `task:<slug>` or `task.py <verb> <slug>`; a slug with a hyphen also as a word of the text (a one-word slug never, it would match ordinary words) |
| inbox | an inbox item    | the newest event of the item, but `describe`, `seen` and `area` (a brief, a runner's look, a routing) |
| inbox | a task           | the newest such event of an open inbox item that names the task |
| run   | any row          | the end of a finished AI run on the row (returns.py `ended_ms`) |
| code  | an issue or PR   | the time GitHub says it last changed, where a list of a page holds it (its `changed_at`) |

`cockpit.flow.seen.counts` says which kinds count: note and status both read `file` (the server cannot tell a note
from a status change without reading the file), doc `doc`, log `log`, inbox `inbox`, run `run`, code `code`.
Not movement: a brief written by describe, a theme given, a Prio or Jev order (none of them touches a marker but
the brief, which absorb() takes in), and what the person's own verbs in the cockpit move of `file`, `doc`, `log` and
`inbox`, for the points the verb names and the tasks an inbox item among them names (absorb: those markers read right
before and right after the verb, inside its lock, and the after values become the mark's where nothing new was
pending before it). Not taken in: `run` (a run ends by an agent, and a verb that ends the item takes the point off the
list anyway) and `code` (GitHub's time comes with a later read of the board, after the verb): an issue moved from the
cockpit can stand as new once the board is read again.

Limits: a row of another kind (a date, a page item) has no marker and comes back only on its revisit day; an issue
that no list of a page holds has no `code` marker either; a pull from git sets the mtimes of the files it changed,
so a STATUS.md changed on another machine counts as new here (it is new to this machine's person too).
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import math
import os
import re
import stat
import sys
import threading
from pathlib import Path
from typing import Any, Callable

COUNTS = ("note", "status", "doc", "run", "code", "log", "inbox")
# the kinds whose interval revisit_days sets: a doing task that moved lately or rests, the backlog and the ideas, a
# question or an approval of the inbox, an issue or a pull request
REVISIT_KINDS = ("active", "resting", "backlog", "question", "issue")
OPEN_READS = ("auto", "click")
MARKERS = ("file", "doc", "log", "inbox", "run", "code")
COUNT_MARKER = dict(note="file", status="file", doc="doc", run="run", code="code", log="log", inbox="inbox")
KEYS = ("enabled", "open_reads", "active_days", "revisit_days", "counts")
DEFAULT_REVISIT = {"active": 7, "resting": 14, "backlog": 30, "question": 2, "issue": 7}
DAYS_MAX = 366
# inbox verbs that are no movement of the item: a brief (describe), a runner's look (seen), a routing (area)
INBOX_QUIET = frozenset({"describe", "seen", "area"})
EVENT_RE = re.compile(r"^(\d{8}T\d{6}Z)-\d{2}-.+-([a-z_]+)\.yaml\Z")
LOG_ROW_RE = re.compile(r"^\| (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) \|")
WORD_RE = re.compile(r"(?<![a-z0-9-])[a-z0-9][a-z0-9-]*(?![a-z0-9-])")
# how a log row names a task as a task: work/tasks/<slug>, work/streams/<slug>, task:<slug>, task.py <verb> <slug>
TASK_REF_RE = re.compile(r"(?:work/(?:tasks|streams)/|task:|task\.py\s+[a-z][a-z_-]*\s+)([a-z0-9][a-z0-9-]*)")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}\Z")
INBOX_ID_RE = re.compile(r"^\d{8}-\d{4}-[a-z0-9-]{1,80}\Z")
MARKS_MAX = 3000
MS_MAX = 10 ** 14           # a time in ms past the year 5000 is no time a mark keeps
FOCUS_MAX = 200


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def defaults() -> dict:
    return {"enabled": False, "open_reads": "auto", "active_days": 7, "revisit_days": dict(DEFAULT_REVISIT),
            "counts": {k: True for k in COUNTS}}


def seen_of(value: Any) -> dict:
    """cockpit.flow.seen on top of the defaults, key by key: a bad value keeps the default of its key"""
    out = defaults()
    if not isinstance(value, dict):
        return out
    if isinstance(value.get("enabled"), bool):
        out["enabled"] = value["enabled"]
    if value.get("open_reads") in OPEN_READS:
        out["open_reads"] = value["open_reads"]
    if _is_int(value.get("active_days")) and 1 <= value["active_days"] <= DAYS_MAX:
        out["active_days"] = value["active_days"]
    days = value.get("revisit_days")
    if isinstance(days, dict):
        for k in REVISIT_KINDS:
            if _is_int(days.get(k)) and 1 <= days[k] <= DAYS_MAX:
                out["revisit_days"][k] = days[k]
    counts = value.get("counts")
    if isinstance(counts, dict):
        for k in COUNTS:
            if isinstance(counts.get(k), bool):
                out["counts"][k] = counts[k]
    return out


def check(value: Any, used: dict, where: str) -> list[str]:
    """One warning per unknown key or value seen_of replaced, naming what is used instead"""
    if not isinstance(value, dict):
        return [f"{where}: must be a mapping, got {value!r:.60}; using enabled false"]
    out = []
    for key, v in value.items():
        at = f"{where}.{str(key)[:40]}"
        if v is None:
            continue
        if key == "enabled" and not isinstance(v, bool):
            out.append(f"{at}: must be true or false, got {v!r:.40}; using {str(used['enabled']).lower()}")
        elif key == "open_reads" and v not in OPEN_READS:
            out.append(f"{at}: must be auto or click, got {v!r:.40}; using {used['open_reads']}")
        elif key == "active_days" and not (_is_int(v) and 1 <= v <= DAYS_MAX):
            out.append(f"{at}: must be a whole number of days from 1 to {DAYS_MAX}, got {v!r:.40}; using {used['active_days']}")
        elif key in ("revisit_days", "counts"):
            if not isinstance(v, dict):
                out.append(f"{at}: must be a mapping, got {v!r:.40}; using the defaults")
                continue
            for k, x in v.items():
                sub = f"{at}.{str(k)[:40]}"
                if key == "revisit_days" and k not in REVISIT_KINDS or key == "counts" and k not in COUNTS:
                    out.append(f"{sub}: unknown key, ignored")
                elif x is None:
                    continue
                elif key == "revisit_days" and not (_is_int(x) and 1 <= x <= DAYS_MAX):
                    out.append(f"{sub}: must be a whole number of days from 1 to {DAYS_MAX}, got {x!r:.40}; "
                               f"using {used['revisit_days'][k]}")
                elif key == "counts" and not isinstance(x, bool):
                    out.append(f"{sub}: must be true or false, got {x!r:.40}; using {str(used['counts'][k]).lower()}")
        elif key not in KEYS:
            out.append(f"{at}: unknown key, ignored")
    return out


def counted(counts: dict) -> set:
    """The markers the counts switch on (note and status share `file`)"""
    return {COUNT_MARKER[k] for k in COUNTS if (counts or {}).get(k, True)}


def _ms(path: Path) -> int | None:
    try:
        st = os.lstat(path)
    except OSError:
        return None
    return int(st.st_mtime * 1000)


def _newest(*values: int | None) -> int | None:
    found = [v for v in values if isinstance(v, int)]
    return max(found) if found else None


def event_ms(name: str) -> tuple[int, str] | None:
    """(ms, verb) of an inbox event's file name (inbox.py event: <UTC stamp>-<seq>-<by>-<verb>.yaml), else None"""
    hit = EVENT_RE.match(name)
    if not hit:
        return None
    try:
        at = dt.datetime.strptime(hit.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None
    return int(at.timestamp() * 1000), hit.group(2)


def _iso_ms(value: Any) -> int | None:
    """ms of an ISO time a tracker writes (2026-10-09T09:11:00Z, with or without a zone: local then)"""
    if not isinstance(value, str) or not value:
        return None
    try:
        at = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return int(at.timestamp() * 1000)


class Markers:
    """The movement markers of the rows (module doc), read from the files the Bridge keeps anyway. The log is parsed
    once per change of work/log.md; everything else is a stat or a listing per row"""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.lock = threading.Lock()
        self._log_stamp: tuple | None = None
        self._log_index: dict[str, int] = {}

    def task_folder(self, slug: str) -> Path | None:
        if not SLUG_RE.match(slug or ""):
            return None
        for kind in ("tasks", "streams"):
            folder = self.root / "work" / kind / slug
            if (folder / "STATUS.md").is_file():
                return folder
        return None

    def task(self, slug: str) -> dict:
        folder = self.task_folder(slug)
        if folder is None:
            return {}
        out = {"file": _ms(folder / "STATUS.md")}
        deliv = folder / "deliverables"
        try:
            if deliv.is_dir() and not stat.S_ISLNK(os.lstat(deliv).st_mode):
                entries = [_ms(e) for e in deliv.iterdir() if not e.name.startswith(".")]
                out["doc"] = _newest(_ms(deliv), *entries)
        except OSError:
            pass
        return {k: v for k, v in out.items() if isinstance(v, int)}

    def inbox(self, item_id: str) -> dict:
        if not INBOX_ID_RE.match(item_id or ""):
            return {}
        try:
            names = os.listdir(self.root / "work" / "inbox" / item_id / "events")
        except OSError:
            return {}
        times = [e[0] for e in map(event_ms, names) if e and e[1] not in INBOX_QUIET]
        return {"inbox": max(times)} if times else {}

    def log(self) -> dict[str, int]:
        """slug-like word -> the newest log row that names it (its context, or the word in its text), in ms"""
        path = self.root / "work" / "log.md"
        try:
            st = path.stat()
        except OSError:
            return {}
        stamp = (st.st_mtime_ns, st.st_size)
        with self.lock:
            if stamp == self._log_stamp:
                return self._log_index
        index: dict[str, int] = {}
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return {}
        for line in text.splitlines():
            hit = LOG_ROW_RE.match(line)
            if not hit:
                continue
            try:
                at = int(dt.datetime.strptime(hit.group(1), "%Y-%m-%d %H:%M").timestamp() * 1000)
            except ValueError:
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) < 4:
                continue
            text = " | ".join(cells[3:])
            # the context cell, a task reference, and a word with a hyphen (a slug of two words or more is distinctive);
            # a one-word slug counts only as a reference or the context, never as an ordinary word of the text
            words = {cells[2], *TASK_REF_RE.findall(text), *(w for w in WORD_RE.findall(text) if "-" in w)}
            for word in words:
                if index.get(word, 0) < at:
                    index[word] = at
        with self.lock:
            self._log_stamp, self._log_index = stamp, index
        return index

    def fresh(self, keys: list[str]) -> dict[str, dict]:
        """The markers of the files behind `keys` as they are now (file, doc, log of a task; inbox of an item)"""
        out: dict[str, dict] = {}
        log = None
        for key in keys:
            if key.startswith("task:"):
                slug = key[5:]
                got = self.task(slug)
                log = self.log() if log is None else log
                if slug in log:
                    got["log"] = log[slug]
                out[key] = got
            elif key.startswith("inbox:"):
                out[key] = self.inbox(key[6:])
        return out

    def build(self, rows: list[dict], returns: list[dict] | None = None, code: dict | None = None) -> dict[str, dict]:
        """The markers of every row of the model (a key once): fresh() for tasks and inbox items, an inbox item's
        events for the task it names, the end of a finished AI run, an issue's change on GitHub (`code`: key -> ms)"""
        keys = list(dict.fromkeys(r["key"] for r in rows if isinstance(r, dict) and isinstance(r.get("key"), str)))
        out = self.fresh(keys)
        for r in rows:
            if not isinstance(r, dict) or not str(r.get("key", "")).startswith("inbox:") or not r.get("task"):
                continue
            seen = (out.get(r["key"]) or {}).get("inbox")
            tkey = f"task:{r['task']}"
            if seen and tkey in out and (out[tkey].get("inbox") or 0) < seen:
                out[tkey]["inbox"] = seen
        for r in returns or []:
            ended = r.get("ended_ms") if isinstance(r, dict) else None
            if _is_int(ended) and r.get("key") in keys:
                bucket = out.setdefault(r["key"], {})
                bucket["run"] = max(bucket.get("run") or 0, ended)
        for key, ms in (code or {}).items():
            if key in keys and _is_int(ms):
                out.setdefault(key, {})["code"] = ms
        return {k: v for k, v in out.items() if v}


def code_markers(view: dict | None, pairs: dict | None) -> dict[str, int]:
    """key -> ms of the newest change GitHub names for an issue or a pull request row: its own `changed_at` where the
    row carries one, else the items of the page lists that hold it (model.page_twins)"""
    out: dict[str, int] = {}
    for key, hits in (pairs or {}).items():
        best = None
        for _pid, section, item_key in hits:
            for it in section.get("items") or []:
                if isinstance(it, dict) and key == f"ref:{it.get('id')}":
                    best = _newest(best, _iso_ms(it.get("changed_at")))
        if best is not None:
            out[key] = best
    return out


class SeenStore:
    """seen.json under the state folder: {"v": 1, "marks": {key: {at, m, until, unread}}, "focus": [key]} (module doc)"""

    def __init__(self, state_dir: Path, clock: Callable[[], float]):
        self.path = Path(state_dir) / "seen.json"
        self.clock = clock
        self.lock = threading.Lock()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        data = data if isinstance(data, dict) else {}
        marks = data.get("marks") if isinstance(data.get("marks"), dict) else {}
        # entry by entry: one a hand or an old version broke (NaN, Infinity, a huge number) is dropped, never the start
        cleaned = {k: self._clean(v) for k, v in marks.items() if isinstance(k, str) and isinstance(v, dict)}
        self._marks = {k: v for k, v in cleaned.items() if v is not None}
        focus = data.get("focus")
        self._focus = [k for k in focus if isinstance(k, str)][:FOCUS_MAX] if isinstance(focus, list) else []

    @staticmethod
    def _clean(v: dict) -> dict | None:
        """One mark as kept, or None where a time in it is no finite number"""
        def ms(x: Any) -> int | None:
            if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or abs(x) > MS_MAX:
                raise ValueError(x)
            return int(x)
        try:
            m = v.get("m") if isinstance(v.get("m"), dict) else {}
            until = v.get("until") if isinstance(v.get("until"), str) and re.match(r"^\d{4}-\d{2}-\d{2}\Z", v["until"]) else None
            return {"at": ms(v["at"]) if "at" in v else 0, "m": {k: ms(x) for k, x in m.items() if k in MARKERS},
                    "until": until, "unread": v.get("unread") is True}
        except (ValueError, TypeError, OverflowError):
            return None

    def _save(self) -> None:
        from .store import atomic_write_json      # store.py imports model.py; kept late, no cycle
        if len(self._marks) > MARKS_MAX:
            for drop in sorted(self._marks, key=lambda k: self._marks[k]["at"])[:len(self._marks) - MARKS_MAX]:
                del self._marks[drop]
        try:
            atomic_write_json(self.path, {"v": 1, "marks": self._marks, "focus": self._focus})
        except OSError as exc:
            # a full disk or a read-only folder: the marks hold in memory, the verb that wrote them still succeeds
            sys.stderr.write(f"seen.json: not saved ({exc})\n")

    def state(self) -> dict:
        with self.lock:
            return {"marks": copy.deepcopy(self._marks), "focus": list(self._focus)}

    def mark(self, key: str) -> dict | None:
        with self.lock:
            return copy.deepcopy(self._marks.get(key))

    def read(self, markers: dict[str, dict]) -> list[str]:
        """Each key of `markers` read now, as its markers stand; a revisit day the person set stays while it is ahead"""
        now = int(self.clock())
        today = dt.datetime.fromtimestamp(now / 1000).date().isoformat()
        with self.lock:
            for key, m in markers.items():
                old = self._marks.get(key) or {}
                until = old.get("until") if (old.get("until") or "") > today else None
                self._marks[key] = {"at": now, "m": dict(m or {}), "until": until, "unread": False}
            self._save()
        return list(markers)

    def unread(self, key: str) -> bool:
        """Marked unread by the person: it stays unread until it is opened again; True when it changed"""
        with self.lock:
            old = self._marks.get(key)
            if old is None:
                return False            # never opened: unread already
            if old["unread"]:
                return False
            self._marks[key] = {**old, "unread": True}
            self._save()
            return True

    def revisit(self, key: str, until: str, markers: dict) -> dict | None:
        """Read now, back on `until` (or on something new before it); the mark it had before, for an undo"""
        with self.lock:
            before = copy.deepcopy(self._marks.get(key))
            self._marks[key] = {"at": int(self.clock()), "m": dict(markers or {}), "until": until, "unread": False}
            self._save()
            return before

    def focus(self, key: str, on: bool) -> bool:
        with self.lock:
            if on and key not in self._focus:
                self._focus = [*self._focus, key][-FOCUS_MAX:]
            elif not on and key in self._focus:
                self._focus = [k for k in self._focus if k != key]
            else:
                return False
            self._save()
            return True

    def absorb(self, pre: dict[str, dict], post: dict[str, dict]) -> list[str]:
        """The person's own verb (or a brief describe wrote) moved the markers of a read point: the markers after it
        become the mark's, but only where nothing new was pending before it (every marker of `pre` at most the
        mark's), so a real change that came before the verb still counts. The keys it took in"""
        changed = []
        with self.lock:
            for key, after in post.items():
                mark = self._marks.get(key)
                if mark is None or after == mark["m"]:
                    continue
                before = pre.get(key) or {}
                if any((v or 0) > (mark["m"].get(k) or 0) for k, v in before.items()):
                    continue
                mark["m"] = {**mark["m"], **after}
                changed.append(key)
            if changed:
                self._save()
        return changed
