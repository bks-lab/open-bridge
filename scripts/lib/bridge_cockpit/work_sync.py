# SPDX-License-Identifier: MIT
"""A served cockpit's writes reach the upstream: which paths a person's action changed, kept until they are committed.

The cockpit compares the work tree before and after a person's action, so a file somebody else left open on this
clone is never swept along. The paths go into a queue file first and are worked off one call at a time by
scripts/work-sync.py, so a server that stops between the two loses nothing. Exit 75 means the commit is safe locally
and the puller's next run pushes it. Anything else stays queued and is tried again.
"""
from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path
from typing import Callable

RETRY_S = 60
WATCHED = "work"


class WorkSync:
    def __init__(self, root: Path, state_dir: Path, run: Callable[[list[str], str], int],
                 note: Callable[[str], None] = lambda _: None):
        self.root = Path(root)
        self.queue = Path(state_dir) / "work-sync.jsonl"
        self.run = run
        self.note = note
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.stopped = threading.Event()

    def snapshot(self) -> dict[str, int]:
        """Every changed file under work/, by its modification time: a second write to an open file counts too."""
        done = subprocess.run(["git", "-C", str(self.root), "status", "--porcelain=v1", "-z", "--no-renames", "-uall",
                               "--", WATCHED], capture_output=True, text=True, timeout=60)
        out: dict[str, int] = {}
        for entry in done.stdout.split("\0"):
            if len(entry) > 3:
                path = entry[3:]
                try:
                    out[path] = (self.root / path).stat().st_mtime_ns
                except OSError:
                    out[path] = 0
        return out

    def after(self, before: dict[str, int], person: str) -> list[str]:
        now = self.snapshot()
        paths = sorted(p for p, stamp in now.items() if before.get(p) != stamp)
        paths = [p for p in paths if p.startswith(("work/tasks/", "work/done/", "work/inbox/")) or p == "work/log.md"]
        if paths:
            with self.lock:
                self.queue.parent.mkdir(parents=True, exist_ok=True)
                with open(self.queue, "a", encoding="utf-8") as handle:
                    handle.write(json.dumps({"person": person, "paths": paths}) + "\n")
            self.wake.set()
        return paths

    def pending(self) -> list[dict]:
        with self.lock:
            try:
                lines = self.queue.read_text(encoding="utf-8").splitlines()
            except OSError:
                return []
        return [json.loads(x) for x in lines if x.strip()]

    def _drop_first(self) -> None:
        with self.lock:
            lines = self.queue.read_text(encoding="utf-8").splitlines(keepends=True)
            temp = self.queue.with_suffix(".tmp")
            temp.write_text("".join(lines[1:]), encoding="utf-8")
            temp.replace(self.queue)

    def drain(self) -> bool:
        """Work the queue off in order. False when an entry stays for the next try."""
        while True:
            entries = self.pending()
            if not entries:
                return True
            code = self.run(entries[0]["paths"], entries[0]["person"])
            if code not in (0, 75):
                self.note(f"work sync: exit {code}, {len(entries)} waiting")
                return False
            self._drop_first()

    def loop(self) -> None:
        while not self.stopped.is_set():
            self.wake.clear()
            ok = self.drain()
            self.wake.wait(None if ok else RETRY_S)

    def stop(self) -> None:
        self.stopped.set()
        self.wake.set()
