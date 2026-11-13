"""Regression tests for inline grounding (``_runtime.config.compose_inline_grounding``).

Inline grounding embeds the agent's grounding file(s) straight into the system
prompt so the public agent answers from context instead of paying a Read/Grep
round-trip per question — the dominant source of the 2026-06-09 "answer never
came back to the page" latency (the answer DID arrive, but ~30 s later via tool
exploration). These lock the contract: declared files land in the prompt in full,
nothing is silently dropped, and an accidental giant file can't blow up the prompt.

Pure function + ``tmp_path`` → fast and deterministic in CI.
"""
from __future__ import annotations

import logging
from pathlib import Path

import _runtime.config as config_mod
from _runtime.config import (
    MAX_INLINE_GROUNDING_BYTES,
    compose_inline_grounding,
    load_agent_config,
    resolve_trust,
)

BASE = "PERSONA PROMPT.\n"


def test_no_patterns_returns_prompt_unchanged(tmp_path):
    (tmp_path / "cv.toml").write_text("name = 'Alex'", "utf-8")
    assert compose_inline_grounding(BASE, str(tmp_path), []) == BASE


def test_no_match_returns_prompt_unchanged(tmp_path):
    (tmp_path / "cv.toml").write_text("name = 'Alex'", "utf-8")
    assert compose_inline_grounding(BASE, str(tmp_path), ["does-not-exist.toml"]) == BASE


def test_matching_file_is_embedded_in_full(tmp_path):
    marker = "experience = 'built an A2A system in 2025'"
    (tmp_path / "config.cv.toml").write_text(f"[params]\n{marker}\n", "utf-8")

    out = compose_inline_grounding(BASE, str(tmp_path), ["config.cv.toml"])

    assert out.startswith(BASE)            # persona stays first
    assert marker in out                   # the actual CV content is embedded
    assert "config.cv.toml" in out         # file is labelled
    # The framing that tells the agent NOT to re-read via tools — this is the
    # whole point of the feature; if it's gone the latency win is gone too.
    assert "answer directly from them" in out


def test_glob_embeds_every_match_sorted(tmp_path):
    (tmp_path / "a.md").write_text("ALPHA", "utf-8")
    (tmp_path / "b.md").write_text("BETA", "utf-8")

    out = compose_inline_grounding(BASE, str(tmp_path), ["*.md"])

    assert "ALPHA" in out and "BETA" in out
    assert out.index("ALPHA") < out.index("BETA")   # sorted, deterministic order


def test_oversized_file_is_skipped(tmp_path):
    (tmp_path / "huge.toml").write_text("x" * (MAX_INLINE_GROUNDING_BYTES + 1), "utf-8")
    (tmp_path / "small.toml").write_text("KEEP_ME", "utf-8")

    out = compose_inline_grounding(BASE, str(tmp_path), ["*.toml"])

    assert "KEEP_ME" in out          # the sane file is still embedded
    assert "xxxx" not in out         # the runaway file is not — prompt stays bounded


def test_only_matching_files_embedded(tmp_path):
    (tmp_path / "cv.toml").write_text("PUBLIC_CV", "utf-8")
    (tmp_path / "secret.txt").write_text("PRIVATE_NOTES", "utf-8")

    out = compose_inline_grounding(BASE, str(tmp_path), ["*.toml"])

    assert "PUBLIC_CV" in out
    assert "PRIVATE_NOTES" not in out   # a non-matching sibling is never pulled in


# ---------------------------------------------------------------------------
# Trust profile — fail-closed resolution (``trust: public | private``, env
# override ``AGENT_TRUST``), the cwd switch it drives, and the loader-level
# non-loopback host warning. Default and every unrecognized value MUST resolve
# to "public" — a typo must never silently grant the relaxed settings.
# ---------------------------------------------------------------------------

def _make_instance(tmp_path: Path, name: str, agent_yaml: str) -> None:
    inst = tmp_path / name
    inst.mkdir()
    (inst / "agent.yaml").write_text(agent_yaml, "utf-8")
    (inst / "system-prompt.md").write_text("PERSONA", "utf-8")


def _load(monkeypatch, tmp_path, name, agent_yaml, **kwargs):
    monkeypatch.delenv("AGENT_TRUST", raising=False)
    monkeypatch.setattr(config_mod, "AGENTS_DIR", tmp_path)
    _make_instance(tmp_path, name, agent_yaml)
    return load_agent_config(name, environment="test", **kwargs)


def test_resolve_trust_defaults_to_public_when_unset(monkeypatch):
    monkeypatch.delenv("AGENT_TRUST", raising=False)
    assert resolve_trust("x", None) == "public"
    assert resolve_trust("x", "") == "public"


def test_resolve_trust_accepts_private(monkeypatch):
    monkeypatch.delenv("AGENT_TRUST", raising=False)
    assert resolve_trust("x", "private") == "private"


def test_resolve_trust_unrecognized_value_falls_back_to_public(monkeypatch):
    monkeypatch.delenv("AGENT_TRUST", raising=False)
    assert resolve_trust("x", "super-trusted") == "public"


def test_resolve_trust_env_override_wins_over_spec(monkeypatch):
    monkeypatch.setenv("AGENT_TRUST", "private")
    assert resolve_trust("x", "public") == "private"


def test_absent_trust_field_resolves_to_public(tmp_path, monkeypatch):
    cfg = _load(monkeypatch, tmp_path, "notrust", 'name: "NoTrust"\n')
    assert cfg.trust == "public"


def test_explicit_public_trust_is_a_noop(tmp_path, monkeypatch):
    cfg = _load(monkeypatch, tmp_path, "expltrust", 'name: "Expl"\ntrust: "public"\n')
    assert cfg.trust == "public"


def test_unrecognized_trust_in_yaml_falls_back_to_public_and_warns(tmp_path, monkeypatch, caplog):
    with caplog.at_level(logging.WARNING, logger="_runtime.config"):
        cfg = _load(monkeypatch, tmp_path, "badtrust", 'name: "Bad"\ntrust: "supertrusted"\n')
    assert cfg.trust == "public"
    assert any("unrecognized trust value" in r.message for r in caplog.records)


def test_blank_trust_in_yaml_falls_back_to_public_without_crash(tmp_path, monkeypatch):
    cfg = _load(monkeypatch, tmp_path, "blanktrust", 'name: "Blank"\ntrust: ""\n')
    assert cfg.trust == "public"


def test_agent_trust_env_overrides_yaml_field(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "AGENTS_DIR", tmp_path)
    _make_instance(tmp_path, "envtrust", 'name: "EnvTrust"\ntrust: "public"\n')
    monkeypatch.setenv("AGENT_TRUST", "private")
    cfg = load_agent_config("envtrust", environment="test")
    assert cfg.trust == "private"


def test_public_trust_cwd_is_the_grounding_dir(tmp_path, monkeypatch):
    ground = tmp_path / "ground"
    ground.mkdir()
    cfg = _load(
        monkeypatch, tmp_path, "pubcwd",
        f'name: "Pub"\ngrounding_dir: "{ground}"\n',
    )
    assert cfg.trust == "public"
    assert cfg.working_dir == str(ground.resolve())


def test_private_trust_cwd_is_the_project_root_even_with_grounding_dir_set(tmp_path, monkeypatch):
    ground = tmp_path / "ground"
    ground.mkdir()
    cfg = _load(
        monkeypatch, tmp_path, "privcwd",
        f'name: "Priv"\ntrust: "private"\nhost: "127.0.0.1"\ngrounding_dir: "{ground}"\n',
    )
    assert cfg.trust == "private"
    assert cfg.working_dir == str(config_mod.PROJECT_ROOT)
    assert cfg.working_dir != str(ground.resolve())


def test_private_trust_on_non_loopback_host_warns(tmp_path, monkeypatch, caplog):
    with caplog.at_level(logging.WARNING, logger="_runtime.config"):
        cfg = _load(
            monkeypatch, tmp_path, "exposedpriv",
            'name: "Exposed"\ntrust: "private"\nhost: "0.0.0.0"\n',
        )
    assert cfg.trust == "private"
    assert cfg.host == "0.0.0.0"
    assert any("non-loopback" in r.message for r in caplog.records)


def test_private_trust_on_loopback_host_does_not_warn(tmp_path, monkeypatch, caplog):
    with caplog.at_level(logging.WARNING, logger="_runtime.config"):
        cfg = _load(
            monkeypatch, tmp_path, "safepriv",
            'name: "Safe"\ntrust: "private"\nhost: "127.0.0.1"\n',
        )
    assert cfg.trust == "private"
    assert not any("non-loopback" in r.message for r in caplog.records)


def test_public_trust_on_non_loopback_host_does_not_warn(tmp_path, monkeypatch, caplog):
    """The warning is specific to trust: private — a public agent is MEANT to be
    reachable from the network, so the same check must not fire for it."""
    with caplog.at_level(logging.WARNING, logger="_runtime.config"):
        cfg = _load(
            monkeypatch, tmp_path, "pubwide",
            'name: "PubWide"\nhost: "0.0.0.0"\n',
        )
    assert cfg.trust == "public"
    assert not any("non-loopback" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Load shedding (#640): how long a shed caller should wait, and how long a turn
# may wait for a free claude -p slot before it is shed.
# ---------------------------------------------------------------------------

def test_busy_settings_default_when_absent(tmp_path, monkeypatch):
    cfg = _load(monkeypatch, tmp_path, "busydefault", 'name: "BusyDefault"\n')
    assert cfg.busy_retry_after_s == 5.0
    assert cfg.slot_wait_timeout_s == 0.0


def test_busy_settings_load_from_agent_yaml(tmp_path, monkeypatch):
    cfg = _load(monkeypatch, tmp_path, "busyset", 'name: "BusySet"\n'
                'busy_retry_after_s: 2.5\nslot_wait_timeout_s: 10\n')
    assert cfg.busy_retry_after_s == 2.5
    assert cfg.slot_wait_timeout_s == 10.0
