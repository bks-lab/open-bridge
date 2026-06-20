---
name: schedule
description: >-
  Scheduled task management — list, create, deploy, disable scheduled jobs.
  Manages infra/channels/_scheduled.yaml. Generates platform-native service
  definitions (launchd/systemd/cron) and deploys to remotes.
  Trigger: "/schedule", "schedule", "scheduled tasks", "cron job",
  "schedule deploy", "schedule list".
metadata:
  scope: core
---

# Schedule

Manage scheduled tasks in `infra/channels/_scheduled.yaml`.
Read the referenced file ONLY when triggered.

## Arguments

| Argument | Effect | Default |
|----------|--------|---------|
| `list` or `(none)` | List scheduled tasks | — |
| `create` | Create new scheduled task | — |
| `deploy {name}` | Deploy to remote | — |
| `disable {name}` | Disable task | — |
| `status` | Show run status | — |

## Decision Tree

```
User wants to...
├── List scheduled tasks               → Read references/workflow.md (§ List)
├── Create new task                    → Read references/workflow.md (§ Create)
├── Deploy to remote                   → Read references/workflow.md (§ Deploy)
├── Disable a task                     → Read references/workflow.md (§ Disable)
├── Check status                       → Read references/workflow.md (§ Status)
└── Questions about scheduling         → Answer from this file
```
