#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Small write commands for a task's STATUS.md.

    python3 scripts/task.py priority <slug> {P0,P1,P2,P3}
    python3 scripts/task.py note <slug> <text>
    python3 scripts/task.py close <slug> [--reason TEXT] [--declined] [--json]
    python3 scripts/task.py reopen <slug> [--as doing|backlog] [--note TEXT] [--json]
    python3 scripts/task.py review [slug ...] [--all] [--fresh] [--keep SLUG ...] [--json]
    python3 scripts/task.py wait <slug> --until YYYY-MM-DD [--on TEXT] | --clear [--json]
    python3 scripts/task.py new [slug] --headline TEXT | --from-inbox ID [--status backlog|doing] [--json]

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

``reopen`` is the inverse of close, for a close by mistake or a task that still has to
be done: the newest work/done/*/<slug>/ moves back to work/tasks/<slug>/, ``status``
becomes doing (or ``--as backlog``), ``closed:`` and ``outcome:`` go, a dated
"Reopened" note joins the notes (the close note stays, so the history reads), the
board is regenerated and one log row is written. A slug that is open is refused.

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

def close_task(root: Path, slug: str, *, reason: str | None = None, declined: bool = False,
               stream: bool = False, now: dt.datetime | None = None) -> dict:
    """The 3-step close of docs/work-system.md: fields and note, move to work/done/YYYY-MM/, board, log row.
    stream also ends a stream: a stream never completes on its own, but a person may end one (the customer left,
    the chance passed). It closes like a task and keeps was_stream, so reopen puts it back under work/streams/."""
    now = now or dt.datetime.now()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", slug):
        raise ValueError(f"not a task slug: {slug!r}")
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
    if was_stream:
        fields.append(("was_stream", "true", "closed"))
    # a normal close drops an old "outcome: declined", which would otherwise survive and mislabel the task
    text = remove_fields(set_fields(text, fields), ("blocked_by", "blocked_since") + (() if declined else ("outcome",)))
    word = "Declined" if declined else "Closed"
    said = ("Stream ended, declined" if declined else "Stream ended") if was_stream else word
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
        append_log_row(root, now, slug, f"{word.lower()}" + (f": {reason}" if reason else ""))
    except Exception as exc:  # noqa: BLE001 - the task is closed; a missing row is a warning
        warnings.append(f"work/log.md row not written: {exc}")
    return {"slug": slug, "moved_to": f"work/done/{now:%Y-%m}/{slug}", "closed": today,
            "outcome": "declined" if declined else None, "reason": reason or None, "stream": was_stream,
            "warnings": warnings}


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
    text = remove_fields(set_fields(text, [("status", status, None)]), ("closed", "outcome", "was_stream"))
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
    return {"slug": slug, "moved_from": str(src.relative_to(root)), "moved_to": str(dest.relative_to(root)),
            "status": status, "note": note or None, "warnings": warnings}


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
PROMPT_VERSION = 3          # raise when the prompt changes: cached verdicts of an older prompt are asked again
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
    return {"command": rv.get("command") or DEFAULT_REVIEW_COMMAND,
            "max_age_days": number("max_age_days", DEFAULT_MAX_AGE_DAYS),
            "stale_days": number("stale_days", DEFAULT_STALE_DAYS)}


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
    for key, label in (("steps", "open steps"), ("log", "log"), ("notes", "notes"), ("inbox", "open inbox")):
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
    cl.add_argument("--stream", action="store_true", help="also end a stream (reopen puts it back under work/streams/)")
    cl.add_argument("--json", action="store_true")
    ro = sub.add_parser("reopen", help="the inverse of close: back to work/tasks/, status, note, board, log row")
    ro.add_argument("slug")
    ro.add_argument("--as", dest="as_status", choices=REOPEN_STATUSES, default="doing")
    ro.add_argument("--note", default="")
    ro.add_argument("--json", action="store_true")
    wt = sub.add_parser("wait", help="runs on: waits on a person or a run until a day, nobody asks before")
    wt.add_argument("slug")
    wt.add_argument("--until", help="YYYY-MM-DD, the day to look again")
    wt.add_argument("--on", default=None, help="what it waits on; without it simply \"runs on\"")
    wt.add_argument("--clear", action="store_true", help="running again: blocked_by and quiet_until go")
    wt.add_argument("--json", action="store_true")
    nw = sub.add_parser("new", help="a new task in work/tasks/, also from an inbox item (which then closes)")
    nw.add_argument("slug", nargs="?")
    nw.add_argument("--headline")
    nw.add_argument("--from-inbox", dest="from_inbox")
    nw.add_argument("--status", choices=NEW_STATUSES, default="backlog")
    nw.add_argument("--type", dest="task_type", default="admin")
    nw.add_argument("--json", action="store_true")
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
            out = close_task(root, args.slug, reason=args.reason, declined=args.declined, stream=args.stream)
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
        if args.cmd == "wait":
            out = wait_task(root, args.slug, until=args.until, on=args.on, clear=args.clear)
            print(json.dumps(out, ensure_ascii=False) if args.json else
                  (f"{out['slug']} running again" if args.clear else f"{out['slug']} runs on until {out['quiet_until']}"))
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
