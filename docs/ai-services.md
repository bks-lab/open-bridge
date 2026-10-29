---
summary: "Configure which local AI CLI handles each Bridge service, keep Claude as the compatibility default, and run a selected provider from worker scripts."
type: reference
last_updated: 2026-10-29
related:
  - ../scripts/lib/ai_services.py
  - ../scripts/ai-run.py
  - bridge-cockpit.md
  - ../rules/core-fix-workflow.md
---

# AI service routing

Bridge services can select a local AI CLI independently. The shared adapter is
`scripts/lib/ai_services.py`; per-instance choices live in
`workflow/ai-services/<service>.yaml`. The config template and schema define the
supported fields. Claude remains the default when no service entry exists, so
existing Claude-backed flows continue to work.

## The services and their providers

`SERVICES` in `scripts/lib/ai_services.py` is the one list of the service IDs
the code selects and the providers each one's code can run. The table below is
its output (`python3 scripts/ai-run.py --list`, `--json` for machines); a test
fails when the code selects an ID missing from `SERVICES`, or when this table
differs from it. A worker's own ID (`ai-run.py --service <id>`) runs on every
provider and is not listed.

<!-- ai-services:begin -->
| Service | Providers | Code |
|---|---|---|
| `briefing-chat` | claude, codex | `scripts/lib/bridge_cockpit/quick.py` |
| `task-review` | claude, codex | `scripts/task.py` |
| `triage` | claude, codex | `scripts/triage.py` |
| `cockpit-activity` | claude | `scripts/lib/bridge_cockpit/activity.py` |
| `cockpit-describe` | claude | `scripts/lib/bridge_cockpit/describe.py` |
| `cockpit-files` | claude | `scripts/lib/bridge_cockpit/actions_work.py` |
| `cockpit-instruct` | claude | `scripts/lib/bridge_cockpit/instruct.py` |
| `cockpit-organize` | claude | `scripts/lib/bridge_cockpit/organize.py` |
| `cockpit-prio` | claude | `scripts/lib/bridge_cockpit/prio.py` |
| `cockpit-themes` | claude | `scripts/lib/bridge_cockpit/themes.py` |
<!-- ai-services:end -->

The
briefing chat also lets a user choose Claude or Codex for a conversation. That
choice applies to the current and subsequent turns; switching providers carries
the completed conversation as prompt context and starts a fresh provider
session. A failed switch leaves the original conversation intact. Choosing
“Use service default” clears the per-chat override.

Worker scripts can use the same routing layer:

```sh
python3 scripts/ai-run.py --service triage --show
python3 scripts/ai-run.py --service triage --json "Classify this item"
```

Use `--provider codex` to override one invocation. The adapter does not silently
fall back to another provider. Codex chat runs in a read-only sandbox; the
worker wrapper also disables its shell tool. Reported cost is unknown when the
CLI does not provide a reliable amount.

## A service your provider cannot run

A service file may name a provider the service's code cannot run yet, such as
`provider: codex` for `cockpit-prio`. The service then stays off, and says so:
`ai_services.gaps()` returns `{service, ready: false, reason:
"provider_unsupported", provider, supported}` for it, `python3
scripts/bridge-cockpit.py status --json` lists it under `provider_gaps`, Prio's
state carries the reason, and Settings, Setup in the cockpit shows one row per
gap. A model pinned in a cockpit block (`cockpit.flow.<name>.model`) runs on
Claude whatever the service file says.

The gap is closed in code, by the agent of the instance that has it:

1. Adapt the service through `scripts/lib/ai_services.py`, with the briefing
   chat (`scripts/lib/bridge_cockpit/quick.py`) as the pattern: the argv comes
   from `ai.codex_argv` (or `ai.batch_argv` for a text-only call), Codex runs in
   its read-only sandbox, the answer is read with `ai.parse_codex`, and there is
   no silent fallback to another provider. Then add the provider to the
   service's entry in `SERVICES` and refresh the table above.
2. Test it: the service's own tests with a Codex answer stubbed, and the whole
   suite.
3. Propose it upstream as a fork PR, per
   [`rules/core-fix-workflow.md`](../rules/core-fix-workflow.md) Path A, so the
   local change reconverges on the next merge.
