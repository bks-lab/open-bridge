---
name: calendar
description: >-
  Calendar and recipient management — list, add, show, cancel, confirm
  scheduled entries. Manages mandant recipient groups (company, household,
  family, friends, colleagues) and workflow/calendars/entries.yaml with multi-recipient
  support, duration estimates, and repeat patterns.
  Trigger: "/calendar", "calendar", "scheduled messages",
  "calendar add", "calendar list",
  "mandants", "recipients", "recipient groups", "add recipient group".
metadata:
  scope: core
---

# Calendar

Manage scheduled outbound actions and recipient groups.
Read the referenced file ONLY when triggered.

## Guard

`calendar.enabled` must be `true` in bridge-config.yaml. If not: inform and exit.

## Arguments

| Argument | Effect | Default |
|----------|--------|---------|
| `list` or `(none)` | Show all entries | — |
| `add` | Create new entry | — |
| `show {id}` | Detail view | — |
| `cancel {id}` | Cancel entry | — |
| `confirm {id}` | Mark as confirmed | — |
| `status` | Summary with next-up | — |
| `mandants` | List all recipient groups | — |
| `mandants add {id}` | Create new mandant | — |
| `mandants show {id}` | Detail view with upcoming entries | — |
| `mandants add-person {mandant}/{person}` | Add person to group | — |

## Decision Tree

```
User wants to...
├── List calendar entries              → Read references/workflow.md (§ List)
├── Add new entry                      → Read references/workflow.md (§ Add)
├── Show entry details                 → Read references/workflow.md (§ Show)
├── Cancel an entry                    → Read references/workflow.md (§ Cancel)
├── Confirm an entry                   → Read references/workflow.md (§ Confirm)
├── Calendar status overview           → Read references/workflow.md (§ Status)
├── List mandants / recipient groups   → Read references/mandants.md (§ List)
├── Add a new mandant                  → Read references/mandants.md (§ Add)
├── Show mandant with upcoming entries → Read references/mandants.md (§ Show)
├── Add a person to a mandant          → Read references/mandants.md (§ Add-Person)
└── Questions about calendar/mandants  → Answer from CLAUDE.md § Calendar + Mandants
```
