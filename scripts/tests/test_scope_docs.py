#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The documented scope model must agree with the router that enforces it.

`scripts/categorize-commits.py` `classify_file()` decides where a file may
travel. Its prose mirror lives in two places a reader actually opens:

* `docs/extension-model.md` § Scope model: the single table of scope values,
  the families whose frontmatter beats the path, and the path rules in router
  order, each with example paths.
* `docs/structure.md`: the per-path tables with a Layer column, and the
  top-level block.

Before this test the two drifted apart without anybody noticing: a document
said USER where the router said org, and a frontmatter list named seven
families where the router read eleven. Each documented row is turned into a
concrete example path here and the router must return the documented tier.
When this test fails, fix the document unless the router is plainly wrong.

Every example is evaluated from an empty temporary directory, so a frontmatter
read finds nothing and the PATH rule answers. Frontmatter precedence is tested
separately with synthetic files. The one walk over the real tree, the
family-row check, looks only at families with a CORE `_template.yaml` or
`_schema.yaml` and skips inside an instance (`bridge-config.yaml` present),
where families of its own are expected and need no CORE row.

Run: python3 -m pytest scripts/tests/test_scope_docs.py -q
"""
from __future__ import annotations

import importlib.util
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
STRUCTURE = REPO / "docs" / "structure.md"
EXTENSION = REPO / "docs" / "extension-model.md"
WRAPPERS = ("identity", "infra", "workflow")

_spec = importlib.util.spec_from_file_location(
    "categorize_commits_docs", REPO / "scripts" / "categorize-commits.py"
)
assert _spec and _spec.loader
cc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cc)

LAYER = {"CORE": "core", "USER": "user", "ORG": "org", "PERSONAL": "personal"}


@pytest.fixture
def empty_cwd(tmp_path, monkeypatch):
    cc._LOGO_BY_THEME_CACHE = None
    monkeypatch.chdir(tmp_path)
    yield tmp_path
    cc._LOGO_BY_THEME_CACHE = None


def _section(text: str, heading: str) -> str:
    """Body of the `## heading` section, up to the next `## `."""
    m = re.search(rf"^## {re.escape(heading)}\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)
    assert m, f"section '## {heading}' not found"
    return m.group(1)


def _rows(block: str) -> list[list[str]]:
    out = []
    for line in block.splitlines():
        if not line.startswith("|") or re.match(r"^\|[\s:|-]+\|$", line):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        out.append(cells)
    return out


def _concrete(path: str) -> str:
    """A documented path pattern turned into one concrete example path."""
    path = re.sub(r"<[^>]+>", "example", path)
    path = path.replace("**", "_tests/case.yaml")
    if path.endswith("/"):
        path += "example.yaml"
    return path


# ---------------------------------------------------------------------------
# docs/structure.md: the per-path tables (`| Path | Layer | Purpose |`)
# ---------------------------------------------------------------------------
def _structure_cases() -> list[tuple[str, str, str]]:
    cases = []
    for cells in _rows(STRUCTURE.read_text(encoding="utf-8")):
        if len(cells) < 3 or cells[0] in ("Path", "Domain"):
            continue
        m = re.fullmatch(r"`([^`]+)`", cells[0])
        # Only a plain Layer: one word, optionally a parenthetical. A Layer that
        # names a split ("CORE · `x/` USER", "Tiered by path") is prose about a
        # mixed folder and is covered by the extension-model rules instead.
        lm = re.fullmatch(r"\**(CORE|USER)\**(?:\s*\([^)]*\))?", cells[1])
        if not (m and lm):
            continue
        cases.append((m.group(1), _concrete(m.group(1)), LAYER[lm.group(1)]))
    return cases


def _toplevel_block_cases() -> list[tuple[str, str, str]]:
    text = _section(STRUCTURE.read_text(encoding="utf-8"), "Top-level")
    block = re.search(r"```\n(.*?)```", text, re.S)
    assert block, "docs/structure.md § Top-level lost its file block"
    cases = []
    for line in block.group(1).splitlines():
        m = re.match(r"^(\S+\.\w+)\s+(\S+)\s", line)
        if not m:
            continue
        layer = m.group(2).split("→")[-1].upper()  # "USER→org": data USER, promote org
        if layer in LAYER:
            cases.append((m.group(1), m.group(1), LAYER[layer]))
    return cases


STRUCTURE_CASES = _structure_cases() + _toplevel_block_cases()


def test_structure_tables_were_parsed():
    # A reformat that silently empties the parse would make every case vanish.
    assert len(STRUCTURE_CASES) > 60, len(STRUCTURE_CASES)


@pytest.mark.parametrize("doc_path,example,expected", STRUCTURE_CASES,
                         ids=[c[0] for c in STRUCTURE_CASES])
def test_structure_row_matches_router(doc_path, example, expected, empty_cwd):
    got = cc.classify_file(example)
    assert got == expected, (
        f"docs/structure.md says `{doc_path}` is {expected!r}, the router sends "
        f"{example} to {got!r}. Correct the document (or the router, if it is wrong)."
    )


def _core_families() -> list[str]:
    """Wrapper families that ship a CORE companion (template or schema)."""
    fams = []
    for wrapper in WRAPPERS:
        for d in sorted((REPO / wrapper).iterdir()):
            if not d.is_dir() or d.name.startswith((".", "_")):
                continue
            companions = [f"{wrapper}/{d.name}/{n}" for n in ("_template.yaml", "_schema.yaml")]
            if any((REPO / c).exists() and cc.classify_file(c) == "core" for c in companions):
                fams.append(f"{wrapper}/{d.name}")
    return fams


def test_every_wrapper_family_has_a_structure_row(monkeypatch):
    """A CORE family with no row in structure.md is undocumented."""
    if (REPO / "bridge-config.yaml").exists():
        pytest.skip("instance tree: its own families need no row in the CORE doc")
    monkeypatch.chdir(REPO)
    text = STRUCTURE.read_text(encoding="utf-8")
    fams = _core_families()
    assert fams, "no wrapper family with a CORE template or schema found"
    missing = [f"{f}/" for f in fams if f"`{f}/" not in text]
    assert not missing, f"families without a row in docs/structure.md: {missing}"


# ---------------------------------------------------------------------------
# docs/extension-model.md § Scope model
# ---------------------------------------------------------------------------
def _scope_section() -> str:
    return _section(EXTENSION.read_text(encoding="utf-8"), "Scope model")


def _table_after(section: str, marker: str) -> list[list[str]]:
    """Rows of the first table that follows a line starting with `marker`."""
    idx = section.find(marker)
    assert idx >= 0, f"marker {marker!r} not found in § Scope model"
    rest = section[idx:]
    m = re.search(r"((?:^\|.*\n)+)", rest, re.M)
    assert m, f"no table after {marker!r}"
    return _rows(m.group(1))[1:]  # drop header


def test_scope_values_table_matches_router_map():
    rows = _table_after(_scope_section(), "**Scope values.**")
    documented = {}
    for cells in rows:
        value = re.fullmatch(r"`([a-z]+)`", cells[0])
        bucket = re.fullmatch(r"`([a-z]+)`", cells[1])
        if value and bucket:
            documented[value.group(1)] = bucket.group(1)
    assert documented == cc._BASE_SCOPE_MAP, (
        "docs/extension-model.md scope values differ from _BASE_SCOPE_MAP in "
        f"scripts/categorize-commits.py: doc={documented} router={cc._BASE_SCOPE_MAP}"
    )


def _documented_dispatch_families() -> set[str]:
    rows = _table_after(_scope_section(), "**Frontmatter beats the path.**")
    fams = set()
    for cells in rows:
        for tok in re.findall(r"`([a-z]+/[a-z0-9-]+)/`", cells[0]):
            if tok.split("/")[0] in WRAPPERS:
                fams.add(tok)
    return fams


def _router_dispatch_families() -> set[str]:
    """The families named in _CLUSTER_WRAPPER_RE, read from the pattern itself."""
    fams = set()
    for wrapper, alts in re.findall(r"(identity|infra|workflow)/\(\?:([^)]+)\)",
                                    cc._CLUSTER_WRAPPER_RE.pattern):
        fams |= {f"{wrapper}/{a}" for a in alts.split("|")}
    assert fams, "could not read the family list out of _CLUSTER_WRAPPER_RE"
    # The parse must agree with what the regex actually matches.
    for f in fams:
        assert cc._CLUSTER_WRAPPER_RE.search(f"{f}/example.yaml"), f
    return fams


def test_frontmatter_family_list_matches_router():
    documented = _documented_dispatch_families()
    router = _router_dispatch_families()
    assert documented == router, (
        "families whose frontmatter `scope:` wins, docs vs _CLUSTER_WRAPPER_RE: "
        f"only in docs {sorted(documented - router)}, only in router {sorted(router - documented)}"
    )


def _path_rule_cases() -> list[tuple[str, str]]:
    rows = _table_after(_scope_section(), "**Path rules, in router order.**")
    cases = []
    for cells in rows:
        tier = re.fullmatch(r"`([a-z]+)`", cells[-1])
        assert tier, f"path-rule row without a single tier: {cells}"
        for ex in re.findall(r"`([^`\s]+)`", cells[1]):
            cases.append((ex, tier.group(1)))
    return cases


PATH_RULE_CASES = _path_rule_cases()


def test_path_rules_were_parsed():
    assert len(PATH_RULE_CASES) > 20, len(PATH_RULE_CASES)


@pytest.mark.parametrize("example,expected", PATH_RULE_CASES,
                         ids=[c[0] for c in PATH_RULE_CASES])
def test_path_rule_example_matches_router(example, expected, empty_cwd):
    got = cc.classify_file(example)
    assert got == expected, (
        f"docs/extension-model.md § Scope model routes `{example}` to {expected!r}, "
        f"the router answers {got!r}."
    )


# ---------------------------------------------------------------------------
# Frontmatter precedence, with synthetic files
# ---------------------------------------------------------------------------
def _write(root: pathlib.Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


@pytest.mark.parametrize("family", sorted(_documented_dispatch_families()))
def test_documented_family_frontmatter_wins(family, empty_cwd):
    _write(empty_cwd, f"{family}/example.yaml", "name: example\nscope: org\n")
    assert cc.classify_file(f"{family}/example.yaml") == "org"


def test_undocumented_family_frontmatter_does_not_win(empty_cwd):
    # A family outside the list: the path decides, whatever the file says.
    _write(empty_cwd, "workflow/meetings/example.yaml", "name: example\nscope: org\n")
    assert cc.classify_file("workflow/meetings/example.yaml") == "user"


PRIVATE_ALIAS_CASES = [
    ("workflow/contexts/example.yaml", "name: example\nscope: private\n"),
    ("docs/example.md", "---\nscope: private\n---\n# Example\n"),
    ("skills/example/SKILL.md",
     "---\nname: example\ndescription: x\nmetadata:\n  scope: private\n---\n"),
    (".claude/agents/example.md", "---\nname: example\nscope: private\n---\n"),
    ("themes/example.yaml", "meta:\n  scope: private\n"),
]


@pytest.mark.parametrize("path,text", PRIVATE_ALIAS_CASES,
                         ids=[c[0] for c in PRIVATE_ALIAS_CASES])
def test_private_is_an_alias_of_user_everywhere(path, text, empty_cwd):
    """The scope-values table promises `private` routes like `user` wherever a
    frontmatter tier is read, so no reader may hand back a raw token."""
    _write(empty_cwd, path, text)
    assert cc.classify_file(path) == "user"


def test_unknown_subagent_scope_fails_closed(empty_cwd):
    _write(empty_cwd, ".claude/agents/example.md", "---\nname: example\nscope: bogus\n---\n")
    assert cc.classify_file(".claude/agents/example.md") == "user"


@pytest.mark.parametrize("path,text,expected", [
    # Fall back to the path: an unrecognised wrapper or theme tag routes like no tag.
    ("workflow/contexts/example.yaml", "name: example\nscope: privat\n", "user"),
    ("themes/example.yaml", "meta:\n  scope: privat\n", "user"),
    # A doc falls back to the docs/ default, which is core. The document says so.
    ("docs/example.md", "---\nscope: privat\n---\n# Example\n", "core"),
    # Skills fail closed.
    ("skills/example/SKILL.md",
     "---\nname: example\ndescription: x\nmetadata:\n  scope: privat\n---\n", "user"),
], ids=["wrapper", "theme", "doc", "skill"])
def test_unrecognised_token_behaves_as_documented(path, text, expected, empty_cwd):
    _write(empty_cwd, path, text)
    assert cc.classify_file(path) == expected


def test_skill_journal_stays_user_in_a_core_skill(empty_cwd):
    _write(empty_cwd, "skills/example/SKILL.md",
           "---\nname: example\ndescription: x\nmetadata:\n  scope: core\n---\n")
    assert cc.classify_file("skills/example/SKILL.md") == "core"
    assert cc.classify_file("skills/example/LEARNINGS.md") == "user"


def test_org_path_pattern_beats_a_subagent_tag(empty_cwd):
    prefixes = [re.match(r"\^\\\.claude/agents/([\w-]+)$", p) for p in cc.ORG_PATTERNS]
    prefixes = [m.group(1) for m in prefixes if m]
    if not prefixes:
        pytest.skip("no org path pattern for sub-agents in this router")
    path = f".claude/agents/{prefixes[0]}example.md"
    _write(empty_cwd, path, "---\nname: example\nscope: core\n---\n")
    assert cc.classify_file(path) == "org"
