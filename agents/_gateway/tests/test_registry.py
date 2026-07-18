"""Tests for gateway/registry.py (SPEC.md § 4 REG-1..5, § 5 pinned interfaces).

Hermetic: no network, no real ports; every registry file is a YAML fixture
written under ``tmp_path``. Covers:

- REG-1: minimal + full ``load_registry`` entries, defaults applied.
- REG-2: duplicate id / bad slug / unknown enum / missing field -> RegistryError.
- REG-3: ``auth_mode: token`` without ``credential_ref``; a ``credential_ref``
  that looks like a literal secret value (fails the ENV-NAME regex) -> RegistryError.
- REG-4 (via ``resolve_credential``): open -> None; token + env set -> value;
  token + env missing/empty -> UnauthorizedError naming the var, never a token
  value.
- REG-5: ``Registry.get`` on an unknown bridge id -> UnknownBridgeError.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from gateway.errors import RegistryError, UnauthorizedError, UnknownBridgeError
from gateway.registry import BridgeEntry, Registry, load_registry, resolve_credential


def _write_registry(tmp_path: Path, bridges: list[dict]) -> Path:
    """Dump a ``bridges:`` YAML registry fixture under tmp_path and return its path."""
    path = tmp_path / "registry.yaml"
    path.write_text(yaml.safe_dump({"bridges": bridges}, sort_keys=False))
    return path


# ---------------------------------------------------------------------------
# REG-1 — well-formed load, defaults applied
# ---------------------------------------------------------------------------


def test_load_registry_minimal_entry_applies_defaults(tmp_path: Path) -> None:
    path = _write_registry(
        tmp_path,
        [
            {
                "id": "example",
                "card_url": "https://bridge.test/.well-known/agent-card.json",
                "description": "Example bridge.",
            }
        ],
    )

    registry = load_registry(path)

    assert isinstance(registry, Registry)
    assert len(registry.bridges) == 1
    entry = registry.bridges[0]
    assert entry.id == "example"
    assert entry.card_url == "https://bridge.test/.well-known/agent-card.json"
    assert entry.description == "Example bridge."
    assert entry.auth_mode == "open"  # REG-1 default
    assert entry.credential_ref is None
    assert entry.min_tier == "anonymous"  # REG-1 default


def test_load_registry_full_entry_preserves_all_fields(tmp_path: Path) -> None:
    path = _write_registry(
        tmp_path,
        [
            {
                "id": "full-bridge",
                "card_url": "https://bridge.test/full/agent-card.json",
                "description": "Full bridge entry with token auth.",
                "auth_mode": "token",
                "credential_ref": "FULL_BRIDGE_TOKEN",
                "min_tier": "authenticated",
            }
        ],
    )

    registry = load_registry(path)

    entry = registry.get("full-bridge")
    assert entry == BridgeEntry(
        id="full-bridge",
        card_url="https://bridge.test/full/agent-card.json",
        description="Full bridge entry with token auth.",
        auth_mode="token",
        credential_ref="FULL_BRIDGE_TOKEN",
        min_tier="authenticated",
    )


def test_load_registry_multiple_entries_all_present(tmp_path: Path) -> None:
    path = _write_registry(
        tmp_path,
        [
            {
                "id": "bridge-a",
                "card_url": "https://a.test/agent-card.json",
                "description": "Bridge A.",
            },
            {
                "id": "bridge-b",
                "card_url": "https://b.test/agent-card.json",
                "description": "Bridge B.",
                "min_tier": "authenticated",
                "auth_mode": "token",
                "credential_ref": "BRIDGE_B_TOKEN",
            },
        ],
    )

    registry = load_registry(path)

    assert registry.ids() == ("bridge-a", "bridge-b")


# ---------------------------------------------------------------------------
# REG-2 — schema violations -> RegistryError naming the offending entry
# ---------------------------------------------------------------------------


def test_load_registry_duplicate_id_raises_registry_error(tmp_path: Path) -> None:
    path = _write_registry(
        tmp_path,
        [
            {
                "id": "dup-bridge",
                "card_url": "https://a.test/agent-card.json",
                "description": "First.",
            },
            {
                "id": "dup-bridge",
                "card_url": "https://b.test/agent-card.json",
                "description": "Second.",
            },
        ],
    )

    with pytest.raises(RegistryError, match="dup-bridge"):
        load_registry(path)


def test_load_registry_bad_slug_raises_registry_error(tmp_path: Path) -> None:
    path = _write_registry(
        tmp_path,
        [
            {
                "id": "Bad_Slug",  # uppercase + underscore violate ^[a-z0-9][a-z0-9-]*$
                "card_url": "https://a.test/agent-card.json",
                "description": "Invalid slug.",
            }
        ],
    )

    with pytest.raises(RegistryError, match="Bad_Slug"):
        load_registry(path)


def test_load_registry_slug_leading_hyphen_raises_registry_error(tmp_path: Path) -> None:
    path = _write_registry(
        tmp_path,
        [
            {
                "id": "-leading-hyphen",
                "card_url": "https://a.test/agent-card.json",
                "description": "Invalid slug.",
            }
        ],
    )

    with pytest.raises(RegistryError, match="leading-hyphen"):
        load_registry(path)


def test_load_registry_unknown_auth_mode_raises_registry_error(tmp_path: Path) -> None:
    path = _write_registry(
        tmp_path,
        [
            {
                "id": "weird-auth",
                "card_url": "https://a.test/agent-card.json",
                "description": "Bad auth_mode.",
                "auth_mode": "handshake",
            }
        ],
    )

    with pytest.raises(RegistryError, match="handshake"):
        load_registry(path)


def test_load_registry_unknown_min_tier_raises_registry_error(tmp_path: Path) -> None:
    path = _write_registry(
        tmp_path,
        [
            {
                "id": "weird-tier",
                "card_url": "https://a.test/agent-card.json",
                "description": "Bad min_tier.",
                "min_tier": "superuser",
            }
        ],
    )

    with pytest.raises(RegistryError, match="superuser"):
        load_registry(path)


def test_load_registry_missing_card_url_raises_registry_error(tmp_path: Path) -> None:
    path = _write_registry(
        tmp_path,
        [
            {
                "id": "no-card-url",
                "description": "Missing card_url.",
            }
        ],
    )

    with pytest.raises(RegistryError, match="no-card-url"):
        load_registry(path)


def test_load_registry_missing_description_raises_registry_error(tmp_path: Path) -> None:
    path = _write_registry(
        tmp_path,
        [
            {
                "id": "no-description",
                "card_url": "https://a.test/agent-card.json",
            }
        ],
    )

    with pytest.raises(RegistryError, match="no-description"):
        load_registry(path)


# ---------------------------------------------------------------------------
# REG-3 — token auth_mode credential_ref rules
# ---------------------------------------------------------------------------


def test_load_registry_token_without_credential_ref_raises_registry_error(
    tmp_path: Path,
) -> None:
    path = _write_registry(
        tmp_path,
        [
            {
                "id": "token-no-ref",
                "card_url": "https://a.test/agent-card.json",
                "description": "Token mode without credential_ref.",
                "auth_mode": "token",
            }
        ],
    )

    with pytest.raises(RegistryError, match="token-no-ref"):
        load_registry(path)


def test_load_registry_credential_ref_secret_value_raises_registry_error(
    tmp_path: Path,
) -> None:
    """A ``credential_ref`` that looks like a literal secret ("sk-abc123") must
    fail the ENV-NAME regex ``^[A-Z][A-Z0-9_]*$`` — lowercase + hyphen."""
    path = _write_registry(
        tmp_path,
        [
            {
                "id": "token-secret-leak",
                "card_url": "https://a.test/agent-card.json",
                "description": "credential_ref looks like a secret value.",
                "auth_mode": "token",
                "credential_ref": "sk-abc123",
            }
        ],
    )

    with pytest.raises(RegistryError, match="token-secret-leak"):
        load_registry(path)


# ---------------------------------------------------------------------------
# REG-4 — resolve_credential matrix
# ---------------------------------------------------------------------------


def test_resolve_credential_open_mode_returns_none() -> None:
    entry = BridgeEntry(
        id="open-bridge",
        card_url="https://a.test/agent-card.json",
        description="Open bridge.",
        auth_mode="open",
    )

    assert resolve_credential(entry, env={}) is None


def test_resolve_credential_token_mode_env_set_returns_value() -> None:
    entry = BridgeEntry(
        id="token-bridge",
        card_url="https://a.test/agent-card.json",
        description="Token bridge.",
        auth_mode="token",
        credential_ref="TOKEN_BRIDGE_SECRET",
    )

    value = resolve_credential(
        entry, env={"TOKEN_BRIDGE_SECRET": "super-secret-value-should-not-leak"}
    )

    assert value == "super-secret-value-should-not-leak"


def test_resolve_credential_token_mode_env_missing_raises_unauthorized() -> None:
    entry = BridgeEntry(
        id="token-bridge",
        card_url="https://a.test/agent-card.json",
        description="Token bridge.",
        auth_mode="token",
        credential_ref="MISSING_TOKEN_VAR",
    )

    with pytest.raises(UnauthorizedError, match="MISSING_TOKEN_VAR"):
        resolve_credential(entry, env={})


def test_resolve_credential_token_mode_env_empty_raises_unauthorized() -> None:
    entry = BridgeEntry(
        id="token-bridge",
        card_url="https://a.test/agent-card.json",
        description="Token bridge.",
        auth_mode="token",
        credential_ref="EMPTY_TOKEN_VAR",
    )

    with pytest.raises(UnauthorizedError, match="EMPTY_TOKEN_VAR"):
        resolve_credential(entry, env={"EMPTY_TOKEN_VAR": ""})


def test_resolve_credential_error_message_never_contains_token_value() -> None:
    """REG-4: the UnauthorizedError must name the missing var, and must never
    leak a token value — including an unrelated secret sitting in the same env
    mapping (guards against an implementation that dumps the whole env)."""
    entry = BridgeEntry(
        id="token-bridge",
        card_url="https://a.test/agent-card.json",
        description="Token bridge.",
        auth_mode="token",
        credential_ref="MISSING_TOKEN_VAR",
    )
    decoy_secret = "decoy-secret-abcdef123456"

    with pytest.raises(UnauthorizedError) as exc_info:
        resolve_credential(
            entry, env={"UNRELATED_SECRET": decoy_secret, "MISSING_TOKEN_VAR": ""}
        )

    message = str(exc_info.value)
    assert "MISSING_TOKEN_VAR" in message
    assert decoy_secret not in message


# ---------------------------------------------------------------------------
# REG-5 — Registry.get on an unknown id
# ---------------------------------------------------------------------------


def test_registry_get_unknown_id_raises_unknown_bridge_error() -> None:
    registry = Registry(
        bridges=(
            BridgeEntry(
                id="known-bridge",
                card_url="https://a.test/agent-card.json",
                description="Known bridge.",
            ),
        )
    )

    with pytest.raises(UnknownBridgeError, match="unknown-bridge"):
        registry.get("unknown-bridge")


def test_registry_get_known_id_returns_matching_entry() -> None:
    known = BridgeEntry(
        id="known-bridge",
        card_url="https://a.test/agent-card.json",
        description="Known bridge.",
    )
    registry = Registry(bridges=(known,))

    assert registry.get("known-bridge") == known
