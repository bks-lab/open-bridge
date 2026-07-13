# The Bridge — GitHub Copilot

GitHub Copilot reads this `.github/copilot-instructions.md` at session start.
This project keeps its full, tool-agnostic operating manual in
**[`AGENTS.md`](../AGENTS.md)** — the canonical and complete reference (no further
hops). `CLAUDE.md` and `GEMINI.md` are the same kind of thin pointer.

**If you are GitHub Copilot:** read [`AGENTS.md`](../AGENTS.md) and follow it.
Skills are auto-discovered under `.github/skills/` — a symlink to the top-level
`skills/` folder, so every supported agent loads the same skill set.

## Run setup once (fresh clone)

A plain `git clone` does **not** arm the repo's guard rails. Before your first
commit, run **`./bin/setup`** once (Windows: `bin\setup.ps1`). It:

- arms the `pre-push` leak guard via `git config core.hooksPath scripts/hooks`
  (blocks publishing local user data to a public upstream), and
- repairs the skills-discovery symlinks if your checkout materialized them as
  plain files.

## Session-start gate

Before acting on a fresh clone, read [`rules/session-start.md`](../rules/session-start.md)
(Phase 0). It detects branch/config state and, for a new user, opens the
onboarding front door.

Copilot has no Skill tool or slash-commands, so to onboard, read
[`skills/bridge-onboard/SKILL.md`](../skills/bridge-onboard/SKILL.md) →
[`skills/bridge-onboard/references/workflow.md`](../skills/bridge-onboard/references/workflow.md)
and run the phases inline.
