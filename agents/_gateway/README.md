---
summary: "Thin, stateless MCP→A2A gateway: MCP clients (Claude, ChatGPT Dev Mode, Gemini) talk to bridge A2A agents through three tools, with a tiered-access model where anonymous is standard and a bearer token unlocks more."
type: readme
last_updated: 2026-07-18
related:
  - SPEC.md
  - ../README.md
  - https://github.com/bks-lab/open-bridge/issues/124
---

# agents/_gateway — MCP→A2A Gateway

The counterpart to [`agents/_runtime/`](../README.md): the runtime makes a bridge
addressable over **A2A**; this gateway makes those A2A agents reachable from the
**MCP**-only frontends people actually use (Claude connectors, ChatGPT developer
mode, Gemini, any MCP client). Pure translation layer — no model, no reasoning,
no persistent state. Discovery issue:
[#124](https://github.com/bks-lab/open-bridge/issues/124).

```
MCP client ──Streamable HTTP──▶ gateway ──A2A JSON-RPC──▶ bridge agent(s)
            [optional Bearer]           [v1.0 wire, v0.3 fallback]
```

Three tools, one registry:

| Tool | Does |
|------|------|
| `list_bridges` | Registry entries visible at the caller's access tier |
| `get_bridge_card(bridge)` | Fetch + normalize the AgentCard (reads both card dialects) |
| `ask_bridge(bridge, message, conversation?)` | One A2A ask; `conversation` continues a thread |

## Tiered access — anonymous is standard, a token unlocks more

Every request resolves to an access tier through **one** resolver
(`gateway/tiers.py`), which is also the seam where OAuth 2.1 plugs in later:

- **Anonymous** (no `Authorization` header): sees and asks only bridges with
  `min_tier: anonymous`; cards come as normalized summaries.
- **Authenticated** (`Authorization: Bearer <token>`, token from the list in the
  env var named by `tokens_env`): sees all bridges, may ask
  `min_tier: authenticated` bridges, and `get_bridge_card` additionally returns
  the full raw card (`extended: true`).
- An *invalid* header is a hard `unauthorized` error — never a silent downgrade.

The client's token is never forwarded upstream (two independent auth hops):
bridges that require credentials declare `auth_mode: token` +
`credential_ref: <ENV_VAR_NAME>` in the registry, and the gateway resolves that
env var per ask.

## Quickstart

```bash
cd agents/_gateway
cp registry.example.yaml registry.yaml     # add your bridges' card URLs
export GATEWAY_AUTH_TOKENS="some-random-token"   # optional: enables the elevated tier
uv run python -m gateway --registry registry.yaml --port 8900
```

Then point any MCP client at `http://127.0.0.1:8900/mcp` (Streamable HTTP), e.g.:

```bash
claude mcp add --transport http bridge-gateway http://127.0.0.1:8900/mcp
```

Config resolution is defaults ← YAML (`--config gateway.yaml`) ← `GATEWAY_*`
env vars (env wins; CLI flags beat both). All keys and defaults are documented
in [`gateway.example.yaml`](gateway.example.yaml) and SPEC §3.

## Behind a tunnel — the 421 trap

The MCP SDK auto-enables DNS-rebinding protection when the gateway binds a
loopback host: a public tunnel hostname in the `Host` header is answered with
HTTP 421. Set the allowlist when deploying behind a tunnel:

```bash
export GATEWAY_ALLOWED_HOSTS="gateway.example.com,127.0.0.1:8900,localhost:8900"
```

Protection stays ON — the listed hosts **replace** the SDK's localhost-only
auto-allowlist. That replacement cuts both ways: list your loopback
`host:port` too, or local health probes against the running service start
421ing the moment you configure the tunnel hostname (found live on first
deploy).

## Robustness contract

- Per-bridge concurrency gate (default 2, matching the runtime's own cap):
  an over-limit ask fails fast with a typed `busy` error carrying
  `retry_after_s` — never an invisible queue that burns the client's timeout.
- `ask_timeout_s` (default 55 s) must stay below your MCP client's tool-call
  timeout; agent turns of 60–90 s are normal for broad questions, so raise both
  sides together when needed.
- Every tool returns a typed envelope (`ok` / `error.code` from a stable
  taxonomy: `unknown_bridge`, `tier_denied`, `unauthorized`, `busy`, `timeout`,
  `unreachable`, `upstream_error`) — machine-checkable, never a raised
  exception, never an empty reply.
- Card reads handle **both** AgentCard dialects (v1 `supportedInterfaces[]` and
  legacy top-level fields) and both wire dialects (v1 `SendMessage` with the
  `A2A-Version: 1.0` header; v0.3 `message/send` fallback) — the dialect is
  chosen per card, per the lesson from #121.

## Tests

Hermetic TDD suite (in-process fake A2A server, real MCP client over an ASGI
transport, no network, no ports):

```bash
cd agents/_gateway
uv run --with pytest --with pytest-asyncio --with starlette pytest
```

CI runs this as the `gateway-pytest` job in
[`agents-tests.yml`](../../.github/workflows/agents-tests.yml). The full
requirements, pinned interfaces, and wire reference live in [SPEC.md](SPEC.md).

## Security posture

The gateway adds reach, not privilege: it is a client like any other in front
of the target agent and bypasses none of the agent's own guardrails
(grounding confinement, scoped tools, human-gated intake — see
[`agents/README.md`](../README.md)). Still, an open gateway in front of open
agents widens exposure — put an edge rate-limit in front of a public
deployment, keep `min_tier: authenticated` on anything you don't want
anonymous traffic to reach, and prefer per-bridge upstream credentials over
open agents where the content warrants it.

## Deploy

Host the gateway on a remote (launchd/systemd), behind a tunnel that maps a
public hostname to the local port — then set `allowed_hosts` (§ Behind a
tunnel above) or every request 421s. A generic systemd unit:

```ini
[Unit]
Description=bridge-gateway (MCP->A2A)

[Service]
WorkingDirectory=/path/to/agents/_gateway
ExecStart=/path/to/uv run python -m gateway --registry registry.yaml --port 8900
Environment=GATEWAY_AUTH_TOKENS=<token>
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

or the launchd equivalent (`ProgramArguments` running the same `uv run`
command, `KeepAlive` true). `registry.yaml` and an optional `gateway.yaml`
live next to the unit's `WorkingDirectory` — keep both out of git (they may
carry internal `card_url`s) alongside the `.env`-style file backing
`GATEWAY_AUTH_TOKENS` and any `credential_ref` targets.

The gateway is stateless MCP-only — there is no separate `/health` endpoint
(one path, `/mcp`, per TRN-1). Probe liveness with a minimal JSON-RPC
`initialize` call instead:

```bash
curl -s http://127.0.0.1:8900/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize",
       "params":{"protocolVersion":"2025-06-18","capabilities":{},
                 "clientInfo":{"name":"probe","version":"0"}}}'
```

A `200` with a `serverInfo` payload means the process is up; a bare `curl -o
/dev/null -w '%{http_code}'` GET against `/mcp` also distinguishes "listening
but rejects a malformed request" (`406`) from "port is down" (connection
refused) when a full JSON-RPC probe is overkill.

Track the deploy as an `infra/channels/<name>.yaml` entry (`type: bridge` or
`api`, per that schema) + the remote's service list — the declared `status:`
is never trusted, the service manager is
([`rules/deploy-reconciliation.md`](../../rules/deploy-reconciliation.md)).
