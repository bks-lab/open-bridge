#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
r"""Content-leak guard (scrub-leak + PII gate).

Two layers of defence, standalone (stdlib only, no hardcoded user paths):

1. **Pipe-list scope literals** — a misconfigured scrub regex can mangle
   ``scope: core`` into a pipe-list (``scope: core|user|org``). The pattern
   ``scope:\s*[a-z]+\|[a-z\|]+`` flags any pipe-list scope value — always
   wrong: scope is a single literal (core, user, org, private).

2. **Content classes that must never ship in the OSS cut** — personal
   names, absolute ``/Users/<name>`` paths, ``@bks-lab.com`` addresses.
   Each class carries an allowlist for files where the mention is
   intentional (LICENSE, TRADEMARK.md, AUTHORS, SECURITY.md,
   CODE_OF_CONDUCT.md, ... — governance files name BKS-Lab/Boiman on
   purpose).

Sensitive rosters (customer names, third-party person names) deliberately
do NOT live in this script — shipping them would leak the very roster the
guard protects. They load at runtime from
``scripts/leak-patterns-internal.txt`` (one ``<class-id> <regex>`` per
line), which each org keeps untracked / gitignored. A published repo ships
no roster; forks add their own the same way.

Usage:
    no-scrub-leak.py FILE [FILE ...]   # check given files (pre-commit mode)
    no-scrub-leak.py                   # scan the whole repo (CI mode)

Exit code 0 = clean, 1 = leaks found (report on stderr).
"""
import os
import re
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Governance / legal files where BKS-Lab / Boiman naming is intentional.
GOVERNANCE_FILES = {
    "LICENSE",
    "TRADEMARK.md",
    "AUTHORS",
    "SECURITY.md",
    "CODE_OF_CONDUCT.md",
    "ACKNOWLEDGMENTS.md",
    "CONTRIBUTING.md",
    ".github/CODEOWNERS",  # owner handles (@mboiman) are intentional
}

# Org-specific roster patterns (customer names, third-party persons) load at
# runtime from this file so the shipped script never embeds them. Each org
# keeps it untracked / gitignored; a published repo ships no roster.
INTERNAL_PATTERNS_FILE = "scripts/leak-patterns-internal.txt"

# The roster file itself contains the very patterns the guard scans for, so
# scanning it would be pure noise — allowlist it from the content classes.
INTERNAL_ROSTER = {INTERNAL_PATTERNS_FILE}

# This script embeds the leak patterns itself.
SELF = {"scripts/no-scrub-leak.py"}

# Leak-check tooling data that deliberately encodes the patterns/exceptions
# (bridge-leak-check tolerance config shipped via bridge-sync overrides).
TOOLING_DATA = {
    "skills/bridge-sync/data/overrides/open-bridge/skills/"
    "bridge-leak-check/data/per-repo-tolerance.yaml",
}

# Files whose copyright/attribution footer intentionally names the
# license holder (mirrors LICENSE).
COPYRIGHT_FILES = {"README.md"}

# Placeholder usernames that are fine in /Users/... example paths.
PLACEHOLDER_USERS = {
    "you", "yourname", "your-name", "username", "user", "name",
    "example", "alice", "bob", "jdoe", "johndoe", "me",
}

BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".gz",
    ".tar", ".woff", ".woff2", ".ttf", ".otf", ".mp3", ".mp4", ".m4a",
    ".pyc", ".so", ".dylib",
}


def users_path_filter(match):
    """Allow placeholder usernames in /Users/... example paths."""
    name = match.group(1).lower()
    if set(name) == {"."}:  # /Users/... ellipsis redaction
        return False
    return name not in PLACEHOLDER_USERS


# (class_id, compiled_regex, allowed_relative_paths, match_filter_or_None)
CHECKS = [
    (
        "merge-conflict",
        re.compile(r"^(<{7} |>{7} |\|{7} |<{7}$|>{7}$)"),
        SELF,
        None,
    ),
    (
        "pipe-list-scope",
        re.compile(r"scope:\s*[a-z]+\|[a-z\|]+"),
        SELF,  # the docstring documents the mangled form
        None,
    ),
    (
        "personal-name",
        # Copyright-holder self-check only — third-party person names and
        # customer rosters come from INTERNAL_PATTERNS_FILE (never shipped).
        re.compile(r"\b(mboiman|boiman)\b", re.IGNORECASE),
        GOVERNANCE_FILES | INTERNAL_ROSTER | SELF | COPYRIGHT_FILES,
        None,
    ),
    (
        "abs-user-path",
        re.compile(r"/Users/([A-Za-z0-9._-]+)"),
        INTERNAL_ROSTER | SELF,
        users_path_filter,
    ),
    (
        "org-email",
        re.compile(r"[A-Za-z0-9._%+-]+@bks-lab\.com", re.IGNORECASE),
        GOVERNANCE_FILES | INTERNAL_ROSTER | SELF | TOOLING_DATA,
        None,
    ),
]

# Allowlists for classes loaded from INTERNAL_PATTERNS_FILE: reuse the
# builtin class's allowlist when the class-id matches, else a safe default.
_BUILTIN_ALLOWLISTS = {class_id: allowed for class_id, _, allowed, _ in CHECKS}
_DEFAULT_ALLOWLIST = INTERNAL_ROSTER | SELF


def load_internal_patterns():
    """Append checks from the (never-shipped) internal roster file."""
    path = os.path.join(REPO_ROOT, INTERNAL_PATTERNS_FILE)
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            class_id, _, pattern = line.partition(" ")
            if not pattern:
                continue
            CHECKS.append((
                class_id,
                re.compile(pattern, re.IGNORECASE),
                _BUILTIN_ALLOWLISTS.get(class_id, _DEFAULT_ALLOWLIST),
                None,
            ))


load_internal_patterns()


def repo_files():
    """All tracked files (git), falling back to a filesystem walk."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=REPO_ROOT, capture_output=True, check=True,
        ).stdout
        return [p.decode() for p in out.split(b"\0") if p]
    except (OSError, subprocess.CalledProcessError):
        files = []
        for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
            dirnames[:] = [d for d in dirnames if d != ".git"]
            for f in filenames:
                files.append(
                    os.path.relpath(os.path.join(dirpath, f), REPO_ROOT)
                )
        return files


def scan(rel_path):
    """Yield (class_id, lineno, line) leak hits for one file."""
    if os.path.splitext(rel_path)[1].lower() in BINARY_EXTENSIONS:
        return
    abs_path = os.path.join(REPO_ROOT, rel_path)
    try:
        with open(abs_path, errors="ignore") as fh:
            lines = fh.readlines()
    except OSError:
        # Deliberately lenient HERE, and guarded in main(). The repo-wide sweep
        # derives its list from `git ls-files`, where a file deleted in the
        # worktree but not yet staged is an ordinary transient state. Paths
        # named on the command line are asserted by the caller and get the
        # opposite treatment: see _unreadable() below.
        return
    for class_id, pattern, allowed, match_filter in CHECKS:
        if rel_path in allowed:
            continue
        for i, line in enumerate(lines, 1):
            for match in pattern.finditer(line):
                if match_filter is None or match_filter(match):
                    yield (class_id, i, line.rstrip())
                    break  # one report per line per class


# Exit codes are a contract: scripts/overlay.py already branches on 1 versus
# "anything else", treating the latter as a blocked write. An unreadable path is
# a gate failure, not a leak, so it needs its own code rather than borrowing 1.
EXIT_CLEAN = 0
EXIT_LEAK = 1
EXIT_UNREADABLE = 2


def _unreadable(rel_path):
    """Why this path cannot be scanned, or None when it can.

    Only ever applied to paths the CALLER named. A gate that reports clean about
    a file it never opened is worse than no gate, because the caller stops
    looking. On 2026-09-11 four paths reached this scanner as one nonsense
    string (an unquoted variable under zsh, which does not word-split) and the
    run reported `clean (1 file(s) scanned)` having read nothing.
    """
    abs_path = os.path.join(REPO_ROOT, rel_path)
    if os.path.isdir(abs_path):
        return "is a directory, not a file"
    if not os.path.exists(abs_path):
        return "does not exist"
    try:
        with open(abs_path, errors="ignore"):
            pass
    except OSError as exc:
        return exc.strerror or "cannot be opened"
    return None


def main(argv):
    if argv:
        # Pre-commit mode: paths come in relative to the repo root (or cwd).
        targets = [
            os.path.relpath(os.path.abspath(p), REPO_ROOT) for p in argv
        ]
        unreadable = [(p, why) for p in targets if (why := _unreadable(p))]
        if unreadable:
            sys.stderr.write(
                "no-scrub-leak: refusing to report on paths it could not read.\n"
                "Nothing was scanned for these, so nothing can be said about them:\n"
            )
            for rel_path, why in unreadable:
                sys.stderr.write(f"  {rel_path}: {why}\n")
            sys.stderr.write(
                "\nIf this came from a shell variable, quote it: zsh does not "
                "word-split unquoted expansions, so several paths arrive as one.\n"
            )
            return EXIT_UNREADABLE
    else:
        targets = repo_files()

    hits = []
    counts = {}
    scanned = 0
    skipped_binary = 0
    for rel_path in targets:
        if os.path.splitext(rel_path)[1].lower() in BINARY_EXTENSIONS:
            skipped_binary += 1
            continue
        scanned += 1
        for class_id, lineno, line in scan(rel_path):
            hits.append(f"[{class_id}] {rel_path}:{lineno}: {line.strip()}")
            counts[class_id] = counts.get(class_id, 0) + 1

    if hits:
        sys.stderr.write("Content leak detected:\n  " + "\n  ".join(hits) + "\n")
        summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        sys.stderr.write(f"\n{len(hits)} hit(s) total ({summary})\n")
        sys.stderr.write(
            "Fix: scrub the content, or — if the mention is intentional "
            "(governance file) — extend the per-class allowlist in "
            "scripts/no-scrub-leak.py\n"
        )
        return EXIT_LEAK
    # Report what was actually READ. Counting handed-over paths instead is how a
    # binary, or a path that did not resolve, used to pass as "scanned".
    note = f", {skipped_binary} binary skipped" if skipped_binary else ""
    print(f"no-scrub-leak: clean ({scanned} file(s) scanned{note})")
    return EXIT_CLEAN


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
