---
name: archive
description: >-
  Archive the current week — collect log entries, generate summary, reset
  log.md, check upstream. Supports --force mode.
  Trigger: "/archive", "archive", "archive week",
  "week archive", "week wrap-up".
metadata:
  scope: core
---

# Archive

Weekly archive workflow. Read the referenced file ONLY when triggered.

## Arguments

| Argument | Effect | Default |
|----------|--------|---------|
| `(none)` | Archive with day-of-week detection | — |
| `--force` | Archive without confirmation | false |

## Prerequisites

`bridge-config.yaml` with `work.enabled: true`. If not: inform and exit.

## Decision Tree

```
User wants to...
├── Archive the week                 → Read references/workflow.md
├── Check for upstream CORE updates  → Read skills/briefing/references/upstream-summary.md
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
