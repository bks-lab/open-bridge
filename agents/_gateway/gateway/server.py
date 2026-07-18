"""MCP server wiring + tool logic (SPEC TRN/ERR/CONC, §5).

``GatewayService`` holds the MCP-free tool logic (unit tests hit it directly);
``build_server`` wraps it into FastMCP (stateless Streamable HTTP). Errors are
returned in the result envelope, never raised across the MCP boundary — only
typed returns give MCP clients an outputSchema/structuredContent.
"""

from __future__ import annotations

from dataclasses import dataclass
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

    Single event loop, plain int — raises BridgeBusyError instead of queueing.
    """

    def __init__(self, limit: int, retry_after_s: float) -> None:
        raise NotImplementedError

    def slot(self):
        """Async context manager guarding one in-flight ask."""
        raise NotImplementedError


@dataclass
class GatewayService:
    """Tool logic, MCP-free — unit tests hit this directly; build_server wraps it."""

    config: GatewayConfig
    registry: Registry
    resolver: TierResolver
    http: httpx.AsyncClient

    async def list_bridges(self, tier: AccessTier) -> ListBridgesResult:
        raise NotImplementedError

    async def get_bridge_card(self, tier: AccessTier, bridge: str) -> GetBridgeCardResult:
        raise NotImplementedError

    async def ask_bridge(
        self,
        tier: AccessTier,
        bridge: str,
        message: str,
        conversation: str | None = None,
    ) -> AskBridgeResult:
        raise NotImplementedError


def build_server(
    config: GatewayConfig,
    registry: Registry,
    *,
    http: httpx.AsyncClient | None = None,
) -> FastMCP:
    raise NotImplementedError


def main(argv: list[str] | None = None) -> None:
    raise NotImplementedError
