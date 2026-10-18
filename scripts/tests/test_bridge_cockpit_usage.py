# SPDX-License-Identifier: MIT
"""Contract for the token use of the last seven days (scripts/lib/bridge_cockpit/usage.py).

Claude Code writes every answer of the model into the transcript of its session
(~/.claude/projects/<slug>/<session>.jsonl, subagents in <session>/subagents/agent-*.jsonl), with the model
and `usage` (input, output, cache read, cache written). One answer can stand on several lines (one per content
block) with the same message id and request id: it counts once. `entrypoint` tells who asked: `cli` is a
session (a subagent when `isSidechain`), `sdk-*` a program (`claude -p`, a worker). Only measured counts,
no price. Reading is incremental: a file is read from where the last scan stopped.

Run: python3 -m pytest scripts/tests/test_bridge_cockpit_usage.py -q
"""
from __future__ import annotations

import datetime as dt
import json
import threading
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
if str(ROOT / "scripts" / "lib") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from bridge_cockpit import usage  # noqa: E402

NOW = dt.datetime(2026, 10, 13, 15, 0)


def line(day_offset=0, *, model="claude-opus-5-5", mid="m1", req="r1", out=100, inp=10, cr=1000, cw=50,
         entry="cli", side=False, cwd="/x/proj-a", hour=12):
    when = (NOW - dt.timedelta(days=day_offset)).replace(hour=hour).astimezone(dt.timezone.utc)
    return json.dumps({"type": "assistant", "timestamp": when.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                       "entrypoint": entry, "isSidechain": side, "cwd": cwd, "requestId": req,
                       "message": {"id": mid, "model": model,
                                   "usage": {"input_tokens": inp, "output_tokens": out,
                                             "cache_read_input_tokens": cr, "cache_creation_input_tokens": cw}}})


def write(base: Path, rel: str, lines: list[str]) -> Path:
    path = base / "projects" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for x in lines:
            f.write(x + "\n")
    return path


def scan(base: Path, u: usage.Usage | None = None) -> dict:
    u = u or usage.Usage(base=base, now=lambda: NOW)
    return u.view()


def test_an_answer_on_several_lines_counts_once(tmp_path):
    write(tmp_path, "p/s1.jsonl", [line(), line(), json.dumps({"type": "user", "message": {"content": "hi"}})])
    v = scan(tmp_path)
    today = v["days"][-1]
    assert today["day"] == "2026-10-13"
    assert today["sources"]["session"]["output"] == 100
    assert today["sources"]["session"]["input"] == 10
    assert today["sources"]["session"]["cache_read"] == 1000 and today["sources"]["session"]["cache_write"] == 50


def test_who_asked_decides_the_source(tmp_path):
    write(tmp_path, "p/s1.jsonl", [line(mid="a", out=1)])
    write(tmp_path, "p/s1/subagents/agent-x.jsonl", [line(mid="b", out=2, side=True)])
    write(tmp_path, "q/s2.jsonl", [line(mid="c", out=4, entry="sdk-cli")])
    src = scan(tmp_path)["days"][-1]["sources"]
    assert (src["session"]["output"], src["subagent"]["output"], src["worker"]["output"]) == (1, 2, 4)


def test_seven_days_oldest_first_and_older_answers_are_left_out(tmp_path):
    write(tmp_path, "p/s1.jsonl", [line(0, mid="a"), line(6, mid="b"), line(7, mid="c"), line(30, mid="d")])
    v = scan(tmp_path)
    assert [d["day"] for d in v["days"]] == [f"2026-10-{d:02d}" for d in range(7, 14)]
    assert v["days"][0]["output"] == 100 and v["days"][-1]["output"] == 100
    assert sum(d["output"] for d in v["days"]) == 200


def test_models_and_projects_of_the_week_largest_first(tmp_path):
    write(tmp_path, "p/s1.jsonl", [line(mid="a", out=10, cwd="/x/small"),
                                   line(1, mid="b", model="claude-sonnet-5-5", out=500, cwd="/x/big"),
                                   line(mid="c", model="<synthetic>", out=0)])
    v = scan(tmp_path)
    assert [m["model"] for m in v["models"]] == ["claude-sonnet-5-5", "claude-opus-5-5"]
    assert [p["project"] for p in v["projects"]] == ["big", "small"]
    # a day carries its own split, so a click on a day can show it
    assert v["days"][-1]["models"] == [{"model": "claude-opus-5-5", "output": 10}]
    assert v["days"][-2]["projects"] == [{"project": "big", "output": 500}]


def test_a_source_far_above_its_usual_day_is_named(tmp_path):
    usual = [line(d, mid=f"u{d}", out=20_000, entry="sdk-cli") for d in range(1, 7)]
    write(tmp_path, "w/s.jsonl", usual + [line(0, mid="today", out=200_000, entry="sdk-cli")])
    write(tmp_path, "p/s.jsonl", [line(d, mid=f"s{d}", out=20_000) for d in range(0, 7)])
    v = scan(tmp_path)
    assert v["outliers"] == [{"source": "worker", "today": 200_000, "usual": 20_000, "factor": 10.0}]


def test_a_small_day_is_no_outlier_even_when_it_is_many_times_the_usual(tmp_path):
    write(tmp_path, "w/s.jsonl", [line(d, mid=f"u{d}", out=100, entry="sdk-cli") for d in range(1, 7)]
          + [line(0, mid="t", out=5_000, entry="sdk-cli")])
    assert scan(tmp_path)["outliers"] == []


def test_reading_goes_on_where_it_stopped(tmp_path):
    u = usage.Usage(base=tmp_path, now=lambda: NOW)
    path = write(tmp_path, "p/s1.jsonl", [line(mid="a")])
    assert u.view()["days"][-1]["output"] == 100
    with path.open("a", encoding="utf-8") as f:
        f.write(line(mid="b", out=7) + "\n" + line(mid="c")[:30])   # the last line is still being written
    assert u.view()["days"][-1]["output"] == 107
    with path.open("a", encoding="utf-8") as f:
        f.write(line(mid="c", out=1)[30:] + "\n")
    assert u.view()["days"][-1]["output"] == 108


def test_a_broken_line_is_skipped_and_an_empty_home_is_an_empty_week(tmp_path):
    write(tmp_path, "p/s1.jsonl", ['{"usage": broken', line()])
    assert scan(tmp_path)["days"][-1]["output"] == 100
    v = scan(tmp_path / "nothing")
    assert len(v["days"]) == 7 and v["total"]["output"] == 0 and v["outliers"] == []


def test_a_transcript_larger_than_a_block_counts_as_if_read_whole(tmp_path, monkeypatch):
    # many answers, some of them on several lines, one line longer than a block on its own
    lines = [line(d % 7, mid=f"m{i}", out=i + 1, cwd=f"/x/p{i % 3}") for i, d in enumerate(range(40))]
    lines += [line(mid="m3", out=4, cwd="/x/p0"), line(mid="long", out=9, cwd="/x/" + "q" * 300)]
    path = write(tmp_path, "p/s1.jsonl", lines)
    whole = scan(tmp_path)
    monkeypatch.setattr(usage, "BLOCK", 64)
    u = usage.Usage(base=tmp_path, now=lambda: NOW)
    assert path.stat().st_size > 10 * usage.BLOCK
    assert u.view() == whole
    assert u.offsets[str(path)] == path.stat().st_size


def test_a_partial_last_line_across_blocks_is_picked_up_on_the_next_scan(tmp_path, monkeypatch):
    monkeypatch.setattr(usage, "BLOCK", 50)
    u = usage.Usage(base=tmp_path, now=lambda: NOW)
    path = write(tmp_path, "p/s1.jsonl", [line(mid="a")])
    tail = line(mid="b", out=7)
    with path.open("a", encoding="utf-8") as f:
        f.write(tail[:120])                       # longer than a block, still being written
    assert u.view()["days"][-1]["output"] == 100
    assert u.offsets[str(path)] == len(line(mid="a")) + 1
    with path.open("a", encoding="utf-8") as f:
        f.write(tail[120:] + "\n")
    assert u.view()["days"][-1]["output"] == 107


def test_the_offsets_of_a_deleted_transcript_are_dropped(tmp_path):
    u = usage.Usage(base=tmp_path, now=lambda: NOW)
    gone = write(tmp_path, "p/gone.jsonl", [line(mid="a")])
    kept = write(tmp_path, "p/kept.jsonl", [line(mid="b")])
    u.view()
    assert set(u.offsets) == {str(gone), str(kept)}
    gone.unlink()
    u.view()
    assert set(u.offsets) == {str(kept)}


def test_latest_never_scans_in_the_calling_thread_and_keeps_the_last_view(tmp_path):
    write(tmp_path, "p/s1.jsonl", [line()])
    clock = [0.0]
    u = usage.Usage(base=tmp_path, now=lambda: NOW, clock=lambda: clock[0])
    scans: list[int] = []
    real = u.scan

    def counted():
        scans.append(threading.get_ident())
        real()
    u.scan = counted
    assert u.latest() is None                     # nothing known yet: the first scan runs on its own thread
    u.join()
    assert threading.get_ident() not in scans and len(scans) == 1
    first = u.latest()
    assert first["days"][-1]["output"] == 100
    clock[0] += usage.MAX_AGE - 1                 # still fresh: no new scan
    assert u.latest() is first
    assert len(scans) == 1
    clock[0] += 2                                 # stale: the last view still answers, a new scan starts
    assert u.latest() is first
    u.join()
    assert len(scans) == 2 and threading.get_ident() not in scans
