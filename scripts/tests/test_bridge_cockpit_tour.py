# SPDX-License-Identifier: MIT
"""Contract for the cockpit's first-run tour (the guided introduction of the page).

On the first visit the page offers a short tour: a welcome, then one step per area with the area
lit up, Next, Back and Skip. Whether it was finished or skipped is kept on the server (state.json),
so a second browser does not offer it again; Help and Settings start it again at any time.
`cockpit.tour: false` switches the offer off (the tour can still be started by hand).

Run: pytest -q scripts/tests/test_bridge_cockpit_tour.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_bridge_cockpit import World, private_key_dir  # noqa: E402,F401  (the autouse fixture comes along)
from lib.bridge_cockpit.actions import ActionError  # noqa: E402
from lib.bridge_cockpit.config import load_web_config  # noqa: E402

CFG = "cockpit:\n  enabled: true\n  language: en\n{tour}"


def world(tmp_path, tour: str = "") -> World:
    return World(tmp_path, config=CFG.format(tour=tour), serve=False, prepare=False)


def test_the_tour_is_offered_by_default_and_the_config_switches_the_offer_off(tmp_path):
    root = tmp_path / "a"
    root.mkdir()
    (root / "bridge-config.yaml").write_text(CFG.format(tour=""), encoding="utf-8")
    assert load_web_config(root).tour is True
    (root / "bridge-config.yaml").write_text(CFG.format(tour="  tour: false\n"), encoding="utf-8")
    cfg = load_web_config(root)
    assert cfg.tour is False and cfg.config_warnings == ()
    (root / "bridge-config.yaml").write_text(CFG.format(tour="  tour: maybe\n"), encoding="utf-8")
    cfg = load_web_config(root)
    assert cfg.tour is True                                     # a wrong value keeps the default
    assert any("tour" in w for w in cfg.config_warnings)


def test_the_state_carries_the_offer_and_nothing_done_on_a_new_bridge(tmp_path):
    w = world(tmp_path)
    try:
        assert w.app.state_payload()["tour"] == {"enabled": True, "done": None}
    finally:
        w.close()
    w = world(tmp_path / "off", tour="  tour: false\n")
    try:
        assert w.app.state_payload()["tour"] == {"enabled": False, "done": None}
    finally:
        w.close()


def test_finishing_or_skipping_is_kept_on_the_server_and_survives_a_restart(tmp_path):
    from lib.bridge_cockpit.store import WebStore
    w = world(tmp_path)
    try:
        out = w.act("tour_done", how="skipped", v=1)
        done = out["tour"]["done"]
        assert done == {"how": "skipped", "v": 1, "at": w.app.store.today()}
        saved = json.loads((w.state / "state.json").read_text(encoding="utf-8"))
        assert saved["tour"] == done
        w.act("tour_done", how="finished", v=2)
        again = WebStore(w.state, w.clock)                      # what a restarted server reads
        assert again.tour() == {"how": "finished", "v": 2, "at": w.app.store.today()}
        out = w.act("tour_reset")
        assert out["tour"]["done"] is None and w.app.state_payload()["tour"]["done"] is None
        assert json.loads((w.state / "state.json").read_text(encoding="utf-8")).get("tour") is None
    finally:
        w.close()


def test_a_kept_tour_with_a_broken_shape_counts_as_not_done(tmp_path):
    state = tmp_path / "state"
    state.mkdir(parents=True)
    (state / "state.json").write_text(json.dumps({"v": 1, "tour": {"how": "rm -rf", "v": "x"}}), encoding="utf-8")
    w = world(tmp_path)
    try:
        assert w.app.state_payload()["tour"]["done"] is None
    finally:
        w.close()


def test_the_tour_verbs_check_their_arguments(tmp_path):
    w = world(tmp_path)
    try:
        for bad in ({"how": "later", "v": 1}, {"how": "finished", "v": -1}, {"how": "finished", "v": True},
                    {"how": "finished"}, {"v": 1}):
            with pytest.raises(ActionError):
                w.act("tour_done", **bad)
    finally:
        w.close()


def test_the_tour_verbs_never_take_the_write_lock_and_tell_every_open_page():
    from lib.bridge_cockpit.actions_base import LOCAL_VERBS, SPEC
    for verb in ("tour_done", "tour_reset"):
        assert verb in SPEC and verb in LOCAL_VERBS
    events = (Path(__file__).resolve().parents[1] / "web" / "api.js").read_text(encoding="utf-8")
    assert "'tour'" in events.split("const EVENTS", 1)[1].split("\n", 1)[0]
