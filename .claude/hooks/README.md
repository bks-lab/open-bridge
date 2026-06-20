# `.claude/hooks/` — Runtime enforcement hooks

The Bridge ships optional Claude Code hooks for runtime
enforcement of invariants that are otherwise documentation-only.
Hooks are **opt-in** — they are not registered in any default
`settings.json` shipped with the repo. You decide which to enable
in your own `.claude/settings.json`.

## Available hooks

### `session-start-phase0.sh` — Branch/config state detection (recommended)

Replaces the manual Phase 0 check documented in `rules/session-start.md`
with a deterministic SessionStart hook. Runs `git branch --show-current`,
checks for `user/*` branches and `bridge-config.yaml`, then emits a
`<bridge-phase0>` block to stdout with the detected state (NORMAL,
WRONG_BRANCH, ORPHAN, NEW_USER, BROKEN_CONFIG, BROKEN_USER_BRANCH,
CORE_DEV) and the next action.

Bonus signals (NORMAL state only):
- CORE commits ahead of current user branch → offers to merge the core branch (`git merge main`)
- `work/log.md` older than 24h → hints at a stale day-block

**Enable** (see § How to enable below):
```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {"type": "command",
           "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/session-start-phase0.sh"}
        ]
      }
    ]
  }
}
```

### `worklog-drift-check.sh` — Stop hook, enforces work-log freshness

When the turn edited code/docs/configs but `work/log.md` has no row for
today, blocks stop (exit 2) with a reminder. Claude sees the reminder
in-band and adds a log entry before ending the turn. Only fires on
`user/*` branches. Drop an empty `.bridge-nolog` file in the repo root
for a read-only session.

Trigger files: `*.md|py|ts|tsx|js|yaml|yml|json|sh|rs|go` or writes
anywhere under `skills/`, `protocols/`, `contexts/`, `agents/`,
`identity/personas/`, `calendar/`, `mandants/`, `infra/remotes/`.

**Enable** (see § How to enable below):
```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {"type": "command",
           "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/worklog-drift-check.sh"}
        ]
      }
    ]
  }
}
```

### `consent-boundary-check.sh` — Layer 2 consent boundary

Blocks or warns on writes that violate the consent boundary
invariant (folder = consent boundary). Fires on `PreToolUse` for
`Bash`, `Write`, `Edit`, and `NotebookEdit`.

**What it does:**
- Discovers the currently active agent instance (from the
  `BRIDGE_ACTIVE_INSTANCE` environment variable, or the most
  recently modified `log.md` in `agents/active/` — the `agents/`
  tree belongs to the Bridge-Agent layer, which is in development
  and not part of this release (see the README.md roadmap note);
  on bridges without it the hook passes through)
- Checks the target path against universal boundary rules:
  - Writes to *another* instance's folder → forbidden
  - Writes to `identity/personas/*.yaml` (except template/examples) → warn
  - Writes to `bridge-config.yaml` → warn
  - Writes to `protocols/standing-orders/routing-<other>.md`
    (cross-persona routing) → forbidden
- Logs every tool call to stderr for auditability
- In warn-only mode (default), exit 0; in block mode
  (`BRIDGE_CONSENT_BLOCK=1`), exit 2 to deny the tool call

**Status**: MVP. The hook uses heuristic path extraction from
Bash commands and does not yet parse the `consent_scope` block
from SKILL.md. This is a conservative first step — the goal is
visibility and a few hard-wired rules, with more sophistication
landing once the pattern proves out.

## How to enable

Add a `PreToolUse` hook block to your personal
`.claude/settings.json` (which is gitignored — see `.gitignore`):

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash|Write|Edit|NotebookEdit",
        "hooks": [
          {
            "type": "command",
            "command": "$BRIDGE_ROOT/.claude/hooks/consent-boundary-check.sh"
          }
        ]
      }
    ]
  }
}
```

Set `BRIDGE_ROOT` in your shell profile to the absolute path of
your Bridge checkout:

```bash
# ~/.zshrc or ~/.bashrc
export BRIDGE_ROOT="$HOME/Developer/open-bridge"
```

Restart Claude Code for the settings.json change to take effect.

## Enabling block mode

By default the hook runs in **warn-only** mode — it logs every
risky write to stderr but exits 0 so the tool call proceeds.
This lets you see what would be blocked without actually breaking
any workflow.

Once you have watched a few sessions and adjusted any false
positives, enable blocking by adding the env var to your hook
command:

```json
{
  "type": "command",
  "command": "BRIDGE_CONSENT_BLOCK=1 $BRIDGE_ROOT/.claude/hooks/consent-boundary-check.sh"
}
```

In block mode, a forbidden write exits the hook with code 2,
which Claude Code treats as a PreToolUse denial — the tool call
is cancelled and Claude sees an error in-band.

## Disabling

Remove the hook entry from your `.claude/settings.json` and
restart Claude Code. The hook script itself can stay on disk; it
does nothing until a settings.json references it.

## Telling the hook which instance is active

Two ways:

1. **Environment variable**: set `BRIDGE_ACTIVE_INSTANCE` in the
   shell session where Claude Code runs. This is reliable but
   requires you to update it each time you switch instances.

   ```bash
   export BRIDGE_ACTIVE_INSTANCE="archivist-freelancer"
   ```

2. **Automatic detection**: the hook falls back to "most
   recently modified `log.md`" under `agents/active/`. This
   works well in practice because the active instance is usually
   the one that just wrote its log.

If neither is set, the hook passes through without checking —
it does not guess.

## Debugging

Watch stderr of the hook:

```bash
# In one terminal, tail a log file the hook writes to
tail -f /tmp/bridge-consent.log

# In your .claude/settings.json, tee stderr to that file:
"command": "$BRIDGE_ROOT/.claude/hooks/consent-boundary-check.sh 2>>/tmp/bridge-consent.log"
```

## Related

  — full three-layer design
  — the active instance model
  how spawning multiplies write-points
