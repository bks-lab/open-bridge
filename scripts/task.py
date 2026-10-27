#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Small write commands for a task's STATUS.md.

    python3 scripts/task.py priority <slug> {P0,P1,P2,P3}
    python3 scripts/task.py note <slug> <text>
    python3 scripts/task.py close <slug> [--reason TEXT] [--declined | --merged-into KEEP] [--json]
    python3 scripts/task.py reopen <slug> [--as doing|backlog] [--note TEXT] [--json]
    python3 scripts/task.py merge <keep> --from <slug> [--heading TEXT] [--json]
    python3 scripts/task.py unmerge <keep> --from <slug> [--as doing|backlog|review] [--json]
    python3 scripts/task.py review [slug ...] [--all] [--fresh] [--keep SLUG ...] [--json]
    python3 scripts/task.py wait <slug> --until YYYY-MM-DD [--on TEXT] | --clear [--json]
    python3 scripts/task.py new [slug] --headline TEXT | --from-inbox ID [--status backlog|doing] [--json]
    python3 scripts/task.py log [--] <context> <text>
    python3 scripts/task.py next <slug> [--] <text> | --clear [--json]
    python3 scripts/task.py brief <slug> --brief-json JSON [--basis HEX] [--edited] | --mark-edited [--json]

Rewrites only the ``priority:`` line inside the YAML frontmatter of
work/tasks/<slug>/STATUS.md or work/streams/<slug>/STATUS.md (the key is added
after ``status:`` when absent), sets ``last_updated:`` to today, leaves every
other byte alone (comments, quoting, order), then regenerates work/board.md with
scripts/gen-board.py. An unknown slug or value exits 1 without writing.

``note`` appends ``- YYYY-MM-DD: <text>`` to the ``## Notes`` section of the body,
creating it at the end when there is none, and sets ``last_updated:``; nothing
else changes.

Comment and blank lines above the opening ``---`` (the shipped template starts
with a ``# yaml-language-server:`` line) are kept byte for byte.

``close`` is the 3-step close of docs/work-system.md as one command: the task
gets ``status: done``, ``closed:``, ``outcome: declined`` with ``--declined``, loses
``blocked_by``/``blocked_since``, gets a dated note with the reason; then the
directory moves to work/done/YYYY-MM/<slug>/ (a plain move, no git), the board is
regenerated and one row goes into today's block of work/log.md. A stream, an
unknown slug or a task already under work/done/ is refused without writing.
``--merged-into KEEP`` closes it as merged into another task instead (``outcome: merged``,
``merged_into: KEEP``, the note "Merged into KEEP"); it excludes ``--declined``.

``merge`` makes one task of two about the same thing: the task ``--from`` names is closed as merged into
``<keep>``, and ``<keep>`` gets one section with what it said (its headline, its goal, every line of its
notes and every open step, as text) and the paths of its STATUS.md and of up to 20 of its documents at their
new place under work/done/ (the folder moves whole, nothing is copied), the same paths in ``related:``
tagged ``# merged-from: <slug>``, and a dated note. Everything is checked before the first write, and when
the close fails the section and the related lines come out again. ``unmerge`` takes it back: the section and
the tagged related lines go, the merged task opens again (``--as``), and both tasks get a note.

``next`` sets the task's next step, ``next: {what: <text>}`` as the schema has it (a step written
before, also as a block mapping, goes whole), with ``last_updated:`` and a dated "Next step: <text>" note,
so the step carries the day it was taken over; ``--clear`` takes it away. The cockpit's files view writes
it only when the person takes over a suggested step.

``brief`` writes the task's brief (lib/bridge_cockpit/card_fields.py: goal, story, acceptance, by, at) as
the nested ``brief:`` block of the frontmatter, written or replaced as a whole where it stands (appended
before the closing ``---`` when there is none), with ``basis`` (brief_basis of the file as written) and
``edited`` (false, ``--edited`` for a person's write). A brief the gate finds anything wrong with is refused,
and so is one whose ``--basis`` (the text it was written against) no longer matches the file. Every other byte
stays, ``last_updated`` too: a brief is no activity on the task. ``--mark-edited`` only turns ``edited:``
true in a block a person changed by hand (the cockpit's describe pass finds those), nothing else.

``log`` writes one row into today's block of work/log.md, for a decision on a row that has no task or
inbox item of its own (a GitHub issue, a deadline): the cockpit keeps the person's sentence there.

``reopen`` is the inverse of close, for a close by mistake or a task that still has to
be done: the newest work/done/*/<slug>/ moves back to work/tasks/<slug>/, ``status``
becomes doing (or ``--as backlog``), ``closed:`` and ``outcome:`` go, a dated
"Reopened" note joins the notes (the close note stays, so the history reads), the
board is regenerated and one log row is written. A slug that is open is refused.
``merged_into`` goes as well.

``review`` recommends per task in doing or review (``--backlog`` adds backlog,
named slugs are reviewed whatever their status): close, continue, waiting, stale
or unclear. It never changes a task. Evidence is
gathered cheaply (frontmatter, open steps, log rows, last commit, open inbox
items, GitHub references resolved in ONE GraphQL call); a small model judges all
tasks needing a verdict in ONE call. Two signals are computed before any model:
own_refs_closed (every tracked issue/PR closed as completed or merged) and
blocker_resolved (everything blocked_by names is closed or merged); either one
recommends closing, whatever the model says. Only ``unclear`` answers
go to a stronger model in a second call. Verdicts are cached in
.bridge/task-review.json by a hash of the evidence. Model: docs/bridge-cockpit.md § 3.

The allowed values are the enum in work/templates/_schema.status.yaml.
The contract lives in ``scripts/tests/test_task.py`` and ``test_task_review.py``.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import errno
import hashlib
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from lib import ai_services as ai
from lib.bridge_cockpit.card_fields import brief_basis, validate_brief
PRIORITIES = ("P0", "P1", "P2", "P3")      # work/templates/_schema.status.yaml: priority.enum


def find_status(root: Path, slug: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", slug):
        raise ValueError(f"not a task slug: {slug!r}")
    for kind in ("tasks", "streams"):
        path = root / "work" / kind / slug / "STATUS.md"
        if path.is_file():
            return path
    raise ValueError(f"no task or stream {slug!r} under {root / 'work'}")


def set_priority(text: str, value: str, today: str) -> str:
    """Edit the frontmatter lines only; the body and all other bytes stay as they are."""
    return set_fields(text, [("priority", value, "status"), ("last_updated", today, None)])


NOTES = re.compile(r"^## Notes\s*$")


def add_note(text: str, note: str, today: str) -> str:
    """Append a dated line to the notes section of the body; the frontmatter gets last_updated."""
    note = " ".join(note.split())
    if not note:
        raise ValueError("empty note")
    nl = "\r\n" if "\r\n" in text.split("\n", 1)[0] + "\n" else "\n"
    line = f"- {today}: {note}{nl}"
    lines = set_fields(text, [("last_updated", today, None)]).splitlines(keepends=True)
    start = next((i for i, ln in enumerate(lines) if NOTES.match(ln.rstrip("\r\n"))), None)
    if start is None:
        return "".join(lines).rstrip("\r\n") + f"{nl}{nl}## Notes{nl}{nl}" + line
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    at = end
    while at > start + 1 and not lines[at - 1].strip():
        at -= 1
    if not lines[at - 1].endswith("\n"):
        lines[at - 1] += nl
    if at == start + 1:
        lines.insert(at, nl)      # a blank line under the heading, as a new section has
        at += 1
    lines.insert(at, line)
    return "".join(lines)


def set_fields(text: str, fields: list) -> str:
    """Set (key, value, insert-after-key) in the frontmatter; the body and all other bytes stay."""
    lines = text.splitlines(keepends=True)
    start = 0
    while start < len(lines) and (not lines[start].strip() or lines[start].startswith("#")):
        start += 1            # a leading "# yaml-language-server: ..." line stays as it is
    if start >= len(lines) or lines[start].rstrip("\r\n") != "---":
        raise ValueError("STATUS.md has no frontmatter")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].rstrip("\r\n") == "---"), None)
    if end is None:
        raise ValueError("STATUS.md frontmatter is not closed")
    nl = "\r\n" if lines[start].endswith("\r\n") else "\n"

    def find(key: str) -> int | None:
        return next((i for i in range(start + 1, end) if re.match(rf"{key}:(\s|$)", lines[i])), None)

    def put(key: str, new: str, after: str | None = None) -> None:
        nonlocal end
        i = find(key)
        if i is not None:
            lines[i] = f"{key}: {new}" + (lines[i][len(lines[i].rstrip("\r\n")):] or nl)
            return
        at = find(after) if after else None
        pos = at + 1 if at is not None else end
        lines.insert(pos, f"{key}: {new}{nl}")
        end += 1

    for key, value, after in fields:
        put(key, value, after=after)
    return "".join(lines)


def regenerate_board(root: Path) -> None:
    spec = importlib.util.spec_from_file_location("gen_board", ROOT / "scripts" / "gen-board.py")
    mod = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode = True
    spec.loader.exec_module(mod)
    mod.ROOT = root
    mod.TASKS, mod.STREAMS, mod.DONE = (root / "work" / n for n in ("tasks", "streams", "done"))
    mod.main([])


def stale_links(root: Path, old: str) -> list[str]:
    """Files under work/ whose Markdown links still point at `old`. Reported, never rewritten here."""
    try:
        spec = importlib.util.spec_from_file_location("check_edges", ROOT / "scripts" / "check-edges.py")
        mod = importlib.util.module_from_spec(spec)
        sys.dont_write_bytecode = True
        spec.loader.exec_module(mod)
        return mod.links_into(root, old)
    except Exception:  # noqa: BLE001 - a missing hint must never fail a close
        return []


def remove_fields(text: str, keys) -> str:
    """Drop `key:` lines of the frontmatter, with their indented continuation lines."""
    lines = text.splitlines(keepends=True)
    start = 0
    while start < len(lines) and (not lines[start].strip() or lines[start].startswith("#")):
        start += 1
    end = next((i for i in range(start + 1, len(lines)) if lines[i].rstrip("\r\n") == "---"), len(lines))
    drop, i = set(), start + 1
    while i < end:
        if any(re.match(rf"{k}:(\s|$)", lines[i]) for k in keys):
            drop.add(i)
            i += 1
            while i < end and lines[i][:1] in (" ", "\t") and lines[i].strip():
                drop.add(i)
                i += 1
            continue
        i += 1
    return "".join(ln for n, ln in enumerate(lines) if n not in drop)


_MODULES: dict = {}


def _module(name: str, path: Path):
    if name not in _MODULES:
        spec = importlib.util.spec_from_file_location(f"task_{name}", path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod      # a module that looks itself up by name finds itself
        sys.dont_write_bytecode = True
        spec.loader.exec_module(mod)
        _MODULES[name] = mod
    return _MODULES[name]


def _briefing():
    """briefing.py owns the log row placement and the step/log extraction the dashboard shows."""
    return _module("briefing", ROOT / "scripts" / "briefing.py")


LOG_GLYPH = "📋"


def append_log_row(root: Path, now: dt.datetime, context: str, what: str) -> None:
    """One `| YYYY-MM-DD HH:MM | glyph | context | what |` row in today's day block (created when missing),
    placed the way the briefing places its own row."""
    b = _briefing()
    log = root / "work" / "log.md"
    text = log.read_text(encoding="utf-8") if log.is_file() else ""
    row = f"| {now:%Y-%m-%d %H:%M} | {LOG_GLYPH} | {context} | {what.replace('|', '/')} |"
    new = b.log_row(text, now, row, row, b._new_day_block(root, now, b._weekday(now)))
    log.write_text(new if text else new.lstrip("\n"), encoding="utf-8")


# ---------------------------------------------------------------- close

MERGE_SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,79}")   # _schema.status.yaml merged_into.pattern


def close_task(root: Path, slug: str, *, reason: str | None = None, declined: bool = False,
               stream: bool = False, merged_into: str | None = None, now: dt.datetime | None = None) -> dict:
    """The 3-step close of docs/work-system.md: fields and note, move to work/done/YYYY-MM/, board, log row.
    stream also ends a stream: a stream never completes on its own, but a person may end one (the customer left,
    the chance passed). It closes like a task and keeps was_stream, so reopen puts it back under work/streams/.
    merged_into closes it as merged into that task (outcome: merged), never together with declined."""
    now = now or dt.datetime.now()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", slug):
        raise ValueError(f"not a task slug: {slug!r}")
    if merged_into is not None:
        if declined:
            raise ValueError("a task closes as merged or as declined, not both")
        if not MERGE_SLUG_RE.fullmatch(merged_into):
            raise ValueError(f"not a task slug: {merged_into!r}")
    work = root / "work"
    src = work / "tasks" / slug
    was_stream = False
    if not (src / "STATUS.md").is_file() and stream and (work / "streams" / slug / "STATUS.md").is_file():
        src, was_stream = work / "streams" / slug, True
    if not (src / "STATUS.md").is_file():
        if (work / "streams" / slug / "STATUS.md").is_file():
            raise ValueError(f"{slug} is a stream: streams never close on their own (--stream ends one)")
        if any((work / "done").glob(f"*/{slug}/STATUS.md")):
            raise ValueError(f"{slug} is already closed (work/done/)")
        raise ValueError(f"no task {slug!r} under {work / 'tasks'}")
    dest = work / "done" / f"{now:%Y-%m}" / slug
    if dest.exists():
        raise ValueError(f"{dest.relative_to(root)} exists already")
    today = now.date().isoformat()
    reason = " ".join((reason or "").split())
    path = src / "STATUS.md"
    text = path.read_bytes().decode("utf-8")
    fields = [("status", "done", None), ("closed", f'"{today}"', "status")]
    if declined:
        fields.append(("outcome", "declined", "closed"))
    if merged_into:
        fields += [("outcome", "merged", "closed"), ("merged_into", merged_into, "outcome")]
    if was_stream:
        fields.append(("was_stream", "true", "closed"))
    # a normal close drops an old "outcome: declined", which would otherwise survive and mislabel the task
    text = remove_fields(text, ("merged_into",))
    text = remove_fields(set_fields(text, fields), ("blocked_by", "blocked_since")
                         + (() if declined or merged_into else ("outcome",)))
    word = "Declined" if declined else "Closed"
    said = ("Stream ended, declined" if declined else "Stream ended") if was_stream else word
    if merged_into:
        said = f"Merged into {merged_into}"
    text = add_note(text, f"{said}: {reason}" if reason else said, today)
    # Move first, then write at the destination: a move that fails leaves the task untouched in place.
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.rename(src, dest)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        shutil.move(str(src), str(dest))
    try:
        (dest / "STATUS.md").write_bytes(text.encode("utf-8"))
    except OSError:
        os.rename(dest, src)                        # back where it was, as it was
        raise
    warnings = []
    try:
        with contextlib.redirect_stdout(sys.stderr):   # stdout carries the --json answer only
            regenerate_board(root)
    except Exception as exc:  # noqa: BLE001 - the task is closed; a stale board is a warning
        warnings.append(f"work/board.md not regenerated: {exc}")
    try:
        append_log_row(root, now, slug, (f"merged into {merged_into}" if merged_into else word.lower())
                       + (f": {reason}" if reason else ""))
    except Exception as exc:  # noqa: BLE001 - the task is closed; a missing row is a warning
        warnings.append(f"work/log.md row not written: {exc}")
    old = src.relative_to(root).as_posix()
    stale = stale_links(root, old)
    if stale:
        warnings.append(f"{len(stale)} file(s) still link to {old}: {', '.join(stale)}; "
                        f"python3 scripts/check-edges.py --fix rewrites them")
    out = {"slug": slug, "moved_to": f"work/done/{now:%Y-%m}/{slug}", "closed": today,
           "outcome": "declined" if declined else "merged" if merged_into else None, "reason": reason or None,
           "stream": was_stream, "stale_links": stale, "warnings": warnings}
    if merged_into:
        out["merged_into"] = merged_into
    return out


# ---------------------------------------------------------------- runs on

def wait_task(root: Path, slug: str, *, until: str | None = None, on: str | None = None, clear: bool = False,
              today: str | None = None) -> dict:
    """"Runs on": the task waits on a person or a run until a day to look again. It stays doing; blocked_by says
    on what, quiet_until until when nobody asks after it (briefing advice, task review). clear takes it back."""
    today = today or dt.date.today().isoformat()
    path = find_status(root, slug)
    text = path.read_bytes().decode("utf-8")
    kept = False
    if clear:
        text = remove_fields(text, ("blocked_by", "blocked_since", "quiet_until"))
        text = add_note(text, "Running again", today)
    else:
        if not until:
            raise ValueError("--until YYYY-MM-DD is required (or --clear)")
        dt.date.fromisoformat(until)
        on = " ".join((on or "").split())
        kept = re.search(r"^blocked_by:", text, re.M) is not None and not on
        on = on or "runs on"
        # without --on an existing reason stays: it says more than "runs on"
        fields = ([] if kept else [("blocked_by", json.dumps(on, ensure_ascii=False), "status")]) + [("quiet_until", until, "blocked_by")]
        if not re.search(r"^blocked_since:", text, re.M):
            fields.append(("blocked_since", today, "blocked_by"))
        text = add_note(set_fields(text, fields), f"Runs on until {until}" + ("" if kept else f": {on}"), today)
    path.write_bytes(text.encode("utf-8"))
    with contextlib.redirect_stdout(sys.stderr):
        regenerate_board(root)
    return {"slug": slug, "quiet_until": None if clear else until, "on": None if clear or kept else on}


# ---------------------------------------------------------------- next step

def set_next(root: Path, slug: str, text: str | None = None, *, clear: bool = False, today: str | None = None) -> dict:
    """The task's next step as ``next: {what}``, dated by last_updated and a note; clear takes it away."""
    today = today or dt.date.today().isoformat()
    path = find_status(root, slug)
    old = path.read_bytes().decode("utf-8")
    new = remove_fields(old, ("next",))
    if clear:
        new = add_note(new, "Next step cleared", today)
        what = None
    else:
        if text is None or "\n" in text or "\r" in text:
            raise ValueError("the next step is one line of text (or --clear)")
        what = " ".join(text.split())
        if not what or len(what) > 300:
            raise ValueError("the next step must be 1 to 300 characters")
        line = "{what: " + json.dumps(what, ensure_ascii=False) + "}"
        new = add_note(set_fields(new, [("next", line, "status")]), f"Next step: {what}", today)
    path.write_bytes(new.encode("utf-8"))
    with contextlib.redirect_stdout(sys.stderr):
        regenerate_board(root)
    return {"slug": slug, "next": what}


# ---------------------------------------------------------------- brief

BRIEF_ORDER = ("goal", "story", "acceptance", "by", "at", "basis", "edited")


def brief_block(brief: dict, nl: str = "\n") -> str:
    """The brief as the frontmatter block it is written as: texts JSON-quoted (a basis of digits stays text)."""
    q = lambda v: json.dumps(v, ensure_ascii=False)  # noqa: E731
    out = ["brief:"]
    for key in BRIEF_ORDER:
        if key not in brief:
            continue
        value = brief[key]
        if key == "story":
            out.append("  story: {" + ", ".join(f"{k}: {q(value[k])}" for k in ("as", "want", "so_that")) + "}")
        elif key == "acceptance":
            out += ["  acceptance:" + ("" if value else " []")] + [f"    - {q(x)}" for x in value]
        elif key == "edited":
            out.append(f"  edited: {'true' if value else 'false'}")
        else:
            out.append(f"  {key}: {q(value)}")
    return nl.join(out) + nl


def _replace_file(path: Path, text: str) -> None:
    """The new text in a file beside `path`, which then takes its place: a reader never sees half of it"""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_bytes(text.encode("utf-8"))
        with contextlib.suppress(OSError):
            os.chmod(tmp, path.stat().st_mode & 0o7777)
        os.replace(tmp, path)
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink()


def _front_bounds(lines: list) -> tuple:
    start = 0
    while start < len(lines) and (not lines[start].strip() or lines[start].startswith("#")):
        start += 1
    if start >= len(lines) or lines[start].rstrip("\r\n") != "---":
        raise ValueError("STATUS.md has no frontmatter")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].rstrip("\r\n") == "---"), None)
    if end is None:
        raise ValueError("STATUS.md frontmatter is not closed")
    return start, end


def _brief_span(lines: list, start: int, end: int) -> tuple | None:
    """(first, past) of the brief block in the frontmatter, as card_fields.strip_brief takes it out: the
    `brief:` line and the indented and blank lines after it, less the blank lines at its end"""
    first = next((i for i in range(start + 1, end) if re.match(r"brief\s*:", lines[i])), None)
    if first is None:
        return None
    past, i = first + 1, first + 1
    while i < end and (lines[i][:1] in (" ", "\t") or not lines[i].strip()):
        i += 1
        if lines[i - 1].strip():
            past = i
    return first, past


def write_brief(root: Path, slug: str, brief: dict, *, basis: str | None = None, edited: bool = False,
                today: str | None = None) -> dict:
    """Write or replace the task's brief block; see the module doc. Returns {slug, basis, brief}."""
    today = today or dt.date.today().isoformat()
    path = find_status(root, slug)
    old = path.read_bytes().decode("utf-8")
    if basis is not None and brief_basis(old) != basis:
        raise ValueError("STATUS.md changed since the brief was written against it")
    if not isinstance(brief, dict):
        raise ValueError("brief: not a mapping")
    given = {k: v for k, v in brief.items() if k not in ("basis", "edited")}
    clean, errors = validate_brief({"at": today, **given, "basis": "0" * 16, "edited": bool(edited)})
    if errors or clean is None:
        raise ValueError("brief: " + "; ".join(errors or ["empty"]))
    lines = old.splitlines(keepends=True)
    start, end = _front_bounds(lines)
    nl = "\r\n" if lines[start].endswith("\r\n") else "\n"
    span = _brief_span(lines, start, end)
    first, past = span if span else (end, end)

    def render(b: dict) -> str:
        return "".join(lines[:first]) + brief_block(b, nl) + "".join(lines[past:])

    clean["basis"] = brief_basis(render(clean))     # the basis leaves the block out, so it is the same after
    new = render(clean)
    _replace_file(path, new)
    return {"slug": slug, "basis": clean["basis"], "brief": clean}


def mark_brief_edited(root: Path, slug: str) -> dict:
    """`edited: true` in the brief block a person changed by hand; every other byte of it stays."""
    path = find_status(root, slug)
    old = path.read_bytes().decode("utf-8")
    lines = old.splitlines(keepends=True)
    start, end = _front_bounds(lines)
    span = _brief_span(lines, start, end)
    if span is None:
        raise ValueError(f"{slug} has no brief to mark")
    first, past = span
    nl = "\r\n" if lines[start].endswith("\r\n") else "\n"
    flag = next((i for i in range(first + 1, past) if re.match(r"\s+edited\s*:", lines[i])), None)
    if flag is not None:
        indent = re.match(r"\s+", lines[flag]).group(0)
        lines[flag] = f"{indent}edited: true" + (lines[flag][len(lines[flag].rstrip("\r\n")):] or nl)
    elif past > first + 1:
        indent = re.match(r"[ \t]+", lines[first + 1]).group(0)
        lines.insert(past, f"{indent}edited: true{nl}")
    else:
        # a flow mapping on one line: written again as a block, its texts as they were
        data = (yaml_load("".join(lines[first:past])) or {}).get("brief")
        if not isinstance(data, dict):
            raise ValueError(f"{slug}: the brief block is not a mapping")
        lines[first:past] = [brief_block({**data, "edited": True}, nl)]
    _replace_file(path, "".join(lines))
    return {"slug": slug, "edited": True}


def yaml_load(text: str):
    import yaml
    return yaml.safe_load(text)


# ---------------------------------------------------------------- new, also from an inbox item

NEW_STATUSES = ("backlog", "doing")


def _new_slug(text: str) -> str:
    text = text.lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        text = text.replace(a, b)
    # the head of a summary ("X: the details"), no aside in brackets, cut between words, never inside one
    text = re.sub(r"\([^)]*\)", " ", text.split(": ", 1)[0])
    words = [w for w in re.split(r"[^a-z0-9]+", text) if w]
    slug = ""
    for w in words:
        if slug and len(slug) + 1 + len(w) > 40:
            break
        slug = f"{slug}-{w}" if slug else w
    return slug[:48] or "task"


def new_task(root: Path, slug: str | None = None, *, headline: str | None = None, status: str = "backlog",
             from_inbox: str | None = None, task_type: str = "admin", now: dt.datetime | None = None) -> dict:
    """A new work/tasks/<slug>/STATUS.md (the template's required fields, a short body). From an inbox item the
    headline and the situation come from the item, the origin names it, and the item closes with a pointer to
    the task: an inbox item that turned out to be work for more than one sitting becomes a task."""
    now = now or dt.datetime.now()
    today = now.date().isoformat()
    if status not in NEW_STATUSES:
        raise ValueError(f"status must be one of {NEW_STATUSES}")
    box = item = None
    if from_inbox:
        box = _module("inbox", ROOT / "scripts" / "inbox.py").Inbox(root / "work" / "inbox", actor="task")
        item = box.get(box.resolve(from_inbox))
        if item.state in ("done", "dropped"):
            raise ValueError(f"inbox item {item.id} is closed ({item.state}); it becomes no task")
        headline = headline or item.summary
    headline = " ".join((headline or "").split())
    if not headline:
        raise ValueError("a task needs a headline (--headline)")
    slug = slug or _new_slug(headline)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", slug):
        raise ValueError(f"not a task slug: {slug!r}")
    work = root / "work"
    if any(p.is_dir() for p in (work / "tasks" / slug, work / "streams" / slug)) or any((work / "done").glob(f"*/{slug}")):
        raise ValueError(f"a task {slug!r} exists already")
    origin = (f"inbox {item.id} ({str(item.created or '')[:10]}, {item.source}): {item.summary}" if item
              else f"Ad-hoc {today}")
    situation = (item.detail or item.summary) if item else headline
    fm = [f"slug: {slug}", f"type: {task_type}", f"status: {status}", "priority: P2", f'created: "{today}"',
          f'last_updated: "{today}"', f"headline: {json.dumps(headline, ensure_ascii=False)}",
          f"origin: {json.dumps(origin, ensure_ascii=False)}", "sync:", "  bridge_only: true"]
    body = (f"# {headline}\n\n## Situation\n\n{situation}\n\n## Status\n\nNew{' (from the inbox)' if item else ''}.\n\n"
            "## Next Steps\n\n- [ ] First step\n")
    d = work / "tasks" / slug
    d.mkdir(parents=True)
    (d / "STATUS.md").write_text("# yaml-language-server: $schema=../../templates/_schema.status.yaml\n---\n"
                                 + "\n".join(fm) + "\n---\n\n" + body, encoding="utf-8")
    warnings = []
    if item:
        box.close(item.id, note=f"became the task {slug} (work/tasks/{slug}/)")
        try:
            (work / "inbox.md").write_text(box.render(), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001 - the item is closed; a stale view is a warning
            warnings.append(f"work/inbox.md not rendered: {exc}")
    try:
        with contextlib.redirect_stdout(sys.stderr):
            regenerate_board(root)
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"work/board.md not regenerated: {exc}")
    try:
        append_log_row(root, now, slug, f"new task ({status})" + (f" from inbox {item.id}" if item else ""))
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"work/log.md row not written: {exc}")
    return {"slug": slug, "status": status, "path": f"work/tasks/{slug}/STATUS.md",
            "inbox": item.id if item else None, "warnings": warnings}


REOPEN_STATUSES = ("doing", "backlog", "review")   # review too: an undo restores the status before the close


def reopen_task(root: Path, slug: str, *, status: str = "doing", note: str | None = None,
                now: dt.datetime | None = None) -> dict:
    """The inverse of close_task: back to work/tasks/ (an ended stream back to work/streams/), status set, close
    fields gone, note, board, log row."""
    now = now or dt.datetime.now()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", slug):
        raise ValueError(f"not a task slug: {slug!r}")
    if status not in REOPEN_STATUSES:
        raise ValueError(f"reopen as one of {', '.join(REOPEN_STATUSES)}")
    work = root / "work"
    for kind in ("tasks", "streams"):
        if (work / kind / slug / "STATUS.md").is_file():
            raise ValueError(f"{slug} is open already (work/{kind}/)")
    closed = sorted((work / "done").glob(f"*/{slug}/STATUS.md"))
    if not closed:
        raise ValueError(f"no closed task {slug!r} under {work / 'done'}")
    src = closed[-1].parent                     # month folders sort by date: the latest close
    text = closed[-1].read_bytes().decode("utf-8")
    dest = work / ("streams" if re.search(r"^was_stream:\s*true\s*$", text, re.M) else "tasks") / slug
    today = now.date().isoformat()
    note = " ".join((note or "").split())
    text = remove_fields(set_fields(text, [("status", status, None)]), ("closed", "outcome", "was_stream", "merged_into"))
    text = add_note(text, f"Reopened: {note}" if note else "Reopened", today)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.rename(src, dest)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        shutil.move(str(src), str(dest))
    try:
        (dest / "STATUS.md").write_bytes(text.encode("utf-8"))
    except OSError:
        os.rename(dest, src)
        raise
    warnings = []
    try:
        with contextlib.redirect_stdout(sys.stderr):
            regenerate_board(root)
    except Exception as exc:  # noqa: BLE001 - the task is open again; a stale board is a warning
        warnings.append(f"work/board.md not regenerated: {exc}")
    try:
        append_log_row(root, now, slug, "reopened" + (f": {note}" if note else ""))
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"work/log.md row not written: {exc}")
    ideas = _close_shelve_ideas(root, slug, warnings)
    return {"slug": slug, "moved_from": str(src.relative_to(root)), "moved_to": str(dest.relative_to(root)),
            "status": status, "note": note or None, "closed_ideas": ideas, "warnings": warnings}


SHELVE_DAYS = 90            # how long a shelved idea stays quiet when --until is not given


def _headline_of(text: str, slug: str) -> str:
    """The task's one-line name: headline:, then title:, then the first heading of the body, then the slug."""
    m = re.match(r"(?:[^\S\n]*#[^\n]*\n|\s*\n)*---[^\S\n]*\n(.*?)\n---[^\S\n]*(?:\n|$)(.*)", text.lstrip("\ufeff"), re.S)
    front, body = (m.group(1), m.group(2)) if m else ("", text)
    try:
        fm = yaml_load(front) if front else None
    except Exception:  # noqa: BLE001 - a broken frontmatter must not stop a shelve; fall through to the heading
        fm = None
    for key in ("headline", "title"):
        value = " ".join(str(fm.get(key) or "").split()) if isinstance(fm, dict) else ""
        if value:
            return value
    heading = re.search(r"^#\s+(.+?)\s*$", body, re.M)
    return " ".join(heading.group(1).split()) if heading else slug


def shelve_task(root: Path, slug: str, *, until: str | None = None, reason: str | None = None,
                now: dt.datetime | None = None) -> dict:
    """Park a finite task nobody works on without losing it, in one command instead of three: an idea in the
    inbox (key shelve:<slug>, deferred until a day so nothing announces it), then the task closes as declined.
    The order leaves no half state: every check runs before anything is written, the idea comes first, and when
    the close still fails the idea closes again, so a task is never gone without its idea. reopen_task closes
    the idea when the task comes back."""
    now = now or dt.datetime.now()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", slug):
        raise ValueError(f"not a task slug: {slug!r}")
    work = root / "work"
    path = work / "tasks" / slug / "STATUS.md"
    if not path.is_file():
        if (work / "streams" / slug / "STATUS.md").is_file():
            raise ValueError(f"{slug} is a stream: streams are not finite and are not shelved")
        if any((work / "done").glob(f"*/{slug}/STATUS.md")):
            raise ValueError(f"{slug} is already closed (work/done/)")
        raise ValueError(f"no task {slug!r} under {work / 'tasks'}")
    until = until or (now.date() + dt.timedelta(days=SHELVE_DAYS)).isoformat()
    dt.date.fromisoformat(until)
    month = f"{now:%Y-%m}"
    if (work / "done" / month / slug).exists():
        raise ValueError(f"work/done/{month}/{slug} exists already")
    headline = _headline_of(path.read_bytes().decode("utf-8"), slug)
    reason = " ".join((reason or "").split())
    where = f"work/done/{month}/{slug}/STATUS.md"
    detail = (f"Shelved on {now.date().isoformat()}" + (f" ({reason})" if reason else "") + f". The task lives in {where}. "
              f"To bring it back: python3 scripts/task.py reopen {slug}")
    box = _module("inbox", ROOT / "scripts" / "inbox.py").Inbox(work / "inbox", actor="task")
    item_id = box.add(source="task", kind="idea", summary=headline, gate="only-you", urgency="later", detail=detail,
                      key=f"shelve:{slug}")
    created = box.last_new == item_id
    muted = None
    if box.get(item_id).state not in ("open", "deferred"):
        # add() hands back the last idea under this key when a person dropped or rejected it. A new shelve is a
        # new decision, so that idea comes back; only a mute rule the person wrote keeps it dropped.
        muted = box.muted_by("task", "idea", f"shelve:{slug}")
        if muted is None:
            box.event(item_id, "reopen", text=f"{slug} shelved again")
            created = True
    try:
        box.event(item_id, "defer", until=until)
        out = close_task(root, slug, reason=f"shelved: {reason}" if reason else "shelved", declined=True, now=now)
    except Exception:
        if created:                                  # the idea alone would announce a task that is still open
            try:
                box.close(item_id, note=f"shelve of {slug} failed; the task stays open")
            except Exception:  # noqa: BLE001 - the original failure is the one to report
                pass
        raise
    try:
        (work / "inbox.md").write_text(box.render(), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - the task is shelved; a stale view is a warning
        out["warnings"].append(f"work/inbox.md not rendered: {exc}")
    if muted is not None:
        out["warnings"].append(f"the idea {item_id} stays dropped: mute rule {muted.get('id')} holds for it "
                               f"(inbox.py unmute takes the rule back)")
    out.update({"inbox": item_id, "until": until, "headline": headline})
    return out


def _close_shelve_ideas(root: Path, slug: str, warnings: list) -> list:
    """The open or deferred idea a shelve filed for this task is done once the task is back."""
    inbox_dir = root / "work" / "inbox"
    if not inbox_dir.is_dir():
        return []
    closed = []
    try:
        box = _module("inbox", ROOT / "scripts" / "inbox.py").Inbox(inbox_dir, actor="task")
        for item in box.items():
            if item.key == f"shelve:{slug}" and item.state in ("open", "deferred"):
                box.close(item.id, note=f"the task {slug} was reopened")
                closed.append(item.id)
        if closed:
            (root / "work" / "inbox.md").write_text(box.render(), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - the task is open again; a lingering idea is a warning
        warnings.append(f"shelve idea for {slug} not closed: {exc}")
    return closed


# ---------------------------------------------------------------- merge: two tasks about the same thing

MERGE_DOCS_MAX = 20          # the documents of a merged task linked in the one it went into
MERGE_HEADING = "Merged from {slug}"
PLAIN_PATH_RE = re.compile(r"[A-Za-z0-9._/-]+")
STEP_OPEN_RE = re.compile(r"^\s*[-*+] \[ \]")
LIST_ITEM_RE = re.compile(r"^\s*[-*+] ")


def _marks(slug: str) -> tuple[str, str]:
    """The two lines a merged block stands between in the kept task's STATUS.md"""
    return f"<!-- merged-from: {slug} -->", f"<!-- /merged-from: {slug} -->"


def _related_tag(slug: str) -> str:
    return f"# merged-from: {slug}"


def _finite_open(work: Path, slug: str) -> Path:
    """The STATUS.md of an open finite task; a stream, a closed task or none at all is refused"""
    if not MERGE_SLUG_RE.fullmatch(slug):
        raise ValueError(f"not a task slug: {slug!r}")
    path = work / "tasks" / slug / "STATUS.md"
    if path.is_file():
        return path
    if (work / "streams" / slug / "STATUS.md").is_file():
        raise ValueError(f"{slug} is a stream: only finite tasks merge")
    if any((work / "done").glob(f"*/{slug}/STATUS.md")):
        raise ValueError(f"{slug} is already closed (work/done/)")
    raise ValueError(f"no task {slug!r} under {work / 'tasks'}")


def _front_and_body(text: str) -> tuple[dict, str]:
    """The frontmatter as a mapping (empty when it does not parse) and the body after it"""
    m = re.match(r"(?:[^\S\n]*#[^\n]*\n|\s*\n)*---[^\S\n]*\n(.*?)\n---[^\S\n]*(?:\n|$)(.*)", text.lstrip("﻿"), re.S)
    if not m:
        return {}, text
    try:
        fm = yaml_load(m.group(1))
    except Exception:  # noqa: BLE001 - a broken frontmatter gives no goal; the body still counts
        fm = None
    return (fm if isinstance(fm, dict) else {}), m.group(2)


def _merged_parts(text: str, slug: str) -> dict:
    """What a merged task brings along as text: its headline, its goal when it says more, every line of its notes
    and every open step, each as written"""
    fm, body = _front_and_body(text)
    headline = _headline_of(text, slug)
    brief = fm.get("brief") if isinstance(fm.get("brief"), dict) else {}
    goal = " ".join(str(brief.get("goal") or "").split())
    lines = body.splitlines()
    start = next((i for i, ln in enumerate(lines) if NOTES.match(ln.rstrip())), None)
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines)) if start is not None else None
    notes = [ln.rstrip() if LIST_ITEM_RE.match(ln) else f"- {ln.strip()}"
             for ln in (lines[start + 1:end] if start is not None else []) if ln.strip()]
    inside = set(range(start, end)) if start is not None else set()
    steps = [ln.rstrip() for i, ln in enumerate(lines) if i not in inside and STEP_OPEN_RE.match(ln)]
    return {"headline": headline, "goal": goal if goal and goal != " ".join(headline.split()) else "",
            "notes": notes, "steps": steps}


def _merged_docs(folder: Path) -> list[str]:
    """Up to MERGE_DOCS_MAX files of a task's deliverables/, relative and sorted: no dotfile, no link"""
    deliv = folder / "deliverables"
    if deliv.is_symlink() or not deliv.is_dir():
        return []
    found = []
    for base, dirs, files in os.walk(deliv, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not os.path.islink(os.path.join(base, d)))
        for name in files:
            path = Path(base) / name
            if name.startswith(".") or path.is_symlink() or not path.is_file():
                continue
            found.append(path.relative_to(deliv).as_posix())
    return sorted(found)[:MERGE_DOCS_MAX]


def _yaml_item(path: str) -> str:
    """A path as a YAML list item: plain where it can be, else quoted"""
    return path if PLAIN_PATH_RE.fullmatch(path) else json.dumps(path, ensure_ascii=False)


def _front_range(lines: list) -> tuple[int, int]:
    start = 0
    while start < len(lines) and (not lines[start].strip() or lines[start].startswith("#")):
        start += 1
    if start >= len(lines) or lines[start].rstrip("\r\n") != "---":
        raise ValueError("STATUS.md has no frontmatter")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].rstrip("\r\n") == "---"), None)
    if end is None:
        raise ValueError("STATUS.md frontmatter is not closed")
    return start, end


def _related_block(lines: list, start: int, end: int) -> tuple[int | None, int, str]:
    """(line of `related:`, the line after its block, what follows the key on its line) in the frontmatter"""
    at = next((i for i in range(start + 1, end) if re.match(r"related:(\s|$)", lines[i])), None)
    if at is None:
        return None, end, ""
    after = at + 1
    while after < end and (lines[after][:1] in (" ", "\t") or not lines[after].strip()):
        after += 1
    rest = re.sub(r"\s+#.*$", "", lines[at].rstrip("\r\n")[len("related:"):]).strip()
    return at, after, rest


def _add_related(text: str, paths: list, slug: str) -> tuple[str, int, str | None]:
    """The paths as items of `related:`, each tagged with the slug: a new block list when there is none, after
    the last item of a block list; a flow list or a scalar stays as it is (a warning)"""
    lines = text.splitlines(keepends=True)
    start, end = _front_range(lines)
    nl = "\r\n" if lines[start].endswith("\r\n") else "\n"
    at, after, rest = _related_block(lines, start, end)
    if at is not None and rest:
        return text, 0, "related: is not a block list, the paths stand only in the merged section"
    indent, pos = "  ", end
    if at is not None:
        items = [i for i in range(at + 1, after) if lines[i].lstrip().startswith("- ")]
        if items:
            indent = lines[items[-1]][:len(lines[items[-1]]) - len(lines[items[-1]].lstrip())]
        pos = (items[-1] + 1) if items else at + 1
    new = [f"{indent}- {_yaml_item(p)}  {_related_tag(slug)}{nl}" for p in paths]
    if at is None:
        new = [f"related:{nl}"] + new
    lines[pos:pos] = new
    return "".join(lines), len(paths), None


def _drop_related(text: str, slug: str) -> tuple[str, int]:
    """The related items a merge of slug added, and `related:` itself when no item is left"""
    lines = text.splitlines(keepends=True)
    start, end = _front_range(lines)
    at, after, rest = _related_block(lines, start, end)
    if at is None or rest:
        return text, 0
    tag = _related_tag(slug)
    gone = [i for i in range(at + 1, after) if lines[i].lstrip().startswith("- ") and lines[i].rstrip().endswith(tag)]
    left = [i for i in range(at + 1, after) if lines[i].lstrip().startswith("- ") and i not in gone]
    drop = set(gone) | ({at} if not left else set())
    return "".join(ln for i, ln in enumerate(lines) if i not in drop), len(gone)


def _insert_block(text: str, block: list) -> str:
    """The merged block before the `## Notes` of the body when there is one, else at the end"""
    lines = text.splitlines(keepends=True)
    nl = "\r\n" if lines and lines[0].endswith("\r\n") else "\n"
    _start, end = _front_range(lines)
    at = next((i for i in range(end + 1, len(lines)) if NOTES.match(lines[i].rstrip("\r\n"))), None)
    if at is None:
        return text.rstrip("\r\n") + nl + nl + nl.join(block) + nl
    head = [] if at == 0 or not lines[at - 1].strip() else [nl]
    lines[at:at] = head + [ln + nl for ln in block] + [nl]
    return "".join(lines)


def _remove_block(text: str, slug: str) -> str | None:
    """The text without the merged block of slug (its markers inclusive, one blank line after it); None when the
    block is not there as a merge left it (a marker gone or out of order)"""
    lines = text.splitlines(keepends=True)
    first, last = _marks(slug)
    a = next((i for i, ln in enumerate(lines) if ln.strip() == first), None)
    b = next((i for i, ln in enumerate(lines) if ln.strip() == last), None)
    if a is None or b is None or b < a:
        return None
    stop = b + 1
    if stop < len(lines) and not lines[stop].strip():
        stop += 1
    elif stop >= len(lines) and a > 0 and not lines[a - 1].strip():
        a -= 1                       # a block at the end took a blank line before it
    return "".join(lines[:a] + lines[stop:])


def merge_task(root: Path, keep: str, slug: str, *, heading: str | None = None,
               now: dt.datetime | None = None) -> dict:
    """slug closes as merged into keep: keep gets one section with what slug said and where its files went, its
    related: lists those paths, both get a note; checked before the first write, taken out again when the close
    fails. One merged task per call."""
    now = now or dt.datetime.now()
    work = root / "work"
    if keep == slug:
        raise ValueError("a task does not merge into itself")
    keep_path = _finite_open(work, keep)
    src_path = _finite_open(work, slug)
    month = f"{now:%Y-%m}"
    if (work / "done" / month / slug).exists():
        raise ValueError(f"work/done/{month}/{slug} exists already")
    before = keep_path.read_bytes()
    keep_text = before.decode("utf-8")
    first, _last = _marks(slug)
    if first in keep_text:
        raise ValueError(f"{keep} holds a merged section of {slug} already")
    parts = _merged_parts(src_path.read_bytes().decode("utf-8"), slug)
    docs = _merged_docs(src_path.parent)
    moved = f"work/done/{month}/{slug}"
    paths = [f"{moved}/STATUS.md"] + [f"{moved}/deliverables/{d}" for d in docs]
    title = " ".join((heading or MERGE_HEADING).replace("{slug}", slug).split()) or MERGE_HEADING.format(slug=slug)
    chunks = [[parts["headline"]], [parts["goal"]] if parts["goal"] else [], parts["notes"], parts["steps"],
              [f"- {p}" for p in paths]]
    block = [first, f"## {title}", ""]
    for chunk in (c for c in chunks if c):
        block += chunk + [""]
    block[-1] = _marks(slug)[1]
    today = now.date().isoformat()
    text = _insert_block(keep_text, block)
    text, related, warning = _add_related(text, paths, slug)
    text = add_note(text, f"Merged in {slug}: {parts['headline']}", today)
    _replace_file(keep_path, text)
    try:
        out = close_task(root, slug, merged_into=keep, now=now)
    except BaseException:
        _replace_file(keep_path, before.decode("utf-8"))     # nothing half merged: the section goes again
        raise
    warnings = ([warning] if warning else []) + list(out["warnings"])
    try:
        append_log_row(root, now, keep, f"merged in {slug}")
    except Exception as exc:  # noqa: BLE001 - the merge stands; a missing row is a warning
        warnings.append(f"work/log.md row not written: {exc}")
    return {"keep": keep, "slug": slug, "moved_to": out["moved_to"], "notes": len(parts["notes"]),
            "steps": len(parts["steps"]), "docs": len(docs), "related": related, "warnings": warnings}


def unmerge_task(root: Path, keep: str, slug: str, *, status: str = "doing", now: dt.datetime | None = None) -> dict:
    """The inverse of merge_task: the section and the tagged related lines leave keep, slug opens again as
    status, both get a note. Refused when slug is not closed as merged into keep or the section is not there."""
    now = now or dt.datetime.now()
    work = root / "work"
    if status not in REOPEN_STATUSES:
        raise ValueError(f"reopen as one of {', '.join(REOPEN_STATUSES)}")
    keep_path = _finite_open(work, keep)
    if not MERGE_SLUG_RE.fullmatch(slug):
        raise ValueError(f"not a task slug: {slug!r}")
    closed = sorted((work / "done").glob(f"*/{slug}/STATUS.md"))
    fm = _front_and_body(closed[-1].read_bytes().decode("utf-8"))[0] if closed else {}
    if fm.get("outcome") != "merged" or fm.get("merged_into") != keep:
        raise ValueError(f"{slug} is not closed as merged into {keep}")
    before = keep_path.read_bytes().decode("utf-8")
    text = _remove_block(before, slug)
    if text is None:
        raise ValueError(f"the merged section of {slug} in {keep} was changed by hand")
    text, related = _drop_related(text, slug)
    text = add_note(text, f"Merge of {slug} taken back", now.date().isoformat())
    _replace_file(keep_path, text)
    try:
        out = reopen_task(root, slug, status=status, note=f"merge into {keep} taken back", now=now)
    except BaseException:
        _replace_file(keep_path, before)
        raise
    warnings = list(out["warnings"])
    try:
        append_log_row(root, now, keep, f"merge of {slug} taken back")
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"work/log.md row not written: {exc}")
    return {"keep": keep, "slug": slug, "moved_to": out["moved_to"], "status": status,
            "removed": {"block": True, "related": related}, "warnings": warnings}


# ---------------------------------------------------------------- review

REVIEW_CACHE = Path(".bridge") / "task-review.json"
VERDICTS = ("close", "continue", "waiting", "stale", "unclear")
CONFIDENCES = ("high", "medium", "low")
# Aliases resolve to full ids: the CLI alias `haiku` meant an older model than the one asked for.
MODEL_IDS = ai.CLAUDE_MODELS
# bridge-config.yaml `models:` tier keys, the instance's names first, then the template's.
TIER_KEYS = {"mechanical": ("mechanical", "routine"), "directed": ("directed", "analysis")}
TIER_DEFAULT = {"mechanical": MODEL_IDS["haiku"], "directed": MODEL_IDS["sonnet"]}
DEFAULT_REVIEW_COMMAND = (
    'claude -p --model {model} --output-format json --no-session-persistence --setting-sources "" '
    '--strict-mcp-config --tools ""')        # no tool at all: the evidence is in the prompt
DEFAULT_MAX_AGE_DAYS = 7
DEFAULT_STALE_DAYS = 21
REVIEW_STATUSES = ("doing", "review")      # --backlog adds backlog
# The whole review (evidence, both tiers) stays inside this budget; the dashboard waits 240 s.
REVIEW_BUDGET_SEC = 190
TIER_ONE_MAX_SEC = 150
# What one call of the directed model costs when no run has measured it (a small Sonnet call, 2026-10).
DIRECTED_CALL_USD = 0.021
PROMPT_VERSION = 4          # raise when the prompt changes: cached verdicts of an older prompt are asked again
_clock = time.monotonic
LANGUAGE_NAMES = {"de": "German", "en": "English", "fr": "French", "es": "Spanish", "it": "Italian",
                  "nl": "Dutch", "pt": "Portuguese", "pl": "Polish"}
CLIP = {"origin": 200, "headline": 160, "blocked_by": 240}
GH_REF = re.compile(r"(?<![\w/.-])([A-Za-z0-9][\w.-]*/[\w.-]+)#(\d+)\b")
REVIEW_PROMPT = """You review the open tasks of a work tracker and recommend one verdict per task. Today is {today}.

Verdicts:
- close: the evidence shows the work is done or moot, e.g. a linked issue closed as completed, a linked PR merged, every step checked, the log reports it finished.
- continue: the work is open and still moving.
- waiting: blocked on a person or an event that is still pending (a linked issue or PR still open, an answer not yet given).
- stale: no activity for {stale_days} days or more and no pending blocker.
- unclear: the evidence supports none of the above.
A blocker that names an issue or PR which is now closed or merged is no longer pending: decide whether the work is done.
A task may start with a `signals:` line, computed from GitHub: own_refs_closed (every issue and PR the task tracks is closed as completed or merged) and blocker_resolved (everything its blocker names is closed or merged). When own_refs_closed holds, the verdict is close, with confidence medium unless the steps clearly describe new work that remains AFTER that reference closed (steps written before it closed, or steps that only read, review, confirm or wrap up that reference, do not count); the reason names the closed reference with its date and, briefly, which steps still look open, so the person can confirm. blocker_resolved alone means the task is no longer waiting: decide from the steps and the log whether it is done or should continue.
A task may list `acceptance:` criteria, the outcomes that make it done: when the evidence shows each of them met, that supports close; when one is plainly not met yet, it does not. Name the criteria the evidence meets in the reason.
Confidence: high when one piece of evidence decides it, medium when it is likely, low when you guess.

Answer with a JSON array only, one object per task:
[{{"slug": "<slug>", "verdict": "close|continue|waiting|stale|unclear", "reason": "<one sentence>", "confidence": "high|medium|low"}}]
Write each reason as one sentence in {language} that names the evidence.

Tasks:

{tasks}
"""


def default_run(argv, input=None, timeout=60, cwd=None):
    """Run a command; a missing binary or a timeout is a failed run, never an exception."""
    try:
        return subprocess.run(argv, input=input, capture_output=True, text=True, timeout=timeout, cwd=cwd)
    except (OSError, subprocess.SubprocessError) as exc:
        return subprocess.CompletedProcess(argv, 127, "", str(exc))


def _config(root: Path) -> dict:
    return _briefing().read_config(root)


def _model_id(value, fallback: str) -> str:
    v = str(value or "").strip()
    if not v or v.lower() in ("parent", "inherit"):
        return fallback
    return MODEL_IDS.get(v.lower(), v)


def tier_model(cfg: dict, tier: str) -> str:
    models = cfg.get("models") if isinstance(cfg.get("models"), dict) else {}
    value = next((models[k] for k in TIER_KEYS[tier] if models.get(k)), None)
    return _model_id(value, TIER_DEFAULT[tier])


def _language(cfg: dict) -> str:
    lang = cfg.get("language")
    code = lang.get("conversation") if isinstance(lang, dict) else lang
    code = str(code or "en").strip()
    return LANGUAGE_NAMES.get(code.lower(), code or "English")


def _review_cfg(cfg: dict) -> dict:
    work = cfg.get("work") if isinstance(cfg.get("work"), dict) else {}
    rv = work.get("review") if isinstance(work.get("review"), dict) else {}
    def number(key, default):
        try:
            return int(rv.get(key, default))
        except (TypeError, ValueError):
            return default
    skip = rv.get("skip_sections")
    skip = [skip] if isinstance(skip, str) else skip if isinstance(skip, list) else []
    return {"command": rv.get("command") or DEFAULT_REVIEW_COMMAND,
            "max_age_days": number("max_age_days", DEFAULT_MAX_AGE_DAYS),
            "stale_days": number("stale_days", DEFAULT_STALE_DAYS),
            # briefing section ids whose rows the triage leaves out (triage.py); empty = every row is judged
            "skip_sections": [str(x) for x in skip if x]}


def _plain(value):
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return json.loads(json.dumps(value, default=str))
    return " ".join(str(value).split())


def _notes(body: str, n: int = 3) -> list:
    m = re.search(r"^## Notes\s*$(.*?)(?=^## |\Z)", body, flags=re.M | re.S)
    if not m:
        return []
    lines = [ln.strip()[2:] for ln in m.group(1).splitlines() if ln.strip().startswith("- ")]
    return [_briefing()._clip(ln, 160) for ln in lines[-n:]]


BARE_REF = re.compile(r"(?<![\w/.#-])#(\d+)\b")


def _sync_repo(fm: dict) -> tuple:
    gh = ((fm.get("sync") or {}).get("github") or {}) if isinstance(fm.get("sync"), dict) else {}
    gh = gh if isinstance(gh, dict) else {}
    repo = gh.get("repo")
    return (repo if isinstance(repo, str) and "/" in repo else None), gh


def _own_refs(fm: dict) -> list:
    """The issues and PRs the task tracks itself: sync.github issues and pull requests."""
    repo, gh = _sync_repo(fm)
    if not repo:
        return []
    return list(dict.fromkeys((repo, int(n)) for key in ("issues", "pull_requests", "prs")
                              for n in gh.get(key) or [] if str(n).isdigit()))


def _blocker_refs(fm: dict) -> list:
    """What blocked_by names: owner/repo#N, and a bare #N in the task's own repository."""
    text = str(fm.get("blocked_by") or "")
    found = [(m.group(1), int(m.group(2))) for m in GH_REF.finditer(text)]
    repo, _ = _sync_repo(fm)
    if repo:
        found += [(repo, int(m.group(1))) for m in BARE_REF.finditer(text)]
    return list(dict.fromkeys(found))


def _refs_of(fm: dict, texts: list) -> list:
    found = _own_refs(fm) + _blocker_refs(fm)
    for text in texts:
        for m in GH_REF.finditer(str(text or "")):
            found.append((m.group(1), int(m.group(2))))
    return list(dict.fromkeys(found))


def _completed(ref: dict) -> bool:
    return bool(ref.get("merged")) or (ref.get("state") == "CLOSED" and ref.get("reason") in (None, "COMPLETED")
                                       and ref.get("kind") != "pr")


def _closed(ref: dict) -> bool:
    return bool(ref.get("merged")) or ref.get("state") in ("CLOSED", "MERGED")


def signals(own: list, blocker: list, states: dict) -> dict:
    """Computed before any model: are the task's own references done, is what blocks it resolved."""
    def key(r):
        return f"{r[0]}#{r[1]}"
    own_done = bool(own) and all(_completed(states.get(key(r), {})) for r in own)
    blocker_done = bool(blocker) and all(_closed(states.get(key(r), {})) for r in blocker)
    closed = [f"{key(r)} {states[key(r)].get('closed_at') or ''}".strip() for r in dict.fromkeys(own + blocker)
              if _closed(states.get(key(r), {}))]
    return {"own_refs_closed": own_done, "blocker_resolved": blocker_done, "closed_refs": closed}


def resolve_refs(refs: list, run, body: bool = False) -> dict:
    """State of every issue or PR in ONE `gh api graphql` call. A failure leaves them `unknown`. `body` asks
    for the start of each text too (the triage describes board items from it)."""
    result = {f"{r}#{n}": {"state": "unknown"} for r, n in refs}
    if not refs:
        return result
    repos = sorted({r for r, _ in refs})
    parts = []
    for i, repo in enumerate(repos):
        owner, name = repo.split("/", 1)
        nums = sorted({n for r, n in refs if r == repo})
        fields = " ".join(
            f"n{n}: issueOrPullRequest(number: {n}) {{ __typename "
            f"... on Issue {{ state stateReason closedAt title{' body' if body else ''} }} "
            f"... on PullRequest {{ state merged closedAt title{' body' if body else ''} }} }}" for n in nums)
        parts.append(f"r{i}: repository(owner: {json.dumps(owner)}, name: {json.dumps(name)}) {{ {fields} }}")
    query = "query { " + " ".join(parts) + " }"
    try:
        done = run(["gh", "api", "graphql", "-f", f"query={query}"], timeout=40)
        data = (json.loads(done.stdout or "{}") or {}).get("data") or {}
    except (ValueError, AttributeError, TypeError):
        data = {}
    for i, repo in enumerate(repos):
        node = data.get(f"r{i}") if isinstance(data, dict) else None
        for r, n in refs:
            x = node.get(f"n{n}") if r == repo and isinstance(node, dict) else None
            if isinstance(x, dict):
                result[f"{r}#{n}"] = {
                    "kind": "pr" if x.get("__typename") == "PullRequest" else "issue",
                    "state": x.get("state") or "unknown", "reason": x.get("stateReason"),
                    "merged": x.get("merged"), "closed_at": (x.get("closedAt") or "")[:10] or None,
                    "title": _briefing()._clip(str(x.get("title") or ""), 80),
                    **({"body": _briefing()._clip(str(x.get("body") or ""), 500)} if body else {})}
    return result


def _ref_text(key: str, ref: dict) -> str:
    if ref.get("state") == "unknown":
        return f"{key} state unknown"
    what = "PR" if ref.get("kind") == "pr" else "issue"
    state = "MERGED" if ref.get("merged") else ref.get("state")
    reason = f"/{ref['reason']}" if ref.get("reason") and ref.get("state") == "CLOSED" else ""
    when = f" {ref['closed_at']}" if ref.get("closed_at") else ""
    return f"{key} {what} {state}{reason}{when} \"{ref.get('title') or ''}\""


def gather(root: Path, slugs, run, backlog: bool = False, now_day: dt.date | None = None) -> list:
    """Evidence per open task, deterministic: what goes to the model and what the cache hashes."""
    b = _briefing()
    base = root / "work" / "tasks"
    if slugs:
        paths = []
        for slug in slugs:
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", slug) or not (base / slug / "STATUS.md").is_file():
                raise ValueError(f"no open task {slug!r} under {base}")
            paths.append(base / slug / "STATUS.md")
    else:
        paths = [p for p in sorted(base.glob("*/STATUS.md")) if not p.parent.name.startswith("_")]
    try:
        inbox = _module("inbox", ROOT / "scripts" / "inbox.py").Inbox(
            root / "work" / "inbox", actor="task-review").open_items()
    except Exception:  # noqa: BLE001 - no inbox, no inbox evidence
        inbox = []
    rows = b._log_rows(root)
    tasks = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        fm = b._frontmatter(text)
        wanted = REVIEW_STATUSES + (("backlog",) if backlog else ())
        if not slugs and fm.get("status") not in wanted:
            continue
        # "runs on" (task.py wait): a check of all tasks leaves it alone until the day it names; named, it is checked
        if not slugs and str(fm.get("quiet_until") or "") >= (now_day or dt.date.today()).isoformat():
            continue
        slug = path.parent.name
        body = re.split(r"^---\s*$", text, maxsplit=2, flags=re.M)[-1]
        heading = re.search(r"^# (.+)$", body, flags=re.M)
        title = _plain(fm.get("title") or (heading.group(1) if heading else slug))
        steps = b.task_steps(body)
        nxt = fm.get("next") if isinstance(fm.get("next"), dict) else {}
        commit = run(["git", "-C", str(root), "log", "-1", "--format=%cs", "--", f"work/tasks/{slug}"], timeout=15)
        ev = {k: _plain(fm.get(k)) for k in ("status", "priority", "type", "created", "last_updated", "blocked_by",
                                               "blocked_since", "headline", "context", "origin")}
        for key, n in CLIP.items():   # a compact prompt: the opening of a long field carries its point
            if ev.get(key):
                ev[key] = b._clip(ev[key], n)
        ev.update({
            "next": _plain(f"{nxt.get('what')} (who: {nxt.get('who') or '?'})") if nxt.get("what") else None,
            "steps": steps, "log": b.task_log(rows, slug), "notes": _notes(body),
            "last_commit": (commit.stdout.strip() or None) if getattr(commit, "returncode", 1) == 0 else None,
            "inbox": [f"{i.kind}: {b._clip(str(i.summary), 100)} ({i.state})" for i in inbox
                      if getattr(i, "task", None) == slug],
            # what makes the task done, as its brief says (card_fields.py): evidence for a close verdict
            "acceptance": (validate_brief(fm["brief"])[0] or {}).get("acceptance") or None
            if isinstance(fm.get("brief"), dict) else None,
        })
        refs = _refs_of(fm, [fm.get("blocked_by"), fm.get("headline"), title, ev["next"], *steps])
        tasks.append({"slug": slug, "title": title, "evidence": ev, "refs": refs,
                      "own": _own_refs(fm), "blocker": _blocker_refs(fm)})
    states = resolve_refs(list(dict.fromkeys(r for t in tasks for r in t["refs"])), run)
    for t in tasks:
        t["evidence"]["github"] = {f"{r}#{n}": states[f"{r}#{n}"] for r, n in t["refs"]}
        t["signals"] = signals(t["own"], t["blocker"], states)
        t["evidence"]["signals"] = t["signals"]
        t["hash"] = hashlib.sha256(json.dumps(t["evidence"], sort_keys=True, default=str)
                                   .encode("utf-8")).hexdigest()[:16]
    return tasks


def _task_block(t: dict) -> str:
    ev = t["evidence"]
    out = [f"## {t['slug']}"]
    sig = t.get("signals") or {}
    names = [n for n in ("own_refs_closed", "blocker_resolved") if sig.get(n)]
    if names:   # first, so a small model cannot miss it
        what = ", ".join(f"{c.split(' ')[0]} closed {c.split(' ')[1]}" if " " in c else f"{c} closed"
                         for c in sig.get("closed_refs") or [])
        out.append(f"signals: {', '.join(names)}" + (f" ({what})" if what else ""))
    out.append(f"title: {t['title']}")
    head = ", ".join(f"{k}: {ev[k]}" for k in ("status", "priority", "type", "created", "last_updated") if ev.get(k))
    out.append(head)
    for key in ("headline", "origin", "blocked_by", "blocked_since", "next", "last_commit"):
        if ev.get(key):
            out.append(f"{key}: {ev[key]}")
    for key, label in (("acceptance", "acceptance"), ("steps", "open steps"), ("log", "log"), ("notes", "notes"),
                       ("inbox", "open inbox")):
        if ev.get(key):
            out.append(f"{label}: " + " | ".join(ev[key]))
    if not ev.get("log") and not ev.get("last_commit"):
        out.append("log: none")
    for key, ref in ev.get("github", {}).items():
        out.append("github: " + _ref_text(key, ref))
    return "\n".join(out)


def _json_array(text: str) -> list:
    text = re.sub(r"```(?:json)?", "", text or "")
    start, end = text.find("["), text.rfind("]")
    if not 0 <= start < end:
        return []
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        return []
    return [d for d in data if isinstance(d, dict)] if isinstance(data, list) else []


def ask_model(command: str, model: str, prompt: str, run, timeout: int) -> dict:
    """One model call. Claude's JSON envelope gives cost and the models actually used; any other
    command's plain stdout is read as the answer, cost unknown."""
    argv = [a.replace("{model}", model) for a in shlex.split(command)]
    done = run(argv, input=prompt, timeout=timeout)
    text, cost, used = (done.stdout or "") if done.returncode == 0 else "", None, []
    try:
        outer = json.loads(text)
        if isinstance(outer, dict) and "result" in outer:
            text = str(outer.get("result") or "")
            cost = outer.get("total_cost_usd")
            used = list((outer.get("modelUsage") or {}).keys())
    except ValueError:
        pass
    return {"items": _json_array(text), "cost": cost, "used": used, "ok": done.returncode == 0,
            "error": (done.stderr or "").strip()[-200:] if done.returncode != 0 else None}


def service_model(root: Path, service: str, default: str) -> str:
    choice = ai.select(root, service, default)
    return choice.model or "codex-default"


def ask_service(root: Path, service: str, command: str, model: str, prompt: str, run, timeout: int) -> dict:
    choice = ai.select(root, service, model)
    if choice.provider == "claude":
        return ask_model(command, choice.model or model, prompt, run, timeout)
    # The CLI's default model is deliberately not guessed from a release name.
    argv = ai.batch_argv(choice, prompt, binary="codex")
    done = run(argv, timeout=timeout, cwd=root)
    answer = ai.parse_codex(done.stdout or "") if done.returncode == 0 else None
    ok = bool(answer and not answer["error"])
    return {"items": _json_array(answer["text"]) if ok else [], "cost": None, "used": [], "ok": ok,
            "error": None if ok else ((answer or {}).get("text") or (done.stderr or "no completed answer"))[-200:]}


def _load_cache(root: Path) -> dict:
    try:
        data = json.loads((root / REVIEW_CACHE).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) and isinstance(data.get("tasks"), dict) else {"tasks": {}}
    except (OSError, ValueError):
        return {"tasks": {}}


def _save_cache(root: Path, cache: dict) -> None:
    path = root / REVIEW_CACHE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"version": 1, **cache}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def _summary(t: dict) -> str:
    ev = t["evidence"]
    parts = [ev.get("status") or "?"]
    if ev.get("blocked_by"):
        parts.append("blocked")
    for key, ref in ev.get("github", {}).items():
        state = "MERGED" if ref.get("merged") else ref.get("state")
        parts.append(f"{key} {state}" + (f"/{ref['reason']}" if ref.get("reason") and state == "CLOSED" else ""))
    last = max([r[:10] for r in ev.get("log") or []] + [ev.get("last_commit") or "", ev.get("last_updated") or ""])
    if last:
        parts.append(f"last activity {last}")
    if ev.get("steps"):
        parts.append(f"{len(ev['steps'])} open steps")
    if ev.get("inbox"):
        parts.append(f"{len(ev['inbox'])} inbox")
    return " · ".join(parts)


def _last_activity(ev: dict) -> dt.date | None:
    found = []
    for raw in [r[:10] for r in ev.get("log") or []] + [ev.get("last_commit"), ev.get("last_updated")]:
        try:
            found.append(dt.date.fromisoformat(str(raw)[:10]))
        except (TypeError, ValueError):
            continue
    return max(found) if found else None


def _chips(t: dict) -> list:
    """The evidence as structured chips for a dashboard: references, blocker, open steps, inbox."""
    ev, out = t["evidence"], []
    for key, ref in ev.get("github", {}).items():
        state = ("merged" if ref.get("merged") or ref.get("state") == "MERGED" else
                 "closed" if ref.get("state") == "CLOSED" else "open" if ref.get("state") == "OPEN" else "unknown")
        out.append({"kind": "ref", "ref": key, "state": state, "date": ref.get("closed_at")})
    if t["signals"]["blocker_resolved"]:
        out.append({"kind": "unblocked"})
    elif ev.get("blocked_by"):
        out.append({"kind": "blocked"})
    if ev.get("steps"):
        out.append({"kind": "steps", "count": len(ev["steps"])})
    if ev.get("inbox"):
        out.append({"kind": "inbox", "count": len(ev["inbox"])})
    return out


def review(root: Path, slugs=None, *, fresh: bool = False, run=None, now: dt.datetime | None = None,
           save: bool = True, backlog: bool = False, escalate: bool = False) -> dict:
    """A recommendation per open task; never changes a task. Only tasks whose evidence changed reach a model.
    `escalate` asks the directed model straight away, past the cache, for the named tasks only."""
    if escalate and not slugs:
        raise ValueError("--escalate needs the tasks named: review --escalate <slug> ...")
    run = run or default_run
    now = now or dt.datetime.now()
    started = _clock()
    cfg = _config(root)
    rcfg = _review_cfg(cfg)
    tiers = [service_model(root, "task-review", tier_model(cfg, tier)) for tier in ("mechanical", "directed")]
    if escalate:
        tiers, fresh = [tiers[1]], True
    tasks = gather(root, slugs, run, backlog=backlog, now_day=now.date())
    # a verdict holds for its evidence AND for what it was asked with: language, models, rule, prompt
    settings = json.dumps([_language(cfg), tiers, rcfg["stale_days"], PROMPT_VERSION,
                           ai.load(root, "task-review"), rcfg["command"]], sort_keys=True)
    for t in tasks:
        t["hash"] = hashlib.sha256(f"{t['hash']}|{settings}".encode("utf-8")).hexdigest()[:16]
    cache = _load_cache(root)
    entries = cache["tasks"]
    verdicts, need = {}, []
    for t in tasks:
        old = entries.get(t["slug"])
        if old and old.get("hash") == t["hash"] and not fresh:
            try:
                age = (now - dt.datetime.fromisoformat(str(old.get("at")))).days
            except ValueError:
                age = rcfg["max_age_days"] + 1
            if old.get("kept") or age <= rcfg["max_age_days"]:
                verdicts[t["slug"]] = {**old, "cached": True}
                continue
        need.append(t)
    previous = {s: (e or {}).get("verdict") for s, e in entries.items()}   # before this run writes anything
    cost, cost_known, used_all, mismatch, calls, by_model = 0.0, True, [], [], 0, {}
    batch = need
    answered = {}
    for level, model in enumerate(tiers):
        if not batch or (level == 1 and model == tiers[0]):
            break
        prompt = REVIEW_PROMPT.format(today=now.date().isoformat(), language=_language(cfg),
                                      stale_days=rcfg["stale_days"],
                                      tasks="\n\n".join(_task_block(t) for t in batch))
        left = REVIEW_BUDGET_SEC - (_clock() - started)
        if left < 10:
            break
        res = ask_service(root, "task-review", rcfg["command"], model, prompt, run,
                          int(min(left, TIER_ONE_MAX_SEC) if level == 0 else left))
        calls += 1
        if res["cost"] is None:
            cost_known = False          # a failed or timed-out call has a cost nobody reported
        else:
            cost += float(res["cost"])
            by_model[model] = by_model.get(model, 0.0) + float(res["cost"])
        used = res["used"] or ([model] if res["ok"] else [])
        used_all += [u for u in used if u not in used_all]
        if res["used"] and model not in res["used"]:
            mismatch.append({"requested": model, "used": res["used"]})
        actual = model if (not res["used"] or model in res["used"]) else res["used"][0]
        wanted = {t["slug"] for t in batch}
        for item in res["items"]:
            slug = str(item.get("slug") or "")
            if slug not in wanted:
                continue
            verdict = str(item.get("verdict") or "").lower()
            conf = str(item.get("confidence") or "").lower()
            answered[slug] = {"verdict": verdict if verdict in VERDICTS else "unclear",
                              "confidence": conf if conf in CONFIDENCES else "low",
                              "reason": _briefing()._clip(str(item.get("reason") or ""), 400), "model": actual}
        if save:   # what this tier answered is kept even when the next one runs out of time
            _remember(cache, need, answered, now, previous)
            _save_cache(root, cache)
        # only what the first model could not place goes on; a low confidence shows on the card instead
        batch = [t for t in batch if t["slug"] not in answered or answered[t["slug"]]["verdict"] == "unclear"]
    _remember(cache, need, answered, now, previous)
    for t in need:
        got = answered.get(t["slug"])
        verdicts[t["slug"]] = ({**entries[t["slug"]], "cached": False} if got else
                               {"verdict": "unclear", "confidence": "low", "reason": "no answer from the model",
                                "model": None, "cached": False, "kept": False})
    out = []
    for t in tasks:
        v = verdicts[t["slug"]]
        out.append({"slug": t["slug"], "title": t["title"], "verdict": v.get("verdict"), "reason": v.get("reason"),
                    "confidence": v.get("confidence"), "model": v.get("model"), "cached": bool(v.get("cached")),
                    "kept": bool(v.get("kept")), "evidence_summary": _summary(t), "signals": t["signals"],
                    # deterministic: the task's own issues and PRs are done, so closing is recommended,
                    # whatever the model said; a resolved blocker alone is only a hint
                    "resolved": t["signals"]["own_refs_closed"],
                    "status": t["evidence"].get("status"), "priority": t["evidence"].get("priority"),
                    "days_since_activity": (now.date() - last).days if (last := _last_activity(t["evidence"]))
                    else None,
                    "chips": _chips(t), "previous_verdict": v.get("previous"),
                    "changed": bool(v.get("previous")) and v.get("previous") != v.get("verdict")})
    result = {"tasks": out, "cost_usd": round(cost, 6), "cost_known": cost_known, "models_used": used_all,
              "cost_by_model": {m: round(c, 6) for m, c in by_model.items()},
              # what "check closer" will cost: one call of the directed model, measured when this run made one
              "escalate_call_usd": (None if ai.select(root, "task-review").provider == "codex" else
                                    round(by_model.get(tier_model(cfg, "directed"), DIRECTED_CALL_USD), 6)),
              "model_mismatch": mismatch, "calls": calls, "reviewed": len(out),
              "to_close": sum(1 for x in out if (x["verdict"] == "close" or x["resolved"]) and not x["kept"]),
              "reviewed_at": now.isoformat(timespec="seconds"), "duration_sec": round(_clock() - started, 1)}
    if save:   # the dashboard's overview reads the last run from here, with no model call
        last = cache.get("last") if isinstance(cache.get("last"), dict) else None
        if slugs and last:
            mine = {x["slug"]: x for x in out}
            seen = {x.get("slug") for x in last.get("tasks", [])}
            last = {**last, "tasks": [mine.get(x.get("slug"), x) for x in last.get("tasks", [])]
                    + [x for x in out if x["slug"] not in seen]}
        else:
            last = result
        cache["last"] = last
        _save_cache(root, cache)
    return result


def _remember(cache: dict, need: list, answered: dict, now: dt.datetime, previous: dict | None = None) -> None:
    """Put the answered verdicts into the cache; a kept dismissal survives as long as its hash does,
    and the verdict before this run is kept beside the new one, for "changed"."""
    entries = cache["tasks"]
    for t in need:
        got = answered.get(t["slug"])
        if not got:
            continue
        old = entries.get(t["slug"]) or {}
        entries[t["slug"]] = {**got, "hash": t["hash"], "at": now.isoformat(timespec="seconds"),
                              "resolved": t["signals"]["own_refs_closed"],
                              "previous": (previous or {}).get(t["slug"]),
                              "kept": bool(old.get("kept")) and old.get("hash") == t["hash"]}


def keep(root: Path, slugs) -> dict:
    """Dismiss the recommendation of these tasks until their evidence changes."""
    cache = _load_cache(root)
    missing = [s for s in slugs if s not in cache["tasks"]]
    if missing:
        raise ValueError(f"no recommendation to keep for: {', '.join(missing)}")
    for s in slugs:
        cache["tasks"][s]["kept"] = True
    # the dashboard's overview reads the last run: it shows the dismissal at once, not after the next check
    last = cache.get("last") if isinstance(cache.get("last"), dict) else None
    for t in (last or {}).get("tasks") or []:
        if isinstance(t, dict) and t.get("slug") in slugs:
            t["kept"] = True
    _save_cache(root, cache)
    return {"kept": list(slugs)}


def render_review(result: dict) -> str:
    lines = []
    width = max([len(t["slug"]) for t in result["tasks"]] + [4])
    for t in result["tasks"]:
        model = (t["model"] or "-").replace("claude-", "")
        flag = " (kept)" if t["kept"] else " (cached)" if t["cached"] else ""
        if t["resolved"] and t["verdict"] != "close":
            flag += f" [signal: {', '.join(t['signals']['closed_refs'])} closed]"
        lines.append(f"{t['slug']:<{width}}  {t['verdict']:<8}  {t['confidence'] or '':<6}  {model:<12}  "
                     f"{t['reason']}{flag}")
    cost = f"{result['cost_usd']:.4f} USD" + ("" if result["cost_known"] else " (+ unknown)")
    lines.append(f"{result['reviewed']} reviewed, {result['to_close']} to close · {result['calls']} model call(s) · "
                 f"{cost} · models: {', '.join(result['models_used']) or 'none'}")
    for m in result["model_mismatch"]:
        lines.append(f"WARNING: asked for {m['requested']}, answered by {', '.join(m['used'])}")
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="task.py", description="Small write commands for STATUS.md.")
    p.add_argument("--root", type=Path, default=ROOT, help="repository root (default: this checkout)")
    sub = p.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("priority", help="set a task's priority")
    pr.add_argument("slug")
    pr.add_argument("value", choices=PRIORITIES)
    nt = sub.add_parser("note", help="append a dated note to a task's notes section")
    nt.add_argument("slug")
    nt.add_argument("text")
    cl = sub.add_parser("close", help="the 3-step close: fields, move to work/done/YYYY-MM/, board, log row")
    cl.add_argument("slug")
    cl.add_argument("--reason", default="")
    cl.add_argument("--declined", action="store_true", help="closed without completion (outcome: declined)")
    cl.add_argument("--merged-into", dest="merged_into", metavar="KEEP",
                    help="closed as merged into this task (outcome: merged, merged_into)")
    cl.add_argument("--stream", action="store_true", help="also end a stream (reopen puts it back under work/streams/)")
    cl.add_argument("--json", action="store_true")
    ro = sub.add_parser("reopen", help="the inverse of close: back to work/tasks/, status, note, board, log row")
    ro.add_argument("slug")
    ro.add_argument("--as", dest="as_status", choices=REOPEN_STATUSES, default="doing")
    ro.add_argument("--note", default="")
    ro.add_argument("--json", action="store_true")
    mg = sub.add_parser("merge", help="close a task as merged into another, its notes, open steps and documents "
                                      "linked in a section of the one that stays")
    mg.add_argument("keep")
    mg.add_argument("--from", dest="from_slug", required=True, metavar="SLUG")
    mg.add_argument("--heading", default=None, help=f'the section\'s heading, "{{slug}}" replaced (default "{MERGE_HEADING}")')
    mg.add_argument("--json", action="store_true")
    um = sub.add_parser("unmerge", help="take a merge back: the section goes, the merged task opens again")
    um.add_argument("keep")
    um.add_argument("--from", dest="from_slug", required=True, metavar="SLUG")
    um.add_argument("--as", dest="as_status", choices=REOPEN_STATUSES, default="doing")
    um.add_argument("--json", action="store_true")
    sh = sub.add_parser("shelve", help="park a finite task nobody works on: an idea in the inbox, deferred, "
                                       "and the task closed as declined")
    sh.add_argument("slug")
    sh.add_argument("--until", help=f"YYYY-MM-DD, the day the idea may surface again (default: today + {SHELVE_DAYS} days)")
    sh.add_argument("--reason", default="")
    sh.add_argument("--json", action="store_true")
    wt = sub.add_parser("wait", help="runs on: waits on a person or a run until a day, nobody asks before")
    wt.add_argument("slug")
    wt.add_argument("--until", help="YYYY-MM-DD, the day to look again")
    wt.add_argument("--on", default=None, help="what it waits on; without it simply \"runs on\"")
    wt.add_argument("--clear", action="store_true", help="running again: blocked_by and quiet_until go")
    wt.add_argument("--json", action="store_true")
    lg = sub.add_parser("log", help="one row in today's block of work/log.md, for a decision on a row with no task or "
                                    "inbox item of its own (an issue, a deadline)")
    lg.add_argument("context")
    lg.add_argument("text")
    nx = sub.add_parser("next", help="set the task's next step (next: {what}) with a dated note, or --clear it")
    nx.add_argument("slug")
    nx.add_argument("text", nargs="?")
    nx.add_argument("--clear", action="store_true")
    nx.add_argument("--json", action="store_true")
    nw = sub.add_parser("new", help="a new task in work/tasks/, also from an inbox item (which then closes)")
    nw.add_argument("slug", nargs="?")
    nw.add_argument("--headline")
    nw.add_argument("--from-inbox", dest="from_inbox")
    nw.add_argument("--status", choices=NEW_STATUSES, default="backlog")
    nw.add_argument("--type", dest="task_type", default="admin")
    nw.add_argument("--json", action="store_true")
    br = sub.add_parser("brief", help="write or replace the task's brief block (goal, story, acceptance), "
                                      "or --mark-edited after a person changed it")
    br.add_argument("slug")
    br.add_argument("--brief-json", dest="brief_json", help='{"goal": "...", "acceptance": [...], "by": "<model id>"}')
    br.add_argument("--basis", help="the brief_basis it was written against; refused when the file moved on")
    br.add_argument("--edited", action="store_true", help="a person wrote it (edited: true)")
    br.add_argument("--mark-edited", dest="mark_edited", action="store_true",
                    help="only set edited: true in the block as it stands")
    br.add_argument("--json", action="store_true")
    rv = sub.add_parser("review", help="recommend close/continue/waiting/stale/unclear per open task")
    rv.add_argument("slugs", nargs="*")
    rv.add_argument("--all", action="store_true", help="every task in doing or review (the default without slugs)")
    rv.add_argument("--backlog", action="store_true", help="with --all: backlog tasks too")
    rv.add_argument("--fresh", action="store_true", help="ignore cached verdicts")
    rv.add_argument("--keep", nargs="+", metavar="SLUG", help="dismiss these recommendations until the evidence changes")
    rv.add_argument("--escalate", action="store_true",
                    help="ask the directed model at once for the named tasks, past the cache")
    rv.add_argument("--no-save", action="store_true", help="write no cache (a read-only run)")
    rv.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    root = args.root.resolve()
    today = dt.date.today().isoformat()
    try:
        if args.cmd == "close":
            out = close_task(root, args.slug, reason=args.reason, declined=args.declined, stream=args.stream,
                             merged_into=args.merged_into)
            print(json.dumps(out, ensure_ascii=False) if args.json else f"closed {out['slug']} -> {out['moved_to']}")
            for warning in out["warnings"]:
                print(f"task: warning: {warning}", file=sys.stderr)
            return 0
        if args.cmd == "reopen":
            out = reopen_task(root, args.slug, status=args.as_status, note=args.note)
            print(json.dumps(out, ensure_ascii=False) if args.json else f"reopened {out['slug']} <- {out['moved_from']}")
            for warning in out["warnings"]:
                print(f"task: warning: {warning}", file=sys.stderr)
            return 0
        if args.cmd in ("merge", "unmerge"):
            out = (merge_task(root, args.keep, args.from_slug, heading=args.heading) if args.cmd == "merge"
                   else unmerge_task(root, args.keep, args.from_slug, status=args.as_status))
            print(json.dumps(out, ensure_ascii=False) if args.json else
                  f"{args.cmd}d {out['slug']} {'into' if args.cmd == 'merge' else 'from'} {out['keep']}")
            for warning in out["warnings"]:
                print(f"task: warning: {warning}", file=sys.stderr)
            return 0
        if args.cmd == "shelve":
            out = shelve_task(root, args.slug, until=args.until, reason=args.reason)
            print(json.dumps(out, ensure_ascii=False) if args.json else
                  f"shelved {out['slug']} -> {out['moved_to']} (idea {out['inbox']}, until {out['until']})")
            for warning in out["warnings"]:
                print(f"task: warning: {warning}", file=sys.stderr)
            return 0
        if args.cmd == "wait":
            out = wait_task(root, args.slug, until=args.until, on=args.on, clear=args.clear)
            print(json.dumps(out, ensure_ascii=False) if args.json else
                  (f"{out['slug']} running again" if args.clear else f"{out['slug']} runs on until {out['quiet_until']}"))
            return 0
        if args.cmd == "next":
            if args.clear and args.text is not None:
                raise ValueError("a step or --clear, not both")
            out = set_next(root, args.slug, args.text, clear=args.clear)
            print(json.dumps(out, ensure_ascii=False) if args.json else
                  (f"{out['slug']}: next step cleared" if args.clear else f"{out['slug']}: next {out['next']}"))
            return 0
        if args.cmd == "brief":
            if args.mark_edited == bool(args.brief_json) or (args.mark_edited and (args.basis or args.edited)):
                raise ValueError("give --brief-json or --mark-edited, not both and not neither")
            if args.mark_edited:
                out = mark_brief_edited(root, args.slug)
            else:
                try:
                    data = json.loads(args.brief_json)
                except ValueError:
                    raise ValueError("brief: --brief-json is no JSON") from None
                out = write_brief(root, args.slug, data, basis=args.basis, edited=args.edited, today=today)
            print(json.dumps(out, ensure_ascii=False) if args.json else f"{out['slug']}: brief written")
            return 0
        if args.cmd == "log":
            what = " ".join(args.text.split())
            if not what:
                raise ValueError("empty log row")
            append_log_row(root, dt.datetime.now(), " ".join(args.context.split()) or "cockpit", what)
            return 0
        if args.cmd == "new":
            out = new_task(root, args.slug, headline=args.headline, status=args.status, from_inbox=args.from_inbox,
                           task_type=args.task_type)
            print(json.dumps(out, ensure_ascii=False) if args.json else f"new task {out['slug']} ({out['status']})")
            for warning in out["warnings"]:
                print(f"task: warning: {warning}", file=sys.stderr)
            return 0
        if args.cmd == "review":
            if args.keep:
                out = keep(root, args.keep)
                print(json.dumps(out) if args.json else f"kept: {', '.join(out['kept'])}")
                return 0
            if args.all and args.slugs:
                raise ValueError("name slugs or --all, not both")
            out = review(root, args.slugs or None, fresh=args.fresh, save=not args.no_save,
                         backlog=args.backlog, escalate=args.escalate)
            print(json.dumps(out, ensure_ascii=False) if args.json else render_review(out))
            return 0
        path = find_status(root, args.slug)
        old = path.read_bytes().decode("utf-8")   # bytes: read_text would turn CRLF into LF
        new = (set_priority(old, args.value, today) if args.cmd == "priority"
               else add_note(old, args.text, today))
    except (ValueError, OSError) as exc:
        print(f"task: {exc}", file=sys.stderr)
        return 1
    path.write_bytes(new.encode("utf-8"))
    try:
        regenerate_board(root)
    except Exception as exc:  # noqa: BLE001 - the file is written; a stale board is a warning
        print(f"task: written, but the board failed: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
