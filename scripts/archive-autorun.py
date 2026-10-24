#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The scheduled archive: everything in /archive that is provably mechanical.

    python3 scripts/archive-autorun.py [--dry-run] [--today YYYY-MM-DD]

WHAT IT DELIBERATELY DOES NOT DO. It does not run a model. `/archive` Phase 4
writes a narrative and Phase 5 selects durable facts, and both are judgement; a
scheduled job that spawned an agent with write access to the work log would be
the largest unattended blast radius in this repo, and board-pilot's own fenced
call site warns that copying that fence is how a future fix lands in one of three
places. So this job does the mechanical half and RECORDS the other half as an
obligation, instead of doing it badly or pretending it is done.

Mechanical, and all of it verified:
  · the plan            scripts/archive-buckets.py, one entry per period
  · the raw backups     each holding ONLY its own period's day-blocks
  · a metrics summary   counts and pointers, marked as un-narrated
  · the reset           open periods retained, unchecked items and the owed
                        judgement filed in the inbox (scripts/inbox.py), not in
                        a TODO block nothing ever closes; without an inbox they
                        stay in the log, so nothing is lost
Judgement, left to a human-run `/archive` over the raws, which lose nothing:
  · the narrative sections of each summary
  · Phase 5 distillation into the memory base

ORDER IS THE SAFETY PROPERTY. Every file is written and verified non-empty before
`log.md` is touched, because until then the log is the only place those rows exist.
A pre-existing archive file is never overwritten: that is either a re-run or a
collision, and both want a human.

Contract: scripts/tests/test_archive_autorun.py
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BLOCK_RE = re.compile(r"^## \S+ (\d{2})\.(\d{2})(?:[^0-9.]|$)", re.M)


def _buckets_mod():
    spec = importlib.util.spec_from_file_location("ab", HERE / "archive-buckets.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def day_blocks(text: str) -> dict[str, str]:
    marks = list(BLOCK_RE.finditer(text))
    out = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        out[f"{m.group(1)}.{m.group(2)}"] = text[m.start():end].rstrip() + "\n"
    return out


def file_in_inbox(items: list[tuple[str, str, str]]) -> str | None:
    """File (key, summary, detail) items in work/inbox; None on success, else why not.

    Keys make a re-run file nothing twice. Any failure is reported, never
    raised: the caller then keeps the items in the log instead.
    """
    path = HERE / "inbox.py"
    if not path.is_file():
        return "scripts/inbox.py not found"
    try:
        sys.path.insert(0, str(HERE))
        spec = importlib.util.spec_from_file_location("inbox_for_archive", path)
        mod = importlib.util.module_from_spec(spec)
        # Registered before exec: on Python 3.12 @dataclass looks its module up
        # in sys.modules and fails on an unregistered one.
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        box = mod.Inbox(ROOT / "work" / "inbox", actor="archive-autorun")
        for key, summary, detail in items:
            box.add(source="archive-autorun", kind="finding", summary=summary,
                    urgency="later", detail=detail, key=key, closer="person")
    except Exception as exc:  # noqa: BLE001 - any failure keeps the items in the log
        return f"{type(exc).__name__}: {exc}"
    finally:
        if sys.path and sys.path[0] == str(HERE):
            sys.path.pop(0)
    return None


def todo_key(line: str, today: _dt.date) -> str:
    """Inbox key of one carried TODO line: readable slug, but unique by hash.

    The slug alone collapses non-ASCII text and long shared prefixes, and
    Inbox.add would then absorb the second item into the first. The date
    keeps a new TODO with old wording from landing on an item dropped in an
    earlier archive; a re-run on the same day still files nothing twice.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", line[len("- [ ] "):].lower()).strip("-")[:40]
    digest = hashlib.sha1(line.encode("utf-8")).hexdigest()[:10]
    return f"log-todo-{today.isoformat()}-{slug or 'item'}-{digest}"


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True,
                          cwd=ROOT).stdout.strip()


def summary_text(b: dict, rows: int, commits: int, contexts: list[str]) -> str:
    return "\n".join([
        f"# {b['label']} — {b['first']} to {b['last']}", "",
        "> **Metrics only — not narrated.** Written by the scheduled archive, which",
        "> does not run a model. The Done / Blockers / Highlights sections a human or",
        f"> agent would write are still owed; every row is in [`{b['stem']}-raw.md`]"
        f"(./{b['stem']}-raw.md), so nothing is lost by filling them in later.", "",
        "## Metrics", "",
        f"- Commits: {commits}",
        f"- Worklog rows: {rows}",
        f"- Contexts touched: {', '.join(contexts) if contexts else '—'}",
        f"- Day blocks: {len(b['day_blocks'])} ({', '.join(b['day_blocks'])})", "",
        "## Done", "", "_not narrated — see the raw log_", "",
        "## Blockers / Defects", "", "_not narrated — see the raw log_", "",
        "## Highlights / Learnings", "", "_not narrated — see the raw log_", "",
        "---", "",
        f"Raw log: [`{b['stem']}-raw.md`](./{b['stem']}-raw.md)", "",
    ])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--today")
    a = ap.parse_args(argv)

    import yaml
    cfg = yaml.safe_load((ROOT / "bridge-config.yaml").read_text()) or {}
    if not (cfg.get("work") or {}).get("enabled"):
        print("archive-autorun: work.enabled is not true; nothing to do")
        return 0

    branch = git("branch", "--show-current")
    if not branch.startswith("user/"):
        print(f"archive-autorun: refused, not on a user/* branch (on '{branch or 'detached'}')")
        return 3

    ab = _buckets_mod()
    cadence = ab.resolve_cadence((cfg.get("work") or {}).get("archive_cadence"))
    today = _dt.date.fromisoformat(a.today) if a.today else _dt.date.today()
    log_path = ROOT / "work" / "log.md"
    text = log_path.read_text(encoding="utf-8")
    plan = ab.plan(text, cadence, today)
    todo = [b for b in plan if b["archive"]]
    if not todo:
        print(f"archive-autorun: nothing closed ({cadence}); the open period stays")
        return 0

    blocks = day_blocks(text)
    # Never overwrite an existing archive: a collision wants a human, not a guess.
    for b in todo:
        for p in (ROOT / b["dir"] / f"{b['stem']}.md", ROOT / b["dir"] / f"{b['stem']}-raw.md"):
            if p.exists():
                print(f"archive-autorun: refused, {p.relative_to(ROOT)} already exists")
                return 3

    written: list[Path] = []
    for b in todo:
        d = ROOT / b["dir"]
        if not a.dry_run:
            d.mkdir(parents=True, exist_ok=True)
        body = "".join(blocks[k] for k in b["day_blocks"] if k in blocks)
        rows = len(re.findall(r"^\|\s*\d{4}-\d{2}-\d{2}[ T]", body, re.M))
        ctx = sorted({m.group(1).strip() for m in re.finditer(
            r"^\|\s*\d{4}-\d{2}-\d{2}[^|]*\|[^|]*\|([^|]+)\|", body, re.M)})
        commits = len(git("log", "--oneline", "--first-parent", "--no-merges",
                          f"--after={b['first']} 00:00",
                          f"--before={b['last']} 23:59").splitlines())
        raw = (f"# RAW — {b['label']} ({b['first']} to {b['last']})\n\n"
               f"<!-- Unprocessed day-blocks, exactly as they stood in work/log.md\n"
               f"     before the scheduled archive of {today.isoformat()}. -->\n\n" + body)
        for p, content in ((d / f"{b['stem']}-raw.md", raw),
                           (d / f"{b['stem']}.md", summary_text(b, rows, commits, ctx))):
            if not a.dry_run:
                p.write_text(content, encoding="utf-8")
            written.append(p)

    if not a.dry_run:
        missing = [p for p in written if not p.exists() or p.stat().st_size == 0]
        if missing:
            print("archive-autorun: ABORTED before the reset, "
                  f"{len(missing)} file(s) missing or empty: "
                  + ", ".join(str(p.relative_to(ROOT)) for p in missing[:3]))
            return 1

    kept = [b for b in plan if not b["archive"]]
    keep_keys = [k for b in kept for k in b["day_blocks"]]
    # Only what leaves the log is filed: the preamble and the archived
    # day-blocks. A TODO in a block that stays would be filed now and again
    # when its period closes, reopening an item closed in between.
    first = BLOCK_RE.search(text)
    leaving = (text[:first.start()] if first else text) + "".join(
        blocks[k] for b in todo for k in b["day_blocks"] if k in blocks)
    todos, seen = [], set()
    for line in leaving.splitlines():
        if line.startswith("- [ ] "):
            key = re.sub(r"\W+", "", line.lower())  # whole line: a prefix cap merged distinct items
            if key not in seen:
                seen.add(key); todos.append(line)
    label = kept[0]["label"] if kept else ab.describe(ab.bucket_of(today, cadence), cadence)["label"]
    obligation = (f"- [ ] {len(todo)} period(s) archived mechanically on "
                  f"{today.isoformat()} — narrative summaries and Phase 5 distillation "
                  f"still owed; run `/archive` over work/archive to fill them in")
    carried = [t for t in todos if t != obligation]
    # Open items go to the inbox, where something closes them (docs/inbox.md).
    # A rolling TODO block in the log is a sentence nobody ever closes.
    detail = f"carried from work/log.md by the scheduled archive of {today.isoformat()}"
    items = [(f"archive-autorun-owed-{today.isoformat()}", obligation[len("- [ ] "):], detail)]
    items += [(todo_key(t, today), t[len("- [ ] "):], detail) for t in carried]
    why_not = None if a.dry_run else file_in_inbox(items)
    parts = [f"# {label} — scheduled archive {today.isoformat()}", ""]
    new_log = "\n".join(parts) + "".join(blocks[k] for k in keep_keys)
    if why_not is not None:
        new_log += ("\n### Carried over\n\n" + obligation + "\n"
                    + "\n".join(carried) + "\n")
    if not a.dry_run:
        log_path.write_text(new_log, encoding="utf-8")

    verb = "would archive" if a.dry_run else "archived"
    print(f"archive-autorun: {verb} {len(todo)} period(s), "
          f"{sum(b['rows'] for b in todo)} rows, {len(written)} files")
    for b in todo:
        print(f"  {b['label']:<14} {b['rows']:>3} rows → {b['dir']}/{b['stem']}.md")
    if kept:
        print(f"  {kept[0]['label']} stays in the log ({kept[0]['rows']} rows)")
    if a.dry_run:
        print(f"  would file {len(items)} open item(s) in the inbox")
    elif why_not is None:
        print(f"  {len(items)} open item(s) filed in the inbox, narrative + "
              "distillation among them")
    else:
        print(f"  inbox unavailable ({why_not}); {len(items)} open item(s) kept "
              "in the log under 'Carried over'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
