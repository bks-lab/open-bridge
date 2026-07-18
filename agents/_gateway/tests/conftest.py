"""Shared fixtures for the server-layer test files (SPEC.md § 7, Agent D scope).

Used by test_config.py / test_server_tools.py / test_integration_mcp.py.
Nothing here is autouse and no fixture name collides with the module-level
test files (test_registry / test_tiers / test_a2a_client), so the pre-existing
suite is untouched by this conftest.

All fixtures are hermetic: FakeA2A is driven in-process via
``httpx.ASGITransport`` — no real ports, no network. Tokens are dummy test
strings, never real secrets (CFG-2).
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from fake_a2a import FakeA2A
from gateway.config import GatewayConfig
from gateway.registry import BridgeEntry, Registry
from gateway.server import GatewayService
from gateway.tiers import TierResolver

# Dummy client bearer token for the gateway's own auth hop (never a secret).
GOOD_TOKEN = "test-token-good"

# FakeA2A serves its card here; tests wire httpx clients with
# base_url="http://a2a.test" so this absolute URL resolves in-process.
CARD_URL = "http://a2a.test/.well-known/agent-card.json"


def make_registry(*entries: BridgeEntry) -> Registry:
    """Build a Registry directly from BridgeEntry values (no YAML round-trip)."""
    return Registry(bridges=tuple(entries))


def two_tier_registry() -> Registry:
    """One anonymous-visible and one authenticated-only bridge, same fake card."""
    return make_registry(
        BridgeEntry(
            id="open-fake",
            card_url=CARD_URL,
            description="Anonymous-tier fake bridge.",
        ),
        BridgeEntry(
            id="secure-fake",
            card_url=CARD_URL,
            description="Authenticated-only fake bridge.",
            min_tier="authenticated",
        ),
    )


@pytest.fixture
def default_config() -> GatewayConfig:
    return GatewayConfig()


@pytest.fixture
def busy_config() -> GatewayConfig:
    """Single ask slot per bridge + a distinctive busy retry hint (CONC-1, ERR-3)."""
    return GatewayConfig(per_bridge_concurrency=1, busy_retry_after_s=7.5)


@pytest.fixture
def no_cache_config() -> GatewayConfig:
    """Card cache disabled (SPEC § 3: ``card_cache_ttl_s: 0`` disables)."""
    return GatewayConfig(card_cache_ttl_s=0.0)


@pytest.fixture
async def make_http():
    """Factory: a fresh httpx.AsyncClient wired onto a FakeA2A's ASGI app.

    Clients are closed at teardown so no async generators leak across tests.
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


@pytest.fixture
def make_resolver() -> Callable[..., TierResolver]:
    """Factory: TierResolver over a registry with the dummy client token list."""

    def _make(
        registry: Registry, tokens: frozenset[str] = frozenset({GOOD_TOKEN})
    ) -> TierResolver:
        return TierResolver(registry=registry, tokens=tokens)

    return _make


@pytest.fixture
def make_service(make_http, make_resolver) -> Callable[..., GatewayService]:
    """Factory: a GatewayService wired to one FakeA2A over an in-process client."""

    def _make(
        fake: FakeA2A,
        *,
        registry: Registry | None = None,
        config: GatewayConfig | None = None,
        tokens: frozenset[str] = frozenset({GOOD_TOKEN}),
    ) -> GatewayService:
        active_registry = registry if registry is not None else two_tier_registry()
        return GatewayService(
            config=config if config is not None else GatewayConfig(),
            registry=active_registry,
            resolver=make_resolver(active_registry, tokens),
            http=make_http(fake),
        )

    return _make
