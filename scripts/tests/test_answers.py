# SPDX-License-Identifier: MIT
"""The four answers every point takes, in one place (scripts/lib/answers.py).

Every point answers who is on the move and when. The cockpit's cards, every view, every page that shows a
point and the printed briefing offer the same four answers in the same order: Do it (the Bridge takes the
next step), Later (a day, or the watch list), Done, Obsolete (closed as not done). The briefing's answer
words ("3 do", "3 später montag") and the old words (ja, los, nachfassen, parken, streichen ...) are parsed
here, and what an answer does to a row of each kind is a table here, so the cockpit never derives it again.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
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


ans = _load("answers", ROOT / "scripts" / "lib" / "answers.py")

FRIDAY = dt.date(2026, 11, 20)       # a Friday


# ---------------------------------------------------------------- the set

def test_exactly_four_answers_in_a_fixed_order_do_first():
    assert ans.ANSWERS == ("do", "later", "done", "obsolete")
    assert ans.PRIMARY == "do"
    assert ans.LATER_CHOICES == ("tomorrow", "monday", "week", "pick", "list")
    assert ans.MORE == ("owner", "tab", "fields", "ask")


def test_the_words_of_each_answer_in_english_and_german():
    de = {a["id"]: a for a in ans.answer_defs("de")}
    en = {a["id"]: a for a in ans.answer_defs("en")}
    assert [de[i]["label"] for i in ans.ANSWERS] == ["Mach das", "Später", "Erledigt", "Veraltet"]
    assert [en[i]["label"] for i in ans.ANSWERS] == ["Do it", "Later", "Done", "Obsolete"]
    assert [de[i]["say"] for i in ans.ANSWERS] == ["mach", "später", "erledigt", "veraltet"]
    assert [en[i]["say"] for i in ans.ANSWERS] == ["do", "later", "done", "obsolete"]
    assert de["do"]["primary"] is True and not any(de[i]["primary"] for i in ("later", "done", "obsolete"))
    # Obsolete is quiet and asks before it acts, in place
    assert de["obsolete"]["confirm"] is True and de["obsolete"]["quiet"] is True
    assert [c["label"] for c in ans.later_defs("de")] == ["morgen", "Montag", "in einer Woche", "Tag wählen", "Merkliste"]
    assert [c["label"] for c in ans.more_defs("de")] == ["Liegt bei …", "Zum Tab", "Felder", "Fragen"]
    assert ans.words("de")["done_stream"] == "für diesmal erledigt"
    assert ans.words("fr") == ans.words("en")         # an unknown language speaks English


def test_the_words_carry_no_dash():
    for lang in ("en", "de"):
        for text in ans.words(lang).values():
            assert "—" not in text and "–" not in text and "--" not in text


# ---------------------------------------------------------------- the day of a Later

def test_a_later_choice_is_a_day():
    assert ans.later_until("tomorrow", FRIDAY) == "2026-11-21"
    assert ans.later_until("monday", FRIDAY) == "2026-11-23"
    assert ans.later_until("monday", dt.date(2026, 11, 23)) == "2026-11-30"   # on a Monday: the next one
    assert ans.later_until("week", FRIDAY) == "2026-11-27"
    assert ans.later_until("pick", FRIDAY, "2026-12-03") == "2026-12-03"
    assert ans.later_until("list", FRIDAY) == ans.LIST_DAY
    assert ans.later_until(None, FRIDAY) == "2026-11-21"                      # no choice: tomorrow


def test_a_picked_day_in_the_past_or_unreadable_is_refused():
    for bad in ("2026-11-19", "2026-11-20", "soon", None):
        try:
            ans.later_until("pick", FRIDAY, bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad!r} was taken")


def test_the_watch_list_is_a_day_nobody_reaches():
    assert ans.is_list_day(ans.LIST_DAY) and ans.is_list_day("9999-12-31")
    assert not ans.is_list_day("2026-12-01") and not ans.is_list_day(None)


# ---------------------------------------------------------------- the answer words

def one(text, today=FRIDAY):
    got = ans.parse(text, today)
    assert len(got) == 1, got
    return got[0]


def test_the_four_words_in_both_languages_answer_a_numbered_row():
    for text, want in (("3 mach", "do"), ("3 do", "do"), ("3 Mach das", "do"), ("3 do it", "do"),
                       ("3 später", "later"), ("3 later", "later"), ("3 erledigt", "done"), ("3 done", "done"),
                       ("3 veraltet", "obsolete"), ("3 obsolete", "obsolete")):
        got = one(text)
        assert (got["nr"], got["answer"]) == (3, want), text


def test_a_later_may_carry_its_day():
    got = one("3 später montag")
    assert got["answer"] == "later" and got["choice"] == "monday" and got["until"] == "2026-11-23"
    assert one("3 later tomorrow")["until"] == "2026-11-21"
    assert one("4 später in einer Woche")["until"] == "2026-11-27"
    assert one("4 later in a week")["until"] == "2026-11-27"
    assert one("5 später 3.12.")["until"] == "2026-12-03"
    assert one("5 later 2026-12-03")["until"] == "2026-12-03"
    assert one("6 später merkliste")["until"] == ans.LIST_DAY
    assert one("6 later list")["choice"] == "list"
    plain = one("7 später")
    assert plain["choice"] == "tomorrow" and plain["until"] == "2026-11-21"


def test_several_answers_in_one_line():
    got = ans.parse("1 mach, 3 später montag 5 veraltet; 6 erledigt", FRIDAY)
    assert [(g["nr"], g["answer"]) for g in got] == [(1, "do"), (3, "later"), (5, "obsolete"), (6, "done")]
    assert got[1]["until"] == "2026-11-23"


def test_the_old_words_are_aliases_of_the_four():
    cases = {"ja": ("do", None), "yes": ("do", None), "los": ("do", None), "go": ("do", None),
             "nachfassen": ("do", None), "nudge": ("do", None),
             "einplanen": ("later", "pick"), "schedule": ("later", "pick"),
             "nicht jetzt": ("later", "tomorrow"), "not now": ("later", "tomorrow"),
             "warten": ("later", "tomorrow"), "wait": ("later", "tomorrow"),
             "parken": ("later", "list"), "park": ("later", "list"),
             "behalten": ("later", "tomorrow"), "keep": ("later", "tomorrow"),
             "streichen": ("obsolete", None), "drop": ("obsolete", None)}
    for word, (answer, choice) in cases.items():
        got = one(f"2 {word}")
        assert got["answer"] == answer, word
        if answer == "later" and choice != "pick":
            assert got["choice"] == choice, word
        assert got["alias"] is True, word
    assert one("2 mach")["alias"] is False


def test_einplanen_with_a_day_puts_it_on_that_day():
    got = one("2 einplanen montag")
    assert got["answer"] == "later" and got["until"] == "2026-11-23"


def test_a_letter_picks_the_answer_in_the_fixed_order():
    got = ans.parse("1a 3b 4c 5d", FRIDAY)
    assert [(g["nr"], g["answer"]) for g in got] == [(1, "do"), (3, "later"), (4, "done"), (5, "obsolete")]


def test_what_is_no_answer_is_left_out_and_said():
    assert ans.parse("hello there", FRIDAY) == []
    assert ans.parse("3 frobnicate", FRIDAY) == [{"nr": 3, "answer": None, "word": "frobnicate", "choice": None,
                                                    "until": None, "alias": False}]


# ---------------------------------------------------------------- what an answer does to a row

def test_the_kind_of_a_row():
    assert ans.row_kind({"tab": "t1"}) == "tab"
    assert ans.row_kind({"inbox_id": "i1"}) == "inbox"
    assert ans.row_kind({"inbox_id": "i1", "bucket": "waiting"}) == "waiting"
    assert ans.row_kind({"task": "a"}) == "task"
    assert ans.row_kind({"task": "a", "stream": True}) == "stream"
    assert ans.row_kind({"task": "a", "bucket": "waiting"}) == "waiting"
    # a stream is a stream in any bucket: its Done is for this time, its Obsolete ends it (round 4: a waiting stream
    # was a waiting point, and "3 erledigt" gave task.py close, which a stream refuses)
    assert ans.row_kind({"task": "a", "stream": True, "bucket": "waiting"}) == "stream"
    assert ans.row_kind({"ref": "o/r#1"}) == "issue"
    assert ans.row_kind({"title": "x"}) == "other"


def test_do_it_on_a_task_starts_an_agent_and_moves_it_to_i_do():
    e = ans.effect("do", {"task": "a", "step": "draft it"})
    assert e["cockpit"] == {"verb": "do_it", "args": {"keys": ["task:a"]}} and e["then"] == "delegate" and e["running"] is True
    # the chat starts the agent the cockpit starts (round 4: "mach" on a task ran nothing)
    assert e["cli"] == ["workplace.py launch --items a --mode go --yes"]


def test_do_it_on_an_inbox_item_is_its_yes_and_the_run():
    e = ans.effect("do", {"inbox_id": "i1"})
    assert e["cockpit"] == {"verb": "do_it", "args": {"keys": ["inbox:i1"], "yes": True}}
    # without an action of its own the yes gets an agent, as the cockpit's do_it starts one
    assert e["cli"] == ["inbox.py approve i1", "workplace.py launch --items i1 --mode go --yes"] and e["then"] == "delegate"
    acted = ans.effect("do", {"inbox_id": "i1", "has_action": True})
    assert acted["cli"] == ["inbox.py approve i1", "inbox.py run"]


def test_do_it_on_an_approved_item_starts_it_now():
    e = ans.effect("do", {"inbox_id": "i1", "inbox_state": "approved", "has_action": True})
    assert e["cli"] == ["inbox.py run"] and e["cockpit"]["verb"] == "do_it" and e["then"] == "delegate"
    # round 4: one without an action ran nothing from the chat, the cockpit started an agent
    bare = ans.effect("do", {"inbox_id": "i1", "inbox_state": "approved"})
    assert bare["cli"] == ["workplace.py launch --items i1 --mode go --yes"]


def test_do_it_on_an_only_you_item_prepares_it_and_gives_no_yes():
    # round 3: "5 mach" on an only-you item approved it (inbox.py approve), the cockpit's Do it gave no yes and
    # started an agent to prepare it: one word, two acts
    e = ans.effect("do", {"inbox_id": "i1", "gate": "only-you"})
    assert not any("approve" in c or c == "inbox.py run" for c in e["cli"])
    assert e["cli"] == ['inbox.py note i1 "Do it: prepare it, the person does the last step"',
                        "workplace.py launch --items i1 --mode go --yes"]
    assert e["cockpit"] == {"verb": "do_it", "args": {"keys": ["inbox:i1"], "yes": True}}
    assert e["prepare_only"] is True and e["running"] is True and e["then"] == "delegate"


def test_do_it_on_a_waiting_point_writes_a_nudge_as_a_draft_never_sent():
    e = ans.effect("do", {"task": "a", "bucket": "waiting", "who": "Ada"})
    # a verb the server has (round 1: "nudge" was none, the page sent do_it): an agent writes the draft, never sends
    # round 2: while the agent writes it the point runs in I'll do, the draft then waits in Do
    assert e["cockpit"]["verb"] == "do_it" and e["draft_only"] is True and e["then"] == "delegate" and e["ready"] == "do"
    assert "draft" in e["cockpit"]["args"]["note"].lower()


def test_a_tab_that_asks_answers_with_its_own_words():
    e = ans.effect("do", {"tab": "t1"})
    # no verb of its own: the tab's own answer (a dialog's option, its ready suggestion, Yes or No) is the act
    assert e["cockpit"] is None and e["own_answers"] is True and e["cli"] == []


def test_later_puts_off_to_a_day_or_onto_the_watch_list():
    assert ans.effect("later", {"inbox_id": "i1"}, until="2026-11-23")["cli"] == ["inbox.py defer i1 --until 2026-11-23"]
    task = ans.effect("later", {"task": "a"}, until="2026-11-23")
    assert task["cockpit"] == {"verb": "later", "args": {"key": "task:a", "until": "2026-11-23"}} and task["then"] == "later"
    # round 1: "72 später" did nothing durable from the chat; it hides the task as the cockpit's Later does
    assert task["cli"] == ["briefing.py hide task:a --until 2026-11-23"]
    assert ans.effect("later", {"ref": "o/r#1"}, until="2026-11-23")["cli"] == ["briefing.py hide ref:o/r#1 --until 2026-11-23"]
    park = ans.effect("later", {"task": "a"}, until=ans.LIST_DAY)
    assert park["cockpit"]["verb"] == "task_park" and park["then"] == "list"
    assert park["cli"][0].startswith("task.py status a backlog")
    shelf = ans.effect("later", {"inbox_id": "i1"}, until=ans.LIST_DAY)
    assert shelf["cli"] == [f"inbox.py defer i1 --until {ans.LIST_DAY}"] and shelf["then"] == "list"
    issue = ans.effect("later", {"ref": "o/r#1"}, until=ans.LIST_DAY)
    # round 4: the table named `hide`, whose day the server refuses past a year; the cockpit sends later
    assert issue["cockpit"] == {"verb": "later", "args": {"key": "ref:o/r#1", "until": ans.LIST_DAY}} and issue["then"] == "list"
    assert issue["cli"] == [f"briefing.py hide ref:o/r#1 --until {ans.LIST_DAY}"]


def test_later_on_a_waiting_point_keeps_it_with_the_same_person():
    e = ans.effect("later", {"task": "a", "bucket": "waiting", "who": "Ada"}, until="2026-11-23")
    assert e["cockpit"] == {"verb": "runs_on", "args": {"keys": ["task:a"], "until": "2026-11-23", "on": "Ada"}}
    assert e["cli"] == ["task.py wait a --until 2026-11-23"] and e["then"] == "later"
    i = ans.effect("later", {"inbox_id": "i1", "bucket": "waiting", "who": "Ada"}, until="2026-11-23")
    assert i["cli"] == ["inbox.py defer i1 --until 2026-11-23 --on Ada"]
    # the watch list is the watch list on a waiting point too, the same act as the cockpit's (round 1: the chat's
    # "parken" waited until 9999, the cockpit parked the task)
    park = ans.effect("later", {"task": "a", "bucket": "waiting", "who": "Ada"}, until=ans.LIST_DAY)
    assert park["cockpit"]["verb"] == "task_park" and park["then"] == "list"
    assert park["cli"][0].startswith("task.py status a backlog")
    shelf = ans.effect("later", {"inbox_id": "i1", "bucket": "waiting", "who": "Ada"}, until=ans.LIST_DAY)
    assert shelf["cli"] == [f"inbox.py defer i1 --until {ans.LIST_DAY}"] and shelf["then"] == "list"


def test_done_closes_and_a_stream_is_done_for_now():
    assert ans.effect("done", {"inbox_id": "i1"})["cli"][0].startswith("inbox.py close i1")
    assert ans.effect("done", {"task": "a"})["cockpit"] == {"verb": "settle", "args": {"keys": ["task:a"], "outcome": "done"}}
    s = ans.effect("done", {"task": "a", "stream": True}, today="2026-11-21")
    # done for this time: out of sight until tomorrow and counted as done today, the same from the chat
    assert s["cockpit"] == {"verb": "later", "args": {"key": "task:a", "until": "2026-11-22", "done": True}} and s["then"] == "done"
    assert s["cli"] == ["briefing.py hide task:a --until 2026-11-22 --done"] and s["stream_continues"] is True
    issue = ans.effect("done", {"ref": "o/r#1"})
    assert issue["cockpit"] == {"verb": "settle", "args": {"keys": ["ref:o/r#1"], "outcome": "done"}} and issue["github"] == "untouched"


def test_obsolete_closes_as_not_done_with_a_note():
    i = ans.effect("obsolete", {"inbox_id": "i1"})
    assert i["cli"] == ['inbox.py drop i1 --note "veraltet" --reason outdated']
    assert i["cockpit"] == {"verb": "settle", "args": {"keys": ["inbox:i1"], "outcome": "not_doing", "reason": "outdated"}}
    t = ans.effect("obsolete", {"task": "a"})
    assert t["cli"] == ['task.py close a --declined --reason "Wird nicht gemacht: veraltet"']
    s = ans.effect("obsolete", {"task": "a", "stream": True})
    assert s["cli"] == ['task.py close a --stream --declined --reason "Wird nicht gemacht: veraltet"']
    assert s["cockpit"]["args"] == {"keys": ["task:a"], "outcome": "not_doing", "stream": True}
    issue = ans.effect("obsolete", {"ref": "o/r#1"})
    assert issue["github"] == "untouched" and issue["cli"] == ["briefing.py dismiss ref:o/r#1 --outcome not_doing"]
    assert ans.effect("done", {"ref": "o/r#1"})["cli"] == ["briefing.py dismiss ref:o/r#1 --outcome done"]


def test_every_answer_has_an_effect_on_every_kind():
    rows = {"tab": {"tab": "t"}, "inbox": {"inbox_id": "i"}, "task": {"task": "a"}, "stream": {"task": "a", "stream": True},
            "waiting": {"task": "a", "bucket": "waiting"}, "issue": {"ref": "o/r#1"}, "other": {"title": "x"}}
    for kind, row in rows.items():
        for a in ans.ANSWERS:
            e = ans.effect(a, row, until="2026-11-23")
            assert e["answer"] == a and e["kind"] == kind, (a, kind)
            assert e["cockpit"] is None if (kind, a) == ("tab", "do") else e["cockpit"]["verb"], (a, kind)


def test_an_unknown_answer_is_refused():
    try:
        ans.effect("park", {"task": "a"})
    except ValueError:
        return
    raise AssertionError("park was taken as an answer")


def test_the_parser_keeps_every_day_and_every_number_it_is_given():
    # round 2 of the four answers: a named day after a small word fell back to tomorrow, a shared word lost a number,
    # a word with a comma behind it answered nothing, and "3: später" answered nothing at all
    today = dt.date(2026, 11, 21)              # a Saturday
    monday = "2026-11-23"
    for said in ("3 später am montag", "3 später bis montag", "3 später auf montag", "3 später nächsten montag",
                 "3 later on monday", "3: später montag"):
        got = ans.parse(said, today)
        assert [(g["nr"], g["answer"], g["until"]) for g in got] == [(3, "later", monday)], said
    got = ans.parse("3 later monday and 4 done", today)
    assert [(g["nr"], g["answer"], g["until"]) for g in got] == [(3, "later", monday), (4, "done", None)]
    got = ans.parse("3, 5 erledigt", today)
    assert [(g["nr"], g["answer"]) for g in got] == [(3, "done"), (5, "done")]
    assert [(g["nr"], g["answer"]) for g in ans.parse("3 und 5 erledigt", today)] == [(3, "done"), (5, "done")]
    assert [g["answer"] for g in ans.parse("3 erledigt, danke", today)] == ["done"]
    assert [g["answer"] for g in ans.parse("3 veraltet bitte", today)] == ["obsolete"]


# ---------------------------------------------------------------- the chat and the cockpit do the same

def test_a_stream_from_the_chat_is_done_for_this_time_and_obsolete_ends_it_in_any_bucket():
    # round 4: "3 erledigt" on a stream row gave task.py close, which close_task refuses for a stream; a waiting stream
    # did it even with stream set
    for bucket in ("plan", "waiting", "do"):
        row = {"task": "rota", "stream": True, "bucket": bucket}
        done = ans.effect("done", row, today="2026-11-21")
        assert done["cli"] == ["briefing.py hide task:rota --until 2026-11-22 --done"], bucket
        gone = ans.effect("obsolete", row)
        assert gone["cli"] == ['task.py close rota --stream --declined --reason "Wird nicht gemacht: veraltet"'], bucket
    # the watch list on a waiting stream puts it off to the list's day, as the cockpit does, never task.py wait
    shelf = ans.effect("later", {"task": "rota", "stream": True, "bucket": "waiting"}, until=ans.LIST_DAY)
    assert shelf["cli"] == [f"briefing.py hide task:rota --until {ans.LIST_DAY}"]


def _contract():
    import json
    return json.loads((ROOT / "scripts" / "tests" / "fixtures" / "answers" / "effects.json").read_text(encoding="utf-8"))


def _comparable(act: dict) -> dict:
    """An act without the page's words (a note's, a text's, a park's reason)"""
    args = {k: v for k, v in (act.get("args") or {}).items() if k not in ("text", "note")}
    if act.get("verb") == "task_park":
        args.pop("reason", None)
    return {"verb": act.get("verb"), "args": args}


def test_the_table_names_the_act_the_cockpit_sends():
    # round 4: the table named verbs the server has not (tab_answer) or refuses (hide past a year), and nothing held
    # it to the cockpit's mapping; web/buckets.js is held to the same cases (bridge_cockpit_answer_contract.test.mjs)
    c = _contract()
    for case in c["cases"]:
        e = ans.effect(case["answer"], case["row"], until=case.get("until"), today=c["today"])
        assert _comparable(e["cockpit"]) == _comparable(case["act"]), case["name"]


def test_every_act_of_the_table_is_a_verb_the_server_takes():
    sys.path.insert(0, str(ROOT / "scripts" / "lib"))
    from bridge_cockpit import actions_base as base
    rows = [{"tab": "t"}, {"inbox_id": "i"}, {"inbox_id": "i", "inbox_state": "approved"}, {"inbox_id": "i", "gate": "only-you"},
            {"task": "a"}, {"task": "a", "stream": True}, {"task": "a", "bucket": "waiting", "who": "Ada"},
            {"inbox_id": "i", "bucket": "waiting"}, {"ref": "o/r#1"}, {"ref": "o/r#1", "bucket": "waiting"}]
    for row in rows:
        for a in ans.ANSWERS:
            for until in ("2026-11-23", ans.LIST_DAY):
                e = ans.effect(a, row, until=until, today="2026-11-21")
                if e["cockpit"] is None:
                    continue
                spec = base.SPEC[e["cockpit"]["verb"]]
                assert set(e["cockpit"]["args"]) <= set(spec), (a, row, e["cockpit"])
                assert all(name in e["cockpit"]["args"] for name, (_, need) in spec.items() if need), (a, row, e["cockpit"])


def test_later_in_a_count_of_days_or_weeks_and_the_watch_list_alone():
    # round 4: "3 später in 1 woche" put it off to tomorrow and answered a number 1; "2 merkliste" answered nothing
    today = dt.date(2026, 11, 21)
    got = [(p["nr"], p["answer"], p["until"]) for p in ans.parse("3 später in 1 woche", today)]
    assert got == [(3, "later", "2026-11-28")]
    assert [(p["nr"], p["until"]) for p in ans.parse("3 later in 3 days, 4 done", today)] == [(3, "2026-11-24"), (4, None)]
    shelf = ans.parse("2 merkliste", today)
    assert [(p["nr"], p["answer"], p["choice"], p["until"]) for p in shelf] == [(2, "later", "list", ans.LIST_DAY)]


def test_a_picked_day_lies_within_the_days_the_server_takes():
    # round 4: the page, the server and the chat each had their own limit
    today = dt.date(2026, 11, 21)
    assert ans.later_until("pick", today, (today + dt.timedelta(days=ans.LATER_MAX_DAYS)).isoformat())
    try:
        ans.later_until("pick", today, (today + dt.timedelta(days=ans.LATER_MAX_DAYS + 1)).isoformat())
    except ValueError:
        pass
    else:
        raise AssertionError("a day past the limit was taken")
    base = (ROOT / "scripts" / "lib" / "bridge_cockpit" / "actions_base.py").read_text(encoding="utf-8")
    assert f"timedelta(days={ans.LATER_MAX_DAYS})" in base
    page = (ROOT / "scripts" / "web" / "buckets.js").read_text(encoding="utf-8")
    assert f"LATER_MAX_DAYS = {ans.LATER_MAX_DAYS}" in page
