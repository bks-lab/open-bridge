# SPDX-License-Identifier: MIT
"""Reading in the Prio of Work through (prio.py, jev.rank): the page names the points its work view shows by key, the
server looks each one up in what it knows itself (its rows, the work page's sections, its tabs), holds back what the
page's private words or skip_sections name, merges only the same thing (one key, a tab with its own task), and asks one
of two rankers, Jev (TypeSafe) or Haiku (a small Claude model, off by default), for the same fields per point. The
order says which one made it. Optionally a Jev read-in that fails on a click runs Haiku instead
(cockpit.flow.prio.fallback).

No request leaves the test: Jev's API call, the key and the claude -p run are injected."""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.bridge_cockpit import jev, prio  # noqa: E402
from lib.bridge_cockpit.config import load_web_config  # noqa: E402
from lib.bridge_cockpit.runner import Runner, RunnerRefused, RunResult  # noqa: E402

HAIKU = "claude-haiku-5-5"
NOW = 1_760_000_000_000          # 2025-10-09, a Thursday
TODAY = "2025-10-09"

# what the server knows: its rows by key (collector.resolve), the work page's sections, its tabs
INDEX = {
    "task:offer": {"key": "task:offer", "task": "offer", "title": "Write the offer", "status": "review", "due": "2025-10-10",
                   "created": "2025-10-01", "priority": "P1"},
    "inbox:20251008-0900-ask": {"key": "inbox:20251008-0900-ask", "inbox_id": "20251008-0900-ask", "title": "Approve the quote",
                                "inbox_state": "open"},
    "ref:acme/web#12": {"key": "ref:acme/web#12", "ref": "acme/web#12", "title": "Fix the login form", "due": "2025-10-07"},
    "ref:cal-standup": {"key": "ref:cal-standup", "ref": "cal-standup", "title": "Weekly standup notes", "due": "2025-10-12"},
    "task:old-notes": {"key": "task:old-notes", "task": "old-notes", "title": "Old notes", "status": "doing"},
    # the private word stands only in the detail the server holds; the page never sends it
    "task:year-end": {"key": "task:year-end", "task": "year-end", "title": "Year end", "status": "doing", "detail": "P2 · taxes"},
    "inbox:20251007-0800-dup": {"key": "inbox:20251007-0800-dup", "inbox_id": "20251007-0800-dup", "title": "write  the Offer."},
}
TABS = [{"ref": "surface:7", "name": "research tab", "state": "working"},
        {"ref": "surface:8", "name": "offer tab", "slug": "offer", "state": "working"}]
WORK = [{"id": "inbox", "kind": "inbox", "title": "Inbox", "items": [
            {"title": "Approve the quote", "inbox": "20251008-0900-ask", "detail": "decision"}]},
        {"id": "tasks", "kind": "tasks", "title": "Tasks", "items": [{"title": "Old notes", "task": "old-notes"}]}]
TRIAGE = {"ref:cal-standup": {"verdict": "stale", "doer": "ai", "gist": "nobody reads them"},
          "task:offer": {"verdict": "keep", "doer": "you", "gist": "send it to the customer"}}
CFG = {"private": ["taxes"], "skip_sections": ["tasks"]}

# what the page sends: keys, a running flag, and text the server never trusts
ROWS = [
    {"key": "task:offer", "title": "Something else entirely", "running": False},
    {"key": "inbox:20251008-0900-ask", "title": "Approve the quote"},
    {"key": "tab:surface:7", "title": "research tab", "running": True},
    {"key": "ref:acme/web#12", "title": "Fix the login form"},
    {"key": "ref:cal-standup", "title": "Weekly standup notes"},
    {"key": "task:old-notes", "title": "Old notes"},
    {"key": "task:year-end", "title": "Year end"},
    {"key": "inbox:20251007-0800-dup", "title": "write  the Offer."},
    {"key": "tab:surface:8", "title": "offer tab", "running": True},
    {"key": "inbox:forged-1", "title": "Not on the server"},
    {"key": "tab:surface:99", "title": "No such tab"},
]
SERVER_KEYS = ["task:offer", "inbox:20251008-0900-ask", "tab:surface:7", "ref:acme/web#12", "ref:cal-standup",
               "inbox:20251007-0800-dup"]


# ---------------------------------------------------------------- config (cockpit.flow.prio)

def test_prio_has_its_defaults_haiku_off_and_takes_its_keys_one_by_one(tmp_path):
    cfg = load_web_config(tmp_path, {})
    assert cfg.flow["prio"] == {"fallback": "none", "haiku": {"enabled": False, "budget_per_day": prio.DEFAULT_BUDGET, "model": None}}
    cfg = load_web_config(tmp_path, {"cockpit": {"flow": {"prio": {"fallback": "haiku",
                                                                   "haiku": {"enabled": True, "budget_per_day": 2, "model": "sonnet"}}}}})
    assert cfg.flow["prio"] == {"fallback": "haiku", "haiku": {"enabled": True, "budget_per_day": 2, "model": "sonnet"}}
    assert cfg.config_warnings == ()


@pytest.mark.parametrize("value, key", [
    ({"haiku": {"budget_per_day": -1}}, "haiku.budget_per_day"), ({"haiku": {"enabled": "yes"}}, "haiku.enabled"),
    ({"fallback": "codex"}, "fallback"), ({"haiku": {"model": "gpt"}}, "haiku.model"), ({"colour": "red"}, "colour")])
def test_a_wrong_prio_value_keeps_its_default_and_says_so(tmp_path, value, key):
    cfg = load_web_config(tmp_path, {"cockpit": {"flow": {"prio": value}}})
    assert cfg.flow["prio"] == prio.defaults()
    assert any(f"cockpit.flow.prio.{key}" in w for w in cfg.config_warnings), cfg.config_warnings


# ---------------------------------------------------------------- the rows: looked up on the server

def test_due_reads_as_words_computed_in_code():
    assert prio.due_text("2025-10-09", TODAY) == "today"
    assert prio.due_text("2025-10-10", TODAY) == "tomorrow"
    assert prio.due_text("2025-10-12T09:00", TODAY) == "in 3 days"
    assert prio.due_text("2025-10-08", TODAY) == "overdue 1 day"
    assert prio.due_text("2025-10-07", TODAY) == "overdue 2 days"
    assert prio.due_text("soon", TODAY) is None and prio.due_text(None, TODAY) is None


def rank_app(tmp_path, jev_on=True, haiku_on=True, prio_cfg=None, now=NOW, index=None):
    page = {"id": "arbeit", "title": "Arbeit", "jev": CFG, "sections": [{k: v for k, v in s.items() if k != "items"} for s in WORK]}
    by = {s["id"]: s["items"] for s in WORK}
    rows = INDEX if index is None else index
    collector = types.SimpleNamespace(view={"pages": [page]}, model={},
                                      page_items=lambda p, s: (by[s], len(by[s])) if p == "arbeit" else None,
                                      resolve=lambda key: {"row": rows[key], "out": {}} if key in rows else None)
    flow = {"prio": {"fallback": "none", "haiku": {"enabled": haiku_on, "budget_per_day": prio.DEFAULT_BUDGET, "model": None}}}
    for k, v in (prio_cfg or {}).items():
        flow["prio"][k] = {**flow["prio"][k], **v} if isinstance(v, dict) else v
    cfg = types.SimpleNamespace(jev_enabled=jev_on, jev_model=None, jev_key_ref=None, language="en", flow=flow,
                                person_name=None, jev_person=None, jev_criteria=None)
    lines = []
    app = types.SimpleNamespace(collector=collector, clock=lambda: now, cfg=cfg, root=tmp_path, state_dir=tmp_path,
                                triage=types.SimpleNamespace(state=lambda: {"items": TRIAGE}),
                                tabs=types.SimpleNamespace(tab_list=lambda: [dict(t) for t in TABS]),
                                runner=types.SimpleNamespace(claude="/fake/bin/claude"),
                                actions=types.SimpleNamespace(audit_line=lambda verb, subject, **kw: lines.append((verb, kw))))
    app.lines = lines
    return app


def rows_for(app, rows=ROWS):
    return jev._rows_for(app, jev._work_page(app, "arbeit"), TODAY, rows)


def test_rows_are_the_servers_items_held_back_by_private_words_and_skip_sections_and_unknown_keys(tmp_path):
    rows, skipped = rows_for(rank_app(tmp_path))
    # a tab, an issue, a meeting reference and a row the triage marked stand; the private one (by its server detail),
    # the one in a skipped section, the forged key and the unknown tab do not
    assert [r["key"] for r in rows] == SERVER_KEYS
    assert skipped == {"private": 1, "section": 1, "same": 1, "unknown": 2, "over": 0}
    offer = rows[0]
    # every field comes from the server's item, never from what the page sent
    assert offer["title"] == "Write the offer" and offer["kind"] == "task" and offer["status"] == "review"
    assert offer["due"] == "tomorrow" and offer["age_days"] == 8 and offer["gist"] == "send it to the customer"
    # the tab working on the task is that task: one row, marked running
    assert offer["running"] is True
    assert rows[2]["kind"] == "tab" and rows[2]["title"] == "research tab" and rows[2]["running"] is True
    assert rows[3]["kind"] == "issue" and rows[3]["due"] == "overdue 2 days"
    # a title alike is no reason to merge: the inbox item stands on its own
    assert rows[5]["kind"] == "inbox"


def test_a_private_word_matches_the_servers_detail_source_and_gist(tmp_path):
    app = rank_app(tmp_path)
    # the page item's detail (decision) and the triage's gist (customer); the source is read from the item's folder
    app.collector.view["pages"][0]["jev"] = {"private": ["decision", "customer"]}
    rows, skipped = rows_for(app, ROWS[:2])
    assert rows == [] and skipped["private"] == 2


def test_what_leaves_the_machine_is_only_the_fields_of_a_row(tmp_path):
    rows, _ = rows_for(rank_app(tmp_path))
    sent = prio.wire(rows)
    assert sent[0] == {"id": "t1", "title": "Write the offer", "kind": "task", "status": "review", "due": "tomorrow",
                       "running": True, "age_days": 8, "gist": "send it to the customer", "priority": "P1"}
    text = json.dumps(sent)
    assert "task:" not in text and "inbox:" not in text and "surface" not in text and "20251008" not in text
    assert "Something else" not in text


# ---------------------------------------------------------------- the Haiku ranker

def haiku_answer(n_points, used=HAIKU, cost=0.002, first=1, skip=()):
    points = [{"n": i + 1, "urgency": 3 if i == 0 else 1, "impact": 3 if i == 0 else 0, "effort": 1,
               "only_me": i == 0, "reason": f"reason {i + 1}"} for i in range(n_points) if i + 1 not in skip]
    out = {"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": cost,
           "modelUsage": {used: {"costUSD": cost}}, "result": "", "structured_output": {"points": points, "first": first}}
    return RunResult(True, 0, json.dumps(out), "", 1)


def points_of(argv):
    return json.loads(argv[-1].split("\n", 1)[1])["points"]


def test_the_prio_argv_is_one_exact_shape_the_runner_lets_through(tmp_path):
    runner = Runner(tmp_path, cmux=None, claude="/fake/bin/claude", codex=None)
    argv = prio.argv("/fake/bin/claude", HAIKU, "Rate these.", "data")
    assert argv[:12] == ["/fake/bin/claude", "-p", "--model", HAIKU, "--output-format", "json", "--no-session-persistence",
                         "--setting-sources", "", "--tools", "", "--json-schema"]
    assert argv[12] == prio.SCHEMA and argv[16] == "data"
    runner.check(argv)
    for change in (lambda a: a.__setitem__(3, "haiku"), lambda a: a.__setitem__(10, "Read"),
                   lambda a: a.__setitem__(12, "{}"), lambda a: a.insert(6, "--verbose")):
        bad = prio.argv("/fake/bin/claude", HAIKU, "Rate these.", "data")
        change(bad)
        assert not prio.argv_ok(bad, "/fake/bin/claude")
        with pytest.raises(RunnerRefused):
            runner.check(bad)


def test_haiku_answers_in_the_shape_jev_answers():
    tasks = [{"id": "t1", "key": "task:a", "title": "A"}, {"id": "t2", "key": "task:b", "title": "B"}]
    resp = prio.response_of(haiku_answer(2, first=2).out, 2, HAIKU)
    assert resp["answers"]["t1.urgency"]["score"] == 3 and resp["answers"]["t2.impact"]["score"] == 0
    assert resp["answers"]["t1.only_me"]["noul"] == 1.0 and resp["answers"]["t2.only_me"]["noul"] == 0.0
    assert resp["answers"]["first"]["choice"] == "t2" and resp["reasons"] == {"t1": "reason 1", "t2": "reason 2"}
    plan = jev.plan_from(tasks, resp)
    by = {x["id"]: x for x in plan["items"]}
    assert by["t1"]["quadrant"] == "now" and by["t1"]["who"] == "me" and by["t2"]["who"] == "delegate"
    assert plan["first"] == "t2"
    bad = RunResult(True, 0, json.dumps({"type": "result", "structured_output": {"points": []}}), "", 1)
    assert prio.response_of(bad.out, 2, HAIKU) is None


def test_a_point_without_urgency_or_impact_gets_no_square_from_either_ranker():
    tasks = [{"id": "t1", "key": "task:a"}, {"id": "t2", "key": "task:b"}, {"id": "t3", "key": "task:c"}]
    jev_resp = {"answers": {"t1.urgency": {"score": 3}, "t1.impact": {"score": 3}, "t2.urgency": {"score": 3}}}
    by = {x["id"]: x for x in jev.plan_from(tasks, jev_resp)["items"]}
    assert by["t1"]["quadrant"] == "now" and by["t2"]["quadrant"] is None and by["t3"]["quadrant"] is None
    resp = prio.response_of(haiku_answer(3, skip=(2,)).out, 3, HAIKU)
    by = {x["id"]: x for x in jev.plan_from(tasks, resp)["items"]}
    assert by["t2"]["quadrant"] is None and by["t1"]["quadrant"] == "now"


def run_haiku(name, subject, argv, timeout):
    return haiku_answer(len(points_of(argv)))


def test_haiku_reads_in_with_jev_switched_off_and_names_itself(tmp_path):
    app = rank_app(tmp_path, jev_on=False)
    runs = []

    def run(name, subject, argv, timeout):
        runs.append(argv)
        return run_haiku(name, subject, argv, timeout)

    handler = types.SimpleNamespace(sent=None)
    handler.send_json = lambda status, body: setattr(handler, "sent", (status, body))
    handler.send_error_json = lambda *a: None
    jev.handle_post(handler, app, "/api/jev/rank", {"page": "arbeit", "force": True, "ranker": "haiku", "rows": ROWS},
                    prio_call=run)
    status, body = handler.sent
    assert status == 200, body
    order = body["order"]
    assert order["ranker"] == "haiku" and order["model"] == "haiku" and order["sent"] == 6
    assert len(runs) == 1 and prio.argv_ok(runs[0], "/fake/bin/claude")
    first = order["items"][0]
    assert first["reason"] == "reason 1" and first["who"] == "me" and first["quadrant"] == "now"
    assert all(x["who"] == "delegate" for x in order["items"] if x["rank"] > 1)
    # Jev stays off for its own read-in
    jev.handle_post(handler, app, "/api/jev/rank", {"page": "arbeit", "force": True, "rows": ROWS})
    assert handler.sent[0] == 404 and handler.sent[1]["error"]["code"] == "jev_off"
    st = prio.state(app)
    assert st["haiku"]["enabled"] is True and st["haiku"]["ready"] is True
    assert st["haiku"]["budget_left"] == prio.DEFAULT_BUDGET - 1 and st["fallback"] == "none"
    assert [(v, kw["rows"], kw["model"]) for v, kw in app.lines] == [("prio_haiku", 6, "haiku")]


def test_haiku_switched_off_refuses_and_says_so_in_the_state(tmp_path):
    app = rank_app(tmp_path, haiku_on=False)
    with pytest.raises(jev.JevError) as e:
        jev.rank(app, {"page": "arbeit", "force": True, "ranker": "haiku", "rows": ROWS}, prio_call=run_haiku)
    assert e.value.code == "prio_off"
    assert prio.state(app)["haiku"] == {"enabled": False, "ready": False, "model": None, "budget_left": prio.DEFAULT_BUDGET}


def test_haiku_keeps_its_budget_per_day_and_counts_a_run_that_raised(tmp_path):
    app = rank_app(tmp_path, prio_cfg={"haiku": {"budget_per_day": 2}})

    def boom(*a):
        raise OSError("claude went away")
    with pytest.raises(OSError):
        jev.rank(app, {"page": "arbeit", "force": True, "ranker": "haiku", "rows": ROWS}, prio_call=boom)
    jev.rank(app, {"page": "arbeit", "force": True, "ranker": "haiku", "rows": ROWS}, prio_call=run_haiku)
    with pytest.raises(jev.JevError) as e:
        jev.rank(app, {"page": "arbeit", "force": True, "ranker": "haiku", "rows": ROWS}, prio_call=run_haiku)
    assert e.value.status == 429 and e.value.code == "prio_budget"
    nxt = rank_app(tmp_path, prio_cfg={"haiku": {"budget_per_day": 2}}, now=NOW + 86_400_000)
    assert jev.rank(nxt, {"page": "arbeit", "force": True, "ranker": "haiku", "rows": ROWS},
                    prio_call=run_haiku)["order"]["ranker"] == "haiku"


def test_the_budget_is_reserved_before_the_call(tmp_path):
    app = rank_app(tmp_path, prio_cfg={"haiku": {"budget_per_day": 1}})
    seen = []

    def run(name, subject, argv, timeout):
        seen.append(prio.budget_left(app))       # a second click arriving now finds no run left
        return run_haiku(name, subject, argv, timeout)
    jev.rank(app, {"page": "arbeit", "force": True, "ranker": "haiku", "rows": ROWS}, prio_call=run)
    assert seen == [0]


def test_a_view_too_big_for_one_prompt_is_trimmed_and_says_how_much(tmp_path, monkeypatch):
    many = {f"task:t{i}": {"key": f"task:t{i}", "task": f"t{i}", "title": f"Task number {i} " + "x" * 120, "status": "doing",
                           "priority": "P3" if i % 2 else "P1"} for i in range(40)}
    app = rank_app(tmp_path, index=many)
    monkeypatch.setattr(prio, "PROMPT_MAX", 4000)
    sent = []

    def run(name, subject, argv, timeout):
        sent.append(points_of(argv))
        return run_haiku(name, subject, argv, timeout)
    out = jev.rank(app, {"page": "arbeit", "force": True, "ranker": "haiku", "rows": [{"key": k} for k in many]}, prio_call=run)
    order = out["order"]
    assert order["skipped"]["over"] > 0 and order["sent"] == len(sent[0]) == 40 - order["skipped"]["over"]
    # the gists go first, then the rows with the lowest priority
    assert all("gist" not in p for p in sent[0]) and all(p.get("priority") == "P1" for p in sent[0][: len(sent[0]) // 2])


# ---------------------------------------------------------------- Jev, the fallback, the gate

def jev_answers(payload, key):
    tasks = payload["state"]["tasks"]
    out = {}
    for i, t in enumerate(tasks):
        out[f"{t['id']}.urgency"] = {"score": 3 if i == 0 else 0}
        out[f"{t['id']}.impact"] = {"score": 3 if i == 0 else 1}
        out[f"{t['id']}.effort"] = {"score": 1}
        out[f"{t['id']}.only_me"] = {"noul": 0.9 if i == 0 else 0.1}
    out["first"] = {"choice": "t1", "probabilities": {"t1": 0.8}}
    return {"model": "jev-test", "answers": out, "usage": {"input_tokens": 3, "output_tokens": 2}}


def test_jev_reads_in_every_point_of_the_page_in_one_request(tmp_path):
    sent = []

    def call(payload, key):
        sent.append(payload)
        return jev_answers(payload, key)

    many = dict(INDEX, **{f"task:t{i}": {"key": f"task:t{i}", "task": f"t{i}", "title": f"Task number {i}", "status": "doing"}
                          for i in range(30)})
    rows = ROWS + [{"key": f"task:t{i}"} for i in range(30)]
    out = jev.rank(rank_app(tmp_path, index=many), {"page": "arbeit", "force": True, "rows": rows}, call=call, key=lambda: "k")
    assert len(sent) == 1, "36 rows go in one request"
    order = out["order"]
    assert order["ranker"] == "jev" and order["sent"] == 36 and order["fallback"] is None
    tasks = sent[0]["state"]["tasks"]
    assert set(tasks[0]) == {"id", "title", "kind", "status", "due", "running", "age_days", "gist", "priority"}
    by = {x["key"]: x for x in order["items"]}
    assert "tab:surface:7" in by and "ref:cal-standup" in by and "task:year-end" not in by
    assert "taxes" not in json.dumps(sent[0])


def down(status=502, code="jev_upstream"):
    def call(payload, key):
        raise jev.JevError(status, code, "Jev failed")
    return call


def test_a_failed_jev_click_runs_haiku_when_the_fallback_says_so(tmp_path):
    app = rank_app(tmp_path, prio_cfg={"fallback": "haiku"})
    out = jev.rank(app, {"page": "arbeit", "force": True, "rows": ROWS}, call=down(), key=lambda: "k", prio_call=run_haiku)
    assert out["order"]["ranker"] == "haiku" and out["order"]["fallback"] == {"from": "jev", "code": "jev_upstream"}
    for status, code in ((429, "jev_busy"), (503, "jev_no_key"), (504, "jev_timeout")):
        again = jev.rank(rank_app(tmp_path, prio_cfg={"fallback": "haiku"}, now=NOW + status),
                         {"page": "arbeit", "force": True, "rows": ROWS}, call=down(status, code), key=lambda: "k", prio_call=run_haiku)
        assert again["order"]["fallback"]["code"] == code
    # a refusal of Jev (400, 401, 403) never falls back, nor without the fallback, nor with Haiku off
    for status in (400, 401, 403):
        with pytest.raises(jev.JevError) as e:
            jev.rank(app, {"page": "arbeit", "force": True, "rows": ROWS}, call=down(status, "jev_refused"), key=lambda: "k",
                     prio_call=run_haiku)
        assert e.value.status == status
    for plain in (rank_app(tmp_path), rank_app(tmp_path, haiku_on=False, prio_cfg={"fallback": "haiku"})):
        called = []
        with pytest.raises(jev.JevError):
            jev.rank(plain, {"page": "arbeit", "force": True, "rows": ROWS}, call=down(), key=lambda: "k",
                     prio_call=lambda *a: called.append(a))
        assert called == []


def test_the_daily_order_never_falls_back_and_fails_once_a_day(tmp_path):
    app = rank_app(tmp_path, prio_cfg={"fallback": "haiku"})
    calls, runs = [], []

    def failing(payload, key):
        calls.append(1)
        raise jev.JevError(502, "jev_upstream", "down")
    with pytest.raises(jev.JevError):
        jev.rank(app, {"page": "arbeit", "daily": True, "rows": ROWS}, call=failing, key=lambda: "k",
                 prio_call=lambda *a: runs.append(a))
    assert runs == [] and len(calls) == 1
    # a reload the same day reads what there is and calls nothing, and says the day's order failed
    again = jev.rank(rank_app(tmp_path, prio_cfg={"fallback": "haiku"}, now=NOW + 60_000),
                     {"page": "arbeit", "daily": True, "rows": ROWS}, call=failing, key=lambda: "k")
    assert len(calls) == 1 and again["order"] is None and again["failed_today"] is True
    # a click still orders; the next day the daily order tries again
    with pytest.raises(jev.JevError):
        jev.rank(rank_app(tmp_path, now=NOW + 86_400_000), {"page": "arbeit", "daily": True, "rows": ROWS}, call=failing,
                 key=lambda: "k")
    assert len(calls) == 2


def test_a_haiku_click_is_never_answered_by_a_fresh_jev_order(tmp_path):
    app = rank_app(tmp_path)
    jev.rank(app, {"page": "arbeit", "force": True, "rows": ROWS}, call=jev_answers, key=lambda: "k")
    st = jev._pages_state(app)
    kept = st.orders["arbeit"]
    # a Jev order newer than the one the click saw: the click still asks Haiku
    st.orders["arbeit"] = {**kept, "at_ms": kept["at_ms"] + 1}
    out = jev.rank(app, {"page": "arbeit", "force": True, "ranker": "haiku", "rows": ROWS}, prio_call=run_haiku)
    assert out["order"]["ranker"] == "haiku"
    assert jev._fresh_fits({"ranker": "jev"}, "haiku", True, TODAY) is False
    assert jev._fresh_fits({"ranker": "haiku"}, "haiku", True, TODAY) is True


def test_the_newest_order_wins_whichever_ranker_made_it(tmp_path):
    app = rank_app(tmp_path)
    first = jev.rank(app, {"page": "arbeit", "force": True, "rows": ROWS}, call=jev_answers, key=lambda: "k")
    assert first["order"]["ranker"] == "jev"
    second = jev.rank(rank_app(tmp_path, now=NOW + 60_000), {"page": "arbeit", "force": True, "ranker": "haiku", "rows": ROWS},
                      prio_call=run_haiku)
    kept = jev.rank(rank_app(tmp_path, now=NOW + 120_000), {"page": "arbeit"})
    assert kept["order"]["ranker"] == "haiku" and kept["order"]["at_ms"] == second["order"]["at_ms"]


def test_an_unrated_point_stays_out_of_the_order(tmp_path):
    app = rank_app(tmp_path)

    def partial(payload, key):
        out = jev_answers(payload, key)
        del out["answers"]["t2.impact"]
        return out
    order = jev.rank(app, {"page": "arbeit", "force": True, "rows": ROWS}, call=partial, key=lambda: "k")["order"]
    assert len(order["items"]) == 5 and order["skipped"]["unrated"] == 1


def test_rank_refuses_an_unknown_ranker_and_rows_that_are_no_list(tmp_path):
    app = rank_app(tmp_path)
    for body in ({"page": "arbeit", "ranker": "gpt"}, {"page": "arbeit", "rows": "all"}):
        with pytest.raises(jev.JevError) as e:
            jev.rank(app, body)
        assert e.value.code == "invalid_argument"


def test_call_api_keeps_the_status_jev_answered(monkeypatch):
    import io
    import urllib.error

    def raise_http(code):
        def urlopen(req, timeout=None):
            raise urllib.error.HTTPError(jev.API_URL, code, "x", {}, io.BytesIO(b"nope"))
        return urlopen
    for code, status, name in ((401, 401, "jev_refused"), (403, 403, "jev_refused"), (400, 400, "jev_refused"),
                               (500, 502, "jev_upstream"), (503, 502, "jev_upstream")):
        monkeypatch.setattr(jev.urllib.request, "urlopen", raise_http(code))
        with pytest.raises(jev.JevError) as e:
            jev.call_api({}, "k")
        assert (e.value.status, e.value.code) == (status, name), code

    def slow(req, timeout=None):
        raise TimeoutError("timed out")
    monkeypatch.setattr(jev.urllib.request, "urlopen", slow)
    with pytest.raises(jev.JevError) as e:
        jev.call_api({}, "k")
    assert (e.value.status, e.value.code) == (504, "jev_timeout")


def test_a_codex_service_says_why_haiku_cannot_read_in(tmp_path):
    # the service file names codex, which Prio's read-in cannot run yet: the state says so instead of hiding it
    app = rank_app(tmp_path)
    (tmp_path / "workflow" / "ai-services").mkdir(parents=True)
    (tmp_path / "workflow" / "ai-services" / "cockpit-prio.yaml").write_text(
        "schema_version: 1\nscope: user\nid: cockpit-prio\nprovider: codex\n", encoding="utf-8")
    haiku = prio.state(app)["haiku"]
    assert haiku["ready"] is False and haiku["reason"] == "provider_unsupported" and haiku["provider"] == "codex"
    with pytest.raises(jev.JevError) as e:
        jev.rank(app, {"page": "arbeit", "force": True, "ranker": "haiku", "rows": ROWS}, prio_call=run_haiku)
    assert e.value.code == "prio_unavailable"
    # a model pinned in the cockpit block runs on Claude whatever the service file says: no gap then
    pinned = rank_app(tmp_path, prio_cfg={"haiku": {"model": "haiku"}})
    assert prio.state(pinned)["haiku"]["ready"] is True and "reason" not in prio.state(pinned)["haiku"]


def test_a_broken_service_file_says_so_in_the_state(tmp_path):
    app = rank_app(tmp_path)
    (tmp_path / "workflow" / "ai-services").mkdir(parents=True)
    (tmp_path / "workflow" / "ai-services" / "cockpit-prio.yaml").write_text(
        "schema_version: 1\nscope: user\nid: cockpit-prio\nprovider: gemini\n", encoding="utf-8")
    haiku = prio.state(app)["haiku"]
    assert haiku["ready"] is False and haiku["reason"] == "config_invalid" and "cockpit-prio" in haiku["error"]
    # switched off: nothing to say
    assert "reason" not in prio.state(rank_app(tmp_path, haiku_on=False))["haiku"]
