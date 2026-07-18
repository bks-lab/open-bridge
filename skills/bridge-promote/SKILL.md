---
name: bridge-promote
description: >-
  Promote CORE changes from your user branch to upstream (Scope-Routing
  per scope: core → OSS upstream, org → your org overlay, user → local).
  Analyzes commits, categorizes by CORE/USER/ORG path+frontmatter rules,
  runs mandatory content-safety checks per repo (leak scanner + blocklist,
  refuses on PII/customer hits), and creates fork-based PRs to upstream
  repos — no upstream push access needed. For file-level community
  contributions with adaptation, use the bridge-contribute skill
  (/contribute) instead.
  Trigger: "/bridge-promote", "promote", "cherry-pick", "push to upstream",
  "promote to upstream", "promote commits".
metadata:
  scope: core
---

# Bridge Promote — Scope Routing

Routes commits from `user/*` to the right upstream based on `scope:`
frontmatter (or path inference). See CLAUDE.md § Tier Model.

| Commit scope | Goes to | How |
|---|---|---|
| `scope: core` (or unset, on CORE-allowlist path) | **OSS upstream** (e.g. `bks-lab/open-bridge:main`) plus your org overlay if configured | Cherry-pick to local `development`, then PR to the OSS upstream |
| `scope: org` | **Your org overlay only** (e.g. `<your-org>/<your-bridge>:development`) | Cherry-pick + PR to your org's overlay repo |
| `scope: user` / `private` | **stays local** on `user/{name}` | No-op |

If you don't have an org overlay configured, only `scope: core` commits
get promoted; `scope: org` commits stay on your user branch.

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
