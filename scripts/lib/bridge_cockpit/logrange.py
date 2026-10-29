# SPDX-License-Identifier: MIT
"""The log page's time range (GET /api/logrange): the rows of the log and its archive for any range of days, the own
commits of the page's commits section over it, and the history beside the log (meetings, closed tasks, transcripts)
one entry each. Read only, every read a command through the runner (argv lists, timeouts), as /api/timeline.

    GET /api/logrange[?from=YYYY-MM-DD][&to=YYYY-MM-DD][&commits=<section id>]
        {ok, from, to, first, today, rev, offset, total, days, groups [{name, task, about_task, about_path, kind}],
         glyphs, rows [[day, time, group, glyph]], repos [{repo, branch, url, ts}] | null, repos_from, skipped}
    GET /api/logrange?ids=<id,...>&rev=<rev>                 {ok, rev, texts {id: text}}
    GET /api/logrange?q=<words>&rev=<rev>[&from=…][&to=…]   {ok, rev, q, hits [id, ...]}
    GET /api/logrange?sources=other[&from=…][&to=…][&q=<words>]
        {ok, from, to, transcripts, events [{date, time, kind, source, path, folder}]}

`from` defaults to the first day of the log, `to` to today; both days are in the range. The rows come newest first and
compact, without their text: a row is its day, time, group and glyph as indexes into `days`, `groups` and `glyphs`,
its id `offset` plus its place, and a group carries once what every row of it needs: the task it is (`task`, an open
task or stream of that name) or is about (`about_task`, `about_path` for a closed one) and its work kind, the lookup
the collector makes for the rows of the day (collector.about_of). A year of 8 000 rows of long text answers in under
200 KB instead of some 8 MB. The text comes by id, a page of the list at a time; the words are found here, in the
text and the context case folded as the page's own filter reads a row, and come back as ids. Ids and words name rows
of one answer: a `rev` the log has changed since is refused (Stale, 409). The page buckets the rows itself
(scripts/web/logic.js), so a zoom or another bar width never asks again.

Kept: the whole log is read once (scripts/work-find.py --rows) and kept until a file of it changes (the size and
the time of every file of work/log.md and work/archive/, a stat walk of a few hundred files); a range is cut from
it. The commits (scripts/briefing.py commits) and the other history (scripts/work-find.py --events) are kept a
minute per range and words, git and the transcripts having no cheap mark of change. The commits reach back a week
at least and up to today, so the rail can name the repositories that were busy in the last seven days and are quiet
in the range.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import threading

from .. import work_find
from . import origin as og
from .collector import about_of

DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\Z")
SECTION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
TASK_RE = re.compile(r"^[a-z0-9][a-z0-9-]*\Z")
SOURCES = ("log", "other")
REV_RE = re.compile(r"^[0-9a-f]{12}\Z")
IDS_MAX = 200           # the texts one request asks for: two pages of the list
TIMEOUT = 30            # one read of the whole log, of the commits or of the other history
KEEP_S = 60             # how long the commits and the other history of one range stay kept
KEEP_MAX = 16           # ranges kept of each
WEEK = 7


class Refused(ValueError):
    """A parameter the range does not take: its name and why"""

    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field = field


def _day(value: str, field: str) -> str | None:
    if not value:
        return None
    try:
        if DAY_RE.match(value):
            return dt.date.fromisoformat(value).isoformat()
    except ValueError:
        pass
    raise Refused(field, "not a day (YYYY-MM-DD)")


def check_days(one) -> dict:
    """`from` and `to` of a request as {since, until}, each a day or None; Refused for one that is no day or a range
    that ends before it starts (also the timeline's, /api/timeline)"""
    since, until = _day(one("from"), "from"), _day(one("to"), "to")
    if since and until and until < since:
        raise Refused("to", "the range ends before it starts")
    return {"since": since, "until": until}


def check(one) -> dict:
    """The parameters of a request as {since, until, sources, q, commits, ids, rev}; Refused for one it does not take"""
    days = check_days(one)
    since, until = days["since"], days["until"]
    sources = one("sources") or "log"
    if sources not in SOURCES:
        raise Refused("sources", f"one of {', '.join(SOURCES)}")
    q, commits, rev, ids = one("q") or None, one("commits") or None, one("rev") or None, one("ids") or None
    if rev is not None and (sources != "log" or not REV_RE.match(rev)):
        raise Refused("rev", "the rev of an answer of the log")
    if ids is not None:
        parts = ids.split(",")
        if len(parts) > IDS_MAX or not all(x.isdigit() and len(x) <= 7 for x in parts):
            raise Refused("ids", f"up to {IDS_MAX} row ids, comma separated")
        ids = [int(x) for x in parts]
    if q is not None:
        try:
            q, _ = work_find.check_query(q)
        except ValueError as exc:
            raise Refused("q", str(exc)) from None
    if sources == "log" and (q is not None or ids is not None) and rev is None:
        raise Refused("rev", "words and ids name rows of one answer: its rev")
    if commits is not None and (sources != "log" or not SECTION_RE.match(commits)):
        raise Refused("commits", "a section id, only with the log")
    return {"since": since, "until": until, "sources": sources, "q": q, "commits": commits, "ids": ids, "rev": rev}


def _last_line(run) -> dict | None:
    try:
        data = json.loads(run.out.strip().splitlines()[-1]) if run.ok else None
    except (ValueError, IndexError):
        return None
    return data if isinstance(data, dict) else None


class Stale(ValueError):
    """Ids or words that name rows of an answer the log has changed since"""


class LogRange:
    """The reads of /api/logrange and what they keep; one per cockpit (app.logrange)"""

    def __init__(self, app):
        self.app = app
        self.lock = threading.Lock()
        self.rows_kept: tuple | None = None     # (mark of the log's files, {first, rows})
        self.kept: dict = {}                    # (what, range, words) -> (when it was read in s, answer)

    # ---- the log

    def mark(self) -> tuple:
        """What changes when the log or its archive does: the size and time of each of their files"""
        out = []
        root = self.app.root
        try:
            st = (root / "work" / "log.md").stat()
            out.append(("log.md", st.st_size, st.st_mtime_ns))
        except OSError:
            pass
        base = root / "work" / "archive"
        for here, dirs, files in os.walk(base, followlinks=False):
            dirs.sort()
            for name in sorted(files):
                try:
                    st = os.stat(os.path.join(here, name), follow_symlinks=False)
                except OSError:
                    continue
                out.append((os.path.relpath(os.path.join(here, name), base), st.st_size, st.st_mtime_ns))
        return tuple(out)

    def all_rows(self) -> dict:
        """{first, rows} of the whole log, read again only when a file of it changed; ValueError when it cannot be read"""
        mark = self.mark()
        with self.lock:
            if self.rows_kept and self.rows_kept[0] == mark:
                return self.rows_kept[1]
        app = self.app
        argv = [app.runner.python, app.runner.script("scripts/work-find.py"), "--root", str(app.root), "--rows", "--json"]
        run = app.run(argv, TIMEOUT)
        data = _last_line(run)
        if not data or not isinstance(data.get("rows"), list):
            raise ValueError((run.err or run.out or "the log did not answer").strip()[-200:])
        known = og.known_from_root(app.root, fresh=True)   # read again with the log: a task closed since counts
        about: dict = {}
        rows = []
        for r in data["rows"]:
            group = str(r.get("context") or "")
            if group not in about:
                kind = og.work_kind(group, known)
                # a row whose context is an open task or stream leads there (as briefing.sec_activity); else the task,
                # stream or closed one it is about (collector.about_of), so its file opens from the row
                task = group if TASK_RE.match(group) and kind in ("task", "stream") else None
                found = about_of({"group": group, "task": task}, app.root, known)
                about[group] = {"task": task, "about_task": found["about_task"], "about_path": found["about_path"],
                                "kind": og.work_kind(task or found["about_task"], known)}
            rows.append({"date": r.get("date"), "time": r.get("time"), "glyph": r.get("glyph") or None, "group": group or None,
                         "title": str(r.get("text") or "").replace("**", "")})
        # what the word filter reads of a row: its context and its text as the log holds it, case folded, the rule the
        # history (work_find.history, Every day's list) finds a log row by
        low = [f"{r.get('context') or ''} {r.get('text') or ''}".lower() for r in data["rows"]]
        rows = app.scrub_tree(rows)
        rev = hashlib.sha256(repr(mark).encode("utf-8")).hexdigest()[:12]
        kept = {"first": data.get("first"), "rows": rows, "low": low, "about": app.scrub_tree(about), "rev": rev}
        with self.lock:
            self.rows_kept = (mark, kept)
        return kept

    # ---- what is kept a minute

    def _kept(self, key: tuple, read):
        now = self.app.clock() / 1000
        with self.lock:
            hit = self.kept.get(key)
            if hit and now - hit[0] < KEEP_S:
                return hit[1]
        value = read()
        with self.lock:
            if len(self.kept) >= KEEP_MAX:
                self.kept.pop(min(self.kept, key=lambda k: self.kept[k][0]))
            self.kept[key] = (now, value)
        return value

    def commits(self, section: str, since: str, until: str) -> dict | None:
        """{repos, skipped} of the profile's commits section over the range, None when it cannot be read"""
        app = self.app

        def read():
            argv = [app.runner.python, app.runner.script("scripts/briefing.py"), "--root", str(app.root), "commits"]
            profile = app.collector.view_profile()
            argv += ([profile] if profile else []) + ["--section", section, "--since", since, "--until", until]
            data = _last_line(app.run(argv, TIMEOUT))
            if not data or not isinstance(data.get("repos"), list):
                return None
            return app.scrub_tree({"repos": data["repos"], "skipped": data.get("skipped") or []})
        return self._kept(("commits", section, since, until), read)

    def events(self, since: str, until: str, q: str | None) -> dict:
        """{transcripts, events} of the other history over the range; ValueError when it cannot be read"""
        app = self.app

        def read():
            argv = [app.runner.python, app.runner.script("scripts/work-find.py"), "--root", str(app.root), "--events",
                    "--json", "--meetings", app.cfg.meetings]
            transcripts = work_find.transcript_root(app.cfg.transcripts)
            argv += (["--transcripts", str(transcripts)] if transcripts else []) + ["--since", since, "--until", until]
            run = app.run(argv + (["--", q] if q else []), TIMEOUT)
            data = _last_line(run)
            if not data or not isinstance(data.get("entries"), list):
                raise ValueError((run.err or run.out or "the history did not answer").strip()[-200:])
            return app.scrub_tree({"transcripts": data.get("transcripts") is True, "events": data["entries"]})
        return self._kept(("events", since, until, q), read)

    # ---- the answer

    def view(self, params: dict) -> dict:
        """The answer of one request (check); ValueError when the log or the history cannot be read"""
        today = dt.date.fromtimestamp(self.app.clock() / 1000).isoformat()
        if params["sources"] == "other":
            since, until = params["since"] or "1970-01-01", params["until"] or today
            got = self.events(since, until, params["q"])
            return {"ok": True, "from": params["since"], "to": until, **got}
        log = self.all_rows()
        rows = log["rows"]
        if params["rev"] is not None and params["rev"] != log["rev"]:
            raise Stale("the log changed since this answer; ask for the range again")
        if params["ids"] is not None:
            return {"ok": True, "rev": log["rev"], "texts": {str(i): rows[i]["title"] for i in params["ids"] if i < len(rows)}}
        since, until = params["since"] or log["first"] or today, params["until"] or today
        # the rows stand newest first, so the days of a range are one run of them
        at = [i for i, r in enumerate(rows) if since <= (r["date"] or "") <= until]
        lo, hi = (at[0], at[-1] + 1) if at else (0, 0)
        if params["q"] is not None:
            words = work_find.check_query(params["q"])[1]
            return {"ok": True, "rev": log["rev"], "q": params["q"],
                    "hits": [i for i in range(lo, hi) if all(w in log["low"][i] for w in words)]}
        days, groups, glyphs, packed = [], [], [], []
        index: dict = {"d": {}, "g": {}, "y": {}}

        def ref(kind, value, out, entry):
            if value not in index[kind]:
                index[kind][value] = len(out)
                out.append(entry)
            return index[kind][value]
        for r in rows[lo:hi]:
            packed.append([ref("d", r["date"], days, r["date"]), r["time"],
                           ref("g", r["group"], groups, {"name": r["group"], **log["about"].get(r["group"] or "", {})}),
                           ref("y", r["glyph"], glyphs, r["glyph"])])
        out = {"ok": True, "from": since, "to": until, "first": log["first"], "today": today, "rev": log["rev"], "offset": lo,
               "total": hi - lo, "days": days, "groups": groups, "glyphs": glyphs, "rows": packed,
               "repos": None, "repos_from": None, "skipped": []}
        if params["commits"]:
            week = (dt.date.fromisoformat(today) - dt.timedelta(days=WEEK - 1)).isoformat()
            back = min(since, week)
            got = self.commits(params["commits"], back, max(until, today))
            if got is not None:
                out.update(repos=got["repos"], repos_from=back, skipped=got["skipped"])
        return out
