---
name: cockpit
description: >-
  Open the Bridge cockpit, the local web page (127.0.0.1) that watches and steers the whole Bridge: briefing, work (inbox and tasks), agent tabs and sessions, workers, machines, tokens. Starts the server if needed. Not the per-project view (/dashboard). Trigger: "/cockpit", "cockpit", "open the cockpit", "web cockpit", "bridge dashboard in the browser", "Cockpit öffnen".
metadata:
  scope: core
---

# Cockpit

Opens the cockpit (`scripts/bridge-cockpit.py`, guide `docs/bridge-cockpit.md`).
It is an early version (alpha) and still being extended; mention that when a user meets it for the first time.

## Run

```bash
python3 scripts/bridge-cockpit.py open --json
```

It starts the server in the background (or reuses the running one) and opens the page itself: a
browser tab in the control workspace when the terminal driver can, else the default browser. The
answer is `{"opened": ..., "port": ..., "reused": ...}`: report in one line where it `opened` and
the address `http://127.0.0.1:<port>/`, nothing else. Never run `url` or `start` just to show a link:
their link carries a login code, and a login code does not belong in the conversation. Arguments after `/cockpit` pass through:
`--via auto|cmux|system|none` picks where it opens, `status` and `stop` run that command instead of
`open`. `/cockpit url` is never run here: tell the user to type `python3 scripts/bridge-cockpit.py
url` in their own terminal, which prints a login link to open by hand.
`--json` applies only to `open`, `start` and `status`; never append it to `stop`, which refuses it
with a usage text (exit 2).

After opening, run `python3 scripts/bridge-cockpit.py status --json` once. When `can_launch` is
`false`, no terminal driver starts agent tabs, so every "Let AI do it" in the cockpit would fail:
say so in one line and offer to set `workplace.driver` in `bridge-config.yaml` for the terminal this
machine has (cmux: `skills/cmux/scripts/cmux_driver.py`, tmux: `skills/tmux/scripts/tmux_driver.py`,
detected as in `bridge-onboard` D1d), written only on a yes, then `stop` and `open` again. `null`
means the driver did not answer: say nothing.

On a first open, add one line: **Settings, Setup** (the first area of Settings, whose tab carries a count while something is wrong) lists what still keeps the cockpit
from working well and what can be switched on, and the first visit's welcome offers it before the tour.

## When it refuses

| Exit | Meaning | Say |
|---|---|---|
| 1 | not running (from `status` or `stop`), not an error | that the cockpit is not running and that `/cockpit` (or `python3 scripts/bridge-cockpit.py start`) starts it |
| 2 | with a usage text on stderr: a wrong call (an unknown subcommand or flag) | nothing to the user about the config: fix the arguments and run it again |
| 2 | without a usage text: `cockpit.enabled` is not `true` (or the config is invalid) | how to switch it on: `cockpit: {enabled: true}` in `bridge-config.yaml` |
| 3 | the port is taken | which port (`cockpit.port`) and that another program holds it |
| 4 | the server did not come up | the last lines of `.bridge/cockpit/stdout.log`, then `server.log` |
| 5 | the page could not be opened | that `python3 scripts/bridge-cockpit.py url` in a terminal prints a login link to open by hand (once, within a minute) |
