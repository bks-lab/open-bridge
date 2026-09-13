---
summary: How this repo's tool names map onto other agent platforms, and what a missing delegation API changes.
type: reference
last_updated: 2026-08-29
related:
  - AGENTS.md
  - docs/skill-distribution-architecture.md
---

# Tool Mapping

`AGENTS.md` is tool-agnostic, but it has to name tools to be useful. It uses the
Claude Code names. If your platform calls them something else, map them here.

| Claude Code | Codex | Copilot CLI | Gemini CLI | Cursor/Windsurf | Purpose |
|-------------|-------|-------------|------------|-----------------|---------|
| Read | shell read (`sed`, `cat`) | read_file | read_file | open/read file | Read file contents |
| Write | `apply_patch` | write_file | write_file | create file | Create/overwrite file |
| Edit | `apply_patch` | edit_file | edit_file | patch file | Patch existing file |
| Bash | shell command | run_command | run_command | terminal | Execute shell command |
| Grep | `rg` | search | search | search | Search file contents |
| Glob | `rg --files` / `find` | find_files | find_files | file search | Find files by pattern |
| Agent | sub-agent tool if available | — | — | background agent if available | Spawn/delegate work |

## The `—` in the Agent row

It means the platform has no delegation API, not that the capability is missing.
A skill that would dispatch a sub-agent runs the same logic **inline** instead.
What changes is the isolation architecture, not the outcome: the work happens in
the main context rather than an isolated one, so its raw output (log dumps, file
trees, API results) lands in the session instead of being summarised away.

That is worth knowing before dispatching something noisy on a platform without
delegation, and it is the only place in this repo where the platform genuinely
changes what happens rather than what it is called.

## Codex notes

Prefer `rg` and `rg --files` for search, `apply_patch` for edits, and
`AGENTS.md` as the repo-level instruction file. Codex reads the same universal
skills through `.agents/skills/*/SKILL.md`.
