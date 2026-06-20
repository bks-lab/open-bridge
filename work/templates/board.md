# Work Board

> **Generated** snapshot of all tasks — derived from the task dirs, never hand-curated.
> Sections map 1:1 to the `status:` enum (+ Streams + Done); counts come from `ls`.
> Single source of truth for task state is each `work/tasks/<slug>/STATUS.md` —
> humans edit STATUS.md, the board is regenerated (`scripts/gen-board.py`).

## Doing

| Slug | Type | Priority | Started | Note |
|---|---|---|---|---|

## Review

| Slug | Type | Priority | Started | Note |
|---|---|---|---|---|

## Backlog

| Slug | Type | Priority | Note |
|---|---|---|---|

## Streams

| Slug | Type | Priority | Note |
|---|---|---|---|

## Done — YYYY-MM

| Slug | Type | Closed | Note |
|---|---|---|---|

---

## Conventions

- The board is **generated from the directories** — sections == the `status:` enum
  (`doing`, `review`, `backlog`) plus `Streams` and a rolling `Done — YYYY-MM`. Counts
  come from `ls` over the task dirs, so they **cannot drift**. Never hand-curate it:
  edit the task's `STATUS.md` and regenerate.
- A task in `Doing`/`Review`/`Backlog` MUST have its folder at `work/tasks/<slug>/` with a
  valid `STATUS.md`; its section == its `status:` field.
- `Streams` lists `work/streams/<slug>/` long-runners (KIND = the folder). Streams are
  **excluded from WIP** — they never count against `max_active`.
- A task in `Done` MUST have been moved to `work/done/YYYY-MM/<slug>/` already.
- A blocked task is NOT a separate section — it stays in `Doing`/`Review` and carries a
  `blocked_by:` flag in its STATUS.md (declined → `done` + `outcome: declined`).
- WIP cap (`doing + review` in `work/tasks/` > `work.max_active`) surfaces a **warning** at
  session start — it never blocks new work.
- Empty section = no entries; do not write "none" — keep it terse.
