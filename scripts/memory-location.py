#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Resolve where Claude Code's auto memory lives for this repo, and manage
the move from the legacy hash path into a directory inside the repo.

THE SETTING. Claude Code reads `autoMemoryDirectory` from any settings scope
(project `.claude/settings.json`, local `.claude/settings.local.json`, or the
user's `~/.claude/settings.json`). The value must be an absolute path, or
start with `~/`; a relative value is silently ignored and the harness falls
back to its own default, `~/.claude/projects/<encoded-root>/memory` (the
absolute project path with every `/` replaced by `-`). The setting is keyed
to the git PROJECT: a value set in the main checkout also governs every
linked worktree and every subdirectory (session transcripts stay per cwd;
memory does not). See https://code.claude.com/docs/en/memory and
`docs/memory.md`.

THIS SCRIPT is the one resolver every CORE reader should call instead of
reconstructing that hash path by hand (the derivation used to be duplicated
in `scripts/okf-export.py`'s `default_memory_dir()`, and drifts silently the
moment an instance opts into an in-repo directory).

    python3 scripts/memory-location.py status [--json]
    python3 scripts/memory-location.py enable [--path work/memory] [--dry-run]
    python3 scripts/memory-location.py migrate [--dry-run] [--prefer-newer]
    python3 scripts/memory-location.py stub-legacy --yes
    python3 scripts/memory-location.py check [--strict]
    python3 scripts/memory-location.py index
    python3 scripts/memory-location.py get <name>
    python3 scripts/memory-location.py links [--json]

`index` and `get` are the harness-agnostic Phase 1 read (`rules/operations.md`):
any agent reads the index and fetches a fact by name, the way
`scripts/context-index.py` serves `ecosystem.yaml`. Inside Claude Code with auto
memory on, `index` prints a one-line note instead, since the harness already
loaded that same file. `links` counts facts whose session transcript is gone
(`docs/memory.md` § Retention); it reads only the local disk.

`resolve_memory_dir(start, home=None)` is the library entry point: it never
raises on a missing git binary, a missing settings file, or invalid JSON, and
returns `(Path, source, warnings)` where `source` is one of `setting:local`,
`setting:project`, `setting:user` or `legacy`.

Contract: `scripts/tests/test_memory_location.py`.
"""

from __future__ import annotations

import argparse
import filecmp
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

LOAD_LIMIT_LINES = 200
LOAD_LIMIT_BYTES = 25 * 1024  # "25 KB" per the harness's own load cap
HOOK_CHAR_LIMIT = 120
STUB_MARKER = "<!-- memory-location: pointer stub, see scripts/memory-location.py -->"
PRE_MOVE_SUFFIX = ".pre-move"

INDEX_LINE_RE = re.compile(
    r"^-\s*\[(?P<title>[^\]]*)\]\((?P<link>[^)]+)\)\s*(?:\u2014|\u2013|-|:)\s*(?P<hook>.*)$"
)
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+\.md)\)")


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def _git_common_dir(start: Path) -> Path | None:
    """Absolute `--git-common-dir` for `start`, or None if git could not answer.

    A linked worktree's common dir lives inside the MAIN checkout, so this is
    what makes a worktree resolve to the same settings as the checkout it was
    made from, per the harness's own project-keyed scoping.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    out = result.stdout.strip()
    return Path(out) if out else None


def repo_root_for(start) -> Path:
    """The repo root that owns memory for `start`: the main checkout's parent
    directory when `start` is inside a git project (worktree or not), or
    `start` itself, resolved, when it is not a git project at all."""
    common_dir = _git_common_dir(Path(start))
    if common_dir is not None:
        return common_dir.parent
    return Path(start).resolve()


def legacy_memory_dir(repo_root: Path, home: Path) -> Path:
    """The harness's own default: the leading `/` becomes a leading `-` too."""
    encoded = str(repo_root).replace("/", "-")
    return home / ".claude" / "projects" / encoded / "memory"


def _read_json_object(path: Path) -> tuple[dict | None, str | None]:
    """(parsed dict, None) on success; (None, warning) on a file that exists
    but is not a JSON object. Missing files are the caller's business."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None, None
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"{path} is not valid JSON, skipped: {exc}"
    if not isinstance(data, dict):
        return None, f"{path} does not hold a JSON object, skipped"
    return data, None


def resolve_memory_dir(start, home=None) -> tuple[Path, str, list[str]]:
    """(memory_dir, source, warnings). Never raises.

    Precedence: repo_root/.claude/settings.local.json, then
    repo_root/.claude/settings.json, then home/.claude/settings.json. The
    FIRST of those that contains the `autoMemoryDirectory` key decides,
    whether or not its value turns out to be usable; an unusable value falls
    through to the legacy hash path rather than trying the next file.
    """
    home = Path(home) if home is not None else Path.home()
    repo_root = repo_root_for(start)
    warnings: list[str] = []

    candidates = [
        (repo_root / ".claude" / "settings.local.json", "setting:local"),
        (repo_root / ".claude" / "settings.json", "setting:project"),
        (home / ".claude" / "settings.json", "setting:user"),
    ]

    for path, source in candidates:
        if not path.is_file():
            continue
        data, warning = _read_json_object(path)
        if data is None:
            if warning:
                warnings.append(warning)
            continue
        if "autoMemoryDirectory" not in data:
            continue
        value = data["autoMemoryDirectory"]
        if isinstance(value, str) and value:
            if value.startswith("~/"):
                return (home / value[2:]), source, warnings
            if Path(value).is_absolute():
                return Path(value), source, warnings
        warnings.append(
            f"autoMemoryDirectory={value} in {path} is not absolute; "
            "Claude Code ignores it silently"
        )
        break  # the first file WITH the key decides, valid or not

    return legacy_memory_dir(repo_root, home), "legacy", warnings


# ---------------------------------------------------------------------------
# Shared file-listing (migrate and status's drift preview use the same set)
# ---------------------------------------------------------------------------


def _top_level_files(directory: Path) -> dict[str, Path]:
    """{name: path} for top-level regular files. Directories, any name
    containing `.bak`, and the `MEMORY.md.pre-move` copy that stub-legacy
    keeps are excluded. Empty dict when `directory` is not a dir."""
    if not directory.is_dir():
        return {}
    out: dict[str, Path] = {}
    for entry in directory.iterdir():
        if not entry.is_file():
            continue
        if ".bak" in entry.name or entry.name.endswith(PRE_MOVE_SUFFIX):
            continue
        out[entry.name] = entry
    return out


def _count_md(directory: Path) -> int:
    if not directory.is_dir():
        return 0
    return sum(1 for p in directory.glob("*.md") if p.is_file())


def _is_stub(path: Path) -> bool:
    """True when `path` is a legacy MEMORY.md already replaced by stub-legacy."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            return handle.read(len(STUB_MARKER)) == STUB_MARKER
    except OSError:
        return False


def _migrate_plan(
    source_dir: Path, target_dir: Path, prefer_newer: bool
) -> tuple[list[str], list[str], list[str]]:
    """(to_copy, skipped, conflicts) file names, computed with zero writes.

    A source `MEMORY.md` that is itself a pointer stub (written by
    `stub-legacy`) is excluded from all three lists rather than treated as
    ordinary content: it is not the real index, and letting `--prefer-newer`
    copy it over the target (its mtime is always the newest thing around
    right after `stub-legacy` runs) would overwrite the real, already-migrated
    index with the pointer text.
    """
    source_files = _top_level_files(source_dir)
    target_files = _top_level_files(target_dir)

    stub_path = source_files.get("MEMORY.md")
    if stub_path is not None and _is_stub(stub_path):
        del source_files["MEMORY.md"]

    to_copy: list[str] = []
    skipped: list[str] = []
    conflicts: list[str] = []

    for name, src in sorted(source_files.items()):
        dst = target_files.get(name)
        if dst is None:
            to_copy.append(name)
            continue
        if filecmp.cmp(src, dst, shallow=False):
            skipped.append(name)
            continue
        if prefer_newer and src.stat().st_mtime > dst.stat().st_mtime:
            to_copy.append(name)
            continue
        conflicts.append(name)

    return to_copy, skipped, conflicts


# ---------------------------------------------------------------------------
# check: lint a resolved MEMORY.md
# ---------------------------------------------------------------------------


def lint_memory_index(memory_dir: Path) -> list[str]:
    """Violation strings for `memory_dir/MEMORY.md`. Empty list when the
    directory or the file itself is missing (nothing to lint yet)."""
    index_path = memory_dir / "MEMORY.md"
    if not memory_dir.is_dir() or not index_path.is_file():
        return []

    text = index_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    violations: list[str] = []

    if len(lines) > LOAD_LIMIT_LINES:
        violations.append(
            f"MEMORY.md has {len(lines)} lines, over the {LOAD_LIMIT_LINES}-line load limit"
        )
    byte_size = len(text.encode("utf-8"))
    if byte_size > LOAD_LIMIT_BYTES:
        violations.append(
            f"MEMORY.md is {byte_size} bytes, over the {LOAD_LIMIT_BYTES}-byte (25 KB) load limit"
        )

    for lineno, line in enumerate(lines, start=1):
        match = INDEX_LINE_RE.match(line)
        if not match or not match.group("link").endswith(".md"):
            continue
        hook = match.group("hook")
        if len(hook) > HOOK_CHAR_LIMIT:
            violations.append(
                f"MEMORY.md:{lineno} hook is {len(hook)} chars, over the "
                f"{HOOK_CHAR_LIMIT}-char cap: {match.group('title')!r}"
            )

    for lineno, line in enumerate(lines, start=1):
        for link in LINK_RE.findall(line):
            if "://" in link or link.startswith("/") or link.startswith("~"):
                continue
            if not (memory_dir / link).is_file():
                violations.append(f"MEMORY.md:{lineno} links to missing file: {link}")

    return violations


# ---------------------------------------------------------------------------
# check: coverage, is every fact reachable from an index?
# ---------------------------------------------------------------------------

INDEX_FILES = ("MEMORY.md", "MEMORY-ARCHIVE.md")
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]")
# Coverage reads a markdown link more leniently than the index lint: a
# `#section` anchor or a `"title"` after the target still reaches the file.
COVERAGE_LINK_RE = re.compile(r'\[[^\]]*\]\(([^)\s#]+\.md)(?:#[^)\s]*)?(?:\s+"[^"]*")?\)')


def _is_meta_file(name: str) -> bool:
    """MEMORY.md, MEMORY-ARCHIVE.md, README.md, PROVENANCE.md: an all-uppercase
    stem marks a file about the memory base, not a fact in it. A stem with no
    letter at all (`2026-10.md`) is not uppercase, so it stays a fact."""
    stem = name[:-3]
    return any(c.isalpha() for c in stem) and stem == stem.upper()


def coverage_report(memory_dir: Path) -> tuple[int, list[str]]:
    """(fact count, unreachable fact names, sorted).

    Reachability is transitive from MEMORY.md and MEMORY-ARCHIVE.md: a fact is
    reached by a relative `[..](file.md)` link or a `[[wikilink]]` (its `name:`
    slug or its file stem) in any file already reached. A wikilink from a fact
    nobody reaches reaches nothing.
    """
    files = {
        name: path
        for name, path in _top_level_files(memory_dir).items()
        if name.endswith(".md")
    }
    facts = {name for name in files if not _is_meta_file(name)}
    # File stems first, then slugs, both in sorted order: a wikilink resolves
    # the same way on every run, and a stem always wins over another fact's slug.
    by_key: dict[str, str] = {name[:-3]: name for name in sorted(facts)}
    for name in sorted(facts):
        slug = _frontmatter_name(files[name])
        if slug:
            by_key.setdefault(slug.strip(), name)

    reached: set[str] = set()
    queue = [name for name in INDEX_FILES if name in files]
    seen = set(queue)
    while queue:
        current = queue.pop()
        text = files[current].read_text(encoding="utf-8", errors="replace")
        targets = [link.removeprefix("./") for link in COVERAGE_LINK_RE.findall(text)]
        targets += [by_key.get(key.strip(), "") for key in WIKILINK_RE.findall(text)]
        for target in targets:
            if target in facts and target not in seen:
                seen.add(target)
                reached.add(target)
                queue.append(target)
    return len(facts), sorted(facts - reached)


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def build_status(repo_arg, home=None) -> dict:
    home = Path(home) if home is not None else Path.home()
    repo_root = repo_root_for(repo_arg)
    memory_dir, source, warnings = resolve_memory_dir(repo_arg, home)
    legacy_dir = legacy_memory_dir(repo_root, home)

    memory_files_set = _top_level_files(memory_dir)
    legacy_files_set = _top_level_files(legacy_dir)
    legacy_index = legacy_files_set.get("MEMORY.md")
    if legacy_index is not None and _is_stub(legacy_index):
        # a pointer stub is not drift: stub-legacy wrote it on purpose
        del legacy_files_set["MEMORY.md"]

    only_in_legacy = sorted(set(legacy_files_set) - set(memory_files_set))
    newer_in_legacy: list[str] = []
    for name in sorted(set(legacy_files_set) & set(memory_files_set)):
        legacy_path = legacy_files_set[name]
        memory_path = memory_files_set[name]
        if filecmp.cmp(legacy_path, memory_path, shallow=False):
            continue
        if legacy_path.stat().st_mtime > memory_path.stat().st_mtime:
            newer_in_legacy.append(name)

    index_path = memory_dir / "MEMORY.md"
    if index_path.is_file():
        index_text = index_path.read_text(encoding="utf-8", errors="replace")
        index_lines = len(index_text.splitlines())
        index_bytes = len(index_text.encode("utf-8"))
    else:
        index_lines = 0
        index_bytes = 0

    return {
        "memory_dir": str(memory_dir),
        "source": source,
        "legacy_dir": str(legacy_dir),
        "memory_dir_exists": memory_dir.is_dir(),
        "legacy_exists": legacy_dir.is_dir(),
        "memory_files": _count_md(memory_dir),
        "legacy_files": _count_md(legacy_dir),
        "only_in_legacy": only_in_legacy,
        "newer_in_legacy": newer_in_legacy,
        "index_lines": index_lines,
        "index_bytes": index_bytes,
        "index_within_load_limit": index_lines <= LOAD_LIMIT_LINES
        and index_bytes <= LOAD_LIMIT_BYTES,
        "warnings": warnings,
    }


def cmd_status(args) -> int:
    status = build_status(args.repo)
    if args.json:
        print(json.dumps(status, indent=2))
        return 0

    print(f"memory_dir:   {status['memory_dir']}  ({status['source']})")
    print(f"exists:       {status['memory_dir_exists']}, {status['memory_files']} fact file(s)")
    if status["source"] != "legacy":
        print(f"legacy_dir:   {status['legacy_dir']}")
        print(
            f"legacy:       exists={status['legacy_exists']}, "
            f"{status['legacy_files']} fact file(s)"
        )
        if status["only_in_legacy"]:
            print(f"only in legacy (never migrated): {', '.join(status['only_in_legacy'])}")
        if status["newer_in_legacy"]:
            print(f"newer in legacy (a running session wrote after migrate): "
                  f"{', '.join(status['newer_in_legacy'])}")
    print(
        f"MEMORY.md:    {status['index_lines']} lines, {status['index_bytes']} bytes, "
        f"within load limit: {status['index_within_load_limit']}"
    )
    for warning in status["warnings"]:
        print(f"warning: {warning}")
    return 0


# ---------------------------------------------------------------------------
# enable
# ---------------------------------------------------------------------------


def cmd_enable(args) -> int:
    repo_root = repo_root_for(args.repo)
    if args.path:
        if args.path.startswith("~/"):
            target = Path.home() / args.path[2:]
        else:
            target = Path(args.path)
            if not target.is_absolute():
                target = repo_root / target
    else:
        target = repo_root / "work" / "memory"

    settings_path = repo_root / ".claude" / "settings.local.json"
    existing, warning = (
        _read_json_object(settings_path) if settings_path.is_file() else ({}, None)
    )
    if settings_path.is_file() and existing is None:
        print(f"error: {warning or f'{settings_path} is not a JSON object'}", file=sys.stderr)
        return 2

    if _is_git_repo(repo_root):
        rel = str(settings_path.relative_to(repo_root))
        ignored = _check_ignore(repo_root, rel)
        if ignored is False:
            print(
                f"error: {rel} is NOT git-ignored in this repo. Refusing to write an "
                "absolute path into a file that could be committed. Add it to "
                ".gitignore first (see rules/secret-placement.md).",
                file=sys.stderr,
            )
            return 2

    updated = dict(existing)
    already = updated.get("autoMemoryDirectory") == str(target)
    updated["autoMemoryDirectory"] = str(target)

    if already:
        print(f"unchanged: autoMemoryDirectory already {target} in {settings_path}")
        return 0

    if args.dry_run:
        print(f"would write autoMemoryDirectory={target} to {settings_path}")
        return 0

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(updated, indent=2) + "\n", encoding="utf-8")
    print(f"wrote autoMemoryDirectory={target} to {settings_path}")
    print(
        "note: a session that was already running can keep writing to its old "
        "memory directory. Run 'migrate' now, restart sessions, then run it again."
    )
    return 0


def _is_git_repo(root: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


def _check_ignore(root: Path, rel_path: str) -> bool | None:
    """True/False when git can answer; None on any git-level ambiguity, in
    which case the caller does not refuse on it (fail open on the tool, not
    on the safety property itself)."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "check-ignore", "-q", rel_path],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    return None


# ---------------------------------------------------------------------------
# migrate
# ---------------------------------------------------------------------------


def cmd_migrate(args) -> int:
    repo_root = repo_root_for(args.repo)
    home = Path.home()
    memory_dir, source, _warnings = resolve_memory_dir(args.repo, home)
    legacy_dir = legacy_memory_dir(repo_root, home)

    if source == "legacy":
        print(
            "error: no autoMemoryDirectory is configured, so there is nothing to "
            "migrate INTO. Run 'enable' first.",
            file=sys.stderr,
        )
        return 2
    if not legacy_dir.is_dir():
        print(f"error: legacy directory does not exist: {legacy_dir}", file=sys.stderr)
        return 2

    to_copy, skipped, conflicts = _migrate_plan(legacy_dir, memory_dir, args.prefer_newer)

    if args.dry_run:
        print(f"would copy {len(to_copy)}, skip {len(skipped)}, conflict {len(conflicts)}")
        if conflicts:
            print(f"conflicts: {', '.join(sorted(conflicts))}")
        return 1 if conflicts else 0

    memory_dir.mkdir(parents=True, exist_ok=True)
    for name in to_copy:
        shutil.copy2(legacy_dir / name, memory_dir / name)

    print(f"copied {len(to_copy)}, skipped {len(skipped)} (identical), "
          f"{len(conflicts)} conflict(s)")
    if conflicts:
        print(f"conflicts (neither copied nor touched, resolve by hand): "
              f"{', '.join(sorted(conflicts))}")
        print("legacy directory left untouched; safe to re-run 'migrate' later.")
    return 1 if conflicts else 0


# ---------------------------------------------------------------------------
# stub-legacy
# ---------------------------------------------------------------------------


def cmd_stub_legacy(args) -> int:
    if not args.yes:
        print("error: refusing without --yes (this rewrites the legacy MEMORY.md)",
              file=sys.stderr)
        return 2

    repo_root = repo_root_for(args.repo)
    home = Path.home()
    memory_dir, source, _warnings = resolve_memory_dir(args.repo, home)
    legacy_dir = legacy_memory_dir(repo_root, home)

    if source == "legacy":
        print("error: autoMemoryDirectory is not configured, memory IS still the "
              "legacy directory. Nothing to point away from.", file=sys.stderr)
        return 2

    legacy_index = legacy_dir / "MEMORY.md"
    if legacy_index.is_file():
        existing = legacy_index.read_text(encoding="utf-8", errors="replace")
        if existing.startswith(STUB_MARKER):
            print(f"error: {legacy_index} is already a pointer stub.", file=sys.stderr)
            return 2

    to_copy, _skipped, conflicts = _migrate_plan(legacy_dir, memory_dir, prefer_newer=False)
    if to_copy or conflicts:
        print(
            "error: a dry-run migrate would still copy or conflict on "
            f"{len(to_copy) + len(conflicts)} file(s); run 'migrate' (and resolve any "
            "conflicts) before stubbing the legacy index.",
            file=sys.stderr,
        )
        if to_copy:
            print(f"  would copy: {', '.join(sorted(to_copy))}", file=sys.stderr)
        if conflicts:
            print(f"  conflicts:  {', '.join(sorted(conflicts))}", file=sys.stderr)
        return 2

    if not legacy_dir.is_dir():
        print(f"error: legacy directory does not exist: {legacy_dir}", file=sys.stderr)
        return 2

    pre_move = legacy_dir / f"MEMORY.md{PRE_MOVE_SUFFIX}"
    if legacy_index.is_file():
        legacy_index.replace(pre_move)

    stub = (
        f"{STUB_MARKER}\n"
        "# Memory has moved\n\n"
        "Auto memory for this repo now lives at:\n\n"
        f"    {memory_dir}\n\n"
        "This file is a pointer, not the index; nothing reads it. The previous "
        f"index is kept next to it as `MEMORY.md{PRE_MOVE_SUFFIX}` for reference.\n"
    )
    legacy_index.write_text(stub, encoding="utf-8")
    print(f"wrote pointer stub to {legacy_index} (previous index kept as {pre_move.name})")
    return 0


STUB_LEGACY_HELP = (
    "Run this only after every session that was started BEFORE 'enable' has "
    "ended: such a session is still writing to the legacy directory and would "
    "rewrite MEMORY.md there on its next save, undoing the stub."
)


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------


def cmd_check(args) -> int:
    memory_dir, _source, _warnings = resolve_memory_dir(args.repo)
    violations = lint_memory_index(memory_dir)
    for violation in violations:
        print(violation, file=sys.stderr)
    if violations:
        print(f"memory-location check: {len(violations)} finding(s)", file=sys.stderr)

    facts, unreachable = coverage_report(memory_dir)
    for name in unreachable:
        print(f"unreachable: {name}", file=sys.stderr)
    if unreachable:
        level = "error" if args.strict else "warning"
        hint = "" if args.strict else ", --strict fails on it"
        print(
            f"memory-location check {level}: {len(unreachable)} of {facts} fact file(s) "
            "unreachable from MEMORY.md, MEMORY-ARCHIVE.md or a [[wikilink]] "
            f"(docs/memory.md § Coverage{hint})",
            file=sys.stderr,
        )
    return 1 if violations or (args.strict and unreachable) else 0


# ---------------------------------------------------------------------------
# Settings lookup shared by index, get and links
# ---------------------------------------------------------------------------

BRIDGE_MEMORY_DIR = Path("work") / "memory"


def _claude_dir(home: Path) -> Path:
    """The harness's config dir: `CLAUDE_CONFIG_DIR` when set, else ~/.claude."""
    override = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(override).expanduser() if override else home / ".claude"


def _first_setting(repo_root: Path, home: Path, key: str):
    """(value, source) from the first settings file holding `key`, same
    precedence as resolve_memory_dir; (None, "default") when none does."""
    for path, source in (
        (repo_root / ".claude" / "settings.local.json", "setting:local"),
        (repo_root / ".claude" / "settings.json", "setting:project"),
        (_claude_dir(home) / "settings.json", "setting:user"),
    ):
        if not path.is_file():
            continue
        data, _warning = _read_json_object(path)
        if data is not None and key in data:
            return data[key], source
    return None, "default"


def resolve_read_dir(start, home=None) -> tuple[Path, str, list[str]]:
    """Where a READER finds the memory base, on any harness.

    Same as resolve_memory_dir while a setting names a directory. Without
    one, `work/memory/` wins when it exists (source "bridge"): that is the
    Bridge-owned location, and a fresh clone never carries the gitignored
    setting. Only then the legacy harness path. resolve_memory_dir itself
    stays unchanged, because migrate and stub-legacy mean "what the harness
    writes to", which is still the legacy path until `enable` runs.
    """
    home = Path(home) if home is not None else Path.home()
    memory_dir, source, warnings = resolve_memory_dir(start, home)
    if source == "legacy":
        bridge_dir = repo_root_for(start) / BRIDGE_MEMORY_DIR
        if bridge_dir.is_dir():
            return bridge_dir, "bridge", warnings
    return memory_dir, source, warnings


def _harness_already_loaded(start, home: Path, read_dir: Path) -> bool:
    """True when Claude Code has already put this exact MEMORY.md into the
    session, in full. A heuristic: `CLAUDECODE` is also set in sub-agent and
    `claude -p` shells, so a false "already loaded" is possible there."""
    if not os.environ.get("CLAUDECODE"):
        return False
    if os.environ.get("CLAUDE_CODE_DISABLE_AUTO_MEMORY", "").lower() in ("1", "true"):
        return False
    repo_root = repo_root_for(start)
    enabled, _source = _first_setting(repo_root, home, "autoMemoryEnabled")
    if enabled is False:
        return False
    harness_dir, _source, _warnings = resolve_memory_dir(start, home)
    if harness_dir != read_dir:
        return False  # the harness reads its legacy dir, not this one
    # an oversized index is loaded truncated, so its tail was never seen
    return not any("load limit" in v for v in lint_memory_index(read_dir))


# ---------------------------------------------------------------------------
# index / get: the Phase 1 read that works on any harness
# ---------------------------------------------------------------------------


def cmd_index(args) -> int:
    home = Path.home()
    memory_dir, _source, _warnings = resolve_read_dir(args.repo, home)
    index_path = memory_dir / "MEMORY.md"
    if not index_path.is_file():
        return 0
    if _harness_already_loaded(args.repo, home, memory_dir):
        print(f"memory index already loaded by Claude Code from {memory_dir}; "
              "fetch a fact with: python3 scripts/memory-location.py get <name>")
        return 0
    sys.stdout.write(index_path.read_text(encoding="utf-8", errors="replace"))
    return 0


def _frontmatter_name(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if not text.startswith("---"):
        return None
    match = re.search(r"^name:\s*['\"]?([^'\"\n]+?)['\"]?\s*$", text.split("\n---", 1)[0], re.M)
    return match.group(1) if match else None


def _inside(path: Path, directory: Path) -> bool:
    try:
        return path.resolve().is_relative_to(directory.resolve())
    except OSError:
        return False


def cmd_get(args) -> int:
    memory_dir, _source, _warnings = resolve_read_dir(args.repo)
    key = args.name
    found: Path | None = None
    if "/" not in key and "\\" not in key and ".." not in key and memory_dir.is_dir():
        for candidate in (key, f"{key}.md"):
            if (memory_dir / candidate).is_file():
                found = memory_dir / candidate
                break
        if found is None:
            for path in sorted(memory_dir.glob("*.md")):
                if _frontmatter_name(path) == key:
                    found = path
                    break
    if found is not None and not _inside(found, memory_dir):
        print(f"refused: {found.name} points outside {memory_dir}", file=sys.stderr)
        return 1
    if found is None:
        print(f"no memory fact named {key!r} in {memory_dir}", file=sys.stderr)
        return 1
    sys.stdout.write(found.read_text(encoding="utf-8", errors="replace"))
    return 0


# ---------------------------------------------------------------------------
# links: do the session links in memory facts still resolve?
# ---------------------------------------------------------------------------

DEFAULT_RETENTION_DAYS = 30  # Claude Code's cleanupPeriodDays default
UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
SESSION_LINK_RE = re.compile(rf"originSessionId:\s*['\"]?({UUID})|({UUID})\.jsonl", re.I)
FACT_FILE_RE = re.compile(r"^(user|feedback|project|reference)_.+\.md$")
DECLARED_RETENTION_RE = re.compile(r"^  transcript_retention_days:\s*['\"]?(\d+)['\"]?\s*(?:#.*)?$")


def _declared_retention(config: Path) -> int | None:
    """`work.transcript_retention_days` from bridge-config.yaml, read without
    a YAML dependency: only a two-space key inside the top-level `work:` block."""
    in_work = False
    for line in config.read_text(encoding="utf-8", errors="replace").splitlines():
        if line and not line[0].isspace() and not line.startswith("#"):
            in_work = line.split("#", 1)[0].strip() == "work:"
            continue
        if in_work:
            match = DECLARED_RETENTION_RE.match(line)
            if match:
                return int(match.group(1))
    return None


def build_links(repo_arg, home=None) -> dict:
    home = Path(home) if home is not None else Path.home()
    repo_root = repo_root_for(repo_arg)
    memory_dir, _source, warnings = resolve_read_dir(repo_arg, home)

    projects = _claude_dir(home) / "projects"
    transcripts = {p.stem.lower() for p in projects.glob("*/*.jsonl")}
    facts = sorted(p for p in memory_dir.glob("*.md") if FACT_FILE_RE.match(p.name))
    linked: list[str] = []
    unresolved: list[str] = []
    for path in facts:
        text = path.read_text(encoding="utf-8", errors="replace")
        ids = {(a or b).lower() for a, b in SESSION_LINK_RE.findall(text)}
        if not ids:
            continue
        linked.append(path.name)
        if not ids & transcripts:
            unresolved.append(path.name)

    value, retention_source = _first_setting(repo_root, home, "cleanupPeriodDays")
    retention = value if isinstance(value, int) and not isinstance(value, bool) else None
    if retention is None:
        if value is not None:
            warnings.append(f"cleanupPeriodDays={value!r} is not a whole number; "
                            f"assuming the default of {DEFAULT_RETENTION_DAYS}")
        retention, retention_source = DEFAULT_RETENTION_DAYS, "default"

    declared = None
    config = repo_root / "bridge-config.yaml"
    if config.is_file():
        declared = _declared_retention(config)
        if declared is not None and declared != retention:
            warnings.append(
                f"bridge-config.yaml declares work.transcript_retention_days: {declared}, "
                f"but the harness keeps transcripts {retention} days ({retention_source})"
            )

    return {
        "memory_dir": str(memory_dir),
        "files": len(facts),
        "linked": len(linked),
        "unresolved": unresolved,
        "retention_days": retention,
        "retention_source": retention_source,
        "declared_retention_days": declared,
        "warnings": warnings,
    }


def cmd_links(args) -> int:
    report = build_links(args.repo)
    if args.json:
        print(json.dumps(report, indent=2))
        return 0
    print(f"{report['linked']} of {report['files']} memory files carry a session link, "
          f"{len(report['unresolved'])} of {report['linked']} unresolved")
    for name in report["unresolved"]:
        print(f"  unresolved: {name}")
    print(f"transcript retention: {report['retention_days']} days ({report['retention_source']}); "
          "a session link is only guaranteed to resolve inside that window")
    for warning in report["warnings"]:
        print(f"warning: {warning}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="memory-location",
        description="Resolve and manage Claude Code's autoMemoryDirectory for this repo.",
    )
    parser.add_argument("--repo", default=".", help="repo path (default: cwd)")
    sub = parser.add_subparsers(dest="command", required=True)

    st = sub.add_parser("status", help="where memory resolves to today, and drift vs legacy")
    st.add_argument("--json", action="store_true", help="machine-readable output")
    st.set_defaults(func=cmd_status)

    en = sub.add_parser("enable", help="write autoMemoryDirectory into settings.local.json")
    en.add_argument(
        "--path",
        help="target dir: relative to --repo, absolute, or ~/-prefixed (default: work/memory)",
    )
    en.add_argument("--dry-run", action="store_true", help="report only, no write")
    en.set_defaults(func=cmd_enable)

    mi = sub.add_parser("migrate", help="copy legacy fact files into the resolved directory")
    mi.add_argument("--dry-run", action="store_true", help="report only, no copy")
    mi.add_argument("--prefer-newer", action="store_true",
                     help="on a conflict, copy when the legacy file is the newer one")
    mi.set_defaults(func=cmd_migrate)

    su = sub.add_parser(
        "stub-legacy",
        help="replace the legacy MEMORY.md with a pointer stub",
        description=STUB_LEGACY_HELP,
        epilog=STUB_LEGACY_HELP,
    )
    su.add_argument("--yes", action="store_true", help="required to actually write")
    su.set_defaults(func=cmd_stub_legacy)

    ch = sub.add_parser(
        "check",
        help="lint the resolved MEMORY.md and warn on fact files no index reaches",
    )
    ch.add_argument("--strict", action="store_true",
                    help="exit 1 when a fact file is unreachable, not just warn")
    ch.set_defaults(func=cmd_check)

    ix = sub.add_parser(
        "index",
        help="print the resolved MEMORY.md (Phase 1 read), or a one-line note when "
             "Claude Code already loaded it",
    )
    ix.set_defaults(func=cmd_index)

    ge = sub.add_parser("get", help="print one fact by file name or frontmatter name")
    ge.add_argument("name", help="fact file name (with or without .md) or its name: slug")
    ge.set_defaults(func=cmd_get)

    li = sub.add_parser(
        "links", help="count memory facts whose session transcript no longer exists (offline)"
    )
    li.add_argument("--json", action="store_true", help="machine-readable output")
    li.set_defaults(func=cmd_links)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
