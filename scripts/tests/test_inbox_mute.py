# SPDX-License-Identifier: MIT
"""Contract for dropping with a reason, mute rules and the noise of a source (scripts/inbox.py).

What this file holds the inbox to:

* a drop may say why (`once`, `duplicate`, `family`, `source`); the reason is part of the event;
* `family` and `source` leave a mute rule behind, one file of its own under `work/inbox/_mutes/`,
  so two machines never write the same file and the rule travels with `inbox.py sync`;
* a muted finding is still filed and dropped at once by `mute`: nothing is lost, it counts in the
  noise and a reopen brings it back;
* an item filed as `now` is never muted: a source that was too loud must not swallow an outage;
* a source mute ends by itself after `MUTE_SOURCE_DAYS`, a family mute stays until it is lifted;
* `stats` counts per source what was filed and what a person dropped, so the loud filer is visible.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "inbox.py"

spec = importlib.util.spec_from_file_location("inbox", SCRIPT)
assert spec is not None and spec.loader is not None
inbox = importlib.util.module_from_spec(spec)
sys.modules["inbox"] = inbox
sys.dont_write_bytecode = True
spec.loader.exec_module(inbox)

NOW = dt.datetime(2026, 10, 17, 18, 0)


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture()
def clock():
    return Clock(NOW)


@pytest.fixture()
def box(tmp_path, clock):
    return inbox.Inbox(tmp_path / "work" / "inbox", actor="laptop", clock=clock)


def finding(box, **kw):
    base = dict(source="mini/daily-health", kind="finding", summary="1 crash in 24h", closer="reporter")
    base.update(kw)
    return box.add(**base)


# ---------------------------------------------------------------- the reason

def test_a_drop_records_its_reason(box):
    item_id = finding(box, key="mini-health:crash:aa")
    assert box.drop(item_id, note="not worth it", reason="once") is None
    item = box.get(item_id)
    assert item.state == "dropped"
    last = item.events[-1]
    assert last.verb == "drop" and last.data["reason"] == "once" and last.data["text"] == "not worth it"


def test_an_unknown_reason_is_refused_and_nothing_is_written(box):
    item_id = finding(box)
    with pytest.raises(ValueError):
        box.drop(item_id, reason="annoying")
    assert box.get(item_id).state == "open"


def test_once_and_duplicate_leave_no_rule(box):
    for reason in ("once", "duplicate"):
        box.drop(finding(box, summary=reason), reason=reason)
    assert box.mutes() == []


# ---------------------------------------------------------------- the rules

def test_family_mutes_the_key_family_of_the_same_source(box):
    first = finding(box, key="mini-health:crash:aa")
    rule = box.drop(first, reason="family")
    assert rule is not None
    [r] = box.mutes()
    assert r["id"] == rule and r["source"] == "mini/daily-health" and r["key_prefix"] == "mini-health:crash:"
    assert r.get("until") is None and r["from_item"] == first
    again = finding(box, key="mini-health:crash:bb", summary="another crash")
    assert again != first
    item = box.get(again)
    assert item.state == "dropped"
    assert item.events[-1].by == "mute" and item.events[-1].data["rule"] == rule
    # the same family from another source is not touched
    other = finding(box, source="laptop/daily-health", key="mini-health:crash:cc")
    assert box.get(other).state == "open"
    # nor is another family of the same source
    assert box.get(finding(box, key="mini-health:disk:full")).state == "open"


def test_family_without_a_key_family_mutes_the_kind_of_that_source(box):
    first = finding(box, key="plain-key")
    box.drop(first, reason="family")
    [r] = box.mutes()
    assert "key_prefix" not in r and r["kind"] == "finding"
    assert box.get(finding(box, summary="something else")).state == "dropped"
    assert box.get(finding(box, kind="question", summary="a question")).state == "open"


def test_source_mutes_everything_of_the_source_for_a_while(box, clock):
    box.drop(finding(box), reason="source")
    [r] = box.mutes()
    assert r["until"] == (NOW.date() + dt.timedelta(days=inbox.MUTE_SOURCE_DAYS)).isoformat()
    assert box.get(finding(box, kind="idea", summary="an idea")).state == "dropped"
    clock.now = NOW + dt.timedelta(days=inbox.MUTE_SOURCE_DAYS + 1)
    assert box.mutes() == []
    assert box.get(finding(box, kind="idea", summary="later idea")).state == "open"


def test_now_is_never_muted(box):
    box.drop(finding(box), reason="source")
    assert box.get(finding(box, summary="disk full", urgency="now")).state == "open"


def test_a_muted_key_stays_one_item(box):
    box.drop(finding(box, key="notify:aa"), reason="family")
    muted = finding(box, key="notify:bb")
    assert finding(box, key="notify:bb") == muted


def test_unmute_lifts_the_rule(box):
    rule = box.drop(finding(box, key="a:b"), reason="family")
    box.unmute(rule)
    assert box.mutes() == []
    assert box.get(finding(box, key="a:c")).state == "open"
    with pytest.raises(KeyError):
        box.unmute(rule)


def test_rules_are_files_of_their_own_and_not_items(box):
    box.drop(finding(box, key="a:b"), reason="family")
    box.drop(finding(box, source="other", key="c:d"), reason="family")
    files = sorted((box.root / inbox.MUTES_DIR).glob("*.yaml"))
    assert len(files) == 2
    assert all(i.id != inbox.MUTES_DIR for i in box.items())
    assert box.validate() == []


def test_a_broken_rule_file_is_skipped_and_reported(box):
    rule_dir = box.root / inbox.MUTES_DIR
    rule_dir.mkdir(parents=True)
    (rule_dir / "broken.yaml").write_text("source: [", encoding="utf-8")
    (rule_dir / "empty.yaml").write_text("{}", encoding="utf-8")
    assert box.mutes() == []
    assert box.get(finding(box)).state == "open"
    problems = box.validate()
    assert any("broken.yaml" in p for p in problems) and any("empty.yaml" in p for p in problems)


def test_a_reopen_brings_a_muted_item_back(box):
    box.drop(finding(box, key="a:b"), reason="family")
    muted = finding(box, key="a:c")
    box.reopen(muted)
    assert box.get(muted).state == "open"


# ---------------------------------------------------------------- the noise

def test_stats_count_what_a_person_dropped_per_source(box, clock):
    for n in range(4):
        item_id = finding(box, summary=f"crash {n}")
        if n < 3:
            box.drop(item_id, reason="once" if n else "duplicate")
    kept = box.add(source="radar", kind="decision", summary="merge PR")
    box.close(kept)
    old = Clock(NOW - dt.timedelta(days=40))
    inbox.Inbox(box.root, actor="laptop", clock=old).add(source="radar", kind="idea", summary="ancient")
    rows = {r["source"]: r for r in box.stats(days=30)}
    loud = rows["mini/daily-health"]
    assert (loud["filed"], loud["dropped"], loud["muted"], loud["done"], loud["open"]) == (4, 3, 0, 0, 1)
    assert loud["share"] == 0.75 and loud["reasons"] == {"duplicate": 1, "once": 2}
    assert rows["radar"]["filed"] == 1 and rows["radar"]["dropped"] == 0
    assert [r["source"] for r in box.stats(days=30)][0] == "mini/daily-health"


def test_stats_count_a_muted_item_apart_from_a_person_dropping_it(box):
    box.drop(finding(box, key="a:b"), reason="family")
    finding(box, key="a:c")
    [row] = box.stats(days=30)
    assert (row["filed"], row["dropped"], row["muted"]) == (2, 1, 1)
    assert row["share"] == 0.5


def test_a_drop_without_a_reason_counts_as_unknown(box):
    box.event(finding(box), "drop", text="old cockpit")
    [row] = box.stats(days=30)
    assert row["reasons"] == {"unknown": 1}


# ---------------------------------------------------------------- the command line

def run(tmp_path, *args):
    return subprocess.run([sys.executable, str(SCRIPT), "--root", str(tmp_path), "--by", "laptop", *args],
                          capture_output=True, text=True, timeout=30)


def test_cli_drop_with_reason_mute_list_unmute_and_stats(tmp_path):
    added = run(tmp_path, "add", "--from", "mini/daily-health", "--kind", "finding", "--summary", "crash",
                "--key", "mini-health:crash:aa", "--closer", "reporter")
    item_id = added.stdout.strip()
    done = run(tmp_path, "drop", item_id, "--reason", "family", "--note", "apple crash")
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith("muted ")
    listed = json.loads(run(tmp_path, "mute", "list", "--json").stdout)
    assert [r["key_prefix"] for r in listed] == ["mini-health:crash:"]
    stats = json.loads(run(tmp_path, "stats", "--days", "30", "--json").stdout)
    assert stats[0]["source"] == "mini/daily-health" and stats[0]["dropped"] == 1
    assert run(tmp_path, "unmute", listed[0]["id"]).returncode == 0
    assert json.loads(run(tmp_path, "mute", "list", "--json").stdout) == []
    bad = run(tmp_path, "drop", item_id, "--reason", "annoying")
    assert bad.returncode != 0


def test_cli_drop_without_reason_still_works(tmp_path):
    item_id = run(tmp_path, "add", "--from", "x", "--kind", "idea", "--summary", "y").stdout.strip()
    assert run(tmp_path, "drop", item_id, "--note", "old way").returncode == 0
    data = yaml.safe_load(next((tmp_path / "work" / "inbox" / item_id / "events").glob("*.yaml")).read_text())
    assert data["verb"] == "drop" and "reason" not in data
