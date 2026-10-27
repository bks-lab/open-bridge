# SPDX-License-Identifier: MIT
"""The Activity tab of the Work through page (activity.py): one feed of what happened to a point, newest first, from
the sources the Bridge already keeps (notes, the log, the files in deliverables/, status changes, theme moves,
decisions, starts of agents, sessions, code references), with counts per filter and the facts of the fields column;
the documents served with a policy per file type; a document attached to the task's deliverables/ under strict
rules; a summary of a small model on a click, within a daily budget. And `by` on the decision verbs, kept in the
history and the starts.

Uses the world of test_bridge_cockpit (fake runner, fake git); the model is never called, git never runs."""
from __future__ import annotations

import base64
import datetime as dt
import http.client
import json
import math
import os
import sys
import urllib.parse
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_bridge_cockpit import NOW, ONLY_ID, TOMORROW, YES_ID, World, fail, ok, private_key_dir  # noqa: E402,F401

from lib.bridge_cockpit import activity as act  # noqa: E402
from lib.bridge_cockpit.actions import ActionError  # noqa: E402
from lib.bridge_cockpit.config import flow_defaults, load_web_config  # noqa: E402
from lib.bridge_cockpit.runner import Runner, RunnerRefused  # noqa: E402

HAIKU = "claude-haiku-5-5"
DEMO = "task:demo-task"
ONLY = f"inbox:{ONLY_ID}"
YES = f"inbox:{YES_ID}"
ISSUE = "ref:example/repo#12"
VENDOR = "ref:example/repo#7"
FAKE_GIT = "/fake/bin/git"
DAY_MS = 24 * 3600 * 1000

CONFIG = ("cockpit:\n  enabled: true\n  language: en\n  flow:\n    enabled: {flow}\n"
          "    summary:\n      enabled: {summary}\n      budget_per_day: {budget}\n"
          "    attach:\n      enabled: {attach}\n      max_mb: {mb}\n"
          "workplace:\n  control:\n    name: Control\n")

STATUS_MD = """---
type: feature
status: review
priority: P1
created: 2026-10-01
last_updated: 2026-10-08
headline: Demo task
origin: invented
sync:
  github:
    repo: example/repo
    issues: [12]
    pull_requests: [34]
---

# Demo task

## Goal

Ship the demo.

## Notes

- 2026-10-02: Build plan written, see example/repo#40
- 2026-10-03: With AI: agent started from the cockpit (let AI do it)
- 2026-10-04: Result: the draft is in deliverables/plan.md
- 2026-10-05: Attached: deliverables/offer.pdf
- 2026-10-06: Review filed https://github.com/example/repo/pull/41 and #43
- 2026-10-09: started the demo
"""


def ms(y, mo, d, h=12, mi=0):
    return int(dt.datetime(y, mo, d, h, mi).timestamp() * 1000)


T1, T2, T3 = ms(2026, 10, 2, 9), ms(2026, 10, 4, 9), ms(2026, 10, 6, 9)
S1, S2 = ms(2026, 10, 1, 10), ms(2026, 10, 3, 10)


def git_docs(*records):
    """the output of the docs log: records newest first, each (at_ms, [(status, path)])"""
    return "".join(f"\x1e{at // 1000}\x1fTest Person\n\n" + "".join(f"{s}\t{p}\n" for s, p in files)
                   for at, files in records)


def git_status(*records):
    """the output of the status log: records newest first, each (at_ms, old or None, new)"""
    out = []
    for at, old, new in records:
        head = "--- /dev/null\n" if old is None else "--- a/work/tasks/demo-task/STATUS.md\n"
        lines = (f"-status: {old}\n" if old is not None else "") + f"+status: {new}\n"
        out.append(f"\x1e{at // 1000}\x1fTest Person\n\ndiff --git a/x b/x\n{head}+++ b/work/tasks/demo-task/STATUS.md\n"
                   f"@@ -3 +3 @@\n{lines}")
    return "".join(out)


DOCS_OUT = git_docs((T3, [("M", "work/tasks/demo-task/deliverables/plan.md")]),
                    (T2, [("M", "work/tasks/demo-task/deliverables/plan.md")]),
                    (T1, [("A", "work/tasks/demo-task/deliverables/plan.md"),
                          ("A", "work/tasks/demo-task/deliverables/gone.md")]))
STATUS_OUT = git_status((S2, "backlog", "doing"), (S1, None, "backlog"))


def git_handler(docs=DOCS_OUT, status=STATUS_OUT):
    def handle(argv):
        return ok(docs if "--name-status" in argv else status)
    return handle


def make_world(tmp_path, flow="true", summary="true", budget=3, attach="true", mb=1, git=FAKE_GIT):
    w = World(tmp_path, config=CONFIG.format(flow=flow, summary=summary, budget=budget, attach=attach, mb=mb))
    w.runner.git = git
    w.runner.handlers["git.log"] = git_handler()
    w.runner.handlers["claude.p"] = lambda argv: summary_answer("The plan was written and went to review.")
    task = w.root / "work" / "tasks" / "demo-task"
    (task / "STATUS.md").write_text(STATUS_MD, encoding="utf-8")
    os.utime(task / "STATUS.md", (ms(2026, 10, 8, 15) / 1000,) * 2)
    deliv = task / "deliverables"
    (deliv / "sub").mkdir(parents=True)
    for rel, at in (("plan.md", T3 - 60_000), ("offer.pdf", ms(2026, 10, 5, 11)), ("sub/deep.txt", ms(2026, 10, 7, 8)),
                    (".hidden", ms(2026, 10, 7, 8))):
        (deliv / rel).write_text(f"content of {rel}\n", encoding="utf-8")
        os.utime(deliv / rel, (at / 1000,) * 2)
    (deliv / "link.md").symlink_to(task / "STATUS.md")
    return w


@pytest.fixture
def world(tmp_path):
    w = make_world(tmp_path)
    yield w
    w.close()


def summary_answer(text, used=HAIKU, cost=0.0004):
    return ok({"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": cost,
               "modelUsage": {used: {"costUSD": cost}}, "result": "", "structured_output": {"text": text}})


def get(w, route, **query):
    status, headers, body = w.request("GET", f"{route}?{urllib.parse.urlencode(query)}", headers=w.cookie)
    return status, headers, body


def feed(w, key=DEMO, **extra):
    status, _h, body = get(w, "/api/flow/activity", key=key, **extra)
    assert status == 200, body
    return json.loads(body)


def kinds(data):
    return [r["kind"] for r in data["rows"]]


def of(data, kind):
    return [r for r in data["rows"] if r["kind"] == kind]


def seed_sources(w):
    """a start of an agent, a session, a workflow run, two theme moves, a Jev order and a decision on the demo task"""
    app = w.app
    app.launches.record([{"key": DEMO, "item": "demo-task", "title": "Demo task", "mode": "go", "by": "instruction"}])
    app.store.link_session("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", "demo-task", "Demo session", "/tmp/demo", "hand")
    app.sessions.runs = [{"id": "wf_demo", "name": "demo review", "status": "completed", "summary": "Reviewed the plan",
                          "task": "demo-task", "since_ms": ms(2026, 10, 7, 14), "at_ms": ms(2026, 10, 7, 15)}]
    data = app.themes.load()
    data["themes"] = [{"id": "t000001", "name": "Release", "by": "person"}]
    data["assign"] = {DEMO: {"theme": "t000001", "by": "person"}}
    data["moves"] = [{"key": DEMO, "from": None, "to": "Docs", "by": "ai", "at_ms": ms(2026, 10, 7, 9)},
                     {"key": DEMO, "from": "Docs", "to": "Release", "by": "person", "at_ms": ms(2026, 10, 8, 9)},
                     {"key": "task:other-task", "from": None, "to": "Docs", "by": "ai", "at_ms": ms(2026, 10, 8, 9)}]
    app.themes.save(data)
    (w.state / "jev-pages.json").write_text(json.dumps({"v": 1, "orders": {"work": {
        "at_ms": int(NOW) - 3600_000, "day": "2026-10-09", "items": [
            {"key": DEMO, "rank": 4, "quadrant": "plan", "urgency": 0.67, "impact": 1.0, "effort": 0.33, "only_me": 0.8},
            {"key": "task:other-task", "rank": 1, "quadrant": "now"}]}}}), encoding="utf-8")
    w.act("later", key=DEMO, until=TOMORROW, by="suggestion")
    app.collector.rebuild()


# ---------------------------------------------------------------- config (cockpit.flow.summary, .instruct, .attach)

def test_the_three_blocks_are_off_by_default_and_take_their_keys(tmp_path):
    cfg = load_web_config(tmp_path, {})
    assert cfg.flow["summary"] == {"enabled": False, "budget_per_day": 10, "model": None}
    assert cfg.flow["instruct"] == {"enabled": False, "budget_per_day": 30, "model": None}
    assert cfg.flow["attach"] == {"enabled": False, "max_mb": 10}
    assert cfg.flow == flow_defaults() and cfg.config_warnings == ()
    block = {"summary": {"enabled": True, "budget_per_day": 0, "model": "sonnet"},
             "instruct": {"enabled": True, "budget_per_day": 5, "model": "opus"}, "attach": {"enabled": True, "max_mb": 25}}
    cfg = load_web_config(tmp_path, {"cockpit": {"flow": block}})
    assert {k: cfg.flow[k] for k in block} == block and cfg.config_warnings == ()


@pytest.mark.parametrize("block, value, key", [
    ("summary", {"enabled": "yes"}, "enabled"), ("summary", {"budget_per_day": -1}, "budget_per_day"),
    ("summary", {"model": "gpt"}, "model"), ("summary", {"colour": 1}, "colour"),
    ("instruct", {"budget_per_day": 2.5}, "budget_per_day"), ("instruct", {"model": "haiku-4"}, "model"),
    ("attach", {"max_mb": 0}, "max_mb"), ("attach", {"max_mb": 26}, "max_mb"), ("attach", {"enabled": 1}, "enabled"),
    ("attach", {"model": "haiku"}, "model")])
def test_a_wrong_value_in_a_block_keeps_its_default_and_says_so(tmp_path, block, value, key):
    cfg = load_web_config(tmp_path, {"cockpit": {"flow": {block: value}}})
    assert cfg.flow[block] == flow_defaults()[block]
    assert any(f"cockpit.flow.{block}.{key}" in x for x in cfg.config_warnings), cfg.config_warnings


def test_a_block_that_is_no_mapping_is_off_and_says_so(tmp_path):
    cfg = load_web_config(tmp_path, {"cockpit": {"flow": {"attach": "on"}}})
    assert cfg.flow["attach"] == flow_defaults()["attach"]
    assert cfg.config_warnings and cfg.config_warnings[0].startswith("cockpit.flow.attach:")


def test_the_state_carries_the_budgets_left_and_the_blocks(world):
    state = world.app.state_payload()
    assert state["flow_ai"] == {"summary_left": 3, "instruct_left": 30, "instruct_running": False}
    assert state["work"]["flow"]["summary"]["enabled"] is True and state["work"]["flow"]["attach"]["max_mb"] == 1


# ---------------------------------------------------------------- the feed

def test_the_feed_of_a_task_holds_every_kind_newest_first_with_its_counts(world):
    seed_sources(world)
    data = feed(world)
    rows = data["rows"]
    assert data["ok"] is True and data["key"] == DEMO and data["more"] is False
    assert len({r["id"] for r in rows}) == len(rows)
    order = [(r["at_ms"], -i) for i, r in enumerate(rows)]
    assert order == sorted(order, reverse=True)
    assert set(kinds(data)) == {"note", "log", "doc", "status", "theme", "decision", "created", "agent", "session", "code"}
    counts = data["counts"]
    assert counts["all"] == len(rows)
    for name in ("notes", "docs", "state", "agents", "code"):
        assert counts[name] == sum(1 for r in rows if name in r["filters"]), name
    assert counts == {"all": 23, "notes": 4, "docs": 4, "state": 10, "agents": 4, "code": 5}
    for r in rows:
        assert set(r) == {"id", "at", "at_ms", "kind", "filters", "text", "change", "undone_ms", "by", "links", "doc", "agent"}
        assert isinstance(r["text"], str) and "\n" not in r["text"] and len(r["text"]) <= 300
        assert len(r["links"]) <= 4
        assert r["by"] is None or r["by"]["kind"] in act.BY_KINDS
    # a day without a time reads as the day and sorts as its noon
    note = next(r for r in of(data, "note") if r["text"].startswith("Build plan"))
    assert note["at"] == "2026-10-02" and note["at_ms"] == ms(2026, 10, 2) and note["by"] is None


def test_notes_and_log_rows_are_notes_and_a_log_row_equal_to_a_same_day_note_is_left_out(world):
    data = feed(world)
    assert sorted(r["text"] for r in of(data, "note")) == [
        "Build plan written, see example/repo#40",
        "Review filed https://github.com/example/repo/pull/41 and #43", "started the demo"]
    logs = of(data, "log")
    assert [r["text"] for r in logs] == ["mentions demo-task in passing"]
    assert logs[0]["at"] == "2026-10-09T10:00" and logs[0]["filters"] == ["notes"]


def test_the_return_channels_own_lines_fold_into_one_agent_row_and_attached_notes_into_the_doc(world):
    data = feed(world)
    texts = [r["text"] for r in data["rows"] if r["kind"] in ("note", "log")]
    assert not any(t.startswith(("With AI:", "Result:", "Attached:")) for t in texts)
    [start] = of(data, "agent")
    assert start["at"] == "2026-10-03" and start["filters"] == ["agents", "state"]
    assert start["agent"] == {"mode": "go", "stage": "result", "result": "the draft is in deliverables/plan.md"}
    [offer] = [r for r in of(data, "doc") if r["doc"]["path"] == "deliverables/offer.pdf"]
    assert offer["doc"]["attached"] is True and offer["by"] == {"kind": "you", "name": None}


def test_documents_come_from_git_new_and_changed_at_most_two_rows_per_file(world):
    data = feed(world)
    docs = of(data, "doc")
    by_path = {}
    for r in docs:
        by_path.setdefault(r["doc"]["path"], []).append(r)
    # never a dotfile, a link or a file git names that is gone
    assert sorted(by_path) == ["deliverables/offer.pdf", "deliverables/plan.md", "deliverables/sub/deep.txt"]
    changed, new = by_path["deliverables/plan.md"]
    assert (new["doc"]["state"], new["at_ms"], new["doc"]["changes"]) == ("new", T1, 0)
    assert (changed["doc"]["state"], changed["at_ms"], changed["doc"]["changes"]) == ("changed", T3, 2)
    assert changed["by"] == {"kind": "git", "name": "Test Person"} and changed["text"] == "plan.md"
    assert new["links"] == [{"kind": "doc", "slug": "demo-task", "path": "deliverables/plan.md"}]
    assert new["doc"]["bytes"] == len("content of plan.md\n")
    [deep] = by_path["deliverables/sub/deep.txt"]
    assert deep["doc"]["state"] == "new" and deep["at_ms"] == ms(2026, 10, 7, 8) and deep["by"] is None
    calls = [c for c in world.runner.calls if c[0] == FAKE_GIT]
    assert calls[0] == [FAKE_GIT, "-C", str(world.root), "log", "--no-color", "--no-renames", "--max-count=200",
                        "--format=%x1e%at%x1f%an", "--name-status", "--", "work/tasks/demo-task/deliverables"]


def test_a_quoted_git_path_is_read_and_a_tracked_file_takes_its_times_from_git_alone(world):
    deliv = world.root / "work" / "tasks" / "demo-task" / "deliverables"
    (deliv / "Café menu.md").write_text("v2\n", encoding="utf-8")
    os.utime(deliv / "Café menu.md", (ms(2026, 10, 8, 16) / 1000,) * 2)     # a checkout writes every mtime anew
    world.runner.handlers["git.log"] = git_handler(docs=git_docs(
        (T3, [("M", '"work/tasks/demo-task/deliverables/Caf\\303\\251 menu.md"')]),
        (T2, [("A", '"work/tasks/demo-task/deliverables/Caf\\303\\251 menu.md"')])))
    data = feed(world, fresh="1")
    rows = [r for r in of(data, "doc") if r["doc"]["path"] == "deliverables/Café menu.md"]
    assert [(r["doc"]["state"], r["at_ms"], r["doc"]["changes"]) for r in rows] == [("changed", T3, 1), ("new", T2, 0)]


def test_a_file_git_never_saw_is_changed_when_written_after_it_was_made(world):
    path = put(world, "draft.md", b"v1")
    made = os.stat(path)
    born = getattr(made, "st_birthtime", made.st_mtime)
    os.utime(path, (born + 3600, born + 3600))
    if getattr(os.stat(path), "st_birthtime", None) is None:
        pytest.skip("no birth time on this file system")
    rows = [r for r in of(feed(world, fresh="1"), "doc") if r["doc"]["path"] == "deliverables/draft.md"]
    assert [(r["doc"]["state"], r["doc"]["changes"]) for r in rows] == [("changed", 1), ("new", 0)]


def test_without_git_the_documents_and_status_come_from_the_files(tmp_path):
    w = make_world(tmp_path, git=None)
    try:
        data = feed(w)
        assert not [c for c in w.runner.calls if c and c[0] == FAKE_GIT]
        assert sorted(r["doc"]["path"] for r in of(data, "doc")) == [
            "deliverables/offer.pdf", "deliverables/plan.md", "deliverables/sub/deep.txt"]
        assert of(data, "status") == []
        [created] = of(data, "created")
        assert created["change"] == {"field": "status", "old": None, "new": "review"}
    finally:
        w.close()


def test_a_failed_git_call_leaves_the_file_times(world):
    world.runner.handlers["git.log"] = lambda argv: fail("fatal: not a git repository")
    data = feed(world)
    assert len(of(data, "doc")) == 3 and of(data, "status") == []


def test_status_rows_from_git_and_the_working_tree_and_the_created_row(world):
    data = feed(world)
    status = of(data, "status")
    assert [(r["change"], r["at_ms"]) for r in status] == [
        ({"field": "status", "old": "doing", "new": "review"}, ms(2026, 10, 8, 15)),
        ({"field": "status", "old": "backlog", "new": "doing"}, S2)]
    assert status[0]["by"] is None and status[1]["by"] == {"kind": "git", "name": "Test Person"}
    [created] = of(data, "created")
    assert created["at"] == "2026-10-01" and created["change"] == {"field": "status", "old": None, "new": "backlog"}
    calls = [c for c in world.runner.calls if c[0] == FAKE_GIT]
    assert calls[1] == [FAKE_GIT, "-C", str(world.root), "log", "--no-color", "--max-count=100", "--format=%x1e%at%x1f%an",
                        "-G^status:", "-p", "-U0", "--", "work/tasks/demo-task/STATUS.md"]


def test_code_references_once_at_their_first_day(world):
    data = feed(world)
    code = {r["text"]: r for r in of(data, "code")}
    assert sorted(code) == ["example/repo#12", "example/repo#34", "example/repo#40", "example/repo#41", "example/repo#43"]
    assert code["example/repo#40"]["at"] == "2026-10-02"
    assert code["example/repo#41"]["links"] == [{"kind": "web", "href": "https://github.com/example/repo/pull/41"}]
    assert code["example/repo#43"]["links"] == [{"kind": "web", "href": "https://github.com/example/repo/issues/43"}]
    # the sync block's refs, named nowhere, stand at the day the task was made
    assert code["example/repo#34"]["at"] == "2026-10-01"
    assert code["example/repo#34"]["links"][0]["href"] == "https://github.com/example/repo/pull/34"


def test_code_rows_leave_out_the_rows_own_source_and_a_bare_number_needs_one_repo():
    texts = [("2026-10-02", None, "see https://github.com/example/repo/issues/12 and #5 and board #18"),
             ("2026-10-03", None, "commit https://github.com/example/repo/commit/0123456789abcdef in other/repo#2")]
    refs = act.code_refs(texts, {}, ["example/repo"], url="https://github.com/example/repo/issues/12", ref=None)
    assert [r["text"] for r in refs] == ["example/repo#5", "example/repo@0123456", "other/repo#2"]
    refs = act.code_refs(texts, {}, ["example/repo", "example/other"], url=None, ref="other/repo#2")
    assert [r["text"] for r in refs] == ["example/repo#12", "example/repo@0123456"]
    # a reference stands at the earliest text that names it, whichever source comes first in the list
    refs = act.code_refs([("2026-10-05", None, "see other/repo#9"), ("2026-10-03", ms(2026, 10, 3, 9), "other/repo#9 too")],
                         {}, [])
    assert refs == [{"text": "other/repo#9", "href": "https://github.com/other/repo/issues/9", "day": "2026-10-03",
                     "at_ms": ms(2026, 10, 3, 9)}]


def test_decisions_theme_moves_agents_and_sessions(world):
    seed_sources(world)
    data = feed(world)
    [decision] = of(data, "decision")
    assert decision["change"] == {"field": "decision", "old": None, "new": "later", "until": TOMORROW}
    assert decision["by"] == {"kind": "suggestion", "name": None} and decision["undone_ms"] is None
    themes = of(data, "theme")
    assert [r["change"] for r in themes] == [{"field": "theme", "old": "Docs", "new": "Release"},
                                            {"field": "theme", "old": None, "new": "Docs"}]
    assert [r["by"]["kind"] for r in themes] == ["you", "themes"]
    launch = next(r for r in of(data, "agent") if r["at_ms"] == int(NOW))
    assert launch["agent"]["mode"] == "go" and launch["agent"]["stage"] == "asks"
    assert launch["change"] == {"field": "driver", "old": None, "new": "demo-task"}
    assert launch["links"] == [{"kind": "tab", "ref": "surface:7"}] and launch["by"] == {"kind": "instruction", "name": None}
    run = next(r for r in of(data, "agent") if r["agent"]["mode"] == "workflow")
    assert run["text"] == "demo review" and run["agent"]["result"] == "Reviewed the plan"
    [session] = of(data, "session")
    assert session["text"] == "Demo session" and session["filters"] == ["agents", "state"]
    assert session["change"] == {"field": "driver", "old": None, "new": "Demo session"}
    # taken back, the decision says so on its one row
    world.act("unhide", key=DEMO)
    [decision] = of(feed(world, fresh="1"), "decision")
    assert decision["undone_ms"] == int(NOW)


def test_the_facts_created_moved_and_jev(world):
    seed_sources(world)
    data = feed(world)
    assert data["facts"]["created"] == "2026-10-01" and data["facts"]["moved"] == "2026-10-09T12:00"
    assert data["facts"]["jev"] == {"quadrant": "plan", "rank": 4, "urgency": 0.67, "impact": 1.0, "effort": 0.33,
                                    "only_me": 0.8, "at_ms": int(NOW) - 3600_000}
    # an order older than rank_max_age_days stands for nothing
    world.clock.advance(8 * 24 * 3600)
    assert feed(world, fresh="1")["facts"]["jev"] is None


def test_an_inbox_rows_feed_its_events_and_the_documents_of_the_task_it_names(world):
    events = world.root / "work" / "inbox" / ONLY_ID / "events"
    events.mkdir(parents=True)
    (world.root / "work" / "inbox" / ONLY_ID / "item.yaml").write_text(
        "summary: Review the demo report\ncreated: '2026-10-09T09:00'\ntask: demo-task\n", encoding="utf-8")
    (events / "20261009T071000Z-00-web-note.yaml").write_text("verb: note\nby: web\ntext: Asked the vendor\n", encoding="utf-8")
    (events / "20261009T072000Z-01-web-defer.yaml").write_text("verb: defer\nby: web\nuntil: '2026-10-12'\n", encoding="utf-8")
    (events / "20261009T073000Z-02-runner-reopen.yaml").write_text("verb: reopen\nby: runner\n", encoding="utf-8")
    data = feed(world, key=ONLY)
    assert [r["text"] for r in of(data, "note")] == ["Asked the vendor"]
    assert of(data, "note")[0]["by"] == {"kind": "you", "name": None}
    assert [r["change"] for r in of(data, "status")] == [{"field": "status", "old": "deferred", "new": "open"},
                                                        {"field": "status", "old": "open", "new": "deferred"}]
    assert of(data, "status")[0]["by"] == {"kind": "bridge", "name": "runner"}
    [created] = of(data, "created")
    assert created["at"] == "2026-10-09T09:00" and created["change"]["new"] == "open"
    assert sorted(r["doc"]["path"] for r in of(data, "doc")) == [
        "deliverables/offer.pdf", "deliverables/plan.md", "deliverables/plan.md", "deliverables/sub/deep.txt"]
    # what the task attached says so here too, while none of the task's notes stands in the inbox row's feed
    assert next(r for r in of(data, "doc") if r["doc"]["path"] == "deliverables/offer.pdf")["doc"]["attached"] is True
    assert not of(data, "log") and of(data, "code") == []
    assert data["can"]["attach"] is True


def test_a_row_with_nothing_has_an_empty_feed(world):
    data = feed(world, key=VENDOR)
    assert data["rows"] == [] and data["counts"]["all"] == 0
    assert data["can"] == {"note": True, "attach": False, "summary": False} and data["summary"] is None


def test_the_feed_is_cut_at_200_rows_and_counts_before_the_cut(world):
    task = world.root / "work" / "tasks" / "demo-task" / "STATUS.md"
    task.write_text(STATUS_MD + "".join(f"- 2026-09-{1 + i % 28:02d}: note {i}\n" for i in range(230)), encoding="utf-8")
    data = feed(world)
    assert len(data["rows"]) == 200 and data["more"] is True and data["counts"]["all"] > 230
    assert data["counts"]["notes"] > 200


def test_the_feed_is_kept_for_20_seconds_and_a_write_or_fresh_reads_again(world):
    first = feed(world)
    task = world.root / "work" / "tasks" / "demo-task" / "STATUS.md"
    task.write_text(task.read_text(encoding="utf-8") + "- 2026-10-09: one more\n", encoding="utf-8")
    world.clock.advance(10)
    assert feed(world) == first
    assert "one more" in [r["text"] for r in of(feed(world, fresh="1"), "note")]
    task.write_text(task.read_text(encoding="utf-8") + "- 2026-10-09: and another\n", encoding="utf-8")
    world.clock.advance(25)
    assert "and another" in [r["text"] for r in of(feed(world), "note")]
    # a verb that names the key drops what was kept
    task.write_text(task.read_text(encoding="utf-8") + "- 2026-10-09: after a note\n", encoding="utf-8")
    world.act("note", key=DEMO, text="a sentence")
    assert "after a note" in [r["text"] for r in of(feed(world), "note")]
    # a plan of the instruction line changes nothing, so it keeps the feed
    task.write_text(task.read_text(encoding="utf-8") + "- 2026-10-09: after a plan\n", encoding="utf-8")
    world.app.cfg.flow["instruct"]["enabled"] = True
    world.runner.handlers["claude.p"] = lambda argv: ok({"type": "result", "is_error": False, "result": "",
                                                         "structured_output": {"steps": [], "unclear": None}})
    world.act("flow_instruct", text="nothing", keys=[DEMO], point=True)
    assert "after a plan" not in [r["text"] for r in of(feed(world), "note")]


def test_the_feed_refuses_a_bad_key_a_gone_row_and_answers_flow_off(world, tmp_path):
    status, _h, body = get(world, "/api/flow/activity", key="nope")
    assert status == 400 and json.loads(body)["error"]["field"] == "key"
    status, _h, body = get(world, "/api/flow/activity", key="task:no-such-task")
    assert status == 409 and json.loads(body)["error"]["code"] == "stale_row"
    off = make_world(tmp_path / "off", flow="false")
    try:
        status, _h, body = get(off, "/api/flow/activity", key=DEMO)
        assert status == 409 and json.loads(body)["error"]["code"] == "flow_off"
        assert "flow_ai" in off.app.state_payload()
    finally:
        off.close()


def test_the_feed_is_scrubbed(world):
    task = world.root / "work" / "tasks" / "demo-task" / "STATUS.md"
    task.write_text(STATUS_MD + f"- 2026-10-09: the key {world.app.token} leaked\n", encoding="utf-8")
    body = get(world, "/api/flow/activity", key=DEMO)[2].decode("utf-8")
    assert world.app.token not in body and "[token]" in body


# ---------------------------------------------------------------- git, two exact shapes

def test_the_runner_lets_the_two_git_shapes_through_and_nothing_else(tmp_path):
    runner = Runner(tmp_path, cmux=None, claude=None, codex=None, git=FAKE_GIT)
    root = str(runner.root)
    docs = act.docs_argv(FAKE_GIT, root, "work/tasks/demo-task")
    status = act.status_argv(FAKE_GIT, root, "work/streams/demo-task")
    runner.check(docs)
    runner.check(status)
    bad = [act.docs_argv(FAKE_GIT, root, "work/done/2026-10/demo-task"), act.docs_argv(FAKE_GIT, "/elsewhere", "work/tasks/x"),
           act.docs_argv(FAKE_GIT, root, "work/tasks/../x"), [*docs[:4], "-p", *docs[4:]], [FAKE_GIT, "status"],
           ["/usr/bin/git", *docs[1:]], [*status[:-1], "work/tasks/demo-task/other.md"], docs[:-1]]
    for argv in bad:
        assert not act.git_argv_ok(argv, FAKE_GIT, root), argv
        with pytest.raises(RunnerRefused):
            runner.check(argv)
    assert not act.git_argv_ok(docs, None, root)


# ---------------------------------------------------------------- documents, served by type

def put(w, rel, data=b"x"):
    path = w.root / "work" / "tasks" / "demo-task" / "deliverables" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


@pytest.mark.parametrize("name, ctype, csp", [
    ("page.html", "text/html; charset=utf-8", "sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; "
     "style-src 'unsafe-inline'; img-src data:; font-src data:; connect-src 'none'; form-action 'none'; base-uri 'none'; "
     "frame-ancestors 'none'"),
    ("paper.pdf", "application/pdf", "default-src 'none'; object-src 'self'; frame-ancestors 'none'"),
    ("pic.PNG", "image/png", "sandbox; default-src 'none'; img-src 'self'; style-src 'unsafe-inline'"),
    ("pic.svg", "image/svg+xml", "sandbox; default-src 'none'; img-src 'self'; style-src 'unsafe-inline'"),
    ("notes.md", "text/plain; charset=utf-8", "sandbox; default-src 'none'"),
    ("data.yaml", "text/plain; charset=utf-8", "sandbox; default-src 'none'"),
    ("blob.bin", "application/octet-stream", "sandbox; default-src 'none'")])
def test_a_document_is_served_with_a_policy_for_its_type(world, name, ctype, csp):
    put(world, f"sub/{name}", b"<b>hello</b>")
    status, headers, body = get(world, "/api/flow/doc", slug="demo-task", path=f"deliverables/sub/{name}")
    assert status == 200 and body == b"<b>hello</b>"
    assert headers["Content-Type"] == ctype and headers["Content-Security-Policy"] == csp
    assert headers["X-Content-Type-Options"] == "nosniff" and headers["Cache-Control"] == "no-store"
    assert headers["Referrer-Policy"] == "no-referrer" and headers["X-Frame-Options"] == "DENY"
    assert headers["Content-Length"] == str(len(body))
    if ctype == "application/octet-stream":
        assert headers["Content-Disposition"] == f"attachment; filename*=UTF-8''{name}"
    else:
        assert "Content-Disposition" not in headers


def test_a_download_name_is_percent_encoded(world):
    put(world, "Offer v2 é.zip")
    status, headers, _b = get(world, "/api/flow/doc", slug="demo-task", path="deliverables/Offer v2 é.zip")
    assert status == 200 and headers["Content-Disposition"] == "attachment; filename*=UTF-8''Offer%20v2%20%C3%A9.zip"


@pytest.mark.parametrize("slug, path, status", [
    ("demo-task", "deliverables/../STATUS.md", 400), ("demo-task", "STATUS.md", 400), ("demo-task", "deliverables/", 400),
    ("demo-task", "deliverables//etc/passwd", 400), ("demo-task", "deliverables/a\\b.md", 400),
    ("demo-task", "deliverables/.hidden", 400), ("Demo", "deliverables/plan.md", 400),
    ("demo-task", "deliverables/missing.md", 404), ("demo-task", "deliverables/sub", 404),
    ("demo-task", "deliverables/link.md", 404), ("no-such-task", "deliverables/plan.md", 404)])
def test_a_document_path_that_leaves_the_folder_or_is_no_file_is_refused(world, slug, path, status):
    got, _h, body = get(world, "/api/flow/doc", slug=slug, path=path)
    assert got == status, body


def test_a_symlinked_folder_on_the_way_is_refused(world, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("secret", encoding="utf-8")
    deliv = world.root / "work" / "tasks" / "demo-task" / "deliverables"
    (deliv / "jump").symlink_to(outside)
    assert get(world, "/api/flow/doc", slug="demo-task", path="deliverables/jump/secret.md")[0] == 404
    other = world.root / "work" / "tasks" / "other-task"
    other.mkdir()
    (other / "STATUS.md").write_text("---\nstatus: doing\n---\n# Other\n", encoding="utf-8")
    (other / "deliverables").symlink_to(outside)
    assert get(world, "/api/flow/doc", slug="other-task", path="deliverables/secret.md")[0] == 404


def test_the_document_route_answers_flow_off(tmp_path):
    w = make_world(tmp_path, flow="false")
    try:
        status, _h, body = get(w, "/api/flow/doc", slug="demo-task", path="deliverables/plan.md")
        assert status == 409 and json.loads(body)["error"]["code"] == "flow_off"
    finally:
        w.close()


def test_the_document_route_needs_the_session(world):
    status, _h, _b = world.request("GET", "/api/flow/doc?slug=demo-task&path=deliverables/plan.md")
    assert status == 401


# ---------------------------------------------------------------- attach a document

def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def attach(w, key=DEMO, name="notes.txt", data=b"hi", **extra):
    status, _h, body = w.post("/api/flow/attach", {"key": key, "name": name, "data": b64(data), **extra})
    return status, json.loads(body)


def post_length(w, path, length):
    """A POST that declares a body of `length` and never sends it: what the server answers before it reads one"""
    conn = http.client.HTTPConnection("127.0.0.1", w.port, timeout=5)
    conn.putrequest("POST", path, skip_host=True, skip_accept_encoding=True)
    for name, value in {"Host": f"127.0.0.1:{w.port}", **w.cookie, "X-Bridge-Token": w.app.csrf,
                        "Origin": f"http://127.0.0.1:{w.port}", "Content-Type": "application/json",
                        "Content-Length": str(length)}.items():
        conn.putheader(name, value)
    conn.endheaders()
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    return resp.status, json.loads(body)


def deliverables(w, slug="demo-task"):
    return w.root / "work" / "tasks" / slug / "deliverables"


def test_a_document_is_attached_flat_into_the_tasks_deliverables_with_a_note(world):
    status, res = attach(world, name="Offer v2.pdf", data=b"%PDF-1.4 demo")
    assert status == 200, res
    path = deliverables(world) / "Offer v2.pdf"
    assert path.read_bytes() == b"%PDF-1.4 demo" and (path.stat().st_mode & 0o777) == 0o644
    assert res["ok"] is True and res["verb"] == "flow_attach"
    a = res["attach"]
    assert (a["path"], a["name"], a["bytes"]) == ("deliverables/Offer v2.pdf", "Offer v2.pdf", 13)
    row = a["row"]
    assert row["kind"] == "doc" and row["doc"]["path"] == "deliverables/Offer v2.pdf" and row["doc"]["attached"] is True
    assert row["doc"]["state"] == "new" and row["by"] == {"kind": "you", "name": None}
    assert row["links"] == [{"kind": "doc", "slug": "demo-task", "path": "deliverables/Offer v2.pdf"}]
    notes = world.runner.of("task.note")
    assert notes[-1][-4:] == ["note", "demo-task", "--", "Attached: deliverables/Offer v2.pdf"]
    audit = (world.state / "audit.log").read_text(encoding="utf-8").splitlines()[-1]
    assert " flow_attach task:demo-task " in audit and "bytes=13" in audit and "Offer" not in audit


def test_the_note_of_an_attach_folds_into_its_document_row(world):
    attach(world, name="notes.txt")
    task = world.root / "work" / "tasks" / "demo-task" / "STATUS.md"
    task.write_text(task.read_text(encoding="utf-8") + "- 2026-10-09: Attached: deliverables/notes.txt\n", encoding="utf-8")
    data = feed(world, fresh="1")
    [row] = [r for r in of(data, "doc") if r["doc"]["path"] == "deliverables/notes.txt"]
    assert row["doc"]["attached"] is True and row["by"]["kind"] == "you"
    assert not any("Attached" in r["text"] for r in of(data, "note"))


@pytest.mark.parametrize("given, made", [
    ("../../etc/passwd", "passwd"), ("C:\\Users\\x\\Offer v2.pdf", "Offer v2.pdf"), ("  .hidden  ", "hidden"),
    ("a\x00b\nc.txt", "abc.txt"), ("Invoice<1>|?.pdf", "Invoice_1_.pdf"), ("Cre\u0300me bru\u0302le\u0301e.md", "Crème brûlée.md"),
    ("\u202eexe.pdf", "exe.pdf"), ("a   b__c.txt", "a b_c.txt"), ("-rf .txt", "rf .txt"), ("x.tar.gz", "x.tar.gz"),
    ("ok (1) +a,b=c@d.md", "ok (1) +a,b=c@d.md"), ("...", ""), ("/", ""), ("_-_", "")])
def test_the_name_of_an_attachment_is_made_safe(given, made):
    assert act.safe_name(given) == made


def test_a_long_name_keeps_its_extension_and_120_characters():
    made = act.safe_name("x" * 200 + ".pdf")
    assert len(made) == 120 and made.endswith("x.pdf")
    made = act.safe_name("y" * 200 + "." + "e" * 20)
    assert len(made) == 120 and made == "y" * 120


def test_a_taken_name_gets_a_number_then_is_refused(world):
    deliv = deliverables(world)
    (deliv / "Notes.TXT").write_text("old", encoding="utf-8")
    status, res = attach(world, name="notes.txt")
    assert status == 200 and res["attach"]["name"] == "notes-2.txt"
    for i in range(3, 100):
        (deliv / f"notes-{i}.txt").write_text("x", encoding="utf-8")
    status, res = attach(world, name="notes.txt")
    assert status == 409 and res["error"]["code"] == "attach_exists"
    assert (deliv / "Notes.TXT").read_text(encoding="utf-8") == "old"


@pytest.mark.parametrize("data, code, status", [
    ("", "invalid_argument", 400), ("aGk", "invalid_argument", 400), ("aG k=", "invalid_argument", 400),
    ("@@@@", "invalid_argument", 400), (7, "invalid_argument", 400)])
def test_the_data_must_be_strict_base64_of_one_byte_or_more(world, data, code, status):
    got, _h, body = world.post("/api/flow/attach", {"key": DEMO, "name": "a.txt", "data": data})
    res = json.loads(body)
    assert got == status and res["error"]["code"] == code and res["error"]["field"] == "data"
    assert not (deliverables(world) / "a.txt").exists()


def test_more_than_max_mb_is_refused_and_a_bigger_body_never_read(world):
    status, res = attach(world, data=b"x" * (1024 * 1024 + 1))
    assert status == 413 and res["error"]["code"] == "attach_too_big"
    status, res = attach(world, data=b"x" * (1024 * 1024))
    assert status == 200
    cap = math.ceil(1 * 2 ** 20 / 3) * 4 + 4096
    assert act.attach_body_cap(1) == cap
    status, res = post_length(world, "/api/flow/attach", cap + 1)
    assert status == 413 and res["error"]["code"] == "payload_too_large"
    # every other path keeps 64 KB
    status, res = post_length(world, "/api/action", 64 * 1024 + 1)
    assert status == 413 and res["error"]["code"] == "payload_too_large"


def test_attach_off_and_flow_off_answer_before_the_body_is_read(tmp_path):
    for flow, attach_on, code in (("true", "false", "attach_off"), ("false", "true", "flow_off")):
        w = make_world(tmp_path / code, flow=flow, attach=attach_on)
        try:
            status, res = post_length(w, "/api/flow/attach", 2_000_000)
            assert status == 409 and res["error"]["code"] == code
            with pytest.raises(ActionError) as e:
                w.act("flow_attach", key=DEMO, name="a.txt", data=b64(b"hi"))
            assert e.value.code == code
            assert not (deliverables(w) / "a.txt").exists() and not (deliverables(w) / "big.txt").exists()
        finally:
            w.close()


def test_a_row_without_an_open_task_takes_no_document_and_an_inbox_row_attaches_to_its_task(world):
    for key in (ISSUE, YES):
        status, res = attach(world, key=key)
        assert status == 409 and res["error"]["code"] == "attach_no_task", key
    status, res = attach(world, key=ONLY, name="from the inbox.txt")
    assert status == 200 and (deliverables(world) / "from the inbox.txt").is_file()
    assert world.runner.of("task.note")[-1][-3] == "demo-task"
    assert feed(world, key=ONLY, fresh="1")["can"]["attach"] is True
    assert feed(world, key=ISSUE)["can"]["attach"] is False


def test_a_symlinked_deliverables_folder_or_task_folder_is_not_written(world, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    other = world.root / "work" / "tasks" / "other-task"
    other.mkdir()
    (other / "STATUS.md").write_text("---\nstatus: doing\n---\n# Other\n", encoding="utf-8")
    (other / "deliverables").symlink_to(outside)
    status, res = attach(world, key="task:other-task")
    assert status == 409 and res["error"]["code"] == "not_applicable"
    assert list(outside.iterdir()) == []


def test_attach_makes_the_folder_and_refuses_an_unknown_field_or_a_gone_row(world):
    other = world.root / "work" / "tasks" / "other-task"
    other.mkdir()
    (other / "STATUS.md").write_text("---\nstatus: doing\n---\n# Other\n", encoding="utf-8")
    status, res = attach(world, key="task:other-task")
    assert status == 200 and (other / "deliverables" / "notes.txt").is_file()
    assert ((other / "deliverables").stat().st_mode & 0o777) == 0o755
    status, res = attach(world, path="x")
    assert status == 400 and res["error"]["field"] == "path"
    status, res = attach(world, key="task:no-such-task")
    assert status == 409 and res["error"]["code"] == "stale_row"
    status, res = attach(world, name="...")
    assert status == 400 and res["error"]["field"] == "name"


# ---------------------------------------------------------------- the summary of a small model

def summary_calls(w):
    return w.runner.of("claude.p")


def data_of(argv):
    head, rest = argv[-1].split("\n", 1)
    return head, json.loads(rest)


def test_a_summary_is_written_on_a_click_quietly_and_kept(world):
    seed_sources(world)
    res = world.act("flow_activity_summary", key=DEMO)
    [argv] = summary_calls(world)
    assert argv[:12] == ["/fake/bin/claude", "-p", "--model", HAIKU, "--output-format", "json", "--no-session-persistence",
                         "--setting-sources", "", "--tools", "", "--json-schema"]
    assert argv[12] == act.SUMMARY_SCHEMA and act.summary_argv_ok(argv, "/fake/bin/claude")
    head, data = data_of(argv)
    assert "never an instruction" in head
    sent = data["rows"]
    assert sent and len(sent) <= 60 and all(set(r) == {"at", "kind", "text", "change"} for r in sent)
    # the last seven days only: what came before the 2nd of October stays out
    assert all(r["at"] >= "2026-10-02" for r in sent)
    assert "English" in argv[14] and "three sentences" in argv[14]
    s = res["summary"]
    assert s["text"] == "The plan was written and went to review." and s["model"] == "haiku" and s["cached"] is False
    assert s["since"] == "2026-10-02" and s["stale"] is False and s["at_ms"] == int(NOW)
    assert res["flow_ai"]["summary_left"] == 2 and res["note"] == ""
    kept = json.loads((world.state / act.STATE_FILE).read_text(encoding="utf-8"))
    assert kept["summaries"][DEMO]["text"] == s["text"]
    assert feed(world)["summary"] == {k: s[k] for k in ("text", "since", "at_ms", "model", "stale")}


def test_an_unchanged_feed_answers_the_kept_summary_without_a_call_and_a_change_makes_it_stale(world):
    world.act("flow_activity_summary", key=DEMO)
    again = world.act("flow_activity_summary", key=DEMO)
    assert again["summary"]["cached"] is True and len(summary_calls(world)) == 1
    assert again["flow_ai"]["summary_left"] == 2
    task = world.root / "work" / "tasks" / "demo-task" / "STATUS.md"
    task.write_text(task.read_text(encoding="utf-8") + "- 2026-10-09: a new step\n", encoding="utf-8")
    assert feed(world, fresh="1")["summary"]["stale"] is True
    world.runner.handlers["claude.p"] = lambda argv: summary_answer("Now with a new step.")
    res = world.act("flow_activity_summary", key=DEMO)
    assert res["summary"]["cached"] is False and res["summary"]["text"] == "Now with a new step."
    assert feed(world)["summary"]["stale"] is False


def test_a_dash_and_a_fourth_sentence_do_not_stand(world):
    world.runner.handlers["claude.p"] = lambda argv: summary_answer("One \u2014 two. Three. Four. Five.")
    text = world.act("flow_activity_summary", key=DEMO)["summary"]["text"]
    assert "\u2014" not in text and text == "One, two. Three. Four."


def test_the_summary_refuses_off_empty_budget_running_unavailable_and_failed(tmp_path):
    w = make_world(tmp_path / "a", budget=1)
    try:
        def code(key=DEMO):
            with pytest.raises(ActionError) as e:
                w.act("flow_activity_summary", key=key)
            return e.value.status, e.value.code
        assert code(VENDOR) == (409, "summary_empty")
        assert code("task:no-such-task") == (409, "stale_row")
        w.app.activity.summary_running = True
        assert code() == (409, "summary_running")
        w.app.activity.summary_running = False
        w.runner.handlers["claude.p"] = lambda argv: fail("model down")
        assert code() == (502, "summary_failed")
        assert w.app.state_payload()["flow_ai"]["summary_left"] == 0
        assert code() == (429, "summary_budget")
        assert len(summary_calls(w)) == 1
        w.runner.claude = None
        assert code() == (503, "summary_unavailable")
    finally:
        w.close()
    w = make_world(tmp_path / "b", summary="false")
    try:
        with pytest.raises(ActionError) as e:
            w.act("flow_activity_summary", key=DEMO)
        assert e.value.code == "summary_off"
    finally:
        w.close()
    w = make_world(tmp_path / "c", flow="false")
    try:
        with pytest.raises(ActionError) as e:
            w.act("flow_activity_summary", key=DEMO)
        assert e.value.code == "flow_off"
    finally:
        w.close()


def test_the_summary_model_comes_from_the_block_else_the_service(world):
    folder = world.root / "workflow" / "ai-services"
    folder.mkdir(parents=True)
    service = folder / "cockpit-activity.yaml"
    service.write_text("schema_version: 1\nscope: user\nid: cockpit-activity\nprovider: claude\nmodels:\n  claude: sonnet\n",
                       encoding="utf-8")
    world.runner.handlers["claude.p"] = lambda argv: summary_answer("Sonnet wrote it.", used="claude-sonnet-5-5")
    assert world.act("flow_activity_summary", key=DEMO)["summary"]["model"] == "sonnet"
    assert summary_calls(world)[-1][3] == "claude-sonnet-5-5"
    task = world.root / "work" / "tasks" / "demo-task" / "STATUS.md"
    task.write_text(task.read_text(encoding="utf-8") + "- 2026-10-09: one more line\n", encoding="utf-8")
    world.app.cfg.flow["summary"]["model"] = "opus"
    world.act("flow_activity_summary", key=DEMO)
    assert summary_calls(world)[-1][3] == "claude-opus-5-5"
    world.app.cfg.flow["summary"]["model"] = None
    task.write_text(task.read_text(encoding="utf-8") + "- 2026-10-09: and one more\n", encoding="utf-8")
    service.write_text("schema_version: 1\nscope: user\nid: cockpit-activity\nprovider: codex\n", encoding="utf-8")
    with pytest.raises(ActionError) as e:
        world.act("flow_activity_summary", key=DEMO)
    assert (e.value.status, e.value.code) == (503, "summary_unavailable")


def test_the_summary_argv_is_one_exact_shape(tmp_path):
    runner = Runner(tmp_path, cmux=None, claude="/fake/bin/claude", codex=None, git=None)
    argv = act.summary_argv("/fake/bin/claude", HAIKU, "Summarize.", "data")
    runner.check(argv)
    for change in (lambda a: a.__setitem__(3, "haiku"), lambda a: a.__setitem__(10, "Read"),
                   lambda a: a.__setitem__(12, "{}"), lambda a: a.insert(6, "--verbose"),
                   lambda a: a.__setitem__(16, "x" * 16001)):
        bad = act.summary_argv("/fake/bin/claude", HAIKU, "Summarize.", "data")
        change(bad)
        assert not act.summary_argv_ok(bad, "/fake/bin/claude")
        with pytest.raises(RunnerRefused):
            runner.check(bad)
