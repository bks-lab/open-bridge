#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""A long SKILL.md or a long description is warned about, never failed.

The description is resident: the harness lists it in every session and every
sub-agent dispatch, so its bytes come out of the `listing:skills` cap. The
SKILL.md body loads whenever the skill runs, so a body that inlines its whole
command reference pays for all of it on every trigger. Both grow one edit at a
time, and both are a judgement call, so the gate in
`scripts/validate-skill-scope.py` warns and keeps exit 0.

Run: python3 -m pytest scripts/tests/test_skill_size_warnings.py -q
"""
from __future__ import annotations

import importlib.util
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location(
        "validate_skill_scope", REPO / "scripts/validate-skill-scope.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _skill(root: pathlib.Path, name: str, description: str, body_lines: int = 5) -> None:
    d = root / name
    d.mkdir()
    head = (
        f"---\nname: {name}\ndescription: >-\n  {description}\n"
        f"metadata:\n  scope: core\n---\n"
    )
    used = head.count("\n")
    body = "".join(f"line {i}\n" for i in range(max(body_lines - used, 0)))
    (d / "SKILL.md").write_text(head + body, encoding="utf-8")


def test_the_limits_are_declared_constants():
    vss = _load()
    assert vss.SKILL_MD_MAX_LINES == 300
    assert vss.DESCRIPTION_MAX_BYTES == 380


def test_a_skill_within_both_limits_draws_no_warning(tmp_path, monkeypatch):
    vss = _load()
    _skill(tmp_path, "small", "x" * 380, body_lines=300)
    monkeypatch.setattr(vss, "SKILLS_DIR", tmp_path)
    assert vss.size_warnings() == []


def test_a_long_skill_md_is_warned_with_its_line_count(tmp_path, monkeypatch):
    vss = _load()
    _skill(tmp_path, "long", "short", body_lines=301)
    monkeypatch.setattr(vss, "SKILLS_DIR", tmp_path)
    warnings = vss.size_warnings()
    assert len(warnings) == 1 and "long" in warnings[0] and "301" in warnings[0]
    assert "references/" in warnings[0]


def test_a_long_description_is_warned_in_bytes_not_characters(tmp_path, monkeypatch):
    vss = _load()
    # 190 two-byte characters: 190 characters, 380 bytes. One more tips it.
    _skill(tmp_path, "umlaut", "ä" * 190)
    _skill(tmp_path, "over", "ä" * 191)
    monkeypatch.setattr(vss, "SKILLS_DIR", tmp_path)
    warnings = vss.size_warnings()
    assert len(warnings) == 1 and "over" in warnings[0] and "382" in warnings[0]


def test_the_folded_description_is_measured_as_the_listing_carries_it(tmp_path, monkeypatch):
    """One line, whitespace collapsed: the fold's newlines and indent are not paid."""
    vss = _load()
    d = tmp_path / "folded"
    d.mkdir()
    lines = "\n".join("  " + "y" * 40 for _ in range(9))  # 9*40 + 8 spaces = 368
    (d / "SKILL.md").write_text(
        f"---\nname: folded\ndescription: >-\n{lines}\nmetadata:\n  scope: core\n---\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(vss, "SKILLS_DIR", tmp_path)
    assert vss.size_warnings() == []


def test_warnings_never_fail_the_gate(tmp_path, monkeypatch, capsys):
    vss = _load()
    _skill(tmp_path, "long", "z" * 500, body_lines=400)
    monkeypatch.setattr(vss, "SKILLS_DIR", tmp_path)
    monkeypatch.setattr("sys.argv", ["validate-skill-scope.py", "--check"])
    assert vss.main() == 0
    err = capsys.readouterr().err
    assert "warning" in err and "long" in err
