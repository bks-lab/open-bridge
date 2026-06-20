# /schedule — Scheduled Task Management

Manage scheduled messages and tasks defined in `infra/channels/_scheduled.yaml`.

## Guard

`channels.enabled` must be `true` in bridge-config.yaml.

## Arguments

- `(none)` or `list` — show all scheduled tasks with status
- `create` — interactive creation of a new scheduled message
- `deploy` — generate platform-native jobs and deploy to remotes
- `disable {name}` — disable a scheduled task
- `status` — check if deployed jobs are running on their remotes

## Workflow: List

1. Read `infra/channels/_scheduled.yaml`
2. For each schedule entry, show: name, channel, recipient, cron (human-readable), enabled
3. Render:

```
Scheduled Messages (3)
══════════════════════
  ✓ Daily Status     email → team@ex.com      Mon-Fri 08:00
  ✓ Weekly Digest    telegram → My Bot         Sunday 10:00
  ✗ Reminder         signal → Alice            (disabled)
```

## Workflow: Create

1. Ask: channel (from infra/channels/*.yaml), recipient, schedule (cron or natural language)
2. Ask: prompt (what should the message contain?)
3. Ask: model (haiku recommended for cost)
4. Add entry to `infra/channels/_scheduled.yaml`
5. Offer to deploy immediately

## Workflow: Deploy

1. Read `infra/channels/_scheduled.yaml`
2. For each enabled schedule:
   a. Determine target remote from channel's `runtime.remote`
   b. Generate platform-native job:
      - **macOS**: launchd plist with `StartCalendarInterval`
      - **Linux**: systemd timer + service unit
      - **Fallback**: crontab entry
   c. Generate send script (uses `claude --print --model {model} "{prompt}"` piped to channel send)
   d. SCP files to server
   e. Reload service manager
3. Verify each job is loaded
4. Report deployment status

## Workflow: Disable

1. Find entry in `_scheduled.yaml` by name
2. Set `enabled: false`
3. If deployed, unload on remote server
4. Confirm

## Workflow: Status

1. For each enabled schedule, SSH to runtime server
2. Check if launchd/systemd job exists and last run time
3. Report: running, last success, last failure
