# SPDX-License-Identifier: MIT
"""The Workspaces area of the settings page: every area with its rules and a switch.

An area comes from workplace.workspaces, its rules from workflow/workspaces/<id>.yaml (read through the engine,
scripts/workspace.py, on every state, so an edited file shows at once). The switches are kept in
.bridge/cockpit/workspaces.json, so the page never writes bridge-config.yaml and a click makes no commit.

Off takes an area out of the bar, the chips and the shelf. Nothing is deleted, nothing stops running, and the line
All still counts it. An archived workspace counts as off, and so does the child of one that is off.
"""
from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path
from typing import Any

import workspace as engine  # scripts/ is on the path of the cockpit

FILE = "workspaces.json"


def key_of(name: Any) -> str:
    return str(name or "").strip().lower()


class Workspaces:
    def __init__(self, app: Any):
        self.app = app
        self.path = Path(app.state_dir) / FILE
        self.lock = threading.Lock()
        self.rev = 0
        self.off = self._load()

    def _load(self) -> list[str]:
        try:
            names = json.loads(self.path.read_text(encoding="utf-8")).get("off")
        except (OSError, ValueError, AttributeError):
            return []
        return [n for n in names if isinstance(n, str)] if isinstance(names, list) else []

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"off": self.off}, ensure_ascii=False), encoding="utf-8")
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
            off = {key_of(n) for n in self.off}
        items = []
        names = self.areas()
        for name in names:
            items.append(self._item(name, by_area.get(key_of(name)), off, by_id))
        known = {key_of(n) for n in names}
        placed = {i["id"] for i in items}
        items += [self._item(None, r, off, by_id) for r in rows if r["id"] not in placed and key_of(r.get("area")) not in known]
        return {"rev": self.rev, "off": [i["area"] for i in items if i["area"] and (not i["on"] or i["held_by"] or i["archived"])],
                "items": items}

    def _item(self, area: str | None, row: dict | None, off: set, by_id: dict) -> dict:
        row = row or {}
        above = by_id.get(row.get("parent")) or {}
        above_area = above.get("area")
        held = above_area if above_area and (key_of(above_area) in off or above.get("archived")) else None
        return {"area": area, "id": row.get("id"), "title": row.get("title") or area, "parent": row.get("parent"),
                "children": row.get("children") or [], "archived": bool(row.get("archived")),
                "level": (row.get("boundary") or {}).get("level"), "style": (row.get("writing") or {}).get("style_skill"),
                "mail": (row.get("writing") or {}).get("mail_profile"), "persona": (row.get("refs") or {}).get("persona"),
                "on": key_of(area) not in off, "held_by": held}

    def switch(self, area: str, on: bool) -> bool:
        """False: no such area. The name is kept as the config spells it."""
        name = next((n for n in self.areas() if key_of(n) == key_of(area)), None)
        if name is None:
            return False
        with self.lock:
            kept = [n for n in self.off if key_of(n) != key_of(name)]
            self.off = kept if on else [*kept, name]
            self.rev += 1
            self._save()
        return True

    def area_of(self, slug: str) -> str | None:
        return next((r.get("area") for r in self.rows() if r["id"] == slug), None)

    def changed(self) -> dict:
        with self.lock:
            self.rev += 1
        state = self.state()
        self.app.broadcast("workspaces", state)
        return state

    def command(self, verb: str, slug: str) -> list[str]:
        return [sys.executable, self.app.runner.script("scripts/workspace.py"), "--repo-root", str(self.app.root), verb, slug]
