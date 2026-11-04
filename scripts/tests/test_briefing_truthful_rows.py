# SPDX-License-Identifier: MIT
"""A briefing's rows say what is true and stand where they belong.

One morning's audit found no shown row in its right place: rows settled in the cockpit came back, a row put off
led the list, an overdue promise sorted last, whole buckets fell away unsaid, and a task's row named only its
next step, so nobody could tell what it was about.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


bf = sys.modules.get("briefing") or _load("briefing", ROOT / "scripts" / "briefing.py")
bv = _load("briefing_view", ROOT / "scripts" / "lib" / "briefing_view.py")
inbox = sys.modules.get("inbox") or _load("inbox", ROOT / "scripts" / "inbox.py")

NOW = dt.datetime(2026, 10, 5, 7, 45)


def sec(sid, kind, items, **extra):
    return {"id": sid, "kind": kind, "title": sid, "status": "ok", "items": items, "all": items, "total": len(items), **extra}


def result(*sections, **extra):
    return {"profile": "morning", "title": "Morning", "collected_at": NOW.isoformat(timespec="minutes"),
            "sections": list(sections), **extra}


def profile(view=None, sections=None, **extra):
    return {"schema_version": 1, "scope": "user", "id": "morning", "for": "alice",
            "view": {"style": "triage", **(view or {})},
            "sections": sections or [{"kind": "inbox"}, {"kind": "advise"}, {"kind": "tasks"},
                                     {"kind": "tracker", "id": "gh", "provider": "github"}], **extra}


def ask(iid, title, **kw):
    return {"id": iid, "title": title, "state": kw.pop("state", "open"), "urgency": kw.pop("urgency", "later"),
            "kind": kw.pop("kind", "decision"), "gate": kw.pop("gate", "your-yes"), "due": kw.pop("due", None),
            "task": kw.pop("task", None), **kw}


def task(slug, title, nxt=None, **kw):
    return {"id": slug, "title": title, "state": "doing", "next": nxt, "changed_at": "2026-10-04",
            "url": f"work/tasks/{slug}/STATUS.md", **kw}


def titles(view):
    return {b["id"]: [i["title"] for i in b["items"]] for b in view["buckets"]}


# ---------------------------------------------------------------- settled in the cockpit


def test_a_row_settled_in_the_cockpit_does_not_come_back():
    r = result(sec("gh", "tracker", [{"id": "acme/app#7", "title": "Review the draft", "state": "review"},
                                     {"id": "acme/app#8", "title": "Still open", "state": "review"}]),
               settled={"dismissed": ["ref:acme/app#7"], "hidden": {}})
    view = bv.build(r, profile())
    assert titles(view)["do"] == ["Still open"]
    assert any("1" in line and "cockpit" in line.lower() for line in view["hygiene"])


def test_the_status_line_does_not_count_a_settled_row():
    sections = [{"kind": "command", "id": "dl", "report_ok": True, "argv": ["x"]}]
    r = result(sec("dl", "command", [{"id": "m:1", "title": "Promise", "state": "ready"}]),
               settled={"dismissed": ["ref:m:1"], "hidden": {}})
    assert "⚠" not in bv.draw(bv.build(r, profile(view={"style": "report"}, sections=sections)))


def test_a_row_hidden_in_the_cockpit_stays_away_until_its_day():
    r = result(sec("tasks", "tasks", [task("t1", "Portal", nxt={"what": "Check the portal", "who": "me"})]),
               settled={"dismissed": [], "hidden": {"task:t1": "2026-10-09"}})
    assert not bv.build(r, profile())["buckets"]
    r["settled"]["hidden"]["task:t1"] = "2026-10-05"       # its day has come
    assert bv.build(r, profile())["buckets"]


def test_without_a_settled_record_the_view_is_what_it_was():
    """The cockpit keeps its own record and its own Show again: it builds without `settled`."""
    r = result(sec("gh", "tracker", [{"id": "acme/app#7", "title": "Review the draft", "state": "review"}]))
    assert titles(bv.build(r, profile()))["do"] == ["Review the draft"]


def test_render_reads_the_settled_record(tmp_path):
    root = tmp_path / "b"
    folder = root / "work" / "cockpit" / "settled"
    folder.mkdir(parents=True)
    (folder / "20261001T000000Z-000-aaaa-dismiss.yaml").write_text(
        yaml.safe_dump({"schema_version": 1, "key": "ref:acme/app#7", "act": "dismiss", "outcome": "done", "title": "x"}))
    (folder / "20261001T000000Z-000-bbbb-hide.yaml").write_text(
        yaml.safe_dump({"schema_version": 1, "key": "task:t1", "act": "hide", "until": "2026-10-09"}))
    (folder / "20261001T000000Z-000-cccc-hide.yaml").write_text(
        yaml.safe_dump({"schema_version": 1, "key": "task:t2", "act": "hide", "until": "2026-10-01"}))
    got = bf.settled_record(root, NOW)
    assert got == {"dismissed": ["ref:acme/app#7"], "hidden": {"task:t1": "2026-10-09"}}
    assert bf.settled_record(tmp_path / "none", NOW) == {"dismissed": [], "hidden": {}}


# ---------------------------------------------------------------- put off, waiting


def test_a_row_put_off_past_the_lookahead_does_not_stand_in_do_for_being_only_yours():
    r = result(sec("inbox", "inbox", [ask("i1", "Keep the raise or object", state="deferred", until="2026-10-06",
                                          gate="only-you", due="2026-10-30"),
                                      ask("i2", "Open today", urgency="today")]))
    got = titles(bv.build(r, profile()))
    assert got["do"] == ["Open today"] and got["plan"] == ["Keep the raise or object"]


def test_a_row_put_off_and_due_within_the_lookahead_stays_in_do():
    r = result(sec("inbox", "inbox", [ask("i1", "Post the note", state="deferred", until="2026-10-06",
                                          gate="only-you", due="2026-10-06")]))
    assert titles(bv.build(r, profile()))["do"] == ["Post the note"]


def test_a_row_put_off_on_someone_waits_for_them():
    r = result(sec("inbox", "inbox", [ask("i1", "The agent's answer", state="deferred", until="2026-10-06",
                                          gate="only-you", due="2026-10-20", waiting_on="Alex")]))
    view = bv.build(r, profile())
    row = next(b for b in view["buckets"] if b["id"] == "waiting")["items"][0]
    assert any("Alex" in w for w in row["why"])


def test_the_inbox_section_says_what_a_put_off_item_waits_on(tmp_path):
    root = tmp_path / "b"
    (root / "work" / "inbox").mkdir(parents=True)
    box = inbox.Inbox(root / "work" / "inbox", actor="test", clock=lambda: NOW)
    item = box.add(source="t", kind="question", summary="The agent's answer", gate="only-you")
    box.event(item, "defer", until="2026-10-06", waits_on="Alex")
    p = profile(view={"lookahead_days": 1}, sections=[{"kind": "inbox"}])
    got = bf.collect(root, p, bf.Context(root, now=NOW, cfg={}))["sections"][0]["items"]
    assert got[0]["waiting_on"] == "Alex"


def test_the_inbox_cut_keeps_what_is_due_first(tmp_path):
    root = tmp_path / "b"
    (root / "work" / "inbox").mkdir(parents=True)
    box = inbox.Inbox(root / "work" / "inbox", actor="test", clock=lambda: NOW)
    box.add(source="t", kind="decision", summary="No date", urgency="later")
    box.add(source="t", kind="decision", summary="Due soon", urgency="later", due="2026-10-06")
    got = bf.collect(root, profile(sections=[{"kind": "inbox", "max": 1}]), bf.Context(root, now=NOW, cfg={}))
    assert [i["title"] for i in got["sections"][0]["items"]] == ["Due soon"]


# ---------------------------------------------------------------- order and caps


def test_a_row_forced_into_do_ranks_as_do():
    sections = [{"kind": "inbox"}, {"kind": "command", "id": "dl", "bucket": "do", "argv": ["x"]}]
    r = result(sec("inbox", "inbox", [ask("i1", "Later today", urgency="today")]),
               sec("dl", "command", [{"id": "m:1", "title": "Promise overdue", "state": "ready"}]))
    do = next(b for b in bv.build(r, profile(sections=sections))["buckets"] if b["id"] == "do")["items"]
    assert {i["title"]: i["rank"] for i in do} == {"Later today": 2, "Promise overdue": 2}


def test_no_bucket_falls_away_behind_a_long_plan():
    cards = [{"id": f"acme/app#{n}", "title": f"Card {n}", "state": "ready"} for n in range(40)]
    r = result(sec("gh", "tracker", cards),
               sec("tasks", "tasks", [task("t1", "Refund", blocked_by="Alex", blocked_since="2026-09-20")]))
    view = bv.build(r, profile(view={"max_items": 10}))
    assert [b["id"] for b in view["buckets"]] == ["plan", "waiting"]
    assert sum(len(b["items"]) for b in view["buckets"]) == 10


def test_the_report_says_when_a_whole_bucket_did_not_fit():
    cards = [{"id": f"acme/app#{n}", "title": f"Card {n}", "state": "review"} for n in range(5)]
    r = result(sec("gh", "tracker", cards),
               sec("tasks", "tasks", [task("t1", "Refund", blocked_by="Alex", blocked_since="2026-09-20")]))
    view = bv.build(r, profile(view={"style": "report", "max_items": 3}))
    assert view["dropped"] == 1 and "+1" in bv.draw(view)


def test_the_short_plan_list_prefers_your_own_rows_to_a_board_card():
    sections = [{"kind": "inbox"}, {"kind": "tasks"}, {"kind": "tracker", "id": "gh", "provider": "github"},
                {"kind": "tracker", "id": "board", "provider": "github-board"}]
    r = result(sec("inbox", "inbox", [ask("i1", "Decide the name")]),
               sec("tasks", "tasks", [task("t1", "Portal", nxt={"what": "Approve the mockup", "who": "me"}),
                                      task("t2", "Site", nxt={"what": "Read the draft", "who": "me"})]),
               sec("gh", "tracker", [{"id": f"acme/app#{n}", "title": f"Issue {n}", "state": "ready"} for n in range(3)]),
               sec("board", "tracker", [{"id": f"acme/web#{n}", "title": f"Card {n}", "state": "ready"} for n in range(3)]))
    text = bv.draw(bv.build(r, profile(view={"style": "report", "report": {"top": 1, "per_bucket": 2}}, sections=sections)))
    bucket = text[text.index("### Plan"):]
    assert "Approve the mockup" in bucket and "Read the draft" in bucket and "Issue" not in bucket.split("*+")[0]


def test_two_pieces_of_advice_about_one_item_are_one_row():
    sections = [{"kind": "advise"}]
    r = result(sec("advise", "advise", [
        {"id": "waiting:inbox:i1", "title": "waiting since 30.10: Set up the host", "check": "waiting", "state": "new"},
        {"id": "due:inbox:i1", "title": "due 06.10: Set up the host", "check": "due", "state": "new"}]))
    got = titles(bv.build(r, profile(sections=sections)))
    assert got == {"do": ["due 06.10: Set up the host"]}


# ---------------------------------------------------------------- who is you


def test_a_step_naming_the_person_is_theirs_not_someone_elses():
    r = result(sec("tasks", "tasks", [task("t1", "Portal", nxt={"what": "Try the switch", "who": "Alice Example"})]))
    view = bv.build(r, profile(_person="Alice Example"))
    assert [b["id"] for b in view["buckets"]] == ["plan"]
    assert [b["id"] for b in bv.build(r, profile())["buckets"]] == ["waiting"]


def test_a_profile_carrying_the_person_still_validates():
    data = {"schema_version": 1, "scope": "user", "id": "p", "sections": [], "_person": "Alice"}
    assert not [p for p in bf.profile_problems(data, "p") if "_person" in p]


# ---------------------------------------------------------------- titles a reader understands


def test_a_task_row_is_titled_by_its_h1_and_keeps_its_step_apart():
    # the cockpit's one point view (stage 4): the name is the task's H1, the step stands on a line of its own
    r = result(sec("tasks", "tasks", [task("t1", "Portal redesign", nxt={"what": "Approve in daily use", "who": "me"})]))
    row = bv.build(r, profile())["buckets"][0]["items"][0]
    assert titles(bv.build(r, profile()))["plan"] == ["Portal redesign"]
    assert row["step"] == "Approve in daily use"
    assert "next: Approve in daily use" in row["why"]


def test_a_long_task_title_stays_whole_and_is_never_glued_to_its_step():
    long = "Portal redesign: a long sentence on everything the work should do one day"
    r = result(sec("tasks", "tasks", [task("t1", long, nxt={"what": "Approve it", "who": "me"})]))
    assert titles(bv.build(r, profile()))["plan"] == [long]


def test_a_step_already_naming_its_task_stays_the_step():
    r = result(sec("tasks", "tasks", [task("t1", "Portal", nxt={"what": "Portal: approve it", "who": "me"})]))
    row = bv.build(r, profile())["buckets"][0]["items"][0]
    assert row["title"] == "Portal" and row["step"] == "Portal: approve it"


def test_a_task_row_folded_into_an_inbox_line_gives_the_bare_step():
    r = result(sec("inbox", "inbox", [ask("i1", "Answer the vendor", urgency="today", task="t1")]),
               sec("tasks", "tasks", [task("t1", "Portal", nxt={"what": "Send the draft", "who": "me"})]))
    row = bv.build(r, profile())["buckets"][0]["items"][0]
    assert any(w.endswith("Send the draft") and "Portal" not in w for w in row["why"])


def test_a_machine_stamp_in_a_title_reads_as_a_day():
    r = result(sec("inbox", "inbox", [ask("i1", "Prepare: dentist (2026-10-06 16:30)", urgency="today"),
                                      ask("i2", "Prepare: school (2026-10-20 09:00)", urgency="today")]))
    assert titles(bv.build(r, profile()))["do"] == ["Prepare: dentist (tomorrow 16:30)", "Prepare: school (20.10 09:00)"]


def test_the_headline_names_the_next_date_by_its_topic_not_a_cut_sentence():
    r = result(sec("inbox", "inbox", [ask("i1", "Register both numbers: a fresh captcha each, an hour apart at the least",
                                          due="2026-10-06")]))
    headline = bv.build(r, profile())["headline"]
    assert "Register both numbers" in headline and "fresh captcha" not in headline and "…" not in headline


# ---------------------------------------------------------------- the overlay probe


def test_an_overlay_without_a_materialize_block_is_no_finding():
    up = _load("upstream_items", ROOT / "skills" / "briefing" / "scripts" / "upstream_items.py")
    assert [r["title"] for r in up.overlay_items([{"name": "a", "materialized": False, "materializes": False}])] == []
    assert len(up.overlay_items([{"name": "b", "materialized": False}])) == 1
