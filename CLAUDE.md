@AGENTS.md

@ecosystem.yaml

# Claude Code specifics

The canonical, tool-agnostic operating manual for this repo is the **~800-line
[`AGENTS.md`](AGENTS.md)**
(Linux-Foundation convention, read natively by Codex/Cursor/Copilot/Gemini). It is inlined
above via `@AGENTS.md`, so the full manual — session-start gate, rules, task management, agents,
standing orders, commands — is already in your context. This file only adds the
Claude-Code-specific bits.

`@ecosystem.yaml` auto-loads the project registry (created at onboarding, gitignored, so the
import does nothing / is skipped when the file is absent on a fresh clone). Onboarding appends
further `@`-imports here as it seeds
the live USER files (e.g. `identity/agent/SOUL.md` + `IDENTITY.md`).

**Run the Phase-0 session-start gate before responding.** Belt-and-suspenders, so the gate
survives even if the import above fails to resolve:
Do not answer the first user message (even "hi", "status", "what can you do") before running Phase 0.
Phase 0 mechanic, inlined here so it works even if `@AGENTS.md` is silently dropped: detect the
current branch + whether a `user/*` branch exists + whether `bridge-config.yaml` is present, and
route accordingly — on the core branch with no `user/*` and no `bridge-config.yaml`, trigger the
NEW USER path (`/bridge-onboard`); otherwise route to the matching state (wrong-branch, orphan,
broken-config, or normal task-management load).

If `@AGENTS.md` does not resolve in your harness, read `AGENTS.md` manually before responding.
