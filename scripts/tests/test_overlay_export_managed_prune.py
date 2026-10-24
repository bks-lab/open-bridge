#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Regression: the exporter must not delete the overlay's OWN materialized files.

Measured against a live pair (an instance and its org overlay): a
`--scope org --dry-run` export scheduled 35 files for deletion from `tree/`, among
them the complete `references/` and `templates/` of two org skills, plus an org
rule.

The loop is closed and vicious. `/overlay` materializes overlay content DOWN into the
consuming bridge and records each file in `overlays.lock.yaml`, excluding it from git
via `.git/info/exclude` (a fork of a public repo is itself public). The exporter asks
`git check-ignore` to learn what git refuses to track — the guard that once caught a
live `.env` and a live Elastic key. Overlay-managed files answer "ignored", so the
exporter never discovers them, and every mirror file it did not discover counts as
stale. The tool meant to BUILD the mirror deletes the half of it that came from the
mirror in the first place.

A file may only be pruned when it is genuinely orphaned: out of scope AND not carried
in the lock as overlay-managed.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "scripts" / "overlay-export.py"


@pytest.fixture(scope="module")
def oe():
    spec = importlib.util.spec_from_file_location("overlay_export", MODULE_PATH)
    assert spec and spec.loader
    m = importlib.util.module_from_spec(spec)
    sys.modules["overlay_export"] = m
    spec.loader.exec_module(m)
    return m


def _w(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


@pytest.fixture
def pair(tmp_path: Path):
    """A bridge that CONSUMES an overlay, plus that overlay's source repo."""
    bridge = tmp_path / "bridge"
    overlay = tmp_path / "overlay"

    # authored org content — discovered normally
    _w(bridge / "workflow" / "contexts" / "acme.yaml", "schema_version: 1\nscope: org\nx: 1\n")

    # overlay-managed content: present on disk, git-ignored via .git/info/exclude,
    # and carried in overlays.lock.yaml. This is what must survive a prune.
    managed = "skills/acme-logging/references/keys.md"
    _w(bridge / managed, "# keys\n")
    _w(bridge / "skills" / "acme-logging" / "SKILL.md",
       "---\nname: acme-logging\nmetadata:\n  scope: org\n---\n\n# skill\n")

    subprocess.run(["git", "init", "-q"], cwd=bridge, check=True)
    # gone.yaml was this bridge's once (its history says so), then removed: the
    # one genuine orphan. Without that evidence it would be foreign and kept.
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    git = ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
           "-c", "commit.gpgsign=false"]
    _w(bridge / "workflow" / "contexts" / "gone.yaml", "schema_version: 1\nscope: org\n")
    subprocess.run([*git, "add", "workflow"], cwd=bridge, check=True, env=env)
    subprocess.run([*git, "commit", "-q", "-m", "seed"], cwd=bridge, check=True, env=env)
    subprocess.run([*git, "rm", "-q", "workflow/contexts/gone.yaml"], cwd=bridge,
                   check=True, env=env)
    subprocess.run([*git, "commit", "-q", "-m", "drop"], cwd=bridge, check=True, env=env)
    (bridge / ".git" / "info").mkdir(parents=True, exist_ok=True)
    (bridge / ".git" / "info" / "exclude").write_text(f"/{managed}\n", encoding="utf-8")

    _w(bridge / "overlays.lock.yaml",
       "overlays:\n"
       "  acme:\n"
       "    url: git@example.com:org/overlay.git\n"
       "    files:\n"
       f"    - src: tree/{managed}\n"
       f"      dest: {managed}\n"
       "      source_sha256: deadbeef\n"
       "      materialized_sha256: deadbeef\n")

    # the mirror already holds the managed file AND one genuinely orphaned file
    _w(overlay / "tree" / managed, "# keys\n")
    _w(overlay / "tree" / "workflow" / "contexts" / "gone.yaml", "schema_version: 1\nscope: org\n")
    return bridge, overlay, managed


def test_overlay_managed_file_is_not_pruned(oe, pair):
    bridge, overlay, managed = pair
    plan = oe.export_overlay(str(bridge), str(overlay), scope="org", dry_run=True)
    assert managed not in plan["pruned"], (
        "the exporter would delete the overlay's own materialized file: "
        f"{plan['pruned']}")


def test_a_genuinely_orphaned_mirror_file_is_still_pruned(oe, pair):
    """The guard must not turn the prune off wholesale."""
    bridge, overlay, _ = pair
    plan = oe.export_overlay(str(bridge), str(overlay), scope="org", dry_run=True)
    assert "workflow/contexts/gone.yaml" in plan["pruned"]


def test_managed_rule_keeps_its_manifest_entry(oe, pair):
    """files[] describes the MIRROR, not just what was discovered this run.

    An overlay-managed rule lives in the mirror but is invisible to discovery, so
    building files[] from the discovered set alone drops its `kind: rule` entry —
    measured on a live pair as 6 -> 5, with one org rule falling
    out. infer_kind() would derive the same kind, so nothing breaks at materialize
    time, but the contract would churn on every export and understate the mirror.
    """
    bridge, overlay, _ = pair
    rule = "rules/org/example-rule.md"
    _w(bridge / rule, "---\nscope: org\n---\n\n# rule\n")
    _w(overlay / "tree" / rule, "---\nscope: org\n---\n\n# rule\n")
    lock = bridge / "overlays.lock.yaml"
    lock.write_text(lock.read_text(encoding="utf-8") +
                    f"    - src: tree/{rule}\n"
                    f"      dest: {rule}\n"
                    "      source_sha256: cafe\n"
                    "      materialized_sha256: cafe\n", encoding="utf-8")
    (bridge / ".git" / "info" / "exclude").write_text(
        (bridge / ".git" / "info" / "exclude").read_text(encoding="utf-8") + f"/{rule}\n",
        encoding="utf-8")
    plan = oe.export_overlay(str(bridge), str(overlay), scope="org", dry_run=True)
    dests = [e["dest"] for e in plan["files_entries"]]
    assert rule in dests, f"managed rule lost its files[] entry: {dests}"


def test_dry_run_touches_nothing(oe, pair):
    bridge, overlay, managed = pair
    oe.export_overlay(str(bridge), str(overlay), scope="org", dry_run=True)
    assert (overlay / "tree" / managed).exists()
    assert (overlay / "tree" / "workflow" / "contexts" / "gone.yaml").exists()
