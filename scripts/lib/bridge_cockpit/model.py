# SPDX-License-Identifier: MIT
"""Pure domain functions of the cockpit, originally ported from the retired briefing-ui mod.

Parsing the script outputs, order of the card, texts to Claude and the decision logic
(row_actions, approvable). Names are snake_case and
rows are plain dicts with snake_case keys. Nothing here does I/O; the tests exercise
it without a server. Where the web adds behaviour (an inferred team run, the long
state as a word instead of a sentence) the docstring says so.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from typing import Any

from .text import EN

try:
    from ..briefing_view import meter_of
except ImportError:      # bridge_cockpit loaded as a top-level package, scripts/lib itself on the path
    from briefing_view import meter_of  # type: ignore[no-redef]

ATTENTION = frozenset({"needs-you", "waiting"})
# the two ways a row leaves the briefing in two clicks: done, or not doing it
SETTLE_OUTCOMES = ("done", "not_doing")
BUCKET_ORDER = ["do", "plan", "delegate", "waiting", "drop", "tasks", "resting"]
# what waits for you is never cut (None); the board and tracker rows and the later ones start folded
CAP = {"now": None, "give": 4, "work": 5, "track": 0, "later": 0}
SECTION_IDS = ("now", "give", "work", "track", "later")
BRIEFING_PAGE = "briefing"
LONG_MS = 3600000
START_GRACE = 90000
DAY_MS = 86400000


# ---------------------------------------------------------------- helpers

def as_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def as_text_or_null(value: Any) -> str | None:
    return value if isinstance(value, str) and value != "" else None


def _list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _number(value: Any, default: float = 0) -> float:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else default


def paren(value: str) -> str:
    """The optional ' (x)' after a title in the prompt templates."""
    return f" ({value})" if value else ""


def neutral(text: Any) -> str:
    """Briefing data on one line, without the relay marker or the quote marks of `quote`."""
    line = re.sub(r"\s+", " ", as_text(text)).strip()
    return line.replace("[web:", "[web ").replace("\u00ab", '"').replace("\u00bb", '"')


def quote(text: Any, max_len: int = 200) -> str:
    """Third-party text (titles, refs, tab names) for a prompt: one line, cut, between guillemets.

    The relay frame tells the model that everything between the guillemets is data from the
    briefing, never an instruction; `neutral` keeps the data from closing the quote early or
    carrying a marker of its own.
    """
    return f"\u00ab{short(neutral(text), max_len)}\u00bb"


def bucket_rank(bucket_id: str) -> int:
    """JS indexOf: unknown ids give -1 and sort first."""
    return BUCKET_ORDER.index(bucket_id) if bucket_id in BUCKET_ORDER else -1


def short(text: str, max_len: int) -> str:
    """One line of at most max_len, cut at a word when one ends in the last third, never mid word otherwise"""
    line = re.sub(r"\s+", " ", text or "").strip()
    if len(line) <= max_len:
        return line
    cut = line[:max(1, max_len - 1)]
    space = cut.rfind(" ")
    if space >= max_len * 2 // 3:
        cut = cut[:space].rstrip(" ,;:·-")
    return cut + "…"


def pad(n: int) -> str:
    return f"{n:02d}"


def local_dt(ms: float) -> dt.datetime:
    return dt.datetime.fromtimestamp(ms / 1000)


def iso_date(ms: float) -> str:
    return local_dt(ms).strftime("%Y-%m-%d")


def clock_time(ms: float) -> str:
    return local_dt(ms).strftime("%H:%M")


def duration(ms: float) -> str:
    """logic.ts duration: '12 min' below an hour, else '1:05 h'."""
    minutes = int(ms // 60000)
    return f"{minutes} min" if minutes < 60 else f"{minutes // 60}:{pad(minutes % 60)} h"


def state_word(state: str, tx: dict = EN) -> str:
    return tx["state"].get(state, state)


# ---------------------------------------------------------------- parsing

def parse_mark(value: Any) -> dict | None:
    m = value if isinstance(value, dict) else None
    if not m or not isinstance(m.get("label"), str) or not m["label"]:
        return None
    return {"label": m["label"], "color": m["color"] if isinstance(m.get("color"), str) else None}


def parse_meter(value: Any) -> dict | None:
    """The optional gauge of a page row, checked again with the same rule that made it
    (briefing_view.meter_of): the view file is input."""
    return meter_of(value)


def parse_info(i: dict) -> dict:
    i = _dict(i)
    tone = i.get("tone") if i.get("tone") in ("bad", "warn", "dim") else None
    lines = [{"kind": as_text(l["kind"]), "text": as_text(l["text"])} for l in _list(i.get("lines"))
             if isinstance(l, dict) and isinstance(l.get("kind"), str) and isinstance(l.get("text"), str) and l["text"]]
    return {"title": as_text(i.get("title")), "detail": as_text(i.get("detail")), "when": as_text(i.get("when")),
            "tone": tone, "url": as_text_or_null(i.get("url")), "task": as_text_or_null(i.get("task")),
            "ask": i.get("ask") is True, "mark": parse_mark(i.get("mark")),
            "priority": as_text_or_null(i.get("priority")), "state": as_text_or_null(i.get("state")),
            "lines": lines, "meter": parse_meter(i.get("meter")),
            "group": as_text_or_null(i.get("group")), "icon": as_text_or_null(i.get("icon")),
            "tags": {k: v for k, v in _dict(i.get("tags")).items() if isinstance(k, str) and isinstance(v, str)} or None,
            "inbox": as_text_or_null(i.get("inbox")),
            "actions": [{"id": a["id"], "label": a["label"]} for a in _list(i.get("actions"))
                        if isinstance(a, dict) and isinstance(a.get("id"), str) and isinstance(a.get("label"), str)] or None,
            "row_id": as_text_or_null(i.get("row_id")),
            "flags": [f for f in _list(i.get("flags")) if isinstance(f, str) and len(f) <= 24][:12] or None,
            "who": as_text_or_null(i.get("who")),
            "gh": parse_gh(i.get("gh")),
            "cal": parse_cal(i.get("cal")),
            "due_at": as_text_or_null(i.get("due_at")),
            "id": as_text_or_null(i.get("id")), "actionable": i.get("actionable") is True,
            "at": as_text_or_null(i.get("at")),
            "account": parse_account(i.get("account"))}


def parse_cal(value: Any) -> dict | None:
    """An event's facts (briefing_view.calendar_facts), checked again: the view file is input."""
    if not isinstance(value, dict):
        return None
    return {"start": as_text_or_null(value.get("start")), "end": as_text_or_null(value.get("end")),
            "day": as_text_or_null(value.get("day")),
            "minutes": value.get("minutes") if isinstance(value.get("minutes"), int) else 0,
            "all_day": value.get("all_day") is True, "calendar": as_text_or_null(value.get("calendar")),
            "info": value.get("info") is True, "where": as_text_or_null(value.get("where")),
            "online": value.get("online") is True,
            "people": [x for x in _list(value.get("people")) if isinstance(x, str)][:20],
            "past": value.get("past") is True, "running": value.get("running") is True,
            "overlaps": [x for x in _list(value.get("overlaps")) if isinstance(x, str)][:3]}


def parse_cal_figures(value: Any) -> dict | None:
    """The figures above an agenda (briefing_view.calendar_figures): counts, the next event, the free block."""
    if not isinstance(value, dict):
        return None
    num = lambda k: value.get(k) if isinstance(value.get(k), int) else 0   # noqa: E731
    nxt = value.get("next") if isinstance(value.get("next"), dict) else None
    free = value.get("free_today") if isinstance(value.get("free_today"), dict) else None
    return {**{k: num(k) for k in ("today", "busy_today", "tomorrow", "week", "overlaps", "info_week")},
            "day_start": value.get("day_start") if isinstance(value.get("day_start"), int) else 8,
            "day_end": value.get("day_end") if isinstance(value.get("day_end"), int) else 20,
            "next": {"start": as_text_or_null(nxt.get("start")), "title": as_text(nxt.get("title"))} if nxt else None,
            "free_today": {"minutes": int(_number(free.get("minutes"))), "from": as_text_or_null(free.get("from"))}
            if free else None}


def parse_gh(value: Any) -> dict | None:
    """A GitHub row's facts (briefing_view.github_facts), checked again: the view file is input."""
    if not isinstance(value, dict):
        return None
    texts = lambda v, n: [x for x in _list(v) if isinstance(x, str)][:n]   # noqa: E731
    return {"title": as_text(value.get("title")), "repo": as_text_or_null(value.get("repo")),
            "number": value.get("number") if isinstance(value.get("number"), int) else None,
            "type": value["type"] if value.get("type") in ("pr", "draft") else "issue", "state": as_text_or_null(value.get("state")),
            "status": as_text_or_null(value.get("status")), "priority": as_text_or_null(value.get("priority")),
            "labels": texts(value.get("labels"), 4),
            "people": texts(value.get("people"), 3),
            "prs": [{"n": p["n"], "draft": p.get("draft") is True} for p in _list(value.get("prs"))
                    if isinstance(p, dict) and isinstance(p.get("n"), int)][:3],
            "task": as_text_or_null(value.get("task")), "stream": value.get("stream") is True,
            "changed": as_text_or_null(value.get("changed")),
            "quiet": value.get("quiet") if isinstance(value.get("quiet"), int) else None,
            "note": as_text_or_null(value.get("note"))}


def parse_boards(value: Any) -> list[dict] | None:
    """A board summary of a GitHub section: name, slug, open cards per state, the person's switch and default."""
    out = []
    for b in _list(value)[:40]:
        if not isinstance(b, dict) or not isinstance(b.get("name"), str):
            continue
        counts = b.get("counts") if isinstance(b.get("counts"), dict) else {}
        out.append({"name": b["name"], "slug": as_text_or_null(b.get("slug")), "org": as_text_or_null(b.get("org")),
                    "number": b.get("number") if isinstance(b.get("number"), int) else None,
                    "open": b.get("open") if isinstance(b.get("open"), int) else None,
                    "counts": {k: v for k, v in counts.items() if isinstance(k, str) and isinstance(v, int)},
                    "capped": b.get("capped") if isinstance(b.get("capped"), int) else None,
                    "mode": b.get("mode") if b.get("mode") in ("off", "mine", "all") else None,
                    "default": b.get("default") if b.get("default") in ("off", "mine", "all") else None})
    return out or None


def parse_account(a: Any) -> dict | None:
    """An account row's {id, status}: what the dashboard's status menu acts on."""
    if not isinstance(a, dict) or not isinstance(a.get("id"), str) or not a["id"]:
        return None
    return {"id": a["id"], "status": a["status"] if isinstance(a.get("status"), str) else None}


def _base_row(**extra) -> dict:
    row = {"bucket": "do", "title": "", "why": [], "sources": [], "inbox_id": None, "gate": None, "task": None,
           "ref": None, "url": None, "priority": None, "urgency": None, "area": None, "area_names": [],
           "task_type": None, "has_action": False, "inbox_state": None, "inbox_key": None, "mark": None,
           "due": None, "is_new": False, "is_changed": False,
           # a task row's state (doing, review) and its next step, derived (task_next), never stored
           "status": None, "next": None, "created": None}
    row.update(extra)
    return row


def task_row(slug: str, title: str) -> dict:
    row = _base_row(title=title, task=slug)
    row["key"] = f"task:{slug}"
    return row


def task_row_for(slug: str, title: str, tasks: list[dict], tx: dict = EN) -> dict:
    t = next((x for x in tasks if x["slug"] == slug), None)
    if t is None:
        return task_row(slug, title)
    why = [tx["blocked"].format(by=t["blocked_by"])] if t["blocked_by"] else (
        [tx["quiet_for"].format(days=as_text(t["age"]))] if t["stale"] else [])
    row = task_row(slug, title or t.get("title") or t["label"])
    row.update(why=why, sources=["tasks"], priority=t["priority"], area=t["area"], area_names=list(t["area_names"]),
               task_type=t["type"])
    return row


# the live cards a page may place after one of its sections (`cards:` in workflow/briefings/*.yaml)
CARD_IDS = ("costs", "usage", "noise")


def parse_cards(value) -> list[dict] | None:
    """A page's `cards:` as [{id, after}], in the listed order: an unknown id or a broken entry is dropped,
    `after` is a section id or None (the end of the page). None when the page names no list at all."""
    if not isinstance(value, list):
        return None
    return [{"id": c["id"], "after": c["after"] if isinstance(c.get("after"), str) and c["after"] else None}
            for c in value if isinstance(c, dict) and c.get("id") in CARD_IDS]


def parse_pages(data: dict, tx: dict = EN) -> list[dict]:
    pages = []
    for p in _list(_dict(data).get("pages")):
        p = _dict(p)
        sections = []
        for x in _list(p.get("sections")):
            x = _dict(x)
            items = [parse_info(i) for i in _list(x.get("items"))]
            sections.append({
                "id": as_text(x.get("id")), "kind": as_text(x.get("kind")), "title": as_text(x.get("title")),
                "status": as_text(x.get("status")), "reason": as_text(x.get("reason")), "alarm": x.get("alarm") is True,
                "left_out": x.get("left_out") is True,
                "empty": as_text(x.get("empty")) or tx["empty"], "items": items, "count": len(items),
                # total is not in the mod's InfoPage: the web keeps it for "more n"
                "total": int(_number(x.get("total"), len(items))),
                "weight": _number(x.get("weight")), "bad": _number(x.get("bad")),
                "as_of": as_text_or_null(x.get("as_of")),
                "view": x.get("view") if x.get("view") in ("tiles", "mosaic", "groups", "board", "agenda") else None,
                "cal_figures": parse_cal_figures(x.get("cal_figures")),
                "hide_empty": x.get("hide_empty") is True,
                "stale": as_text_or_null(x.get("stale")),
                "boards": parse_boards(x.get("boards")),
                "metrics": [{"id": as_text(g.get("id")), "n": int(_number(g.get("n"))),
                             "days": g.get("days") if isinstance(g.get("days"), int) else None}
                            for g in _list(x.get("metrics")) if isinstance(g, dict) and isinstance(g.get("id"), str)][:12] or None,
            })
        page = {"id": as_text(p.get("id")), "title": as_text(p.get("title")), "sections": sections,
                "group": p.get("group") if p.get("group") in ("more", "work", "day") else "main", "overview": p.get("overview") is True,
                "cards": parse_cards(p.get("cards")),
                # the order by Jev: the words stay on the server (jev.rank), the page only learns there is one
                "jev": ({k: [as_text(x) for x in v] if isinstance(v := p["jev"].get(k), list) else []
                         for k in ("skip_sections", "private")} if isinstance(p.get("jev"), dict) else None)}
        if page["id"] and page["id"] != BRIEFING_PAGE and sections:
            pages.append(page)
    return pages


def page_badge(page: dict) -> dict:
    bad = sum(s["bad"] for s in page["sections"])
    if bad > 0:
        return {"kind": "bad", "n": int(bad)}
    weight = sum(s["weight"] for s in page["sections"])
    is_warn = any(s["weight"] > 0 and any(it["tone"] == "warn" for it in s["items"]) for s in page["sections"])
    if weight > 0:
        return {"kind": "count", "n": int(weight), "warn": is_warn}
    if all(s["status"] == "ok" for s in page["sections"]):
        return {"kind": "ok"}
    return {"kind": "none"}


def row_key(row: dict) -> str:
    if row.get("inbox_id"):
        return f"inbox:{row['inbox_id']}"
    if row.get("task"):
        return f"task:{row['task']}"
    if row.get("ref"):
        return f"ref:{row['ref']}"
    return f"title:{row.get('title', '')[:60]}"


def item_key(page_id: str, section_id: str, info: dict) -> str:
    """The key of a page item: its source id, else a hash of its title (a row without an id still has one)"""
    rid = info.get("id") or "h" + hashlib.sha1(as_text(info.get("title")).encode("utf-8")).hexdigest()[:10]
    return f"item:{page_id}/{section_id}/{rid}"


def launch_item(row: dict) -> str | None:
    return row.get("inbox_id") or row.get("task") or None


def github_url(ref: str | None) -> str | None:
    m = re.fullmatch(r"([\w.-]+/[\w.-]+)#(\d+)", ref) if ref else None
    return f"https://github.com/{m.group(1)}/issues/{m.group(2)}" if m else None


def row_url(row: dict) -> str | None:
    url = row.get("url")
    if url and re.match(r"https?://", url):
        return url
    return github_url(row.get("ref"))


def parse_view(raw: Any, is_full: bool, now: float, tx: dict = EN) -> dict:
    data = _dict(raw)
    v = _dict(data.get("view"))
    buckets = []
    seen_keys: set[str] = set()
    for b in _list(v.get("buckets")):
        b = _dict(b)
        rows = []
        for i in _list(b.get("items")):
            i = _dict(i)
            base = _base_row(
                bucket=as_text(b.get("id")), title=as_text(i.get("title")),
                why=[w for w in (as_text(x) for x in _list(i.get("why"))) if w],
                sources=[as_text(x) for x in _list(i.get("sources"))],
                inbox_id=as_text_or_null(i.get("inbox_id")), gate=as_text_or_null(i.get("gate")),
                task=as_text_or_null(i.get("task")), ref=as_text_or_null(i.get("ref")),
                url=as_text_or_null(i.get("url")), priority=as_text_or_null(i.get("priority")),
                urgency=as_text_or_null(i.get("urgency")), has_action=i.get("has_action") is True,
                inbox_state=as_text_or_null(i.get("inbox_state")), inbox_key=as_text_or_null(i.get("inbox_key")),
                mark=parse_mark(i.get("mark")),
                # web only: shown by the page, not used for any decision
                due=as_text_or_null(i.get("due")), is_new=i.get("new") is True, is_changed=i.get("changed") is True,
                # when an inbox item was filed: the age of a next step taken from it
                created=as_text_or_null(i.get("created")),
            )
            # Same key twice (same number from two trackers): the second gets the block added.
            key = row_key(base)
            base["key"] = f"{key}@{base['bucket']}:{len(rows)}" if key in seen_keys else key
            rows.append(base)
            seen_keys.add(key)
        buckets.append({"id": as_text(b.get("id")), "title": as_text(b.get("title")), "rows": rows})
    buckets.sort(key=lambda b: bucket_rank(b["id"]))
    agenda = [{"when": as_text(a.get("when")), "title": as_text(a.get("title"))}
              for a in (_dict(x) for x in _list(v.get("agenda"))) if not a.get("info")]
    # probe: a report_ok section, whose rows are findings; state: error or skipped when the source did not run
    status = [{"title": as_text(s.get("title")), "count": _number(s.get("count")), "probe": s.get("health") is True,
               "state": s.get("status") if s.get("status") in ("error", "skipped") else "ok",
               "reason": as_text_or_null(s.get("reason")) or None,
               # left out of this pass on purpose (comes with the full one), unlike a source that cannot run here
               "left_out": s.get("left_out") is True}
              for s in (_dict(x) for x in _list(v.get("status")))]
    headline = as_text(v.get("headline"))
    return {
        "profile": as_text(data.get("profile")),
        "title": as_text(data.get("title")),
        "headline": headline,
        # the headline after its own count: a dashboard says the count it shows on the Briefing tab instead
        "headline_rest": headline.split(" · ", 1)[1] if " · " in headline else "",
        "since": as_text_or_null(v.get("since")),
        "extras": {"clear": [as_text(x) for x in _list(v.get("clear"))],
                   "hygiene": [as_text(x) for x in _list(v.get("hygiene"))],
                   "workplace": as_text_or_null(v.get("workplace"))},
        "collected_at": clock_time(now),
        "collected_ms": int(now),
        "is_full": is_full,
        "full_ms": int(now) if is_full else 0,
        "skipped": [as_text(x.get("id")) for x in (_dict(s) for s in _list(data.get("sections")))
                    if x.get("status") == "skipped"],
        "buckets": buckets,
        "agenda": agenda,
        "status": status,
        "pages": parse_pages(data, tx),
    }


def _json_list(out: Any) -> list:
    data = json.loads(out) if isinstance(out, (str, bytes)) else out
    if not isinstance(data, list):
        raise ValueError("expected a JSON list")
    return data


def parse_tasks(out: Any) -> list[dict]:
    result = []
    for t in (_dict(x) for x in _json_list(out)):
        result.append({
            "slug": as_text(t.get("slug")), "label": as_text(t.get("label")), "area": as_text(t.get("area")),
            # the full heading; the label is the short tab name, cut with an ellipsis
            "title": as_text(t.get("title")) or as_text(t.get("label")),
            "area_names": [as_text(t.get("area"))] + [as_text(a) for a in _list(t.get("area_aliases"))],
            "priority": as_text_or_null(t.get("priority")), "blocked_by": as_text_or_null(t.get("blocked_by")),
            "stale": t.get("stale") is True, "age": _number(t.get("age")), "type": as_text_or_null(t.get("type")),
            # tasks or streams (workplace.py); a stream never closes
            "kind": t.get("kind") if t.get("kind") in ("tasks", "streams") else None,
            # doing or review, what STATUS.md names as next, and the day it last changed (workplace.py tasks)
            "status": as_text_or_null(t.get("status")), "next": as_text_or_null(t.get("next")),
            "updated": as_text_or_null(t.get("updated")),
        })
    return result


def parse_teams(out: Any) -> list[dict]:
    result = []
    for t in (_dict(x) for x in _json_list(out)):
        roles = []
        for r in (_dict(x) for x in _list(t.get("roles"))):
            # TS maps context to go; with --team workplace.py ignores the mode, so keeping it is harmless.
            mode = r.get("mode") if r.get("mode") in ("report", "context") else "go"
            roles.append({"id": as_text(r.get("id")), "name": as_text(r.get("name")), "mode": mode})
        result.append({"id": as_text(t.get("id")), "label": as_text(t.get("label")),
                       "for_types": [as_text(x) for x in _list(t.get("for_types"))], "roles": roles})
    return result


def task_next(task: dict, inbox_rows: list[dict]) -> dict | None:
    """The next step of a task, derived and never stored: its oldest open inbox item, else the `next:` of its
    STATUS.md; each with where it comes from and since when ({what, from, since, key}), None when nothing names
    one. An item put off is not open (the page leaves it out the same way, logic.js dossierParts); one that waits
    for a yes still is. A tab that asks and a result that waits are live: the page puts them in front itself
    (logic.js queueOf)."""
    mine = [r for r in inbox_rows if r.get("inbox_id") and r.get("task") == task["slug"]
            and r.get("inbox_state") != "deferred"]
    if mine:
        first = min(mine, key=lambda r: (r.get("created") or "9999", r.get("inbox_id") or ""))
        return {"what": first["title"], "from": "inbox", "since": first.get("created"), "key": first.get("key")}
    if task.get("next"):
        return {"what": task["next"], "from": "status", "since": task.get("updated"), "key": None}
    return None


def with_tasks(view: dict, tasks: list[dict], tx: dict = EN) -> dict:
    by_slug = {t["slug"]: t for t in tasks}
    inbox_rows = [r for b in view["buckets"] for r in b["rows"] if r.get("inbox_id") and r.get("task")]
    seen: set[str] = set()
    inbox_count: dict[str, int] = {}
    buckets = []
    for b in view["buckets"]:
        if b["id"] in ("tasks", "resting"):
            continue
        rows = []
        for r in b["rows"]:
            t = by_slug.get(r["task"]) if r.get("task") else None
            if not t:
                rows.append(r)
                continue
            # An inbox entry is a part of its task, never the task itself: the task keeps its own row.
            if r.get("inbox_id"):
                inbox_count[t["slug"]] = inbox_count.get(t["slug"], 0) + 1
            else:
                seen.add(t["slug"])
            # An inbox entry shows the area of its task, but not its priority.
            priority = r["priority"] if r.get("inbox_id") else (r["priority"] if r["priority"] is not None else t["priority"])
            mine = {} if r.get("inbox_id") else {"status": t.get("status"), "next": task_next(t, inbox_rows)}
            rows.append({**r, "area": t["area"], "area_names": list(t["area_names"]), "priority": priority,
                         "task_type": t["type"], **mine})
        buckets.append({**b, "rows": rows})

    def to_row(t: dict, bucket: str) -> dict:
        why = [tx["blocked"].format(by=t["blocked_by"])] if t["blocked_by"] else (
            [tx["quiet_for"].format(days=as_text(t["age"]))] if t["stale"] else [])
        if inbox_count.get(t["slug"]):
            why.append(tx["inbox_open"].format(n=inbox_count[t["slug"]]))
        base = _base_row(bucket=bucket, title=t.get("title") or t["label"], why=why, sources=["tasks"], task=t["slug"],
                         priority=t["priority"], area=t["area"], area_names=list(t["area_names"]), task_type=t["type"],
                         status=t.get("status"), next=task_next(t, inbox_rows))
        base["key"] = row_key(base)
        return base

    rest = [t for t in tasks if t["slug"] not in seen]
    active = [to_row(t, "tasks") for t in rest if not t["blocked_by"] and not t["stale"]]
    resting = [to_row(t, "resting") for t in rest if t["blocked_by"] or t["stale"]]
    if active:
        buckets.append({"id": "tasks", "title": tx["bucket_tasks"], "rows": active})
    if resting:
        buckets.append({"id": "resting", "title": tx["bucket_resting"], "rows": resting})
    return {**view, "buckets": buckets}


# ---------------------------------------------------------------- order of the card

def prio_rank(row: dict) -> int:
    m = re.fullmatch(r"P(\d)", row.get("priority") or "")
    return int(m.group(1)) if m else 4


def urgency_rank(row: dict) -> int:
    return 0 if row.get("urgency") == "now" else 1 if row.get("urgency") == "today" else 2


def classify(row: dict) -> str:
    if row.get("urgency") in ("now", "today") or row.get("bucket") == "do":
        return "now"
    if row.get("bucket") in ("drop", "waiting", "resting"):
        return "later"
    if row.get("inbox_id"):
        return "give" if row.get("gate") in ("your-yes", "free") else "later"
    if row.get("task"):
        return "work"
    # a board item, an application, an issue: it comes from a tracker, not from the Bridge's own tasks
    if row.get("ref"):
        return "track"
    return "later"


def all_rows(view: dict | None) -> list[dict]:
    return [r for b in view["buckets"] for r in b["rows"]] if view else []


def filed_by(tab: dict, view: dict | None) -> dict | None:
    if not tab.get("slug") or not view:
        return None
    prefix = f"tab-{tab['slug']}-"
    # The tab files with --task <slug>; only without a task does the key count.
    for r in all_rows(view):
        if r.get("inbox_id") is not None and (r.get("inbox_key") or "").startswith(prefix) \
                and (r.get("task") is None or r.get("task") == tab["slug"]):
            return r
    return None


def is_waiting(tab: dict, view: dict | None) -> bool:
    if tab.get("state") == "needs-you":
        return True
    return tab.get("state") == "waiting" and filed_by(tab, view) is None


def is_live(tab: dict) -> bool:
    return tab.get("state") != "shell"


def tab_for(row: dict, tabs: list[dict]) -> dict | None:
    mine = [t for t in tabs if (row.get("task") is not None and t.get("slug") == row.get("task"))
            or (row.get("inbox_id") is not None and t.get("item") == row.get("inbox_id"))]
    for t in mine:
        if t.get("state") in ATTENTION:
            return t
    for t in reversed(mine):
        if is_live(t):
            return t
    return mine[-1] if mine else None


def long_state(tab: dict, seen: dict, now: float) -> str | None:
    """logic.ts longText as a word: 'waiting' or 'running'; the frontend writes the sentence."""
    s = seen.get(tab.get("ref"))
    if not s or s.get("state") != tab.get("state") or now - s.get("since_ms", now) < LONG_MS:
        return None
    if tab.get("state") in ATTENTION:
        return "waiting"
    return "running" if tab.get("state") == "working" else None


def team_state(row: dict, runs: dict, teams: list[dict], tabs: list[dict], now: float) -> dict | None:
    task = row.get("task")
    run = runs.get(task) if task else None
    if task and run is None:
        # web only: a run started elsewhere (the mod, another page) is inferred from the live tabs.
        live = [t for t in tabs if t.get("slug") == task and t.get("team") and is_live(t)]
        if live:
            team_id = live[0]["team"]
            run = {"team": team_id, "roles": [t["role"] for t in live if t.get("team") == team_id and t.get("role")],
                   "at": 0}
    team = next((t for t in teams if run and t["id"] == run.get("team")), None)
    if not run or not team:
        return None
    started = len([r for r in team["roles"] if r["id"] in run.get("roles", [])])
    nxt = team["roles"][started] if started < len(team["roles"]) else None
    last = team["roles"][started - 1] if started > 0 else None
    last_tab = next((t for t in tabs if t.get("slug") == task and t.get("role") == last["id"]), None) if last else None
    is_ready = started == 0 or (last_tab.get("state") in ATTENTION if last_tab else now - run.get("at", 0) > START_GRACE)
    return {"team": team, "started": started, "next": nxt, "is_ready": is_ready,
            "waiting_for": None if is_ready or not last else last["name"]}


def layout(view: dict | None, done: list | set, hide: dict, today: str, tabs: list[dict],
           open_section: str | None = None, show_all: bool = False) -> dict:
    groups: dict[str, list] = {s: [] for s in SECTION_IDS}
    hidden_rows = []
    for row in all_rows(view):
        if row["key"] in done:
            continue
        if (hide.get(row["key"]) or "") > today:
            hidden_rows.append(row)
        else:
            groups[classify(row)].append(row)
    sections = []
    for sid in SECTION_IDS:
        rows = sorted(groups[sid], key=lambda r: (urgency_rank(r), prio_rank(r)))
        if show_all or open_section == sid:
            sections.append({"id": sid, "all": rows, "shown": rows})
            continue
        # Tasks compact: only P0 to P2 and what already has a tab
        pool = [r for r in rows if prio_rank(r) <= 2 or tab_for(r, tabs)] if sid == "work" else rows
        sections.append({"id": sid, "all": rows, "shown": pool if CAP[sid] is None else pool[:CAP[sid]]})
    numbered = [r for s in sections for r in s["all"]]
    return {"sections": sections, "hidden_rows": hidden_rows, "numbered": numbered,
            "numbers": {r["key"]: i + 1 for i, r in enumerate(numbered)}}


def merge_view(base: dict, fresh: dict) -> dict:
    gone = set(fresh.get("skipped") or [])
    base_skipped = base.get("skipped") or []
    keys = {r["key"] for b in fresh["buckets"] for r in b["rows"]}
    ids = list(dict.fromkeys([b["id"] for b in fresh["buckets"]] + [b["id"] for b in base.get("buckets", [])]))
    buckets = []
    for bid in ids:
        old = next((o for o in base.get("buckets", []) if o["id"] == bid), None)
        b = next((o for o in fresh["buckets"] if o["id"] == bid), None) or {**old, "rows": []}
        extra = [r for r in (old["rows"] if old else []) if r.get("sources") and all(s in gone for s in r["sources"])
                 and r["key"] not in keys]
        merged = {**b, "rows": list(b["rows"]) + extra}
        if merged["rows"]:
            buckets.append(merged)
    buckets.sort(key=lambda b: bucket_rank(b["id"]))
    base_sections = [s for pg in (base.get("pages") or []) for s in pg["sections"]]
    pages = [{**pg, "sections": [(next((f for f in base_sections if f["id"] == q["id"]), q) if q["id"] in gone else q)
                                 for q in pg["sections"]]}
             for pg in (fresh.get("pages") or [])]
    # The headline counts every row and names the next date: a run that left out sections the earlier
    # one had would undercount, so the earlier headline stays until a run as complete as it comes.
    fresh_skipped = fresh.get("skipped") or []
    fresh_has_inbox = "inbox" not in fresh_skipped
    fresh_has_calendar = "calendar" not in fresh_skipped
    fresh_is_partial = any(s not in base_skipped for s in fresh_skipped)
    # The 'all clear' and hygiene lines and the since line come from every section of a run, so
    # a partial run would drop those of the sections it left out: they stay like the headline.
    fresh_extras = fresh.get("extras") or {"clear": [], "hygiene": [], "workplace": None}
    base_extras = base.get("extras") or {}
    extras = ({**fresh_extras, "clear": list(base_extras.get("clear") or []),
               "hygiene": list(base_extras.get("hygiene") or [])} if fresh_is_partial else fresh_extras)
    return {
        **fresh,
        "extras": extras,
        "since": base.get("since") if fresh_is_partial else fresh.get("since"),
        "headline": base.get("headline", "") if fresh_is_partial else fresh["headline"],
        "status": fresh["status"] if fresh_has_inbox else base.get("status", []),
        "agenda": fresh["agenda"] if fresh_has_calendar else base.get("agenda", []),
        "is_full": bool(fresh.get("is_full") or base.get("is_full")),
        "full_ms": max(fresh.get("full_ms") or 0, base.get("full_ms") or 0),
        # A saved view of an older version does not know skipped yet.
        "skipped": [s for s in fresh_skipped if s in base_skipped],
        "buckets": buckets,
        "pages": pages,
    }


def to_tab(t: dict) -> dict:
    t = _dict(t)
    return {"name": as_text(t.get("name")), "workspace": as_text(t.get("workspace")), "ref": as_text(t.get("ref")),
            "ws_ref": as_text(t.get("ws_ref")), "state": as_text(t.get("state")), "last": as_text(t.get("last")),
            "slug": as_text_or_null(t.get("slug")), "item": as_text_or_null(t.get("item")),
            "team": as_text_or_null(t.get("team")), "role": as_text_or_null(t.get("role")),
            # where the driver read the state (cmux: hook or glyph); a glyph is lost with a title of its own
            "state_source": t.get("state_source") if t.get("state_source") in ("hook", "glyph") else None,
            # kept internally, never sent to the page
            "id": as_text_or_null(t.get("id")), "is_self": t.get("is_self") is True}


def ref_number(ref: Any) -> int:
    m = re.search(r"(\d+)$", as_text(ref))
    return int(m.group(1)) if m else 2 ** 53 - 1


# ---------------------------------------------------------------- decisions of register.tsx

def row_actions(row: dict, tab: dict | None) -> list[dict]:
    """register.tsx rowActions: the first matching branch wins."""
    def act(aid: str, primary: bool = False, dim: bool = False) -> dict:
        return {"id": aid, "primary": primary, "dim": dim}

    approved = row.get("inbox_state") == "approved"
    if tab and not is_live(tab) and launch_item(row) is not None and not approved:
        return [act("restart", primary=True), act("to_tab")]
    if tab:
        return [act("to_tab", primary=True)]
    if row.get("inbox_id") and approved:
        return [act("approved", dim=True)]     # discarding is in the close menu beside every row
    if row.get("bucket") == "waiting":
        return [act("follow_up")]
    if row.get("inbox_id") and row.get("gate") == "only-you":
        # yours to do: an agent can only advise; "done" is in the close menu beside it, never a second button
        return [act("advise", primary=True)]
    if launch_item(row) is not None:
        return [act("do", primary=True), act("advise")]
    # a foreign row (an issue, an application, a deadline): Get it done and Advise file it to the inbox, then start on that
    return [act("do", primary=True), act("advise"), act("ask")]


def approvable(row: dict, tab: dict | None, section: str) -> bool:
    """register.tsx dashboard: only entries whose yes executes an action, no tab, no yes given."""
    return bool(row.get("inbox_id") and row.get("gate") == "your-yes" and row.get("has_action")
                and row.get("inbox_state") != "approved" and tab is None and section == "give")


# ---------------------------------------------------------------- texts to Claude

def ask_about(row: dict, tx: dict = EN) -> str:
    where = row.get("ref") or row.get("url") or row.get("task") or row.get("inbox_id") or ""
    return tx["ask_about"].format(title=quote(row.get("title", "")), where=paren(quote(where) if where else ""))


def ask_info(section: str, info: dict, tx: dict = EN) -> str:
    url = info.get("url") or ""
    extra = ", ".join(x for x in [info.get("detail") or "", url if re.match(r"https?:", url) else ""] if x)
    return tx["ask_info"].format(section=neutral(section), title=quote(info.get("title", "")),
                                 extra=paren(quote(extra) if extra else ""))


def follow_up(row: dict, tx: dict = EN) -> str:
    why = ", ".join(row.get("why") or [])
    return tx["follow_up"].format(title=quote(row.get("title", "")), why=paren(quote(why) if why else ""))


def overview(view: dict, rows: list[dict], tx: dict = EN) -> str:
    lines = [f"{i + 1}. [{classify(r)}] {quote(r['title'], 140)}" for i, r in enumerate(rows[:25])]
    return "\n".join([tx["overview_head"].format(at=view["collected_at"], headline=quote(view["headline"])), *lines,
                      tx["overview_tail"]])


def plan_day(view: dict, rows: list[dict], waiting: list[dict], tx: dict = EN) -> str:
    agenda = [f"- {neutral(a['when'])} {quote(a['title'], 80)}" for a in view.get("agenda", [])]
    lines = []
    for i, r in enumerate(rows[:30]):
        tag = classify(r) + (f" {neutral(r['priority'])}" if r.get("priority") else "") + \
            (f" {quote(r['mark']['label'], 40)}" if r.get("mark") else "")
        lines.append(f"{i + 1}. [{tag}] {quote(r['title'], 120)}")
    tabs = [f"- {quote(t['workspace'], 60)} / {quote(t['name'], 60)}: {state_word(t['state'], tx)}" for t in waiting]
    out = [tx["plan_head"].format(at=view["collected_at"], headline=quote(view["headline"]))]
    if agenda:
        out += [tx["plan_agenda"], *agenda]
    out += [tx["plan_rows"], *lines]
    if tabs:
        out += [tx["plan_tabs"], *tabs]
    out.append(tx["plan_tail"])
    return "\n".join(out)


def evening(tabs: list[dict], seen: dict, now: float, tx: dict = EN) -> str:
    open_tabs = [t for t in tabs if t.get("state") != "shell"]
    if not open_tabs:
        return tx["evening"]
    lines = []
    for t in open_tabs:
        s = seen.get(t["ref"])
        since = tx["evening_since"].format(duration=duration(now - s["since_ms"])) if s else ""
        last = tx["evening_last"].format(last=quote(t["last"], 80)) if t.get("last") else ""
        lines.append(f"- {quote(t['workspace'], 60)} / {quote(t['name'], 60)}: {state_word(t['state'], tx)}{since}{last}")
    return "\n".join([tx["evening"], tx["evening_tabs"], *lines])
