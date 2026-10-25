# SPDX-License-Identifier: MIT
"""Where a note leads: the `go` target of an action note (actions_base.note_go, Ctx.note, App.note).

A toast that names its place can be clicked to get there. The server hands that place along with the note,
in the action result and in the `note` broadcast, as one small closed union; any other shape is dropped,
never passed through.

Run: pytest -q scripts/tests/test_bridge_cockpit_note_go.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
for p in (ROOT / "scripts", ROOT / "scripts" / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from lib.bridge_cockpit.actions_base import Ctx, note_go  # noqa: E402
from test_bridge_cockpit import World, private_key_dir  # noqa: E402,F401  (the autouse fixture comes along)


@pytest.fixture
def world(tmp_path):
    w = World(tmp_path)
    yield w
    w.close()


# ---------------------------------------------------------------- the union


@pytest.mark.parametrize("go", [
    {"kind": "tab", "ref": "surface:7"},
    {"kind": "row", "key": "ref:example/repo#12"},
    {"kind": "item", "key": "task:demo-task"},
    {"kind": "item", "key": "inbox:20261009-0910-tidy-labels-c3d4"},
    {"kind": "page", "id": "tasks"},
    {"kind": "page", "id": "@sessions"},
    {"kind": "conv", "id": "g0123456789"},
    {"kind": "ask", "id": "q0123456789"},
    {"kind": "claude"},
])
def test_a_known_target_passes_as_it_is(go):
    assert note_go(go) == go


def test_only_the_fields_of_its_kind_are_kept():
    assert note_go({"kind": "tab", "ref": "surface:7", "path": "/etc/passwd", "x": 1}) == {"kind": "tab", "ref": "surface:7"}
    assert note_go({"kind": "claude", "id": "anything"}) == {"kind": "claude"}


@pytest.mark.parametrize("go", [
    None, "surface:7", ["tab", "surface:7"], {}, {"kind": "file", "path": "work/tasks/x"},
    {"kind": ["tab"], "ref": "surface:7"}, {"kind": {"x": 1}},
    {"kind": "tab"}, {"kind": "tab", "ref": 7}, {"kind": "tab", "ref": "--all"}, {"kind": "tab", "ref": "surface:7\n"},
    {"kind": "row", "key": "nokind"}, {"kind": "row", "key": "task:../../etc"},
    {"kind": "item", "key": "ref:example/repo#12"},          # only an inbox item or a task opens in the item drawer
    {"kind": "page", "id": "../settings"}, {"kind": "page", "id": "x" * 80},
    {"kind": "conv", "id": "q0123456789"}, {"kind": "ask", "id": "g0123456789"},
    {"kind": "row", "key": "title:" + "x" * 400},
])
def test_any_other_shape_is_dropped(go):
    assert note_go(go) is None


def test_the_first_note_with_a_target_wins_and_a_bad_one_is_never_kept():
    ctx = Ctx(None, "x")
    ctx.note("one", go={"kind": "nope"})
    assert ctx.go is None
    ctx.note("two", go={"kind": "tab", "ref": "surface:7"})
    ctx.note("three", go={"kind": "tab", "ref": "surface:8"})
    assert ctx.go == {"kind": "tab", "ref": "surface:7"}
    assert ctx.notes == ["one", "two", "three"]


# ---------------------------------------------------------------- the server note and the action result


def test_the_server_note_keeps_a_valid_target_and_drops_another(world):
    world.app.note("look here", "warn", {"kind": "tab", "ref": "surface:7"})
    assert world.app.notes[-1]["go"] == {"kind": "tab", "ref": "surface:7"}
    world.app.note("plain", "info", {"kind": "file", "path": "/etc/passwd"})
    assert "go" not in world.app.notes[-1]
    world.app.note("plain too")
    assert "go" not in world.app.notes[-1]


def test_a_tab_verb_leads_back_to_its_tab_in_the_result_and_the_broadcast(world):
    res = world.act("tab_jump", tab_ref="surface:7")
    assert res["note"] and res["go"] == {"kind": "tab", "ref": "surface:7"}
    assert world.app.notes[-1]["go"] == {"kind": "tab", "ref": "surface:7"}
    res = world.act("tab_send", tab_ref="surface:7", text="please continue")
    assert res["go"] == {"kind": "tab", "ref": "surface:7"}


def test_a_closed_tab_leads_nowhere(world):
    res = world.act("tab_close", tab_ref="surface:8")
    assert res["note"] and res["go"] is None
    assert "go" not in world.app.notes[-1]


def test_a_tab_adopted_by_a_task_leads_to_the_task(world):
    res = world.act("adopt", key="task:other-task", tab_ref="surface:11")
    assert res["go"] == {"kind": "item", "key": "task:other-task"}


def test_a_row_edit_leads_to_its_row(world):
    res = world.act("note", key="task:demo-task", text="checked the labels")
    assert res["note"] and res["go"] == {"kind": "item", "key": "task:demo-task"}


def test_a_step_on_a_page_row_leads_to_that_page(world):
    import json
    from test_bridge_cockpit import ok
    world.runner.handlers["briefing.act"] = lambda argv: ok(json.dumps({"ok": True, "did": "turned down"}))
    res = world.act("row_action", page="tasks", section="apps", index=0, action="turned_down")
    assert res["go"] == {"kind": "page", "id": "tasks"}

