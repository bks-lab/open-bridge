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
# the part after the kind may hold slashes (item:systems/checks/x) but never a ".." segment: a key is a name, not a path
ROW_KEY_RE = re.compile(r"^(inbox|task|ref|title|item):(?!(?:.*/)?\.\.(?:/|\Z)).{1,240}\Z")
INBOX_ID_RE = re.compile(r"^[0-9]{8}-[0-9]{4}-[a-z0-9][a-z0-9-]{0,119}\Z")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}\Z")
RUN_ID_RE = re.compile(r"wf_[A-Za-z0-9-]{1,64}")   # a workflow run (sessions.py read_run)
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
# where a free quick question may stand outside the chat lists, the newest replacing the last: the start page's core,
# the files view's suggested next step
QUICK_PLACES = ("core", "suggest")
# a task's next step as STATUS.md keeps it (task.py next): one line
STEP_MAX = 300
# why a task is shelved (the Work through page's "Drop because"): one short line
REASON_MAX = 200
# how the chat's route chip came to its choice (logic.js routeOf, views/chat.js)
ROUTE_BY = ("prefix", "words", "default", "flipped", "forced")
# who decided a do_it, later, shelve or settle the Work through page sends: a suggestion taken over, a batch, a line
# of the instruction line; absent, the person's own click. Kept in the history and the starts, acted on nowhere
BY_CHOICES = ("suggestion", "batch", "instruction")

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
              "note": ("text", False), "by": ("by", False)},
    "advise": {"keys": ("keys", True), "model": ("launch_model", False), "effort": ("launch_effort", False), "note": ("text", False)},
    "start_agent": {"keys": ("keys", True), "model": ("launch_model", False), "effort": ("launch_effort", False), "note": ("text", False)},
    "collect_context": {"key": ("key", True), "model": ("launch_model", False), "effort": ("launch_effort", False),
                        "note": ("text", False)},
    # text: the person's sentence, kept where the row lives (WorkVerbs.write_note)
    "later": {"key": ("key", True), "until": ("date", True), "text": ("text", False), "by": ("by", False)},
    "hide": {"key": ("key", True), "until": ("date", True)},
    # the Work through page's "Drop because" on a task: parked as an idea with its reason (task.py shelve);
    # until: the day the idea may surface again, else task.py's own default
    "shelve": {"key": ("key", True), "reason": ("reason", True), "until": ("date", False), "by": ("by", False)},
    "unhide": {"key": ("key", True)},
    "drop": {"key": ("key", True), "reason": ("drop_reason", False)},
    "inbox_unmute": {"id": ("inbox_id", True)},
    "done": {"key": ("key", True)},
    "urgency": {"key": ("key", True), "value": ("urgency", True)},
    "area": {"key": ("key", True), "value": ("text", False)},
    "priority": {"key": ("key", True), "value": ("priority", True)},
    # stream: the page asked, and a stream among the keys ends (task.py close --stream)
    "task_close": {"keys": ("keys", True), "reason": ("close_reason", True), "text": ("text", False), "stream": ("bool", False)},
    "settle": {"keys": ("keys", True), "outcome": ("outcome", True), "text": ("text", False), "stream": ("bool", False),
               "by": ("by", False)},
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
    # describe (describe.py): one item's brief now (a proposal when a person wrote it), a proposal taken over as it
    # is or as the person changed it (edited: true), a proposal dropped. `ahead`: the Work through page prepares a
    # card before it stands in front, so the run keeps within describe.budget_per_hour as the pass does
    "describe_run": {"key": ("key", True), "ahead": ("bool", False)},
    "describe_apply": {"key": ("key", True), "proposal": ("describe_id", True), "brief": ("brief", False)},
    "describe_discard": {"key": ("key", True), "proposal": ("describe_id", True)},
    # the themes of the Work through page (themes.py): one run over the open points (assign: those without a theme,
    # regroup: a click orders them all anew), a point moved by hand to a theme or to a new one, a theme renamed
    "flow_themes_run": {"mode": ("themes_mode", True), "keys": ("keys", True)},
    "flow_theme_move": {"key": ("key", True), "theme": ("theme_id", True)},
    "flow_theme_new": {"key": ("key", True), "name": ("theme_name", True)},
    "flow_theme_rename": {"theme": ("theme_id", True), "name": ("theme_name", True)},
    # the Activity tab and the instruction line of Work through: a summary of a point's activity (activity.py), one
    # sentence turned into steps over the points in scope, never run here (instruct.py; point: the scope is the open
    # point), and a document attached to the task's deliverables/ (POST /api/flow/attach runs this verb)
    "flow_activity_summary": {"key": ("key", True)},
    "flow_instruct": {"text": ("instruct_text", True), "keys": ("keys", True), "point": ("bool", False)},
    "flow_attach": {"key": ("key", True), "name": ("attach_name", True), "data": ("attach_data", True)},
    "snapshot": {},
    "home_tiles": {"ids": ("tile_ids", True), "seen": ("tile_ids", False)},
    "pin": {"key": ("key", True), "on": ("bool", True)},
    "return_forget": {"key": ("key", True)},
    # the files view: a workflow run's result checked, so it no longer waits in its task's file
    "run_seen": {"id": ("run_id", True)},
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
    # the files view takes over a suggested next step: next: {what} with a dated note (task.py next)
    "task_set_next": {"key": ("key", True), "text": ("line", True)},
    # taking a to_task back: the task it made closes as declined, the inbox item opens again
    "to_task_undo": {"id": ("inbox_id", True), "slug": ("slug", True)},
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
    # the decision guide (guide.py): a reading of one waiting tab, and its two switches beside the config
    "guide_read": {"tab_ref": ("tab_ref", True)},
    "guide_settings": {"enabled": ("bool", False), "auto": ("bool", False)},
    "guide_settings_reset": {},
    # the first-run tour: finished or skipped (v: the page's tour version), and taken back to offer it again
    "tour_done": {"how": ("tour_how", True), "v": ("index", True)},
    "tour_reset": {},
    "account_status": {"page": ("page_id", True), "section": ("page_id", True), "index": ("index", True),
                       "status": ("account_status", True)},
    "github_board": {"section": ("page_id", True), "slug": ("page_id", True), "mode": ("board_mode", True)},
    # the mode a board takes until the person switches it (settings), or "profile" to leave it to the profile
    "github_board_default": {"mode": ("board_default", True)},
}
BOARD_MODES = ("off", "mine", "all")
BOARD_DEFAULTS = (*BOARD_MODES, "profile")
ACCOUNT_STATUSES = ("active", "paused", "disabled")
# a command row's own step and the undo token it returns (the same rules as briefing.py act)
ROW_STEP_RE = re.compile(r"^[a-z][a-z0-9_-]{0,39}\Z")
UNDO_TOKEN_RE = re.compile(r"^restore:[A-Za-z0-9._~-]{1,120}\Z")
ROW_REF_RE = re.compile(r"^[A-Za-z0-9][^\x00-\x1f]{0,199}\Z")
PAGE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}\Z")
ASK_HASH_RE = re.compile(r"^[0-9a-f]{16}\Z")   # the hash of a tab's question (asks.py)
TAB_STATES = ("needs-you", "waiting", "working")
TOUR_HOW = ("finished", "skipped")   # how the first-run tour ended (store.py tour)
TILE_ID_RE = re.compile(r"^[A-Za-z0-9@][A-Za-z0-9:._@/-]{0,79}\Z")   # a tile or shelf of the start page
# where a note leads (the toast's `go`): one small closed union, each kind with the one field it needs and its
# own pattern; the conversations as agents.py and quick.py name them. Never a path: a place the page opens itself.
GO_PAGE_RE = re.compile(r"^@?[a-z0-9][a-z0-9_-]{0,63}\Z")
GO_FIELDS = {
    "tab": ("ref", TAB_REF_RE),
    "row": ("key", ROW_KEY_RE),
    "item": ("key", re.compile(r"^(?:inbox|task):")),   # and a row key: only an inbox item or a task has the item drawer
    "page": ("id", GO_PAGE_RE),
    "conv": ("id", re.compile(r"^g[0-9a-f]{10}\Z")),
    "ask": ("id", re.compile(r"^q[0-9a-f]{10}\Z")),
    "claude": None,
}
READ_ONLY_VERBS = frozenset({"snapshot_list", "organize_propose"})
# only stores with their own locks (store.py, launch.py, ticker.py, guide.py): they never wait for a write that runs
LOCAL_VERBS = frozenset({"pin", "hide", "home_tiles", "ticker_settings", "ticker_settings_reset", "launch_settings",
                         "launch_settings_reset", "session_link", "run_seen", "guide_read", "guide_settings", "guide_settings_reset",
                         "tour_done", "tour_reset", "flow_themes_run", "flow_theme_move", "flow_theme_new",
                         "flow_theme_rename", "flow_activity_summary", "flow_instruct"})
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


def note_go(go: Any) -> dict | None:
    """A note's target as the page takes it ({kind: tab, ref} ...), only the field of its kind; any other shape None"""
    if not isinstance(go, dict) or not isinstance(go.get("kind"), str) or go["kind"] not in GO_FIELDS:
        return None
    kind = go["kind"]
    spec = GO_FIELDS[kind]
    if spec is None:
        return {"kind": kind}
    field, pattern = spec
    value = go.get(field)
    if not isinstance(value, str) or not pattern.match(value) or (kind == "item" and not ROW_KEY_RE.match(value)):
        return None
    return {"kind": kind, field: value}


def row_go(row: dict) -> dict | None:
    """Where a note about a row leads: an inbox item or a task to its item drawer, any other row to the row"""
    key = row.get("key") if isinstance(row, dict) else None
    return note_go({"kind": "item" if str(key).startswith(("inbox:", "task:")) else "row", "key": key})


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
        self.go: dict | None = None    # where the note leads (note_go), the first note that names a place
        self.by: str | None = None     # who decided (BY_CHOICES), None for the person's own click

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
        app = self.actions.app
        run = app.run(argv, timeout)
        self.steps.append({"call": name, "subject": subject, "ok": run.ok, "exit": run.code, "took_ms": run.took_ms,
                           "err": self.actions.app.scrub(run.err or "")[-300:]})
        return run

    def note(self, text: str, bad: bool = False, go: dict | None = None) -> None:
        if text:
            self.notes.append(text)
            self.go = self.go or note_go(go)
        self.failed = self.failed or bad

    def delta(self) -> None:
        self.reload = "delta"

    def tabs_after(self, delay: float) -> None:
        self.tabs_delay = delay if self.tabs_delay is None else min(self.tabs_delay, delay)
        if self.reload == "none":
            self.reload = "tabs"
