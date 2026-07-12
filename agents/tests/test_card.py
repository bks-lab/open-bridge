"""A2A v1.0 AgentCard conformance for the Bridge-Agent runtime (hermetic).

Locks the wire-level shape A2A spec v1.0 requires, so a refactor or an SDK bump
can't silently regress it: transport lives in ``supported_interfaces[]`` (the
v1.0 mechanism that replaced a single top-level ``url``), each binding JSON-RPC,
and the card is served at the canonical ``/.well-known/agent-card.json`` (the
legacy ``/.well-known/agent.json`` alias is kept for v0.3 clients).

No network, no ``claude`` subprocess: build the card and inspect the routes.
"""
from __future__ import annotations

from a2a.utils import TransportProtocol

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


def test_card_served_at_canonical_well_known_path():
    app = build_app(_cfg())
    paths = {getattr(r, "path", None) for r in app.routes}
    assert WELL_KNOWN in paths                 # v1.0 canonical discovery path
    assert LEGACY_AGENT_CARD_PATH in paths     # legacy alias for v0.3 clients
    assert "/health" in paths
