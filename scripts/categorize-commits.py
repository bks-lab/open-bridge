#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Categorize commits by scope (core / org / user) for /promote routing.

Mirrors the path → scope table in rules/operations.md § CORE/USER Separation.
Run from repo root.

Usage:
    scripts/categorize-commits.py                    # since last open-bridge snapshot
    scripts/categorize-commits.py --since 2026-05-03
    scripts/categorize-commits.py --range open-bridge/main..HEAD
    scripts/categorize-commits.py --commit <sha>     # detail for one commit
    scripts/categorize-commits.py --json             # machine-readable output

Output shows per-commit category + file-level breakdown for MIXED commits,
so /promote can decide which files to cherry-pick by path-selection rather
than full-commit cherry-pick (which fails on disjoint histories anyway).
"""
import argparse
import json
import os
import re
import subprocess
import sys

# ---------------------------------------------------------------------------
# Path → scope table — MIRROR of rules/operations.md § CORE/USER Separation.
# Keep in sync with operations.md (manual — no automated drift check yet).
#
# Scope is now STRUCTURAL: tier is decided by where a file lives, not a tag.
# Whole folders (work/, rules/user/) are user; the `_`-prefix split inside the
# cluster wrappers (identity/ infra/ workflow/) marks `_schema`/`_template`
# core vs every other instance user; skill tier lives in `metadata.scope`,
# read from each skill's SKILL.md below.
# ---------------------------------------------------------------------------

USER_PATTERNS = [
    r"^work/",                                        # incl. the job-application pipeline stream
    r"^rules/user/",                                  # user-tier rules (applications, …) — folder = tier
    r"^docs/applications\.md$",                       # personal applications feature — user-tier
    r"^bridge-config\.yaml$",
    r"^bridge-deck\.config\.yaml$",
    r"^overlays\.lock\.yaml$",                         # generated org-overlay lockfile — local-only, never promoted
    r"^\.bridge/",                                     # sparse org-overlay cache (.bridge/overlays/<name>/) — local-only
    # NB: the overlay ENGINE stays core — scripts/overlay.py + docs/schemas/*
    # match no USER/ORG pattern and fall through to CORE (ships to open-bridge).
    r"^identity/personas/(?!_(schema|template))",     # personas/<id>.yaml
    r"^identity/mandants/(?!_(schema|template))",     # mandants/<id>.yaml
    r"^identity/accounts/(?!_template)",              # accounts/<id>.yaml — instance-specific
    r"^infra/remotes/(?!_(schema|template))",
    r"^infra/channels/(?!_(schema|template))",
    r"^infra/instances/(?!_(schema|template))",       # instances/<id>.yaml — names real repos/customers (instances → user; _schema/_template stay core)
    r"^infra/backups/(topology|_state)\.yaml$",
    r"^infra/backups/launchd/",                       # instance-specific launchd plists
    r"^infra/backups/volumes/",
    r"^workflow/calendars/(?!_(schema|template))",
    r"^workflow/contexts/(?!_(schema|template)|customer-a\.yaml|doc-system\.)",  # contexts/<id>.yaml — instance-specific (org-overlay contexts excluded — they live in ORG_PATTERNS)
    r"^workflow/projects/(?!_(schema|template))",     # projects/<slug>.yaml (instances → user; _schema/_template stay core)
    r"^identity/voiceprints/",                        # biometric speaker embeddings (GDPR Art. 9)
    r"^identity/contracts/(?!_(schema|template))",    # contracts/<id>.yaml — customer-no/persona PII
    r"^protocols/standing-orders/user/",              # user-authored orders (mirrors rules/user/); shipped defaults stay CORE
]

ORG_PATTERNS = [
    r"^ecosystem\.yaml$",                             # Org overlay carries ecosystem
    r"^rules/org/",                                   # org-tier rules (wiki-navigation, wiki-principles) — folder = tier
    # NOTE: skills are NOT path-matched here — they route by `metadata.scope`
    # read from SKILL.md below. A hardcoded skill path would SHADOW the
    # frontmatter and mis-route a re-scoped skill. Org skills are caught by the
    # frontmatter read.
    r"^\.claude/agents/customer-a-",
    r"^workflow/contexts/(customer-a|doc-system)\.yaml$",
    r"^identity/mandants/org\.yaml$",
    r"^docs/(public-release-cleanup|three-tier-architecture|wiki-architecture)\.md$",
]

# Everything else not matched above defaults to CORE.

# ---------------------------------------------------------------------------

def classify_file(path: str) -> str:
    for p in USER_PATTERNS:
        if re.search(p, path):
            return "user"
    for p in ORG_PATTERNS:
        if re.search(p, path):
            return "org"
    # Skill/agent files — frontmatter `scope:` overrides path inference.
    # For ANY file under skills/<name>/, read the scope from that skill's SKILL.md
    # (fixes the leak where skills/<name>/references/foo.md was treated as core
    # even though skills/<name>/SKILL.md declares a non-core scope).
    m = re.match(r"^skills/([^/]+)/", path)
    if m:
        scope = read_frontmatter_scope(f"skills/{m.group(1)}/SKILL.md")
        if scope:
            return scope
    m = re.match(r"^\.claude/agents/([^/]+)\.md$", path)
    if m:
        scope = read_frontmatter_scope(path)
        if scope:
            return scope
    # Agent identity (IDENTITY.md / SOUL.md) carries `scope: user` in
    # frontmatter — honor it. The tight regex deliberately excludes
    # `_template.SOUL.md` / `_template.IDENTITY.md`, which fall through to CORE.
    if re.match(r"^identity/agent/(IDENTITY|SOUL)\.md$", path):
        scope = read_frontmatter_scope(path)
        if scope:
            return scope
    return "core"


def read_frontmatter_scope(path: str) -> str | None:
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        head = f.read(2000)
    m = re.search(r"^---\s*\n(.*?)\n---", head, re.DOTALL | re.MULTILINE)
    if not m:
        return None
    fm = m.group(1)
    # 1) top-level `scope:` — sub-agents (.claude/agents/*.md) and rules keep it there.
    sm = re.search(r"^scope:\s*([a-z]+)", fm, re.MULTILINE)
    if sm:
        return sm.group(1)
    # 2) `metadata.scope` — skills/*/SKILL.md nest scope under metadata: for
    # skill-creator conformance (its validator forbids non-standard top-level keys).
    # Scope the search to the metadata: block so a `scope:` mention inside a
    # description block-scalar can't false-match.
    mb = re.search(r"^metadata:[ \t]*\n((?:[ \t]+.*\n?)*)", fm, re.MULTILINE)
    if mb:
        ms = re.search(r"^[ \t]+scope:\s*([a-z]+)", mb.group(1), re.MULTILINE)
        if ms:
            return ms.group(1)
    return None


def commits_in_range(rev_range: str, since: str | None) -> list[tuple[str, str]]:
    cmd = ["git", "log", "--no-merges", "--pretty=format:%H|%s"]
    if since:
        cmd.append(f"--since={since}")
    if rev_range:
        cmd.append(rev_range)
    out = subprocess.check_output(cmd, text=True).strip()
    pairs: list[tuple[str, str]] = []
    for line in out.splitlines():
        if not line:
            continue
        sha, _, subj = line.partition("|")
        pairs.append((sha, subj))
    return pairs


def files_in_commit(sha: str) -> list[str]:
    out = subprocess.check_output(
        ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", sha],
        text=True,
    )
    return [line for line in out.splitlines() if line]


def categorize_commit(sha: str) -> dict:
    files = files_in_commit(sha)
    by_file = {f: classify_file(f) for f in files}
    scopes = set(by_file.values())
    if scopes == {"core"}:
        category = "CORE"
    elif scopes == {"org"} or scopes == {"core", "org"}:
        category = "Org"
    elif scopes == {"user"}:
        category = "USER"
    else:
        category = "MIXED"
    return {
        "sha": sha,
        "category": category,
        "files": by_file,
        "scopes_present": sorted(scopes),
    }


def render_table(results: list[dict], commits: list[tuple[str, str]]) -> None:
    subj_by_sha = {sha: subj for sha, subj in commits}
    for r in results:
        subj = subj_by_sha.get(r["sha"], "")[:70]
        print(f"{r['category']:5s}  {r['sha'][:7]}  {subj}")
        if r["category"] == "MIXED":
            for f, s in r["files"].items():
                print(f"        └─ {s:4s}  {f}")
    print()
    counts = {c: 0 for c in ["CORE", "Org", "USER", "MIXED"]}
    for r in results:
        counts[r["category"]] += 1
    print(f"Total: {len(results)} commits  "
          f"[CORE={counts['CORE']}  Org={counts['Org']}  "
          f"USER={counts['USER']}  MIXED={counts['MIXED']}]")
    if counts["MIXED"]:
        print("\nMIXED commits need path-selective cherry-pick — "
              "see rules/operations.md § CORE/USER Separation.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", help="git --since date (e.g. 2026-05-03)")
    ap.add_argument("--range", default="HEAD",
                    help="git revision range (default: HEAD)")
    ap.add_argument("--commit", help="categorize a single commit and exit")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    if args.commit:
        result = categorize_commit(args.commit)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            render_table([result], [(args.commit, "")])
        return 0

    commits = commits_in_range(args.range, args.since)
    if not commits:
        print("No commits in range.", file=sys.stderr)
        return 0
    results = [categorize_commit(sha) for sha, _ in commits]
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        render_table(results, commits)
    return 0


if __name__ == "__main__":
    sys.exit(main())
