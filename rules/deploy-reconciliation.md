---
scope: core
description: Declared status (status:) in infra/channels/infra/remotes/work is never trusted — actual state lives on the remote and must be probed before any "running" claim.
---

# Deploy Reconciliation

The Bridge holds many `status:` fields — in `infra/channels/*.yaml`, in
`infra/remotes/*.yaml` service blocks, in `work/tasks/*/STATUS.md`. These are
**declarations**. Actual state lives on the target remote. Declared state
drifts silently. Never conflate them.

## The rule

Before claiming "is running / is deployed / is live" for any service,
channel, bot, scheduler job, or launchd/systemd unit:

1. **Read the declaration** (`infra/channels/*.yaml` / `infra/remotes/*.yaml` /
   `STATUS.md`) — note expected label, mode, remote.
2. **Probe reality on the remote** — do not trust the `status:` field.
3. **Surface drift** — if declaration and reality disagree, report it
   before proceeding.

### Legal values for `status:`

| Value | Meaning | When |
|---|---|---|
| `pending` | Never deployed yet | Template default, pre-first-deploy — legitimate resting state |
| `active` | Verified running on the remote | Only after the full deploy cycle (below) passes |
| `paused` | Deliberately stopped | Deploy intact, runtime disabled by choice |
| `disabled` | Retired, kept for reference | Units removed from the remote |

**Illegal as resting states** (these are todo markers — clear them or
downgrade to `pending` before closing the session): `deployed-pending-bootstrap`,
`wip`, `in-progress`, anything custom. Their presence = unfinished work
someone else will inherit silently.

## The deploy cycle (bootstrap → verify → publish status)

Whenever a service lands on a remote, the full cycle runs. Omitting step 3
or 4 is **unfinished work**, regardless of what `status:` says.

1. **Stage** — SCP plist/unit/script to the remote. Files on disk ≠ deployed.
2. **Bootstrap** — load the unit:
   - macOS launchd: `launchctl bootstrap gui/$(id -u) <plist>` then
     `launchctl enable gui/$(id -u)/<label>`
   - Linux systemd: `systemctl --user enable --now <unit>` (or system-wide)
   - Cron: install via `crontab` — no bootstrap step, but verify with
     `crontab -l | grep <marker>`
3. **Verify presence** — the service manager acknowledges the unit:
   - launchd: `launchctl list | grep <label>` returns a line
   - systemd: `systemctl is-enabled <unit>` and `is-active <unit>`
   - On failure: do not write `status: active` — leave as `pending` and
     surface the error.
4. **Verify behavior** (for pipelines with output artifacts) — trigger the
   unit and confirm the expected artifact appears within the expected
   window. For watch-path pipelines: `touch` the trigger file, then poll
   for the output.
5. **Publish status** — only now set `status: active` in the yaml, update
   `work/board.md` to match any `work/tasks/*/STATUS.md`, commit.

## The `verify:` schema

Each declaration carries a machine-readable truth probe so reconciliation
can run unattended:

```yaml
verify:
  # Service-manager presence check
  service_check: "launchctl list | grep com.example.my-service"
  # OR for systemd:
  # service_check: "systemctl --user is-active my-service"

  # Optional: output-artifact probe (for pipelines that produce files)
  artifact_probe:
    path: "~/some/output/**/*.m4a"       # glob, relative to remote $HOME
    within_minutes: 60                    # max time after trigger
    expected_after: "trigger description" # human-readable, e.g. "new .md in briefings/"
```

`infra/channels/_template.yaml` and the service entries in `infra/remotes/_template.yaml`
both include this block.

## Health check consumers

`/channel health` and `/remote health` iterate all declarations, run the
`verify:` probes over SSH, and render a single pass/fail table. Any
declaration with `status: active` that fails its probe is a reconciliation
incident — the declaration is wrong, fix it or fix the deployment.

## Anti-patterns

- **"plist deployed" is not deployed.** Files on disk without
  `launchctl bootstrap` + `launchctl list`-confirmation are staged, not running.
- **`status:` as a todo marker.** Do not use `status:` to track
  "in progress" — that's what `work/tasks/<slug>/STATUS.md` is for.
  `status:` reflects actual runtime state.
- **Board ≠ STATUS.md drift.** `work/board.md` summary must track the
  Doing task's `STATUS.md`. When they diverge, `STATUS.md` wins; update
  the board.
- **Fire-and-forget chains.** Scheduled job A writes a file; watch-path
  pipeline B generates a derived artifact. If B is silently broken, A
  looks fine. Declare the expected artifact via `artifact_probe` so the
  gap is visible.

## When to read this file

- Before ANY `/channel deploy`, `/remote deploy`, or manual `scp + launchctl`
  dance on a remote.
- Before declaring a service "running" / "deployed" in a response.
- When `status:` is anything other than `active` and the user references
  the thing as if it should be working.
- On `/channel health` or `/remote health` — the probe semantics live here.
