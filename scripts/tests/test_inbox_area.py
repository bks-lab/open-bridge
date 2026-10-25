# SPDX-License-Identifier: MIT
"""Contract for the area of an inbox item (scripts/inbox.py), and the router that places it.

An item linked to a task shows that task's area. Before this, an item without a task had none, and the
cockpit's start page counted most of the inbox under "no area" (33 of 51 on 25.10.2026). Now:

* an item may carry an `area` from the start (`add --area`), or get one later by an `area` event
  (the last one wins, an empty value takes it back), like the urgency;
* with `inbox.place_on_add: true` in bridge-config.yaml, an item filed with neither a task nor an
  area starts `workplace.py place` for itself, detached, so the filer never waits on a model;
* `workplace.py place` asks the configured router once for all items it is given and writes an
  `area` event by `router` for each answer that names a configured workspace; a failing router
  writes nothing.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]

spec = importlib.util.spec_from_file_location("inbox", ROOT / "scripts" / "inbox.py")
assert spec is not None and spec.loader is not None
inbox = importlib.util.module_from_spec(spec)
sys.modules["inbox"] = inbox
sys.dont_write_bytecode = True
spec.loader.exec_module(inbox)

wspec = importlib.util.spec_from_file_location("workplace_for_area", ROOT / "scripts" / "workplace.py")
assert wspec is not None and wspec.loader is not None
workplace = importlib.util.module_from_spec(wspec)
wspec.loader.exec_module(workplace)

NOW = dt.datetime(2026, 10, 25, 18, 0)
SPACES = [{"name": "Bridge", "aliases": ["open-bridge"], "description": "own Bridge and open-bridge"},
          {"name": "Home", "default": True, "description": "private, family"}]


@pytest.fixture()
def box(tmp_path):
    return inbox.Inbox(tmp_path / "work" / "inbox", actor="laptop", clock=lambda: NOW)


def add(box, **kw):
    base = dict(source="cli", kind="finding", summary="the sink drips", closer="person")
    base.update(kw)
    return box.add(**base)


# ---------------------------------------------------------------- the field

def test_an_item_has_no_area_until_it_gets_one(box):
    item = box.get(add(box))
    assert item.area is None
    assert item.as_dict()["area"] is None


def test_add_with_an_area_keeps_it_in_the_item_file(box):
    item_id = add(box, area="Home")
    assert box.get(item_id).area == "Home"
    assert yaml.safe_load((box.root / item_id / "item.yaml").read_text())["area"] == "Home"


def test_the_last_area_event_wins_and_an_empty_one_takes_it_back(box):
    item_id = add(box, area="Home")
    box.set_area(item_id, "Bridge")
    assert box.get(item_id).area == "Bridge"
    box.set_area(item_id, "")
    assert box.get(item_id).area is None
    assert "area: Home" in (box.root / item_id / "item.yaml").read_text()   # the file is never rewritten


def test_set_area_refuses_a_closed_item(box):
    item_id = add(box)
    box.close(item_id)
    with pytest.raises(ValueError, match="closed"):
        box.set_area(item_id, "Home")


def test_an_area_event_by_the_router_carries_its_reason(box):
    item_id = add(box)
    box.set_area(item_id, "Home", by="router", why="a household repair")
    event = box.get(item_id).events[-1]
    assert (event.verb, event.by, event.data) == ("area", "router", {"value": "Home", "why": "a household repair"})


def test_validate_accepts_the_area_verb(box):
    box.set_area(add(box), "Home")
    assert box.validate() == []


def test_cli_area_sets_and_clears(tmp_path, capsys):
    root = tmp_path
    (root / "work" / "inbox").mkdir(parents=True)
    assert inbox.main(["--root", str(root), "add", "--from", "cli", "--kind", "idea", "--summary", "x",
                       "--area", "Home"]) == 0
    item_id = capsys.readouterr().out.strip()
    assert inbox.main(["--root", str(root), "area", item_id[:15], "Bridge"]) == 0
    assert inbox.main(["--root", str(root), "list", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["area"] == "Bridge"
    assert inbox.main(["--root", str(root), "area", item_id, "--clear"]) == 0
    assert inbox.Inbox(root / "work" / "inbox", actor="t").get(item_id).area is None


# ---------------------------------------------------------------- placing on add

@pytest.fixture()
def spawned(monkeypatch):
    calls = []

    class FakePopen:
        def __init__(self, argv, **kw):
            calls.append((argv, kw))

    monkeypatch.setattr(inbox.subprocess, "Popen", FakePopen)
    return calls


def _repo(tmp_path, place: bool):
    (tmp_path / "work" / "inbox").mkdir(parents=True)
    (tmp_path / "bridge-config.yaml").write_text(yaml.safe_dump({"inbox": {"place_on_add": place}}))
    return tmp_path


def _add(root, *extra):
    return inbox.main(["--root", str(root), "add", "--from", "cli", "--kind", "idea", "--summary", "the sink drips",
                       *extra])


def test_an_item_without_task_or_area_starts_place_for_itself(tmp_path, spawned, capsys):
    root = _repo(tmp_path, True)
    assert _add(root) == 0
    item_id = capsys.readouterr().out.strip()
    assert item_id
    (argv, kw), = spawned
    assert argv[-3:] == ["place", "--pending", "--quiet"]
    assert str(root) in argv and kw.get("cwd") == str(root)
    assert kw.get("start_new_session") is True       # detached: the filer never waits on a model


@pytest.mark.parametrize("extra", [("--task", "kitchen"), ("--area", "Home")])
def test_an_item_with_a_task_or_an_area_is_not_placed(tmp_path, spawned, extra):
    assert _add(_repo(tmp_path, True), *extra) == 0
    assert spawned == []


def test_nothing_is_placed_without_the_setting(tmp_path, spawned):
    assert _add(_repo(tmp_path, False)) == 0
    assert spawned == []


def test_a_repeat_of_an_open_item_is_not_placed_again(tmp_path, spawned):
    root = _repo(tmp_path, True)
    _add(root, "--key", "sink")
    _add(root, "--key", "sink")
    assert len(spawned) == 1


def test_a_failing_spawn_never_fails_the_add(tmp_path, monkeypatch, capsys):
    def broken(*a, **k):
        raise OSError("no python")
    monkeypatch.setattr(inbox.subprocess, "Popen", broken)
    assert _add(_repo(tmp_path, True)) == 0
    assert capsys.readouterr().out.strip()


# ---------------------------------------------------------------- workplace.py place

def _router(tmp_path, answer: str, rc: int = 0) -> list:
    script = tmp_path / "router.py"
    script.write_text(f"import sys\nsys.stdin.read()\nprint({answer!r})\nsys.exit({rc})\n")
    return [sys.executable, str(script)]


def test_place_writes_the_router_answer_as_an_area_event(tmp_path, box):
    a, b = add(box, summary="the sink drips"), add(box, summary="cockpit button too small")
    answer = json.dumps([{"item": a, "workspace": "Home", "why": "household"},
                         {"item": b, "workspace": "Bridge", "why": "cockpit"}])
    cfg = {"workspaces": SPACES, "router": {"command": _router(tmp_path, answer)}}
    placed = workplace.place(tmp_path, cfg, [a, b])
    assert {p["item"]: p["area"] for p in placed} == {a: "Home", b: "Bridge"}
    assert box.get(a).area == "Home" and box.get(b).area == "Bridge"
    assert box.get(a).events[-1].by == "router"


def test_place_skips_items_that_have_a_task_or_an_area_or_are_closed(tmp_path, box):
    linked, given, closed = add(box, task="kitchen"), add(box, area="Home"), add(box)
    box.close(closed)
    cfg = {"workspaces": SPACES, "router": {"command": _router(tmp_path, "[]")}}
    assert workplace.place(tmp_path, cfg, [linked, given, closed]) == []


def test_place_ignores_an_unknown_workspace_and_a_failing_router(tmp_path, box):
    a = add(box)
    bad = json.dumps([{"item": a, "workspace": "Mars", "why": "?"}])
    assert workplace.place(tmp_path, {"workspaces": SPACES, "router": {"command": _router(tmp_path, bad)}}, [a]) == []
    assert workplace.place(tmp_path, {"workspaces": SPACES, "router": {"command": _router(tmp_path, "x", 1)}}, [a]) == []
    assert workplace.place(tmp_path, {"workspaces": SPACES}, [a]) == []      # no router configured
    assert box.get(a).area is None


def test_place_unplaced_takes_every_open_item_without_task_and_area(tmp_path, box):
    a, _linked = add(box), add(box, task="kitchen")
    assert workplace.unplaced(tmp_path) == [a]


def test_place_dry_run_writes_nothing(tmp_path, box):
    a = add(box)
    answer = json.dumps([{"item": a, "workspace": "Home", "why": "household"}])
    cfg = {"workspaces": SPACES, "router": {"command": _router(tmp_path, answer)}}
    assert workplace.place(tmp_path, cfg, [a], write=False)[0]["area"] == "Home"
    assert box.get(a).area is None


def test_a_launched_item_without_task_goes_to_its_area(tmp_path, box):
    a = add(box, area="Bridge")
    cfg = {"workspaces": SPACES}
    entry, = workplace.build_launch(tmp_path, cfg, [a], "go")
    assert entry["workspace"] == "Bridge"
    plain = add(box, summary="another")
    entry, = workplace.build_launch(tmp_path, cfg, [plain], "go")
    assert entry["workspace"] == "Home"                      # no area: the default, as before


def test_a_muted_new_item_is_not_placed(tmp_path, spawned):
    root = _repo(tmp_path, True)
    box = inbox.Inbox(root / "work" / "inbox", actor="t")
    first = box.add(source="cli", kind="idea", summary="noise", key="loud:1")
    box.drop(first, reason="family")
    _add(root, "--key", "loud:2")
    assert spawned == []


def _with_spaces(root):
    (root / "bridge-config.yaml").write_text(yaml.safe_dump({"workplace": {"workspaces": SPACES}}))
    return root


def test_an_area_is_stored_under_its_workspace_name_whatever_alias_or_case(tmp_path, capsys):
    root = _with_spaces(tmp_path)
    (root / "work" / "inbox").mkdir(parents=True)
    assert inbox.main(["--root", str(root), "add", "--from", "cli", "--kind", "idea", "--summary", "x",
                       "--area", "OPEN-BRIDGE"]) == 0
    item_id = capsys.readouterr().out.strip()
    box = inbox.Inbox(root / "work" / "inbox", actor="t")
    assert box.get(item_id).area == "Bridge"
    assert inbox.main(["--root", str(root), "area", item_id, "home"]) == 0
    assert box.get(item_id).area == "Home"


def test_an_unknown_area_is_refused_by_area_and_left_out_by_add(tmp_path, capsys):
    root = _with_spaces(tmp_path)
    (root / "work" / "inbox").mkdir(parents=True)
    assert inbox.main(["--root", str(root), "add", "--from", "cli", "--kind", "idea", "--summary", "x",
                       "--area", "Hom"]) == 0
    out = capsys.readouterr()
    item_id = out.out.strip()
    assert "no area here" in out.err
    box = inbox.Inbox(root / "work" / "inbox", actor="t")
    assert box.get(item_id).area is None
    assert inbox.main(["--root", str(root), "area", item_id, "Mars"]) == 1
    assert inbox.main(["--root", str(root), "area", item_id, "  "]) == 1     # blank is not a clear
    assert box.get(item_id).area is None


def test_place_does_not_overwrite_an_area_a_person_set_while_the_router_thought(tmp_path, box, monkeypatch):
    a, b = add(box), add(box, summary="second")
    answer = json.dumps([{"item": a, "workspace": "Bridge"}, {"item": b, "workspace": "Bridge"}])
    cfg = {"workspaces": SPACES, "router": {"command": _router(tmp_path, answer)}}
    real = workplace._ask_router

    def slow(*args, **kw):
        out = real(*args, **kw)
        box.set_area(a, "Home")         # a person, meanwhile
        box.close(b)                    # and a check closed the other one
        return out
    monkeypatch.setattr(workplace, "_ask_router", slow)
    assert workplace.place(tmp_path, cfg, [a, b]) == []
    assert box.get(a).area == "Home"


def test_pending_places_everything_once_and_a_second_placer_leaves(tmp_path, box):
    a = add(box)
    answer = json.dumps([{"item": a, "workspace": "Home"}])
    cfg = {"workspaces": SPACES, "router": {"command": _router(tmp_path, answer)}}
    import fcntl
    lock = tmp_path / workplace.PLACE_LOCK
    lock.parent.mkdir(parents=True)
    with open(lock, "a") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert workplace.place_pending(tmp_path, cfg, settle=0) == []
    b = add(box, summary="the router does not know this one")
    placed = workplace.place_pending(tmp_path, cfg, settle=0)
    assert [p["item"] for p in placed] == [a]          # b was asked about once, and not again
    assert box.get(b).area is None

