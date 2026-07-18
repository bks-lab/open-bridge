"""Gateway configuration: defaults <- YAML <- ENV (SPEC CFG-1..2, §3 table).

Secrets only ever arrive via env-var indirection — no secret material in YAML.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


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


def load_config(
    path: Path | None = None, env: Mapping[str, str] | None = None
) -> GatewayConfig:
    raise NotImplementedError
