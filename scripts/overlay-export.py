#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Author a single-owner overlay repo by EXPORTING scope-tagged live files.

This is the *authoring* half of the overlay primitive (Direction A). Where
scripts/overlay.py MATERIALIZES an overlay's `tree/` mirror DOWN into a
consumer, this script builds that mirror UP: it copies every file the router
classifies into a given tier (`personal` by default) into `<target>/tree/<path>`
and regenerates `<target>/overlay.manifest.yaml`'s `files[]` — the exact shape
scripts/overlay.py then consumes (source_root `tree/`, manifest at the repo
root, per-rule `kind: rule` exceptions).

Why an export step (not /promote): `/promote` and `/bridge-sync` cherry-pick
SAME-PATH commits onto a normal-layout branch, which would land files at the
overlay's repo ROOT — not under `tree/` — producing a mirror overlay.py cannot
read. A `tree/`-prefixed flat mirror must be BUILT, which is this script.

Single-owner => VERBATIM. A personal overlay carries no per-consumer
placeholders: files are copied byte-for-byte with NO scrubbing and the manifest
gets NO `prompt_fields`. Customer/org-bleed protection is the promote-time
blocklist's job, not this tool's.

Contract (public surface, mirrored by scripts/tests/test_overlay_export.py):
    is_excluded(relpath) -> bool
    discover_scoped_files(repo_root, scope="personal") -> list[str]  (sorted)
    manifest_files_entries(relpaths, scope="personal") -> list[dict]
    build_manifest(existing, files_entries, scope="personal") -> dict
    export_overlay(repo_root, target, *, scope="personal", dry_run=False) -> dict
    main(argv=None) -> int

Guarantees:
    - NEVER writes into the live repo — it only reads the repo and writes under
      <target>. It DOES consult git, for exactly one read-only question:
      `git check-ignore`, to learn which files git refuses to track (see
      git_ignored). It ran no git at all until 2026-08-01, and that is precisely
      how a live `.env` and a live API key came to be staged for a shared
      overlay — a pattern list can only exclude the shapes someone thought of.
    - Deterministic + idempotent: re-running against unchanged input yields a
      byte-identical tree/ and manifest; stale mirror files are pruned.
    - No wall-clock / date content anywhere (so the output is reproducible).

The scope→tier decision is delegated wholesale to
scripts/categorize-commits.py classify_file() (the executable mirror of
rules/operations.md § CORE/USER Separation), imported via importlib because of
its hyphenated filename — the same pattern scripts/overlay.py uses.

Exit codes:
    0 — success        1 — bad --repo-root

Design: work/tasks/personal-overlay-separation/deliverables/DESIGN.md §2.3–2.4.
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import os
import subprocess
import sys

try:
    import yaml
except ImportError:  # pragma: no cover - environment guard
    sys.stderr.write("ERROR: PyYAML not installed. pip install pyyaml\n")
    sys.exit(2)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

DEFAULT_SCOPE = "personal"
SOURCE_ROOT = "tree/"
MANIFEST_FILE = "overlay.manifest.yaml"

# Contract exclusions: never export these regardless of a file's classified
# tier. work/ = live instance runtime; identity/agent/ = THIS bridge's
# orchestrator identity (a split-off authors its own).
EXCLUDE_DIR_PREFIXES = ("work/", "identity/agent/")

# The flat-mirror selection a fresh (bootstrap) manifest scaffold advertises to
# the consumer engine — mirrors scripts/overlay.py's expectations + DESIGN §2.3.
_DEFAULT_EXCLUDE = ["**/_*.yaml", "**/README.md", "identity/agent/**", "work/**"]

_GITIGNORE_BODY = "__pycache__/\n*.pyc\n.DS_Store\n"


# ---------------------------------------------------------------------------
# Reused primitive: classify_file (hyphenated filename → importlib, not import)
# ---------------------------------------------------------------------------

def _load_module(name: str, filename: str):
    path = os.path.join(SCRIPT_DIR, filename)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f"cannot load {filename}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


try:
    _categorize = _load_module("categorize_commits", "categorize-commits.py")
    classify_file = _categorize.classify_file
except Exception as exc:  # pragma: no cover - defensive
    sys.stderr.write(f"ERROR: cannot load categorize-commits.py: {exc}\n")
    sys.exit(2)


# ---------------------------------------------------------------------------
# CWD helper — classify_file reads frontmatter relative to CWD
# ---------------------------------------------------------------------------

class _Pushd:
    """chdir into `path` for the duration of a `with` block, always restoring."""

    def __init__(self, path: str):
        self.path = path
        self._prev: str | None = None

    def __enter__(self):
        self._prev = os.getcwd()
        os.chdir(self.path)
        return self

    def __exit__(self, *exc):
        if self._prev is not None:
            os.chdir(self._prev)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

#: Build + runtime artifacts. This walk NEVER runs git (see the module docstring),
#: so .gitignore does not protect the overlay: anything sitting on disk under a
#: scoped path is a publication candidate. Measured 2026-08-01 — a `--scope org`
#: run staged 21 of these, among them a bot's stored conversations and four .bak
#: snapshots, which is how they reached the shared org overlay to begin with.
_ARTIFACT_DIRS = ("__pycache__/", "/data/state/", "/data/conversations/")
_ARTIFACT_SUFFIXES = (".pyc", ".pyo")

#: One-shot migration helpers with no runtime references — source, but not
#: something a consumer should materialize.
_EXCLUDE_EXACT = frozenset({
    "skills/ui-ux-pro-max/data/_sync_all.py",
})


def never_promote_paths(repo_root: str) -> frozenset[str]:
    """`promote.never_promote` from bridge-config.yaml — files that exist on BOTH
    sides and must never be copied in either direction.

    A tier cannot express "belongs to neither side". `ecosystem.yaml` is the
    per-instance base, so materializing it would overwrite each consumer's own;
    `ecosystem.<org>.yaml` is RECEIVED from the org, so writing it back reverts
    whatever the org changed (that already cost one commit).

    The list was wired into the three promote SKILLS in C4 but not here — and
    this is the tool that actually writes into an overlay repo. Measured
    2026-08-01: a `--scope org` run wanted to create both of those files.
    A governance list no code path reads is not a rule, it is a wish.
    """
    path = os.path.join(repo_root, "bridge-config.yaml")
    try:
        with open(path, encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError):
        return frozenset()
    entries = (cfg.get("promote") or {}).get("never_promote") or []
    return frozenset(
        e["path"] for e in entries if isinstance(e, dict) and e.get("path")
    )


def _is_artifact(relpath: str) -> bool:
    base = os.path.basename(relpath)
    padded = "/" + relpath
    if any(seg in padded for seg in _ARTIFACT_DIRS):
        return True
    if relpath.endswith(_ARTIFACT_SUFFIXES):
        return True
    # .bak, .bak.20260221_0906, report.html.bak — editor and manual snapshots
    return ".bak" in base


def is_excluded(relpath: str) -> bool:
    """True if `relpath` must never be exported.

    Three classes: the contract exclusions (work/**, identity/agent/**), build and
    runtime artifacts, and `_`-prefixed CORE companions.

    The underscore rule keeps its original reach — a `_`-prefixed basename is
    reserved everywhere (`_schema.yaml` / `_template.yaml` in the cluster
    wrappers per AGENTS.md § Layout, `_draft.md` under rules/) — with ONE carve
    out: `skills/`. A skill is a self-contained directory whose filenames are its
    own business, and the blanket rule silently dropped four real source files:
    a skill's documented entry point (`presets/_index.html`), the schema its own
    SKILL.md tells you to read (`presets/_template.yaml`), and a package
    `__init__.py` without which the package will not import. A skill that
    materializes missing its entry point is broken in a way nobody sees until
    the consumer runs it.
    """
    if relpath in _EXCLUDE_EXACT:
        return True
    if _is_artifact(relpath):
        return True
    if not relpath.startswith("skills/") and \
            os.path.basename(relpath).startswith("_"):
        return True
    for prefix in EXCLUDE_DIR_PREFIXES:
        if relpath == prefix.rstrip("/") or relpath.startswith(prefix):
            return True
    return False


def git_ignored(repo_root: str, relpaths: list[str]) -> set[str]:
    """The subset of `relpaths` that git refuses to track.

    THE authoritative exclusion. The pattern lists above enumerate artifact
    SHAPES, which only ever closes the shapes someone thought of; measured
    2026-08-01, a `--scope org` run still staged `skills/sharepoint-manager/.env`
    (a live Azure client secret for a customer tenant) and a skill's
    `config.local.json` (a live Elastic Cloud API key) — neither looks like a
    build artifact, and both were gitignored. git already knew.

    A `git check-ignore` that neither succeeds (0) nor cleanly reports "none"
    (1) is FATAL, not a warning: the caller is about to publish into a shared
    repo, and continuing on unknown ignore state is exactly how a secret ships.
    """
    if not relpaths:
        return set()
    if not os.path.isdir(os.path.join(repo_root, ".git")):
        print(
            f"WARNING: {repo_root} is not a git checkout — .gitignore cannot be "
            "consulted, so only the pattern-based exclusions apply.",
            file=sys.stderr,
        )
        return set()
    proc = subprocess.run(
        ["git", "check-ignore", "--stdin"],
        cwd=repo_root, input="\n".join(relpaths),
        capture_output=True, text=True,
    )
    if proc.returncode not in (0, 1):
        sys.exit(
            "FATAL: `git check-ignore` failed, so it is unknown which files are "
            f"gitignored. Refusing to export.\n{proc.stderr.strip()}"
        )
    return {p for p in proc.stdout.splitlines() if p.strip()}


def discover_scoped_files(repo_root: str, scope: str = DEFAULT_SCOPE) -> list[str]:
    """SORTED repo-relative paths whose classify_file() == `scope`, minus the
    exclusions. Reads only — the live repo is never modified. classify_file
    resolves frontmatter relative to CWD, so the walk runs from inside
    repo_root."""
    repo_root = os.path.abspath(repo_root)
    forbidden = never_promote_paths(repo_root)
    found: list[str] = []
    with _Pushd(repo_root):
        for dirpath, dirnames, filenames in os.walk("."):
            dirnames[:] = [d for d in dirnames if d != ".git"]
            for fn in filenames:
                rel = os.path.normpath(os.path.join(dirpath, fn)).replace(os.sep, "/")
                if rel in (".", ""):
                    continue
                if is_excluded(rel):
                    continue
                if rel in forbidden:
                    print(f"  skipped (never_promote): {rel}", file=sys.stderr)
                    continue
                if classify_file(rel) == scope:
                    found.append(rel)
    ignored = git_ignored(repo_root, found)
    if ignored:
        for p in sorted(ignored):
            print(f"  skipped (gitignored): {p}", file=sys.stderr)
    return sorted(p for p in found if p not in ignored)


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def _is_rule(dest: str, scope: str) -> bool:
    return dest.startswith(f"rules/{scope}/") and dest.endswith(".md")


def manifest_files_entries(relpaths, scope: str = DEFAULT_SCOPE) -> list[dict]:
    """The `files[]` EXCEPTION list. Namespaced rules (rules/<scope>/*.md) need
    an explicit `kind: rule`; everything else is a verbatim mirror covered by
    `defaults` and gets NO entry. Single-owner => no `prompt_fields`, ever.
    Sorted by dest for determinism."""
    entries = [{"dest": r, "kind": "rule"} for r in relpaths if _is_rule(r, scope)]
    entries.sort(key=lambda e: e["dest"])
    return entries


def _default_manifest(scope: str) -> dict:
    """Bootstrap scaffold when the target has no manifest yet. Generic (no
    instance PII): overlay identity defaults to the scope slug; the human can
    enrich name/description/ecosystem_fragment and this tool preserves them."""
    return {
        "schema_version": 1,
        "overlay": {
            "name": scope,
            "org": scope,
            "description": (
                f"Single-owner {scope} overlay — verbatim mirror authored by "
                f"scripts/overlay-export.py (no scrubbing, no prompt_fields)."
            ),
        },
        "defaults": {
            "scope": scope,
            "source_root": SOURCE_ROOT,
            "on_conflict": "prompt",
        },
        "selection": {
            "include": ["**"],
            "exclude": list(_DEFAULT_EXCLUDE),
        },
    }


def build_manifest(existing, files_entries, scope: str = DEFAULT_SCOPE) -> dict:
    """Regenerate the manifest. An existing manifest's scaffold VALUES (overlay
    identity, defaults, selection, ecosystem_fragment, …) are preserved; only
    `files[]` is replaced. An absent/empty existing yields the bootstrap
    scaffold."""
    if isinstance(existing, dict) and existing:
        manifest = copy.deepcopy(existing)
    else:
        manifest = _default_manifest(scope)
    manifest["files"] = list(files_entries)
    return manifest


def _manifest_header(scope: str) -> str:
    return (
        "# yaml-language-server: $schema=./docs/schemas/overlay-manifest.schema.yaml\n"
        "# GENERATED by scripts/overlay-export.py — files[] is regenerated on every\n"
        "# export; hand comments/formatting may be lost (scaffold VALUES preserved).\n"
        f"# Single-owner {scope} overlay: verbatim mirror, no scrubbing, no prompt_fields.\n"
    )


def _dump_manifest(manifest: dict, scope: str) -> bytes:
    body = yaml.safe_dump(manifest, sort_keys=False, default_flow_style=False,
                          allow_unicode=True, width=100)
    return (_manifest_header(scope) + body).encode("utf-8")


# ---------------------------------------------------------------------------
# Low-level file I/O (COPY verbatim; never git, never symlink)
# ---------------------------------------------------------------------------

def _read_bytes(path: str) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()


def _write_bytes(path: str, data: bytes) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)


def _tree_files(tree_root: str) -> list[str]:
    """Existing tree-relative file paths under `tree_root` (posix spelling)."""
    out: list[str] = []
    if not os.path.isdir(tree_root):
        return out
    for dirpath, _dirnames, filenames in os.walk(tree_root):
        for fn in filenames:
            abs_p = os.path.join(dirpath, fn)
            out.append(os.path.relpath(abs_p, tree_root).replace(os.sep, "/"))
    return out


def _prune_empty_dirs(tree_root: str) -> None:
    for dirpath, _dirnames, _filenames in os.walk(tree_root, topdown=False):
        if os.path.abspath(dirpath) == os.path.abspath(tree_root):
            continue
        try:
            if not os.listdir(dirpath):
                os.rmdir(dirpath)
        except OSError:  # pragma: no cover - defensive
            pass


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

LOCK_FILE = "overlays.lock.yaml"


def overlay_managed_paths(repo_root: str) -> set[str]:
    """Repo-relative paths this bridge holds because an OVERLAY put them there.

    Read from `overlays.lock.yaml`, which `/overlay` writes when it materializes.
    They are deliberately git-ignored in the consumer (a fork of a public repo is
    itself public), so `git_ignored` — rightly — hides them from discovery. Without
    this set the exporter would then read every mirror copy of them as an orphan
    and delete it: the tool that BUILDS the mirror would eat the half of it that
    came from the mirror. Measured on a live consumer/overlay pair: 35 files, among
    them the complete references/ and templates/ of two org skills.

    A missing or malformed lock yields the empty set, and the caller then behaves
    exactly as before — never a crash, and never a silently WIDER prune.
    """
    path = os.path.join(repo_root, LOCK_FILE)
    if yaml is None or not os.path.exists(path):
        return set()
    try:
        with open(path, encoding="utf-8") as fh:
            lock = yaml.safe_load(fh)
    except (OSError, UnicodeDecodeError, Exception):  # noqa: B014 - yaml errors vary
        return set()
    if not isinstance(lock, dict):
        return set()
    managed: set[str] = set()
    for entry in (lock.get("overlays") or {}).values():
        if not isinstance(entry, dict):
            continue
        for f in (entry.get("files") or []):
            if isinstance(f, dict) and isinstance(f.get("dest"), str):
                managed.add(f["dest"])
    return managed


def export_overlay(repo_root: str, target_overlay_dir: str, *,
                   scope: str = DEFAULT_SCOPE, dry_run: bool = False) -> dict:
    """Export every `scope`-classified live file into `<target>/tree/<path>` and
    regenerate `<target>/overlay.manifest.yaml` files[].

    Returns a plan/result dict:
        {scope, repo_root, target, tree_root, manifest_path,
         copied[list], pruned[list], files_entries[list], manifest[dict], dry_run}

    `--dry-run` computes the full plan but writes nothing.
    """
    repo_root = os.path.abspath(repo_root)
    target = os.path.abspath(target_overlay_dir)
    if not os.path.isdir(repo_root):
        raise NotADirectoryError(f"repo_root does not exist: {repo_root}")

    tree_root = os.path.join(target, "tree")
    manifest_path = os.path.join(target, MANIFEST_FILE)

    relpaths = discover_scoped_files(repo_root, scope)
    relset = set(relpaths)
    # Only a GENUINE orphan may be pruned: out of scope AND not carried by an
    # overlay. See overlay_managed_paths() for why the second half is needed.
    managed = overlay_managed_paths(repo_root)
    existing = set(_tree_files(tree_root))
    pruned = sorted(p for p in existing if p not in relset and p not in managed)
    # files[] describes the MIRROR AS IT WILL BE, not merely what this run
    # discovered: everything written now, plus everything already there that
    # survives the prune (the overlay-managed half). Built from the discovered set
    # alone, a managed rule silently loses its `kind: rule` entry — measured
    # on a live pair as 6 -> 5, with one org rule dropping out.
    mirror_after = sorted(relset | (existing - set(pruned)))
    files_entries = manifest_files_entries(mirror_after, scope)

    existing_manifest = None
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, encoding="utf-8") as fh:
                loaded = yaml.safe_load(fh)
            if isinstance(loaded, dict):
                existing_manifest = loaded
        except yaml.YAMLError:
            existing_manifest = None
    manifest = build_manifest(existing_manifest, files_entries, scope)

    result = {
        "scope": scope,
        "repo_root": repo_root,
        "target": target,
        "tree_root": tree_root,
        "manifest_path": manifest_path,
        "copied": list(relpaths),
        "pruned": pruned,
        "files_entries": files_entries,
        "manifest": manifest,
        "dry_run": dry_run,
    }
    if dry_run:
        return result

    # 1) copy verbatim (source bytes → tree/<path>)
    for rel in relpaths:
        _write_bytes(os.path.join(tree_root, rel),
                     _read_bytes(os.path.join(repo_root, rel)))
    # 2) prune stale mirror files + emptied dirs
    for rel in pruned:
        stale = os.path.join(tree_root, rel)
        if os.path.exists(stale):
            os.remove(stale)
    _prune_empty_dirs(tree_root)
    # 3) regenerate the manifest
    _write_bytes(manifest_path, _dump_manifest(manifest, scope))
    # bootstrap .gitignore once (never clobber a hand-authored one)
    gitignore = os.path.join(target, ".gitignore")
    if not os.path.exists(gitignore):
        _write_bytes(gitignore, _GITIGNORE_BODY.encode("utf-8"))
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="overlay-export.py",
        description="Export scope-tagged live files into an overlay repo tree/ "
                    "and regenerate its manifest files[].",
    )
    ap.add_argument("--repo-root", default=".", help="Bridge instance root (default: .)")
    ap.add_argument("--target", required=True,
                    help="overlay repo dir to write (tree/ + overlay.manifest.yaml)")
    ap.add_argument("--scope", default=DEFAULT_SCOPE,
                    help=f"tier to export (default: {DEFAULT_SCOPE})")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the plan; write nothing")
    args = ap.parse_args(argv)

    if not os.path.isdir(args.repo_root):
        sys.stderr.write(f"ERROR: --repo-root {args.repo_root} is not a directory\n")
        return 1

    result = export_overlay(args.repo_root, args.target,
                            scope=args.scope, dry_run=args.dry_run)

    if args.dry_run:
        print(f"overlay-export (DRY-RUN): {len(result['copied'])} {args.scope} "
              f"file(s) would export to {result['tree_root']}")
        for rel in result["copied"]:
            print(f"  + tree/{rel}")
        for rel in result["pruned"]:
            print(f"  - tree/{rel} (stale, would prune)")
        print(f"  manifest files[]: {len(result['files_entries'])} rule entr(ies)")
    else:
        print(f"overlay-export: {len(result['copied'])} {args.scope} file(s) -> "
              f"{result['tree_root']}; pruned {len(result['pruned'])}; "
              f"manifest {result['manifest_path']} "
              f"(files[]={len(result['files_entries'])})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
