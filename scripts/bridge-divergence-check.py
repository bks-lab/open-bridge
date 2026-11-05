#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
bridge-divergence-check.py — CORE/USER divergence + upstream conflict sentinel.

The Bridge keeps merges with upstream conflict-free ONLY as long as USER work
does not diverge a tracked CORE file. This script is the early-warning: it finds
every CORE file you have changed locally (committed on your user branch OR
uncommitted in the working tree) and flags which of those the upstream has ALSO
changed — i.e. the files that will conflict on the next `git merge upstream/main`.

It classifies a path with the canonical scope router, `classify_file()` in
scripts/categorize-commits.py (the same one /bridge-promote uses), so skill
`metadata.scope`, cluster-wrapper frontmatter, org and personal paths all count
as non-CORE. Only a path the router calls `core` can diverge CORE.
  A root CLAUDE.md stays on the CORE side here on purpose, see ENTRY_FILE.
  A CORE path declared in bridge-config.yaml `promote.local_adaptations` is an
  intentional local edit: reported separately, never a warning, but still a
  conflict risk when upstream changed it too.

Exit code: 0 = no CORE conflict risk, 2 = conflict-risk file(s) present.

Usage:
  bridge-divergence-check.py [--upstream upstream/main] [--json]
"""
import argparse, importlib.util, json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_router = _load("categorize_commits_for_divergence", "categorize-commits.py")
_resolve = _load("upstream_resolve_for_divergence", "upstream-resolve.py")


# A root CLAUDE.md classifies `user` in the promote router (it must never reach
# upstream), but this sentinel keeps it a CORE path ON PURPOSE: upstream deleted
# its CLAUDE.md, so a fork that edited one meets a modify/delete conflict, and
# flagging it is what makes the migration hint below fire.
ENTRY_FILE = "CLAUDE.md"
ENTRY_HINT = ("upstream removed CLAUDE.md: run python3 scripts/migrate-entry-file.py "
              "(docs/updating.md)")


def is_core(path):
    """CORE per the canonical scope router; the entry file is CORE on purpose."""
    return path == ENTRY_FILE or _router.classify_file(path) == "core"


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

    core_all = sorted(f for f in local_all if is_core(f))
    adaptations, _problems = _resolve.load_adaptations("bridge-config.yaml")
    declared = {f: r for f in core_all
                if (r := _resolve.adaptation_for(f, adaptations))}
    declared_list = sorted(declared)
    local_core = [f for f in core_all if f not in declared]
    conflict_risk = sorted(f for f in core_all if f in upstream_all)

    # The fork still has a root CLAUDE.md that upstream no longer ships.
    has_local_entry = os.path.isfile(ENTRY_FILE) or subprocess.run(
        ["git", "cat-file", "-e", f"HEAD:{ENTRY_FILE}"], capture_output=True).returncode == 0
    upstream_has_entry = subprocess.run(
        ["git", "cat-file", "-e", f"{a.upstream}:{ENTRY_FILE}"], capture_output=True).returncode == 0
    hints = []
    if ENTRY_FILE in conflict_risk or (has_local_entry and not upstream_has_entry):
        hints.append(ENTRY_HINT)

    result = {
        "behind": behind, "ahead": ahead,
        "local_core_edits": local_core,
        "declared_adaptations": declared_list,
        "conflict_risk": conflict_risk,
        "verdict": "at-risk" if conflict_risk else ("diverged" if local_core else "clean"),
        "hints": hints,
    }

    if a.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"upstream drift: {behind} behind, {ahead} ahead ({a.upstream})")
        print(f"local CORE edits: {len(local_core)}  |  declared local adaptations: "
              f"{len(declared_list)}  |  conflict-risk on next merge: {len(conflict_risk)}")
        if conflict_risk:
            print("\n⚠ CONFLICT-RISK (CORE file changed both locally and upstream):")
            for f in conflict_risk:
                tag = "  (declared in promote.local_adaptations)" if f in declared else ""
                print(f"  ✗ {f}{tag}")
        noconf = [f for f in local_core if f not in conflict_risk]
        if noconf:
            print("\n⚠ diverged CORE files (no upstream change yet — promote or revert):")
            for f in noconf:
                print(f"  · {f}")
        quiet = [f for f in declared_list if f not in conflict_risk]
        if quiet:
            print("\n✓ declared local adaptations (promote.local_adaptations, not a warning):")
            for f in quiet:
                print(f"  · {f} — {declared[f][:60]}")
        for h in hints:
            print(f"\n→ {h}")
        if result["verdict"] == "clean":
            print("\n✓ clean — no CORE divergence; merge is safe.")

    sys.exit(2 if conflict_risk else 0)


if __name__ == "__main__":
    main()
