# SPDX-License-Identifier: MIT
"""Conversations: quick chats handed on or forgotten, A2A conversations, sessions linked to tasks, and
/api/ask, the question to Claude.
"""
from __future__ import annotations

import re
import uuid
from typing import Any

from . import model as m
from .history import item as history_item
from .quick import CONV_RE
from .relay import KINDS as ASK_KINDS
from .actions_base import (CONTEXT_MAX, HANDOFF_MAX, HANDOFF_ORDER_MAX, INBOX_ID_RE, SHORT_TIMEOUT, ActionError, Ctx,
                           bad_arg, check_key, check_text)


class ChatVerbs:
    """A part of Actions (actions.py), which holds the registry and the helpers called here."""

    def v_quick_handoff(self, ctx: Ctx, conv: str, to: str, text: str | None = None) -> None:
        """A quick conversation becomes work: "tab" files it to the inbox and starts an agent tab on it
        (the workplace's agent model, Sonnet or more, never the quick model), "control" gives it to the
        control session through the relay. The chat carries how that went (quick.py `handed`): claimed as
        `starting` once every check passed, then the launch outcome or the relay's queued / offline, and
        `failed` whatever goes wrong on the way, so a second click is refused only while one is starting."""
        app = self.app
        order = (text or "").strip()
        if len(order) > HANDOFF_ORDER_MAX:
            # refused, never trimmed: a cut order would start the work on half the instruction
            raise bad_arg("text", f"length must be 1 to {HANDOFF_ORDER_MAX}")
        text = app.quick.transcript(conv)
        if not text:
            raise ActionError(409, "stale_row", "the conversation has no answer yet", "conv")
        # what the person adds on handing on is the order, kept whole at the end
        text = f"{text[:HANDOFF_MAX - len(order) - 2]}\n\n{order}" if order else text[:HANDOFF_MAX]
        if to == "control" and not app.cfg.relay:
            raise self.not_applicable("no control session: the relay is off", "to")
        try:
            app.quick.claim_handoff(conv, to, app.clock())
        except KeyError:
            raise ActionError(409, "stale_row", "the conversation is gone", "conv") from None
        except RuntimeError:
            raise ActionError(409, "handoff_running", self.tx["handoff_running"], "conv") from None
        done: dict = {"status": "failed"}
        try:
            if to == "control":
                record, online = self.ask_relay(ctx, "free", self.tx["handoff_control"].format(text=text))
                if not online:
                    ctx.note(self.tx["handoff_offline"], bad=True)
                done = {"status": "queued" if online else "offline", "relay_id": record.get("id")}
                return
            first = app.quick.first_question(conv)
            new_id = self.inbox_add(ctx, conv, first, text)
            if new_id is None:
                return
            done = {"status": "failed", "inbox_id": new_id}
            # a chat that is about nothing yet is now about this item: it leaves when the item ends
            app.quick.set_about(conv, {"kind": "handoff", "inbox": new_id})
            got = self.launch(ctx, [{"key": f"inbox:{new_id}", "inbox_id": new_id, "title": first}], "go", app.cfg.target)
            done = {"status": got, "inbox_id": new_id}
            if got == "busy" and order:
                # the tab of this chat is already on its way: the new words reach the item as a note, not that tab
                ctx.call("inbox.note", new_id, self.inbox("note", new_id, "--", order[:2000]), SHORT_TIMEOUT)
                ctx.note(self.tx["handoff_order_late"], bad=True)
        finally:
            handed = app.quick.set_handed(conv, **done)
            if handed is not None:
                ctx.extra["handed"] = handed
            ctx.audit_extra["handed"] = done["status"]

    def v_chat_tab(self, ctx: Ctx, text: str, routed: str | None = None) -> None:
        """A problem from the chat that needs a session able to act: filed as a decision and started at
        once as an agent tab (the workplace's model and target), with no quick answer in between. The reply
        names the inbox item and the launch outcome, for the status line under the chat."""
        if routed:
            ctx.audit_extra["routed"] = routed
        first = text.strip().splitlines()[0]
        ctx.extra.update({"inbox_id": None, "launch": "failed"})
        new_id = self.inbox_add(ctx, f"chat-{uuid.uuid4().hex[:10]}", first, text.strip())
        if new_id is not None:
            ctx.extra["inbox_id"] = new_id
            ctx.extra["launch"] = self.launch(ctx, [{"key": f"inbox:{new_id}", "inbox_id": new_id, "title": first}], "go",
                                              self.app.cfg.target)

    def v_chat_remind(self, ctx: Ctx, text: str, until: str | None = None) -> None:
        """A reminder the chat proposed ([[remind: ...]]), filed on the person's click as a free inbox item; with a
        day it stays out of sight until then, like "Later". The chat itself never writes (18.10.: "remind me" had
        no way at all)."""
        new_id = self.inbox_add(ctx, f"remind-{uuid.uuid4().hex[:10]}", text, self.tx["remind_detail"])
        if new_id is None:
            return
        title = m.short(text, 60)
        if until:
            key = f"inbox:{new_id}"
            self.app.store.hide(key, until)
            ctx.history.append(history_item(key, text, "other", f"hidden until {until}"))
            ctx.note(self.tx["remind_until"].format(until=until, title=title))
        else:
            ctx.note(self.tx["remind_now"].format(title=title))
        ctx.delta()

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

    def info_inbox(self, sec: dict, info: dict) -> str | None:
        """The inbox item a page row stands for, found the way page_item_entry and file_page_item key it."""
        if not info.get("id"):
            return None
        profile = self.app.collector.view_profile() or ""
        same = f":{sec['id']}:{info['id']}"
        return self.filed_page_item(f"briefing:{profile}{same}" if profile else "", same)

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
        # may come along, never required: what the page shows right now, for a free quick question only
        optional = {"free": {"context"}}.get(kind, set())
        for name in args:
            if name not in allowed and name not in optional:
                raise bad_arg(str(name)[:40], "unknown argument")
        for name in allowed:
            if name not in args:
                raise bad_arg(name, "missing")
        context = args.get("context")
        if context is not None:
            if via != "quick":
                raise bad_arg("context", "only for a free quick question")
            if not isinstance(context, str) or "\x00" in context:
                raise bad_arg("context", "must be a string")
            if len(context) > CONTEXT_MAX:
                # refused, never cut: half a picture reads as the whole of it
                raise bad_arg("context", f"length must be at most {CONTEXT_MAX}")
            context = context.strip() or None
        model = app.collector.model
        about = None                     # the row and the item a quick chat is about: it leaves when that ends
        if kind in ("row", "follow_up"):
            row = self.entry(check_key(args["key"], "key"))["row"]
            prompt = m.ask_about(row, tx) if kind == "row" else m.follow_up(row, tx)
            item = m.launch_item(row)
            if item:
                about = {"kind": kind, "key": row["key"], **({"inbox": item} if INBOX_ID_RE.match(item) else {"task": item})}
        elif kind == "info":
            page, section, index = args["page"], args["section"], args["index"]
            if not isinstance(page, str) or not isinstance(section, str) or not isinstance(index, int) or isinstance(index, bool):
                raise bad_arg("index", "page and section are strings, index an integer")
            found = app.collector.page_item(page, section, index)
            if not found:
                raise ActionError(409, "stale_row", "the page item is no longer in the model", "index")
            sec, info = found
            prompt = m.ask_info(re.sub(r"\s*\(.*?\)", "", sec["title"]), info, tx)
            about = {"kind": "info", "key": m.item_key(page, sec["id"], info),
                     "inbox": self.info_inbox(sec, info) if via == "quick" else None}
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
                conv_id = app.quick.start(prompt, qmodel, conv, kind, place, context=context, about=about)
            except KeyError:
                raise ActionError(409, "stale_row", "the conversation is gone", "conv")
            except RuntimeError as exc:
                raise ActionError(409, "not_applicable", str(exc), "conv")
            self.audit_line("ask", kind, via="quick", conv=conv_id, model=qmodel, chars=len(prompt),
                            **({"context_chars": len(context)} if context else {}))
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
