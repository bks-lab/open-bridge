# SPDX-License-Identifier: MIT
"""Contract for the way the origin of a work row and its task or stream reach the page: the briefing keeps the
inbox item's `from` and the section a row came from, the cockpit model classifies both (origin.py) and every
row, hidden row, task row and page item goes out with `origin`, `work_kind` and `about_kind`. Nothing new goes to
Jev. docs/bridge-cockpit.md "Where a row comes from".

Run: pytest -q scripts/tests/test_bridge_cockpit_origin_flow.py
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_bridge_cockpit import TASKS, World, collect_fixture, ok, private_key_dir  # noqa: E402,F401
from lib import briefing_view as bv  # noqa: E402
from lib.bridge_cockpit import actions as ac  # noqa: E402,F401
from lib.bridge_cockpit import daybook, details, jev  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
if "briefing" in sys.modules:
    bf = sys.modules["briefing"]
else:
    spec = importlib.util.spec_from_file_location("briefing", ROOT / "scripts" / "briefing.py")
    bf = importlib.util.module_from_spec(spec)
    sys.modules["briefing"] = bf
    spec.loader.exec_module(bf)


def add_item(root: Path, source: str, summary: str, *extra: str) -> str:
    run = subprocess.run([sys.executable, str(ROOT / "scripts" / "inbox.py"), "--root", str(root), "--by", "test", "add",
                          "--from", source, "--kind", "finding", "--summary", summary, *extra],
                         capture_output=True, text=True, timeout=60, check=True)
    return run.stdout.strip().splitlines()[-1]


# ---------------------------------------------------------------- briefing.py and briefing_view.py

def test_every_inbox_builder_keeps_who_filed_the_item(tmp_path):
    root = tmp_path / "b"
    (root / "work" / "inbox").mkdir(parents=True)
    add_item(root, "homebox/issue-radar", "open one", "--key", "a")
    later = add_item(root, "claude", "put off", "--key", "b")
    runs = add_item(root, "tab:docs", "runs on", "--key", "c")
    soon = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    for argv in (["defer", later, "--until", soon], ["defer", runs, "--until", soon, "--on", "a person"]):
        subprocess.run([sys.executable, str(ROOT / "scripts" / "inbox.py"), "--root", str(root), "--by", "t", *argv],
                       capture_output=True, text=True, timeout=60, check=True)
    ctx = bf.Context(root, cfg={})
    got = {i["title"]: i["from"] for i in bf.sec_inbox({"kind": "inbox"}, ctx)}
    assert got == {"open one": "homebox/issue-radar"}
    got = {i["title"]: i["from"] for i in bf.sec_inbox({"kind": "inbox", "deferred": "runs"}, ctx)}
    assert got == {"runs on": "tab:docs"}
    got = {i["title"]: i["from"] for i in bf.sec_inbox({"kind": "inbox", "deferred": "all"}, ctx)}
    assert got == {"open one": "homebox/issue-radar", "put off": "claude", "runs on": "tab:docs"}


def link(tmp_path, monkeypatch, tasks):
    real = bf._load_module

    class Scan:
        @staticmethod
        def scan_status_tasks(root):
            return tasks

    monkeypatch.setattr(bf, "_load_module", lambda name, path: Scan if name == "tracker_sync" else real(name, path))
    root = tmp_path / "b"
    (root / "work" / "inbox").mkdir(parents=True, exist_ok=True)
    items = [{"id": "acme/web#5", "title": "x", "state": "open"}]
    bf.link_local(items, bf.Context(root, cfg={}))
    return items[0]


def test_a_tracker_row_names_the_stream_that_syncs_it_and_a_closed_place_is_no_stream(tmp_path, monkeypatch):
    row = link(tmp_path, monkeypatch, [{"slug": "team-onboarding", "status": "doing", "path": "work/streams/team-onboarding/STATUS.md",
                                        "issues": ["acme/web#5"]}])
    assert row["linked_task"]["stream"] is True and "task" not in row
    assert row["about_task"] == "team-onboarding" and row["about_kind"] == "stream"
    row = link(tmp_path, monkeypatch, [{"slug": "docs-refresh", "status": "doing", "path": "work/tasks/docs-refresh/STATUS.md",
                                        "issues": ["acme/web#5"]}])
    assert row["task"] == "docs-refresh" and row["about_task"] == "docs-refresh" and row["about_kind"] == "task"
    row = link(tmp_path, monkeypatch, [{"slug": "gone", "status": "doing", "path": "work/done/2026-09/gone/STATUS.md",
                                        "issues": ["acme/web#5"]}])
    assert row["linked_task"]["stream"] is False


def result(*sections):
    return {"collected_at": "2026-10-09T09:00", "sections": list(sections)}


def test_a_view_row_carries_the_from_and_the_section_and_a_merged_row_keeps_both(tmp_path):
    inbox = {"id": "inbox", "kind": "inbox", "status": "ok", "items": [
        {"id": "20261009-0900-a-ab12", "title": "Fix it", "state": "open", "urgency": "later", "kind": "decision",
         "gate": "free", "key": "briefing:p:gh:acme/web#4", "from": "bridge-cockpit", "changed_at": "2026-10-09T09:00"},
        {"id": "20261009-0901-b-ab13", "title": "Radar", "state": "open", "urgency": "later", "kind": "finding",
         "gate": "free", "key": "issue-radar:untasked:acme/web#9", "from": "homebox/issue-radar"}]}
    gh = {"id": "gh", "kind": "tracker", "provider": "github-board", "status": "ok", "items": [
        {"id": "acme/web#4", "title": "Fix it", "state": "open", "url": "https://github.com/acme/web/issues/4",
         "linked_task": {"slug": "team-onboarding", "stream": True}, "about_task": "team-onboarding", "about_kind": "stream"}]}
    built = bv.build(result(inbox, gh), {"id": "p", "sections": [{"kind": "inbox", "id": "inbox"},
                                                                 {"kind": "tracker", "id": "gh", "provider": "github-board"}]})
    rows = {r["title"]: r for b in built["buckets"] for r in b["items"]}
    fix = rows["Fix it"]
    assert fix["origin_raw"] == "bridge-cockpit" and fix["inbox_kind"] == "decision"
    assert fix["ref"] == "acme/web#4" and fix["url"] == "https://github.com/acme/web/issues/4"
    assert fix["origin_provider"] == "github-board" and fix["about_task"] == "team-onboarding" and fix["about_kind"] == "stream"
    assert rows["Radar"]["origin_raw"] == "homebox/issue-radar" and rows["Radar"]["origin_section_kind"] == "inbox"


def test_a_page_row_carries_its_source_text_and_its_section():
    sec = {"id": "inbox", "kind": "inbox", "status": "ok", "items": [
        {"id": "20261009-0900-a-ab12", "title": "x", "state": "open", "kind": "finding", "gate": "free", "from": "claude"}]}
    pages = bv.pages(result(sec), {"id": "p", "sections": [{"kind": "inbox", "id": "inbox"}]})
    it = next(i for pg in pages for s in pg["sections"] for i in s["items"])
    assert it["origin_raw"] == "claude" and it["origin_section_kind"] == "inbox"


# ---------------------------------------------------------------- the cockpit model

def fixture_with_origins(root: Path) -> dict:
    data = collect_fixture(root)
    data["sections"] = [{"id": "inbox", "kind": "inbox", "status": "ok"},
                        {"id": "github", "kind": "tracker", "provider": "github-board", "title": "GitHub", "status": "ok"},
                        {"id": "calendar", "kind": "calendar", "status": "ok"}, {"id": "tasks", "kind": "tasks", "status": "ok"}]
    do = data["view"]["buckets"][0]["items"]
    do[0].update(origin_raw="homebox/issue-radar", inbox_key="issue-radar:untasked:acme/web#12", inbox_kind="finding")
    do.append({"title": "About the quiet stream", "inbox_id": "20261009-0930-quiet-a1b2", "task": "quiet-task",
               "sources": ["inbox"], "origin_raw": "claude", "inbox_key": "q", "gate": "free", "urgency": "today"})
    data["view"]["buckets"][2]["items"][1].update(origin_provider="github-board", origin_section_kind="tracker")
    page = data["pages"][1]["sections"][0]["items"][0]
    page["origin_raw"] = "Ad-hoc 2026-10-01"
    return data


def world(tmp_path):
    w = World(tmp_path, serve=False, prepare=False)
    w.runner.handlers["briefing.collect"] = lambda argv: ok(fixture_with_origins(w.root))
    w.app.tabs.poll()
    w.app.collector.request("both")
    w.app.collector.drain()
    return w


def test_every_row_goes_out_with_its_origin_and_its_work_kind(tmp_path):
    w = world(tmp_path)
    try:
        model = w.app.collector.model
        rows = {r["key"]: r for s in model["sections"] for r in s["rows"]}
        radar = next(r for r in rows.values() if r["inbox_id"] == "20261009-0900-review-demo-a1b2")
        assert radar["origin"]["category"] == "bot" and radar["origin"]["ref"] == "acme/web#12"
        assert radar["work_kind"] == "task" and radar["about_kind"] is None
        quiet = next(r for r in rows.values() if r["inbox_id"] == "20261009-0930-quiet-a1b2")
        assert quiet["origin"]["category"] == "session" and quiet["work_kind"] == "stream"
        assert quiet["stream"] is False and quiet["closable"] is False
        issue = rows["ref:example/repo#12"]
        assert issue["origin"]["category"] == "github" and issue["work_kind"] is None
        task = rows["task:demo-task"]
        assert task["work_kind"] == "task" and task["origin"]["category"] == "bridge"
        every = {**{r["key"]: r for r in model["task_rows"]}, **rows}
        assert every["task:quiet-task"]["work_kind"] == "stream" and every["task:quiet-task"]["origin"]["category"] == "bridge"
        assert every["task:quiet-task"]["stream"] is True
        for r in [*rows.values(), *model["task_rows"], *model["hidden"]]:
            assert {"origin", "work_kind", "about_kind"} <= set(r), r["key"]
        items = [it for pg in model["pages"] for s in pg["sections"] for it in s["items"]]
        demo = next(it for it in items if it.get("task") == "demo-task")
        assert demo["work_kind"] == "task" and demo["origin"]["category"] == "bridge"
        assert demo["origin"]["raw"] == "Ad-hoc 2026-10-01"
        assert all({"origin", "work_kind"} <= set(it) for it in items)
        # the map stays on the server, the raw text rides only on the rows that have one
        assert "origin_map" not in json.dumps(model)
    finally:
        w.close()


def test_a_hidden_row_goes_out_with_its_origin_too(tmp_path):
    w = world(tmp_path)
    try:
        key = "ref:example/repo#7"
        w.act("later", key=key, until="2026-10-20")
        w.app.collector.request("delta")
        w.app.collector.drain()
        hidden = {r["key"]: r for r in w.app.collector.model["hidden"]}
        assert hidden[key]["origin"]["category"] == "github" and "work_kind" in hidden[key]
    finally:
        w.close()


# ---------------------------------------------------------------- the rebuild paths

def test_the_inbox_detail_and_the_task_detail_name_the_origin(tmp_path):
    w = World(tmp_path, serve=False, prepare=False)
    try:
        d = details.inbox_detail(w.root, "20261009-0910-tidy-labels-c3d4", None)
        assert d["origin"]["category"] == "bot" and d["origin"]["detail"] == "demo"     # <host>/<job>, no skill folder here
        assert d["origin"]["raw"] == "briefing/demo"
        listing = [{"id": "20261009-0910-tidy-labels-c3d4", "task": "demo-task", "state": "open", "from": "claude",
                    "kind": "decision", "summary": "x"}]
        t = details.task_detail(w.root, "demo-task", listing)
        assert t["work_kind"] == "task" and t["origin"]["category"] == "bridge" and t["origin"]["raw"] == "invented"
        assert t["inbox"][0]["from"] == "claude" and t["inbox"][0]["kind"] == "decision"
        assert t["inbox"][0]["origin"]["category"] == "session"
        done = w.root / "work" / "done" / "2026-10" / "old-stream"
        done.mkdir(parents=True)
        (done / "STATUS.md").write_text("---\nstatus: done\nwas_stream: true\nclosed: 2026-10-08\n---\n\n# Old stream\n")
        assert details.task_detail(w.root, "old-stream", [])["work_kind"] == "done_stream"
        week = daybook.week_done(w.root, dt.date(2026, 10, 9))
        assert [(x["slug"], x["work_kind"]) for x in week["items"]] == [("old-stream", "done_stream")]
    finally:
        w.close()


def test_a_page_item_rebuilt_from_the_inbox_keeps_its_source(tmp_path):
    w = World(tmp_path, serve=False, prepare=False)
    try:
        w.runner.handlers["inbox.list"] = lambda argv: ok([{"id": "20261009-0910-tidy-labels-c3d4", "state": "open",
                                                             "from": "briefing/demo", "kind": "decision"}])
        entry = w.app.actions.page_entry("inbox:20261009-0910-tidy-labels-c3d4")
        assert entry["row"]["origin_raw"] == "briefing/demo" and entry["row"]["inbox_kind"] == "decision"
    finally:
        w.close()


def test_jev_gets_nothing_new():
    assert not {"origin", "origin_raw", "work_kind", "about_kind", "inbox_kind"} & set(jev.ROW_FIELDS)
