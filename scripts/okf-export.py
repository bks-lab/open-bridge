#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Export a Bridge instance as an Open Knowledge Format (OKF) v0.2 bundle.

A single, additive, dependency-free script that walks a Bridge instance's
knowledge surfaces (work/ STATUS.md + deliverables, docs/, rules/,
examples/) and emits a static OKF bundle — one markdown file per concept, a
per-type index.md, and a root index.md carrying the OKF version. No PyYAML
dependency: frontmatter parsing is hand-rolled. It keeps
scripts/extract-frontmatter.py's leading-comment-prolog convention (skips the
`# yaml-language-server: $schema=...` hint) and reads the same flat
`key: value` scalars scripts/gen-board.py's parse_status() reads, but it
deliberately diverges from that script on two points, because gen-board.py is
lenient where YAML is not:

  * quoting is resolved BEFORE inline comments, the order YAML itself uses, so
    a `#` inside a quoted scalar stays a literal character (`"... as PR #214"`
    keeps its issue number). On an UNQUOTED scalar a ` #` after a space or a
    tab still opens a comment and is still stripped. A quote closes a quoted
    scalar only where a quote may close one (nothing behind it, or a
    comment); anywhere else it was a character in the value, and the value
    degrades to the plain path rather than being cut there. A value that does
    NOT open with a quote is a plain scalar and keeps every character
    including its last, so `monitor is 12"` and `The so-called "bridge"`
    survive; only an orphaned outer PAIR is stripped off a quoted scalar
    whose closing quote could not be found.
  * the OPENING `---` fence is only a fence at COLUMN 0. The CLOSING one is
    judged by block-scalar state: an indented `---` inside an open block
    scalar is content (that is what a block-scalar continuation line looks
    like), and an indented `---` anywhere else still closes, because holding
    the closer to column 0 unconditionally eats the body of every file that
    merely indents its fence.

Measured rather than asserted: over 21,144 well-formed frontmatter lines
(every value spelled plain, double quoted and single quoted, each line
accepted by PyYAML), this parser now agrees with PyYAML on all of them.

Concept mapping (source -> OKF `type`):
  work/tasks/<slug>/STATUS.md          -> task
  work/streams/<slug>/STATUS.md        -> stream
  work/done/<month>/<slug>/STATUS.md   -> task
  */deliverables/*.md under work/      -> deliverable
  docs/**/*.md                         -> doc
  rules/**/*.md                        -> rule
  examples/**/*.md                     -> example
  <memory-dir>/*.md fact files         -> memory   (user scope only)

Memory facts are the instance's auto-memory files (frontmatter with a
`name:` key). The directory defaults to whatever `scripts/memory-location.py`
resolves for the instance root: a configured `autoMemoryDirectory` when one
exists, otherwise the harness's own legacy default,
`~/.claude/projects/<encoded-root>/memory` (override either way with
--memory-dir). Every concept carries a `resource:` field pointing at its
source (repo-relative path, or `memory/<filename>` for memory facts).

What v0.2 emits, and what it deliberately does not:

  generated.by   the actor that produced this BUNDLE DOCUMENT — by default
                 `okf-export/<EXPORTER_VERSION>`, overridable with
                 --generated-by. It never claims to be the author of the
                 underlying knowledge; `resource` is the provenance pointer.
  generated.at   the source's `last_updated`/`created`, normalized to an ISO
                 instant. A date that cannot be proven (partial, the literal
                 `YYYY-MM-DD` template placeholder, calendar-impossible) is
                 OMITTED rather than guessed.
  bridge_status  the source's Bridge workflow state, under a namespaced key.
                 It is NEVER written to OKF's own `status`: that field means
                 document readiness (draft|stable|deprecated) while a Bridge
                 status means work state (backlog|doing|review|done), and
                 `draft` is a homograph across the two. Absent `status`
                 already means `stable`, which is the true claim here.
  timestamp      REMOVED in v0.2 (superseded by generated.at). Not dual-emitted:
                 the spec's legacy fallback applies only when `generated` is
                 absent, which it never is.
  verified /     never emitted. Nothing in a Bridge instance is a verification
  sources /      event, a derivation edge, or an expiry instant, and all three
  stale_after    drive consumer behaviour (trust tiers, credibility
                 propagation, staleness gating) — so a fabricated value does
                 not read as noise, it reads as a false claim.

Empty optional fields are omitted, never written as "" or []: absence
carries meaning in OKF, so an empty value is a different claim from
"not recorded".

Every index file lists exactly as many entries as it has things to list, one
per line, and every entry's link points at that entry's own concept file. A
per-type index.md is the only generated file that puts source text into
markdown, and THREE of its values are source-derived: the title, the
description and the slug, which is a source FILENAME. The two text fields are
rendered as inline TEXT rather than markup (control characters, every line
break included, become spaces; `[`, `]`, backslash and `<` are escaped) and the
slug is percent-encoded into a relative URL. Otherwise a newline in any of
the three splits its own bullet and the overflow reads as an entry the count
above it does not admit; an unescaped closing bracket hands the parentheses
behind it to the source as a link destination; raw inline HTML opens list
items of its own; and a filename holding a space or a `)` leaves the entry
with no usable link at all. See _md_inline and _md_destination.

Wikilinks (kebab-case `[[slug]]` only — bash `[[ -f ... ]]` conditionals
never match) are resolved at export time against the bundle's own slug
index — never rewritten in the source repo. A resolved link becomes a
bundle-root-relative markdown link (`[slug](/<type>/<slug>.md)`, memory
concepts win cross-type slug collisions); an unresolved `[[slug]]` is left
completely untouched (OKF tolerates dangling references) and is reported
back in the manifest.

Scope controls which sources are walked:
  --scope user   everything (work/ + docs/ + rules/ + examples/ + memory)
                 — private, full-instance export.
  --scope core   docs/ + examples/ only — the public-safe subset for a demo
                 export (e.g. docs/ + examples/agency/). Run
                 scripts/no-scrub-leak.py over the output before publishing
                 a core-scope bundle.

--out must lie OUTSIDE every directory ANY scope walks, and outside the memory
dir, in EVERY scope. A bundle written inside a scanned directory is read back
in as source material on the next run, so the concept count climbs on every
run and the byte-identical re-run guarantee is false; the destination is
therefore refused before the walk and before anything is cleared. The scanned
set is derived from the same per-scope pattern list discover_sources globs
(_SCOPE_PATTERNS), so it can never drift out of step with what is actually
read: each pattern contributes its fixed prefix (which covers a directory that
does not exist yet) and the resolved result of running the walk's own glob
over the pattern's parent (which covers a directory reached through a symlink
at a literal segment after the globbed part). The guard takes the UNION over
the scopes rather than the running one, and the memory clause applies in every
scope for the same reason: the bundle stays on disk for the next run whichever
scope that is. Comparison is segment-wise on resolved paths in the
filesystem's own case-folded namespace, so a symlink, a `..` segment or a
different letter case cannot slip past it; on a case-SENSITIVE filesystem that
also refuses a pair that really is two directories, which the refusal says.
dist/okf-bundle is outside the scanned set in every scope.

Usage:
  python3 scripts/okf-export.py --out dist/okf-bundle
  python3 scripts/okf-export.py --root . --out dist/okf-bundle --scope core
  python3 scripts/okf-export.py --out dist/okf-bundle --generated-by human:alice

Exit codes:
  0   bundle written successfully
  1   --root does not exist / is not a directory, unsafe --out refused, a
      concept cannot be written, or --generated-by is not a valid OKF actor.
      An --out is unsafe when it exists and is not a directory, when it is
      --root or an ancestor of it, when it sits inside a scanned directory or
      contains one, when it overlaps the memory dir (in either scope), or when
      it is a non-empty directory that does not look like a prior bundle. A
      concept cannot be written when two of one type name a single file, or
      when a slug is longer than the filesystem's filename limit. Every one of
      those is checked before the destination is cleared, so a refused run
      leaves the sources and any previous bundle untouched.
  2   argparse usage error (e.g. unknown --scope; raised as SystemExit)
"""
from __future__ import annotations

import argparse
import importlib.util
import re
import shutil
import sys
import unicodedata
from datetime import date, datetime
from pathlib import Path

OKF_VERSION = "0.2"
# The exporter's OWN version, deliberately separate from the spec version so
# the two can never drift into each other. Hand-bumped: deriving it from
# `git describe` would make the output depend on clone state and break the
# byte-identical re-run guarantee.
EXPORTER_VERSION = "1.0"

# OKF section 7 actor convention: `<producer>/<version>` for an agent or tool,
# `human:<id>` for a person, `process:<id>` for an automated process. The value
# is written verbatim into every concept's `generated.by`, so it is validated
# rather than trusted: an unconstrained string is an unreadable provenance
# claim, and one containing a newline or a quote is malformed YAML. (Trust
# TIERS derive from `verified`, not from this field, so a wrong actor here
# misattributes provenance but cannot inflate a tier.)
# `\A`/`\Z`, never `^`/`$`: in Python `$` also matches before a trailing
# newline, so `--generated-by $'human:alice\n'` would pass a `$`-anchored gate
# and then split the rendered `generated:` flow mapping across two lines.
_ACTOR_RE = re.compile(r"\A(?:human|process):[A-Za-z0-9._-]+\Z|\A[A-Za-z0-9._-]+/[A-Za-z0-9._-]+\Z")
# Only a full calendar date. `date.fromisoformat` also accepts `20260702` and
# `2026-W27-1` on Python 3.11+, which must NOT be silently widened.
_BARE_DATE_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")
# An instant that already carries an explicit UTC offset, as OKF section 5
# requires. `T` only: a space separator is not the ISO 8601 form the spec names.
_OFFSET_DATETIME_RE = re.compile(
    r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})\Z"
)

# Kebab-case identifiers only: bash `[[ -f file ]]` conditionals inside code
# blocks must never match (and must never be rewritten or reported).
_WIKILINK_RE = re.compile(r"\[\[([a-z][a-z0-9-]*)\]\]")
# `[ \t]*`, never `\s*`: YAML separates `key:` from its value with spaces and
# tabs, and `\s` also matches U+00A0. A value that STARTS with a non-breaking
# space starts with content, and `\s*` ate that character before the value was
# ever resolved.
_FRONTMATTER_KV_RE = re.compile(r"^([A-Za-z_][\w]*):[ \t]*(.*)$")
_YAML_LS_PROLOG_RE = re.compile(r"^#\s*yaml-language-server:")
_BLOCK_SCALAR_RE = re.compile(r"^[|>][+-]?\d*$")
# One markdown line, terminator kept. `\r\n`, `\r` and `\n` and nothing else,
# which is where `str.splitlines` is wrong for this job: see _split_lines.
_LINE_RE = re.compile(r"[^\r\n]*(?:\r\n|\r|\n|\Z)")
# An inline comment on an UNQUOTED scalar. The `#` must open the line or follow
# a SPACE OR TAB, exactly as YAML requires: `value#nospace` is one plain scalar,
# and `key: # note` (the hash directly after the `key:` separator, so the value
# is empty) is a comment. Applied only after quoting has been resolved.
# `[ \t]`, never `\s`: `\s` also matches U+00A0, which YAML counts as content,
# so `before\xa0#after` was read as a comment and the value truncated to
# `before`.
_PLAIN_COMMENT_RE = re.compile(r"(?:\A|[ \t])#.*\Z")
# The two-character escapes read back inside a double-quoted scalar: every one
# `_yaml_quote` emits, plus YAML's `\/`. Anything else is left verbatim rather
# than guessed at, so `"\d+"` keeps its backslash. Note what that does NOT
# cover: `_yaml_quote` writes a control character as `\xNN`, which is not in
# this table and is read back as the four literal characters.
_DQ_ESCAPES = {"\\": "\\", '"': '"', "/": "/", "n": "\n", "r": "\r", "t": "\t"}
_RESERVED_SLUGS = frozenset({"index", "log"})
# Every containment refusal carries this. `_fs_path_identity` compares folded
# segments, so on a case-SENSITIVE filesystem the guard can refuse a pair that
# really is two directories, and a bare "it is inside X" would then be a plain
# falsehood to an operator looking at both of them in `ls`. Naming the
# comparison is what keeps the message true in that case.
_FOLD_NOTE = "path names compared case-insensitively and NFC-folded"
# The longest filename the common filesystems accept: ext4, APFS, NTFS and
# XFS all cap a single path component at 255 bytes (NTFS at 255 UTF-16 units,
# which this under-counts for astral characters rather than over-counts).
# Checked before anything is cleared, because the alternative is an OSError
# from write_text after the rmtree, which is where a half-written destination
# comes from.
_NAME_MAX_BYTES = 255


def _fs_identity(slug: str) -> str:
    """The form in which two slugs name the SAME FILE.

    A slug becomes a filename, so the namespace that has to stay unique is
    the filesystem's, not the byte string's. The macOS default (APFS) and
    NTFS compare filenames case-insensitively, and APFS additionally reads
    the NFC and NFD spellings of one character as the same name while
    preserving whichever bytes were written. So `readme` and `README`, and
    the two spellings of `café`, are one file there: two byte-distinct slugs
    pass a byte-equality check and the second write silently replaces the
    first (issue #152, the same symptom as an exact duplicate).

    NFC then case-fold covers both spellings, and is a pure function of its
    argument: no clock, no environment, no set iteration, so nothing about
    the exporter's determinism moves.

    Only the uniqueness KEY folds. This decides WHETHER two concepts collide
    and never what either of them is called: the emitted filename stays the
    concept's own slug, capitals, accents and normalization intact.

    The cost is deliberate. On a case-SENSITIVE filesystem `readme.md` and
    `README.md` really are two files, and folding bumps one of them anyway.
    That is the trade taken on purpose: WHICH concepts collide is then the
    same question everywhere, rather than one whose answer depends on the
    filesystem under the export.

    What that does NOT promise, because only the KEY folds: the emitted
    filename still follows the source filename's own spelling, so a concept
    whose source is named in NFD produces different bundle bytes from the
    same concept named in NFC. Normalization spelling is a per-tree property
    (APFS preserves whichever bytes were written; macOS git's default
    core.precomposeunicode hands them back as NFC), so two clones of one repo
    can still differ there. Folding closes the collision axis and nothing
    else.
    """
    return unicodedata.normalize("NFC", slug).casefold()


# The reserved names in the form _slug_is_taken compares, DERIVED rather than
# hand-written, so a future reserved name added in any spelling is folded too.
_RESERVED_IDENTITIES = frozenset(_fs_identity(name) for name in _RESERVED_SLUGS)

# A slug becomes a FILENAME, so it must be one path segment and nothing else.
# Repo-derived slugs come from the filesystem and are safe by construction, but
# a memory fact's `name:` is arbitrary frontmatter: `../../x` or `sub/dir` would
# make the exporter write outside --out, and it is supposed to only ever read
# the source tree. Leading dot excluded, which also rules out `.` and `..`.
_SAFE_SLUG_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]*\Z")
# Memory-dir housekeeping files that are never concepts (index + provenance).
_MEMORY_SKIP = frozenset({"MEMORY.md", "MEMORY-ARCHIVE.md", "PROVENANCE.md"})


def _closes_quoted_scalar(rest: str) -> bool:
    """True when ``rest`` is a legal tail for a quoted scalar.

    ``rest`` is everything after a candidate closing quote. Only two tails
    mean the quote really closed the value: nothing at all, or an inline
    comment. Anything else means the quote was a character inside the value
    and the real closing quote is elsewhere (or nowhere).

    Taking the first quote whatever follows it is how `'Alex's bridge'`
    resolved to `Alex`: the apostrophe looked like the closing quote, and
    the rest of the value was then discarded as the comment position. No
    whitespace is required in front of the `#`, because the value has already
    ended at the quote and there is nothing left for the hash to be part of
    (PyYAML reads `"a"#b` the same way). That is the opposite of the rule for
    a PLAIN scalar, where a `#` without leading whitespace is content
    (``_PLAIN_COMMENT_RE``).
    """
    rest = rest.strip()
    return not rest or rest.startswith("#")


def _resolve_scalar(raw: str) -> tuple[str, bool]:
    """Resolve one frontmatter value. Returns (value, was_quoted).

    Quoting is resolved FIRST and the inline comment second, which is the
    order YAML itself uses: a `#` opens a comment only outside a quoted
    scalar. Doing it the other way round truncates `"... as PR #214"` at the
    hash and then removes the orphaned opening quote, so the loss leaves no
    trace for the caller to notice.

    Three paths:

    * double-quoted: scan to the closing `"`, honouring backslash escapes so
      `\\"` does not close the scalar. The escapes read back are the ones in
      ``_DQ_ESCAPES``; any other backslash pair is left verbatim rather than
      guessed at, so `"\\d+"` reaches the caller as `\\d+`. That guarantee is
      narrower than it looks, and deliberately not sold as more: a hand-written
      `"C:\\path\\to"` resolves to `C:\\path`, a TAB, `o`, because `\\t` IS in
      the table. Values this exporter wrote survive a write/read round trip
      except for control characters, which ``_yaml_quote`` writes as `\\xNN`
      and this table does not read back.
    * single-quoted: scan to the closing `'`, collapsing a doubled `''` to one
      `'` (the only escape a YAML single-quoted scalar has).
    * plain, or a quote that never closes the scalar: strip a trailing inline
      comment, then apply the historic quote strip, which is CONDITIONAL on
      the value beginning with a quote. That condition is the whole of its
      business. A YAML plain scalar cannot open with `"` or `'` (both are
      indicators there), so a value that does not open with one was never a
      quoted scalar this parser tried and failed to unquote, and taking a
      character off its end is pure loss. `The so-called "bridge"`,
      `it is 'fine'` and `monitor is 12"` are ordinary prose that PyYAML
      round-trips unchanged, and the unconditional ``strip('"').strip("'")``
      this replaces ate the last character of each, silently, in the
      function issue #151 names.

    Whitespace is trimmed as YAML trims a plain scalar, spaces and tabs only
    (plus a trailing CR on a CRLF source). ``str.strip()`` is Unicode-aware
    and took U+00A0 with it, so a description pasted out of a browser lost
    the non-breaking space it ended on.

    A quote counts as closing only where ``_closes_quoted_scalar`` says one
    may (nothing but a comment behind it). Where it does not, the scan is
    abandoned and the value takes the plain path: `'Alex's bridge'` and
    `"He said "stop" once"` keep every character between their outer quotes,
    and only that outer pair (the delimiters the line was trying to use) is
    stripped. PyYAML rejects both lines outright, so there is no
    YAML-conformant answer to defer to here; the choice is between keeping a
    malformed value whole and silently dropping its tail, and this parser is
    tolerant on purpose.

    ``was_quoted`` is load-bearing rather than informational: with quotes
    resolved first, `title: "|"` would otherwise reach the block-scalar check
    as a bare `|` and swallow the following frontmatter lines as its body.
    """
    # Spaces, tabs and a trailing CR on a CRLF source. NOT bare `rstrip()`,
    # which is Unicode-aware and would take a trailing U+00A0 that YAML counts
    # as content.
    raw = raw.rstrip(" \t\r")

    if raw.startswith('"'):
        out: list[str] = []
        idx = 1
        while idx < len(raw):
            ch = raw[idx]
            if ch == "\\" and idx + 1 < len(raw):
                unescaped = _DQ_ESCAPES.get(raw[idx + 1])
                out.append(unescaped if unescaped is not None else raw[idx : idx + 2])
                idx += 2
                continue
            if ch == '"':
                if _closes_quoted_scalar(raw[idx + 1 :]):
                    return "".join(out), True
                break  # a quote mid-value: degrade to the plain path, whole
            out.append(ch)
            idx += 1
    elif raw.startswith("'"):
        out = []
        idx = 1
        while idx < len(raw):
            ch = raw[idx]
            if ch == "'":
                if idx + 1 < len(raw) and raw[idx + 1] == "'":
                    out.append("'")
                    idx += 2
                    continue
                if _closes_quoted_scalar(raw[idx + 1 :]):
                    return "".join(out), True
                break  # ditto: an apostrophe is not a closing quote
            out.append(ch)
            idx += 1

    value = _PLAIN_COMMENT_RE.sub("", raw, count=1).strip(" \t")
    if value[:1] in ('"', "'"):
        # Only here: this value opened with a quote, so it WAS a quoted scalar
        # whose closing quote could not be found. Stripping the orphaned
        # delimiters is the historic degrade. A value that opened with
        # anything else is a plain scalar, and its last character is content.
        value = value.strip('"').strip("'")
    return value, False


def _split_lines(text: str) -> list[str]:
    """Split on the line terminators a MARKDOWN FILE has, keeping the ends.

    ``str.splitlines`` breaks on eight more characters than that: U+000B,
    U+000C, U+001C-U+001E, U+0085 and U+2028/U+2029. A frontmatter scalar
    holding one of those was cut in half, the quoted scalar never closed on
    its own pseudo-line, and the value degraded to the plain path and lost
    its tail. PyYAML accepts U+2028 and U+2029 inside a double-quoted scalar
    and returns them verbatim, so that truncation was a disagreement with a
    real parser on well-formed input, and it made the exporter unable to read
    back a concept file it had written itself.

    ``"".join`` over the result reconstructs ``text`` exactly, which is what
    lets the body be sliced out of it untouched.
    """
    lines = _LINE_RE.findall(text)
    if lines and lines[-1] == "":
        lines.pop()  # the zero-width match `findall` leaves at end of string
    return lines


def _block_scalar_indicator(raw_value: str) -> str | None:
    """The block-scalar indicator ``raw_value`` opens with, or None.

    The ONE definition of "this line opens a block scalar", read by both
    passes below. The fence scan needs it to know whether an indented `---`
    is content or the closing fence, and the key parser needs it to know
    whether to fold the following lines. Two answers to one question is how
    a scan and a parse drift apart over the same file.

    A QUOTED value is a string and never an indicator: `title: "|"` is the
    one-character string, not the head of a block.
    """
    value, was_quoted = _resolve_scalar(raw_value)
    if not was_quoted and _BLOCK_SCALAR_RE.match(value):
        return value
    return None


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split ``text`` into (frontmatter dict, body). Hand-rolled, no PyYAML.

    Reads the same flat `key: value` scalars as scripts/gen-board.py's
    parse_status() and keeps scripts/extract-frontmatter.py's
    leading-comment-prolog skip (so a `# yaml-language-server: $schema=...`
    hint above the `---` fence never confuses detection), with two deliberate
    divergences from gen-board.py: quoting is resolved before inline comments
    (see ``_resolve_scalar``), and the OPENING fence counts only at column 0.
    A file with no frontmatter block returns ({}, text) with the body left
    completely untouched.

    The CLOSING fence is judged by block-scalar state rather than by column
    alone. An indented `---` inside an open block scalar is content (issue
    #151: `line.strip() == "---"` closed the block early, lost the remaining
    keys and leaked four frontmatter lines into the body); an indented `---`
    anywhere else still closes, because holding the closer to column 0
    unconditionally costs the body of every file that merely indents its
    fence. Such a file has no block scalar open at all, and the scan then
    either reads on to the next column-0 `---` and swallows the text between
    as frontmatter, or finds no fence and reports the whole file as body with
    no keys. Both are silent losses of exactly the shape #151 is about, so
    the state the two cases differ by is the state this scan tracks.

    A leading UTF-8 BOM is dropped before anything else. ``str.rstrip`` does
    not remove U+FEFF, so `\\ufeff---` never equalled `---` and a
    BOM-prefixed source was read as having no frontmatter at all: every key
    gone, the title fallen back to the body H1, and the raw frontmatter text
    emitted into the concept body.
    """
    if text.startswith("﻿"):
        text = text[1:]

    lines = _split_lines(text)
    in_block = False
    in_block_scalar = False
    fm_start_idx: int | None = None
    fence_close_idx: int | None = None

    for idx, line in enumerate(lines):
        if not in_block:
            if _YAML_LS_PROLOG_RE.match(line.lstrip()):
                continue
            # `rstrip`, never `strip`: the OPENING fence lives at column 0.
            # Trailing whitespace (and a CRLF `\r`) is tolerated, leading
            # indentation is not, so an indented leading `---` is content (an
            # indented code block) and the file has no frontmatter.
            if line.rstrip() == "---":
                in_block = True
                fm_start_idx = idx + 1
                continue
            if line.strip() == "":
                continue
            # first non-empty, non-comment, non-fence line -> no frontmatter block
            return {}, text
        else:
            # A block-scalar continuation line is blank or indented, by
            # definition. While one is open those lines are content, `---`
            # included; the first line that is neither ends the block scalar.
            if in_block_scalar and (line.strip() == "" or line.startswith((" ", "\t"))):
                continue
            in_block_scalar = False
            if line.strip() == "---":
                fence_close_idx = idx
                break
            match = _FRONTMATTER_KV_RE.match(line.rstrip("\r\n"))
            in_block_scalar = match is not None and (
                _block_scalar_indicator(match.group(2)) is not None
            )

    if fm_start_idx is None or fence_close_idx is None:
        return {}, text

    fm: dict[str, str] = {}
    fm_lines = lines[fm_start_idx:fence_close_idx]
    idx2 = 0
    while idx2 < len(fm_lines):
        line = fm_lines[idx2]
        stripped = line.rstrip("\n")
        if not stripped.strip() or stripped.lstrip().startswith("#"):
            idx2 += 1
            continue
        m = _FRONTMATTER_KV_RE.match(stripped)
        if not m:
            idx2 += 1
            continue
        key, raw = m.group(1), m.group(2)
        indicator = _block_scalar_indicator(raw)
        if indicator is not None:
            # YAML block scalar (`>-`/`|`/...) — fold/preserve the indented
            # continuation lines instead of shipping the bare indicator as
            # the literal value.
            folded = indicator.startswith(">")
            idx2 += 1
            block_lines: list[str] = []
            while idx2 < len(fm_lines) and (
                fm_lines[idx2].strip() == "" or fm_lines[idx2].startswith((" ", "\t"))
            ):
                block_line = fm_lines[idx2].rstrip("\n").strip()
                if block_line:
                    block_lines.append(block_line)
                idx2 += 1
            val = " ".join(block_lines) if folded else "\n".join(block_lines)
        else:
            val, _ = _resolve_scalar(raw)
            idx2 += 1
        fm[key] = val

    body = "".join(lines[fence_close_idx + 1 :])
    return fm, body


def concept_slug(path: Path) -> str:
    """`STATUS.md` -> parent directory name; anything else -> the file stem."""
    if path.name == "STATUS.md":
        return path.parent.name
    return path.stem


def derive_title(frontmatter: dict, body: str, fallback: str) -> str:
    """frontmatter["title"] -> first `# ` H1 line in body -> fallback."""
    title = frontmatter.get("title")
    if title:
        return title
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def derive_description(frontmatter: dict, body: str) -> str:
    """frontmatter["description"] -> ["summary"] -> ["headline"] -> "" (never from body)."""
    del body  # part of the documented signature; description never derives from body
    for key in ("description", "summary", "headline"):
        value = frontmatter.get(key)
        if value:
            return value
    return ""


def resolve_wikilinks(text: str, slug_to_relpath: dict) -> tuple[str, list[str]]:
    """Replace every kebab-case `[[slug]]`: resolved -> markdown link,
    unresolved -> left completely untouched (OKF tolerates dangling
    references; rewriting them would corrupt content such as bash
    conditionals or deliberate wiki syntax).

    Returns (new_text, unresolved_slugs) — unresolved slugs are reported in
    the order they were encountered (duplicates included, callers dedupe).
    """
    unresolved: list[str] = []

    def _replace(match: re.Match) -> str:
        slug = match.group(1)
        relpath = slug_to_relpath.get(slug)
        if relpath is not None:
            return f"[{slug}]({relpath})"
        unresolved.append(slug)
        return match.group(0)

    new_text = _WIKILINK_RE.sub(_replace, text)
    return new_text, unresolved


# The ONE list of source patterns per scope, read by BOTH consumers:
# discover_sources (which globs them) and scanned_dirs (which derives from
# them the directories write_bundle refuses to write a bundle into). A second
# literal copy in the guard would drift silently the day someone adds a
# pattern to only one of the two, and the walk would resume eating its own
# output (issue #153). Add a pattern here and both behaviours follow.
_DOC_TIER_PREFIXES = ("docs/user/", "docs/org/", "docs/personal/")
_SCOPE_PATTERNS: dict[str, tuple[str, ...]] = {
    "core": (
        "docs/**/*.md",
        "examples/**/*.md",
    ),
    "user": (
        "work/tasks/*/STATUS.md",
        "work/streams/*/STATUS.md",
        "work/done/*/*/STATUS.md",
        "work/**/deliverables/*.md",
        "docs/**/*.md",
        "rules/**/*.md",
        "examples/**/*.md",
    ),
}

# The glob metacharacters Path.glob honours. A segment containing any of them
# is not a fixed directory name, so prefix derivation stops there.
_GLOB_CHARS = frozenset("*?[")


def patterns_for(scope: str) -> tuple[str, ...]:
    """The source glob patterns for ``scope`` ("user" or "core")."""
    try:
        return _SCOPE_PATTERNS[scope]
    except KeyError:
        expected = " or ".join(repr(name) for name in sorted(_SCOPE_PATTERNS))
        raise ValueError(f"unknown scope: {scope!r} (expected {expected})") from None


def _pattern_prefix(pattern: str) -> str:
    """The fixed leading path of a glob pattern, up to its first globbed segment.

    ``docs/**/*.md`` -> ``docs``; ``work/tasks/*/STATUS.md`` -> ``work/tasks``;
    ``work/**/deliverables/*.md`` -> ``work``. Segment-wise by construction,
    never a string prefix, so a sibling named ``docs-bundle`` is not mistaken
    for something inside ``docs``.

    A pattern whose very first segment is globbed has NO fixed prefix and
    yields "". The walk then reads the whole tree, which scanned_dirs turns
    into the root itself rather than dropping the pattern and under-guarding.
    """
    fixed: list[str] = []
    for segment in pattern.split("/"):
        if _GLOB_CHARS & set(segment):
            break
        fixed.append(segment)
    return "/".join(fixed)


def _pattern_parent(pattern: str) -> str:
    """A glob for the DIRECTORIES ``pattern`` reads its files out of.

    ``docs/**/*.md`` -> ``docs/**``; ``work/**/deliverables/*.md`` ->
    ``work/**/deliverables``; ``*.md`` -> "" (the root itself, no glob to run).
    """
    head, sep, _ = pattern.rpartition("/")
    return head if sep else ""


def scanned_dirs(root: Path, scope: str) -> list[Path]:
    """The resolved directories ``discover_sources(root, scope)`` reads under.

    Derived from ``patterns_for(scope)``, never from a hand-kept second list,
    and in two layers because one is not enough.

    The FIXED PREFIX (``_pattern_prefix``) covers directories that do not
    exist yet: they are scanned the moment they appear, and a bundle sitting
    there would be read back in on the next run. The JOINED path is what
    resolves, not just ``root``. Resolving only the root and appending the
    prefix compares the scanned directory on its LINK path while the
    destination is compared on its real one, so a repo whose ``docs/`` points
    elsewhere could never match however ``--out`` was spelled.

    The GLOBBED PART is why that alone still let issue #153 through.
    ``Path.glob`` follows a symlink at every LITERAL segment after the
    globbed one, so ``work/**/deliverables/*.md`` reads through a directory
    named ``deliverables`` wherever it really points, and the fixed prefix of
    that pattern is only ``work``. Running the walk's own glob over the
    pattern's parent (``work/**/deliverables``) and resolving each match is
    what puts those targets in front of the guard: the read set is defined by
    the glob engine, so the guard has to ask the glob engine. A dangling link
    counts too (``resolve`` is non-strict), so the very first run is refused
    rather than the second.

    Set-built and sorted, and every element is a resolved path: nothing here
    can put filesystem enumeration order into the exporter's output.
    """
    root = Path(root).resolve()
    found: set[Path] = set()
    for pattern in patterns_for(scope):
        prefix = _pattern_prefix(pattern)
        found.add(((root / prefix) if prefix else root).resolve())
        parent = _pattern_parent(pattern)
        if parent:
            for match in root.glob(parent):
                if match.is_dir() or match.is_symlink():
                    found.add(match.resolve())
    return sorted(found)


def all_scanned_dirs(root: Path) -> list[tuple[Path, tuple[str, ...]]]:
    """Every directory ANY scope walks, each with the scopes that walk it.

    This, and not ``scanned_dirs(root, scope)`` alone, is what the
    destination guard reads. The scope is chosen per invocation, but the
    bundle it leaves behind stays on disk for every later run: core scope
    does not walk ``rules/``, so a core bundle lands there happily, and the
    next user-scope run globs ``rules/**/*.md`` and ingests it. Guarding only
    the scope in front of you makes the corruption a function of which scope
    ran last, which is not a property anyone can reason about.

    Sorted by path, with the scope names in sorted order, so the refusal a
    given tree produces is always the same one.
    """
    by_dir: dict[Path, list[str]] = {}
    for scope in sorted(_SCOPE_PATTERNS):
        for scanned in scanned_dirs(root, scope):
            by_dir.setdefault(scanned, []).append(scope)
    return [(scanned, tuple(by_dir[scanned])) for scanned in sorted(by_dir)]


def _fs_path_identity(path: Path) -> tuple[str, ...]:
    """The form in which two RESOLVED paths name the same directory.

    Segment-wise, and each segment folded exactly as ``_fs_identity`` folds a
    slug, for the same reason: the filesystems this runs on compare path
    segments case-insensitively (the macOS default and NTFS), and APFS reads
    the NFC and NFD spellings of one character as one name. ``d/DOCS`` and
    ``d/docs`` are ONE directory there, so a byte-equal comparison of the two
    spellings sees two unrelated paths and waves the bundle into the very
    directory the walk reads.

    Segment-wise rather than over the whole string, so the sibling
    ``docs-bundle`` stays outside ``docs``. Folding rather than comparing
    inodes, because the guard has to judge directories that DO NOT EXIST YET
    (``scanned_dirs`` returns those on purpose, and a fresh instance is
    exactly the tree where ``docs/`` has not been created), which no
    stat-based identity can do. Pure, like ``_fs_identity``: nothing here
    moves the exporter's determinism.

    On a case-SENSITIVE filesystem this refuses a pair that really is two
    directories. That is the deliberate trade, the same one ``_fs_identity``
    takes for slugs: one notion of filesystem identity, so one tree behaves
    the same way everywhere, and the cost of the extra refusal is that the
    operator names another destination.
    """
    return tuple(_fs_identity(part) for part in Path(path).parts)


def _contains(ancestor: Path, descendant: Path) -> bool:
    """True when resolved ``descendant`` IS ``ancestor`` or lies beneath it.

    The filesystem-identity replacement for ``Path.is_relative_to``, which
    compares path segments byte for byte.
    """
    outer = _fs_path_identity(ancestor)
    inner = _fs_path_identity(descendant)
    return inner[: len(outer)] == outer


def discover_sources(root: Path, scope: str) -> list[Path]:
    """Walk ``root`` for OKF source files per ``scope`` ("user" or "core")."""
    root = Path(root)
    found: set[Path] = set()
    for pattern in patterns_for(scope):
        found.update(p for p in root.glob(pattern) if p.is_file())
    if scope == "core":
        # The core scope is the privacy boundary, so it keeps only what the
        # scope router itself calls core: never docs/user/, docs/org/ or
        # docs/personal/ (docs/kernel.md), and never a doc a fork has not moved
        # yet whose `scope:` line keeps it local.
        found = {p for p in found
                 if not p.relative_to(root).as_posix().startswith(_DOC_TIER_PREFIXES)
                 and not (p.relative_to(root).as_posix().startswith("docs/")
                          and _router_tier(root, p.relative_to(root).as_posix()) != "core")}
    return sorted(found, key=lambda p: p.relative_to(root).as_posix())


_ROUTER = None


def _router_tier(root: Path, rel: str) -> str:
    """The tier scripts/categorize-commits.py gives `rel` inside `root`."""
    global _ROUTER
    if _ROUTER is None:
        spec = importlib.util.spec_from_file_location(
            "categorize_commits_okf", Path(__file__).resolve().parent / "categorize-commits.py")
        if spec is None or spec.loader is None:
            raise RuntimeError("scripts/categorize-commits.py not found beside okf-export.py")
        _ROUTER = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_ROUTER)
    import os
    here = os.getcwd()
    try:
        os.chdir(root)
        return _ROUTER.classify_file(rel)
    finally:
        os.chdir(here)


def concept_type_for(path: Path, root: Path) -> str:
    """Map a discovered source path to its OKF concept type."""
    rel = Path(path).relative_to(root)
    parts = rel.parts

    if parts[0] == "work":
        if "deliverables" in parts:
            return "deliverable"
        if path.name == "STATUS.md" and len(parts) >= 2:
            if parts[1] == "tasks":
                return "task"
            if parts[1] == "streams":
                return "stream"
            if parts[1] == "done":
                return "task"
    elif parts[0] == "docs":
        return "doc"
    elif parts[0] == "rules":
        return "rule"
    elif parts[0] == "examples":
        return "example"

    raise ValueError(f"cannot determine OKF concept type for {rel}")


def default_generated_by() -> str:
    """The actor this exporter names as the producer of a bundle document.

    It names the TRANSFORMATION, never the author of the underlying
    knowledge: the exporter produced this OKF file, it did not write the
    Bridge document behind it. `resource` is the real provenance pointer.
    Deriving an author from `git log`/`git config`/`$USER` is refused on
    three counts: a committer is not a knowledge author, it would inject a
    real identity into a `--scope core` bundle, and it would make output
    depend on clone state.
    """
    return f"okf-export/{EXPORTER_VERSION}"


def normalize_timestamp(value: str) -> str | None:
    """Coerce a source date to an OKF instant, or return None if unprovable.

    OKF section 5 requires every timestamp-valued key to be an ISO 8601
    datetime with an explicit UTC offset, but Bridge sources carry bare
    dates (``last_updated: 2026-07-02``). Exactly two shapes are accepted:

    * a full calendar date -> widened to ``<date>T00:00:00Z``. Midnight is
      the EARLIEST instant consistent with the stated date, so no consumer
      ever reads the content as fresher than the evidence supports.
    * a datetime that already carries an offset -> passed through verbatim.

    Everything else returns None and the caller omits ``generated.at``
    entirely: a partial date (``2026-03``) would require inventing a day,
    ``work/templates/STATUS.md`` seeds new tasks with the literal
    ``YYYY-MM-DD`` placeholder, and section 5.2 does not mark ``at``
    required. Pure: reads only its argument, never the clock.

    Both branches PROVE the value rather than merely shape-matching it: the
    regexes are all ``\\d{2}`` groups, so month 13, day-31-in-June and hour 25
    match the pattern. An impossible instant, emitted unquoted, is frontmatter
    no YAML parser can load, which breaks conformance for the whole bundle.
    """
    value = (value or "").strip()
    if _BARE_DATE_RE.match(value):
        try:
            date.fromisoformat(value)
        except ValueError:
            return None  # calendar-impossible, e.g. 2026-02-30
        return f"{value}T00:00:00Z"
    if _OFFSET_DATETIME_RE.match(value):
        # `Z` is only accepted by fromisoformat from 3.11; normalize for the
        # probe so the check does not depend on the interpreter version.
        probe = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            datetime.fromisoformat(probe)
        except ValueError:
            return None  # e.g. 2026-06-31T09:00:00Z, 2026-07-02T25:00:00Z
        return value
    return None


def build_concept(path: Path, root: Path) -> dict:
    """Read ``path`` and build its OKF concept dict (body left un-resolved)."""
    text = Path(path).read_text(encoding="utf-8")
    fm, body = parse_frontmatter(text)
    slug = concept_slug(path)
    okf_type = concept_type_for(path, root)
    title = derive_title(fm, body, fallback=slug)
    description = derive_description(fm, body)
    generated_at = normalize_timestamp(fm.get("last_updated") or fm.get("created") or "")
    tags = [value for value in (fm.get("status"), fm.get("context")) if value]
    return {
        "slug": slug,
        "okf_type": okf_type,
        "title": title,
        "description": description,
        "resource": Path(path).relative_to(root).as_posix(),
        "generated_at": generated_at,
        # A Bridge workflow state, NEVER OKF's `status`. The two vocabularies
        # are orthogonal and `draft` is a homograph across them: see the
        # module docstring.
        "bridge_status": fm.get("status") or None,
        "tags": tags,
        "body": body,
    }


def default_memory_dir(root: Path, home: Path | None = None) -> Path:
    """Resolve the instance's auto-memory directory for ``root``.

    Delegates to ``scripts/memory-location.py``'s ``resolve_memory_dir()``:
    a configured ``autoMemoryDirectory`` (``root/.claude/settings.local.json``,
    then ``root/.claude/settings.json``, then ``home/.claude/settings.json``)
    wins; with nothing configured, the result is the same legacy derivation
    this function used to compute directly, ``~/.claude/projects/<encoded>/
    memory`` where ``<encoded>`` is the absolute project path with every
    ``/`` replaced by ``-`` (the leading slash becomes a leading dash).

    Loaded by file path (``importlib``) because the sibling script's filename
    has a dash and cannot be a normal import. If that load fails for any
    reason (missing file, syntax error), falls back to the legacy derivation
    itself, with a stderr notice, rather than raising. For a plain checkout
    with nothing configured that matches the resolver; the fallback ignores
    the settings files and does not map a linked worktree to its main checkout.

    ``home`` overrides ``Path.home()``, for hermetic testing.
    """
    home = Path(home) if home is not None else Path.home()
    encoded = str(Path(root).resolve()).replace("/", "-")
    legacy = home / ".claude" / "projects" / encoded / "memory"

    resolver_path = Path(__file__).resolve().parent / "memory-location.py"
    try:
        spec = importlib.util.spec_from_file_location("_bridge_memory_location", resolver_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load {resolver_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as exc:  # pragma: no cover - defensive
        sys.stderr.write(
            f"NOTICE: could not load {resolver_path} ({exc}); falling back to "
            "the legacy memory-directory derivation\n"
        )
        return legacy

    memory_dir, _source, _warnings = module.resolve_memory_dir(root, home)
    return memory_dir


def discover_memory(memory_dir: Path) -> list[Path]:
    """Memory fact files: every ``*.md`` with a ``name:`` frontmatter key,
    excluding index/provenance housekeeping files (``MEMORY.md`` etc.)."""
    memory_dir = Path(memory_dir)
    if not memory_dir.is_dir():
        return []
    found: list[Path] = []
    for path in sorted(memory_dir.glob("*.md"), key=lambda p: p.name):
        if path.name in _MEMORY_SKIP or path.name.startswith("_"):
            continue
        fm, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
        if fm.get("name"):
            found.append(path)
    return found


def build_memory_concept(path: Path) -> dict:
    """Build a ``memory``-type concept from an auto-memory fact file.

    Slug = the frontmatter ``name:`` (already kebab-case by convention),
    falling back to the filename stem with its ``<type>_`` prefix stripped
    and underscores dashed. Memory facts carry no top-level date, so
    ``generated_at`` stays None and the key is omitted rather than guessed;
    ``resource`` points into the (out-of-repo) memory dir.
    """
    text = Path(path).read_text(encoding="utf-8")
    fm, body = parse_frontmatter(text)
    # The filename-derived slug is safe by construction (a directory entry can
    # hold no separator), so it doubles as the fallback when `name:` is absent
    # OR is not a usable single path segment.
    fallback = path.stem.split("_", 1)[-1].replace("_", "-")
    candidate = fm.get("name") or fallback
    slug = candidate if _SAFE_SLUG_RE.match(candidate) else fallback
    return {
        "slug": slug,
        "okf_type": "memory",
        "title": derive_title(fm, body, fallback=slug),
        "description": derive_description(fm, body),
        "resource": f"memory/{path.name}",
        "generated_at": None,
        "bridge_status": None,
        "tags": [],
        "body": body,
    }


_YAML_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"}


def _yaml_quote(value: str) -> str:
    """Render a scalar as a double-quoted YAML string, safe on ONE line.

    A double-quoted scalar is the only flow form that can carry an arbitrary
    string, but only if everything that would end the scalar or the line is
    escaped. Escaping just backslash and quote is not enough: a raw newline
    folds the value into a space, or — when the continuation line happens to
    start with ``---`` — terminates the frontmatter block outright, and a raw
    control character makes the whole block unreadable to a real YAML parser.
    Source frontmatter reaches this function verbatim (a ``title: |`` block
    scalar arrives multi-line), so it must survive anything a source file
    can hold.
    """
    out: list[str] = []
    for ch in value:
        escaped = _YAML_ESCAPES.get(ch)
        if escaped is not None:
            out.append(escaped)
        elif ch < "\x20" or ch == "\x7f" or "\x80" <= ch <= "\x9f":
            out.append(f"\\x{ord(ch):02x}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def _render_concept(concept: dict, generated_by: str | None = None) -> str:
    """Render one OKF v0.2 concept file.

    An empty optional field is OMITTED rather than written as ``""``/``[]``:
    OKF section 5 states that absence carries meaning, so an empty string is
    a different (and false) claim from "not recorded". Only ``type`` is
    always required (section 4.1).
    """
    generated_by = generated_by or default_generated_by()
    lines = [
        "---",
        f"type: {concept['okf_type']}",
        f"title: {_yaml_quote(concept['title'])}",
    ]
    if concept["description"]:
        lines.append(f"description: {_yaml_quote(concept['description'])}")
    lines.append(f"resource: {_yaml_quote(concept['resource'])}")

    # `by` is the only REQUIRED key inside `generated` (section 5.2); `at` is
    # written only when the source date could be proven (see normalize_timestamp).
    generated = f"{{ by: {generated_by}"
    if concept.get("generated_at"):
        generated += f", at: {concept['generated_at']}"
    lines.append(f"generated: {generated} }}")

    if concept.get("bridge_status"):
        lines.append(f"bridge_status: {_yaml_quote(concept['bridge_status'])}")
    if concept["tags"]:
        # Every tag is quoted individually: an unquoted flow sequence splits a
        # tag on its own comma and is broken outright by a `]` inside a value.
        tags = ", ".join(_yaml_quote(tag) for tag in concept["tags"])
        lines.append(f"tags: [{tags}]")
    lines.extend(["---", ""])
    return "\n".join(lines) + concept["body"]


# What a markdown index entry escapes so a source-derived scalar cannot leave
# its own position. `\` belongs in the set for the same reason the brackets do,
# one character further back: escape only `[` and `]`, and a title reading
# `x\](evil)` is emitted as `x\\](evil)`, where the `\\` is a literal backslash
# and the `]` behind it is bare again, closing the link text and handing
# `(evil)` to the source as the destination. Measured, not reasoned.
#
# `<` is in the set because CommonMark passes inline raw HTML through
# untouched: a title of `a</li><li><a href='...'>evil</a>` rendered as four
# list items under a header claiming three, the extra ones carrying an
# attacker-chosen href, which is the same outcome as the newline route and
# needs neither a line break nor a bracket. An autolink `<https://...>` puts a
# foreign href inside an entry the same way. CommonMark renders `\<` as a bare
# `<`, so a legitimate one still reads as itself.
_MD_INLINE_ESCAPES = {"\\": "\\\\", "[": "\\[", "]": "\\]", "<": "\\<"}
# What a link DESTINATION cannot carry raw, and why each one is here:
#   space, `(`, `)`   CommonMark ends an unbracketed destination at an ASCII
#                     space and requires its parentheses to be balanced, so
#                     `Getting Started.md` is not read as a link at all and
#                     `weird).md` points at `weird`, which is not in the bundle
#   `<`, `>`          a destination may not carry either unescaped
#   `#`, `?`          a URL reader takes these as a fragment or a query, so the
#                     link resolves to a different file than the one on disk
#   `%`               so the encoding below is reversible
#   `\`, backtick,
#   `[`, `]`, `{`,
#   `}`, `|`, `^`,
#   `"`               excluded from a URI by RFC 3986, so a consumer that
#                     parses the destination as one may reject them
# Everything else, accents and capitals included, stays byte-for-byte the
# concept's own filename.
_MD_DESTINATION_UNSAFE = frozenset(' "#%()<>?[\\]^`{|}')


def _is_control(ch: str) -> bool:
    """True for a character that must not reach a ONE-line markdown entry.

    The C0 and C1 control ranges (every ASCII line break included), which is
    the range ``_yaml_quote`` escapes, reached from the other side: a
    frontmatter scalar escapes them to stay on one line, an index entry
    replaces them to stay on one line. Widened by U+2028/U+2029: CommonMark
    does not count those as line endings, but Unicode calls them line
    separators and Python's own ``str.splitlines`` breaks on them, so a
    consumer reading the index line by line would see an entry the count above
    it does not admit.
    """
    return ch < "\x20" or ch == "\x7f" or "\x80" <= ch <= "\x9f" or ch in "\u2028\u2029"


def _md_inline(value: str) -> str:
    """Render a source-derived scalar as markdown inline TEXT for an index entry.

    An index entry is `* [title](slug.md) - description` on ONE line, and both
    interpolated fields arrive verbatim from source frontmatter. Two things
    let a field leave its own position:

    * a line break ends the entry, so everything after it reads as another
      entry. The header then states one concept while the list shows two, and
      the fabricated one carries whatever link it likes. A `title: |` block
      scalar arrives multi-line from the source itself; a single-line
      `description: "a\\n* [x](...)"` gets there too, now that a double-quoted
      scalar's escapes are read back. Every control character becomes a space
      and the result is stripped, so a field spans exactly one line and adds
      no trailing whitespace of its own.
    * an unescaped `]` closes the link text early and lets the `(...)` behind
      it become a destination the source chose, which needs no line break at
      all. `[`, `]` and `\\` are escaped; CommonMark renders a
      backslash-escaped punctuation mark as the bare character, so a
      legitimate bracket still reads as a bracket. `(` and `)` need no escape:
      a destination can only follow an unescaped `]`, and after the escape
      above the only unescaped `]` on the line is the one this renderer
      writes, whose destination is the concept's own file.
    * raw inline HTML is passed straight through by CommonMark, so
      `a</li><li><a href='...'>evil</a>` in a title closes the entry's own
      list item and opens further ones with a link the source chose. `<` is
      escaped for that, which closes the autolink route (`<https://...>`) with
      it.

    That is the whole guarantee: one entry per concept, whose link is that
    concept's own file. It covers only what this function is given. The link
    DESTINATION between the two fields is source-derived as well (the slug is
    a source filename), and it is ``_md_destination``, not this, that keeps it
    inside the bundle. Other inline markdown still renders, exactly as it does
    in the concept bodies, which are markdown by design: emphasis around a
    `*`, a code span between backticks, an HTML entity such as `&auml;`. None
    of those can move an entry's link or fabricate a second entry. The concept
    FILES never needed any of this: every source-derived value there goes
    through ``_yaml_quote``.
    """
    one_line = "".join(" " if _is_control(ch) else ch for ch in value).strip()
    return "".join(_MD_INLINE_ESCAPES.get(ch, ch) for ch in one_line)


def _md_destination(slug: str) -> str:
    """Render a concept slug as an index entry's link destination.

    The slug is the source FILENAME, so it is every bit as source-derived as
    the title beside it, and it was interpolated raw. Three everyday spellings
    broke the entry that carries it: `Getting Started.md` produced
    `* [T](Getting Started.md)`, which CommonMark does not read as a link at
    all, so that concept had no link in its index; `weird).md` closed the
    destination early and pointed the link at `weird`, which is not in the
    bundle; and a slug holding U+2028 split its own bullet across two lines
    for any consumer using ``str.splitlines``, which is the fabricated-entry
    failure ``_is_control`` exists to prevent, arriving through the one field
    that did not go through it.

    Percent-encoding rather than an angle-bracket destination, because the
    result is then a relative URL in the ordinary sense and OKF section 8 asks
    for a relative URL. Only the characters in ``_MD_DESTINATION_UNSAFE`` and
    the control range are touched, so an ordinary slug (accents, capitals and
    all) reaches the entry byte for byte as the file is named on disk.
    """
    out: list[str] = []
    for ch in slug:
        if _is_control(ch) or ch in _MD_DESTINATION_UNSAFE:
            out.extend(f"%{byte:02X}" for byte in ch.encode("utf-8"))
        else:
            out.append(ch)
    return "".join(out)


def _render_type_index(okf_type: str, concepts: list[dict]) -> str:
    """Render a per-type ``index.md`` — a reserved filename, so it carries NO
    frontmatter block (the root ``index.md`` is the sole exception, carrying
    ``okf_version``)."""
    lines = [
        f"# {okf_type.capitalize()} Index",
        "",
        f"{len(concepts)} concept(s).",
        "",
    ]
    # `* [Title](relative-url) - short description` is the form OKF section 8
    # shows for an index entry. All THREE interpolated values are
    # source-derived (the title, the description, and the slug, which is a
    # source filename), so all three are rendered rather than pasted: the two
    # text fields through _md_inline, the destination through _md_destination.
    # The count above is a claim about the list below, and any one of the three
    # left raw falsifies it.
    for concept in sorted(concepts, key=lambda c: c["slug"]):
        title = _md_inline(concept["title"])
        description = _md_inline(concept["description"])
        suffix = f" - {description}" if description else ""
        lines.append(f"* [{title}]({_md_destination(concept['slug'])}.md){suffix}")
    lines.append("")
    return "\n".join(lines)


def _render_root_index(scope: str, concepts: list[dict], types: list[str]) -> str:
    """Render the bundle-root ``index.md``.

    ``okf_version`` is the ONE key OKF permits in an index file's
    frontmatter (sections 8 + 12), so scope and concept count are stated in
    the body prose instead of the block. ``_is_bundle_dir`` keys off
    ``okf_version`` alone, so the destructive ``--out`` guard still
    recognises bundles written by earlier versions.

    Nothing SOURCE-DERIVED is interpolated here, which is why no value on this
    page goes through ``_md_inline``: ``scope`` is one of two literals
    argparse accepts, and every entry is a concept TYPE, drawn from what
    ``concept_type_for`` returns (deliverable, doc, example, rule, stream,
    task) plus ``memory``, which ``build_memory_concept`` sets directly and
    which therefore does not appear in that function. Both halves are closed
    sets of literals in this module. Route any future field that carries
    source text through ``_md_inline`` before it reaches a line.
    """
    lines = [
        "---",
        f"okf_version: {_yaml_quote(OKF_VERSION)}",
        "---",
        "",
        "# OKF Bundle",
        "",
        f"Open Knowledge Format v{OKF_VERSION} export. Scope: {scope}. "
        f"{len(concepts)} concept(s).",
        "",
    ]
    for okf_type in types:
        lines.append(f"* [{okf_type}]({okf_type}/index.md)")
    lines.append("")
    return "\n".join(lines)


class BundleDestinationError(Exception):
    """Raised when ``--out`` is not safe to clear/write."""


def _is_bundle_dir(path: Path) -> bool:
    """True if ``path`` looks like a prior OKF bundle (root index.md carrying
    ``okf_version`` frontmatter) — i.e. safe to clear and regenerate."""
    index = path / "index.md"
    if not index.is_file():
        return False
    fm, _ = parse_frontmatter(index.read_text(encoding="utf-8"))
    return "okf_version" in fm


def _slug_is_taken(taken: set[tuple[str, str]], okf_type: str, slug: str) -> bool:
    """True when ``slug`` is unavailable for a concept of ``okf_type``.

    The ONE predicate both passes of dedupe_slugs ask, so a reserved name and
    a claimed name can never be checked asymmetrically. The reserved test is
    deliberately type-independent: ``<type>/index.md`` is generated for every
    populated type directory, so no type may ever hold a concept named after
    a reserved file, and a future reserved name such as "log-2" is honoured
    by the bump loop for free.

    Both halves ask about the slug's ``_fs_identity``, because availability
    is a question about the FILE and two slugs can be one file. A byte-exact
    reserved test is how ``docs/Index.md`` kept the slug ``Index``, was
    written to ``<type>/Index.md``, and was then destroyed by the generated
    ``<type>/index.md`` written after it.
    """
    identity = _fs_identity(slug)
    return identity in _RESERVED_IDENTITIES or (okf_type, identity) in taken


def _claim_slug(taken: set[tuple[str, str]], okf_type: str, slug: str) -> None:
    """Record ``slug`` as no longer available for ``okf_type``.

    Paired with _slug_is_taken on purpose: a claim stored in one form and
    asked about in another is precisely the hole this pair exists to close,
    so the folding lives in exactly these two functions and nowhere else.
    """
    taken.add((okf_type, _fs_identity(slug)))


def dedupe_slugs(concepts: list[dict]) -> None:
    """Ensure every concept of one type names its own FILE, and never a
    reserved OKF filename. Mutates ``concept["slug"]`` in place.

    Uniqueness is measured on ``_fs_identity(slug)``, not on the slug: a
    slug becomes a filename, and `readme`/`README`, or the NFC and NFD
    spellings of `café`, are one file on a case-insensitive or normalizing
    filesystem. The emitted filename is unaffected and stays the concept's
    own slug: only the uniqueness key folds.

    "index" is always reserved: write_bundle generates ``<type>/index.md``
    itself, so any source concept slugged "index" would otherwise be
    silently clobbered by it. "log" is reserved for a chronological
    change-history file. Both, plus any other same-type slug collision
    (e.g. two differently-pathed ``README.md`` sources), take the LOWEST FREE
    numeric suffix (``slug-2``, ``slug-3``, ...), checked against every
    natural claim in the bundle rather than against a per-stem counter.

    A concept keeps its own natural slug wherever it can; the colliding
    duplicate is the one that moves. That rule needs TWO passes, because the
    natural owner of a bumped name may be discovered AFTER the duplicate that
    would otherwise be handed it (issue #152: docs/api/overview.md,
    docs/cli/overview.md, docs/zz/overview-2.md). Pass 1 claims every natural
    slug; only then does pass 2 compute a suffix, so a bumped name can never
    land on a slug some other concept owns, whichever order they arrive in.

    The suffix is appended to the concept's OWN natural slug, never to a
    parsed-off stem: a duplicate of a natural "overview-2" becomes
    "overview-2-2" rather than stealing "overview-3" from its potential
    natural owner.

    Deterministic: both passes walk ``concepts`` in discovery order (the list
    arrives pre-sorted by source path) and each candidate suffix is tried
    from 2 upward, so the assignment is fully determined by the input list.
    ``taken`` is a membership set only and is never iterated, so no set
    ordering can reach a filename.
    """
    taken: set[tuple[str, str]] = set()
    pending: list[dict] = []

    # Pass 1 (claim): every concept that CAN keep its natural slug does, and
    # the rest are parked. `taken` is complete before any suffix is computed.
    for concept in concepts:
        okf_type, slug = concept["okf_type"], concept["slug"]
        if _slug_is_taken(taken, okf_type, slug):
            pending.append(concept)
        else:
            _claim_slug(taken, okf_type, slug)

    # Pass 2 (bump): the lowest free suffix on the concept's own stem.
    for concept in pending:
        okf_type, stem = concept["okf_type"], concept["slug"]
        suffix = 2
        while _slug_is_taken(taken, okf_type, f"{stem}-{suffix}"):
            suffix += 1
        concept["slug"] = f"{stem}-{suffix}"
        _claim_slug(taken, okf_type, concept["slug"])


def _assert_unique_slugs(concepts: list[dict]) -> None:
    """Belt and braces behind dedupe_slugs: no two concepts of one type may
    name the same file, because ``write_text`` would silently let the second
    win.

    The failure this guards is invisible in both directions (issue #152): the
    bundle holds one fewer file than the manifest counts, and the type index
    grows two bullets pointing at one file. Raising ``BundleDestinationError``
    rather than a new exception type is deliberate, so main() already turns it
    into a clean stderr line and exit 1 instead of a traceback.

    Keyed on ``_fs_identity``, the same namespace dedupe_slugs assigns in. A
    backstop that compares bytes while the filesystem compares folded names
    would wave through exactly the collision it exists to catch, so both
    slugs go into the message: they are not necessarily equal, they only
    name one file.
    """
    claimed: dict[tuple[str, str], tuple[str, str]] = {}
    for concept in concepts:
        key = (concept["okf_type"], _fs_identity(concept["slug"]))
        first = claimed.get(key)
        if first is not None:
            raise BundleDestinationError(
                f"refusing to write the bundle: {first[0]} (slug {first[1]!r}) "
                f"and {concept['resource']} (slug {concept['slug']!r}) are both "
                f"{key[0]} concepts naming one file, so one would overwrite "
                "the other"
            )
        claimed[key] = (concept["resource"], concept["slug"])


def _assert_writable_slugs(concepts: list[dict]) -> None:
    """No concept may name a file the filesystem cannot hold.

    ``_SAFE_SLUG_RE`` bounds a memory fact's ``name:`` in SHAPE but not in
    length, and ``dedupe_slugs`` can add `-2` to a slug that was already at
    the limit. Either way ``target.write_text`` raised a bare
    ``OSError: File name too long`` from inside the write loop, which is
    after ``shutil.rmtree`` and before the root ``index.md``: the previous
    bundle was gone, the leftover directory no longer satisfied
    ``_is_bundle_dir``, and every later run refused to clear it even once the
    offending source was removed. The operator's only way out was ``rm -rf``.

    Raised as ``BundleDestinationError`` for the same reason
    ``_assert_unique_slugs`` is, and called next to it for the same reason:
    both belong before the rmtree, so the invariant fails with the previous
    bundle intact rather than after it.
    """
    for concept in concepts:
        name = f"{concept['slug']}.md"
        size = len(name.encode("utf-8"))
        if size > _NAME_MAX_BYTES:
            raise BundleDestinationError(
                f"refusing to write the bundle: {concept['resource']} would be "
                f"written as {name[:40]}... ({size} bytes), and a filename "
                f"longer than {_NAME_MAX_BYTES} bytes is too long for the "
                "filesystem. Shorten the source name"
            )


def write_bundle(
    root: Path,
    out_dir: Path,
    scope: str,
    memory_dir: Path | None = None,
    generated_by: str | None = None,
) -> dict:
    """Discover -> build -> resolve wikilinks -> write an OKF bundle at ``out_dir``.

    ``memory_dir`` adds the instance's auto-memory fact files as
    ``memory``-type concepts under USER scope, the primary wikilink target.
    Under core scope it is never read, but it is still guarded against as a
    destination: the store is usually out-of-repo data this exporter only
    ever reads, and a bundle written there is rmtree'd over on the next run
    of either scope.

    ``generated_by`` is the run-wide OKF actor written into every concept's
    ``generated.by``; it defaults to this exporter (see
    ``default_generated_by``). Run-wide rather than per-concept on purpose,
    so ``build_concept`` stays a pure function of the source file's bytes.

    Deterministic and idempotent: re-running against unchanged input produces
    a byte-identical file set (stable sort order, no wall-clock content).
    """
    generated_by = generated_by or default_generated_by()
    root = Path(root).resolve()
    out_dir = Path(out_dir).resolve()

    # Before any containment question: a destination that exists and is not a
    # directory. `Path.iterdir` raises NotADirectoryError on a regular file,
    # which reached the operator as a traceback where the documented contract
    # promises one stderr line.
    if out_dir.exists() and not out_dir.is_dir():
        raise BundleDestinationError(
            f"refusing to write the bundle to {out_dir}: it exists and is not "
            "a directory. Point --out at a directory that does not exist yet, "
            "or at a previous bundle output (e.g. dist/okf-bundle)"
        )

    if _contains(out_dir, root):
        raise BundleDestinationError(
            f"refusing to write the bundle to {out_dir}: it is --root or an "
            f"ancestor of --root ({_FOLD_NOTE}), so clearing it would delete "
            "source data, not just the bundle. Point --out outside the source "
            "tree, or at a directory no scope walks (e.g. dist/okf-bundle)"
        )

    # The converse guard, and the reason it runs HERE: a destination inside a
    # directory a scope walks would be read back in as source material on the
    # very next run of that scope, so the bundle would grow a concept per
    # generated file every time and the byte-identical re-run guarantee would
    # be false. It has to fire before discover_sources below (or the previous
    # run's output is already in memory) and before the rmtree further down
    # (or the evidence is deleted by the same run that consumed it).
    #
    # Against the UNION of every scope, not this run's scope: the bundle stays
    # on disk after the run that wrote it, so a destination only the other
    # scope walks is still eaten (see all_scanned_dirs). That makes the
    # refusal wider than this run's read set on purpose. Fail-closed is the
    # right bias when the failure being guarded is silent data corruption, and
    # the answer to a refusal is another destination.
    for scanned, scopes in all_scanned_dirs(root):
        walkers = " and ".join(f"--scope {name}" for name in scopes)
        walk = "walks" if len(scopes) == 1 else "walk"
        which = "that scope" if len(scopes) == 1 else "either scope"
        if _contains(scanned, out_dir):
            raise BundleDestinationError(
                f"refusing to write the bundle to {out_dir}: it is inside "
                f"{scanned} ({_FOLD_NOTE}), which {walkers} {walk} for "
                f"sources, so a run of {which} would re-ingest this bundle as "
                "source material. Point --out at a directory NO scope walks "
                "(e.g. dist/okf-bundle)"
            )
        if _contains(out_dir, scanned):
            raise BundleDestinationError(
                f"refusing to write the bundle to {out_dir}: it contains "
                f"{scanned} ({_FOLD_NOTE}), which {walkers} {walk} for "
                "sources, so clearing it would delete source data, not just "
                "the bundle. Point --out at a directory NO scope walks "
                "(e.g. dist/okf-bundle)"
            )

    # The memory store is READ only under user scope (see the discover_memory
    # call below), and guarded as a destination under every scope, for the
    # same reason all_scanned_dirs takes the union over scopes: the bundle
    # outlives the run that wrote it. A core-scope run gated out of this
    # clause wrote its bundle into the store happily, and the next run of
    # EITHER scope then rmtree'd it, fact files and all, because the directory
    # now carried an okf_version index and sailed through the late non-bundle
    # check. The store usually lives outside the repo and this exporter is
    # strictly a reader of it.
    if memory_dir is not None:
        resolved_memory = Path(memory_dir).resolve()
        if _contains(resolved_memory, out_dir) or _contains(out_dir, resolved_memory):
            raise BundleDestinationError(
                f"refusing to write the bundle to {out_dir}: it overlaps the "
                f"memory dir {resolved_memory} ({_FOLD_NOTE}). The exporter "
                "never writes into the memory store, in any scope. Point --out "
                "at a directory outside it (e.g. dist/okf-bundle)"
            )

    sources = discover_sources(root, scope)
    concepts = [build_concept(path, root) for path in sources]
    if scope == "user" and memory_dir is not None:
        concepts.extend(build_memory_concept(path) for path in discover_memory(memory_dir))
    dedupe_slugs(concepts)
    # Before the sort, before the rmtree below, and before any write: a future
    # regression must fail with the previous bundle intact, not after it.
    _assert_unique_slugs(concepts)
    _assert_writable_slugs(concepts)
    concepts.sort(key=lambda c: (c["okf_type"], c["slug"]))

    # Wikilinks are memory references by convention — on a cross-type slug
    # collision the memory concept wins the link target, everything else is
    # first-come in the stable (type, slug) order.
    slug_to_relpath: dict[str, str] = {}
    for concept in concepts:
        if concept["okf_type"] == "memory":
            slug_to_relpath[concept["slug"]] = f"/memory/{concept['slug']}.md"
    for concept in concepts:
        slug_to_relpath.setdefault(
            concept["slug"], f"/{concept['okf_type']}/{concept['slug']}.md"
        )

    unresolved_all: set[str] = set()
    for concept in concepts:
        resolved_body, unresolved = resolve_wikilinks(concept["body"], slug_to_relpath)
        concept["body"] = resolved_body
        unresolved_all.update(unresolved)

    if out_dir.exists():
        if any(out_dir.iterdir()) and not _is_bundle_dir(out_dir):
            raise BundleDestinationError(
                f"refusing to clear {out_dir}: it already exists, is "
                "non-empty, and does not look like a prior OKF bundle (no "
                "index.md carrying okf_version) — point --out at an empty "
                "directory or a previous bundle output"
            )
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    by_type: dict[str, list[dict]] = {}
    for concept in concepts:
        by_type.setdefault(concept["okf_type"], []).append(concept)

    # The root index.md goes down FIRST, before any concept file, because
    # _is_bundle_dir keys off it and that is what decides whether a later run
    # may clear this directory. Written last, ANY failure inside the write
    # loop (a full disk, a permission error, a filename the filesystem
    # rejects) left a non-empty directory that no longer looked like a bundle
    # and that the exporter then refused for good. The file content does not
    # depend on the loop below, only on `by_type`, so nothing about the
    # bundle's bytes changes; only the order they appear in does.
    (out_dir / "index.md").write_text(
        _render_root_index(scope, concepts, sorted(by_type)), encoding="utf-8"
    )

    for okf_type in sorted(by_type):
        type_concepts = by_type[okf_type]
        type_dir = out_dir / okf_type
        type_dir.mkdir(parents=True, exist_ok=True)
        for concept in sorted(type_concepts, key=lambda c: c["slug"]):
            # Belt and braces behind _SAFE_SLUG_RE: whatever a future slug
            # source is, a concept must never be written outside its own type
            # directory. The exporter is read-only against the source tree, and
            # an escaping filename is precisely how that guarantee would break.
            target = type_dir / f"{concept['slug']}.md"
            if target.parent.resolve() != type_dir.resolve():
                raise BundleDestinationError(
                    f"refusing to write concept {concept['slug']!r}: it resolves "
                    f"outside {type_dir}"
                )
            target.write_text(_render_concept(concept, generated_by), encoding="utf-8")
        (type_dir / "index.md").write_text(
            _render_type_index(okf_type, type_concepts), encoding="utf-8"
        )

    return {
        "okf_version": OKF_VERSION,
        "scope": scope,
        "concept_count": len(concepts),
        "generated_by": generated_by,
        # A COUNT, never a list of paths: the manifest is printed, and a list
        # would put instance-relative source paths into that output.
        "concepts_without_generated_at": sum(
            1 for c in concepts if not c.get("generated_at")
        ),
        "unresolved_wikilinks": sorted(unresolved_all),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="okf-export.py",
        description="Export a Bridge instance as an Open Knowledge Format (OKF) v0.2 bundle.",
    )
    parser.add_argument("--root", default=".", help="Bridge instance root (default: .)")
    parser.add_argument("--out", required=True, help="output bundle directory")
    parser.add_argument(
        "--scope",
        choices=["user", "core"],
        default="user",
        help="user = everything (work/+docs/+rules/+examples/+memory); "
        "core = docs/+examples/ only (default: user)",
    )
    parser.add_argument(
        "--memory-dir",
        default=None,
        help="auto-memory directory to export as memory concepts (user scope "
        "only; default: resolved via scripts/memory-location.py, i.e. a "
        "configured autoMemoryDirectory, else the legacy "
        "~/.claude/projects/<encoded-root>/memory; silently skipped when "
        "absent)",
    )
    parser.add_argument(
        "--generated-by",
        default=None,
        metavar="ACTOR",
        help="OKF actor written to every concept's generated.by; one of "
        "'<producer>/<version>', 'human:<id>' or 'process:<id>' "
        f"(default: {default_generated_by()})",
    )
    args = parser.parse_args(argv)

    root = Path(args.root)
    if not root.is_dir():
        sys.stderr.write(f"ERROR: --root {root} does not exist or is not a directory\n")
        return 1

    generated_by = args.generated_by or default_generated_by()
    if not _ACTOR_RE.match(generated_by):
        sys.stderr.write(
            f"ERROR: --generated-by {generated_by!r} is not an OKF actor. Use "
            "'<producer>/<version>', 'human:<id>' or 'process:<id>'. The value "
            "is written verbatim into every concept, so an unconstrained string "
            "would be an unreadable provenance claim at best and malformed YAML "
            "at worst.\n"
        )
        return 1
    if generated_by.startswith("human:") and args.scope == "core":
        sys.stderr.write(
            f"WARNING: --scope core with a human actor ({generated_by}) writes a "
            "personal identifier into every concept of a bundle whose whole "
            "point is being publishable. Proceeding as requested.\n"
        )

    # Resolved in EVERY scope, read in one. write_bundle can only guard a
    # destination it has been told about, and the store it must never rmtree
    # is the same store whichever scope is running (see the memory clause
    # there). Only the NOTICE is user-scope, because only user scope was going
    # to export from it.
    memory_dir: Path | None = Path(args.memory_dir) if args.memory_dir else default_memory_dir(root)
    if not memory_dir.is_dir():
        if args.scope == "user":
            sys.stderr.write(f"NOTICE: no memory dir at {memory_dir} — skipping memory export\n")
        memory_dir = None

    out_dir = Path(args.out)
    try:
        manifest = write_bundle(
            root, out_dir, args.scope, memory_dir=memory_dir, generated_by=generated_by
        )
    except BundleDestinationError as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        return 1
    print(
        f"okf-export: wrote {manifest['concept_count']} concept(s) to {out_dir} "
        f"(scope={manifest['scope']}, okf_version={manifest['okf_version']}, "
        f"generated_by={manifest['generated_by']}, "
        f"without_generated_at={manifest['concepts_without_generated_at']}, "
        f"unresolved_wikilinks={len(manifest['unresolved_wikilinks'])})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
