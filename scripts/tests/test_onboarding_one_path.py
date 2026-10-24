"""A new user gets one way to a private home, not three that disagree.

The re-home (clone, `origin` renamed to `upstream`, a new private repo as
`origin`) is the only recommended path. GitHub's "Use this template" button
survives only as a footnote that names its cost. The origin marker is written
and committed before the guard is armed and before the first push, so the
first push already runs through an armed guard that knows the origin is
private. The feature tour covers every family AGENTS.md routes to, without a
hard count that goes stale.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

ONBOARDING_FILES = [
    "SETUP.md",
    "docs/install.md",
    "rules/session-start.md",
    "rules/push-guard.md",
    "skills/bridge-onboard/SKILL.md",
    "skills/bridge-onboard/references/workflow.md",
]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def paragraphs(text: str) -> list[str]:
    """Paragraphs, with Markdown headings dropped: a title is not a
    recommendation. Comment lines inside code fences stay, they are advice."""
    kept, inside = [], False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            inside = not inside
        elif not inside and re.match(r"#{1,6} ", line):
            continue
        kept.append(line)
    return [p for p in re.split(r"\n\s*\n", "\n".join(kept)) if p.strip()]


def code_lines(text: str) -> list[str]:
    """Lines inside fenced code blocks, in document order."""
    out, inside = [], False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            inside = not inside
            continue
        if inside:
            out.append(line.strip())
    return out


def first_index(lines: list[str], needle: str) -> int:
    for i, line in enumerate(lines):
        if needle in line:
            return i
    raise AssertionError(f"no code line contains {needle!r}")


# --- the template button is a footnote, never a recommendation -------------


def test_template_button_is_only_a_footnote_with_its_cost():
    for rel in ONBOARDING_FILES:
        for para in paragraphs(read(rel)):
            flat = " ".join(para.split())
            if "use this template" not in flat.lower():
                continue
            assert "unrelated histories" in flat, (
                f"{rel}: a paragraph mentions the template button without its "
                f"cost (unrelated histories):\n{para}"
            )
            low = flat.lower()
            for word in ("cleanest", "recommended", "← recommended"):
                assert word not in low, f"{rel}: template button still recommended:\n{para}"


def test_skill_and_workflow_do_not_offer_the_button_as_a_rehome_option():
    for rel in ("skills/bridge-onboard/SKILL.md", "skills/bridge-onboard/references/workflow.md"):
        text = read(rel)
        assert "Use this\ntemplate" not in text and "Use this template" not in text, (
            f"{rel}: the wizard offers the template button; the re-home is the one path"
        )


# --- SETUP.md: marker before the guard, committed, then the first push ------


def test_setup_writes_and_commits_the_marker_before_arming_and_pushing():
    lines = code_lines(read("SETUP.md"))
    marker = first_index(lines, "> .bridge-origin")
    add = first_index(lines, "git add .bridge-origin")
    commit = first_index(lines, "git commit")
    setup = first_index(lines, "./bin/setup")
    push = next(i for i, l in enumerate(lines) if re.search(r"\bgit push\b|--push\b", l))
    assert marker < add < commit < setup, "marker must be written and committed before bin/setup"
    assert setup < push, "the first push must run after bin/setup armed the guard"


def test_setup_creates_the_private_repo_without_pushing_yet():
    for line in code_lines(read("SETUP.md")):
        if "gh repo create" in line:
            assert "--push" not in line, "gh repo create must not push before the guard is armed"
            assert "--private" in line


# --- lane [3] and the canonical remediation name the same sequence ----------


def lane3_row() -> str:
    for line in read("rules/session-start.md").splitlines():
        if line.startswith("| **[3]**"):
            return line
    raise AssertionError("lane [3] row missing from rules/session-start.md")


def test_lane3_names_the_rehome_and_the_committed_marker():
    row = lane3_row()
    assert "remote rename origin upstream" in row
    assert ".bridge-origin" in row
    assert "commit" in row


def test_push_guard_remediation_commits_the_marker_before_the_push():
    text = read("rules/push-guard.md")
    block = text.split("## Remediation", 1)[1].split("\n## ", 1)[0]
    lines = code_lines(block)
    marker = first_index(lines, "> .bridge-origin")
    commit = first_index(lines, "git commit")
    push = first_index(lines, "git push")
    assert marker < commit < push
    for line in lines:
        if "gh repo create" in line:
            assert "--push" not in line


# --- feature tour covers the AGENTS.md families, no hard count --------------


def agents_families() -> list[str]:
    text = read("AGENTS.md")
    table = text.split("| Family | Read it when |", 1)[1].split("\n\n", 1)[0]
    fams: list[str] = []
    for line in table.splitlines():
        if not line.startswith("| `"):
            continue
        first_cell = line.split("|")[1]
        fams += re.findall(r"`([a-z0-9-]+/[a-z0-9-]+/)`", first_cell)
    assert len(fams) > 10, fams
    return fams


def test_feature_tour_has_a_section_for_every_agents_family():
    tour = read("docs/feature-tour.md")
    headings = set(re.findall(r"^## (\S+/\S+/)\s*$", tour, flags=re.M))
    missing = [f for f in agents_families() if f not in headings]
    assert not missing, f"docs/feature-tour.md lacks sections for: {missing}"


def test_feature_tour_index_links_every_section():
    tour = read("docs/feature-tour.md")
    index = tour.split("## Index", 1)[1].split("\n## ", 1)[0]
    for fam in agents_families():
        anchor = "#" + fam.replace("/", "")
        assert anchor in index, f"index row missing for {fam} ({anchor})"


def test_feature_tour_states_no_family_count():
    tour = read("docs/feature-tour.md")
    assert not re.search(r"\b\d+\s+families\b", tour), "drop the hard family count"


# --- AGENTS.md: NEW-USER is a pointer, Phase 0 stays mandatory --------------


def test_agents_new_user_paragraph_is_a_pointer_and_phase0_stays_critical():
    text = read("AGENTS.md")
    para = next(p for p in paragraphs(text) if p.startswith("**For NEW USER:**"))
    assert "rules/session-start.md" in para
    assert len(para.encode()) < 600, f"NEW-USER paragraph should be a pointer ({len(para.encode())} B)"
    assert text.count("**Critical:**") >= 2
    assert "before running Phase 0" in text
