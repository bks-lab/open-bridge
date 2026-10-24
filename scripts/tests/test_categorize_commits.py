#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Pytest suite for scripts/categorize-commits.py — the /promote scope router.

CONTRACT — this file is the authoritative spec for the classifier's public
surface after the `personal` tier was added (the fourth scope, alongside
core / org / user). It pins the load-bearing behaviours:

    classify_file(path) -> "core" | "org" | "user" | "personal"
        - CLUSTER-WRAPPER CONFIG FILES (identity/{personas,mandants,accounts,
          contracts}, infra/channels, workflow/{contexts,projects}): a
          frontmatter `scope:` WINS over the path default. Mapping:
          personal->personal, org->org, user->user, core->core,
          private->user. NO frontmatter scope ⇒ fall through to the existing
          path rules (which default these paths to user) — the fail-safe
          direction: a mis-/missing tag never leaks upward, it just fails to
          promote.
        - PERSONAL path tiers: rules/personal/**, ecosystem.personal.yaml,
          ecosystem.local.yaml -> personal.
        - The pre-existing LIVE gap is closed: ecosystem.<org>.yaml -> org
          (was CORE), ecosystem.local.yaml -> personal (was CORE).
        - Everything previously core/org/user is unchanged.

    category_for_scopes(scopes: set) -> "CORE"|"Org"|"USER"|"Personal"|"MIXED"
        Pure scope-set -> commit-category collapse. Mirrors the existing
        {core}->CORE / {org}|{core,org}->Org pattern, adds
        {personal}|{core,personal}->Personal. Any cross-tier mix (org+personal,
        user+personal, user+org, core+user, ...) stays MIXED.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "scripts" / "categorize-commits.py"


@pytest.fixture(scope="module")
def cc() -> types.ModuleType:
    """Load scripts/categorize-commits.py via importlib (hyphenated filename)."""
    spec = importlib.util.spec_from_file_location("categorize_commits", MODULE_PATH)
    assert spec and spec.loader, f"could not build an import spec for {MODULE_PATH}"
    module = importlib.util.module_from_spec(spec)
    sys.modules["categorize_commits"] = module
    spec.loader.exec_module(module)
    return module


def _write(root: Path, relpath: str, scope: str | None = None, body: str = "x: 1\n") -> None:
    """Write a fixture in the SAME shape the real repo uses:
    - `.yaml` cluster-wrapper config → BARE top-level `scope:` key (no fence),
      because a `---` fence would break yaml.safe_load. This mirrors reality;
      the earlier suite falsely fenced YAML and masked the bare-key classifier gap.
    - `.md` (rules/agents/IDENTITY/SOUL) → a `---` frontmatter fence.
    """
    p = root / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    if scope is None:
        p.write_text(body, encoding="utf-8")
    elif relpath.endswith(".yaml"):
        p.write_text(f"schema_version: 1\nscope: {scope}\n{body}", encoding="utf-8")
    else:
        p.write_text(f"---\nscope: {scope}\n---\n{body}", encoding="utf-8")


@pytest.fixture
def in_tmp_repo(tmp_path, monkeypatch):
    """classify_file reads frontmatter via paths relative to CWD → chdir tmp."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


# --- cluster-wrapper: frontmatter wins over path default ---------------------

def test_persona_scope_personal_classifies_personal(cc, in_tmp_repo):
    _write(in_tmp_repo, "identity/personas/alice-freelancer.yaml", scope="personal")
    assert cc.classify_file("identity/personas/alice-freelancer.yaml") == "personal"


def test_persona_scope_user_classifies_user(cc, in_tmp_repo):
    _write(in_tmp_repo, "identity/personas/alice-work.yaml", scope="user")
    assert cc.classify_file("identity/personas/alice-work.yaml") == "user"


def test_persona_without_frontmatter_falls_back_to_user(cc, in_tmp_repo):
    # fail-safe: a missing tag defaults local-only, never leaks upward.
    _write(in_tmp_repo, "identity/personas/bare.yaml", scope=None)
    assert cc.classify_file("identity/personas/bare.yaml") == "user"


def test_mandant_scope_org_classifies_org(cc, in_tmp_repo):
    _write(in_tmp_repo, "identity/mandants/acme.yaml", scope="org")
    assert cc.classify_file("identity/mandants/acme.yaml") == "org"


def test_account_scope_personal(cc, in_tmp_repo):
    _write(in_tmp_repo, "identity/accounts/alice-mail.yaml", scope="personal")
    assert cc.classify_file("identity/accounts/alice-mail.yaml") == "personal"


def test_contract_scope_personal(cc, in_tmp_repo):
    _write(in_tmp_repo, "identity/contracts/city-power.yaml", scope="personal")
    assert cc.classify_file("identity/contracts/city-power.yaml") == "personal"


def test_channel_scope_user(cc, in_tmp_repo):
    _write(in_tmp_repo, "infra/channels/imessage.yaml", scope="user")
    assert cc.classify_file("infra/channels/imessage.yaml") == "user"


def test_channel_retagged_org(cc, in_tmp_repo):
    # voice-news is an org product; re-tag org must route org, not user.
    _write(in_tmp_repo, "infra/channels/voice-news.yaml", scope="org")
    assert cc.classify_file("infra/channels/voice-news.yaml") == "org"


def test_doc_system_context_driven_by_frontmatter(cc, in_tmp_repo):
    # doc-system.yaml is mixed-scope and stays local; frontmatter (user) wins,
    # NOT the legacy ORG_PATTERNS special-case.
    _write(in_tmp_repo, "workflow/contexts/doc-system.yaml", scope="user")
    assert cc.classify_file("workflow/contexts/doc-system.yaml") == "user"


def test_context_without_frontmatter_falls_through_to_user(cc, in_tmp_repo):
    _write(in_tmp_repo, "workflow/contexts/something.yaml", scope=None)
    assert cc.classify_file("workflow/contexts/something.yaml") == "user"


def test_schema_template_stay_core(cc, in_tmp_repo):
    # _schema/_template inside a wrapper are CORE (not intercepted, not user).
    _write(in_tmp_repo, "identity/personas/_schema.yaml", scope=None)
    _write(in_tmp_repo, "identity/personas/_template.yaml", scope=None)
    assert cc.classify_file("identity/personas/_schema.yaml") == "core"
    assert cc.classify_file("identity/personas/_template.yaml") == "core"


# --- personal path tiers -----------------------------------------------------

def test_rules_personal_is_personal(cc, in_tmp_repo):
    _write(in_tmp_repo, "rules/personal/finance.md", scope=None, body="# finance\n")
    assert cc.classify_file("rules/personal/finance.md") == "personal"


def test_rules_user_unchanged(cc, in_tmp_repo):
    _write(in_tmp_repo, "rules/user/migration-playbook.md", scope=None, body="# x\n")
    assert cc.classify_file("rules/user/migration-playbook.md") == "user"


def test_rules_org_unchanged(cc, in_tmp_repo):
    _write(in_tmp_repo, "rules/org/wiki.md", scope=None, body="# x\n")
    assert cc.classify_file("rules/org/wiki.md") == "org"


# --- ecosystem fragments: the LIVE leak fix ---------------------------------

def test_ecosystem_org_fragment_is_org_not_core(cc, in_tmp_repo):
    _write(in_tmp_repo, "ecosystem.acme.yaml", scope=None, body="org: acme\n")
    assert cc.classify_file("ecosystem.acme.yaml") == "org"


def test_ecosystem_local_is_personal_not_core(cc, in_tmp_repo):
    _write(in_tmp_repo, "ecosystem.local.yaml", scope=None, body="freelance: {}\n")
    assert cc.classify_file("ecosystem.local.yaml") == "personal"


def test_ecosystem_personal_is_personal(cc, in_tmp_repo):
    _write(in_tmp_repo, "ecosystem.personal.yaml", scope=None, body="freelance: {}\n")
    assert cc.classify_file("ecosystem.personal.yaml") == "personal"


def test_ecosystem_base_is_user(cc, in_tmp_repo):
    # The instance base carries one machine's local_root and paths; an org
    # shares its own ecosystem.<org>.yaml instead.
    _write(in_tmp_repo, "ecosystem.yaml", scope=None, body="org: acme\nlocal_root: ~/src\n")
    assert cc.classify_file("ecosystem.yaml") == "user"
    _write(in_tmp_repo, "ecosystem.acme.yaml", scope=None, body="org: acme\n")
    assert cc.classify_file("ecosystem.acme.yaml") == "org"


# --- unchanged core / skill routing -----------------------------------------

def test_generic_doc_is_core(cc, in_tmp_repo):
    _write(in_tmp_repo, "docs/structure.md", scope=None, body="# doc\n")
    assert cc.classify_file("docs/structure.md") == "core"


def test_work_is_user(cc, in_tmp_repo):
    _write(in_tmp_repo, "work/log.md", scope=None, body="# log\n")
    assert cc.classify_file("work/log.md") == "user"


def test_skill_scope_personal_via_frontmatter(cc, in_tmp_repo):
    (in_tmp_repo / "skills/moneymoney").mkdir(parents=True)
    (in_tmp_repo / "skills/moneymoney/SKILL.md").write_text(
        "---\nname: moneymoney\nmetadata:\n  scope: personal\n---\n# x\n", encoding="utf-8"
    )
    assert cc.classify_file("skills/moneymoney/references/foo.md") == "personal"


# --- commit-category collapse ------------------------------------------------

@pytest.mark.parametrize("scopes,expected", [
    ({"core"}, "CORE"),
    ({"org"}, "Org"),
    ({"core", "org"}, "Org"),
    ({"user"}, "USER"),
    ({"personal"}, "Personal"),
    ({"core", "personal"}, "Personal"),
    ({"personal", "org"}, "MIXED"),
    ({"personal", "user"}, "MIXED"),
    ({"user", "org"}, "MIXED"),
    ({"core", "user"}, "MIXED"),
])
def test_category_for_scopes(cc, scopes, expected):
    assert cc.category_for_scopes(set(scopes)) == expected


# --- read_frontmatter_scope: both real on-disk shapes (regression: bare-key gap) ---

def test_read_frontmatter_scope_bare_yaml_key(cc, in_tmp_repo):
    # real cluster-wrapper YAML carries a BARE top-level scope key, NO fence.
    (in_tmp_repo / "identity/personas").mkdir(parents=True)
    (in_tmp_repo / "identity/personas/p.yaml").write_text(
        "schema_version: 1\nscope: personal\nid: p\n", encoding="utf-8")
    assert cc.read_frontmatter_scope("identity/personas/p.yaml") == "personal"
    assert cc.classify_file("identity/personas/p.yaml") == "personal"


def test_read_frontmatter_scope_fenced_md(cc, in_tmp_repo):
    (in_tmp_repo / "rules").mkdir(parents=True)
    (in_tmp_repo / "rules/x.md").write_text("---\nscope: core\n---\n# x\n", encoding="utf-8")
    assert cc.read_frontmatter_scope("rules/x.md") == "core"


def test_bare_scope_only_matches_top_level(cc, in_tmp_repo):
    # an indented `scope:` (nested, not a top-level key) must NOT be read as tier;
    # no top-level scope → None → classify falls back to user (fail-safe).
    (in_tmp_repo / "identity/personas").mkdir(parents=True)
    (in_tmp_repo / "identity/personas/q.yaml").write_text(
        "schema_version: 1\nmeta:\n  scope: org\nid: q\n", encoding="utf-8")
    assert cc.read_frontmatter_scope("identity/personas/q.yaml") is None
    assert cc.classify_file("identity/personas/q.yaml") == "user"


# --- Regression: the 2000-byte read window silently downgraded org → user ------
# Measured on a live tree: two board registries carried `scope: org` at byte
# 2101 and byte 3127, both behind a long non-English comment header. read_frontmatter_scope() read only the first 2000
# bytes, found nothing, and classify_file() fell through to the path default
# `user`. The direction is fail-safe (nothing leaks upward), but the consequence is
# real: scripts/overlay-export.py then treats the file as out-of-scope, and its
# mirror copy in the org overlay is pruned as stale. Both board registries were
# scheduled for deletion by a dry-run export before this was found.

def _long_header(bytes_before: int) -> str:
    """A comment header that pushes the first real key past `bytes_before`."""
    line = "# " + ("Comment line with multibyte characters äöüß € that lengthens the header. " * 2) + "\n"
    n = (bytes_before // len(line.encode("utf-8"))) + 1
    return line * n


def test_bare_yaml_scope_behind_a_long_comment_header(cc, in_tmp_repo):
    """A top-level `scope:` is a top-level key wherever it stands in the file."""
    p = in_tmp_repo / "workflow" / "projects" / "board.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_long_header(2500) + "scope: org\nnumber: 26\n", encoding="utf-8")
    assert len(p.read_text(encoding="utf-8").encode("utf-8")) > 2500
    assert cc.read_frontmatter_scope("workflow/projects/board.yaml") == "org"
    assert cc.classify_file("workflow/projects/board.yaml") == "org"


def test_fenced_md_scope_after_a_long_frontmatter_block(cc, in_tmp_repo):
    """A fenced `.md` whose CLOSING fence sits past the old window. The block is
    read as a whole, so `scope:` must be found wherever it stands inside it."""
    p = in_tmp_repo / "rules" / "org" / "long.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("---\n" + _long_header(2500) + "scope: org\n---\n\ntext\n", encoding="utf-8")
    assert cc.read_frontmatter_scope("rules/org/long.md") == "org"


def test_scope_inside_a_code_block_is_not_frontmatter(cc, in_tmp_repo):
    """Widening the window must not let a documented example become the tier.
    A `scope:` at column 0 inside a fenced code block is prose, not a key."""
    p = in_tmp_repo / "rules" / "org" / "doc.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# Titel\n\n" + _long_header(2500) +
                 "```yaml\nscope: core\n```\n", encoding="utf-8")
    assert cc.read_frontmatter_scope("rules/org/doc.md") is None


def test_indented_scope_is_still_not_a_top_level_key(cc, in_tmp_repo):
    """Widening the window must NOT start matching nested `scope:` values.
    A nested key is indented; only column 0 counts."""
    p = in_tmp_repo / "workflow" / "projects" / "nested.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_long_header(2500) + "block:\n  scope: org\n", encoding="utf-8")
    assert cc.read_frontmatter_scope("workflow/projects/nested.yaml") is None
    assert cc.classify_file("workflow/projects/nested.yaml") == "user"
