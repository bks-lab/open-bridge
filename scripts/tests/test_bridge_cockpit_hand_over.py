# SPDX-License-Identifier: MIT
"""Contract for Hand over and a Drop that drops (Work through, cockpit.flow.seen and cockpit.flow.drop_idea).

With the read marks on, In progress ▾ is Hand over ▾: only for someone else, the same verb work_on and check-in, its
words say handed over. Drop on a task follows cockpit.flow.drop_idea: true (the default, as before) shelves it (the
task declined, an idea filed and put off), false closes it as declined with its reason and files no idea.

Run: python3 -m pytest -q scripts/tests/test_bridge_cockpit_hand_over.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_bridge_cockpit import TOMORROW, World, private_key_dir, world  # noqa: E402,F401
from lib.bridge_cockpit import config as cf  # noqa: E402
from lib.bridge_cockpit.config import load_web_config  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
BASE = "cockpit:\n  enabled: true\n  language: en\n  flow:\n    enabled: true\n"


def flow_world(tmp_path, extra: str) -> World:
    return World(tmp_path / "w", config=BASE + extra + "workplace:\n  control:\n    name: Control\n")


# ---------------------------------------------------------------- the key

def test_drop_idea_is_on_by_default_so_a_drop_shelves_as_before(tmp_path):
    cfg = load_web_config(tmp_path, {})
    assert cfg.flow["drop_idea"] is True and cf.flow_defaults()["drop_idea"] is True
    assert load_web_config(tmp_path, {"cockpit": {"flow": {"drop_idea": False}}}).flow["drop_idea"] is False


def test_a_bad_drop_idea_keeps_its_default_and_says_so(tmp_path):
    cfg = load_web_config(tmp_path, {"cockpit": {"flow": {"drop_idea": "no"}}})
    assert cfg.flow["drop_idea"] is True
    assert len(cfg.config_warnings) == 1 and cfg.config_warnings[0].startswith("cockpit.flow.drop_idea:")


def test_drop_idea_has_a_doc_row_and_a_template_line():
    import re
    doc = (ROOT / "docs" / "bridge-cockpit.md").read_text(encoding="utf-8")
    assert re.search(r"^\| `flow\.drop_idea` \|", doc, re.M)
    from test_bridge_cockpit_config import template_block
    assert template_block()["flow"]["drop_idea"] is True


# ---------------------------------------------------------------- Drop on a task

def test_drop_idea_true_shelves_the_task(world):
    world.runner.calls.clear()
    world.act("shelve", key="task:other-task", reason="not needed")
    assert world.runner.of("task.shelve") and not world.runner.of("task.close")


def test_drop_idea_false_closes_the_task_as_declined_and_files_no_idea(tmp_path):
    w = flow_world(tmp_path, "    drop_idea: false\n")
    try:
        w.runner.calls.clear()
        res = w.act("shelve", key="task:other-task", reason="not needed")
        assert not w.runner.of("task.shelve"), "no idea is filed"
        [argv] = w.runner.of("task.close")
        assert "--declined" in argv and any("not needed" in a for a in argv)
        assert res["ok"] and res["settled"] == ["task:other-task"]
        undo = [it["undo"] for e in w.app.history.state() for it in e["items"] if it["kind"] == "task"][0]
        assert undo["verb"] == "task_reopen"
    finally:
        w.close()


# ---------------------------------------------------------------- Hand over

def test_hand_over_words_it_as_handed_over_while_the_marks_are_on(tmp_path):
    w = flow_world(tmp_path, "    seen:\n      enabled: true\n")
    try:
        w.act("work_on", key="task:demo-task", who="Robin", until=TOMORROW, text="the numbers")
        notes = [a for c in w.runner.of("task.note") for a in c]
        assert any(a.startswith("Handed over to Robin") for a in notes), notes
        dids = [it["did"] for e in w.app.history.state() for it in e["items"]]
        assert f"handed over to Robin until {TOMORROW}" in dids
    finally:
        w.close()


def test_in_progress_keeps_its_words_while_the_marks_are_off(world):
    world.act("work_on", key="task:demo-task", who="Robin", until=TOMORROW, text="the numbers")
    notes = [a for c in world.runner.of("task.note") for a in c]
    assert any(a.startswith("In progress with Robin") for a in notes), notes
