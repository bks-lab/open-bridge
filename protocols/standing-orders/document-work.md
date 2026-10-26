---
name: document-work
scope: always
enforcement: hook-warned
applies_to: []   # empty = every dispatched sub-agent
load: eager   # fires without its own vocabulary: work gets logged unasked, or not at all
fires_unprompted: true   # --check refuses on-trigger for this order
---
# Document All Work

Log every significant action to work/log.md.

## Triggers

- After git commits
- After skill/command invocations
- On repo switches
- On significant findings (bug found, deployment, review done)
- After 30+ minutes without logging: catch up immediately

## What to Document

Not just actions ("PR created") — also **insights** and **findings**:
- "Bug is in auth_handler.py:142 — token refresh race condition under load"
- "Workaround: set retry_count=3 because upstream API drops first request"
- "Decision: use approach B because A requires schema migration"

log.md is the **working memory** — rich enough that /briefing can
reconstruct what happened, what was learned, and what's blocked.

## Format

`| YYYY-MM-DD HH:MM | glyph | context | what |`

The **single, frozen** row format, with a **full-ISO date+time** so a row
self-dates. The day-block header stays `## {Weekday} DD.MM` (a parser anchor; no
year there). The legacy `| HH:MM | ... |` variant is **retired**.

- Timestamp from `date '+%Y-%m-%d %H:%M'` — NEVER xx:xx or placeholders
- glyph: emoji from activity_types in bridge-config.yaml
- context: project tag from ecosystem.yaml, or #issue-number
- Order: chronological, new entries at the end of the current day-block

## Additional

- STATUS.md is the SoT; `board.md` is **regenerated** from the task dirs
  (`scripts/gen-board.py`) — never hand-edited on a task switch.
- **Task threshold.** Every state change still gets its log row; the threshold
  saves tasks, never log rows. Three questions, in order, for any work item:
  1. Finished in this session: a log row only, no task unless asked for.
  2. Mentioned, nothing started: an inbox item of kind `idea`, no task.
  3. A task only if the person asks for one, OR something already exists
     (branch, draft, file, a sent request awaiting an answer) AND it continues
     in a later session, OR the person committed to someone with a date.
  Then offer ONE line, ``Task `<slug>`? [y/n]``, only if no directory in
  `work/tasks/` or `work/streams/` covers it. Never create it unasked; drop it
  once declined. Tracker issues stay in the tracker: an assigned issue is the
  task, and the briefing's "assigned without a task" count is information, never
  an order. Criteria: `protocols/standing-orders/board-task-criteria.md`.

## Violations

- Working for 30+ minutes without a log entry
- Using placeholder timestamps (xx:xx) or the retired time-only row format
  `| HH:MM | ... |` (rows must carry the full `YYYY-MM-DD HH:MM`)
- Hand-editing `board.md` instead of updating STATUS.md and regenerating
- A task created for work that fails the threshold (finished, or only mentioned)
