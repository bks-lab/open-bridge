# SPDX-License-Identifier: MIT
"""Watcher of the cockpit: stat-only scans of the work tree and the relay directory.

Every 2 s the mtimes of work/inbox (the dir, each item.yaml, each events dir),
work/tasks and work/streams (the dirs and each STATUS.md), work/log.md and the folder
work/cockpit/settled (settled.py) are compared with the previous scan; a change schedules a
`delta` pass, debounced 3 s and held for as long as the collector asks (after a pass at least as long as that pass took). At local
midnight one `full` pass runs (deferred inbox items reopen without an event). The same
thread scans the relay every 1 s, cleans it every 10 min and writes the server stats
into server.json every 10 s. Nothing here reads file contents of the work tree.
"""
from __future__ import annotations

import os
import threading
import time
import traceback
from pathlib import Path
from typing import Any

from .model import iso_date

WORK_SCAN_S = 2.0
DEBOUNCE_S = 3.0
RELAY_SCAN_S = 1.0
RELAY_CLEANUP_S = 600.0
STATS_S = 10.0
ERROR_EVERY_S = 60.0         # a step that keeps failing is logged once a minute, not twice a second


def _mtime(path: str) -> int | None:
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return None


def _put(out: dict[str, int], path: str) -> None:
    value = _mtime(path)
    if value is not None:
        out[path] = value


def task_snapshot(root: Path) -> dict[str, int]:
    """path -> mtime_ns of work/tasks and work/streams (the dirs and each STATUS.md): what the task list reads."""
    root = Path(root)
    out: dict[str, int] = {}
    for name in ("tasks", "streams"):
        base = root / "work" / name
        _put(out, str(base))
        try:
            for entry in os.scandir(base):
                if entry.is_dir(follow_symlinks=False):
                    _put(out, os.path.join(entry.path, "STATUS.md"))
        except OSError:
            pass
    return out


def snapshot(root: Path) -> dict[str, int]:
    """path -> mtime_ns of everything the watcher compares."""
    root = Path(root)
    out: dict[str, int] = {}

    def put(path: str) -> None:
        _put(out, path)

    inbox = root / "work" / "inbox"
    put(str(inbox))
    try:
        for entry in os.scandir(inbox):
            if entry.is_dir(follow_symlinks=False):
                put(os.path.join(entry.path, "item.yaml"))
                put(os.path.join(entry.path, "events"))
    except OSError:
        pass
    out.update(task_snapshot(root))
    put(str(root / "work" / "log.md"))
    put(str(root / "work" / "cockpit" / "settled"))     # a pull that brought a row settled on another machine
    return out


class Watcher:
    def __init__(self, app: Any):
        self.app = app
        self.previous = snapshot(app.root)
        self.due: float | None = None
        self.day = iso_date(app.clock())
        self.stop = threading.Event()
        self.last = {"relay": 0.0, "work": 0.0, "stats": 0.0, "cleanup": None}
        self.logged: dict[str, float] = {}

    def check(self, now_s: float) -> bool:
        """One scan; True when a delta pass was requested now (after the debounce)."""
        current = snapshot(self.app.root)
        if current != self.previous:
            self.previous = current
            self.due = now_s + DEBOUNCE_S
        if self.due is not None and now_s >= self.due:
            # a pass in flight, or one that just ended, holds the delta (#386): passes never follow each other
            # faster than they take
            hold = getattr(self.app.collector, "delta_hold_ms", None)
            wait_ms = hold() if hold else 0
            if wait_ms > 0:
                self.due = now_s + wait_ms / 1000
                return False
            self.due = None
            self.app.collector.request("delta")
            return True
        return False

    def midnight(self) -> bool:
        today = iso_date(self.app.clock())
        if today == self.day:
            return False
        self.day = today
        self.app.store.prune()
        self.app.collector.request("full")
        return True

    def _due(self, name: str, now: float, every: float) -> bool:
        last = self.last[name]
        if last is None:
            self.last[name] = now           # the cleanup waits a whole period after the start
            return False
        if now - last < every:
            return False
        self.last[name] = now
        return True

    def _safe(self, name: str, fn: Any, now: float) -> None:
        """One step on its own: a step that raises is logged (once a minute per step) and the next runs"""
        try:
            fn()
        except Exception:  # noqa: BLE001 - the loop must outlive any one step
            if now - self.logged.get(name, -ERROR_EVERY_S) >= ERROR_EVERY_S:
                self.logged[name] = now
                self.app.log_error(f"watch step {name} failed:\n" + traceback.format_exc())

    def step(self, now: float) -> None:
        """One turn of the loop at monotonic time `now`: each step that is due, each in its own try"""
        if self._due("relay", now, RELAY_SCAN_S):
            self._safe("relay_scan", self.app.relay_scan, now)
        if self._due("work", now, WORK_SCAN_S):
            self._safe("check", lambda: self.check(now), now)
            self._safe("midnight", self.midnight, now)
            self._safe("tick", lambda: self.app.collector.tick(self.app.client_count()), now)
        if self._due("cleanup", now, RELAY_CLEANUP_S):
            self._safe("relay_cleanup", self.app.relay.cleanup, now)
        if self._due("stats", now, STATS_S):
            self._safe("server_json", self.app.write_server_json, now)

    def loop(self) -> None:
        while not self.stop.wait(0.5):
            self.step(time.monotonic())

    def shutdown(self) -> None:
        self.stop.set()
