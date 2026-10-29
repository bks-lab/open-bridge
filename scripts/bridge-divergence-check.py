#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
bridge-divergence-check.py — CORE/USER divergence + upstream conflict sentinel.

The Bridge keeps merges with upstream conflict-free ONLY as long as USER work
does not diverge a tracked CORE file. This script is the early-warning: it finds
every CORE file you have changed locally (committed on your user branch OR
uncommitted in the working tree) and flags which of those the upstream has ALSO
changed — i.e. the files that will conflict on the next `git merge upstream/main`.

It classifies a path as USER (safe to diverge) vs CORE (divergence = future
conflict) purely structurally, matching docs/structure.md:
  USER: work/, bridge-config.yaml, ecosystem*.yaml, overlays.lock.yaml,
        identity/{personas,accounts,mandants,contracts}/<id>, identity/agent/{SOUL,IDENTITY}.md,
        infra/{remotes,channels,backups}/<id>, workflow/{calendars,contexts,projects}/<id>,
        rules/user/**, protocols/standing-orders/user/**, themes/<non-builtin>
  CORE: everything else (skills/, rules/*.md, docs/, scripts/, templates/schemas,
        CLAUDE.md/AGENTS.md/README.md, .claude/agents/, protocols/standing-orders/*.md)

Exit code: 0 = no CORE conflict risk, 2 = conflict-risk file(s) present.

Usage:
  bridge-divergence-check.py [--upstream upstream/main] [--json]
"""
import argparse, json, os, re, subprocess, sys

BUILTIN_THEMES = {"professional", "professional-de", "professional-fr", "professional-zh-cn", "_template", "_schema"}

# A path is USER (safe to diverge from CORE) if it matches one of these.
USER_PATTERNS = [
    r"^work/",
    r"^imports/",
    r"^bridge-config\.ya?ml$",
    r"^ecosystem(\.[a-z0-9-]+)?\.ya?ml$",
    r"^overlays\.lock\.ya?ml$",
    r"^\.bridge/",
    r"^identity/(personas|accounts|mandants|contracts)/(?!_)[^/]+\.(ya?ml|md)$",
    r"^identity/agent/(SOUL|IDENTITY)\.md$",
    r"^infra/(remotes|channels|backups)/(?!_)[^/]+(\.ya?ml|\.md|/.*)$",
    r"^infra/(scheduled|instances)/(?!_)",
    r"^workflow/(calendars|contexts|projects)/(?!_)[^/]+\.(ya?ml|md)$",
    r"^rules/(user|org)/",
    r"^protocols/standing-orders/(user|org)/",
]


def is_user(path):
    if any(re.search(p, path) for p in USER_PATTERNS):
        return True
    # custom (non-builtin) theme file = USER
    m = re.match(r"^themes/([a-z0-9-]+)\.ya?ml$", path)
    if m and m.group(1) not in BUILTIN_THEMES:
        return True
    return False


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True).stdout.strip()


def name_set(diff_range):
    out = git("diff", "--name-only", diff_range)
    return set(l for l in out.splitlines() if l)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--upstream", default="upstream/main")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    # verify the upstream ref exists
    if subprocess.run(["git", "rev-parse", "--verify", a.upstream],
                      capture_output=True).returncode != 0:
        sys.exit(f"error: ref '{a.upstream}' not found (git fetch upstream first?)")

    base = git("merge-base", "HEAD", a.upstream)
    behind = int(git("rev-list", "--count", f"HEAD..{a.upstream}") or 0)
    ahead = int(git("rev-list", "--count", f"{a.upstream}..HEAD") or 0)

    # local CORE edits: committed (base..HEAD) + uncommitted working tree
    local_all = name_set(f"{base}..HEAD") | set(
        l for l in git("diff", "--name-only", "HEAD").splitlines() if l)
    upstream_all = name_set(f"{base}..{a.upstream}")

    local_core = sorted(f for f in local_all if not is_user(f))
    conflict_risk = sorted(f for f in local_core if f in upstream_all)

    result = {
        "behind": behind, "ahead": ahead,
        "local_core_edits": local_core,
        "conflict_risk": conflict_risk,
        "verdict": "at-risk" if conflict_risk else ("diverged" if local_core else "clean"),
    }

    if a.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"upstream drift: {behind} behind, {ahead} ahead ({a.upstream})")
        print(f"local CORE edits: {len(local_core)}  |  conflict-risk on next merge: {len(conflict_risk)}")
        if conflict_risk:
            print("\n⚠ CONFLICT-RISK (CORE file changed both locally and upstream):")
            for f in conflict_risk:
                print(f"  ✗ {f}")
        if local_core:
            noconf = [f for f in local_core if f not in conflict_risk]
            if noconf:
                print("\n⚠ diverged CORE files (no upstream change yet — promote or revert):")
                for f in noconf:
                    print(f"  · {f}")
        if result["verdict"] == "clean":
            print("\n✓ clean — no CORE divergence; merge is safe.")

    sys.exit(2 if conflict_risk else 0)


if __name__ == "__main__":
    main()
