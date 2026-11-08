# SPDX-License-Identifier: MIT
"""Settings, On this machine (scripts/lib/bridge_cockpit/views.py): a page or a section of the briefing profile switched
off on one machine. Kept in .bridge/cockpit/views.json beside the config, passed to every collect as --skip-page and
--skip-section, and the list of what can be switched comes from the catalog the last collect sent."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_bridge_cockpit import World, collect_fixture, ok, private_key_dir  # noqa: E402,F401  (the autouse fixture comes along)
from lib.bridge_cockpit import access as ac  # noqa: E402
from lib.bridge_cockpit.actions import ActionError  # noqa: E402
from lib.bridge_cockpit.views import Views, catalog_of  # noqa: E402

CATALOG = [{"id": "lab", "title": "Lab", "group": "main", "under": None,
            "sections": [{"id": "lab-probe", "title": "Lab probe", "kind": "command"}]},
           {"id": "ci-monitor", "title": "CI", "group": "more", "under": "lab",
            "sections": [{"id": "ci", "title": "CI runs", "kind": "tracker"}]}]


@pytest.fixture
def cockpit(tmp_path):
    w = World(tmp_path, prepare=False)
    w.runner.handlers["briefing.collect"] = lambda argv: ok(json.dumps({**collect_fixture(w.root), "page_catalog": CATALOG}))
    w.app.collector.request("both")
    w.app.collector.drain()
    yield w
    w.close()


def last_collect(w):
    return w.runner.of("briefing.collect")[-1]


def test_the_list_comes_from_the_catalog_of_the_last_collect(cockpit):
    state = cockpit.app.state_payload()["views"]
    assert state["catalog"] == CATALOG and state["pages_off"] == [] and state["sections_off"] == []


def test_a_switch_is_kept_on_this_machine_and_reaches_the_next_collect(cockpit):
    before = (cockpit.root / "bridge-config.yaml").read_text(encoding="utf-8")
    res = cockpit.act("view_switch", kind="section", id="lab-probe", on=False)
    assert res["views"]["sections_off"] == ["lab-probe"]
    assert (cockpit.root / "bridge-config.yaml").read_text(encoding="utf-8") == before
    assert json.loads((cockpit.state / "views.json").read_text(encoding="utf-8")) == {"pages_off": [], "sections_off": ["lab-probe"]}
    cockpit.app.collector.drain()                  # the switch asked for a pass: no restart
    argv = last_collect(cockpit)
    assert argv[argv.index("--skip-section") + 1] == "lab-probe" and "--skip-page" not in argv
    cockpit.act("view_switch", kind="page", id="ci-monitor", on=False)
    cockpit.app.collector.drain()
    argv = last_collect(cockpit)
    assert argv[argv.index("--skip-page") + 1] == "ci-monitor"
    # a new start reads the file again; back on, the flag goes
    assert Views(cockpit.app).state()["pages_off"] == ["ci-monitor"]
    cockpit.act("view_switch", kind="section", id="lab-probe", on=True)
    cockpit.app.collector.drain()
    assert "--skip-section" not in last_collect(cockpit)


def test_an_id_the_profile_no_longer_has_is_kept(cockpit):
    cockpit.act("view_switch", kind="page", id="old-page", on=False)
    assert cockpit.app.views.state()["pages_off"] == ["old-page"]
    assert "old-page" not in [p["id"] for p in cockpit.app.views.state()["catalog"]]


def test_a_switch_refuses_what_is_no_page_or_section_id(cockpit):
    with pytest.raises(ActionError):
        cockpit.act("view_switch", kind="tab", id="lab", on=False)
    with pytest.raises(ActionError):
        cockpit.act("view_switch", kind="page", id="../etc", on=False)


def test_a_broken_file_and_a_broken_catalog_change_nothing(cockpit):
    (cockpit.state / "views.json").write_text("{not json", encoding="utf-8")
    assert Views(cockpit.app).state()["pages_off"] == []
    (cockpit.state / "views.json").write_text(json.dumps({"pages_off": ["lab", 3, "../x"], "sections_off": "ci"}), encoding="utf-8")
    fresh = Views(cockpit.app)
    assert (fresh.pages_off, fresh.sections_off) == (["lab"], [])
    assert catalog_of("nope") is None
    assert catalog_of([{"id": "Bad Id"}, {"id": "ok", "sections": [{"id": "s", "title": 5}, {"title": "x"}]}]) == [
        {"id": "ok", "title": "ok", "group": "main", "under": None, "sections": [{"id": "s", "title": "s", "kind": ""}]}]


def test_the_switches_are_the_owners_alone():
    assert "view_switch" in ac.OWNER_VERBS and "views" in ac.OWNER_EVENTS and "views" in ac.STATE_NEUTRAL
