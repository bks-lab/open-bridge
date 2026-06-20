---
name: mandants
description: >-
  Mandant management — recipient groups for outbound messages. List, add,
  show mandants and add persons to groups. Types: company, household,
  family, friends, colleagues, individual.
  Trigger: "/mandants", "mandants", "recipients", "recipient groups",
  "add recipient group".
metadata:
  scope: core
---

# Mandants

Manage recipient groups in `identity/mandants/*.yaml`.
Read the referenced file ONLY when triggered.

## Guard

`mandants.enabled` must be `true` in bridge-config.yaml. If not: inform and exit.

## Arguments

| Argument | Effect | Default |
|----------|--------|---------|
| `list` or `(none)` | List all mandants | — |
| `add` | Create new mandant | — |
| `show {id}` | Detail view with persons | — |
| `add-person {mandant}` | Add person to group | — |

## Decision Tree

```
User wants to...
├── List mandants                      → Read references/workflow.md (§ List)
├── Add new mandant                    → Read references/workflow.md (§ Add)
├── Show mandant details               → Read references/workflow.md (§ Show)
├── Add person to mandant              → Read references/workflow.md (§ Add-Person)
└── Questions about mandants           → Answer from CLAUDE.md § Mandants
```
