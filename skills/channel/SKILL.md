---
name: channel
description: >-
  Messaging channel management: health checks, deployments, start/stop
  services. Reads infra/channels/*.yaml. Not for timed sends (→ /schedule) or
  runs on a machine (→ /workload).
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
| Scheduled messages in `infra/channels/_scheduled.yaml` | **`/schedule` skill** |
| Any other cron/launchd/systemd job on a machine | **`/workload` skill** |
| Recipient groups for those messages | **`/mandants` skill** |

When the user asks about a scheduled message ("compliment for Mom",
"weekly-digest", its send time) route to `/schedule`. A job that is not a
message (a poller, a nightly sync, a daemon, "is the job still there") is a
workload: route to `/workload`, which declares it in `workflow/workloads/` and
reads its state from the live service manager. Channel management is the
transport layer; scheduling is a separate concern.

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
├── Scheduled messages                 → Delegate to `/schedule` skill
├── Cron/launchd/systemd jobs          → Delegate to `/workload` skill
├── Recipient group management         → Delegate to `/mandants` skill
└── Questions about channels           → Answer from this file
```
