# SPDX-License-Identifier: MIT
"""Read-only readers for the detail endpoints: a task's STATUS.md and an inbox item.

/api/task reads work/tasks/<slug>/STATUS.md, else work/streams/<slug>/, else the newest
work/done/<month>/<slug>/ (the resolved path must stay inside work/); with `path` exactly that one of these
folders (the search finds an open and a closed file of one slug apart): front matter, every `## ` section (body
cut to 6000 characters), and the last 15 rows of work/log.md that name the slug.
It also lists the open inbox items that name the slug as their task, and the files of its folder besides
STATUS.md (`files`: every *.md and *.yaml, at most eight folders deep, never in a video/, deliverables/ or
node_modules/ folder, never a hidden one or a link, and never walked into such a folder); `file=` reads one of
exactly those (task_file), at most 40000 characters of it. A name is any text without a slash, backslash or
control character that does not start with a dot (FILE_RE), so whatever the list shows can be read.
/api/inbox reads work/inbox/<id>/item.yaml and events/*.yaml (the last 50), with how the item
ends (`closer`, `closes_when` as plain data, nested at most four deep). Headings are never
matched by language: the sections come back in the order they stand in the file.
Both carry a `card` (card.py), built from what they read and the triage and describe entries the server
hands in; `inbox_facts` is the same reading of one inbox item for the rows of the model, kept until the
item file, its events folder or an event file changes.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import threading
from dataclasses import replace
from pathlib import Path

import yaml

from . import card as cd
from . import origin as og
from .card_fields import validate_brief

try:
    from ..inbox_verbs import TERMINAL
except ImportError:                       # loaded with scripts/lib on the path, as returns.py is
    from inbox_verbs import TERMINAL  # type: ignore[no-redef]

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}\Z")
INBOX_ID_RE = re.compile(r"^[0-9]{8}-[0-9]{4}-[a-z0-9][a-z0-9-]{0,119}\Z")
LOG_ROW_RE = re.compile(r"^\| \d{4}-\d{2}-\d{2} \d{2}:\d{2} \|")
SECTION_MAX = 6000
TOTAL_MAX = 80 * 1024
LOG_ROWS = 15
DETAIL_MAX = 8000
EVENTS_MAX = 50
RELATED_MAX = 20
FRONT_KEYS = ("type", "status", "priority", "created", "last_updated", "headline", "origin", "blocked_by", "next")
ACTIVE = ("open", "approved", "waiting")
FILE_SUFFIXES = (".md", ".yaml", ".yml")
FILE_SKIP_DIRS = ("video", "deliverables", "node_modules")
FILES_MAX = 60
FILE_TEXT_MAX = 40000
FILE_DEPTH = 8
# one part of a file's path inside its folder: no slash, backslash or control character, never a leading dot
_FILE_PART = r"(?!\.)[^/\\\x00-\x1f\x7f]+"
FILE_RE = re.compile(rf"^{_FILE_PART}(?:/{_FILE_PART}){{0,{FILE_DEPTH - 1}}}\Z")


def _scalar(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _text(value):
    """A front matter value as the card reads it: a date as its ISO text, a text as it is, anything else None"""
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    return value if isinstance(value, (str, int, float)) and not isinstance(value, bool) else None


def _heading(body: str) -> str | None:
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip() or None
    return None


def _inside(path: Path, base: Path) -> bool:
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except (ValueError, OSError):
        return False


def _plain(value, depth: int = 0):
    """A probe as plain data for the page: scalars, lists and mappings, at most four levels deep"""
    if depth > 4:
        return None
    if isinstance(value, dict):
        return {str(k): _plain(v, depth + 1) for k, v in list(value.items())[:20]}
    if isinstance(value, list):
        return [_plain(v, depth + 1) for v in value[:20]]
    return _scalar(value)


def split_front(text: str) -> tuple[dict, str]:
    lines = text.splitlines(keepends=True)
    # The first `---` opens the front matter. Real STATUS.md files start with a
    # `# yaml-language-server: $schema=...` comment line, so leading comment and
    # blank lines are skipped; any other leading text means there is none.
    start = 0
    while start < len(lines) and lines[start].strip() != "---":
        if lines[start].strip() and not lines[start].lstrip().startswith("#"):
            return {}, text
        start += 1
    if start >= len(lines):
        return {}, text
    for i in range(start + 1, len(lines)):
        if lines[i].strip() == "---":
            try:
                front = yaml.safe_load("".join(lines[start + 1:i]))
            except yaml.YAMLError:
                front = None
            return (front if isinstance(front, dict) else {}), "".join(lines[i + 1:])
    return {}, text


def sections_of(body: str) -> list[dict]:
    out: list[dict] = []
    current: dict | None = None
    buf: list[str] = []
    for line in body.splitlines():
        if line.startswith("## "):
            if current is not None:
                current["text"] = "\n".join(buf).strip("\n")
                out.append(current)
            current, buf = {"heading": line[3:].strip()}, []
        elif current is not None:
            buf.append(line)
    if current is not None:
        current["text"] = "\n".join(buf).strip("\n")
        out.append(current)
    for s in out:
        s["truncated"] = len(s["text"]) > SECTION_MAX
        s["text"] = s["text"][:SECTION_MAX]
    return out


def log_rows(root: Path, slug: str) -> list[dict]:
    path = Path(root) / "work" / "log.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    rows = []
    for line in text.splitlines():
        if not LOG_ROW_RE.match(line):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4:
            continue
        at, glyph, context, what = cells[0], cells[1], cells[2], " | ".join(cells[3:])
        if context == slug or slug in what:
            rows.append({"at": at, "glyph": glyph, "context": context, "text": what})
    return rows[-LOG_ROWS:]


def folder_files(folder: Path) -> list[dict]:
    """The files of a task's folder besides its STATUS.md: {path (inside the folder), size}, by path. The walk
    never enters a hidden, skipped or linked folder, nor one deeper than FILE_DEPTH; every path matches FILE_RE."""
    found = []
    try:
        base = folder.resolve()
    except OSError:
        return []
    for top, dirs, files in os.walk(folder, followlinks=False):
        rel_top = Path(top).relative_to(folder)
        depth = len(rel_top.parts)
        dirs[:] = [] if depth >= FILE_DEPTH - 1 else sorted(
            d for d in dirs if not d.startswith(".") and d not in FILE_SKIP_DIRS and not (Path(top) / d).is_symlink())
        for name in files:
            rel = (rel_top / name).as_posix()
            if Path(name).suffix.lower() not in FILE_SUFFIXES or rel == "STATUS.md" or not FILE_RE.match(rel):
                continue
            path = Path(top) / name
            try:
                if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(base):
                    continue
                found.append({"path": rel, "size": path.stat().st_size})
            except OSError:
                continue
    found.sort(key=lambda f: f["path"].split("/"))
    return found[:FILES_MAX]


def _place(root: Path, slug: str, folder: str | None) -> tuple[str, Path] | None:
    """(kind, STATUS.md) of a slug: the open one first, then a stream, then the newest closed one; `folder`
    picks exactly that one of these places"""
    done = root / "work" / "done"
    places = [("task", root / "work" / "tasks"), ("stream", root / "work" / "streams")]
    if done.is_dir():
        places += [("done", month) for month in sorted(done.iterdir(), reverse=True) if month.is_dir()]
    for kind, base in places:
        path = base / slug / "STATUS.md"
        if folder is not None and (base / slug).relative_to(root).as_posix() != folder:
            continue
        if path.is_file() and _inside(path, root / "work"):
            return kind, path
    return None


def task_file(root: Path, slug: str, rel: str, folder: str | None = None) -> dict | None:
    """One of the files task_detail lists for a slug (never another), its text cut to FILE_TEXT_MAX"""
    if not isinstance(slug, str) or not SLUG_RE.match(slug) or not isinstance(rel, str):
        return None
    root = Path(root)
    found = _place(root, slug, folder)
    if found is None:
        return None
    if rel not in {f["path"] for f in folder_files(found[1].parent)}:
        return None
    try:
        with (found[1].parent / rel).open(encoding="utf-8", errors="replace") as fh:
            text = fh.read(FILE_TEXT_MAX + 1)    # never more than the cut and one character to tell it was cut
    except OSError:
        return None
    return {"ok": True, "slug": slug, "file": rel, "text": text[:FILE_TEXT_MAX], "cut": len(text) > FILE_TEXT_MAX}


def task_detail(root: Path, slug: str, listing: list | None = None, folder: str | None = None,
                origin_map: tuple = (), ctx: cd.Ctx | None = None) -> dict | None:
    """The file of a slug, the open one first; `folder` (`work/done/<month>/<slug>`) picks one of its places,
    compared with the places as they are, so a folder that is none of them is never read."""
    if not isinstance(slug, str) or not SLUG_RE.match(slug):
        return None
    root = Path(root)
    found = _place(root, slug, folder)
    if found is None:
        return None
    kind, path = found
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    front, body = split_front(text)
    nxt = front.get("next")
    # what the card reads (card.task_card): the next step with who and by when, the checklist, the brief
    facts = {"title": _heading(body), "status": _text(front.get("status")), "priority": _text(front.get("priority")),
             "blocked_by": _text(front.get("blocked_by")), "updated": _text(front.get("last_updated")),
             "area": _text(front.get("area")), "headline": _text(front.get("headline")),
             "brief": _plain(front["brief"]) if isinstance(front.get("brief"), dict) else None,
             "next": _text(nxt.get("what") if isinstance(nxt, dict) else nxt),
             "next_who": _text(nxt.get("who")) if isinstance(nxt, dict) else None,
             "next_due": _text(nxt.get("due")) if isinstance(nxt, dict) else None,
             "progress": cd.progress(text), "placeholder": cd.placeholder_steps(text)}
    if isinstance(nxt, dict):     # `next: {what, who}` reads as its words
        front = {**front, "next": nxt.get("what")}
    related = front.get("related") if isinstance(front.get("related"), list) else []
    known = og.known_from_root(root, origin_map)
    # the four kinds the page names (origin.WORK_KINDS); `kind` keeps the folder words the files view reads
    work_kind = kind if kind in ("task", "stream") else "done_stream" if front.get("was_stream") is True else "done_task"
    origin = og.classify_row({"key": f"task:{slug}", "task": slug, "origin_raw": _scalar(front.get("origin"))
                              if isinstance(front.get("origin"), str) else None}, known)
    result = {"ok": True, "slug": slug, "kind": kind, "work_kind": work_kind, "origin": origin, "path": path.resolve().relative_to(root.resolve()).as_posix(),
              "front": {k: _scalar(front.get(k)) for k in FRONT_KEYS}, "sections": sections_of(body),
              # the brief block as a mapping, never flattened through _scalar (card_fields.py names its shape)
              "brief": _plain(front["brief"]) if isinstance(front.get("brief"), dict) else None,
              # the paths STATUS.md names as related, as written: the files view lists them as references
              "related": [str(x)[:300] for x in related if isinstance(x, (str, int, float))][:RELATED_MAX],
              "log": log_rows(root, slug),
              "files": folder_files(path.parent),
              "inbox": [{"id": e.get("id"), "summary": _scalar(e.get("summary")), "state": e.get("state"),
                         "urgency": _scalar(e.get("urgency")), "gate": _scalar(e.get("gate")),
                         "from": _scalar(e.get("from")), "kind": _scalar(e.get("kind")),
                         "origin": og.classify_row({"inbox_id": e.get("id"), "inbox_key": _scalar(e.get("key")),
                                                    "origin_raw": _scalar(e.get("from")), "sources": ["inbox"]}, known)}
                        for e in listing or [] if isinstance(e, dict) and e.get("task") == slug
                        and e.get("state") in ACTIVE and isinstance(e.get("id"), str) and INBOX_ID_RE.match(e["id"])][:20]}
    # the one card of the task (card.py), read before any section is dropped for size
    result["card"] = cd.card_of({**result, "facts": facts}, _with_work(ctx, known))
    # total response max 80 KB: drop sections from the end, marking the last kept one truncated
    while len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > TOTAL_MAX and result["sections"]:
        result["sections"].pop()
        if result["sections"]:
            result["sections"][-1]["truncated"] = True
    return result


def inbox_detail(root: Path, item_id: str, listing: list | None, origin_map: tuple = (),
                 ctx: cd.Ctx | None = None) -> dict | None:
    if not isinstance(item_id, str) or not INBOX_ID_RE.match(item_id):
        return None
    base = Path(root) / "work" / "inbox"
    folder = base / item_id
    item_path = folder / "item.yaml"
    if not item_path.is_file() or not _inside(item_path, base):
        return None
    try:
        item = yaml.safe_load(item_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        item = None
    item = item if isinstance(item, dict) else {}
    events = []
    briefs = []
    events_dir = folder / "events"
    if events_dir.is_dir() and _inside(events_dir, base):
        for path in sorted(events_dir.glob("*.yaml")):
            try:
                ev = yaml.safe_load(path.read_text(encoding="utf-8"))
            except (OSError, yaml.YAMLError):
                continue
            if not isinstance(ev, dict):
                continue
            if ev.get("verb") == "describe":
                briefs.append(ev.get("brief"))
            entry = {"verb": _scalar(ev.get("verb")), "by": _scalar(ev.get("by")), "at": _scalar(ev.get("at"))}
            for extra in ("until", "note", "text"):   # text: what a tab noted or closed with
                if extra in ev:
                    entry[extra] = _scalar(ev.get(extra))
            if entry["verb"] == "area" and ev.get("value"):
                # the area it was given, and the router's reason when the router gave it
                why = _scalar(ev.get("why"))
                entry["text"] = f"{_scalar(ev.get('value'))} ({why})" if why else _scalar(ev.get("value"))
            events.append(entry)
    state_at = _state_at(events)
    events = events[-EVENTS_MAX:]
    state = None
    for entry in listing or []:
        if isinstance(entry, dict) and entry.get("id") == item_id:
            state = entry.get("state")
            break
    action = item.get("action")
    argv = action.get("argv") if isinstance(action, dict) else None
    action_display = " ".join(str(a) for a in argv) if isinstance(argv, list) and argv else None
    detail = _scalar(item.get("detail"))
    cut = isinstance(detail, str) and len(detail) > DETAIL_MAX
    result = {"ok": True, "id": item_id, "item": {
        "summary": _scalar(item.get("summary")), "detail": detail[:DETAIL_MAX] if cut else detail,
        "detail_truncated": cut, "kind": _scalar(item.get("kind")),
        "gate": _scalar(item.get("gate")), "urgency": _scalar(item.get("urgency")), "state": _scalar(state),
        "task": _scalar(item.get("task")), "due": _scalar(item.get("due")), "key": _scalar(item.get("key")),
        "from": _scalar(item.get("from")), "created": _scalar(item.get("created")), "action_display": action_display,
        "has_closes_when": item.get("closes_when") is not None, "closes_when": _plain(item.get("closes_when")),
        "closer": _scalar(item.get("closer"))}, "events": events,
        # who filed it, as the page names it (origin.py); the raw `from` stays in item.from
        "origin": og.classify_row({"inbox_id": item_id, "inbox_key": _scalar(item.get("key")),
                                   "origin_raw": _scalar(item.get("from")) if isinstance(item.get("from"), str) else None,
                                   "sources": ["inbox"]}, og.known_from_root(root, origin_map))}
    facts = _facts(item, briefs, events[-1]["at"] if events else None, state_at)
    result["card"] = cd.card_of({**result, "facts": facts}, _with_work(ctx, og.known_from_root(root, origin_map)))
    return result


def _with_work(ctx: cd.Ctx | None, known: og.Known) -> cd.Ctx:
    """The card context with the work kinds of this Bridge's tree under the ones it was handed"""
    ctx = ctx if isinstance(ctx, cd.Ctx) else cd.Ctx()
    return replace(ctx, work={**known.work, **ctx.work})


#: the verbs that change an inbox item's state (scripts/inbox.py Item.state and approval): the ends, a defer, a
#: yes, a failed run that takes the yes back, a reopen. A note, a seen, an area or a describe leave it as it was.
STATE_VERBS = frozenset(TERMINAL) | {"defer", "approve", "failed", "reopen"}


def _state_at(events) -> str | None:
    """When the item's state last changed: the time of its last state-changing event, None without one"""
    at = None
    for ev in events:
        if isinstance(ev, dict) and ev.get("verb") in STATE_VERBS and ev.get("at"):
            at = ev.get("at")
    return _text(at)


def _facts(item: dict, briefs: list, updated, state_at=None) -> dict:
    """What card.inbox_card reads of an item: its detail and how it closes, its brief (the latest
    `describe` event, None when that one took the brief back) through the gate it was written through, its
    last event (`updated`) and its last change of state (`state_at`)"""
    brief = validate_brief(briefs[-1])[0] if briefs and isinstance(briefs[-1], dict) else None
    return {"detail": _text(item.get("detail")), "kind": _text(item.get("kind")), "gate": _text(item.get("gate")),
            "due": _text(item.get("due")), "created": _text(item.get("created")), "task": _text(item.get("task")),
            "area": _text(item.get("area")), "closes_when": _plain(item.get("closes_when")),
            "closer": _text(item.get("closer")), "brief": brief, "updated": _text(updated),
            "state_at": _text(state_at)}


_FACTS: dict = {}
_FACTS_LOCK = threading.Lock()
FACTS_CAP = 1000


def inbox_facts(root: Path, item_id: str) -> dict | None:
    """card.inbox_card's facts of one item (see _facts), read from work/inbox/<id>/ and kept until the
    item file, the events folder or one of its event files changes (an event rewritten in place leaves the
    folder's time alone), so a rebuild of the model costs a stat per file. The dict is shared: callers copy
    it before they change it."""
    if not isinstance(item_id, str) or not INBOX_ID_RE.match(item_id):
        return None
    base = Path(root) / "work" / "inbox"
    folder = base / item_id
    item_path, events_dir = folder / "item.yaml", folder / "events"
    try:
        files = sorted(events_dir.glob("*.yaml")) if events_dir.is_dir() else []
        stamp = (item_path.stat().st_mtime_ns,
                 events_dir.stat().st_mtime_ns if events_dir.is_dir() else 0,
                 len(files), max((f.stat().st_mtime_ns for f in files), default=0))
    except OSError:
        return None
    key = (str(base), item_id)
    with _FACTS_LOCK:
        held = _FACTS.get(key)
        if held and held[0] == stamp:
            return held[1]
    if not _inside(item_path, base):
        return None
    try:
        item = yaml.safe_load(item_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        item = None
    item = item if isinstance(item, dict) else {}
    briefs, last, read = [], None, []
    if events_dir.is_dir() and _inside(events_dir, base):
        for path in files:
            try:
                ev = yaml.safe_load(path.read_text(encoding="utf-8"))
            except (OSError, yaml.YAMLError):
                continue
            if isinstance(ev, dict):
                last = ev.get("at") or last
                read.append(ev)
                if ev.get("verb") == "describe":
                    briefs.append(ev.get("brief"))
    facts = _facts(item, briefs, last, _state_at(read))
    with _FACTS_LOCK:
        if len(_FACTS) >= FACTS_CAP:
            _FACTS.clear()
        _FACTS[key] = (stamp, facts)
    return facts
