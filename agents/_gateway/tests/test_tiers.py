"""Purpose: exercises ``gateway.tiers`` — the single auth/visibility decision
point (SPEC.md §4 TIER-1..7, plus the CARD-6 ``extended`` split).

Covers: header → AccessTier resolution (no header → ANONYMOUS, valid Bearer →
AUTHENTICATED), ``tokens_from_env`` list parsing, the TIER-3 negative space
(wrong token / non-Bearer scheme / bare "Bearer" / empty configured list —
every one of these MUST raise UnauthorizedError, never silently downgrade to
ANONYMOUS), ``visible()`` filtering by ``min_tier``, ``check_ask()`` gating,
and ``extended()`` (CARD-6). Registry objects are built directly from
BridgeEntry dataclasses — no YAML/load_registry involved (that is
test_registry.py's job).
"""

from __future__ import annotations

import pytest

from gateway.errors import TierDeniedError, UnauthorizedError
from gateway.registry import BridgeEntry, Registry
from gateway.tiers import AccessTier, TierResolver, tokens_from_env

ANON_ENTRY = BridgeEntry(
    id="anon-bridge",
    card_url="https://example.test/anon-bridge/.well-known/agent-card.json",
    description="Anonymous-tier bridge",
    min_tier="anonymous",
)

AUTH_ENTRY = BridgeEntry(
    id="auth-bridge",
    card_url="https://example.test/auth-bridge/.well-known/agent-card.json",
    description="Authenticated-only bridge",
    min_tier="authenticated",
)

REGISTRY = Registry(bridges=(ANON_ENTRY, AUTH_ENTRY))

GOOD_TOKEN = "good-token-123"


def _resolver(tokens: frozenset[str] = frozenset({GOOD_TOKEN})) -> TierResolver:
    return TierResolver(registry=REGISTRY, tokens=tokens)


# ---------------------------------------------------------------------------
# TIER-1 / TIER-2 — resolve() happy paths
# ---------------------------------------------------------------------------


def test_resolve_no_header_returns_anonymous():
    resolver = _resolver()
    assert resolver.resolve(None) is AccessTier.ANONYMOUS


def test_resolve_valid_bearer_returns_authenticated():
    resolver = _resolver(frozenset({GOOD_TOKEN}))
    assert resolver.resolve(f"Bearer {GOOD_TOKEN}") is AccessTier.AUTHENTICATED


def test_resolve_valid_bearer_among_multiple_tokens_returns_authenticated():
    resolver = _resolver(frozenset({"tok-a", GOOD_TOKEN, "tok-c"}))
    assert resolver.resolve(f"Bearer {GOOD_TOKEN}") is AccessTier.AUTHENTICATED


# ---------------------------------------------------------------------------
# TIER-2 — tokens_from_env parsing (comma-separated, stripped, empties dropped)
# ---------------------------------------------------------------------------


def test_tokens_from_env_splits_commas():
    env = {"GATEWAY_AUTH_TOKENS": "tok-a,tok-b,tok-c"}
    assert tokens_from_env("GATEWAY_AUTH_TOKENS", env) == frozenset(
        {"tok-a", "tok-b", "tok-c"}
    )


def test_tokens_from_env_strips_whitespace_around_entries():
    env = {"GATEWAY_AUTH_TOKENS": " tok-a , tok-b ,  tok-c  "}
    assert tokens_from_env("GATEWAY_AUTH_TOKENS", env) == frozenset(
        {"tok-a", "tok-b", "tok-c"}
    )


def test_tokens_from_env_drops_empty_entries_from_stray_commas():
    env = {"GATEWAY_AUTH_TOKENS": "tok-a,,tok-b,,,"}
    assert tokens_from_env("GATEWAY_AUTH_TOKENS", env) == frozenset({"tok-a", "tok-b"})


def test_tokens_from_env_single_token_no_commas():
    env = {"GATEWAY_AUTH_TOKENS": "only-token"}
    assert tokens_from_env("GATEWAY_AUTH_TOKENS", env) == frozenset({"only-token"})


def test_tokens_from_env_missing_var_returns_empty_frozenset():
    assert tokens_from_env("GATEWAY_AUTH_TOKENS", {}) == frozenset()


def test_tokens_from_env_empty_value_returns_empty_frozenset():
    env = {"GATEWAY_AUTH_TOKENS": ""}
    assert tokens_from_env("GATEWAY_AUTH_TOKENS", env) == frozenset()


def test_tokens_from_env_whitespace_only_value_returns_empty_frozenset():
    env = {"GATEWAY_AUTH_TOKENS": "   "}
    assert tokens_from_env("GATEWAY_AUTH_TOKENS", env) == frozenset()


# ---------------------------------------------------------------------------
# TIER-3 — negative resolve() cases: never a silent downgrade to ANONYMOUS
# ---------------------------------------------------------------------------


def test_resolve_wrong_token_raises_unauthorized():
    resolver = _resolver(frozenset({GOOD_TOKEN}))
    with pytest.raises(UnauthorizedError):
        resolver.resolve("Bearer wrong-token")


def test_resolve_wrong_token_does_not_silently_downgrade_to_anonymous():
    """TIER-3 explicit non-downgrade assertion: a typo'd/foreign token must
    surface as a hard failure, and resolve() must never return a tier at all
    on that path (catch broadly, then check no AccessTier value leaked out)."""
    resolver = _resolver(frozenset({GOOD_TOKEN}))
    tier_returned = None
    try:
        tier_returned = resolver.resolve("Bearer wrong-token")
    except UnauthorizedError:
        pass
    assert tier_returned is None, (
        "resolve() must raise UnauthorizedError on a bad token, "
        "not return AccessTier.ANONYMOUS or any other tier"
    )


def test_resolve_basic_scheme_raises_unauthorized():
    resolver = _resolver(frozenset({GOOD_TOKEN}))
    with pytest.raises(UnauthorizedError):
        resolver.resolve("Basic dXNlcjpwYXNz")


def test_resolve_bare_bearer_without_token_raises_unauthorized():
    resolver = _resolver(frozenset({GOOD_TOKEN}))
    with pytest.raises(UnauthorizedError):
        resolver.resolve("Bearer")


def test_resolve_bearer_with_trailing_space_and_no_token_raises_unauthorized():
    resolver = _resolver(frozenset({GOOD_TOKEN}))
    with pytest.raises(UnauthorizedError):
        resolver.resolve("Bearer ")


def test_resolve_against_empty_configured_token_list_raises_unauthorized():
    """Even a well-formed 'Bearer <t>' header must fail hard when the
    configured list is empty/unset — not fall back to anonymous."""
    resolver = _resolver(frozenset())
    with pytest.raises(UnauthorizedError):
        resolver.resolve("Bearer anything-at-all")


def test_resolve_unknown_scheme_raises_unauthorized():
    resolver = _resolver(frozenset({GOOD_TOKEN}))
    with pytest.raises(UnauthorizedError):
        resolver.resolve("Token abc123")


# ---------------------------------------------------------------------------
# TIER-4 — visible() filtering by min_tier
# ---------------------------------------------------------------------------


def test_visible_anonymous_sees_only_anonymous_min_tier_entries():
    resolver = _resolver()
    result = resolver.visible(AccessTier.ANONYMOUS)
    assert result == (ANON_ENTRY,)


def test_visible_authenticated_sees_all_entries():
    resolver = _resolver()
    result = resolver.visible(AccessTier.AUTHENTICATED)
    assert set(result) == {ANON_ENTRY, AUTH_ENTRY}
    assert len(result) == 2


def test_visible_anonymous_never_includes_authenticated_only_entry():
    resolver = _resolver()
    result = resolver.visible(AccessTier.ANONYMOUS)
    assert AUTH_ENTRY not in result


# ---------------------------------------------------------------------------
# TIER-5 — check_ask() gating (TierDeniedError, upstream never contacted)
# ---------------------------------------------------------------------------


def test_check_ask_denies_anonymous_on_authenticated_only_entry():
    resolver = _resolver()
    with pytest.raises(TierDeniedError):
        resolver.check_ask(AccessTier.ANONYMOUS, AUTH_ENTRY)


def test_check_ask_allows_authenticated_on_authenticated_only_entry():
    resolver = _resolver()
    resolver.check_ask(AccessTier.AUTHENTICATED, AUTH_ENTRY)  # must not raise


def test_check_ask_allows_anonymous_on_anonymous_entry():
    resolver = _resolver()
    resolver.check_ask(AccessTier.ANONYMOUS, ANON_ENTRY)  # must not raise


def test_check_ask_allows_authenticated_on_anonymous_entry():
    resolver = _resolver()
    resolver.check_ask(AccessTier.AUTHENTICATED, ANON_ENTRY)  # must not raise


# ---------------------------------------------------------------------------
# CARD-6 — extended() by tier
# ---------------------------------------------------------------------------


def test_extended_false_for_anonymous_tier():
    resolver = _resolver()
    assert resolver.extended(AccessTier.ANONYMOUS, ANON_ENTRY) is False


def test_extended_true_for_authenticated_tier():
    resolver = _resolver()
    assert resolver.extended(AccessTier.AUTHENTICATED, ANON_ENTRY) is True


def test_extended_true_for_authenticated_tier_on_authenticated_only_entry():
    resolver = _resolver()
    assert resolver.extended(AccessTier.AUTHENTICATED, AUTH_ENTRY) is True
