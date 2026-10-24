@AGENTS.md

# Claude Code specifics

The canonical, tool-agnostic operating manual for this repo is
**[`AGENTS.md`](AGENTS.md)**
(Linux-Foundation convention, read natively by Codex/Cursor/Copilot/Gemini). Its size, and
that of everything else a session loads, is reported by `python3 scripts/measure-context.py`
rather than written down here, where it would go stale. AGENTS.md is inlined
above via `@AGENTS.md`, so the full manual — session-start gate, rules, task management, agents,
standing orders, commands — is already in your context. This file only adds the
Claude-Code-specific bits.

The project registry (`ecosystem.yaml`, created at onboarding, per instance) is no longer
`@`-imported. It is **indexed**: Phase 1 runs
`python3 scripts/context-index.py ecosystem.yaml`, which emits the settings verbatim and one
line per repo, customer and workspace; the entry itself arrives with `--get <name>` when
somebody names one. The registry is the always-on file that grows with the instance rather
than with this repo, and reading it whole meant carrying a paragraph about every project in
order to know that the project exists. Details: [`docs/context-index.md`](docs/context-index.md).

That trade has a real cost worth naming: an `@`-import is resident for the whole session,
while a Phase 1 read is ordinary conversation and can be compacted away later. The card is
small enough to re-run, and `--get` is always available; a file large enough to matter here is
too large to keep resident on that argument alone. Keeping the `@`-import beside a `card:` gets
neither: `measure-context.py` fails it as `contradiction`, since the import loads the file whole.

Onboarding appends further `@`-imports here as it seeds the live USER files
(e.g. `identity/agent/SOUL.md` + `IDENTITY.md`).

**Run the Phase-0 session-start gate before responding.** Belt-and-suspenders, so the gate
survives even if the import above fails to resolve:
Do not answer the first user message (even "hi", "status", "what can you do") before running Phase 0.
Phase 0 mechanic, inlined here so it works even if `@AGENTS.md` is silently dropped: detect the
current branch + whether a `user/*` branch exists + whether `bridge-config.yaml` is present, and
route accordingly — on the core branch with no `user/*` and no `bridge-config.yaml`, trigger the
NEW USER path (`/bridge-onboard`); otherwise route to the matching state (wrong-branch, orphan,
broken-config, or normal task-management load).

If `@AGENTS.md` does not resolve in your harness, read `AGENTS.md` manually before responding.
