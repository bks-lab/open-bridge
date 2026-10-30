"""AGENTS.md is the one entry file, and it carries the instance's slots.

Claude Code (2.1.277 on the Anthropic API, 2.1.281 on every backend) loads
AGENTS.md exactly where it would load CLAUDE.md, but only while no CLAUDE.md
sits beside it: a root `CLAUDE.md`, `CLAUDE.local.md` or `.claude/CLAUDE.md`
makes it load only those. CORE therefore ships none of them. The instance
layer (IDENTITY, SOUL, INSTANCE) loads through fixed `@` lines near the top
of AGENTS.md, so onboarding never writes an import. Codex reads only the
first 32768 bytes of AGENTS.md and resolves no imports, so the file stays
under that cut and tells every other agent to read the slots itself.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
AGENTS = ROOT / "AGENTS.md"
SLOTS = [
    "identity/agent/IDENTITY.md",
    "identity/agent/SOUL.md",
    "identity/agent/INSTANCE.md",
]
CODEX_CUT = 32768
POINTERS = ["GEMINI.md", ".github/copilot-instructions.md"]


def agents_bytes() -> bytes:
    return AGENTS.read_bytes()


def agents_text() -> str:
    return agents_bytes().decode("utf-8")


def unfenced_lines(text: str) -> list[tuple[int, str]]:
    """(byte offset at line end, line) for every line outside ``` fences."""
    out, inside, offset = [], False, 0
    for line in text.splitlines(keepends=True):
        offset += len(line.encode("utf-8"))
        bare = line.rstrip("\n")
        if bare.strip().startswith("```"):
            inside = not inside
            continue
        if not inside:
            out.append((offset, bare))
    return out


def loaded_block(text: str) -> str:
    return text.split("## Loaded with this file", 1)[1].split("\n## ", 1)[0]


def test_core_ships_no_root_claude_md():
    if (ROOT / "bridge-config.yaml").exists():
        pytest.skip("an instance checkout may still be migrating its CLAUDE.md")
    tracked = subprocess.run(
        ["git", "ls-files", "CLAUDE.md", "CLAUDE.local.md", ".claude/CLAUDE.md"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert tracked == "", f"CORE must not track a shadowing entry file: {tracked}"


def test_agents_md_carries_the_identity_slots():
    text = agents_text()
    lines = unfenced_lines(text)
    req = next(off for off, line in lines if line == "## Required Reading")
    for slot in SLOTS:
        hits = [off for off, line in lines if line == "@" + slot]
        assert hits, f"AGENTS.md lacks the column-0 import line @{slot} outside a fence"
        assert hits[0] < req, f"@{slot} must come before ## Required Reading"
        assert hits[0] <= 4096, f"@{slot} must sit within the first 4096 bytes"


def test_loaded_block_ends_within_the_first_4096_bytes():
    raw = agents_bytes()
    start = raw.index(b"## Loaded with this file")
    end = raw.index(b"\n## ", start + 1)
    assert end <= 4096, f"the slot block ends at byte {end}"


def test_agents_md_fits_the_codex_cut():
    size = len(agents_bytes())
    assert size <= CODEX_CUT, f"AGENTS.md is {size} B; Codex reads only {CODEX_CUT}"


def test_the_slot_paragraph_tells_other_agents_to_read_them():
    block = loaded_block(agents_text())
    first_import = block.index("\n@identity/")
    above = block[:first_import]
    assert "Any other agent" in above
    for slot in SLOTS:
        assert f"`{slot}`" in block, f"{slot} is not named in backticks in the slot block"
    link = re.compile(r"\]\((\.\./)?identity/agent/(IDENTITY|SOUL|INSTANCE)\.md\)")
    for rel in ["AGENTS.md", *POINTERS]:
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert not link.search(text), f"{rel} links an instance file that CORE does not ship"


def test_phase0_comes_first():
    head = agents_bytes()[:1024].decode("utf-8", errors="ignore")
    assert "run Phase 0" in head


def test_meter_discovers_the_slots():
    spec = importlib.util.spec_from_file_location(
        "measure_context_entry", ROOT / "scripts" / "measure-context.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    found = mod.discover_imports(ROOT, entry="AGENTS.md")
    for slot in SLOTS:
        assert slot in found, f"the meter does not see @{slot}: {found}"


@pytest.mark.parametrize("rel", POINTERS)
def test_pointer_files_name_the_slots(rel):
    text = (ROOT / rel).read_text(encoding="utf-8")
    for slot in SLOTS:
        assert slot in text, f"{rel} does not tell its agent to read {slot}"
    assert "`CLAUDE.md` and" not in text, f"{rel} still calls CLAUDE.md a pointer"
