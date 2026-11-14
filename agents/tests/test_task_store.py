"""Tasks survive a restart, and an answer waiting for its owner is asked for again.

With ``InMemoryTaskStore`` a restart lost every task, so a caller
got "Task not found" and an approval in progress was gone. ``SqliteTaskStore`` writes
tasks through to SQLite; the executor journals each pending approval and re-asks it
at start. Also here: a shed task (all slots busy) ends failed with a reason, never
completed (open-bridge#640).

Hermetic: fake runner, fake approver, database under ``tmp_path``.
"""
from __future__ import annotations

import asyncio
import dataclasses
import threading
import time

import pytest
from a2a.utils import DEFAULT_RPC_URL
from starlette.testclient import TestClient

import _runtime.server as server_module
from _runtime.approval import ApprovalConfig, Decision
from _runtime.config import load_agent_config
from _runtime.server import build_app

ANSWER = "Draft answer."
V1 = {"A2A-Version": "1.0"}


class _FakeRunner:
    gate: threading.Event | None = None

    def __init__(self, **_kwargs):
        pass

    async def __call__(self, prompt, *, context_id=None, resume_session_id=None):
        while _FakeRunner.gate is not None and not _FakeRunner.gate.is_set():
            await asyncio.sleep(0.02)
        return ANSWER


class _FakeApprover:
    decision = Decision("approve")
    hold = 0.0
    requests: list = []

    def __init__(self, cfg, **_kwargs):
        pass

    async def __call__(self, request):
        _FakeApprover.requests.append(request)
        await asyncio.sleep(_FakeApprover.hold)
        return _FakeApprover.decision


@pytest.fixture
def fakes(monkeypatch, tmp_path):
    monkeypatch.setattr(server_module, "SubprocessClaudeRunner", _FakeRunner)
    monkeypatch.setattr(server_module, "CommandApprover", _FakeApprover)
    monkeypatch.setenv("AGENT_TASK_STORE", str(tmp_path / "tasks.sqlite"))
    _FakeRunner.gate = None
    _FakeApprover.decision = Decision("approve")
    _FakeApprover.hold = 0.0
    _FakeApprover.requests = []


def _cfg(approval=True, max_concurrency=1):
    cfg = load_agent_config("_template", environment="test")
    return dataclasses.replace(
        cfg,
        approval=ApprovalConfig(command=("fake",), timeout_sec=60) if approval else ApprovalConfig(),
        max_concurrency=max_concurrency,
    )


def _send(client, text="Status?", message_id="m-1"):
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
    return r.json()


def _state(client, task_id):
    res = _get(client, task_id)
    return res["result"]["status"]["state"] if "result" in res else "ERROR"


def _until(client, task_id, done, timeout=5):
    deadline = time.monotonic() + timeout
    state = _state(client, task_id)
    while not done(state) and time.monotonic() < deadline:
        time.sleep(0.05)
        state = _state(client, task_id)
    return state


def test_a_finished_task_is_still_there_after_a_restart(fakes):
    with TestClient(build_app(_cfg())) as c:
        tid = _send(c)["id"]
        assert _until(c, tid, lambda s: s == "TASK_STATE_COMPLETED") == "TASK_STATE_COMPLETED"
    with TestClient(build_app(_cfg())) as c:
        task = _get(c, tid)["result"]
        assert task["status"]["state"] == "TASK_STATE_COMPLETED"
        assert ANSWER in str(task)


@pytest.mark.parametrize("verdict, final", [
    ("approve", "TASK_STATE_COMPLETED"),
    ("reject", "TASK_STATE_REJECTED"),
    ("timeout", "TASK_STATE_CANCELED"),
])
def test_an_approval_waiting_at_restart_is_asked_again(fakes, verdict, final):
    _FakeApprover.hold = 30.0
    with TestClient(build_app(_cfg())) as c:
        tid = _send(c)["id"]
        deadline = time.monotonic() + 5
        while not _FakeApprover.requests and time.monotonic() < deadline:
            time.sleep(0.02)
        assert _state(c, tid) == "TASK_STATE_WORKING"
    # The first process is gone mid-approval; the next one asks the owner again.
    _FakeApprover.hold = 0.0
    _FakeApprover.decision = Decision(verdict)
    with TestClient(build_app(_cfg())) as c:
        assert _until(c, tid, lambda s: s == final) == final
        assert len(_FakeApprover.requests) == 2
        assert _FakeApprover.requests[1]["answer"] == ANSWER
        # Same held answer, same ask_id: the approver can wait on the item it already filed
        # instead of sending the owner a second notice.
        assert _FakeApprover.requests[0]["ask_id"]
        assert _FakeApprover.requests[1]["ask_id"] == _FakeApprover.requests[0]["ask_id"]
        task = _get(c, tid)["result"]
        assert (ANSWER in str(task)) == (verdict == "approve")
    # Decided once: a further restart does not ask again.
    with TestClient(build_app(_cfg())) as c:
        time.sleep(0.2)
        assert _state(c, tid) == final
        assert len(_FakeApprover.requests) == 2


def test_each_held_answer_gets_its_own_ask_id(fakes):
    with TestClient(build_app(_cfg())) as c:
        first = _send(c, message_id="m-1")["id"]
        second = _send(c, message_id="m-2")["id"]
        for tid in (first, second):
            assert _until(c, tid, lambda s: s == "TASK_STATE_COMPLETED") == "TASK_STATE_COMPLETED"
    ids = [r["ask_id"] for r in _FakeApprover.requests]
    assert len(ids) == 2 and len(set(ids)) == 2


def test_a_shed_task_fails_with_a_retry_reason(fakes):
    _FakeRunner.gate = threading.Event()
    with TestClient(build_app(_cfg(approval=False, max_concurrency=1))) as c:
        first = _send(c, message_id="m-1")["id"]
        deadline = time.monotonic() + 5
        while _state(c, first) != "TASK_STATE_WORKING" and time.monotonic() < deadline:
            time.sleep(0.02)
        second = _send(c, message_id="m-2")["id"]
        assert _until(c, second, lambda s: s not in ("TASK_STATE_SUBMITTED", "TASK_STATE_WORKING")) \
            == "TASK_STATE_FAILED"
        msg = _get(c, second)["result"]["status"]["message"]
        assert msg["metadata"]["reason"] == "busy"
        assert msg["metadata"]["retry_after_s"] == 5.0
        _FakeRunner.gate.set()
        assert _until(c, first, lambda s: s == "TASK_STATE_COMPLETED") == "TASK_STATE_COMPLETED"
