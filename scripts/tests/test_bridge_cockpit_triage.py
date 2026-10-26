# SPDX-License-Identifier: MIT
"""The dashboard's triage: the last run of scripts/triage.py for the page, a run in the background on
a click and once a day, only the allowed argv. Uses the world of test_bridge_cockpit (fake runner)."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_bridge_cockpit import World, ok, private_key_dir  # noqa: E402,F401  (the autouse fixture comes along)

LAST = {"at": "2026-10-10T20:00:00", "cost_usd": 0.024, "cost_known": True, "calls": 3, "model": "claude-haiku-5-5",
        "items": [{"key": "task:demo-task", "kind": "task", "title": "Demo", "gist": "Demo fertig machen",
                   "verdict": "close", "reason": "PR gemergt", "doer": "ai", "effort": "small", "why": "Code im Repo",
                   "verdict_from": "check", "model": "claude-haiku-5-5", "cached": False},
                  {"key": "inbox:x-1", "kind": "inbox", "title": "Frage", "gist": "Frage an dich", "verdict": "keep",
                   "doer": "you", "effort": None, "why": "nur du", "reason": "", "secret": "never shown"}],
        "counts": {"close": 1, "ai": 1, "you": 1, "unclear": 0}}


@pytest.fixture
def world(tmp_path):
    w = World(tmp_path)
    yield w
    w.close()


def write_last(world, last=LAST):
    path = world.app.root / ".bridge" / "triage.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "items": {}, "last": last}), encoding="utf-8")


def test_without_a_run_the_page_gets_an_empty_triage_and_a_run_is_due(world):
    st = world.app.triage.state()
    assert st["items"] == {} and st["last"] is None and st["running"] is None
    assert world.app.triage.due(time.time())


def test_the_last_run_reaches_the_page_keyed_and_trimmed(world):
    write_last(world)
    st = world.app.triage.state()
    assert st["items"]["task:demo-task"]["gist"] == "Demo fertig machen"
    assert st["items"]["inbox:x-1"]["doer"] == "you" and "secret" not in st["items"]["inbox:x-1"]
    assert st["last"]["cost_ct"] == 2.4 and st["last"]["model"] == "haiku-5-5" and st["last"]["count"] == 2
    assert world.app.state_payload()["triage"]["items"]["inbox:x-1"]["gist"] == "Frage an dich"


def test_a_click_runs_triage_py_in_the_background_with_the_allowed_argv(world):
    world.runner.handlers["triage.run"] = lambda argv: ok(LAST)
    world.runner.calls.clear()
    status, _, body = world.post("/api/triage/run", {"fresh": True})
    assert status == 202 and json.loads(body)["ok"] is True
    end = time.time() + 3
    while world.app.triage.state()["running"] and time.time() < end:
        time.sleep(0.02)
    argv = world.runner.of("triage.run")[0]
    assert argv[0] == sys.executable and argv[1].endswith("scripts/triage.py") and argv[-3:] == ["run", "--json", "--fresh"]
    # the board, application and issue rows come from the cockpit's own view, handed over as a file
    assert world.app.store.view_path.is_file()
    assert argv[argv.index("--view") + 1] == str(world.app.store.view_path) and argv.index("--view") < argv.index("run")
    status, _, _ = world.post("/api/triage/run", {"what": 1})
    assert status == 400


def test_a_run_once_a_day(world):
    write_last(world, {**LAST, "at": "2026-10-10T20:00:00"})
    import datetime as dt
    at = dt.datetime.fromisoformat("2026-10-10T20:00:00").timestamp()
    assert not world.app.triage.due(at + 3600) and world.app.triage.due(at + 25 * 3600)


def test_next_rank_takes_a_fresh_jev_rank_and_leaves_out_an_old_one(world):
    """The Work through area orders tasks by `next_rank`: the rank of Jev's last order of a page, only while
    it is younger than cockpit.flow.rank_max_age_days (7), so old and new judgments never mix (review F6)."""
    from lib.bridge_cockpit import jev
    write_last(world)
    now = world.app.clock()
    day = 24 * 3600 * 1000
    jev._pages_state(world.app).orders = {
        "arbeit": {"at_ms": now - day, "items": [{"key": "task:demo-task", "rank": 2}, {"key": "task:nobody", "rank": 1}]},
        "alt": {"at_ms": now - 8 * day, "items": [{"key": "inbox:x-1", "rank": 1}]},
    }
    items = world.app.triage.state()["items"]
    assert (items["task:demo-task"]["next_rank"], items["task:demo-task"]["rank_at"]) == (2, now - day)
    assert (items["inbox:x-1"]["next_rank"], items["inbox:x-1"]["rank_at"]) == (None, None)
    assert "task:nobody" not in items                      # a rank alone makes no triage row
    # a newer order of another page wins for the same row
    jev._pages_state(world.app).orders["neu"] = {"at_ms": now - 1000, "items": [{"key": "task:demo-task", "rank": 5}]}
    assert world.app.triage.state()["items"]["task:demo-task"]["next_rank"] == 5
    # a shorter limit drops the day-old rank too
    import dataclasses
    world.app.cfg = dataclasses.replace(world.app.cfg, flow_rank_max_age_days=1)
    del jev._pages_state(world.app).orders["neu"]
    world.clock.advance(3600)
    assert world.app.triage.state()["items"]["task:demo-task"]["next_rank"] is None


def test_a_damaged_jev_order_never_breaks_the_triage(world):
    from lib.bridge_cockpit import jev
    write_last(world)
    jev._pages_state(world.app).orders = {"x": "nope", "y": {"at_ms": "soon", "items": [{"key": "task:demo-task", "rank": 1}]},
                                          "z": {"at_ms": world.app.clock(), "items": ["bad", {"key": "task:demo-task", "rank": True}]}}
    assert world.app.triage.state()["items"]["task:demo-task"]["next_rank"] is None
