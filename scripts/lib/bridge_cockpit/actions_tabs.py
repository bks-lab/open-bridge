# SPDX-License-Identifier: MIT
"""Verbs on agent tabs through the terminal driver: adopt, press, send, jump, close, the control tab, the
layout snapshot, and a relay question handed to the control tab.
"""
from __future__ import annotations

import sys

from . import model as m
from . import returns as ret
from .actions_base import (CMUX_TIMEOUT, LAUNCH_TIMEOUT, LIST_TIMEOUT, SHORT_TIMEOUT, SNAPSHOT_TIMEOUT, TAB_REF_RE,
                           ActionError, Ctx)


class TabVerbs:
    """A part of Actions (actions.py), which holds the registry and the helpers called here."""

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

    def press(self, ctx: Ctx, tab_ref: str, key: str, said: str) -> None:
        tab = self.tab(tab_ref)
        if tab["state"] != "needs-you":
            raise self.not_applicable("the tab is not asking", "tab_ref")
        # The state on the page may be seconds old: if the tab has moved on, Esc would abort its work.
        self.app.tabs.poll()
        now_tab = self.app.tabs.find(tab_ref)
        if not now_tab or now_tab["state"] != "needs-you":
            ctx.note(self.tx["not_asking"].format(name=m.short(tab["name"], 30)))
            return
        run = ctx.call("workplace.key", tab_ref, self.app.workplace("key", tab_ref, key), CMUX_TIMEOUT)
        if run.ok:
            ctx.note(self.tx["key_sent"].format(name=m.short(tab["name"], 30), said=said))
        else:
            ctx.note(self.tx["key_failed"].format(err=m.short(run.err.strip(), 100)), bad=True)
        ctx.tabs_after(3)

    def v_tab_yes(self, ctx: Ctx, tab_ref: str) -> None:
        self.press(ctx, tab_ref, "1", self.tx["said_yes"])

    def v_tab_no(self, ctx: Ctx, tab_ref: str) -> None:
        self.press(ctx, tab_ref, "escape", self.tx["said_no"])

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

    def v_tab_send(self, ctx: Ctx, tab_ref: str, text: str) -> None:
        tab = self.tab(tab_ref)
        if not m.is_live(tab):
            raise self.not_applicable("the tab holds no agent", "tab_ref")
        self.send_to(ctx, tab, text)

    def v_tab_go_on(self, ctx: Ctx, tab_ref: str) -> None:
        tab = self.tab(tab_ref)
        if tab["state"] != "waiting" or m.filed_by(tab, self.app.collector.view) is not None:
            raise self.not_applicable("go on is for waiting tabs without a filed result", "tab_ref")
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
