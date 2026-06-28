#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Validate Bridge config files against their schemas.

Wrapper around `check-jsonschema` (https://check-jsonschema.readthedocs.io/)
that knows the Bridge schema-bearing surfaces (persona, theme, channel,
remote, mandant, calendar). Iterates each surface, finds instance files
via glob, and validates them against the surface's `_schema.yaml` using
JSON Schema Draft 2020-12.

Also validates that every `rules/*.md` carries an explicit `scope:`
frontmatter value (core|org|user|private) — the field `/promote` and
`/bridge-sync` route on. A rule with missing or invalid scope fails the
check (this is what keeps generic CORE rules from leaking to open-bridge).

This is the bridge-internal config validator. For ecosystem.yaml
cross-reference checks, run `validate-ecosystem.py` (separate concern).

Setup:
  pipx install check-jsonschema      # one-time
  # or via uv: uv tool install check-jsonschema

Exit codes:
  0 — all instances valid
  1 — at least one validation error
  2 — setup error (missing dep, schema not found, etc.)

Usage:
  scripts/validate-bridge.py                  # validate everything
  scripts/validate-bridge.py --surface theme  # validate one surface
  scripts/validate-bridge.py --list           # show discovered files
"""
from __future__ import annotations

import argparse
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Generic, OSS-clean scope tiers — built in, safe to ship to open-bridge.
#   core → public + org-internal upstream · org → org-internal only · user/private → local.
# An instance's concrete org tag (e.g. "acme") is NOT hardcoded here — it is
# declared in bridge-config.yaml `promote.scopes.org_aliases` and routes like
# `org`. This keeps THIS file generic so it promotes to open-bridge unchanged.
GENERIC_SCOPES = {"core", "org", "user", "private"}


def org_scope_aliases() -> set[str]:
    """Instance-specific org-tag aliases (e.g. {"acme"}) from bridge-config.yaml.

    Empty set if PyYAML is unavailable, the config is missing, or the key is
    absent — so a fresh open-bridge clone validates against generic tiers only.
    """
    try:
        import yaml
    except ImportError:
        return set()
    cfg_path = REPO_ROOT / "bridge-config.yaml"
    if not cfg_path.exists():
        return set()
    try:
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return set()
    aliases = (((cfg.get("promote") or {}).get("scopes") or {}).get("org_aliases")) or []
    return {str(a) for a in aliases}


def allowed_scopes() -> set[str]:
    """Generic tiers plus this instance's configured org aliases."""
    return GENERIC_SCOPES | org_scope_aliases()

# Surface registry — single source of truth for which folders ship schemas.
# Each entry: (surface name, schema path, instance glob, exclude prefixes).
# Exclude prefixes filter out template/schema files that share the dir.
SURFACES = [
    {
        "name": "persona",
        "schema": "identity/personas/_schema.yaml",
        "instances": "identity/personas/*.yaml",
        "exclude_prefixes": ["_"],
    },
    {
        "name": "theme",
        "schema": "themes/_schema.yaml",
        "instances": "themes/*.yaml",
        "exclude_prefixes": ["_"],
    },
    {
        "name": "channel",
        "schema": "infra/channels/_schema.yaml",
        "instances": "infra/channels/*.yaml",
        "exclude_prefixes": ["_"],
    },
    {
        "name": "remote",
        "schema": "infra/remotes/_schema.yaml",
        "instances": "infra/remotes/*.yaml",
        "exclude_prefixes": ["_"],
    },
    {
        "name": "mandant",
        "schema": "identity/mandants/_schema.yaml",
        "instances": "identity/mandants/*.yaml",
        "exclude_prefixes": ["_"],
    },
    {
        "name": "calendar",
        "schema": "workflow/calendars/_schema.yaml",
        "instances": "workflow/calendars/*.yaml",
        "exclude_prefixes": ["_"],
    },
    {
        # Generated root-config lockfile (scope: user) recording applied org
        # overlays, pinned to immutable hashes. Absent on a fresh clone → the
        # glob finds no instances and the surface is a no-op; validated when
        # an /overlay subscription has written it. See docs/org-overlays.md.
        "name": "overlays-lock",
        "schema": "docs/schemas/overlays-lock.schema.yaml",
        "instances": "overlays.lock.yaml",
        "exclude_prefixes": [],
    },
]


def discover_instances(surface: dict) -> list[Path]:
    """Glob instance files for a surface, applying exclusion rules."""
    excludes = surface.get("exclude_prefixes", [])
    paths = sorted(REPO_ROOT.glob(surface["instances"]))
    return [
        p
        for p in paths
        if not any(p.name.startswith(prefix) for prefix in excludes)
    ]


def validate_surface(surface: dict, *, validator: str) -> tuple[int, int]:
    """Validate one surface. Returns (pass_count, fail_count)."""
    schema_path = REPO_ROOT / surface["schema"]
    if not schema_path.exists():
        sys.stderr.write(f"  SKIP  schema not found: {schema_path}\n")
        return (0, 0)

    instances = discover_instances(surface)
    if not instances:
        print(f"  ({surface['name']}: no instances found)")
        return (0, 0)

    cmd = [
        validator,
        "--schemafile",
        str(schema_path),
        "--default-filetype",
        "yaml",
        *(str(p) for p in instances),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 0:
        for inst in instances:
            print(f"  PASS  {inst.relative_to(REPO_ROOT)}")
        return (len(instances), 0)

    # check-jsonschema prints failures to stdout; surface them
    sys.stdout.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)

    # Best-effort: count failed files from "FAIL" markers in stdout
    failed_files = sum(1 for line in result.stdout.splitlines() if "errors were encountered" in line.lower() or "validation failed" in line.lower())
    failed = max(failed_files, 1)
    passed = max(len(instances) - failed, 0)
    return (passed, failed)


# Markdown surfaces whose `scope:` frontmatter is required + tier-validated.
# Unlike SURFACES (JSON-Schema YAML), these are plain-Python frontmatter checks
# — no check-jsonschema dependency. rules/*.md is CORE-by-path, so an unscoped
# rule inherits `core` and would leak to open-bridge; this gate forbids that.
MD_SCOPE_SURFACES = [
    {
        "name": "rules",
        "instances": "rules/*.md",
        "exclude_prefixes": ["_"],
    },
]


def discover_md_instances(surface: dict) -> list[Path]:
    """Glob markdown instance files for a scope surface, applying exclusions."""
    excludes = surface.get("exclude_prefixes", [])
    paths = sorted(REPO_ROOT.glob(surface["instances"]))
    return [p for p in paths if not any(p.name.startswith(x) for x in excludes)]


def _load_frontmatter_extractor():
    """Import the canonical extract() from extract-frontmatter.py (hyphenated)."""
    spec = importlib.util.spec_from_file_location(
        "extract_frontmatter", Path(__file__).resolve().parent / "extract-frontmatter.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load extract-frontmatter.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.extract


def validate_md_scope_surface(surface: dict) -> tuple[int, int]:
    """Validate `scope:` frontmatter on a markdown surface. Returns (pass, fail)."""
    extract = _load_frontmatter_extractor()
    allowed = allowed_scopes()
    instances = discover_md_instances(surface)
    if not instances:
        print(f"  ({surface['name']}: no instances found)")
        return (0, 0)

    passed = failed = 0
    for inst in instances:
        rel = inst.relative_to(REPO_ROOT)
        try:
            fm = extract(inst)
        except SystemExit:
            # extract() exits on unterminated block / invalid YAML — treat as fail,
            # don't abort the whole validator run.
            fm = None
        scope = fm.get("scope") if isinstance(fm, dict) else None
        if scope is None:
            print(f"  FAIL  {rel} — missing required `scope:` frontmatter")
            failed += 1
        elif scope not in allowed:
            print(f"  FAIL  {rel} — invalid scope '{scope}' (allowed: {', '.join(sorted(allowed))})")
            failed += 1
        else:
            print(f"  PASS  {rel} [scope: {scope}]")
            passed += 1
    return (passed, failed)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Bridge configs against schemas")
    parser.add_argument("--surface", help="Validate only this surface (e.g. persona, rules)")
    parser.add_argument("--list", action="store_true", help="List discovered files and exit")
    args = parser.parse_args()

    json_surfaces = SURFACES
    md_surfaces = MD_SCOPE_SURFACES
    if args.surface:
        json_surfaces = [s for s in SURFACES if s["name"] == args.surface]
        md_surfaces = [s for s in MD_SCOPE_SURFACES if s["name"] == args.surface]
        if not json_surfaces and not md_surfaces:
            known = [s["name"] for s in SURFACES] + [s["name"] for s in MD_SCOPE_SURFACES]
            sys.stderr.write(
                f"ERROR: unknown surface '{args.surface}'. Known: {', '.join(known)}\n"
            )
            return 2

    if args.list:
        for s in json_surfaces:
            schema = REPO_ROOT / s["schema"]
            schema_status = "OK" if schema.exists() else "MISSING"
            print(f"\n{s['name']}: schema={s['schema']} [{schema_status}]")
            for inst in discover_instances(s):
                print(f"  {inst.relative_to(REPO_ROOT)}")
        for s in md_surfaces:
            print(f"\n{s['name']}: scope-frontmatter check (instances={s['instances']})")
            for inst in discover_md_instances(s):
                print(f"  {inst.relative_to(REPO_ROOT)}")
        return 0

    total_pass = 0
    total_fail = 0

    if json_surfaces:
        validator = shutil.which("check-jsonschema")
        if not validator:
            sys.stderr.write(
                "ERROR: check-jsonschema not found in PATH.\n"
                "  Install: pipx install check-jsonschema\n"
                "  (or: uv tool install check-jsonschema)\n"
            )
            return 2
        for s in json_surfaces:
            print(f"\n[{s['name']}]")
            p, f = validate_surface(s, validator=validator)
            total_pass += p
            total_fail += f

    for s in md_surfaces:
        print(f"\n[{s['name']} — scope frontmatter]")
        p, f = validate_md_scope_surface(s)
        total_pass += p
        total_fail += f

    print(f"\n{'─' * 50}")
    print(f"Total: {total_pass} passed, {total_fail} failed")
    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
