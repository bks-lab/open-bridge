# SPDX-License-Identifier: MIT
"""Round 4 of the four answers: an agent tab that asks is a numbered row of the briefing's Do, and a row keeps its
number all day (the day's number book), so an answer moves no other row's number.

Run: python3 -m pytest -q scripts/tests/test_four_answers_r4.py
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "scripts"))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


bv = sys.modules.get("briefing_view") or _load("briefing_view", ROOT / "scripts" / "lib" / "briefing_view.py")
bf = sys.modules.get("briefing") or _load("briefing", ROOT / "scripts" / "briefing.py")
answers = sys.modules.get("answers") or _load("answers", ROOT / "scripts" / "lib" / "answers.py")

NOW = dt.datetime(2026, 11, 20, 7, 45)


def sec(sid, kind, items):
    return {"id": sid, "kind": kind, "title": sid, "status": "ok", "items": items, "all": items, "total": len(items)}


def result(*sections, **extra):
    return {"profile": "morning", "title": "Morning", "collected_at": NOW.isoformat(timespec="minutes"),
            "sections": list(sections), **extra}


def profile(style="triage", **extra):
    return {"schema_version": 1, "scope": "user", "id": "morning", "for": "alice",
            "sections": [{"kind": "inbox"}, {"kind": "tasks"}, {"kind": "workplace"}], "view": {"style": style}, **extra}


def item(iid, title, **kw):
    return {"id": iid, "title": title, "state": "open", "urgency": "today", "kind": "decision", "gate": "your-yes",
            "due": None, "task": None, **kw}


def task(slug, nxt, **kw):
    return {"id": slug, "title": f"Task {slug}", "state": "doing", "next": nxt, "blocked_by": None,
            "changed_at": "2026-10-01", "url": f"work/tasks/{slug}/STATUS.md", **kw}


ASKS = {"id": "tab:surface:9", "title": "Contact import", "state": "asks", "tab_ref": "surface:9", "project": "Home"}


def items_of(view):
    return [(b["id"], r) for b in view["buckets"] for r in b["items"]]


# ---------------------------------------------------------------- an agent tab that asks

def test_an_asking_tab_is_a_row_of_do_shown_first_and_numbered_after_every_other_row():
    r = result(sec("inbox", "inbox", [item("20261120-0900-sign-a1b2", "Sign"), item("20261120-0910-read-c3d4", "Read")]),
               sec("tasks", "tasks", [task("a", {"what": "draft it", "who": "me"})]),
               sec("workplace", "workplace", [ASKS]))
    v = bv.build(r, profile())
    do = [x for b, x in items_of(v) if b == "do"]
    assert do[0]["tab_ref"] == "surface:9" and do[0]["title"] == "Agent tab asks: Contact import"
    # numbered last, so a tab that comes or goes moves no other number
    assert do[0]["nr"] == max(x["nr"] for _b, x in items_of(v))
    text = bv.draw(v)
    assert "Agent tab asks: Contact import" in text
    # the chat answers it in the tab, with the tab's own answer
    assert answers.effect("do", do[0])["own_answers"] is True


def test_the_cockpit_gives_the_tabs_number_to_the_tab_never_a_second_row():
    sys.path.insert(0, str(ROOT / "scripts"))
    from lib.bridge_cockpit import model as m
    r = result(sec("inbox", "inbox", [item("20261120-0900-sign-a1b2", "Sign")]), sec("workplace", "workplace", [ASKS]))
    v = bv.build(r, profile())
    parsed = m.parse_view({"view": v}, True, 0)
    assert parsed["tab_nrs"] == {"surface:9": 2}
    assert not [x for b in parsed["buckets"] for x in b["rows"] if "Contact import" in x["title"]]


def test_asking_tabs_are_the_unbound_ones_in_a_dialog():
    class Wp:
        @staticmethod
        def driver_from(spec):
            return object()

        @staticmethod
        def status_rows(root, cfg, driver):
            return [{"ref": "surface:1", "name": "Free", "state": "needs-you"},
                    {"ref": "surface:2", "name": "Of a task", "state": "needs-you", "slug": "a"},
                    {"ref": "surface:3", "name": "Of an item", "state": "needs-you", "item": "x"},
                    {"ref": "surface:4", "name": "Working", "state": "working"}]
    got = bf.asking_tabs(Wp, ROOT, {"driver": {"argv": ["x"]}})
    assert [t["tab_ref"] for t in got] == ["surface:1"] and got[0]["state"] == "asks"
    assert bf.asking_tabs(Wp, ROOT, {}) == []


# ---------------------------------------------------------------- a number all day

def test_with_the_days_book_a_row_keeps_its_number_after_an_answer():
    rows = [item(f"20261120-09{n:02d}-ask-{n}", f"Ask {n}") for n in range(4)]
    first = bv.build(result(sec("inbox", "inbox", rows), number_book={}), profile())
    book = first["number_book"]
    nr = {x["title"]: x["nr"] for _b, x in items_of(first)}
    assert sorted(nr.values()) == [1, 2, 3, 4]
    # Ask of number 2 is done: the others keep theirs, a new row gets the next number nobody had
    gone = [x for x in rows if x["title"] != next(t for t, n in nr.items() if n == 2)]
    later = bv.build(result(sec("inbox", "inbox", gone + [item("20261120-1000-ask-new", "Ask new")]), number_book=book),
                     profile())
    again = {x["title"]: x["nr"] for _b, x in items_of(later)}
    assert {t: n for t, n in again.items() if t != "Ask new"} == {t: n for t, n in nr.items() if n != 2}
    assert again["Ask new"] == 5
    # each bucket lists its rows by their numbers, as the cockpit's buckets do
    assert [x["nr"] for _b, x in items_of(later)] == sorted(x["nr"] for _b, x in items_of(later))


def test_the_book_is_the_days_and_the_profiles(tmp_path):
    bf.save_number_book(tmp_path, "morning", NOW, {"inbox:a": 3})
    assert bf.number_book(tmp_path, "morning", NOW) == {"inbox:a": 3}
    assert bf.number_book(tmp_path, "morning", NOW + dt.timedelta(days=1)) == {}
    assert bf.number_book(tmp_path, "other", NOW) == {}
    assert bf.number_book(tmp_path, "../x", NOW) == {}
    data = json.loads((tmp_path / ".bridge" / "cockpit" / "numbers" / "morning.json").read_text())
    assert data["day"] == "2026-11-20"


def test_a_cockpit_pass_takes_the_printed_numbers_of_the_book():
    rows = [item(f"20261120-09{n:02d}-ask-{n}", f"Ask {n}") for n in range(3)]
    book = {f"inbox:20261120-0900-ask-0": 7}
    v = bv.build(result(sec("inbox", "inbox", rows), number_book=book), profile(_whole=True), "triage")
    nr = {x["title"]: x["nr"] for _b, x in items_of(v)}
    assert nr["Ask 0"] == 7 and sorted(nr.values()) == [7, 8, 9]
    assert v["number_book"]["inbox:20261120-0901-ask-1"] == 8


# ---------------------------------------------------------------- one count of Do

def test_the_day_part_of_the_headline_carries_no_count_of_do():
    rows = [item("20261120-0900-sign-a1b2", "Sign"), item("20261120-0910-read-c3d4", "Read", kind="finding")]
    v = bv.build(result(sec("inbox", "inbox", rows)), profile())
    assert v["headline"].startswith("1 ") and "report" in v["headline"]
    assert "report" not in v["headline_day"] and not v["headline_day"][:1].isdigit()
    from lib.bridge_cockpit import model as m
    # the Due panel's head says its own count before this part: "15 wait for you · 4 reports" counted twice (round 4)
    assert m.parse_view({"view": v}, True, 0)["headline_rest"] == v["headline_day"]
