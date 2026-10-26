# SPDX-License-Identifier: MIT
"""References in a brief: what a reader of a card can reach from the item, and whether a brief points only at that.

A criterion such as "all gaps of epic #95 are closed" or "the open points of the report (§6) are answered" names
something the reader of the card cannot find: which repository holds #95, which report has a §6? describe.py gives
the model the references the item really has (`reachable`, then `references` for the prompt) and checks the answer
against them afterwards (`resolutions`, `unresolved`); card.py turns each text of a brief into parts a page can draw
as text and links (`parts`).

What is reachable (`reachable(text, front, ...)`), at most REFS_MAX entries:
- the repositories the item is bound to: the frontmatter's `sync.github.repo`, else the context's
  `sync.defaults.github.repo`, else every `repos[].github` of the context; with them `sync.github.issues` and
  `pull_requests` as owner/repo#n, and the board of `sync.github.project`;
- full URLs of the text (a github.com issue or pull request URL as its owner/repo#n), owner/repo#n, and a bare #n
  qualified to owner/repo#n when exactly one repository is known ("Board #18" is a board number, never an issue);
- paths the text names that exist (repo-relative, or relative to the item's folder as a Markdown link writes
  them), never one outside the root, and the files of the item's folder;
- slugs of other tasks and streams that exist (open or closed);
- `extra`: what an inbox item's closes_when probe names (gh_pr, gh_issue, task_status, path_exists).

What a brief points at (`find`), in this order, each span taken once: URLs, owner/repo#n, "Board #n", a bare #n, a
section ("§6"), a path (one with a file extension, a trailing slash or two slashes), a file name with a known
extension, a slug in backticks, and a token that is a known slug or repository. A plain hyphenated word or "and/or"
is no reference. `resolutions` maps each found text to {text, ref} (ref is a card link: {kind: web, href},
{kind: file, path} or {kind: task, key, folder}) or None when the reader cannot reach it; a bare #n reads as
owner/repo#n. A section is never a link: it stands as plain text when its text also names a place that resolves,
and is unresolved otherwise.

Pure: the disk is asked through the `exists` and `folder_of` callables only, nothing raises on bad input.
"""
from __future__ import annotations

import posixpath
import re
from typing import Any, Callable, Iterable, NamedTuple

from .card_fields import strip_brief

REFS_MAX = 24             # entries of the reachable list, what the prompt carries
REF_LEN = 160             # a longer reference is left out
CANDIDATES_MAX = 60       # tokens of one text checked against the disk

_TRAIL = ".,;:!?)]}'\""
URL_RE = re.compile(r"https?://[^\s<>()\[\]{}\"'`|]+")
GH_URL_RE = re.compile(r"https?://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/(issues|pull)/(\d+)(?:[/?#].*)?\Z")
GH_REF_RE = re.compile(r"(?<![\w/.@-])([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#(\d+)\b")
BOARD_RE = re.compile(r"(?i)\b(?:board|project|projekt)\s+#(\d+)\b")
BARE_RE = re.compile(r"(?<![\w/#&])#(\d+)\b")
# a colour is no issue: "#a1b2c3" never matches BARE_RE, "colour #123" is skipped by the word before it
COLOUR_RE = re.compile(r"(?i)(?:farbe|colou?r|hex)\s*\Z")
SECTION_RE = re.compile(r"(?<!§)§\s?\d+[a-z]?(?:\.\d+)*")
# what follows a section of a law: "§ 14 UStG", "§ 3 Abs. 2", "§25a Nr. 1" (a law names itself with two capitals)
LAW_RE = re.compile(r"\s*(?:(?:Abs|Nr|S|Satz|Art)\.?\s|Absatz\b|Satz\b|[A-ZÄÖÜ][A-Za-zÄÖÜäöü]*[A-ZÄÖÜ][A-Za-zÄÖÜäöü]*\b)")
PATH_RE = re.compile(r"(?<![\w/.:@-])(?:\.{1,2}/)*[\w.-]+(?:/[\w.-]+)+/?")
# a file name without a folder: documents and data only, so "Node.js" or "Vue.js" stay names of tools
FILE_RE = re.compile(r"(?<![\w/.-])[\w-]+(?:\.[\w-]+)*\.(?:md|markdown|ya?ml|json|csv|txt|pdf|html?|"
                     r"xlsx|docx|pptx|png|jpe?g|eml|xml)\b", re.IGNORECASE)
MDLINK_RE = re.compile(r"\]\(([^)\s]+)\)")
# in backticks a hyphenated word is a slug; a plain word (`done`, `main`) only when it is a known one (WORD_TICK_RE)
TICK_RE = re.compile(r"`([a-z0-9]+(?:-[a-z0-9]+)+)`")
WORD_TICK_RE = re.compile(r"`([a-z0-9]+)`")
SLUG_RE = re.compile(r"(?<![\w/.-])[a-z0-9]+(?:-[a-z0-9]+)+(?![\w/.-])")
REPO_RE = re.compile(r"(?<![\w/.-])[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?![\w/#-])")
EXT_RE = re.compile(r"\.(?=[A-Za-z0-9]{0,4}[A-Za-z])[A-Za-z0-9]{1,5}\Z")
#: the first folders of a Bridge a path without an extension may start with
TOP_DIRS = ("work", "docs", "scripts", "skills", "workflow", "identity", "infra", "rules", "protocols", "trackers",
            "themes", "mods", "agents", "examples")
BOARD_ORG_RE = re.compile(r"[A-Za-z0-9_.-]+\Z")
REPO_NAME_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")


class Found(NamedTuple):
    start: int
    end: int
    type: str         # url, github, board, bare, section, path, file, slug, token
    raw: str


def _d(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _gh_href(repo: str, n: str, kind: str = "issues") -> str:
    return f"https://github.com/{repo}/{kind}/{n}"


def _url_end(text: str, m: re.Match) -> int:
    return m.start() + len(m.group(0).rstrip(_TRAIL))


# ---------------------------------------------------------------- finding references in a text

def _pathish(token: str) -> bool:
    """A path a brief points at: a file extension, a trailing slash, a leading ./ or ../, or a first folder of a
    Bridge (TOP_DIRS); never a date, and/or or Soll/Ist/Delta"""
    if "://" in token or all(part.isdigit() for part in token.strip("/").split("/") if part):
        return False
    return (bool(EXT_RE.search(token.rstrip("/"))) or token.endswith("/") or token.startswith(("./", "../"))
            or token.split("/", 1)[0] in TOP_DIRS)


def find(text: Any, known: Iterable[str] = ()) -> list[Found]:
    """The references of a text, in order (module doc); `known` are slugs and repositories a plain token may name"""
    if not isinstance(text, str) or not text:
        return []
    known = {k.casefold() for k in known if isinstance(k, str)}
    taken: list[tuple[int, int]] = []
    out: list[Found] = []

    def take(start: int, end: int, kind: str, raw: str) -> None:
        if end <= start or any(start < e and s < end for s, e in taken):
            return
        taken.append((start, end))
        out.append(Found(start, end, kind, raw))

    for m in URL_RE.finditer(text):
        end = _url_end(text, m)
        take(m.start(), end, "url", text[m.start():end])
    for m in GH_REF_RE.finditer(text):
        take(m.start(), m.end(), "github", m.group(0))
    for m in BOARD_RE.finditer(text):
        take(m.start(), m.end(), "board", m.group(0))
    for m in BARE_RE.finditer(text):
        if not COLOUR_RE.search(text[max(0, m.start() - 12):m.start()]):
            take(m.start(), m.end(), "bare", m.group(0))
    for m in SECTION_RE.finditer(text):
        if not LAW_RE.match(text, m.end()) and not re.match(r"\s*,\s*\d", text[m.end():]):
            take(m.start(), m.end(), "section", m.group(0))
    for m in PATH_RE.finditer(text):
        token = m.group(0).rstrip(".")
        if _pathish(token):
            take(m.start(), m.start() + len(token), "path", token)
    for m in FILE_RE.finditer(text):
        take(m.start(), m.end(), "file", m.group(0))
    for m in TICK_RE.finditer(text):
        take(m.start(), m.end(), "slug", m.group(1))
    for m in WORD_TICK_RE.finditer(text):
        if m.group(1) in known:
            take(m.start(), m.end(), "token", m.group(1))
    for regex in (SLUG_RE, REPO_RE):
        for m in regex.finditer(text):
            if m.group(0).casefold() in known:
                take(m.start(), m.end(), "token", m.group(0))
    return sorted(out)


# ---------------------------------------------------------------- what a reader can reach

class _Reach:
    def __init__(self, own: str | None):
        self.own = own
        self.refs: list[dict] = []
        self.keys: set[str] = set()

    def add(self, kind: str, text: str, ref: dict, key: str | None = None) -> None:
        key = (key or f"{kind}:{text}").casefold()
        if len(self.refs) >= REFS_MAX or key in self.keys or not text or len(text) > REF_LEN:
            return
        self.keys.add(key)
        self.refs.append({"type": kind, "text": text, "ref": ref})

    def github(self, repo: str, n: Any, href: str | None = None, kind: str = "issues") -> None:
        text = f"{repo}#{n}"
        self.add("github", text, {"kind": "web", "href": href or _gh_href(repo, n, kind)}, f"github:{text}")


def bound_repos(front: Any, context: Any = None) -> list[str]:
    """The repositories an item is bound to: its sync.github.repo, else its context's (module doc)"""
    repo = _d(_d(_d(front).get("sync")).get("github")).get("repo")
    if isinstance(repo, str) and REPO_NAME_RE.fullmatch(repo.strip()):
        return [repo.strip()]
    ctx = _d(context)
    repo = _d(_d(_d(ctx.get("sync")).get("defaults")).get("github")).get("repo")
    if isinstance(repo, str) and REPO_NAME_RE.fullmatch(repo.strip()):
        return [repo.strip()]
    out = []
    for entry in ctx.get("repos") or []:
        gh = _d(entry).get("github")
        if isinstance(gh, str) and REPO_NAME_RE.fullmatch(gh.strip()) and gh.strip() not in out:
            out.append(gh.strip())
    return out


def _inside(path: str) -> str | None:
    """A repo-relative path as written, normalized; None for one that leaves the root or is hidden"""
    if not path or path.startswith(("/", "~")) or "://" in path or "\\" in path:
        return None
    norm = posixpath.normpath(path.split("#", 1)[0])
    if norm in (".", "") or any(part.startswith(".") for part in norm.split("/")):
        return None
    return norm


def reachable(text: Any, front: Any = None, *, own: str | None = None, context: Any = None,
              exists: Callable[[str], bool] | None = None, folder_of: Callable[[str], str | None] | None = None,
              files: Iterable[str] = (), extra: Iterable[Any] = ()) -> dict:
    """{repos, project, own, refs: [{type, text, ref}]}: what a reader of the item's card can reach (module doc).
    `own` is the item's folder (work/tasks/<slug>), `exists(path)` says whether a repo-relative path exists,
    `folder_of(slug)` the folder of a task or stream (None for none), `files` the files of the item's folder."""
    text = strip_brief(text) if isinstance(text, str) else ""
    front = _d(front)
    exists = exists or (lambda _p: False)
    folder_of = folder_of or (lambda _s: None)
    r = _Reach(own)
    gh = _d(_d(front.get("sync")).get("github"))
    repos = bound_repos(front, context)
    own_repo = gh.get("repo").strip() if isinstance(gh.get("repo"), str) and REPO_NAME_RE.fullmatch(gh["repo"].strip()) else None
    project = _d(gh.get("project"))
    board = (project if isinstance(project.get("org"), str) and BOARD_ORG_RE.fullmatch(project["org"])
             and isinstance(project.get("number"), int) and not isinstance(project.get("number"), bool) else None)
    own_slug = own.rstrip("/").rsplit("/", 1)[-1] if own else front.get("slug")
    for repo in repos:
        r.add("repo", repo, {"kind": "web", "href": f"https://github.com/{repo}"})
    if own_repo:      # the issues of the sync block are the item's own repository's, never a context's
        for key, kind in (("issues", "issues"), ("pull_requests", "pull")):
            for n in gh.get(key) or []:
                if isinstance(n, int) and not isinstance(n, bool) and n > 0:
                    r.github(own_repo, n, kind=kind)
    if board:
        url = f"https://github.com/orgs/{board['org']}/projects/{board['number']}"
        r.add("url", url, {"kind": "web", "href": url})

    blank = list(text)

    def blot(start: int, end: int) -> None:
        blank[start:end] = " " * (end - start)

    for m in URL_RE.finditer(text):
        url = text[m.start():_url_end(text, m)]
        gm = GH_URL_RE.match(url)
        if gm:
            r.github(f"{gm.group(1)}/{gm.group(2)}", gm.group(4), href=url)
        else:
            r.add("url", url, {"kind": "web", "href": url})
        blot(m.start(), m.end())
    rest = "".join(blank)
    for m in GH_REF_RE.finditer(rest):
        r.github(m.group(1), m.group(2))
        blot(m.start(), m.end())
    for m in BOARD_RE.finditer("".join(blank)):
        blot(m.start(), m.end())
    if len(repos) == 1:
        for m in BARE_RE.finditer("".join(blank)):
            r.github(repos[0], m.group(1))

    def path(candidate: str, relative: bool = False) -> None:
        tries = ([posixpath.join(own, candidate)] if own else []) if relative else \
            [candidate, *([posixpath.join(own, candidate)] if own else [])]
        for p in tries:
            p = _inside(p)
            if p and exists(p):
                r.add("path", p, {"kind": "file", "path": p}, f"path:{p}")
                return

    seen: set[str] = set()
    candidates = [(m.group(1), True) for m in MDLINK_RE.finditer(text) if not URL_RE.match(m.group(1))]
    candidates += [(m.group(0).rstrip("."), False) for m in PATH_RE.finditer("".join(blank))]
    candidates += [(m.group(0), False) for m in FILE_RE.finditer("".join(blank))]
    candidates += [(p, True) for p in front.get("related") or [] if isinstance(p, str)]
    for candidate, relative in candidates:
        if candidate in seen or len(seen) >= CANDIDATES_MAX:
            continue
        seen.add(candidate)
        path(candidate, relative)
    slugs: list[str] = []
    for m in [*TICK_RE.finditer(text), *WORD_TICK_RE.finditer(text), *SLUG_RE.finditer(text)]:
        slug = m.group(1) if m.re is not SLUG_RE else m.group(0)
        # a slug holds a letter: a date such as 2026-07-13 is none
        if slug != own_slug and slug not in slugs and len(slugs) < CANDIDATES_MAX and re.search("[a-z]", slug):
            slugs.append(slug)
    probes = list(extra)
    while probes:
        probe = _d(probes.pop(0))
        for combine in ("all", "any"):
            if isinstance(probe.get(combine), list):
                probes.extend(probe[combine][:8])
        for key in ("gh_pr", "gh_issue"):
            value = probe.get(key)
            if isinstance(value, str):
                gm = GH_URL_RE.match(value.strip())
                m = GH_REF_RE.fullmatch(value.strip())
                if gm:
                    r.github(f"{gm.group(1)}/{gm.group(2)}", gm.group(4), href=value.strip())
                elif m:
                    r.github(m.group(1), m.group(2), kind="pull" if key == "gh_pr" else "issues")
        if isinstance(probe.get("task_status"), str):
            slugs.insert(0, probe["task_status"])
        if isinstance(probe.get("path_exists"), str):
            path(probe["path_exists"])
    for slug in slugs:
        folder = folder_of(slug)
        if folder:
            done = folder if folder.startswith("work/done/") else None
            r.add("task", slug, {"kind": "task", "key": slug, "folder": done}, f"task:{slug}")
    # the files of the folder last: what the text names comes first when the list is full
    for p in files:
        if isinstance(p, str) and _inside(p):
            r.add("path", p, {"kind": "file", "path": p}, f"path:{p}")
    return {"repos": repos, "project": board, "own": own, "refs": r.refs}


def references(reach: Any) -> list[str]:
    """The texts of what is reachable, for the prompt"""
    return [x["text"] for x in _d(reach).get("refs") or [] if isinstance(x, dict) and isinstance(x.get("text"), str)]


# ---------------------------------------------------------------- resolving what a brief points at

def _lookup(reach: dict) -> dict:
    return {(x["type"], x["text"].casefold()): x for x in reach.get("refs") or []
            if isinstance(x, dict) and isinstance(x.get("text"), str)}


def _resolve(f: Found, reach: dict, table: dict) -> dict | None:
    def hit(kind: str, key: str, text: str | None = None) -> dict | None:
        x = table.get((kind, key.casefold()))
        return {"text": text or f.raw, "ref": dict(x["ref"])} if x else None

    if f.type == "url":
        gm = GH_URL_RE.match(f.raw)
        if gm:
            x = table.get(("github", f"{gm.group(1)}/{gm.group(2)}#{gm.group(4)}".casefold()))
            return {"text": f.raw, "ref": {"kind": "web", "href": f.raw}} if x else None
        return hit("url", f.raw) or hit("url", f.raw.rstrip("/"))
    if f.type == "github":
        return hit("github", f.raw)
    if f.type == "board":
        board = _d(reach.get("project"))
        n = re.search(r"\d+", f.raw).group(0)
        if board and str(board.get("number")) == n:
            return {"text": f.raw, "ref": {"kind": "web",
                                           "href": f"https://github.com/orgs/{board['org']}/projects/{n}"}}
        return None
    if f.type == "bare":
        repos = reach.get("repos") or []
        return hit("github", f"{repos[0]}{f.raw}", f"{repos[0]}{f.raw}") if len(repos) == 1 else None
    if f.type in ("path", "file"):
        p = _inside(f.raw.rstrip("/"))
        if not p:
            return None
        own = reach.get("own")
        found = hit("path", p) or (hit("path", posixpath.join(own, p)) if own else None)
        if found:
            return found
        ends = [x for (kind, _), x in table.items() if kind == "path" and x["text"].endswith("/" + p)]
        return {"text": f.raw, "ref": dict(ends[0]["ref"])} if len(ends) == 1 else None
    if f.type in ("slug", "token"):
        return hit("task", f.raw) or hit("repo", f.raw)
    return None


def _known(reach: dict) -> list[str]:
    return [x["text"] for x in reach.get("refs") or [] if isinstance(x, dict) and x.get("type") in ("task", "repo")]


def resolutions(texts: Iterable[Any], reach: Any) -> dict:
    """{found text: {text, ref} | None} for every reference the texts name (sections aside, see parts)"""
    reach = _d(reach)
    table, known = _lookup(reach), _known(reach)
    out: dict = {}
    for text in texts:
        for f in find(text, known):
            if f.type != "section" and f.raw not in out:
                out[f.raw] = _resolve(f, reach, table)
    return out


def parts(text: Any, refs: Any) -> list[dict] | None:
    """The text in parts a page draws: {text}, {text, ref} (a link) and {text, unresolved: true}. None without a
    `refs` map (nothing says what the text points at) or without any reference in the text. A reference the map
    does not hold stays plain text: the map was made for another text"""
    if not isinstance(refs, dict) or not isinstance(text, str):
        return None
    known = [k for k, v in refs.items() if isinstance(v, dict) and _d(v.get("ref")).get("kind") in ("task", "web")]
    found = find(text, known)
    if not found:
        return None
    placed = any(f.type != "section" and isinstance(refs.get(f.raw), dict) for f in found)
    out: list[dict] = []

    def plain(words: str) -> None:
        if not words:
            return
        if out and set(out[-1]) == {"text"}:
            out[-1] = {"text": out[-1]["text"] + words}
        else:
            out.append({"text": words})

    pos = 0
    for f in found:
        plain(text[pos:f.start])
        pos = f.end
        if f.type == "section":
            if placed:
                plain(f.raw)
            else:
                out.append({"text": f.raw, "unresolved": True})
            continue
        if f.raw not in refs:
            plain(text[f.start:f.end])
        elif isinstance(refs[f.raw], dict) and isinstance(refs[f.raw].get("ref"), dict):
            out.append({"text": str(refs[f.raw].get("text") or f.raw), "ref": dict(refs[f.raw]["ref"])})
        else:
            out.append({"text": f.raw, "unresolved": True})
    plain(text[pos:])
    return out


def unresolved(texts: Iterable[Any], refs: Any) -> list[str]:
    """Every reference of the texts a reader cannot reach, each once, in order"""
    out: list[str] = []
    for text in texts:
        for p in parts(text, refs) or []:
            if p.get("unresolved") and p["text"] not in out:
                out.append(p["text"])
    return out
