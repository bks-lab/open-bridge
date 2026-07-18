---
summary: "Bridge-Agents — persistent, addressable agents that front a persona to the outside world over A2A. Runtime (CORE) + instances (USER)."
type: readme
last_updated: 2026-07-18
related:
  - ../docs/representative-agent.md
  - ../identity/agent/README.md
  - _gateway/README.md
---

# agents/ — Bridge-Agents

This directory holds **Bridge-Agents**: persistent, addressable agents that
front one identity to the outside world over the **A2A** protocol (Agent2Agent).
They answer about you, reveal availability, and take in requests — under hard
human gates.

## Sub-Agent vs. Bridge-Agent (disambiguation)

"Agent" means two different things in this repo. Don't confuse them:

| | **Sub-Agent** (`.claude/agents/`) | **Bridge-Agent** (`agents/`) |
|---|---|---|
| Lifetime | ephemeral — one task, returns a summary | persistent, addressable entity |
| Direction | inward (works for you, in your session) | outward (fronts you to the world) / peer |
| Identity | a function with tools | body = repo, self = IDENTITY/SOUL, interface = AgentCard |
| Transport | Task tool / SendMessage / cmux pane | A2A (JSON-RPC + SSE), optionally signal/email |
| Defined by | a markdown file + frontmatter | a runnable instance under `agents/<name>/` |

A Bridge-Agent has **two faces**: an *outer* face (the world / foreign agents /
public visitors — the **representative agent**, see
[`docs/representative-agent.md`](../docs/representative-agent.md)) and an *inner*
face (your own fleet / peer bridges — the **mesh**). Same machinery, one self,
two directions.

## Layout

```
agents/
  _runtime/        CORE — the generic engine (claude -p + A2A server)
    runner.py        subprocess runner (one claude -p per turn)
    executor.py      A2A executor (concurrency cap · LRU memory · cancel · artifacts)
    card.py          build an AgentCard from the instance config
    config.py        load agents/<name>/ into one resolved AgentConfig
    server.py        Starlette app + entrypoint (build_app / main)
  _template/       CORE — copy to start a new instance
    tools/           CORE reference: intake_notify.py (fixed-recipient scaffold)
  _gateway/        CORE — thin, stateless MCP→A2A gateway (list_bridges, get_bridge_card, ask_bridge)
  tests/           CORE — hermetic runner regression net (test_runner.py, test_intake_notify.py)
  pyproject.toml   CORE — runtime deps (a2a-sdk, uvicorn, starlette, click, pyyaml)
  <name>/          USER — one instance per agent
    agent.yaml       declarative config (card spec + runtime knobs)
    system-prompt.md the persona (appended system prompt)
    tools/           instance-specific scoped tools (argparse CLIs)
```

**Scope:** `_runtime/`, `_template/`, `_gateway/`, `tests/`, `pyproject.toml`, this
README = **CORE** (ship to open-bridge). Each `agents/<name>/` instance = **USER**
(your persona / PII — stays local). The runtime never contains
organization-specific content. `_gateway/` details: [`agents/_gateway/README.md`](_gateway/README.md).

## Create an instance

```bash
cp -r agents/_template agents/<name>
# edit agents/<name>/agent.yaml  (name, public_url, grounding_dir, skills, tools)
# edit agents/<name>/system-prompt.md  (the persona + disclosure boundary)
cd agents && uv run python -m _runtime.server --agent <name> --port 8011
```

Then probe it:

```bash
curl -s localhost:8011/.well-known/agent-card.json | head
curl -s localhost:8011/health
```

## Safety model (why a public endpoint is safe)

- **cwd = grounding_dir** — Read/Glob/Grep are confined to *public* content; the
  agent can never read the bridge's private files. Instance tools run by absolute
  path (`${tools_dir}` substituted at load).
- **Scoped `allowed_tools`** — read-only plus only the intended tools; no generic
  shell, no write, no arbitrary send.
- **Fixed-recipient intake** — an intake tool captures requests for *you* alone
  (fixed recipient from `AGENT_NOTIFY_TO` env only, no recipient argument),
  durable-first, notify best-effort and never-raises, PII-free audit. CORE ships
  the stdlib-only scaffold `_template/tools/intake_notify.py` (override its `send()`
  seam with your transport); a testable contract locks it (`tests/test_intake_notify.py`).
- **No autonomous outward action** — bookings/replies go through your gate.
- **Public-endpoint caps** — concurrency, input length; add a per-IP edge
  rate-limit at your CDN.
- **Honest card** — advertise only capabilities that are real.
- **Read-only-shell denylist (backstop)** — `acceptEdits` auto-allows shell the
  engine classifies as read-only *independent of* `allowed_tools`, so the runtime
  also denies the known file-read/exfil/recon binaries. It is a backstop, never the
  control — the real read-confinement is the cwd above plus an OS sandbox.
- **Project-only settings** — the runtime loads `--setting-sources project`, never
  the host user's `~/.claude` allowlist/hooks, so a host preference can't silently
  widen this internet-facing agent.
- **Large stream buffer** — when consuming `--output-format stream-json`, the
  runtime raises the subprocess line limit (a single `Read` tool_result can embed a
  whole file on one NDJSON line and overrun the default 64 KiB → a textless failed
  turn).
- **OS sandbox is the named real fix** — confine reads to the grounding dir and
  block network/keychain with the mechanism the host supports (container-as-`nobody`
  on Linux; a `sandbox-exec` profile or dedicated low-priv user on macOS, which keeps
  the keychain/calendar the agent legitimately needs).

## Latency & the answer contract

The runtime upholds one hard contract on every turn: **exactly one non-empty
answer, delivered within `timeout` — never a hang, never a blank bubble.** A public
visitor must never watch "…working" forever or get an empty reply. The runner holds
that line three ways: it raises the subprocess line buffer (a `Read` of a large
grounding file lands as one huge NDJSON line that would overrun the default 64 KiB),
it enforces an overall deadline even when the subprocess streams continuously, and it
falls back to the accumulated assistant text (or a plain message) when no terminal
result arrives. Two production incidents bought this contract; it is now locked by a
hermetic regression net — [`tests/test_runner.py`](tests/test_runner.py), stubbed (no
real `claude`, no network) and run in CI ([`.github/workflows/agents-tests.yml`](../.github/workflows/agents-tests.yml))
on any `agents/**` change. **Don't weaken those paths without keeping the tests green.**

**Latency is a knob to tune, not a bug to fix.** A broad question that makes the
model `Read` the whole grounding and reason a full answer takes ~60–90 s with
`sonnet`. That is fine over a tunnel: SSE keepalive pings hold the connection open
across the silent reasoning gap, and on expiry `timeout` returns a text "try again"
message (never a blank). So give `timeout` generous headroom — the tunnel won't drop
a long stream. The real levers to make it *fast*: keep the grounding small, or inject
the public content straight into `system-prompt.md` instead of a per-turn `Read` (both
remove a tool round-trip and the big-line cost); a faster model trades some depth for
latency on pure Q&A.

## Deploy

Host the runtime on a remote (launchd/systemd), behind a tunnel that maps the
`public_url` hostname to the local port. Track the deploy as an
`infra/channels/<name>.yaml` entry + the remote's service list — the declared
`status:` is never trusted, the service manager is
([`rules/deploy-reconciliation.md`](../rules/deploy-reconciliation.md)).

Full guide: [`docs/representative-agent.md`](../docs/representative-agent.md).
