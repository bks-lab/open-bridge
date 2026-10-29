#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Search every task, stream and closed task, the log and its archive, and get the files ranked.

    python3 scripts/work-find.py gateway september
    python3 scripts/work-find.py --json "invoice onboarding"
    python3 scripts/work-find.py --history --transcripts ~/Transcripts "gateway retry"

The words are plain text, never a pattern, matched case-insensitively. A file (the folder of one slug) is a
hit when its slug, its title and its lines hold every word between them; files whose slug or title holds
every word come first, then those with a hit in their STATUS.md, then the rest, open before closed. A log
row belongs to the file its context column or its text names. `video/` and `deliverables/` folders, hidden
files and anything outside the Bridge are never read. Uses `rg` when it is installed, plain Python when not,
with the same answer either way.

With --history it answers when something was done or discussed instead: every line of the log and its archive,
the meeting notes and folders, the closed tasks and (with --transcripts) the raw transcripts that holds every word,
each with its day, newest first.

For a page that charts the log over any range (the cockpit's /api/logrange), --rows lists every row of the log and
its archive with its day and glyph (a row that stands in two files once), --events every meeting, closed task and
transcript as one entry each (with words only those that hold every one); both always answer in JSON. --since and
--until (days, both included) narrow --history, --rows and --events.

    python3 scripts/work-find.py --rows --since 2026-10-01 --until 2026-10-31
    python3 scripts/work-find.py --events --transcripts ~/Transcripts -- gateway

The logic lives in scripts/lib/work_find.py; the cockpit's /api/find and /api/history run this command. Exit 0 with or
without hits, 2 for a query it refuses (shorter than 2 or longer than 200 characters, a control character).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.dont_write_bytecode = True
if str(ROOT / "scripts" / "lib") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import work_find  # noqa: E402


def day(value: str) -> str:
    """A day as YYYY-MM-DD, a real one"""
    try:
        if work_find.DAY_RE.match(value):
            return dt.date.fromisoformat(value).isoformat()
    except ValueError:
        pass
    raise argparse.ArgumentTypeError(f"not a day: {value!r}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="work-find.py", description="Search the files of the work system.")
    p.add_argument("--root", type=Path, default=ROOT, help="the Bridge root (default: this checkout)")
    p.add_argument("--json", action="store_true", help="the whole answer as one JSON object")
    p.add_argument("--engine", choices=("auto", "rg", "python"), default="auto",
                   help="auto: rg when installed, else Python (default)")
    p.add_argument("--history", action="store_true",
                   help="when it was done or discussed: every line with every word, by day, newest first")
    p.add_argument("--transcripts", type=Path, default=None, help="--history: the folder of the raw meeting transcripts")
    p.add_argument("--meetings", default=work_find.MEETINGS_DIR,
                   help=f"--history: the meeting folders below the root (default {work_find.MEETINGS_DIR})")
    p.add_argument("--rows", action="store_true",
                   help="every row of the log and its archive with its day, newest first (no words)")
    p.add_argument("--events", action="store_true",
                   help="the meetings, closed tasks and transcripts one entry each, newest first (words optional)")
    p.add_argument("--since", type=day, default=None, help="--history, --rows, --events: from this day (YYYY-MM-DD)")
    p.add_argument("--until", type=day, default=None, help="--history, --rows, --events: up to this day, included")
    p.add_argument("query", nargs="*", help="the words to find")
    args = p.parse_args(argv)
    if not (args.query or args.rows or args.events):
        p.error("the words to find are required")
    try:
        if args.rows:
            result = work_find.log_rows(args.root, since=args.since, until=args.until)
        elif args.events:
            result = work_find.history_events(args.root, transcripts=args.transcripts, meetings=args.meetings.strip("/"),
                                              query=" ".join(args.query) if args.query else None,
                                              since=args.since, until=args.until)
        elif args.history:
            result = work_find.history(args.root, " ".join(args.query), transcripts=args.transcripts,
                                       meetings=args.meetings.strip("/"), since=args.since, until=args.until)
        else:
            result = work_find.find(args.root, " ".join(args.query), engine=args.engine)
    except ValueError as exc:
        print(f"work-find: {exc}", file=sys.stderr)
        return 2
    if args.json or args.rows or args.events:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(work_find.render_history(result) if args.history else work_find.render(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
