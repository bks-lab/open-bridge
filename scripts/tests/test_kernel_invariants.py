"""The guardrails that must stay always-on after AGENTS.md became a kernel.

AGENTS.md lost its family table and its feature sections; their guardrails
moved into `route:` text in docs/data-model.yaml (rendered into
docs/families.md, which AGENTS.md imports) or stayed in the kernel prose.
Both files reach every session and every sub-agent, so each invariant must
be findable in one of them. A short needle per invariant keeps a later trim
from dropping one silently: delete the sentence and this goes red.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ALWAYS_ON = ["AGENTS.md", "docs/families.md"]

# invariant -> needles that must ALL appear (case-insensitive, whitespace and
# markdown emphasis normalised) in AGENTS.md or docs/families.md
INVARIANTS = {
    "remote means a machine, never git remote": ["never `git remote`"],
    "check infra/remotes/ before asking which PC": ["which PC?"],
    "read identity/accounts/ before any cloud operation": ["before ANY cloud operation"],
    "no raw secret in YAML": ["no raw secret in YAML"],
    "reference URIs only": ["reference URIs only"],
    "workloads carry no status field": ["no status: field"],
    "only the backup executor writes _state.yaml": ["only the backup executor writes _state.yaml"],
    "never hand-pick a brand colour": ["never hand-pick a brand colour"],
    "read workflow/projects before any GitHub/ADO call": [
        "Before ANY GitHub/ADO operation, read the matching `workflow/projects/<slug>.yaml`"],
    "never hardcode a field value": ["never hardcode a field value"],
    "never set an issue straight to Done": ['never set an issue straight to "Done"'],
    "Theme is vocabulary only": ["Themes control user-facing vocabulary only"],
    "Bridge Deck is optional, never auto-install": ["Bridge Deck", "never auto-install"],
    "never point ~/.claude/skills at a Bridge repo": [
        "Never point `~/.claude/skills` at a Bridge repo"],
    "promote pointer": ["rules/operations.md", "rules/promote-safety.md"],
}


def normalise(text: str) -> str:
    """Blockquote markers, emphasis and line wraps do not change a sentence."""
    text = re.sub(r"(?m)^\s*>\s?", "", text).replace("*", "")
    return re.sub(r"\s+", " ", text).lower()


def always_on() -> str:
    parts = []
    for rel in ALWAYS_ON:
        path = ROOT / rel
        assert path.is_file(), f"{rel} is part of the always-on surface and is missing"
        parts.append(path.read_text(encoding="utf-8"))
    return normalise("\n".join(parts))


@pytest.mark.parametrize("name", sorted(INVARIANTS))
def test_invariant_is_always_on(name):
    text = always_on()
    missing = [n for n in INVARIANTS[name] if normalise(n) not in text]
    assert not missing, (f"invariant '{name}' left the always-on surface "
                         f"(AGENTS.md + docs/families.md): {missing}")


def test_agents_md_imports_the_index():
    lines = [line.rstrip() for line in (ROOT / "AGENTS.md").read_text(encoding="utf-8").splitlines()]
    assert "@docs/families.md" in lines


def test_promote_pointer_is_one_line_in_the_rules_list():
    """Both promote rules are named together, so nobody reads one and misses the other."""
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    rules = text.split("\n## Rules\n", 1)[1].split("\n### ", 1)[0]
    items = re.split(r"\n- ", rules)
    assert any("rules/operations.md" in i and "rules/promote-safety.md" in i and "promote" in i
               for i in items), "no Rules item names both promote rules"
