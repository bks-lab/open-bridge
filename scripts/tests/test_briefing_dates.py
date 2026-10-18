# SPDX-License-Identifier: MIT
"""The dates page as an agenda: each event's facts one field each, the events it collides with, the figures above
it, and the date of a deadline row, so a dashboard can draw a day, a week or a month without reading a detail
line. Recorded events only."""
from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


bv = sys.modules.get("briefing_view") or _load("briefing_view", ROOT / "scripts" / "lib" / "briefing_view.py")
NOW = dt.datetime(2026, 10, 19, 11, 0)     # a Monday


def ev(title, start, end=None, **more):
    return {"id": f"{start} {title}", "title": title, "start": start, "end": end or start, "state": "new", **more}


EVENTS = [
    ev("Standup", "2026-10-19T09:00", "2026-10-19T09:15", calendar="Work"),
    ev("Review", "2026-10-19T14:00", "2026-10-19T15:00", calendar="Work", location="Room 2"),
    ev("Pick up", "2026-10-19T14:30", "2026-10-19T15:00", calendar="Family", info=True),
    ev("Call", "2026-10-19T14:45", "2026-10-19T15:30", calendar="Work", url="https://meet.example/x",
       attendees=["Alex", "Sam"]),
    ev("Weekly", "2026-10-20T10:00", "2026-10-20T11:30", calendar="Work"),
    ev("Conference", "2026-10-22", "2026-10-23", calendar="Work"),
    ev("Later", "2026-10-28T09:00", "2026-10-28T10:00", calendar="Work"),
]


def section():
    return bv._page_section({"id": "calendar", "kind": "calendar", "items": EVENTS, "status": "ok"},
                            {"id": "calendar", "view": "agenda"}, NOW, bv.labels_for("en"))


def test_every_event_carries_its_facts_one_field_each():
    rows = {r["title"]: r for r in section()["items"]}
    standup = rows["Standup"]["cal"]
    assert standup == {"start": "2026-10-19T09:00", "end": "2026-10-19T09:15", "day": "2026-10-19", "minutes": 15,
                       "all_day": False, "calendar": "Work", "info": False, "where": None, "online": False,
                       "people": [], "past": True, "running": False, "overlaps": []}
    assert rows["Call"]["cal"]["online"] is True and rows["Call"]["cal"]["people"] == ["Alex", "Sam"]
    assert rows["Pick up"]["cal"]["info"] is True
    assert rows["Conference"]["cal"]["all_day"] is True and rows["Conference"]["cal"]["day"] == "2026-10-22"


def test_events_that_count_name_what_they_collide_with_information_never_does():
    rows = {r["title"]: r for r in section()["items"]}
    assert rows["Review"]["cal"]["overlaps"] == ["Call"] and rows["Call"]["cal"]["overlaps"] == ["Review"]
    assert rows["Pick up"]["cal"]["overlaps"] == []            # information is shown, never a collision
    assert rows["Conference"]["cal"]["overlaps"] == []         # a day that is full is no collision either


def test_the_figures_count_the_day_the_week_and_find_the_free_block():
    f = section()["cal_figures"]
    assert f["today"] == 3 and f["tomorrow"] == 1 and f["week"] == 5 and f["info_week"] == 1
    assert f["busy_today"] == 15 + 90                          # 09:00 to 09:15 and 14:00 to 15:30, merged
    assert f["overlaps"] == 2
    assert f["next"] == {"start": "2026-10-19T14:00", "title": "Review"}
    # the longest gap left today: 15:30 to the end of the working day, longer than now until the review
    assert f["free_today"] == {"minutes": 270, "from": "2026-10-19T15:30"}
    assert (f["day_start"], f["day_end"]) == (bv.CAL_DAY_START, bv.CAL_DAY_END)


def test_after_the_working_day_there_is_no_free_block_left():
    late = bv.calendar_figures([], dt.datetime(2026, 10, 19, 21, 0))
    assert late["free_today"] is None and late["next"] is None and late["today"] == 0


def test_a_running_event_says_so():
    rows = {r["title"]: r for r in bv._page_section(
        {"id": "calendar", "kind": "calendar", "items": EVENTS, "status": "ok"}, {"id": "calendar"},
        dt.datetime(2026, 10, 19, 14, 50), bv.labels_for("en"))["items"]}
    assert rows["Review"]["cal"]["running"] is True and rows["Weekly"]["cal"]["running"] is False


def test_a_deadline_row_carries_its_date_so_a_dates_page_can_count_it():
    sec = bv._page_section({"id": "deadlines", "kind": "command", "status": "ok",
                            "items": [{"id": "a", "title": "Slides", "changed_at": "2026-10-14"},
                                      {"id": "b", "title": "No date"}]},
                           {"id": "deadlines", "when": "changed_at"}, NOW, bv.labels_for("en"))
    assert sec["items"][0]["due_at"] == "2026-10-14" and "due_at" not in sec["items"][1]
    assert "cal_figures" not in sec


def test_agenda_is_a_view_a_page_may_ask_for():
    assert "agenda" in bv.PAGE_VIEWS
    assert section()["view"] == "agenda"
    ok = {"pages": [{"id": "dates", "title": "Dates", "sections": [{"id": "calendar", "view": "agenda"}]}]}
    assert not [p for p in bv._page_problems(ok) if "view" in p]
    bad = {"pages": [{"id": "dates", "title": "Dates", "sections": [{"id": "calendar", "view": "timeline"}]}]}
    assert any("view must be one of" in p and "agenda" in p for p in bv._page_problems(bad))
