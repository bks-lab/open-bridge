# SPDX-License-Identifier: MIT
"""Verbs on inbox items and tasks: start, put off, hide, drop, close, reopen, review, note, approve, teams.
"""
from __future__ import annotations

import json

from . import model as m
from .details import split_front
from .history import item as history_item
from .actions_base import DECLINED_REASONS, SHORT_TIMEOUT, TEAM_RE, ActionError, Ctx, bad_arg, row_go


class WorkVerbs:
    """A part of Actions (actions.py), which holds the registry and the helpers called here."""

    def refuse_approved(self, rows: list[dict]) -> None:
        """A yes already given runs on the next pass: no start verb goes at the same item a second time."""
        if any(row.get("inbox_state") == "approved" for row in rows):
            raise self.not_applicable("an approved item runs on its own; take the yes back first", "keys")

    def start_noted(self, ctx: Ctx, entries: list[dict], note: str, mode: str, target: str, word: str | None = None) -> None:
        """A start with the person's sentence. A row whose agent tab runs gets the sentence typed into that tab;
        every other row gets it on the item first ("Start note: ..."), and the agent is told to read it before
        anything else (workplace.py launch --start-note). A tab that asks something takes no text: it is refused
        before anything is written."""
        for e in entries:
            tab = e.get("tab")
            if tab and m.is_live(tab) and tab.get("state") == "needs-you":
                raise self.not_applicable("the tab asks you something; answer it there first", "keys")
        rows = []
        for e in entries:
            tab = e.get("tab")
            if tab and m.is_live(tab):
                # kept on the item too: typed into a tab, the sentence would otherwise live only on a screen
                if self.send_to(ctx, tab, note):
                    self.write_note(ctx, e["row"], self.tx["tab_note"].format(text=note))
            else:
                rows.append(e["row"])
        rows = [r for r in rows if m.launch_item(r) is not None] + self.file_all(ctx, rows)
        started = [r for r in rows if self.write_note(ctx, r, f"Start note: {note}")]
        if started:
            self.launch(ctx, started, mode, target, word=word, start_note=True)

    def write_note(self, ctx: Ctx, row: dict, text: str) -> bool:
        """The person's sentence, or a decision with it, where the row lives: an inbox item's notes, a task's or a
        stream's notes, and for any other row (an issue, a deadline) a row in work/log.md, since it has no place of
        its own here and its source stays as it is."""
        if row.get("inbox_id"):
            item = self.inbox_id(row)
            run = ctx.call("inbox.note", item, self.inbox("note", item, "--", text), SHORT_TIMEOUT)
        elif row.get("task"):
            slug = self.slug(row)
            run = ctx.call("task.note", slug, self.task_cmd("note", slug, "--", text), SHORT_TIMEOUT)
        else:
            ref = str(row.get("ref") or "")
            # the repo of an issue, else the source the row came from (an application, a protocol)
            context = (ref.split("#")[0].rsplit("/", 1)[-1] if "#" in ref else str((row.get("sources") or [""])[0])) or "cockpit"
            label = str(row.get("title") or row["key"])[:120] + (f" ({ref})" if ref else "")
            run = ctx.call("task.log_row", row["key"], self.task_cmd("log", "--", context, f"{label} · {text}"), SHORT_TIMEOUT)
        if not run.ok:
            ctx.note(self.tx["note_failed"].format(err=m.short(run.err, 100)), bad=True)
        return run.ok

    def v_do_it(self, ctx: Ctx, keys: list[str], target: str | None = None, note: str | None = None) -> None:
        entries = self.entries(keys)
        rows = [e["row"] for e in entries]
        self.refuse_approved(rows)
        if note:
            # a sentence of the person's is an order for an agent, never the item's own canned action
            self.start_noted(ctx, entries, note, "go", target or self.app.cfg.target)
            return
        rows = [r for r in rows if m.launch_item(r) is not None] + self.file_all(ctx, rows)
        yes = [r for r in rows if r.get("inbox_id") and r.get("gate") == "your-yes" and r.get("has_action")]
        rest = [r for r in rows if r not in yes]
        for row in yes:
            self.approve(ctx, row)
        if rest:
            self.launch(ctx, rest, "go", target or self.app.cfg.target)
        if not yes and not rest and not ctx.failed:
            ctx.note(self.tx["nothing_to_do"])

    def v_advise(self, ctx: Ctx, keys: list[str], note: str | None = None) -> None:
        if note:
            self.start_noted(ctx, self.entries(keys), note, "report", self.app.cfg.target)
            return
        rows = [e["row"] for e in self.entries(keys)]
        # a row with nothing to start on (an issue, a deadline) becomes an inbox item first, as for do_it:
        # it gets a tab of its own and never goes into a running session (14.10.)
        startable = [r for r in rows if m.launch_item(r) is not None] + self.file_all(ctx, rows)
        if startable:
            self.launch(ctx, startable, "report", self.app.cfg.target)

    def v_start_agent(self, ctx: Ctx, keys: list[str], note: str | None = None) -> None:
        """An agent tab that goes at the item at once ("go"), for an inbox item as for a task: unlike
        do_it it never approves an item's own action, unlike advise it does not stop at a report"""
        entries = self.entries(keys)
        rows = [e["row"] for e in entries]
        if any(m.launch_item(r) is None for r in rows):
            raise self.not_applicable("an agent starts on an inbox item or a task", "keys")
        self.refuse_approved(rows)
        if note:
            self.start_noted(ctx, entries, note, "go", self.app.cfg.target, word=self.tx["btn_start_agent"])
            return
        self.launch(ctx, rows, "go", self.app.cfg.target, word=self.tx["btn_start_agent"])

    def v_collect_context(self, ctx: Ctx, key: str, note: str | None = None) -> None:
        entry = self.entry(key)
        row = entry["row"]
        if m.launch_item(row) is None:
            raise self.not_applicable("collecting context needs an inbox item or a task")
        if note:
            self.start_noted(ctx, [entry], note, "context", self.app.cfg.target)
            return
        self.launch(ctx, [row], "context", self.app.cfg.target)

    def v_later(self, ctx: Ctx, key: str, until: str, text: str | None = None) -> None:
        """Put off until a day. An inbox item records its defer itself and keeps the sentence as a note; a task, a
        stream and any other row are only hidden here, so the decision is written where the row lives
        (write_note), with the sentence when there is one."""
        row = self.entry(key)["row"]
        words = self.tx["later_note"].format(until=until) + (f": {text}" if text else "")
        # every inbox item is put off, whatever its gate: hidden only, a free one would still run meanwhile
        if row.get("inbox_id"):
            item = self.inbox_id(row)
            if text and not self.write_note(ctx, row, words):
                return
            run = ctx.call("inbox.defer", item, self.inbox("defer", item, "--until", until), SHORT_TIMEOUT)
            if not run.ok:
                ctx.note(self.tx["later_failed"].format(err=m.short(run.err, 100)), bad=True)
                return
            # like a hide, a defer can be taken back from the note and the history (inbox_reopen)
            ctx.history.append(history_item(row["key"], row["title"], "inbox", f"later until {until}", item))
            self.settle(ctx, row, self.tx["later_back"].format(until=until))
            return
        self.write_note(ctx, row, words)
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
                                    "work_kind": "stream" if row.get("stream") else "task",
                                    "undo": {"verb": "task_running", "args": {"slug": slug}}})
                ctx.note(self.tx["runs_on_note"].format(until=until) + f": {title}")
                ctx.delta()
            else:
                self.write_note(ctx, row, self.tx["runs_on_note"].format(until=until) + (f": {on}" if on else ""))
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
        ctx.note(self.tx["running_again"].format(slug=slug), go={"kind": "item", "key": f"task:{slug}"})
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
        if slug:
            ctx.history.append({"key": row["key"], "title": str(row["title"])[:200], "kind": "inbox", "did": f"to task {slug}",
                                "ident": item, "undo": {"verb": "to_task_undo", "args": {"id": item, "slug": slug}},
                                "undone_ms": None})
        ctx.extra["task"] = slug
        self.app.collector.request("both")

    def v_to_task_undo(self, ctx: Ctx, id: str, slug: str) -> None:  # noqa: A002 - the API name
        """Takes a to_task back. Nothing is deleted: the task it made closes as declined, so its folder and
        notes stay findable under work/done/, and the inbox item opens again. Only an undo the server handed out."""
        history = getattr(self.app, "history", None)
        it = history.open_undo("to_task_undo", {"id": id, "slug": slug}) if history else None
        if it is None:
            raise self.not_applicable("nothing of that to take back", "id")
        run = ctx.call("task.close", slug, self.task_cmd("close", slug, "--declined", "--reason", self.tx["to_task_undone_reason"]),
                       SHORT_TIMEOUT)
        if not run.ok:
            ctx.note(self.tx["task_close_failed"].format(title=slug, err=m.short(run.err, 100)), bad=True)
            return
        self.v_inbox_reopen(ctx, id)
        history.mark_undone("to_task_undo", id)

    def v_hide(self, ctx: Ctx, key: str, until: str) -> None:
        self.hide_until(ctx, self.entry(key)["row"], until)

    def v_unhide(self, ctx: Ctx, key: str) -> None:
        found = self.entry(key)
        if not found["hidden"] or not self.app.store.unhide(key):
            raise self.not_applicable("the row is not hidden")
        if getattr(self.app, "history", None) is not None:
            self.app.history.mark_undone("unhide", key)
        ctx.note(self.tx["unhidden_note"].format(title=m.short(found["row"]["title"], 60)), go=row_go(found["row"]))

    def v_drop(self, ctx: Ctx, key: str, reason: str | None = None) -> None:
        row = self.entry(key)["row"]
        if not row.get("inbox_id"):
            # Discard means discard: a task closes as declined, any other row leaves for good (settle not_doing).
            # It used to hide the row for a week, so a discarded task came back
            self.v_settle(ctx, [key], "not_doing")
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
        self.settle_soon(ctx)

    def v_shelve(self, ctx: Ctx, key: str, reason: str, until: str | None = None) -> None:
        """"Drop because" on a task (the Work through page): parked without being lost, in one step of task.py shelve,
        an idea in the inbox deferred until a day and the task closed as declined, the reason on both. Only a finite
        task: a stream never ends this way, an inbox item or any other row is dropped or settled instead. The reason
        is one argv word, glued to its flag, so a reason that looks like a flag stays text. Taken back by reopening
        the task, which closes the idea again (task.py reopen)."""
        entry = self.entry(key)
        row = entry["row"]
        if not row.get("task") or row.get("inbox_id") or row.get("stream") or (entry["out"] or {}).get("stream"):
            raise self.not_applicable("only a task is shelved; a stream runs on, an inbox item is dropped", "key")
        slug = self.slug(row)
        before = self.task_status(slug)     # read before the shelve moves the folder: the undo restores it
        argv = self.task_cmd("shelve", slug, f"--reason={reason}", *(["--until", until] if until else []))
        run = ctx.call("task.shelve", slug, argv, SHORT_TIMEOUT)
        if not run.ok:
            ctx.note(self.tx["shelve_failed"].format(title=m.short(row["title"], 40), err=m.short(run.err, 100)), bad=True)
            return
        ctx.history.append(history_item(row["key"], row["title"], "task", "shelved", slug, before, work_kind="task"))
        self.settle(ctx, row, self.tx["task_shelved"])
        self.settle_soon(ctx)

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
        self.settle_soon(ctx)

    def v_urgency(self, ctx: Ctx, key: str, value: str) -> None:
        row = self.entry(key)["row"]
        if not row.get("inbox_id"):
            raise self.not_applicable("urgency is for inbox items")
        item = self.inbox_id(row)
        run = ctx.call("inbox.urgency", item, self.inbox("urgency", item, value), SHORT_TIMEOUT)
        if run.ok:
            ctx.note(self.tx["urgency_set"].format(word=self.tx["urgency"].get(value, value), title=m.short(row["title"], 60)),
                     go=row_go(row))
            ctx.delta()
        else:
            ctx.note(self.tx["urgency_failed"].format(err=m.short(run.err, 100)), bad=True)

    def v_area(self, ctx: Ctx, key: str, value: str | None = None) -> None:
        """Give an inbox item one of the configured areas, or take its area back (no value). An item with a task
        shows the task's area, so only one without gets one here."""
        row = self.entry(key)["row"]
        if not row.get("inbox_id") or row.get("task"):
            raise self.not_applicable("an area is for inbox items without a task")
        if value and value not in self.app.cfg.areas:
            raise bad_arg("value", "not a configured area (workplace.workspaces)")
        item = self.inbox_id(row)
        run = ctx.call("inbox.area", item, self.inbox("area", item, value or "--clear"), SHORT_TIMEOUT)
        if run.ok:
            ctx.note((self.tx["area_set"].format(area=value, title=m.short(row["title"], 60)) if value
                      else self.tx["area_cleared"].format(title=m.short(row["title"], 60))), go=row_go(row))
            ctx.delta()
        else:
            ctx.note(self.tx["area_failed"].format(err=m.short(run.err, 100)), bad=True)

    def v_priority(self, ctx: Ctx, key: str, value: str) -> None:
        row = self.entry(key)["row"]
        # an inbox row names the task it came from; its priority is not that task's to change from here
        if not row.get("task") or row.get("inbox_id"):
            raise self.not_applicable("priority is for tasks")
        slug = self.slug(row)
        run = ctx.call("task.priority", slug, self.task_cmd("priority", slug, value), SHORT_TIMEOUT)
        if run.ok:
            ctx.note(self.tx["prio_set"].format(priority=value, title=m.short(row["title"], 60)), go=row_go(row))
            ctx.delta()
        else:
            ctx.note(self.tx["prio_failed"].format(err=m.short(run.err, 100)), bad=True)

    def v_task_set_next(self, ctx: Ctx, key: str, text: str) -> None:
        """The person takes over a suggested next step: STATUS.md keeps it as next: {what} with a dated note
        (task.py next), only on this click; the step shown before was derived and never stored."""
        row = self.entry(key)["row"]
        if not row.get("task") or row.get("inbox_id"):
            raise self.not_applicable("a next step is for tasks")
        slug = self.slug(row)
        run = ctx.call("task.next", slug, self.task_cmd("next", slug, "--", " ".join(text.split())), SHORT_TIMEOUT)
        if run.ok:
            ctx.note(self.tx["next_set"].format(title=m.short(row["title"], 60)), go=row_go(row))
            ctx.delta()
        else:
            ctx.note(self.tx["next_failed"].format(err=m.short(run.err, 100)), bad=True)

    def task_rows(self, keys: list[str], closing: bool = False, stream: bool = False) -> list[tuple[dict, dict]]:
        """(row, out) per key, every one a task row; closing also needs every one finite, or a stream the page
        asked about (stream)."""
        found = []
        for key in keys:
            entry = self.entry(key, "keys")
            row = entry["row"]
            if not row.get("task") or row.get("inbox_id"):
                raise self.not_applicable("this is for tasks", "keys")
            self.slug(row)
            out = entry["out"] or {}
            if closing and not out.get("closable") and not (stream and out.get("stream")):
                raise self.not_applicable("a stream ends only when the page asked first", "keys")
            found.append((row, entry["out"] or {}))
        return found

    def task_status(self, slug: str) -> str | None:
        """The status in an open task's or stream's STATUS.md, or None when there is none to read."""
        for kind in ("tasks", "streams"):
            try:
                text = (self.app.root / "work" / kind / slug / "STATUS.md").read_text(encoding="utf-8")
                break
            except (OSError, UnicodeDecodeError):
                continue
        else:
            return None
        status = split_front(text)[0].get("status")
        return status if isinstance(status, str) else None

    def v_task_close(self, ctx: Ctx, keys: list[str], reason: str, text: str | None = None, stream: bool = False) -> None:
        rows = self.task_rows(keys, closing=True, stream=stream)
        done = failed = 0
        for row, out in rows:
            slug = self.slug(row)
            why = reason
            if why == "auto":
                why = "not_doing" if ((out.get("review") or {}).get("verdict") == "stale") else "done"
            words = self.tx["close_reason"][why] + (f": {text}" if text else "")
            argv = self.task_cmd("close", slug, *(["--stream"] if out.get("stream") else []),
                                 *(["--declined"] if why in DECLINED_REASONS else []), "--reason", words)
            before = self.task_status(slug)     # read before the close moves the folder: the undo restores it
            run = ctx.call("task.close", slug, argv, SHORT_TIMEOUT)
            if not run.ok:
                failed += 1
                ctx.note(self.tx["task_close_failed"].format(title=m.short(row["title"], 40),
                                                             err=m.short(run.err, 100)), bad=True)
                continue
            done += 1
            ctx.history.append(history_item(row["key"], row["title"], "task",
                                            "declined" if why in DECLINED_REASONS else "done", slug, before,
                                            work_kind="stream" if out.get("stream") or row.get("stream") else "task"))
            if len(rows) == 1:
                self.settle(ctx, row, self.tx["task_declined" if why in DECLINED_REASONS else "task_closed"])
            else:
                self.app.collector.settle(row["key"], self.tx["task_closed"])
                ctx.settled.append(row["key"])
        if len(rows) > 1:
            ctx.note(self.tx["tasks_closed"].format(n=done) + (f" · {failed} ✗" if failed else ""), bad=bool(failed))
            ctx.delta()
        if done:
            self.settle_soon(ctx)

    def v_settle(self, ctx: Ctx, keys: list[str], outcome: str, text: str | None = None, stream: bool = False) -> None:
        """Done or not doing, for any row: a finite task closes through task.py, an inbox item closes or
        drops, every other row (a GitHub issue, an application, a deadline from a protocol) leaves the
        briefing for good, while its source stays as it is. A stream never settles. All rows are checked
        before the first write."""
        plan = []
        for key in keys:
            entry = self.entry(key, "keys")
            row, out = entry["row"], entry["out"] or {}
            if row.get("task") and not row.get("inbox_id"):
                if not out.get("closable") and not (stream and out.get("stream")):
                    raise self.not_applicable("a stream ends only when the page asked first", "keys")
                plan.append(("task", key, row))
            elif row.get("inbox_id"):
                self.inbox_id(row)
                plan.append(("inbox", key, row))
            else:
                plan.append(("other", key, row))
        extra = f": {text}" if text else ""
        tasks = [k for kind, k, _ in plan if kind == "task"]
        if tasks:
            self.v_task_close(ctx, tasks, outcome, text, stream)
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
                self.settle_soon(ctx)
            elif kind == "other":
                # not collector.settle: its source still lists the row, so it would stay invisible for good;
                # dismissed it shows under the hidden rows with "show again"
                self.app.store.dismiss(key, outcome, row["title"])
                self.write_note(ctx, row, self.tx["close_reason"][outcome] + extra)
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
        ctx.note(word.format(title=m.short(title, 60)), go={"kind": "item", "key": keys[0]})
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
        self.settle_soon(ctx)
        self.reopened(ctx, "task_reopen", slug, (f"task:{slug}",),
                      self.tx[{"doing": "task_reopened", "review": "task_reopened_review"}.get(status, "task_reopened_backlog")])

    def v_inbox_reopen(self, ctx: Ctx, id: str, note: str | None = None) -> None:  # noqa: A002 - the API name
        run = ctx.call("inbox.reopen", id, self.inbox("reopen", id, *(["--note", note] if note else [])), SHORT_TIMEOUT)
        if not run.ok:
            ctx.note(self.tx["reopen_failed"].format(err=m.short(run.err, 100)), bad=True)
            return
        self.settle_soon(ctx)
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
            ctx.note(self.tx["task_kept" if len(slugs) == 1 else "task_kept_many"].format(n=len(slugs), title=m.short(rows[0][0]["title"], 60)),
                     go=row_go(rows[0][0]) if len(slugs) == 1 else None)
        else:
            ctx.note(self.tx["task_keep_failed"].format(err=m.short(run.err, 100)), bad=True)

    def v_note(self, ctx: Ctx, key: str, text: str) -> None:
        row = self.entry(key)["row"]
        if self.write_note(ctx, row, " ".join(text.split())):
            ctx.note(self.tx["note_added"].format(title=m.short(row["title"], 40), line=m.short(text, 60)), go=row_go(row))
            ctx.delta()

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

    # ------------------------------------------------------------ describe (describe.py)

    def describe_ctx(self, ctx: Ctx):
        """The steps of a describe verb go on its record like any other call"""
        return lambda name, subject, argv, timeout, **kw: ctx.call(name, subject, argv, timeout, **kw)

    def v_describe_run(self, ctx: Ctx, key: str, ahead: bool = False) -> None:
        """One item's brief now: written while no person changed it, else a proposal; the model call runs
        without the write lock. A click always runs; a brief prepared ahead (the Work through page) only while
        the hour's budget has a call left"""
        app = self.app
        tx = app.describe.tx()
        if ahead and app.describe.budget_left() <= 0:
            raise ActionError(429, "describe_budget", tx["budget"], "ahead")
        result = app.describe.run_key(key, why="ahead" if ahead else "click", call=self.describe_ctx(ctx),
                                      unlocked=ctx.unlocked)
        ctx.note(tx["written"].format(title=result["title"]) if result["outcome"] == "written" else tx["proposed"])
        ctx.extra["describe"] = app.describe.state_for(key)
        ctx.extra["outcome"] = result["outcome"]
        ctx.delta()

    # ------------------------------------------------------------ themes of the Work through page (themes.py)

    def v_flow_themes_run(self, ctx: Ctx, mode: str, keys: list) -> None:
        """One run of the themes over open points: each key must be a row the page shows now. The model call runs
        on the themes' own lock, never the write lock (it writes nothing of the Bridge)"""
        app = self.app
        rows = []
        for key in keys:
            found = app.collector.resolve(key)
            if not found:
                raise ActionError(409, "stale_row", "the row is no longer there", "keys")
            rows.append({**found["out"], "key": key})
        done = app.themes.run(mode, rows, call=lambda name, subject, argv, timeout, **kw: ctx.call(name, subject, argv, timeout, **kw))
        ctx.note(app.themes.tx()["ordered"].format(n=done["n"]))
        ctx.extra["themes"] = app.themes.state()

    def _theme_row(self, key: str) -> None:
        if not self.app.collector.resolve(key):
            raise ActionError(409, "stale_row", "the row is no longer there", "key")

    def v_flow_theme_move(self, ctx: Ctx, key: str, theme: str) -> None:
        self._theme_row(key)
        name = self.app.themes.move(key, theme)
        ctx.note(self.app.themes.tx()["moved"].format(name=name))
        ctx.extra["themes"] = self.app.themes.state()

    def v_flow_theme_new(self, ctx: Ctx, key: str, name: str) -> None:
        self._theme_row(key)
        made = self.app.themes.new(key, name)
        ctx.note(self.app.themes.tx()["moved"].format(name=made))
        ctx.extra["themes"] = self.app.themes.state()

    def v_flow_theme_rename(self, ctx: Ctx, theme: str, name: str) -> None:
        made = self.app.themes.rename(theme, name)
        ctx.note(self.app.themes.tx()["renamed"].format(name=made))
        ctx.extra["themes"] = self.app.themes.state()

    def v_describe_apply(self, ctx: Ctx, key: str, proposal: str, brief: dict | None = None) -> None:
        app = self.app
        result = app.describe.apply(key, proposal, brief, call=self.describe_ctx(ctx))
        ctx.note(app.describe.tx()["applied"].format(title=result["title"]))
        ctx.extra["describe"] = app.describe.state_for(key)
        ctx.delta()

    def v_describe_discard(self, ctx: Ctx, key: str, proposal: str) -> None:
        app = self.app
        app.describe.discard(key, proposal)
        ctx.note(app.describe.tx()["discarded"])
        ctx.extra["describe"] = app.describe.state_for(key)
