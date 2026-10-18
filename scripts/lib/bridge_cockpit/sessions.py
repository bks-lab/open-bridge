# SPDX-License-Identifier: MIT
"""Every running Claude Code session on this machine, with its subagents and workflows, for the Sessions page.

Claude Code keeps one file per running session in ~/.claude/sessions/<pid>.json (session id, cwd, name,
busy or idle and since when). A session's subagents write their transcripts to
~/.claude/projects/<cwd as a slug>/<session id>/subagents/agent-<id>.jsonl beside a .meta.json (type,
description); a transcript that grew in the last two minutes counts as running. Workflows leave one
workflows/wf_*.json per run with its status and agent count. The cmux tab of a session comes from the
CMUX_SURFACE_ID in the process environment, the tmux tab from TMUX_PANE (%3, the tmux driver's id and
ref of a tab), read once per pid with `ps` and matched to the tab list, so the page can jump to it. Only
that one variable is kept; the rest of the environment is dropped.
Everything here only reads; a file that does not parse is skipped.
"""
from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any, Callable

RUNNING_WINDOW_MS = 120_000       # a subagent transcript that grew this recently is still working
RECENT_DONE_MS = 3_600_000        # finished subagents of the last hour are counted, not listed
AGENT_CAP = 12
SURFACE_RE = re.compile(r"(?:^|\s)CMUX_SURFACE_ID=([0-9A-Fa-f-]{36})(?:\s|$)")
PANE_RE = re.compile(r"(?:^|\s)TMUX_PANE=(%\d+)(?:\s|$)")    # a tab of the tmux driver
# the task a tab was started for (scripts/workplace.py TAB_ENV); an inbox tab carries inbox-<words>
TAB_SLUG_RE = re.compile(r"(?:^|\s)BRIDGE_TAB_SLUG=([A-Za-z0-9][A-Za-z0-9._-]*)(?:\s|$)")
PS = "/bin/ps"
WF_ACTIVE = frozenset({"running", "pending", "started", "in_progress", "paused"})


def claude_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def project_slug(cwd: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", cwd)


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _mtime_ms(path: Path) -> int:
    try:
        return int(path.stat().st_mtime * 1000)
    except OSError:
        return 0


def _text(value: Any, cap: int = 120) -> str | None:
    return " ".join(value.split())[:cap] if isinstance(value, str) and value.strip() else None


def subagents(folder: Path, now_ms: float, started_ms: int) -> dict:
    running, done = [], 0
    try:
        files = sorted(folder.glob("agent-*.jsonl"))
    except OSError:
        files = []
    for log in files:
        last = _mtime_ms(log)
        if last < started_ms:
            continue
        meta = _json(log.with_name(log.name[: -len(".jsonl")] + ".meta.json"))
        meta = meta if isinstance(meta, dict) else {}
        if now_ms - last <= RUNNING_WINDOW_MS:
            running.append({"id": log.stem[len("agent-"):][:12], "type": _text(meta.get("agentType"), 60) or "agent",
                            "description": _text(meta.get("description")),
                            "since_ms": _mtime_ms(log.with_name(log.name[: -len(".jsonl")] + ".meta.json")) or last,
                            "background": meta.get("requestShape") == "background"})
        elif now_ms - last <= RECENT_DONE_MS:
            done += 1
    running.sort(key=lambda a: a["since_ms"])
    return {"running": running[:AGENT_CAP], "running_count": len(running), "done_recent": done}


def workflows(folder: Path) -> list[dict]:
    out = []
    try:
        files = sorted(folder.glob("wf_*.json"))
    except OSError:
        files = []
    for path in files:
        wf = _json(path)
        if not isinstance(wf, dict) or str(wf.get("status") or "").lower() not in WF_ACTIVE:
            continue
        out.append({"name": _text(wf.get("workflowName"), 60) or path.stem, "status": str(wf.get("status")),
                    "agents": wf.get("agentCount") if isinstance(wf.get("agentCount"), int) else None,
                    "since_ms": wf.get("startTime") if isinstance(wf.get("startTime"), (int, float)) else None})
    return out


class Sessions:
    """Scans on demand (after each tab poll); keeps the surface of a pid, which never changes."""

    def __init__(self, app: Any, base: Path | None = None, alive: Callable[[int], bool] = pid_alive):
        self.app = app
        self.base = base
        self.alive = alive
        self.lock = threading.Lock()
        self.surfaces: dict[int, tuple[str | None, str | None]] = {}
        self.last: list[dict] = []

    def env_of(self, pid: int) -> tuple[str | None, str | None]:
        """(terminal tab: cmux surface or tmux pane, task slug of the tab) from the process environment;
        read once per pid"""
        with self.lock:
            if pid in self.surfaces:
                return self.surfaces[pid]
        run = self.app.run([PS, "eww", "-o", "command=", "-p", str(pid)], 5)
        found = (SURFACE_RE.search(run.out or "") or PANE_RE.search(run.out or "")) if run.ok else None
        slug = TAB_SLUG_RE.search(run.out or "") if run.ok else None
        env = (found.group(1).upper() if found else None, slug.group(1) if slug else None)
        with self.lock:
            self.surfaces[pid] = env
        return env

    def surface_of(self, pid: int) -> str | None:
        return self.env_of(pid)[0]

    def scan(self, tabs: list[dict], now_ms: float, control_ref: str | None = None,
             relay_sessions: frozenset = frozenset()) -> list[dict]:
        base = self.base or claude_dir()
        # a tab by its id, or by its ref where the driver gives no id (the same rule as the relay's)
        by_surface = {str(t.get("id") or t.get("ref") or "").upper(): t for t in tabs if t.get("id") or t.get("ref")}
        out = []
        try:
            files = sorted((base / "sessions").glob("*.json"))
        except OSError:
            files = []
        alive_pids = set()
        for path in files:
            data = _json(path)
            if not isinstance(data, dict):
                continue
            pid, sid, cwd = data.get("pid"), data.get("sessionId"), data.get("cwd")
            if not isinstance(pid, int) or not isinstance(sid, str) or not re.fullmatch(r"[0-9a-f-]{36}", sid):
                continue
            if not isinstance(cwd, str) or not self.alive(pid):
                continue
            alive_pids.add(pid)
            started = int(data.get("startedAt") or 0) if isinstance(data.get("startedAt"), (int, float)) else 0
            folder = base / "projects" / project_slug(cwd) / sid
            surface, tab_slug = self.env_of(pid)
            tab = by_surface.get(surface or "")
            status = data.get("status") if data.get("status") in ("busy", "idle", "shell") else "unknown"
            out.append({
                "id": sid[:8], "sid": sid, "tab_slug": tab_slug, "pid": pid, "name": _text(data.get("name"), 80) or sid[:8],
                "project": Path(cwd).name, "cwd": cwd, "here": Path(cwd) == self.app.root,
                "status": status, "since_ms": int(data.get("statusUpdatedAt") or data.get("updatedAt") or started or 0),
                "started_ms": started, "kind": _text(data.get("kind"), 20), "version": _text(data.get("version"), 20),
                "remote": bool(data.get("bridgeSessionId")), "relay": sid in relay_sessions,
                "tab": {"ref": tab["ref"], "ws_ref": tab.get("ws_ref") or None, "name": tab["name"],
                        "workspace": tab["workspace"], "state": tab["state"],
                        "is_control": tab["ref"] == control_ref} if tab else None,
                "agents": subagents(folder / "subagents", now_ms, started),
                "workflows": workflows(folder / "workflows"),
            })
        with self.lock:
            self.surfaces = {p: s for p, s in self.surfaces.items() if p in alive_pids}
        # this Bridge first, then the busy ones, then by when they started
        out.sort(key=lambda s: (not s["here"], s["project"], s["status"] != "busy", s["started_ms"]))
        return out

    def state(self) -> list[dict]:
        with self.lock:
            return list(self.last)

    def refresh(self, tabs: list[dict], now_ms: float, control_ref: str | None,
                relay_sessions: frozenset = frozenset()) -> bool:
        """Scan again; True when anything the page shows changed."""
        new = self.scan(tabs, now_ms, control_ref, relay_sessions)
        with self.lock:
            changed = json.dumps(new, sort_keys=True) != json.dumps(self.last, sort_keys=True)
            self.last = new
        return changed
