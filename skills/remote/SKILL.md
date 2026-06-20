---
name: remote
description: 'Owns `infra/remotes/*.yaml` — fleet ops (inventory, WoL, SSH/RDP, reachability, shutdown/reboot) + service ops (health, logs, restart, deploy). "remote" = physical machine, not git remote. Triggers: "remote", "my PC", "my machines", "fleet", "wake", "WoL", "ssh to", "RDP", machine names (homeserver, workstation, laptop, router).'
metadata:
  scope: core
---

# Remote

Manage remote machines defined in `infra/remotes/*.yaml`.
Read the referenced file ONLY when triggered.

## Guard

`remotes.enabled` must be `true` in bridge-config.yaml. If not: inform and exit.

## Arguments

| Argument | Effect | Default |
|----------|--------|---------|
| `(none)` | Dashboard of all remotes | — |
| `{hostname}` | Detail view of one remote | — |
| `health {hostname}` | SSH health check | — |
| `logs {hostname} {service}` | Show recent logs | — |
| `restart {hostname} {service}` | Restart service | — |
| `sync {hostname}` | Sync config files | — |
| `wake {hostname}` | Wake-on-LAN | — |
| `connect {hostname}` | Open SSH / RDP session | — |
| `shutdown {hostname}` | Power off (requires `[y]`) | — |
| `reboot {hostname}` | Restart machine (requires `[y]`) | — |

## Decision Tree

```
User wants to...
├── Remote overview / dashboard        → Read references/workflow.md (§ Dashboard)
├── Detail view of one machine         → Read references/workflow.md (§ Dashboard, single host)
├── Wake / power on a machine          → Read references/fleet.md (§ Stage 3 WoL)
├── Connect via SSH / RDP              → Read references/fleet.md (§ Stage 4 Connect)
├── Reboot or shutdown                 → Read references/fleet.md (§ Stage 5)
├── Check reachability / online?       → Read references/fleet.md (§ Stage 2)
├── Update inventory after a change    → Read references/fleet.md (§ Stage 6)
├── Health check for a machine         → Read references/workflow.md (§ Health Check)
├── View service logs                  → Read references/workflow.md (§ Logs)
├── Restart a service                  → Read references/workflow.md (§ Restart)
├── Sync config to a remote            → Read references/workflow.md (§ Sync)
├── Deploy services to a remote        → Read references/workflow.md (§ Deploy)
├── Identify "my PC" / intent-only     → Read references/fleet.md (§ Stage 1 + Learned routing)
└── Questions about remotes            → Answer from CLAUDE.md § Remotes
```

## Reference map

| File | Owns |
|------|------|
| `references/fleet.md` | Inventory, WoL, connect, shutdown, reachability, "my PC" routing |
| `references/workflow.md` | Service dashboard, health, logs, restart, sync, deploy |

## Hard Rules (non-negotiable)

- **Tailscale first**, LAN as fallback — LAN fails on VPN or foreign networks
- **No destructive operation** (shutdown, reboot, format) without per-action `[y]`
- **Never store credentials** in `infra/remotes/*.yaml` — KeyVault / 1Password URIs only
- **Honor `wake_on_lan.enabled: false`** — never force wake a machine that opted out
- **Read `infra/remotes/{target}.yaml` before any operation** — no guessing
