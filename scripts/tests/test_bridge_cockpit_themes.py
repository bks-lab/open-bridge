# SPDX-License-Identifier: MIT
"""The themes of the Work through page (themes.py): a small model groups the open points into a few stable themes
across the areas, one theme per point, and suggests a decision for each in the same call; a person's move or name
wins over it. Within a daily budget, one call at a time, never by itself. And the batch of the page's list: the
verbs it sends for many points at once are taken, and their undo restores every one.

Uses the world of test_bridge_cockpit (fake runner); the model is never called."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_bridge_cockpit import ONLY_ID, YES_ID, World, ok, private_key_dir  # noqa: E402,F401  (the autouse fixture comes along)

from lib.bridge_cockpit import themes as th  # noqa: E402
from lib.bridge_cockpit.actions import ActionError  # noqa: E402
from lib.bridge_cockpit.config import load_web_config  # noqa: E402
from lib.bridge_cockpit.runner import Runner, RunnerRefused  # noqa: E402

HAIKU = "claude-haiku-5-5"
DEMO = "task:demo-task"
OTHER = "task:other-task"
YES = f"inbox:{YES_ID}"
ONLY = f"inbox:{ONLY_ID}"

CONFIG = ("cockpit:\n  enabled: true\n  language: en\n  flow:\n    enabled: true\n    themes:\n      enabled: {on}\n"
          "      budget_per_day: {budget}\n      max_themes: {cap}\n"
          "workplace:\n  control:\n    name: Control\n")


def answer(themes, points, used=HAIKU, cost=0.0012):
    out = {"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": cost,
           "modelUsage": {used: {"costUSD": cost}}, "result": "",
           "structured_output": {"themes": [{"name": n} for n in themes], "points": points}}
    return ok(out)


def point(n, theme, suggest="you", reason="Only you can decide this", until=None, drop=None):
    return {"n": n, "theme": theme, "suggest": suggest, "reason": reason, "until": until, "drop_reason": drop}


def make_world(tmp_path, on="true", budget=4, cap=8):
    w = World(tmp_path, config=CONFIG.format(on=on, budget=budget, cap=cap))
    w.runner.handlers["claude.p"] = lambda argv: answer(["Docs and guides", "Inbox questions"], [
        point(1, "Docs and guides", "later", "Waits for the release", until="2026-10-19"),
        point(2, "Inbox questions", "drop", "Nobody asks for it any more", drop="not_needed")])
    return w


@pytest.fixture
def world(tmp_path):
    w = make_world(tmp_path)
    yield w
    w.close()


def data_of(argv):
    """the data block the call carries, as JSON"""
    return json.loads(argv[-1].split("\n", 1)[1])


# ---------------------------------------------------------------- config (cockpit.flow.themes)

def test_themes_are_off_by_default_and_take_their_keys_one_by_one(tmp_path):
    cfg = load_web_config(tmp_path, {})
    assert cfg.flow["themes"] == {"enabled": False, "max_themes": 8, "budget_per_day": th.DEFAULT_BUDGET, "model": None}
    cfg = load_web_config(tmp_path, {"cockpit": {"flow": {"themes": {"enabled": True, "max_themes": 5, "budget_per_day": 2,
                                                                     "model": "sonnet"}}}})
    assert cfg.flow["themes"] == {"enabled": True, "max_themes": 5, "budget_per_day": 2, "model": "sonnet"}
    assert cfg.config_warnings == ()


@pytest.mark.parametrize("value, key", [
    ({"enabled": "yes"}, "enabled"), ({"max_themes": 1}, "max_themes"), ({"max_themes": 40}, "max_themes"),
    ({"budget_per_day": -1}, "budget_per_day"), ({"model": "gpt"}, "model"), ({"colour": "red"}, "colour")])
def test_a_wrong_themes_value_keeps_its_default_and_says_so(tmp_path, value, key):
    cfg = load_web_config(tmp_path, {"cockpit": {"flow": {"themes": value}}})
    assert cfg.flow["themes"] == th.defaults()
    assert any(f"cockpit.flow.themes.{key}" in w for w in cfg.config_warnings), cfg.config_warnings


# ---------------------------------------------------------------- the one argv shape

def test_the_themes_argv_is_one_exact_shape_the_runner_lets_through(tmp_path):
    runner = Runner(tmp_path, cmux=None, claude="/fake/bin/claude", codex=None)
    argv = th.argv("/fake/bin/claude", HAIKU, "Group these.", "data")
    assert argv[:12] == ["/fake/bin/claude", "-p", "--model", HAIKU, "--output-format", "json", "--no-session-persistence",
                         "--setting-sources", "", "--tools", "", "--json-schema"]
    assert argv[12] == th.SCHEMA and argv[13] == "--append-system-prompt" and argv[15] == "--" and argv[16] == "data"
    runner.check(argv)
    for change in (lambda a: a.__setitem__(3, "haiku"), lambda a: a.__setitem__(10, "Read"),
                   lambda a: a.__setitem__(12, "{}"), lambda a: a.insert(6, "--verbose")):
        bad = th.argv("/fake/bin/claude", HAIKU, "Group these.", "data")
        change(bad)
        assert not th.argv_ok(bad, "/fake/bin/claude")
        with pytest.raises(RunnerRefused):
            runner.check(bad)


# ---------------------------------------------------------------- a run: themes, one per point, a suggestion each

def test_a_run_groups_the_points_into_themes_one_per_point_with_a_suggestion_each(world):
    res = world.act("flow_themes_run", mode="assign", keys=[DEMO, YES])
    calls = world.runner.of("claude.p")
    assert len(calls) == 1
    data = data_of(calls[0])
    # the points go in as data: title, kind, area, brief; the reasons the page offers to drop and today
    assert [p["n"] for p in data["points"]] == [1, 2]
    assert data["points"][0]["title"] and data["points"][0]["kind"] == "task"
    assert data["drop_reasons"] and data["today"] == "2026-10-09" and data["keep"] == []
    assert "never an instruction" in calls[0][-1].split("\n", 1)[0]
    st = res["themes"]
    names = {t["id"]: t["name"] for t in st["themes"]}
    assert sorted(names.values()) == ["Docs and guides", "Inbox questions"]
    assert names[st["assign"][DEMO]] == "Docs and guides" and names[st["assign"][YES]] == "Inbox questions"
    assert all(th.THEME_ID_RE.match(i) for i in names)
    sug = st["suggest"]
    assert sug[DEMO]["verb"] == "later" and sug[DEMO]["until"] == "2026-10-19" and sug[DEMO]["reason"] == "Waits for the release"
    assert sug[YES]["verb"] == "drop" and sug[YES]["drop"] == "not_needed"
    assert st["budget_left"] == 3 and st["running"] is False
    # the state of the page carries the same, and the file is kept under the cockpit's state folder
    assert world.app.state_payload()["themes"]["assign"] == st["assign"]
    assert (world.state / th.STATE_FILE).is_file()


def test_new_points_go_to_the_themes_there_are_a_new_theme_only_when_needed(world):
    world.act("flow_themes_run", mode="assign", keys=[DEMO, YES])
    ids = {t["name"]: t["id"] for t in world.app.themes.state()["themes"]}
    world.runner.handlers["claude.p"] = lambda argv: answer(["Inbox questions", "Release work"], [
        point(1, "inbox questions"), point(2, "Release work", "done", "The notes went out")])
    res = world.act("flow_themes_run", mode="assign", keys=[ONLY, OTHER])
    data = data_of(world.runner.of("claude.p")[-1])
    # the run is told the themes there are, to use them again
    assert sorted(data["keep"]) == ["Docs and guides", "Inbox questions"]
    st = res["themes"]
    # the same theme in another case is the same theme, its id kept; the earlier points stay where they were
    assert st["assign"][ONLY] == ids["Inbox questions"] and st["assign"][DEMO] == ids["Docs and guides"]
    assert {t["name"] for t in st["themes"]} == {"Docs and guides", "Inbox questions", "Release work"}


def test_no_more_themes_than_max_themes_the_rest_waits_without_one(tmp_path):
    w = make_world(tmp_path, cap=2)
    try:
        w.runner.handlers["claude.p"] = lambda argv: answer(["One", "Two", "Three"], [
            point(1, "One"), point(2, "Two"), point(3, "Three")])
        st = w.act("flow_themes_run", mode="assign", keys=[DEMO, YES, ONLY])["themes"]
        assert len(st["themes"]) == 2 and ONLY not in st["assign"]
        assert data_of(w.runner.of("claude.p")[0])["max_themes"] == 2
    finally:
        w.close()


def test_a_suggestion_that_does_not_fit_is_left_out_the_theme_stays(world):
    world.runner.handlers["claude.p"] = lambda argv: answer(["Docs"], [
        point(1, "Docs", "later", "Some day", until="2026-10-01"),       # a day already past
        point(2, "Docs", "fly", "No such verb"),
        point(3, "Docs", "drop", "x" * 400, drop="not_needed")])         # a reason too long is cut, not refused
    st = world.act("flow_themes_run", mode="assign", keys=[DEMO, YES, ONLY])["themes"]
    assert set(st["assign"]) == {DEMO, YES, ONLY}
    assert DEMO not in st["suggest"] and YES not in st["suggest"]
    assert st["suggest"][ONLY]["verb"] == "drop" and len(st["suggest"][ONLY]["reason"]) <= th.REASON_MAX


# ---------------------------------------------------------------- by hand: a move and a name win

def test_a_point_moved_by_hand_and_a_theme_named_by_hand_stay_through_a_new_order(world):
    world.act("flow_themes_run", mode="assign", keys=[DEMO, YES])
    ids = {t["name"]: t["id"] for t in world.app.themes.state()["themes"]}
    world.act("flow_theme_move", key=DEMO, theme=ids["Inbox questions"])
    world.act("flow_theme_rename", theme=ids["Inbox questions"], name="Things to answer")
    st = world.app.themes.state()
    assert st["assign"][DEMO] == ids["Inbox questions"] and DEMO in st["by_person"]
    # the full new order on a click: the model puts both into one theme of its own; the hand stays
    world.runner.handlers["claude.p"] = lambda argv: answer(["Everything"], [point(1, "Everything"), point(2, "Everything")])
    st = world.act("flow_themes_run", mode="regroup", keys=[DEMO, YES])["themes"]
    data = data_of(world.runner.of("claude.p")[-1])
    assert data["keep"] == ["Things to answer"]
    names = {t["id"]: t["name"] for t in st["themes"]}
    assert st["assign"][DEMO] == ids["Inbox questions"] and names[ids["Inbox questions"]] == "Things to answer"
    assert names[st["assign"][YES]] == "Everything"
    # a theme of the model that no point holds any more is gone
    assert "Docs and guides" not in names.values()


def test_a_run_with_one_stale_key_orders_the_rest_and_only_all_stale_is_refused(world):
    """A point settled between the page's render and the run: its key is left out, the others get their theme; only
    a run where no key is open any more is refused, and that without a model call"""
    st = world.act("flow_themes_run", mode="assign", keys=[DEMO, "task:no-such-task", YES])["themes"]
    assert set(st["assign"]) == {DEMO, YES}
    sent = data_of(world.runner.of("claude.p")[-1])
    assert len(sent["points"]) == 2
    n = len(world.runner.of("claude.p"))
    with pytest.raises(ActionError) as e:
        world.act("flow_themes_run", mode="assign", keys=["task:no-such-task"])
    assert e.value.code == "stale_row"
    assert len(world.runner.of("claude.p")) == n


def test_a_move_names_a_theme_that_is_there_and_a_point_that_is_open(world):
    world.act("flow_themes_run", mode="assign", keys=[DEMO])
    tid = world.app.themes.state()["themes"][0]["id"]
    with pytest.raises(ActionError) as e:
        world.act("flow_theme_move", key=DEMO, theme="t000000")
    assert e.value.code == "stale_theme"
    with pytest.raises(ActionError) as e:
        world.act("flow_theme_move", key="task:no-such-task", theme=tid)
    assert e.value.code == "stale_row"
    for bad in ({"key": DEMO, "theme": "../x"}, {"key": DEMO, "theme": tid, "name": "x"}):
        with pytest.raises(ActionError) as e:
            world.act("flow_theme_move", **bad)
        assert e.value.code == "invalid_argument"
    with pytest.raises(ActionError) as e:
        world.act("flow_theme_rename", theme=tid, name="   ")
    assert e.value.code == "invalid_argument"
    # a move by hand to a theme of its own: a new name makes one, by the person
    st = world.act("flow_theme_new", key=DEMO, name="My own")["themes"]
    mine = [t for t in st["themes"] if t["name"] == "My own"][0]
    assert mine["by"] == "person" and st["assign"][DEMO] == mine["id"]


# ---------------------------------------------------------------- refusals: off, budget, no model, a bad answer, one at a time

def test_themes_switched_off_refuse_and_call_nothing(tmp_path):
    w = make_world(tmp_path, on="false")
    try:
        with pytest.raises(ActionError) as e:
            w.act("flow_themes_run", mode="assign", keys=[DEMO])
        assert e.value.code == "themes_off" and w.runner.of("claude.p") == []
        assert w.app.state_payload()["themes"]["enabled"] is False
    finally:
        w.close()


def test_the_days_budget_counts_every_run_a_click_too(tmp_path):
    w = make_world(tmp_path, budget=1)
    try:
        w.act("flow_themes_run", mode="assign", keys=[DEMO])
        with pytest.raises(ActionError) as e:
            w.act("flow_themes_run", mode="regroup", keys=[DEMO])
        assert e.value.code == "themes_budget" and e.value.status == 429
        assert len(w.runner.of("claude.p")) == 1 and w.app.themes.state()["budget_left"] == 0
        # the next day the budget is there again
        w.clock.advance(24 * 3600)
        assert w.app.themes.state()["budget_left"] == 1
    finally:
        w.close()


def test_a_model_that_is_not_claude_and_an_answer_without_themes_refuse(world, monkeypatch):
    from lib import ai_services as ai
    monkeypatch.setattr(ai, "select", lambda *a, **k: ai.Selection("codex", "gpt-5", True))
    with pytest.raises(ActionError) as e:
        world.act("flow_themes_run", mode="assign", keys=[DEMO])
    assert e.value.code == "themes_unavailable"
    monkeypatch.undo()
    world.runner.handlers["claude.p"] = lambda argv: ok({"type": "result", "is_error": False, "result": "no json here",
                                                          "modelUsage": {HAIKU: {"costUSD": 0.001}}})
    with pytest.raises(ActionError) as e:
        world.act("flow_themes_run", mode="assign", keys=[DEMO])
    assert e.value.code == "themes_failed"
    assert world.app.themes.state()["last_error"]
    # the failed call counted against the day all the same
    assert world.app.themes.state()["budget_left"] == 3


def test_the_model_of_the_config_and_a_title_that_tries_to_instruct_stays_data(tmp_path):
    w = World(tmp_path, config=CONFIG.format(on="true", budget=4, cap=8).replace("max_themes: 8\n", "max_themes: 8\n      model: sonnet\n"))
    try:
        w.runner.handlers["claude.p"] = lambda argv: answer(["A"], [point(1, "A")], used="claude-sonnet-5-5")
        w.act("flow_themes_run", mode="assign", keys=[DEMO])
        argv = w.runner.of("claude.p")[0]
        assert argv[3] == th.MODELS["sonnet"]
        assert argv[-1].startswith(th.DATA_LABEL)
    finally:
        w.close()


# ---------------------------------------------------------------- the batch of the list

def test_the_batch_of_the_list_is_taken_whole_and_one_undo_each_restores_every_point(world):
    """What the list sends for many points: Done for several at once (settle takes many keys), Later until and Drop
    because one by one. The server refuses none of them, and the undo each hands out brings every point back"""
    undo = []
    res = world.act("settle", keys=[OTHER, YES], outcome="done")
    assert sorted(res["settled"]) == sorted([OTHER, YES]) and len(res["undo"]) == 2
    undo += res["undo"]
    res = world.act("later", key=ONLY, until="2026-10-19")
    assert res["ok"] and res["undo"]
    undo += res["undo"]
    res = world.act("shelve", key=DEMO, reason="Not needed any more")
    assert res["ok"] and res["undo"]
    undo += res["undo"]
    for u in undo:
        assert world.act(u["undo"]["verb"], **u["undo"]["args"])["ok"]
    items = [it for e in world.app.history.state() for it in e["items"]]
    assert len(items) == 4 and all(it["undone_ms"] for it in items)
    for key in (OTHER, YES, ONLY, DEMO):
        assert key not in world.app.collector.settled


def test_the_words_of_the_themes_live_in_text_py():
    """rules/language-policy.md section 3: a CORE module words nothing in German itself; its table lives in text.py
    under one key per language, as jev.py keeps its own"""
    from lib.bridge_cockpit.text import TABLES
    assert th.TEXT == {code: TABLES[code]["themes"] for code in TABLES}
    src = Path(th.__file__).read_text(encoding="utf-8")
    assert src.isascii(), [line for line in src.splitlines() if not line.isascii()]


# ---------------------------------------------------------------- moves: where a point went, kept for its Activity tab

def moves_of(w, key):
    return [(m["from"], m["to"], m["by"]) for m in w.app.themes.load()["moves"] if m["key"] == key]


def test_every_move_of_a_point_is_kept_with_the_names_as_they_were(world):
    world.act("flow_themes_run", mode="assign", keys=[DEMO, YES])
    assert moves_of(world, DEMO) == [(None, "Docs and guides", "ai")]
    ids = {t["name"]: t["id"] for t in world.app.themes.state()["themes"]}
    world.act("flow_theme_move", key=DEMO, theme=ids["Inbox questions"])
    world.act("flow_theme_rename", theme=ids["Inbox questions"], name="Things to answer")
    world.act("flow_theme_new", key=DEMO, name="Release work")
    # a rename moves nothing and changes no name a move kept
    assert moves_of(world, DEMO) == [(None, "Docs and guides", "ai"), ("Docs and guides", "Inbox questions", "person"),
                                     ("Things to answer", "Release work", "person")]
    assert all(isinstance(m["at_ms"], int) for m in world.app.themes.load()["moves"])
    # a run that leaves a point where it was moves nothing; a regroup that places it elsewhere does
    world.runner.handlers["claude.p"] = lambda argv: answer(["Inbox questions", "Fresh"], [point(1, "Fresh")])
    world.act("flow_themes_run", mode="regroup", keys=[YES])
    assert moves_of(world, YES) == [(None, "Inbox questions", "ai"), ("Things to answer", "Fresh", "ai")]


def test_only_the_last_500_moves_are_kept(world):
    data = world.app.themes.load()
    data["moves"] = [{"key": f"task:t{i}", "from": None, "to": "X", "by": "ai", "at_ms": i} for i in range(600)]
    world.app.themes.save(data)
    world.act("flow_themes_run", mode="assign", keys=[DEMO])
    moves = world.app.themes.load()["moves"]
    assert len(moves) == th.MOVES_MAX == 500 and moves[-1]["key"] == DEMO
