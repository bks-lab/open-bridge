# SPDX-License-Identifier: MIT
"""What the cockpit takes over from the briefing for Work through by its buckets (cockpit.flow.buckets).

The briefing's view names its buckets with their titles and answers (`bucket_defs`) and numbers every row as the
printed briefing does (`nr`); the cockpit keeps both, the buckets as the model's `buckets`, the number as each row's
`brief_nr`, so a card says "In the briefing: no. 3" and "3 yes" in the chat is the same act as a click on the card.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.bridge_cockpit import model as m  # noqa: E402

DEFS = [{"id": "do", "title": "Tun (du, heute)", "options": ["ja", "später", "streichen"]},
        {"id": "plan", "title": "Planen", "options": ["einplanen", "später"]}]


def raw(items, defs=DEFS):
    return {"profile": "cockpit", "title": "Cockpit",
            "view": {"buckets": [{"id": "do", "title": "Tun (du, heute)", "items": items}], "bucket_defs": defs}}


def test_a_row_keeps_its_number_in_the_printed_briefing():
    view = m.parse_view(raw([{"title": "Sign", "inbox_id": "i1", "nr": 3}, {"title": "Read", "inbox_id": "i2"}]), True, 0)
    rows = view["buckets"][0]["rows"]
    assert [r["brief_nr"] for r in rows] == [3, None]


def test_a_number_that_is_no_whole_number_above_zero_is_none():
    for bad in (0, -1, "3", True, 2.5):
        view = m.parse_view(raw([{"title": "Sign", "inbox_id": "i1", "nr": bad}]), True, 0)
        assert view["buckets"][0]["rows"][0]["brief_nr"] is None, bad


def test_the_view_keeps_the_profiles_buckets_in_its_order():
    view = m.parse_view(raw([]), True, 0)
    assert view["bucket_defs"] == DEFS


def test_only_the_five_buckets_each_once_with_answers_of_text():
    defs = [{"id": "plan", "title": "", "options": ["einplanen", 3, " ", "später"]}, {"id": "plan", "title": "again"},
            {"id": "tasks", "title": "no bucket of the briefing"}, "x"]
    assert m.bucket_defs_of(defs) == [{"id": "plan", "title": "plan", "options": ["einplanen", "später"]}]
    assert m.bucket_defs_of(None) == []
