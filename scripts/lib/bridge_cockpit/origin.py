# SPDX-License-Identifier: MIT
"""Where a work row comes from, as one category the page names in a word (docs/bridge-cockpit.md, "Where a row
comes from").

Pure and never raising: the collector, the detail calls and the rebuild paths hand it a row (or an inbox item's free
`from` text) and a `Known`, the names this Bridge declares (skills, declared runs, machines, its tasks and streams,
the sections of the view and the person's own `cockpit.origin_map`). Nothing here names a machine, a customer or a
skill of one instance: the rules are shapes (a `/session` suffix, a `tab:` prefix, an agent tool, a `<host>/<job>`
pair, a tracker provider) and lookups in the instance's own tree. What no rule recognises is `other` and keeps its
raw text, so the classification never hides what was written.

The result is {category, word_key, detail, raw, ref, via_cockpit}: `raw` exactly as written (or None), `detail` a
short part of it for the chip, `word_key` the board name of a `tracker` row and the work kind of a `work` row.
"""
from __future__ import annotations

import fnmatch
import re
import threading
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

CATEGORIES = ("github", "tracker", "calendar", "bot", "session", "skill", "work", "person", "bridge", "other")
WORK_KINDS = ("task", "stream", "done_task", "done_stream")
# agent tools that file from a session; generic, no instance names
AGENT_CLIS = ("claude", "codex", "gemini", "copilot", "cursor", "opencode")
SESSION_SEGMENTS = ("session", "chat")
DETAIL_MAX = 32
# an issue or merge request reference; applied to keys, ids and task origin text only, never to summaries
REF_RE = re.compile(r"([\w.-]+/[\w.-]+#\d+)")
REF_FULL_RE = re.compile(r"[\w.-]+/[\w.-]+#\d+")
# the same lists as briefing.py TRACKERS and GITHUB_TRACKERS (a test holds them equal)
TRACKERS = ("github", "github-board", "github-work", "gitlab", "ado", "jira", "linear")
GITHUB_TRACKERS = ("github", "github-board", "github-work")
# how a board reads when its playbook gives no better name than its id
BOARD_NAMES = {"gitlab": "GitLab", "ado": "Azure Boards", "jira": "Jira", "linear": "Linear"}
COCKPIT_FROM = "bridge-cockpit"
SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}\Z")
WAS_STREAM_RE = re.compile(r"^was_stream:\s*true\s*$", re.M | re.I)
TASK_ORIGIN_RE = re.compile(r"^inbox \S+ \([^,()]*, ([^()]+)\):")
# task.py's own origin for a task started here with no inbox item behind it
ADHOC_RE = re.compile(r"^ad-hoc(?: \d{4}-\d{2}-\d{2})?$", re.I)
# a GitHub issue or pull request URL, its repo and number
GITHUB_URL_RE = re.compile(r"https?://(?:www\.)?github\.com/([\w.-]+)/([\w.-]+)(?:/(?:issues|pull)/(\d+))?", re.I)
# a task origin that names GitHub as where it began: the ref or the URL first, after at most a word like "from"
GITHUB_START_RE = re.compile(r"^(?:(?:from|issue|pr|pull request|see)\s+)?(?:https?://(?:www\.)?github\.com/\S+|[\w.-]+/[\w.-]+#\d+)(?=$|[\s,.;:)])", re.I)
# names that read as an automatic job by their ending, on any Bridge
BOT_SUFFIXES = ("-bot", "-notifier", "-autorun", "-watcher", "-watchdog", "-probe", "-monitor", "-cron", "-daemon", "-poller")
# what a source that is no source reads as (task.py writes None when an item had none)
NO_SOURCE = ("none", "null", "-")
CACHE_SECONDS = 30.0


@dataclass(frozen=True)
class Known:
    skills: frozenset = frozenset()     # skills/<name>/ dirs that hold a SKILL.md
    runs: frozenset = frozenset()       # declared runs: workloads, channels, agents/<name>/ with an agent.yaml
    scripts: frozenset = frozenset()    # the Bridge's own filers: scripts/*.py and skills/*/scripts/*.py stems
    hosts: frozenset = frozenset()      # infra/remotes ids and their declared names
    work: Mapping = field(default_factory=dict)         # slug -> task | stream | done_task | done_stream
    mapping: tuple = ()                 # cockpit.origin_map: ((pattern_lower, category), ...) in file order
    sections: Mapping = field(default_factory=dict)     # section id -> {kind, provider, title} of the view
    boards: Mapping = field(default_factory=dict)       # provider -> the board name its playbook gives


# ---------------------------------------------------------------- what this Bridge declares

def front_block(text: Any) -> str:
    """The frontmatter of a STATUS.md as text, between its two `---` fences, after any leading comment or blank
    lines (task.py writes a `# yaml-language-server: ...` line first); "" for a file without one"""
    if not isinstance(text, str):
        return ""
    lines = text.splitlines()
    i = 0
    while i < len(lines) and (not lines[i].strip() or lines[i].lstrip().startswith("#")):
        i += 1
    if i >= len(lines) or lines[i].strip() != "---":
        return ""
    end = next((j for j in range(i + 1, len(lines)) if lines[j].strip() == "---"), len(lines))
    return "\n".join(lines[i + 1:end])


def was_stream(text: Any) -> bool:
    """Whether a closed STATUS.md was a stream (task.py close keeps `was_stream: true`)"""
    return WAS_STREAM_RE.search(front_block(text)) is not None


def _stems(folder: Path) -> set:
    try:
        return {p.stem.lower() for p in folder.glob("*.yaml") if not p.name.startswith("_")}
    except OSError:
        return set()


def _dirs(folder: Path, need: str | None = None) -> set:
    try:
        return {p.name.lower() for p in folder.iterdir()
                if p.is_dir() and not p.name.startswith(("_", ".")) and (need is None or (p / need).is_file())}
    except OSError:
        return set()


def _remote_names(folder: Path) -> set:
    """infra/remotes ids, plus the names an entry declares for itself (hostname, aliases), read without a YAML parser"""
    out = _stems(folder)
    try:
        files = [p for p in folder.glob("*.yaml") if not p.name.startswith("_")]
    except OSError:
        return out
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")[:20000]
        except OSError:
            continue
        # top-level keys only: a nested `name:` is a service's or a user's, not the machine's
        for m in re.finditer(r"^(?:hostname|host_name|name|alias):\s*[\"']?([A-Za-z0-9._-]{1,64})[\"']?\s*$", text, re.M):
            out.add(m.group(1).lower())
        block = re.search(r"^aliases:\s*(\[[^\]]*\]|(?:\n\s+-\s*.+)+)", text, re.M)
        if block:
            out |= {x.lower() for x in re.findall(r"[A-Za-z0-9._-]{1,64}", block.group(1))}
    return out


def _work(root: Path) -> dict:
    work: dict = {}
    base = root / "work"
    try:
        done = sorted((p for p in (base / "done").iterdir() if p.is_dir()), reverse=True) if (base / "done").is_dir() else []
    except OSError:
        done = []
    for month in reversed(done):          # oldest first, so the newest closing of a slug wins
        try:
            folders = [p for p in month.iterdir() if p.is_dir() and (p / "STATUS.md").is_file()]
        except OSError:
            continue
        for p in folders:
            try:
                head = (p / "STATUS.md").read_text(encoding="utf-8", errors="replace")[:4000]
            except OSError:
                head = ""
            work[p.name] = "done_stream" if was_stream(head) else "done_task"
    for kind, folder in (("stream", "streams"), ("task", "tasks")):      # a live slug wins over a closed one
        try:
            names = [p.name for p in (base / folder).iterdir() if p.is_dir() and not p.name.startswith("_")]
        except OSError:
            names = []
        for name in names:
            work[name] = kind
    return work


def _boards(root: Path) -> dict:
    out = {}
    for provider in TRACKERS:
        path = root / "trackers" / f"{provider}.md"
        name = None
        try:
            head = path.read_text(encoding="utf-8", errors="replace")[:2000] if path.is_file() else ""
        except OSError:
            head = ""
        for key in ("title", "name"):
            m = re.search(rf"^{key}:\s*[\"']?([^\"'\n]{{1,40}})[\"']?\s*$", head, re.M)
            if m:
                name = m.group(1).strip()
                break
        if not name or name.lower() == provider:
            name = BOARD_NAMES.get(provider, name or provider)
        out[provider] = name
    return out


_CACHE: dict = {}
_LOCK = threading.Lock()


def _scripts(root: Path) -> set:
    """The stems of the Bridge's own scripts (scripts/*.py, skills/*/scripts/*.py): CORE files by these names"""
    out = set()
    for pattern in ("scripts/*.py", "skills/*/scripts/*.py"):
        try:
            out |= {p.stem.lower() for p in root.glob(pattern) if not p.name.startswith(("_", "."))}
        except OSError:
            pass
    return out


def _tree(root: Path) -> Known:
    root = Path(root)
    return Known(skills=frozenset(_dirs(root / "skills", "SKILL.md")),
                 runs=frozenset(_stems(root / "workflow" / "workloads") | _stems(root / "infra" / "channels")
                                | _dirs(root / "agents", "agent.yaml")),
                 scripts=frozenset(_scripts(root)),
                 hosts=frozenset(_remote_names(root / "infra" / "remotes")),
                 work=_work(root), boards=_boards(root))


def known_from_root(root: Any, mapping: tuple = (), sections: Mapping | None = None, *, fresh: bool = False,
                    clock=time.monotonic) -> Known:
    """The names of this Bridge, read from its tree at most every CACHE_SECONDS (a collector pass and the detail calls
    share it), with the person's map and the sections of the current view on top. Never raises: a tree that cannot
    be read gives empty sets, so every row is still classified by its shape."""
    try:
        key = str(Path(root).resolve())
    except (OSError, TypeError, ValueError):
        return Known(mapping=tuple(mapping or ()), sections=dict(sections or {}))
    now = clock()
    with _LOCK:
        hit = _CACHE.get(key)
    if fresh or hit is None or now - hit[0] > CACHE_SECONDS:
        try:
            tree = _tree(Path(key))
        except Exception:  # noqa: BLE001 - a lookup is a nicety, never a reason to lose the page
            tree = Known()
        with _LOCK:
            _CACHE[key] = (now, tree)
    else:
        tree = hit[1]
    return replace(tree, mapping=tuple(mapping or ()), sections=dict(sections or {}))


# ---------------------------------------------------------------- one free `from` text

def _clip(text: Any) -> str | None:
    if not isinstance(text, str) or not text.strip():
        return None
    text = text.strip()
    return text if len(text) <= DETAIL_MAX else text[:DETAIL_MAX - 1].rstrip() + "…"


def _result(category: str, detail: Any = None, raw: Any = None, *, word_key: str | None = None,
            ref: str | None = None, via_cockpit: bool = False) -> dict:
    return {"category": category, "word_key": word_key, "detail": _clip(detail), "raw": raw if isinstance(raw, str) and raw else None,
            "ref": ref, "via_cockpit": via_cockpit}


def _mapped(low: str, mapping: tuple) -> str | None:
    pairs = [(str(p).lower(), c) for p, c in mapping or () if isinstance(p, str) and c in CATEGORIES]
    for pattern, cat in pairs:
        if pattern == low:
            return cat
    for pattern, cat in pairs:
        if any(ch in pattern for ch in "*?[") and fnmatch.fnmatchcase(low, pattern):
            return cat
    return None


def _github(text: str) -> dict | None:
    """GitHub named as the source: the word, an issue or pull request URL, or an `owner/repo#n` ref"""
    low = text.lower()
    if low in ("github", "gh", "github.com"):
        return _result("github", None, text)
    m = GITHUB_URL_RE.match(text)
    if m:
        repo = f"{m.group(1)}/{m.group(2)}"
        return _result("github", repo, text, ref=f"{repo}#{m.group(3)}" if m.group(3) else None)
    if REF_FULL_RE.fullmatch(text):
        return _result("github", text.split("#", 1)[0], text, ref=text)
    return None


def _work_of(text: str, known: Known, kinds: tuple) -> dict | None:
    kind = known.work.get(text) or known.work.get(text.lower())
    return _result("work", text, text, word_key=kind) if kind in kinds else None


def _rules(text: str, known: Known, *, top: bool) -> dict:
    low = text.lower()
    segs = [s for s in low.split("/")]
    raw_segs = text.split("/")
    m = re.match(r"^tab[:-](.+)$", text, re.I)
    if m:                                                           # 2. a tab of the workplace
        return _result("session", m.group(1), text)
    tool = low[: -len("-session")] if low.endswith("-session") else low
    if low in AGENT_CLIS or segs[0] in AGENT_CLIS or tool in AGENT_CLIS:      # 3. an agent tool
        return _result("session", next(c for c in (low, segs[0], tool) if c in AGENT_CLIS), text)
    if low.endswith("-session") and tool:                          # 4. a session by its suffix
        return _result("session", text[: -len("-session")], text)
    if len(segs) >= 2 and segs[1] in SESSION_SEGMENTS and segs[0]:
        return _result("session", raw_segs[0], text)
    gh = _github(text)                                              # 5. GitHub named as the source
    if gh:
        return gh
    if top and len(segs) >= 2 and segs[0] == "bridge" and "/".join(segs[1:]):     # 6. bridge/<what>
        rest = "/".join(raw_segs[1:])
        inner = _rules(rest, known, top=False)
        return inner if inner["category"] != "other" else _result("bot", rest, text)
    live = _work_of(text, known, ("task", "stream"))               # 7. an open task or stream: the closest name
    if live:
        return live
    if low in known.runs or low in known.hosts:                    # 8. a declared run, a machine
        return _result("bot", text, text)
    if "-" in low and low.split("-", 1)[0] in AGENT_CLIS:           # 9. an agent tool by its full name (claude-code)
        return _result("session", low.split("-", 1)[0], text)
    if len(segs) >= 2 and segs[0] and segs[1] and segs[0] not in known.skills:     # 10. <host>/<job>
        # only a machine this Bridge knows is dropped from the detail; any other first part says what filed it
        return _result("bot", "/".join(raw_segs[1:]) if segs[0] in known.hosts else text, text)
    if low in known.skills or segs[0] in known.skills:             # 11. a skill run
        return _result("skill", text, text)
    done = _work_of(text, known, ("done_task", "done_stream"))     # 12. a closed task or an ended stream
    if done:
        return done
    if low in known.scripts or low.endswith(BOT_SUFFIXES):         # 13. the Bridge's own filers, a bot by its name
        return _result("bot", text, text)
    return _result("other", text, text)                             # 14. as written


def classify_from(raw: Any, known: Known | None = None) -> dict | None:
    """The category of a free `from` text (an inbox item's source): the person's map first, then the shape rules.
    None for no text at all. Never raises."""
    try:
        if not isinstance(raw, str) or not raw.strip():
            return None
        known = known or Known()
        text = raw.strip()
        if text.lower() in NO_SOURCE:
            return None
        cat = _mapped(text.lower(), known.mapping)
        if cat:
            segs = text.split("/")
            if len(segs) > 1 and (segs[0].lower() == "bridge" or segs[0].lower() in known.hosts):
                segs = segs[1:]
            return _result(cat, "/".join(segs), raw)
        if text.lower() == COCKPIT_FROM:                             # a click in the cockpit, by a person
            return _result("person", None, raw, via_cockpit=True)
        out = _rules(text, known, top=True)
        out["raw"] = raw
        return out
    except Exception:  # noqa: BLE001 - a label is a nicety
        return _result("other", raw if isinstance(raw, str) else None, raw if isinstance(raw, str) else None)


def from_task_origin(text: Any) -> str | None:
    """The `from` of the inbox item a task was made from, out of its STATUS.md origin
    ("inbox <id> (<date>, <from>): <summary>", task.py); None for any other origin"""
    if not isinstance(text, str):
        return None
    m = TASK_ORIGIN_RE.match(text.strip())
    return m.group(1).strip() or None if m else None


def work_kind(slug: Any, known: Known | None = None) -> str | None:
    if not isinstance(slug, str) or not SLUG_RE.match(slug):
        return None
    return (known or Known()).work.get(slug)


# ---------------------------------------------------------------- one row

def _repo_of(ref: str | None, url: str | None) -> str | None:
    if ref and REF_FULL_RE.fullmatch(ref):
        return ref.split("#", 1)[0]
    try:
        parts = [p for p in urlparse(url or "").path.split("/") if p]
    except ValueError:
        return None
    return "/".join(parts[:2]) if len(parts) >= 2 else None


def _host(url: Any) -> str:
    try:
        return (urlparse(url).hostname or "").lower() if isinstance(url, str) else ""
    except ValueError:
        return ""


def _section(row: dict, known: Known, sid: str | None = None) -> dict:
    """The section a row came from: the one named (`sid`, a cockpit filing names it in its key) before the row's own
    first source; the kind the row carries counts unless it is the inbox the filing landed in"""
    named = sid is not None
    sid = sid or next((s for s in row.get("sources") or [] if isinstance(s, str)), None)
    sec = known.sections.get(sid) if sid else None
    sec = sec if isinstance(sec, dict) else {}
    own = row.get("origin_section_kind") if row.get("origin_section_kind") != "inbox" else None
    return {"id": sid, "kind": (sec.get("kind") or own) if named else (own or sec.get("kind")),
            "provider": row.get("origin_provider") or sec.get("provider"),
            "title": sec.get("title") or sid}


def _from_section(row: dict, known: Known, sec: dict, ref: str | None = None) -> dict:
    provider, kind, title = sec.get("provider"), sec.get("kind"), sec.get("title")
    ref = ref or (row.get("ref") if isinstance(row.get("ref"), str) else None)
    url = row.get("url") if isinstance(row.get("url"), str) else None
    if provider in GITHUB_TRACKERS or (not provider and (_host(url) == "github.com" or (ref and REF_FULL_RE.fullmatch(ref)))):
        return _result("github", _repo_of(ref, url), None, ref=ref)
    if provider in TRACKERS:
        return _result("tracker", _repo_of(ref, url), None, word_key=known.boards.get(provider) or BOARD_NAMES.get(provider, provider), ref=ref)
    if kind == "calendar":
        return _result("calendar", title)
    if kind == "command":
        return _result("bot", title)
    if str(row.get("key") or "").startswith("advise:") or kind == "advise":
        return _result("bridge", title)
    return _result("other", title or next(iter(row.get("sources") or []), None))


def _filed_by_cockpit(row: dict, raw: str | None) -> tuple[bool, str | None]:
    """Whether a click in the cockpit filed this item, and the section it was filed from"""
    key = str(row.get("inbox_key") or "")
    parts = key.split(":", 3)
    if parts[0] == "briefing" and len(parts) == 4:
        return True, parts[2]
    if key.startswith("web:"):
        rest = key[4:]
        if rest.startswith("ref:") and REF_FULL_RE.fullmatch(rest[4:]):     # a board row: web:ref:<owner/repo#n>
            return True, None
        m = re.match(r"^item:([^:]+):", rest)
        if m and not REF_FULL_RE.fullmatch(m.group(1)):
            return True, m.group(1)
        m = re.match(r"^item:[^/]+/([^/]+)/", rest)          # a page item: item:<page>/<section>/<id>
        return True, m.group(1) if m else None
    if isinstance(raw, str) and raw.strip().lower() == COCKPIT_FROM:
        return True, None
    return False, None


def _tab_slug(key: str, known: Known) -> str | None:
    if not key.startswith("tab-"):
        return None
    rest = key[4:]
    slugs = sorted((s for s in known.work if rest.startswith(s + "-")), key=len, reverse=True)
    if slugs:
        return slugs[0]
    m = re.match(r"^(.+)-[^-]+$", rest)
    return m.group(1) if m else None


def classify_row(row: Any, known: Known | None = None) -> dict | None:
    """Who or what filed a work row (inbox item), or where it lives (a tracker or section row), or how a task began.
    None when there is nothing to say (an inbox row of a view saved before the field existed). Never raises."""
    try:
        if not isinstance(row, dict):
            return None
        known = known or Known()
        raw = row.get("origin_raw") if isinstance(row.get("origin_raw"), str) and row["origin_raw"].strip() \
            and row["origin_raw"].strip().lower() not in NO_SOURCE else None
        key = str(row.get("inbox_key") or "")
        if row.get("inbox_id"):
            hit = REF_RE.search(key)
            ref = hit.group(1) if hit else (row.get("ref") if isinstance(row.get("ref"), str) else None)
            if raw is None:
                slug = _tab_slug(key, known)
                # no source written down: a neutral "other" the page still names, never a row without a tag
                return _result("session", slug, None, ref=ref) if slug else _result("other", None, None, ref=ref)
            by_cockpit, sid = _filed_by_cockpit(row, raw)
            if by_cockpit:
                web_ref = key[8:] if key.startswith("web:ref:") and REF_FULL_RE.fullmatch(key[8:]) else None
                sec = _section(row, known, sid) if sid or row.get("origin_section_kind") or row.get("origin_provider") \
                    else {"kind": None, "provider": None, "title": None}
                if web_ref and not (sec.get("kind") in ("tracker", "calendar", "command") or sec.get("provider")):
                    out = _from_section(row, known, {"provider": row.get("origin_provider"), "kind": "tracker",
                                                     "title": None}, web_ref)
                elif sec.get("kind") in ("tracker", "calendar", "command") or sec.get("provider"):
                    out = _from_section(row, known, sec, ref)
                else:
                    out = _result("person", None, raw, ref=ref)
                out.update(raw=raw, via_cockpit=True)
                out["ref"] = out.get("ref") or ref
                return out
            out = classify_from(raw, known)
            if out is not None:
                out["ref"] = ref
            return out
        ref = row.get("ref") if isinstance(row.get("ref"), str) else None
        if str(row.get("key") or "").startswith("advise:"):
            return _result("bridge", _section(row, known).get("title"))
        if row.get("task") and not (ref and REF_FULL_RE.fullmatch(ref)) and not row.get("origin_provider"):
            if raw is None or ADHOC_RE.match(raw.strip()):          # started here, nothing else written down
                return _result("bridge", None, raw)
            if TASK_ORIGIN_RE.match(raw.strip()):                    # made from an inbox item
                inner = from_task_origin(raw)
                out = classify_from(inner, known) if inner and inner.strip().lower() not in NO_SOURCE else None
                if out is None:
                    return _result("other", None, raw)
                out["raw"] = raw
                return out
            first = raw.split()[0].lower()
            if first in known.skills:
                return _result("skill", raw.split()[0], raw)
            text = raw.strip()
            if GITHUB_START_RE.match(text):                          # begun on GitHub: the ref or URL comes first
                hit = REF_RE.search(text)
                url = GITHUB_URL_RE.search(text)
                if url and (not hit or url.start() < hit.start()):
                    repo = f"{url.group(1)}/{url.group(2)}"
                    return _result("github", repo, raw, ref=f"{repo}#{url.group(3)}" if url.group(3) else None)
                return _result("github", _repo_of(hit.group(1), None), raw, ref=hit.group(1))
            # a source was written down that no rule knows (a call, a meeting, a mail): shown as written
            return _result("other", raw, raw)
        return _from_section(row, known, _section(row, known))
    except Exception:  # noqa: BLE001 - a label is a nicety, never a reason to lose the row
        return None
