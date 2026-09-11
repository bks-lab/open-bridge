#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Regression tests for the CORE census in scripts/check-figure-counts.py.

The figure on docs/explore.html answers ONE question: how many files does a
fresh clone get, split by folder. The census that feeds it used to be "every
tracked file that is not under examples/", which is true on the default branch
and false on every `user/*` branch, because an instance tracks its own work/
content there. `validate.yml` runs on `main` AND on `user/**` by design, so the
check could never pass on the branches it was deliberately pointed at.

Two directions are asserted here, and they pull against each other:

  * an INSTANCE file must never inflate the CORE count — otherwise `--write`
    bakes one operator's task list into a page that ships to open-bridge;
  * a file that SHIPS must still be counted even when the promote router calls
    it `user` — work/templates/ and work/_learning/ scaffolding live inside a
    USER-tier folder but a fresh clone gets them, and .gitignore /
    .bridge-origin exist on both sides and must never be copied either way.

That second class is why classify_file() alone is the wrong answer: the promote
router decides "may this travel upward", the figure asks "does a clone get it".
Both are right; they are different questions.

Run: python3 -m pytest scripts/tests/test_figure_counts.py -q
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "check_figure_counts", REPO / "scripts" / "check-figure-counts.py"
)
assert _spec and _spec.loader, "cannot load scripts/check-figure-counts.py"
cfc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cfc)


# ---------------------------------------------------------------------------
# An instance's own content must never count as CORE. Every path here is
# tracked on a user/* branch and absent from the default branch.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", [
    "work/log.md",
    "work/board.md",
    "work/STATUS.md",
    "work/tasks/some-task/STATUS.md",
    "work/tasks/some-task/NOTES.md",
    "work/streams/a-long-runner/STATUS.md",
    "work/done/2026-09/some-task/STATUS.md",
    "work/archive/weeks/2026-W29.md",
    "work/trackers/github/some-board.json",
    "work/_learning/proposals/2026-01-01-some-proposal.md",
    "work/_learning/proposals/accepted/2026-01-01-accepted.md",
    "work/_learning/proposals/rejected/2026-01-01-rejected.md",
    "work/_learning/postmortems/2026-01-01-some-task.md",
    "work/_learning/audit-history/2026-01-01.md",
    "work/_learning/user-patterns.md",
    "identity/agent/IDENTITY.md",
    "identity/agent/SOUL.md",
])
def test_instance_content_is_not_core(path):
    assert cfc.is_core_file(path) is False, (
        f"{path} is instance content; counting it as CORE lets --write bake one "
        f"operator's tree into a page that ships to open-bridge"
    )


# ---------------------------------------------------------------------------
# Ships with a fresh clone, therefore counts, even though the promote router
# classifies it `user` so an instance copy never travels upward.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", [
    "work/templates/STATUS.md",
    "work/templates/day.md",
    "work/templates/week-skeleton.md",
    "work/templates/_schema.status.yaml",
    "work/_learning/README.md",
    "work/_learning/_schema.proposal.yaml",
    "work/_learning/audit-trail.md",
    "work/_learning/proposals/.gitkeep",
    "work/_learning/proposals/accepted/.gitkeep",
    "work/_learning/postmortems/.gitkeep",
    "work/_learning/audit-history/.gitkeep",
    ".gitignore",
    ".bridge-origin",
])
def test_shipped_scaffolding_is_core(path):
    assert cfc.is_core_file(path) is True, (
        f"{path} ships with a fresh clone and must stay in the census, even "
        f"though the promote router calls it user"
    )


# ---------------------------------------------------------------------------
# Ordinary CORE additions still count, so a PR that adds one is still told to
# update the figure. Losing this would gut the check upstream.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", [
    "rules/some-rule.md",
    # scripts/ is an explicit allowlist in the router, fail-CLOSED on purpose:
    # a new script does not ship until somebody lists it. Pin an allowlisted one
    # so this asserts the real contract instead of an invented path.
    "scripts/categorize-commits.py",
    "docs/some-doc.md",
    "protocols/standing-orders/some-order.md",
    "trackers/some-provider.md",
    "infra/remotes/_template.yaml",
    "workflow/projects/_schema.yaml",
])
def test_core_additions_still_count(path):
    assert cfc.is_core_file(path) is True, (
        f"{path} is CORE; dropping it would let a PR add a shipped file without "
        f"the figure noticing"
    )


# ---------------------------------------------------------------------------
# The USER half of the figure is drawn from the shipped example workspace, so
# nothing under examples/ may ever land in the CORE half.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", [
    "examples/agency/work/log.md",
    "examples/agency/identity/agent/SOUL.md",
    "examples/agency/.claude/agents/some-agent.md",
])
def test_examples_are_never_core(path):
    assert cfc.is_core_file(path) is False


# ---------------------------------------------------------------------------
# End-to-end: the census over the real tree must be branch-independent. Run on
# the default branch or on a user/* branch, the CORE total is the same, because
# the difference between those trees is instance content by construction.
# ---------------------------------------------------------------------------
def test_census_excludes_all_instance_files():
    import subprocess
    head = subprocess.run(
        ["git", "-C", str(REPO), "ls-files"],
        capture_output=True, text=True, check=True,
    ).stdout.split()
    only_here = [f for f in head if cfc.is_core_file(f)
                 and (f.startswith(("work/log", "work/board", "work/tasks/",
                                     "work/streams/", "work/done/", "work/archive/"))
                      # identity/agent/ also holds CORE scaffolding (_template.*,
                      # _schema.yaml, README.md). Only the two live files are the
                      # operator's, and those are what must never be counted.
                      or f in ("identity/agent/IDENTITY.md", "identity/agent/SOUL.md"))]
    assert not only_here, (
        "instance files leaked into the CORE census: " + ", ".join(sorted(only_here)[:10])
    )
