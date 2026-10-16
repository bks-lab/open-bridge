"""Owner approval: a finished answer leaves only after its owner released it.

With an ``approval:`` block the executor holds every finished answer, marks the task
WORKING with a waiting message, and asks an external approver command. ``approve``
sends the answer, ``edit`` sends the owner's text instead, ``reject``, a timeout or a
broken approver end the task REJECTED without the answer. Nothing of the answer may
reach the caller before the decision: no streamed delta, no step label.

Hermetic: the runner is a fake, the approver is either a fake class or a short
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
from _runtime.approval import ApprovalConfig, CommandApprover, Decision, parse_approval
from _runtime.config import load_agent_config
from _runtime.server import build_app

SECRET_ANSWER = "Vertraulicher Stand: 110 Euro."
V1 = {"A2A-Version": "1.0"}


class _FakeRunner:
    def __init__(self, **_kwargs):
        pass

    async def __call__(self, prompt, *, context_id=None, resume_session_id=None):
        return SECRET_ANSWER

    async def stream(self, prompt, *, context_id=None, resume_session_id=None):
        yield {"kind": "step", "tool": "Read", "label": "Lese infrago-stand.md"}
        yield {"kind": "delta", "text": SECRET_ANSWER[:12]}
        yield {"kind": "answer", "text": SECRET_ANSWER}


class _FakeApprover:
    """Answers with ``decision`` after ``hold`` seconds; records every request."""

    decision = Decision("approve")
    hold = 0.0
    requests: list = []

    def __init__(self, cfg, **_kwargs):
        pass

    async def __call__(self, request):
        _FakeApprover.requests.append(request)
        await asyncio.sleep(_FakeApprover.hold)
        return _FakeApprover.decision


def _cfg(max_concurrency=1):
    cfg = load_agent_config("_template", environment="test")
    return dataclasses.replace(
        cfg,
        approval=ApprovalConfig(command=("fake",), timeout_sec=60),
        max_concurrency=max_concurrency,
    )


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(server_module, "SubprocessClaudeRunner", _FakeRunner)
    monkeypatch.setattr(server_module, "CommandApprover", _FakeApprover)
    _FakeApprover.decision = Decision("approve")
    _FakeApprover.hold = 0.0
    _FakeApprover.requests = []
    with TestClient(build_app(_cfg())) as c:
        yield c


def _send(client, text="Stand?", message_id="m-1"):
    params = {
        "message": {"role": "ROLE_USER", "messageId": message_id, "parts": [{"text": text}]},
        "configuration": {"returnImmediately": True},
    }
    r = client.post(DEFAULT_RPC_URL, json={"jsonrpc": "2.0", "id": "1", "method": "SendMessage",
                                           "params": params}, headers=V1)
    assert r.status_code == 200, r.text
    return r.json()["result"]["task"]


def _get(client, task_id):
    r = client.post(DEFAULT_RPC_URL, json={"jsonrpc": "2.0", "id": "2", "method": "GetTask",
                                           "params": {"id": task_id}}, headers=V1)
    return r.json()["result"]


def _final(client, task_id, timeout=5):
    deadline = time.monotonic() + timeout
    task = _get(client, task_id)
    while time.monotonic() < deadline:
        task = _get(client, task_id)
        if task["status"]["state"] not in ("TASK_STATE_SUBMITTED", "TASK_STATE_WORKING"):
            return task
        time.sleep(0.05)
    return task


def _texts(task):
    parts = [p.get("text", "") for a in task.get("artifacts", []) for p in a.get("parts", [])]
    parts += [p.get("text", "") for p in (task["status"].get("message") or {}).get("parts", [])]
    return " ".join(parts)


def test_an_approved_answer_is_sent(client):
    task = _final(client, _send(client)["id"])
    assert task["status"]["state"] == "TASK_STATE_COMPLETED"
    assert SECRET_ANSWER in _texts(task)
    assert _FakeApprover.requests[0]["answer"] == SECRET_ANSWER
    assert _FakeApprover.requests[0]["question"] == "Stand?"


def test_an_edited_answer_replaces_the_draft(client):
    _FakeApprover.decision = Decision("edit", "Frag mich morgen persönlich.")
    task = _final(client, _send(client)["id"])
    assert task["status"]["state"] == "TASK_STATE_COMPLETED"
    assert "Frag mich morgen persönlich." in _texts(task)
    assert SECRET_ANSWER not in json.dumps(task)


@pytest.mark.parametrize("verdict", ["reject", "timeout", "error"])
def test_no_release_means_rejected_without_the_answer(client, verdict):
    _FakeApprover.decision = Decision(verdict)
    task = _final(client, _send(client)["id"])
    assert task["status"]["state"] == "TASK_STATE_REJECTED"
    assert SECRET_ANSWER not in json.dumps(task)


def test_while_waiting_the_task_is_working_and_leaks_nothing(client):
    _FakeApprover.hold = 1.0
    task_id = _send(client)["id"]
    deadline = time.monotonic() + 3
    while not _FakeApprover.requests and time.monotonic() < deadline:
        time.sleep(0.02)
    waiting = _get(client, task_id)
    assert waiting["status"]["state"] == "TASK_STATE_WORKING"
    dumped = json.dumps(waiting)
    assert SECRET_ANSWER[:12] not in dumped, "a streamed delta reached the caller before approval"
    assert "infrago-stand.md" not in dumped, "a step label reached the caller before approval"
    assert _final(client, task_id)["status"]["state"] == "TASK_STATE_COMPLETED"


def test_a_waiting_approval_does_not_block_the_next_caller(client):
    # max_concurrency is 1: the slot must be free while the owner decides.
    _FakeApprover.hold = 1.0
    first = _send(client, message_id="m-a")["id"]
    deadline = time.monotonic() + 3
    while not _FakeApprover.requests and time.monotonic() < deadline:
        time.sleep(0.02)
    second = _final(client, _send(client, message_id="m-b")["id"])
    assert second["status"]["state"] == "TASK_STATE_COMPLETED"
    assert SECRET_ANSWER in _texts(second)
    assert _final(client, first)["status"]["state"] == "TASK_STATE_COMPLETED"


def test_without_approval_nothing_changes(monkeypatch):
    monkeypatch.setattr(server_module, "SubprocessClaudeRunner", _FakeRunner)
    cfg = load_agent_config("_template", environment="test")
    with TestClient(build_app(cfg)) as c:
        task = _final(c, _send(c)["id"])
    assert task["status"]["state"] == "TASK_STATE_COMPLETED"


# --- the command approver ---------------------------------------------------------

def _program(body):
    return ApprovalConfig(command=(sys.executable, "-c", body), timeout_sec=5)


def _run(approver, request=None):
    return asyncio.run(approver(request or {"question": "q", "answer": "a"}))


def test_the_command_gets_the_request_on_stdin_and_its_answer_is_the_decision():
    body = ("import json,sys; r=json.load(sys.stdin); "
            "print(json.dumps({'decision':'edit','text':r['answer'].upper()}))")
    assert _run(CommandApprover(_program(body))) == Decision("edit", "A")


@pytest.mark.parametrize("body", [
    "import sys; sys.exit(3)",                                  # crashes
    "print('not json')",                                        # garbage
    "import json; print(json.dumps({'decision':'maybe'}))",    # unknown verdict
    "import json; print(json.dumps({'decision':'edit'}))",     # edit without text
])
def test_a_broken_approver_fails_closed(body):
    assert _run(CommandApprover(_program(body))).verdict == "error"


def test_a_silent_approver_times_out():
    cfg = ApprovalConfig(command=(sys.executable, "-c", "import time; time.sleep(30)"), timeout_sec=0.5)
    assert _run(CommandApprover(cfg)).verdict == "timeout"


# --- config ------------------------------------------------------------------------

def test_parse_approval_substitutes_the_tools_dir():
    cfg = parse_approval("x", {"command": ["python3", "${tools_dir}/approve.py"], "timeout_sec": 90},
                         tools_dir="/opt/t")
    assert cfg.command == ("python3", "/opt/t/approve.py") and cfg.timeout_sec == 90 and cfg.enabled


def test_no_block_means_no_approval():
    assert not parse_approval("x", None, tools_dir="/t").enabled


@pytest.mark.parametrize("spec", [{"command": []}, {"command": "python3 x.py"}, {"timeout_sec": 5}])
def test_a_bad_block_refuses_to_start(spec):
    with pytest.raises(ValueError):
        parse_approval("x", spec, tools_dir="/t")


# --- a decision may carry a standing rule (peer requests, see _runtime/policy.py) ----

def test_a_rule_travels_with_the_decision():
    body = ("import json; print(json.dumps({'decision':'approve','text':'ok',"
            "'rule':{'effect':'allow','note':'darf','junk':'x'}}))")
    got = _run(CommandApprover(_program(body)))
    assert got == Decision("approve", "ok", {"effect": "allow", "note": "darf"})


@pytest.mark.parametrize("rule", ["'allow'", "{'effect':'maybe'}", "{'note':'no effect'}"])
def test_an_unusable_rule_fails_the_whole_decision_closed(rule):
    body = f"import json; print(json.dumps({{'decision':'approve','rule':{rule}}}))"
    assert _run(CommandApprover(_program(body))).verdict == "error"
