# SPDX-License-Identifier: MIT
"""Watcher of the cockpit: stat-only scans of the work tree and the relay directory.

Every 2 s the mtimes of work/inbox (the dir, each item.yaml, each events dir),
work/tasks and work/streams (the dirs and each STATUS.md) and work/log.md are compared
with the previous scan; a change schedules a `delta` pass, debounced 3 s and held for as
long as the collector asks (after a pass at least as long as that pass took). At local
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
    return out


class Watcher:
    def __init__(self, app: Any):
        self.app = app
        self.previous = snapshot(app.root)
        self.due: float | None = None
        self.day = iso_date(app.clock())
        self.stop = threading.Event()

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

    def loop(self) -> None:
        last_work = last_relay = last_stats = 0.0
        last_cleanup = time.monotonic()
        while not self.stop.wait(0.5):
            now = time.monotonic()
            try:
                if now - last_relay >= RELAY_SCAN_S:
                    last_relay = now
                    self.app.relay_scan()
                if now - last_work >= WORK_SCAN_S:
                    last_work = now
                    self.check(now)
                    self.midnight()
                    self.app.collector.tick(self.app.client_count())
                if now - last_cleanup >= RELAY_CLEANUP_S:
                    last_cleanup = now
                    self.app.relay.cleanup()
                if now - last_stats >= STATS_S:
                    last_stats = now
                    self.app.write_server_json()
            except Exception:
                self.app.log_error("watch loop failed:\n" + traceback.format_exc())

    def shutdown(self) -> None:
        self.stop.set()
