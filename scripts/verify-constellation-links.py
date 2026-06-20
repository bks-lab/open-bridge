#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Verify every link the constellation builds — auth-aware version.

Internal paths (the-bridge/blob/.../...): verified via `git ls-tree origin/<branch>`
External bks-lab repos: verified via `gh repo view`
External public URLs: HTTP HEAD with redirect-aware status check
"""
from __future__ import annotations
import re
import subprocess
import sys
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

REPO_ROOT = Path(__file__).resolve().parents[1]
HTML = REPO_ROOT / "docs/repo-layout/network.html"
OWNER = "bks-lab"
NAME = "open-bridge"
USER_BRANCH = "user/your-name"
CORE_BRANCH = "main"

NODE_RX = re.compile(r"\{\s*id:\s*'([^']+)'.*?\}", re.DOTALL)
def field(key): return re.compile(rf"\b{key}\s*:\s*'([^']+)'")
PATH_RX, TPL_RX, EXTREP_RX, EXTURL_RX = field("path"), field("template"), field("externalRepo"), field("externalUrl")
GITIG_RX = re.compile(r"\bgitignored\s*:\s*true\b")


BRANCH_OVERRIDES = {
    "skills/customer-a-coordinator/": "user",
    ".claude/agents/customer-a-log-analyst.md": "user",
    ".claude/agents/customer-a-deployment-verifier.md": "user",
    ".claude/agents/network-reconcile.md": "user",
    "identity/personas/_template.yaml": "user",
    "identity/accounts/_template.yaml": "user",
    "identity/mandants/_template.yaml": "user",
    "workflow/contexts/_template.yaml": "user",
    "docs/examples/projects/operational.yaml": "user",
}


def branch_for_path(path: str, live_files: dict | None = None) -> str:
    p = path.lstrip("/")
    # 0. LIVE branch files (state.json schema >= 3) — authoritative
    if live_files and live_files.get("core") is not None and live_files.get("user") is not None:
        is_dir = p.endswith("/")
        on_core = any(f.startswith(p) for f in live_files["core"]) if is_dir else p in live_files["core"]
        on_user = any(f.startswith(p) for f in live_files["user"]) if is_dir else p in live_files["user"]
        if on_user and not on_core: return USER_BRANCH
        if on_core and not on_user: return CORE_BRANCH
        # both or neither → fall through
    if p in BRANCH_OVERRIDES:
        return USER_BRANCH if BRANCH_OVERRIDES[p] == "user" else CORE_BRANCH
    CORE_PREFIXES = (
        "CLAUDE.md", "README.md", "AGENTS.md", "DESIGN.md",
        "ecosystem.yaml", "docs/", "rules/", "themes/", "trackers/", "skills/",
        ".claude/commands/", "examples/",
    )
    if re.search(r"_template(s)?(\.|/|$)", p): return CORE_BRANCH
    if re.search(r"_schema(\.|/|$)", p): return CORE_BRANCH
    for pref in CORE_PREFIXES:
        if p == pref or p.startswith(pref): return CORE_BRANCH
    if p.startswith("protocols/standing-orders/user/"): return USER_BRANCH
    if p.startswith("protocols/"): return CORE_BRANCH
    if p.startswith(".claude/agents/"): return CORE_BRANCH
    return USER_BRANCH


def git_path_exists(branch: str, path: str) -> tuple[bool, str]:
    """Check if path exists in remote branch via local refs.

    Uses origin/<branch> assumed to be up-to-date (we just pushed).
    Returns (exists, info).
    """
    ref = f"origin/{branch}"
    clean = path.rstrip("/")
    try:
        # ls-tree returns a line if the entry exists, else empty
        out = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", ref, clean],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=10,
        )
        if out.returncode != 0:
            # Maybe the ref doesn't exist or path is a file
            tree = subprocess.run(
                ["git", "ls-tree", ref, clean],
                cwd=REPO_ROOT, capture_output=True, text=True, timeout=10,
            )
            return (bool(tree.stdout.strip()), tree.stderr.strip() or tree.stdout.strip())
        # Either a directory listing (multi-line) or a single file (one line)
        return (bool(out.stdout.strip()), "exists" if out.stdout.strip() else "not in tree")
    except subprocess.TimeoutExpired:
        return (False, "timeout")
    except Exception as e:
        return (False, str(e))


def gh_repo_exists(slug: str) -> tuple[bool, str]:
    try:
        out = subprocess.run(
            ["gh", "repo", "view", slug, "--json", "name,visibility"],
            capture_output=True, text=True, timeout=15,
        )
        if out.returncode == 0:
            return (True, out.stdout.strip()[:60])
        return (False, out.stderr.strip()[:120])
    except Exception as e:
        return (False, str(e))


def http_ok(url: str, timeout: float = 8.0) -> tuple[bool, int | str]:
    try:
        req = Request(url, method="HEAD", headers={"User-Agent": "constellation-verifier/2"})
        with urlopen(req, timeout=timeout) as r:
            return (200 <= r.status < 400, r.status)
    except HTTPError as e:
        # Some sites return 405 on HEAD but work for GET — try GET
        if e.code in (405, 403):
            try:
                req = Request(url, method="GET", headers={"User-Agent": "constellation-verifier/2"})
                with urlopen(req, timeout=timeout) as r:
                    return (200 <= r.status < 400, r.status)
            except Exception as e2:
                return (False, str(e2))
        return (False, e.code)
    except URLError as e:
        return (False, str(e.reason))
    except Exception as e:
        return (False, str(e))


def extract_nodes(html: str) -> list[dict]:
    nodes_start = html.find("const NODES = [")
    nodes_end = html.find("];", nodes_start)
    block = html[nodes_start:nodes_end]
    out: list[dict] = []
    for m in NODE_RX.finditer(block):
        body = m.group(0)
        node = {"id": m.group(1)}
        for key, rx in [("path", PATH_RX), ("template", TPL_RX),
                        ("externalRepo", EXTREP_RX), ("externalUrl", EXTURL_RX)]:
            mm = rx.search(body)
            if mm: node[key] = mm.group(1)
        node["gitignored"] = bool(GITIG_RX.search(body))
        out.append(node)
    return out


def load_live_files() -> dict | None:
    """Try to load branch_files from live state.json (schema_version 3)."""
    import json
    from urllib.request import urlopen
    try:
        with urlopen("http://homeserver:8793/state.json", timeout=5) as r:
            d = json.loads(r.read().decode("utf-8"))
        if d.get("schema_version", 0) >= 3 and d.get("branch_files"):
            return d["branch_files"]
    except Exception as e:
        print(f"(state.json fetch skipped: {e})", file=sys.stderr)
    return None


def main() -> int:
    if not HTML.exists():
        print(f"NOTICE: {HTML.relative_to(REPO_ROOT)} is not present "
              "(rendered on demand, not committed) — nothing to verify.",
              file=sys.stderr)
        return 0
    html = HTML.read_text(encoding="utf-8")
    nodes = extract_nodes(html)

    # Make sure refs are fresh
    print("Fetching origin refs...", file=sys.stderr)
    subprocess.run(["git", "fetch", "origin", "--quiet"], cwd=REPO_ROOT, timeout=30)

    live_files = load_live_files()
    if live_files:
        print(f"Live branch_files loaded: core={len(live_files['core'])}, user={len(live_files['user'])}\n")
    else:
        print("Live branch_files unavailable — using BRANCH_OVERRIDES + heuristic\n")

    # Curry live_files into the resolver so call sites pass only path
    resolve_branch = (lambda p: branch_for_path(p, live_files))  # noqa: E731

    print(f"Parsed {len(nodes)} nodes from {HTML.name}\n")
    failures: list[tuple[str, str, str]] = []
    pass_count = 0
    skip_count = 0

    for n in nodes:
        nid = n["id"]
        # 1. path → local exists + git tree exists (unless gitignored — only check local)
        if "path" in n:
            path = n["path"]
            local = REPO_ROOT / path.rstrip("/")
            if not local.exists():
                failures.append((nid, "local-missing", str(path)))
                print(f"  FAIL {nid:30s} local missing: {path}")
            else:
                pass_count += 1

            if not n["gitignored"]:
                branch = resolve_branch(path)
                ok, info = git_path_exists(branch, path)
                tag = "git-blob" if not path.endswith("/") else "git-tree"
                if ok:
                    print(f"  ok   {nid:30s} {tag} @{branch} → {path}")
                    pass_count += 1
                else:
                    failures.append((nid, "git-tree-missing", f"@{branch} {path}: {info}"))
                    print(f"  FAIL {nid:30s} {tag} @{branch} {path}: {info}")
            else:
                # gitignored → only verify locally
                skip_count += 1

        # 2. template (always CORE; tracked)
        if "template" in n:
            tpl_path = n["template"]
            tpl_local = REPO_ROOT / tpl_path
            if not tpl_local.exists():
                failures.append((nid, "template-local-missing", tpl_path))
                print(f"  FAIL {nid:30s} template local missing: {tpl_path}")
            else:
                tpl_branch = resolve_branch(tpl_path)
                ok, info = git_path_exists(tpl_branch, tpl_path)
                if ok:
                    print(f"  ok   {nid:30s} tpl @{tpl_branch} → {tpl_path}")
                    pass_count += 1
                else:
                    failures.append((nid, "template-git-missing", f"@{tpl_branch} {tpl_path}: {info}"))
                    print(f"  FAIL {nid:30s} tpl @{tpl_branch} {tpl_path}: {info}")

        # 3. externalRepo → gh repo view
        if "externalRepo" in n:
            slug = n["externalRepo"]
            ok, info = gh_repo_exists(slug)
            if ok:
                print(f"  ok   {nid:30s} ext-repo {slug}  ({info})")
                pass_count += 1
            else:
                failures.append((nid, "ext-repo-missing", f"{slug}: {info}"))
                print(f"  FAIL {nid:30s} ext-repo {slug}: {info}")

        # 4. externalUrl → HTTP HEAD (skip auth-walled)
        if "externalUrl" in n:
            url = n["externalUrl"]
            auth_walled = any(d in url for d in [
                "portal.azure.com", "sharepoint.com", "vault.azure.net",
                "kb.eu-central-1.aws.cloud.es.io", "homeserver:",
            ]) or re.search(r"github\.com/orgs/[^/]+/projects/\d+$", url)
            ok, status = http_ok(url)
            if ok:
                print(f"  ok   {nid:30s} ext-url  {status} {url}")
                pass_count += 1
            elif auth_walled:
                print(f"  skip {nid:30s} ext-url  {status} {url}  (auth-walled)")
                skip_count += 1
            else:
                # For org URL etc., try gh api
                if "github.com/orgs/" in url:
                    failures.append((nid, "ext-url-fail", f"{status} {url} (check manually)"))
                else:
                    failures.append((nid, "ext-url-fail", f"{status} {url}"))
                print(f"  FAIL {nid:30s} ext-url  {status} {url}")

    print(f"\n{'-'*60}")
    print(f"Pass: {pass_count} · Skip: {skip_count} · Fail: {len(failures)}")
    if failures:
        print("\nFAILURES (must-fix):")
        for nid, kind, detail in failures:
            print(f"  · {nid}: {kind} → {detail}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
