# SPDX-License-Identifier: MIT
"""Contract for a live session's task, recognised from the end of its own transcript (sessions.py infer).

A Claude session in a tab that names exactly one open task, again and again at the end of its transcript, works on
it: the Sessions state says so (`task`, `task_how: "seen"`, `task_since_ms`) without anybody linking it, and Work
through shows it under Running now. Only the slug and the sign leave the server, never a word of the transcript,
and nothing is written: a seen link is no link of the store. The rules:

* what counts: in an assistant event its text blocks and the input of its tool calls, in a user event its plain
  text without the harness's reminders; never a tool result (a listing or a git status names many tasks), never
  thinking. A mention is `task:<slug>`, `work/tasks|streams/<slug>` (relative or under this Bridge's root) or
  `task.py <verb> [flags] [--] <slug>`, of an open task or stream;
* the newest event that names exactly one open task decides; one that names none or two is passed over;
  `task_since_ms` is the oldest event of the unbroken run naming that task;
* only the last 256 KiB and at most 400 events, of sessions in a tab whose folder belongs to this Bridge (the
  root, a folder in it, one of its worktrees, or a folder that is no Bridge at all), at most 12 per scan;
* a link by hand beats a tab's link, which beats what is seen; "Not this task" (session_unlink) refuses the pair
  for good, also for the tab's own link; linking by hand takes the refusal back;
* with cockpit.flow off, or flow.infer_sessions false, no transcript is read.

Run: pytest -q scripts/tests/test_bridge_cockpit_sessions.py
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_bridge_cockpit import STATUS, World, ok, private_key_dir, refused  # noqa: E402,F401  (the autouse fixture comes along)
from lib.bridge_cockpit import guide as gd  # noqa: E402
from lib.bridge_cockpit import sessions as sess  # noqa: E402
from lib.bridge_cockpit.store import WebStore  # noqa: E402

FLOW_ON = "cockpit:\n  enabled: true\n  language: en\n  flow:\n    enabled: true\n"
SID = "6c2f1a0e-3b4d-4e5f-8a9b-0c1d2e3f4a5b"
SID_B = "0f9e8d7c-6b5a-4f3e-9d2c-1b0a9f8e7d6c"
SURF = "8E1C2A44-5D6F-4A7B-9C8D-0E1F2A3B4C5D"
SURF_B = "1A2B3C4D-5E6F-4A7B-8C9D-0E1F2A3B4C5E"
SLUGS = {"demo-task", "other-task", "release-notes"}
ROOT_TEXT = "/home/me/bridge"


# ---------------------------------------------------------------- the transcript as Claude Code writes it

def at(minute: int) -> str:
    return f"2026-10-27T13:{minute:02d}:00.000Z"


def ms(minute: int) -> int:
    return int(dt.datetime.fromisoformat(at(minute).replace("Z", "+00:00")).timestamp() * 1000)


def bash(command: str, minute: int) -> dict:
    return {"type": "assistant", "timestamp": at(minute),
            "message": {"role": "assistant", "content": [{"type": "tool_use", "name": "Bash", "id": "t",
                                                          "input": {"command": command, "description": "a step"}}]}}


def said(text: str, minute: int, kind: str = "text") -> dict:
    block = {"type": kind, kind if kind != "text" else "text": text}
    return {"type": "assistant", "timestamp": at(minute), "message": {"role": "assistant", "content": [block]}}


def asked(content, minute: int, **extra) -> dict:
    return {"type": "user", "timestamp": at(minute), "message": {"role": "user", "content": content}, **extra}


def result(text: str, minute: int) -> dict:
    return asked([{"type": "tool_result", "tool_use_id": "t", "content": text}], minute)


def lines(*events) -> list[str]:
    return [json.dumps(e) for e in events]


def infer(*events, slugs=SLUGS, roots=(ROOT_TEXT,)):
    return sess.infer_task(lines(*events), slugs, roots)


# ---------------------------------------------------------------- the rule, on its own

def test_each_sign_names_its_task():
    assert infer(bash("python3 scripts/task.py note demo-task -- ran the tests", 1)) == ("demo-task", ms(1))
    assert infer(bash("cat work/tasks/other-task/STATUS.md", 2)) == ("other-task", ms(2))
    assert infer(said("this belongs to task:release-notes", 3)) == ("release-notes", ms(3))
    assert infer(asked("look at work/streams/release-notes/ please", 4)) == ("release-notes", ms(4))
    assert infer(asked([{"type": "text", "text": "the key is task:demo-task"}], 5)) == ("demo-task", ms(5))
    read = {"type": "assistant", "timestamp": at(6), "message": {"content": [
        {"type": "tool_use", "name": "Read", "input": {"file_path": f"{ROOT_TEXT}/work/tasks/demo-task/STATUS.md"}}]}}
    assert infer(read) == ("demo-task", ms(6))


def test_the_root_written_from_home_counts_too(monkeypatch, tmp_path):
    """E1 (round 6): a transcript writes the Bridge's root as `~/...` as often as absolute; both are its spellings,
    and a folder outside the home has no `~` spelling"""
    home = tmp_path / "home"
    root = home / "code" / "bridge"
    root.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    spell = sess.root_spellings(root, [root.resolve()])
    assert "~/code/bridge" in spell and str(root) in spell
    assert infer(bash("cat ~/code/bridge/work/tasks/demo-task/STATUS.md", 1), roots=spell) == ("demo-task", ms(1))
    # the same path under another folder of the home names nothing
    assert infer(bash("cat ~/code/other/work/tasks/demo-task/STATUS.md", 1), roots=spell) == (None, None)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    assert not any(x.startswith("~") for x in sess.root_spellings(outside, [outside.resolve()]))


@pytest.mark.parametrize("command, found", [
    ("python3 scripts/task.py close --stream -- release-notes", "release-notes"),
    ('python3 scripts/task.py note "demo-task" -- quoted', "demo-task"),
    ("python3 scripts/task.py note 'demo-task'", "demo-task"),
    ("python3 scripts/task.py priority demo-task P1", "demo-task"),
    ("python3 scripts/task.py note demo-task-two -- a longer slug", None),
    ("python3 scripts/task.py note demo-task.md", None),
    ("python3 scripts/mytask.py note demo-task", None),
    ("python3 scripts/task.py review", None),
    ("echo demo-task is mentioned in passing", None),
    ("cat /home/me/other-bridge/work/tasks/demo-task/STATUS.md", None),
])
def test_what_a_command_names(command, found):
    assert infer(bash(command, 1))[0] == found


def test_an_event_that_names_two_tasks_is_passed_over_and_an_older_one_decides():
    assert infer(bash("task.py note other-task -- x", 1),
                 bash("diff work/tasks/demo-task/STATUS.md work/tasks/other-task/STATUS.md", 2)) == ("other-task", ms(1))
    # two tasks named and nothing older: no task, rather than the wrong one
    assert infer(said("task:demo-task and task:other-task", 1)) == (None, None)


def test_a_tool_result_thinking_and_the_harness_reminders_name_nothing():
    assert infer(result("work/tasks/demo-task/STATUS.md\nM work/tasks/demo-task/STATUS.md", 1)) == (None, None)
    assert infer(said("I should look at work/tasks/demo-task/", 1, kind="thinking")) == (None, None)
    assert infer(asked("<system-reminder>M work/tasks/demo-task/STATUS.md</system-reminder> go on", 1)) == (None, None)
    assert infer(asked("work/tasks/demo-task/", 1, isMeta=True)) == (None, None)
    assert infer(asked("work/tasks/demo-task/", 1, isSidechain=True)) == (None, None)
    assert infer({"type": "attachment", "timestamp": at(1), "attachment": {"text": "task:demo-task"}}) == (None, None)


def test_a_closed_task_names_nothing():
    # only open tasks and streams count: a closed one is not among the slugs, so the open one decides
    assert infer(bash("task.py note done-task", 2), slugs={"demo-task"}) == (None, None)
    assert infer(bash("task.py reopen done-task", 3), bash("task.py note demo-task", 2), slugs={"demo-task"}) == (
        "demo-task", ms(2))


def test_since_is_the_oldest_event_of_the_unbroken_run():
    events = (bash("task.py note other-task", 1),      # another task: the run stops here
              bash("task.py note demo-task", 2),
              said("nothing named", 3),
              said("task:demo-task and task:other-task", 4),   # two: passed over, the run goes on
              {**bash("task.py note demo-task", 5), "timestamp": "not a time"},
              said("task:demo-task", 6))
    assert infer(*events) == ("demo-task", ms(2))
    # the newest names the task: since the newest of its run when nothing older names it
    assert infer(said("task:demo-task", 7)) == ("demo-task", ms(7))
    # no time anywhere: the task, without a since
    assert infer({**said("task:demo-task", 7), "timestamp": None}) == ("demo-task", None)


def test_only_the_newest_events_and_bytes_count(tmp_path):
    many = [bash("task.py note demo-task", 1)] + [said("nothing", 2)] * sess.INFER_EVENTS
    assert infer(*many) == (None, None)
    assert infer(*many[1:], said("task:other-task", 3)) == ("other-task", ms(3))
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join(lines(bash("task.py note demo-task", 1), said("x" * sess.TAIL_BYTES, 2))) + "\n",
                    encoding="utf-8")
    assert sess.infer_task(sess.read_tail(path, sess.TAIL_BYTES), SLUGS, ()) == (None, None)


def attachment(size: int, minute: int) -> dict:
    """A large harness line (a file or a notice the harness attached): no event of the session's own"""
    return {"type": "attachment", "timestamp": at(minute), "attachment": {"content": "x" * size}}


def test_the_end_read_grows_while_only_harness_lines_fill_it(tmp_path):
    # a session waiting on its agents: its last 256 KiB are attachments only; the read grows to find its work
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join(lines(bash("task.py note demo-task", 1), *[attachment(40_000, 2)] * 10)) + "\n",
                    encoding="utf-8")
    assert sess.infer_task(sess.read_tail(path, sess.TAIL_BYTES), SLUGS, ()) == (None, None)
    assert sess.infer_file(path, SLUGS, ()) == ("demo-task", ms(1))
    # never further back than the last step
    far = tmp_path / "far.jsonl"
    far.write_text("\n".join(lines(bash("task.py note demo-task", 1), *[attachment(500_000, 2)] * 10)) + "\n",
                   encoding="utf-8")
    assert far.stat().st_size > sess.TAIL_STEPS[-1] and sess.infer_file(far, SLUGS, ()) == (None, None)
    # a decision in the first step reads no further
    near = tmp_path / "near.jsonl"
    near.write_text("\n".join(lines(bash("task.py note other-task", 1), *[attachment(40_000, 2)] * 10,
                                    bash("task.py note demo-task", 3))) + "\n", encoding="utf-8")
    assert sess.infer_file(near, SLUGS, ()) == ("demo-task", ms(3))
    assert sess.infer_file(tmp_path / "missing.jsonl", SLUGS, ()) == (None, None)


def test_the_guide_reads_its_transcripts_through_the_same_tail_reader():
    assert gd.read_tail is sess.read_tail and gd.transcript_path is sess.transcript_path


# ---------------------------------------------------------------- the store keeps the refusals

def test_a_refusal_is_kept_per_session_and_capped(tmp_path):
    clock = lambda: 1_000_000.0  # noqa: E731
    store = WebStore(tmp_path, clock)
    store.refuse_session(SID, "demo-task")
    assert set(store.session_refused()[SID]) == {"demo-task"}
    for n in range(10):
        store.refuse_session(SID, f"task-{n}")
    assert len(store.session_refused()[SID]) == 8
    assert WebStore(tmp_path, clock).session_refused() == store.session_refused()      # it outlives a restart
    assert store.unrefuse_session(SID, "task-9") is True and "task-9" not in store.session_refused()[SID]
    assert store.unrefuse_session(SID, "never") is False
    data = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert set(data["session_refused"][SID]) == set(store.session_refused()[SID])


# ---------------------------------------------------------------- the server: live sessions of this Bridge

class Home:
    """Claude Code's own folder of a test: live sessions, each in a tab, each with its transcript"""

    def __init__(self, w: World, base: Path):
        self.w, self.base = w, base / "claude"
        (self.base / "sessions").mkdir(parents=True)
        self.tabs, self.env = [], {}
        w.app.sessions.base = self.base
        w.app.sessions.alive = lambda pid: True
        w.runner.handlers["workplace.status"] = lambda argv: ok(STATUS + self.tabs)
        w.runner.handlers["eww.-o"] = lambda argv: ok(self.env.get(int(argv[-1]), "claude X=1\n"))

    def session(self, sid: str, cwd: Path, *events, pid: int = 4100, surface: str | None = SURF,
                tab_slug: str | None = None, started_ms: int | None = None) -> Path:
        started = started_ms if started_ms is not None else ms(0)
        (self.base / "sessions" / f"{pid}.json").write_text(json.dumps(
            {"pid": pid, "sessionId": sid, "cwd": str(cwd), "startedAt": started, "status": "busy", "name": "work"}),
            encoding="utf-8")
        if surface:
            self.tabs.append({"name": f"tab {pid}", "workspace": "Demo", "ref": f"surface:{pid}", "ws_ref": "workspace:2",
                              "state": "working", "id": surface})
            self.env[pid] = f"claude CMUX_SURFACE_ID={surface}" + (f" BRIDGE_TAB_SLUG={tab_slug}" if tab_slug else "") + "\n"
        path = sess.transcript_path(self.base, str(cwd), sid)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines({"type": "user", "cwd": str(cwd), "message": {"content": "hello"}}, *events))
                        + "\n", encoding="utf-8")
        return path

    def append(self, path: Path, *events) -> None:
        with path.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(lines(*events)) + "\n")

    def poll(self) -> dict:
        self.w.app.tabs.poll()
        return {x["sid"]: x for x in self.w.app.sessions_state()["sessions"]}


def task(root: Path, slug: str, kind: str = "tasks") -> None:
    folder = root / "work" / kind / slug
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "STATUS.md").write_text("---\nstatus: doing\nheadline: A task\n---\n", encoding="utf-8")


@pytest.fixture
def flow(tmp_path):
    w = World(tmp_path, config=FLOW_ON)
    task(w.root, "other-task")
    yield w, Home(w, tmp_path)
    w.close()


def test_a_session_that_works_on_one_task_is_seen_working_on_it_and_nothing_is_written(flow):
    w, home = flow
    home.session(SID, w.root, bash("python3 scripts/task.py note demo-task -- ran it", 5), said("done", 6))
    x = home.poll()[SID]
    assert (x["task"], x["task_how"], x["task_since_ms"]) == ("demo-task", "seen", ms(5))
    assert w.app.store.session_links() == {} and w.app.sessions_state()["links"] == []
    state = (w.state / "state.json").read_text(encoding="utf-8") if (w.state / "state.json").exists() else ""
    assert SID not in state and "ran it" not in json.dumps(w.app.state_payload())   # never a word of it


def test_two_tasks_named_or_a_closed_one_give_no_task(flow):
    w, home = flow
    done = w.root / "work" / "done" / "2026-10" / "old-task"
    done.mkdir(parents=True)
    (done / "STATUS.md").write_text("---\nstatus: done\n---\n", encoding="utf-8")
    home.session(SID, w.root, said("task:demo-task and task:other-task", 5))
    home.session(SID_B, w.root, bash("python3 scripts/task.py reopen old-task", 5), pid=4101, surface=SURF_B)
    got = home.poll()
    assert got[SID]["task"] is None and got[SID]["task_how"] is None and got[SID]["task_since_ms"] is None
    assert got[SID_B]["task"] is None


def test_a_link_by_hand_wins_and_a_tab_link_wins_over_what_is_seen(flow):
    w, home = flow
    home.session(SID, w.root, bash("task.py note demo-task", 5), started_ms=ms(1))
    home.session(SID_B, w.root, bash("task.py note other-task", 5), pid=4101, surface=SURF_B, tab_slug="demo-task")
    assert home.poll()[SID]["task_how"] == "seen"
    w.clock.now = ms(30)
    w.act("session_link", session=SID, slug="other-task")
    got = home.poll()
    assert (got[SID]["task"], got[SID]["task_how"], got[SID]["task_since_ms"]) == ("other-task", "hand", ms(30))
    assert (got[SID_B]["task"], got[SID_B]["task_how"]) == ("demo-task", "tab")
    # a link never dates before the session started
    w.app.store._links[SID]["at_ms"] = ms(0)
    assert home.poll()[SID]["task_since_ms"] == ms(1)


def test_not_this_task_holds_and_another_task_may_still_be_seen(flow):
    w, home = flow
    path = home.session(SID, w.root, bash("task.py note demo-task", 5))
    assert home.poll()[SID]["task"] == "demo-task"
    res = w.act("session_unlink", session=SID)
    assert res["session"] == {"sid": SID, "refused": "demo-task"}
    assert res["note"] == "The session no longer counts as work on demo-task"
    assert home.poll()[SID]["task"] is None
    home.append(path, said("still task:demo-task", 7))
    assert home.poll()[SID]["task"] is None                                    # refused for good
    home.append(path, bash("task.py note other-task", 8))
    assert home.poll()[SID]["task"] == "other-task"                            # another one may still be seen
    # nothing linked and nothing seen any more: refused as before
    w.act("session_unlink", session=SID)
    refused(w, "stale_row", "session_unlink", session=SID)
    # linking by hand takes the refusal back
    w.act("session_link", session=SID, slug="demo-task")
    assert "demo-task" not in w.app.store.session_refused().get(SID, {})
    assert home.poll()[SID]["task_how"] == "hand"


def test_unlinking_a_task_tab_session_holds_the_tab_does_not_link_it_again(flow):
    w, home = flow
    home.session(SID, w.root, pid=4100, tab_slug="demo-task")
    assert home.poll()[SID]["task_how"] == "tab"
    res = w.act("session_unlink", session=SID)
    assert res["session"]["refused"] == "demo-task" and res["note"] == "The session no longer belongs to a task"
    got = home.poll()[SID]
    assert got["task"] is None and SID not in w.app.store.session_links()


def test_a_link_to_a_task_that_closed_no_longer_counts_and_the_session_is_seen_again(flow):
    w, home = flow
    task(w.root, "tab-task")
    path = home.session(SID, w.root, pid=4100, tab_slug="tab-task")
    w.clock.now = ms(2)
    home.session(SID_B, w.root, bash("task.py note other-task", 3), pid=4101, surface=SURF_B)
    home.poll()
    w.act("session_link", session=SID_B, slug="demo-task")
    got = home.poll()
    assert (got[SID]["task"], got[SID]["task_how"]) == ("tab-task", "tab")
    assert (got[SID_B]["task"], got[SID_B]["task_how"]) == ("demo-task", "hand")
    # both tasks close (a merge or a done moves the folder): the links stay kept for resume, but count no more
    for slug in ("tab-task", "demo-task"):
        done = w.root / "work" / "done" / "2026-10" / slug
        done.parent.mkdir(parents=True, exist_ok=True)
        (w.root / "work" / "tasks" / slug).rename(done)
    home.append(path, bash("task.py note other-task -- going on with the next one", 9))
    got = home.poll()
    assert (got[SID]["task"], got[SID]["task_how"]) == ("other-task", "seen")
    assert (got[SID_B]["task"], got[SID_B]["task_how"]) == ("other-task", "seen")
    assert set(w.app.store.session_links()) == {SID, SID_B}          # kept, a reopen counts them again
    assert w.app.sessions_state()["links"] == []


def test_a_session_of_another_bridge_is_never_read_a_plain_folder_is(flow, tmp_path, monkeypatch):
    w, home = flow
    other = tmp_path / "other-bridge"
    (other / "work" / "tasks" / "demo-task").mkdir(parents=True)
    (other / "bridge-config.yaml").write_text("identity: {}\n", encoding="utf-8")
    plain = tmp_path / "plain-repo"
    plain.mkdir()
    home.session(SID, other, bash("task.py note demo-task", 5))
    home.session(SID_B, plain, bash("task.py note demo-task", 5), pid=4101, surface=SURF_B)
    read = []
    real = sess.read_tail
    monkeypatch.setattr(sess, "read_tail", lambda path, n: read.append(Path(path)) or real(path, n))
    got = home.poll()
    assert got[SID]["task"] is None and got[SID_B]["task"] == "demo-task"
    assert read and all(SID not in p.name for p in read)                      # the other Bridge's file is never opened


def test_a_session_without_a_tab_is_not_read_and_at_most_twelve_are(flow, monkeypatch):
    w, home = flow
    home.session(SID, w.root, bash("task.py note demo-task", 5), surface=None)
    assert home.poll()[SID]["task"] is None
    read = []
    real = sess.read_tail
    monkeypatch.setattr(sess, "read_tail", lambda path, n: read.append(path) or real(path, n))
    for n in range(14):
        sid = f"{n:08d}-0000-4000-8000-000000000000"
        home.session(sid, w.root, bash("task.py note demo-task", 5), pid=4200 + n, surface=f"{n:08d}-AAAA-4AAA-8AAA-AAAAAAAAAAAA")
    home.poll()
    assert len(read) == sess.INFER_SESSIONS_MAX == 12


def test_an_unchanged_transcript_is_read_once(flow, monkeypatch):
    w, home = flow
    path = home.session(SID, w.root, bash("task.py note demo-task", 5))
    read = []
    real = sess.read_tail
    monkeypatch.setattr(sess, "read_tail", lambda p, n: read.append(p) or real(p, n))
    home.poll()
    home.poll()
    assert len(read) == 1
    home.append(path, said("more", 6))
    home.poll()
    assert len(read) == 2


@pytest.mark.parametrize("config", [
    "cockpit:\n  enabled: true\n  language: en\n",
    FLOW_ON + "    infer_sessions: false\n",
])
def test_with_the_page_off_or_the_switch_off_no_transcript_is_read(tmp_path, monkeypatch, config):
    w = World(tmp_path, config=config)
    try:
        home = Home(w, tmp_path)
        home.session(SID, w.root, bash("task.py note demo-task", 5))
        monkeypatch.setattr(sess, "read_tail", lambda path, n: pytest.fail("a transcript was read"))
        x = home.poll()[SID]
        assert x["task"] is None and x["task_how"] is None
        refused(w, "stale_row", "session_unlink", session=SID)
    finally:
        w.close()
