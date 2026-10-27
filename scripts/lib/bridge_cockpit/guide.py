# SPDX-License-Identifier: MIT
"""The decision guide: where a waiting session stands and what its owner could tell it next.

When an agent tab waits for you (asks a question, shows a dialog, or is done and idle), Claude Haiku reads
the end of that session and answers in two short sentences where it stands and what it waits for, with
up to OPTIONS_MAX next steps. The page draws that as a small tree whose branches are buttons. A button
sends through the reply verbs that already guard a tab (tab_send with the question's hash, tab_option for
a dialog's numbered option), so the guide adds no way of its own to write into a tab.

What Haiku reads: the session's transcript, ~/.claude/projects/<cwd as a slug>/<session id>.jsonl, found
through the Sessions scan (sessions.py, a session's tab by CMUX_SURFACE_ID or TMUX_PANE), of which only the
first ask (what the session was started for), its title, the last ask, the one before it and the agent's
words after the last ask are kept: no tool calls, tool output, thinking, meta lines or subagents. The task
the session belongs to (a task tab's BRIDGE_TAB_SLUG, or a link made on the Sessions page) adds its headline.
Besides where it stands, Haiku says in one line what the session is about (`about`); without that line the
title, the task's headline or the first ask stand in, and they show already while Haiku reads. A tab without a transcript gives its screen instead. The cockpit's key
is scrubbed out before the prompt is written and again from the answer. The call is model_route.haiku_argv:
no tools, no settings, no session.

Off until cockpit.session_guide.enabled (or the settings page) switches it on. With `auto` (the default
once on) a tab is read when it starts waiting with a new question, at most `per_hour` such reads an hour,
never the control tab, never a tab whose result is filed; the button reads any waiting tab again. One read
runs at a time, on a worker thread of its own; each change goes out as the SSE event `guide`.
The settings page's changes are kept in .bridge/cockpit/guide.json beside the config, never in it.
"""
from __future__ import annotations

import collections
import json
import re
import threading
from pathlib import Path
from typing import Any

from .. import model_route as mr
from . import model as m
# one reader of a session's transcript for the guide and the task a session works on (sessions.infer)
from .sessions import NOISE_RE, TAG_RE, claude_dir, read_tail, transcript_path  # noqa: F401
from .store import atomic_write_json, read_json

FILE = "guide.json"
DEFAULTS: dict[str, Any] = {"enabled": False, "auto": True, "per_hour": 30}
SWITCHES = ("enabled", "auto")
TIMEOUT = 90
HOUR_MS = 3_600_000
TAIL_BYTES = 600_000          # the end of a transcript read for the last turns; a turn longer than this is cut
USER_MAX = 1200               # the last ask: its start
PREV_MAX = 300                # the ask before it: its start
SAID_MAX = 3000               # what the agent said after the last ask: its end
SCREEN_MAX = 2500             # a tab without a transcript: the end of its screen
TITLE_MAX = 120
HEAD_BYTES = 200_000          # the start of a transcript read for its first ask
FIRST_MAX = 600               # the first ask: its start
TASK_TITLE_MAX = 160
ABOUT_MAX = 120
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}\Z")
HEADLINE_RE = re.compile(r"^headline:\s*(.+?)\s*$", re.M)
ASK_MAX = 600
WHERE_MAX = 200
WAITS_MAX = 160
OPTIONS_MAX = 4
LABEL_MAX = 48
SEND_MAX = 300
WHY_MAX = 90
CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
# what reaches beyond the session or cannot be taken back: such an option needs a second click on the page,
# whatever Haiku said about it; read in the words a step sends (a dialog's label), never negated (risky_words)
RISKY_RE = re.compile(
    r"\b(push|force|merge|delete|remove|drop|deploy|release|publish|rm\s+-|reset\s+--hard|rebase|send|mail|"
    r"pay|transfer|revoke|rotate|shutdown|reboot|wipe|purge|"
    r"pushen|mergen|löschen|lösche|entfernen|entferne|veröffentlich\w*|senden|sende|schick\w*|ausroll\w*|"
    r"überweis\w*|zurücksetzen)\b", re.I)


# a risky word does not count right after a negation in the same clause: "commit, aber nicht pushen"
NEGATION_RE = re.compile(r"(?:^|\s)(?:nicht|nichts|kein\w*|ohne|nie|niemals|no|not|nothing|never|without|don['’]?t|do\s+not)"
                         r"(?:\s+\S+){0,2}\s*$", re.I)
CLAUSE_RE = re.compile(r"[,.;:!?\n]")


def risky_words(text: str) -> bool:
    """Whether words sent to a session ask for something that reaches beyond it (RISKY_RE), not counting a
    word negated in its own clause"""
    for found in RISKY_RE.finditer(text or ""):
        before = text[max(0, found.start() - 60):found.start()]
        cut = max((m.end() for m in CLAUSE_RE.finditer(before)), default=0)
        if not NEGATION_RE.search(before[cut:]):
            return True
    return False


class GuideError(Exception):
    def __init__(self, status: int, code: str, message: str, field: str | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.field = status, code, message, field


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def guide_of(value: Any) -> dict:
    """cockpit.session_guide on top of DEFAULTS, key by key: a bad value keeps the default of its key."""
    out = dict(DEFAULTS)
    for key, v in (value.items() if isinstance(value, dict) else ()):
        if key in SWITCHES and isinstance(v, bool):
            out[key] = v
        elif key == "per_hour" and _is_int(v) and 1 <= v <= 1000:
            out[key] = v
    return out


def check(value: Any, cfg_value: dict, where: str) -> list[str]:
    """The config check's warnings for the block (config.check_block)."""
    if not isinstance(value, dict):
        return [f"{where}: must be a mapping; ignored"]
    out = []
    for key, v in value.items():
        at = f"{where}.{str(key)[:40]}"
        if key not in DEFAULTS:
            out.append(f"{at}: unknown key, ignored")
        elif v is None:
            continue
        elif key in SWITCHES and not isinstance(v, bool):
            out.append(f"{at}: must be true or false; using {str(cfg_value[key]).lower()}")
        elif key == "per_hour" and not (_is_int(v) and 1 <= v <= 1000):
            out.append(f"{at}: must be a whole number from 1 to 1000; using {cfg_value[key]}")
    return out


# ------------------------------------------------------------------ reading a session

def clean(text: Any, cap: int | None = None, keep: str = "start") -> str:
    """Words without control characters and runs of blanks; cut to `cap` at a word, keeping the start or the end."""
    if not isinstance(text, str):
        return ""
    lines = [" ".join(CONTROL_RE.sub(" ", ln).split()) for ln in text.splitlines()]
    out = "\n".join(ln for ln in lines if ln).strip()
    if cap is None or len(out) <= cap:
        return out
    if keep == "end":
        cut = out[-(cap - 1):]
        space = cut.find(" ")
        if 0 <= space < cap // 3:
            cut = cut[space + 1:]
        return "…" + cut
    cut = out[:cap - 1]
    space = cut.rfind(" ")
    if space >= cap * 2 // 3:
        cut = cut[:space]
    return cut.rstrip(" ,;:") + "…"


def _flat(text: str, cap: int) -> str:
    """One line: every blank (newlines included) as one space, then cut"""
    return clean(" ".join(text.split()) if isinstance(text, str) else "", cap)


def _user_text(content: Any) -> str | None:
    """What the person typed: plain text without the harness's reminders; None for tool results"""
    if isinstance(content, str):
        parts = [content]
    elif isinstance(content, list):
        parts = [b.get("text") for b in content if isinstance(b, dict) and b.get("type") == "text"
                 and isinstance(b.get("text"), str)]
    else:
        return None
    text = TAG_RE.sub(" ", NOISE_RE.sub(" ", "\n".join(parts)))
    text = clean(text)
    return text or None


def _assistant_text(content: Any) -> list[str]:
    if not isinstance(content, list):
        return []
    return [b["text"].strip() for b in content if isinstance(b, dict) and b.get("type") == "text"
            and isinstance(b.get("text"), str) and b["text"].strip()]


def turns_of(lines: list[str]) -> dict:
    """{title, prev, user, said} of a transcript's lines: the session's title, the ask before the last, the
    last ask, and what the agent said after it. Lines that do not parse, meta lines and subagents are skipped."""
    title = None
    asks: list[str] = []
    said: list[str] = []
    for raw in lines:
        try:
            entry = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        kind = entry.get("type")
        if kind == "ai-title" and isinstance(entry.get("aiTitle"), str):
            title = clean(entry["aiTitle"], TITLE_MAX) or title
            continue
        if kind not in ("user", "assistant") or entry.get("isSidechain") or entry.get("isMeta"):
            continue
        message = entry.get("message") if isinstance(entry.get("message"), dict) else {}
        if kind == "user":
            text = _user_text(message.get("content"))
            if text:
                asks.append(text)
                said = []
        else:
            said.extend(_assistant_text(message.get("content")))
    return {"title": title, "prev": clean(asks[-2], PREV_MAX) if len(asks) > 1 else None,
            "user": clean(asks[-1], USER_MAX) if asks else None,
            "said": clean("\n".join(said), SAID_MAX, keep="end") if said else None}


def first_ask(path: Path) -> str | None:
    """The first thing the person asked in a session: what it was started for. Read from the start of the
    transcript; None when there is none."""
    try:
        with open(path, "rb") as fh:
            data = fh.read(HEAD_BYTES)
    except OSError:
        return None
    lines = data.decode("utf-8", errors="replace").splitlines()
    if len(data) >= HEAD_BYTES and lines:
        lines = lines[:-1]                 # the read may end inside a line
    for raw in lines:
        try:
            entry = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(entry, dict) or entry.get("type") != "user" or entry.get("isSidechain") or entry.get("isMeta"):
            continue
        message = entry.get("message") if isinstance(entry.get("message"), dict) else {}
        text = _user_text(message.get("content"))
        if text:
            return clean(text, FIRST_MAX)
    return None


def task_headline(root: Path, slug: str | None) -> str | None:
    """The headline of an open task or stream (its STATUS.md front matter); None for anything else."""
    if not isinstance(slug, str) or not SLUG_RE.match(slug):
        return None
    for kind in ("tasks", "streams"):
        path = Path(root) / "work" / kind / slug / "STATUS.md"
        try:
            head = path.read_text(encoding="utf-8")[:6000]
        except OSError:
            continue
        found = HEADLINE_RE.search(head)
        if found:
            return clean(found.group(1).strip().strip('"\''), TASK_TITLE_MAX) or None
        return None
    return None


def key_of(tab: dict) -> str:
    """Which question a reading answers: the hash of the question the tab poll read (asks.py), else the
    state and since when the tab is in it. The page computes the same (logic.js guideKey)."""
    ask = tab.get("ask") if isinstance(tab.get("ask"), dict) else None
    if ask and isinstance(ask.get("hash"), str):
        return ask["hash"]
    return f"{tab.get('state')}:{int(tab.get('since_ms') or 0)}"


# ------------------------------------------------------------------ the prompt and the answer

PROMPT = """You help {person} decide what to tell an AI coding agent session that now waits for them.
Read the session below and answer in {language}, plainly, without dashes as punctuation.

Session: "{name}" in workspace "{workspace}"{project}{title}{task}
State: {state_words}
{question}
{turns}
Answer with one JSON object only:
{{"about": "<what this session works on as a whole, so {person} recognises it at a glance: a short phrase, at most 12 words, naming the subject, not the state>",
 "where": "<where the session stands, one sentence, at most 25 words>",
 "waits_for": "<what exactly it waits for from {person}, one sentence, at most 18 words>",
 "options": [{options_shape}],
 "pick": <index of the option you recommend, or null>}}
Rules: two to four options, the most sensible first. {options_rule} Mark "risky": true only when the message itself
asks the agent to push, merge, delete, deploy, send something outside, or do what cannot be undone; a message
that says not to (commit, but do not push) is not risky. Invent no facts; when the
session gives too little to go on, give no options and say so in "where"."""

WAIT_SHAPE = ('{"label": "<button text, at most 5 words>", "send": "<the exact message to type into the session, '
              'in the language the session is held in, at most 40 words>", "why": "<at most 10 words>", "risky": false}')
WAIT_RULE = "Each option is a message to the agent; one may simply let it go on."
DIALOG_SHAPE = '{"n": <number of a dialog option shown below>, "why": "<at most 10 words>", "risky": false}'
DIALOG_RULE = "The session shows a dialog: each option names one of its numbered choices by its number, nothing else."
LANGUAGES = {"de": "German", "en": "English"}


def prompt(tab: dict, context: dict, language: str, person: str | None) -> str:
    """The prompt for one tab; always within model_route.HAIKU_PROMPT_MAX (the longest parts give way)."""
    ask = tab.get("ask") if isinstance(tab.get("ask"), dict) else {}
    dialog = tab.get("state") == "needs-you" and bool(ask.get("options"))
    lines = []
    if ask.get("text"):
        lines.append(f"What the screen shows it asks: {clean(ask['text'], ASK_MAX)}")
    if dialog:
        lines.append("Dialog options: " + "; ".join(f"{o['n']}. {clean(o.get('label'), LABEL_MAX * 2)}"
                                                    for o in ask["options"] if _is_int(o.get("n"))))
    state_words = {"needs-you": "shows a dialog or a permission prompt and cannot go on without an answer",
                   "waiting": "finished its turn and waits for the next message"}.get(tab.get("state"), str(tab.get("state")))
    base = dict(person=person or "the user", language=LANGUAGES.get(language, "English"),
                name=clean(tab.get("name"), 80), workspace=clean(tab.get("workspace"), 80),
                project=f', folder "{clean(context.get("project"), 60)}"' if context.get("project") else "",
                title=f', titled "{context["title"]}"' if context.get("title") else "",
                task=f'\nIt belongs to the task "{context["task_title"]}"' if context.get("task_title") else "",
                state_words=state_words, question="\n".join(lines),
                options_shape=DIALOG_SHAPE if dialog else WAIT_SHAPE, options_rule=DIALOG_RULE if dialog else WAIT_RULE)
    prev, user, said = context.get("prev") or "", context.get("user") or "", context.get("said") or ""
    first = context.get("first") or ""
    if first and first in (user, prev):
        first = ""                 # a session of one or two asks: the first is already there
    for _ in range(14):
        started = f"\nWhat the session was started for (its first ask):\n<<<\n{first}\n>>>\n" if first else ""
        if context.get("source") == "screen":
            turns = started + f"\nThe end of its terminal screen:\n<<<\n{said}\n>>>\n"
        else:
            turns = (started + (f"\nThe ask before the last one:\n<<<\n{prev}\n>>>\n" if prev else "")
                     + (f"\nThe last ask to the agent:\n<<<\n{user}\n>>>\n" if user else "")
                     + (f"\nWhat the agent said after it:\n<<<\n{said}\n>>>\n" if said else ""))
        text = PROMPT.format(turns=turns, **base)
        if len(text) <= mr.HAIKU_PROMPT_MAX:
            return text
        over = len(text) - mr.HAIKU_PROMPT_MAX + 20
        if prev:
            prev = ""
        elif len(first) > 300:
            first = first[:300] + "…"
        elif len(said) > 600:
            said = "…" + said[min(len(said) - 500, over):]
        elif len(user) > 300:
            user = user[:max(200, len(user) - over)] + "…"
        else:
            said, user, first = said[-300:], user[:200], first[:150]
    return text[:mr.HAIKU_PROMPT_MAX]


def _answer_text(stdout: str) -> tuple[str, float | None]:
    """The text of the answer (the claude -p envelope's result, or the bare text) and its cost."""
    text, cost = stdout or "", None
    try:
        envelope = json.loads(text)
        if isinstance(envelope, dict):
            c = envelope.get("total_cost_usd")
            cost = float(c) if isinstance(c, (int, float)) and not isinstance(c, bool) else None
            if isinstance(envelope.get("result"), str):
                text = envelope["result"]
    except ValueError:
        pass
    return text, cost


def parse(stdout: str, state: str, ask: dict | None) -> tuple[dict | None, float | None]:
    """Haiku's answer as {where, waits_for, options, pick}, only what is safe to offer, and the cost; None
    when there is no usable answer. A dialog's option names one of the dialog's own numbers and takes its
    label from the screen; a waiting tab's option carries the words a button sends."""
    text, cost = _answer_text(stdout)
    start, end = text.find("{"), text.rfind("}")
    try:
        data = json.loads(text[start:end + 1]) if 0 <= start < end else None
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return None, cost
    where = _flat(data.get("where"), WHERE_MAX)
    if not where:
        return None, cost
    shown = {o["n"]: o.get("label") or str(o["n"]) for o in ((ask or {}).get("options") or [])
             if isinstance(o, dict) and _is_int(o.get("n"))}
    dialog = state == "needs-you" and bool(shown)
    options: list[dict] = []
    taken: set[int] = set()
    raw_options = data.get("options") if isinstance(data.get("options"), list) else []
    for raw in raw_options:
        if not isinstance(raw, dict) or len(options) >= OPTIONS_MAX:
            continue
        why = _flat(raw.get("why"), WHY_MAX)
        if dialog:
            n = raw.get("n")
            if not _is_int(n) or n not in shown or n in taken:
                continue
            taken.add(n)
            label = _flat(shown[n], LABEL_MAX)
            options.append({"label": label, "send": None, "n": n, "why": why,
                            "risky": raw.get("risky") is True or risky_words(label)})
        else:
            label, send = _flat(raw.get("label"), LABEL_MAX), _flat(raw.get("send"), SEND_MAX)
            if not label or not send:
                continue
            options.append({"label": label, "send": send, "n": None, "why": why,
                            "risky": raw.get("risky") is True or risky_words(send)})
    pick = data.get("pick")
    return {"where": where, "waits_for": _flat(data.get("waits_for"), WAITS_MAX), "about": _flat(data.get("about"), ABOUT_MAX),
            "options": options,
            "pick": pick if _is_int(pick) and 0 <= pick < len(options) else None}, cost


# ------------------------------------------------------------------ the guide

class Guide:
    def __init__(self, app: Any):
        self.app = app
        self.path = app.state_dir / FILE
        self.lock = threading.Lock()
        self.entries: dict[str, dict] = {}
        self.queue: collections.deque = collections.deque()       # (ref, manual)
        self.worker: threading.Thread | None = None
        self.auto_reads: collections.deque = collections.deque()  # when each auto read of the last hour started
        self.rev = 0

    # ------------------------------------------------------------ settings

    def defaults(self) -> dict:
        return dict(getattr(self.app.cfg, "session_guide", None) or DEFAULTS)

    def overrides(self) -> dict:
        data = read_json(self.path)
        return {k: v for k, v in (data.items() if isinstance(data, dict) else ()) if k in SWITCHES and isinstance(v, bool)}

    def settings(self) -> dict:
        return {**self.defaults(), **self.overrides()}

    def save(self, change: dict) -> None:
        if not isinstance(change, dict) or not change:
            raise GuideError(400, "invalid_argument", "nothing to change", "settings")
        for key, value in change.items():
            if key not in SWITCHES or not isinstance(value, bool):
                raise GuideError(400, "invalid_argument", f"{key} must be true or false", str(key)[:40])
        with self.lock:
            base = self.defaults()
            out = {**self.overrides(), **change}
            out = {k: v for k, v in out.items() if v != base.get(k)}
            if out:
                atomic_write_json(self.path, out)
            else:
                self.path.unlink(missing_ok=True)
            self.rev += 1
            if not self.settings()["enabled"]:
                self.entries = {}
                self.queue.clear()

    def reset(self) -> None:
        with self.lock:
            self.path.unlink(missing_ok=True)
            self.rev += 1
            if not self.settings()["enabled"]:
                self.entries = {}
                self.queue.clear()

    def state(self) -> dict:
        s = self.settings()
        with self.lock:
            entries = {ref: json.loads(json.dumps(e)) for ref, e in self.entries.items()}
            rev = self.rev
        return {"enabled": s["enabled"], "auto": s["auto"], "per_hour": s["per_hour"],
                "available": getattr(self.app.runner, "claude", None) is not None,
                "overridden": sorted(self.overrides()), "rev": rev, "entries": entries}

    def busy(self) -> bool:
        with self.lock:
            return self.worker is not None or bool(self.queue)

    # ------------------------------------------------------------ which tabs

    @staticmethod
    def wants(tab: dict) -> bool:
        # an idle tab asks nothing (model.is_idle): reading it would spend the hour's readings on a finished tab
        return (tab.get("state") in m.ATTENTION and not tab.get("is_control") and not tab.get("idle")
                and bool(tab.get("live", True)))

    def on_tabs(self, tabs_state: dict) -> None:
        """After each tab poll: drop the readings of tabs that no longer wait, and with auto queue a reading
        of every waiting tab whose question is new, within the hour's limit."""
        s = self.settings()
        if not s["enabled"]:
            with self.lock:
                if self.entries or self.queue:
                    self.entries, self.rev = {}, self.rev + 1
                    self.queue.clear()
            return
        tabs = [t for t in tabs_state.get("tabs") or [] if self.wants(t)]
        refs = {t["ref"] for t in tabs}
        screens = "screen" in self.app.driver_caps()
        now = self.app.clock()
        start = False
        changed = False
        with self.lock:
            for ref in list(self.entries):
                if ref not in refs and not self.entries[ref].get("running"):
                    del self.entries[ref]
                    changed = True
            while self.auto_reads and now - self.auto_reads[0] >= HOUR_MS:
                self.auto_reads.popleft()
            if s["auto"] and getattr(self.app.runner, "claude", None):
                queued = {r for r, _ in self.queue}
                for t in tabs:
                    if t.get("filed_by") or (screens and not t.get("ask")):
                        continue          # a filed result says enough; a question not read yet would be read twice
                    held = self.entries.get(t["ref"])
                    if (held and held.get("key") == key_of(t)) or t["ref"] in queued:
                        continue
                    if len(self.auto_reads) >= s["per_hour"]:
                        break
                    self.auto_reads.append(now)
                    self.queue.append((t["ref"], False))
                    start = True
            if changed:
                self.rev += 1
        if start:
            self._kick()
        elif changed:
            self.app.broadcast("guide", self.state())

    # ------------------------------------------------------------ reading

    def start(self, ref: str) -> bool:
        """The button: read this tab now. False when a reading of it is queued or runs."""
        s = self.settings()
        if not s["enabled"]:
            raise GuideError(409, "not_applicable", "the decision guide is switched off (cockpit.session_guide)")
        if getattr(self.app.runner, "claude", None) is None:
            raise GuideError(409, "not_applicable", "claude is not available")
        tab = next((t for t in self.app.tabs_state()["tabs"] if t["ref"] == ref), None)
        if tab is None:
            raise GuideError(404, "not_found", "no such tab", "tab_ref")
        if not self.wants(tab):
            raise GuideError(409, "not_applicable", "the tab does not wait for you", "tab_ref")
        with self.lock:
            if any(r == ref for r, _ in self.queue) or (self.entries.get(ref) or {}).get("running"):
                return False
            self.queue.append((ref, True))
        self._kick()
        return True

    def _kick(self) -> None:
        with self.lock:
            if self.worker is not None and self.worker.is_alive():
                return
            self.worker = threading.Thread(target=self._work, name="bridge-cockpit-guide", daemon=True)
            self.worker.start()

    def _work(self) -> None:
        while True:
            with self.lock:
                if not self.queue:
                    self.worker = None
                    return
                ref, manual = self.queue.popleft()
            try:
                self._read(ref, manual)
            except Exception as exc:  # noqa: BLE001 - one failed reading never stops the worker
                self.app.log_error(f"guide {ref}: {exc!r}")
                with self.lock:
                    if (self.entries.get(ref) or {}).get("running"):
                        self.entries[ref] = {**self.entries[ref], "running": False, "error": str(exc)[:200]}
                        self.rev += 1
                self.app.broadcast("guide", self.state())

    def _session_of(self, ref: str) -> dict | None:
        """The live session in a tab, with the task it is linked to (server.sessions_state)"""
        try:
            sessions = self.app.sessions_state()["sessions"]
        except Exception:  # noqa: BLE001 - an app without the links still finds the session
            sessions = self.app.sessions.state()
        return next((x for x in sessions if (x.get("tab") or {}).get("ref") == ref), None)

    def context_of(self, tab: dict) -> dict:
        """What Haiku reads of a tab: its session's first ask and last turns, else the end of its screen,
        and the task it belongs to; scrubbed."""
        app = self.app
        scrub = app.scrub
        session = self._session_of(tab["ref"]) or {}
        slug = session.get("task") or session.get("tab_slug") or tab.get("slug")
        headline = task_headline(app.root, slug)
        about = {"task": slug if headline else None, "task_title": scrub(headline) if headline else None,
                 "project": session.get("project")}
        if session.get("sid") and session.get("cwd"):
            base = getattr(app.sessions, "base", None) or claude_dir()
            path = transcript_path(Path(base), session["cwd"], session["sid"])
            turns = turns_of(read_tail(path, TAIL_BYTES))
            if turns["user"] or turns["said"]:
                first = first_ask(path)
                return {**{k: scrub(v) if isinstance(v, str) else v for k, v in turns.items()},
                        "first": scrub(first) if first else None, **about, "source": "transcript"}
        text, _digest, _err = app.tab_screen(tab["ref"])
        return {"title": None, "first": None, "prev": None, "user": None,
                "said": clean(scrub(text or ""), SCREEN_MAX, keep="end"), **about, "source": "screen"}

    @staticmethod
    def topic_of(context: dict) -> dict:
        """What the page shows of what a session is about before and beside Haiku's line"""
        return {"title": context.get("title"), "first": clean(context.get("first"), 300) or None,
                "task": context.get("task"), "task_title": context.get("task_title"), "project": context.get("project")}

    @staticmethod
    def read_of(context: dict) -> dict:
        """What Haiku read, as the page shows it under "What was read": the asks and the agent's last words
        (or the end of the screen), already scrubbed and capped"""
        return {"first": context.get("first"), "prev": context.get("prev"), "user": context.get("user"),
                "said": context.get("said"), "source": context.get("source")}

    @staticmethod
    def fallback_about(context: dict) -> str:
        """The line for `about` without Haiku's: the session's title, its task's headline, its first ask"""
        for value in (context.get("title"), context.get("task_title"), context.get("first"), context.get("user")):
            text = _flat(value or "", ABOUT_MAX)
            if text:
                return text
        return ""

    def _read(self, ref: str, manual: bool) -> None:
        app = self.app
        tab = next((t for t in app.tabs_state()["tabs"] if t["ref"] == ref), None)
        if tab is None or not self.wants(tab):
            with self.lock:
                self.entries.pop(ref, None)
                self.rev += 1
            app.broadcast("guide", self.state())
            return
        key = key_of(tab)
        base = {"ref": ref, "key": key, "state": tab["state"], "auto": not manual, "running": True,
                "started_ms": int(app.clock()), "at_ms": None, "error": None, "about": "", "topic": None, "read": None, "where": "",
                "waits_for": "", "options": [], "pick": None, "cost_usd": None, "source": None}
        with self.lock:
            self.entries[ref] = base
            self.rev += 1
        app.broadcast("guide", self.state())
        context = self.context_of(tab)
        # what the session is about shows at once, while Haiku still reads
        base = {**base, "source": context["source"], "topic": self.topic_of(context), "about": self.fallback_about(context),
                "read": self.read_of(context)}
        with self.lock:
            if (self.entries.get(ref) or {}).get("started_ms") == base["started_ms"]:
                self.entries[ref] = base
                self.rev += 1
        app.broadcast("guide", self.state())
        entry = dict(base)
        if not (context.get("user") or context.get("said")):
            entry.update(running=False, at_ms=int(app.clock()), error="nothing to read in this session yet")
        else:
            text = prompt(tab, context, app.cfg.language, getattr(app.cfg, "person_name", None))
            run = app.run(mr.haiku_argv(app.runner.claude, text), TIMEOUT)
            if not run.ok:
                err = (run.err or "").strip().splitlines()[-1:] or [f"exit {run.code}"]
                entry.update(running=False, at_ms=int(app.clock()), error=app.scrub(err[0])[:200] or "the reading failed")
            else:
                result, cost = parse(app.scrub(run.out), tab["state"], tab.get("ask"))
                if result is None:
                    entry.update(running=False, at_ms=int(app.clock()), cost_usd=cost, error="no usable answer")
                else:
                    entry.update(running=False, at_ms=int(app.clock()), cost_usd=cost,
                                 **{**result, "about": result["about"] or base["about"]})
        with self.lock:
            if (self.entries.get(ref) or {}).get("started_ms") == base["started_ms"]:
                self.entries[ref] = entry
                self.rev += 1
        app.broadcast("guide", self.state())
