#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Pytest suite for scripts/okf-export.py (the Tier 1 OKF v0.2 exporter).

CONTRACT — this file is the authoritative spec for the exporter's public
surface (read against scripts/extract-frontmatter.py and
scripts/gen-board.py for the existing hand-rolled-parsing conventions this
repo already uses). scripts/okf-export.py implements this exact surface:

    OKF_VERSION: str                                            = "0.2"
    EXPORTER_VERSION: str                                       = "1.0"
        The exporter's OWN version, deliberately a separate constant from
        the spec version so the two can never drift into each other.

    default_generated_by() -> str
        f"okf-export/{EXPORTER_VERSION}". Names the transformation that
        produced the bundle document, NEVER the author of the underlying
        knowledge. Must not read git, $USER, or any environment.

    normalize_timestamp(value: str) -> str | None
        Two accepted shapes, everything else -> None:
        a full `YYYY-MM-DD` calendar date -> widened to `<date>T00:00:00Z`;
        an ISO datetime that already carries an explicit offset -> verbatim.
        None for a partial date, the literal `YYYY-MM-DD` placeholder, a
        calendar-impossible date, a naive datetime, free text and "". The
        strict regex gate runs BEFORE date.fromisoformat, which on Python
        3.11+ would otherwise accept `20260702` and `2026-W27-1`. Pure:
        reads only its argument, never the clock.

    parse_frontmatter(text: str) -> tuple[dict, str]
        Hand-rolled (NO PyYAML dependency). Reads the same flat
        `key: value` scalars as gen-board.py's parse_status() and skips
        leading `# ...` comment lines (the
        `# yaml-language-server: $schema=...` prolog convention) before the
        first `---` fence, but diverges from that script on two points:

        RESOLUTION ORDER. Quoting is resolved BEFORE inline comments, the
        order YAML itself uses. A `#` inside a double- or single-quoted
        scalar is a literal character (`"... as PR #214"` keeps its issue
        number); a backslash-escaped quote does not close a double-quoted
        scalar, and the two-character escapes in _DQ_ESCAPES are read back
        (every one _yaml_quote emits, plus YAML's `\\/`; a control character,
        which _yaml_quote writes as `\\xNN`, is NOT read back and returns as
        four literal characters); a doubled `''` inside a single-quoted
        scalar collapses to one `'`. On an UNQUOTED scalar a ` #` (start of
        value, or after whitespace) still opens a comment and is still
        stripped, so `value#nospace` stays whole and `key: # note` resolves
        to "". A QUOTED value is never a block-scalar indicator:
        `title: "|"` is the one-character string.

        WHERE A QUOTE CLOSES. A quote closes a quoted scalar only where a
        quote may close one: with nothing behind it, or an inline comment
        (`"a"# tight` resolves to `a`, since the value has already ended at
        the quote). Anything else means that quote was a character inside the
        value, and the scalar then degrades to the plain path rather than
        being cut there: `'Alex's bridge'` and `"He said "stop" once"` keep
        every character between their outer quotes, and only that outer pair
        goes. PyYAML rejects both of those lines outright, so there is no
        conformant answer to defer to; the choice is between keeping a
        malformed value whole and silently dropping its tail, and for a
        deliberately tolerant parser the second is the worse failure.

        The orphaned-pair strip is CONDITIONAL on the value opening with a
        quote, because a YAML plain scalar cannot: `monitor is 12"`,
        `The so-called "bridge"` and `it is 'fine'` are well-formed YAML that
        PyYAML round-trips, and an unconditional strip of both ends ate the
        last character of each (issue #151's symptom through a spelling the
        first fix did not close).

        WHITESPACE IS SPACE AND TAB. Trimming, the `key:` separator and the
        ` #` that opens an inline comment all use `[ \\t]`, never `\\s`, which
        also matches U+00A0. A non-breaking space in a pasted value is content
        to YAML, and `\\s` variously trimmed it, ate it before the value was
        resolved, or read it as the whitespace in front of a comment and
        truncated there.

        FENCE COLUMN. The OPENING `---` counts only at column 0 (trailing
        whitespace, and a trailing CR on a CRLF source, are tolerated), so a
        file whose first non-blank line is an INDENTED `---` has no
        frontmatter. The CLOSING `---` is judged by BLOCK-SCALAR STATE rather
        than by column: inside an open block scalar an indented `---` is
        content (that is exactly what a continuation line looks like), and
        outside one an indented `---` still closes. A column-0-only closer is
        lossy in its own right, and in #151's own shape: a file that merely
        indents its closing fence has the body below it read as frontmatter
        up to the next column-0 `---`, or no frontmatter recognised at all.

        LINE SPLITTING is on `\\r\\n`, `\\r` and `\\n` only. `str.splitlines`
        breaks on five more characters plus U+2028/U+2029, which cut a scalar
        in half at a character PyYAML accepts inside a double-quoted value and
        returns verbatim.

        A leading UTF-8 BOM is dropped before detection. `str.rstrip` does not
        remove U+FEFF, so a BOM-prefixed file was read as having no
        frontmatter at all: every key gone, the title fallen back to the body
        H1, the raw frontmatter emitted into the concept body.

        Returns (frontmatter_dict, body_text). A file with NO frontmatter
        block returns ({}, text): the body is the untouched original text
        (minus a BOM, where it carried one).

        MEASURED, not asserted: over 21,144 well-formed frontmatter lines
        (each probe value spelled plain, double quoted and single quoted, and
        every line accepted by PyYAML), parse_frontmatter agrees with PyYAML
        on all of them. origin/main disagreed on 9,169 of the same lines.

    _split_lines(text: str) -> list[str]
        The line splitter above. `"".join` over the result reconstructs the
        input exactly, which is what lets the body be sliced out untouched.

    _block_scalar_indicator(raw_value: str) -> str | None
        The ONE definition of "this line opens a block scalar", read by both
        the fence scan and the key parser, so a scan and a parse cannot drift
        apart over the same file. A QUOTED value is never an indicator:
        `title: "|"` is the one-character string.

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
        Those patterns are NOT a literal inside this function. They live in
        the module-level _SCOPE_PATTERNS and are read through patterns_for(),
        which is also what scanned_dirs() (and therefore write_bundle's
        destination guard) reads. ONE pattern source, two consumers: a second
        hand-kept list would drift the day a pattern is added to only one of
        them, and the walk would resume eating its own output.

    patterns_for(scope: str) -> tuple[str, ...]
        _SCOPE_PATTERNS[scope]; any other scope raises ValueError, with the
        expected-values half of the message derived from _SCOPE_PATTERNS so
        it cannot drift either.

    _pattern_prefix(pattern: str) -> str
        The fixed leading path of a glob pattern, up to its first globbed
        segment: `docs/**/*.md` -> "docs", `work/tasks/*/STATUS.md` ->
        "work/tasks", `work/**/deliverables/*.md` -> "work". Segment-wise,
        never a string prefix, so `docs-bundle` is not inside `docs`. A
        pattern whose first segment is already globbed yields "".

    _pattern_parent(pattern: str) -> str
        The glob for the DIRECTORIES a pattern reads its files out of:
        `docs/**/*.md` -> `docs/**`, `work/**/deliverables/*.md` ->
        `work/**/deliverables`, `*.md` -> "".

    scanned_dirs(root: Path, scope: str) -> list[Path]
        The sorted, deduplicated, RESOLVED directories discover_sources
        reads under, derived from patterns_for(scope) in TWO layers.

        The fixed prefix (_pattern_prefix) covers a directory that does not
        exist yet: it is scanned the moment it appears. An empty prefix maps
        to root itself rather than being dropped, so a future whole-tree
        pattern cannot silently under-guard. The JOINED path is what
        resolves, not just root: resolving the root alone and appending the
        prefix compares a symlinked `docs/` on its LINK path while --out is
        compared on its real one, and the two then never match.

        The prefix alone is NOT the read set. Path.glob follows a symlink at
        every LITERAL segment after the globbed part, so
        `work/**/deliverables/*.md` reads through a link named `deliverables`
        wherever it really points, while that pattern's fixed prefix is only
        `work`. So the walk's own glob is run over _pattern_parent(pattern)
        and each match resolved, which puts those targets in front of the
        guard: the read set is defined by the glob engine, so the guard asks
        the glob engine. A dangling link counts too (resolve is non-strict),
        so the FIRST run is refused rather than the second.

        Set-built and sorted, every element resolved, so filesystem
        enumeration order cannot reach the exporter's output.

    all_scanned_dirs(root: Path) -> list[tuple[Path, tuple[str, ...]]]
        The union over every scope of scanned_dirs(root, scope), each
        directory paired with the sorted scope names that walk it. This, not
        scanned_dirs alone, is what write_bundle's destination guard reads:
        the bundle outlives the run that wrote it, so a destination only the
        OTHER scope walks is still re-ingested. Sorted by path, so a given
        tree always produces the same refusal.

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
         "resource": str, "generated_at": str | None,
         "bridge_status": str | None, "tags": list[str], "body": str}
        `generated_at` <- normalize_timestamp(frontmatter["last_updated"] or
        frontmatter["created"] or ""). `bridge_status` <-
        frontmatter["status"] or None — a Bridge WORKFLOW state, never OKF's
        own `status`. `tags` <- [frontmatter["status"]] +
        [frontmatter["context"]] (only the ones present), else [].
        `body` is the RAW markdown body (wikilinks not yet resolved).

    dedupe_slugs(concepts: list[dict]) -> None
        Mutates concept["slug"] in place so no two concepts of one type name
        the same FILE, and no concept names a reserved one ("index", "log"),
        which write_bundle generates itself for every populated type
        directory. A colliding concept takes the LOWEST FREE numeric suffix
        on its own natural slug (`slug-2`, `slug-3`, ...), free meaning
        claimed by no other concept of that type and not reserved. Two
        properties follow, and both are asserted: a concept KEEPS its
        natural slug wherever it can, so the duplicate is what moves and a
        bumped name can never land on a slug another concept owns, whether
        that owner is discovered before or after it; and the suffix is
        appended to the concept's own slug rather than to a parsed-off stem,
        so a duplicate of a natural `overview-2` becomes `overview-2-2` and
        never steals `overview-3`.

        THE NAMESPACE IS THE FILESYSTEM'S, not the byte string's. Both the
        claim and the reserved test are keyed on _fs_identity(slug) =
        unicodedata.normalize("NFC", slug).casefold(), because a slug becomes
        a filename and `readme`/`README`, or the NFC and NFD spellings of
        `café`, are ONE file on a case-insensitive or normalizing filesystem
        (the macOS default). Byte-keyed, both concepts keep their natural
        slug, the second write lands on the first file, and one body is gone
        with the manifest still counting it; a source named `Index.md` is
        destroyed by the generated `<type>/index.md` written after it. Only
        the KEY folds: the emitted filename stays the concept's own slug
        (`readme.md` + `README-2.md`), and a bumped memory slug still
        satisfies _SAFE_SLUG_RE. On a case-SENSITIVE filesystem this bumps a
        pair that would not have collided there, which is the deliberate
        trade: one tree exports to one bundle on every platform.

        Deterministic: both passes walk the list in discovery order (it
        arrives pre-sorted by source path) and try suffixes from 2 upward,
        so the assignment depends on the input list alone. _fs_identity is
        pure, so folding adds no new input to that.

        NOT folded: the slug -> relpath index write_bundle builds for
        wikilink resolution. The wikilink grammar is ASCII lowercase kebab,
        so a folded link index could only differ from an exact one where the
        target slug could never have been named by a link anyway, and it
        would have to choose arbitrarily between two now-distinct files.

    write_bundle(root, out_dir, scope, memory_dir=None, generated_by=None) -> dict
        Orchestrates discover_sources -> build_concept (all) ->
        dedupe_slugs -> a slug->relpath index -> resolve_wikilinks over every
        body -> writes
        out_dir/<type>/<slug>.md for every populated type, writes
        out_dir/<type>/index.md per populated type directory, and writes
        out_dir/index.md (root) whose frontmatter carries
        `okf_version: "0.2"` AND NOTHING ELSE (the one key OKF permits in an
        index file). `generated_by` is run-wide, defaulting to
        default_generated_by(). Deterministic + idempotent: re-running with
        unchanged input produces BYTE-IDENTICAL files, in a FRESH INTERPRETER
        as much as in the same one. Set and dict iteration over strings is
        fixed within a process and varies between processes (PYTHONHASHSEED),
        so an in-process re-run cannot see a hash-ordered field at all: every
        ordering that reaches the output has to come from a sorted list or
        from the discovery-ordered concept list, never from a set.
        Two concepts of one type naming the same file (compared in the same
        folded namespace dedupe_slugs assigns in) raise
        BundleDestinationError (exit 1 via main), checked after dedupe_slugs
        and BEFORE the output directory is cleared, so the invariant fails
        loudly with the previous bundle intact rather than silently dropping
        a concept. Returns a manifest:
        {"okf_version": "0.2", "scope": scope, "concept_count": int,
        "generated_by": str, "concepts_without_generated_at": int,
        "unresolved_wikilinks": list[str]} — the undated figure is a COUNT,
        never a list of source paths, because the manifest is printed.

        INDEX ENTRIES. Every index file lists exactly as many entries as it
        has things to list (a type index one per concept of that type, the
        root index one per populated type directory), each on ONE line, and
        every entry's link points at that entry's own file inside the bundle.
        A type index is the only generated file that interpolates source text
        into markdown, and THREE of its values are source-derived: the title,
        the description and the SLUG, which is a source filename.
          * the two text fields go through _md_inline: control characters
            (every line break included, plus U+2028/U+2029) become spaces,
            and `[`, `]`, `\\` and `<` are backslash-escaped. Without that a
            newline splits its bullet and the overflow reads as an entry the
            header does not count; an unescaped `]` hands the `(...)` behind
            it to the source as a link destination; and raw inline HTML,
            which CommonMark passes straight through, opens list items of its
            own carrying an href the source chose.
          * the slug goes through _md_destination, which percent-encodes what
            a link destination cannot carry raw (space, parentheses, `<`,
            `>`, `#`, `?`, `%` and the RFC 3986 exclusions). A filename with
            a space produced something CommonMark does not read as a link at
            all; one with a `)` pointed the link at a file the bundle does
            not contain; one with U+2028 split its own bullet.
        Measured with a real CommonMark parser, not by inspection: every
        index renders as exactly N list items with N hrefs, each resolving
        (after URL-decoding) to one of that type's own concept files.
        The concept FILES need none of this: every source-derived value there
        is written through _yaml_quote.

        DESTINATION GUARDS, every one raising BundleDestinationError (exit 1
        via main). The five below run BEFORE discover_sources walks anything
        and BEFORE the output directory is cleared, so a refused run costs an
        error message and leaves both the sources and any previous bundle
        untouched:
          * out_dir exists and is not a directory. Checked first, because
            Path.iterdir raises NotADirectoryError on a regular file and the
            operator got a traceback where the contract promises a message.
          * out_dir is --root or an ancestor of it (clearing would delete
            the source tree).
          * out_dir lies inside ANY directory ANY scope walks, or contains
            one. `--out` must be outside every all_scanned_dirs(root) entry,
            NOT merely outside this run's own read set: `dist/okf-bundle`
            qualifies, `docs/`, `examples/`, `work/`, `rules/` and anything
            under them do not, in either scope. Without this the walk
            re-ingests the previous run's own output as source material, the
            concept count climbs on every run, and the byte-identical
            guarantee above is false (issue #153).
            Containment is segment-wise, so the sibling `docs-bundle` is
            legal. Comparison is on RESOLVED paths, so a symlinked or
            dot-segmented `--out` is judged on where it really lands and a
            symlinked `docs/` on where it really reads. The segments are
            compared in the same folded namespace dedupe_slugs uses
            (_fs_path_identity applies _fs_identity per segment), so `DOCS/`
            and `docs/`, one directory on the macOS default filesystem, are
            one directory to the guard too. Folded rather than compared by
            inode because the guard must judge directories that do not exist
            yet, which is exactly a fresh instance.
            The refusal is deliberately WIDER than the glob in two ways,
            both fail-closed against silent corruption: it covers scopes
            this run is not in, and _pattern_prefix collapses
            `work/**/deliverables/*.md` to `work`, so all of `work/` is
            refused even where nothing there could be globbed back in. On a
            case-SENSITIVE filesystem the fold makes it wider still, refusing
            a `Docs/` that really is a separate directory; the message names
            the comparison for that reason, so the containment it states is
            not a claim the operator can see is false.
            The message names `dist/okf-bundle`, a destination that works.
          * out_dir overlaps memory_dir in either direction, IN EVERY SCOPE.
            Not gated on the run's read set: core scope never walks the store
            but a bundle written there outlives the run, and the next run of
            either scope rmtrees it, fact files included, because it now
            carries an okf_version index. Same argument all_scanned_dirs
            makes for scopes. main() therefore resolves the memory dir under
            every scope and reads it under one.
          * two concepts of one type name the same file (dedupe_slugs'
            backstop), or a slug is longer than the filesystem's 255-byte
            filename limit. Neither is about WHERE --out points, so neither
            names a working destination; both are checked with the previous
            bundle still on disk.
        One guard runs LATE, after the walk and immediately before the
        rmtree it gates: out_dir exists, is non-empty, and does not look like
        a prior bundle (no index.md carrying okf_version). It is the one that
        decides whether the destination may be cleared, so it cannot run
        earlier.
        The root index.md is written FIRST, before any concept file, because
        _is_bundle_dir keys off it: a run that dies mid-write (a full disk, a
        permission error) then leaves a destination the next run can still
        clear, instead of one the exporter refuses for good.

    default_memory_dir(root: Path) -> Path
        Delegates to `scripts/memory-location.py`'s `resolve_memory_dir()`,
        which reads settings files and shells out to git; falls back to the
        legacy `~/.claude/projects/<encoded-root>/memory` derivation directly
        only if loading that sibling script itself fails.

    discover_memory(memory_dir: Path) -> list[Path]
        The `*.md` fact files under memory_dir, sorted by filename, skipping
        the housekeeping files in _MEMORY_SKIP (MEMORY.md, MEMORY-ARCHIVE.md,
        PROVENANCE.md), `_`-prefixed files, and any file without a non-empty
        `name:` frontmatter key. A missing directory yields [].

    build_memory_concept(path: Path) -> dict
        The same concept dict shape as build_concept, with okf_type "memory",
        resource `memory/<filename>` and generated_at None (a fact carries no
        top-level date, so the key is omitted rather than guessed). The slug
        is the fact's `name:` where that satisfies _SAFE_SLUG_RE, else the
        filename stem with its `<type>_` prefix stripped and underscores
        dashed. "memory" is set here and never passes through
        concept_type_for, which is why _render_root_index's closed set is
        that function's returns PLUS this one.

    Emitted concept frontmatter, in order, empty fields OMITTED:
        type, title, description?, resource, generated { by, at? },
        bridge_status?, tags?

    NEVER EMITTED, and each an explicit decision rather than an oversight:
        timestamp    superseded by generated.at in v0.2; not dual-emitted,
                     because the spec's legacy fallback applies only when
                     `generated` is absent, which it never is.
        status       OKF `status` is document readiness; a Bridge status is
                     work state, and `draft` is a homograph across the two.
        verified     nothing in a Bridge instance is a verification event,
                     and trust tiers are derived purely from this field.
        sources      `related:` is see-also, not derived-from; a fabricated
                     entry manufactures a lineage edge consumers walk.
        stale_after  a consumer GATE; no Bridge field says when a document
                     stops being true. If ever adopted it is an absolute ISO
                     instant with an offset, never a bare date, never a TTL.

    main(argv: list[str] | None = None) -> int
        argparse CLI: --root (default "."), --out (required), --scope
        {"user","core"} (default "user"; invalid choice -> argparse
        SystemExit), --memory-dir, --generated-by ACTOR. A --generated-by
        value that is not an OKF actor (`<producer>/<version>`, `human:<id>`
        or `process:<id>`) -> stderr + exit 1, no bundle written. A `human:`
        actor with --scope core -> stderr WARNING, still exits 0.
        Non-existent/non-dir --root -> prints to stderr, returns a non-zero
        exit code (no traceback). On success prints a one-line summary and
        returns 0.

Hermetic: every test builds its own synthetic mini-instance under tmp_path
(generic names only — "acme", "sample-task" — never real repo/customer
content) and never touches the real repo tree beyond importing the module
under test.
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import os
import re
import subprocess
import sys
import tokenize
import types
import unicodedata
import urllib.parse
from pathlib import Path

import pytest
import yaml  # TEST-only dependency — never imported by the exporter itself

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "scripts" / "okf-export.py"


def _pyyaml_frontmatter(path: Path) -> dict:
    """Parse a bundle file's frontmatter block with a REAL YAML parser.

    Deliberately NOT parse_frontmatter: validating a lenient producer with
    its own lenient reader is the same procedure run twice, and lets a
    malformed block round-trip "successfully". A real parser is what an
    actual OKF consumer will use, so it is what conformance must be
    measured against.
    """
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path} carries no frontmatter fence"
    _, block, _ = text.split("---\n", 2)
    return yaml.safe_load(block) or {}


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
# parse_frontmatter: quoting is resolved BEFORE comments
# --------------------------------------------------------------------------

def test_hash_inside_a_double_quoted_value_is_literal(okf_export):
    """In YAML a `#` inside a quoted scalar is a character, not a comment.

    Stripping the inline comment before resolving the quotes truncated the
    value at the first `#`, so an issue or PR reference was silently cut off
    and the orphaned opening quote was then removed too, leaving no trace.
    """
    text = '---\nheadline: "fixes in review as PR #214"\n---\n\nBody.\n'
    fm, _ = okf_export.parse_frontmatter(text)
    assert fm["headline"] == "fixes in review as PR #214"


def test_hash_inside_a_single_quoted_value_is_literal(okf_export):
    """Single quotes protect a `#` exactly as double quotes do."""
    text = "---\nheadline: 'issue #99 open'\n---\n\nBody.\n"
    fm, _ = okf_export.parse_frontmatter(text)
    assert fm["headline"] == "issue #99 open"


def test_unquoted_inline_comment_is_still_stripped(okf_export):
    """GUARD: on an UNQUOTED scalar a ` #` really does open a comment.

    This is the behaviour the quote fix must not trade away. A `#` with no
    whitespace in front of it is part of the value, so `value#nospace` stays
    whole.
    """
    text = (
        "---\n"
        "plain: plain value  # a real comment\n"
        "nospace: value#nospace\n"
        "---\n\nBody.\n"
    )
    fm, _ = okf_export.parse_frontmatter(text)
    assert fm["plain"] == "plain value"
    assert fm["nospace"] == "value#nospace"


def test_quoted_block_indicator_is_not_treated_as_a_block_scalar(okf_export):
    """GUARD: `title: "|"` is the one-character string, not a block indicator.

    Resolving the quotes ahead of the block-scalar check hands a bare `|` to
    that check, which would swallow every following frontmatter line as the
    block body. The resolver therefore has to report whether the value WAS
    quoted, and a quoted value is never a block indicator.
    """
    text = '---\ntitle: "|"\nstatus: doing\n---\n\nBody.\n'
    fm, body = okf_export.parse_frontmatter(text)
    assert fm == {"title": "|", "status": "doing"}
    assert body.strip() == "Body."


def test_block_indicator_with_a_trailing_comment_still_folds(okf_export):
    """GUARD: a block indicator may legally carry a trailing comment.

    `title: | # note` must still fold its indented continuation lines, which
    proves the plain-scalar comment strip still runs ahead of the
    block-indicator match.
    """
    text = (
        "---\n"
        "title: | # note\n"
        "  Line one\n"
        "  Line two\n"
        "status: doing\n"
        "---\n\nBody.\n"
    )
    fm, _ = okf_export.parse_frontmatter(text)
    assert fm["title"] == "Line one\nLine two"
    assert fm["status"] == "doing"


def test_double_quoted_escaped_quote_is_unescaped(okf_export):
    """A `\\"` inside a double-quoted scalar does not close it."""
    text = '---\ntitle: "He said \\"stop\\" once"\n---\n\nBody.\n'
    fm, _ = okf_export.parse_frontmatter(text)
    assert fm["title"] == 'He said "stop" once'


def test_single_quoted_doubled_quote_collapses(okf_export):
    """`''` is the only escape a YAML single-quoted scalar has."""
    text = "---\ntitle: 'it''s fine'\n---\n\nBody.\n"
    fm, _ = okf_export.parse_frontmatter(text)
    assert fm["title"] == "it's fine"


def test_comment_only_value_resolves_to_empty(okf_export):
    """`title: # just a note` has no value, it has a comment.

    Storing the comment text as the value titled the concept with it. An
    empty value lets derive_title fall through to the body H1, which is the
    honest answer. Locked explicitly because it is a deliberate behaviour
    change rather than a side effect.
    """
    text = "---\ntitle: # just a note\n---\n\n# Real Heading\n\nBody.\n"
    fm, body = okf_export.parse_frontmatter(text)
    assert fm["title"] == ""
    assert okf_export.derive_title(fm, body, fallback="slug") == "Real Heading"


# --------------------------------------------------------------------------
# parse_frontmatter: a quote closes a scalar only where a quote may close one
# --------------------------------------------------------------------------

def test_apostrophe_inside_a_single_quoted_value_keeps_the_whole_value(okf_export):
    """REGRESSION: `title: 'Alex's bridge'` must not truncate to `Alex`.

    A scanner that accepts the first quote it meets, whatever follows it,
    reads the apostrophe as the closing quote and discards the rest as the
    comment position. PyYAML rejects this line outright, so there is no
    "matches YAML" answer to hide behind: the choice is between keeping the
    value whole and dropping its tail, and silently dropping the tail is the
    exact failure class this parser exists to avoid. An apostrophe inside a
    single-quoted value is an everyday shape.
    """
    fm, _ = okf_export.parse_frontmatter("---\ntitle: 'Alex's bridge'\n---\n\nBody.\n")
    assert fm["title"] == "Alex's bridge"


def test_unescaped_inner_double_quote_keeps_the_whole_value(okf_export):
    """REGRESSION: `title: "He said "stop" once"` must not truncate to `He said `.

    Same defect through the double-quoted path. The escaped form
    (`\\"stop\\"`) is handled by the escape branch and is tested separately;
    this is the unescaped shape a human types.
    """
    fm, _ = okf_export.parse_frontmatter('---\ntitle: "He said "stop" once"\n---\n\nBody.\n')
    assert fm["title"] == 'He said "stop" once'


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        # A quote closes the scalar when nothing but a comment follows it.
        ('"well formed"', "well formed"),
        ("'well formed'", "well formed"),
        ('"well formed"  # trailing comment', "well formed"),
        ("'well formed'  # trailing comment", "well formed"),
        # No whitespace before the `#` either: the value already ended at the
        # quote, so there is nothing for the hash to be part of. PyYAML reads
        # this one the same way.
        ('"well formed"# tight comment', "well formed"),
        # A `#` INSIDE the quotes is still a literal (the fix must not trade
        # that away to get the tail rule).
        ('"a # b"  # c', "a # b"),
        # Anything else after the quote means it did not close the scalar, so
        # the value degrades to the historic plain strip and stays whole.
        ('"He said "stop" once"', 'He said "stop" once'),
        ("'Alex's bridge'", "Alex's bridge"),
        ('"value" trailing junk', 'value" trailing junk'),
        # A quote that is never closed: unchanged, the historic plain strip.
        ('"unterminated', "unterminated"),
        ("'unterminated", "unterminated"),
        # Empty and quotes-only values.
        ('""', ""),
        ("''", ""),
        ('"""', ""),
        ("'''", ""),
    ],
)
def test_quoted_scalar_tail_rule(okf_export, value, expected):
    """One table for the whole rule: a closing quote is only a closing quote
    when what follows it is empty or a comment.

    Every "did not close" row is the value origin/main produced. Preserving
    those is the point: this parser is deliberately more tolerant than YAML,
    and a tolerance that silently shortens a value is worse than no tolerance
    at all.
    """
    fm, _ = okf_export.parse_frontmatter(f"---\ntitle: {value}\n---\n\nBody.\n")
    assert fm["title"] == expected


def test_a_fallen_through_quote_does_not_disturb_the_following_keys(okf_export):
    """The degrade is confined to its own line: the block still parses."""
    text = (
        "---\n"
        "title: 'Alex's bridge'\n"
        "status: doing\n"
        "---\n\nBody.\n"
    )
    fm, body = okf_export.parse_frontmatter(text)
    assert fm == {"title": "Alex's bridge", "status": "doing"}
    assert body.strip() == "Body."


# --------------------------------------------------------------------------
# parse_frontmatter: a fence lives at column 0
# --------------------------------------------------------------------------

def test_indented_fence_inside_a_block_scalar_does_not_close_the_frontmatter(okf_export):
    """An indented `---` is block-scalar content, never the closing fence.

    Comparing `line.strip()` against `---` threw away the one piece of
    information that distinguishes the two: a frontmatter fence is at column
    0 by definition, a block-scalar continuation line is indented by
    definition. The block closed early, the remaining keys were lost and four
    frontmatter lines leaked into the body.
    """
    text = (
        "---\n"
        "title: |\n"
        "  Heading\n"
        "  ---\n"
        "  Trailer\n"
        "status: doing\n"
        "context: acme\n"
        "---\n"
        "\n# Body\n\nText.\n"
    )
    fm, body = okf_export.parse_frontmatter(text)
    assert fm == {"title": "Heading\n---\nTrailer", "status": "doing", "context": "acme"}
    assert body == "\n# Body\n\nText.\n"


def test_column_zero_fence_still_closes_the_block(okf_export):
    """GUARD: the ordinary closing fence keeps working.

    Tightening the closer must not tighten it into never matching, and a
    later `---` horizontal rule in the body stays part of the body.
    """
    text = "---\nstatus: doing\n---\n\nIntro.\n\n---\n\nAfter the rule.\n"
    fm, body = okf_export.parse_frontmatter(text)
    assert fm == {"status": "doing"}
    assert body == "\nIntro.\n\n---\n\nAfter the rule.\n"


def test_indented_opening_fence_is_not_frontmatter(okf_export):
    """An indented leading `---` is content (an indented code block).

    The opener is held to the same column-0 rule as the closer: a parser
    whose opener is looser than its closer accepts a pair of fences that are
    not the same kind of thing. The right answer for such a file is ({},
    text) with the body untouched.
    """
    text = "  ---\n  title: not frontmatter\n  ---\n\nBody.\n"
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


def test_discover_sources_core_scope_leaves_the_docs_tier_folders_out(okf_export, bridge_root):
    # docs/user/, docs/org/ and docs/personal/ hold an instance's own docs
    # (docs/kernel.md); the core scope is the export's privacy boundary.
    for rel in ("docs/user/mine.md", "docs/org/shared.md", "docs/personal/notes.md"):
        target = bridge_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("---\ntitle: x\n---\n# x\n", encoding="utf-8")
    core = {p.relative_to(bridge_root).as_posix() for p in okf_export.discover_sources(bridge_root, "core")}
    assert core == {"docs/sample-doc.md", "examples/acme-demo/README.md"}
    user = {p.relative_to(bridge_root).as_posix() for p in okf_export.discover_sources(bridge_root, "user")}
    assert "docs/user/mine.md" in user


def test_discover_sources_core_scope_leaves_an_unmigrated_private_doc_out(okf_export, bridge_root):
    # A fork that has not moved its docs yet: the router still keeps them local,
    # and so must the core export.
    (bridge_root / "docs" / "mine.md").write_text("---\nscope: user\n---\n# Mine\n", encoding="utf-8")
    (bridge_root / "docs" / "odd.md").write_text("---\nscope: usr\n---\n# Odd\n", encoding="utf-8")
    core = {p.relative_to(bridge_root).as_posix() for p in okf_export.discover_sources(bridge_root, "core")}
    assert "docs/mine.md" not in core and "docs/odd.md" not in core
    assert "docs/sample-doc.md" in core


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
    assert c["generated_at"] == "2026-01-05T00:00:00Z"
    assert c["bridge_status"] == "doing"
    assert "doing" in c["tags"] and "acme" in c["tags"]


def test_build_concept_doc_uses_summary_field_and_h1_title(okf_export, bridge_root):
    c = okf_export.build_concept(bridge_root / "docs/sample-doc.md", bridge_root)
    assert c["okf_type"] == "doc"
    assert c["title"] == "Sample Doc"
    assert c["description"] == "Doc about acme"
    assert c["generated_at"] == "2026-01-03T00:00:00Z"
    assert c["bridge_status"] is None
    assert c["tags"] == []


def test_build_concept_rule_without_frontmatter_falls_back_to_h1_and_empty_fields(okf_export, bridge_root):
    c = okf_export.build_concept(bridge_root / "rules/sample-rule.md", bridge_root)
    assert c["okf_type"] == "rule"
    assert c["title"] == "Sample Rule"
    assert c["description"] == ""
    assert c["generated_at"] is None
    assert c["tags"] == []


# --------------------------------------------------------------------------
# write_bundle
# --------------------------------------------------------------------------

def test_write_bundle_user_scope_manifest_counts_and_version(okf_export, bridge_root, tmp_path):
    out = tmp_path / "bundle-user"
    manifest = okf_export.write_bundle(bridge_root, out, "user")
    assert manifest["okf_version"] == "0.2"
    assert manifest["scope"] == "user"
    assert manifest["concept_count"] == 7
    assert "missing-thing" in manifest["unresolved_wikilinks"]


def test_write_bundle_root_index_declares_okf_version(okf_export, bridge_root, tmp_path):
    out = tmp_path / "bundle-root-index"
    okf_export.write_bundle(bridge_root, out, "user")
    fm, _ = okf_export.parse_frontmatter((out / "index.md").read_text(encoding="utf-8"))
    assert fm.get("okf_version") == "0.2"


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


@pytest.mark.parametrize(
    "hostile_name,expected_slug",
    [
        ("../../escaped", "escape-probe"),      # climbs out of the bundle entirely
        ("sub/dir/nested", "escape-probe"),     # silently creates a subdirectory
        ("/absolute", "escape-probe"),          # anchors at the filesystem root
        (".hidden", "escape-probe"),            # leading dot is not a slug
        ("fine-name", "fine-name"),             # the ordinary case still wins
    ],
)
def test_memory_name_cannot_escape_the_output_directory(
    okf_export, bridge_root, tmp_path, hostile_name, expected_slug
):
    """A memory fact's `name:` is arbitrary frontmatter, not a safe path.

    It was previously used verbatim as the output filename, so a name
    containing `..` or `/` made the exporter write outside `--out` — up to and
    including over a file in the source tree it is supposed to only read.
    """
    mem = tmp_path / "hostile-memory"
    # Real memory files are named `<type>_<slug>.md`, and the fallback strips
    # that type prefix — so this filename yields the slug "escape-probe".
    _write(
        mem / "reference_escape_probe.md",
        f"---\nname: {hostile_name}\ndescription: Probe\n---\n\nBody.\n",
    )
    out = tmp_path / "nested" / "bundle-escape"
    okf_export.write_bundle(bridge_root, out, "user", memory_dir=mem)

    assert (out / "memory" / f"{expected_slug}.md").is_file()
    written = [p for p in out.rglob("*.md")]
    for path in written:
        assert out in path.resolve().parents, f"{path} escaped {out}"
    # nothing landed beside or above the bundle
    assert not list((tmp_path / "nested").glob("*.md"))
    assert not list(tmp_path.glob("*.md"))


def test_unsafe_memory_name_falls_back_to_the_filename_slug(okf_export, tmp_path):
    """A `name:` carrying a literal `#` is not a usable single path segment.

    The truncating comment strip used to sanitize it by accident: `"fact #2"`
    arrived as `fact`, which _SAFE_SLUG_RE happily accepted. With the value
    resolved correctly the name no longer matches, so the filename-derived
    fallback takes over. This is the one slug-affecting consequence of the
    quoting fix and it is pinned here on purpose.
    """
    mem = tmp_path / "memory-hash-name"
    _write(
        mem / "feedback_hash_name.md",
        '---\nname: "fact #2"\ndescription: "note #7"\n---\n\nBody.\n',
    )
    concept = okf_export.build_memory_concept(mem / "feedback_hash_name.md")
    assert concept["slug"] == "hash-name"
    assert concept["description"] == "note #7"


def test_default_memory_dir_derives_encoded_path_under_home(okf_export, tmp_path):
    fake_home = tmp_path / "fake-home"
    derived = okf_export.default_memory_dir(tmp_path / "acme-instance", home=fake_home)
    encoded = str((tmp_path / "acme-instance").resolve()).replace("/", "-")
    assert derived == fake_home / ".claude" / "projects" / encoded / "memory"
    assert encoded.startswith("-")  # leading slash of the abs path becomes a leading dash


def test_default_memory_dir_prefers_a_configured_setting(okf_export, tmp_path):
    # Resolved up front (not just under tmp_path) so the path this test writes
    # settings.local.json to is byte-identical to the one resolve_memory_dir()
    # looks under. Some platforms put pytest's tmp_path behind a symlink
    # (macOS /var -> /private/var), and resolving only inside the function
    # under test would silently look somewhere this test never wrote to.
    root = (tmp_path / "acme-instance").resolve()
    fake_home = tmp_path / "fake-home"
    configured = root / "work" / "memory"
    _write(
        root / ".claude" / "settings.local.json",
        '{\n  "autoMemoryDirectory": "%s"\n}\n' % configured,
    )
    derived = okf_export.default_memory_dir(root, home=fake_home)
    assert derived == configured


def test_default_memory_dir_falls_back_to_legacy_on_a_relative_setting(okf_export, tmp_path):
    root = (tmp_path / "acme-instance").resolve()  # see comment above
    fake_home = tmp_path / "fake-home"
    _write(
        root / ".claude" / "settings.local.json",
        '{\n  "autoMemoryDirectory": "work/memory"\n}\n',
    )
    derived = okf_export.default_memory_dir(root, home=fake_home)
    encoded = str(root).replace("/", "-")
    assert derived == fake_home / ".claude" / "projects" / encoded / "memory"


def _bundle_digest(out: Path) -> dict:
    """{bundle-relative path: sha256 of the file's bytes} for a whole bundle."""
    return {
        p.relative_to(out).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in out.rglob("*")
        if p.is_file()
    }


def test_write_bundle_is_byte_identical_on_rerun(okf_export, bridge_root, tmp_path):
    """Determinism is a load-bearing contract, so compare CONTENT, not names.

    The former path-only comparison passed even if every byte of every file
    had changed between runs — it only proved the same filenames were
    written, which is not what the contract promises.
    """
    out = tmp_path / "bundle-idempotent"
    manifest_1 = okf_export.write_bundle(bridge_root, out, "user")
    digest_1 = _bundle_digest(out)
    manifest_2 = okf_export.write_bundle(bridge_root, out, "user")
    digest_2 = _bundle_digest(out)
    assert manifest_1 == manifest_2
    assert digest_1 == digest_2


# PYTHONHASHSEED values pinned as literals, so this test's verdict is fixed
# rather than sampled: the same seeds run on every machine and every CI job.
# Several of them because one 2-element set is a coin flip per seed, while the
# multi-element orderings separate on the first seed.
_HASH_SEEDS = ("1", "2", "3", "4", "5", "6", "7", "8")


def _export_in_a_fresh_process(root: Path, out: Path, scope: str, hash_seed: str) -> dict:
    """Run the exporter as its own process under a pinned PYTHONHASHSEED.

    subprocess is a TEST-side tool here. The exporter itself may never call
    it (test_module_source_has_no_wall_clock_call forbids exactly that), but
    a second interpreter is the only place a hash-ordered field becomes
    visible, so the check has to be made from outside.
    """
    completed = subprocess.run(
        [sys.executable, str(MODULE_PATH), "--root", str(root), "--out", str(out),
         "--scope", scope],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONHASHSEED": hash_seed},
    )
    assert completed.returncode == 0, completed.stderr
    return _bundle_digest(out)


def test_bundle_is_byte_identical_across_processes_with_different_hash_seeds(bridge_root, tmp_path):
    """The determinism contract, measured where it can actually fail.

    The in-process re-run above cannot see this class of defect at all. Set
    and dict iteration over a fixed group of strings is stable for the whole
    life of one interpreter, so a rendered field ordered by a set produces
    the same bytes twice in a row and the digest comparison passes. Change
    the hash seed and the same input yields a different bundle: two exports
    of one unchanged instance stop matching, and any consumer diffing them
    reads content churn that never happened.

    Sweeping several pinned seeds is what makes the verdict deterministic.
    Ordering a two-element field by a set flips on roughly half of all seeds,
    so a single seed would decide by luck; eight decide by rule.
    """
    digests = [
        _export_in_a_fresh_process(bridge_root, tmp_path / f"bundle-seed-{seed}", "user", seed)
        for seed in _HASH_SEEDS
    ]
    assert digests[0], "the export produced no files to compare"
    for seed, digest in zip(_HASH_SEEDS[1:], digests[1:]):
        differing = sorted(
            name for name in set(digest) | set(digests[0])
            if digest.get(name) != digests[0].get(name)
        )
        assert not differing, (
            f"PYTHONHASHSEED={seed} produced a different bundle: {differing}"
        )


def test_render_keeps_tags_in_source_order(okf_export):
    """`tags` is a LIST in source order, so the render may not reorder it.

    Passing it through a set is the shortest way to lose that: the emitted
    order then follows string hashing, which is the one input the exporter is
    not allowed to have. Eight tags rather than the two a real concept
    carries, so the assertion holds by rule instead of by coin flip: a set
    reproduces an eight-element insertion order once in 40320 attempts.
    """
    tags = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel"]
    concept = {
        "okf_type": "doc",
        "title": "Ordered Tags",
        "description": "",
        "resource": "docs/ordered.md",
        "tags": list(tags),
        "body": "Body.\n",
    }
    _, block, _ = okf_export._render_concept(concept).split("---\n", 2)
    assert yaml.safe_load(block)["tags"] == tags


def test_module_source_has_no_wall_clock_call():
    """No render path may read the clock, a file mtime, or git.

    Any of these makes a re-export differ from the previous one even when
    the source tree is unchanged, breaking the byte-identical guarantee
    above. Asserted against the module source so the regression is caught at
    the exact line someone would write it.
    """
    # Comments and string literals are stripped first: a substring scan over
    # raw text would fire on the module's own comment explaining why git is
    # refused, which is documentation, not a call.
    tokens = tokenize.generate_tokens(io.StringIO(MODULE_PATH.read_text(encoding="utf-8")).readline)
    code = "".join(
        tok.string for tok in tokens if tok.type in (tokenize.NAME, tokenize.OP, tokenize.NUMBER)
    )
    for forbidden in (
        "datetime.now", "utcnow", "date.today", "time.time", "st_mtime", "getmtime",
        # Not just the clock: git state and the environment are equally
        # non-reproducible, and a git-derived generated.by/at is exactly the
        # convenience a future contributor would reach for.
        "subprocess", "os.environ", "getenv", "popen", "check_output",
    ):
        assert forbidden not in code, f"non-reproducible call {forbidden!r} in the exporter"


def test_exporter_imports_without_pyyaml(bridge_root, tmp_path, monkeypatch):
    """The exporter is dependency-free; PyYAML is a TEST-only dependency.

    CI pre-installs PyYAML for this suite, so a stray ``import yaml`` in the
    exporter would pass CI and only fail for a user running the script on a
    bare interpreter. Blocking the module makes the constraint enforceable.
    """

    class _BlockYAML:
        def find_spec(self, fullname, path=None, target=None):
            del path, target  # part of the finder protocol, unused here
            if fullname == "yaml" or fullname.startswith("yaml."):
                raise ImportError("PyYAML is deliberately unavailable to the exporter")
            return None

    monkeypatch.delitem(sys.modules, "yaml", raising=False)
    monkeypatch.setattr(sys, "meta_path", [_BlockYAML(), *sys.meta_path])

    spec = importlib.util.spec_from_file_location("okf_export_no_yaml", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    manifest = module.write_bundle(bridge_root, tmp_path / "bundle-no-yaml", "user")
    assert manifest["concept_count"] == 7


# --------------------------------------------------------------------------
# OKF v0.2 — normalize_timestamp
# --------------------------------------------------------------------------

def test_normalize_timestamp_widens_bare_date_to_midnight_utc(okf_export):
    assert okf_export.normalize_timestamp("2026-07-02") == "2026-07-02T00:00:00Z"


@pytest.mark.parametrize(
    "value",
    ["2026-08-04T15:50:53Z", "2026-08-04T15:50:53+02:00", "2026-08-04T15:50:53-05:00"],
)
def test_normalize_timestamp_passes_through_offset_bearing_datetime(okf_export, value):
    """An instant that already carries an explicit offset is never rewritten."""
    assert okf_export.normalize_timestamp(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "YYYY-MM-DD",              # the literal placeholder work/templates/STATUS.md seeds
        "2026-03",                 # partial: would require inventing one day out of 31
        "2026-02-30",              # calendar-impossible
        "2026-08-04T15:50:53",     # naive: no offset, so not a knowable instant
        "sometime in March",
        "",
    ],
)
def test_normalize_timestamp_returns_none_for_unprovable_values(okf_export, value):
    """Refuse rather than guess — the field is simply omitted downstream."""
    assert okf_export.normalize_timestamp(value) is None


@pytest.mark.parametrize(
    "value",
    [
        "2026-02-30T00:00:00Z",       # calendar-impossible, offset-bearing
        "2026-06-31T09:00:00Z",       # June has 30 days
        "2026-13-45T99:99:99Z",       # every component out of range
        "2026-07-02T25:00:00Z",       # hour 25
        "2026-07-02T14:00:00+99:99",  # impossible offset
        "2026-07-02 14:00:00Z",       # space separator is not the ISO form
    ],
)
def test_normalize_timestamp_rejects_impossible_offset_instants(okf_export, value):
    """The offset branch must PROVE the value, not merely shape-match it.

    The regex is all `\\d{2}` groups, so month 13 and day-31-in-June match the
    pattern. Passing such a value through emits an unquoted scalar that no
    YAML parser can load, which breaks conformance for the entire bundle
    while the exporter still exits 0 and reports every date as proven.
    """
    assert okf_export.normalize_timestamp(value) is None


def test_impossible_source_instant_never_reaches_the_bundle(okf_export, tmp_path):
    """End-to-end companion to the unit test above."""
    root = tmp_path / "impossible-instant"
    _write(root / "docs/bad.md", "---\nlast_updated: 2026-06-31T09:00:00Z\n---\n\n# Bad\n\nBody.\n")
    out = tmp_path / "bundle-impossible"
    manifest = okf_export.write_bundle(root, out, "core")
    fm = _pyyaml_frontmatter(out / "doc" / "bad.md")   # must not raise
    assert "at" not in fm["generated"]
    assert manifest["concepts_without_generated_at"] == 1


@pytest.mark.parametrize("value", ["20260702", "2026-W27-1"])
def test_normalize_timestamp_rejects_compact_and_week_forms(okf_export, value):
    """The strict regex gate must run BEFORE date.fromisoformat.

    Python 3.11+ accepts both of these, so without the gate they would be
    silently widened into an instant the source never stated.
    """
    assert okf_export.normalize_timestamp(value) is None


# --------------------------------------------------------------------------
# OKF v0.2 — generated / trust / lifecycle fields
# --------------------------------------------------------------------------

CORE_SCOPE_KEY_ALLOWLIST = {
    "type", "title", "description", "resource", "generated", "bridge_status", "tags",
}


def _concept_files(out: Path) -> list[Path]:
    return [p for p in out.rglob("*.md") if p.name != "index.md"]


def _trust_tier(fm: dict) -> str:
    """OKF section 5.3's tier rule, implemented independently of the exporter."""
    verified = fm.get("verified")
    if not verified:
        return "unverified"
    entries = verified if isinstance(verified, list) else [verified]
    actors = [str(e.get("by", "")) for e in entries]
    return "human-reviewed" if any(a.startswith("human:") for a in actors) else "machine-confirmed"


def test_concept_emits_generated_flow_mapping_with_by(okf_export, bridge_root, memory_dir, tmp_path):
    """`by` is the only REQUIRED key inside `generated` (spec 5.2)."""
    out = tmp_path / "bundle-generated"
    okf_export.write_bundle(bridge_root, out, "user", memory_dir=memory_dir)
    for path in _concept_files(out):
        generated = _pyyaml_frontmatter(path).get("generated")
        assert isinstance(generated, dict), path
        assert generated.get("by") == f"okf-export/{okf_export.EXPORTER_VERSION}", path


def test_generated_at_present_for_dated_source_and_absent_for_undated(okf_export, bridge_root, tmp_path):
    out = tmp_path / "bundle-generated-at"
    okf_export.write_bundle(bridge_root, out, "user")
    # Asserted on the emitted TEXT: an unquoted ISO instant is what the spec's
    # own examples show, and PyYAML (YAML 1.1) resolves it to a native
    # datetime, so a value comparison would test the parser, not the output.
    assert "at: 2026-01-05T00:00:00Z" in (out / "task" / "sample-task.md").read_text(encoding="utf-8")
    assert "at" in _pyyaml_frontmatter(out / "task" / "sample-task.md")["generated"]
    undated = _pyyaml_frontmatter(out / "rule" / "sample-rule.md")["generated"]
    assert "at" not in undated


def test_generated_at_omitted_when_source_date_unparseable(okf_export, tmp_path):
    root = tmp_path / "partial-date-instance"
    _write(root / "docs/partial.md", "---\ncreated: 2026-03\n---\n\n# Partial\n\nBody.\n")
    out = tmp_path / "bundle-partial"
    okf_export.write_bundle(root, out, "core")
    fm = _pyyaml_frontmatter(out / "doc" / "partial.md")
    assert "at" not in fm["generated"]
    assert "2026-03" not in (out / "doc" / "partial.md").read_text(encoding="utf-8").split("---")[1]


def test_no_timestamp_key_emitted_for_any_concept(okf_export, bridge_root, memory_dir, tmp_path):
    """v0.2 clean break: `timestamp` is superseded by `generated.at`."""
    out = tmp_path / "bundle-no-timestamp"
    okf_export.write_bundle(bridge_root, out, "user", memory_dir=memory_dir)
    for path in _concept_files(out):
        assert "timestamp" not in _pyyaml_frontmatter(path), path


def test_no_concept_emits_okf_status_key(okf_export, bridge_root, memory_dir, tmp_path):
    """The homograph guard.

    OKF `status` is document readiness (draft|stable|deprecated); a Bridge
    `status` is WORK state (backlog|doing|review|done). Mapping one onto the
    other, even behind an enum whitelist, would turn a Bridge task in draft
    state into the OKF claim that the DOCUMENT is unreviewed and possibly
    incomplete. Absent `status` already means `stable`, which is the true
    claim about an exported write-up.
    """
    out = tmp_path / "bundle-no-status"
    okf_export.write_bundle(bridge_root, out, "user", memory_dir=memory_dir)
    for path in _concept_files(out):
        assert "status" not in _pyyaml_frontmatter(path), path


def test_bridge_status_is_namespaced_and_preserves_its_value(okf_export, hostile_root, tmp_path):
    out = tmp_path / "bundle-bridge-status"
    okf_export.write_bundle(hostile_root, out, "user")
    assert _pyyaml_frontmatter(out / "task" / "comma-tag.md")["bridge_status"] == "final, not sent"


def test_bridge_status_value_still_appears_in_tags(okf_export, bridge_root, tmp_path):
    """REGRESSION — the v0.1 tags derivation is untouched by the migration."""
    out = tmp_path / "bundle-tags-regression"
    okf_export.write_bundle(bridge_root, out, "user")
    tags = _pyyaml_frontmatter(out / "task" / "sample-task.md")["tags"]
    assert "doing" in tags and "acme" in tags


@pytest.mark.parametrize("field", ["verified", "sources", "stale_after", "usage_window"])
def test_no_concept_emits_a_fabricated_provenance_or_trust_field(okf_export, bridge_root, memory_dir, tmp_path, field):
    """Nothing in a Bridge instance honestly supplies any of these.

    `verified` is the costliest to fake: spec 5.3 derives trust tiers purely
    from it, so a synthetic entry silently promotes every concept in the
    bundle out of `unverified`. `stale_after` is a consumer GATE (10.5), so
    a fabricated horizon suppresses content that is perfectly current.
    """
    out = tmp_path / f"bundle-no-{field}"
    okf_export.write_bundle(bridge_root, out, "user", memory_dir=memory_dir)
    for path in _concept_files(out):
        assert field not in _pyyaml_frontmatter(path), path


def test_every_concept_derives_trust_tier_unverified(okf_export, bridge_root, memory_dir, tmp_path):
    """Asserts the consumer-visible consequence, not just key absence."""
    out = tmp_path / "bundle-trust-tier"
    okf_export.write_bundle(bridge_root, out, "user", memory_dir=memory_dir)
    for path in _concept_files(out):
        assert _trust_tier(_pyyaml_frontmatter(path)) == "unverified", path


def test_related_frontmatter_is_never_promoted_to_sources(okf_export, tmp_path):
    """`related:` is see-also, not derived-from (spec 5.1)."""
    root = tmp_path / "related-instance"
    _write(
        root / "docs/with-related.md",
        "---\nsummary: \"Doc with a related list\"\nrelated:\n  - other-doc.md\n  - ../scripts/x.py\n---\n\n# With Related\n\nBody.\n",
    )
    out = tmp_path / "bundle-related"
    okf_export.write_bundle(root, out, "core")
    fm = _pyyaml_frontmatter(out / "doc" / "with-related.md")
    assert "sources" not in fm
    assert "other-doc.md" not in str(fm)


def test_concept_with_no_frontmatter_invents_nothing(okf_export, bridge_root, tmp_path):
    """The anti-fabrication guard, stated as an exact key set."""
    out = tmp_path / "bundle-invents-nothing"
    okf_export.write_bundle(bridge_root, out, "user")
    fm = _pyyaml_frontmatter(out / "rule" / "sample-rule.md")
    assert set(fm) == {"type", "title", "resource", "generated"}
    assert fm["generated"] == {"by": f"okf-export/{okf_export.EXPORTER_VERSION}"}


def test_empty_description_and_tags_keys_are_omitted(okf_export, bridge_root, tmp_path):
    """Spec 5: absence carries meaning, so never write `description: ""`."""
    out = tmp_path / "bundle-omit-empty"
    okf_export.write_bundle(bridge_root, out, "user")
    fm = _pyyaml_frontmatter(out / "rule" / "sample-rule.md")
    assert "description" not in fm
    assert "tags" not in fm


# --------------------------------------------------------------------------
# OKF v0.2 — the --generated-by actor
# --------------------------------------------------------------------------

def test_generated_by_defaults_to_exporter_actor(okf_export):
    assert okf_export.EXPORTER_VERSION != okf_export.OKF_VERSION
    assert okf_export.default_generated_by() == f"okf-export/{okf_export.EXPORTER_VERSION}"


@pytest.mark.parametrize("actor", ["human:sample", "process:nightly-export", "some-tool/2.1"])
def test_generated_by_cli_override_used_verbatim(okf_export, bridge_root, tmp_path, actor):
    out = tmp_path / f"bundle-actor-{actor.replace(':', '-').replace('/', '-')}"
    rc = okf_export.main(
        ["--root", str(bridge_root), "--out", str(out), "--scope", "user", "--generated-by", actor]
    )
    assert rc == 0
    assert _pyyaml_frontmatter(out / "doc" / "sample-doc.md")["generated"]["by"] == actor


@pytest.mark.parametrize(
    "actor",
    [
        "Some Person", "human:", "no-slash-no-prefix", "a/b/c",
        # Python's `$` also matches BEFORE a trailing newline, so a `$`-anchored
        # gate would pass these and then split the rendered flow mapping across
        # two physical lines. The regex uses \Z for exactly this reason.
        "human:alice\n", "okf-export/1.0\n", "process:ci\n",
        'okf-export/1.0"', "okf-export/1.0 }",
    ],
)
def test_generated_by_rejects_non_actor_string_with_nonzero_exit(okf_export, bridge_root, tmp_path, actor):
    """A typo'd actor would silently mis-tier a whole bundle (spec 5.3/7)."""
    out = tmp_path / "bundle-bad-actor"
    rc = okf_export.main(
        ["--root", str(bridge_root), "--out", str(out), "--scope", "user", "--generated-by", actor]
    )
    assert rc == 1
    assert not out.exists()


def test_generated_by_never_reads_git_or_environment(okf_export, bridge_root, tmp_path, monkeypatch):
    """Locks the privacy + determinism boundary against a future 'convenience' default."""
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=bridge_root, check=True)
    subprocess.run(["git", "config", "user.name", "Real Person"], cwd=bridge_root, check=True)
    subprocess.run(["git", "config", "user.email", "real@example.com"], cwd=bridge_root, check=True)
    monkeypatch.setenv("USER", "realperson")

    out = tmp_path / "bundle-no-git-actor"
    okf_export.write_bundle(bridge_root, out, "user")
    rendered = (out / "doc" / "sample-doc.md").read_text(encoding="utf-8")
    assert f"okf-export/{okf_export.EXPORTER_VERSION}" in rendered
    assert "Real Person" not in rendered and "realperson" not in rendered


def test_core_scope_warns_when_generated_by_is_a_human_actor(okf_export, bridge_root, tmp_path, capsys):
    out = tmp_path / "bundle-core-human-actor"
    rc = okf_export.main(
        ["--root", str(bridge_root), "--out", str(out), "--scope", "core",
         "--generated-by", "human:sample"]
    )
    assert rc == 0
    assert "WARNING" in capsys.readouterr().err


def test_core_scope_frontmatter_keys_are_within_allowlist(okf_export, bridge_root, memory_dir, tmp_path):
    """Privacy regression for the newly added keys."""
    out = tmp_path / "bundle-core-allowlist"
    okf_export.write_bundle(bridge_root, out, "core", memory_dir=memory_dir)
    for path in _concept_files(out):
        fm = _pyyaml_frontmatter(path)
        assert set(fm) <= CORE_SCOPE_KEY_ALLOWLIST, (path, set(fm) - CORE_SCOPE_KEY_ALLOWLIST)
        blob = str(fm)
        assert "memory/" not in blob and "work/" not in blob and "human:" not in blob


# --------------------------------------------------------------------------
# OKF v0.2 — bundle level
# --------------------------------------------------------------------------

def test_root_index_frontmatter_carries_only_okf_version(okf_export, bridge_root, tmp_path):
    """Spec 8/12: `okf_version` is the ONE key permitted in an index.md."""
    out = tmp_path / "bundle-root-index-trim"
    okf_export.write_bundle(bridge_root, out, "user")
    index = out / "index.md"
    assert _pyyaml_frontmatter(index) == {"okf_version": "0.2"}
    body = index.read_text(encoding="utf-8")
    assert "scope: user" not in body.split("---")[1]
    assert "user" in body and "7" in body  # both still stated in the body prose


def test_is_bundle_dir_still_recognizes_a_v01_bundle(okf_export, tmp_path):
    """Trimming the root index must not make a v0.1 bundle unrecognisable.

    This asserts the predicate only. The guard it feeds is covered by the two
    BundleDestinationError tests below, which exercise the actual rmtree path.
    """
    old = tmp_path / "v01-bundle"
    old.mkdir()
    (old / "index.md").write_text('---\nokf_version: "0.1"\nscope: user\n---\n\n# OKF Bundle\n', encoding="utf-8")
    assert okf_export._is_bundle_dir(old) is True
    plain = tmp_path / "not-a-bundle"
    plain.mkdir()
    (plain / "index.md").write_text("# Just a readme, no frontmatter\n", encoding="utf-8")
    assert okf_export._is_bundle_dir(plain) is False


def test_write_bundle_refuses_to_clear_a_non_bundle_directory(okf_export, bridge_root, tmp_path):
    """The rmtree guard, exercised rather than assumed.

    `write_bundle` calls shutil.rmtree on --out. A non-empty directory that is
    not a prior bundle must raise BEFORE anything is deleted, or a mistyped
    --out silently destroys unrelated data.
    """
    precious = tmp_path / "precious"
    precious.mkdir()
    keeper = precious / "important.txt"
    keeper.write_text("do not delete me", encoding="utf-8")

    with pytest.raises(okf_export.BundleDestinationError):
        okf_export.write_bundle(bridge_root, precious, "user")
    assert keeper.exists(), "guard raised but the directory was cleared anyway"
    assert keeper.read_text(encoding="utf-8") == "do not delete me"


def test_write_bundle_refuses_an_out_dir_that_would_delete_the_source(okf_export, bridge_root, tmp_path):
    """--out == --root, or an ancestor of it, would clear the source tree."""
    del tmp_path
    for destination in (bridge_root, bridge_root.parent):
        with pytest.raises(okf_export.BundleDestinationError):
            okf_export.write_bundle(bridge_root, destination, "user")
    assert (bridge_root / "docs" / "sample-doc.md").exists()


# --------------------------------------------------------------------------
# --out inside a scanned directory (issue #153)
#
# The converse of the guard above. That one asks "does --out CONTAIN the
# source?"; these ask "does --out SIT INSIDE something the walk reads?".
# Unguarded, every run re-ingests the previous run's own output as source
# material, so the concept count grows without bound and the documented
# byte-identical re-run property is false.
# --------------------------------------------------------------------------

def _core_docs_tree(root: Path) -> None:
    """The filed reproduction's two-file docs/ tree."""
    _write(root / "docs/alpha.md", '---\ntitle: "Alpha"\ndescription: "First doc"\n---\n\n# Alpha\n\nBody.\n')
    _write(root / "docs/beta.md", '---\ntitle: "Beta"\ndescription: "Second doc"\n---\n\n# Beta\n\nBody.\n')


def test_write_bundle_refuses_an_out_dir_inside_a_scanned_directory(okf_export, tmp_path):
    """The filed defect, refused on the FIRST run rather than the second.

    `--out ./docs/okfbundle` with `--scope core` satisfies neither term of
    the --root guard, so today the export runs and leaves its own output
    where the next walk will read it back in.
    """
    root = tmp_path / "instance"
    _core_docs_tree(root)
    out = root / "docs" / "okfbundle"

    with pytest.raises(okf_export.BundleDestinationError) as excinfo:
        okf_export.write_bundle(root, out, "core")

    message = str(excinfo.value)
    assert str((root / "docs").resolve()) in message, (
        "the message must name the scanned directory the operator has to move --out out of"
    )
    assert not out.exists(), "guard raised but the destination was created anyway"


def test_a_second_run_can_never_reingest_the_first_runs_output(okf_export, tmp_path):
    """Issue #153 verbatim: concept_count went 2 -> 6 -> 10 across three runs.

    The illegal destination is refused outright; a legal one keeps the count
    flat, which is the byte-identical re-run property this defect broke.
    """
    root = tmp_path / "instance"
    _core_docs_tree(root)

    with pytest.raises(okf_export.BundleDestinationError):
        okf_export.write_bundle(root, root / "docs" / "okfbundle", "core")

    legal = root / "dist" / "okf-bundle"
    counts = [okf_export.write_bundle(root, legal, "core")["concept_count"] for _ in range(3)]
    assert counts == [2, 2, 2], f"count grew across runs: {counts}"


@pytest.mark.parametrize(
    ("scope", "scanned"),
    [("core", "docs"), ("core", "examples"), ("user", "work"), ("user", "rules")],
)
def test_write_bundle_refuses_an_out_dir_equal_to_a_scanned_directory(
    okf_export, bridge_root, scope, scanned
):
    """--out == a scanned directory is refused, and the sources survive.

    Some of these are refused today too, but only by luck: the LATE
    non-bundle guard happens to fire because the directory is non-empty and
    carries no okf_version index. That is an accident of content, not a
    rule, so it is pinned here as a rule.
    """
    with pytest.raises(okf_export.BundleDestinationError):
        okf_export.write_bundle(bridge_root, bridge_root / scanned, scope)
    assert (bridge_root / "docs" / "sample-doc.md").exists()
    assert (bridge_root / "work" / "tasks" / "sample-task" / "STATUS.md").exists()


def test_scanned_out_guard_fires_before_the_walk(okf_export, bridge_root, monkeypatch):
    """The refusal must precede discover_sources, not follow it.

    A guard placed after the walk would already hold the previous run's
    output in memory, which is exactly how the filed bundle acquired a
    `type: doc` concept whose body was the earlier run's rendered index.
    """
    def _explode(root, scope):  # pragma: no cover - must never run
        raise AssertionError("discover_sources ran before the destination was validated")

    monkeypatch.setattr(okf_export, "discover_sources", _explode)
    with pytest.raises(okf_export.BundleDestinationError):
        okf_export.write_bundle(bridge_root, bridge_root / "docs" / "okfbundle", "core")


def test_scanned_out_guard_fires_before_anything_is_cleared(okf_export, tmp_path):
    """A prior bundle at an illegal --out must be refused, not cleared.

    This is the ordering trap in the filed report: the destination LOOKS
    like a valid prior bundle, so the late guard clears it happily, and the
    evidence of the re-ingestion is deleted in the very run that consumed
    it. The sentinel proves the rmtree never happened.
    """
    root = tmp_path / "instance"
    _core_docs_tree(root)
    out = root / "docs" / "okfbundle"
    out.mkdir(parents=True)
    (out / "index.md").write_text('---\nokf_version: "0.2"\n---\n\n# OKF Bundle\n', encoding="utf-8")
    sentinel = out / "sentinel.txt"
    sentinel.write_text("untouched", encoding="utf-8")
    assert okf_export._is_bundle_dir(out), "fixture must look like a prior bundle to the late guard"

    with pytest.raises(okf_export.BundleDestinationError):
        okf_export.write_bundle(root, out, "core")
    assert sentinel.read_text(encoding="utf-8") == "untouched"


def test_guard_and_discovery_share_one_pattern_source(okf_export, tmp_path, monkeypatch):
    """One list of scanned patterns, read by both the walk and the guard.

    A second literal directory list in the guard would drift silently the
    day someone adds a pattern to only one of the two. Adding a pattern here
    must therefore change BOTH behaviours at once.
    """
    monkeypatch.setitem(
        okf_export._SCOPE_PATTERNS, "core", okf_export._SCOPE_PATTERNS["core"] + ("guides/**/*.md",)
    )
    root = tmp_path / "instance"
    _core_docs_tree(root)
    _write(root / "guides/intro.md", '---\ntitle: "Intro"\n---\n\n# Intro\n\nBody.\n')

    found = okf_export.discover_sources(root, "core")
    assert root / "guides" / "intro.md" in found, "the walk did not pick up the new pattern"

    with pytest.raises(okf_export.BundleDestinationError):
        okf_export.write_bundle(root, root / "guides" / "okfbundle", "core")


def test_sibling_directory_sharing_a_name_prefix_is_a_legal_out(okf_export, tmp_path):
    """`docs-bundle` is not inside `docs`. Containment is segment-wise.

    A `str.startswith` comparison would refuse this, because the string
    `<root>/docs-bundle` does start with the string `<root>/docs`.
    """
    root = tmp_path / "instance"
    _core_docs_tree(root)
    manifest = okf_export.write_bundle(root, root / "docs-bundle", "core")
    assert manifest["concept_count"] == 2
    assert (root / "docs-bundle" / "index.md").exists()


def test_out_dir_reaching_a_scanned_directory_through_a_symlink_is_refused(okf_export, tmp_path):
    """Containment is judged on where --out LANDS, not on how it is spelled.

    The sibling test above pins the guard against being too broad. This one
    pins the other edge: `<tmp>/docs-link/okfbundle` shares no leading path
    with `<root>/docs`, so a comparison made on the argument as given reads
    it as outside every scanned directory. It resolves straight into `docs/`,
    and the walk then re-ingests the bundle exactly as in issue #153, with
    the concept count climbing on every re-run.
    """
    root = tmp_path / "instance"
    _core_docs_tree(root)
    link = tmp_path / "docs-link"
    try:
        link.symlink_to(root / "docs", target_is_directory=True)
    except (OSError, NotImplementedError):  # pragma: no cover - platform without symlinks
        pytest.skip("this platform does not permit creating symlinks")

    with pytest.raises(okf_export.BundleDestinationError):
        okf_export.write_bundle(root, link / "okfbundle", "core")
    assert not (root / "docs" / "okfbundle").exists(), (
        "guard raised but the bundle landed in docs/ anyway"
    )


def test_out_dir_reaching_a_scanned_directory_through_dot_segments_is_refused(okf_export, tmp_path):
    """The same rule for `<root>/dist/../docs/okfbundle`.

    `Path` carries a `..` segment verbatim, so an unresolved comparison reads
    this destination as sitting under `dist/`, which no scope walks, and
    waves it through. `dist/okf-bundle` is the documented happy path, so a
    relative --out written from beside it is an ordinary typo rather than an
    exotic one.
    """
    root = tmp_path / "instance"
    _core_docs_tree(root)

    with pytest.raises(okf_export.BundleDestinationError):
        okf_export.write_bundle(root, root / "dist" / ".." / "docs" / "okfbundle", "core")
    assert not (root / "docs" / "okfbundle").exists(), (
        "guard raised but the bundle landed in docs/ anyway"
    )


def test_an_unscanned_directory_inside_root_is_still_a_legal_out(okf_export, bridge_root):
    """`dist/okf-bundle` under --root stays legal, in every scope.

    It is the usage the module docstring and the guide both document, so a
    blanket refusal of any --out beneath --root would break the documented
    happy path.
    """
    for scope in ("core", "user"):
        out = bridge_root / "dist" / f"okf-bundle-{scope}"
        manifest = okf_export.write_bundle(bridge_root, out, scope)
        assert manifest["scope"] == scope
        assert (out / "index.md").exists()


def _symlink_or_skip(link: Path, target: Path) -> None:
    """Create a directory symlink, skipping the test where the platform cannot."""
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):  # pragma: no cover - platform without symlinks
        pytest.skip("this platform does not permit creating symlinks")


def test_a_case_only_spelling_of_a_scanned_directory_is_refused(okf_export, tmp_path):
    """`DOCS/` and `docs/` are ONE directory on the macOS default filesystem.

    Measured before this fix, straight from the filed reproduction and with
    the filed signature: `--out d/DOCS/okfbundle --scope core` ran clean and
    the concept count went 2 -> 6 -> 10 across three runs of an unchanged
    two-file tree. The walk read one directory while the guard compared two
    byte-distinct strings, so the bundle landed exactly where the next glob
    would read it back in.

    Refused on a case-SENSITIVE filesystem too, where the two spellings
    really are two directories. That is the same trade dedupe_slugs already
    takes for slugs: ONE notion of filesystem identity, so one tree behaves
    the same way on every platform, and the cost is a refusal the operator
    answers by naming another destination.
    """
    root = tmp_path / "instance"
    _core_docs_tree(root)

    with pytest.raises(okf_export.BundleDestinationError):
        okf_export.write_bundle(root, root / "DOCS" / "okfbundle", "core")
    assert not (root / "docs" / "okfbundle").exists(), (
        "guard raised but the bundle landed in docs/ anyway"
    )


def test_a_case_only_spelling_of_root_is_refused(okf_export, tmp_path):
    """The --root guard folds too, and it is the one that protects the tree.

    `--out INSTANCE` against `--root instance` is the same directory on a
    case-insensitive filesystem, and the refusal there is not about a growing
    concept count: it is the guard between a typo and an rmtree of the whole
    source tree.
    """
    root = tmp_path / "instance"
    _core_docs_tree(root)

    with pytest.raises(okf_export.BundleDestinationError) as excinfo:
        okf_export.write_bundle(root, tmp_path / "INSTANCE", "core")
    assert "--root" in str(excinfo.value), "the --root clause must be what fired"
    assert (root / "docs" / "alpha.md").exists(), "guard raised but the sources were cleared"


def test_scanned_dirs_resolves_a_symlinked_prefix(okf_export, tmp_path):
    """The unit behind the next test, and what the docstring already claims.

    `(root / prefix)` left unresolved compares the scanned directory on its
    LINK path while --out is compared on its real one, so the two can never
    match however the destination is spelled.
    """
    root = tmp_path / "instance"
    real = tmp_path / "realdocs"
    real.mkdir(parents=True)
    _symlink_or_skip(root / "docs", real)

    assert real.resolve() in okf_export.scanned_dirs(root, "core")


def test_a_scanned_directory_that_is_itself_a_symlink_is_refused(okf_export, tmp_path):
    """The walk follows `root/docs -> /elsewhere/realdocs`; the guard must too.

    Measured before this fix, the filed signature again:
    `--out root/docs/okfbundle --scope core` against a repo whose `docs/` is
    a symlink ran 2 -> 6 -> 10. The existing symlink test covers the mirror
    image (a symlinked --out reaching a real scanned directory); this is the
    side where the SOURCE directory is the link.
    """
    root = tmp_path / "instance"
    real = tmp_path / "realdocs"
    real.mkdir(parents=True)
    _symlink_or_skip(root / "docs", real)
    _core_docs_tree(root)  # writes through the link, into realdocs/
    assert (real / "alpha.md").exists(), "fixture must place the sources behind the link"

    with pytest.raises(okf_export.BundleDestinationError):
        okf_export.write_bundle(root, root / "docs" / "okfbundle", "core")
    assert not (real / "okfbundle").exists(), (
        "guard raised but the bundle landed behind the link anyway"
    )


def test_out_dir_containing_a_scanned_directory_is_refused(okf_export, tmp_path):
    """The converse clause, which only resolving the prefixes makes reachable.

    Before the prefixes resolved, this branch had no case at all: for --out
    to contain a scanned directory it had to be --root or an ancestor of it,
    and the FIRST guard refuses both, so the clause was unreachable and
    untested. A `docs/` symlink pointing INTO the destination reaches it
    without going through --root, and clearing --out would then delete the
    source tree rather than a previous bundle.
    """
    root = tmp_path / "instance"
    root.mkdir(parents=True)
    out = tmp_path / "bundle-out"
    real = out / "inner-docs"
    real.mkdir(parents=True)
    _symlink_or_skip(root / "docs", real)
    _core_docs_tree(root)

    with pytest.raises(okf_export.BundleDestinationError) as excinfo:
        okf_export.write_bundle(root, out, "core")
    assert "contains" in str(excinfo.value), (
        "the containment clause must be what fired, not the late non-bundle check"
    )
    assert (real / "alpha.md").exists(), "guard raised but the sources were cleared"


def test_the_destination_guard_covers_every_scope_not_only_the_running_one(okf_export, tmp_path):
    """A bundle outlives the run that wrote it, so the guard cannot be per-run.

    Measured before this fix: `--out h/rules/okfbundle --scope core` was
    accepted and wrote 1 concept, because core walks only `docs/` and
    `examples/`. The next `--scope user` run globbed `rules/**/*.md`, ate
    that bundle, and reported 5 concepts from a two-file tree. Guarding only
    the scope in front of you makes the corruption a function of which scope
    ran last, which is not a property an operator can reason about.
    """
    root = tmp_path / "instance"
    _write(root / "docs/alpha.md", '---\ntitle: "Alpha"\n---\n\n# Alpha\n\nBody.\n')
    _write(root / "rules/sample-rule.md", '---\ntitle: "Sample Rule"\n---\n\n# Rule\n\nBody.\n')

    with pytest.raises(okf_export.BundleDestinationError) as excinfo:
        okf_export.write_bundle(root, root / "rules" / "okfbundle", "core")
    message = str(excinfo.value)
    assert str((root / "rules").resolve()) in message
    assert "user" in message, "the message must name the scope whose walk would eat it"
    assert not (root / "rules" / "okfbundle").exists()

    counts = [
        okf_export.write_bundle(root, tmp_path / "dist", "user")["concept_count"]
        for _ in range(3)
    ]
    assert counts == [2, 2, 2], f"count grew across runs: {counts}"


@pytest.mark.parametrize("scope", ["core", "user"])
@pytest.mark.parametrize("scanned", ["docs", "examples", "work", "rules"])
def test_every_scanned_directory_is_refused_in_every_scope(okf_export, bridge_root, scope, scanned):
    """THE RULE the previous test states once, pinned over the whole matrix.

    `work/` and `rules/` are walked by user scope only, `docs/` and
    `examples/` by both, and none of that matters to the destination: the
    guard reads the union of every scope's scanned directories.
    """
    with pytest.raises(okf_export.BundleDestinationError):
        okf_export.write_bundle(bridge_root, bridge_root / scanned / "okfbundle", scope)
    assert not (bridge_root / scanned / "okfbundle").exists()


def test_the_prefix_widening_refuses_a_destination_it_could_never_reingest(okf_export, bridge_root):
    """A deliberate over-refusal, pinned as a decision rather than left as a bug.

    _pattern_prefix("work/**/deliverables/*.md") collapses to "work", so the
    guard refuses everything under `work/`. `work/exports/okfbundle` is such
    a destination: the pattern needs a literal `deliverables` segment, the
    bundle's type directory is named `deliverable`, so nothing written there
    could ever be globbed back in. It is refused anyway.

    Fail-closed is the right bias for a guard whose failure mode is silent
    data corruption, and the operator's answer is one word of the path. The
    message therefore has to name a destination that works, which
    test_an_unscanned_directory_inside_root_is_still_a_legal_out proves it
    does.
    """
    with pytest.raises(okf_export.BundleDestinationError) as excinfo:
        okf_export.write_bundle(bridge_root, bridge_root / "work" / "exports" / "okfbundle", "user")
    assert "dist/okf-bundle" in str(excinfo.value), (
        "a refusal that names no working destination leaves the operator guessing"
    )


def test_write_bundle_refuses_an_out_dir_inside_the_memory_dir(okf_export, bridge_root, memory_dir):
    """The exporter is strictly a READER of the memory dir. It never writes there.

    The memory dir usually lives outside the repo, and --out inside it makes
    every re-run rmtree part of that out-of-repo store.
    """
    with pytest.raises(okf_export.BundleDestinationError) as excinfo:
        okf_export.write_bundle(bridge_root, memory_dir / "okfbundle", "user", memory_dir=memory_dir)
    assert str(memory_dir.resolve()) in str(excinfo.value)
    assert list(memory_dir.glob("*.md")), "guard raised but the fact files are gone"


def test_write_bundle_refuses_an_out_dir_equal_to_an_empty_memory_dir(okf_export, bridge_root, tmp_path):
    """The case the late non-bundle guard cannot see.

    An EMPTY memory dir passes `any(out_dir.iterdir())`, so today the
    exporter rmtrees the user's memory directory and writes a bundle over
    it. A fresh instance has exactly that directory.
    """
    empty_memory = tmp_path / "empty-memory"
    empty_memory.mkdir()
    with pytest.raises(okf_export.BundleDestinationError):
        okf_export.write_bundle(bridge_root, empty_memory, "user", memory_dir=empty_memory)
    assert empty_memory.is_dir()
    assert not (empty_memory / "index.md").exists(), "the memory dir was overwritten with a bundle"


def test_a_case_only_spelling_of_the_memory_dir_is_refused(okf_export, bridge_root, memory_dir):
    """The memory clause compares in the same folded namespace as the rest.

    One notion of filesystem identity across all three destination guards,
    or the weakest of them decides what gets through. Here the weakest one
    would rmtree the user's fact store.
    """
    shouting = memory_dir.parent / memory_dir.name.upper()
    with pytest.raises(okf_export.BundleDestinationError) as excinfo:
        okf_export.write_bundle(bridge_root, shouting, "user", memory_dir=memory_dir)
    assert "memory dir" in str(excinfo.value), "the memory clause must be what fired"
    assert list(memory_dir.glob("*.md")), "guard raised but the fact files are gone"


# The memory clause used to be gated on `scope == "user"`, pinned here by
# test_core_scope_does_not_refuse_a_memory_dir_it_never_reads. That gate is
# gone: see test_the_memory_dir_is_refused_as_a_destination_in_every_scope
# further down for the replacement and the measurement that forced it.


def test_scanned_dirs_derives_the_core_set_from_the_patterns(okf_export, tmp_path):
    """`docs/**/*.md` -> `docs`; the leading fixed segments, nothing more."""
    root = tmp_path / "instance"
    root.mkdir()
    assert okf_export.scanned_dirs(root, "core") == [
        (root / "docs").resolve(),
        (root / "examples").resolve(),
    ]
    user = okf_export.scanned_dirs(root, "user")
    for name in ("docs", "examples", "rules", "work"):
        assert (root / name).resolve() in user, f"user scope must guard {name}/"


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        ("docs/**/*.md", "docs"),
        ("examples/**/*.md", "examples"),
        ("work/tasks/*/STATUS.md", "work/tasks"),
        ("work/done/*/*/STATUS.md", "work/done"),
        ("work/**/deliverables/*.md", "work"),
        ("rules/**/*.md", "rules"),
        # No fixed leading segment at all: the whole root is scanned. Mapped
        # to "" on purpose, so scanned_dirs can turn it into root rather than
        # silently dropping the pattern and under-guarding.
        ("**/*.md", ""),
        ("*.md", ""),
    ],
)
def test_pattern_prefix_stops_at_the_first_globbed_segment(okf_export, pattern, expected):
    assert okf_export._pattern_prefix(pattern) == expected


def test_patterns_for_rejects_an_unknown_scope(okf_export):
    """The documented ValueError contract survives the shared-source refactor."""
    with pytest.raises(ValueError):
        okf_export.patterns_for("bogus")


def test_main_cli_refuses_a_self_ingesting_out_with_exit_1(okf_export, tmp_path, capsys):
    """The filed command line, end to end: exit 1, ERROR on stderr, no traceback."""
    root = tmp_path / "instance"
    _core_docs_tree(root)
    out = root / "docs" / "okfbundle"

    rc = okf_export.main(["--root", str(root), "--out", str(out), "--scope", "core"])
    assert rc == 1
    captured = capsys.readouterr()
    assert captured.err.startswith("ERROR: ")
    assert not out.exists()


@pytest.mark.parametrize("concept_type", ["task", "stream", "deliverable", "doc", "rule", "example", "memory"])
def test_type_index_has_no_frontmatter(okf_export, bridge_root, memory_dir, tmp_path, concept_type):
    out = tmp_path / "bundle-type-index-nofm"
    okf_export.write_bundle(bridge_root, out, "user", memory_dir=memory_dir)
    text = (out / concept_type / "index.md").read_text(encoding="utf-8")
    assert not text.startswith("---")


def test_type_index_entries_match_spec_bullet_form(okf_export, bridge_root, tmp_path):
    """Spec 8 shows `* [Title](relative-url) - short description`."""
    out = tmp_path / "bundle-type-index-form"
    okf_export.write_bundle(bridge_root, out, "user")
    entries = [
        line for line in (out / "doc" / "index.md").read_text(encoding="utf-8").splitlines()
        if line.startswith("* [")
    ]
    assert entries, "no spec-form bullets found"
    assert "* [Sample Doc](sample-doc.md) - Doc about acme" in entries
    # U+2014 spelled as an escape, not as itself: the assertion is about the
    # generated bundle, and this file is not a place for a stray em dash.
    assert "\u2014" not in (out / "doc" / "index.md").read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# Index integrity: one entry per concept, and the entry's link is its own
# --------------------------------------------------------------------------

# An index entry, spelled out rather than matched loosely. The title and the
# description may hold anything EXCEPT an unescaped `[`, `]` or `\`. An
# unescaped `]` closes the link text early and hands what follows to the
# source as a destination; an unescaped `\` in front of an escaped `]` puts
# that `]` back; `[` is held to the same rule so an entry's link text is
# exactly its title. `(` and `)` are unrestricted on purpose: a destination
# can only follow an unescaped `]`, and under this class the only one on the
# line is the `]` the renderer itself writes.
_INDEX_ENTRY_RE = re.compile(
    r"\A\* \[(?:[^\[\]\\]|\\.)*\]\((?P<target>[^()]*)\)(?: - (?:[^\[\]\\]|\\.)*)?\Z"
)


def _index_entry_lines(index_md: Path) -> list[str]:
    """Every non-blank line of a generated index after its `N concept(s).` line.

    Deliberately NOT "every line starting with `* [`": a field carrying a
    newline splits its own bullet across two lines, and such a filter would
    drop the overflow line and count the broken entry as intact. The point of
    this helper is to see every line the renderer produced.
    """
    lines = index_md.read_text(encoding="utf-8").splitlines()
    for pos, line in enumerate(lines):
        if line.endswith("concept(s)."):
            return [rest for rest in lines[pos + 1:] if rest.strip()]
    raise AssertionError(f"{index_md} carries no `N concept(s).` line")


@pytest.fixture
def index_hostile_root(tmp_path: Path) -> Path:
    """An instance whose frontmatter is hostile to the INDEX renderer.

    Separate from ``hostile_root`` (which is hostile to the frontmatter
    renderer) so a failure names which of the two surfaces broke.
    """
    root = tmp_path / "index-hostile-instance"
    # Route 1, NEW in the branch that resolved quoting: `\n` inside a
    # double-quoted scalar is unescaped into a real newline, so a SINGLE-line
    # source field reaches the renderer multi-line.
    _write(
        root / "docs/innocent.md",
        "---\n"
        'title: "Innocent"\n'
        'description: "real desc\\n* [Fake](https://evil.example/x) - injected bullet"\n'
        "---\n\n"
        "Body.\n",
    )
    # Route 2, PRE-EXISTING: a `title: |` block scalar is multi-line in the
    # source itself and never needed an escape to get there.
    _write(
        root / "docs/block-title.md",
        "---\n"
        "title: |\n"
        "  Multi one\n"
        "  * [BlockFake](https://evil.example/b) - injected via block scalar\n"
        'description: "Block scalar title"\n'
        "---\n\n"
        "Body.\n",
    )
    # Route 3, PRE-EXISTING: no newline needed at all. A `]` closes the link
    # text early and the `(...)` that follows becomes a destination the source
    # chose, so the entry count stays right while the link leaves the bundle.
    _write(
        root / "rules/bracket-title.md",
        "---\n"
        'title: "x](https://evil.example/h) [y"\n'
        'description: "desc [link](https://evil.example/d) here"\n'
        "---\n\n"
        "Body.\n",
    )
    # Not a fourth route but a GUARD on the escape set: a backslash directly
    # in front of the source's `]`. Escape the brackets alone and the emitted
    # `\\` reads as a literal backslash, leaving the `]` behind it bare again,
    # so the hijack of route 3 comes straight back. (origin/main mis-renders
    # this same file too, for its own reason: it never unescaped `\\`, so the
    # value reached the entry with both backslashes.)
    _write(
        root / "examples/backslash-title.md",
        "---\n"
        'title: "x\\\\](https://evil.example/z) [y"\n'
        "---\n\n"
        "Body.\n",
    )
    _write(
        root / "work/tasks/plain-task/STATUS.md",
        "---\nstatus: doing\nheadline: \"An ordinary headline\"\n---\n\n# Plain Task\n\nBody.\n",
    )
    return root


def test_every_generated_index_lists_exactly_one_entry_per_concept(
    okf_export, index_hostile_root, tmp_path
):
    """THE RULE, not a spot check: every index file the bundle contains lists
    exactly as many entries as it has things to list, and every entry is one
    well-formed line.

    A source-derived title or description is interpolated into a markdown
    bullet, so a newline in one fabricates an entry: the header says
    `1 concept(s).` and the list shows two, the second able to carry any link
    it likes. Counting only lines that look like bullets would miss the other
    half of the same defect, an entry broken across two lines.
    """
    out = tmp_path / "bundle-index-integrity"
    manifest = okf_export.write_bundle(index_hostile_root, out, "user")

    type_dirs = sorted(p for p in out.iterdir() if p.is_dir())
    assert type_dirs, "no type directories were written"

    total = 0
    for type_dir in type_dirs:
        concepts = sorted(p.name for p in type_dir.glob("*.md") if p.name != "index.md")
        total += len(concepts)
        entries = _index_entry_lines(type_dir / "index.md")
        assert len(entries) == len(concepts), (
            f"{type_dir.name}/index.md lists {len(entries)} entr(ies) for "
            f"{len(concepts)} concept(s): {entries}"
        )
        for entry in entries:
            match = _INDEX_ENTRY_RE.match(entry)
            assert match, f"{type_dir.name}/index.md entry is not one clean bullet: {entry!r}"
            assert match.group("target") in concepts, (
                f"{type_dir.name}/index.md links {match.group('target')!r}, "
                f"which is not one of its own concepts {concepts}"
            )

    assert total == manifest["concept_count"]

    root_entries = _index_entry_lines(out / "index.md")
    assert len(root_entries) == len(type_dirs), (
        f"root index.md lists {len(root_entries)} entr(ies) for "
        f"{len(type_dirs)} type director(ies): {root_entries}"
    )
    expected_targets = {f"{d.name}/index.md" for d in type_dirs}
    for entry in root_entries:
        match = _INDEX_ENTRY_RE.match(entry)
        assert match, f"root index.md entry is not one clean bullet: {entry!r}"
        assert match.group("target") in expected_targets


def test_a_description_newline_cannot_fabricate_an_index_entry(
    okf_export, index_hostile_root, tmp_path
):
    """The NEW route, reproduced end to end.

    `description: "real desc\\n* [Fake](...)"` is one line of source. The
    fabricated bullet must end up INSIDE the innocent concept's own entry,
    flattened, rather than as a second entry with its own external link.
    """
    out = tmp_path / "bundle-index-desc-newline"
    okf_export.write_bundle(index_hostile_root, out, "user")
    text = (out / "doc" / "index.md").read_text(encoding="utf-8")

    assert "\n* [Fake]" not in text
    assert "\n* \\[Fake\\]" not in text
    innocent = [line for line in text.splitlines() if line.startswith("* [Innocent]")]
    assert len(innocent) == 1
    assert "injected bullet" in innocent[0], (
        "the description text itself must survive, only its line break goes"
    )
    # The concept file keeps the real newline: _yaml_quote escapes it there,
    # and that path was never the broken one.
    assert "\n" in _pyyaml_frontmatter(out / "doc" / "innocent.md")["description"]


def test_a_block_scalar_title_cannot_fabricate_an_index_entry(
    okf_export, index_hostile_root, tmp_path
):
    """The PRE-EXISTING route: a `title: |` block scalar is multi-line in the
    source, so it needed no escape to reach the renderer with a newline in it.
    """
    out = tmp_path / "bundle-index-block-title"
    okf_export.write_bundle(index_hostile_root, out, "user")
    text = (out / "doc" / "index.md").read_text(encoding="utf-8")

    assert "\n* [BlockFake]" not in text
    assert "\n* \\[BlockFake\\]" not in text
    entry = [line for line in text.splitlines() if line.startswith("* [Multi one")]
    assert len(entry) == 1
    assert "injected via block scalar" in entry[0]
    assert entry[0].endswith("(block-title.md) - Block scalar title")


def test_an_index_title_cannot_supply_its_own_link_target(
    okf_export, index_hostile_root, tmp_path
):
    """The PRE-EXISTING bracket route, which fabricates no line at all.

    `title: "x](https://evil.example/h) [y"` keeps the entry count right and
    still moves the entry's first link off the bundle, because the `]` closes
    the link text early and the `(...)` behind it becomes the destination.
    """
    out = tmp_path / "bundle-index-bracket-title"
    okf_export.write_bundle(index_hostile_root, out, "user")
    entries = _index_entry_lines(out / "rule" / "index.md")

    assert len(entries) == 1
    match = _INDEX_ENTRY_RE.match(entries[0])
    # The regex is the assertion: it admits no unescaped `[` or `]` inside the
    # title or the description, so the only link the entry can form is the one
    # the renderer wrote, and its destination is the concept's own file.
    assert match, f"entry is not one clean bullet: {entries[0]!r}"
    assert match.group("target") == "bracket-title.md"
    # Escaped, not dropped: a reader still sees exactly what the source said.
    assert "x\\](https://evil.example/h) \\[y" in entries[0]
    assert "desc \\[link\\](https://evil.example/d) here" in entries[0]


def test_a_backslash_before_the_bracket_does_not_defeat_the_escape(
    okf_export, index_hostile_root, tmp_path
):
    """GUARD on the escape set: `\\` has to be escaped alongside the brackets.

    `title: "x\\\\](...)"` carries a backslash in front of its `]`. Escape only
    the brackets and the emitted text is `x\\\\](...)`, where the `\\\\` is a
    literal backslash and the `]` behind it is bare, so it closes the link
    text and the `(...)` becomes the destination. Escaping `\\` too keeps the
    pair as `\\\\` plus `\\]`, and the entry's link stays the concept's own file.
    """
    out = tmp_path / "bundle-index-backslash-title"
    okf_export.write_bundle(index_hostile_root, out, "user")
    entries = _index_entry_lines(out / "example" / "index.md")

    assert len(entries) == 1
    match = _INDEX_ENTRY_RE.match(entries[0])
    assert match, f"entry is not one clean bullet: {entries[0]!r}"
    assert match.group("target") == "backslash-title.md"
    assert entries[0].startswith("* [x\\\\\\](https://evil.example/z) \\[y]")


def test_an_ordinary_title_and_description_reach_the_index_unchanged(
    okf_export, bridge_root, tmp_path
):
    """GUARD: the flattening must be invisible to content that never needed it."""
    out = tmp_path / "bundle-index-ordinary"
    okf_export.write_bundle(bridge_root, out, "user")
    entries = _index_entry_lines(out / "doc" / "index.md")
    assert entries == ["* [Sample Doc](sample-doc.md) - Doc about acme"]


def test_no_concept_file_is_named_index_or_log(okf_export, tmp_path):
    """REGRESSION on _RESERVED_SLUGS + dedupe_slugs (spec 2 reserved names)."""
    root = tmp_path / "reserved-instance"
    _write(root / "docs/index.md", "---\nsummary: \"Would collide\"\n---\n\n# Index Doc\n\nBody.\n")
    _write(root / "docs/log.md", "---\nsummary: \"Would collide too\"\n---\n\n# Log Doc\n\nBody.\n")
    out = tmp_path / "bundle-reserved"
    okf_export.write_bundle(root, out, "core")
    assert (out / "doc" / "index-2.md").exists()
    assert (out / "doc" / "log-2.md").exists()
    assert not _pyyaml_frontmatter(out / "doc" / "index-2.md").get("okf_version")


# --------------------------------------------------------------------------
# Slug uniqueness: a bumped slug must land on a name nobody else claims
# --------------------------------------------------------------------------

def _doc(title: str, summary: str) -> str:
    return f'---\nsummary: "{summary}"\n---\n\n# {title}\n\nBody.\n'


def _index_bullet_targets(index_md: Path) -> list[str]:
    """Every `* [Title](target.md) - description` link target, in file order."""
    return re.findall(r"^\* \[[^\]]*\]\(([^)]+)\)", index_md.read_text(encoding="utf-8"), re.M)


def test_bumped_slug_never_lands_on_a_slug_another_concept_owns(okf_export, tmp_path):
    """The reproduction from issue #152.

    Two `overview.md` sources collide; the loser is bumped to `overview-2`,
    which is the slug the third source already owns naturally. Today the two
    concepts share one file, so the bundle holds one fewer file than the
    manifest counts and one index bullet points at another concept's content.
    """
    root = tmp_path / "collision-instance"
    _write(root / "docs/api/overview.md", _doc("API Overview", "API overview"))
    _write(root / "docs/cli/overview.md", _doc("CLI Overview", "CLI overview"))
    _write(root / "docs/zz/overview-2.md", _doc("ZZ Overview Two", "Already owns overview-2"))
    out = tmp_path / "bundle-collision"
    manifest = okf_export.write_bundle(root, out, "core")

    assert manifest["concept_count"] == 3
    assert len(_concept_files(out)) == 3
    # The natural owner of `overview-2` keeps it; the bumped duplicate takes
    # the next FREE suffix instead of overwriting a name in use.
    assert _pyyaml_frontmatter(out / "doc" / "overview-2.md")["title"] == "ZZ Overview Two"
    assert _pyyaml_frontmatter(out / "doc" / "overview.md")["title"] == "API Overview"
    assert (out / "doc" / "overview-3.md").is_file()
    assert _pyyaml_frontmatter(out / "doc" / "overview-3.md")["title"] == "CLI Overview"


def test_reserved_bump_never_overwrites_a_real_index_2_source(okf_export, tmp_path):
    """The reserved half of the same hole.

    `docs/index.md` is bumped off the reserved slug onto `index-2`, which is
    the slug the real `docs/index-2.md` source owns. The concept destroyed is
    therefore not the duplicate but an untouched, uncontested source file.
    """
    root = tmp_path / "reserved-collision"
    _write(root / "docs/index.md", _doc("Index Doc", "Would collide with the reserved name"))
    _write(root / "docs/index-2.md", _doc("Real Index Two", "A genuine index-2 source"))
    out = tmp_path / "bundle-reserved-collision"
    manifest = okf_export.write_bundle(root, out, "core")

    assert manifest["concept_count"] == 2
    assert len(_concept_files(out)) == 2
    assert _pyyaml_frontmatter(out / "doc" / "index-2.md")["title"] == "Real Index Two"
    assert (out / "doc" / "index-3.md").is_file()
    assert _pyyaml_frontmatter(out / "doc" / "index-3.md")["title"] == "Index Doc"


@pytest.mark.parametrize("owner_dir", ["aa", "zz"])
def test_natural_owner_keeps_its_slug_in_either_discovery_order(okf_export, tmp_path, owner_dir):
    """The natural owner wins whether it is discovered before or after the
    duplicate that would be bumped onto its slug.

    Guards the plausible wrong fix (a SINGLE pass carrying a taken-set),
    which happens to be right when the owner sorts first and still steals the
    slug when it sorts last.
    """
    root = tmp_path / f"order-{owner_dir}"
    _write(root / f"docs/{owner_dir}/overview-2.md", _doc("Natural Owner", "Owns overview-2"))
    _write(root / "docs/api/overview.md", _doc("API Overview", "API overview"))
    _write(root / "docs/cli/overview.md", _doc("CLI Overview", "CLI overview"))
    out = tmp_path / f"bundle-order-{owner_dir}"
    okf_export.write_bundle(root, out, "core")

    assert len(_concept_files(out)) == 3
    assert _pyyaml_frontmatter(out / "doc" / "overview-2.md")["resource"] == (
        f"docs/{owner_dir}/overview-2.md"
    )


def test_bumped_stem_does_not_steal_a_later_natural_suffix(okf_export, tmp_path):
    """The suffix is appended to the concept's OWN natural slug.

    Guards a fix that parses the trailing number off `overview-2` and keeps
    counting from it: that hands the duplicate `overview-3`, which is a slug
    a third source owns naturally.
    """
    root = tmp_path / "stem-instance"
    _write(root / "docs/a/overview-2.md", _doc("A Two", "First overview-2"))
    _write(root / "docs/b/overview-2.md", _doc("B Two", "Second overview-2"))
    _write(root / "docs/c/overview-3.md", _doc("C Three", "Natural overview-3"))
    out = tmp_path / "bundle-stem"
    okf_export.write_bundle(root, out, "core")

    assert len(_concept_files(out)) == 3
    assert _pyyaml_frontmatter(out / "doc" / "overview-2.md")["title"] == "A Two"
    assert _pyyaml_frontmatter(out / "doc" / "overview-2-2.md")["title"] == "B Two"
    assert _pyyaml_frontmatter(out / "doc" / "overview-3.md")["title"] == "C Three"


def test_concept_count_equals_the_number_of_concept_files_written(okf_export, tmp_path):
    """The failure is silent in BOTH directions, so assert both halves.

    A count that outruns the file listing, and index bullets that point twice
    at one file, are the two user-visible symptoms of a lost concept.
    """
    root = tmp_path / "heavy-instance"
    _write(root / "docs/api/overview.md", _doc("API Overview", "One"))
    _write(root / "docs/cli/overview.md", _doc("CLI Overview", "Two"))
    _write(root / "docs/zz/overview-2.md", _doc("ZZ Overview", "Three"))
    _write(root / "docs/index.md", _doc("Index Doc", "Four"))
    _write(root / "docs/nested/index-2.md", _doc("Nested Index Two", "Five"))
    _write(root / "examples/api/overview.md", _doc("Example Overview", "Six"))
    _write(root / "examples/cli/overview.md", _doc("Example Overview Two", "Seven"))
    out = tmp_path / "bundle-heavy"
    manifest = okf_export.write_bundle(root, out, "core")

    assert manifest["concept_count"] == len(_concept_files(out))
    targets = _index_bullet_targets(out / "doc" / "index.md")
    assert len(targets) == len(set(targets)), f"index bullets share a target: {targets}"
    for target in targets:
        assert (out / "doc" / target).is_file(), f"index bullet points at a missing {target}"


def test_duplicate_slugs_raise_before_the_output_directory_is_cleared(
    okf_export, bridge_root, tmp_path, monkeypatch
):
    """Belt and braces behind dedupe_slugs, and its PLACEMENT matters.

    A future regression that lets two concepts share a (type, slug) must fail
    loudly, before the previous bundle is destroyed and before a single file
    is written, rather than producing a quietly short bundle.
    """
    prior = tmp_path / "bundle-prior"
    okf_export.write_bundle(bridge_root, prior, "core")
    prior_digest = _bundle_digest(prior)
    assert prior_digest

    root = tmp_path / "dup-instance"
    _write(root / "docs/api/overview.md", _doc("API Overview", "API overview"))
    _write(root / "docs/cli/overview.md", _doc("CLI Overview", "CLI overview"))
    monkeypatch.setattr(okf_export, "dedupe_slugs", lambda concepts: None)

    with pytest.raises(okf_export.BundleDestinationError):
        okf_export.write_bundle(root, prior, "core")
    assert _bundle_digest(prior) == prior_digest, "the previous bundle was destroyed"

    fresh = tmp_path / "bundle-never-created"
    with pytest.raises(okf_export.BundleDestinationError):
        okf_export.write_bundle(root, fresh, "core")
    assert not fresh.exists(), "a partial bundle directory was left behind"


def test_bundle_is_byte_identical_on_rerun_with_colliding_slugs(okf_export, tmp_path):
    """The existing determinism test uses a collision-free fixture, so it
    never exercised the bump path at all."""
    root = tmp_path / "rerun-instance"
    _write(root / "docs/api/overview.md", _doc("API Overview", "One"))
    _write(root / "docs/cli/overview.md", _doc("CLI Overview", "Two"))
    _write(root / "docs/zz/overview-2.md", _doc("ZZ Overview", "Three"))
    _write(root / "docs/index.md", _doc("Index Doc", "Four"))
    out = tmp_path / "bundle-rerun"

    manifest_1 = okf_export.write_bundle(root, out, "core")
    digest_1 = _bundle_digest(out)
    manifest_2 = okf_export.write_bundle(root, out, "core")
    digest_2 = _bundle_digest(out)
    assert manifest_1 == manifest_2
    assert digest_1 == digest_2


def test_slug_assignment_is_identical_for_two_identical_trees(okf_export, tmp_path):
    """Assignment depends on discovery order alone.

    Two separately built but content-identical trees must produce the same
    bytes, which no set or dict iteration order could guarantee.
    """
    files = {
        "docs/api/overview.md": _doc("API Overview", "One"),
        "docs/cli/overview.md": _doc("CLI Overview", "Two"),
        "docs/zz/overview-2.md": _doc("ZZ Overview", "Three"),
        "docs/index.md": _doc("Index Doc", "Four"),
        "docs/log.md": _doc("Log Doc", "Five"),
    }
    digests = []
    for run in ("one", "two"):
        root = tmp_path / f"twin-{run}"
        for relpath, content in files.items():
            _write(root / relpath, content)
        out = tmp_path / f"bundle-twin-{run}"
        okf_export.write_bundle(root, out, "core")
        digests.append(_bundle_digest(out))
    assert digests[0] == digests[1]


def test_memory_slug_collision_gets_a_free_suffix(okf_export, tmp_path):
    """Memory concepts are appended AFTER the repo concepts, so they take the
    same bump path, and their slug comes from `name:`, not the filename."""
    root = tmp_path / "memory-collision-root"
    _write(root / "docs/sample-doc.md", _doc("Sample Doc", "A doc"))
    mem = tmp_path / "memory-collision"
    _write(mem / "feedback_a.md", "---\nname: acme-thing\ndescription: First\n---\n\nA body.\n")
    _write(mem / "feedback_b.md", "---\nname: acme-thing\ndescription: Second\n---\n\nB body.\n")
    _write(mem / "feedback_c.md", "---\nname: acme-thing-2\ndescription: Third\n---\n\nC body.\n")
    out = tmp_path / "bundle-memory-collision"
    manifest = okf_export.write_bundle(root, out, "user", memory_dir=mem)

    memory_files = sorted(p.name for p in (out / "memory").glob("*.md") if p.name != "index.md")
    assert len(memory_files) == 3, memory_files
    assert manifest["concept_count"] == len(_concept_files(out))
    # feedback_c.md owns `acme-thing-2` naturally even though it is discovered
    # last; the duplicate feedback_b.md is the one that moves.
    assert _pyyaml_frontmatter(out / "memory" / "acme-thing-2.md")["resource"] == (
        "memory/feedback_c.md"
    )


# --------------------------------------------------------------------------
# Slug uniqueness is a FILESYSTEM property, not a byte-string one
# --------------------------------------------------------------------------

def _fs_name(name: str) -> str:
    """The filesystem's own name identity, restated independently of the
    exporter: NFC-normalized and case-folded.

    Written out here rather than imported from the module under test, so
    these tests measure the RULE (two names that are one file) instead of
    echoing whatever the implementation happens to compute.
    """
    return unicodedata.normalize("NFC", name).casefold()


def _marked_doc(title: str, marker: str) -> str:
    """A doc source whose BODY carries a marker found nowhere else.

    The marker never appears in the title or the description, so it can only
    reach the bundle through the concept file the exporter writes for this
    source: finding it proves the body survived, and the generated indexes
    cannot supply it by accident.
    """
    return f'---\nsummary: "A doc"\n---\n\n# {title}\n\n{marker}\n'


def _assert_every_concept_reached_the_bundle(out: Path, manifest: dict, markers: list[str]) -> None:
    """The invariant behind issue #152, stated for ANY bundle rather than for
    one example tree.

    Two halves, because a lost concept is silent in both directions.

    COUNT. A populated type directory holds exactly one file per concept of
    that type plus the one index the exporter generates for it, so the whole
    bundle holds concept_count + one index per type directory + the root
    index. A bundle short of that is a bundle whose manifest counts a
    concept the filesystem no longer has.

    BODY. Every marker is still somewhere in the bundle, in exactly one
    file. The count alone passes when a GENERATED index overwrites a
    concept, because the eaten file is still a file: only the body says
    whether what is left is the concept or the index that landed on it.
    """
    type_dirs = sorted(p for p in out.iterdir() if p.is_dir())
    files = sorted(out.rglob("*.md"))
    expected = manifest["concept_count"] + len(type_dirs) + 1
    assert len(files) == expected, (
        f"bundle holds {len(files)} files, expected {expected} "
        f"({manifest['concept_count']} concepts + {len(type_dirs)} type "
        f"index(es) + the root index): {[p.name for p in files]}"
    )
    for marker in markers:
        holders = sorted(p.name for p in files if marker in p.read_text(encoding="utf-8"))
        assert len(holders) == 1, f"{marker} is in {holders}, expected exactly one file"


def test_two_slugs_differing_only_in_case_both_reach_the_bundle(okf_export, tmp_path):
    """Issue #152's symptom, reached through case instead of byte equality.

    `readme` and `README` are two byte-distinct slugs and one filename on a
    case-insensitive filesystem (the macOS default), so the second write
    lands on the first file: the manifest counts two doc concepts and the
    bundle holds one, exit code 0, no warning.
    """
    root = tmp_path / "case-instance"
    _write(root / "docs/api/readme.md", _marked_doc("Api Readme", "MARKER_LOWER"))
    _write(root / "docs/cli/README.md", _marked_doc("Cli Readme", "MARKER_UPPER"))
    # A fixture that silently made ONE file would make every assertion below
    # pass for the wrong reason, so prove the two sources exist first. They
    # live in DIFFERENT parent directories precisely because they could not
    # coexist in one.
    sources = sorted(p.relative_to(root).as_posix() for p in root.rglob("*.md"))
    assert sources == ["docs/api/readme.md", "docs/cli/README.md"], sources

    out = tmp_path / "bundle-case"
    manifest = okf_export.write_bundle(root, out, "core")

    assert manifest["concept_count"] == 2
    _assert_every_concept_reached_the_bundle(out, manifest, ["MARKER_LOWER", "MARKER_UPPER"])
    # The EMITTED filename is the concept's own slug, never a folded key: the
    # natural owner (discovered first) keeps its lowercase stem and the
    # duplicate takes a suffix on its OWN stem, capitals intact. Compared
    # against the directory listing, so this is a byte-exact name check
    # rather than a case-insensitive existence probe.
    assert sorted(p.name for p in (out / "doc").iterdir()) == [
        "README-2.md",
        "index.md",
        "readme.md",
    ]


def test_two_slugs_differing_only_in_normalization_both_reach_the_bundle(okf_export, tmp_path):
    """The same hole through Unicode normalization instead of case.

    APFS preserves the bytes of a filename but compares NFC and NFD
    spellings of one character as the same name, so two byte-distinct
    `café.md` sources are one file in the bundle.
    """
    nfc = unicodedata.normalize("NFC", "café")
    nfd = unicodedata.normalize("NFD", "café")
    assert nfc != nfd, "the fixture needs two distinct byte spellings"

    root = tmp_path / "normalization-instance"
    _write(root / "docs/x" / f"{nfc}.md", _marked_doc("Cafe NFC", "MARKER_NFC"))
    _write(root / "docs/y" / f"{nfd}.md", _marked_doc("Cafe NFD", "MARKER_NFD"))
    sources = sorted(p.relative_to(root).as_posix() for p in root.rglob("*.md"))
    assert sources == [f"docs/x/{nfc}.md", f"docs/y/{nfd}.md"], sources

    out = tmp_path / "bundle-normalization"
    manifest = okf_export.write_bundle(root, out, "core")

    assert manifest["concept_count"] == 2
    _assert_every_concept_reached_the_bundle(out, manifest, ["MARKER_NFC", "MARKER_NFD"])
    assert sorted(p.name for p in (out / "doc").iterdir()) == sorted(
        [f"{nfc}.md", f"{nfd}-2.md", "index.md"]
    )


@pytest.mark.parametrize("stem", ["Index", "INDEX", "Log", "LOG", "lOg"])
def test_a_reserved_slug_in_another_case_is_still_reserved(okf_export, tmp_path, stem):
    """The exporter's own generated index eats a source concept.

    The reserved-name check compares bytes, so `docs/Index.md` keeps the slug
    `Index` and is written to `doc/Index.md`. write_bundle then writes the
    generated `doc/index.md` LAST, which is the same file on this
    filesystem, and the source concept is gone. Parametrized over several
    spellings on purpose: a fix keyed on the three literal trees in the
    report would leave the fourth one live.
    """
    root = tmp_path / f"reserved-case-{stem}"
    _write(root / f"docs/{stem}.md", _marked_doc(f"{stem} Doc", "UNIQUE_BODY_MARKER_A"))
    _write(root / "docs/other.md", _marked_doc("Other Doc", "UNIQUE_BODY_MARKER_B"))
    out = tmp_path / f"bundle-reserved-case-{stem}"
    manifest = okf_export.write_bundle(root, out, "core")

    assert manifest["concept_count"] == 2
    _assert_every_concept_reached_the_bundle(
        out, manifest, ["UNIQUE_BODY_MARKER_A", "UNIQUE_BODY_MARKER_B"]
    )
    # The generated index is still a generated index, and the source concept
    # is still a concept: neither has become the other.
    assert (out / "doc" / "index.md").read_text(encoding="utf-8").startswith("# Doc Index")
    # And no concept file NAMES a reserved file, whatever its spelling: `log`
    # generates nothing today, so a `Log.md` concept survives the count check
    # by luck and would be eaten the day the change-history file lands.
    for path in (out / "doc").iterdir():
        if path.name == "index.md":
            continue
        assert _fs_name(path.stem) not in {"index", "log"}, (
            f"concept written as {path.name}, which is a reserved bundle filename"
        )


def test_memory_names_differing_only_in_case_both_reach_the_bundle(okf_export, tmp_path):
    """The memory path, whose slug comes from a fact's `name:` rather than
    from a filename, and is therefore not safe by construction.

    Also pins the property a bumped memory slug must keep: it stays a legal
    single path segment under _SAFE_SLUG_RE, so the suffix can never be the
    thing that lets a slug escape its type directory.
    """
    root = tmp_path / "memory-case-root"
    _write(root / "docs/sample-doc.md", _marked_doc("Sample Doc", "MARKER_DOC"))
    mem = tmp_path / "memory-case"
    _write(mem / "feedback_a.md", "---\nname: acme-thing\n---\n\nMARKER_MEM_LOWER\n")
    _write(mem / "feedback_b.md", "---\nname: Acme-Thing\n---\n\nMARKER_MEM_UPPER\n")
    out = tmp_path / "bundle-memory-case"
    manifest = okf_export.write_bundle(root, out, "user", memory_dir=mem)

    assert manifest["concept_count"] == 3
    _assert_every_concept_reached_the_bundle(
        out, manifest, ["MARKER_DOC", "MARKER_MEM_LOWER", "MARKER_MEM_UPPER"]
    )
    for path in (out / "memory").iterdir():
        if path.name == "index.md":
            continue
        assert okf_export._SAFE_SLUG_RE.match(path.stem), (
            f"bumped memory slug {path.stem!r} is not a safe path segment"
        )


def test_the_uniqueness_guard_also_sees_a_case_only_duplicate(okf_export, tmp_path, monkeypatch):
    """_assert_unique_slugs is the backstop behind dedupe_slugs, so it has to
    measure the same namespace dedupe_slugs does.

    A guard that compares bytes while the filesystem compares folded names
    waves through exactly the collision it exists to catch.
    """
    root = tmp_path / "guard-case-instance"
    _write(root / "docs/api/readme.md", _marked_doc("Api Readme", "MARKER_LOWER"))
    _write(root / "docs/cli/README.md", _marked_doc("Cli Readme", "MARKER_UPPER"))
    monkeypatch.setattr(okf_export, "dedupe_slugs", lambda concepts: None)

    fresh = tmp_path / "bundle-never-created"
    with pytest.raises(okf_export.BundleDestinationError):
        okf_export.write_bundle(root, fresh, "core")
    assert not fresh.exists(), "a partial bundle directory was left behind"


def test_folding_the_uniqueness_key_does_not_fold_wikilink_resolution(okf_export, tmp_path):
    """Deliberate limit of the fix, pinned so it is a decision and not a
    later surprise.

    The wikilink grammar is ASCII lowercase kebab (`[a-z][a-z0-9-]*`), so a
    folded link index could only ever differ from an exact one where the
    target slug is NOT lowercase kebab, i.e. where the link text could never
    have named it in the first place. Folding there would invent a target
    the author did not write, and would have to pick arbitrarily between two
    now-distinct files. `slug_to_relpath` therefore stays byte-exact:
    `[[readme]]` resolves to the concept whose slug IS `readme`, and reaches
    nothing when no concept spells it that way.
    """
    root = tmp_path / "wikilink-case-instance"
    _write(root / "docs/api/readme.md", _marked_doc("Api Readme", "MARKER_LOWER"))
    _write(root / "docs/cli/README.md", _marked_doc("Cli Readme", "MARKER_UPPER"))
    _write(root / "docs/other.md", _marked_doc("Other Doc", "See [[readme]] for more."))
    out = tmp_path / "bundle-wikilink-case"
    manifest = okf_export.write_bundle(root, out, "core")

    assert manifest["unresolved_wikilinks"] == []
    body = (out / "doc" / "other.md").read_text(encoding="utf-8")
    assert "[readme](/doc/readme.md)" in body

    # ... and with no exact `readme` owner in the tree, the link stays whole
    # rather than being handed to the `README` concept.
    upper_only = tmp_path / "wikilink-upper-only"
    _write(upper_only / "docs/cli/README.md", _marked_doc("Cli Readme", "MARKER_UPPER"))
    _write(upper_only / "docs/other.md", _marked_doc("Other Doc", "See [[readme]] for more."))
    out_upper = tmp_path / "bundle-wikilink-upper"
    manifest_upper = okf_export.write_bundle(upper_only, out_upper, "core")

    assert manifest_upper["unresolved_wikilinks"] == ["readme"]
    assert "[[readme]]" in (out_upper / "doc" / "other.md").read_text(encoding="utf-8")


def _folded_collision_tree(root: Path) -> None:
    """One tree carrying every folded-collision shape at once."""
    nfc = unicodedata.normalize("NFC", "café")
    nfd = unicodedata.normalize("NFD", "café")
    _write(root / "docs/api/readme.md", _marked_doc("Api Readme", "MARKER_LOWER"))
    _write(root / "docs/cli/README.md", _marked_doc("Cli Readme", "MARKER_UPPER"))
    _write(root / "docs/zz/ReadMe.md", _marked_doc("Zz Readme", "MARKER_MIXED"))
    _write(root / "docs/x" / f"{nfc}.md", _marked_doc("NFC", "MARKER_NFC"))
    _write(root / "docs/y" / f"{nfd}.md", _marked_doc("NFD", "MARKER_NFD"))
    _write(root / "docs/Index.md", _marked_doc("Index Doc", "MARKER_INDEX"))
    _write(root / "docs/LOG.md", _marked_doc("Log Doc", "MARKER_LOG"))


def test_folded_collision_bundle_is_byte_identical_on_rerun(okf_export, tmp_path):
    """Determinism has to hold on the path the fix added, not only on the
    collision-free fixture."""
    root = tmp_path / "folded-rerun-instance"
    _folded_collision_tree(root)
    out = tmp_path / "bundle-folded-rerun"

    manifest_1 = okf_export.write_bundle(root, out, "core")
    digest_1 = _bundle_digest(out)
    manifest_2 = okf_export.write_bundle(root, out, "core")
    digest_2 = _bundle_digest(out)
    assert manifest_1 == manifest_2
    assert digest_1 == digest_2


def test_folded_collision_bundle_is_identical_across_hash_seeds(tmp_path):
    """The folded key is a set membership test, and a set is exactly where a
    hash-ordered assignment would hide. Measured from fresh interpreters,
    since in-process iteration order is stable for the life of one."""
    root = tmp_path / "folded-seed-instance"
    _folded_collision_tree(root)
    digests = [
        _export_in_a_fresh_process(root, tmp_path / f"bundle-folded-{seed}", "core", seed)
        for seed in _HASH_SEEDS
    ]
    assert digests[0], "the export produced no files to compare"
    for seed, digest in zip(_HASH_SEEDS[1:], digests[1:]):
        differing = sorted(
            name for name in set(digest) | set(digests[0])
            if digest.get(name) != digests[0].get(name)
        )
        assert not differing, f"PYTHONHASHSEED={seed} produced a different bundle: {differing}"


def test_manifest_reports_generated_by_and_undated_count(okf_export, bridge_root, tmp_path):
    out = tmp_path / "bundle-manifest"
    manifest = okf_export.write_bundle(bridge_root, out, "user")
    assert manifest["okf_version"] == "0.2"
    assert manifest["generated_by"] == f"okf-export/{okf_export.EXPORTER_VERSION}"
    # sample-rule.md and examples/acme-demo/README.md carry no date at all
    assert manifest["concepts_without_generated_at"] == 2
    assert isinstance(manifest["concepts_without_generated_at"], int)


def test_contract_docstring_and_guide_declare_v0_2():
    """A half-migrated suite would freeze v0.1 semantics while the bundle says 0.2."""
    contract = Path(__file__).read_text(encoding="utf-8")
    guide = (REPO_ROOT / "docs" / "okf-export.md").read_text(encoding="utf-8")
    assert 'OKF_VERSION: str' in contract and '"0.2"' in contract
    # The guide may REFERENCE v0.1 (the migration note does); what it must not
    # do is still describe itself as PRODUCING one.
    assert "(OKF) v0.2 bundle" in guide
    assert "(OKF) v0.1 bundle" not in guide
    for declined in ("verified", "sources", "stale_after"):
        assert declined in guide, f"guide does not state why {declined} is not emitted"


# --------------------------------------------------------------------------
# YAML safety: every emitted frontmatter block must survive a REAL parser
# --------------------------------------------------------------------------

@pytest.fixture
def hostile_root(tmp_path: Path) -> Path:
    """A mini instance whose frontmatter values are hostile to naive quoting.

    Kept separate from ``bridge_root`` on purpose: that fixture's file count
    is asserted verbatim by the discovery tests, so growing it would couple
    unrelated suites together.
    """
    root = tmp_path / "hostile-instance"
    _write(
        root / "docs/block-title.md",
        "---\n"
        "title: |\n"
        "  Line one\n"
        "  Line two\n"
        'summary: "Doc whose title is a block scalar"\n'
        "---\n\n"
        "Body.\n",
    )
    _write(
        root / "work/tasks/comma-tag/STATUS.md",
        "---\n"
        'status: "final, not sent"\n'
        "context: acme\n"
        "---\n\n"
        "# Comma Tag\n\nBody.\n",
    )
    _write(
        root / "work/tasks/bracket-tag/STATUS.md",
        "---\n"
        'status: "blocked [see issue 42]"\n'
        "context: acme\n"
        "---\n\n"
        "# Bracket Tag\n\nBody.\n",
    )
    # A colon-space is the block-context indicator, so unlike a comma or a
    # bracket it breaks `description:` and `bridge_status:` rather than the
    # flow sequence. Without it the quoting of those two positions is untested.
    _write(
        root / "docs/colon-desc.md",
        "---\n"
        'summary: "Note: this description carries a colon"\n'
        "---\n\n"
        "# Colon Desc\n\nBody.\n",
    )
    _write(
        root / "work/tasks/colon-status/STATUS.md",
        "---\n"
        'status: "blocked: waiting on review"\n'
        "---\n\n"
        "# Colon Status\n\nBody.\n",
    )
    return root


def test_colon_bearing_description_and_status_survive_a_real_parser(okf_export, hostile_root, tmp_path):
    """A colon-space would otherwise turn one scalar into a nested mapping."""
    out = tmp_path / "bundle-hostile-colon"
    okf_export.write_bundle(hostile_root, out, "user")
    assert _pyyaml_frontmatter(out / "doc" / "colon-desc.md")["description"] == (
        "Note: this description carries a colon"
    )
    assert _pyyaml_frontmatter(out / "task" / "colon-status.md")["bridge_status"] == (
        "blocked: waiting on review"
    )


def test_render_escapes_newlines_in_quoted_scalars(okf_export):
    """A multi-line scalar must render on ONE physical line, escaped.

    Today it is emitted verbatim, so the value silently folds (newline ->
    space) or, if a line happens to start with `---` or hold a control
    character, produces frontmatter no real parser can read at all.
    """
    quoted = okf_export._yaml_quote("Line one\nLine two")
    assert "\n" not in quoted
    assert quoted == '"Line one\\nLine two"'
    assert yaml.safe_load(f"title: {quoted}")["title"] == "Line one\nLine two"


@pytest.mark.parametrize(
    "value",
    [
        "Head\tTabbed\x01ctrl\rreturn",
        r"C:\path\to\thing",          # backslash: without escaping, YAML reads \t as a tab
        'He said "stop"',             # embedded quote closes the scalar
        r'mixed \ and " together',
        "trailing backslash \\",
    ],
)
def test_yaml_quote_roundtrips_through_a_real_parser(okf_export, value):
    quoted = okf_export._yaml_quote(value)
    assert yaml.safe_load(f"title: {quoted}")["title"] == value


def test_block_scalar_title_roundtrips_through_pyyaml(okf_export, hostile_root, tmp_path):
    """Both lines of a `title: |` block scalar survive the export."""
    out = tmp_path / "bundle-hostile-title"
    okf_export.write_bundle(hostile_root, out, "user")
    fm = _pyyaml_frontmatter(out / "doc" / "block-title.md")
    assert fm["title"] == "Line one\nLine two"


def test_exported_description_keeps_the_issue_number(okf_export, tmp_path):
    """End to end: a `#` in a quoted headline reaches the emitted bundle.

    Measured with a real YAML parser rather than the exporter's own reader,
    so a lenient producer cannot be validated by an equally lenient consumer.
    """
    root = tmp_path / "issue-number-instance"
    _write(
        root / "work/tasks/cart-pass/STATUS.md",
        "---\n"
        "status: review\n"
        'headline: "cart fixes in review as PR #214"\n'
        "---\n\n"
        "# Cart Pass\n\nBody.\n",
    )
    out = tmp_path / "bundle-issue-number"
    okf_export.write_bundle(root, out, "user")
    fm = _pyyaml_frontmatter(out / "task" / "cart-pass.md")
    assert fm["description"] == "cart fixes in review as PR #214"


def test_rendered_value_containing_a_yaml_fence_does_not_end_the_block(okf_export):
    """A `---` inside a VALUE must not terminate the emitted frontmatter.

    Asserted at the render boundary, which is the half the exporter owns:
    whatever value arrives, the block it writes stays one parseable unit.
    The source half is now covered too, by
    test_indented_fence_inside_a_block_scalar_does_not_close_the_frontmatter.
    That such a value could not be delivered through a fixture used to be
    true, and it was a defect rather than a property: the parser closed its
    block at the first line that STRIPPED to `---`, which an indented
    block-scalar line does.
    """
    concept = {
        "okf_type": "doc",
        "title": "Heading\n---\nTrailer",
        "description": "",
        "resource": "docs/x.md",
        "timestamp": "",
        "tags": [],
        "body": "Body.\n",
    }
    rendered = okf_export._render_concept(concept)
    _, block, body = rendered.split("---\n", 2)
    assert yaml.safe_load(block)["title"] == "Heading\n---\nTrailer"
    assert body == "Body.\n"


def test_tag_containing_comma_does_not_split_into_two_tags(okf_export, hostile_root, tmp_path):
    """`final, not sent` is ONE tag, not two."""
    out = tmp_path / "bundle-hostile-comma"
    okf_export.write_bundle(hostile_root, out, "user")
    tags = _pyyaml_frontmatter(out / "task" / "comma-tag.md")["tags"]
    assert "final, not sent" in tags
    assert len(tags) == 2  # the status value plus the context value, never three


def test_tag_containing_bracket_does_not_corrupt_the_list(okf_export, hostile_root, tmp_path):
    """A `]` inside a tag must not close the flow sequence early."""
    out = tmp_path / "bundle-hostile-bracket"
    okf_export.write_bundle(hostile_root, out, "user")
    tags = _pyyaml_frontmatter(out / "task" / "bracket-tag.md")["tags"]
    assert "blocked [see issue 42]" in tags


def test_every_emitted_concept_frontmatter_parses_with_pyyaml(okf_export, hostile_root, tmp_path):
    """OKF conformance clause 1, swept over a whole hostile bundle."""
    out = tmp_path / "bundle-hostile-sweep"
    okf_export.write_bundle(hostile_root, out, "user")
    concepts = [p for p in out.rglob("*.md") if p.name != "index.md"]
    assert concepts, "fixture produced no concept files"
    for path in concepts:
        fm = _pyyaml_frontmatter(path)
        assert isinstance(fm, dict), path
        assert fm.get("type"), f"{path} has no non-empty type"  # clause 2


# --------------------------------------------------------------------------
# Silent source losses the first two fixes left standing (issue #151's shape)
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "line",
    [
        # A plain scalar whose last character is a quote. Legal YAML, everyday
        # prose, and the historic `value.strip('"').strip("'")` ate the quote.
        'title: The so-called "bridge"',
        "title: it is 'fine'",
        'title: monitor is 12"',
        "description: a take on the \"hand-rolled parser\"",
        # Both ends, still never a quoted scalar: a plain scalar cannot OPEN
        # with a quote, so nothing here was ever delimited.
        "title: ask \"who\"",
    ],
)
def test_a_plain_scalar_keeps_a_quote_it_ends_on(okf_export, line):
    """REGRESSION: an unquoted value must not lose a trailing quote character.

    PyYAML round-trips every line here, so this is not a malformed source
    degrading: it is a well-formed one being shortened. The historic strip
    ran on BOTH ends of every fallen-through value, and a plain scalar never
    had an opening quote for the closing one to pair with. Measured against a
    real parser rather than against a hand-written expectation, because the
    claim being made is agreement with YAML.
    """
    key = line.split(":", 1)[0]
    fm, _ = okf_export.parse_frontmatter(f"---\n{line}\n---\n\nBody.\n")
    assert fm[key] == yaml.safe_load(line)[key]


def test_a_plain_scalar_keeps_unicode_whitespace_yaml_counts_as_content(okf_export):
    """`str.strip()` is Unicode-aware; a YAML plain scalar is trimmed of
    spaces and tabs only.

    A description pasted out of a browser or a word processor routinely ends
    in U+00A0, and the exporter dropped it. Nothing marks the loss.
    """
    for line in [
        # Trailing: `str.strip()` is Unicode-aware; a YAML plain scalar is
        # trimmed of spaces and tabs only.
        "description: a NBSP tail ",
        # Leading: the `key:` separator is spaces and tabs, so a value that
        # STARTS with U+00A0 starts with content. `\\s*` ate it, and the
        # `'quoted'` left behind then went down the fallen-through quote
        # path and came out empty.
        "description:  'a NBSP head'",
        # In the middle: YAML opens an inline comment on a `#` after a
        # space or a tab, not after any Unicode space. `\\s` in the comment
        # pattern read U+00A0 as one and truncated the value there.
        "description: before #after",
    ]:
        fm, _ = okf_export.parse_frontmatter(f"---\n{line}\n---\n\nBody.\n")
        assert fm["description"] == yaml.safe_load(line)["description"], repr(line)


def test_a_byte_order_mark_does_not_hide_the_frontmatter_block(okf_export):
    """A UTF-8 BOM made the whole block invisible, keys and all.

    `str.rstrip()` does not remove U+FEFF, so `\\ufeff---` never equalled
    `---` and the file was read as having no frontmatter: title fell back to
    the body H1, description and last_updated were dropped, and the raw
    frontmatter text was emitted into the concept body.
    """
    body = "---\ntitle: \"Real Title\"\ndescription: \"Load bearing\"\nlast_updated: 2026-01-02\n---\n\n# Body H1\n\ntext\n"
    fm, rest = okf_export.parse_frontmatter("﻿" + body)
    assert fm["title"] == "Real Title"
    assert fm["description"] == "Load bearing"
    assert fm["last_updated"] == "2026-01-02"
    assert rest == "\n# Body H1\n\ntext\n"
    assert okf_export.parse_frontmatter("﻿" + body) == okf_export.parse_frontmatter(body)


def test_a_bom_source_reaches_the_bundle_with_its_own_title_and_date(okf_export, tmp_path):
    """The same defect end to end, where it is visible: the concept."""
    root = tmp_path / "bom-instance"
    _write(
        root / "docs" / "bom.md",
        "﻿---\ntitle: \"Real Title\"\ndescription: \"Load bearing\"\n"
        "last_updated: 2026-01-02\n---\n\n# Body H1\n\ntext\n",
    )
    out = tmp_path / "bom-bundle"
    okf_export.write_bundle(root, out, "core")
    emitted = (out / "doc" / "bom.md").read_text(encoding="utf-8")
    fm = _pyyaml_frontmatter(out / "doc" / "bom.md")
    assert fm["title"] == "Real Title"
    assert fm["description"] == "Load bearing"
    assert "at: 2026-01-02T00:00:00Z" in emitted
    assert "title:" not in emitted.split("---\n", 2)[2], (
        "the source frontmatter leaked into the concept body"
    )


@pytest.mark.parametrize("separator", [" ", " "])
def test_a_unicode_line_separator_inside_a_scalar_does_not_truncate_it(okf_export, separator):
    """`str.splitlines` breaks on U+2028/U+2029; YAML does not.

    The value was cut at the separator: the quoted scalar never closed on its
    own pseudo-line, so it fell through to the plain path and lost its tail.
    PyYAML accepts both characters inside a double-quoted scalar and returns
    them verbatim, which makes this a disagreement on well-formed input.
    """
    block = f'title: "Alpha{separator}Beta"\ndescription: "before{separator}after"\n'
    fm, rest = okf_export.parse_frontmatter(f"---\n{block}---\n\nBody.\n")
    assert fm == yaml.safe_load(block)
    assert rest == "\nBody.\n"


def test_an_emitted_concept_round_trips_through_both_parsers(okf_export, tmp_path):
    """What the exporter writes, the exporter (and a real parser) can read back.

    A separator character in a source title reached the concept file raw, and
    the exporter's own parser then truncated it there: the bundle it produced
    was not a bundle it could read.
    """
    root = tmp_path / "sep-instance"
    _write(root / "docs" / "sep.md", '---\ntitle: "Alpha Beta"\n---\n\n# H1\n\nbody\n')
    out = tmp_path / "sep-bundle"
    okf_export.write_bundle(root, out, "core")

    emitted = (out / "doc" / "sep.md").read_text(encoding="utf-8")
    assert okf_export.parse_frontmatter(emitted)[0]["title"] == "Alpha Beta"
    assert _pyyaml_frontmatter(out / "doc" / "sep.md")["title"] == "Alpha Beta"
    # The INDEX still flattens it: _is_control covers U+2028 so an entry
    # cannot split across two lines for a consumer using str.splitlines.
    entries = _index_entry_lines(out / "doc" / "index.md")
    assert entries == ["* [Alpha Beta](sep.md)"]


def test_an_indented_closing_fence_outside_a_block_scalar_still_closes(okf_export):
    """REGRESSION introduced by the column-0 rule, and the reason it needs
    block-scalar state rather than a column test alone.

    #151's block-scalar case needs an indented `---` to stay content INSIDE a
    block scalar. Making every indented `---` content costs the body of any
    file that merely indents its closing fence: the scan reads on to the next
    column-0 `---` and swallows everything in between as frontmatter, or,
    where no later fence exists, gives up and reports no frontmatter at all.
    origin/main parsed both of these.
    """
    with_later_fence = (
        '---\ntitle: "T"\n  ---\n\nThe entire body that must reach the bundle.\n\n---\ntrailer\n'
    )
    fm, body = okf_export.parse_frontmatter(with_later_fence)
    assert fm == {"title": "T"}
    assert body == "\nThe entire body that must reach the bundle.\n\n---\ntrailer\n"

    without_later_fence = "---\ntitle: A\nstatus: doing\n  ---\nBody one.\n"
    fm, body = okf_export.parse_frontmatter(without_later_fence)
    assert fm == {"title": "A", "status": "doing"}
    assert body == "Body one.\n"


def test_the_block_scalar_fence_rule_survives_the_indented_closer(okf_export):
    """GUARD: the #151 case must not come back when the closer loosens again.

    An indented `---` inside a `title: |` block is content; the same line
    outside one closes the frontmatter. Both in one file, so a fix that
    reaches for either rule alone fails here.
    """
    text = (
        "---\n"
        "title: |\n"
        "  Heading\n"
        "  ---\n"
        "  Trailer\n"
        "status: doing\n"
        "  ---\n"
        "Body.\n"
    )
    fm, body = okf_export.parse_frontmatter(text)
    assert fm == {"title": "Heading\n---\nTrailer", "status": "doing"}
    assert body == "Body.\n"


# --------------------------------------------------------------------------
# A refused or failed run must leave the previous bundle usable
# --------------------------------------------------------------------------

def test_a_slug_too_long_for_the_filesystem_is_refused_before_the_rmtree(okf_export, tmp_path):
    """_SAFE_SLUG_RE bounds a memory `name:` in shape but not in LENGTH.

    A 300-character name passed every gate and then raised a bare OSError
    from `write_text`, AFTER the rmtree and BEFORE the root index.md: the
    previous bundle was gone and the destination no longer looked like a
    bundle, so every later run refused it and the operator had to delete the
    directory by hand. The exporter's own stated invariant is that a failure
    fails with the previous bundle intact, not after it.
    """
    root = tmp_path / "long-instance"
    _write(root / "docs" / "a.md", '---\ntitle: "A"\n---\n\n# A\n\nbody\n')
    mem = tmp_path / "long-memory"
    _write(mem / "reference_ok.md", "---\nname: ok-fact\n---\n\nbody\n")
    out = tmp_path / "long-bundle"

    first = okf_export.write_bundle(root, out, "user", memory_dir=mem)
    assert first["concept_count"] == 2

    _write(mem / "reference_long.md", f"---\nname: {'a' * 300}\n---\n\nbody\n")
    with pytest.raises(okf_export.BundleDestinationError) as excinfo:
        okf_export.write_bundle(root, out, "user", memory_dir=mem)
    assert "too long" in str(excinfo.value)
    assert okf_export._is_bundle_dir(out), "the previous bundle must survive a refused run"

    (mem / "reference_long.md").unlink()
    assert okf_export.write_bundle(root, out, "user", memory_dir=mem)["concept_count"] == 2


def test_a_write_that_dies_mid_bundle_leaves_a_destination_the_next_run_can_clear(
    okf_export, tmp_path, monkeypatch
):
    """The root index.md goes down FIRST, so a crash is recoverable.

    _is_bundle_dir keys off that file. Written last, ANY mid-write failure (a
    full disk, a permission error, a name the filesystem rejects) left a
    non-empty directory that no longer looked like a bundle, and the exporter
    then refused its own destination forever.
    """
    root = tmp_path / "crash-instance"
    _write(root / "docs" / "a.md", '---\ntitle: "A"\n---\n\n# A\n\nbody\n')
    out = tmp_path / "crash-bundle"

    def _boom(concept, generated_by=None):  # pragma: no cover - raises by design
        raise OSError(63, "File name too long")

    monkeypatch.setattr(okf_export, "_render_concept", _boom)
    with pytest.raises(OSError):
        okf_export.write_bundle(root, out, "core")
    monkeypatch.undo()

    assert okf_export._is_bundle_dir(out), (
        "a half-written destination the exporter can never clear again"
    )
    assert okf_export.write_bundle(root, out, "core")["concept_count"] == 1


def test_an_out_dir_that_is_an_existing_file_is_refused_cleanly(okf_export, bridge_root, tmp_path):
    """`Path.iterdir` raises NotADirectoryError on a regular file.

    The documented exit-code contract promises a stderr line for a refused
    --out; what the operator got was a Python traceback.
    """
    target = tmp_path / "not-a-dir"
    target.write_text("hi", encoding="utf-8")
    with pytest.raises(okf_export.BundleDestinationError):
        okf_export.write_bundle(bridge_root, target, "core")
    assert target.read_text(encoding="utf-8") == "hi"


def test_main_cli_refuses_a_file_out_with_a_message_not_a_traceback(
    okf_export, bridge_root, tmp_path, capsys
):
    target = tmp_path / "cli-not-a-dir"
    target.write_text("hi", encoding="utf-8")
    rc = okf_export.main(["--root", str(bridge_root), "--out", str(target), "--scope", "core"])
    assert rc == 1
    assert capsys.readouterr().err.startswith("ERROR: ")


# --------------------------------------------------------------------------
# The destination guard: a symlinked LITERAL segment, and the memory store
# --------------------------------------------------------------------------

def test_scanned_dirs_sees_a_directory_reached_through_a_globbed_segment(okf_export, tmp_path):
    """The fixed prefix is not the whole read set.

    `Path.glob` follows a symlink at every LITERAL segment after the globbed
    part, so `work/**/deliverables/*.md` reads through a link named
    `deliverables`. Resolving only `_pattern_prefix` ("work") leaves that
    target invisible to the guard.
    """
    root = tmp_path / "instance"
    (root / "work" / "loop").mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    _symlink_or_skip(root / "work" / "loop" / "deliverables", elsewhere)

    assert elsewhere.resolve() in okf_export.scanned_dirs(root, "user")


def test_a_symlinked_segment_after_a_glob_cannot_hide_the_destination(okf_export, tmp_path):
    """Issue #153's signature through a spelling the prefix guard cannot see.

    Measured before this fix: `work/loop/deliverables -> <out>/deliverable`
    and the count went 2, 4, 6, 8, 10 across five runs, exit 0 every time,
    with the bundle filling up with `d1-2.md`, `d1-3.md`, `index-2.md`. The
    guard has to read the same glob engine the walk does.
    """
    root = tmp_path / "instance"
    _write(root / "docs" / "a.md", '---\ntitle: "A"\n---\n\n# A\n\nbody a\n')
    _write(
        root / "work" / "real" / "deliverables" / "d1.md",
        '---\ntitle: "D1"\n---\n\n# D1\n\ndeliv one\n',
    )
    (root / "work" / "loop").mkdir(parents=True, exist_ok=True)
    out = tmp_path / "bundle"
    _symlink_or_skip(root / "work" / "loop" / "deliverables", out / "deliverable")

    with pytest.raises(okf_export.BundleDestinationError):
        okf_export.write_bundle(root, out, "user", memory_dir=None)
    assert not (out / "index.md").exists(), "guard raised but the bundle was written anyway"


@pytest.mark.parametrize("scope", ["core", "user"])
def test_the_memory_dir_is_refused_as_a_destination_in_every_scope(
    okf_export, bridge_root, memory_dir, scope
):
    """The union rule the scanned-directory clause already follows.

    A bundle outlives the run that wrote it. A core-scope run gated out of
    this clause wrote its bundle INTO the memory store, and the next run of
    either scope then rmtree'd that store, fact files and all, because the
    directory now carried an okf_version index and passed the late
    non-bundle check. Measured: three fact files written after a first core
    run were gone after the second, exit 0 both times.

    This replaces test_core_scope_does_not_refuse_a_memory_dir_it_never_reads,
    which pinned the gate as deliberate. The gate mirrored this run's READ
    set, but the destination outlives this run, which is the same argument
    all_scanned_dirs makes for scopes and the same one the module docstring,
    the exit-code contract and the guide's own boldfaced rule already state
    unconditionally.
    """
    with pytest.raises(okf_export.BundleDestinationError) as excinfo:
        okf_export.write_bundle(bridge_root, memory_dir / "okfbundle", scope, memory_dir=memory_dir)
    assert "memory dir" in str(excinfo.value)
    assert list(memory_dir.glob("*.md")), "guard raised but the fact files are gone"


def test_main_guards_the_memory_dir_under_core_scope_too(
    okf_export, bridge_root, memory_dir, capsys
):
    """The CLI half: main resolved the memory dir under user scope only, so
    write_bundle could not guard what it was never told about.

    Reading it stays user-only; knowing where it is has to be unconditional.
    """
    rc = okf_export.main(
        [
            "--root", str(bridge_root),
            "--out", str(memory_dir / "core-bundle"),
            "--scope", "core",
            "--memory-dir", str(memory_dir),
        ]
    )
    assert rc == 1
    assert "memory" in capsys.readouterr().err
    assert list(memory_dir.glob("*.md")), "the fact store must be untouched"
    assert not (memory_dir / "core-bundle").exists()


def test_core_scope_still_exports_no_memory_concepts(okf_export, bridge_root, memory_dir, tmp_path):
    """GUARD on the clause above: guarding the memory dir is not reading it."""
    out = tmp_path / "core-no-memory"
    manifest = okf_export.write_bundle(bridge_root, out, "core", memory_dir=memory_dir)
    assert manifest["scope"] == "core"
    assert not (out / "memory").exists()


# --------------------------------------------------------------------------
# Index entries: the SLUG is source-derived too
# --------------------------------------------------------------------------

def _hostile_named_docs(root: Path) -> list[str]:
    """Write one doc per hostile FILENAME, skipping names this FS rejects."""
    frontmatter = '---\ntitle: "Plain title"\ndescription: "Plain description"\n---\n\n# H1\n\nbody\n'
    written: list[str] = []
    for name in ["Getting Started.md", "weird).md", "hash#tag.md", "sep line.md", "plain.md"]:
        try:
            _write(root / "docs" / name, frontmatter)
        except OSError:  # pragma: no cover - filesystem-dependent
            continue
        written.append(name)
    return written


def test_a_hostile_source_filename_cannot_break_its_own_index_entry(okf_export, tmp_path):
    """The slug is the source FILENAME, and it was interpolated raw.

    _md_inline escaped the title and the description; the link destination
    between them took whatever the file was called. A space makes the entry
    something CommonMark cannot read as a link at all; a `)` closes the
    destination early and points it at a file the bundle does not contain; a
    `#` turns the rest into a fragment; U+2028 splits the entry across two
    lines for any consumer using str.splitlines, which is the exact
    fabricated-entry failure _is_control exists to prevent.
    """
    root = tmp_path / "slug-hostile"
    names = _hostile_named_docs(root)
    if len(names) < 2:  # pragma: no cover - filesystem-dependent
        pytest.skip("this filesystem accepts none of the hostile filenames")
    out = tmp_path / "slug-hostile-bundle"
    okf_export.write_bundle(root, out, "core")

    concepts = sorted(p.name for p in (out / "doc").glob("*.md") if p.name != "index.md")
    entries = _index_entry_lines(out / "doc" / "index.md")
    assert len(entries) == len(concepts)
    for entry in entries:
        match = _INDEX_ENTRY_RE.match(entry)
        assert match, f"entry is not one clean bullet: {entry!r}"
        target = match.group("target")
        assert not set(target) & set(" <>"), f"destination is not a URL: {target!r}"
        assert not any(okf_export._is_control(ch) for ch in target)
        assert urllib.parse.unquote(target) in concepts, (
            f"index links {target!r}, which is not one of {concepts}"
        )


def test_raw_html_in_a_title_cannot_fabricate_a_list_item(okf_export, tmp_path):
    """`<` was the one markup character _md_inline left alone.

    CommonMark passes inline raw HTML straight through, so a title of
    `a</li><li><a href='...'>evil</a>` rendered as FOUR list items under a
    header claiming three, with an attacker-chosen href: the same outcome the
    escape set exists to prevent, reached without a line break or a bracket.
    An autolink `<https://evil.example>` puts a foreign href inside an entry
    the same way.
    """
    root = tmp_path / "html-title"
    _write(
        root / "docs" / "evil.md",
        "---\ntitle: \"a</li><li><a href='https://evil.example'>evil</a>\"\n"
        'description: "<https://evil.example>"\n---\n\n# H1\n\nbody\n',
    )
    out = tmp_path / "html-title-bundle"
    okf_export.write_bundle(root, out, "core")

    entries = _index_entry_lines(out / "doc" / "index.md")
    assert len(entries) == 1
    entry = entries[0]
    for pos, ch in enumerate(entry):
        if ch == "<":
            assert pos and entry[pos - 1] == "\\", f"unescaped `<` at {pos} in {entry!r}"
    # Escaped, never dropped: a reader still sees what the source said.
    assert "evil" in entry


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
