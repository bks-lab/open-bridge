# SPDX-License-Identifier: MIT
"""Verbs of the start page and the settings page (tiles, pins, launch and ticker settings, the decision
guide, the return channel) and of a briefing page's own rows (an account's status, a board's mode, a command row's steps).
"""
from __future__ import annotations

import json

from . import model as m
from .guide import GuideError
from .launch import LaunchError
from .ticker import TickerError
from .actions_base import CONTROL_RE, SHORT_TIMEOUT, UNDO_TOKEN_RE, ActionError, Ctx


class PageVerbs:
    """A part of Actions (actions.py), which holds the registry and the helpers called here."""

    def v_home_tiles(self, ctx: Ctx, ids: list, seen: list | None = None) -> None:
        """The start page's choice of tiles and shelves, kept on the server so every browser shows the same"""
        self.app.store.set_home_tiles(ids, seen)
        self.app.broadcast("home", self.app.store.home())

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
        run = ctx.call("briefing.act", f"{section}/{row}", argv, SHORT_TIMEOUT * 3)
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
        ctx.note(self.tx["step_done"].format(title=m.short(str(it.get("title") or row), 60), did=label))

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
