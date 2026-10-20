# SPDX-License-Identifier: MIT
"""Contract for the decision guide of the cockpit (scripts/lib/bridge_cockpit/guide.py).

When an agent tab waits for its owner, Claude Haiku reads the end of that session (its transcript under
~/.claude/projects/, the tab's screen where there is none) and answers in two sentences where the session
stands and what it waits for, with two to four next steps. The page draws that as a small tree whose
branches are buttons; a button sends through the reply verbs that already guard a tab (tab_send,
tab_option), never through a path of its own. Off until cockpit.session_guide.enabled or the settings page
switches it on. Hermetic: claude is the FakeRunner's, the Claude folder a temp one.

Run: pytest -q scripts/tests/test_bridge_cockpit_guide.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_bridge_cockpit import World, ok, fail, private_key_dir  # noqa: E402,F401  (the autouse fixture comes along)
from lib import model_route as mr  # noqa: E402
from lib.bridge_cockpit import guide as gd  # noqa: E402
from lib.bridge_cockpit.actions import ActionError  # noqa: E402
from lib.bridge_cockpit.config import load_web_config  # noqa: E402

SID = "5b0e8f3c-2f4a-4d7e-9a1b-0c2d3e4f5a6b"
SURF = "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"
GUIDE_CFG = ("cockpit:\n  enabled: true\n  language: en\n  relay: true\n  session_guide:\n{guide}"
             "workplace:\n  control:\n    name: Control\n")
ON = "    enabled: true\n"
SCREEN = "> fix the readme\n\n⏺ The README now names the new flag. Shall I open a pull request?\n\n│ > │\n"


def line(kind: str, content, **more) -> str:
    entry = {"type": kind, "message": {"role": kind, "content": content}, "isSidechain": False, **more}
    return json.dumps(entry)


TRANSCRIPT = [
    json.dumps({"type": "ai-title", "aiTitle": "README flag", "sessionId": SID}),
    line("user", "first ask: look at the flags"),
    line("assistant", [{"type": "text", "text": "I looked at the flags."}]),
    line("user", "<system-reminder>noise the model never needs</system-reminder>please document the --dry flag in the README"),
    line("assistant", [{"type": "thinking", "thinking": "secret thoughts"}, {"type": "tool_use", "id": "t1", "name": "Edit", "input": {}}]),
    line("user", [{"type": "tool_result", "tool_use_id": "t1", "content": "edited"}]),
    line("user", "meta words", isMeta=True),
    json.dumps({"type": "user", "isSidechain": True, "message": {"role": "user", "content": "a subagent's prompt"}}),
    line("assistant", [{"type": "text", "text": "The README now names the --dry flag."},
                       {"type": "text", "text": "Shall I open a pull request?"}]),
]


def haiku_answer(payload: dict | str, cost: float = 0.0021) -> str:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return json.dumps({"type": "result", "result": text, "total_cost_usd": cost})


WAITING_ANSWER = {
    "where": "The README documents the --dry flag; the change is not committed yet.",
    "waits_for": "Whether to open a pull request.",
    "options": [
        {"label": "Open the PR", "send": "Yes, commit and open a pull request.", "why": "the change is done", "risky": False},
        {"label": "Show the diff", "send": "Show me the diff first.", "why": "check before it leaves", "risky": False},
        {"label": "Stop here", "send": "No, leave it uncommitted.", "why": "", "risky": False},
    ],
    "pick": 1,
}


def claude_home(base: Path, root: Path, now_ms: float, lines: list[str] | None = TRANSCRIPT) -> Path:
    home = base / "claude"
    (home / "sessions").mkdir(parents=True, exist_ok=True)
    alive = {"pid": os.getpid(), "sessionId": SID, "cwd": str(root), "startedAt": int(now_ms - 3_600_000),
             "name": "readme", "status": "idle", "statusUpdatedAt": int(now_ms - 60_000), "kind": "interactive"}
    (home / "sessions" / f"{alive['pid']}.json").write_text(json.dumps(alive), encoding="utf-8")
    folder = home / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(root))
    folder.mkdir(parents=True, exist_ok=True)
    if lines is not None:
        (folder / f"{SID}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return home


def waiting_tab(state: str = "waiting", **more) -> dict:
    return {"name": "Readme work", "workspace": "Bridge", "ref": "surface:40", "ws_ref": "workspace:9",
            "state": state, "id": SURF, **more}


def make_world(tmp_path, guide: str = ON, tabs: list[dict] | None = None, screen: str = SCREEN,
               transcript: list[str] | None = TRANSCRIPT, answer: str | None = None) -> World:
    w = World(tmp_path, config=GUIDE_CFG.format(guide=guide), asks=True, prepare=False)
    now_ms = time.time() * 1000
    w.clock.now = now_ms
    w.app.sessions.base = claude_home(tmp_path, w.root, now_ms, transcript)
    w.runner.handlers["workplace.status"] = lambda argv: ok(tabs if tabs is not None else [waiting_tab()])
    w.runner.handlers["workplace.screen"] = lambda argv: ok({"text": screen})
    w.runner.handlers["eww.-o"] = lambda argv: ok(f"claude CMUX_SURFACE_ID={SURF} X=1\n")
    w.runner.handlers["claude.p"] = lambda argv: ok(answer if answer is not None else haiku_answer(WAITING_ANSWER))
    return w


def settle(w: World, seconds: float = 5.0) -> None:
    """Wait until the guide's worker is idle."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not w.app.guide.busy():
            return
        time.sleep(0.01)
    raise AssertionError("the guide did not finish in time")


def poll(w: World) -> None:
    w.app.tabs.poll()
    settle(w)


def haiku_calls(w: World) -> list[list[str]]:
    return w.runner.of("claude.p")


@pytest.fixture
def world(tmp_path):
    w = World(tmp_path)
    yield w
    w.close()


@pytest.fixture
def gworld(tmp_path):
    w = make_world(tmp_path)
    yield w
    w.close()


# ---------------------------------------------------------------- 1 off by default

def test_without_a_block_the_guide_is_off_and_reads_nothing(world):
    state = world.app.state_payload()["guide"]
    assert state["enabled"] is False and state["entries"] == {}
    world.app.tabs.poll()
    assert world.runner.of("claude.p") == []


def test_config_takes_the_block_key_by_key_and_warns_on_a_bad_one(tmp_path):
    (tmp_path / "bridge-config.yaml").write_text(
        "cockpit:\n  session_guide:\n    enabled: true\n    auto: maybe\n    per_hour: 5\n    colour: red\n",
        encoding="utf-8")
    cfg = load_web_config(tmp_path)
    assert cfg.session_guide == {"enabled": True, "auto": True, "per_hour": 5}
    warnings = " ".join(cfg.config_warnings)
    assert "session_guide.auto" in warnings and "session_guide.colour" in warnings
    (tmp_path / "bridge-config.yaml").write_text("cockpit:\n  session_guide:\n    per_hour: 0\n", encoding="utf-8")
    assert load_web_config(tmp_path).session_guide["per_hour"] == gd.DEFAULTS["per_hour"]


# ---------------------------------------------------------------- 2 reading a session

def test_the_transcript_gives_the_last_ask_and_what_the_agent_said_after_it(tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_text("\n".join(TRANSCRIPT) + "\n", encoding="utf-8")
    turns = gd.turns_of(gd.read_tail(path, gd.TAIL_BYTES))
    assert turns["title"] == "README flag"
    assert turns["user"] == "please document the --dry flag in the README"        # no reminder, no meta, no subagent
    assert turns["prev"] == "first ask: look at the flags"
    assert turns["said"] == "The README now names the --dry flag.\nShall I open a pull request?"
    assert "secret thoughts" not in json.dumps(turns)                               # thinking never leaves


def test_a_tail_read_drops_the_cut_first_line_and_a_missing_file_reads_empty(tmp_path):
    path = tmp_path / "s.jsonl"
    path.write_text("x" * 50 + "\n" + "\n".join(TRANSCRIPT) + "\n", encoding="utf-8")
    lines = gd.read_tail(path, len("\n".join(TRANSCRIPT)) + 10)
    assert all(not ln.startswith("xxx") for ln in lines)
    assert gd.turns_of(lines)["said"].endswith("pull request?")
    assert gd.read_tail(tmp_path / "missing.jsonl", 1000) == []
    assert gd.turns_of(["{nope", "", json.dumps({"type": "user"})]) == {"title": None, "prev": None, "user": None, "said": None}


def test_long_turns_keep_the_start_of_the_ask_and_the_end_of_the_answer():
    long_ask = "ask " + "a" * 5000 + " END"
    long_said = "START " + "b" * 9000 + " the last words"
    turns = gd.turns_of([line("user", long_ask), line("assistant", [{"type": "text", "text": long_said}])])
    assert len(turns["user"]) <= gd.USER_MAX and turns["user"].startswith("ask ")
    assert len(turns["said"]) <= gd.SAID_MAX and turns["said"].endswith("the last words")


def test_the_key_of_a_tab_is_its_question_else_its_state_since(gworld):
    assert gd.key_of({"state": "waiting", "since_ms": 5, "ask": {"hash": "0123456789abcdef"}}) == "0123456789abcdef"
    assert gd.key_of({"state": "waiting", "since_ms": 5, "ask": None}) == "waiting:5"


# ---------------------------------------------------------------- 3 the prompt and the answer

def test_the_prompt_names_the_question_the_turns_and_the_language_and_stays_under_the_limit(gworld):
    tab = {"name": "Readme work", "workspace": "Bridge", "state": "waiting",
           "ask": {"text": "Shall I open a pull request?", "options": []}}
    context = {"title": "README flag", "prev": "earlier", "user": "please document it", "said": "Done. Shall I?",
               "source": "transcript", "project": "bridge"}
    text = gd.prompt(tab, context, "de", "Alex")
    assert "please document it" in text and "Shall I open a pull request?" in text and "German" in text
    assert "Alex" in text and len(text) <= mr.HAIKU_PROMPT_MAX
    huge = {**context, "said": "z" * 20000, "user": "y" * 20000, "prev": "x" * 20000}
    assert len(gd.prompt(tab, huge, "en", None)) <= mr.HAIKU_PROMPT_MAX


def test_a_waiting_answer_becomes_options_that_send_words(gworld):
    result, cost = gd.parse(haiku_answer(WAITING_ANSWER), "waiting", None)
    assert cost == pytest.approx(0.0021)
    assert result["where"].startswith("The README documents")
    assert result["waits_for"] == "Whether to open a pull request."
    assert [o["label"] for o in result["options"]] == ["Open the PR", "Show the diff", "Stop here"]
    assert result["options"][0]["send"] == "Yes, commit and open a pull request."
    assert all(o["n"] is None for o in result["options"])
    assert result["pick"] == 1


def test_options_that_push_merge_delete_or_deploy_count_as_risky_whatever_haiku_says(gworld):
    answer = {**WAITING_ANSWER, "options": [
        {"label": "Ship it", "send": "git push --force and merge the PR", "risky": False},
        {"label": "Clean up", "send": "Delete the old branch", "risky": False},
        {"label": "Look", "send": "Show me the test output", "risky": False},
        {"label": "Löschen", "send": "Lösche die Datei", "risky": False},
    ]}
    result, _ = gd.parse(haiku_answer(answer), "waiting", None)
    assert [o["risky"] for o in result["options"]] == [True, True, False, True]


def test_a_bad_answer_keeps_only_what_is_safe_to_offer(gworld):
    answer = {"where": "  It   stands\nhere \x07 ", "options": [
        {"label": "", "send": "no label"}, {"label": "No send"}, {"label": "x" * 200, "send": "y" * 2000, "why": "w" * 400},
        {"label": "two", "send": "b"}, {"label": "three", "send": "c"}, {"label": "four", "send": "d"}, {"label": "five", "send": "e"},
    ], "pick": 9}
    result, _ = gd.parse(haiku_answer(answer), "waiting", None)
    assert result["where"] == "It stands here"
    assert len(result["options"]) == gd.OPTIONS_MAX
    first = result["options"][0]
    assert len(first["label"]) <= gd.LABEL_MAX and len(first["send"]) <= gd.SEND_MAX and len(first["why"]) <= gd.WHY_MAX
    assert result["pick"] is None
    assert gd.parse(haiku_answer("no json here"), "waiting", None)[0] is None
    assert gd.parse(haiku_answer({"options": []}), "waiting", None)[0] is None            # no where: nothing to show
    assert gd.parse("", "waiting", None)[0] is None


def test_a_dialog_answer_only_names_options_the_dialog_shows(gworld):
    ask = {"options": [{"n": 1, "label": "Yes"}, {"n": 2, "label": "Yes, and don't ask again"}, {"n": 3, "label": "No"}]}
    answer = {"where": "It wants to run the tests.", "waits_for": "Permission to run pytest.",
              "options": [{"n": 1, "why": "safe, read only"}, {"n": 7, "why": "not there"}, {"n": 3, "why": "stop"},
                          {"n": 1, "why": "twice"}, {"label": "free words", "send": "type this"}], "pick": 0}
    result, _ = gd.parse(haiku_answer(answer), "needs-you", ask)
    assert [(o["n"], o["label"], o["send"]) for o in result["options"]] == [(1, "Yes", None), (3, "No", None)]
    assert result["pick"] == 0


# ---------------------------------------------------------------- 4 reading on its own

def test_a_tab_that_starts_waiting_is_read_once_with_haiku_without_tools(gworld):
    poll(gworld)
    calls = haiku_calls(gworld)
    assert len(calls) == 1
    argv = calls[0]
    assert argv[:12] == mr.haiku_argv(gworld.runner.claude, "")[:12]                      # no tools, no session, no settings
    assert "please document the --dry flag" in argv[12]
    entry = gworld.app.state_payload()["guide"]["entries"]["surface:40"]
    tab = next(t for t in gworld.app.tabs_state()["tabs"] if t["ref"] == "surface:40")
    assert entry["key"] == tab["ask"]["hash"] and entry["state"] == "waiting" and entry["source"] == "transcript"
    assert entry["running"] is False and entry["error"] is None and len(entry["options"]) == 3
    assert entry["cost_usd"] == pytest.approx(0.0021) and entry["auto"] is True
    poll(gworld)
    gworld.clock.advance(120)
    poll(gworld)
    assert len(haiku_calls(gworld)) == 1                                                  # the same question is not read again


def test_a_new_question_in_the_same_tab_is_read_again(tmp_path):
    screens = iter([SCREEN, SCREEN.replace("Shall I open a pull request?", "Which branch should it go to?")])
    w = make_world(tmp_path)
    current = {"text": next(screens)}
    w.runner.handlers["workplace.screen"] = lambda argv: ok(current)
    try:
        poll(w)
        current["text"] = next(screens)
        w.clock.advance(61)                                                               # asks.py reads a question again after a minute
        poll(w)
        assert len(haiku_calls(w)) == 2
    finally:
        w.close()


def test_the_control_tab_a_working_tab_and_a_shell_are_never_read(tmp_path):
    tabs = [waiting_tab(ref="surface:1", id="X1", workspace="Control", name="control"),
            waiting_tab(ref="surface:2", id="X2", state="working"), waiting_tab(ref="surface:3", id="X3", state="shell")]
    w = make_world(tmp_path, tabs=tabs)
    try:
        poll(w)
        poll(w)
        assert haiku_calls(w) == []
    finally:
        w.close()


def test_without_auto_nothing_is_read_until_the_button(tmp_path):
    w = make_world(tmp_path, guide=ON + "    auto: false\n")
    try:
        poll(w)
        assert haiku_calls(w) == []
        out = w.act("guide_read", tab_ref="surface:40")
        assert out["ok"] is True
        settle(w)
        assert len(haiku_calls(w)) == 1
        assert w.app.guide.state()["entries"]["surface:40"]["auto"] is False
    finally:
        w.close()


def test_auto_reads_stop_at_the_hourly_limit_and_the_button_still_works(tmp_path):
    w = make_world(tmp_path, guide=ON + "    per_hour: 1\n")
    current = {"text": SCREEN}
    w.runner.handlers["workplace.screen"] = lambda argv: ok(current)
    try:
        poll(w)
        current["text"] = SCREEN.replace("pull request", "draft")
        w.clock.advance(61)
        poll(w)
        assert len(haiku_calls(w)) == 1
        w.act("guide_read", tab_ref="surface:40")
        settle(w)
        assert len(haiku_calls(w)) == 2
    finally:
        w.close()


def test_without_a_transcript_the_screen_is_read_instead(tmp_path):
    w = make_world(tmp_path, transcript=None)
    try:
        poll(w)
        argv = haiku_calls(w)[0]
        assert "The README now names the new flag" in argv[12]
        assert w.app.guide.state()["entries"]["surface:40"]["source"] == "screen"
    finally:
        w.close()


def test_a_failed_read_says_why_and_is_not_retried_by_itself(tmp_path):
    w = make_world(tmp_path)
    w.runner.handlers["claude.p"] = lambda argv: fail("rate limited")
    try:
        poll(w)
        entry = w.app.guide.state()["entries"]["surface:40"]
        assert entry["running"] is False and "rate limited" in entry["error"] and entry["options"] == []
        w.clock.advance(120)
        poll(w)
        assert len(haiku_calls(w)) == 1
        w.runner.handlers["claude.p"] = lambda argv: ok(haiku_answer("not json"))
        w.act("guide_read", tab_ref="surface:40")
        settle(w)
        assert w.app.guide.state()["entries"]["surface:40"]["error"]
    finally:
        w.close()


def test_the_cockpit_key_never_reaches_haiku_or_the_page(tmp_path):
    w = make_world(tmp_path)
    key = w.app.token
    w.runner.handlers["workplace.screen"] = lambda argv: ok({"text": SCREEN.replace("new flag", f"flag {key}")})
    lines = TRANSCRIPT[:-1] + [line("assistant", [{"type": "text", "text": f"the key is {key}. Shall I?"}])]
    w.app.sessions.base = claude_home(tmp_path / "other", w.root, w.clock.now, lines)
    w.runner.handlers["claude.p"] = lambda argv: ok(haiku_answer({**WAITING_ANSWER, "where": f"It printed {key}"}))
    try:
        poll(w)
        assert key not in haiku_calls(w)[0][12]
        assert key not in json.dumps(w.app.guide.state())
    finally:
        w.close()


def test_a_tab_that_stopped_waiting_leaves_the_guide(tmp_path):
    tabs = [waiting_tab()]
    w = make_world(tmp_path, tabs=tabs)
    try:
        poll(w)
        assert "surface:40" in w.app.guide.state()["entries"]
        tabs[0] = waiting_tab(state="working")
        poll(w)
        assert w.app.guide.state()["entries"] == {}
    finally:
        w.close()


def test_a_finished_read_goes_out_as_a_guide_event(gworld):
    seen = []
    original = gworld.app.broadcast
    gworld.app.broadcast = lambda event, payload: (seen.append((event, payload)), original(event, payload))
    poll(gworld)
    guide_events = [p for e, p in seen if e == "guide"]
    assert guide_events and guide_events[-1]["entries"]["surface:40"]["running"] is False


# ---------------------------------------------------------------- 5 verbs and settings

def test_guide_read_refuses_while_off_for_an_unknown_tab_and_for_a_tab_that_does_not_wait(tmp_path):
    w = make_world(tmp_path, guide="    enabled: false\n")
    try:
        w.app.tabs.poll()
        with pytest.raises(ActionError) as off:
            w.act("guide_read", tab_ref="surface:40")
        assert off.value.status == 409
        w.act("guide_settings", enabled=True, auto=False)
        with pytest.raises(ActionError) as unknown:
            w.act("guide_read", tab_ref="surface:99")
        assert unknown.value.status in (404, 409)
        with pytest.raises(ActionError) as bad:
            w.act("guide_read", tab_ref="surface:40;rm")
        assert bad.value.status == 400
        w.runner.handlers["workplace.status"] = lambda argv: ok([waiting_tab(state="working")])
        w.app.tabs.poll()
        with pytest.raises(ActionError) as busy:
            w.act("guide_read", tab_ref="surface:40")
        assert busy.value.status == 409
    finally:
        w.close()


def test_settings_from_the_page_sit_beside_the_config_and_reset_back(tmp_path):
    w = make_world(tmp_path, guide="    enabled: false\n")
    try:
        out = w.act("guide_settings", enabled=True)
        assert out["guide"]["enabled"] is True and out["guide"]["overridden"] == ["enabled"]
        saved = json.loads((w.state / "guide.json").read_text(encoding="utf-8"))
        assert saved == {"enabled": True}
        assert "session_guide" not in (w.root / "bridge-config.yaml").read_text(encoding="utf-8").split("enabled: false")[1]
        poll(w)
        assert len(haiku_calls(w)) == 1                                                   # switched on from the page: it reads
        out = w.act("guide_settings_reset")
        assert out["guide"]["enabled"] is False and out["guide"]["overridden"] == []
        assert not (w.state / "guide.json").exists()
        with pytest.raises(ActionError):
            w.act("guide_settings", enabled="yes")
    finally:
        w.close()


def test_the_guide_verbs_never_take_the_write_lock():
    from lib.bridge_cockpit.actions_base import LOCAL_VERBS, SPEC
    for verb in ("guide_read", "guide_settings", "guide_settings_reset"):
        assert verb in SPEC and verb in LOCAL_VERBS
