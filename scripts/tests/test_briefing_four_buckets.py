# SPDX-License-Identifier: MIT
"""Four buckets and four answers, the model the operator decided on 21.11.2026.

Every point answers who is on the move and when: do (you, today), plan (you, no day yet), delegate (the
Bridge), waiting (anyone else). The bucket "park or drop" is gone: a task nobody touched for long stays in its
own bucket and says "resting for N days". What is out of sight is only counted below the buckets: put off to
a day (later), on the watch list (list), done or obsolete today. Every numbered row takes the same four
answers (scripts/lib/answers.py), the view carries them for the cockpit, and every row a numbering style
shows has a number, in the order of the buckets the cockpit shows.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
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
bv = sys.modules.get("briefing_view") or _load("briefing_view", ROOT / "scripts" / "lib" / "briefing_view.py")
inbox = sys.modules.get("inbox") or _load("inbox", ROOT / "scripts" / "inbox.py")

NOW = dt.datetime(2026, 11, 20, 7, 45)        # a Friday


def sec(sid, kind, items):
    return {"id": sid, "kind": kind, "title": sid, "status": "ok", "items": items, "all": items, "total": len(items)}


def result(*sections, **extra):
    return {"profile": "morning", "title": "Morning", "collected_at": NOW.isoformat(timespec="minutes"),
            "sections": list(sections), **extra}


def profile(view=None, sections=None, **extra):
    return {"schema_version": 1, "scope": "user", "id": "morning", "for": "alice",
            "sections": sections or [{"kind": "inbox"}, {"kind": "tasks"}, {"kind": "advise"}],
            "view": view or {"style": "triage"}, **extra}


def item(iid, title, **kw):
    return {"id": iid, "title": title, "state": "open", "urgency": "today", "kind": "decision", "gate": "your-yes",
            "due": None, "task": None, **kw}


def task(slug, nxt, **kw):
    return {"id": slug, "title": f"Task {slug}", "state": "doing", "next": nxt, "blocked_by": None,
            "changed_at": "2026-10-01", "url": f"work/tasks/{slug}/STATUS.md", **kw}


def quiet(slug, days):
    return {"id": f"advise:quiet:{slug}", "title": f"Task {slug} untouched for {days} days (park?)", "check": "quiet",
            "task": slug, "urgency": "later", "days": days}


def rows_of(view):
    return {r["title"]: (b["id"], r) for b in view["buckets"] for r in b["items"]}


# ---------------------------------------------------------------- four buckets

def test_four_buckets_in_this_order():
    assert bv.BUCKETS == ("do", "plan", "delegate", "waiting")
    v = bv.build(result(), profile())
    assert [b["id"] for b in v["bucket_defs"]] == ["do", "plan", "delegate", "waiting"]


def test_the_buckets_are_named_in_the_profiles_language():
    v = bv.build(result(), {**profile(), "_language": "de"})
    assert [b["title"] for b in v["bucket_defs"]] == ["Tun", "Planen", "Mache ich", "Wartet auf andere"]
    titled = bv.build(result(), {**profile(view={"style": "triage", "buckets": [{"id": "do", "title": "Heute"}]}),
                                 "_language": "de"})
    assert [b["title"] for b in titled["bucket_defs"]] == ["Heute"]


def test_a_resting_task_stays_in_its_own_bucket_and_says_how_long():
    r = result(sec("tasks", "tasks", [task("a", {"what": "draft it"}), task("b", {"what": "ask", "who": "bridge"})]),
               sec("advise", "advise", [quiet("a", 54), quiet("b", 30)]))
    got = rows_of(bv.build(r, profile()))
    assert got["Task a"][0] == "plan" and got["Task a"][1]["resting"] == 54
    assert "resting for 54 days" in got["Task a"][1]["why"]
    assert got["Task b"][0] == "delegate" and got["Task b"][1]["resting"] == 30
    assert not any("untouched" in t for t in got)             # the advice is the mark, never a row of its own


def test_the_resting_mark_in_german():
    r = result(sec("tasks", "tasks", [task("a", {"what": "draft it"})]), sec("advise", "advise", [quiet("a", 1)]))
    got = rows_of(bv.build(r, {**profile(), "_language": "de"}))
    assert "ruht seit 1 Tag" in got["Task a"][1]["why"]


def test_a_resting_task_without_a_row_of_its_own_stands_as_the_advice_in_plan():
    r = result(sec("advise", "advise", [quiet("c", 40)]))
    got = rows_of(bv.build(r, profile()))
    (bucket, row), = got.values()
    assert bucket == "plan" and row["task"] == "c"


def test_an_older_profile_with_drop_and_options_validates_and_shows_four():
    old = {"style": "triage", "buckets": [
        {"id": "do", "title": "Do", "options": ["yes", "later", "drop"]}, {"id": "plan", "options": ["schedule"]},
        {"id": "delegate"}, {"id": "waiting", "options": ["nudge", "wait"], "nudge_after_days": 5}, {"id": "drop"}]}
    assert bv.problems(old, None) == []
    r = result(sec("tasks", "tasks", [task("a", {"what": "draft it"})]), sec("advise", "advise", [quiet("a", 54)]))
    v = bv.build(r, profile(view=old))
    assert [b["id"] for b in v["bucket_defs"]] == ["do", "plan", "delegate", "waiting"]
    assert all("options" not in b for b in v["bucket_defs"]) and all("options" not in b for b in v["buckets"])
    assert rows_of(v)["Task a"][0] == "plan"


def test_a_profile_that_listed_only_drop_shows_the_four():
    v = bv.build(result(), profile(view={"style": "triage", "buckets": [{"id": "drop"}]}))
    assert [b["id"] for b in v["bucket_defs"]] == list(bv.BUCKETS)


def test_a_section_forced_into_drop_validates_and_its_rows_take_their_own_bucket():
    p = profile(sections=[{"kind": "tasks", "bucket": "drop"}])
    assert not [x for x in bf.profile_problems(p, "morning") if "bucket" in x]
    got = rows_of(bv.build(result(sec("tasks", "tasks", [task("a", {"what": "x", "who": "bridge"})])), p))
    assert got["Task a"][0] == "delegate"


def test_no_row_ever_stands_in_drop():
    r = result(sec("tasks", "tasks", [task("a", {"what": "x"})]), sec("advise", "advise", [quiet("a", 90), quiet("z", 9)]))
    for style in ("triage", "report", "calm", "brevity", "plan"):
        v = bv.build(r, profile(view={"style": style}))
        assert not [b for b in v.get("buckets") or [] if b["id"] == "drop"]
        assert "drop" not in (v.get("plan") or {})


# ---------------------------------------------------------------- four answers, carried for the cockpit

def test_the_view_carries_the_four_answers_in_its_language():
    v = bv.build(result(), {**profile(), "_language": "de"})
    assert [a["label"] for a in v["answers"]["answers"]] == ["Mach das", "Später", "Erledigt", "Veraltet"]
    assert [c["id"] for c in v["answers"]["later"]] == ["tomorrow", "monday", "week", "pick", "list"]
    assert v["answers"]["list_day"] == "9999-12-31"


def test_triage_says_the_four_answers_once_and_no_bucket_its_own():
    r = result(sec("inbox", "inbox", [item("i1", "Merge the fix?")]), sec("tasks", "tasks", [task("a", {"what": "x"})]))
    text = bv.draw(bv.build(r, profile()))
    assert "Answer with a number and a word: do · later · done · obsolete" in text
    assert "a yes" not in text and "a schedule" not in text
    de = bv.draw(bv.build(r, {**profile(), "_language": "de"}))
    assert "Antwort mit Nummer und Wort: mach · später · erledigt · veraltet" in de


def test_report_says_the_answers_once_below_the_buckets():
    r = result(sec("inbox", "inbox", [item("i1", "Merge the fix?")]))
    text = bv.draw(bv.build(r, profile(view={"style": "report"})))
    assert "do · later · done · obsolete" in text and "(a " not in text


def test_calm_shows_how_to_answer_with_a_word_and_a_day():
    r = result(sec("inbox", "inbox", [item("i1", "Merge the fix?")]))
    text = bv.draw(bv.build(r, profile(view={"style": "calm"})))
    assert "“1 do”" in text and "“1 later monday”" in text


# ---------------------------------------------------------------- every shown row numbered, in the cockpit's order

def four_rows():
    return result(sec("inbox", "inbox", [item("i1", "Merge the fix?")]),
                  sec("tasks", "tasks", [task("p", {"what": "plan it"}), task("d", {"what": "run it", "who": "bridge"}),
                                         task("w", {"what": "answer", "who": "Ada"})]))


def test_triage_numbers_every_row_also_without_answer_keys():
    v = bv.build(four_rows(), profile(view={"style": "triage", "answer_keys": False}))
    nrs = [r["nr"] for b in v["buckets"] for r in b["items"]]
    assert nrs == [1, 2, 3, 4]
    text = bv.draw(v)
    assert "  -  " not in text and "  4  " in text


def test_calm_numbers_in_the_order_of_the_buckets_the_cockpit_shows():
    v = bv.build(four_rows(), profile(view={"style": "calm"}))
    order = [(b["id"], r["nr"]) for b in v["buckets"] for r in b["items"]]
    assert order == [("do", 1), ("plan", 2), ("delegate", 3), ("waiting", 4)]
    text = bv.draw(v)
    # the printed numbers are the row numbers: I'll do comes before waiting, as in the cockpit
    assert text.index("3. ") < text.index("4. Ada")
    assert text.index("I'll do it if you want") < text.index("Waiting on others")


def test_calm_follows_the_profiles_bucket_order():
    p = profile(view={"style": "calm", "buckets": [{"id": "waiting"}, {"id": "do"}]})
    v = bv.build(four_rows(), p)
    assert [(b["id"], r["nr"]) for b in v["buckets"] for r in b["items"]] == [("waiting", 1), ("do", 2)]


def test_calm_numbers_a_dated_plan_row_in_its_bucket_order():
    r = result(sec("tasks", "tasks", [task("p1", {"what": "one"}), task("p2", {"what": "two", "due": "2026-12-01"})]))
    v = bv.build(r, profile(view={"style": "calm"}))
    plan = next(b for b in v["buckets"] if b["id"] == "plan")
    assert [x["nr"] for x in plan["items"]] == sorted(x["nr"] for x in plan["items"])
    assert bv.numbered(v) == [x for b in v["buckets"] for x in b["items"] if x.get("nr")]


# ---------------------------------------------------------------- out of sight, counted

def test_the_out_of_sight_counts_stand_below_the_buckets():
    r = result(sec("inbox", "inbox", [item("i1", "Merge the fix?")]), aside={"later": 2, "list": 5, "done_today": 1})
    v = bv.build(r, profile())
    assert v["aside"] == {"later": 2, "list": 5, "done_today": 1}
    assert "Out of sight: later 2 · watch list 5 · done today 1" in bv.draw(v)
    de = bv.draw(bv.build(r, {**profile(), "_language": "de"}))
    assert "Außer Sicht: später 2 · Merkliste 5 · fertig heute 1" in de
    assert "Merkliste 5" in bv.draw(bv.build(r, {**profile(view={"style": "calm"}), "_language": "de"}))
    zero = bv.build(result(aside={"later": 0, "list": 0, "done_today": 0}), profile())
    assert "Out of sight" not in bv.draw(zero)
    assert bv.build(result(), profile())["aside"] is None


def _root(tmp_path):
    root = tmp_path / "b"
    for d in ("work/inbox", "work/tasks", "work/done/2026-11", "work/cockpit/settled"):
        (root / d).mkdir(parents=True)
    return root


def _task_file(root, where, slug, **fm):
    path = root / where / slug / "STATUS.md"
    path.parent.mkdir(parents=True)
    path.write_text("---\n" + yaml.safe_dump({"slug": slug, **fm}) + "---\n# " + slug + "\n", encoding="utf-8")


def test_aside_counts_later_the_watch_list_and_done_today(tmp_path):
    root = _root(tmp_path)
    box = inbox.Inbox(root / "work" / "inbox", actor="t", clock=lambda: NOW)
    near = box.add(source="t", kind="decision", summary="Back tomorrow")
    box.event(near, "defer", until="2026-11-21")          # within the lookahead: it is in the view
    far = box.add(source="t", kind="decision", summary="Back in a week")
    box.event(far, "defer", until="2026-11-27")
    shelf = box.add(source="t", kind="idea", summary="Some day")
    box.event(shelf, "defer", until="9999-12-31")
    runs = box.add(source="t", kind="decision", summary="Ada answers")
    box.event(runs, "defer", until="2026-11-27", waits_on="Ada")   # waits on someone: no later of yours
    done = box.add(source="t", kind="finding", summary="Closed today")
    box.close(done)
    gone = box.add(source="t", kind="finding", summary="Dropped today")
    box.drop(gone, note="veraltet")
    _task_file(root, "work/tasks", "parked", status="backlog")
    _task_file(root, "work/tasks", "busy", status="doing")
    _task_file(root, "work/done/2026-11", "finished", status="done", closed="2026-11-20")
    _task_file(root, "work/done/2026-11", "older", status="done", closed="2026-11-02")
    settled = {"dismissed": ["ref:o/r#1"], "dismissed_on": {"ref:o/r#1": "2026-11-20"},
               "hidden": {"ref:o/r#2": "2026-11-30", "ref:o/r#3": "9999-12-31"}}
    got = bf.aside_counts(root, NOW, 1, settled)
    assert got == {"later": 2, "list": 3, "done_today": 4}


def test_collect_json_carries_the_counts_in_the_view(tmp_path, capsys):
    root = _root(tmp_path)
    (root / "bridge-config.yaml").write_text("{}\n", encoding="utf-8")
    _task_file(root, "work/tasks", "parked", status="backlog")
    path = root / "workflow" / "briefings" / "morning.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump(profile(sections=[{"kind": "tasks"}])), encoding="utf-8")
    assert bf.main(["--root", str(root), "collect", "--json", "--no-save"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["view"]["aside"]["list"] == 1
    assert [a["id"] for a in data["view"]["answers"]["answers"]] == ["do", "later", "done", "obsolete"]


def test_the_settled_record_says_the_day_of_each_dismissal(tmp_path):
    root = _root(tmp_path)
    sys.path.insert(0, str(ROOT / "scripts" / "lib"))
    from bridge_cockpit.settled import SettledStore
    SettledStore(root / "work" / "cockpit" / "settled", lambda: 0).dismiss("ref:o/r#1", "done", "An issue")
    rec = bf.settled_record(root, NOW)
    assert rec["dismissed"] == ["ref:o/r#1"] and set(rec["dismissed_on"]) == {"ref:o/r#1"}


# ---------------------------------------------------------------- no answer that is gone

def test_no_row_asks_a_question_of_the_answers_that_are_gone():
    # round 1 of the four answers: 26 rows read "(untouched for 55 days · park? · resting for 55 days)" and waiting
    # rows ended in "nudge?" / "nachfassen?". Park and Nudge are no answers any more: a resting task says only how
    # long it rests, a waiting row only how long it waits (Do it writes the nudge)
    adv = _load("briefing_advise_words", ROOT / "skills" / "briefing" / "scripts" / "advise.py")
    for lang, words in adv.TEXTS.items():
        for key, text in words.items():
            assert not any(w in text for w in ("park", "nudge", "nachfassen", "nachhaken", "anschieben")), (lang, key, text)
    for labels in (bv.LABELS, bv.LABELS_DE):
        assert "nudge" not in labels
    waiting = task("w", {"what": "reply", "who": "Robin"}, changed_at="2026-09-01")
    for lang in ("en", "de"):
        v = bv.build(result(sec("tasks", "tasks", [waiting, task("q", None)]), sec("advise", "advise", [quiet("q", 55)])),
                     {**profile(), "_language": lang})
        text = bv.draw(v)
        for word in ("nudge?", "nachfassen?", "park?", "parken?", "untouched", "unberührt"):
            assert word not in text, (lang, word, text)
        assert ("resting for 55 days" if lang == "en" else "ruht seit 55 Tagen") in text
