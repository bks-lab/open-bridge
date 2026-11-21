# SPDX-License-Identifier: MIT
"""Round 2 of the simulation of the four answers: what the testers reproduced on simulated Bridges, the server's and
the briefing's part.

Run: python3 -m pytest -q scripts/tests/test_bridge_cockpit_four_answers_r2.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.bridge_cockpit import model as m  # noqa: E402

_spec = importlib.util.spec_from_file_location("briefing_view_r2", Path(__file__).resolve().parents[1] / "lib" / "briefing_view.py")
bv = importlib.util.module_from_spec(_spec)
sys.modules["briefing_view_r2"] = bv
_spec.loader.exec_module(bv)


def _sec(sid, kind, items):
    return {"id": sid, "kind": kind, "title": sid, "status": "ok", "items": items, "all": items, "total": len(items)}


def _build(items, tasks=(), view=None):
    secs = [_sec("inbox", "inbox", list(items))] + ([_sec("tasks", "tasks", list(tasks))] if tasks else [])
    return bv.build({"profile": "m", "title": "M", "collected_at": "2026-11-21T08:00", "sections": secs},
                    {"id": "m", "sections": [{"kind": "inbox"}] + ([{"kind": "tasks"}] if tasks else []),
                     "view": {"style": "triage", **(view or {})}})


def _buckets(built):
    return {b["id"]: [r["title"] for r in b["items"]] for b in built["buckets"]}


# ---------------------------------------------------------------- only you: Do

def test_an_only_you_item_stands_in_do_also_without_a_day():
    # round 2: "Migrate the dashboard" (decision, only-you, urgency later, no due) stood in Plan, the model says Do
    items = [{"id": "20260419-2015-migrate", "title": "Migrate the dashboard", "state": "open", "urgency": "later",
              "kind": "decision", "gate": "only-you"},
             {"id": "20260419-2016-other", "title": "Check the notes", "state": "open", "urgency": "later",
              "kind": "decision", "gate": "your-yes"},
             {"id": "20260419-2017-idea", "title": "An idea", "state": "open", "urgency": "later",
              "kind": "idea", "gate": "only-you"}]
    got = _buckets(_build(items))
    assert "Migrate the dashboard" in got["do"]
    assert "Check the notes" in got["plan"]
    assert "An idea" not in got.get("do", []), "an idea asks nobody, only-you or not"


# ---------------------------------------------------------------- an item's own tab

def test_an_inbox_rows_own_tab_beats_the_tab_of_its_task():
    # round 2: the item d779 about a stream got the stream's dialog tab, its own yes-or-no tab was not its tab
    row = {"inbox_id": "20261121-2146-swap-d779", "task": "rota"}
    stream = {"ref": "surface:13", "slug": "rota", "item": None, "state": "needs-you"}
    own = {"ref": "surface:17", "slug": None, "item": "20261121-2146-swap-d779", "state": "waiting"}
    assert m.tab_for(row, [stream, own])["ref"] == "surface:17"
    # a task's own row keeps its task's tab
    assert m.tab_for({"task": "rota"}, [stream, own])["ref"] == "surface:13"


# ---------------------------------------------------------------- With … a name on an inbox item

BUCKETS_ON = "cockpit:\n  enabled: true\n  language: en\n  flow:\n    enabled: true\n"


def test_an_inbox_item_with_someone_stays_a_point_so_it_stands_in_waiting(tmp_path):
    # round 2: With Jordan Lee on an inbox item left every bucket while the briefing listed it under Waiting on others
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_bridge_cockpit import World, YES_ID
    w = World(tmp_path, config=BUCKETS_ON)
    try:
        res = w.act("work_on", key=f"inbox:{YES_ID}", who="Jordan Lee", until="2026-12-01")
        assert res["ok"] and f"inbox:{YES_ID}" not in w.app.collector.settled
        assert "Jordan Lee" in res["note"]
    finally:
        w.close()


# ---------------------------------------------------------------- one number per row, short print or long

def test_a_short_and_a_long_print_name_a_row_by_one_number():
    # round 2: `render --max-items 300` numbered the waiting rows 92 to 96, their cockpit cards said 10 to 12
    items = [{"id": f"20261001-09{n:02d}-ask-{n}", "title": f"Ask {n}", "state": "open", "kind": "decision",
              "gate": "your-yes", "urgency": ("now", "later")[n % 2]} for n in range(20)]
    items += [{"id": "20261001-0900-wait", "title": "Wait for Robin", "state": "open", "kind": "decision", "waits_for": True}]
    short = _build(items, view={"max_items": 9})
    long = _build(items, view={"max_items": 300})
    nr = lambda v: {r["title"]: r["nr"] for b in v["buckets"] for r in b["items"]}
    s, lg = nr(short), nr(long)
    assert all(lg[t] == n for t, n in s.items())
    assert sorted(lg.values()) == list(range(1, len(lg) + 1))
    assert s["Waiting for: Wait for Robin"] == len(lg)
