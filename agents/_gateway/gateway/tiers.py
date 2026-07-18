"""Access tiers + the ONE auth/visibility decision point (SPEC TIER-1..7).

Anonymous is the standard tier; a valid bearer token elevates. This resolver is
the later OAuth 2.1 seam: ``resolve()``'s internals change, every other surface
stays. Invalid credentials fail loudly — never a silent anonymous downgrade.
"""

from __future__ import annotations

import enum
import os
from collections.abc import Mapping
from dataclasses import dataclass

from gateway.errors import TierDeniedError, UnauthorizedError
from gateway.registry import BridgeEntry, Registry


class AccessTier(enum.IntEnum):
    ANONYMOUS = 0
    AUTHENTICATED = 1


def tokens_from_env(env_var: str, env: Mapping[str, str] | None = None) -> frozenset[str]:
    """Comma-separated token list; entries stripped, empties dropped."""
    source = os.environ if env is None else env
    raw = source.get(env_var, "")
    return frozenset(t for t in (part.strip() for part in raw.split(",")) if t)


@dataclass(frozen=True)
class TierResolver:
    """The single auth/visibility decision point (TIER-6).

    ``resolve()`` is the only place that inspects the raw header — an OAuth
    2.1 rollout later replaces its internals only; every other method here
    (``visible``/``check_ask``/``extended``) is expressed purely in terms of
    the already-resolved ``AccessTier`` and stays untouched by that seam.
    """

    registry: Registry
    tokens: frozenset[str]

    def resolve(self, authorization: str | None) -> AccessTier:
        # TIER-1: absent header -> anonymous, the one silent-downgrade-free path.
        if authorization is None:
            return AccessTier.ANONYMOUS

        # TIER-3: anything present that isn't a valid "Bearer <known-token>"
        # must raise, never fall through to ANONYMOUS.
        scheme, _, rest = authorization.partition(" ")
        if scheme != "Bearer":
            raise UnauthorizedError("Authorization header does not use the Bearer scheme")

        token = rest.strip()
        if not token or token not in self.tokens:
            raise UnauthorizedError("Bearer token is missing or not recognized")

        return AccessTier.AUTHENTICATED

    def visible(self, tier: AccessTier) -> tuple[BridgeEntry, ...]:
        # TIER-4: anonymous callers only ever see anonymous-tier entries.
        if tier >= AccessTier.AUTHENTICATED:
            return self.registry.bridges
        return tuple(e for e in self.registry.bridges if e.min_tier == "anonymous")

    def check_ask(self, tier: AccessTier, entry: BridgeEntry) -> None:
        # TIER-5: caller's tier must meet or exceed the entry's min_tier.
        required = (
            AccessTier.AUTHENTICATED if entry.min_tier == "authenticated" else AccessTier.ANONYMOUS
        )
        if tier < required:
            raise TierDeniedError(f"bridge '{entry.id}' requires tier '{entry.min_tier}'")

    def extended(self, tier: AccessTier, entry: BridgeEntry) -> bool:
        # CARD-6: extended card detail is a pure function of the caller's tier.
        return tier >= AccessTier.AUTHENTICATED
