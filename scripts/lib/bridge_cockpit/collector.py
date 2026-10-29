# SPDX-License-Identifier: MIT
"""Collect pipeline of the cockpit: one collect at a time, coalesced, merged, cached.

Three passes run `briefing.py collect --json --no-save` (never without --no-save: the
snapshot baseline of .bridge/briefings/ belongs to the terminal briefing): `quick`
leaves out the slow trackers and command sections, `full` asks everything, `delta`
asks only what changes on disk. The task list (`workplace.py tasks`) is read on every
quick and full pass, but on a delta only when work/tasks or work/streams changed since
the last read or a cockpit action asked for it. Each pass is parsed, merged with the previous view
(model.merge_view), joined with the task list (model.with_tasks) and turned into the
model the page renders (`build_model`). A request while a pass runs is queued as the
strongest of what was asked (full > quick > delta). Rules: contract section 3.4.
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import re
import sys
import threading
import traceback
import urllib.parse
from pathlib import Path
from typing import Any

from dataclasses import replace

from . import card as cd
from . import model as m
from . import origin as og
from .daybook import week_done
from .details import INBOX_ID_RE, inbox_facts
from .watch import task_snapshot
from . import returns as ret

TASK_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}\Z")      # the same rule as actions.SLUG_RE

PASS_FLAGS = {
    "quick": ["--skip", "tracker", "--skip", "command"],
    "full": [],
    "delta": ["--only", "inbox", "--only", "advise", "--only", "tasks", "--only", "activity", "--only", "workplace"],
}
# "both" is quick followed by full (start, user reload); it is never shown as a pass of its own.
RANK = {"delta": 0, "quick": 1, "full": 2, "both": 3}
COLLECT_TIMEOUT = 120
LIST_TIMEOUT = 20
SWEEP_TIMEOUT = 20      # one inbox close of the sweep after a full pass
ITEM_CAP = 50
DRAWN_CAP = 300
ADOPT_CAP = 4
START_HOLD_MS = 15000
RECHECK_S = (15, 1800)  # the shortest and longest wait a step may ask for before its section is read again


def make_link(url: str | None, root: Path) -> dict | None:
    """http(s) as a web link; file:// inside the root as a relative path; anything else dropped."""
    if not url or not isinstance(url, str):
        return None
    if re.match(r"https?://", url):
        return {"kind": "web", "href": url}
    if url.startswith("file://"):
        try:
            path = Path(urllib.parse.unquote(urllib.parse.urlparse(url).path)).resolve()
            rel = path.relative_to(Path(root).resolve())
        except (ValueError, OSError):
            return None
        return {"kind": "file", "path": rel.as_posix()}
    return None


def info_out(it: dict, index: int, root: Path, tabs: list[dict], view: dict | None, starting: set,
             page_id: str = "", section_id: str = "", known: og.Known | None = None,
             card_ctx: cd.Ctx | None = None) -> dict:
    # a task row, or a row an agent was started on (its inbox item): either way the tab shows on the row
    tab = m.tab_for({"task": it.get("task"), "inbox_id": None if it.get("task") else it.get("inbox")}, tabs) \
        if it.get("task") or it.get("inbox") else None
    out = {"index": index, "key": m.item_key(page_id, section_id, it), "actionable": it.get("actionable") is True, "title": it["title"], "detail": it["detail"], "when": it["when"], "tone": it["tone"],
            "link": make_link(it.get("url"), root), "task": it.get("task"), "ask": it["ask"], "mark": it["mark"],
            "priority": it.get("priority"), "state": it.get("state"), "lines": it.get("lines", []),
            "meter": it.get("meter"), "group": it.get("group"), "icon": it.get("icon"), "glyph": it.get("glyph"),
            "tags": it.get("tags"), "account": it.get("account"), "inbox": it.get("inbox"),
            "actions": it.get("actions"), "row_id": it.get("row_id"), "at": it.get("at"), "flags": it.get("flags"), "who": it.get("who"), "gh": it.get("gh"),
            "cal": it.get("cal"), "due_at": it.get("due_at"),
            "starting": bool(it.get("task") and it["task"] in starting), "tab": tab_summary(tab, view),
            **page_origin(it, section_id, known)}
    # the one card of the item (card.py), from what the row carries and the section it stands in
    out["card"] = cd.card_of(out, card_ctx)
    return out


def page_origin(it: dict, section_id: str, known: og.Known | None) -> dict:
    """Where a page item comes from and what it is (origin.py): an inbox item by its `from`, a task by its origin,
    anything else by its section; the work kind of the task it is, or the task or stream it is about"""
    known = known or og.Known()
    inbox = it.get("inbox") if it.get("origin_section_kind") == "inbox" else None
    # an inbox item reads its key as Due does (a cockpit filing names its section there); its own id is no ref
    row = {"key": f"item:{section_id}", "inbox_id": inbox, "inbox_key": it.get("inbox_key") if inbox else None,
           "task": it.get("task") if not inbox else None, "ref": None if inbox else it.get("row_id") or it.get("id"),
           "url": it.get("url"),
           "sources": [section_id], "origin_raw": it.get("origin_raw"), "origin_provider": it.get("origin_provider"),
           "origin_section_kind": it.get("origin_section_kind")}
    slug = it.get("task") or it.get("about_task") or (it.get("gh") or {}).get("task")
    return {"origin": og.classify_row(row, known), "work_kind": og.work_kind(slug, known),
            "about_kind": it.get("about_kind") or ("stream" if (it.get("gh") or {}).get("stream") else None)}


def tab_summary(tab: dict | None, view: dict | None) -> dict | None:
    if not tab:
        return None
    return {"ref": tab["ref"], "state": tab["state"], "live": m.is_live(tab), "waiting": m.is_waiting(tab, view),
            "idle": tab.get("idle") is True}


def build_model(view: dict, *, root: Path, tabs: list[dict], seen: dict, control_ref: str | None, hidden: dict,
                dismissed: dict | None = None,
                runs: dict, teams: list[dict], tasks: list[dict], settled: set, starting: set, now: float,
                seq: int, stale: bool, profile: str | None, tx: dict,
                review: dict | None = None, origin_map: tuple = (), triage: dict | None = None,
                describe: dict | None = None, files: list[dict] | None = None,
                carry_deferred: bool = False, pairs: dict | None = None, acks: dict | None = None) -> tuple[dict, dict]:
    """The page model (contract section 3.3) and an index row_key -> internal row for the verbs. `triage` (the
    triage items by key) and `describe` (the brief proposals by key) feed the card of each row (card.py).
    `carry_deferred` (Work through on) adds `deferred`: the inbox items a page lists that are put off past the
    briefing's window, as rows (deferred_rows). `pairs` (model.page_twins of the view) is worked out here when the
    caller has none: a row of Due and the page items of the same thing take one decision (model.decision_twins),
    and a row names the GitHub list it stands in (`on_board`, model.board_places). `acks` (store.acks) are the
    findings marked seen: such a page row stays, grey, and counts toward no badge and no alarm (model.ack_item)."""
    today = m.iso_date(now)
    pairs = m.page_twins(view) if pairs is None else pairs
    twins = m.decision_twins(pairs)
    places = m.board_places(pairs)
    # Later, Done or Not doing under ref:<id> (Work through) holds for item:<page>/<section>/<id> (the GitHub page)
    # and the other way round
    dismissed = m.with_twins(dismissed or {}, twins)
    settled = set(m.with_twins(dict.fromkeys(settled), twins))
    hidden = {**m.with_twins(hidden, twins), **{k: "9999-12-31" for k in dismissed}}     # out until "show again"
    lay = m.layout(view, settled, hidden, today, tabs)
    numbers = lay["numbers"]
    index: dict[str, dict] = {}
    others = [t for t in tabs if t["ref"] != control_ref]

    kinds = {t["slug"]: t.get("kind") for t in tasks}
    # the names this Bridge declares, once per pass (origin.py): its tasks and streams as listed win over the tree
    known = og.known_from_root(root, origin_map, view.get("section_info") or {})
    known = og.replace(known, work={**known.work, **{slug: "stream" if kind == "streams" else "task"
                                                     for slug, kind in kinds.items() if kind in ("tasks", "streams")}})

    def closable(slug: Any) -> bool:
        """A finite task can close, a stream never; a task workplace.py does not list is looked up on disk."""
        if not isinstance(slug, str) or not TASK_SLUG_RE.match(slug):
            return False
        kind = kinds.get(slug)
        return kind == "tasks" if kind else (root / "work" / "tasks" / slug).is_dir()

    def is_stream(slug: Any) -> bool:
        if not isinstance(slug, str) or not TASK_SLUG_RE.match(slug):
            return False
        kind = kinds.get(slug)
        return kind == "streams" if kind else (root / "work" / "streams" / slug).is_dir()

    review = review or {"running": None, "error": None, "last": None, "tasks": {}}
    verdicts = review["tasks"]
    # what every card is built with (card.py): the text table, the triage and describe entries, the tasks as
    # listed, the work kinds of this Bridge and the inbox items as read from disk (kept until they change)
    card_ctx = cd.Ctx(tx=tx.get("card") if isinstance(tx, dict) else None, triage=triage or {},
                      describe=describe or {}, tasks={t["slug"]: t for t in tasks}, work=dict(known.work),
                      inbox=lambda item_id: inbox_facts(root, item_id))

    def row_out(row: dict, section: str) -> dict:
        tab = m.tab_for(row, tabs)
        live_tab = tab if tab and m.is_live(tab) else None
        item = m.launch_item(row)
        is_task_row = bool(row.get("task")) and not row.get("inbox_id")
        adopt = []
        if is_task_row and not live_tab:
            adopt = [{"ref": t["ref"], "name": t["name"], "workspace": t["workspace"]} for t in tabs
                     if t["workspace"] in row.get("area_names", []) and not t.get("slug") and not t.get("item")
                     and t["state"] != "shell"][:ADOPT_CAP]
        team = None
        suggestions: list[str] = []
        if is_task_row:
            st = m.team_state(row, runs, teams, tabs, now)
            if st:
                team = {"team_id": st["team"]["id"], "started": st["started"],
                        "next_role": {"id": st["next"]["id"], "name": st["next"]["name"]} if st["next"] else None,
                        "ready": st["is_ready"], "waiting_for": st["waiting_for"]}
            fits = sorted(teams, key=lambda t: 0 if row.get("task_type") and row["task_type"] in t["for_types"] else 1)
            suggestions = [t["id"] for t in fits]
        url = m.row_url(row)
        link = {"kind": "web", "href": url} if url else make_link(row.get("url"), root)
        out = {
            "key": row["key"], "bucket": row["bucket"], "section": section, "number": numbers.get(row["key"]),
            "title": row["title"], "why": list(row.get("why", [])), "sources": list(row.get("sources", [])),
            "inbox_id": row.get("inbox_id"), "gate": row.get("gate"), "task": row.get("task"), "ref": row.get("ref"),
            "url": url, "link": link, "priority": row.get("priority"), "urgency": row.get("urgency"),
            "area": row.get("area"), "area_names": list(row.get("area_names", [])), "task_type": row.get("task_type"),
            "due": row.get("due"), "has_action": bool(row.get("has_action")), "inbox_state": row.get("inbox_state"),
            "inbox_key": row.get("inbox_key"), "mark": row.get("mark"), "is_new": bool(row.get("is_new")),
            "is_changed": bool(row.get("is_changed")), "tab": tab_summary(tab, view),
            "actions": m.row_actions(row, tab),
            "selectable": not live_tab and item is not None and row.get("inbox_state") != "approved",
            "starting": bool(item and item in starting), "adopt_candidates": adopt, "team": team,
            "team_suggestions": suggestions,
            "closable": is_task_row and closable(row.get("task")),
            # done or not doing in two clicks, every row the same: a stream too, it only asks first ("stream")
            "stream": is_task_row and is_stream(row.get("task")),
            "settle": list(m.SETTLE_OUTCOMES),
            "review": verdicts.get(row.get("task")) if is_task_row else None,
            # the files view (logic.js queueOf): doing or review, and the next step with where it comes from
            "status": row.get("status") if is_task_row else None, "next": row.get("next") if is_task_row else None,
            # who or what filed the row and what it is (origin.py, docs/bridge-cockpit.md "Where a row comes from"):
            # the task or stream it is, or is about, by its folder; `stream` and `closable` keep their meaning
            "origin": og.classify_row(row, known),
            "work_kind": og.work_kind(row.get("task") or row.get("about_task"), known),
            "about_kind": row.get("about_kind"),
            "inbox_kind": row.get("inbox_kind"),
            # the GitHub list the row also stands in ({page, section}, model.board_places): Work through folds such
            # rows of Not now into one line that leads there
            "on_board": places.get(row["key"]),
            # what a person sees an inbox row as (ask, report, idea); "waits for you" counts the asks
            "art": m.art_of_kind(row.get("inbox_kind")) if row.get("inbox_id") else None,
            # Work through: when a task last moved (its STATUS.md), and the day a deferred item comes back, read
            # from its own events as the card reads them (details.inbox_facts, kept until the item changes)
            "updated": row.get("updated") if is_task_row else None,
            "until": ((card_ctx.inbox(row["inbox_id"]) or {}).get("until")
                      if row.get("inbox_id") and row.get("inbox_state") == "deferred" else None),
        }
        # the one card of the row (card.py), from the row as it goes out (and when its item was filed)
        out["card"] = cd.card_of({**out, "created": row.get("created")}, card_ctx)
        # beside it what the card cannot hold of the describe view: stale, a proposal, a run (card.describe_state)
        out["describe"] = cd.describe_state(row["key"], card_ctx)
        index[row["key"]] = {"row": row, "section": section, "tab": tab, "out": out, "hidden": False}
        return out

    sections = []
    approvable = []
    for s in lay["sections"]:
        rows = [row_out(r, s["id"]) for r in s["all"]]
        sections.append({"id": s["id"], "total": len(s["all"]), "rows": rows, "compact": [r["key"] for r in s["shown"]]})
        approvable += [r["key"] for r in s["all"] if m.approvable(r, index[r["key"]]["tab"], s["id"])]
    hidden_out = []
    for r in lay["hidden_rows"]:
        out = row_out(r, m.classify(r))
        out["hidden_until"] = None if r["key"] in dismissed else hidden.get(r["key"])
        out["settled_as"] = (dismissed.get(r["key"]) or {}).get("outcome")
        index[r["key"]]["hidden"] = True
        hidden_out.append(out)
    # "open tab" on a page item addresses task:<slug>: every active task resolves, even without a row,
    # and so does every task a page shows (a backlog task on a tasks page), like the mod's
    # `trow ?? taskRow(slug, title)`. The slug is checked again before it reaches an argv.
    page_items = [it for pg in view.get("pages", []) for sec in pg["sections"] for it in sec["items"]
                  if isinstance(it.get("task"), str) and it.get("task")]
    page_tasks = [(it["task"], it.get("title") or it["task"]) for it in page_items]
    # They go out as task_rows too, so a task opened from a page shows the same actions as one on the card.
    task_rows = []
    # the page's full title beats the short label; an item without a title does not
    page_titles = {it["task"]: it["title"] for it in reversed(page_items) if it.get("title")}
    # and every task the last check judged, so its overview row has the same actions
    review_tasks = [(slug, v["title"]) for slug, v in verdicts.items()]
    # a task the list of every task names (cockpit.files_scope all) carries its status and fields from there too
    listed = files if files is not None else tasks
    for slug, title in [(t["slug"], page_titles.get(t["slug"]) or t.get("title") or t["label"]) for t in tasks] + page_tasks + review_tasks:
        key = f"task:{slug}"
        if key not in index and key not in settled:
            task_rows.append(row_out(m.task_row_for(slug, title, listed, tx), "work"))
    deferred_out = deferred_rows(view, index, settled, root, row_out, today) if carry_deferred else None

    pages = []
    alarms = []
    for pg in view.get("pages", []):
        secs = []
        for s in pg["sections"]:
            # drawn views and the GitHub list (board) filter and search every row
            cap = DRAWN_CAP if s.get("view") in ("mosaic", "tiles", "groups", "board", "log") else ITEM_CAP
            sec_ctx = replace(card_ctx, section_kind=s.get("kind"))
            shown = [info_out(it, i, root, tabs, view, starting, pg["id"], s["id"], known, sec_ctx)
                     for i, it in enumerate(s["items"][:cap])]
            items = [i for i in shown if not (i["actionable"] and (i["key"] in settled or (hidden.get(i["key"]) or "") > today))]
            # a row put off or settled leaves the table, and its count, finding and weight go with it, so the tab
            # badge, the section head and the alarm never count a row the page does not show (a row weighs unless
            # it is dim, briefing_view._page_section; a section that does not count stays at 0)
            gone = [i for i in shown if i not in items]
            # a finding marked seen stays on the page, grey, and counts like a row put off (model.ack_item)
            marked = [i for i in items if m.ack_item(i, acks or {})]
            bad = max(0, s["bad"] - sum(1 for i in gone if i.get("tone") == "bad")
                      - sum(1 for i in marked if i["acked"]["tone"] == "bad"))
            weight = max(0, s["weight"] - sum(1 for i in gone if i.get("tone") != "dim") - len(marked))
            sec = {k: s[k] for k in ("id", "kind", "title", "status", "reason", "alarm", "empty", "as_of")}
            sec["left_out"] = s.get("left_out") is True    # a section asked again on its own has no such key
            for extra in ("stale", "boards", "metrics", "cal_figures"):
                if s.get(extra):
                    sec[extra] = s[extra]
            secs.append(sec | {"count": max(0, s["count"] - len(gone)), "total": max(0, s["total"] - len(gone)), "bad": bad,
                               "weight": weight, "items": items, "view": s.get("view"), "hide_empty": s.get("hide_empty") is True,
                               "hide_ok": s.get("hide_ok") is True,
                               "steps": s.get("steps"), "place": s.get("place"),
                               "more": max(0, len(s["items"]) - cap)})
            if bad > 0:
                alarms.append({"page_id": pg["id"], "page_title": pg["title"], "section_title": s["title"],
                               "count": int(bad)})
        pages.append({"id": pg["id"], "title": pg["title"], "badge": m.page_badge({"sections": secs}), "sections": secs,
                      "group": pg.get("group", "main"), "overview": pg.get("overview") is True, "search": pg.get("search") is True,
                      "cards": m.parse_cards(pg.get("cards")),
                      "under": pg.get("under"), "subs": list(pg.get("subs") or []),
                      "jev": isinstance(pg.get("jev"), dict)})

    waiting_tabs = [t for t in others if m.is_waiting(t, view)]
    long_tabs = [t for t in others if m.long_state(t, seen, now)]
    attention = {t["ref"] for t in waiting_tabs} | {t["ref"] for t in long_tabs}
    totals = {s["id"]: s["total"] for s in sections}
    # what waits for you: the rows of Now that ask (briefing_view.asks_you). An idea or a report filed for today
    # still stands in Now, so the section's own total can be the larger number
    asks = sum(1 for r in next((x["all"] for x in lay["sections"] if x["id"] == "now"), []) if m.asks_you(r))
    files_out = None if files is None else files_of(files, index)
    model = {
        "seq": seq, "stale": stale,
        "profile": view.get("profile") or profile or "", "title": view.get("title") or "",
        "collected_at": view.get("collected_at", ""), "collected_ms": view.get("collected_ms", 0),
        "full_ms": view.get("full_ms", 0), "is_full": bool(view.get("is_full")),
        "headline": view.get("headline", ""), "headline_rest": view.get("headline_rest", ""), "since": view.get("since"),
        "skipped": list(view.get("skipped", [])), "agenda": list(view.get("agenda", [])),
        "status": list(view.get("status", [])),
        "extras": view.get("extras") or {"clear": [], "hygiene": [], "workplace": None},
        "counts": {"waiting_tabs": len(waiting_tabs), "long_tabs": len(long_tabs),
                   "working_tabs": len([t for t in others if t["state"] == "working"]),
                   "now": asks, "give": totals["give"], "work": totals["work"],
                   "track": totals["track"], "later": totals["later"],
                   "hidden": len(hidden_out),
                   "flow_open": flow_open(sections, hidden_out, files_out, task_rows, deferred_out)},
        "sections": sections, "numbers": numbers, "hidden": hidden_out, "approvable": approvable,
        "task_rows": task_rows,
        "review": {"running": review["running"], "error": review["error"], "last": review["last"],
                   "keys": [f"task:{slug}" for slug in verdicts if f"task:{slug}" in index]},
        "pages": pages, "alarms": alarms,
        "teams": [{"id": t["id"], "label": t["label"], "for_types": t["for_types"],
                   "roles": [{"id": r["id"], "name": r["name"], "mode": r["mode"]} for r in t["roles"]]} for t in teams],
        # the one coloured number of the page bar (14.10.): the asks of Now, the rows only; the approvals stand in their
        # own section. With Work through on the page counts its points that need you instead (flow.js flowWaiting,
        # 28.10.), tabs that ask among them, and so does the start page's head line
        "briefing_badge": asks,
        # every task and stream as a file (cockpit.files_scope all), None while the files view walks the active ones
        "files": files_out,
    }
    if deferred_out is not None:
        model["deferred"] = deferred_out
    return model, index


def deferred_rows(view: dict, index: dict, settled: set, root: Path, row_out, today: str) -> list[dict]:
    """The inbox items a page lists (an inbox section: the idea shelf, what runs on) that are put off past the
    briefing's window, so no section carries them: a row each (bucket plan, inbox_state deferred, the day it comes
    back as `until`), in the index like any other, so the verbs reach it. Read from the item's own events as the
    card reads them (details.inbox_facts): an item taken back on, closed, or no longer put off is left out"""
    have = {e["row"].get("inbox_id") for e in index.values() if isinstance(e, dict) and isinstance(e.get("row"), dict)}
    out, seen = [], set()
    for pg in view.get("pages", []):
        for sec in pg.get("sections", []):
            if sec.get("kind") != "inbox":
                continue
            for it in sec.get("items", []):
                iid = it.get("inbox")
                key = f"inbox:{iid}"
                if not isinstance(iid, str) or iid in have or iid in seen or key in index or key in settled:
                    continue
                facts = inbox_facts(root, iid) or {}
                if not facts.get("deferred") or facts["deferred"] <= today:
                    continue
                seen.add(iid)
                row = m._base_row(bucket="plan", title=facts.get("summary") or it.get("title") or iid, inbox_id=iid,
                                  gate=facts.get("gate") or None, task=facts.get("task") or None, inbox_state="deferred",
                                  inbox_kind=facts.get("kind") or None, area=facts.get("area") or None,
                                  due=facts.get("due") or None, created=facts.get("created") or None, sources=["inbox"])
                row["key"] = key
                out.append(row_out(row, "later"))
    return out


def flow_open(sections: list[dict], hidden: list[dict], files: list[dict] | None, task_rows: list[dict] | None = None,
              deferred: list[dict] | None = None) -> int:
    """How many things are open, each once (Work through's universe, flow.js flowUniverse): every row of the
    sections, every hidden row not decided here (no settled_as: put off, it is still open), every file of the
    files view (files_scope all) under its task's key, every task a page names whose folder is open (a task or a
    stream under work/tasks or work/streams: closable or stream) and every item put off past the window (deferred)"""
    keys = {r["key"] for s in sections for r in s["rows"]}
    keys |= {r["key"] for r in hidden if r.get("settled_as") is None}
    keys |= {f"task:{f['slug']}" for f in files or []}
    keys |= {r["key"] for r in task_rows or [] if r.get("closable") or r.get("stream")}
    keys |= {r["key"] for r in deferred or []}
    return len(keys)


ACTIVE = ("doing", "review")     # the tasks every consumer but the files view reads (workplace.py ACTIVE)
FILE_STATES = (*ACTIVE, "backlog")


def files_of(tasks: list[dict], index: dict) -> list[dict]:
    """Every task and stream as a file of the files view (cockpit.files_scope all), flat and small, in the order
    workplace.py lists them: only what its shelf and its reason chip read (files.js fileShelves, fileReason), the
    bucket of the row that stands for it (None for one with no row, a backlog task) and whether it is put off
    (deferred, until the day it comes back, None for one put away until shown again). The cover reads the rest
    from the task's detail, so headline, next and progress stay out of a list that goes out with every poll. A
    closed task never comes in."""
    out = []
    for t in tasks:
        if t.get("status") not in FILE_STATES:
            continue
        entry = index.get(f"task:{t['slug']}") or {}
        row = entry.get("out") or {}
        deferred = entry.get("hidden") is True
        out.append({"slug": t["slug"], "kind": "stream" if t.get("kind") == "streams" else "task",
                    "status": t["status"], "area_names": [a for a in t.get("area_names") or [] if a],
                    "priority": t.get("priority"), "title": t.get("title") or t.get("label") or t["slug"],
                    "updated": t.get("updated"), "blocked_by": t.get("blocked_by"), "bucket": row.get("bucket"),
                    "deferred": deferred, "deferred_until": row.get("hidden_until") if deferred else None})
    return out


class Collector:
    """Owns the view, the task and team lists, the model and the queue of passes."""

    def __init__(self, app: Any):
        self.app = app
        self.cond = threading.Condition(threading.RLock())
        self.lock = threading.RLock()
        self.pending: str | None = None
        self.pending_fresh = False
        self.running: str | None = None
        self.running_fresh = False
        self.started_ms = 0
        self.took_ms: dict[str, int] = {}
        # the last passes with their time and outcome, for the start page's ticker (ticker.perf)
        self.passes: collections.deque = collections.deque(maxlen=10)
        self.last_error: dict | None = None
        self.ask_triage = False
        self.view: dict | None = None
        self.tasks: list[dict] = []
        # every task and stream but the closed ones (cockpit.files_scope all), else None: model.files
        self.all_tasks: list[dict] | None = None
        self.teams: list[dict] = []
        self.model: dict | None = None
        self.index: dict[str, dict] = {}
        # the keys of one thing in Due and on a page (model.decision_twins), from the view of the last rebuild
        self.twin_map: dict[str, tuple[str, ...]] = {}
        self.seq = 0
        self.sent: str | None = None           # the last model sent, without its seq and pages
        self.sent_pages: dict | None = None    # and its pages, each as sent, by id
        self.stale = False
        self.settled: dict[str, str] = {}
        self.starting: dict[str, float] = {}
        # when the last full pass started, successful or not: tick waits full_minutes from it
        self.full_attempt_ms = 0.0
        # [due ms, section]: a step asked to read its section again at these times (recheck), each once
        self.rechecks: list[list] = []
        # the task list: a delta reads it only when an action asked or the task tree changed since the last read
        self.pending_tasks = False
        self.tasks_seen: dict[str, int] | None = None
        # the last pass's end and length, so the watcher's next delta waits at least that long (delta_hold_ms)
        self.ended_ms = 0.0
        self.pass_ms = 0.0
        self.stop = False

    # ------------------------------------------------------------ queue

    def request(self, kind: str, fresh: bool = False, tasks: bool = False) -> None:
        """Queue a pass; `tasks` makes a delta read the task list even when the task tree looks unchanged."""
        with self.cond:
            busy = self.running is not None
            if busy and kind == "both":
                kind = "full"
            if busy and fresh:
                self.app.note(self.app.tx["already_loading"], "info")
            if self.pending is None or RANK[kind] > RANK[self.pending]:
                self.pending = kind
            self.pending_fresh = self.pending_fresh or fresh
            self.pending_tasks = self.pending_tasks or tasks
            self.cond.notify_all()
        self.app.broadcast("loading", self.loading_state())

    def delta_hold_ms(self) -> float:
        """How long a watched delta still waits: while a pass runs, and after one for as long as it took."""
        with self.cond:
            now = self.app.clock()
            if self.running is not None:
                return max(1.0, now - self.started_ms)
            return max(0.0, self.ended_ms + self.pass_ms - now)

    def is_idle(self) -> bool:
        with self.cond:
            return self.pending is None and self.running is None

    def loading_state(self) -> dict:
        with self.cond:
            queued = self.pending
            if queued == "both":
                queued = "quick"
            return {"pass": self.running, "fresh": self.running_fresh if self.running else False,
                    "started_ms": self.started_ms if self.running else 0,
                    "eta_ms": self.took_ms.get(self.running, 0) if self.running else 0,
                    "queued": queued, "last_error": self.last_error}

    def step(self) -> bool:
        """Run one queued pass in this thread; False when nothing was queued."""
        with self.cond:
            if self.pending is None:
                return False
            kind, fresh, tasks = self.pending, self.pending_fresh, self.pending_tasks
            self.pending, self.pending_fresh, self.pending_tasks = None, False, False
            if kind == "both":
                kind, self.pending, self.pending_fresh = "quick", "full", fresh
            self.running, self.running_fresh, self.started_ms = kind, fresh, int(self.app.clock())
            if kind == "full":
                self.full_attempt_ms = self.started_ms
        self.app.broadcast("loading", self.loading_state())
        try:
            self.run_pass(kind, fresh, tasks)
        except Exception:  # never crash the worker
            self.app.log_error("collect pass failed:\n" + traceback.format_exc())
            self.last_error = {"pass": kind, "message": "internal error", "at": m.clock_time(self.app.clock())}
            self.app.note(self.app.tx["load_failed"].format(err="internal error"), "bad")
        finally:
            with self.cond:
                self.running = None
                self.ended_ms = self.app.clock()
                self.pass_ms = max(0.0, self.ended_ms - self.started_ms)
            self.app.broadcast("loading", self.loading_state())
        return True

    def drain(self) -> None:
        while self.step():
            pass

    def worker(self) -> None:
        while True:
            with self.cond:
                while self.pending is None and not self.stop:
                    self.cond.wait(timeout=1.0)
                if self.stop:
                    return
            self.step()

    def shutdown(self) -> None:
        with self.cond:
            self.stop = True
            self.cond.notify_all()

    # ------------------------------------------------------------ one pass

    def collect_argv(self, kind: str, fresh: bool) -> list[str]:
        app = self.app
        argv = [sys.executable, app.runner.script("scripts/briefing.py"), "--root", str(app.root), "collect"]
        if app.cfg.profile:
            argv.append(app.cfg.profile)
        argv += ["--json", "--no-save", "--max-items", "500", *PASS_FLAGS[kind]]
        if getattr(app.cfg, "setup", True):
            argv.append("--setup")      # the Setup page (scripts/bridge-setup.py), on every pass: a pass that leaves it out keeps it
        if fresh:
            argv.append("--fresh")
        if self.ask_triage:
            argv += ["--style", "triage"]
        return argv

    def refresh_tasks(self) -> None:
        seen = task_snapshot(self.app.root)     # before the read: a change during it is read next time
        # cockpit.files_scope all: one read of every task (the backlog too) for model.files, and every other
        # consumer (rows, WIP, focus) keeps the doing and review ones it always had
        every = getattr(self.app.cfg, "files_scope", "active") == "all"
        run = self.app.run(self.app.workplace("tasks", *(["--all"] if every else []), "--json"), LIST_TIMEOUT)
        if run.ok:
            try:
                tasks = m.parse_tasks(run.out)
            except (ValueError, TypeError):
                return
            with self.lock:
                self.tasks = [t for t in tasks if t["status"] in ACTIVE] if every else tasks
                self.all_tasks = tasks if every else None
                self.tasks_seen = seen

    def refresh_teams(self) -> None:
        run = self.app.run(self.app.workplace("teams", "--json"), LIST_TIMEOUT)
        if run.ok:
            try:
                teams = m.parse_teams(run.out)
            except (ValueError, TypeError):
                return
            with self.lock:
                self.teams = teams

    def run_pass(self, kind: str, fresh: bool, tasks: bool = False) -> None:
        app = self.app
        # a second process of about a second: a delta from an inbox or log write does without it (#386)
        if kind != "delta" or tasks or task_snapshot(app.root) != self.tasks_seen:
            self.refresh_tasks()
        if not self.teams or (fresh and kind == "quick"):
            self.refresh_teams()
        started = app.clock()
        run = app.run(self.collect_argv(kind, fresh), COLLECT_TIMEOUT)
        raw = self._json(run)
        # Without a view the page would show the tasks and nothing else: ask once more for the triage view.
        if run.ok and isinstance(raw, dict) and "view" not in raw and not self.ask_triage:
            self.ask_triage = True
            run = app.run(self.collect_argv(kind, fresh), COLLECT_TIMEOUT)
            raw = self._json(run)
        ended = app.clock()
        self.took_ms[kind] = int(ended - started)
        def record(ok: bool) -> None:
            self.passes.append({"kind": kind, "took_ms": int(ended - started), "ok": ok, "at_ms": int(ended)})
            ticker = getattr(app, "ticker", None)   # the ticker's status band reads the passes (ticker.perf)
            if ticker is not None:
                try:
                    ticker.pass_recorded()
                except Exception as exc:  # noqa: BLE001 (the ticker never breaks a pass)
                    app.log_error(f"ticker pass: {exc!r}")
        if not run.ok or not isinstance(raw, dict):
            record(False)
            why = (run.err or "").strip().splitlines()[-1:] if not run.ok else ["no JSON object"]
            message = m.short(app.scrub(why[0]) if why else f"exit {run.code}", 120)
            self.last_error = {"pass": kind, "message": message, "at": m.clock_time(ended)}
            app.note(app.tx["load_failed"].format(err=message), "bad")
            return
        try:
            fresh_view = m.parse_view(raw, kind == "full", ended, app.tx)
        except Exception as error:  # unreadable output keeps the previous model
            message = m.short(app.scrub(str(error)), 120)
            self.last_error = {"pass": kind, "message": message, "at": m.clock_time(ended)}
            app.note(app.tx["view_unreadable"].format(err=message), "bad")
            record(False)
            return
        record(True)
        with self.lock:
            before = self.view
            # What this run left out stays at the state of the previous one. Add the tasks only afterwards:
            # otherwise a task whose inbox row comes from the previous run would appear twice.
            merged = m.with_tasks(m.merge_view(before, fresh_view) if before else fresh_view, self.tasks, app.tx)
            self.view = merged
            self.stale = False
            self.last_error = None
            present = {r["key"] for r in m.all_rows(merged)}
            # a task only a page shows stays settled while that page still lists it
            present |= {f"task:{it['task']}" for pg in merged.get("pages", []) for sec in pg.get("sections", [])
                        for it in sec.get("items", []) if isinstance(it.get("task"), str)}
            self.settled = {k: v for k, v in self.settled.items() if k in present}
        app.store.save_view(merged, app.cfg.language)
        self.rebuild()
        if kind == "full":
            self.sweep_filed(fresh_view)
        app.ack_closed_findings()

    def sweep_filed(self, view: dict) -> None:
        """Close the inbox items Get it done filed for page rows (`briefing:<profile>:<section>:<id>`, from the
        cockpit) whose row this full pass no longer shows. The briefing does the same for its own items, but
        only when it runs with --file, which the cockpit never does. A section that failed, was skipped or
        was cut short cannot say a row is gone, so its items stay"""
        app = self.app
        profile = view.get("profile") or app.cfg.profile
        if not profile:
            return
        prefix = f"briefing:{profile}:"
        looked, present = set(), set()
        for pg in view.get("pages", []):
            for sec in pg.get("sections", []):
                items = sec.get("items", [])
                if sec.get("status") != "ok" or sec.get("stale") or sec.get("total", len(items)) > len(items):
                    continue
                looked.add(sec["id"])
                present |= {f"{prefix}{sec['id']}:{it['id']}" for it in items if it.get("id")}
        if not looked:
            return
        app.inbox_cache = (0.0, None)
        closed = False
        for e in app.inbox_listing() or []:
            key = str(e.get("key") or "") if isinstance(e, dict) else ""
            if (e.get("from") != "bridge-cockpit" or e.get("state") not in ("open", "approved", "waiting", "deferred")
                    or not key.startswith(prefix) or not INBOX_ID_RE.match(str(e.get("id")))):
                continue
            if key[len(prefix):].split(":", 1)[0] in looked and key not in present:
                run = app.run(app.actions.inbox("close", e["id"], "--note", app.tx["swept_note"]), SWEEP_TIMEOUT)
                closed = closed or run.ok
        if closed:
            app.inbox_cache = (0.0, None)

    @staticmethod
    def _json(run) -> Any:
        if not run.ok:
            return None
        try:
            return json.loads(run.out)
        except ValueError:
            return None

    # ------------------------------------------------------------ model

    def load_stale(self) -> bool:
        view = self.app.store.load_view(self.app.cfg.language)
        if not view:
            return False
        with self.lock:
            self.view = view
            self.stale = True
        self.rebuild()
        return True

    def starting_items(self) -> set[str]:
        now = self.app.clock()
        with self.lock:
            self.starting = {k: v for k, v in self.starting.items() if v > now}
            return set(self.starting)

    def hold(self, items: list[str]) -> None:
        with self.lock:
            for item in items:
                self.starting[item] = float("inf")

    def release(self, items: list[str], after_ms: int = 0) -> None:
        now = self.app.clock()
        with self.lock:
            for item in items:
                if after_ms:
                    self.starting[item] = now + after_ms
                else:
                    self.starting.pop(item, None)

    def settle(self, key: str, note: str) -> None:
        with self.lock:
            self.settled[key] = note

    def unsettle(self, key: str) -> None:
        """A row taken back (reopened) shows again at once, before the next pass lists it."""
        with self.lock:
            self.settled.pop(key, None)

    def rebuild(self) -> None:
        app = self.app
        with self.lock:
            if self.view is None:
                return
            self.seq += 1
            tabs = app.tabs.tab_list()
            pairs = m.page_twins(self.view)
            self.twin_map = m.decision_twins(pairs)
            model, index = build_model(
                self.view, root=app.root, tabs=tabs, seen=app.tabs.seen_copy(), control_ref=app.tabs.control_ref(),
                hidden=app.store.hidden(), dismissed=app.store.dismissed(), runs=app.store.team_runs(), teams=self.teams, tasks=self.tasks,
                settled=set(self.settled), starting=self.starting_items(), now=app.clock(), seq=self.seq,
                stale=self.stale, profile=app.cfg.profile, tx=app.tx, review=app.review.state(self.task_open),
                origin_map=getattr(app.cfg, "origin_map", ()), files=self.all_tasks,
                carry_deferred=(getattr(app.cfg, "flow", None) or {}).get("enabled") is True, pairs=pairs,
                acks=app.store.acks(), **app.card_sources())
            # the start page's day book and the week's closed tasks; a failure there never stops the page
            try:
                app.daybook.record(model)
                model["days"] = app.daybook.view()
                model["week"] = week_done(app.root, dt.date.fromtimestamp(app.clock() / 1000))
            except (OSError, ValueError, TypeError, AttributeError):
                model["days"], model["week"] = {"quota": {}, "counts": {}}, {"count": 0, "since": None, "items": []}
            # the return channel: where each start handed to a tab stands (returns.py)
            try:
                seen, asks = app.tabs.seen_copy(), app.tabs.asks_now()
                rich = [{**t, "filed_by": (m.filed_by(t, self.view) or {}).get("key"), "ask": asks.get(t["ref"]),
                         "since_ms": int(seen.get(t["ref"], {}).get("since_ms", 0)),
                         "is_control": t["ref"] == app.tabs.control_ref()} for t in tabs]
                rows = {k: (v.get("out") or v) for k, v in index.items() if isinstance(v, dict)}
                model["returns"] = ret.build(app.launches.all(), rich, rows, app.root, app.clock())
                # an end not yet written to the item's log: written once, after the lock
                to_log = [r for r in model["returns"] if r["stage"] in ("result", "lost") and ret.log_line(r, app.cfg.language)
                          and app.launches.mark(r["key"], r["stage"])]
            except (OSError, ValueError, TypeError, AttributeError, KeyError):
                model["returns"], to_log = [], []
            self.model, self.index = model, index
            # Published under the lock: two rebuilds reach the page in the order of their seq
            # (publish only serializes and enqueues). A model equal to the last one sent but for
            # its seq is not sent again: the page would only render the same thing anew.
            # When only pages changed, only those pages go out (view_pages, put in by id on the page): the
            # whole model is the largest event, and most changes touch one page (review C34)
            rest = json.dumps({k: v for k, v in model.items() if k not in ("seq", "pages")}, sort_keys=True, default=str)
            listed = model.get("pages") or []
            pages = {p.get("id"): json.dumps(p, sort_keys=True, default=str) for p in listed}
            whole = rest != self.sent or self.sent_pages is None or len(pages) != len(listed)
            if whole and (rest, pages) != (self.sent, self.sent_pages):
                app.broadcast("view", model)
            elif not whole and pages != self.sent_pages:
                app.broadcast("view_pages", {"seq": model["seq"], "order": [p["id"] for p in listed],
                                             "pages": [p for p in listed if self.sent_pages.get(p["id"]) != pages[p["id"]]]})
            self.sent, self.sent_pages = rest, pages
        for r in to_log:
            self.log_return(r)

    def log_return(self, r: dict) -> None:
        """One line in the task's notes or the inbox item's events: how a start handed to a tab ended"""
        line = ret.log_line(r, self.app.cfg.language)
        if not line:
            return
        kind, item, text = line
        script = "scripts/task.py" if kind == "task" else "scripts/inbox.py"
        by = [] if kind == "task" else ["--by", "web"]
        argv = [sys.executable, self.app.runner.script(script), "--root", str(self.app.root), *by, "note", item, "--", text]
        self.app.run(argv, 30)

    def task_open(self, slug: str) -> bool:
        """A task the check judged is still worth showing while it is open (not moved to work/done/)."""
        if not TASK_SLUG_RE.match(slug):
            return False
        if any(t.get("slug") == slug for t in self.tasks):
            return True
        work = self.app.root / "work"
        return (work / "tasks" / slug / "STATUS.md").is_file() or (work / "streams" / slug / "STATUS.md").is_file()

    def resolve(self, key: str) -> dict | None:
        with self.lock:
            return self.index.get(key)

    def page_items(self, page_id: str, section_id: str) -> tuple[list[dict], int] | None:
        with self.lock:
            view = self.view
            if not view:
                return None
            for pg in view.get("pages", []):
                if pg["id"] != page_id:
                    continue
                for s in pg["sections"]:
                    if s["id"] == section_id:
                        tabs = self.app.tabs.tab_list()
                        starting = self.starting_items()
                        items = [info_out(it, i, self.app.root, tabs, view, starting, page_id, section_id) for i, it in enumerate(s["items"])]
                        # a decision on the same thing in Due holds here too (model.decision_twins)
                        out = m.with_twins({**self.app.store.hidden(), **{k: "9999-12-31" for k in self.app.store.dismissed()}},
                                           self.twin_map)
                        settled = m.with_twins(dict(self.settled), self.twin_map)
                        today = m.iso_date(self.app.clock())
                        items = [i for i in items if not (i["actionable"] and (i["key"] in settled or (out.get(i["key"]) or "") > today))]
                        return items, s.get("total", len(items))
        return None

    def twins(self, key: str) -> tuple[str, ...]:
        """`key` and the keys of the same thing in Due and on the pages (model.decision_twins), `key` first: one
        decision holds for all of them, so Show again takes it back under each"""
        with self.lock:
            return self.twin_map.get(key) or (key,)

    def view_profile(self) -> str | None:
        with self.lock:
            return (self.view or {}).get("profile") or self.app.cfg.profile or None

    def page_item_by_key(self, key: str) -> tuple[dict, dict, dict] | None:
        """(page, section, raw info) of a page item by its `item:` key, in the whole section (not the capped list)"""
        with self.lock:
            for pg in (self.view or {}).get("pages", []):
                for s in pg["sections"]:
                    for it in s["items"]:
                        if m.item_key(pg["id"], s["id"], it) == key:
                            return pg, s, it
        return None

    def page_item(self, page_id: str, section_id: str, index: int) -> tuple[dict, dict] | None:
        """(section, raw info) of a page item, for the ask prompt."""
        with self.lock:
            for pg in (self.view or {}).get("pages", []):
                if pg["id"] == page_id:
                    for s in pg["sections"]:
                        if s["id"] == section_id and 0 <= index < len(s["items"]):
                            return s, s["items"][index]
        return None

    def last_full_ms(self, view: dict) -> float:
        """The last full pass that succeeded or was tried, whichever is later."""
        return max(view.get("full_ms") or 0, self.full_attempt_ms)

    def expire_starting(self) -> None:
        """A launch hold that ran out changes the model: rebuild once, so `starting` leaves the page."""
        now = self.app.clock()
        with self.lock:
            expired = any(v <= now for v in self.starting.values())
        if expired:
            self.rebuild()

    def forget(self, section: str) -> None:
        """Void the section's cached answer and queue a full pass, so the next pass asks it again."""
        for cached in (self.app.root / ".bridge" / "briefing-cache").glob(f"*/{section}.json"):
            cached.unlink(missing_ok=True)
        self.request("full")

    def recheck(self, section: str, delays: object) -> None:
        """Read `section` again after each of `delays` seconds (a reboot answers at once and switches later):
        whole numbers from 15 s to 30 min, eight at most, anything else dropped."""
        if not isinstance(delays, list):
            return
        now = self.app.clock()
        due = [now + d * 1000 for d in delays if type(d) is int and RECHECK_S[0] <= d <= RECHECK_S[1]][:8]
        with self.lock:
            self.rechecks += [[t, section] for t in due]

    def tick(self, clients: int) -> None:
        """Every WORK_SCAN_S: end launch holds, run the rechecks that are due; while a page is open, one
        full pass every full_minutes."""
        self.expire_starting()
        now = self.app.clock()
        with self.lock:
            due = sorted({sec for t, sec in self.rechecks if t <= now})
            self.rechecks = [r for r in self.rechecks if r[0] > now]
        for section in due:
            self.forget(section)
        with self.lock:
            view = self.view
        if clients <= 0 or view is None or not self.is_idle():
            return
        if self.app.clock() - self.last_full_ms(view) >= self.app.cfg.full_minutes * 60000:
            self.request("full")

    def on_connect(self) -> None:
        with self.lock:
            view = self.view
        if not self.is_idle():
            return
        if view is None:
            self.request("quick")
        elif self.app.clock() - self.last_full_ms(view) > self.app.cfg.full_minutes * 60000:
            self.request("full")
