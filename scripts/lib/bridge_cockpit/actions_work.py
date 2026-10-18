# SPDX-License-Identifier: MIT
"""Verbs on inbox items and tasks: start, put off, hide, drop, close, reopen, review, note, approve, teams.
"""
from __future__ import annotations

import datetime as dt
import json

from . import model as m
from .details import split_front
from .history import item as history_item
from .actions_base import DECLINED_REASONS, SHORT_TIMEOUT, TEAM_RE, ActionError, Ctx, bad_arg


class WorkVerbs:
    """A part of Actions (actions.py), which holds the registry and the helpers called here."""

    def v_do_it(self, ctx: Ctx, keys: list[str], target: str | None = None) -> None:
        rows = [e["row"] for e in self.entries(keys)]
        for row in rows:
            if row.get("inbox_state") == "approved":
                raise self.not_applicable("Do it needs an inbox item or a task that is not approved yet", "keys")
        rows = [r for r in rows if m.launch_item(r) is not None] + self.file_all(ctx, rows)
        yes = [r for r in rows if r.get("inbox_id") and r.get("gate") == "your-yes" and r.get("has_action")]
        rest = [r for r in rows if r not in yes]
        for row in yes:
            self.approve(ctx, row)
        if rest:
            self.launch(ctx, rest, "go", target or self.app.cfg.target)
        if not yes and not rest and not ctx.failed:
            ctx.note(self.tx["nothing_to_do"])

    def v_advise(self, ctx: Ctx, keys: list[str]) -> None:
        rows = [e["row"] for e in self.entries(keys)]
        # a row with nothing to start on (an issue, a deadline) becomes an inbox item first, as for do_it:
        # it gets a tab of its own and never goes into a running session (14.10.)
        startable = [r for r in rows if m.launch_item(r) is not None] + self.file_all(ctx, rows)
        if startable:
            self.launch(ctx, startable, "report", self.app.cfg.target)

    def v_start_agent(self, ctx: Ctx, keys: list[str]) -> None:
        """An agent tab that goes at the item at once ("go"), for an inbox item as for a task: unlike
        do_it it never approves an item's own action, unlike advise it does not stop at a report"""
        rows = [e["row"] for e in self.entries(keys)]
        if any(m.launch_item(r) is None for r in rows):
            raise self.not_applicable("an agent starts on an inbox item or a task", "keys")
        self.launch(ctx, rows, "go", self.app.cfg.target, word=self.tx["btn_start_agent"])

    def v_collect_context(self, ctx: Ctx, key: str) -> None:
        row = self.entry(key)["row"]
        if m.launch_item(row) is None:
            raise self.not_applicable("collecting context needs an inbox item or a task")
        self.launch(ctx, [row], "context", self.app.cfg.target)

    def v_later(self, ctx: Ctx, key: str, until: str) -> None:
        row = self.entry(key)["row"]
        if row.get("inbox_id") and row.get("gate") != "free":
            item = self.inbox_id(row)
            run = ctx.call("inbox.defer", item, self.inbox("defer", item, "--until", until), SHORT_TIMEOUT)
            if not run.ok:
                ctx.note(self.tx["later_failed"].format(err=m.short(run.err, 100)), bad=True)
                return
            # like a hide, a defer can be taken back from the note and the history (inbox_reopen)
            ctx.history.append(history_item(row["key"], row["title"], "inbox", f"later until {until}", item))
            self.settle(ctx, row, self.tx["later_back"].format(until=until))
            return
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
                                    "undo": {"verb": "task_running", "args": {"slug": slug}}})
                ctx.note(self.tx["runs_on_note"].format(until=until) + f": {title}")
                ctx.delta()
            else:
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
        ctx.note(self.tx["running_again"].format(slug=slug))
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
        ctx.extra["task"] = slug
        self.app.collector.request("both")

    def v_hide(self, ctx: Ctx, key: str, until: str) -> None:
        self.hide_until(ctx, self.entry(key)["row"], until)

    def v_unhide(self, ctx: Ctx, key: str) -> None:
        found = self.entry(key)
        if not found["hidden"] or not self.app.store.unhide(key):
            raise self.not_applicable("the row is not hidden")
        if getattr(self.app, "history", None) is not None:
            self.app.history.mark_undone("unhide", key)
        ctx.note(self.tx["unhidden_note"].format(title=m.short(found["row"]["title"], 60)))

    def v_drop(self, ctx: Ctx, key: str, reason: str | None = None) -> None:
        row = self.entry(key)["row"]
        if not row.get("inbox_id"):
            until = (self.today() + dt.timedelta(days=7)).isoformat()
            self.hide_until(ctx, row, until)
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
            ctx.note(self.tx["urgency_set"].format(word=self.tx["urgency"].get(value, value), title=m.short(row["title"], 60)))
            ctx.delta()
        else:
            ctx.note(self.tx["urgency_failed"].format(err=m.short(run.err, 100)), bad=True)

    def v_priority(self, ctx: Ctx, key: str, value: str) -> None:
        row = self.entry(key)["row"]
        # an inbox row names the task it came from; its priority is not that task's to change from here
        if not row.get("task") or row.get("inbox_id"):
            raise self.not_applicable("priority is for tasks")
        slug = self.slug(row)
        run = ctx.call("task.priority", slug, self.task_cmd("priority", slug, value), SHORT_TIMEOUT)
        if run.ok:
            ctx.note(self.tx["prio_set"].format(priority=value, title=m.short(row["title"], 60)))
            ctx.delta()
        else:
            ctx.note(self.tx["prio_failed"].format(err=m.short(run.err, 100)), bad=True)

    def task_rows(self, keys: list[str], closing: bool = False) -> list[tuple[dict, dict]]:
        """(row, out) per key, every one a task row; closing also needs every one finite."""
        found = []
        for key in keys:
            entry = self.entry(key, "keys")
            row = entry["row"]
            if not row.get("task") or row.get("inbox_id"):
                raise self.not_applicable("this is for tasks", "keys")
            self.slug(row)
            if closing and not (entry["out"] or {}).get("closable"):
                raise self.not_applicable("only a finite task closes, never a stream", "keys")
            found.append((row, entry["out"] or {}))
        return found

    def task_status(self, slug: str) -> str | None:
        """The status in an open task's STATUS.md, or None when there is none to read."""
        try:
            text = (self.app.root / "work" / "tasks" / slug / "STATUS.md").read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
        status = split_front(text)[0].get("status")
        return status if isinstance(status, str) else None

    def v_task_close(self, ctx: Ctx, keys: list[str], reason: str, text: str | None = None) -> None:
        rows = self.task_rows(keys, closing=True)
        done = failed = 0
        for row, out in rows:
            slug = self.slug(row)
            why = reason
            if why == "auto":
                why = "not_doing" if ((out.get("review") or {}).get("verdict") == "stale") else "done"
            words = self.tx["close_reason"][why] + (f": {text}" if text else "")
            argv = self.task_cmd("close", slug, *(["--declined"] if why in DECLINED_REASONS else []), "--reason", words)
            before = self.task_status(slug)     # read before the close moves the folder: the undo restores it
            run = ctx.call("task.close", slug, argv, SHORT_TIMEOUT)
            if not run.ok:
                failed += 1
                ctx.note(self.tx["task_close_failed"].format(title=m.short(row["title"], 40),
                                                             err=m.short(run.err, 100)), bad=True)
                continue
            done += 1
            ctx.history.append(history_item(row["key"], row["title"], "task",
                                            "declined" if why in DECLINED_REASONS else "done", slug, before))
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

    def v_settle(self, ctx: Ctx, keys: list[str], outcome: str, text: str | None = None) -> None:
        """Done or not doing, for any row: a finite task closes through task.py, an inbox item closes or
        drops, every other row (a GitHub issue, an application, a deadline from a protocol) leaves the
        briefing for good, while its source stays as it is. A stream never settles. All rows are checked
        before the first write."""
        plan = []
        for key in keys:
            entry = self.entry(key, "keys")
            row, out = entry["row"], entry["out"] or {}
            if row.get("task") and not row.get("inbox_id"):
                if not out.get("closable"):
                    raise self.not_applicable("a stream runs on, it never settles", "keys")
                plan.append(("task", key, row))
            elif row.get("inbox_id"):
                self.inbox_id(row)
                plan.append(("inbox", key, row))
            else:
                plan.append(("other", key, row))
        extra = f": {text}" if text else ""
        tasks = [k for kind, k, _ in plan if kind == "task"]
        if tasks:
            self.v_task_close(ctx, tasks, outcome, text)
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
        ctx.note(word.format(title=m.short(title, 60)))
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
            ctx.note(self.tx["task_kept" if len(slugs) == 1 else "task_kept_many"].format(n=len(slugs), title=m.short(rows[0][0]["title"], 60)))
        else:
            ctx.note(self.tx["task_keep_failed"].format(err=m.short(run.err, 100)), bad=True)

    def v_note(self, ctx: Ctx, key: str, text: str) -> None:
        row = self.entry(key)["row"]
        if row.get("task"):
            slug = self.slug(row)
            run = ctx.call("task.note", slug, self.task_cmd("note", slug, "--", text), SHORT_TIMEOUT)
        elif row.get("inbox_id"):
            item = self.inbox_id(row)
            run = ctx.call("inbox.note", item, self.inbox("note", item, "--", text), SHORT_TIMEOUT)
        else:
            raise self.not_applicable("notes only go to tasks and inbox items")
        if run.ok:
            ctx.note(self.tx["note_added"].format(title=m.short(row["title"], 40), line=m.short(text, 60)))
            ctx.delta()
        else:
            ctx.note(self.tx["note_failed"].format(err=m.short(run.err, 100)), bad=True)

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
