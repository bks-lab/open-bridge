---
summary: How this repo's tool names map onto other agent platforms, and what a missing delegation API changes.
type: reference
last_updated: 2026-09-13
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

## Mistral Vibe notes

Vibe reads `AGENTS.md` and discovers the same skills through `.agents/skills`.
Its programmatic mode is `vibe -p "PROMPT"`, not an `exec` subcommand. Role
files in `.claude/agents/` are not Vibe agents: where Vibe cannot delegate, the
role runs inline, as described above.

## The end-of-turn check on every client

On a `user/*` branch, the turn goes back to the agent with the reason when the
working tree holds uncommitted changes to code, docs or configs while
`work/log.md` is neither among them nor touched today, or when a new or changed
task `STATUS.md` claims the task is done while its `status:` says otherwise. An
empty `.bridge-nolog` file in the repo root opts a read-only session out. One
script does the checking, `scripts/worklog-drift-check.sh`, and each client runs
it from a hook declared in this repo. Nothing in `AGENTS.md` asks the agent to
call it; the client does.

| Client | Declared in | Event | A block reaches the agent as |
|---|---|---|---|
| Claude Code | `.claude/settings.json` | `Stop` | exit 2, reason on stderr |
| Codex CLI | `.codex/hooks.json` | `Stop` | exit 2, reason on stderr |
| Mistral Vibe | `.vibe/hooks.toml` | `post_agent` | `{"decision": "deny", "reason": "..."}` on stdout |

Codex and Vibe load project hooks only from a checkout you trust, so each needs
one step per clone:

- **Codex:** trust the project when Codex asks, then review and approve the
  hook in `/hooks`. Codex records that approval against the hook definition,
  so a changed `.codex/hooks.json` asks again.
- **Vibe:** trust the folder when Vibe asks (it remembers the folder in
  `~/.vibe/trusted_folders.toml`) and start Vibe at the repository root. Vibe
  reads `./.vibe/hooks.toml` from the directory it starts in and runs the hook
  command through a shell from there, so the relative script path resolves.
  `vibe -p` never asks for trust; pass `--trust` for a scripted run.

Limits:

- Codex documents no cap on how often a Stop hook may continue a turn, so the
  script lets a turn end once it has already been sent back
  (`stop_hook_active`). One reminder per turn, which is what a nudge is.
- Vibe retries a denied turn at most three times, then shows a warning.
- The script uses `python3` to read the payload's `cwd` and to write Vibe's
  JSON. Without it, both clients fall back to the hook's own directory, and a
  Vibe block shows up as a hook failure instead of a retry. The Codex loop guard
  does not need `python3`.
- Whether Vibe runs `post_agent` hooks under `vibe -p` is not documented.

`bash scripts/tests/test-worklog-drift-check.sh` covers all three clients,
including the declared commands run through a shell from the checkout, the
way Codex and Vibe run them.
