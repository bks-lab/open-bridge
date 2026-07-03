---
name: document-work
scope: always
enforcement: blocking
applies_to: []   # empty = every dispatched sub-agent
description: Mandatory work-log entry after every commit, skill/command invocation, repo switch, or significant finding — no placeholder timestamps, catch up after 30+ silent minutes
---
# Document All Work

Log every significant action to work/log.md.

## Triggers

- After git commits
- After skill/command invocations
- On repo switches
- On significant findings (bug found, deployment, review done)
- After 30+ minutes without logging: catch up immediately

## Format

`| HH:MM | Type | Context | What |`

- Time-only from `date '+%H:%M'` — the date lives in the day-block header (see docs/work-system.md); NEVER placeholders
- Type: emoji from activity_types in bridge-config.yaml
- Context: project/repo tag from ecosystem.yaml

## Additional

- Update board.md on every task switch
- Proactively suggest task creation when >30 min on a topic without a tracked task

## Violations

- Working for 30+ minutes without a log entry
- Using placeholder timestamps (xx:xx)
- Switching tasks without updating board.md
