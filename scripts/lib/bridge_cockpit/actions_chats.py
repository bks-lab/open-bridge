# SPDX-License-Identifier: MIT
"""Conversations: quick chats handed on or forgotten, A2A conversations, sessions linked to tasks, and
/api/ask, the question to Claude.
"""
from __future__ import annotations

import re
import uuid
from typing import Any

from . import model as m
from .quick import CONV_RE
from .relay import KINDS as ASK_KINDS
from .actions_base import (HANDOFF_MAX, HANDOFF_ORDER_MAX, SHORT_TIMEOUT, ActionError, Ctx, bad_arg, check_key,
                           check_text)


class ChatVerbs:
    """A part of Actions (actions.py), which holds the registry and the helpers called here."""

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
