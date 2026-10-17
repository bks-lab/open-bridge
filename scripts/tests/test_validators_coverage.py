#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Coverage tests for the two scope validators.

Both validators were passing while looking past real drift, because each globs
one level less than the tree it guards:

  * `validate-skill-scope.py` globs `skills/*/SKILL.md`, so a skill DIRECTORY
    with no SKILL.md is invisible — it reported "92 skills valid" against 93
    directories. The missing one routed to `core` through the router's fail-open
    default and carried customer names.
  * `validate-bridge.py` globs `rules/*.md` non-recursively, so all of
    `rules/org/**`, `rules/personal/**`, `rules/user/**` — 17 files — were never
    checked for folder↔frontmatter agreement, the exact thing that surface exists
    to enforce.

A validator that cannot see a file cannot guard it. These tests assert the
coverage itself, not just the verdict.

Run: python3 -m pytest scripts/tests/test_validators_coverage.py -q
"""
from __future__ import annotations

import importlib.util
import pathlib
import re
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    assert spec and spec.loader, f"cannot load {rel}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# validate-skill-scope.py — every skill DIRECTORY must be accounted for
# ---------------------------------------------------------------------------
def _skill_dirs() -> list[pathlib.Path]:
    return sorted(d for d in (REPO / "skills").iterdir()
                  if d.is_dir() and not d.name.startswith("_"))


def test_every_skill_directory_has_a_skill_md():
    """A dir without SKILL.md has no declared tier — the router must not guess."""
    orphans = [d.name for d in _skill_dirs() if not (d / "SKILL.md").exists()]
    assert not orphans, (
        f"skill directories without SKILL.md: {orphans}. They declare no tier, so "
        "every file in them falls through the frontmatter read. Give each one a "
        "SKILL.md, or remove the directory."
    )


def test_validator_counts_every_directory_not_just_skill_md_files():
    """The reported count must match the directory count, or drift hides in the gap."""
    proc = subprocess.run(
        [sys.executable, "scripts/validate-skill-scope.py"],
        cwd=REPO, capture_output=True, text=True,
    )
    combined = proc.stdout + proc.stderr
    m = re.search(r"(\d+)\s+skills valid", combined)
    if not m:
        pytest.fail(f"could not parse the validator's count from:\n{combined}")
    assert int(m.group(1)) == len(_skill_dirs()), (
        f"validator counted {m.group(1)} but there are {len(_skill_dirs())} skill "
        "directories. It globs */SKILL.md, so a directory without one is invisible."
    )


# ---------------------------------------------------------------------------
# validate-bridge.py — the rules/ surface must cover its tier subfolders
# ---------------------------------------------------------------------------
TIER_FOLDERS = ("org", "personal", "user")


def _tiered_rule_files() -> list[pathlib.Path]:
    out: list[pathlib.Path] = []
    for tier in TIER_FOLDERS:
        out.extend(sorted((REPO / "rules" / tier).glob("*.md")))
    return out


def test_rules_surface_globs_the_tier_subfolders():
    vb = _load("validate_bridge", "scripts/validate-bridge.py")
    surface = next(s for s in vb.MD_SCOPE_SURFACES if s["name"] == "rules")
    covered = {p.resolve() for p in vb.discover_md_instances(surface)}
    missing = [
        str(p.relative_to(REPO)) for p in _tiered_rule_files()
        if p.resolve() not in covered
    ]
    assert not missing, (
        f"{len(missing)} tiered rule files are outside the validator's glob "
        f"(first few: {missing[:4]}). rules/*.md is not recursive, so rules/org, "
        "rules/personal and rules/user are unguarded — the folder IS the tier there."
    )


def _frontmatter_scope(path: pathlib.Path) -> str | None:
    for line in path.read_text(encoding="utf-8").splitlines()[:40]:
        m = re.match(r"^scope:\s*(\S+)", line)
        if m:
            return m.group(1)
    return None


@pytest.mark.parametrize(
    "path", [p for p in _tiered_rule_files()], ids=lambda p: str(p.name)
)
def test_tiered_rule_frontmatter_matches_its_folder(path: pathlib.Path):
    """AGENTS.md § Rules: the folder is the tier, and `scope:` must agree with it."""
    folder = path.parent.name
    declared = _frontmatter_scope(path)
    assert declared is not None, f"{path.relative_to(REPO)} has no top-level `scope:`"
    assert declared == folder, (
        f"{path.relative_to(REPO)} sits in rules/{folder}/ but declares "
        f"scope: {declared}. The folder routes it, the frontmatter is the backstop — "
        "they must agree or one of them is lying to the next reader."
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
