---
slug: task-closedlinked
type: task
status: doing
created: 2026-06-01
last_updated: 2026-06-04
# Issue #16 is CLOSED on GitHub but its board card still shows In Progress.
# Lifecycle wins: closed ⇒ remote effectively done ⇒ vs local doing = remote_ahead.
sync:
  bridge_only: false
  github:
    repo: demo-org/demo
    issues: [16]
    project: { org: demo-org, number: 7 }
---
# Task linking a closed issue (board card stale)
