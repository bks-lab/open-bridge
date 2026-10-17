"""`type: python` — the seam an instance fills with its own sink.

WHY THIS EXISTS, and why it is not an Elastic feature. This skill is `scope: core`
and ships to the public upstream, so it must never learn a vendor: no index name,
no auth header, no document shape. But an instance may well need its run to land
somewhere this engine has no business knowing about — a search cluster, a metrics
bus, a queue. The generic answer is to let the CONFIG name a callable and to keep
everything else identical to the two shipped transports.

WHAT MUST BE IDENTICAL, and each of these is a test below:

  X1  the sink is built from `factory:` and receives the run;
  X2  `events:` filters it exactly as it filters a webhook or a file. Without the
      wrapper the config key would silently do nothing for this type, which is the
      same class of bug as an ignored knob;
  X3  `enabled: false` builds nothing and never even resolves the factory. A
      disabled target that still imports a module has already run instance code;
  X4  a factory that cannot be resolved fails at LOAD, naming the target and the
      spec. The whole posture of `report:` is that a typo must not degrade to
      "silent while the channel stays quiet";
  X5  an object without `.emit` is refused at WIRING time for the same reason: it
      would be a sink that swallows the run. Wiring, not load, and the split is
      deliberate: load resolves the attribute and checks it is callable, the build
      calls it and checks the result. Checking `.emit` at load would mean calling
      the factory once to inspect it and once to use it, so any construction side
      effect would happen twice — and the port only promises construction is
      CHEAP, never that it is free. Both points sit before any work and both fail
      loudly, which is the property that matters;
  X6  a sink that raises never stops the work. It rides the same guard as every
      other sink, and the failure lands in the ledger.

TRUST. `factory:` runs code the config names, in the engine's own process. That is
not a new boundary: the same file already declares `run:` command lines for every
stage, and both come from the operator's own repo. It is stated here so nobody has
to infer it.
"""
from __future__ import annotations

import pytest

from engine.config import load_pipeline_from_dict
from engine.interfaces import BoardItem
from engine.report import build_reporters

_STAGES = [{"name": "spec", "run": "cmd:true", "on_success": "done"}]


class Recorder:
    """A sink shaped like every other: it only records."""

    made = []

    def __init__(self, **options):
        self.options = options
        self.seen = []
        Recorder.made.append(self)

    def emit(self, event, item, *, stage=None, result=None, **fields):
        self.seen.append(event)


class NotASink:
    """Resolvable, callable, and returns something with no `emit`."""

    def __init__(self, **options):
        pass


class Exploding:
    def __init__(self, **options):
        pass

    def emit(self, *a, **kw):
        raise RuntimeError("sink is down")


def _load(target):
    return load_pipeline_from_dict(
        {"pipeline": {"stages": _STAGES, "report": {"targets": [target]}}}
    )


def _target(**over):
    base = {"name": "journal", "type": "python",
            "factory": f"{__name__}:Recorder"}
    base.update(over)
    return base


def _built(target, **kw):
    cfg = _load(target)
    return build_reporters(cfg.report, state_dir=kw.pop("state_dir", "/tmp"), **kw)


@pytest.fixture(autouse=True)
def _clear():
    Recorder.made = []
    yield
    Recorder.made = []


# --- X1 ---------------------------------------------------------------------
def test_x1_the_named_factory_is_built_and_receives_the_run(tmp_path):
    (sink,) = _built(_target(), state_dir=str(tmp_path))
    sink.emit("armed", object())

    assert Recorder.made, "the factory was never called"
    assert Recorder.made[0].seen == ["armed"], (
        "the run did not reach the sink: " + repr(Recorder.made[0].seen))


def test_x1b_options_reach_the_factory_as_keywords(tmp_path):
    _built(_target(options={"index": "demo", "tries": 3}), state_dir=str(tmp_path))
    assert Recorder.made[0].options == {"index": "demo", "tries": 3}


# --- X2 ---------------------------------------------------------------------
def test_x2_the_events_filter_applies_here_too(tmp_path):
    """CONTROL for X1. An unwrapped sink would see everything, and `events:` would
    be a knob that silently does nothing for exactly one target type."""
    (sink,) = _built(_target(events=["gate"]), state_dir=str(tmp_path))
    item = object()
    sink.emit("armed", item)
    sink.emit("stage_start", item)
    sink.emit("gate", item)

    assert Recorder.made[0].seen == ["gate"], (
        "the sink saw events it did not ask for: " + repr(Recorder.made[0].seen))


# --- X3 ---------------------------------------------------------------------
def test_x3_a_disabled_target_never_even_resolves_the_factory(tmp_path):
    built = _built(_target(enabled=False), state_dir=str(tmp_path))
    assert built == [], "a disabled target was built"
    assert Recorder.made == [], (
        "a disabled target still ran instance code. `enabled: false` must mean "
        "nothing happens, not that it happens and is then discarded")


# --- X4 + X5 ----------------------------------------------------------------
def test_x4_an_unresolvable_factory_fails_at_load_naming_it():
    with pytest.raises(ValueError) as e:
        _load(_target(factory="no.such.module:Thing"))
    text = str(e.value)
    assert "journal" in text and "no.such.module:Thing" in text, (
        "the error names neither the target nor the spec: " + text)


def test_x4b_a_factory_without_a_colon_is_refused():
    with pytest.raises(ValueError) as e:
        _load(_target(factory="engine.report"))
    assert "factory" in str(e.value)


def test_x4c_a_python_target_must_declare_a_factory():
    with pytest.raises(ValueError) as e:
        _load({"name": "journal", "type": "python"})
    assert "factory" in str(e.value)


def test_x5_an_object_without_emit_is_refused_at_wiring_time(tmp_path):
    """Loud, and before any work. See the header for why this is the build and not
    the load: a load-time check would call the factory twice."""
    with pytest.raises(ValueError) as e:
        _built(_target(factory=f"{__name__}:NotASink"), state_dir=str(tmp_path))
    text = str(e.value)
    assert "emit" in text, "the error does not say what is missing: " + text
    assert "journal" in text, "the error does not name the target: " + text


def test_x5b_url_env_and_path_are_refused_on_a_python_target():
    """They would never be read, and a key that is never read is a lie about where
    the address comes from. The other two types refuse the same way."""
    for key, value in (("url_env", "BP_X"), ("path", "/tmp/x.log")):
        with pytest.raises(ValueError) as e:
            _load(_target(**{key: value}))
        assert key in str(e.value)


# --- X6 ---------------------------------------------------------------------
def test_x6_a_sink_that_raises_does_not_stop_the_work(tmp_path):
    """It rides the same guard as every other sink. Measured here rather than
    assumed, because this is the one sink type whose code the engine did not write."""
    from engine.record import emit_guarded

    (sink,) = _built(_target(factory=f"{__name__}:Exploding"), state_dir=str(tmp_path))

    class Res:
        notes = ""

    res = Res()
    emit_guarded(sink, res, "armed", BoardItem(id="A", title="x", status="Todo"))
    assert "journal" in res.notes, (
        "the failing sink is not named in the ledger: " + repr(res.notes))
