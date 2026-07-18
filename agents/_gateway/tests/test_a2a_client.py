"""Tests for gateway/a2a_client.py (SPEC.md § 4 CARD/WIRE/CONV, § 7 test plan).

Hermetic: no network, no real ports. FakeA2A (tests/fake_a2a.py) is driven via
``httpx.ASGITransport``; the two "unreachable"/"non-JSON" negative cases use a
raw ``httpx.MockTransport`` instead, since they need behavior no in-process
ASGI app can produce (a real connection failure / a non-JSON body). Covers:

- Card reading, both dialects, including the #121 regression cases (CARD-1..6).
- Send, v1.0 wire: method/header/role/parts shape, all WIRE-3 reply branches,
  WIRE-5 error branches, WIRE-6 fresh messageId (CONC-3 for the timeout case).
- Send, v0.3 fallback wire (WIRE-2/4).
- contextId roundtrip (CONV-1/2).
- One minimal frozen-dataclass shape check for NormalizedCard/AgentReply — the
  SPEC-sanctioned exception to "everything must be red" (these dataclasses
  have plain generated __init__, no NotImplementedError body, so they already
  pass; kept to exactly one test, see build notes).
"""

from __future__ import annotations

import uuid

import httpx
import pytest

from fake_a2a import FakeA2A
from gateway.a2a_client import AgentReply, NormalizedCard, fetch_card, send_message
from gateway.errors import (
    BridgeTimeoutError,
    BridgeUnreachableError,
    UnauthorizedError,
    UpstreamError,
)

CARD_URL = "http://a2a.test/.well-known/agent-card.json"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _v1_card(url: str = "http://a2a.test/rpc") -> NormalizedCard:
    """A hand-built v1 NormalizedCard — decouples send_message tests from
    fetch_card actually working (both are red independently in this phase)."""
    return NormalizedCard(
        name="fake-bridge",
        description="Fake bridge",
        protocol_version="1.0",
        jsonrpc_url=url,
        dialect="v1",
        skills=(),
        raw={},
    )


def _v0_3_card(url: str = "http://a2a.test/rpc") -> NormalizedCard:
    return NormalizedCard(
        name="fake-bridge",
        description="Fake bridge",
        protocol_version="0.3",
        jsonrpc_url=url,
        dialect="v0_3",
        skills=(),
        raw={},
    )


def _assert_valid_uuid4(value: str) -> None:
    assert uuid.UUID(value).version == 4


@pytest.fixture
async def make_client():
    """Factory: wires a fresh httpx.AsyncClient onto a FakeA2A's ASGI app.

    Not a conftest.py fixture on purpose — this test file is self-contained
    per the build assignment (fake_a2a.py + test_a2a_client.py only).
    """
    clients: list[httpx.AsyncClient] = []

    def _make(fake: FakeA2A) -> httpx.AsyncClient:
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=fake.app), base_url="http://a2a.test"
        )
        clients.append(client)
        return client

    yield _make

    for client in clients:
        await client.aclose()


# ---------------------------------------------------------------------------
# dataclass shape (SPEC-sanctioned exception — kept to exactly one test)
# ---------------------------------------------------------------------------


def test_normalized_card_and_agent_reply_are_frozen_dataclasses_with_pinned_fields() -> (
    None
):
    card = _v1_card()
    assert card.dialect == "v1"
    assert card.jsonrpc_url == "http://a2a.test/rpc"
    with pytest.raises(AttributeError):
        card.dialect = "v0_3"  # type: ignore[misc]

    reply = AgentReply(text="hi", context_id="ctx-1", raw={})
    assert reply.text == "hi"
    assert reply.context_id == "ctx-1"
    with pytest.raises(AttributeError):
        reply.text = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# CARD-1..6 — card reading, both dialects (the #121 regression suite)
# ---------------------------------------------------------------------------


async def test_fetch_card_v1_supported_interfaces_picks_jsonrpc_entry(make_client) -> None:
    fake = FakeA2A(dialect="v1")
    http = make_client(fake)

    card = await fetch_card(CARD_URL, http=http)

    assert card.dialect == "v1"
    assert card.protocol_version == "1.0"
    assert card.jsonrpc_url == "http://a2a.test/rpc"


async def test_fetch_card_v1_shaped_card_with_v0_3_interface_entry_selects_v0_3(
    make_client,
) -> None:
    """#121 regression: a v1-shaped card (has supportedInterfaces) whose
    JSONRPC entry itself declares protocolVersion "0.3" must still select
    v0_3 — per-entry version, not "presence of supportedInterfaces == v1"."""
    fake = FakeA2A(dialect="v1")
    fake.card_override = {
        "name": "fake-bridge",
        "description": "v1-shaped card with a 0.3 JSONRPC entry",
        "supportedInterfaces": [
            {
                "url": "http://a2a.test/rpc",
                "protocolBinding": "JSONRPC",
                "protocolVersion": "0.3",
            }
        ],
    }
    http = make_client(fake)

    card = await fetch_card(CARD_URL, http=http)

    assert card.dialect == "v0_3"
    assert card.protocol_version == "0.3"
    assert card.jsonrpc_url == "http://a2a.test/rpc"


async def test_fetch_card_legacy_card_without_supported_interfaces_selects_v0_3(
    make_client,
) -> None:
    """Legacy card: no supportedInterfaces, no protocolVersion at all -> v0_3
    (CARD-3: missing version is treated as fully 0.3)."""
    fake = FakeA2A(dialect="v0_3")
    http = make_client(fake)

    card = await fetch_card(CARD_URL, http=http)

    assert card.dialect == "v0_3"
    assert card.jsonrpc_url == "http://a2a.test/rpc"


async def test_fetch_card_grpc_only_card_raises_upstream_error(make_client) -> None:
    fake = FakeA2A(dialect="v1")
    fake.card_override = {
        "name": "fake-bridge",
        "description": "GRPC-only card, no JSONRPC anywhere",
        "supportedInterfaces": [
            {"url": "grpc://a2a.test:50051", "protocolBinding": "GRPC"}
        ],
    }
    http = make_client(fake)

    with pytest.raises(UpstreamError):
        await fetch_card(CARD_URL, http=http)


async def test_fetch_card_404_raises_unreachable(make_client) -> None:
    fake = FakeA2A(dialect="v1")
    http = make_client(fake)

    with pytest.raises(BridgeUnreachableError):
        await fetch_card("http://a2a.test/no-such-card.json", http=http)


async def test_fetch_card_connect_error_raises_unreachable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated connection refused", request=request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://a2a.test")
    try:
        with pytest.raises(BridgeUnreachableError):
            await fetch_card(CARD_URL, http=http)
    finally:
        await http.aclose()


async def test_fetch_card_non_json_response_raises_upstream_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json-at-all", headers={"content-type": "text/plain"})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://a2a.test")
    try:
        with pytest.raises(UpstreamError):
            await fetch_card(CARD_URL, http=http)
    finally:
        await http.aclose()


async def test_fetch_card_slow_card_raises_timeout(make_client) -> None:
    fake = FakeA2A(dialect="v1", delay_s=0.2)
    http = make_client(fake)

    with pytest.raises(BridgeTimeoutError):
        await fetch_card(CARD_URL, http=http, timeout_s=0.05)


async def test_fetch_card_401_raises_unauthorized(make_client) -> None:
    fake = FakeA2A(dialect="v1", require_token="secret-tok")
    http = make_client(fake)

    with pytest.raises(UnauthorizedError):
        await fetch_card(CARD_URL, http=http)


async def test_fetch_card_token_mode_sends_bearer_header_on_card_get(make_client) -> None:
    fake = FakeA2A(dialect="v1", require_token="secret-tok")
    http = make_client(fake)

    card = await fetch_card(CARD_URL, http=http, token="secret-tok")

    assert card.dialect == "v1"
    get_requests = [r for r in fake.requests if r["method"] == "GET"]
    assert get_requests, "expected a captured card GET request"
    assert get_requests[-1]["headers"].get("authorization") == "Bearer secret-tok"


# ---------------------------------------------------------------------------
# WIRE-1/3/5/6, CONC-3 — send, v1.0 wire
# ---------------------------------------------------------------------------


async def test_send_message_v1_wire_shape_method_header_role_parts(make_client) -> None:
    fake = FakeA2A(dialect="v1", reply_shape="message")
    http = make_client(fake)
    card = _v1_card()

    reply = await send_message(card, "hello there", http=http)

    rpc_requests = [r for r in fake.requests if r["method"] == "POST"]
    assert len(rpc_requests) == 1
    req = rpc_requests[0]
    assert req["headers"].get("a2a-version") == "1.0"
    assert req["body"]["method"] == "SendMessage"
    message = req["body"]["params"]["message"]
    assert message["role"] == "ROLE_USER"
    assert message["parts"] == [{"text": "hello there"}]
    assert "kind" not in message["parts"][0]
    _assert_valid_uuid4(message["messageId"])
    assert reply.text == "fake reply text"
    assert reply.context_id == "ctx-fake-1"


async def test_send_message_v1_message_reply_returns_text_and_context(make_client) -> None:
    fake = FakeA2A(dialect="v1", reply_shape="message", context_id="ctx-msg-1")
    http = make_client(fake)
    card = _v1_card()

    reply = await send_message(card, "ping", http=http)

    assert reply.text == "fake reply text"
    assert reply.context_id == "ctx-msg-1"


async def test_send_message_v1_task_completed_joins_artifact_text(make_client) -> None:
    fake = FakeA2A(dialect="v1", reply_shape="task")
    http = make_client(fake)
    card = _v1_card()

    reply = await send_message(card, "ping", http=http)

    assert reply.text == "artifact reply text"
    assert reply.context_id == "ctx-fake-1"


async def test_send_message_v1_task_completed_without_artifacts_falls_back_to_status_message(
    make_client,
) -> None:
    fake = FakeA2A(dialect="v1", reply_shape="task")
    fake.include_artifacts = False
    http = make_client(fake)
    card = _v1_card()

    reply = await send_message(card, "ping", http=http)

    assert reply.text == "status message text"


async def test_send_message_v1_task_input_required_returns_status_message_same_conversation(
    make_client,
) -> None:
    fake = FakeA2A(dialect="v1", reply_shape="input_required")
    http = make_client(fake)
    card = _v1_card()

    reply = await send_message(card, "ping", http=http, context_id="c-existing")

    assert reply.text == "please provide more info"
    assert reply.context_id == "c-existing"


async def test_send_message_v1_task_failed_raises_upstream_error(make_client) -> None:
    fake = FakeA2A(dialect="v1", reply_shape="failed")
    http = make_client(fake)
    card = _v1_card()

    with pytest.raises(UpstreamError):
        await send_message(card, "ping", http=http)


async def test_send_message_v1_jsonrpc_error_object_raises_upstream_error(make_client) -> None:
    fake = FakeA2A(dialect="v1", reply_shape="jsonrpc_error")
    http = make_client(fake)
    card = _v1_card()

    with pytest.raises(UpstreamError):
        await send_message(card, "ping", http=http)


async def test_send_message_v1_malformed_result_raises_upstream_error(make_client) -> None:
    fake = FakeA2A(dialect="v1", reply_shape="malformed")
    http = make_client(fake)
    card = _v1_card()

    with pytest.raises(UpstreamError):
        await send_message(card, "ping", http=http)


async def test_send_message_non_2xx_response_raises_upstream_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://a2a.test")
    card = _v1_card()
    try:
        with pytest.raises(UpstreamError):
            await send_message(card, "ping", http=http)
    finally:
        await http.aclose()


async def test_send_message_slow_send_raises_timeout(make_client) -> None:
    fake = FakeA2A(dialect="v1", reply_shape="message", delay_s=0.2)
    http = make_client(fake)
    card = _v1_card()

    with pytest.raises(BridgeTimeoutError):
        await send_message(card, "ping", http=http, timeout_s=0.05)


async def test_send_message_every_request_carries_a_fresh_message_id(make_client) -> None:
    fake = FakeA2A(dialect="v1", reply_shape="message")
    http = make_client(fake)
    card = _v1_card()

    await send_message(card, "one", http=http)
    await send_message(card, "two", http=http)

    rpc_requests = [r for r in fake.requests if r["method"] == "POST"]
    ids = [r["body"]["params"]["message"]["messageId"] for r in rpc_requests]
    assert len(ids) == 2
    assert ids[0] != ids[1]
    for message_id in ids:
        _assert_valid_uuid4(message_id)


# ---------------------------------------------------------------------------
# WIRE-2/4 — send, v0.3 fallback wire
# ---------------------------------------------------------------------------


async def test_send_message_v0_3_wire_shape_method_no_version_header_role_parts(
    make_client,
) -> None:
    fake = FakeA2A(dialect="v0_3", reply_shape="message")
    http = make_client(fake)
    card = _v0_3_card()

    reply = await send_message(card, "hello there", http=http)

    rpc_requests = [r for r in fake.requests if r["method"] == "POST"]
    assert len(rpc_requests) == 1
    req = rpc_requests[0]
    assert "a2a-version" not in req["headers"]
    assert req["body"]["method"] == "message/send"
    message = req["body"]["params"]["message"]
    assert message["role"] == "user"
    assert message["parts"] == [{"kind": "text", "text": "hello there"}]
    assert reply.text == "fake reply text"


async def test_send_message_v0_3_message_result_parsed(make_client) -> None:
    fake = FakeA2A(dialect="v0_3", reply_shape="message", context_id="ctx-v03-1")
    http = make_client(fake)
    card = _v0_3_card()

    reply = await send_message(card, "ping", http=http)

    assert reply.text == "fake reply text"
    assert reply.context_id == "ctx-v03-1"


async def test_send_message_v0_3_task_result_parsed(make_client) -> None:
    fake = FakeA2A(dialect="v0_3", reply_shape="task")
    http = make_client(fake)
    card = _v0_3_card()

    reply = await send_message(card, "ping", http=http)

    assert reply.text == "artifact reply text"


# ---------------------------------------------------------------------------
# CONV-1/2 — contextId roundtrip
# ---------------------------------------------------------------------------


async def test_send_message_no_context_id_omits_contextId_returns_upstream_generated(
    make_client,
) -> None:
    fake = FakeA2A(dialect="v1", reply_shape="message", context_id="ctx-generated-xyz")
    http = make_client(fake)
    card = _v1_card()

    reply = await send_message(card, "ping", http=http)

    rpc_requests = [r for r in fake.requests if r["method"] == "POST"]
    assert "contextId" not in rpc_requests[-1]["body"]["params"]["message"]
    assert reply.context_id == "ctx-generated-xyz"


async def test_send_message_with_context_id_sent_verbatim_and_echoed_back(
    make_client,
) -> None:
    fake = FakeA2A(dialect="v1", reply_shape="message")
    http = make_client(fake)
    card = _v1_card()

    reply = await send_message(card, "ping", http=http, context_id="c-7")

    rpc_requests = [r for r in fake.requests if r["method"] == "POST"]
    assert rpc_requests[-1]["body"]["params"]["message"]["contextId"] == "c-7"
    assert reply.context_id == "c-7"
