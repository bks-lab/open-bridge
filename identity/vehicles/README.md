---
summary: "Vehicle registry — owned or leased vehicles, their tax classification, and pointers to everything they generate."
type: readme
last_updated: 2026-08-04
related:
  - identity/personas/_template.yaml
  - identity/contracts/_template.yaml
  - infra/remotes/_template.yaml
---

# identity/vehicles/

One file per vehicle the user owns or leases. Carries identification, the
persona that bears the tax consequences, and — the actual point — **pointers to
every other place the vehicle already lives**.

## Why here

`identity/` answers *who am I, to whom do I send*. An owned asset attached to a
tax entity belongs to that question, alongside `personas/` (self), `accounts/`
(cloud identities) and `contracts/` (obligations).

It is deliberately **not** `infra/`, which answers *where does what run, how do I
reach it*. An associated wallbox or tracker IS infra and lives in
`infra/remotes/` — the vehicle itself is not.

## The problem this type solves

A vehicle scatters its traces. A single car legitimately touches:

| Where | What |
|---|---|
| `identity/personas/` | which tax entity bears it |
| `identity/contracts/` | the electricity or fuel contract |
| `infra/remotes/` | wallbox, tracker, telematics box |
| `work/streams/` | telemetry snapshots, receipt registers |
| `work/tasks/` | the logbook for the current year |
| document archive | registration, insurance, purchase invoices, tax notices |

Every one of those placements is correct. Together they mean the owner has to
remember six paths — and in practice discovers half of them again each time.

**This file is an entry point, not a warehouse.** It never copies those
contents; it names their location so the next reader gets there in one hop.
Keep the pointers current and the scatter stops mattering.

## Conventions

- Filename = the plate as a lowercase-kebab slug (`ab-cd-1234.yaml`), no
  type-prefix.
- `scope:` is **never** `core` — plate, VIN and tax data are PII. Use
  `personal` to route into a personal overlay, `user` to stay strictly local.
- `plate_variants:` is load-bearing, not decoration. Counterparties spell a
  plate differently (hyphenated, unspaced, with or without an EV suffix) and
  document-routing rules match on the string. A missing variant fails
  **silently** — the document routes somewhere else and nobody sees an error.
  Add a variant the first time you meet it.
- Facts that recur yearly and are easy to misremember (tax exemptions and their
  end date, subsidy claims, consumption figures used for conversions) belong in
  the file. Anything that changes per document does not.

## Files

- `_template.yaml` — copy this (CORE)
- `_schema.yaml` — JSON Schema Draft 2020-12 (CORE)
- `<plate-slug>.yaml` — your instances (USER)
- `<plate-slug>.README.md` — optional companion for purchase decisions,
  cost-allocation reasoning, service history
