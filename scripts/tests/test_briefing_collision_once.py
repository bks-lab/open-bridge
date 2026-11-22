# SPDX-License-Identifier: MIT
"""A point stands once, also where its due time collides with several calendar events.

After #704 an inbox item due Wednesday 17:30 stood three times in Do, on the cockpit's Dran and Work through, each
row numbered 3 and saying "collides with the calendar": the advice made one finding per overlapping event, and the
briefing made one row per finding, each named by the item's task. Now the advice makes one finding per item that
names every event it collides with, and the briefing shows that item as one row (its own, where it has one), with the
collisions as its reasons and one number.

Run: python3 -m pytest -q scripts/tests/test_briefing_collision_once.py
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "scripts"))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


bv = sys.modules.get("briefing_view") or _load("briefing_view", ROOT / "scripts" / "lib" / "briefing_view.py")
inbox = sys.modules.get("inbox") or _load("inbox", ROOT / "scripts" / "inbox.py")
advise = _load("briefing_advise_once", ROOT / "skills" / "briefing" / "scripts" / "advise.py")

NOW = dt.datetime(2026, 11, 22, 7, 45)
ITEM = "20261119-0822-demo-fuer-mi-25-11-17-30-vorbereit-62ab"
TITLE = "Demo Wed 25.11. 17:30: read the product vision, then walk through the time tracking use case"
EVENTS = [{"title": "Interview prep", "start": "2026-11-25T17:00", "end": "2026-11-25T18:00"},
          {"title": "Guitar lesson", "start": "2026-11-25T17:30", "end": "2026-11-25T18:00"},
          {"title": "Tutoring", "start": "2026-11-25T18:00", "end": "2026-11-25T19:00"}]


# ---------------------------------------------------------------- the advice: one finding per item


@pytest.fixture()
def repo(tmp_path):
    (tmp_path / "work" / "inbox").mkdir(parents=True)
    (tmp_path / "bridge-config.yaml").write_text("briefing:\n  advise:\n    collision_minutes: 60\n", encoding="utf-8")
    return tmp_path


def test_an_item_colliding_with_three_events_is_one_finding_that_names_all_three(repo):
    box = inbox.Inbox(repo / "work" / "inbox", actor="briefing", clock=lambda: NOW)
    item_id = box.add(source="weekly", kind="idea", summary=TITLE, due="2026-11-25T17:30", task="k2a-gui-einstieg")
    found = [f for f in advise.advise(repo, now=NOW, calendar=EVENTS) if f["check"] == "collision"]
    assert len(found) == 1, found
    f = found[0]
    assert f["key"] == f"advise:collision:{item_id}"
    assert f["inbox"] == item_id and f["item"] == TITLE
    assert [e["title"] for e in f["events"]] == ["Interview prep", "Guitar lesson", "Tutoring"]
    for name in ("Interview prep", "Guitar lesson", "Tutoring"):
        assert name in f["summary"]


def test_the_briefing_section_passes_the_item_and_its_events_on():
    bf = sys.modules.get("briefing") or _load("briefing", ROOT / "scripts" / "briefing.py")
    finding = {"check": "collision", "key": f"advise:collision:{ITEM}", "summary": "s", "urgency": "today",
               "task": "k2a-gui-einstieg", "file": True, "inbox": ITEM, "item": TITLE,
               "events": [{"title": "Tutoring", "start": "18:00", "end": "19:00"}]}
    got = bf.advise_rows([finding])
    assert got[0]["inbox"] == ITEM and got[0]["item"] == TITLE and got[0]["events"] == finding["events"]


# ---------------------------------------------------------------- the briefing: one row, its collisions as reasons


def sec(sid, kind, items):
    return {"id": sid, "kind": kind, "title": sid, "status": "ok", "items": items, "all": items, "total": len(items)}


def result(*sections):
    return {"profile": "morning", "title": "Morning", "collected_at": NOW.isoformat(timespec="minutes"),
            "sections": list(sections)}


def profile(*sections, style="triage"):
    return {"schema_version": 1, "scope": "user", "id": "morning", "for": "alice", "sections": list(sections),
            "view": {"style": style}}


def idea(**kw):
    return {"id": ITEM, "title": TITLE, "state": "open", "urgency": "later", "kind": "idea", "gate": "your-yes",
            "task": "k2a-gui-einstieg", "due": "2026-11-25T17:30", "changed_at": "2026-11-19T08:22", **kw}


def finding(events=EVENTS):
    return {"id": f"advise:collision:{ITEM}", "title": f"“{TITLE}” collides", "state": "new", "urgency": "today",
            "check": "collision", "task": "k2a-gui-einstieg", "file": True, "inbox": ITEM, "item": TITLE,
            "events": [{"title": e["title"], "start": e["start"][11:], "end": e["end"][11:]} for e in events]}


def old_findings():
    """What the advice made before: one finding per event, keyed by the event"""
    return [{"id": f"advise:collision:{ITEM}:{e['title'].lower().replace(' ', '-')}",
             "title": f"“{TITLE}” collides with “{e['title']}”", "state": "new", "urgency": "today",
             "check": "collision", "task": "k2a-gui-einstieg", "file": True} for e in EVENTS]


def rows_of(view):
    return [r for b in view["buckets"] for r in b["items"]]


def test_an_item_on_the_watch_list_with_three_collisions_stands_once_in_do_with_its_reasons():
    # the live case: the item's own section is out of the buckets (bucket: none), so the advice brings it in
    r = result(sec("ideas", "inbox", [idea()]), sec("advise", "advise", [finding()]))
    v = bv.build(r, profile({"kind": "inbox", "id": "ideas", "bucket": "none"}, {"kind": "advise", "id": "advise"}))
    rows = [x for x in rows_of(v) if TITLE in x["title"]]
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["bucket"] == "do"
    # the point is the inbox item: its answers act on the item, never on its task
    assert row["inbox_id"] == ITEM and row["title"] == TITLE
    said = " ".join(row["why"])
    for name in ("Interview prep", "Guitar lesson", "Tutoring"):
        assert name in said
    assert isinstance(row["nr"], int)


def test_findings_of_an_older_advice_one_per_event_still_make_one_row():
    r = result(sec("ideas", "inbox", [idea()]), sec("advise", "advise", old_findings()))
    v = bv.build(r, profile({"kind": "inbox", "id": "ideas", "bucket": "none"}, {"kind": "advise", "id": "advise"}))
    rows = [x for x in rows_of(v) if TITLE in x["title"]]
    assert len(rows) == 1, rows
    assert rows[0]["inbox_id"] == ITEM


def test_an_item_with_its_own_row_takes_the_collisions_as_reasons_on_that_row():
    for order in (("inbox", "advise"), ("advise", "inbox")):
        secs = {"inbox": sec("inbox", "inbox", [idea(urgency="later", kind="decision")]),
                "advise": sec("advise", "advise", [finding()])}
        r = result(*(secs[k] for k in order))
        v = bv.build(r, profile(*({"kind": k, "id": k} for k in order)))
        rows = [x for x in rows_of(v) if TITLE in x["title"] or x.get("inbox_id") == ITEM]
        assert len(rows) == 1, (order, rows)
        assert rows[0]["bucket"] == "do" and rows[0]["title"] == TITLE
        assert "Tutoring" in " ".join(rows[0]["why"])


def test_the_printed_briefing_numbers_the_point_once():
    r = result(sec("ideas", "inbox", [idea()]), sec("advise", "advise", [finding()]))
    p = profile({"kind": "inbox", "id": "ideas", "bucket": "none"}, {"kind": "advise", "id": "advise"})
    text = bv.draw(bv.build(r, p))
    assert text.count(TITLE[:30]) == 1, text
