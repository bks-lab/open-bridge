---
scope: org
description: Org-only routing rule for the example-org engagement — which board, context, and recipient group a touchpoint lands in
---

# Example-Org Routing

Org-overlay rule — materializes to `rules/org/example-routing.md` in the
consumer. Rules are tiered by folder: `rules/org/**` = org tier (additive, like
a nested AGENTS.md). This file ships only in the example-org overlay; it never
touches CORE `rules/*.md`.

## When this rule applies

Any task, document, or outbound message tagged with the `example-docs` context
(or whose repo lives under the `example-org/` GitHub org).

## Routing

- **Board** — every trackable item syncs to `workflow/projects/example-board.yaml`
  (GitHub Project). Issues are created in the `issue_repo` declared there, never
  hand-rolled with raw `gh issue create`.
- **Context** — documentation routes through `workflow/contexts/example-docs.yaml`;
  its `sync.defaults` are the fallback when a STATUS.md omits an explicit `sync:`
  block.
- **Recipients** — outbound status updates default to the `example-team` mandant
  (`identity/mandants/example-team.yaml`). Pick a specific person/channel only
  when the message is addressed to one.

## Guardrails

- Cloud operations against the example-org tenant read
  `identity/accounts/example-cloud.yaml` first for tenant + token URI — never
  hardcode IDs or inline a secret.
- Treat `rules/org/**` as advisory layering on top of CORE rules; on conflict,
  the CORE rule wins and this file defers.
