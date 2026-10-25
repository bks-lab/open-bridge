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

The workflow runs of the last week, of every session (ended ones too), are bound to the open task they belong
to, for the task's file in the files view (`runs`): a run belongs to a task only where it names exactly one, never
by a guess. A mention is `task:<slug>`, `work/tasks/<slug>/` or `work/streams/<slug>/` in its name, summary,
arguments or script (an absolute path only under this Bridge's root), or a name that is the slug; two tasks named
make no binding. The session it ran in being linked to the task, and the folder it ran in ending in the slug,
only confirm a mention: alone they bind nothing, and a session linked to another task undoes it. A run belongs to
this Bridge only where the folder it ran in (from the session's own file) is the Bridge, a folder in it, one of
its git worktrees, or a folder that is no Bridge at all; a run of another Bridge on the machine, or of a session
whose folder is unknown, is never read (rules/multi-instance-isolation.md). Only what the page shows leaves the
server: never the script.
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
RUN_KEEP_MS = 7 * 24 * 3600 * 1000   # a workflow run older than a week is no longer the file's
RUNS_MAX = 40                        # the newest bound runs the page gets
RUN_SCAN_MS = 30_000                 # the runs are read again at most this often (and when the open tasks change)
ANSWER_MAX = 600


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


def _mention_re(slug: str, roots: tuple = ()) -> re.Pattern:
    """A mention of a slug: `task:<slug>`, or `work/tasks|streams/<slug>` as a relative path or under one of
    `roots` (this Bridge's root as written and as resolved); a path under any other folder names nothing"""
    tail = r"(?![A-Za-z0-9_-])"
    under = "".join(f"|{re.escape(r.rstrip('/'))}/" for r in roots if r)
    return re.compile(rf"(?<![A-Za-z0-9_-])task:{re.escape(slug)}{tail}"
                      rf"|(?:(?<![A-Za-z0-9_./~-]){under})work/(?:tasks|streams)/{re.escape(slug)}{tail}")


def run_task(text: str, name: str, sid: str, slugs: set, links: dict, root: str | tuple = "",
             place: str = "") -> tuple[str | None, list]:
    """(task, signs) of a workflow run: the one open task it names, with the signs that agree ("named",
    "session", "place"); (None, []) when it names none or two, or its session is linked to another task.
    `place` is the name of the folder it ran in where that is not the Bridge's root."""
    roots = (root,) if isinstance(root, str) else tuple(root)
    named = [slug for slug in slugs if name == slug or (slug in text and _mention_re(slug, roots).search(text))]
    if len(named) != 1:
        return None, []
    slug, signs = named[0], ["named"]
    linked = (links.get(sid) or {}).get("task") if sid else None
    if isinstance(linked, str) and linked in slugs:
        if linked != slug:
            return None, []
        signs.append("session")
    if place and (place == slug or place.endswith("-" + slug)):
        signs.append("place")
    return slug, signs


def own_folders(root: Path) -> list[Path]:
    """This Bridge's root and every git worktree of its repository (read from the git folder, no git run)"""
    try:
        root = root.resolve()
    except OSError:
        return [root]
    out = [root]
    try:
        git = root / ".git"
        if git.is_file():
            m = re.match(r"gitdir:\s*(.+)", git.read_text(encoding="utf-8").strip())
            gitdir = (root / m.group(1).strip()).resolve() if m else None
            common_file = gitdir / "commondir" if gitdir else None
            common = ((gitdir / common_file.read_text(encoding="utf-8").strip()).resolve()
                      if common_file and common_file.is_file() else gitdir)
        else:
            common = git if git.is_dir() else None
        if common is not None:
            if common.name == ".git":
                out.append(common.parent)
            for entry in sorted((common / "worktrees").glob("*/gitdir")):
                out.append(Path(entry.read_text(encoding="utf-8").strip()).parent.resolve())
    except (OSError, ValueError):
        pass
    return list(dict.fromkeys(out))


def is_bridge(folder: Path) -> bool:
    """A folder that holds a Bridge of its own: its config, or a work/tasks folder"""
    return (folder / "bridge-config.yaml").is_file() or (folder / "work" / "tasks").is_dir()


CWD_RE = re.compile(r'"cwd"\s*:\s*"((?:[^"\\]|\\.)*)"')
CWD_LINES = 40


def session_cwd(transcript: Path) -> str | None:
    """The folder a session ran in, from the first lines of its own file (<project>/<session id>.jsonl)"""
    try:
        with transcript.open(encoding="utf-8", errors="replace") as fh:
            for _ in range(CWD_LINES):
                line = fh.readline(1 << 20)
                if not line:
                    break
                m = CWD_RE.search(line)
                if m:
                    try:
                        cwd = json.loads(f'"{m.group(1)}"')
                    except ValueError:
                        return None
                    return cwd if isinstance(cwd, str) and cwd.startswith("/") else None
    except OSError:
        return None
    return None


def _answer(result: Any) -> str | None:
    """What a run left as its result, as a few lines: a text, else its `final`, else its first text"""
    if isinstance(result, dict):
        result = result.get("final") if isinstance(result.get("final"), str) else next(
            (v for v in result.values() if isinstance(v, str)), None)
    elif isinstance(result, list):
        result = next((v for v in result if isinstance(v, str)), None)
    return result.strip()[:ANSWER_MAX] if isinstance(result, str) and result.strip() else None


def read_run(path: Path) -> dict | None:
    """One wf_*.json as the page knows it, with the text its task is found in (kept here, never sent)"""
    wf = _json(path)
    if not isinstance(wf, dict):
        return None
    args = wf.get("args")
    start = wf.get("startTime") if isinstance(wf.get("startTime"), (int, float)) else None
    took = wf.get("durationMs") if isinstance(wf.get("durationMs"), (int, float)) else None
    status = str(wf.get("status") or "").lower() or "unknown"
    name = _text(wf.get("workflowName"), 80) or path.stem
    return {"id": path.stem, "name": name, "status": status, "summary": _text(wf.get("summary"), 300),
            "agents": wf.get("agentCount") if isinstance(wf.get("agentCount"), int) else None,
            "since_ms": int(start) if start is not None else None,
            "ended_ms": int(start + took) if start is not None and took is not None and status not in WF_ACTIVE else None,
            "answer": _answer(wf.get("result")),
            "_text": " ".join(x if isinstance(x, str) else json.dumps(x) for x in
                              (wf.get("workflowName"), wf.get("summary"), args, wf.get("script")) if x)}


class Sessions:
    """Scans on demand (after each tab poll); keeps the surface of a pid, which never changes."""

    def __init__(self, app: Any, base: Path | None = None, alive: Callable[[int], bool] = pid_alive):
        self.app = app
        self.base = base
        self.alive = alive
        self.lock = threading.Lock()
        self.surfaces: dict[int, tuple[str | None, str | None]] = {}
        self.last: list[dict] = []
        self.run_cache: dict[str, tuple[tuple, dict | None]] = {}   # path -> ((mtime, size), read_run)
        self.runs: list[dict] = []
        self.runs_key: tuple = ()
        self.runs_at = None
        self.cwd_cache: dict[str, str | None] = {}   # <project>/<session id> -> the folder it ran in

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

    def run_place(self, project: Path, sid: str, home: Path | None, own: list[Path]) -> tuple[bool, str]:
        """(this Bridge's, folder name) of the session a run ran in: its folder from the session's own file,
        the Bridge's root where the project is the root's and that file is gone; never another Bridge's"""
        key = f"{project.name}/{sid}"
        if key not in self.cwd_cache:
            self.cwd_cache[key] = session_cwd(project / f"{sid}.jsonl")
        cwd = self.cwd_cache[key]
        if cwd is None:
            return (home is not None and project.name == project_slug(str(home))), ""
        try:
            folder = Path(cwd).resolve()
        except OSError:
            return False, ""
        for mine in own:
            if folder == mine or folder.is_relative_to(mine):
                return True, ("" if folder == own[0] else folder.name)
        if any(is_bridge(p) for p in (folder, *folder.parents)):
            return False, ""
        return True, folder.name

    def scan_runs(self, now_ms: float, slugs: set, links: dict, home: Path | None = None) -> list[dict]:
        """The workflow runs of the last week that belong to one of these open tasks, newest first"""
        base = self.base or claude_dir()
        own = own_folders(Path(home)) if home else []
        roots = tuple(dict.fromkeys(str(x) for x in ((home, own[0]) if home else ())))
        found, seen = [], set()
        try:
            files = list((base / "projects").glob("*/*/workflows/wf_*.json"))
        except OSError:
            files = []
        for path in files:
            try:
                st = path.stat()
            except OSError:
                continue
            if now_ms - st.st_mtime * 1000 > RUN_KEEP_MS:
                continue
            key, stamp = str(path), (st.st_mtime_ns, st.st_size)
            seen.add(key)
            cached = self.run_cache.get(key)
            run = cached[1] if cached and cached[0] == stamp else read_run(path)
            self.run_cache[key] = (stamp, run)
            if run is None:
                continue
            sid = path.parent.parent.name
            mine, place = self.run_place(path.parent.parent.parent, sid, home, own)
            if not mine:
                continue
            task, how = run_task(run["_text"], run["name"], sid, slugs, links, roots, place)
            if task:
                found.append({**{k: v for k, v in run.items() if k != "_text"}, "task": task, "how": how,
                              "sid": sid, "at_ms": int(st.st_mtime * 1000)})
        self.run_cache = {k: v for k, v in self.run_cache.items() if k in seen}
        sessions_seen = {f"{Path(k).parent.parent.parent.name}/{Path(k).parent.parent.name}" for k in seen}
        self.cwd_cache = {k: v for k, v in self.cwd_cache.items() if k in sessions_seen}
        found.sort(key=lambda r: -r["at_ms"])
        return found[:RUNS_MAX]

    def refresh_runs(self, now_ms: float, slugs: set, links: dict, home: Path | None = None) -> bool:
        """Read the runs again when a while has passed or the open tasks or links changed; True on a change"""
        key = (tuple(sorted(slugs)), json.dumps({k: (v or {}).get("task") for k, v in links.items()}, sort_keys=True))
        if self.runs_at is not None and key == self.runs_key and now_ms - self.runs_at < RUN_SCAN_MS:
            return False
        new = self.scan_runs(now_ms, slugs, links, home)
        with self.lock:
            changed = new != self.runs
            self.runs, self.runs_key, self.runs_at = new, key, now_ms
        return changed

    def run_state(self) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.runs]

    def refresh(self, tabs: list[dict], now_ms: float, control_ref: str | None,
                relay_sessions: frozenset = frozenset()) -> bool:
        """Scan again; True when anything the page shows changed."""
        new = self.scan(tabs, now_ms, control_ref, relay_sessions)
        with self.lock:
            changed = json.dumps(new, sort_keys=True) != json.dumps(self.last, sort_keys=True)
            self.last = new
        return changed
