"""A new user gets one way to a private home, not three that disagree.

The re-home (clone, `origin` renamed to `upstream`, a new private repo as
`origin`) is the only recommended path. GitHub's "Use this template" button
survives only as a footnote that names its cost. The origin marker is written
and committed before the guard is armed and before the first push, so the
first push already runs through an armed guard that knows the origin is
private. The feature tour covers every cluster-wrapper family in
docs/data-model.yaml (the source of the family index AGENTS.md imports),
without a hard count that goes stale.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

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


# --- feature tour covers the model's families, no hard count ---------------


def model_families() -> list[str]:
    """Every cluster-wrapper family in docs/data-model.yaml.

    Not a regex over docs/families.md: its own-lifecycle line names
    top-level rows (protocols/standing-orders/ and others) that the feature
    tour has no heading for.
    """
    model = yaml.safe_load(read("docs/data-model.yaml"))
    fams = [row["path"] for row in model["families"]
            if row["path"].split("/", 1)[0] in ("identity", "infra", "workflow")]
    assert len(fams) > 10, fams
    return fams


def test_feature_tour_has_a_section_for_every_agents_family():
    tour = read("docs/feature-tour.md")
    headings = set(re.findall(r"^## (\S+/\S+/)\s*$", tour, flags=re.M))
    missing = [f for f in model_families() if f not in headings]
    assert not missing, f"docs/feature-tour.md lacks sections for: {missing}"


def test_feature_tour_index_links_every_section():
    tour = read("docs/feature-tour.md")
    index = tour.split("## Index", 1)[1].split("\n## ", 1)[0]
    for fam in model_families():
        anchor = "#" + fam.replace("/", "")
        assert anchor in index, f"index row missing for {fam} ({anchor})"


def test_feature_tour_states_no_family_count():
    tour = read("docs/feature-tour.md")
    assert not re.search(r"\b\d+\s+families\b", tour), "drop the hard family count"


# --- what left AGENTS.md still lives somewhere --------------------------------


def test_moved_guardrails_still_exist():
    """The kernel rewrite moved feature sections out of AGENTS.md; each
    guardrail they carried must survive in the doc that now holds it."""
    needles = {
        "docs/remotes.md": ["git remote", "arm"],
        "docs/bridge-deck.md": ["never install it unasked"],
        "infra/backups/README.md": ["executor"],
        "docs/workloads.md": ["status:"],
        "docs/channels.md": ["/schedule"],
        "docs/cloud-accounts.md": ["before any cloud operation"],
    }
    for rel, words in needles.items():
        text = " ".join(read(rel).split()).lower()
        for word in words:
            assert word.lower() in text, f"{rel} lost '{word}'"


def test_agents_md_names_the_index_for_other_agents():
    """Claude Code imports docs/families.md; every other agent has to be told
    in plain text, since none of them resolves an @ line."""
    text = read("AGENTS.md")
    lines = [line.rstrip() for line in text.splitlines()]
    assert "@docs/families.md" in lines, "AGENTS.md lacks the column-0 import @docs/families.md"
    prose = [line for line in lines if not line.startswith("@")]
    assert any("`docs/families.md`" in line for line in prose), \
        "AGENTS.md never names `docs/families.md` outside the import line"
    for rel in ["GEMINI.md", ".github/copilot-instructions.md"]:
        assert "`docs/families.md`" in read(rel), f"{rel} does not name `docs/families.md`"


# --- AGENTS.md: NEW-USER is a pointer, Phase 0 stays mandatory --------------


def test_agents_new_user_paragraph_is_a_pointer_and_phase0_stays_critical():
    text = read("AGENTS.md")
    para = next(p for p in paragraphs(text) if p.startswith("**For NEW USER:**"))
    assert "rules/session-start.md" in para
    assert len(para.encode()) < 600, f"NEW-USER paragraph should be a pointer ({len(para.encode())} B)"
    assert text.count("**Critical:**") >= 2
    assert "before running Phase 0" in text


# --- review round: the marker vouches only for a checked, committed truth ---


def section(text: str, heading: str) -> str:
    return text.split(heading, 1)[1].split("\n## ", 1)[0]


def test_setup_checks_privacy_without_gh_before_writing_the_marker():
    """The no-gh path takes a URL on trust; an anonymous API call that must
    answer 404 proves the repo is not public before the marker vouches for it."""
    text = read("SETUP.md")
    step1 = section(text, "## Step 1")
    assert "api.github.com/repos/<me>/<name>" in step1
    assert "404" in step1 and "200" in step1
    assert text.index("api.github.com/repos/") < text.index("> .bridge-origin")


def test_push_guard_no_gh_path_checks_privacy_too():
    block = section(read("rules/push-guard.md"), "## Remediation")
    assert "api.github.com/repos/" in block and "404" in block


def test_setup_preflight_checks_git_identity():
    """Step 2 commits; on a fresh machine without an identity that commit
    fails and the marker never reaches the private repo."""
    pre = section(read("SETUP.md"), "## Before you change anything")
    assert "git config user.name" in pre and "git config user.email" in pre


def test_marker_write_keeps_the_shipped_comment_header():
    """Replacing only the two key lines keeps later upstream edits of the
    header mergeable."""
    for rel, block in (
        ("SETUP.md", read("SETUP.md")),
        ("rules/push-guard.md", section(read("rules/push-guard.md"), "## Remediation")),
    ):
        lines = code_lines(block)
        write = first_index(lines, "> .bridge-origin")
        assert "grep '^#' .bridge-origin" in " ".join(lines[: write + 1]), (
            f"{rel}: the marker write drops the shipped comment header"
        )


# --- D4 only creates the identity files, it never writes an import ---------


FORBID = ("Never write an `@`-import anywhere, and never create a `CLAUDE.md`: "
          "a `CLAUDE.md` at the root would make Claude Code skip `AGENTS.md`.")


def test_d4_writes_no_import():
    wf = read("skills/bridge-onboard/references/workflow.md")
    d4 = "### D4" + wf.split("### D4", 1)[1].split("\n### ", 1)[0]
    assert FORBID in d4, "D4 must forbid writing an import or a CLAUDE.md"
    assert "CLAUDE.md" not in d4.replace(FORBID, ""), "D4 still names CLAUDE.md"
    assert "edits no other file" in d4
    readme = read("identity/agent/README.md")
    loading = readme.split("## Loading order", 1)[1].split("\n## ", 1)[0]
    assert "imported into `CLAUDE.md`" not in loading
    assert "CLAUDE.md" not in loading
