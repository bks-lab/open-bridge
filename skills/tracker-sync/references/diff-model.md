---
summary: "Delta classification + phase-bucket rules for tracker-sync diff"
type: reference
last_updated: 2026-06-04
related:
  - scripts/tracker-sync.py
  - trackers/README.md
  - work/templates/_schema.status.yaml
---

# Tracker-Sync — Diff Model

How `scripts/tracker-sync.py diff` turns (snapshot × STATUS.md) into a delta.

## Inputs

1. **Snapshots** — `work/trackers/<provider>/<slug>.json`, each item already
   normalized to the `trackers/README.md` schema (carries `number`, `state`,
   `assigned_to_me`, `url`, …). The snapshot IS the dump.
2. **Local tasks** — every `work/tasks/*/STATUS.md` and
   `work/streams/*/STATUS.md` whose `sync.github.issues` is non-empty.
   `bridge_only: true` tasks are skipped entirely (deliberately local).

## Phase buckets (why we don't cry wolf)

Local `status:` and remote normalized `state` live on different scales, and
local `doing` legitimately spans both `in_progress` and `review`. So both sides
collapse to four comparable buckets before comparison:

| Bucket | Local `status:` | Remote normalized `state` |
|---|---|---|
| `todo` | `backlog` | `new`, `ready` |
| `active` | `doing` | `in_progress`, `review` |
| `blocked` | `waiting` | `blocked` |
| `closed` | `done` | `done`, `removed` |

Rank: `todo`(0) < `active`(1) < `closed`(2). `blocked` is compared separately.

## Classification

For each (task, issue):

| Result | Condition |
|---|---|
| `in_sync` | same bucket |
| `state_mismatch` | exactly one side is `blocked` |
| `remote_ahead` | board rank > local rank (board moved on) |
| `local_ahead` | local rank > board rank (you moved on) |
| `orphan_local` | the issue number is in no snapshot (stale link / wrong repo / not pulled) |

Plus, scanned across all snapshots (assigned-to-me, unlinked items):

| Result | Condition |
|---|---|
| `board_stale` | issue is **closed/merged** but its board card is NOT on a done state (card never moved to Done) |
| `orphan_remote` | issue still **open**, linked to no task |

### Issue lifecycle vs board Status field

The board Status field (`🆕 New`, `🏗 In progress`, …) is **not** the issue
lifecycle. A closed issue can sit on a `New` card forever. So `pull` fetches
each repo's closed issues + merged/closed PRs and stamps `item.closed` +
`item.issue_state`. In `diff`, **lifecycle wins**: a closed issue counts as
`done` regardless of its card. That means a closed issue linked to a still-open
task shows as `remote_ahead` (close your task), and a closed issue with a
stale card shows as `board_stale` (move the card). Without this, both looked
like open `orphan_remote` — a real-world bug class (in the originating incident,
15 of 17 "orphans" were actually long-closed issues with stale cards).

## What each class proposes (all gated)

- `remote_ahead` → **propose** a STATUS.md edit (e.g. `doing → done`). Never
  auto-written — a board move isn't always a phase completion. Mirrors the
  task-sync standing-order Phase-5 STATUS-drift rule, on the tracker axis.
- `local_ahead` → feed into `plan`; push via github-projects-manager (gated).
- `board_stale` → propose a board-hygiene push (card → Done) via
  github-projects-manager, gated. The issue is already closed; only the card lags.
- `state_mismatch` / `orphan_*` → surface, let the human decide (link, unlink,
  create task, fix repo, re-pull).

## Push mapping (plan)

`local_ahead` → target normalized state via:

| Local `status:` | target normalized |
|---|---|
| `backlog` | `new` |
| `doing` | `in_progress` |
| `waiting` | `blocked` |
| `done` | `done` |

The exact board option name comes from reversing the board's `state_map`
(in `workflow/projects/<slug>.yaml`) — e.g. `done → "✅ Done"` on a board
with emoji-prefixed options. No registry → `to_option: null`; do not push blind.

## sync_policy (optional, per board)

`workflow/projects/<slug>.yaml` may carry:

```yaml
sync_policy:
  authority: remote        # remote (default) | local
  auto_pull: true          # may /briefing refresh this board's snapshot
  push_requires_confirm: true   # always true in practice; explicit here
```

Absent = `authority: remote`, `auto_pull: true`. `authority: local` is rare
(a board only you touch) and still never auto-pushes — it only flips which side
a `*_ahead` row defaults its proposal toward.

## Determinism boundary

The engine only *classifies* and *maps*. It never decides what a drift *means*
or writes anything outbound — that judgement is the skill + the human. This is
the same propose-not-apply gate as the rest of The Bridge.
