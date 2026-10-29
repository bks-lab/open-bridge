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
    """chat_keep_hours now also lets A2A conversations go, a chat about an item leaves with it, and a chat handed to a
    tab stays chat_keep_hours after its item ended (round 6d): the doc says all three"""
    doc = (ROOT / "docs" / "bridge-cockpit.md").read_text(encoding="utf-8")
    row = next(line for line in doc.splitlines() if line.startswith("| `chat_keep_hours` |"))
    assert "quick chats and A2A agent conversations untouched this long go to the archive" in row
    assert "a chat handed to a tab stays this long after the latest of its handoff, its result and its item's end" in row
    assert "0 keeps them" in row
    flat = " ".join(doc.split()).lower()
    assert "a chat started from a briefing row leaves when its item closes, once it has been quiet for 10 minutes" in flat
    assert "a chat handed to a tab stays `chat_keep_hours`" in flat


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


# ---------------------------------------------------------------- cockpit.work_view and cockpit.focus_to_files

def test_the_work_tab_keeps_its_old_default_unless_the_config_names_another_view(tmp_path):
    cfg = load_web_config(tmp_path, {})
    assert cfg.work_view == "due" and cfg.focus_to_files is False
    for view in ("due", "source", "jev", "files", "flow"):
        cfg = load_web_config(tmp_path, {"cockpit": {"work_view": view, "focus_to_files": True}})
        assert cfg.work_view == view and cfg.focus_to_files is True and cfg.config_warnings == ()


@pytest.mark.parametrize("block, key, used", [
    ({"work_view": "dossier"}, "cockpit.work_view", "\"due\""),
    ({"work_view": 3}, "cockpit.work_view", "\"due\""),
    ({"focus_to_files": "yes"}, "cockpit.focus_to_files", "false"),
])
def test_a_wrong_work_view_or_focus_switch_keeps_the_default_and_says_so(tmp_path, block, key, used):
    cfg = load_web_config(tmp_path, {"cockpit": block})
    assert cfg.work_view == "due" and cfg.focus_to_files is False
    out = cfg.config_warnings
    assert len(out) == 1 and out[0].startswith(key + ":") and out[0].endswith("using " + used), out


OFF = {"enabled": False, "block": [], "left": 20}     # the files tab's question to its records, as the default leaves it


def test_the_state_hands_the_work_view_and_the_focus_switch_to_the_page(tmp_path):
    base = "cockpit:\n  enabled: true\n  language: en\n"
    w = World(tmp_path / "a", config=base, serve=False, prepare=False)
    try:
        assert w.app.state_payload()["work"] == {"view": "due", "focus_to_files": False, "files_scope": "active",
                                                 "flow": cf.flow_defaults(), "views": list(cf.WORK_VIEWS), "files_search": OFF}
    finally:
        w.close()
    w = World(tmp_path / "b", config=base + "  work_view: files\n  focus_to_files: true\n", serve=False, prepare=False)
    try:
        assert w.app.state_payload()["work"] == {"view": "files", "focus_to_files": True, "files_scope": "active",
                                                 "flow": cf.flow_defaults(), "views": list(cf.WORK_VIEWS), "files_search": OFF}
    finally:
        w.close()


def test_with_work_through_on_the_state_names_the_person_its_waiting_rule_reads(tmp_path):
    base = "cockpit:\n  enabled: true\n  language: en\n  person_name: Ada\n"
    w = World(tmp_path / "a", config=base + "  flow:\n    enabled: true\n", serve=False, prepare=False)
    try:
        assert w.app.state_payload()["work"]["person"] == "Ada"
    finally:
        w.close()
    w = World(tmp_path / "b", config=base, serve=False, prepare=False)
    try:
        assert "person" not in w.app.state_payload()["work"]        # flow off: nothing new goes out
    finally:
        w.close()


# ---------------------------------------------------------------- cockpit.flow (the Work through page)

def test_the_flow_page_is_off_by_default_with_its_reasons_and_its_return_delay(tmp_path):
    cfg = load_web_config(tmp_path, {})
    assert cfg.flow == {"enabled": False, "drop_reasons": ["resolves_itself", "not_needed", "someone_else", "not_worth_it"],
                        "return_after_s": 20, "prep_ahead": 2, "max_running": 4, "rank_max_age_days": 7,
                        "rerank_per_day": 3, "ahead_days": 2, "infer_sessions": True,
                        "themes": {"enabled": False, "max_themes": 8, "budget_per_day": 6, "model": None},
                        "summary": {"enabled": False, "budget_per_day": 10, "model": None},
                        "instruct": {"enabled": False, "budget_per_day": 30, "model": None},
                        "attach": {"enabled": False, "max_mb": 10},
                        "prio": {"haiku_budget_per_day": 6, "fallback": "none", "model": None}}
    assert cfg.flow == cf.flow_defaults() and cfg.config_warnings == ()


def test_the_flow_block_takes_its_three_keys(tmp_path):
    block = {"enabled": True, "drop_reasons": ["not_needed", "the vendor does it"], "return_after_s": 45}
    cfg = load_web_config(tmp_path, {"cockpit": {"flow": block}})
    assert cfg.flow == {**cf.flow_defaults(), **block} and cfg.config_warnings == ()
    # off again by a bare `off`, and a delay of 0 asks for the return card at once
    cfg = load_web_config(tmp_path, {"cockpit": {"flow": {"enabled": False, "return_after_s": 0}}})
    assert cfg.flow["enabled"] is False and cfg.flow["return_after_s"] == 0


def test_a_wrong_flow_value_keeps_its_default_and_names_the_key(tmp_path):
    block = {"enabled": "yes", "drop_reasons": "not_needed", "return_after_s": -5, "rerank": 3}
    cfg = load_web_config(tmp_path, {"cockpit": {"flow": block}})
    assert cfg.flow == cf.flow_defaults()
    keys = sorted(w.split(":", 1)[0] for w in cfg.config_warnings)
    assert keys == ["cockpit.flow.drop_reasons", "cockpit.flow.enabled", "cockpit.flow.rerank", "cockpit.flow.return_after_s"]
    # a list with an empty or overlong reason keeps the good ones and says which were left out
    cfg = load_web_config(tmp_path, {"cockpit": {"flow": {"drop_reasons": ["not_needed", "", "x" * 81, 7]}}})
    assert cfg.flow["drop_reasons"] == ["not_needed"] and len(cfg.config_warnings) == 1
    assert cfg.config_warnings[0].startswith("cockpit.flow.drop_reasons")
    assert warnings_of(tmp_path, {"flow": "on"})[0].startswith("cockpit.flow:")


def test_the_state_hands_the_flow_block_to_the_page(tmp_path):
    base = "cockpit:\n  enabled: true\n  language: en\n  flow:\n    enabled: true\n    return_after_s: 30\n"
    w = World(tmp_path / "a", config=base, serve=False, prepare=False)
    try:
        flow = w.app.state_payload()["work"]["flow"]
        assert flow == {**cf.flow_defaults(), "enabled": True, "return_after_s": 30}
    finally:
        w.close()


def test_the_areas_are_the_names_of_the_configured_workspaces(tmp_path):
    spaces = [{"name": "Bridge"}, {"name": " Home "}, {"name": ""}, {"slugs": ["x-*"]}, "junk", {"name": "Bridge"}]
    cfg = load_web_config(tmp_path, {"workplace": {"workspaces": spaces}})
    assert cfg.areas == ("Bridge", "Home")
    assert load_web_config(tmp_path, {}).areas == ()



# ---------------------------------------------------------------- cockpit.origin_map

def test_the_origin_map_is_empty_unless_the_config_names_one(tmp_path):
    assert load_web_config(tmp_path, {}).origin_map == ()


def test_a_valid_origin_map_loads_lower_cased_in_file_order(tmp_path):
    cfg = load_web_config(tmp_path, {"cockpit": {"origin_map": {"Notes-Bot": "bot", "*-health": "bot", "alex": "person"}}})
    assert cfg.origin_map == (("notes-bot", "bot"), ("*-health", "bot"), ("alex", "person"))
    assert cfg.config_warnings == ()


def test_a_wrong_origin_map_says_what_it_ignores(tmp_path):
    out = warnings_of(tmp_path, {"origin_map": ["a"]})
    assert len(out) == 1 and out[0].startswith("cockpit.origin_map: must be a mapping") and out[0].endswith("using none")
    cfg = load_web_config(tmp_path, {"cockpit": {"origin_map": {"alex": "human", "bob": "person", 3: "bot",
                                                                "Bob": "bot"}}})
    assert cfg.origin_map == (("bob", "person"),)
    bad = cfg.config_warnings
    assert any(w.startswith("cockpit.origin_map.alex:") and "must be one of" in w and w.endswith("ignored") for w in bad), bad
    assert any("cockpit.origin_map.3" in w and "ignored" in w for w in bad), bad
    assert any("cockpit.origin_map.Bob" in w and "duplicate, first one kept" in w for w in bad), bad
    assert not any("unknown key" in w for w in bad)


def test_the_origin_map_never_reaches_the_page(tmp_path):
    base = "cockpit:\n  enabled: true\n  language: en\n  origin_map:\n    alex: person\n"
    w = World(tmp_path / "a", config=base, serve=False, prepare=False)
    try:
        assert "alex" not in json.dumps(w.app.state_payload())
        assert w.app.cfg.origin_map == (("alex", "person"),)
    finally:
        w.close()


# ---------------------------------------------------------------- cockpit.flow: the Work through area

def test_the_flow_block_defaults_and_its_keys(tmp_path):
    cfg = load_web_config(tmp_path, {})
    assert cfg.flow == cf.flow_defaults()
    cfg = load_web_config(tmp_path, {"cockpit": {"flow": {"enabled": True, "prep_ahead": 0, "max_running": 2,
                                                          "rank_max_age_days": 3, "rerank_per_day": 0}}})
    assert cfg.flow == {**cf.flow_defaults(), "enabled": True, "prep_ahead": 0, "max_running": 2,
                        "rank_max_age_days": 3, "rerank_per_day": 0}
    assert cfg.config_warnings == ()


@pytest.mark.parametrize("flow, key, used", [
    ({"enabled": "yes"}, "cockpit.flow.enabled", "false"),
    ({"prep_ahead": -1}, "cockpit.flow.prep_ahead", "2"),
    ({"max_running": 0}, "cockpit.flow.max_running", "4"),
    ({"rank_max_age_days": 1.5}, "cockpit.flow.rank_max_age_days", "7"),
    ({"rerank_per_day": "3"}, "cockpit.flow.rerank_per_day", "3"),
    ({"ahead_days": -1}, "cockpit.flow.ahead_days", "2"),
    ({"ahead_days": 1.5}, "cockpit.flow.ahead_days", "2"),
    ({"infer_sessions": "no"}, "cockpit.flow.infer_sessions", "true"),
])
def test_a_bad_flow_value_keeps_its_default_and_says_so(tmp_path, flow, key, used):
    cfg = load_web_config(tmp_path, {"cockpit": {"flow": flow}})
    assert cfg.flow[key.rsplit(".", 1)[1]] == json.loads(used)
    out = cfg.config_warnings
    assert len(out) == 1 and out[0].startswith(key + ":") and out[0].endswith("using " + used), out


def test_every_flow_key_has_a_doc_row():
    doc = (ROOT / "docs" / "bridge-cockpit.md").read_text(encoding="utf-8")
    for key in ("enabled", "prep_ahead", "max_running", "rank_max_age_days", "rerank_per_day", "ahead_days",
                "infer_sessions", "summary.enabled", "summary.budget_per_day", "summary.model",
                "instruct.enabled", "instruct.budget_per_day", "instruct.model", "attach.enabled", "attach.max_mb",
                "prio.haiku_budget_per_day", "prio.fallback", "prio.model"):
        assert re.search(rf"^\| `flow\.{re.escape(key)}` \|", doc, re.M), f"flow.{key} has no row in docs/bridge-cockpit.md"
    flow = template_block()["flow"]
    # round 3 of Work through: each block in the template with its default, all off
    assert {k: flow[k] for k in ("summary", "instruct", "attach")} == {
        "summary": {"enabled": False, "budget_per_day": 10}, "instruct": {"enabled": False, "budget_per_day": 30},
        "attach": {"enabled": False, "max_mb": 10}}
    # Prio's second ranker and its fallback: in the template with their defaults
    assert flow["prio"] == {"haiku_budget_per_day": 6, "fallback": "none"}


# ---------------------------------------------------------------- round 4: ahead_days, infer_sessions, work_views

def test_the_flow_block_takes_ahead_days_and_infer_sessions(tmp_path):
    cfg = load_web_config(tmp_path, {"cockpit": {"flow": {"ahead_days": 0, "infer_sessions": False}}})
    assert cfg.flow["ahead_days"] == 0 and cfg.flow["infer_sessions"] is False and cfg.config_warnings == ()
    cfg = load_web_config(tmp_path, {"cockpit": {"flow": {"ahead_days": 366}}})
    assert cfg.flow["ahead_days"] == 366 and cfg.flow["infer_sessions"] is True


def test_every_work_view_is_offered_unless_the_config_names_fewer(tmp_path):
    cfg = load_web_config(tmp_path, {})
    assert cfg.work_views == cf.WORK_VIEWS == ("due", "source", "jev", "files", "flow") and cfg.config_warnings == ()
    cfg = load_web_config(tmp_path, {"cockpit": {"work_views": ["flow", "files"], "work_view": "flow"}})
    assert cfg.work_views == ("files", "flow") and cfg.work_view == "flow" and cfg.config_warnings == ()


@pytest.mark.parametrize("value, views, word", [
    (["files", "flow", "dossier"], ("files", "flow"), "dossier"),          # an unknown word is dropped
    (["flow"], ("files", "flow"), "files"),                                # files is always kept
    ("files", cf.WORK_VIEWS, "list"),                                      # not a list: the default
    ([], cf.WORK_VIEWS, "nothing"),                                        # nothing left: the default
    (["dossier"], cf.WORK_VIEWS, "dossier"),
])
def test_a_wrong_work_views_list_says_what_it_kept(tmp_path, value, views, word):
    cfg = load_web_config(tmp_path, {"cockpit": {"work_views": value}})
    assert cfg.work_views == views
    assert cfg.config_warnings and all(w.startswith("cockpit.work_views") for w in cfg.config_warnings)
    assert any(word in w for w in cfg.config_warnings), cfg.config_warnings


def test_a_work_view_the_list_leaves_out_opens_the_first_view_kept(tmp_path):
    cfg = load_web_config(tmp_path, {"cockpit": {"work_views": ["files", "flow"], "work_view": "due"}})
    assert cfg.work_view == "files"
    out = cfg.config_warnings
    assert len(out) == 1 and out[0].startswith("cockpit.work_view:") and "files" in out[0], out


def test_a_work_view_the_list_leaves_out_opens_work_through_where_it_is_kept_and_on(tmp_path):
    # round 6 B: a Bridge that keeps only the files and Work through lands in Work through, never in the files
    cfg = load_web_config(tmp_path, {"cockpit": {"work_views": ["files", "flow"], "flow": {"enabled": True}}})
    assert cfg.work_view == "flow" and cfg.config_warnings == ()
    cfg = load_web_config(tmp_path, {"cockpit": {"work_views": ["files", "flow"], "work_view": "due", "flow": {"enabled": True}}})
    assert cfg.work_view == "flow"
    out = cfg.config_warnings
    assert len(out) == 1 and out[0].startswith("cockpit.work_view:") and '"flow"' in out[0], out
    # Work through off: the first view kept, as before
    cfg = load_web_config(tmp_path, {"cockpit": {"work_views": ["files", "flow"], "flow": {"enabled": False}}})
    assert cfg.work_view == "files"


def test_the_state_hands_the_work_views_to_the_page(tmp_path):
    base = "cockpit:\n  enabled: true\n  language: en\n  work_views: [flow, files]\n"
    w = World(tmp_path / "a", config=base, serve=False, prepare=False)
    try:
        work = w.app.state_payload()["work"]
        assert work["views"] == ["files", "flow"] and work["view"] == "files"
    finally:
        w.close()


# ---------------------------------------------------------------- round 6c: the files tab's question to its records

def test_the_files_search_block_is_off_by_default_and_keeps_the_words_that_fit(tmp_path):
    cfg = load_web_config(tmp_path, {})
    assert cfg.files_search == {"enabled": False, "budget_per_day": 20, "model": None, "block": []}
    cfg = load_web_config(tmp_path, {"cockpit": {"files_search": {"enabled": True, "budget_per_day": 5, "model": "sonnet",
                                                                 "block": ["Versicherung", "Gesundheit", "Steuer", "Familie"]}}})
    assert cfg.files_search == {"enabled": True, "budget_per_day": 5, "model": "sonnet",
                                "block": ["Versicherung", "Gesundheit", "Steuer", "Familie"]}
    assert cfg.config_warnings == ()


@pytest.mark.parametrize("value, word", [
    ({"block": "Versicherung"}, "list of words"),
    ({"block": ["ok", "", 3]}, "is ignored"),
    ({"enabled": "yes"}, "true or false"),
    ({"model": "gpt"}, "cockpit-files"),
    ({"ask": True}, "unknown key"),
    ("on", "mapping"),
])
def test_a_wrong_files_search_block_says_what_it_uses(tmp_path, value, word):
    cfg = load_web_config(tmp_path, {"cockpit": {"files_search": value}})
    assert cfg.files_search["block"] == (["ok"] if isinstance(value, dict) and value.get("block") == ["ok", "", 3] else [])
    assert len(cfg.config_warnings) == 1 and cfg.config_warnings[0].startswith("cockpit.files_search")
    assert word in cfg.config_warnings[0], cfg.config_warnings
