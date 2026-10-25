# SPDX-License-Identifier: MIT
"""Search the files of the work system: every task, stream and closed task, the log and its archive.

One search, two callers that must never disagree: `scripts/work-find.py` (the command, also for a chat
session) and the cockpit's `/api/find` (which runs that command through its runner). What it reads:

- `work/tasks/`, `work/streams/`, `work/done/` and `work/archive/`, every `*.md` and `*.yaml` below them,
  never inside a `video/` or `deliverables/` folder, never a hidden file or folder, never a symlink, never a
  file larger than 2 MB, never anything that resolves outside the Bridge root;
- `work/log.md`.

The query is plain words, never a pattern: matched case-insensitively as fixed strings (`a.b(` finds the
text `a.b(`). A file (one task, the folder of one slug) is a hit when its slug, its title and its lines
hold every word between them. A log or archive line belongs to the file its context column names, else to
the first slug it mentions; a line that names none stays with its log or archive file and counts only when
it holds every word itself.

The order is the point, since a common word finds hundreds of files: first the files whose slug or title
holds every word (rank 0), then those with a hit in their STATUS.md (rank 1), then the rest (rank 2); open
before closed, more hit lines first. Each file brings at most HITS_MAX lines with a short snippet.

`rg` (ripgrep) only narrows which files to read when it is installed: argv only, `--fixed-strings`, every
word behind `-e`, the paths behind `--`, no config, no ignore files. The reading and ranking is the same
Python for both ways, so the answer does not depend on whether `rg` is there; without it every eligible
file is read.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import yaml

QUERY_MAX = 200
WORDS_MAX = 8
HITS_MAX = 5
GROUPS_MAX = 40
SNIPPET_MAX = 200
FILE_MAX = 2 * 1024 * 1024
RG_TIMEOUT = 20
EXTS = (".md", ".yaml")
SKIP_DIRS = frozenset({"video", "deliverables"})
TREES = ("tasks", "streams", "done", "archive")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
LOG_ROW_RE = re.compile(r"^\| \d{4}-\d{2}-\d{2} \d{2}:\d{2} \|")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}\Z")
KIND_ORDER = {"task": 0, "stream": 0, "done": 1, "log": 2, "archive": 2}


def check_query(query: object) -> tuple[str, list[str]]:
    """The query as searched and its words (case-folded, each once, in order); ValueError when it is not one:
    not a string, a control character, shorter than 2 or longer than QUERY_MAX characters."""
    if not isinstance(query, str):
        raise ValueError("the query must be a string")
    if CONTROL_RE.search(query):
        raise ValueError("control characters are not allowed")
    text = " ".join(query.split())
    if not 2 <= len(text) <= QUERY_MAX:
        raise ValueError(f"the query must be 2 to {QUERY_MAX} characters")
    words: list[str] = []
    for word in text.casefold().split():
        if word not in words:
            words.append(word)
    return text, words[:WORDS_MAX]


def _eligible(root: Path, rel: str) -> bool:
    """A file the search may read: under one of the trees or the log, a known extension, no hidden or skipped
    folder on the way, no symlink, not too large, inside the root once resolved."""
    parts = rel.split("/")
    if rel != "work/log.md":
        if len(parts) < 3 or parts[0] != "work" or parts[1] not in TREES:
            return False
        if not rel.endswith(EXTS):
            return False
        if any(p.startswith(".") or p in SKIP_DIRS or p in ("", "..") for p in parts[2:]):
            return False
    path = root / rel
    try:
        here = root
        for p in parts:
            here = here / p
            if here.is_symlink():
                return False
        if not path.is_file() or path.stat().st_size > FILE_MAX:
            return False
        path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _walk(root: Path) -> list[str]:
    """Every eligible file, the Python way: what `rg` would hand on, without asking it."""
    out = []
    for tree in TREES:
        base = root / "work" / tree
        if not base.is_dir() or base.is_symlink():
            continue
        for here, dirs, files in os.walk(base, followlinks=False):
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS)
            for name in files:
                rel = (Path(here) / name).relative_to(root).as_posix()
                if _eligible(root, rel):
                    out.append(rel)
    if _eligible(root, "work/log.md"):
        out.append("work/log.md")
    return sorted(out)


def rg_argv(rg: str, words: list[str], paths: list[str]) -> list[str]:
    """The one shape `rg` is called in: the files that hold any word, every word a fixed string behind -e."""
    argv = [rg, "--files-with-matches", "--no-config", "--no-ignore", "--no-messages", "--ignore-case",
            "--fixed-strings", "--max-filesize", "2M", "--glob", "*.md", "--glob", "*.yaml",
            "--glob", "!video/", "--glob", "!deliverables/"]
    for word in words:
        argv += ["-e", word]
    return argv + ["--", *paths]


def _rg_files(root: Path, rg: str, words: list[str]) -> list[str] | None:
    """The files `rg` finds any word in, or None when it cannot answer (missing, failed, timed out)."""
    paths = [f"work/{t}" for t in TREES if (root / "work" / t).is_dir()]
    if (root / "work" / "log.md").is_file():
        paths.append("work/log.md")
    if not paths:
        return []
    try:
        run = subprocess.run(rg_argv(rg, words, paths), cwd=str(root), stdin=subprocess.DEVNULL, capture_output=True,
                             timeout=RG_TIMEOUT, shell=False, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    out = run.stdout.decode("utf-8", errors="replace")
    if run.returncode not in (0, 1) and not out.strip():
        return None
    found = {line.strip().replace("\\", "/").removeprefix("./") for line in out.splitlines() if line.strip()}
    return sorted(rel for rel in found if _eligible(root, rel))


def known_slugs(root: Path) -> dict[str, tuple[str, str]]:
    """slug -> (kind, folder): an open task first, then a stream, then the newest closed one (as /api/task)."""
    out: dict[str, tuple[str, str]] = {}
    work = root / "work"
    places = [("task", work / "tasks"), ("stream", work / "streams")]
    done = work / "done"
    if done.is_dir():
        places += [("done", month) for month in sorted(done.iterdir(), reverse=True)
                   if month.is_dir() and not month.name.startswith(".")]
    for kind, base in places:
        if not base.is_dir():
            continue
        for d in sorted(base.iterdir()):
            if d.is_dir() and not d.is_symlink() and SLUG_RE.match(d.name) and d.name not in out:
                out[d.name] = (kind, d.relative_to(root).as_posix())
    return out


def _slug_of_path(rel: str) -> str | None:
    parts = rel.split("/")
    if len(parts) >= 4 and parts[1] in ("tasks", "streams"):
        return parts[2]
    if len(parts) >= 5 and parts[1] == "done":
        return parts[3]
    return None


def _slug_of_line(line: str, slugs: dict, order: list[str]) -> str | None:
    """A log or archive line's file: the context column of a log row, else the first slug it names."""
    if LOG_ROW_RE.match(line):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and cells[2] in slugs:
            return cells[2]
    low = line.casefold()
    for slug in order:
        at = low.find(slug)
        while at >= 0:
            before = low[at - 1] if at else " "
            end = at + len(slug)
            after = low[end] if end < len(low) else " "
            if not (before.isalnum() or before == "-") and not (after.isalnum() or after == "-"):
                return slug
            at = low.find(slug, at + 1)
    return None


def snippet(line: str, words: list[str]) -> str:
    text = " ".join(line.split())
    if len(text) <= SNIPPET_MAX:
        return text
    low = text.casefold()
    at = min((low.find(w) for w in words if w in low), default=0)
    start = max(0, at - 60)
    cut = text[start:start + SNIPPET_MAX]
    return ("…" if start else "") + cut + ("…" if start + SNIPPET_MAX < len(text) else "")


def title_of(root: Path, folder: str, slug: str) -> str:
    """A file's title: the headline of its STATUS.md, else its first `# ` heading, else its slug."""
    try:
        text = (root / folder / "STATUS.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return slug
    body = text
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.strip() == "---"), None)
    if start is not None and all(not ln.strip() or ln.lstrip().startswith("#") for ln in lines[:start]):
        end = next((i for i in range(start + 1, len(lines)) if lines[i].strip() == "---"), None)
        if end is not None:
            try:
                front = yaml.safe_load("\n".join(lines[start + 1:end]))
            except yaml.YAMLError:
                front = None
            if isinstance(front, dict) and isinstance(front.get("headline"), str) and front["headline"].strip():
                return " ".join(front["headline"].split())[:300]
            body = "\n".join(lines[end + 1:])
    for ln in body.splitlines():
        if ln.startswith("# "):
            return ln[2:].strip()[:300] or slug
    return slug


def find(root: Path | str, query: object, *, engine: str = "auto", rg: str | None = None,
         groups_max: int = GROUPS_MAX) -> dict:
    """The files that hold every word of `query`, ranked. `engine` "auto" asks `rg` when it is installed and
    reads every file itself when not (or when `rg` fails), "rg" and "python" force one way. ValueError for a
    query check_query refuses."""
    root = Path(root).resolve()
    text, words = check_query(query)
    used = "python"
    files: list[str] | None = None
    if engine in ("auto", "rg"):
        binary = rg or shutil.which("rg")
        if binary:
            files = _rg_files(root, binary, words)
            used = "rg" if files is not None else "python"
    if files is None:
        files = _walk(root)
    slugs = known_slugs(root)
    order = sorted(slugs, key=lambda s: (-len(s), s))
    groups: dict[tuple, dict] = {}

    def group(key: tuple, slug: str | None, kind: str, path: str) -> dict:
        if key not in groups:
            groups[key] = {"slug": slug, "kind": kind, "path": path, "words": set(), "hits": [], "status": False}
        return groups[key]

    for rel in files:
        try:
            lines = (root / rel).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        loose = rel == "work/log.md" or rel.startswith("work/archive/")
        own = None if loose else _slug_of_path(rel)
        for n, line in enumerate(lines, 1):
            low = line.casefold()
            got = {w for w in words if w in low}
            if not got:
                continue
            slug = own if not loose else _slug_of_line(line, slugs, order)
            if slug and slug in slugs:
                kind, folder = slugs[slug]
                g = group(("file", slug), slug, kind, folder)
            elif not loose:
                continue      # a folder with no slug of its own (a stray file in a tree): no file to open
            else:
                if len(got) < len(words):
                    continue  # a line nobody owns counts only when it holds every word itself
                g = group(("loose", rel), None, "log" if rel == "work/log.md" else "archive", rel)
            g["words"] |= got
            is_status = rel.endswith("/STATUS.md") and not loose
            g["status"] = g["status"] or is_status
            g["hits"].append({"path": rel, "line": n, "text": snippet(line, words), "n": len(got), "status": is_status})
    # a file whose name alone holds every word is found without a line
    for slug, (kind, folder) in slugs.items():
        if all(w in slug for w in words):
            group(("file", slug), slug, kind, folder)
    out = []
    for g in groups.values():
        title = title_of(root, g["path"], g["slug"]) if g["slug"] else g["path"]
        name = f"{g['slug'] or ''} {title}".casefold()
        named = bool(g["slug"]) and all(w in name for w in words)
        if not named and not set(words) <= (g["words"] | {w for w in words if w in name}):
            continue
        rank = 0 if named else 1 if g["status"] else 2
        hits = sorted(g["hits"], key=lambda h: (not h["status"], -h["n"], h["path"], h["line"]))
        out.append({"slug": g["slug"], "kind": g["kind"], "path": g["path"], "title": title, "rank": rank,
                    "count": len(hits), "hits": [{k: h[k] for k in ("path", "line", "text")} for h in hits[:HITS_MAX]]})
    out.sort(key=lambda g: (g["rank"], KIND_ORDER.get(g["kind"], 3), -g["count"], g["slug"] or g["path"]))
    return {"ok": True, "query": text, "words": words, "engine": used, "total": len(out),
            "truncated": len(out) > groups_max, "groups": out[:groups_max]}


def render(result: dict) -> str:
    """The answer as lines for a terminal: one line per file, its hits indented under it."""
    if not result["groups"]:
        return f"nothing found for {result['query']!r}"
    lines = []
    for g in result["groups"]:
        lines.append(f"{g['slug'] or g['path']}  ({g['kind']}, {g['count']} hits)  {g['title']}")
        for h in g["hits"]:
            lines.append(f"    {h['path']}:{h['line']}: {h['text']}")
    more = f", the first {len(result['groups'])} shown" if result["truncated"] else ""
    lines.append(f"{result['total']} files{more} · {result['engine']}")
    return "\n".join(lines)
