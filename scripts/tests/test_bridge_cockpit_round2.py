# SPDX-License-Identifier: MIT
"""Round 2 of the cockpit simulation (21.11.2026): an answer reaches only the point as the page saw it.

A second browser that slept (a laptop lid, a dropped event stream) still showed a point another browser had
answered. Its answer went through and replaced the first one: a Later became a drop, and a Later on a dropped
item was confirmed as "back tomorrow" though it never came back. The page now names the state it saw (`was`), and
the server refuses an answer to a point that moved on since (409 point_moved); nothing is written.

Run: pytest -q scripts/tests/test_bridge_cockpit_round2.py
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

from lib.bridge_cockpit.actions_base import ActionError  # noqa: E402
from test_bridge_cockpit import YES_ID, World, private_key_dir  # noqa: E402,F401  (the autouse fixture comes along)


@pytest.fixture
def world(tmp_path):
    w = World(tmp_path)
    yield w
    w.close()


def event(w: World, item: str, name: str, body: str) -> None:
    (w.root / "work" / "inbox" / item / "events" / name).write_text(body, encoding="utf-8")


def moved(w: World, verb: str, **args) -> None:
    w.runner.calls.clear()
    with pytest.raises(ActionError) as err:
        w.act(verb, **args)
    assert (err.value.status, err.value.code) == (409, "point_moved")
    assert not [c for c in w.runner.calls if "defer" in c or "drop" in c or "approve" in c or "status" in c or "review" in c]


def test_an_answer_to_an_item_another_browser_put_off_or_dropped_is_refused(world):
    key = f"inbox:{YES_ID}"
    event(world, YES_ID, "20261009T100000Z-02-web-defer.yaml", "verb: defer\nby: web\nat: '2026-10-09T10:00'\nuntil: '2026-12-01'\n")
    moved(world, "settle", keys=[key], outcome="not_doing", was="open")
    moved(world, "do_it", keys=[key], yes=True, was="open")
    # the page that saw it put off answers it as it is
    world.act("later", key=key, until="2026-12-02", was="deferred")
    event(world, YES_ID, "20261009T100100Z-03-web-drop.yaml", "verb: drop\nby: web\nat: '2026-10-09T10:01'\n")
    moved(world, "later", key=key, until="2026-10-10", was="deferred")
    moved(world, "later", key=key, until="2026-10-10", was="open")


def test_an_answer_to_a_task_another_browser_parked_is_refused(world):
    status = world.root / "work" / "tasks" / "demo-task" / "STATUS.md"
    status.write_text(status.read_text(encoding="utf-8").replace("status: doing", "status: backlog"), encoding="utf-8")
    moved(world, "task_keep", keys=["task:demo-task"], was="doing")
    moved(world, "task_park", key="task:demo-task", was="doing")


def test_without_was_nothing_is_compared(world):
    # every other caller (the chat, the classic page, a script) acts as before
    world.act("later", key=f"inbox:{YES_ID}", until="2026-10-10")
    assert world.runner.of("inbox.defer")
