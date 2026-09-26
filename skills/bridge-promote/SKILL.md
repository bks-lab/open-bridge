---
name: bridge-promote
description: >-
  Promote CORE changes from your user branch to upstream by scope (core to OSS
  upstream, org to org overlay). Runs mandatory content-safety checks, opens
  fork-based PRs. For file-level contributions use bridge-contribute. Trigger:
  "/bridge-promote", "promote", "cherry-pick", "push to upstream".
metadata:
  scope: core
---

# Bridge Promote — Scope Routing

Routes commits from `user/*` to the right upstream based on `scope:`
frontmatter (or path inference). See CLAUDE.md § Tier Model.

| Commit scope | Goes to | How |
|---|---|---|
| `scope: core` (or unset, on CORE-allowlist path) | the upstream with **`scope: core`** (e.g. `bks-lab/open-bridge:main`) plus any org/personal overlay that also carries it | Cherry-pick to local `development`, then PR to the OSS upstream |
| `scope: org` | the upstream with **`scope: org`** only (your org overlay, e.g. `<your-org>/<your-bridge>:development`) | Cherry-pick + PR to that repo |
| `scope: personal` | the upstream with **`scope: personal`** only (your personal overlay) | Cherry-pick + PR to that repo |
| `scope: user` / `private` | **stays local** on `user/{name}` | No-op |

**Destination selection is by SCOPE, never by `role:` alone.** For a
commit/file of scope `S`, the destination is the `bridge-config.yaml.upstreams[]`
entry whose **`scope:` field == `S`** — `core`→the `scope: core` upstream,
`org`→the `scope: org` upstream, `personal`→the `scope: personal` upstream.
Two upstreams may now share `role: org-overlay` (an org overlay **and** a
personal overlay), so `role` no longer identifies a unique destination.

**FAIL-CLOSED guard (mandatory).** Before routing, count the upstreams with
`role: org-overlay`. If that count is `> 1` **and** the routing would still
pick any destination by `role` (rather than by a matching `scope:` field),
**ABORT** — do not guess. Message: *"Ambiguous routing: N upstreams carry
`role: org-overlay` but a destination is being chosen by role. Route by
`upstreams[].scope` (org→`scope: org`, personal→`scope: personal`) instead.
Aborting rather than risk sending personal PII to the org overlay or customer
content to the personal repo."*

**HARD GATE — personal upstream stays disabled for real promotes until proven.**
Do not enable the `scope: personal` upstream for a non-`--dry-run` promote until
a `--dry-run` routing matrix shows **every** `scope: personal` file routed to the
personal upstream **and every** `scope: org` file routed to the org upstream,
with **zero cross-routes**. Until that dry-run is green, treat `scope: personal`
files as local-only.

If you don't have an org overlay configured, only `scope: core` commits
get promoted; `scope: org` / `scope: personal` commits stay on your user branch.

Read the referenced file ONLY when triggered.

## Arguments

| Argument | Effect | Default |
|----------|--------|---------|
| `(none)` | Full promote workflow with scope-routing | — |
| `--dry-run` | Analyze only, don't cherry-pick or push | false |
| `--repo <name>` | Force destination (matches a name in `upstreams[]`), skip auto-routing | auto |

## Prerequisites

- Current branch must be `user/*`. Refuses on `development` or `main`.
- `bridge-config.yaml.upstreams[]` defines available targets — the
  template ships the shared OSS upstream (`bks-lab/open-bridge`,
  `contribute: true`) by default; optionally a
  `<your-org>/<your-bridge>` overlay.
- For PR submission: `gh` authenticated. **No push access to the
  upstream required** — open-bridge PRs go fork-based (`gh repo fork`
  once, push the branch to your fork, `gh pr create --repo
  bks-lab/open-bridge`). See the bridge-contribute skill
  (`skills/bridge-contribute/references/workflow.md` § Step 5).
- Your own leak roster in `scripts/leak-patterns-internal.txt`
  (local-only) — your customer/person patterns for the safety gate.

## Decision Tree

```
User wants to...
├── Promote commits (auto-routed by scope)   → references/workflow.md
├── Dry-run analysis only                    → references/workflow.md (stop after Step 4)
├── Force one specific upstream              → references/workflow.md § --repo override
├── Scan branch for contributions            → bridge-contribute skill (/contribute)
├── Adapt/generalize content                 → bridge-contribute skill § Adapt mode
└── Questions about CORE/USER/ORG split      → Answer from CLAUDE.md § Tier Model
```

## Safety

Before any cherry-pick or push, a **mandatory** two-layer content-safety
gate runs — per destination repo:

1. `python3 scripts/no-scrub-leak.py {outgoing files}` — `scripts/no-scrub-leak.py`
   is a shared repo-root utility shipped with the Bridge repo itself, not a
   file inside this skill's own directory. It checks universal
   classes (absolute user paths, key/token shapes) plus **your own
   roster** from `scripts/leak-patterns-internal.txt` (you maintain your
   customer/PII regexes there; the shipped scanner cannot know them).
2. The blocklist scan from `rules/promote-safety.md` — the OSS upstream
   uses the strictest blocklist (no org/customer/personal leaks); your
   org overlay may use a relaxed one (customer refs OK, personal
   blocked). See `bridge-config.yaml.promote.content_blocklist`.

**REFUSE path:** personal-PII or roster hits exclude the affected
files/commits from the PR — no override flag. Remediation: adapt via
`/contribute --adapt` and re-scan, or drop them. Clean items still ship.
