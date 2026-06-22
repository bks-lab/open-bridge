---
summary: "Example agency setup — cluster-wrapper layout (identity/, infra/, workflow/) plus .claude/agents/ and standing orders"
type: readme
last_updated: 2026-06-20
related:
  - ecosystem.yaml
  - bridge-config.yaml
  - .claude/agents/ops-officer.md
  - protocols/standing-orders/document-work.md
  - identity/mandants/team.yaml
  - workflow/calendars/entries.yaml
---
# Agency Example

Complete reference setup for a small dev team running The Bridge.
Layout follows the cluster-wrapper convention — see
[`docs/structure.md`](../../docs/structure.md) for the full map.

## Layout at a glance

```
examples/agency/
├── bridge-config.yaml          ← user config
├── ecosystem.yaml              ← repo registry
├── .claude/agents/             ← native Claude Code sub-agents
├── identity/
│   ├── accounts/               ← cloud/mail account inventory
│   └── mandants/               ← recipient groups
├── infra/
│   ├── backups/                ← backup topology
│   ├── channels/               ← outbound transports
│   └── remotes/                ← machines
├── workflow/
│   ├── calendars/              ← scheduled outbound
│   └── contexts/               ← per-domain routing
├── protocols/standing-orders/  ← always-on rules
└── work/                       ← task board, daily log, task lifecycle
```

## Agents (`.claude/agents/`)
- [ops-officer.md](.claude/agents/ops-officer.md) — Daily briefings, board management
- [code-analyst.md](.claude/agents/code-analyst.md) — Code review, deep dives
- [deploy-engineer.md](.claude/agents/deploy-engineer.md) — CI/CD, infrastructure

## Standing orders (`protocols/standing-orders/`)
- [document-work.md](protocols/standing-orders/document-work.md) — Standing order: log all work

## Identity (`identity/`)
- [accounts/cloud-provider.yaml](identity/accounts/cloud-provider.yaml) — Cloud-provider account inventory (fictional tenant)
- [mandants/team.yaml](identity/mandants/team.yaml) — Acme Dev core team (4 persons)

## Workflow (`workflow/`)
- [calendars/entries.yaml](workflow/calendars/entries.yaml) — Scheduled entries (digest, standup, retro)
- [contexts/webapp/](workflow/contexts/webapp/) — Per-domain context for the webapp engagement

## Infra (`infra/`)
- [backups/topology.yaml](infra/backups/topology.yaml) — Minimal backup topology (one source, one target, one pipeline)
- [remotes/prod-server.yaml](infra/remotes/prod-server.yaml) — Production remote config
- [channels/email.yaml](infra/channels/email.yaml) — Email channel
- [channels/slack-bot.yaml](infra/channels/slack-bot.yaml) — Slack integration
- [channels/_scheduled.yaml](infra/channels/_scheduled.yaml) — Scheduled messages
- [channels/scheduled/weekend-check/context.md](infra/channels/scheduled/weekend-check/context.md) — Example scheduled job: weekend deploy health check

## Work (`work/`)
The Chaos-Tamer system, populated with example data so a clone shows a *filled* board instead of an empty one:
- [board.md](work/board.md) — generated snapshot: Doing (2), Review (1), Streams (1), Done (1)
- [log.md](work/log.md) — append-only daily log (`| Time | Glyph | Context | What |`)
- [tasks/](work/tasks/) — finite tasks, one `STATUS.md` each (`backlog → doing → review → done`)
- [streams/](work/streams/) — long-runners, excluded from the WIP cap (e.g. `platform-maintenance`)
- [done/2026-06/](work/done/2026-06/) — closed work, archived by month
