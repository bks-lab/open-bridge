---
name: board-task-criteria
scope: always
enforcement: advisory
applies_to: []
---
# Board-Task Criteria — When does work become a Board task?

`document-work.md` says *when to log*. `work-board-reconciliation.md`
says *the board and the folder must stay coherent*. This order fills
the gap between them: **at what point does a work item escalate from a
log.md entry to a Board task with its own STATUS.md?**

## KIND is the folder (orthogonal to class)

Before the class question, fix the **KIND** — and KIND is the folder, never a
field (there is no `kind:` frontmatter):

- `work/tasks/` = **finite** task (reaches `done`).
- `work/streams/` = **long-runner** (never `done`, excluded from WIP).

KIND (finite vs long-runner) and class (A/B/C below) are **orthogonal axes**:
KIND is *where the task lives*; class is *how far it escalates* (log-only vs
board-task vs silent). A finite task and a stream can both be A-class.

## Three-class model

Every work unit falls into exactly one class:

```
                      ┌── Work unit ──┐
                      │               │
            cross-session?           one-shot?
                yes                    │
                ▼                      ▼
   ┌─────────────────┐       ┌──────────────────┐
   │ A. BOARD TASK   │       │ B. LOG-ONLY      │
   │ STATUS.md       │       │ log.md entry     │
   │ Board row       │       │ no STATUS.md     │
   │ context/mandant │       │ no Board row     │
   └─────────────────┘       └──────────────────┘

                                     │
                          read-only routine command?
                                     ▼
                            ┌──────────────────┐
                            │ C. SILENT        │
                            │ no log entry     │
                            └──────────────────┘
```

## Decision tree — three questions

**Q1: Does the work need to survive across sessions?**
- If the session ends now and resumes in 3 days: do you need pickup
  notes (risks, stakeholders, open points)?
- **YES → A (Board task)**

**Q2: External recipient or external system involved?**
- A counterparty receives a message? An external board (GitHub
  Projects, ADO, Jira) gets updated? A customer wiki page is written?
  A contract or invoice goes out?
- **YES → A (Board task)** — even if it could be finished in one session

**Q3: Pure read-only routine command?**
- `/briefing`, `/bridge`, `/archive`, `/calendar list`, `git status`,
  `gh issue list` …
- **YES → C (silent, no log)**

**Otherwise → B (log-only)**.

## Application table

| Work-unit class | Class | Reason |
|---|---|---|
| Customer escalation, months-long | A | cross-session + external recipient |
| Incident response, multi-week | A | cross-session + external system |
| Feature build, multi-session | A | cross-session pickup |
| Infra setup, days–weeks | A | cross-session pickup |
| Bridge-meta task, paused with pickup plan | A | cross-session resumption |
| Bridge-meta task, one-shot drift-fix | **B** | session-bounded, no external party |
| Sequential-thinking session | B (auto-logged) | analysis support, not work itself |
| Application with pipeline | A (sub-tree `work/streams/applications/`) | own lifecycle |
| Cold idea, sitting in backlog | **`work/backlog.md`** | no pickup plan, no body |
| Scratch / utility folder | exempt | `work/tasks/_meetings/` etc. |

## Cold ideas — the third lane

Items shown as "Backlog row without STATUS.md" on the board are neither
A nor B — they are **cold ideas**. They have no pickup plan, no risks,
no body, just a title and "maybe someday".

**Rule:** Cold ideas live in `work/backlog.md` (compact 1-line list),
not in `work/board.md`. Only on pickup does a cold idea become an
A-class Board task (STATUS.md gets created).

`work/backlog.md` is created **lazily** — as long as cold ideas stay
under ~10 rows and remain scrollable in board.md's Backlog section,
no separation is needed. Trigger for split: Backlog grows past 15 items
or cold-share exceeds 50 % of Backlog rows.

## Sub-items of existing tasks

When work is a **sub-item of an existing task** (e.g. a multi-tier task
with numbered sub-items A1–A5/B1–B3/C1–C5), **no new Board task is
created**. Instead:

1. log.md entry referencing the parent slug
2. Check off the sub-item in the parent STATUS.md, or update its state
3. Bump the parent `last_updated:` date

## Instance-managed sub-trees

Some instances carry their own sub-trees with a separate lifecycle
(applications/job-search, customer-specific incident archives, etc.).
These are long-runners → they live under `work/streams/`. Items from
those sub-trees appear on board.md in their **own section**
(`## Streams — Applications`, `## Streams — Customer X`, …), **not** in
the general Review table. The sub-tree's `<id>/STATUS.md` is the SoT.

## The rule in one sentence

- **A (Board task):** cross-session pickup **or** external recipient.
- **B (Log-only):** otherwise, when state changed.
- **C (Silent):** read-only routine commands.
- **Sub-items:** no own task, check off in parent STATUS.
- **Cold ideas:** `work/backlog.md`, no Board row.

## Violations

- A row in board.md Doing without a STATUS.md (except folder-less
  Review rows and instance-managed sub-trees).
- A folder in `work/tasks/<slug>/` with no Board row.
- A cold idea sitting as a board Backlog row when it will never become
  active.
- A sub-item gets its own task instead of being checked off in the
  parent STATUS.
- An application sits in the general Review table instead of the
  `## Streams — Applications` section.

## Cross-refs

- `protocols/standing-orders/document-work.md` — log.md triggers
- `protocols/standing-orders/work-board-reconciliation.md` — folder ↔ board invariants
- `work/templates/_schema.status.yaml` — STATUS.md schema
- `CLAUDE.md § Task Management` — proactive task-suggestion triggers
