# SPDX-License-Identifier: MIT
"""The return channel of the cockpit: what became of a row handed to an agent tab."""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts" / "lib") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from bridge_cockpit import returns  # noqa: E402

T0 = dt.datetime(2026, 10, 13, 20, 0, tzinfo=dt.timezone.utc).timestamp() * 1000
MIN = 60_000
ITEM = "20261013-1900-answer-the-vendor-ab12"


class Clock:
    def __init__(self, ms: float):
        self.ms = ms

    def __call__(self) -> float:
        return self.ms


def tab(state, **extra):
    return {"ref": "surface:7", "state": state, "since_ms": T0 + MIN, "last": "reading the files", "slug": None,
            "item": None, "filed_by": None, "is_control": False, **extra}


def event(root, item, at_ms, verb, text):
    d = root / "work" / "inbox" / item / "events"
    d.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.fromtimestamp(at_ms / 1000, dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (d / f"{stamp}-00-x-{verb}.yaml").write_text(
        f"verb: {verb}\nby: tab\nat: '{stamp}'\ntext: '{text}'\n", encoding="utf-8")


def book(tmp_path, clock):
    b = returns.Launches(tmp_path / "state", clock)
    b.record([{"key": "task:alpha", "item": "alpha", "title": "Alpha", "mode": "go"},
              {"key": f"inbox:{ITEM}", "item": ITEM, "title": "Answer the vendor", "mode": "report"}])
    return b


def test_a_launch_is_kept_across_a_restart_and_a_second_one_replaces_the_first(tmp_path):
    clock = Clock(T0)
    book(tmp_path, clock)
    clock.ms = T0 + 5 * MIN
    again = returns.Launches(tmp_path / "state", clock)
    again.record([{"key": "task:alpha", "item": "alpha", "title": "Alpha", "mode": "context"}])
    keys = [(x["key"], x["mode"], x["at_ms"]) for x in returns.Launches(tmp_path / "state", clock).all()]
    assert keys == [("task:alpha", "context", T0 + 5 * MIN), (f"inbox:{ITEM}", "report", T0)]
    again.forget("task:alpha")
    assert [x["key"] for x in again.all()] == [f"inbox:{ITEM}"]


def test_launches_older_than_a_week_drop_out(tmp_path):
    clock = Clock(T0)
    book(tmp_path, clock)
    clock.ms = T0 + 8 * 24 * 60 * MIN
    b = returns.Launches(tmp_path / "state", clock)
    b.record([{"key": "task:beta", "item": "beta", "title": "Beta", "mode": "go"}])
    assert [x["key"] for x in b.all()] == ["task:beta"]


def test_the_stage_follows_the_tab_and_what_it_left(tmp_path):
    clock = Clock(T0)
    b = book(tmp_path, clock)
    root = tmp_path
    rows = {"task:alpha": {"key": "task:alpha", "title": "Alpha"}, f"inbox:{ITEM}": {"key": f"inbox:{ITEM}", "title": "Answer"}}
    # just started, no tab yet
    out = {x["key"]: x for x in returns.build(b.all(), [], rows, root, T0 + 30_000)}
    assert out["task:alpha"]["stage"] == "started" and out["task:alpha"]["tab"] is None
    # a tab works on it
    tabs = [tab("working", slug="alpha"), tab("needs-you", ref="surface:8", item=ITEM)]
    out = {x["key"]: x for x in returns.build(b.all(), tabs, rows, root, T0 + 3 * MIN)}
    assert out["task:alpha"]["stage"] == "working" and out["task:alpha"]["tab"]["last"] == "reading the files"
    assert out[f"inbox:{ITEM}"]["stage"] == "asks"
    # the inbox tab noted a finding after the start: that is its answer
    event(root, ITEM, T0 - MIN, "note", "old note before the start")
    event(root, ITEM, T0 + 4 * MIN, "note", "Vendor wants XRechnung 3.0")
    tabs = [tab("working", slug="alpha"), tab("waiting", ref="surface:8", item=ITEM)]
    out = {x["key"]: x for x in returns.build(b.all(), tabs, rows, root, T0 + 5 * MIN)}
    assert out[f"inbox:{ITEM}"]["stage"] == "result"
    assert out[f"inbox:{ITEM}"]["result"]["text"] == "Vendor wants XRechnung 3.0"
    # the task tab filed its result into the inbox
    tabs = [tab("waiting", slug="alpha", filed_by="inbox:20261013-2010-result-cd34")]
    rows["inbox:20261013-2010-result-cd34"] = {"key": "inbox:20261013-2010-result-cd34", "title": "Alpha: the plan is ready"}
    out = {x["key"]: x for x in returns.build(b.all(), tabs, rows, root, T0 + 6 * MIN)}
    assert out["task:alpha"]["stage"] == "result"
    assert out["task:alpha"]["result"] == {"kind": "filed", "text": "Alpha: the plan is ready",
                                            "key": "inbox:20261013-2010-result-cd34", "at_ms": None}


def test_a_closed_item_is_done_and_a_tab_gone_without_a_word_is_lost(tmp_path):
    clock = Clock(T0)
    b = book(tmp_path, clock)
    event(tmp_path, ITEM, T0 + 2 * MIN, "close", "answered the vendor")
    out = {x["key"]: x for x in returns.build(b.all(), [], {}, tmp_path, T0 + 10 * MIN)}
    assert out[f"inbox:{ITEM}"]["stage"] == "done" and out[f"inbox:{ITEM}"]["result"]["text"] == "answered the vendor"
    # the task row is gone from the briefing, no tab, no result: nobody knows
    assert out["task:alpha"]["stage"] == "lost"
    # still in the briefing, tab closed, no result after a while: lost as well
    out = {x["key"]: x for x in returns.build(b.all(), [], {"task:alpha": {"key": "task:alpha"}}, tmp_path, T0 + 10 * MIN)}
    assert out["task:alpha"]["stage"] == "lost"


def test_the_newest_launch_comes_first_and_the_list_is_short(tmp_path):
    clock = Clock(T0)
    b = returns.Launches(tmp_path / "state", clock)
    for i in range(30):
        clock.ms = T0 + i * MIN
        b.record([{"key": f"task:t{i}", "item": f"t{i}", "title": f"T{i}", "mode": "go"}])
    out = returns.build(b.all(), [], {}, tmp_path, clock.ms)
    assert len(out) == returns.SHOW_MAX and out[0]["key"] == "task:t29"
    assert json.loads((tmp_path / "state" / "launches.json").read_text())["v"] == 1


def test_each_stage_is_written_to_the_log_once(tmp_path):
    clock = Clock(T0)
    b = book(tmp_path, clock)
    assert b.mark("task:alpha", "lost") is True
    assert b.mark("task:alpha", "lost") is False                     # once
    assert returns.Launches(tmp_path / "state", clock).mark("task:alpha", "lost") is False   # also after a restart
    assert b.mark("task:alpha", "result") is True
    assert b.mark("task:nobody", "lost") is False


def test_what_goes_to_the_log_and_what_the_agent_already_wrote(tmp_path):
    # a task: its answer and a silent end go to its notes; a close is its own record
    assert returns.log_line({"item": "alpha", "stage": "result", "result": {"kind": "filed", "text": "The plan", "key": "inbox:x"}}, "de") \
        == ("task", "alpha", "Bei der AI: Antwort abgelegt, The plan (inbox:x)")
    assert returns.log_line({"item": "alpha", "stage": "lost", "result": None}, "de")[2].startswith("Bei der AI: Tab beendet ohne Rückmeldung")
    assert returns.log_line({"item": "alpha", "stage": "done", "result": None}, "de") is None
    # an inbox item: what the agent noted or closed with is already in its events
    assert returns.log_line({"item": ITEM, "stage": "result", "result": {"kind": "note", "text": "x", "key": None}}, "de") is None
    assert returns.log_line({"item": ITEM, "stage": "lost", "result": None}, "en") == ("inbox", ITEM, "With AI: the tab ended without a word")
    assert returns.start_line("go", "de") == "Bei der AI: Agent gestartet aus dem Cockpit (AI machen lassen)"
    assert returns.start_line("report", "en") == "With AI: agent started from the cockpit (advise)"


def test_the_cockpits_own_notes_are_no_answer(tmp_path):
    """The start line and the "ended without a word" line the cockpit writes itself, in either language, must not
    turn a lost start into an answered one."""
    clock = Clock(T0)
    b = book(tmp_path, clock)
    for i, lang in enumerate(("en", "de")):
        event(tmp_path, ITEM, T0 + (1 + i) * 1000, "note", returns.start_line("report", lang))
        event(tmp_path, ITEM, T0 + (5 + i) * MIN, "note", returns.log_line({"item": ITEM, "stage": "lost"}, lang)[2])
    out = {x["key"]: x for x in returns.build(b.all(), [], {}, tmp_path, T0 + 10 * MIN)}
    assert out[f"inbox:{ITEM}"]["stage"] == "lost" and out[f"inbox:{ITEM}"]["result"] is None
    event(tmp_path, ITEM, T0 + 8 * MIN, "note", "the vendor has the answer")
    out = {x["key"]: x for x in returns.build(b.all(), [], {}, tmp_path, T0 + 10 * MIN)}
    assert out[f"inbox:{ITEM}"]["stage"] == "result"


def load_inbox():
    import importlib.util
    spec = importlib.util.spec_from_file_location("inbox_for_returns", ROOT / "scripts" / "inbox.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod      # dataclasses resolve the module by name while loading
    spec.loader.exec_module(mod)
    return mod


def test_an_executed_item_is_settled_and_its_start_is_done(tmp_path):
    clock = Clock(T0)
    b = book(tmp_path, clock)
    event(tmp_path, ITEM, T0 + MIN, "approve", "")
    event(tmp_path, ITEM, T0 + 3 * MIN, "executed", "sent the answer")
    assert returns.inbox_settled(tmp_path, ITEM) is True
    assert returns.tab_settled(tmp_path, {"item": ITEM}) == "item"
    out = {x["key"]: x for x in returns.build(b.all(), [], {}, tmp_path, T0 + 10 * MIN)}
    assert out[f"inbox:{ITEM}"]["stage"] == "done" and out[f"inbox:{ITEM}"]["result"]["text"] == "sent the answer"


def test_a_start_dropped_without_a_tab_is_done_and_never_lost(tmp_path):
    clock = Clock(T0)
    b = book(tmp_path, clock)
    event(tmp_path, ITEM, T0 + MIN, "drop", "not needed after all")
    for later in (T0 + 2 * MIN, T0 + returns.GRACE_MS + MIN, T0 + 60 * MIN):
        r = {x["key"]: x for x in returns.build(b.all(), [], {}, tmp_path, later)}[f"inbox:{ITEM}"]
        assert r["stage"] == "done" and returns.log_line(r, "en") is None
    # the reason a person dropped it with is no answer of the agent
    assert r["result"] is None
    # a reopen after the drop takes the end back
    event(tmp_path, ITEM, T0 + 5 * MIN, "reopen", "")
    r = {x["key"]: x for x in returns.build(b.all(), [], {}, tmp_path, T0 + 60 * MIN)}[f"inbox:{ITEM}"]
    assert r["stage"] == "lost" and returns.inbox_settled(tmp_path, ITEM) is False


def test_an_end_before_the_start_does_not_end_the_start(tmp_path):
    clock = Clock(T0)
    b = book(tmp_path, clock)
    event(tmp_path, ITEM, T0 - 5 * MIN, "close", "old close")
    r = {x["key"]: x for x in returns.build(b.all(), [], {}, tmp_path, T0 + MIN)}[f"inbox:{ITEM}"]
    assert r["stage"] == "started"


def test_every_terminal_verb_of_the_inbox_ends_a_start(tmp_path):
    """The inbox owns which verbs end an item: a verb it adds must settle the tab and end the start here too."""
    inbox = load_inbox()
    assert inbox.TERMINAL, "the inbox names its terminal verbs"
    for i, verb in enumerate(sorted(inbox.TERMINAL)):
        root = tmp_path / verb
        b = book(root, Clock(T0))
        event(root, ITEM, T0 + MIN, verb, "")
        assert returns.inbox_settled(root, ITEM) is True, verb
        assert {x["key"]: x for x in returns.build(b.all(), [], {}, root, T0 + 60 * MIN)}[f"inbox:{ITEM}"]["stage"] == "done", verb
