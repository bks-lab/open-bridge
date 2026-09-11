---
name: document-work
scope: always
enforcement: hook-warned
applies_to: []   # empty = every dispatched sub-agent
load: eager   # fires without its own vocabulary: work gets logged unasked, or not at all
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

This is the **single, frozen** log row format. Every row carries a **full-ISO
date+time** so it self-dates — a stale or unarchived log is never ambiguous. The
day-block header stays `## {Weekday} DD.MM` (a display anchor for the parsers; do
NOT add a year there). The legacy time-only variant `| HH:MM | ... |` is
**retired** — do not author it.

- Timestamp from `date '+%Y-%m-%d %H:%M'` — NEVER xx:xx or placeholders
- glyph: emoji from activity_types in bridge-config.yaml
- context: project tag from ecosystem.yaml, or #issue-number
- Order: chronological, new entries at the end of the current day-block

## Additional

- STATUS.md is the SoT; `board.md` is **regenerated** from the task dirs
  (`scripts/gen-board.py`) — never hand-edited on a task switch.
- **Proactively suggest task creation.** At the end of any turn where work
  landed, when that work continues past this session OR an external recipient
  is involved, and no directory in `work/tasks/` or `work/streams/` already
  covers it, offer exactly ONE line: ``Task `<slug>`? [y/n]``. Never create it
  unasked, and drop it for the rest of the session once declined. Every input
  here is observable in the turn itself (did work land, does a task exist,
  does it cross a session or a party boundary), which the retired ">30 min on
  a topic" wording was not: the executing agent has no clock on the
  conversation, so that rule could never fire. Criteria:
  `protocols/standing-orders/board-task-criteria.md`.

## Violations

- Working for 30+ minutes without a log entry
- Using placeholder timestamps (xx:xx) or the retired time-only row format
  `| HH:MM | ... |` (rows must carry the full `YYYY-MM-DD HH:MM`)
- Hand-editing `board.md` instead of updating STATUS.md and regenerating
- Work landed that meets the Class A test (cross-session pickup or external
  recipient) and no task was offered
