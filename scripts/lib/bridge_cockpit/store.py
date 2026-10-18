# SPDX-License-Identifier: MIT
"""Persistent web state under state_dir: state.json (hidden rows, team runs) and view.json.

The mod keeps its own hidden rows and team runs in its `$.store`; the web keeps
these separately (documented, not synced: contract section 13). Every write is
atomic (tmp file + os.replace). Also the small file helpers the other modules share:
atomic JSON writes, log files rotated at 1 MB, and the chat archive (chats/<name>-YYYY-MM.jsonl), where a
conversation goes when it leaves its list, so no chat is ever dropped.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .model import SETTLE_OUTCOMES, iso_date

LOG_MAX_BYTES = 1024 * 1024
SESSION_LINKS_MAX = 300      # the newest links of sessions to tasks; an older one has long been resumed or forgotten


def atomic_write_text(path: Path, text: str, mode: int | None = None) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        if mode is not None:
            os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_json(path: Path, data: Any, mode: int | None = None) -> None:
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, separators=(",", ":")), mode)


def read_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def archive_conv(state_dir: Path, name: str, conv: dict, why: str, now_ms: int) -> None:
    """Append one conversation, whole, to the archive file of the month it leaves its list (local time);
    raises OSError when it cannot be kept, and the caller then keeps the conversation in its list. At
    least once: should the list file fail to save afterwards, the conversation comes back after a
    restart and a second removal archives it again."""
    folder = Path(state_dir) / "chats"
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = folder / f"{name}-{time.strftime('%Y-%m', time.localtime(now_ms / 1000))}.jsonl"
    line = json.dumps({"at_ms": now_ms, "why": why, "conv": conv}, ensure_ascii=False, separators=(",", ":"))
    with _log_lock:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")


_log_lock = threading.Lock()


def append_log(path: Path, line: str, max_bytes: int = LOG_MAX_BYTES) -> None:
    """Append one line; at max_bytes the file becomes <name>.1 (one backup)."""
    path = Path(path)
    with _log_lock:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and path.stat().st_size >= max_bytes:
                os.replace(path, path.with_name(path.name + ".1"))
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(line.rstrip("\n") + "\n")
        except OSError:
            pass


class WebStore:
    """state.json: {"v": 1, "hidden": {row_key: "YYYY-MM-DD"}, "dismissed": {row_key: {outcome, at, title}},
    "team_runs": {slug: {team, roles, at}}}. A dismissed row (done or not doing, from a source the web
    cannot close, like a GitHub issue) stays out of the briefing until "show again"; no date brings it back."""

    def __init__(self, state_dir: Path, clock: Callable[[], float]):
        self.state_dir = Path(state_dir)
        self.path = self.state_dir / "state.json"
        self.view_path = self.state_dir / "view.json"
        self.clock = clock
        self.lock = threading.Lock()
        data = read_json(self.path)
        data = data if isinstance(data, dict) else {}
        hidden = data.get("hidden") if isinstance(data.get("hidden"), dict) else {}
        runs = data.get("team_runs") if isinstance(data.get("team_runs"), dict) else {}
        self._hidden = {k: v for k, v in hidden.items() if isinstance(k, str) and isinstance(v, str)}
        gone = data.get("dismissed") if isinstance(data.get("dismissed"), dict) else {}
        self._dismissed = {k: v for k, v in gone.items()
                           if isinstance(k, str) and isinstance(v, dict) and v.get("outcome") in SETTLE_OUTCOMES}
        tiles = data.get("home_tiles")
        # the start page's own choice of tiles and shelves; None until one was made
        self._home = [x for x in tiles if isinstance(x, str)] if isinstance(tiles, list) else None
        seen, pins = data.get("home_seen"), data.get("pins")
        # what the chooser offered when the choice was made: a tile it did not offer yet gets its default
        self._seen = [x for x in seen if isinstance(x, str)] if isinstance(seen, list) else None
        self._pins = [x for x in pins if isinstance(x, str)] if isinstance(pins, list) else []
        self._runs = {k: v for k, v in runs.items()
                      if isinstance(v, dict) and isinstance(v.get("team"), str) and isinstance(v.get("roles"), list)}
        links = data.get("session_links") if isinstance(data.get("session_links"), dict) else {}
        # which task a Claude session works on: {session id: {task, name, cwd, at_ms, how}}, how is "tab" (the
        # session runs in a task tab, BRIDGE_TAB_SLUG) or "hand" (linked on the Sessions page). Kept after the
        # session ends, so the task can go on in it (claude --resume, only on this machine).
        self._links = {k: v for k, v in links.items()
                       if isinstance(k, str) and isinstance(v, dict) and isinstance(v.get("task"), str)}
        self.prune()

    def today(self) -> str:
        return iso_date(self.clock())

    def _save(self) -> None:
        atomic_write_json(self.path, {"v": 1, "hidden": self._hidden, "dismissed": self._dismissed,
                                      "team_runs": self._runs, "home_tiles": self._home, "home_seen": self._seen,
                                      "pins": self._pins, "session_links": self._links})

    def prune(self) -> bool:
        """Drop hidden entries whose date has come (hidden while date > today)."""
        today = self.today()
        with self.lock:
            gone = [k for k, v in self._hidden.items() if v <= today]
            for k in gone:
                del self._hidden[k]
            if gone:
                self._save()
            return bool(gone)

    def home_tiles(self) -> list | None:
        with self.lock:
            return None if self._home is None else list(self._home)

    def set_home_tiles(self, ids: list, seen: list | None = None) -> None:
        with self.lock:
            self._home = list(ids)
            if seen is not None:
                self._seen = list(seen)
            self._save()

    def home(self) -> dict:
        with self.lock:
            return {"tiles": None if self._home is None else list(self._home),
                    "seen": None if self._seen is None else list(self._seen), "pins": list(self._pins)}

    def pin(self, key: str, on: bool) -> None:
        """A row pinned to the start page, or taken off it; the order is the order of pinning"""
        with self.lock:
            if on and key not in self._pins:
                self._pins.append(key)
            elif not on and key in self._pins:
                self._pins.remove(key)
            else:
                return
            self._save()

    def hidden(self) -> dict:
        with self.lock:
            return dict(self._hidden)

    def hide(self, key: str, until: str) -> None:
        with self.lock:
            self._hidden[key] = until
            self._save()

    def unhide(self, key: str) -> bool:
        with self.lock:
            if key not in self._hidden and key not in self._dismissed:
                return False
            self._hidden.pop(key, None)
            self._dismissed.pop(key, None)
            self._save()
            return True

    def dismissed(self) -> dict:
        with self.lock:
            return json.loads(json.dumps(self._dismissed))

    def dismiss(self, key: str, outcome: str, title: str) -> None:
        with self.lock:
            self._dismissed[key] = {"outcome": outcome, "at": iso_date(self.clock()), "title": title[:200]}
            self._hidden.pop(key, None)
            self._save()

    def team_runs(self) -> dict:
        with self.lock:
            return json.loads(json.dumps(self._runs))

    def set_team_run(self, slug: str, run: dict | None) -> None:
        with self.lock:
            if run is None:
                self._runs.pop(slug, None)
            else:
                self._runs[slug] = run
            self._save()

    def session_links(self) -> dict:
        with self.lock:
            return json.loads(json.dumps(self._links))

    def link_session(self, sid: str, task: str, name: str, cwd: str, how: str) -> bool:
        """True when it changed. A link by hand is never replaced by one a tab suggests."""
        with self.lock:
            old = self._links.get(sid)
            if old and (old.get("how") == "hand" and how == "tab" or (old.get("task") == task and old.get("how") == how)):
                if old.get("name") != name and name:
                    old["name"] = name[:120]
                    self._save()
                return False
            self._links[sid] = {"task": task, "name": name[:120], "cwd": cwd[:400], "at_ms": int(self.clock()),
                                "how": how}
            for drop in sorted(self._links, key=lambda k: self._links[k].get("at_ms", 0))[:-SESSION_LINKS_MAX]:
                del self._links[drop]
            self._save()
            return True

    def unlink_session(self, sid: str) -> bool:
        with self.lock:
            if self._links.pop(sid, None) is None:
                return False
            self._save()
            return True

    # view.json: stale while revalidate
    def save_view(self, view: dict, language: str | None = None) -> None:
        try:
            atomic_write_json(self.view_path, {"v": 1, "view": view, "language": language})
        except OSError:
            pass

    def load_view(self, language: str | None = None) -> dict | None:
        """Today's last view, unless it was written in another language (the words in it are the briefing's)."""
        data = read_json(self.view_path)
        if isinstance(data, dict) and language and data.get("language") not in (None, language):
            return None
        view = data.get("view") if isinstance(data, dict) else None
        if not isinstance(view, dict) or not isinstance(view.get("collected_ms"), (int, float)):
            return None
        if not isinstance(view.get("buckets"), list):
            return None
        return view if iso_date(view["collected_ms"]) == self.today() else None
