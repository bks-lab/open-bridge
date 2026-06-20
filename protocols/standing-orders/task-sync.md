---
name: task-sync
scope: always
enforcement: blocking
applies_to: []   # empty = every dispatched sub-agent
---
# Task Sync Routing

When a task in `work/tasks/<slug>/` references external systems (GitHub
issues, wiki pages, ADO work items), the bridge enforces a **three-tier
resolver** to keep the bridge state and the external state aligned.

Resolver order (most specific wins):

1. **STATUS.md `sync:` block** — explicit per-task overrides
2. **`workflow/contexts/<context>.yaml` `sync.defaults`** — domain-level defaults
3. **`bridge_only: true`** — implicit fallback (local-only task)

The `sync` block schema lives in `work/templates/_schema.status.yaml`.
The `sync.defaults` schema lives in `workflow/contexts/_schema.yaml`.

## Triggers — when this standing-order acts

### 1. Task create

When the user creates a new task (`create task`, `track this`, ...):

- If STATUS.md has `context: <slug>` and `workflow/contexts/<slug>.yaml`
  exists with a `sync.defaults` block: **propose** the defaults as the
  initial `sync:` block content.
- Show a 3-line preview with `[y]` to accept, `[e]` to edit, `[n]` to keep
  empty (= bridge_only: true).
- If `context` has `dual_doku.required: true`: also propose the matching
  wiki path from `event_type_map[<type>].wiki_subpath`.

### 2. Status change

When STATUS.md `status:` transitions to **any** value in the closed enum
`{backlog, doing, review, done}` — `review` is a first-class status, not a
not-yet-real holding state:

- If `sync.github.issues` is non-empty: **prompt** before writing the mapped
  board Status to GitHub — "set Issue #N to `<mapped Status>`? [y/n]". The
  target Status is resolved from the internal `status` via the
  `status_mapping` block in `workflow/projects/<slug>.yaml` (see § Related),
  not hardcoded.
- If `sync.ado.work_items` is non-empty: same for ADO.
- Never auto-push — every external write needs explicit confirmation.

### 3. Task close

When the user marks a task `done` (or says any close-trigger phrase:
"task done", "document everything", "wrap up", "close out",
"finished — file it all", …), execute the five sub-phases below in order.

#### 3a. Dual-Doku Self-Check (existing gate)

- Read `workflow/contexts/<context>.yaml` self_check list (if present).
- Walk through every item, ask `[y/n]` per step:
  ```
  Task close self-check (context: <customer>):
    [ ] GitHub Issue updated with all Project #N fields
    [ ] Wiki markdown file written with last_updated: YYYY-MM-DD
    [ ] _MOC.md / incidents/index.md updated
    [ ] Work-log entry in work/log.md
    [ ] work/board.md regenerated from the dirs (STATUS.md is the SoT)
    [ ] Submodule pointer bumped in <your-org>/wiki
  ```
- If `dual_doku.post_actions` is non-empty (e.g. `submodule_bump`): run
  each action with `[y]` confirmation.
- A task is not done until every applicable self-check item is checked.

#### 3b. Postmortem (delegated to skill)

Unless `bridge-config.yaml.learning.postmortem.enabled` is `false`:
**invoke the `task-close-postmortem` skill** and let it own the
post-mortem capture + improvement-scan + proposal-writing logic.

The skill returns:
- frontmatter edits applied to `STATUS.md`
  (`time_invested`, `estimate_vs_actual`, `lessons`, `bridge_gaps`)
- a Postmortem body section (if user answered any prose questions)
- a count of proposals written to `work/_learning/proposals/`

If skill is unavailable (context-pressure edge case): the standing-order
falls through to 3c without postmortem — log a `📝 Docs` warning in
`work/log.md` so the gap is visible.

The skill is also directly user-invokable (`/postmortem the last hour`,
`reflect on the piece we just finished`) — same logic, different entry point.

#### 3c. 3-Step Move (existing close mechanic)

1. `mv work/tasks/<slug>/ work/done/$(date +%Y-%m)/<slug>/`
2. Regenerate `work/board.md` from the dirs (`scripts/gen-board.py`; the moved
   task drops out of Doing/Review and rolls into the `## Done — YYYY-MM`
   section; counts from `ls`)
3. Append entry to `work/log.md` with timestamp, type, context, summary

Per CLAUDE.md § Task Management "Task lifecycle (3-step enforcement)".

#### 3d. Recap

Surface a 1-block summary:

```
✅ Task <slug> closed.
   Dual-Doku self-check: <N>/<N> ok
   Postmortem: <X> bullets, <Y> bridge-gaps captured (or skipped)
   Proposals written: <N>  [→ /bridge-learn to review]
   Moved: work/done/<YYYY-MM>/<slug>/
```

### 4. Significant log entry

When a log entry has impact beyond a single line (decision, escalation,
incident analysis):

- If the task has `sync.wiki.path`: **prompt** "Export this as a wiki
  entry under `<path>`? [y/n]".
- The user can decline — log entry alone may be sufficient for non-
  customer-facing decisions.

## Decision rules

### When the resolver picks `bridge_only`

A task is `bridge_only` when:

- STATUS.md explicitly sets `sync: { bridge_only: true }`, **or**
- STATUS.md has no `sync:` block AND no `context:` resolves to defaults

`bridge_only` is **a deliberate answer**, not an unconfigured state.
Personal research, internal infra setup, and exploratory work all
legitimately stay local. It is normal for a large fraction of active
tasks to be `bridge_only: true` — that's the expected ratio.

### When the resolver merges defaults

A task **inherits** context defaults when:

- STATUS.md sets `context: <slug>`
- `workflow/contexts/<slug>.yaml` has `sync.defaults`
- STATUS.md `sync:` is present but partial (e.g. only `github.issues: [42]`
  set — the resolver fills `github.repo` from the context default)

Explicit STATUS values **always win** over context defaults — never
silently downgrade an explicit choice.

### When the resolver enforces dual_doku

When `workflow/contexts/<context>.yaml` has `dual_doku.required: true`:

- A task with `sync.github` set MUST also have `sync.wiki` set (or vice
  versa). The resolver warns at task-create time if only one is filled.
- The self-check list at task-close enforces both targets were touched.
- `bridge_only: true` is incompatible with `dual_doku.required: true` —
  if a task with this context legitimately bypasses dual_doku, the user
  must override `dual_doku.required: false` in STATUS.md (rare, document why).

## Phase 5 — Evidence-Check (session-start, opportunistic)

STATUS.md is human-edited text and drifts when the user commits work
between sessions without updating the file. The bridge then surfaces
stale priorities ("to do today") for tasks that commits have already
closed.

**Trigger:** session start, `/briefing` Stream A, or any read of
`work/tasks/<slug>/STATUS.md`.

**Procedure (per active task):**

1. Read `STATUS.md.last_updated` as cutoff date.
2. Determine the task's evidence paths:
   - **Preferred:** `STATUS.md.sync.evidence_paths[]` if set (explicit
     list of paths the task touches — see
     `work/templates/_schema.status.yaml`).
   - **Fallback heuristic:** match slug tokens (split on `-`) against
     `git log --name-only --since=<cutoff>` and pick paths with ≥1
     slug-token hit.
3. Run `git log --since=<cutoff> --oneline -- <evidence_paths>`.
4. If `N ≥ 2` commits exist since cutoff:
   - Surface in `/briefing` Warnings section:
     `⚠ STATUS-Drift: <slug> has N commits since last_updated <DATE>. Update STATUS.md?`
   - **Never auto-update STATUS.md.** Commits aren't necessarily
     phase-completions (could be refactors, hotfixes). User decides.
5. If `STATUS.md.status` is still `doing` but the most recent commit's
   message contains close-verbs (`close`, `done`, `complete`, `final`,
   `ship`), upgrade the warning to:
   `⚠ STATUS-Drift (likely done): <slug> last commit "<subject>" suggests closure.`

**Why:** STATUS-Drift is a recurring failure mode — a multi-phase task
ships its phases via commits but the STATUS.md file is never edited.
The briefing then surfaces the task as the top priority for today
instead of recognizing it as effectively closed. This phase closes
that gap by reading the git log as a second source of truth.

## Violations

- Marking a task `done` without running the context self-check
- Closing a `dual_doku.required` task with only one target touched
- Setting `sync.github.issues` without also setting `sync.github.repo`
  (resolver should have filled it from defaults — investigate)
- Editing an external system without recording it in the task's `sync` block
  (means the bridge state no longer reflects the truth)

## Repair recipes

**Issue exists on board but not in `sync.github.issues`:** add the issue
number to STATUS.md, run `last_updated: $(date +%Y-%m-%d)`, log the
backfill in `work/log.md`.

**Wiki entry exists but `sync.wiki.path` is empty:** add the path, log
the backfill.

**`dual_doku.required` task closed without submodule bump:** check
`git log -1 <your-org>/wiki -- wiki/customers/<customer>/` — if the parent
pointer is stale, run the bump as a backfill commit.

## Origin

This standing-order generalizes a hardcoded customer-specific dual-doku
rule that previously lived inside a domain coordinator skill. Any context
can opt into dual-doku by adding `dual_doku.required: true` and an
`event_type_map`. Customer-specific edge cases (e.g. `submodule_bump`)
live in `dual_doku.post_actions` per-context.

## Related

- `work/templates/STATUS.md` — STATUS.md template with sync-block shape
- `work/templates/_schema.status.yaml` — JSON Schema for STATUS frontmatter
- `workflow/contexts/_schema.yaml` — JSON Schema for context files
- `workflow/contexts/<slug>.yaml` — reference dual-doku context
- `workflow/projects/<slug>.yaml` — board fields referenced via project.ref;
  carries the `status_mapping` block (internal `status` → board Status, the
  **write** direction read on status-change push) alongside `state_map` (the
  board → normalized **read** direction). `status` is remote-authoritative on pull.
- `protocols/standing-orders/work-board-reconciliation.md` — folder↔board axis check
- `protocols/standing-orders/document-work.md` — log.md format + 30-min rule
