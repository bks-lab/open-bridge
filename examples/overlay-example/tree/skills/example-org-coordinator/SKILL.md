---
name: example-org-coordinator
kind: skill
description: >-
  Single entry point for the example-org engagement — board sync against the
  example-board GitHub Project, status-report prep for the example-team mandant,
  documentation routing through the example-docs context, and tenant-aware cloud
  lookups via example-cloud. Reads field schemas from
  workflow/projects/example-board.yaml; routes per rules/org/example-routing.md.
  Trigger: "example-org", "example board", "example-org status", "example-team
  update", "sync example-org".
metadata:
  scope: org
  tools: [Bash, Read, Glob, Grep]
---

# Example-Org Coordinator

Org-overlay skill — materializes to `skills/example-org-coordinator/SKILL.md`
in the consumer. Behavioural content: the overlay engine forces a per-file human
`[y]` before this skill is applied. The top-level `kind: skill` tag and
`metadata.scope: org` are the overlay tripwires; `metadata.scope: org` keeps it
org-internal (never promoted to the CORE/public upstream) and is what
`scripts/validate-skill-scope.py` reads.

## What it does

Coordinates every example-org operation behind one trigger so the main session
never reaches for raw `gh` or `az` commands:

- **Board** — reads field values + state mappings from
  `workflow/projects/example-board.yaml`, then drives the board through
  `github-projects-manager` (issue creation, field transitions, board queries).
- **Status reports** — collects board state into a weekly update for the
  `example-team` mandant (`identity/mandants/example-team.yaml`).
- **Docs** — routes documentation through the `example-docs` context
  (`workflow/contexts/example-docs.yaml`) and its `sync.defaults`.
- **Cloud** — resolves tenant ID + token URI from
  `identity/accounts/example-cloud.yaml` before any cloud op; never hardcodes.

## Conventions

- Never set a board item to "Done" directly — "In Review" first, human confirms.
- Always use the exact Status option strings declared in the project config.
- Follow `rules/org/example-routing.md`; on conflict with a CORE rule, the CORE
  rule wins.
