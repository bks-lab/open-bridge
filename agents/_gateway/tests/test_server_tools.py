"""Tests for GatewayService tool logic (SPEC.md § 7: TIER-4/5, ERR-1..4,
CONC-1/2, CARD-6) — hitting the service directly, no MCP plumbing.

Hermetic: every upstream is a FakeA2A driven through httpx.ASGITransport; the
captured ``FakeA2A.requests`` list is the wire-level truth used to assert what
was (and, for tier_denied, was NOT) sent upstream.
"""

from __future__ import annotations

import asyncio

from conftest import CARD_URL, make_registry
from fake_a2a import FakeA2A
from gateway.registry import BridgeEntry
from gateway.tiers import AccessTier


def _card_gets(fake: FakeA2A) -> int:
    return len(
        [r for r in fake.requests if r["path"] == "/.well-known/agent-card.json"]
    )


def _rpc_posts(fake: FakeA2A) -> int:
    return len([r for r in fake.requests if r["path"] == "/rpc"])


# ---------------------------------------------------------------------------
# list_bridges — TIER-4 filtering + ok envelope
# ---------------------------------------------------------------------------


async def test_list_bridges_anonymous_filters_to_anonymous_entries(make_service):
    service = make_service(FakeA2A())

    result = await service.list_bridges(AccessTier.ANONYMOUS)

    assert result["ok"] is True
    assert result["tier"] == "anonymous"
    assert result["error"] is None
    assert [b["id"] for b in result["bridges"]] == ["open-fake"]
    assert result["bridges"][0]["min_tier"] == "anonymous"
    assert result["bridges"][0]["description"] == "Anonymous-tier fake bridge."


async def test_list_bridges_authenticated_includes_all_entries(make_service):
    service = make_service(FakeA2A())

    result = await service.list_bridges(AccessTier.AUTHENTICATED)

    assert result["ok"] is True
    assert result["tier"] == "authenticated"
    assert result["error"] is None
    assert sorted(b["id"] for b in result["bridges"]) == ["open-fake", "secure-fake"]


# ---------------------------------------------------------------------------
# get_bridge_card — CARD-6 tiered detail + TIER-5 denial
# ---------------------------------------------------------------------------


async def test_get_bridge_card_anonymous_returns_summary_without_raw_card(
    make_service,
):
    fake = FakeA2A()
    service = make_service(fake)

    result = await service.get_bridge_card(AccessTier.ANONYMOUS, "open-fake")

    assert result["ok"] is True
    assert result["bridge"] == "open-fake"
    assert result["name"] == "fake-bridge"
    assert result["description"] == "Fake A2A bridge for hermetic tests."
    assert result["protocol_version"] == "1.0"
    assert result["dialect"] == "v1"
    assert result["skills"] == []
    assert result["extended"] is False
    assert result["card"] is None
    assert result["error"] is None


async def test_get_bridge_card_authenticated_returns_full_raw_card(make_service):
    fake = FakeA2A()
    service = make_service(fake)

    result = await service.get_bridge_card(AccessTier.AUTHENTICATED, "open-fake")

    assert result["ok"] is True
    assert result["extended"] is True
    assert result["card"] == fake.card()


async def test_get_bridge_card_tier_denied_as_anonymous_never_contacts_upstream(
    make_service,
):
    fake = FakeA2A()
    service = make_service(fake)

    result = await service.get_bridge_card(AccessTier.ANONYMOUS, "secure-fake")

    assert result["ok"] is False
    assert result["error"] is not None
    assert result["error"]["code"] == "tier_denied"
    assert result["card"] is None
    assert result["name"] is None
    # TIER-5: the upstream bridge must NOT have been contacted at all.
    assert fake.requests == []


# ---------------------------------------------------------------------------
# ask_bridge — happy path, unknown bridge, tier denial
# ---------------------------------------------------------------------------


async def test_ask_bridge_happy_path_returns_text_and_conversation(make_service):
    fake = FakeA2A()  # v1 dialect, completed-task reply with artifacts
    service = make_service(fake)

    result = await service.ask_bridge(AccessTier.ANONYMOUS, "open-fake", "hello")

    assert result["ok"] is True
    assert result["bridge"] == "open-fake"
    assert result["text"] == "artifact reply text"
    assert result["conversation"] == "ctx-fake-1"
    assert result["error"] is None


async def test_ask_bridge_unknown_bridge_returns_unknown_bridge_envelope(
    make_service,
):
    fake = FakeA2A()
    service = make_service(fake)

    result = await service.ask_bridge(AccessTier.AUTHENTICATED, "no-such", "hello")

    assert result["ok"] is False
    assert result["error"] is not None
    assert result["error"]["code"] == "unknown_bridge"
    assert result["text"] is None
    assert result["conversation"] is None
    assert fake.requests == []


async def test_ask_bridge_tier_denied_as_anonymous_never_contacts_upstream(
    make_service,
):
    fake = FakeA2A()
    service = make_service(fake)

    result = await service.ask_bridge(AccessTier.ANONYMOUS, "secure-fake", "hello")

    assert result["ok"] is False
    assert result["error"] is not None
    assert result["error"]["code"] == "tier_denied"
    assert result["text"] is None
    assert fake.requests == []


# ---------------------------------------------------------------------------
# busy — CONC-1/2 fail-fast + slot release, ERR-3 retry hint
# ---------------------------------------------------------------------------


async def test_ask_bridge_concurrent_over_limit_fails_fast_busy_then_releases_slot(
    make_service, busy_config
):
    fake = FakeA2A()
    service = make_service(fake, config=busy_config)

    # Warm the card cache with a fast ask so the delayed ask below holds its
    # concurrency slot inside the RPC call, not inside a card fetch.
    warmup = await service.ask_bridge(AccessTier.ANONYMOUS, "open-fake", "warmup")
    assert warmup["ok"] is True

    fake.delay_s = 0.3
    in_flight = asyncio.create_task(
        service.ask_bridge(AccessTier.ANONYMOUS, "open-fake", "slow one")
    )
    await asyncio.sleep(0.05)  # let the task acquire the single slot

    busy = await service.ask_bridge(AccessTier.ANONYMOUS, "open-fake", "second")
    assert busy["ok"] is False
    assert busy["error"] is not None
    assert busy["error"]["code"] == "busy"
    assert busy["error"]["retry_after_s"] == busy_config.busy_retry_after_s
    assert busy["text"] is None

    first = await in_flight
    assert first["ok"] is True

    # CONC-2: the slot is released on completion — a new ask succeeds.
    fake.delay_s = 0.0
    after = await service.ask_bridge(AccessTier.ANONYMOUS, "open-fake", "third")
    assert after["ok"] is True


# ---------------------------------------------------------------------------
# upstream failures as envelopes — ERR-2/3/4
# ---------------------------------------------------------------------------


async def test_ask_bridge_upstream_jsonrpc_error_returns_upstream_error_envelope(
    make_service,
):
    fake = FakeA2A(reply_shape="jsonrpc_error")
    service = make_service(fake)

    result = await service.ask_bridge(AccessTier.ANONYMOUS, "open-fake", "hello")

    assert result["ok"] is False
    assert result["error"] is not None
    assert result["error"]["code"] == "upstream_error"
    # ERR-3: only "busy" carries a retry hint.
    assert result["error"]["retry_after_s"] is None
    assert result["text"] is None
    assert result["conversation"] is None


async def test_ask_bridge_error_never_contains_credential_value(
    make_service, monkeypatch
):
    secret = "secret-cred-value-123"
    monkeypatch.setenv("FAKE_BRIDGE_CRED", secret)
    fake = FakeA2A(require_token="a-different-upstream-token")
    registry = make_registry(
        BridgeEntry(
            id="token-fake",
            card_url=CARD_URL,
            description="Token-mode fake bridge.",
            auth_mode="token",
            credential_ref="FAKE_BRIDGE_CRED",
        )
    )
    service = make_service(fake, registry=registry)

    result = await service.ask_bridge(AccessTier.ANONYMOUS, "token-fake", "hello")

    assert result["ok"] is False
    assert result["error"] is not None
    assert result["error"]["code"] == "unauthorized"
    # ERR-4: no credential material anywhere in the returned envelope.
    assert secret not in repr(result)


# ---------------------------------------------------------------------------
# card cache — SPEC § 2 decision 6
# ---------------------------------------------------------------------------


async def test_ask_bridge_card_cache_fetches_card_once_for_two_asks(make_service):
    fake = FakeA2A()
    service = make_service(fake)  # default card_cache_ttl_s=300

    first = await service.ask_bridge(AccessTier.ANONYMOUS, "open-fake", "one")
    second = await service.ask_bridge(AccessTier.ANONYMOUS, "open-fake", "two")

    assert first["ok"] is True
    assert second["ok"] is True
    assert _card_gets(fake) == 1
    assert _rpc_posts(fake) == 2


async def test_ask_bridge_card_cache_ttl_zero_fetches_card_every_ask(
    make_service, no_cache_config
):
    fake = FakeA2A()
    service = make_service(fake, config=no_cache_config)

    first = await service.ask_bridge(AccessTier.ANONYMOUS, "open-fake", "one")
    second = await service.ask_bridge(AccessTier.ANONYMOUS, "open-fake", "two")

    assert first["ok"] is True
    assert second["ok"] is True
    assert _card_gets(fake) == 2
