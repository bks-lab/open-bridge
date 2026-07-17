"""A2A v1.0 AgentCard conformance for the Bridge-Agent runtime (hermetic).

Locks the wire-level shape A2A spec v1.0 requires, so a refactor or an SDK bump
can't silently regress it: transport lives in ``supported_interfaces[]`` (the
v1.0 mechanism that replaced a single top-level ``url``), each binding JSON-RPC,
and the card is served at the canonical ``/.well-known/agent-card.json`` (the
legacy ``/.well-known/agent.json`` alias is kept for v0.3 clients).

No network, no ``claude`` subprocess: build the card, serve it, and inspect the routes.

**Why some of these assert on served BYTES, not on the built object.** The card the SDK
serialises is not simply the card we built: without an explicit ``protocol_version`` on
the interface, the v0_3-compat layer emits the card in the LEGACY dialect (top-level
``protocolVersion: "0.3"`` + ``preferredTransport``, no version on the interface). That
difference is invisible in ``build_agent_card()``'s return value, so an object-only test
can never see it — and didn't: this suite claimed "v1.0 conformance" while every Bridge
agent served 0.3 to the world. A peer reads the bytes; so do we.
"""
from __future__ import annotations

from a2a.utils import TransportProtocol
from a2a.utils.constants import PROTOCOL_VERSION_CURRENT
from starlette.testclient import TestClient

from _runtime.card import build_agent_card
from _runtime.config import load_agent_config
from _runtime.server import LEGACY_AGENT_CARD_PATH, build_app

WELL_KNOWN = "/.well-known/agent-card.json"


def _cfg():
    return load_agent_config("_template", environment="test")


def test_card_declares_v1_supported_interfaces():
    card = build_agent_card(_cfg())
    assert card.supported_interfaces, "v1.0 card must expose supported_interfaces[]"
    iface = card.supported_interfaces[0]
    assert iface.protocol_binding == TransportProtocol.JSONRPC
    assert iface.url.endswith("/")


def test_card_has_all_v1_required_fields():
    card = build_agent_card(_cfg())
    assert card.name and card.description and card.version
    assert card.capabilities.streaming is True
    assert card.default_input_modes == ["text"]
    assert card.default_output_modes == ["text"]
    # a2a-sdk 1.x cards are protobuf: skills is a repeated field, not a py list.
    assert len(card.skills) >= 1


def test_served_card_advertises_the_current_protocol_version():
    """The regression this whole file was supposed to prevent, and missed.

    A v1.0 client reads the protocol version off ``supportedInterfaces[]``. If we don't
    put it there, the compat layer serves the 0.3 dialect instead — and the peer either
    reads "0.3" or, if it only knows the v1.0 location, nothing at all. Both happened in
    production: every Bridge agent advertised 0.3, and a sibling agent that had moved to
    v1.0 became unreachable to its 0.3-only mesh clients.
    """
    client = TestClient(build_app(_cfg()))
    card = client.get(WELL_KNOWN).json()
    iface = card["supportedInterfaces"][0]
    assert iface["protocolVersion"] == PROTOCOL_VERSION_CURRENT
    assert iface["protocolBinding"] == "JSONRPC"


def test_served_card_is_not_the_v0_3_dialect():
    """The 0.3 dialect is recognisable by where it puts the interface descriptor.

    Asserted as its own case because the failure is silent: a 0.3-dialect card is still
    valid JSON, still 200s, still passes every object-level check above.
    """
    client = TestClient(build_app(_cfg()))
    card = client.get(WELL_KNOWN).json()
    assert card.get("protocolVersion") != "0.3", "served card fell back to the 0.3 dialect"


def test_legacy_card_path_still_serves_for_v0_3_clients():
    """Advertising v1.0 must not evict 0.3 clients — the alias and the compat layer stay."""
    client = TestClient(build_app(_cfg()))
    assert client.get(LEGACY_AGENT_CARD_PATH).status_code == 200


def test_card_served_at_canonical_well_known_path():
    app = build_app(_cfg())
    paths = {getattr(r, "path", None) for r in app.routes}
    assert WELL_KNOWN in paths                 # v1.0 canonical discovery path
    assert LEGACY_AGENT_CARD_PATH in paths     # legacy alias for v0.3 clients
    assert "/health" in paths
