---
summary: "bridge-attach: a session in any repo gets exactly one Bridge (skills, an attach text, the Bridge's hooks and memory) through one launcher for Claude Code, Codex and Copilot CLI. What each tool supports, what was measured, and the limits that stay."
type: guide
last_updated: 2026-11-27
related:
  - ../skills/bridge-attach/SKILL.md
  - ../scripts/bridge-attach.py
  - ../scripts/tests/test_bridge_attach.py
  - workspaces.md
  - multi-instance.md
  - tool-mapping.md
---

# bridge-attach

A Bridge session starts in the Bridge folder. The work happens in repos. `/workspace` covers
one direction (the Bridge first, repos as members). bridge-attach covers the other: a session
that starts in a repo gets the Bridge.

```bash
cd ~/Developer/some-repo
<bridge>/bin/bridge-attach claude      # or codex, copilot; args after it go to the tool
```

## What the launcher does

1. **Phase 0 against the Bridge root**, read-only (`git -C <root>`), never against the
   repo. Only state NORMAL (a `user/*` branch with `bridge-config.yaml`) attaches. Every other
   state exits 3 with the reason. Phase 0 read in a repo would misroute: a repo on a feature
   branch reads as CORE DEV, one on its default branch as NEW USER (onboarding in the wrong repo).
2. **The attach text** (`scripts/bridge-attach.py slice`), about 4,500 characters on a real
   instance: the Bridge's name and root, the context tag of the repo, where the manual is, how
   Bridge commands run, how a log row is written, the memory, and the state of this repo's
   context (matching inbox items, board counts, the last two days of log rows for the tag).
   Inbox items that do not match are counted, never shown, so private items stay out of repo
   sessions. Statements are factual, not imperative: the Claude Code docs warn that text framed
   as system commands can trigger prompt-injection defenses.
3. **The tool**, with the environment `BRIDGE_ROOT`, `BRIDGE_ATTACH=1`, `BRIDGE_ATTACH_TAG` for
   that process only. Nothing is written into the repo. Run files live in
   `~/.bridge/attach/<bridge folder>/<time>-<pid>/` and are pruned after 7 days.

The context tag is the registry entry whose `github:` matches the repo's origin or whose
`local_path` matches its folder (`ecosystem*.yaml`), else the folder name.

## Per tool

| | Claude Code | Codex | Copilot CLI |
|---|---|---|---|
| Bridge skills | `--add-dir <root>` (with subagents and commands) | no: an added dir contributes no skills | `--add-dir <root>` (`.github/skills`) |
| Attach text | `--append-system-prompt-file`: no size cap, survives compaction | `-c developer_instructions=<text>`: additive, arrives whole | `COPILOT_CUSTOM_INSTRUCTIONS_DIRS` → generated `.github/instructions/bridge.instructions.md` |
| Bridge hooks | generated plugin (`--plugin-dir`) that replays the Bridge's own `.claude/settings*.json` hooks with `CLAUDE_PROJECT_DIR=<root>` | not replayed | not replayed |
| Bridge memory | `--settings {"autoMemoryDirectory"}`, except inside a cmux-style terminal or when the caller passes `--settings` | the text names the memory folder | the text names the memory folder |
| Write to the Bridge | add-dir is writable | `--add-dir <root>` makes it a writable root | `--add-dir <root>` |

Measured on 2026-11-27 with Claude Code 2.1.332, codex-cli 0.172.0 and Copilot CLI 1.0.116
(Copilot only against a local recording endpoint, no model access on the test machine).

## Why it is built this way

- **No SessionStart hook for the text.** A hook's text above 10,000 characters is replaced by a
  2,000-character preview and a file path the model does not read on its own. A lean slice of a
  real instance with the manual measured 26,600 characters.
- **No `--settings` for hooks.** Claude Code applies only the last `--settings`, without a
  warning. A cmux-style terminal wrapper passes its own and drops its hooks when the caller
  passes one. Plugin hooks merge, so the Bridge hooks come as a plugin; `--settings` carries only the
  memory folder, and is left out inside such a terminal (until the wrapper merges settings).
- **No hook in the user's global settings.** It would fire in every headless `claude -p` run on
  the machine, and some of them already export `BRIDGE_ROOT`.
- **AGENTS.md by pointer.** An `AGENTS.md` in an added directory never loads (Claude Code,
  Codex and Copilot alike). The text names it and the model reads it when it needs it.
- **Bridge commands through `bin/bridge-run`.** Most skills name Bridge-relative paths
  (`python3 scripts/...`). Written as they are, they fail in a repo's folder; `bin/bridge-run`
  runs them in the Bridge root without moving the session's shell. Skills meant to act on the
  current repo (dashboard, bridge-greeting) run without it.

## Limits that stay

- Codex lists no Bridge skills. Their SKILL.md files stay readable under the root.
- The Bridge's log check (Stop hook) checks the Bridge's tree, not the repo's changes.
- A running session attached with the skill (`/bridge-attach`) gets no hooks and no memory
  setting, and its attach text is conversation content that compaction may shorten.
- Exactly one Bridge per session. Which Bridge a workspace uses is the launcher's choice; a
  terminal app that starts agents per workspace can call `bridge-attach.py plan` and merge the
  result into its own wrapper.
