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
from typing import Any, Callable

from .. import model_route as mr
from . import model as m
from . import organize as og
from .config import TARGETS
from .agents import CONV_RE as AGENT_CONV_RE, MODES as AGENT_MODES, PEER_RE as AGENT_PEER_RE
from .quick import CONV_RE
from .relay import RELAY_ID_RE
from .history import REOPEN_AS
from .store import append_log
# every shared name stays importable from here (ActionError, SPEC, the patterns): callers never changed
from .actions_base import *  # noqa: F401,F403
from .actions_base import (ACCOUNT_STATUSES, ASK_HASH_RE, BOARD_DEFAULTS, BOARD_MODES, CLOSE_REASONS, CMUX_VERBS, CONTROL_RE,
                           DROP_REASONS, INBOX_ID_RE, LAYOUT_VERBS, LOCAL_VERBS, NEEDS_CAP, PAGE_ID_RE, PRIORITIES,
                           READ_ONLY_VERBS, ROUTE_BY, ROW_REF_RE, ROW_STEP_RE, RUN_ID_RE, SESSION_ID_RE, SLUG_RE, SPEC, TAB_REF_RE,
                           STEP_MAX, TAB_STATES, TEAM_RE, TILE_ID_RE, TITLE_MAX, TOUR_HOW, UNDO_TOKEN_RE, URGENCIES, WS_REF_RE, ActionError,
                           Ctx, bad_arg, check_date, check_key, check_text)
from .actions_chats import ChatVerbs
from .actions_launch import LaunchSteps
from .actions_pages import PageVerbs
from .actions_tabs import TabVerbs
from .actions_work import WorkVerbs


# The argument types of SPEC. Most are one pattern or one list of words with the message a refusal names;
# the rest have a check of their own. validate() raises LookupError for a kind that is in none of them.
PATTERN_KINDS: dict[str, tuple[re.Pattern, str]] = {
    "conv": (CONV_RE, "not a conversation id"),
    "tab_ref": (TAB_REF_RE, "not a tab ref"),
    "ws_ref": (WS_REF_RE, "not a workspace ref"),
    "peer": (AGENT_PEER_RE, "not a peer id"),
    "agent_conv": (AGENT_CONV_RE, "not a conversation id"),
    "slug": (SLUG_RE, "not a task slug"),
    "session_id": (SESSION_ID_RE, "not a session id"),
    "run_id": (RUN_ID_RE, "not a workflow run id"),
    "inbox_id": (INBOX_ID_RE, "not an inbox id"),
    "page_id": (PAGE_ID_RE, "not a page or section id"),
    "row_step": (ROW_STEP_RE, "not a step"),
    "undo_token": (UNDO_TOKEN_RE, "not an undo token"),
    "row_ref": (ROW_REF_RE, "not a row id"),
    "relay_id": (RELAY_ID_RE, "not a relay id"),
    "ask_hash": (ASK_HASH_RE, "not a question hash"),
    "organize_id": (og.ID_RE, "not a proposal id"),
}
_LAUNCH_MODELS = ("auto", *mr.MODELS)
_LAUNCH_EFFORTS = ("auto", "standard", *mr.EFFORTS)
CHOICE_KINDS: dict[str, tuple[tuple, str]] = {
    "launch_model": (_LAUNCH_MODELS, f"must be one of {', '.join(_LAUNCH_MODELS)}"),
    "launch_effort": (_LAUNCH_EFFORTS, f"must be one of {', '.join(_LAUNCH_EFFORTS)}"),
    "target": (TARGETS, "unknown target"),
    "handoff": (("tab", "control"), "tab or control"),
    "outcome": (m.SETTLE_OUTCOMES, "unknown outcome"),
    "drop_reason": (DROP_REASONS, "unknown reason"),
    "close_reason": (CLOSE_REASONS, "unknown reason"),
    "urgency": (URGENCIES, "unknown urgency"),
    "priority": (PRIORITIES, "unknown priority"),
    "a2a_mode": (AGENT_MODES, "question or task"),
    "reopen_as": (("doing", "backlog"), "doing or backlog"),
    "restore_as": (REOPEN_AS, " or ".join(REOPEN_AS)),
    "account_status": (ACCOUNT_STATUSES, "unknown status"),
    "board_mode": (BOARD_MODES, "off, mine or all"),
    "board_default": (BOARD_DEFAULTS, "off, mine, all or profile"),
    "route_by": (ROUTE_BY, f"must be one of {', '.join(ROUTE_BY)}"),
    "tab_state": (TAB_STATES, f"must be one of {', '.join(TAB_STATES)}"),
    "tour_how": (TOUR_HOW, "finished or skipped"),
}


def _keys(actions: "Actions", value: Any, name: str, today: dt.date) -> list[str]:
    if not isinstance(value, list) or not 1 <= len(value) <= 50:
        raise bad_arg(name, "must be a list of 1 to 50 row keys")
    keys = [check_key(k, name) for k in value]
    if len(set(keys)) != len(keys):
        raise bad_arg(name, "duplicate keys")
    return keys


def _settings(actions: "Actions", value: Any, name: str, today: dt.date) -> dict:
    # the deep check is the store's own (LaunchModel.save, Ticker.save); MAX_BODY already caps the size
    if not isinstance(value, dict) or not value:
        raise bad_arg(name, "must be an object of settings")
    return value


def _tile_ids(actions: "Actions", value: Any, name: str, today: dt.date) -> list:
    if not isinstance(value, list) or len(value) > 60:
        raise bad_arg(name, "must be a list of up to 60 tile ids")
    if not all(isinstance(x, str) and TILE_ID_RE.match(x) for x in value):
        raise bad_arg(name, "not a tile id")
    if len(set(value)) != len(value):
        raise bad_arg(name, "duplicate ids")
    return list(value)


def _bool(actions: "Actions", value: Any, name: str, today: dt.date) -> bool:
    if not isinstance(value, bool):
        raise bad_arg(name, "must be true or false")
    return value


def _team(actions: "Actions", value: Any, name: str, today: dt.date) -> str:
    if not isinstance(value, str) or not TEAM_RE.match(value):
        raise bad_arg(name, "not a team id")
    if not any(t["id"] == value for t in actions.app.collector.teams):
        raise bad_arg(name, "unknown team")
    return value


def _index(actions: "Actions", value: Any, name: str, today: dt.date) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value < 10000:
        raise bad_arg(name, "not a row index")
    return value


def _title(actions: "Actions", value: Any, name: str, today: dt.date) -> str:
    # a name as typed: refused when it does not fit, never cut (a cut name is not the one asked for)
    if isinstance(value, str) and re.search(r"[\n\t]", value):
        raise bad_arg(name, "one line, no tabs")
    return check_text(value, name, TITLE_MAX)


def _line(actions: "Actions", value: Any, name: str, today: dt.date) -> str:
    # one line of text (a next step): refused when it holds a line break or a tab, never cut
    if isinstance(value, str) and re.search(r"[\n\r\t]", value):
        raise bad_arg(name, "one line, no tabs")
    return check_text(value, name, STEP_MAX)


def _tab_name(actions: "Actions", value: Any, name: str, today: dt.date) -> str:
    # compared with the tab's name as it is, so never stripped
    if not isinstance(value, str) or not 1 <= len(value) <= 120 or "\x00" in value or CONTROL_RE.search(value):
        raise bad_arg(name, "must be a tab name of 1 to 120 characters")
    return value


def _digit(actions: "Actions", value: Any, name: str, today: dt.date) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 9:
        raise bad_arg(name, "must be a number from 1 to 9")
    return value


def _organize_items(actions: "Actions", value: Any, name: str, today: dt.date) -> list[str]:
    if (not isinstance(value, list) or not 1 <= len(value) <= og.MAX_ITEMS
            or not all(isinstance(x, str) and og.ITEM_ID_RE.match(x) for x in value)):
        raise bad_arg(name, f"must be a list of 1 to {og.MAX_ITEMS} item ids")
    if len(set(value)) != len(value):
        raise bad_arg(name, "an item is listed twice")
    return list(value)


SPECIAL_KINDS: dict[str, Callable[["Actions", Any, str, dt.date], Any]] = {
    "keys": _keys,
    "key": lambda actions, value, name, today: check_key(value, name),
    "launch_settings": _settings,
    "ticker_settings": _settings,
    "tile_ids": _tile_ids,
    "date": lambda actions, value, name, today: check_date(value, name, today),
    "text": lambda actions, value, name, today: check_text(value, name, 2000),
    # what the chat box takes (ASK_MAX on the page): a chat handed to a tab is not cut
    "long_text": lambda actions, value, name, today: check_text(value, name, 4000),
    "bool": _bool,
    "team": _team,
    "index": _index,
    "title": _title,
    "line": _line,
    "tab_name": _tab_name,
    "digit": _digit,
    "organize_items": _organize_items,
}
ARG_KINDS = frozenset(PATTERN_KINDS) | frozenset(CHOICE_KINDS) | frozenset(SPECIAL_KINDS)


class Actions(LaunchSteps, WorkVerbs, TabVerbs, ChatVerbs, PageVerbs):
    def __init__(self, app: Any):
        self.app = app
        self.write_lock = threading.Lock()
        self.acting: set[str] = set()      # section/row of a briefing.py act under way (actions_pages.py)
        self.acting_lock = threading.Lock()
        self.layout_lock = threading.Lock()
        self.control_starting = False  # a control tab is being opened (start_control, outside the write lock)
        self.proposals = og.Proposals(lambda: self.app.clock())

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
            if not SLUG_RE.match(slug):
                return None
            stream = (root / "work" / "streams" / slug / "STATUS.md").is_file()
            if not stream and not (root / "work" / "tasks" / slug / "STATUS.md").is_file():
                return None
            row = m.task_row(slug, slug)
            return {"row": row, "out": {"settle": list(m.SETTLE_OUTCOMES), "closable": not stream, "stream": stream},
                    "hidden": False}
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
            if kind not in ARG_KINDS:
                # a programming error, never a refusal: a kind without a check would let its value through
                raise LookupError(f"SPEC kind {kind!r} of {verb}.{name} has no check in validate()")
            # an optional text left empty is no text (the page sends its empty box along)
            if name not in args or args[name] is None or (not required and kind in ("text", "long_text") and args[name] == ""):
                if required:
                    raise bad_arg(name, "missing")
                continue
            value = args[name]
            if kind in PATTERN_KINDS:
                pattern, message = PATTERN_KINDS[kind]
                if not isinstance(value, str) or not pattern.fullmatch(value):
                    raise bad_arg(name, message)
                out[name] = value
            elif kind in CHOICE_KINDS:
                choices, message = CHOICE_KINDS[kind]
                if value not in choices:
                    raise bad_arg(name, message)
                out[name] = value
            else:
                out[name] = SPECIAL_KINDS[kind](self, value, name, today)
        return out

    # ------------------------------------------------------------ entry point

    def execute(self, verb: Any, args: Any) -> dict:
        clean = self.validate(verb, args)
        if verb in CMUX_VERBS and not self.app.runner.cmux:
            raise ActionError(503, "cmux_unavailable", "the cmux CLI is not available")
        if verb in NEEDS_CAP and NEEDS_CAP[verb] not in self.app.driver_caps():
            raise ActionError(503, "driver_cannot", f"the terminal driver cannot {NEEDS_CAP[verb]} a tab")
        ctx = Ctx(self, verb)
        ctx.subject = ",".join(clean.get("keys", [])) or clean.get("key") or clean.get("tab_ref") or clean.get("ws_ref") \
            or clean.get("proposal") or clean.get("relay_id") or clean.get("slug") or clean.get("id") or ""
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
        self.audit_line(ctx.verb, ctx.subject, exits=exits, ok=ok, **ctx.audit_extra)

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
