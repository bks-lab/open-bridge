---
name: document-work
scope: always
enforcement: blocking
applies_to: []   # empty = every dispatched sub-agent
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

`| HH:MM | glyph | context | what |`

This is the **single, frozen** log row format. The date comes from the
day-block header (`## {Weekday} DD.MM`), so the row carries **time-only**.
The legacy dated variant `| YYYY-MM-DD HH:MM | ... |` is **retired** — do
not author it.

- Time from `date '+%H:%M'` — NEVER xx:xx or placeholders
- glyph: emoji from activity_types in bridge-config.yaml
- context: project tag from ecosystem.yaml, or #issue-number
- Order: chronological, new entries at the end of the current day-block

## Additional

- STATUS.md is the SoT; `board.md` is **regenerated** from the task dirs
  (`scripts/gen-board.py`) — never hand-edited on a task switch.
- Proactively suggest task creation when >30 min on a topic without a tracked task

## Violations

- Working for 30+ minutes without a log entry
- Using placeholder timestamps (xx:xx) or the retired dated row format
  `| YYYY-MM-DD HH:MM | ... |`
- Hand-editing `board.md` instead of updating STATUS.md and regenerating
