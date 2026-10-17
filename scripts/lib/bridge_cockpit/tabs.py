# SPDX-License-Identifier: MIT
"""Tab poller of the cockpit: agent tabs from `workplace.py status --json`.

The server is the only poller (never two status calls at once) and runs while at least
one page is connected, every `tabs_seconds`, plus the follow-up polls the mod makes after
a launch (+5 s), a key or a message (+3 s), a close (+1 s) and an adopt (now). It keeps
since when each tab is in its state (tab_seen), raises alerts for tabs that newly wait
or wait or run for an hour, and marks the control tab, which never counts as waiting.
The server never reads or writes .bridge/briefing-ui/tabs.json (that file is the mod's).
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any

from . import model as m
from . import returns as ret

STATUS_TIMEOUT = 20


class TabPoller:
    def __init__(self, app: Any):
        self.app = app
        self.lock = threading.RLock()
        self.busy = threading.Lock()
        self.cond = threading.Condition()
        self.tabs: list[dict] = []
        self.seen: dict[str, dict] = {}
        self.error: dict | None = None
        self.at_ms = 0
        self.polled_once = False
        self.control: str | None = None
        self.next_extra = float("inf")
        self.last_poll = 0.0
        self.stop = False

    # ------------------------------------------------------------ reads

    def tab_list(self) -> list[dict]:
        with self.lock:
            return [dict(t) for t in self.tabs]

    def seen_copy(self) -> dict:
        with self.lock:
            return {k: dict(v) for k, v in self.seen.items()}

    def pick_control(self, tabs: list[dict], now: float) -> str | None:
        """The control tab: the oldest one in the control workspace that has the relay on, else the oldest
        there. A session that started before the web part was switched on never heartbeats and would
        otherwise keep the page offline for good. Picked again at every read, not only at a tab poll, so a
        session that comes up between two polls is used at once."""
        app = self.app
        # the relay off, no tab is singled out: the oldest Claude tab was often the one being worked in
        if not app.cfg.relay:
            return None
        candidates = [t for t in tabs if app.cfg.control and t["workspace"] == app.cfg.control and t["state"] != "shell"]
        if not candidates:
            return None
        live = {h["surface"] for h in app.relay.heartbeats(now) if h["surface"]}
        pool = [t for t in candidates if t.get("id") in live or t.get("ref") in live] or candidates
        return min(pool, key=lambda t: m.ref_number(t["ref"]))["ref"]

    def control_ref(self) -> str | None:
        tabs = self.tab_list()
        control = self.pick_control(tabs, self.app.clock())
        with self.lock:
            self.control = control
        return control

    def control_tab(self) -> dict | None:
        ref = self.control_ref()
        with self.lock:
            return next((dict(t) for t in self.tabs if t["ref"] == ref), None)

    def find(self, ref: str) -> dict | None:
        with self.lock:
            return next((dict(t) for t in self.tabs if t["ref"] == ref), None)

    def state(self, view: dict | None) -> dict:
        """TabsState (contract section 8.1)."""
        self.control_ref()                 # the pick follows the heartbeats, not only the last poll
        now = self.app.clock()
        with self.lock:
            tabs = []
            for t in self.tabs:
                is_control = t["ref"] == self.control
                filed = m.filed_by(t, view)
                seen = self.seen.get(t["ref"], {})
                tabs.append({
                    "ref": t["ref"], "ws_ref": t["ws_ref"], "name": t["name"], "workspace": t["workspace"],
                    "state": t["state"], "last": t["last"], "slug": t["slug"], "item": t["item"], "team": t["team"],
                    "role": t["role"], "live": m.is_live(t), "waiting": m.is_waiting(t, view) and not is_control,
                    "is_control": is_control, "filed_by": filed["key"] if filed else None,
                    "settled": None if is_control else ret.tab_settled(self.app.root, t),
                    "since_ms": int(seen.get("since_ms", 0)), "long": None if is_control else m.long_state(t, self.seen, now),
                })
            control = {"name": self.app.cfg.control, "ref": self.control} if self.app.cfg.control and self.control else None
            return {"at_ms": self.at_ms, "tabs": tabs, "error": dict(self.error) if self.error else None, "control": control}

    # ------------------------------------------------------------ poll

    def poll(self, wait: bool = True) -> bool:
        """One status call; False when another one was running and wait is False."""
        if not self.busy.acquire(blocking=wait):
            return False
        try:
            self._poll_once()
        finally:
            self.busy.release()
            self.last_poll = time.monotonic()
        return True

    def _poll_once(self) -> None:
        app = self.app
        run = app.run(app.workplace("status", "--json"), STATUS_TIMEOUT)
        now = app.clock()
        raw = None
        why = ""
        if run.ok:
            try:
                raw = json.loads(run.out)
                if not isinstance(raw, list):
                    raise ValueError("status is not a list")
            except ValueError as error:
                raw, why = None, str(error)
        else:
            lines = [line for line in (run.err or "").strip().splitlines() if line.strip()]
            why = lines[-1] if lines else app.tx["status_failed"]
        alerts: list[dict] = []
        with self.lock:
            if raw is None:
                if self.error is None:
                    self.error = {"since": m.clock_time(now), "message": m.short(why, 80)}
            else:
                self.error = None
                new = [m.to_tab(t) for t in raw if isinstance(t, dict)]
                control = self.pick_control(new, now)
                known = {t["ref"]: t["state"] for t in self.tabs}
                if self.polled_once:
                    for t in new:
                        if t["ref"] == control or t["state"] not in m.ATTENTION:
                            continue
                        if t["ref"] in known and known[t["ref"]] not in m.ATTENTION:
                            alerts.append({"kind": "tab_waiting", "ref": t["ref"], "name": t["name"],
                                           "workspace": t["workspace"], "state": t["state"]})
                seen = {}
                for t in new:
                    prev = self.seen.get(t["ref"])
                    seen[t["ref"]] = prev if prev and prev["state"] == t["state"] else {
                        "state": t["state"], "since_ms": now, "warned": False}
                for t in new:
                    entry = seen[t["ref"]]
                    if t["ref"] != control and m.long_state(t, seen, now) and not entry["warned"]:
                        seen[t["ref"]] = {**entry, "warned": True}
                        alerts.append({"kind": "tab_long", "ref": t["ref"], "name": t["name"],
                                       "workspace": t["workspace"], "state": t["state"]})
                self.tabs, self.seen, self.control = new, seen, control
                self.polled_once = True
                self.at_ms = int(now)
        app.on_tabs(alerts)

    # ------------------------------------------------------------ schedule

    def schedule(self, delay_s: float) -> None:
        with self.cond:
            self.next_extra = min(self.next_extra, time.monotonic() + delay_s)
            self.cond.notify_all()

    def loop(self) -> None:
        while True:
            with self.cond:
                if self.stop:
                    return
                now = time.monotonic()
                periodic = self.last_poll + self.app.cfg.tabs_seconds if self.app.client_count() > 0 else float("inf")
                wake = min(self.next_extra, periodic)
                if wake > now:
                    self.cond.wait(timeout=min(wake - now, 1.0))
                    continue
                self.next_extra = float("inf")
            try:
                self.poll()
            except Exception:
                import traceback
                self.app.log_error("tab poll failed:\n" + traceback.format_exc())

    def shutdown(self) -> None:
        with self.cond:
            self.stop = True
            self.cond.notify_all()
