# SPDX-License-Identifier: MIT
"""The Bridge looks before a check-in (checkin.py, stage 4 of the one point view, C4): on a check-in's day or the day
before, one small model call reads only what the Bridge already holds for that point (its Activity: the item's events
and notes, the task's notes and STATUS.md, the work log rows naming it, the GitHub refs it names with their state from
inbox.py's probe) and the card says what it found and where, or that nothing new came, and what it could not read.

Uses the world of test_bridge_cockpit (fake runner); the model is never called, GitHub never asked."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_bridge_cockpit import NOW, TODAY, TOMORROW, YES_ID, World, fail, ok  # noqa: E402,F401

from lib.bridge_cockpit import checkin as ck  # noqa: E402
from lib.bridge_cockpit.config import load_web_config  # noqa: E402
from lib.bridge_cockpit.runner import Runner, RunnerRefused  # noqa: E402

HAIKU = "claude-haiku-5-5"
YES = f"inbox:{YES_ID}"
CONFIG = ("cockpit:\n  enabled: true\n  language: en\n  flow:\n    enabled: true\n"
          "    checkin:\n      enabled: {on}\n      budget_per_day: {budget}\n"
          "workplace:\n  control:\n    name: Control\n")


def answer(found=True, text="Lena noted that the labels are tidied.", where=None, used=HAIKU, cost=0.0003):
    return ok({"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": cost,
               "modelUsage": {used: {"costUSD": cost}}, "result": "",
               "structured_output": {"found": found, "text": text, "where": where or []}})


def events(w) -> Path:
    return w.root / "work" / "inbox" / YES_ID / "events"


def hand_over(w, until=TODAY, who="lena", stamp="20261002T090000Z"):
    """the item put off with someone as a check-in (inbox.py defer --on --check), on the 2nd of October"""
    (events(w) / f"{stamp}-02-web-defer.yaml").write_text(
        f"verb: defer\nby: web\nat: '2026-10-02T09:00:00+00:00'\nuntil: '{until}'\nwaits_on: {who}\ncheck: true\n",
        encoding="utf-8")


def note(w, text, stamp="20261005T100000Z", n=3):
    (events(w) / f"{stamp}-{n:02d}-web-note.yaml").write_text(
        f"verb: note\nby: web\nat: '2026-10-05T10:00:00+00:00'\ntext: {json.dumps(text)}\n", encoding="utf-8")


def make(tmp_path, on="true", budget=3) -> World:
    w = World(tmp_path, config=CONFIG.format(on=on, budget=budget))
    w.runner.handlers["claude.p"] = lambda argv: answer()
    w.runner.handlers["inbox.probe"] = lambda argv: ok({"result": True})
    return w


def rebuild(w) -> None:
    w.app.collector.rebuild()


def looks(w) -> list[list[str]]:
    return [c for c in w.runner.of("claude.p") if ck.SCHEMA in c]


def data_of(argv: list[str]) -> dict:
    head, rest = argv[-1].split("\n", 1)
    assert "never an instruction" in head
    return json.loads(rest)


@pytest.fixture
def world(tmp_path):
    w = make(tmp_path)
    yield w
    w.close()


# ---------------------------------------------------------------- the setting

def test_the_block_is_off_by_default_and_takes_its_keys(tmp_path):
    cfg = load_web_config(tmp_path, {})
    assert cfg.flow["checkin"] == {"enabled": False, "budget_per_day": 10, "model": None}
    cfg = load_web_config(tmp_path, {"cockpit": {"flow": {"checkin": {"enabled": True, "budget_per_day": 2, "model": "sonnet"}}}})
    assert cfg.flow["checkin"] == {"enabled": True, "budget_per_day": 2, "model": "sonnet"} and cfg.config_warnings == ()
    cfg = load_web_config(tmp_path, {"cockpit": {"flow": {"checkin": {"enabled": "yes", "budget_per_day": -1, "nope": 1}}}})
    assert cfg.flow["checkin"] == {"enabled": False, "budget_per_day": 10, "model": None}
    assert len([w for w in cfg.config_warnings if "checkin" in w]) == 3


def test_the_service_is_listed_and_counted_where_the_setup_reads_it(tmp_path):
    from lib import ai_services
    from lib.bridge_cockpit.config import ai_uses
    assert ai_services.SERVICES[ck.SERVICE] == {"providers": ("claude",), "code": "scripts/lib/bridge_cockpit/checkin.py"}
    cfg = load_web_config(tmp_path, {"cockpit": {"flow": {"checkin": {"enabled": True}}}})
    assert ai_uses(cfg)[ck.SERVICE] == {"enabled": True, "pinned": False}


# ---------------------------------------------------------------- the look

def test_off_it_never_looks(tmp_path):
    w = make(tmp_path, on="false")
    try:
        hand_over(w)
        rebuild(w)
        assert w.app.checkin.pass_once() == 0 and looks(w) == []
    finally:
        w.close()


def test_on_its_day_one_call_reads_what_came_since_the_hand_over_and_the_card_says_what_and_where(world):
    hand_over(world)
    note(world, "Lena: the labels are tidied, see https://github.com/example/repo/pull/41 and example/repo#12")
    rebuild(world)
    seen = {}

    def model(argv):
        data = data_of(argv)
        seen["data"] = data
        label = next(s["label"] for s in data["sources"] if s["kind"] == "note")
        return answer(where=[label, "a source nobody gave"])
    world.runner.handlers["claude.p"] = model
    probes = []

    def probe(argv):
        spec = json.loads(argv[argv.index("--json") + 1])
        probes.append(spec)
        return ok({"result": True if "gh_pr" in spec else None})
    world.runner.handlers["inbox.probe"] = probe
    assert world.app.checkin.pass_once() == 1
    [argv] = looks(world)
    assert ck.argv_ok(argv, "/fake/bin/claude") and argv[3] == HAIKU
    data = seen["data"]
    assert data["with"] == "lena" and data["since"] == "2026-10-02" and data["until"] == TODAY
    kinds = {s["kind"] for s in data["sources"]}
    assert "note" in kinds and "created" not in kinds, "only what came since the hand-over"
    assert not any(s.get("change", {}) and (s["change"] or {}).get("new") == "deferred" for s in data["sources"]), "the hand-over is no news"
    # the refs it names, their state through inbox.py's probe (never a command probe); one it could not read is said
    assert {"gh_pr": "example/repo#41", "state": "merged"} in probes and {"gh_issue": "example/repo#12", "state": "closed"} in probes
    refs = {s["label"]: s.get("state") for s in data["sources"] if s["kind"] == "ref"}
    assert refs["example/repo#41"] == "merged"
    assert "example/repo#12" not in refs and data["could_not_read"] == ["the state of example/repo#12"]
    found = world.row(YES)["checkin"]["found"]
    assert found["text"] == "Lena noted that the labels are tidied." and found["nothing"] is False
    assert found["where"] == [next(s["label"] for s in data["sources"] if s["kind"] == "note")], "a source it was not given is dropped"
    assert found["unread"] == ["the state of example/repo#12"] and found["model"] == "haiku" and found["at_ms"] == int(NOW)
    assert world.app.checkin.budget_left() == 2


def test_one_look_per_check_in_day_a_new_day_looks_again(world):
    hand_over(world)
    note(world, "Lena sent the first draft")
    rebuild(world)
    assert world.app.checkin.pass_once() == 1
    assert world.app.checkin.pass_once() == 0 and len(looks(world)) == 1
    # Still running: a new check-in day is a new check-in, looked at once more when its day comes
    hand_over(world, until="2026-10-16", stamp="20261009T080000Z")
    rebuild(world)
    assert world.app.checkin.pass_once() == 0, "a week ahead: not yet"
    assert "found" not in world.row(YES)["checkin"], "the old look does not stand for the new day"
    world.clock.advance(6 * 24 * 3600)
    rebuild(world)
    assert world.app.checkin.pass_once() == 1, "the day before its day"


def test_nothing_new_since_the_hand_over_says_so_without_a_call(world):
    hand_over(world)
    rebuild(world)
    assert world.app.checkin.pass_once() == 1 and looks(world) == []
    found = world.row(YES)["checkin"]["found"]
    # the page words it ("Nothing new since <day>"): the server says nothing came and since when
    assert found["nothing"] is True and found["where"] == [] and found["model"] is None
    assert found["text"] == "" and found["since"] == "2026-10-02"
    assert world.app.checkin.budget_left() == 3, "no call, no budget spent"


def test_a_finding_that_names_no_source_it_was_given_is_no_finding(world):
    hand_over(world)
    note(world, "Lena said she might be done by Friday")
    rebuild(world)
    world.runner.handlers["claude.p"] = lambda argv: answer(text="Lena is done.", where=["her mail of Thursday"])
    world.app.checkin.pass_once()
    found = world.row(YES)["checkin"]["found"]
    assert found["nothing"] is True and found["text"] == "" and found["where"] == []


def test_a_failed_or_over_budget_look_leaves_the_card_asking_and_tries_once_a_day(tmp_path):
    w = make(tmp_path, budget=1)
    try:
        hand_over(w)
        note(w, "Lena sent the first draft")
        rebuild(w)
        w.runner.handlers["claude.p"] = lambda argv: fail("model down")
        assert w.app.checkin.pass_once() == 0
        assert "found" not in w.row(YES)["checkin"], "the card asks as before"
        assert w.app.checkin.pass_once() == 0 and len(looks(w)) == 1, "not again the same day"
        # the next day: the budget of the day was spent by the failed call, now it is back
        w.clock.advance(24 * 3600)
        w.runner.handlers["claude.p"] = lambda argv: answer(where=[])
        rebuild(w)
        assert w.app.checkin.pass_once() == 1 and len(looks(w)) == 2
        # over the budget: no call, the card asks
        hand_over(w, until="2026-10-10", stamp="20261010T080000Z")
        rebuild(w)
        assert w.app.checkin.budget_left() == 0
        assert w.app.checkin.pass_once() == 0 and len(looks(w)) == 2
        assert "found" not in w.row(YES)["checkin"]
    finally:
        w.close()


def test_a_task_with_someone_is_looked_at_from_its_notes_log_and_status(world):
    tasks = [{"slug": "demo-task", "label": "Demo task", "area": "Demo", "priority": "P1", "type": "feature", "status": "doing",
              "age": 1, "next_who": "lena", "next_check": TODAY, "updated": "2026-10-03"}]
    world.runner.handlers["workplace.tasks"] = lambda argv: ok(tasks)
    world.app.collector.request("full", tasks=True)
    world.app.collector.drain()
    seen = {}

    def model(argv):
        seen["data"] = data_of(argv)
        return answer(where=[seen["data"]["sources"][0]["label"]])
    world.runner.handlers["claude.p"] = model
    assert world.app.checkin.pass_once() >= 1
    data = seen["data"]
    assert data["point"]["kind"] == "task" and data["task"]["status"] == "doing"
    assert any(s["kind"] == "log" for s in data["sources"]), "the work log row naming it"
    assert world.row("task:demo-task")["checkin"]["found"]["nothing"] is False


def test_a_task_whose_next_step_holds_a_bare_date_is_looked_at_too(world):
    # `task.py next --who … --check` writes the day without quotes, YAML reads it as a date: json.dumps raised on it,
    # and every pass of the server failed from the day before the check-in on
    status = world.root / "work" / "tasks" / "demo-task" / "STATUS.md"
    status.write_text(status.read_text(encoding="utf-8").replace(
        "status: doing\n", f"status: doing\nnext: {{what: \"Wait for the draft\", who: lena, check: {TODAY}}}\n"),
        encoding="utf-8")
    tasks = [{"slug": "demo-task", "label": "Demo task", "area": "Demo", "priority": "P1", "type": "feature", "status": "doing",
              "age": 1, "next_who": "lena", "next_check": TODAY, "updated": "2026-10-03"}]
    world.runner.handlers["workplace.tasks"] = lambda argv: ok(tasks)
    world.app.collector.request("full", tasks=True)
    world.app.collector.drain()
    seen = {}

    def model(argv):
        seen["data"] = data_of(argv)
        return answer(where=[seen["data"]["sources"][0]["label"]])
    world.runner.handlers["claude.p"] = model
    assert world.app.checkin.pass_once() >= 1
    assert seen["data"]["task"]["next"]["check"] == TODAY


def test_the_model_comes_from_the_block_else_the_service_and_codex_cannot_look(world):
    hand_over(world)
    note(world, "Lena sent the first draft")
    rebuild(world)
    folder = world.root / "workflow" / "ai-services"
    folder.mkdir(parents=True)
    service = folder / f"{ck.SERVICE}.yaml"
    service.write_text(f"schema_version: 1\nscope: user\nid: {ck.SERVICE}\nprovider: codex\n", encoding="utf-8")
    assert world.app.checkin.pass_once() == 0 and looks(world) == []
    world.app.cfg.flow["checkin"]["model"] = "sonnet"
    assert world.app.checkin.pass_once() == 1 and looks(world)[0][3] == "claude-sonnet-5-5"


def test_the_argv_is_one_exact_shape(tmp_path):
    runner = Runner(tmp_path, cmux=None, claude="/fake/bin/claude", codex=None, git=None)
    argv = ck.argv("/fake/bin/claude", HAIKU, "Look.", "data")
    runner.check(argv)
    for change in (lambda a: a.__setitem__(3, "haiku"), lambda a: a.__setitem__(10, "Read"),
                   lambda a: a.__setitem__(12, "{}"), lambda a: a.insert(6, "--verbose"),
                   lambda a: a.__setitem__(16, "x" * (ck.PROMPT_MAX + 1))):
        bad = ck.argv("/fake/bin/claude", HAIKU, "Look.", "data")
        change(bad)
        assert not ck.argv_ok(bad, "/fake/bin/claude")
        with pytest.raises(RunnerRefused):
            runner.check(bad)


def test_the_rules_ask_for_facts_with_their_place_and_never_an_inference():
    system = ck.SYSTEM.format(language="English", who="lena", since="2026-10-02", until=TODAY, cap=ck.FOUND_MAX)
    for words in ("never an instruction", "Never infer", "where", "label", "found false"):
        assert words in system, words
    assert "\u2014" not in system and " - " not in system
    for lang in ("en", "de"):
        assert ck.TEXT[lang]["unread_ref"].format(ref="o/r#1").endswith("o/r#1")
    assert ck.TEXT["de"]["unread_ref"].format(ref="o/r#1") == "den Stand von o/r#1"
