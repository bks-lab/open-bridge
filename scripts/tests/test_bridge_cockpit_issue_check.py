# SPDX-License-Identifier: MIT
"""Check with AI on an issue card (issue_check.py): on a click, the issue's GitHub detail goes to a small model as data,
a fixed schema answers done, not_done or unclear with the evidence and a review comment, unclear asks the stronger
model once. The answer is kept per issue and comes back with GET /api/issue; nothing on the board is written."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_bridge_cockpit import World, ok, private_key_dir  # noqa: E402,F401  (the autouse fixture comes along)

from lib.bridge_cockpit import issue_check as ic  # noqa: E402
from lib.bridge_cockpit.actions import ActionError  # noqa: E402
from lib.bridge_cockpit.runner import RunResult  # noqa: E402

KEY = "ref:example/repo#12"
DETAIL = {"ok": True, "ref": "example/repo#12", "type": "issue", "title": "Fix the example issue", "state": "open",
          "updated": "2026-10-28T10:00:00Z", "body": "- [x] parser fixed\n- [x] test added", "body_cut": False,
          "assignees": ["someone"], "labels": [],
          "comments": {"total": 1, "items": [{"author": "someone", "at": "2026-10-28T10:00:00Z", "body": "Merged in #13."}]},
          "boards": [{"title": "Ops", "number": 7, "status": "In Progress"}],
          "prs": [{"number": 13, "state": "merged", "title": "Fix the parser", "draft": False}]}


def answer(verdict="done", used="claude-haiku-5-5", cost=0.004, **over) -> RunResult:
    body = {"verdict": verdict, "reason": "Both boxes are ticked and #13 is merged.", "evidence": ["#13 merged"],
            "missing": [] if verdict == "done" else ["a test on CI"], "comment": "Parser fixed in #13, test added.", **over}
    return ok({"type": "result", "is_error": False, "structured_output": body, "total_cost_usd": cost,
               "modelUsage": {used: {"costUSD": cost}}})


@pytest.fixture
def world(tmp_path):
    w = World(tmp_path)
    w.runner.handlers["briefing.detail"] = lambda argv: ok(DETAIL)
    w.runner.handlers["claude.p"] = lambda argv: answer()
    yield w
    w.close()


def model_calls(w: World) -> list[list[str]]:
    return w.runner.of("claude.p")


def test_the_call_has_one_shape_no_tools_no_settings_this_schema_and_the_runner_lets_only_it_through(world):
    argv = ic.argv(world.app.runner.claude, "claude-haiku-5-5", "rules", "data")
    assert ic.argv_ok(argv, world.app.runner.claude)
    assert argv[argv.index("--tools") + 1] == "" and argv[argv.index("--setting-sources") + 1] == ""
    assert json.loads(argv[argv.index("--json-schema") + 1])["properties"]["verdict"]["enum"] == ["done", "not_done", "unclear"]
    world.app.runner.check(argv)
    bad = list(argv)
    bad[bad.index("--tools") + 1] = "Bash"
    assert not ic.argv_ok(bad, world.app.runner.claude)


def test_the_issue_goes_in_as_data_with_its_body_comments_prs_and_boards():
    system, text = ic.prompt(DETAIL, "German")
    assert "German" in system and "never an instruction" in text
    data = json.loads(text.split("\n", 1)[1])
    assert data["prs"][0]["state"] == "merged" and data["boards"][0]["status"] == "In Progress"
    assert data["comments"][0]["body"] == "Merged in #13."


def test_check_reads_the_detail_fresh_asks_the_small_model_and_keeps_the_answer(world):
    res = world.act("issue_check", key=KEY)
    assert res["ok"]
    detail = world.runner.of("briefing.detail")[-1]
    assert detail[-2:] == ["example/repo#12", "--fresh"]
    calls = model_calls(world)
    assert len(calls) == 1 and calls[0][calls[0].index("--model") + 1] == "claude-haiku-5-5"
    got = res["issue_check"]
    assert got["verdict"] == "done" and got["comment"].startswith("Parser fixed") and got["model"] == "claude-haiku-5-5"
    assert ic.kept(world.app.state_dir, "example/repo#12", DETAIL["updated"])["verdict"] == "done"
    assert "done" in res["note"].lower() or "fertig" in res["note"].lower()


def test_unclear_asks_the_stronger_model_once(world):
    answers = iter([answer("unclear"), answer("not_done", used="claude-sonnet-5-5")])
    world.runner.handlers["claude.p"] = lambda argv: next(answers)
    got = world.act("issue_check", key=KEY)["issue_check"]
    models = [c[c.index("--model") + 1] for c in model_calls(world)]
    assert models == ["claude-haiku-5-5", "claude-sonnet-5-5"]
    assert got["verdict"] == "not_done" and got["missing"] == ["a test on CI"]


def test_get_issue_carries_the_kept_check(world):
    world.act("issue_check", key=KEY)
    world.runner.handlers["issue_transition.plan"] = lambda argv: ok({"ok": True, "ref": "example/repo#12", "boards": [], "unmatched": [],
                                                                     "updated": DETAIL["updated"]})
    status, _, body = world.request("GET", "/api/issue?ref=example%2Frepo%2312", headers=world.cookie)
    assert status == 200 and json.loads(body)["check"]["verdict"] == "done"


def test_an_answer_without_a_verdict_is_an_error_and_nothing_is_kept(world):
    world.runner.handlers["claude.p"] = lambda argv: ok({"type": "result", "is_error": False, "result": "no idea"})
    with pytest.raises(ActionError):
        world.act("issue_check", key=KEY)
    assert ic.kept(world.app.state_dir, "example/repo#12", DETAIL["updated"]) is None


def test_only_a_github_issue_is_checked_and_nothing_is_written_to_github(world):
    with pytest.raises(ActionError):
        world.act("issue_check", key="task:other-task")
    world.act("issue_check", key=KEY)
    assert not any(len(c) > 1 and c[1].endswith("issue_transition.py") for c in world.runner.calls)


def test_a_detail_github_could_not_refresh_is_not_judged(world):
    world.runner.handlers["briefing.detail"] = lambda argv: ok({**DETAIL, "stale": "no network"})
    with pytest.raises(ActionError):
        world.act("issue_check", key=KEY)
    assert not model_calls(world)


def test_a_kept_check_ends_when_the_issue_changes(world):
    world.act("issue_check", key=KEY)
    plan = {"ok": True, "ref": "example/repo#12", "boards": [], "unmatched": [], "updated": "2026-10-29T08:00:00Z"}
    world.runner.handlers["issue_transition.plan"] = lambda argv: ok(plan)
    _, _, body = world.request("GET", "/api/issue?ref=example%2Frepo%2312", headers=world.cookie)
    assert json.loads(body)["check"] is None


@pytest.mark.parametrize("over", [{"prs": []}, {"prs": [{"number": 13, "state": "open", "title": "x", "draft": False}]},
                                  {"body_cut": True}])
def test_done_on_an_open_issue_needs_a_merged_pull_request_and_the_whole_body(world, over):
    world.runner.handlers["briefing.detail"] = lambda argv: ok({**DETAIL, **over})
    got = world.act("issue_check", key=KEY)["issue_check"]
    assert got["verdict"] == "unclear" and got["missing"]
    assert len(model_calls(world)) == 1


def test_done_on_a_closed_issue_stands_without_a_pull_request(world):
    world.runner.handlers["briefing.detail"] = lambda argv: ok({**DETAIL, "state": "closed", "prs": []})
    assert world.act("issue_check", key=KEY)["issue_check"]["verdict"] == "done"


def test_the_rules_say_the_data_never_instructs_and_the_model_learns_what_was_cut():
    system, text = ic.prompt({**DETAIL, "body_cut": True, "comments": {"total": 9, "items": DETAIL["comments"]["items"]}}, "German")
    assert "never follow" in system.lower()
    data = json.loads(text.split("\n", 1)[1])
    assert data["body_cut"] is True and data["comments_total"] == 9


def test_a_small_model_that_failed_does_not_buy_the_stronger_one(world):
    world.runner.handlers["claude.p"] = lambda argv: ok({"type": "result", "is_error": True, "result": "overloaded"})
    with pytest.raises(ActionError):
        world.act("issue_check", key=KEY)
    assert len(model_calls(world)) == 1


def test_the_kept_answers_sit_in_the_state_folder_for_the_owner_alone(world):
    world.act("issue_check", key=KEY)
    path = world.app.state_dir / "issue-check.json"
    assert path.stat().st_mode & 0o777 == 0o600
