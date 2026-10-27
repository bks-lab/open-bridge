# SPDX-License-Identifier: MIT
"""Contract for Merge on the Work through page: flow_merge, task_unmerge, the history and the Activity rows.

* flow_merge {keep, keys}: the tasks of `keys` close as merged into the task of `keep`, one `task.py merge` each, in
  the order given. Refused with flow_off while Work through is off, before its arguments are read; every row is
  checked before the first write: a key that is gone (stale_row), one that is no open finite task under work/tasks/,
  a stream or an inbox item (merge_not_task), keep among the keys or more than nine (invalid_argument). A merge that
  fails is said and the next one goes on;
* one history entry, per merged task an item with its undo (task_unmerge with the status it had) and an item on
  the kept task; the answer carries merge {keep, merged, failed}, the settled keys and the undo;
* task_unmerge {keep, slug, as}: only an undo the server handed out, only while the merged section is there as the
  merge left it (merge_changed); no flow gate, it is an undo;
* both Activities show the merge as a decision row, with when it was taken back.

The runner is the fake of test_bridge_cockpit: task.py never runs here (its own contract is test_task.py), its
answers come from handlers that write the marker of the merged section as the real one does.

Run: pytest -q scripts/tests/test_bridge_cockpit_merge.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
import urllib.parse
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_bridge_cockpit import NOW, ONLY_ID, World, fail, ok, private_key_dir, refused  # noqa: E402,F401
from lib.bridge_cockpit import actions_work as aw  # noqa: E402
from lib.bridge_cockpit import history as hist  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
FLOW = "cockpit:\n  enabled: true\n  language: {lang}\n  flow:\n    enabled: {on}\n"
KEEP, A, B = "task:demo-task", "task:other-task", "task:filed-task"


def status(root: Path, slug: str, state: str, kind: str = "tasks") -> Path:
    folder = root / "work" / kind / slug
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "STATUS.md"
    path.write_text(f"---\nslug: {slug}\nstatus: {state}\nheadline: The {slug}\n---\n\n# The {slug}\n\n## Notes\n",
                    encoding="utf-8")
    return path


def make(tmp_path, on: str = "true", lang: str = "en") -> World:
    w = World(tmp_path, config=FLOW.format(on=on, lang=lang))
    status(w.root, "other-task", "review")
    status(w.root, "filed-task", "backlog")
    status(w.root, "quiet-task", "doing", kind="streams")
    keep = w.root / "work" / "tasks" / "demo-task" / "STATUS.md"

    def merge(argv):
        slug = argv[argv.index("--from") + 1]
        first, last = aw.merge_marks(slug)
        keep.write_text(keep.read_text(encoding="utf-8") + f"\n{first}\n## Merged from {slug}\n{last}\n", encoding="utf-8")
        return ok({"keep": "demo-task", "slug": slug, "moved_to": f"work/done/2026-10/{slug}", "notes": 1, "steps": 1,
                   "docs": 0, "related": 1, "warnings": []})

    def unmerge(argv):
        slug = argv[argv.index("--from") + 1]
        first, last = aw.merge_marks(slug)
        text = keep.read_text(encoding="utf-8")
        keep.write_text(text[:text.index(first)] + text[text.index(last) + len(last):], encoding="utf-8")
        return ok({"keep": "demo-task", "slug": slug, "moved_to": f"work/tasks/{slug}", "status": "review",
                   "removed": {"block": True, "related": 1}, "warnings": []})
    w.runner.handlers["task.merge"] = merge
    w.runner.handlers["task.unmerge"] = unmerge
    w.app.collector.request("both")
    w.app.collector.drain()
    return w


@pytest.fixture
def world(tmp_path):
    w = make(tmp_path)
    yield w
    w.close()


def task_calls(w: World) -> list[list[str]]:
    return [c for c in w.runner.calls if w.runner.key(c) in ("task.merge", "task.unmerge", "task.close", "task.reopen")]


def T(w: World, *args: str) -> list[str]:
    return [sys.executable, w.app.runner.script("scripts/task.py"), "--root", str(w.root), *args]


# ---------------------------------------------------------------- flow_merge

def test_the_merge_closes_each_task_into_the_one_that_stays_in_the_order_given(world):
    world.runner.calls.clear()
    res = world.act("flow_merge", keep=KEEP, keys=[A, B])
    assert task_calls(world) == [
        T(world, "merge", "demo-task", "--from", "other-task", "--heading", "Merged from {slug}", "--json"),
        T(world, "merge", "demo-task", "--from", "filed-task", "--heading", "Merged from {slug}", "--json")]
    assert res["ok"] is True and res["merge"] == {"keep": "demo-task", "merged": ["other-task", "filed-task"], "failed": []}
    assert res["settled"] == [A, B]
    assert res["note"] == "Other task, Filed task merged into Work on the demo task"
    # one undo per merged task, back to the status it had
    assert [u["undo"] for u in res["undo"]] == [
        {"verb": "task_unmerge", "args": {"keep": "demo-task", "slug": "other-task", "as": "review"}},
        {"verb": "task_unmerge", "args": {"keep": "demo-task", "slug": "filed-task", "as": "backlog"}}]
    [entry] = [e for e in world.app.history.state() if e["verb"] == "flow_merge"]
    assert entry["id"] == res["history"]
    assert [(it["key"], it["did"], it.get("into"), it.get("from")) for it in entry["items"]] == [
        (A, "merged", "demo-task", None), (KEEP, "merged_in", None, "other-task"),
        (B, "merged", "demo-task", None), (KEEP, "merged_in", None, "filed-task")]
    gone = entry["items"][0]
    assert gone["kind"] == "task" and gone["ident"] == "other-task" and gone["work_kind"] == "task"
    assert gone["undone_ms"] is None and entry["items"][1]["undo"] is None
    # the merged rows leave the model at once, the kept one stays
    assert world.app.collector.resolve(A) is None and world.app.collector.resolve(KEEP) is not None


def test_the_heading_is_in_the_language_of_the_instance(tmp_path):
    w = make(tmp_path, lang="de")
    try:
        w.runner.calls.clear()
        w.act("flow_merge", keep=KEEP, keys=[A])
        assert "Zusammengeführt aus {slug}" in task_calls(w)[0]
    finally:
        w.close()


def test_a_merge_that_fails_is_said_and_the_next_one_goes_on(world):
    real = world.runner.handlers["task.merge"]
    world.runner.handlers["task.merge"] = lambda argv: fail("it broke") if "other-task" in argv else real(argv)
    res = world.act("flow_merge", keep=KEEP, keys=[A, B])
    assert res["ok"] is False and res["merge"] == {"keep": "demo-task", "merged": ["filed-task"], "failed": ["other-task"]}
    assert "Could not merge Other task: it broke" in res["note"] and res["settled"] == [B]
    assert [u["undo"]["args"]["slug"] for u in res["undo"]] == ["filed-task"]


@pytest.mark.parametrize("args, code, field", [
    ({"keep": KEEP, "keys": [KEEP, A]}, "invalid_argument", "keys"),            # the one that stays is no merged one
    ({"keep": KEEP, "keys": [A, A]}, "invalid_argument", "keys"),
    ({"keep": KEEP, "keys": [f"task:t{n}" for n in range(10)]}, "invalid_argument", "keys"),
    ({"keep": "task:gone-task", "keys": [A]}, "stale_row", "keep"),
    ({"keep": KEEP, "keys": [A, "task:gone-task"]}, "stale_row", "keys"),
    ({"keep": KEEP, "keys": [f"inbox:{ONLY_ID}"]}, "merge_not_task", "keys"),
    ({"keep": KEEP, "keys": ["task:quiet-task"]}, "merge_not_task", "keys"),     # a stream
    ({"keep": "task:quiet-task", "keys": [A]}, "merge_not_task", "keep"),
    ({"keep": KEEP, "keys": ["ref:example/repo#12"]}, "merge_not_task", "keys"),
])
def test_every_row_is_checked_before_the_first_write(world, args, code, field):
    world.runner.calls.clear()
    err = refused(world, code, "flow_merge", **args)
    assert err.field == field
    assert task_calls(world) == []


def test_a_task_closed_meanwhile_is_no_open_task(world):
    (world.root / "work" / "tasks" / "other-task" / "STATUS.md").unlink()
    err = refused(world, "merge_not_task", "flow_merge", keep=KEEP, keys=[A])
    assert err.field == "keys"


def test_with_work_through_off_the_merge_is_refused_before_its_arguments(tmp_path):
    w = make(tmp_path, on="false")
    try:
        refused(w, "flow_off", "flow_merge", keep="not a key", keys="nothing")
        assert task_calls(w) == []
    finally:
        w.close()


# ---------------------------------------------------------------- task_unmerge, the undo

def test_the_undo_reopens_the_merged_task_as_it_was_and_both_items_say_so(world):
    res = world.act("flow_merge", keep=KEEP, keys=[A])
    undo = res["undo"][0]["undo"]
    world.runner.calls.clear()
    back = world.act(undo["verb"], **undo["args"])
    assert task_calls(world) == [T(world, "unmerge", "demo-task", "--from", "other-task", "--as", "review", "--json")]
    assert back["ok"] is True and back["unmerge"] == {"keep": "demo-task", "slug": "other-task"}
    assert back["note"] == "Merge of Other task taken back"
    [entry] = [e for e in world.app.history.state() if e["verb"] == "flow_merge"]
    assert all(it["undone_ms"] == int(NOW) for it in entry["items"])
    # handed out once, taken back once
    refused(world, "not_applicable", undo["verb"], **undo["args"])


def test_only_an_undo_the_server_handed_out_is_taken(world):
    world.act("flow_merge", keep=KEEP, keys=[A])
    refused(world, "not_applicable", "task_unmerge", keep="demo-task", slug="other-task", **{"as": "doing"})
    refused(world, "not_applicable", "task_unmerge", keep="demo-task", slug="filed-task")
    refused(world, "invalid_argument", "task_unmerge", keep="demo-task", slug="other-task", **{"as": "done"})


def test_a_section_changed_by_hand_cannot_be_taken_back(world):
    res = world.act("flow_merge", keep=KEEP, keys=[A])
    keep = world.root / "work" / "tasks" / "demo-task" / "STATUS.md"
    keep.write_text(keep.read_text(encoding="utf-8").replace(aw.merge_marks("other-task")[1], ""), encoding="utf-8")
    world.runner.calls.clear()
    err = refused(world, "merge_changed", "task_unmerge", **res["undo"][0]["undo"]["args"])
    assert err.field == "keep" and task_calls(world) == []


def test_the_undo_needs_no_work_through(world, tmp_path):
    res = world.act("flow_merge", keep=KEEP, keys=[A])
    import dataclasses
    world.app.cfg = dataclasses.replace(world.app.cfg, flow={**world.app.cfg.flow, "enabled": False})
    assert world.act("task_unmerge", **res["undo"][0]["undo"]["args"])["ok"] is True


def test_the_undo_verb_and_the_backfill_know_a_merge():
    assert "task_unmerge" in hist.UNDO_VERBS


def test_a_task_closed_as_merged_backfills_as_merged(tmp_path):
    done = tmp_path / "work" / "done" / "2026-10" / "gone-task"
    done.mkdir(parents=True)
    (done / "STATUS.md").write_text("---\nstatus: done\noutcome: merged\nmerged_into: demo-task\n---\n\n# Gone\n",
                                    encoding="utf-8")
    item = hist._closed_item(tmp_path, "task:gone-task")
    assert item["did"] == "merged" and item["undo"] == {"verb": "task_reopen", "args": {"slug": "gone-task"}}


def test_the_marks_are_the_ones_task_py_writes():
    spec = importlib.util.spec_from_file_location("task_for_marks", ROOT / "scripts" / "task.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod._marks("x-task") == aw.merge_marks("x-task")


# ---------------------------------------------------------------- the Activity of both tasks

def feed(w: World, key: str) -> dict:
    status, _h, body = w.request("GET", f"/api/flow/activity?{urllib.parse.urlencode({'key': key, 'fresh': '1'})}",
                                 headers=w.cookie)
    assert status == 200, body
    return json.loads(body)


def decisions(data: dict) -> list[dict]:
    return [r for r in data["rows"] if r["kind"] == "decision"]


def test_both_activities_show_the_merge_and_when_it_was_taken_back(world):
    res = world.act("flow_merge", keep=KEEP, keys=[A])
    [kept] = decisions(feed(world, KEEP))
    assert kept["change"] == {"field": "decision", "old": None, "new": "merged_in", "from": "other-task"}
    assert kept["text"] == "Merged in other-task" and kept["undone_ms"] is None
    # the fake runner leaves the folder in place, so the merged task still answers (a real merge moved it to done/)
    [gone] = decisions(feed(world, A))
    assert gone["change"] == {"field": "decision", "old": None, "new": "merged", "into": "demo-task"}
    assert gone["text"] == "Merged into demo-task"
    world.act("task_unmerge", **res["undo"][0]["undo"]["args"])
    assert decisions(feed(world, KEEP))[0]["undone_ms"] == int(NOW)
    assert decisions(feed(world, A))[0]["undone_ms"] == int(NOW)


def test_a_backlog_task_without_a_row_merges_under_its_own_title(tmp_path):
    w = World(tmp_path, config=FLOW.format(on="true", lang="en") + "  files_scope: all\n")
    try:
        status(w.root, "parked", "backlog")
        listed = [{"slug": "demo-task", "label": "Demo task", "area": "Demo", "status": "doing", "kind": "tasks"},
                  {"slug": "parked", "label": "Parked", "title": "A parked idea", "area": "Ops", "status": "backlog",
                   "kind": "tasks"}]
        w.runner.handlers["workplace.tasks"] = lambda argv: ok(listed)
        w.runner.handlers["task.merge"] = lambda argv: ok({"keep": "demo-task", "slug": "parked"})
        w.app.collector.request("both")
        w.app.collector.drain()
        assert w.app.collector.resolve("task:parked") is None          # no row of its own: only model.files
        res = w.act("flow_merge", keep=KEEP, keys=["task:parked"])
        assert res["note"] == "A parked idea merged into Work on the demo task"
        assert res["undo"][0]["title"] == "A parked idea"
    finally:
        w.close()
