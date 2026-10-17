# SPDX-License-Identifier: MIT
"""Collect pipeline of the cockpit: one collect at a time, coalesced, merged, cached.

Three passes run `briefing.py collect --json --no-save` (never without --no-save: the
snapshot baseline of .bridge/briefings/ belongs to the terminal briefing): `quick`
leaves out the slow trackers and command sections, `full` asks everything, `delta`
asks only what changes on disk. Each pass is parsed, merged with the previous view
(model.merge_view), joined with the task list (model.with_tasks) and turned into the
model the page renders (`build_model`). A request while a pass runs is queued as the
strongest of what was asked (full > quick > delta). Rules: contract section 3.4.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
import threading
import traceback
import urllib.parse
from pathlib import Path
from typing import Any

from . import model as m
from .daybook import week_done
from .details import INBOX_ID_RE
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
             page_id: str = "", section_id: str = "") -> dict:
    tab = m.tab_for({"task": it.get("task"), "inbox_id": None}, tabs) if it.get("task") else None
    return {"index": index, "key": m.item_key(page_id, section_id, it), "actionable": it.get("actionable") is True, "title": it["title"], "detail": it["detail"], "when": it["when"], "tone": it["tone"],
            "link": make_link(it.get("url"), root), "task": it.get("task"), "ask": it["ask"], "mark": it["mark"],
            "priority": it.get("priority"), "state": it.get("state"), "lines": it.get("lines", []),
            "meter": it.get("meter"), "group": it.get("group"), "icon": it.get("icon"),
            "tags": it.get("tags"), "account": it.get("account"), "inbox": it.get("inbox"),
            "actions": it.get("actions"), "row_id": it.get("row_id"), "at": it.get("at"),
            "starting": bool(it.get("task") and it["task"] in starting), "tab": tab_summary(tab, view)}


def tab_summary(tab: dict | None, view: dict | None) -> dict | None:
    if not tab:
        return None
    return {"ref": tab["ref"], "state": tab["state"], "live": m.is_live(tab), "waiting": m.is_waiting(tab, view)}


def build_model(view: dict, *, root: Path, tabs: list[dict], seen: dict, control_ref: str | None, hidden: dict,
                dismissed: dict | None = None,
                runs: dict, teams: list[dict], tasks: list[dict], settled: set, starting: set, now: float,
                seq: int, stale: bool, profile: str | None, tx: dict,
                review: dict | None = None) -> tuple[dict, dict]:
    """The page model (contract section 3.3) and an index row_key -> internal row for the verbs."""
    today = m.iso_date(now)
    dismissed = dismissed or {}
    hidden = {**hidden, **{k: "9999-12-31" for k in dismissed}}     # out until "show again"
    lay = m.layout(view, settled, hidden, today, tabs)
    numbers = lay["numbers"]
    index: dict[str, dict] = {}
    others = [t for t in tabs if t["ref"] != control_ref]

    kinds = {t["slug"]: t.get("kind") for t in tasks}

    def closable(slug: Any) -> bool:
        """A finite task can close, a stream never; a task workplace.py does not list is looked up on disk."""
        if not isinstance(slug, str) or not TASK_SLUG_RE.match(slug):
            return False
        kind = kinds.get(slug)
        return kind == "tasks" if kind else (root / "work" / "tasks" / slug).is_dir()

    review = review or {"running": None, "error": None, "last": None, "tasks": {}}
    verdicts = review["tasks"]

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
            # done or not doing in two clicks: a finite task, an inbox item, any other row; a stream never
            "settle": ([] if is_task_row and not closable(row.get("task")) else list(m.SETTLE_OUTCOMES)),
            "review": verdicts.get(row.get("task")) if is_task_row else None,
        }
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
    for slug, title in [(t["slug"], page_titles.get(t["slug"]) or t.get("title") or t["label"]) for t in tasks] + page_tasks + review_tasks:
        key = f"task:{slug}"
        if key not in index and key not in settled:
            task_rows.append(row_out(m.task_row_for(slug, title, tasks, tx), "work"))

    pages = []
    alarms = []
    for pg in view.get("pages", []):
        secs = []
        for s in pg["sections"]:
            cap = DRAWN_CAP if s.get("view") in ("mosaic", "tiles", "groups") else ITEM_CAP    # drawn views filter every row
            shown = [info_out(it, i, root, tabs, view, starting, pg["id"], s["id"]) for i, it in enumerate(s["items"][:cap])]
            items = [i for i in shown if not (i["actionable"] and (i["key"] in settled or (hidden.get(i["key"]) or "") > today))]
            # a row put off or settled leaves the table, and its count and finding go with it, so the tab badge,
            # the section head and the alarm never count a row the page does not show
            gone = [i for i in shown if i not in items]
            bad = max(0, s["bad"] - sum(1 for i in gone if i.get("tone") == "bad"))
            sec = {k: s[k] for k in ("id", "kind", "title", "status", "reason", "alarm", "empty", "weight", "as_of")}
            secs.append(sec | {"count": max(0, s["count"] - len(gone)), "total": max(0, s["total"] - len(gone)), "bad": bad,
                               "items": items, "view": s.get("view"), "hide_empty": s.get("hide_empty") is True,
                               "more": max(0, len(s["items"]) - cap)})
            if bad > 0:
                alarms.append({"page_id": pg["id"], "page_title": pg["title"], "section_title": s["title"],
                               "count": int(bad)})
        pages.append({"id": pg["id"], "title": pg["title"], "badge": m.page_badge({"sections": secs}), "sections": secs,
                      "group": pg.get("group", "main"), "overview": pg.get("overview") is True,
                      "jev": isinstance(pg.get("jev"), dict)})

    waiting_tabs = [t for t in others if m.is_waiting(t, view)]
    long_tabs = [t for t in others if m.long_state(t, seen, now)]
    attention = {t["ref"] for t in waiting_tabs} | {t["ref"] for t in long_tabs}
    totals = {s["id"]: s["total"] for s in sections}
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
                   "now": totals["now"], "give": totals["give"], "work": totals["work"], "later": totals["later"],
                   "hidden": len(hidden_out)},
        "sections": sections, "numbers": numbers, "hidden": hidden_out, "approvable": approvable,
        "task_rows": task_rows,
        "review": {"running": review["running"], "error": review["error"], "last": review["last"],
                   "keys": [f"task:{slug}" for slug in verdicts if f"task:{slug}" in index]},
        "pages": pages, "alarms": alarms,
        "teams": [{"id": t["id"], "label": t["label"], "for_types": t["for_types"],
                   "roles": [{"id": r["id"], "name": r["name"], "mode": r["mode"]} for r in t["roles"]]} for t in teams],
        # the one coloured number of the page bar (14.10.): what waits for you, the same count as the station
        # "waits for you" and the lead line of the start page; the approvals stand in their own section
        "briefing_badge": totals["now"],
    }
    return model, index


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
        self.last_error: dict | None = None
        self.ask_triage = False
        self.view: dict | None = None
        self.tasks: list[dict] = []
        self.teams: list[dict] = []
        self.model: dict | None = None
        self.index: dict[str, dict] = {}
        self.seq = 0
        self.stale = False
        self.settled: dict[str, str] = {}
        self.starting: dict[str, float] = {}
        # when the last full pass started, successful or not: tick waits full_minutes from it
        self.full_attempt_ms = 0.0
        self.stop = False

    # ------------------------------------------------------------ queue

    def request(self, kind: str, fresh: bool = False) -> None:
        with self.cond:
            busy = self.running is not None
            if busy and kind == "both":
                kind = "full"
            if busy and fresh:
                self.app.note(self.app.tx["already_loading"], "info")
            if self.pending is None or RANK[kind] > RANK[self.pending]:
                self.pending = kind
            self.pending_fresh = self.pending_fresh or fresh
            self.cond.notify_all()
        self.app.broadcast("loading", self.loading_state())

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
            kind, fresh = self.pending, self.pending_fresh
            self.pending, self.pending_fresh = None, False
            if kind == "both":
                kind, self.pending, self.pending_fresh = "quick", "full", fresh
            self.running, self.running_fresh, self.started_ms = kind, fresh, int(self.app.clock())
            if kind == "full":
                self.full_attempt_ms = self.started_ms
        self.app.broadcast("loading", self.loading_state())
        try:
            self.run_pass(kind, fresh)
        except Exception:  # never crash the worker
            self.app.log_error("collect pass failed:\n" + traceback.format_exc())
            self.last_error = {"pass": kind, "message": "internal error", "at": m.clock_time(self.app.clock())}
            self.app.note(self.app.tx["load_failed"].format(err="internal error"), "bad")
        finally:
            with self.cond:
                self.running = None
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
        if fresh:
            argv.append("--fresh")
        if self.ask_triage:
            argv += ["--style", "triage"]
        return argv

    def refresh_tasks(self) -> None:
        run = self.app.run(self.app.workplace("tasks", "--json"), LIST_TIMEOUT)
        if run.ok:
            try:
                tasks = m.parse_tasks(run.out)
            except (ValueError, TypeError):
                return
            with self.lock:
                self.tasks = tasks

    def refresh_teams(self) -> None:
        run = self.app.run(self.app.workplace("teams", "--json"), LIST_TIMEOUT)
        if run.ok:
            try:
                teams = m.parse_teams(run.out)
            except (ValueError, TypeError):
                return
            with self.lock:
                self.teams = teams

    def run_pass(self, kind: str, fresh: bool) -> None:
        app = self.app
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
        if not run.ok or not isinstance(raw, dict):
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
            return
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
                if sec.get("status") != "ok" or sec.get("total", len(items)) > len(items):
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
            model, index = build_model(
                self.view, root=app.root, tabs=tabs, seen=app.tabs.seen_copy(), control_ref=app.tabs.control_ref(),
                hidden=app.store.hidden(), dismissed=app.store.dismissed(), runs=app.store.team_runs(), teams=self.teams, tasks=self.tasks,
                settled=set(self.settled), starting=self.starting_items(), now=app.clock(), seq=self.seq,
                stale=self.stale, profile=app.cfg.profile, tx=app.tx, review=app.review.state(self.task_open))
            # the start page's day book and the week's closed tasks; a failure there never stops the page
            try:
                app.daybook.record(model)
                model["days"] = app.daybook.view()
                model["week"] = week_done(app.root, dt.date.fromtimestamp(app.clock() / 1000))
            except (OSError, ValueError, TypeError, AttributeError):
                model["days"], model["week"] = {"quota": {}, "counts": {}}, {"count": 0, "since": None, "items": []}
            # the return channel: where each start handed to a tab stands (returns.py)
            try:
                seen = app.tabs.seen_copy()
                rich = [{**t, "filed_by": (m.filed_by(t, self.view) or {}).get("key"),
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
            # (publish only serializes and enqueues).
            app.broadcast("view", model)
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
                        out = {**self.app.store.hidden(), **{k: "9999-12-31" for k in self.app.store.dismissed()}}
                        today = m.iso_date(self.app.clock())
                        items = [i for i in items if not (i["actionable"] and (i["key"] in self.settled or (out.get(i["key"]) or "") > today))]
                        return items, s.get("total", len(items))
        return None

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

    def tick(self, clients: int) -> None:
        """Every WORK_SCAN_S: end launch holds; while a page is open, one full pass every full_minutes."""
        self.expire_starting()
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
