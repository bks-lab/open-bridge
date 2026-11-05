"""docs/ is tiered by FOLDER, the way rules/ is.

`docs/` ships wholesale as core. Its `user/`, `org/` and `personal/` subfolders
are the only places a doc of another tier may live, and there the folder
decides. A `scope:` line in a doc is a backstop that must agree with the
folder; it never moves a file between tiers on its own.

Before this suite a doc carrying `scope: user` lay in `docs/` beside the CORE
guides, guarded by that one line. A typo (`scope: usr`) or a deleted line sent
it to the public upstream, and `test_scope_docs.py` held the typo case as the
intended behaviour. These tests hold the router (`classify_file`), the shared
placement helper (`doc_placement`) and the validator surface
(`validate-bridge.py`, `docs_tier_problems`) to the folder rule.

Run: python3 -m pytest scripts/tests/test_docs_tier.py -q
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cc = _load("categorize_commits_docs_tier", "scripts/categorize-commits.py")
vb = _load("validate_bridge_docs_tier", "scripts/validate-bridge.py")


def _write(root: pathlib.Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _doc(scope: str | None) -> str:
    head = f"---\nscope: {scope}\nsummary: x\n---\n" if scope else "---\nsummary: x\n---\n"
    return head + "# Example\n"


@pytest.fixture
def tree(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


# ------------------------------------------------------------- the router --

@pytest.mark.parametrize("path,scope,expected", [
    # The folder is the tier, whatever the line says.
    ("docs/user/example.md", None, "user"),
    ("docs/user/example.md", "core", "user"),
    ("docs/org/example.md", None, "org"),
    ("docs/org/example.md", "core", "org"),
    ("docs/personal/example.md", None, "personal"),
    ("docs/personal/example.md", "core", "personal"),
    ("docs/user/deeper/example.md", None, "user"),
    # Outside the tier folders: undeclared or core is core.
    ("docs/example.md", None, "core"),
    ("docs/example.md", "core", "core"),
    # A declared other tier is still honoured as a backstop (the validator
    # reports the file as misplaced), so an instance that has not migrated yet
    # never leaks on its next promote.
    ("docs/example.md", "user", "user"),
    ("docs/example.md", "private", "user"),
    ("docs/example.md", "org", "org"),
    # An unrecognised token fails CLOSED: a typo never ships a doc.
    ("docs/example.md", "usr", "user"),
    ("docs/example.md", "privat", "user"),
])
def test_docs_route_by_folder(tree, path, scope, expected):
    _write(tree, path, _doc(scope))
    assert cc.classify_file(path) == expected


def test_non_markdown_in_a_tier_folder_follows_the_folder(tree):
    _write(tree, "docs/user/diagram.png", "x")
    _write(tree, "docs/org/data.yaml", "a: 1\n")
    assert cc.classify_file("docs/user/diagram.png") == "user"
    assert cc.classify_file("docs/org/data.yaml") == "org"


def test_kernel_ships_only_the_files_it_names(tree):
    # kernel/ is enumerated, like mods/: the manifest ships, a stray file in the
    # folder stays local (fail closed) and check-kernel.py names it.
    _write(tree, "kernel/manifest.yaml", "schema_version: 1\n")
    _write(tree, "kernel/stray.md", _doc("user"))
    _write(tree, "kernel/notes.yaml", "a: 1\n")
    assert cc.classify_file("kernel/manifest.yaml") == "core"
    _write(tree, "kernel/families.yaml", "families: []\n")
    assert cc.classify_file("kernel/families.yaml") == "core"
    assert cc.classify_file("kernel/stray.md") == "user"
    assert cc.classify_file("kernel/notes.yaml") == "user"


@pytest.mark.parametrize("line", ['scope: "user"', "scope: 'user'", "scope: User", "scope: USER",
                                  "scope:  user  ", "scope: user # mine"])
def test_a_quoted_or_capitalised_scope_is_still_read(tree, line):
    _write(tree, "docs/mine.md", f"---\n{line}\nsummary: x\n---\n# Mine\n")
    assert cc.classify_file("docs/mine.md") == "user"
    place = cc.doc_placement("docs/mine.md", tree)
    assert place.declared == "user" and not place.unknown


@pytest.mark.parametrize("line", ['scope: "usr"', "scope: Core-ish", "scope: 42", "scope:"])
def test_any_other_scope_value_in_a_doc_fails_closed(tree, line):
    _write(tree, "docs/mine.md", f"---\n{line}\nsummary: x\n---\n# Mine\n")
    assert cc.classify_file("docs/mine.md") == "user"
    assert cc.doc_placement("docs/mine.md", tree).unknown


# ------------------------------------------------------- doc_placement() --

@pytest.mark.parametrize("path,scope,folder,declared", [
    ("docs/example.md", None, "core", None),
    ("docs/example.md", "core", "core", "core"),
    ("docs/example.md", "user", "core", "user"),
    ("docs/example.md", "usr", "core", "?"),
    ("docs/user/example.md", "core", "user", "core"),
    ("docs/org/sub/example.md", "org", "org", "org"),
])
def test_doc_placement_reports_folder_and_declared_tier(tree, path, scope, folder, declared):
    _write(tree, path, _doc(scope))
    got = cc.doc_placement(path, tree)
    assert got.folder == folder
    assert got.token == scope
    assert got.declared == (None if declared is None else (None if declared == "?" else declared))
    assert got.unknown == (declared == "?")


def test_doc_placement_ignores_a_scope_after_the_frontmatter(tree):
    _write(tree, "docs/example.md", "---\nsummary: x\n---\n```yaml\nscope: user\n```\n")
    assert cc.doc_placement("docs/example.md", tree).token is None
    assert cc.classify_file("docs/example.md") == "core"


def test_a_fenced_frontmatter_example_in_a_doc_without_frontmatter_is_not_its_own(tree):
    # A guide that shows a frontmatter block as an example must not take the
    # example's scope as its own: only a block at the very top is frontmatter.
    text = "# Personas\n\nA persona file starts like this:\n\n```markdown\n---\nscope: user\n---\n```\n"
    _write(tree, "docs/example.md", text)
    assert cc.doc_placement("docs/example.md", tree).token is None
    assert cc.classify_file("docs/example.md") == "core"


@pytest.mark.parametrize("text", [
    "# yaml-language-server: $schema=./_schema.yaml\n---\nscope: user\n---\n# Mine\n",
    "\n---\nscope: user\n---\n# Mine\n",
    "<!-- note -->\n---\nscope: user\n---\n# Mine\n",
    "scope: user\n\n# Mine\n",
    "# Mine\n\nscope: user\n",
])
def test_a_scope_line_outside_the_top_frontmatter_fails_closed_and_is_named(tree, text):
    # The old reader found these and kept the doc local; the anchored reader
    # alone would have shipped them. They stay user and the validator asks for
    # the line to move into a frontmatter block at the very top.
    _write(tree, "docs/mine.md", text)
    assert cc.classify_file("docs/mine.md") == "user"
    place = cc.doc_placement("docs/mine.md", tree)
    assert place.stray and place.declared == "user"
    [(rel, message)] = vb.docs_tier_problems(tree)
    assert rel == "docs/mine.md" and "top" in message


# ------------------------------------------------------- the validator --

def test_a_clean_docs_tree_has_no_problems(tree):
    _write(tree, "docs/guide.md", _doc(None))
    _write(tree, "docs/other.md", _doc("core"))
    _write(tree, "docs/user/mine.md", _doc(None))
    _write(tree, "docs/user/tagged.md", _doc("user"))
    _write(tree, "docs/org/shared.md", _doc("org"))
    assert vb.docs_tier_problems(tree) == []


def test_a_user_doc_beside_the_core_guides_is_a_problem_that_names_the_fix(tree):
    _write(tree, "docs/mine.md", _doc("user"))
    problems = vb.docs_tier_problems(tree)
    assert len(problems) == 1
    rel, message = problems[0]
    assert rel == "docs/mine.md"
    assert "docs/user/" in message
    assert "migrate-docs-tier.py" in message


def test_a_tier_folder_and_a_disagreeing_line_is_a_problem(tree):
    _write(tree, "docs/user/mine.md", _doc("core"))
    [(rel, message)] = vb.docs_tier_problems(tree)
    assert rel == "docs/user/mine.md"
    assert "disagree" in message


def test_an_unknown_scope_in_docs_is_a_problem(tree):
    _write(tree, "docs/mine.md", _doc("usr"))
    [(rel, message)] = vb.docs_tier_problems(tree)
    assert rel == "docs/mine.md"
    assert "usr" in message and "unknown" in message


def test_an_unknown_scope_in_a_tier_folder_is_named_as_that_tier(tree):
    _write(tree, "docs/org/shared.md", _doc("usr"))
    [(rel, message)] = vb.docs_tier_problems(tree)
    assert rel == "docs/org/shared.md" and "unknown" in message
    assert "(org)" in message and "(user)" not in message


def test_the_legacy_user_doc_is_a_problem_until_it_moves(tree):
    # docs/applications.md is the one instance filename the CORE router still
    # names; it stays user so nothing leaks, and the validator asks for the move.
    _write(tree, "docs/applications.md", "# Applications\n")
    assert cc.classify_file("docs/applications.md") == "user"
    [(rel, message)] = vb.docs_tier_problems(tree)
    assert rel == "docs/applications.md"
    assert "docs/user/" in message and "migrate-docs-tier.py" in message


def test_a_tree_without_docs_is_quiet(tree):
    assert vb.docs_tier_problems(tree) == []


def test_the_core_tree_keeps_every_doc_where_its_tier_says():
    if (REPO / "bridge-config.yaml").exists():
        pytest.skip("an instance: validate-bridge.py reports its own docs, see docs/updating.md")
    assert vb.docs_tier_problems(REPO) == []
