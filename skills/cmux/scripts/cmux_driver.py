#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""cmux as a workplace driver for scripts/workplace.py.

The plan (which task, which workspace, new or resumed) belongs to CORE
(scripts/workplace.py, docs/workplace.md). This script is only what cmux can do:
list the tabs, open the plan, type into a tab, rename a tab, make a tab or a workspace and close a
workspace. It speaks the CORE JSON protocol: one request on stdin, one answer on stdout.

    {"verb": "tabs"}       -> {"tabs": [{"name", "workspace", "ref", "ws_ref", "state", "state_source", "last"}]}
    {"verb": "sessions"}   -> {"sessions": {"<tab title>": "<agent session id>"}}
    {"verb": "open", "plan": {...}, "only": [...] | null, "resume": bool, "here": ref | null}
    {"verb": "launch", "tabs": [{"label", "slug", "command", "workspace", "aliases"}],
     "target": "tab" | "workspace" | "area", "here": ref | null}
    {"verb": "send", "tab": ref, "text": "..."}
    {"verb": "rename", "tab": ref, "title": "..."}
    {"verb": "rename_workspace", "workspace": ws_ref, "title": "..."}
    {"verb": "move_tab", "tab": ref, "workspace": ws_ref, "index": n (optional)}
    {"verb": "set_color", "workspace": ws_ref, "color": "<palette name>" | null}
    {"verb": "set_description", "workspace": ws_ref, "text": "..." | null}
    {"verb": "workspaces"} -> {"workspaces": [{"ref", "title", "color", "color_name", "description", "cwd",
                                               "branch", ...}]}
    {"verb": "new_tab", "workspace": ws_ref, "title": "..." | null, "command": "..." | null}
                           -> {"report": [...], "ref": "surface:N"}
    {"verb": "new_workspace", "title": "...", "color": "<palette name>" | null, "cwd": "..." | null,
     "command": "..." | null}  -> {"report": [...], "ws_ref": "workspace:N", "ref": "surface:M"}
    {"verb": "close_workspace", "workspace": ws_ref}

`move_tab` moves one tab without focusing it and refuses (an ERROR line) the last tab of a workspace,
which cmux would drop. `set_color` takes a PALETTE name and sends cmux its hex; null clears the colour,
as null clears the description in `set_description`. A workspace's `color_name` is the PALETTE name of
its hex, null for any other colour.

A tab's `state_source` says where its state was read: `hook` (the hook file knows its agent) or
`glyph` (only the status glyph of its title). cmux drops the glyph once a tab has a title of its own,
so a renamed tab without a hook reads as a shell from then on.

`workspaces` only reads (workspace list, sidebar-state, list-notifications): what the cmux sidebar
shows, for the cockpit's own sidebar. Like `workspace list` it covers the current window.

`new_tab` opens one tab in a workspace and `new_workspace` one workspace, neither takes the focus. No
`command` is a plain shell; a `command` goes the way `launch` sends it (a short typed line, the start
marker awaited). Both answer the new refs, also when the command did not start (an ERROR line says so):
the tab exists, and the caller may open it. `new_workspace` starts in `cwd` (default the Bridge folder)
and takes a palette colour. `close_workspace` closes one workspace and never the last one of its window.

Wire it in bridge-config.yaml:

    workplace:
      driver: {command: ["python3", "${root}/skills/cmux/scripts/cmux_driver.py"]}

A `command` may be several KB (a whole prompt). cmux types it into the new tab's shell, which
may still be starting and then keeps only 1024 bytes of a line, so the driver never types a
long command raw: cmux_layout.typed_command puts it in a private launcher file and types
`/bin/sh '<file>'`. A launched tab's file first creates a start marker; a tab whose marker does
not appear within CMUX_LAUNCH_WAIT_SEC (default 20) is reported as an ERROR line, never as
started. It keeps its label: the typed line may still run after a slow shell start, and the
label is how a later click finds that agent instead of opening a second one.

Rules: it never closes a tab or a workspace on its own, only `close` and `close_workspace`, which a
person asked for, and never moves the last tab out of a workspace (cmux would drop the emptied
workspace). A tab the plan has open already is reused, never opened twice (`new_tab` and `launch` open
one on purpose). It reads every window (`tree --all`), not only the current
one. When cmux is missing, refuses a call, or gives no readable answer, the
driver exits non-zero with {"error": "..."} on stdout and the reason on stderr, so
CORE reads the tab view as UNKNOWN, never as "no tab is open".

The control workspace starts `workplace.control.command` (with a shell behind it)
when the config sets one and the plan is not opened `--here`.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cmux_layout as cl  # noqa: E402

ROOT = cl.BRIDGE_ROOT
HOOKS_FILE = Path(os.environ.get("CMUX_HOOKS_FILE", Path.home() / ".cmuxterm/claude-hook-sessions.json"))
PERMISSION_EVENTS = ("Notification", "PermissionRequest")
WAITING_EVENTS = ("Stop", "SessionStart")
SPINNER = set("◐◓◑◒")   # quarter-circle spinner; Braille is matched by range
IDLE_GLYPH = "✳"                        # eight-spoked asterisk: the agent is idle
KEEP_SHELL = cl.KEEP_SHELL


LAUNCH_WAIT_SEC = 20.0
# cmux's named workspace colours with the hex it stores for each (the same map as workplace.py COLORS)
PALETTE = {
    "Red": "#C0392B", "Crimson": "#922B21", "Orange": "#A04000", "Amber": "#7D6608",
    "Olive": "#4A5C18", "Green": "#196F3D", "Teal": "#006B6B", "Aqua": "#0E6B8C",
    "Blue": "#1565C0", "Navy": "#1A5276", "Indigo": "#283593", "Purple": "#6A1B9A",
    "Magenta": "#AD1457", "Rose": "#880E4F", "Brown": "#7B3F00", "Charcoal": "#3E4B5E",
}
PALETTE_BY_HEX = {v.upper(): k for k, v in PALETTE.items()}
INDEX_MAX = 99


class DriverError(RuntimeError):
    """cmux gave no answer the driver can trust."""


# ---------------------------------------------------------------- reading cmux

def _load_json(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _glyph(title: str) -> str | None:
    head = (title or "").lstrip()[:1]
    if head == IDLE_GLYPH:
        return "idle"
    if head in SPINNER or (head and 0x2800 <= ord(head) <= 0x28FF):
        return "busy"
    return None


def live_tabs(session: dict, hooks: dict) -> list[dict]:
    """Terminal tabs from cmux's session file, with state and last line from the hook file.

    The state is in the CORE vocabulary: needs-you, waiting, working, shell.
    The hook file decides first: a surface it lists runs an agent, and its last
    hook event says what the agent does. The title glyph is only the fallback,
    because cmux drops it once a tab has a custom title (and the workplace
    renames every task tab).
    """
    by_surface = hooks.get("activeSessionsBySurface") or {}
    sessions = hooks.get("sessions") or {}
    tabs = []
    for window in session.get("windows") or []:
        for ws in (window.get("tabManager") or {}).get("workspaces") or []:
            ws_title = ws.get("customTitle") or cl.strip_status_glyph(ws.get("processTitle") or "")
            panels = {p.get("id"): p for p in ws.get("panels") or []}
            order = [pid for pane in cl._panel_ids_in_order(ws.get("layout") or {}) for pid in pane]
            order += [pid for pid in panels if pid not in order]
            for pid in order:
                p = panels.get(pid)
                if not p or p.get("type", "terminal") != "terminal":
                    continue
                raw = p.get("title") or ""
                bound = by_surface.get(pid)
                hook = sessions.get((bound or {}).get("sessionId") or "") or {}
                if bound:
                    event = hook.get("hookEventName")
                    state = ("needs-you" if event in PERMISSION_EVENTS
                             else "waiting" if event in WAITING_EVENTS else "working")
                else:
                    glyph = _glyph(raw)
                    state = "shell" if glyph is None else "waiting" if glyph == "idle" else "working"
                tabs.append({"workspace": ws_title, "ws_ref": ws.get("workspaceId"),
                             "surface": pid, "state": state, "state_source": "hook" if bound else "glyph",
                             "title": p.get("customTitle") or cl.strip_status_glyph(raw),
                             "last": (hook.get("lastBody") or "").replace("\n", " ")[:90]})
    return tabs


def read_tree() -> dict:
    """`cmux tree --all --json`: every window, live, refs and UUIDs. Raises when unreadable."""
    out = cl.cmux_checked("tree", "--all", "--json", "--id-format", "both")
    try:
        tree = json.loads(out)
    except ValueError as exc:
        raise DriverError(f"cmux tree gave no JSON: {out.strip()[:120]}") from exc
    if not isinstance(tree, dict) or not isinstance(tree.get("windows"), list):
        raise DriverError("cmux tree gave no window list")
    return tree


def _tree_workspaces(tree: dict):
    for window in tree.get("windows") or []:
        yield from window.get("workspaces") or []


def workspace_index(tree: dict) -> dict[str, str]:
    """Workspace title -> ref across ALL windows (the first title wins)."""
    index: dict[str, str] = {}
    for ws in _tree_workspaces(tree):
        title = cl.strip_status_glyph(ws.get("title") or "").strip()
        if title and ws.get("ref"):
            index.setdefault(title, ws["ref"])
    return index


def surface_counts(tree: dict) -> dict[str, int]:
    """Workspace ref -> number of surfaces of any kind in it."""
    counts = {}
    for ws in _tree_workspaces(tree):
        counts[ws.get("ref")] = sum(len(p.get("surfaces") or []) or int(p.get("surface_count") or 0)
                                    for p in ws.get("panes") or [])
    return counts


def surface_homes(tree: dict) -> dict[str, str]:
    """Surface ref -> the ref of the workspace it lives in."""
    return {sf.get("ref"): ws.get("ref") for ws in _tree_workspaces(tree)
            for pane in ws.get("panes") or [] for sf in pane.get("surfaces") or []}


def socket_tabs(tree: dict) -> list[dict]:
    """Terminal tabs from `cmux tree --json`: live, unlike the session file,
    which cmux writes with a delay."""
    tabs = []
    for window in tree.get("windows") or []:
        for ws in window.get("workspaces") or []:
            for pane in ws.get("panes") or []:
                for sf in pane.get("surfaces") or []:
                    if sf.get("type") != "terminal":
                        continue
                    tabs.append({"workspace": cl.strip_status_glyph(ws.get("title") or "").strip(),
                                 "ws_ref": ws.get("ref"),
                                 "surface": sf.get("ref"),
                                 "id": sf.get("id"),
                                 "title": cl.strip_status_glyph(sf.get("title") or "")})
    return tabs


def current_tabs() -> list[dict]:
    """Live tab refs from the socket, every window.

    Only when cmux answers `ping` but the tree fails does the session file stand
    in. When the socket is down the session file is a leftover that names tabs
    which no longer exist, so that is a DriverError, never a tab list.
    """
    try:
        return socket_tabs(read_tree())
    except (DriverError, cl.CmuxError) as exc:
        if isinstance(exc, cl.CmuxUnavailable) or not cl.cmux_reachable():
            raise DriverError(f"cmux does not answer, tab view unknown ({exc})") from exc
    session = _load_json(cl.DEFAULT_SOURCE)
    if "windows" not in session:
        raise DriverError("cmux gave no tab tree and the session file is not readable")
    return live_tabs(session, {})


def _key(tab: dict) -> tuple[str, str]:
    return (tab.get("workspace") or "", cl.strip_status_glyph(tab.get("title") or "").strip())


def tabs() -> list[dict]:
    """Live refs from the socket, state and last line from the session file and hooks.

    The socket calls a tab `surface:91`, the session file calls the same tab by a
    UUID: joining by ref matches nothing, so every tab would read as a shell.
    Tabs are joined by (workspace, title without status glyph) instead.
    """
    live = {_key(t): t for t in live_tabs(_load_json(cl.DEFAULT_SOURCE), _load_json(HOOKS_FILE))}
    # The tab this process runs in (cmux sets the UUID), marked is_self so a caller running in a tab
    # can skip its own tab.
    own = os.environ.get("CMUX_SURFACE_ID") or None
    out = []
    for t in current_tabs():
        info = live.get(_key(t), {})
        out.append({"name": t["title"], "workspace": t["workspace"], "ref": t["surface"],
                    "ws_ref": t.get("ws_ref"), "state": info.get("state", "shell"),
                    "state_source": info.get("state_source", "glyph"),
                    "last": info.get("last", ""), "id": t.get("id"),
                    "is_self": own is not None and t.get("id") == own})
    return out


def sessions_by_title(snapshots: list[dict]) -> dict[str, str]:
    """Tab title -> agent session id, the newest snapshot (first in the list) wins."""
    found: dict[str, str] = {}
    for snap in snapshots:
        for ws in cl.iter_workspaces(snap.get("layout") or {}):
            for pane in ws.get("panes") or []:
                for tab in pane:
                    if tab.get("kind") == "claude" and tab.get("session_id"):
                        found.setdefault(tab.get("title") or "", tab["session_id"])
    return found


def sessions() -> dict[str, str]:
    return sessions_by_title(cl.load_snapshots(cl.DEFAULT_DIR))


# ---------------------------------------------------------------- opening the plan

def to_cmux_plan(plan: dict) -> dict:
    """CORE plan -> the shape apply_calls expects: open tabs carry `surface`, and
    every command keeps its tab alive when the agent exits."""
    converted = {**plan, "workspaces": []}
    for ws in plan.get("workspaces") or []:
        new_tabs = []
        for t in ws.get("tabs") or []:
            tab = dict(t)
            if tab.get("action") == "open":
                tab["surface"] = tab.get("ref")
            elif tab.get("command") and not tab["command"].endswith(KEEP_SHELL):
                tab["command"] = tab["command"] + KEEP_SHELL
            new_tabs.append(tab)
        converted["workspaces"].append({**ws, "tabs": new_tabs})
    return converted


def resolve_workspace(ws: dict, existing: dict[str, str]) -> str | None:
    """By name, then by alias; an exact title first, else the same title in another case
    ("open-bridge" finds "Open-Bridge")."""
    folded: dict[str, str] = {}
    for title, ref in existing.items():
        folded.setdefault(title.casefold(), ref)
    for name in [ws["name"], *(ws.get("aliases") or [])]:
        if name in existing:
            return existing[name]
        if str(name).casefold() in folded:
            return folded[str(name).casefold()]
    return None


def _with_shell(command: str) -> str:
    return command if command.endswith(KEEP_SHELL) else command + KEEP_SHELL


def apply_calls(plan: dict, existing: dict[str, str], root: str, only: set[str] | None = None,
                here: str | None = None, resume: bool = False,
                counts: dict[str, int] | None = None, homes: dict[str, str] | None = None) -> list[dict]:
    """The cmux calls, in order. There is no close operation, on purpose.

    `existing` maps workspace titles to refs across every window, `counts` the
    surfaces per workspace ref, `homes` each surface to its workspace ref. `ws`
    names a workspace created earlier in the list. `here` is the calling tab: it
    moves into the control workspace last, after every other workspace has its
    tabs. A tab that is the last one of its workspace is never moved (cmux would
    drop the emptied workspace); it is renamed where it is and reported. Tabs that
    would resume an earlier session open only when `resume` is set.
    """
    counts = dict(counts or {})
    homes = homes or {}
    calls = []

    def keep(tab_ref: str, label: str, src_ref: str | None, src_name, ws_name: str) -> None:
        if src_ref and src_ref in counts:
            why = "it is the last tab there, moving it would close that workspace"
        else:
            why = "its workspace is unknown, so it is not moved"
        calls.append({"op": "note", "ws": ws_name,
                      "text": f"  kept {label} in {src_name or src_ref or 'its workspace'}: {why}"})
        calls.append({"op": "rename", "ws": ws_name, "surface": tab_ref, "tab": label, "ws_ref": src_ref})

    def can_move(src_ref: str | None) -> bool:
        if not src_ref or counts.get(src_ref, 0) <= 1:
            return False
        counts[src_ref] -= 1
        return True

    ctl = plan.get("control") or {"name": "Control"}
    ctl_ref = resolve_workspace(ctl, existing)
    if not ctl_ref:
        command = _with_shell(ctl["command"]) if ctl.get("command") and not here else None
        calls.append({"op": "create", "ws": ctl["name"], "cwd": root, "command": command})
    calls.append({"op": "decorate", "ws": ctl["name"], "ref": ctl_ref, "color": ctl.get("color"),
                  "description": ctl.get("description")})
    calls.append({"op": "order", "ws": ctl["name"], "ref": ctl_ref, "index": 0})
    for pos, ws in enumerate(plan.get("workspaces") or [], 1):
        if only and ws["name"] not in only:
            continue
        cwd = ws.get("cwd") or root
        names = {ws["name"], *(ws.get("aliases") or [])}
        opened = [t for t in ws["tabs"] if t["action"] == "open"]
        wanted = [t for t in ws["tabs"] if resume or t["action"] != "resume"]
        new = [t for t in wanted if t["action"] != "open" and t.get("command")]
        ref = resolve_workspace(ws, existing)
        placed = []          # (tab, "stay" | "move" | "keep", source ref)
        for t in opened:
            src = t.get("ws_ref") or homes.get(t.get("surface"))
            if t.get("workspace") in names:
                placed.append((t, "stay", src))
            else:
                placed.append((t, "move" if can_move(src) else "keep", src))
        exists = bool(ref)
        if not ref and (new or any(kind == "move" for _, kind, _ in placed)):
            exists = True
            first = new.pop(0) if new else None
            calls.append({"op": "create", "ws": ws["name"], "cwd": cwd,
                          "slug": first and first["slug"], "command": first and first["command"],
                          "tab": first and first["label"], "leftover_shell": first is None})
        if exists:
            calls.append({"op": "decorate", "ws": ws["name"], "ref": ref, "color": ws.get("color"),
                          "description": ws.get("description")})
            calls.append({"op": "order", "ws": ws["name"], "ref": ref, "index": pos})
        here_now = {}
        for t, kind, src in placed:
            if kind == "keep":
                keep(t["surface"], t["label"], src, t.get("workspace"), ws["name"])
                continue
            if kind == "move":
                calls.append({"op": "move", "ws": ws["name"], "ref": ref, "surface": t["surface"],
                              "tab": t["label"], "from": t.get("workspace")})
            calls.append({"op": "rename", "ws": ws["name"], "surface": t["surface"], "tab": t["label"],
                          "ws_ref": src if kind == "stay" else None})
            here_now[t["slug"]] = t["surface"]
        for t in new:
            calls.append({"op": "tab", "ws": ws["name"], "ref": ref, "slug": t["slug"],
                          "command": t["command"], "tab": t["label"]})
        if exists:
            calls.append({"op": "tab_order", "ws": ws["name"], "ref": ref,
                          "slugs": [t["slug"] for t in wanted], "known": here_now})
    if here:
        src = homes.get(here)
        if can_move(src):
            calls.append({"op": "move", "ws": ctl["name"], "ref": ctl_ref, "surface": here,
                          "tab": ctl["name"], "from": "this tab"})
            calls.append({"op": "rename", "ws": ctl["name"], "ref": ctl_ref, "surface": here,
                          "tab": ctl["name"], "ws_ref": None})
        else:
            keep(here, ctl["name"], src, None, ctl["name"])
    return calls


def rename_tab(surface: str, ws_ref: str | None, title: str) -> str:
    """cmux resolves a tab relative to a workspace (default: the caller's), so a
    tab in another workspace is only renamed with --workspace."""
    args = ["tab-action", "--action", "rename", "--tab", surface, "--title", title]
    if ws_ref:
        args += ["--workspace", ws_ref]
    return cl.cmux_checked(*args)


def run_calls(calls: list[dict], existing: dict[str, str]) -> list[str]:
    """Run the calls. A call cmux refuses becomes an ERROR line, never a success line."""
    refs = dict(existing)
    surfaces: dict[str, str] = {}  # slug -> surface ref of tabs created here
    report = []
    for c in calls:
        ws_ref = c.get("ref") or refs.get(c["ws"])
        try:
            if c["op"] == "note":
                report.append(c["text"])
            elif c["op"] == "create":
                args = ["workspace", "create", "--name", c["ws"], "--cwd", c["cwd"], "--focus", "false"]
                if c.get("command"):
                    args += ["--command", cl.typed_command(c["command"])]
                out = cl.cmux_checked(*args)
                ws_ref = cl.parse_ref(out, "workspace")
                if not ws_ref:
                    report.append(f"ERROR workspace {c['ws']} not created: {out.strip()[:120]}")
                    continue
                refs[c["ws"]] = ws_ref
                if c.get("tab"):
                    sref = cl._first_surface(ws_ref)
                    if sref:
                        rename_tab(sref, ws_ref, c["tab"])
                        surfaces[c["slug"]] = sref
                report.append(f"created {c['ws']} ({ws_ref})" + (f" with {c['tab']}" if c.get("tab") else ""))
                if c.get("leftover_shell"):
                    # cmux cannot create a workspace around an existing tab, so a new one
                    # starts with a shell. It stays: the driver never closes a tab.
                    report.append(f"  {c['ws']} keeps its starting shell tab (the driver never closes a tab)")
            elif c["op"] == "rename":
                rename_tab(c["surface"], c.get("ws_ref") or c.get("ref") or refs.get(c["ws"]), c["tab"])
            elif not ws_ref:
                report.append(f"skipped {c['op']} {c['ws']}: workspace missing")
            elif c["op"] == "decorate":
                cl.cmux_checked("workspace", "rename", ws_ref, "--title", c["ws"])
                for cmd in cl.decoration_commands(ws_ref, c):
                    cl.cmux_checked(*cmd)
            elif c["op"] == "move":
                cl.cmux_checked("move-surface", "--surface", c["surface"], "--workspace", ws_ref,
                                "--focus", "false")
                report.append(f"  moved {c['tab']}: {c.get('from')} -> {c['ws']}")
            elif c["op"] == "tab_order":
                known = {**c.get("known", {}), **surfaces}
                for i, slug in enumerate(s for s in c["slugs"] if s in known):
                    cl.cmux_checked("reorder-surface", "--workspace", ws_ref, "--surface", known[slug],
                                    "--index", str(i))
            elif c["op"] == "order":
                cl.cmux_checked("reorder-workspace", "--workspace", ws_ref, "--index", str(c["index"]))
            elif c["op"] == "tab":
                sref = cl.parse_ref(cl.cmux_checked("new-surface", "--workspace", ws_ref, "--command",
                                                    cl.typed_command(c["command"]), "--focus", "false"),
                                    "surface")
                if sref:
                    rename_tab(sref, ws_ref, c["tab"])
                    surfaces[c["slug"]] = sref
                    report.append(f"  tab {c['tab']} in {c['ws']} ({sref})")
                else:
                    report.append(f"  ERROR tab {c['tab']} in {c['ws']}: no surface ref")
        except cl.CmuxError as exc:
            what = c.get("tab") or c["ws"]
            report.append(f"  ERROR {c['op']} {what} in {c['ws']}: {exc}")
    return report


# ---------------------------------------------------------------- verbs

def resolve_here(here: str | None, tree: dict) -> str | None:
    """The calling tab as `surface:N`. `$CMUX_SURFACE_ID` is a UUID, while the tree
    speaks refs: match a UUID the tree exposes, else the tree's own `caller` when
    the value is this process's $CMUX_SURFACE_ID. None when it cannot be found."""
    if not here:
        return None
    if re.fullmatch(r"surface:\d+", here):
        return here
    for ws in _tree_workspaces(tree):
        for pane in ws.get("panes") or []:
            for sf in pane.get("surfaces") or []:
                if any(str(sf.get(k) or "").upper() == here.upper() for k in ("id", "uuid")):
                    return sf.get("ref")
    caller = tree.get("caller") or {}
    if caller.get("surface_ref") and here == os.environ.get("CMUX_SURFACE_ID"):
        return caller["surface_ref"]
    return None


def open_plan(req: dict) -> list[str]:
    """Refuses (DriverError) when the workspaces cannot be read: planning on an
    empty view would create the control workspace and every workspace again."""
    plan = to_cmux_plan(req.get("plan") or {})
    try:
        tree = read_tree()
    except (DriverError, cl.CmuxError) as exc:
        raise DriverError(f"cannot read cmux workspaces, nothing opened ({exc})") from exc
    existing = workspace_index(tree)
    only = set(req["only"]) if req.get("only") else None
    here = resolve_here(req.get("here"), tree)
    notes = []
    if req.get("here") and not here:
        notes.append(f"calling tab {req['here']} not found in cmux, so it was not moved into the control workspace")
    calls = apply_calls(plan, existing, str(ROOT), only, here, bool(req.get("resume")),
                        counts=surface_counts(tree), homes=surface_homes(tree))
    return notes + run_calls(calls, existing)


def control_calls(ctl: dict, command: str, existing: dict[str, str], root: str) -> list[dict]:
    """One new agent tab in the control workspace, the workspace created first when it is missing.
    Nothing is moved or closed: a control tab that does not answer stays where it is."""
    ref = resolve_workspace(ctl, existing)
    calls: list[dict] = []
    if not ref:
        calls.append({"op": "create", "ws": ctl["name"], "cwd": root, "command": _with_shell(command),
                      "slug": "control", "tab": ctl["name"]})
        calls.append({"op": "decorate", "ws": ctl["name"], "ref": None, "color": ctl.get("color"),
                      "description": ctl.get("description")})
        calls.append({"op": "order", "ws": ctl["name"], "ref": None, "index": 0})
    else:
        calls.append({"op": "tab", "ws": ctl["name"], "ref": ref, "slug": "control",
                      "command": _with_shell(command), "tab": ctl["name"]})
    return calls


def control(req: dict) -> list[str]:
    """Start a new agent tab in the control workspace (the page's relay needs one that answers)."""
    ctl = req.get("control") if isinstance(req.get("control"), dict) else {}
    if not ctl.get("name"):
        raise ValueError("control needs control.name")
    command = str(req.get("command") or "").strip()
    if not command:
        raise ValueError("control needs a command")
    try:
        tree = read_tree()
    except (DriverError, cl.CmuxError) as exc:
        raise DriverError(f"cannot read cmux workspaces, nothing started ({exc})") from exc
    existing = workspace_index(tree)
    return run_calls(control_calls(ctl, command, existing, str(req.get("root") or ROOT)), existing)


def caller_workspace(here: str | None, tree: dict) -> str | None:
    """The workspace of the calling tab: `here` first, else the tree's own `caller`.
    None when neither is known; the selected workspace is never a fallback."""
    surface = resolve_here(here, tree)
    if surface:
        home = surface_homes(tree).get(surface)
        if home:
            return home
    return (tree.get("caller") or {}).get("workspace_ref")


def _launch_wait() -> float:
    try:
        return max(0.0, float(os.environ.get("CMUX_LAUNCH_WAIT_SEC", LAUNCH_WAIT_SEC)))
    except ValueError:
        return LAUNCH_WAIT_SEC


def _launch_line(t: dict) -> tuple[str, Path]:
    """The short line cmux types for a launched tab, and the marker its launcher creates first."""
    marker = cl.launcher_dir() / f"{uuid.uuid4().hex}.started"
    return cl.typed_command(_with_shell(t["command"]), marker=marker), marker


def _await_started(pending: list[dict], report: list[str]) -> None:
    """Wait until each launched tab's command has started (its marker exists). A tab whose
    marker does not come in time is an ERROR line, so the caller never counts it as started.
    The tab is not renamed: its command may still run late, and its label keeps it findable."""
    wait = _launch_wait()
    deadline = time.monotonic() + wait
    while any(not p["marker"].exists() for p in pending) and time.monotonic() < deadline:
        time.sleep(0.2)
    for p in pending:
        if p["marker"].exists():
            p["marker"].unlink(missing_ok=True)
            continue
        report[p["index"]] = (f"ERROR tab {p['label']}: command did not start within {wait:g} s "
                              f"(shell busy or typed line lost); the tab stays open and may still start late")


def launch(req: dict) -> list[str]:
    """One new tab per entry: in the caller's workspace (tab), in a new workspace each (workspace), or in
    the workspace named after the entry's area, created once when missing (area). Never closes anything."""
    tabs = req.get("tabs") or []
    target = req.get("target") or "tab"
    if target not in ("tab", "workspace", "area"):
        raise ValueError(f"unknown launch target {target!r}")
    report: list[str] = []
    pending: list[dict] = []
    if target == "workspace":
        for t in tabs:
            try:
                line, marker = _launch_line(t)
                out = cl.cmux_checked("workspace", "create", "--name", t["label"], "--cwd", str(ROOT),
                                      "--focus", "false", "--command", line)
                ref = cl.parse_ref(out, "workspace")
                report.append(f"workspace {t['label']} ({ref})" if ref
                              else f"ERROR workspace {t['label']} not created: {out.strip()[:120]}")
                if ref:
                    pending.append({"label": t["label"], "marker": marker, "index": len(report) - 1})
            except cl.CmuxError as exc:
                report.append(f"ERROR workspace {t['label']}: {exc}")
        _await_started(pending, report)
        return report
    try:
        tree = read_tree()
    except (DriverError, cl.CmuxError) as exc:
        raise DriverError(f"cannot read cmux workspaces, nothing opened ({exc})") from exc
    caller = caller_workspace(req.get("here"), tree)
    # area: each tab goes into the workspace named after its area, created once when missing
    areas = workspace_index(tree) if target == "area" else {}
    titles = {ref: title for title, ref in workspace_index(tree).items()}
    for t in tabs:
        area = t.get("workspace") if target == "area" else None
        ws_ref = resolve_workspace({"name": area, "aliases": t.get("aliases")}, areas) if area else caller
        try:
            line, marker = _launch_line(t)
            if area and not ws_ref:
                # the first tab of a new area IS its starting tab: no stray shell is left behind
                out = cl.cmux_checked("workspace", "create", "--name", area, "--cwd", str(ROOT), "--focus", "false",
                                      "--command", line)
                ws_ref = cl.parse_ref(out, "workspace")
                if not ws_ref:
                    report.append(f"ERROR workspace {area} not created: {out.strip()[:120]}")
                    continue
                areas[area] = ws_ref
                titles[ws_ref] = area
                report.append(f"new workspace {area} ({ws_ref})")
                sref = cl._first_surface(ws_ref)
            elif not ws_ref:
                report.append(f"ERROR tab {t['label']}: calling workspace not found, not opened "
                              "(never the selected workspace)")
                continue
            else:
                out = cl.cmux_checked("new-surface", "--workspace", ws_ref, "--command", line, "--focus", "false")
                sref = cl.parse_ref(out, "surface")
            if not sref:
                report.append(f"ERROR tab {t['label']}: no surface ref")
                continue
            rename_tab(sref, ws_ref, t["label"])
            report.append(f"tab {t['label']} ({sref}) in {titles.get(ws_ref, ws_ref)}")
            pending.append({"label": t["label"], "marker": marker, "index": len(report) - 1})
        except cl.CmuxError as exc:
            report.append(f"ERROR tab {t['label']}: {exc}")
    _await_started(pending, report)
    return report


def _text(req: dict, key: str, what: str) -> str | None:
    """A text the request may leave out: None for none or blank, else the text. Anything but text is an error."""
    value = req.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise DriverError(f"{what} takes {key} as text")
    return value.strip() or None


def new_tab(req: dict) -> dict:
    """One new tab in the workspace named by its live ref, unfocused: a plain shell, or `command` sent the way
    launch sends it. Answers the new tab's ref, also when the command did not start (an ERROR line says so):
    the tab exists then, and its title keeps it findable."""
    ws = _ref(req, "workspace", "new_tab")
    title, command = _text(req, "title", "new_tab"), _text(req, "command", "new_tab")
    tree = read_tree()
    if ws not in surface_counts(tree):
        raise DriverError(f"no open workspace {ws}")
    where = {ref: name for name, ref in workspace_index(tree).items()}.get(ws, ws)
    args = ["new-surface", "--workspace", ws]
    marker = None
    if command:
        line, marker = _launch_line({"command": command})
        args += ["--command", line]
    out = cl.cmux_checked(*args, "--focus", "false")
    sref = cl.parse_ref(out, "surface")
    if not sref:
        raise DriverError(f"cmux new-surface gave no surface ref: {out.strip()[:120]}")
    report = [f"tab {title} ({sref}) in {where}" if title else f"tab {sref} in {where}"]
    if title:
        try:
            rename_tab(sref, ws, title)
        except cl.CmuxError as exc:
            report.append(f"  ERROR tab {sref}: not named {title!r}: {exc}")
    if marker:
        _await_started([{"label": title or sref, "marker": marker, "index": 0}], report)
    return {"report": report, "ref": sref}


def new_workspace(req: dict) -> dict:
    """One new workspace, unfocused, with its first tab: a plain shell, or `command` sent the way launch sends
    it. Answers the workspace ref and its first tab's ref, also when the command did not start."""
    title = _text(req, "title", "new_workspace")
    if not title:
        raise DriverError("new_workspace needs a title")
    color = req.get("color")
    if color is not None and color not in PALETTE:
        raise DriverError(f"new_workspace takes one of {', '.join(PALETTE)} or no colour")
    cwd, command = _text(req, "cwd", "new_workspace") or str(ROOT), _text(req, "command", "new_workspace")
    args = ["workspace", "create", "--name", title, "--cwd", cwd, "--focus", "false"]
    marker = None
    if command:
        line, marker = _launch_line({"command": command})
        args += ["--command", line]
    out = cl.cmux_checked(*args)
    ws_ref = cl.parse_ref(out, "workspace")
    if not ws_ref:
        raise DriverError(f"cmux workspace create gave no workspace ref: {out.strip()[:120]}")
    report = [f"workspace {title} ({ws_ref})"]
    if color:
        try:
            for cmd in cl.decoration_commands(ws_ref, {"color": PALETTE[color]}):
                cl.cmux_checked(*cmd)
        except cl.CmuxError as exc:
            report.append(f"  ERROR workspace {title} ({ws_ref}) not coloured: {exc}")
    sref = cl._first_surface(ws_ref)
    if not sref:
        report.append(f"  ERROR workspace {title} ({ws_ref}) shows no first tab")
    if marker:
        _await_started([{"label": title, "marker": marker, "index": 0}], report)
    return {"report": report, "ws_ref": ws_ref, "ref": sref}


def close_workspace(req: dict) -> list[str]:
    """Closes one workspace by its live ref, on a person's request. The last workspace of a window stays
    (an ERROR line): closing it would close the window."""
    ws = _ref(req, "workspace", "close_workspace")
    window = next((w for w in read_tree().get("windows") or []
                   if any(x.get("ref") == ws for x in w.get("workspaces") or [])), None)
    if window is None:
        raise DriverError(f"no open workspace {ws}")
    if len(window.get("workspaces") or []) <= 1:
        return [f"ERROR {ws} is the last workspace of its window, closing it would close the window"]
    cl.cmux_checked("close-workspace", "--workspace", ws)
    return [f"{ws} closed"]


def _ws_ref_of(surface: str) -> str | None:
    """The workspace of an open tab. A ref that is not open is an error, not a guess."""
    for t in current_tabs():
        if t["surface"] == surface:
            return t.get("ws_ref")
    raise DriverError(f"no open tab {surface}")


def send(req: dict) -> list[str]:
    surface, text = req["tab"], req["text"]
    ws_ref = _ws_ref_of(surface)
    where = ["--workspace", ws_ref] if ws_ref else []
    cl.cmux_checked("send", *where, "--surface", surface, text)
    cl.cmux_checked("send-key", *where, "--surface", surface, "Enter")
    return [f"sent to {surface}"]


def rename(req: dict) -> list[str]:
    rename_tab(req["tab"], _ws_ref_of(req["tab"]), req["title"])
    return [f"{req['tab']} is now named {req['title']!r}"]


def rename_workspace(req: dict) -> list[str]:
    """One workspace gets a title of its own; a ref cmux does not know is an error, never a guess."""
    ref, title = req.get("workspace"), req.get("title")
    if not isinstance(ref, str) or not ref.strip() or not isinstance(title, str) or not title.strip():
        raise DriverError("rename_workspace needs a workspace ref and a title")
    try:
        cl.cmux_checked("workspace", "rename", ref, "--title", title)
    except cl.CmuxError as exc:
        raise DriverError(f"cmux refused to rename {ref}: {exc}") from exc
    return [f"{ref} is now named {title!r}"]


def _ref(req: dict, key: str, what: str) -> str:
    value = req.get(key)
    if not isinstance(value, str) or not value.strip():
        raise DriverError(f"{what} needs a {key} ref")
    return value


def move_tab(req: dict) -> list[str]:
    """One tab into another workspace, unfocused. A tab that is the last one of its workspace stays (cmux
    would drop the emptied workspace): an ERROR line, nothing moved. Refs cmux does not show are errors."""
    tab, ws = _ref(req, "tab", "move_tab"), _ref(req, "workspace", "move_tab")
    index = req.get("index")
    if index is not None and (isinstance(index, bool) or not isinstance(index, int) or not 0 <= index <= INDEX_MAX):
        raise DriverError(f"move_tab index must be 0 to {INDEX_MAX}")
    tree = read_tree()
    counts, homes = surface_counts(tree), surface_homes(tree)
    src = homes.get(tab)
    if src is None:
        raise DriverError(f"no open tab {tab}")
    if ws not in counts:
        raise DriverError(f"no open workspace {ws}")
    if src == ws:
        return [f"{tab} is in {ws} already"]
    if counts.get(src, 0) <= 1:
        return [f"ERROR {tab} is the last tab of {src}, moving it would close that workspace"]
    args = ["move-surface", "--surface", tab, "--workspace", ws, "--focus", "false"]
    if index is not None:
        args += ["--index", str(index)]
    cl.cmux_checked(*args)
    return [f"moved {tab} into {ws}"]


def set_color(req: dict) -> list[str]:
    ws = _ref(req, "workspace", "set_color")
    color = req.get("color")
    if color is None:
        cl.cmux_checked("workspace-action", "--workspace", ws, "--action", "clear-color")
        return [f"{ws} has no colour now"]
    if color not in PALETTE:
        raise DriverError(f"set_color takes one of {', '.join(PALETTE)} or null")
    cl.cmux_checked("workspace-action", "--workspace", ws, "--action", "set-color", "--color", PALETTE[color])
    return [f"{ws} is {color} now"]


def set_description(req: dict) -> list[str]:
    ws = _ref(req, "workspace", "set_description")
    text = req.get("text")
    if text is None:
        cl.cmux_checked("workspace-action", "--workspace", ws, "--action", "clear-description")
        return [f"{ws} has no description now"]
    if not isinstance(text, str) or not text.strip():
        raise DriverError("set_description needs a text or null")
    cl.cmux_checked("workspace-action", "--workspace", ws, "--action", "set-description", "--description", text)
    return [f"{ws} has a new description"]


# ---------------------------------------------------------------- workspaces, read only

STATUS_ATTR = re.compile(r"\s+(icon|color|priority|work|url)=(\S+)$")


def parse_sidebar(text: str) -> dict:
    """`cmux sidebar-state` (key=value lines, status entries indented): branch, dirty, PR and the
    status entries with their text and colour."""
    out: dict = {"branch": None, "dirty": False, "pr": None, "statuses": []}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.strip().split("=", 1)
        if line.startswith((" ", "\t")):
            attrs = {}
            while (m := STATUS_ATTR.search(value)):
                attrs[m.group(1)] = m.group(2)
                value = value[:m.start()]
            out["statuses"].append({"name": key, "text": value.strip()[:200], "color": attrs.get("color")})
        elif key == "git_branch" and value and value != "none":
            branch, _, flag = value.partition(" ")
            out["branch"], out["dirty"] = branch, flag.strip() == "dirty"
        elif key == "pr" and value and value != "none":
            out["pr"] = value[:120]
    return out


def workspaces() -> list[dict]:
    """The workspaces of the current window as the cmux sidebar shows them. A workspace whose
    sidebar cannot be read still shows, with its name; a list that cannot be read is an error."""
    try:
        data = json.loads(cl.cmux_checked("--json", "workspace", "list"))
    except ValueError as exc:
        raise DriverError(f"cmux workspace list is not JSON ({exc})") from exc
    rows = data.get("workspaces") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise DriverError("cmux workspace list has no workspaces")
    unread: dict[str, int] = {}
    try:
        notes = json.loads(cl.cmux_checked("--json", "list-notifications") or "[]")
        for n in notes if isinstance(notes, list) else []:
            if isinstance(n, dict) and n.get("is_read") is False and isinstance(n.get("workspace_id"), str):
                unread[n["workspace_id"]] = unread.get(n["workspace_id"], 0) + 1
    except (cl.CmuxError, ValueError):
        pass
    out = []
    for w in rows:
        if not isinstance(w, dict) or not isinstance(w.get("ref"), str):
            continue
        try:
            side = parse_sidebar(cl.cmux_checked("sidebar-state", "--workspace", w["ref"]))
        except cl.CmuxError:
            side = parse_sidebar("")

        def text(key: str, cap: int = 300) -> str | None:
            v = w.get(key)
            return v.strip()[:cap] if isinstance(v, str) and v.strip() else None

        latest = text("latest_submitted_message", 500)
        color = text("custom_color", 20)
        out.append({"ref": w["ref"], "id": text("id", 80), "title": text("title", 120) or w["ref"],
                    "color": color, "color_name": PALETTE_BY_HEX.get(color.upper()) if color else None,
                    "description": text("description"),
                    "pinned": w.get("pinned") is True, "selected": w.get("selected") is True,
                    "cwd": text("current_directory", 500), "branch": side["branch"], "dirty": side["dirty"],
                    "pr": side["pr"], "unread": unread.get(w.get("id") or "", 0),
                    "latest": {"text": latest, "at": text("latest_submitted_at", 40)} if latest else None,
                    "statuses": side["statuses"][:6]})
    return out


# the cockpit steers a tab with these (docs/workplace.md, the optional verbs); cmux serves them all
CAPS = ["tabs", "sessions", "open", "launch", "send", "rename", "control", "focus", "key", "keys", "screen", "close",
        "workspaces", "rename_workspace", "move_tab", "set_color", "set_description",
        "new_tab", "new_workspace", "close_workspace"]
# the one key set a driver takes; cmux's own names for the two that are not typed as they are
KEYS = {"enter": "Enter", "escape": "escape", "y": "y", "n": "n", **{str(i): str(i) for i in range(1, 10)}}


def _where(surface: str) -> list[str]:
    ws_ref = _ws_ref_of(surface)
    return ["--workspace", ws_ref] if ws_ref else []


def focus(req: dict) -> list[str]:
    surface = req["tab"]
    where = _where(surface)
    if where:
        cl.cmux_checked("select-workspace", *where)
    cl.cmux_checked("focus-panel", "--panel", surface, *where)
    return [f"{surface} in front"]


def key(req: dict) -> list[str]:
    surface, name = req["tab"], req.get("key")
    if name not in KEYS:
        raise ValueError(f"key {name!r} is not one of {', '.join(KEYS)}")
    cl.cmux_checked("send-key", *_where(surface), "--surface", surface, KEYS[name])
    return [f"{name} into {surface}"]


# the keys of a live terminal, under the names cmux takes (workplace.py TERM_KEYS)
TERM_KEYS = ("enter", "escape", "tab", "shift+tab", "backspace", "delete", "up", "down", "left", "right", "home", "end",
             "pageup", "pagedown", *(f"ctrl+{c}" for c in "abcdefghijklmnopqrstuvwxyz"))


def keys(req: dict) -> list[str]:
    """A keyboard, in order. --force on every step: without it cmux refuses a prompt that holds text or an open
    dialog, and typing is what fills a prompt and answers a dialog. Text with a backslash takes the paste path,
    since `cmux send` reads a typed backslash and n as Enter."""
    surface = req["tab"]
    where = [*_where(surface), "--surface", surface]
    steps = req.get("keys") or []
    for step in steps:
        if "key" in step:
            if step["key"] not in TERM_KEYS:
                raise ValueError(f"key {step['key']!r} is not one of {', '.join(TERM_KEYS)}")
            cl.cmux_checked("send-key", "--force", *where, step["key"])
        elif "paste" in step or "\\" in step["text"]:
            cl.cmux_checked("send", "--paste", "--force", *where, "--", step.get("paste", step.get("text")))
        else:
            cl.cmux_checked("send", "--force", *where, "--", step["text"])
    return [f"{len(steps)} steps into {surface}"]


def screen(req: dict) -> str:
    surface = req["tab"]
    lines = max(1, min(int(req.get("lines") or 40), 500))
    out = cl.cmux_checked("read-screen", *_where(surface), "--surface", surface, "--lines", str(lines))
    return "\n".join(line.rstrip() for line in out.splitlines()).strip("\n")


def close(req: dict) -> list[str]:
    surface = req["tab"]
    # --force: cmux (0.65+) refuses a surface with a live process, and a waiting agent is one;
    # the caller already decided (workplace.py close runs only when asked, the cockpit only on settled tabs)
    cl.cmux_checked("close-surface", "--surface", surface, "--force", *_where(surface))
    return [f"{surface} closed"]


def handle(req: dict) -> dict:
    if cl.cmux_bin() is None:
        raise DriverError("cmux is not installed (no CMUX_BIN, no `cmux` on PATH, no app bundle)")
    verb = req.get("verb")
    if verb == "tabs":
        return {"tabs": tabs()}
    if verb == "sessions":
        return {"sessions": sessions()}
    if verb == "workspaces":
        return {"workspaces": workspaces()}
    if verb == "open":
        return {"report": open_plan(req)}
    if verb == "launch":
        return {"report": launch(req)}
    if verb == "send":
        return {"report": send(req)}
    if verb == "rename":
        return {"report": rename(req)}
    if verb == "rename_workspace":
        return {"report": rename_workspace(req)}
    if verb == "move_tab":
        return {"report": move_tab(req)}
    if verb == "set_color":
        return {"report": set_color(req)}
    if verb == "set_description":
        return {"report": set_description(req)}
    if verb == "new_tab":
        return new_tab(req)
    if verb == "new_workspace":
        return new_workspace(req)
    if verb == "close_workspace":
        return {"report": close_workspace(req)}
    if verb == "control":
        return {"report": control(req)}
    if verb == "caps":
        return {"caps": CAPS}
    if verb == "focus":
        return {"report": focus(req)}
    if verb == "key":
        return {"report": key(req)}
    if verb == "keys":
        return {"report": keys(req)}
    if verb == "screen":
        return {"text": screen(req)}
    if verb == "close":
        return {"report": close(req)}
    raise ValueError(f"unknown verb {verb!r}")


def main() -> int:
    try:
        req = json.loads(sys.stdin.read() or "{}")
        if not isinstance(req, dict):
            raise ValueError("request is not a JSON object")
        answer = handle(req)
    except (DriverError, cl.CmuxError, ValueError, KeyError) as exc:
        message = f"cmux_driver: {exc}"
        print(json.dumps({"error": message}))
        print(message, file=sys.stderr)
        return 1
    print(json.dumps(answer, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
