# SPDX-License-Identifier: MIT
"""Contract for the read marks of Work through (scripts/lib/bridge_cockpit/seen.py, cockpit.flow.seen).

Read means out of sight until something new happens to the point or its revisit day comes. The mark is the
cockpit's own state (seen.json in the state folder, never shared through git): opening a point marks it read with
the movement markers it had then; a marker that moves later makes it new again. Not movement: a brief describe
writes, and the person's own verbs (absorb). Revisit (the verb `later` with `revisit: true`) sets the day it comes
back and writes into the task only when a sentence is given.

Run: python3 -m pytest -q scripts/tests/test_bridge_cockpit_seen.py
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_bridge_cockpit import YES_ID, World, ok, private_key_dir, refused, world  # noqa: E402,F401
from lib.bridge_cockpit import config as cf  # noqa: E402
from lib.bridge_cockpit import seen as sn  # noqa: E402
from lib.bridge_cockpit.config import load_web_config  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
TASK = "task:demo-task"
ITEM = f"inbox:{YES_ID}"


def touch(path: Path, at: float) -> None:
    os.utime(path, (at, at))


# ---------------------------------------------------------------- the config block

def test_the_seen_block_is_off_by_default_with_its_intervals_and_counts(tmp_path):
    cfg = load_web_config(tmp_path, {})
    assert cfg.flow["seen"] == {"enabled": False, "open_reads": "auto", "active_days": 7,
                                "revisit_days": {"active": 7, "resting": 14, "backlog": 30, "question": 2, "issue": 7},
                                "counts": {"note": True, "status": True, "doc": True, "run": True, "code": True,
                                           "log": True, "inbox": True}}
    assert cfg.flow == cf.flow_defaults() and cfg.config_warnings == ()


def test_the_seen_block_takes_its_keys_and_keeps_the_rest(tmp_path):
    block = {"enabled": True, "open_reads": "click", "active_days": 5, "revisit_days": {"question": 1},
             "counts": {"log": False}}
    cfg = load_web_config(tmp_path, {"cockpit": {"flow": {"seen": block}}})
    seen = cfg.flow["seen"]
    assert seen["enabled"] is True and seen["open_reads"] == "click" and seen["active_days"] == 5
    assert seen["revisit_days"] == {**sn.DEFAULT_REVISIT, "question": 1}
    assert seen["counts"]["log"] is False and seen["counts"]["note"] is True
    assert cfg.config_warnings == ()


@pytest.mark.parametrize("block, key", [
    ({"enabled": "yes"}, "cockpit.flow.seen.enabled"),
    ({"open_reads": "hover"}, "cockpit.flow.seen.open_reads"),
    ({"active_days": 0}, "cockpit.flow.seen.active_days"),
    ({"revisit_days": {"resting": -1}}, "cockpit.flow.seen.revisit_days.resting"),
    ({"revisit_days": {"later": 3}}, "cockpit.flow.seen.revisit_days.later"),
    ({"counts": {"brief": True}}, "cockpit.flow.seen.counts.brief"),
    ({"counts": {"note": "no"}}, "cockpit.flow.seen.counts.note"),
    ({"colour": "red"}, "cockpit.flow.seen.colour"),
])
def test_a_bad_seen_value_keeps_its_default_and_says_so(tmp_path, block, key):
    cfg = load_web_config(tmp_path, {"cockpit": {"flow": {"seen": block}}})
    assert cfg.flow["seen"] == sn.defaults()
    assert len(cfg.config_warnings) == 1 and cfg.config_warnings[0].startswith(key + ":"), cfg.config_warnings


def test_every_seen_key_has_a_doc_row_and_a_template_line():
    import re
    doc = (ROOT / "docs" / "bridge-cockpit.md").read_text(encoding="utf-8")
    for key in ("seen.enabled", "seen.open_reads", "seen.active_days", "seen.revisit_days", "seen.counts"):
        assert re.search(rf"^\| `flow\.{re.escape(key)}` \|", doc, re.M), f"flow.{key} has no row in docs/bridge-cockpit.md"
    from test_bridge_cockpit_config import template_block
    assert template_block()["flow"]["seen"] == {k: v for k, v in sn.defaults().items()}


# ---------------------------------------------------------------- the markers

def test_a_tasks_markers_are_its_status_file_its_documents_and_the_log_rows_that_name_it(tmp_path):
    w = World(tmp_path, serve=False, prepare=False)
    try:
        folder = w.root / "work" / "tasks" / "demo-task"
        touch(folder / "STATUS.md", 1_800_000_000)
        markers = sn.Markers(w.root)
        got = markers.fresh([TASK])[TASK]
        assert got["file"] == 1_800_000_000_000 and "doc" not in got
        assert got["log"] == int(dt.datetime(2026, 10, 9, 10, 0).timestamp() * 1000), "the newest row naming the slug"
        (folder / "deliverables").mkdir()
        (folder / "deliverables" / "plan.md").write_text("x", encoding="utf-8")
        touch(folder / "deliverables" / "plan.md", 1_800_000_500)
        touch(folder / "deliverables", 1_800_000_100)
        assert markers.fresh([TASK])[TASK]["doc"] == 1_800_000_500_000
        with (w.root / "work" / "log.md").open("a", encoding="utf-8") as fh:
            fh.write("| 2026-10-11 08:00 | x | other | demo-task-two is something else |\n")
        assert markers.fresh([TASK])[TASK]["log"] == int(dt.datetime(2026, 10, 9, 10, 0).timestamp() * 1000), \
            "a longer slug is no mention"
    finally:
        w.close()


def test_an_inbox_items_marker_is_its_newest_event_but_a_brief_a_look_or_a_routing(tmp_path):
    w = World(tmp_path, serve=False, prepare=False)
    try:
        events = w.root / "work" / "inbox" / YES_ID / "events"
        markers = sn.Markers(w.root)
        assert markers.fresh([ITEM])[ITEM] == {}, "the fixture's only event is a runner's look"
        (events / "20261010T080000Z-00-web-note.yaml").write_text("verb: note\n", encoding="utf-8")
        for verb in ("describe", "seen", "area"):
            (events / f"20261012T080000Z-00-mac-mini-{verb}.yaml").write_text(f"verb: {verb}\n", encoding="utf-8")
        at = int(dt.datetime(2026, 10, 10, 8, 0, tzinfo=dt.timezone.utc).timestamp() * 1000)
        assert markers.fresh([ITEM])[ITEM] == {"inbox": at}
    finally:
        w.close()


def test_build_hands_an_items_event_to_its_task_a_runs_end_and_an_issues_change():
    markers = sn.Markers(Path("/nonexistent"))
    rows = [{"key": TASK, "task": "demo-task"}, {"key": "inbox:20261010-0800-x-a1b2", "inbox_id": "20261010-0800-x-a1b2",
                                                "task": "demo-task"}, {"key": "ref:o/r#1"}]
    markers.fresh = lambda keys: {TASK: {"file": 5}, "inbox:20261010-0800-x-a1b2": {"inbox": 9}}
    out = markers.build(rows, returns=[{"key": TASK, "stage": "done", "ended_ms": 7}, {"key": "task:gone", "ended_ms": 8}],
                        code={"ref:o/r#1": 11, "ref:o/r#2": 12})
    assert out == {TASK: {"file": 5, "inbox": 9, "run": 7}, "inbox:20261010-0800-x-a1b2": {"inbox": 9}, "ref:o/r#1": {"code": 11}}


def test_code_markers_read_the_change_of_the_page_items_that_hold_an_issue():
    section = {"id": "gh", "items": [{"id": "o/r#1", "changed_at": "2026-10-09T09:11:00Z"}, {"id": "o/r#2"}]}
    pairs = {"ref:o/r#1": [("work", section, "item:work/gh/o/r#1")], "ref:o/r#2": [("work", section, "item:work/gh/o/r#2")]}
    at = int(dt.datetime(2026, 10, 9, 9, 11, tzinfo=dt.timezone.utc).timestamp() * 1000)
    assert sn.code_markers(None, pairs) == {"ref:o/r#1": at}


# ---------------------------------------------------------------- the store

class Clock:
    def __init__(self, now=dt.datetime(2026, 10, 10, 9, 0).timestamp() * 1000):
        self.now = now

    def __call__(self):
        return self.now


def test_the_store_keeps_read_unread_revisit_and_focus_across_a_restart(tmp_path):
    clock = Clock()
    store = sn.SeenStore(tmp_path, clock)
    assert store.read({TASK: {"file": 5}}) == [TASK]
    assert store.mark(TASK) == {"at": int(clock.now), "m": {"file": 5}, "until": None, "unread": False}
    assert store.unread(TASK) is True and store.unread(TASK) is False
    assert store.unread("task:never") is False, "never opened is unread already"
    before = store.revisit(ITEM, "2026-10-12", {"inbox": 3})
    assert before is None and store.mark(ITEM)["until"] == "2026-10-12"
    assert store.focus(TASK, True) is True and store.focus(TASK, True) is False
    again = sn.SeenStore(tmp_path, clock)
    assert again.state() == store.state()
    assert again.state()["marks"][TASK]["unread"] is True and again.state()["focus"] == [TASK]
    # a read keeps a revisit day the person set while it is ahead, drops it once it came
    again.read({ITEM: {"inbox": 4}})
    assert again.mark(ITEM)["until"] == "2026-10-12"
    clock.now += 3 * 86400_000
    again.read({ITEM: {"inbox": 4}})
    assert again.mark(ITEM)["until"] is None


def test_absorb_takes_in_the_persons_own_change_but_never_one_that_was_pending(tmp_path):
    store = sn.SeenStore(tmp_path, Clock())
    store.read({TASK: {"file": 5}, ITEM: {"inbox": 3}})
    # the person's own note moved the file: taken in
    assert store.absorb({TASK: {"file": 5}}, {TASK: {"file": 9}}) == [TASK]
    assert store.mark(TASK)["m"] == {"file": 9}
    # something new came before the verb (8 > 5): it still counts, the verb takes nothing in
    assert store.absorb({ITEM: {"inbox": 8}}, {ITEM: {"inbox": 10}}) == []
    assert store.mark(ITEM)["m"] == {"inbox": 3}
    assert store.absorb({"task:x": {}}, {"task:x": {"file": 1}}) == [], "no mark, nothing to take in"


# ---------------------------------------------------------------- the server: verbs, state and model

SEEN_ON = ("cockpit:\n  enabled: true\n  language: en\n  flow:\n    enabled: true\n    seen:\n      enabled: true\n"
           "workplace:\n  control:\n    name: Control\n")


@pytest.fixture
def seen_world(tmp_path):
    w = World(tmp_path / "seen", config=SEEN_ON)
    yield w
    w.close()


def test_the_model_carries_the_markers_and_the_state_the_marks_while_seen_is_on(seen_world, world):
    model = seen_world.app.collector.model
    assert TASK in model["moved"] and "file" in model["moved"][TASK]
    assert seen_world.app.state_payload()["seen"] == {"marks": {}, "focus": []}
    assert seen_world.app.state_payload()["work"]["flow"]["seen"]["enabled"] is True
    assert "moved" not in world.app.collector.model, "off: nothing is read for it"


def test_opening_a_point_marks_it_read_with_its_markers_and_unread_takes_it_back(seen_world):
    w = seen_world
    out = w.act("seen_read", keys=[TASK, ITEM])
    assert out["ok"] and not out["note"], "quiet: no toast for an open"
    mark = w.app.seen.mark(TASK)
    assert mark["m"] == w.app.collector.model["moved"][TASK] and mark["unread"] is False
    assert w.app.state_payload()["seen"]["marks"][TASK]["at"] == int(w.clock())
    w.act("seen_unread", key=TASK)
    assert w.app.seen.mark(TASK)["unread"] is True
    w.act("seen_focus", key=TASK, on=True)
    assert w.app.state_payload()["seen"]["focus"] == [TASK]


def test_the_seen_verbs_refuse_while_the_marks_are_off(world):
    refused(world, "seen_off", "seen_read", keys=[TASK])
    refused(world, "seen_off", "seen_unread", key=TASK)


def test_revisit_sets_the_day_and_writes_nothing_into_the_task_without_a_sentence(seen_world):
    w = seen_world
    out = w.act("later", key=TASK, until="2026-10-20", revisit=True)
    assert out["ok"]
    assert w.app.seen.mark(TASK)["until"] == "2026-10-20"
    assert not w.runner.of("task.note"), "no sentence, no note"
    assert TASK not in w.app.store.hidden(), "a revisit hides nothing: the point stays, read, in its overview"
    assert [u["undo"] for u in out["undo"]] == [{"verb": "seen_unread", "args": {"key": TASK}}]


def test_revisit_with_a_sentence_writes_it_as_a_note_and_the_note_stays_read(seen_world):
    w = seen_world
    status = w.root / "work" / "tasks" / "demo-task" / "STATUS.md"

    def note(argv):
        with status.open("a", encoding="utf-8") as fh:
            fh.write("\n- 2026-10-10: Later until 2026-10-20: ask again\n")
        touch(status, time.time() + 5)
        return ok("")
    w.runner.handlers["task.note"] = note
    w.act("later", key=TASK, until="2026-10-20", text="ask again", revisit=True)
    assert w.runner.of("task.note"), "the sentence is a note"
    mark = w.app.seen.mark(TASK)
    assert mark["until"] == "2026-10-20"
    assert mark["m"]["file"] == sn.Markers(w.root).fresh([TASK])[TASK]["file"], "its own note is no news"


def test_later_without_revisit_keeps_its_old_way(seen_world):
    w = seen_world
    w.act("later", key=TASK, until="2026-10-20")
    assert w.app.store.hidden().get(TASK) == "2026-10-20" and w.app.seen.mark(TASK) is None


def test_a_note_of_the_person_on_a_read_point_is_no_news_but_one_from_elsewhere_is(seen_world):
    w = seen_world
    status = w.root / "work" / "tasks" / "demo-task" / "STATUS.md"
    touch(status, 1_800_000_000)
    w.app.collector.rebuild()
    w.act("seen_read", keys=[TASK])

    def note(argv):
        touch(status, 1_800_000_100)
        return ok("")
    w.runner.handlers["task.note"] = note
    w.act("note", key=TASK, text="mine")
    assert w.app.seen.mark(TASK)["m"]["file"] == 1_800_000_100_000, "the person's own verb is taken in"
    touch(status, 1_800_000_200)           # an agent's note, outside the cockpit
    w.app.collector.rebuild()
    assert w.app.collector.model["moved"][TASK]["file"] > w.app.seen.mark(TASK)["m"]["file"]


def test_a_brief_describe_writes_is_no_news(seen_world):
    w = seen_world
    status = w.root / "work" / "tasks" / "demo-task" / "STATUS.md"
    touch(status, 1_800_000_000)
    w.act("seen_read", keys=[TASK])

    def brief(argv):
        touch(status, 1_800_000_300)
        return ok({"basis": "b1"})
    w.runner.handlers["task.brief"] = brief
    item = {"kind": "task", "id": "demo-task", "key": TASK, "basis": "b1"}
    w.app.describe.write(item, {"goal": "Ship the demo.", "criteria": ["It runs."]}, edited=False)
    assert w.app.seen.mark(TASK)["m"]["file"] == 1_800_000_300_000


# ---------------------------------------------------------------- review: absorb, undo, a broken file, the log

def test_a_verb_on_an_item_that_names_a_read_task_is_no_news_to_the_task(seen_world):
    from test_bridge_cockpit import ONLY_ID
    w = seen_world
    events = w.root / "work" / "inbox" / ONLY_ID / "events"
    events.mkdir(parents=True)
    (w.root / "work" / "inbox" / ONLY_ID / "item.yaml").write_text("summary: Review\ntask: demo-task\n", encoding="utf-8")
    (events / "20261001T080000Z-00-mac-note.yaml").write_text("verb: note\n", encoding="utf-8")
    w.app.collector.rebuild()
    assert "inbox" in w.app.collector.model["moved"][TASK], "the item's event stands for the task too"
    w.act("seen_read", keys=[TASK])

    def note(argv):
        (events / "20261009T100000Z-00-web-note.yaml").write_text("verb: note\n", encoding="utf-8")
        return ok("")
    w.runner.handlers["inbox.note"] = note
    w.act("note", key=f"inbox:{ONLY_ID}", text="mine")
    w.app.collector.rebuild()
    assert w.app.collector.model["moved"][TASK]["inbox"] == w.app.seen.mark(TASK)["m"]["inbox"], \
        "the person's own note on the item leaves the task read"


def test_the_undo_of_a_revisit_is_marked_taken_back(seen_world):
    w = seen_world
    out = w.act("later", key=TASK, until="2026-10-20", revisit=True)
    item = w.app.history.open_undo("seen_unread", {"key": TASK})
    assert item is not None and out["undo"]
    w.act("seen_unread", key=TASK)
    assert w.app.history.open_undo("seen_unread", {"key": TASK}) is None, "a stale Undo cannot come back"
    assert w.app.seen.mark(TASK)["unread"] is True


def test_a_broken_mark_is_dropped_and_the_store_still_starts(tmp_path):
    (tmp_path / "seen.json").write_text('{"v": 1, "marks": {"task:a": {"at": 1e999, "m": {}}, "task:b": {"at": 5, "m": {"file": NaN}},'
                                        ' "task:c": {"at": 7, "m": {"file": 3}}}, "focus": ["task:c"]}', encoding="utf-8")
    store = sn.SeenStore(tmp_path, Clock())
    assert set(store.state()["marks"]) == {"task:c"} and store.state()["focus"] == ["task:c"]


def test_a_full_disk_never_turns_a_verb_into_a_failure(seen_world, monkeypatch):
    w = seen_world
    w.act("seen_read", keys=[TASK])
    from lib.bridge_cockpit import store as st

    def full(*a, **k):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(st, "atomic_write_json", full)
    status = w.root / "work" / "tasks" / "demo-task" / "STATUS.md"

    def note(argv):
        touch(status, time.time() + 50)
        return ok("")
    w.runner.handlers["task.note"] = note
    assert w.act("note", key=TASK, text="mine")["ok"]
    assert w.act("later", key=TASK, until="2026-10-20", revisit=True)["ok"]


def test_the_log_names_a_one_word_slug_only_as_a_task_reference(tmp_path):
    root = tmp_path
    for slug in ("backup", "demo-task"):
        (root / "work" / "tasks" / slug).mkdir(parents=True)
        (root / "work" / "tasks" / slug / "STATUS.md").write_text("# x\n", encoding="utf-8")
    log = root / "work" / "log.md"
    log.write_text("| 2026-10-09 09:00 | x | other | the backup ran fine, demo-task moved |\n", encoding="utf-8")
    markers = sn.Markers(root)
    got = markers.fresh(["task:backup", "task:demo-task"])
    assert "log" not in got["task:backup"], "an ordinary word is no mention of a one-word slug"
    assert "log" in got["task:demo-task"], "a slug with a hyphen is distinctive enough as a word"
    for row in ("| 2026-10-09 10:00 | x | backup | done |", "| 2026-10-09 10:01 | x | other | see work/tasks/backup/STATUS.md |",
                "| 2026-10-09 10:02 | x | other | task:backup closed |", "| 2026-10-09 10:03 | x | other | task.py note backup -- hi |"):
        log.write_text(row + "\n", encoding="utf-8")
        assert "log" in sn.Markers(root).fresh(["task:backup"])["task:backup"], row


# ---------------------------------------------------------------- follow-up: the instruction line and Activity say Revisit

def test_the_planner_hears_later_as_a_revisit_while_the_marks_are_on():
    from lib.bridge_cockpit import instruct as ins
    pts = [{"n": 1, "title": "x", "out": {"kind": "task", "settle": ["done"]}, "tab": None}]
    plain, _ = ins.prompt(pts, "later", "2026-10-09", "English", [], True)
    revisit, _ = ins.prompt(pts, "later", "2026-10-09", "English", [], True, revisit=True)
    assert "comes back unread" not in plain and "later (not now;" in plain
    assert "later (not now: the point is read now and comes back unread on until" in revisit


def test_a_revisit_stands_in_activity_as_a_revisit_with_its_day(seen_world):
    w = seen_world
    w.act("later", key=TASK, until="2026-10-20", revisit=True)
    data = w.app.activity.view(TASK, fresh=True)
    [row] = [r for r in data["rows"] if r["kind"] == "decision"]
    assert row["change"]["new"] == "revisit" and row["change"]["until"] == "2026-10-20"
    assert row["text"].startswith("Revisit")
