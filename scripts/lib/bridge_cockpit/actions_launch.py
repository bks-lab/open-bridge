# SPDX-License-Identifier: MIT
"""The pieces the verbs share (register.tsx): settle a row, approve an item, hide a row, jump to a tab, start
agents (launch), ask the control session, and file a row without an item behind it to the inbox.
"""
from __future__ import annotations

import datetime as dt
import json

from . import model as m
from . import returns as ret
from .collector import START_HOLD_MS
from .history import item as history_item
from .actions_base import (ACTIVE_INBOX_STATES, CMUX_TIMEOUT, INBOX_ID_RE, LAUNCH_TIMEOUT, SHORT_TIMEOUT, SLUG_RE,
                           TAB_REF_RE, Ctx)


class LaunchSteps:
    """A part of Actions (actions.py), which holds the registry and the helpers called here."""

    def settle_soon(self, ctx: Ctx) -> None:
        """An item ended or came back: the chats about it are looked at on the next tab poll (quick.py)."""
        self.app.quick.settle_soon()
        ctx.tabs_after(1)

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
        self.app.store.hide(row["key"], until, str(row["title"]))
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
               word: str | None = None, resume: dict | None = None, start_note: bool = False) -> str:
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
        if start_note:
            argv += ["--start-note"]
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
        # read once: the answer before and after the start must be the same one (review C8)
        can_launch = "launch" in app.driver_caps()
        if can_launch:
            # without a driver nothing starts: "starting" first and "not started" after read as two answers (18.10.)
            app.note(tx["launch_start"].format(word=word, n=len(items), where=where), "info")
        with ctx.unlocked():    # the items are held: a second start of them is refused as starting_already
            run = ctx.call("workplace.launch", ",".join(items), argv, LAUNCH_TIMEOUT)
        if run.ok and not can_launch:
            # no terminal driver: workplace.py only printed what to start, nothing runs, so nothing is recorded
            lines = []
            try:
                lines = [m.as_text(x).strip() for x in m._list(json.loads(run.out).get("report"))]
            except (ValueError, AttributeError):
                pass
            commands = [line for line in lines if line and not line.startswith("No driver configured")]
            # the commands go to the page to copy, never into the message: a whole agent prompt with its shell
            # quoting filled the screen (18.10.)
            ctx.extra["manual"] = commands
            ctx.note(tx["manual_start"].format(word=word), bad=True)
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
                                  **(chosen or {}), **({"by": ctx.by} if ctx.by else {})}
                                 for r in launched if r.get("key") and m.launch_item(r)])
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
            ctx.note(tx["already_open"].format(label=m.short(running[0]["label"], 40)), go={"kind": "tab", "ref": running[0]["ref"]})
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
        self.app.store.hide(row["key"], until, str(row["title"]))
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
            filed = self.filed_page_item(inbox_key, page["row"])
            if filed:
                return filed
        detail = " ".join(x for x in [page.get("detail"), m.row_url(row) or ""] if x)
        summary = f"{page['section']}: {row['title']}"
        if inbox_key:
            return self.inbox_add(ctx, row["key"], summary, detail, key=inbox_key, closer="reporter")
        return self.inbox_add(ctx, row["key"], summary, detail)

    def filed_page_item(self, inbox_key: str, same: str | None) -> str | None:
        """The active inbox item filed for a page row: under `inbox_key`, or the same row (`same` is
        ":<section>:<item>") filed under any profile's name, since the cockpit's profile often extends the
        briefing's. None when there is none."""
        for e in self.app.inbox_listing() or []:
            key = str(e.get("key") or "") if isinstance(e, dict) else ""
            if ((inbox_key and key == inbox_key or same and key.startswith("briefing:") and key.endswith(same))
                    and e.get("state") in ACTIVE_INBOX_STATES and INBOX_ID_RE.match(str(e.get("id")))):
                return e["id"]
        return None

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
