# SPDX-License-Identifier: MIT
"""Describe (describe.py): Haiku writes and keeps each item's brief (goal, story, acceptance) in its STATUS.md or
inbox item while no person changed it, proposes once one did, within an hourly budget, one call at a time.

Uses the world of test_bridge_cockpit (fake runner); the model is never called, task.py and inbox.py run for
real against the temp Bridge."""
from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_bridge_cockpit import YES_ID, World, ok, private_key_dir  # noqa: E402,F401  (the autouse fixture comes along)

from lib.bridge_cockpit import describe as dsc  # noqa: E402
from lib.bridge_cockpit.actions import ActionError  # noqa: E402
from lib.bridge_cockpit.card_fields import brief_basis  # noqa: E402
from lib.bridge_cockpit.config import load_web_config  # noqa: E402
from lib.bridge_cockpit.runner import Runner, RunnerRefused, RunResult  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
HAIKU = "claude-haiku-5-5"
GOAL = "Ship the demo so the team can try it on Friday"
CRITERIA = ["The demo opens without an error", "Two colleagues tried it and said so"]


def answer(goal=GOAL, acceptance=CRITERIA, story=None, used=HAIKU, cost=0.0021, structured=True):
    brief = {"goal": goal, "acceptance": acceptance, "story": story}
    out = {"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": cost,
           "modelUsage": {used: {"costUSD": cost}} if used else {}}
    if structured:
        out.update(result="", structured_output=brief)
    else:
        out["result"] = "Here it is:\n" + json.dumps(brief)
    return ok(out)


CONFIG = ("cockpit:\n  enabled: true\n  language: en\n  describe:\n    auto: {auto}\n    budget_per_hour: {budget}\n"
          "workplace:\n  control:\n    name: Control\n")


def real(argv):
    """task.py and inbox.py of this checkout, run for real against the temp Bridge"""
    argv = [argv[0], str(ROOT / "scripts" / Path(argv[1]).name), *argv[2:]]
    done = subprocess.run(argv, capture_output=True, text=True)
    return RunResult(done.returncode == 0, done.returncode, done.stdout, done.stderr, 1)


def make_world(tmp_path, auto="off", budget=20):
    w = World(tmp_path, config=CONFIG.format(auto=auto, budget=budget))
    w.runner.handlers["task.brief"] = real
    w.runner.handlers["inbox.describe"] = real
    w.runner.handlers["claude.p"] = lambda argv: answer()
    return w


@pytest.fixture
def world(tmp_path):
    w = make_world(tmp_path)
    yield w
    w.close()


def status_path(world, slug="demo-task", kind="tasks"):
    return world.app.root / "work" / kind / slug / "STATUS.md"


def brief_of(world, slug="demo-task", kind="tasks"):
    text = status_path(world, slug, kind).read_text(encoding="utf-8")
    return yaml.safe_load(text.split("---\n", 2)[1]).get("brief")


def add_task(world, slug, body="Some work.\n", kind="tasks", extra=""):
    d = world.app.root / "work" / kind / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "STATUS.md").write_text(f"---\nstatus: doing\nheadline: {slug} work\n{extra}---\n\n# {slug.title()}\n\n{body}",
                                 encoding="utf-8")


def model_calls(world):
    return world.runner.of("claude.p")


def calls_for(world, title="Demo task"):
    """the model calls about one item: its title is in the data the call carries"""
    return [c for c in model_calls(world) if title in c[-1]]


# ---------------------------------------------------------------- the one argv shape

def describe_argv(claude="/fake/bin/claude", model=HAIKU, system="Write a brief.", text="data", effort="medium"):
    return dsc.argv(claude, model, system, text, effort)


def test_the_describe_argv_is_one_exact_shape_the_runner_lets_through(tmp_path):
    runner = Runner(tmp_path, cmux=None, claude="/fake/bin/claude", codex=None)
    argv = describe_argv()
    assert argv[:14] == ["/fake/bin/claude", "-p", "--model", HAIKU, "--effort", "medium", "--output-format", "json",
                         "--no-session-persistence", "--setting-sources", "", "--tools", "", "--json-schema"]
    assert argv[14] == dsc.SCHEMA and argv[15] == "--append-system-prompt" and argv[17] == "--" and argv[18] == "data"
    runner.check(argv)
    for effort in dsc.EFFORTS:
        runner.check(describe_argv(effort=effort))


@pytest.mark.parametrize("change", [
    lambda a: a.__setitem__(3, "haiku"),                       # an alias, never a full id
    lambda a: a.__setitem__(5, "max"),                          # an effort describe does not take
    lambda a: a.__setitem__(5, "xhigh"),
    lambda a: a[4:6].__len__() and a.__delitem__(slice(4, 6)),  # no effort at all
    lambda a: a.__setitem__(12, "Read"),                        # a tool
    lambda a: a.__setitem__(14, '{"type": "object"}'),          # another schema
    lambda a: a.__setitem__(10, "user"),                        # settings
    lambda a: a.insert(8, "--verbose"),                         # anything more
    lambda a: a.__setitem__(18, "x" * (dsc.PROMPT_MAX + 1)),    # past the prompt limit
    lambda a: a.__setitem__(16, ""),                            # no instruction
    lambda a: a.__setitem__(0, "/other/claude"),                # another program
])
def test_any_other_describe_argv_is_refused(tmp_path, change):
    runner = Runner(tmp_path, cmux=None, claude="/fake/bin/claude", codex=None)
    argv = describe_argv()
    change(argv)
    with pytest.raises(RunnerRefused):
        runner.check(argv)


def test_no_call_adds_to_the_env_any_more_the_model_may_think(tmp_path):
    """describe asked for no thinking through MAX_THINKING_TOKENS=0 once; now the model may think, at the effort
    cockpit.describe.effort names, and no call of the runner adds anything to its clean env"""
    import inspect
    assert "env_extra" not in inspect.signature(Runner.run).parameters
    assert not hasattr(dsc, "ENV")
    runner = Runner(tmp_path, cmux=None, claude="/fake/bin/claude", codex=None)
    assert "MAX_THINKING_TOKENS" not in runner.env()


# ---------------------------------------------------------------- reading the answer

ITEM = {"key": "task:demo", "kind": "task", "id": "demo", "title": "Demo task", "basis": "0123456789abcdef"}


def test_the_answer_becomes_a_brief_through_the_gate_with_the_model_that_answered():
    got = dsc.parse(answer().out, ITEM, HAIKU, "2026-10-25")
    assert got["brief"] == {"goal": GOAL, "acceptance": CRITERIA, "by": HAIKU, "at": "2026-10-25",
                            "basis": "0123456789abcdef", "edited": False}
    assert got["cost_usd"] == 0.0021 and got["model_mismatch"] is False and got["used"] == HAIKU


def test_an_answer_in_the_result_text_is_read_too():
    story = {"as": "a colleague", "want": "to try the demo", "so_that": "I can give feedback"}
    got = dsc.parse(answer(structured=False, story=story).out, ITEM, HAIKU, "2026-10-25")
    assert got["brief"]["goal"] == GOAL and got["brief"]["story"] == story


def test_more_than_five_criteria_are_clipped_to_five():
    eight = [f"Outcome number {n} can be seen" for n in range(8)]
    got = dsc.parse(answer(acceptance=eight).out, ITEM, HAIKU, "2026-10-25")
    assert got["brief"]["acceptance"] == eight[:5] and any("kept the first 5" in e for e in got["errors"])


def test_a_stream_keeps_no_criteria():
    got = dsc.parse(answer().out, {**ITEM, "kind": "stream"}, HAIKU, "2026-10-25")
    assert got["brief"]["acceptance"] == []


def test_another_model_than_asked_is_flagged_and_stored_as_it_answered():
    got = dsc.parse(answer(used="claude-sonnet-5-5").out, ITEM, HAIKU, "2026-10-25")
    assert got["model_mismatch"] is True and got["brief"]["by"] == "claude-sonnet-5-5"


@pytest.mark.parametrize("goal", ["Demo task", "demo TASK", "Ship it \u2014 now", "x" * 141, ""])
def test_a_goal_that_repeats_the_title_or_fails_the_gate_gives_no_brief(goal):
    got = dsc.parse(answer(goal=goal).out, ITEM, HAIKU, "2026-10-25")
    assert got["brief"] is None and got["errors"]


@pytest.mark.parametrize("out", ["", "not json", json.dumps({"type": "result", "is_error": True, "result": "x"})])
def test_an_unreadable_answer_gives_no_brief(out):
    got = dsc.parse(out, ITEM, HAIKU, "2026-10-25")
    assert got["brief"] is None


# ---------------------------------------------------------------- what the model sees

def test_the_input_is_capped_scrubbed_and_marked_as_data(world):
    path = status_path(world)
    text = path.read_text(encoding="utf-8").replace("## Goal", "## Older\n\nold part\n\n## Goal")
    text = text.replace("headline: Demo task\n", "headline: Demo task\nblocked_by: SECRET-TOKEN\n")
    text += "\n## Latest\n\nthe newest words\n"
    path.write_text(text, encoding="utf-8")
    world.app.scrub = lambda s: s.replace("SECRET-TOKEN", "[token]")
    item = world.app.describe.item("task:demo-task")
    assert item["basis"] == brief_basis(text) and item["kind"] == "task" and item["title"] == "Demo task"
    data = json.loads(item["data"])
    assert len(item["data"]) <= dsc.DATA_MAX
    assert data["front"]["status"] == "doing" and data["front"]["blocked_by"] == "[token]"
    assert data["heading"] == "Demo task" and "Ship the demo." in data["body_start"]
    assert [s.split("\n", 1)[0] for s in data["recent_sections"]] == ["## Notes", "## Latest"]
    system, prompt = dsc.prompt(item, "German")
    assert "German" in system and "data" in prompt.split("\n", 1)[0].lower()
    assert "SECRET-TOKEN" not in prompt and len(system) <= dsc.SYSTEM_MAX


def test_the_open_inbox_of_a_task_goes_along(world):
    item_dir = world.app.root / "work" / "inbox" / YES_ID
    y = (item_dir / "item.yaml").read_text(encoding="utf-8") + "task: demo-task\n"
    (item_dir / "item.yaml").write_text(y, encoding="utf-8")
    data = json.loads(world.app.describe.item("task:demo-task", full=True)["data"])
    assert data["open_inbox"] == ["decision: Tidy labels"]
    # the basis never depends on them: a card's stale flag reads the item without
    assert world.app.describe.item("task:demo-task")["basis"] == world.app.describe.item("task:demo-task", full=True)["basis"]


# ---------------------------------------------------------------- the button: describe_run

def test_describe_run_writes_the_brief_into_status_md(world):
    before = status_path(world).read_text(encoding="utf-8")
    res = world.act("describe_run", key="task:demo-task")
    assert res["ok"] and res["describe"]["written"] == "ai" and res["describe"]["stale"] is False
    b = brief_of(world)
    assert b["goal"] == GOAL and b["by"] == HAIKU and b["edited"] is False and b["acceptance"] == CRITERIA
    after = status_path(world).read_text(encoding="utf-8")
    assert b["basis"] == brief_basis(after) == brief_basis(before)
    [argv] = model_calls(world)
    assert argv[3] == HAIKU and argv[4:6] == ["--effort", "medium"]
    state = json.loads((world.app.root / ".bridge" / "describe.json").read_text(encoding="utf-8"))
    entry = state["items"]["task:demo-task"]
    assert entry["sha"] == dsc.brief_sha(b) and entry["cost_usd"] == 0.0021 and entry["by"] == HAIKU


def test_the_model_comes_from_the_ai_service_file(world):
    folder = world.app.root / "workflow" / "ai-services"
    folder.mkdir(parents=True)
    (folder / "cockpit-describe.yaml").write_text("schema_version: 1\nscope: user\nid: cockpit-describe\n"
                                                  "provider: claude\nmodels:\n  claude: sonnet\n", encoding="utf-8")
    world.runner.handlers["claude.p"] = lambda argv: answer(used="claude-sonnet-5-5")
    world.act("describe_run", key="task:demo-task")
    assert model_calls(world)[0][3] == "claude-sonnet-5-5"


def test_a_mismatch_is_said_and_the_real_model_stored(world):
    world.runner.handlers["claude.p"] = lambda argv: answer(used="claude-sonnet-5-5")
    res = world.act("describe_run", key="task:demo-task")
    assert brief_of(world)["by"] == "claude-sonnet-5-5" and res["describe"]["model_mismatch"] is True


def test_an_edited_brief_is_never_overwritten_the_run_proposes(world):
    world.act("describe_run", key="task:demo-task")
    path = status_path(world)
    mine = path.read_text(encoding="utf-8").replace(GOAL, "The goal Michael wrote").replace("edited: false", "edited: true")
    path.write_text(mine, encoding="utf-8")
    world.runner.handlers["claude.p"] = lambda argv: answer(goal="A newer goal from the model")
    res = world.act("describe_run", key="task:demo-task")
    assert path.read_text(encoding="utf-8") == mine
    prop = res["describe"]["proposal"]
    assert prop["brief"]["goal"] == "A newer goal from the model" and dsc.PROPOSAL_RE.match(prop["id"])
    assert res["describe"]["written"] == "human"


def test_describe_apply_writes_the_proposal_as_a_human_choice(world):
    world.act("describe_run", key="task:demo-task")
    path = status_path(world)
    path.write_text(path.read_text(encoding="utf-8").replace("edited: false", "edited: true"), encoding="utf-8")
    world.runner.handlers["claude.p"] = lambda argv: answer(goal="A newer goal from the model")
    pid = world.act("describe_run", key="task:demo-task")["describe"]["proposal"]["id"]
    res = world.act("describe_apply", key="task:demo-task", proposal=pid)
    b = brief_of(world)
    assert b["goal"] == "A newer goal from the model" and b["edited"] is True and b["by"] == HAIKU
    assert res["describe"]["proposal"] is None and res["describe"]["written"] == "human"
    with pytest.raises(ActionError) as gone:
        world.act("describe_apply", key="task:demo-task", proposal=pid)
    assert gone.value.code == "stale_proposal"


def test_describe_apply_takes_the_persons_own_text(world):
    world.act("describe_run", key="task:demo-task")
    path = status_path(world)
    path.write_text(path.read_text(encoding="utf-8").replace("edited: false", "edited: true"), encoding="utf-8")
    pid = world.act("describe_run", key="task:demo-task")["describe"]["proposal"]["id"]
    own = {"goal": "My own goal for the demo", "acceptance": ["It runs on my laptop"]}
    world.act("describe_apply", key="task:demo-task", proposal=pid, brief=own)
    b = brief_of(world)
    assert b["goal"] == "My own goal for the demo" and b["acceptance"] == ["It runs on my laptop"] and b["edited"] is True


@pytest.mark.parametrize("bad", [{"goal": "x" * 141}, {"goal": "One \u2013 two"}, {"acceptance": ["a"]}, "text",
                                 {"goal": "ok", "extra": 1}])
def test_describe_apply_refuses_a_brief_the_gate_refuses(world, bad):
    with pytest.raises(ActionError) as refused:
        world.act("describe_apply", key="task:demo-task", proposal="d0123456789", brief=bad)
    assert refused.value.code == "invalid_argument" and refused.value.field == "brief"


def test_describe_discard_drops_the_proposal_and_it_is_not_made_again_for_that_text(tmp_path):
    w = make_world(tmp_path, auto="stale")
    try:
        w.act("describe_run", key="task:demo-task")
        path = status_path(w)
        path.write_text(path.read_text(encoding="utf-8").replace("edited: false", "edited: true") + "\nmore\n",
                        encoding="utf-8")
        pid = w.act("describe_run", key="task:demo-task")["describe"]["proposal"]["id"]
        res = w.act("describe_discard", key="task:demo-task", proposal=pid)
        assert res["describe"]["proposal"] is None
        n = len(calls_for(w))
        w.app.describe.pass_once()
        assert len(calls_for(w)) == n               # discarded for this basis: no new proposal
    finally:
        w.close()


def test_describe_run_for_an_inbox_item_writes_a_describe_event(world):
    res = world.act("describe_run", key=f"inbox:{YES_ID}")
    assert res["ok"] and res["describe"]["written"] == "ai"
    events = sorted((world.app.root / "work" / "inbox" / YES_ID / "events").glob("*-describe.yaml"))
    assert len(events) == 1
    ev = yaml.safe_load(events[-1].read_text(encoding="utf-8"))
    assert ev["brief"]["goal"] == GOAL and ev["brief"]["by"] == HAIKU and ev["brief"]["edited"] is False


def test_an_unknown_or_closed_key_is_stale_row(world):
    for key in ("task:nope", "inbox:20991231-0000-nope", "ref:x"):
        with pytest.raises(ActionError) as gone:
            world.act("describe_run", key=key)
        assert gone.value.code in ("stale_row", "not_applicable")
    assert model_calls(world) == []


def test_a_failed_call_is_kept_as_the_last_error_and_nothing_written(world):
    world.runner.handlers["claude.p"] = lambda argv: RunResult(False, 1, "", "boom", 1)
    with pytest.raises(ActionError) as failed:
        world.act("describe_run", key="task:demo-task")
    assert failed.value.code == "describe_failed"
    assert brief_of(world) is None and world.app.describe.state_for("task:demo-task")["last_error"]


def test_two_runs_never_go_at_once(world):
    gate, seen = threading.Event(), {}

    def slow(argv):
        gate.wait(3)
        return answer()

    world.runner.handlers["claude.p"] = slow
    t = threading.Thread(target=lambda: seen.update(first=world.act("describe_run", key="task:demo-task")))
    t.start()
    for _ in range(200):
        if world.app.describe.state_for("task:demo-task")["running"]:
            break
        threading.Event().wait(0.01)
    with pytest.raises(ActionError) as busy:
        world.app.describe.run_key(f"inbox:{YES_ID}", why="auto")
    assert busy.value.code == "describe_running"
    gate.set()
    t.join(5)
    assert seen["first"]["ok"]


# ---------------------------------------------------------------- a hand edit outside the cockpit

def test_a_hand_edit_is_found_and_marked_without_a_model_call(tmp_path):
    w = make_world(tmp_path, auto="stale")
    try:
        w.act("describe_run", key="task:demo-task")
        path = status_path(w)
        text = path.read_text(encoding="utf-8").replace(GOAL, "Michael changed this goal")
        path.write_text(text, encoding="utf-8")
        n = len(calls_for(w))
        w.app.describe.pass_once()
        assert path.read_text(encoding="utf-8") == text.replace("edited: false", "edited: true")
        assert len(calls_for(w)) == n
        assert w.app.describe.state_for("task:demo-task")["written"] == "human"
    finally:
        w.close()


def test_an_untouched_ai_brief_counts_as_ai(world):
    world.act("describe_run", key="task:demo-task")
    assert world.app.describe.state_for("task:demo-task")["written"] == "ai"
    assert world.app.describe.state_for("task:demo-task")["stale"] is False


# ---------------------------------------------------------------- stale and the pass by itself

def test_a_brief_goes_stale_when_the_text_changes(world):
    world.act("describe_run", key="task:demo-task")
    path = status_path(world)
    path.write_text(path.read_text(encoding="utf-8") + "\n## New\n\nnew work\n", encoding="utf-8")
    assert world.app.describe.state_for("task:demo-task")["stale"] is True


def test_auto_off_makes_no_call(world):
    assert world.app.cfg.describe["auto"] == "off"
    assert world.app.describe.pass_once() == 0 and model_calls(world) == []


def test_auto_missing_writes_only_what_has_no_brief(tmp_path):
    w = make_world(tmp_path, auto="missing")
    try:
        add_task(w, "second")
        w.app.describe.pass_once()
        assert brief_of(w)["goal"] == GOAL and brief_of(w, "second")["goal"] == GOAL
        calls = len(model_calls(w))
        assert calls == 3            # two tasks and the inbox item
        path = status_path(w)
        path.write_text(path.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")
        w.app.describe.pass_once()
        assert len(model_calls(w)) == calls     # stale, but auto: missing leaves it
    finally:
        w.close()


def test_auto_stale_writes_a_stale_brief_again(tmp_path):
    w = make_world(tmp_path, auto="stale")
    try:
        w.app.describe.pass_once()
        path = status_path(w)
        path.write_text(path.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")
        w.runner.handlers["claude.p"] = lambda argv: answer(goal="The demo is shipped and tried")
        n = len(model_calls(w))
        w.app.describe.pass_once()
        assert len(model_calls(w)) == n + 1 and brief_of(w)["goal"] == "The demo is shipped and tried"
        assert w.app.describe.state_for("task:demo-task")["stale"] is False
    finally:
        w.close()


def test_kinds_limit_what_the_pass_takes(tmp_path):
    w = World(tmp_path, config=("cockpit:\n  enabled: true\n  language: en\n  describe:\n    auto: missing\n"
                                "    kinds: [inbox]\nworkplace:\n  control:\n    name: Control\n"))
    try:
        w.runner.handlers.update({"task.brief": real, "inbox.describe": real, "claude.p": lambda argv: answer()})
        w.app.describe.pass_once()
        assert len(model_calls(w)) == 1 and brief_of(w) is None
    finally:
        w.close()


def test_an_edited_item_gets_a_proposal_at_most_once_per_basis(tmp_path):
    w = make_world(tmp_path, auto="stale")
    try:
        w.act("describe_run", key="task:demo-task")
        path = status_path(w)
        path.write_text(path.read_text(encoding="utf-8").replace("edited: false", "edited: true") + "\nmore\n",
                        encoding="utf-8")
        mine = path.read_text(encoding="utf-8")
        n = len(calls_for(w))
        w.app.describe.pass_once()
        w.app.describe.pass_once()
        assert len(calls_for(w)) == n + 1
        assert path.read_text(encoding="utf-8") == mine
        assert w.app.describe.state_for("task:demo-task")["proposal"]["brief"]["goal"] == GOAL
    finally:
        w.close()


def test_the_hourly_budget_holds_the_pass(tmp_path):
    w = make_world(tmp_path, auto="missing", budget=2)
    try:
        for n in range(3):
            add_task(w, f"more-{n}")
        w.app.describe.pass_once()
        assert len(model_calls(w)) == 2
        w.app.describe.pass_once()
        assert len(model_calls(w)) == 2           # the hour is not over
        w.clock.advance(3601)
        w.app.describe.pass_once()
        assert len(model_calls(w)) == 4
        assert w.app.describe.budget_left() == 0
    finally:
        w.close()


def test_a_failed_text_is_not_asked_again_by_the_pass_until_it_changes(tmp_path):
    w = make_world(tmp_path, auto="missing")
    try:
        w.runner.handlers["claude.p"] = lambda argv: answer(goal="Demo task")     # repeats the title
        w.app.describe.pass_once()
        n = len(model_calls(w))
        w.app.describe.pass_once()
        assert len(model_calls(w)) == n
    finally:
        w.close()


def test_a_status_md_without_a_closed_frontmatter_costs_no_call(tmp_path):
    w = make_world(tmp_path, auto="missing")
    try:
        d = w.app.root / "work" / "tasks" / "broken"
        d.mkdir(parents=True)
        (d / "STATUS.md").write_text("# yaml-language-server: x\n---\n\n# Broken\n\nNo fields.\n", encoding="utf-8")
        with pytest.raises(ActionError) as refused:
            w.act("describe_run", key="task:broken")
        assert refused.value.code == "describe_no_front" and calls_for(w, "Broken") == []
        w.app.describe.pass_once()
        assert calls_for(w, "Broken") == [] and w.app.describe.state_for("task:broken")["last_error"]
    finally:
        w.close()


def test_a_failed_write_is_not_tried_again_by_the_pass_until_the_text_changes(tmp_path):
    w = make_world(tmp_path, auto="missing")
    try:
        w.runner.handlers["task.brief"] = lambda argv: RunResult(False, 1, "", "task: disk full", 1)
        w.app.describe.pass_once()
        n = len(calls_for(w))
        assert n == 1 and w.app.describe.state_for("task:demo-task")["last_error"] == "task: disk full"
        w.app.describe.pass_once()
        assert len(calls_for(w)) == n
    finally:
        w.close()


def test_the_pass_starts_only_when_auto_is_on(world, tmp_path):
    assert world.app.describe.start_auto() is False
    w = make_world(tmp_path / "on", auto="missing")
    try:
        assert w.app.describe.start_auto() is True
        assert any(t.name == "bridge-cockpit-describe" for t in threading.enumerate())
    finally:
        w.close()


# ---------------------------------------------------------------- config

def test_describe_config_defaults_to_off(tmp_path):
    cfg = load_web_config(tmp_path, {"cockpit": {}})
    assert cfg.describe == {"auto": "off", "budget_per_hour": 20, "kinds": ["task", "stream", "inbox"], "effort": "medium"}
    assert cfg.config_warnings == ()


def test_describe_config_takes_its_keys_and_warns_on_bad_values(tmp_path):
    cfg = load_web_config(tmp_path, {"cockpit": {"describe": {"auto": "stale", "budget_per_hour": 5, "kinds": ["task"],
                                                              "effort": "high"}}})
    assert cfg.describe == {"auto": "stale", "budget_per_hour": 5, "kinds": ["task"], "effort": "high"}
    assert cfg.config_warnings == ()
    bad = load_web_config(tmp_path, {"cockpit": {"describe": {"auto": "always", "budget_per_hour": -1,
                                                              "kinds": ["task", "github"], "speed": 1, "effort": "max"}}})
    assert bad.describe == {"auto": "off", "budget_per_hour": 20, "kinds": ["task"], "effort": "medium"}
    text = " | ".join(bad.config_warnings)
    for part in ("cockpit.describe.auto", "cockpit.describe.budget_per_hour", "cockpit.describe.kinds",
                 "cockpit.describe.speed: unknown key", "cockpit.describe.effort"):
        assert part in text
    assert load_web_config(tmp_path, {"cockpit": {"describe": "on"}}).config_warnings
    # a bare `auto: off` in YAML is false: still off, without a warning
    plain = load_web_config(tmp_path, yaml.safe_load("cockpit:\n  describe:\n    auto: off\n"))
    assert plain.describe["auto"] == "off" and plain.config_warnings == ()


def test_the_ai_services_template_lists_the_cockpit_services():
    text = (ROOT / "workflow" / "ai-services" / "_template.yaml").read_text(encoding="utf-8")
    assert "cockpit-describe" in text and "cockpit-organize" in text


def test_the_docs_name_the_describe_keys():
    text = (ROOT / "docs" / "bridge-cockpit.md").read_text(encoding="utf-8")
    assert "`describe`" in text and "budget_per_hour" in text and "auto: missing" in text and "effort" in text


def test_the_configured_effort_reaches_the_call(tmp_path):
    w = World(tmp_path, config=("cockpit:\n  enabled: true\n  language: en\n  describe:\n    effort: low\n"
                                "workplace:\n  control:\n    name: Control\n"))
    try:
        w.runner.handlers.update({"task.brief": real, "inbox.describe": real, "claude.p": lambda argv: answer()})
        w.act("describe_run", key="task:demo-task")
        [argv] = model_calls(w)
        assert argv[4:6] == ["--effort", "low"]
    finally:
        w.close()


# ---------------------------------------------------------------- review fixes

def test_the_schema_carries_the_limits_so_the_model_is_held_to_them():
    schema = json.loads(dsc.SCHEMA)
    props = schema["properties"]
    assert props["goal"]["maxLength"] == dsc.BRIEF_LIMITS["goal"]
    assert props["acceptance"]["items"]["maxLength"] == dsc.BRIEF_LIMITS["acceptance_len"]
    story = props["story"]["anyOf"][0]["properties"]
    assert {k: v["maxLength"] for k, v in story.items()} == {k: dsc.BRIEF_LIMITS["story"] for k in ("as", "want", "so_that")}


def test_a_task_with_fewer_than_two_criteria_is_said():
    got = dsc.parse(answer(acceptance=["The demo opens without an error"]).out, ITEM, HAIKU, "2026-10-25")
    assert got["brief"]["acceptance"] == ["The demo opens without an error"]
    assert any("at least 2" in e for e in got["errors"])
    stream = dsc.parse(answer(acceptance=[]).out, {**ITEM, "kind": "stream"}, HAIKU, "2026-10-25")
    assert not any("at least 2" in e for e in stream["errors"])


def test_what_the_gate_left_out_of_a_written_brief_is_kept_as_a_warning(world):
    story = {"as": "a colleague", "want": "w" * 90, "so_that": "I can give feedback"}
    world.runner.handlers["claude.p"] = lambda argv: answer(story=story)
    res = world.act("describe_run", key="task:demo-task")
    assert res["ok"] and "story" not in brief_of(world)
    state = world.app.describe.state_for("task:demo-task")
    assert state["last_error"] is None and any("story.want" in w for w in state["warnings"])
    world.runner.handlers["claude.p"] = lambda argv: answer()
    path = status_path(world)
    path.write_text(path.read_text(encoding="utf-8") + "\nmore\n", encoding="utf-8")
    world.act("describe_run", key="task:demo-task")
    assert world.app.describe.state_for("task:demo-task")["warnings"] == []


def test_the_title_is_scrubbed_like_the_data(world):
    path = status_path(world)
    path.write_text(path.read_text(encoding="utf-8").replace("# Demo task", "# Demo SECRET-TOKEN"), encoding="utf-8")
    world.app.scrub = lambda s: s.replace("SECRET-TOKEN", "[token]")
    item = world.app.describe.item("task:demo-task", full=True)
    assert item["title"] == "Demo [token]"
    res = world.act("describe_run", key="task:demo-task")
    assert "SECRET-TOKEN" not in json.dumps(res)


def test_an_unavailable_model_stops_the_pass_and_counts_no_call(tmp_path):
    w = make_world(tmp_path, auto="missing")
    try:
        add_task(w, "second")
        folder = w.app.root / "workflow" / "ai-services"
        folder.mkdir(parents=True)
        (folder / "cockpit-describe.yaml").write_text("schema_version: 1\nscope: user\nid: cockpit-describe\n"
                                                      "provider: openai\nmodels:\n  openai: gpt-5\n", encoding="utf-8")
        asked = []
        real_item = w.app.describe.item
        w.app.describe.item = lambda key, full=False: (asked.append((key, full)), real_item(key, full))[1]
        assert w.app.describe.pass_once() == 0 and model_calls(w) == []
        assert len([k for k, full in asked if full]) == 1, "the pass stops at the first item it cannot describe"
    finally:
        w.close()


def test_the_docs_say_what_the_local_hashes_do_not_promise_and_no_longer_switch_thinking_off():
    text = (ROOT / "docs" / "bridge-cockpit.md").read_text(encoding="utf-8")
    assert "per machine" in text and "per machine" in (dsc.__doc__ or "")
    assert "MAX_THINKING_TOKENS" not in text and "MAX_THINKING_TOKENS" not in (dsc.__doc__ or "")


# ---------------------------------------------------------------- what reaches the page (server.describe_items)

def rebuilt_row(world, key="task:demo-task"):
    """the row as the page gets it after the next pass, the task list read for real (it carries the brief)"""
    world.runner.handlers["workplace.tasks"] = real
    world.app.collector.refresh_tasks()
    world.app.collector.request("both")
    world.app.collector.drain()
    return world.row(key)


def test_a_written_brief_reaches_the_row_card_with_who_wrote_it(world):
    world.act("describe_run", key="task:demo-task")
    out = rebuilt_row(world)
    assert out["card"]["goal"] == GOAL and out["card"]["acceptance"] == CRITERIA and out["card"]["written"] == "ai"
    assert out["describe"]["written"] == "ai" and out["describe"]["stale"] is False and out["describe"]["proposal"] is None
    # what the page's AI mark says on hover: the model and the day it wrote the brief
    assert out["describe"]["by"] == HAIKU and out["describe"]["at"] == world.app.describe.today()


def test_a_stale_brief_says_so_on_the_row(world):
    world.act("describe_run", key="task:demo-task")
    path = status_path(world)
    path.write_text(path.read_text(encoding="utf-8") + "\n## New\n\nnew work\n", encoding="utf-8")
    assert rebuilt_row(world)["describe"]["stale"] is True


def test_a_proposal_reaches_the_row_and_the_task_detail(world):
    world.act("describe_run", key="task:demo-task")
    path = status_path(world)
    path.write_text(path.read_text(encoding="utf-8").replace("edited: false", "edited: true"), encoding="utf-8")
    world.runner.handlers["claude.p"] = lambda argv: answer(goal="A newer goal from the model")
    pid = world.act("describe_run", key="task:demo-task")["describe"]["proposal"]["id"]
    out = rebuilt_row(world)
    assert out["describe"]["proposal"]["id"] == pid and out["describe"]["written"] == "human"
    assert out["card"]["goal"] == GOAL and out["card"]["written"] == "human"
    detail = json.loads(world.request("GET", "/api/task?slug=demo-task", headers=world.cookie)[2])
    assert detail["describe"]["proposal"]["brief"]["goal"] == "A newer goal from the model"
    assert detail["card"]["written"] == "human"


def test_an_inbox_item_carries_its_describe_state_on_the_row_and_the_detail(world):
    world.act("describe_run", key=f"inbox:{YES_ID}")
    out = rebuilt_row(world, f"inbox:{YES_ID}")
    assert out["card"]["goal"] == GOAL and out["describe"]["written"] == "ai"
    detail = json.loads(world.request("GET", f"/api/inbox?id={YES_ID}", headers=world.cookie)[2])
    assert detail["describe"]["written"] == "ai" and detail["card"]["goal"] == GOAL


def test_describe_items_names_only_what_has_something_to_say(world):
    assert world.app.describe_items() == {}
    assert rebuilt_row(world)["describe"] is None
    world.act("describe_run", key="task:demo-task")
    items = world.app.describe_items()
    assert set(items) == {"task:demo-task"} and items["task:demo-task"] == world.app.describe.state_for("task:demo-task")


def test_a_damaged_describe_store_never_stops_the_page(world):
    (world.app.root / ".bridge").mkdir(exist_ok=True)
    (world.app.root / ".bridge" / "describe.json").write_text("{not json", encoding="utf-8")
    assert world.app.describe_items() == {}
    assert rebuilt_row(world)["card"]["kind"] == "task"


def test_a_detail_reads_only_its_own_describe_view(world, monkeypatch):
    world.act("describe_run", key="task:demo-task")
    asked = []
    real_state = world.app.describe.state_for
    monkeypatch.setattr(world.app.describe, "state_for", lambda key: asked.append(key) or real_state(key))
    detail = json.loads(world.request("GET", "/api/task?slug=demo-task", headers=world.cookie)[2])
    assert detail["describe"]["written"] == "ai" and detail["card"]["goal"] == GOAL
    assert asked == ["task:demo-task"]
    # an item describe never touched carries no describe view, as on the rows
    world.request("GET", f"/api/inbox?id={YES_ID}", headers=world.cookie)
    assert json.loads(world.request("GET", f"/api/inbox?id={YES_ID}", headers=world.cookie)[2])["describe"] is None


def test_the_model_build_reads_an_inbox_item_again_only_once_it_changed(world, monkeypatch):
    world.act("describe_run", key=f"inbox:{YES_ID}")
    reads = []
    make = world.app.describe._inbox

    def counting():
        inbox = make()
        get = inbox.get
        inbox.get = lambda iid: reads.append(iid) or get(iid)
        return inbox
    monkeypatch.setattr(world.app.describe, "_inbox", counting)
    first = world.app.describe.views()
    assert first[f"inbox:{YES_ID}"]["written"] == "ai"
    reads.clear()
    assert world.app.describe.views() == first and reads == []
    # a new event (here: a seen note) changes the item, so the next build reads it again
    events = world.app.root / "work" / "inbox" / YES_ID / "events"
    (events / "9999-seen.yaml").write_text("verb: seen\nby: web\nat: '2026-10-25T10:00:00'\n", encoding="utf-8")
    world.app.describe.views()
    assert reads == [YES_ID]


# ---------------------------------------------------------------- references a reader can reach (brief_refs.py)

BOUND = "sync:\n  bridge_only: false\n  github:\n    repo: acme/app\n    issues: [95]\n"
EPIC = "All gaps are tracked in epic #95 and listed in work/tasks/epic-work/gaps.md.\n"
EPIC_TITLE = "Epic-Work"


def add_epic(world):
    add_task(world, "epic-work", body=EPIC, extra=BOUND)
    (status_path(world, "epic-work").parent / "gaps.md").write_text("# Gaps\n", encoding="utf-8")


def test_the_prompt_carries_the_references_a_reader_can_reach_as_data(world):
    add_epic(world)
    item = world.app.describe.item("task:epic-work", full=True)
    data = json.loads(item["data"])
    assert "acme/app#95" in data["references"] and "work/tasks/epic-work/gaps.md" in data["references"]
    assert "#95" not in [x for x in data["references"] if not x.startswith("acme/")]
    system, text = dsc.prompt(item, "English")
    assert '"references":' in text.split("\n", 1)[1], "the list goes in as data, inside the JSON block"
    assert "bare #" in system and "references" in system and "on its own" in system
    assert len(system) <= dsc.SYSTEM_MAX


def test_a_reference_the_scrub_changes_is_never_offered(world):
    add_task(world, "secret-link", body="See https://example.org/x?token=SECRET-TOKEN and https://example.org/ok.\n")
    world.app.scrub = lambda s: s.replace("SECRET-TOKEN", "[token]")
    data = json.loads(world.app.describe.item("task:secret-link", full=True)["data"])
    assert data["references"] == ["https://example.org/ok"]


def test_a_brief_with_an_unresolved_reference_is_written_with_a_warning_and_retried_once(tmp_path):
    w = make_world(tmp_path, auto="stale")
    try:
        add_epic(w)
        w.runner.handlers["claude.p"] = lambda argv: answer(
            acceptance=["All gaps of epic #95 are closed", "The open points of the report (Bericht §6) are answered"])
        w.act("describe_run", key="task:epic-work")
        assert brief_of(w, "epic-work")["acceptance"][1].endswith("(Bericht §6) are answered"), "it is written all the same"
        state = w.app.describe.state_for("task:epic-work")
        assert any("§6" in x for x in state["warnings"]) and not any("#95" in x for x in state["warnings"])
        assert state["stale"] is True and state["stale_why"] == "refs"
        n = len(calls_for(w, EPIC_TITLE))
        w.app.describe.pass_once()
        assert len(calls_for(w, EPIC_TITLE)) == n + 1, "the pass tries once more for this text"
        w.app.describe.pass_once()
        assert len(calls_for(w, EPIC_TITLE)) == n + 1, "and then leaves it: no loop"
        state = w.app.describe.state_for("task:epic-work")
        assert state["stale"] is False and any("§6" in x for x in state["warnings"])
    finally:
        w.close()


def test_a_resolved_reference_reaches_the_card_as_a_link_and_an_unresolved_one_as_a_gap(world):
    add_epic(world)
    world.runner.handlers["claude.p"] = lambda argv: answer(
        goal="Every gap of work/tasks/epic-work/gaps.md is closed",
        acceptance=["All gaps of epic #95 are closed", "Bericht §6 is answered"])
    world.act("describe_run", key="task:epic-work")
    card = rebuilt_row(world, "task:epic-work")["card"]
    refs = card["brief_refs"]
    assert {"text": "work/tasks/epic-work/gaps.md", "ref": {"kind": "file", "path": "work/tasks/epic-work/gaps.md"}} in refs["goal"]
    assert {"text": "acme/app#95", "ref": {"kind": "web", "href": "https://github.com/acme/app/issues/95"}} in refs["acceptance"][0]
    assert {"text": "§6", "unresolved": True} in refs["acceptance"][1]
    assert "unresolved_ref" in card["gaps"]


def store_items(world):
    path = world.app.root / ".bridge" / "describe.json"
    return path, json.loads(path.read_text(encoding="utf-8"))


def test_an_ai_brief_from_an_older_prompt_is_stale_and_rewritten_an_edited_one_never(tmp_path):
    w = make_world(tmp_path, auto="stale")
    try:
        w.act("describe_run", key="task:demo-task")
        path, data = store_items(w)
        assert data["items"]["task:demo-task"]["prompt_version"] == dsc.PROMPT_VERSION
        assert w.app.describe.state_for("task:demo-task")["stale"] is False
        # written before prompts had a version: an older prompt
        del data["items"]["task:demo-task"]["prompt_version"]
        path.write_text(json.dumps(data), encoding="utf-8")
        state = w.app.describe.state_for("task:demo-task")
        assert state["stale"] is True and state["stale_why"] == "prompt"
        w.runner.handlers["claude.p"] = lambda argv: answer(goal="The demo is shipped and tried")
        n = len(calls_for(w))
        w.app.describe.pass_once()
        assert len(calls_for(w)) == n + 1 and brief_of(w)["goal"] == "The demo is shipped and tried"
        assert w.app.describe.state_for("task:demo-task")["stale"] is False
        # a person's brief from an older prompt stays as it is: not stale, no call, no proposal
        status = status_path(w)
        status.write_text(status.read_text(encoding="utf-8").replace("edited: false", "edited: true"), encoding="utf-8")
        mine = status.read_text(encoding="utf-8")
        path, data = store_items(w)
        data["items"]["task:demo-task"]["prompt_version"] = dsc.PROMPT_VERSION - 1
        path.write_text(json.dumps(data), encoding="utf-8")
        assert w.app.describe.state_for("task:demo-task")["stale"] is False
        n = len(calls_for(w))
        w.app.describe.pass_once()
        assert len(calls_for(w)) == n and status.read_text(encoding="utf-8") == mine
        assert w.app.describe.state_for("task:demo-task")["proposal"] is None
    finally:
        w.close()
