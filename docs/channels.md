---
summary: "Channels — messaging integration concept, channel types, schema overview. Operations live in the channel skill; scheduled jobs in /schedule."
type: guide
last_updated: 2026-06-11
related:
  - ../skills/channel/SKILL.md
  - ../skills/schedule/SKILL.md
  - ../infra/channels/_template.yaml
---

# Channels — Messaging Integration

Connect The Bridge to messaging platforms. Send notifications, receive messages,
and automate outbound communication.

## Channel Types

| Type | Mode | Examples | Use Case |
|------|------|---------|----------|
| **plugin** | tmux keepalive | iMessage, Discord, Slack | Claude Code built-in channel plugins |
| **collector** | scheduled cron | Signal, RSS, Webhooks | Pull-based message collection |
| **bot** | keepalive daemon | Telegram, Slack Bot | Bidirectional messaging bot |
| **api** | on-demand/scheduled | Email (Graph API), Teams | API-based message access |
| **bridge** | background process | WhatsApp (MCP) | MCP-based external service bridge |

## Channel Schema

One file per channel: `infra/channels/<name>.yaml`, created from
`infra/channels/_template.yaml` (the full schema lives there). Overview:

```yaml
name: my-channel
display_name: "My Channel"
type: bot                    # plugin | collector | bot | api | bridge

implementation:
  skill: skill-name          # Claude skill — OR plugin: name@publisher, OR mcp: server-name

runtime:
  remote: server-hostname    # from infra/remotes/*.yaml, or "local"
  mode: on-demand            # tmux | launchd | on-demand
  service: service-slug      # from infra/remotes/{host}.yaml services list

access:
  policy: allowlist          # allowlist | pairing | disabled
  contacts: []               # named handles
  groups: []                 # named group ids

checkin:
  enabled: true              # include in /briefing?

behavior:
  auto_response: false       # auto-respond to messages?

status: active               # pending | active | paused | disabled
```

## Operations

Inventory, health checks, deploy, start/stop live in the `channel` skill
([`skills/channel/SKILL.md`](../skills/channel/SKILL.md)). Scheduled
messages and cron/launchd/systemd jobs are a separate concern owned by the
`/schedule` skill ([`skills/schedule/SKILL.md`](../skills/schedule/SKILL.md)).

## Setup

1. Enable channels: set `channels.enabled: true` in bridge-config.yaml
2. Copy `infra/channels/_template.yaml` to `infra/channels/{name}.yaml`
3. Configure runtime (which server runs the channel)
4. Test: `/channel health`
