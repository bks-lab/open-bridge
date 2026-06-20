---
name: work-board-reconciliation
scope: always
enforcement: advisory
applies_to: []
---
# Work Board Reconciliation — Folder ↔ STATUS Coherence

Two orthogonal axes describe a task. They must never drift apart silently.

## The two axes

| Axis | Lives in | Values |
|---|---|---|
| **Filesystem KIND** (where the task lives) | `work/{tasks,streams,done}/<slug>/` | `tasks` (finite) · `streams` (long-runner) · `done/YYYY-MM` |
| **Workflow status** (what state the work is in) | `status:` frontmatter in `STATUS.md` | `backlog` · `doing` · `review` · `done` |

KIND is the **folder**, status is the **field** — they never collapse. There is
**no `work/doing/` directory**: "Doing" is the `status: doing` value (and a board
section), not a folder. `board.md` is **generated** from these two axes by
`scripts/gen-board.py` — its sections map 1:1 to the enum (+ Streams + Done) and
its counts are `ls` over the task dirs, so the board itself cannot drift; only
folder ↔ `status:` can.

## Invariants

1. Every `work/tasks/<slug>/` and `work/streams/<slug>/` directory MUST carry a `STATUS.md` whose `status:` is a valid enum value (`backlog` · `doing` · `review` · `done`). The board section a task appears in is **derived** from that `status:` (streams render in `## Streams`).
2. `board.md` is **generated** from the task dirs via `scripts/gen-board.py` — it is never hand-curated. Counts are `ls` over `work/tasks/`/`work/streams/`, so Quick-Stats are mechanical and cannot drift. A human edit to `board.md` is itself drift: fix STATUS.md and regenerate.
3. When a task reaches `status: done`, the directory MUST be moved to `work/done/YYYY-MM/<slug>/` in the same step (and the board regenerated).
4. `work/tasks/_meetings/` is a utility folder for transcripts — exempt from this order.
5. WIP is a **WARNING, never a block**: session-start warns when `doing + review` in `work/tasks/` exceeds `work.max_active` (bridge-config.yaml). Streams are **excluded** from WIP. New work is never refused; the remedy is to close, reprioritise, or reclassify a task to `work/streams/`.
6. The optional `| Sync |` column on the Doing lane (added by `/briefing` Phase 2 step 4) reflects the resolver state of each task's external bindings. Drift markers (`!`) trigger a Warning line in `/briefing` output — investigate before the next session.

## Session-Start Scan (advisory)

After Task Management load (CLAUDE.md § Session Start step 2), reconcile the
folder ↔ `status:` axis (board-row drift is gone — the board is generated):

```
tasks   = ls work/tasks/   | grep -v '^_'
streams = ls work/streams/ | grep -v '^_'
for each: read STATUS.md status:  → must be a valid enum value
```

Surface drift in this compact form (only when drift exists, otherwise silent):

```
⚠️ Task drift:
  STATUS.md missing / status: invalid: <slug1>, <slug2>
  status: done but not moved to work/done/: <slug3>
  WIP warning: doing+review in work/tasks/ = 12 (max_active 10)
```

Do NOT auto-fix. Offer:
- `[r]` reconcile interactively (go through each drift, decide per item)
- `[s]` skip for this session
- `[g]` regenerate `board.md` from the dirs (`scripts/gen-board.py`; counts are mechanical)

## Violations

- Creating a `work/doing/` directory (wrong axis — "doing" is a `status:` value)
- A task reaching `status: done` without moving the folder to `work/done/`
- Hand-editing `board.md` instead of editing STATUS.md and regenerating
- A `work/tasks/<slug>/` with no STATUS.md or an invalid `status:` value

## Repair recipes

**Missing / invalid `status:`:** open the STATUS.md → set `status:` to a valid enum value (`backlog`/`doing`/`review`/`done`) → regenerate board → log entry.
**Status-mismatch (board ≠ dirs):** the board is generated, so a mismatch means STATUS.md `status:` is wrong → fix the STATUS.md `status:`, then regenerate the board (`scripts/gen-board.py`; never hand-edit the board).
**Stale `Done`:** move directory `mv work/tasks/<slug> work/done/$(date +%Y-%m)/<slug>`, regenerate `board.md`, and add a `log.md` row.
