"""Static YAML bridge registry (SPEC REG-1..5, §3).

Secrets never live in YAML: ``credential_ref`` is an ENV VAR NAME, resolved at
call time via env indirection (injectable for tests).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

AuthMode = Literal["open", "token"]
MinTier = Literal["anonymous", "authenticated"]


@dataclass(frozen=True)
class BridgeEntry:
    id: str
    card_url: str
    description: str
    auth_mode: AuthMode = "open"
    credential_ref: str | None = None
    min_tier: MinTier = "anonymous"


@dataclass(frozen=True)
class Registry:
    bridges: tuple[BridgeEntry, ...]

    def get(self, bridge_id: str) -> BridgeEntry:
        raise NotImplementedError

    def ids(self) -> tuple[str, ...]:
        raise NotImplementedError


def load_registry(path: Path) -> Registry:
    raise NotImplementedError


def resolve_credential(
    entry: BridgeEntry, env: Mapping[str, str] | None = None
) -> str | None:
    """None for auth_mode=open; ``env[credential_ref]`` for token mode.

    Raises UnauthorizedError when the env var is unset/empty (REG-4).
    ``env`` defaults to ``os.environ``; injectable for tests.
    """
    raise NotImplementedError
