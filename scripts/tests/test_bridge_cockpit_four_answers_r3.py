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


# ---------------------------------------------------------------- calm: one number per row, printed as it is

def _sec(sid, kind, items):
    return {"id": sid, "kind": kind, "title": sid, "status": "ok", "items": items, "all": items, "total": len(items)}


def _calm(n_do=12, n_plan=9, n_wait=3, max_items=10):
    items = [{"id": f"20261001-09{n:02d}-ask-{n}", "title": f"Ask {n}", "state": "open", "kind": "decision",
              "gate": "your-yes", "urgency": "now"} for n in range(n_do)]
    items += [{"id": f"20261001-10{n:02d}-plan-{n}", "title": f"Plan {n}", "state": "open", "kind": "decision",
               "gate": "your-yes", "urgency": "later"} for n in range(n_plan)]
    items += [{"id": f"20261001-11{n:02d}-wait-{n}", "title": f"Wait {n}", "state": "open", "kind": "decision",
               "waits_for": True} for n in range(n_wait)]
    result = {"profile": "m", "title": "M", "collected_at": "2026-11-21T08:00", "sections": [_sec("inbox", "inbox", items)]}
    prof = lambda cap: {"id": "m", "sections": [{"kind": "inbox"}], "view": {"style": "calm", "max_items": cap}}  # noqa: E731
    return bv.build(result, prof(max_items)), bv.build(result, prof(10 ** 6))


def test_calm_prints_each_row_by_its_number_in_the_whole_list():
    # round 3: calm printed its own consecutive numbers (Plan 33 to 35), the view carried 43 to 45, the cards said 43
    short, whole = _calm()
    text = bv.draw_calm(short)
    import re as _re
    printed = {int(m.group(1)) for m in _re.finditer(r"(?m)^(\d+)\. ", text)}
    carried = {r["nr"] for r in bv.numbered(short)}
    assert printed == carried
    nr_whole = {r["title"]: r["nr"] for b in whole["buckets"] for r in b["items"]}
    assert all(nr_whole[r["title"]] == r["nr"] for r in bv.numbered(short))


def test_calm_numbers_every_row_of_every_bucket():
    # round 3: 41 of 96 cards had no number, calm numbered 5 Plan and 3 I'll do rows and nothing past them
    _short, whole = _calm()
    rows = [r for b in whole["buckets"] for r in b["items"]]
    assert all(r.get("nr") for r in rows)
    assert sorted(r["nr"] for r in rows) == list(range(1, len(rows) + 1))
