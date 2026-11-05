#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""migrate-kernel.py: remove the keys kernel/manifest.yaml retires, once.

Two kinds of leftover, both listed in kernel/manifest.yaml:

  * `retired:` a top-level key nothing reads any more but a session still
    carries; it is removed
  * `moved:` a kernel path that moved; the instance's own live files that still
    name the old path are rewritten (CORE files come from upstream, records of
    the past and code are never edited, as in scripts/migrate-docs-tier.py)

A retired key is a declaration nothing reads any more but a session still
carries. The first one is `work_system` in ecosystem.yaml: it named where the
work log and the board live, no script read it (the switch is `work.enabled` in
bridge-config.yaml, the paths are in kernel/manifest.yaml), and the registry
card showed it to every session at start. kernel/manifest.yaml lists such keys
under `retired:`, scripts/check-kernel.py names each one a file still carries,
and this script removes them (docs/kernel.md, docs/updating.md).

Only a top-level key is removed, with its indented block and the comment lines
directly above it. Every other byte of the file stays as it was, comments
included. Stdlib only.

Usage:
  python3 scripts/migrate-kernel.py            # dry run: name what would go
  python3 scripts/migrate-kernel.py --write    # remove it
  python3 scripts/migrate-kernel.py --check    # exit 1 while a retired key is left

Exit codes: 0 done or nothing to do (dry run always 0) · 1 --check found work ·
2 setup error.
"""
from __future__ import annotations

import argparse
import fnmatch
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST = "kernel/manifest.yaml"


@dataclass(frozen=True)
class Retired:
    file: str
    key: str
    reason: str
    fix: str
    pattern: str = ""   # set for a card edit in context-budget.user.yaml: whose card


def _manifest_list(root: Path, name: str, fields: tuple[str, ...]) -> list[dict]:
    """A top-level list of flat mappings in the manifest.

    PyYAML when it is there, the reader check-kernel.py uses too; without it a
    small line reader that takes both list styles (`  - x:` and `- x:`) and
    drops a trailing `# comment`.
    """
    path = root / MANIFEST
    if not path.is_file():
        return []
    try:
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return [{k: str(v) for k, v in item.items()} for item in data.get(name) or []
                if isinstance(item, dict)]
    except ImportError:
        pass
    items: list[dict] = []
    inside = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if re.match(rf"^{name}:\s*$", line):
            inside = True
            continue
        if inside and line and not line[0].isspace() and not line.startswith(("#", "- ")):
            break
        if not inside:
            continue
        m = re.match(rf"^\s*(-\s+)?({'|'.join(fields)}):\s*(.*?)\s*(?:\s#.*)?$", line)
        if not m:
            continue
        if m.group(1):
            items.append({})
        if items:
            items[-1][m.group(2)] = m.group(3).strip("\"'")
    return items


def _retired(root: Path) -> list[Retired]:
    items = _manifest_list(root, "retired", ("file", "key", "reason", "fix"))
    return [Retired(i.get("file", ""), i.get("key", ""), i.get("reason", ""), i.get("fix", ""))
            for i in items if i.get("file") and i.get("key")]


# ------------------------------------------------------------ moved paths --

@dataclass
class MovePlan:
    moves: list[tuple[str, str]]
    files: list[str]


_MODULES: dict[str, object] = {}


def _load(name: str, rel: str):
    if name in _MODULES:
        return _MODULES[name]
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, HERE / rel)
    if spec is None or spec.loader is None:
        raise SystemExit(f"error: scripts/{rel} not found beside this script")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    _MODULES[name] = mod
    return mod


def _io_read(path: Path) -> str:
    with open(path, encoding="utf-8", newline="") as f:   # keep CRLF as it is
        return f.read()


def _io_write(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def _rewrite_lines(text: str, rel: str, moves: list[tuple[str, str]], mdt) -> str:
    """Follow each move line by line, and leave a line that already names the
    new path alone: it describes the move ("moves A to B") and would read
    "moves B to B" afterwards."""
    out = []
    for line in text.splitlines(keepends=True):
        for old, new in moves:
            if new not in line:
                line = mdt._inbound(line, rel, old, new)
        out.append(line)
    return "".join(out)


def plan_moves(root: Path, moves: list[tuple[str, str]] | None = None) -> MovePlan:
    """The instance's own live files that still name a kernel path that moved.

    CORE files are upstream's to update, records of the past stay as written
    and code is never edited: the same rules as scripts/migrate-docs-tier.py,
    whose link rewriting this reuses.
    """
    root = Path(root)
    if moves is None:
        moves = [(m["old"], m["new"]) for m in _manifest_list(root, "moved", ("old", "new"))
                 if m.get("old") and m.get("new")]
    if not moves:
        return MovePlan([], [])
    mdt = _load("migrate_docs_tier_for_kernel", "migrate-docs-tier.py")
    router = _load("categorize_commits_for_migrate_kernel", "categorize-commits.py")
    files = []
    for rel in mdt._files(root):
        if Path(rel).suffix not in mdt.REWRITE_SUFFIXES or mdt._is_history(rel):
            continue
        text = mdt._read(root, rel)
        if not text or _rewrite_lines(text, rel, moves, mdt) == text:
            continue
        here = os.getcwd()
        try:
            os.chdir(root)
            tier = router.classify_file(rel)
        finally:
            os.chdir(here)
        if tier != "core":
            files.append(rel)
    return MovePlan(moves, files)


def apply_moves(root: Path, the_plan: MovePlan) -> list[str]:
    root = Path(root)
    if not the_plan.files:
        return []
    mdt = _load("migrate_docs_tier_for_kernel", "migrate-docs-tier.py")
    changed = []
    for rel in the_plan.files:
        text = _io_read(root / rel)
        new = _rewrite_lines(text, rel, the_plan.moves, mdt)
        if new != text:
            _io_write(root / rel, new)
            changed.append(rel)
    return changed


def _block(lines: list[str], key: str) -> tuple[int, int] | None:
    """[start, end) of a top-level key: its comment lines above, itself, its body."""
    pattern = re.compile(rf"^{re.escape(key)}:")
    for i, line in enumerate(lines):
        if not pattern.match(line):
            continue
        start = i
        while (start > 0 and lines[start - 1].startswith("#")
               and not lines[start - 1].startswith("# yaml-language-server")):
            start -= 1
        end = i + 1
        while end < len(lines) and (not lines[end].strip() or lines[end][0].isspace()):
            end += 1
        while end > i + 1 and not lines[end - 1].strip():
            end -= 1   # trailing blank lines belong to the gap, not the block
        return start, end
    return None


USER_BUDGET = "context-budget.user.yaml"


def _tier(root: Path, rel: str) -> str:
    router = _load("categorize_commits_for_migrate_kernel", "categorize-commits.py")
    here = os.getcwd()
    try:
        os.chdir(root)
        return router.classify_file(rel)
    finally:
        os.chdir(here)


def _card_keep_edits(lines: list[str], pattern: str, key: str) -> list[str] | None:
    """The user budget with `key` dropped from the card `keep:` of every item
    whose name matches `pattern`; None when nothing would change."""
    out: list[str] = []
    item = None
    in_keep = False
    changed = False
    for line in lines:
        m = re.match(r"^  ([^\s#][^:]*):\s*$", line)
        if m:
            item = m.group(1).strip().strip("\"'")
            in_keep = False
        mine = item is not None and fnmatch.fnmatchcase(item, pattern)
        flow = re.match(r"^(\s+keep:\s*\[)(.*)(\].*)$", line)
        if mine and flow:
            values = [v.strip() for v in flow.group(2).split(",") if v.strip()]
            if key in values:
                line = flow.group(1) + ", ".join(v for v in values if v != key) + flow.group(3)
                changed = True
            out.append(line)
            continue
        if mine and re.match(r"^\s+keep:\s*$", line):
            in_keep = True
            out.append(line)
            continue
        if in_keep:
            entry = re.match(r"^\s+-\s*(\S+)\s*$", line)
            if entry:
                if entry.group(1).strip("\"'") == key:
                    changed = True
                    continue
            else:
                in_keep = False
        out.append(line)
    return out if changed else None


def plan(root: Path) -> list[Retired]:
    """One hit per file that still carries a retired key.

    `file` may be a glob, so every registry is covered. A CORE file (the template
    ecosystem.example.yaml) is upstream's to fix and never edited here. The
    instance's own card in context-budget.user.yaml is a hit too when it still
    keeps the key: context-index.py --check fails on a kept key the file lacks.
    """
    root = Path(root)
    found = []
    budget = root / USER_BUDGET
    for item in _retired(root):
        for path in sorted(p for p in root.glob(item.file) if p.is_file()):
            rel = path.relative_to(root).as_posix()
            if _tier(root, rel) == "core":
                continue
            if _block(_io_read(path).split("\n"), item.key):
                found.append(Retired(rel, item.key, item.reason, item.fix))
        if budget.is_file() and _card_keep_edits(
                _io_read(budget).split("\n"), item.file, item.key) is not None:
            found.append(Retired(USER_BUDGET, item.key, f"the card of {item.file} keeps it",
                                 item.fix, pattern=item.file))
    return found


REFUSED: list[str] = []   # files apply() left alone, with the reason


def _same_but(before: str, after: str, key: str | None, pattern: str = "") -> bool:
    """True when `after` is valid YAML equal to `before` minus what was meant to go.

    Without PyYAML the edit is trusted, as the line rules alone decide it.
    """
    try:
        import yaml
    except ImportError:
        return True
    try:
        old, new = yaml.safe_load(before) or {}, yaml.safe_load(after) or {}
    except yaml.YAMLError:
        return False
    if not isinstance(old, dict) or not isinstance(new, dict):
        return False
    if pattern:  # a card edit: only `key` may leave a keep list
        for name, spec in (old.get("items") or {}).items():
            keep = ((spec or {}).get("card") or {}).get("keep")
            if isinstance(keep, list) and fnmatch.fnmatchcase(str(name), pattern):
                spec["card"]["keep"] = [k for k in keep if k != key]
        return old == new
    old.pop(key, None)
    return old == new


def apply(root: Path, the_plan: list[Retired]) -> list[str]:
    root = Path(root)
    changed = []
    for item in the_plan:
        path = root / item.file
        before = _io_read(path)
        lines = before.split("\n")
        if item.pattern:
            edited = _card_keep_edits(lines, item.pattern, item.key)
            if edited is not None:
                after = "\n".join(edited)
                if not _same_but(before, after, item.key, item.pattern):
                    REFUSED.append(f"{item.file}: the card edit would change more than {item.key}")
                    continue
                _io_write(path, after)
                changed.append(item.file)
            continue
        span = _block(lines, item.key)
        if span is None:
            continue
        start, end = span
        del lines[start:end]
        # Two gaps meet where the block was: keep one.
        if 0 < start < len(lines) and not lines[start - 1].strip() and not lines[start].strip():
            del lines[start]
        after = "\n".join(lines)
        if not _same_but(before, after, item.key):
            REFUSED.append(f"{item.file}: removing {item.key} would change other keys too "
                           "(an odd layout); remove it by hand")
            continue
        _io_write(path, after)
        changed.append(item.file)
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Remove the keys kernel/manifest.yaml retires")
    parser.add_argument("--repo-root", default=str(HERE.parent))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="remove the retired keys")
    mode.add_argument("--check", action="store_true", help="exit 1 while a retired key is left")
    args = parser.parse_args(argv)
    root = Path(args.repo_root).resolve()
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 2
    the_plan = plan(root)
    moves = plan_moves(root)
    if not the_plan and not moves.files:
        print("kernel: no retired key and no moved kernel path left in this tree, nothing to do")
        return 0
    for item in the_plan:
        print(f"  retire  {item.file}: {item.key} ({item.reason})")
    for rel in moves.files:
        print(f"  follow  {rel}: names a kernel path that moved "
              f"({', '.join(f'{o} -> {n}' for o, n in moves.moves)})")
    if args.check:
        return 1
    if not args.write:
        print("dry run: nothing changed. Run again with --write.")
        return 0
    for rel in apply(root, the_plan) + apply_moves(root, moves):
        print(f"  wrote {rel}")
    for note in REFUSED:
        print(f"  left  {note}")
    print("done: review with `git diff`, then commit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
