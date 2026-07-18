"""A2A client: dual-dialect card reader + dual-wire sender (SPEC CARD/WIRE/CONV).

Speaks the native v1.0 wire (``SendMessage``, ``A2A-Version: 1.0``, proto enum
role names) with a v0.3 fallback (``message/send``, kind-discriminated parts).
The card reader reads BOTH dialect locations — the #121 lesson: a reader that
checks only one location breaks silently the moment the peer upgrades.

No a2a-sdk dependency (SPEC §2 decision 1): raw httpx JSON-RPC, wire shapes
pinned in SPEC §6. ``http`` is always injected — production passes a shared
``httpx.AsyncClient``, tests pass one wired to an in-process ASGI transport.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from gateway.errors import (
    BridgeTimeoutError,
    BridgeUnreachableError,
    UnauthorizedError,
    UpstreamError,
)

Dialect = Literal["v1", "v0_3"]

# WIRE-3/4: task states that resolve to a final answer (artifacts, or the
# status message as a fallback when no artifacts are attached).
_COMPLETED_STATES = frozenset({"TASK_STATE_COMPLETED", "completed"})
# WIRE-3: task states where the conversation continues under the same
# contextId — the caller is expected to reply with another ask_bridge call.
_CONTINUE_STATES = frozenset(
    {
        "TASK_STATE_INPUT_REQUIRED",
        "input-required",
        "TASK_STATE_AUTH_REQUIRED",
        "auth-required",
    }
)
# WIRE-3: terminal failure states — surfaced as UpstreamError, never a reply.
_FAILURE_STATES = frozenset(
    {
        "TASK_STATE_FAILED",
        "failed",
        "TASK_STATE_CANCELED",
        "canceled",
        "TASK_STATE_REJECTED",
        "rejected",
    }
)

_UNAUTHORIZED_STATUS_CODES = frozenset({401, 403})


@dataclass(frozen=True)
class NormalizedCard:
    name: str
    description: str
    protocol_version: str
    jsonrpc_url: str
    dialect: Dialect
    skills: tuple[dict[str, Any], ...]
    raw: dict[str, Any]


@dataclass(frozen=True)
class AgentReply:
    text: str
    context_id: str | None
    raw: dict[str, Any]


async def fetch_card(
    card_url: str,
    *,
    http: httpx.AsyncClient,
    token: str | None = None,
    timeout_s: float = 10.0,
) -> NormalizedCard:
    """Fetch + normalize an AgentCard, reading both wire dialect locations.

    CARD-1..CARD-5: GETs ``card_url`` with ``Accept: application/json`` (plus
    a bearer header iff ``token`` is given), then picks the JSONRPC endpoint
    either from ``supportedInterfaces[]`` (v1-shaped cards) or the legacy
    top-level ``url`` (CARD-2), and derives the wire dialect to speak from the
    selected entry's ``protocolVersion`` (CARD-3).
    """
    headers = {"Accept": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"

    try:
        # httpx.Timeout is passed on the request so a real network transport
        # enforces it; ASGITransport (used by the hermetic test suite) calls
        # the app in-process and does not honor it, so asyncio.wait_for is the
        # belt-and-suspenders enforcement that makes a slow fake reliably
        # trigger BridgeTimeoutError too.
        response = await asyncio.wait_for(
            http.get(card_url, headers=headers, timeout=httpx.Timeout(timeout_s)),
            timeout=timeout_s,
        )
    except (httpx.TimeoutException, TimeoutError) as exc:
        raise BridgeTimeoutError(f"card fetch timed out: {card_url}") from exc
    except httpx.TransportError as exc:
        raise BridgeUnreachableError(f"card fetch unreachable: {card_url}") from exc

    if response.status_code in _UNAUTHORIZED_STATUS_CODES:
        raise UnauthorizedError(
            f"card fetch unauthorized (HTTP {response.status_code}): {card_url}"
        )
    if not (200 <= response.status_code < 300):
        raise BridgeUnreachableError(
            f"card fetch failed (HTTP {response.status_code}): {card_url}"
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise UpstreamError(f"card response is not valid JSON: {card_url}") from exc

    jsonrpc_url, protocol_version = _select_jsonrpc_endpoint(data)
    dialect = _dialect_from_protocol_version(protocol_version)

    return NormalizedCard(
        name=data.get("name", ""),
        description=data.get("description", ""),
        protocol_version=protocol_version if protocol_version is not None else "0.3",
        jsonrpc_url=jsonrpc_url,
        dialect=dialect,
        skills=tuple(data.get("skills", [])),
        raw=data,
    )


def _select_jsonrpc_endpoint(data: dict[str, Any]) -> tuple[str, str | None]:
    """CARD-2: pick the JSONRPC endpoint + its declared protocolVersion.

    Prefers a non-empty ``supportedInterfaces[]`` entry (per-entry version —
    the #121 lesson: presence of ``supportedInterfaces`` does not itself mean
    v1). Falls back to the legacy top-level ``url``/``protocolVersion`` when
    ``supportedInterfaces`` is absent or empty. Raises ``UpstreamError``
    (CARD-4) when no JSONRPC endpoint can be found anywhere.
    """
    supported_interfaces = data.get("supportedInterfaces")
    if supported_interfaces:
        for entry in supported_interfaces:
            if entry.get("protocolBinding") == "JSONRPC" and entry.get("url"):
                return entry["url"], entry.get("protocolVersion")
        raise UpstreamError(
            "card has no JSONRPC entry in supportedInterfaces (GRPC-only or "
            "malformed card)"
        )

    url = data.get("url")
    preferred_transport = data.get("preferredTransport")
    if preferred_transport is not None and preferred_transport != "JSONRPC":
        raise UpstreamError(
            f"legacy card preferredTransport is not JSONRPC: {preferred_transport!r}"
        )
    if not url:
        raise UpstreamError("card has no url and no supportedInterfaces")
    return url, data.get("protocolVersion")


def _dialect_from_protocol_version(protocol_version: str | None) -> Dialect:
    """CARD-3: prefix ``1`` -> v1; prefix ``0`` or missing -> v0_3."""
    if protocol_version is not None and protocol_version.startswith("1"):
        return "v1"
    return "v0_3"


async def send_message(
    card: NormalizedCard,
    text: str,
    *,
    http: httpx.AsyncClient,
    token: str | None = None,
    context_id: str | None = None,
    timeout_s: float = 55.0,
) -> AgentReply:
    """Send one message over the card's dialect and normalize the reply.

    WIRE-1/2: builds the dialect-correct JSON-RPC request (method, headers,
    role, part shape). WIRE-6: every request carries a fresh ``messageId``.
    CONV-1/2: ``context_id`` is sent verbatim as ``contextId`` when given, and
    omitted entirely otherwise — letting the upstream generate one.
    WIRE-3/4/5: the reply is normalized via ``_extract_reply``.
    """
    message: dict[str, Any] = {"messageId": str(uuid.uuid4())}
    if card.dialect == "v1":
        message["role"] = "ROLE_USER"
        message["parts"] = [{"text": text}]
    else:
        message["role"] = "user"
        message["parts"] = [{"kind": "text", "text": text}]
    if context_id is not None:
        message["contextId"] = context_id

    method = "SendMessage" if card.dialect == "v1" else "message/send"
    body = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": method,
        "params": {"message": message},
    }

    headers = {"Content-Type": "application/json"}
    if card.dialect == "v1":
        headers["A2A-Version"] = "1.0"
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"

    try:
        # See fetch_card: ASGITransport ignores httpx.Timeout, so
        # asyncio.wait_for backstops it for the hermetic test suite.
        response = await asyncio.wait_for(
            http.post(
                card.jsonrpc_url,
                json=body,
                headers=headers,
                timeout=httpx.Timeout(timeout_s),
            ),
            timeout=timeout_s,
        )
    except (httpx.TimeoutException, TimeoutError) as exc:
        raise BridgeTimeoutError(
            f"send_message timed out: {card.jsonrpc_url}"
        ) from exc
    except httpx.TransportError as exc:
        raise BridgeUnreachableError(
            f"send_message unreachable: {card.jsonrpc_url}"
        ) from exc

    if response.status_code in _UNAUTHORIZED_STATUS_CODES:
        raise UnauthorizedError(
            f"send_message unauthorized (HTTP {response.status_code})"
        )
    if not (200 <= response.status_code < 300):
        raise UpstreamError(f"send_message failed (HTTP {response.status_code})")

    try:
        payload = response.json()
    except ValueError as exc:
        raise UpstreamError("send_message response is not valid JSON") from exc

    if "error" in payload:
        error = payload["error"]
        code = error.get("code") if isinstance(error, dict) else None
        message_text = error.get("message") if isinstance(error, dict) else error
        raise UpstreamError(f"upstream JSON-RPC error {code}: {message_text}")

    result = payload.get("result")
    if not isinstance(result, dict):
        raise UpstreamError("malformed JSON-RPC response: missing result")

    return _extract_reply(result, context_id)


def _extract_reply(result: dict[str, Any], sent_context_id: str | None) -> AgentReply:
    """WIRE-3/4: normalize a v1 or v0_3 JSON-RPC result into an AgentReply.

    A v1 result nests the payload under a ``"message"``/``"task"`` key; a
    v0_3 result is kind-discriminated with the fields merged at the top
    level (``"kind": "message"`` / ``"kind": "task"``). Both shapes are
    handled uniformly here since the extraction rules (WIRE-3) are the same
    once the message/task object is located.
    """
    message = result.get("message")
    if not isinstance(message, dict) and result.get("kind") == "message":
        message = result
    if isinstance(message, dict):
        text = _join_parts_text(message.get("parts", []))
        context_id = message.get("contextId", sent_context_id)
        return AgentReply(text=text, context_id=context_id, raw=result)

    task = result.get("task")
    if not isinstance(task, dict) and result.get("kind") == "task":
        task = result
    if isinstance(task, dict):
        return _reply_from_task(task, result, sent_context_id)

    raise UpstreamError("malformed JSON-RPC result: neither message nor task shape")


def _reply_from_task(
    task: dict[str, Any], raw_result: dict[str, Any], sent_context_id: str | None
) -> AgentReply:
    """WIRE-3 task-branch extraction, keyed by ``status.state``."""
    context_id = task.get("contextId", sent_context_id)
    status = task.get("status") or {}
    state = status.get("state")
    status_message = status.get("message") or {}

    if state in _COMPLETED_STATES:
        artifacts = task.get("artifacts") or []
        if artifacts:
            parts = [part for artifact in artifacts for part in artifact.get("parts", [])]
            text = _join_parts_text(parts)
        else:
            text = _join_parts_text(status_message.get("parts", []))
        return AgentReply(text=text, context_id=context_id, raw=raw_result)

    if state in _CONTINUE_STATES:
        text = _join_parts_text(status_message.get("parts", []))
        return AgentReply(text=text, context_id=context_id, raw=raw_result)

    if state in _FAILURE_STATES:
        failure_text = _join_parts_text(status_message.get("parts", []))
        detail = f": {failure_text}" if failure_text else ""
        raise UpstreamError(f"upstream task ended in state {state!r}{detail}")

    raise UpstreamError(f"upstream task in unexpected state: {state!r}")


def _join_parts_text(parts: list[dict[str, Any]]) -> str:
    """Concatenate ``parts[].text`` — works for both v1 (no ``kind``) and
    v0_3 (``kind: "text"``) part shapes, since both carry a ``text`` field."""
    return "".join(part.get("text", "") for part in parts)
