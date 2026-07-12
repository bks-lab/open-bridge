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

from _runtime.config import (
    MAX_INLINE_GROUNDING_BYTES,
    compose_inline_grounding,
)

BASE = "PERSONA PROMPT.\n"


def test_no_patterns_returns_prompt_unchanged(tmp_path):
    (tmp_path / "cv.toml").write_text("name = 'Michael'", "utf-8")
    assert compose_inline_grounding(BASE, str(tmp_path), []) == BASE


def test_no_match_returns_prompt_unchanged(tmp_path):
    (tmp_path / "cv.toml").write_text("name = 'Michael'", "utf-8")
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
