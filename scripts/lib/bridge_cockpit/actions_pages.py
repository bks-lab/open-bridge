# SPDX-License-Identifier: MIT
"""Verbs of the start page and the settings page (tiles, pins, the first-run tour, launch and ticker settings, the decision
guide, the return channel), of a briefing page's own rows (an account's status, a board's mode, a command row's steps)
and of a background job of the workers view (Analyse in a tab).
"""
from __future__ import annotations

import datetime as dt
import json
import re

from . import model as m
from .guide import GuideError
from .launch import LaunchError
from .ticker import TickerError
from .actions_base import CONTROL_RE, INBOX_ID_RE, SHORT_TIMEOUT, UNDO_TOKEN_RE, ActionError, Ctx


class PageVerbs:
    """A part of Actions (actions.py), which holds the registry and the helpers called here."""

    def v_home_tiles(self, ctx: Ctx, ids: list, seen: list | None = None) -> None:
        """The start page's choice of tiles and shelves, kept on the server so every browser shows the same"""
        self.app.store.set_home_tiles(ids, seen)
        self.app.broadcast("home", self.app.store.home())

    def v_tour_done(self, ctx: Ctx, how: str, v: int) -> None:
        """The first-run tour was finished or skipped: kept on the server, so no other browser offers it again"""
        self.app.store.set_tour(how, v)
        self.tour_changed(ctx)

    def v_tour_reset(self, ctx: Ctx) -> None:
        """Offer the tour again on the next visit"""
        self.app.store.set_tour(None)
        self.tour_changed(ctx)

    def tour_changed(self, ctx: Ctx) -> None:
        state = self.app.tour_state()
        ctx.extra["tour"] = state
        self.app.broadcast("tour", state)

    def v_launch_settings(self, ctx: Ctx, settings: dict) -> None:
        """The settings page's change of how an agent picks its model; kept beside the config, never in it"""
        try:
            self.app.launch_model.save(settings)
        except LaunchError as error:
            raise ActionError(error.status, error.code, error.message, error.field) from None
        self.settings_changed(ctx)

    def v_launch_settings_reset(self, ctx: Ctx) -> None:
        """Back to what bridge-config.yaml says"""
        self.app.launch_model.reset()
        self.settings_changed(ctx)

    def settings_changed(self, ctx: Ctx) -> None:
        state = self.app.launch_model.state()
        ctx.extra["launch"] = state
        self.app.broadcast("launch", state)

    # the news ticker (ticker.py): each verb returns at once, a thread does the slow part and
    # broadcasts the `ticker` event when it ends; none of them waits under the write lock

    def v_ticker_settings(self, ctx: Ctx, settings: dict) -> None:
        """The settings page's change of the ticker; kept beside the config, never in it"""
        try:
            self.app.ticker.save(settings)
        except TickerError as error:
            raise ActionError(error.status, error.code, error.message, error.field) from None
        self.ticker_changed(ctx)

    def v_ticker_settings_reset(self, ctx: Ctx) -> None:
        """Back to what bridge-config.yaml says"""
        self.app.ticker.reset()
        self.ticker_changed(ctx)

    def v_ticker_refresh(self, ctx: Ctx) -> None:
        """Read the feeds now; a refresh already running is no error"""
        if not self.app.ticker.request_refresh():
            ctx.extra["already"] = True
        self.ticker_changed(ctx)

    def v_ticker_edit(self, ctx: Ctx) -> None:
        """Let Claude Haiku pick and shorten the items: only ever on this click"""
        try:
            started = self.app.ticker.edit_start()
        except TickerError as error:
            raise ActionError(error.status, error.code, error.message, error.field) from None
        if not started:
            raise ActionError(409, "not_applicable", "the editor is already running")
        self.ticker_changed(ctx)

    def v_ticker_profile(self, ctx: Ctx, llm: bool = False) -> None:
        """Propose interests from the open tasks, as keywords or (llm) written by Claude Haiku; a proposal
        only, the page saves it when the owner takes it"""
        try:
            started = self.app.ticker.profile_start(bool(llm))
        except TickerError as error:
            raise ActionError(error.status, error.code, error.message, error.field) from None
        if not started:
            raise ActionError(409, "not_applicable", "a proposal is already being written")
        self.ticker_changed(ctx)

    # the decision guide (guide.py): a reading runs on the guide's own thread and ends with a `guide` event

    def v_guide_read(self, ctx: Ctx, tab_ref: str) -> None:
        """Let Claude Haiku read where this waiting tab stands and what it could be told next"""
        try:
            started = self.app.guide.start(tab_ref)
        except GuideError as error:
            raise ActionError(error.status, error.code, error.message, error.field) from None
        if not started:
            raise ActionError(409, "not_applicable", "a reading of this tab is already under way")
        self.guide_changed(ctx)

    def v_guide_settings(self, ctx: Ctx, enabled: bool | None = None, auto: bool | None = None) -> None:
        """The settings page's switches of the guide; kept beside the config, never in it"""
        change = {k: v for k, v in (("enabled", enabled), ("auto", auto)) if v is not None}
        try:
            self.app.guide.save(change)
        except GuideError as error:
            raise ActionError(error.status, error.code, error.message, error.field) from None
        self.guide_changed(ctx)
        self.app.tabs.schedule(0)          # switched on: the waiting tabs are read at the next poll

    def v_guide_settings_reset(self, ctx: Ctx) -> None:
        """Back to what bridge-config.yaml says"""
        self.app.guide.reset()
        self.guide_changed(ctx)

    def guide_changed(self, ctx: Ctx) -> None:
        state = self.app.guide.state()
        ctx.extra["guide"] = state
        self.app.broadcast("guide", state)

    def ticker_changed(self, ctx: Ctx) -> None:
        state = self.app.ticker.state()
        ctx.extra["ticker"] = state
        self.app.broadcast("ticker", state)

    def v_return_forget(self, ctx: Ctx, key: str) -> None:
        """Take a start out of the return channel; the row and its tab stay as they are"""
        if not self.app.launches.forget(key):
            raise self.not_applicable("no start of that row in the return channel")
        self.app.collector.rebuild()

    def v_run_seen(self, ctx: Ctx, id: str) -> None:
        """A workflow run's result checked in the files view: it no longer waits in its task's file. Only a run
        the page was shown (bound to an open task) can be marked"""
        run = next((r for r in self.app.sessions_state()["runs"] if r["id"] == id), None)
        if run is None:
            raise ActionError(409, "stale_row", "no such workflow run of an open task", "id")
        self.app.store.run_seen(id)
        ctx.note(self.tx["run_seen"].format(name=m.short(run["name"], 40), slug=run["task"]),
                 go={"kind": "item", "key": f"task:{run['task']}"})
        self.app.broadcast("sessions", self.app.sessions_state())

    def v_pin(self, ctx: Ctx, key: str, on: bool) -> None:
        """A row on the start page's pinned shelf; it stays until taken off, whatever the briefing says"""
        self.app.store.pin(key, on)
        self.app.broadcast("home", self.app.store.home())

    def v_account_status(self, ctx: Ctx, page: str, section: str, index: int, status: str) -> None:
        """Set an account's `status:` in its file (bridge-resources.py set-status), then ask that page
        again without its cached answers, so the row, the overview and the inventory follow."""
        app = self.app
        found = app.collector.page_item(page, section, index)
        if not found:
            raise ActionError(409, "stale_row", "the page item is no longer in the model", "index")
        account = found[1].get("account")
        if not isinstance(account, dict) or not isinstance(account.get("id"), str):
            raise self.not_applicable("not an account row", "index")
        aid = account["id"]
        ctx.subject = f"account:{aid}"
        script = app.runner.script("scripts/bridge-resources.py")
        run = ctx.call("bridge-resources.set-status", aid,
                       [app.runner.python, script, "--root", str(app.root), "set-status", aid, status], SHORT_TIMEOUT)
        if not run.ok:
            ctx.note(self.tx["status_failed"].format(err=m.short(run.err or run.out, 120)), bad=True)
            return
        for pg in (app.collector.view or {}).get("pages", []):
            if pg.get("id") == page:
                for sec in pg.get("sections", []):
                    for cached in (app.root / ".bridge" / "briefing-cache").glob(f"*/{sec.get('id')}.json"):
                        cached.unlink(missing_ok=True)     # a cache, rebuilt by the next pass
        ctx.note(self.tx["status_set"].format(title=m.short(found[1].get("title") or aid, 60),
                                              status=self.tx["account_status"][status]))
        app.collector.request("full")

    def v_github_board(self, ctx: Ctx, section: str, slug: str, mode: str) -> None:
        """Switch one board of a GitHub section: off (not asked, costs nothing), mine (your cards), all (every open
        card). The choice is this person's, kept in .bridge/github-boards.json, never in the profile; the section is
        asked again at once."""
        found = next((b for pg in (self.app.collector.view or {}).get("pages", []) for sec in pg.get("sections", [])
                      if sec.get("id") == section for b in sec.get("boards") or [] if b.get("slug") == slug), None)
        if found is None:
            raise ActionError(409, "stale_row", "the board is not in that section", "slug")
        ctx.subject = f"board:{slug}"
        try:
            from ..briefing_providers.github_work import save_board_mode
            save_board_mode(self.app.root, slug, mode)
        except (OSError, ValueError, ImportError) as exc:
            ctx.note(self.tx["status_failed"].format(err=m.short(str(exc), 120)), bad=True)
            return
        ctx.note(self.tx["board_mode_set"].format(name=m.short(found.get("name") or slug, 60),
                                                  mode=self.tx["board_mode"][mode]))
        self.forget_section(section)

    def v_github_board_default(self, ctx: Ctx, mode: str) -> None:
        """The mode a board takes until the person switches it, from the settings; "profile" leaves it to the
        profile again. Kept beside the switches, every section with boards is asked again."""
        ctx.subject = "board:default"
        try:
            from ..briefing_providers.github_work import save_board_default
            save_board_default(self.app.root, None if mode == "profile" else mode)
        except (OSError, ValueError, ImportError) as exc:
            ctx.note(self.tx["status_failed"].format(err=m.short(str(exc), 120)), bad=True)
            return
        ctx.note(self.tx["board_default_set"].format(mode=self.tx["board_default"][mode]))
        for sec in {sec.get("id") for pg in (self.app.collector.view or {}).get("pages", [])
                    for sec in pg.get("sections", []) if sec.get("boards")}:
            self.forget_section(sec)

    # ------------------------------------------------------------ a command row's own steps

    def briefing_act(self, ctx: Ctx, section: str, row: str, action: str) -> dict | None:
        """`briefing.py act`: the profile's section runs the step after asking its rows again."""
        app = self.app
        view = app.collector.view or {}
        profile = app.cfg.profile or (view.get("profile") if isinstance(view.get("profile"), str) else None)
        if not profile:
            raise self.not_applicable("no briefing profile to act through", None)
        argv = [app.runner.python, app.runner.script("scripts/briefing.py"), "--root", str(app.root), "act",
                profile, section, row, action]
        key = f"{section}/{row}"
        with self.acting_lock:
            if key in self.acting:
                raise ActionError(409, "not_applicable", "a step of this row is already running")
            self.acting.add(key)
        try:
            # up to 90 s: without the write lock, so every other click goes on meanwhile (review C30)
            with ctx.unlocked():
                run = ctx.call("briefing.act", key, argv, SHORT_TIMEOUT * 3)
        finally:
            with self.acting_lock:
                self.acting.discard(key)
        if not run.ok:
            ctx.note(self.tx["step_failed"].format(err=m.short(run.err or run.out, 120)), bad=True)
            return None
        try:
            data = json.loads(run.out.strip().splitlines()[-1])
        except (ValueError, IndexError):
            data = {}
        self.forget_section(section)
        return data if isinstance(data, dict) else {}

    def forget_section(self, section: str) -> None:
        """The section's cached answer is void after a step: the next pass asks it again."""
        for cached in (self.app.root / ".bridge" / "briefing-cache").glob(f"*/{section}.json"):
            cached.unlink(missing_ok=True)
        self.app.collector.request("full")

    def v_row_action(self, ctx: Ctx, page: str, section: str, index: int, action: str) -> None:
        found = self.app.collector.page_item(page, section, index)
        if not found:
            raise ActionError(409, "stale_row", "the page item is no longer in the model", "index")
        it = found[1]
        steps = {a.get("id"): a.get("label") for a in it.get("actions") or [] if isinstance(a, dict)}
        row = it.get("row_id")
        if action not in steps or not isinstance(row, str):
            raise self.not_applicable("the row does not offer this step", "action")
        ctx.subject = f"{section}/{row}"
        data = self.briefing_act(ctx, section, row, action)
        if data is None:
            return
        label = str(data.get("did") or steps[action])
        launch = data.get("launch")
        if isinstance(launch, dict) and all(isinstance(launch.get(k), str) and launch[k].strip()
                                            for k in ("summary", "prompt", "key")):
            # a step that hands back a tab (a calendar row's prepare): filed under the event's key, so a second
            # click finds the same item, and started like Do it; the inbox item is its record, no undo
            summary = CONTROL_RE.sub(" ", launch["summary"]).strip()[:200]
            new_id = self.inbox_add(ctx, row, summary, CONTROL_RE.sub(" ", launch["prompt"]).strip()[:3500],
                                    key=CONTROL_RE.sub(" ", launch["key"]).strip()[:240])
            if new_id is not None:
                self.launch(ctx, [{"key": f"inbox:{new_id}", "inbox_id": new_id, "title": summary}], "go",
                            self.app.cfg.target, word=label)
            return
        undo = data.get("undo")
        ctx.history.append({"key": f"row:{section}:{row}", "title": str(it.get("title") or row)[:200], "kind": "row",
                            "did": label, "ident": row, "undone_ms": None,
                            "undo": {"verb": "row_undo", "args": {"section": section, "row": row, "action": undo}}
                            if isinstance(undo, str) and UNDO_TOKEN_RE.match(undo) else None})
        ctx.note(self.tx["step_done"].format(title=m.short(str(it.get("title") or row), 60), did=label), go={"kind": "page", "id": page})

    def worker_run(self, host: str, ident: str) -> dict | None:
        """The background job `ident` on `host` as the kept workers view holds it (GET /api/workers), a retired one
        never; None when the view or the job is not there"""
        try:
            view = json.loads((self.app.root / ".bridge" / "resources" / "workers-view.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        runs = view.get("runs") if isinstance(view, dict) else None
        return next((r for r in runs if isinstance(r, dict) and r.get("host") == host and r.get("id") == ident
                     and not r.get("retired")), None) if isinstance(runs, list) else None

    def worker_state(self, run: dict) -> str:
        state = str(run.get("state") or "unknown")
        return self.tx["worker_state"].get(state, state)

    def worker_items(self, runs: list) -> None:
        """Every job filed under worker:<host>:<id> gets `advise`: the newest item of that key, {inbox, state}, so its
        row shows the tab and its result instead of offering a second start; the others are left as they are"""
        newest: dict[str, dict] = {}
        for e in self.app.inbox_listing() or []:
            key = str(e.get("key") or "") if isinstance(e, dict) else ""
            if key.startswith("worker:") and INBOX_ID_RE.match(str(e.get("id"))) and e["id"] > newest.get(key, {}).get("id", ""):
                newest[key] = e
        for r in runs:
            found = newest.get(f"worker:{r.get('host')}:{r.get('id')}") if isinstance(r, dict) else None
            if found:
                r["advise"] = {"inbox": found["id"], "state": str(found.get("state") or "")}

    def worker_brief(self, run: dict) -> str:
        """What the advising tab is told, all of it from the workers view: job, machine, unit, schedule, program, log,
        every finding with its hint, the last and the next run, and what it reads and checks"""
        tx, none = self.tx, self.tx["worker_unknown"]
        last = (run.get("strip") or [None])[-1]
        last_text = (f"{last.get('at')} ({last.get('verdict') or '?'}, rc {last.get('rc')})"
                     if isinstance(last, dict) and last.get("at") else none)
        next_text = none
        every = re.match(r"^every (\d+)s$", str(run.get("when") or ""))
        stamp = last.get("at") if isinstance(last, dict) else None
        if every and stamp:
            try:
                at = dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00")) + dt.timedelta(seconds=int(every[1]))
                next_text = at.isoformat(timespec="seconds")
            except ValueError:
                pass
        elif not every:
            now = dt.datetime.fromtimestamp(self.app.clock() / 1000)
            pct = (now.hour * 60 + now.minute) / 14.4
            later = [x for x in (run.get("day") or {}).get("marks") or []
                     if isinstance(x, dict) and x.get("today") and float(x.get("at_pct") or 0) > pct]
            next_text = str(later[0].get("label") or none) if later else none
        findings = "\n".join("- " + tx["worker_finding"].format(
            state=tx["worker_state"].get(str(f.get("state")), str(f.get("state") or "?")), detail=f.get("detail") or "",
            hint=tx["worker_hint"].format(hint=f["hint"]) if f.get("hint") else "")
            for f in run.get("findings") or [] if isinstance(f, dict)) or none
        program = str(run.get("program") or "") + m.paren(str(run.get("program_where") or "")) if run.get("program") else ""
        text = tx["worker_brief"].format(
            id=run["id"], host=run["host"], title=run.get("title") or run["id"], kind=run.get("kind") or none,
            when=run.get("when") or none, unit=run.get("unit") or none, runtime=run.get("runtime") or none,
            program=program or none, log=run.get("log") or none, last=last_text, next=next_text, findings=findings)
        return CONTROL_RE.sub(" ", text)[:3500]

    def v_worker_advise(self, ctx: Ctx, host: str, id: str) -> None:
        """Analyse in a tab on a background job: filed under worker:<host>:<id> with a brief built here from the
        workers view (never from the page), and started in mode report (Advise: read and propose, change nothing).
        A second click finds the same item, so its tab opens instead of a second one, as for a row's step"""
        run = self.worker_run(host, id)
        if run is None:
            raise self.not_applicable("the workers view holds no such job", "id")
        key = f"worker:{host}:{id}"
        ctx.subject = key
        summary = self.tx["worker_summary"].format(id=id, host=host, state=self.worker_state(run))
        new_id = self.inbox_add(ctx, key, summary, self.worker_brief(run), key=key)
        if new_id is not None:
            self.launch(ctx, [{"key": f"inbox:{new_id}", "inbox_id": new_id, "title": summary}], "report",
                        self.app.cfg.target, word=self.tx["btn_worker_advise"])

    def v_row_undo(self, ctx: Ctx, section: str, row: str, action: str) -> None:
        ctx.subject = f"{section}/{row}"
        # only an undo this server handed out for a step it ran, and only once: the token is written into a file
        history = getattr(self.app, "history", None)
        it = history.open_undo("row_undo", {"section": section, "row": row, "action": action}) if history else None
        if it is None:
            raise self.not_applicable("no step on this row to take back", "action")
        if self.briefing_act(ctx, section, row, action) is None:
            return
        history.mark(it)
        ctx.note(self.tx["step_undone"].format(title=m.short((it or {}).get("title") or row, 60)))
