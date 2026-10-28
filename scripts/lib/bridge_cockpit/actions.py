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
from .. import work_find as wf
from . import model as m
from . import activity as act
from . import describe as dsc
from . import instruct as ins
from . import organize as og
from . import themes as thm
from .card_fields import validate_brief
from .config import TARGETS
from .agents import CONV_RE as AGENT_CONV_RE, MODES as AGENT_MODES, PEER_RE as AGENT_PEER_RE
from .quick import CONV_RE
from .relay import RELAY_ID_RE
from .history import REOPEN_AS
from .store import append_log
# every shared name stays importable from here (ActionError, SPEC, the patterns): callers never changed
from .actions_base import *  # noqa: F401,F403
from .actions_base import (ACCOUNT_STATUSES, ASK_HASH_RE, BOARD_DEFAULTS, BOARD_MODES, BY_CHOICES, CLOSE_REASONS, CMUX_VERBS, CONTROL_RE,
                           DROP_REASONS, INBOX_ID_RE, LAYOUT_VERBS, LOCAL_VERBS, NEEDS_CAP, PAGE_ID_RE, PRIORITIES,
                           READ_ONLY_VERBS, REASON_MAX, FINDING_KEY_RE, ROUTE_BY, ROW_REF_RE, ROW_STEP_RE, RUN_ID_RE, SESSION_ID_RE, SLUG_RE, SPEC, TAB_REF_RE,
                           STEP_MAX, TAB_STATES, TEAM_RE, TILE_ID_RE, TITLE_MAX, TOUR_HOW, UNDO_TOKEN_RE, URGENCIES, WORKER_REF_RE, WS_REF_RE,
                           ActionError, Ctx, bad_arg, check_date, check_key, check_text)
from .actions_chats import ChatVerbs
from .actions_launch import LaunchSteps
from .actions_pages import PageVerbs
from .actions_tabs import TabVerbs
from .actions_work import WorkVerbs

#: the verbs of Work through's rounds 3 and 4, refused with flow_off before their arguments are checked
FLOW_OFF_FIRST = frozenset({"flow_activity_summary", "flow_instruct", "flow_attach", "flow_merge"})
#: a folder of one record, as work_find.known_folders names it (a question to the records names them so)
RECORD_PATH_RE = re.compile(r"^work/(?:(?:tasks|streams)|done/[0-9]{4}-[0-9]{2})/[a-z0-9][a-z0-9-]{0,79}\Z")


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
    "finding_key": (FINDING_KEY_RE, "not a finding key"),
    "inbox_id": (INBOX_ID_RE, "not an inbox id"),
    "page_id": (PAGE_ID_RE, "not a page or section id"),
    "row_step": (ROW_STEP_RE, "not a step"),
    "undo_token": (UNDO_TOKEN_RE, "not an undo token"),
    "row_ref": (ROW_REF_RE, "not a row id"),
    "worker_ref": (WORKER_REF_RE, "not a job or machine name"),
    "relay_id": (RELAY_ID_RE, "not a relay id"),
    "ask_hash": (ASK_HASH_RE, "not a question hash"),
    "organize_id": (og.ID_RE, "not a proposal id"),
    "describe_id": (dsc.PROPOSAL_RE, "not a proposal id"),
    "theme_id": (thm.THEME_ID_RE, "not a theme id"),
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
    "themes_mode": (thm.MODES, "assign or regroup"),
    "by": (BY_CHOICES, "suggestion, batch or instruction"),
}


def _keys(actions: "Actions", value: Any, name: str, today: dt.date) -> list[str]:
    if not isinstance(value, list) or not 1 <= len(value) <= 50:
        raise bad_arg(name, "must be a list of 1 to 50 row keys")
    keys = [check_key(k, name) for k in value]
    if len(set(keys)) != len(keys):
        raise bad_arg(name, "duplicate keys")
    return keys


def _record_paths(actions: "Actions", value: Any, name: str, today: dt.date) -> list[str]:
    """The folders of a question to the records: 1 to ASK_FILES_MAX, each work/tasks|streams/<slug> or
    work/done/<month>/<slug>, each once"""
    if not isinstance(value, list) or not 1 <= len(value) <= wf.ASK_FILES_MAX:
        raise bad_arg(name, f"must be a list of 1 to {wf.ASK_FILES_MAX} folders")
    if not all(isinstance(x, str) and RECORD_PATH_RE.match(x) for x in value):
        raise bad_arg(name, "not a folder of a task")
    if len(set(value)) != len(value):
        raise bad_arg(name, "duplicate folders")
    return list(value)


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


def _reason(actions: "Actions", value: Any, name: str, today: dt.date) -> str:
    # why a task is shelved: one line, its blanks collapsed, refused when it does not fit, never cut
    if isinstance(value, str) and re.search(r"[\n\r\t]", value):
        raise bad_arg(name, "one line, no tabs")
    return " ".join(check_text(value, name, REASON_MAX).split())


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


def _theme_name(actions: "Actions", value: Any, name: str, today: dt.date) -> str:
    # a theme's name: one line of words, refused when it does not fit, never cut
    if isinstance(value, str) and re.search(r"[\n\r\t]", value):
        raise bad_arg(name, "one line, no tabs")
    text = " ".join(check_text(value, name, thm.NAME_MAX).split())
    if not text:
        raise bad_arg(name, "must not be empty")
    return text


def _attach_name(actions: "Actions", value: Any, name: str, today: dt.date) -> str:
    # the name a document is kept under: made safe (activity.safe_name), refused when nothing is left of it
    made = act.safe_name(value)
    if not made:
        raise bad_arg(name, "must be a file name")
    return made


def _attach_data(actions: "Actions", value: Any, name: str, today: dt.date) -> bytes:
    # the document itself: strict base64 of 1 byte up to cockpit.flow.attach.max_mb (activity.decode_data)
    return act.decode_data(value, act.block(actions.app, "attach")["max_mb"], name)


def _brief(actions: "Actions", value: Any, name: str, today: dt.date) -> dict:
    # what a person wrote for a brief: refused whole when the gate finds anything wrong, never cut
    if not isinstance(value, dict):
        raise bad_arg(name, "must be a brief: goal, story, acceptance")
    text = {k: v for k, v in value.items() if k not in ("by", "at", "basis", "edited")}
    clean, errors = validate_brief(text)
    if errors or clean is None:
        raise bad_arg(name, "; ".join(errors or ["goal: missing"])[:300])
    return clean


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
    "reason": _reason,
    "tab_name": _tab_name,
    "digit": _digit,
    "organize_items": _organize_items,
    "brief": _brief,
    "theme_name": _theme_name,
    # the sentence of the instruction line: line breaks folded into blanks, 1 to 600 characters (instruct.fold)
    "instruct_text": lambda actions, value, name, today: ins.fold(value, name),
    "attach_name": _attach_name,
    "attach_data": _attach_data,
    "record_paths": _record_paths,
}
ARG_KINDS = frozenset(PATTERN_KINDS) | frozenset(CHOICE_KINDS) | frozenset(SPECIAL_KINDS)
# the verbs after which the Activity tab's kept feeds stand: they change nothing a feed reads
KEEPS_FEEDS = READ_ONLY_VERBS | {"flow_instruct", "files_ask"}


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
                              inbox_key=it.get("key"), sources=["inbox"],
                              origin_raw=it.get("from") or None, inbox_kind=it.get("kind") or None)
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
            # a task the files view lists without a row (a backlog task, files_scope all) keeps its own title
            listed = next((t for t in (self.app.collector.all_tasks or self.app.collector.tasks or [])
                           if t.get("slug") == slug), None)
            row = m.task_row(slug, (listed or {}).get("title") or (listed or {}).get("label") or slug)
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
        # put off or decided under this key or under the row of Due it is (collector.twins): Show again takes it back
        hidden, dismissed, today = self.app.store.hidden(), self.app.store.dismissed(), self.today().isoformat()
        gone = any((hidden.get(k) or "") > today or k in dismissed for k in self.app.collector.twins(key))
        return {"row": row, "out": {"settle": list(m.SETTLE_OUTCOMES), "closable": False}, "hidden": gone}

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
        # the verbs of Work through's round 3 answer flow_off while the page is off, before their arguments are read:
        # a 400 for a bad argument would say the verb is there
        if verb in FLOW_OFF_FIRST and not act.flow_on(self.app):
            raise ActionError(409, "flow_off", act.TEXT[act._lang(self.app)]["off"])
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
        ctx.by = clean.pop("by", None)
        touched = self.touched(clean)
        try:
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
        finally:
            # what a verb names is read anew by the Activity tab (activity.py keeps a feed CACHE_MS); a plan of the
            # instruction line changes nothing
            if verb not in KEEPS_FEEDS and touched and getattr(self.app, "activity", None) is not None:
                self.app.activity.drop(touched)
        return self.finish(ctx)

    @staticmethod
    def touched(clean: dict) -> list[str]:
        """The row keys a verb names: its keys and key, a task by its slug, an inbox item by its id"""
        out = [k for k in clean.get("keys") or [] if isinstance(k, str)]
        if isinstance(clean.get("key"), str):
            out.append(clean["key"])
        if isinstance(clean.get("slug"), str):
            out.append(f"task:{clean['slug']}")
        if isinstance(clean.get("keep"), str):          # a merge: the task that stays, by its key or its slug
            out.append(clean["keep"] if ":" in clean["keep"] else f"task:{clean['keep']}")
        if isinstance(clean.get("id"), str) and INBOX_ID_RE.match(clean["id"]):
            out.append(f"inbox:{clean['id']}")
        return out

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
                ctx.extra["history"] = self.app.history.add(ctx.verb, ctx.history, by=ctx.by)
                ctx.extra["undo"] = [{"title": x["title"], "kind": x["kind"], "undo": x["undo"]}
                                     for x in ctx.history if x.get("undo")]
            if refused is not None:
                self.refused_after(ctx, refused)

    def audit(self, ctx: Ctx) -> None:
        exits = ",".join(str(s["exit"]) for s in ctx.steps) or "-"
        ok = all(s["ok"] for s in ctx.steps)
        self.audit_line(ctx.verb, ctx.subject, exits=exits, ok=ok, **({"by": ctx.by} if ctx.by else {}), **ctx.audit_extra)

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
        go = ctx.go if note else None
        if note:
            go = app.note(note, "ok" if ok else "bad", go)
        app.collector.rebuild()
        if ctx.reload == "delta":
            app.collector.request("delta", tasks=True)     # a verb may have moved or edited a task
        if ctx.tabs_delay is not None:
            app.tabs.schedule(ctx.tabs_delay)
        return {"ok": ok, "verb": ctx.verb, "note": note, "go": go, "steps": ctx.steps, "settled": ctx.settled,
                "reload": ctx.reload, "jump": ctx.jump, "relay": ctx.relay, "confirm": ctx.confirm, **ctx.extra}
