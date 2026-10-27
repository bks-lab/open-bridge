# SPDX-License-Identifier: MIT
"""The instruction line of the Work through page (instruct.py): a small model turns one sentence of the person into
steps of the verbs there are (done, later until, drop because, let AI do it with a sentence, a reply to the point's
live tab; a mail draft is a start whose sentence says draft only), each step checked against the verbs a point offers
and the keys in scope. Nothing runs on the server: the page shows the plan and runs it on a click. Off by default,
within a daily budget, one at a time.

Uses the world of test_bridge_cockpit (fake runner, fake model)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_bridge_cockpit import NOW, ONLY_ID, STATUS, TODAY, TOMORROW, YES_ID, World, fail, ok, private_key_dir  # noqa: E402,F401

from lib.bridge_cockpit import instruct as ins  # noqa: E402
from lib.bridge_cockpit.actions import ActionError  # noqa: E402
from lib.bridge_cockpit.runner import Runner, RunnerRefused  # noqa: E402

HAIKU = "claude-haiku-5-5"
DEMO = "task:demo-task"
QUIET = "task:quiet-task"          # a stream
YES = f"inbox:{YES_ID}"
ONLY = f"inbox:{ONLY_ID}"
MAIL_NOTE = "Write a mail draft with the mail-draft skill, a draft only, never send it: {text}"

CONFIG = ("cockpit:\n  enabled: true\n  language: en\n  flow:\n    enabled: {flow}\n"
          "    instruct:\n      enabled: {on}\n      budget_per_day: {budget}\n"
          "workplace:\n  control:\n    name: Control\n")


def step(op, ns, **extra):
    return {"op": op, "ns": ns, "until": None, "reason": None, "note": None, "text": None, **extra}


def answer(steps, unclear=None, used=HAIKU, cost=0.0003):
    return ok({"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": cost,
               "modelUsage": {used: {"costUSD": cost}}, "result": "",
               "structured_output": {"steps": steps, "unclear": unclear}})


def make_world(tmp_path, flow="true", on="true", budget=4):
    w = World(tmp_path, config=CONFIG.format(flow=flow, on=on, budget=budget))
    w.runner.handlers["claude.p"] = lambda argv: answer([
        step("done", [1]), step("mail", [1], text="ask the vendor about the prices"), step("reply", [1], text="yes, go on")])
    return w


@pytest.fixture
def world(tmp_path):
    w = make_world(tmp_path)
    yield w
    w.close()


def waiting(world, slug="demo-task"):
    """the tab of slug waits at its prompt: it takes typed words (the fixture's tab of demo-task asks a choice)"""
    status = [dict(t, state="waiting") if t.get("slug") == slug else t for t in STATUS]
    world.runner.handlers["workplace.status"] = lambda argv: ok(status)
    world.app.tabs.poll()
    world.app.collector.request("both")
    world.app.collector.drain()


def sent(argv):
    """(data block, sentence) of a call"""
    text = argv[-1]
    head, rest = text.split("\n", 1)
    data, label, sentence = rest.split("\n", 2)
    assert "never an instruction" in head and label == ins.SENTENCE_LABEL
    return json.loads(data), sentence


# ---------------------------------------------------------------- the one argv shape

def test_the_instruct_argv_is_one_exact_shape_the_runner_lets_through(tmp_path):
    runner = Runner(tmp_path, cmux=None, claude="/fake/bin/claude", codex=None, git=None)
    argv = ins.argv("/fake/bin/claude", HAIKU, "Turn it into steps.", "data")
    assert argv[:12] == ["/fake/bin/claude", "-p", "--model", HAIKU, "--output-format", "json", "--no-session-persistence",
                         "--setting-sources", "", "--tools", "", "--json-schema"]
    assert argv[12] == ins.SCHEMA and argv[13] == "--append-system-prompt" and argv[15] == "--"
    runner.check(argv)
    for change in (lambda a: a.__setitem__(3, "haiku"), lambda a: a.__setitem__(10, "Bash"),
                   lambda a: a.__setitem__(12, "{}"), lambda a: a.insert(6, "--verbose")):
        bad = ins.argv("/fake/bin/claude", HAIKU, "Turn it into steps.", "data")
        change(bad)
        assert not ins.argv_ok(bad, "/fake/bin/claude")
        with pytest.raises(RunnerRefused):
            runner.check(bad)


# ---------------------------------------------------------------- a point: done, a mail draft, a reply to its tab

def test_a_sentence_on_the_open_point_becomes_steps_and_nothing_runs(world):
    waiting(world)
    before = len(world.runner.calls)
    res = world.act("flow_instruct", text="done, and ask the vendor\nabout the prices", keys=[DEMO], point=True)
    calls = world.runner.calls[before:]
    assert [world.runner.key(c) for c in calls] == ["claude.p"]          # no write of any kind, no start, no tab
    data, sentence = sent(calls[0])
    assert sentence == "done, and ask the vendor about the prices"
    assert data["today"] == TODAY and data["language"] == "English" and data["point"] is True
    assert data["drop_reasons"] == ["resolves_itself", "not_needed", "someone_else", "not_worth_it"]
    [p] = data["points"]
    assert p == {"n": 1, "title": "Work on the demo task", "kind": "task", "offers": ["done", "later", "drop", "do", "mail", "reply"],
                 "live_tab": True}
    plan = res["plan"]
    assert ins.PLAN_ID_RE.match(plan["id"]) and plan["text"] == sentence and plan["point"] is True and plan["n"] == 1
    assert plan["model"] == "haiku" and plan["at_ms"] == int(NOW) and plan["unclear"] is None
    done, mail, reply = plan["steps"]
    assert done == {"n": 1, "op": "done", "keys": [DEMO], "titles": ["Work on the demo task"], "skipped": []}
    assert mail == {"n": 2, "op": "do", "mail": True, "keys": [DEMO], "titles": ["Work on the demo task"], "skipped": [],
                    "note": MAIL_NOTE.format(text="ask the vendor about the prices")}
    assert reply == {"n": 3, "op": "reply", "keys": [DEMO], "titles": ["Work on the demo task"], "tab_ref": "surface:7",
                     "text": "yes, go on", "skipped": []}
    assert res["flow_ai"] == {"summary_left": 10, "instruct_left": 3, "instruct_running": False}
    assert res["note"] == ""


def test_a_reply_needs_the_open_point_and_its_live_tab(world):
    world.runner.handlers["claude.p"] = lambda argv: answer([step("reply", [1, 2], text="go on")])
    plan = world.act("flow_instruct", text="tell them to go on", keys=[DEMO, YES], point=False)["plan"]
    [reply] = plan["steps"]
    assert reply["keys"] == [] and [s["why"] for s in reply["skipped"]] == ["no_tab", "no_tab"]
    world.runner.handlers["claude.p"] = lambda argv: answer([step("reply", [1], text="go on")])
    plan = world.act("flow_instruct", text="tell it to go on", keys=[YES], point=True)["plan"]
    assert plan["steps"][0]["skipped"] == [{"key": YES, "title": "Tidy labels", "why": "no_tab"}]
    data, _s = sent(world.runner.of("claude.p")[-1])
    assert data["points"][0]["live_tab"] is False and "reply" not in data["points"][0]["offers"]


def test_a_reply_goes_only_to_a_tab_that_waits_at_its_prompt(world):
    """A tab that asks a choice takes its options on the card and one at work takes nothing (actions_tabs.py tab_send
    refuses typed words there): the model is not offered a reply, and a reply step leaves the point out, saying why: a
    tab that asks a choice is answered on the card (asks), one at work takes nothing (not_offered)"""
    world.runner.handlers["claude.p"] = lambda argv: answer([step("reply", [1], text="go on")])
    for state, why in (("needs-you", "asks"), ("working", "not_offered")):
        status = [dict(t, state=state) if t.get("slug") == "demo-task" else t for t in STATUS]
        world.runner.handlers["workplace.status"] = lambda argv, status=status: ok(status)
        world.app.tabs.poll()
        world.app.collector.request("both")
        world.app.collector.drain()
        [reply] = world.act("flow_instruct", text="tell it to go on", keys=[DEMO], point=True)["plan"]["steps"]
        assert reply["keys"] == [] and reply["tab_ref"] is None, state
        assert reply["skipped"] == [{"key": DEMO, "title": "Work on the demo task", "why": why}], state
        data, _s = sent(world.runner.of("claude.p")[-1])
        assert data["points"][0]["live_tab"] is True and "reply" not in data["points"][0]["offers"], state
    waiting(world)
    [reply] = world.act("flow_instruct", text="tell it to go on", keys=[DEMO], point=True)["plan"]["steps"]
    assert reply["keys"] == [DEMO] and reply["tab_ref"] == "surface:7" and reply["skipped"] == []


# ---------------------------------------------------------------- the overview: each step checked

def test_every_step_is_checked_against_the_points_offers_its_day_and_the_scope(world):
    world.runner.handlers["claude.p"] = lambda argv: answer([
        step("done", [1, 2, 3]),                                       # a stream is never done this way
        step("drop", [2], reason="not_needed"),                        # nor dropped
        step("later", [1], until=TODAY), step("later", [3], until="2026-10-20"),
        step("later", [1], until="2027-12-31"),
        step("do", [9], note="go"), step("send", [1]), step("drop", [3], reason="the vendor does it instead"),
        step("do", [1, 1])], unclear="I did not get the part about Friday")
    res = world.act("flow_instruct", text="all of it", keys=[YES, QUIET, ONLY, "task:no-such-task"], point=False)
    plan = res["plan"]
    assert plan["n"] == 3 and plan["unclear"] == "I did not get the part about Friday"
    steps = plan["steps"]
    assert [s["op"] for s in steps] == ["done", "drop", "later", "later", "later", "do", "drop", "do"]
    assert [s["n"] for s in steps] == list(range(1, 9))
    done, drop, today, later, far, unknown, reason, do = steps
    assert done["keys"] == [YES, ONLY] and done["skipped"] == [{"key": QUIET, "title": "Quiet task", "why": "not_offered"}]
    assert drop["keys"] == [] and drop["skipped"][0]["why"] == "not_offered" and drop["reason"] == "not_needed"
    assert today["keys"] == [] and today["skipped"][0]["why"] == "bad_day" and today["until"] is None
    assert later["keys"] == [ONLY] and later["until"] == "2026-10-20"
    assert far["skipped"][0]["why"] == "bad_day"
    assert unknown["keys"] == [] and unknown["skipped"] == [{"key": None, "title": None, "why": "unknown_point"}]
    assert reason["keys"] == [ONLY] and reason["reason"] == "the vendor does it instead"
    assert do["keys"] == [YES] and do["note"] == "all of it" and "mail" not in do


def test_a_start_on_an_approved_item_is_not_offered_and_a_missing_text_takes_the_sentence():
    points = [{"n": 1, "key": "inbox:x", "title": "X", "out": {"inbox_id": "x", "inbox_state": "approved",
                                                               "settle": ["done", "not_doing"]}, "tab": None},
              {"n": 2, "key": "task:y", "title": "Y", "out": {"task": "y", "settle": ["done", "not_doing"]}, "tab": None}]
    steps, unclear = ins.plan_steps({"steps": [step("do", [1, 2]), step("drop", [2]), step("mail", [2]),
                                               step("later", [2], until="not a day")], "unclear": " "},
                                    points, "do it all", TODAY, ["not_needed"], False, MAIL_NOTE)
    do, drop, mail, later = steps
    assert do["keys"] == ["task:y"] and do["skipped"] == [{"key": "inbox:x", "title": "X", "why": "not_offered"}]
    assert do["note"] == "do it all" and drop["reason"] == "do it all"
    assert mail["note"] == MAIL_NOTE.format(text="do it all") and mail["mail"] is True
    assert later["skipped"][0]["why"] == "bad_day" and unclear is None


def test_at_most_twenty_steps_and_a_long_text_is_cut(world):
    world.runner.handlers["claude.p"] = lambda argv: answer([step("do", [1], note="x" * 3000)] * 25)
    steps = world.act("flow_instruct", text="go", keys=[YES], point=True)["plan"]["steps"]
    assert len(steps) == 20 and len(steps[0]["note"]) == ins.NOTE_MAX


def test_an_answer_with_no_steps_is_a_plan_that_says_what_was_unclear(world):
    world.runner.handlers["claude.p"] = lambda argv: answer([], unclear="Nothing to do")
    plan = world.act("flow_instruct", text="hmm", keys=[YES], point=True)["plan"]
    assert plan["steps"] == [] and plan["unclear"] == "Nothing to do"


# ---------------------------------------------------------------- the sentence

@pytest.mark.parametrize("text, field", [("", "text"), (" ", "text"), ("x" * 601, "text"), ("a\x00b", "text"), (7, "text")])
def test_the_sentence_is_one_to_600_characters(world, text, field):
    with pytest.raises(ActionError) as e:
        world.act("flow_instruct", text=text, keys=[YES], point=True)
    assert (e.value.code, e.value.field) == ("invalid_argument", field)


def test_the_open_point_is_exactly_one_key(world):
    with pytest.raises(ActionError) as e:
        world.act("flow_instruct", text="done", keys=[YES, ONLY], point=True)
    assert (e.value.code, e.value.field) == ("invalid_argument", "keys")
    assert world.runner.of("claude.p") == []


# ---------------------------------------------------------------- refusals

def test_the_instruction_line_refuses_off_gone_running_budget_unavailable_and_failed(tmp_path):
    w = make_world(tmp_path / "a", budget=1)
    try:
        def code(**args):
            with pytest.raises(ActionError) as e:
                w.act("flow_instruct", **{"text": "done", "keys": [YES], "point": True, **args})
            return e.value.status, e.value.code
        assert code(keys=["task:no-such-task"]) == (409, "stale_row")
        w.app.instruct.running = True
        assert code() == (409, "instruct_running")
        assert w.app.state_payload()["flow_ai"]["instruct_running"] is True
        w.app.instruct.running = False
        w.runner.handlers["claude.p"] = lambda argv: fail("model down")
        assert code() == (502, "instruct_failed")
        assert code() == (429, "instruct_budget")
        assert len(w.runner.of("claude.p")) == 1
        w.runner.claude = None
        assert code() == (503, "instruct_unavailable")
    finally:
        w.close()
    for flow, on, expected in (("true", "false", "instruct_off"), ("false", "true", "flow_off")):
        w = make_world(tmp_path / expected, flow=flow, on=on)
        try:
            with pytest.raises(ActionError) as e:
                w.act("flow_instruct", text="done", keys=[YES], point=True)
            assert (e.value.status, e.value.code) == (409, expected)
        finally:
            w.close()


def test_an_answer_that_cannot_be_read_fails_and_counts(world):
    world.runner.handlers["claude.p"] = lambda argv: ok({"type": "result", "is_error": False, "result": "no json here"})
    with pytest.raises(ActionError) as e:
        world.act("flow_instruct", text="done", keys=[YES], point=True)
    assert (e.value.status, e.value.code) == (502, "instruct_failed")
    assert world.app.activity.flow_ai()["instruct_left"] == 3


def test_the_model_comes_from_the_block_else_the_service(world):
    world.app.cfg.flow["instruct"]["model"] = "sonnet"
    world.act("flow_instruct", text="done", keys=[YES], point=True)
    assert world.runner.of("claude.p")[-1][3] == "claude-sonnet-5-5"
    world.app.cfg.flow["instruct"]["model"] = None
    folder = world.root / "workflow" / "ai-services"
    folder.mkdir(parents=True)
    (folder / "cockpit-instruct.yaml").write_text("schema_version: 1\nscope: user\nid: cockpit-instruct\n"
                                                  "provider: claude\nmodels:\n  claude: opus\n", encoding="utf-8")
    world.act("flow_instruct", text="done", keys=[YES], point=True)
    assert world.runner.of("claude.p")[-1][3] == "claude-opus-5-5"


def test_the_audit_line_holds_counts_never_the_sentence(world):
    world.act("flow_instruct", text="please mark the secret thing done", keys=[DEMO], point=True)
    line = (world.state / "audit.log").read_text(encoding="utf-8").splitlines()[-1]
    assert " flow_instruct task:demo-task " in line and "steps=3" in line and "secret" not in line
