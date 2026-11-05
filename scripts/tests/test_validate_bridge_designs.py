#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""validate-bridge's `design` surface: a design is Markdown, its schema holds the front matter.

The validator is handed each design's front matter as a temporary .yaml copy,
and every message it prints, on stdout or stderr, must name the Markdown file
a person edits, never the temporary copy.

Run: python3 -m pytest scripts/tests/test_validate_bridge_designs.py -q
"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("validate_bridge", REPO / "scripts" / "validate-bridge.py")
vb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vb)

SURFACE = next(s for s in vb.SURFACES if s["name"] == "design")


def _tree(tmp_path: Path, designs: dict[str, str]) -> Path:
    folder = tmp_path / "identity" / "designs"
    folder.mkdir(parents=True)
    shutil.copy(REPO / "identity" / "designs" / "_schema.yaml", folder / "_schema.yaml")
    for name, text in designs.items():
        (folder / name).write_text(text, encoding="utf-8")
    return tmp_path


GOOD = '---\nversion: alpha\nscope: user\nname: good\ndescription: d\ncolors:\n  primary: "#000000"\n---\n# x\n'
BAD = "---\nversion: alpha\nscope: user\ndescription: d\n---\n# x\n"


def test_the_surface_reads_front_matter_of_markdown_designs():
    assert SURFACE["instances"] == "identity/designs/*.md" and SURFACE.get("frontmatter") is True


def test_front_matter_copy_is_the_block_alone(tmp_path):
    md = tmp_path / "brand.md"
    md.write_text(GOOD + "\nprose: not: yaml: at all\n", encoding="utf-8")
    copy = vb._front_matter_file(md, tmp_path)
    assert copy.name == "brand.yaml" and "prose" not in copy.read_text(encoding="utf-8")


def _validator():
    found = shutil.which("check-jsonschema")
    if not found:
        pytest.skip("check-jsonschema is not installed")
    return found


def test_a_design_without_name_or_colors_fails_and_is_named(tmp_path, monkeypatch, capsys):
    validator = _validator()
    root = _tree(tmp_path, {"good.md": GOOD, "bad.md": BAD, "_template.md": BAD})
    monkeypatch.setattr(vb, "REPO_ROOT", root)
    passed, failed = vb.validate_surface(SURFACE, validator=validator)
    out = capsys.readouterr()
    assert (passed, failed) == (1, 1)
    text = out.out + out.err
    assert "identity/designs/bad.md" in text and "bad.yaml" not in text, text


def test_stderr_names_the_markdown_file_too(tmp_path, monkeypatch, capsys):
    """A copy that does not parse is reported on stderr; that message names the .md as well."""
    validator = _validator()
    root = _tree(tmp_path, {"broken.md": "---\nname: [unclosed\n---\n"})
    monkeypatch.setattr(vb, "REPO_ROOT", root)
    vb.validate_surface(SURFACE, validator=validator)
    out = capsys.readouterr()
    assert "broken.yaml" not in out.out + out.err, out.out + out.err


def test_a_design_named_default_is_refused(tmp_path, monkeypatch, capsys):
    """`design_ref: default` opts out to the root DESIGN.md, so no design may take that name."""
    root = _tree(tmp_path, {"default.md": GOOD})
    monkeypatch.setattr(vb, "REPO_ROOT", root)
    passed, failed = vb.validate_surface(SURFACE, validator=shutil.which("check-jsonschema") or "true")
    out = capsys.readouterr()
    assert failed == 1 and "identity/designs/default.md" in out.out + out.err and "reserved" in out.out + out.err
