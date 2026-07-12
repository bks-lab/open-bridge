"""The CORE ``_template`` instance loads and stays generic / public-safe.

The template ships in a PUBLIC repo, so it must carry zero host-specific data
and be English-only. Rather than blocklisting names (incomplete, and the names
would themselves land in the OSS repo), this asserts *structural* genericity:
``load_agent_config('_template')`` resolves, every identity-bearing field is
still an angle-bracket placeholder (never a filled-in persona), and no file
carries an absolute host path or German text. The repo's own content-safety
scanner owns the exhaustive name/org denylist across the whole tree.
"""
from __future__ import annotations

import re

from _runtime.config import AGENTS_DIR, load_agent_config


def test_template_instance_loads():
    cfg = load_agent_config("_template", environment="test")
    assert cfg.name and cfg.version


def test_template_identity_fields_are_placeholders():
    cfg = load_agent_config("_template", environment="test")
    # Every human/org-identifying field must remain an angle-bracket placeholder,
    # never a filled-in real value — a filled value would mean a persona leaked
    # into a CORE, public-shipped template.
    for value in (
        cfg.name,
        cfg.description,
        cfg.public_url,
        cfg.provider.get("organization", "<>"),
        cfg.provider.get("url", "<>"),
    ):
        assert "<" in value and ">" in value, f"template field not a placeholder: {value!r}"


def test_template_files_english_only_and_pathless():
    tdir = AGENTS_DIR / "_template"
    files = [p for p in tdir.rglob("*") if p.is_file()]
    assert files, "no _template files found"
    text = "\n".join(p.read_text("utf-8") for p in files)
    assert not re.search(r"[äöüßÄÖÜ]", text), "_template must be English-only"
    assert "/Users/" not in text and "/home/" not in text, "no absolute host paths in template"
