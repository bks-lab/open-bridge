---
summary: "prod-server Setup — Ubuntu 24.04, Tailscale, systemd services"
created: 2026-03
---
# prod-server — Setup Protocol

## Hardware

- Ubuntu 24.04 LTS (VPS or dedicated)
- 4 vCPU, 8GB RAM, 100GB SSD
- Provider: Hetzner / DigitalOcean / AWS

## SSH

SSH key auth, password disabled:

```bash
ssh-copy-id deploy@prod.acme-dev.com
```

## Tailscale

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

Reachable as `prod-server` on Tailscale network.

## Services

Two systemd user services:

| Service | Type | What |
|---------|------|------|
| acme-slack-bot | keepalive | Slack Bot responding to #dev-team |
| acme-email-watcher | scheduled (10min) | Check team@acme-dev.com inbox |

Install:

```bash
mkdir -p ~/.config/systemd/user/
# Copy .service and .timer files
systemctl --user daemon-reload
systemctl --user enable --now acme-slack-bot
systemctl --user enable --now acme-email-watcher.timer
```

## Known Issues

None yet. Document workarounds here as they arise.
