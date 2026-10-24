# SPDX-License-Identifier: MIT
"""inbox_tab_index keeps a persistent per-item cache, so a status poll re-reads only what changed.

`workplace.py status` runs every few seconds while the cockpit is open; parsing every inbox
item and event with pure-Python yaml each time was the biggest slice of its CPU.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("workplace", ROOT / "scripts" / "workplace.py")
assert spec is not None and spec.loader is not None
wp = importlib.util.module_from_spec(spec)
sys.modules["workplace"] = wp
sys.dont_write_bytecode = True
spec.loader.exec_module(wp)

OPEN_ID = "20261006-1411-systems-remotes-buildhost-alpha-0855"
DONE_ID = "20261006-1500-closed-thing-aaaa"
THIRD_ID = "20261007-0900-third-thing-bbbb"


def _item(root: Path, iid: str, verbs=()):
    d = root / "work" / "inbox" / iid
    d.mkdir(parents=True)
    (d / "item.yaml").write_text(
        "schema_version: 1\nkind: question\nsummary: x\ngate: free\nurgency: today\n"
        "created: '2026-10-06T14:11:00+02:00'\nfrom: test\n", encoding="utf-8")
    for i, verb in enumerate(verbs):
        _event(d, f"0{i}-{verb}.yaml", verb)
    return d


def _event(item_dir: Path, name: str, verb: str, extra: str = ""):
    ev = item_dir / "events"
    ev.mkdir(exist_ok=True)
    (ev / name).write_text(f"verb: {verb}\nby: t\nat: '2026-10-06T15:00:00+02:00'\n{extra}", encoding="utf-8")


@pytest.fixture()
def root(tmp_path):
    _item(tmp_path, OPEN_ID)
    _item(tmp_path, DONE_ID, ["close"])
    return tmp_path


@pytest.fixture()
def loads(monkeypatch):
    """Counts every yaml parse the inbox does."""
    calls = []
    real = yaml.load

    def counting(stream, Loader=None):
        calls.append(stream)
        return real(stream, Loader=Loader)

    monkeypatch.setattr(yaml, "load", counting)
    monkeypatch.setattr(yaml, "safe_load", lambda s: counting(s, yaml.SafeLoader))
    return calls


def _ids(index: dict) -> set:
    return set(index.values())


def test_first_call_indexes_open_and_done_items(root):
    assert _ids(wp.inbox_tab_index(root)) == {OPEN_ID, DONE_ID}


def test_second_call_without_changes_parses_nothing(root, loads):
    first = wp.inbox_tab_index(root)
    assert loads
    loads.clear()
    assert wp.inbox_tab_index(root) == first
    assert loads == []


def test_a_changed_item_is_read_again_and_the_others_are_not(root, loads):
    wp.inbox_tab_index(root)
    loads.clear()
    d = root / "work" / "inbox" / OPEN_ID
    _event(d, "00-close.yaml", "close")
    os.utime(d / "events", ns=(1, 1))      # a coarse clock must not hide the change
    wp.inbox_tab_index(root)
    assert any("verb: close" in str(s) for s in loads)
    assert sum("kind: question" in str(s) for s in loads) == 1   # only the changed item's item.yaml


def test_a_removed_item_drops_out(root):
    wp.inbox_tab_index(root)
    import shutil
    shutil.rmtree(root / "work" / "inbox" / OPEN_ID)
    assert _ids(wp.inbox_tab_index(root)) == {DONE_ID}


def test_a_new_item_appears(root):
    wp.inbox_tab_index(root)
    _item(root, THIRD_ID)
    assert THIRD_ID in _ids(wp.inbox_tab_index(root))


def test_done_items_stay_in_the_index(root):
    assert DONE_ID in _ids(wp.inbox_tab_index(root))
    assert DONE_ID in _ids(wp.inbox_tab_index(root))     # also when served from the cache


def test_an_open_item_wins_over_a_done_one_with_the_same_label(root):
    twin = "20261006-1411-systems-remotes-buildhost-alpha-0855"
    assert wp.inbox_tab_index(root)[f"inbox-{wp.inbox_slug(twin)}"] == OPEN_ID


@pytest.mark.parametrize("junk", ["not json {", "[1, 2]", '{"version": 999, "items": "x"}', '{"items": {"a": 5}}'])
def test_a_broken_or_foreign_cache_is_ignored_and_rewritten(root, junk):
    wp.inbox_tab_index(root)
    cache = next((root / ".bridge" / "cache").glob("*.json"))
    cache.write_text(junk, encoding="utf-8")
    assert _ids(wp.inbox_tab_index(root)) == {OPEN_ID, DONE_ID}
    assert isinstance(json.loads(cache.read_text(encoding="utf-8")), dict)
    assert not list(cache.parent.glob("*.tmp*"))


def test_a_deferral_is_judged_against_the_day_of_the_read(root):
    """The cache keeps the end date, not the verdict, so a lapsed deferral reopens without a file change."""
    d = _item(root, THIRD_ID)
    _event(d, "00-defer.yaml", "defer", "until: '2020-01-01'\n")
    wp.inbox_tab_index(root)
    cache = next((root / ".bridge" / "cache").glob("*.json"))
    entry = json.loads(cache.read_text(encoding="utf-8"))["items"][THIRD_ID]
    assert entry["deferred_until"] == "2020-01-01" and entry["state"] == "open"
    assert wp.inbox_tab_index(root)[f"inbox-{wp.inbox_slug(THIRD_ID)}"] == THIRD_ID
