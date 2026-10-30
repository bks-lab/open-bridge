#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""tmux as a workplace driver for scripts/workplace.py.

The plan (which task, which workspace, new or resumed) belongs to CORE
(scripts/workplace.py, docs/workplace.md). This script is only what tmux can do,
in whatever terminal app runs it (iTerm, Terminal, Ghostty, VS Code). It speaks
the CORE JSON protocol: one request on stdin, one answer on stdout.

    {"verb": "tabs"}       -> {"tabs": [{"name", "workspace", "ref", "ws_ref", "state", "last", "id", "is_self"}]}
    {"verb": "sessions"}   -> {"sessions": {"<window name>": "<agent session id>"}}
    {"verb": "open", "plan": {...}, "only": [...] | null, "resume": bool, "here": ref | null}
    {"verb": "launch", "tabs": [{"label", "slug", "command", "workspace", "aliases"}],
     "target": "tab" | "workspace" | "area", "here": ref | null}
    {"verb": "send", "tab": ref, "text": "..."}
    {"verb": "rename", "tab": ref, "title": "..."}
    {"verb": "rename_workspace", "workspace": ws_ref, "title": "..."}
    {"verb": "move_tab", "tab": ref, "workspace": ws_ref}   (no index: tmux numbers windows itself)
    {"verb": "control", "control": {...}, "command": "...", "root": "..."}
    {"verb": "caps"} | {"verb": "focus", "tab": ref} | {"verb": "key", "tab": ref, "key": k}
    {"verb": "keys", "tab": ref, "keys": [{"text": t} | {"key": k} | {"paste": t}]}
    {"verb": "screen", "tab": ref, "lines": n} | {"verb": "close", "tab": ref}

Mapping: a tmux SESSION is a workspace, a WINDOW is a tab (its name is the tab
name), and a tab's ref is the pane id of the window's active pane (`%3`), which
stays stable while the window lives and moves with it between sessions. A workspace's
ref (`ws_ref`) is the session id (`$2`), which stays when the session is renamed.

Wire it in bridge-config.yaml:

    workplace:
      driver: {command: ["python3", "${root}/skills/tmux/scripts/tmux_driver.py"]}

BRIDGE_TMUX_SOCKET names a private server (`tmux -L <name>`), so tests never
touch the person's own tmux. BRIDGE_TMUX_BIN overrides the binary.

Rules, the same as the cmux reference driver: it never closes a tab or a
workspace on its own (only `close`, which a person asked for, and even that never
removes the last pane of the server), never moves the last window out of a
session (tmux would destroy the emptied session), a tab already open is reused,
and a step tmux refuses is an ERROR line, never a success line.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
VERBS = ["tabs", "sessions", "open", "launch", "send", "rename", "control",
         "caps", "focus", "key", "keys", "screen", "close", "rename_workspace", "move_tab"]
SHELLS = {"zsh", "bash", "fish", "sh", "dash", "ksh", "tcsh", "csh", "nu", "-zsh", "-bash", "-fish", "-sh", "login"}
KEEP_SHELL = '; exec "${SHELL:-/bin/sh}" -l'
KEYS = {"enter": ("Enter", False), "escape": ("Escape", False),
        **{k: (k, True) for k in ("y", "n", *map(str, range(1, 10)))}}
# the keys of a live terminal, under tmux's names (workplace.py TERM_KEYS)
TERM_KEYS = {"enter": "Enter", "escape": "Escape", "tab": "Tab", "shift+tab": "BTab", "backspace": "BSpace", "delete": "DC",
             "up": "Up", "down": "Down", "left": "Left", "right": "Right", "home": "Home", "end": "End",
             "pageup": "PPage", "pagedown": "NPage", **{f"ctrl+{c}": f"C-{c}" for c in "abcdefghijklmnopqrstuvwxyz"}}
REF_RE = re.compile(r"%\d+")
WS_REF_RE = re.compile(r"\$\d+")
SEP = "\x1f"
SEP_ESCAPED = "\\037"     # how tmux 3.4 prints SEP in -F output; newer tmux passes the byte
SEND_CHUNK = 2000          # tmux carries a command in one IPC message (16 KB); long text goes in parts
INLINE_MAX = 1000          # a longer launch command goes into a private launcher file
LAUNCHER_DAYS = 7
SCREEN_LINES = 40
SCREEN_MAX_LINES = 5000    # a shell tab's whole scrollback, for the cockpit's tab history (workplace.py SCREEN_MAX_LINES)
STATE_WINDOW = 15          # only the bottom of the screen decides the state, never old scrollback


class DriverError(RuntimeError):
    """tmux gave no answer the driver can trust."""


class NoServer(DriverError):
    """No tmux server runs on this socket: there are no tabs, which is a true answer."""


# ---------------------------------------------------------------- pure heuristics

WORKING_RE = re.compile(r"esc to interrupt|ctrl\+c to interrupt", re.IGNORECASE)
NEEDS_YOU_RE = re.compile(
    r"Do you want to|Would you like to|Allow (this|once|always|command)|\(y/n\)|\[y/N\]|\[Y/n\]"
    r"|^\s*[❯›>▶]\s*\d+\.\s"                     # a numbered choice with the cursor on it
    r"|Press enter to confirm",
    re.IGNORECASE | re.MULTILINE)
AGENT_MARK_RE = re.compile(r"esc to interrupt|\? for shortcuts|bypass permissions|accept edits on"
                           r"|Claude Code|OpenAI Codex|context left", re.IGNORECASE)


def bottom(text: str, n: int = STATE_WINDOW) -> str:
    """The last n non-blank lines: what the agent shows now, not what scrolled past."""
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    return "\n".join(lines[-n:])


def last_line(text: str) -> str:
    for ln in reversed((text or "").splitlines()):
        if ln.strip():
            return ln.strip()[:200]
    return ""


def screen_shows_agent(text: str) -> bool:
    return bool(AGENT_MARK_RE.search(bottom(text)))


def classify_state(screen: str, agent: bool) -> str:
    """CORE state from the screen. A pane without an agent is `shell` whatever it shows:
    the launch rule reads `shell` as "holds no agent" and lets a new tab open."""
    if not agent:
        return "shell"
    tail = bottom(screen)
    if NEEDS_YOU_RE.search(tail):
        return "needs-you"
    if WORKING_RE.search(bottom(screen, 6)):
        return "working"
    return "waiting"


def is_shell(command: str) -> bool:
    return Path((command or "").strip()).name in SHELLS


def is_agent_args(args: str) -> bool:
    """A process that is a coding agent: Claude Code or Codex, native binary or node package."""
    try:
        argv = shlex.split(args or "")
    except ValueError:
        argv = (args or "").split()
    if not argv:
        return False
    head = Path(argv[0]).name
    if head in ("claude", "codex"):
        return True
    joined = " ".join(argv[:3])
    return bool(re.search(r"@anthropic-ai/claude-code|/claude(\.js)?(\s|$)|@openai/codex|/codex(\.js)?(\s|$)", joined))


SESSION_RE = re.compile(r"(?:--resume|-r|--session-id)[ =]([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                        r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})")


def session_id_in(args: str) -> str | None:
    m = SESSION_RE.search(args or "")
    return m.group(1) if m else None


def parse_ps(text: str) -> dict[int, tuple[int, str]]:
    """`ps -A -o pid=,ppid=,args=` -> {pid: (ppid, args)}."""
    procs = {}
    for ln in (text or "").splitlines():
        parts = ln.strip().split(None, 2)
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            procs[int(parts[0])] = (int(parts[1]), parts[2] if len(parts) > 2 else "")
    return procs


def descendants(pid: int, procs: dict[int, tuple[int, str]]) -> list[str]:
    """Args of pid and every process below it, the pane's shell first."""
    children: dict[int, list[int]] = {}
    for p, (pp, _) in procs.items():
        children.setdefault(pp, []).append(p)
    out, todo, seen = [], [pid], set()
    while todo:
        p = todo.pop(0)
        if p in seen:
            continue
        seen.add(p)
        if p in procs:
            out.append(procs[p][1])
        todo += sorted(children.get(p, []))
    return out


def session_name(name: str) -> str:
    """tmux refuses `:` and turns `.` into `_` in a session name; do it first so lookups match."""
    return re.sub(r"[:.]", "_", str(name or "").strip()) or "Workspace"


def resolve_session(names: list, existing: list[str]) -> str | None:
    """By name, then alias; exact first, else the same name in another case."""
    folded = {}
    for s in existing:
        folded.setdefault(s.casefold(), s)
    for n in names:
        if not n:
            continue
        n = session_name(n)
        if n in existing:
            return n
        if n.casefold() in folded:
            return folded[n.casefold()]
    return None


def with_shell(command: str) -> str:
    return command if command.endswith(KEEP_SHELL) else command + KEEP_SHELL


# ---------------------------------------------------------------- tmux access

def tmux_bin() -> str | None:
    env = os.environ.get("BRIDGE_TMUX_BIN")
    if env:
        return env
    found = shutil.which("tmux")
    if found:
        return found
    for p in ("/opt/homebrew/bin/tmux", "/usr/local/bin/tmux", "/usr/bin/tmux"):
        if os.access(p, os.X_OK):
            return p
    return None


def tmux(*args: str, check: bool = True) -> str:
    binary = tmux_bin()
    if not binary:
        raise DriverError("tmux is not installed (no BRIDGE_TMUX_BIN, no `tmux` on PATH)")
    argv = [binary]
    sock = os.environ.get("BRIDGE_TMUX_SOCKET")
    if sock:
        argv += ["-L", sock]
    try:
        done = subprocess.run(argv + list(args), capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        raise DriverError(f"tmux failed to run: {exc}") from exc
    if done.returncode != 0 and check:
        err = (done.stderr or done.stdout).strip()
        if re.search(r"no server running|error connecting to|No such file or directory", err):
            raise NoServer(err)
        raise DriverError(err[:200] or f"tmux {args[0]} exit {done.returncode}")
    return done.stdout


PANE_FIELDS = ["session_name", "session_id", "window_id", "window_name", "window_index", "pane_id", "pane_active",
               "pane_current_command", "pane_pid", "window_active"]


def split_row(line: str, maxsplit: int = -1) -> list[str]:
    """One -F output line split on SEP, whether tmux printed the byte or its escape."""
    return line.replace(SEP_ESCAPED, SEP).split(SEP, maxsplit)


def list_panes() -> list[dict]:
    """Every pane on the server; [] when no server runs (then no tab is open, truly)."""
    fmt = SEP.join("#{%s}" % f for f in PANE_FIELDS)
    try:
        out = tmux("list-panes", "-a", "-F", fmt)
    except NoServer:
        return []
    rows = []
    for ln in out.splitlines():
        vals = split_row(ln)
        if len(vals) == len(PANE_FIELDS):
            rows.append(dict(zip(PANE_FIELDS, vals)))
    return rows


def windows(panes: list[dict] | None = None) -> list[dict]:
    """One entry per window: its active pane is the tab's ref, all its panes are kept for is_self."""
    panes = list_panes() if panes is None else panes
    by_win: dict[str, dict] = {}
    for p in panes:
        w = by_win.setdefault(p["window_id"], {"session": p["session_name"], "session_id": p["session_id"],
                                               "name": p["window_name"],
                                               "window_id": p["window_id"], "index": p["window_index"],
                                               "panes": [], "active": None})
        w["panes"].append(p["pane_id"])
        if p["pane_active"] == "1" or w["active"] is None:
            w["active"] = p
    return list(by_win.values())


def sessions_list() -> list[str]:
    try:
        return [s for s in tmux("list-sessions", "-F", "#{session_name}").splitlines() if s]
    except NoServer:
        return []


def capture(ref: str, lines: int | None = None) -> str:
    args = ["capture-pane", "-p", "-J", "-t", ref]
    if lines:
        args += ["-S", f"-{lines}"]
    return tmux(*args)


def ps_table() -> dict[int, tuple[int, str]]:
    try:
        done = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,args="], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return {}
    return parse_ps(done.stdout)


def check_ref(ref) -> str:
    """A ref must be a pane id that is open now; anything else is an error, never a guess."""
    if not isinstance(ref, str) or not REF_RE.fullmatch(ref):
        raise ValueError(f"not a tmux pane ref: {ref!r} (expected %N)")
    if not any(p["pane_id"] == ref for p in list_panes()):
        raise DriverError(f"no open tab {ref}")
    return ref


def session_ids() -> dict[str, str]:
    """Session id ($N) -> session name, of every session on the server."""
    try:
        out = tmux("list-sessions", "-F", "#{session_id}" + SEP + "#{session_name}")
    except NoServer:
        return {}
    rows = (split_row(ln, 1) for ln in out.splitlines())
    return dict(r for r in rows if len(r) == 2)


def check_ws_ref(ref) -> str:
    """A workspace ref must be a session id that exists now; anything else is an error, never a guess."""
    if not isinstance(ref, str) or not WS_REF_RE.fullmatch(ref):
        raise ValueError(f"not a tmux session ref: {ref!r} (expected $N)")
    if ref not in session_ids():
        raise DriverError(f"no open workspace {ref}")
    return ref


# ---------------------------------------------------------------- reading verbs

def tabs() -> list[dict]:
    own = os.environ.get("TMUX_PANE")
    procs = ps_table()
    out = []
    for w in windows():
        p = w["active"]
        try:
            screen = capture(p["pane_id"])
        except DriverError:
            screen = ""
        tree = descendants(int(p["pane_pid"]), procs) if p["pane_pid"].isdigit() else []
        agent = any(is_agent_args(a) for a in tree) or (
            not is_shell(p["pane_current_command"]) and screen_shows_agent(screen))
        out.append({"name": w["name"], "workspace": w["session"], "ref": p["pane_id"], "ws_ref": w["session_id"],
                    "state": classify_state(screen, agent), "last": last_line(screen),
                    "id": p["pane_id"], "is_self": bool(own) and own in w["panes"]})
    return out


def sessions() -> dict[str, str]:
    procs = ps_table()
    found: dict[str, str] = {}
    for w in windows():
        p = w["active"]
        if not p["pane_pid"].isdigit():
            continue
        for args in descendants(int(p["pane_pid"]), procs):
            sid = session_id_in(args) if is_agent_args(args) else None
            if sid:
                found.setdefault(w["name"], sid)
                break
    return found


# ---------------------------------------------------------------- opening

def launcher_dir() -> Path:
    d = Path(os.environ.get("BRIDGE_TMUX_LAUNCH_DIR") or Path.home() / ".cache/bridge-tmux/commands")
    d.mkdir(parents=True, exist_ok=True)
    d.chmod(0o700)
    return d


def runnable(command: str) -> str:
    """The command tmux hands to the window's shell. A long one (a whole prompt) goes into a private
    file first: tmux carries a command in one IPC message, and a few KB of prompt can exceed it."""
    if len(command.encode()) <= INLINE_MAX and "\n" not in command:
        return command
    d = launcher_dir()
    now = time.time()
    for f in d.iterdir():
        try:
            if f.is_file() and now - f.stat().st_mtime > LAUNCHER_DAYS * 86400:
                f.unlink()
        except OSError:
            pass
    body = command + "\n"
    f = d / (hashlib.sha1(body.encode("utf-8")).hexdigest()[:16] + ".sh")
    fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write(body)
    return f"/bin/sh {shlex.quote(str(f))}"


def new_session(name: str, cwd: str, label: str | None, command: str | None) -> str:
    """A detached session; its first window is the tab when a command is given. Returns the pane id."""
    args = ["new-session", "-d", "-P", "-F", "#{pane_id}", "-s", session_name(name), "-c", cwd]
    if label:
        args += ["-n", label]
    if command:
        args.append(runnable(with_shell(command)))
    ref = tmux(*args).strip()
    if label:
        tmux("set-option", "-w", "-t", ref, "automatic-rename", "off", check=False)
    return ref


def new_window(session: str, cwd: str, label: str, command: str | None) -> str:
    args = ["new-window", "-d", "-P", "-F", "#{pane_id}", "-t", f"={session}:", "-c", cwd, "-n", label]
    if command:
        args.append(runnable(with_shell(command)))
    return tmux(*args).strip()


def window_of(ref: str, wins: list[dict]) -> dict | None:
    return next((w for w in wins if ref in w["panes"]), None)


def find_window(session: str, label: str, wins: list[dict]) -> dict | None:
    return next((w for w in wins if w["session"] == session and w["name"] == label), None)


def move_window(ref: str, session: str) -> None:
    tmux("move-window", "-d", "-s", ref, "-t", f"={session}:")


def open_plan(req: dict) -> list[str]:
    """The plan as sessions and windows. Nothing is ever closed; a window that is the last one
    of its session stays there (tmux would destroy the emptied session) and is renamed in place."""
    plan = req.get("plan") or {}
    only = set(req["only"]) if req.get("only") else None
    resume = bool(req.get("resume"))
    root = str(ROOT)
    report: list[str] = []
    wins = windows()
    existing = sessions_list()
    counts = {s: sum(1 for w in wins if w["session"] == s) for s in existing}

    def can_move(src: str | None) -> bool:
        if not src or counts.get(src, 0) <= 1:
            return False
        counts[src] -= 1
        return True

    def keep(ref: str, label: str, src: str | None) -> None:
        why = ("it is the last tab there, moving it would close that workspace" if src in counts
               else "its workspace is unknown, so it is not moved")
        report.append(f"  kept {label} in {src or 'its workspace'}: {why}")
        tmux("rename-window", "-t", ref, "--", label)

    ctl = plan.get("control") or {"name": "Control"}
    ctl_session = resolve_session([ctl.get("name"), *(ctl.get("aliases") or [])], existing)
    if not ctl_session:
        try:
            command = ctl.get("command") if not req.get("here") else None
            new_session(ctl["name"], root, ctl["name"] if command else None, command)
            ctl_session = session_name(ctl["name"])
            existing.append(ctl_session)
            counts[ctl_session] = 1
            report.append(f"created {ctl_session}")
        except DriverError as exc:
            report.append(f"ERROR workspace {ctl['name']} not created: {exc}")

    for ws in plan.get("workspaces") or []:
        if only and ws["name"] not in only:
            continue
        cwd = ws.get("cwd") or root
        names = {ws["name"], *(ws.get("aliases") or [])}
        target = resolve_session([ws["name"], *(ws.get("aliases") or [])], existing)
        wanted = [t for t in ws.get("tabs") or [] if resume or t.get("action") != "resume"]
        for t in wanted:
            label = t.get("label") or t.get("slug")
            try:
                if t.get("action") == "open":
                    ref = t.get("ref")
                    w = window_of(ref, wins)
                    if not w:
                        report.append(f"  ERROR tab {label}: {ref} is not open")
                        continue
                    if w["session"] in names or w["session"] == target:
                        tmux("rename-window", "-t", ref, "--", label)
                        continue
                    if not target:
                        if not can_move(w["session"]):
                            keep(ref, label, w["session"])
                            continue
                        # tmux cannot create a session around an existing window: the new one starts
                        # with a shell, which stays (the driver never closes a tab)
                        new_session(ws["name"], cwd, None, None)
                        target = session_name(ws["name"])
                        existing.append(target)
                        counts[target] = 1
                        report.append(f"created {target}")
                        report.append(f"  {target} keeps its starting shell tab (the driver never closes a tab)")
                    elif not can_move(w["session"]):
                        keep(ref, label, w["session"])
                        continue
                    move_window(ref, target)
                    counts[target] = counts.get(target, 0) + 1
                    tmux("rename-window", "-t", ref, "--", label)
                    report.append(f"  moved {label}: {w['session']} -> {target}")
                    continue
                if not t.get("command"):
                    continue
                if target:
                    same = find_window(target, label, wins)
                    if same:
                        report.append(f"  already open: {label} ({same['active']['pane_id']}) in {target}")
                        continue
                    ref = new_window(target, cwd, label, t["command"])
                else:
                    ref = new_session(ws["name"], cwd, label, t["command"])
                    target = session_name(ws["name"])
                    existing.append(target)
                    report.append(f"created {target} with {label}")
                counts[target] = counts.get(target, 0) + 1
                report.append(f"  tab {label} ({ref}) in {target}")
            except DriverError as exc:
                report.append(f"  ERROR tab {label} in {ws['name']}: {exc}")

    here = req.get("here")
    if here and ctl_session:
        w = window_of(here, windows())
        if not w:
            report.append(f"calling tab {here} not found in tmux, so it was not moved into the control workspace")
        elif w["session"] != ctl_session:
            try:
                if can_move(w["session"]):
                    move_window(here, ctl_session)
                    report.append(f"  moved {ctl['name']}: this tab -> {ctl_session}")
                    tmux("rename-window", "-t", here, "--", ctl["name"])
                else:
                    keep(here, ctl["name"], w["session"])
            except DriverError as exc:
                report.append(f"  ERROR move this tab to {ctl_session}: {exc}")
    return report


def caller_session(here: str | None, wins: list[dict]) -> str | None:
    """The session of the calling pane: `here` first, else $TMUX_PANE. Never the attached or last one."""
    for ref in (here, os.environ.get("TMUX_PANE")):
        if ref:
            w = window_of(ref, wins)
            if w:
                return w["session"]
    return None


def launch(req: dict) -> list[str]:
    """One new window per entry: in the caller's session (tab), in a new session each (workspace),
    or in the session named after the entry's area, created once when missing (area).
    Like cmux, a launch never reuses by label: workplace.py already skips an agent that runs,
    and `--again` asks for a second tab on purpose."""
    target = req.get("target") or "tab"
    if target not in ("tab", "workspace", "area"):
        raise ValueError(f"unknown launch target {target!r}")
    root = str(ROOT)
    wins = windows()
    existing = sessions_list()
    caller = caller_session(req.get("here"), wins) if target == "tab" else None
    report: list[str] = []
    for t in req.get("tabs") or []:
        label = t.get("label") or t.get("slug") or "tab"
        try:
            if target == "workspace":
                name = session_name(label)
                if name in existing:
                    ref = new_window(name, root, label, t["command"])
                    report.append(f"tab {label} ({ref}) in {name}")
                else:
                    ref = new_session(name, root, label, t["command"])
                    existing.append(name)
                    report.append(f"workspace {name} ({ref})")
                continue
            if target == "area":
                area = t.get("workspace")
                if not area:
                    report.append(f"ERROR tab {label}: no area workspace given")
                    continue
                sess = resolve_session([area, *(t.get("aliases") or [])], existing)
                if not sess:
                    # the first tab of a new area IS its starting window: no stray shell is left behind
                    ref = new_session(area, root, label, t["command"])
                    sess = session_name(area)
                    existing.append(sess)
                    report.append(f"new workspace {sess}")
                    report.append(f"tab {label} ({ref}) in {sess}")
                    continue
            else:
                sess = caller
                if not sess:
                    report.append(f"ERROR tab {label}: calling workspace not found, not opened "
                                  "(never the attached workspace)")
                    continue
            ref = new_window(sess, root, label, t["command"])
            report.append(f"tab {label} ({ref}) in {sess}")
        except (DriverError, KeyError) as exc:
            report.append(f"ERROR tab {label}: {exc}")
    return report


def control(req: dict) -> list[str]:
    """An agent tab in the control session. A control window that already runs an agent is reused;
    one that holds only a shell (its agent ended) does not count, and a new window opens beside it."""
    ctl = req.get("control") if isinstance(req.get("control"), dict) else {}
    if not ctl.get("name"):
        raise ValueError("control needs control.name")
    command = str(req.get("command") or "").strip()
    if not command:
        raise ValueError("control needs a command")
    root = str(req.get("root") or ROOT)
    existing = sessions_list()
    sess = resolve_session([ctl["name"], *(ctl.get("aliases") or [])], existing)
    try:
        if not sess:
            ref = new_session(ctl["name"], root, ctl["name"], command)
            return [f"created {session_name(ctl['name'])} with {ctl['name']} ({ref})"]
        for t in tabs():
            if t["workspace"] == sess and t["name"] == ctl["name"] and t["state"] != "shell":
                return [f"already open: {ctl['name']} ({t['ref']}) in {sess}"]
        ref = new_window(sess, root, ctl["name"], command)
        return [f"  tab {ctl['name']} in {sess} ({ref})"]
    except DriverError as exc:
        return [f"  ERROR tab {ctl['name']} in {ctl['name']}: {exc}"]


# ---------------------------------------------------------------- steering verbs

def send(req: dict) -> list[str]:
    ref, text = check_ref(req["tab"]), str(req["text"])
    for i in range(0, len(text), SEND_CHUNK):
        tmux("send-keys", "-t", ref, "-l", text[i:i + SEND_CHUNK])
    tmux("send-keys", "-t", ref, "Enter")
    return [f"sent to {ref}"]


def rename(req: dict) -> list[str]:
    ref = check_ref(req["tab"])
    # `--` ends tmux's flags: a title that starts with '-' is a title, not an option
    tmux("rename-window", "-t", ref, "--", str(req["title"]))
    return [f"{ref} is now named {req['title']!r}"]


def rename_workspace(req: dict) -> list[str]:
    """Renames the session with the session-name sanitizer; a name another session has (compared after
    the same sanitizer, in any case) is refused: tmux would refuse it too, and two workspaces of one name
    could no longer be told apart by the plan."""
    ref = check_ws_ref(req.get("workspace"))
    title = req.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("rename_workspace needs a title")
    name = session_name(title)
    if any(sid != ref and session_name(n).casefold() == name.casefold() for sid, n in session_ids().items()):
        raise DriverError(f"the name {name!r} is in use by another session")
    tmux("rename-session", "-t", ref, "--", name)
    return [f"{ref} is now named {name!r}"]


def move_tab(req: dict) -> list[str]:
    """Moves the tab's window into another session (`move-window -d`, nothing focused). The last window of a
    session stays where it is, as in open: tmux would destroy the emptied session. An index is not offered
    (tmux numbers the windows of a session itself)."""
    ref = check_ref(req.get("tab"))
    target = check_ws_ref(req.get("workspace"))
    wins = windows()
    w = window_of(ref, wins)
    if w is None:
        raise DriverError(f"no open tab {ref}")
    if w["session_id"] == target:
        return [f"{ref} is in {target} already"]
    if sum(1 for x in wins if x["session_id"] == w["session_id"]) <= 1:
        return [f"ERROR {ref} is the last window of {w['session']}, moving it would close that workspace"]
    tmux("move-window", "-d", "-s", ref, "-t", f"{target}:")
    return [f"moved {ref} into {target}"]


def key(req: dict) -> list[str]:
    k = str(req.get("key") or "").lower()
    if k not in KEYS:
        return [f"ERROR key {req.get('key')!r} is not allowed (enter, escape, y, n, 1-9)"]
    ref = check_ref(req["tab"])
    name, literal = KEYS[k]
    tmux("send-keys", "-t", ref, *(["-l"] if literal else []), name)
    return [f"key {k} to {ref}"]


def keys(req: dict) -> list[str]:
    """A keyboard, in order: named keys by tmux's name, text and pastes as literal text."""
    ref = check_ref(req["tab"])
    steps = req.get("keys") or []
    if any("key" in step and step["key"] not in TERM_KEYS for step in steps):
        return ["ERROR a key that is not one of the terminal's"]
    for step in steps:
        if "key" in step:
            tmux("send-keys", "-t", ref, TERM_KEYS[step["key"]])
            continue
        text = step.get("text", step.get("paste", ""))
        for i in range(0, len(text), SEND_CHUNK):
            tmux("send-keys", "-t", ref, "-l", text[i:i + SEND_CHUNK])
    return [f"{len(steps)} steps to {ref}"]


def screen(req: dict) -> dict:
    ref = check_ref(req["tab"])
    try:
        n = int(req.get("lines") or SCREEN_LINES)
    except (TypeError, ValueError):
        n = SCREEN_LINES
    n = max(1, min(n, SCREEN_MAX_LINES))
    lines = [ln.rstrip() for ln in capture(ref, n).splitlines()]
    while lines and not lines[-1]:
        lines.pop()
    return {"text": "\n".join(lines[-n:])}


def focus(req: dict) -> list[str]:
    ref = check_ref(req["tab"])
    tmux("select-window", "-t", ref)
    tmux("select-pane", "-t", ref)
    clients = [c for c in tmux("list-clients", "-F", "#{client_name}", check=False).splitlines() if c]
    if os.environ.get("TMUX"):
        tmux("switch-client", "-t", ref, check=False)
    elif clients:
        tmux("switch-client", "-c", clients[0], "-t", ref, check=False)
    note = "" if clients else " (no client attached: it shows on the next attach)"
    return [f"focused {ref}{note}"]


def close(req: dict) -> list[str]:
    """Kills that one pane, on a person's request. Never the last pane of the server: that would end
    the server and every session with it."""
    ref = check_ref(req["tab"])
    if len(list_panes()) <= 1:
        return [f"ERROR {ref} is the last pane on this tmux server, closing it would end the server"]
    tmux("kill-pane", "-t", ref)
    return [f"closed {ref}"]


def handle(req: dict) -> dict:
    if tmux_bin() is None:
        raise DriverError("tmux is not installed (no BRIDGE_TMUX_BIN, no `tmux` on PATH)")
    verb = req.get("verb")
    if verb == "caps":
        return {"caps": list(VERBS)}
    if verb == "tabs":
        return {"tabs": tabs()}
    if verb == "sessions":
        return {"sessions": sessions()}
    if verb == "screen":
        return screen(req)
    actions = {"open": open_plan, "launch": launch, "send": send, "rename": rename, "control": control,
               "focus": focus, "key": key, "keys": keys, "close": close, "rename_workspace": rename_workspace,
               "move_tab": move_tab}
    if verb in actions:
        return {"report": actions[verb](req)}
    raise ValueError(f"unknown verb {verb!r}")


def main() -> int:
    try:
        req = json.loads(sys.stdin.read() or "{}")
        if not isinstance(req, dict):
            raise ValueError("request is not a JSON object")
        answer = handle(req)
    except (DriverError, ValueError, KeyError) as exc:
        message = f"tmux_driver: {exc}"
        print(json.dumps({"error": message}))
        print(message, file=sys.stderr)
        return 1
    print(json.dumps(answer, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
