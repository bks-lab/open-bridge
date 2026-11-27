#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Pytest suite for scripts/bridge-attach.py.

CONTRACT, this file is the authoritative spec for that surface.

WHY THIS EXISTS. A Bridge session starts in the Bridge folder. Work happens in
other repos. /bridge-attach gives a session in any repo exactly one Bridge:
its skills (`--add-dir`), a short attach text (operating rules, state, the
slice of inbox, board and log that concerns this repo), the Bridge's own
project hooks and its memory. Measured on 2026-11-27 (Claude Code 2.1.332):

  - a SessionStart hook's text is cut at 10,000 chars, so the attach text goes
    in through `--append-system-prompt-file`, which has no cap and survives
    compaction; it still stays small, because it costs tokens every turn;
  - Claude Code applies only the LAST `--settings`; a cmux-style agent wrapper
    drops its own hooks when the caller passes one, so hooks travel as a
    generated plugin (`--plugin-dir`, plugin hooks merge) and `--settings` is
    used only for `autoMemoryDirectory`, and never inside such a terminal;
  - an AGENTS.md in an added directory never loads; the attach text points at
    it and the model reads it.

    state(root) -> (state, branch)
        Phase 0, read-only, against the Bridge root, never the caller's cwd.
        NORMAL only on a `user/*` branch with bridge-config.yaml. Every other
        state refuses the attach (CORE_DEV, NO_CONFIG, NOT_A_REPO).

    context_tag(root, cwd) -> str
        The registry entry whose `github:` matches the cwd repo's origin or
        whose `local_path` matches the cwd; else the cwd folder name.

    render(root, cwd, max_chars) -> str
        The attach text. Factual statements, never imperative system text.
        Never longer than max_chars. Inbox items that do not match the repo
        are counted, never shown.

    plan(tool, root, cwd, args, env, state_dir) -> dict
        argv and env for claude, codex or copilot, plus the files written.
        Writes nothing into cwd.

    main(argv) -> int
        `check`, `slice`, `plan`, `exec`, `replay-hooks`. Refusal exits 3.
"""

import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "bridge-attach.py"


def load():
    spec = importlib.util.spec_from_file_location("bridge_attach", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["bridge_attach"] = mod
    spec.loader.exec_module(mod)
    return mod


ba = load()


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True)


def make_repo(path, branch="main", origin=None):
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", branch)
    git(path, "config", "user.email", "t@example.invalid")
    git(path, "config", "user.name", "t")
    (path / "README.md").write_text("x\n")
    git(path, "add", "README.md")
    git(path, "commit", "-q", "-m", "init")
    if origin:
        git(path, "remote", "add", "origin", origin)
    return path


LOG = """# Work log

## Fri 27.11

| Time | Type | Context | What |
|---|---|---|---|
| 2026-11-27 09:00 | 💻 | widget | fixed the widget parser |
| 2026-11-27 10:00 | 💻 | other | unrelated private thing |
"""

BOARD = """# Board

| Lane | Count |
|---|---|
| Doing (tasks) | 4 |
| Review (tasks) | 1 |
| Backlog (tasks) | 7 |
"""

INBOX = [
    {"id": "a1", "state": "open", "summary": "widget: release notes need a look", "area": "Acme"},
    {"id": "a2", "state": "open", "summary": "Bank letter about the account", "area": "Private"},
    {"id": "a3", "state": "open", "summary": "Doctor appointment", "area": "Family"},
]


def make_bridge(tmp_path, branch="user/tester", config=True, inbox=INBOX, memory=True):
    root = make_repo(tmp_path / "bridge", branch=branch)
    (root / "AGENTS.md").write_text("# Manual\n")
    (root / "identity/agent").mkdir(parents=True)
    (root / "identity/agent/IDENTITY.md").write_text("# IDENTITY\n\n## Name\n\n**Test Bridge** (since today).\n")
    if config:
        (root / "bridge-config.yaml").write_text("identity:\n  name: tester\nlanguage:\n  conversation: de\n")
    (root / "ecosystem.yaml").write_text(
        "repos:\n  widget:\n    github: acme/widget\n    local_path: ~/nowhere/widget\n"
    )
    (root / "work").mkdir()
    (root / "work/log.md").write_text(LOG)
    (root / "work/board.md").write_text(BOARD)
    (root / "scripts").mkdir()
    (root / "scripts/inbox.py").write_text(
        "import json, sys\nprint(json.dumps(%s))\n" % json.dumps(inbox)
    )
    if memory:
        (root / "work/memory").mkdir()
        (root / "work/memory/MEMORY.md").write_text("# Memory\n")
        (root / ".claude").mkdir()
        (root / ".claude/settings.local.json").write_text(json.dumps({
            "autoMemoryDirectory": str(root / "work/memory"),
            "hooks": {
                "SessionStart": [{"matcher": "", "hooks": [
                    {"type": "command", "command": "echo start-$CLAUDE_PROJECT_DIR >> \"$HOOKLOG\""}]}],
                "Stop": [{"hooks": [
                    {"type": "command", "command": "echo stop >> \"$HOOKLOG\""}]}],
            },
        }))
    return root


# ---------------------------------------------------------------- Phase 0

def test_state_normal_on_user_branch_with_config(tmp_path):
    root = make_bridge(tmp_path)
    assert ba.state(root) == ("NORMAL", "user/tester")


def test_state_refuses_core_branch(tmp_path):
    root = make_bridge(tmp_path, branch="main")
    assert ba.state(root)[0] == "CORE_DEV"


def test_state_refuses_missing_config(tmp_path):
    root = make_bridge(tmp_path, config=False)
    assert ba.state(root)[0] == "NO_CONFIG"


def test_state_reads_the_root_not_the_cwd(tmp_path, monkeypatch):
    root = make_bridge(tmp_path)
    other = make_repo(tmp_path / "other", branch="main")
    monkeypatch.chdir(other)
    assert ba.state(root)[0] == "NORMAL"


def test_state_not_a_repo(tmp_path):
    (tmp_path / "plain").mkdir()
    assert ba.state(tmp_path / "plain")[0] == "NOT_A_REPO"


# ---------------------------------------------------------------- context tag

def test_tag_from_origin(tmp_path):
    root = make_bridge(tmp_path)
    repo = make_repo(tmp_path / "checkout-x", origin="git@github.com:acme/widget.git")
    assert ba.context_tag(root, repo) == "widget"


def test_tag_from_local_path(tmp_path):
    root = make_bridge(tmp_path)
    repo = make_repo(tmp_path / "w")
    (root / "ecosystem.yaml").write_text(f"repos:\n  gadget:\n    local_path: {repo}\n")
    assert ba.context_tag(root, repo) == "gadget"


def test_tag_falls_back_to_folder_name(tmp_path):
    root = make_bridge(tmp_path)
    repo = make_repo(tmp_path / "Some-Repo")
    assert ba.context_tag(root, repo) == "some-repo"


# ---------------------------------------------------------------- render

def test_render_names_bridge_root_tag_and_manual(tmp_path):
    root = make_bridge(tmp_path)
    repo = make_repo(tmp_path / "w", origin="https://github.com/acme/widget")
    text = ba.render(root, repo)
    assert "Test Bridge" in text
    assert str(root) in text
    assert "`widget`" in text
    assert str(root / "AGENTS.md") in text
    assert str(root / "bin/bridge-run") in text


def test_render_shows_matching_inbox_and_only_counts_the_rest(tmp_path):
    root = make_bridge(tmp_path)
    repo = make_repo(tmp_path / "w", origin="https://github.com/acme/widget")
    text = ba.render(root, repo)
    assert "release notes need a look" in text
    assert "Bank letter" not in text
    assert "Doctor" not in text
    assert "2 other open items" in text


def test_render_log_rows_only_for_the_tag(tmp_path):
    root = make_bridge(tmp_path)
    repo = make_repo(tmp_path / "w", origin="https://github.com/acme/widget")
    text = ba.render(root, repo)
    assert "fixed the widget parser" in text
    assert "unrelated private thing" not in text


def test_render_board_counts(tmp_path):
    root = make_bridge(tmp_path)
    repo = make_repo(tmp_path / "w")
    text = ba.render(root, repo)
    assert "Doing 4" in text and "Review 1" in text and "Backlog 7" in text


def test_render_is_factual_not_imperative(tmp_path):
    root = make_bridge(tmp_path)
    text = ba.render(root, make_repo(tmp_path / "w"))
    for word in ("MUST", "IMPORTANT", "NEVER", "ALWAYS"):
        assert word not in text


def test_render_respects_max_chars(tmp_path):
    many = [{"id": f"i{n}", "state": "open", "summary": f"widget item {n} " + "x" * 300} for n in range(80)]
    root = make_bridge(tmp_path, inbox=many)
    repo = make_repo(tmp_path / "w", origin="https://github.com/acme/widget")
    text = ba.render(root, repo, max_chars=3000)
    assert len(text) <= 3000
    assert "Bridge attached" in text


def test_render_survives_missing_work_files(tmp_path):
    root = make_bridge(tmp_path)
    (root / "work/log.md").unlink()
    (root / "work/board.md").unlink()
    (root / "scripts/inbox.py").unlink()
    text = ba.render(root, make_repo(tmp_path / "w"))
    assert "Bridge attached" in text


def test_render_memory_line_names_the_bridge_memory(tmp_path):
    root = make_bridge(tmp_path)
    text = ba.render(root, make_repo(tmp_path / "w"))
    assert str(root / "work/memory") in text


# ---------------------------------------------------------------- plan

def run_plan(tool, root, cwd, tmp_path, args=(), env=None):
    return ba.plan(tool, root, cwd, list(args), dict(env or {}), tmp_path / "state")


def test_plan_claude(tmp_path):
    root = make_bridge(tmp_path)
    repo = make_repo(tmp_path / "w")
    p = run_plan("claude", root, repo, tmp_path, args=["--model", "haiku"])
    argv = p["argv"]
    assert argv[0] == "claude"
    assert argv[argv.index("--add-dir") + 1] == str(root)
    attach = Path(argv[argv.index("--append-system-prompt-file") + 1])
    assert "Bridge attached" in attach.read_text()
    plugin = Path(argv[argv.index("--plugin-dir") + 1])
    hooks = json.loads((plugin / "hooks/hooks.json").read_text())
    assert set(hooks["hooks"]) >= {"SessionStart", "Stop"}
    settings = json.loads(Path(argv[argv.index("--settings") + 1]).read_text())
    assert settings == {"autoMemoryDirectory": str(root / "work/memory")}
    assert argv[-2:] == ["--model", "haiku"]
    assert p["env"]["BRIDGE_ROOT"] == str(root)
    assert p["env"]["BRIDGE_ATTACH"] == "1"


def test_plan_claude_inside_a_wrapping_terminal_passes_no_settings(tmp_path):
    root = make_bridge(tmp_path)
    p = run_plan("claude", root, make_repo(tmp_path / "w"), tmp_path, env={"CMUX_SURFACE_ID": "s1"})
    assert "--settings" not in p["argv"]
    assert any("wraps the agent" in n for n in p["notes"])


def test_plan_claude_keeps_the_callers_settings(tmp_path):
    root = make_bridge(tmp_path)
    p = run_plan("claude", root, make_repo(tmp_path / "w"), tmp_path, args=["--settings", "/x.json"])
    assert p["argv"].count("--settings") == 1
    assert p["argv"][-2:] == ["--settings", "/x.json"]


def test_plan_claude_without_memory_setting(tmp_path):
    root = make_bridge(tmp_path, memory=False)
    p = run_plan("claude", root, make_repo(tmp_path / "w"), tmp_path)
    assert "--settings" not in p["argv"]


def test_plan_codex(tmp_path):
    root = make_bridge(tmp_path)
    p = run_plan("codex", root, make_repo(tmp_path / "w"), tmp_path, args=["exec", "hi"])
    argv = p["argv"]
    assert argv[0] == "codex"
    assert argv[argv.index("--add-dir") + 1] == str(root)
    c = argv[argv.index("-c") + 1]
    assert c.startswith("developer_instructions=") and "Bridge attached" in c
    assert argv[-2:] == ["exec", "hi"]
    assert any("skills" in n for n in p["notes"])


def test_plan_copilot(tmp_path):
    root = make_bridge(tmp_path)
    p = run_plan("copilot", root, make_repo(tmp_path / "w"), tmp_path)
    assert p["argv"][:3] == ["copilot", "--add-dir", str(root)]
    d = Path(p["env"]["COPILOT_CUSTOM_INSTRUCTIONS_DIRS"])
    assert "Bridge attached" in (d / ".github/instructions/bridge.instructions.md").read_text()


def test_plan_writes_nothing_into_the_repo(tmp_path):
    root = make_bridge(tmp_path)
    repo = make_repo(tmp_path / "w")
    for tool in ("claude", "codex", "copilot"):
        run_plan(tool, root, repo, tmp_path)
    out = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, text=True).stdout
    assert out == ""


def test_plan_refuses_when_not_normal(tmp_path):
    root = make_bridge(tmp_path, branch="main")
    with pytest.raises(ba.Refused):
        run_plan("claude", root, make_repo(tmp_path / "w"), tmp_path)


def test_plan_refuses_attaching_the_bridge_to_itself(tmp_path):
    root = make_bridge(tmp_path)
    with pytest.raises(ba.Refused):
        run_plan("claude", root, root, tmp_path)


def test_plan_unknown_tool(tmp_path):
    root = make_bridge(tmp_path)
    with pytest.raises(ba.Refused):
        run_plan("vim", root, make_repo(tmp_path / "w"), tmp_path)


# ---------------------------------------------------------------- replay-hooks

def test_replay_runs_the_bridges_own_hooks_with_the_root_as_project_dir(tmp_path, monkeypatch):
    root = make_bridge(tmp_path)
    log = tmp_path / "hook.log"
    monkeypatch.setenv("HOOKLOG", str(log))
    monkeypatch.setenv("BRIDGE_ROOT", str(root))
    rc = ba.replay_hooks(root, "SessionStart", '{"source": "startup"}')
    assert rc == 0
    assert log.read_text().strip() == f"start-{root}"


def test_replay_ignores_other_events(tmp_path, monkeypatch):
    root = make_bridge(tmp_path)
    log = tmp_path / "hook.log"
    monkeypatch.setenv("HOOKLOG", str(log))
    assert ba.replay_hooks(root, "SessionEnd", "{}") == 0
    assert not log.exists()


# ---------------------------------------------------------------- CLI

def test_cli_check_exit_codes(tmp_path, capsys):
    root = make_bridge(tmp_path)
    assert ba.main(["check", "--root", str(root)]) == 0
    main_root = make_bridge(tmp_path / "b2", branch="main")
    assert ba.main(["check", "--root", str(main_root)]) == 3


def test_cli_slice_prints_the_text(tmp_path, capsys):
    root = make_bridge(tmp_path)
    repo = make_repo(tmp_path / "w")
    assert ba.main(["slice", "--root", str(root), "--cwd", str(repo)]) == 0
    assert "Bridge attached" in capsys.readouterr().out


def test_bridge_run_executes_in_the_root(tmp_path):
    run = Path(__file__).resolve().parents[2] / "bin" / "bridge-run"
    out = subprocess.run([str(run), "pwd", "-P"], cwd=tmp_path, capture_output=True, text=True)
    assert out.returncode == 0
    assert Path(out.stdout.strip()) == run.parents[1].resolve()


# ---------------------------------------------------------------- review 2026-11-27

def test_short_folder_name_does_not_leak_private_items(tmp_path):
    inbox = [{"id": "p", "state": "open", "summary": "Bank mail about the loan", "area": "Private"},
             {"id": "q", "state": "open", "summary": "Doctor appointment", "area": "Family"},
             {"id": "r", "state": "open", "summary": "ai: rotate the token", "area": "Work"}]
    root = make_bridge(tmp_path, inbox=inbox)
    text = ba.render(root, make_repo(tmp_path / "ai"))
    assert "Bank mail" not in text and "Doctor" not in text
    assert "rotate the token" in text


def test_log_rows_match_the_context_cell_not_a_substring(tmp_path):
    root = make_bridge(tmp_path)
    (root / "work/log.md").write_text(
        "## Fri 27.11\n\n| Time | Type | Context | What |\n|---|---|---|---|\n"
        "| 2026-11-27 09:00 | x | widget-tools | other tool |\n"
        "| 2026-11-27 10:00 | x | acme / widget | the shared one |\n")
    rows = ba.log_rows(root, "widget")
    assert any("the shared one" in r for r in rows)
    assert not any("other tool" in r for r in rows)


def test_log_rows_survive_the_year_boundary(tmp_path):
    root = make_bridge(tmp_path)
    (root / "work/log.md").write_text(
        "## Fri 01.01\n\n| 2027-01-01 08:00 | x | widget | new year row |\n\n"
        "## Thu 31.12\n\n| 2026-12-31 20:00 | x | widget | last year row |\n\n"
        "## Sun 20.12\n\n| 2026-12-20 10:00 | x | widget | old row |\n")
    rows = ba.log_rows(root, "widget")
    assert any("new year row" in r for r in rows)
    assert any("last year row" in r for r in rows)
    assert not any("old row" in r for r in rows)


def write_settings(root, name, hooks):
    path = root / ".claude" / name
    path.parent.mkdir(exist_ok=True)
    data = json.loads(path.read_text()) if path.exists() else {}
    data["hooks"] = hooks
    path.write_text(json.dumps(data))


def test_replay_star_matcher_and_bad_regex(tmp_path, monkeypatch, capsys):
    root = make_bridge(tmp_path)
    log = tmp_path / "hook.log"
    monkeypatch.setenv("HOOKLOG", str(log))
    write_settings(root, "settings.local.json", {"SessionStart": [
        {"matcher": "*", "hooks": [{"type": "command", "command": "echo star >> \"$HOOKLOG\""}]},
        {"matcher": "(", "hooks": [{"type": "command", "command": "echo bad >> \"$HOOKLOG\""}]},
    ]})
    assert ba.replay_hooks(root, "SessionStart", '{"source": "startup"}') == 0
    assert log.read_text().split() == ["star"]


def test_replay_matcher_field_per_event(tmp_path, monkeypatch):
    root = make_bridge(tmp_path)
    log = tmp_path / "hook.log"
    monkeypatch.setenv("HOOKLOG", str(log))
    write_settings(root, "settings.local.json", {"PreCompact": [
        {"matcher": "manual", "hooks": [{"type": "command", "command": "echo manual >> \"$HOOKLOG\""}]}]})
    ba.replay_hooks(root, "PreCompact", '{"trigger": "auto"}')
    assert not log.exists()
    ba.replay_hooks(root, "PreCompact", '{"trigger": "manual"}')
    assert log.read_text().split() == ["manual"]


def test_replay_runs_in_the_bridge_root(tmp_path, monkeypatch):
    root = make_bridge(tmp_path)
    log = tmp_path / "hook.log"
    monkeypatch.setenv("HOOKLOG", str(log))
    monkeypatch.chdir(make_repo(tmp_path / "w"))
    write_settings(root, "settings.local.json", {"Stop": [
        {"hooks": [{"type": "command", "command": "pwd -P >> \"$HOOKLOG\""}]}]})
    ba.replay_hooks(root, "Stop", "{}")
    assert Path(log.read_text().strip()) == root.resolve()


def test_replay_passes_exit_2_and_dedupes(tmp_path, monkeypatch, capsys):
    root = make_bridge(tmp_path)
    log = tmp_path / "hook.log"
    monkeypatch.setenv("HOOKLOG", str(log))
    same = {"hooks": [{"type": "command", "command": "echo once >> \"$HOOKLOG\""}]}
    write_settings(root, "settings.json", {"Stop": [same]})
    write_settings(root, "settings.local.json", {"Stop": [same, {"hooks": [
        {"type": "command", "command": "echo blocked >&2; exit 2"}]}]})
    assert ba.replay_hooks(root, "Stop", "{}") == 2
    assert log.read_text().split() == ["once"]
    assert "blocked" in capsys.readouterr().err


def test_replay_forwards_stderr_of_a_failing_hook(tmp_path, capsys):
    root = make_bridge(tmp_path)
    write_settings(root, "settings.local.json", {"Stop": [{"hooks": [
        {"type": "command", "command": "echo broken >&2; exit 1"}]}]})
    assert ba.replay_hooks(root, "Stop", "{}") == 0
    assert "broken" in capsys.readouterr().err


def test_replay_merges_json_outputs(tmp_path, capsys):
    root = make_bridge(tmp_path)
    one = json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "A1"}})
    two = json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "B2"}})
    write_settings(root, "settings.local.json", {"SessionStart": [{"hooks": [
        {"type": "command", "command": f"echo '{one}'"},
        {"type": "command", "command": f"echo '{two}'"},
        {"type": "command", "command": "echo plain C3"}]}]})
    ba.replay_hooks(root, "SessionStart", '{"source": "startup"}')
    out = json.loads(capsys.readouterr().out)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "A1" in ctx and "B2" in ctx and "C3" in ctx


def test_plugin_timeout_is_the_sum_and_paths_are_shell_quoted(tmp_path):
    root = make_bridge(tmp_path)
    write_settings(root, "settings.local.json", {"Stop": [{"hooks": [
        {"type": "command", "command": "true first", "timeout": 30},
        {"type": "command", "command": "true second", "timeout": 40}]}]})
    p = run_plan("claude", root, make_repo(tmp_path / "w"), tmp_path)
    plugin = Path(p["argv"][p["argv"].index("--plugin-dir") + 1])
    stop = json.loads((plugin / "hooks/hooks.json").read_text())["hooks"]["Stop"][0]["hooks"][0]
    assert stop["timeout"] >= 70
    import shlex
    assert shlex.quote(str(root)) in stop["command"]
    assert '"' not in stop["command"]


def test_exec_with_a_missing_tool_exits_3(tmp_path, monkeypatch, capsys):
    root = make_bridge(tmp_path)
    repo = make_repo(tmp_path / "w")
    empty = tmp_path / "emptybin"
    empty.mkdir()
    import shutil
    (empty / "git").symlink_to(shutil.which("git"))
    monkeypatch.setenv("PATH", str(empty))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert ba.main(["exec", "claude", "--root", str(root), "--cwd", str(repo)]) == 3
    assert "not found" in capsys.readouterr().err


def test_bridge_run_through_a_symlink(tmp_path):
    run = Path(__file__).resolve().parents[2] / "bin" / "bridge-run"
    link = tmp_path / "bridge-run"
    link.symlink_to(run)
    out = subprocess.run([str(link), "pwd", "-P"], cwd=tmp_path, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert Path(out.stdout.strip()) == run.parents[1].resolve()


def test_render_trims_sections_before_cutting(tmp_path):
    many = [{"id": f"i{n}", "state": "open", "summary": f"widget item {n} " + "x" * 300} for n in range(80)]
    root = make_bridge(tmp_path, inbox=many)
    repo = make_repo(tmp_path / "w", origin="https://github.com/acme/widget")
    text = ba.render(root, repo, max_chars=4000)
    assert text.rstrip().endswith(")") or "more about `widget`" in text
    assert "more about `widget`" in text
