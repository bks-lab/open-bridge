# SPDX-License-Identifier: MIT
"""scripts/lib/model_route.py: the judgment of how complex an item is, and the model it maps to."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import model_route as mr  # noqa: E402

S = mr.normalize({"enabled": True, "auto": True})
ITEMS = [{"id": "a", "title": "Fix a typo in the README", "kind": "task", "priority": "P3",
          "detail": "private words", "path": "/Users/x/secret"},
         {"id": "b", "title": "Redesign the storage layer", "kind": "task"}]


def jev_answer(scores: dict) -> dict:
    return {"answers": {k: {"score": v, "confidence": 0.8} for k, v in scores.items()}}


def test_defaults_are_off_and_validate_themselves():
    assert mr.DEFAULTS["enabled"] is False and mr.DEFAULTS["auto"] is False and mr.DEFAULTS["effort"] is False
    assert mr.normalize({}) == mr.DEFAULTS


@pytest.mark.parametrize("change", [
    {"nope": 1}, {"enabled": "yes"}, {"default_model": "gpt"}, {"default_effort": "max"}, {"router": "x"},
    {"jev_model": "jev-latest"}, {"max_model": "fable"},
    {"jev_bands": [{"below": 1, "model": "haiku", "effort": "low"}]},                      # last band must be open
    {"jev_bands": [{"below": 2, "model": "haiku"}, {"below": 1, "model": "opus"}, {"below": None, "model": "opus"}]},
    {"haiku_map": [{"model": "haiku"}]},
])
def test_bad_settings_are_refused(change):
    with pytest.raises(mr.SettingsError):
        mr.normalize(change)


def test_a_score_maps_through_the_bands_and_respects_the_cap():
    assert mr.from_score(0.2, S) == {"model": "haiku", "effort": "medium"}
    assert mr.from_score(1.5, S) == {"model": "sonnet", "effort": "high"}
    assert mr.from_score(3.0, S) == {"model": "opus", "effort": "xhigh"}
    capped = mr.normalize({"max_model": "sonnet"}, S)
    assert mr.from_score(3.0, capped)["model"] == "sonnet"


def test_haiku_levels_map_through_their_own_table():
    assert [mr.from_level(n, S)["model"] for n in range(4)] == ["haiku", "sonnet", "sonnet", "opus"]


def test_only_title_kind_and_priority_leave_the_machine():
    req = mr.jev_request(ITEMS, S)
    sent = json.dumps(req) + mr.haiku_prompt(ITEMS)
    assert "private words" not in sent and "/Users/x" not in sent
    assert req["model"] == "jev-1.14.0" and set(req["questions"]) == {"a", "b"}
    assert req["questions"]["a"]["type"] == "score" and req["questions"]["a"]["criteria"] == mr.LEVELS
    assert "`items[1]`" in req["questions"]["b"]["instructions"]


def test_jev_decides_first_and_haiku_is_not_asked():
    asked = []
    out = mr.route(ITEMS, S, jev=lambda p: jev_answer({"a": 0.1, "b": 2.9}), haiku=lambda p: asked.append(p) or "")
    assert out["a"]["model"] == "haiku" and out["a"]["routed_by"] == "jev" and out["a"]["confidence"] == 0.8
    assert out["b"]["model"] == "opus" and asked == []


def test_haiku_takes_what_jev_left_open_and_the_default_the_rest():
    haiku = json.dumps({"result": 'Here: [{"id": "b", "level": 1, "why": "contained"}]'})
    out = mr.route(ITEMS, S, jev=lambda p: jev_answer({"a": 0.1}), haiku=lambda p: haiku)
    assert out["b"] == {"model": "sonnet", "effort": "medium", "routed_by": "haiku", "level": 1,
                        "confidence": None, "why": "contained"}
    out = mr.route(ITEMS, S, jev=lambda p: jev_answer({}), haiku=lambda p: "garbage")
    assert out["a"]["routed_by"] == "default" and out["a"]["model"] == "sonnet"


def test_a_failing_judge_never_breaks_the_route():
    def boom(_):
        raise OSError("network down")
    out = mr.route(ITEMS, S, jev=boom, haiku=boom)
    assert {r["routed_by"] for r in out.values()} == {"default"}


def test_router_setting_limits_the_judges():
    only_haiku = mr.normalize({"router": "haiku"}, S)
    out = mr.route(ITEMS, only_haiku, jev=lambda p: jev_answer({"a": 3, "b": 3}),
                   haiku=lambda p: '[{"id": "a", "level": 0}, {"id": "b", "level": 0}]')
    assert {r["routed_by"] for r in out.values()} == {"haiku"}
    only_jev = mr.normalize({"router": "jev"}, S)
    out = mr.route(ITEMS, only_jev, jev=None, haiku=lambda p: '[{"id": "a", "level": 0}]')
    assert {r["routed_by"] for r in out.values()} == {"default"}


def test_out_of_range_answers_are_ignored():
    out = mr.route(ITEMS, S, jev=lambda p: jev_answer({"a": 7, "b": True}),
                   haiku=lambda p: '[{"id": "a", "level": 9}, {"id": "b", "level": "2"}]')
    assert {r["routed_by"] for r in out.values()} == {"default"}


def test_the_haiku_call_has_exactly_one_shape():
    argv = mr.haiku_argv("/bin/claude", "judge this")
    assert mr.haiku_argv_ok(argv, "/bin/claude")
    assert "--tools" in argv and argv[argv.index("--tools") + 1] == ""
    assert not mr.haiku_argv_ok(argv, "/other/claude")
    assert not mr.haiku_argv_ok([*argv[:3], "claude-opus-5-5", *argv[4:]], "/bin/claude")
    assert not mr.haiku_argv_ok([*argv[:-1], "--tools", "Bash", "x"], "/bin/claude")
    assert not mr.haiku_argv_ok([*argv[:-1], "x" * (mr.HAIKU_PROMPT_MAX + 1)], "/bin/claude")
