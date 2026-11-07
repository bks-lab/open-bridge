# SPDX-License-Identifier: MIT
"""Contract for scripts/inbox-approve.py: an agent's held answer waits in the inbox.

agents/_runtime/approval.py starts an approver command once per finished answer,
writes one JSON request to its stdin and reads one JSON decision from its stdout.
This approver files the answer as an inbox item and waits until a person decided
there, so held answers sit next to everything else that needs that person.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APPROVER = ROOT / "scripts" / "inbox-approve.py"
spec = importlib.util.spec_from_file_location("inbox", ROOT / "scripts" / "inbox.py")
assert spec is not None and spec.loader is not None
inbox = importlib.util.module_from_spec(spec)
sys.modules["inbox"] = inbox
sys.dont_write_bytecode = True
spec.loader.exec_module(inbox)

REQUEST = {"task_id": "t-1", "context_id": "c-1", "peer": "partner-bridge",
           "question": "When is the next release?", "answer": "Friday, after the review."}


def start(repo: Path, timeout_sec: float = 20):
    proc = subprocess.Popen(
        [sys.executable, str(APPROVER), "--root", str(repo), "--poll", "0.1"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    assert proc.stdin is not None
    proc.stdin.write(json.dumps({**REQUEST, "timeout_sec": timeout_sec}))
    proc.stdin.close()
    return proc


def wait_for_item(repo: Path, seconds: float = 10) -> str:
    box = inbox.Inbox(repo / "work" / "inbox", actor="owner")
    deadline = time.time() + seconds
    while time.time() < deadline:
        items = box.items()
        if items:
            return items[0].id
        time.sleep(0.05)
    raise AssertionError("approver filed no item")


def finish(proc) -> dict:
    # stdin was closed in start(); communicate() would try to flush it again,
    # which Python 3.12 rejects ("I/O operation on closed file").
    proc.wait(timeout=20)
    out, err = proc.stdout.read(), proc.stderr.read()
    assert proc.returncode == 0, err
    return json.loads(out.strip().splitlines()[-1])


@pytest.fixture()
def repo(tmp_path):
    (tmp_path / "work" / "inbox").mkdir(parents=True)
    return tmp_path


def test_held_answer_becomes_an_only_you_draft(repo):
    proc = start(repo)
    item_id = wait_for_item(repo)
    item = inbox.Inbox(repo / "work" / "inbox", actor="owner").get(item_id)
    assert item.kind == "draft" and item.gate == "only-you" and item.urgency == "now"
    assert "partner-bridge" in item.summary and "Friday" in item.detail
    proc.kill()


@pytest.mark.parametrize("verb, expected", [("approve", "approve"), ("reject", "reject"), ("drop", "reject")])
def test_decision_in_the_inbox_is_the_answer(repo, verb, expected):
    proc = start(repo)
    item_id = wait_for_item(repo)
    inbox.Inbox(repo / "work" / "inbox", actor="owner").event(item_id, verb)
    assert finish(proc) == {"decision": expected}


def test_approve_with_text_is_an_edit(repo):
    proc = start(repo)
    item_id = wait_for_item(repo)
    inbox.Inbox(repo / "work" / "inbox", actor="owner").approve(item_id, text="Friday.")
    assert finish(proc) == {"decision": "edit", "text": "Friday."}


def test_silence_past_the_deadline_is_a_timeout_and_the_item_is_dropped(repo):
    proc = start(repo, timeout_sec=0.5)
    decision = finish(proc)
    assert decision == {"decision": "timeout"}
    box = inbox.Inbox(repo / "work" / "inbox", actor="owner")
    assert box.items()[0].state == "dropped"


def test_unreadable_request_exits_nonzero(repo):
    done = subprocess.run([sys.executable, str(APPROVER), "--root", str(repo)], input="not json",
                          capture_output=True, text=True, timeout=10)
    assert done.returncode != 0
    assert not list((repo / "work" / "inbox").iterdir())


def test_an_old_yes_never_releases_a_new_answer(repo):
    """Review 2026-10-04: the same task_id used to dedup onto the first item and reuse its yes."""
    first = start(repo)
    item_id = wait_for_item(repo)
    inbox.Inbox(repo / "work" / "inbox", actor="owner").approve(item_id)
    assert finish(first) == {"decision": "approve"}
    second = start(repo, timeout_sec=1.0)          # same task_id, a new answer
    assert finish(second) == {"decision": "timeout"}
    items = inbox.Inbox(repo / "work" / "inbox", actor="owner").items()
    assert len(items) == 2


def test_a_decided_item_is_closed_so_it_cannot_linger(repo):
    proc = start(repo)
    item_id = wait_for_item(repo)
    inbox.Inbox(repo / "work" / "inbox", actor="owner").approve(item_id)
    finish(proc)
    assert inbox.Inbox(repo / "work" / "inbox", actor="owner").get(item_id).state == "done"


def test_a_long_question_is_cut_between_words(repo):
    # 07.11.2026: "... nur mit dem Satz 'Empfang ü" stood in the briefing, cut inside a word.
    long_q = "Test via the broker: answer only with the sentence 'reception works' " + "and more words " * 10
    proc = subprocess.Popen(
        [sys.executable, str(APPROVER), "--root", str(repo), "--poll", "0.1"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    proc.stdin.write(json.dumps({**REQUEST, "question": long_q, "timeout_sec": 20}))
    proc.stdin.close()
    item = inbox.Inbox(repo / "work" / "inbox", actor="owner").get(wait_for_item(repo))
    proc.kill()
    head = item.summary.split(": ", 1)[1]
    assert head.endswith("…")
    assert long_q.startswith(head[:-1].rstrip()) and long_q[len(head[:-1].rstrip())] == " "
