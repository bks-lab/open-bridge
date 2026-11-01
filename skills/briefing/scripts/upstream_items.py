#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Inbound drift as briefing rows: a `command` section with `covers: [upstream]`.

  - kind: command
    id: upstream
    argv: ["python3", "skills/briefing/scripts/upstream_items.py"]
    covers: [upstream]
    report_ok: true

Reads `upstreams:` from bridge-config.yaml. CORE (no `materialize:` block): fetch the
remote whose URL names the upstream repo (never a remote by name) and count the
commits HEAD does not have. Org overlays: `scripts/overlay.py status --json`. One row
per upstream that needs a person; [] when nothing does. A check that cannot run is a
row: an unreachable upstream must not read as "in sync". Rules behind it:
skills/briefing/references/upstream-summary.md.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]


def _run(argv, cwd=None, timeout=30) -> str:
    p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout).strip().splitlines()[-1] if (p.stderr or p.stdout).strip()
                           else f"exit {p.returncode}")
    return p.stdout


def _row(name: str, title: str, state: str = "ready", url: str = "") -> dict:
    return {"id": f"upstream:{name}", "title": title, "state": state, "raw_state": "drift", "type": "task",
            "url": url, "changed_at": dt.datetime.now().isoformat(timespec="minutes"), "tracker": "upstream",
            "category": "open"}


def _remote_for(repo: str, remotes: str) -> str | None:
    want = repo.lower().removesuffix(".git")
    for line in remotes.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1] == "(fetch)":
            url = re.sub(r"\.git$", "", parts[1].lower())
            if url.endswith("/" + want) or url.endswith(":" + want):
                return parts[0]
    return None


def _url_of(remote: str, remotes: str) -> str:
    for line in remotes.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == remote:
            return parts[1]
    return ""


def _web_page(repo: str, remote_url: str, branch: str) -> str:
    """The upstream's commit list on its web host, when its remote is one; else empty."""
    m = re.match(r"^(?:https?://(?:[^@/]+@)?|ssh://(?:[^@/]+@)?|git@)([\w.-]+?)(?::\d+)?[:/]", remote_url.strip())
    if not m:
        return ""
    host = re.sub(r"^(github\.com|gitlab\.com|bitbucket\.org)-[\w.-]+$", r"\1", m.group(1))
    return f"https://{host}/{repo.removesuffix('.git')}/commits/{branch}"


def core_items(upstreams: list, run=None, cwd=None) -> list:
    run = run or (lambda argv, **k: _run(argv, cwd=cwd))
    out = []
    # CORE is the one `role: oss-core` entry; an org-overlay without `materialize:` is
    # one this Bridge authors, not consumes (references/upstream-summary.md).
    cores = [u for u in upstreams if isinstance(u, dict) and u.get("role") == "oss-core" and u.get("repo")]
    if len(cores) > 1:
        return [_row("core", f"{len(cores)} upstreams carry role: oss-core, exactly one may; CORE drift unknown",
                     "blocked")]
    for u in cores:
        name, repo, branch = u.get("name") or u["repo"], u["repo"], u.get("branch") or "main"
        remotes = run(["git", "remote", "-v"])
        remote = _remote_for(repo, remotes)
        if remote is None:
            out.append(_row(name, f"{repo}: no git remote points at it, inbound drift unknown", "blocked"))
            continue
        try:
            run(["git", "fetch", "--quiet", "--no-tags", remote, branch])
        except Exception as exc:  # noqa: BLE001 - unreachable is a row, never "in sync"
            out.append(_row(name, f"{repo}: could not fetch ({exc}), inbound drift unknown", "blocked"))
            continue
        behind = int(run(["git", "rev-list", "--count", f"HEAD..{remote}/{branch}"]).strip() or 0)
        if behind:
            newest = run(["git", "log", "-1", "--format=%s", f"{remote}/{branch}"]).strip()
            out.append(_row(name, f"{repo}: {behind} commit(s) not merged yet, newest: {newest}",
                            url=_web_page(repo, _url_of(remote, remotes), branch)))
    return out


def overlay_items(data: list) -> list:
    out = []
    for d in data:
        name = d.get("name")
        if d.get("materializes") is False:
            continue          # declared without a `materialize:` block: a promote target, nothing to sync down
        if not d.get("materialized"):
            out.append(_row(name, f"Overlay {name}: subscribed but never materialized (overlay sync {name})"))
            continue
        reasons, state = [], "ready"
        conflicts = (d.get("files") or {}).get("conflict") or 0
        if conflicts:
            reasons.append(f"{conflicts} conflict(s)")
            state = "blocked"
        if d.get("cache_ahead"):
            reasons.append("a newer upstream state waits, sync due")
        if d.get("stale"):
            reasons.append(f"last sync {d.get('days_since_sync')} days ago (interval {d.get('interval_days')})")
        if d.get("plan_error"):
            reasons.append(f"plan error: {d['plan_error']}")
            state = "blocked"
        if reasons:
            out.append(_row(name, f"Overlay {name}: " + ", ".join(reasons) + f" (overlay sync {name})", state))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--root", type=Path, default=ROOT)
    args = ap.parse_args(argv)
    try:
        cfg = yaml.safe_load((args.root / "bridge-config.yaml").read_text(encoding="utf-8")) or {}
    except OSError:
        cfg = {}
    upstreams = [u for u in cfg.get("upstreams") or [] if isinstance(u, dict)]
    rows = core_items(upstreams, cwd=str(args.root))
    if any(u.get("materialize") for u in upstreams):
        overlay = args.root / "scripts" / "overlay.py"
        try:
            data = json.loads(_run([sys.executable, str(overlay), "status", "--json"], cwd=str(args.root),
                                   timeout=120))
            blocks = {u.get("name"): bool(u.get("materialize")) for u in upstreams}
            rows += overlay_items([{**d, "materializes": blocks.get(d.get("name"), True)} for d in data])
        except Exception as exc:  # noqa: BLE001
            rows.append(_row("overlays", f"Overlay state unknown: {exc}", "blocked"))
    print(json.dumps(rows, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
