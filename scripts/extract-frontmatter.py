#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Extract YAML frontmatter from a markdown file as JSON on stdout.

Used by:
  work/templates/_schema.status.yaml docstring  (validation recipe)
  pre-commit hooks                              (frontmatter sanity)

Format: looks for a YAML block delimited by `---` lines at the top of the
file. Comment lines (`# ...`) before the first `---` are skipped — this
lets STATUS.md carry the `# yaml-language-server: $schema=...` hint above
the frontmatter block.

Usage:
  python3 scripts/extract-frontmatter.py work/tasks/<slug>/STATUS.md
  python3 scripts/extract-frontmatter.py STATUS.md | check-jsonschema \\
    --schemafile work/templates/_schema.status.yaml -

Exit codes:
  0 — frontmatter found and emitted as JSON
  1 — no frontmatter found / unterminated block
  2 — invalid YAML inside frontmatter
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("ERROR: PyYAML not installed. pip install pyyaml\n")
    sys.exit(2)


def extract(path: Path) -> dict | None:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        sys.stderr.write(f"ERROR: {path} not found\n")
        sys.exit(2)

    in_block = False
    buf: list[str] = []
    for line in text.splitlines():
        if not in_block:
            if line.lstrip().startswith("#"):
                continue
            if line.strip() == "---":
                in_block = True
                continue
            if line.strip() == "":
                continue
            # first non-empty non-comment non-fence line → no frontmatter
            return None
        else:
            if line.strip() == "---":
                break
            buf.append(line)
    else:
        if in_block:
            sys.stderr.write(f"ERROR: {path} frontmatter block not closed\n")
            sys.exit(1)
    if not buf:
        return None
    try:
        return yaml.safe_load("\n".join(buf)) or {}
    except yaml.YAMLError as exc:
        sys.stderr.write(f"ERROR: {path} invalid YAML in frontmatter: {exc}\n")
        sys.exit(2)


def main() -> int:
    if len(sys.argv) != 2:
        sys.stderr.write("Usage: extract-frontmatter.py <markdown-file>\n")
        return 2
    fm = extract(Path(sys.argv[1]))
    if fm is None:
        sys.stderr.write(f"NOTICE: no frontmatter in {sys.argv[1]}\n")
        return 1
    print(json.dumps(fm, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
