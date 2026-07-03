#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Pytest suite for scripts/okf-export.py (the Tier 1 OKF v0.1 exporter).

CONTRACT — this file is the authoritative spec for the exporter's public
surface (read against scripts/extract-frontmatter.py and
scripts/gen-board.py for the existing hand-rolled-parsing conventions this
repo already uses). scripts/okf-export.py implements this exact surface:

    OKF_VERSION: str                                            = "0.1"

    parse_frontmatter(text: str) -> tuple[dict, str]
        Hand-rolled (NO PyYAML dependency, mirrors gen-board.py's
        parse_status()). Skips leading `# ...` comment lines (the
        `# yaml-language-server: $schema=...` prolog convention) before the
        first `---` fence. Reads the first `---`...`---` block as flat
        `key: value` scalar pairs, stripping a trailing inline `# comment`
        and surrounding quotes. Returns (frontmatter_dict, body_text).
        A file with NO frontmatter block returns ({}, text) — the body is
        the untouched original text.

    concept_slug(path: Path) -> str
        `STATUS.md` -> parent directory name (task/stream slug, same
        convention as gen-board.py). Any other filename -> the file's stem.

    derive_title(frontmatter: dict, body: str, fallback: str) -> str
        frontmatter["title"] -> first `# ` H1 line in body -> fallback.

    derive_description(frontmatter: dict, body: str) -> str
        frontmatter["description"] -> frontmatter["summary"] ->
        frontmatter["headline"] -> "" (never derived from body).

    resolve_wikilinks(text: str, slug_to_relpath: dict[str, str]) -> tuple[str, list[str]]
        Replaces every `[[slug]]` occurrence where slug is a kebab-case
        identifier (`[a-z][a-z0-9-]*`): if slug is a key in
        slug_to_relpath, becomes a markdown link `[slug](relpath)`;
        otherwise the `[[slug]]` text is left completely untouched (OKF
        tolerates dangling references; rewriting them would corrupt
        content) and the slug is appended to the returned unresolved list.
        Non-kebab bracket pairs — e.g. bash `[[ -f file ]]` conditionals
        inside code blocks — never match and are never reported.

    discover_sources(root: Path, scope: str) -> list[Path]
        scope == "user": every work/tasks/*/STATUS.md,
        work/streams/*/STATUS.md, work/done/*/*/STATUS.md, every
        */deliverables/*.md under work/, every docs/**/*.md, rules/**/*.md
        and examples/**/*.md under root.
        scope == "core": ONLY docs/**/*.md + examples/**/*.md (work/ and
        rules/ excluded entirely — this is the public-safe subset for a
        demo export).
        Any other scope string raises ValueError.

    concept_type_for(path: Path, root: Path) -> str
        .../work/tasks/<slug>/STATUS.md      -> "task"
        .../work/streams/<slug>/STATUS.md    -> "stream"
        .../work/done/<month>/<slug>/STATUS.md -> "task"
        .../deliverables/*.md                -> "deliverable"
        docs/**/*.md                         -> "doc"
        rules/**/*.md                        -> "rule"
        examples/**/*.md                     -> "example"

    build_concept(path: Path, root: Path) -> dict
        {"slug": str, "okf_type": str, "title": str, "description": str,
         "timestamp": str, "tags": list[str], "body": str}
        `timestamp` <- frontmatter.get("last_updated") or
        frontmatter.get("created") or "". `tags` <- [frontmatter["status"]]
        + [frontmatter["context"]] (only the ones present), else [].
        `body` is the RAW markdown body (wikilinks not yet resolved).

    write_bundle(root: Path, out_dir: Path, scope: str) -> dict
        Orchestrates discover_sources -> build_concept (all) -> a
        slug->relpath index -> resolve_wikilinks over every body -> writes
        out_dir/<type>/<slug>.md (OKF frontmatter type/title/description/
        timestamp/tags + resolved body) for every populated type, writes
        out_dir/<type>/index.md per populated type directory, and writes
        out_dir/index.md (root) whose frontmatter carries
        `okf_version: "0.1"`. Deterministic + idempotent: re-running with
        unchanged input produces byte-identical file sets. Returns a
        manifest: {"okf_version": "0.1", "scope": scope,
        "concept_count": int, "unresolved_wikilinks": list[str]}.

    main(argv: list[str] | None = None) -> int
        argparse CLI: --root (default "."), --out (required), --scope
        {"user","core"} (default "user"; invalid choice -> argparse
        SystemExit). Non-existent/non-dir --root -> prints to stderr,
        returns a non-zero exit code (no traceback). On success prints a
        one-line summary and returns 0.

Hermetic: every test builds its own synthetic mini-instance under tmp_path
(generic names only — "acme", "sample-task" — never real repo/customer
content) and never touches the real repo tree beyond importing the module
under test.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "scripts" / "okf-export.py"


@pytest.fixture(scope="module")
def okf_export() -> types.ModuleType:
    """Load scripts/okf-export.py via importlib.util (not on sys.path)."""
    spec = importlib.util.spec_from_file_location("okf_export", MODULE_PATH)
    assert spec is not None and spec.loader is not None, (
        f"could not build an import spec for {MODULE_PATH}"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["okf_export"] = module
    spec.loader.exec_module(module)
    return module


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture
def bridge_root(tmp_path: Path) -> Path:
    """A synthetic mini Bridge instance — generic acme/sample-* names only."""
    root = tmp_path / "acme-instance"

    _write(
        root / "work/tasks/sample-task/STATUS.md",
        "---\n"
        "type: task\n"
        "status: doing\n"
        "context: acme\n"
        "priority: P2\n"
        "created: 2026-01-01\n"
        "last_updated: 2026-01-05\n"
        'headline: "Kickoff automation for Acme"\n'
        "---\n\n"
        "# Sample Task\n\n"
        "Body text describing the sample task for the fixture.\n",
    )
    _write(
        root / "work/tasks/sample-task/deliverables/summary.md",
        "---\n"
        'summary: "Deliverable summary text for Acme"\n'
        "last_updated: 2026-01-04\n"
        "---\n\n"
        "# Summary\n\n"
        "Deliverable body content.\n",
    )
    _write(
        root / "work/streams/sample-stream/STATUS.md",
        "---\n"
        "type: stream\n"
        "status: doing\n"
        "context: acme\n"
        "created: 2026-01-01\n"
        "---\n\n"
        "# Sample Stream\n\n"
        "Stream body content.\n",
    )
    _write(
        root / "work/done/2026-01/finished-task/STATUS.md",
        "---\n"
        "status: done\n"
        "outcome: shipped\n"
        "context: acme\n"
        "created: 2025-12-01\n"
        "last_updated: 2026-01-02\n"
        "---\n\n"
        "# Finished Task\n\n"
        "Closed task body.\n",
    )
    _write(
        root / "docs/sample-doc.md",
        "# yaml-language-server: $schema=./_schema.yaml\n"
        "---\n"
        'summary: "Doc about acme"\n'
        "last_updated: 2026-01-03\n"
        "---\n\n"
        "# Sample Doc\n\n"
        "See [[sample-rule]] and [[missing-thing]] for more.\n",
    )
    _write(
        root / "rules/sample-rule.md",
        "# Sample Rule\n\n"
        "Some rule text with no frontmatter at all.\n",
    )
    _write(
        root / "examples/acme-demo/README.md",
        "# Acme Demo\n\n"
        "Example content for the acme demo.\n",
    )
    return root


@pytest.fixture
def memory_dir(tmp_path: Path) -> Path:
    """A synthetic auto-memory directory (lives OUTSIDE the instance root)."""
    mem = tmp_path / "memory"

    _write(
        mem / "feedback_acme_preference.md",
        "---\n"
        "name: acme-preference\n"
        "description: Acme prefers weekly summaries over daily pings\n"
        "metadata:\n"
        "  type: feedback\n"
        "---\n\n"
        "Acme prefers weekly summaries. See [[sample-rule]].\n",
    )
    _write(
        mem / "reference_acme_endpoint.md",
        "---\n"
        "name: acme-endpoint\n"
        "description: The Acme staging endpoint and its auth quirk\n"
        "metadata:\n"
        "  type: reference\n"
        "---\n\n"
        "Staging lives behind the acme gateway.\n",
    )
    # Index + provenance files and frontmatter-less strays must be skipped.
    _write(mem / "MEMORY.md", "# Memory Index\n\n- [Acme preference](feedback_acme_preference.md)\n")
    _write(mem / "MEMORY-ARCHIVE.md", "# Archive\n")
    _write(mem / "PROVENANCE.md", "# Provenance\n")
    _write(mem / "scratch-note.md", "No frontmatter here, not a memory fact.\n")
    return mem


# --------------------------------------------------------------------------
# parse_frontmatter
# --------------------------------------------------------------------------

def test_parse_frontmatter_extracts_scalar_fields(okf_export):
    text = "---\nstatus: doing\ncontext: acme\n---\n\nBody paragraph.\n"
    fm, body = okf_export.parse_frontmatter(text)
    assert fm == {"status": "doing", "context": "acme"}
    assert body.strip() == "Body paragraph."


def test_parse_frontmatter_skips_yaml_language_server_comment_prolog(okf_export):
    text = (
        "# yaml-language-server: $schema=./_schema.yaml\n"
        "---\nstatus: doing\n---\n\nBody.\n"
    )
    fm, body = okf_export.parse_frontmatter(text)
    assert fm.get("status") == "doing"
    assert body.strip() == "Body."


def test_parse_frontmatter_strips_quotes_and_inline_comments(okf_export):
    text = (
        '---\nheadline: "Kickoff for Acme"  # short desc\ncontext: acme\n---\n\nBody.\n'
    )
    fm, _ = okf_export.parse_frontmatter(text)
    assert fm.get("headline") == "Kickoff for Acme"
    assert fm.get("context") == "acme"


def test_parse_frontmatter_no_block_returns_empty_dict_and_full_body(okf_export):
    text = "# Just A Heading\n\nNo frontmatter block at all.\n"
    fm, body = okf_export.parse_frontmatter(text)
    assert fm == {}
    assert body == text


# --------------------------------------------------------------------------
# concept_slug
# --------------------------------------------------------------------------

def test_concept_slug_uses_parent_dir_for_status_md(okf_export, bridge_root):
    p = bridge_root / "work/tasks/sample-task/STATUS.md"
    assert okf_export.concept_slug(p) == "sample-task"


def test_concept_slug_uses_filename_stem_for_other_files(okf_export, bridge_root):
    assert okf_export.concept_slug(bridge_root / "docs/sample-doc.md") == "sample-doc"
    assert (
        okf_export.concept_slug(bridge_root / "work/tasks/sample-task/deliverables/summary.md")
        == "summary"
    )


# --------------------------------------------------------------------------
# derive_title / derive_description
# --------------------------------------------------------------------------

def test_derive_title_prefers_frontmatter_title_field(okf_export):
    fm = {"title": "Explicit Title"}
    body = "# Different H1\n\nBody."
    assert okf_export.derive_title(fm, body, fallback="fallback-slug") == "Explicit Title"


def test_derive_title_falls_back_to_h1_heading(okf_export):
    fm = {}
    body = "# Heading From Body\n\nBody text."
    assert okf_export.derive_title(fm, body, fallback="fallback-slug") == "Heading From Body"


def test_derive_title_falls_back_to_provided_fallback(okf_export):
    fm = {}
    body = "No heading here at all."
    assert okf_export.derive_title(fm, body, fallback="fallback-slug") == "fallback-slug"


def test_derive_description_prefers_description_then_summary_then_headline(okf_export):
    assert okf_export.derive_description(
        {"description": "D", "summary": "S", "headline": "H"}, ""
    ) == "D"
    assert okf_export.derive_description({"summary": "S", "headline": "H"}, "") == "S"
    assert okf_export.derive_description({"headline": "H"}, "") == "H"


def test_derive_description_empty_when_nothing_found(okf_export):
    assert okf_export.derive_description({}, "Body without any explicit fields.") == ""


# --------------------------------------------------------------------------
# resolve_wikilinks
# --------------------------------------------------------------------------

def test_resolve_wikilinks_replaces_resolved_slug_with_markdown_link(okf_export):
    text = "See [[sample-rule]] for details."
    new_text, unresolved = okf_export.resolve_wikilinks(text, {"sample-rule": "rule/sample-rule.md"})
    assert "[[sample-rule]]" not in new_text
    assert "[sample-rule](rule/sample-rule.md)" in new_text
    assert unresolved == []


def test_resolve_wikilinks_leaves_unresolved_slug_untouched_and_reports_it(okf_export):
    text = "See [[missing-thing]] for details."
    new_text, unresolved = okf_export.resolve_wikilinks(text, {})
    assert new_text == text  # dangling reference left verbatim, never rewritten
    assert unresolved == ["missing-thing"]


def test_resolve_wikilinks_ignores_bash_conditionals_and_non_kebab_brackets(okf_export):
    text = 'if [[ -f "$file" ]]; then\n  use [[Wiki Style]] links\nfi\n'
    new_text, unresolved = okf_export.resolve_wikilinks(text, {"file": "doc/file.md"})
    assert new_text == text  # neither bracket pair is a kebab wikilink
    assert unresolved == []


def test_resolve_wikilinks_no_wikilinks_returns_text_unchanged(okf_export):
    text = "Plain text, no links here."
    new_text, unresolved = okf_export.resolve_wikilinks(text, {"x": "y"})
    assert new_text == text
    assert unresolved == []


# --------------------------------------------------------------------------
# discover_sources
# --------------------------------------------------------------------------

def test_discover_sources_user_scope_finds_all_seven_fixture_files(okf_export, bridge_root):
    paths = okf_export.discover_sources(bridge_root, "user")
    rels = {p.relative_to(bridge_root).as_posix() for p in paths}
    assert rels == {
        "work/tasks/sample-task/STATUS.md",
        "work/tasks/sample-task/deliverables/summary.md",
        "work/streams/sample-stream/STATUS.md",
        "work/done/2026-01/finished-task/STATUS.md",
        "docs/sample-doc.md",
        "rules/sample-rule.md",
        "examples/acme-demo/README.md",
    }


def test_discover_sources_core_scope_excludes_work_and_rules(okf_export, bridge_root):
    paths = okf_export.discover_sources(bridge_root, "core")
    rels = {p.relative_to(bridge_root).as_posix() for p in paths}
    assert rels == {"docs/sample-doc.md", "examples/acme-demo/README.md"}


def test_discover_sources_unknown_scope_raises_value_error(okf_export, bridge_root):
    with pytest.raises(ValueError):
        okf_export.discover_sources(bridge_root, "bogus")


# --------------------------------------------------------------------------
# concept_type_for
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "relpath,expected_type",
    [
        ("work/tasks/sample-task/STATUS.md", "task"),
        ("work/streams/sample-stream/STATUS.md", "stream"),
        ("work/done/2026-01/finished-task/STATUS.md", "task"),
        ("work/tasks/sample-task/deliverables/summary.md", "deliverable"),
        ("docs/sample-doc.md", "doc"),
        ("rules/sample-rule.md", "rule"),
        ("examples/acme-demo/README.md", "example"),
    ],
)
def test_concept_type_for_maps_each_fixture_path_to_expected_type(
    okf_export, bridge_root, relpath, expected_type
):
    assert okf_export.concept_type_for(bridge_root / relpath, bridge_root) == expected_type


# --------------------------------------------------------------------------
# build_concept
# --------------------------------------------------------------------------

def test_build_concept_task_status_maps_headline_status_context_and_timestamp(okf_export, bridge_root):
    c = okf_export.build_concept(bridge_root / "work/tasks/sample-task/STATUS.md", bridge_root)
    assert c["slug"] == "sample-task"
    assert c["okf_type"] == "task"
    assert c["title"] == "Sample Task"
    assert c["description"] == "Kickoff automation for Acme"
    assert c["timestamp"] == "2026-01-05"
    assert "doing" in c["tags"] and "acme" in c["tags"]


def test_build_concept_doc_uses_summary_field_and_h1_title(okf_export, bridge_root):
    c = okf_export.build_concept(bridge_root / "docs/sample-doc.md", bridge_root)
    assert c["okf_type"] == "doc"
    assert c["title"] == "Sample Doc"
    assert c["description"] == "Doc about acme"
    assert c["timestamp"] == "2026-01-03"
    assert c["tags"] == []


def test_build_concept_rule_without_frontmatter_falls_back_to_h1_and_empty_fields(okf_export, bridge_root):
    c = okf_export.build_concept(bridge_root / "rules/sample-rule.md", bridge_root)
    assert c["okf_type"] == "rule"
    assert c["title"] == "Sample Rule"
    assert c["description"] == ""
    assert c["timestamp"] == ""
    assert c["tags"] == []


# --------------------------------------------------------------------------
# write_bundle
# --------------------------------------------------------------------------

def test_write_bundle_user_scope_manifest_counts_and_version(okf_export, bridge_root, tmp_path):
    out = tmp_path / "bundle-user"
    manifest = okf_export.write_bundle(bridge_root, out, "user")
    assert manifest["okf_version"] == "0.1"
    assert manifest["scope"] == "user"
    assert manifest["concept_count"] == 7
    assert "missing-thing" in manifest["unresolved_wikilinks"]


def test_write_bundle_root_index_declares_okf_version(okf_export, bridge_root, tmp_path):
    out = tmp_path / "bundle-root-index"
    okf_export.write_bundle(bridge_root, out, "user")
    fm, _ = okf_export.parse_frontmatter((out / "index.md").read_text(encoding="utf-8"))
    assert fm.get("okf_version") == "0.1"


def test_write_bundle_creates_per_type_index_files(okf_export, bridge_root, tmp_path):
    out = tmp_path / "bundle-type-index"
    okf_export.write_bundle(bridge_root, out, "user")
    for concept_type in ("task", "stream", "deliverable", "doc", "rule", "example"):
        assert (out / concept_type / "index.md").exists(), concept_type


def test_write_bundle_doc_concept_roundtrips_resolved_and_unresolved_wikilinks(okf_export, bridge_root, tmp_path):
    out = tmp_path / "bundle-doc-roundtrip"
    okf_export.write_bundle(bridge_root, out, "user")
    content = (out / "doc" / "sample-doc.md").read_text(encoding="utf-8")
    fm, body = okf_export.parse_frontmatter(content)
    assert fm.get("type") == "doc"
    assert fm.get("title") == "Sample Doc"
    assert fm.get("description") == "Doc about acme"
    assert fm.get("resource") == "docs/sample-doc.md"
    assert "[[sample-rule]]" not in body
    assert "[[missing-thing]]" in body  # unresolved -> left verbatim
    assert "(/rule/sample-rule.md)" in body  # resolved -> bundle-root-relative


def test_write_bundle_core_scope_excludes_task_stream_deliverable_rule_dirs(okf_export, bridge_root, tmp_path):
    out = tmp_path / "bundle-core"
    manifest = okf_export.write_bundle(bridge_root, out, "core")
    assert manifest["concept_count"] == 2
    for concept_type in ("task", "stream", "deliverable", "rule"):
        assert not (out / concept_type).exists()
    assert (out / "doc").exists()
    assert (out / "example").exists()


def test_write_bundle_user_scope_exports_memory_facts(okf_export, bridge_root, memory_dir, tmp_path):
    out = tmp_path / "bundle-memory"
    manifest = okf_export.write_bundle(bridge_root, out, "user", memory_dir=memory_dir)
    assert manifest["concept_count"] == 9  # 7 repo concepts + 2 memory facts
    content = (out / "memory" / "acme-preference.md").read_text(encoding="utf-8")
    fm, body = okf_export.parse_frontmatter(content)
    assert fm.get("type") == "memory"
    assert fm.get("description") == "Acme prefers weekly summaries over daily pings"
    assert fm.get("resource") == "memory/feedback_acme_preference.md"
    # Memory body wikilinks resolve against the full bundle slug index:
    assert "(/rule/sample-rule.md)" in body
    # Index/provenance/frontmatter-less files are never exported as concepts:
    for skipped in ("MEMORY.md", "MEMORY-ARCHIVE.md", "PROVENANCE.md", "scratch-note.md"):
        assert not (out / "memory" / skipped).exists()
    assert (out / "memory" / "index.md").exists()  # generated type index only


def test_write_bundle_core_scope_never_exports_memory(okf_export, bridge_root, memory_dir, tmp_path):
    out = tmp_path / "bundle-core-no-memory"
    manifest = okf_export.write_bundle(bridge_root, out, "core", memory_dir=memory_dir)
    assert manifest["concept_count"] == 2
    assert not (out / "memory").exists()


def test_default_memory_dir_derives_encoded_path_under_home(okf_export, tmp_path):
    derived = okf_export.default_memory_dir(tmp_path / "acme-instance")
    encoded = str((tmp_path / "acme-instance").resolve()).replace("/", "-")
    assert derived == Path.home() / ".claude" / "projects" / encoded / "memory"
    assert encoded.startswith("-")  # leading slash of the abs path becomes a leading dash


def test_write_bundle_is_idempotent_on_rerun(okf_export, bridge_root, tmp_path):
    out = tmp_path / "bundle-idempotent"
    manifest_1 = okf_export.write_bundle(bridge_root, out, "user")
    files_1 = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
    manifest_2 = okf_export.write_bundle(bridge_root, out, "user")
    files_2 = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
    assert manifest_1 == manifest_2
    assert files_1 == files_2


# --------------------------------------------------------------------------
# main (CLI)
# --------------------------------------------------------------------------

def test_main_cli_success_writes_bundle_and_returns_zero(okf_export, bridge_root, tmp_path):
    out = tmp_path / "cli-bundle"
    rc = okf_export.main(["--root", str(bridge_root), "--out", str(out), "--scope", "user"])
    assert rc == 0
    assert (out / "index.md").exists()


def test_main_cli_missing_root_returns_nonzero(okf_export, tmp_path):
    missing_root = tmp_path / "does-not-exist"
    rc = okf_export.main(["--root", str(missing_root), "--out", str(tmp_path / "cli-out"), "--scope", "user"])
    assert rc != 0


def test_main_cli_rejects_unknown_scope_via_argparse(okf_export, bridge_root, tmp_path):
    with pytest.raises(SystemExit):
        okf_export.main(["--root", str(bridge_root), "--out", str(tmp_path / "cli-bogus"), "--scope", "bogus"])
