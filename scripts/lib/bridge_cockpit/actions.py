# SPDX-License-Identifier: MIT
"""Verbs of the cockpit: a fixed registry, strict argument checks, the mod's handlers.

The page sends `{verb, args}`; rows are addressed by their row key from the current model,
tabs by their ref, so the page never hands the server an inbox id or a slug. Every id
that ends up in an argv is checked again against its pattern, every argv element is a
list item of its own (no shell), free text goes after `--`. Write verbs run one at a
time and leave one line in audit.log (never a text, never the token). A slow subprocess
(a start, the layout snapshot) runs outside the write lock, and verbs that only touch
stores with their own locks never take it. The handlers are
ports of register.tsx (doIt, advise, launch, startRole, later, drop, closeDone, ...);
the verb table is contract section 4.2.
"""
from __future__ import annotations

import datetime as dt
import re
import sys
import threading
from typing import Any

from .. import model_route as mr
from . import model as m
from .agents import CONV_RE as AGENT_CONV_RE, MODES as AGENT_MODES, PEER_RE as AGENT_PEER_RE
from .quick import CONV_RE
from .relay import RELAY_ID_RE
from .history import REOPEN_AS
from .store import append_log
# every shared name stays importable from here (ActionError, SPEC, the patterns): callers never changed
from .actions_base import *  # noqa: F401,F403
from .actions_base import (ACCOUNT_STATUSES, BOARD_MODES, CLOSE_REASONS, CMUX_VERBS, DROP_REASONS, INBOX_ID_RE,
                           LAYOUT_VERBS, LOCAL_VERBS, NEEDS_CAP, PAGE_ID_RE, PRIORITIES, READ_ONLY_VERBS, ROW_REF_RE,
                           ROW_STEP_RE, SESSION_ID_RE, SLUG_RE, SPEC, TAB_REF_RE, TARGETS, TEAM_RE, TILE_ID_RE,
                           UNDO_TOKEN_RE, URGENCIES, ActionError, Ctx, bad_arg, check_date, check_key, check_text)
from .actions_chats import ChatVerbs
from .actions_launch import LaunchSteps
from .actions_pages import PageVerbs
from .actions_tabs import TabVerbs
from .actions_work import WorkVerbs


class Actions(LaunchSteps, WorkVerbs, TabVerbs, ChatVerbs, PageVerbs):
    def __init__(self, app: Any):
        self.app = app
        self.write_lock = threading.Lock()
        self.layout_lock = threading.Lock()
        self.control_starting = False  # a control tab is being opened (start_control, outside the write lock)

    # ------------------------------------------------------------ helpers

    @property
    def tx(self) -> dict:
        return self.app.tx

    def today(self) -> dt.date:
        return dt.date.fromisoformat(m.iso_date(self.app.clock()))

    def inbox(self, *args: str) -> list[str]:
        app = self.app
        return [sys.executable, app.runner.script("scripts/inbox.py"), "--root", str(app.root), "--by", "web", *args]

    def task_cmd(self, *args: str) -> list[str]:
        app = self.app
        return [sys.executable, app.runner.script("scripts/task.py"), "--root", str(app.root), *args]

    def cmux(self, *args: str) -> list[str]:
        if not self.app.runner.cmux:
            raise ActionError(503, "cmux_unavailable", "the cmux CLI is not available")
        return [self.app.runner.cmux, *args]

    def entry(self, key: str, field: str = "key") -> dict:
        found = self.app.collector.resolve(key) or self.page_entry(key)
        if not found:
            raise ActionError(409, "stale_row", "the row is no longer in the model", field)
        return found

    def page_entry(self, key: str) -> dict | None:
        """A row the Inbox or Tasks page lists but the briefing does not (it shows only the first few):
        built from the item itself, an inbox item only while it is active, a task only while its folder
        is under work/tasks/. Nothing is made up for anything else."""
        root = self.app.root
        if key.startswith("inbox:"):
            iid = key[6:]
            if not INBOX_ID_RE.match(iid):
                return None
            state = next((e.get("state") for e in self.app.inbox_listing() or []
                          if isinstance(e, dict) and e.get("id") == iid), None)
            # a put-off item ("runs on", later) still answers: done, unimportant, a task, open again
            if state not in ("open", "approved", "waiting", "deferred"):
                return None
            from .details import inbox_detail
            d = inbox_detail(root, iid, None)
            if not d:
                return None
            it = d["item"]
            row = m._base_row(title=it.get("summary") or iid, inbox_id=iid, gate=it.get("gate"), urgency=it.get("urgency"),
                              task=it.get("task") or None, has_action=bool(it.get("action_display")), inbox_state=state,
                              inbox_key=it.get("key"), sources=["inbox"])
            row["key"] = key
            return {"row": row, "out": {"settle": list(m.SETTLE_OUTCOMES), "closable": False}, "hidden": False}
        if key.startswith("item:"):
            return self.page_item_entry(key)
        if key.startswith("task:"):
            slug = key[5:]
            if not SLUG_RE.match(slug) or not (root / "work" / "tasks" / slug / "STATUS.md").is_file():
                return None
            row = m.task_row(slug, slug)
            return {"row": row, "out": {"settle": list(m.SETTLE_OUTCOMES), "closable": True}, "hidden": False}
        return None

    def page_item_entry(self, key: str) -> dict | None:
        """A row of the Status, Dates, Trackers or More page, handed on like any other: built from the item as
        the briefing shows it now (None once it is gone), and only when its section calls it actionable"""
        found = self.app.collector.page_item_by_key(key)
        if not found:
            return None
        pg, sec, it = found
        if it.get("actionable") is not True:
            raise self.not_applicable("a person has nothing to do on this row")
        profile = self.app.collector.view_profile() or ""
        url = it.get("url") if isinstance(it.get("url"), str) and re.match(r"https?://", it["url"]) else None
        # an id of the source lets the briefing's own sweep close the item once the row is gone; a hash cannot
        inbox_key = f"briefing:{profile}:{sec['id']}:{it['id']}" if it.get("id") and profile else None
        row = m._base_row(title=it["title"], url=url, sources=[sec.get("title") or sec["id"]],
                          page_item={"section": sec.get("title") or sec["id"], "detail": it.get("detail") or "",
                                     "inbox_key": inbox_key, "row": f":{sec['id']}:{it['id']}" if it.get("id") else None})
        row["key"] = key
        hidden = (self.app.store.hidden().get(key) or "") > self.today().isoformat()
        return {"row": row, "out": {"settle": list(m.SETTLE_OUTCOMES), "closable": False}, "hidden": hidden}

    def entries(self, keys: list[str]) -> list[dict]:
        return [self.entry(k, "keys") for k in keys]

    def tab(self, ref: str) -> dict:
        tab = self.app.tabs.find(ref)
        if not tab:
            raise ActionError(409, "stale_tab", "the tab is no longer in the tab list", "tab_ref")
        if not TAB_REF_RE.match(tab["ref"] or ""):
            raise ActionError(409, "not_applicable", "the tab has no valid refs", "tab_ref")
        return tab

    @staticmethod
    def not_applicable(message: str, field: str | None = "key") -> ActionError:
        return ActionError(409, "not_applicable", message, field)

    @staticmethod
    def inbox_id(row: dict) -> str:
        value = row.get("inbox_id")
        if not isinstance(value, str) or not INBOX_ID_RE.match(value):
            raise ActionError(409, "not_applicable", "the inbox id fails validation", "key")
        return value

    @staticmethod
    def slug(row: dict) -> str:
        value = row.get("task")
        if not isinstance(value, str) or not SLUG_RE.match(value):
            raise ActionError(409, "not_applicable", "the task slug fails validation", "key")
        return value

    def validate(self, verb: Any, args: Any) -> dict:
        if not isinstance(verb, str) or verb not in SPEC:
            raise ActionError(400, "unknown_verb", "unknown verb", "verb")
        if args is None:
            args = {}
        if not isinstance(args, dict):
            raise bad_arg("args", "must be an object")
        spec = SPEC[verb]
        for name in args:
            if name not in spec:
                raise bad_arg(str(name)[:40], "unknown argument")
        out: dict[str, Any] = {}
        today = self.today()
        for name, (kind, required) in spec.items():
            # an optional text left empty is no text (the page sends its empty box along)
            if name not in args or args[name] is None or (not required and kind in ("text", "long_text") and args[name] == ""):
                if required:
                    raise bad_arg(name, "missing")
                continue
            value = args[name]
            if kind == "keys":
                if not isinstance(value, list) or not 1 <= len(value) <= 50:
                    raise bad_arg(name, "must be a list of 1 to 50 row keys")
                keys = [check_key(k, name) for k in value]
                if len(set(keys)) != len(keys):
                    raise bad_arg(name, "duplicate keys")
                out[name] = keys
            elif kind == "key":
                out[name] = check_key(value, name)
            elif kind in ("launch_model", "launch_effort"):
                allowed = ("auto", *mr.MODELS) if kind == "launch_model" else ("auto", "standard", *mr.EFFORTS)
                if value not in allowed:
                    raise bad_arg(name, f"must be one of {', '.join(allowed)}")
                out[name] = value
            elif kind == "launch_settings":
                if not isinstance(value, dict) or not value:
                    raise bad_arg(name, "must be an object of settings")
                out[name] = value
            elif kind == "ticker_settings":
                # the deep check is Ticker.save's; MAX_BODY already caps the size
                if not isinstance(value, dict) or not value:
                    raise bad_arg(name, "must be an object of settings")
                out[name] = value
            elif kind == "tile_ids":
                if not isinstance(value, list) or len(value) > 60:
                    raise bad_arg(name, "must be a list of up to 60 tile ids")
                if not all(isinstance(x, str) and TILE_ID_RE.match(x) for x in value):
                    raise bad_arg(name, "not a tile id")
                if len(set(value)) != len(value):
                    raise bad_arg(name, "duplicate ids")
                out[name] = list(value)
            elif kind == "target":
                if value not in TARGETS:
                    raise bad_arg(name, "unknown target")
                out[name] = value
            elif kind == "date":
                out[name] = check_date(value, name, today)
            elif kind == "conv":
                if not isinstance(value, str) or not CONV_RE.match(value):
                    raise bad_arg(name, "not a conversation id")
                out[name] = value
            elif kind == "handoff":
                if value not in ("tab", "control"):
                    raise bad_arg(name, "tab or control")
                out[name] = value
            elif kind == "outcome":
                if value not in m.SETTLE_OUTCOMES:
                    raise bad_arg(name, "unknown outcome")
                out[name] = value
            elif kind == "drop_reason":
                if value not in DROP_REASONS:
                    raise bad_arg(name, "unknown reason")
                out[name] = value
            elif kind == "close_reason":
                if value not in CLOSE_REASONS:
                    raise bad_arg(name, "unknown reason")
                out[name] = value
            elif kind == "urgency":
                if value not in URGENCIES:
                    raise bad_arg(name, "unknown urgency")
                out[name] = value
            elif kind == "priority":
                if value not in PRIORITIES:
                    raise bad_arg(name, "unknown priority")
                out[name] = value
            elif kind == "text":
                out[name] = check_text(value, name, 2000)
            elif kind == "long_text":
                # what the chat box takes (ASK_MAX on the page): a chat handed to a tab is not cut
                out[name] = check_text(value, name, 4000)
            elif kind == "bool":
                if not isinstance(value, bool):
                    raise bad_arg(name, "must be true or false")
                out[name] = value
            elif kind == "team":
                if not isinstance(value, str) or not TEAM_RE.match(value):
                    raise bad_arg(name, "not a team id")
                if not any(t["id"] == value for t in self.app.collector.teams):
                    raise bad_arg(name, "unknown team")
                out[name] = value
            elif kind == "tab_ref":
                if not isinstance(value, str) or not TAB_REF_RE.match(value):
                    raise bad_arg(name, "not a tab ref")
                out[name] = value
            elif kind == "peer":
                if not isinstance(value, str) or not AGENT_PEER_RE.match(value):
                    raise bad_arg(name, "not a peer id")
                out[name] = value
            elif kind == "agent_conv":
                if not isinstance(value, str) or not AGENT_CONV_RE.match(value):
                    raise bad_arg(name, "not a conversation id")
                out[name] = value
            elif kind == "a2a_mode":
                if value not in AGENT_MODES:
                    raise bad_arg(name, "question or task")
                out[name] = value
            elif kind == "slug":
                if not isinstance(value, str) or not SLUG_RE.match(value):
                    raise bad_arg(name, "not a task slug")
                out[name] = value
            elif kind == "session_id":
                if not isinstance(value, str) or not SESSION_ID_RE.fullmatch(value):
                    raise bad_arg(name, "not a session id")
                out[name] = value
            elif kind == "inbox_id":
                if not isinstance(value, str) or not INBOX_ID_RE.match(value):
                    raise bad_arg(name, "not an inbox id")
                out[name] = value
            elif kind == "reopen_as":
                if value not in ("doing", "backlog"):
                    raise bad_arg(name, "doing or backlog")
                out[name] = value
            elif kind == "restore_as":
                if value not in REOPEN_AS:
                    raise bad_arg(name, " or ".join(REOPEN_AS))
                out[name] = value
            elif kind == "page_id":
                if not isinstance(value, str) or not PAGE_ID_RE.match(value):
                    raise bad_arg(name, "not a page or section id")
                out[name] = value
            elif kind == "index":
                if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value < 10000:
                    raise bad_arg(name, "not a row index")
                out[name] = value
            elif kind == "account_status":
                if value not in ACCOUNT_STATUSES:
                    raise bad_arg(name, "unknown status")
                out[name] = value
            elif kind == "board_mode":
                if value not in BOARD_MODES:
                    raise bad_arg(name, "off, mine or all")
                out[name] = value
            elif kind == "row_step":
                if not isinstance(value, str) or not ROW_STEP_RE.match(value):
                    raise bad_arg(name, "not a step")
                out[name] = value
            elif kind == "undo_token":
                if not isinstance(value, str) or not UNDO_TOKEN_RE.match(value):
                    raise bad_arg(name, "not an undo token")
                out[name] = value
            elif kind == "row_ref":
                if not isinstance(value, str) or not ROW_REF_RE.match(value):
                    raise bad_arg(name, "not a row id")
                out[name] = value
            elif kind == "relay_id":
                if not isinstance(value, str) or not RELAY_ID_RE.match(value):
                    raise bad_arg(name, "not a relay id")
                out[name] = value
        return out

    # ------------------------------------------------------------ entry point

    def execute(self, verb: Any, args: Any) -> dict:
        clean = self.validate(verb, args)
        if verb in CMUX_VERBS and not self.app.runner.cmux:
            raise ActionError(503, "cmux_unavailable", "the cmux CLI is not available")
        if verb in NEEDS_CAP and NEEDS_CAP[verb] not in self.app.driver_caps():
            raise ActionError(503, "driver_cannot", f"the terminal driver cannot {NEEDS_CAP[verb]} a tab")
        ctx = Ctx(self, verb)
        ctx.subject = ",".join(clean.get("keys", [])) or clean.get("key") or clean.get("tab_ref") or clean.get("relay_id") \
            or clean.get("slug") or clean.get("id") or ""
        handler = getattr(self, f"v_{verb}")
        ctx.pick = {k: clean.pop(k) for k in ("model", "effort") if k in clean}
        if verb in READ_ONLY_VERBS:
            handler(ctx, **clean)
        elif verb in LOCAL_VERBS:
            self.recorded(ctx, handler, clean)
        elif verb in LAYOUT_VERBS:
            with self.layout_lock:
                self.recorded(ctx, handler, clean)
        else:
            with self.write_lock:
                ctx.locked = True
                self.recorded(ctx, handler, clean)
        return self.finish(ctx)

    def refused_after(self, ctx: Ctx, error: ActionError) -> None:
        """A refusal that follows a step that wrote: the page still gets what to take back, and the model
        is built again, as finish() would have done"""
        if not (ctx.history or ctx.settled):
            return
        error.extra = {"settled": ctx.settled, **{k: ctx.extra[k] for k in ("history", "undo") if k in ctx.extra}}
        self.app.collector.rebuild()

    def recorded(self, ctx: Ctx, handler: Any, clean: dict) -> None:
        """A write: the handler, then its audit line and its history entry, whatever it raised."""
        refused = None
        try:
            handler(ctx, **clean)
        except ActionError as error:
            refused = error
            raise
        finally:
            if ctx.steps or ctx.notes or ctx.settled:
                self.audit(ctx)
            if ctx.history and getattr(self.app, "history", None) is not None:
                ctx.extra["history"] = self.app.history.add(ctx.verb, ctx.history)
                ctx.extra["undo"] = [{"title": x["title"], "kind": x["kind"], "undo": x["undo"]}
                                     for x in ctx.history if x.get("undo")]
            if refused is not None:
                self.refused_after(ctx, refused)

    def audit(self, ctx: Ctx) -> None:
        exits = ",".join(str(s["exit"]) for s in ctx.steps) or "-"
        ok = all(s["ok"] for s in ctx.steps)
        self.audit_line(ctx.verb, ctx.subject, exits=exits, ok=ok)

    def audit_line(self, verb: str, subject: str = "", **fields: Any) -> None:
        """One line in audit.log: time, verb, subject, then key=value. The one writer of that file, for
        /api/action as for ask, route, jev and triage; callers pass ids and counts, never a text or a key."""
        now = dt.datetime.fromtimestamp(self.app.clock() / 1000).isoformat(timespec="seconds")
        flat = lambda v: str(v).lower() if isinstance(v, bool) else re.sub(r"\s+", "_", str(v))[:120] or "-"  # noqa: E731
        subject = re.sub(r"\s+", " ", subject).strip()[:600].replace(" ", "_") or "-"
        tail = "".join(f" {k}={flat(v)}" for k, v in fields.items())
        append_log(self.app.state_dir / "audit.log", f"{now} {verb} {subject}{tail}")

    def finish(self, ctx: Ctx) -> dict:
        app = self.app
        ok = all(s["ok"] for s in ctx.steps) and not ctx.failed
        note = app.scrub(" · ".join(n for n in ctx.notes if n))
        if note:
            app.note(note, "ok" if ok else "bad")
        app.collector.rebuild()
        if ctx.reload == "delta":
            app.collector.request("delta", tasks=True)     # a verb may have moved or edited a task
        if ctx.tabs_delay is not None:
            app.tabs.schedule(ctx.tabs_delay)
        return {"ok": ok, "verb": ctx.verb, "note": note, "steps": ctx.steps, "settled": ctx.settled,
                "reload": ctx.reload, "jump": ctx.jump, "relay": ctx.relay, "confirm": ctx.confirm, **ctx.extra}
