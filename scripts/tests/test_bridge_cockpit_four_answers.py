# SPDX-License-Identifier: MIT
"""What the server gives the cockpit's four answers (Work through by the briefing's buckets, lib/answers.py).

Every point takes the same four answers, Do it, Later, Done, Obsolete. The server's part:

- Later to the watch list puts a point off to the watch list's day (answers.LIST_DAY): an inbox item is deferred to
  it, any other row hidden until it; no other day past a year is taken.
- "With …" under More hands a task's next step to you or to the Bridge (verb task_owner, task.py next --who), with
  an undo that gives the step back to whoever had it.
- The model carries the profile's four buckets (a listed `drop` is left out, no answers of their own), the counts
  of what is out of sight (later, watch list, done today) and a resting task's days.

Run: python3 -m pytest -q scripts/tests/test_bridge_cockpit_four_answers.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_bridge_cockpit import YES_ID, K, I, world, writes, private_key_dir  # noqa: E402,F401
from lib.bridge_cockpit import model as m  # noqa: E402
from lib.bridge_cockpit.actions import ActionError  # noqa: E402

LIST_DAY = "9999-12-31"


# ---------------------------------------------------------------- Later to the watch list

def test_later_to_the_watch_list_defers_an_inbox_item_to_the_list_day(world):
    world.runner.calls.clear()
    res = world.act("later", key=f"inbox:{YES_ID}", until=LIST_DAY)
    assert writes(world) == [I(world, "defer", YES_ID, "--until", LIST_DAY)]
    assert res["settled"] == [f"inbox:{YES_ID}"]
    # the toast says the watch list, never the far day
    assert "watch list" in res["note"].lower() and "9999" not in res["note"]


def test_later_to_the_watch_list_hides_any_other_row_until_the_list_day(world):
    world.runner.calls.clear()
    res = world.act("later", key="task:other-task", until=LIST_DAY)
    assert world.app.store.hidden() == {"task:other-task": LIST_DAY}
    assert "9999" not in res["note"]
    assert all("9999" not in " ".join(c) for c in writes(world)), "the note where the row lives names the list"


def test_no_other_day_past_a_year_is_taken(world):
    for bad in ("2099-01-01", "9999-12-30"):
        with pytest.raises(ActionError):
            world.act("later", key=f"inbox:{YES_ID}", until=bad)


# ---------------------------------------------------------------- With … (who has the next step)

def _with_step(world, slug="demo-task", what="Ship it"):
    path = world.root / "work" / "tasks" / slug / "STATUS.md"
    path.write_text(path.read_text(encoding="utf-8").replace("origin: invented\n", f"origin: invented\nnext: {{what: {what}}}\n"),
                    encoding="utf-8")


def test_task_owner_hands_the_step_to_the_bridge_and_its_undo_gives_it_back(world):
    _with_step(world)
    world.runner.calls.clear()
    res = world.act("task_owner", key="task:demo-task", who="bridge")
    assert writes(world)[0] == K(world, "next", "demo-task", "--who", "bridge", "--json")
    assert res["ok"]
    undo = [it["undo"] for e in world.app.history.state() for it in e["items"] if it["kind"] == "task"][0]
    assert undo["verb"] == "task_next" and undo["args"]["slug"] == "demo-task" and undo["args"]["who"]
    world.runner.calls.clear()
    world.act(undo["verb"], **undo["args"])
    assert writes(world)[0][:5] == K(world, "next", "demo-task", "--who")[:5]


def test_task_owner_on_a_task_without_a_step_names_the_task_as_its_step(world):
    # round 1 of the four answers: 36 of 40 tasks had no next step, and task.py next refused "has no next step to
    # give someone", in English, for every one. The task itself is the step then; the undo takes that step back
    world.runner.calls.clear()
    res = world.act("task_owner", key="task:demo-task", who="bridge")
    assert writes(world)[0] == K(world, "next", "demo-task", world.row("task:demo-task")["title"], "--who", "bridge", "--json")
    assert res["ok"]
    undo = [it["undo"] for e in world.app.history.state() for it in e["items"] if it["kind"] == "task"][0]
    assert undo == {"verb": "task_next", "args": {"slug": "demo-task", "clear": True}}
    world.runner.calls.clear()
    world.act(undo["verb"], **undo["args"])
    assert writes(world)[0] == K(world, "next", "demo-task", "--clear", "--json")


def test_handing_a_task_without_a_step_to_a_person_names_the_task_as_its_step(world):
    world.runner.calls.clear()
    world.act("work_on", key="task:demo-task", who="Noa", until="2026-12-01")
    assert writes(world)[0] == K(world, "next", "demo-task", world.row("task:demo-task")["title"], "--who", "Noa", "--check", "2026-12-01", "--json")


def test_task_owner_takes_a_task_and_one_line_only(world):
    with pytest.raises(ActionError):
        world.act("task_owner", key=f"inbox:{YES_ID}", who="me")
    for bad in ("", "a\nb", "x" * 61):
        with pytest.raises(ActionError):
            world.act("task_owner", key="task:demo-task", who=bad)


# ---------------------------------------------------------------- the model

def test_the_buckets_are_the_four_without_answers_of_their_own():
    defs = [{"id": "do", "title": "Tun", "options": ["ja"]}, {"id": "drop", "title": "Parken oder streichen"},
            {"id": "waiting", "title": "Wartet auf andere"}, {"id": "do", "title": "again"}]
    assert m.bucket_defs_of(defs) == [{"id": "do", "title": "Tun"}, {"id": "waiting", "title": "Wartet auf andere"}]


def test_the_view_carries_what_is_out_of_sight_and_how_long_a_task_rests():
    raw = {"profile": "cockpit", "title": "Cockpit",
           "view": {"buckets": [{"id": "plan", "title": "Planen", "items": [
               {"title": "Quiet one", "task": "quiet-one", "resting": 54, "nr": 2},
               {"title": "Quiet, no days", "task": "quiet-two", "resting": True},
               {"title": "Busy", "task": "busy"}]}],
               "aside": {"later": 2, "list": 5, "done_today": 1}}}
    view = m.parse_view(raw, True, 0)
    assert view["aside"] == {"later": 2, "list": 5, "done_today": 1}
    assert [r["resting"] for r in view["buckets"][0]["rows"]] == [54, True, None]
    # an older briefing counts nothing: none, never zeros it did not count
    assert m.parse_view({"view": {"buckets": []}}, True, 0)["aside"] is None
    assert m.parse_view({"view": {"aside": {"later": "x", "list": -1}}}, True, 0)["aside"] == {"later": 0, "list": 0, "done_today": 0}


def test_an_inbox_item_a_page_lists_names_its_task_but_is_no_task_of_its_own():
    # round 1 of the four answers: a task parked onto the watch list left a second point in Do, titled as its open
    # inbox item ("Estimate for Avery is ready to send"), with all four answers and no number: the inbox page's item
    # named the task, and the collector made a task row of it, with the item's title and no status
    view = {"pages": [{"id": "work", "sections": [
        {"id": "inbox", "kind": "inbox", "view": "table", "items": [{"title": "Estimate for Avery is ready", "task": "est"}]},
        {"id": "tasks", "kind": "tasks", "view": "table", "items": [{"title": "Plan the move", "task": "move"}]},
        {"id": "board", "kind": "tasks", "view": "taskboard", "items": [{"title": "Board card", "task": "board"}]}]}]}
    assert m.page_tasks(view) == [("move", "Plan the move")]


def test_a_task_put_off_to_a_day_is_no_point_until_then():
    # a task the briefing puts out of sight until a day it names in `away`, and the cockpit's tasks beside the
    # briefing leave it out the same way
    raw = {"view": {"buckets": [], "away": [{"key": "task:quiet", "until": "2026-11-28"}, {"key": "bad"}, "x"]}}
    v = m.parse_view(raw, True, 0)
    assert v["away"] == [{"key": "task:quiet", "until": "2026-11-28"}]
    tasks = [{"slug": s, "label": s, "title": s, "area": "A", "area_names": ["A"], "priority": None, "blocked_by": "Robin" if s == "quiet" else None,
              "stale": False, "age": 0, "type": None, "status": "doing", "next": None, "updated": None, "origin": None}
             for s in ("quiet", "open")]
    got = m.with_tasks(v, tasks)
    assert [r["task"] for b in got["buckets"] for r in b["rows"]] == ["open"]
    # a quick pass that left the tasks out keeps what the full pass put away
    quick = m.parse_view({"view": {"buckets": [], "away": []}, "sections": []}, False, 0)
    assert m.merge_view(v, {**quick, "skipped": ["tasks"]})["away"] == v["away"]


def test_later_on_a_task_writes_nothing_where_the_task_lives_so_its_undo_leaves_no_trace(world):
    # round 1 of the four answers: after Later > tomorrow and Undo, STATUS.md kept "## Notes - Später bis ..." and a
    # new last_updated. A plain Later is only the cockpit's record; with a sentence the sentence is a note
    world.runner.calls.clear()
    world.act("later", key="task:demo-task", until="2026-12-01")
    assert writes(world) == [] and world.app.store.hidden() == {"task:demo-task": "2026-12-01"}


def test_a_stream_done_for_this_time_is_out_of_sight_until_tomorrow_and_done_today(world):
    world.runner.calls.clear()
    res = world.act("later", key="task:demo-task", until="2026-12-01", done=True)
    assert writes(world) == []
    assert world.app.store.hidden() == {"task:demo-task": "2026-12-01"}
    assert set(world.app.store.settled.hidden_done("2026-11-30")) == {"task:demo-task"}
    assert "until" not in res["note"].lower() and "2026" not in res["note"]


def test_how_long_a_task_rests_reaches_its_card(tmp_path):
    # round 1 of the four answers: the briefing said "resting for 55 days" (resting: 55), the page's row said None,
    # so no card showed the quiet mark "ruht seit N Tagen"
    from test_bridge_cockpit import World, collect_fixture, ok
    w = World(tmp_path, prepare=False)
    try:
        def resting(argv):
            data = collect_fixture(w.root)
            data["view"]["buckets"][2]["items"][0]["resting"] = 55
            return ok(data)
        w.runner.handlers["briefing.collect"] = resting
        w.app.tabs.poll()
        w.app.collector.request("both")
        w.app.collector.drain()
        row = w.row("task:demo-task")
        assert row["resting"] == 55
    finally:
        w.close()


def test_a_quiet_task_beside_the_briefing_says_its_days_too():
    tasks = [{"slug": "q", "label": "q", "title": "Q", "area": "A", "area_names": ["A"], "priority": None, "blocked_by": None,
              "stale": True, "age": 53, "type": None, "status": "doing", "next": None, "updated": None, "origin": None}]
    got = m.with_tasks(m.parse_view({"view": {"buckets": []}}, True, 0), tasks)
    assert [r["resting"] for b in got["buckets"] for r in b["rows"]] == [53]


def test_obsolete_says_obsolete_in_its_toast_while_the_buckets_are_on(tmp_path):
    # round 1 of the four answers: the button and its confirm said Veraltet, the toast "Verworfen" (the old Drop)
    from test_bridge_cockpit import World
    w = World(tmp_path, config="cockpit:\n  enabled: true\n  language: en\n  flow:\n    enabled: true\n")
    try:
        res = w.act("settle", keys=[f"inbox:{YES_ID}"], outcome="not_doing", reason="outdated", text="veraltet")
        assert res["note"].startswith("Obsolete") and "Dropped" not in res["note"]
        res = w.act("settle", keys=["task:demo-task"], outcome="not_doing", text="veraltet")
        assert "Obsolete" in res["note"] and "dropped" not in res["note"].lower()
    finally:
        w.close()


def test_with_the_buckets_off_the_toast_keeps_its_word(world):
    res = world.act("settle", keys=[f"inbox:{YES_ID}"], outcome="not_doing", reason="outdated")
    assert res["note"].startswith("Dropped")


def test_a_start_is_named_do_it_while_the_buckets_are_on(tmp_path):
    # round 1 (words): Mach das failed with "Nicht gestartet (AI machen lassen): ...", one act under two labels
    from test_bridge_cockpit import World
    w = World(tmp_path, config="cockpit:\n  enabled: true\n  language: en\n  flow:\n    enabled: true\n")
    try:
        res = w.act("do_it", keys=["task:demo-task"])
        assert "Let AI do it" not in res["note"] and "Do it" in res["note"]
    finally:
        w.close()


def test_a_yes_given_keeps_the_point_so_it_stands_in_ill_do(tmp_path):
    # round 1 of the four answers: after Do it an approved item left every bucket of the cockpit (it stayed settled while
    # the next collection still listed it, in I'll do), Due by source then offered Do it again and the server said 409
    from test_bridge_cockpit import World
    w = World(tmp_path, config="cockpit:\n  enabled: true\n  language: en\n  flow:\n    enabled: true\n")
    try:
        res = w.act("do_it", keys=[f"inbox:{YES_ID}"], yes=True)
        assert res["ok"] and f"inbox:{YES_ID}" not in w.app.collector.settled
    finally:
        w.close()


def test_a_task_the_briefing_folds_into_its_inbox_line_is_one_point():
    # round 1 of the four answers: the briefing folded "Decide on the power contract" (the task) into its inbox line
    # "Keep or cancel the power contract", the cockpit showed both, sometimes in two buckets
    import importlib.util
    spec = importlib.util.spec_from_file_location("briefing_view_fold", Path(__file__).resolve().parents[1] / "lib" / "briefing_view.py")
    bv = importlib.util.module_from_spec(spec)
    sys.modules["briefing_view_fold"] = bv
    spec.loader.exec_module(bv)
    items = [{"id": "20260929-1900-keep-or-cancel", "title": "Keep or cancel the power contract", "state": "open", "urgency": "today",
              "kind": "decision", "gate": "only-you", "task": "power"}]
    tasks = [{"id": "power", "title": "Decide on the power contract", "state": "doing", "next": {"what": "decide"},
              "changed_at": "2026-11-01", "url": "work/tasks/power/STATUS.md"}]
    sec = lambda sid, kind, it: {"id": sid, "kind": kind, "title": sid, "status": "ok", "items": it, "all": it, "total": len(it)}
    built = bv.build({"profile": "m", "title": "M", "collected_at": "2026-11-21T08:00",
                      "sections": [sec("inbox", "inbox", items), sec("tasks", "tasks", tasks)]},
                     {"id": "m", "sections": [{"kind": "inbox"}, {"kind": "tasks"}], "view": {"style": "triage"}})
    rows = [r for b in built["buckets"] for r in b["items"]]
    assert len(rows) == 1 and rows[0]["folded_tasks"] == ["power"]
    view = m.parse_view({"view": built}, True, 0)
    t = [{"slug": "power", "label": "power", "title": "Decide on the power contract", "area": "A", "area_names": ["A"], "priority": None,
          "blocked_by": None, "stale": False, "age": 0, "type": None, "status": "doing", "next": "decide", "updated": None, "origin": None}]
    got = m.with_tasks(view, t)
    assert [r["key"] for b in got["buckets"] for r in b["rows"]] == ["inbox:20260929-1900-keep-or-cancel"]


def test_a_point_put_off_in_another_browser_refuses_the_next_answer(world):
    # round 1 (scale): browser B put a task off until tomorrow, browser A pressed Done 50 ms later, and both ran
    world.act("later", key="task:demo-task", until="2026-12-01", was="doing")
    with pytest.raises(ActionError) as err:
        world.act("settle", keys=["task:demo-task"], outcome="done", was="doing")
    assert err.value.code == "point_moved"
