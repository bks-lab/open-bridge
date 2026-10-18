# SPDX-License-Identifier: MIT
"""Organize with AI: one model call proposes tidier names, tab moves, colours and descriptions for the
workspaces of THIS Bridge; nothing changes until a person ticks items and applies them (actions.py
organize_propose, organize_apply).

Scope: only workspaces whose folder lies in this Bridge or a repo it registers (ecosystem*.yaml), by the
longest folder that matches, so a workspace in a sibling Bridge's clone stays out; only the tabs in
those workspaces; never the control tab or the control workspace. The model sees titles, slugs, states,
90 characters of a tab's last line, 200 of its question and two folder names of the workspace, all
scrubbed; no full screen, no home path, no token.

One call, no tools, no session, no settings (argv / argv_ok, the only shape the runner lets through).
The answer is checked item by item (items): unknown, control and out-of-scope refs, no-ops, task tabs,
configured workspaces, managed or used names, the last tab of a workspace and verbs the driver does not
serve are dropped. A proposal lives in memory for TTL_MS (Proposals), one at a time.
"""
from __future__ import annotations

import json
import os
import re
import threading
import uuid
from pathlib import Path
from typing import Any

from .quick import MODELS
from .text import TABLES

SERVICE = "cockpit-organize"
DEFAULT_MODEL = "haiku"
ORGANIZE_TIMEOUT = 90
APPLY_BUDGET_S = 120
TTL_MS = 15 * 60 * 1000
MAX_WORKSPACES = 30
MAX_TABS = 80
MAX_ITEMS = 40
LAST_MAX = 90
ASK_MAX = 200
WHY_MAX = 160
TITLE_MAX = 80
DESCRIPTION_MAX = 120
PROMPT_MAX = 24000
SYSTEM_MAX = 4000
KINDS = ("ws_title", "ws_color", "ws_description", "tab_title", "tab_move")
# the order apply runs them in: moves first (they count tabs), names, then the decoration
APPLY_ORDER = ("tab_move", "tab_title", "ws_title", "ws_description", "ws_color")
CAPS = {"ws_title": "rename_workspace", "ws_color": "set_color", "ws_description": "set_description",
        "tab_title": "rename", "tab_move": "move_tab"}
ID_RE = re.compile(r"^o[0-9a-f]{10}\Z")
ITEM_ID_RE = re.compile(r"^[a-z_]{1,20}:[A-Za-z0-9$%@:._/-]{1,64}\Z")
BAD_CHARS = re.compile(r"[\x00-\x1f\x7f]")
# the portable workspace colours (workplace.py COLORS, the cmux driver's PALETTE: the same map)
COLORS = {
    "Red": "#C0392B", "Crimson": "#922B21", "Orange": "#A04000", "Amber": "#7D6608",
    "Olive": "#4A5C18", "Green": "#196F3D", "Teal": "#006B6B", "Aqua": "#0E6B8C",
    "Blue": "#1565C0", "Navy": "#1A5276", "Indigo": "#283593", "Purple": "#6A1B9A",
    "Magenta": "#AD1457", "Rose": "#880E4F", "Brown": "#7B3F00", "Charcoal": "#3E4B5E",
}
_BY_HEX = {v.upper(): k for k, v in COLORS.items()}


def color_name(color: Any) -> str | None:
    """The palette name of a reported hex, else None"""
    return _BY_HEX.get(color.strip().upper()) if isinstance(color, str) else None


def palette_name(name: Any) -> str | None:
    if not isinstance(name, str):
        return None
    return next((k for k in COLORS if k.casefold() == name.strip().casefold()), None)


def fold(name: Any) -> str:
    """A workspace name as the workplace compares it (workplace.py _ws_fold)"""
    return re.sub(r"[:.]", "_", str(name or "").strip()).casefold()


# ---------------------------------------------------------------- scope

def _real(path: Any) -> str | None:
    if not isinstance(path, str) or not path.strip():
        return None
    return os.path.realpath(os.path.expanduser(path))


def repo_paths(root: Path) -> list[str]:
    """The folders of the repos this Bridge registers (ecosystem*.yaml): `local_path`, else `local_root` of
    that file plus the repo's name from `github`; only folders that exist"""
    import yaml
    out: list[str] = []
    for path in sorted(Path(root).glob("ecosystem*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(data, dict):
            continue
        base = data.get("local_root") if isinstance(data.get("local_root"), str) else None

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                local = node.get("local_path")
                gh = node.get("github")
                if isinstance(local, str) and local.strip():
                    out.append(os.path.expanduser(local.strip()))
                elif base and isinstance(gh, str) and "/" in gh:
                    out.append(os.path.join(os.path.expanduser(base), gh.rsplit("/", 1)[1]))
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)
        walk(data)
    return [r for r in dict.fromkeys(_real(p) for p in out) if r and os.path.isdir(r)]


def scope_test(root: Path, bridges: list[dict]):
    """A function cwd -> True when the longest folder it lies in is this Bridge or one of its repos"""
    mine = [p for p in [_real(str(root)), *repo_paths(root)] if p]
    others = [p for p in (_real(b.get("path")) for b in bridges or []) if p]
    places = [(p, True) for p in mine] + [(p, False) for p in others]

    def inside(cwd: Any) -> bool:
        real = _real(cwd)
        if not real:
            return False
        hits = [(p, ours) for p, ours in places if real == p or real.startswith(p.rstrip("/") + "/")]
        if not hits:
            return False
        return max(hits, key=lambda h: (len(h[0]), h[1]))[1]
    return inside


def short_cwd(cwd: Any) -> str:
    """Home-relative, the last two folder names only: never a full path"""
    if not isinstance(cwd, str) or not cwd.strip():
        return ""
    path = cwd.strip()
    home = os.path.expanduser("~")
    if home and (path == home or path.startswith(home.rstrip("/") + "/")):
        path = path[len(home):]
    parts = [p for p in path.split("/") if p]
    return "/".join(parts[-2:])


def _text(value: Any, cap: int, scrub) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return scrub(text)[:cap]


# ---------------------------------------------------------------- the snapshot

def gather(app: Any) -> dict:
    """What the model sees and what apply compares with: the workspaces of this Bridge and their tabs.
    `base` keeps per ref the values the items start from (internal, never sent)."""
    scrub = app.scrub
    state = app.tabs_state()
    tabs = [t for t in state.get("tabs") or [] if isinstance(t, dict)]
    listed = app.tabs.workspace_list() or []
    control_ref = app.tabs.control_ref()
    control_name = fold(getattr(app.cfg, "control", None) or "")
    control_ws = {t.get("ws_ref") for t in tabs if control_ref and t.get("ref") == control_ref and t.get("ws_ref")}
    inside = scope_test(app.root, app.bridges.state() if getattr(app, "bridges", None) else [])
    spaces, base_ws = [], {}
    for w in listed:
        ref = w.get("ref")
        if not isinstance(ref, str) or ref in control_ws or (control_name and fold(w.get("title")) == control_name):
            continue
        if not inside(w.get("cwd_real") or w.get("cwd")):
            continue
        if len(spaces) >= MAX_WORKSPACES:
            break
        title = str(w.get("title") or "")
        cname = w.get("color_name") if w.get("color_name") in COLORS else color_name(w.get("color"))
        desc = w.get("description") if isinstance(w.get("description"), str) and w.get("description").strip() else None
        spaces.append({"ref": ref, "title": _text(title, TITLE_MAX + 40, scrub), "color_name": cname,
                       "description": _text(desc, DESCRIPTION_MAX + 80, scrub) if desc else None,
                       "pinned": w.get("pinned") is True, "cwd": _text(short_cwd(w.get("cwd")), 120, scrub)})
        base_ws[ref] = {"title": title, "color_name": cname, "color": w.get("color") or None, "description": desc}
    out_tabs, base_tab = [], {}
    for t in tabs:
        ref = t.get("ref")
        if not isinstance(ref, str) or ref == control_ref or t.get("is_control") or t.get("ws_ref") not in base_ws:
            continue
        if len(out_tabs) >= MAX_TABS:
            break
        bound = bool(t.get("slug") or t.get("item") or t.get("team"))
        ask = t.get("ask") if isinstance(t.get("ask"), dict) else None
        out_tabs.append({"ref": ref, "title": _text(t.get("name"), TITLE_MAX + 40, scrub), "workspace": t["ws_ref"],
                         "state": t.get("state"), "slug": t.get("slug") or None, "task_bound": bound,
                         "last": _text(t.get("last"), LAST_MAX, scrub),
                         "ask": _text(ask.get("text"), ASK_MAX, scrub) if ask else None})
        base_tab[ref] = {"title": str(t.get("name") or ""), "workspace": t["ws_ref"], "bound": bound,
                         "state": t.get("state"), "state_source": t.get("state_source")}
    # every name in use, also outside the scope: a new name must not take one of them
    used_tabs = {str(t.get("name") or "").strip().casefold(): t.get("ref") for t in tabs if t.get("name")}
    used_ws = {fold(w.get("title")): w.get("ref") for w in listed if w.get("title")}
    used_ws.update({fold(t.get("workspace")): t.get("ws_ref") for t in tabs if t.get("workspace")})
    live = {}
    for t in tabs:
        if t.get("ws_ref"):
            live[t["ws_ref"]] = live.get(t["ws_ref"], 0) + 1
    return {"workspaces": spaces, "tabs": out_tabs,
            "base": {"ws": base_ws, "tab": base_tab, "used_tabs": used_tabs, "used_ws": used_ws, "count": live}}


def prompt(snapshot: dict, lang: str) -> tuple[str, str]:
    """(system text, prompt): the instruction, and the snapshot as JSON labelled as data"""
    tx = TABLES["de" if isinstance(lang, str) and lang.lower().startswith("de") else "en"]
    data = json.dumps({"workspaces": snapshot["workspaces"], "tabs": snapshot["tabs"]}, ensure_ascii=False,
                      separators=(",", ":"))
    return tx["organize_system"], f"{tx['organize_data']}\n{data}"


def argv(claude: str, model: str, system: str, text: str) -> list[str]:
    return [claude, "-p", "--model", model, "--output-format", "json", "--no-session-persistence",
            "--setting-sources", "", "--tools", "", "--append-system-prompt", system, "--", text]


def argv_ok(argv_: list[str], claude: str | None) -> bool:
    """The one shape an organize call has: a full model id, no tools, no settings, no session, JSON out"""
    if not claude or len(argv_) != 15:
        return False
    shape = argv(claude, argv_[3], argv_[12], argv_[14])
    return (argv_ == shape and argv_[3] in MODELS.values()
            and isinstance(argv_[12], str) and 0 < len(argv_[12]) <= SYSTEM_MAX
            and isinstance(argv_[14], str) and 0 < len(argv_[14]) <= PROMPT_MAX)


def parse(out: str) -> dict:
    """The model's answer from the claude -p JSON envelope (its `result`) or bare: {workspaces, tabs}"""
    from .actions import ActionError
    unreadable = ActionError(502, "organize_unreadable", "the model's answer cannot be read")
    text = out or ""
    try:
        env = json.loads(text)
    except ValueError:
        env = None
    if isinstance(env, dict) and "result" in env:
        if env.get("is_error") or not isinstance(env.get("result"), str):
            raise unreadable
        text = env["result"]
    elif isinstance(env, dict) and ("workspaces" in env or "tabs" in env):
        text = json.dumps(env)
    start, end = text.find("{"), text.rfind("}")
    if not 0 <= start < end:
        raise unreadable
    try:
        answer = json.loads(text[start:end + 1])
    except ValueError:
        raise unreadable from None
    if not isinstance(answer, dict) or not ({"workspaces", "tabs"} & set(answer)):
        raise unreadable
    ws, tabs = answer.get("workspaces", []), answer.get("tabs", [])
    if not isinstance(ws, list) or not isinstance(tabs, list):
        raise unreadable
    return {"workspaces": [w for w in ws if isinstance(w, dict)], "tabs": [t for t in tabs if isinstance(t, dict)]}


# ---------------------------------------------------------------- the items

def _title(value: Any) -> str | None:
    if not isinstance(value, str) or BAD_CHARS.search(value):
        return None
    text = value.strip()
    return text if 1 <= len(text) <= TITLE_MAX else None


def _description(value: Any) -> str | None:
    if not isinstance(value, str) or BAD_CHARS.search(value):
        return None
    text = value.strip()
    return text if 1 <= len(text) <= DESCRIPTION_MAX else None


def items(answer: dict, snapshot: dict, caps, managed: dict, scrub=lambda s: s) -> list[dict]:
    """The model's answer as checked items {id, kind, ref, from, to, why, cap}; anything that is not safe
    to offer is left out (module docstring)"""
    base = snapshot["base"]
    caps = set(caps or [])
    tab_names = {n.casefold() for n in managed.get("tab_names") or set()}
    ws_names = {fold(n) for n in managed.get("workspace_names") or set()}
    used_tabs = dict(base["used_tabs"])
    used_ws = dict(base["used_ws"])
    count = dict(base["count"])
    out: list[dict] = []
    seen: set[str] = set()

    def add(kind: str, ref: str, old, new, why) -> None:
        iid = f"{kind}:{ref}"
        if iid in seen or CAPS[kind] not in caps or not ITEM_ID_RE.match(iid) or len(out) >= MAX_ITEMS:
            return
        seen.add(iid)
        out.append({"id": iid, "kind": kind, "ref": ref, "from": old, "to": new,
                    "why": _text(why if isinstance(why, str) else "", WHY_MAX, scrub), "cap": CAPS[kind]})

    for w in answer.get("workspaces") or []:
        ref = w.get("ref")
        cur = base["ws"].get(ref) if isinstance(ref, str) else None
        if cur is None or fold(cur["title"]) in ws_names:
            continue          # unknown, out of scope, control, or configured (the plan sets these again)
        why = w.get("why")
        if "title" in w:
            new = _title(w.get("title"))
            if (new and new != cur["title"] and fold(new) not in ws_names
                    and used_ws.get(fold(new), ref) == ref and f"ws_title:{ref}" not in seen):
                add("ws_title", ref, cur["title"], new, why)
                if f"ws_title:{ref}" in seen:
                    used_ws[fold(new)] = ref
        if "color" in w:
            raw = w.get("color")
            new = None if raw is None else palette_name(raw)
            ok = (raw is None and (cur["color"] or cur["color_name"])) or (new is not None and new != cur["color_name"])
            if ok:
                add("ws_color", ref, cur["color_name"], new, why)
        if "description" in w:
            raw = w.get("description")
            new = None if raw is None else _description(raw)
            ok = (raw is None and cur["description"]) or (new is not None and new != cur["description"])
            if ok:
                add("ws_description", ref, cur["description"], new, why)
    for t in answer.get("tabs") or []:
        ref = t.get("ref")
        cur = base["tab"].get(ref) if isinstance(ref, str) else None
        if cur is None or cur["bound"]:
            continue          # unknown, out of scope, control, or a task tab (its name finds it, open moves it back)
        why = t.get("why")
        if "title" in t:
            new = _title(t.get("title"))
            glyph = cur.get("state_source") == "glyph" and cur.get("state") != "shell"
            key = (new or "").casefold()
            if (new and new != cur["title"] and not glyph and key not in tab_names
                    and used_tabs.get(key, ref) == ref and f"tab_title:{ref}" not in seen):
                add("tab_title", ref, cur["title"], new, why)
                if f"tab_title:{ref}" in seen:
                    used_tabs[key] = ref
        if "workspace" in t:
            dest = t.get("workspace")
            src = cur["workspace"]
            if (isinstance(dest, str) and dest in base["ws"] and dest != src and count.get(src, 0) > 1
                    and f"tab_move:{ref}" not in seen and CAPS["tab_move"] in caps):
                add("tab_move", ref, src, dest, why)
                if f"tab_move:{ref}" in seen:
                    count[src] = count.get(src, 0) - 1
                    count[dest] = count.get(dest, 0) + 1
    return out


def managed_names(root: Path) -> dict:
    """workplace.py managed_names for this Bridge, from the workplace module next to this code; an
    unreadable one gives no names (the workplace commands check them again before anything changes)"""
    import importlib.util
    import sys
    path = Path(__file__).resolve().parents[2] / "workplace.py"
    try:
        mod = sys.modules.get("_cockpit_workplace")
        if mod is None:
            spec = importlib.util.spec_from_file_location("_cockpit_workplace", path)
            mod = importlib.util.module_from_spec(spec)
            sys.modules["_cockpit_workplace"] = mod
            spec.loader.exec_module(mod)
        return mod.managed_names(Path(root), mod.load_cfg(Path(root)))
    except Exception:  # noqa: BLE001 - a broken workplace config must not break the cockpit
        return {"tab_names": set(), "workspace_names": set()}


# ---------------------------------------------------------------- proposals in memory

class Proposals:
    """The current proposal (one at a time, TTL_MS) and the single-flight flag of a propose"""

    def __init__(self, clock):
        self.clock = clock
        self.lock = threading.Lock()
        self.current: dict | None = None
        self.running = False

    def begin(self) -> bool:
        with self.lock:
            if self.running:
                return False
            self.running = True
            return True

    def end(self) -> None:
        with self.lock:
            self.running = False

    def put(self, base: dict, found: list[dict]) -> dict:
        prop = {"id": "o" + uuid.uuid4().hex[:10], "at_ms": int(self.clock()), "base": base, "items": found}
        with self.lock:
            self.current = prop
        return prop

    def get(self, pid: str) -> dict | None:
        with self.lock:
            prop = self.current
        if not prop or prop["id"] != pid or self.clock() - prop["at_ms"] > TTL_MS:
            return None
        return prop
