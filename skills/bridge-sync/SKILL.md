---
name: bridge-sync
description: >-
  End-of-sprint batch-sync: pushes ALL pending scope:core + scope:org
  commits from the local user branch to BOTH upstreams (open-bridge +
  your org overlay) in one operation, with per-destination scrubbing and
  parallel PR creation. Complements /promote (per-commit) and
  /contribute (per-file) with a sprint-level workflow.
  Trigger: "/bridge-sync", "sync to upstreams", "push to both",
  "batch promote", "end-of-sprint sync", "sync all pending",
  "push everything to both repos".
metadata:
  scope: core
---

# Bridge Sync — Batch end-of-sprint upstream sync

`/bridge-sync` is the **wide-net** complement to `/promote` and `/contribute`.

| Skill | Granularity | Use case |
|---|---|---|
| `/promote` | per-commit | "promote this batch of recent commits" |
| `/contribute` | per-file | "scan for upstream-worthy files, adapt, PR" |
| `/bridge-sync` | per-sprint | "push EVERYTHING pending to both upstreams now" |

Read the referenced file ONLY when triggered.

## When to use

- End of a work-sprint, ready to publish all upstream-worthy changes at once
- After a refactor that touched many CORE+org files — manual cherry-pick is tedious
- When `/promote` has been deferred for days and there's a backlog
- When you want both `bks-lab/open-bridge` and your org overlay updated in one operation

**NOT** for:
- A single commit (`/promote` is leaner)
- File-level adaptation work (`/contribute --adapt` does that)
- USER-only changes (those stay local)

## Arguments

| Argument | Effect | Default |
|---|---|---|
| `(none)` | Full sync to both upstreams | — |
| `--dry-run` | Show routing matrix, don't push | false |
| `--repo open-bridge` | Sync only to open-bridge | both |
| `--repo <your-bridge>` | Sync only to your org overlay | both |
| `--since <ref>` | Sync commits since this ref (default: last sync tag) | last sync |
| `--no-scrub` | Disable open-bridge scrubbing (DANGER — only for emergency) | false |

## Prerequisites

- Current branch must be `user/*`. Refuses on `development` / `main`.
- `bridge-config.yaml.upstreams[]` defines BOTH upstreams.
- `git remote` has `origin` (your fork) + `upstream` (typically `<your-org>/<your-bridge>`).
- For open-bridge sync: `gh` CLI authenticated with cross-fork PR rights.

## Decision Tree

```
User wants to...
├── Full sync (default)                  → references/workflow.md
├── Dry-run / preview routing            → references/workflow.md (stop after Step 4)
├── Sync only one repo                   → references/workflow.md § --repo override
├── Configure scrub patterns             → rules/promote-safety.md per-repo blocklists
└── Tag the sync point                   → references/workflow.md § sync-tag
```

## Safety

`/bridge-sync` runs a **three-layer safety pipeline** per destination
(see `rules/promote-safety.md` for the full rule):

1. **`scrub_rules.<dest>`** — auto-rewrite during cherry-pick. Maps
   personal/internal tokens (your username, org, hostnames) to
   placeholders. Configured in `bridge-config.yaml.promote.scrub_rules`.
2. **`content_blocklist.<dest>`** — hard-block scan after scrub. Hits
   classify as `scrubable` (handled by layer 1), `adaptable` (defer for
   `/contribute --adapt`), or `personal-PII` (refuse).
3. **Universal patterns** — private keys, API tokens, paths — always
   blocked regardless of destination.

A commit hitting an `adaptable` pattern doesn't block the whole sync —
it gets routed as 🟡 in the matrix and deferred. The clean commits still
ship. `--no-scrub` only disables layer 1 (auto-rewrite); layers 2+3
always run.

Workflow recipes for conflict resolution (DU / UU / divergent structure),
MIXED-CU cherry-picks, and residual-leak fixup (`git commit --fixup` +
`rebase --autosquash`) live in `references/workflow.md` § Step 5.
