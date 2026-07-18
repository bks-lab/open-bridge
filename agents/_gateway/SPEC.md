---
summary: "Build spec for agents/_gateway — a thin, stateless MCP→A2A gateway (Streamable HTTP) that lets MCP clients (Claude, ChatGPT Dev Mode, Gemini) talk to bridge A2A agents. Pinned interfaces for parallel module builds, EARS requirements, hermetic TDD test plan, live verification plan."
type: spec
last_updated: 2026-07-18
related:
  - https://github.com/bks-lab/open-bridge/issues/124
  - agents/README.md
  - agents/_runtime/
---

# agents/_gateway — MCP→A2A Gateway SPEC

Discovery issue: [bks-lab/open-bridge#124](https://github.com/bks-lab/open-bridge/issues/124).
Counterpart to the `agents/_runtime/` A2A agent (#47): the runtime makes a bridge
addressable over A2A; this gateway makes those A2A agents reachable from the MCP-only
frontends people actually use. Pure translation layer — no model, no reasoning inside.

All wire/SDK claims in this spec were verified against live sources on 2026-07-18:
the A2A v1.0.1 specification text (raw `specification.md`), the `a2a-python` repo,
a hands-on `mcp==1.28.1` install (server + client exercised end-to-end), and the
`agents/_runtime` code on this branch. Where older prose and verified behavior
diverged, this spec pins the **verified behavior** and notes the divergence inline.

---

## 1. Goal & Non-Goals

### Goal

A self-contained CORE component `agents/_gateway/` — an MCP server (Streamable HTTP,
stateless, one port, `/mcp` endpoint) exposing exactly three tools:

| Tool | Purpose |
|------|---------|
| `list_bridges` | Bridges from a static YAML registry, filtered by the caller's access tier |
| `get_bridge_card(bridge)` | Fetch + normalize the AgentCard (reads BOTH card dialects) |
| `ask_bridge(bridge, message, conversation?)` | A2A `SendMessage` on the native v1.0 wire with v0.3 fallback; `conversation` maps to the A2A `contextId` |

Every tool resolves its answer through ONE central access-tier resolver
(anonymous = standard, bearer token = elevated). The resolver is the later
OAuth 2.1 seam — plugging in OAuth changes the resolver, never the tools.

### Non-Goals (MVP)

- Dynamic per-skill MCP tool fanout from AgentCard skills (survey in #124: nobody does
  this; a generic free-text ask tool is the recurring pattern).
- Full OAuth 2.1/PKCE flow (phase 2 — the tier resolver is the seam).
- SSE / MCP progress streaming (phase 2; MVP returns one buffered answer).
- Calling `GetExtendedAgentCard` upstream ("extended" in the MVP means *more of the
  public card*, not the authenticated-extended-card A2A call; see § 4 CARD-6).
- Token pass-through client→gateway→agent (confused-deputy; RFC 8707). Two independent
  auth hops, always.
- Imports from `agents/_runtime` (self-contained; a later repo split stays cheap).
- Persistent state of any kind (no DB, no session store; see § 5 conversation design).

---

## 2. Architecture

```
MCP client (Claude / ChatGPT Dev Mode / Gemini)
   │  Streamable HTTP  POST /mcp   [Authorization: Bearer <gateway token>]  (optional)
   ▼
FastMCP server (stateless_http=True, json_response=True)         server.py
   │  header → AccessTier                                        tiers.py
   │  bridge id → BridgeEntry                                    registry.py
   │  per-bridge concurrency gate                                server.py (BridgeGate)
   ▼
A2A client — dual dialect                                        a2a_client.py
   │  GET  <card_url>                    (both card dialects)
   │  POST <jsonrpc_url>  SendMessage    (v1.0 wire, A2A-Version: 1.0)
   │  POST <jsonrpc_url>  message/send   (v0.3 fallback wire)
   ▼
Bridge A2A agent (agents/_runtime or any A2A endpoint)
```

Modules (each independently buildable against § 5 pinned interfaces):

| File | Purpose |
|------|---------|
| `gateway/errors.py` | Typed error taxonomy + `ErrorInfo` payload shape |
| `gateway/registry.py` | YAML bridge registry: `BridgeEntry`, `load_registry`, credential env-indirection |
| `gateway/tiers.py` | `AccessTier`, `TierResolver` — the single auth/visibility decision point |
| `gateway/a2a_client.py` | Card fetch/normalize (dual dialect) + `send_message` (dual wire) |
| `gateway/config.py` | `GatewayConfig`: defaults ← YAML ← ENV |
| `gateway/server.py` | `GatewayService` (tool logic), `build_server` (FastMCP wiring), `main` |

### Decision log (fixed — do not re-litigate during build)

1. **No `a2a-sdk` dependency.** The gateway must speak two wire dialects; the SDK is
   v1-native (proto-first since 1.0.0, 2026-04-20) and its client would fight the v0.3
   fallback. Raw `httpx` JSON-RPC, wire shapes pinned in § 6.
2. **Stateless conversation mapping.** `conversation` IS the upstream A2A `contextId`,
   passed through verbatim (opaque to the MCP client, per spec §3.4.1 "SHOULD be
   treated as opaque"). No gateway-side table, survives restarts, zero memory growth.
3. **Errors are returned, not raised, at the tool boundary.** Verified: FastMCP wraps
   raised exceptions in a prefixed plain-text `isError` result — not machine-parseable —
   and only *typed* return annotations produce `outputSchema`/`structuredContent`
   (an untyped `dict` return does NOT). Therefore every tool returns one concrete
   TypedDict with an `ok`/`error` envelope. Internal code raises `GatewayError`
   subclasses; `server.py` converts at the boundary.
4. **Invalid bearer token → `unauthorized` error, never silent anonymous downgrade.**
   A typo'd token must be visible, and OAuth later needs the same hard failure.
5. **Header access via `ctx.request_context.request`.** Verified on `mcp==1.28.1`:
   `get_http_request()` does NOT exist in this version; the working path is a
   `Context`-annotated tool parameter and the raw Starlette request on its
   `request_context`.
6. **Card TTL cache (default 300 s) inside `a2a_client.fetch_card` callers** — a pure
   in-process cache in `server.py`, not persistent state. `card_cache_ttl_s: 0` disables.
7. **The gateway's client-facing bearer tokens and the per-bridge upstream credentials
   are disjoint universes.** The client's `Authorization` header is never forwarded
   upstream; upstream credentials come only from `credential_ref` env indirection.

---

## 3. Registry & Config Data Model

`registry.yaml` (path from config; `registry.example.yaml` ships in this directory):

```yaml
bridges:
  - id: example                # unique slug, ^[a-z0-9][a-z0-9-]*$
    card_url: "https://<bridge-host>/.well-known/agent-card.json"
    description: "One line shown to MCP clients in list_bridges."
    auth_mode: open            # open | token
    # credential_ref: EXAMPLE_BRIDGE_TOKEN   # ENV VAR NAME — never a secret value
    min_tier: anonymous        # anonymous | authenticated
```

Gateway config resolution order: built-in defaults ← optional YAML (`--config`) ← ENV.
ENV always wins. Keys and defaults:

| Config key (YAML) | ENV override | Default | Meaning |
|---|---|---|---|
| `registry` | `GATEWAY_REGISTRY` | `registry.yaml` | Path to bridge registry |
| `host` | `GATEWAY_HOST` | `127.0.0.1` | Bind host |
| `port` | `GATEWAY_PORT` | `8900` | Bind port |
| `ask_timeout_s` | `GATEWAY_ASK_TIMEOUT_S` | `55.0` | Budget per upstream send; MUST stay below the MCP client's tool-call/turn timeout (typically 60 s) |
| `card_timeout_s` | `GATEWAY_CARD_TIMEOUT_S` | `10.0` | Budget per card fetch |
| `card_cache_ttl_s` | `GATEWAY_CARD_CACHE_TTL_S` | `300.0` | In-process card cache TTL; `0` disables |
| `per_bridge_concurrency` | `GATEWAY_PER_BRIDGE_CONCURRENCY` | `2` | Concurrent `ask_bridge` calls per bridge |
| `busy_retry_after_s` | `GATEWAY_BUSY_RETRY_AFTER_S` | `10.0` | Retry hint carried by `busy` errors |
| `tokens_env` | `GATEWAY_TOKENS_ENV` | `GATEWAY_AUTH_TOKENS` | NAME of the env var holding the comma-separated client bearer-token list |
| `allowed_hosts` | `GATEWAY_ALLOWED_HOSTS` (comma-separated; YAML: list) | *(empty)* | Host-header allowlist for the SDK's DNS-rebinding protection. Empty keeps the SDK default (localhost-only auto-allowlist when binding a localhost host). Set to the public hostname(s) — exact `host[:port]` values or `host:*` port wildcards — when serving behind a tunnel; see the § 7 footnote on the 421 trap |

---

## 4. Requirements (EARS)

### Registry (REG)

- **REG-1** When `load_registry` is called with a well-formed YAML file, the gateway
  shall produce one `BridgeEntry` per `bridges[]` item, applying defaults
  `auth_mode=open`, `min_tier=anonymous`.
- **REG-2** When the registry contains a duplicate `id`, an id not matching
  `^[a-z0-9][a-z0-9-]*$`, an unknown `auth_mode`/`min_tier` value, or a missing
  `card_url`/`description`, `load_registry` shall raise `RegistryError` naming the
  offending entry.
- **REG-3** When an entry has `auth_mode: token`, it shall require `credential_ref`,
  and `credential_ref` shall match `^[A-Z][A-Z0-9_]*$` (an ENV VAR NAME — a value that
  looks like a literal secret is a schema violation).
- **REG-4** When `resolve_credential` is called for a `token` entry whose env var is
  unset or empty, the gateway shall raise `UnauthorizedError` naming the missing env
  var (never logging a token value).
- **REG-5** When `Registry.get` is called with an unknown bridge id, it shall raise
  `UnknownBridgeError`.

### Tiers & client auth (TIER)

- **TIER-1** When a request carries no `Authorization` header, the resolver shall
  assign `AccessTier.ANONYMOUS`.
- **TIER-2** When a request carries `Authorization: Bearer <t>` and `<t>` is in the
  configured token list (comma-separated value of the env var named by `tokens_env`,
  entries trimmed, empties ignored), the resolver shall assign
  `AccessTier.AUTHENTICATED`.
- **TIER-3** When a request carries an `Authorization` header that is malformed, uses
  a non-Bearer scheme, or carries a token not in the list (including when the list is
  empty/unset), the resolver shall raise `UnauthorizedError` — never silently
  downgrade to anonymous.
- **TIER-4** While a caller is `ANONYMOUS`, `list_bridges` shall include only entries
  with `min_tier: anonymous`; while `AUTHENTICATED`, it shall include all entries.
- **TIER-5** When `get_bridge_card` or `ask_bridge` targets an entry whose `min_tier`
  exceeds the caller's tier, the gateway shall return a `tier_denied` error and shall
  not contact the upstream bridge.
- **TIER-6** All tier decisions (visibility, ask permission, extended card detail)
  shall flow through `TierResolver` exclusively — no tier logic in tool bodies.
  This resolver is the OAuth 2.1 seam; its public surface must not leak "static
  token list" assumptions.
- **TIER-7** The gateway shall never forward the client's `Authorization` header
  upstream.

### Card reading (CARD)

- **CARD-1** When fetching a card, the gateway shall GET the registry `card_url`
  (conventionally `…/.well-known/agent-card.json`) with `Accept: application/json`,
  adding `Authorization: Bearer <resolved credential>` iff `auth_mode: token`.
- **CARD-2 (dual dialect — the #121 lesson)** When the card contains a non-empty
  `supportedInterfaces[]`, the reader shall select the first entry with
  `protocolBinding == "JSONRPC"` and take `url` + `protocolVersion` from that entry
  (per-entry version: an interface entry may declare `0.3` inside a v1-shaped card).
  When `supportedInterfaces` is absent, the reader shall fall back to the top-level
  v0.3 fields: `url`, optional `preferredTransport` (must be absent or `"JSONRPC"`),
  optional top-level `protocolVersion`.
- **CARD-3** The wire dialect shall derive from the selected `protocolVersion`:
  prefix `1` → `v1`; prefix `0` or **missing** → `v0_3` (a card without any protocol
  version is treated as fully 0.3 — verified against a2a-sdk card behavior).
- **CARD-4** When no JSONRPC interface can be selected (e.g. GRPC-only card, missing
  url), the reader shall raise `UpstreamError` describing the card defect.
- **CARD-5** When the card endpoint is unreachable / times out / returns non-2xx /
  returns non-JSON, the reader shall raise `BridgeUnreachableError` /
  `BridgeTimeoutError` / `BridgeUnreachableError` (with HTTP status; 401/403 →
  `UnauthorizedError`) / `UpstreamError` respectively.
- **CARD-6** While the caller is `ANONYMOUS`, `get_bridge_card` shall return the
  normalized summary only (`extended=false`, `card=null`); while `AUTHENTICATED`, it
  shall additionally return the full raw card JSON (`extended=true`). The MVP shall
  not call `GetExtendedAgentCard` upstream (that call is only legal when
  `capabilities.extendedAgentCard` is true — v1.0 moved this flag under
  `capabilities`; record for phase 2).

### Wire (WIRE) — exact JSON in § 6

- **WIRE-1** While dialect is `v1`, the client shall POST JSON-RPC with method
  `SendMessage` (PascalCase), header `A2A-Version: 1.0`, and params =
  `SendMessageRequest` = `{"message": {...}}` where the message carries
  `role: "ROLE_USER"` and `parts: [{"text": ...}]` — **no** `"kind"` discriminator.
  (A missing `A2A-Version` header makes a v1 server assume 0.3 semantics — spec
  §3.6.2 — so the header is mandatory on every v1 request.)
- **WIRE-2** While dialect is `v0_3`, the client shall POST JSON-RPC with method
  `message/send`, **no** `A2A-Version` header, `role: "user"`, and
  `parts: [{"kind": "text", "text": ...}]`.
- **WIRE-3** When a v1 response `result` contains `"message"`, the reply text shall be
  the concatenation of its `parts[].text` and the context shall be its `contextId`.
  When it contains `"task"`, the context shall be `task.contextId` and the text shall
  be resolved by state: `TASK_STATE_COMPLETED` → join of `artifacts[].parts[].text`
  (fallback `status.message.parts[].text`); `TASK_STATE_INPUT_REQUIRED` /
  `TASK_STATE_AUTH_REQUIRED` → `status.message.parts[].text` (the conversation
  continues under the same `conversation`); `TASK_STATE_FAILED` / `_CANCELED` /
  `_REJECTED` → `UpstreamError` carrying the state and any status message.
  (The task branch is not theoretical: `agents/_runtime` delivers its answer as a
  completed-Task **artifact** — verified in `_runtime/executor.py`.)
- **WIRE-4** When the dialect is `v0_3`, the same extraction shall apply to the
  kind-discriminated result (`"kind": "message"` / `"kind": "task"`, lower-case states
  such as `completed`, `input-required`, parts with `"kind": "text"`).
- **WIRE-5** When the JSON-RPC envelope contains an `error` object, or `result`
  matches neither shape, the client shall raise `UpstreamError` including the JSON-RPC
  error code/message when present.
- **WIRE-6** Every outgoing message shall carry a fresh `messageId` (uuid4 string).

### Conversation (CONV)

- **CONV-1** When `ask_bridge` is called without `conversation`, the gateway shall
  send no `contextId`; the upstream-generated `contextId` (spec §3.4.1: MUST be in
  the response if generated) shall be returned as `conversation`.
- **CONV-2** When `ask_bridge` is called with `conversation`, the gateway shall send
  it verbatim as `contextId`, and shall return the response's `contextId` (falling
  back to the sent value when the response omits it).
- **CONV-3** The gateway shall keep no conversation state (registry of § 2 decision 2).

### Errors (ERR)

- **ERR-1** The error taxonomy shall be exactly: `unknown_bridge`, `tier_denied`,
  `unauthorized`, `busy`, `timeout`, `unreachable`, `upstream_error` — stable string
  codes, machine-checkable. (`upstream_error` extends the six mandated codes to cover
  malformed cards/wire and failed tasks.)
- **ERR-2** Every tool shall return its result TypedDict with `ok: true` and
  `error: null` on success, or `ok: false` and a populated `ErrorInfo` on failure —
  never a raised exception across the MCP boundary, never a silent empty result.
- **ERR-3** When concurrency is exhausted (CONC-1), the `busy` error shall carry
  `retry_after_s` (config `busy_retry_after_s`); all other codes shall carry
  `retry_after_s: null`.
- **ERR-4** Error messages shall never contain credential values.

### Concurrency (CONC)

- **CONC-1** While `per_bridge_concurrency` asks are in flight for a bridge, a further
  `ask_bridge` for that bridge shall fail fast with `busy` (no queueing, no waiting).
- **CONC-2** Concurrency accounting shall be per bridge id, in-process
  (`BridgeGate` counter; single event loop — no locks needed), and released on every
  exit path.
- **CONC-3** When an upstream send exceeds `ask_timeout_s`, the gateway shall abort
  with `timeout` and release the slot.

### Config (CFG)

- **CFG-1** `load_config` shall apply precedence defaults ← YAML ← ENV exactly as the
  § 3 table defines, and shall raise `RegistryError`-analogous `ValueError` on
  non-numeric numeric fields.
- **CFG-2** The gateway shall read secrets (client token list, upstream credentials)
  exclusively via env-var indirection — no secret material in any YAML.

### Transport (TRN)

- **TRN-1** The server shall be FastMCP with `stateless_http=True`,
  `json_response=True`, `streamable_http_path="/mcp"`, served by uvicorn on one
  host:port (verified constructor kwargs on `mcp==1.28.1`).
- **TRN-2** All three tools shall have fully typed parameters and TypedDict returns so
  the SDK emits `outputSchema` and `structuredContent` (verified: only typed returns
  get this; plain `dict` does not).
- **TRN-3** Tool handlers shall obtain the `Authorization` header via a
  `Context`-annotated parameter → `ctx.request_context.request.headers.get("authorization")`
  (verified path on 1.28.1; `get_http_request()` does not exist there).
- **TRN-4** `python -m gateway` shall run `server.main()` (flags:
  `--config`, `--registry`, `--host`, `--port` — flags beat ENV beats YAML).

---

## 5. Pinned Interfaces

These signatures are frozen so four agents can build the modules in parallel.
Style: `from __future__ import annotations`, full typing, module docstrings that
explain WHY, ~90-char lines (repo has no formatter config — match `_runtime` style).

### `gateway/errors.py`

```python
from typing import ClassVar, TypedDict

class ErrorInfo(TypedDict):
    code: str                      # ERR-1 taxonomy value
    message: str                   # human-readable, credential-free
    retry_after_s: float | None    # set for "busy" only

class GatewayError(Exception):
    """Base for all typed gateway failures. code is a stable machine string."""
    code: ClassVar[str] = "gateway_error"
    def __init__(self, message: str, *, retry_after_s: float | None = None) -> None: ...
    retry_after_s: float | None
    def to_info(self) -> ErrorInfo: ...

class UnknownBridgeError(GatewayError):      code = "unknown_bridge"
class TierDeniedError(GatewayError):         code = "tier_denied"
class UnauthorizedError(GatewayError):       code = "unauthorized"
class BridgeBusyError(GatewayError):         code = "busy"
class BridgeTimeoutError(GatewayError):      code = "timeout"
class BridgeUnreachableError(GatewayError):  code = "unreachable"
class UpstreamError(GatewayError):           code = "upstream_error"

class RegistryError(ValueError):
    """Startup-time config/schema violation — never crosses the MCP boundary."""
```

### `gateway/registry.py`

```python
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

AuthMode = Literal["open", "token"]
MinTier = Literal["anonymous", "authenticated"]

@dataclass(frozen=True)
class BridgeEntry:
    id: str
    card_url: str
    description: str
    auth_mode: AuthMode = "open"
    credential_ref: str | None = None    # ENV VAR NAME (REG-3), never a secret
    min_tier: MinTier = "anonymous"

@dataclass(frozen=True)
class Registry:
    bridges: tuple[BridgeEntry, ...]
    def get(self, bridge_id: str) -> BridgeEntry: ...      # raises UnknownBridgeError
    def ids(self) -> tuple[str, ...]: ...

def load_registry(path: Path) -> Registry: ...             # raises RegistryError

def resolve_credential(
    entry: BridgeEntry, env: Mapping[str, str] | None = None,
) -> str | None:
    """None for auth_mode=open; env[credential_ref] for token mode.
    Raises UnauthorizedError when the env var is unset/empty (REG-4).
    env defaults to os.environ; injectable for tests."""
```

### `gateway/tiers.py`

```python
import enum
from collections.abc import Mapping
from dataclasses import dataclass
from gateway.registry import BridgeEntry, Registry

class AccessTier(enum.IntEnum):
    ANONYMOUS = 0
    AUTHENTICATED = 1

def tokens_from_env(env_var: str, env: Mapping[str, str] | None = None) -> frozenset[str]:
    """Comma-separated token list; entries stripped, empties dropped."""

@dataclass(frozen=True)
class TierResolver:
    """The ONE auth/visibility decision point (TIER-6). OAuth 2.1 later replaces
    resolve()'s internals; every other surface stays."""
    registry: Registry
    tokens: frozenset[str]

    def resolve(self, authorization: str | None) -> AccessTier: ...
        # None -> ANONYMOUS; valid "Bearer <t>" -> AUTHENTICATED;
        # anything else present -> raises UnauthorizedError (TIER-3)
    def visible(self, tier: AccessTier) -> tuple[BridgeEntry, ...]: ...
    def check_ask(self, tier: AccessTier, entry: BridgeEntry) -> None: ...
        # raises TierDeniedError (TIER-5)
    def extended(self, tier: AccessTier, entry: BridgeEntry) -> bool: ...
        # True iff tier >= AUTHENTICATED (CARD-6)
```

### `gateway/a2a_client.py`

```python
from dataclasses import dataclass
from typing import Any, Literal
import httpx

Dialect = Literal["v1", "v0_3"]

@dataclass(frozen=True)
class NormalizedCard:
    name: str
    description: str
    protocol_version: str        # normalized, e.g. "1.0" or "0.3"
    jsonrpc_url: str             # selected JSONRPC endpoint
    dialect: Dialect             # wire dialect to speak (CARD-3)
    skills: tuple[dict[str, Any], ...]
    raw: dict[str, Any]          # full card JSON (extended detail source)

@dataclass(frozen=True)
class AgentReply:
    text: str
    context_id: str | None
    raw: dict[str, Any]          # full JSON-RPC result (debug/tests)

async def fetch_card(
    card_url: str, *, http: httpx.AsyncClient,
    token: str | None = None, timeout_s: float = 10.0,
) -> NormalizedCard: ...
    # CARD-1..CARD-5; raises BridgeUnreachableError / BridgeTimeoutError /
    # UnauthorizedError / UpstreamError

async def send_message(
    card: NormalizedCard, text: str, *, http: httpx.AsyncClient,
    token: str | None = None, context_id: str | None = None,
    timeout_s: float = 55.0,
) -> AgentReply: ...
    # WIRE-1..WIRE-6, CONV-1..CONV-2; raises BridgeTimeoutError /
    # BridgeUnreachableError / UnauthorizedError / UpstreamError
```

`http` is always injected — production passes a shared `httpx.AsyncClient()`,
tests pass one wired to `httpx.ASGITransport(app=fake_a2a_app)` or `MockTransport`.
Exception mapping: `httpx.TimeoutException → BridgeTimeoutError`;
`httpx.TransportError → BridgeUnreachableError`; HTTP 401/403 → `UnauthorizedError`;
other non-2xx → `BridgeUnreachableError` (card) / `UpstreamError` (JSON-RPC).

### `gateway/config.py`

```python
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class GatewayConfig:
    registry_path: Path = Path("registry.yaml")
    host: str = "127.0.0.1"
    port: int = 8900
    ask_timeout_s: float = 55.0
    card_timeout_s: float = 10.0
    card_cache_ttl_s: float = 300.0
    per_bridge_concurrency: int = 2
    busy_retry_after_s: float = 10.0
    tokens_env: str = "GATEWAY_AUTH_TOKENS"
    allowed_hosts: tuple[str, ...] = ()   # § 3 table; empty = SDK default

def load_config(
    path: Path | None = None, env: Mapping[str, str] | None = None,
) -> GatewayConfig: ...
    # defaults <- YAML <- ENV (GATEWAY_* names per the § 3 table); CFG-1
```

### `gateway/server.py`

```python
from dataclasses import dataclass, field
from typing import Any, TypedDict
import httpx
from mcp.server.fastmcp import Context, FastMCP
from gateway.config import GatewayConfig
from gateway.errors import ErrorInfo
from gateway.registry import Registry
from gateway.tiers import AccessTier, TierResolver

class BridgeSummary(TypedDict):
    id: str
    description: str
    min_tier: str

class ListBridgesResult(TypedDict):
    ok: bool
    tier: str                          # "anonymous" | "authenticated"
    bridges: list[BridgeSummary]
    error: ErrorInfo | None

class GetBridgeCardResult(TypedDict):
    ok: bool
    bridge: str
    name: str | None
    description: str | None
    protocol_version: str | None
    dialect: str | None
    skills: list[dict[str, Any]] | None
    extended: bool                     # CARD-6
    card: dict[str, Any] | None        # full raw card, extended only
    error: ErrorInfo | None

class AskBridgeResult(TypedDict):
    ok: bool
    bridge: str
    conversation: str | None           # upstream contextId, verbatim (CONV-1/2)
    text: str | None
    error: ErrorInfo | None

class BridgeGate:
    """Fail-fast per-bridge concurrency counter (CONC-1/2): single event loop,
    plain int — raises BridgeBusyError instead of queueing."""
    def __init__(self, limit: int, retry_after_s: float) -> None: ...
    def slot(self):  # async context manager
        ...

@dataclass
class GatewayService:
    """Tool logic, MCP-free — unit tests hit this directly; build_server wraps it."""
    config: GatewayConfig
    registry: Registry
    resolver: TierResolver
    http: httpx.AsyncClient
    async def list_bridges(self, tier: AccessTier) -> ListBridgesResult: ...
    async def get_bridge_card(self, tier: AccessTier, bridge: str) -> GetBridgeCardResult: ...
    async def ask_bridge(
        self, tier: AccessTier, bridge: str, message: str,
        conversation: str | None = None,
    ) -> AskBridgeResult: ...

def build_server(
    config: GatewayConfig, registry: Registry, *,
    http: httpx.AsyncClient | None = None,
) -> FastMCP: ...
    # FastMCP(name="bridge-gateway", host=..., port=..., stateless_http=True,
    #         json_response=True, streamable_http_path="/mcp")
    # Tool signatures registered (Context param excluded from the client schema):
    #   async def list_bridges(ctx: Context) -> ListBridgesResult
    #   async def get_bridge_card(bridge: str, ctx: Context) -> GetBridgeCardResult
    #   async def ask_bridge(bridge: str, message: str, ctx: Context,
    #                        conversation: str | None = None) -> AskBridgeResult
    # Each wrapper: header = ctx.request_context.request.headers.get("authorization")
    #   tier = resolver.resolve(header)   # UnauthorizedError -> ok=false envelope
    # Errors from resolve() are converted to the tool's own result TypedDict.

def main(argv: list[str] | None = None) -> None: ...
    # argparse: --config, --registry, --host, --port; then
    # build_server(...).run(transport="streamable-http")
```

Error conversion rule (single helper, used by all three tools): catch `GatewayError`,
fill `ok=False`, `error=exc.to_info()`, null the payload fields. Nothing else is
caught — a genuine bug should surface loudly in tests, not be masked as upstream_error.

---

## 6. Wire Reference (normative for impl AND fake server)

Verified 2026-07-18 against A2A spec v1.0.1 (`a2aproject/A2A` `docs/specification.md`)
and `a2a-python` ≥1.0. Note for reviewers with pre-2026 A2A knowledge: v1.0 was a
proto-first rewrite — `message/send` and `role: "user"` are the LEGACY dialect, and
the parts field **kept the name `parts`** (only the `"kind"` discriminator dropped).

### v1.0 request (dialect `v1`)

```http
POST {jsonrpc_url}
Content-Type: application/json
A2A-Version: 1.0
Authorization: Bearer <upstream credential>        # token-mode bridges only

{"jsonrpc": "2.0", "id": "<uuid4>", "method": "SendMessage",
 "params": {"message": {
     "messageId": "<uuid4>",
     "role": "ROLE_USER",
     "parts": [{"text": "<message>"}],
     "contextId": "<conversation>"                 # only when continuing (CONV-2)
 }}}
```

### v1.0 response (`result` is one of)

```json
{"message": {"role": "ROLE_AGENT", "parts": [{"text": "..."}], "contextId": "ctx-1"}}

{"task": {"id": "t-1", "contextId": "ctx-1",
          "status": {"state": "TASK_STATE_COMPLETED",
                     "message": {"role": "ROLE_AGENT", "parts": [{"text": "..."}]}},
          "artifacts": [{"artifactId": "a-1", "parts": [{"text": "..."}]}]}}
```

States: `TASK_STATE_SUBMITTED|WORKING|COMPLETED|FAILED|CANCELED|REJECTED|
INPUT_REQUIRED|AUTH_REQUIRED` (extraction rules: WIRE-3).

### v0.3 request (dialect `v0_3` — fallback)

```http
POST {jsonrpc_url}
Content-Type: application/json
                                                   # NO A2A-Version header (WIRE-2)
{"jsonrpc": "2.0", "id": "<uuid4>", "method": "message/send",
 "params": {"message": {
     "messageId": "<uuid4>",
     "role": "user",
     "parts": [{"kind": "text", "text": "<message>"}],
     "contextId": "<conversation>"
 }}}
```

### v0.3 response (`result` is kind-discriminated)

```json
{"kind": "message", "role": "agent", "parts": [{"kind": "text", "text": "..."}],
 "contextId": "ctx-1"}

{"kind": "task", "id": "t-1", "contextId": "ctx-1",
 "status": {"state": "completed", "message": {"kind": "message", "parts": [
     {"kind": "text", "text": "..."}]}},
 "artifacts": [{"parts": [{"kind": "text", "text": "..."}]}]}
```

### Card dialect detection (CARD-2/3)

| Card shape | Endpoint | Dialect |
|---|---|---|
| `supportedInterfaces: [{url, protocolBinding: "JSONRPC", protocolVersion: "1.0"}]` | entry `url` | `v1` |
| `supportedInterfaces` entry with `protocolVersion: "0.3"` | entry `url` | `v0_3` |
| no `supportedInterfaces`; top-level `url` (+ optional `preferredTransport: "JSONRPC"`) | top-level `url` | `v0_3` (also when `protocolVersion` missing entirely) |
| JSONRPC nowhere (e.g. GRPC-only) | — | `UpstreamError` |

---

## 7. Test Plan (TDD — tests land FIRST and must fail before impl)

Hermetic: no network, no `claude` subprocess, no real ports. The fake A2A server is an
in-process ASGI app driven through `httpx.ASGITransport`; the MCP integration test
drives the real gateway ASGI app through the real MCP client using
`streamablehttp_client(..., httpx_client_factory=...)` — parameter verified present
on `mcp==1.28.1`. `tmp_path` for all file fixtures. Naming:
`test_<behavior>_<expected>`. Each test file carries a purpose docstring.

### `tests/fake_a2a.py` (shared infra, no tests)

```python
class FakeA2A:
    """Configurable in-process A2A endpoint (Starlette app).
    Serves GET /.well-known/agent-card.json + POST /rpc in either dialect."""
    def __init__(self, *, dialect: Dialect = "v1",
                 reply_shape: Literal["message", "task", "input_required",
                                      "failed", "jsonrpc_error", "malformed"] = "task",
                 context_id: str = "ctx-fake-1", delay_s: float = 0.0,
                 require_token: str | None = None) -> None: ...
    app: Starlette                       # wire via httpx.ASGITransport(app=...)
    requests: list[dict]                 # captured JSON bodies + headers for asserts
    def card(self) -> dict: ...          # dialect-correct AgentCard JSON
```

### `tests/test_registry.py` → REG-1..5

- load minimal + full entries, defaults applied (REG-1)
- duplicate id / bad slug / unknown enum / missing field → `RegistryError` (REG-2)
- `token` without `credential_ref`; `credential_ref` looking like a secret value
  (`"sk-abc123"` fails the ENV-NAME regex) → `RegistryError` (REG-3)
- `resolve_credential`: open→None; token+env set→value; token+env missing/empty →
  `UnauthorizedError`, message names the var, never a value (REG-4)
- `get` unknown id → `UnknownBridgeError` (REG-5)

### `tests/test_tiers.py` → TIER-1..6

- no header → ANONYMOUS; valid Bearer → AUTHENTICATED (TIER-1/2)
- token list parsing: commas, whitespace, empty entries (TIER-2)
- wrong token / `Basic` scheme / bare `Bearer` / empty configured list →
  `UnauthorizedError` — asserts NO silent downgrade (TIER-3, negative)
- `visible`: anonymous sees only `min_tier: anonymous`; authenticated sees all (TIER-4)
- `check_ask` on authenticated-only entry as anonymous → `TierDeniedError` (TIER-5)
- `extended` false/true by tier (CARD-6)

### `tests/test_a2a_client.py` → CARD-1..5, WIRE-1..6, CONV-1/2

Card reading (both dialects — the #121 regression suite):
- v1 card `supportedInterfaces` → JSONRPC entry picked, dialect `v1`
- v1-shaped card whose JSONRPC entry says `protocolVersion: "0.3"` → dialect `v0_3`
- legacy card (top-level url, no `supportedInterfaces`, no `protocolVersion`) → `v0_3`
- GRPC-only card → `UpstreamError` (CARD-4, negative)
- card 404 / connect error → `unreachable`; slow card → `timeout`; 401 →
  `unauthorized` (CARD-5, negative)
- token-mode: `Authorization: Bearer` present on card GET (CARD-1, via
  `FakeA2A.requests`)

Send, v1 wire (assert on captured request):
- method `SendMessage`, header `A2A-Version: 1.0`, `role: "ROLE_USER"`,
  parts `[{"text": ...}]` with NO `kind` key, fresh `messageId` (WIRE-1/6)
- reply `message` → text + contextId (WIRE-3)
- reply `task` completed → artifact text joined; completed w/o artifacts →
  status.message fallback (WIRE-3 — matches the real `_runtime` answer shape)
- reply `task` input_required → status.message text, same conversation (WIRE-3)
- reply `task` failed → `UpstreamError` (WIRE-3, negative)
- JSON-RPC `error` object / malformed result → `UpstreamError` (WIRE-5, negative)
- slow send → `BridgeTimeoutError` (CONC-3)

Send, v0.3 fallback wire:
- method `message/send`, NO `A2A-Version` header, `role: "user"`,
  parts `[{"kind": "text", ...}]` (WIRE-2)
- kind-discriminated message + task results parsed (WIRE-4)

contextId roundtrip:
- no `context_id` sent → request has no `contextId`; reply ctx returned (CONV-1)
- `context_id="c-7"` → request carries it verbatim; echoed reply returned (CONV-2)

### `tests/test_config.py` → CFG-1

- no YAML, no ENV → pinned `GatewayConfig` defaults
- YAML overrides every default; partial YAML leaves the rest at default
- ENV overrides both YAML and defaults, one case per `GATEWAY_*` name from the § 3
  table with the correct type
- non-numeric `GATEWAY_PORT` / `GATEWAY_ASK_TIMEOUT_S`, and a non-numeric numeric
  field inside the YAML file, each raise `ValueError` (negative)
- `allowed_hosts`: empty by default, YAML list parses, `GATEWAY_ALLOWED_HOSTS` CSV
  overrides the YAML list (§ 3 table)

### `tests/test_server_tools.py` → TIER-4/5, ERR-1..4, CONC-1/2, CARD-6 (via `GatewayService`, no MCP plumbing)

- `list_bridges` anonymous vs authenticated filtering; result envelope `ok=true`
- `get_bridge_card`: anonymous summary (`extended=false, card=null`) vs authenticated
  full raw card; tier_denied on min_tier=authenticated bridge as anonymous (negative)
- `ask_bridge` happy path: text + conversation populated
- unknown bridge → `ok=false, error.code="unknown_bridge"` (negative)
- busy: with `per_bridge_concurrency=1` and a delayed FakeA2A, second concurrent ask →
  `busy` with `retry_after_s` set; after completion a new ask succeeds — slot released
  (CONC-1/2, ERR-3, negative + recovery)
- upstream errors surface as envelope, payload fields null, no credential text (ERR-2/4)
- card cache: two asks → one card GET; ttl=0 → two card GETs

### `tests/test_integration_mcp.py` — real MCP client ⇄ real gateway, in-process

Wiring: `mcp_app = build_server(...).streamable_http_app()`;
`streamablehttp_client("http://gw.test/mcp", headers=...,
httpx_client_factory=lambda **kw: httpx.AsyncClient(
    transport=httpx.ASGITransport(app=mcp_app), base_url="http://gw.test", **kw))`
→ `ClientSession.initialize()` (client MUST send
`Accept: application/json, text/event-stream` — the SDK client does; a missing header
406s, verified). FakeA2A injected as the service's `http`.

- `initialize` + `list_tools` → exactly 3 tools, each with `outputSchema` (TRN-2)
- anonymous session: `list_bridges` hides the authenticated-only bridge;
  `ask_bridge` on it → `tier_denied` (TIER-4/5 end-to-end)
- session with `headers={"Authorization": "Bearer <good>"}` → both visible, ask ok,
  `structuredContent` present and matches the TypedDict (TRN-2/3)
- session with a bad token → every tool returns `ok=false, unauthorized` (TIER-3 e2e)
- multi-turn: ask → take `conversation` → second ask with it → FakeA2A saw the same
  `contextId` on the wire both times (CONV-1/2 e2e)
- `allowed_hosts=["gw.test"]` → a session against `http://gw.test` initializes and
  calls tools (§ 3 `allowed_hosts` end-to-end; see footnote)

> **Footnote — the 421 trap.** `mcp` 1.28.1 auto-enables DNS-rebinding protection
> whenever `host` is `127.0.0.1`/`localhost`/`::1`, allowlisting ONLY localhost Host
> headers. Behind a tunnel the public hostname arrives in the Host header, so every
> request dies with HTTP 421 although the server is "up". A non-empty `allowed_hosts`
> (§ 3) is passed to FastMCP as `TransportSecuritySettings(
> enable_dns_rebinding_protection=True, allowed_hosts=...)` — the allowlist is
> replaced, the protection itself stays on. Empty config passes `None` and keeps the
> SDK default untouched.

### Commands (upstream idiom: uv, ephemeral test deps)

```bash
cd agents/_gateway
uv run --with pytest --with pytest-asyncio pytest            # full suite
uv run --with pytest --with pytest-asyncio pytest tests/test_a2a_client.py -k v0_3
```

Red phase gate: after writing tests + empty module skeletons (signatures with
`raise NotImplementedError`), the suite MUST collect cleanly and fail; commit that
state before implementing (TDD evidence).

---

## 8. Verification Plan

### V1 — hermetic suite green

`cd agents/_gateway && uv run --with pytest --with pytest-asyncio pytest` exits 0.

### V2 — live end-to-end against a real bridge agent (manual, before merge)

No private hostnames in this file — substitute your own instance.

1. Start a real agent: `cd agents && uv run python -m _runtime.server --agent <name>`
   (or use an already-running bridge; its card lives at
   `https://<your-bridge-host>/.well-known/agent-card.json`).
2. `registry.yaml`: one entry with that `card_url`, `auth_mode` per the agent,
   `min_tier: anonymous`; plus a second entry with `min_tier: authenticated` to
   exercise tiers. Export `GATEWAY_AUTH_TOKENS=<random token>`.
3. `cd agents/_gateway && uv run python -m gateway --registry registry.yaml`.
4. Connect a real MCP client to `http://<host>:8900/mcp` (e.g.
   `claude mcp add --transport http bridge-gateway http://<host>:8900/mcp`), then:
   - `list_bridges` anonymous → only the anonymous bridge; with
     `--header "Authorization: Bearer <token>"` → both (TIER e2e)
   - `get_bridge_card` → normalized card, correct `dialect` for the runtime
     (the `_runtime` server registers v0.3 compat, but its native card/wire are v1 —
     expect `v1` from `supportedInterfaces`)
   - `ask_bridge` → real answer text (the runtime answers via completed-Task artifact —
     WIRE-3 task branch is exercised live)
   - second `ask_bridge` with the returned `conversation` → agent demonstrably keeps
     context (the runtime keys memory by `context_id`)
   - two parallel long asks + a third → `busy` with retry hint
5. Negative: stop the agent → `ask_bridge` returns `unreachable`, not a hang.

### V3 — CI wiring (a deliberate step; nothing happens automatically)

`.github/workflows/agents-tests.yml` path trigger `agents/**` already fires for this
directory, BUT `agents/pyproject.toml` pins `testpaths=["tests"]`, so gateway tests
would silently not run. Add a second job to the same workflow:

```yaml
  gateway-pytest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv run --with pytest --with pytest-asyncio pytest
        working-directory: agents/_gateway
```

Definition of done for CI: both jobs green on the PR; the gateway job demonstrably
executed >0 tests (guard against silent no-collection).

---

## 9. File Layout & Packaging

```
agents/_gateway/
├── SPEC.md                  # this file
├── pyproject.toml           # own package — self-containment is the repo-split seam
├── registry.example.yaml    # documented per-field, agent.yaml comment style
├── gateway.example.yaml     # optional config file, all keys + defaults commented
├── gateway/
│   ├── __init__.py
│   ├── __main__.py          # python -m gateway → server.main()
│   ├── errors.py
│   ├── registry.py
│   ├── tiers.py
│   ├── a2a_client.py
│   ├── config.py
│   └── server.py
└── tests/
    ├── conftest.py          # tmp_path registries, FakeA2A + injected http fixtures
    ├── fake_a2a.py
    ├── test_registry.py
    ├── test_tiers.py
    ├── test_a2a_client.py
    ├── test_config.py
    ├── test_server_tools.py
    └── test_integration_mcp.py
```

README.md follows after the MVP lands (not part of this build). No SPDX headers in
.py files (repo-wide MIT LICENSE covers it). English only — CORE policy.

### `pyproject.toml` (pinned sketch)

```toml
[project]
name = "bridge-gateway"
version = "0.1.0"
description = "Thin, stateless MCP->A2A gateway: MCP clients talk to bridge A2A agents"
requires-python = ">=3.11"
dependencies = [
    "mcp>=1.28.1,<2",        # verified: FastMCP stateless_http/json_response/streamable_http_path, Context.request_context.request, streamablehttp_client(httpx_client_factory=...)
    "httpx>=0.27",           # direct dep: A2A JSON-RPC client + ASGITransport in tests
    "pyyaml>=6.0",           # registry + config files
    "uvicorn>=0.35.0",       # serving (FastMCP.run uses it); version matches agents/
]
# No [build-system] — like agents/: not packaged, runs via pythonpath.
# Test deps stay OUT of [project]: injected ephemerally, upstream idiom:
#   uv run --with pytest --with pytest-asyncio pytest

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
asyncio_mode = "auto"
```

Deliberately absent: `a2a-sdk` (§ 2 decision 1), `starlette` (only tests import it,
and it arrives transitively with `mcp`; if the fake server wants it explicitly, add
`--with starlette` to the test command instead of a runtime dep).

### `registry.example.yaml` (shape)

Documented per-field in the `agents/_template/agent.yaml` comment style (WHY over
WHAT, placeholders in `<angle brackets>`), content exactly as § 3.

---

## 10. Build Order (4 parallel agents)

| Agent | Builds | Depends on pinned interfaces of |
|---|---|---|
| A | `errors.py` + `registry.py` + their tests | — |
| B | `tiers.py` + tests | errors, registry (dataclass shapes only) |
| C | `a2a_client.py` + `fake_a2a.py` + tests | errors |
| D | `config.py` + `server.py` + tool/integration tests | all of the above |

Interfaces in § 5 are the contract: an agent may add private helpers, but public
names/signatures/exception behavior are frozen. Any needed deviation is a SPEC PR
first, not a silent drift.
