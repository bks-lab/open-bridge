#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Regression: the export prune must not delete what the export never wrote.

Measured on a live consumer/overlay pair: a `--scope org --dry-run` planned
"stale, would prune" for `references/<file>.md` inside an org skill. The skill
folder is excluded in the consumer through `.git/info/exclude`, so discovery
skips it, and a colleague had added the reference file straight to `tree/` in
the overlay. The exporter read "not discovered this run" as "stale" and would
have deleted a colleague's work from the shared overlay.

A mirror file may only be pruned when this bridge once owned it: the consumer's
git history has the path, and the export did not skip it on purpose (gitignored,
`.git/info/exclude`, `never_promote`, or the export's own exclusions). Anything
else is FOREIGN: reported as "foreign, kept" in the plan and deleted only with
`--prune-foreign`.
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
    spec = importlib.util.spec_from_file_location("overlay_export_foreign", MODULE_PATH)
    assert spec and spec.loader
    m = importlib.util.module_from_spec(spec)
    sys.modules["overlay_export_foreign"] = m
    spec.loader.exec_module(m)
    return m


@pytest.fixture(autouse=True)
def _isolated_git(monkeypatch):
    # Never read the developer's global git config (identity, hooks, excludes).
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


def _w(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
         "-c", "commit.gpgsign=false", *args],
        cwd=cwd, check=True, capture_output=True,
    )


ORG_CTX = "schema_version: 1\nscope: org\nx: 1\n"
SKILL = "skills/acme-costs"
FOREIGN_REF = f"{SKILL}/references/costs.md"


@pytest.fixture
def pair(tmp_path: Path):
    """A consumer bridge with history, plus the overlay mirror it exports to."""
    bridge = tmp_path / "bridge"
    overlay = tmp_path / "overlay"
    _w(bridge / "workflow/contexts/acme.yaml", ORG_CTX)
    # once owned by this bridge, then deleted: the one genuinely stale file
    _w(bridge / "workflow/contexts/gone.yaml", ORG_CTX)
    _git(bridge.parent, "init", "-q", str(bridge))
    _git(bridge, "add", "-A")
    _git(bridge, "commit", "-q", "-m", "seed")
    (bridge / "workflow/contexts/gone.yaml").unlink()
    _git(bridge, "commit", "-q", "-am", "drop gone")

    # an org skill the consumer keeps out of git on purpose
    _w(bridge / f"{SKILL}/SKILL.md",
       "---\nname: acme-costs\nmetadata:\n  scope: org\n---\n\n# skill\n")
    (bridge / ".git/info").mkdir(parents=True, exist_ok=True)
    (bridge / ".git/info/exclude").write_text(f"{SKILL}/\n", encoding="utf-8")

    _w(overlay / "tree/workflow/contexts/acme.yaml", ORG_CTX)
    _w(overlay / "tree/workflow/contexts/gone.yaml", ORG_CTX)
    _w(overlay / f"tree/{SKILL}/SKILL.md", "# skill\n")
    _w(overlay / f"tree/{FOREIGN_REF}", "# costs, added by a colleague\n")
    # added to the overlay directly, never present in this bridge
    _w(overlay / "tree/workflow/contexts/colleague.yaml", ORG_CTX)
    return bridge, overlay


def _foreign(plan) -> dict:
    return dict(plan["foreign"])


def test_a_file_under_a_skipped_folder_is_foreign_not_stale(oe, pair):
    bridge, overlay = pair
    plan = oe.export_overlay(str(bridge), str(overlay), scope="org", dry_run=True)
    assert FOREIGN_REF not in plan["pruned"]
    assert f"{SKILL}/SKILL.md" not in plan["pruned"]
    assert "gitignored" in _foreign(plan)[FOREIGN_REF]


def test_a_file_this_bridge_never_had_is_foreign(oe, pair):
    bridge, overlay = pair
    plan = oe.export_overlay(str(bridge), str(overlay), scope="org", dry_run=True)
    assert "workflow/contexts/colleague.yaml" not in plan["pruned"]
    assert "never tracked" in _foreign(plan)["workflow/contexts/colleague.yaml"]


def test_a_file_this_bridge_once_owned_is_still_pruned(oe, pair):
    bridge, overlay = pair
    plan = oe.export_overlay(str(bridge), str(overlay), scope="org", dry_run=True)
    assert plan["pruned"] == ["workflow/contexts/gone.yaml"]


def test_a_never_promote_path_is_foreign(oe, pair):
    bridge, overlay = pair
    _w(bridge / "bridge-config.yaml",
       "promote:\n  never_promote:\n    - path: ecosystem.acme.yaml\n")
    _w(overlay / "tree/ecosystem.acme.yaml", "org: acme\n")
    plan = oe.export_overlay(str(bridge), str(overlay), scope="org", dry_run=True)
    assert "ecosystem.acme.yaml" not in plan["pruned"]
    assert "never_promote" in _foreign(plan)["ecosystem.acme.yaml"]


def test_a_path_the_export_excludes_is_foreign(oe, pair):
    bridge, overlay = pair
    _w(overlay / "tree/work/notes.md", "# notes\n")
    plan = oe.export_overlay(str(bridge), str(overlay), scope="org", dry_run=True)
    assert "work/notes.md" not in plan["pruned"]
    assert "excluded" in _foreign(plan)["work/notes.md"]


def test_a_real_run_keeps_foreign_files_on_disk(oe, pair):
    bridge, overlay = pair
    oe.export_overlay(str(bridge), str(overlay), scope="org")
    assert (overlay / f"tree/{FOREIGN_REF}").exists()
    assert (overlay / "tree/workflow/contexts/colleague.yaml").exists()
    assert not (overlay / "tree/workflow/contexts/gone.yaml").exists()


def test_prune_foreign_deletes_them_on_request(oe, pair):
    bridge, overlay = pair
    plan = oe.export_overlay(str(bridge), str(overlay), scope="org", prune_foreign=True)
    assert FOREIGN_REF in plan["pruned"]
    assert not (overlay / f"tree/{FOREIGN_REF}").exists()
    assert not (overlay / "tree/workflow/contexts/colleague.yaml").exists()
    assert plan["foreign"] == []


def test_a_foreign_rule_keeps_its_manifest_entry(oe, pair):
    bridge, overlay = pair
    _w(overlay / "tree/rules/org/colleague-rule.md", "---\nscope: org\n---\n# r\n")
    plan = oe.export_overlay(str(bridge), str(overlay), scope="org", dry_run=True)
    assert "rules/org/colleague-rule.md" in [e["dest"] for e in plan["files_entries"]]


def test_without_git_history_nothing_is_pruned(oe, tmp_path):
    bridge, overlay = tmp_path / "plain", tmp_path / "overlay"
    _w(bridge / "workflow/contexts/acme.yaml", ORG_CTX)
    _w(overlay / "tree/workflow/contexts/old.yaml", ORG_CTX)
    plan = oe.export_overlay(str(bridge), str(overlay), scope="org", dry_run=True)
    assert plan["pruned"] == []
    assert "workflow/contexts/old.yaml" in _foreign(plan)


def test_the_dry_run_names_foreign_files_as_kept(oe, pair, capsys):
    bridge, overlay = pair
    rc = oe.main(["--repo-root", str(bridge), "--target", str(overlay),
                  "--scope", "org", "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert f"tree/{FOREIGN_REF} (foreign, kept:" in out
    assert "tree/workflow/contexts/gone.yaml (stale, would prune)" in out
    assert f"tree/{FOREIGN_REF} (stale" not in out
    assert "--prune-foreign" in out


def test_the_cli_flag_prunes_foreign(oe, pair):
    bridge, overlay = pair
    rc = oe.main(["--repo-root", str(bridge), "--target", str(overlay),
                  "--scope", "org", "--prune-foreign"])
    assert rc == 0
    assert not (overlay / f"tree/{FOREIGN_REF}").exists()


def test_a_worktree_consumer_still_consults_gitignore(oe, pair, tmp_path):
    # In a linked worktree `.git` is a FILE. Reading that as "not a checkout"
    # turned the gitignore guard off, the one that keeps a live secret out.
    bridge, overlay = pair
    wt = tmp_path / "wt"
    _git(bridge, "worktree", "add", "-q", str(wt))
    _w(wt / ".gitignore", "secret.yaml\n")
    _w(wt / "workflow/contexts/secret.yaml", ORG_CTX)
    plan = oe.export_overlay(str(wt), str(overlay), scope="org", dry_run=True)
    assert "workflow/contexts/secret.yaml" not in plan["copied"]
