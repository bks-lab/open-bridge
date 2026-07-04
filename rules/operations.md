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

Only runs when Phase 0 returns NORMAL **and** `work.enabled: true` in
bridge-config.yaml:

1. Read `work/log.md` — last activity, current week
2. Read `work/board.md` — active tasks (`work/tasks/` finite tasks; `work/streams/` long-running streams)
3. Create today's day-block if missing (from `work/templates/day.md`; header `## {Weekday} DD.MM`)
4. Load standing orders from `protocols/standing-orders/` (scope: always)
5. Check CORE updates: `git log HEAD..main --oneline` — offer merge if new commits
6. On "continue", "morning", "status": show summary, don't ask questions. When
   `bridge-config.yaml` `purpose.statement` is non-empty, **lead the summary with**
   `This Bridge is for {statement}.` so the session opens oriented around the
   instance's north-star. Empty statement → omit the line (today's behaviour).

## Commit Hygiene

### CORE/USER Separation

Before committing, verify paths match the branch:

**On `user/{name}` branch:** all paths allowed.

**On `main` (or preparing `/promote`) — Scope-Routing:**

Three scope tiers control which upstream a path can land on. The scope
comes from frontmatter (`scope: core | org | user | private`) for
skills/agents — **skills** nest it under `metadata:` (`metadata.scope`),
**sub-agents** keep it top-level; for raw config paths it's inferred from
the path itself.

| Scope | Allowed upstream | Path examples |
|---|---|---|
| `core` (or unset) | **open-bridge** + your org overlay | CLAUDE.md, README.md, CONTRIBUTING.md, docs/**, skills/** (`metadata.scope: core`), .claude/skills/**, .claude/agents/** (`scope: core` or unset), rules/*.md (top-level only = CORE tier; org/user rules live in `rules/org/` + `rules/user/` — see those rows), identity/{personas,accounts,mandants,contracts}/{_schema,_template}.yaml, infra/{remotes,channels,backups,instances}/{_schema,_template}.yaml, workflow/{calendars,contexts,projects}/{_schema,_template}.yaml, themes/**, trackers/**, scripts/{generate-bridge,validate-ecosystem,validate-bridge,validate-skill-scope}.py, scripts/scaffold-user.sh, .pre-commit-config.yaml, .github/workflows/validate.yml, protocols/standing-orders/*.md (CORE default orders) |
| `org` | **your org overlay ONLY** (never open-bridge) | skills/customer-a-coordinator/ (= `metadata.scope: org`), .claude/agents/{customer-a-*,network-*}.md, ecosystem.yaml, rules/org/** (wiki-navigation, wiki-principles), workflow/contexts/{customer-a,doc-system}.yaml, identity/mandants/org.yaml |
| `user` / `private` | **stays local** (never any upstream) | bridge-config.yaml, identity/personas/<id>.yaml, identity/mandants/<id>.yaml, identity/contracts/<id>.yaml, infra/remotes/<id>.yaml + setup.md, infra/channels/<id>.yaml, infra/instances/<id>.yaml, infra/backups/topology.yaml + _state.yaml, workflow/calendars/entries.yaml, workflow/projects/<slug>.yaml, work/ (incl. work/streams/applications/), rules/user/** (applications), protocols/standing-orders/user/** (user-authored orders) |

**Routing-logic for `/promote` (per commit, per file):**
1. Read `scope:` frontmatter — skills: `metadata.scope`; sub-agents/rules:
   top-level `scope:` (or infer from path → table above)
2. Route the commit to ALL upstreams that the scope allows:
   - `core` → both open-bridge AND your org overlay (open-bridge first, then the overlay pulls)
   - `org` → your org overlay only
   - `user`/`private` → stay local
3. Mixed-scope commits are split — never push a commit with `org` content to open-bridge.

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

After completing a logical unit of work:
- Suggest committing: "Ready to commit these changes?"
- Show what would be committed (files list)
- On user branch: commit freely
- On main: validate CORE-only paths first

## Context Switching

When switching to another repo:
1. Read that repo's CLAUDE.md FIRST — every repo has its own conventions
2. Check branch model (development vs main vs dev)
3. Commit changes THERE, not in the bridge
4. Return and log the cross-repo work in work/log.md

## Work Logging

> When `work.enabled: true`, logging is **MANDATORY and CONTINUOUS — not
> best-effort.** Every substantive unit of work gets its **own** `work/log.md`
> row the **moment it lands** — in the same turn it happened, not batched at the
> end, not once per day. That covers: a code change or commit, a bug fixed, a
> decision made (+ the *why*), a finding worth keeping, a deploy/restart, an
> issue/PR/board operation. If you did work this turn and there is no row for it,
> the turn is **not finished** — append the row before you hand back. The
> **tool-agnostic** deterministic backstop is the `scripts/hooks/pre-commit` hook
> (armed via `core.hooksPath=scripts/hooks`): at every productive commit, from any
> tool, it prints a per-event log reminder + the live active-task list + a WIP
> re-check — **warn-only**, it never blocks. The `worklog-drift-check.sh` Stop hook
> is a Claude-only reinforcement on top. Do not wait for either to nag — log as you go. The user should never have to ask "did you log
> that?". When `work.enabled` is false, no logging is expected.

Mechanics under this gate:

**Triggers:** Log to `work/log.md` after git commits, command invocations, repo switches, significant findings, end of work blocks.
**30-minute rule:** If >30 min without logging, catch up immediately.
**Board sync:** `work/board.md` is **generated** from the task dirs — edit STATUS.md and regenerate; never hand-curate the board.
**WIP warning:** If `doing + review` tasks in `work/tasks/` >= max_active, **warn only** (never blocks) and suggest closing, reprioritising, or reclassifying. Long-running streams live in `work/streams/` and do **not** count toward the limit.

Full work-system semantics — log format, logging levels, and the task lifecycle — live in [`docs/work-system.md`](../docs/work-system.md).

## Completion landing

At completion, do not leave work stranded on orphan feature branches or unmerged
PRs — drive it to the repo's **default branch**. The finished state should live
on the default; dangling feature branches and parked PRs are unwanted.

Determine the default **live**, never assume it — `gh api repos/X --jq .default_branch`
(e.g. `<you>/<your-bridge>` = `user/<name>`, open-bridge = `main`, an org overlay = `development`).
The landing step then forks on what the default actually is:

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

**Auto-end-of-work cycle** (normal Feature-/UAT-work): when a unit is done and
verified, run the cycle yourself without being asked — deploy/restart the affected
service and verify it runs, document (STATUS.md + `work/log.md` + relevant repo
docs), commit + push the whole `work/` folder plus your own files to the
Feature-/USER-branch — **but only when `origin` is a private repo you own; never
push a `user/*` branch to a public/upstream origin** ([`push-guard.md`](push-guard.md)) —
(atomic — stage only the intended paths, never sweep in unrelated in-flight
changes), then confirm briefly (commit hashes + service state).

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
independent **unframed** review pass — agents that judge fresh, with the brief
"assume nothing is intentional, report everything" ("nimm nichts als intentional
an"). Framed audits briefed with your own preloaded "ground truth" only check
*against your assumptions* and dismiss the exact errors you got wrong; an
unframed pass checks *the assumptions themselves*. Framed audits are good for
fixing-against-spec, bad for finding your own thinking errors. This is the
active-verification complement to SOUL § Verify before claim.
