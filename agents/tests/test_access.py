"""Per-peer grounding and owner-granted access.

Two promises. First: a peer reads only its own folder, so what one Bridge may see is
decided by the folder the owner builds for it, never by a prompt. Second: when the
answer needs a topic the owner keeps "on request", the agent says so with a
``⟦access:<topic>⟧`` line, the owner is asked about the TOPIC (not about a refusal),
and a yes re-answers the question with that topic opened, so the peer gets what the
owner released.

Hermetic: the runner and the approver are fakes, the grant command is a short
``python3 -c`` program that creates a folder.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import sys
import time
from pathlib import Path

import pytest
from a2a.utils import DEFAULT_RPC_URL
from starlette.testclient import TestClient

import _runtime.server as server_module
from _runtime.access import (
    AccessConfig,
    GrantConfig,
    parse_access,
    split_access_directive,
)
from _runtime.approval import ApprovalConfig, Decision
from _runtime.auth import AuthConfig, Peer
from _runtime.config import load_agent_config
from _runtime.server import build_app

ALICE = "a" * 40
BOB = "b" * 40
V1 = {"A2A-Version": "1.0"}


def _auth(token):
    return {**V1, "Authorization": f"Bearer {token}"}


class _FakeRunner:
    """Answers from a script; records the scope of every call."""

    script: list = []
    scopes: list = []

    def __init__(self, **_kwargs):
        pass

    def _next(self, scope):
        _FakeRunner.scopes.append(scope)
        item = _FakeRunner.script.pop(0) if _FakeRunner.script else "plain answer"
        return item(scope) if callable(item) else item

    async def __call__(self, prompt, *, context_id=None, resume_session_id=None, scope=None):
        return self._next(scope)

    async def stream(self, prompt, *, context_id=None, resume_session_id=None, scope=None):
        yield {"kind": "answer", "text": self._next(scope)}


class _FakeApprover:
    decisions: list = []
    requests: list = []
    notices: list = []

    def __init__(self, cfg, **_kwargs):
        pass

    async def __call__(self, request):
        _FakeApprover.requests.append(request)
        if _FakeApprover.decisions:
            return _FakeApprover.decisions.pop(0)
        return Decision("approve")

    async def notice(self, request):
        _FakeApprover.notices.append(request)


def _peers_tree(tmp_path) -> Path:
    peers = tmp_path / "inst" / "share" / "peers"
    for pid, text in (("alice", "Index for alice"), ("bob", "Index for bob")):
        (peers / pid).mkdir(parents=True)
        (peers / pid / "index.md").write_text(text, "utf-8")
    return peers


_GRANT_PROGRAM = r"""
import json, pathlib, sys
req = json.loads(sys.stdin.read())
log = pathlib.Path(sys.argv[1])
with log.open("a") as f:
    f.write(json.dumps(req) + "\n")
if req["action"] == "grant":
    d = pathlib.Path(sys.argv[2]) / req["peer"] / req["task_id"]
    d.mkdir(parents=True, exist_ok=True)
    (d / "index.md").write_text("Index with " + req["topic"])
    print(json.dumps({"grounding_dir": str(sys.argv[3] if len(sys.argv) > 3 else d)}))
"""


def _cfg(tmp_path, *, grant=True, grant_dir_override=None):
    peers = _peers_tree(tmp_path)
    grants = peers.parent / "grants"
    argv = [sys.executable, "-c", _GRANT_PROGRAM, str(tmp_path / "grant.log"), str(grants)]
    if grant_dir_override:
        argv.append(str(grant_dir_override))
    cfg = load_agent_config("_template", environment="test")
    return dataclasses.replace(
        cfg,
        trust="peer",
        auth=AuthConfig(mode="bearer", peers=(Peer(id="alice", token=ALICE), Peer(id="bob", token=BOB))),
        approval=ApprovalConfig(command=("fake",), timeout_sec=60),
        access=AccessConfig(
            peers_dir=peers,
            grant=GrantConfig(command=tuple(argv), timeout_sec=30) if grant else None,
        ),
        base_system_prompt="You are a test agent.",
        inline_grounding=["index.md"],
        allowed_tools="Read(/${grounding_dir}/**),Glob(/${grounding_dir}/**)",
    )


@pytest.fixture
def make_client(monkeypatch):
    monkeypatch.setattr(server_module, "SubprocessClaudeRunner", _FakeRunner)
    monkeypatch.setattr(server_module, "CommandApprover", _FakeApprover)
    _FakeRunner.script = []
    _FakeRunner.scopes = []
    _FakeApprover.decisions = []
    _FakeApprover.requests = []
    _FakeApprover.notices = []
    opened = []

    def make(cfg):
        c = TestClient(build_app(cfg))
        c.__enter__()
        opened.append(c)
        return c

    yield make
    for c in opened:
        c.__exit__(None, None, None)


def _ask(client, token, text="What do you know about the machine?", message_id="m-1"):
    message = {"role": "ROLE_USER", "messageId": message_id, "parts": [{"text": text}]}
    r = client.post(DEFAULT_RPC_URL, json={"jsonrpc": "2.0", "id": "1", "method": "SendMessage",
                                           "params": {"message": message,
                                                      "configuration": {"returnImmediately": True}}},
                    headers=_auth(token))
    assert r.status_code == 200, r.text
    task_id = r.json()["result"]["task"]["id"]
    deadline = time.monotonic() + 10
    while True:
        r = client.post(DEFAULT_RPC_URL, json={"jsonrpc": "2.0", "id": "2", "method": "GetTask",
                                               "params": {"id": task_id}}, headers=_auth(token))
        task = r.json()["result"]
        if task["status"]["state"] not in ("TASK_STATE_SUBMITTED", "TASK_STATE_WORKING"):
            return task
        assert time.monotonic() < deadline, task
        time.sleep(0.05)


def _text(task):
    parts = [p.get("text", "") for a in task.get("artifacts", []) for p in a.get("parts", [])]
    parts += [p.get("text", "") for p in (task["status"].get("message") or {}).get("parts", [])]
    return " ".join(parts)


def _grant_log(tmp_path):
    path = tmp_path / "grant.log"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


# --- the directive ------------------------------------------------------------------

def test_split_takes_a_trailing_access_line():
    text, topic = split_access_directive("Asking the owner.\n⟦access:bigpc⟧")
    assert (text, topic) == ("Asking the owner.", "bigpc")


def test_split_tolerates_backticks_and_blank_lines():
    text, topic = split_access_directive("One moment.\n\n`⟦ access:labs ⟧`\n\n")
    assert (text, topic) == ("One moment.", "labs")


def test_split_drops_an_unusable_topic_without_granting_anything():
    for bad in ("../secrets", "A B", "x" * 200, ""):
        text, topic = split_access_directive(f"One moment.\n⟦access:{bad}⟧")
        assert topic is None
        assert "access" not in text


def test_split_leaves_prose_alone():
    prose = "Die Zeile ⟦access:x⟧ steht mitten im Satz und bleibt."
    assert split_access_directive(prose) == (prose, None)


# --- configuration ------------------------------------------------------------------

_OK = {"allowed_tools": "Read(/${grounding_dir}/**)", "extra_read_dirs": [], "has_approval": True}

def test_parse_access_needs_a_folder_for_every_peer(tmp_path):
    inst = tmp_path / "inst"
    (inst / "share" / "peers" / "alice").mkdir(parents=True)
    with pytest.raises(ValueError, match="bob"):
        parse_access("x", {"peers_dir": "share/peers"}, inst_dir=inst, tools_dir=str(inst / "tools"),
                     trust="peer", peer_ids=["alice", "bob"], **_OK)


def test_parse_access_is_for_peer_agents_only(tmp_path):
    with pytest.raises(ValueError, match="peer"):
        parse_access("x", {"peers_dir": "share/peers"}, inst_dir=tmp_path, tools_dir="t",
                     trust="public", peer_ids=[], **_OK)


def test_parse_access_keeps_the_folder_inside_the_instance(tmp_path):
    inst = tmp_path / "inst"
    inst.mkdir()
    with pytest.raises(ValueError, match="inside"):
        parse_access("x", {"peers_dir": "../elsewhere"}, inst_dir=inst, tools_dir="t",
                     trust="peer", peer_ids=[], **_OK)


def test_parse_access_resolves_the_grant_command(tmp_path):
    inst = tmp_path / "inst"
    (inst / "share" / "peers" / "alice").mkdir(parents=True)
    cfg = parse_access("x", {"peers_dir": "share/peers",
                             "grant": {"command": ["python3", "${tools_dir}/grant.py"]}},
                       inst_dir=inst, tools_dir="/abs/tools", trust="peer", peer_ids=["alice"], **_OK)
    assert cfg.peers_dir == (inst / "share" / "peers").resolve()
    assert cfg.grant.command == ("python3", "/abs/tools/grant.py")


# --- one folder per peer -------------------------------------------------------------

def test_each_peer_runs_in_its_own_folder(make_client, tmp_path):
    cfg = _cfg(tmp_path)
    client = make_client(cfg)
    _ask(client, ALICE)
    _ask(client, BOB, message_id="m-2")
    alice, bob = _FakeRunner.scopes
    assert alice.working_dir == str(cfg.access.peers_dir / "alice")
    assert bob.working_dir == str(cfg.access.peers_dir / "bob")
    assert "Index for alice" in alice.system_prompt and "Index for bob" not in alice.system_prompt
    assert "Index for bob" in bob.system_prompt and "Index for alice" not in bob.system_prompt
    assert alice.allowed_tools == f"Read(/{cfg.access.peers_dir / 'alice'}/**),Glob(/{cfg.access.peers_dir / 'alice'}/**)"


def test_the_folder_is_read_fresh_on_every_request(make_client, tmp_path):
    cfg = _cfg(tmp_path)
    client = make_client(cfg)
    _ask(client, ALICE)
    (cfg.access.peers_dir / "alice" / "index.md").write_text("Index for alice, rebuilt", "utf-8")
    _ask(client, ALICE, message_id="m-2")
    assert "rebuilt" in _FakeRunner.scopes[1].system_prompt


def test_a_peer_whose_folder_vanished_gets_nothing(make_client, tmp_path):
    cfg = _cfg(tmp_path)
    client = make_client(cfg)
    for f in (cfg.access.peers_dir / "bob").iterdir():
        f.unlink()
    (cfg.access.peers_dir / "bob").rmdir()
    task = _ask(client, BOB)
    assert task["status"]["state"] == "TASK_STATE_FAILED"
    assert _FakeRunner.scopes == []


# --- asking the owner for a topic -----------------------------------------------------

def test_an_access_line_asks_the_owner_about_the_topic(make_client, tmp_path):
    cfg = _cfg(tmp_path)
    _FakeRunner.script = ["The owner has to open this.\n⟦access:bigpc⟧", "Ryzen 9, 128 GB, RTX 4090."]
    _FakeApprover.decisions = [Decision("approve", grant="once")]
    task = _ask(make_client(cfg), ALICE)
    asked = _FakeApprover.requests[0]
    assert asked["kind"] == "access"
    assert asked["topic"] == "bigpc"
    assert asked["peer"] == "alice"
    assert "⟦" not in asked["answer"]
    assert task["status"]["state"] == "TASK_STATE_COMPLETED"
    assert "RTX 4090" in _text(task)
    assert "has to open" not in _text(task)


def test_a_yes_reanswers_inside_the_granted_folder(make_client, tmp_path):
    cfg = _cfg(tmp_path)
    _FakeRunner.script = ["One moment.\n⟦access:bigpc⟧", "Answer with access."]
    _FakeApprover.decisions = [Decision("approve", grant="once")]
    _ask(make_client(cfg), ALICE)
    first, second = _FakeRunner.scopes
    granted = cfg.access.peers_dir.parent / "grants"
    assert first.working_dir == str(cfg.access.peers_dir / "alice")
    assert Path(second.working_dir).parent == granted / "alice"
    assert "Index with bigpc" in second.system_prompt
    assert str(second.working_dir) in second.allowed_tools


def test_the_grant_command_learns_scope_and_is_released_afterwards(make_client, tmp_path):
    cfg = _cfg(tmp_path)
    _FakeRunner.script = ["One moment.\n⟦access:bigpc⟧", "Answer."]
    _FakeApprover.decisions = [Decision("approve", grant="always")]
    _ask(make_client(cfg), ALICE)
    grant, release = _grant_log(tmp_path)
    assert grant["action"] == "grant" and grant["scope"] == "always"
    assert grant["peer"] == "alice" and grant["topic"] == "bigpc"
    assert release["action"] == "release" and release["task_id"] == grant["task_id"]


def test_the_reanswer_goes_out_without_a_second_card_but_with_a_notice(make_client, tmp_path):
    cfg = _cfg(tmp_path)
    _FakeRunner.script = ["One moment.\n⟦access:bigpc⟧", "Answer with access."]
    _FakeApprover.decisions = [Decision("approve", grant="once")]
    _ask(make_client(cfg), ALICE)
    assert [r["kind"] for r in _FakeApprover.requests] == ["access"]
    notice = _FakeApprover.notices[0]
    assert notice["kind"] == "notice" and notice["answer"] == "Answer with access."
    assert notice["topic"] == "bigpc"


@pytest.mark.parametrize("decision", [Decision("approve"), Decision("edit", "text")])
def test_access_needs_an_explicit_grant(make_client, tmp_path, decision):
    # An approver that does not know kind: access shows a harmless-looking draft; its
    # plain yes must not open a topic.
    cfg = _cfg(tmp_path)
    _FakeRunner.script = ["One moment.\n⟦access:bigpc⟧", "must not run"]
    _FakeApprover.decisions = [decision]
    task = _ask(make_client(cfg), ALICE)
    assert task["status"]["state"] == "TASK_STATE_REJECTED"
    assert _grant_log(tmp_path) == []
    assert len(_FakeRunner.scopes) == 1


@pytest.mark.parametrize("verdict", ["reject", "timeout", "error"])
def test_no_yes_opens_nothing(make_client, tmp_path, verdict):
    cfg = _cfg(tmp_path)
    _FakeRunner.script = ["One moment.\n⟦access:bigpc⟧"]
    _FakeApprover.decisions = [Decision(verdict)]
    task = _ask(make_client(cfg), ALICE)
    assert task["status"]["state"] == "TASK_STATE_REJECTED"
    assert _grant_log(tmp_path) == []
    assert len(_FakeRunner.scopes) == 1


def test_a_grant_folder_outside_the_share_is_refused(make_client, tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    cfg = _cfg(tmp_path, grant_dir_override=outside)
    _FakeRunner.script = ["One moment.\n⟦access:bigpc⟧", "must not run"]
    _FakeApprover.decisions = [Decision("approve", grant="once")]
    task = _ask(make_client(cfg), ALICE)
    assert task["status"]["state"] == "TASK_STATE_FAILED"
    assert len(_FakeRunner.scopes) == 1
    assert [e["action"] for e in _grant_log(tmp_path)] == ["grant", "release"]


def test_a_grant_folder_of_another_peer_is_refused(make_client, tmp_path):
    cfg = _cfg(tmp_path, grant_dir_override=tmp_path / "inst" / "share" / "peers" / "bob")
    _FakeRunner.script = ["One moment.\n⟦access:bigpc⟧", "must not run"]
    _FakeApprover.decisions = [Decision("approve", grant="once")]
    task = _ask(make_client(cfg), ALICE)
    assert task["status"]["state"] == "TASK_STATE_FAILED"
    assert len(_FakeRunner.scopes) == 1


def test_the_reanswer_cannot_ask_again(make_client, tmp_path):
    cfg = _cfg(tmp_path)
    _FakeRunner.script = ["One moment.\n⟦access:bigpc⟧", "More?\n⟦access:other⟧"]
    _FakeApprover.decisions = [Decision("approve", grant="once")]
    task = _ask(make_client(cfg), ALICE)
    assert [r["kind"] for r in _FakeApprover.requests] == ["access"]
    assert _text(task).strip().startswith("More?")
    assert "⟦" not in _text(task)


def test_without_a_grant_command_the_line_is_dropped_and_the_answer_is_approved_as_usual(make_client, tmp_path):
    cfg = _cfg(tmp_path, grant=False)
    _FakeRunner.script = ["Nothing on that.\n⟦access:bigpc⟧"]
    task = _ask(make_client(cfg), ALICE)
    assert "kind" not in _FakeApprover.requests[0]
    assert "⟦" not in _FakeApprover.requests[0]["answer"]
    assert "⟦" not in _text(task)


def test_an_answer_without_the_line_is_approved_as_usual(make_client, tmp_path):
    cfg = _cfg(tmp_path)
    _FakeRunner.script = ["Hello back."]
    task = _ask(make_client(cfg), ALICE)
    assert "kind" not in _FakeApprover.requests[0]
    assert _grant_log(tmp_path) == []
    assert "Hello back." in _text(task)


# --- the approver's side --------------------------------------------------------------

def test_the_approver_reads_a_grant(tmp_path):
    from _runtime.approval import CommandApprover

    prog = 'import sys,json; sys.stdin.read(); print(json.dumps({"decision":"approve","grant":"always"}))'
    approver = CommandApprover(ApprovalConfig(command=(sys.executable, "-c", prog), timeout_sec=10))
    decision = asyncio.run(approver({"kind": "access", "topic": "x"}))
    assert decision.verdict == "approve" and decision.grant == "always"


def test_an_unknown_grant_fails_closed(tmp_path):
    from _runtime.approval import CommandApprover

    prog = 'import sys,json; sys.stdin.read(); print(json.dumps({"decision":"approve","grant":"forever"}))'
    approver = CommandApprover(ApprovalConfig(command=(sys.executable, "-c", prog), timeout_sec=10))
    assert asyncio.run(approver({"kind": "access", "topic": "x"})).verdict == "error"


# --- review round 17.10. ------------------------------------------------------------

def test_history_does_not_cross_peers_on_the_same_context(make_client, tmp_path):
    cfg = _cfg(tmp_path)
    client = make_client(cfg)
    prompts = []

    def remember(scope):
        return "secret for alice"
    _FakeRunner.script = [remember, "bob answer"]
    orig = _FakeRunner.stream

    async def stream(self, prompt, **kw):
        prompts.append(prompt)
        async for evt in orig(self, prompt, **kw):
            yield evt
    _FakeRunner.stream = stream
    try:
        for token, mid in ((ALICE, "m-1"), (BOB, "m-2")):
            message = {"role": "ROLE_USER", "messageId": mid, "contextId": "shared",
                       "parts": [{"text": "hello"}]}
            r = client.post(DEFAULT_RPC_URL, json={"jsonrpc": "2.0", "id": "1", "method": "SendMessage",
                                                   "params": {"message": message}}, headers=_auth(token))
            assert r.status_code == 200, r.text
    finally:
        _FakeRunner.stream = orig
    assert "secret for alice" not in prompts[1]


@pytest.mark.parametrize("tools", ["Read,Glob,Grep", "Read(//etc/**)", "Bash(ls:*)",
                                   "Read(/${grounding_dir}/**),Grep"])
def test_access_refuses_tool_rules_that_reach_beyond_the_folder(tmp_path, tools):
    inst = tmp_path / "inst"
    (inst / "share" / "peers" / "alice").mkdir(parents=True)
    with pytest.raises(ValueError, match="allowed_tools"):
        parse_access("x", {"peers_dir": "share/peers"}, inst_dir=inst, tools_dir="t", trust="peer",
                     peer_ids=["alice"], allowed_tools=tools, extra_read_dirs=[], has_approval=True)


def test_access_refuses_extra_read_dirs(tmp_path):
    inst = tmp_path / "inst"
    (inst / "share" / "peers" / "alice").mkdir(parents=True)
    with pytest.raises(ValueError, match="extra_read_dirs"):
        parse_access("x", {"peers_dir": "share/peers"}, inst_dir=inst, tools_dir="t", trust="peer",
                     peer_ids=["alice"], allowed_tools="Read(/${grounding_dir}/**)",
                     extra_read_dirs=["/somewhere"], has_approval=True)


def test_access_grant_needs_an_owner_to_ask(tmp_path):
    inst = tmp_path / "inst"
    (inst / "share" / "peers" / "alice").mkdir(parents=True)
    with pytest.raises(ValueError, match="approval"):
        parse_access("x", {"peers_dir": "share/peers", "grant": {"command": ["x"]}}, inst_dir=inst,
                     tools_dir="t", trust="peer", peer_ids=["alice"],
                     allowed_tools="Read(/${grounding_dir}/**)", extra_read_dirs=[], has_approval=False)


@pytest.mark.parametrize("bad", [".", "..", "a/b", ""])
def test_access_refuses_peer_ids_that_are_paths(tmp_path, bad):
    inst = tmp_path / "inst"
    (inst / "share" / "peers").mkdir(parents=True)
    with pytest.raises(ValueError, match="peer id"):
        parse_access("x", {"peers_dir": "share/peers"}, inst_dir=inst, tools_dir="t", trust="peer",
                     peer_ids=[bad], allowed_tools="Read(/${grounding_dir}/**)", extra_read_dirs=[],
                     has_approval=True)


def test_a_scoped_turn_loads_no_settings_and_no_memory_files():
    from _runtime.access import RunScope
    from _runtime.runner import SubprocessClaudeRunner

    runner = SubprocessClaudeRunner(binary="claude", model="m", system_prompt="p", working_dir="/w")
    cmd = runner._build_cmd("q", stream=True, scope=RunScope("/peer", "Read(//peer/**)", "sp"))
    assert cmd[cmd.index("--setting-sources") + 1] == ""
    assert cmd[cmd.index("--allowedTools") + 1] == "Read(//peer/**)"
    assert "--add-dir" not in cmd


def test_the_notice_does_not_hold_the_answer(make_client, tmp_path):
    cfg = _cfg(tmp_path)
    _FakeRunner.script = ["One moment.\n⟦access:bigpc⟧", "Answer with access."]
    _FakeApprover.decisions = [Decision("approve", grant="once")]
    slow = asyncio.Event()

    async def notice(self, request):
        await slow.wait()                         # never finishes during the test
    orig = _FakeApprover.notice
    _FakeApprover.notice = notice
    try:
        task = _ask(make_client(cfg), ALICE)
    finally:
        _FakeApprover.notice = orig
    assert task["status"]["state"] == "TASK_STATE_COMPLETED"


def test_a_scoped_turn_cannot_write():
    from _runtime.access import RunScope
    from _runtime.runner import SubprocessClaudeRunner

    runner = SubprocessClaudeRunner(binary="claude", model="m", system_prompt="p", working_dir="/w")
    cmd = runner._build_cmd("q", stream=False, scope=RunScope("/peer", "Read(//peer/**)", "sp"))
    assert cmd[cmd.index("--permission-mode") + 1] == "default"
    denied = cmd[cmd.index("--disallowedTools") + 1].split(",")
    for tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        assert tool in denied
