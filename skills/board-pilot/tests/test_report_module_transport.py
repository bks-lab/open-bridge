"""`type: module`: a TRANSPORT the config names, so the engine keeps the card.

WHY THIS EXISTS ALONGSIDE `type: python`. Both let an instance supply its own
delivery, and they are not interchangeable:

  * `type: python` replaces the whole SINK. It receives the raw event and must
    render everything itself. Right for a destination with its own document
    shape (a search cluster, a metrics bus) where this engine's line and card
    would be the wrong artefact anyway.
  * `type: module` replaces only the TRANSPORT. The engine still renders the
    line and the adaptive card, with the incident band, the journey line, the
    labels and the context block, and hands both to the named module. Right for
    a destination that wants exactly the card a webhook would get, delivered
    some other way.

The case that forced it: a channel where one incident must be ONE post with
everything else hanging under it as replies. That needs the message id the
first call returns, so the transport is stateful across calls; but the card is
the same card. Rebuilding it inside an instance sink would fork the renderer,
and a forked renderer drifts on the first label somebody changes.

WHAT MUST BE IDENTICAL to the two shipped transports, one test each:

  M1  the transport is built from `factory:` and receives BOTH the rendered
      line and the rendered card;
  M2  `events:` filters it exactly as it filters a webhook;
  M3  `enabled: false` builds nothing and never resolves the factory;
  M4  an unresolvable factory fails at LOAD, naming the target;
  M5  an object without `.send` is refused at WIRING time, because it would be
      a transport that swallows the run;
  M6  `options:` reaches the factory verbatim, since that is where an instance
      puts the names of its environment variables;
  M7  the arming flag reaches the factory, or a dry run would deliver for real.

TRUST is the same as `type: python`: the config names code, and the config is
the operator's own file, which already declares `run:` command lines.
"""
from __future__ import annotations

import pytest
from engine.config import load_pipeline_from_dict
from engine.interfaces import BoardItem
from engine.report import build_reporters

_STAGES = [{"name": "spec", "run": "cmd:true", "on_success": "done"}]


class Wire:
    """A transport shaped like every other: it only records."""

    made: list = []

    def __init__(self, **options):
        self.options = options
        self.seen: list = []
        Wire.made.append(self)

    def send(self, text, card=None):
        self.seen.append((text, card))


def build(**options):
    return Wire(**options)


def build_without_send(**options):
    return object()


def _pipeline(target):
    return load_pipeline_from_dict(
        {"pipeline": {"stages": _STAGES, "report": {"targets": [target]}}})


def _target(**over):
    base = {
        "name": "channel",
        "type": "module",
        "factory": f"{__name__}:build",
        "events": ["stage"],
    }
    base.update(over)
    return base


def _item():
    return BoardItem(id="PVTI_1", title="Scrap", status="Doing",
                     url="https://example.invalid/1")


def _reporters(cfg, **kw):
    return build_reporters(cfg.report, state_dir=kw.pop("state_dir", "/tmp"), **kw)


def setup_function():
    Wire.made = []


def test_m1_the_module_transport_receives_line_and_card(tmp_path):
    """M1: and the CARD is the point. `type: python` cannot get this."""
    pipeline = _pipeline(_target(card={"incident": "LOOP-001", "sender": "board-pilot"}))
    reporters = _reporters(pipeline, state_dir=tmp_path, armed=True)

    for reporter in reporters:
        reporter.emit("stage", _item(), stage=None, result=None)

    assert len(Wire.made) == 1
    text, card = Wire.made[0].seen[0]
    assert isinstance(text, str) and text
    assert card is not None, "the engine rendered no card; then this type has no purpose"
    assert "LOOP-001" in str(card)


def test_m2_events_filters_it_like_any_other_transport(tmp_path):
    """M2: a knob that works for a webhook and silently not here is the bug."""
    pipeline = _pipeline(_target(events=["gate"]))
    reporters = _reporters(pipeline, state_dir=tmp_path, armed=True)

    for reporter in reporters:
        reporter.emit("stage", _item(), stage=None, result=None)

    assert Wire.made[0].seen == []


def test_m3_a_disabled_target_never_resolves_the_factory(tmp_path):
    """M3: a disabled target that imports instance code has already run it."""
    pipeline = _pipeline(_target(enabled=False, factory="does.not.exist:nope"))

    assert _reporters(pipeline, state_dir=tmp_path, armed=True) == []
    assert Wire.made == []


def test_m4_an_unresolvable_factory_fails_at_load():
    """M4: loudly, and naming the target. A typo must not degrade to silence."""
    with pytest.raises(ValueError) as caught:
        _pipeline(_target(factory="no.such.module:build"))

    assert "channel" in str(caught.value)


def test_m5_an_object_without_send_is_refused_at_wiring(tmp_path):
    """M5: it would be a transport that swallows every message."""
    pipeline = _pipeline(_target(factory=f"{__name__}:build_without_send"))

    with pytest.raises(ValueError) as caught:
        _reporters(pipeline, state_dir=tmp_path, armed=True)

    assert "send" in str(caught.value)


def test_m6_options_reach_the_factory_verbatim(tmp_path):
    """M6: an instance puts its VARIABLE NAMES here, never its values."""
    pipeline = _pipeline(_target(options={"team_env": "LOOP_TEAMS_TEAM_ID",
                                          "faden_env": "LOOP_FADEN_DIR"}))
    _reporters(pipeline, state_dir=tmp_path, armed=True)

    assert Wire.made[0].options["team_env"] == "LOOP_TEAMS_TEAM_ID"
    assert Wire.made[0].options["faden_env"] == "LOOP_FADEN_DIR"


def test_m7_the_arming_flag_reaches_the_factory(tmp_path):
    """M7: both directions, because passing a constant would satisfy one.

    Without this the dry run delivers for real, which on this project means a
    rehearsal posting into the channel the demo runs in.
    """
    pipeline = _pipeline(_target())
    _reporters(pipeline, state_dir=tmp_path, armed=False)
    _reporters(pipeline, state_dir=tmp_path, armed=True)

    assert [w.options["armed"] for w in Wire.made] == [False, True]
