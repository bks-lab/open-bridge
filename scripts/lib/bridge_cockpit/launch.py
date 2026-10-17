# SPDX-License-Identifier: MIT
"""The model (and effort) an agent tab starts with: the settings, the choice of one start, the route.

The config (cockpit.launch_model) says what a Bridge starts with; the settings page changes that on
top, kept in .bridge/cockpit/launch.json, so the page never writes bridge-config.yaml. Everything is
off until `enabled`: then the start runs exactly as before, no judge is asked and no flag is added.

A start names a model (haiku, sonnet, opus) or `auto`. Auto at the click only asks Jev, which answers
in a fraction of a second; the page fetches its recommendation beforehand through /api/route (Jev or
Haiku, model_route.py) and sends the concrete model. A click itself never waits for a judge: Auto
without a fetched recommendation starts with the default, so a slow or hanging API holds no start.
"""
from __future__ import annotations

import threading
from typing import Any

from .. import model_route as mr
from .store import atomic_write_json, read_json

try:
    from . import jev
except ImportError:            # a Bridge without the optional Jev module
    jev = None  # type: ignore[assignment]

FILE = "launch.json"
HAIKU_TIMEOUT = 60
CACHE_MS = 10 * 60 * 1000
SWITCHES = ("enabled", "manual", "auto", "effort")


class LaunchError(Exception):
    def __init__(self, status: int, code: str, message: str, field: str | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.field = status, code, message, field


class LaunchModel:
    def __init__(self, app: Any):
        self.app = app
        self.path = app.state_dir / FILE
        self.lock = threading.Lock()
        self.cache: dict[str, tuple[float, str, dict]] = {}
        self.generation = 0            # bumped by every settings change; a route judged before it is not kept

    # ------------------------------------------------------------ settings

    def defaults(self) -> dict:
        return dict(getattr(self.app.cfg, "launch_model", None) or mr.DEFAULTS)

    def overrides(self) -> dict:
        data = read_json(self.path)
        if not isinstance(data, dict):
            return {}
        out = {}
        for key, value in data.items():
            try:
                mr.normalize({key: value})
            except mr.SettingsError:
                continue           # a stale or hand-edited value falls back to the config's
            out[key] = value
        return out

    def settings(self) -> dict:
        return mr.normalize(self.overrides(), self.defaults())

    def save(self, change: Any) -> dict:
        try:
            mr.normalize(change, self.defaults())
        except mr.SettingsError as error:
            raise LaunchError(400, "invalid_argument", str(error), error.field) from None
        with self.lock:
            merged = {**self.overrides(), **change}
            base = self.defaults()
            # a value equal to the config's is no override: the page then shows it as the config's own
            atomic_write_json(self.path, {k: v for k, v in merged.items() if v != base.get(k)})
            self.forget()
        return self.settings()

    def forget(self) -> None:
        """Drop every recommendation (under self.lock): they were judged with the old settings."""
        self.cache.clear()
        self.generation += 1

    def reset(self) -> dict:
        with self.lock:
            atomic_write_json(self.path, {})
            self.forget()
        return self.settings()

    # ------------------------------------------------------------ judges

    def jev_ready(self) -> bool:
        if jev is None:
            return False
        try:
            return bool(jev.status(self.app).get("ready"))
        except Exception:      # noqa: BLE001  a broken keychain is "not ready", never a failed page
            return False

    def router(self, s: dict) -> str:
        """Which judge Auto would ask now: jev, haiku or off."""
        if not (s["enabled"] and s["auto"]):
            return "off"
        has_jev = s["router"] in ("chain", "jev") and self.jev_ready()
        has_haiku = s["router"] in ("chain", "haiku") and bool(getattr(self.app.runner, "claude", None))
        return "jev" if has_jev else "haiku" if has_haiku else "off"

    def ask_jev(self, payload: dict) -> dict:
        key = jev.resolve_key(ref=getattr(self.app.cfg, "jev_key_ref", None))
        return jev.call_api(payload, key)

    def ask_haiku(self, prompt: str) -> str:
        run = self.app.run(mr.haiku_argv(self.app.runner.claude, prompt), HAIKU_TIMEOUT)
        if not run.ok:
            raise RuntimeError("haiku failed")
        return run.out

    def judges(self, s: dict) -> dict:
        """The judges this route may ask."""
        out: dict = {}
        if s["router"] in ("chain", "jev") and self.jev_ready():
            out["jev"] = self.ask_jev
        if s["router"] in ("chain", "haiku") and getattr(self.app.runner, "claude", None):
            out["haiku"] = self.ask_haiku
        return out

    # ------------------------------------------------------------ the route

    @staticmethod
    def item_of(row: dict) -> dict:
        kind = row.get("task_type") or ("inbox item" if row.get("inbox_id") else "task")
        return {"title": str(row.get("title") or ""), "kind": str(kind), "priority": str(row.get("priority") or "")}

    def route_rows(self, keyed: list[tuple[str, dict]], cached_only: bool = False) -> dict:
        """{row key: route} for rows already resolved; cached per key and title for ten minutes.
        cached_only answers from the cache and gives the rest the default, asking no judge."""
        with self.lock:
            s, generation = self.settings(), self.generation
            now = self.app.clock()
            out, todo = {}, []
            for key, row in keyed:
                hit = self.cache.get(key)
                if hit and now - hit[0] < CACHE_MS and hit[1] == str(row.get("title") or ""):
                    out[key] = hit[2]
                else:
                    todo.append((key, row))
        if todo and cached_only:
            out.update({key: mr.default_route(s, "no recommendation fetched") for key, _ in todo})
        elif todo:
            items = [{"id": f"k{i}", **self.item_of(row)} for i, (_, row) in enumerate(todo)]
            routes = mr.route(items, s, **self.judges(s))
            with self.lock:
                for i, (key, row) in enumerate(todo):
                    out[key] = routes[f"k{i}"]
                    if routes[f"k{i}"]["routed_by"] != "default" and self.generation == generation:
                        self.cache[key] = (now, str(row.get("title") or ""), routes[f"k{i}"])
        return out

    def handle_route(self, body: dict) -> dict:
        for name in body:
            if name != "keys":
                raise LaunchError(400, "invalid_argument", "unknown field", str(name)[:40])
        s = self.settings()
        if self.router(s) == "off":
            raise LaunchError(404, "launch_off", "Auto is not switched on (cockpit.launch_model)")
        from .actions import ROW_KEY_RE        # here: actions imports this module
        keys = body.get("keys")
        if (not isinstance(keys, list) or not 1 <= len(keys) <= mr.MAX_ITEMS
                or not all(isinstance(k, str) and ROW_KEY_RE.match(k) for k in keys) or len(set(keys)) != len(keys)):
            raise LaunchError(400, "invalid_argument", f"keys must be a list of 1 to {mr.MAX_ITEMS} distinct row keys", "keys")
        keyed = list(zip(keys, (e["row"] for e in self.app.actions.entries(keys))))
        return {"ok": True, "routes": self.route_rows(keyed)}

    # ------------------------------------------------------------ one start

    def pick(self, rows: list[dict], model: str | None, effort: str | None) -> dict | None:
        """What one start runs with: {model, effort, routed_by, why}, or None while switched off.

        A model picked by hand counts as it is (manual on). With manual off a sent model is Auto's
        recommendation and stays under max_model. Auto takes the recommendation the page fetched,
        else the default; several rows of one start share the strongest pick. Effort: `standard`
        is none (Claude Code's own), a level is that level, missing or `auto` follows the route."""
        s = self.settings()
        if not s["enabled"]:
            return None
        if model in (None, "auto") and s["auto"]:
            keyed = [(str(r.get("key") or i), r) for i, r in enumerate(rows)]
            routes = list(self.route_rows(keyed, cached_only=True).values()) or [mr.default_route(s, "no row")]
            best = max(routes, key=lambda r: mr.MODELS.index(r["model"]))
            chosen = {"model": mr.capped(best["model"], s), "effort": best["effort"],
                      "routed_by": best["routed_by"], "why": best["why"]}
        elif model in mr.MODELS and s["manual"]:
            chosen = {"model": model, "effort": s["default_effort"], "routed_by": "chosen", "why": ""}
        elif model in mr.MODELS and s["auto"]:
            chosen = {"model": mr.capped(model, s), "effort": s["default_effort"], "routed_by": "recommended", "why": ""}
        else:
            chosen = {"model": s["default_model"], "effort": s["default_effort"], "routed_by": "default", "why": ""}
        if effort == "standard":
            chosen["effort"] = None
        elif effort in mr.EFFORTS:
            chosen["effort"] = effort
        if not s["effort"]:
            chosen["effort"] = None
        return chosen

    # ------------------------------------------------------------ the page

    def state(self) -> dict:
        s = self.settings()
        base = self.defaults()
        return {**{k: s[k] for k in SWITCHES}, "models": list(mr.MODELS), "efforts": list(mr.EFFORTS),
                "default_model": s["default_model"], "default_effort": s["default_effort"],
                "router": self.router(s), "settings": s, "defaults": base,
                "overridden": sorted(k for k in s if s[k] != base.get(k))}
