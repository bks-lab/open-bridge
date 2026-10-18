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
import subprocess
import sys
import threading
import types
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


# ---- Bridges, history, other machines -------------------------------------------------------------------

def bridge_root(tmp: Path, instances: dict[str, str] | None = None, remotes: dict[str, str] | None = None,
                config: str = "") -> Path:
    root = tmp / "bridge"
    (root / "infra" / "instances").mkdir(parents=True)
    (root / "infra" / "remotes").mkdir(parents=True)
    (root / "infra" / "instances" / "_template.yaml").write_text("name: tpl\nlocation: {path: /x}\n")
    for slug, text in (instances or {}).items():
        (root / "infra" / "instances" / f"{slug}.yaml").write_text(text)
    for slug, text in (remotes or {}).items():
        (root / "infra" / "remotes" / f"{slug}.yaml").write_text(text)
    if config:
        (root / "bridge-config.yaml").write_text(config)
    return root


def make(tmp: Path, root: Path | None = None, now=NOW, **kw) -> usage.Usage:
    return usage.Usage(base=tmp, now=lambda: now, root=root, host=kw.pop("host", "my-laptop"), **kw)


def test_bridges_read_from_instances_skip_templates_and_empty_paths(tmp_path):
    root = bridge_root(tmp_path, {"alpha": "name: Alpha\nlocation: {path: /w/alpha}\n",
                                  "beta": "location: {path: /w/alpha/beta}\n",
                                  "nopath": "name: N\nlocation: {host: my-server}\n"})
    got = {name: path for path, name in usage.bridges(root)}
    assert got == {"Alpha": "/w/alpha", "beta": "/w/alpha/beta"}


def test_a_record_belongs_to_the_longest_matching_bridge_on_a_path_boundary(tmp_path):
    root = bridge_root(tmp_path, {"alpha": "name: Alpha\nlocation: {path: /w/alpha}\n",
                                  "beta": "name: Beta\nlocation: {path: /w/alpha/beta}\n"})
    write(tmp_path, "p/s.jsonl", [line(mid="a", out=1, cwd="/w/alpha/work"),
                                  line(mid="b", out=2, cwd="/w/alpha/beta/x"),
                                  line(mid="c", out=4, cwd="/w/alphabet"),     # no boundary: no Bridge
                                  line(mid="d", out=8, cwd="/elsewhere")])
    v = make(tmp_path, root).view()
    rows = {(b["bridge"], b["host"]): b["output"] for b in v["bridges"]}
    assert rows == {("Alpha", "my-laptop"): 1, ("Beta", "my-laptop"): 2, (None, "my-laptop"): 12}
    assert v["days"][-1]["bridges"][0] == {"bridge": None, "host": "my-laptop", "output": 12}


def test_without_root_there_is_no_bridge_and_no_history_file(tmp_path):
    write(tmp_path, "p/s.jsonl", [line(1, mid="a")])
    v = usage.Usage(base=tmp_path, now=lambda: NOW).view()
    assert [b["bridge"] for b in v["bridges"]] == [None]
    assert v["range"] == 7 and v["hosts"][0]["local"] is True
    assert not list(tmp_path.rglob("usage-days.json"))


def test_the_existing_keys_keep_their_shape(tmp_path):
    write(tmp_path, "p/s.jsonl", [line()])
    v = make(tmp_path, bridge_root(tmp_path)).view()
    assert {"days", "total", "models", "projects", "outliers", "range", "at", "host", "bridges", "hosts"} <= set(v)
    d = v["days"][-1]
    assert set(d) == {"day", "sources", "output", "models", "projects", "bridges"}
    assert set(d["sources"]) == set(usage.SOURCES) and d["output"] == 100
    b = v["bridges"][0]
    assert set(b) == {"bridge", "host", "output", "all", "models", "days"}
    assert b["all"] == 10 + 100 + 1000 + 50 and len(b["days"]) == 7 and b["days"][-1] == 100
    assert b["models"] == [{"model": "claude-opus-5-5", "output": 100}]


def store_of(root: Path) -> dict:
    return json.loads((root / ".bridge" / "resources" / "usage-days.json").read_text())


def test_closed_days_go_to_the_store_today_does_not(tmp_path):
    root = bridge_root(tmp_path, {"alpha": "name: Alpha\nlocation: {path: /x}\n"})
    write(tmp_path, "p/s.jsonl", [line(0, mid="t"), line(1, mid="y", out=5), line(1, mid="z", out=6, side=True)])
    make(tmp_path, root).view()
    s = store_of(root)
    assert s["schema"] == 1 and s["host"] == "my-laptop"
    assert list(s["days"]) == ["2026-10-12"]
    assert sorted(s["days"]["2026-10-12"]) == [["session", "claude-opus-5-5", "proj-a", "Alpha", 10, 5, 1000, 50],
                                               ["subagent", "claude-opus-5-5", "proj-a", "Alpha", 10, 6, 1000, 50]]
    assert not list((root / ".bridge" / "resources").glob(".*tmp"))     # written atomically, no leftover


def test_ranges_30_and_90_read_older_days_from_the_store(tmp_path):
    root = bridge_root(tmp_path)
    old = {"2026-09-20": [["worker", "m-old", "p", None, 1, 70, 0, 0]],     # 23 days back: in 30 and 90
           "2026-07-20": [["session", "m-old", "p", "B", 1, 9, 0, 0]],       # 85 days back: only in 90
           "2026-05-01": [["session", "m-old", "p", None, 1, 1, 0, 0]]}      # older than 120 days: pruned
    (root / ".bridge" / "resources").mkdir(parents=True)
    (root / ".bridge" / "resources" / "usage-days.json").write_text(json.dumps({"schema": 1, "host": "my-laptop", "days": old}))
    write(tmp_path, "p/s.jsonl", [line()])
    u = make(tmp_path, root)
    v7, v30, v90 = u.view(), u.view(days=30), u.view(days=90)
    assert (len(v7["days"]), len(v30["days"]), len(v90["days"])) == (7, 30, 90)
    assert (v7["total"]["output"], v30["total"]["output"], v90["total"]["output"]) == (100, 170, 179)
    assert v30["range"] == 30 and v90["days"][0]["day"] == "2026-07-16"
    assert "2026-05-01" not in store_of(root)["days"] and "2026-07-20" in store_of(root)["days"]
    assert {m["model"] for m in v90["models"]} == {"claude-opus-5-5", "m-old"}


def test_a_stored_day_is_replaced_only_while_it_is_in_the_scan_window(tmp_path):
    root = bridge_root(tmp_path)
    (root / ".bridge" / "resources").mkdir(parents=True)
    (root / ".bridge" / "resources" / "usage-days.json").write_text(json.dumps({"schema": 1, "host": "my-laptop", "days": {
        "2026-10-10": [["session", "stale", "p", None, 0, 999, 0, 0]],      # in the window: the scan wins
        "2026-10-01": [["session", "kept", "p", None, 0, 33, 0, 0]]}}))     # out of it: kept as stored
    write(tmp_path, "p/s.jsonl", [line(3, mid="a", out=4)])
    v = make(tmp_path, root).view(days=30)
    days = store_of(root)["days"]
    assert days["2026-10-10"] == [["session", "claude-opus-5-5", "proj-a", None, 10, 4, 1000, 50]]
    assert days["2026-10-01"] == [["session", "kept", "p", None, 0, 33, 0, 0]]
    assert v["total"]["output"] == 37


def test_a_range_outside_the_allowed_clamps_to_the_nearest():
    assert [usage.clamp_range(x) for x in (None, 7, 1, 20, 30, 59, 61, 90, 400, "x", "30")] == \
        [7, 7, 7, 30, 30, 30, 90, 90, 90, 7, 30]


# ---- other machines --------------------------------------------------------------------------------------

def export_doc(host="my-server", rows=None, at="2026-10-13T06:00:00+02:00"):
    return {"schema": 1, "kind": "usage-export", "host": host, "at": at, "days": [], "range": 90,
            "rows": rows if rows is not None else {"2026-10-13": [["worker", "claude-haiku-5-5", "svc", "Remote", 1, 40, 2, 3]],
                                                   "2026-10-12": [["session", "claude-opus-5-5", "svc", "Remote", 0, 2, 0, 0]],
                                                   "2026-08-01": [["session", "claude-opus-5-5", "svc", "Remote", 0, 500, 0, 0]]}}


class FakeSSH:
    def __init__(self, answers: dict[str, object]):
        self.answers, self.calls = answers, []

    def __call__(self, argv, **kw):
        self.calls.append((argv, kw))
        host = argv[argv.index("ConnectTimeout=5") + 1]
        got = self.answers.get(host)
        if isinstance(got, dict):
            return types.SimpleNamespace(returncode=0, stdout=json.dumps(got), stderr="")
        return types.SimpleNamespace(returncode=255, stdout="", stderr=f"ssh: connect to host {host}: timed out\n")


def test_remote_hosts_come_from_instances_with_a_remote_file_and_never_the_local_host(tmp_path):
    root = bridge_root(tmp_path,
                       {"a": "location: {path: /x, host: my-server}\n",
                        "b": "location: {path: /y, host: no-file}\n",              # no infra/remotes file: skipped
                        "c": "location: {path: /z, host: home-box}\n",             # the local machine by its hostname
                        "d": "location: {path: /q, host: my-server}\n"},           # counted once
                       {"my-server": "name: my-server\n",
                        "home-box": "name: home-box\nnetwork: {hostname: My-Laptop.local}\n"})
    hosts, remote_file = usage.remote_hosts(root, "my-laptop")
    assert hosts == ["my-server"] and remote_file == "~/.bridge/resources/usage.json"


def test_config_names_the_remotes_and_the_remote_file(tmp_path):
    root = bridge_root(tmp_path, {"a": "location: {path: /x, host: my-server}\n"}, {"my-server": "name: s\n"},
                       config="cockpit:\n  usage:\n    remotes: [build-box, my-laptop]\n    remote_file: /data/usage.json\n")
    assert usage.remote_hosts(root, "my-laptop") == (["build-box"], "/data/usage.json")


def test_remote_rows_add_into_days_total_and_bridges_and_hosts_say_who_answered(tmp_path):
    root = bridge_root(tmp_path, config="cockpit:\n  usage:\n    remotes: [my-server, gone-box]\n")
    write(tmp_path, "p/s.jsonl", [line(mid="a")])
    ssh = FakeSSH({"my-server": export_doc()})
    u = make(tmp_path, root, run=ssh)
    u.refresh_remotes()
    v = u.view()
    argv, kw = ssh.calls[0]
    assert argv[:5] == ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5"] and kw["timeout"] == 15
    assert argv[-1] == "cat ~/.bridge/resources/usage.json"
    assert v["days"][-1]["output"] == 140 and v["days"][-1]["sources"]["worker"]["output"] == 40
    assert v["total"]["output"] == 142                      # the remote day from August is outside 7 days
    rows = {(b["bridge"], b["host"]): b for b in v["bridges"]}
    assert rows[("Remote", "my-server")]["output"] == 42 and rows[("Remote", "my-server")]["all"] == 48
    assert rows[("Remote", "my-server")]["days"][-2:] == [2, 40]
    assert {"bridge": "Remote", "host": "my-server", "output": 40} in v["days"][-1]["bridges"]
    assert v["hosts"][0] == {"host": "my-laptop", "ok": True, "error": None, "at": v["at"], "local": True}
    assert v["hosts"][1] == {"host": "my-server", "ok": True, "error": None, "at": "2026-10-13T06:00:00+02:00", "local": False}
    gone = v["hosts"][2]
    assert gone["host"] == "gone-box" and gone["ok"] is False and "timed out" in gone["error"] and gone["local"] is False
    assert v["outliers"] == []                              # outliers stay on local data


def test_remote_reads_are_cached_and_a_failure_never_breaks_the_local_view(tmp_path):
    root = bridge_root(tmp_path, config="cockpit:\n  usage:\n    remotes: [my-server]\n")
    write(tmp_path, "p/s.jsonl", [line(mid="a")])
    clock = [0.0]

    def broken(argv, **kw):
        raise subprocess.TimeoutExpired(argv, 15)
    ssh = FakeSSH({"my-server": export_doc()})
    u = make(tmp_path, root, run=ssh, clock=lambda: clock[0])
    u.refresh_remotes()
    u.refresh_remotes()
    assert len(ssh.calls) == 1                              # within ten minutes: the cache answers
    clock[0] += usage.REMOTE_TTL + 1
    u.run = broken
    u.refresh_remotes()
    v = u.view()
    assert v["days"][-1]["output"] == 100 and v["hosts"][1]["ok"] is False


def test_view_on_a_request_never_reads_remotes_itself(tmp_path):
    root = bridge_root(tmp_path, config="cockpit:\n  usage:\n    remotes: [my-server]\n")
    seen: list[int] = []

    def ssh(argv, **kw):
        seen.append(threading.get_ident())
        return FakeSSH({"my-server": export_doc()})(argv, **kw)
    u = make(tmp_path, root, run=ssh)
    v = u.view()                                            # nothing read yet: listed, not reachable yet
    assert v["hosts"][1]["host"] == "my-server" and v["hosts"][1]["ok"] is False
    u.join()
    assert seen and threading.get_ident() not in seen
    assert u.view()["hosts"][1]["ok"] is True


def test_an_export_never_reads_remotes_and_carries_its_rows(tmp_path):
    root = bridge_root(tmp_path, config="cockpit:\n  usage:\n    remotes: [my-server]\n")
    write(tmp_path, "p/s.jsonl", [line(mid="a"), line(2, mid="b", out=3)])

    def ssh(argv, **kw):
        raise AssertionError("an export must not follow remotes")
    u = make(tmp_path, root, run=ssh, remotes=False)
    doc = u.export(days=90)
    u.join()
    assert doc["schema"] == 1 and doc["kind"] == "usage-export" and doc["host"] == "my-laptop"
    assert doc["range"] == 90 and len(doc["days"]) == 90 and [h["host"] for h in doc["hosts"]] == ["my-laptop"]
    assert doc["rows"]["2026-10-13"] == [["session", "claude-opus-5-5", "proj-a", None, 10, 100, 1000, 50]]
    assert doc["rows"]["2026-10-11"][0][5] == 3


# ---- review findings -----------------------------------------------------------------------------------

def test_an_unreadable_store_is_kept_aside_never_overwritten_with_the_window(tmp_path):
    root = bridge_root(tmp_path)
    res = root / ".bridge" / "resources"
    res.mkdir(parents=True)
    (res / "usage-days.json").write_text('{"schema": 1, "host": "my-laptop", "days": {"2026-09-01": [["sess')  # cut off
    write(tmp_path, "p/s.jsonl", [line(1, mid="y", out=5)])
    make(tmp_path, root).view()
    aside = list(res.glob("usage-days.json.bad*"))
    assert len(aside) == 1 and aside[0].read_text().endswith('[["sess')        # the history is still there
    assert list(store_of(root)["days"]) == ["2026-10-12"]


def test_two_writers_never_share_a_temp_file(tmp_path, monkeypatch):
    root = bridge_root(tmp_path)
    write(tmp_path, "p/s.jsonl", [line(1, mid="y", out=5)])
    names = []
    real = usage.os.replace

    def spy(src, dst):
        names.append(Path(src).name)
        return real(src, dst)
    monkeypatch.setattr(usage.os, "replace", spy)
    make(tmp_path, root).view()
    write(tmp_path, "p/t.jsonl", [line(2, mid="z", out=6)])
    make(tmp_path, root).view()
    assert len(names) == 2 and names[0] != names[1] and all(n.startswith(".usage-days.json.") for n in names)
    assert not list((root / ".bridge" / "resources").glob(".*tmp*"))


def test_a_machine_not_read_yet_is_pending_not_unreachable(tmp_path):
    root = bridge_root(tmp_path, config="cockpit:\n  usage:\n    remotes: [my-server]\n")
    u = make(tmp_path, root, run=FakeSSH({"my-server": export_doc()}))
    first = u.view()["hosts"][1]
    assert first == {"host": "my-server", "ok": False, "pending": True, "error": None, "at": None, "local": False}
    u.join()
    assert u.view()["hosts"][1]["ok"] is True and "pending" not in u.view()["hosts"][1]


def test_the_local_machine_is_named_by_its_remotes_slug_found_through_any_of_its_names(tmp_path):
    root = bridge_root(tmp_path, {}, {"my-laptop": "name: my-laptop\nhostname: \"Laptop-Bonjour-2\"\n",
                                      "my-server": "name: my-server\n"})
    # `hostname` gives a router's name; the Bonjour name (LocalHostName) is the one the remotes file holds
    sh = lambda argv, **kw: types.SimpleNamespace(returncode=0, stdout="Laptop-Bonjour-2\n", stderr="")
    assert usage.local_host(root, gethostname=lambda: "Mac.fritz.box", run=sh) == "my-laptop"
    # no remotes file matches: the short hostname, lowercase
    nobody = lambda argv, **kw: types.SimpleNamespace(returncode=1, stdout="", stderr="")
    assert usage.local_host(root, gethostname=lambda: "Box.lan", run=nobody) == "box"


def test_config_names_the_local_machine(tmp_path):
    root = bridge_root(tmp_path, {}, {"my-laptop": "name: my-laptop\n"}, config="cockpit:\n  usage:\n    host: my-laptop\n")
    assert usage.local_host(root, gethostname=lambda: "Mac", run=lambda *a, **k: None) == "my-laptop"
    assert usage.Usage(base=tmp_path / "claude", root=root).host == "my-laptop"
