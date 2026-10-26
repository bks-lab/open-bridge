# SPDX-License-Identifier: MIT
"""The triage of the cockpit: `scripts/triage.py run` in the background, its last run for the page.

Every open task and inbox item gets one line of what it is about, whether it can go and who does it
(the AI, the person, or the AI prepares and the person confirms). A run asks the small model only for
items whose evidence changed, so it is cheap; it takes up to a few minutes and runs on a thread of its
own. Once a day it runs by itself; "re-sort" on the page starts one (POST /api/triage/run). What the
page shows comes from the last run that triage.py keeps in .bridge/triage.json (key `last`), read again
only when the file changed. The page gets it as the `triage` event and in the state payload.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from typing import Any

CACHE = Path(".bridge") / "triage.json"
SCRIPT = "scripts/triage.py"
TIMEOUT = 330
DAILY_SEC = 24 * 3600
CHECK_EVERY_SEC = 15 * 60
ITEM_FIELDS = ("kind", "title", "gist", "topic", "verdict", "reason", "doer", "effort", "why", "verdict_from", "model")
NUMBER_FIELDS = ("level", "jev")       # how complex for an AI: Haiku's level, Jev's score (launch.py picks the model)
DAY_MS = 24 * 3600 * 1000


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def jev_ranks(orders: Any, now_ms: float, max_age_days: float) -> dict:
    """{key: (rank, at_ms)} from Jev's last order of each page (jev.py rank, jev-pages.json): the newest order
    that holds a row wins, and an order older than max_age_days counts for nothing, so a rank never mixes
    old and new judgments. Anything malformed is skipped."""
    out: dict = {}
    for order in (orders.values() if isinstance(orders, dict) else ()):
        at = order.get("at_ms") if isinstance(order, dict) else None
        if not (_is_int(at) or isinstance(at, float)) or now_ms - at > max_age_days * DAY_MS:
            continue
        for x in order.get("items") or ():
            if isinstance(x, dict) and isinstance(x.get("key"), str) and _is_int(x.get("rank")):
                if x["key"] not in out or out[x["key"]][1] < at:
                    out[x["key"]] = (x["rank"], at)
    return out


def _cents(usd: Any) -> float:
    try:
        return round(float(usd) * 100, 2)
    except (TypeError, ValueError):
        return 0.0


class Triage:
    def __init__(self, app: Any):
        self.app = app
        self.lock = threading.Lock()
        self.running: dict | None = None
        self.error: str | None = None
        self._cache: tuple[float, dict | None] = (-1.0, None)

    def last(self) -> dict | None:
        path = Path(self.app.root) / CACHE
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return None
        with self.lock:
            if self._cache[0] == mtime:
                return self._cache[1]
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        last = data.get("last") if isinstance(data, dict) and isinstance(data.get("last"), dict) else None
        with self.lock:
            self._cache = (mtime, last)
        return last

    def state(self) -> dict:
        """running, the last run's numbers, one entry per key (`task:<slug>`, `inbox:<id>`); a damaged file
        degrades to "not sorted yet"."""
        with self.lock:
            out = {"running": dict(self.running) if self.running else None, "error": self.error, "last": None, "items": {}}
        last = self.last()
        if not last:
            return out
        items = {}
        for x in last.get("items") or []:
            if isinstance(x, dict) and isinstance(x.get("key"), str):
                items[x["key"]] = {k: x.get(k) if isinstance(x.get(k), str) else None for k in ITEM_FIELDS}
                items[x["key"]].update({k: x[k] if isinstance(x.get(k), (int, float)) and not isinstance(x.get(k), bool)
                                        else None for k in NUMBER_FIELDS})
        # the order of the Work through area: Jev's rank while it is fresh (cockpit.flow.rank_max_age_days)
        ranks = self.ranks()
        for key, item in items.items():
            item["next_rank"], item["rank_at"] = ranks.get(key, (None, None))
        out["items"] = items
        out["last"] = {"at": last.get("at"), "count": len(items), "cost_ct": _cents(last.get("cost_usd")),
                       "cost_known": bool(last.get("cost_known", True)), "calls": last.get("calls"),
                       "model": str(last.get("model") or "").replace("claude-", "") or None,
                       "duration_sec": last.get("duration_sec")}
        return out

    def ranks(self) -> dict:
        from .jev import _pages_state
        app = self.app
        st = _pages_state(app)
        with st.lock:
            orders = dict(st.orders)
        return jev_ranks(orders, app.clock(), app.cfg.flow["rank_max_age_days"])

    def argv(self, fresh: bool) -> list[str]:
        app = self.app
        view = app.store.view_path
        return [sys.executable, app.runner.script(SCRIPT), "--root", str(app.root),
                *(["--view", str(view)] if view.is_file() else []), "run", "--json", *(["--fresh"] if fresh else [])]

    def start(self, fresh: bool = False, why: str = "click") -> bool:
        with self.lock:
            if self.running:
                return False
            self.running = {"started_ms": int(self.app.clock()), "why": why}
            self.error = None
        threading.Thread(target=self._run, args=(fresh, why), name="bridge-cockpit-triage", daemon=True).start()
        self.app.broadcast("triage", self.state())
        return True

    def _run(self, fresh: bool, why: str = "click") -> None:
        app = self.app
        tx = app.tx
        result = None
        try:
            run = app.run(self.argv(fresh), TIMEOUT)
            result = None
            if run.ok:
                try:
                    result = json.loads(run.out)
                except ValueError:
                    result = None
            if not isinstance(result, dict):
                err = (run.err or "").strip().splitlines()[-1:] or ["no answer"]
                with self.lock:
                    self.error = app.scrub(err[0])[:200]
                app.note(tx["triage_failed"].format(err=self.error), "bad")
            else:
                c = result.get("counts") or {}
                cost = (tx["review_cost"].format(ct=f"{_cents(result.get('cost_usd')):.2f}")
                        if result.get("cost_known", True) else tx["review_cost_unknown"])
                app.note(tx["triage_done"].format(n=len(result.get("items") or []), close=c.get("close", 0),
                                                  ai=c.get("ai", 0), you=c.get("you", 0), cost=cost), "ok")
        except Exception as exc:  # noqa: BLE001 - a failed run must never leave `running` set
            with self.lock:
                self.error = str(exc)[:200]
            app.log_error(f"triage: {exc!r}")
        finally:
            with self.lock:
                self.running = None
            # titles go to the small model: the line says how many items, which model and whether it answered
            done = isinstance(result, dict)
            self.audit(why, fresh=fresh, rows=len(result.get("items") or []) if done else 0,
                       model=str(result.get("model") or "").replace("claude-", "") or "-" if done else "-", ok=done)
            app.broadcast("triage", self.state())

    def audit(self, why: str, **fields: Any) -> None:
        actions = getattr(self.app, "actions", None)
        if actions is not None:
            actions.audit_line("triage", why, **fields)

    # ------------------------------------------------------------ once a day by itself

    def due(self, now_sec: float) -> bool:
        last = self.last()
        if not last:
            return True
        try:
            import datetime as dt
            at = dt.datetime.fromisoformat(str(last.get("at"))).timestamp()
        except (ValueError, TypeError):
            return True
        return now_sec - at >= DAILY_SEC

    def start_daily(self) -> None:
        def loop() -> None:
            time.sleep(60)     # after the first collect, not in its way
            while True:
                try:
                    if self.due(time.time()):
                        self.start(why="daily")
                except Exception as exc:  # noqa: BLE001 - the daily run never takes the server down
                    self.app.log_error(f"triage daily: {exc!r}")
                time.sleep(CHECK_EVERY_SEC)
        threading.Thread(target=loop, name="bridge-cockpit-triage-daily", daemon=True).start()

    def handle_post(self, handler: Any, body: dict) -> None:
        from .actions import ActionError
        for name in body:
            if name != "fresh":
                raise ActionError(400, "invalid_argument", "unknown field", str(name)[:40])
        fresh = body.get("fresh", False)
        if not isinstance(fresh, bool):
            raise ActionError(400, "invalid_argument", "fresh must be true or false", "fresh")
        started = self.start(fresh=fresh)
        if not started:
            self.audit("click", fresh=fresh, started=False)     # a run is on: this click sent nothing
        handler.send_json(202 if started else 409, {"ok": started, "triage": self.state()})
