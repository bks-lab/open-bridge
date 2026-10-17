"""The `report:` block is checked at LOAD, because at runtime it is almost invisible.

`emit_guarded` catches everything a sink can throw and files it in `res.notes`, the
launchd ledger, on purpose: a report must never decide whether work advances. That
same property means a typo'd target degrades to "a line in a log nobody reads while
the channel stays quiet", which during a live demo is indistinguishable from "the
automation is thinking". So every value a human can type here is checked at load,
against a closed set, naming the offender. That is the posture `record:`/`evidence:`
already have (config.validate_transparency).

The event vocabulary is IMPORTED, never re-typed. Three copies of one list is three
places for a new event to arrive in two of them.
"""
import pytest

import engine.config as config_mod
import engine.record as record_mod
from engine.config import ReportTarget, load_pipeline_from_dict
from engine.report import build_reporters

_STAGES = [{"name": "spec", "run": "cmd:true", "on_success": "done"}]


def _load(report):
    return load_pipeline_from_dict({"pipeline": {"stages": _STAGES, "report": report}})


def _targets(*targets):
    return {"targets": list(targets)}


def _webhook(**over):
    base = {"name": "channel", "type": "webhook", "url_env": "BP_DEMO_WEBHOOK"}
    base.update(over)
    return base


# === the vocabulary is one set, imported ===================================


def test_the_event_vocabulary_is_imported_not_retyped():
    """Same OBJECT, not merely equal: a copy passes an equality check on the day it
    is made and diverges silently on the day someone adds an event to one of them."""
    assert config_mod._RECORD_EVENTS is record_mod.EVENTS


# === the block loads, and its absence changes nothing ======================


def test_absent_block_is_an_empty_target_list():
    assert load_pipeline_from_dict({"pipeline": {"stages": _STAGES}}).report == ()


def test_a_target_round_trips_with_its_defaults():
    (t,) = _load(_targets(_webhook())).report
    assert isinstance(t, ReportTarget)
    assert (t.name, t.type, t.mode, t.enabled) == ("channel", "webhook", "stream", True)
    # DEFAULT_EVENTS, not EVENTS: since `note` exists, the vocabulary a list is
    # validated against and the list a silent target gets are two different
    # things. A target that says nothing must not start receiving notes.
    assert t.events == record_mod.DEFAULT_EVENTS
    assert "note" in record_mod.EVENTS and "note" not in t.events
    assert t.url_env == "BP_DEMO_WEBHOOK"


# === every knob a human can typo ===========================================


def test_unknown_block_key_is_refused():
    with pytest.raises(ValueError, match="report"):
        _load({"targets": [], "enabled": True})


def test_unknown_target_key_is_refused():
    with pytest.raises(ValueError, match="url"):
        _load(_targets(_webhook(url="https://example.invalid/hook")))


def test_unknown_type_is_refused():
    with pytest.raises(ValueError, match="teams"):
        _load(_targets(_webhook(type="teams")))


def test_unknown_mode_is_refused():
    with pytest.raises(ValueError, match="batch"):
        _load(_targets(_webhook(mode="batch")))


def test_unknown_event_is_refused():
    with pytest.raises(ValueError, match="dispatched"):
        _load(_targets(_webhook(events=["stage", "dispatched"])))


def test_a_nameless_target_is_refused():
    with pytest.raises(ValueError, match="name"):
        _load(_targets({"type": "webhook", "url_env": "X"}))


def test_two_targets_may_not_share_a_name():
    with pytest.raises(ValueError, match="channel"):
        _load(_targets(_webhook(), _webhook(mode="digest", flush_on=["gate"])))


# === the address is a POINTER, never a value ===============================


def test_a_url_in_url_env_is_refused():
    """board-pilot is scope: core and ships INTO the target repo, and the demo repo
    is public. `url_env` names an environment variable; a URL there is a webhook
    address committed to a public repo, which is a leak with a valid schema.
    """
    with pytest.raises(ValueError, match="environment variable"):
        _load(_targets(_webhook(url_env="https://example.invalid/hook")))


def test_a_webhook_without_url_env_is_refused():
    with pytest.raises(ValueError, match="url_env"):
        _load(_targets({"name": "channel", "type": "webhook"}))


def test_a_webhook_may_not_carry_a_path():
    with pytest.raises(ValueError, match="path"):
        _load(_targets(_webhook(path="/tmp/x.log")))


def test_a_file_target_needs_a_path_and_no_url_env():
    with pytest.raises(ValueError, match="path"):
        _load(_targets({"name": "f", "type": "file"}))
    with pytest.raises(ValueError, match="url_env"):
        _load(_targets({"name": "f", "type": "file", "path": "x.log", "url_env": "X"}))


# === the digest/stream split ===============================================


def test_a_digest_without_flush_on_is_refused():
    """A digest that never flushes collects forever and reports nothing: the exact
    failure it exists to prevent, wearing a green config."""
    with pytest.raises(ValueError, match="flush_on"):
        _load(_targets(_webhook(mode="digest", flush_on=[])))


def test_a_flush_event_the_target_filters_out_is_refused():
    """`events` is the filter; a flush event outside it never arrives."""
    with pytest.raises(ValueError, match="flush_on"):
        _load(_targets(_webhook(mode="digest", events=["stage"], flush_on=["gate"])))


def test_a_stream_target_may_not_carry_flush_on():
    with pytest.raises(ValueError, match="flush_on"):
        _load(_targets(_webhook(flush_on=["gate"])))


# === load → build ===========================================================


def test_the_loaded_targets_build_the_two_shapes(tmp_path):
    from engine.report import DigestReporter, StreamReporter

    cfg = _load(
        _targets(
            {"name": "channel", "type": "file", "path": str(tmp_path / "c.log")},
            {"name": "summary", "type": "file", "path": str(tmp_path / "s.log"),
             "mode": "digest", "flush_on": ["gate", "park"]},
        )
    )
    built = build_reporters(cfg.report, state_dir=tmp_path)
    assert [type(r) for r in built] == [StreamReporter, DigestReporter]
    assert built[1].flush_on == ("gate", "park")


def test_building_a_webhook_target_reads_no_secret_and_opens_no_socket(tmp_path, monkeypatch):
    """The Recorder is constructed even when disabled, so engine start stays offline.
    A reporter that resolved its address (or its secret) in __init__ would hang the
    engine's start on a network resource, and fail it on a box where the variable
    is simply not exported yet."""
    monkeypatch.delenv("BP_DEMO_WEBHOOK", raising=False)
    built = build_reporters(_load(_targets(_webhook())).report, state_dir=tmp_path)
    assert len(built) == 1                      # constructed fine with no variable set
