# SPDX-License-Identifier: MIT
"""The day book of the start page: a quota's use per day, yesterday's counts, the week's closed tasks."""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
if str(ROOT / "scripts" / "lib") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts" / "lib"))


from bridge_cockpit import daybook  # noqa: E402

DAY = 86_400_000


def at(day: str, hour: int = 12) -> float:
    return dt.datetime.fromisoformat(f"{day}T{hour:02d}:00").timestamp() * 1000


class Clock:
    def __init__(self, ms: float):
        self.ms = ms

    def __call__(self) -> float:
        return self.ms


def model(week: float, waiting: int = 3, work: int = 9) -> dict:
    meter = {"value": week, "max": 100, "unit": "%", "elapsed": 0.3, "window_h": 168}
    return {"counts": {"now": waiting, "waiting_tabs": 1}, "pages": [
        {"id": "work", "badge": {"kind": "count", "n": work}, "sections": []},
        {"id": "ops", "badge": None, "sections": [{"id": "quota", "items": [
            {"title": "Woche, alle Modelle: 19 %", "meter": meter},
            {"title": "Cost", "meter": {"value": 3, "unit": "$"}}]}]}]}


def test_the_id_of_a_quota_is_the_one_the_page_makes():
    # logic.js tileSlug and homeCatalog make the same id
    assert daybook.slug("Week, all Modelle: Ä") == "week-all-modelle-a"
    assert daybook.quota_id("quota", "Woche, alle Modelle: 19 %") == "q:quota:woche-alle-modelle"


def test_a_quota_counts_what_it_used_each_day_across_a_reset(tmp_path):
    clock = Clock(at("2026-10-12", 9))
    book = daybook.DayBook(tmp_path, clock)
    book.record(model(10))                 # the first reading: nothing known before it
    book.record(model(14))
    clock.ms = at("2026-10-13", 8)
    book.record(model(15))                 # overnight use counts to the day it is seen on
    book.record(model(19))
    clock.ms = at("2026-10-13", 20)
    book.record(model(2))                  # the window reset: from zero again
    view = daybook.DayBook(tmp_path, clock).view()       # it survives a restart
    q = view["quota"]["q:quota:woche-alle-modelle"]
    assert q["today"] == 7
    assert q["days"][-2:] == [{"date": "2026-10-12", "used": 4}, {"date": "2026-10-13", "used": 7}]
    assert "q:quota:cost" not in view["quota"]


def test_a_count_remembers_the_day_before(tmp_path):
    clock = Clock(at("2026-10-11"))
    book = daybook.DayBook(tmp_path, clock)
    book.record(model(1, waiting=5, work=12))
    clock.ms = at("2026-10-12")
    book.record(model(1, waiting=4, work=10))
    clock.ms = at("2026-10-13")
    book.record(model(1, waiting=6, work=9))
    view = book.view()["counts"]
    assert view["c:waiting"] == {"before": 4, "date": "2026-10-12"}
    assert view["p:work"] == {"before": 10, "date": "2026-10-12"}
    assert "p:ops" not in view


def test_the_book_keeps_two_weeks(tmp_path):
    clock = Clock(at("2026-09-01"))
    book = daybook.DayBook(tmp_path, clock)
    for i in range(30):
        clock.ms = at("2026-09-01") + i * DAY
        book.record(model(i))
    days = json.loads((tmp_path / "days.json").read_text())["counts"]["c:waiting"]
    assert len(days) == 15


def test_the_week_counts_the_tasks_closed_since_monday(tmp_path):
    def done(month, slug, closed, title="T"):
        d = tmp_path / "work" / "done" / month / slug
        d.mkdir(parents=True)
        (d / "STATUS.md").write_text(f"---\nslug: {slug}\nstatus: done\nclosed: \"{closed}\"\n---\n\n# {title}\n", encoding="utf-8")
    done("2026-10", "a", "2026-10-12", "Alpha")      # Monday
    done("2026-10", "b", "2026-10-13", "Beta")
    done("2026-10", "c", "2026-10-11")               # Sunday before: last week
    done("2026-09", "d", "2026-09-30")
    week = daybook.week_done(tmp_path, dt.date(2026, 10, 14))
    assert week["count"] == 2
    assert [x["title"] for x in week["items"]] == ["Beta", "Alpha"]      # newest first
    assert week["since"] == "2026-10-12"
    assert daybook.week_done(tmp_path / "nowhere", dt.date(2026, 10, 14))["count"] == 0


def test_the_week_names_an_ended_stream_also_behind_the_comment_line_task_py_writes(tmp_path):
    for slug, head in (("plain-stream", ""), ("commented-stream", "# yaml-language-server: $schema=x\n"),
                       ("commented-task", "# yaml-language-server: $schema=x\n")):
        d = tmp_path / "work" / "done" / "2026-10" / slug
        d.mkdir(parents=True)
        stream = "" if slug.endswith("task") else "was_stream: true\n"
        (d / "STATUS.md").write_text(f"{head}---\nslug: {slug}\nstatus: done\n{stream}closed: \"2026-10-13\"\n---\n\n# {slug}\n",
                                     encoding="utf-8")
    kinds = {x["slug"]: x["work_kind"] for x in daybook.week_done(tmp_path, dt.date(2026, 10, 14))["items"]}
    assert kinds == {"plain-stream": "done_stream", "commented-stream": "done_stream", "commented-task": "done_task"}
