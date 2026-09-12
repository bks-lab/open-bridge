# Open Bridge Codex

A Codex CLI edition of Open Bridge: the shared plain-text workspace, skills and
project knowledge, with a Codex-specific launcher and completion checks.
**No Claude executable, account, plugin or lifecycle hook is required.**

This edition is additive to Open Bridge. Existing Claude and other-client entry
points remain available in the shared source repository; the Codex runtime does
not invoke them. It is not a claim that one model performs better than another.

## Start

Requirements: Git, Python 3.10 or newer with PyYAML, Bash, and an installed,
authenticated Codex CLI. Supported launcher environments: Linux, macOS and WSL.
Native Windows is not covered by this Bash-based completion check.

From a clean Open Bridge checkout containing this contribution:

```bash
./bin/open-bridge-codex --check
./bin/open-bridge-codex
```

The CLI reads `AGENTS.md` and discovers the shared skills through `.agents/skills`.
For a new user it follows Bridge onboarding. For an existing private instance it
loads the existing identity, project registry and task state. Personal onboarding
content stays in the private instance; never push a user branch to this public repo.

Pass Codex arguments after `--` (cwd, worktree and remote overrides are rejected
so the completion check always covers the checkout Codex used):

```bash
./bin/open-bridge-codex -- "Show my Bridge status"
./bin/open-bridge-codex --exec -- "Read AGENTS.md and give a read-only project briefing"
```

The launcher sets up the existing Git push guard, preserves custom hook
installations by refusing to overwrite them, records a worktree checkpoint,
starts only Codex, and checks logging/status drift when that CLI process exits.
It does not change your model, account, approval policy or sandbox settings.

## What is Codex-specific?

- `bin/open-bridge-codex`: interactive and noninteractive CLI entry point.
- `scripts/codex-bridge.py`: client entry to the shared `scripts/lib/cli_bridge.py`
  context and checkpoint engine, including already-dirty worktrees.
- `scripts/lib/cli_launcher.py`: shared CLI process management and output routing.
- `docs/codex.md`: explicit skill discovery, delegation, resume and completion
  instructions. Selected role instructions are passed to Codex subagents; Claude
  role definitions are not assumed to be native Codex registrations.
- `scripts/worklog-drift-check.sh`: shared, client-independent status checker.
  The older Claude hook is a compatibility wrapper around this same script.

The launcher checks **process exit**, not every assistant message. Per-turn
checks remain agent-invoked through AGENTS.md. If Codex exits before fixing a
logging finding, the launcher returns nonzero and preserves the checkpoint.
It cannot force the model to resume after exit. Ignored files, other repositories
and external actions still require explicit log entries.

See [the integration guide](docs/codex.md) for the complete contract and
[contribution guidelines](CONTRIBUTING.md) for development. The shared Open Bridge
license and attribution apply unchanged.

## Automation contracts

CLI stdout remains the CLI's output, including JSON/JSONL modes. Bridge diagnostics
and completion results go to stderr, so machine consumers can parse stdout.
A removed, empty or non-regular work log does not satisfy required logging.
Completion failures retain the checkpoint and return nonzero.

The Codex and Vibe editions use the same shared engine. Installing or authenticating
another coding client is unnecessary; each launcher selects only its own executable.
