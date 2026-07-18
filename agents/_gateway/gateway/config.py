"""Gateway configuration: defaults <- YAML <- ENV (SPEC CFG-1..2, §3 table).

Secrets only ever arrive via env-var indirection — no secret material in YAML.
The env mapping is injectable so tests never touch the real process
environment; production callers simply omit it and get ``os.environ``.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class GatewayConfig:
    registry_path: Path = Path("registry.yaml")
    host: str = "127.0.0.1"
    port: int = 8900
    ask_timeout_s: float = 55.0
    card_timeout_s: float = 10.0
    card_cache_ttl_s: float = 300.0
    per_bridge_concurrency: int = 2
    busy_retry_after_s: float = 10.0
    tokens_env: str = "GATEWAY_AUTH_TOKENS"
    # Host-header allowlist for the SDK's DNS-rebinding protection. Empty =
    # keep the SDK default (localhost-only auto-allowlist when binding a
    # localhost host) — set it when a tunnel puts a public hostname in the
    # Host header, which the auto-allowlist would reject with HTTP 421.
    allowed_hosts: tuple[str, ...] = ()


# One row per §3 table key: (dataclass field, YAML key, ENV name, coercion).
# The coercion doubles as CFG-1 validation — int()/float() raise ValueError on
# non-numeric input, which is exactly the loud failure the spec mandates.
_SCALARS: tuple[tuple[str, str, str, Callable[[Any], Any]], ...] = (
    ("registry_path", "registry", "GATEWAY_REGISTRY", lambda v: Path(str(v))),
    ("host", "host", "GATEWAY_HOST", str),
    ("port", "port", "GATEWAY_PORT", int),
    ("ask_timeout_s", "ask_timeout_s", "GATEWAY_ASK_TIMEOUT_S", float),
    ("card_timeout_s", "card_timeout_s", "GATEWAY_CARD_TIMEOUT_S", float),
    ("card_cache_ttl_s", "card_cache_ttl_s", "GATEWAY_CARD_CACHE_TTL_S", float),
    (
        "per_bridge_concurrency",
        "per_bridge_concurrency",
        "GATEWAY_PER_BRIDGE_CONCURRENCY",
        int,
    ),
    ("busy_retry_after_s", "busy_retry_after_s", "GATEWAY_BUSY_RETRY_AFTER_S", float),
    ("tokens_env", "tokens_env", "GATEWAY_TOKENS_ENV", str),
)


def load_config(
    path: Path | None = None, env: Mapping[str, str] | None = None
) -> GatewayConfig:
    """Resolve the effective config: defaults <- optional YAML <- ENV (CFG-1).

    ENV always wins so a deployment can override a checked-in YAML without
    editing it. Per-field coercion raises ValueError on non-numeric numeric
    fields — a typo'd ``GATEWAY_PORT`` must abort startup, never silently
    fall back to a default.
    """
    active_env: Mapping[str, str] = os.environ if env is None else env

    yaml_doc: dict[str, Any] = {}
    if path is not None:
        loaded = yaml.safe_load(Path(path).read_text())
        if loaded is not None:
            if not isinstance(loaded, dict):
                raise ValueError(f"config file is not a YAML mapping: {path}")
            yaml_doc = loaded

    values: dict[str, Any] = {}
    for field_name, yaml_key, env_name, convert in _SCALARS:
        if env_name in active_env:
            values[field_name] = convert(active_env[env_name])
        elif yaml_key in yaml_doc and yaml_doc[yaml_key] is not None:
            values[field_name] = convert(yaml_doc[yaml_key])

    # allowed_hosts is the one list-valued key: a YAML list, or a
    # comma-separated ENV string (entries trimmed, empties dropped — the same
    # CSV convention the client token list uses).
    if "GATEWAY_ALLOWED_HOSTS" in active_env:
        raw_csv = active_env["GATEWAY_ALLOWED_HOSTS"]
        values["allowed_hosts"] = tuple(
            host for host in (part.strip() for part in raw_csv.split(",")) if host
        )
    elif "allowed_hosts" in yaml_doc and yaml_doc["allowed_hosts"] is not None:
        raw_hosts = yaml_doc["allowed_hosts"]
        if not isinstance(raw_hosts, list):
            raise ValueError("allowed_hosts must be a YAML list of host[:port] strings")
        values["allowed_hosts"] = tuple(str(host) for host in raw_hosts)

    return GatewayConfig(**values)
