"""Derived peer authentication: any peer the upstream relay vouches for.

``auth.mode: derived`` replaces the per-peer token list with one shared secret. The
relay sends ``X-A2A-Sender: <id>`` and ``Authorization: Bearer <token>``, where the
token is an HMAC of the id under that secret, so the agent recognises a peer it has
never been told about without an edit or a restart. ``peers: open`` takes any
well-formed id, a list restricts to the ids it names.

With ``access:`` a first-time peer gets its folder copied from ``peer_template``;
without a template (or folder) the request fails closed, never falling back to a
broader folder. The owner's approval of every answer is untouched by any of this.
"""
from __future__ import annotations

import dataclasses
import os
import threading
from pathlib import Path

import _runtime.access as access_module
import _runtime.config as config_module
import _runtime.server as server_module
import pytest
from _runtime.access import AccessConfig, ensure_peer_folder, parse_access
from _runtime.auth import (
    DEFAULT_SENDER_HEADER,
    AuthConfig,
    Peer,
    derive_token,
    parse_auth,
)
from _runtime.card import build_agent_card
from _runtime.config import load_agent_config
from _runtime.server import build_app
from a2a.utils import DEFAULT_RPC_URL
from starlette.testclient import TestClient

SECRET = "0123456789abcdef0123456789abcdef"
V1 = {"A2A-Version": "1.0"}


# --- the token ----------------------------------------------------------------------

def test_derived_token_matches_the_pinned_vector():
    # The relay computes the same value independently; this pins the formula.
    assert derive_token(SECRET, "alice") == (
        "6c7cd7e855dec6d02b7cdbfd81294527fcad78e36b55255be42a9bcc99ddce84"
    )


def test_derived_tokens_differ_per_peer_and_per_secret():
    assert derive_token(SECRET, "alice") != derive_token(SECRET, "bob")
    assert derive_token(SECRET, "alice") != derive_token(SECRET + "x", "alice")


# --- configuration: fail closed -------------------------------------------------------

def test_parse_auth_reads_the_secret_from_the_environment(monkeypatch):
    monkeypatch.setenv("AGENT_PEER_SECRET", SECRET)
    auth = parse_auth("x", {"mode": "derived", "secret_env": "AGENT_PEER_SECRET", "peers": "open"})
    assert auth.enabled
    assert auth.mode == "derived"
    assert auth.open_peers
    assert auth.peer_ids is None
    assert auth.sender_header == DEFAULT_SENDER_HEADER == "X-A2A-Sender"


def test_parse_auth_derived_with_a_list(monkeypatch):
    monkeypatch.setenv("AGENT_PEER_SECRET", SECRET)
    auth = parse_auth("x", {"mode": "derived", "secret_env": "AGENT_PEER_SECRET",
                            "sender_header": "X-Relay-Sender", "peers": ["alice", "bob"]})
    assert not auth.open_peers
    assert auth.peer_ids == ("alice", "bob")
    assert auth.sender_header == "X-Relay-Sender"


def test_the_secret_never_shows_in_repr(monkeypatch):
    monkeypatch.setenv("AGENT_PEER_SECRET", SECRET)
    auth = parse_auth("x", {"mode": "derived", "secret_env": "AGENT_PEER_SECRET", "peers": "open"})
    assert SECRET not in repr(auth)


@pytest.mark.parametrize("spec", [
    {"mode": "derived", "peers": "open"},                                           # no secret_env
    {"mode": "derived", "secret_env": "UNSET_PEER_SECRET", "peers": "open"},        # secret missing
    {"mode": "derived", "secret_env": "SHORT_PEER_SECRET", "peers": "open"},        # secret too short
    {"mode": "derived", "secret": SECRET, "secret_env": "AGENT_PEER_SECRET", "peers": "open"},  # raw secret
    {"mode": "derived", "secret_env": "AGENT_PEER_SECRET"},                         # peers not chosen
    {"mode": "derived", "secret_env": "AGENT_PEER_SECRET", "peers": []},            # nobody may call
    {"mode": "derived", "secret_env": "AGENT_PEER_SECRET", "peers": "everyone"},    # typo for open
    {"mode": "derived", "secret_env": "AGENT_PEER_SECRET", "peers": ["Alice"]},     # not a plain id
    {"mode": "derived", "secret_env": "AGENT_PEER_SECRET", "peers": [{"id": "alice"}]},  # not a string
    {"mode": "derived", "secret_env": "AGENT_PEER_SECRET", "peers": "open", "sender_header": ""},
])
def test_parse_auth_derived_refuses_to_start_on_a_bad_block(monkeypatch, spec):
    monkeypatch.delenv("UNSET_PEER_SECRET", raising=False)
    monkeypatch.setenv("SHORT_PEER_SECRET", "s" * 31)
    monkeypatch.setenv("AGENT_PEER_SECRET", SECRET)
    with pytest.raises(ValueError) as exc:
        parse_auth("x", spec)
    assert SECRET not in str(exc.value)


# --- the endpoint -----------------------------------------------------------------------

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


def _derived(*, allowed=None, header=DEFAULT_SENDER_HEADER):
    return AuthConfig(mode="derived", secret=SECRET, sender_header=header,
                      open_peers=allowed is None, allowed=tuple(allowed or ()))


def _cfg(**overrides):
    cfg = load_agent_config("_template", environment="test")
    return dataclasses.replace(cfg, trust="peer", **({"auth": _derived()} | overrides))


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


def _send(client, headers, message_id="m-1"):
    return client.post(
        DEFAULT_RPC_URL,
        json={"jsonrpc": "2.0", "id": "1", "method": "SendMessage", "params": {
            "message": {"role": "ROLE_USER", "messageId": message_id, "parts": [{"text": "Hello"}]}
        }},
        headers={**V1, **headers},
    )


def _as(peer, token=None, header=DEFAULT_SENDER_HEADER):
    return {"Authorization": f"Bearer {token or derive_token(SECRET, peer)}", header: peer}


def _state(r):
    return r.json()["result"]["task"]["status"]["state"]


def test_a_valid_derived_token_with_its_sender_is_answered(client_for):
    r = _send(client_for(_cfg()), _as("alice"))
    assert r.status_code == 200, r.text
    assert _state(r) == "TASK_STATE_COMPLETED"


def test_the_sender_header_name_is_configurable(client_for):
    client = client_for(_cfg(auth=_derived(header="X-Relay-Sender")))
    assert _send(client, _as("alice", header="X-Relay-Sender")).status_code == 200
    assert _send(client, _as("alice")).status_code == 401


def test_a_wrong_token_is_refused_with_401(client_for):
    r = _send(client_for(_cfg()), _as("alice", token="f" * 64))
    assert r.status_code == 401


def test_another_peers_token_is_refused_with_401(client_for):
    r = _send(client_for(_cfg()), _as("alice", token=derive_token(SECRET, "bob")))
    assert r.status_code == 401


def test_a_token_under_another_secret_is_refused_with_401(client_for):
    r = _send(client_for(_cfg()), _as("alice", token=derive_token(SECRET + "x", "alice")))
    assert r.status_code == 401


def test_a_missing_sender_header_is_refused_with_401(client_for):
    r = _send(client_for(_cfg()), {"Authorization": f"Bearer {derive_token(SECRET, 'alice')}"})
    assert r.status_code == 401


def test_no_authorization_is_refused_with_401(client_for):
    r = _send(client_for(_cfg()), {DEFAULT_SENDER_HEADER: "alice"})
    assert r.status_code == 401


@pytest.mark.parametrize("bad", ["Alice", "-alice", "alice-", "a" * 64, "../alice", "al ice",
                                 "al_ice", "_default", ""])
def test_a_bad_sender_id_is_refused_with_401(client_for, bad):
    r = _send(client_for(_cfg()), _as(bad, token=derive_token(SECRET, bad)))
    assert r.status_code == 401


def test_an_id_outside_the_list_is_refused_with_401(client_for):
    client = client_for(_cfg(auth=_derived(allowed=["alice"])))
    assert _send(client, _as("alice")).status_code == 200
    assert _send(client, _as("bob")).status_code == 401


def test_the_peer_id_is_the_authenticated_user(client_for, caplog):
    import logging

    caplog.set_level(logging.INFO, logger="_runtime.executor")
    r = _send(client_for(_cfg()), _as("alice"))
    assert r.status_code == 200, r.text
    peers = [getattr(rec, "peer", None) for rec in caplog.records if rec.msg == "executor: peer request"]
    assert peers == ["alice"]


def test_no_secret_or_token_reaches_the_log(client_for, caplog):
    import logging

    caplog.set_level(logging.DEBUG)
    client = client_for(_cfg())
    _send(client, _as("alice"))
    _send(client, _as("alice", token="f" * 64))
    # The runtime's own lines. (a2a-sdk logs whole request headers at DEBUG, for
    # bearer tokens as much as derived ones; the server runs at INFO.)
    text = "\n".join(rec.getMessage() for rec in caplog.records if rec.name.startswith("_runtime"))
    assert "peer_auth: refused" in text
    assert SECRET not in text
    assert derive_token(SECRET, "alice") not in text


def test_a_hand_built_derived_config_without_secret_refuses_to_start(client_for):
    with pytest.raises(ValueError):
        client_for(_cfg(auth=AuthConfig(mode="derived", secret="", open_peers=True)))


def test_the_card_declares_bearer_in_derived_mode():
    card = build_agent_card(_cfg())
    assert "bearer" in card.security_schemes


# --- bearer mode is unchanged ------------------------------------------------------------

def test_bearer_mode_ignores_the_sender_header(client_for):
    token = "a" * 40
    cfg = _cfg(auth=AuthConfig(mode="bearer", peers=(Peer(id="alice", token=token),)))
    client = client_for(cfg)
    assert _send(client, {"Authorization": f"Bearer {token}"}).status_code == 200
    # A derived token is no bearer token, whatever the sender header claims.
    assert _send(client, _as("alice")).status_code == 401


# --- per-peer folders from a template -----------------------------------------------------

def _share(tmp_path, *, template=True) -> tuple[Path, Path]:
    peers = tmp_path / "inst" / "share" / "peers"
    peers.mkdir(parents=True)
    tpl = peers / "_default"
    if template:
        (tpl / "notes").mkdir(parents=True)
        (tpl / "index.md").write_text("Index from the template", "utf-8")
        (tpl / "notes" / "a.md").write_text("note", "utf-8")
    return peers, tpl


def _access_cfg(tmp_path, *, template=True, allowed=None):
    peers, tpl = _share(tmp_path, template=template)
    return _cfg(
        auth=_derived(allowed=allowed),
        access=AccessConfig(peers_dir=peers, peer_template=tpl if template else None),
        base_system_prompt="You are a test agent.",
        inline_grounding=["index.md"],
        allowed_tools="Read(/${grounding_dir}/**)",
    )


def test_a_first_time_peer_gets_its_folder_from_the_template(client_for, tmp_path):
    cfg = _access_cfg(tmp_path)
    r = _send(client_for(cfg), _as("alice"))
    assert _state(r) == "TASK_STATE_COMPLETED", r.text
    folder = cfg.access.peers_dir / "alice"
    assert (folder / "index.md").read_text("utf-8") == "Index from the template"
    assert (folder / "notes" / "a.md").is_file()
    (scope,) = _FakeRunner.scopes
    assert scope.working_dir == str(folder)
    assert "Index from the template" in scope.system_prompt
    # Only the peer's folder appeared; no temp leftovers beside it.
    assert sorted(p.name for p in cfg.access.peers_dir.iterdir()) == ["_default", "alice"]


def test_an_existing_folder_is_kept_as_it_is(client_for, tmp_path):
    cfg = _access_cfg(tmp_path)
    own = cfg.access.peers_dir / "alice"
    own.mkdir()
    (own / "index.md").write_text("Index built for alice", "utf-8")
    _send(client_for(cfg), _as("alice"))
    assert (own / "index.md").read_text("utf-8") == "Index built for alice"
    assert "Index built for alice" in _FakeRunner.scopes[0].system_prompt


def test_without_a_template_a_new_peer_fails_closed(client_for, tmp_path):
    cfg = _access_cfg(tmp_path, template=False)
    r = _send(client_for(cfg), _as("alice"))
    assert _state(r) == "TASK_STATE_FAILED"
    assert _FakeRunner.scopes == []
    assert not (cfg.access.peers_dir / "alice").exists()


def test_a_configured_but_missing_template_fails_closed(client_for, tmp_path):
    cfg = _access_cfg(tmp_path)
    tpl = cfg.access.peer_template
    for f in sorted(tpl.rglob("*"), reverse=True):
        f.rmdir() if f.is_dir() else f.unlink()
    tpl.rmdir()
    r = _send(client_for(cfg), _as("alice"))
    assert _state(r) == "TASK_STATE_FAILED"
    assert _FakeRunner.scopes == []


def test_the_template_never_carries_a_symlink_out(tmp_path):
    peers, tpl = _share(tmp_path)
    secret_dir = tmp_path / "private"
    secret_dir.mkdir()
    (secret_dir / "secret.md").write_text("private", "utf-8")
    os.symlink(secret_dir, tpl / "linked-dir")
    os.symlink(secret_dir / "secret.md", tpl / "linked-file.md")
    folder = ensure_peer_folder(peers, "alice", tpl)
    assert folder == (peers / "alice").resolve()
    names = {p.name for p in folder.rglob("*")}
    assert "linked-dir" not in names and "linked-file.md" not in names
    assert "secret.md" not in names
    assert not any(p.is_symlink() for p in folder.rglob("*"))


def test_a_template_that_is_itself_a_symlink_is_not_followed(tmp_path):
    peers, _ = _share(tmp_path, template=False)
    real = tmp_path / "elsewhere"
    real.mkdir()
    (real / "index.md").write_text("outside", "utf-8")
    link = peers / "_default"
    os.symlink(real, link)
    assert ensure_peer_folder(peers, "alice", link) is None
    assert not (peers / "alice").exists()


def test_concurrent_first_requests_end_in_one_folder(tmp_path):
    peers, tpl = _share(tmp_path)
    results, errors = [], []
    barrier = threading.Barrier(8)

    def worker():
        try:
            barrier.wait()
            results.append(ensure_peer_folder(peers, "alice", tpl))
        except Exception as exc:  # noqa: BLE001 - surfaced by the assert below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert results == [(peers / "alice").resolve()] * 8
    assert (peers / "alice" / "index.md").read_text("utf-8") == "Index from the template"
    assert sorted(p.name for p in peers.iterdir()) == ["_default", "alice"]


def test_losing_the_rename_race_uses_the_winners_folder(tmp_path, monkeypatch):
    peers, tpl = _share(tmp_path)
    real_rename = os.rename

    def rename_after_the_other_request_won(src, dst):
        # The other first request finishes between our copy and our rename.
        Path(dst).mkdir()
        (Path(dst) / "index.md").write_text("Index from the winner", "utf-8")
        return real_rename(src, dst)

    monkeypatch.setattr(access_module.os, "rename", rename_after_the_other_request_won)
    folder = ensure_peer_folder(peers, "alice", tpl)
    assert folder == (peers / "alice").resolve()
    assert (folder / "index.md").read_text("utf-8") == "Index from the winner"
    assert sorted(p.name for p in peers.iterdir()) == ["_default", "alice"]


def test_ensure_refuses_an_id_that_is_a_path(tmp_path):
    peers, tpl = _share(tmp_path)
    for bad in ("../alice", "", ".alice", "a/b"):
        assert ensure_peer_folder(peers, bad, tpl) is None
    assert sorted(p.name for p in peers.iterdir()) == ["_default"]


# --- startup with folders ------------------------------------------------------------------

_OK = {"allowed_tools": "Read(/${grounding_dir}/**)", "extra_read_dirs": [], "has_approval": True}


def test_open_peers_need_no_folder_at_startup(tmp_path):
    inst = tmp_path / "inst"
    (inst / "share" / "peers" / "_default").mkdir(parents=True)
    cfg = parse_access("x", {"peers_dir": "share/peers", "peer_template": "share/peers/_default"},
                       inst_dir=inst, tools_dir="t", trust="peer", peer_ids=None, **_OK)
    assert cfg.peer_template == (inst / "share" / "peers" / "_default").resolve()


def test_a_listed_peer_still_needs_its_folder_at_startup(tmp_path):
    inst = tmp_path / "inst"
    (inst / "share" / "peers" / "_default").mkdir(parents=True)
    with pytest.raises(ValueError, match="alice"):
        parse_access("x", {"peers_dir": "share/peers", "peer_template": "share/peers/_default"},
                     inst_dir=inst, tools_dir="t", trust="peer", peer_ids=["alice"], **_OK)


def test_the_template_must_stay_inside_the_instance(tmp_path):
    inst = tmp_path / "inst"
    (inst / "share" / "peers").mkdir(parents=True)
    with pytest.raises(ValueError, match="peer_template"):
        parse_access("x", {"peers_dir": "share/peers", "peer_template": "../outside"},
                     inst_dir=inst, tools_dir="t", trust="peer", peer_ids=None, **_OK)


def test_the_template_cannot_be_a_peer_folder(tmp_path):
    inst = tmp_path / "inst"
    (inst / "share" / "peers" / "alice").mkdir(parents=True)
    with pytest.raises(ValueError, match="peer_template"):
        parse_access("x", {"peers_dir": "share/peers", "peer_template": "share/peers/alice"},
                     inst_dir=inst, tools_dir="t", trust="peer", peer_ids=None, **_OK)


def _write_instance(tmp_path, body):
    inst = tmp_path / "peertest"
    inst.mkdir()
    (inst / "agent.yaml").write_text(body, "utf-8")
    (inst / "system-prompt.md").write_text("You are a test.", "utf-8")
    return inst


def test_load_agent_config_wires_derived_open_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_PEER_SECRET", SECRET)
    inst = _write_instance(tmp_path, (
        "name: t\ntrust: peer\n"
        'allowed_tools: "Read(/${grounding_dir}/**)"\n'
        "auth:\n  mode: derived\n  secret_env: AGENT_PEER_SECRET\n  peers: open\n"
        'access:\n  peers_dir: "share/peers"\n  peer_template: "share/peers/_default"\n'
    ))
    (inst / "share" / "peers" / "_default").mkdir(parents=True)
    monkeypatch.setattr(config_module, "AGENTS_DIR", tmp_path)
    cfg = load_agent_config("peertest", environment="test")
    assert cfg.auth.mode == "derived" and cfg.auth.open_peers
    assert cfg.access.peers_dir == (inst / "share" / "peers").resolve()
    assert cfg.access.peer_template == (inst / "share" / "peers" / "_default").resolve()


def test_load_agent_config_refuses_derived_without_secret(monkeypatch, tmp_path):
    monkeypatch.delenv("AGENT_PEER_SECRET", raising=False)
    _write_instance(tmp_path, (
        "name: t\ntrust: peer\n"
        "auth:\n  mode: derived\n  secret_env: AGENT_PEER_SECRET\n  peers: open\n"
    ))
    monkeypatch.setattr(config_module, "AGENTS_DIR", tmp_path)
    with pytest.raises(ValueError, match="secret"):
        load_agent_config("peertest", environment="test")


def test_load_agent_config_keeps_the_startup_check_for_a_list(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_PEER_SECRET", SECRET)
    inst = _write_instance(tmp_path, (
        "name: t\ntrust: peer\n"
        'allowed_tools: "Read(/${grounding_dir}/**)"\n'
        "auth:\n  mode: derived\n  secret_env: AGENT_PEER_SECRET\n  peers: [alice]\n"
        'access:\n  peers_dir: "share/peers"\n'
    ))
    (inst / "share" / "peers").mkdir(parents=True)
    monkeypatch.setattr(config_module, "AGENTS_DIR", tmp_path)
    with pytest.raises(ValueError, match="alice"):
        load_agent_config("peertest", environment="test")

