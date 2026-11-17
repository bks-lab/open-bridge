# SPDX-License-Identifier: MIT
"""Contract for the Features area of the cockpit's settings page (scripts/lib/bridge_cockpit/features.py).

One catalogue names every feature the page can switch beside the config: the keys of the `cockpit:` block a fresh
cockpit leaves off (Work through and its sub switches, the briefs, the daily sort, the chat as cmux, the files
switches, the voice) and the three switches the settings page already kept in stores of their own (launch_model,
ticker, session_guide). A config feature's override goes to <state>/features.json and is merged into the block by
load_web_config before anything reads it, so bridge-config.yaml is never written; a store feature goes to its own
store. Presets are named sets of values: basic and full built in, more as files in workflow/cockpit-presets/.
A change of a config feature needs a restart, which a server under `serve` does by itself.

Hermetic: a fake Bridge in tmp_path (test_bridge_cockpit.World), no network (the ticker's fetch is a fake), no
real restart (on_restart is a fake, os.execv is recorded).

Run: python3 -m pytest scripts/tests/test_bridge_cockpit_features.py -q
"""
from __future__ import annotations

import importlib.util
import json
import re
import signal
import sys
import threading
import time
import types
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_bridge_cockpit import World, private_key_dir  # noqa: E402,F401  (the autouse fixture comes along)
from lib.bridge_cockpit import access as ac  # noqa: E402
from lib.bridge_cockpit import actions_base as ab  # noqa: E402
from lib.bridge_cockpit import features as ft  # noqa: E402
from lib.bridge_cockpit.actions import ActionError  # noqa: E402
from lib.bridge_cockpit.config import WORK_VIEWS, load_web_config  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "scripts" / "bridge-cockpit.py"
PRESETS = ROOT / "workflow" / "cockpit-presets"
BASE = {"cockpit": {"enabled": True, "language": "en"}}

# the contract's table: id -> (group, kind, values, requires, ai, store, area), in the page's order
TABLE = {
    "flow": ("work", "switch", (), None, False, None, None),
    "flow_only": ("work", "switch", (), "flow", False, None, None),
    "flow_themes": ("work", "switch", (), "flow", True, None, None),
    "flow_summary": ("work", "switch", (), "flow", True, None, None),
    "flow_instruct": ("work", "switch", (), "flow", True, None, None),
    "flow_checkin": ("work", "switch", (), "flow", True, None, None),
    "flow_prio_haiku": ("work", "switch", (), "flow", True, None, None),
    "flow_seen": ("work", "switch", (), "flow", False, None, None),
    "flow_attach": ("work", "switch", (), "flow", False, None, None),
    "describe": ("work", "choice", ("off", "missing", "stale"), None, True, None, None),
    "triage_daily": ("work", "switch", (), None, True, None, None),
    "chat_layout": ("chat", "choice", ("classic", "workspaces"), None, False, None, None),
    "files_scope": ("files", "choice", ("active", "all"), None, False, None, None),
    "files_search": ("files", "switch", (), None, True, None, None),
    "launch_model": ("helpers", "switch", (), None, True, "launch", "launch"),
    "ticker": ("helpers", "switch", (), None, False, "ticker", "ticker"),
    "session_guide": ("helpers", "switch", (), None, True, "guide", "guide"),
    "voice": ("page", "switch", (), None, False, None, None),
}
STORES = {"launch_model", "ticker", "session_guide"}
CONFIG_IDS = [i for i in TABLE if i not in STORES]

# what each config feature is in the loaded config, read straight from the WebConfig (not through features.py)
READ = {
    "flow": lambda c: c.flow["enabled"],
    "flow_only": lambda c: (c.work_view == "flow" and c.work_views == ("files", "flow")) or
                           (False if c.work_views == WORK_VIEWS else None),
    "flow_themes": lambda c: c.flow["themes"]["enabled"],
    "flow_summary": lambda c: c.flow["summary"]["enabled"],
    "flow_instruct": lambda c: c.flow["instruct"]["enabled"],
    "flow_checkin": lambda c: c.flow["checkin"]["enabled"],
    "flow_prio_haiku": lambda c: c.flow["prio"]["haiku"]["enabled"],
    "flow_seen": lambda c: c.flow["seen"]["enabled"],
    "flow_attach": lambda c: c.flow["attach"]["enabled"],
    "describe": lambda c: c.describe["auto"],
    "triage_daily": lambda c: c.triage_daily,
    "chat_layout": lambda c: c.chat_layout,
    "files_scope": lambda c: c.files_scope,
    "files_search": lambda c: c.files_search["enabled"],
    "voice": lambda c: c.voice,
}


def values_of(fid: str) -> tuple:
    kind, values = TABLE[fid][1], TABLE[fid][2]
    return (True, False) if kind == "switch" else values


def no_network(w: World) -> None:
    """The ticker reads feeds once switched on: an empty feed here, never the network"""
    w.app.ticker.fetch = lambda url: b"<rss><channel></channel></rss>"


def read_file(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


@pytest.fixture
def world(tmp_path):
    w = World(tmp_path, prepare=False)
    no_network(w)
    yield w
    w.close()


def make_world(tmp_path, config: str) -> World:
    w = World(tmp_path, config=config, prepare=False)
    no_network(w)
    return w


# ---------------------------------------------------------------- 1. the catalogue

def test_the_catalogue_is_the_contract_table_in_order():
    assert [f.id for f in ft.CATALOG] == list(TABLE)
    assert len({f.id for f in ft.CATALOG}) == len(ft.CATALOG)
    for f in ft.CATALOG:
        group, kind, values, requires, ai, store, area = TABLE[f.id]
        assert (f.group, f.kind, tuple(f.values), f.requires, f.ai, f.store, f.area) == \
            (group, kind, values, requires, ai, store, area), f.id
    assert ft.BY_ID["flow"] is ft.CATALOG[0]


def test_requires_names_a_switch_of_the_catalogue():
    for f in ft.CATALOG:
        if f.requires:
            assert ft.BY_ID[f.requires].kind == "switch" and ft.BY_ID[f.requires].store is None


@pytest.mark.parametrize("fid,value", [(fid, v) for fid in CONFIG_IDS for v in values_of(fid)])
def test_each_config_feature_loads_clean_and_reads_back(tmp_path, fid, value):
    # flow_only acts only with Work through on (finding 6)
    cfg = load_web_config(tmp_path, BASE, overrides={fid: value, **({"flow": True} if fid == "flow_only" else {})})
    assert cfg.config_warnings == ()
    assert READ[fid](cfg) == value
    assert ft.value_of(cfg, fid) == value
    # the patch itself is a plain cockpit: block, read the same way
    block = ft.deep_merge(BASE["cockpit"], ft.patch(fid, value))
    plain = load_web_config(tmp_path, {"cockpit": block})
    assert plain.config_warnings == () and READ[fid](plain) == value


def test_flow_only_patches_the_view_keys_and_off_keeps_the_config_s_work_view():
    assert ft.patch("flow_only", True) == {"work_view": "flow", "work_views": ["files", "flow"]}
    assert ft.patch("flow_only", False) == {"work_views": list(WORK_VIEWS)}
    assert ft.patch("flow_prio_haiku", True) == {"flow": {"prio": {"haiku": {"enabled": True}}}}
    assert ft.patch("describe", "stale") == {"describe": {"auto": "stale"}}


def test_a_store_feature_has_no_patch():
    for fid in STORES:
        with pytest.raises(KeyError):
            ft.patch(fid, True)


# ---------------------------------------------------------------- 2. the overrides

def test_an_override_deep_merges_and_keeps_its_siblings(tmp_path):
    data = {"cockpit": {"enabled": True, "flow": {"enabled": True, "themes": {"max_themes": 5, "budget_per_day": 2}}}}
    before = json.dumps(data, sort_keys=True)
    cfg = load_web_config(tmp_path, data, overrides={"flow_themes": True, "flow_seen": True})
    assert cfg.flow["themes"]["enabled"] is True and cfg.flow["themes"]["max_themes"] == 5
    assert cfg.flow["themes"]["budget_per_day"] == 2 and cfg.flow["enabled"] is True
    assert cfg.flow["seen"]["enabled"] is True and cfg.config_warnings == ()
    assert json.dumps(data, sort_keys=True) == before          # the caller's data is never changed


def test_an_override_wins_over_the_config(tmp_path):
    data = {"cockpit": {"enabled": True, "voice": True, "describe": {"auto": "missing", "budget_per_hour": 3}}}
    cfg = load_web_config(tmp_path, data, overrides={"voice": False, "describe": "stale"})
    assert cfg.voice is False and cfg.describe["auto"] == "stale" and cfg.describe["budget_per_hour"] == 3


def test_the_file_is_read_from_the_state_dir(tmp_path):
    root = tmp_path / "bridge"
    root.mkdir()
    (root / "bridge-config.yaml").write_text("cockpit:\n  enabled: true\n", encoding="utf-8")
    state = tmp_path / "state"
    state.mkdir()
    (state / "features.json").write_text(json.dumps({"voice": True}), encoding="utf-8")
    assert load_web_config(root, state_dir=state).voice is True
    assert load_web_config(root).voice is False                   # the default state dir has no file
    default = root / ".bridge" / "cockpit"
    default.mkdir(parents=True)
    (default / "features.json").write_text(json.dumps({"triage_daily": True}), encoding="utf-8")
    assert load_web_config(root).triage_daily is True
    # data given: the file is not read, only what overrides= names
    assert load_web_config(root, {"cockpit": {"enabled": True}}, state_dir=state).voice is False
    assert load_web_config(root, {"cockpit": {"enabled": True}}, overrides={"voice": True}).voice is True


def test_keys_outside_the_catalogue_and_bad_values_are_ignored_and_named(tmp_path):
    bad = {"enabled": False, "port": 1, "served": {"access": {}}, "relay": True, "launch_model": True,
           "flow": "yes", "describe": "always", "chat_layout": 3, "nope": 1, "voice": True}
    cfg = load_web_config(tmp_path, BASE, overrides=bad)
    assert cfg.enabled is True and cfg.port == 8797 and cfg.relay is False and cfg.served_access is None
    assert cfg.flow["enabled"] is False and cfg.describe["auto"] == "off" and cfg.chat_layout == "classic"
    assert cfg.launch_model["enabled"] is False
    assert cfg.voice is True                                       # the good one still applies
    text = "\n".join(cfg.config_warnings)
    for key in ("enabled", "port", "served", "relay", "launch_model", "flow", "describe", "chat_layout", "nope"):
        assert f"features.json.{key}:" in text, key
    assert "features.json.voice" not in text


@pytest.mark.parametrize("content", ["{broken", "[1, 2]", "", "null"])
def test_a_broken_or_missing_file_is_no_override(tmp_path, content):
    state = tmp_path / "state"
    state.mkdir()
    (state / "features.json").write_text(content, encoding="utf-8")
    root = tmp_path / "bridge"
    root.mkdir()
    (root / "bridge-config.yaml").write_text("cockpit:\n  enabled: true\n  voice: true\n", encoding="utf-8")
    cfg = load_web_config(root, state_dir=state)
    assert cfg.voice is True and cfg.enabled is True
    assert load_web_config(root, state_dir=tmp_path / "nothing").voice is True


def test_no_cockpit_block_takes_overrides_onto_an_empty_one(tmp_path):
    cfg = load_web_config(tmp_path, {}, overrides={"voice": True})
    assert cfg.voice is True and cfg.enabled is False


def test_flow_only_without_flow_is_refused_with_a_warning(tmp_path):
    cfg = load_web_config(tmp_path, BASE, overrides={"flow_only": True})
    assert cfg.work_views == WORK_VIEWS and cfg.work_view == "due"
    assert any(w.startswith("features.json.flow_only:") and "flow" in w for w in cfg.config_warnings)
    on = load_web_config(tmp_path, BASE, overrides={"flow": True, "flow_only": True})
    assert on.work_views == ("files", "flow") and on.config_warnings == ()
    by_config = load_web_config(tmp_path, {"cockpit": {"enabled": True, "flow": {"enabled": True}}}, overrides={"flow_only": True})
    assert by_config.work_views == ("files", "flow") and by_config.config_warnings == ()


def test_flow_only_off_keeps_a_custom_config_and_a_stale_override_drops_again(tmp_path):
    custom = {"cockpit": {"enabled": True, "flow": {"enabled": True}, "work_views": ["due", "files", "flow"], "work_view": "files"}}
    cfg = load_web_config(tmp_path, custom, overrides={"flow_only": False})      # it equals the config now: no override
    assert cfg.work_views == ("due", "files", "flow") and cfg.work_view == "files" and cfg.config_warnings == ()
    stale = load_web_config(tmp_path, custom, overrides={"flow": True, "voice": False})
    assert stale.flow["enabled"] is True and stale.config_warnings == ()
    only = {"cockpit": {"enabled": True, "flow": {"enabled": True}, "work_views": ["files", "flow"], "work_view": "flow"}}
    off = load_web_config(tmp_path, only, overrides={"flow_only": False})
    assert off.work_views == WORK_VIEWS and off.work_view == "flow"           # the config's own work_view stays


def test_a_file_nested_too_deep_is_no_override(tmp_path):
    root, state = tmp_path / "bridge", tmp_path / "state"
    root.mkdir()
    state.mkdir()
    (root / "bridge-config.yaml").write_text("cockpit:\n  enabled: true\n", encoding="utf-8")
    (state / "features.json").write_text("[" * 200_000, encoding="utf-8")
    assert load_web_config(root, state_dir=state).enabled is True
    assert ft.read_overrides(state / "features.json") == {}


# ---------------------------------------------------------------- the store

def test_save_validates_everything_before_writing(world):
    path = world.state / "features.json"
    for change, field in (({"flow": True, "describe": "sometimes"}, "describe"), ({"voice": "on"}, "voice"),
                          ({"flow": True, "port": 9000}, "port"), ({"launch_model": "yes"}, "launch_model")):
        with pytest.raises(ft.FeatureError) as error:
            world.app.features.save(change)
        assert error.value.status == 400 and error.value.code == "invalid_argument" and error.value.field == field
    assert not path.exists()
    assert world.app.launch_model.settings()["enabled"] is False


def test_save_drops_values_equal_to_the_config(tmp_path):
    w = make_world(tmp_path, "cockpit:\n  enabled: true\n  language: en\n  flow:\n    enabled: true\n")
    try:
        f = w.app.features
        f.save({"flow": True, "voice": True, "describe": "missing"})
        assert read_file(w.state / "features.json") == {"voice": True, "describe": "missing"}
        f.save({"voice": False})
        assert read_file(w.state / "features.json") == {"describe": "missing"}
        f.save({"flow": False})
        assert read_file(w.state / "features.json") == {"describe": "missing", "flow": False}
    finally:
        w.close()


def test_store_features_go_to_their_stores_never_to_the_file(world):
    f = world.app.features
    f.save({"launch_model": True, "ticker": True, "session_guide": True})
    assert read_file(world.state / "features.json") in (None, {})
    assert read_file(world.state / "launch.json") == {"enabled": True}
    assert read_file(world.state / "ticker.json")["enabled"] is True
    assert read_file(world.state / "guide.json") == {"enabled": True}
    assert world.app.launch_model.settings()["enabled"] is True
    assert world.app.ticker.settings()["enabled"] is True and world.app.guide.settings()["enabled"] is True
    items = {i["id"]: i for i in f.state()["items"]}
    assert items["ticker"]["value"] is True and items["ticker"]["config"] is False and items["ticker"]["overridden"] is True


def test_reset_empties_the_file_and_drops_only_the_stores_enabled(world):
    f = world.app.features
    world.app.launch_model.save({"enabled": True, "auto": True})
    world.app.guide.save({"enabled": True, "auto": False})
    f.save({"flow": True, "voice": True, "ticker": True})
    f.reset()
    assert read_file(world.state / "features.json") == {}
    assert read_file(world.state / "launch.json") == {"auto": True}          # its other key stays
    assert read_file(world.state / "guide.json") == {"auto": False}
    assert world.app.ticker.settings()["enabled"] is False
    assert f.state()["overridden"] == 0


def test_the_value_is_the_one_after_a_restart_and_restart_is_pending(world):
    f = world.app.features
    assert f.pending() is False
    f.save({"flow": True})
    items = {i["id"]: i for i in f.state()["items"]}
    assert items["flow"]["value"] is True and items["flow"]["config"] is False and items["flow"]["overridden"] is True
    assert world.app.cfg.flow["enabled"] is False                  # the running server is unchanged
    assert f.pending() is True and f.state()["restart"]["pending"] is True
    f.save({"flow": False})
    assert f.pending() is False


def test_save_refuses_flow_only_while_flow_stays_off(world):
    with pytest.raises(ft.FeatureError) as error:
        world.app.features.save({"flow_only": True})
    assert error.value.status == 400 and error.value.field == "flow_only"
    assert not (world.state / "features.json").exists()
    world.app.features.save({"flow": True, "flow_only": True})
    assert read_file(world.state / "features.json") == {"flow": True, "flow_only": True}
    world.app.features.save({"flow": False})                 # Work through off takes its flow_only along
    assert read_file(world.state / "features.json") == {}
    world.app.features.save({"flow": True, "flow_only": True})
    world.app.features.save({"flow_only": False})            # off is the config's own value: the override goes
    assert read_file(world.state / "features.json") == {"flow": True}


def test_a_served_cockpit_never_sorts_by_itself(world):
    import dataclasses
    world.app.cfg = dataclasses.replace(world.app.cfg, served=True)
    f = world.app.features
    items = {i["id"]: i for i in f.state()["items"]}
    assert items["triage_daily"]["available"] is False
    assert all(i["available"] for k, i in items.items() if k != "triage_daily")
    world.app.on_restart = lambda: None
    res = world.act("features_save", settings={"triage_daily": True})
    assert res["restart"] == "none" and read_file(world.state / "features.json") in (None, {})
    res = world.act("features_preset", preset="full")         # the rest of full applies
    assert "triage_daily" not in read_file(world.state / "features.json")
    assert next(p for p in res["features"]["presets"] if p["id"] == "full")["matches"] is True


# ---------------------------------------------------------------- 3. presets

def test_the_built_in_basic_puts_every_feature_at_its_default():
    basic = ft.builtin_presets()["basic"]
    assert set(basic) == set(TABLE)
    for fid, (_g, kind, values, *_rest) in TABLE.items():
        assert basic[fid] == (False if kind == "switch" else values[0]), fid


def test_the_built_in_full_leaves_files_search_and_flow_only_alone():
    full = ft.builtin_presets()["full"]
    assert set(full) == set(TABLE) - {"files_search", "flow_only"}
    assert full["describe"] == "stale" and full["chat_layout"] == "workspaces" and full["files_scope"] == "all"
    assert all(full[fid] is True for fid, row in TABLE.items() if row[1] == "switch" and fid in full)


def write_preset(root: Path, name: str, text: str) -> None:
    folder = root / "workflow" / "cockpit-presets"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(text, encoding="utf-8")


TEAM = ("schema_version: 1\nscope: org\nid: team\ntitle: Team\ndescription: What the team works with.\n"
        "features:\n  flow: true\n  flow_themes: true\n  nonsense: true\n  describe: always\n  ticker: true\n")


def test_preset_files_are_found_and_cleaned(tmp_path):
    root = tmp_path / "bridge"
    write_preset(root, "_template.yaml", "schema_version: 1\nscope: user\nid: _template\ntitle: T\nfeatures: {flow: true}\n")
    write_preset(root, "team.yaml", TEAM)
    write_preset(root, "basic.yaml", "schema_version: 1\nscope: user\nid: basic\ntitle: Mine\nfeatures: {flow: true}\n")
    write_preset(root, "broken.yaml", "features: [\n")
    write_preset(root, "other.yaml", "schema_version: 1\nscope: user\nid: elsewhere\ntitle: X\nfeatures: {flow: true}\n")
    write_preset(root, "empty.yaml", "schema_version: 1\nscope: user\nid: empty\ntitle: E\nfeatures: {nonsense: 1}\n")
    write_preset(root, "notes.txt", "not a preset\n")
    presets, warnings = ft.load_presets(root)
    assert [p["id"] for p in presets] == ["team"]
    team = presets[0]
    assert team == {"id": "team", "builtin": False, "title": "Team", "description": "What the team works with.",
                    "scope": "org", "features": {"flow": True, "flow_themes": True, "ticker": True}}
    text = "\n".join(warnings)
    assert "workflow/cockpit-presets/team.yaml: unknown feature nonsense, left out" in warnings
    assert re.search(r"workflow/cockpit-presets/team\.yaml: describe .*always", text)
    assert re.search(r"workflow/cockpit-presets/basic\.yaml: .*built-in", text)
    assert "workflow/cockpit-presets/broken.yaml" in text
    assert "workflow/cockpit-presets/other.yaml" in text
    assert "workflow/cockpit-presets/empty.yaml" in text
    assert "_template" not in text and "notes.txt" not in text


def test_a_bare_off_in_a_preset_file_is_off(tmp_path):
    write_preset(tmp_path, "quiet.yaml", "schema_version: 1\nscope: user\nid: quiet\ntitle: Quiet\n"
                                         "features: {describe: off, voice: off}\n")
    presets, warnings = ft.load_presets(tmp_path)
    assert presets[0]["features"] == {"describe": "off", "voice": False} and warnings == []


def test_a_preset_with_flow_only_but_not_flow_leaves_it_out(tmp_path):
    write_preset(tmp_path, "views.yaml", "schema_version: 1\nscope: user\nid: views\ntitle: V\n"
                                         "features: {flow_only: true, voice: true}\n")
    write_preset(tmp_path, "both.yaml", "schema_version: 1\nscope: user\nid: both\ntitle: B\n"
                                        "features: {flow: true, flow_only: true}\n")
    presets, warnings = ft.load_presets(tmp_path)
    by = {p["id"]: p["features"] for p in presets}
    assert by == {"both": {"flow": True, "flow_only": True}, "views": {"voice": True}}
    assert any(w.startswith("workflow/cockpit-presets/views.yaml: flow_only") for w in warnings)


def test_no_folder_is_no_preset_file(tmp_path):
    assert ft.load_presets(tmp_path) == ([], [])


def test_apply_sets_only_the_features_a_preset_names(tmp_path):
    w = make_world(tmp_path, "cockpit:\n  enabled: true\n  language: en\n")
    try:
        write_preset(w.root, "team.yaml", TEAM)
        f = w.app.features
        f.save({"voice": True, "describe": "missing"})
        f.apply("team")
        assert read_file(w.state / "features.json") == {"voice": True, "describe": "missing", "flow": True, "flow_themes": True}
        assert w.app.ticker.settings()["enabled"] is True
        with pytest.raises(ft.FeatureError) as error:
            f.apply("nobody")
        assert error.value.status == 404
    finally:
        w.close()


def test_matches_says_whether_every_named_feature_has_its_value(tmp_path):
    w = make_world(tmp_path, "cockpit:\n  enabled: true\n  language: en\n")
    try:
        write_preset(w.root, "team.yaml", TEAM)
        f = w.app.features
        by = lambda: {p["id"]: p for p in f.state()["presets"]}  # noqa: E731
        assert by()["basic"]["matches"] is True and by()["team"]["matches"] is False
        f.apply("team")
        assert by()["team"]["matches"] is True and by()["basic"]["matches"] is False
        f.save({"flow_themes": False})
        assert by()["team"]["matches"] is False
        f.apply("full")
        assert by()["full"]["matches"] is True
        f.apply("basic")
        assert by()["basic"]["matches"] is True and by()["full"]["matches"] is False
    finally:
        w.close()


def test_the_template_is_valid_and_names_only_catalogue_features():
    text = (PRESETS / "_template.yaml").read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    assert data["schema_version"] == 1 and data["scope"] in ("user", "org", "personal")
    assert set(data["features"]) <= set(TABLE)
    for fid, value in data["features"].items():
        assert value in values_of(fid), fid
    assert "\u2014" not in text and "\u2013" not in text      # no em or en dash


def test_the_schema_holds_the_catalogue():
    schema = yaml.safe_load((PRESETS / "_schema.yaml").read_text(encoding="utf-8"))
    assert set(schema["required"]) >= {"schema_version", "scope", "id", "title", "features"}
    assert schema["properties"]["scope"]["enum"] == ["user", "org", "personal"]
    props = schema["properties"]["features"]["properties"]
    assert list(props) == list(TABLE)
    for fid, (_g, kind, values, *_rest) in TABLE.items():
        assert props[fid] == ({"type": "boolean"} if kind == "switch" else {"enum": list(values)}), fid
    assert set(schema["properties"]["id"]["not"]["enum"]) == set(ft.builtin_presets())


def test_the_template_matches_its_schema():
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.validate(yaml.safe_load((PRESETS / "_template.yaml").read_text(encoding="utf-8")),
                        yaml.safe_load((PRESETS / "_schema.yaml").read_text(encoding="utf-8")))


# ---------------------------------------------------------------- 4. state and verbs

def test_the_state_has_the_contract_shape(tmp_path):
    w = make_world(tmp_path, "cockpit:\n  enabled: true\n  language: en\n  files_search:\n    block: [secret, private]\n")
    try:
        write_preset(w.root, "team.yaml", TEAM)
        state = w.app.state_payload()["features"]
        assert set(state) == {"items", "presets", "overridden", "restart", "files_block", "warnings"}
        items = {i["id"]: i for i in state["items"]}
        assert [i["id"] for i in state["items"]] == list(TABLE)
        assert items["flow"] == {"id": "flow", "group": "work", "kind": "switch", "value": False, "config": False,
                                 "overridden": False, "requires": None, "ai": False, "store": None, "area": None,
                                 "available": True}
        assert items["describe"] == {"id": "describe", "group": "work", "kind": "choice", "values": ["off", "missing", "stale"],
                                     "value": "off", "config": "off", "overridden": False, "requires": None, "ai": True,
                                     "store": None, "area": None, "available": True}
        assert items["launch_model"] == {"id": "launch_model", "group": "helpers", "kind": "switch", "value": False,
                                         "config": False, "overridden": False, "requires": None, "ai": True,
                                         "store": "launch", "area": "launch", "available": True}
        assert items["flow_themes"]["requires"] == "flow"
        assert [p["id"] for p in state["presets"]] == ["basic", "full", "team"]
        basic = state["presets"][0]
        assert set(basic) == {"id", "builtin", "title", "description", "scope", "features", "matches"}
        assert basic["builtin"] is True and basic["title"] is None and basic["description"] is None and basic["scope"] is None
        assert state["presets"][2]["builtin"] is False and state["presets"][2]["scope"] == "org"
        assert state["overridden"] == 0 and state["restart"] == {"pending": False, "requested": False, "can": False, "code": False, "done_ms": None}
        assert state["files_block"] == ["secret", "private"]
        assert any("unknown feature nonsense" in x for x in state["warnings"])
        w.app.on_restart = lambda: None
        assert w.app.features.state()["restart"]["can"] is True
    finally:
        w.close()


def test_save_through_the_action_layer_without_a_restart_hook(world, monkeypatch):
    events = []
    monkeypatch.setattr(world.app, "broadcast", lambda e, p: events.append((e, p)))
    res = world.act("features_save", settings={"flow": True, "flow_seen": True})
    assert res["ok"] is True and res["restart"] == "needed"
    items = {i["id"]: i for i in res["features"]["items"]}
    assert items["flow"]["value"] is True and items["flow"]["overridden"] is True and res["features"]["overridden"] == 2
    assert [e for e, _ in events].count("features") == 1
    assert read_file(world.state / "features.json") == {"flow": True, "flow_seen": True}
    assert world.app.restart_requested is False                 # nothing can restart it: nothing is in flight
    assert res["features"]["restart"] == {"pending": True, "requested": False, "can": False, "code": False, "done_ms": None}


def test_a_store_change_needs_no_restart(world, monkeypatch):
    events = []
    monkeypatch.setattr(world.app, "broadcast", lambda e, p: events.append((e, p)))
    called = []
    world.app.on_restart = lambda: called.append(1)
    res = world.act("features_save", settings={"session_guide": True, "launch_model": True})
    assert res["restart"] == "none" and world.app.restart_requested is False
    names = [e for e, _ in events]
    assert "features" in names and "guide" in names and "launch" in names
    assert called == []


def test_the_verb_itself_never_starts_the_restart(world):
    """The verb says `now`; the restart starts only once the HTTP handler wrote the answer (finding 3)"""
    fired = []
    world.app.on_restart = lambda: fired.append(1)
    res = world.act("features_save", settings={"chat_layout": "workspaces"})
    assert res["restart"] == "now" and world.app.restart_requested is False
    assert res["features"]["restart"] == {"pending": True, "requested": False, "can": True, "code": False, "done_ms": None}
    assert world.app._restart_timer is None and fired == []


def test_the_answer_is_written_before_the_restart_is_asked(world, monkeypatch):
    from lib.bridge_cockpit import server as srv
    order, fired, events = [], threading.Event(), []
    real_send = srv.Handler.send_json
    real_request = world.app.request_restart

    def send_json(self, status, payload):
        real_send(self, status, payload)
        if isinstance(payload, dict) and payload.get("verb") == "features_save":
            order.append("sent")

    def request_restart():
        order.append("restart")
        return real_request()
    monkeypatch.setattr(srv.Handler, "send_json", send_json)
    monkeypatch.setattr(world.app, "request_restart", request_restart)
    monkeypatch.setattr(srv, "RESTART_DELAY_S", 0.01)
    monkeypatch.setattr(world.app, "broadcast", lambda e, p: events.append((e, p)))
    world.app.on_restart = fired.set
    status, _, data = world.post("/api/action", {"verb": "features_save", "args": {"settings": {"chat_layout": "workspaces"}}})
    assert status == 200 and json.loads(data)["restart"] == "now"
    assert fired.wait(3)
    assert order == ["sent", "restart"]
    assert world.app.restart_requested is True
    # once in flight, the page hears it: requested true
    sent = [p for e, p in events if e == "features"]
    assert sent[-1]["restart"] == {"pending": True, "requested": True, "can": True, "code": False, "done_ms": None}


def test_an_answer_without_a_restart_asks_none(world, monkeypatch):
    calls = []
    monkeypatch.setattr(world.app, "request_restart", lambda: calls.append(1))
    world.app.on_restart = lambda: None
    status, _, data = world.post("/api/action", {"verb": "features_save", "args": {"settings": {"voice": False}}})
    assert status == 200 and json.loads(data)["restart"] == "none" and calls == []


def test_a_hand_edited_config_is_pending_but_not_requested(world):
    """A change of bridge-config.yaml while the server runs: pending, never in flight, so the page offers Restart now"""
    config = world.root / "bridge-config.yaml"
    config.write_text(config.read_text(encoding="utf-8").replace("  relay: true\n", "  relay: true\n  voice: true\n"),
                      encoding="utf-8")
    assert world.app.features.state()["restart"] == {"pending": True, "requested": False, "can": False, "code": False, "done_ms": None}
    world.app.on_restart = lambda: None
    assert world.app.features.state()["restart"] == {"pending": True, "requested": False, "can": True, "code": False, "done_ms": None}


def test_restart_now_is_a_verb_of_its_own(world):
    res = world.act("features_restart")
    assert res["restart"] == "needed" and world.app.restart_requested is False
    world.app.on_restart = lambda: None
    res = world.act("features_restart")
    assert res["restart"] == "now" and res["features"]["restart"]["can"] is True
    assert world.app.restart_requested is False           # the HTTP handler asks for it after the answer


def test_saving_the_value_it_has_asks_no_restart(world):
    world.app.on_restart = lambda: None
    assert world.act("features_save", settings={"voice": False})["restart"] == "none"
    assert world.app.restart_requested is False


@pytest.mark.parametrize("settings,field", [({"flow": "yes"}, "flow"), ({"voice": True, "port": 1}, "port"),
                                            ({"describe": "always"}, "describe"), ({}, "settings")])
def test_a_bad_save_is_refused_and_writes_nothing(world, settings, field):
    with pytest.raises(ActionError) as error:
        world.act("features_save", settings=settings)
    assert error.value.status == 400 and error.value.code == "invalid_argument" and error.value.field == field
    assert not (world.state / "features.json").exists()
    assert not (world.state / "launch.json").exists()


def test_preset_and_reset_through_the_action_layer(world):
    world.app.on_restart = lambda: None
    res = world.act("features_preset", preset="full")
    assert res["restart"] == "now"
    assert next(p for p in res["features"]["presets"] if p["id"] == "full")["matches"] is True
    assert world.app.ticker.settings()["enabled"] is True
    res = world.act("features_reset")
    assert res["features"]["overridden"] == 0 and read_file(world.state / "features.json") == {}
    assert res["restart"] == "none"                     # back to what the server runs
    assert world.app.ticker.settings()["enabled"] is False
    with pytest.raises(ActionError) as error:
        world.act("features_preset", preset="nobody")
    assert error.value.status == 404
    with pytest.raises(ActionError) as error:
        world.act("features_preset", preset="../x")
    assert error.value.status == 400 and error.value.field == "preset"


VERBS = ("features_save", "features_preset", "features_reset", "features_restart")


def test_the_verbs_are_the_owners_only():
    for verb in VERBS:
        assert verb in ab.SPEC and verb in ab.LOCAL_VERBS
        assert verb not in ac.PERSON_VERBS and verb in ac.OWNER_VERBS
    assert "features" in ac.OWNER_EVENTS and "features" in ac.STATE_NEUTRAL


@pytest.mark.parametrize("verb", VERBS)
def test_a_person_is_refused_every_verb_and_never_sees_the_features(world, verb):
    args = {"features_save": {"settings": {"flow": True}}, "features_preset": {"preset": "full"}}.get(verb, {})
    with pytest.raises(ActionError) as error:
        world.app.actions.execute(verb, args, viewer="x")
    assert error.value.status == 403
    assert not (world.state / "features.json").exists() and world.app.restart_requested is False
    world.app.features.save({"flow": True})
    owner = world.app.state_payload()["features"]
    assert owner["overridden"] == 1
    assert world.app.access.state("x")["features"] == ac.STATE_NEUTRAL["features"]
    assert world.app.access.event("x", "features", owner) is None


def test_the_answer_leaves_before_the_restart(world, monkeypatch):
    """request_restart calls the hook on a timer, never inside the request"""
    calls = []
    world.app.on_restart = lambda: calls.append(threading.current_thread().name)
    assert world.app.request_restart() is True
    assert calls == []
    world.app.on_restart = None
    world.app._restart_timer = None
    world.app.restart_requested = False
    assert world.app.request_restart() is False and world.app.restart_requested is False


# a store's own verbs (Model choice, News ticker, the decision guide): (feature, save verb and args, the same verb with
# a change that leaves `enabled` alone, the reset verb)
STORE_VERBS = [
    ("launch_model", ("launch_settings", {"settings": {"enabled": True}}),
     ("launch_settings", {"settings": {"auto": True}}), "launch_settings_reset"),
    ("ticker", ("ticker_settings", {"settings": {"enabled": True}}),
     ("ticker_settings", {"settings": {"speed": "slow"}}), "ticker_settings_reset"),
    ("session_guide", ("guide_settings", {"enabled": True}), ("guide_settings", {"auto": False}), "guide_settings_reset"),
]


@pytest.mark.parametrize("fid,save,other,reset", STORE_VERBS, ids=[row[0] for row in STORE_VERBS])
def test_a_store_verb_that_moves_its_switch_tells_the_features_area(world, monkeypatch, fid, save, other, reset):
    """The helpers' rows of the Features area read the stores: their own verbs say so, or the rows go stale"""
    events = []
    monkeypatch.setattr(world.app, "broadcast", lambda e, p: events.append((e, p)))

    def features_of(res: dict) -> dict:
        sent = [p for e, p in events if e == "features"]
        assert len(sent) == 1 and res["features"] == sent[0]
        return {i["id"]: i for i in sent[0]["items"]}[fid]

    res = world.act(save[0], **save[1])
    item = features_of(res)
    assert item["value"] is True and item["overridden"] is True
    assert world.app.features.state()["overridden"] == 1
    events.clear()
    res = world.act(other[0], **other[1])                # its switch stays where it is: nothing to tell
    assert "features" not in res and [e for e, _ in events if e == "features"] == []
    events.clear()
    res = world.act(reset)
    item = features_of(res)
    assert item["value"] is False and item["overridden"] is False
    events.clear()
    res = world.act(reset)                               # nothing left to reset
    assert "features" not in res and [e for e, _ in events if e == "features"] == []


# ---------------------------------------------------------------- bridge-cockpit.py

def cli():
    spec = importlib.util.spec_from_file_location("cockpit_cli_features", CLI)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def cli_root(tmp_path) -> tuple[Path, Path]:
    root = tmp_path / "bridge"
    root.mkdir(parents=True)
    (root / "bridge-config.yaml").write_text("cockpit:\n  enabled: true\n", encoding="utf-8")
    state = tmp_path / "state"
    state.mkdir()
    (state / "features.json").write_text(json.dumps({"voice": True}), encoding="utf-8")
    return root, state


def test_check_config_reads_the_overrides_of_its_state_dir(tmp_path):
    root, state = cli_root(tmp_path)
    cfg, code = cli().check_config(root, False, state)
    assert code == 0 and cfg.voice is True


class FakeApp:
    def __init__(self):
        self.port = 0
        self.on_restart = None
        self.restart_requested = False
        self.stopped = False
        self.cancelled = []
        self.actions = types.SimpleNamespace(write_lock=threading.Lock())

    def start(self):
        pass

    def stop(self):
        self.stopped = True

    def cancel_restart(self, why):
        self.restart_requested = False
        self.cancelled.append(why)


class Execed(Exception):
    """os.execv never returns: the fake raises this once an exec would have worked"""


class FakeServer:
    """serve_forever plays one way of the server's end: a restart the page asked for (while a write verb runs, or one
    that outlasts the lock), a SIGTERM after it, or a plain stop"""

    def __init__(self, way: str, handlers: dict):
        self.app = FakeApp()
        self.way = way
        self.handlers = handlers
        self.down = threading.Event()
        self.closed = False
        self.verb_done = self.shutdown_at = None

    def serve_forever(self, poll_interval=0.5):
        if self.way == "plain":
            return
        self.app.restart_requested = True             # as App.request_restart does once a hook is set
        if self.way == "sigterm":
            self.handlers[signal.SIGTERM](signal.SIGTERM, None)
            assert self.down.wait(5)
            return
        lock = self.app.actions.write_lock
        held = threading.Event()

        def verb():
            with lock:
                held.set()
                time.sleep(0.3 if self.way == "restart" else 1.0)
                self.verb_done = time.monotonic()
        threading.Thread(target=verb, daemon=True).start()
        assert held.wait(5)
        self.app.on_restart()                         # the timer's call: waits for the verb, then the shutdown
        if self.way == "restart":
            assert self.down.wait(5), "on_restart did not shut the server down"

    def shutdown(self):
        self.shutdown_at = time.monotonic()
        self.down.set()

    def server_close(self):
        self.closed = True


def serve(tmp_path, monkeypatch, way, execv=None):
    from lib.bridge_cockpit import server as srv
    root, state = cli_root(tmp_path)
    module = cli()
    handlers = {}
    fake = FakeServer(way, handlers)
    seen = {}

    def make_server(r, **kwargs):
        seen.update(kwargs, root=r)
        return fake
    monkeypatch.setattr(srv, "make_server", make_server)
    monkeypatch.setattr(module.signal, "signal", lambda signum, handler: handlers.__setitem__(signum, handler))
    execs = []

    def fake_execv(exe, argv):
        execs.append((exe, argv, fake.app.actions.write_lock.locked()))
        raise Execed()
    monkeypatch.setattr(module.os, "execv", execv or fake_execv)
    monkeypatch.setattr(sys, "argv", ["bridge-cockpit.py", "--root", str(root), "serve"])
    args = types.SimpleNamespace(ignore_disabled=False, port=0, served=False)
    return module, fake, seen, execs, (lambda: module.cmd_serve(args, root, state)), root, state


def test_serve_execs_itself_after_cleanup_once_the_running_write_ended(tmp_path, monkeypatch):
    module, fake, seen, execs, run, root, state = serve(tmp_path, monkeypatch, "restart")
    with pytest.raises(Execed):
        run()
    assert seen["state_dir"] == state and seen["cfg"].voice is True
    assert fake.app.stopped and fake.closed and callable(fake.app.on_restart)
    assert fake.shutdown_at >= fake.verb_done                   # the write ended before the shutdown began
    # the same interpreter and arguments, the write lock still held at the exec, so no write starts after it
    assert execs == [(sys.executable, [sys.executable, str(CLI.resolve()), "--root", str(root), "serve"], True)]


def test_a_plain_stop_never_execs(tmp_path, monkeypatch):
    module, fake, seen, execs, run, root, state = serve(tmp_path, monkeypatch, "plain")
    assert run() == 0 and execs == []


def test_a_sigterm_after_a_requested_restart_stops_for_good(tmp_path, monkeypatch):
    module, fake, seen, execs, run, root, state = serve(tmp_path, monkeypatch, "sigterm")
    assert run() == 0 and execs == []
    assert fake.app.restart_requested is False and fake.app.on_restart is None


def test_a_write_that_outlasts_the_lock_cancels_the_restart(tmp_path, monkeypatch):
    module, fake, seen, execs, run, root, state = serve(tmp_path, monkeypatch, "slow")
    monkeypatch.setattr(module, "RESTART_LOCK_S", 0.05)
    assert run() == 0 and execs == []
    assert fake.app.cancelled and fake.shutdown_at is None and fake.app.restart_requested is False


def test_an_exec_that_fails_tries_another_python_then_says_so(tmp_path, monkeypatch, capsys):
    tried = []

    def failing(exe, argv):
        tried.append(exe)
        raise OSError(8, "Exec format error")
    module, fake, seen, execs, run, root, state = serve(tmp_path, monkeypatch, "restart", execv=failing)
    monkeypatch.setattr(module, "_python_with_yaml", lambda: "/fake/yaml/python3")
    monkeypatch.setattr(module.shutil, "which", lambda name: "/fake/path/python3")
    code = run()
    assert code != 0 and tried == [sys.executable, "/fake/yaml/python3", "/fake/path/python3"]
    err = capsys.readouterr().err
    assert "could not start again" in err and "bridge-cockpit.py" in err

    def second_works(exe, argv):
        tried.append(exe)
        if exe == sys.executable:
            raise OSError(2, "No such file or directory")
        raise Execed()
    tried.clear()
    module, fake, seen, execs, run, root, state = serve(tmp_path / "again", monkeypatch, "restart", execv=second_works)
    monkeypatch.setattr(module, "_python_with_yaml", lambda: "/fake/yaml/python3")
    with pytest.raises(Execed):
        run()
    assert tried == [sys.executable, "/fake/yaml/python3"]


# ---------------------------------------------------------------- docs

def test_the_doc_describes_the_features_area():
    doc = (ROOT / "docs" / "bridge-cockpit.md").read_text(encoding="utf-8")
    flat = " ".join(doc.split())
    assert "### Features and presets" in doc
    assert "| `features.json` |" in doc
    for words in ("features.json", "workflow/cockpit-presets/", "never writes `bridge-config.yaml`", "org overlay"):
        assert words in flat, words


# ---------------------------------------------------------------- the code it runs, and the restart it made

def test_codestamp_takes_the_modules_loaded_from_its_own_folder(tmp_path):
    from lib.bridge_cockpit import codestamp as cs
    base = tmp_path / "scripts"
    (base / "lib").mkdir(parents=True)
    (base / "lib" / "a.py").write_text("A = 1\n", encoding="utf-8")
    (base / "entry.py").write_text("", encoding="utf-8")
    modules = {"a": types.SimpleNamespace(__file__=str(base / "lib" / "a.py")),
               "elsewhere": types.SimpleNamespace(__file__=str(tmp_path / "other" / "b.py")),
               "builtin": types.SimpleNamespace(__file__=None), "bare": object(),
               "main": types.SimpleNamespace(__file__=str(base / "entry.py"))}
    assert cs.loaded_files(base, modules) == sorted([(base / "entry.py").resolve(), (base / "lib" / "a.py").resolve()])


def test_codestamp_sees_a_file_that_changed_or_went(tmp_path):
    from lib.bridge_cockpit import codestamp as cs
    one, two = tmp_path / "one.py", tmp_path / "two.py"
    one.write_text("x = 1\n", encoding="utf-8")
    two.write_text("y = 2\n", encoding="utf-8")
    stamp = cs.CodeStamp(tmp_path, files=[one, two])
    assert stamp.changed() is False
    one.write_text("x = 1  # a longer line now\n", encoding="utf-8")
    assert stamp.changed() is True
    again = cs.CodeStamp(tmp_path, files=[one, two])
    two.unlink()
    assert again.changed() is True
    # by default: what this process loaded from the folder, which never changes under a test
    assert cs.CodeStamp(ROOT / "scripts").changed() is False


def test_the_restart_block_says_when_newer_code_waits_and_announces_it_once(world, tmp_path):
    from lib.bridge_cockpit import codestamp as cs
    code = tmp_path / "code.py"
    code.write_text("v = 1\n", encoding="utf-8")
    world.app.code = cs.CodeStamp(tmp_path, files=[code])
    sent = []
    world.app.broadcast = lambda event, payload: sent.append((event, payload))
    assert world.app.features.state()["restart"]["code"] is False
    assert world.app.code_check() is False and sent == []
    code.write_text("v = 2  # the update\n", encoding="utf-8")
    assert world.app.code_check() is True
    assert world.app.features.state()["restart"]["code"] is True
    assert [e for e, _ in sent] == ["features"] and sent[0][1]["restart"]["code"] is True
    world.app.code_check()
    assert len(sent) == 1, "said once, not on every check"


def test_the_watcher_checks_the_code_on_its_stats_turn(world):
    seen = []
    world.app.code_check = lambda: seen.append(1)
    world.app.write_server_json = lambda: None
    world.app.watcher.step(1000.0)
    assert seen == [1]
    world.app.watcher.step(1001.0)
    assert seen == [1], "not again before the next stats turn"


def test_restart_now_also_runs_for_newer_code_alone(world):
    world.app.code_newer = True
    assert world.app.features.pending() is False
    world.app.on_restart = lambda: None
    assert world.act("features_restart")["restart"] == "now"


def test_the_restart_block_carries_when_this_server_came_back(world):
    assert world.app.features.state()["restart"]["done_ms"] is None
    world.app.restarted_ms = 1_700_000_000_000
    assert world.app.features.state()["restart"]["done_ms"] == 1_700_000_000_000


def test_a_persons_empty_features_block_has_the_same_restart_keys(world):
    assert set(ac.STATE_NEUTRAL["features"]["restart"]) == set(world.app.features.state()["restart"])
    assert ac.STATE_NEUTRAL["features"]["restart"]["code"] is False
    assert ac.STATE_NEUTRAL["features"]["restart"]["done_ms"] is None


def test_a_restart_hands_its_time_to_the_next_process(tmp_path, monkeypatch):
    module, fake, seen, execs, run, root, state = serve(tmp_path, monkeypatch, "restart")
    env_at_exec = []
    real = module.os.execv

    def recording(exe, argv):
        env_at_exec.append(module.os.environ.get(module.RESTARTED_ENV))
        return real(exe, argv)
    monkeypatch.setattr(module.os, "execv", recording)
    monkeypatch.delenv(module.RESTARTED_ENV, raising=False)
    before = int(time.time() * 1000)
    with pytest.raises(Execed):
        run()
    assert env_at_exec and before <= int(env_at_exec[0]) <= int(time.time() * 1000)
    monkeypatch.delenv(module.RESTARTED_ENV, raising=False)


def test_serve_takes_the_restart_time_and_drops_it_from_the_environment(tmp_path, monkeypatch):
    module, fake, seen, execs, run, root, state = serve(tmp_path, monkeypatch, "plain")
    monkeypatch.setenv(module.RESTARTED_ENV, "1700000000123")
    assert run() == 0
    assert fake.app.restarted_ms == 1700000000123
    assert module.RESTARTED_ENV not in module.os.environ, "an agent the cockpit starts never inherits it"
    module2, fake2, *_rest, run2, _r, _s = serve(tmp_path / "plain", monkeypatch, "plain")
    monkeypatch.setenv(module2.RESTARTED_ENV, "not a time")
    assert run2() == 0 and fake2.app.restarted_ms is None


def test_the_doc_names_the_set_here_banner_and_the_newer_code_notice():
    doc = (ROOT / "docs" / "bridge-cockpit.md").read_text(encoding="utf-8")
    flat = " ".join(doc.split()).lower()
    for words in ("set here", "newer cockpit version", "codestamp.py", "bridge_cockpit_restarted_ms"):
        assert words in flat, words


def test_the_listen_queue_takes_the_burst_of_a_reload_after_a_restart():
    """After a restart the page loads anew at once: the page, a dozen style sheets and modules in parallel, while the
    server is still busy starting. Python's default queue of 5 overflowed under load, the browser got connection
    resets for app.js and the page stayed blank (seen live: one restart in two at a load of 300 and more)"""
    from lib.bridge_cockpit import server as srv
    assert srv.WebServer.request_queue_size >= 64


def test_codestamp_skips_a_module_whose_file_is_no_path(tmp_path):
    from lib.bridge_cockpit import codestamp as cs
    odd = {"weird": types.SimpleNamespace(__file__=12345), "bytes": types.SimpleNamespace(__file__=b"\x00")}
    assert cs.loaded_files(tmp_path, odd) == []


def test_boot_guard_and_its_test_are_core():
    import importlib.util as iu
    spec = iu.spec_from_file_location("categorize_commits_boot", ROOT / "scripts" / "categorize-commits.py")
    mod = iu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for f in ("scripts/web/boot.js", "scripts/tests/bridge_cockpit_boot.test.mjs", "scripts/lib/bridge_cockpit/codestamp.py"):
        assert f in mod.SCRIPTS_CORE_ALLOWLIST, f
