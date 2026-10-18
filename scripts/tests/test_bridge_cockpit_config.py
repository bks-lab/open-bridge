# SPDX-License-Identifier: MIT
"""Contract for the check of the cockpit: block (scripts/lib/bridge_cockpit/config.py, #402).

The loader keeps every fallback it had (an unknown open_in still opens `auto`), and now also says so: each
unknown key, wrong type or value outside the allowed set becomes one warning naming the key and the value
used instead. `bridge-cockpit.py status` prints them and `/api/bootstrap` hands them to the settings page.
The cockpit never refuses to start on one; only a bad `port` stays an error.

Run: pytest -q scripts/tests/test_bridge_cockpit_config.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_bridge_cockpit import World, private_key_dir  # noqa: E402,F401  (the autouse fixture comes along)
from lib.bridge_cockpit import config as cf  # noqa: E402
from lib.bridge_cockpit.config import WebConfigError, load_web_config  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "scripts" / "bridge-cockpit.py"


def warnings_of(tmp_path, block: dict, **rest) -> tuple:
    return load_web_config(tmp_path, {"cockpit": block, **rest}).config_warnings


def template_block() -> dict:
    """The commented cockpit: block of bridge-config.yaml.template, uncommented and parsed."""
    lines, inside = [], False
    for line in (ROOT / "bridge-config.yaml.template").read_text(encoding="utf-8").splitlines():
        if line.startswith("# cockpit:"):
            inside = True
        elif inside and not line.startswith("#"):
            break
        if inside:
            lines.append(line[2:] if line.startswith("# ") else line[1:])
    return yaml.safe_load("\n".join(lines))["cockpit"]


# ---------------------------------------------------------------- the three cases of the issue

def test_an_unknown_key_gives_one_warning_naming_it(tmp_path):
    out = warnings_of(tmp_path, {"enabled": True, "tab_seconds": 30})
    assert len(out) == 1 and "cockpit.tab_seconds" in out[0] and "unknown" in out[0]


def test_an_invalid_open_in_gives_one_warning_with_the_fallback(tmp_path):
    cfg = load_web_config(tmp_path, {"cockpit": {"open_in": "browser"}})
    assert cfg.open_in == "auto"                                   # the fallback still applies
    assert len(cfg.config_warnings) == 1
    assert "cockpit.open_in" in cfg.config_warnings[0] and "browser" in cfg.config_warnings[0]
    assert re.search(r"using \"auto\"", cfg.config_warnings[0])


def test_an_invalid_launch_target_gives_one_warning_with_the_fallback(tmp_path):
    cfg = load_web_config(tmp_path, {"cockpit": {"launch": {"target": "areas"}}})
    assert cfg.target == "area"
    assert len(cfg.config_warnings) == 1
    assert "cockpit.launch.target" in cfg.config_warnings[0] and "using \"area\"" in cfg.config_warnings[0]


def test_a_valid_config_gives_no_warning(tmp_path):
    assert warnings_of(tmp_path, {}) == ()
    assert load_web_config(tmp_path, {}).config_warnings == ()
    full = {"enabled": True, "port": 8798, "open_in": "cmux", "relay": True, "person_name": "Ada", "profile": "morning",
            "tabs_seconds": 15, "full_minutes": 2.5, "voice": True, "triage_daily": False, "snapshot_minutes": 0,
            "language": "de-DE", "chat_layout": "workspaces", "launch": {"target": "tab"},
            "launch_model": {"enabled": True, "default_model": "haiku", "router": "jev"},
            "ticker": {"enabled": True, "speed": "fast", "smart": {"mute": ["crypto"]}, "editor": {"max_picks": 5},
                       "feeds": [{"id": "a", "name": "A", "url": "https://example.org/a.xml"}]}}
    assert warnings_of(tmp_path, full) == ()


def test_the_template_block_is_valid(tmp_path):
    # the template lists every key with its default: the registry knows all of them, and they all pass
    block = template_block()
    assert {"enabled", "port", "launch", "launch_model", "ticker"} <= set(block)
    assert warnings_of(tmp_path, block) == ()


def test_every_key_of_the_registry_is_in_the_template_and_the_doc():
    block = template_block()
    doc = (ROOT / "docs" / "bridge-cockpit.md").read_text(encoding="utf-8")
    for key in cf.BLOCK_KEYS:
        assert re.search(rf"^\| `{key}(\.[a-z_]+)?` \|", doc, re.M), f"{key} has no row in docs/bridge-cockpit.md"
        if key != "chat_layout":                                     # the template keeps the experimental one out
            assert key in block, f"{key} is missing in bridge-config.yaml.template"


# ---------------------------------------------------------------- types, values, nested blocks

@pytest.mark.parametrize("block, key, used", [
    ({"tabs_seconds": 2.5}, "cockpit.tabs_seconds", "10"),
    ({"tabs_seconds": 2}, "cockpit.tabs_seconds", "5"),
    ({"relay": "yes"}, "cockpit.relay", "false"),
    ({"enabled": "yes"}, "cockpit.enabled", "false"),
    ({"full_minutes": "ten"}, "cockpit.full_minutes", "10"),
    ({"snapshot_minutes": -5}, "cockpit.snapshot_minutes", "0"),
    ({"chat_layout": "tiles"}, "cockpit.chat_layout", "\"classic\""),
    ({"person_name": 7}, "cockpit.person_name", "none"),
    ({"launch": "tab"}, "cockpit.launch", "target \"area\""),
])
def test_wrong_types_and_values_name_the_key_and_the_value_used(tmp_path, block, key, used):
    out = warnings_of(tmp_path, block)
    assert len(out) == 1 and out[0].startswith(key + ":") and out[0].endswith("using " + used), out


def test_unknown_keys_inside_launch_and_the_nested_blocks(tmp_path):
    out = warnings_of(tmp_path, {"launch": {"targte": "tab"},
                                 "launch_model": {"enabeld": True, "router": "gpt"},
                                 "ticker": {"speed": "warp", "nope": 1, "smart": {"mute_terms": []},
                                            "feeds": [{"id": "ok", "name": "Ok", "url": "https://example.org/x"},
                                                      {"id": "Bad Id", "name": "B", "url": "https://example.org/y"}]}})
    keys = sorted(w.split(":", 1)[0] for w in out)
    assert keys == ["cockpit.launch.targte", "cockpit.launch_model.enabeld", "cockpit.launch_model.router",
                    "cockpit.ticker.feeds[1].id", "cockpit.ticker.nope", "cockpit.ticker.smart.mute_terms",
                    "cockpit.ticker.speed"], out


def test_the_fallbacks_stay_as_they_were(tmp_path):
    cfg = load_web_config(tmp_path, {"cockpit": {"enabled": True, "tabs_seconds": 2, "launch": {"target": "x"},
                                                 "open_in": "browser", "launch_model": {"router": "gpt"},
                                                 "ticker": {"speed": "warp"}},
                                     "briefing": {"claude_code_ui": {"full_minutes": 3}}})   # retired, read no more
    assert (cfg.tabs_seconds, cfg.target, cfg.open_in, cfg.full_minutes) == (5, "area", "auto", 10)
    assert cfg.launch_model["router"] == "chain" and cfg.ticker["speed"] == "normal"
    assert len(cfg.config_warnings) == 5
    with pytest.raises(WebConfigError, match="cockpit.port"):          # a bad port still refuses to start
        load_web_config(tmp_path, {"cockpit": {"port": 80, "nope": 1}})


def test_a_block_that_is_no_mapping_is_one_warning(tmp_path):
    out = load_web_config(tmp_path, {"cockpit": ["enabled"]}).config_warnings
    assert len(out) == 1 and out[0].startswith("cockpit:")


def test_an_empty_value_counts_as_left_out(tmp_path):
    # `profile:` with nothing after it is YAML null: the key is left out, not wrong
    assert warnings_of(tmp_path, {"profile": None, "port": None, "person_name": ""}) == ()


# ---------------------------------------------------------------- where the warnings show

def test_bootstrap_carries_the_warnings(tmp_path):
    w = World(tmp_path, config="cockpit:\n  enabled: true\n  open_in: browser\n  tab_seconds: 3\n"
                               "workplace:\n  control:\n    name: Control\n", prepare=False)
    try:
        status, _, body = w.request("GET", "/api/bootstrap", headers=w.cookie)
        data = json.loads(body)
        assert status == 200 and len(data["config_warnings"]) == 2
        assert any("cockpit.open_in" in x for x in data["config_warnings"])
    finally:
        w.close()


def test_bootstrap_of_a_valid_config_has_an_empty_list(tmp_path):
    w = World(tmp_path, prepare=False)
    try:
        assert json.loads(w.request("GET", "/api/bootstrap", headers=w.cookie)[2])["config_warnings"] == []
    finally:
        w.close()


def _status(tmp_path, config: str, *args):
    root = tmp_path / ("bridge-json" if "--json" in args else "bridge")
    root.mkdir()
    (root / "bridge-config.yaml").write_text(config, encoding="utf-8")
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "BRIDGE_COCKPIT_KEY_DIR": str(tmp_path / "keys")}
    return subprocess.run([sys.executable, str(CLI), "--root", str(root), "--state-dir", str(tmp_path / "state"),
                           "status", *args], env=env, capture_output=True, text=True, timeout=30)


def test_status_prints_the_warnings(tmp_path):
    res = _status(tmp_path, "cockpit:\n  enabled: true\n  open_in: browser\n  launch: {target: areas}\n")
    assert res.returncode == 1 and "not running" in res.stdout              # not running: still exit 1
    lines = [x for x in res.stdout.splitlines() if x.startswith("warning: ")]
    assert len(lines) == 2 and "cockpit.open_in" in lines[0] + lines[1] and "cockpit.launch.target" in lines[0] + lines[1]


def test_status_json_carries_the_warnings(tmp_path):
    res = _status(tmp_path, "cockpit:\n  enabled: true\n  tab_seconds: 3\n", "--json")
    out = json.loads(res.stdout)
    assert out["running"] is False and len(out["config_warnings"]) == 1


def test_status_of_a_valid_config_prints_no_warning(tmp_path):
    res = _status(tmp_path, "cockpit:\n  enabled: true\n")
    assert "warning" not in res.stdout and res.stdout.strip() == "not running"
    assert json.loads(_status(tmp_path, "cockpit:\n  enabled: true\n", "--json").stdout)["config_warnings"] == []


def test_the_doc_says_chat_keep_hours_covers_quick_chats_and_a2a_conversations():
    """chat_keep_hours now also lets A2A conversations go, and a chat about an item leaves with it: the doc says both"""
    doc = (ROOT / "docs" / "bridge-cockpit.md").read_text(encoding="utf-8")
    row = next(line for line in doc.splitlines() if line.startswith("| `chat_keep_hours` |"))
    assert "quick chats and A2A agent conversations untouched this long go to the archive" in row
    assert "0 keeps them" in row
    assert ("a chat started from a briefing row or handed to a tab leaves when its item closes, "
            "once it has been quiet for 10 minutes") in " ".join(doc.split()).lower()


# ---------------------------------------------------------------- cockpit.usage (read by usage.remote_hosts)

def test_the_usage_block_is_known_and_checked(tmp_path):
    assert warnings_of(tmp_path, {"usage": {"remotes": ["my-server"], "remote_file": "~/.bridge/resources/usage.json"}}) == ()
    assert warnings_of(tmp_path, {"usage": {"remotes": []}}) == ()            # an empty list: no other machine
    out = warnings_of(tmp_path, {"usage": {"remotes": "my-server", "remote_file": 7, "remots": []}})
    assert sorted(w.split(":", 1)[0] for w in out) == ["cockpit.usage.remote_file", "cockpit.usage.remotes",
                                                       "cockpit.usage.remots"], out
    bad = warnings_of(tmp_path, {"usage": {"remotes": ["my-server", "not a host"]}})
    assert len(bad) == 1 and "cockpit.usage.remotes" in bad[0] and "not a host" in bad[0]
    assert warnings_of(tmp_path, {"usage": "x"})[0].startswith("cockpit.usage: must be a mapping")
    assert warnings_of(tmp_path, {"usage": {"host": "my-laptop"}}) == ()
    assert warnings_of(tmp_path, {"usage": {"host": "a b"}})[0].startswith("cockpit.usage.host")
