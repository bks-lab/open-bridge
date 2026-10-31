# SPDX-License-Identifier: MIT
"""The Workspaces area of the settings page: every area with its rules and a switch.

An area comes from workplace.workspaces, its rules from workflow/workspaces/<id>.yaml (read through the engine,
scripts/workspace.py, on every state, so an edited file shows at once). The switches are kept in
.bridge/cockpit/workspaces.json, so the page never writes bridge-config.yaml and a click makes no commit.

Two switches. Shown takes an area out of the bar, the chips and the shelf, it stays in the picker. Active is the
stronger one: a resting workspace leaves the picker too and its rules no longer hold. Neither deletes anything or stops
a background run, and the line All still counts them. An archived workspace rests, and a child rests with its parent.

Delete takes any area but the default: its file through the engine, then its entry out of bridge-config.yaml, a copy of
both under .bridge/trash/. Tasks and records stay, a task falls to the default area.
"""
from __future__ import annotations

import json
import os
import sys
import threading
from dataclasses import replace
from pathlib import Path
from typing import Any

import workspace as engine  # scripts/ is on the path of the cockpit
from lib import work_find

FILE = "workspaces.json"


def key_of(name: Any) -> str:
    return str(name or "").strip().lower()


class Workspaces:
    def __init__(self, app: Any):
        self.app = app
        self.path = Path(app.state_dir) / FILE
        self.lock = threading.Lock()
        self.rev = 0
        self.off, self.inactive = self._load()
        self.gone: list[str] = []          # deleted since the start: a page keeps the boot's list of areas until it loads again

    def _load(self) -> tuple[list[str], list[str]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return [], []
        names = lambda k: [n for n in data.get(k) or [] if isinstance(n, str)] if isinstance(data, dict) else []
        return names("off"), names("inactive")

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"off": self.off, "inactive": self.inactive}, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    def areas(self) -> list[str]:
        return list(self.app.cfg.areas)

    def rows(self) -> list[dict]:
        """The effective definitions, a broken file among them never takes the page down"""
        try:
            defs = engine.Consumer(str(self.app.root)).all_definitions()
            return [engine.effective(defs, k) for k in sorted(defs)]
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            self.app.log_error(f"workspaces: {exc!r}")
            return []

    def state(self) -> dict:
        rows = self.rows()
        by_area: dict[str, dict] = {}
        for row in rows:
            # a child without an area of its own stands under its parent's: the area belongs to the parent
            if row.get("area") and "area" not in row["inherited"]:
                by_area.setdefault(key_of(row["area"]), row)
        by_id = {r["id"]: r for r in rows}
        with self.lock:
            hidden, resting = {key_of(n) for n in self.off}, {key_of(n) for n in self.inactive}
            gone = list(self.gone)
        names = self.areas()
        fixed = key_of(getattr(self.app.cfg, "area_default", None))
        items = [self._item(n, by_area.get(key_of(n)), hidden, resting, by_id, fixed) for n in names]
        known = {key_of(n) for n in names}
        placed = {i["id"] for i in items}
        items += [self._item(None, r, hidden, resting, by_id, fixed) for r in rows
                  if r["id"] not in placed and key_of(r.get("area")) not in known]
        asleep = [i for i in items if not i["active"] or i["active_held_by"]]
        return {"rev": self.rev, "inactive": [i["key"] for i in asleep], "gone": gone,
                "off": [*(i["area"] for i in items if i["area"] and (not i["on"] or i["held_by"] or i in asleep)), *gone],
                "items": items}

    def _item(self, area: str | None, row: dict | None, hidden: set, resting: set, by_id: dict, fixed: str) -> dict:
        row = row or {}
        above = by_id.get(row.get("parent")) or {}
        name = above.get("area") or above.get("title")
        above_rests = bool(above) and (above.get("archived") or key_of(above.get("area") or above.get("id")) in resting)
        held = name if above and (above_rests or key_of(above.get("area")) in hidden) else None
        key = area or row.get("id")
        return {"key": key, "area": area, "id": row.get("id"), "title": row.get("title") or area, "parent": row.get("parent"),
                "children": row.get("children") or [], "archived": bool(row.get("archived")),
                "level": (row.get("boundary") or {}).get("level"), "style": (row.get("writing") or {}).get("style_skill"),
                "mail": (row.get("writing") or {}).get("mail_profile"), "persona": (row.get("refs") or {}).get("persona"),
                "calendars": (row.get("sources") or {}).get("calendars"), "cost_center": (row.get("sources") or {}).get("cost_center"),
                "on": key_of(area) not in hidden, "held_by": held, "fixed": bool(area) and key_of(area) == fixed,
                "active": key_of(key) not in resting and not row.get("archived"), "active_held_by": name if above_rests else None}

    def find(self, key: str) -> dict | None:
        return next((i for i in self.state()["items"] if key_of(i["key"]) == key_of(key)), None)

    def _mark(self, names: list[str], key: str, on: bool) -> list[str]:
        kept = [n for n in names if key_of(n) != key_of(key)]
        return kept if on else [*kept, key]

    def switch(self, area: str, on: bool) -> bool:
        """Shown or not. False: no such area. The name is kept as the config spells it."""
        name = next((n for n in self.areas() if key_of(n) == key_of(area)), None)
        if name is None:
            return False
        with self.lock:
            self.off = self._mark(self.off, name, on)
            self.rev += 1
            self._save()
        return True

    def activate(self, key: str, on: bool) -> dict | None:
        """Active or resting; the item as it stood, None: no such one"""
        item = self.find(key)
        if item is None:
            return None
        with self.lock:
            self.inactive = self._mark(self.inactive, item["key"], on)
            self.rev += 1
            self._save()
        return item

    def forget(self, key: str) -> None:
        """A deleted area leaves the switches, the config it was read from has changed"""
        with self.lock:
            self.off, self.inactive = self._mark(self.off, key, True), self._mark(self.inactive, key, True)
            self.gone.append(key)
            self._save()
        cfg = self.app.cfg
        self.app.cfg = replace(cfg, areas=tuple(n for n in cfg.areas if key_of(n) != key_of(key)))

    def plan(self, item: dict) -> dict:
        """What a delete touches and what stops it, before anyone clicks"""
        key = key_of(item["area"])
        tabs = [t for t in self.app.tabs.tab_list() if key and key_of(t.get("workspace")) == key]
        rows = [r for r in work_find.records(self.app.root)["records"] if key and key_of(r.get("area")) == key]
        records = sum(1 for r in rows if r["kind"] == "done")
        blockers = [*(["tabs"] if tabs else []), *(["children"] if item["children"] else []), *(["fixed"] if item["fixed"] else [])]
        return {"key": item["key"], "tasks": len(rows) - records, "records": records, "tabs": len(tabs),
                "children": item["children"], "fixed": item["fixed"], "blockers": blockers}

    def changed(self) -> dict:
        with self.lock:
            self.rev += 1
        state = self.state()
        self.app.broadcast("workspaces", state)
        return state

    def command(self, verb: str, slug: str) -> list[str]:
        return [sys.executable, self.app.runner.script("scripts/workspace.py"), "--repo-root", str(self.app.root), verb, slug]
