# SPDX-License-Identifier: MIT
"""Who sees what: a person named under `members:` of a workspace gets the areas of their workspaces, nothing else.

The owner, who logs in with the key, is not touched by anything here. For a person it runs the other way round from
a filter: nothing goes out unless this file lists it. A route, a verb, an event or a field somebody adds later is
closed until it is classified here, and the guards in test_bridge_cockpit_access.py fail until then.

Which rows a person sees is decided in one place, row_ok: the row names areas, every one of them is in the person's
scope, and it names at least one. A row that names none, or names one area of theirs and one that is not, stays out.
What a person may open or change follows from that: only what the cut model lists (visible). The scope is read from
the definitions on every call, so taking a name off a workspace works at once, and a workspace that rests, is archived
or cannot be read gives nothing. Questions to a model stay closed: it would read the whole Bridge from here.

The records of the files tab are read from the folders, closed ones too, so the model cannot say whose they are. A
record counts as an area's where workplace.py places a task the same way: by `area:`, by the workspace's `slugs:` or
by its `contexts:`. What only the default area catches stays out, as a row without an area does.

What a person's page shows follows from here as well: bootstrap names their pages, routes and verbs, and the page
sends nothing else (api.js), so a closed route is no error on their screen.
"""
from __future__ import annotations

import os
import re
from typing import Any

from .. import work_find
from .actions_base import ActionError
from .config import read_config_file
from .describe import _module

PERSON_RE = re.compile(r"^[a-z][a-z0-9-]{0,39}\Z")      # the same words as members: in docs/schemas/workspace.schema.yaml

PUBLIC = frozenset({"/api/health"})
PERSON_GET = frozenset({"/api/bootstrap", "/api/state", "/api/events", "/api/task", "/api/inbox", "/api/records"})
OWNER_GET = frozenset({
    "/api/agents", "/api/chats/archive", "/api/costs", "/api/costs/statement", "/api/find", "/api/flow/activity",
    "/api/flow/doc", "/api/github", "/api/graph", "/api/graph/node", "/api/history", "/api/inbox/noise", "/api/issue",
    "/api/logrange", "/api/page", "/api/relay", "/api/tab-history", "/api/tab/screen", "/api/ticker",
    "/api/timeline", "/api/usage", "/api/workers"})
PERSON_POST = frozenset({"/api/action", "/api/presence"})
OWNER_POST = frozenset({"/api/ask", "/api/reload", "/api/route", "/api/seen", "/api/clicks", "/api/flow/attach",
                        "/api/triage/run"})

# the tabs of a person's page, in this order: Start, Today, the files, the Chat. The rest would stand empty
PERSON_PAGES = ("@start", "briefing", "@files", "@chat")

# verb -> the arguments that name what it changes; each of them has to be a row the person sees
PERSON_VERBS = {"note": ("key",), "done": ("key",), "later": ("key",), "drop": ("key",), "priority": ("key",),
                "urgency": ("key",), "task_set_next": ("key",), "task_close": ("keys",), "settle": ("keys",)}
OWNER_VERBS = frozenset("""
    a2a_ask a2a_forget a2a_poll account_status adopt advise approve_all area ask_via_tab chat_remind chat_tab
    collect_context describe_apply describe_discard describe_run do_it explain_note files_ask finding_ack
    finding_unack flow_activity_summary flow_attach flow_instruct flow_merge flow_theme_move flow_theme_new
    flow_theme_rename flow_themes_run github_board github_board_default guide_read guide_settings
    guide_settings_reset hide home_tiles inbox_reopen inbox_unmute issue_check issue_done issue_review
    launch_settings launch_settings_reset organize_apply organize_propose pin quick_forget quick_handoff
    return_forget row_action row_undo run_seen runs_on session_link session_resume session_unlink shelve snapshot
    snapshot_list start_agent start_control tab_close tab_done tab_go_on tab_jump tab_keys tab_move tab_new tab_no
    tab_option tab_rename tab_send tab_yes task_keep task_reopen task_review task_running task_unmerge team_role
    ticker_edit ticker_profile ticker_refresh ticker_settings ticker_settings_reset timeline_ask to_task
    to_task_undo tour_done tour_reset unhide worker_advise workspace_active workspace_close workspace_delete
    workspace_new workspace_plan workspace_rename workspace_switch workspaces_enabled""".split())

PERSON_EVENTS = frozenset({"view", "workspaces", "loading"})
OWNER_EVENTS = frozenset({"ticker", "guide", "quick", "sessions", "agents", "relay", "acks", "triage", "quick_live",
                          "home", "view_pages", "tour", "themes", "tabs", "relay_state", "note", "launch", "describe",
                          "alert"})

# the state as a person gets it: these are worked out below, the rest is the empty shape the page knows
STATE_PERSON = frozenset({"ok", "server", "model", "loading", "workspaces", "work"})
STATE_NEUTRAL: dict[str, Any] = {
    "tabs": {"at_ms": 0, "tabs": [], "error": None, "control": None, "workspaces": None}, "notes": [],
    "relay": {"enabled": False, "online": False, "reason": "off", "session": None, "records": []},
    "cmux": {"ok": False, "error": None}, "driver": {"caps": []}, "home": {"tiles": None, "seen": None, "pins": []},
    "sessions": {"at_ms": 0, "sessions": [], "links": [], "runs": []},
    "quick": {"available": False, "default": None, "models": [], "keep_hours": 0, "config_error": None, "providers": {}, "convs": []},
    "quick_live": {}, "agents": {"peers": [], "convs": [], "keep_hours": 0},
    "triage": {"running": None, "error": None, "last": None, "items": {}},
    "jev": {"enabled": False, "ready": False, "reason": "off"},
    "prio": {"haiku": {"enabled": False, "ready": False, "model": None, "budget_left": 0}, "fallback": "off"},
    "launch": {"enabled": False, "manual": False, "auto": False, "effort": False, "models": [], "efforts": [],
               "default_model": None, "default_effort": None, "router": "off", "settings": {}},
    "ticker": {"rev": 0, "enabled": False, "settings": {"enabled": False}, "defaults": {}},
    "guide": {"enabled": False, "auto": False, "per_hour": 0, "available": False, "overridden": [], "rev": 0, "entries": {}},
    "tour": {"enabled": False, "done": None},
    "themes": {"enabled": False, "max_themes": 0, "themes": [], "assign": {}, "by_person": [], "suggest": {}, "at_ms": None,
               "budget_left": 0, "running": False, "last_error": None},
    "flow_ai": {"summary_left": 0, "instruct_left": 0, "instruct_running": False},
    "rooms": {"layout": "classic", "root": None, "control": None, "bridges": []}}

MODEL_FIELDS = frozenset({"seq", "collected_at", "collected_ms", "full_ms", "is_full"})
MODEL_COUNTED = frozenset({"counts", "numbers"})
MODEL_ROWS = frozenset({"sections", "hidden", "approvable", "task_rows", "files", "deferred"})
MODEL_NEUTRAL: dict[str, Any] = {
    "stale": False, "profile": "", "title": "", "headline": "", "headline_rest": "", "since": None, "skipped": [], "agenda": [], "status": [],
    "extras": {"clear": [], "hygiene": [], "workplace": None}, "pages": [], "alarms": [], "teams": [], "briefing_badge": 0,
    "review": {"running": False, "error": None, "last": None, "keys": []}, "days": {"quota": {}, "counts": {}},
    "week": {"quota": {}, "counts": {}}, "returns": []}

ROW_FIELDS = frozenset({
    "key", "bucket", "section", "number", "title", "why", "sources", "inbox_id", "gate", "task", "ref", "priority", "urgency",
    "area", "area_names", "task_type", "due", "has_action", "inbox_state", "mark", "is_new", "is_changed",
    "closable", "stream", "settle", "status", "next", "origin", "work_kind", "about_kind", "inbox_kind", "art", "updated",
    "until", "card",
    # what a task row and a file row carry beside these
    "slug", "label", "age", "stale", "type", "kind", "blocked_by", "path_kind"})
ROW_NEUTRAL: dict[str, Any] = {"url": None, "link": None, "inbox_key": None, "tab": None, "actions": [], "starting": False,
                               "adopt_candidates": [], "team": None, "team_suggestions": [], "review": None,
                               "also_inbox": [], "on_board": None, "describe": None, "selectable": False}
TASK_FIELDS = frozenset({"ok", "slug", "kind", "work_kind", "origin", "front", "sections", "brief", "files", "inbox", "card"})
TASK_NEUTRAL: dict[str, Any] = {"related": [], "log": [], "describe": None}
TASK_DROPPED = frozenset({"path"})       # where it lies on this machine, the page of a person needs no folder
INBOX_FIELDS = frozenset({"ok", "id", "item", "origin", "card"})
INBOX_ITEM = frozenset({"summary", "detail", "detail_truncated", "kind", "gate", "urgency", "state", "due", "created"})
RECORD_FIELDS = frozenset({"slug", "kind", "path", "title", "status", "priority", "area", "updated", "work_kind"})
RECORDS_ALL = 10 ** 6       # read them all: the cap of work_find.records would cut before the area does
LOADING_FIELDS = frozenset({"pass", "fresh", "started_ms", "eta_ms"})
WORKSPACE_ITEM = frozenset({"key", "area", "id", "title", "on", "fixed", "active", "level"})
WORKSPACE_NEUTRAL: dict[str, Any] = {"parent": None, "children": [], "held_by": None, "active_held_by": None}


def key_of(name: Any) -> str:
    return str(name or "").strip().lower()


class Access:
    def __init__(self, app: Any):
        self.app = app

    # ------------------------------------------------------------ who may see which area

    def person_of(self, address: str | None) -> str | None:
        """Who a signed-in address is: the member a workspace maps it to under `logins:`. Read on every call, so
        taking the line away works at once. An address on two people opens for neither."""
        if not address:
            return None
        try:
            found = {name for row in self.app.workspaces.rows() for name, mail in (row.get("logins") or {}).items()
                     if isinstance(mail, str) and mail.strip().lower() == address and name in (row.get("members") or [])}
        except Exception as exc:
            self.app.log_error(f"access: {exc!r}")
            return None
        return found.pop() if len(found) == 1 else None

    def scope(self, person: str) -> frozenset:
        """The areas of a person, as key_of spells them. Empty for anything that cannot be read."""
        try:
            rows = self.app.workspaces.rows()
            resting = {key_of(n) for n in self.app.workspaces.inactive}
            by_id = {r["id"]: r for r in rows}
            names = set()
            for row in rows:
                above = by_id.get(row.get("parent")) or {}
                key = key_of(row.get("area") or row.get("id"))
                up = key_of(above.get("area") or above.get("id")) if above else None
                if person in (row.get("members") or []) and row.get("area") and not row.get("archived") and not above.get("archived") \
                        and key not in resting and up not in resting:
                    names.add(key)
            return frozenset(names)
        except Exception as exc:     # whatever went wrong, it must end in nothing
            self.app.log_error(f"access: {exc!r}")
            return frozenset()

    def canon(self, name: Any) -> str:
        aliases = {key_of(a): key_of(n) for a, n in getattr(self.app.cfg, "area_aliases", ())}
        return aliases.get(key_of(name), key_of(name))

    def row_ok(self, row: dict, scope: frozenset) -> bool:
        names = [n for n in [row.get("area"), *(row.get("area_names") or [])] if key_of(n)]
        return bool(names) and all(self.canon(n) in scope for n in names)

    # ------------------------------------------------------------ what goes out

    def clean(self, value: Any) -> Any:
        """No path of this machine leaves, whatever a text quotes"""
        if isinstance(value, str):
            for path in (str(self.app.root), os.path.expanduser("~")):
                value = value.replace(f"{path}/", "").replace(path, "")
            return value
        if isinstance(value, dict):
            return {k: self.clean(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.clean(v) for v in value]
        return value

    def row(self, row: dict) -> dict:
        return {**ROW_NEUTRAL, **{k: v for k, v in row.items() if k in ROW_FIELDS}}

    def rows(self, rows: Any, scope: frozenset) -> list[dict]:
        return [self.row(r) for r in rows or [] if isinstance(r, dict) and self.row_ok(r, scope)]

    def model(self, model: dict | None, scope: frozenset) -> dict | None:
        if not isinstance(model, dict):
            return None
        sections, seen = [], set()
        for sec in model.get("sections") or []:
            rows = self.rows(sec.get("rows"), scope)
            keys = {r["key"] for r in rows}
            seen |= keys
            sections.append({"id": sec.get("id"), "total": len(rows), "rows": rows,
                             "compact": [k for k in sec.get("compact") or [] if k in keys]})
        hidden = self.rows(model.get("hidden"), scope)
        tasks = self.rows(model.get("task_rows"), scope)
        files = None if model.get("files") is None else self.rows(model["files"], scope)
        seen |= {r["key"] for r in hidden if r.get("key")}
        counts = dict.fromkeys(model.get("counts") or {}, 0)
        counts.update({s["id"]: s["total"] for s in sections if s["id"] in counts}, hidden=len(hidden))
        out = {**MODEL_NEUTRAL, **{k: v for k, v in model.items() if k in MODEL_FIELDS}, "sections": sections, "hidden": hidden,
               "task_rows": tasks, "files": files, "counts": counts,
               "numbers": {k: v for k, v in (model.get("numbers") or {}).items() if k in seen},
               "approvable": [a for a in model.get("approvable") or [] if (a if isinstance(a, str) else a.get("key")) in seen]}
        if "deferred" in model:
            out["deferred"] = self.rows(model["deferred"], scope)
        return self.clean(out)

    def visible(self, person: str) -> set[str]:
        """The keys a person may open or change: what the cut model lists"""
        model = self.model(self.app.collector.model, self.scope(person))
        if not model:
            return set()
        keys = {r["key"] for s in model["sections"] for r in s["rows"]} | {r["key"] for r in model["hidden"] if r.get("key")}
        for row in [*model["task_rows"], *(model["files"] or []), *model.get("deferred", [])]:
            if row.get("key"):
                keys.add(row["key"])
            if row.get("slug"):
                keys.add(f"task:{row['slug']}")
        return keys

    def workspaces(self, state: dict, scope: frozenset) -> dict:
        items = [{**WORKSPACE_NEUTRAL, **{k: v for k, v in i.items() if k in WORKSPACE_ITEM}} for i in state.get("items") or []
                 if i.get("area") and key_of(i["area"]) in scope]
        return {"rev": state.get("rev", 0), "enabled": True, "inactive": [], "gone": [], "off": [], "items": items}

    def loading(self, payload: Any) -> dict:
        return {k: v for k, v in (payload or {}).items() if k in LOADING_FIELDS}

    def work(self, state: dict) -> dict:
        """The plain day: Work through, the instruction line and the sources all lead to a model or a tab"""
        return {"view": "due", "focus_to_files": False, "files_scope": None, "flow": {"enabled": False}, "views": ["due"],
                "files_search": {"enabled": False, "block": [], "left": 0}}

    def state(self, person: str) -> dict:
        app, scope = self.app, self.scope(person)
        return {**STATE_NEUTRAL, "ok": True, "server": {"version": app.version, "started_ms": app.started_ms, "person": person},
                "model": self.model(app.collector.model, scope), "loading": self.loading(app.collector.loading_state()),
                "workspaces": self.workspaces(app.workspaces.state(), scope), "work": self.work(app.work_state())}

    def bootstrap(self, person: str) -> dict:
        app, cfg, scope = self.app, self.app.cfg, self.scope(person)
        areas = [n for n in cfg.areas if key_of(n) in scope]
        mine = lambda name: self.canon(name) in scope  # noqa: E731
        return {"ok": True, "csrf": app.csrf_of(person), "language": cfg.language, "version": app.version, "scratch": None,
                "config_warnings": [],
                "config": {"port": app.port, "relay": False, "tabs_seconds": cfg.tabs_seconds, "full_minutes": cfg.full_minutes,
                           "voice": False, "target": None, "control": None, "profile": None, "areas": areas,
                           "area_aliases": {a: n for a, n in getattr(cfg, "area_aliases", ()) if mine(a)},
                           "area_tags": {n: [n] for n in areas}, "clicks": False,
                           "person": {"name": person, "pages": list(PERSON_PAGES), "verbs": sorted(PERSON_VERBS),
                                      "routes": sorted(PERSON_GET | PERSON_POST | PUBLIC)}}}

    # ------------------------------------------------------------ the files tab

    def record_area(self, record: dict, spaces: list[dict]) -> str | None:
        """The area of a record, by the rule the tasks follow, None where only the default would take it"""
        word = record.get("area")
        found = _module("_cockpit_workplace", "workplace.py").workspace_for({"slug": record["slug"], "area": word, "context": word},
                                                                            {"workspaces": spaces})
        return found.get("name") if any(found is ws for ws in spaces) and not found.get("default") else None

    def placed(self) -> list[dict]:
        """Every record with the area it counts for"""
        spaces = (read_config_file(self.app.root).get("workplace") or {}).get("workspaces") or []
        return [{**r, "area": self.record_area(r, spaces)} for r in work_find.records(self.app.root, RECORDS_ALL)["records"]]

    def records(self, person: str) -> dict:
        scope = self.scope(person)
        mine = [{k: v for k, v in r.items() if k in RECORD_FIELDS} for r in self.placed() if r["area"] and self.canon(r["area"]) in scope]
        return self.clean({"ok": True, "total": len(mine), "truncated": False, "records": mine})

    def record_open(self, person: str, slug: str, folder: str | None) -> bool:
        """Whether a person may read this file: the model lists it for them, or every folder it could mean is theirs"""
        if folder is None and f"task:{slug}" in self.visible(person):
            return True
        scope = self.scope(person)
        same = [r for r in self.placed() if r["slug"] == slug and (r["path"] == folder if folder else r["kind"] != "done")]
        return bool(same) and all(r["area"] and self.canon(r["area"]) in scope for r in same)

    def event(self, person: str, event: str, payload: Any) -> Any:
        """What one event becomes for a person, None for nothing"""
        scope = self.scope(person)
        if not scope or event not in PERSON_EVENTS:
            return None
        if event == "view":
            return self.model(payload, scope)
        if event == "workspaces":
            return self.workspaces(payload, scope)
        return self.loading(payload)

    def task(self, person: str, result: dict) -> dict:
        seen = self.visible(person)
        out = {**TASK_NEUTRAL, **{k: v for k, v in result.items() if k in TASK_FIELDS}}
        out["inbox"] = [i for i in out.get("inbox") or [] if f"inbox:{i.get('id')}" in seen]
        return self.clean(out)

    def inbox(self, result: dict) -> dict:
        out = {k: v for k, v in result.items() if k in INBOX_FIELDS}
        out["item"] = {k: v for k, v in (result.get("item") or {}).items() if k in INBOX_ITEM}
        return self.clean({**out, "events": [], "describe": None})

    # ------------------------------------------------------------ what a person may change

    def verb_ok(self, verb: Any) -> None:
        if not isinstance(verb, str) or verb not in PERSON_VERBS:
            raise ActionError(403, "not_yours", "this action is not open to you")

    def check(self, person: str, verb: str, clean: dict) -> None:
        targets: list[str] = []
        for name in PERSON_VERBS[verb]:
            value = clean.get(name)
            targets += [value] if isinstance(value, str) else list(value or [])
        seen = self.visible(person)
        if not targets or not all(t in seen for t in targets):
            raise ActionError(403, "not_yours", "this row is not in your workspaces")
        # closing a row also ends the asks folded into it (actions_work end_also): each of them has to be theirs as well
        for target in targets:
            found = self.app.collector.resolve(target) or {}
            also = (found.get("out") or {}).get("also_inbox") or []
            if not all(f"inbox:{a.get('id')}" in seen for a in also):
                raise ActionError(403, "not_yours", "this row is not in your workspaces")
