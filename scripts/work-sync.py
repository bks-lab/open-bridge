#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Commit what a person wrote on an always-on clone, and push it.

    python3 scripts/work-sync.py [--root R] --actor NAME [--path work/tasks/x/STATUS.md ...]

A cockpit served on another machine (bridge-cockpit.py serve --served) writes into a clone a puller may reset to
its upstream, so a person's entry has to reach the upstream as soon as it lands. This script commits the named
paths and nothing else, rebases onto the upstream and pushes. Without --path it only pushes what waits.

Only work/tasks/, work/done/, work/inbox/ and work/log.md are accepted: a task's close moves its folder from one to
the other, and the log row names who did it. The generated work/board.md is put back, not committed: the next
render writes it anyway, and a local copy would collide with the next pull.

Exit codes as the puller's: 0 done, 75 the commit stays local and the next run pushes it (no network, a lost race),
65 needs a person (a real conflict, unpushed commits outside the list), 2 a path outside the list, nothing written,
1 anything else.
"""
from __future__ import annotations

import argparse
import datetime as dt
import posixpath
import subprocess
import sys
from pathlib import Path

PREFIXES = ("work/tasks/", "work/done/", "work/inbox/")
FILES = ("work/log.md",)
GENERATED = ("work/board.md", "work/inbox.md")
PUSH_TRIES = 3


def allowed(path: str) -> bool:
    if not path or path.startswith("/") or posixpath.normpath(path) != path:
        return False
    return path in FILES or any(path.startswith(p) and len(path) > len(p) for p in PREFIXES)


def sync(root: Path, actor: str, paths: list[str]) -> int:
    def git(*args: str, timeout: float = 120) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=timeout)

    if paths:
        known = [p for p in paths if (root / p).exists()
                 or git("ls-files", "--error-unmatch", "--", p).returncode == 0]
        if known:
            done = git("add", "-A", "--", *known)
            if done.returncode != 0:
                print(f"work sync: {done.stderr.strip()[:200]}", file=sys.stderr)
                return 1
            if git("diff", "--cached", "--quiet", "--", *known).returncode != 0:
                done = git("commit", "-q", "-m", f"work: {actor} {dt.datetime.now():%Y-%m-%d %H:%M}", "--", *known)
                if done.returncode != 0:
                    print(f"work sync: {done.stderr.strip()[:200]}", file=sys.stderr)
                    return 1
    for path in GENERATED:
        if git("ls-files", "--error-unmatch", "--", path).returncode == 0:
            git("checkout", "--", path)
    for _ in range(PUSH_TRIES):
        if git("fetch", "--quiet").returncode != 0:
            print("work sync: fetch failed, the commit stays local", file=sys.stderr)
            return 75
        if git("rev-parse", "--abbrev-ref", "@{u}").returncode != 0:
            print("work sync: the branch has no upstream", file=sys.stderr)
            return 1
        outside = [p for p in git("diff", "--name-only", "@{u}...HEAD").stdout.split() if not allowed(p)]
        if outside:
            print(f"work sync: unpushed commits outside the list ({', '.join(outside[:3])}), not pushing",
                  file=sys.stderr)
            return 65
        if git("rev-list", "--count", "@{u}..HEAD").stdout.strip() == "0":
            return 0
        done = git("rebase", "--autostash", "@{u}")
        if done.returncode != 0:
            git("rebase", "--abort")
            print(f"work sync: rebase failed and was aborted: {done.stderr.strip()[:200]}", file=sys.stderr)
            return 65
        if git("push", "--quiet").returncode == 0:
            return 0
    print("work sync: push failed, the commit stays local", file=sys.stderr)
    return 75


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="work-sync.py", description="Commit and push a person's entries.")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--actor", required=True)
    parser.add_argument("--path", action="append", default=[])
    args = parser.parse_args(argv)
    bad = [p for p in args.path if not allowed(p)]
    if bad:
        print(f"work sync: outside the list: {bad[0][:120]}", file=sys.stderr)
        return 2
    return sync(Path(args.root), args.actor, args.path)


if __name__ == "__main__":
    sys.exit(main())
