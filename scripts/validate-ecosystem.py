#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Validate cross-references in ecosystem.yaml.

Catches the class of drift where a repo gets renamed, archived, or removed
but references to it stay in workspaces / depends_on / wiki_ref. The bridge
loads ecosystem.yaml at session start and downstream tooling (briefing,
dashboard, tracker fan-out) breaks silently on dangling refs.

Exit codes:
  0 — all refs resolve (warnings may have been printed)
  1 — at least one hard error (dangling ref, malformed format)

Checks:
  workspaces.*.repos[]  → key must exist somewhere in the repo registry
  depends_on (per repo) → key must exist somewhere in the repo registry
  wiki_ref              → dotted path must resolve against base.<target>
  issue_repo            → must be "<org>/<repo>" format
  github                → must be "<org>/<repo>" format
  local_path            → must start with ~/ or /
  workspace ref         → warn if target has status: archived
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("ERROR: PyYAML not installed. pip install pyyaml\n")
    sys.exit(2)


REPO_PATH_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")


class Report:
    def __init__(self):
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def err(self, path: str, msg: str) -> None:
        self.errors.append(f"ERROR  {path}: {msg}")

    def warn(self, path: str, msg: str) -> None:
        self.warnings.append(f"WARN   {path}: {msg}")

    def emit(self) -> int:
        for line in self.warnings:
            print(line, file=sys.stderr)
        for line in self.errors:
            print(line, file=sys.stderr)
        if self.errors:
            print(f"\n{len(self.errors)} error(s), {len(self.warnings)} warning(s).",
                  file=sys.stderr)
            return 1
        if self.warnings:
            print(f"\n0 errors, {len(self.warnings)} warning(s).", file=sys.stderr)
        else:
            print("ecosystem.yaml: all cross-refs resolve.", file=sys.stderr)
        return 0


def collect_repos(data: dict) -> dict[str, dict]:
    """Flatten every repo-like entry into {key: node} from all known sections.

    Sections scanned: base, customers.*.repos, customers.*.packages,
    projects.*.repos, projects.*.packages, partners.*.repos, internal,
    personal, references.
    Repos/packages elsewhere are ignored (not part of the cross-ref surface).
    """
    registry: dict[str, dict] = {}

    def absorb(section: dict | None, label: str) -> None:
        if not isinstance(section, dict):
            return
        for key, node in section.items():
            if not isinstance(node, dict):
                continue
            if key in registry:
                # Collision is unusual but not an error — first wins for the
                # registry, cross-ref resolution succeeds either way.
                continue
            registry[key] = {**node, "__section__": label}

    absorb(data.get("base"), "base")
    for cust_key, cust in (data.get("customers") or {}).items():
        if isinstance(cust, dict):
            absorb(cust.get("repos"), f"customers.{cust_key}.repos")
            absorb(cust.get("packages"), f"customers.{cust_key}.packages")
    for proj_key, proj in (data.get("projects") or {}).items():
        if isinstance(proj, dict):
            absorb(proj.get("repos"), f"projects.{proj_key}.repos")
            absorb(proj.get("packages"), f"projects.{proj_key}.packages")
    for partner_key, partner in (data.get("partners") or {}).items():
        if isinstance(partner, dict):
            absorb(partner.get("repos"), f"partners.{partner_key}.repos")
    absorb(data.get("internal"), "internal")
    absorb(data.get("personal"), "personal")
    absorb(data.get("references"), "references")

    return registry


def resolve_dotted(registry: dict[str, dict], dotted: str) -> object:
    """Resolve 'wiki.areas.customer-a' — first segment must be a repo key in
    the flat registry (e.g. 'wiki' defined in base), remaining segments
    traverse into that node. Returns None if any segment is missing."""
    segs = dotted.split(".")
    if not segs:
        return None
    head, *rest = segs
    cur: object = registry.get(head)
    for seg in rest:
        if not isinstance(cur, dict) or seg not in cur:
            return None
        cur = cur[seg]
    return cur


def check_format(report: Report, path: str, field: str, value: object) -> None:
    if field in ("github", "issue_repo"):
        if not isinstance(value, str) or not REPO_PATH_RE.match(value):
            report.err(path, f"{field} must match '<org>/<repo>', got: {value!r}")
    elif field == "local_path":
        if not isinstance(value, str) or not (value.startswith("~/") or value.startswith("/")):
            report.err(path, f"local_path must start with ~/ or /, got: {value!r}")


def check_repo_node(report: Report, path: str, node: dict) -> None:
    """Per-repo format + depends_on checks. Cross-ref resolution happens
    separately (needs the flat registry)."""
    for field in ("github", "issue_repo", "local_path"):
        if field in node:
            check_format(report, path, field, node[field])


def check_workspaces(report: Report, data: dict, registry: dict[str, dict]) -> None:
    for ws_key, ws in (data.get("workspaces") or {}).items():
        if not isinstance(ws, dict):
            continue
        repos = ws.get("repos")
        if not isinstance(repos, list):
            continue
        path = f"workspaces.{ws_key}.repos"
        for repo_ref in repos:
            if not isinstance(repo_ref, str):
                report.err(path, f"entry must be a string, got: {repo_ref!r}")
                continue
            if repo_ref not in registry:
                report.err(path, f"unknown repo reference: '{repo_ref}'")
                continue
            target = registry[repo_ref]
            if target.get("status") == "archived":
                report.warn(
                    path,
                    f"'{repo_ref}' is status=archived — still listed in active workspace",
                )


def check_depends_on(report: Report, registry: dict[str, dict]) -> None:
    for repo_key, node in registry.items():
        deps = node.get("depends_on")
        if deps is None:
            continue
        if not isinstance(deps, list):
            report.err(f"{node['__section__']}.{repo_key}.depends_on",
                       f"must be a list, got: {type(deps).__name__}")
            continue
        path = f"{node['__section__']}.{repo_key}.depends_on"
        for dep in deps:
            if not isinstance(dep, str):
                report.err(path, f"entry must be a string, got: {dep!r}")
                continue
            if dep not in registry:
                report.err(path, f"unknown package reference: '{dep}'")


def check_wiki_refs(report: Report, data: dict, registry: dict[str, dict]) -> None:
    for cust_key, cust in (data.get("customers") or {}).items():
        if not isinstance(cust, dict) or "wiki_ref" not in cust:
            continue
        dotted = cust["wiki_ref"]
        path = f"customers.{cust_key}.wiki_ref"
        if not isinstance(dotted, str):
            report.err(path, f"must be a string, got: {dotted!r}")
            continue
        resolved = resolve_dotted(registry, dotted)
        if resolved is None:
            report.err(path, f"unresolved path: '{dotted}'")


def check_formats(report: Report, data: dict, registry: dict[str, dict]) -> None:
    """Format-only checks that don't need the registry for resolution."""
    for repo_key, node in registry.items():
        check_repo_node(report, f"{node['__section__']}.{repo_key}", node)

    # github_projects top-level list
    for i, project in enumerate(data.get("github_projects") or []):
        if not isinstance(project, dict):
            continue
        if "issue_repo" in project:
            check_format(report, f"github_projects[{i}]", "issue_repo",
                         project["issue_repo"])

    # top-level customers.*.issue_repo
    for cust_key, cust in (data.get("customers") or {}).items():
        if isinstance(cust, dict) and "issue_repo" in cust:
            check_format(report, f"customers.{cust_key}", "issue_repo",
                         cust["issue_repo"])


def validate(path: Path) -> int:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        # Match the CI workflow's graceful behaviour
        # (.github/workflows/validate.yml § ecosystem-validation): a fresh
        # OSS clone has no ecosystem.yaml and that is expected; the file
        # gets created during /bridge-onboard or by hand.
        sys.stderr.write(
            f"NOTICE: {path} not found — skipping cross-ref check "
            f"(expected for fresh OSS clones; create via /bridge-onboard "
            f"or copy from examples/agency/ecosystem.yaml).\n"
        )
        return 0
    except yaml.YAMLError as exc:
        sys.stderr.write(f"ERROR: {path} is not valid YAML: {exc}\n")
        return 2

    if not isinstance(data, dict):
        sys.stderr.write(f"ERROR: {path} must be a YAML mapping at top level\n")
        return 2

    report = Report()
    registry = collect_repos(data)
    check_workspaces(report, data, registry)
    check_depends_on(report, registry)
    check_wiki_refs(report, data, registry)
    check_formats(report, data, registry)

    return report.emit()


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("ecosystem.yaml")
    return validate(target)


if __name__ == "__main__":
    sys.exit(main())
