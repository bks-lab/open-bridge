# SPDX-License-Identifier: MIT
"""Contract for the shared record of settled rows (scripts/lib/bridge_cockpit/settled.py).

A row the person settled in the cockpit (done, not doing, or not now until a day) stays settled on
every machine: each decision is one new file under work/cockpit/settled/, written once and never
changed, so two machines writing through git never conflict. WebStore reads it merged with the
legacy keys of state.json, migrates those once (idempotent) and keeps writing them for a downgrade.

Run: python3.14 -m pytest -q scripts/tests/test_bridge_cockpit_settled.py
"""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from lib.bridge_cockpit import watch  # noqa: E402
from lib.bridge_cockpit.settled import SettledStore  # noqa: E402
from lib.bridge_cockpit.store import WebStore  # noqa: E402

NOW = dt.datetime(2026, 10, 10, 9, 0).timestamp() * 1000     # local 10.10.2026 09:00, in ms like the cockpit clock
TODAY = "2026-10-10"
KEY = "ref:example/repo#12"


class Clock:
    def __init__(self, now: float = NOW):
        self.now = now

    def __call__(self) -> float:
        return self.now

    def days(self, n: int) -> None:
        self.now += n * 86400 * 1000


def files(folder: Path) -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(folder.glob("*.yaml"))}


def legacy(state_dir: Path, hidden=None, dismissed=None, **extra) -> dict:
    data = {"v": 1, "hidden": hidden or {}, "dismissed": dismissed or {}, "team_runs": {}, "home_tiles": None,
            "home_seen": None, "pins": [], "session_links": {}, "tour": None, "runs_seen": {}, **extra}
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "state.json").write_text(json.dumps(data), encoding="utf-8")
    return data


# ---------------------------------------------------------------- the store itself

def test_each_decision_is_one_new_file_never_changed(tmp_path):
    folder, clock = tmp_path / "settled", Clock()
    store = SettledStore(folder, clock)
    store.hide(KEY, "2026-10-12", "Fix the example issue")
    first = files(folder)
    store.dismiss(KEY, "done", "Fix the example issue")
    store.unsettle(KEY)
    now = files(folder)
    assert len(now) == 3
    assert {k: now[k] for k in first} == first                  # what was written stays as it was
    assert store.hidden(TODAY) == {} and store.dismissed() == {}


def test_the_latest_decision_for_a_key_wins(tmp_path):
    clock = Clock()
    store = SettledStore(tmp_path / "settled", clock)
    store.dismiss(KEY, "not_doing", "Fix the example issue")
    assert store.dismissed() == {KEY: {"outcome": "not_doing", "at": TODAY, "title": "Fix the example issue"}}
    assert store.hidden(TODAY) == {}
    store.hide(KEY, "2026-10-12", "Fix the example issue")      # a later "not now" replaces the dismissal
    assert store.dismissed() == {} and store.hidden(TODAY) == {KEY: "2026-10-12"}
    assert store.knows(KEY) and not store.knows("ref:example/repo#13")


def test_a_hide_ends_on_its_day_and_a_dismissal_never(tmp_path):
    clock = Clock()
    store = SettledStore(tmp_path / "settled", clock)
    store.hide("task:alpha", "2026-10-12", "Alpha")
    store.dismiss(KEY, "done", "Fix the example issue")
    assert store.hidden("2026-10-11") == {"task:alpha": "2026-10-12"}
    assert store.hidden("2026-10-12") == {}                     # hidden while the date is after today
    assert KEY in store.dismissed()


def test_a_file_from_another_machine_is_read_without_a_restart(tmp_path):
    folder = tmp_path / "settled"
    here, there = SettledStore(folder, Clock()), SettledStore(folder, Clock(NOW + 5000))
    assert here.dismissed() == {}
    there.dismiss(KEY, "done", "Fix the example issue")         # as if a pull brought its file
    assert KEY in here.dismissed()
    there.unsettle(KEY)
    assert here.dismissed() == {}


def test_a_broken_or_foreign_file_is_skipped(tmp_path):
    folder = tmp_path / "settled"
    folder.mkdir()
    (folder / "20261010T070000Z-000-aaaa-dismiss.yaml").write_text("{not yaml: [", encoding="utf-8")
    (folder / "20261010T070001Z-000-bbbb-dismiss.yaml").write_text("key: 12\nact: dismiss\n", encoding="utf-8")
    (folder / "20261010T070002Z-000-cccc-dismiss.yaml").write_text(
        f"key: '{KEY}'\nact: dismiss\noutcome: maybe\n", encoding="utf-8")
    (folder / "notes.txt").write_text("not a decision", encoding="utf-8")
    store = SettledStore(folder, Clock())
    assert store.dismissed() == {} and store.hidden(TODAY) == {}
    store.dismiss(KEY, "done", "ok")
    assert KEY in store.dismissed()


def test_a_file_read_while_it_was_still_arriving_counts_once_it_is_complete(tmp_path):
    # git checks a file out by writing it in place, so a read can meet it empty or cut short
    folder = tmp_path / "settled"
    folder.mkdir()
    arriving = folder / "20261010T070000Z-000-aaaa-dismiss.yaml"
    arriving.write_text("", encoding="utf-8")
    store = SettledStore(folder, Clock())
    assert store.dismissed() == {}
    arriving.write_text(f"key: '{KEY}'\nact: dismiss\noutcome: done\ntitle: t\n", encoding="utf-8")
    assert KEY in store.dismissed()


def test_same_second_decisions_keep_their_order(tmp_path):
    clock = Clock()
    store = SettledStore(tmp_path / "settled", clock)
    for _ in range(3):
        store.dismiss(KEY, "done", "t")
        store.unsettle(KEY)
    assert store.dismissed() == {}
    store.dismiss(KEY, "not_doing", "t")
    assert store.dismissed()[KEY]["outcome"] == "not_doing"


# ---------------------------------------------------------------- WebStore: legacy, migration, undo

def test_without_a_shared_folder_webstore_is_what_it_was(tmp_path):
    store = WebStore(tmp_path, Clock())
    store.dismiss(KEY, "done", "t")
    store.hide("task:alpha", "2026-10-12")
    data = json.loads((tmp_path / "state.json").read_text())
    assert data["dismissed"][KEY]["outcome"] == "done" and data["hidden"] == {"task:alpha": "2026-10-12"}
    assert store.unhide(KEY) and KEY not in store.dismissed()


def test_legacy_entries_migrate_once_and_state_json_stays_untouched(tmp_path):
    state, folder, clock = tmp_path / "state", tmp_path / "work" / "cockpit" / "settled", Clock()
    before = legacy(state, hidden={"task:alpha": "2026-10-20"},
                    dismissed={KEY: {"outcome": "not_doing", "at": "2026-09-30", "title": "Fix the example issue"}},
                    pins=["task:alpha"])
    raw = (state / "state.json").read_text()
    store = WebStore(state, clock, settled_dir=folder)
    assert (state / "state.json").read_text() == raw and json.loads(raw) == before
    migrated = files(folder)
    assert len(migrated) == 2 and all("legacy" in name for name in migrated)
    fresh = SettledStore(folder, clock)                          # what another machine reads after a pull
    assert fresh.hidden(TODAY) == {"task:alpha": "2026-10-20"}
    assert fresh.dismissed() == {KEY: {"outcome": "not_doing", "at": "2026-09-30", "title": "Fix the example issue"}}
    WebStore(state, clock, settled_dir=folder)                   # a second start writes nothing new
    assert files(folder) == migrated
    assert store.home()["pins"] == ["task:alpha"]                # per-viewer conveniences stay in state.json


def test_two_machines_migrating_the_same_entry_write_the_same_file(tmp_path):
    entry = {KEY: {"outcome": "done", "at": "2026-09-30", "title": "Fix the example issue"}}
    legacy(tmp_path / "a", dismissed=entry)
    legacy(tmp_path / "b", dismissed=entry)
    WebStore(tmp_path / "a", Clock(), settled_dir=tmp_path / "sa")
    WebStore(tmp_path / "b", Clock(NOW + 60_000), settled_dir=tmp_path / "sb")
    assert files(tmp_path / "sa") == files(tmp_path / "sb")      # git sees one file added twice with one content


def test_a_key_the_shared_record_knows_is_not_migrated_again(tmp_path):
    # taken back on another machine; this machine's state.json still has the old dismissal
    state, folder = tmp_path / "state", tmp_path / "settled"
    legacy(state, dismissed={KEY: {"outcome": "done", "at": "2026-09-30", "title": "t"}})
    SettledStore(folder, Clock(NOW - 1000)).unsettle(KEY)
    store = WebStore(state, Clock(), settled_dir=folder)
    assert len(files(folder)) == 1
    assert KEY not in store.dismissed()                          # the shared record wins over the legacy key


def test_a_legacy_key_is_still_read_when_the_folder_cannot_be_written(tmp_path):
    state = tmp_path / "state"
    legacy(state, dismissed={KEY: {"outcome": "done", "at": "2026-09-30", "title": "t"}})
    blocker = tmp_path / "work"
    blocker.write_text("a file where the folder should be", encoding="utf-8")
    store = WebStore(state, Clock(), settled_dir=blocker / "cockpit" / "settled")
    assert KEY in store.dismissed()                              # nothing that was settled reappears


def test_webstore_writes_both_and_reads_the_merge(tmp_path):
    state, folder, clock = tmp_path / "state", tmp_path / "settled", Clock()
    store = WebStore(state, clock, settled_dir=folder)
    store.dismiss(KEY, "done", "Fix the example issue")
    store.hide("task:alpha", "2026-10-12")
    data = json.loads((state / "state.json").read_text())
    assert KEY in data["dismissed"] and data["hidden"] == {"task:alpha": "2026-10-12"}   # an older version still reads it
    other = WebStore(tmp_path / "other-state", Clock(), settled_dir=folder)            # another machine, empty state.json
    assert KEY in other.dismissed() and other.hidden() == {"task:alpha": "2026-10-12"}


def test_undo_on_one_machine_shows_the_row_again_on_the_other(tmp_path):
    folder = tmp_path / "settled"
    here = WebStore(tmp_path / "here", Clock(), settled_dir=folder)
    there = WebStore(tmp_path / "there", Clock(NOW + 1000), settled_dir=folder)
    here.dismiss(KEY, "not_doing", "Fix the example issue")
    assert KEY in there.dismissed()
    assert there.unhide(KEY)                                      # "show again" on the other machine
    assert KEY not in here.dismissed() and KEY not in there.dismissed()
    assert not there.unhide(KEY)                                  # nothing left to take back
    names = files(folder)
    assert len(names) == 2 and sum("unsettle" in n for n in names) == 1   # an undo is a record, nothing is deleted


def test_a_settled_row_survives_a_lost_state_json(tmp_path):
    state, folder = tmp_path / "state", tmp_path / "settled"
    WebStore(state, Clock(), settled_dir=folder).dismiss(KEY, "done", "t")
    shutil.rmtree(state)
    assert KEY in WebStore(state, Clock(), settled_dir=folder).dismissed()


def test_prune_keeps_the_shared_record_and_ends_a_hide_by_date(tmp_path):
    state, folder, clock = tmp_path / "state", tmp_path / "settled", Clock()
    store = WebStore(state, clock, settled_dir=folder)
    store.hide("task:alpha", "2026-10-12")
    written = files(folder)
    clock.days(2)
    store.prune()
    assert store.hidden() == {} and files(folder) == written


# ---------------------------------------------------------------- two writers through git

def git(cwd, *args):
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
    run = subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=cwd, env=env,
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    return run


def test_two_machines_settling_the_same_row_merge_without_a_conflict(tmp_path):
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    a, b = tmp_path / "a", tmp_path / "b"
    git(tmp_path, "clone", "-q", str(origin), str(a))
    (a / "README.md").write_text("x\n")
    git(a, "add", "-A"); git(a, "commit", "-q", "-m", "init"); git(a, "push", "-q", "origin", "HEAD:main")
    git(tmp_path, "clone", "-q", str(origin), str(b))
    # the same legacy entry on both machines, then each settles and takes back on its own
    entry = {KEY: {"outcome": "done", "at": "2026-09-30", "title": "Fix the example issue"}}
    legacy(tmp_path / "sa", dismissed=entry)
    legacy(tmp_path / "sb", dismissed=entry)
    sa = WebStore(tmp_path / "sa", Clock(), settled_dir=a / "work" / "cockpit" / "settled")
    sb = WebStore(tmp_path / "sb", Clock(NOW + 2000), settled_dir=b / "work" / "cockpit" / "settled")
    sa.hide("task:alpha", "2026-10-20")
    sb.unhide(KEY)
    sb.dismiss("task:beta", "not_doing", "Beta")
    git(a, "add", "work"); git(a, "commit", "-q", "-m", "a"); git(a, "push", "-q", "origin", "HEAD:main")
    git(b, "add", "work"); git(b, "commit", "-q", "-m", "b")
    git(b, "pull", "-q", "--rebase", "origin", "main")           # asserts returncode 0: no conflict
    git(b, "push", "-q", "origin", "HEAD:main")
    git(a, "pull", "-q", "--rebase", "origin", "main")
    for side in (sa, sb):
        assert side.hidden() == {"task:alpha": "2026-10-20"}
        assert set(side.dismissed()) == {"task:beta"}


# ---------------------------------------------------------------- the watcher sees a pull

def test_the_watcher_sees_a_new_decision(tmp_path):
    before = watch.snapshot(tmp_path)
    SettledStore(tmp_path / "work" / "cockpit" / "settled", Clock()).dismiss(KEY, "done", "t")
    after = watch.snapshot(tmp_path)
    assert after != before and str(tmp_path / "work" / "cockpit" / "settled") in after
