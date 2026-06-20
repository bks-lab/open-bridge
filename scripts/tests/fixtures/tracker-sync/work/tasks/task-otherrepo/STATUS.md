---
slug: task-otherrepo
type: task
status: done
created: 2026-06-01
last_updated: 2026-06-04
# Links issue #10 in a DIFFERENT repo than task-insync's #10 — must not
# cross-match. done(local) == done(remote) ⇒ in_sync.
sync:
  bridge_only: false
  github:
    repo: other-org/other
    issues: [10]
    project: { org: other-org, number: 9 }
---
# Other-repo task (cross-repo issue-number collision regression)
