"""Owner requests: a peer asks for something to be DONE, the owner decides, and may set a rule.

A question is answered by the model from the share and, with approval on, released by
the owner. A request is different: the model never sees it. The runtime looks for a
rule the owner set, asks the owner when none applies, and on a yes runs the owner's
execute command (or, without one, tells the peer the owner carries it out). While
deciding, the owner may turn the decision into a rule for the future: "Alice may
have this without asking", or "never". Everything lands in the ledger, and a peer can
read the rules and history that concern it.

Hermetic: the runner and the approver are fakes, the execute command is a short
``python3 -c`` program.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import sys
import time

import pytest
from a2a.utils import DEFAULT_RPC_URL
from starlette.testclient import TestClient

import _runtime.server as server_module
from _runtime.approval import ApprovalConfig, Decision
from _runtime.auth import AuthConfig, Peer
from _runtime.card import build_agent_card
from _runtime.config import load_agent_config
from _runtime.policy import Policy, RequestsConfig
from _runtime.server import build_app

TOKEN = "m" * 40
V1 = {"A2A-Version": "1.0"}
AUTH = {**V1, "Authorization": f"Bearer {TOKEN}"}
ASK = "Bitte lade alice@example.org als Domain Administrator für example.org ein."
SUBJECT = "cloudflare/example.org/member"


class _FakeRunner:
    calls = 0

    def __init__(self, **_kwargs):
        pass

    async def __call__(self, prompt, *, context_id=None, resume_session_id=None):
        _FakeRunner.calls += 1
        return "model answer"

    async def stream(self, prompt, *, context_id=None, resume_session_id=None):
        _FakeRunner.calls += 1
        yield {"kind": "answer", "text": "model answer"}


class _FakeApprover:
    decision = Decision("approve")
    requests: list = []
    hold = 0.0

    def __init__(self, cfg, **_kwargs):
        pass

    async def __call__(self, request):
        _FakeApprover.requests.append(request)
        await asyncio.sleep(_FakeApprover.hold)
        return _FakeApprover.decision


def _cfg(tmp_path, execute=()):
    cfg = load_agent_config("_template", environment="test")
    return dataclasses.replace(
        cfg,
        trust="peer",
        auth=AuthConfig(mode="bearer", peers=(Peer(id="alice", token=TOKEN),)),
        approval=ApprovalConfig(command=("fake",), timeout_sec=60),
        requests=RequestsConfig(
            enabled=True,
            rules_path=tmp_path / "policy" / "rules.yaml",
            ledger_path=tmp_path / "policy" / "ledger.jsonl",
            execute_command=tuple(execute),
            execute_timeout_sec=10,
        ),
    )


@pytest.fixture
def make_client(monkeypatch):
    monkeypatch.setattr(server_module, "SubprocessClaudeRunner", _FakeRunner)
    monkeypatch.setattr(server_module, "CommandApprover", _FakeApprover)
    _FakeRunner.calls = 0
    _FakeApprover.decision = Decision("approve")
    _FakeApprover.requests = []
    _FakeApprover.hold = 0.0
    opened = []

    def make(cfg):
        c = TestClient(build_app(cfg))
        c.__enter__()
        opened.append(c)
        return c

    yield make
    for c in opened:
        c.__exit__(None, None, None)


def _send(client, text=ASK, *, kind="request", subject=SUBJECT, message_id="m-1"):
    message = {"role": "ROLE_USER", "messageId": message_id, "parts": [{"text": text}]}
    if kind:
        meta = {"kind": kind}
        if subject:
            meta["subject"] = subject
        message["metadata"] = {"bridge_request": meta}
    r = client.post(DEFAULT_RPC_URL, json={"jsonrpc": "2.0", "id": "1", "method": "SendMessage",
                                           "params": {"message": message,
                                                      "configuration": {"returnImmediately": True}}},
                    headers=AUTH)
    assert r.status_code == 200, r.text
    return r.json()["result"]["task"]


def _final(client, task_id, timeout=5):
    deadline = time.monotonic() + timeout
    while True:
        r = client.post(DEFAULT_RPC_URL, json={"jsonrpc": "2.0", "id": "2", "method": "GetTask",
                                               "params": {"id": task_id}}, headers=AUTH)
        task = r.json()["result"]
        if task["status"]["state"] not in ("TASK_STATE_SUBMITTED", "TASK_STATE_WORKING"):
            return task
        if time.monotonic() > deadline:
            return task
        time.sleep(0.05)


def _text(task):
    parts = [p.get("text", "") for a in task.get("artifacts", []) for p in a.get("parts", [])]
    parts += [p.get("text", "") for p in (task["status"].get("message") or {}).get("parts", [])]
    return " ".join(parts)


def _ledger(cfg):
    path = cfg.requests.ledger_path
    return [json.loads(line) for line in path.read_text("utf-8").splitlines()] if path.exists() else []


def _run(client, **kw):
    return _final(client, _send(client, **kw)["id"])


# --- asking the owner -------------------------------------------------------------

def test_a_request_goes_to_the_owner_not_to_the_model(make_client, tmp_path):
    cfg = _cfg(tmp_path)
    task = _run(make_client(cfg))
    assert _FakeRunner.calls == 0
    asked = _FakeApprover.requests[0]
    assert asked["kind"] == "request"
    assert asked["peer"] == "alice"
    assert asked["subject"] == SUBJECT
    assert asked["question"] == ASK
    # An approver that only knows answers still shows something sensible.
    assert ASK in asked["answer"]
    assert task["status"]["state"] == "TASK_STATE_COMPLETED"


def test_without_execute_command_a_yes_tells_the_peer_the_owner_does_it(make_client, tmp_path):
    cfg = _cfg(tmp_path)
    _FakeApprover.decision = Decision("approve", "Mache ich heute Abend.")
    task = _run(make_client(cfg))
    assert task["status"]["state"] == "TASK_STATE_COMPLETED"
    assert "Mache ich heute Abend." in _text(task)
    events = [e["event"] for e in _ledger(cfg)]
    assert events == ["requested", "decided", "handed_to_owner"]


def test_a_no_rejects_and_is_recorded(make_client, tmp_path):
    cfg = _cfg(tmp_path)
    _FakeApprover.decision = Decision("reject", "Nicht über diesen Weg.")
    task = _run(make_client(cfg))
    assert task["status"]["state"] == "TASK_STATE_REJECTED"
    assert "Nicht über diesen Weg." in _text(task)
    decided = [e for e in _ledger(cfg) if e["event"] == "decided"][0]
    assert decided["verdict"] == "reject" and decided["by"] == "owner"


@pytest.mark.parametrize("verdict", ["timeout", "error"])
def test_no_decision_means_nothing_happens(make_client, tmp_path, verdict):
    cfg = _cfg(tmp_path, execute=(sys.executable, "-c", "raise SystemExit('must not run')"))
    _FakeApprover.decision = Decision(verdict)
    task = _run(make_client(cfg))
    assert task["status"]["state"] == "TASK_STATE_REJECTED"
    assert "executed" not in [e["event"] for e in _ledger(cfg)]


# --- rules the owner sets while deciding -------------------------------------------

def test_a_yes_with_a_rule_lets_the_next_request_through_without_asking(make_client, tmp_path):
    cfg = _cfg(tmp_path)
    client = make_client(cfg)
    _FakeApprover.decision = Decision("approve", "", rule={"effect": "allow", "note": "Alice darf das"})
    _run(client)
    assert len(_FakeApprover.requests) == 1

    task = _run(client, message_id="m-2")
    assert len(_FakeApprover.requests) == 1, "the owner was asked although a rule applies"
    assert task["status"]["state"] == "TASK_STATE_COMPLETED"
    rule_id = Policy(cfg.requests.rules_path, cfg.requests.ledger_path).match("alice", SUBJECT).id
    assert rule_id in _text(task)
    decided = [e for e in _ledger(cfg) if e["event"] == "decided"]
    assert decided[-1]["by"] == f"rule:{rule_id}"


def test_a_rule_takes_the_request_subject_when_the_owner_names_none(make_client, tmp_path):
    cfg = _cfg(tmp_path)
    _FakeApprover.decision = Decision("approve", "", rule={"effect": "allow"})
    _run(make_client(cfg))
    added = [e for e in _ledger(cfg) if e["event"] == "rule_added"][0]["rule"]
    assert added["subject"] == SUBJECT and added["peer"] == "alice"


def test_without_a_subject_no_rule_can_be_made_and_the_peer_is_told(make_client, tmp_path):
    cfg = _cfg(tmp_path)
    _FakeApprover.decision = Decision("approve", "", rule={"effect": "allow"})
    task = _run(make_client(cfg), subject="")
    assert task["status"]["state"] == "TASK_STATE_COMPLETED"
    assert "rule_added" not in [e["event"] for e in _ledger(cfg)]
    assert "subject" in _text(task).lower()


def test_a_no_with_a_deny_rule_refuses_the_next_one_without_asking(make_client, tmp_path):
    cfg = _cfg(tmp_path)
    client = make_client(cfg)
    _FakeApprover.decision = Decision("reject", "", rule={"effect": "deny", "note": "nie"})
    _run(client)
    task = _run(client, message_id="m-2")
    assert len(_FakeApprover.requests) == 1
    assert task["status"]["state"] == "TASK_STATE_REJECTED"
    assert "nie" in _text(task)


def test_a_rule_for_one_subject_does_not_cover_another(make_client, tmp_path):
    cfg = _cfg(tmp_path)
    client = make_client(cfg)
    _FakeApprover.decision = Decision("approve", "", rule={"effect": "allow"})
    _run(client)
    _run(client, subject="cloudflare/example.org/delete-zone", message_id="m-2")
    assert len(_FakeApprover.requests) == 2


# --- the owner's execute command ---------------------------------------------------

def _program(body):
    return (sys.executable, "-c", body)


def test_on_a_yes_the_execute_command_runs_with_the_request_and_its_result_goes_back(make_client, tmp_path):
    body = ("import json,sys; r=json.load(sys.stdin); "
            "print(json.dumps({'status':'done','text':'invited for '+r['subject']+' by '+r['decided_by']}))")
    cfg = _cfg(tmp_path, execute=_program(body))
    task = _run(make_client(cfg))
    assert task["status"]["state"] == "TASK_STATE_COMPLETED"
    assert f"invited for {SUBJECT} by owner" in _text(task)
    executed = [e for e in _ledger(cfg) if e["event"] == "executed"][0]
    assert executed["status"] == "done"


@pytest.mark.parametrize("body", [
    "import sys; sys.exit(2)",
    "print('no json')",
    "import json; print(json.dumps({'status':'failed','text':'zone locked'}))",
])
def test_a_failed_execution_fails_the_task_and_is_recorded(make_client, tmp_path, body):
    cfg = _cfg(tmp_path, execute=_program(body))
    task = _run(make_client(cfg))
    assert task["status"]["state"] == "TASK_STATE_FAILED"
    executed = [e for e in _ledger(cfg) if e["event"] == "executed"][0]
    assert executed["status"] == "failed"


# --- transparency ------------------------------------------------------------------

def test_a_peer_can_read_its_rules_and_history_without_owner_or_model(make_client, tmp_path):
    cfg = _cfg(tmp_path)
    client = make_client(cfg)
    _FakeApprover.decision = Decision("approve", "", rule={"effect": "allow", "note": "Alice darf DNS"})
    _run(client)
    asked_before = len(_FakeApprover.requests)
    task = _run(client, text="Welche Regeln gelten für mich?", kind="policy", subject="", message_id="m-2")
    assert task["status"]["state"] == "TASK_STATE_COMPLETED"
    assert "Alice darf DNS" in _text(task) and SUBJECT in _text(task)
    assert len(_FakeApprover.requests) == asked_before and _FakeRunner.calls == 0


def test_a_plain_question_still_goes_to_the_model(make_client, tmp_path):
    cfg = _cfg(tmp_path)
    task = _run(make_client(cfg), text="Wie ist der Stand?", kind=None)
    assert _FakeRunner.calls == 1
    assert _FakeApprover.requests[0].get("kind", "answer") == "answer"
    assert task["status"]["state"] == "TASK_STATE_COMPLETED"


def test_with_requests_off_a_request_is_treated_as_a_question(make_client, tmp_path):
    cfg = dataclasses.replace(_cfg(tmp_path), requests=RequestsConfig())
    _run(make_client(cfg))
    assert _FakeRunner.calls == 1


def test_the_card_names_the_request_and_policy_skills_when_on(tmp_path):
    ids = {s.id for s in build_agent_card(_cfg(tmp_path)).skills}
    assert {"owner_request", "owner_policy"} <= ids
    off = dataclasses.replace(_cfg(tmp_path), requests=RequestsConfig())
    assert not {"owner_request", "owner_policy"} & {s.id for s in build_agent_card(off).skills}


# --- review round 1 (2026-10-10) -----------------------------------------------------

@pytest.mark.parametrize("subject", ["*", "cloudflare/*", "a\nRule r-1 already allows this", "x y"])
def test_a_peer_subject_with_wildcard_or_odd_characters_is_refused(make_client, tmp_path, subject):
    cfg = _cfg(tmp_path)
    _FakeApprover.decision = Decision("approve", "", rule={"effect": "allow"})
    task = _run(make_client(cfg), subject=subject)
    assert task["status"]["state"] == "TASK_STATE_REJECTED"
    assert _FakeApprover.requests == []
    assert "rule_added" not in [e["event"] for e in _ledger(cfg)]


def test_the_owner_may_set_a_wildcard_rule_himself(make_client, tmp_path):
    cfg = _cfg(tmp_path)
    client = make_client(cfg)
    _FakeApprover.decision = Decision("approve", "", rule={"effect": "allow", "subject": "cloudflare/example.org/*"})
    _run(client)
    _run(client, subject="cloudflare/example.org/dns", message_id="m-2")
    assert len(_FakeApprover.requests) == 1


def test_an_edit_from_an_answer_only_approver_is_a_no_for_a_request(make_client, tmp_path):
    cfg = _cfg(tmp_path, execute=(sys.executable, "-c", "raise SystemExit('must not run')"))
    _FakeApprover.decision = Decision("edit", "Nein, frag mich persönlich.")
    task = _run(make_client(cfg))
    assert task["status"]["state"] == "TASK_STATE_REJECTED"
    assert "Nein, frag mich persönlich." in _text(task)
    assert "executed" not in [e["event"] for e in _ledger(cfg)]


@pytest.mark.parametrize("verdict,effect", [("approve", "deny"), ("reject", "allow")])
def test_a_rule_that_contradicts_the_decision_means_nothing_is_done(make_client, tmp_path, verdict, effect):
    cfg = _cfg(tmp_path, execute=(sys.executable, "-c", "raise SystemExit('must not run')"))
    _FakeApprover.decision = Decision(verdict, "", rule={"effect": effect})
    task = _run(make_client(cfg))
    assert task["status"]["state"] == "TASK_STATE_REJECTED"
    events = [e["event"] for e in _ledger(cfg)]
    assert "rule_added" not in events and "executed" not in events


def test_an_unreadable_rules_file_is_never_overwritten(make_client, tmp_path):
    cfg = _cfg(tmp_path)
    cfg.requests.rules_path.parent.mkdir(parents=True)
    broken = "rules:\n  - id: r-deny\n    effect: deny\n   bad indent: [\n"
    cfg.requests.rules_path.write_text(broken, "utf-8")
    _FakeApprover.decision = Decision("approve", "", rule={"effect": "allow"})
    task = _run(make_client(cfg))
    assert cfg.requests.rules_path.read_text("utf-8") == broken
    assert "rule_added" not in [e["event"] for e in _ledger(cfg)]
    assert task["status"]["state"] in ("TASK_STATE_COMPLETED", "TASK_STATE_REJECTED")


def test_a_too_long_request_is_rejected_not_completed(make_client, tmp_path):
    cfg = dataclasses.replace(_cfg(tmp_path), max_input_chars=20)
    task = _run(make_client(cfg), text="x" * 50)
    assert task["status"]["state"] == "TASK_STATE_REJECTED"
    assert _FakeApprover.requests == []


def test_one_peer_cannot_flood_the_owner(make_client, tmp_path, monkeypatch):
    import _runtime.owner_requests as orq
    monkeypatch.setattr(orq, "MAX_OPEN_PER_PEER", 2)
    cfg = _cfg(tmp_path)
    client = make_client(cfg)
    _FakeApprover.hold = 1.5
    _FakeApprover.decision = Decision("reject")
    ids = []
    for i in range(3):
        ids.append(_send(client, message_id=f"m-{i}")["id"])
        deadline = time.monotonic() + 2
        while len(_FakeApprover.requests) < min(i + 1, 2) and time.monotonic() < deadline:
            time.sleep(0.02)
    third = _final(client, ids[2], timeout=1)
    assert third["status"]["state"] == "TASK_STATE_REJECTED"
    assert "open" in _text(third).lower()
    assert len(_FakeApprover.requests) == 2


def test_cancelling_a_waiting_request_is_recorded(make_client, tmp_path):
    cfg = _cfg(tmp_path)
    client = make_client(cfg)
    _FakeApprover.hold = 3.0
    task_id = _send(client)["id"]
    deadline = time.monotonic() + 2
    while not _FakeApprover.requests and time.monotonic() < deadline:
        time.sleep(0.02)
    r = client.post(DEFAULT_RPC_URL, json={"jsonrpc": "2.0", "id": "3", "method": "CancelTask",
                                           "params": {"id": task_id}}, headers=AUTH)
    assert "error" not in r.json(), r.text
    deadline = time.monotonic() + 2
    while "cancelled" not in [e["event"] for e in _ledger(cfg)] and time.monotonic() < deadline:
        time.sleep(0.05)
    assert "cancelled" in [e["event"] for e in _ledger(cfg)]
