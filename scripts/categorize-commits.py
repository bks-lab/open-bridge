#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Categorize commits by scope (core / org / user / personal) for /promote routing.

Mirrors the path → scope table in rules/operations.md § CORE/USER Separation.
Run from repo root.

Usage:
    scripts/categorize-commits.py                    # since last open-bridge snapshot
    scripts/categorize-commits.py --since 2026-05-03
    scripts/categorize-commits.py --range open-bridge/main..HEAD
    scripts/categorize-commits.py --commit <sha>     # detail for one commit
    scripts/categorize-commits.py --json             # machine-readable output

Output shows per-commit category + file-level breakdown for MIXED commits,
so /promote can decide which files to cherry-pick by path-selection rather
than full-commit cherry-pick (which fails on disjoint histories anyway).
"""
import argparse
import json
import os
import re
import subprocess
import sys

# ---------------------------------------------------------------------------
# Path → scope table — MIRROR of rules/operations.md § CORE/USER Separation.
# Keep in sync with operations.md (manual — no automated drift check yet).
#
# Scope is now STRUCTURAL: tier is decided by where a file lives, not a tag.
# Whole folders (work/, rules/user/) are user; the `_`-prefix split inside the
# cluster wrappers (identity/ infra/ workflow/) marks `_schema`/`_template`
# core vs every other instance user; skill tier lives in `metadata.scope`,
# read from each skill's SKILL.md below.
# ---------------------------------------------------------------------------

USER_PATTERNS = [
    r"^work/",                                        # incl. the job-application pipeline stream
    r"^rules/user/",                                  # user-tier rules (applications, …) — folder = tier
    r"^docs/applications\.md$",                       # personal applications feature — user-tier
    r"^bridge-config\.yaml$",
    r"^bridge-deck\.config\.yaml$",
    r"^overlays\.lock\.yaml$",                         # generated org-overlay lockfile — local-only, never promoted
    r"^\.bridge/",                                     # sparse org-overlay cache (.bridge/overlays/<name>/) — local-only
    # NB: the overlay ENGINE stays core — scripts/overlay.py + docs/schemas/*
    # match no USER/ORG pattern and fall through to CORE (ships to open-bridge).
    r"^identity/personas/(?!_(schema|template))",     # personas/<id>.yaml
    r"^identity/mandants/(?!_(schema|template))",     # mandants/<id>.yaml
    r"^identity/accounts/(?!_(schema|template))",     # accounts/<id>.yaml — instance-specific
    r"^infra/remotes/(?!_(schema|template))",
    r"^infra/channels/(?!_(schema|template))",
    r"^infra/instances/(?!_(schema|template))",       # instances/<id>.yaml — names real repos/customers (instances → user; _schema/_template stay core)
    r"^infra/backups/(topology|_state)\.yaml$",
    r"^infra/backups/launchd/",                       # instance-specific launchd plists
    r"^infra/backups/volumes/",
    r"^workflow/calendars/(?!_(schema|template))",
    # The literal carves below are LOAD-BEARING: VERIFIED_CORE runs *after* this
    # list, so without them these two upstream-identical files never reach it.
    # `_(schema|template)` alone does not match `_doc-system.template.yaml` —
    # the distinguishing word sits in the middle, not at the start.
    r"^workflow/contexts/(?!_(schema|template)|_doc-system\.template\.yaml$|customer-a\.yaml$)",
    r"^workflow/projects/(?!_(schema|template)|README\.md$)",
    r"^identity/voiceprints/",                        # biometric speaker embeddings (GDPR Art. 9)
    r"^identity/contracts/(?!_(schema|template))",    # contracts/<id>.yaml — customer-no/persona PII
    r"^protocols/standing-orders/user/",              # user-authored orders (mirrors rules/user/); shipped defaults stay CORE

    # --- added 2026-08-01: families that reached the fail-open `return "core"` ---
    # Each CORE set below is enumerated from `git ls-tree open-bridge/main -- <dir>`,
    # i.e. what upstream demonstrably ships — not from a shape predicate. A shape
    # predicate ("anything starting with _") is fail-OPEN for the next file nobody
    # anticipated; an enumeration fails the other way, which is the recoverable one.
    #
    # AGENTS.md § Agents: the generic runtime + template ship CORE, but every
    # agents/<name>/ INSTANCE is USER. 19+6 files carried the operator's identity,
    # calendars and Graph/KeyVault wiring straight at the public repo.
    r"^agents/(?!_runtime/|_template/|_gateway/|tests/|__init__\.py$|README\.md$|pyproject\.toml$|\.gitignore$)",
    # identity/agent/: deny-by-default. The old (IDENTITY|SOUL)-only branch missed
    # IDENTITY-lore.md, and would miss the next file added here too.
    r"^identity/agent/(?!(?:README\.md|_schema\.yaml|_soul-deck\.yaml|_soul-deck\.schema\.yaml|_template\.IDENTITY\.md|_template\.SOUL\.md)$)",
    # Per-instance branding inside a scope:core skill. Must precede the skill
    # frontmatter dispatch below, which would otherwise claim it as core.
    # This is the FALLBACK for undeclared branding; a theme that declares
    # `meta.scope:` re-tiers itself (and its logo) earlier — see _declared_branding_scope.
    r"^skills/bridge-greeting/assets/logos/(?!bridge\.txt$)",
    # themes/ is whole-folder CORE, so an instance theme is a structural exception.
    r"^themes/(?!_)(?!professional(?:-de)?\.yaml$)[^/]+\.yaml$",
    # workflow/checks/ — the whole surface is instance-local (decision 2026-08-01).
    # Unlike its sibling wrappers there is no CORE half to preserve: upstream has
    # never shipped a checks/ folder, and the only consumer is the `user`-scoped
    # checkup skill. So the `_`-companions are USER here too, which is why this
    # sits in the pattern list rather than relying on the `_`-prefix rule.
    r"^workflow/checks/",
    # Declarations ABOUT the local tree: which files this instance has, which
    # of their references are excused and why. Classified `core` they would
    # ride a promote upward carrying one instance's directory layout into a
    # public repo, and nothing would say so. `context-budget.user.yaml` is
    # gitignored by default and would have been missed the day an instance
    # tracks it — which a private instance using GitHub as offsite backup does.
    # `reachability-scenarios.yaml` belongs here too: the CORE script that reads
    # it, `scripts/check-reachability.py`, already declares it instance-owned.
    r"^edges\.yaml$",
    r"^context-budget\.user\.yaml$",
    r"^workspaces\.lock\.yaml$",                      # sibling of overlays.lock.yaml above
    r"^reachability-scenarios\.yaml$",                 # instance's own machine/customer names (check-reachability.py)
    # Per-tier INVERTED: these exist on both sides and must never be copied either
    # way. .bridge-origin in particular tells the push guard whether the origin is
    # public — promoting ours would disarm the guard downstream.
    r"^\.gitignore$",
    r"^\.bridge-origin$",
    r"^imports/(?!\.gitkeep$)",                       # AGENTS.md § Scope: whole folder = USER
]

ORG_PATTERNS = [
    r"^ecosystem\.yaml$",                             # instance-base ecosystem (org overlay carries it)
    # ANY org's registry fragment — `ecosystem.<org>.yaml`. This matched a single
    # literal filename until 2026-08-01, which failed twice over: another org's
    # fragment classified `core` and shipped to the public repo, and a CORE file
    # that ships to open-bridge carried an org name (AGENTS.md: a core file reads
    # config, it never embeds org IDs). The carve-outs are the two non-org members
    # of the family — `example` is the CORE template that must keep shipping, and
    # `personal`/`local` are matched earlier by PERSONAL_PATTERNS anyway (named
    # here as a backstop, in case that list is ever reordered).
    r"^ecosystem\.(?!example\.|personal\.|local\.)[a-z0-9][a-z0-9-]*\.yaml$",
    r"^rules/org/",                                   # org-tier rules (wiki-navigation, wiki-principles) — folder = tier
    # NOTE: skills are NOT path-matched here — they route by `metadata.scope`
    # read from SKILL.md below. A hardcoded skill path would SHADOW the
    # frontmatter and mis-route a re-scoped skill. Org skills are caught by the
    # frontmatter read.
    r"^\.claude/agents/customer-a-",
    r"^workflow/contexts/customer-a\.yaml$",          # CORE example context stays org (doc-system is now frontmatter-driven — see classify_file)
    r"^identity/mandants/org\.yaml$",
    r"^docs/(public-release-cleanup|three-tier-architecture|wiki-architecture)\.md$",
]

# Personal tier — the operator's own private overlay (a `role: org-overlay` upstream
# with `scope: personal`; the repo is named in bridge-config.yaml, not here).
# Path-based personal tiers below; cluster-wrapper CONFIG files reach `personal`
# via a frontmatter `scope: personal` (see _CLUSTER_WRAPPER_RE / classify_file).
PERSONAL_PATTERNS = [
    r"^rules/personal/",                              # personal-tier rules — folder = tier (parallels rules/org, rules/user)
    r"^ecosystem\.personal\.yaml$",                   # personal/freelance registry fragment
    r"^ecosystem\.local\.yaml$",                      # legacy name of ecosystem.personal.yaml (pre-rename) — was mis-classified CORE
]

# Cluster-wrapper CONFIG instance files whose tier is decided by a frontmatter
# `scope:` (personal/user/org/core), WINNING over the path default. One level
# deep, real instances only (excludes _schema/_template and nested bot dirs).
#
# `infra/remotes` joined the list 2026-08-01. Every file there already carried a
# `scope:` (the anti-deletion tripwire — see the 98fb1c0 bulk-rm incident), but
# nothing read it, so an org-owned managed service tagged `scope: org` still
# classified `user`. That file documents the workaround in its own header and
# had been hand-carried to the org overlay for six weeks — which meant
# `overlay-export --scope org` saw it as stale and would PRUNE it.
# Adding the wrapper moves exactly that one file; the 16 personal machines
# declare `scope: user` and stay local, and an undeclared remote falls through
# to the path rule (user), so the read fails closed.
_CLUSTER_WRAPPER_RE = re.compile(
    r"^(?:identity/(?:personas|mandants|accounts|contracts)"
    r"|infra/(?:channels|remotes)"
    r"|workflow/(?:contexts|projects))/"
    r"(?!_(?:schema|template))"
    r"[^/]+\.(?:yaml|md)$"
)

# Frontmatter scope token → routing bucket. The four generic tiers plus
# `private`, which stays local like `user`.
_BASE_SCOPE_MAP = {
    "core": "core", "org": "org",
    "personal": "personal", "user": "user", "private": "user",
}


def _instance_scope_aliases() -> dict[str, str]:
    """Instance-authored scope tokens, read from bridge-config.yaml `upstreams[]`.

    An instance may name its overlay and then tag files with that NAME rather
    than the generic tier — e.g. `scope: <overlay-name>` meaning "the overlay
    called that", i.e. `org`. Such an alias used to sit as a literal in the map
    above, which put a specific organisation's name inside a CORE file that
    ships to the public repo — the exact anti-pattern AGENTS.md names ("reads
    config, never embeds org IDs"), and a content-blocklist hit that made this
    very file unpromotable.

    The config already carries the mapping: each `upstreams[]` entry has a `name`
    and the `scope` it routes. So read it rather than restate it. Hand-parsed
    (this module is dependency-free by design, no yaml import) over the exact
    shape scripts/overlay.py writes; anything unparseable yields no aliases,
    which degrades to the generic tokens rather than mis-routing.
    """
    aliases: dict[str, str] = {}
    try:
        with open("bridge-config.yaml", encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return aliases
    in_block = False
    name: str | None = None
    for raw in lines:
        if re.match(r"^[A-Za-z_]", raw):                 # a new top-level key
            in_block = raw.startswith("upstreams:")
            name = None
            continue
        if not in_block:
            continue
        if re.match(r"^-\s", raw):                        # next list item
            name = None
        m = re.match(r"^-?\s*name:\s*([A-Za-z0-9._-]+)", raw)
        if m:
            name = m.group(1)
            continue
        m = re.match(r"^\s*scope:\s*([a-z]+)", raw)
        if m and name and m.group(1) in _BASE_SCOPE_MAP:
            aliases[name] = _BASE_SCOPE_MAP[m.group(1)]
    # never let an alias shadow a generic token
    return {k: v for k, v in aliases.items() if k not in _BASE_SCOPE_MAP}


_SCOPE_MAP = {**_BASE_SCOPE_MAP, **_instance_scope_aliases()}

# Everything else not matched above defaults to CORE.

# ---------------------------------------------------------------------------

# scripts/ is an ALLOWLIST, not a denylist. rules/operations.md already names
# a handful of promotable scripts while globbing its neighbours (docs/**,
# themes/**) — that contrast is allowlist INTENT the router never implemented,
# so scripts/ silently became a catch-all that ships anything new by default.
# A script is the artifact most likely to hardcode a host, an absolute path, a
# launchd label or a credential path — which is exactly what the two offenders
# (sync-pii-to-homeserver.sh, push-bridge-state.sh) did.
#
# Generated from `git ls-tree -r --name-only open-bridge/main -- scripts`, i.e.
# what upstream demonstrably ships. Cost of the allowlist, accepted knowingly:
# a genuinely-core NEW script must be registered here deliberately. That failure
# is visible in the categorize table and one line to fix; the denylist failure
# is an irreversible push into a public MIT repo.
SCRIPTS_CORE_ALLOWLIST = frozenset({
    "scripts/bin/gh",
    "scripts/bridge-dashboard.py",
    "scripts/categorize-commits.py",
    "scripts/check-figure-counts.py",
    "scripts/check-inline-scripts.py",
    "scripts/check-site-links.py",
    "scripts/extract-bridge-state.py",
    "scripts/extract-frontmatter.py",
    "scripts/gen-board.py",
    "scripts/generate-bridge.py",
    "scripts/hooks/pre-commit",
    "scripts/hooks/pre-push",
    "scripts/no-scrub-leak.py",
    "scripts/okf-export.py",
    "scripts/overlay.py",
    "scripts/scaffold-user.sh",
    "scripts/system-discovery.py",
    "scripts/tests/fixtures/broken-depends-on.yaml",
    "scripts/tests/fixtures/broken-issue-repo.yaml",
    "scripts/tests/fixtures/broken-wiki-ref.yaml",
    "scripts/tests/fixtures/broken-workspace-ref.yaml",
    "scripts/tests/fixtures/overlay/core-refusal-overlay/overlay.manifest.yaml",
    "scripts/tests/fixtures/overlay/core-refusal-overlay/tree/identity/mandants/README.md",
    "scripts/tests/fixtures/overlay/core-refusal-overlay/tree/workflow/contexts/clean.yaml",
    "scripts/tests/fixtures/overlay/core-refusal-overlay/tree/workflow/projects/_fixture.yaml",
    "scripts/tests/fixtures/overlay/malformed-overlay/overlay.manifest.yaml",
    "scripts/tests/fixtures/overlay/malformed-overlay/tree/workflow/contexts/x.yaml",
    "scripts/tests/fixtures/overlay/overlay-a/overlay.manifest.yaml",
    "scripts/tests/fixtures/overlay/overlay-a/tree/workflow/contexts/shared.yaml",
    "scripts/tests/fixtures/overlay/overlay-b/overlay.manifest.yaml",
    "scripts/tests/fixtures/overlay/overlay-b/tree/workflow/contexts/shared.yaml",
    "scripts/tests/fixtures/overlay/secret-overlay/overlay.manifest.yaml",
    "scripts/tests/fixtures/overlay/secret-overlay/tree/identity/accounts/leaky.yaml",
    "scripts/tests/fixtures/overlay/secret-overlay/tree/workflow/contexts/clean-sibling.yaml",
    "scripts/tests/fixtures/overlay/traversal-overlay/escaped.yaml",
    "scripts/tests/fixtures/overlay/traversal-overlay/overlay.manifest.yaml",
    "scripts/tests/fixtures/overlay/traversal-overlay/tree/workflow/contexts/ok.yaml",
    "scripts/tests/fixtures/tracker-sync/work/tasks/task-bridgeonly/STATUS.md",
    "scripts/tests/fixtures/tracker-sync/work/tasks/task-closedlinked/STATUS.md",
    "scripts/tests/fixtures/tracker-sync/work/tasks/task-insync/STATUS.md",
    "scripts/tests/fixtures/tracker-sync/work/tasks/task-local-ahead/STATUS.md",
    "scripts/tests/fixtures/tracker-sync/work/tasks/task-mismatch/STATUS.md",
    "scripts/tests/fixtures/tracker-sync/work/tasks/task-orphanlocal/STATUS.md",
    "scripts/tests/fixtures/tracker-sync/work/tasks/task-otherrepo/STATUS.md",
    "scripts/tests/fixtures/tracker-sync/work/tasks/task-remote-ahead/STATUS.md",
    "scripts/tests/fixtures/tracker-sync/work/trackers/github/demo.json",
    "scripts/tests/fixtures/tracker-sync/work/trackers/github/demo2.json",
    "scripts/tests/fixtures/tracker-sync/workflow/projects/demo.yaml",
    "scripts/tests/fixtures/valid-minimal.yaml",
    "scripts/tests/fixtures/warn-archived-in-workspace.yaml",
    "scripts/tests/test-okf-export.sh",
    "scripts/tests/test-overlay.sh",
    "scripts/tests/test-push-guard.sh",
    "scripts/tests/test-system-discovery.sh",
    "scripts/tests/test-tracker-sync.sh",
    "scripts/tests/test-validate-ecosystem.sh",
    "scripts/tests/test-workspace-registry.sh",
    "scripts/tests/test-workspace-skill.sh",
    "scripts/tests/test-workspace.sh",
    "scripts/tests/test_okf_export.py",
    "scripts/tracker-sync.py",
    "scripts/validate-bridge.py",
    "scripts/validate-ecosystem.py",
    "scripts/validate-skill-scope.py",
    "scripts/validate-status.py",
    "scripts/verify-constellation-links.py",
    "scripts/workspace.py",
    "scripts/workspace_registry.py",
    # Local-only, each VERIFIED generic against promote.content_blocklist:
    "scripts/overlay-export.py",
    "scripts/tests/test_overlay_secret_scan.py",
    # NOT listed on purpose: test_push_guard_content_net.py names real instance
    # paths BY DESIGN, which is what makes it a leak-regression test. It stays
    # `user`, and it is not tracked upstream either.
    #
    # Registered 2026-08-27, all thirteen already tracked on open-bridge main and
    # byte-identical here. They were added next to files that ARE listed, and the
    # set above was generated once and never re-generated, so each shipped, and
    # the router then refused to carry the next change to it. Nothing said so.
    # test_scope_router.py sat here as a deliberate exclusion for naming real
    # instance paths; it was made portable afterwards (its own docstring states
    # it) and the exclusion outlived its reason.
    #
    # test_every_file_upstream_ships_stays_core is what makes this list stop
    # going stale: it re-derives the answer from the upstream tree on every run.
    "scripts/bridge-divergence-check.py",
    "scripts/capability_registry.py",
    "scripts/lib/__init__.py",
    "scripts/lib/registry_io.py",
    "scripts/tests/test-capability-registry.sh",
    "scripts/tests/test-extract-frontmatter.sh",
    "scripts/tests/test-gen-board.sh",
    "scripts/tests/test-validate-bridge-rule-map.sh",
    "scripts/tests/test_extract_frontmatter.py",
    "scripts/tests/test_gen_board.py",
    "scripts/tests/test_scope_router.py",
    "scripts/tests/test_validate_bridge_rule_map.py",
    "scripts/upstream-monitor.sh",
    # Registered 2026-08-29 with the context budget. validate.yml runs all three
    # in CI, so a non-core classification would have upstream CI call files that
    # never shipped. test_paths_a_core_ci_workflow_runs_are_core caught exactly
    # that, before the first human read the diff.
    "scripts/bridge-config.py",
    "scripts/check-doc-routes.py",
    "scripts/lib/standing_orders.py",
    "scripts/measure-context.py",
    "scripts/standing-orders.py",
    "scripts/worklog.py",
    "scripts/tests/test-bridge-config.sh",
    "scripts/tests/test-doc-routes.sh",
    "scripts/tests/test-measure-context.sh",
    "scripts/tests/test-standing-orders.sh",
    "scripts/tests/test-worklog.sh",
    "scripts/tests/test_bridge_config.py",
    "scripts/tests/test_doc_routes.py",
    "scripts/tests/test_measure_context.py",
    "scripts/tests/test_standing_orders.py",
    "scripts/tests/test_worklog.py",
    # Registered 2026-08-28: both are generic guards with no instance name in
    # them, both are RUN by validate.yml, and that workflow promotes. A core CI
    # job calling a file classified `user` is the same defect the `_tests`
    # families had, one directory over.
    "scripts/check-generated-output.py",
    "scripts/tests/test_generated_output_escapes.py",
    # Registered 2026-08-30 with the context index. Same reason as the block
    # above: validate.yml runs the suite and the `--check` guard, so a
    # non-core classification would have upstream CI call files that never
    # shipped.
    "scripts/context-index.py",
    "scripts/lib/context_index.py",
    "scripts/tests/test-context-index.sh",
    "scripts/tests/test_context_index.py",
    # Registered 2026-08-30 with the reachability contract. Same reason again:
    # validate.yml runs the suite, the check and its mutation battery.
    "scripts/check-reachability.py",
    "scripts/tests/test-reachability.sh",
    "scripts/tests/test_reachability.py",
    # Registered 2026-08-30 with the edge guard. validate.yml runs both.
    "scripts/check-edges.py",
    "scripts/tests/test-edges.sh",
    # Registered 2026-08-30 with the pre-commit always-on gate; validate.yml
    # runs it, so a non-core classification would have upstream CI call a file
    # that never shipped.
    "scripts/tests/test-precommit-guards.sh",
    # Registered 2026-08-30 with the push-guard commit-set contract. Same
    # reason as its neighbours: validate.yml runs it, so a non-core
    # classification would have upstream CI call a file that never shipped.
    "scripts/tests/test-push-guard-commit-set.sh",
    "scripts/tests/test_edges.py",
    # Registered with the guarded auto-merge (upstream-autoupdate.sh + its
    # installer). Same reason as scripts/upstream-monitor.sh above, which is
    # the reporting half of the same pair: the allowlist is deliberate, so a
    # new script that genuinely belongs to CORE has to say so here or the
    # next change to it silently fails to promote.
    "scripts/install-upstream-autoupdate.sh",
    "scripts/upstream-autoupdate.sh",
})


# Upstream-identical files that a USER pattern above would otherwise claim.
# Admission criterion, enforce it in review:
#     git ls-tree -r open-bridge/main -- <path>   → present
#     git diff open-bridge/main -- <path>          → EMPTY
# All nine verified byte-identical on 2026-08-01. This is NOT a README shape
# rule — it is a nine-element literal list that happens to contain four READMEs,
# each individually checked. identity/voiceprints/README.md and
# infra/channels/bots/igor-zahnarzt/README.md are absent BY CONSTRUCTION.
# Position (after PERSONAL/USER/ORG) means a careless addition here degrades to
# a no-op instead of overriding a denylist.
VERIFIED_CORE = frozenset({
    "identity/agent/README.md",
    "identity/agent/_soul-deck.schema.yaml",
    "identity/agent/_soul-deck.yaml",
    "identity/agent/_template.IDENTITY.md",
    "identity/agent/_template.SOUL.md",
    "infra/backups/README.md",
    "infra/transcriptions/README.md",
    "workflow/contexts/_doc-system.template.yaml",
    "workflow/projects/README.md",
})

# The root repair. _CLUSTER_WRAPPER_RE enumerates seven types; AGENTS.md § Layout
# documents a GENERIC <wrapper>/<types>/ rule. Every type added since — checks,
# workspaces, utilities, transcriptions — got neither a dispatch nor a pattern and
# landed on the fail-open `return "core"`. Four silent leaks, one mechanism.
#
# rules/operations.md already PRESCRIBES fail-closed here ("a missing or mistaken
# tag never leaks upward, it just fails to promote"); the router simply never
# implemented it outside those seven types.
#
# The lookahead names TWO LITERALS, never a `^_` predicate: `infra/backups/_state.yaml`
# does not satisfy it, so it falls through to `user` — a second, independent net
# under the USER_PATTERNS entry that already claims it. Structurally this fallback
# can only ever return "user", so it cannot lift any README into core.
CLUSTER_WRAPPER_FALLBACK = re.compile(
    r"^(?:identity|infra|workflow)/[a-z0-9][a-z0-9-]*/(?!_(?:schema|template)\.yaml$)"
)

# `_tests/` beside a wrapper schema is that schema's own regression suite, so it
# is CORE material by construction and belongs with the schema it guards. The
# fallback above cannot see that: its lookahead names two literals, so a whole
# directory of contract fixtures falls through to `user`. infra/remotes/_tests/
# shipped upstream on 2026-08-27 together with the CI step that runs it, and the
# router said `user` for all ten files on the same day.
#
# ENUMERATED, not a `_tests` predicate, and the reason is not symmetry with the
# comment above: fixtures are the one place where instance data legitimately sits
# while a suite is being written. A family joins this list once its fixtures are
# generic, which is a decision somebody makes, not a shape a regex can read.
#
# Checked FIRST in classify_file, ahead of the frontmatter dispatch, and that is
# the load-bearing part. A fixture of a declaration IS a declaration: every file
# in infra/remotes/_tests/ carries `scope: user`, because that is the value a
# remote inventory is supposed to have. The dispatch read it as the file's own
# tier and answered `user` before any path rule ran. A fixture's `scope:`
# describes what it depicts, never where it lives, and only an enumerated
# family may claim that exemption, which is why the set above is a list and not
# a shape.
WRAPPER_TESTS_CORE = re.compile(r"^(?:infra/remotes|workflow/workloads)/_tests/")
# workflow/workloads joined on 2026-08-27, when its 69 fixtures were rewritten
# generic and in English for exactly this step. Before that they named real
# hosts, real customers and one real person, so the family stayed out and its
# CI guard stayed red, which is the shape this list is meant to have.


def _unquote(path: str) -> str:
    """Undo git's `core.quotePath` escaping, defensively.

    files_in_commit() no longer produces quoted paths, but classify_file is a
    PUBLIC entry point — scripts/overlay.py and scripts/overlay-export.py both
    import it, and a future caller may hand over raw `git` output. A single
    leading quote would otherwise break every `^` anchor at once and default the
    file to core, so normalise here rather than trusting every caller.
    """
    if len(path) > 1 and path[0] == '"' and path[-1] == '"':
        try:
            return path[1:-1].encode("ascii", "backslashreplace").decode(
                "unicode_escape"
            ).encode("latin-1").decode("utf-8")
        except (UnicodeDecodeError, UnicodeEncodeError):
            return path[1:-1]
    return path


def classify_file(path: str) -> str:
    path = _unquote(path)
    # Before everything, including the frontmatter dispatch below: see
    # WRAPPER_TESTS_CORE. A contract fixture depicts a declaration and therefore
    # carries that declaration's `scope:`, which is not its own tier.
    if WRAPPER_TESTS_CORE.search(path):
        return "core"
    # Cluster-wrapper config files: a frontmatter `scope:` WINS over the path
    # default. No frontmatter scope ⇒ fall through to the path rules below
    # (fail-safe: a missing tag defaults to `user`, never leaking upward).
    if _CLUSTER_WRAPPER_RE.search(path):
        token = read_frontmatter_scope(path)
        mapped = _SCOPE_MAP.get(token) if token else None
        if mapped:
            return mapped
    # A theme's own `meta.scope:` (and the logo it declares) WINS over the path
    # default, same precedence as the cluster-wrapper dispatch above.
    branding = _declared_branding_scope(path)
    if branding:
        return branding
    for p in PERSONAL_PATTERNS:
        if re.search(p, path):
            return "personal"
    for p in USER_PATTERNS:
        if re.search(p, path):
            return "user"
    for p in ORG_PATTERNS:
        if re.search(p, path):
            return "org"
    # scripts/ is allowlisted, not denylisted — see SCRIPTS_CORE_ALLOWLIST.
    if path.startswith("scripts/") and path not in SCRIPTS_CORE_ALLOWLIST:
        return "user"
    # Skill/agent files — frontmatter `scope:` overrides path inference.
    # For ANY file under skills/<name>/, read the scope from that skill's SKILL.md
    # (fixes the leak where skills/<name>/references/foo.md was treated as core
    # even though skills/<name>/SKILL.md declares a non-core scope).
    #
    # FAIL-CLOSED: a skills/<dir>/ with no SKILL.md (or an unrecognised token)
    # used to fall through to the core default. skills/sequential-thinking-workspace/
    # did exactly that and shipped customer names, while its sibling skill declares
    # `personal`. Mapping through _SCOPE_MAP also stops a raw token leaking out as
    # a pseudo-tier that category_for_scopes() would collapse to MIXED.
    m = re.match(r"^skills/([^/]+)/", path)
    if m:
        token = read_frontmatter_scope(f"skills/{m.group(1)}/SKILL.md")
        return _SCOPE_MAP.get(token or "", "user")
    m = re.match(r"^\.claude/agents/([^/]+)\.md$", path)
    if m:
        scope = read_frontmatter_scope(path)
        if scope:
            return scope
    # NB: the former identity/agent/(IDENTITY|SOUL).md frontmatter branch lived
    # here and is now dead — the deny-by-default USER_PATTERNS entry claims the
    # whole directory earlier, and it missed IDENTITY-lore.md anyway. A branch
    # that can never fire is worse than no branch: the next reader believes it.
    if path in VERIFIED_CORE:
        return "core"
    if CLUSTER_WRAPPER_FALLBACK.search(path):
        return "user"
    return "core"


# ---------------------------------------------------------------------------
# Branding: themes declare their OWN tier, logos inherit it.
#
# `themes/` is whole-folder CORE, so anything else there used to be a hardcoded
# structural exception. But this router is itself a CORE file that ships to
# open-bridge — an org token baked in here is the exact anti-pattern AGENTS.md
# names ("reads config, never embeds instance logic, org IDs"). So a theme
# carries `meta.scope:` the way a skill carries `metadata.scope:`, and the logo
# inherits it through the `branding.logo_ascii:` link the theme already declares.
# Adding another org's theme then needs zero edits to this file.
#
# Undeclared stays undeclared: the two upstream themes have no `meta.scope`,
# fall through, and remain core; any other undeclared theme still lands on the
# USER_PATTERNS fallback above.
# ---------------------------------------------------------------------------
_THEME_RE = re.compile(r"^themes/(?!_)[^/]+\.yaml$")
_LOGO_RE = re.compile(r"^skills/[^/]+/assets/logos/[^/]+$")
_THEME_META_SCOPE_RE = re.compile(
    r"^meta:[ \t]*\n((?:[ \t]+.*\n?)*)", re.MULTILINE
)
_LOGO_BY_THEME_CACHE: dict[str, str] | None = None


def _theme_declared_scope(path: str) -> str | None:
    """Read `meta.scope:` from a theme file. None when it declares nothing."""
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8", errors="replace") as f:
        head = f.read(4000)
    block = _THEME_META_SCOPE_RE.search(head)
    if not block:
        return None
    m = re.search(r"^[ \t]+scope:\s*([a-z]+)", block.group(1), re.MULTILINE)
    return m.group(1) if m else None


def _logo_owner_map() -> dict[str, str]:
    """logo path -> owning theme path, from each theme's `branding.logo_ascii:`."""
    global _LOGO_BY_THEME_CACHE
    if _LOGO_BY_THEME_CACHE is not None:
        return _LOGO_BY_THEME_CACHE
    owners: dict[str, str] = {}
    try:
        names = sorted(os.listdir("themes"))
    except OSError:
        names = []
    for name in names:
        theme = f"themes/{name}"
        if not _THEME_RE.match(theme):
            continue
        try:
            with open(theme, encoding="utf-8", errors="replace") as f:
                text = f.read(4000)
        except OSError:
            continue
        for logo in re.findall(r"^\s*logo_ascii:\s*(\S+)", text, re.MULTILINE):
            owners.setdefault(logo.strip("\"'"), theme)
    _LOGO_BY_THEME_CACHE = owners
    return owners


def _declared_branding_scope(path: str) -> str | None:
    """Tier for a theme or a theme-owned logo, when the theme declares one."""
    if _THEME_RE.match(path):
        return _SCOPE_MAP.get(_theme_declared_scope(path) or "")
    if _LOGO_RE.match(path):
        owner = _logo_owner_map().get(path)
        if owner:
            return _SCOPE_MAP.get(_theme_declared_scope(owner) or "")
    return None


_SCOPE_READ_CAP = 1_048_576  # 1 MiB; the largest config in this tree is ~60 KB


def _blank_code_fences(text: str) -> str:
    """Replace ```...``` spans with blank lines, preserving line count/offsets."""
    def blank(m: "re.Match[str]") -> str:
        return "\n" * m.group(0).count("\n")
    return re.sub(r"^```.*?^```[^\n]*$", blank, text, flags=re.S | re.M)


def read_frontmatter_scope(path: str) -> str | None:
    if not os.path.exists(path):
        return None
    # The whole file, not a 2000-byte peek. A top-level `scope:` is a top-level
    # key wherever it stands, and a long comment header is normal in this tree:
    # measured 2026-08-20, two `workflow/projects/*.yaml` on one instance carry
    # `scope: org` at byte 2101 and byte 3127. Both read as
    # `user` under the old window. The direction was fail-safe (nothing leaks
    # upward), but overlay-export.py then classed them out of scope and a dry-run
    # export scheduled their mirror copies for deletion as stale.
    # Capped so a stray huge file cannot be slurped; config files are far below it.
    try:
        with open(path, encoding="utf-8") as f:
            head = f.read(_SCOPE_READ_CAP)
    except (OSError, UnicodeDecodeError):
        return None
    m = re.search(r"^---\s*\n(.*?)\n---", head, re.DOTALL | re.MULTILINE)
    if m:
        fm = m.group(1)
        # 1) top-level `scope:` inside the fence — sub-agents (.claude/agents/*.md),
        # rules, IDENTITY/SOUL keep it there.
        sm = re.search(r"^scope:\s*([a-z]+)", fm, re.MULTILINE)
        if sm:
            return sm.group(1)
        # 2) `metadata.scope` — skills/*/SKILL.md nest scope under metadata: for
        # skill-creator conformance (its validator forbids non-standard top-level keys).
        # Scope the search to the metadata: block so a `scope:` mention inside a
        # description block-scalar can't false-match.
        mb = re.search(r"^metadata:[ \t]*\n((?:[ \t]+.*\n?)*)", fm, re.MULTILINE)
        if mb:
            ms = re.search(r"^[ \t]+scope:\s*([a-z]+)", mb.group(1), re.MULTILINE)
            if ms:
                return ms.group(1)
        return None
    # 3) No `---` fence: a plain YAML config file (personas/mandants/accounts/
    # contracts) carries `scope:` as a BARE top-level key — a `---` fence would
    # break yaml.safe_load, so the tier lives at column 0 directly. Read it there.
    # (A top-level key is at col 0; a `scope:` value deeper in a nested block is
    # indented and won't match.)
    # Fenced code blocks are documentation, not frontmatter. Blanking them keeps a
    # documented `scope: core` example from becoming the file's own tier now that
    # the whole file is in scope of this search.
    sm = re.search(r"^scope:\s*([a-z]+)", _blank_code_fences(head), re.MULTILINE)
    if sm:
        return sm.group(1)
    return None


def commits_in_range(rev_range: str, since: str | None) -> list[tuple[str, str]]:
    cmd = ["git", "log", "--no-merges", "--pretty=format:%H|%s"]
    if since:
        cmd.append(f"--since={since}")
    if rev_range:
        cmd.append(rev_range)
    out = subprocess.check_output(cmd, text=True).strip()
    pairs: list[tuple[str, str]] = []
    for line in out.splitlines():
        if not line:
            continue
        sha, _, subj = line.partition("|")
        pairs.append((sha, subj))
    return pairs


def files_in_commit(sha: str) -> list[str]:
    # `core.quotePath` defaults to TRUE, so git wraps any path containing a
    # non-ASCII byte in quotes and octal-escapes it:
    #     "agents/alice/tools/verf\303\274gbarkeit.py"
    # The leading quote breaks the `^` anchor of EVERY pattern in PERSONAL /
    # USER / ORG simultaneously, and defeats read_frontmatter_scope's
    # os.path.exists — so one umlaut in a filename routes it straight to the
    # public repo. `-c core.quotePath=false` plus NUL separation removes both
    # the quoting and any newline-in-filename ambiguity at the source.
    out = subprocess.check_output(
        ["git", "-c", "core.quotePath=false", "diff-tree", "-z",
         "--no-commit-id", "--name-only", "-r", sha],
        text=True,
    )
    return [p for p in out.split("\0") if p]


def category_for_scopes(scopes: set) -> str:
    """Collapse a set of file-scopes to a commit category.

    Mirrors the {core}->CORE and {org}|{core,org}->Org pattern and extends it
    with {personal}|{core,personal}->Personal — `core` (generic) rides along
    with a single non-core tier. Any CROSS-tier mix (org+personal, user+personal,
    user+org, core+user, …) is MIXED and needs a path-selective cherry-pick.
    """
    if scopes == {"core"}:
        return "CORE"
    if scopes == {"org"} or scopes == {"core", "org"}:
        return "Org"
    if scopes == {"personal"} or scopes == {"core", "personal"}:
        return "Personal"
    if scopes == {"user"}:
        return "USER"
    return "MIXED"


def categorize_commit(sha: str) -> dict:
    files = files_in_commit(sha)
    by_file = {f: classify_file(f) for f in files}
    scopes = set(by_file.values())
    return {
        "sha": sha,
        "category": category_for_scopes(scopes),
        "files": by_file,
        "scopes_present": sorted(scopes),
    }


def render_table(results: list[dict], commits: list[tuple[str, str]]) -> None:
    subj_by_sha = {sha: subj for sha, subj in commits}
    for r in results:
        subj = subj_by_sha.get(r["sha"], "")[:70]
        print(f"{r['category']:5s}  {r['sha'][:7]}  {subj}")
        if r["category"] == "MIXED":
            for f, s in r["files"].items():
                print(f"        └─ {s:4s}  {f}")
    print()
    counts = {c: 0 for c in ["CORE", "Org", "Personal", "USER", "MIXED"]}
    for r in results:
        counts[r["category"]] += 1
    print(f"Total: {len(results)} commits  "
          f"[CORE={counts['CORE']}  Org={counts['Org']}  "
          f"Personal={counts['Personal']}  "
          f"USER={counts['USER']}  MIXED={counts['MIXED']}]")
    if counts["MIXED"]:
        print("\nMIXED commits need path-selective cherry-pick — "
              "see rules/operations.md § CORE/USER Separation.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", help="git --since date (e.g. 2026-05-03)")
    ap.add_argument("--range", default="HEAD",
                    help="git revision range (default: HEAD)")
    ap.add_argument("--commit", help="categorize a single commit and exit")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    if args.commit:
        result = categorize_commit(args.commit)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            render_table([result], [(args.commit, "")])
        return 0

    commits = commits_in_range(args.range, args.since)
    if not commits:
        print("No commits in range.", file=sys.stderr)
        return 0
    results = [categorize_commit(sha) for sha, _ in commits]
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        render_table(results, commits)
    return 0


if __name__ == "__main__":
    sys.exit(main())
