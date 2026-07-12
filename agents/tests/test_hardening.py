"""Public-endpoint hardening of the claude -p runner argv (hermetic).

``--permission-mode acceptEdits`` auto-allows engine-classified read-only shell
INDEPENDENT of ``--allowedTools``, so the runner ships an explicit deny-list
backstop and loads project-only settings. These lock that argv so a refactor
can't silently widen an internet-facing agent. No subprocess is spawned — only
argv assembly is exercised.
"""
from __future__ import annotations

from _runtime.runner import _DISALLOWED_TOOLS, SubprocessClaudeRunner


def _runner():
    return SubprocessClaudeRunner(
        binary="claude",
        model="sonnet",
        system_prompt="PERSONA",
        working_dir="/tmp",
        allowed_tools="Read,Glob,Grep",
    )


def test_denylist_blocks_known_exfil_and_recon_binaries():
    for binary in (
        "curl", "wget", "nc", "ssh", "scp", "security", "sqlite3",
        "base64", "openssl", "git", "osascript", "pbpaste", "defaults", "cat",
    ):
        assert f"Bash({binary}:*)" in _DISALLOWED_TOOLS, f"{binary} must be denied"


def test_python3_stays_allowed_for_scoped_tools():
    # Scoped instance tools run as `python3 <abs>/tool.py`; python3 must NOT be denied.
    assert "Bash(python3:*)" not in _DISALLOWED_TOOLS


def test_build_cmd_hardens_public_endpoint():
    cmd = _runner()._build_cmd("hello", stream=False)
    assert "--disallowedTools" in cmd
    deny = cmd[cmd.index("--disallowedTools") + 1]
    assert "Bash(curl:*)" in deny and "Bash(security:*)" in deny
    # project-only settings — never widen via the host user's ~/.claude
    assert cmd[cmd.index("--setting-sources") + 1] == "project"
    assert cmd[cmd.index("--permission-mode") + 1] == "acceptEdits"
