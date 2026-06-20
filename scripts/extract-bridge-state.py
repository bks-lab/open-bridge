#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Extract live bridge state for the repo-layout v3 live-reload.

Outputs a JSON document on stdout with:
- branch, ahead/behind vs development
- last 50 work/log.md entries (timestamp, type, context, what)
- last 20 git commits (sha, ts, subject, files-touched)
- generated_at ISO timestamp

Designed to be cheap (<1s) so it can run on a 60s launchd cadence.
"""
from __future__ import annotations
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def run(cmd: list[str], cwd: Path = REPO) -> str:
    try:
        return subprocess.run(
            cmd, cwd=cwd, check=True, capture_output=True, text=True
        ).stdout
    except subprocess.CalledProcessError:
        return ""


def branch_state() -> dict:
    branch = run(["git", "branch", "--show-current"]).strip()
    counts = run(
        ["git", "rev-list", "--left-right", "--count", "HEAD...development"]
    ).strip().split()
    ahead, behind = (int(counts[0]), int(counts[1])) if len(counts) == 2 else (0, 0)
    last_dev = run(["git", "log", "-1", "--format=%cI", "development"]).strip()
    return {"branch": branch, "ahead": ahead, "behind": behind, "last_sync": last_dev}


def parse_log_md() -> list[dict]:
    p = REPO / "work" / "log.md"
    if not p.exists():
        return []
    rx = re.compile(
        r"^\|\s*(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})\s*"
        r"\|\s*([^|]+?)\s*"
        r"\|\s*([^|]+?)\s*"
        r"\|\s*(.+?)\s*\|\s*$"
    )
    rows: list[dict] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        m = rx.match(line)
        if not m:
            continue
        rows.append({
            "ts": f"{m.group(1)}T{m.group(2)}:00",
            "type": m.group(3).strip(),
            "context": m.group(4).strip(),
            "what": m.group(5).strip(),
        })
    return rows[-50:]


def parse_frontmatter(text: str) -> dict:
    """Extract simple `key: value` lines from leading --- ... --- block."""
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    out: dict = {}
    for line in parts[1].splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def active_tasks() -> list[dict]:
    """Scan work/tasks/*/STATUS.md and return summary per task.

    Output: list of {slug, title, status, type, severity, last_updated, body_excerpt}
    Skip dot-prefixed and underscore-prefixed (e.g. _meetings/).
    """
    base = REPO / "work" / "tasks"
    if not base.is_dir():
        return []
    out: list[dict] = []
    for d in sorted(base.iterdir()):
        if not d.is_dir() or d.name.startswith(("_", ".")):
            continue
        st = d / "STATUS.md"
        if not st.exists():
            continue
        try:
            text = st.read_text(encoding="utf-8")
        except Exception:
            continue
        fm = parse_frontmatter(text)
        # First non-blank, non-front-matter line as fallback excerpt
        body = text.split("---", 2)[-1] if text.startswith("---") else text
        excerpt = ""
        for ln in body.splitlines():
            s = ln.strip()
            if s and not s.startswith("#"):
                excerpt = s[:160]
                break
        out.append({
            "slug": d.name,
            "title": fm.get("title", d.name).strip("\"'"),
            "status": fm.get("status", ""),
            "type": fm.get("type", ""),
            "severity": fm.get("severity", ""),
            "context": fm.get("context", ""),
            "last_updated": fm.get("last_updated", ""),
            "incident_id": fm.get("incident_id", ""),
            "excerpt": excerpt,
        })
    return out


# Lowercase region IDs that standing orders may reference. Keep this list
# narrow — only well-known top-level dirs the v3 brain renders.
_REGION_KEYWORDS = [
    "work/", "personas/", "mandants/", "calendar/",
    "channels/", "remotes/", "contexts/", "protocols/", "projects/",
    "skills/", "wiki/", "docs/", ".claude/agents/", ".claude/commands/",
    "claude.md", "bridge-config.yaml", "ecosystem.yaml",
]


def standing_orders() -> list[dict]:
    """Scan protocols/standing-orders/*.md, parse frontmatter, derive
    affected regions via keyword scan of body."""
    base = REPO / "protocols" / "standing-orders"
    if not base.is_dir():
        return []
    out: list[dict] = []
    for f in sorted(base.glob("*.md")):
        if f.name.startswith(("_", ".")) or f.name == "README.md":
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        fm = parse_frontmatter(text)
        body = text.split("---", 2)[-1] if text.startswith("---") else text
        body_lc = body.lower()
        regions = sorted({kw for kw in _REGION_KEYWORDS if kw in body_lc})
        out.append({
            "name": fm.get("name", f.stem),
            "scope": fm.get("scope", ""),
            "enforcement": fm.get("enforcement", ""),
            "applies_to": fm.get("applies_to", ""),
            "regions": regions,
            "file": f.name,
        })
    return out


def recent_commits(n: int = 20) -> list[dict]:
    # ASCII GroupSep would be cleaner but Python str.strip() considers
    # it whitespace (!) — use a printable token-pair instead.
    sep = "<<<COMMIT>>>"
    fmt = f"{sep}%H|%cI|%s"
    raw = run(["git", "log", f"-{n}", f"--format={fmt}", "--name-only"]).strip()
    if not raw:
        return []
    out: list[dict] = []
    for blk in raw.split(sep):
        lines = [ln for ln in blk.splitlines() if ln.strip()]
        if not lines:
            continue
        head = lines[0].split("|", 2)
        if len(head) < 3:
            continue
        sha, ts, subj = head
        files = lines[1:]
        out.append({"sha": sha[:8], "ts": ts, "subject": subj, "files": files})
    return out


def _list_dir(rel: str, pattern: str = "*.yaml", exclude_prefix: tuple = ("_",), exclude_names: tuple = ()) -> list[str]:
    """List basenames (no extension) of files in REPO/rel matching pattern,
    excluding prefixes and explicit names. Returns sorted list. Cheap; no
    secrets exposed (just filenames)."""
    p = REPO / rel
    if not p.is_dir():
        return []
    out = []
    for f in sorted(p.glob(pattern)):
        if not f.is_file():
            continue
        stem = f.stem
        if stem in exclude_names:
            continue
        if any(stem.startswith(pref) for pref in exclude_prefix):
            continue
        out.append(stem)
    return out


def _list_subdirs(rel: str, exclude_prefix: tuple = ("_", ".")) -> list[str]:
    p = REPO / rel
    if not p.is_dir():
        return []
    out = []
    for d in sorted(p.iterdir()):
        if not d.is_dir():
            continue
        if any(d.name.startswith(pref) for pref in exclude_prefix):
            continue
        out.append(d.name)
    return out


def inventory() -> dict:
    """Filesystem inventory — basename lists. Used by constellation for
    drift audit (which skills/agents are visualized vs. exist)."""
    # mandants are flat: identity/mandants/<id>.yaml
    mandants = sorted(
        f.stem.removeprefix("mandant.")
        for f in REPO.glob("identity/mandants/*.yaml")
    )
    contexts = sorted(
        f.stem.removeprefix("context.")
        for f in REPO.glob("workflow/contexts/*.yaml")
    )
    projects = sorted(
        f.stem.removeprefix("project.")
        for f in REPO.glob("workflow/projects/*.yaml")
    )
    return {
        "skills": _list_subdirs("skills"),
        "agents": _list_dir(".claude/agents", "*.md", exclude_names=("README",)),
        "remotes": _list_dir("infra/remotes", "*.yaml"),
        "channels": _list_dir("infra/channels", "*.yaml", exclude_prefix=("_",)),
        "rules": _list_dir("rules", "*.md", exclude_names=("README",)),
        "themes": _list_dir("themes", "*.yaml"),
        "trackers": _list_dir("trackers", "*.md", exclude_names=("README",)),
        "standing_orders": _list_dir("protocols/standing-orders", "*.md", exclude_names=("README",)),
        "personas": _list_dir("identity/personas", "*.yaml"),
        "accounts": _list_dir("identity/accounts", "*.yaml"),
        "mandants": mandants,
        "contexts": contexts,
        "projects": projects,
        "work_active": _list_subdirs("work/tasks"),
    }


def counts(inv: dict) -> dict:
    """Counts derived from inventory (single source of truth)."""
    return {k: len(v) for k, v in inv.items()}


def branch_files() -> dict:
    """Tracked files per branch, restricted to interesting prefixes the
    constellation might link to. Used by network.html to determine the
    authoritative branch for any visualized path (eliminates static overrides)."""
    PREFIXES = (
        "CLAUDE.md", "README.md", "AGENTS.md", "DESIGN.md",
        "ecosystem.yaml",
        "docs/", "rules/", "themes/", "trackers/", "skills/",
        ".claude/", "examples/", "protocols/",
        "identity/", "infra/", "workflow/",
        "work/",
    )
    out = {"core": [], "user": []}
    for branch, key in [("development", "core"), ("user/user", "user")]:
        raw = run(["git", "ls-tree", "-r", "--name-only", f"origin/{branch}"])
        if not raw:
            continue
        files = [f for f in raw.splitlines() if any(f.startswith(p) for p in PREFIXES)]
        out[key] = sorted(files)
    return out


def main() -> int:
    inv = inventory()
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": 3,
        "branch_state": branch_state(),
        "log": parse_log_md(),
        "active_tasks": active_tasks(),
        "standing_orders": standing_orders(),
        "commits": recent_commits(20),
        "counts": counts(inv),
        "inventory": inv,
        "branch_files": branch_files(),
    }
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=None)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
