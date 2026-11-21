# SPDX-License-Identifier: MIT
"""The briefing's buckets as one rule for the printed briefing and the cockpit (21.11.2026).

Every point stands in exactly one bucket of the profile's `view.buckets`, by the fixed rule of
scripts/lib/briefing_view.py. The cockpit's Work through sorts its cards into the same buckets
(docs/bridge-cockpit.md, Buckets) and shows each card's number in the printed briefing, so the
rule refinements live here, where both read them:

- an inbox item put off waiting on the Bridge is the Bridge's to do (delegate), never "waiting on
  others"; one only you can take on (gate only-you: a login, a send) is yours (do)
- every visible row has a number (`nr`), calm's waiting rows too, the same the renderers print
- a cockpit pass (every row, `_whole`) numbers as the printed briefing would: its own style,
  its own max_items, without what was settled in the cockpit
- the view names every shown bucket with its title and answers (`bucket_defs`), also an empty one
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


bv = sys.modules.get("briefing_view") or _load("briefing_view", ROOT / "scripts" / "lib" / "briefing_view.py")

NOW = dt.datetime(2026, 10, 5, 7, 45)
SECTIONS = [{"kind": "inbox"}, {"kind": "tasks"}]


def sec(sid, kind, items):
    return {"id": sid, "kind": kind, "title": sid, "status": "ok", "items": items, "all": items, "total": len(items)}


def result(*sections, **extra):
    return {"profile": "morning", "title": "Morning", "collected_at": NOW.isoformat(timespec="minutes"),
            "sections": list(sections), **extra}


def profile(view=None, sections=None, **extra):
    return {"schema_version": 1, "scope": "user", "id": "morning", "for": "alice", "sections": sections or SECTIONS,
            "view": view or {"style": "triage"}, **extra}


def item(iid, title, **kw):
    base = {"id": iid, "title": title, "state": "open", "urgency": "today", "kind": "decision", "gate": "your-yes",
            "due": None, "task": None}
    return {**base, **kw}


def task(slug, nxt, **kw):
    return {"id": slug, "title": slug, "state": "doing", "next": nxt, "blocked_by": None, "changed_at": "2026-10-04",
            "url": f"work/tasks/{slug}/STATUS.md", **kw}


def bucket_of(view, title):
    return next(b["id"] for b in view["buckets"] for r in b["items"] if r["title"] == title)


def deferred(iid, title, on, **kw):
    return item(iid, title, state="deferred", urgency="later", until="2026-10-23", waiting_on=on, **kw)


# ---------------------------------------------------------------- the bucket rule

def test_an_item_put_off_waiting_on_the_bridge_is_the_bridges_to_do():
    rows = [deferred("i1", "Fix the probe", "Bridge"), deferred("i2", "Read the log", "the Bridge"),
            deferred("i3", "Agency answers", "Agency")]
    v = bv.build(result(sec("inbox", "inbox", rows)), profile())
    assert bucket_of(v, "Fix the probe") == "delegate"
    assert bucket_of(v, "Read the log") == "delegate"
    assert bucket_of(v, "Agency answers") == "waiting"


def test_a_section_of_what_waits_on_others_holds_no_row_that_waits_on_the_bridge():
    # a section of what runs on (deferred: runs, bucket: waiting) put 8 rows on the Bridge under Waiting (21.11.2026)
    rows = [deferred("i1", "Fix the probe", "Bridge"), deferred("i2", "Agency answers", "Agency"),
            deferred("i3", "Sign in", "Bridge", gate="only-you")]
    p = profile(sections=[{"kind": "inbox", "id": "runs", "deferred": "runs", "bucket": "waiting"}])
    v = bv.build(result(sec("runs", "inbox", rows)), p)
    assert bucket_of(v, "Fix the probe") == "delegate"
    assert bucket_of(v, "Sign in") == "do"
    assert bucket_of(v, "Agency answers") == "waiting"


def test_an_item_on_the_bridge_that_only_you_can_take_on_is_yours():
    # a login: the Bridge cannot click it for you, so it is no "I'll do"
    rows = [deferred("i1", "Cloud console: sign in", "Bridge", gate="only-you", kind="question")]
    v = bv.build(result(sec("inbox", "inbox", rows)), profile())
    assert bucket_of(v, "Cloud console: sign in") == "do"


def test_a_task_whose_step_is_the_bridges_is_delegate_in_every_spelling():
    rows = [task("a", {"what": "draft it", "who": "bridge"}), task("b", {"what": "draft it", "who": "The Bridge"})]
    v = bv.build(result(sec("tasks", "tasks", rows)), profile())
    assert bucket_of(v, "a") == "delegate" and bucket_of(v, "b") == "delegate"


# ---------------------------------------------------------------- the buckets the view names

def test_the_view_names_every_shown_bucket_with_its_answers_also_an_empty_one():
    buckets = [{"id": "do", "title": "Tun", "options": ["ja", "später", "streichen"]}, {"id": "waiting"},
               {"id": "delegate", "title": "Mache ich", "options": ["los", "nicht jetzt"]}]
    v = bv.build(result(sec("inbox", "inbox", [item("i1", "Sign")])), profile({"style": "triage", "buckets": buckets}))
    assert v["bucket_defs"] == [{"id": "do", "title": "Tun", "options": ["ja", "später", "streichen"]},
                                {"id": "waiting", "title": "Waiting on others", "options": ["nudge", "wait"]},
                                {"id": "delegate", "title": "Mache ich", "options": ["los", "nicht jetzt"]}]


def test_without_buckets_in_the_profile_the_defaults_stand_in_their_order():
    v = bv.build(result(sec("inbox", "inbox", [])), profile())
    assert [b["id"] for b in v["bucket_defs"]] == ["do", "plan", "delegate", "waiting", "drop"]
    assert v["bucket_defs"][0]["options"] == ["yes", "later", "drop"]


# ---------------------------------------------------------------- the numbers

def _rows():
    return [sec("inbox", "inbox", [item("i1", "Sign the contract"), item("i2", "Object", urgency="later"),
                                   deferred("i3", "Agency answers", "Agency"), deferred("i4", "Fix the probe", "Bridge")])]


def _printed_numbers(text):
    return [int(m.group(1)) for m in re.finditer(r"^\s*(\d+)\.?\s", text, re.M)]


def test_calm_numbers_every_visible_row_waiting_included_as_it_prints_them():
    v = bv.build(result(*_rows()), profile({"style": "calm"}))
    nr = {r["title"]: r.get("nr") for b in v["buckets"] for r in b["items"]}
    assert nr == {"Sign the contract": 1, "Object": 2, "Agency answers": 3, "Fix the probe": 4}
    text = bv.draw(v)
    assert "3. Agency (Agency answers) until 23.10" in text and "4. Fix the probe" in text


def test_triage_and_report_print_the_numbers_the_rows_carry():
    for style, pattern in (("triage", r"^\s+(\d+)\s+(.+?)(?:\s\s\(|$)"), ("report", r"^(\d+)\. (?:\*\*)?(.+?)(?:\*\*)?\s*$")):
        v = bv.build(result(*_rows()), profile({"style": style}))
        carried = {r["title"]: r["nr"] for b in v["buckets"] for r in b["items"]}
        printed = {m.group(2).strip(): int(m.group(1)) for m in re.finditer(pattern, bv.draw(v), re.M)}
        assert carried and all(printed.get(t) == n for t, n in carried.items()), (style, carried, printed)


def test_a_cockpit_pass_numbers_as_the_printed_briefing_would():
    # the cockpit asks for every row (--max-items 500, `_whole`); its cards still say the printed number
    rows = [sec("inbox", "inbox", [item(f"i{n}", f"Ask {n}") for n in range(1, 8)])]
    printed = bv.build(result(*rows), profile({"style": "calm", "max_items": 4}))
    cockpit = bv.build(result(*rows), profile({"style": "calm", "max_items": 500}, _whole=True, _print_max=4))
    want = {r["title"]: r.get("nr") for b in printed["buckets"] for r in b["items"]}
    got = {r["title"]: r.get("nr") for b in cockpit["buckets"] for r in b["items"]}
    assert len(got) == 7 and {t: n for t, n in got.items() if n} == want


def test_a_cockpit_pass_numbers_by_the_profiles_style_not_the_forced_one():
    rows = [sec("inbox", "inbox", [item("i1", "Sign"), item("i2", "Object", urgency="later")])]
    v = bv.build(result(*rows), profile({"style": "brevity"}, _whole=True), "triage")
    assert all("nr" not in r for b in v["buckets"] for r in b["items"])    # brevity prints no numbers


def test_a_cockpit_pass_leaves_out_what_was_settled_in_the_cockpit_when_it_numbers():
    rows = [sec("inbox", "inbox", [item("i1", "Sign"), item("i2", "Read"), item("i3", "Pay")])]
    settled = {"dismissed": ["inbox:i1"], "hidden": {}}
    v = bv.build(result(*rows, numbering_settled=settled), profile({"style": "calm"}, _whole=True))
    nr = {r["title"]: r.get("nr") for b in v["buckets"] for r in b["items"]}
    assert nr == {"Sign": None, "Read": 1, "Pay": 2}


def test_obsolete_is_an_answer_of_every_numbered_row_with_the_cockpits_act():
    """"3 veraltet" (or "3 obsolete") answers any numbered row as the cockpit's fixed last answer Obsolete does:
    one act per kind of row, written down where the briefing reads its answers (control.md) and in both docs."""
    control = (ROOT / "skills" / "briefing" / "references" / "control.md").read_text(encoding="utf-8")
    row = next((line for line in control.splitlines() if line.startswith("|") and "veraltet" in line and "obsolete" in line), "")
    assert row, "the answer table names veraltet and obsolete"
    for act in ("inbox.py drop", "--reason outdated", "task.py close", "--declined", "--stream", "GitHub"):
        assert act in control, act
    for doc in ("briefings.md", "bridge-cockpit.md"):
        text = (ROOT / "docs" / doc).read_text(encoding="utf-8")
        assert re.search(r"veraltet", text) and re.search(r"[Oo]bsolete", text), doc
