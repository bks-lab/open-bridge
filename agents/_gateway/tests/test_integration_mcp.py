"""Integration tests: real MCP client <-> real gateway app, fully in-process
(SPEC.md § 7 test plan, TRN-1..3, TIER e2e, CONV e2e).

Wiring (verified hands-on against mcp==1.28.1):

- ``build_server(...).streamable_http_app()`` returns the Starlette ASGI app.
- The app MUST run inside the session manager's lifespan —
  ``async with server.session_manager.run():`` — otherwise every request dies
  with ``RuntimeError: Task group is not initialized. Make sure to use run().``
  (``httpx.ASGITransport`` never runs a lifespan itself.)
- FastMCP auto-enables DNS-rebinding protection for host 127.0.0.1 with
  ``allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*"]`` — the wildcard
  patterns require an explicit port in the Host header, so the in-process
  base URL must carry one (a portless or foreign host 421s).
- ``streamablehttp_client``'s ``httpx_client_factory`` is called with
  ``headers`` / ``timeout`` / ``auth`` kwargs (the ``McpHttpClientFactory``
  protocol); the factory returns an ``httpx.AsyncClient`` on an
  ``ASGITransport``, so no real socket ever opens.

Hermetic: the upstream A2A side is a FakeA2A (in-process ASGI as well); the
client token list is injected via monkeypatch on GATEWAY_AUTH_TOKENS — dummy
values only, never real secrets.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import httpx
import pytest

from conftest import GOOD_TOKEN, two_tier_registry
from fake_a2a import FakeA2A
from gateway.config import GatewayConfig
from gateway.server import build_server
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client

# Explicit port required — see module docstring (DNS-rebinding allowlist).
BASE_URL = "http://127.0.0.1:8900"

EXPECTED_TOOLS = {"list_bridges", "get_bridge_card", "ask_bridge"}

ASK_RESULT_KEYS = {"ok", "bridge", "conversation", "text", "error"}


@pytest.fixture
async def gateway(monkeypatch, make_http):
    """A running in-process gateway app + its FakeA2A upstream."""
    monkeypatch.setenv("GATEWAY_AUTH_TOKENS", GOOD_TOKEN)
    fake = FakeA2A()
    server = build_server(
        GatewayConfig(), two_tier_registry(), http=make_http(fake)
    )
    app = server.streamable_http_app()
    async with server.session_manager.run():
        yield app, fake


@asynccontextmanager
async def mcp_session(app, headers: dict[str, str] | None = None):
    """An initialized ClientSession against the gateway app, in-process."""

    def factory(headers=None, timeout=None, auth=None) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url=BASE_URL,
            headers=headers,
            timeout=timeout,
            auth=auth,
        )

    async with streamablehttp_client(
        f"{BASE_URL}/mcp", headers=headers, httpx_client_factory=factory
    ) as (read_stream, write_stream, _get_session_id):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            yield session


# ---------------------------------------------------------------------------
# TRN-1/2 — three tools, each with an outputSchema
# ---------------------------------------------------------------------------


async def test_list_tools_exposes_exactly_three_tools_with_output_schema(gateway):
    app, _fake = gateway

    async with mcp_session(app) as session:
        tools = (await session.list_tools()).tools

    assert {tool.name for tool in tools} == EXPECTED_TOOLS
    for tool in tools:
        assert tool.outputSchema is not None, f"{tool.name} lacks outputSchema"


# ---------------------------------------------------------------------------
# TIER-4/5 end-to-end — anonymous session
# ---------------------------------------------------------------------------


async def test_anonymous_session_hides_authenticated_only_bridge(gateway):
    app, _fake = gateway

    async with mcp_session(app) as session:
        result = await session.call_tool("list_bridges", {})

    assert result.structuredContent is not None
    payload = result.structuredContent
    assert payload["ok"] is True
    assert payload["tier"] == "anonymous"
    assert [b["id"] for b in payload["bridges"]] == ["open-fake"]


async def test_anonymous_ask_on_authenticated_only_bridge_returns_tier_denied(
    gateway,
):
    app, fake = gateway

    async with mcp_session(app) as session:
        result = await session.call_tool(
            "ask_bridge", {"bridge": "secure-fake", "message": "hello"}
        )

    payload = result.structuredContent
    assert payload is not None
    assert payload["ok"] is False
    assert payload["error"]["code"] == "tier_denied"
    # The upstream bridge must not have been contacted (TIER-5).
    assert fake.requests == []


# ---------------------------------------------------------------------------
# TIER-2 + TRN-2/3 end-to-end — authenticated session
# ---------------------------------------------------------------------------


async def test_authenticated_session_sees_all_bridges_and_ask_succeeds(gateway):
    app, _fake = gateway
    headers = {"Authorization": f"Bearer {GOOD_TOKEN}"}

    async with mcp_session(app, headers=headers) as session:
        listed = await session.call_tool("list_bridges", {})
        asked = await session.call_tool(
            "ask_bridge", {"bridge": "secure-fake", "message": "hello"}
        )

    listed_payload = listed.structuredContent
    assert listed_payload is not None
    assert listed_payload["ok"] is True
    assert listed_payload["tier"] == "authenticated"
    assert sorted(b["id"] for b in listed_payload["bridges"]) == [
        "open-fake",
        "secure-fake",
    ]

    asked_payload = asked.structuredContent
    assert asked_payload is not None
    # structuredContent present and shaped exactly like AskBridgeResult (TRN-2).
    assert set(asked_payload.keys()) == ASK_RESULT_KEYS
    assert asked_payload["ok"] is True
    assert asked_payload["bridge"] == "secure-fake"
    assert asked_payload["text"] == "artifact reply text"
    assert asked_payload["conversation"] == "ctx-fake-1"
    assert asked_payload["error"] is None


# ---------------------------------------------------------------------------
# TIER-3 end-to-end — bad token never downgrades silently
# ---------------------------------------------------------------------------


async def test_bad_token_session_gets_unauthorized_envelope_from_every_tool(
    gateway,
):
    app, fake = gateway
    headers = {"Authorization": "Bearer not-a-configured-token"}

    async with mcp_session(app, headers=headers) as session:
        calls = {
            "list_bridges": await session.call_tool("list_bridges", {}),
            "get_bridge_card": await session.call_tool(
                "get_bridge_card", {"bridge": "open-fake"}
            ),
            "ask_bridge": await session.call_tool(
                "ask_bridge", {"bridge": "open-fake", "message": "hello"}
            ),
        }

    for tool_name, result in calls.items():
        payload = result.structuredContent
        assert payload is not None, f"{tool_name} returned no structuredContent"
        assert payload["ok"] is False, f"{tool_name} did not fail"
        assert payload["error"]["code"] == "unauthorized", tool_name
    assert fake.requests == []


# ---------------------------------------------------------------------------
# CONV-1/2 end-to-end — multi-turn keeps one contextId on the wire
# ---------------------------------------------------------------------------


async def test_multi_turn_ask_reuses_the_same_context_id_on_the_wire(gateway):
    app, fake = gateway

    async with mcp_session(app) as session:
        first = await session.call_tool(
            "ask_bridge", {"bridge": "open-fake", "message": "first turn"}
        )
        conversation = first.structuredContent["conversation"]
        assert conversation == "ctx-fake-1"

        second = await session.call_tool(
            "ask_bridge",
            {
                "bridge": "open-fake",
                "message": "second turn",
                "conversation": conversation,
            },
        )

    assert second.structuredContent["ok"] is True
    assert second.structuredContent["conversation"] == conversation

    rpc_messages = [
        r["body"]["params"]["message"] for r in fake.requests if r["path"] == "/rpc"
    ]
    assert len(rpc_messages) == 2
    # CONV-1: the opening ask sends NO contextId — the upstream generates it.
    assert "contextId" not in rpc_messages[0]
    # CONV-2: the follow-up carries the returned conversation verbatim, so the
    # fake saw the very same contextId again on the wire.
    assert rpc_messages[1]["contextId"] == conversation
