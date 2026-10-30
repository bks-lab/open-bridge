# SPDX-License-Identifier: MIT
"""The tmux workplace driver: pure state heuristics, then the protocol against a REAL tmux.

The integration tests run on a private socket (BRIDGE_TMUX_SOCKET=bridge-test-<random>) started
with an empty config, so they never touch the person's own tmux server, and they kill only that
private server afterwards. They skip when tmux is not installed.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DRIVER = ROOT / "skills" / "tmux" / "scripts" / "tmux_driver.py"
sys.path.insert(0, str(DRIVER.parent))
import tmux_driver as td  # noqa: E402

TMUX = shutil.which("tmux") or next((p for p in ("/opt/homebrew/bin/tmux", "/usr/local/bin/tmux")
                                     if os.access(p, os.X_OK)), None)

# ---------------------------------------------------------------- pure heuristics

CLAUDE_WORKING = """\
> fix the failing test in scripts/tests

● Reading scripts/workplace.py

✻ Pondering… (12s · ↑ 1.2k tokens · esc to interrupt)

╭──────────────────────────────────────────────╮
│ >                                            │
╰──────────────────────────────────────────────╯
  ⏵⏵ accept edits on (shift+tab to cycle)
"""

CLAUDE_PERMISSION = """\
● Bash(git status)

╭──────────────────────────────────────────────╮
│ Bash command                                 │
│                                              │
│   git status                                 │
│                                              │
│ Do you want to proceed?                      │
│ ❯ 1. Yes                                     │
│   2. Yes, and don't ask again for git status │
│   3. No, and tell Claude what to do (esc)    │
╰──────────────────────────────────────────────╯
"""

CLAUDE_IDLE = """\
● Done. The test passes now.

╭──────────────────────────────────────────────╮
│ >                                            │
╰──────────────────────────────────────────────╯
  ? for shortcuts
"""

CODEX_WORKING = """\
• Running cargo test

▌ Working (8s • Esc to interrupt)
"""

CODEX_APPROVAL = """\
Would you like to run the following command?

  $ rm -rf target

› 1. Yes, proceed
  2. No, and tell Codex what to do differently
"""


@pytest.mark.parametrize("screen,state", [
    (CLAUDE_WORKING, "working"),
    (CLAUDE_PERMISSION, "needs-you"),
    (CLAUDE_IDLE, "waiting"),
    (CODEX_WORKING, "working"),
    (CODEX_APPROVAL, "needs-you"),
    ("", "waiting"),
])
def test_state_of_an_agent_pane(screen, state):
    assert td.classify_state(screen, agent=True) == state


def test_a_pane_without_agent_is_shell_whatever_it_shows():
    assert td.classify_state(CLAUDE_WORKING, agent=False) == "shell"


def test_old_scrollback_does_not_decide_the_state():
    old = CLAUDE_PERMISSION + "\n".join(f"line {i}" for i in range(40)) + "\n" + CLAUDE_IDLE
    assert td.classify_state(old, agent=True) == "waiting"


def test_working_wins_only_from_the_bottom():
    done = CLAUDE_WORKING.replace("  ⏵⏵ accept edits on (shift+tab to cycle)\n", "") + "\n".join(
        f"out {i}" for i in range(10))
    assert td.classify_state(done, agent=True) == "waiting"


def test_last_line_and_shells():
    assert td.last_line("a\n  b  \n\n  \n") == "b"
    assert td.last_line("") == ""
    assert td.is_shell("zsh") and td.is_shell("-bash") and td.is_shell("/bin/sh")
    assert not td.is_shell("claude") and not td.is_shell("2.1.3")


def test_rows_split_on_the_separator_raw_or_escaped():
    # tmux 3.4 (Ubuntu 24.04) prints the unit separator in -F output as the four
    # characters \037; newer tmux passes the byte through. Both must parse.
    raw = "Work" + td.SEP + "one"
    escaped = "Work\\037one"
    assert td.split_row(raw) == ["Work", "one"]
    assert td.split_row(escaped) == ["Work", "one"]
    assert td.split_row("a\\037b\\037c", 1) == ["a", "b" + td.SEP + "c"]


@pytest.mark.parametrize("args,agent", [
    ("claude --resume 1b4e28ba-2fa1-11d2-883f-0016d3cca427", True),
    ("/opt/tools/bin/claude -n task", True),
    ("node /opt/homebrew/lib/node_modules/@anthropic-ai/claude-code/cli.js", True),
    ("codex exec hi", True),
    ("/bin/sh /tmp/t/claude --resume x", True),
    ("-zsh", False),
    ("vim claude.md", False),
    ("cat", False),
])
def test_agent_args(args, agent):
    assert td.is_agent_args(args) is agent


def test_session_id_from_args():
    sid = "1b4e28ba-2fa1-11d2-883f-0016d3cca427"
    assert td.session_id_in(f"claude --resume {sid} --model x") == sid
    assert td.session_id_in(f"claude -r {sid}") == sid
    assert td.session_id_in("claude -n task") is None


def test_process_tree():
    procs = td.parse_ps("  10     1 -zsh\n  11    10 claude -r x\n  12    11 node mcp\n  13     1 other\n")
    assert td.descendants(10, procs) == ["-zsh", "claude -r x", "node mcp"]


def test_session_names_and_resolution():
    assert td.session_name("open.bridge:x") == "open_bridge_x"
    assert td.resolve_session(["Platform", "Infra"], ["infra", "Misc"]) == "infra"
    assert td.resolve_session(["Nope"], ["Misc"]) is None


# ---------------------------------------------------------------- real tmux

needs_tmux = pytest.mark.skipif(TMUX is None, reason="tmux is not installed")


class Tmux:
    def __init__(self, sock: str, tmp: Path):
        self.sock, self.tmp = sock, tmp
        self.env = {**os.environ, "BRIDGE_TMUX_SOCKET": sock, "BRIDGE_TMUX_BIN": TMUX, "SHELL": "/bin/sh",
                    "BRIDGE_TMUX_LAUNCH_DIR": str(tmp / "launch")}
        self.env.pop("TMUX", None)
        self.env.pop("TMUX_PANE", None)

    def raw(self, *args: str) -> str:
        return subprocess.run([TMUX, "-L", self.sock, "-f", "/dev/null", *args], capture_output=True,
                              text=True, check=True, env=self.env).stdout

    def call(self, req: dict, ok: bool = True, **env) -> dict:
        done = subprocess.run([sys.executable, str(DRIVER)], input=json.dumps(req), capture_output=True,
                              text=True, env={**self.env, **env}, timeout=60)
        assert (done.returncode == 0) is ok, done.stdout + done.stderr
        return json.loads(done.stdout.strip().splitlines()[-1])

    def tabs(self, **env) -> list[dict]:
        return self.call({"verb": "tabs"}, **env)["tabs"]

    def by_name(self, name: str) -> dict:
        return next(t for t in self.tabs() if t["name"] == name)

    def wait_screen(self, ref: str, needle: str) -> str:
        text = ""
        for _ in range(50):
            text = self.call({"verb": "screen", "tab": ref, "lines": 50})["text"]
            if needle in text:
                return text
            time.sleep(0.1)
        return text


@pytest.fixture
def tm(tmp_path):
    t = Tmux(f"bridge-test-{uuid.uuid4().hex[:10]}", tmp_path)
    t.raw("new-session", "-d", "-s", "Work", "-n", "one", "cat")
    t.raw("new-window", "-d", "-t", "=Work:", "-n", "two", "sh")
    sock_path = t.raw("display-message", "-p", "#{socket_path}").strip()
    try:
        yield t
    finally:
        # only this private server; tmux leaves its socket file behind, so that goes too
        subprocess.run([TMUX, "-L", t.sock, "kill-server"], capture_output=True)
        if sock_path and Path(sock_path).name == t.sock:
            Path(sock_path).unlink(missing_ok=True)


@needs_tmux
def test_caps_lists_all_fifteen_verbs(tm):
    assert set(tm.call({"verb": "caps"})["caps"]) == set(td.VERBS)
    assert len(td.VERBS) == 15 and {"rename_workspace", "move_tab"} <= set(td.VERBS)
    assert not {"set_color", "set_description"} & set(td.VERBS)      # tmux has no colour or description


@needs_tmux
def test_move_tab_moves_the_window_into_the_session(tm):
    tm.raw("new-session", "-d", "-s", "Other", "-n", "three", "sh")
    one, other = tm.by_name("one"), tm.by_name("three")
    report = tm.call({"verb": "move_tab", "tab": one["ref"], "workspace": other["ws_ref"]})["report"]
    assert report and not report[0].startswith("ERROR")
    moved = tm.by_name("one")
    assert moved["ref"] == one["ref"] and moved["ws_ref"] == other["ws_ref"] and moved["workspace"] == "Other"
    assert tm.by_name("two")["workspace"] == "Work"                  # the other window stays
    # a malformed or unknown ref is an error, never a guess
    assert "not a tmux session ref" in tm.call({"verb": "move_tab", "tab": one["ref"], "workspace": "Work"},
                                               ok=False)["error"]
    assert "no open workspace" in tm.call({"verb": "move_tab", "tab": one["ref"], "workspace": "$999"},
                                          ok=False)["error"]


@needs_tmux
def test_move_tab_never_moves_the_last_window_of_a_session(tm):
    tm.raw("new-session", "-d", "-s", "Solo", "-n", "alone", "sh")
    alone, work = tm.by_name("alone"), tm.by_name("one")
    report = tm.call({"verb": "move_tab", "tab": alone["ref"], "workspace": work["ws_ref"]})["report"]
    assert report[0].startswith("ERROR") and "last" in report[0]
    assert tm.by_name("alone")["workspace"] == "Solo"


@needs_tmux
def test_tabs_carry_the_session_id_as_ws_ref(tm):
    sid = tm.raw("display-message", "-p", "-t", "=Work:", "#{session_id}").strip()
    tabs = tm.tabs()
    assert sid.startswith("$") and {t["ws_ref"] for t in tabs} == {sid}


@needs_tmux
def test_rename_workspace_renames_the_session_with_the_sanitized_title(tm):
    sid = tm.by_name("one")["ws_ref"]
    report = tm.call({"verb": "rename_workspace", "workspace": sid, "title": "open.bridge: notes"})["report"]
    assert report and not report[0].startswith("ERROR")
    assert {t["workspace"] for t in tm.tabs()} == {"open_bridge_ notes"}
    assert {t["ws_ref"] for t in tm.tabs()} == {sid}          # the id stays, only the name changes
    # a name another session has (after the same sanitizer), a malformed or unknown ref: errors, nothing renamed
    tm.raw("new-session", "-d", "-s", "Other_x", "sh")
    assert "in use" in tm.call({"verb": "rename_workspace", "workspace": sid, "title": "other.x"}, ok=False)["error"]
    assert "not a tmux session ref" in tm.call({"verb": "rename_workspace", "workspace": "Work", "title": "X"},
                                               ok=False)["error"]
    assert "no open workspace" in tm.call({"verb": "rename_workspace", "workspace": "$999", "title": "X"},
                                          ok=False)["error"]
    assert "open_bridge_ notes" in {t["workspace"] for t in tm.tabs()}


@needs_tmux
def test_no_server_means_no_tabs(tmp_path):
    t = Tmux(f"bridge-test-{uuid.uuid4().hex[:10]}", tmp_path)
    assert t.tabs() == []


@needs_tmux
def test_tabs_map_session_window_pane(tm):
    tabs = tm.tabs()
    assert {(t["workspace"], t["name"]) for t in tabs} == {("Work", "one"), ("Work", "two")}
    for t in tabs:
        assert t["ref"].startswith("%") and t["id"] == t["ref"]
        assert t["state"] == "shell" and t["is_self"] is False


@needs_tmux
def test_is_self_marks_the_callers_window(tm):
    ref = tm.by_name("two")["ref"]
    tabs = tm.tabs(TMUX_PANE=ref)
    assert [t["name"] for t in tabs if t["is_self"]] == ["two"]


@needs_tmux
def test_send_screen_and_key(tm):
    ref = tm.by_name("one")["ref"]
    assert tm.call({"verb": "send", "tab": ref, "text": "hello driver"})["report"] == [f"sent to {ref}"]
    assert "hello driver" in tm.wait_screen(ref, "hello driver")
    assert tm.call({"verb": "key", "tab": ref, "key": "y"})["report"] == [f"key y to {ref}"]
    tm.call({"verb": "key", "tab": ref, "key": "enter"})
    assert "y" in tm.wait_screen(ref, "\ny")
    bad = tm.call({"verb": "key", "tab": ref, "key": "C-c"})["report"]
    assert bad[0].startswith("ERROR")


@needs_tmux
def test_keys_type_as_a_keyboard_does(tm):
    ref = tm.by_name("one")["ref"]
    report = tm.call({"verb": "keys", "tab": ref, "keys": [{"text": "echo typed"}, {"key": "backspace"}, {"text": "d-live"}, {"key": "enter"}]})["report"]
    assert report == [f"4 steps to {ref}"]
    assert "typed-live" in tm.wait_screen(ref, "\ntyped-live")
    bad = tm.call({"verb": "keys", "tab": ref, "keys": [{"key": "C-c"}]})["report"]
    assert bad[0].startswith("ERROR")


@pytest.mark.parametrize("asked, read", [(40, 40), (3000, 3000), (5000, 5000), (99999, 5000), (None, td.SCREEN_LINES)])
def test_screen_reads_the_scrollback_up_to_five_thousand_lines(monkeypatch, asked, read):
    seen = []
    monkeypatch.setattr(td, "check_ref", lambda ref: ref)
    monkeypatch.setattr(td, "capture", lambda ref, n=None: seen.append(n) or "row\n\n")
    req = {"verb": "screen", "tab": "%3", **({"lines": asked} if asked else {})}
    assert td.screen(req) == {"text": "row"} and seen == [read]


@needs_tmux
def test_screen_strips_trailing_blanks_and_limits_lines(tm):
    ref = tm.by_name("two")["ref"]
    tm.call({"verb": "send", "tab": ref, "text": "for i in 1 2 3 4 5; do echo row$i; done"})
    tm.wait_screen(ref, "row5")
    text = tm.call({"verb": "screen", "tab": ref, "lines": 3})["text"]
    assert len(text.splitlines()) == 3 and not text.endswith("\n")


@needs_tmux
def test_rename_focus_close(tm):
    one, two = tm.by_name("one")["ref"], tm.by_name("two")["ref"]
    tm.call({"verb": "rename", "tab": one, "title": "Renamed"})
    assert tm.by_name("Renamed")["ref"] == one
    assert tm.call({"verb": "focus", "tab": two})["report"][0].startswith(f"focused {two}")
    assert tm.raw("display-message", "-p", "-t", "=Work:", "#{window_name}").strip() == "two"
    assert tm.call({"verb": "close", "tab": one})["report"] == [f"closed {one}"]
    assert [t["ref"] for t in tm.tabs()] == [two]
    # the last pane on the server is never closed: that would end the server
    assert tm.call({"verb": "close", "tab": two})["report"][0].startswith("ERROR")
    assert [t["ref"] for t in tm.tabs()] == [two]


@needs_tmux
def test_unknown_or_malformed_ref_is_an_error(tm):
    assert "no open tab" in tm.call({"verb": "send", "tab": "%999", "text": "x"}, ok=False)["error"]
    assert "not a tmux pane ref" in tm.call({"verb": "screen", "tab": "surface:3"}, ok=False)["error"]
    assert "unknown verb" in tm.call({"verb": "explode"}, ok=False)["error"]


@needs_tmux
def test_launch_tab_goes_into_the_callers_session_only(tm):
    here = tm.by_name("two")["ref"]
    rep = tm.call({"verb": "launch", "target": "tab", "here": here,
                   "tabs": [{"label": "Task", "slug": "task", "command": "cat"}]})["report"]
    assert rep[0].startswith("tab Task (%") and rep[0].endswith("in Work")
    assert tm.by_name("Task")["workspace"] == "Work"
    lost = tm.call({"verb": "launch", "target": "tab", "here": None,
                    "tabs": [{"label": "Nowhere", "slug": "n", "command": "cat"}]})["report"]
    assert lost[0].startswith("ERROR")


@needs_tmux
def test_launch_workspace_and_area(tm):
    tm.call({"verb": "launch", "target": "workspace",
             "tabs": [{"label": "Big", "slug": "big", "command": "cat"}]})
    assert tm.by_name("Big")["workspace"] == "Big"
    rep = tm.call({"verb": "launch", "target": "area", "tabs": [
        {"label": "A1", "slug": "a1", "command": "cat", "workspace": "Platform", "aliases": ["Infra"]},
        {"label": "A2", "slug": "a2", "command": "cat", "workspace": "platform"},
        {"label": "W1", "slug": "w1", "command": "cat", "workspace": "Misc", "aliases": ["work"]},
    ]})["report"]
    assert rep.count("new workspace Platform") == 1
    tabs = {t["name"]: t["workspace"] for t in tm.tabs()}
    assert tabs["A1"] == tabs["A2"] == "Platform" and tabs["W1"] == "Work"


@needs_tmux
def test_launch_writes_a_long_command_to_a_private_file(tm):
    long_cmd = "echo " + "x" * 5000 + " && cat"
    tm.call({"verb": "launch", "target": "workspace",
             "tabs": [{"label": "Long", "slug": "long", "command": long_cmd}]})
    files = list((tm.tmp / "launch").iterdir())
    assert len(files) == 1 and oct(files[0].stat().st_mode & 0o777) == "0o600"
    assert "xxxx" in tm.wait_screen(tm.by_name("Long")["ref"], "xxxx")


@needs_tmux
def test_open_plan_reuses_and_never_closes(tm):
    one = tm.by_name("one")["ref"]
    plan = {"control": {"name": "Control"}, "workspaces": [
        {"name": "Work", "tabs": [
            {"slug": "a", "label": "Alpha", "action": "open", "ref": one, "workspace": "Work"},
            {"slug": "b", "label": "Beta", "action": "new", "command": "cat"},
            {"slug": "c", "label": "Gamma", "action": "resume", "command": "cat"},
        ]},
        {"name": "Fresh", "tabs": [{"slug": "d", "label": "Delta", "action": "new", "command": "cat"}]},
    ]}
    rep = tm.call({"verb": "open", "plan": plan, "only": None, "resume": False, "here": None})["report"]
    assert not any(line.lstrip().startswith("ERROR") for line in rep), rep
    tabs = {t["name"]: t["workspace"] for t in tm.tabs()}
    assert tabs["Alpha"] == "Work" and tabs["Beta"] == "Work" and tabs["Delta"] == "Fresh"
    assert "Gamma" not in tabs and "Control" in {t["workspace"] for t in tm.tabs()}
    count = len(tm.tabs())
    again = tm.call({"verb": "open", "plan": plan, "only": None, "resume": False, "here": None})["report"]
    assert len(tm.tabs()) == count
    assert any("already open: Beta" in line for line in again)


@needs_tmux
def test_open_never_moves_the_last_window_of_a_session(tm):
    tm.raw("new-session", "-d", "-s", "Lonely", "-n", "solo", "cat")
    solo = tm.by_name("solo")["ref"]
    plan = {"control": {"name": "Work"}, "workspaces": [
        {"name": "Elsewhere", "tabs": [{"slug": "s", "label": "Solo", "action": "open", "ref": solo,
                                        "workspace": "Lonely"}]}]}
    rep = tm.call({"verb": "open", "plan": plan, "only": None, "resume": False, "here": None})["report"]
    assert any("kept Solo in Lonely" in line for line in rep)
    assert tm.by_name("Solo")["workspace"] == "Lonely"


@needs_tmux
def test_control_creates_then_opens_beside_a_dead_one(tm):
    req = {"verb": "control", "control": {"name": "Control"}, "command": "cat", "root": str(tm.tmp)}
    assert tm.call(req)["report"][0].startswith("created Control")
    # `cat` is no agent, so the control window reads as shell and a second one opens beside it
    assert "tab Control in Control" in tm.call(req)["report"][0]
    assert tm.call({"verb": "control", "control": {}}, ok=False)["error"]


def _fake_agent(tmp: Path, screen: str) -> str:
    """A script named `claude` that prints a screen and idles: its args look like a resumed agent."""
    d = tmp / "bin"
    d.mkdir(exist_ok=True)
    script = d / "claude"
    (d / "screen.txt").write_text(screen, encoding="utf-8")
    script.write_text(f"#!/bin/sh\ncat '{d / 'screen.txt'}'\nsleep 300\n", encoding="utf-8")
    script.chmod(0o755)
    return f"/bin/sh {script} --resume 1b4e28ba-2fa1-11d2-883f-0016d3cca427"


@needs_tmux
@pytest.mark.parametrize("screen,state", [("● Done.\n  ? for shortcuts\n", "waiting"),
                                          (CLAUDE_WORKING, "working"),
                                          (CLAUDE_PERMISSION, "needs-you")])
def test_agent_state_and_session_from_a_live_pane(tm, screen, state):
    tm.raw("new-window", "-d", "-t", "=Work:", "-n", "agent", _fake_agent(tm.tmp, screen))
    for _ in range(50):
        tab = tm.by_name("agent")
        if tab["state"] == state:
            break
        time.sleep(0.1)
    assert tab["state"] == state
    assert tm.call({"verb": "sessions"})["sessions"] == {"agent": "1b4e28ba-2fa1-11d2-883f-0016d3cca427"}


@needs_tmux
def test_a_title_that_starts_with_a_dash_names_a_tab_and_a_workspace(tm):
    """tmux reads a leading '-' as its flags: the free text goes after `--`"""
    one = tm.by_name("one")["ref"]
    report = tm.call({"verb": "rename", "tab": one, "title": "-scratch"})["report"]
    assert report and not report[0].startswith("ERROR")
    assert tm.by_name("-scratch")["ref"] == one
    sid = tm.by_name("-scratch")["ws_ref"]
    report = tm.call({"verb": "rename_workspace", "workspace": sid, "title": "-notes"})["report"]
    assert report and not report[0].startswith("ERROR")
    assert {t["workspace"] for t in tm.tabs()} == {"-notes"}
