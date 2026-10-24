# SPDX-License-Identifier: MIT
"""Contract for the cockpit watcher (scripts/lib/bridge_cockpit/watch.py).

The watcher compares mtimes of the work tree, debounces a change into one `delta` pass,
runs one `full` pass plus a history prune at local midnight, and keeps its loop alive
when one iteration raises. Hermetic: a fake app (clock, collector spy, store spy) and a
temporary root, the scan time is passed in, no server and no real wait beyond the loop's own.

Run: pytest -q scripts/tests/test_bridge_cockpit_watch.py
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from lib.bridge_cockpit import watch  # noqa: E402


def local_ms(y: int, mo: int, d: int, h: int, mi: int) -> float:
    """Epoch ms of a local wall-clock time, the way model.iso_date reads it back."""
    return dt.datetime(y, mo, d, h, mi).timestamp() * 1000


class Collector:
    def __init__(self) -> None:
        self.requests: list[str] = []
        self.ticks = 0

    def request(self, kind: str) -> None:
        self.requests.append(kind)

    def tick(self, clients: int) -> None:
        self.ticks += 1


class Store:
    def __init__(self) -> None:
        self.prunes = 0

    def prune(self) -> None:
        self.prunes += 1


class Relay:
    def cleanup(self) -> None:
        pass


class FakeApp:
    def __init__(self, root: Path, now_ms: float) -> None:
        self.root = root
        self.now_ms = now_ms
        self.collector = Collector()
        self.store = Store()
        self.relay = Relay()
        self.errors: list[str] = []
        self.relay_scans = 0

    def clock(self) -> float:
        return self.now_ms

    def relay_scan(self) -> None:
        self.relay_scans += 1

    def client_count(self) -> int:
        return 0

    def write_server_json(self) -> None:
        pass

    def log_error(self, text: str) -> None:
        self.errors.append(text)


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    item = tmp_path / "work" / "inbox" / "20261018-0900-sample-0001"
    (item / "events").mkdir(parents=True)
    (item / "item.yaml").write_text("title: sample\n", encoding="utf-8")
    (tmp_path / "work" / "tasks").mkdir()
    (tmp_path / "work" / "log.md").write_text("# log\n", encoding="utf-8")
    return tmp_path


def touch(path: Path, step: int) -> None:
    """Move an mtime by a fixed amount, independent of the file system's clock resolution."""
    st = os.stat(path)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + step * 1_000_000_000))


def item_yaml(root: Path) -> Path:
    return root / "work" / "inbox" / "20261018-0900-sample-0001" / "item.yaml"


def test_snapshot_covers_inbox_items_tasks_and_log(tree: Path) -> None:
    snap = watch.snapshot(tree)
    assert str(item_yaml(tree)) in snap
    assert str(tree / "work" / "log.md") in snap
    assert str(tree / "work" / "tasks") in snap


def test_one_change_yields_one_delta_not_before_the_debounce(tree: Path) -> None:
    app = FakeApp(tree, local_ms(2026, 10, 18, 12, 0))
    w = watch.Watcher(app)
    assert w.check(100.0) is False
    touch(item_yaml(tree), 1)
    assert w.check(101.0) is False
    assert w.check(101.0 + watch.DEBOUNCE_S - 0.01) is False
    assert app.collector.requests == []
    assert w.check(101.0 + watch.DEBOUNCE_S) is True
    assert app.collector.requests == ["delta"]
    assert w.check(110.0) is False
    assert app.collector.requests == ["delta"]


def test_changes_inside_the_window_yield_one_delta_timed_from_the_last(tree: Path) -> None:
    app = FakeApp(tree, local_ms(2026, 10, 18, 12, 0))
    w = watch.Watcher(app)
    touch(item_yaml(tree), 1)
    assert w.check(100.0) is False
    touch(item_yaml(tree), 2)
    assert w.check(102.0) is False
    touch(tree / "work" / "log.md", 1)
    assert w.check(104.0) is False
    # the first change's deadline (103.0) has passed, the last one's (107.0) has not
    assert w.check(104.0 + watch.DEBOUNCE_S - 0.01) is False
    assert app.collector.requests == []
    assert w.check(104.0 + watch.DEBOUNCE_S) is True
    assert w.check(120.0) is False
    assert app.collector.requests == ["delta"]


def test_midnight_prunes_and_requests_full_once(tree: Path) -> None:
    app = FakeApp(tree, local_ms(2026, 10, 18, 23, 59))
    w = watch.Watcher(app)
    assert w.midnight() is False
    app.now_ms = local_ms(2026, 10, 19, 0, 1)
    assert w.midnight() is True
    assert app.store.prunes == 1
    assert app.collector.requests == ["full"]
    app.now_ms = local_ms(2026, 10, 19, 0, 3)
    assert w.midnight() is False
    assert w.check(200.0) is False
    assert app.store.prunes == 1
    assert app.collector.requests == ["full"]


def test_loop_logs_a_failed_iteration_and_continues(tree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(watch, "RELAY_SCAN_S", 0.0)
    app = FakeApp(tree, local_ms(2026, 10, 18, 12, 0))
    w = watch.Watcher(app)
    survived = threading.Event()

    def relay_scan() -> None:
        app.relay_scans += 1
        if app.relay_scans == 1:
            raise RuntimeError("boom in one iteration")
        survived.set()
        w.shutdown()

    app.relay_scan = relay_scan
    thread = threading.Thread(target=w.loop, daemon=True)
    thread.start()
    assert survived.wait(5.0), "the loop did not reach a second iteration"
    thread.join(5.0)
    assert not thread.is_alive()
    assert len(app.errors) == 1
    assert "watch step relay_scan failed" in app.errors[0]
    assert "boom in one iteration" in app.errors[0]


# ---------------------------------------------------------------- #386

class HoldingCollector(Collector):
    """A collector that still holds watched deltas for `hold` ms (a pass that took that long just ended)."""

    def __init__(self, hold: float) -> None:
        super().__init__()
        self.hold = hold

    def delta_hold_ms(self) -> float:
        return self.hold


def test_a_watched_delta_waits_out_the_hold_of_the_last_pass(tree: Path) -> None:
    app = FakeApp(tree, local_ms(2026, 10, 18, 12, 0))
    app.collector = HoldingCollector(2500.0)
    w = watch.Watcher(app)
    touch(item_yaml(tree), 1)
    w.check(100.0)
    assert w.check(100.0 + watch.DEBOUNCE_S) is False
    app.collector.hold = 0.0
    assert w.check(100.0 + watch.DEBOUNCE_S + 2.49) is False      # pushed by the hold it saw
    assert w.check(100.0 + watch.DEBOUNCE_S + 2.5) is True
    assert app.collector.requests == ["delta"]



def test_a_step_that_raises_does_not_take_the_others_with_it(tree: Path) -> None:
    # review C28: one try around all steps meant a failing relay scan skipped the pass, the cleanup
    # and server.json in the same turn
    app = FakeApp(tree, local_ms(2026, 10, 18, 12, 0))
    written = []
    app.relay_scan = lambda: (_ for _ in ()).throw(RuntimeError("relay broke"))
    app.write_server_json = lambda: written.append(1)
    w = watch.Watcher(app)
    w.step(1000.0)
    assert app.collector.ticks == 1 and written == [1]
    assert len(app.errors) == 1 and "relay_scan" in app.errors[0] and "relay broke" in app.errors[0]


def test_the_same_failing_step_is_logged_at_most_once_a_minute(tree: Path) -> None:
    app = FakeApp(tree, local_ms(2026, 10, 18, 12, 0))
    app.relay_scan = lambda: (_ for _ in ()).throw(RuntimeError("relay broke"))
    w = watch.Watcher(app)
    for t in (1000.0, 1010.0, 1030.0):
        w.step(t)
    assert len(app.errors) == 1
    w.step(1000.0 + watch.ERROR_EVERY_S)
    assert len(app.errors) == 2
