# SPDX-License-Identifier: MIT
"""Contract for every task and stream as a file (cockpit.files_scope, docs/cockpit-files.md).

* `cockpit.files_scope` is `active` (the default: the files view walks the doing and review tasks, as before)
  or `all`; anything else keeps `active` and says so; the state hands it to the page with the work view;
* with `all` the collector reads `workplace.py tasks --all --json` once, keeps only the doing and review ones
  for every consumer it had (rows, WIP, focus), and hands the page `model.files`: every task and stream,
  backlog included, done ones never, small and flat, each with its bucket where a row stands for it and
  whether it is put off and until when;
* with `active` the argv stays `tasks --json` and `model.files` is None, so nothing grows.

Run: pytest -q scripts/tests/test_bridge_cockpit_files_all.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_bridge_cockpit import TASKS, World, ok, private_key_dir  # noqa: E402,F401  (the autouse fixture comes along)
from lib.bridge_cockpit import collector as co  # noqa: E402
from lib.bridge_cockpit import model as m  # noqa: E402
from lib.bridge_cockpit.config import load_web_config  # noqa: E402

BASE = "cockpit:\n  enabled: true\n  language: en\n"

# what the page reads of a file (files.js fileShelves, fileReason, views/dossier.js Shelves), and nothing more:
# the cover reads its facts from the task's detail, so headline, next and progress stay out of every poll
FILE_KEYS = {"slug", "kind", "status", "area_names", "priority", "title", "updated", "blocked_by", "bucket",
             "deferred", "deferred_until"}

ALL = [
    {**TASKS[0], "kind": "tasks", "next": "Ship the demo", "next_who": "me", "next_due": "2026-10-30",
     "headline": "The demo ships", "progress": {"done": 1, "total": 3}, "updated": "2026-10-20"},
    {"slug": "parked", "label": "Parked idea", "title": "A parked idea", "area": "Ops", "priority": "P3",
     "status": "backlog", "kind": "tasks", "updated": "2026-09-01"},
    {"slug": "river", "label": "River", "area": "Ops", "priority": "P2", "status": "doing", "kind": "streams",
     "blocked_by": "the vendor"},
]


# ---------------------------------------------------------------- config

def test_files_scope_defaults_to_active_and_takes_all(tmp_path):
    assert load_web_config(tmp_path, {}).files_scope == "active"
    for scope in ("active", "all"):
        cfg = load_web_config(tmp_path, {"cockpit": {"files_scope": scope}})
        assert cfg.files_scope == scope and cfg.config_warnings == ()


@pytest.mark.parametrize("value", ["backlog", 1, True])
def test_a_wrong_files_scope_keeps_active_and_says_so(tmp_path, value):
    cfg = load_web_config(tmp_path, {"cockpit": {"files_scope": value}})
    assert cfg.files_scope == "active"
    out = cfg.config_warnings
    assert len(out) == 1 and out[0].startswith("cockpit.files_scope:") and out[0].endswith('using "active"'), out


def test_the_state_hands_the_files_scope_to_the_page(tmp_path):
    w = World(tmp_path / "a", config=BASE, serve=False, prepare=False)
    try:
        assert w.app.state_payload()["work"]["files_scope"] == "active"
    finally:
        w.close()
    w = World(tmp_path / "b", config=BASE + "  files_scope: all\n", serve=False, prepare=False)
    try:
        assert w.app.state_payload()["work"]["files_scope"] == "all"
    finally:
        w.close()


# ---------------------------------------------------------------- the list

def test_files_of_lists_every_task_flat_with_its_bucket_and_whether_it_is_put_off():
    tasks = m.parse_tasks(ALL)
    index = {"task:demo-task": {"out": {"bucket": "do"}, "hidden": False},
             "task:river": {"out": {"bucket": "resting", "hidden_until": "2026-11-01"}, "hidden": True}}
    files = co.files_of(tasks, index)
    assert [f["slug"] for f in files] == ["demo-task", "parked", "river"]
    assert all(set(f) == FILE_KEYS for f in files)
    demo, parked, river = files
    assert demo["kind"] == "task" and demo["bucket"] == "do" and demo["deferred"] is False
    assert demo["area_names"] == ["Demo", "DemoArea"] and demo["updated"] == "2026-10-20"
    # a backlog task stands in no section: no bucket, never put off
    assert parked["status"] == "backlog" and parked["bucket"] is None and parked["title"] == "A parked idea"
    assert river["kind"] == "stream" and river["deferred"] is True and river["deferred_until"] == "2026-11-01"
    assert river["blocked_by"] == "the vendor"
    # a done task never reaches the list, whatever workplace.py hands over
    assert co.files_of(m.parse_tasks([{"slug": "gone", "status": "done", "kind": "tasks"}]), {}) == []


def test_with_all_the_collector_reads_every_task_but_keeps_its_consumers_on_the_active_ones(tmp_path):
    w = World(tmp_path, config=BASE + "  files_scope: all\n", serve=False, prepare=False)
    try:
        w.runner.handlers["workplace.tasks"] = lambda argv: ok(ALL)
        w.app.tabs.poll()
        w.app.collector.request("both")
        w.app.collector.drain()
        argvs = w.runner.of("workplace.tasks")
        assert argvs and all("--all" in a for a in argvs)
        # rows, WIP and focus see what they always saw: no backlog task in the collector's list
        assert [t["slug"] for t in w.app.collector.tasks] == ["demo-task", "river"]
        model = w.app.collector.model
        keys = {r["key"] for sec in model["sections"] for r in sec["rows"]} | {r["key"] for r in model["task_rows"]}
        assert "task:parked" not in keys
        files = {f["slug"]: f for f in model["files"]}
        assert set(files) == {"demo-task", "parked", "river"}
        assert files["parked"]["status"] == "backlog"
        # demo-task has its row in a section: the bucket comes from there
        assert files["demo-task"]["bucket"] == w.row("task:demo-task")["bucket"]
    finally:
        w.close()


def test_a_task_put_off_through_the_store_comes_out_deferred_with_its_day(tmp_path):
    w = World(tmp_path, config=BASE + "  files_scope: all\n", serve=False, prepare=False)
    try:
        w.runner.handlers["workplace.tasks"] = lambda argv: ok(ALL)
        w.app.tabs.poll()
        w.app.collector.request("both")
        w.app.collector.drain()
        files = {f["slug"]: f for f in w.app.collector.model["files"]}
        assert files["demo-task"]["deferred"] is False and files["demo-task"]["deferred_until"] is None
        # put off to a day, and put away until shown again (dismissed), through the store as the verbs do
        w.app.store.hide("task:demo-task", "2099-01-05")
        w.app.store.dismiss("task:river", "later", "River")
        w.app.collector.request("both")
        w.app.collector.drain()
        files = {f["slug"]: f for f in w.app.collector.model["files"]}
        assert files["demo-task"]["deferred"] is True and files["demo-task"]["deferred_until"] == "2099-01-05"
        assert files["river"]["deferred"] is True and files["river"]["deferred_until"] is None
        # a backlog task stands in no section and is never put off
        assert files["parked"]["deferred"] is False and files["parked"]["bucket"] is None
    finally:
        w.close()


def test_with_active_nothing_changes_and_no_list_goes_out(tmp_path):
    w = World(tmp_path, config=BASE)
    try:
        argvs = w.runner.of("workplace.tasks")
        assert argvs and not any("--all" in a for a in argvs)
        assert w.app.collector.model["files"] is None
    finally:
        w.close()
