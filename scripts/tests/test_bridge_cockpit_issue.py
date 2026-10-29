# SPDX-License-Identifier: MIT
"""The cockpit's issue card on a board: GET /api/issue reads what the boards say now (issue_transition.py plan), the
verbs issue_review and issue_done move the issue through skills/github-projects-manager/scripts/issue_transition.py,
the one write path to the boards, and only on a person's click. Done takes the row out of the list at once."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_bridge_cockpit import World, ok, private_key_dir  # noqa: E402,F401  (the autouse fixture comes along)

from lib.bridge_cockpit.actions import ActionError  # noqa: E402
from lib.bridge_cockpit.runner import RunResult  # noqa: E402

KEY = "ref:example/repo#12"
SCRIPT = "skills/github-projects-manager/scripts/issue_transition.py"
PLAN = {"ok": True, "ref": "example/repo#12", "type": "issue", "state": "OPEN", "url": "https://github.com/example/repo/issues/12",
        "title": "Fix the example issue", "unmatched": [],
        "boards": [{"slug": "ops", "title": "Ops", "owner": "example", "number": 7, "status": "In Progress",
                    "review_state": "In Review", "done_state": "Done", "in_review": False, "in_done": False,
                    "rules": ["done_requires_review"]}]}


def failed(data: dict) -> RunResult:
    return RunResult(False, 1, json.dumps(data), "", 5)


@pytest.fixture
def world(tmp_path):
    w = World(tmp_path)
    yield w
    w.close()


def issue_calls(w: World) -> list[list[str]]:
    return [c for c in w.runner.calls if len(c) > 1 and c[1].endswith(SCRIPT)]


def test_the_runner_may_run_the_board_script_and_nothing_beside_it(world):
    assert SCRIPT in world.app.runner.script(SCRIPT)
    world.app.runner.check([world.app.runner.python, world.app.runner.script(SCRIPT), "--root", str(world.root), "plan", "a/b#1"])


def test_get_issue_reads_the_plan_of_the_boards_and_refuses_what_is_no_issue_ref(world):
    world.runner.handlers["issue_transition.plan"] = lambda argv: ok(PLAN)
    status, _, body = world.request("GET", "/api/issue?ref=example%2Frepo%2312", headers=world.cookie)
    assert status == 200
    data = json.loads(body)
    assert data["boards"][0]["review_state"] == "In Review"
    assert issue_calls(world)[-1][-2:] == ["plan", "example/repo#12"]
    status, _, _ = world.request("GET", "/api/issue?ref=not-a-ref", headers=world.cookie)
    assert status == 400
    world.runner.handlers["issue_transition.plan"] = lambda argv: failed({"ok": False, "error": "github", "detail": "no network"})
    status, _, body = world.request("GET", "/api/issue?ref=example%2Frepo%2312", headers=world.cookie)
    assert status != 200 and "no network" in body.decode("utf-8")


def test_issue_review_runs_the_script_with_the_text_and_says_where_the_issue_stands(world):
    world.runner.handlers["issue_transition.review"] = lambda argv: ok(
        {"ok": True, "boards": [{"slug": "ops", "from": "In Progress", "to": "In Review", "now": "In Review"}], "closed": False})
    res = world.act("issue_review", key=KEY, text="Deployed and verified")
    call = issue_calls(world)[-1]
    assert call[call.index("--root") + 1] == str(world.root)
    assert call[-3:] == ["review", "example/repo#12", "--text=Deployed and verified"]
    assert res["ok"] and "In Review" in res["note"]
    assert KEY not in world.app.store.dismissed(), "in review it stays in the list"


def test_issue_done_closes_on_github_and_takes_the_row_out_at_once(world):
    world.runner.handlers["issue_transition.done"] = lambda argv: ok(
        {"ok": True, "boards": [{"slug": "ops", "from": "In Review", "to": "Done", "now": "Done"}], "closed": True})
    res = world.act("issue_done", key=KEY)
    assert issue_calls(world)[-1][-2:] == ["done", "example/repo#12"], "no --text without one"
    assert res["ok"] and res["settled"] == [KEY]
    assert world.app.store.dismissed()[KEY]["outcome"] == "done"


def test_a_refusal_of_the_script_is_a_bad_note_and_changes_nothing_here(world):
    world.runner.handlers["issue_transition.done"] = lambda argv: failed(
        {"ok": False, "error": "no_board", "detail": "the issue is on no board of workflow/projects/"})
    res = world.act("issue_done", key=KEY, text="x")
    assert res["ok"] is False and "no board" in res["note"]
    assert KEY not in world.app.store.dismissed()


def test_only_a_github_issue_row_moves_on_a_board(world):
    with pytest.raises(ActionError):
        world.act("issue_done", key="task:other-task")
    assert issue_calls(world) == []


def test_review_needs_its_reason_on_the_server_too(world):
    with pytest.raises(ActionError):
        world.act("issue_review", key=KEY)
    assert issue_calls(world) == []


def test_a_reason_starting_with_a_dash_goes_as_one_argument(world):
    world.runner.handlers["issue_transition.review"] = lambda argv: ok({"ok": True, "boards": [], "closed": False})
    world.act("issue_review", key=KEY, text="-fixed")
    assert issue_calls(world)[-1][-1] == "--text=-fixed"


def test_a_run_that_stopped_part_way_says_so(world):
    world.runner.handlers["issue_transition.done"] = lambda argv: failed({"ok": False, "error": "partial", "detail": "timeout"})
    res = world.act("issue_done", key=KEY)
    assert res["ok"] is False and res["note"] == world.app.actions.tx["issue_partial"].format(title="Fix the example issue", err="timeout")


def test_one_issue_moves_once_at_a_time(world):
    from lib.bridge_cockpit import actions_work
    actions_work._ISSUES_MOVING.add("example/repo#12")
    try:
        with pytest.raises(ActionError) as caught:
            world.act("issue_done", key=KEY)
        assert caught.value.code == "issue_busy"
    finally:
        actions_work._ISSUES_MOVING.discard("example/repo#12")
    assert issue_calls(world) == []
