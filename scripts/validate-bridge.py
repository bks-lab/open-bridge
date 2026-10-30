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
  0 — all instances valid (or check-jsonschema absent → schema surfaces
      advisory-skipped; missing the optional tool alone never fails)
  1 — at least one validation error
  2 — setup error (unknown --surface, etc.)

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
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Generic, OSS-clean scope tiers — built in, safe to ship to open-bridge.
#   core → public + org-internal upstream · org → org-internal only · user/private → local.
# An instance's concrete org tag (e.g. "acme") is NOT hardcoded here — it is
# declared in bridge-config.yaml `promote.scopes.org_aliases` and routes like
# `org`. This keeps THIS file generic so it promotes to open-bridge unchanged.
# `personal` is a first-class tier (its own overlay destination, its own
# PERSONAL_PATTERNS block in the scope router, its own `promote.upstreams` entry).
# It was missing here — as it was in identity/{personas,mandants}/_schema.yaml —
# so every file honestly declaring it was reported invalid.
GENERIC_SCOPES = {"core", "org", "personal", "user", "private"}


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
        # A store declaration carries no value, only a locator and the policy
        # that says which kind of secret belongs in it. It is validated for the
        # same reason the remotes are: a typo in `backend:` or a kind nobody
        # declared makes `secrets where` answer nothing, and that reads like
        # "there is nowhere to put this" rather than like a broken file.
        "name": "secret-store",
        "schema": "infra/secret-stores/_schema.yaml",
        "instances": "infra/secret-stores/*.yaml",
        "exclude_prefixes": ["_"],
    },
    {
        # An A2A peer: another agent this Bridge may call (skills/a2a). Validated
        # so that a raw token, a credential that is not a reference, or a plain
        # http card fails here rather than at the first call.
        "name": "a2a-peer",
        "schema": "infra/a2a-peers/_schema.yaml",
        "instances": "infra/a2a-peers/*.yaml",
        "exclude_prefixes": ["_"],
    },
    {
        # An object store: where content that is not configuration lives, and
        # which class of content belongs in it (docs/object-store.md). Validated
        # for the reason the secret stores are: a typo in `backend:` or a
        # credential written as a value must fail here, not at resolve time.
        "name": "object-store",
        "schema": "infra/object-stores/_schema.yaml",
        "instances": "infra/object-stores/*.yaml",
        "exclude_prefixes": ["_"],
    },
    {
        "name": "mandant",
        "schema": "identity/mandants/_schema.yaml",
        "instances": "identity/mandants/*.yaml",
        "exclude_prefixes": ["_"],
    },
    {
        # How a drafted mail is signed (skills/mail-draft). Holds contact data,
        # so the schema refuses scope core.
        "name": "mail-footer",
        "schema": "identity/mail-footers/_schema.yaml",
        "instances": "identity/mail-footers/*.yaml",
        "exclude_prefixes": ["_"],
    },
    {
        # An occasion for mail: footer, greeting, attachments, who it applies to.
        "name": "mail-profile",
        "schema": "workflow/mail-profiles/_schema.yaml",
        "instances": "workflow/mail-profiles/*.yaml",
        "exclude_prefixes": ["_"],
    },
    {
        # One brand per Markdown file (DESIGN.md format). The schema holds the
        # front matter, so `frontmatter` hands the validator that block alone:
        # the prose below it is not YAML.
        "name": "design",
        "schema": "identity/designs/_schema.yaml",
        "instances": "identity/designs/*.md",
        "exclude_prefixes": ["_"],
        "frontmatter": True,
    },
    {
        "name": "calendar",
        "schema": "workflow/calendars/_schema.yaml",
        "instances": "workflow/calendars/*.yaml",
        "exclude_prefixes": ["_"],
    },
    {
        # Declared runs. Live declarations were held against the contract
        # by NOTHING automatic before this surface existed: the
        # skill's own `workload validate --strict` reaches them, but only when
        # a human types it. A declaration that drifts from the schema is not a
        # cosmetic problem: `render` writes it onto a machine.
        #
        # The `_tests/` folder beside them is a directory, so the non-recursive
        # glob never sees its deliberately invalid fixtures.
        "name": "workload",
        "schema": "workflow/workloads/_schema.yaml",
        "instances": "workflow/workloads/*.yaml",
        "exclude_prefixes": ["_"],
    },
    {
        "name": "cost-center",
        "schema": "workflow/cost-centers/_schema.yaml",
        "instances": "workflow/cost-centers/*.yaml",
        "exclude_prefixes": ["_"],
    },
    {
        "name": "ai-service",
        "schema": "workflow/ai-services/_schema.yaml",
        "instances": "workflow/ai-services/*.yaml",
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
    {
        # The declared ceiling on what every session loads before it answers.
        # Tracked here (CORE caps); the per-instance overlay
        # context-budget.user.yaml is gitignored and validated by the same
        # schema when present. Enforced by scripts/measure-context.py.
        "name": "context-budget",
        "schema": "docs/schemas/context-budget.schema.yaml",
        "instances": "context-budget*.yaml",
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


def _front_matter_file(path: Path, folder: Path) -> Path:
    """The block between the first two `---` lines of a Markdown file, as `<stem>.yaml` in `folder`.

    A file without front matter becomes an empty document, which the schema
    then refuses for its required keys rather than this function guessing.
    """
    text = path.read_text(encoding="utf-8")
    block = ""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            block = text[3:end].lstrip("\n")
    out = folder / f"{path.stem}.yaml"
    out.write_text(block or "{}\n", encoding="utf-8")
    return out


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

    files = [str(p) for p in instances]
    tmp = None
    if surface.get("frontmatter"):
        tmp = tempfile.TemporaryDirectory(prefix="validate-bridge-")
        files = [str(_front_matter_file(p, Path(tmp.name))) for p in instances]

    cmd = [
        validator,
        "--schemafile",
        str(schema_path),
        "--default-filetype",
        "yaml",
        *files,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if tmp is not None:
        # name the Markdown file in every message, not its temporary front-matter copy
        for copy, inst in zip(files, instances):
            name = str(inst.relative_to(REPO_ROOT))
            result.stdout = result.stdout.replace(copy, name)
            result.stderr = result.stderr.replace(copy, name)
        tmp.cleanup()

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
        # `rules/**/*.md`, not `rules/*.md`. The non-recursive glob left all of
        # rules/org, rules/personal and rules/user unguarded — 17 files, on the
        # one surface where AGENTS.md § Rules says the FOLDER is the tier and the
        # frontmatter is the required backstop. A validator that cannot see a
        # file cannot guard it, and it reported green the whole time.
        "name": "rules",
        "instances": "rules/**/*.md",
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


#: Tier-bearing subfolders — the folder name IS the tier for anything inside it.
TIER_FOLDERS = ("org", "personal", "user")


def tier_folder_of(rel) -> str | None:
    """Return the tier folder a path sits in, or None for the top-level surface.

    `rules/personal/finance.md` → "personal"; `rules/theme.md` → None (top level
    is core by path, which the surface's own allowed-scopes check covers).
    """
    parts = rel.parts
    if len(parts) >= 3 and parts[1] in TIER_FOLDERS:
        return parts[1]
    return None


# ---------------------------------------------------------------------------
# Rule inventory (.bridge/rule-scope.md)
# ---------------------------------------------------------------------------
#
# Same treatment as .bridge/skill-scope.md, and for the same reason: a table
# generated from the LOCAL tree can never converge across instances, so it must
# not live in a CORE file. `.bridge/` is gitignored and already classified
# local-only by scripts/categorize-commits.py, so this needs no router literal.
#
# The column that earns the file is `state`. Frontmatter says which TIER a rule
# belongs to; it cannot say whether a NEW rule may be authored at that path. In
# an instance subscribed to an org overlay, `rules/org/` is a materialisation
# target: gitignored, and skipped by scripts/overlay-export.py, which asks
# `git check-ignore` and never looks at tracked state. A rule written there is
# invisible to git and never reaches the overlay, with no error anywhere.

RULE_MAP_REL = Path(".bridge") / "rule-scope.md"

#: Printed as a legend above the table.
STATE_MEANING = {
    "authorable": "git will track a new rule here",
    "legacy": "gitignored yet tracked, an existing exception rather than a place to add to",
    "managed": "gitignored and untracked, so a new rule here never travels",
    "unknown": "git could not be consulted",
}


def _git_read(repo_root: Path, args: list[str], stdin: str | None = None) -> list[str] | None:
    """Read-only git call. Returns stdout lines, or None if git could not answer.

    None is a DIFFERENT answer from "nothing matched". The caller must never
    turn an unknown ignore state into a green light.
    """
    if not (repo_root / ".git").exists():
        return None
    try:
        proc = subprocess.run(
            ["git", *args], cwd=repo_root, input=stdin, capture_output=True, text=True
        )
    except OSError:
        return None
    # check-ignore exits 1 when nothing matched, which is a valid empty answer.
    if proc.returncode not in (0, 1):
        return None
    return [ln for ln in proc.stdout.splitlines() if ln.strip()]


def git_ignored(repo_root: Path, relpaths: list[str]) -> set[str] | None:
    """The subset of `relpaths` the ignore RULES exclude, or None.

    `--no-index` is load-bearing. Without it `check-ignore` consults the index
    first and reports a tracked path as not-ignored, which answers "does this
    file travel today" rather than "may I put a NEW file here". The second
    question is the one this map exists for, and the two answers differ exactly
    where it matters: a folder holding tracked leftovers under an ignore rule.
    """
    if not relpaths:
        return set()
    lines = _git_read(
        repo_root, ["check-ignore", "--no-index", "--stdin"], stdin="\n".join(relpaths)
    )
    return None if lines is None else set(lines)


def git_tracked(repo_root: Path) -> set[str] | None:
    """Every path git currently tracks, or None."""
    lines = _git_read(repo_root, ["ls-files"])
    return None if lines is None else set(lines)


def rule_state(rel: str, ignored: set[str] | None, tracked: set[str] | None) -> str:
    """Whether a NEW rule may be authored at `rel`. See STATE_MEANING."""
    if ignored is None or tracked is None:
        return "unknown"
    if rel not in ignored:
        return "authorable"
    return "legacy" if rel in tracked else "managed"


def collect_rule_rows(repo_root) -> list[dict]:
    """One row per `rules/**/*.md`, sorted by path so the map never churns."""
    repo_root = Path(repo_root)
    extract = _load_frontmatter_extractor()
    pairs = sorted(
        (p.relative_to(repo_root).as_posix(), p)
        for p in repo_root.glob("rules/**/*.md")
        if p.is_file() and not p.name.startswith("_")
    )
    rels = [rel for rel, _ in pairs]
    ignored = git_ignored(repo_root, rels)
    tracked = git_tracked(repo_root)
    rows = []
    for rel, path in pairs:
        try:
            fm = extract(path)
        except SystemExit:
            fm = None
        scope = fm.get("scope") if isinstance(fm, dict) else None
        tier = scope or tier_folder_of(path.relative_to(repo_root)) or "core"
        rows.append({"path": rel, "tier": str(tier), "state": rule_state(rel, ignored, tracked)})
    return rows


def render_rule_map(rows: list[dict]) -> str:
    """Deterministic markdown, no timestamp: it is rewritten on every run."""

    def cell(value) -> str:
        flat = " ".join(str(value).split())
        return flat.replace("\\", "\\\\").replace("|", "\\|")

    out = [
        "# Rule scope map",
        "",
        "Derived from the local tree by `scripts/validate-bridge.py`, and never",
        "committed. The authoritative tier is the `scope:` frontmatter in each rule;",
        "this table is a view of it, plus the one thing frontmatter cannot express,",
        "namely whether a NEW rule may be authored at that path.",
        "",
    ]
    out += [f"- `{state}`: {meaning}" for state, meaning in STATE_MEANING.items()]
    out += ["", "| rule | tier | state |", "|---|---|---|"]
    out += [f"| {cell(r['path'])} | {cell(r['tier'])} | {cell(r['state'])} |" for r in rows]
    if not rows:
        out.append("| (no rules found) | | |")
    out.append("")
    return "\n".join(out)


def write_rule_map(repo_root) -> Path:
    """Refresh `.bridge/rule-scope.md` and return its path."""
    repo_root = Path(repo_root)
    out = repo_root / RULE_MAP_REL
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_rule_map(collect_rule_rows(repo_root)), encoding="utf-8")
    return out


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
        elif (tier := tier_folder_of(rel)) and tier != scope:
            # AGENTS.md § Rules: the FOLDER is the tier, and the frontmatter must
            # AGREE with it. Checking only that a `scope:` exists lets the two
            # disagree silently — and then the router (folder) and the reader
            # (frontmatter) believe different things about the same file.
            print(f"  FAIL  {rel} — in rules/{tier}/ but declares scope '{scope}'"
                  f" — folder and frontmatter disagree")
            failed += 1
        else:
            print(f"  PASS  {rel} [scope: {scope}]")
            passed += 1
    return (passed, failed)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Bridge configs against schemas")
    parser.add_argument("--surface", help="Validate only this surface (e.g. persona, rules)")
    parser.add_argument("--list", action="store_true", help="List discovered files and exit")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate only; do not refresh .bridge/rule-scope.md",
    )
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
            # check-jsonschema is strongly recommended but optional — a fresh
            # clone without it must NOT hard-fail onboarding's final step.
            # Emit an advisory (yellow) warning, skip the JSON-Schema surfaces,
            # and continue: the run's exit code reflects real validation only.
            sys.stderr.write(
                "\033[33mWARN: check-jsonschema not found in PATH — "
                "schema validation skipped.\033[0m\n"
                "  Install to enable it: pipx install check-jsonschema\n"
                "  (or: uv tool install check-jsonschema)\n"
            )
        else:
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

    # Refreshed even on a failing run: the inventory answers "what exists and
    # where may I author", which is independent of what currently passes.
    if not args.check:
        print(f"Rule map: {write_rule_map(REPO_ROOT).relative_to(REPO_ROOT)}")

    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
