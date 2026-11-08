# SPDX-License-Identifier: MIT
"""The area On this machine of the settings page: every page of the briefing profile and its sections, each with a
switch, kept for this machine only.

Not every machine needs every page: a lab page, a job tracker or a CI monitor matters on one computer and is noise on
another. The switches are kept in .bridge/cockpit/views.json, so the page never writes the profile and a click makes no
commit. Every collect of the cockpit passes them on (`briefing.py collect --skip-page/--skip-section`): a section switched
off is not run at all and stands nowhere; a page switched off has no tab and no place in its folder, and its sections run
only while a page still on names them. An id the profile no longer has is kept and changes nothing. The terminal
/briefing never reads this file.

The list itself (`catalog`) is what the last collect said the profile holds (`page_catalog`), switched off or not, so
a page can come back on.
"""
from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any

FILE = "views.json"
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}\Z")       # actions_base.PAGE_ID_RE: a page or a section id
KINDS = ("page", "section")
MAX_PAGES, MAX_SECTIONS, MAX_KEPT = 60, 40, 400


def _ids(value: Any) -> list[str]:
    return list(dict.fromkeys(x for x in value if isinstance(x, str) and ID_RE.match(x)))[:MAX_KEPT] \
        if isinstance(value, list) else []


def _text(value: Any, cap: int = 120) -> str:
    return value.strip()[:cap] if isinstance(value, str) else ""


def catalog_of(raw: Any) -> list[dict] | None:
    """The pages a collect listed (briefing_view.page_catalog), in a shape the page can trust; None: not a list"""
    if not isinstance(raw, list):
        return None
    out = []
    for p in raw[:MAX_PAGES]:
        if not isinstance(p, dict) or not isinstance(p.get("id"), str) or not ID_RE.match(p["id"]):
            continue
        secs = [{"id": s["id"], "title": _text(s.get("title")) or s["id"], "kind": _text(s.get("kind"), 20)}
                for s in (p.get("sections") if isinstance(p.get("sections"), list) else [])[:MAX_SECTIONS]
                if isinstance(s, dict) and isinstance(s.get("id"), str) and ID_RE.match(s["id"])]
        under = p.get("under") if isinstance(p.get("under"), str) and ID_RE.match(p["under"]) else None
        out.append({"id": p["id"], "title": _text(p.get("title")) or p["id"], "group": _text(p.get("group"), 20) or "main",
                    "under": under, "sections": secs})
    return out


class Views:
    def __init__(self, app: Any):
        self.app = app
        self.path = Path(app.state_dir) / FILE
        self.lock = threading.Lock()
        self.rev = 0
        self.pages_off, self.sections_off = self._load()
        self.catalog: list[dict] = []

    def _load(self) -> tuple[list[str], list[str]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return [], []
        if not isinstance(data, dict):
            return [], []
        return _ids(data.get("pages_off")), _ids(data.get("sections_off"))

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"pages_off": self.pages_off, "sections_off": self.sections_off}, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(tmp, self.path)

    def argv(self) -> list[str]:
        """What a collect adds: every id switched off, the ones the profile no longer has among them (they change nothing)"""
        with self.lock:
            return [*(a for x in self.pages_off for a in ("--skip-page", x)),
                    *(a for x in self.sections_off for a in ("--skip-section", x))]

    def state(self) -> dict:
        with self.lock:
            return {"rev": self.rev, "pages_off": list(self.pages_off), "sections_off": list(self.sections_off),
                    "catalog": [dict(p) for p in self.catalog]}

    def switch(self, kind: str, ident: str, on: bool) -> None:
        with self.lock:
            field = "pages_off" if kind == "page" else "sections_off"
            kept = [x for x in getattr(self, field) if x != ident]
            setattr(self, field, kept if on else [*kept, ident])
            self.rev += 1
            self._save()

    def learn(self, raw: Any) -> bool:
        """The catalog of a collect; True when it changed (the page gets the new list)"""
        found = catalog_of(raw)
        if found is None:
            return False
        with self.lock:
            if found == self.catalog:
                return False
            self.catalog = found
            self.rev += 1
        return True

    def changed(self) -> dict:
        state = self.state()
        self.app.broadcast("views", state)
        return state
