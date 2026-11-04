"""One connector token per Bridge: the identity comes from ``X-A2A-Sender``.

``auth.mode: bearer`` takes an optional ``connector_token_env``. A caller holding that
token (the local A2A connector) names who is asking in ``X-A2A-Sender``; the header is
read only after the token matched, is held to the plain-id pattern, and a valid token
without a usable header is a 401, never anonymous. Peer tokens keep working beside it.
The token is only accepted on a loopback bind.
"""
from __future__ import annotations

import dataclasses
import logging
import time

import pytest
from a2a.utils import DEFAULT_RPC_URL
from starlette.testclient import TestClient

import _runtime.config as config_module
import _runtime.server as server_module
from _runtime.access import AccessConfig
from _runtime.auth import AuthConfig, Peer, parse_auth
from _runtime.card import build_agent_card
from _runtime.config import load_agent_config
from _runtime.server import build_app

CONNECTOR = "c" * 40
TOKEN_BOB = "a" * 40
V1 = {"A2A-Version": "1.0"}
SENDER = "X-A2A-Sender"


class _FakeRunner:
    scopes: list = []

    def __init__(self, **_kwargs):
        pass

    async def __call__(self, prompt, *, context_id=None, resume_session_id=None, scope=None):
        _FakeRunner.scopes.append(scope)
        return "ok"

    async def stream(self, prompt, *, context_id=None, resume_session_id=None, scope=None):
        _FakeRunner.scopes.append(scope)
        yield {"kind": "answer", "text": "ok"}


def _cfg(*, peers=(), connector=CONNECTOR, **over):
    cfg = load_agent_config("_template", environment="test")
    auth = AuthConfig(mode="bearer", peers=tuple(peers), connector_token=connector)
    return dataclasses.replace(cfg, trust="peer", auth=auth, **over)


@pytest.fixture
def client_for(monkeypatch):
    monkeypatch.setattr(server_module, "SubprocessClaudeRunner", _FakeRunner)
    _FakeRunner.scopes = []
    opened = []

    def make(cfg):
        c = TestClient(build_app(cfg))
        c.__enter__()
        opened.append(c)
        return c

    yield make
    for c in opened:
        c.__exit__(None, None, None)


def _body(method="SendMessage", **params):
    if method == "SendMessage":
        message = {"role": "ROLE_USER", "messageId": "m-1", "parts": [{"text": "Hallo"}], **params.pop("message", {})}
        params = {"message": message, **params}
    return {"jsonrpc": "2.0", "id": "1", "method": method, "params": params}


def _send(client, headers, **kw):
    return client.post(DEFAULT_RPC_URL, json=_body(**kw), headers={**V1, **headers})


def _conn(sender=None, token=CONNECTOR):
    h = {"Authorization": f"Bearer {token}"}
    if sender is not None:
        h[SENDER] = sender
    return h


# --- auth matrix ----------------------------------------------------------------------

def test_connector_token_with_a_valid_sender_is_answered_as_that_sender(client_for, caplog):
    caplog.set_level(logging.INFO, logger="_runtime.executor")
    r = _send(client_for(_cfg()), _conn("alice"))
    assert r.status_code == 200, r.text
    assert r.json()["result"]["task"]["status"]["state"] == "TASK_STATE_COMPLETED"
    peers = [getattr(rec, "peer", None) for rec in caplog.records if rec.msg == "executor: peer request"]
    assert peers == ["alice"]


@pytest.mark.parametrize("sender", [None, "", " ", "../x", "..", "Alice", "a/b", "-x", "x" * 81, "a b"])
def test_connector_token_without_a_usable_sender_is_401(client_for, sender):
    r = _send(client_for(_cfg()), _conn(sender))
    assert r.status_code == 401
    assert r.headers.get("www-authenticate", "").lower().startswith("bearer")


def test_wrong_token_with_a_sender_header_is_401_and_the_header_is_never_used(client_for, caplog):
    caplog.set_level(logging.INFO)
    r = _send(client_for(_cfg()), _conn("alice", token="w" * 40))
    assert r.status_code == 401
    assert not [rec for rec in caplog.records if getattr(rec, "peer", None) == "alice"]


def test_sender_header_without_a_token_is_401(client_for):
    assert _send(client_for(_cfg()), {SENDER: "alice"}).status_code == 401


def test_peer_token_still_works_beside_the_connector_token(client_for, caplog):
    caplog.set_level(logging.INFO, logger="_runtime.executor")
    client = client_for(_cfg(peers=(Peer(id="bob", token=TOKEN_BOB),)))
    r = _send(client, {"Authorization": f"Bearer {TOKEN_BOB}"})
    assert r.status_code == 200, r.text
    # A peer token names its own peer; a sender header riding along does not rename it.
    r = _send(client, {"Authorization": f"Bearer {TOKEN_BOB}", SENDER: "alice"}, message={"messageId": "m-2"})
    assert r.status_code == 200, r.text
    peers = [getattr(rec, "peer", None) for rec in caplog.records if rec.msg == "executor: peer request"]
    assert peers == ["bob", "bob"]
    assert _send(client, _conn("alice"), message={"messageId": "m-3"}).status_code == 200


def test_tailscale_bound_peer_still_needs_its_identity(client_for):
    peer = Peer(id="bob", token=TOKEN_BOB, tailscale_login="bob@example.org")
    client = client_for(_cfg(peers=(peer,)))
    assert _send(client, {"Authorization": f"Bearer {TOKEN_BOB}"}).status_code == 403


def test_message_metadata_never_changes_the_identity(client_for, caplog):
    caplog.set_level(logging.INFO, logger="_runtime.executor")
    r = _send(client_for(_cfg()), _conn("alice"),
              message={"metadata": {"sender": "bob", "x-a2a-sender": "bob", "X-A2A-Sender": "bob"}},
              metadata={"sender": "bob", "X-A2A-Sender": "bob"})
    assert r.status_code == 200, r.text
    peers = [getattr(rec, "peer", None) for rec in caplog.records if rec.msg == "executor: peer request"]
    assert peers == ["alice"]


def test_the_card_stays_readable_and_describes_the_connector_token():
    card = build_agent_card(_cfg())
    text = card.security_schemes["bearer"].http_auth_security_scheme.description
    assert "Per-peer token issued" not in text
    assert "X-A2A-Sender" in text


def test_the_card_for_peer_tokens_only_still_says_per_peer():
    card = build_agent_card(_cfg(peers=(Peer(id="bob", token=TOKEN_BOB),), connector=None))
    text = card.security_schemes["bearer"].http_auth_security_scheme.description
    assert "Per-peer token" in text and "X-A2A-Sender" not in text


# --- config ---------------------------------------------------------------------------

def test_parse_auth_reads_the_connector_token_and_allows_no_peers(monkeypatch):
    monkeypatch.setenv("AGENT_CONNECTOR_TOKEN", CONNECTOR)
    auth = parse_auth("x", {"mode": "bearer", "connector_token_env": "AGENT_CONNECTOR_TOKEN", "peers": []})
    assert auth.enabled and auth.peers == () and auth.connector_token == CONNECTOR
    assert CONNECTOR not in repr(auth)


@pytest.mark.parametrize("env", [None, "short"])
def test_parse_auth_refuses_a_missing_or_weak_connector_token(monkeypatch, env):
    monkeypatch.delenv("AGENT_CONNECTOR_TOKEN", raising=False)
    if env:
        monkeypatch.setenv("AGENT_CONNECTOR_TOKEN", env)
    with pytest.raises(ValueError):
        parse_auth("x", {"mode": "bearer", "connector_token_env": "AGENT_CONNECTOR_TOKEN"})


def test_parse_auth_refuses_the_connector_token_equal_to_a_peer_token(monkeypatch):
    monkeypatch.setenv("AGENT_CONNECTOR_TOKEN", CONNECTOR)
    monkeypatch.setenv("PEER_T", CONNECTOR)
    with pytest.raises(ValueError):
        parse_auth("x", {"mode": "bearer", "connector_token_env": "AGENT_CONNECTOR_TOKEN",
                         "peers": [{"id": "bob", "token_env": "PEER_T"}]})


def test_a_bearer_block_without_peers_and_without_connector_token_is_still_refused():
    with pytest.raises(ValueError):
        parse_auth("x", {"mode": "bearer", "peers": []})


def test_a_raw_connector_token_in_the_file_is_refused():
    with pytest.raises(ValueError):
        parse_auth("x", {"mode": "bearer", "connector_token": CONNECTOR})


def _instance(tmp_path, monkeypatch, host_line=""):
    inst = tmp_path / "ctest"
    share = inst / "share"
    (share / "peers").mkdir(parents=True)
    monkeypatch.setenv("AGENT_CONNECTOR_TOKEN", CONNECTOR)
    (inst / "agent.yaml").write_text(
        f"name: t\ntrust: peer\n{host_line}grounding_dir: {share}\n"
        "access:\n  peers_dir: share/peers\n"
        "allowed_tools: \"Read(/${grounding_dir}/**)\"\n"
        "auth:\n  mode: bearer\n  connector_token_env: AGENT_CONNECTOR_TOKEN\n", "utf-8")
    (inst / "system-prompt.md").write_text("Test.", "utf-8")
    monkeypatch.setattr(config_module, "AGENTS_DIR", tmp_path)


def test_startup_works_with_a_connector_token_and_no_peers(tmp_path, monkeypatch):
    _instance(tmp_path, monkeypatch)
    cfg = load_agent_config("ctest", environment="test")
    assert cfg.auth.connector_token == CONNECTOR and cfg.auth.peers == ()
    assert cfg.access.enabled


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.5", "::", "localhost"])
def test_connector_token_on_a_non_loopback_host_refuses_to_start(tmp_path, monkeypatch, host):
    _instance(tmp_path, monkeypatch, host_line=f"host: \"{host}\"\n")
    with pytest.raises(ValueError, match="loopback"):
        load_agent_config("ctest", environment="test")


@pytest.mark.parametrize("env_host", ["0.0.0.0", "192.168.1.5"])
def test_the_env_override_cannot_open_the_connector_token(tmp_path, monkeypatch, env_host):
    _instance(tmp_path, monkeypatch)
    monkeypatch.setenv("AGENT_HOST", env_host)
    with pytest.raises(ValueError, match="loopback"):
        load_agent_config("ctest", environment="test")


@pytest.mark.parametrize("host", ["127.0.0.1", "::1"])
def test_loopback_hosts_are_accepted(tmp_path, monkeypatch, host):
    _instance(tmp_path, monkeypatch, host_line=f"host: \"{host}\"\n")
    assert load_agent_config("ctest", environment="test").host == host


def test_a_later_host_override_is_caught_when_the_app_is_built(monkeypatch):
    monkeypatch.setattr(server_module, "SubprocessClaudeRunner", _FakeRunner)
    cfg = _cfg()
    cfg.host = "0.0.0.0"   # what ``--host`` does after the config loaded
    with pytest.raises(ValueError, match="loopback"):
        build_app(cfg)


def test_peer_tokens_alone_may_bind_anywhere(monkeypatch):
    monkeypatch.setattr(server_module, "SubprocessClaudeRunner", _FakeRunner)
    cfg = _cfg(peers=(Peer(id="bob", token=TOKEN_BOB),), connector=None)
    cfg.host = "0.0.0.0"
    build_app(cfg)


# --- unknown sender: REJECTED, not FAILED -----------------------------------------------

def _poll(client, headers, task_id):
    deadline = time.monotonic() + 10
    while True:
        r = client.post(DEFAULT_RPC_URL, json=_body("GetTask", id=task_id), headers={**V1, **headers})
        task = r.json()["result"]
        if task["status"]["state"] not in ("TASK_STATE_SUBMITTED", "TASK_STATE_WORKING"):
            return task
        assert time.monotonic() < deadline, task
        time.sleep(0.05)


def _ask(client, headers, **kw):
    r = _send(client, headers, configuration={"returnImmediately": True}, **kw)
    assert r.status_code == 200, r.text
    return _poll(client, headers, r.json()["result"]["task"]["id"])


def _with_folders(tmp_path, *known):
    peers = tmp_path / "share" / "peers"
    for pid in known:
        (peers / pid).mkdir(parents=True)
        (peers / pid / "index.md").write_text(f"Index for {pid}", "utf-8")
    return _cfg(
        access=AccessConfig(peers_dir=peers),
        base_system_prompt="You are a test agent.",
        inline_grounding=["index.md"],
        allowed_tools="Read(/${grounding_dir}/**)",
    )


def test_an_unknown_sender_without_a_folder_is_rejected(client_for, tmp_path):
    client = client_for(_with_folders(tmp_path, "alice"))
    task = _ask(client, _conn("stranger"))
    assert task["status"]["state"] == "TASK_STATE_REJECTED"
    assert _FakeRunner.scopes == []
    assert _ask(client, _conn("alice"), message={"messageId": "m-2"})["status"]["state"] == "TASK_STATE_COMPLETED"


# --- two senders, one contextId --------------------------------------------------------

def test_two_senders_with_the_same_context_id_stay_separated(client_for, tmp_path):
    client = client_for(_with_folders(tmp_path, "alice", "bob"))
    a = _ask(client, _conn("alice"), message={"contextId": "shared", "parts": [{"text": "mine"}]})
    # bob cannot read alice's task ...
    r = client.post(DEFAULT_RPC_URL, json=_body("GetTask", id=a["id"]), headers={**V1, **_conn("bob")})
    assert "error" in r.json(), r.text
    # ... nor continue it by naming its id.
    r = _send(client, _conn("bob"), message={"messageId": "m-9", "taskId": a["id"], "contextId": "shared"})
    assert "error" in r.json() or r.json()["result"]["task"]["id"] != a["id"], r.text
    # and alice's history holds no turn of bob's
    b = _ask(client, _conn("bob"), message={"messageId": "m-3", "contextId": "shared", "parts": [{"text": "theirs"}]})
    assert b["id"] != a["id"]
    texts = [p.get("text") for m in a.get("history", []) for p in m.get("parts", [])]
    assert "theirs" not in texts
