"""MCP server wiring + tool logic (SPEC TRN/ERR/CONC, §5).

``GatewayService`` holds the MCP-free tool logic (unit tests hit it directly);
``build_server`` wraps it into FastMCP (stateless Streamable HTTP). Errors are
returned in the result envelope, never raised across the MCP boundary — only
typed returns give MCP clients an outputSchema/structuredContent, and FastMCP
would otherwise flatten a raised exception into unparseable prefixed text.

Only ``GatewayError`` is converted to an envelope. Anything else propagates —
a genuine bug must surface loudly in tests, not hide behind ``upstream_error``.
"""

from __future__ import annotations

import argparse
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, TypedDict

import httpx
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from gateway.a2a_client import NormalizedCard, fetch_card, send_message
from gateway.config import GatewayConfig, load_config
from gateway.errors import BridgeBusyError, ErrorInfo, GatewayError
from gateway.registry import BridgeEntry, Registry, load_registry, resolve_credential
from gateway.tiers import AccessTier, TierResolver, tokens_from_env


class BridgeSummary(TypedDict):
    id: str
    description: str
    min_tier: str


class ListBridgesResult(TypedDict):
    ok: bool
    tier: str
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
    extended: bool
    card: dict[str, Any] | None
    error: ErrorInfo | None


class AskBridgeResult(TypedDict):
    ok: bool
    bridge: str
    conversation: str | None
    text: str | None
    error: ErrorInfo | None


class BridgeGate:
    """Fail-fast per-bridge concurrency counter (CONC-1/2).

    Single event loop, plain int — no locks needed, and no queueing: an MCP
    client blocked in a queue would burn its own tool-call timeout invisibly,
    so an over-limit ask fails fast with ``busy`` + a retry hint instead.
    """

    def __init__(self, limit: int, retry_after_s: float) -> None:
        self._limit = limit
        self._retry_after_s = retry_after_s
        self._in_flight = 0

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        """Hold one in-flight slot; released on EVERY exit path (CONC-2).

        The busy check happens before the counter increments, so a rejected
        caller never has to release anything; the ``finally`` guarantees the
        release for success, timeout, and upstream-error paths alike.
        """
        if self._in_flight >= self._limit:
            raise BridgeBusyError(
                "bridge is busy — concurrency limit reached, retry later",
                retry_after_s=self._retry_after_s,
            )
        self._in_flight += 1
        try:
            yield
        finally:
            self._in_flight -= 1


@dataclass
class GatewayService:
    """Tool logic, MCP-free — unit tests hit this directly; build_server wraps it."""

    config: GatewayConfig
    registry: Registry
    resolver: TierResolver
    http: httpx.AsyncClient
    # Private in-process state (SPEC §2 decisions 2/6): per-bridge gates and the
    # card TTL cache. Deliberately init=False — losing them on restart is fine.
    _gates: dict[str, BridgeGate] = field(default_factory=dict, init=False, repr=False)
    _card_cache: dict[str, tuple[float, NormalizedCard]] = field(
        default_factory=dict, init=False, repr=False
    )

    async def list_bridges(self, tier: AccessTier) -> ListBridgesResult:
        """TIER-4: visibility is delegated entirely to the resolver."""
        bridges: list[BridgeSummary] = [
            {"id": e.id, "description": e.description, "min_tier": e.min_tier}
            for e in self.resolver.visible(tier)
        ]
        return {"ok": True, "tier": tier.name.lower(), "bridges": bridges, "error": None}

    async def get_bridge_card(
        self, tier: AccessTier, bridge: str
    ) -> GetBridgeCardResult:
        """Normalized card summary; full raw card only for elevated tiers (CARD-6)."""
        try:
            entry = self.registry.get(bridge)
            # TIER-5: deny BEFORE any upstream contact — a denied caller must
            # not be able to probe whether the bridge is even reachable.
            self.resolver.check_ask(tier, entry)
            card = await self._get_card(entry)
        except GatewayError as exc:
            return {
                "ok": False,
                "bridge": bridge,
                "name": None,
                "description": None,
                "protocol_version": None,
                "dialect": None,
                "skills": None,
                "extended": False,
                "card": None,
                "error": exc.to_info(),
            }
        extended = self.resolver.extended(tier, entry)
        return {
            "ok": True,
            "bridge": bridge,
            "name": card.name,
            "description": card.description,
            "protocol_version": card.protocol_version,
            "dialect": card.dialect,
            "skills": list(card.skills),
            "extended": extended,
            "card": card.raw if extended else None,
            "error": None,
        }

    async def ask_bridge(
        self,
        tier: AccessTier,
        bridge: str,
        message: str,
        conversation: str | None = None,
    ) -> AskBridgeResult:
        """One A2A ask; ``conversation`` is the upstream contextId (CONV-1/2)."""
        try:
            entry = self.registry.get(bridge)
            self.resolver.check_ask(tier, entry)
            # The slot covers card fetch + send: both consume upstream capacity,
            # and the gate exists to protect the upstream, not the gateway.
            async with self._gate_for(entry.id).slot():
                token = resolve_credential(entry)
                card = await self._get_card(entry, token=token)
                reply = await send_message(
                    card,
                    message,
                    http=self.http,
                    token=token,
                    context_id=conversation,
                    timeout_s=self.config.ask_timeout_s,
                )
        except GatewayError as exc:
            return {
                "ok": False,
                "bridge": bridge,
                "conversation": None,
                "text": None,
                "error": exc.to_info(),
            }
        return {
            "ok": True,
            "bridge": bridge,
            "conversation": reply.context_id,
            "text": reply.text,
            "error": None,
        }

    def _gate_for(self, bridge_id: str) -> BridgeGate:
        """Lazily created per-bridge gate (CONC-2: accounting is per bridge id)."""
        gate = self._gates.get(bridge_id)
        if gate is None:
            gate = BridgeGate(
                self.config.per_bridge_concurrency, self.config.busy_retry_after_s
            )
            self._gates[bridge_id] = gate
        return gate

    async def _get_card(
        self, entry: BridgeEntry, token: str | None = None
    ) -> NormalizedCard:
        """Card fetch behind the in-process TTL cache (SPEC §2 decision 6).

        ``card_cache_ttl_s: 0`` disables caching entirely. The credential is
        resolved by the caller when it needs the token for the send as well;
        card-only callers let this helper resolve it.
        """
        ttl = self.config.card_cache_ttl_s
        now = time.monotonic()
        if ttl > 0:
            cached = self._card_cache.get(entry.id)
            if cached is not None and cached[0] > now:
                return cached[1]
        if token is None:
            token = resolve_credential(entry)
        card = await fetch_card(
            entry.card_url,
            http=self.http,
            token=token,
            timeout_s=self.config.card_timeout_s,
        )
        if ttl > 0:
            self._card_cache[entry.id] = (now + ttl, card)
        return card


def build_server(
    config: GatewayConfig,
    registry: Registry,
    *,
    http: httpx.AsyncClient | None = None,
) -> FastMCP:
    """Wrap a GatewayService into a stateless Streamable-HTTP FastMCP (TRN-1..3).

    Every tool resolves the caller's tier from the raw Authorization header via
    the ONE resolver (TIER-6); an UnauthorizedError from ``resolve`` becomes an
    ``ok=false`` envelope like any other GatewayError — never a raised
    exception across the MCP boundary (ERR-2), never a silent downgrade.
    """
    service = GatewayService(
        config=config,
        registry=registry,
        resolver=TierResolver(
            registry=registry, tokens=tokens_from_env(config.tokens_env)
        ),
        http=http if http is not None else httpx.AsyncClient(),
    )

    # DNS-rebinding protection: the SDK auto-restricts localhost binds to
    # localhost Host headers, which 421s behind a tunnel (public hostname in
    # the Host header). A configured allowlist replaces the auto-allowlist —
    # protection stays ON, only the accepted Host values change. Empty config
    # passes None, keeping the SDK's default behavior untouched.
    transport_security: TransportSecuritySettings | None = None
    if config.allowed_hosts:
        transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=list(config.allowed_hosts),
        )

    server = FastMCP(
        name="bridge-gateway",
        host=config.host,
        port=config.port,
        stateless_http=True,
        json_response=True,
        streamable_http_path="/mcp",
        transport_security=transport_security,
    )

    def resolve_tier(ctx: Context) -> AccessTier:
        # TRN-3: verified header path on mcp==1.28.1 (get_http_request()
        # does not exist there). Headers are case-insensitive in Starlette.
        header = ctx.request_context.request.headers.get("authorization")
        return service.resolver.resolve(header)

    @server.tool()
    async def list_bridges(ctx: Context) -> ListBridgesResult:
        """List the bridges this caller may see, filtered by access tier."""
        try:
            tier = resolve_tier(ctx)
        except GatewayError as exc:
            # No resolved tier exists on this path; an empty string is honest —
            # reporting "anonymous" would look like the forbidden downgrade.
            return {"ok": False, "tier": "", "bridges": [], "error": exc.to_info()}
        return await service.list_bridges(tier)

    @server.tool()
    async def get_bridge_card(bridge: str, ctx: Context) -> GetBridgeCardResult:
        """Fetch + normalize a bridge's AgentCard (full raw card when elevated)."""
        try:
            tier = resolve_tier(ctx)
        except GatewayError as exc:
            return {
                "ok": False,
                "bridge": bridge,
                "name": None,
                "description": None,
                "protocol_version": None,
                "dialect": None,
                "skills": None,
                "extended": False,
                "card": None,
                "error": exc.to_info(),
            }
        return await service.get_bridge_card(tier, bridge)

    @server.tool()
    async def ask_bridge(
        bridge: str,
        message: str,
        ctx: Context,
        conversation: str | None = None,
    ) -> AskBridgeResult:
        """Send one message to a bridge; pass ``conversation`` back to continue."""
        try:
            tier = resolve_tier(ctx)
        except GatewayError as exc:
            return {
                "ok": False,
                "bridge": bridge,
                "conversation": None,
                "text": None,
                "error": exc.to_info(),
            }
        return await service.ask_bridge(tier, bridge, message, conversation)

    return server


def main(argv: list[str] | None = None) -> None:
    """CLI entrypoint (TRN-4): flags beat ENV beat YAML.

    ``load_config`` already resolves defaults <- YAML <- ENV; the flags are
    applied on top of the result, giving the operator the final word.
    """
    parser = argparse.ArgumentParser(
        prog="gateway",
        description="Thin, stateless MCP->A2A gateway (Streamable HTTP on /mcp).",
    )
    parser.add_argument("--config", type=Path, default=None, help="Config YAML path")
    parser.add_argument(
        "--registry", type=Path, default=None, help="Bridge registry YAML path"
    )
    parser.add_argument("--host", default=None, help="Bind host")
    parser.add_argument("--port", type=int, default=None, help="Bind port")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    if args.registry is not None:
        config = replace(config, registry_path=args.registry)
    if args.host is not None:
        config = replace(config, host=args.host)
    if args.port is not None:
        config = replace(config, port=args.port)

    registry = load_registry(config.registry_path)
    build_server(config, registry).run(transport="streamable-http")
