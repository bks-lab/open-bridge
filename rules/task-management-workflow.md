---
scope: core
description: Detailed workflow for task management — reflex pause, plan/build intent classification, similarity algorithm, cluster detection, class A/B/C, repair recipes. CLAUDE.md § Task Management points here.
---

# Task Management — Detailed Workflow

CLAUDE.md § Task Management carries the reflex rule and the top intent
categories. This file holds the full intent lists, thresholds, the
similarity algorithm, cluster detection, class definitions with
examples, and repair recipes.

## Intent Classification

Classify on **what the user is doing**, not on literal words. The user
may write in any language (German, English, mixed). Match the semantic
intent — the lists below are English exemplars of each category.

### PLAN intent — default output is a chat answer, no file write

The user is thinking, scoping, comparing, drafting language, or asking
for an opinion before committing to an artifact.

Exemplary verbs/phrases:

- **research**, **sketch**, **draft**, **outline**, **conceptualize**
- **explore**, **investigate**, **look into**, **dig into**
- **analyze**, **evaluate**, **weigh**, **scope**
- **clarify**, **think through**, **brainstorm**
- **propose** (as a plan, not as a commit)
- *"what would it look like if…"*, *"how about we…"*, *"let's first…"*

Output rule: **answer in chat as text**. Do NOT write to productive
folders (`skills/`, `protocols/`, `identity/`, `workflow/`, `infra/`,
`work/tasks/<new-slug>/`, `work/streams/<new-slug>/`, `work/board.md`,
`work/log.md`). If the user then asks for files, ask which target:
`work/tasks/<task>/drafts/`, new task, or no file at all.

### BUILD intent — productive paths allowed after the active-task check

The user wants a persistent artifact created, modified, deployed, or
finalized.

Exemplary verbs/phrases:

- **build**, **implement**, **create** (a file), **write** (a file)
- **set up**, **install**, **wire up**, **add**
- **deploy**, **ship**, **release**, **publish**, **go live**
- **merge**, **commit**, **sync**, **push**
- **verify**, **validate**, **finalize**
- **finish**, **close**, **complete**, **wrap up**
- **fix** (when the fix lands as a real change, not just a discussion)

After steps 2+3 below, writes to productive paths are allowed.

### Ambivalent verbs (disambiguation required)

| Verb | Plan reading | Build reading | Disambiguation |
|---|---|---|---|
| `create` / `make` | "let's create a draft of …" = exploring | "create the config file" = disk artifact | drafts → plan; persistent files → build |
| `review` | parallel pre-review (multiple perspectives, iterative) | final gate before merge / release | parallel = plan; sequential-final = build |
| `audit` | analysis pass to find issues | gate that blocks promotion | analysis = plan; gate = build |
| `consolidate` / `pull together` | pre-study aggregation | promoted into system | pre-study = plan; promoted = build |
| `propose` | proposing options to discuss | proposing the artifact about to land | options → plan; landing artifact → build |

When unclear from the user's framing: ask.

## Active-Task Check — Similarity Algorithm

Before proposing a new slug, check (scan **both** `work/tasks/` and
`work/streams/` — a request may belong to a long-running stream;
note that `work/streams/` long-runners are **excluded from the WIP cap**
`work.max_active`, only `work/tasks/` doing+review counts):

1. **Slug prefix match:** shared first `-` segment. If ≥3 active tasks
   share a prefix → **cluster warning** (see below).
2. **Context match:** `context:` frontmatter field in STATUS.md. Same
   context likely means the same doc pipeline.
3. **Stakeholder match:** name from `identity/mandants/*.yaml` appears
   in the user request AND in an active task's body → match.
4. **Keyword overlap:** ≥40% token overlap between the user request and
   a STATUS.md `headline` or the first 3 lines of its Situation.

**Threshold rule:** ≥70% confidence → silent extend. 30-70% → ask
"fits `<existing-slug>` or new?". <30% → propose new.

## Deliverables Location — never /tmp

Any artifact a user or customer is meant to see, edit, or send — HTML
drafts, PDF/Excel exports, mail drafts (`.eml`), briefings, status or
analysis reports, deck files — goes into
`work/tasks/<slug>/deliverables/` **from the first write**, never into
`/tmp` and never onto the Desktop as a stopgap.

**Gate (before the first deliverable artifact):**

1. Task folder under `work/tasks/<slug>/` exists? If not → create it.
2. `deliverables/` inside it exists? If not → `mkdir`.
3. Write the file there directly and name the path in chat.

`/tmp` is volatile — macOS cleanup or a session reset wipes it, taking
hours of edits with it. Browser preview (`open <path>`) works from any
folder, so it is no reason to stage in `/tmp`.

**Stays fine in `/tmp`** — ephemeral internal tool output only:
sub-agent / analysis dumps, `pbpaste`/`pbcopy` scratch, debug snapshots,
one-shot downloads for inspection.

## Cluster Detection — Umbrella Question

When the proposed new slug has a prefix that already carries ≥3 active
tasks (e.g. `bridge-*` with 6 active siblings: feedback-loop,
learning-loop-concept, optimization, pitch-essence, quality-loop,
work-autonomy):

```
Cluster bridge-* (6 active). Before opening a 7th sibling:
  [u] Propose umbrella `bridge-meta` with sub-items
  [a] Attach to: bridge-feedback-loop, bridge-learning-loop-concept, ...
  [n] New sibling anyway (justify briefly)
```

User decides. No auto-action.

## Class A / B / C (per board-task-criteria.md)

### Class A — Board task with STATUS.md
- Cross-session pickup needed (risk / stakeholder / state notes for
  later)
- **OR** external recipient (mandant, customer wiki, GitHub issue)

**Class A examples in this instance:** `customer-a-escalation`
(customer escalation, multi-week), `customer-b-proposal` (customer,
multi-phase), `external-stack-integration` (external stack,
multi-session).

### Class B — Log only
- Otherwise, when state changed but no pickup needed
- Must follow `document-work.md` format

**Examples:** drift fix completed in one session, skill tweak after
user feedback, bridge-meta edit without cross-session risk.

### Class C — Silent
- Pure read-only / routine command
- `/briefing`, `/bridge-status`, `/archive`, `git status`,
  `gh issue list`

## Repair Recipes (drift cases)

**Folder without board row:** the board is generated from the dirs, so a
folder always produces a row on regenerate — if a row is missing, just
regenerate the board; decide class and log the entry.

**Board row without folder:** the board is generated from the dirs, so
this should not arise — a row exists only when a task dir does. If a
stray row lingers, regenerate the board from `work/tasks/` +
`work/streams/`; if the task is genuinely blocked, it stays `doing`/
`review` with a `blocked_by:` flag (it still has a folder).

**Status mismatch (board section ≠ folder STATUS):** the board is
**generated** from the task dirs, so a mismatch means STATUS.md
`status:` is wrong (the board mirrors the dirs, not the reverse). Fix
the STATUS.md `status:` field, then regenerate the board.

**Stale doing task (>14d without update):** propose `[b] backlog /
[r] mark blocked (set `blocked_by:`, status stays doing/review) /
[d] close / [k] touch — still active`. (`waiting` is gone — a blocked
task stays `doing`/`review` and carries a `blocked_by:` free-text flag.)

**Skill/standing-order edit without task context:** if multi-file refactor →
backfill a task, STATUS `created:` = edit date; if single-shot fix →
log-only is fine, no task.

## Cross-Refs

- [`board-task-criteria.md`](../protocols/standing-orders/board-task-criteria.md) — A/B/C classification source
- [`task-sync.md`](../protocols/standing-orders/task-sync.md) — phase 1-4 resolver for external sync
- [`document-work.md`](../protocols/standing-orders/document-work.md) — log.md format + 30-min rule
- [`work-board-reconciliation.md`](../protocols/standing-orders/work-board-reconciliation.md) — folder ↔ board invariants
- `work/templates/STATUS.md` + `_schema.status.yaml` — STATUS frontmatter
- `workflow/contexts/<slug>.yaml` — doc routing defaults
