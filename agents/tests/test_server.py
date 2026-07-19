"""``build_app()`` composes a plain Starlette A2A app against a2a-sdk 1.x.

a2a-sdk 1.x has no ``A2AStarletteApplication`` wrapper; the runtime hand-wires
the JSON-RPC + agent-card + health routes. These assert the app composes and
imports cleanly against the pinned (newest) SDK, without touching the network,
and pin the SDK floor so a downgrade below the current-newest turns CI red.
"""
from __future__ import annotations

from importlib.metadata import version

from starlette.applications import Starlette
from starlette.testclient import TestClient

from a2a.utils import DEFAULT_RPC_URL

from _runtime.config import load_agent_config
from _runtime.server import _restore_a2a_error_code, build_app


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


# --- version-mismatch reporting on the v0.3 compat path -----------------------
#
# A 0.3 method name paired with a non-0.x ``A2A-Version`` header trips
# ``@validate_version`` inside the compat adapter. The adapter's broad
# ``except Exception`` (jsonrpc_adapter.py:141-145) re-raises it as a generic
# InternalError, so the -32009 the spec defines — and the typed ``data`` details
# the v1 path emits — are lost. These pin the repair.


def _version_error(client, method, params, header):
    response = client.post(
        DEFAULT_RPC_URL,
        json={"jsonrpc": "2.0", "id": "1", "method": method, "params": params},
        headers={"A2A-Version": header},
    )
    return response.json()["error"]


def test_v0_3_version_mismatch_matches_the_v1_path():
    """Parity, asserted without naming a single literal.

    Both legs below are the same class of error — a version the handler cannot
    speak — so the wire shape must be identical whichever dialect the client
    used. Comparing the two paths against each other (rather than against
    hardcoded values) is deliberate: this test cannot drift when the SDK changes
    its message text, its detail schema or its code, which is exactly the
    failure mode that produced the bug (an exact-match table against a message
    that interpolates version strings).
    """
    client = TestClient(build_app(_cfg()))
    # v1 method + a 0.3 header -> the v1 path, which reports this correctly.
    # Params are the proto GetTaskRequest's; they must parse, because ParseDict
    # runs before the version check and a bad field would mask it as -32602.
    v1 = _version_error(client, "GetTask", {"id": "x"}, "0.3")
    # 0.3 method + a 1.0 header -> the compat path, which did not.
    v0_3 = _version_error(client, "tasks/get", {"id": "x"}, "1.0")

    assert v0_3["code"] == v1["code"]
    assert v0_3["data"][0]["reason"] == v1["data"][0]["reason"]


def test_v0_3_version_mismatch_reports_32009_with_reason():
    """The absolute pin. Parity alone would also be satisfied by two matching
    wrongs, so anchor the shared value at what the A2A spec actually defines."""
    client = TestClient(build_app(_cfg()))
    err = _version_error(client, "tasks/get", {"id": "x"}, "1.0")

    assert err["code"] == -32009
    assert err["data"][0]["reason"] == "VERSION_NOT_SUPPORTED"


def test_exact_match_restoration_leaves_data_untouched():
    """The five exact-match codes are already correct on the wire. Restoring a
    code must not start rewriting their ``data`` as a side effect."""
    payload = {"error": {"code": -32603, "message": "Task not found", "data": None}}

    assert _restore_a2a_error_code(payload) is True
    assert payload["error"]["code"] == -32001
    assert payload["error"]["data"] is None


def test_genuine_internal_error_is_not_reported_as_a_version_error():
    """The guard against an over-broad rule. Mislabelling a real internal error
    as -32009 is worse than the original bug: the client trusts the diagnosis."""
    payload = {"error": {"code": -32603, "message": "Internal error", "data": None}}

    assert _restore_a2a_error_code(payload) is False
    assert payload["error"]["code"] == -32603
