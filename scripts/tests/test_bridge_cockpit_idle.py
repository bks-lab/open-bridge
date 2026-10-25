# SPDX-License-Identifier: MIT
"""A tab that is done is not a tab that waits on you (25.10.).

The terminal reports `waiting` for a tab that asks something and for a tab that simply finished, so the
start page counted every finished tab as "waits for you". A tab is idle when it waits, is not settled
otherwise, has been still for `cockpit.idle_minutes` (default 10) and its last words ask nothing: no
question mark, no options, nothing typed in its prompt. A settled tab (its item or task is done) is idle at
once. An idle tab leaves `waiting` and carries `idle`; its screen is still read, so a question that comes
later brings it back. In doubt (no screen read) it keeps waiting. Uses the world of test_bridge_cockpit.
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_bridge_cockpit import STATUS, World, ok, private_key_dir  # noqa: E402,F401  (the autouse fixture comes along)
from test_bridge_cockpit_asks import DRAFTED, PERMISSION, SUMMARY, WAITING  # noqa: E402
from lib.bridge_cockpit import model as m  # noqa: E402

MIN = 60 * 1000
TAB = {"ref": "surface:13", "state": "waiting"}
DONE = {"text": "Done. The tests are green.", "options": [], "hash": "h", "yes_no": False, "draft": False}


# ---------------------------------------------------------------- the rule

@pytest.mark.parametrize("ask, since, settled, after, want", [
    (DONE, 0, None, 10 * MIN, True),                                   # still long enough, asks nothing
    (DONE, 5 * MIN, None, 10 * MIN, False),                            # not still long enough yet
    ({**DONE, "yes_no": True}, 0, None, 10 * MIN, False),              # asks something
    ({**DONE, "options": [{"n": 1, "label": "Yes"}]}, 0, None, 10 * MIN, False),
    ({**DONE, "draft": True}, 0, None, 10 * MIN, False),               # someone types an answer
    (None, 0, None, 10 * MIN, False),                                  # nothing read: in doubt it waits
    (None, 9 * MIN, "item", 10 * MIN, True),                           # settled: idle at once
    (DONE, 0, None, 0, False),                                         # idle_minutes 0 switches it off
])
def test_is_idle(ask, since, settled, after, want):
    assert m.is_idle(TAB, ask, since, settled, 10 * MIN, after) is want


def test_only_a_waiting_tab_can_be_idle():
    for state in ("needs-you", "working", "shell"):
        assert m.is_idle({**TAB, "state": state}, DONE, 0, "item", 10 * MIN, 10 * MIN) is False


def test_an_idle_tab_does_not_wait_but_still_counts_as_a_candidate_for_its_screen():
    tab = {**TAB, "slug": None, "idle": True}
    assert m.is_waiting(tab, None) is False
    assert m.waits(tab, None) is True


# ---------------------------------------------------------------- the poll

@pytest.fixture
def world(tmp_path):
    w = World(tmp_path, asks=True)
    yield w
    w.close()


def screens(world, by_ref: dict[str, str]) -> None:
    world.runner.handlers["workplace.screen"] = lambda argv: ok({"text": by_ref.get(argv[argv.index("screen") + 1], SUMMARY)})


def tab(world, ref: str = "surface:13") -> dict:
    return next(t for t in world.app.tabs_state()["tabs"] if t["ref"] == ref)


def test_a_finished_tab_turns_idle_after_ten_quiet_minutes(world):
    screens(world, {"surface:7": PERMISSION, "surface:13": SUMMARY})
    world.app.tabs.poll()
    assert tab(world)["waiting"] is True and tab(world)["idle"] is False
    world.clock.advance(11 * 60)
    world.app.tabs.poll()
    assert tab(world)["waiting"] is False and tab(world)["idle"] is True
    # the dialog of the other tab still waits, whatever the clock
    assert tab(world, "surface:7")["waiting"] is True and tab(world, "surface:7")["idle"] is False
    world.app.collector.rebuild()
    assert world.app.collector.model["counts"]["waiting_tabs"] == 1


def test_a_tab_that_asks_or_has_a_draft_keeps_waiting(world):
    by_ref = {"surface:13": WAITING}
    screens(world, by_ref)
    world.app.tabs.poll()
    world.clock.advance(11 * 60)
    world.app.tabs.poll()
    assert tab(world)["waiting"] is True and tab(world)["idle"] is False
    by_ref["surface:13"] = DRAFTED
    world.clock.advance(61)
    world.app.tabs.poll()
    assert tab(world)["waiting"] is True and tab(world)["idle"] is False


def test_a_question_after_the_quiet_brings_the_tab_back(world):
    by_ref = {"surface:13": SUMMARY}
    screens(world, by_ref)
    world.app.tabs.poll()
    world.clock.advance(11 * 60)
    world.app.tabs.poll()
    assert tab(world)["idle"] is True
    by_ref["surface:13"] = WAITING
    world.clock.advance(61)
    world.app.tabs.poll()
    assert tab(world)["waiting"] is True and tab(world)["idle"] is False


def test_a_tab_that_works_again_is_no_longer_idle(world):
    screens(world, {"surface:13": SUMMARY})
    world.app.tabs.poll()
    world.clock.advance(11 * 60)
    world.app.tabs.poll()
    assert tab(world)["idle"] is True
    world.runner.handlers["workplace.status"] = lambda argv: ok(
        [dict(t, state="working") if t["ref"] == "surface:13" else t for t in STATUS])
    world.app.tabs.poll()
    assert tab(world)["idle"] is False and tab(world)["waiting"] is False


def test_a_poll_without_questions_keeps_the_idle_mark(world):
    screens(world, {"surface:13": SUMMARY})
    world.app.tabs.poll()
    world.clock.advance(11 * 60)
    world.app.tabs.poll()
    world.app.tabs.poll(asks=False)
    assert tab(world)["idle"] is True


def test_idle_minutes_zero_switches_it_off(world):
    world.app.cfg = dataclasses.replace(world.app.cfg, idle_minutes=0)
    screens(world, {"surface:13": SUMMARY})
    world.app.tabs.poll()
    world.clock.advance(60 * 60)
    world.app.tabs.poll()
    assert tab(world)["waiting"] is True and tab(world)["idle"] is False


def test_the_control_tab_is_never_idle(world):
    screens(world, {"surface:3": SUMMARY})
    world.app.tabs.poll()
    world.clock.advance(11 * 60)
    world.app.tabs.poll()
    assert tab(world, "surface:3")["idle"] is False


# ---------------------------------------------------------------- review 25.10.: every place that says "waits"

def test_an_idle_tab_is_never_long_waiting():
    seen = {"surface:13": {"state": "waiting", "since_ms": 0}}
    assert m.long_state({**TAB, "idle": True}, seen, 2 * m.LONG_MS) is None
    assert m.long_state(TAB, seen, 2 * m.LONG_MS) == "waiting"


def test_an_idle_tab_raises_no_hour_alert_and_no_long_mark(world):
    alerts: list = []
    on_tabs = world.app.on_tabs
    world.app.on_tabs = lambda a: (alerts.extend(a), on_tabs(a))
    screens(world, {"surface:13": SUMMARY})
    world.app.tabs.poll()
    world.clock.advance(11 * 60)
    world.app.tabs.poll()
    world.clock.advance(61 * 60)
    world.app.tabs.poll()
    assert tab(world)["idle"] is True and tab(world)["long"] is None
    assert not [a for a in alerts if a["kind"] == "tab_long" and a["ref"] == "surface:13"]


def test_the_guide_does_not_read_an_idle_tab():
    from lib.bridge_cockpit import guide
    assert guide.Guide.wants({"ref": "s", "state": "waiting", "live": True}) is True
    assert guide.Guide.wants({"ref": "s", "state": "waiting", "live": True, "idle": True}) is False


def test_a_tab_whose_task_is_done_is_idle_at_once(world):
    screens(world, {"surface:13": WAITING})
    world.app.tabs.poll()
    assert tab(world)["idle"] is False
    done = world.root / "work" / "done" / "2026-10" / "wait-task"
    done.mkdir(parents=True)
    (done / "STATUS.md").write_text("---\nslug: wait-task\nstatus: done\n---\n", encoding="utf-8")
    world.clock.advance(2)
    world.app.tabs.poll()
    assert tab(world)["idle"] is True and tab(world)["waiting"] is False


def test_the_idle_mark_is_not_carried_over_to_the_control_tab(world):
    screens(world, {"surface:13": SUMMARY})
    world.app.tabs.poll()
    world.clock.advance(11 * 60)
    world.app.tabs.poll()
    assert next(t for t in world.app.tabs.tab_list() if t["ref"] == "surface:13")["idle"] is True
    world.app.tabs.pick_control = lambda tabs, now: "surface:13"
    world.app.tabs.poll(asks=False)
    assert next(t for t in world.app.tabs.tab_list() if t["ref"] == "surface:13")["idle"] is False


def test_a_carried_mark_needs_the_same_state(world):
    screens(world, {"surface:13": SUMMARY})
    world.app.tabs.poll()
    world.clock.advance(11 * 60)
    world.app.tabs.poll()
    world.runner.handlers["workplace.status"] = lambda argv: ok(
        [dict(t, state="needs-you") if t["ref"] == "surface:13" else t for t in STATUS])
    world.app.tabs.poll(asks=False)
    assert tab(world)["idle"] is False and tab(world)["waiting"] is True
