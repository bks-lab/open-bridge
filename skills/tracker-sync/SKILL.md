---
name: tracker-sync
description: >-
  Persistent snapshot + bidirectional reconcile between The Bridge tasks and
  GitHub Project boards. Pulls each board into work/trackers/<provider>/<slug>.json
  (the local mirror / dump), diffs it against work/tasks|streams/*/STATUS.md
  sync.github bindings into a delta table (in_sync · remote_ahead · local_ahead ·
  state_mismatch · orphan_local · orphan_remote), and pushes local→remote changes
  through github-projects-manager — gated, never auto. GitHub is the system of
  record, The Bridge is the cockpit (remote-authoritative). Trigger: "/tracker-sync",
  "tracker sync", "sync my tasks", "reconcile tasks", "board reconcile",
  "snapshot github", "which task is in which state", "github project dump",
  "sync tasks down", "sync tasks up", "task drift", "sync status".
metadata:
  scope: core
  tools: [Bash, Read, Glob, Grep]
---

# Tracker-Sync

Keeps The Bridge's task state and the GitHub Project boards aligned, with a
**persistent local snapshot** as the pivot. Three deterministic engine
subcommands (`scripts/tracker-sync.py` — a shared repo-root utility shipped
with the Bridge repo itself, not a file inside this skill's own directory)
plus one gated write path.

**Provider scope:** GitHub Projects V2 only for now — other trackers
(e.g. ADO) are readable via `trackers/*.md` playbooks but are not
covered by snapshot/diff/push.

**Model — remote-authoritative.** The team works *in* GitHub, so
the board owns shared status. The Bridge mirrors it, surfaces drift, and stages
*your* pushes. Pull is autonomous (read-only); every cross-write is a proposal:
- **never auto-write STATUS.md** (a human decides what a remote change means)
- **never auto-push** to GitHub (gated, batch-confirmed, via github-projects-manager)

## When to use

- "sync my tasks", "which task is in which state"
- "pull the boards", "snapshot the projects", "give me a board dump"
- before/after working a board, to see what drifted
- `/briefing` calls the pull side automatically (see references/workflow.md)

## Subcommands (verbs)

| Verb | What | Gate |
|---|---|---|
| `pull` | refresh snapshots from all enabled GitHub boards | autonomous (read-only) |
| `status` / `diff` | render the delta table (the control surface) | read-only |
| `push` | apply `local_ahead` rows to GitHub | **gated**, via github-projects-manager |
| `sync` | `pull` → `diff` → offer `push` | gated at the push step only |

## How to run

### pull (down — autonomous)
```bash
python3 scripts/tracker-sync.py pull            # all boards from ecosystem.yaml
python3 scripts/tracker-sync.py pull --project <slug>
```
Writes `work/trackers/github/<slug>.json` + `work/trackers/_index.yaml` with a
`pulled_at` stamp. Best-effort: if `gh` is missing/unauthed it warns and skips —
never blocks. The git history of `work/trackers/` IS the dated dump history.

### diff (the cockpit — read-only)
```bash
python3 scripts/tracker-sync.py diff            # table
python3 scripts/tracker-sync.py diff --format json
python3 scripts/tracker-sync.py diff --exit-code   # exit 2 if actionable drift
```
Each row is one linked issue, classified (see references/diff-model.md). Present
the table, then offer the obvious next action per class:

| Class | Means | Offer |
|---|---|---|
| `in_sync` | local == board | nothing |
| `remote_ahead` | board moved past local (e.g. a teammate moved it to Done) | **propose** STATUS.md update (gated; never auto) |
| `local_ahead` | local moved past board | `push` (gated) |
| `state_mismatch` | blocked/odd divergence | surface, ask |
| `orphan_local` | STATUS links an issue not in any snapshot | re-pull / fix repo / unlink |
| `board_stale` | issue closed/merged but its card never moved to Done | propose board-hygiene push (card → Done), gated |
| `orphan_remote` | your **open** board item linked to no task | propose `link` or new task |

`pull` fetches each repo's closed issues/PRs and stamps `item.closed`; in `diff`
the issue **lifecycle wins** over the board Status field (a closed issue on a
`New` card is still done). `--no-issue-state` skips this for a faster pull.

### push (up — GATED, via github-projects-manager)
1. `python3 scripts/tracker-sync.py plan --format json` → list of Status-field ops.
2. Show the batch. For EACH operation get explicit `[y/n]` (or one batch `[y]`).
3. For each approved op, hand off to **github-projects-manager** (it reads
   `workflow/projects/<slug>.yaml` for the real field IDs + exact option names
   and runs the gh GraphQL mutation). NEVER write the board from this script.
4. Re-`pull` and re-`diff` to confirm the row is now `in_sync`. Verify-before-claim.

Boards without a `workflow/projects/<slug>.yaml` registry can be pulled and
diffed, but **push degrades**: `plan` emits `to_option: null` (no field-ID
mapping). Surface that honestly and offer to scaffold the registry from
`workflow/projects/_template.yaml` rather than pushing blind.

## Config

Uses the same `integrations.github` block as `/briefing` Stream B
(`enabled`, `projects: ecosystem`, `assignee_me`). Optional per-board
`sync_policy:` in `workflow/projects/<slug>.yaml` (authority, auto_pull) —
see references/diff-model.md. No config = remote-authoritative default.

## Hard rules

- Remote-authoritative: GitHub wins on `Status`; pull proposes, never overwrites STATUS.
- No auto-push. All board writes go through github-projects-manager, gated.
- Snapshots are USER data (`work/trackers/`) — never promoted upstream.
- The engine is the only deterministic surface; judgement (what a drift *means*)
  stays with the skill + the human.

## Related

- `scripts/tracker-sync.py` — the engine · tests: `scripts/tests/test-tracker-sync.sh`
- `references/diff-model.md` — full classification + phase-bucket rules
- `references/workflow.md` — pull/diff/push playbook + /briefing integration
- `skills/github-projects-manager/` — the gated write executor (push handoff)
- `protocols/standing-orders/task-sync.md` — the per-task `sync.github` resolver
- `trackers/README.md` — normalized item schema (== the snapshot format)
- `workflow/projects/<slug>.yaml` — board registry (fields, state_map, sync_policy)
