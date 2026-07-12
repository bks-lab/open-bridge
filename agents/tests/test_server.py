"""``build_app()`` composes a plain Starlette A2A app against a2a-sdk 1.x.

a2a-sdk 1.x has no ``A2AStarletteApplication`` wrapper; the runtime hand-wires
the JSON-RPC + agent-card + health routes. These assert the app composes and
imports cleanly against the pinned (newest) SDK, without touching the network,
and pin the SDK floor so a downgrade below the current-newest turns CI red.
"""
from __future__ import annotations

from importlib.metadata import version

from starlette.applications import Starlette

from a2a.utils import DEFAULT_RPC_URL

from _runtime.config import load_agent_config
from _runtime.server import build_app


def _cfg():
    return load_agent_config("_template", environment="test")


def test_build_app_returns_starlette_with_core_routes():
    app = build_app(_cfg())
    assert isinstance(app, Starlette)
    paths = {getattr(r, "path", None) for r in app.routes}
    assert DEFAULT_RPC_URL in paths     # JSON-RPC surface (message/send, tasks/*)
    assert "/health" in paths


def test_runs_against_newest_a2a_sdk():
    # The runtime targets A2A spec v1.0 via a2a-sdk 1.x. Pin the floor to the
    # current newest (1.1.0, 2026-05-29) so a downgrade below it fails CI.
    parts = tuple(int(x) for x in version("a2a-sdk").split(".")[:3])
    assert parts >= (1, 1, 0), f"a2a-sdk must be >=1.1.0 (A2A v1.0), got {parts}"
