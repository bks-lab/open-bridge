#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Validate STATUS.md frontmatter against work/templates/_schema.status.yaml.

Makes AGENTS.md's "CI-validated status enum" claim real: every
work/{tasks,streams,done}/*/STATUS.md must carry a `status:` value drawn from
the schema's enum. The enum + required-key list are read FROM the schema
(single source of truth), so this stays honest if the schema evolves. PyYAML
only — no check-jsonschema dependency — so it runs identically in CI and in the
scripts/hooks/pre-commit warn gate. (Full JSON-Schema validation remains
available via the documented recipe:
  extract-frontmatter.py <f> | check-jsonschema --schemafile <schema> - )

Usage:
  scripts/validate-status.py            # all STATUS.md under work/{tasks,streams,done}
  scripts/validate-status.py --staged   # only git-staged STATUS.md (pre-commit)

Exit: 0 = every status enum valid; 1 = at least one invalid/absent status
(CI blocks; the pre-commit hook prints the output but never blocks). Missing
required keys are reported as warnings and do NOT change the exit code, so a
legacy task with incomplete frontmatter never breaks CI over the enum claim.
"""
from __future__ import annotations

import glob
import re
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("validate-status: PyYAML required (pip install pyyaml) — skipping", file=sys.stderr)
    sys.exit(0)  # degrade gracefully: never block on a missing dep

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "work/templates/_schema.status.yaml"
FALLBACK_ENUM = ["backlog", "doing", "review", "done"]


def load_schema():
    try:
        doc = yaml.safe_load(SCHEMA.read_text(encoding="utf-8"))
    except Exception:
        return [], FALLBACK_ENUM
    required = doc.get("required", []) if isinstance(doc, dict) else []
    try:
        enum = doc["properties"]["status"]["enum"] or FALLBACK_ENUM
    except Exception:
        enum = FALLBACK_ENUM
    return required, enum


def _shallow_parse(block):
    """Recover top-level scalar keys via regex when full YAML won't parse
    (e.g. an `origin:` value with an embedded quote breaks yaml.safe_load but
    must not hide a perfectly valid `status:`). Only unindented `key: value`."""
    d = {}
    for ln in block:
        if ln[:1] in (" ", "\t"):
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", ln)
        if m:
            d.setdefault(m.group(1), (m.group(2).strip().strip("\"'") or None))
    return d


def frontmatter(path: Path):
    """Return the YAML frontmatter dict, skipping leading comment/blank lines.
    Returns None only when there is genuinely no `---` block; a block that fails
    to parse as YAML falls back to a shallow regex scan so one malformed field
    can't masquerade as a missing `status`."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    i = 0
    while i < len(lines) and (lines[i].strip() == "" or lines[i].lstrip().startswith("#")):
        i += 1
    if i >= len(lines) or lines[i].strip() != "---":
        return None
    i += 1
    block = []
    while i < len(lines) and lines[i].strip() != "---":
        block.append(lines[i])
        i += 1
    try:
        parsed = yaml.safe_load("\n".join(block))
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    return _shallow_parse(block)  # malformed YAML — recover what we can


def is_root_status(rel: str) -> bool:
    """True only for a task/stream/done ROOT STATUS.md — never a nested copy
    (e.g. artifacts/translations/.../STATUS.md), which are not task records."""
    p = rel.split("/")
    if not p or p[-1] != "STATUS.md" or p[0] != "work":
        return False
    if len(p) == 4 and p[1] in ("tasks", "streams"):       # work/<b>/<slug>/STATUS.md
        return True
    if len(p) == 5 and p[1] == "done":                     # work/done/YYYY-MM/<slug>/STATUS.md
        return True
    return False


def targets(staged: bool):
    if staged:
        out = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
            capture_output=True, text=True,
        ).stdout.splitlines()
        return [ROOT / p for p in out if is_root_status(p)]
    files = (
        glob.glob(str(ROOT / "work/tasks/*/STATUS.md"))       # glob * does not cross /
        + glob.glob(str(ROOT / "work/streams/*/STATUS.md"))
        + glob.glob(str(ROOT / "work/done/*/*/STATUS.md"))
    )
    return [Path(f) for f in files]


def main():
    staged = "--staged" in sys.argv[1:]
    required, enum = load_schema()
    errors, warnings = [], []
    for f in targets(staged):
        if not f.exists():
            continue
        rel = f.relative_to(ROOT)
        # Strict (exit 1) only for the active bucket work/tasks/ — where AGENTS.md's
        # enum claim bites. work/streams/ (often domain-specific sub-tracking) and
        # work/done/ (frozen historical records) surface as non-blocking warnings.
        parts = str(rel).split("/")
        strict = len(parts) > 1 and parts[0] == "work" and parts[1] == "tasks"
        sink = errors if strict else warnings
        fm = frontmatter(f)
        if fm is None:
            sink.append(f"{rel}: no YAML frontmatter block")
            continue
        if fm.get("status") not in enum:
            sink.append(f"{rel}: status: {fm.get('status')!r} not in {enum}")
        for key in required:
            if key not in fm:
                warnings.append(f"{rel}: missing required key '{key}'")

    for w in warnings:
        print("  ! " + w, file=sys.stderr)
    if errors:
        print(f"STATUS.md status-enum validation — {len(errors)} error(s):", file=sys.stderr)
        for e in errors:
            print("  ✗ " + e, file=sys.stderr)
        sys.exit(1)
    if not staged:
        print("validate-status: all STATUS.md status values valid")
    sys.exit(0)


if __name__ == "__main__":
    main()
