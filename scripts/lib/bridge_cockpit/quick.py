# SPDX-License-Identifier: MIT
"""Quick questions of the cockpit: one short Claude session per question, read only, cheap.

"Ask Claude" no longer has to go to the long control session (Opus, a growing conversation, busy
with other work). A question starts `claude -p` with Haiku by default (Sonnet or Opus when picked),
in this Bridge's folder, with nothing but Read, Grep and Glob and without the user's settings, so it
can look at tasks, the board and the log and change nothing. A reply in the same window continues
that session (`--resume`). The CLI streams (`stream-json` with partial messages): the text so far and
what it is reading go to the page as the `quick_live` event, at most every LIVE_EVERY seconds, so an
answer shows while it is written. An event carries only the text added since the one before (`at` says
where it goes, `seq` orders them); a new message in the stream sends its text whole (`full`), and so does
the `quick_live` key of the state a page gets when it connects, so a page that comes late still has all
of it. The final answer, the model that really answered and the cost come
from the closing `result` line; `total_cost_usd` is the sum of the whole session, so a turn costs the
difference. Each question runs on a thread of its own; the page gets the conversations as the `quick`
event. The conversations are kept in the state dir (quick.json), so a chat goes on after a restart.
When the answer turns into work, the page hands it on: "Do it" starts an agent tab (Sonnet or more,
the workplace config), or it goes to the control session. The conversation then carries `handed`: where it
went, when, and how that went (`starting` while it is handed on, then the launch outcome or the relay's
`queued` / `offline`, `failed` on any error), so the page shows a status line instead of a silent click.

A free question may come with `context`: what the page shows right now (logic.js situationText). It goes
into the system text of that one turn as a block labelled as data, sent fresh with every turn, and is never
kept: not in `turns`, not in quick.json, not in a transcript.

A chat may be about something: `about` names the briefing row it was asked on and the inbox item or task
behind it, or the inbox item it was handed on as. Once that item has ended after the chat started (an inbox
item closed, executed, dropped or rejected and not reopened, a task moved to work/done/) and the chat has
been quiet for SETTLE_QUIET_MS, the sweep takes it into the archive (why `settled`). The sweep rides on the
tab poll, reads the files at most every SETTLE_EVERY_MS unless a verb that ends an item asked for it
(settle_soon), and never touches a chat that is answering, has no item, or changed while it read.
"""
from __future__ import annotations

import json
import re
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from .. import ai_services as ai
from . import returns as ret
from .text import TABLES

MODELS = dict(ai.CLAUDE_MODELS)
DEFAULT_MODEL = "haiku"
TOOLS = "Read,Grep,Glob"
QUICK_TIMEOUT = 180
MAX_CONVS = 30
MAX_TURNS = 30
LIVE_EVERY = 0.3
LIVE_KEEP = 20000        # the most of a live text a page is sent in one piece
SETTLE_EVERY_MS = 60_000     # the settle sweep reads the item files at most this often on plain polls
SETTLE_QUIET_MS = 600_000    # a chat about an item that ended leaves only after this long untouched
OUTPUT = ["--output-format", "stream-json", "--verbose", "--include-partial-messages"]
SESSION_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
CONV_RE = re.compile(r"^q[0-9a-f]{10}\Z")
SYSTEM = {code: TABLES[code]["quick_system"] for code in TABLES}   # the words live in text.py
NOBODY = {code: TABLES[code]["quick_nobody"] for code in TABLES}   # the words live in text.py


def system_text(lang: str, who: str | None, can_launch: bool = True, today: str | None = None) -> str:
    """The system text in the dashboard's language, naming the person from cockpit.person_name. It names the
    agent tab the chat hands work to, or says no terminal can start one yet (`can_launch`): a chat that only
    knew it may read told the person the Bridge cannot act and handed them the steps (18.10.)."""
    lang = lang if lang in SYSTEM else "en"
    words = TABLES[lang]
    launch = words["quick_launch_on" if can_launch else "quick_launch_off"].format(do_it=words["btn_do"])
    # without a name the person is "the user", in the grammatical case each sentence needs
    return SYSTEM[lang].format(who=who or NOBODY[lang], who_subject=who or words["quick_nobody_subject"],
                               launch=launch, today=today or "unknown")


# how a conversation is written out: as history for a new session, and handed on as work
FRAME = {code: TABLES[code]["quick_frame"] for code in TABLES}   # the words live in text.py


def resolve_claude() -> str | None:
    """The installed CLI first: `which` inside a cmux tab finds cmux's wrapper for that one terminal."""
    local = Path.home() / ".local" / "bin" / "claude"
    if local.exists():
        return str(local)
    return shutil.which("claude")


def argv_ok(argv: list[str], claude: str | None, models=None) -> bool:
    """The only shape the runner lets through for this program: print mode, a known model, the three
    read tools, no user settings, JSON out, optionally one resume and the system text, then the prompt."""
    if not claude or len(argv) < 14 or argv[0] != claude or argv[1] != "-p":
        return False
    fixed = argv[2:12]
    if fixed[0] != "--model" or fixed[1] not in (models or MODELS.values()) or fixed[2:] != [
            "--setting-sources", "", "--tools", TOOLS, *OUTPUT]:
        return False
    rest = argv[12:]
    if rest[:1] == ["--resume"]:
        if len(rest) < 2 or not SESSION_RE.match(rest[1]):
            return False
        rest = rest[2:]
    if rest[:1] == ["--append-system-prompt"]:
        rest = rest[2:]
    return len(rest) == 2 and rest[0] == "--"


def build_argv(claude: str, model: str, prompt: str, system: str, session: str | None = None,
               actual_model: str | None = None) -> list[str]:
    argv = [claude, "-p", "--model", actual_model or MODELS[model], "--setting-sources", "", "--tools", TOOLS, *OUTPUT]
    if session:
        argv += ["--resume", session]
    return argv + ["--append-system-prompt", system, "--", prompt]


def result_of(out: str) -> dict | None:
    """The closing `result` object: the whole output when it is one JSON document, else the last line
    of the stream that is one."""
    try:
        data = json.loads(out)
        if isinstance(data, dict):
            return data
    except ValueError:
        pass
    for line in reversed(out.splitlines()):
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("type") == "result":
            return data
    return None


def parse_answer(out: str) -> dict | None:
    """The result of `claude -p`: answer text, session, cost of the session so far, the model that
    answered (the largest share in modelUsage)."""
    data = result_of(out)
    if not isinstance(data, dict) or not isinstance(data.get("result"), str):
        return None
    raw = data.get("modelUsage")
    usage: dict = raw if isinstance(raw, dict) else {}
    answered = max(usage, key=lambda k: usage[k].get("costUSD", 0) if isinstance(usage[k], dict) else 0, default=None)
    cost = data.get("total_cost_usd")
    return {"text": data["result"].strip(), "session": data.get("session_id") if isinstance(data.get("session_id"), str) else None,
            "total_usd": float(cost) if isinstance(cost, (int, float)) and not isinstance(cost, bool) else None,
            "model": answered, "error": bool(data.get("is_error"))}


class Live:
    """Reads the stream of one answer: the text of the message being written and what it is reading."""

    def __init__(self, root: Path | None = None):
        self.root = str(root) + "/" if root else None
        self.text = ""
        self.doing: str | None = None

    def feed(self, line: str) -> bool:
        """Takes one line; True when what the page shows changed."""
        try:
            data = json.loads(line)
        except ValueError:
            return False
        if not isinstance(data, dict):
            return False
        if data.get("type") == "stream_event":
            ev = data.get("event") if isinstance(data.get("event"), dict) else {}
            if ev.get("type") == "message_start":
                self.text = ""
                return False
            delta = ev.get("delta") if isinstance(ev.get("delta"), dict) else {}
            if ev.get("type") == "content_block_delta" and delta.get("type") == "text_delta" and isinstance(delta.get("text"), str):
                self.text += delta["text"]
                self.doing = None
                return True
            return False
        if data.get("type") == "assistant":
            msg = data.get("message") if isinstance(data.get("message"), dict) else {}
            for block in msg.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    self.doing = self.describe(block)
                    return True
        return False

    def describe(self, block: dict) -> str:
        args = block.get("input") if isinstance(block.get("input"), dict) else {}
        what = next((str(args[k]) for k in ("file_path", "pattern", "path") if isinstance(args.get(k), str)), "")
        if self.root and what.startswith(self.root):
            what = what[len(self.root):]
        return f"{block.get('name') or '?'} {what}".strip()[:160]


class Quick:
    def __init__(self, app: Any, claude: str | None = "auto"):
        self.app = app
        self.claude = resolve_claude() if claude == "auto" else claude
        self.codex = getattr(getattr(app, "runner", None), "codex", None)
        self.lock = threading.Lock()
        self.convs: dict[str, dict] = {}
        self.expire_failed_ms = 0
        self.settle_at_ms = 0            # when the settle sweep last read the files
        self.settle_due = False          # a verb ended or reopened an item: the next poll sweeps at once
        self.live: dict[str, dict] = {}      # per running conversation what the pages were sent: text, doing, seq
        self.seq = 0
        self.path = Path(app.state_dir) / "quick.json" if getattr(app, "state_dir", None) else None
        self.load()

    def load(self) -> None:
        """The kept conversations; an answer that was running when the server stopped says so."""
        if self.path is None:
            return
        from .store import read_json
        data = read_json(self.path)
        for c in data if isinstance(data, list) else []:
            if not isinstance(c, dict) or not isinstance(c.get("id"), str) or not CONV_RE.match(c["id"]):
                continue
            if not isinstance(c.get("turns"), list) or not c["turns"]:
                continue
            if c.get("running"):
                c["running"] = False
                last = c["turns"][-1]
                if isinstance(last, dict) and last.get("a") is None and not last.get("error"):
                    last["error"] = "interrupted"
            handed = c.get("handed")
            if isinstance(handed, dict) and handed.get("status") == "starting":
                # the server stopped in the middle of handing it on: nothing will end that claim now, so it
                # reads as failed and the chat can be handed on again
                handed["status"] = "failed"
            c.setdefault("about", None)
            self.convs[c["id"]] = c

    def save(self) -> None:
        """Called under the lock."""
        if self.path is None:
            return
        from .store import atomic_write_json
        try:
            atomic_write_json(self.path, sorted(self.convs.values(), key=lambda c: c["started_ms"]), mode=0o600)
        except OSError as exc:
            self.app.log_error(f"quick: not kept: {exc!r}")

    def selection(self, model: str | None = None) -> tuple[str, str, str | None]:
        chosen = ai.select(self.app.root, "briefing-chat", DEFAULT_MODEL)
        if model is None:
            if chosen.provider == "codex":
                model = "codex"
            else:
                model = next((k for k, v in MODELS.items() if v == chosen.model), "claude")
        if model not in (*MODELS, "claude", "codex"):
            raise ValueError("unknown model")
        provider = "codex" if model == "codex" else "claude"
        selected = ai.select(self.app.root, "briefing-chat", DEFAULT_MODEL, provider=provider)
        actual = MODELS[model] if model in MODELS else selected.model
        return model, provider, actual

    def available(self, model: str | None = None) -> bool:
        _, provider, _ = self.selection(model)
        return bool(self.codex if provider == "codex" else self.claude)

    def expire(self, now: int) -> None:
        """Called under the lock: a chat untouched for cockpit.chat_keep_hours goes to the archive."""
        hours = getattr(getattr(self.app, "cfg", None), "chat_keep_hours", 24)
        if not hours or now - self.expire_failed_ms < 3600 * 1000:
            return
        cutoff = now - hours * 3600 * 1000
        gone = False
        for c in list(self.convs.values()):
            if c.get("running") or (c.get("last_ms") or c["started_ms"]) >= cutoff:
                continue
            if not self._archive(c, "expired", now):
                self.expire_failed_ms = now   # the archive is down: keep them all, try again in an hour
                break
            del self.convs[c["id"]]
            gone = True
        if gone:
            self.save()

    def state(self) -> dict:
        with self.lock:
            self.expire(int(self.app.clock()))
            convs = sorted(self.convs.values(), key=lambda c: c.get("last_ms") or c["started_ms"], reverse=True)
            config_error = None
            try:
                default, _, _ = self.selection()
            except ValueError as exc:
                default, config_error = DEFAULT_MODEL, str(exc)
            models = list(MODELS) + ["codex"]
            if default == "claude":
                models.insert(0, "claude")
            return {"available": bool(self.claude or self.codex), "default": default, "models": models,
                    "keep_hours": getattr(getattr(self.app, "cfg", None), "chat_keep_hours", 24),
                    "config_error": config_error,
                    "providers": {"claude": bool(self.claude), "codex": bool(self.codex)},
                    "convs": json.loads(json.dumps(convs))}

    def start(self, prompt: str, model: str | None, conv: str | None = None, kind: str = "free",
              place: str | None = None, context: str | None = None, about: dict | None = None) -> str:
        """Ask in a new conversation, or go on in `conv`; returns the conversation id at once. A new one with
        `place` "core" (the start page's core) takes the place of the last: it goes to the archive. `about`
        (a new one only) names the row and the item it is about, for the settle sweep."""
        model, provider, actual_model = self.selection(model)
        now = int(self.app.clock())
        with self.lock:
            if conv is not None:
                c = self.convs.get(conv)
                if c is None:
                    raise KeyError("no such conversation")
                if c["running"]:
                    raise RuntimeError("this conversation is still answering")
                if len(c["turns"]) >= MAX_TURNS:
                    raise RuntimeError("this conversation is long enough, start a new one")
            else:
                conv = "q" + uuid.uuid4().hex[:10]
                c = {"id": conv, "kind": kind, "started_ms": now, "session": None, "total_usd": 0.0, "turns": [],
                     "running": False, "last_ms": now, "about": dict(about) if about else None}
                if place:
                    c["place"] = place
                    for old in [x for x in self.convs.values() if x.get("place") == place and not x["running"]]:
                        if not self._archive(old, "replaced", now):
                            break
                        del self.convs[old["id"]]
                self.convs[conv] = c
                for old in sorted(self.convs.values(), key=lambda x: x["started_ms"])[:-MAX_CONVS]:
                    if old["running"]:
                        continue
                    if not self._archive(old, "overflow", now):
                        break             # the archive is down: keep them all, try again at the next start
                    del self.convs[old["id"]]
            # a resumed session keeps its model: a switch starts the reply in a new session with the history
            last = c["turns"][-1] if c["turns"] else {}
            # A failed switch must never attach the old provider's id to the new provider.
            owner = c.get("session_provider", "claude")
            same_model = c.get("session_model", MODELS.get(last.get("model_asked"))) == actual_model
            session = c["session"] if last.get("a") and owner == provider and same_model else None
            history = "" if session or not c["turns"] else self._history(c)
            c["turns"].append({"q": prompt, "a": None, "model_asked": model, "model": None, "cost_usd": None,
                               "provider": provider, "at_ms": now, "error": None})
            c["running"] = True
            c["last_ms"] = now
            self.save()
        thread = threading.Thread(target=self._run, args=(conv, model, history + prompt, session, provider, actual_model),
                                  kwargs={"context": context}, name="bridge-cockpit-quick", daemon=True)
        thread.start()
        self.app.broadcast("quick", self.state())
        return conv

    def claim_handoff(self, conv: str, to: str, now: float) -> dict:
        """Mark `conv` as being handed on to `to`; RuntimeError("handoff_running") while an earlier handoff is
        still starting. Any finished one (started, failed, offline, ...) may be followed by another."""
        with self.lock:
            c = self.convs.get(conv)
            if c is None:
                raise KeyError("no such conversation")
            if (c.get("handed") or {}).get("status") == "starting":
                raise RuntimeError("handoff_running")
            c["handed"] = {"to": to, "at_ms": int(now), "status": "starting"}
            self.save()
            handed = dict(c["handed"])
        self.app.broadcast("quick", self.state())
        return handed

    def set_handed(self, conv: str, **fields: Any) -> dict | None:
        """How the handoff went: the fields go onto the record, it is kept, and the pages are told."""
        with self.lock:
            c = self.convs.get(conv)
            if c is None or not isinstance(c.get("handed"), dict):
                return None
            c["handed"].update(fields)
            self.save()
            handed = dict(c["handed"])
        self.app.broadcast("quick", self.state())
        return handed

    def set_about(self, conv: str, about: dict) -> bool:
        """Name what a chat is about when it names no item yet (a handed chat: the inbox item it became). A chat
        from an info row nobody filed has an `about` without an item: that one takes the handed item too."""
        with self.lock:
            c = self.convs.get(conv)
            old = c.get("about") if c is not None else None
            if c is None or isinstance(old, dict) and (old.get("inbox") or old.get("task")):
                return False
            c["about"] = dict(about)
            self.save()
        return True

    def settle_soon(self) -> None:
        """An item ended or came back: the next tab poll sweeps without waiting for the minute."""
        self.settle_due = True

    def sweep_settled(self, now: float, force: bool = False) -> bool:
        """Chats about an item that has ended since the chat started go to the archive (why `settled`), once
        they have been quiet for SETTLE_QUIET_MS. Reads files outside the lock and checks again under it that
        nothing changed meanwhile. True when a chat left."""
        now = int(now)
        if not force and not self.settle_due and now - self.settle_at_ms < SETTLE_EVERY_MS:
            return False
        if now - self.expire_failed_ms < 3600 * 1000:
            return False                  # the archive refused lately: try again after the back-off
        self.settle_at_ms, self.settle_due = now, False
        with self.lock:
            candidates = [(c["id"], c.get("last_ms") or c["started_ms"], c["started_ms"], dict(c["about"]))
                          for c in self.convs.values()
                          if not c.get("running") and isinstance(c.get("about"), dict)
                          and (c["about"].get("inbox") or c["about"].get("task"))]
        root = self.app.root
        settled = []
        for cid, last, started, about in candidates:
            if now - last < SETTLE_QUIET_MS:
                continue
            inbox, task = about.get("inbox"), about.get("task")
            if inbox:
                at = ret.ended_at(root, str(inbox))
                ended = at is not None and at >= started
            else:
                ended = ret.task_done(root, str(task))
            if ended:
                settled.append((cid, last, about))
        if not settled:
            return False
        gone = False
        with self.lock:
            for cid, last, about in settled:
                c = self.convs.get(cid)
                # a new question, a reply or a handoff while the files were read: it stays
                if c is None or c.get("running") or (c.get("last_ms") or c["started_ms"]) != last or c.get("about") != about:
                    continue
                if not self._archive(c, "settled", now):
                    self.expire_failed_ms = now   # the archive is down: keep them, try again in an hour
                    break
                del self.convs[cid]
                gone = True
            if gone:
                self.save()
        return gone

    def forget(self, conv: str) -> None:
        """Take a chat off the list into the archive; one still answering stays until it is done."""
        with self.lock:
            c = self.convs.get(conv)
            if c is None:
                raise KeyError("no such conversation")
            if c.get("running"):
                raise RuntimeError("this conversation is still answering")
            if not self._archive(c, "removed", int(self.app.clock())):
                raise RuntimeError("the archive cannot be written, the chat stays")
            del self.convs[conv]
            self.save()
        self.app.broadcast("quick", self.state())

    def _archive(self, c: dict, why: str, now: int) -> bool:
        """Called under the lock: True when the chat is kept in the archive (or there is no state dir)."""
        if self.path is None:
            return True
        from .store import archive_conv
        try:
            archive_conv(self.path.parent, "quick", c, why, now)
            return True
        except OSError as exc:
            self.app.log_error(f"quick: not archived: {exc!r}")
            return False

    def live_state(self) -> dict:
        """The live text of every answer being written, whole: for a page that connects in the middle"""
        with self.lock:
            return {conv: {"conv": conv, "seq": x["seq"], "at": max(0, len(x["text"]) - LIVE_KEEP),
                           "text": x["text"][-LIVE_KEEP:], "doing": x["doing"], "full": True}
                    for conv, x in self.live.items()}

    def live_event(self, conv: str, text: str, doing: str | None) -> dict:
        """The next `quick_live` payload of `conv`: the text added since the last one, or all of it when
        the stream started a new message. Numbered and kept under the lock, so live_state() and the
        events agree on what a page has"""
        with self.lock:
            self.seq += 1
            was = self.live.get(conv, {}).get("text", "")
            self.live[conv] = {"text": text, "doing": doing, "seq": self.seq}
            if text.startswith(was):
                return {"conv": conv, "seq": self.seq, "at": len(was), "text": text[len(was):], "doing": doing}
            return {"conv": conv, "seq": self.seq, "at": max(0, len(text) - LIVE_KEEP), "text": text[-LIVE_KEEP:],
                    "doing": doing, "full": True}

    def lang(self) -> str:
        lang = str(getattr(self.app.cfg, "language", "de"))[:2]
        return lang if lang in SYSTEM else "en"

    def _can_launch(self) -> bool:
        """Whether the terminal driver can start an agent tab, the same answer launch() goes by; an error while
        asking counts as able, so a hiccup never makes the chat say the Bridge has no terminal"""
        caps = getattr(self.app, "driver_caps", None)
        try:
            return caps is None or "launch" in caps()
        except Exception:  # noqa: BLE001 - asking the driver must never cost the answer
            return True

    def _history(self, c: dict) -> str:
        f = FRAME[self.lang()]
        parts = [f"{f['q']}: {t['q']}\n{f['a']}: {t['a']}" for t in c["turns"] if t.get("a")]
        return (f"{f['history']}:\n" + "\n\n".join(parts) + f"\n\n{f['new']}: ") if parts else ""

    def _run(self, conv: str, model: str, prompt: str, session: str | None,
             provider: str = "claude", actual_model: str | None = None, context: str | None = None) -> None:
        app = self.app
        system = system_text(self.lang(), getattr(app.cfg, "person_name", None), self._can_launch(),
                             time.strftime("%Y-%m-%d", time.localtime(app.clock() / 1000)))
        if context:
            # what the page shows, as data after the system text, fresh on every turn and kept nowhere
            system += "\n\n" + TABLES[self.lang()]["quick_situation"].format(text=app.scrub(context))
        live = ai.CodexStream() if provider == "codex" else Live(getattr(app, "root", None))
        sent = [0.0]

        def on_line(line: str) -> None:
            if not live.feed(line):
                return
            now = time.monotonic()
            if now - sent[0] >= LIVE_EVERY:
                sent[0] = now
                app.broadcast("quick_live", self.live_event(conv, live.text, live.doing))

        try:
            if provider == "codex":
                argv = ai.codex_argv(self.codex or "", system + "\n\n" + prompt, actual_model, session)
            else:
                argv = build_argv(self.claude or "", model, prompt, system, session, actual_model)
            run = app.run(argv, QUICK_TIMEOUT, on_line)
            answer = (ai.parse_codex(run.out) if provider == "codex" else parse_answer(run.out)) if run.ok else None
            with self.lock:
                c = self.convs.get(conv)
                if c is None:
                    return
                turn = c["turns"][-1]
                if answer is None or answer["error"]:
                    lines = (run.err or "").strip().splitlines()
                    err = (answer or {}).get("text") or (lines[-1] if lines else "no answer")
                    turn["error"] = app.scrub(err)[:300]
                else:
                    if session is None:
                        c["total_usd"] = 0.0      # a new session counts from zero
                    turn["a"] = answer["text"][:20000]
                    turn["model"] = (answer["model"] or actual_model or provider).replace("claude-", "")
                    turn["usage"] = answer.get("usage")
                    if answer["total_usd"] is not None:
                        turn["cost_usd"] = round(max(0.0, answer["total_usd"] - c["total_usd"]), 6)
                        c["total_usd"] = answer["total_usd"]
                    sid = answer["session"] or (session if provider == "codex" else None)
                    c["session"] = sid if isinstance(sid, str) and SESSION_RE.match(sid) else None
                    c["session_provider"], c["session_model"] = provider, actual_model
        except Exception as exc:  # noqa: BLE001 - a failed question must never leave `running` set
            app.log_error(f"quick: {exc!r}")
            with self.lock:
                c = self.convs.get(conv)
                if c:
                    c["turns"][-1]["error"] = str(exc)[:300]
        finally:
            with self.lock:
                self.live.pop(conv, None)
                if conv in self.convs:
                    self.convs[conv]["running"] = False
                    self.convs[conv]["last_ms"] = int(app.clock())
                self.save()
            app.broadcast("quick_live", {"conv": conv, "text": None, "doing": None})
            app.broadcast("quick", self.state())

    def transcript(self, conv: str) -> str | None:
        """The conversation as plain text, to hand on to an agent tab or the control session."""
        f = FRAME[self.lang()]
        with self.lock:
            c = self.convs.get(conv)
            if not c:
                return None
            return "\n\n".join(f"{f['q']}: {t['q']}\n{f['a']} ({t['model'] or t['model_asked']}): {t['a'] or ''}"
                               for t in c["turns"] if t.get("a"))

    def first_question(self, conv: str) -> str:
        with self.lock:
            c = self.convs.get(conv)
            return str(c["turns"][0]["q"]).strip().split("\n", 1)[0] if c and c["turns"] else ""
