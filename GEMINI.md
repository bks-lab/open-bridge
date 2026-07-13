# The Bridge — Gemini CLI

Gemini CLI looks for a `GEMINI.md` at the project root. This project keeps its
full, tool-agnostic operating manual in **[`AGENTS.md`](AGENTS.md)** — the canonical
and complete reference (no further hops).

**If you are Gemini CLI:** read [`AGENTS.md`](AGENTS.md) and follow it. Skills
are auto-discovered under `.agents/skills/` — a symlink to the top-level
`skills/` folder, so every supported agent loads the same skill set.

**Before your first commit:** run `./bin/setup` — it arms the `pre-push` leak guard (a fresh `git clone` does not) and repairs the skills-discovery symlinks.

**No slash-command / Skill tool?** To onboard, read `skills/bridge-onboard/SKILL.md` → `references/workflow.md` and run the phases inline.
