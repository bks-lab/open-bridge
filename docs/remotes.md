---
summary: "Remote machines — concept, where instances live, service types, hard rules. Operations live in the remote skill."
type: guide
last_updated: 2026-06-11
related:
  - ../skills/remote/SKILL.md
  - ../infra/remotes/_template.yaml
---

# Remotes — Remote Machine Management

A "remote" is a physical or virtual machine reachable over SSH that runs
services for your bridge — message bots, scheduled tasks, health monitors,
data collectors. Not all remotes are servers — desktops, routers, and USB
toolkits qualify too.

## Where instances live

One file per machine: `infra/remotes/<name>.yaml`, created from
`infra/remotes/_template.yaml` (the full schema lives there), with an
optional `<name>-setup.md` companion for BIOS / first-run / hardware
quirks. Enable the feature with `remotes.enabled: true` in
`bridge-config.yaml`.

## Service Types

| Type | Behavior | Platform |
|------|----------|----------|
| **keepalive** | Always running, auto-restart on crash | launchd KeepAlive / systemd Restart=always |
| **scheduled** | Runs on cron schedule | launchd StartCalendarInterval / systemd timer |

## Hard Rules

- **Tailscale first**, LAN as fallback — LAN fails on VPN or foreign networks
- **No destructive operation** (shutdown, reboot, format) without per-action `[y]`
- **Never store credentials** in `infra/remotes/*.yaml` — KeyVault / 1Password URIs only
- **Honor `wake_on_lan.enabled: false`** — never force wake a machine that opted out

## Operations

All commands and workflows live in the `remote` skill
([`skills/remote/SKILL.md`](../skills/remote/SKILL.md)):

- Inventory, Wake-on-LAN, SSH/RDP connect, shutdown/reboot, reachability
  → `skills/remote/references/fleet.md`
- Deploy, health checks, logs, restart, config sync
  → `skills/remote/references/workflow.md`
