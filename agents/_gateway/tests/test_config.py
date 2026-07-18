"""Tests for gateway/config.py (SPEC.md § 3 table, § 4 CFG-1).

Precedence is defaults <- YAML <- ENV, ENV always winning, with the exact
``GATEWAY_*`` names the § 3 table pins. Non-numeric values in numeric fields
raise ValueError. Hermetic: YAML files live under tmp_path and ``env`` is an
injected plain dict — the real process environment is never consulted.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gateway.config import GatewayConfig, load_config


def _write_yaml(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "gateway.yaml"
    path.write_text(content)
    return path


# ---------------------------------------------------------------------------
# defaults
# ---------------------------------------------------------------------------


def test_load_config_without_yaml_or_env_returns_pinned_defaults() -> None:
    config = load_config(None, env={})

    assert config == GatewayConfig()
    assert config.registry_path == Path("registry.yaml")
    assert config.host == "127.0.0.1"
    assert config.port == 8900
    assert config.ask_timeout_s == 55.0
    assert config.card_timeout_s == 10.0
    assert config.card_cache_ttl_s == 300.0
    assert config.per_bridge_concurrency == 2
    assert config.busy_retry_after_s == 10.0
    assert config.tokens_env == "GATEWAY_AUTH_TOKENS"


# ---------------------------------------------------------------------------
# YAML layer
# ---------------------------------------------------------------------------


def test_load_config_yaml_overrides_defaults_for_all_keys(tmp_path: Path) -> None:
    path = _write_yaml(
        tmp_path,
        """
registry: custom-registry.yaml
host: 0.0.0.0
port: 9001
ask_timeout_s: 30.5
card_timeout_s: 5.0
card_cache_ttl_s: 60.0
per_bridge_concurrency: 4
busy_retry_after_s: 2.5
tokens_env: MY_GATEWAY_TOKENS
""",
    )

    config = load_config(path, env={})

    assert config.registry_path == Path("custom-registry.yaml")
    assert config.host == "0.0.0.0"
    assert config.port == 9001
    assert config.ask_timeout_s == 30.5
    assert config.card_timeout_s == 5.0
    assert config.card_cache_ttl_s == 60.0
    assert config.per_bridge_concurrency == 4
    assert config.busy_retry_after_s == 2.5
    assert config.tokens_env == "MY_GATEWAY_TOKENS"


def test_load_config_partial_yaml_keeps_defaults_for_absent_keys(
    tmp_path: Path,
) -> None:
    path = _write_yaml(tmp_path, "port: 9002\n")

    config = load_config(path, env={})

    assert config.port == 9002
    assert config.host == "127.0.0.1"
    assert config.ask_timeout_s == 55.0
    assert config.tokens_env == "GATEWAY_AUTH_TOKENS"


# ---------------------------------------------------------------------------
# ENV layer — always wins (CFG-1)
# ---------------------------------------------------------------------------


def test_load_config_env_overrides_yaml_and_defaults(tmp_path: Path) -> None:
    # Three-layer merge in one shot: port is set in BOTH yaml and env (env
    # must win); ask_timeout_s only in yaml (yaml wins over default); host
    # only in env; card_timeout_s nowhere (default survives).
    path = _write_yaml(tmp_path, "port: 9001\nask_timeout_s: 30.0\n")
    env = {"GATEWAY_PORT": "9102", "GATEWAY_HOST": "10.0.0.5"}

    config = load_config(path, env=env)

    assert config.port == 9102
    assert config.host == "10.0.0.5"
    assert config.ask_timeout_s == 30.0
    assert config.card_timeout_s == 10.0


def test_load_config_env_names_cover_every_table_key_with_correct_types() -> None:
    env = {
        "GATEWAY_REGISTRY": "env-registry.yaml",
        "GATEWAY_HOST": "192.0.2.7",
        "GATEWAY_PORT": "9200",
        "GATEWAY_ASK_TIMEOUT_S": "40.5",
        "GATEWAY_CARD_TIMEOUT_S": "7.25",
        "GATEWAY_CARD_CACHE_TTL_S": "0",
        "GATEWAY_PER_BRIDGE_CONCURRENCY": "5",
        "GATEWAY_BUSY_RETRY_AFTER_S": "1.5",
        "GATEWAY_TOKENS_ENV": "OTHER_TOKENS_VAR",
    }

    config = load_config(None, env=env)

    assert config.registry_path == Path("env-registry.yaml")
    assert config.host == "192.0.2.7"
    assert config.port == 9200
    assert isinstance(config.port, int)
    assert config.ask_timeout_s == 40.5
    assert config.card_timeout_s == 7.25
    assert config.card_cache_ttl_s == 0.0
    assert config.per_bridge_concurrency == 5
    assert isinstance(config.per_bridge_concurrency, int)
    assert config.busy_retry_after_s == 1.5
    assert config.tokens_env == "OTHER_TOKENS_VAR"


# ---------------------------------------------------------------------------
# non-numeric numeric fields -> ValueError (CFG-1, negative)
# ---------------------------------------------------------------------------


def test_load_config_non_numeric_env_port_raises_value_error() -> None:
    with pytest.raises(ValueError):
        load_config(None, env={"GATEWAY_PORT": "eight-thousand"})


def test_load_config_non_numeric_env_timeout_raises_value_error() -> None:
    with pytest.raises(ValueError):
        load_config(None, env={"GATEWAY_ASK_TIMEOUT_S": "soon"})


def test_load_config_non_numeric_yaml_numeric_field_raises_value_error(
    tmp_path: Path,
) -> None:
    path = _write_yaml(tmp_path, "card_cache_ttl_s: not-a-number\n")

    with pytest.raises(ValueError):
        load_config(path, env={})


# ---------------------------------------------------------------------------
# allowed_hosts — SPEC § 3 (Host-header allowlist for tunnel deployments)
# ---------------------------------------------------------------------------


def test_load_config_allowed_hosts_defaults_empty_and_parses_yaml_list(
    tmp_path: Path,
) -> None:
    # Default empty = keep the SDK's own DNS-rebinding behavior untouched.
    assert load_config(None, env={}).allowed_hosts == ()

    path = _write_yaml(
        tmp_path,
        """
allowed_hosts:
  - gw.example.com
  - "gw.example.com:8900"
""",
    )

    config = load_config(path, env={})

    assert config.allowed_hosts == ("gw.example.com", "gw.example.com:8900")


def test_load_config_allowed_hosts_env_csv_overrides_yaml(tmp_path: Path) -> None:
    path = _write_yaml(tmp_path, "allowed_hosts: [yaml.example.com]\n")
    env = {"GATEWAY_ALLOWED_HOSTS": " env-a.example.com , env-b.example.com:443 ,"}

    config = load_config(path, env=env)

    # ENV wins over YAML; entries trimmed, empties dropped (CSV form).
    assert config.allowed_hosts == ("env-a.example.com", "env-b.example.com:443")
