---
name: bridge-status
description: >-
  Bridge health dashboard — shows branch, config, theme, ecosystem, agents,
  standing orders, work system, and repo status. Flags missing files, KW drift,
  and configuration problems. Includes documentation health and link checking.
  Trigger: "/bridge-status", "bridge status", "bridge health",
  "health check", "docs health", "link check",
  "documentation quality", "pre-release gate".
  (Bare "bridge" and bare "status" are intentionally NOT triggers — too broad,
  would collide with bridge-sync/bridge-dashboard/briefing.)
metadata:
  scope: core
---

# Bridge Status

Status dashboard showing current bridge state with clear indicators.
Read the referenced file ONLY when triggered.

## Arguments

| Argument | Effect | Default |
|----------|--------|---------|
| `(none)` | Terminal status dashboard | — |
| `--html` | Additionally render HTML dashboard | false |
| `--docs` | Full documentation health report | false |

## Decision Tree

```
User wants to...
├── Full status dashboard              → Read references/workflow.md
├── HTML dashboard                     → Read references/workflow.md (--html path)
├── Documentation health report        → Read references/docs-health.md
├── Validate links in docs/wiki        → Read references/docs-health.md (§ Link Detection)
├── Pre-release docs quality gate      → Read references/docs-health.md (§ Pre-Release Quality Gate)
└── Questions about bridge state       → Answer from this file
```
