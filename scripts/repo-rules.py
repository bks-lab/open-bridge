#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Find a repository's working rules, so they are read before the first write.

    python3 scripts/repo-rules.py <path | owner/repo> [...] [--ref REF]
    python3 scripts/repo-rules.py example-org/example-repo --print
    python3 scripts/repo-rules.py ../example-repo --json

A Bridge that writes to a repository (an issue, a PR, a commit, a label, a
board move) follows that repository's rules, not its own habits. Reading
AGENTS.md alone misses them more often than not: an AGENTS.md tends to name
`docs/workflow.md` in a folder table, and the labels, the assignment model and
the task-id scheme live there. This lists every file that looks like a working
rule, one hop of the files AGENTS.md or CLAUDE.md link or name, and the label
set of a GitHub repository, so the agent reads them instead of guessing.

Targets: a local directory, or `owner/repo` read through `gh api` (contents
and labels; `--ref` picks a branch, tag or SHA for a remote target only).

Output: a summary by default, `--print` adds every file's text, `--json` is
the machine form (with the text when `--print` is also given).

Exit: 0 rule files found, 3 none found (the summary says "no working rules
found, Bridge defaults apply"), 4 a target could not be read. An access error
is never reported as "no rules". Several targets: the worst one decides.

The rule this serves: `rules/operations.md` § Context Switching.
Contract: `scripts/tests/test_repo_rules.py`.
"""

from __future__ import annotations

import argparse
import base64
import fnmatch
import json
import posixpath
import re
import subprocess
import sys
from pathlib import Path

EXIT_FOUND = 0
EXIT_NONE = 3
EXIT_ACCESS = 4

# Checked in this order, case-insensitively, against repo-relative paths.
# A pattern's directory is listed once; `*` never crosses a `/`.
CANDIDATES: tuple[str, ...] = (
    "AGENTS.md",
    "CLAUDE.md",
    "CONTRIBUTING.md",
    ".github/CONTRIBUTING.md",
    "docs/CONTRIBUTING.md",
    "docs/workflow*.md",
    "WORKFLOW.md",
    ".github/ISSUE_TEMPLATE/*",
    ".github/pull_request_template.md",
    "pull_request_template.md",
    "docs/pull_request_template.md",
)

# Entry files whose links and named paths are followed, one hop, no recursion.
ENTRY_FILES = ("AGENTS.md", "CLAUDE.md")
# A linked file counts as a working rule when its path says so.
RULE_WORDS = re.compile(r"workflow|contributing|process|convention", re.IGNORECASE)
# Text documents only, and never a CI definition (`.github/workflows/` says
# "workflow" and describes a pipeline, not how people work in the repo).
DOC_PATH = re.compile(
    r"(?<![\w/.-])(/?(?:[\w.-]+/)*[\w.-]+\.(?:md|markdown|mdx|rst|txt))(?![\w/-])",
    re.IGNORECASE)
URL = re.compile(r"\b[a-z][a-z0-9+.-]*://\S+", re.IGNORECASE)


class AccessError(Exception):
    """The target could not be read. Never to be reported as "no rules"."""


# ---------------------------------------------------------------- pure core


def candidate_dirs() -> list[str]:
    """Every directory a candidate pattern lives in, in first-seen order."""
    seen: list[str] = []
    for pattern in CANDIDATES:
        d = posixpath.dirname(pattern)
        if d not in seen:
            seen.append(d)
    return seen


def discover(listing: dict[str, int]) -> list[str]:
    """The candidate files present in `listing`, in CANDIDATES order."""
    found: list[str] = []
    for pattern in CANDIDATES:
        pat_dir, pat_name = posixpath.split(pattern.lower())
        hits = sorted(
            p for p in listing
            if posixpath.dirname(p).lower() == pat_dir
            and fnmatch.fnmatchcase(posixpath.basename(p).lower(), pat_name)
            and p not in found)
        found.extend(hits)
    return found


def extract_links(text: str, entry: str) -> list[str]:
    """Repo-relative paths that `entry` links or names and that look like rules.

    Markdown links, backticked paths and bare mentions in prose or a table
    cell all count: the folder table is where the workflow file hides. URLs,
    anchors, CI workflow files and paths that leave the repository are dropped.
    """
    base = posixpath.dirname(entry)
    out: list[str] = []
    for raw in DOC_PATH.findall(URL.sub(" ", text)):
        if raw.startswith("/"):
            path = posixpath.normpath(raw.lstrip("/"))
        else:
            path = posixpath.normpath(posixpath.join(base, raw))
        if path.startswith("../") or path == "..":
            continue
        if path.lower().startswith(".github/workflows/"):
            continue
        if not RULE_WORDS.search(path):
            continue
        if path not in out:
            out.append(path)
    return out


def collect(source, with_content: bool = False) -> dict:
    """Discover the working rules behind `source`. Raises AccessError."""
    listing: dict[str, int] = {}
    for d in candidate_dirs():
        listing.update(source.list_dir(d))

    files = [{"path": p, "size": listing[p], "via": None} for p in discover(listing)]
    known = {f["path"] for f in files}
    texts: dict[str, str] = {}
    dangling: list[str] = []

    for entry in [f["path"] for f in files]:
        if entry.lower() not in {e.lower() for e in ENTRY_FILES}:
            continue
        texts[entry] = source.read(entry)
        for target in extract_links(texts[entry], entry):
            if target in known:
                continue
            # A bare name in a folder table (`workflow.md` in the `docs/` row)
            # means the found file of that name, not a file at the root.
            if "/" not in target and any(
                    posixpath.basename(k).lower() == target.lower() for k in known):
                continue
            size = listing.get(target)
            if size is None:
                size = source.stat(target)
            if size is None:
                if target not in dangling:
                    dangling.append(target)
                continue
            files.append({"path": target, "size": size, "via": entry})
            known.add(target)

    if with_content:
        for f in files:
            f["content"] = texts.get(f["path"]) or source.read(f["path"])

    return {
        "status": "found" if files else "none",
        "files": files,
        "dangling": dangling,
        "labels": source.labels(),
    }


def aggregate_exit(statuses: list[str]) -> int:
    if "error" in statuses:
        return EXIT_ACCESS
    if "none" in statuses:
        return EXIT_NONE
    return EXIT_FOUND


# ---------------------------------------------------------------- sources


class LocalSource:
    """A checkout on disk. Labels are not read: they live on the host."""

    def __init__(self, root: Path):
        self.root = root

    def list_dir(self, d: str) -> dict[str, int]:
        here = self.root / d if d else self.root
        if not here.is_dir():
            return {}
        try:
            entries = list(here.iterdir())
        except OSError as exc:
            raise AccessError(f"{here}: {exc}") from exc
        return {posixpath.join(d, e.name) if d else e.name: e.stat().st_size
                for e in entries if e.is_file()}

    def stat(self, path: str) -> int | None:
        p = self.root / path
        return p.stat().st_size if p.is_file() else None

    def read(self, path: str) -> str:
        try:
            return (self.root / path).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise AccessError(f"{path}: {exc}") from exc

    def labels(self):
        return None


def run_gh(args: list[str]) -> tuple[int, str, str]:
    """The one place this script shells out. Tests replace it."""
    try:
        proc = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, "", str(exc)
    return proc.returncode, proc.stdout, proc.stderr


def _not_found(stderr: str) -> bool:
    return "HTTP 404" in stderr or "Not Found" in stderr


class RemoteSource:
    """A GitHub repository read through `gh api`, read-only."""

    def __init__(self, repo: str, ref: str | None = None, run=run_gh):
        self.repo = repo
        self.ref = ref
        self.run = run
        self._checked = False

    def _api(self, endpoint: str, *extra: str) -> tuple[int, str, str]:
        return self.run(["api", *extra, endpoint])

    def _contents(self, path: str) -> str:
        endpoint = f"repos/{self.repo}/contents" + (f"/{path}" if path else "")
        if self.ref:
            endpoint += f"?ref={self.ref}"
        return endpoint

    def _check_repo(self) -> None:
        if self._checked:
            return
        rc, _, err = self._api(f"repos/{self.repo}")
        if rc != 0:
            if _not_found(err):
                raise AccessError(f"{self.repo}: repository not found or not visible to this gh login")
            raise AccessError(f"{self.repo}: {err.strip() or 'gh failed'}")
        self._checked = True

    def _get(self, path: str):
        """Contents JSON for `path`, None on 404, AccessError otherwise."""
        self._check_repo()
        rc, out, err = self._api(self._contents(path))
        if rc != 0:
            if _not_found(err):
                return None
            raise AccessError(f"{self.repo}/{path}: {err.strip() or 'gh failed'}")
        try:
            return json.loads(out)
        except json.JSONDecodeError as exc:
            raise AccessError(f"{self.repo}/{path}: unreadable answer from gh") from exc

    def list_dir(self, d: str) -> dict[str, int]:
        data = self._get(d)
        if not isinstance(data, list):
            return {}
        return {e["path"]: int(e.get("size") or 0) for e in data if e.get("type") == "file"}

    def stat(self, path: str) -> int | None:
        data = self._get(path)
        if not isinstance(data, dict) or data.get("type") != "file":
            return None
        return int(data.get("size") or 0)

    def read(self, path: str) -> str:
        data = self._get(path)
        if not isinstance(data, dict) or "content" not in data:
            raise AccessError(f"{self.repo}/{path}: no file content returned")
        return base64.b64decode(data["content"]).decode("utf-8", errors="replace")

    def labels(self):
        self._check_repo()
        rc, out, err = self._api(
            f"repos/{self.repo}/labels?per_page=100", "--paginate",
            "--jq", ".[] | {name, description}")
        if rc != 0:
            raise AccessError(f"{self.repo} labels: {err.strip() or 'gh failed'}")
        labels = []
        for line in out.splitlines():
            line = line.strip()
            if line:
                item = json.loads(line)
                labels.append({"name": item.get("name"), "description": item.get("description") or ""})
        return labels


# ---------------------------------------------------------------- CLI

REPO_SLUG = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _source_for(target: str, ref: str | None):
    path = Path(target).expanduser()
    if path.is_dir():
        if ref:
            return None, "--ref applies to an owner/repo target, not a local path"
        return LocalSource(path.resolve()), None
    if REPO_SLUG.match(target) and not path.exists():
        return RemoteSource(target, ref), None
    return LocalSource(path), None  # raises nothing yet; read below reports it


def _report_one(target: str, ref: str | None, with_content: bool) -> dict:
    source, usage = _source_for(target, ref)
    if usage:
        raise SystemExit(f"repo-rules: {usage}")
    entry = {"target": target, "kind": "remote" if isinstance(source, RemoteSource) else "local",
             "ref": ref}
    try:
        if isinstance(source, LocalSource) and not source.root.is_dir():
            raise AccessError(f"{target}: no such directory, and not an owner/repo name")
        entry.update(collect(source, with_content=with_content))
        entry["error"] = None
    except AccessError as exc:
        entry.update({"status": "error", "files": [], "dangling": [], "labels": None,
                      "error": str(exc)})
    return entry


def _human(entry: dict, with_content: bool) -> str:
    ref = f" @ {entry['ref']}" if entry["ref"] else ""
    lines = [f"== {entry['target']}{ref}"]
    if entry["status"] == "error":
        lines.append(f"ACCESS ERROR: {entry['error']}")
        lines.append("rules unknown, read the repository another way before writing")
        return "\n".join(lines)
    if entry["files"]:
        lines.append(f"rule files ({len(entry['files'])}), read before the first write:")
        for f in entry["files"]:
            via = f"  (named in {f['via']})" if f["via"] else ""
            lines.append(f"  {f['path']}  {f['size']} B{via}")
    else:
        lines.append("no working rules found, Bridge defaults apply")
    for d in entry["dangling"]:
        lines.append(f"  named but not found at that path: {d}")
    labels = entry["labels"]
    if labels is None:
        lines.append("labels: not read (local path; pass owner/repo for the label set)")
    else:
        names = ", ".join(lbl["name"] for lbl in labels) or "none"
        lines.append(f"labels ({len(labels)}): {names}")
    if with_content:
        for f in entry["files"]:
            lines.append(f"\n----- {f['path']} -----")
            lines.append(f["content"].rstrip("\n"))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="List a repository's working-rule files and labels before writing to it.")
    parser.add_argument("targets", nargs="+", metavar="path|owner/repo")
    parser.add_argument("--ref", help="branch, tag or SHA (owner/repo targets only)")
    parser.add_argument("--print", dest="show", action="store_true", help="emit each file's text")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    for target in args.targets:
        _, usage = _source_for(target, args.ref)
        if usage:
            parser.error(usage)

    entries = [_report_one(t, args.ref, args.show) for t in args.targets]
    if args.json:
        print(json.dumps(entries, indent=2, ensure_ascii=False))
    else:
        print("\n\n".join(_human(e, args.show) for e in entries))
    return aggregate_exit([e["status"] for e in entries])


if __name__ == "__main__":
    sys.exit(main())
