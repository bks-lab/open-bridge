# SPDX-License-Identifier: MIT
"""Jev page of the cockpit (scripts/lib/bridge_cockpit/jev.py): state, questions, plan, cache, key.
No request leaves the test: the API call and the key are injected."""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.bridge_cockpit import jev  # noqa: E402

MODEL = {"sections": [{"rows": [
    {"key": "a", "title": "Customer waits for invoices", "priority": "P0", "why": ["customer asks"], "tab": {"ref": "x"}},
    {"key": "b", "title": "Tidy the labels", "why": []},
    {"key": "a", "title": "Customer waits for invoices"},
]}], "task_rows": [{"key": "c", "title": "Sign the offer", "gate": "only-you"}, {"key": "d", "title": ""}]}


def answers(tasks, first="t1"):
    out = {}
    for i, t in enumerate(tasks):
        hi = i == 0
        out[f"{t['id']}.urgency"] = {"type": "score", "score": 3 if hi else 0, "confidence": 0.9}
        out[f"{t['id']}.impact"] = {"type": "score", "score": 3 if hi else 1, "confidence": 0.8}
        out[f"{t['id']}.effort"] = {"type": "score", "score": 1, "confidence": 0.7}
        out[f"{t['id']}.only_me"] = {"type": "noul", "noul": 0.2 if hi else 0.9}
    out["first"] = {"type": "choice", "choice": first, "probabilities": {first: 0.8}, "confidence": 0.6}
    return {"model": "jev-test", "answers": out, "usage": {"input_tokens": 1, "output_tokens": 1}}


def test_collect_dedupes_and_trims():
    tasks = jev.collect_tasks(MODEL)
    assert [t["title"] for t in tasks] == ["Customer waits for invoices", "Tidy the labels", "Sign the offer"]
    assert [t["id"] for t in tasks] == ["t1", "t2", "t3"]
    assert "tab" not in tasks[0] and "why" not in tasks[1]
    assert len(jev.collect_tasks({"task_rows": [{"key": str(i), "title": f"x{i}"} for i in range(50)]})) == jev.MAX_TASKS


def test_request_has_four_questions_per_task_and_one_choice():
    tasks = jev.collect_tasks(MODEL)
    req = jev.build_request(tasks, "2026-10-10")
    assert req["model"] == jev.MODEL == "jev-1.14.0"
    assert len(req["questions"]) == 4 * len(tasks) + 1
    assert set(req["questions"]["first"]["criteria"]) == {"t1", "t2", "t3"}
    assert "`tasks[1]`" in req["questions"]["t2.urgency"]["instructions"]
    assert all("key" not in a for a in req["state"]["tasks"])


def test_request_names_the_person_from_config_and_nobody_by_default():
    tasks = jev.collect_tasks(MODEL)
    neutral = json.dumps(jev.build_request(tasks, "2026-10-10"), ensure_ascii=False)
    assert "the user" in neutral                       # English unless the Bridge speaks another language
    named = jev.build_request(tasks, "2026-10-10", who="Ada", about="Ada, leads a small team")
    assert named["state"]["person"] == "Ada, leads a small team"
    assert "for Ada on day" in named["questions"]["t1.urgency"]["instructions"]
    de = jev.build_request(tasks, "2026-10-10", lang="de")         # the German table, quoted as it renders
    assert "`aufgaben[0]`" in de["questions"]["t1.urgency"]["instructions"] and "aufgaben" in de["state"]
    assert "dem Nutzer" in json.dumps(de, ensure_ascii=False) or "der Nutzer" in json.dumps(de, ensure_ascii=False)


def test_plan_ranks_and_classifies():
    tasks = jev.collect_tasks(MODEL)
    plan = jev.plan_from(tasks, answers(tasks))
    top = plan["items"][0]
    assert top["id"] == "t1" and top["rank"] == 1 and top["quadrant"] == "now" and top["who"] == "delegate"
    assert plan["first"] == "t1"
    assert {it["who"] for it in plan["items"][1:]} == {"me"}
    assert plan["items"][-1]["quadrant"] == "drop"


def test_jev_choice_leads_the_ranking():
    tasks = jev.collect_tasks(MODEL)
    plan = jev.plan_from(tasks, answers(tasks, first="t3"))
    assert plan["first"] == "t3" and plan["items"][0]["id"] == "t3" and plan["items"][1]["id"] == "t1"


def test_plan_survives_missing_answers_and_unknown_choice():
    tasks = jev.collect_tasks(MODEL)
    plan = jev.plan_from(tasks, {"answers": {"first": {"choice": "zz"}}})
    assert all(it["urgency"] == 0.5 and it["only_me"] == 0.5 for it in plan["items"])
    assert plan["first"] == plan["items"][0]["id"]


def fake_app(model, state_dir=None, now=1_760_000_000_000):
    clock = {"ms": now}
    app = types.SimpleNamespace(collector=types.SimpleNamespace(model=model), clock=lambda: clock["ms"])
    if state_dir is not None:
        app.state_dir = state_dir
    app.set_ms = lambda ms: clock.update(ms=ms)
    return app


DAY_MS = 86_400_000


def test_run_caches_same_rows_and_force_asks_again():
    calls = []

    def call(payload, key):
        calls.append(key)
        return answers(jev.collect_tasks(MODEL))

    app = fake_app(MODEL)
    a = jev.run(app, {}, call=call, key=lambda: "k")
    b = jev.run(app, {}, call=call, key=lambda: "k")
    c = jev.run(app, {"force": True}, call=call, key=lambda: "k")
    assert (a["cached"], b["cached"], c["cached"]) == (False, True, False)
    assert calls == ["k", "k"]
    assert a["questions"] == 13 and a["plan"]["items"][0]["id"] == "t1"


def test_cache_only_never_calls_and_reports_stale_rows():
    calls = []

    def call(payload, key):
        calls.append(key)
        return answers(jev.collect_tasks(MODEL))

    app = fake_app(MODEL)
    first = jev.run(app, {"cache_only": True}, call=call, key=lambda: pytest.fail("no key for a cache probe"))
    assert first["stale"] is True and first["digest"] and calls == []
    rated = jev.run(app, {}, call=call, key=lambda: "k")
    again = jev.run(app, {"cache_only": True}, call=call, key=lambda: "k")
    assert again["cached"] is True and again["digest"] == rated["digest"] == first["digest"]
    assert "stale" not in again and calls == ["k"]
    app.collector.model = {"sections": [{"rows": [{"key": "z", "title": "Neue Aufgabe"}]}]}
    changed = jev.run(app, {"cache_only": True}, call=call, key=lambda: "k")
    assert changed["cached"] is True and changed["changed"] is True and calls == ["k"], "today's rating stands"
    forced = jev.run(app, {"cache_only": True, "force": True}, call=call, key=lambda: "k")
    assert forced["cached"] is False and calls == ["k", "k"]
    with pytest.raises(jev.JevError):
        jev.run(app, {"cache_only": "ja"})


def test_run_rejects_unknown_fields_and_handles_empty():
    with pytest.raises(jev.JevError):
        jev.run(fake_app(MODEL), {"evil": 1})
    with pytest.raises(jev.JevError):
        jev.run(fake_app(MODEL), {"force": "yes"})
    out = jev.run(fake_app({}), {}, call=lambda *_: pytest.fail("no call for no rows"))
    assert out["empty"] is True


def test_key_from_env_or_the_configured_keychain_ref():
    assert jev.resolve_key({"TYPESAFE_API_KEY": " s "}) == "s"
    seen = {}

    def run(argv, **kw):
        seen["argv"] = argv
        return types.SimpleNamespace(returncode=0, stdout="abc\n")

    assert jev.resolve_key({}, run=run, ref="keychain://svc/acct") == "abc"
    assert seen["argv"] == ["/usr/bin/security", "find-generic-password", "-s", "svc", "-a", "acct", "-w"]
    with pytest.raises(jev.JevError):
        jev.resolve_key({}, run=run, ref="op://nope")
    with pytest.raises(jev.JevError):                       # nothing configured: no name of anyone's key in the code
        jev.resolve_key({}, run=run)
    with pytest.raises(jev.JevError):
        jev.resolve_key({}, run=lambda *a, **k: types.SimpleNamespace(returncode=44, stdout=""), ref="keychain://svc/acct")


def cfg_app(enabled, ref=None, env=None):
    app = fake_app(MODEL)
    app.cfg = types.SimpleNamespace(jev_enabled=enabled, jev_key_ref=ref)
    app.environ = env or {}
    return app


def test_status_is_off_unless_switched_on_and_ready_only_with_a_key():
    assert jev.status(cfg_app(False)) == {"enabled": False, "ready": False, "reason": "off"}
    found = lambda argv, **kw: types.SimpleNamespace(returncode=0, stdout="")          # noqa: E731
    missing = lambda argv, **kw: types.SimpleNamespace(returncode=44, stdout="")       # noqa: E731
    assert jev.status(cfg_app(True, "keychain://svc/acct"), run=found) == {"enabled": True, "ready": True, "reason": None}
    assert jev.status(cfg_app(True, "keychain://svc/acct"), run=missing)["reason"] == "no_key"
    assert jev.status(cfg_app(True, None))["reason"] == "no_key_ref"
    assert jev.status(cfg_app(True, None, {"TYPESAFE_API_KEY": "x"}))["ready"] is True
    seen = []
    jev.status(cfg_app(True, "keychain://svc/acct"), run=lambda argv, **kw: seen.append(argv) or found(argv))
    assert seen == [["/usr/bin/security", "find-generic-password", "-s", "svc", "-a", "acct"]]   # never -w: no secret read


def test_once_per_day_by_itself_and_kept_across_a_restart(tmp_path):
    calls = []

    def call(payload, key):
        calls.append(payload["state"]["today"])
        return answers(jev.collect_tasks(MODEL))

    app = fake_app(MODEL, tmp_path)
    first = jev.run(app, {}, call=call, key=lambda: "k")
    assert first["cached"] is False and first["usage"] == {"input_tokens": 1, "output_tokens": 1}
    assert first["price"] is None, "the API names no price, nothing is estimated"
    assert first["today"]["ratings"] == 1 and (tmp_path / "jev.json").exists()
    # the dashboard changes later the same day: no second automatic rating, only the note
    app.collector.model = {"sections": [{"rows": [{"key": "z", "title": "Neue Aufgabe"}]}]}
    later = jev.run(app, {}, call=call, key=lambda: "k")
    assert later["cached"] is True and later["changed"] is True and len(calls) == 1
    assert later["at_ms"] == first["at_ms"]
    # a restart reads jev.json: still today's rating, still no call
    again = fake_app(app.collector.model, tmp_path)
    kept = jev.run(again, {}, call=call, key=lambda: "k")
    assert kept["cached"] is True and kept["digest"] == first["digest"] and len(calls) == 1
    # the button always rates, and the day's total grows
    forced = jev.run(again, {"force": True}, call=call, key=lambda: "k")
    assert forced["cached"] is False and forced["today"]["ratings"] == 2
    assert forced["today"]["input_tokens"] == 2 and forced["today"]["output_tokens"] == 2
    # the first request of the next day rates once by itself, the total starts again
    again.set_ms(1_760_000_000_000 + DAY_MS)
    nextday = jev.run(again, {}, call=call, key=lambda: "k")
    assert nextday["cached"] is False and nextday["today"]["ratings"] == 1 and len(calls) == 3
    assert calls[0] != calls[2]
    assert jev.run(again, {}, call=call, key=lambda: "k")["cached"] is True and len(calls) == 3


def test_tokens_never_invented():
    assert jev.tokens_of({"input_tokens": 296, "output_tokens": 20}) == {"input_tokens": 296, "output_tokens": 20}
    assert jev.tokens_of(None) == {"input_tokens": None, "output_tokens": None}
    assert jev.tokens_of({"input_tokens": -1, "output_tokens": True}) == {"input_tokens": None, "output_tokens": None}
    st = jev.JevState()
    t = st.count("2026-10-10", {"input_tokens": None, "output_tokens": None})
    assert t["unknown"] == 1 and t["input_tokens"] == 0


def test_a_broken_store_file_is_ignored(tmp_path):
    (tmp_path / "jev.json").write_text("{not json", encoding="utf-8")
    calls = []
    app = fake_app(MODEL, tmp_path)
    out = jev.run(app, {}, call=lambda p, k: calls.append(1) or answers(jev.collect_tasks(MODEL)), key=lambda: "k")
    assert out["cached"] is False and calls == [1]


# ------------------------------------------------------------------ order of a work page (jev: on a page)
# A page with `jev:` gets an order on a click: its task and inbox rows go to Jev, except the sections it
# names in skip_sections, rows matching a `private` word, and rows the triage says can go or an agent does.
# Only title, a one-line gist, a short label and the priority leave the machine. Never by itself.

WORK = [
    {"id": "inbox", "kind": "inbox", "title": "Waiting for you", "items": [
        {"title": "Customer waits for approval", "detail": "decision · your-yes", "inbox": "i1", "priority": None},
        {"title": "Watch Sam's game PC", "detail": "finding", "inbox": "i2"},
        {"title": "Rotate the log", "detail": "finding", "inbox": "i3"},
        {"title": "Fill in the reference sheet", "detail": "draft", "inbox": "i5", "source": "applications"},
        {"title": "Customer waits for approval", "detail": "decision", "inbox": "i1"}]},
    {"id": "ideen", "kind": "inbox", "title": "Ideas (one question per idea)", "items": [
        {"title": "New idea", "inbox": "i4"}]},
    {"id": "tasks", "kind": "tasks", "title": "Tasks", "items": [
        {"title": "Write the offer", "detail": "P1 · acme", "task": "angebot", "priority": "P1", "state": "doing"},
        {"title": "Taxes", "detail": "P2 · privat", "task": "taxes"}]},
    {"id": "bewerbungen", "kind": "command", "title": "Applications", "items": [
        {"title": "Follow-up company X", "detail": "", "task": None}]},
    {"id": "workplace", "kind": "workplace", "title": "Workplace today", "items": [
        {"title": "Write the offer", "task": "angebot"}]},
]
TRIAGE = {"inbox:i3": {"verdict": "keep", "doer": "ai", "gist": "log rotation"},
          "inbox:i1": {"verdict": "keep", "doer": "you", "gist": "approval for the customer"},
          "task:angebot": {"verdict": "continue", "doer": "you", "gist": "finish the offer"}}
CFG = {"skip_sections": ["bewerbungen"], "private": ["privat", "Sam", "applications"]}


def test_work_rows_leave_out_private_skipped_sections_and_agent_work():
    rows, skipped = jev.pick_rows(WORK, TRIAGE, CFG)
    assert [r["key"] for r in rows] == ["inbox:i1", "inbox:i4", "task:angebot"]
    assert skipped == {"private": 3, "section": 1, "triage": 1}      # the source of an inbox item counts too
    first = rows[0]
    # only what Jev needs, never the detail text, the path or the item id
    assert set(first) == {"key", "title", "gist", "label"}
    assert first["gist"] == "approval for the customer" and first["label"] == "Waiting for you"
    assert rows[2]["priority"] == "P1"
    assert rows[1]["label"] == "Ideas"           # a long section title is cut at its bracket


def test_work_rows_without_config_take_every_keyed_row():
    rows, skipped = jev.pick_rows(WORK, {}, {})
    assert [r["key"] for r in rows] == ["inbox:i1", "inbox:i2", "inbox:i3", "inbox:i5", "inbox:i4", "task:angebot", "task:taxes"]
    assert skipped == {"private": 0, "section": 0, "triage": 0}


def work_app(tmp_path=None, now=1_760_000_000_000):
    page = {"id": "arbeit", "title": "Arbeit", "jev": CFG,
            "sections": [{k: v for k, v in s.items() if k != "items"} | {"items": s["items"]} for s in WORK]}
    by = {s["id"]: s["items"] for s in WORK}
    collector = types.SimpleNamespace(view={"pages": [page]}, model={},
                                      page_items=lambda p, s: (by[s], len(by[s])) if p == "arbeit" else None)
    app = types.SimpleNamespace(collector=collector, clock=lambda: now,
                                triage=types.SimpleNamespace(state=lambda: {"items": TRIAGE}))
    if tmp_path is not None:
        app.state_dir = tmp_path
    return app


def test_rank_orders_on_the_click_and_keeps_the_order(tmp_path):
    sent = []

    def call(payload, key):
        sent.append(payload)
        return answers([{"id": t["id"]} for t in payload["state"]["tasks"]], first="t2")

    app = work_app(tmp_path)
    # without a click nothing goes out: the page asks for the last order only
    plain = jev.rank(app, {"page": "arbeit"}, call=call, key=lambda: "k")
    assert (plain["ok"], plain["page"], plain["order"], plain["today"]["ratings"]) == (True, "arbeit", None, 0)
    assert sent == []
    out = jev.rank(app, {"page": "arbeit", "force": True}, call=call, key=lambda: "k")
    order = out["order"]
    assert [x["key"] for x in order["items"]] == ["inbox:i4", "inbox:i1", "task:angebot"]
    assert order["items"][0]["rank"] == 1 and order["first"] == "inbox:i4"
    assert order["skipped"] == {"private": 3, "section": 1, "triage": 1, "over": 0} and order["sent"] == 3
    assert order["usage"] == {"input_tokens": 1, "output_tokens": 1}
    # what left the machine: no key, no detail, no id of an inbox item
    text = json.dumps(sent[0], ensure_ascii=False)
    assert "Sam" not in text and "Taxes" not in text and "Follow-up" not in text and "i1" not in text
    assert "Referenzblatt" not in text and "applications" not in text
    # the order stands after a restart, and a plain request answers it without a call
    again = jev.rank(work_app(tmp_path), {"page": "arbeit"}, call=call, key=lambda: "k")
    assert again["order"]["items"] == order["items"] and len(sent) == 1


def test_rank_daily_orders_once_a_day_by_itself(tmp_path):
    # the work page's Jev view asks with daily: the first request of a day orders, later ones of the
    # same day answer the kept order without a call, the next day orders again; the private filter
    # of the page applies as on the click
    sent = []

    def call(payload, key):
        sent.append(payload)
        return answers([{"id": t["id"]} for t in payload["state"]["tasks"]], first="t2")

    day = 1_760_000_000_000
    first = jev.rank(work_app(tmp_path, now=day), {"page": "arbeit", "daily": True}, call=call, key=lambda: "k")
    assert len(sent) == 1 and first["order"]["sent"] == 3 and first["order"]["skipped"]["private"] == 3
    assert first["today"]["ratings"] == 1
    later = jev.rank(work_app(tmp_path, now=day + 3_600_000), {"page": "arbeit", "daily": True}, call=call, key=lambda: "k")
    assert len(sent) == 1 and later["order"]["at_ms"] == first["order"]["at_ms"]
    jev.rank(work_app(tmp_path, now=day + 86_400_000), {"page": "arbeit", "daily": True}, call=call, key=lambda: "k")
    assert len(sent) == 2


def test_rank_order_carries_what_the_matrix_draws(tmp_path):
    # the matrix of the Jev view names a dot and rings it by confidence: both stay in the kept order
    out = jev.rank(work_app(tmp_path), {"page": "arbeit", "force": True},
                   call=lambda p, k: answers([{"id": t["id"]} for t in p["state"]["tasks"]]), key=lambda: "k")
    item = out["order"]["items"][0]
    assert item["title"] and item["confidence"] == 0.85 and item["quadrant"] in ("now", "plan", "hand", "drop")


def test_rank_refuses_daily_that_is_not_a_flag():
    with pytest.raises(jev.JevError) as e:
        jev.rank(work_app(), {"page": "arbeit", "daily": "yes"})
    assert e.value.code == "invalid_argument"


def test_rank_sends_more_than_one_batch_and_merges_by_priority(monkeypatch):
    monkeypatch.setattr(jev, "MAX_TASKS", 2)
    calls = []

    def call(payload, key):
        calls.append([t["title"] for t in payload["state"]["tasks"]])
        return answers([{"id": t["id"]} for t in payload["state"]["tasks"]])

    out = jev.rank(work_app(), {"page": "arbeit", "force": True}, call=call, key=lambda: "k")
    assert len(calls) == 2 and sorted(len(c) for c in calls) == [1, 2]
    items = out["order"]["items"]
    assert [x["rank"] for x in items] == [1, 2, 3]
    assert out["order"]["usage"] == {"input_tokens": 2, "output_tokens": 2}


def test_rank_refuses_a_page_without_jev_and_unknown_fields():
    app = work_app()
    with pytest.raises(jev.JevError) as e:
        jev.rank(app, {"page": "nope"})
    assert e.value.code == "not_found"
    with pytest.raises(jev.JevError) as e:
        jev.rank(app, {"page": "arbeit", "x": 1})
    assert e.value.code == "invalid_argument"


def test_the_source_of_an_inbox_item_is_read_from_its_folder(tmp_path):
    folder = tmp_path / "work" / "inbox" / "20261012-1708-referenzblatt-524a"
    folder.mkdir(parents=True)
    (folder / "item.yaml").write_text("schema_version: 1\nfrom: applications\nkind: draft\nsummary: Referenzblatt\n",
                                      encoding="utf-8")
    page = {"id": "w", "jev": {"private": ["applications"]}, "sections": [{"id": "inbox", "kind": "inbox", "title": "Inbox"}]}
    items = [{"title": "Referenzblatt", "inbox": "20261012-1708-referenzblatt-524a"}, {"title": "Anderes", "inbox": "x-1"}]
    app = types.SimpleNamespace(root=tmp_path, collector=types.SimpleNamespace(
        view={"pages": [page]}, page_items=lambda p, s: (items, 2)))
    cfg, sections = jev._work_page(app, "w")
    assert [it.get("source") for it in sections[0]["items"]] == ["applications", None]
    rows, skipped = jev.pick_rows(sections, {}, cfg)
    assert [r["title"] for r in rows] == ["Anderes"] and skipped["private"] == 1


# ------------------------------------------------------------------ one order at a time per page (#383)
# Two open tabs both ask with daily on load; the second waits for the first and answers its order instead
# of paying for it again. Tokens are booked after every batch, so a later failure keeps what was spent.

def _blocking_call(entered, release, sent):
    def call(payload, key):
        sent.append(payload)
        entered.set()
        assert release.wait(5), "the test never released the first call"
        return answers([{"id": t["id"]} for t in payload["state"]["tasks"]], first="t2")
    return call


def test_rank_two_daily_requests_for_one_page_call_jev_once(tmp_path):
    import threading
    import time as _time
    entered, release, sent, out = threading.Event(), threading.Event(), [], {}
    call = _blocking_call(entered, release, sent)
    app = work_app(tmp_path)

    def ask(name):
        out[name] = jev.rank(app, {"page": "arbeit", "daily": True}, call=call, key=lambda: "k")

    first = threading.Thread(target=ask, args=("first",))
    first.start()
    assert entered.wait(5)
    second = threading.Thread(target=ask, args=("second",))
    second.start()
    _time.sleep(0.2)                  # the second request is now waiting, or has called Jev itself
    release.set()
    first.join(5)
    second.join(5)
    assert len(sent) == 1
    assert out["first"]["order"] == out["second"]["order"]
    assert out["second"]["today"]["ratings"] == 1


def test_rank_a_click_while_an_order_runs_answers_that_order(tmp_path):
    import threading
    import time as _time
    entered, release, sent, out = threading.Event(), threading.Event(), [], {}
    call = _blocking_call(entered, release, sent)
    app = work_app(tmp_path)

    def ask(name):
        out[name] = jev.rank(app, {"page": "arbeit", "force": True}, call=call, key=lambda: "k")

    first = threading.Thread(target=ask, args=("first",))
    first.start()
    assert entered.wait(5)
    second = threading.Thread(target=ask, args=("second",))
    second.start()
    _time.sleep(0.2)
    release.set()
    first.join(5)
    second.join(5)
    assert len(sent) == 1 and out["first"]["order"] == out["second"]["order"]
    # a later click, with nothing running, asks Jev again
    jev.rank(app, {"page": "arbeit", "force": True}, call=call, key=lambda: "k")
    assert len(sent) == 2


def test_rank_different_pages_order_in_parallel(tmp_path):
    import threading
    app = work_app(tmp_path)
    page = app.collector.view["pages"][0]
    app.collector.view["pages"].append({**page, "id": "zwei"})
    by = {s["id"]: s["items"] for s in WORK}
    app.collector.page_items = lambda p, s: (by[s], len(by[s]))
    inside = {"arbeit": threading.Event(), "zwei": threading.Event()}
    seen, out = [], {}

    def call_for(page_id, other):
        def call(payload, key):
            inside[page_id].set()
            # each page's call waits until the other page's call is running too: serialised, they would not meet
            seen.append(inside[other].wait(3))
            return answers([{"id": t["id"]} for t in payload["state"]["tasks"]])
        return call

    def ask(page_id, other):
        out[page_id] = jev.rank(app, {"page": page_id, "force": True}, call=call_for(page_id, other), key=lambda: "k")

    threads = [threading.Thread(target=ask, args=("arbeit", "zwei")), threading.Thread(target=ask, args=("zwei", "arbeit"))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert seen == [True, True] and set(out) == {"arbeit", "zwei"}


def test_rank_tokens_of_finished_batches_stay_counted_when_a_later_batch_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(jev, "MAX_TASKS", 1)
    n = []

    def call(payload, key):
        n.append(1)
        if len(n) == 3:
            raise jev.JevError(502, "jev_failed", "upstream broke")
        out = answers([{"id": t["id"]} for t in payload["state"]["tasks"]])
        out["usage"] = {"input_tokens": 10 * len(n), "output_tokens": len(n)}
        return out

    app = work_app(tmp_path)
    with pytest.raises(jev.JevError):
        jev.rank(app, {"page": "arbeit", "force": True}, call=call, key=lambda: "k")
    assert len(n) == 3
    today = jev._state(app).today
    assert (today["input_tokens"], today["output_tokens"], today["ratings"]) == (30, 3, 1)
    assert jev._pages_state(app).orders.get("arbeit") is None
    # the booked tokens reach jev.json as well, so a restart keeps them
    again = jev.rank(work_app(tmp_path), {"page": "arbeit"}, call=call, key=lambda: "k")
    assert again["today"]["input_tokens"] == 30


def test_rank_counts_a_multi_batch_order_as_one_rating(monkeypatch, tmp_path):
    monkeypatch.setattr(jev, "MAX_TASKS", 1)
    out = jev.rank(work_app(tmp_path), {"page": "arbeit", "force": True},
                   call=lambda p, k: answers([{"id": t["id"]} for t in p["state"]["tasks"]]), key=lambda: "k")
    assert out["order"]["calls"] == 3
    assert (out["today"]["ratings"], out["today"]["input_tokens"], out["today"]["unknown"]) == (1, 3, 0)


def test_rank_two_daily_requests_on_a_fresh_app_call_jev_once(monkeypatch, tmp_path):
    # a restarted cockpit with two tabs: both first requests arrive before either state exists. A slow
    # read of the state files widens the window in which each thread would build a state of its own.
    import threading
    import time as _time
    read = jev.read_json

    def slow_read(path):
        _time.sleep(0.05)
        return read(path)

    monkeypatch.setattr(jev, "read_json", slow_read)
    sent, out, start = [], {}, threading.Barrier(2)

    def call(payload, key):
        sent.append(payload)
        out_ = answers([{"id": t["id"]} for t in payload["state"]["tasks"]])
        out_["usage"] = {"input_tokens": 7, "output_tokens": 2}
        return out_

    app = work_app(tmp_path)

    def ask(name):
        start.wait(5)
        out[name] = jev.rank(app, {"page": "arbeit", "daily": True}, call=call, key=lambda: "k")

    threads = [threading.Thread(target=ask, args=(n,)) for n in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert len(sent) == 1 and out["a"]["order"] == out["b"]["order"]
    today = jev._state(app).today
    assert (today["ratings"], today["input_tokens"]) == (1, 7)
    assert jev._pages_state(app).orders["arbeit"] == out["a"]["order"]
