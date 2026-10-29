# SPDX-License-Identifier: MIT
"""Verbs on inbox items and tasks: start, put off, hide, drop, close, reopen, review, note, approve, teams, and the
files tab's question to its records.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import threading

from .. import work_find as wf
from . import activity as act
from . import model as m
from .details import INBOX_ID_RE, inbox_facts, split_front
from .history import REOPEN_AS, item as history_item
from .actions_base import (DECLINED_REASONS, MERGE_MAX, SHORT_TIMEOUT, SLUG_RE, TEAM_RE, ActionError, Ctx, bad_arg,
                           row_go)
from .quick import MODELS
from .text import TABLES

FILES_ASK_TIMEOUT = 90
# one question to the records at a time (v_files_ask), on a lock of its own, never the write lock
_FILES_ASKING = threading.Lock()
# one question to the history at a time (v_timeline_ask), on a lock of its own as well
_TIMELINE_ASKING = threading.Lock()


def record_check(app, words: list[str], themes, path: str, slug: str, kind: str) -> dict:
    """What the block list says of one record (cockpit.files_search.block): its front matter, title, row, theme, the
    text a question would send (work_find.ask_text) and `held`, the words any of them holds: its area (front matter
    and row, every area name), context, theme, path, title and that text, so a word in the body or in `related:`
    holds it as well. A word also matches inside a longer one (Steuer holds Steuerberater and Steuerung alike): it
    holds back more, never less. The question (v_files_ask) and the records the page lists (GET /api/records) both
    read it, so the page counts what the server sends"""
    whole = wf.status_text(app.root, path)      # read once, by the search's rules (no symlink, no huge file)
    front = wf.front_from(whole)
    title = wf.title_from(whole, slug)
    row = {} if kind == "done" else ((app.collector.resolve(f"task:{slug}") or {}).get("out") or {})
    theme = app.themes.theme_name(themes, f"task:{slug}")
    text = (whole or "")[:wf.ASK_TEXT_MAX]
    held = wf.held_by([front.get("area"), front.get("context"), row.get("area"), *(row.get("area_names") or []),
                       theme, path, title, text], words)
    return {"front": front, "title": title, "row": row, "theme": theme, "text": text, "held": held}


def merge_marks(slug: str) -> tuple[str, str]:
    """The two lines a merged section stands between in the kept task's STATUS.md, as task.py merge writes them
    (task.py _marks); an undo is only taken while both are there"""
    return f"<!-- merged-from: {slug} -->", f"<!-- /merged-from: {slug} -->"


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
        """Show again: under the row's own key and under the keys of the same thing (collector.twins: an issue in
        Due and on the GitHub page), wherever the decision was taken"""
        found = self.entry(key)
        taken = [k for k in self.app.collector.twins(key) if self.app.store.unhide(k)] if found["hidden"] else []
        if not taken:
            raise self.not_applicable("the row is not hidden")
        if getattr(self.app, "history", None) is not None:
            for k in taken:                 # only a decision taken back: an expired Later of a twin keeps its entry
                self.app.history.mark_undone("unhide", k)
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
        self.end_also(ctx, row, "drop")
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
        ctx.history.append({**history_item(row["key"], row["title"], "task", "shelved", slug, before, work_kind="task"),
                            "reason": reason})
        self.settle(ctx, row, self.tx["task_shelved"])
        self.settle_soon(ctx)

    def v_inbox_unmute(self, ctx: Ctx, id: str) -> None:  # noqa: A002 - the API name
        run = ctx.call("inbox.unmute", id, self.inbox("unmute", id), SHORT_TIMEOUT)
        if run.ok:
            ctx.note(self.tx["unmuted"])
        else:
            ctx.note(self.tx["unmute_failed"].format(err=m.short(run.err, 100)), bad=True)

    def end_also(self, ctx: Ctx, row: dict, verb: str) -> None:
        """The asks a line took in (briefing_view._fold, `also_inbox`) end with it, the same way (close or drop),
        with a note that names the line. Only the ids the row itself carries and only items still active: one that
        ended meanwhile is left as it ended. A failure is said and the next one goes on; the line stays ended."""
        note = self.tx["also_closed_note"].format(title=m.short(row.get("title") or row["key"], 80))
        for item in row.get("also_inbox") or []:
            if not isinstance(item, str) or not INBOX_ID_RE.match(item) or item == row.get("inbox_id"):
                continue
            facts = inbox_facts(self.app.root, item)
            if facts is None or facts.get("ended"):
                continue
            run = ctx.call(f"inbox.{verb}", item, self.inbox(verb, item, "--note", note), SHORT_TIMEOUT)
            if not run.ok:
                ctx.note(self.tx["done_failed" if verb == "close" else "drop_failed"].format(err=m.short(run.err, 100)),
                         bad=True)

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
        self.end_also(ctx, row, "close")
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
            ctx.history.append({**history_item(row["key"], row["title"], "task",
                                               "declined" if why in DECLINED_REASONS else "done", slug, before,
                                               work_kind="stream" if out.get("stream") or row.get("stream") else "task"),
                                **({"reason": text} if text else {})})
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
                ctx.history.append({**history_item(key, row["title"], "inbox", "done" if outcome == "done" else "dropped", item),
                                    **({"reason": text} if text else {})})
                self.end_also(ctx, row, verb)
                self.settle(ctx, row, self.tx["res_done" if outcome == "done" else "dropped"])
                self.settle_soon(ctx)
            elif kind == "other":
                # not collector.settle: its source still lists the row, so it would stay invisible for good;
                # dismissed it shows under the hidden rows with "show again"; a twin's older Later goes first
                self.clear_twins(key)
                self.app.store.dismiss(key, outcome, row["title"])
                self.write_note(ctx, row, self.tx["close_reason"][outcome] + extra)
                ctx.history.append({**history_item(key, row["title"], "other", outcome), **({"reason": text} if text else {})})
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

    # ------------------------------------------------------------ Merge of Work through (task.py merge, unmerge)

    def merge_row(self, key: str, field: str) -> dict:
        """The row of an open finite task under work/tasks/, else merge_not_task: no stream, no inbox item, no
        other row, no task closed meanwhile"""
        entry = self.entry(key, field)
        row, out = entry["row"], entry["out"] or {}
        slug = row.get("task")
        if (not key.startswith("task:") or row.get("inbox_id") or not isinstance(slug, str) or not SLUG_RE.match(slug)
                or row.get("stream") or out.get("stream")
                or not (self.app.root / "work" / "tasks" / slug / "STATUS.md").is_file()):
            raise ActionError(409, "merge_not_task", "only open tasks merge: no streams, no inbox items", field)
        return row

    def v_flow_merge(self, ctx: Ctx, keep: str, keys: list[str]) -> None:
        """Merge: the tasks of keys close as merged into the task of keep, one task.py merge each in the order given
        (their goal, notes and open steps come over as a section, their documents are linked). Every row is checked
        before the first write; a merge that fails is said and the next one goes on. One history entry, per merged
        task its undo (task_unmerge, back to the status it had) and an item on the kept task."""
        if len(keys) > MERGE_MAX:
            raise bad_arg("keys", f"must be 1 to {MERGE_MAX} task keys")
        if keep in keys:
            raise bad_arg("keys", "the task that stays is not merged into itself")
        for key in (keep, *keys):                       # every key first, then what each one is
            self.entry(key, "keep" if key == keep else "keys")
        kept = self.merge_row(keep, "keep")
        rows = [self.merge_row(key, "keys") for key in keys]
        into = self.slug(kept)
        merged, failed = [], []
        for row in rows:
            slug = self.slug(row)
            before = self.task_status(slug)     # read before the merge moves the folder: the undo restores it
            argv = self.task_cmd("merge", into, "--from", slug, "--heading", self.tx["merge_heading"], "--json")
            run = ctx.call("task.merge", slug, argv, SHORT_TIMEOUT)
            if not run.ok:
                failed.append(slug)
                ctx.note(self.tx["merge_failed"].format(title=m.short(row["title"], 40), err=m.short(run.err, 100)), bad=True)
                continue
            merged.append(slug)
            ctx.history.append({"key": row["key"], "title": str(row["title"])[:200], "kind": "task", "did": "merged",
                                "ident": slug, "into": into, "work_kind": "task", "undone_ms": None,
                                "undo": {"verb": "task_unmerge", "args": {"keep": into, "slug": slug,
                                                                          **({"as": before} if before in REOPEN_AS else {})}}})
            ctx.history.append({"key": kept["key"], "title": str(kept["title"])[:200], "kind": "task", "did": "merged_in",
                                "ident": into, "from": slug, "undo": None, "undone_ms": None})
            self.app.collector.settle(row["key"], self.tx["merge_heading"].replace("{slug}", slug))
            ctx.settled.append(row["key"])
        ctx.extra["merge"] = {"keep": into, "merged": merged, "failed": failed}
        if merged:
            names = ", ".join(m.short(r["title"], 40) for r in rows if r["task"] in merged)
            ctx.note(self.tx["merged"].format(names=names, title=m.short(kept["title"], 60)), go=row_go(kept))
            self.settle_soon(ctx)
        ctx.delta()
        self.app.collector.request("both")

    def v_task_unmerge(self, ctx: Ctx, keep: str, slug: str, **kw) -> None:
        """The undo of one merge: the section and the related lines leave the kept task, the merged task opens again
        with the status it had (task.py unmerge). Only an undo flow_merge handed out, only while the section stands
        between its markers as the merge left it. No flow gate: an undo, also from the history drawer."""
        status = kw.get("as")
        history = getattr(self.app, "history", None)
        it = history.open_undo("task_unmerge", {"keep": keep, "slug": slug, **({"as": status} if status else {})}) \
            if history is not None else None
        if it is None:
            raise self.not_applicable("nothing of that to take back", "slug")
        try:
            text = (self.app.root / "work" / "tasks" / keep / "STATUS.md").read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            text = ""
        first, last = merge_marks(slug)
        lines = [ln.strip() for ln in text.splitlines()]
        if first not in lines or last not in lines or lines.index(last) < lines.index(first):
            raise ActionError(409, "merge_changed", "the merged section was changed by hand", "keep")
        argv = self.task_cmd("unmerge", keep, "--from", slug, *(["--as", status] if status else []), "--json")
        run = ctx.call("task.unmerge", slug, argv, SHORT_TIMEOUT)
        if not run.ok:
            ctx.note(self.tx["reopen_failed"].format(err=m.short(run.err, 100)), bad=True)
            return
        history.mark(it)
        history.mark_where({"key": f"task:{keep}", "did": "merged_in", "from": slug})
        for key in (f"task:{slug}", f"task:{keep}"):
            self.app.collector.unsettle(key)
        ctx.extra["unmerge"] = {"keep": keep, "slug": slug}
        ctx.note(self.tx["merge_undone"].format(title=m.short(it.get("title") or slug, 60)),
                 go={"kind": "item", "key": f"task:{slug}"})
        self.settle_soon(ctx)
        self.app.collector.request("both")

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
        # a brief prepared ahead stays quiet (no note to every page, so no toast per card); a click says what it did
        if not ahead:
            ctx.note(tx["written"].format(title=result["title"]) if result["outcome"] == "written" else tx["proposed"])
        ctx.extra["describe"] = app.describe.state_for(key)
        ctx.extra["outcome"] = result["outcome"]
        ctx.delta()

    # ------------------------------------------------------------ themes of the Work through page (themes.py)

    def v_flow_themes_run(self, ctx: Ctx, mode: str, keys: list) -> None:
        """One run of the themes over open points. A key whose row is gone since the page drew it (settled in
        between) is left out, the others run; only a run with no open key left is refused, before any model call.
        The model call runs on the themes' own lock, never the write lock (it writes nothing of the Bridge)"""
        app = self.app
        rows = []
        for key in keys:
            found = app.collector.resolve(key)
            if found:
                rows.append({**found["out"], "key": key})
        if not rows:
            raise ActionError(409, "stale_row", "the row is no longer there", "keys")
        done = app.themes.run(mode, rows, call=lambda name, subject, argv, timeout, **kw: ctx.call(name, subject, argv, timeout, **kw))
        # the page's own run for new points stays quiet; the click that orders all anew says what it did
        if mode == "regroup":
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

    # ------------------------------------------------------------ the Activity tab and the instruction line

    def v_flow_activity_summary(self, ctx: Ctx, key: str) -> None:
        """The summary of a point's activity (activity.py): the kept one while the rows are the same, else one model
        call outside the write lock. Quiet: the page shows it in place, no note goes to every page"""
        app = self.app
        summary = app.activity.summarize(key, call=self.describe_ctx(ctx))
        ctx.extra["summary"] = summary
        ctx.extra["flow_ai"] = app.activity.flow_ai()
        ctx.audit_extra["cached"] = summary["cached"]

    def v_flow_instruct(self, ctx: Ctx, text: str, keys: list, point: bool = False) -> None:
        """One sentence turned into a plan of steps (instruct.py); nothing runs here, the page runs it on a click"""
        app = self.app
        plan = app.instruct.run(text, keys, point, call=self.describe_ctx(ctx))
        ctx.extra["plan"] = plan
        ctx.extra["flow_ai"] = app.activity.flow_ai()
        ctx.audit_extra.update(points=plan["n"], steps=len(plan["steps"]))

    # ------------------------------------------------------------ the files tab's question to its records

    def v_files_ask(self, ctx: Ctx, text: str, paths: list) -> None:
        """One question over the records the page shows (cockpit.files_search, lib/work_find.py ask_*). A record a word
        of the block list names in its area (front matter and row), theme, path, title or the text that would go
        (record_check) is held back before anything is built, so it never reaches the model; a folder that is no
        record is left out, and when only such folders came the page is stale (files_ask_stale). Off by default,
        within budget_per_day (counted in activity.py's store, read again once the lock is taken), one at a time.
        The answer names records by number only"""
        app = self.app
        tx = TABLES["de" if str(getattr(app.cfg, "language", "en")).startswith("de") else "en"]["files_ask"]
        cfg = act.block(app, "files")
        if not cfg.get("enabled"):
            raise ActionError(409, "files_ask_off", tx["off"])
        words = list(cfg.get("block") or [])
        known = {folder: (slug, kind) for slug, kind, folder in wf.known_folders(app.root)}
        themes = app.themes.load()
        recs, held = [], []
        for path in paths:
            if path not in known:
                continue
            slug, kind = known[path]
            x = record_check(app, words, themes, path, slug, kind)
            if x["held"]:
                held.append(x["held"])
                continue
            front, row = x["front"], x["row"]
            recs.append({"slug": slug, "path": path, "title": x["title"], "status": front.get("status") or kind,
                         "area": row.get("area") or front.get("area") or front.get("context"), "theme": x["theme"],
                         "updated": next((str(front[k])[:10] for k in ("last_updated", "closed", "created") if front.get(k)), None),
                         "text": x["text"]})
        held_words = [w for w in words if any(w in h for h in held)]
        if not recs and not held:
            raise ActionError(409, "files_ask_stale", tx["stale"])
        if not recs:
            raise ActionError(409, "files_ask_held", tx["held"].format(n=len(held)))
        model = act.select_model(app, "files", act.FILES_SERVICE)
        if model is None:
            raise ActionError(503, "files_ask_unavailable", tx["unavailable"])
        if app.activity.budget_left("files") <= 0:
            raise ActionError(429, "files_ask_budget", tx["budget"])
        if not _FILES_ASKING.acquire(blocking=False):
            raise ActionError(409, "files_ask_running", tx["running"])
        try:
            # a second click that came in as the first call let go of the lock passed the read above: read it again
            if app.activity.budget_left("files") <= 0:
                raise ActionError(429, "files_ask_budget", tx["budget"])
            data = [{"n": i + 1, **{k: app.scrub(str(r[k])) if r[k] else r[k] for k in ("title", "slug", "status", "area", "theme", "updated")},
                     "text": app.scrub(r["text"])} for i, r in enumerate(recs)]
            from .describe import language
            system, prompt = wf.ask_prompt(app.scrub(text), data, language(app.root))
            argv = wf.ask_argv(app.runner.claude, model, system, prompt)
            if not wf.ask_argv_ok(argv, app.runner.claude, MODELS.values()):
                raise ActionError(409, "files_ask_too_big", tx["too_big"], "paths")
            run = self.describe_ctx(ctx)("claude.files", "files", argv, FILES_ASK_TIMEOUT)
            got = wf.ask_parse(run.out if run.ok else "", len(recs))
            app.activity.count_call("files", got["cost_usd"])
        finally:
            _FILES_ASKING.release()
        ctx.audit_extra.update(records=len(recs), held=len(held))
        if got["answer"] is None:
            why = "the answer holds none" if run.ok else ((run.err or "").strip().splitlines()[-1:] or ["no answer"])[0]
            raise ActionError(502, "files_ask_failed", tx["failed"].format(why=app.scrub(why)[:200]))
        files = [{**f, "slug": recs[f["n"] - 1]["slug"], "path": recs[f["n"] - 1]["path"], "title": recs[f["n"] - 1]["title"]}
                 for f in got["files"]]
        ctx.extra["ask"] = app.scrub_tree({"answer": got["answer"], "files": files, "sent": len(recs),
                                           "held": {"n": len(held), "words": held_words}, "model": act.alias(got["used"] or model),
                                           "left": app.activity.budget_left("files"), "at_ms": int(app.clock())})

    def v_timeline_ask(self, ctx: Ctx, text: str) -> None:
        """When was it done or discussed (cockpit.files_search, lib/work_find.py history_*): the first call turns the
        question into search terms and maybe a range of days, the lines of the history that hold the most of them are
        picked (history_candidates), every one a word of the block list names in its path, source or text is held back
        before anything is built, and the second call answers from the rest, naming them by number only. Off with the
        files tab's question, within its budget_per_day (one question counts once, both calls' cost together), one at
        a time. Nothing found: no second call, an answer of None"""
        app = self.app
        tx = TABLES["de" if str(getattr(app.cfg, "language", "en")).startswith("de") else "en"]["timeline_ask"]
        cfg = act.block(app, "files")
        if not cfg.get("enabled"):
            raise ActionError(409, "timeline_ask_off", tx["off"])
        words = list(cfg.get("block") or [])
        model = act.select_model(app, "files", act.FILES_SERVICE)
        if model is None:
            raise ActionError(503, "timeline_ask_unavailable", tx["unavailable"])
        if app.activity.budget_left("files") <= 0:
            raise ActionError(429, "timeline_ask_budget", tx["budget"])
        if not _TIMELINE_ASKING.acquire(blocking=False):
            raise ActionError(409, "timeline_ask_running", tx["running"])
        got, sent, held, run = None, [], [], None
        try:
            if app.activity.budget_left("files") <= 0:
                raise ActionError(429, "timeline_ask_budget", tx["budget"])
            from .describe import language
            lang, today, question = language(app.root), dt.date.fromtimestamp(app.clock() / 1000).isoformat(), app.scrub(text)
            call = self.describe_ctx(ctx)
            system, prompt = wf.history_terms_prompt(question, lang, today)
            argv = wf.history_argv(app.runner.claude, model, system, prompt, wf.HISTORY_TERMS_SCHEMA)
            if not wf.history_argv_ok(argv, app.runner.claude, MODELS.values(), wf.HISTORY_TERMS_SCHEMA):
                raise ActionError(409, "timeline_ask_too_big", tx["too_big"], "text")
            run = call("claude.history", "files", argv, FILES_ASK_TIMEOUT)
            terms = wf.history_terms_parse(run.out if run.ok else "")
            cost = terms["cost_usd"] or 0.0
            # no terms came back: the question's own longer words still find something
            asked = terms["terms"] or [w for w in dict.fromkeys(text.lower().split()) if len(w) >= 4][:wf.HISTORY_TERMS_MAX]
            find = lambda since=None, until=None: wf.history_candidates(  # noqa: E731
                app.root, asked, transcripts=app.cfg.transcripts, meetings=app.cfg.meetings, since=since, until=until,
                block=words)
            found = find(terms["from"], terms["to"]) or (find() if terms["from"] or terms["to"] else [])
            # a line a word of the block list names, in itself, its path, its source or its file, never goes
            sent, held = [e for e in found if not e["held"]], [e["held"] for e in found if e["held"]]
            if sent:
                data = [{"n": i + 1, "date": e["date"], "time": e["time"], "kind": e["kind"], "source": app.scrub(e["source"]),
                         "text": app.scrub(e["text"])} for i, e in enumerate(sent)]
                system, prompt = wf.history_answer_prompt(question, data, lang, today)
                argv = wf.history_argv(app.runner.claude, model, system, prompt, wf.HISTORY_ANSWER_SCHEMA)
                # the most entries that fit into one call: the last ones go first
                while data and not wf.history_argv_ok(argv, app.runner.claude, MODELS.values(), wf.HISTORY_ANSWER_SCHEMA):
                    data, sent = data[:-1], sent[:-1]
                    system, prompt = wf.history_answer_prompt(question, data, lang, today)
                    argv = wf.history_argv(app.runner.claude, model, system, prompt, wf.HISTORY_ANSWER_SCHEMA)
                if not data:
                    raise ActionError(409, "timeline_ask_too_big", tx["too_big"], "text")
                run = call("claude.history", "files", argv, FILES_ASK_TIMEOUT)
                got = wf.history_answer_parse(run.out if run.ok else "", len(sent))
                cost += got["cost_usd"] or 0.0
            app.activity.count_call("files", cost or None)
        finally:
            _TIMELINE_ASKING.release()
        ctx.audit_extra.update(entries=len(sent), held=len(held), terms=len(asked))
        if sent and got["answer"] is None:
            why = "the answer holds none" if run.ok else ((run.err or "").strip().splitlines()[-1:] or ["no answer"])[0]
            raise ActionError(502, "timeline_ask_failed", tx["failed"].format(why=app.scrub(why)[:200]))
        keep = ("date", "time", "kind", "source", "path", "line", "text", "folder")
        cited = [{**{k: sent[c["n"] - 1].get(k) for k in keep}, **c} for c in (got["entries"] if got else [])]
        ctx.extra["timeline"] = app.scrub_tree({
            "answer": got["answer"] if got else None, "entries": cited, "terms": asked, "sent": len(sent),
            "held": {"n": len(held), "words": [w for w in words if any(w in h for h in held)]},
            "model": act.alias((got or {}).get("used") or terms.get("used") or model),
            "left": app.activity.budget_left("files"), "at_ms": int(app.clock())})

    def v_flow_attach(self, ctx: Ctx, key: str, name: str, data: bytes) -> None:
        """A document into the open task's deliverables/, flat, under its safe name (a taken one numbered -2 to -99),
        never through a link, never over a file; then a note on the task (text.py activity.attached) that the feed
        folds into the document's row. An inbox row attaches to the task it names. The audit line counts the bytes,
        never the name"""
        app = self.app
        tx = act.TEXT[act._lang(app)]
        if not act.flow_on(app):
            raise ActionError(409, "flow_off", tx["off"])
        if not act.block(app, "attach").get("enabled"):
            raise ActionError(409, "attach_off", tx["attach_off"])
        entry = self.entry(key)
        row = {**entry["row"], **(entry.get("out") or {})}
        task = act.open_task(app.root, row)
        if task is None:
            raise ActionError(409, "attach_no_task", tx["attach_no_task"], "key")
        slug, folder = task
        deliv = folder / "deliverables"
        try:
            inside = folder.resolve().is_relative_to((app.root / "work").resolve())
            if folder.is_symlink() or not inside or deliv.is_symlink() or (deliv.exists() and not deliv.is_dir()):
                raise self.not_applicable(tx["attach_folder"])
            if not deliv.exists():
                deliv.mkdir(mode=0o755)
                os.chmod(deliv, 0o755)
        except OSError as exc:
            raise self.not_applicable(tx["attach_failed"].format(err=m.short(str(exc), 100))) from None
        final = act.free_name(deliv, name)
        if final is None:
            raise ActionError(409, "attach_exists", tx["attach_exists"], "name")
        path = deliv / final
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
        except FileExistsError:
            raise ActionError(409, "attach_exists", tx["attach_exists"], "name") from None
        except OSError as exc:
            raise self.not_applicable(tx["attach_failed"].format(err=m.short(str(exc), 100))) from None
        try:
            os.fchmod(fd, 0o644)
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view):]
        except OSError as exc:
            os.close(fd)
            path.unlink(missing_ok=True)
            raise self.not_applicable(tx["attach_failed"].format(err=m.short(str(exc), 100))) from None
        os.close(fd)
        ctx.audit_extra["bytes"] = len(data)
        line = tx["attached"].format(name=final)
        run = ctx.call("task.note", slug, self.task_cmd("note", slug, "--", line), SHORT_TIMEOUT)
        if run.ok:
            ctx.note(line, go=row_go(row))
        else:
            ctx.note(self.tx["note_failed"].format(err=m.short(run.err, 100)), bad=True)
        app.activity.drop([key, f"task:{slug}"])
        rel = f"deliverables/{final}"
        found = app.activity.doc_row(key, entry, rel)
        if found:
            found["doc"]["attached"] = True
            found["by"] = {"kind": "you", "name": None}
        ctx.extra["attach"] = {"path": rel, "name": final, "bytes": len(data), "row": found}
        ctx.delta()

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
