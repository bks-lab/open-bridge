#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Deterministic repo inventory — the factual seed for a repo→architecture explainer.

Before any LLM reasons about a codebase's architecture, ground it in facts: what
languages, how big, where the entry points are, what it depends on, what docs
already exist. This script produces that seed so the analysis cites reality
instead of guessing (SOUL: verify before claim). It reasons about NOTHING — it
only counts and parses manifests. The architecture interpretation happens after,
in references/repo-analysis.md.

Output (text by default, --json for the fan-out to consume):
  - languages by LOC + file count
  - candidate entry points (main.rs, index.ts, __main__.py, cmd/*, bin/*, …)
  - parsed dependency manifests (Cargo.toml, package.json, pyproject.toml, go.mod,
    requirements.txt) → package name + direct dependency names
  - top-level structure (immediate subdirs, file count, dominant language)
  - documentation files (README*, ARCHITECTURE*, docs/**.md) with LOC — these are
    the doc-driven shortcut candidates

Usage:
  repo-scan.py [path] [--json] [--max-loc-file BYTES]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ImportError:
    tomllib = None

SKIP_DIRS = {
    ".git", "node_modules", "target", "dist", "build", ".venv", "venv",
    "__pycache__", ".next", ".nuxt", ".cache", "vendor", ".idea", ".vscode",
    "coverage", ".pytest_cache", ".mypy_cache", ".turbo", "out", ".gradle",
}
EXT_LANG = {
    ".rs": "Rust", ".py": "Python", ".ts": "TypeScript", ".tsx": "TypeScript",
    ".js": "JavaScript", ".jsx": "JavaScript", ".go": "Go", ".java": "Java",
    ".kt": "Kotlin", ".rb": "Ruby", ".php": "PHP", ".c": "C", ".h": "C/C++ header",
    ".cpp": "C++", ".cc": "C++", ".cs": "C#", ".swift": "Swift", ".scala": "Scala",
    ".sh": "Shell", ".sql": "SQL", ".html": "HTML", ".css": "CSS", ".scss": "CSS",
    ".vue": "Vue", ".svelte": "Svelte", ".md": "Markdown", ".yaml": "YAML",
    ".yml": "YAML", ".toml": "TOML", ".json": "JSON", ".proto": "Protobuf",
}
# Matches entry points even when nested in workspace/monorepo members.
ENTRY_RE = re.compile(
    r"(^|/)(main\.(rs|go|py)|__main__\.py|app\.py|manage\.py"
    r"|index\.(ts|js|mjs)|server\.(ts|js)|Main\.java)$"
)
DOC_RE = re.compile(r"(readme|architecture|design|overview|adr|rfc)", re.I)


def is_text(p: Path, sniff: int = 2048) -> bool:
    try:
        with p.open("rb") as fh:
            return b"\x00" not in fh.read(sniff)
    except OSError:
        return False


def count_loc(p: Path, cap: int) -> int:
    try:
        if p.stat().st_size > cap:
            return 0
        with p.open("r", encoding="utf-8", errors="ignore") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


def walk(root: Path, cap: int):
    langs: dict[str, dict] = {}
    entries, docs, manifests = [], [], []
    top: dict[str, dict] = {}
    for path in root.rglob("*"):
        parts = set(path.relative_to(root).parts)
        if parts & SKIP_DIRS:
            continue
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        ext = path.suffix.lower()
        lang = EXT_LANG.get(ext)
        loc = count_loc(path, cap) if lang and is_text(path) else 0
        if lang:
            d = langs.setdefault(lang, {"files": 0, "loc": 0})
            d["files"] += 1
            d["loc"] += loc
        # top-level bucket
        top_key = path.relative_to(root).parts[0] if len(path.relative_to(root).parts) > 1 else "(root)"
        t = top.setdefault(top_key, {"files": 0, "loc": 0, "langs": {}})
        t["files"] += 1
        t["loc"] += loc
        if lang:
            t["langs"][lang] = t["langs"].get(lang, 0) + loc
        # entry points (skip test/example trees to avoid noise)
        if ENTRY_RE.search(rel) and not re.search(r"(^|/)(tests?|examples?|benches|fixtures)/", rel):
            entries.append(rel)
        # docs
        if ext == ".md" and (DOC_RE.search(path.name) or rel.startswith("docs/")):
            docs.append({"path": rel, "loc": loc})
        # manifests
        if path.name in ("Cargo.toml", "package.json", "pyproject.toml", "go.mod", "requirements.txt", "pom.xml", "build.gradle"):
            manifests.append(path)
    return langs, entries, docs, manifests, top


def parse_toml(p: Path) -> dict:
    if tomllib:
        try:
            return tomllib.loads(p.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            return {}
    return {}


def parse_manifest(p: Path) -> dict:
    name = p.name
    out = {"file": None, "name": None, "deps": []}
    try:
        if name == "Cargo.toml":
            data = parse_toml(p)
            out["name"] = (data.get("package") or {}).get("name")
            if data:
                out["deps"] = sorted((data.get("dependencies") or {}).keys())
            else:  # tomllib unavailable — regex the [dependencies] table
                tail = p.read_text(errors="ignore").split("[dependencies]")[-1]
                out["deps"] = re.findall(r"(?m)^\s*([A-Za-z0-9_-]+)\s*=", tail)
        elif name == "package.json":
            data = json.loads(p.read_text(encoding="utf-8", errors="ignore"))
            out["name"] = data.get("name")
            out["deps"] = sorted(list((data.get("dependencies") or {}).keys()) + list((data.get("devDependencies") or {}).keys()))
        elif name == "pyproject.toml":
            data = parse_toml(p)
            proj = data.get("project") or {}
            out["name"] = proj.get("name") or ((data.get("tool") or {}).get("poetry") or {}).get("name")
            out["deps"] = [re.split(r"[<>=!~ \[]", d, maxsplit=1)[0] for d in (proj.get("dependencies") or [])]
        elif name == "go.mod":
            txt = p.read_text(encoding="utf-8", errors="ignore")
            m = re.search(r"^module\s+(\S+)", txt, re.M)
            out["name"] = m.group(1) if m else None
            out["deps"] = re.findall(r"^\s+(\S+)\s+v[0-9]", txt, re.M)
        elif name == "requirements.txt":
            out["name"] = p.parent.name
            out["deps"] = [re.split(r"[<>=!~ ;\[]", ln, maxsplit=1)[0].strip()
                           for ln in p.read_text(errors="ignore").splitlines()
                           if ln.strip() and not ln.strip().startswith("#")]
    except Exception:
        pass
    out["file"] = p.name
    out["deps"] = sorted({d for d in (out["deps"] or []) if d})[:60]
    return out


def build(root: Path, cap: int) -> dict:
    langs, entries, docs, manifests, top = walk(root, cap)
    return {
        "repo": root.name,
        "path": str(root),
        "languages": dict(sorted(langs.items(), key=lambda kv: -kv[1]["loc"])),
        "entry_points": sorted(set(entries)),
        "manifests": [parse_manifest(m) for m in manifests],
        "docs": sorted(docs, key=lambda d: -d["loc"])[:40],
        "top_level": {
            k: {"files": v["files"], "loc": v["loc"],
                "dominant": max(v["langs"], key=v["langs"].get) if v["langs"] else None}
            for k, v in sorted(top.items(), key=lambda kv: -kv[1]["loc"])
        },
    }


def render_text(r: dict) -> str:
    L = [f"# Repo scan: {r['repo']}  ({r['path']})", ""]
    L.append("## Languages (by LOC)")
    for lang, d in list(r["languages"].items())[:12]:
        L.append(f"  {lang:<16} {d['loc']:>8} LOC  ·  {d['files']} files")
    L.append("\n## Entry-point candidates")
    L += [f"  {e}" for e in r["entry_points"]] or ["  (none matched heuristics — inspect manually)"]
    L.append("\n## Dependency manifests")
    for m in r["manifests"]:
        L.append(f"  {m['file']}  →  name={m['name']}  ({len(m['deps'])} direct deps)")
        if m["deps"]:
            L.append("    " + ", ".join(m["deps"][:24]) + (" …" if len(m["deps"]) > 24 else ""))
    L.append("\n## Top-level structure")
    for k, v in list(r["top_level"].items())[:20]:
        L.append(f"  {k:<22} {v['files']:>5} files · {v['loc']:>7} LOC · {v['dominant'] or '—'}")
    L.append("\n## Documentation (doc-driven-shortcut candidates)")
    for d in r["docs"][:20]:
        L.append(f"  {d['loc']:>5} LOC  {d['path']}")
    L.append("\n→ Next: references/repo-analysis.md (doc-driven shortcut if a big arch doc exists, else code-driven fan-out).")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description="Deterministic repo inventory for repo→architecture explainers")
    ap.add_argument("path", nargs="?", default=".")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--max-loc-file", type=int, default=2_000_000, help="skip LOC count above this byte size")
    args = ap.parse_args()
    root = Path(args.path).resolve()
    if not root.is_dir():
        sys.exit(f"repo-scan: not a directory: {root}")
    r = build(root, args.max_loc_file)
    print(json.dumps(r, indent=2, ensure_ascii=False) if args.json else render_text(r))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
