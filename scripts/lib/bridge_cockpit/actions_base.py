# SPDX-License-Identifier: MIT
"""What every module of the cockpit's verbs shares: the patterns and word lists the arguments are checked
against, the verb table SPEC, the error a refused action raises, the argument checks and Ctx, the record
of what one action did. actions.py re-exports all of it, so callers keep importing from there.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .actions import Actions


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
# why a task closes; `auto` (the overview's bulk close) takes it from the check: stale closes as declined
CLOSE_REASONS = ("done", "not_doing", "superseded", "elsewhere", "auto")
DECLINED_REASONS = frozenset({"not_doing", "superseded"})
# why an inbox item is dropped (inbox.py DROP_REASONS); family and source leave a mute rule behind
DROP_REASONS = ("once", "duplicate", "family", "source")
# a quick chat handed on: what reaches the inbox item or the control session, and the most the order
# typed on handing on may take of it, so some of the conversation always comes along
HANDOFF_MAX = 3500
HANDOFF_ORDER_MAX = 3000
# what the page shows right now, sent along with a free quick question (quick.py): refused above this, never cut
CONTEXT_MAX = 6000
# how the chat's route chip came to its choice (logic.js routeOf, views/chat.js)
ROUTE_BY = ("prefix", "words", "default", "flipped", "forced")

SHORT_TIMEOUT = 30
LAUNCH_TIMEOUT = 150
CMUX_TIMEOUT = 10
STATUS_TIMEOUT = 20
SNAPSHOT_TIMEOUT = 180
LIST_TIMEOUT = 20

# verb -> {arg: (type, required)}
SPEC: dict[str, dict[str, tuple[str, bool]]] = {
    # note: the person's sentence for this start; it goes on the item first (a live tab gets it typed in instead)
    "do_it": {"keys": ("keys", True), "target": ("target", False), "model": ("launch_model", False), "effort": ("launch_effort", False),
              "note": ("text", False)},
    "advise": {"keys": ("keys", True), "model": ("launch_model", False), "effort": ("launch_effort", False), "note": ("text", False)},
    "start_agent": {"keys": ("keys", True), "model": ("launch_model", False), "effort": ("launch_effort", False), "note": ("text", False)},
    "collect_context": {"key": ("key", True), "model": ("launch_model", False), "effort": ("launch_effort", False),
                        "note": ("text", False)},
    "later": {"key": ("key", True), "until": ("date", True)},
    "hide": {"key": ("key", True), "until": ("date", True)},
    "unhide": {"key": ("key", True)},
    "drop": {"key": ("key", True), "reason": ("drop_reason", False)},
    "inbox_unmute": {"id": ("inbox_id", True)},
    "done": {"key": ("key", True)},
    "urgency": {"key": ("key", True), "value": ("urgency", True)},
    "priority": {"key": ("key", True), "value": ("priority", True)},
    # stream: the page asked, and a stream among the keys ends (task.py close --stream)
    "task_close": {"keys": ("keys", True), "reason": ("close_reason", True), "text": ("text", False), "stream": ("bool", False)},
    "settle": {"keys": ("keys", True), "outcome": ("outcome", True), "text": ("text", False), "stream": ("bool", False)},
    "quick_handoff": {"conv": ("conv", True), "to": ("handoff", True), "text": ("long_text", False), "model": ("launch_model", False), "effort": ("launch_effort", False)},
    "quick_forget": {"conv": ("conv", True)},
    # `routed`: how the chat's route chip chose the tab (audit only, never acted on)
    "chat_tab": {"text": ("long_text", True), "model": ("launch_model", False), "effort": ("launch_effort", False),
                 "routed": ("route_by", False)},
    "chat_remind": {"text": ("text", True), "until": ("date", False)},
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
    # organize with AI: a proposal of one model call (read only), then the ticked items of it (organize.py)
    "organize_propose": {},
    "organize_apply": {"proposal": ("organize_id", True), "items": ("organize_items", True)},
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
READ_ONLY_VERBS = frozenset({"snapshot_list", "organize_propose"})
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
        self.audit_extra: dict = {}    # counts a verb adds to its audit line (never a text)
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
