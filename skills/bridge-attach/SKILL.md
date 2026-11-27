---
name: bridge-attach
description: 'Attaches this Bridge to a Claude Code session that works in another repo: /bridge-attach runs Phase 0 against the Bridge root and puts a short attach text (manual, log, inbox, state of the repo) into the session, at start or later; nothing is written into the repo. Shortcut at start, also for Codex and Copilot CLI: bin/bridge-attach. Trigger: "/bridge-attach", "attach the bridge", "bridge in this repo", "start claude with the bridge", "bridge-attach".'
metadata:
  scope: core
---

# bridge-attach

A Bridge session starts in the Bridge folder; the work happens in repos. This skill gives a
session in any repo exactly one Bridge, the one this skill lives in, at start or in the middle
of the work. Background, measurements and limits: [`docs/bridge-attach.md`](../../docs/bridge-attach.md).

> **Paths.** `$SKILL_DIR` is this skill's folder (the Base directory). The Bridge root is
> `$SKILL_DIR/../..`. Every Bridge command below runs through `<root>/bin/bridge-run`, which
> executes it in the Bridge root, so the session's own folder never changes.

## When the skill runs

1. If `BRIDGE_ATTACH` is `1` in the environment, the session was started with the shortcut
   below and is attached already. Run step 2 only when the user asks for a fresh state.
2. Run `<root>/bin/bridge-run python3 scripts/bridge-attach.py slice --cwd "$PWD"` and take its
   output as this session's attach text. It names the Bridge, the context tag of this repo, the
   manual, how Bridge commands and log rows are written, the memory folder, and the state of the
   repo's context: matching inbox items (all others only counted), board counts, recent log rows.
   Exit 3 means the Bridge is not attachable (not on a `user/*` branch, no `bridge-config.yaml`,
   or the folder is the Bridge itself): say why and stop.
3. Say in one line what this way does not attach: the Bridge's project hooks (log check, time
   tracking) and its memory as auto memory. The shortcut at start brings both.

## Three ways in

| Way | How | What comes along |
|---|---|---|
| 1 · in the session, any time | `/bridge-attach`. The skill must be listed: the session was started with `--add-dir <root>`, or the user types `/add-dir <root>` first | attach text as conversation content; after `/compact` the most recent skill output survives up to 5,000 tokens |
| 2 · at start | `claude --add-dir <root> "/bridge-attach"`, or the shortcut `<root>/bin/bridge-attach claude` | the shortcut puts the attach text into the system prompt (no size cap, survives compaction), replays the Bridge's own hooks and sets its memory; also `codex` and `copilot` |
| 3 · automatic | not built: a SessionStart hook cuts its text at 10,000 characters and a hook in the user's global settings fires in every headless run on the machine | a terminal app that starts agents can call `bridge-attach.py plan` instead |

The shortcut refuses (exit 3) on the same conditions as step 2 and prints one line per limit
that applies, for example "no Bridge memory inside a cmux-style terminal".
`<root>/bin/bridge-attach plan claude` prints what it would run and starts nothing.

## What it never does

- Write into the repo the session works in.
- Run Phase 0 or onboarding in that repo.
- Attach a second Bridge, or read another instance's files.
- Install a hook in the user's global settings.

## Check it

```bash
<root>/bin/bridge-run python3 scripts/bridge-attach.py check     # NORMAL user/<name>, exit 0
<root>/bin/bridge-attach plan claude                              # argv, env, files, notes
```

Tests: `scripts/tests/test_bridge_attach.py` (hermetic, throwaway Bridge and repo).
