#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Validate that every skill declares a valid scope, and keep AGENTS.md honest.

Skills are FLAT under `skills/` (open Agent-Skills standard — multi-tool
discovery via .claude/skills, .agents/skills, .github/skills). Because they
can't be foldered by tier, their tier lives in the SKILL.md frontmatter as
`metadata.scope` (or legacy top-level `scope:`). This validator is the
enforcement that makes that frontmatter load-bearing instead of drift-prone.

What it does:
  1. Every `skills/*/SKILL.md` must declare scope ∈ {core, org, user, personal}.
     Missing / invalid → exit 1 (CI + pre-commit gate). This is the load-bearing
     part: it makes the frontmatter authoritative instead of drift-prone.
  2. No two CORE skills may quote the same phrase in their `Trigger:` list
     (case-insensitive). CORE ships to every installation, so a shared trigger
     makes the harness pick between two skills by wording and model, and the
     choice cannot be reproduced. Org and user skills may still shadow a CORE
     trigger on purpose.
  3. Refreshes the per-instance tier map at `.bridge/skill-scope.md`.
  4. WARNS (never fails) on a SKILL.md over SKILL_MD_MAX_LINES lines and on a
     description over DESCRIPTION_MAX_BYTES bytes. See the constants below.

Why the map is NOT in AGENTS.md any more (changed 2026-08-19):
  Every instance has a different skill tree by design (org skills, personal
  skills, local-only skills). A table generated from the LOCAL tree and embedded
  in a CORE file can therefore never converge with upstream: it conflicted on
  every `git merge <oss-core>/main`, and promoting it would have carried local
  org/customer skill names into the public OSS repo. The map is derived data, so
  it now lives beside the other derived state under `.bridge/` (gitignored, and
  already classified local-only by scripts/categorize-commits.py). AGENTS.md
  keeps a static description of the tiers and points here. The authoritative
  tier was always the frontmatter, never the table.

Usage:
  validate-skill-scope.py            # validate scopes + refresh the map
  validate-skill-scope.py --check    # validate only, write nothing
  validate-skill-scope.py --write    # accepted, same as default (back-compat)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("validate-skill-scope: PyYAML required (pip install pyyaml)")

REPO = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO / "skills"
# Derived, per-instance, never committed: .bridge/ is gitignored AND matched by
# the `^\.bridge/` USER pattern in scripts/categorize-commits.py, so this file
# needs no new router literal to stay local-only.
SCOPE_MAP = REPO / ".bridge" / "skill-scope.md"

VALID = ("core", "org", "personal", "user")
SHIPS_TO = {
    "core": "open-bridge + your org overlay + local",
    "org": "your org overlay + local",
    "personal": "your personal overlay + local",
    "user": "local only",
}
# Size warnings. Advisory on purpose: both are judgement calls, and a gate that
# failed on them would be answered by raising the number, not by the edit.
#
# The DESCRIPTION is resident. The harness lists `name` + `description` of
# every skill in every session and every sub-agent dispatch, and the sum is
# capped as `listing:skills` in context-budget.yaml. Above about 380 bytes a
# description is no longer a trigger line but a summary of the skill, and it
# was the heaviest entries that pushed one instance's listing over its cap.
# Measured in UTF-8 bytes after folding to one line, exactly as the listing
# carries it, so a German description is not undercounted by half.
DESCRIPTION_MAX_BYTES = 380
# The BODY loads whenever the skill runs. A SKILL.md is meant to be a decision
# tree that routes to `references/` files read only when triggered; two CORE
# skills had grown to 600+ lines by inlining their full command reference,
# paid on every trigger. 300 lines is about twice a typical routing SKILL.md.
SKILL_MD_MAX_LINES = 300


def frontmatter(path: Path) -> dict | None:
    """Return the parsed YAML frontmatter of a markdown file, or None."""
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        data = yaml.safe_load(parts[1])
        return data if isinstance(data, dict) else None
    except yaml.YAMLError:
        return None


def scope_of(fm: dict | None) -> str | None:
    if not fm:
        return None
    meta = fm.get("metadata")
    if isinstance(meta, dict) and meta.get("scope"):
        return str(meta["scope"]).strip()
    if fm.get("scope"):
        return str(fm["scope"]).strip()
    return None


def quoted_triggers(description: str) -> list[str]:
    """The quoted phrases after `Trigger:` (or `Triggers:`) in a description."""
    m = re.search(r"Triggers?:(.*)$", description, re.S)
    return re.findall(r'"([^"]+)"', m.group(1)) if m else []


def trigger_collisions(core: dict[str, list[str]]) -> list[str]:
    """One error per trigger that more than one CORE skill quotes."""
    owners: dict[str, list[str]] = {}
    for name, triggers in sorted(core.items()):
        for t in {t.strip().casefold() for t in triggers}:
            owners.setdefault(t, []).append(name)
    return [
        f'trigger "{t}" is claimed by several core skills: {", ".join(names)}'
        for t, names in sorted(owners.items()) if len(names) > 1
    ]


def collect() -> tuple[dict[str, list[str]], list[str]]:
    """Return ({scope: [skill names]}, [error strings])."""
    by_scope: dict[str, list[str]] = {s: [] for s in VALID}
    errors: list[str] = []
    core_triggers: dict[str, list[str]] = {}
    # Iterate DIRECTORIES, not `*/SKILL.md`. Globbing the file made a skill
    # directory WITHOUT a SKILL.md invisible: it was neither counted nor flagged,
    # so the validator printed "92 skills valid" against 93 directories. The
    # missing one declared no tier at all, and every file in it fell through the
    # router's frontmatter read — the exact drift this gate exists to catch.
    for skill_dir in sorted(d for d in SKILLS_DIR.iterdir()
                            if d.is_dir() and not d.name.startswith("_")):
        name = skill_dir.name
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            errors.append(
                f"{name}: directory has no SKILL.md — it declares no tier, so the "
                f"scope router cannot classify anything inside it"
            )
            continue
        fm = frontmatter(skill_md)
        sc = scope_of(fm)
        if sc is None:
            errors.append(f"{name}: no scope declared (need metadata.scope ∈ {VALID})")
        elif sc not in VALID:
            errors.append(f"{name}: invalid scope '{sc}' (must be one of {VALID})")
        else:
            by_scope[sc].append(name)
            if sc == "core":
                core_triggers[name] = quoted_triggers(str(fm.get("description", "")))
    errors.extend(trigger_collisions(core_triggers))
    return by_scope, errors


def size_warnings() -> list[str]:
    """One advisory line per skill over a size limit. Never an error."""
    warnings: list[str] = []
    for skill_md in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        if skill_md.parent.name.startswith("_"):
            continue
        name = skill_md.parent.name
        text = skill_md.read_text(encoding="utf-8", errors="replace")
        lines = len(text.splitlines())
        if lines > SKILL_MD_MAX_LINES:
            warnings.append(
                f"{name}: SKILL.md has {lines} lines (> {SKILL_MD_MAX_LINES}); "
                f"move command detail into references/ and keep the decision tree"
            )
        fm = frontmatter(skill_md) or {}
        desc = fm.get("description")
        if isinstance(desc, str):
            size = len(" ".join(desc.split()).encode("utf-8"))
            if size > DESCRIPTION_MAX_BYTES:
                warnings.append(
                    f"{name}: description is {size} bytes (> {DESCRIPTION_MAX_BYTES}); "
                    f"it is listed in every session, shorten it to the trigger line"
                )
    return warnings


def render_map(by_scope: dict[str, list[str]]) -> str:
    """The per-instance tier map. Derived from frontmatter, never authoritative."""
    lines = [
        "<!-- GENERATED by scripts/validate-skill-scope.py — do not edit by hand.",
        "     Per-instance and gitignored: your skill tree is not anyone else's.",
        "     The authoritative tier is `metadata.scope` in each skills/*/SKILL.md. -->",
        "",
        "# Skill tier map",
        "",
        "| Scope | Ships to | Skills |",
        "|-------|----------|--------|",
    ]
    for sc in VALID:
        names = ", ".join(f"`{n}`" for n in sorted(by_scope[sc])) or "—"
        lines.append(f"| `{sc}` | {SHIPS_TO[sc]} | {names} |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    argv = sys.argv[1:]
    check_only = "--check" in argv
    by_scope, errors = collect()

    # Job 1 — the gate. A bad or missing scope fails regardless of mode.
    if errors:
        print("✗ skill-scope validation failed:", file=sys.stderr)
        for e in errors:
            print(f"   - {e}", file=sys.stderr)
        return 1

    # Job 1b: advisory size warnings. Printed, never fatal.
    warnings = size_warnings()
    if warnings:
        print(f"! {len(warnings)} skill size warning(s), advisory:", file=sys.stderr)
        for w in warnings:
            print(f"   - warning: {w}", file=sys.stderr)

    total = sum(len(v) for v in by_scope.values())
    tally = " · ".join(f"{k}:{len(v)}" for k, v in by_scope.items())

    # Job 2 — refresh the derived map. It is gitignored and per-instance, so
    # there is no "drifted" failure mode to report: it is simply rewritten.
    if check_only:
        print(f"✓ {total} skills valid ({tally}) · map not written (--check)")
        return 0

    SCOPE_MAP.parent.mkdir(parents=True, exist_ok=True)
    SCOPE_MAP.write_text(render_map(by_scope), encoding="utf-8")
    rel = SCOPE_MAP.relative_to(REPO)
    print(f"✓ {total} skills valid ({tally}) · map refreshed at {rel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
