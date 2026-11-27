---
name: bridge-attach
description: 'Attaches this Bridge to an agent session that works in another repo (Claude Code, Codex, Copilot CLI): one launcher, Phase 0 against the Bridge root, a short attach text, the Bridge hooks and memory, nothing written into the repo. Trigger: "/bridge-attach", "attach the bridge", "bridge in this repo", "start claude with the bridge", "bridge-attach".'
metadata:
  scope: core
---

# bridge-attach

A Bridge session starts in the Bridge folder; the work happens in repos. This skill gives a
session in any repo exactly one Bridge, the one this skill lives in. Background, measurements
and limits: [`docs/bridge-attach.md`](../../docs/bridge-attach.md).

> **Paths.** `$SKILL_DIR` is this skill's folder (the Base directory). The Bridge root is
> `$SKILL_DIR/../..`. Every Bridge command below runs through `<root>/bin/bridge-run`, which
> executes it in the Bridge root, so the session's own folder never changes.

## Start a session with the Bridge (the normal way)

From the repo, by the launcher's full path:

```bash
<root>/bin/bridge-attach claude            # claude args after it, e.g. --model sonnet
<root>/bin/bridge-attach codex
<root>/bin/bridge-attach copilot
<root>/bin/bridge-attach plan claude       # print what would run, start nothing
```

The launcher refuses (exit 3) when the Bridge is not in state NORMAL (a `user/*` branch with
`bridge-config.yaml`) or when the folder is inside the Bridge itself. It prints one line per
limit that applies, for example "no Bridge memory inside a cmux-style terminal".

## Attach in a running session

1. Skills: if this skill is not listed, the user types `/add-dir <root>` first (Claude Code);
   Bridge skills and subagents then load.
2. Run `<root>/bin/bridge-run python3 scripts/bridge-attach.py slice --cwd "$PWD"` and take its
   output as this session's attach text. It names the manual, the logging command, the inbox and
   the state of the repo's context.
3. Say what is not attached this way: the Bridge's project hooks (log check, time tracking) and
   its memory as auto memory. Those come only with the launcher.

The attach text in a running session is conversation content: after `/compact` the most recent
skill output survives up to 5,000 tokens. The launcher's text is part of the system prompt and
survives compaction whole.

## What it never does

- Write into the repo the session works in.
- Run Phase 0 or onboarding in that repo.
- Attach a second Bridge, or read another instance's files.
- Install a hook in the user's global settings: the launcher passes everything per process.

## Check it

```bash
<root>/bin/bridge-run python3 scripts/bridge-attach.py check     # NORMAL user/<name>, exit 0
<root>/bin/bridge-attach plan claude                              # argv, env, files, notes
```

Tests: `scripts/tests/test_bridge_attach.py` (hermetic, throwaway Bridge and repo).
