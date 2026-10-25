# SPDX-License-Identifier: MIT
"""Verbs on agent tabs through the terminal driver: adopt, press, answer an option, send, jump, close, rename a
tab or a workspace, organize with AI, the control tab, the layout snapshot, and a relay question handed to the
control tab.
"""
from __future__ import annotations

import re
import sys

from .. import ai_services as ai
from . import asks as ak
from . import model as m
from . import organize as og
from . import returns as ret
from .quick import MODELS
from .actions_base import (CMUX_TIMEOUT, LAUNCH_TIMEOUT, LIST_TIMEOUT, SHORT_TIMEOUT, SNAPSHOT_TIMEOUT, TAB_REF_RE,
                           ActionError, Ctx, bad_arg)


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
            ctx.note(self.tx["adopted"].format(tab=m.short(tab["name"], 30), title=m.short(row["title"], 40)),
                     go={"kind": "item", "key": f"task:{slug}"})
        else:
            ctx.note(self.tx["adopt_failed"].format(err=m.short(run.err, 100)), bad=True)
        ctx.tabs_after(0)

    def guard_fresh(self, ctx: Ctx, ref: str, expect: str | None, seen: str | None, name: str | None,
                    sends_text: bool) -> tuple[dict, dict | None]:
        """A reply reaches only the tab and the question it was given for. The tabs are polled again (no
        question is read there), then the tab must still be there, carry the name and the state the page
        named, and, with `seen`, its screen read now must ask the question of that hash (never the one
        kept by the poll). A draft typed in the tab refuses a reply that types text, with or without
        `seen` (read fresh wherever the driver serves screens). Nothing is sent on any refusal. Returns the tab as it is now and the question read now (None without `seen`)."""
        self.app.tabs.poll(asks=False)
        t = self.app.tabs.find(ref)
        moved = ActionError(409, "tab_moved", self.tx["tab_moved"], None)
        if not t or (name is not None and t["name"] != name) or (expect is not None and t["state"] != expect):
            raise moved
        fresh = None
        if seen is not None:
            text, _digest, _err = self.app.tab_screen(ref, fresh=True)
            fresh = ak.question_of(text, t["state"], self.app.scrub) if text is not None else None
            if fresh is None or fresh["hash"] != seen:
                raise moved
            if sends_text and fresh["draft"]:
                raise ActionError(409, "tab_draft", self.tx["tab_draft"], None)
        elif sends_text and "screen" in self.app.driver_caps():
            # no question to compare (a filed tab has none read): its prompt is still read for a draft,
            # since typed words would be appended to it. An unreadable screen refuses nothing here.
            text, _digest, _err = self.app.tab_screen(ref, fresh=True)
            if text is not None and ak.draft_of(text):
                raise ActionError(409, "tab_draft", self.tx["tab_draft"], None)
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
            # nothing was pressed: not ok, so the page does not mark the question answered
            ctx.note(self.tx["not_asking"].format(name=m.short(tab["name"], 30)), bad=True, go={"kind": "tab", "ref": tab_ref})
            return
        if option is not None:
            picked = next((o for o in (fresh or {}).get("options") or [] if o["n"] == option), None)
            if picked is None:
                raise self.not_applicable("the tab offers no such option", "n")
            said = self.tx["said_option"].format(n=option, label=m.short(picked["label"], 40))
        run = ctx.call("workplace.key", tab_ref, self.app.workplace("key", tab_ref, key), CMUX_TIMEOUT)
        if run.ok:
            ctx.note(self.tx["key_sent"].format(name=m.short(tab["name"], 30), said=said), go={"kind": "tab", "ref": tab_ref})
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
            ctx.note(self.tx["jumped"].format(label=m.short(tab.get("label") or tab["ref"], 40)), go={"kind": "tab", "ref": tab["ref"]})

    def send_to(self, ctx: Ctx, tab: dict, text: str) -> bool:
        run = ctx.call("workplace.send", tab["ref"], self.app.workplace("send", tab["ref"], "--", text), SHORT_TIMEOUT)
        if run.ok:
            ctx.note(self.tx["sent_to"].format(name=m.short(tab["name"], 30), text=m.short(text, 60)), go={"kind": "tab", "ref": tab["ref"]})
        else:
            ctx.note(self.tx["send_failed"].format(err=m.short(run.err, 100)), bad=True)
        ctx.tabs_after(3)
        return run.ok

    def v_tab_send(self, ctx: Ctx, tab_ref: str, text: str, seen: str | None = None, expect: str | None = None,
                   name: str | None = None) -> None:
        tab = self.tab(tab_ref)
        if not m.is_live(tab):
            raise self.not_applicable("the tab holds no agent", "tab_ref")
        if seen is not None or expect is not None or name is not None:
            tab, _ = self.guard_fresh(ctx, tab_ref, expect, seen, name, True)
            if not m.is_live(tab):
                raise ActionError(409, "tab_moved", self.tx["tab_moved"], None)
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
            # each reason its own code (the page words it); none names a form field
            for words, code, key in (("name in use", "name_in_use", "name_in_use"),
                                     ("keeps its name", "task_tab_name", "task_tab_name"),
                                     ("configured workspace", "name_managed", "name_managed"),
                                     ("known by this name", "name_managed", "name_managed"),
                                     ("no open tab", "stale_tab", "stale_tab"),
                                     ("no open workspace", "stale_workspace", "stale_workspace"),
                                     ("a title has", "title_invalid", "title_invalid"),
                                     ("control characters", "title_invalid", "title_invalid")):
                if words in why:
                    raise ActionError(409, code, tx[key], None)
            raise ActionError(409, "rename_refused", tx["rename_refused"].format(err=m.short(why, 160) or "?"), None)
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
            raise ActionError(409, "control_tab", self.tx["control_name"], None)
        if tab.get("slug") or tab.get("item") or tab.get("team"):
            raise ActionError(409, "task_tab_name", self.tx["task_tab_name"], None)
        if tab.get("state_source") == "glyph" and tab.get("state") != "shell":
            raise ActionError(409, "rename_loses_state", self.tx["rename_loses_state"], None)
        run = ctx.call("workplace.rename", tab_ref, self.app.workplace("rename", tab_ref, "--", title), SHORT_TIMEOUT)
        self.renamed(ctx, run)

    def v_workspace_rename(self, ctx: Ctx, ws_ref: str, title: str) -> None:
        """A workspace the terminal shows gets a name; the control workspace keeps its own."""
        app = self.app
        listed = app.tabs.workspace_list() or []
        tabs = app.tabs.tab_list()
        # live is a workspace the terminal lists or a tab names by this ref, with or without a title
        here = [w.get("title") for w in listed if w.get("ref") == ws_ref] \
            + [t.get("workspace") for t in tabs if t.get("ws_ref") == ws_ref]
        if not here:
            raise ActionError(409, "stale_workspace", self.tx["stale_workspace"], None)
        current = next((n for n in here if n), "")
        control = app.tabs.control_tab()
        name = (app.cfg.control or "").strip().casefold()
        if (control and control.get("ws_ref") == ws_ref) or (name and str(current or "").strip().casefold() == name):
            raise ActionError(409, "control_tab", self.tx["control_name"], None)
        run = ctx.call("workplace.rename-workspace", ws_ref,
                       app.workplace("rename-workspace", ws_ref, "--", title), SHORT_TIMEOUT)
        if run.ok:
            app.tabs.refresh_workspaces()
        self.renamed(ctx, run)

    # ------------------------------------------------------------ organize with AI (organize.py)

    def v_organize_propose(self, ctx: Ctx) -> None:
        """One model call over the workspaces and tabs of this Bridge; the checked items come back as a
        proposal, nothing is ticked and nothing changes. Read only: its own audit line, counts only."""
        app, tx = self.app, self.tx
        try:
            chosen = ai.select(app.root, og.SERVICE, og.DEFAULT_MODEL)
        except ValueError:
            raise ActionError(503, "organize_unavailable", tx["organize_unavailable"]) from None
        if chosen.provider != "claude" or chosen.model not in MODELS.values():
            raise ActionError(503, "organize_unavailable", tx["organize_unavailable"])
        if not app.runner.claude:
            raise ActionError(503, "cli_unavailable", "the claude CLI is not available")
        if not self.proposals.begin():
            raise ActionError(409, "organize_running", tx["organize_running"])
        try:
            app.tabs.poll(wait=True, asks=False)
            snap = og.gather(app, app.tabs.read_workspaces())
            if not snap["workspaces"]:
                raise ActionError(409, "organize_nothing", tx["organize_nothing"])
            system, text = og.prompt(snap, app.cfg.language)
            argv = og.argv(app.runner.claude, chosen.model, system, text)
            if not og.argv_ok(argv, app.runner.claude):
                # gather keeps the data within the limit; the runner would refuse anything past it as a 500
                raise ActionError(409, "organize_too_big", tx["organize_too_big"])
            run = ctx.call("claude.organize", "", argv, og.ORGANIZE_TIMEOUT)
            if not run.ok:
                raise ActionError(502, "organize_unreadable", tx["organize_unreadable"])
            answer = og.parse(run.out)
            found = og.items(answer, snap, app.driver_caps(), og.managed_names(app.root), app.scrub)
            prop = self.proposals.put(snap["base"], found)
        finally:
            self.proposals.end()
        self.audit_line("organize_propose", "", scope=len(snap["workspaces"]), items=len(found))
        ctx.extra["proposal"] = {"id": prop["id"], "at_ms": prop["at_ms"], "scope": len(snap["workspaces"]),
                                 "items": found}

    def v_organize_apply(self, ctx: Ctx, proposal: str, items: list[str]) -> None:
        """The ticked items of the current proposal, each only while its value is still the one proposed
        from, in a safe order (moves, recounting the last tab before each), each through its workplace
        command with the cap checked again. The driver calls run without the write lock; the whole apply
        has APPLY_BUDGET_S. Nothing is closed, nothing unticked runs."""
        tx = self.tx
        prop = self.proposals.get(proposal)
        if prop is None:
            raise ActionError(409, "stale_proposal", tx["organize_stale"], "proposal")
        by_id = {i["id"]: i for i in prop["items"]}
        if any(x not in by_id for x in items):
            raise bad_arg("items", "an item is not in this proposal")
        if not self.proposals.begin_apply():
            raise ActionError(409, "organize_running", tx["organize_running"])
        try:
            self.organize_apply(ctx, by_id, items)
        finally:
            self.proposals.end_apply()

    def organize_apply(self, ctx: Ctx, by_id: dict, items: list[str]) -> None:
        """v_organize_apply while it is the only apply running"""
        import time
        app, tx = self.app, self.tx
        with ctx.unlocked():
            app.tabs.poll(wait=True, asks=False)
            listed = app.tabs.read_workspaces()
        tabs = {t["ref"]: t for t in app.tabs.tab_list()}
        spaces: dict[str, dict] = {}
        for t in tabs.values():
            if t.get("ws_ref"):
                spaces.setdefault(t["ws_ref"], {"title": t.get("workspace"), "color_name": None, "description": None})
        for w in listed or []:
            spaces[w["ref"]] = {"title": w.get("title"), "color_name": w.get("color_name"),
                                "description": w.get("description") or None}
        count: dict[str, int] = {}
        for t in tabs.values():
            if t.get("ws_ref"):
                count[t["ws_ref"]] = count.get(t["ws_ref"], 0) + 1

        control_ref = app.tabs.control_ref()

        def task_tab(it: dict) -> bool:
            """a tab adopted for a task, an inbox item or a team since the proposal (or the control tab): its
            name finds it and the plan moves it back, so organize changes neither"""
            tab = tabs.get(it["ref"])
            return bool(it["kind"] in ("tab_title", "tab_move") and tab
                        and (tab.get("slug") or tab.get("item") or tab.get("team") or it["ref"] == control_ref))

        def live(it: dict):
            tab, ws = tabs.get(it["ref"]), spaces.get(it["ref"])
            if it["kind"] == "tab_title":
                return tab["name"] if tab else KeyError
            if it["kind"] == "tab_move":
                return tab.get("ws_ref") if tab else KeyError
            if ws is None:
                return KeyError
            return {"ws_title": ws["title"], "ws_color": ws["color_name"], "ws_description": ws["description"]}[it["kind"]]

        applied: list[str] = []
        skipped: list[dict] = []
        failed: list[dict] = []
        todo = sorted((by_id[x] for x in items), key=lambda it: og.APPLY_ORDER.index(it["kind"]))
        started = time.monotonic()
        for it in todo:
            if time.monotonic() - started > og.APPLY_BUDGET_S:
                failed.append({"id": it["id"], "error": "timeout"})
                continue
            if task_tab(it):
                skipped.append({"id": it["id"], "why": "task_tab"})
                continue
            if live(it) != it["from"]:
                skipped.append({"id": it["id"], "why": "changed"})
                continue
            if it["kind"] == "tab_move" and count.get(it["from"], 0) <= 1:
                skipped.append({"id": it["id"], "why": "last_tab"})
                continue
            if it["cap"] not in app.driver_caps():
                failed.append({"id": it["id"], "error": "driver_cannot"})
                continue
            ref, to = it["ref"], it["to"]
            argv = {"tab_move": lambda: app.workplace("move-tab", ref, to),
                    "tab_title": lambda: app.workplace("rename", ref, "--", to),
                    "ws_title": lambda: app.workplace("rename-workspace", ref, "--", to),
                    "ws_description": lambda: app.workplace("workspace-description", ref,
                                                            *(["--clear"] if to is None else ["--", to])),
                    "ws_color": lambda: app.workplace("workspace-color", ref, *(["--clear"] if to is None else [to])),
                    }[it["kind"]]()
            name = "workplace." + argv[4]
            with ctx.unlocked():
                run = ctx.call(name, ref, argv, SHORT_TIMEOUT)
            if run.ok:
                applied.append(it["id"])
                if it["kind"] == "tab_move":
                    count[it["from"]] = count.get(it["from"], 0) - 1
                    count[to] = count.get(to, 0) + 1
            else:
                why = app.scrub(re.sub(r"\s+", " ", (run.err or run.out) or "").strip())
                failed.append({"id": it["id"], "error": og.failure_code(why), "detail": m.short(why, 160)})
        ctx.extra.update({"applied": applied, "skipped": skipped, "failed": failed})
        ctx.audit_extra = {"applied": len(applied), "skipped": len(skipped), "failed": len(failed)}
        ctx.note(tx["organize_applied"].format(applied=len(applied), skipped=len(skipped), failed=len(failed)),
                 bad=bool(failed))
        app.tabs.refresh_workspaces()
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
            ctx.note(self.tx["relay_sent_to_tab"].format(preview=m.short(rec["preview"], 60)), go={"kind": "claude"})
        else:
            ctx.note(self.tx["send_failed"].format(err=m.short(run.err, 100)), bad=True)
        ctx.tabs_after(3)
