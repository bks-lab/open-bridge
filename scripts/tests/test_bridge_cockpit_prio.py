# SPDX-License-Identifier: MIT
"""Reading in the Prio of Work through (prio.py, jev.rank): the page sends every point its work view shows, the
server holds back only what the page's private words name, merges what is the same, and asks one of two rankers,
Jev (TypeSafe) or Haiku (a small Claude model), for the same fields per point. The order says which one made it.
Optionally a Jev read-in that fails runs Haiku instead (cockpit.flow.prio.fallback).

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

# every kind of point the work view shows: a task in review, an inbox question, a tab alone, an issue, a meeting
# reference, a task the triage marked for closing, a private one and a duplicate of a title
ROWS = [
    {"key": "task:offer", "title": "Write the offer", "kind": "task", "status": "review", "due": "2025-10-10",
     "since": "2025-10-01", "running": False},
    {"key": "inbox:20251008-0900-ask", "title": "Approve the quote", "kind": "inbox", "status": "open",
     "since": "2025-10-08"},
    {"key": "tab:surface:7", "title": "research tab", "kind": "tab", "status": "working", "running": True},
    {"key": "ref:acme/web#12", "title": "Fix the login form", "kind": "issue", "due": "2025-10-07"},
    {"key": "ref:cal-standup", "title": "Weekly standup notes", "kind": "item", "due": "2025-10-12"},
    {"key": "task:old-notes", "title": "Old notes", "kind": "task", "status": "doing"},
    {"key": "task:taxes", "title": "Taxes 2024", "kind": "task", "status": "doing"},
    {"key": "inbox:20251007-0800-dup", "title": "write  the Offer.", "kind": "inbox"},
]
TRIAGE = {"task:old-notes": {"verdict": "close", "doer": "ai", "gist": "looks finished"},
          "task:offer": {"verdict": "keep", "doer": "you", "gist": "send it to the customer"}}
CFG = {"private": ["taxes"], "skip_sections": ["tasks"]}


# ---------------------------------------------------------------- config (cockpit.flow.prio)

def test_prio_has_its_defaults_and_takes_its_keys_one_by_one(tmp_path):
    cfg = load_web_config(tmp_path, {})
    assert cfg.flow["prio"] == {"haiku_budget_per_day": prio.DEFAULT_BUDGET, "fallback": "none", "model": None}
    cfg = load_web_config(tmp_path, {"cockpit": {"flow": {"prio": {"haiku_budget_per_day": 2, "fallback": "haiku",
                                                                   "model": "sonnet"}}}})
    assert cfg.flow["prio"] == {"haiku_budget_per_day": 2, "fallback": "haiku", "model": "sonnet"}
    assert cfg.config_warnings == ()


@pytest.mark.parametrize("value, key", [
    ({"haiku_budget_per_day": -1}, "haiku_budget_per_day"), ({"haiku_budget_per_day": "many"}, "haiku_budget_per_day"),
    ({"fallback": "codex"}, "fallback"), ({"model": "gpt"}, "model"), ({"colour": "red"}, "colour")])
def test_a_wrong_prio_value_keeps_its_default_and_says_so(tmp_path, value, key):
    cfg = load_web_config(tmp_path, {"cockpit": {"flow": {"prio": value}}})
    assert cfg.flow["prio"] == prio.defaults()
    assert any(f"cockpit.flow.prio.{key}" in w for w in cfg.config_warnings), cfg.config_warnings


# ---------------------------------------------------------------- the rows: all points, private held back, merged

def test_due_reads_as_words_computed_in_code():
    assert prio.due_text("2025-10-09", TODAY) == "today"
    assert prio.due_text("2025-10-10", TODAY) == "tomorrow"
    assert prio.due_text("2025-10-12T09:00", TODAY) == "in 3 days"
    assert prio.due_text("2025-10-08", TODAY) == "overdue 1 day"
    assert prio.due_text("2025-10-07", TODAY) == "overdue 2 days"
    assert prio.due_text("soon", TODAY) is None and prio.due_text(None, TODAY) is None


def test_rows_take_every_point_hold_back_only_private_words_and_merge_the_same():
    rows, skipped = prio.rows_of(ROWS, TODAY, TRIAGE, CFG["private"])
    keys = [r["key"] for r in rows]
    # a tab, an issue, a meeting reference and a row the triage marked stand too; only the private one is held back
    assert keys == ["task:offer", "inbox:20251008-0900-ask", "tab:surface:7", "ref:acme/web#12", "ref:cal-standup",
                    "task:old-notes"]
    assert skipped == {"private": 1, "same": 1}
    # the same title (case, blanks and a full stop aside) is one row that stands for both keys
    assert rows[0]["keys"] == ["task:offer", "inbox:20251007-0800-dup"]
    offer = rows[0]
    assert offer["due"] == "tomorrow" and offer["age_days"] == 8 and offer["running"] is False
    assert offer["gist"] == "send it to the customer" and offer["status"] == "review" and offer["kind"] == "task"
    assert rows[2]["running"] is True and rows[3]["due"] == "overdue 2 days"
    # the same key twice is one row
    again, sk = prio.rows_of(ROWS[:1] * 2, TODAY, {}, [])
    assert len(again) == 1 and sk == {"private": 0, "same": 1}


def test_a_private_word_matches_the_gist_and_the_source_too():
    rows, skipped = prio.rows_of(ROWS[:2], TODAY, TRIAGE, ["customer", "applications"],
                                 source_of=lambda key: "applications" if key.startswith("inbox:") else None)
    assert rows == [] and skipped["private"] == 2


def test_rows_refuse_what_is_no_row_and_cap_what_is_long():
    rows, _ = prio.rows_of([{"key": "task:a", "title": "x" * 400, "kind": "spaceship", "status": "s" * 90, "running": "yes"},
                            {"key": 7, "title": "no key"}, {"key": "task:b"}, "nonsense"], TODAY, {}, [])
    assert [r["key"] for r in rows] == ["task:a"]
    assert len(rows[0]["title"]) == prio.TITLE_MAX and rows[0]["kind"] == "item" and len(rows[0]["status"]) <= 20
    assert rows[0]["running"] is False


def test_what_leaves_the_machine_is_only_the_fields_of_a_row():
    rows, _ = prio.rows_of(ROWS, TODAY, TRIAGE, CFG["private"])
    sent = prio.wire(rows)
    assert sent[0] == {"id": "t1", "title": "Write the offer", "kind": "task", "status": "review", "due": "tomorrow",
                       "running": False, "age_days": 8, "gist": "send it to the customer"}
    text = json.dumps(sent)
    assert "task:" not in text and "inbox:" not in text and "surface" not in text and "20251008" not in text


# ---------------------------------------------------------------- the Haiku ranker

def haiku_answer(n_points, used=HAIKU, cost=0.002, first=1):
    points = [{"n": i + 1, "urgency": 3 if i == 0 else 1, "impact": 3 if i == 0 else 0, "effort": 1,
               "only_me": i == 0, "reason": f"reason {i + 1}"} for i in range(n_points)]
    out = {"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": cost,
           "modelUsage": {used: {"costUSD": cost}}, "result": "", "structured_output": {"points": points, "first": first}}
    return RunResult(True, 0, json.dumps(out), "", 1)


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
    # an answer without points is no answer
    bad = RunResult(True, 0, json.dumps({"type": "result", "structured_output": {"points": []}}), "", 1)
    assert prio.response_of(bad.out, 2, HAIKU) is None


# ---------------------------------------------------------------- jev.rank with the page's rows, either ranker

WORK = [{"id": "inbox", "kind": "inbox", "title": "Inbox", "items": [{"title": "Approve the quote", "inbox": "i1"}]}]


def rank_app(tmp_path, jev_on=True, prio_cfg=None, now=NOW):
    page = {"id": "arbeit", "title": "Arbeit", "jev": CFG, "sections": [{"id": "inbox", "kind": "inbox", "title": "Inbox"}]}
    by = {s["id"]: s["items"] for s in WORK}
    collector = types.SimpleNamespace(view={"pages": [page]}, model={},
                                      page_items=lambda p, s: (by[s], len(by[s])) if p == "arbeit" else None)
    flow = {"prio": {**prio.defaults(), **(prio_cfg or {})}}
    cfg = types.SimpleNamespace(jev_enabled=jev_on, jev_model=None, jev_key_ref=None, language="en", flow=flow,
                                person_name=None, jev_person=None, jev_criteria=None)
    lines = []
    app = types.SimpleNamespace(collector=collector, clock=lambda: now, cfg=cfg, root=tmp_path, state_dir=tmp_path,
                                triage=types.SimpleNamespace(state=lambda: {"items": TRIAGE}),
                                runner=types.SimpleNamespace(claude="/fake/bin/claude"),
                                actions=types.SimpleNamespace(audit_line=lambda verb, subject, **kw: lines.append((verb, kw))))
    app.lines = lines
    return app


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

    many = ROWS + [{"key": f"task:t{i}", "title": f"Task number {i}", "kind": "task", "status": "doing"} for i in range(30)]
    out = jev.rank(rank_app(tmp_path), {"page": "arbeit", "force": True, "rows": many}, call=call, key=lambda: "k")
    assert len(sent) == 1, "36 rows go in one request"
    order = out["order"]
    assert order["ranker"] == "jev" and order["sent"] == 36 and order["skipped"]["private"] == 1
    assert order["skipped"]["same"] == 1 and order["fallback"] is None
    tasks = sent[0]["state"]["tasks"]
    assert set(tasks[0]) == {"id", "title", "kind", "status", "due", "running", "age_days", "gist"}
    # the merged duplicate carries the same rank as the row it was merged into
    by = {x["key"]: x for x in order["items"]}
    assert by["inbox:20251007-0800-dup"]["rank"] == by["task:offer"]["rank"]
    assert "tab:surface:7" in by and "ref:cal-standup" in by and "task:taxes" not in by
    assert "Taxes" not in json.dumps(sent[0])


def test_haiku_reads_in_with_jev_switched_off_and_names_itself(tmp_path):
    app = rank_app(tmp_path, jev_on=False)
    runs = []

    def run(name, subject, argv, timeout):
        runs.append(argv)
        return haiku_answer(len(json.loads(argv[-1].split("\n", 1)[1])["points"]))

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
    # the state says Haiku is ready and how many runs are left today
    st = prio.state(app)
    assert st["haiku"]["ready"] is True and st["haiku"]["budget_left"] == prio.DEFAULT_BUDGET - 1 and st["fallback"] == "none"
    # one audit line for the Haiku call: what left the machine, never a title
    assert [(v, kw["rows"], kw["model"]) for v, kw in app.lines] == [("prio_haiku", 6, "haiku")]


def test_haiku_keeps_its_budget_per_day(tmp_path):
    app = rank_app(tmp_path, prio_cfg={"haiku_budget_per_day": 1})
    run = lambda name, subject, argv, timeout: haiku_answer(6)  # noqa: E731
    jev.rank(app, {"page": "arbeit", "force": True, "ranker": "haiku", "rows": ROWS}, prio_call=run)
    with pytest.raises(jev.JevError) as e:
        jev.rank(app, {"page": "arbeit", "force": True, "ranker": "haiku", "rows": ROWS}, prio_call=run)
    assert e.value.status == 429 and e.value.code == "prio_budget"
    # the next day has its run again
    nxt = rank_app(tmp_path, prio_cfg={"haiku_budget_per_day": 1}, now=NOW + 86_400_000)
    assert jev.rank(nxt, {"page": "arbeit", "force": True, "ranker": "haiku", "rows": ROWS}, prio_call=run)["order"]["ranker"] == "haiku"


def test_a_failed_jev_read_in_runs_haiku_when_the_fallback_says_so(tmp_path):
    def down(payload, key):
        raise jev.JevError(502, "jev_upstream", "Jev is not reachable: timed out")

    run = lambda name, subject, argv, timeout: haiku_answer(6)  # noqa: E731
    app = rank_app(tmp_path, prio_cfg={"fallback": "haiku"})
    out = jev.rank(app, {"page": "arbeit", "force": True, "rows": ROWS}, call=down, key=lambda: "k", prio_call=run)
    assert out["order"]["ranker"] == "haiku" and out["order"]["fallback"] == {"from": "jev", "code": "jev_upstream"}
    # without the fallback the failure stands, and nothing runs instead
    called = []
    (tmp_path / "b").mkdir()
    plain = rank_app(tmp_path / "b")
    with pytest.raises(jev.JevError) as e:
        jev.rank(plain, {"page": "arbeit", "force": True, "rows": ROWS}, call=down, key=lambda: "k",
                 prio_call=lambda *a: called.append(a))
    assert e.value.code == "jev_upstream" and called == []
    # a refusal of the request itself (4xx) never falls back
    def bad(payload, key):
        raise jev.JevError(400, "invalid_argument", "bad")
    with pytest.raises(jev.JevError):
        jev.rank(app, {"page": "arbeit", "force": True, "rows": ROWS}, call=bad, key=lambda: "k", prio_call=run)


def test_the_newest_order_wins_whichever_ranker_made_it(tmp_path):
    app = rank_app(tmp_path)
    first = jev.rank(app, {"page": "arbeit", "force": True, "rows": ROWS}, call=jev_answers, key=lambda: "k")
    assert first["order"]["ranker"] == "jev"
    later = rank_app(tmp_path, now=NOW + 60_000)
    second = jev.rank(later, {"page": "arbeit", "force": True, "ranker": "haiku", "rows": ROWS},
                      prio_call=lambda *a: haiku_answer(6))
    kept = jev.rank(rank_app(tmp_path, now=NOW + 120_000), {"page": "arbeit"})
    assert kept["order"]["ranker"] == "haiku" and kept["order"]["at_ms"] == second["order"]["at_ms"]


def test_rank_refuses_an_unknown_ranker_and_rows_that_are_no_list(tmp_path):
    app = rank_app(tmp_path)
    for body in ({"page": "arbeit", "ranker": "gpt"}, {"page": "arbeit", "rows": "all"}):
        with pytest.raises(jev.JevError) as e:
            jev.rank(app, body)
        assert e.value.code == "invalid_argument"
