#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Briefing advice: the checks that turn a list of open things into something to act on.

A briefing that lists everything leaves the choosing to the reader. These checks
name what a person would want to know first, from the inbox, the task folders
and (when the caller passes it) today's calendar:

  collision  an inbox item with a due TIME overlaps a calendar event
  quiet      an active task nobody touched for `stale_days`; urgency today for a
             customer context (a relationship goes stale silently), later otherwise
  blocked    a blocked task idle for `blocked_days`: nudge whoever blocks it
  wip        doing + review above work.max_active
  waiting    a decision or draft waiting on a person for `waiting_days` (report only:
             it already is an item)
  due        an open item due within a day (report only)

    python3 skills/briefing/scripts/advise.py [--calendar-json FILE] [--json]
    python3 skills/briefing/scripts/advise.py --file    # findings become inbox items

With --file each finding is an inbox item under the key `advise:<check>:<subject>`,
so a repeat is one item (with its summary refreshed), and an advise item whose
finding is gone is closed on the next run that performed that check. A finding a
person dropped is not filed again. Items it did not create are never touched.

Thresholds: bridge-config.yaml `briefing.advise` (stale_days 7, blocked_days 14,
waiting_days 2, collision_minutes 60, customer_contexts []). The calendar is a JSON
list of {"title", "start", "end"} in ISO form, produced by whatever calendar source
the instance has (the briefing's Stream C); without it the collision check is skipped.
An event with "info": true (from a section's `info_calendars`) never collides.
Contract: skills/briefing/tests/test_advise.py.
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import re
import sys
import threading
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]
DEFAULTS = {"stale_days": 7, "blocked_days": 14, "waiting_days": 2, "collision_minutes": 60,
            "customer_contexts": []}
KEY_PREFIX = "advise:"


_LOADING = threading.Lock()


def _load_inbox():
    with _LOADING:
        return _load_inbox_locked()


def _load_inbox_locked():
    if "inbox" in sys.modules and hasattr(sys.modules["inbox"], "Inbox"):
        return sys.modules["inbox"]
    spec = importlib.util.spec_from_file_location("inbox", REPO / "scripts" / "inbox.py")
    if spec is None or spec.loader is None:  # pragma: no cover
        raise RuntimeError("cannot load scripts/inbox.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["inbox"] = module
    previous, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


# the words of a finding in the instance's conversation language (bridge-config.yaml language.conversation);
# a language not here reads English
TEXTS = {
    "en": {"collides": "“{item}” at {start} collides with “{event}” {e_start} to {e_end}",
           "blocked": "{slug} blocked for {idle} days: nudge? ({why})",
           "quiet": "{slug} untouched for {idle} days", "quiet_customer": " (customer: push or park?)",
           "quiet_park": " (park?)", "wip": "{n} tasks active, cap {cap}: close or park one",
           "waiting": "waits on you since {day}: {item}", "due": "due {day}: {item}"},
    "de": {"collides": "„{item}“ am {start} überschneidet sich mit „{event}“ {e_start} bis {e_end}",
           "blocked": "{slug} seit {idle} Tagen blockiert: nachhaken? ({why})",
           "quiet": "{slug} seit {idle} Tagen unberührt", "quiet_customer": " (Kunde: anschieben oder parken?)",
           "quiet_park": " (parken?)", "wip": "{n} Aufgaben aktiv, Grenze {cap}: eine schließen oder parken",
           "waiting": "wartet seit {day} auf dich: {item}", "due": "fällig {day}: {item}"},
}


def _config(root: Path) -> tuple[dict, int | None]:
    path = root / "bridge-config.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else {}
    data = data or {}
    advise_cfg = {**DEFAULTS, **(((data.get("briefing") or {}).get("advise")) or {})}
    lang = data.get("language")
    code = str((lang.get("conversation") if isinstance(lang, dict) else lang) or "en").strip().lower()
    advise_cfg["_words"] = TEXTS.get(code, TEXTS["en"])
    return advise_cfg, (data.get("work") or {}).get("max_active")


def _frontmatter(text: str) -> dict:
    parts = re.split(r"^---\s*$", text, maxsplit=2, flags=re.M)
    try:
        return (yaml.safe_load(parts[1]) or {}) if len(parts) == 3 else {}
    except yaml.YAMLError:
        return {}


def _day(value) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _when(value) -> dt.datetime | None:
    text = str(value or "")
    if "T" not in text and " " not in text.strip():
        return None
    try:
        return dt.datetime.fromisoformat(text).replace(tzinfo=None)
    except ValueError:
        return None


def _tasks(root: Path) -> list:
    out = []
    for status in sorted((root / "work" / "tasks").glob("*/STATUS.md")):
        if status.parent.name.startswith("_"):
            continue
        text = status.read_text(encoding="utf-8")
        fm = _frontmatter(text)
        if fm.get("status") in ("doing", "review"):
            slug = fm.get("slug") or status.parent.name
            # a row names the work by its title (the H1), the key keeps the slug
            h1 = next((ln[2:].strip() for ln in text.split("\n---", 2)[-1].splitlines() if ln.startswith("# ")), "")
            out.append({"slug": slug, "title": h1 or slug, "context": fm.get("context"),
                        "blocked_by": fm.get("blocked_by"), "updated": _day(fm.get("last_updated")),
                        "quiet_until": _day(fm.get("quiet_until"))})
    return out


def _finding(check, subject, summary, urgency, task=None, file=True) -> dict:
    return {"check": check, "key": f"{KEY_PREFIX}{check}:{subject}", "summary": summary,
            "urgency": urgency, "task": task, "file": file}


def advise(root: Path, *, now: dt.datetime | None = None, calendar: list | None = None,
           inbox=None) -> list:
    """`inbox` is scripts/inbox.py as the caller loaded it. The briefing passes its own,
    loaded under its lock, since its sections run side by side; alone, advise loads it."""
    now = now or dt.datetime.now()
    today = now.date()
    cfg, max_active = _config(root)
    w = cfg["_words"]
    inbox = inbox or _load_inbox()
    box = inbox.Inbox(root / "work" / "inbox", actor="briefing", clock=lambda: now)
    items = box.open_items()
    found = []

    window = dt.timedelta(minutes=int(cfg["collision_minutes"]))
    for item in items:
        start = _when(item.due)
        if not start or not calendar:
            continue
        for event in calendar:
            if event.get("info") is True:   # an info calendar's event is someone else's
                continue
            e_start, e_end = _when(event.get("start")), _when(event.get("end"))
            if not e_start:
                continue
            e_end = e_end or e_start + dt.timedelta(minutes=30)
            if start < e_end and e_start < start + window:
                found.append(_finding(
                    "collision", f"{item.id}:{inbox._slug(str(event.get('title')), 30)}",
                    w["collides"].format(item=item.summary, start=f"{start:%a %d.%m %H:%M}", event=event.get("title"),
                                         e_start=f"{e_start:%H:%M}", e_end=f"{e_end:%H:%M}"),
                    "now" if start.date() == today else "today", item.task))

    tasks = _tasks(root)
    for t in tasks:
        if not t["updated"]:
            continue
        if t["quiet_until"] and t["quiet_until"] >= today:    # "runs on": nobody asks before the day it names
            continue
        idle = (today - t["updated"]).days
        if t["blocked_by"]:
            if idle >= int(cfg["blocked_days"]):
                found.append(_finding("blocked", t["slug"],
                                      w["blocked"].format(slug=t["slug"], idle=idle, why=str(t["blocked_by"])[:80]),
                                      "later", t["slug"]))
        elif idle >= int(cfg["stale_days"]):
            customer = t["context"] in (cfg["customer_contexts"] or [])
            found.append(_finding("quiet", t["slug"],
                                  w["quiet"].format(slug=t["title"], idle=idle)
                                  + (w["quiet_customer"] if customer else w["quiet_park"]),
                                  "today" if customer else "later", t["slug"]))
    if max_active and len(tasks) > int(max_active):
        found.append(_finding("wip", "cap", w["wip"].format(n=len(tasks), cap=max_active),
                              "later"))

    own_keys = {f["key"] for f in found}
    for item in items:
        if str(item.key or "").startswith(KEY_PREFIX) or item.key in own_keys:
            continue
        created = _day(item.created)
        if item.kind in ("decision", "draft", "question") and created and \
                (today - created).days >= int(cfg["waiting_days"]):
            found.append(_finding("waiting", item.id, w["waiting"].format(day=f"{created:%d.%m}", item=item.summary),
                                  item.urgency, item.task, file=False))
        due = _day(item.due)
        if due and 0 <= (due - today).days <= 1:
            found.append(_finding("due", item.id, w["due"].format(day=f"{due:%d.%m}", item=item.summary), item.urgency,
                                  item.task, file=False))
    return found


ALL_CHECKS = ("collision", "quiet", "blocked", "wip")


def checks_run(calendar) -> tuple:
    """Which fileable checks a run actually performed: collision needs a calendar."""
    return ALL_CHECKS if calendar else tuple(c for c in ALL_CHECKS if c != "collision")


def file_findings(box, findings: list, checks_ran: tuple = ALL_CHECKS) -> list:
    """File every fileable finding (one item per key) and close advise items whose finding is gone.

    Only items of a check that RAN are closed: a run without a calendar did not
    look for collisions, so it cannot know that one is gone. A finding a person
    dropped stays dropped (scripts/inbox.py keeps a dropped key quiet).
    """
    wanted = {f["key"] for f in findings if f.get("file")}
    ran = {f"{KEY_PREFIX}{c}:" for c in checks_ran}
    filed = []
    for f in findings:
        if f.get("file"):
            filed.append(box.add(source="briefing/advise", kind="finding", summary=f["summary"],
                                 urgency=f["urgency"], task=f.get("task"), gate="your-yes", key=f["key"]))
    for item in box.open_items():
        key = str(item.key or "")
        if any(key.startswith(p) for p in ran) and key not in wanted:
            box.close(item.id, note="finding no longer holds")
    return filed


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="advise.py", description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--root", type=Path, default=REPO)
    ap.add_argument("--calendar-json", type=Path, help="JSON list of {title, start, end}")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--file", action="store_true", help="file findings as inbox items")
    ap.add_argument("--by", default="briefing")
    args = ap.parse_args(argv)
    calendar = json.loads(args.calendar_json.read_text(encoding="utf-8")) if args.calendar_json else None
    found = advise(args.root, calendar=calendar)
    if args.file:
        inbox = _load_inbox()
        file_findings(inbox.Inbox(args.root / "work" / "inbox", actor=args.by), found,
                      checks_ran=checks_run(calendar))
    if args.json:
        print(json.dumps(found, ensure_ascii=False, indent=1))
    else:
        for f in found:
            print(f"{f['urgency']:5} {f['check']:9} {f['summary']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
