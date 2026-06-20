# Remotes — Detailed Workflows

## Remote Schema

Each remote in `infra/remotes/{hostname}.yaml`:

```yaml
name: string            # identifier
type: string            # macos | linux | windows
os: string              # "macOS 15.4 Tahoe", "Ubuntu 24.04"

ssh:
  user: string
  host: string          # hostname or IP
  port: number          # default 22

network:
  tailscale_ip: string  # VPN IP (preferred — works from anywhere)
  hostname: string      # mDNS / Tailscale hostname
  lan_ip: string        # local network IP (fallback, same network only)

capabilities: []        # ssh, rdp, docker, git, services, claude, gpu, boot, forensics, pentesting

services: []            # only if 'services' in capabilities
  # - slug: string      # identifier
  #   label: string     # launchd/systemd unit name
  #   type: string      # keepalive | scheduled | oneshot
  #   schedule: string  # cron syntax (only for scheduled)
  #   check: string     # command to check status
  #   log: string       # log file path

status: string          # online | offline | pending
```

## Dashboard Workflow (/remote)

1. Read all `infra/remotes/*.yaml` (excluding `_template.yaml`)
2. For each remote: show name, type, capabilities, service count, status
3. Optionally quick-ping via `ssh -o ConnectTimeout=3 {host} echo ok`

## Health Check Workflow (/remote health {hostname})

1. Read `infra/remotes/{hostname}.yaml`
2. SSH connect with timeout
3. Run parallel checks:
   ```bash
   # System vitals
   df -h / | tail -1                     # Disk
   uptime                                # Uptime + load
   # Memory (platform-dependent)
   # macOS: vm_stat | head -5
   # Linux: free -h
   # Windows: wmic OS get FreePhysicalMemory
   
   # Services
   for each service: run check command
   
   # Recent logs
   for each service: tail -3 {log_path}
   ```
4. Render health dashboard with indicators (✓/✗/⚠)

## Service Management

### Restart (/remote restart {hostname} {service})

1. Find service in remote YAML by slug
2. Determine platform from remote type:
   - **macOS:** `launchctl kickstart -k gui/$(id -u)/{label}`
   - **Linux:** `systemctl --user restart {label}`
   - **Windows:** `sc stop {label} && sc start {label}`
3. Wait 5 seconds
4. Re-run check command to verify
5. Log action to work/log.md

### Logs (/remote logs {hostname} {service})

1. Find service log path from YAML
2. SSH: `tail -50 {log_path}`
3. Optionally: `tail -f` for live monitoring

## Deploy Workflow

Follow the 5-step cycle in
[`rules/deploy-reconciliation.md`](../../../rules/deploy-reconciliation.md).
Remote-specific specifics:

**Staging paths** by platform:
- macOS → `~/Library/LaunchAgents/{label}.plist`
- Linux → `~/.config/systemd/user/{label}.service` (+ `.timer` if scheduled)

**Bootstrap**:
- macOS → `launchctl bootstrap gui/$(id -u) {plist} && launchctl enable gui/$(id -u)/{label}`
  (prefer `bootstrap` over legacy `launchctl load`)
- Linux → `systemctl --user daemon-reload && systemctl --user enable --now {unit}`

**Presence check** (step 3): run the service's `check:` field from the
remote yaml. Empty output → bootstrap silently failed, don't flip `status:`.

## Sync Workflow (/remote sync {hostname})

Pushes configuration files from the bridge to a remote machine.

1. Read remote YAML for SSH config
2. Define sync manifest — files to push:
   - Terminal configs (p10k theme, terminal preferences)
   - Bridge scripts (send scripts, health checks)
   - Channel service scripts (from `infra/channels/scheduled/*/send.sh`)
3. For each file: `scp {local} {user}@{host}:{remote}`
4. **Skip machine-specific files** (.zshrc, .zshenv, .zprofile)
   These contain machine-local paths and aliases — syncing them breaks the target.
5. Report what was synced and what was skipped

## Connection Helpers

- **Prefer Tailscale** hostname/IP when available (works from anywhere, even across networks)
- **Fall back to LAN IP** only if Tailscale is unavailable (same network required)
- SSH config: `ConnectTimeout=5`, `StrictHostKeyChecking=accept-new`
- If server has NOPASSWD sudo: execute admin commands directly, don't ask user to do it
