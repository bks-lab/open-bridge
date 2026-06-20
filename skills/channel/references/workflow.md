# Channels — Detailed Workflows

## Channel Types

| Type | Runtime | Examples | How It Works |
|------|---------|---------|-------------|
| **plugin** | tmux keepalive on server | iMessage, Discord, Slack | Claude Code channel plugin runs in persistent tmux session |
| **collector** | scheduled cron/launchd | Signal, RSS, Webhooks | Daemon pulls messages periodically, stores as JSONL |
| **bot** | keepalive daemon | Telegram, Slack Bot | Responds to incoming messages in real-time |
| **api** | on-demand or scheduled | Email (Graph API), Teams | API calls to read/send messages |
| **bridge** | background process | WhatsApp (MCP) | MCP server bridges external service to Claude |

## Channel Schema

Each channel in `infra/channels/{name}.yaml` has:

```yaml
name: string              # identifier
display_name: string      # human-readable
type: string              # plugin | collector | bot | api | bridge

implementation:
  skill: string           # Claude skill name
  # OR plugin: string     # Claude Code plugin (name@publisher)
  # OR mcp: string        # MCP server name

runtime:
  remote: string          # hostname from infra/remotes/*.yaml, or "local"
  mode: string            # tmux | launchd | on-demand
  service: string         # service slug from server's services list
  session: string         # tmux session name (for tmux mode)
  start_command: string   # command to start (for on-demand)

access:
  policy: string          # allowlist | pairing | disabled
  self: string            # own address (email, phone, handle)
  contacts: []            # array of { name, handle/chat_id }
  groups: []              # array of { name, id }

checkin:
  enabled: boolean        # include in /briefing?
  stream: string          # stream label (C, D, E...)
  priority: number        # sort order (lower = earlier)

behavior:
  auto_response: boolean  # auto-respond to incoming?
  signature: boolean      # add "Sent by The Bridge"?
  business_hours_only: boolean

status: string            # pending | active | paused | disabled
```

## Overview Workflow (/channel)

1. Read all `infra/channels/*.yaml` (excluding `_template.yaml`)
2. Read `infra/channels/_scheduled.yaml` for scheduled count
3. For each channel: show name, type, status, runtime
4. Show scheduled message count

## Health Check Workflow (/channel health)

For each channel with `runtime.remote` != "local":
1. SSH to the server
2. Run `verify.service_check` from the channel yaml (falls back to
   runtime-mode default if empty — `launchctl list | grep <label>` for
   launchd, `systemctl --user is-active` for systemd, `tmux has-session`
   for tmux)
3. If `verify.artifact_probe` is defined: check newest matching file
   against `within_minutes` threshold
4. Report pass/fail per channel. Any channel with `status: active` that
   fails its probe is a **reconciliation incident** — surface it, don't
   silently tolerate drift.

Full semantics: [`rules/deploy-reconciliation.md`](../../../rules/deploy-reconciliation.md).

## Deploy Workflow (/channel deploy {name})

Follow the 5-step cycle in
[`rules/deploy-reconciliation.md`](../../../rules/deploy-reconciliation.md) —
it's the single source of truth. Channel-specific specifics:

**Staging paths** (step 1, SCP from local to `runtime.remote`):
- `runtime.mode: launchd` → `~/Library/LaunchAgents/{label}.plist`
- `runtime.mode: systemd` → `~/.config/systemd/user/{label}.service`
- `runtime.mode: tmux` → runs from `runtime.start_command`, nothing to stage
- `runtime.mode: on-demand` → document `start_command`; no bootstrap

**Bootstrap command by mode** (step 2, via SSH):
- launchd → `launchctl bootstrap gui/$(id -u) {plist} && launchctl enable gui/$(id -u)/{label}`
- systemd → `systemctl --user enable --now {unit}`
- tmux → `tmux new-session -d -s {session} '{command}'`

**Presence check** (step 3): run `verify.service_check` from the yaml. Empty?
Derive from `runtime.mode` as described in `infra/channels/_template.yaml`.

**Publish** (step 5): edit `infra/channels/{name}.yaml`, set `status: active`,
commit. Any earlier failure → leave `status: pending` and surface the error.
Never leave `deployed-pending-bootstrap` as a resting state.

## Scheduled Messages

### Architecture

```
infra/channels/
├── _scheduled.yaml                  # All schedule definitions
└── scheduled/{slug}/                # Per-schedule artifacts
    ├── context.md                   # Personal context for prompt enrichment
    └── send.sh                      # Generated send script (/schedule deploy)
```

### Schema (in _scheduled.yaml)

Each schedule supports:
- **Single cron:** `cron: "0 8 * * 1-5"`
- **Multiple cron:** `cron: ["0 8 * * 1-5", "0 9 * * 0,6"]` — creates one job per expression
- **Context file:** `context: scheduled/{slug}/context.md` — injected into prompt for personalization
- **Model selection:** `haiku` for routine, `sonnet` for complex content

### Deploy Workflow (/schedule deploy)

1. Read `infra/channels/_scheduled.yaml`
2. For each enabled schedule:
   a. Find channel in `infra/channels/{name}.yaml`
   b. Get runtime server from channel config
   c. Generate send script (`infra/channels/scheduled/{slug}/send.sh`):
      ```bash
      #!/bin/bash
      # Auto-generated by /schedule deploy
      CONTEXT=""
      [ -f "$CONTEXT_FILE" ] && CONTEXT="Context: $(cat $CONTEXT_FILE)"
      MESSAGE=$(claude --print --model {model} "$CONTEXT {prompt}")
      # Channel-specific send command (osascript, curl, etc.)
      ```
   d. Generate platform-native job:
      - **macOS (launchd):**
        ```xml
        <plist>
          <dict>
            <key>Label</key><string>com.bridge.{schedule-slug}</string>
            <key>ProgramArguments</key>
            <array><string>/path/to/send.sh</string></array>
            <key>StartCalendarInterval</key>
            <!-- Generated from cron expression -->
          </dict>
        </plist>
        ```
      - **Linux (systemd):** timer + service unit
      - **Fallback:** crontab entry
   e. SCP script + job definition to server
   f. Load/reload service manager

### Token Economy

- **haiku** for routine messages (greetings, reminders, digests)
- **sonnet** for complex content (status reports with data analysis)
- **opus** only when explicitly required (never for scheduled messages)
- Pre-check before LLM: skip if no data to report (empty inbox, no commits)

## Start/Stop Workflow

`/channel start {name}` or `/channel stop {name}`:
1. Read channel config
2. Determine runtime mode (tmux, launchd, on-demand)
3. SSH to server and start/stop appropriately
4. Verify status change
