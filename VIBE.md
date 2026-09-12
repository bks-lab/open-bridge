# Open Bridge Vibe

A Vibe CLI edition of Open Bridge: the shared plain-text workspace, skills and
project knowledge, with a Vibe-specific launcher and completion checks.
**No Claude Code or Codex executable, account, plugin or lifecycle hook is required.**

This edition is additive to Open Bridge. Existing Claude and other-client entry
points remain available in the shared source repository; the Vibe runtime does
not invoke them. It is not a claim that one model performs better than another.

## Start

Requirements: Git, Python 3.10 or newer with PyYAML, Bash, and an installed,
authenticated Mistral Vibe CLI (integration tested against version 2.25.0). Supported launcher environments: Linux, macOS and WSL.
Native Windows is not covered by this Bash-based completion check.

From a clean Open Bridge checkout containing this contribution:

```bash
./bin/open-bridge-vibe --check
./bin/open-bridge-vibe
```

The CLI reads `AGENTS.md` and discovers the shared skills through `.agents/skills`.
For a new user it follows Bridge onboarding. For an existing private instance it
loads the existing identity, project registry and task state. Personal onboarding
content stays in the private instance; never push a user branch to this public repo.

Pass Vibe arguments after `--` (workdir, worktree and add-dir overrides are rejected
so the completion check always covers the checkout Vibe used):

```bash
./bin/open-bridge-vibe -- "Show my Bridge status"
./bin/open-bridge-vibe --exec "Read AGENTS.md and give a read-only project briefing" -- --agent plan --max-turns 3
```

The launcher sets up the existing Git push guard, preserves custom hook
installations by refusing to overwrite them, records a worktree checkpoint,
starts only Vibe, and checks logging/status drift when that CLI process exits.
It does not change your model, account, approval policy or trust settings.
Programmatic mode maps the explicit `--exec` prompt to Vibe's `-p` option.
If Vibe requires repository trust, review the checkout and explicitly pass
`--trust`; the launcher never adds it or `--auto-approve`.

## What is Vibe-specific?

- `bin/open-bridge-vibe`: interactive and noninteractive CLI entry point.
- `scripts/vibe-bridge.py`: context loading, knowledge-routing diagnosis and
  per-work-unit checkpoints, including already-dirty worktrees.
- `docs/vibe.md`: explicit skill discovery, delegation, resume and completion
  instructions. Selected role instructions are passed to Vibe subagents; Claude
  role definitions are not assumed to be native Vibe registrations.
- `scripts/worklog-drift-check.sh`: shared, client-independent status checker.
  The older Claude hook is a compatibility wrapper around this same script.

The launcher checks **process exit**, not every assistant message. Per-turn
checks remain agent-invoked through AGENTS.md. If Vibe exits before fixing a
logging finding, the launcher returns nonzero and preserves the checkpoint.
It cannot force the model to resume after exit. Ignored files, other repositories
and external actions still require explicit log entries.

See [the integration guide](docs/vibe.md) for the complete contract and
[contribution guidelines](CONTRIBUTING.md) for development. The shared Open Bridge
license and attribution apply unchanged.
