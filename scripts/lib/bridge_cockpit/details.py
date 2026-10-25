# SPDX-License-Identifier: MIT
"""Read-only readers for the detail endpoints: a task's STATUS.md and an inbox item.

/api/task reads work/tasks/<slug>/STATUS.md, else work/streams/<slug>/, else the newest
work/done/<month>/<slug>/ (the resolved path must stay inside work/): front matter, every `## ` section (body
cut to 6000 characters), and the last 15 rows of work/log.md that name the slug.
It also lists the open inbox items that name the slug as their task.
/api/inbox reads work/inbox/<id>/item.yaml and events/*.yaml (the last 50), with how the item
ends (`closer`, `closes_when` as plain data, nested at most four deep). Headings are never
matched by language: the sections come back in the order they stand in the file.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

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


def _scalar(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


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


def task_detail(root: Path, slug: str, listing: list | None = None) -> dict | None:
    if not isinstance(slug, str) or not SLUG_RE.match(slug):
        return None
    root = Path(root)
    # open first, then a stream, then a closed task (an inbox item can outlive it), newest month first
    done = root / "work" / "done"
    places = [("task", root / "work" / "tasks"), ("stream", root / "work" / "streams")]
    if done.is_dir():
        places += [("done", month) for month in sorted(done.iterdir(), reverse=True) if month.is_dir()]
    for kind, base in places:
        path = base / slug / "STATUS.md"
        if path.is_file() and _inside(path, root / "work"):
            break
    else:
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    front, body = split_front(text)
    nxt = front.get("next")
    if isinstance(nxt, dict):     # `next: {what, who}` reads as its words
        front = {**front, "next": nxt.get("what")}
    related = front.get("related") if isinstance(front.get("related"), list) else []
    result = {"ok": True, "slug": slug, "kind": kind, "path": path.resolve().relative_to(root.resolve()).as_posix(),
              "front": {k: _scalar(front.get(k)) for k in FRONT_KEYS}, "sections": sections_of(body),
              # the paths STATUS.md names as related, as written: the files view lists them as references
              "related": [str(x)[:300] for x in related if isinstance(x, (str, int, float))][:RELATED_MAX],
              "log": log_rows(root, slug),
              "inbox": [{"id": e.get("id"), "summary": _scalar(e.get("summary")), "state": e.get("state"),
                         "urgency": _scalar(e.get("urgency")), "gate": _scalar(e.get("gate"))}
                        for e in listing or [] if isinstance(e, dict) and e.get("task") == slug
                        and e.get("state") in ACTIVE and isinstance(e.get("id"), str) and INBOX_ID_RE.match(e["id"])][:20]}
    # total response max 80 KB: drop sections from the end, marking the last kept one truncated
    while len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > TOTAL_MAX and result["sections"]:
        result["sections"].pop()
        if result["sections"]:
            result["sections"][-1]["truncated"] = True
    return result


def inbox_detail(root: Path, item_id: str, listing: list | None) -> dict | None:
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
    events_dir = folder / "events"
    if events_dir.is_dir() and _inside(events_dir, base):
        for path in sorted(events_dir.glob("*.yaml")):
            try:
                ev = yaml.safe_load(path.read_text(encoding="utf-8"))
            except (OSError, yaml.YAMLError):
                continue
            if not isinstance(ev, dict):
                continue
            entry = {"verb": _scalar(ev.get("verb")), "by": _scalar(ev.get("by")), "at": _scalar(ev.get("at"))}
            for extra in ("until", "note", "text"):   # text: what a tab noted or closed with
                if extra in ev:
                    entry[extra] = _scalar(ev.get(extra))
            events.append(entry)
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
    return {"ok": True, "id": item_id, "item": {
        "summary": _scalar(item.get("summary")), "detail": detail[:DETAIL_MAX] if cut else detail,
        "detail_truncated": cut, "kind": _scalar(item.get("kind")),
        "gate": _scalar(item.get("gate")), "urgency": _scalar(item.get("urgency")), "state": _scalar(state),
        "task": _scalar(item.get("task")), "due": _scalar(item.get("due")), "key": _scalar(item.get("key")),
        "from": _scalar(item.get("from")), "created": _scalar(item.get("created")), "action_display": action_display,
        "has_closes_when": item.get("closes_when") is not None, "closes_when": _plain(item.get("closes_when")),
        "closer": _scalar(item.get("closer"))}, "events": events}
