"""bin/setup warns about a Claude Code too old to load AGENTS.md, never fails.

This repo ships no CLAUDE.md, so a Claude Code below 2.1.281 starts with no
instructions at all. A CLAUDE.md or CLAUDE.local.md in a parent folder has
the same effect on any version: Claude Code loads only those. bin/setup warns
in both cases and leaves its exit code alone, because Claude Code is one of
several supported tools.

Every case runs a copy of bin/setup inside a tmp git repo (the script cds to
its own parent and would otherwise arm hooks in the real checkout), with PATH
reduced to a shim of the tools it calls, so the host's PyYAML or claude never
leak into the result.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ["bash", "python3", "git", "sed", "head", "ln", "mkdir", "rm", "chmod",
         "dirname", "uname", "cat", "env"]


@pytest.fixture()
def shim(tmp_path: Path) -> Path:
    d = tmp_path / "shim"
    d.mkdir()
    for tool in TOOLS:
        found = shutil.which(tool)
        if found:
            (d / tool).symlink_to(found)
    return d


def make_repo(base: Path) -> Path:
    repo = base / "repo"
    (repo / "bin").mkdir(parents=True)
    (repo / "skills" / "bridge-onboard").mkdir(parents=True)
    (repo / "scripts" / "hooks").mkdir(parents=True)
    shutil.copy2(ROOT / "bin" / "setup", repo / "bin" / "setup")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    return repo


def fake_claude(base: Path, output: str) -> Path:
    d = base / "fake"
    d.mkdir()
    script = d / "claude"
    script.write_text(f"#!/bin/sh\necho '{output}'\n", encoding="utf-8")
    script.chmod(0o755)
    return d


def run_setup(repo: Path, path: str) -> subprocess.CompletedProcess:
    env = {"PATH": path, "HOME": str(repo.parent), "LC_ALL": "C"}
    return subprocess.run([str(repo / "bin" / "setup")], cwd=repo, env=env,
                          capture_output=True, text=True, timeout=60)


def claude_lines(out: str) -> list[str]:
    return [line for line in out.splitlines() if "Claude Code" in line]


CASES = [
    ("2.1.314 (Claude Code)", "OK  Claude Code 2.1.314 supports AGENTS.md (default option)"),
    ("2.1.281 (Claude Code)", "OK  Claude Code 2.1.281 supports AGENTS.md (default option)"),
    ("2.10.0 (Claude Code)", "OK  Claude Code 2.10.0 supports AGENTS.md (default option)"),
    ("2.1.280 (Claude Code)", "WARN Claude Code 2.1.280 is older than 2.1.281"),
    ("garbage", "WARN Could not read the Claude Code version"),
]


@pytest.mark.parametrize("output,expected", CASES)
def test_claude_version_line_and_unchanged_exit_code(tmp_path, shim, output, expected):
    repo = make_repo(tmp_path)
    baseline = run_setup(repo, str(shim))
    assert claude_lines(baseline.stdout) == [], baseline.stdout

    fake = fake_claude(tmp_path, output)
    result = run_setup(repo, f"{shim}{os.pathsep}{fake}")
    lines = claude_lines(result.stdout)
    assert len(lines) == 1, result.stdout + result.stderr
    assert lines[0].startswith(expected), lines[0]
    assert result.returncode == baseline.returncode, result.stdout + result.stderr


def test_parent_claude_md_warns_without_changing_the_exit_code(tmp_path, shim):
    outer = tmp_path / "outer"
    outer.mkdir()
    repo = make_repo(outer)
    baseline = run_setup(repo, str(shim))
    assert "will not load AGENTS.md here" not in baseline.stdout

    (outer / "CLAUDE.md").write_text("# parent\n", encoding="utf-8")
    (tmp_path / "CLAUDE.local.md").write_text("# grandparent\n", encoding="utf-8")
    result = run_setup(repo, str(shim))
    warns = [line for line in result.stdout.splitlines()
             if line.startswith("WARN") and "will not load AGENTS.md here" in line]
    assert any(str(outer / "CLAUDE.md") in w for w in warns), result.stdout
    assert any(str(tmp_path / "CLAUDE.local.md") in w for w in warns), result.stdout
    assert result.returncode == baseline.returncode
