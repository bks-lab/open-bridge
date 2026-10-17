#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Exclusion tests for scripts/overlay-export.py.

The exporter walks the filesystem and, by design, NEVER runs git — so it is
blind to `.gitignore`. Anything sitting on disk under a scoped path is a
candidate for publication into an overlay repo that teammates materialize.
Measured 2026-08-01: a `--scope org` run staged 21 build/runtime artifacts,
including a bot's stored conversations and four `.bak` snapshots. That is how
they reached the shared org overlay in the first place.

The opposite failure is live too: a blanket "any `_`-prefixed basename is a
template" rule silently dropped four real source files, among them a skill's
documented entry point and a package `__init__.py`. Inside the cluster wrappers
`_` does mean schema/template; under `skills/` it means nothing.

Run: python3 -m pytest scripts/tests/test_overlay_export_exclusions.py -q
"""
from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "overlay_export", REPO / "scripts" / "overlay-export.py"
)
assert _spec and _spec.loader, "cannot load scripts/overlay-export.py"
oe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(oe)


# --------------------------------------------------------------- must exclude
MUST_EXCLUDE = [
    # build artifacts — a stale .pyc can outlive the source fix it was compiled from
    "skills/acme-search/scripts/__pycache__/es_client.cpython-314.pyc",
    "skills/anything/scripts/__pycache__/mod.cpython-312.pyc",
    "skills/anything/scripts/mod.pyc",
    # runtime state — machine-local, and the reason a bot's chat history shipped
    "skills/telegram-assistant/data/state/bot-state.json",
    "skills/telegram-assistant/data/conversations/tg_100000001.json",
    "skills/project-status-notifier/data/state/hourly-state.json",
    "skills/project-status-notifier/data/state/hourly-state.json.bak.20260221_0906",
    # editor / manual backups
    "skills/acme-pdf/scripts/templates/report.html.bak",
    # contract exclusions that must keep working
    "work/log.md",
    "identity/agent/SOUL.md",
]


@pytest.mark.parametrize("path", MUST_EXCLUDE)
def test_excluded(path: str):
    assert oe.is_excluded(path), (
        f"{path} would be exported into an overlay repo. The exporter never reads "
        ".gitignore, so anything on disk under a scoped path is a publication candidate."
    )


# ------------------------------------------------------------ must NOT exclude
MUST_KEEP = [
    # `_` under skills/ is an ordinary filename, not a template marker
    "skills/creative-design-stack/presets/_index.html",   # entry point, referenced 8x from SKILL.md
    "skills/html-slides/presets/_template.yaml",          # the schema SKILL.md tells you to read
    "skills/sequential-thinking/scripts/utils/__init__.py",  # without it the package is unimportable
    # ordinary sources
    "skills/telegram-assistant/scripts/telegram_bot.py",
    "skills/kibana-dashboard-manager/SKILL.md",
    "workflow/projects/acme.yaml",
]


@pytest.mark.parametrize("path", MUST_KEEP)
def test_kept(path: str):
    assert not oe.is_excluded(path), (
        f"{path} is dropped from the export. Under skills/ a leading underscore is "
        "just a filename — dropping it silently ships a broken skill."
    )


# ------------------------------------------ `_` still means template in wrappers
@pytest.mark.parametrize("path", [
    "identity/personas/_schema.yaml",
    "identity/mandants/_template.yaml",
    "infra/remotes/_schema.yaml",
    "workflow/projects/_template.yaml",
])
def test_underscore_still_excluded_inside_cluster_wrappers(path: str):
    assert oe.is_excluded(path), (
        f"{path} is a CORE companion — `_` inside identity/ infra/ workflow/ does mean "
        "schema/template, and those must not be exported as org/personal content."
    )


# --------------------------------------------------------- .gitignore is truth
# The pattern lists above are a fallback, not the guard. The real rule is: if git
# refuses to track a file, the exporter must refuse to publish it. Enumerating
# artifact shapes closes only the shapes someone thought of — measured 2026-08-01,
# a `--scope org` run still staged `skills/acme-files/.env` (a LIVE Azure
# client secret for a customer tenant) and `kibana-dashboard-manager/config.local.json`
# (a live Elastic Cloud API key), because neither looks like a build artifact.
# Both are gitignored. git already knew.
def _git_ignored(paths: list[str]) -> list[str]:
    if not paths:
        return []
    proc = subprocess.run(
        ["git", "check-ignore", "--stdin"], cwd=REPO,
        input="\n".join(paths), capture_output=True, text=True,
    )
    assert proc.returncode in (0, 1), f"git check-ignore failed: {proc.stderr}"
    return [p for p in proc.stdout.splitlines() if p.strip()]


@pytest.mark.parametrize("scope", ["org", "personal"])
def test_export_never_stages_a_gitignored_file(scope: str):
    files = oe.discover_scoped_files(str(REPO), scope=scope)
    leaked = _git_ignored(files)
    assert not leaked, (
        f"a --scope {scope} export would publish {len(leaked)} gitignored file(s): "
        f"{leaked[:5]}. git refuses to track them; the exporter must refuse to ship them."
    )


@pytest.mark.parametrize("path", [
    "skills/acme-files/.env",
    "skills/kibana-dashboard-manager/config.local.json",
])
def test_the_two_measured_credential_files_are_gone(path: str):
    """Named explicitly so a future refactor cannot quietly re-open this door."""
    if not (REPO / path).exists():
        pytest.skip(f"{path} absent on this machine")
    assert path not in oe.discover_scoped_files(str(REPO), scope="org"), (
        f"{path} is staged for the shared org overlay. It holds live credentials."
    )


def test_env_template_still_exports():
    """The counter-check: the EMPTY template is legitimate shared content."""
    path = "skills/acme-files/.env.template"
    if not (REPO / path).exists():
        pytest.skip(f"{path} absent")
    assert path in oe.discover_scoped_files(str(REPO), scope="org"), (
        f"{path} was dropped. It is tracked, empty, and already in the org overlay — "
        "the ignore filter must not over-reach onto real content."
    )


# --------------------------------------------------- the live tree stays clean
def test_no_junk_in_a_real_org_export():
    """End-to-end: the actual discovery must not surface build or runtime artifacts."""
    files = oe.discover_scoped_files(str(REPO), scope="org")
    junk = [
        f for f in files
        if "__pycache__" in f
        or f.endswith(".pyc")
        or "/data/state/" in f
        or "/data/conversations/" in f
        or ".bak" in f
    ]
    assert not junk, f"a --scope org export would publish {len(junk)} artifacts: {junk[:6]}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


# ------------------------------------------------------- never_promote is honoured
# `promote.never_promote` names files that exist on BOTH sides and must never be
# copied in either direction. It was wired into the three promote SKILLS, but
# not into this exporter, which is the tool that actually writes into an
# overlay repo. Measured 2026-08-01: a `--scope org` run wanted to CREATE
# `tree/ecosystem.<org>.yaml`, a second divergent copy of the fragment the overlay
# already carries at its root and receives FROM the org, plus `tree/ecosystem.yaml`,
# the per-instance base that would overwrite each consumer's own on materialize.
# A governance list no code path reads is not a rule, it is a wish.
def _mini_repo_with_never_promote(root: pathlib.Path) -> None:
    """A synthetic instance: two org-scoped files, one of them on the list."""
    for rel in ("workflow/contexts/shared.yaml", "workflow/contexts/forbidden.yaml"):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("schema_version: 1\nscope: org\n", encoding="utf-8")
    (root / "bridge-config.yaml").write_text(
        "promote:\n"
        "  never_promote:\n"
        "    - path: workflow/contexts/forbidden.yaml\n"
        "      reason: exists on both sides, owned by neither\n",
        encoding="utf-8",
    )


def test_export_honours_never_promote(tmp_path: pathlib.Path):
    _mini_repo_with_never_promote(tmp_path)
    assert oe.never_promote_paths(str(tmp_path)) == {"workflow/contexts/forbidden.yaml"}
    staged = set(oe.discover_scoped_files(str(tmp_path), scope="org"))
    assert "workflow/contexts/forbidden.yaml" not in staged, (
        "a --scope org export stages a file promote.never_promote forbids. "
        "Copying it silently reconfigures the destination."
    )
    # the list must not turn discovery off wholesale
    assert "workflow/contexts/shared.yaml" in staged


def test_the_instance_base_ecosystem_is_never_exported():
    """Named explicitly: each instance authors its own; only the fragment is shared."""
    for scope in ("org", "personal"):
        staged = oe.discover_scoped_files(str(REPO), scope=scope)
        assert "ecosystem.yaml" not in staged, (
            f"--scope {scope} stages ecosystem.yaml. Materializing it overwrites "
            "every consumer's own instance base."
        )
