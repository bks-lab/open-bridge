#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""upstream-resolve.py — decide which upstream-merge conflicts a machine may resolve.

The daily upstream-autoupdate job used to stop at the first predicted conflict and
then stop again every morning after, because nothing ever resolved it: one instance
sat 84 commits behind before anybody looked. Most of those conflicts were not
decisions at all. A fix was promoted, merged upstream under a new hash, and then
upstream built on it (a review edit, a follow-up commit). The local file is an OLDER
upstream version, and upstream's current one is simply newer.

The mirror case froze it just as often: a change is promoted, upstream takes it byte
for byte, and work goes on locally. Now upstream's file is an OLDER local version.
Measured 2026-10-17: 23 conflicting files, 21 of them that case, one an appended
.gitignore block the instance had pulled earlier.

These are the cases this script resolves, decided by CONTENT, never by path or by
commit message:

  take theirs   the local version of the file is byte-identical to a version
                upstream itself had between the merge base and now, and upstream
                did not revert any commit since. Upstream has seen our change and
                moved on from it; nothing local is lost.

  take ours     seen_locally: upstream's version is byte-identical to a version
                this branch had since the merge base, and the branch did not
                revert any commit since. We have seen upstream's file and moved
                on from it; nothing upstream knows is lost.
                contained: since the merge base upstream only ADDED lines, and
                every added block stands in the local file verbatim and in one
                piece. Upstream's change is already there.

  unresolved    everything else, each with the reason:
                · the local version never reached upstream (an unpromoted CORE
                  edit — promote it, or drop it)
                · upstream had it and then REVERTED it. Taking theirs here would
                  silently withdraw a change that may be running locally — on the
                  instance this was written on, a live launchd job.
                · this branch had upstream's version and then REVERTED it locally:
                  upstream still carries what the instance withdrew, a human looks
                · the file was deleted locally, or the conflict is not a plain
                  content one (rename, mode, submodule)

A held file names the local commits behind it, minus every commit whose change to
that file upstream already carries: its patch-id for the path (`git patch-id
--stable`) matches a commit anywhere in upstream's history of the path, whether
that twin is still pending or came down with an earlier merge. A promoted commit
is not local work. A promote squashed together with other changes has no twin of
its own and is still named.
A path declared in bridge-config.yaml `promote.local_adaptations` (a list of
{path, reason}, fnmatch globs allowed, where `*` also matches `/`) is labelled a
declared local adaptation instead of an unpromoted change. It stays held: upstream changed a file this
instance keeps different on purpose, and only a human merges the two.

Every path not provably "take theirs" or "take ours" is unresolved: the script
fails closed.

Usage:
  upstream-resolve.py --theirs upstream/main [--ours HEAD] [--config bridge-config.yaml]
Exit: 0 = plan printed (check "unresolved") · 2 = git could not answer.
"""
from __future__ import annotations

import argparse
import difflib
import fnmatch
import json
import os
import subprocess
import sys

ENV = {**os.environ, "LC_ALL": "C"}


class GitError(RuntimeError):
    pass


def git(*args: str, ok: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess:
    p = subprocess.run(["git", *args], capture_output=True, env=ENV)
    if p.returncode not in ok:
        raise GitError(f"git {' '.join(args)} → {p.returncode}: {p.stderr.decode(errors='replace').strip()}")
    return p


def blob(rev: str, path: str) -> str | None:
    p = git("rev-parse", "-q", "--verify", f"{rev}:{path}", ok=(0, 1, 128))
    return p.stdout.decode().strip() if p.returncode == 0 else None


def conflicts(ours: str, theirs: str) -> tuple[bool, dict[str, set[int]]]:
    """(clean, {path: {stages}}) from merge-tree's exit code and -z stage list."""
    p = git("merge-tree", "--write-tree", "-z", ours, theirs, ok=(0, 1))
    if p.returncode == 0:
        return True, {}
    out: dict[str, set[int]] = {}
    # <tree>NUL then "<mode> <oid> <stage>\t<path>" NUL ... then an empty field.
    for field in p.stdout.decode(errors="surrogateescape").split("\0")[1:]:
        if not field:
            break
        meta, _, path = field.partition("\t")
        parts = meta.split()
        if len(parts) != 3 or not path:
            raise GitError(f"unparseable merge-tree entry: {field!r}")
        out.setdefault(path, set()).add(int(parts[2]))
    if not out:
        raise GitError("merge-tree reported conflicts but listed no paths")
    return False, out


def is_revert(commit: str) -> bool:
    msg = git("log", "-1", "--format=%s%n%b", commit).stdout.decode(errors="replace")
    return msg.startswith('Revert "') or "This reverts commit" in msg


def short(c: str) -> str:
    return c[:7]


def patch_ids(rev_range: str, path: str) -> dict[str, str]:
    """{commit: patch-id of its change to path} for the non-merge commits in rev_range."""
    log = git("log", "--no-merges", "-p", "--format=commit %H", rev_range, "--", path).stdout
    if not log.strip():
        return {}
    p = subprocess.run(["git", "patch-id", "--stable"], input=log, capture_output=True, env=ENV)
    if p.returncode:
        raise GitError(f"git patch-id → {p.returncode}: {p.stderr.decode(errors='replace').strip()}")
    out = {}
    for row in p.stdout.decode().splitlines():
        pid, _, commit = row.partition(" ")
        out[commit.strip()] = pid
    return out


def promoted(base: str, ours: str, theirs: str, path: str) -> set[str]:
    """Local commits in base..ours whose change to path upstream carries, in ANY of its
    history of the path. `git cherry` would see only twins still in ours..theirs; a twin
    that came down with an earlier merge is in neither range it compares."""
    mine = patch_ids(f"{base}..{ours}", path)
    if not mine:
        return set()
    upstream = set(patch_ids(theirs, path).values())
    return {c for c, pid in mine.items() if pid in upstream}


NEVER_REACHED = "local change never reached upstream"
ONLY_MERGES = ("local version differs from upstream, but every local commit to it is already "
               "upstream: the difference comes from a merge resolution")


def local_commits(base: str, ours: str, theirs: str, path: str) -> list[str]:
    # base..ours alone lists every user-only commit ever made to the path, back to
    # the first sync; the ones a human has to look at are those since the base.
    # An old unpromoted edit has none since the base, so fall back to the newest few.
    # A commit upstream already carries patch for patch was promoted: it is not
    # what keeps the file apart, and naming it sends the reader after done work.
    since = git("log", "-1", "--format=%cI", base).stdout.decode().strip()
    done = promoted(base, ours, theirs, path)
    rng = (f"{base}..{ours}", "--", path)

    def pick(*extra: str) -> list[str]:
        out = git("log", "--no-merges", *extra, "--format=%H %s", *rng).stdout
        rows = (r.partition(" ") for r in out.decode(errors="replace").splitlines())
        return [f"{short(h)} {subj}" for h, _, subj in rows if h not in done]

    return pick(f"--since={since}") or pick()[:3]


def load_adaptations(path: str) -> tuple[list[dict], list[str]]:
    """(valid {path, reason} entries, problems) from bridge-config.yaml promote.local_adaptations."""
    if not os.path.isfile(path):
        return [], []
    try:
        import yaml
    except ImportError:
        return [], [f"{path}: pyyaml is not installed, local_adaptations not read"]
    try:
        cfg = yaml.safe_load(open(path, encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as e:
        return [], [f"{path}: {e.__class__.__name__}, local_adaptations not read"]
    raw = ((cfg.get("promote") or {}) if isinstance(cfg, dict) else {}).get("local_adaptations") or []
    if not isinstance(raw, list):
        return [], ["promote.local_adaptations must be a list of {path, reason}"]
    good, bad = [], []
    for i, e in enumerate(raw):
        ok = isinstance(e, dict) and all(isinstance(e.get(k), str) and e[k].strip() for k in ("path", "reason"))
        (good if ok else bad).append(e if ok else f"entry {i}: needs a non-empty path and reason")
    return good, bad


def adaptation_for(path: str, adaptations: list[dict]) -> str | None:
    for a in adaptations:
        if fnmatch.fnmatchcase(path, a["path"]):
            return a["reason"].strip()
    return None


def last_hit(rev_range: str, path: str, want: str) -> tuple[list[str], int | None]:
    """(commits in rev_range touching path, oldest first; index of the last one whose blob is want)."""
    history = git("rev-list", "--reverse", rev_range, "--", path).stdout.decode().split()
    hit = None
    for i, c in enumerate(history):
        if blob(c, path) == want:
            hit = i
    return history, hit


def lines(oid: str | None) -> list[str] | None:
    """A blob as lines, [] for a missing one; None when it is not text."""
    if oid is None:
        return []
    try:
        return git("cat-file", "blob", oid).stdout.decode("utf-8").splitlines(keepends=True)
    except UnicodeDecodeError:
        return None


def contains(hay: list[str], block: list[str]) -> bool:
    n = len(block)
    return any(hay[i:i + n] == block for i in range(len(hay) - n + 1))


def additions_held(base_blob: str | None, ours_blob: str, theirs_blob: str) -> bool:
    """True when upstream only added lines since the base and ours holds each added block in one piece."""
    old, new, mine = lines(base_blob), lines(theirs_blob), lines(ours_blob)
    if old is None or new is None or mine is None:
        return False
    ops = difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes()
    if any(tag not in ("equal", "insert") for tag, *_ in ops):
        return False
    blocks = [new[j1:j2] for tag, _, _, j1, j2 in ops if tag == "insert"]
    return bool(blocks) and all(contains(mine, b) for b in blocks)


def classify_ours(entry: dict, stages: set[int], base: str, ours: str, theirs: str, ours_blob: str) -> dict | None:
    """The mirror rules: a take-ours entry, a held entry when this branch reverted, or None."""
    path = entry["path"]
    theirs_blob = blob(theirs, path)
    if theirs_blob is None or 3 not in stages:
        return None
    history, hit = last_hit(f"{base}..{ours}", path, theirs_blob)
    if hit is not None:
        reverts = [c for c in history[hit + 1:] if is_revert(c)]
        if reverts:
            return {**entry, "reason": f"this branch had upstream's version at {short(history[hit])}, then reverted "
                    "it in " + ", ".join(short(c) for c in reverts),
                    "local_commits": local_commits(base, ours, theirs, path)}
        return {**entry, "rule": "seen_locally", "seen_locally_at": short(history[hit])}
    if additions_held(blob(base, path), ours_blob, theirs_blob):
        return {**entry, "rule": "contained"}
    return None


def classify(path: str, stages: set[int], base: str, ours: str, theirs: str) -> dict:
    entry = {"path": path}
    ours_blob = blob(ours, path)
    if ours_blob is None:
        return {**entry, "reason": "deleted or renamed locally"}
    if 2 not in stages:
        return {**entry, "reason": "not a plain content conflict"}
    history, hit = last_hit(f"{base}..{theirs}", path, ours_blob)
    if hit is None:
        mine = local_commits(base, ours, theirs, path)
        return classify_ours(entry, stages, base, ours, theirs, ours_blob) or {
            **entry, "reason": NEVER_REACHED if mine else ONLY_MERGES, "local_commits": mine}
    later = history[hit + 1:]
    reverts = [c for c in later if is_revert(c)]
    if reverts:
        return {**entry, "reason": f"upstream had it at {short(history[hit])}, then reverted it in "
                + ", ".join(short(c) for c in reverts),
                "local_commits": local_commits(base, ours, theirs, path)}
    return {**entry, "side": "theirs", "seen_upstream_at": short(history[hit]),
            "theirs_deleted": blob(theirs, path) is None}


def plan(ours: str, theirs: str, config: str = "bridge-config.yaml") -> dict:
    ours = git("rev-parse", "--verify", ours).stdout.decode().strip()
    theirs = git("rev-parse", "--verify", theirs).stdout.decode().strip()
    base = git("merge-base", ours, theirs).stdout.decode().strip()
    clean, paths = conflicts(ours, theirs)
    adaptations, invalid = load_adaptations(config)
    take, keep, unresolved = [], [], []
    for path in sorted(paths):
        r = classify(path, paths[path], base, ours, theirs)
        if "reason" in r:
            why = adaptation_for(path, adaptations)
            if why is not None:
                r["local_adaptation"] = why
                if r["reason"] in (NEVER_REACHED, ONLY_MERGES):
                    r["reason"] = f"declared local adaptation ({why}), upstream changed it too: merge by hand"
            unresolved.append(r)
        elif r.pop("side", None) == "theirs":
            take.append(r)
        else:
            keep.append(r)
    out = {"clean": clean, "base": short(base), "take_theirs": take, "take_ours": keep,
           "unresolved": unresolved}
    if invalid:
        out["local_adaptations_invalid"] = invalid
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--theirs", required=True)
    ap.add_argument("--ours", default="HEAD")
    ap.add_argument("--config", default="bridge-config.yaml",
                    help="where promote.local_adaptations is read (default: bridge-config.yaml)")
    a = ap.parse_args()
    try:
        print(json.dumps(plan(a.ours, a.theirs, a.config), indent=2))
    except GitError as e:
        print(f"upstream-resolve: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
