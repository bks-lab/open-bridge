#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Pytest suite for scripts/check-doc-routes.py.

CONTRACT, this file is the authoritative spec for that surface.

WHY THIS EXISTS. Trimming an always-on file works by replacing an explanation
with a pointer to the file that owns it. That trade is only sound while the
pointer resolves. A pointer at a file that was renamed, or never existed, is
strictly worse than the paragraph it replaced: the paragraph was at least
readable, and a dead pointer fails silently, at the moment somebody needed the
thing it pointed at.

So every path an always-on document names has to resolve, and that has to be a
build gate rather than a habit.

    ROUTED_DOCS
        The always-on documents whose pointers are load-bearing.

    extract_routes(text) -> list[str]
        Markdown links only, `[label](path)`. A link is a navigation promise;
        a backticked path is prose, and prose names things that legitimately do
        not exist in a given clone.

        That line was drawn by measurement, not taste. Checking backticked paths
        too produced 24 violations on a healthy tree and not one of them was a
        bug: path fragments written for readability (`personas/` for
        `identity/personas/`), USER data absent in a fresh clone by design
        (`work/log.md`, `rules/user/`), derived and gitignored files
        (`.bridge/skill-scope.md`), a sibling repo (`wiki/`), and one branch name
        that merely looks like a directory (`user/`). A gate with 24 false
        positives on a healthy repo is not a gate; it is a thing people learn to
        skip. So a load-bearing pointer is written as a link, and then it is
        checked.

        A placeholder (`workflow/projects/<slug>.yaml`), an external URL and a
        bare anchor are not routes. A path with an anchor is returned without
        it: the file is what must exist.

    check_routes(repo_root, docs) -> list[str]
        One violation per unresolvable route, naming the document it sits in.

    main(argv) -> int
        0 when every route resolves, 1 otherwise.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check-doc-routes.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("check_doc_routes", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_doc_routes"] = mod
    spec.loader.exec_module(mod)
    return mod


dr = _load_module()


# ---------------------------------------------------------- what is a route --

def test_a_markdown_link_is_a_route():
    assert "rules/theme.md" in dr.extract_routes("see [the theme](rules/theme.md)")


def test_a_backticked_path_is_prose_not_a_route():
    """Prose names things that legitimately do not exist in a given clone.
    See the module docstring for the 24 false positives that settled this."""
    assert dr.extract_routes("owner: `rules/theme.md`") == []


def test_a_directory_link_is_a_route():
    assert "infra/remotes/" in dr.extract_routes("[machines](infra/remotes/)")


def test_an_anchor_is_stripped_so_the_file_is_what_must_exist():
    assert "docs/structure.md" in dr.extract_routes("[x](docs/structure.md#layout)")


def test_a_placeholder_is_not_a_route():
    """`<slug>` is a shape, not a file. Demanding it exist would make the gate
    unusable exactly where the docs are most useful."""
    assert dr.extract_routes("read `workflow/projects/<slug>.yaml`") == []


def test_an_external_url_is_not_a_route():
    assert dr.extract_routes("[spec](https://agents.md/)") == []


def test_a_bare_anchor_is_not_a_route():
    assert dr.extract_routes("[jump](#promote)") == []


def test_a_word_in_backticks_is_not_a_route():
    assert dr.extract_routes("set `scope: always` and pass `--mutate`") == []


def test_a_path_fragment_written_for_readability_is_not_a_route():
    """`personas/` in prose means `identity/personas/`. Demanding the fragment
    resolve was one of the 24 false positives."""
    assert dr.extract_routes("instances live in `personas/`") == []


# --------------------------------------------------------------- the check --

def test_a_resolving_route_passes(tmp_path):
    (tmp_path / "rules").mkdir()
    (tmp_path / "rules" / "theme.md").write_text("x", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("see [t](rules/theme.md)", encoding="utf-8")
    assert dr.check_routes(tmp_path, ["AGENTS.md"]) == []


def test_a_dead_route_is_reported_with_its_document(tmp_path):
    (tmp_path / "AGENTS.md").write_text("see [g](rules/gone.md)", encoding="utf-8")
    violations = dr.check_routes(tmp_path, ["AGENTS.md"])
    assert any("gone.md" in v and "AGENTS.md" in v for v in violations)


def test_a_document_that_is_absent_is_skipped_not_fatal(tmp_path):
    """An instance does not carry every routed document."""
    assert dr.check_routes(tmp_path, ["AGENTS.md"]) == []


def test_a_link_in_a_nested_doc_resolves_against_its_folder(tmp_path):
    """`.github/copilot-instructions.md` links `../AGENTS.md`, which is only
    valid relative to its own folder, the way every markdown renderer reads it."""
    (tmp_path / "AGENTS.md").write_text("x", encoding="utf-8")
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "x.md").write_text("[a](../AGENTS.md)", encoding="utf-8")
    assert dr.check_routes(tmp_path, [".github/x.md"]) == []

    (tmp_path / ".github" / "x.md").write_text("[b](AGENTS.md)", encoding="utf-8")
    violations = dr.check_routes(tmp_path, [".github/x.md"])
    assert any(".github/x.md" in v and "AGENTS.md" in v for v in violations), violations


def test_claude_md_is_not_a_routed_doc():
    """CORE ships no root CLAUDE.md; a fork's legacy one is USER."""
    assert "CLAUDE.md" not in dr.ROUTED_DOCS


def test_copilot_instructions_is_a_routed_doc():
    assert ".github/copilot-instructions.md" in dr.ROUTED_DOCS


# ---------------------------------------------------------------- the gate --

def test_the_gate_exits_zero_when_every_route_resolves(tmp_path):
    (tmp_path / "AGENTS.md").write_text("nothing routed here", encoding="utf-8")
    assert dr.main(["--repo-root", str(tmp_path)]) == 0


def test_the_gate_exits_one_on_a_dead_route(tmp_path):
    (tmp_path / "AGENTS.md").write_text("see [g](rules/gone.md)", encoding="utf-8")
    assert dr.main(["--repo-root", str(tmp_path)]) == 1


def test_the_live_tree_has_no_dead_routes():
    """The gate on the repo itself. If this fails, a pointer in an always-on
    document leads nowhere and somebody will follow it."""
    assert dr.check_routes(REPO_ROOT, dr.ROUTED_DOCS) == []
