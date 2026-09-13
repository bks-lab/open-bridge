#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Regression tests for the scope router — scripts/categorize-commits.py.

`classify_file()` decides which upstream a file may reach. `core` means the file
ships to **bks-lab/open-bridge**, a PUBLIC MIT repo, so a wrong `core` is a leak
and a wrong non-`core` silently cuts this instance off from upstream updates.
Both directions are asserted here.

The router is an ORDERED denylist that ends in `return "core"` — fail-OPEN. Every
path family added after a rule was written therefore defaults to shipping. These
tests pin the families that were found misrouted on 2026-08-01, and — just as
importantly — pin the paths that must NOT move, because the obvious
generalisations of the fix would route real PII into the public repo.

Portability: every path below is either a pure pattern-match (no filesystem
touch inside classify_file at all) or a generic synthetic fixture built by the
`synth_repo` fixture in a throwaway `tmp_path`. No test depends on any specific
Bridge instance's real tree — this file runs the same in any conformant clone,
including open-bridge itself, where none of the real instance data exists.

Run: python3 -m pytest scripts/tests/test_scope_router.py -q
"""
from __future__ import annotations

import importlib.util
import pathlib
import re
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "categorize_commits", REPO / "scripts" / "categorize-commits.py"
)
assert _spec and _spec.loader, "cannot load scripts/categorize-commits.py"
cc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cc)


def tier(path: str) -> str:
    return cc.classify_file(path)


# ---------------------------------------------------------------------------
# synth_repo — a throwaway repo tree with GENERIC synthetic files at every path
# the file-existence-checking tests below need. classify_file() and its helpers
# (read_frontmatter_scope, _theme_declared_scope, _logo_owner_map) use bare
# relative paths and rely on the process CWD, so this fixture also chdirs into
# the tmp tree for the duration of the test — that is what makes a frontmatter
# `scope:` read resolve against synthetic content instead of this developer's
# real instance data. monkeypatch.chdir restores the original CWD on teardown.
#
# `_logo_owner_map()` caches its result on the categorize_commits MODULE
# (`_LOGO_BY_THEME_CACHE`), which survives across tests since the module is
# imported once for the whole file. Reset it on both sides of the fixture so a
# real-repo test and a synth_repo test can never see each other's scan.
# ---------------------------------------------------------------------------
@pytest.fixture
def synth_repo(tmp_path, monkeypatch):
    def write(rel: str, content: str = "") -> pathlib.Path:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    # MUST_NOT_SHIP guard paths (see below).
    write("infra/backups/_state.yaml")
    write("infra/channels/bots/example-clinic/README.md")
    write("identity/voiceprints/README.md")

    # DECLARED_USER_CONFIG + the workflow/checks/ boundary.
    write("workflow/checks/_schema.yaml")
    write("workflow/checks/_template.yaml")
    write("workflow/checks/backup.yaml")
    write("workflow/checks/disk.yaml")
    write("workflow/checks/imports.yaml")
    write("workflow/checks/remotes.yaml")
    write("infra/utilities/energy-provider.yaml")
    write("infra/transcriptions/topology.yaml")

    # Workspaces — customer repo names + private clone URLs, generic examples.
    write("workflow/workspaces/customer-a.yaml")
    write("workflow/workspaces/customer-b.yaml")
    write("workspaces.lock.yaml")

    # scripts/ — instance scripts that must not fall into the core allowlist.
    write("scripts/sync-pii-to-homeserver.sh")
    write("scripts/push-bridge-state.sh")

    # A fixture skill declaring its own `metadata.scope: personal`, with a
    # nested evals/ file that must inherit that tier rather than the fail-open
    # core default — the synthetic stand-in for the historic orphan-dir fix.
    write(
        "skills/example-skill/SKILL.md",
        "---\n"
        "name: example-skill\n"
        "description: synthetic fixture skill for the router tests\n"
        "metadata:\n"
        "  scope: personal\n"
        "---\n"
        "# Example Skill\n",
    )
    write("skills/example-skill/evals/trigger-eval.json", "{}\n")

    # Org branding: a theme declaring its own tier, and the logo it links to
    # via `branding.logo_ascii:` — an org overriding the shipped `professional`
    # theme with its own terminal branding, using the same "acme" placeholder
    # the ecosystem-fragment tests below use for a generic org.
    write(
        "themes/acme.yaml",
        "schema_version: 1\n"
        "meta:\n"
        "  scope: org\n"
        "  name: acme\n"
        "branding:\n"
        "  logo_ascii: skills/bridge-greeting/assets/logos/acme.txt\n",
    )
    write("skills/bridge-greeting/assets/logos/acme.txt", "ACME\n")

    # infra/remotes/ — the tripwire family: one org-owned managed service and
    # five personal machines, each declaring its own real `scope:` as a bare
    # top-level key (no `---` fence, matching how these files are actually
    # written).
    write("infra/remotes/managed-cluster.yaml", "name: managed-cluster\nscope: org\n")
    for name in ("homeserver", "workstation", "fritzbox", "tesla-wallconnector", "ds"):
        write(f"infra/remotes/{name}.yaml", f"name: {name}\nscope: user\n")

    cc._LOGO_BY_THEME_CACHE = None
    monkeypatch.chdir(tmp_path)
    yield tmp_path
    cc._LOGO_BY_THEME_CACHE = None


# ---------------------------------------------------------------------------
# GUARDS — these must NEVER become `core`. Each one is a real leak that a
# plausible generalisation of the fix would introduce. They are listed first
# because a fix that trips one is worse than the bug it repairs.
# ---------------------------------------------------------------------------
MUST_NOT_SHIP = [
    # Trap 1 — a blanket "`_`-prefix in a cluster wrapper is core" flips this.
    # It records real backup volumes and hosts.
    ("infra/backups/_state.yaml", "user"),
    # Trap 2 — a blanket "README.md in a cluster wrapper is core" flips these.
    # A freelance client (practice name, booking-software integration) …
    ("infra/channels/bots/example-clinic/README.md", "user"),
    # … and a biometric directory naming real people (GDPR Art. 9).
    ("identity/voiceprints/README.md", "user"),
]


@pytest.mark.parametrize("path,expected", MUST_NOT_SHIP)
def test_guard_never_ships_to_public(path: str, expected: str, synth_repo):
    assert (synth_repo / path).exists(), f"guard path vanished — update the test: {path}"
    assert tier(path) == expected, (
        f"LEAK GUARD TRIPPED: {path} classifies {tier(path)!r}, must be {expected!r}. "
        "A generalisation in the router has started routing instance PII to the public repo."
    )


# ---------------------------------------------------------------------------
# Bridge-Agent instances. AGENTS.md: the generic runtime + template ship as CORE
# under agents/, but each agents/<name>/ INSTANCE is USER.
# ---------------------------------------------------------------------------
AGENT_INSTANCES = [
    "agents/alice/agent.yaml",
    "agents/alice/system-prompt.md",
    "agents/alice/calendars.json",
    "agents/alice/tools/ask_kb.py",
    "agents/alice/tools/availability.py",
    "agents/alice/tools/test_agent_confinement.py",
    "agents/openbridge/agent.yaml",
    "agents/openbridge/DEPLOY.md",          # carries real `scope: user` frontmatter
    "agents/openbridge/system-prompt.md",
    "agents/openbridge/grounding-seed/about.md",
    "agents/openbridge/tools/ask_kb.py",
]


@pytest.mark.parametrize("path", AGENT_INSTANCES)
def test_agent_instances_are_user(path: str):
    assert tier(path) == "user", (
        f"{path} classifies {tier(path)!r}. AGENTS.md declares agents/<name>/ instances USER; "
        "these files carry the operator's identity, calendars and Graph/KeyVault wiring."
    )


def test_agent_runtime_and_template_stay_core():
    """The generic half must keep shipping — the fix must not over-reach."""
    for path in ("agents/README.md", "agents/_template/agent.yaml"):
        if (REPO / path).exists():
            assert tier(path) == "core", f"{path} should stay core, got {tier(path)!r}"


# ---------------------------------------------------------------------------
# Cluster-wrapper types added after _CLUSTER_WRAPPER_RE was written. All of these
# declare their own tier in frontmatter and are ignored today.
# ---------------------------------------------------------------------------
DECLARED_USER_CONFIG = [
    "workflow/checks/remotes.yaml",        # homeserver.tailXXXXXX.ts.net, example-bot-UAT
    "workflow/checks/imports.yaml",        # real interview names
    "workflow/checks/backup.yaml",
    "infra/utilities/energy-provider.yaml",  # address, customer + meter numbers
    "infra/transcriptions/topology.yaml",  # says "NEVER promotes upstream" in its own header
]


@pytest.mark.parametrize("path", DECLARED_USER_CONFIG)
def test_config_declaring_user_scope_is_not_core(path: str, synth_repo):
    assert (synth_repo / path).exists(), f"path vanished — update the test: {path}"
    assert tier(path) != "core", (
        f"{path} classifies core although it declares a non-core scope in its own frontmatter. "
        "The cluster-wrapper frontmatter dispatch does not cover this type."
    )


# ---------------------------------------------------------------------------
# Workspaces — customer repo names + private clone URLs; and the root lockfile,
# whose sibling overlays.lock.yaml is already `user`.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", [
    "workflow/workspaces/customer-a.yaml",
    "workflow/workspaces/customer-b.yaml",  # `title: Example Practice GmbH` survives the scrub
    "workspaces.lock.yaml",
])
def test_workspaces_are_user(path: str, synth_repo):
    assert (synth_repo / path).exists(), f"path vanished — update the test: {path}"
    assert tier(path) == "user", f"{path} classifies {tier(path)!r}, expected user"


def test_lockfile_siblings_agree():
    """overlays.lock.yaml and workspaces.lock.yaml are the same kind of artifact."""
    assert tier("overlays.lock.yaml") == tier("workspaces.lock.yaml"), (
        "the two generated root lockfiles classify differently — one of them is an oversight"
    )


# ---------------------------------------------------------------------------
# scripts/ — rules/operations.md carries an ALLOWLIST; the router has no rule at
# all, making it a catch-all that ships anything new by default.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", [
    "scripts/sync-pii-to-homeserver.sh",   # its stated purpose is moving PII between machines
    "scripts/push-bridge-state.sh",
])
def test_instance_scripts_are_not_core(path: str, synth_repo):
    assert (synth_repo / path).exists(), f"path vanished — update the test: {path}"
    assert tier(path) != "core", (
        f"{path} classifies core. rules/operations.md lists promotable scripts explicitly; "
        "the router has no scripts/ rule, so every new script ships by default."
    )


def test_core_engine_scripts_still_ship():
    """The allowlisted engines must stay core — the fix must not over-reach."""
    for path in ("scripts/overlay.py", "scripts/categorize-commits.py"):
        assert tier(path) == "core", f"{path} should stay core, got {tier(path)!r}"


def test_the_shared_drift_check_ships_with_its_client_hooks():
    """Claude Code, Codex and Mistral Vibe all call one script. The declarations
    are useless downstream without it, and it is a scripts/ file, so only the
    allowlist keeps it core."""
    for path in ("scripts/worklog-drift-check.sh", ".codex/hooks.json", ".vibe/hooks.toml"):
        assert tier(path) == "core", f"{path} should be core, got {tier(path)!r}"


# ---------------------------------------------------------------------------
# Skill directories with no SKILL.md fall through the frontmatter read straight
# into the fail-open core default.
# ---------------------------------------------------------------------------
def test_skill_dir_without_skill_md_is_not_core():
    """A skills/<dir>/ with no SKILL.md declares no tier — it must not default to core.

    Historic case: an orphaned skill directory held only an eval fixture naming
    real customers, had no SKILL.md, and so fell straight through the
    frontmatter read into the fail-open core default. The file has since moved
    under a properly-declared skill's evals/ directory, so the property here is
    asserted against a synthetic directory instead of a real one — the rule
    must hold for the NEXT such directory, not just that one.
    """
    assert tier("skills/no-such-skill-dir/some-file.json") != "core", (
        "a skill directory without SKILL.md still defaults to core"
    )


def test_the_historic_orphan_skill_dir_is_resolved(synth_repo):
    """The orphan-directory incident above, pinned end-to-end against a synthetic
    stand-in: a fixture skill declares `metadata.scope: personal` in its own
    SKILL.md, and a nested evals/ file must inherit that tier rather than the
    fail-open core default. The orphan directory itself (`legacy-orphan-workspace`)
    is deliberately never created — its absence is itself the historic fix.
    """
    assert not (synth_repo / "skills/legacy-orphan-workspace").exists(), (
        "the orphan skill directory pattern is back — a dir with no SKILL.md routes to core"
    )
    moved = "skills/example-skill/evals/trigger-eval.json"
    assert (synth_repo / moved).exists(), f"{moved} missing — fixture setup is broken"
    assert tier(moved) == "personal", (
        f"{moved} should inherit `personal` from skills/example-skill/SKILL.md, "
        f"got {tier(moved)!r}"
    )


def test_org_branding_asset_is_not_core(synth_repo):
    path = "skills/bridge-greeting/assets/logos/acme.txt"
    assert (synth_repo / path).exists(), f"path vanished — update the test: {path}"
    assert tier(path) != "core", (
        f"{path} classifies core. It renders org branding as block glyphs — invisible to every "
        "string scanner — and carries the org token in its filename. Upstream ships only bridge.txt."
    )


def test_org_theme_is_not_core(synth_repo):
    path = "themes/acme.yaml"
    assert (synth_repo / path).exists(), f"path vanished — update the test: {path}"
    assert tier(path) != "core", f"{path} classifies core; it is instance/org branding"


# ---------------------------------------------------------------------------
# Org branding is SHARED, not local. Michael's call (2026-08-01): an org theme
# and logo belong in the org overlay, so every teammate's Bridge greets in that
# org's colours instead of each person re-authoring them. `user` would have kept
# them out of public — correct on the leak axis, wrong on the distribution axis.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", [
    "themes/acme.yaml",
    "skills/bridge-greeting/assets/logos/acme.txt",
])
def test_org_branding_routes_to_the_org_overlay(path: str, synth_repo):
    assert (synth_repo / path).exists(), f"path vanished — update the test: {path}"
    assert tier(path) == "org", (
        f"{path} classifies {tier(path)!r}. Org branding ships to the org overlay so "
        "teammates inherit it; `user` would strand it on this one machine."
    )


# ---------------------------------------------------------------------------
# workflow/checks/ — Michael's call (2026-08-01): not CORE at all.
# AGENTS.md ships the data model, not the executor; here even the data model is
# instance-shaped (a `checkup` skill that is itself `user` is the only reader).
# It never reached open-bridge/main, so this pins a boundary rather than
# repairing a leak — including the `_`-companions, which the `_`-prefix rule
# would otherwise keep classifying core forever.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", [
    "workflow/checks/_schema.yaml",
    "workflow/checks/_template.yaml",
    "workflow/checks/backup.yaml",
    "workflow/checks/disk.yaml",
    "workflow/checks/imports.yaml",
    "workflow/checks/remotes.yaml",
])
def test_checks_never_classify_core(path: str, synth_repo):
    assert (synth_repo / path).exists(), f"path vanished — update the test: {path}"
    assert tier(path) == "user", (
        f"{path} classifies {tier(path)!r}. The whole workflow/checks/ surface stays "
        "local — its only consumer is the `user`-scoped checkup skill."
    )


# ---------------------------------------------------------------------------
# infra/remotes/ was the last cluster wrapper whose files declare a `scope:` that
# nothing reads. Every one carries the tripwire tag: personal machines say
# `user`, and an org-owned managed service says `org` — then documents the
# workaround in its own header ("/promote does not route this file
# automatically; the org sync happens manually"). It has been hand-carried to
# the org overlay, so `overlay-export --scope org` would otherwise treat it as
# stale and PRUNE it. Reading the declaration the files already carry fixes
# all of that.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# The ecosystem fragment family. The router matched ONE literal filename, so
# one org's fragment was org while any other org's fragment classified core
# and shipped to the public repo — the same fail-open shape, and a hardcoded org
# token in a CORE file besides (AGENTS.md: a core file reads config, it never
# embeds org IDs). Found 2026-08-01 by the pre-publication review.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", [
    "ecosystem.acme.yaml",
    "ecosystem.contoso-gmbh.yaml",          # any other org's fragment must route the same way
])
def test_any_org_ecosystem_fragment_is_org(path: str):
    assert tier(path) == "org", (
        f"{path} classifies {tier(path)!r}. An org registry fragment names customers, "
        "boards and repos — it belongs in the org overlay, never in the public repo."
    )


@pytest.mark.parametrize("path,expected", [
    ("ecosystem.example.yaml", "core"),      # the CORE template, ships upstream
    ("ecosystem.personal.yaml", "personal"),
    ("ecosystem.local.yaml", "personal"),    # pre-rename name of the same file
    ("ecosystem.yaml", "org"),               # instance base, carried by the overlay
])
def test_the_non_org_ecosystem_files_keep_their_tier(path: str, expected: str):
    """The generalisation must not swallow the template or the personal fragments."""
    assert tier(path) == expected, f"{path} classifies {tier(path)!r}, expected {expected!r}"


def test_router_embeds_no_org_token():
    """This file is CORE and ships to open-bridge; an org name in it is a leak AND drift."""
    src = (REPO / "scripts" / "categorize-commits.py").read_text(encoding="utf-8")
    code = "\n".join(
        line.split("#", 1)[0] for line in src.splitlines()
    )
    assert "bks" not in code.lower(), (
        "the router's CODE still contains an org token. Tier decisions must come from "
        "structure or a file's own declaration, never a baked-in org name."
    )


def test_org_owned_remote_routes_by_its_declaration(synth_repo):
    path = "infra/remotes/managed-cluster.yaml"
    assert (synth_repo / path).exists(), f"path vanished — update the test: {path}"
    assert tier(path) == "org", (
        f"{path} declares `scope: org` but classifies {tier(path)!r}. It already lives "
        "in the org overlay; a `user` verdict makes overlay-export prune it."
    )


@pytest.mark.parametrize("path", [
    "infra/remotes/homeserver.yaml",
    "infra/remotes/workstation.yaml",
    "infra/remotes/fritzbox.yaml",
    "infra/remotes/tesla-wallconnector.yaml",
    "infra/remotes/ds.yaml",
])
def test_personal_machines_stay_local(path: str, synth_repo):
    """The whole point of the tripwire: reading declarations must not free the rest."""
    assert (synth_repo / path).exists(), f"path vanished — update the test: {path}"
    assert tier(path) == "user", (
        f"{path} classifies {tier(path)!r}. These carry LAN addresses, Tailscale names "
        "and household hardware — they declare `scope: user` and must stay local."
    )


def test_remote_without_a_declaration_fails_closed():
    """An undeclared remote must NOT inherit core from the path fallback."""
    assert tier("infra/remotes/brand-new-box.yaml") == "user", (
        "an undeclared remote classifies non-user — the declaration read must fail "
        "closed onto the path rule, never open onto core"
    )


def test_remote_template_still_ships():
    assert tier("infra/remotes/_template.yaml") == "core", (
        "the remotes template is CORE scaffolding; reading declarations must not "
        "swallow it (it declares `scope: user` as the value a USER file should copy)"
    )


def test_checks_are_absent_upstream():
    """Guard the premise: if upstream ever ships checks/, this decision needs revisiting."""
    out = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "open-bridge/main", "--", "workflow/checks/"],
        cwd=REPO, capture_output=True, text=True,
    ).stdout.strip()
    assert not out, (
        "open-bridge/main now ships workflow/checks/ — classifying it `user` here "
        f"silently stops receiving those updates. Upstream files: {out.splitlines()[:5]}"
    )


# ---------------------------------------------------------------------------
# The other direction: files byte-identical to open-bridge/main that we classify
# away from core. Each one is an update channel we have silently closed.
# ---------------------------------------------------------------------------
def _identical_to_upstream(path: str) -> bool:
    proc = subprocess.run(
        ["git", "diff", "--quiet", "open-bridge/main", "--", path],
        cwd=REPO, capture_output=True,
    )
    return proc.returncode == 0


@pytest.mark.parametrize("path", [
    "identity/accounts/_schema.yaml",
    "workflow/contexts/_doc-system.template.yaml",
    "workflow/projects/README.md",
    "infra/transcriptions/README.md",
])
def test_files_identical_to_upstream_stay_core(path: str):
    if not (REPO / path).exists():
        pytest.skip(f"{path} not present")
    if not _identical_to_upstream(path):
        pytest.skip(f"{path} diverges locally — demotion may be legitimate")
    assert tier(path) == "core", (
        f"{path} is byte-identical to open-bridge/main but classifies {tier(path)!r}. "
        "We have silently stopped receiving upstream updates for it."
    )


# ---------------------------------------------------------------------------
# Whole-folder USER surfaces AGENTS.md names but the router never encoded.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", [
    "imports/some-recording.m4a",          # AGENTS.md § Scope: "work/, imports/ = USER"
    "themes/some-private-theme.yaml",      # an unshared instance theme still stays local
])
def test_whole_folder_user_surfaces(path: str):
    assert tier(path) == "user", f"{path} classifies {tier(path)!r}, expected user"


@pytest.mark.parametrize("path", [
    "themes/professional.yaml",
    "themes/professional-de.yaml",
    "themes/_schema.yaml",
    "skills/bridge-greeting/assets/logos/bridge.txt",
])
def test_shipped_theme_and_logo_stay_core(path: str):
    """The upstream set must keep flowing — the instance rule must not over-reach."""
    assert tier(path) == "core", f"{path} classifies {tier(path)!r}, expected core"


# ---------------------------------------------------------------------------
# Per-tier INVERTED root files: they exist on both sides and must never be
# copied in either direction, so neither may classify core.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", [".gitignore", ".bridge-origin"])
def test_inverted_root_files_never_ship(path: str):
    assert tier(path) != "core", (
        f"{path} classifies core, but it diverges per tier by design — promoting it would "
        "overwrite the upstream's own variant (and .bridge-origin would disarm the push guard)."
    )


# ---------------------------------------------------------------------------
# Quoted paths. git quotes any path with a non-ASCII byte (core.quotePath
# defaults to true), and the leading `"` breaks the `^` anchor of EVERY pattern
# at once — so an umlaut in a filename silently routes it to core.
# ---------------------------------------------------------------------------
def test_non_ascii_path_is_not_anchored_away():
    raw = "agents/alice/tools/verfügbarkeit.py"
    assert tier(raw) == "user", f"unquoted form already wrong: {tier(raw)!r}"
    quoted = '"agents/alice/tools/verf\\303\\274gbarkeit.py"'
    assert tier(quoted) != "core", (
        "a git-quoted path classifies core: the leading quote breaks every ^-anchor at once. "
        "files_in_commit() must pass -z with core.quotePath=false."
    )


# ---------------------------------------------------------------------------
# Structural property: the terminal default. Documented here so a deliberate
# change to fail-closed updates this test on purpose rather than by accident.
# ---------------------------------------------------------------------------
def test_unknown_path_default_is_pinned():
    got = tier("some/brand-new/unregistered-thing.yaml")
    assert got in {"core", "user"}, f"unexpected default {got!r}"
    if got == "core":
        pytest.xfail(
            "router still fails OPEN: an unregistered path ships to the public repo by default"
        )


# ---------------------------------------------------------------------------
# The generalisation of test_files_identical_to_upstream_stay_core above.
#
# That test names four paths by hand and has therefore only ever proved four
# things. The invariant behind it is total: a tree that carries NO user tier is
# CORE by construction, so every file tracked in it must classify core. Anything
# else is an update channel closed in silence: the file ships upstream, and the
# router refuses to carry the next change to it, with no error anywhere.
#
# Run against the whole upstream tree it found 23 such files at once, in three
# families that each went stale the same way: a hand-maintained enumeration that
# nobody re-generated when a file was added next to it.
# ---------------------------------------------------------------------------

#: Tracked upstream AND deliberately not core. Each entry is a divergence that
#: must never be copied in either direction, so `user` is the correct answer.
UPSTREAM_NON_CORE_BY_DESIGN = frozenset({
    # Per-tier INVERTED; see test_inverted_root_files_never_ship.
    ".gitignore",
    ".bridge-origin",
})

#: Same, by prefix. `work/` is whole-folder USER (AGENTS.md § Scope): upstream
#: ships the empty scaffolding, and promote must never carry what a downstream
#: puts into it. Shipping the seed and refusing the content is the point.
UPSTREAM_NON_CORE_PREFIXES = ("work/",)


def _upstream_ref():
    """The ref whose tree is CORE-only by definition, or None.

    Two shapes of checkout ask this. In a downstream Bridge the OSS upstream is
    a remote, so `open-bridge/main` is the tree to read. In open-bridge itself
    there is no such remote and none is needed: a checkout without
    `bridge-config.yaml` has no user tier at all, so its own HEAD is the tree.
    Anything else skips rather than guesses.
    """
    probe = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", "open-bridge/main"],
        cwd=REPO, capture_output=True, text=True,
    )
    if probe.returncode == 0:
        return "open-bridge/main"
    if not (REPO / "bridge-config.yaml").exists():
        return "HEAD"
    return None


def _governed_by_a_declared_skill_scope(path: str) -> bool:
    """True when this file's tier was DECLARED rather than fallen into.

    A skill takes its tier from its own SKILL.md, and the whole directory goes
    with it. An instance that forks a core skill down to `user` (this tree has
    done that with skills/remote/, which carries machine specifics) drags along
    files that never diverged, and calling those a defect would be calling a
    decision a defect. The guard exists for tiers nobody chose.
    """
    parts = path.split("/")
    if len(parts) < 3 or parts[0] != "skills":
        return False
    declared = cc.read_frontmatter_scope(f"skills/{parts[1]}/SKILL.md")
    return bool(declared) and cc._SCOPE_MAP.get(declared) not in (None, "core")


def test_every_file_upstream_ships_stays_core():
    ref = _upstream_ref()
    if ref is None:
        pytest.skip("no CORE-only tree reachable from here")
    listing = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", ref],
        cwd=REPO, capture_output=True, text=True,
    )
    assert listing.returncode == 0, f"cannot read {ref}: {listing.stderr.strip()}"
    tracked = [f for f in listing.stdout.split("\n") if f]
    assert len(tracked) > 100, f"{ref} listed only {len(tracked)} files, wrong ref?"

    # In a DOWNSTREAM instance the invariant holds only for files that are still
    # byte identical to upstream. An instance may legitimately fork a core skill
    # down to `user` (this tree has done exactly that with skills/remote/, which
    # carries machine specifics), and calling that a defect would make the guard
    # permanently red and therefore ignored. A file that has NOT diverged and
    # still classifies non-core is the real case: an update channel closed in
    # silence. In a CORE-only checkout there is nothing to diverge from, so every
    # tracked file is asserted.
    instance = (REPO / "bridge-config.yaml").exists()
    offenders = sorted(
        f for f in tracked
        if tier(f) != "core"
        and f not in UPSTREAM_NON_CORE_BY_DESIGN
        and not f.startswith(UPSTREAM_NON_CORE_PREFIXES)
        and not (instance and not _identical_to_upstream(f))
        and not _governed_by_a_declared_skill_scope(f)
    )
    assert not offenders, (
        f"{len(offenders)} file(s) ship on {ref} but classify non-core, so the next "
        "change to each one silently fails to promote:\n  " + "\n  ".join(offenders)
    )


# ---------------------------------------------------------------------------
# A CORE CI job may only execute CORE files.
#
# `.github/workflows/validate.yml` is named in the rules/operations.md core
# allowlist, so it promotes. A script it runs that classifies non-core does not
# travel with it, and upstream then runs a step pointing at a file that never
# arrived. This is not hypothetical: the remote-inventory contract was merged
# upstream with its CI step and its suite classified `user` on the same day.
# ---------------------------------------------------------------------------
_RUNNABLE_IN_CI = re.compile(r"(?:scripts|skills|infra|workflow|bin)/[\w./-]+\.(?:sh|py)")


def test_paths_a_core_ci_workflow_runs_are_core():
    workflow = REPO / ".github" / "workflows" / "validate.yml"
    if not workflow.exists():
        pytest.skip("no validate.yml in this checkout")
    assert tier(".github/workflows/validate.yml") == "core", (
        "premise gone: validate.yml no longer promotes, so this guard proves nothing"
    )
    named = sorted(set(_RUNNABLE_IN_CI.findall(workflow.read_text(encoding="utf-8"))))
    executed = [p for p in named if (REPO / p).exists()]
    assert executed, "found no runnable path in validate.yml, so the regex stopped matching"
    offenders = sorted(p for p in executed if tier(p) != "core")
    assert not offenders, (
        "validate.yml promotes and runs these, but they classify non-core and stay "
        "behind, so upstream CI would call a file that never shipped:\n  "
        + "\n  ".join(f"{p} -> {tier(p)}" for p in offenders)
    )


def test_a_user_surface_keeps_its_tests_local():
    """The `_tests` rule must not over-reach into a whole-folder USER surface.

    `workflow/checks/` is USER end to end by decision (see above), companions
    included. The `_tests` rule runs FIRST in classify_file, so ordering is not
    what holds this out. The enumeration in WRAPPER_TESTS_CORE does. This pins
    that: widening it to a shape would route an instance's own probe fixtures at
    the public repo, and nothing downstream would object.
    """
    assert tier("workflow/checks/_tests/probe.yaml") == "user"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


def test_per_instance_declaration_files_are_user():
    """`edges.yaml` and `context-budget.user.yaml` name an instance's own paths.

    Both are declarations ABOUT the local tree — which files it has, which of
    their references are excused and why. Classified `core` they would ride a
    promote upward carrying one instance's directory layout into a public repo,
    and nothing would say so: the tracked ones would simply be carried, and the
    gitignored one would be missed on the day somebody tracks it, which is
    exactly what a private instance using GitHub as offsite backup does.

    Found while shipping the edge guard, on the same day the reachability check
    found five families nobody had named. The pattern is the same one that had
    already bitten `infra/remotes/_tests/`: a new family next to a registered
    one, and the list was generated once and never re-generated.
    """
    for path in ("edges.yaml", "context-budget.user.yaml"):
        assert tier(path) == "user", path


def test_the_core_budget_itself_stays_core():
    """The counterpart. `context-budget.yaml` is the shipped policy."""
    assert tier("context-budget.yaml") == "core"
