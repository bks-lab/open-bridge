---
name: bridge-status
description: >-
  Checks this Bridge installation: branch, config, registries, local repos, work system, plus docs health and link checking. Not live service health, not the daily overview (briefing). Trigger: "/bridge-status", "bridge status", "bridge health", "docs health", "link check". Bare "bridge" or "status" are not triggers.
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
