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

def test_task_owner_hands_the_step_to_the_bridge_and_its_undo_gives_it_back(world):
    world.runner.calls.clear()
    res = world.act("task_owner", key="task:demo-task", who="bridge")
    assert writes(world)[0] == K(world, "next", "demo-task", "--who", "bridge", "--json")
    assert res["ok"]
    undo = [it["undo"] for e in world.app.history.state() for it in e["items"] if it["kind"] == "task"][0]
    assert undo["verb"] == "task_next" and undo["args"]["slug"] == "demo-task" and undo["args"]["who"]
    world.runner.calls.clear()
    world.act(undo["verb"], **undo["args"])
    assert writes(world)[0][:5] == K(world, "next", "demo-task", "--who")[:5]


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
