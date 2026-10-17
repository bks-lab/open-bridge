"""The shell filled from the repo's DESIGN.md defines every token it and the simulation use."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
REPO = SKILL.parents[1]


def _vars(text: str) -> tuple[set[str], set[str]]:
    defined = set(re.findall(r"(--[\w-]+)\s*:", text))
    used = set(re.findall(r"var\((--[\w-]+)\s*[,)]", text))
    return defined, used


def test_filled_shell_leaves_no_token_undefined(tmp_path):
    out = tmp_path / "shell.html"
    subprocess.run([sys.executable, str(SKILL / "scripts" / "design-to-css.py"), str(REPO / "DESIGN.md"),
                    "--shell", "--out", str(out)], check=True, capture_output=True)
    text = out.read_text("utf-8") + (SKILL / "assets" / "simulation.css").read_text("utf-8")
    defined, used = _vars(text)
    assert not (used - defined), sorted(used - defined)


def test_filling_twice_does_not_stack_generated_blocks(tmp_path):
    first, second = tmp_path / "a.html", tmp_path / "b.html"
    script = str(SKILL / "scripts" / "design-to-css.py")
    subprocess.run([sys.executable, script, str(REPO / "DESIGN.md"), "--shell", "--out", str(first)],
                   check=True, capture_output=True)
    subprocess.run([sys.executable, script, str(REPO / "DESIGN.md"), "--shell", str(first), "--out", str(second)],
                   check=True, capture_output=True)
    assert second.read_text("utf-8").count("generated from DESIGN.md") == 1
