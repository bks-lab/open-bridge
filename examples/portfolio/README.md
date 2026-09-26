---
summary: "Runnable demo workspace (Sam Rivera): one person with three hats (consultancy partner, freelancer, private household) and a home server. Personas, a managed client service, life admin, silent digests, drafts-only outbound."
type: readme
last_updated: 2026-09-24
related:
  - CLAUDE.md
  - AGENTS.md
  - bridge-config.yaml
  - ecosystem.yaml
  - protocols/standing-orders/user/outbound-draft-only.md
  - identity/personas/sam-partner.yaml
  - workflow/workloads/daily-health-digest.yaml
  - ../agency/README.md
---
# Portfolio Example

Sam Rivera: a runnable demo workspace for BKS open-bridge. All data is
fictional: every company, person, host and number in this folder is invented.

## Who this shape is for

One person who wears several hats at once and needs them kept apart:

- **Partner** in a three-person consultancy (Northwind Advisory), running a
  managed service for a client (Fabrikam Retail): incidents, a weekly health
  report, a shared board.
- **Independent freelancer** with a current client (Contoso Logistics) and a
  pipeline of applications for the next engagement.
- **Private household**: the annual tax return, an electricity contract and
  its meter, a car with a logbook, a family.
- A small **always-on home server** that runs the digests, the reports and
  the backups for all three.

If your Bridge would carry work AND private life, and more than one legal
entity signs your mail, this is closer to your shape than
[`examples/agency/`](../agency/).

## Try it: 2 minutes, nothing to configure

```bash
git clone https://github.com/bks-lab/open-bridge.git
cd open-bridge/examples/portfolio
claude        # or: codex, copilot
```

Then ask:

- `good morning`: a briefing grouped by hat, with the blocked P1 incident,
  the stale backup, the contract deadline and the overdue pipeline follow-ups
- `switch to the freelance client`: only Contoso, nothing from the other hats
- `what is overdue?`: every dated item before today, each with its file
- `draft the follow-up to Fabrikam`: a draft with the company signature,
  never a sent mail

Everything it answers is read from plain files in this folder. Open
[`work/log.md`](work/log.md) next to it and check. [`CLAUDE.md`](CLAUDE.md)
puts the runtime into demo mode: no onboarding, no setup. The agent may play
along inside this folder; `git restore examples/` puts the demo back. Do not
push: this clone points at the public repo.

## How it differs from `examples/agency`

| | agency (Acme Dev) | portfolio (Sam Rivera) |
|---|---|---|
| People | a team of four to delegate to | one operator; the partners are recipients, not a roster |
| Identities | one company | three personas, each with its own tax data, signature and filing paths |
| Where work syncs | every task has a board | one board (the managed service); freelance work syncs to the client's repo; private tasks are `bridge_only` and never leave |
| Machines | a production server | a laptop plus a home server that watches everything |
| Push messages | standup and digest reminders | silence unless something is red |
| Outbound | sent by the channel | drafts only, a standing order says so |
| Life admin | none | tax return, utility contract and meter, vehicle logbook |

## The patterns worth copying

1. **Personas that carry weight.** A task's `context:` names a context, the
   context names a `persona_ref`, the persona supplies signature, sender and
   filing destination. The wrong signature on a client mail is the classic
   portfolio mistake; this chain prevents it.
   [`workflow/contexts/`](workflow/contexts/) → [`identity/personas/`](identity/personas/)
2. **A managed service as a stream plus incident tasks.** The service never
   ends ([`work/streams/fabrikam-managed-service/`](work/streams/fabrikam-managed-service/STATUS.md));
   each incident is a finite task with `blocked_by:` while the client owes
   something ([`work/tasks/fabrikam-sync-backlog/`](work/tasks/fabrikam-sync-backlog/STATUS.md)).
   The weekly health report is a workload on the home server that writes a
   draft ([`workflow/workloads/fabrikam-weekly-report.yaml`](workflow/workloads/fabrikam-weekly-report.yaml)).
3. **Life admin across personas.** The electricity contract
   ([`identity/contracts/`](identity/contracts/example-power-electricity.yaml)) splits
   its cost between the private and freelance personas; its meter lives in
   [`infra/utilities/`](infra/utilities/home-electricity.yaml); the car
   ([`identity/vehicles/`](identity/vehicles/ex-sr-42e.yaml)) points at its
   logbook task and the tax return that needs it.
4. **Digests that stay silent.**
   [`workflow/workloads/daily-health-digest.yaml`](workflow/workloads/daily-health-digest.yaml)
   checks all three hats every morning and pushes only a red line. The stale
   travel-drive backup in [`infra/backups/_state.yaml`](infra/backups/_state.yaml)
   is the kind of line it exists for.
5. **Outbound is draft only.**
   [`protocols/standing-orders/user/outbound-draft-only.md`](protocols/standing-orders/user/outbound-draft-only.md)
   is the one standing order: "send X" means a finished draft, and the human
   presses send.
6. **The pipeline surfaces at session start.**
   [`work/streams/freelance-pipeline/`](work/streams/freelance-pipeline/STATUS.md)
   is a table with follow-up dates; the briefing names the rows that are past due.

## Layout at a glance

```
examples/portfolio/
├── CLAUDE.md / AGENTS.md       ← demo brief (overrides the repo root in here)
├── bridge-config.yaml          ← user config
├── ecosystem.yaml              ← the three hats and their repos
├── .claude/agents/             ← one sub-agent: paperwork-clerk
├── identity/
│   ├── personas/               ← sam-partner, sam-freelance, sam-private
│   ├── mandants/               ← northwind-team, fabrikam, rivera-family
│   ├── contracts/              ← the electricity contract
│   └── vehicles/               ← the car
├── infra/
│   ├── remotes/                ← sam-laptop, homebox
│   ├── channels/               ← email (drafts), chat-bot
│   ├── backups/                ← topology + last-run state (one stale target)
│   └── utilities/              ← the meter behind the contract
├── workflow/
│   ├── contexts/               ← northwind, contoso, household
│   ├── projects/               ← the one board
│   ├── workloads/              ← daily-health-digest, fabrikam-weekly-report
│   └── calendars/              ← two private reminders
├── protocols/standing-orders/user/  ← outbound-draft-only
└── work/                       ← board, log, tasks, streams, done
```

## Work (`work/`)

- [board.md](work/board.md): generated by `scripts/gen-board.py` from the task
  folders: Doing (2), Review (1), Backlog (1), Streams (2), Done (1)
- [log.md](work/log.md): two days of rows across all three hats
- Tasks, one per hat: `fabrikam-sync-backlog` (incident, blocked),
  `contoso-route-export` (feature, in review), `tax-return-2025` (bridge_only),
  `vehicle-logbook-q3` (backlog)
- Streams: `fabrikam-managed-service`, `freelance-pipeline`
- Done: `meter-reading-q3`
