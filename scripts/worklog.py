#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Emit the part of work/log.md a session start actually needs.

Phase 1 says to read `work/log.md` for "last activity, current week". Nothing
enforced the second half, and reading a file reads the file: on a live instance
the log measured 405,076 bytes, roughly 155,800 tokens, four times everything
else in the always-on budget put together. The instruction was prose, and prose
does not truncate a file.

    python3 scripts/worklog.py --recent 3

Same shape as the config slice: name what the session needs, and emit exactly
that. The rest of the log stays where it is, and `/briefing` and `/archive` read
it in full when that is what they are for.

WHAT IS KEPT. Everything before the first day heading (the week line and the
focus line, which are session context in their own right) plus the N most
recent day blocks, chosen by the date in the heading rather than by position in
the file. An instance that appends day blocks at the end must get the same answer
as one that prepends them; assuming an order is how a silently wrong week
happens. A heading whose date will not parse is kept rather than dropped, because
losing a day is worse than including one too many.

Year boundaries: headings carry `DD.MM` without a year by design (the display
anchor `/archive` and `/briefing` key off). A log spanning 31.12 and 02.01 would
therefore order those two wrongly. It is left that way on purpose: the archive
resets the log weekly, so the case is rare, and the failure is one extra old
block rather than a missing recent one.

THE ROLLOVER IS NAMED HERE. `/archive` runs on request, and the reminder to run
it lived in prose; once nobody said the word, the log kept growing (one instance
reached three closed weeks and 595 KB). Every session start runs this script, so
`--recent` now LEADS with a notice whenever the log still holds a period that
`work.archive_cadence` has closed, with its row count and size, every time and
regardless of when anyone last mentioned it. `--check` says the same with exit 1,
for an audit. Neither archives: `/archive` distils memory and asks before it
writes, so naming the debt is the whole job here. The period arithmetic is
`scripts/archive-buckets.py`'s, never a second copy.

`--check-placement` names rows filed under another day's block. Every row
self-dates, so a Tuesday row under the Monday heading is detectable. It is kept
apart from `--check` on purpose: a session past midnight files tomorrow's rows
under today, which is cosmetic, and must not drown the archive signal.

THE WRITE PATH. `--append --context C --what W` puts one row into the block of
the row's own date and opens that block when it is missing, in the log's own
order. The day ends at the next `## ` heading of any kind, so a pinned section
never takes the row. Inside the day, placement is `scripts/briefing.py`'s
`log_row`, the same code `task.py` and the briefing use. Pipes and line breaks
in the text are folded, so free text can never forge a heading.

    python3 scripts/worklog.py --check
    python3 scripts/worklog.py --append --context bridge --what "decided X, because Y"

The contract lives in `scripts/tests/test_worklog.py`.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import importlib.util
import re
import sys
from pathlib import Path

LOG_PATH = Path("work") / "log.md"
DAY_HEADING = re.compile(r"^## .*?(\d{2})\.(\d{2})\s*$")
DEFAULT_RECENT = 3
#: A worklog row's own date, the frozen `| YYYY-MM-DD HH:MM |` format.
ROW_DATE = re.compile(r"^\|\s*(\d{4})-(\d{2})-(\d{2})[ T]")
HERE = Path(__file__).resolve().parent
DEFAULT_GLYPH = "📋"


def _sibling(name: str, filename: str):
    """A hyphenated or heavy sibling script, loaded by path and only when needed."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def parse_blocks(text: str) -> tuple[str, list[str]]:
    """(everything before the first `## ` heading, one string per day block)."""
    lines = text.split("\n")
    starts = [i for i, line in enumerate(lines) if line.startswith("## ")]
    if not starts:
        return text, []
    header = "\n".join(lines[: starts[0]])
    bounds = starts + [len(lines)]
    # Trailing blank lines are formatting noise, and whether a block has them
    # depends on whether it is the last one in the file. Normalising here is
    # what makes the parse position-independent, which is the property the whole
    # date-based selection rests on.
    blocks = [
        "\n".join(lines[bounds[i] : bounds[i + 1]]).rstrip()
        for i in range(len(starts))
    ]
    return header, blocks


def _dated(block: str):
    """(month, day) for a parseable heading, or None."""
    match = DAY_HEADING.match(block.split("\n", 1)[0])
    if not match:
        return None
    return int(match.group(2)), int(match.group(1))


def _sort_key(index_and_block: tuple[int, str]) -> tuple[int, int, int]:
    """Newest first, among DATED blocks only.

    It used to be asked to rank the unparseable ones too, returning `(0, 0, ...)`
    for them — which under `reverse=True` sorted them last, and `[:count]` then
    cut them first. The module's own contract says the opposite, and the two
    lived four lines apart. Ranking is now only asked of blocks that HAVE a
    rank; keeping the rest is `recent_blocks`' job.
    """
    index, block = index_and_block
    parsed = _dated(block)
    day_key = (parsed[0] * 100 + parsed[1]) if parsed else 0
    return (1 if parsed else 0, day_key, -index)


def recent_blocks(blocks: list[str], count: int) -> list[str]:
    """The `count` most recent DATED blocks, plus every undated one.

    "A heading whose date will not parse is kept rather than dropped, because
    losing a day is worse than including one too many" — the contract at the top
    of this file. Keeping it means keeping it IN ADDITION: an undated block does
    not consume one of the `count` slots, or adding a pinned section to the log
    would silently shorten the working memory by a day and nothing would say so.

    Undated blocks stay in FILE order, because that is the only order they have:
    a pinned section sits where its author put it, and there is no date to rank
    it by. Dated blocks stay newest-first as before.

    The slice is measured by the context budget, so a log that grows undated
    sections trips a declared cap rather than quietly costing every session.
    """
    dated = [(i, b) for i, b in enumerate(blocks) if _dated(b)]
    undated = [b for b in blocks if not _dated(b)]
    ordered = sorted(dated, key=_sort_key, reverse=True)
    return undated + [block for _, block in ordered[: max(0, count)]]


def render(header: str, blocks: list[str]) -> str:
    """Deterministic."""
    parts = [header.rstrip()] if header.strip() else []
    parts += [block.rstrip() for block in blocks]
    return ("\n\n".join(parts) + "\n") if parts else ""


# ---------------------------------------------------------- the rollover --

def _cadence(root: Path) -> str:
    """work.archive_cadence, resolved the way /archive resolves it."""
    raw = None
    cfg = root / "bridge-config.yaml"
    if cfg.is_file():
        try:
            import yaml

            data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
            work = data.get("work") if isinstance(data, dict) else None
            raw = work.get("archive_cadence") if isinstance(work, dict) else None
        except Exception:  # noqa: BLE001 - an unreadable config keeps the default
            raw = None
    return _sibling("_archive_buckets", "archive-buckets.py").resolve_cadence(raw)


def archive_status(text: str, cadence: str, today: _dt.date) -> dict:
    """The closed periods still in the log: labels, rows, and the bytes they hold.

    The plan is archive-buckets.py's, so this can never disagree with what
    `/archive` would actually do.
    """
    ab = _sibling("_archive_buckets", "archive-buckets.py")
    closed = [b for b in ab.plan(text, cadence, today) if b["archive"]]
    keys = {k for b in closed for k in b["day_blocks"]}
    size = 0
    for dd, mm, body in ab._blocks(text):
        if f"{dd}.{mm}" in keys:
            size += len(body.encode("utf-8"))
    return {"cadence": cadence, "periods": closed,
            "rows": sum(b["rows"] for b in closed), "bytes": size}


def misfiled_rows(text: str) -> dict:
    """{block DD.MM: {row date: count}} for rows whose own date is another day."""
    _, blocks = parse_blocks(text)
    found: dict = {}
    for block in blocks:
        head = DAY_HEADING.match(block.split("\n", 1)[0])
        if not head:
            continue
        for line in block.split("\n")[1:]:
            m = ROW_DATE.match(line)
            if m and (m.group(3), m.group(2)) != head.groups():
                key = f"{head.group(1)}.{head.group(2)}"
                iso = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
                found.setdefault(key, {})
                found[key][iso] = found[key].get(iso, 0) + 1
    return found


def _kb(size: int) -> str:
    return f"{size / 1024:.1f} KB"


def rollover_notice(status: dict) -> str:
    """One line for the session start, empty when nothing closed is left."""
    periods = status["periods"]
    if not periods:
        return ""
    labels = ", ".join(str(b["label"]) for b in periods)
    return (f"> ⚠ work/log.md holds {len(periods)} closed {status['cadence']} period(s) "
            f"not archived ({labels}): {status['rows']} rows, {_kb(status['bytes'])}. "
            "Run /archive, which distils memory first and asks before it writes.\n")


def misfiled_notice(found: dict) -> str:
    if not found:
        return ""
    total = sum(n for dates in found.values() for n in dates.values())
    where = "; ".join(f"under {k}: " + ", ".join(sorted(d)) for k, d in sorted(found.items()))
    return (f"> ⚠ work/log.md has {total} row(s) under another day's block ({where}). "
            "Move them under their own day; `worklog.py --append` opens the block.\n")


# ------------------------------------------------------------- the append --

def _cell(value: str) -> str:
    """One table cell: a pipe would split it and a line break would end the row,
    so free text from a hook can never forge a heading or a second row."""
    return " ".join(value.replace("|", "/").splitlines()).strip()


def _place_block(lines: list[str], block: list[str], key: tuple[int, int]) -> list[str]:
    """Insert a new day block where its date belongs, in the log's own direction.

    Newest first (the first heading is later than the last) puts it before the
    first older day, otherwise before the first later day, and at the end when
    there is none. Dates carry no year, so a log spanning New Year can misplace
    one block; the row inside it is still right.
    """
    heads = [(i, (int(m.group(2)), int(m.group(1))))
             for i, m in ((i, DAY_HEADING.match(ln)) for i, ln in enumerate(lines)) if m]
    newest_first = len(heads) >= 2 and heads[0][1] > heads[-1][1]
    at = next((i for i, k in heads if (k < key if newest_first else k > key)), None)
    if at is None:
        while lines and not lines[-1].strip():
            lines.pop()
        return lines + ([""] if lines else []) + block
    return lines[:at] + block + [""] + lines[at:]


def append_row(root: Path, at: _dt.datetime, context: str, what: str,
               glyph: str = DEFAULT_GLYPH, today: _dt.date | None = None) -> str:
    """One row into the block of `at`'s day, opening that block when it is missing.

    The day's range ends at the next `## ` heading of any kind, as in
    `parse_blocks`, so a pinned section after the day never takes the row.
    Inside the range, placement is `briefing.log_row`'s.
    """
    b = _sibling("_briefing_for_worklog", "briefing.py")
    log = root / LOG_PATH
    text = log.read_text(encoding="utf-8") if log.is_file() else ""
    row = f"| {at:%Y-%m-%d %H:%M} | {_cell(glyph)} | {_cell(context)} | {_cell(what)} |"
    lines = text.rstrip("\n").split("\n") if text.strip() else []
    want = (f"{at:%d}", f"{at:%m}")

    def find() -> int | None:
        return next((i for i, ln in enumerate(lines)
                     if (m := DAY_HEADING.match(ln)) and m.groups() == want), None)

    hit = find()
    if hit is None:
        block = b._new_day_block(root, at, b._weekday(at))
        if at.date() != (today or _dt.date.today()):
            block = block.replace("<details open>", "<details>")
        lines = _place_block(lines, block.split("\n"), (at.month, at.day))
        hit = find()
    end = next((j for j in range(hit + 1, len(lines)) if lines[j].startswith("## ")), len(lines))
    tail = 0
    while end - tail > hit + 1 and not lines[end - tail - 1].strip():
        tail += 1
    segment = "\n".join(lines[hit:end - tail])
    placed = b.log_row(segment, at, row, row, segment).rstrip("\n").split("\n")
    lines = lines[:hit] + placed + lines[end - tail:end] + lines[end:]
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
    return row


def _minute(value: str) -> _dt.datetime:
    try:
        return _dt.datetime.strptime(value, "%Y-%m-%d %H:%M")
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected 'YYYY-MM-DD HH:MM', got {value!r}") from None


def _date(value: str) -> _dt.date:
    try:
        return _dt.date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected 'YYYY-MM-DD', got {value!r}") from None


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Emit the recent part of work/log.md."
    )
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--recent", type=int, default=DEFAULT_RECENT)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 while the log holds a period work.archive_cadence has closed",
    )
    parser.add_argument(
        "--check-placement",
        action="store_true",
        help="exit 1 while a row sits under another day's block (cosmetic, kept apart)",
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="write one row into its own day's block, opening the block when missing",
    )
    parser.add_argument("--context", help="--append: the repo or area tag")
    parser.add_argument("--what", help="--append: what happened, and why")
    parser.add_argument("--glyph", default=DEFAULT_GLYPH, help="--append: activity glyph")
    parser.add_argument("--at", type=_minute, help="--append: 'YYYY-MM-DD HH:MM', default now")
    parser.add_argument("--today", type=_date, help="YYYY-MM-DD, for tests")
    parser.add_argument(
        "--to-string",
        action="store_true",
        help="return the text instead of printing it (used by the suite)",
    )
    args = parser.parse_args(argv)

    root = (
        Path(args.repo_root).resolve()
        if args.repo_root
        else Path(__file__).resolve().parents[1]
    )
    path = root / LOG_PATH

    if args.append:
        if not args.context or not args.what:
            parser.error("--append needs --context and --what")
        at = args.at or _dt.datetime.now().replace(second=0, microsecond=0)
        sys.stdout.write(append_row(root, at, args.context, args.what, args.glyph, args.today) + "\n")
        return 0

    if not path.is_file():
        # Phase 1 creates it from a template and continues; do not die here.
        return "" if args.to_string else 0

    text = path.read_text(encoding="utf-8", errors="replace")
    today = args.today or _dt.date.today()

    if args.check or args.check_placement:
        report = ""
        if args.check:
            report += rollover_notice(archive_status(text, _cadence(root), today))
        if args.check_placement:
            report += misfiled_notice(misfiled_rows(text))
        sys.stdout.write(report or "work/log.md: nothing to report\n")
        return 1 if report else 0

    header, blocks = parse_blocks(text)
    out = render(header, recent_blocks(blocks, args.recent))
    if args.to_string:
        return out
    try:
        notice = rollover_notice(archive_status(text, _cadence(root), today))
    except Exception:  # noqa: BLE001 - the slice is the job; a failed plan never hides it
        notice = ""
    sys.stdout.write((notice + "\n" if notice else "") + out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
