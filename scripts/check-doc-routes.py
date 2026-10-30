#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Every path an always-on document names must resolve.

Trimming an always-on file works by replacing an explanation with a pointer to
the file that owns it. That trade is only sound while the pointer resolves. A
pointer at a file that was renamed, or never existed, is strictly worse than the
paragraph it replaced: the paragraph was at least readable, and a dead pointer
fails silently, at the moment somebody needed the thing it pointed at.

A load-bearing pointer is therefore written as a markdown link, and a link is
what this checks. A backticked path stays prose.

    python3 scripts/check-doc-routes.py

Exit 0 when every route resolves, 1 otherwise.

The contract lives in `scripts/tests/test_doc_routes.py`.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# The always-on documents whose pointers are load-bearing. A document that an
# instance does not carry is skipped, not fatal. No CLAUDE.md: CORE ships none,
# and a fork's legacy one is USER content (scripts/migrate-entry-file.py).
ROUTED_DOCS = (
    "AGENTS.md",
    "GEMINI.md",
    "README.md",
    ".github/copilot-instructions.md",
)

MD_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def _clean(target: str) -> str | None:
    """The file a route points at, or None when it is not a route."""
    target = target.split("#", 1)[0].strip()
    if not target or "://" in target or target.startswith(("#", "mailto:")):
        return None
    # A placeholder is a shape, not a file. Demanding it exist would make the
    # gate unusable exactly where the docs are most useful.
    if "<" in target or ">" in target or "*" in target or "{" in target:
        return None
    return target


def extract_routes(text: str) -> list[str]:
    """Every repo path the text LINKS to.

    Markdown links only. A link is a navigation promise; a backticked path is
    prose, and prose names things that legitimately do not exist in a given
    clone. Checking backticks too produced 24 violations on a healthy tree and
    not one was a bug (see `scripts/tests/test_doc_routes.py`). A gate with 24
    false positives on a healthy repo is not a gate; it is a thing people learn
    to skip.
    """
    found: list[str] = []
    seen: set[str] = set()
    for raw in MD_LINK.findall(text):
        target = _clean(raw)
        if target and target not in seen:
            seen.add(target)
            found.append(target)
    return found


def check_routes(repo_root: Path, docs) -> list[str]:
    """One violation per unresolvable route, naming the document it sits in.

    A route resolves against the folder of the document that carries it, the
    way a markdown renderer follows it: `.github/copilot-instructions.md`
    links `../AGENTS.md`.
    """
    root = Path(repo_root)
    violations = []
    for name in docs:
        doc = root / name
        if not doc.is_file():
            continue
        text = doc.read_text(encoding="utf-8", errors="replace")
        for route in extract_routes(text):
            target = doc.parent / route
            if not target.exists():
                violations.append(f"{name}: route does not resolve: {route}")
    return violations


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify every path an always-on document names."
    )
    parser.add_argument("--repo-root", default=None)
    args = parser.parse_args(argv)
    root = (
        Path(args.repo_root).resolve()
        if args.repo_root
        else Path(__file__).resolve().parents[1]
    )
    violations = check_routes(root, ROUTED_DOCS)
    if violations:
        print("check-doc-routes: dead routes", file=sys.stderr)
        for violation in violations:
            print(f"  {violation}", file=sys.stderr)
        return 1
    print("check-doc-routes: every route resolves")
    return 0


if __name__ == "__main__":
    sys.exit(main())
