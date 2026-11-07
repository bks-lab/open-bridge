# SPDX-License-Identifier: MIT
"""Contract for skills/briefing/scripts/advise.py: the checks that turn a list into advice.

Each check looks at the inbox, the task folders and (when given) today's calendar
and names something a person would want to know before choosing what to do:
a plan colliding with a meeting, a task going quiet, a block nobody nudged.
With --file every finding becomes an inbox item under a stable key, and a
finding that no longer holds closes its own item on the next run.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
REPO = HERE.parents[3]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    sys.dont_write_bytecode = True
    spec.loader.exec_module(module)
    return module


inbox = load("inbox", REPO / "scripts" / "inbox.py")
advise = load("advise", HERE.parents[1] / "scripts" / "advise.py")

NOW = dt.datetime(2026, 10, 4, 18, 0)


def task(root: Path, slug: str, **fm):
    d = root / "work" / "tasks" / slug
    d.mkdir(parents=True)
    fields = {"slug": slug, "status": "doing", "last_updated": "2026-10-03", **fm}
    lines = "\n".join(f"{k}: {json.dumps(v)}" for k, v in fields.items())
    (d / "STATUS.md").write_text(f"---\n{lines}\n---\n\n# {slug}\n", encoding="utf-8")


@pytest.fixture()
def repo(tmp_path):
    (tmp_path / "work" / "inbox").mkdir(parents=True)
    (tmp_path / "bridge-config.yaml").write_text(
        "work:\n  max_active: 3\nbriefing:\n  advise:\n    stale_days: 7\n    blocked_days: 14\n"
        "    customer_contexts: [bigcorp]\n", encoding="utf-8")
    return tmp_path


def box(repo):
    return inbox.Inbox(repo / "work" / "inbox", actor="briefing", clock=lambda: NOW)


def checks(findings):
    return sorted(f["check"] for f in findings)


def test_planned_item_colliding_with_a_meeting_is_named(repo):
    box(repo).add(source="session", kind="decision", summary="Post the launch", due="2026-10-06T15:00")
    calendar = [{"title": "Review with client", "start": "2026-10-06T15:30", "end": "2026-10-06T16:15"},
                {"title": "Lunch", "start": "2026-10-06T12:00", "end": "2026-10-06T13:00"}]
    found = advise.advise(repo, now=NOW, calendar=calendar)
    hits = [f for f in found if f["check"] == "collision"]
    assert len(hits) == 1 and "Review with client" in hits[0]["summary"]


def test_a_date_without_time_never_collides(repo):
    box(repo).add(source="session", kind="decision", summary="Some day", due="2026-10-06")
    calendar = [{"title": "All day thing", "start": "2026-10-06T09:00", "end": "2026-10-06T17:00"}]
    assert "collision" not in checks(advise.advise(repo, now=NOW, calendar=calendar))


def test_customer_task_going_quiet_is_today_internal_one_is_later(repo):
    task(repo, "bigcorp-rollout", context="bigcorp", last_updated="2026-09-20")
    task(repo, "tidy-scripts", context="internal", last_updated="2026-09-20")
    task(repo, "fresh", context="bigcorp")
    found = {f["task"]: f for f in advise.advise(repo, now=NOW) if f["check"] == "quiet"}
    assert set(found) == {"bigcorp-rollout", "tidy-scripts"}
    assert found["bigcorp-rollout"]["urgency"] == "today"
    assert found["tidy-scripts"]["urgency"] == "later"


def test_long_block_is_a_nudge_not_a_quiet_task(repo):
    task(repo, "vendor-wait", blocked_by="vendor answers", last_updated="2026-09-10")
    found = advise.advise(repo, now=NOW)
    assert checks(found) == ["blocked"]
    assert "vendor answers" in found[0]["summary"]


def test_wip_over_the_cap(repo):
    for i in range(4):
        task(repo, f"t{i}")
    assert "wip" in checks(advise.advise(repo, now=NOW))


def test_file_creates_items_once_and_closes_them_when_the_finding_is_gone(repo):
    task(repo, "bigcorp-rollout", context="bigcorp", last_updated="2026-09-20")
    b = box(repo)
    advise.file_findings(b, advise.advise(repo, now=NOW))
    advise.file_findings(b, advise.advise(repo, now=NOW))
    open_items = b.open_items()
    assert len(open_items) == 1 and open_items[0].key == "advise:quiet:bigcorp-rollout"
    # the task moved: the next run finds nothing and closes its own item
    status = repo / "work" / "tasks" / "bigcorp-rollout" / "STATUS.md"
    status.write_text(status.read_text().replace("2026-09-20", "2026-10-04"))
    advise.file_findings(b, advise.advise(repo, now=NOW))
    assert b.open_items() == []


def test_file_never_closes_items_it_did_not_create(repo):
    b = box(repo)
    other = b.add(source="person", kind="decision", summary="mine", key="advise-lookalike")
    advise.file_findings(b, [])
    assert b.get(other).state == "open"


def test_report_only_findings_are_not_filed(repo):
    b = box(repo)
    b.add(source="x", kind="decision", summary="old decision")
    found = advise.advise(repo, now=NOW + dt.timedelta(days=3))
    waiting = [f for f in found if f["check"] == "waiting"]
    assert waiting and waiting[0]["file"] is False
    advise.file_findings(b, found)
    assert len(b.items()) == 1


def test_a_run_without_calendar_leaves_collision_items_alone(repo):
    b = box(repo)
    b.add(source="session", kind="decision", summary="Post the launch", due="2026-10-06T15:00")
    calendar = [{"title": "Review", "start": "2026-10-06T15:30", "end": "2026-10-06T16:15"}]
    advise.file_findings(b, advise.advise(repo, now=NOW, calendar=calendar), checks_ran=advise.checks_run(calendar))
    collision = [i for i in b.open_items() if str(i.key).startswith("advise:collision")]
    assert len(collision) == 1
    advise.file_findings(b, advise.advise(repo, now=NOW), checks_ran=advise.checks_run(None))
    assert b.get(collision[0].id).state == "open"


def test_a_dropped_finding_is_not_filed_again(repo):
    task(repo, "tidy", context="internal", last_updated="2026-09-20")
    b = box(repo)
    advise.file_findings(b, advise.advise(repo, now=NOW))
    item = b.open_items()[0]
    b.event(item.id, "drop", text="leave it")
    advise.file_findings(b, advise.advise(repo, now=NOW))
    assert b.open_items() == []


def test_an_info_event_never_collides(repo):
    # An event from an info calendar (family) is someone else's: not a collision of yours.
    box(repo).add(source="session", kind="decision", summary="Post the launch", due="2026-10-06T15:00")
    calendar = [{"title": "School play", "start": "2026-10-06T15:30", "end": "2026-10-06T16:15", "info": True}]
    assert "collision" not in checks(advise.advise(repo, now=NOW, calendar=calendar))


def test_a_finding_speaks_the_configured_language(repo):
    cfg = repo / "bridge-config.yaml"
    cfg.write_text(cfg.read_text(encoding="utf-8") + "language:\n  conversation: de\n", encoding="utf-8")
    for i in range(4):
        task(repo, f"t{i}", last_updated="2026-10-05")
    wip = next(f for f in advise.advise(repo, now=NOW) if f["check"] == "wip")
    assert wip["summary"] == "4 Aufgaben aktiv, Grenze 3: eine schließen oder parken"


def test_a_task_that_runs_on_is_quiet_until_its_day(repo):
    # task.py wait: blocked_by + quiet_until; no "blocked" and no "quiet" advice before that day, both after it
    task(repo, "vendor-wait", blocked_by="vendor answers", last_updated="2026-09-10", quiet_until="2026-10-20")
    task(repo, "long-run", last_updated="2026-09-10", quiet_until="2026-10-20")
    assert advise.advise(repo, now=NOW) == []
    later = NOW.replace(month=10, day=21)
    assert checks(advise.advise(repo, now=later)) == ["blocked", "quiet"]


def test_a_quiet_task_is_named_by_its_title_not_its_slug(repo):
    # 07.11.2026: "ai-sccrm-onboarding-michael seit 10 Tagen unberührt" named a folder, not a piece of work.
    task(repo, "portal-relaunch-q4", last_updated="2026-09-20")
    status = repo / "work" / "tasks" / "portal-relaunch-q4" / "STATUS.md"
    status.write_text(status.read_text(encoding="utf-8").replace("# portal-relaunch-q4", "# Portal relaunch"),
                      encoding="utf-8")
    quiet = [f for f in advise.advise(repo, now=NOW) if f["check"] == "quiet"]
    assert quiet and quiet[0]["summary"].startswith("Portal relaunch untouched for")
    assert quiet[0]["key"] == "advise:quiet:portal-relaunch-q4"
