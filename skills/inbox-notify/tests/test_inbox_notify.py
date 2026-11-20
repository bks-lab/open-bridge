# SPDX-License-Identifier: MIT
"""Contract for skills/inbox-notify: an open item that needs a person now becomes one text and one
poll on the channel, the vote runs the verb behind the option, and nothing else ever touches the
account. Hermetic: `signal-cli` is a fake on PATH that records every call and replays a scripted
inbox, so no message leaves this machine."""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
ENGINE = ROOT / "skills" / "inbox-notify" / "scripts" / "inbox_notify.py"
UUID = "0b7e5b2e-1c3d-4e5f-8a9b-0c1d2e3f4a5b"
OTHER = "ffffffff-1111-2222-3333-444444444444"

spec = importlib.util.spec_from_file_location("inbox", ROOT / "scripts" / "inbox.py")
assert spec is not None and spec.loader is not None
inbox = importlib.util.module_from_spec(spec)
sys.modules["inbox"] = inbox
sys.dont_write_bytecode = True
spec.loader.exec_module(inbox)

FAKE = r'''#!/usr/bin/env python3
import json, os, sys
d = os.environ["FAKE_SIGNAL_DIR"]
args = sys.argv[1:]
with open(os.path.join(d, "calls.jsonl"), "a") as f:
    f.write(json.dumps(args) + "\n")
cmd = next((a for a in args if a in ("send", "sendPollCreate", "sendPollTerminate", "receive")), "")
if cmd == "sendPollCreate":
    c = os.path.join(d, "counter")
    n = int(open(c).read()) + 1 if os.path.exists(c) else 1700000000001
    open(c, "w").write(str(n))
    print(json.dumps({"timestamp": n, "results": [{"type": "SUCCESS", "recipientAddress": {"uuid": os.environ["FAKE_UUID"]}}]}))
elif cmd == "receive":
    p = os.path.join(d, "incoming.jsonl")
    if os.path.exists(p):
        sys.stdout.write(open(p).read()); open(p, "w").close()
else:
    print(json.dumps({"timestamp": 1}))
'''

CHANNEL = """schema_version: 1
scope: user
name: signal
display_name: Signal
type: bot
implementation: {skill: inbox-notify}
runtime: {remote: local, mode: launchd, service_label: org.example.inbox-notify}
transport:
  kind: signal-cli
  account: "+10000000000"
  recipient: "u:owner.1"
  receive_timeout_sec: 1
notify:
  urgencies: [now]
  cockpit_url: http://127.0.0.1:8797/
access: {policy: allowlist, self: "u:owner.1"}
status: active
"""


@pytest.fixture()
def bridge(tmp_path, monkeypatch):
    (tmp_path / "work" / "inbox").mkdir(parents=True)
    (tmp_path / "infra" / "channels").mkdir(parents=True)
    (tmp_path / "infra" / "channels" / "signal.yaml").write_text(CHANNEL)
    (tmp_path / "bridge-config.yaml").write_text("inbox:\n  notify_via: signal\n")
    fake_dir = tmp_path / "fake"
    fake_dir.mkdir()
    binary = fake_dir / "signal-cli"
    binary.write_text(FAKE)
    binary.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_SIGNAL_DIR", str(fake_dir))
    monkeypatch.setenv("FAKE_SIGNAL_UUID", UUID)
    monkeypatch.setenv("FAKE_UUID", UUID)
    return tmp_path


def box(root: Path) -> "inbox.Inbox":
    return inbox.Inbox(root / "work" / "inbox", actor="owner")


def held_answer(root: Path, peer="partner-bridge", **extra) -> str:
    return box(root).add(
        source=f"agent-approval/{peer}", kind="draft", gate="only-you", urgency="now",
        summary=f"Answer to {peer} waits for your release: when is the release?",
        detail="Question:\nWhen is the next release?\n\nDrafted answer:\nFriday, after the review.",
        actions=["approve", "reject"],
        expires_at=(dt.datetime.now().astimezone() + dt.timedelta(hours=1)).isoformat(timespec="seconds"),
        **extra)


def run(root: Path, *args: str, check=True) -> subprocess.CompletedProcess:
    done = subprocess.run([sys.executable, str(ENGINE), "--root", str(root), *args],
                          capture_output=True, text=True, timeout=60)
    if check:
        assert done.returncode == 0, done.stdout + done.stderr
    return done


def calls(root: Path) -> list[list[str]]:
    path = root / "fake" / "calls.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def commands(root: Path) -> list[str]:
    out = []
    for argv in calls(root):
        out.append(next(a for a in argv if a in ("send", "sendPollCreate", "sendPollTerminate", "receive")))
    return out


def options(argv: list[str]) -> list[str]:
    """The poll options: everything after the LAST -o (the first -o is the json output flag)."""
    return argv[len(argv) - argv[::-1].index("-o"):]


def incoming(root: Path, *envelopes: dict) -> None:
    with (root / "fake" / "incoming.jsonl").open("a") as f:
        for env in envelopes:
            f.write(json.dumps({"envelope": env}) + "\n")


def vote(ts: str, options: list[int], uuid=UUID, count=1) -> dict:
    return {"sourceUuid": uuid, "sourceNumber": "+19999999999",
            "dataMessage": {"pollVote": {"targetSentTimestamp": int(ts), "optionIndexes": options,
                                         "voteCount": count, "authorUuid": uuid}}}


def quote(ts: str, text: str, uuid=UUID) -> dict:
    return {"sourceUuid": uuid, "dataMessage": {"message": text, "quote": {"id": int(ts), "authorUuid": "x"}}}


def poll_ts(root: Path, item_id: str) -> str:
    notes = [e.data["text"] for e in box(root).get(item_id).events if e.verb == "note"]
    marks = [n for n in notes if n.startswith("notify poll ")]
    assert marks, notes
    return marks[-1].split()[2]


# ------------------------------------------------------------------ announcing

def test_a_held_answer_becomes_one_text_and_one_poll_with_the_items_actions(bridge):
    item_id = held_answer(bridge)
    run(bridge, "tick")
    assert commands(bridge) == ["send", "sendPollCreate", "receive"]
    send, poll = calls(bridge)[0], calls(bridge)[1]
    text = send[send.index("-m") + 1]
    assert "Waiting for you: Answer to partner-bridge" in text
    assert "When is the next release?" in text and "Friday, after the review." in text
    assert "Valid until" in text and "http://127.0.0.1:8797/" in text
    assert poll[poll.index("-u") + 1] == "owner.1"            # u:<name> becomes -u <name>, never positional
    assert "--no-multi" in poll
    assert options(poll) == ["Approve", "Reject"]
    assert poll[poll.index("-q") + 1].startswith("Answer to partner-bridge")
    mark = [e.data["text"] for e in box(bridge).get(item_id).events if e.verb == "note"][-1]
    assert mark.startswith(f"notify poll 1700000000001 {UUID} via signal options approve,reject")


def test_an_announced_item_is_not_announced_again(bridge):
    held_answer(bridge)
    run(bridge, "tick")
    run(bridge, "tick")
    assert commands(bridge) == ["send", "sendPollCreate", "receive", "receive"]


def test_only_items_that_need_a_person_now_are_announced(bridge):
    b = box(bridge)
    b.add(source="deputy", kind="decision", summary="Renew the domain next month", urgency="later",
          actions=["approve", "defer"])
    b.add(source="watcher/ci", kind="finding", summary="All green", urgency="now")      # no actions: nothing to do
    b.add(source="watcher/ci", kind="question", summary="Red check", urgency="now", actions=[])
    run(bridge, "tick")
    assert commands(bridge) == ["receive"]


def test_sources_narrow_the_selection(bridge):
    cfg = (bridge / "infra" / "channels" / "signal.yaml")
    cfg.write_text(cfg.read_text().replace("urgencies: [now]", "urgencies: [now]\n  sources: [agent-approval/]"))
    box(bridge).add(source="deputy", kind="question", summary="Which logo?", urgency="now", actions=["approve", "drop"])
    held_answer(bridge)
    run(bridge, "tick")
    assert commands(bridge) == ["send", "sendPollCreate", "receive"]


def test_a_single_action_gets_a_no_op_second_option(bridge):
    box(bridge).add(source="watcher/ci", kind="question", summary="Close the stale PR?", urgency="now", actions=["close"])
    run(bridge, "tick")
    poll = calls(bridge)[1]
    assert options(poll) == ["Close", "Later"]


def test_labels_and_texts_come_from_the_channel_file(bridge):
    cfg = bridge / "infra" / "channels" / "signal.yaml"
    cfg.write_text(CHANNEL.replace("  cockpit_url: http://127.0.0.1:8797/\n",
                                   "  labels: {approve: Freigeben, reject: Ablehnen}\n"
                                   "  texts: {heading: 'Freigabe wartet: {summary}'}\n"))
    held_answer(bridge)
    run(bridge, "tick")
    send, poll = calls(bridge)[0], calls(bridge)[1]
    assert send[send.index("-m") + 1].startswith("Freigabe wartet: Answer to partner-bridge")
    assert options(poll) == ["Freigeben", "Ablehnen"]


def test_dry_run_sends_nothing_reads_nothing_and_notes_nothing(bridge):
    item_id = held_answer(bridge)
    done = run(bridge, "tick", "--dry-run")
    assert "[poll]" in done.stdout and "Approve / Reject" in done.stdout
    assert calls(bridge) == []
    assert all(e.verb != "note" for e in box(bridge).get(item_id).events)


# ------------------------------------------------------------------ voting

def test_a_vote_for_the_first_option_approves_terminates_the_poll_and_confirms(bridge):
    item_id = held_answer(bridge)
    run(bridge, "tick")
    ts = poll_ts(bridge, item_id)
    incoming(bridge, vote(ts, [0]))
    run(bridge, "tick")
    item = box(bridge).get(item_id)
    assert item.state == "approved"
    assert any(e.verb == "approve" and e.by == "inbox-notify" for e in item.events)
    assert any(e.verb == "note" and e.data["text"].startswith("notify decided approve via signal") for e in item.events)
    tail = calls(bridge)[-2:]                          # receive, then terminate, then the confirmation
    assert [next(a for a in c if a in ("sendPollTerminate", "send")) for c in tail] == ["sendPollTerminate", "send"]
    assert tail[0][tail[0].index("--poll-timestamp") + 1] == ts
    assert tail[1][tail[1].index("-m") + 1].startswith("Approve: Answer to partner-bridge")


def test_a_vote_for_the_second_option_rejects(bridge):
    item_id = held_answer(bridge)
    run(bridge, "tick")
    incoming(bridge, vote(poll_ts(bridge, item_id), [1]))
    run(bridge, "tick")
    item = box(bridge).get(item_id)
    assert item.state == "dropped"                    # a reject ends the item like a drop; the verb tells them apart
    assert any(e.verb == "reject" and e.by == "inbox-notify" for e in item.events)


def test_the_verbs_behind_the_options_are_the_items_own(bridge):
    item_id = box(bridge).add(source="deputy", kind="question", summary="Keep the old key?", urgency="now",
                              actions=["drop", "defer", "approve"])
    run(bridge, "tick")
    poll = calls(bridge)[1]
    assert options(poll) == ["Drop", "Defer", "Approve"]
    incoming(bridge, vote(poll_ts(bridge, item_id), [1]))
    run(bridge, "tick")
    item = box(bridge).get(item_id)
    defer = [e for e in item.events if e.verb == "defer"]
    assert defer and defer[0].data["until"] == (dt.date.today() + dt.timedelta(days=1)).isoformat()


def test_a_vote_from_another_identity_does_nothing(bridge):
    item_id = held_answer(bridge)
    run(bridge, "tick")
    incoming(bridge, vote(poll_ts(bridge, item_id), [0], uuid=OTHER))
    done = run(bridge, "tick")
    assert box(bridge).get(item_id).state == "open"
    assert "another identity" in done.stdout
    assert "sendPollTerminate" not in commands(bridge)


def test_a_vote_on_an_unknown_poll_and_a_withdrawn_vote_do_nothing(bridge):
    item_id = held_answer(bridge)
    run(bridge, "tick")
    incoming(bridge, vote("1600000000000", [0]), vote(poll_ts(bridge, item_id), []))
    done = run(bridge, "tick")
    assert box(bridge).get(item_id).state == "open"
    assert "unknown poll" in done.stdout and "withdrawn" in done.stdout


def test_the_last_vote_of_a_tick_wins(bridge):
    item_id = held_answer(bridge)
    run(bridge, "tick")
    ts = poll_ts(bridge, item_id)
    incoming(bridge, vote(ts, [1], count=1), vote(ts, [0], count=2))
    run(bridge, "tick")
    assert box(bridge).get(item_id).state == "approved"


def test_a_vote_on_an_item_decided_elsewhere_only_terminates_the_poll(bridge):
    item_id = held_answer(bridge)
    run(bridge, "tick")
    ts = poll_ts(bridge, item_id)
    box(bridge).close(item_id, note="done in the cockpit")
    incoming(bridge, vote(ts, [0]))
    run(bridge, "tick")
    item = box(bridge).get(item_id)
    assert item.state == "done"
    assert not any(e.verb == "approve" for e in item.events)
    assert "sendPollTerminate" in commands(bridge)


def test_a_poll_whose_item_was_decided_elsewhere_is_terminated_once(bridge):
    item_id = held_answer(bridge)
    run(bridge, "tick")
    box(bridge).approve(item_id)
    run(bridge, "tick")
    run(bridge, "tick")
    assert commands(bridge).count("sendPollTerminate") == 1
    notes = [e.data["text"] for e in box(bridge).get(item_id).events if e.verb == "note"]
    assert sum(n.startswith("notify closed-elsewhere via signal") for n in notes) == 1


def test_a_quoted_reply_releases_the_quoted_text_as_the_edited_answer(bridge):
    item_id = held_answer(bridge)
    run(bridge, "tick")
    incoming(bridge, quote(poll_ts(bridge, item_id), "Friday. Thursday if the review is early."))
    run(bridge, "tick")
    item = box(bridge).get(item_id)
    assert item.state == "approved"
    assert item.approved_text == "Friday. Thursday if the review is early."
    assert any(e.verb == "note" and "notify decided approve via signal" in e.data["text"] for e in item.events)


def test_a_quoted_reply_on_an_item_without_approve_does_nothing(bridge):
    item_id = box(bridge).add(source="watcher/ci", kind="question", summary="Close it?", urgency="now",
                              actions=["close", "drop"])
    run(bridge, "tick")
    incoming(bridge, quote(poll_ts(bridge, item_id), "yes please"))
    done = run(bridge, "tick")
    assert box(bridge).get(item_id).state == "open"
    assert "offers no approve" in done.stdout


# ------------------------------------------------------------------ config and guards

def test_without_a_channel_nothing_is_sent_and_the_exit_is_2(bridge):
    (bridge / "bridge-config.yaml").write_text("inbox: {}\n")
    held_answer(bridge)
    done = run(bridge, "tick", check=False)
    assert done.returncode == 2 and "notify_via" in done.stderr
    assert calls(bridge) == []


def test_a_missing_handle_is_a_config_error_before_anything_is_sent(bridge):
    cfg = bridge / "infra" / "channels" / "signal.yaml"
    cfg.write_text(cfg.read_text().replace('recipient: "u:owner.1"', "recipient: ''").replace(
        'access: {policy: allowlist, self: "u:owner.1"}', "access: {policy: allowlist}"))
    held_answer(bridge)
    done = run(bridge, "tick", check=False)
    assert done.returncode == 2 and "transport.recipient" in done.stderr
    assert calls(bridge) == []


def test_handles_may_be_file_references(bridge):
    (bridge / "account").write_text("+10000000000\n")
    (bridge / "recipient").write_text("u:owner.1\n")
    cfg = bridge / "infra" / "channels" / "signal.yaml"
    cfg.write_text(cfg.read_text().replace('account: "+10000000000"', f'account: "file://{bridge}/account"')
                   .replace('recipient: "u:owner.1"', f'recipient: "file://{bridge}/recipient"'))
    held_answer(bridge)
    run(bridge, "tick")
    poll = calls(bridge)[1]
    assert poll[poll.index("-a") + 1] == "+10000000000" and poll[poll.index("-u") + 1] == "owner.1"


def test_show_prints_the_resolved_configuration(bridge):
    done = run(bridge, "show")
    assert "recipient: u:owner.1" in done.stdout and "urgencies:" in done.stdout
    assert calls(bridge) == []


def test_test_sends_one_text_and_one_poll(bridge):
    run(bridge, "test")
    assert commands(bridge) == ["send", "sendPollCreate"]
    poll = calls(bridge)[1]
    assert options(poll) == ["Yes", "No"]


def test_a_second_tick_while_one_runs_exits_without_touching_the_account(bridge):
    import fcntl
    held_answer(bridge)
    lock = bridge / ".bridge" / "inbox-notify.signal.lock"
    lock.parent.mkdir(parents=True)
    with lock.open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        done = run(bridge, "tick")
    assert "one reader" in done.stdout
    assert calls(bridge) == []
