"""Access tiers + the ONE auth/visibility decision point (SPEC TIER-1..7).

Anonymous is the standard tier; a valid bearer token elevates. This resolver is
the later OAuth 2.1 seam: ``resolve()``'s internals change, every other surface
stays. Invalid credentials fail loudly — never a silent anonymous downgrade.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass

from gateway.registry import BridgeEntry, Registry


class AccessTier(enum.IntEnum):
    ANONYMOUS = 0
    AUTHENTICATED = 1


def tokens_from_env(env_var: str, env: Mapping[str, str] | None = None) -> frozenset[str]:
    """Comma-separated token list; entries stripped, empties dropped."""
    raise NotImplementedError


@dataclass(frozen=True)
class TierResolver:
    """The single auth/visibility decision point (TIER-6)."""

    registry: Registry
    tokens: frozenset[str]

    def resolve(self, authorization: str | None) -> AccessTier:
        raise NotImplementedError

    def visible(self, tier: AccessTier) -> tuple[BridgeEntry, ...]:
        raise NotImplementedError

    def check_ask(self, tier: AccessTier, entry: BridgeEntry) -> None:
        raise NotImplementedError

    def extended(self, tier: AccessTier, entry: BridgeEntry) -> bool:
        raise NotImplementedError
