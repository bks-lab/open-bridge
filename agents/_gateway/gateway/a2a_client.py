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

from dataclasses import dataclass
from typing import Any, Literal

import httpx

Dialect = Literal["v1", "v0_3"]


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
    raise NotImplementedError


async def send_message(
    card: NormalizedCard,
    text: str,
    *,
    http: httpx.AsyncClient,
    token: str | None = None,
    context_id: str | None = None,
    timeout_s: float = 55.0,
) -> AgentReply:
    raise NotImplementedError
