# cockpit-relay

A Claude Code mod that lets the Bridge cockpit (`scripts/bridge-cockpit.py`)
ask this Claude Code session. "To the control session" on the cockpit page
reaches the session through it. Contract and limits:
[`docs/bridge-cockpit.md`](../../docs/bridge-cockpit.md), section 5.

What it does, and nothing else:

- writes a heartbeat every 5 seconds to
  `.bridge/cockpit/relay/heartbeat/<session>.json`: alive, busy, the question
  in flight, and where the session runs (the cmux surface, else the tmux pane
  such as `%3`, else `null`), so the server can pick the control session;
- reads `.bridge/cockpit/relay/inbox/` every 2 seconds and submits a question
  only when the server addressed it to this session and signed it with
  `relay.key` (kept outside the Bridge in `$BRIDGE_COCKPIT_KEY_DIR`, else
  `~/.local/state/bridge-cockpit/`);
- submits one question at a time, never during a running turn, never twice,
  and writes what became of it to `.bridge/cockpit/relay/done/<id>.json`
  (answered, aborted, error, expired, stuck, rejected).

It came out of the retired `briefing-ui` mod, so the cockpit kept reaching the
control session when the briefing card went away.

## Switch

```yaml
cockpit:
  enabled: true
  relay: true      # off unless true: without it the page works, no session takes questions
```

Only the top-level `cockpit:` block counts. The relay never runs in an agent tab (`BRIDGE_TAB_SLUG`
set), in a `claude -p` or SDK run, or outside a Bridge.

## Install and test

From the Bridge folder:

```bash
claude plugin marketplace add ./mods --scope local
claude plugin install cockpit-relay@open-bridge-mods --scope local
npx -y -p typescript@5.6.3 -c 'node mods/cockpit-relay/tests/pure.test.mjs'   # pure functions
claude plugin test mods/cockpit-relay                                          # engine tests, local only
```
