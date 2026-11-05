#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""migrate-docs-tier.py: move a fork's own docs into their tier folder, once.

`docs/` ships wholesale as core. Since 2026-11-05 it is tiered by folder, the
way `rules/` is: a doc of another tier lives in `docs/user/`, `docs/org/` or
`docs/personal/`, and the folder decides (docs/kernel.md, docs/extension-model.md
§ Scope model). A fork that kept its own docs in `docs/` with a `scope:` line
meets `validate-bridge.py` red on its next upstream merge, and the daily update
job files an inbox item for it. This script is the fix that message names:

  * every `docs/**/*.md` outside the tier folders whose `scope:` line declares
    user (or private), org or personal moves to `docs/<tier>/<same path>`
    (`git mv` when the file is tracked, so the history follows it); so does
    `docs/applications.md`, the one user doc the router still knows by name
  * its own relative links and its frontmatter `related:` paths are rewritten
    for the new location; URLs and in-page anchors stay as they are
  * every link elsewhere that resolved to the old path is rewritten to the new
    one, in the instance's own Markdown, YAML and plain-text files, in
    whichever form it used (repo-relative `docs/x.md`, or relative to the file
    that links it). That includes `identity/agent/` and `work/memory/` where
    git ignores them, since every session reads them
  * a CORE file is never edited: it comes from upstream, and a local edit would
    conflict with the next merge. One that names the moved doc is listed
  * code is never edited: a script or page that still names the old path is
    listed, for a person to look at
  * records of the past are never edited either: the work log and every other
    `log.md`, closed tasks (`work/done/`), archives, reports (`work/reports/`),
    a task's or stream's deliverables, the inbox, and any file whose name
    or folder starts with a date say what was true when they were written

Nothing is guessed. An unknown `scope:` token, a line that disagrees with a tier
folder, or a target that already exists is reported and the file stays put.

Usage:
  python3 scripts/migrate-docs-tier.py            # dry run: print the plan, change nothing
  python3 scripts/migrate-docs-tier.py --write    # move and rewrite
  python3 scripts/migrate-docs-tier.py --check    # exit 1 while anything is left to do

Exit codes: 0 done or nothing to do (dry run always 0) · 1 --check found work ·
2 setup error.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import posixpath
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
REWRITE_SUFFIXES = {".md", ".markdown", ".yaml", ".yml", ".txt"}
SCAN_SUFFIXES = REWRITE_SUFFIXES | {".py", ".sh", ".js", ".mjs", ".ts", ".html", ".json", ".toml"}
SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__"}
# Records of the past: the work log, closed tasks, archives. They say what was
# true when they were written, so a path in them is never rewritten; a row that
# named the old place still names it, and the report lists the file.
HISTORY = ("work/log.md", "work/done/", "work/archive/")
TIER_FOLDERS = ("user", "org", "personal")


@dataclass
class Move:
    source: str      # repo-relative, posix
    target: str
    declared: str


@dataclass
class Plan:
    moves: list[Move] = field(default_factory=list)
    unplaceable: list[tuple[str, str]] = field(default_factory=list)
    mentions_left: list[str] = field(default_factory=list)
    history_left: list[str] = field(default_factory=list)
    core_left: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)

    @property
    def pending(self) -> bool:
        return bool(self.moves or self.unplaceable)


def _router():
    spec = importlib.util.spec_from_file_location("categorize_commits_mdt", HERE / "categorize-commits.py")
    if spec is None or spec.loader is None:
        raise SystemExit("error: scripts/categorize-commits.py not found beside this script")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _is_git(root: Path) -> bool:
    return subprocess.run(["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
                          capture_output=True, text=True).returncode == 0


# Instance files a fork may keep out of git (the root .gitignore ignores them until
# user-data.py arms a private origin) that are still live: the always-on files a
# session imports and the memory it recalls. A link in them must follow a move
# like a link in a tracked file, or every session keeps reading the old path.
LIVE_IGNORED = ("identity/agent", "work/memory")
# Generated files that name paths but are never edited by hand: the overlay and
# workspace engines rewrite them on their next run.
GENERATED = frozenset({"overlays.lock.yaml", "workspaces.lock.yaml"})
OVERLAY_LOCK = "overlays.lock.yaml"


def overlay_owned(root: Path) -> dict[str, str]:
    """dest path -> overlay name, for every file an org overlay materializes.

    A migration may still edit such a file (it is the instance's copy), but the
    overlay's source keeps the old text: the next sync reports a local edit, or
    brings the old text back to a fresh subscriber. The caller names them, so
    the same change reaches the overlay.
    """
    owned: dict[str, str] = {}
    try:
        text = (Path(root) / OVERLAY_LOCK).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return owned
    name = None
    for line in text.splitlines():
        m = re.match(r"^  ([^\s#][^:]*):\s*$", line)
        if m:
            name = m.group(1).strip().strip("\"'")
            continue
        d = re.match(r"^\s+dest:\s*['\"]?([^'\"#]+?)['\"]?\s*(#.*)?$", line)
        if d and name:
            owned[d.group(1).strip()] = name
    return owned


def overlay_notes(root: Path, changed: list[str]) -> list[str]:
    owned = overlay_owned(root)
    return [f"  overlay {rel} comes from overlay '{owned[rel]}': make the same change in "
            "that overlay's source, or its next sync reports a local edit and a fresh "
            "subscriber gets the old text back"
            for rel in changed if rel in owned]


def _files(root: Path) -> list[str]:
    """Every file a link could live in: tracked plus untracked-not-ignored in git,
    plus the live instance files in LIVE_IGNORED even where git ignores them."""
    if _is_git(root):
        out = subprocess.run(["git", "-C", str(root), "ls-files", "-co", "--exclude-standard"],
                             capture_output=True, text=True, check=True).stdout
        ignored = subprocess.run(["git", "-C", str(root), "ls-files", "-oi", "--exclude-standard",
                                  "--", *LIVE_IGNORED],
                                 capture_output=True, text=True, check=True).stdout
        return sorted({line for line in (out + ignored).splitlines()
                       if line and line not in GENERATED and (root / line).is_file()})
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            rel = Path(dirpath, name).relative_to(root).as_posix()
            if rel not in GENERATED:
                found.append(rel)
    return sorted(found)


def _token_re(basename: str) -> re.Pattern[str]:
    # A path token ending in the moved file's name, not glued to more path
    # characters on either side; a `#anchor` after it stays outside the group.
    # A full stop that ends a sentence ("Detail: docs/x.md.") is not part of the
    # path; one that continues it (`x.md.bak`) is.
    return re.compile(rf"(?<![\w.~/:-])((?:[\w.~-]+/)*{re.escape(basename)})(?![\w~/-]|\.[\w~/-])")


def _resolves(token: str, linking_file: str, old: str) -> str | None:
    """'dir' when the token is relative to the linking file, 'root' when it is
    repo-relative, None when it points elsewhere."""
    here = posixpath.dirname(linking_file)
    if posixpath.normpath(posixpath.join(here, token)) == old:
        return "dir"
    if posixpath.normpath(token) == old:
        return "root"
    return None


def _inbound(text: str, linking_file: str, old: str, new: str) -> str:
    def swap(m: re.Match[str]) -> str:
        how = _resolves(m.group(1), linking_file, old)
        if how == "dir":
            return posixpath.relpath(new, posixpath.dirname(linking_file) or ".")
        if how == "root":
            return new
        return m.group(1)
    text = _token_re(posixpath.basename(old)).sub(swap, text)
    # A root-absolute link, `[x](/docs/old.md)`: the token pattern above stops
    # at the leading slash, so it is matched on its own.
    return re.sub(rf"(?<=[(\s\"'`<])/{re.escape(old)}(?![\w~/-]|\.[\w~/-])", "/" + new, text)


# `[text](target)` and `[text](target "title")`, and a reference definition
# `[id]: target` on a line of its own.
_LINK_RE = re.compile(r"(\]\()([^)\s]+)((?:\s+\"[^\"]*\")?\))")
_REF_DEF_RE = re.compile(r"^(\s{0,3}\[(?!\^)[^\]]+\]:\s*)(\S+)(.*)$")   # never a footnote [^1]
_PATHLIKE_RE = re.compile(r"[/#]|\.[A-Za-z0-9]{1,5}$")
_TOP_KEY_RE = re.compile(r"^([A-Za-z_][\w-]*):(.*)$")
_LIST_ITEM_RE = re.compile(r"^(\s*-\s+)(\S+)(\s*)$")
_FLOW_RE = re.compile(r"^(related:\s*\[)(.*)(\]\s*)$")


def _is_relative_link(target: str) -> bool:
    return not (target.startswith(("#", "/", "mailto:")) or "://" in target)


def _relocate(target: str, old: str, new: str) -> str:
    path, sep, anchor = target.partition("#")
    if not path:
        return target
    absolute = posixpath.normpath(posixpath.join(posixpath.dirname(old), path))
    if absolute == old:  # a link to itself
        absolute = new
    moved = posixpath.relpath(absolute, posixpath.dirname(new))
    return moved + (sep + anchor if sep else "")


def _related_entry(entry: str, root: Path, old: str, new: str, unresolved: list[str]) -> str:
    """A `related:` path keeps the convention it was written in.

    The tree writes them both ways: relative to the file (`../skills/x`) and
    from the repo root (`docs/x.md`, `AGENTS.md`). Relative to the file wins
    when it resolves, since that is how a Markdown reader follows it; a path
    that only resolves from the root stays as it is; one that resolves nowhere
    is left alone and reported.
    """
    if not _is_relative_link(entry):
        return entry
    path, sep, anchor = entry.partition("#")
    from_file = posixpath.normpath(posixpath.join(posixpath.dirname(old), path))
    if from_file == old or (root / from_file).exists():
        return _relocate(entry, old, new)
    if posixpath.normpath(path) == old:          # names the doc itself, from the root
        return new + (sep + anchor if sep else "")
    if (root / posixpath.normpath(path)).exists():
        return entry
    unresolved.append(f"{new}: related entry {entry} resolves nowhere, left as written")
    return entry


def _outbound(text: str, old: str, new: str, root: Path | None = None,
              unresolved: list[str] | None = None) -> str:
    """Rewrite the moved file's own relative links for its new folder."""
    root = Path(root) if root is not None else Path(".")
    unresolved = unresolved if unresolved is not None else []
    lines = text.split("\n")
    in_front = bool(lines) and lines[0].strip() == "---"
    key = None
    fence = False
    out = []
    for i, line in enumerate(lines):
        if in_front and i > 0 and line.strip() == "---":
            in_front = False
            out.append(line)
            continue
        if in_front:
            top = _TOP_KEY_RE.match(line)
            if top:
                key = top.group(1)
                flow = _FLOW_RE.match(line)
                if flow:
                    items = [s.strip() for s in flow.group(2).split(",")]
                    line = flow.group(1) + ", ".join(
                        _related_entry(s, root, old, new, unresolved) if s else s
                        for s in items) + flow.group(3)
            elif key == "related":
                item = _LIST_ITEM_RE.match(line)
                if item:
                    line = item.group(1) + _related_entry(item.group(2), root, old, new,
                                                          unresolved) + item.group(3)
            out.append(line)
            continue
        if line.lstrip().startswith(("```", "~~~")):
            fence = not fence
            out.append(line)
            continue
        if fence:  # an example, never a link of this doc
            out.append(line)
            continue
        ref = _REF_DEF_RE.match(line)
        if ref and _is_relative_link(ref.group(2)) and _PATHLIKE_RE.search(ref.group(2)):
            out.append(ref.group(1) + _relocate(ref.group(2), old, new) + ref.group(3))
            continue
        out.append(_LINK_RE.sub(
            lambda m: m.group(1) + (_relocate(m.group(2), old, new)
                                    if _is_relative_link(m.group(2)) else m.group(2)) + m.group(3),
            line))
    return "\n".join(out)


# Records written at a moment, beside the log: what a task or stream delivered,
# and the inbox items. They cite paths as evidence of what was true then.
# Records beyond HISTORY: deliverables, the inbox, reports, every log, and any
# file or folder whose name starts with its date (a dated report, a meeting's
# folder with its minutes and triage, a day note).
_RECORD_RE = re.compile(r"^work/(?:tasks|streams)/[^/]+/deliverables/|^work/inbox/|^work/reports/"
                        r"|(?:^|/)log\.md$|(?:^|/)\d{4}-\d{2}-\d{2}[^/]*(?:/|$)")


def _write(path: Path, text: str) -> None:
    """Write back with the line endings the text already has (CRLF stays CRLF)."""
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def _is_history(rel: str) -> bool:
    return rel == HISTORY[0] or rel.startswith(HISTORY[1:]) or bool(_RECORD_RE.search(rel))


def _tier(router, root: Path, rel: str) -> str:
    """The tier the scope router gives `rel` in the tree at `root`."""
    here = os.getcwd()
    try:
        os.chdir(root)
        return router.classify_file(rel)
    finally:
        os.chdir(here)


def _mentions(text: str, rel: str, source: str) -> bool:
    return any(_resolves(m.group(1), rel, source)
               for m in _token_re(posixpath.basename(source)).finditer(text))


def _read(root: Path, rel: str) -> str | None:
    try:
        with open(root / rel, encoding="utf-8", newline="") as f:   # keep CRLF as it is
            return f.read()
    except (OSError, UnicodeDecodeError):
        return None


def plan(root: Path) -> Plan:
    root = Path(root)
    result = Plan()
    docs = root / "docs"
    if not docs.is_dir():
        return result
    router = _router()
    for path in sorted(docs.rglob("*.md")):
        rel = path.relative_to(root).as_posix()
        place = router.doc_placement(rel, root)
        if place.token is None and not place.legacy:
            continue
        if place.stray:
            result.unplaceable.append((rel, "its scope line sits outside a frontmatter block at "
                                            "the top: move it into one, then run this again"))
            continue
        if place.unknown:
            result.unplaceable.append((rel, f"unknown scope '{place.token}': say what it is, "
                                            "then run this again"))
            continue
        if place.folder != "core":
            if place.declared != place.folder:
                result.unplaceable.append((rel, f"in docs/{place.folder}/ but declares "
                                                f"'{place.token}': fix the line or the folder by hand"))
            continue
        if place.declared == "core":
            continue
        target = f"docs/{place.declared}/{rel[len('docs/'):]}"
        if (root / target).exists():
            result.unplaceable.append((rel, f"{target} already exists"))
            continue
        result.moves.append(Move(rel, target, place.declared))
        text = _read(root, rel)
        if text is not None:  # the dry run already names a related entry that resolves nowhere
            _outbound(text, rel, target, root, result.unresolved)

    if result.moves:
        sources = {m.source for m in result.moves}
        for rel in _files(root):
            if rel in sources or Path(rel).suffix not in SCAN_SUFFIXES:
                continue
            history = _is_history(rel)
            rewritable = Path(rel).suffix in REWRITE_SUFFIXES and not history
            core = rewritable and _tier(router, root, rel) == "core"
            if rewritable and not core:
                continue
            text = _read(root, rel)
            if text is None:
                continue
            if any(_mentions(text, rel, move.source) for move in result.moves):
                if core:
                    result.core_left.append(rel)
                else:
                    (result.history_left if history else result.mentions_left).append(rel)
    return result


def apply(root: Path, the_plan: Plan) -> list[str]:
    """Carry out the moves; returns every file that changed."""
    root = Path(root)
    changed: list[str] = []
    git = _is_git(root)
    router = _router() if the_plan.moves else None
    for move in the_plan.moves:
        src, dst = root / move.source, root / move.target
        dst.parent.mkdir(parents=True, exist_ok=True)
        tracked = git and subprocess.run(
            ["git", "-C", str(root), "ls-files", "--error-unmatch", move.source],
            capture_output=True, text=True).returncode == 0
        if tracked:
            subprocess.run(["git", "-C", str(root), "mv", move.source, move.target],
                           check=True, capture_output=True, text=True)
        else:
            src.rename(dst)
        text = _read(root, move.target)
        if text is not None:
            rewritten = _outbound(text, move.source, move.target, root, [])
            if rewritten != text:
                _write(dst, rewritten)
        changed.append(move.target)
        for rel in _files(root):
            if rel == move.target or Path(rel).suffix not in REWRITE_SUFFIXES or _is_history(rel):
                continue
            if rel in the_plan.core_left or _tier(router, root, rel) == "core":
                continue  # a CORE file comes from upstream; the plan names it
            text = _read(root, rel)
            if text is None or posixpath.basename(move.source) not in text:
                continue
            rewritten = _inbound(text, rel, move.source, move.target)
            if rewritten != text:
                _write(root / rel, rewritten)
                changed.append(rel)
        if tracked:
            subprocess.run(["git", "-C", str(root), "add", "--", move.target],
                           check=True, capture_output=True, text=True)
    return changed


def _print_plan(the_plan: Plan) -> None:
    if not the_plan.pending:
        print("docs/: every doc sits where its tier says, nothing to move")
        return
    for move in the_plan.moves:
        print(f"  move  {move.source} -> {move.target}  (scope: {move.declared})")
    for rel, reason in the_plan.unplaceable:
        print(f"  stay  {rel}: {reason}")
    for note in the_plan.unresolved:
        print(f"  check {note}")
    for rel in the_plan.history_left:
        print(f"  keep  {rel} names a moved doc; it is a record of the past and stays as written")
    for rel in the_plan.core_left:
        print(f"  core  {rel} names a moved doc; it is a CORE file, which comes from upstream "
              "and is never edited here. If that line is your own, move it to "
              "identity/agent/INSTANCE.md or a page in docs/user/")
    for rel in the_plan.mentions_left:
        print(f"  note  {rel} names a moved doc; it is code or a page, which this script never "
              "edits, so look at it")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Move a fork's own docs into docs/user|org|personal/")
    parser.add_argument("--repo-root", default=str(HERE.parent))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="move the files and rewrite the links")
    mode.add_argument("--check", action="store_true", help="exit 1 while anything is left to do")
    args = parser.parse_args(argv)
    root = Path(args.repo_root).resolve()
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 2

    the_plan = plan(root)
    _print_plan(the_plan)
    if args.check:
        return 1 if the_plan.pending else 0
    if not args.write:
        if the_plan.moves:
            print("dry run: nothing changed. Run again with --write to move.")
        return 0
    changed = apply(root, the_plan)
    for rel in changed:
        print(f"  wrote {rel}")
    for note in overlay_notes(root, changed):
        print(note)
    if changed:
        print("done: review with `git status` and `git diff --staged`, then commit "
              "(validate-bridge.py should now pass the docs surface)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
