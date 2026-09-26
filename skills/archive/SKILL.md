---
name: archive
description: >-
  Archives every closed period still in the log: one summary per period,
  distils durable facts into memory (propose-then-confirm), resets log.md.
  Period follows work.archive_cadence (weekly, bi-weekly, monthly, quarterly,
  yearly). Trigger: "/archive", "archive", "archive week", "archive month",
  "week wrap-up".
metadata:
  scope: core
---

# Archive

Periodic archive workflow. Read the referenced file ONLY when triggered.

The period is **configurable** — `bridge-config.yaml` `work.archive_cadence`
(`weekly` default, then `bi-weekly` / `monthly` / `quarterly` / `yearly`).
The same key drives `/briefing`'s staleness warning, so the reminder and the
archiver always agree on what "overdue" means.

Archiving **distils before it resets**: `work/archive/` has no reader, so
without a distil step archiving would be forgetting with a backup. Phase 5
proposes durable facts for the memory base — which *is* loaded every session
— and never writes one without confirmation
([`rules/learning-autonomy.md`](../../rules/learning-autonomy.md)).

## Arguments

| Argument | Effect | Default |
|----------|--------|---------|
| `(none)` | Archive every closed period in the log, one file each, per `work.archive_cadence` | — |
| `--force` | Archive the current (in-progress) period too | false |
| `--no-distil` | Skip Phase 5; archive without proposing memories | false |

## Prerequisites

`bridge-config.yaml` with `work.enabled: true`. If not: inform and exit.

## Decision Tree

```
User wants to...
├── Archive the period               → Read references/workflow.md
├── Change how often it archives     → bridge-config.yaml work.archive_cadence
├── Are we behind on anything?       → Read skills/briefing/references/upstream-summary.md
└── Questions about archiving        → Answer from this file
```

## Activity Types

| Symbol | Name |
|--------|------|
| 🧪 | Testing |
| 💻 | Development |
| 🔬 | Analysis |
| 📋 | Planning |
| 📝 | Documentation |
| 🔧 | DevOps |
| 📅 | Meeting |
| 📧 | Communication |
| 📁 | Documents |
