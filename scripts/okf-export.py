#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Export a Bridge instance as an Open Knowledge Format (OKF) v0.1 bundle.

A single, additive, dependency-free script that walks a Bridge instance's
knowledge surfaces (work/ STATUS.md + deliverables, docs/, rules/,
examples/) and emits a static OKF bundle — one markdown file per concept, a
per-type index.md, and a root index.md carrying the OKF version. No PyYAML
dependency: frontmatter parsing is hand-rolled, mirroring the conventions
already used by scripts/extract-frontmatter.py (skips the
`# yaml-language-server: $schema=...` comment prolog) and scripts/gen-board.py
(parse_status()'s flat `key: value` scalar extraction, quote + inline-comment
stripping).

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
`name:` key); the directory usually lives OUTSIDE the repo and defaults to
`~/.claude/projects/<encoded-root>/memory` (override with --memory-dir).
Every concept carries a `resource:` field pointing at its source (repo-
relative path, or `memory/<filename>` for memory facts).

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

Usage:
  python3 scripts/okf-export.py --out dist/okf-bundle
  python3 scripts/okf-export.py --root . --out dist/okf-bundle --scope core

Exit codes:
  0 — bundle written successfully
  1 — --root does not exist / is not a directory, or unsafe --out refused
  2 — argparse usage error (e.g. unknown --scope; raised as SystemExit)
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

OKF_VERSION = "0.1"

# Kebab-case identifiers only: bash `[[ -f file ]]` conditionals inside code
# blocks must never match (and must never be rewritten or reported).
_WIKILINK_RE = re.compile(r"\[\[([a-z][a-z0-9-]*)\]\]")
_FRONTMATTER_KV_RE = re.compile(r"^([A-Za-z_][\w]*):\s*(.*)$")
_YAML_LS_PROLOG_RE = re.compile(r"^#\s*yaml-language-server:")
_BLOCK_SCALAR_RE = re.compile(r"^[|>][+-]?\d*$")
_RESERVED_SLUGS = frozenset({"index", "log"})
# Memory-dir housekeeping files that are never concepts (index + provenance).
_MEMORY_SKIP = frozenset({"MEMORY.md", "MEMORY-ARCHIVE.md", "PROVENANCE.md"})


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split ``text`` into (frontmatter dict, body). Hand-rolled, no PyYAML.

    Mirrors scripts/gen-board.py's parse_status() field extraction plus
    scripts/extract-frontmatter.py's leading-comment-prolog skip (so a
    `# yaml-language-server: $schema=...` hint above the `---` fence never
    confuses detection). A file with no frontmatter block returns ({}, text)
    with the body left completely untouched.
    """
    lines = text.splitlines(keepends=True)
    in_block = False
    fm_start_idx: int | None = None
    fence_close_idx: int | None = None

    for idx, line in enumerate(lines):
        if not in_block:
            if _YAML_LS_PROLOG_RE.match(line.lstrip()):
                continue
            if line.strip() == "---":
                in_block = True
                fm_start_idx = idx + 1
                continue
            if line.strip() == "":
                continue
            # first non-empty, non-comment, non-fence line -> no frontmatter block
            return {}, text
        else:
            if line.strip() == "---":
                fence_close_idx = idx
                break

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
        key, val = m.group(1), m.group(2)
        val = re.sub(r"\s+#.*$", "", val).strip()
        if _BLOCK_SCALAR_RE.match(val):
            # YAML block scalar (`>-`/`|`/...) — fold/preserve the indented
            # continuation lines instead of shipping the bare indicator as
            # the literal value.
            folded = val.startswith(">")
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
            val = val.strip('"').strip("'")
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


def discover_sources(root: Path, scope: str) -> list[Path]:
    """Walk ``root`` for OKF source files per ``scope`` ("user" or "core")."""
    root = Path(root)
    if scope == "core":
        patterns = ["docs/**/*.md", "examples/**/*.md"]
    elif scope == "user":
        patterns = [
            "work/tasks/*/STATUS.md",
            "work/streams/*/STATUS.md",
            "work/done/*/*/STATUS.md",
            "work/**/deliverables/*.md",
            "docs/**/*.md",
            "rules/**/*.md",
            "examples/**/*.md",
        ]
    else:
        raise ValueError(f"unknown scope: {scope!r} (expected 'user' or 'core')")

    found: set[Path] = set()
    for pattern in patterns:
        found.update(p for p in root.glob(pattern) if p.is_file())
    return sorted(found, key=lambda p: p.relative_to(root).as_posix())


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


def build_concept(path: Path, root: Path) -> dict:
    """Read ``path`` and build its OKF concept dict (body left un-resolved)."""
    text = Path(path).read_text(encoding="utf-8")
    fm, body = parse_frontmatter(text)
    slug = concept_slug(path)
    okf_type = concept_type_for(path, root)
    title = derive_title(fm, body, fallback=slug)
    description = derive_description(fm, body)
    timestamp = fm.get("last_updated") or fm.get("created") or ""
    tags = [value for value in (fm.get("status"), fm.get("context")) if value]
    return {
        "slug": slug,
        "okf_type": okf_type,
        "title": title,
        "description": description,
        "resource": Path(path).relative_to(root).as_posix(),
        "timestamp": timestamp,
        "tags": tags,
        "body": body,
    }


def default_memory_dir(root: Path) -> Path:
    """Derive the instance's auto-memory directory from its root path.

    The harness stores per-project memory under
    ``~/.claude/projects/<encoded>/memory`` where ``<encoded>`` is the
    absolute project path with every ``/`` replaced by ``-`` (the leading
    slash becomes a leading dash).
    """
    encoded = str(Path(root).resolve()).replace("/", "-")
    return Path.home() / ".claude" / "projects" / encoded / "memory"


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
    and underscores dashed. Memory facts carry no dates, so ``timestamp``
    stays empty; ``resource`` points into the (out-of-repo) memory dir.
    """
    text = Path(path).read_text(encoding="utf-8")
    fm, body = parse_frontmatter(text)
    slug = fm.get("name") or path.stem.split("_", 1)[-1].replace("_", "-")
    return {
        "slug": slug,
        "okf_type": "memory",
        "title": derive_title(fm, body, fallback=slug),
        "description": derive_description(fm, body),
        "resource": f"memory/{path.name}",
        "timestamp": "",
        "tags": [],
        "body": body,
    }


def _yaml_quote(value: str) -> str:
    """Render a scalar as a double-quoted YAML string (backslash + quote escaped)."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _render_concept(concept: dict) -> str:
    tags = ", ".join(concept["tags"])
    header = "\n".join(
        [
            "---",
            f"type: {concept['okf_type']}",
            f"title: {_yaml_quote(concept['title'])}",
            f"description: {_yaml_quote(concept['description'])}",
            f"resource: {_yaml_quote(concept['resource'])}",
            f"timestamp: {_yaml_quote(concept['timestamp'])}",
            f"tags: [{tags}]",
            "---",
            "",
        ]
    )
    return header + concept["body"]


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
    for concept in sorted(concepts, key=lambda c: c["slug"]):
        suffix = f" — {concept['description']}" if concept["description"] else ""
        lines.append(f"- [{concept['title']}]({concept['slug']}.md){suffix}")
    lines.append("")
    return "\n".join(lines)


def _render_root_index(scope: str, concepts: list[dict], types: list[str]) -> str:
    lines = [
        "---",
        f"okf_version: {_yaml_quote(OKF_VERSION)}",
        f"scope: {scope}",
        f"concept_count: {len(concepts)}",
        "---",
        "",
        "# OKF Bundle",
        "",
        f"Open Knowledge Format v{OKF_VERSION} export — scope: {scope}, "
        f"{len(concepts)} concept(s).",
        "",
    ]
    for okf_type in types:
        lines.append(f"- [{okf_type}]({okf_type}/index.md)")
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


def dedupe_slugs(concepts: list[dict]) -> None:
    """Ensure every concept's (okf_type, slug) is unique and never collides
    with a reserved OKF filename — mutates ``concept["slug"]`` in place.

    "index" is always reserved: write_bundle generates ``<type>/index.md``
    itself, so any source concept slugged "index" would otherwise be
    silently clobbered by it. "log" is reserved for a chronological
    change-history file. Both, plus any other same-type slug collision
    (e.g. two differently-pathed ``README.md`` sources), get a stable
    numeric suffix (``slug-2``, ``slug-3``, ...) in discovery order
    (concepts arrive pre-sorted by source path; a stable sort keeps that
    order for equal keys).
    """
    seen: dict[tuple[str, str], int] = {
        (okf_type, reserved): 1
        for okf_type in {c["okf_type"] for c in concepts}
        for reserved in _RESERVED_SLUGS
    }
    for concept in concepts:
        key = (concept["okf_type"], concept["slug"])
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > 1:
            concept["slug"] = f"{concept['slug']}-{seen[key]}"


def write_bundle(
    root: Path, out_dir: Path, scope: str, memory_dir: Path | None = None
) -> dict:
    """Discover -> build -> resolve wikilinks -> write an OKF bundle at ``out_dir``.

    ``memory_dir`` (user scope only) adds the instance's auto-memory fact
    files as ``memory``-type concepts — the primary wikilink target.

    Deterministic and idempotent: re-running against unchanged input produces
    a byte-identical file set (stable sort order, no wall-clock content).
    """
    root = Path(root).resolve()
    out_dir = Path(out_dir).resolve()

    if out_dir == root or root.is_relative_to(out_dir):
        raise BundleDestinationError(
            f"refusing to write the bundle to {out_dir}: it is --root or an "
            "ancestor of --root, so clearing it would delete source data, "
            "not just the bundle"
        )

    sources = discover_sources(root, scope)
    concepts = [build_concept(path, root) for path in sources]
    if scope == "user" and memory_dir is not None:
        concepts.extend(build_memory_concept(path) for path in discover_memory(memory_dir))
    dedupe_slugs(concepts)
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

    for okf_type in sorted(by_type):
        type_concepts = by_type[okf_type]
        type_dir = out_dir / okf_type
        type_dir.mkdir(parents=True, exist_ok=True)
        for concept in sorted(type_concepts, key=lambda c: c["slug"]):
            (type_dir / f"{concept['slug']}.md").write_text(
                _render_concept(concept), encoding="utf-8"
            )
        (type_dir / "index.md").write_text(
            _render_type_index(okf_type, type_concepts), encoding="utf-8"
        )

    (out_dir / "index.md").write_text(
        _render_root_index(scope, concepts, sorted(by_type)), encoding="utf-8"
    )

    return {
        "okf_version": OKF_VERSION,
        "scope": scope,
        "concept_count": len(concepts),
        "unresolved_wikilinks": sorted(unresolved_all),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="okf-export.py",
        description="Export a Bridge instance as an Open Knowledge Format (OKF) v0.1 bundle.",
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
        "only; default: derived as ~/.claude/projects/<encoded-root>/memory, "
        "silently skipped when absent)",
    )
    args = parser.parse_args(argv)

    root = Path(args.root)
    if not root.is_dir():
        sys.stderr.write(f"ERROR: --root {root} does not exist or is not a directory\n")
        return 1

    memory_dir: Path | None = None
    if args.scope == "user":
        memory_dir = Path(args.memory_dir) if args.memory_dir else default_memory_dir(root)
        if not memory_dir.is_dir():
            sys.stderr.write(f"NOTICE: no memory dir at {memory_dir} — skipping memory export\n")
            memory_dir = None

    out_dir = Path(args.out)
    try:
        manifest = write_bundle(root, out_dir, args.scope, memory_dir=memory_dir)
    except BundleDestinationError as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        return 1
    print(
        f"okf-export: wrote {manifest['concept_count']} concept(s) to {out_dir} "
        f"(scope={manifest['scope']}, okf_version={manifest['okf_version']}, "
        f"unresolved_wikilinks={len(manifest['unresolved_wikilinks'])})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
