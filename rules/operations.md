---
scope: core
description: Session management, commit hygiene, CORE/USER validation, context switching
---
# Bridge Operations

## Session Start

### Phase 0 — Detection (always first)

Before answering any user message at session start, run the detection gate
in [`rules/session-start.md`](session-start.md). It checks branch,
`user/*` existence, and `bridge-config.yaml` presence, and routes to
onboarding, branch-switch, orphan-state handling, or normal load. Do not
skip this phase — not even for generic greetings.

### Phase 1 — Work-system load

Only runs when Phase 0 returns NORMAL **and** `work.enabled: true` in the
session slice of bridge-config.yaml. Read that slice with
`python3 scripts/bridge-config.py --session`, which emits the six blocks the
session load needs; the other fifteen belong to the skill that owns them and are
read when that skill runs. Reading the whole file to reach `work.enabled` is
what the slice exists to stop:

1. Read the recent slice of the work log with
   `python3 scripts/worklog.py --recent 3` (the week header, the rolling TODO
   and the three most recent day blocks) plus `work/board.md` (active tasks —
   `work/tasks/` finite, `work/streams/` long-running). Reading the whole log to
   reach the last activity is what the slice exists to stop: on one live
   instance that file was 405,076 bytes. `/briefing` and `/archive` still read
   it in full, which is what they are for
2. Create today's day-block if missing (from `work/templates/day.md`;
   header `## {Weekday} DD.MM`)
3. Read the registry index: `python3 scripts/context-index.py ecosystem.yaml`
   (settings verbatim, one line per repo/customer/workspace). Fetch an entry
   with `--get <name>` when the work names one. Skip silently when the file is
   absent, which is the normal state before onboarding
4. Load standing orders: run `python3 scripts/standing-orders.py --index` and
   read the bodies it marks `eager`. For the rest the index carries a summary
   and a trigger vocabulary; read that body when its vocabulary comes up. The
   index is computed at the moment of use, so it is never stale
5. Check CORE updates: `git log HEAD..main --oneline` — offer merge if new
6. On "continue", "morning", "status": show summary, don't ask questions.
   When `bridge-config.yaml` `purpose.statement` is non-empty, **lead the
   summary with** `This Bridge is for {statement}.` so the session opens
   oriented around the instance's north-star. Empty statement → omit the
   line (today's behaviour).

## Commit Hygiene

### Conventional commits + release impact

Repos with an automatic release workflow (`.github/workflows/release.yml`, e.g.
open-bridge) compute the next version **from the merged commit subject** — and a
squash-merge turns the **PR title** into that subject. The branch name never
enters into it. So two disciplines, every commit:

1. **Pick the type from the actual change class, not by habit:** `feat:` = a new
   capability · `fix:` = a behaviour/bug change · `docs:` = docs/text only ·
   `chore:`/`ci:`/`refactor:`/`test:`/`style:`/`build:` = supporting change. The
   type drives the release — `feat:` → minor, `fix:` → patch, everything else →
   **no release** (full mapping: [`docs/releasing.md`](../docs/releasing.md)).
2. **Name the branch to match the type** — `docs/…`, `fix/…`, `feat/…`. It has no
   effect on the release, but an incoherent prefix (a `feat/` branch carrying a
   `docs:` change) forces the merger to double-check what will ship.

Keep the minor digit meaningful: while in `0.x`, reserve `feat:` (→ minor) for
genuine product capabilities. Site/marketing/visual tweaks are `docs:`/`chore:`
(no release), **not** `feat:` — otherwise the version number runs ahead of real
maturity.

### CORE/USER Separation

Before committing, verify paths match the branch:

**On `user/{name}` branch:** all paths allowed.

**On `main` (or preparing `/promote`) — Scope-Routing:**

Four scope tiers control which upstream a path can land on. Scope comes from
frontmatter (`scope: core | org | personal | user | private`) — **skills** nest
it under `metadata:` (`metadata.scope`), **sub-agents** and **rules** keep it
top-level. For the cluster-wrapper config paths
(`identity/{personas,mandants,accounts,contracts}`, `infra/channels`,
`workflow/{contexts,projects}`) a frontmatter `scope:` **wins over** the path
default; with no frontmatter the path decides (defaulting these to `user` — the
fail-safe: a missing or mistaken tag never leaks upward, it just fails to
promote). `personal` is an optional fourth tier — a private overlay under your
**own** account, separate from your org's overlay (see the § Tier Model).

| Scope | Allowed upstream | Path examples |
|---|---|---|
| `core` (or unset) | **open-bridge** + your org overlay | CLAUDE.md, README.md, CONTRIBUTING.md, docs/**, skills/** (`metadata.scope: core`), .claude/skills/**, .claude/agents/** (`scope: core` or unset), .codex/hooks.json, .vibe/hooks.toml, rules/*.md (top-level only = CORE tier; org/user rules live in `rules/org/` + `rules/user/` — see those rows), identity/{personas,accounts,mandants,contracts}/{_schema,_template}.yaml, infra/{remotes,channels,backups,instances}/{_schema,_template}.yaml, workflow/{calendars,contexts,projects}/{_schema,_template}.yaml, <wrapper>/<type>/_tests/** for the families listed in `WRAPPER_TESTS_CORE` (a schema's own contract suite ships with the schema; the list is enumerated because a fixture may hold instance data until its suite is generic), themes/**, trackers/**, scripts/** (ALLOWLIST, not a glob: the authoritative set is `SCRIPTS_CORE_ALLOWLIST` in scripts/categorize-commits.py; a new core script is registered there deliberately), scripts/tests/**, .pre-commit-config.yaml, .github/workflows/validate.yml, protocols/standing-orders/*.md (CORE default orders) |
| `org` | **your org overlay ONLY** (never open-bridge) | skills/customer-a-coordinator/ (= `metadata.scope: org`), .claude/agents/{customer-a-*,network-*}.md, ecosystem.yaml, ecosystem.<org>.yaml, rules/org/** (wiki-navigation, wiki-principles), workflow/contexts/customer-a.yaml (+ any context carrying `scope: org`), identity/mandants/org.yaml |
| `personal` | **your personal overlay ONLY** (never open-bridge, never your org overlay) | cluster-wrapper config carrying `scope: personal` — identity/{personas,mandants,accounts,contracts}/<id>.yaml, infra/channels/<id>.yaml, workflow/{contexts,projects}/<id>.yaml; rules/personal/**; ecosystem.personal.yaml |
| `user` / `private` | **stays local** (never any upstream) | bridge-config.yaml, cluster-wrapper config with `scope: user` or **no** frontmatter (identity/{personas,mandants,accounts,contracts}, infra/{remotes,channels}, workflow/{contexts,projects}), infra/instances/<id>.yaml, infra/backups/topology.yaml + _state.yaml, workflow/calendars/entries.yaml, work/ (incl. work/streams/applications/), rules/user/**, protocols/standing-orders/user/** (user-authored orders) |

**Routing-logic for `/promote` (per commit, per file):**
1. Read `scope:` frontmatter — skills: `metadata.scope`; sub-agents/rules:
   top-level `scope:` (or infer from path → table above)
2. Route the commit to ALL upstreams that the scope allows:
   - `core` → both open-bridge AND your org overlay (open-bridge first, then the overlay pulls)
   - `org` → your org overlay only
   - `personal` → your personal overlay only (a private overlay under your own account)
   - `user`/`private` → stay local
3. Mixed-scope commits are split — never push a commit with `org` (or `personal`) content to open-bridge.

Language is a parallel tier rule: CORE (`scope: core`) is authored in
English; `org`/`user` tiers may stay in the author's language. See
[`rules/language-policy.md`](language-policy.md).

### `workflow/contexts/` — special case (per-repo gitignore)

Routing contexts split by content, not by folder:

| File | Scope | open-bridge | org overlay | private (this repo) |
|---|---|---|---|---|
| `workflow/contexts/_template.yaml` | core | tracked | tracked | tracked |
| `workflow/contexts/{customer-a,doc-system}.yaml` | org | gitignored | tracked (org-shared) | tracked |
| `workflow/contexts/<personal>.yaml` | user | gitignored | gitignored | tracked |

In **this** instance (private) all contexts are tracked — git serves as
offsite backup. In **`open-bridge`** (public OSS) only `_template.yaml`
ships; the rest is `.gitignore`d. In **your org overlay** (org-internal) the
org-shared contexts (`customer-a`, `doc-system`) are tracked, personal
ones are not.

The same per-repo policy applies to `identity/personas/`,
`identity/mandants/`, and `workflow/projects/` — see each upstream's
`.gitignore` for the canonical filter.

**Repo-specific blocklist (in addition to path scope):**
Even path-allowed files run through `rules/promote-safety.md` content scan,
**per destination repo**. open-bridge has the strictest blocklist
(no Org/customer/personal refs). Your org overlay allows customer refs but
blocks personal PII.

If a commit mixes scope tiers: split into separate commits.

If a commit mixes CORE and USER files: split into separate commits.

**Content safety (in addition to path allowlist)**: even inside allowed
paths, content can leak user identity, customer names, or infrastructure
identifiers — especially inside "Example" blocks and render samples.
Before any cherry-pick, merge, or direct commit targeting `main`,
run the scan defined in `rules/promote-safety.md`.
Rationalizations like "it's only an example" are the exact failure
mode that rule exists to block.

### Messages

- Prefix: feat, fix, refactor, docs, config
- Focus on "why" not "what"
- Don't bundle unrelated changes

### Offering to Commit

After a logical unit of work: suggest committing ("Ready to commit these
changes?"), show the files list. On a user branch, commit freely; on main,
validate CORE-only paths first.

## Context Switching

When switching to another repo:
1. Read that repo's CLAUDE.md FIRST — every repo has its own conventions
2. Check branch model (development vs main vs dev)
3. Commit changes THERE, not in the bridge
4. Return and log the cross-repo work in work/log.md

## Work Logging

> When `work.enabled: true`, logging is **MANDATORY and CONTINUOUS — not
> best-effort.** Every substantive unit of work gets its **own** `work/log.md`
> row the **moment it lands** — in the same turn it happened, not batched
> at the end, not once per day. That covers: a code change or commit, a bug
> fixed, a decision made (+ the *why*), a finding worth keeping, a
> deploy/restart, an issue/PR/board operation. If you did work this turn and
> there is no row for it, the turn is **not finished** — append the row
> before you hand back. The tool-agnostic backstop is the
> `scripts/hooks/pre-commit` hook (armed via `core.hooksPath=scripts/hooks`):
> at every productive commit it prints a log reminder, the active-task list,
> and a WIP re-check — **warn-only**, never blocking. The
> `worklog-drift-check.sh` Stop hook is a Claude-only reinforcement on top.
> Do not wait for either to nag — log as you go. The user should never have
> to ask "did you log that?". When `work.enabled` is false, no logging is
> expected.

Mechanics under this gate:

**Triggers:** Log to `work/log.md` after git commits, command invocations, repo switches, significant findings, end of work blocks.
**30-minute rule:** If >30 min without logging, catch up immediately.
**Board sync:** `work/board.md` is **generated** from the task dirs — edit STATUS.md and regenerate; never hand-curate the board.
**WIP warning:** If `doing + review` tasks in `work/tasks/` >= max_active, **warn only** (never blocks) and suggest closing, reprioritising, or reclassifying. Long-running streams live in `work/streams/` and do **not** count toward the limit.

Full work-system semantics — log format, logging levels, and the task lifecycle — live in [`docs/work-system.md`](../docs/work-system.md).

## Completion landing

At completion, do not leave work stranded on orphan feature branches or
unmerged PRs — drive it to the repo's **default branch**, determined
**live**, never assumed (`gh api repos/X --jq .default_branch`; e.g.
`<you>/<your-bridge>` = `user/<name>`, open-bridge = `main`, an org
overlay = `development`). The landing step then forks on what the default
actually is:

- **Default is a personal user branch** (e.g. your own Bridge instance = `user/<name>`):
  commit + push there directly, no gate. This is the normal Feature-/USER-branch
  push that is already allowed (see `auto-end-of-work-cycle` below).
- **Default is a SHARED branch** (`main` / `development` on the upstreams):
  drive the PR toward merge, but the merge itself stays **announced and GATED** —
  never merge or push to `main` / `development` without explicit OK. This
  preserves the global hard rule; the only change is that the default *expectation*
  shifts from "park the PR, the user merges later" to **"land it"** (you actively
  push it to done rather than leaving it open).

After an **approved** merge: sync local clones to the default
(`git checkout <default> && git pull`) and delete stale feature branches.

**Auto-end-of-work cycle** (normal Feature-/UAT-work): when a unit is done
and verified, run the cycle yourself without being asked — deploy/restart
the affected service and verify it runs, document (STATUS.md +
`work/log.md` + relevant repo docs), commit + push the whole `work/` folder
plus your own files to the Feature-/USER-branch **only when `origin` is a
private repo you own; never push a `user/*` branch to a public/upstream
origin** ([`push-guard.md`](push-guard.md)). Stage atomically (intended
paths only, never sweep in unrelated in-flight changes), then confirm
briefly (commit hashes + service state).

**Hard gates stay** regardless of the above: no push to `main`/`development`;
**no push of a `user/*` branch (or USER content) to a PUBLIC/upstream origin** —
gate on origin *visibility*, not just the branch name (a `user/*` push is not a
`main` push but is the worse leak; resolve `gh repo view --json visibility` and see
[`push-guard.md`](push-guard.md)); no merge, no real Prod deploy, no outward-facing
action (live number, `dry_run=false`, secret rotation) without explicit OK.

**Maestro exception:** a real Maestro mission (P3+) overrides the auto-commit —
nothing the mission produces is committed or pushed until the user's **end-approval**.
The conductor prepares; the human lands.

## Pre-"done" independent review

Before declaring something **done / launch-ready / consistent**, run one
independent **unframed** review pass: agents that judge fresh, briefed
"assume nothing is intentional, report everything" ("nimm nichts als
intentional an"). A framed audit, briefed with your own preloaded "ground
truth," only checks *against your assumptions* and dismisses the exact
errors you got wrong; an unframed pass checks *the assumptions themselves*
— good for finding your own thinking errors, where a framed audit is only
good for fixing-against-spec. This is the active-verification complement to
SOUL § Verify before claim.
