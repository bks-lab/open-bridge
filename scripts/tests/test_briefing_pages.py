# SPDX-License-Identifier: MIT
"""Contract for the dashboard pages of a briefing (scripts/lib/briefing_view.py `pages`).

A dashboard shows the briefing's sections as tabs beside the briefing itself. Which
section sits on which tab, and which item field fills which column, differs per person:
one has health probes and GitHub, another a Jira board and no calendar. So the profile
says it (`view.pages`), and without that the pages follow from each section's kind, so
that no section the person collects is left without a place.

Every row carries the same four columns, whatever its kind: when, title, detail, link.
A column stays empty only when the item has nothing for it.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


bf = sys.modules.get("briefing") or _load("briefing", ROOT / "scripts" / "briefing.py")
bv = sys.modules.get("briefing_view") or _load("briefing_view", ROOT / "scripts" / "lib" / "briefing_view.py")

NOW = "2026-10-08T12:00"


def _sec(sid, kind, items, status="ok", **extra):
    return {"id": sid, "kind": kind, "title": sid.capitalize(), "status": status, "items": items,
            "total": len(items), **extra}


def _result():
    return {"collected_at": NOW, "sections": [
        _sec("inbox", "inbox", [{"id": "1", "title": "Answer the vendor"}]),
        _sec("probes", "command", [{"id": "p1", "title": "Backup stale", "state": "blocked", "raw_state": "stale"},
                                   {"id": "p2", "title": "Disk at 85 %", "state": "in_progress"}]),
        _sec("mine", "tracker", [
            {"id": "acme/app#7", "title": "Fix login", "type": "pr", "raw_state": "open", "project": "acme/app",
             "url": "https://example.test/acme/app/pull/7", "changed_at": "2026-10-08T09:30:00"},
            {"id": "acme/app#3", "title": "Old bug", "type": "issue", "raw_state": "open", "project": "Roadmap",
             "url": "https://example.test/acme/app/issues/3", "changed_at": "2026-10-05T10:00:00", "priority": "P1"}]),
        _sec("cal", "calendar", [
            {"id": "a", "title": "Standup", "start": "2026-10-08T09:00", "end": "2026-10-08T09:15"},
            {"id": "b", "title": "Review", "start": "2026-10-08T15:00", "end": "2026-10-08T16:00"},
            {"id": "c", "title": "Dentist", "start": "2026-10-09T08:00", "end": "2026-10-09T09:00", "info": True}]),
        _sec("commits", "commits", [
            {"id": "quiet", "title": "quiet", "counts": [3, 0], "spark": "▂▁", "branch": "main"},
            {"id": "busy", "title": "busy", "counts": [1, 5], "spark": "▁█", "branch": "dev"}]),
        _sec("log", "activity", [
            {"id": "x", "title": "Shipped it", "project": "app", "changed_at": "2026-10-08T11:00"},
            {"id": "y", "title": "Planned it", "project": "app", "changed_at": "2026-10-06T10:00"}]),
        _sec("workplace", "workplace", [{"id": "t", "title": "Tab one", "project": "Area", "state": "new"}]),
    ]}


def _profile(view=None):
    return {"id": "morning", "view": view or {}}


def _page(pages, pid):
    return next(p for p in pages if p["id"] == pid)


def _section(pages, sid):
    return next(s for p in pages for s in p["sections"] if s["id"] == sid)


# ---------------------------------------------------------------- default pages

def test_without_a_pages_block_every_section_finds_a_page_by_its_kind():
    pages = bv.pages(_result(), _profile())
    assert [p["id"] for p in pages] == ["work", "status", "dates", "trackers", "today", "more"]
    assert [s["id"] for s in _page(pages, "status")["sections"]] == ["probes"]
    assert [s["id"] for s in _page(pages, "today")["sections"]] == ["commits", "log"]
    # a kind the defaults do not know still shows, on the last page
    assert [s["id"] for s in _page(pages, "more")["sections"]] == ["workplace"]


def test_default_pages_sit_where_a_person_looks_for_them():
    # work in front, dates and trackers behind More, what happened today under the day list (no second "Today" tab)
    groups = {p["id"]: p["group"] for p in bv.pages(_result(), _profile())}
    assert groups == {"work": "main", "status": "main", "dates": "more", "trackers": "more", "today": "day", "more": "more"}
    titles = {p["id"]: p["title"] for p in bv.pages(_result(), _profile())}
    assert titles["work"] == "Work" and titles["today"] == "What happened today"


def test_the_work_page_carries_every_inbox_and_task_list_and_the_briefing_keeps_them_too():
    result = _result()
    result["sections"] += [_sec("inbox-runs", "inbox", [{"id": "2", "title": "Waits on the vendor"}], bucket="none"),
                           _sec("tasks", "tasks", [{"id": "t1", "title": "Ship it", "task": "ship"}]),
                           _sec("advise", "advise", [{"id": "a", "title": "A hint"}])]
    work = _page(bv.pages(result, _profile()), "work")
    assert [s["id"] for s in work["sections"]] == ["inbox", "inbox-runs", "tasks"]   # advice stays on the briefing


def test_a_page_without_a_section_is_left_out():
    result = _result()
    result["sections"] = [s for s in result["sections"] if s["kind"] != "calendar"]
    assert "dates" not in [p["id"] for p in bv.pages(result, _profile())]


def test_page_titles_come_from_the_labels():
    pages = bv.pages(_result(), _profile({"labels": {"page_dates": "Termine"}}))
    assert _page(pages, "dates")["title"] == "Termine"
    assert _page(pages, "status")["title"] == "Status"


# ---------------------------------------------------------------- the profile decides

def test_the_profile_places_sections_on_its_own_pages():
    view = {"pages": [
        {"id": "ops", "title": "Ops", "sections": ["probes", "mine"]},
        {"id": "week", "title": "Week", "sections": ["cal"]},
    ]}
    pages = bv.pages(_result(), _profile(view))
    assert [p["id"] for p in pages][:2] == ["ops", "week"]
    assert [s["id"] for s in _page(pages, "ops")["sections"]] == ["probes", "mine"]
    assert _page(pages, "ops")["title"] == "Ops"


def test_a_section_no_page_names_lands_on_the_rest_page():
    pages = bv.pages(_result(), _profile({"pages": [{"id": "ops", "sections": ["probes"]}]}))
    assert [s["id"] for s in _page(pages, "more")["sections"]] == ["mine", "cal", "commits", "log", "workplace"]


def test_page_skip_keeps_a_feeding_section_off_every_page():
    pages = bv.pages(_result(), _profile({"pages": [{"id": "ops", "sections": ["probes"]}], "page_skip": ["mine", "log"]}))
    assert [s["id"] for s in _page(pages, "more")["sections"]] == ["cal", "commits", "workplace"]
    assert bv._page_problems({"page_skip": "mine"}) == ["view.page_skip must be a list of section ids"]


def test_the_rest_page_can_be_switched_off():
    pages = bv.pages(_result(), _profile({"pages": [{"id": "ops", "sections": ["probes"]}], "page_rest": "hide"}))
    assert [p["id"] for p in pages] == ["ops"]


def test_a_page_may_also_show_a_briefing_kind_when_the_profile_asks():
    pages = bv.pages(_result(), _profile({"pages": [{"id": "ops", "sections": ["inbox"]}], "page_rest": "hide"}))
    assert [s["id"] for s in _page(pages, "ops")["sections"]] == ["inbox"]


# ---------------------------------------------------------------- columns

def test_tracker_rows_fill_every_column():
    rows = _section(bv.pages(_result(), _profile()), "mine")["items"]
    pr, old = rows
    assert pr == {"title": "acme/app#7 Fix login", "when": "09:30", "detail": "PR · open",
                  "tone": None, "url": "https://example.test/acme/app/pull/7", "task": None, "ask": True, "mark": None,
                  "actionable": True, "id": "acme/app#7"}
    # a project that the id already names is not repeated; another one is
    assert old["detail"] == "open · Roadmap · P1"
    assert old["when"] == "05.10"


def test_calendar_rows_say_until_when_and_mark_what_is_past_or_only_info():
    rows = _section(bv.pages(_result(), _profile()), "cal")["items"]
    assert [r["when"] for r in rows] == ["09:00", "15:00", "tomorrow 08:00"]
    assert rows[0]["detail"] == "until 09:15" and rows[0]["tone"] == "dim"
    assert rows[1]["tone"] is None
    assert rows[2]["detail"] == "until 09:00 · info"


def test_command_findings_are_warnings_and_blocked_ones_are_bad():
    rows = _section(bv.pages(_result(), _profile()), "probes")["items"]
    assert [r["tone"] for r in rows] == ["bad", "warn"]
    assert rows[0]["detail"] == "stale"
    assert rows[1]["detail"] == "in_progress"


def test_a_command_row_may_carry_a_meter_and_a_broken_one_is_dropped():
    result = {"collected_at": NOW, "sections": [_sec("quota", "command", [
        {"id": "a", "title": "Week: 74 %", "meter": {"value": 74, "max": 100, "unit": "%", "elapsed": 0.62}},
        {"id": "b", "title": "Cost", "meter": {"value": 12.5, "unit": "$"}},
        {"id": "c", "title": "Broken", "meter": {"value": "lots"}},
        {"id": "d", "title": "Out of range", "meter": {"value": 3, "max": 0, "elapsed": 7, "unit": "a very long unit"}},
        {"id": "e", "title": "Plain"}])]}
    profile = {"id": "p", "sections": [{"kind": "command", "id": "quota", "argv": ["true"]}]}
    rows = _section(bv.pages(result, profile), "quota")["items"]
    assert rows[0]["meter"] == {"value": 74.0, "max": 100.0, "unit": "%", "elapsed": 0.62, "warn": None, "bad": None,
                                "window_h": None}
    assert rows[1]["meter"] == {"value": 12.5, "max": None, "unit": "$", "elapsed": None, "warn": None, "bad": None,
                                "window_h": None}
    assert "meter" not in rows[2] and "meter" not in rows[4]
    assert rows[3]["meter"] == {"value": 3.0, "max": None, "unit": None, "elapsed": None, "warn": None, "bad": None,
                                "window_h": None}


def test_a_meter_may_name_the_length_of_its_time_window():
    # with it a dashboard reckons the share per day; nonsense becomes None
    result = {"collected_at": NOW, "sections": [_sec("quota", "command", [
        {"id": "a", "title": "Week", "meter": {"value": 19, "max": 100, "elapsed": 0.25, "window_h": 168}},
        {"id": "b", "title": "Zero", "meter": {"value": 1, "max": 100, "window_h": 0}},
        {"id": "c", "title": "Text", "meter": {"value": 1, "max": 100, "window_h": "week"}},
        {"id": "d", "title": "Years", "meter": {"value": 1, "max": 100, "window_h": 24 * 400}}])]}
    profile = {"id": "p", "sections": [{"kind": "command", "id": "quota", "argv": ["true"]}]}
    rows = _section(bv.pages(result, profile), "quota")["items"]
    assert [r["meter"]["window_h"] for r in rows] == [168.0, None, None, None]


def test_a_meter_may_name_where_warning_and_bad_begin():
    result = {"collected_at": NOW, "sections": [_sec("quota", "command", [
        {"id": "a", "title": "Week", "meter": {"value": 74, "max": 100, "unit": "%", "warn": 80, "bad": 95}},
        {"id": "b", "title": "Odd", "meter": {"value": 5, "max": 100, "warn": 90, "bad": 70}},
        {"id": "c", "title": "Over", "meter": {"value": 5, "max": 100, "warn": 150, "bad": "x"}}])]}
    profile = {"id": "p", "sections": [{"kind": "command", "id": "quota", "argv": ["true"]}]}
    rows = _section(bv.pages(result, profile), "quota")["items"]
    assert (rows[0]["meter"]["warn"], rows[0]["meter"]["bad"]) == (80.0, 95.0)
    assert (rows[1]["meter"]["warn"], rows[1]["meter"]["bad"]) == (None, None)     # bad before warn: neither
    assert (rows[2]["meter"]["warn"], rows[2]["meter"]["bad"]) == (None, None)     # beyond max, not a number


def test_a_section_may_ask_for_tiles_or_a_mosaic_and_rows_for_group_and_icon():
    result = {"collected_at": NOW, "sections": [_sec("res", "command", [
        {"id": "a", "title": "fn-a", "group": " Azure X ", "icon": "function", "tone": "none"},
        {"id": "b", "title": "plain"}])]}
    profile = {"id": "p", "sections": [{"kind": "command", "id": "res", "argv": ["true"]}],
               "view": {"pages": [{"id": "r", "title": "R", "sections": [{"id": "res", "view": "tiles"}]}]}}
    sec = _section(bv.pages(result, profile), "res")
    assert sec["view"] == "tiles"
    assert not bv._page_problems({"pages": [{"id": "r", "title": "R", "sections": [{"id": "res", "view": "groups"}]}]})
    assert (sec["items"][0]["group"], sec["items"][0]["icon"]) == ("Azure X", "function")
    assert "group" not in sec["items"][1]
    assert any("view must be one of" in x for x in
               bv._page_problems({"pages": [{"id": "r", "title": "R", "sections": [{"id": "res", "view": "cube"}]}]}))


def test_a_command_row_may_offer_its_own_steps():
    result = {"collected_at": NOW, "sections": [_sec("apps", "command", [
        {"id": "2026-10/a", "title": "A", "actions": [{"id": "nachgefasst", "label": "nachgefasst"},
                                                      {"id": "Bad Id", "label": "x"}, {"id": "abgesagt", "label": ""}]},
        {"id": "2026-10/b", "title": "B", "actions": "nope"}])]}
    profile = {"id": "p", "sections": [{"kind": "command", "id": "apps", "argv": ["true"]}]}
    rows = _section(bv.pages(result, profile), "apps")["items"]
    assert rows[0]["actions"] == [{"id": "nachgefasst", "label": "nachgefasst"}] and rows[0]["row_id"] == "2026-10/a"
    assert "actions" not in rows[1] and "row_id" not in rows[1]


def test_commits_lead_with_todays_count_busiest_first():
    rows = _section(bv.pages(_result(), _profile()), "commits")["items"]
    assert [r["title"] for r in rows] == ["busy", "quiet"]
    assert rows[0]["when"] == "5 today" and rows[0]["detail"] == "▁█ dev"
    assert rows[1]["tone"] == "dim"


def test_activity_from_earlier_days_is_dimmed():
    rows = _section(bv.pages(_result(), _profile()), "log")["items"]
    assert [r["when"] for r in rows] == ["11:00", "06.10"]
    assert [r["tone"] for r in rows] == [None, "dim"]
    assert rows[0]["detail"] == "app"
    assert rows[0]["group"] == "app"            # a log row belongs to its context, for `view: groups`


def test_a_page_entry_names_the_fields_for_its_columns():
    view = {"pages": [{"id": "ops", "sections": [
        {"id": "mine", "when": "changed_at", "detail": ["priority", "type"], "link": "none"}]}], "page_rest": "hide"}
    rows = _section(bv.pages(_result(), _profile(view)), "mine")["items"]
    assert rows[1]["detail"] == "P1 · issue"
    assert rows[1]["when"] == "05.10"
    assert rows[1]["url"] is None


def test_only_a_web_address_becomes_a_link():
    result = _result()
    result["sections"][-2]["items"][0]["url"] = "work/tasks/x/STATUS.md"
    rows = _section(bv.pages(result, _profile()), "log")["items"]
    assert rows[0]["url"] is None


def test_alarm_makes_every_finding_bad_and_says_so_on_the_section():
    view = {"pages": [{"id": "ops", "sections": [{"id": "probes", "alarm": True, "empty": "all green"}]}],
            "page_rest": "hide"}
    sec = _section(bv.pages(_result(), _profile(view)), "probes")
    assert sec["alarm"] is True and sec["empty"] == "all green"
    assert [r["tone"] for r in sec["items"]] == ["bad", "bad"]
    assert sec["bad"] == 2


# ---------------------------------------------------------------- what the tab bar counts

def test_each_section_says_what_it_adds_to_its_tab_badge():
    pages = bv.pages(_result(), _profile())
    assert _section(pages, "cal")["weight"] == 2          # the past standup does not count
    assert _section(pages, "commits")["weight"] == 5      # today's commits, not repositories
    assert _section(pages, "probes")["bad"] == 1


def test_badge_false_keeps_a_section_out_of_the_tab_number():
    view = {"pages": [{"id": "day", "sections": ["commits", {"id": "log", "badge": False}]}], "page_rest": "hide"}
    pages = bv.pages(_result(), _profile(view))
    assert _section(pages, "log")["weight"] == 0
    assert _section(pages, "commits")["weight"] == 5


def test_hide_empty_is_carried_only_when_set_and_must_be_a_bool():
    view = {"pages": [{"id": "day", "sections": ["commits", {"id": "log", "hide_empty": True}]}], "page_rest": "hide"}
    pages = bv.pages(_result(), _profile(view))
    assert _section(pages, "log")["hide_empty"] is True
    assert "hide_empty" not in _section(pages, "commits")
    assert any("hide_empty must be true or false" in x for x in
               bv._page_problems({"pages": [{"id": "d", "sections": [{"id": "log", "hide_empty": "yes"}]}]}))


def test_a_skipped_section_keeps_its_place_and_says_why():
    result = _result()
    result["sections"][2] = _sec("mine", "tracker", [], status="skipped", reason="quick mode")
    sec = _section(bv.pages(result, _profile()), "mine")
    assert sec["status"] == "skipped" and sec["items"] == []
    assert sec["empty"] == "nothing"


# ---------------------------------------------------------------- validation

def test_a_good_pages_block_passes():
    view = {"pages": [{"id": "ops", "title": "Ops", "sections": [
        "probes", {"id": "mine", "when": "changed_at", "detail": ["priority"], "link": "url", "empty": "-", "alarm": False}]}],
        "page_rest": "show"}
    assert bv.problems(view, None) == []


def test_a_broken_pages_block_is_named():
    bad = bv.problems({"pages": [{"title": "x"}, {"id": "briefing", "sections": []},
                                 {"id": "a", "sections": [{"id": "s", "colour": "red"}, {"id": "t", "alarm": "yes"}]},
                                 {"id": "a", "sections": ["u"]}],
                       "page_rest": "maybe"}, None)
    text = " | ".join(bad)
    assert "view.pages 1: needs an id" in text
    assert "view.pages 2: briefing is the briefing itself" in text
    assert "view.pages 2: sections must be a non-empty list" in text
    assert "view.pages 3, section s: unknown key colour" in text
    assert "view.pages 3, section t: alarm must be true or false" in text
    assert "view.pages 4: page a listed twice" in text
    assert "view.page_rest must be show or hide" in text


def test_validate_names_a_page_section_the_profile_does_not_have():
    profile = {"schema_version": 1, "scope": "user", "id": "morning",
               "sections": [{"kind": "inbox"}], "view": {"pages": [{"id": "ops", "sections": ["nope"]}]}}
    assert any("view.pages 1: no section 'nope' in this profile" in p for p in bf.profile_problems(profile, "morning"))


def test_an_empty_section_still_carries_every_field():
    profile = {"id": "p", "sections": [{"kind": "command", "id": "probe", "argv": ["true"]}]}
    result = {"collected_at": NOW, "sections": [_sec("probe", "command", [])]}
    assert bv.pages(result, profile) == [{"id": "status", "title": "Status", "sections": [
        {"id": "probe", "kind": "command", "title": "Probe", "status": "ok", "reason": "", "alarm": False, "empty": "nothing",
         "items": [], "total": 0, "weight": 0, "bad": 0, "as_of": None}], "group": "main"}]


def test_collect_json_carries_the_pages(tmp_path, capsys):
    root = tmp_path / "b"
    (root / "work" / "inbox").mkdir(parents=True)
    (root / "work" / "tasks").mkdir(parents=True)
    (root / "bridge-config.yaml").write_text("{}\n", encoding="utf-8")
    path = root / "workflow" / "briefings" / "morning.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump({
        "schema_version": 1, "scope": "user", "id": "morning", "default": True,
        "sections": [{"kind": "tasks"}, {"kind": "command", "id": "probe", "title": "Probe",
                                         "argv": [sys.executable, "-c", "print('[]')"]}],
        "view": {"style": "triage", "pages": [{"id": "ops", "title": "Ops", "sections": ["probe"]}]}}),
        encoding="utf-8")
    assert bf.main(["--root", str(root), "collect", "--json", "--no-save"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [(p["id"], [s["id"] for s in p["sections"]]) for p in data["pages"]] == [("ops", ["probe"])]


# ---------------------------------------------------------------- links and actions

def test_a_local_file_becomes_a_file_link_when_the_root_is_known(tmp_path):
    (tmp_path / "work" / "tasks" / "x").mkdir(parents=True)
    (tmp_path / "work" / "tasks" / "x" / "STATUS.md").write_text("x", encoding="utf-8")
    result = _result()
    result["sections"][-2]["items"][0]["url"] = "work/tasks/x/STATUS.md"
    rows = _section(bv.pages(result, _profile(), root=tmp_path), "log")["items"]
    assert rows[0]["url"] == (tmp_path / "work" / "tasks" / "x" / "STATUS.md").as_uri()
    # a path that does not exist stays without a link
    result["sections"][-2]["items"][0]["url"] = "work/tasks/gone/STATUS.md"
    assert _section(bv.pages(result, _profile(), root=tmp_path), "log")["items"][0]["url"] is None


def test_a_row_names_its_task_so_a_dashboard_can_open_or_jump_to_its_tab():
    result = _result()
    result["sections"][-2]["items"][0]["task"] = "alpha"
    pages = bv.pages(result, _profile())
    assert _section(pages, "log")["items"][0]["task"] == "alpha"
    assert _section(pages, "log")["items"][1]["task"] is None
    assert _section(pages, "workplace")["items"][0]["task"] == "t"     # a proposed tab is its task


def test_findings_tracker_and_inbox_rows_can_be_asked_about_the_rest_not():
    pages = bv.pages(_result(), _profile())
    assert all(r["ask"] for r in _section(pages, "probes")["items"])
    assert all(r["ask"] for r in _section(pages, "mine")["items"])
    inbox = bv.pages(_result(), _profile({"pages": [{"id": "in", "title": "In", "sections": [{"id": "inbox"}]}]}))
    assert all(r["ask"] for r in _section(inbox, "inbox")["items"])
    assert not any(r["ask"] for r in _section(pages, "cal")["items"] + _section(pages, "commits")["items"])


# ---------------------------------------------------------------- inbox, tasks, a source's own tone

def test_a_source_may_set_the_tone_of_its_rows():
    result = _result()
    result["sections"][1]["items"][0]["tone"] = "none"     # a probe that is information, not a finding
    result["sections"][1]["items"][1]["tone"] = "dim"
    rows = _section(bv.pages(result, _profile()), "probes")["items"]
    assert [r["tone"] for r in rows] == [None, "dim"]


def test_pages_show_every_row_not_only_the_briefings_first_few():
    result = _result()
    result["sections"][-2]["all"] = result["sections"][-2]["items"] + [
        {"id": "z", "title": "Older", "project": "app", "changed_at": "2026-10-01T10:00"}]
    assert len(_section(bv.pages(result, _profile()), "log")["items"]) == 3


def test_inbox_and_task_rows_fill_their_columns_when_a_page_names_them():
    result = _result()
    result["sections"].append(_sec("tasks", "tasks", [
        {"id": "alpha", "title": "Alpha", "state": "doing", "priority": "P1", "project": "acme",
         "blocked_by": "waits for the vendor", "changed_at": "2026-10-07", "url": "work/tasks/alpha/STATUS.md"}]))
    result["sections"][0]["items"][0].update(due="2026-10-08", gate="only-you", kind="decision", task="alpha",
                                             urgency="now")
    view = {"pages": [{"id": "work", "sections": ["inbox", "tasks"]}], "page_rest": "hide"}
    pages = bv.pages(result, _profile(view))
    inbox = _section(pages, "inbox")["items"][0]
    assert inbox["when"] == "today" and inbox["detail"] == "decision · only-you"
    assert inbox["task"] == "alpha" and inbox["ask"] is True and inbox["tone"] == "warn"
    task = _section(pages, "tasks")["items"][0]
    assert task["when"] == "07.10" and task["detail"] == "P1 · acme · waits for the vendor"
    assert task["task"] == "alpha" and task["tone"] == "warn"


def test_a_task_row_carries_its_detail_lines_priority_and_state_for_a_dashboard():
    result = _result()
    result["sections"].append(_sec("tasks", "tasks", [
        {"id": "alpha", "title": "Alpha", "state": "doing", "priority": "P1", "project": "acme",
         "blocked_by": "waits for the vendor", "blocked_since": "2026-10-06", "changed_at": "2026-10-07",
         "origin": "Asked in chat", "next": {"what": "send the draft", "who": "me", "due": "2026-10-10"},
         "steps": ["first box", "second box"], "log": ["2026-10-07 09:00 alpha drafted"]},
        {"id": "beta", "title": "Beta", "state": "doing", "changed_at": "2026-10-07"}]))
    view = {"pages": [{"id": "work", "sections": ["tasks"]}], "page_rest": "hide"}
    alpha, beta = _section(bv.pages(result, _profile(view)), "tasks")["items"]
    assert alpha["priority"] == "P1" and alpha["state"] == "doing"
    assert alpha["lines"] == [
        {"kind": "origin", "text": "Asked in chat"},
        {"kind": "next", "text": "send the draft · me · 2026-10-10"},
        {"kind": "blocked", "text": "waits for the vendor · 2026-10-06"},
        {"kind": "step", "text": "first box"},
        {"kind": "step", "text": "second box"},
        {"kind": "log", "text": "2026-10-07 09:00 alpha drafted"},
    ]
    assert beta["lines"] == []
    # other kinds carry no lines: the field belongs to task rows
    assert "lines" not in _section(bv.pages(result, _profile()), "log")["items"][0]


# ---------------------------------------------------------------- what a link may be

def test_a_file_link_never_leaves_the_bridge(tmp_path):
    root = tmp_path / "b"
    (root / "work").mkdir(parents=True)
    (tmp_path / "secret").write_text("x", encoding="utf-8")
    result = _result()
    for path in ("../secret", str(tmp_path / "secret")):
        result["sections"][-2]["items"][0]["url"] = path
        assert _section(bv.pages(result, _profile(), root=root), "log")["items"][0]["url"] is None, path


def test_a_web_link_loses_credentials_and_one_with_a_key_in_its_query_is_dropped():
    result = _result()
    items = result["sections"][2]["items"]
    items[0]["url"] = "https://x-access-token:ghp_SECRET@github.com/o/r/pull/7"
    items[1]["url"] = "https://fn.example.test/api/run?code=abc123&x=1"
    rows = _section(bv.pages(result, _profile()), "mine")["items"]
    assert rows[0]["url"] == "https://github.com/o/r/pull/7"
    assert rows[1]["url"] is None


def test_the_rest_page_id_is_reserved_and_a_section_stands_on_one_page_only():
    bad = " | ".join(bv.problems({"pages": [{"id": "more", "sections": ["a"]},
                                            {"id": "x", "sections": ["b"]}, {"id": "y", "sections": ["b"]}]}, None))
    assert "view.pages 1: more is the page for the rest, pick another id" in bad
    assert "view.pages 3: section b already stands on page x" in bad


# ---------------------------------------------------------------- speed

def test_sections_run_side_by_side_and_keep_their_order(tmp_path):
    import time as _time
    root = tmp_path / "b"
    (root / "work" / "inbox").mkdir(parents=True)
    slow = [sys.executable, "-c", "import time, json; time.sleep(1); print('[]')"]
    profile = {"id": "p", "sections": [{"kind": "command", "id": f"s{n}", "argv": slow} for n in range(4)]}
    started = _time.monotonic()
    result = bf.collect(root, profile, bf.Context(root, cfg={}))
    assert _time.monotonic() - started < 2.5          # four seconds one after the other
    assert [s["id"] for s in result["sections"]] == ["s0", "s1", "s2", "s3"]
    assert all(s["status"] == "ok" for s in result["sections"])


def test_only_runs_the_named_kinds_and_marks_the_rest_skipped(tmp_path, capsys):
    root = tmp_path / "b"
    (root / "work" / "inbox").mkdir(parents=True)
    (root / "work" / "tasks").mkdir(parents=True)
    (root / "bridge-config.yaml").write_text("{}\n", encoding="utf-8")
    path = root / "workflow" / "briefings" / "morning.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump({"schema_version": 1, "scope": "user", "id": "morning", "default": True,
                                    "sections": [{"kind": "tasks"}, {"kind": "command", "id": "probe",
                                                                     "argv": [sys.executable, "-c", "print('[]')"]}]}),
                    encoding="utf-8")
    assert bf.main(["--root", str(root), "collect", "--json", "--no-save", "--only", "command"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert {s["id"]: s["status"] for s in data["sections"]} == {"tasks": "skipped", "probe": "ok"}
    tasks = next(s for s in data["sections"] if s["id"] == "tasks")
    assert tasks["reason"] == "left out in this run (--only command)"


def test_a_failed_section_tells_its_reason_on_the_page():
    result = _result()
    result["sections"][2] = _sec("mine", "tracker", [], status="error", reason="gh: token invalid")
    assert _section(bv.pages(result, _profile()), "mine")["reason"] == "gh: token invalid"


def test_two_sections_loading_the_same_module_at_once_both_get_it_whole(tmp_path):
    root = tmp_path / "b"
    (root / "work" / "inbox").mkdir(parents=True)
    profile = {"id": "p", "sections": [{"kind": "inbox", "id": f"in{n}"} for n in range(6)]}
    for _ in range(5):
        saved = sys.modules.pop("inbox", None)
        try:
            result = bf.collect(root, profile, bf.Context(root, cfg={}))
        finally:
            if saved is not None:
                sys.modules["inbox"] = saved
        assert [s["status"] for s in result["sections"]] == ["ok"] * 6, [s.get("reason") for s in result["sections"]]



def test_an_advise_section_takes_the_inbox_from_the_briefings_loader(tmp_path, monkeypatch):
    """advise reads the inbox too. Its own loader takes no lock, so beside an inbox section
    it could publish a half-loaded copy over the one that section is loading: inside a
    briefing it must use the module the briefing's loader hands it."""
    root = tmp_path / "b"
    (root / "work" / "inbox").mkdir(parents=True)
    advise = bf._load_module("briefing_advise", ROOT / "skills" / "briefing" / "scripts" / "advise.py")

    def unlocked():
        raise AssertionError("advise loaded the inbox itself, outside the briefing's lock")

    monkeypatch.setattr(advise, "_load_inbox", unlocked)
    profile = {"id": "p", "sections": [{"kind": "inbox", "id": "in"}, {"kind": "advise", "id": "adv"}]}
    result = bf.collect(root, profile, bf.Context(root, cfg={}))
    assert [s["status"] for s in result["sections"]] == ["ok", "ok"], [s.get("reason") for s in result["sections"]]

# ---------------------------------------------------------------- cache

def _cached_profile(argv, minutes=5):
    return {"id": "p", "sections": [{"kind": "command", "id": "slow", "argv": argv, "cache_minutes": minutes}]}


def test_a_section_with_cache_minutes_answers_from_its_last_run_until_they_pass(tmp_path):
    import datetime as _dt
    root = tmp_path / "b"
    (root / "work" / "inbox").mkdir(parents=True)
    marker = tmp_path / "runs"
    argv = [sys.executable, "-c", f"open({str(marker)!r}, 'a').write('x'); print('[{{\"id\": \"1\", \"title\": \"t\"}}]')"]
    at = _dt.datetime(2026, 10, 8, 12, 0)
    first = bf.collect(root, _cached_profile(argv), bf.Context(root, cfg={}, now=at))
    again = bf.collect(root, _cached_profile(argv), bf.Context(root, cfg={}, now=at + _dt.timedelta(minutes=4)))
    assert marker.read_text() == "x"                          # the second run did not ask
    assert [i["title"] for i in again["sections"][0]["items"]] == ["t"]
    assert again["sections"][0]["cached_at"] == "2026-10-08T12:00:00"
    assert "cached_at" not in first["sections"][0]
    bf.collect(root, _cached_profile(argv), bf.Context(root, cfg={}, now=at + _dt.timedelta(minutes=6)))
    assert marker.read_text() == "xx"                         # five minutes passed: asked again


def test_fresh_or_a_changed_section_asks_the_source_again(tmp_path):
    import datetime as _dt
    root = tmp_path / "b"
    (root / "work" / "inbox").mkdir(parents=True)
    marker = tmp_path / "runs"
    argv = [sys.executable, "-c", f"open({str(marker)!r}, 'a').write('x'); print('[]')"]
    at = _dt.datetime(2026, 10, 8, 12, 0)
    bf.collect(root, _cached_profile(argv), bf.Context(root, cfg={}, now=at))
    ctx = bf.Context(root, cfg={}, now=at)
    ctx.fresh = True
    bf.collect(root, _cached_profile(argv), ctx)
    assert marker.read_text() == "xx"
    bf.collect(root, _cached_profile(argv, minutes=9), bf.Context(root, cfg={}, now=at))   # other config: void
    assert marker.read_text() == "xxx"


def test_a_failure_is_never_kept(tmp_path):
    import datetime as _dt
    root = tmp_path / "b"
    (root / "work" / "inbox").mkdir(parents=True)
    at = _dt.datetime(2026, 10, 8, 12, 0)
    failing = bf.collect(root, _cached_profile([sys.executable, "-c", "import sys; sys.exit(3)"]),
                         bf.Context(root, cfg={}, now=at))
    assert failing["sections"][0]["status"] == "error"
    assert not (root / ".bridge" / "briefing-cache").exists()


def test_cache_minutes_is_validated():
    profile = {"schema_version": 1, "scope": "user", "id": "morning",
               "sections": [{"kind": "inbox", "cache_minutes": 0}]}
    assert any("cache_minutes must be a positive whole number" in p for p in bf.profile_problems(profile, "morning"))


def test_a_cached_section_says_when_its_source_last_answered():
    result = _result()
    result["sections"][2]["cached_at"] = "2026-10-08T11:55:00"
    assert _section(bv.pages(result, _profile()), "mine")["as_of"] == "11:55"
    assert _section(bv.pages(_result(), _profile()), "mine")["as_of"] is None


# ---------------------------------------------------------------- marks

def _marked(marks):
    profile = _profile()
    profile["view"] = {**profile.get("view", {}), "marks": marks}
    return profile


def test_a_mark_labels_every_row_that_names_one_of_its_words():
    profile = _marked([{"label": "ACME", "match": ["acme/"], "color": "magenta"}, {"label": "Login", "match": "login"}])
    rows = _section(bv.pages(_result(), profile), "mine")["items"]
    assert rows[0]["mark"] == {"label": "ACME", "color": "magenta"}    # first mark wins over Login
    assert rows[1]["mark"] == {"label": "ACME", "color": "magenta"}    # matched through its url
    assert _section(bv.pages(_result(), profile), "probes")["items"][0]["mark"] is None


def test_a_mark_word_never_matches_the_source_name():
    """`tracker` names the source (a provider, or a command section's id): a word that
    happens to be a source name must not mark every row of that section."""
    result = _result()
    for item in result["sections"][1]["items"]:
        item["tracker"] = "probes"
    profile = _marked([{"label": "P", "match": "probes"}])
    assert [r["mark"] for r in _section(bv.pages(result, profile), "probes")["items"]] == [None, None]


def test_marks_reach_the_briefing_rows_too():
    profile = _marked([{"label": "VENDOR", "match": "vendor"}])
    rows = [r for b in bv.build(_result(), profile)["buckets"] for r in b["items"]]
    marked = [r for r in rows if r.get("mark")]
    assert [r["title"] for r in marked] == ["Answer the vendor"]
    assert marked[0]["mark"] == {"label": "VENDOR", "color": None}


def test_marks_are_validated():
    view = {"marks": [{"label": "", "match": []}, {"label": "X", "match": "x", "color": "pink", "extra": 1}, "nope"]}
    problems = bv.problems(view, None)
    assert "view.marks[0].label must be text of 1 to 16 characters" in problems
    assert "view.marks[0].match must be text or a list of text" in problems
    assert any(p.startswith("view.marks[1].color must be one of") for p in problems)
    assert "view.marks[1]: unknown key extra" in problems
    assert "view.marks[2] must be a mapping" in problems


def test_the_text_views_put_the_mark_in_front_of_the_title():
    profile = _marked([{"label": "VENDOR", "match": "vendor"}])
    for style in ("triage", "report"):
        text = bf.render_view(_result(), profile, style=style)
        assert "[VENDOR] " in text and "Answer the vendor" in text, style
    brevity = bf.render_view(_result(), _marked([{"label": "ACME", "match": "acme/"}]), style="brevity")
    assert "[ACME] Fix login" in brevity


def test_a_cached_answer_never_crosses_midnight(tmp_path):
    import datetime as _dt
    root = tmp_path / "b"
    (root / "work" / "inbox").mkdir(parents=True)
    marker = tmp_path / "runs"
    argv = [sys.executable, "-c", f"open({str(marker)!r}, 'a').write('x'); print('[]')"]
    bf.collect(root, _cached_profile(argv, minutes=60), bf.Context(root, cfg={}, now=_dt.datetime(2026, 10, 8, 23, 50)))
    bf.collect(root, _cached_profile(argv, minutes=60), bf.Context(root, cfg={}, now=_dt.datetime(2026, 10, 9, 0, 5)))
    assert marker.read_text() == "xx"


def test_briefing_and_more_are_taken_page_ids_for_validate_and_the_schema_alike():
    import pytest
    jsonschema = pytest.importorskip("jsonschema")
    schema = yaml.safe_load((ROOT / "workflow" / "briefings" / "_schema.yaml").read_text(encoding="utf-8"))
    for taken in ("briefing", "more"):
        profile = {"schema_version": 1, "scope": "user", "id": "p", "sections": [{"kind": "tasks"}],
                   "view": {"pages": [{"id": taken, "sections": ["tasks"]}]}}
        assert any(taken in p for p in bf.profile_problems(profile, "p")), taken
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(profile, schema)


def test_an_inbox_row_on_a_page_names_its_item():
    # a dashboard joins the row to what it knows about the item (its triage, its close) by this id
    rows = _section(bv.pages(_result(), _profile({"pages": [{"id": "in", "sections": ["inbox"]}]})), "inbox")["items"]
    assert rows[0]["inbox"] == "1"
    probes = _section(bv.pages(_result(), _profile({"pages": [{"id": "ops", "sections": ["probes"]}]})), "probes")
    assert "inbox" not in probes["items"][0]


def test_a_page_can_stand_behind_more_in_the_page_bar():
    # a dashboard with many tabs keeps the daily ones in front; `group: more` puts a page behind
    # a "More" menu, every other page stays in front (group main, the default)
    view = {"pages": [{"id": "ops", "sections": ["probes"], "group": "more"},
                      {"id": "week", "sections": ["cal"]}]}
    pages = bv.pages(_result(), _profile(view))
    assert _page(pages, "ops")["group"] == "more"
    assert _page(pages, "week")["group"] == "main"
    assert bv._page_problems(view) == []
    assert bv._page_problems({"pages": [{"id": "ops", "sections": ["probes"], "group": "side"}]}) == [
        "view.pages 1: group must be main, more, work or day"]


def test_a_page_of_group_work_folds_into_the_work_tab():
    # `group: work` gives a page no tab of its own: it is the "by source" view of the work tab,
    # beside "what is due" and "by Jev"
    view = {"pages": [{"id": "work", "sections": ["probes"], "group": "work"}]}
    assert _page(bv.pages(_result(), _profile(view)), "work")["group"] == "work"
    assert bv._page_problems(view) == []


def test_a_page_can_open_with_an_overview_of_its_sections():
    # `overview: true` asks a dashboard for a board of tiles on top, one per section, each a jump to it
    view = {"pages": [{"id": "ops", "sections": ["probes"], "overview": True}, {"id": "week", "sections": ["cal"]}]}
    pages = bv.pages(_result(), _profile(view))
    assert _page(pages, "ops")["overview"] is True
    assert "overview" not in _page(pages, "week")
    assert bv._page_problems(view) == []
    assert bv._page_problems({"pages": [{"id": "ops", "sections": ["probes"], "overview": "yes"}]}) == [
        "view.pages 1: overview must be true or false"]


def test_a_page_can_ask_for_an_order_by_jev():
    # `jev:` asks a dashboard for an order of the page's rows on a click; skip_sections and private keep rows home
    jev = {"skip_sections": ["probes"], "private": ["privat"]}
    view = {"pages": [{"id": "ops", "sections": ["probes"], "jev": jev}, {"id": "week", "sections": ["cal"]}]}
    pages = bv.pages(_result(), _profile(view))
    assert _page(pages, "ops")["jev"] == jev
    assert "jev" not in _page(pages, "week")
    assert bv._page_problems(view) == []
    assert bv._page_problems({"pages": [{"id": "ops", "sections": ["probes"], "jev": {}}]}) == []
    assert bv._page_problems({"pages": [{"id": "ops", "sections": ["probes"], "jev": True}]}) == [
        "view.pages 1: jev must be a mapping"]
    assert bv._page_problems({"pages": [{"id": "ops", "sections": ["probes"], "jev": {"private": "x", "y": 1}}]}) == [
        "view.pages 1: jev.private must be a list of words", "view.pages 1: jev: unknown key y"]


def test_a_calendar_row_carries_its_start_for_a_countdown():
    rows = _section(bv.pages(_result(), _profile()), "cal")["items"]
    assert rows[0]["at"].startswith("2026-10-08T09:00")
    other = _section(bv.pages(_result(), _profile()), "mine")["items"]
    assert "at" not in other[0]


def test_an_inbox_item_that_runs_on_says_on_what_and_when_to_look_again():
    r = {"collected_at": NOW, "sections": [_sec("runs", "inbox", [
        {"id": "20261014-1000-x-ab12", "title": "Answer from Ada", "state": "deferred", "until": "2026-10-19",
         "waiting_on": "an answer from Ada", "kind": "question", "gate": "your-yes"}])]}
    row = _section(bv.pages(r, _profile({"pages": [{"id": "work", "sections": ["runs"]}]})), "runs")["items"][0]
    assert row["detail"].startswith("an answer from Ada · look again ") and "19.10" in row["detail"]
    assert [ln["kind"] for ln in row["lines"]] == ["blocked", "look"]


def test_the_default_words_follow_the_bridges_language():
    # one table per language under the same keys; a German Bridge gets German pages without a profile
    assert set(bv.LABELS) == set(bv.LABELS_DE) and all(v.strip() for v in bv.LABELS_DE.values())
    german = {**_profile(), "_language": "de"}
    titles = {p["id"]: p["title"] for p in bv.pages(_result(), german)}
    assert titles["dates"] == "Termine" and titles["today"] == "Was heute geschah"
    assert {p["id"]: p["title"] for p in bv.pages(_result(), _profile())}["dates"] == "Dates"     # English otherwise
    assert bv.labels_for("fr") is bv.LABELS and bv.labels_for("de-AT") is bv.LABELS_DE


# ---------------------------------------------------------------- rows a person can act on

def test_findings_and_tracker_rows_are_actionable_by_default_and_carry_their_source_id():
    pages = bv.pages(_result(), _profile())
    probes = _section(pages, "probes")["items"]
    assert [(r["id"], r["actionable"]) for r in probes] == [("p1", True), ("p2", True)]
    assert all(r["actionable"] for r in _section(pages, "mine")["items"])


def test_rows_that_are_no_task_are_not_actionable_by_default():
    """A gauge, an appointment, a commit count and a log line need no one: no Do it, no Later"""
    pages = bv.pages(_result(), _profile())
    for sid in ("cal", "commits", "log"):
        assert not any(r["actionable"] for r in _section(pages, sid)["items"]), sid
    quiet = {"collected_at": NOW, "sections": [_sec("res", "command", [{"id": "a", "title": "fine", "tone": "none"}])]}
    assert _section(bv.pages(quiet, _profile()), "res")["items"][0]["actionable"] is False


def test_a_row_that_leads_to_an_inbox_item_or_a_task_keeps_its_own_path():
    result = {"collected_at": NOW, "sections": [_sec("work", "tasks", [{"id": "t1", "title": "A task", "state": "blocked"}])]}
    assert _section(bv.pages(result, _profile()), "work")["items"][0]["actionable"] is False


def test_a_page_entry_switches_actionable_on_or_off_for_its_whole_section():
    def view(sid, value):
        return {"pages": [{"id": "x", "title": "X", "sections": [{"id": sid, "actionable": value}]}]}
    pages = bv.pages(_result(), _profile(view("cal", True)))
    assert all(r["actionable"] for r in _section(pages, "cal")["items"])
    pages = bv.pages(_result(), _profile(view("probes", False)))
    assert not any(r["actionable"] for r in _section(pages, "probes")["items"])


def test_actionable_in_a_page_entry_is_validated():
    ok = {"pages": [{"id": "x", "title": "X", "sections": [{"id": "probes", "actionable": True}]}]}
    assert not bv._page_problems(ok)
    bad = {"pages": [{"id": "x", "title": "X", "sections": [{"id": "probes", "actionable": "yes"}]}]}
    assert any("actionable must be true or false" in p for p in bv._page_problems(bad))
