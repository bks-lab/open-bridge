# SPDX-License-Identifier: MIT
"""Round 3 of the simulation of the four answers: what the testers reproduced on simulated Bridges, the server's,
the chat's and the briefing's part.

Run: python3 -m pytest -q scripts/tests/test_bridge_cockpit_four_answers_r3.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_bridge_cockpit import YES_ID, K, World, writes  # noqa: E402

_spec = importlib.util.spec_from_file_location("briefing_view_r3", Path(__file__).resolve().parents[1] / "lib" / "briefing_view.py")
bv = importlib.util.module_from_spec(_spec)
sys.modules["briefing_view_r3"] = bv
_spec.loader.exec_module(bv)

BUCKETS_ON = "cockpit:\n  enabled: true\n  language: en\n  flow:\n    enabled: true\n"


@pytest.fixture
def w(tmp_path):
    world = World(tmp_path, config=BUCKETS_ON)
    try:
        yield world
    finally:
        world.close()


def _step(world, line, slug="demo-task"):
    path = world.root / "work" / "tasks" / slug / "STATUS.md"
    path.write_text(path.read_text(encoding="utf-8").replace("origin: invented\n", f"origin: invented\nnext: {line}\n"),
                    encoding="utf-8")
    world.app.collector.request("both")
    world.app.collector.drain()


# ---------------------------------------------------------------- With … you on a step with a check-in

def test_with_you_on_a_step_with_a_check_in_takes_the_check_in_back_and_its_undo_returns_it(w):
    # round 3: With … du on a task handed to Kim with a check-in kept "In progress with me, check-in 2026-11-29"
    _step(w, "{what: Ship it, who: Kim, check: 2026-11-29}")
    w.runner.calls.clear()
    res = w.act("task_owner", key="task:demo-task", who="me")
    assert res["ok"]
    assert writes(w)[0] == K(w, "next", "demo-task", "--who", "me", "--clear-check", "--json")
    undo = [it["undo"] for e in w.app.history.state() for it in e["items"] if it["kind"] == "task"][0]
    assert undo["args"]["who"] == "Kim" and undo["args"]["check"] == "2026-11-29"
