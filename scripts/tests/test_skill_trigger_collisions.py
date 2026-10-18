#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Two CORE skills must not claim the same quoted trigger.

Every CORE skill ships to every installation, and the harness picks a skill by
matching what the user said against the `Trigger:` list in each description.
When two of them quote the same phrase, which one runs depends on wording and
model, and the choice cannot be reproduced. The cockpit once listed a bare
"dashboard" while the `dashboard` skill owned "/dashboard" and "show dashboard".

`scripts/validate-skill-scope.py` is the gate (it already reads every skill's
frontmatter), so these tests drive it.

Run: python3 -m pytest scripts/tests/test_skill_trigger_collisions.py -q
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


def _skill(root: pathlib.Path, name: str, scope: str, triggers: str) -> None:
    d = root / name
    d.mkdir()
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: >-\n  Does {name}. Trigger: {triggers}.\n"
        f"metadata:\n  scope: {scope}\n---\n\n# {name}\n",
        encoding="utf-8",
    )


def _description(name: str) -> str:
    vss = _load()
    fm = vss.frontmatter(REPO / "skills" / name / "SKILL.md")
    return str(fm.get("description", ""))


def test_quoted_triggers_parses_the_trigger_list():
    vss = _load()
    desc = 'Does x. Not y. Trigger: "/x", "Open X", "x --all".'
    assert vss.quoted_triggers(desc) == ["/x", "Open X", "x --all"]


def test_quoted_triggers_ignores_quotes_before_the_trigger_list():
    vss = _load()
    desc = 'Reads "config" files. Trigger: "/x".'
    assert vss.quoted_triggers(desc) == ["/x"]


def test_two_core_skills_with_the_same_trigger_fail(tmp_path, monkeypatch):
    vss = _load()
    _skill(tmp_path, "alpha", "core", '"/alpha", "Dashboard"')
    _skill(tmp_path, "beta", "core", '"/beta", "dashboard"')
    monkeypatch.setattr(vss, "SKILLS_DIR", tmp_path)
    _, errors = vss.collect()
    hits = [e for e in errors if "dashboard" in e]
    assert hits, f"expected a trigger collision, got {errors}"
    assert "alpha" in hits[0] and "beta" in hits[0]


def test_a_shared_trigger_outside_core_is_not_a_collision(tmp_path, monkeypatch):
    """Only CORE ships everywhere; an org or user skill may shadow on purpose."""
    vss = _load()
    _skill(tmp_path, "alpha", "core", '"/alpha", "dashboard"')
    _skill(tmp_path, "beta", "user", '"/beta", "dashboard"')
    monkeypatch.setattr(vss, "SKILLS_DIR", tmp_path)
    _, errors = vss.collect()
    assert errors == []


def test_the_real_tree_has_no_core_trigger_collision():
    vss = _load()
    _, errors = vss.collect()
    collisions = [e for e in errors if "trigger" in e]
    assert collisions == []


def test_cockpit_does_not_claim_the_bare_dashboard_trigger():
    vss = _load()
    triggers = [t.casefold() for t in vss.quoted_triggers(_description("cockpit"))]
    assert "dashboard" not in triggers


def test_cockpit_and_dashboard_name_each_other():
    assert "/dashboard" in _description("cockpit").split("Trigger:")[0]
    assert "/cockpit" in _description("dashboard").split("Trigger:")[0]
