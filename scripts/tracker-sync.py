#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""tracker-sync — persistent snapshot + bidirectional reconcile for The Bridge.

The Bridge is the cockpit; the GitHub Project is the system of record
(remote-authoritative). This engine has three deterministic subcommands:

  pull   Read each enabled GitHub Project board (via `gh`), normalise the
         items into the shared schema (trackers/README.md) and persist a
         snapshot under work/trackers/<provider>/<slug>.json. Read-only
         against GitHub, safe to run autonomously. git history of the
         snapshot dir == the dated dump an operator would otherwise keep
         by hand. Best-effort: missing/unauthed `gh` warns and skips,
         never blocks (tracker contract).

  diff   Compare the snapshots against every work/tasks|streams/*/STATUS.md
         that declares `sync.github`, and classify each linked issue:
           in_sync · remote_ahead · local_ahead · state_mismatch
           · orphan_local · orphan_remote
         This is the control surface ("which task in which state, what's
         left to do"). Offline, deterministic — never writes anything.

  plan   For every `local_ahead` row, emit the github-projects-manager
         push operation that would bring the board in line with the local
         STATUS (Status field → target option). plan only PROPOSES; the
         actual gated write is executed by skills/tracker-sync via
         github-projects-manager. No STATUS.md is ever auto-written and no
         board is ever auto-pushed.

Dependencies: Python 3 + PyYAML. `gh` only for `pull`.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

# --------------------------------------------------------------------------
# Phase model — collapse fine-grained states into comparable buckets so the
# diff doesn't cry wolf (local `doing` legitimately covers in_progress AND
# review; both sides closed however they got there).
# --------------------------------------------------------------------------

# STATUS.md `status:` enum → bucket
LOCAL_BUCKET = {
    "backlog": "todo",
    "doing": "active",
    "review": "active",
    "done": "closed",
}
# Note: "blocked" is no longer a status — it's the blocked_by: flag (any status).
# classify() takes a `blocked` arg; a flagged task buckets to "blocked".

# normalized tracker state (trackers/README.md) → bucket
REMOTE_BUCKET = {
    "new": "todo",
    "ready": "todo",
    "in_progress": "active",
    "review": "active",
    "blocked": "blocked",
    "done": "closed",
    "removed": "closed",
}

RANK = {"todo": 0, "active": 1, "closed": 2}

# STATUS.md status → the normalized board state we'd push it TO
LOCAL_TO_NORMALIZED = {
    "backlog": "new",
    "doing": "in_progress",
    "review": "review",
    "done": "done",
}

# Fallback raw→normalized map when a board has no registry state_map
# (mirrors trackers/github.md).
DEFAULT_GH_STATE_MAP = {
    "Backlog": "new",
    "Todo": "ready",
    "To Do": "ready",
    "Ready": "ready",
    "Ready for Dev": "ready",
    "In Progress": "in_progress",
    "Doing": "in_progress",
    "In Review": "review",
    "Review": "review",
    "Code Review": "review",
    "Done": "done",
    "Closed": "done",
    "Completed": "done",
    "Declined": "removed",
    "Blocked": "blocked",
}

def normalize_board_state(raw_state: str, state_map: dict | None = None) -> str:
    """Map a board Status option name → normalized state.

    Registry boards carry an exact state_map (emoji included). Registry-LESS
    boards fall back to DEFAULT_GH_STATE_MAP — but real boards prefix options
    with emoji ('✅ Done', '🆕 New'), which plain keys miss. So strip leading
    non-alphanumerics and match case-insensitively. (This is the 2026-06-04
    bug where every card on a registry-less board mapped to 'new'.)"""
    if not raw_state:
        return "new"
    if state_map and raw_state in state_map:
        return state_map[raw_state]
    if raw_state in DEFAULT_GH_STATE_MAP:
        return DEFAULT_GH_STATE_MAP[raw_state]
    core = re.sub(r"^[^0-9A-Za-z]+", "", raw_state).strip().lower()
    for k, v in DEFAULT_GH_STATE_MAP.items():
        if k.lower() == core:
            return v
    return "new"


ACTIONABLE = {
    "remote_ahead",
    "local_ahead",
    "state_mismatch",
    "orphan_local",
    "board_stale",
    "orphan_remote",
}

# stable display order (most actionable first)
CLASS_ORDER = [
    "local_ahead",
    "remote_ahead",
    "state_mismatch",
    "orphan_local",
    "board_stale",
    "orphan_remote",
    "in_sync",
]


def classify(local_status: str, remote_state: str, blocked: bool = False) -> str:
    lb = "blocked" if blocked else LOCAL_BUCKET.get(local_status, "active")
    rb = REMOTE_BUCKET.get(remote_state, "todo")
    if lb == rb:
        return "in_sync"
    if lb == "blocked" or rb == "blocked":
        return "state_mismatch"
    return "remote_ahead" if RANK[rb] > RANK[lb] else "local_ahead"


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------

def repo_root_default() -> Path:
    return Path(__file__).resolve().parents[1]


def parse_frontmatter(path: Path) -> dict:
    """Return the YAML frontmatter (between the first two `---`) as a dict."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    parts = text.split("\n---", 1)
    if len(parts) < 2:
        return {}
    body = parts[0][3:]  # strip leading ---
    try:
        data = yaml.safe_load(body)
        return data if isinstance(data, dict) else {}
    except yaml.YAMLError:
        return {}


def load_snapshots(root: Path) -> list[dict]:
    snaps = []
    store = root / "work" / "trackers"
    if not store.is_dir():
        return snaps
    for jf in sorted(store.rglob("*.json")):
        if jf.name.startswith("_"):
            continue
        try:
            snaps.append(json.loads(jf.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"warning: skipping unreadable snapshot {jf}: {exc}",
                  file=sys.stderr)
    return snaps


def scan_status_tasks(root: Path) -> list[dict]:
    """Every tasks/streams task that declares a github sync binding."""
    tasks = []
    for bucket in ("tasks", "streams"):
        base = root / "work" / bucket
        if not base.is_dir():
            continue
        for status_md in sorted(base.glob("*/STATUS.md")):
            fm = parse_frontmatter(status_md)
            if not fm:
                continue
            sync = fm.get("sync") or {}
            if sync.get("bridge_only"):
                continue
            gh = sync.get("github") or {}
            issues = gh.get("issues") or []
            if not issues:
                continue
            tasks.append({
                "slug": fm.get("slug", status_md.parent.name),
                "status": fm.get("status", "doing"),
                "blocked_by": fm.get("blocked_by"),
                "repo": gh.get("repo"),
                "issues": issues,
                "project": gh.get("project") or {},
                "path": str(status_md.relative_to(root)),
            })
    return tasks


def load_registries(root: Path) -> dict:
    """Map (org, number) → registry dict for github-tracked boards."""
    reg = {}
    base = root / "workflow" / "projects"
    if not base.is_dir():
        return reg
    for yf in sorted(base.glob("*.yaml")):
        if yf.name.startswith("_"):
            continue
        try:
            data = yaml.safe_load(yf.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        proj = data.get("project") or {}
        if proj.get("tracker") != "github":
            continue
        key = (proj.get("org"), proj.get("number"))
        data["_slug"] = (data.get("identity") or {}).get("slug", yf.stem)
        reg[key] = data
    return reg


# --------------------------------------------------------------------------
# diff
# --------------------------------------------------------------------------

ISSUE_URL_RE = re.compile(r"github\.com/([^/]+/[^/]+)/(?:issues|pull)/\d+")


def issue_repo_of(item: dict) -> str | None:
    """owner/repo for a snapshot item — issue numbers are per-repo, so this
    is required to disambiguate (#5 in repo A is NOT #5 in repo B)."""
    m = ISSUE_URL_RE.search(item.get("url") or "")
    if m:
        return m.group(1)
    return item.get("repo")


def build_item_index(snaps: list[dict]) -> tuple[dict, dict]:
    """Returns (by_key, by_num):
       by_key (repo, number) → item  — the correct, collision-free key
       by_num  number        → item  — ambiguous fallback for tasks that
                                        declare issues without a repo."""
    by_key: dict = {}
    by_num: dict = {}
    for snap in snaps:
        for it in snap.get("items", []):
            num = it.get("number")
            if num is None:
                continue
            repo = issue_repo_of(it)
            it["_repo"] = repo
            by_key[(repo, num)] = it
            by_num.setdefault(num, it)
    return by_key, by_num


def compute_rows(root: Path) -> list[dict]:
    snaps = load_snapshots(root)
    by_key, by_num = build_item_index(snaps)
    tasks = scan_status_tasks(root)

    rows = []
    linked: set = set()       # (repo, num) for repo-qualified links
    linked_any: set = set()   # bare num for repo-less links (suppress all repos)

    for task in tasks:
        repo = task.get("repo")
        for issue in task["issues"]:
            if repo:
                linked.add((repo, issue))
                item = by_key.get((repo, issue))
            else:
                linked_any.add(issue)
                item = by_num.get(issue)
            if item is None:
                rows.append({
                    "class": "orphan_local",
                    "issue": issue, "slug": task["slug"],
                    "local": task["status"], "remote": "—",
                    "repo": repo, "url": None, "title": None,
                    "path": task["path"],
                })
                continue
            # Issue lifecycle wins over the board Status field: a closed issue
            # is effectively "done" even if its card never moved off New.
            closed = bool(item.get("closed"))
            eff_remote = "done" if closed else item.get("state", "new")
            disp_remote = (item.get("issue_state") or "closed") if closed \
                else item.get("state", "new")
            rows.append({
                "class": classify(task["status"], eff_remote, blocked=bool(task.get("blocked_by"))),
                "issue": issue, "slug": task["slug"],
                "local": task["status"], "remote": disp_remote,
                "repo": item.get("_repo"), "url": item.get("url"),
                "title": item.get("title"), "path": task["path"],
                "board_state": item.get("state"),
            })

    # Unlinked, assigned-to-me items:
    #   - issue closed but card NOT on a done state ⇒ board_stale (hygiene)
    #   - issue open ⇒ orphan_remote (untracked work)
    for (repo, num), it in by_key.items():
        if (repo, num) in linked or num in linked_any:
            continue
        if not it.get("assigned_to_me"):
            continue
        board_bucket = REMOTE_BUCKET.get(it.get("state", "new"), "todo")
        if it.get("closed"):
            if board_bucket == "closed":
                continue  # closed AND card Done = fully reconciled, skip
            rows.append({
                "class": "board_stale",
                "issue": num, "slug": "(unlinked)",
                "local": f"issue:{it.get('issue_state') or 'closed'}",
                "remote": f"card:{it.get('state')}",
                "repo": repo, "url": it.get("url"),
                "title": it.get("title"), "path": None,
                "board_state": it.get("state"),
            })
            continue
        if board_bucket == "closed":
            continue  # open issue but card already Done — leave it
        rows.append({
            "class": "orphan_remote",
            "issue": num, "slug": "(unlinked)",
            "local": "—", "remote": it.get("state", "new"),
            "repo": repo, "url": it.get("url"),
            "title": it.get("title"), "path": None,
            "board_state": it.get("state"),
        })

    rows.sort(key=lambda r: (CLASS_ORDER.index(r["class"]),
                             r.get("repo") or "", r["issue"]))
    return rows


def render_diff_table(rows: list[dict]) -> str:
    if not rows:
        return "No github-linked tasks found — nothing to reconcile."
    lines = []
    for r in rows:
        line = f"{r['class']} | #{r['issue']} | {r['slug']} | {r['local']}→{r['remote']}"
        detail = [d for d in (r.get("repo"),
                              (r["title"][:48] if r.get("title") else None)) if d]
        if detail:
            line += "  (" + " · ".join(detail) + ")"
        lines.append(line)
    # summary
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["class"]] = counts.get(r["class"], 0) + 1
    summary = "  ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    lines.append("")
    lines.append(f"Summary: {summary}")
    return "\n".join(lines)


def cmd_diff(args) -> int:
    root = Path(args.root).resolve()
    rows = compute_rows(root)
    if args.format == "json":
        print(json.dumps({"rows": rows}, ensure_ascii=False, indent=2))
    else:
        print(render_diff_table(rows))
    if args.exit_code and any(r["class"] in ACTIONABLE for r in rows):
        return 2
    return 0


# --------------------------------------------------------------------------
# plan
# --------------------------------------------------------------------------

def reverse_state_option(registry: dict | None, target_state: str) -> str | None:
    """First board option name whose normalized value == target_state."""
    if not registry:
        return None
    state_map = registry.get("state_map") or {}
    for option, norm in state_map.items():
        if norm == target_state:
            return option
    return None


def compute_plan(root: Path) -> list[dict]:
    rows = compute_rows(root)
    tasks = {(t["slug"]): t for t in scan_status_tasks(root)}
    registries = load_registries(root)
    ops = []
    for r in rows:
        if r["class"] != "local_ahead":
            continue
        task = tasks.get(r["slug"], {})
        proj = task.get("project") or {}
        reg = registries.get((proj.get("org"), proj.get("number")))
        target_state = LOCAL_TO_NORMALIZED.get(r["local"], "in_progress")
        ops.append({
            "tracker": "github",
            "project": proj,
            "issue": r["issue"],
            "repo": task.get("repo"),
            "field": "Status",
            "from_state": r["remote"],
            "from_option": reverse_state_option(reg, r["remote"]),
            "to_state": target_state,
            "to_option": reverse_state_option(reg, target_state),
            "reason": f"local STATUS={r['local']} ahead of board ({r['remote']})",
            "slug": r["slug"],
        })
    return ops


def render_plan_table(ops: list[dict]) -> str:
    if not ops:
        return "No local→remote pushes pending (no local_ahead tasks)."
    lines = ["Pending pushes (gated — execute via skills/tracker-sync → github-projects-manager):"]
    for op in ops:
        frm = op["from_option"] or op["from_state"]
        to = op["to_option"] or op["to_state"]
        lines.append(f"push | #{op['issue']} | {op['slug']} | {frm}→{to}")
    return "\n".join(lines)


def cmd_plan(args) -> int:
    root = Path(args.root).resolve()
    ops = compute_plan(root)
    if args.format == "json":
        print(json.dumps({"operations": ops}, ensure_ascii=False, indent=2))
    else:
        print(render_plan_table(ops))
    return 0


# --------------------------------------------------------------------------
# pull (integration — needs `gh`)
# --------------------------------------------------------------------------

def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "board"


def gh_available() -> bool:
    try:
        subprocess.run(["gh", "auth", "status"],
                       capture_output=True, timeout=15, check=True)
        return True
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return False


def fetch_repo_closed(repo: str, cache: dict) -> dict | None:
    """{issue_number: 'closed'|'merged'} for a repo — one query per kind,
    cached per run. The project board only carries its Status field, not the
    issue lifecycle, so a closed issue can sit on a 'New' card; this is how we
    learn the truth. Returns None on failure (caller leaves items as open)."""
    if repo in cache:
        return cache[repo]
    cmap: dict = {}
    ok = False
    try:
        r = subprocess.run(
            ["gh", "issue", "list", "--repo", repo, "--state", "closed",
             "--json", "number", "--limit", "1000"],
            capture_output=True, text=True, timeout=30, check=True)
        for i in json.loads(r.stdout or "[]"):
            cmap[i["number"]] = "closed"
        ok = True
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError) as exc:
        print(f"warning: issue-state fetch failed for {repo}: {exc}",
              file=sys.stderr)
    try:
        r = subprocess.run(
            ["gh", "pr", "list", "--repo", repo, "--state", "all",
             "--json", "number,state", "--limit", "1000"],
            capture_output=True, text=True, timeout=30, check=True)
        for p in json.loads(r.stdout or "[]"):
            st = (p.get("state") or "").upper()
            if st in ("CLOSED", "MERGED"):
                cmap[p["number"]] = st.lower()
        ok = True
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError) as exc:
        print(f"warning: PR-state fetch failed for {repo}: {exc}",
              file=sys.stderr)
    cache[repo] = cmap if ok else None
    return cache[repo]


def enrich_issue_state(items: list[dict], cache: dict) -> None:
    """Mark each item closed/merged from its repo's lifecycle (in place)."""
    by_repo: dict = {}
    for it in items:
        repo = issue_repo_of(it)
        if repo:
            by_repo.setdefault(repo, []).append(it)
    for repo, its in by_repo.items():
        cmap = fetch_repo_closed(repo, cache)
        if not cmap:
            continue
        for it in its:
            life = cmap.get(it["number"])
            if life:
                it["closed"] = True
                it["issue_state"] = life


def resolve_boards(root: Path, registries: dict) -> list[dict]:
    """Boards to pull, from ecosystem.yaml github_projects."""
    eco = root / "ecosystem.yaml"
    boards = []
    if not eco.is_file():
        return boards
    try:
        data = yaml.safe_load(eco.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return boards
    for entry in data.get("github_projects", []) or []:
        org = entry.get("org")
        number = entry.get("number")
        reg = registries.get((org, number))
        slug = reg["_slug"] if reg else slugify(entry.get("name", f"{org}-{number}"))
        boards.append({
            "org": org,
            "number": number,
            "name": entry.get("name", slug),
            "issue_repo": entry.get("issue_repo"),
            "slug": slug,
            "registry": reg,
        })
    return boards


def normalize_gh_item(raw: dict, board: dict, assignee_me: str | None) -> dict | None:
    content = raw.get("content") or {}
    number = content.get("number")
    if number is None:
        return None  # draft item without a backing issue/PR
    reg = board.get("registry")
    state_map = (reg or {}).get("state_map") or {}
    raw_state = raw.get("status") or ""
    state = normalize_board_state(raw_state, state_map)

    assignees = []
    for a in raw.get("assignees", []) or []:
        assignees.append(a.get("login") if isinstance(a, dict) else a)
    labels = []
    for lab in raw.get("labels", []) or []:
        labels.append(lab.get("name") if isinstance(lab, dict) else lab)

    repo = content.get("repository") or board.get("issue_repo")
    return {
        "id": f"#{number}",
        "number": number,
        "title": content.get("title") or raw.get("title"),
        "raw_state": raw_state,
        "state": state,
        "type": content.get("type", "issue"),
        "assignee": assignees[0] if assignees else None,
        "assigned_to_me": bool(assignee_me) and assignee_me in assignees,
        "url": content.get("url"),
        "changed_at": raw.get("updatedAt") or content.get("updatedAt"),
        "labels": labels,
        "repo": repo,
    }


def cmd_pull(args) -> int:
    root = Path(args.root).resolve()
    if not gh_available():
        print("warning: `gh` not installed or not authenticated — "
              "skipping pull (run `gh auth login`).", file=sys.stderr)
        return 0

    cfg = {}
    cfg_path = root / "bridge-config.yaml"
    if cfg_path.is_file():
        try:
            cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            cfg = {}
    assignee_me = (((cfg.get("integrations") or {}).get("github") or {})
                   .get("assignee_me"))

    registries = load_registries(root)
    boards = resolve_boards(root, registries)
    if args.project and args.project != "all":
        boards = [b for b in boards if b["slug"] == args.project]
    if not boards:
        print("No boards resolved from ecosystem.yaml github_projects.",
              file=sys.stderr)
        return 0

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    store = root / "work" / "trackers" / "github"
    store.mkdir(parents=True, exist_ok=True)
    index_entries = []
    closed_cache: dict = {}   # repo → {number: lifecycle}, reused across boards

    for board in boards:
        cmd = ["gh", "project", "item-list", str(board["number"]),
               "--owner", board["org"], "--format", "json",
               "--limit", str(args.limit)]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True,
                                 timeout=30, check=True)
            payload = json.loads(res.stdout)
        except (subprocess.SubprocessError, json.JSONDecodeError, OSError) as exc:
            print(f"warning: pull failed for {board['slug']} "
                  f"(#{board['number']}): {exc}", file=sys.stderr)
            continue

        items = []
        for raw in payload.get("items", []):
            norm = normalize_gh_item(raw, board, assignee_me)
            if norm:
                items.append(norm)

        if getattr(args, "issue_state", True):
            enrich_issue_state(items, closed_cache)

        snapshot = {
            "tracker": "github",
            "project": {
                "slug": board["slug"],
                "org": board["org"],
                "number": board["number"],
                "name": board["name"],
            },
            "pulled_at": now,
            "item_count": len(items),
            "items": items,
        }
        out = store / f"{board['slug']}.json"
        out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
        index_entries.append({
            "tracker": "github",
            "slug": board["slug"],
            "number": board["number"],
            "items": len(items),
            "pulled_at": now,
            "path": f"github/{board['slug']}.json",
        })
        print(f"pulled {board['slug']} (#{board['number']}): {len(items)} items")

    index = {
        "_comment": "Auto-written by scripts/tracker-sync.py — do not hand-edit.",
        "last_pull": now,
        "snapshots": index_entries,
    }
    (root / "work" / "trackers" / "_index.yaml").write_text(
        yaml.safe_dump(index, sort_keys=False, allow_unicode=True),
        encoding="utf-8")
    return 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def cmd_selftest(args) -> int:
    """Pure-function checks not reachable via the snapshot-based diff tests
    (state normalization incl. emoji-prefixed options, classify buckets)."""
    checks = [
        (normalize_board_state("✅ Done") == "done", "emoji '✅ Done' → done"),
        (normalize_board_state("🆕 New") == "new", "emoji '🆕 New' → new"),
        (normalize_board_state("🏗 In progress") == "in_progress", "emoji In progress"),
        (normalize_board_state("👀 In review") == "review", "emoji In review"),
        (normalize_board_state("🔖 Ready for Dev") == "ready", "emoji Ready for Dev"),
        (normalize_board_state("❌ Declined") == "removed", "emoji Declined → removed"),
        (normalize_board_state("📋 Backlog") == "new", "emoji Backlog → new"),
        (normalize_board_state("Done", {"Done": "done"}) == "done", "registry exact"),
        (normalize_board_state("") == "new", "empty → new"),
        (classify("doing", "done") == "remote_ahead", "classify remote_ahead"),
        (classify("done", "in_progress") == "local_ahead", "classify local_ahead"),
        (classify("doing", "in_progress") == "in_sync", "classify in_sync"),
        (classify("doing", "in_progress", blocked=True) == "state_mismatch", "classify mismatch"),
    ]
    ok = True
    for passed, name in checks:
        print(f"  {'PASS' if passed else 'FAIL'}  {name}")
        ok = ok and passed
    return 0 if ok else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="tracker-sync engine for The Bridge")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", default=str(repo_root_default()),
                        help="Bridge repo root (default: inferred from script path)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_pull = sub.add_parser("pull", parents=[common],
                            help="pull GitHub Projects into snapshots")
    p_pull.add_argument("--project", default="all",
                        help="board slug to pull, or 'all' (default)")
    p_pull.add_argument("--limit", type=int, default=200,
                        help="max items per board (default 200)")
    p_pull.add_argument("--no-issue-state", dest="issue_state",
                        action="store_false",
                        help="skip per-repo issue open/closed enrichment (faster)")
    p_pull.set_defaults(func=cmd_pull, issue_state=True)

    p_diff = sub.add_parser("diff", parents=[common],
                            help="reconcile snapshots against STATUS.md")
    p_diff.add_argument("--format", choices=["table", "json"], default="table")
    p_diff.add_argument("--exit-code", action="store_true",
                        help="exit 2 if any actionable drift exists")
    p_diff.set_defaults(func=cmd_diff)

    p_plan = sub.add_parser("plan", parents=[common],
                            help="emit gated push ops for local_ahead tasks")
    p_plan.add_argument("--format", choices=["table", "json"], default="table")
    p_plan.set_defaults(func=cmd_plan)

    p_self = sub.add_parser("selftest", help="run pure-function checks")
    p_self.set_defaults(func=cmd_selftest)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
