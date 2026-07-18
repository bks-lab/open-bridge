"""Shared test infra: a configurable in-process fake A2A endpoint (SPEC.md § 7).

``FakeA2A`` is a tiny Starlette app serving the two routes a real A2A agent
exposes:

- ``GET  /.well-known/agent-card.json`` — the AgentCard, in either wire dialect.
- ``POST /rpc``                          — JSON-RPC 2.0, in either wire dialect.

It is driven entirely in-process via ``httpx.ASGITransport(app=fake.app)`` —
no real socket, no real network — and every request it receives (headers +
parsed JSON body) is appended to ``.requests`` so tests can assert on exactly
what the client under test sent over the wire.

No tests live in this module (SPEC.md § 7: "shared infra, no tests").

Constructor knobs (pinned, SPEC.md § 7)
----------------------------------------
``dialect``, ``reply_shape``, ``context_id``, ``delay_s``, ``require_token`` —
exactly the parameters SPEC.md pins for ``FakeA2A.__init__``.

Extra post-construction test knobs (NOT part of the pinned constructor;
plain public attributes a test may mutate before firing a request)
--------------------------------------------------------------------
- ``card_override``: when set to a dict, ``.card()`` returns it verbatim
  instead of the dialect's canned card. Needed for the #121 regression cases
  in SPEC.md § 7 (a v1-shaped card whose JSONRPC interface entry says
  ``protocolVersion: "0.3"``; a GRPC-only card) — shapes that do not
  correspond to either canned ``dialect`` value and therefore cannot be
  selected through the pinned constructor alone.
- ``include_artifacts``: when the fake replies with a completed
  ``reply_shape="task"``, set this to ``False`` to omit ``artifacts`` and
  exercise the WIRE-3 status.message fallback path. Defaults to ``True``.

Both are additive (no change to the pinned constructor signature or to
``.card()``'s pinned return type) — flagged here, and in the build notes,
so the SPEC owner can fold them into § 7 explicitly if desired.
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from gateway.a2a_client import Dialect

ReplyShape = Literal[
    "message", "task", "input_required", "failed", "jsonrpc_error", "malformed"
]

# The fake always advertises (and answers on) this absolute URL — tests wire
# their httpx.AsyncClient to base_url="http://a2a.test" per SPEC.md § 7, so a
# NormalizedCard.jsonrpc_url built from this card is directly POST-able
# through that same client.
_RPC_URL = "http://a2a.test/rpc"


class FakeA2A:
    """Configurable in-process A2A endpoint (Starlette app).

    Serves GET /.well-known/agent-card.json + POST /rpc in either dialect.
    """

    def __init__(
        self,
        *,
        dialect: Dialect = "v1",
        reply_shape: ReplyShape = "task",
        context_id: str = "ctx-fake-1",
        delay_s: float = 0.0,
        require_token: str | None = None,
    ) -> None:
        self.dialect = dialect
        self.reply_shape = reply_shape
        self.context_id = context_id
        self.delay_s = delay_s
        self.require_token = require_token

        self.requests: list[dict[str, Any]] = []

        # Extra test knobs — see module docstring.
        self.card_override: dict[str, Any] | None = None
        self.include_artifacts: bool = True

        self.app: Starlette = self._build_app()

    # -- public API (pinned) -------------------------------------------------

    def card(self) -> dict[str, Any]:
        """Dialect-correct AgentCard JSON (SPEC.md § 6 card dialect table)."""
        if self.card_override is not None:
            return self.card_override

        if self.dialect == "v1":
            return {
                "name": "fake-bridge",
                "description": "Fake A2A bridge for hermetic tests.",
                "capabilities": {"extendedAgentCard": True},
                "skills": [],
                "supportedInterfaces": [
                    {
                        "url": _RPC_URL,
                        "protocolBinding": "JSONRPC",
                        "protocolVersion": "1.0",
                    }
                ],
            }

        # v0_3 — legacy shape: no supportedInterfaces, no protocolVersion at
        # all (CARD-3: a missing version is treated as fully 0.3).
        return {
            "name": "fake-bridge",
            "description": "Fake A2A bridge for hermetic tests.",
            "url": _RPC_URL,
            "capabilities": {},
            "skills": [],
        }

    # -- ASGI wiring -----------------------------------------------------------

    def _build_app(self) -> Starlette:
        return Starlette(
            routes=[
                Route(
                    "/.well-known/agent-card.json",
                    self._card_endpoint,
                    methods=["GET"],
                ),
                Route("/rpc", self._rpc_endpoint, methods=["POST"]),
            ]
        )

    def _check_auth(self, request: Request) -> JSONResponse | None:
        """Return a 401 response iff require_token is set and unmet, else None."""
        if self.require_token is None:
            return None
        header = request.headers.get("authorization")
        if header != f"Bearer {self.require_token}":
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return None

    @staticmethod
    def _capture(request: Request, *, body: Any) -> dict[str, Any]:
        return {
            "method": request.method,
            "path": request.url.path,
            "headers": {k.lower(): v for k, v in request.headers.items()},
            "body": body,
        }

    async def _card_endpoint(self, request: Request) -> JSONResponse:
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        self.requests.append(self._capture(request, body=None))
        auth_error = self._check_auth(request)
        if auth_error is not None:
            return auth_error
        return JSONResponse(self.card())

    async def _rpc_endpoint(self, request: Request) -> JSONResponse:
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        body = await request.json()
        self.requests.append(self._capture(request, body=body))
        auth_error = self._check_auth(request)
        if auth_error is not None:
            return auth_error
        return JSONResponse(self._build_rpc_response(body))

    # -- reply construction (SPEC.md § 6 wire reference) ------------------------

    def _build_rpc_response(self, body: dict[str, Any]) -> dict[str, Any]:
        req_id = body.get("id", "unknown")

        if self.reply_shape == "jsonrpc_error":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32000, "message": "simulated upstream failure"},
            }

        if self.reply_shape == "malformed":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"bogus": "shape matching neither message nor task"},
            }

        message = body.get("params", {}).get("message", {})
        incoming_context_id = message.get("contextId")
        context_id = (
            incoming_context_id if incoming_context_id is not None else self.context_id
        )
        v1 = self.dialect == "v1"

        if self.reply_shape == "message":
            text = "fake reply text"
            if v1:
                result: dict[str, Any] = {
                    "message": {
                        "role": "ROLE_AGENT",
                        "parts": [{"text": text}],
                        "contextId": context_id,
                    }
                }
            else:
                result = {
                    "kind": "message",
                    "role": "agent",
                    "parts": [{"kind": "text", "text": text}],
                    "contextId": context_id,
                }
            return {"jsonrpc": "2.0", "id": req_id, "result": result}

        # Task-shaped replies: task / input_required / failed.
        task = self._build_task(context_id=context_id, v1=v1)
        result = {"task": task} if v1 else {"kind": "task", **task}
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    def _build_task(self, *, context_id: str, v1: bool) -> dict[str, Any]:
        if self.reply_shape == "task":
            state = "TASK_STATE_COMPLETED" if v1 else "completed"
            status_text = "status message text"
        elif self.reply_shape == "input_required":
            state = "TASK_STATE_INPUT_REQUIRED" if v1 else "input-required"
            status_text = "please provide more info"
        elif self.reply_shape == "failed":
            state = "TASK_STATE_FAILED" if v1 else "failed"
            status_text = "upstream task failed"
        else:
            raise ValueError(f"unsupported task reply_shape: {self.reply_shape!r}")

        if v1:
            status_message = {"role": "ROLE_AGENT", "parts": [{"text": status_text}]}
        else:
            status_message = {
                "kind": "message",
                "parts": [{"kind": "text", "text": status_text}],
            }
        status = {"state": state, "message": status_message}

        artifacts: list[dict[str, Any]] = []
        if self.reply_shape == "task" and self.include_artifacts:
            artifacts_text = "artifact reply text"
            if v1:
                artifacts = [{"artifactId": "a-1", "parts": [{"text": artifacts_text}]}]
            else:
                artifacts = [{"parts": [{"kind": "text", "text": artifacts_text}]}]

        return {
            "id": "t-1",
            "contextId": context_id,
            "status": status,
            "artifacts": artifacts,
        }
