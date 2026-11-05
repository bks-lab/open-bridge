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
frontmatter (or path inference). See docs/org-overlays.md (tier model). A root `CLAUDE.md` classifies `user` and never promotes.

| Commit scope | Goes to | How |
|---|---|---|
| `scope: core` (or unset, on CORE-allowlist path) | the upstream with **`scope: core`** (e.g. `bks-lab/open-bridge:main`) plus any org/personal overlay that also carries it | Cherry-pick to local `development`, then PR to the OSS upstream |
| `scope: org` | the upstream with **`scope: org`** only (your org overlay, e.g. `<your-org>/<your-bridge>:development`) | Cherry-pick + PR to that repo, **unless it is a flat mirror** (below): then refuse and export |
| `scope: personal` | the upstream with **`scope: personal`** only (your personal overlay) | Same as `org`: cherry-pick + PR, or refuse and export for a flat mirror |
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

**FLAT-MIRROR GUARD (mandatory, per overlay destination).** An overlay repo
that carries `overlay.manifest.yaml` is read by `scripts/overlay.py` only below
its `defaults.source_root` (`tree/` when unset). A cherry-pick writes the same
path it had here, so the file lands at the overlay's repo root and no consumer
ever sees it, without any error. Before routing (workflow Step 0b), per overlay
destination, against the ref Step 0 fetched:

```bash
python3 scripts/overlay-export.py --check-ref {name}/{branch}
```

**Any non-zero exit means REFUSE that destination** (3: flat mirror, 2: the ref
does not resolve, so the fetch failed or the name is wrong): do not
cherry-pick, re-apply, or open a PR there, not even for `scope: core` commits. Tell the user to build the mirror
instead with `python3 scripts/overlay-export.py --target <overlay checkout>
--scope <tier> --dry-run` (then without `--dry-run`), after pulling any
colleague PR against `tree/` back first. Other destinations still ship. Recipe:
`docs/org-overlays.md` § Authoring an overlay.

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
- For PR submission: `gh` authenticated. Whether a fork is needed is
  DECIDED, not assumed: `gh api repos/<repo> --jq .permissions.push` —
  `true` pushes the branch straight to the upstream, `false` takes the
  fork route. **No push access to the upstream required** — open-bridge PRs go fork-based (`gh repo fork`
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
├── Overlay with a manifest (flat mirror)    → refuse; docs/org-overlays.md § Authoring an overlay
├── Scan branch for contributions            → bridge-contribute skill (/contribute)
├── Adapt/generalize content                 → bridge-contribute skill § Adapt mode
└── Questions about CORE/USER/ORG split      → Answer from docs/org-overlays.md (tier model)
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
