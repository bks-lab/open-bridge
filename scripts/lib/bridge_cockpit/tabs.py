# SPDX-License-Identifier: MIT
"""Tab poller of the cockpit: agent tabs from `workplace.py status --json`.

The server is the only poller (never two status calls at once) and runs while at least
one page is shown, every `tabs_seconds` (every HIDDEN_TABS_S while the only open pages sit in
background browser tabs, so their title count stays roughly current), plus follow-up polls after
a launch (+5 s), a key or a message (+3 s), a close (+1 s) and an adopt (now). It keeps
since when each tab is in its state (tab_seen), in SEEN_FILE under the state folder too, so a restart of the
server keeps how long a tab has waited (the first poll after it takes the kept time of a tab still in the same
state, and forgets the tabs that are gone), raises alerts for tabs that newly wait
or wait or run for an hour, and marks the control tab, which never counts as waiting.
With `cockpit.chat_layout: workspaces` each poll also asks `workplace.py workspaces --json` for the
workspaces as the terminal shows them (read only); None when the driver cannot say.
Each poll also reads what the waiting tabs ask (asks.py) off their screens: only for the tabs that wait
or need you, only when the driver serves `screen`, again only when a tab's state changed or its question
is a minute old, at most ASK_READS_PER_POLL reads in ASK_BUDGET_S seconds, the tabs that need you first.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from . import asks as ak
from . import model as m
from . import organize as org
from . import returns as ret

STATUS_TIMEOUT = 20
WORKSPACES_EVERY_MS = 30_000   # the workspaces change slowly and cost one cmux call each: at most every half minute
WORKSPACES_TIMEOUT = 40
HIDDEN_TABS_S = 60   # the poll interval while every open page is hidden
ASK_REFRESH_MS = 60_000   # a question unchanged in its state is read again after a minute
ASK_READS_PER_POLL = 4
ASK_BUDGET_S = 3
SEEN_FILE = "tabs-seen.json"   # since when each tab is in its state, kept across restarts


class TabPoller:
    def __init__(self, app: Any):
        self.app = app
        self.lock = threading.RLock()
        self.busy = threading.Lock()
        self.cond = threading.Condition()
        self.tabs: list[dict] = []
        self.workspaces: list[dict] | None = None
        self.workspaces_ms = 0.0
        self.seen: dict[str, dict] = self._load_seen()
        self.asks: dict[str, tuple] = {}   # ref -> ((state, last, since_ms), ask or None, read at ms)
        self.error: dict | None = None
        self.at_ms = 0
        self.polled_once = False
        self.control: str | None = None
        self.next_extra = float("inf")
        self.last_poll = 0.0
        self.stop = False
        self.monotonic = time.monotonic   # the loop's clock; tests replace it

    # ------------------------------------------------------------ since when, kept

    def _seen_path(self):
        folder = getattr(self.app, "state_dir", None)
        return None if folder is None else os.path.join(str(folder), SEEN_FILE)

    def _load_seen(self) -> dict[str, dict]:
        """The kept since of each tab ({ref: {state, since_ms, warned}}); empty when there is none or it does not read"""
        path = self._seen_path()
        try:
            with open(path, encoding="utf-8") as handle:     # type: ignore[arg-type]
                data = json.load(handle)
        except (OSError, TypeError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {ref: {"state": v["state"], "since_ms": float(v["since_ms"]), "warned": bool(v.get("warned"))}
                for ref, v in data.items() if isinstance(ref, str) and isinstance(v, dict) and isinstance(v.get("state"), str)
                and isinstance(v.get("since_ms"), (int, float))}

    def _save_seen(self, seen: dict) -> None:
        """Write the since of each tab when a tab came, went or changed its state; a failed write keeps it in memory"""
        path = self._seen_path()
        if path is None:
            return
        try:
            from .store import atomic_write_json
            atomic_write_json(Path(path), seen)
        except OSError:
            pass

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

    def workspace_list(self) -> list[dict] | None:
        """The workspaces as the terminal showed them at the last read (chat_layout workspaces), else None"""
        with self.lock:
            return [dict(w) for w in self.workspaces] if self.workspaces is not None else None

    def refresh_workspaces(self) -> None:
        """The next poll reads the workspaces again, not after half a minute (a workspace was renamed).
        Only with chat_layout workspaces: otherwise no list is read and rooms come from the tabs."""
        with self.lock:
            self.workspaces_ms = 0.0

    def read_workspaces(self) -> list[dict] | None:
        """The workspaces read now (organize: the list as it is, not as it was half a minute ago), one read at a
        time with the polls (the busy lock). Kept as the list the page shows when the chat lists workspaces."""
        with self.busy:
            rows = self._workspaces()
        if rows is not None and self.app.cfg.chat_layout == "workspaces":
            with self.lock:
                self.workspaces = rows
                self.workspaces_ms = self.app.clock()
        return [dict(w) for w in rows] if rows is not None else None

    def _ask_of(self, t: dict) -> dict | None:
        """The question read off a tab's screen, only while the tab still is in the state it was read in;
        called with self.lock held"""
        held = self.asks.get(t["ref"])
        return held[1] if held and held[0][0] == t["state"] and t["state"] in m.ATTENTION else None

    def asks_now(self) -> dict:
        """{ref: question} of the tabs that ask one now (the return channel tells a question from a still tab)"""
        with self.lock:
            return {t["ref"]: self._ask_of(t) for t in self.tabs if self._ask_of(t)}

    def find(self, ref: str) -> dict | None:
        with self.lock:
            return next((dict(t) for t in self.tabs if t["ref"] == ref), None)

    def state(self, view: dict | None) -> dict:
        """TabsState (contract section 8.1)."""
        self.control_ref()                 # the pick follows the heartbeats, not only the last poll
        now = self.app.clock()
        # the task of the session in each tab, for a tab known by its name alone (read outside the lock)
        tasks = self.app.tab_tasks() if hasattr(self.app, "tab_tasks") else {}
        with self.lock:
            tabs = []
            for t in self.tabs:
                is_control = t["ref"] == self.control
                filed = m.filed_by(t, view)
                seen = self.seen.get(t["ref"], {})
                ask = self._ask_of(t)
                tabs.append({
                    "ref": t["ref"], "ws_ref": t["ws_ref"], "name": t["name"], "workspace": t["workspace"],
                    "state": t["state"], "last": t["last"], "slug": t["slug"], "item": t["item"], "team": t["team"],
                    "role": t["role"], "state_source": t.get("state_source"), "live": m.is_live(t), "waiting": m.is_waiting(t, view) and not is_control,
                    "idle": t.get("idle") is True and not is_control,
                    "is_control": is_control, "filed_by": filed["key"] if filed else None,
                    "settled": None if is_control else ret.tab_settled(self.app.root, t),
                    "behind": None if is_control else ret.tab_behind(self.app.root, t, tasks.get(t["ref"])),
                    "since_ms": int(seen.get("since_ms", 0)), "long": None if is_control else m.long_state(t, self.seen, now),
                    "ask": None if is_control or ask is None else dict(ask, options=[dict(o) for o in ask["options"]]),
                })
            control = {"name": self.app.cfg.control, "ref": self.control} if self.app.cfg.control and self.control else None
            return {"at_ms": self.at_ms, "tabs": tabs, "error": dict(self.error) if self.error else None, "control": control,
                    "workspaces": [dict(w) for w in self.workspaces] if self.workspaces is not None else None}

    # ------------------------------------------------------------ poll

    def poll(self, wait: bool = True, asks: bool = True) -> bool:
        """One status call; False when another one was running and wait is False. `asks=False` reads no
        question (the guard of a reply polls that way: it reads the one screen it needs itself)."""
        if not self.busy.acquire(blocking=wait):
            return False
        try:
            self._poll_once(asks)
        finally:
            self.busy.release()
            self.last_poll = self.monotonic()
        return True

    def _poll_once(self, asks: bool = True) -> None:
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
                # the idle mark lives as long as the state it was given in, never on the control tab; the next
                # read of questions renews it
                before = {t["ref"]: t for t in self.tabs}
                for t in new:
                    old = before.get(t["ref"])
                    t["idle"] = bool(t["ref"] != control and old and old.get("idle") and old["state"] == t["state"])
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
                changed = seen != self.seen
                self.tabs, self.seen, self.control = new, seen, control
                if changed:
                    self._save_seen(seen)
                self.polled_once = True
                self.at_ms = int(now)
        if app.cfg.chat_layout != "workspaces":
            with self.lock:
                self.workspaces = None
        elif self.workspaces is None or now - self.workspaces_ms >= WORKSPACES_EVERY_MS:
            workspaces = self._workspaces()
            with self.lock:
                if workspaces is not None or self.workspaces is None:   # a failed read keeps the last list
                    self.workspaces = workspaces
                if workspaces is not None:
                    self.workspaces_ms = now
        if asks and raw is not None:
            self._refresh_asks(now)
            self._mark_idle(now)
        app.on_tabs(alerts)

    def _refresh_asks(self, now: float) -> None:
        """The questions of the tabs that wait or need you, read off their screens (asks.py). The candidates
        first and the driver's caps second, so a poll without a waiting tab asks the driver nothing."""
        app = self.app
        if not getattr(app, "asks_enabled", True):
            with self.lock:
                self.asks = {}
            return
        view = app.collector.view
        with self.lock:
            tabs = [dict(t) for t in self.tabs]
            seen = {k: dict(v) for k, v in self.seen.items()}
            control = self.control
            held = dict(self.asks)
        # an idle tab is read too: a question that comes later brings it back
        candidates = [t for t in tabs if t["ref"] != control and m.waits(t, view)]
        if not candidates or "screen" not in app.driver_caps():
            with self.lock:
                self.asks = {}
            return
        keyed = [(t, (t["state"], t["last"], int(seen.get(t["ref"], {}).get("since_ms", 0)))) for t in candidates]
        keyed.sort(key=lambda x: (0 if x[0]["state"] == "needs-you" else 1, x[1][2]))
        kept: dict[str, tuple] = {}
        reads = 0
        started = self.monotonic()
        for t, key in keyed:
            ref = t["ref"]
            old = held.get(ref)
            if old and old[0] == key and 0 <= now - old[2] < ASK_REFRESH_MS:
                kept[ref] = old
                continue
            if reads >= ASK_READS_PER_POLL or self.monotonic() - started >= ASK_BUDGET_S:
                if old and old[0] == key:
                    kept[ref] = old          # an old question of the same state waits for the next poll
                continue
            reads += 1
            text, _digest, _err = app.tab_screen(ref)
            ask = ak.question_of(text, t["state"], app.scrub) if text is not None else None
            kept[ref] = (key, ask, now)
        with self.lock:
            self.asks = kept

    def _mark_idle(self, now: float) -> None:
        """Which waiting tabs are done rather than asking (model.is_idle), from the questions just read"""
        after_ms = float(getattr(self.app.cfg, "idle_minutes", 10)) * 60 * 1000
        with self.lock:
            waiting = [dict(t) for t in self.tabs if t["state"] == "waiting"]
        # the disk is read outside the lock, so a reader of state() never waits on it
        settled = {t["ref"]: ret.tab_settled(self.app.root, t) for t in waiting}
        with self.lock:
            for t in self.tabs:
                held = self.asks.get(t["ref"])
                ask = held[1] if held and held[0][0] == t["state"] else None
                since = self.seen.get(t["ref"], {}).get("since_ms", now)
                t["idle"] = t["ref"] != self.control and m.is_idle(t, ask, since, settled.get(t["ref"]), now, after_ms)

    def _workspaces(self) -> list[dict] | None:
        run = self.app.run(self.app.workplace("workspaces", "--json"), WORKSPACES_TIMEOUT)
        if not run.ok:
            return None
        try:
            rows = json.loads(run.out)
        except ValueError:
            return None
        if not isinstance(rows, list):
            return None
        out = []
        for w in rows:
            if isinstance(w, dict) and isinstance(w.get("ref"), str):
                cwd = w.get("cwd")
                # the folder as the Bridges list resolves it, so a symlinked path still finds its Bridge;
                # the palette name of the colour, by its hex (a name the driver gives that does not match is not taken)
                out.append({**w, "cwd_real": os.path.realpath(cwd) if isinstance(cwd, str) and cwd else None,
                            "color_name": org.color_name(w.get("color"))})
        return out

    # ------------------------------------------------------------ schedule

    def schedule(self, delay_s: float) -> None:
        with self.cond:
            self.next_extra = min(self.next_extra, self.monotonic() + delay_s)
            self.cond.notify_all()

    def interval(self) -> float:
        """Seconds between two periodic polls: tabs_seconds for a shown page, HIDDEN_TABS_S for hidden ones only."""
        if self.app.client_count() > 0:
            return self.app.cfg.tabs_seconds
        if self.app.connected_count() > 0:
            return max(self.app.cfg.tabs_seconds, HIDDEN_TABS_S)
        return float("inf")

    def step(self) -> float:
        """Polls when one is due and returns 0, else returns how long the loop may wait (at most 1 s)."""
        with self.cond:
            now = self.monotonic()
            wake = min(self.next_extra, self.last_poll + self.interval())
            if wake > now:
                return min(wake - now, 1.0)
            self.next_extra = float("inf")
        try:
            self.poll()
        except Exception:
            import traceback
            self.app.log_error("tab poll failed:\n" + traceback.format_exc())
        return 0.0

    def loop(self) -> None:
        while True:
            with self.cond:
                if self.stop:
                    return
            wait = self.step()
            if wait > 0:
                with self.cond:
                    if not self.stop and self.next_extra > self.monotonic():
                        self.cond.wait(timeout=wait)

    def shutdown(self) -> None:
        with self.cond:
            self.stop = True
            self.cond.notify_all()
