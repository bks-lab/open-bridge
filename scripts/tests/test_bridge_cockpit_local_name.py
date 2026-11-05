# SPDX-License-Identifier: MIT
"""Contract for the cockpit's own local name and its login item (docs/bridge-cockpit.md, A name of its own).

- `cockpit.local_name: <label>` lets the server answer under `<label>.localhost:<port>` beside 127.0.0.1 and
  localhost: exactly that one name, for the Host header and for the Origin of every click, never any other
  `.localhost` name. Without it nothing changes. A value that is no DNS label stops the start, as a bad port does;
- server.json names it, so `url`, `open` and `status` print the address the running server takes;
- the login item's label and path come from one place (lib/bridge_cockpit/autostart.py), which the CLI and the
  Setup page both read.

Run: pytest -q scripts/tests/test_bridge_cockpit_local_name.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_bridge_cockpit import World, private_key_dir  # noqa: E402,F401  (the autouse fixture comes along)
from lib.bridge_cockpit import autostart  # noqa: E402
from lib.bridge_cockpit.config import WebConfigError, load_web_config  # noqa: E402

CLI = ROOT / "scripts" / "bridge-cockpit.py"
NAMED = "cockpit:\n  enabled: true\n  language: en\n  local_name: my-bridge\n"


def cli():
    spec = importlib.util.spec_from_file_location("cockpit_cli_local_name", CLI)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def named(tmp_path):
    w = World(tmp_path, config=NAMED)
    yield w
    w.close()


@pytest.fixture
def plain_world(tmp_path):
    w = World(tmp_path / "plain")
    yield w
    w.close()


# ---------------------------------------------------------------- config

@pytest.mark.parametrize("value", ["my-bridge", "bks-open-bridge", "a", "x1"])
def test_a_dns_label_is_kept(tmp_path, value):
    assert load_web_config(tmp_path, {"cockpit": {"enabled": True, "local_name": value}}).local_name == value


def test_without_it_there_is_none(tmp_path):
    assert load_web_config(tmp_path, {"cockpit": {"enabled": True}}).local_name is None


@pytest.mark.parametrize("value", ["My-Bridge", "-x", "x-", "a.b", "my bridge", "x" * 64, "", 7, True,
                                   "evil.example", "bridge.localhost"])
def test_anything_else_refuses_to_start(tmp_path, value):
    with pytest.raises(WebConfigError, match="cockpit.local_name"):
        load_web_config(tmp_path, {"cockpit": {"enabled": True, "local_name": value}})


# ---------------------------------------------------------------- the server takes that one name

def test_the_local_name_opens_the_page_and_the_api(named):
    host = f"my-bridge.localhost:{named.port}"
    status, _, body = named.request("GET", "/api/health", host=host)
    assert status == 200 and json.loads(body)["ok"] is True
    status, _, _ = named.request("GET", "/api/state", headers=named.cookie, host=host)
    assert status == 200


def test_a_click_from_the_local_name_counts_as_the_page(named):
    payload = {"verb": "urgency", "args": {"key": "inbox:x", "value": "now"}}
    status, _, body = named.post("/api/action", payload, {"Origin": f"http://my-bridge.localhost:{named.port}",
                                                          "Sec-Fetch-Site": "same-origin"})
    assert json.loads(body).get("error", {}).get("code") != "forbidden_origin" and status != 403


@pytest.mark.parametrize("host", ["other.localhost:{port}", "my-bridge.localhost:{other}", "my-bridge.localhost",
                                  "x.my-bridge.localhost:{port}", "my-bridge.localhost.evil.example:{port}"])
def test_every_other_name_stays_refused(named, host):
    host = host.format(port=named.port, other=named.port + 1)
    status, _, body = named.request("GET", "/api/health", host=host)
    assert status == 403 and json.loads(body)["error"]["code"] == "bad_host"


@pytest.mark.parametrize("origin", ["http://other.localhost:{port}", "https://my-bridge.localhost:{port}",
                                    "http://my-bridge.localhost:{other}"])
def test_every_other_origin_stays_refused(named, origin):
    payload = {"verb": "urgency", "args": {"key": "inbox:x", "value": "now"}}
    origin = origin.format(port=named.port, other=named.port + 1)
    status, _, body = named.post("/api/action", payload, {"Origin": origin})
    assert status == 403 and json.loads(body)["error"]["code"] == "forbidden_origin"


def test_without_a_local_name_no_localhost_name_opens_anything(plain_world):
    status, _, _ = plain_world.request("GET", "/api/health", host=f"my-bridge.localhost:{plain_world.port}")
    assert status == 403


def test_server_json_names_it(named, plain_world):
    assert named.app.server_json()["local_name"] == "my-bridge"
    assert plain_world.app.server_json()["local_name"] is None


# ---------------------------------------------------------------- the CLI prints the address the server takes

def test_the_address_follows_the_running_server(tmp_path):
    c = cli()
    assert c.plain(8797) == "http://127.0.0.1:8797/"
    assert c.plain(8797, "my-bridge") == "http://my-bridge.localhost:8797/"
    state = tmp_path / "state"
    state.mkdir()
    (state / "token").write_text("k" * 43, encoding="utf-8")
    assert c.link({"port": 8797, "local_name": "my-bridge"}, state).startswith("http://my-bridge.localhost:8797/?code=")
    assert c.link({"port": 8797}, state).startswith("http://127.0.0.1:8797/?code=")


# ---------------------------------------------------------------- the login item, from one place

def test_the_cli_and_the_setup_page_name_the_same_login_item(tmp_path, monkeypatch):
    monkeypatch.setattr(autostart, "LAUNCH_AGENTS", tmp_path / "agents")
    root = tmp_path / "bridge"
    label, _ = cli().launch_agent(root, tmp_path / "state", "/usr/bin/python3", "/usr/bin:/bin")
    assert label == autostart.label(root)
    assert autostart.plist_path(root) == tmp_path / "agents" / f"{label}.plist"
    assert autostart.installed(root) is False
    (tmp_path / "agents").mkdir()
    autostart.plist_path(root).write_text("<plist/>", encoding="utf-8")
    assert autostart.installed(root) is True
