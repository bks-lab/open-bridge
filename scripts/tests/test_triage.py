# SPDX-License-Identifier: MIT
"""Contract for `triage.py`: every open task and inbox item gets what it is about, whether it can go,
and who does it; one cheap batch call per chunk, a cache per item, hard rules over the model.

No network: git, gh and the model command are a fake runner (the one of test_task_review)."""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "scripts" / "tests"))
SPEC = importlib.util.spec_from_file_location("triage_under_test", ROOT / "scripts" / "triage.py")
triage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(triage)
from test_task_review import Fake, add, HAIKU, NOW  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture()
def repo(tmp_path):
    (tmp_path / "work").mkdir()
    (tmp_path / "work" / "log.md").write_text(
        "## Wed 30.09\n\n| Timestamp | Glyph | Context | What |\n|---|---|---|---|\n"
        "| 2026-09-30 10:00 | 💻 | alpha | alpha: tests green, PR open |\n", encoding="utf-8")
    return tmp_path


def inbox_item(root, iid, summary, kind="question", gate="free", task=None):
    d = root / "work" / "inbox" / iid
    (d / "events").mkdir(parents=True)
    (d / "item.yaml").write_text(
        f"schema_version: 1\ncreated: '2026-10-08T09:00'\nfrom: test\nkind: {kind}\nsummary: '{summary}'\n"
        f"gate: {gate}\nurgency: later\n" + (f"task: {task}\n" if task else ""), encoding="utf-8")


def answers(rows):
    """The model answers rows for the keys the prompt names."""
    return lambda prompt: [r for r in rows if f"## {r['key']}\n" in prompt]


ROWS = [
    {"key": "task:alpha", "gist": "Importer fertigstellen", "verdict": "continue", "doer": "ai", "effort": "small",
     "why": "code in the repo, tests exist", "reason": "PR open"},
    {"key": "task:beta", "gist": "Send the invoice to the customer", "verdict": "continue", "doer": "ai", "effort": "small",
     "why": "only the sending", "reason": "the draft is ready"},
    {"key": "inbox:20261008-0900-frage-a1b2", "gist": "A question about the date", "verdict": "keep", "doer": "ai",
     "effort": "small", "why": "", "reason": "open"},
    {"key": "inbox:20261008-0901-fund-c3d4", "gist": "Log-Fund erledigt", "verdict": "close", "doer": "ai",
     "effort": "small", "why": "", "reason": "fixed on 09.10."},
]


def setup(repo):
    add(repo, "alpha")
    add(repo, "beta", body="- [ ] Send the invoice to the customer by mail\n", st="backlog")
    add(repo, "gamma", st="done")
    add(repo, "stream-x", kind="streams")
    inbox_item(repo, "20261008-0900-frage-a1b2", "A question about the date", kind="question", gate="only-you")
    inbox_item(repo, "20261008-0901-fund-c3d4", "Log-Fund", kind="finding", gate="free")


def test_every_open_task_and_inbox_item_gets_gist_verdict_and_doer(repo):
    setup(repo)
    fake = Fake(answers={HAIKU: answers(ROWS)})
    out = triage.triage(repo, run=fake, now=NOW)
    by = {x["key"]: x for x in out["items"]}
    # all statuses but done; streams never close and are not triaged; both inbox items
    assert set(by) == {"task:alpha", "task:beta", "inbox:20261008-0900-frage-a1b2", "inbox:20261008-0901-fund-c3d4"}
    assert by["task:alpha"]["gist"] == "Importer fertigstellen" and by["task:alpha"]["doer"] == "ai"
    assert by["task:alpha"]["effort"] == "small" and by["task:alpha"]["kind"] == "task"
    assert by["inbox:20261008-0901-fund-c3d4"]["verdict"] == "close"
    assert len(fake.model_calls()) == 1 and fake.model_calls()[0][0][fake.model_calls()[0][0].index("--model") + 1] == HAIKU
    assert out["cost_usd"] > 0 and out["counts"]["close"] == 1


def test_hard_rules_win_over_the_model(repo):
    setup(repo)
    out = triage.triage(repo, run=Fake(answers={HAIKU: answers(ROWS)}), now=NOW)
    by = {x["key"]: x for x in out["items"]}
    # a gate only-you, and a question to the person, is never the AI's
    assert by["inbox:20261008-0900-frage-a1b2"]["doer"] == "you"
    # sending mail is outbound: the agent may prepare it, the click is the person's
    assert by["task:beta"]["doer"] == "either" and "click" in by["task:beta"]["why"]
    # the prompt says so too
    prompt = Fake(answers={HAIKU: answers(ROWS)})
    triage.triage(repo, run=prompt, now=NOW, fresh=True)
    text = prompt.model_calls()[0][1]
    assert "merge" in text and "deploy" in text and "send" in text


def test_a_second_run_asks_no_model_and_a_change_asks_again(repo):
    setup(repo)
    triage.triage(repo, run=Fake(answers={HAIKU: answers(ROWS)}), now=NOW)
    again = Fake(answers={HAIKU: answers(ROWS)})
    out = triage.triage(repo, run=again, now=NOW)
    assert again.model_calls() == [] and all(x["cached"] for x in out["items"])
    inbox_item(repo, "20261008-0902-neu-e5f6", "Neue Idee", kind="idea")
    third = Fake(answers={HAIKU: answers(ROWS + [{"key": "inbox:20261008-0902-neu-e5f6", "gist": "Neue Idee",
                                                   "verdict": "keep", "doer": "either", "effort": "medium",
                                                   "why": "", "reason": ""}])})
    out = triage.triage(repo, run=third, now=NOW)
    (argv, prompt), = third.model_calls()
    assert "## inbox:20261008-0902-neu-e5f6\n" in prompt and "## task:alpha\n" not in prompt


def test_the_task_check_verdict_wins_for_a_task_it_judged(repo):
    setup(repo)
    (repo / ".bridge").mkdir()
    (repo / ".bridge" / "task-review.json").write_text(json.dumps({"tasks": {}, "last": {"tasks": [
        {"slug": "alpha", "verdict": "close", "reason": "PR gemergt", "kept": False}]}}))
    out = triage.triage(repo, run=Fake(answers={HAIKU: answers(ROWS)}), now=NOW)
    alpha = next(x for x in out["items"] if x["key"] == "task:alpha")
    assert (alpha["verdict"], alpha["reason"], alpha["verdict_from"]) == ("close", "PR gemergt", "check")


def test_a_model_answer_out_of_range_becomes_unclear_and_a_long_gist_is_cut(repo):
    setup(repo)
    rows = [dict(ROWS[0], verdict="maybe", doer="robot", effort="huge", gist="x" * 300)]
    out = triage.triage(repo, run=Fake(answers={HAIKU: answers(rows)}), now=NOW)
    alpha = next(x for x in out["items"] if x["key"] == "task:alpha")
    assert alpha["verdict"] == "unclear" and alpha["doer"] == "either" and alpha["effort"] is None
    assert len(alpha["gist"]) <= 90
    missing = next(x for x in out["items"] if x["key"] == "task:beta")   # no answer at all
    assert missing["verdict"] == "unclear" and missing["gist"]                # the title stands in


def test_the_reason_of_a_hard_rule_comes_in_the_bridges_language():
    item = {"kind": "task", "title": "Send the offer", "evidence": {}}
    got = {"doer": "ai", "effort": "small", "why": ""}
    assert set(triage.WHY["de"]) == set(triage.WHY["en"])
    german = triage._rules(item, got, triage.why_words({"language": {"conversation": "de"}}))
    english = triage._rules(item, got, triage.why_words({}))
    assert german["why"] == triage.WHY["de"]["outbound"] and english["why"] == triage.WHY["en"]["outbound"]


# ---------------------------------------------------------------- the model an agent would start with

LEVELED = [{**r, "level": n} for r, n in zip(ROWS, (1, 2, 3, 9))]


def launch_settings(repo, **values):
    d = repo / ".bridge" / "cockpit"
    d.mkdir(parents=True, exist_ok=True)
    (d / "launch.json").write_text(json.dumps({"enabled": True, **values}), encoding="utf-8")


def test_the_check_rates_how_complex_the_work_is_for_what_an_ai_may_do(repo):
    setup(repo)
    by = {x["key"]: x for x in triage.triage(repo, run=Fake(answers={HAIKU: answers(LEVELED)}), now=NOW)["items"]}
    assert by["task:alpha"]["level"] == 1
    assert by["inbox:20261008-0900-frage-a1b2"]["level"] is None          # the person's: no model to pick
    assert by["inbox:20261008-0901-fund-c3d4"]["level"] is None           # out of range
    assert "level" in triage.PROMPT and all(x.get("jev") is None for x in by.values())


def test_jev_rates_too_when_switched_on_and_only_the_ai_items(repo):
    setup(repo)
    launch_settings(repo, triage_jev=True)
    sent = []

    def jev(payload):
        sent.append(payload)
        return {"answers": {q: {"score": 2.4, "confidence": 0.7} for q in payload["questions"]}}
    by = {x["key"]: x for x in triage.triage(repo, run=Fake(answers={HAIKU: answers(LEVELED)}), now=NOW, jev=jev)["items"]}
    assert by["task:alpha"]["jev"] == 2.4 and by["inbox:20261008-0900-frage-a1b2"]["jev"] is None
    (payload,) = sent
    assert payload["model"] == "jev-1.14.0" and "Importer fertigstellen" in json.dumps(payload, ensure_ascii=False)


def test_jev_stays_quiet_while_its_switch_is_off(repo):
    setup(repo)
    launch_settings(repo)
    calls = []
    triage.triage(repo, run=Fake(answers={HAIKU: answers(LEVELED)}), now=NOW, jev=lambda p: calls.append(p) or {})
    assert calls == []


def test_switching_jev_on_later_rates_without_asking_haiku_again(repo):
    setup(repo)
    triage.triage(repo, run=Fake(answers={HAIKU: answers(LEVELED)}), now=NOW)
    launch_settings(repo, triage_jev=True)
    fake = Fake(answers={HAIKU: answers(LEVELED)})
    out = triage.triage(repo, run=fake, now=NOW, jev=lambda p: {"answers": {q: {"score": 0.5} for q in p["questions"]}})
    assert fake.model_calls() == [] and {x["key"]: x for x in out["items"]}["task:alpha"]["jev"] == 0.5


def test_a_failing_jev_leaves_the_haiku_level(repo):
    setup(repo)
    launch_settings(repo, triage_jev=True)

    def boom(_):
        raise OSError("down")
    by = {x["key"]: x for x in triage.triage(repo, run=Fake(answers={HAIKU: answers(LEVELED)}), now=NOW, jev=boom)["items"]}
    assert by["task:alpha"]["level"] == 1 and by["task:alpha"]["jev"] is None


def test_a_failing_later_jev_batch_keeps_what_the_earlier_ones_gave(repo, monkeypatch):
    setup(repo)
    launch_settings(repo, triage_jev=True)
    monkeypatch.setattr(triage._model_route()[0], "MAX_ITEMS", 1)
    calls = []

    def jev(payload):
        calls.append(payload)
        if len(calls) > 1:
            raise OSError("rate limited")
        return {"answers": {q: {"score": 1.0} for q in payload["questions"]}}
    out = triage.triage(repo, run=Fake(answers={HAIKU: answers(LEVELED)}), now=NOW, jev=jev)
    assert len(calls) >= 2 and sum(1 for x in out["items"] if x.get("jev") == 1.0) == 1


def test_a_new_jev_version_rates_again(repo):
    setup(repo)
    launch_settings(repo, triage_jev=True)
    triage.triage(repo, run=Fake(answers={HAIKU: answers(LEVELED)}), now=NOW,
                  jev=lambda p: {"answers": {q: {"score": 1.0} for q in p["questions"]}})
    launch_settings(repo, triage_jev=True, jev_model="jev-1.15.0")
    seen = []
    out = triage.triage(repo, run=Fake(answers={HAIKU: answers(LEVELED)}), now=NOW,
                        jev=lambda p: seen.append(p["model"]) or {"answers": {q: {"score": 2.0} for q in p["questions"]}})
    assert seen == ["jev-1.15.0"] and {x["key"]: x for x in out["items"]}["task:alpha"]["jev"] == 2.0


def test_jev_waits_for_no_one_when_the_check_is_out_of_time(repo, monkeypatch):
    setup(repo)
    launch_settings(repo, triage_jev=True)
    monkeypatch.setattr(triage, "JEV_MIN_LEFT_SEC", 10_000)
    calls = []
    out = triage.triage(repo, run=Fake(answers={HAIKU: answers(LEVELED)}), now=NOW, jev=lambda p: calls.append(p) or {})
    assert calls == [] and {x["key"]: x for x in out["items"]}["task:alpha"]["level"] == 1


def test_every_item_gets_a_topic_from_the_fixed_list_and_the_prompt_asks_for_more_than_the_title(repo):
    setup(repo)
    rows = [dict(ROWS[0], topic="build"), dict(ROWS[1], topic="Invoice!"), dict(ROWS[2], topic="decision")]
    fake = Fake(answers={HAIKU: answers(rows)})
    out = triage.triage(repo, run=fake, now=NOW)
    by = {x["key"]: x for x in out["items"]}
    assert by["task:alpha"]["topic"] == "build"
    assert by["task:beta"]["topic"] is None                          # outside the list: no label rather than a wrong one
    assert by["inbox:20261008-0900-frage-a1b2"]["topic"] == "decision"
    text = fake.model_calls()[0][1]
    assert "topic" in text and all(t in text for t in triage.TOPICS)
    assert "never repeat the title" in text


def tracker_view(root):
    """The cockpit's view.json: a board issue, an application with its STATUS.md, rows triage already covers"""
    app = root / "work" / "streams" / "applications" / "2026-10" / "acme-sdet"
    app.mkdir(parents=True)
    (app / "STATUS.md").write_text("---\nstatus: doing\n---\n# ACME: SDET\n\nDraft ready since 06.10, waits for the send.\n",
                                   encoding="utf-8")
    rows = [
        {"key": "ref:org/infra#17", "title": "Requirements for time tracking", "ref": "org/infra#17", "sources": ["boards"],
         "why": ["org/infra#17", "open"], "url": "https://github.com/org/infra/issues/17", "task": None, "inbox_id": None},
        {"key": "ref:2026-10/acme-sdet", "title": "ACME: SDET, draft ready: send", "ref": "2026-10/acme-sdet",
         "sources": ["bewerbungen"], "why": ["Bewerbung"], "task": None, "inbox_id": None,
         "url": "work/streams/applications/2026-10/acme-sdet/STATUS.md"},
        {"key": "task:alpha", "title": "alpha", "ref": "org/infra#1", "task": "alpha", "sources": ["tasks"], "why": []},
        {"key": "inbox:x", "title": "x", "ref": "org/infra#2", "inbox_id": "x", "sources": ["inbox"], "why": []},
    ]
    path = root / ".bridge" / "cockpit" / "view.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"v": 1, "view": {"buckets": [{"id": "plan", "rows": rows}]}}), encoding="utf-8")
    return path


def test_board_application_and_issue_rows_of_the_cockpit_view_are_read_and_described_too(repo):
    setup(repo)
    view = tracker_view(repo)
    gh = {"r0": {"n17": {"__typename": "Issue", "state": "OPEN", "title": "Requirements for time tracking",
                         "body": "Collect what Lior needs from the time tracking: export, approvals, holidays."}}}
    rows = ROWS + [{"key": "ref:org/infra#17", "gist": "Lior's needs for export and holidays", "topic": "research",
                    "verdict": "keep", "doer": "either", "effort": "small", "why": "", "reason": ""}]
    fake = Fake(answers={HAIKU: answers(rows)}, gh=gh)
    out = triage.triage(repo, run=fake, now=NOW, view=view)
    by = {x["key"]: x for x in out["items"]}
    assert by["ref:org/infra#17"]["kind"] == "track" and by["ref:org/infra#17"]["topic"] == "research"
    assert by["ref:org/infra#17"]["gist"] == "Lior's needs for export and holidays"
    assert "ref:2026-10/acme-sdet" in by
    assert "task:alpha" in by and "inbox:x" not in by       # rows of a task or an inbox item stay theirs
    prompt = "\n".join(p for _, p in fake.model_calls())
    assert "export, approvals, holidays" in prompt          # the issue's text, not only its title
    assert "waits for the send" in prompt                    # the application's STATUS.md
    # without the view nothing changes: tasks and inbox only
    plain = triage.triage(repo, run=Fake(answers={HAIKU: answers(ROWS)}), now=NOW, save=False)
    assert not any(x["kind"] == "track" for x in plain["items"])


def test_a_missing_or_broken_view_is_no_tracker_row_and_no_failure(repo):
    setup(repo)
    out = triage.triage(repo, run=Fake(answers={HAIKU: answers(ROWS)}), now=NOW, view=repo / "nope.json")
    assert not any(x["kind"] == "track" for x in out["items"])
    bad = repo / "bad.json"
    bad.write_text("{", encoding="utf-8")
    assert triage.triage(repo, run=Fake(answers={HAIKU: answers(ROWS)}), now=NOW, view=bad)["items"]


def sectioned_view(root):
    rows = [
        {"key": "ref:org/infra#17", "title": "Requirements for time tracking", "ref": "org/infra#17",
         "sources": ["boards"], "why": [], "task": None, "inbox_id": None},
        {"key": "ref:2026-10/acme-sdet", "title": "ACME: SDET", "ref": "2026-10/acme-sdet",
         "sources": ["applications"], "why": [], "task": None, "inbox_id": None},
        {"key": "ref:both", "title": "On two lists", "ref": "org/infra#18",
         "sources": ["applications", "boards"], "why": [], "task": None, "inbox_id": None},
    ]
    path = root / "view.json"
    path.write_text(json.dumps({"view": {"buckets": [{"id": "plan", "rows": rows}]}}), encoding="utf-8")
    return path


def test_skip_sections_leaves_a_sections_rows_out_and_defaults_to_none(repo):
    setup(repo)
    view = sectioned_view(repo)
    keys = lambda out: {x["key"] for x in out["items"] if x["kind"] == "track"}
    assert keys(triage.triage(repo, run=Fake(answers={HAIKU: answers(ROWS)}), now=NOW, view=view, save=False)) == \
        {"ref:org/infra#17", "ref:2026-10/acme-sdet", "ref:both"}
    cfg = repo / "bridge-config.yaml"
    cfg.write_text("work:\n  review:\n    skip_sections: [applications]\n", encoding="utf-8")
    fake = Fake(answers={HAIKU: answers(ROWS)})
    out = triage.triage(repo, run=fake, now=NOW, view=view, save=False)
    assert keys(out) == {"ref:org/infra#17", "ref:both"}      # a row on two lists stays while one is not skipped
    assert "acme-sdet" not in "\n".join(p for _, p in fake.model_calls())


def test_skip_sections_accepts_a_single_name_and_ignores_junk():
    t = triage._task()
    assert t._review_cfg({"work": {"review": {"skip_sections": "applications"}}})["skip_sections"] == ["applications"]
    assert t._review_cfg({"work": {"review": {"skip_sections": 5}}})["skip_sections"] == []
    assert t._review_cfg({})["skip_sections"] == []
