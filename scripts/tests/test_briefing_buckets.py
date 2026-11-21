# SPDX-License-Identifier: MIT
"""The briefing's buckets as one rule for the printed briefing and the cockpit (21.11.2026).

Every point stands in exactly one bucket of the profile's `view.buckets`, by the fixed rule of
scripts/lib/briefing_view.py. The cockpit's Work through sorts its cards into the same buckets
(docs/bridge-cockpit.md, Buckets) and shows each card's number in the printed briefing, so the
rule refinements live here, where both read them:

- an inbox item put off waiting on the Bridge is the Bridge's to do (delegate), never "waiting on
  others"; one only you can take on (gate only-you: a login, a send) is yours (do)
- every visible row has a number (`nr`), calm's waiting rows too, the same the renderers print, in the order of
  the buckets (do, plan, delegate, waiting) as the cockpit shows them
- a cockpit pass (every row, `_whole`) numbers as the printed briefing would: its own style,
  its own max_items, without what was settled in the cockpit
- the view names every shown bucket with its title (`bucket_defs`), also an empty one; a bucket has no answers
  of its own, every point takes the four the view carries (`answers`, scripts/lib/answers.py)
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


def test_an_item_you_said_yes_to_is_the_bridges_to_do_never_asked_again():
    # Round 2 (21.11.2026): after a yes (inbox.py approve, the cockpit's Yes) the item still stood in Do as "1 yes",
    # asking for the yes it had. A yes given is the Bridge's to run (delegate); only you can do an only-you one
    rows = [item("i1", "Fix the test plan", state="approved"), item("i2", "Send the offer", state="approved", gate="only-you"),
            item("i3", "Decide the price list")]
    v = bv.build(result(sec("inbox", "inbox", rows)), profile())
    assert bucket_of(v, "Fix the test plan") == "delegate"
    assert bucket_of(v, "Send the offer") == "do"
    assert bucket_of(v, "Decide the price list") == "do"


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

def test_the_view_names_every_shown_bucket_also_an_empty_one_and_its_options_are_ignored():
    buckets = [{"id": "do", "title": "Tun", "options": ["ja", "später", "streichen"]}, {"id": "waiting"},
               {"id": "delegate", "title": "Mache ich", "options": ["los", "nicht jetzt"]}]
    v = bv.build(result(sec("inbox", "inbox", [item("i1", "Sign")])), profile({"style": "triage", "buckets": buckets}))
    assert v["bucket_defs"] == [{"id": "do", "title": "Tun"}, {"id": "waiting", "title": "Waiting on others"},
                                {"id": "delegate", "title": "Mache ich"}]
    assert [a["id"] for a in v["answers"]["answers"]] == ["do", "later", "done", "obsolete"]


def test_without_buckets_in_the_profile_the_defaults_stand_in_their_order():
    v = bv.build(result(sec("inbox", "inbox", [])), profile())
    assert [b["id"] for b in v["bucket_defs"]] == ["do", "plan", "delegate", "waiting"]


# ---------------------------------------------------------------- the numbers

def _rows():
    return [sec("inbox", "inbox", [item("i1", "Sign the contract"), item("i2", "Object", urgency="later"),
                                   deferred("i3", "Agency answers", "Agency"), deferred("i4", "Fix the probe", "Bridge")])]


def _printed_numbers(text):
    return [int(m.group(1)) for m in re.finditer(r"^\s*(\d+)\.?\s", text, re.M)]


def test_calm_numbers_every_visible_row_waiting_included_as_it_prints_them():
    v = bv.build(result(*_rows()), profile({"style": "calm"}))
    nr = {r["title"]: r.get("nr") for b in v["buckets"] for r in b["items"]}
    assert nr == {"Sign the contract": 1, "Object": 2, "Fix the probe": 3, "Agency answers": 4}
    text = bv.draw(v)
    assert "4. Agency (Agency answers) until 23.10" in text and "3. Fix the probe" in text


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


def test_a_cockpit_pass_numbers_as_the_printed_briefing_would_also_with_a_capped_section():
    # round 1 of the simulation: the inbox section has `max: 3`. A view with buckets reads every item of a section
    # (its `all`), the printed run and the cockpit's pass alike, so both put each row in the same bucket and give it
    # the same number; the view's own max_items cuts what is printed
    items = [item(f"i{n}", f"Ask {n}", urgency="later" if n % 2 else "today") for n in range(1, 8)]
    tasks = [{"id": f"t{n}", "title": f"Task {n}", "task": f"t{n}", "state": "doing", "next": {"what": f"step {n}"}}
             for n in range(1, 4)]
    cfg = [{"kind": "inbox", "max": 3}, {"kind": "tasks"}]
    capped = {**sec("inbox", "inbox", items[:3]), "all": items, "total": len(items)}
    printed = bv.build(result(capped, sec("tasks", "tasks", tasks)), profile({"style": "triage", "max_items": 6}, cfg))
    whole = result(sec("inbox", "inbox", items), sec("tasks", "tasks", tasks))
    cockpit = bv.build(whole, profile({"style": "triage", "max_items": 500}, cfg, _whole=True, _print_max=6))
    want = {r["title"]: r.get("nr") for b in printed["buckets"] for r in b["items"]}
    got = {r["title"]: r.get("nr") for b in cockpit["buckets"] for r in b["items"]}
    assert len(got) == 10 and len(want) == 6
    assert {t: n for t, n in got.items() if n} == want
    # every bucket counts the same rows in both, and every row stands in the same bucket
    total = lambda v: {b["id"]: b["total"] for b in v["buckets"]}
    assert total(printed) == total(cockpit)
    bucket = lambda v: {r["title"]: b["id"] for b in v["buckets"] for r in b["items"]}
    assert {t: b for t, b in bucket(cockpit).items() if t in want} == bucket(printed)


def test_numbers_are_unique_and_in_order_in_a_whole_pass():
    # round 1 (words): `render --max-items 300` printed 17 numbers twice and Plan ran 10, 11, 8, 9
    items = [item(f"2026100{n % 9 + 1}-0900-ask-{n}", f"Ask {n}", urgency=("now", "today", "later")[n % 3]) for n in range(30)]
    tasks = [task(f"t{n}", {"what": f"step {n}"}) for n in range(10)]
    cfg = [{"kind": "inbox", "max": 4}, {"kind": "tasks"}]
    whole = result(sec("inbox", "inbox", items), sec("tasks", "tasks", tasks))
    v = bv.build(whole, profile({"style": "triage", "max_items": 300}, cfg, _whole=True, _print_max=12))
    nrs = [r["nr"] for b in v["buckets"] for r in b["items"] if r.get("nr")]
    assert nrs == list(range(1, 13))


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


def test_a_quiet_task_is_named_by_its_title_and_the_advice_stands_beside_it():
    # Round 2: the advice "Check the dashboard untouched for 54 days (park?)" was the point's title, on the card, the
    # list and the toast ("Ins Backlog geparkt: Check the … untouched for…"). The task keeps its own title; how long it
    # rested and the question stand beside it
    advice = {"id": "advise:quiet:dash", "title": "Check the dashboard untouched for 54 days (park?)", "check": "quiet",
              "urgency": "later", "task": "dash"}
    v = bv.build(result(sec("advise", "advise", [advice]), sec("tasks", "tasks", [task("dash", None, title="Check the dashboard")])),
                 profile(sections=[{"kind": "advise"}, {"kind": "tasks"}]))
    row = next(r for b in v["buckets"] for r in b["items"] if r.get("task") == "dash" or r["title"].startswith("Check the dashboard"))
    assert row["title"] == "Check the dashboard"
    assert "park?" not in " ".join(row["why"])


def test_an_item_past_its_sections_max_is_read_itself_never_as_advice_in_another_bucket():
    # Round 1 of the four answers: an inbox item past the section's `max:` stood as the advice "waits on you since
    # 19.07: ..." under Plan, although it is urgent now and only you can do it (Do); which items fell past `max:`
    # moved with every unrelated answer, so a point jumped from Do to Plan. A view with buckets reads every item:
    # the advice folds into the item's own row, in the item's own bucket
    items = [item("20260617-0900-ask-1", "Ask 1"), item("20260719-0900-document-the-backup-check", "Document the backup check",
                                                       urgency="now", gate="only-you")]
    advice = {"id": "advise:waiting:20260719-0900-document-the-backup-check", "check": "waiting", "urgency": "now",
              "title": "waits on you since 19.07: Document the backup check"}
    cfg = [{"kind": "inbox", "max": 1}, {"kind": "advise"}]
    capped = {**sec("inbox", "inbox", items[:1]), "all": items}
    v = bv.build(result(capped, sec("advise", "advise", [advice])), profile({"style": "triage"}, cfg))
    titles = {r["title"]: b["id"] for b in v["buckets"] for r in b["items"]}
    assert titles == {"Ask 1": "do", "Document the backup check": "do"}


def test_advice_standing_alone_for_an_urgent_item_stands_in_do():
    # the advice still stands alone where its item is in no section (muted there, or no inbox section): an item urgent
    # now or today is yours today, as the item's own row would be
    advice = {"id": "advise:waiting:20260719-0900-x", "check": "waiting", "urgency": "now", "title": "waits on you since 19.07: X"}
    later = {"id": "advise:waiting:20260719-0900-y", "check": "waiting", "urgency": "later", "title": "waits on you since 19.07: Y"}
    v = bv.build(result(sec("advise", "advise", [advice, later])), profile({"style": "triage"}, [{"kind": "advise"}]))
    assert {r["title"]: b["id"] for b in v["buckets"] for r in b["items"]} == {advice["title"]: "do", later["title"]: "plan"}
