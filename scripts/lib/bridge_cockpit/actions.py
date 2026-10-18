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

import contextlib
import datetime as dt
import json
import re
import uuid
import sys
import threading
from typing import Any

from .. import model_route as mr
from . import asks as ak
from . import model as m
from . import returns as ret
from .collector import START_HOLD_MS
from .agents import CONV_RE as AGENT_CONV_RE, MODES as AGENT_MODES, PEER_RE as AGENT_PEER_RE
from .quick import CONV_RE, DEFAULT_MODEL, MODELS
from .relay import KINDS as ASK_KINDS, RELAY_ID_RE
from .details import split_front
from .history import REOPEN_AS, item as history_item
from .launch import LaunchError
from .ticker import TickerError
from .store import append_log

ACTIVE_INBOX_STATES = ("open", "approved", "waiting", "deferred")
ROW_KEY_RE = re.compile(r"^(inbox|task|ref|title|item):.{1,240}\Z")
INBOX_ID_RE = re.compile(r"^[0-9]{8}-[0-9]{4}-[a-z0-9][a-z0-9-]{0,119}\Z")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}\Z")
SESSION_ID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
# a tab is the terminal driver's own name for it (surface:3 in cmux, %3 in tmux), passed as one argv word
TAB_REF_RE = re.compile(r"^[A-Za-z0-9%][A-Za-z0-9:%_.@/-]{0,63}\Z")
# a workspace the same way (workspace:2 in cmux, $2 in tmux)
WS_REF_RE = re.compile(r"^[A-Za-z0-9$%@][A-Za-z0-9:%_.@$/-]{0,63}\Z")
TITLE_MAX = 80
TEAM_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}\Z")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\Z")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
URGENCIES = ("now", "today", "later")
PRIORITIES = ("P0", "P1", "P2", "P3")
TARGETS = ("tab", "workspace", "area", "auto")
# why a task closes; `auto` (the overview's bulk close) takes it from the check: stale closes as declined
CLOSE_REASONS = ("done", "not_doing", "superseded", "elsewhere", "auto")
DECLINED_REASONS = frozenset({"not_doing", "superseded"})
# why an inbox item is dropped (inbox.py DROP_REASONS); family and source leave a mute rule behind
DROP_REASONS = ("once", "duplicate", "family", "source")
# a quick chat handed on: what reaches the inbox item or the control session, and the most the order
# typed on handing on may take of it, so some of the conversation always comes along
HANDOFF_MAX = 3500
HANDOFF_ORDER_MAX = 3000

SHORT_TIMEOUT = 30
LAUNCH_TIMEOUT = 150
CMUX_TIMEOUT = 10
STATUS_TIMEOUT = 20
SNAPSHOT_TIMEOUT = 180
LIST_TIMEOUT = 20

# verb -> {arg: (type, required)}
SPEC: dict[str, dict[str, tuple[str, bool]]] = {
    "do_it": {"keys": ("keys", True), "target": ("target", False), "model": ("launch_model", False), "effort": ("launch_effort", False)},
    "advise": {"keys": ("keys", True), "model": ("launch_model", False), "effort": ("launch_effort", False)},
    "start_agent": {"keys": ("keys", True), "model": ("launch_model", False), "effort": ("launch_effort", False)},
    "collect_context": {"key": ("key", True), "model": ("launch_model", False), "effort": ("launch_effort", False)},
    "later": {"key": ("key", True), "until": ("date", True)},
    "hide": {"key": ("key", True), "until": ("date", True)},
    "unhide": {"key": ("key", True)},
    "drop": {"key": ("key", True), "reason": ("drop_reason", False)},
    "inbox_unmute": {"id": ("inbox_id", True)},
    "done": {"key": ("key", True)},
    "urgency": {"key": ("key", True), "value": ("urgency", True)},
    "priority": {"key": ("key", True), "value": ("priority", True)},
    "task_close": {"keys": ("keys", True), "reason": ("close_reason", True), "text": ("text", False)},
    "settle": {"keys": ("keys", True), "outcome": ("outcome", True), "text": ("text", False)},
    "quick_handoff": {"conv": ("conv", True), "to": ("handoff", True), "text": ("long_text", False), "model": ("launch_model", False), "effort": ("launch_effort", False)},
    "quick_forget": {"conv": ("conv", True)},
    "chat_tab": {"text": ("long_text", True), "model": ("launch_model", False), "effort": ("launch_effort", False)},
    "task_review": {"keys": ("keys", False), "escalate": ("bool", False), "fresh": ("bool", False)},
    "task_keep": {"keys": ("keys", True)},
    "note": {"key": ("key", True), "text": ("text", True)},
    "approve_all": {"keys": ("keys", True), "confirm": ("bool", False)},
    "team_role": {"key": ("key", True), "team": ("team", True), "model": ("launch_model", False), "effort": ("launch_effort", False)},
    "adopt": {"key": ("key", True), "tab_ref": ("tab_ref", True)},
    # a reply may name the question it answers (seen: its hash), the tab's name and the state it expects;
    # the server checks them against the tab as it is now before anything reaches it (guard_fresh)
    "tab_yes": {"tab_ref": ("tab_ref", True), "seen": ("ask_hash", False), "name": ("tab_name", False)},
    "tab_no": {"tab_ref": ("tab_ref", True), "seen": ("ask_hash", False), "name": ("tab_name", False)},
    "tab_option": {"tab_ref": ("tab_ref", True), "n": ("digit", True), "seen": ("ask_hash", True), "name": ("tab_name", False)},
    "tab_jump": {"tab_ref": ("tab_ref", True)},
    "tab_send": {"tab_ref": ("tab_ref", True), "text": ("text", True), "seen": ("ask_hash", False),
                 "expect": ("tab_state", False), "name": ("tab_name", False)},
    "tab_go_on": {"tab_ref": ("tab_ref", True), "seen": ("ask_hash", False), "name": ("tab_name", False)},
    "tab_close": {"tab_ref": ("tab_ref", True)},
    # a name of a tab or a workspace; task tabs and configured workspaces keep theirs (workplace.py managed_names)
    "tab_rename": {"tab_ref": ("tab_ref", True), "title": ("title", True)},
    "workspace_rename": {"ws_ref": ("ws_ref", True), "title": ("title", True)},
    "snapshot": {},
    "home_tiles": {"ids": ("tile_ids", True), "seen": ("tile_ids", False)},
    "pin": {"key": ("key", True), "on": ("bool", True)},
    "return_forget": {"key": ("key", True)},
    "start_control": {},
    "snapshot_list": {},
    "ask_via_tab": {"relay_id": ("relay_id", True)},
    "a2a_ask": {"peer": ("peer", True), "text": ("text", True), "conv": ("agent_conv", False), "mode": ("a2a_mode", False)},
    "a2a_poll": {"conv": ("agent_conv", True)},
    "a2a_forget": {"conv": ("agent_conv", True)},
    "task_reopen": {"slug": ("slug", True), "as": ("restore_as", False), "note": ("text", False)},
    "row_action": {"page": ("page_id", True), "section": ("page_id", True), "index": ("index", True),
                   "action": ("row_step", True)},
    "row_undo": {"section": ("page_id", True), "row": ("row_ref", True), "action": ("undo_token", True)},
    "inbox_reopen": {"id": ("inbox_id", True), "note": ("text", False)},
    "runs_on": {"keys": ("keys", True), "until": ("date", True), "on": ("text", False)},
    "task_running": {"slug": ("slug", True)},
    "to_task": {"key": ("key", True), "status": ("reopen_as", False)},
    "session_link": {"session": ("session_id", True), "slug": ("slug", True)},
    "session_unlink": {"session": ("session_id", True)},
    "session_resume": {"session": ("session_id", True), "model": ("launch_model", False), "effort": ("launch_effort", False)},
    "launch_settings": {"settings": ("launch_settings", True)},
    "launch_settings_reset": {},
    "ticker_settings": {"settings": ("ticker_settings", True)},
    "ticker_settings_reset": {},
    "ticker_refresh": {},
    "ticker_edit": {},
    "ticker_profile": {"llm": ("bool", False)},
    "account_status": {"page": ("page_id", True), "section": ("page_id", True), "index": ("index", True),
                       "status": ("account_status", True)},
    "github_board": {"section": ("page_id", True), "slug": ("page_id", True), "mode": ("board_mode", True)},
}
BOARD_MODES = ("off", "mine", "all")
ACCOUNT_STATUSES = ("active", "paused", "disabled")
# a command row's own step and the undo token it returns (the same rules as briefing.py act)
ROW_STEP_RE = re.compile(r"^[a-z][a-z0-9_-]{0,39}\Z")
UNDO_TOKEN_RE = re.compile(r"^restore:[A-Za-z0-9._~-]{1,120}\Z")
ROW_REF_RE = re.compile(r"^[A-Za-z0-9][^\x00-\x1f]{0,199}\Z")
PAGE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}\Z")
ASK_HASH_RE = re.compile(r"^[0-9a-f]{16}\Z")   # the hash of a tab's question (asks.py)
TAB_STATES = ("needs-you", "waiting", "working")
TILE_ID_RE = re.compile(r"^[A-Za-z0-9@][A-Za-z0-9:._@/-]{0,79}\Z")   # a tile or shelf of the start page
READ_ONLY_VERBS = frozenset({"snapshot_list"})
# only stores with their own locks (store.py, launch.py, ticker.py): they never wait for a write that runs
LOCAL_VERBS = frozenset({"pin", "hide", "home_tiles", "ticker_settings", "ticker_settings_reset", "launch_settings",
                         "launch_settings_reset", "session_link"})
# the layout snapshot writes nothing of the Bridge: one at a time on a lock of its own, never the write lock
LAYOUT_VERBS = frozenset({"snapshot"})
# saving the layout is cmux's own feature; steering a tab goes through the terminal driver and needs its verb
CMUX_VERBS = frozenset({"snapshot", "snapshot_list"})
NEEDS_CAP = {"tab_yes": "key", "tab_no": "key", "tab_option": "key", "tab_jump": "focus", "tab_close": "close",
             "tab_rename": "rename", "workspace_rename": "rename_workspace"}


class ActionError(Exception):
    def __init__(self, status: int, code: str, message: str, field: str | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.field = status, code, message, field
        self.extra: dict = {}   # what a refused action had written before: settled rows, undo, history


def bad_arg(field: str, message: str) -> ActionError:
    return ActionError(400, "invalid_argument", message, field)


def check_text(value: Any, field: str, max_len: int) -> str:
    if not isinstance(value, str):
        raise bad_arg(field, "must be a string")
    if "\x00" in value or CONTROL_RE.search(value):
        raise bad_arg(field, "control characters are not allowed")
    text = value.strip()
    if not 1 <= len(text) <= max_len:
        raise bad_arg(field, f"length must be 1 to {max_len}")
    return text


def check_date(value: Any, field: str, today: dt.date) -> str:
    if not isinstance(value, str) or not DATE_RE.match(value):
        raise bad_arg(field, "must be YYYY-MM-DD")
    try:
        day = dt.date.fromisoformat(value)
    except ValueError:
        raise bad_arg(field, "not a calendar date") from None
    if not today < day <= today + dt.timedelta(days=366):
        raise bad_arg(field, "must be after today and within 366 days")
    return value


def check_key(value: Any, field: str) -> str:
    if not isinstance(value, str) or not ROW_KEY_RE.match(value):
        raise bad_arg(field, "not a row key")
    return value


class Ctx:
    """What one action did: steps, notes, settled rows, follow-ups."""

    def __init__(self, actions: "Actions", verb: str):
        self.actions = actions
        self.verb = verb
        self.steps: list[dict] = []
        self.notes: list[str] = []
        self.failed = False
        self.settled: list[str] = []
        self.reload = "none"
        self.tabs_delay: float | None = None
        self.jump: dict | None = None
        self.relay: dict | None = None
        self.confirm: dict | None = None
        self.extra: dict = {}          # verb specific answer fields (a conversation id)
        self.history: list[dict] = []  # what this action closed, hid or settled, each with its undo
        self.subject = ""
        self.pick: dict = {}           # the model and effort the start of this action asks for (launch.py)
        self.locked = False            # this action holds the write lock

    @contextlib.contextmanager
    def unlocked(self):
        """The slow part of a verb (a subprocess) without the write lock; what it must keep for itself (the
        hold on a starting item) it takes under the lock before, the rest it does under the lock after."""
        if not self.locked:
            yield
            return
        self.actions.write_lock.release()
        try:
            yield
        finally:
            self.actions.write_lock.acquire()

    def call(self, name: str, subject: str, argv: list[str], timeout: float):
        run = self.actions.app.run(argv, timeout)
        self.steps.append({"call": name, "subject": subject, "ok": run.ok, "exit": run.code, "took_ms": run.took_ms,
                           "err": self.actions.app.scrub(run.err or "")[-300:]})
        return run

    def note(self, text: str, bad: bool = False) -> None:
        if text:
            self.notes.append(text)
        self.failed = self.failed or bad

    def delta(self) -> None:
        self.reload = "delta"

    def tabs_after(self, delay: float) -> None:
        self.tabs_delay = delay if self.tabs_delay is None else min(self.tabs_delay, delay)
        if self.reload == "none":
            self.reload = "tabs"


class Actions:
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
            elif kind == "ws_ref":
                if not isinstance(value, str) or not WS_REF_RE.match(value):
                    raise bad_arg(name, "not a workspace ref")
                out[name] = value
            elif kind == "title":
                # a name as typed: refused when it does not fit, never cut (a cut name is not the one asked for)
                if isinstance(value, str) and re.search(r"[\n\t]", value):
                    raise bad_arg(name, "one line, no tabs")
                out[name] = check_text(value, name, TITLE_MAX)
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
            elif kind == "ask_hash":
                if not isinstance(value, str) or not ASK_HASH_RE.match(value):
                    raise bad_arg(name, "not a question hash")
                out[name] = value
            elif kind == "tab_state":
                if value not in TAB_STATES:
                    raise bad_arg(name, f"must be one of {', '.join(TAB_STATES)}")
                out[name] = value
            elif kind == "tab_name":
                # compared with the tab's name as it is, so never stripped
                if not isinstance(value, str) or not 1 <= len(value) <= 120 or "\x00" in value or CONTROL_RE.search(value):
                    raise bad_arg(name, "must be a tab name of 1 to 120 characters")
                out[name] = value
            elif kind == "digit":
                if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 9:
                    raise bad_arg(name, "must be a number from 1 to 9")
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
        ctx.subject = ",".join(clean.get("keys", [])) or clean.get("key") or clean.get("tab_ref") or clean.get("ws_ref") \
            or clean.get("relay_id") or clean.get("slug") or clean.get("id") or ""
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

    # ------------------------------------------------------------ shared pieces (register.tsx)

    def settle(self, ctx: Ctx, row: dict, text: str) -> None:
        self.app.collector.settle(row["key"], text)
        ctx.settled.append(row["key"])
        ctx.note(f"{text}: {m.short(row['title'], 60)}")
        ctx.delta()

    def approve(self, ctx: Ctx, row: dict) -> bool:
        item = self.inbox_id(row)
        run = ctx.call("inbox.approve", item, self.inbox("approve", item), SHORT_TIMEOUT)
        if not run.ok:
            ctx.note(self.tx["approve_failed"].format(err=m.short(run.err, 100)), bad=True)
            return False
        # It runs on the machine that is the inbox runner, at the next pass; never `inbox.py run` from here.
        # Until then the yes can be taken back from the history (inbox reopen clears it).
        ctx.history.append(history_item(row["key"], row["title"], "inbox", "approved", item))
        self.settle(ctx, row, self.tx["approved_note"])
        return True

    def hide_until(self, ctx: Ctx, row: dict, until: str) -> None:
        self.app.store.hide(row["key"], until)
        ctx.history.append(history_item(row["key"], row["title"], "other", f"hidden until {until}"))
        ctx.note(self.tx["hidden_note"].format(until=until, title=m.short(row["title"], 60)))

    def jump_to(self, ctx: Ctx, tab: dict) -> bool:
        ref = tab["ref"]
        if not TAB_REF_RE.match(ref or ""):
            return False
        run = ctx.call("workplace.focus", ref, self.app.workplace("focus", ref), CMUX_TIMEOUT)
        if not run.ok:
            ctx.note(self.tx["jump_failed"].format(err=m.short((run.err or run.out).strip(), 100)), bad=True)
            return False
        return True

    def launch(self, ctx: Ctx, rows: list[dict], mode: str, target: str, team: dict | None = None,
               word: str | None = None, resume: dict | None = None) -> str:
        """register.tsx launch: returns started | partly | failed | running | busy | nothing | manual (no driver)."""
        tx, app = self.tx, self.app
        wanted = [m.launch_item(r) for r in rows if m.launch_item(r)]
        if not wanted:
            ctx.note(tx["nothing_to_start"])
            return "nothing"
        for item in wanted:
            if not (INBOX_ID_RE.match(item) or SLUG_RE.match(item)):
                raise self.not_applicable("a launch item fails validation")
        busy = app.collector.starting_items()
        items = [x for x in dict.fromkeys(wanted) if x not in busy]
        for row in rows:
            if m.launch_item(row) in busy:
                ctx.note(tx["starting_already"].format(title=m.short(row["title"], 40)))
        if not items:
            return "busy"
        here = None
        if target == "tab":
            control = app.tabs.control_tab()
            if control and TAB_REF_RE.match(control["ref"]):
                here = control["ref"]
            else:
                target = "area"
                ctx.note(tx["here_missing"])
        argv = app.workplace("launch", "--items", ",".join(items), "--mode", mode, "--target", target, "--yes", "--json")
        if here:
            argv += ["--here", here]
        if team:
            argv += ["--team", team["id"], "--role", team["role"]]
        if resume:
            argv += ["--resume", resume["sid"], *(["--cwd", resume["cwd"]] if resume.get("cwd") else [])]
        chosen = app.launch_model.pick(rows, ctx.pick.get("model"), ctx.pick.get("effort")) \
            if getattr(app, "launch_model", None) is not None else None
        if chosen:
            argv += ["--model", chosen["model"], *(["--effort", chosen["effort"]] if chosen["effort"] else [])]
        word = word or (tx["launch_team"].format(role=team["name"]) if team else tx["btn_do"] if mode == "go"
                else tx["launch_context"] if mode == "context" else tx["btn_advise"])
        areas = list(dict.fromkeys(r.get("area") for r in rows if m.launch_item(r) in items and r.get("area")))
        where = tx["where_area"].format(name=areas[0]) if target == "area" and len(areas) == 1 else tx["where"][target]
        app.collector.hold(items)
        app.collector.rebuild()
        app.note(tx["launch_start"].format(word=word, n=len(items), where=where), "info")
        with ctx.unlocked():    # the items are held: a second start of them is refused as starting_already
            run = ctx.call("workplace.launch", ",".join(items), argv, LAUNCH_TIMEOUT)
        if run.ok and "launch" not in app.driver_caps():
            # no terminal driver: workplace.py only printed what to start, nothing runs, so nothing is recorded
            lines = []
            try:
                lines = [m.as_text(x).strip() for x in m._list(json.loads(run.out).get("report"))]
            except (ValueError, AttributeError):
                pass
            commands = [line for line in lines if line and not line.startswith("No driver configured")]
            ctx.note(tx["manual_start"].format(word=word, commands=" · ".join(commands) or "?"), bad=True)
            app.collector.release(items)
            return "manual"
        report = run.err
        started: list[str] = []
        running: list[dict] = []
        any_skipped = False
        try:
            data = json.loads(run.out)
            if not isinstance(data, dict):
                raise ValueError("not an object")
            lines = [m.as_text(x) for x in m._list(data.get("report"))]
            entries = [e for e in m._list(data.get("items")) if isinstance(e, dict)]
            fresh = [line for line in lines if not line.startswith("already open:")]
            report = " · ".join(fresh) or ("" if lines else report)
            if target == "auto":
                placed = [tx["placed"].format(label=m.short(m.as_text(e.get("label")), 30),
                                              workspace=tx["own_ws"] if e.get("own") else (m.as_text(e.get("workspace")) or "?"),
                                              why=m.paren(m.as_text(e.get("why"))))
                          for e in entries if e.get("label") and not e.get("error") and not e.get("skipped")]
                if placed:
                    report = " · ".join(placed)
            has_error_line = any(line.startswith("ERROR") for line in lines)
            if not has_error_line and lines:
                started = [m.as_text(e["item"]) for e in entries if e.get("item") and not e.get("error") and not e.get("skipped")]
            any_skipped = any(e.get("skipped") for e in entries)
            running = [{"label": m.as_text(e.get("label") or e.get("item")), "ref": m.as_text(e.get("ref"))}
                       for e in entries if e.get("skipped") == "open" and e.get("ref")]
        except ValueError:
            pass  # no JSON answer: stderr is already in report
        launched = [r for r in rows if r.get("task") in started or r.get("inbox_id") in started]
        # the return channel follows every start that ran (returns.py)
        if launched and getattr(app, "launches", None) is not None:
            app.launches.record([{"key": r["key"], "item": m.launch_item(r), "title": r.get("title"), "mode": mode,
                                  **(chosen or {})} for r in launched if r.get("key") and m.launch_item(r)])
            # and the item's own log says so, for every other reader (returns.py)
            line = ret.start_line(mode, app.cfg.language)
            for r in launched:
                item = m.launch_item(r)
                if r.get("task") == item and SLUG_RE.match(item):
                    ctx.call("task.note", item, self.task_cmd("note", item, "--", line), SHORT_TIMEOUT)
                elif item and INBOX_ID_RE.match(item):
                    ctx.call("inbox.note", item, self.inbox("note", item, "--", line), SHORT_TIMEOUT)
        only_running = run.ok and any_skipped and not launched
        outcome = tx["res_started"] if run.ok else (tx["partly_started"].format(n=len(launched)) if launched else tx["start_failed"])
        if not only_running:
            ctx.note(tx["launch_outcome"].format(outcome=outcome, word=word, report=m.short(report or "", 160)),
                     bad=not run.ok)
        if running:
            app.tabs.poll()
            tab = app.tabs.find(running[0]["ref"])
            if tab and "focus" in app.driver_caps():
                self.jump_to(ctx, tab)
                ctx.jump = {"ref": tab["ref"]}
            ctx.note(tx["already_open"].format(label=m.short(running[0]["label"], 40)))
            ctx.tabs_after(0)
        if launched:
            ctx.tabs_after(5)
        # A start that ran holds its items until the new tab shows up; a failed one frees them at once.
        if not only_running and (run.ok or launched):
            app.collector.release(items, START_HOLD_MS)
        else:
            app.collector.release(items)
        if only_running:
            return "running"
        return "started" if run.ok else "partly" if launched else "failed"

    def ask_relay(self, ctx: Ctx, kind: str, prompt: str) -> tuple[dict, bool]:
        app = self.app
        record, online = app.relay.ask(kind, prompt, app.tabs.control_tab(), app.names_tabs())
        if online:
            ctx.note(self.tx["relay_queued"].format(preview=m.short(prompt, 60)))
        else:
            reason = app.relay_state(with_records=False)["reason"] or "no_heartbeat"
            ctx.note(self.tx["relay_offline"].format(reason=self.tx["relay_reason"].get(reason, reason)), bad=True)
        ctx.relay = record
        app.broadcast("relay", record)
        return record, online

    # ------------------------------------------------------------ verbs

    def file_foreign(self, ctx: Ctx, row: dict) -> dict | None:
        """A row without an inbox item or a task behind it (an issue, an application, a deadline) becomes
        an inbox item an agent can start on; the row itself leaves the briefing for 30 days, the inbox
        item stands for it. None when the inbox refused or answered with something that is no id."""
        page = row.get("page_item")
        if page:
            new_id = self.file_page_item(ctx, row, page)
        else:
            source = (row.get("sources") or ["briefing"])[0]
            detail = " ".join(x for x in [f"{source}:", row.get("ref") or "", m.row_url(row) or ""] if x)
            new_id = self.inbox_add(ctx, row["key"], row["title"], detail)
        if new_id is None:
            return None
        until = (self.today() + dt.timedelta(days=30)).isoformat()
        self.app.store.hide(row["key"], until)
        # the row is back with "show again", from the toast or the history; the inbox item stays
        ctx.history.append(history_item(row["key"], row["title"], "other", f"filed, hidden until {until}"))
        ctx.settled.append(row["key"])
        return {"inbox_id": new_id, "title": row["title"], "area": row.get("area")}

    def file_all(self, ctx: Ctx, rows: list[dict]) -> list[dict]:
        """Every row without an item behind it filed to the inbox, up to the first the inbox refuses: the
        rows filed before it are hidden already and are started, that one and the rest are named and stay"""
        filed = []
        foreign = [r for r in rows if m.launch_item(r) is None]
        for i, row in enumerate(foreign):
            new = self.file_foreign(ctx, row)
            if new is None:
                left = ", ".join(m.short(r["title"], 40) for r in foreign[i:])
                ctx.note(self.tx["not_filed"].format(titles=left), bad=True)
                break
            filed.append(new)
        return filed

    def file_page_item(self, ctx: Ctx, row: dict, page: dict) -> str | None:
        """The inbox item for a page row: the one the briefing's `to_inbox` already filed under its key, else a
        new one under that key, which the briefing closes when the row is gone. A row without a source id
        has no such key: it is filed for a person to close."""
        inbox_key = page.get("inbox_key")
        if inbox_key:
            # the same row filed under any profile's name: the cockpit's profile often extends the briefing's
            same = page["row"]
            for e in self.app.inbox_listing() or []:
                key = str(e.get("key") or "") if isinstance(e, dict) else ""
                if ((key == inbox_key or key.startswith("briefing:") and key.endswith(same))
                        and e.get("state") in ACTIVE_INBOX_STATES and INBOX_ID_RE.match(str(e.get("id")))):
                    return e["id"]
        detail = " ".join(x for x in [page.get("detail"), m.row_url(row) or ""] if x)
        summary = f"{page['section']}: {row['title']}"
        if inbox_key:
            return self.inbox_add(ctx, row["key"], summary, detail, key=inbox_key, closer="reporter")
        return self.inbox_add(ctx, row["key"], summary, detail)

    def inbox_add(self, ctx: Ctx, row_key: str, summary: str, detail: str, key: str | None = None,
                  closer: str = "person") -> str | None:
        """File a free decision item for a person, under `web:<row key>` unless a key is given; its id, or None
        with a note."""
        argv = self.inbox("add", "--from", "bridge-cockpit", "--kind", "decision", "--gate", "free", "--closer", closer,
                          f"--key={key or 'web:' + row_key}", f"--summary={m.short(summary, 200)}", f"--detail={detail}")
        run = ctx.call("inbox.add", row_key, argv, SHORT_TIMEOUT)
        new_id = (run.out or "").strip().splitlines()[-1:] if run.ok else []
        if not run.ok or not new_id or not INBOX_ID_RE.match(new_id[0]):
            ctx.note(self.tx["file_failed"].format(err=m.short(run.err or run.out or "?", 100)), bad=True)
            return None
        return new_id[0]

    def v_do_it(self, ctx: Ctx, keys: list[str], target: str | None = None) -> None:
        rows = [e["row"] for e in self.entries(keys)]
        for row in rows:
            if row.get("inbox_state") == "approved":
                raise self.not_applicable("Do it needs an inbox item or a task that is not approved yet", "keys")
        rows = [r for r in rows if m.launch_item(r) is not None] + self.file_all(ctx, rows)
        yes = [r for r in rows if r.get("inbox_id") and r.get("gate") == "your-yes" and r.get("has_action")]
        rest = [r for r in rows if r not in yes]
        for row in yes:
            self.approve(ctx, row)
        if rest:
            self.launch(ctx, rest, "go", target or self.app.cfg.target)
        if not yes and not rest and not ctx.failed:
            ctx.note(self.tx["nothing_to_do"])

    def v_advise(self, ctx: Ctx, keys: list[str]) -> None:
        rows = [e["row"] for e in self.entries(keys)]
        # a row with nothing to start on (an issue, a deadline) becomes an inbox item first, as for do_it:
        # it gets a tab of its own and never goes into a running session (14.10.)
        startable = [r for r in rows if m.launch_item(r) is not None] + self.file_all(ctx, rows)
        if startable:
            self.launch(ctx, startable, "report", self.app.cfg.target)

    def v_start_agent(self, ctx: Ctx, keys: list[str]) -> None:
        """An agent tab that goes at the item at once ("go"), for an inbox item as for a task: unlike
        do_it it never approves an item's own action, unlike advise it does not stop at a report"""
        rows = [e["row"] for e in self.entries(keys)]
        if any(m.launch_item(r) is None for r in rows):
            raise self.not_applicable("an agent starts on an inbox item or a task", "keys")
        self.launch(ctx, rows, "go", self.app.cfg.target, word=self.tx["btn_start_agent"])

    def v_collect_context(self, ctx: Ctx, key: str) -> None:
        row = self.entry(key)["row"]
        if m.launch_item(row) is None:
            raise self.not_applicable("collecting context needs an inbox item or a task")
        self.launch(ctx, [row], "context", self.app.cfg.target)

    def v_later(self, ctx: Ctx, key: str, until: str) -> None:
        row = self.entry(key)["row"]
        if row.get("inbox_id") and row.get("gate") != "free":
            item = self.inbox_id(row)
            run = ctx.call("inbox.defer", item, self.inbox("defer", item, "--until", until), SHORT_TIMEOUT)
            if not run.ok:
                ctx.note(self.tx["later_failed"].format(err=m.short(run.err, 100)), bad=True)
                return
            # like a hide, a defer can be taken back from the note and the history (inbox_reopen)
            ctx.history.append(history_item(row["key"], row["title"], "inbox", f"later until {until}", item))
            self.settle(ctx, row, self.tx["later_back"].format(until=until))
            return
        self.hide_until(ctx, row, until)

    def v_runs_on(self, ctx: Ctx, keys: list[str], until: str, on: str | None = None) -> None:
        """"Runs on": quiet until a day, waiting on someone or something. An inbox item is put off with what
        it waits on (inbox.py defer --on), a task keeps doing with blocked_by and quiet_until (task.py wait),
        any other row is hidden until the day. Each can be taken back."""
        on = " ".join((on or "").split()) or None
        rows = [e["row"] for e in self.entries(keys)]
        for row in rows:     # a row gone with a refresh, or one whose id fails, refuses before anything is written
            if row.get("inbox_id"):
                self.inbox_id(row)
            elif row.get("task"):
                self.slug(row)
        for row in rows:
            title = m.short(row["title"], 60)
            if row.get("inbox_id"):
                item = self.inbox_id(row)
                run = ctx.call("inbox.defer", item, self.inbox("defer", item, "--until", until, *(["--on", on] if on else [])),
                               SHORT_TIMEOUT)
                if not run.ok:
                    ctx.note(self.tx["later_failed"].format(err=m.short(run.err, 100)), bad=True)
                    continue
                ctx.history.append(history_item(row["key"], row["title"], "inbox", f"runs on until {until}", item))
                self.settle(ctx, row, self.tx["runs_on_note"].format(until=until))
            elif row.get("task"):
                slug = self.slug(row)
                run = ctx.call("task.wait", slug, self.task_cmd("wait", slug, "--until", until,
                                                              *(["--on", on] if on else []), "--json"), SHORT_TIMEOUT)
                if not run.ok:
                    ctx.note(self.tx["later_failed"].format(err=m.short(run.err, 100)), bad=True)
                    continue
                ctx.history.append({"key": row["key"], "title": str(row["title"])[:200], "kind": "task",
                                    "did": f"runs on until {until}", "ident": slug, "undone_ms": None,
                                    "undo": {"verb": "task_running", "args": {"slug": slug}}})
                ctx.note(self.tx["runs_on_note"].format(until=until) + f": {title}")
                ctx.delta()
            else:
                self.hide_until(ctx, row, until)
        self.app.collector.request("both")

    def v_task_running(self, ctx: Ctx, slug: str) -> None:
        """A task that ran on is worked on again: blocked_by and quiet_until go (task.py wait --clear)."""
        run = ctx.call("task.wait", slug, self.task_cmd("wait", slug, "--clear", "--json"), SHORT_TIMEOUT)
        if not run.ok:
            ctx.note(self.tx["reopen_failed"].format(err=m.short(run.err, 100)), bad=True)
            return
        if getattr(self.app, "history", None) is not None:
            self.app.history.mark_undone("task_running", slug)
        ctx.note(self.tx["running_again"].format(slug=slug))
        self.app.collector.request("both")

    def v_to_task(self, ctx: Ctx, key: str, status: str | None = None) -> None:
        """An inbox item that is work for more than one sitting becomes a task (task.py new --from-inbox);
        the item closes with a pointer to it."""
        row = self.entry(key)["row"]
        if not row.get("inbox_id"):
            raise self.not_applicable("only an inbox item becomes a task", "key")
        item = self.inbox_id(row)
        run = ctx.call("task.new", item, self.task_cmd("new", "--from-inbox", item, "--status", status or "backlog",
                                                       "--json"), SHORT_TIMEOUT)
        if not run.ok:
            ctx.note(self.tx["to_task_failed"].format(err=m.short(run.err, 100)), bad=True)
            return
        try:
            slug = json.loads(run.out).get("slug") or ""
        except ValueError:
            slug = ""
        self.settle(ctx, row, self.tx["to_task_note"].format(slug=slug))
        ctx.extra["task"] = slug
        self.app.collector.request("both")

    def v_hide(self, ctx: Ctx, key: str, until: str) -> None:
        self.hide_until(ctx, self.entry(key)["row"], until)

    def v_home_tiles(self, ctx: Ctx, ids: list, seen: list | None = None) -> None:
        """The start page's choice of tiles and shelves, kept on the server so every browser shows the same"""
        self.app.store.set_home_tiles(ids, seen)
        self.app.broadcast("home", self.app.store.home())

    def v_launch_settings(self, ctx: Ctx, settings: dict) -> None:
        """The settings page's change of how an agent picks its model; kept beside the config, never in it"""
        try:
            self.app.launch_model.save(settings)
        except LaunchError as error:
            raise ActionError(error.status, error.code, error.message, error.field) from None
        self.settings_changed(ctx)

    def v_launch_settings_reset(self, ctx: Ctx) -> None:
        """Back to what bridge-config.yaml says"""
        self.app.launch_model.reset()
        self.settings_changed(ctx)

    def settings_changed(self, ctx: Ctx) -> None:
        state = self.app.launch_model.state()
        ctx.extra["launch"] = state
        self.app.broadcast("launch", state)

    # the news ticker (ticker.py): each verb returns at once, a thread does the slow part and
    # broadcasts the `ticker` event when it ends; none of them waits under the write lock

    def v_ticker_settings(self, ctx: Ctx, settings: dict) -> None:
        """The settings page's change of the ticker; kept beside the config, never in it"""
        try:
            self.app.ticker.save(settings)
        except TickerError as error:
            raise ActionError(error.status, error.code, error.message, error.field) from None
        self.ticker_changed(ctx)

    def v_ticker_settings_reset(self, ctx: Ctx) -> None:
        """Back to what bridge-config.yaml says"""
        self.app.ticker.reset()
        self.ticker_changed(ctx)

    def v_ticker_refresh(self, ctx: Ctx) -> None:
        """Read the feeds now; a refresh already running is no error"""
        if not self.app.ticker.request_refresh():
            ctx.extra["already"] = True
        self.ticker_changed(ctx)

    def v_ticker_edit(self, ctx: Ctx) -> None:
        """Let Claude Haiku pick and shorten the items: only ever on this click"""
        try:
            started = self.app.ticker.edit_start()
        except TickerError as error:
            raise ActionError(error.status, error.code, error.message, error.field) from None
        if not started:
            raise ActionError(409, "not_applicable", "the editor is already running")
        self.ticker_changed(ctx)

    def v_ticker_profile(self, ctx: Ctx, llm: bool = False) -> None:
        """Propose interests from the open tasks, as keywords or (llm) written by Claude Haiku; a proposal
        only, the page saves it when the owner takes it"""
        try:
            started = self.app.ticker.profile_start(bool(llm))
        except TickerError as error:
            raise ActionError(error.status, error.code, error.message, error.field) from None
        if not started:
            raise ActionError(409, "not_applicable", "a proposal is already being written")
        self.ticker_changed(ctx)

    def ticker_changed(self, ctx: Ctx) -> None:
        state = self.app.ticker.state()
        ctx.extra["ticker"] = state
        self.app.broadcast("ticker", state)

    def v_return_forget(self, ctx: Ctx, key: str) -> None:
        """Take a start out of the return channel; the row and its tab stay as they are"""
        if not self.app.launches.forget(key):
            raise self.not_applicable("no start of that row in the return channel")
        self.app.collector.rebuild()

    def v_pin(self, ctx: Ctx, key: str, on: bool) -> None:
        """A row on the start page's pinned shelf; it stays until taken off, whatever the briefing says"""
        self.app.store.pin(key, on)
        self.app.broadcast("home", self.app.store.home())

    def v_unhide(self, ctx: Ctx, key: str) -> None:
        found = self.entry(key)
        if not found["hidden"] or not self.app.store.unhide(key):
            raise self.not_applicable("the row is not hidden")
        if getattr(self.app, "history", None) is not None:
            self.app.history.mark_undone("unhide", key)
        ctx.note(self.tx["unhidden_note"].format(title=m.short(found["row"]["title"], 60)))

    def v_drop(self, ctx: Ctx, key: str, reason: str | None = None) -> None:
        row = self.entry(key)["row"]
        if not row.get("inbox_id"):
            until = (self.today() + dt.timedelta(days=7)).isoformat()
            self.hide_until(ctx, row, until)
            return
        item = self.inbox_id(row)
        argv = self.inbox("drop", item, "--note", self.tx["drop_note"], *(["--reason", reason] if reason else []))
        run = ctx.call("inbox.drop", item, argv, SHORT_TIMEOUT)
        if not run.ok:
            ctx.note(self.tx["drop_failed"].format(err=m.short(run.err, 100)), bad=True)
            return
        ctx.history.append(history_item(row["key"], row["title"], "inbox", "dropped", item))
        # inbox.py prints `muted <rule>` when the reason left a rule behind; the page offers to lift it
        muted = next((line.split()[1] for line in run.out.splitlines() if line.startswith("muted ") and len(line.split()) == 2), None)
        if muted:
            ctx.extra["muted"] = muted
        self.settle(ctx, row, self.tx["dropped_muted" if muted else "dropped"])

    def v_inbox_unmute(self, ctx: Ctx, id: str) -> None:  # noqa: A002 - the API name
        run = ctx.call("inbox.unmute", id, self.inbox("unmute", id), SHORT_TIMEOUT)
        if run.ok:
            ctx.note(self.tx["unmuted"])
        else:
            ctx.note(self.tx["unmute_failed"].format(err=m.short(run.err, 100)), bad=True)

    def v_done(self, ctx: Ctx, key: str) -> None:
        row = self.entry(key)["row"]
        if not row.get("inbox_id") or row.get("gate") != "only-you":
            raise self.not_applicable("Done is for inbox items only you can do")
        item = self.inbox_id(row)
        run = ctx.call("inbox.close", item, self.inbox("close", item, "--note", self.tx["done_note"]), SHORT_TIMEOUT)
        if not run.ok:
            ctx.note(self.tx["done_failed"].format(err=m.short(run.err, 100)), bad=True)
            return
        ctx.history.append(history_item(row["key"], row["title"], "inbox", "done", item))
        self.settle(ctx, row, self.tx["res_done"])

    def v_urgency(self, ctx: Ctx, key: str, value: str) -> None:
        row = self.entry(key)["row"]
        if not row.get("inbox_id"):
            raise self.not_applicable("urgency is for inbox items")
        item = self.inbox_id(row)
        run = ctx.call("inbox.urgency", item, self.inbox("urgency", item, value), SHORT_TIMEOUT)
        if run.ok:
            ctx.note(self.tx["urgency_set"].format(word=self.tx["urgency"].get(value, value), title=m.short(row["title"], 60)))
            ctx.delta()
        else:
            ctx.note(self.tx["urgency_failed"].format(err=m.short(run.err, 100)), bad=True)

    def v_priority(self, ctx: Ctx, key: str, value: str) -> None:
        row = self.entry(key)["row"]
        # an inbox row names the task it came from; its priority is not that task's to change from here
        if not row.get("task") or row.get("inbox_id"):
            raise self.not_applicable("priority is for tasks")
        slug = self.slug(row)
        run = ctx.call("task.priority", slug, self.task_cmd("priority", slug, value), SHORT_TIMEOUT)
        if run.ok:
            ctx.note(self.tx["prio_set"].format(priority=value, title=m.short(row["title"], 60)))
            ctx.delta()
        else:
            ctx.note(self.tx["prio_failed"].format(err=m.short(run.err, 100)), bad=True)

    def task_rows(self, keys: list[str], closing: bool = False) -> list[tuple[dict, dict]]:
        """(row, out) per key, every one a task row; closing also needs every one finite."""
        found = []
        for key in keys:
            entry = self.entry(key, "keys")
            row = entry["row"]
            if not row.get("task") or row.get("inbox_id"):
                raise self.not_applicable("this is for tasks", "keys")
            self.slug(row)
            if closing and not (entry["out"] or {}).get("closable"):
                raise self.not_applicable("only a finite task closes, never a stream", "keys")
            found.append((row, entry["out"] or {}))
        return found

    def task_status(self, slug: str) -> str | None:
        """The status in an open task's STATUS.md, or None when there is none to read."""
        try:
            text = (self.app.root / "work" / "tasks" / slug / "STATUS.md").read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
        status = split_front(text)[0].get("status")
        return status if isinstance(status, str) else None

    def v_task_close(self, ctx: Ctx, keys: list[str], reason: str, text: str | None = None) -> None:
        rows = self.task_rows(keys, closing=True)
        done = failed = 0
        for row, out in rows:
            slug = self.slug(row)
            why = reason
            if why == "auto":
                why = "not_doing" if ((out.get("review") or {}).get("verdict") == "stale") else "done"
            words = self.tx["close_reason"][why] + (f": {text}" if text else "")
            argv = self.task_cmd("close", slug, *(["--declined"] if why in DECLINED_REASONS else []), "--reason", words)
            before = self.task_status(slug)     # read before the close moves the folder: the undo restores it
            run = ctx.call("task.close", slug, argv, SHORT_TIMEOUT)
            if not run.ok:
                failed += 1
                ctx.note(self.tx["task_close_failed"].format(title=m.short(row["title"], 40),
                                                             err=m.short(run.err, 100)), bad=True)
                continue
            done += 1
            ctx.history.append(history_item(row["key"], row["title"], "task",
                                            "declined" if why in DECLINED_REASONS else "done", slug, before))
            if len(rows) == 1:
                self.settle(ctx, row, self.tx["task_declined" if why in DECLINED_REASONS else "task_closed"])
            else:
                self.app.collector.settle(row["key"], self.tx["task_closed"])
                ctx.settled.append(row["key"])
        if len(rows) > 1:
            ctx.note(self.tx["tasks_closed"].format(n=done) + (f" · {failed} ✗" if failed else ""), bad=bool(failed))
            ctx.delta()

    def v_quick_handoff(self, ctx: Ctx, conv: str, to: str, text: str | None = None) -> None:
        """A quick conversation becomes work: "tab" files it to the inbox and starts an agent tab on it
        (the workplace's agent model, Sonnet or more, never the quick model), "control" gives it to the
        control session through the relay."""
        order = (text or "").strip()
        if len(order) > HANDOFF_ORDER_MAX:
            # refused, never trimmed: a cut order would start the work on half the instruction
            raise bad_arg("text", f"length must be 1 to {HANDOFF_ORDER_MAX}")
        text = self.app.quick.transcript(conv)
        if not text:
            raise ActionError(409, "stale_row", "the conversation has no answer yet", "conv")
        # what the person adds on handing on is the order, kept whole at the end
        text = f"{text[:HANDOFF_MAX - len(order) - 2]}\n\n{order}" if order else text[:HANDOFF_MAX]
        if to == "control":
            if not self.app.cfg.relay:
                raise self.not_applicable("no control session: the relay is off", "to")
            record, online = self.ask_relay(ctx, "free", self.tx["handoff_control"].format(text=text))
            if not online:
                ctx.note(self.tx["handoff_offline"], bad=True)
            return
        first = self.app.quick.first_question(conv)
        new_id = self.inbox_add(ctx, conv, first, text)
        if new_id is not None:
            got = self.launch(ctx, [{"key": f"inbox:{new_id}", "inbox_id": new_id, "title": first}], "go", self.app.cfg.target)
            if got == "busy" and order:
                # the tab of this chat is already on its way: the new words reach the item as a note, not that tab
                ctx.call("inbox.note", new_id, self.inbox("note", new_id, "--", order[:2000]), SHORT_TIMEOUT)
                ctx.note(self.tx["handoff_order_late"], bad=True)

    def v_chat_tab(self, ctx: Ctx, text: str) -> None:
        """A problem from the chat that needs a session able to act: filed as a decision and started at
        once as an agent tab (the workplace's model and target), with no quick answer in between."""
        first = text.strip().splitlines()[0]
        new_id = self.inbox_add(ctx, f"chat-{uuid.uuid4().hex[:10]}", first, text.strip())
        if new_id is not None:
            self.launch(ctx, [{"key": f"inbox:{new_id}", "inbox_id": new_id, "title": first}], "go", self.app.cfg.target)

    def v_settle(self, ctx: Ctx, keys: list[str], outcome: str, text: str | None = None) -> None:
        """Done or not doing, for any row: a finite task closes through task.py, an inbox item closes or
        drops, every other row (a GitHub issue, an application, a deadline from a protocol) leaves the
        briefing for good, while its source stays as it is. A stream never settles. All rows are checked
        before the first write."""
        plan = []
        for key in keys:
            entry = self.entry(key, "keys")
            row, out = entry["row"], entry["out"] or {}
            if row.get("task") and not row.get("inbox_id"):
                if not out.get("closable"):
                    raise self.not_applicable("a stream runs on, it never settles", "keys")
                plan.append(("task", key, row))
            elif row.get("inbox_id"):
                self.inbox_id(row)
                plan.append(("inbox", key, row))
            else:
                plan.append(("other", key, row))
        extra = f": {text}" if text else ""
        tasks = [k for kind, k, _ in plan if kind == "task"]
        if tasks:
            self.v_task_close(ctx, tasks, outcome, text)
        for kind, key, row in plan:
            if kind == "inbox":
                item = self.inbox_id(row)
                verb, note = ("close", self.tx["done_note"]) if outcome == "done" else ("drop", self.tx["drop_note"])
                run = ctx.call(f"inbox.{verb}", item, self.inbox(verb, item, "--note", note + extra), SHORT_TIMEOUT)
                if not run.ok:
                    ctx.note(self.tx["done_failed" if outcome == "done" else "drop_failed"].format(err=m.short(run.err, 100)), bad=True)
                    continue
                ctx.history.append(history_item(key, row["title"], "inbox", "done" if outcome == "done" else "dropped", item))
                self.settle(ctx, row, self.tx["res_done" if outcome == "done" else "dropped"])
            elif kind == "other":
                # not collector.settle: its source still lists the row, so it would stay invisible for good;
                # dismissed it shows under the hidden rows with "show again"
                self.app.store.dismiss(key, outcome, row["title"])
                ctx.history.append(history_item(key, row["title"], "other", outcome))
                ctx.settled.append(key)
                ctx.note(f"{self.tx['dismissed_' + outcome]}: {m.short(row['title'], 60)}")
                ctx.delta()

    def reopened(self, ctx: Ctx, verb: str, ident: str, keys: tuple, word: str) -> None:
        """After a reopen: the history says it was taken back, the row is no longer settled, a fresh pass."""
        it = self.app.history.mark_undone(verb, ident) if getattr(self.app, "history", None) is not None else None
        title = (it or {}).get("title") or ident
        for key in {*keys, *(((it or {}).get("key"),) if it else ())}:
            self.app.collector.unsettle(key)
        ctx.note(word.format(title=m.short(title, 60)))
        self.app.collector.request("both")   # the quick pass brings the row back in seconds, the full one follows

    def v_task_reopen(self, ctx: Ctx, slug: str, note: str | None = None, **kw) -> None:
        """A closed task back to work/tasks/: doing, backlog when it only should still be done, or review
        when an undo restores a task closed while in review."""
        status = kw.get("as") or "doing"
        argv = self.task_cmd("reopen", slug, "--as", status, *(["--note", note] if note else []), "--json")
        run = ctx.call("task.reopen", slug, argv, SHORT_TIMEOUT)
        if not run.ok:
            ctx.note(self.tx["reopen_failed"].format(err=m.short(run.err, 100)), bad=True)
            return
        self.reopened(ctx, "task_reopen", slug, (f"task:{slug}",),
                      self.tx[{"doing": "task_reopened", "review": "task_reopened_review"}.get(status, "task_reopened_backlog")])

    def v_inbox_reopen(self, ctx: Ctx, id: str, note: str | None = None) -> None:  # noqa: A002 - the API name
        run = ctx.call("inbox.reopen", id, self.inbox("reopen", id, *(["--note", note] if note else [])), SHORT_TIMEOUT)
        if not run.ok:
            ctx.note(self.tx["reopen_failed"].format(err=m.short(run.err, 100)), bad=True)
            return
        self.reopened(ctx, "inbox_reopen", id, (f"inbox:{id}",), self.tx["inbox_reopened"])

    def v_task_review(self, ctx: Ctx, keys: list[str] | None = None, escalate: bool = False,
                      fresh: bool = False) -> None:
        slugs = [self.slug(row) for row, _ in self.task_rows(keys or [])]
        if escalate and not slugs:
            raise bad_arg("keys", "a closer check names its tasks")
        if not self.app.review.start(slugs, escalate, fresh):
            raise ActionError(409, "review_busy", "a check is already running")
        ctx.steps.append({"call": "task.review", "subject": ",".join(slugs) or "all", "ok": True, "exit": 0,
                          "took_ms": 0, "err": ""})
        ctx.note(self.tx["review_started_closer" if escalate else "review_started"])

    def v_task_keep(self, ctx: Ctx, keys: list[str]) -> None:
        if self.app.review.running:     # both write .bridge/task-review.json
            raise ActionError(409, "review_busy", "a check is running, keep open after it")
        rows = self.task_rows(keys)
        slugs = [self.slug(row) for row, _ in rows]
        run = ctx.call("task.keep", ",".join(slugs), self.task_cmd("review", "--keep", *slugs, "--json"), SHORT_TIMEOUT)
        if run.ok:
            ctx.note(self.tx["task_kept" if len(slugs) == 1 else "task_kept_many"].format(n=len(slugs), title=m.short(rows[0][0]["title"], 60)))
        else:
            ctx.note(self.tx["task_keep_failed"].format(err=m.short(run.err, 100)), bad=True)

    def v_note(self, ctx: Ctx, key: str, text: str) -> None:
        row = self.entry(key)["row"]
        if row.get("task"):
            slug = self.slug(row)
            run = ctx.call("task.note", slug, self.task_cmd("note", slug, "--", text), SHORT_TIMEOUT)
        elif row.get("inbox_id"):
            item = self.inbox_id(row)
            run = ctx.call("inbox.note", item, self.inbox("note", item, "--", text), SHORT_TIMEOUT)
        else:
            raise self.not_applicable("notes only go to tasks and inbox items")
        if run.ok:
            ctx.note(self.tx["note_added"].format(title=m.short(row["title"], 40), line=m.short(text, 60)))
            ctx.delta()
        else:
            ctx.note(self.tx["note_failed"].format(err=m.short(run.err, 100)), bad=True)

    def v_approve_all(self, ctx: Ctx, keys: list[str], confirm: bool = False) -> None:
        model = self.app.collector.model or {}
        allowed = set(model.get("approvable", []))
        if len(keys) < 2 or any(k not in allowed for k in keys):
            raise self.not_applicable("approve all needs more than one approvable row", "keys")
        rows = [e["row"] for e in self.entries(keys)]
        if not confirm:
            ctx.confirm = {"count": len(rows)}
            return
        done = sum(1 for row in rows if self.approve(ctx, row))
        ctx.note(self.tx["approve_all_done"].format(n=done, total=len(rows)), bad=done < len(rows))

    def v_team_role(self, ctx: Ctx, key: str, team: str) -> None:
        app, tx = self.app, self.tx
        row = self.entry(key)["row"]
        if not row.get("task") or row.get("inbox_id"):
            raise self.not_applicable("teams start on task rows")
        slug = self.slug(row)
        recipe = next(t for t in app.collector.teams if t["id"] == team)
        now = app.clock()
        runs = app.store.team_runs()
        st = m.team_state(row, runs, app.collector.teams, app.tabs.tab_list(), now)
        is_same = st is not None and st["team"]["id"] == team
        if is_same and not st["is_ready"]:
            ctx.note(tx["waits_for_role"].format(name=st["waiting_for"] or tx["prev_role"]))
            return
        role = st["next"] if is_same else (recipe["roles"][0] if recipe["roles"] else None)
        if not role:
            ctx.note(tx["all_roles_started"])
            return
        if not TEAM_RE.match(role["id"]):
            raise self.not_applicable("the role id fails validation", "team")
        if slug in app.collector.starting_items():
            ctx.note(tx["starting_already"].format(title=m.short(row["title"], 40)))
            return
        before = runs.get(slug)
        if is_same:
            # an inferred run (started elsewhere) has no record: its roles come from the team state
            earlier = list(before["roles"]) if before else [r["id"] for r in st["team"]["roles"][:st["started"]]]
            roles = earlier + [role["id"]]
        else:
            roles = [role["id"]]
        app.store.set_team_run(slug, {"team": team, "roles": roles, "at": int(now)})
        result = self.launch(ctx, [row], role["mode"], app.cfg.target, {"id": team, "role": role["id"], "name": role["name"]})
        if result in ("failed", "manual"):
            app.store.set_team_run(slug, before)

    def v_adopt(self, ctx: Ctx, key: str, tab_ref: str) -> None:
        found = self.entry(key)
        row = found["row"]
        if not row.get("task") or row.get("inbox_id"):
            raise self.not_applicable("only task rows take a tab")
        candidates = {c["ref"] for c in ((found.get("out") or {}).get("adopt_candidates") or [])}
        if tab_ref not in candidates:
            raise self.not_applicable("the tab is not free in this task's area", "tab_ref")
        tab = self.tab(tab_ref)
        slug = self.slug(row)
        run = ctx.call("workplace.adopt", tab_ref, self.app.workplace("adopt", tab_ref, slug), SHORT_TIMEOUT)
        if run.ok:
            ctx.note(self.tx["adopted"].format(tab=m.short(tab["name"], 30), title=m.short(row["title"], 40)))
        else:
            ctx.note(self.tx["adopt_failed"].format(err=m.short(run.err, 100)), bad=True)
        ctx.tabs_after(0)

    def guard_fresh(self, ctx: Ctx, ref: str, expect: str | None, seen: str | None, name: str | None,
                    sends_text: bool) -> tuple[dict, dict | None]:
        """A reply reaches only the tab and the question it was given for. The tabs are polled again (no
        question is read there), then the tab must still be there, carry the name and the state the page
        named, and, with `seen`, its screen read now must ask the question of that hash (never the one
        kept by the poll). A draft typed in the tab refuses a reply that types text. Nothing is sent on
        any refusal. Returns the tab as it is now and the question read now (None without `seen`)."""
        self.app.tabs.poll(asks=False)
        t = self.app.tabs.find(ref)
        moved = ActionError(409, "tab_moved", self.tx["tab_moved"], "tab_ref")
        if not t or (name is not None and t["name"] != name) or (expect is not None and t["state"] != expect):
            raise moved
        fresh = None
        if seen is not None:
            text, _digest, _err = self.app.tab_screen(ref, fresh=True)
            fresh = ak.question_of(text, t["state"], self.app.scrub) if text is not None else None
            if fresh is None or fresh["hash"] != seen:
                raise moved
            if sends_text and fresh["draft"]:
                raise ActionError(409, "tab_draft", self.tx["tab_draft"], "tab_ref")
        return t, fresh

    def press(self, ctx: Ctx, tab_ref: str, key: str, said: str, seen: str | None = None, name: str | None = None,
              option: int | None = None) -> None:
        tab = self.tab(tab_ref)
        if tab["state"] != "needs-you":
            raise self.not_applicable("the tab is not asking", "tab_ref")
        # The state on the page may be seconds old: if the tab has moved on, Esc would abort its work.
        if seen is not None or name is not None:
            now_tab, fresh = self.guard_fresh(ctx, tab_ref, None, seen, name, False)
        else:
            self.app.tabs.poll(asks=False)
            now_tab, fresh = self.app.tabs.find(tab_ref), None
        if not now_tab or now_tab["state"] != "needs-you":
            ctx.note(self.tx["not_asking"].format(name=m.short(tab["name"], 30)))
            return
        if option is not None:
            picked = next((o for o in (fresh or {}).get("options") or [] if o["n"] == option), None)
            if picked is None:
                raise self.not_applicable("the tab offers no such option", "n")
            said = self.tx["said_option"].format(n=option, label=m.short(picked["label"], 40))
        run = ctx.call("workplace.key", tab_ref, self.app.workplace("key", tab_ref, key), CMUX_TIMEOUT)
        if run.ok:
            ctx.note(self.tx["key_sent"].format(name=m.short(tab["name"], 30), said=said))
        else:
            ctx.note(self.tx["key_failed"].format(err=m.short((run.err or run.out).strip(), 100)), bad=True)
        ctx.tabs_after(3)

    def v_tab_yes(self, ctx: Ctx, tab_ref: str, seen: str | None = None, name: str | None = None) -> None:
        self.press(ctx, tab_ref, "1", self.tx["said_yes"], seen, name)

    def v_tab_no(self, ctx: Ctx, tab_ref: str, seen: str | None = None, name: str | None = None) -> None:
        self.press(ctx, tab_ref, "escape", self.tx["said_no"], seen, name)

    def v_tab_option(self, ctx: Ctx, tab_ref: str, n: int, seen: str, name: str | None = None) -> None:
        """One numbered option of the dialog the tab shows: its digit, never a yes for a choice"""
        self.press(ctx, tab_ref, str(n), "", seen, name, option=n)

    def v_tab_jump(self, ctx: Ctx, tab_ref: str) -> None:
        tab = self.tab(tab_ref)
        if self.jump_to(ctx, tab):
            ctx.note(self.tx["jumped"].format(label=m.short(tab.get("label") or tab["ref"], 40)))

    def send_to(self, ctx: Ctx, tab: dict, text: str) -> None:
        run = ctx.call("workplace.send", tab["ref"], self.app.workplace("send", tab["ref"], "--", text), SHORT_TIMEOUT)
        if run.ok:
            ctx.note(self.tx["sent_to"].format(name=m.short(tab["name"], 30), text=m.short(text, 60)))
        else:
            ctx.note(self.tx["send_failed"].format(err=m.short(run.err, 100)), bad=True)
        ctx.tabs_after(3)

    def v_tab_send(self, ctx: Ctx, tab_ref: str, text: str, seen: str | None = None, expect: str | None = None,
                   name: str | None = None) -> None:
        tab = self.tab(tab_ref)
        if not m.is_live(tab):
            raise self.not_applicable("the tab holds no agent", "tab_ref")
        if seen is not None or expect is not None or name is not None:
            tab, _ = self.guard_fresh(ctx, tab_ref, expect, seen, name, True)
            if not m.is_live(tab):
                raise ActionError(409, "tab_moved", self.tx["tab_moved"], "tab_ref")
            # a dialog takes its options (tab_option), never typed words: a digit typed there would pick
            # an option past the option's own guard
            if tab["state"] == "needs-you":
                raise self.not_applicable("a dialog takes its options, not text", "tab_ref")
        self.send_to(ctx, tab, text)

    def v_tab_go_on(self, ctx: Ctx, tab_ref: str, seen: str | None = None, name: str | None = None) -> None:
        tab = self.tab(tab_ref)
        if tab["state"] != "waiting" or m.filed_by(tab, self.app.collector.view) is not None:
            raise self.not_applicable("go on is for waiting tabs without a filed result", "tab_ref")
        if seen is not None or name is not None:
            tab, _ = self.guard_fresh(ctx, tab_ref, "waiting", seen, name, True)
        self.send_to(ctx, tab, self.tx["go_on"])

    def v_tab_close(self, ctx: Ctx, tab_ref: str) -> None:
        tab = self.tab(tab_ref)
        if tab["state"] != "waiting" or (m.filed_by(tab, self.app.collector.view) is None
                                         and ret.tab_settled(self.app.root, tab) is None):
            raise self.not_applicable("close is for waiting tabs whose result is filed or whose item or task is settled", "tab_ref")
        run = ctx.call("workplace.close", tab_ref, self.app.workplace("close", tab_ref), CMUX_TIMEOUT)
        if run.ok:
            ctx.note(self.tx["tab_closed"].format(name=m.short(tab["name"], 30)))
        else:
            ctx.note(self.tx["close_failed"].format(err=m.short(run.err.strip(), 100)), bad=True)
        ctx.tabs_after(1)

    def renamed(self, ctx: Ctx, run) -> None:
        """What a rename through workplace.py came to. Its refusal (exit 2: a name in use or managed, a ref
        that is gone) is this action's refusal; a driver that failed (exit 1, an ERROR line) is a note."""
        tx = self.tx
        why = ((run.err or run.out) or "").strip()
        if run.code == 2:
            if "name in use" in why:
                raise ActionError(409, "name_in_use", tx["name_in_use"], "title")
            if "configured workspace" in why or "known by this name" in why:
                raise ActionError(409, "name_managed", tx["name_managed"], "title")
            raise ActionError(409, "not_applicable", m.short(why, 160) or tx["rename_failed"].format(err="?"), "title")
        if run.ok:
            ctx.note(tx["renamed"])
        else:
            ctx.note(tx["rename_failed"].format(err=m.short(why, 100)), bad=True)
        ctx.tabs_after(1)

    def v_tab_rename(self, ctx: Ctx, tab_ref: str, title: str) -> None:
        """A tab of its own gets a name. A task, inbox or team tab is found by its name, the control session
        is the control, and a tab whose state only its title glyph tells would lose it with a name of its own."""
        tab = self.tab(tab_ref)
        if tab_ref == self.app.tabs.control_ref():
            raise ActionError(409, "control_tab", self.tx["control_name"], "tab_ref")
        if tab.get("slug") or tab.get("item") or tab.get("team"):
            raise ActionError(409, "task_tab_name", self.tx["task_tab_name"], "tab_ref")
        if tab.get("state_source") == "glyph" and tab.get("state") != "shell":
            raise ActionError(409, "rename_loses_state", self.tx["rename_loses_state"], "tab_ref")
        run = ctx.call("workplace.rename", tab_ref, self.app.workplace("rename", tab_ref, "--", title), SHORT_TIMEOUT)
        self.renamed(ctx, run)

    def v_workspace_rename(self, ctx: Ctx, ws_ref: str, title: str) -> None:
        """A workspace the terminal shows gets a name; the control workspace keeps its own."""
        app = self.app
        listed = app.tabs.workspace_list() or []
        tabs = app.tabs.tab_list()
        current = next((w.get("title") for w in listed if w.get("ref") == ws_ref), None) \
            or next((t["workspace"] for t in tabs if t.get("ws_ref") == ws_ref), None)
        if current is None and not any(t.get("ws_ref") == ws_ref for t in tabs):
            raise ActionError(409, "stale_workspace", self.tx["stale_workspace"], "ws_ref")
        control = app.tabs.control_tab()
        name = (app.cfg.control or "").strip().casefold()
        if (control and control.get("ws_ref") == ws_ref) or (name and str(current or "").strip().casefold() == name):
            raise ActionError(409, "control_tab", self.tx["control_name"], "ws_ref")
        run = ctx.call("workplace.rename-workspace", ws_ref,
                       app.workplace("rename-workspace", ws_ref, "--", title), SHORT_TIMEOUT)
        if run.ok:
            app.tabs.refresh_workspaces()
        self.renamed(ctx, run)

    def layout_script(self, verb: str) -> list[str]:
        return [sys.executable, self.app.runner.script("skills/cmux/scripts/cmux_layout.py"), verb]

    def v_start_control(self, ctx: Ctx) -> None:
        """A new agent tab in the control workspace, for a relay without a session that answers."""
        app = self.app
        if app.relay_state(with_records=False)["online"]:
            raise self.not_applicable("a control session answers already", None)
        if self.control_starting:
            raise self.not_applicable("the control tab is starting already", None)
        self.control_starting = True
        try:
            with ctx.unlocked():
                run = ctx.call("workplace.control", app.cfg.control or "", app.workplace("control", "--yes"),
                               LAUNCH_TIMEOUT)
        finally:
            self.control_starting = False
        if run.ok:
            ctx.note(self.tx["control_starting"])
            ctx.tabs_after(3)
        else:
            ctx.note(self.tx["control_failed"].format(err=m.short(run.err or run.out, 120)), bad=True)

    def v_a2a_ask(self, ctx: Ctx, peer: str, text: str, conv: str | None = None, mode: str | None = None) -> None:
        """A message to an A2A agent, only ever on the user's click; the answer comes as the `agents` event."""
        try:
            ctx.extra["conv"] = self.app.agents.start(peer, text, mode or "question", conv)
        except KeyError as exc:
            raise ActionError(409, "stale_row", str(exc).strip("'"), "conv" if conv else "peer")
        except (RuntimeError, ValueError) as exc:
            raise ActionError(409, "not_applicable", str(exc), "conv")
        ctx.subject = f"a2a:{peer}"

    def v_a2a_poll(self, ctx: Ctx, conv: str) -> None:
        try:
            self.app.agents.poll(conv)
        except KeyError as exc:
            raise ActionError(409, "stale_row", str(exc).strip("'"), "conv")
        except RuntimeError as exc:
            raise ActionError(409, "not_applicable", str(exc), "conv")
        ctx.extra["conv"] = conv

    def v_quick_forget(self, ctx: Ctx, conv: str) -> None:
        """Take a chat with the Bridge off the list; it is kept in the archive (chats/ in the state dir)."""
        try:
            self.app.quick.forget(conv)
        except KeyError as exc:
            raise ActionError(409, "stale_row", str(exc).strip("'"), "conv")
        except RuntimeError as exc:
            raise ActionError(409, "not_applicable", str(exc), "conv")
        ctx.extra["conv"] = conv

    def session_task(self, slug: str) -> None:
        if not self.app.task_open(slug):
            raise ActionError(409, "stale_row", "no open task with this slug", "slug")

    def v_session_link(self, ctx: Ctx, session: str, slug: str) -> None:
        """Link a session to the task it works on (by hand, it wins over what a tab suggests)."""
        self.session_task(slug)
        live = next((x for x in self.app.sessions.state() if x.get("sid") == session), None)
        old = self.app.store.session_links().get(session) or {}
        if live is None and not old:
            raise ActionError(409, "stale_row", "no such session here", "session")
        name = (live or old).get("name") or session[:8]
        self.app.store.link_session(session, slug, name, (live or old).get("cwd") or "", "hand")
        ctx.note(self.tx["session_linked"].format(name=m.short(name, 40), slug=slug))
        self.app.broadcast("sessions", self.app.sessions_state())

    def v_session_unlink(self, ctx: Ctx, session: str) -> None:
        if not self.app.store.unlink_session(session):
            raise ActionError(409, "stale_row", "the session is not linked", "session")
        ctx.note(self.tx["session_unlinked"])
        self.app.broadcast("sessions", self.app.sessions_state())

    def v_session_resume(self, ctx: Ctx, session: str) -> None:
        """Go on in an ended session of a task: a new tab with claude --resume in the folder it ran in."""
        link = self.app.store.session_links().get(session)
        if not link:
            raise ActionError(409, "stale_row", "the session is not linked to a task", "session")
        if any(x.get("sid") == session for x in self.app.sessions.state()):
            raise self.not_applicable("the session still runs: go to its tab", "session")
        self.session_task(link["task"])
        row = {"task": link["task"], "title": link.get("name") or link["task"], "key": f"task:{link['task']}"}
        self.launch(ctx, [row], "go", "area", word=self.tx["btn_resume"], resume={"sid": session, "cwd": link.get("cwd")})

    def v_a2a_forget(self, ctx: Ctx, conv: str) -> None:
        """Take a conversation off the list into the archive (local only, the agent is not told)."""
        try:
            self.app.agents.forget(conv)
        except KeyError as exc:
            raise ActionError(409, "stale_row", str(exc).strip("'"), "conv")
        except RuntimeError as exc:
            raise ActionError(409, "not_applicable", str(exc), "conv")
        ctx.extra["conv"] = conv

    def v_account_status(self, ctx: Ctx, page: str, section: str, index: int, status: str) -> None:
        """Set an account's `status:` in its file (bridge-resources.py set-status), then ask that page
        again without its cached answers, so the row, the overview and the inventory follow."""
        app = self.app
        found = app.collector.page_item(page, section, index)
        if not found:
            raise ActionError(409, "stale_row", "the page item is no longer in the model", "index")
        account = found[1].get("account")
        if not isinstance(account, dict) or not isinstance(account.get("id"), str):
            raise self.not_applicable("not an account row", "index")
        aid = account["id"]
        ctx.subject = f"account:{aid}"
        script = app.runner.script("scripts/bridge-resources.py")
        run = ctx.call("bridge-resources.set-status", aid,
                       [app.runner.python, script, "--root", str(app.root), "set-status", aid, status], SHORT_TIMEOUT)
        if not run.ok:
            ctx.note(self.tx["status_failed"].format(err=m.short(run.err or run.out, 120)), bad=True)
            return
        for pg in (app.collector.view or {}).get("pages", []):
            if pg.get("id") == page:
                for sec in pg.get("sections", []):
                    for cached in (app.root / ".bridge" / "briefing-cache").glob(f"*/{sec.get('id')}.json"):
                        cached.unlink(missing_ok=True)     # a cache, rebuilt by the next pass
        ctx.note(self.tx["status_set"].format(title=m.short(found[1].get("title") or aid, 60),
                                              status=self.tx["account_status"][status]))
        app.collector.request("full")

    def v_github_board(self, ctx: Ctx, section: str, slug: str, mode: str) -> None:
        """Switch one board of a GitHub section: off (not asked, costs nothing), mine (your cards), all (every open
        card). The choice is this person's, kept in .bridge/github-boards.json, never in the profile; the section is
        asked again at once."""
        found = next((b for pg in (self.app.collector.view or {}).get("pages", []) for sec in pg.get("sections", [])
                      if sec.get("id") == section for b in sec.get("boards") or [] if b.get("slug") == slug), None)
        if found is None:
            raise ActionError(409, "stale_row", "the board is not in that section", "slug")
        ctx.subject = f"board:{slug}"
        try:
            from ..briefing_providers.github_work import save_board_mode
            save_board_mode(self.app.root, slug, mode)
        except (OSError, ValueError, ImportError) as exc:
            ctx.note(self.tx["status_failed"].format(err=m.short(str(exc), 120)), bad=True)
            return
        ctx.note(self.tx["board_mode_set"].format(name=m.short(found.get("name") or slug, 60),
                                                  mode=self.tx["board_mode"][mode]))
        self.forget_section(section)

    # ------------------------------------------------------------ a command row's own steps

    def briefing_act(self, ctx: Ctx, section: str, row: str, action: str) -> dict | None:
        """`briefing.py act`: the profile's section runs the step after asking its rows again."""
        app = self.app
        view = app.collector.view or {}
        profile = app.cfg.profile or (view.get("profile") if isinstance(view.get("profile"), str) else None)
        if not profile:
            raise self.not_applicable("no briefing profile to act through", None)
        argv = [app.runner.python, app.runner.script("scripts/briefing.py"), "--root", str(app.root), "act",
                profile, section, row, action]
        run = ctx.call("briefing.act", f"{section}/{row}", argv, SHORT_TIMEOUT * 3)
        if not run.ok:
            ctx.note(self.tx["step_failed"].format(err=m.short(run.err or run.out, 120)), bad=True)
            return None
        try:
            data = json.loads(run.out.strip().splitlines()[-1])
        except (ValueError, IndexError):
            data = {}
        self.forget_section(section)
        return data if isinstance(data, dict) else {}

    def forget_section(self, section: str) -> None:
        """The section's cached answer is void after a step: the next pass asks it again."""
        for cached in (self.app.root / ".bridge" / "briefing-cache").glob(f"*/{section}.json"):
            cached.unlink(missing_ok=True)
        self.app.collector.request("full")

    def v_row_action(self, ctx: Ctx, page: str, section: str, index: int, action: str) -> None:
        found = self.app.collector.page_item(page, section, index)
        if not found:
            raise ActionError(409, "stale_row", "the page item is no longer in the model", "index")
        it = found[1]
        steps = {a.get("id"): a.get("label") for a in it.get("actions") or [] if isinstance(a, dict)}
        row = it.get("row_id")
        if action not in steps or not isinstance(row, str):
            raise self.not_applicable("the row does not offer this step", "action")
        ctx.subject = f"{section}/{row}"
        data = self.briefing_act(ctx, section, row, action)
        if data is None:
            return
        label = str(data.get("did") or steps[action])
        launch = data.get("launch")
        if isinstance(launch, dict) and all(isinstance(launch.get(k), str) and launch[k].strip()
                                            for k in ("summary", "prompt", "key")):
            # a step that hands back a tab (a calendar row's prepare): filed under the event's key, so a second
            # click finds the same item, and started like Do it; the inbox item is its record, no undo
            summary = CONTROL_RE.sub(" ", launch["summary"]).strip()[:200]
            new_id = self.inbox_add(ctx, row, summary, CONTROL_RE.sub(" ", launch["prompt"]).strip()[:3500],
                                    key=CONTROL_RE.sub(" ", launch["key"]).strip()[:240])
            if new_id is not None:
                self.launch(ctx, [{"key": f"inbox:{new_id}", "inbox_id": new_id, "title": summary}], "go",
                            self.app.cfg.target, word=label)
            return
        undo = data.get("undo")
        ctx.history.append({"key": f"row:{section}:{row}", "title": str(it.get("title") or row)[:200], "kind": "row",
                            "did": label, "ident": row, "undone_ms": None,
                            "undo": {"verb": "row_undo", "args": {"section": section, "row": row, "action": undo}}
                            if isinstance(undo, str) and UNDO_TOKEN_RE.match(undo) else None})
        ctx.note(self.tx["step_done"].format(title=m.short(str(it.get("title") or row), 60), did=label))

    def v_row_undo(self, ctx: Ctx, section: str, row: str, action: str) -> None:
        ctx.subject = f"{section}/{row}"
        # only an undo this server handed out for a step it ran, and only once: the token is written into a file
        history = getattr(self.app, "history", None)
        it = history.open_undo("row_undo", {"section": section, "row": row, "action": action}) if history else None
        if it is None:
            raise self.not_applicable("no step on this row to take back", "action")
        if self.briefing_act(ctx, section, row, action) is None:
            return
        history.mark(it)
        ctx.note(self.tx["step_undone"].format(title=m.short((it or {}).get("title") or row, 60)))

    def v_snapshot(self, ctx: Ctx) -> None:
        run = ctx.call("cmux_layout.snapshot", "", self.layout_script("snapshot"), SNAPSHOT_TIMEOUT)
        ctx.note(self.tx["saved"] if run.ok else self.tx["save_failed"].format(err=m.short(run.err, 100)), bad=not run.ok)

    def v_snapshot_list(self, ctx: Ctx) -> None:
        run = ctx.call("cmux_layout.list", "", self.layout_script("list"), LIST_TIMEOUT)
        if run.ok:
            ctx.note(" · ".join([line.strip() for line in run.out.splitlines() if line.strip()][:6]))
        else:
            ctx.note(self.tx["list_unreadable"].format(err=m.short(run.err, 80)), bad=True)

    def v_ask_via_tab(self, ctx: Ctx, relay_id: str) -> None:
        app = self.app
        rec = app.relay.get(relay_id)
        if not rec:
            raise ActionError(409, "stale_row", "the question is no longer known", "relay_id")
        if rec.get("offline") != "offline":
            raise self.not_applicable(self.tx["relay_not_offline"], "relay_id")
        app.tabs.poll()
        control = app.tabs.control_tab()
        if not control or control["state"] != "waiting" or not TAB_REF_RE.match(control["ref"]):
            raise self.not_applicable(self.tx["control_not_waiting"], "relay_id")
        run = ctx.call("workplace.send", control["ref"], app.workplace("send", control["ref"], "--", rec["text"]),
                       SHORT_TIMEOUT)
        if run.ok:
            ctx.relay = app.relay.mark_sent_to_tab(relay_id)
            app.broadcast("relay", ctx.relay)
            ctx.note(self.tx["relay_sent_to_tab"].format(preview=m.short(rec["preview"], 60)))
        else:
            ctx.note(self.tx["send_failed"].format(err=m.short(run.err, 100)), bad=True)
        ctx.tabs_after(3)

    # ------------------------------------------------------------ /api/ask

    def ask(self, kind: Any, args: Any, via: Any = "control", model: Any = None, conv: Any = None,
            place: Any = None) -> tuple[int, dict]:
        """A question to Claude. `via` "quick" (what the page sends) asks a short read-only session of its
        own (quick.py, Haiku unless the page names a model) and answers with the conversation id; "control"
        hands it to the control session through the relay. `place` "core": a free quick question of the start
        page's core, kept out of the chat lists, and a new one replaces the last."""
        app, tx = self.app, self.tx
        if via not in ("quick", "control"):
            raise bad_arg("via", "quick or control")
        if place is not None and (place != "core" or via != "quick" or kind != "free"):
            raise bad_arg("place", "only core, for a free quick question")
        if via == "control" and not app.cfg.relay:
            return 409, {"ok": False, "error": {"code": "relay_disabled", "message": "no control session: the relay is off",
                                                 "field": "via"}}
        if via == "quick":
            try:
                qmodel, provider, _ = app.quick.selection(model)
            except ValueError:
                raise bad_arg("model", "unknown model or invalid AI service configuration")
            if conv is not None and (not isinstance(conv, str) or not CONV_RE.match(conv)):
                raise bad_arg("conv", "not a conversation id")
            if not app.quick.available(qmodel):
                raise ActionError(503, "cli_unavailable", f"the {provider} CLI is not available", None)
        if not isinstance(kind, str) or kind not in ASK_KINDS:
            raise bad_arg("kind", "unknown kind")
        args = {} if args is None else args
        if not isinstance(args, dict):
            raise bad_arg("args", "must be an object")
        allowed = {"row": {"key"}, "follow_up": {"key"}, "info": {"page", "section", "index"}, "free": {"text"},
                   "overview": set(), "plan_day": set(), "evening": set()}[kind]
        for name in args:
            if name not in allowed:
                raise bad_arg(str(name)[:40], "unknown argument")
        for name in allowed:
            if name not in args:
                raise bad_arg(name, "missing")
        model = app.collector.model
        if kind in ("row", "follow_up"):
            row = self.entry(check_key(args["key"], "key"))["row"]
            prompt = m.ask_about(row, tx) if kind == "row" else m.follow_up(row, tx)
        elif kind == "info":
            page, section, index = args["page"], args["section"], args["index"]
            if not isinstance(page, str) or not isinstance(section, str) or not isinstance(index, int) or isinstance(index, bool):
                raise bad_arg("index", "page and section are strings, index an integer")
            found = app.collector.page_item(page, section, index)
            if not found:
                raise ActionError(409, "stale_row", "the page item is no longer in the model", "index")
            sec, info = found
            prompt = m.ask_info(re.sub(r"\s*\(.*?\)", "", sec["title"]), info, tx)
        elif kind == "free":
            prompt = check_text(args["text"], "text", 4000)
        else:
            if model is None or app.collector.view is None:
                raise ActionError(409, "stale_row", "no briefing loaded yet", None)
            rows = [app.collector.index[k]["row"] for s in model["sections"] for k in (r["key"] for r in s["rows"])
                    if k in app.collector.index]
            view = app.collector.view
            control = app.tabs.control_ref()
            tabs = [t for t in app.tabs.tab_list() if t["ref"] != control]
            if kind == "overview":
                prompt = m.overview(view, rows, tx)
            elif kind == "plan_day":
                prompt = m.plan_day(view, rows, [t for t in tabs if m.is_waiting(t, view)], tx)
            else:
                prompt = m.evening(tabs, app.tabs.seen_copy(), app.clock(), tx)
        if via == "quick":
            try:
                conv_id = app.quick.start(prompt, qmodel, conv, kind, place)
            except KeyError:
                raise ActionError(409, "stale_row", "the conversation is gone", "conv")
            except RuntimeError as exc:
                raise ActionError(409, "not_applicable", str(exc), "conv")
            self.audit_line("ask", kind, via="quick", conv=conv_id, model=qmodel, chars=len(prompt))
            return 202, {"ok": True, "conv": conv_id}
        ctx = Ctx(self, "ask")
        record, online = self.ask_relay(ctx, kind, prompt)
        self.audit_line("ask", kind, via="control", id=record.get("id") or "-", chars=len(prompt), online=online)
        app.note(" · ".join(ctx.notes), "info" if online else "warn")
        if online:
            return 202, {"ok": True, "record": record}
        control = app.tabs.control_tab()
        fallback = {"available": bool(control and control["state"] == "waiting"),
                    "tab": {"ref": control["ref"], "name": control["name"], "state": control["state"]} if control else None}
        return 409, {"ok": False, "error": {"code": "relay_offline", "message": "the relay is offline", "field": None},
                     "record": record, "fallback": fallback}
