"""Static YAML bridge registry (SPEC REG-1..5, §3).

Secrets never live in YAML: ``credential_ref`` is an ENV VAR NAME, resolved at
call time via env indirection (injectable for tests).
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

from gateway.errors import RegistryError, UnauthorizedError, UnknownBridgeError

AuthMode = Literal["open", "token"]
MinTier = Literal["anonymous", "authenticated"]

# REG-2: slug id regex.
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
# REG-3: credential_ref must be an ENV VAR NAME, never a literal secret value.
_CREDENTIAL_REF_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")

_AUTH_MODES: tuple[AuthMode, ...] = ("open", "token")
_MIN_TIERS: tuple[MinTier, ...] = ("anonymous", "authenticated")


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
        for entry in self.bridges:
            if entry.id == bridge_id:
                return entry
        raise UnknownBridgeError(f"Unknown bridge id: {bridge_id!r}")

    def ids(self) -> tuple[str, ...]:
        return tuple(entry.id for entry in self.bridges)


def _require(raw: dict[str, Any], key: str, entry_id: str) -> Any:
    """Fetch a required field, raising RegistryError naming the offending entry."""
    value = raw.get(key)
    if value is None or value == "":
        raise RegistryError(f"Bridge entry {entry_id!r} is missing required field {key!r}")
    return value


def _parse_entry(raw: dict[str, Any]) -> BridgeEntry:
    """Validate + build one BridgeEntry from a raw YAML mapping (REG-1..3)."""
    entry_id = raw.get("id")
    if not entry_id:
        raise RegistryError("Bridge entry is missing required field 'id'")
    if not _ID_RE.match(entry_id):
        raise RegistryError(
            f"Bridge entry {entry_id!r} has an invalid id "
            f"(must match ^[a-z0-9][a-z0-9-]*$)"
        )

    card_url = _require(raw, "card_url", entry_id)
    description = _require(raw, "description", entry_id)

    auth_mode: AuthMode = raw.get("auth_mode", "open")
    if auth_mode not in _AUTH_MODES:
        raise RegistryError(
            f"Bridge entry {entry_id!r} has unknown auth_mode {auth_mode!r} "
            f"(expected one of {_AUTH_MODES})"
        )

    min_tier: MinTier = raw.get("min_tier", "anonymous")
    if min_tier not in _MIN_TIERS:
        raise RegistryError(
            f"Bridge entry {entry_id!r} has unknown min_tier {min_tier!r} "
            f"(expected one of {_MIN_TIERS})"
        )

    credential_ref = raw.get("credential_ref")

    if auth_mode == "token":
        if not credential_ref:
            raise RegistryError(
                f"Bridge entry {entry_id!r} has auth_mode 'token' but no "
                f"credential_ref"
            )
        if not _CREDENTIAL_REF_RE.match(credential_ref):
            raise RegistryError(
                f"Bridge entry {entry_id!r} has a credential_ref "
                f"{credential_ref!r} that does not look like an ENV VAR NAME "
                f"(must match ^[A-Z][A-Z0-9_]*$) — did you paste a literal secret?"
            )

    return BridgeEntry(
        id=entry_id,
        card_url=card_url,
        description=description,
        auth_mode=auth_mode,
        credential_ref=credential_ref,
        min_tier=min_tier,
    )


def load_registry(path: Path) -> Registry:
    """Load + validate a ``bridges:`` YAML registry file (REG-1/2/3)."""
    raw_doc = yaml.safe_load(Path(path).read_text()) or {}
    raw_bridges = raw_doc.get("bridges") or []

    seen_ids: set[str] = set()
    entries: list[BridgeEntry] = []
    for raw in raw_bridges:
        entry = _parse_entry(raw)
        if entry.id in seen_ids:
            raise RegistryError(f"Duplicate bridge id: {entry.id!r}")
        seen_ids.add(entry.id)
        entries.append(entry)

    return Registry(bridges=tuple(entries))


def resolve_credential(
    entry: BridgeEntry, env: Mapping[str, str] | None = None
) -> str | None:
    """None for auth_mode=open; ``env[credential_ref]`` for token mode.

    Raises UnauthorizedError when the env var is unset/empty (REG-4).
    ``env`` defaults to ``os.environ``; injectable for tests.
    """
    if entry.auth_mode == "open":
        return None

    active_env = os.environ if env is None else env
    # credential_ref is guaranteed non-None for auth_mode="token" by REG-3 validation.
    var_name = entry.credential_ref
    assert var_name is not None
    value = active_env.get(var_name)
    if not value:
        raise UnauthorizedError(
            f"Bridge {entry.id!r} requires credential env var {var_name!r}, "
            f"which is unset or empty"
        )
    return value
