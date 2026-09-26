---
name: channel
description: >-
  Messaging channel management: health checks, deployments, start/stop
  services. Reads infra/channels/*.yaml. Not for cron jobs (→ /schedule).
  Trigger: "/channel", "channel status", "channel health", "channel deploy",
  "start channel", "stop channel".
metadata:
  scope: core
---

# Channel

Manage messaging channels (imessage, email, telegram, whatsapp, signal, teams)
and their runtime services. Read the referenced file ONLY when triggered.

## Scope boundary

| Concern | Owner |
|---------|-------|
| Channel inventory, health, deploy, start/stop | **This skill** |
| Scheduled messages, cron/launchd/systemd jobs | **`/schedule` skill** |
| Recipient groups for those messages | **`/mandants` skill** |

When the user asks about a scheduled message ("compliment for Mom",
"weekly-digest", cron timing) route to `/schedule`. Channel management
is the transport layer; scheduling is a separate concern.

## Arguments

| Argument | Effect | Default |
|----------|--------|---------|
| `(none)` | Channel overview | — |
| `{name}` | Detail view of one channel | — |
| `health` | Health check all channels | — |
| `deploy {name}` | Deploy channel service | — |
| `start/stop/restart {name}` | Service control | — |

## Decision Tree

```
User wants to...
├── Channel overview / status          → Read references/workflow.md (§ Overview)
├── Channel health check               → Read references/workflow.md (§ Health Check)
├── Start/stop a channel               → Read references/workflow.md (§ Start/Stop)
├── Deploy channel services            → Read references/workflow.md (§ Deploy)
├── Scheduled messages / cron jobs     → Delegate to `/schedule` skill
├── Recipient group management         → Delegate to `/mandants` skill
└── Questions about channels           → Answer from this file
```
