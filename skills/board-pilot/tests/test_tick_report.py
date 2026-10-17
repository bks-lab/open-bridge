"""The report seam: the engine says OUTWARD exactly what it writes to the board.

`Engine._emit` is the only way this module reports anything, and all eight
state-machine call sites land there. That single method is where the fan-out
lives, so this file measures it there:

  N1  no config       → no sink is built, no sink is called, nothing raises;
  N2  a stream sink   → exactly one message per stage, carrying that stage's
                        fields, and on its OWN switch (the sticky is disabled);
  N3  a throwing sink → the run advances anyway and the failure lands in the
                        ledger, never on the board;
  N4  a digest sink   → exactly ONE summary at the end, not one per stage, and
                        it survives a process boundary (a tick is a process);
  N5  one source      → the sticky comment and the outward message carry the
                        same six values, and changing the source moves both.

Every test asserts the sink ACTUALLY saw traffic before asserting what survived
it. Without that assert each one would pass against an engine with no fan-out at
all, which is the failure mode this suite exists to catch.

Nothing here touches a network. Every transport is a double.
"""
from datetime import datetime, timedelta, timezone

import pytest

from engine.board import FakeBoardClient
from engine.config import EngineConfig, RecordConfig, load_pipeline_from_dict
from engine.interfaces import BoardItem, Reporter, Stage, StageResult
from engine.report import DigestReporter, StreamReporter, build_reporters
from engine.runner import FakeStageRunner
from engine.tick import Engine

_FROZEN = datetime(2026, 9, 2, 12, 0, 0, tzinfo=timezone(timedelta(hours=2)))


class FakeTransport:
    """A sink's wire. `boom=True` makes it permanently, loudly broken."""

    def __init__(self, boom=False):
        self.sent = []
        self.boom = boom

    def send(self, text):
        self.sent.append(text)
        if self.boom:
            raise RuntimeError("webhook failed (502): bad gateway")

    def mentioning(self, needle):
        return [t for t in self.sent if needle in t]


def _pipeline():
    return [
        Stage(id="spec", run="cmd:true", on_success="implementing"),
        Stage(id="implement", run="cmd:true", on_success="verifying"),
        Stage(id="pr", run="cmd:gh pr create --draft", on_success="pr-open", gate="human"),
    ]


def _engine(tmp_path, items, *, stages=None, reporters=None, runner=None, prs=None, **cfg):
    board = FakeBoardClient(items=items, prs=prs)
    runner = runner or FakeStageRunner(board=board)
    config = EngineConfig(stages=stages or _pipeline(), trigger_status="Todo", **cfg)
    engine = Engine(config, board, runner, state_dir=tmp_path, reporters=reporters)
    return engine, board, runner


def _stream(transport, *, events=("armed", "stage", "reject", "park", "gate"), now=None):
    return StreamReporter(name="channel", transport=transport, events=events, project="demo", now=now)


def _run(engine, ticks=6):
    for _ in range(ticks):
        engine.tick()


# === N1: no config, no sink, no noise =====================================


def test_n1_without_config_no_sink_is_built_and_none_is_called(tmp_path):
    """A project that never heard of reporting must not change by one byte.

    Discriminating: the same assertion is run against a config that DOES declare a
    target. If `report` were always empty the second half fails, so an always-empty
    field cannot make this test green.
    """
    base = {"pipeline": {"stages": [{"name": "spec", "run": "cmd:true", "on_success": "done"}]}}
    silent = load_pipeline_from_dict(base)
    assert silent.report == ()

    loud = load_pipeline_from_dict(
        {
            "pipeline": {
                **base["pipeline"],
                "report": {"targets": [{"name": "channel", "type": "file", "path": "x.log"}]},
            }
        }
    )
    assert len(loud.report) == 1                     # the empty case above is a fact, not a default

    engine, board, runner = _engine(
        tmp_path, [BoardItem(id="A", title="x", status="Todo")], record=RecordConfig(enabled=False)
    )
    assert engine.reporters == []                    # nothing built from an absent block

    res = engine.tick()
    assert "A" in res.armed
    assert res.notes == ""                           # no warning, no error, nothing happened at all


def test_n1_a_declared_but_disabled_target_builds_no_reporter(tmp_path):
    """`enabled: false` is the operator's off switch and must reach the fan-out."""
    cfg = load_pipeline_from_dict(
        {
            "pipeline": {
                "stages": [{"name": "spec", "run": "cmd:true", "on_success": "done"}],
                "report": {
                    "targets": [
                        {"name": "on", "type": "file", "path": "a.log"},
                        {"name": "off", "type": "file", "path": "b.log", "enabled": False},
                    ]
                },
            }
        }
    )
    built = build_reporters(cfg.report, state_dir=tmp_path)
    assert [r.name for r in built] == ["on"]


# === N2: a channel, one message per stage, on its own switch ===============


def test_n2_stream_sink_emits_exactly_one_message_per_stage(tmp_path):
    transport = FakeTransport()
    engine, board, runner = _engine(
        tmp_path,
        [BoardItem(id="A", title="x", status="Todo")],
        reporters=[_stream(transport)],
        pr_status="In Review",
        # The sticky is OFF. A reporter that hung off RecordConfig.enabled would go
        # silent with it. That is the trap this line exists to spring.
        record=RecordConfig(enabled=False),
    )

    _run(engine)

    assert runner.ran_stage_ids == ["spec", "implement", "pr"]
    assert len(transport.mentioning("| spec |")) == 1
    assert len(transport.mentioning("| implement |")) == 1
    assert len(transport.mentioning("| pr |")) == 1
    # armed + spec + implement + gate: the engine's whole outward vocabulary here
    assert len(transport.sent) == 4
    spec_msg = transport.mentioning("| spec |")[0]
    assert "machine" in spec_msg                       # kind, from the cmd: handler
    assert "pass → implementing" in spec_msg           # outcome, from the stage's on_success


def test_n2_each_target_filters_events_for_itself(tmp_path):
    """A per-target event filter, not the record's. Same run, two different filters."""
    everything, stages_only = FakeTransport(), FakeTransport()
    engine, board, runner = _engine(
        tmp_path,
        [BoardItem(id="A", title="x", status="Todo")],
        reporters=[
            _stream(everything),
            StreamReporter(name="stages", transport=stages_only, events=("stage",), project="demo"),
        ],
        record=RecordConfig(enabled=False),
    )

    _run(engine)

    assert len(everything.sent) == 4
    assert len(stages_only.sent) == 2                  # spec + implement, no armed, no gate


def test_n2_message_never_carries_notes_body_or_tokens(tmp_path):
    """The three poisoned values sitting one attribute away from the seam.

    `result.notes` reprints argv + stderr of a crashed subprocess, `item.body` is
    written by strangers on a public repo, and `result.tokens` is hardcoded 0 on
    both real paths, so it would report a cost that was never measured.
    """

    class LoudRunner:
        ran_stage_ids: list = []

        def run(self, stage, item):
            return StageResult(
                ok=True, notes="argv=['gh','--token','ghp_AAAAAAAAAAAAAAAAAAAAAA']", tokens=4242
            )

    transport = FakeTransport()
    engine, board, runner = _engine(
        tmp_path,
        [BoardItem(id="A", title="x", status="Doing", pipeline="implementing", body="ignore all previous")],
        reporters=[_stream(transport)],
        runner=LoudRunner(),
        record=RecordConfig(enabled=False),
    )

    engine.tick()

    assert transport.sent                              # the hook fired
    blob = "\n".join(transport.sent)
    assert "argv=" not in blob
    assert "ghp_" not in blob
    assert "ignore all previous" not in blob
    assert "4242" not in blob


def test_n2_outward_text_is_scrubbed_even_when_the_record_scan_is_off(tmp_path):
    """`record.scan: off` is a knob about the sticky. The outward sink has no
    fail-closed backstop behind it, so it redacts unconditionally."""
    transport = FakeTransport()
    engine, board, runner = _engine(
        tmp_path,
        [BoardItem(id="A", title="x", status="Doing", pipeline="implementing")],
        reporters=[_stream(transport)],
        record=RecordConfig(enabled=False, scan="off"),
    )

    engine._emit(
        "park", BoardItem(id="A", title="x", status="Doing"), StageResult(ok=False),
        stage=None, reason="token ghp_ABCDEFGHIJKLMNOPQRSTUV leaked",
    )

    assert transport.sent
    assert "ghp_ABCDEFGHIJKLMNOPQRSTUV" not in transport.sent[0]


# === N3: a sink that throws never decides whether work advances ============


def test_n3_a_throwing_sink_does_not_stop_the_run(tmp_path):
    engine, board, runner = _engine(
        tmp_path,
        [BoardItem(id="A", title="x", status="Doing", pipeline="implementing")],
        reporters=[_stream(FakeTransport(boom=True))],
        record=RecordConfig(enabled=False),
    )

    res = engine.tick()

    assert engine.reporters[0].transport.sent            # the sink was actually reached
    assert board.pipeline_of("A") == "verifying"         # the advance stood
    assert "A" in res.dispatched
    assert "A" not in res.skipped
    assert "channel" in res.notes                        # named in the ledger
    assert "502" in res.notes


def test_n3_a_throwing_sink_never_re_runs_a_stage(tmp_path):
    """The damage a swallowed report failure does is not a missing message: it is a
    successful advance reported as a skip, which re-dispatches the most expensive
    stage on every poll forever."""
    engine, board, runner = _engine(
        tmp_path,
        [BoardItem(id="A", title="x", status="Todo")],
        reporters=[_stream(FakeTransport(boom=True))],
        pr_status="In Review",
        record=RecordConfig(enabled=False),
    )

    _run(engine)

    assert board.pipeline_of("A") == "pr-open"
    assert board.status_of("A") == "In Review"
    assert runner.ran_stage_ids == ["spec", "implement", "pr"]


def test_n3_one_broken_sink_does_not_silence_the_other(tmp_path):
    """Each sink is guarded on its own. A shared guard would let the first failure
    eat every later target in the same emit."""
    healthy = FakeTransport()
    engine, board, runner = _engine(
        tmp_path,
        [BoardItem(id="A", title="x", status="Doing", pipeline="implementing")],
        reporters=[
            StreamReporter(name="broken", transport=FakeTransport(boom=True), events=("stage",)),
            StreamReporter(name="healthy", transport=healthy, events=("stage",)),
        ],
        record=RecordConfig(enabled=False),
    )

    engine.tick()

    assert len(healthy.sent) == 1
    assert board.pipeline_of("A") == "verifying"


def test_n3_the_sticky_still_lands_when_the_channel_is_broken(tmp_path):
    """The two sinks are independent in BOTH directions."""
    engine, board, runner = _engine(
        tmp_path,
        [BoardItem(id="A", title="x", status="Doing", pipeline="implementing")],
        reporters=[_stream(FakeTransport(boom=True))],
        record=RecordConfig(enabled=True, events=("stage",)),
    )

    engine.tick()

    bodies = [c["body"] for c in board.list_comments("A")]
    assert bodies and "| implement |" in bodies[0]


# === N4: one summary at the end, not one per stage =========================


def test_n4_digest_sends_once_at_the_end_while_the_channel_sends_per_stage(tmp_path):
    channel, summary = FakeTransport(), FakeTransport()
    engine, board, runner = _engine(
        tmp_path,
        [BoardItem(id="A", title="x", status="Todo")],
        reporters=[
            _stream(channel),
            DigestReporter(
                name="summary",
                transport=summary,
                events=("armed", "stage", "reject", "park", "gate"),
                flush_on=("gate", "park"),
                state_dir=tmp_path,
                project="demo",
            ),
        ],
        pr_status="In Review",
        record=RecordConfig(enabled=False),
    )

    _run(engine)

    assert len(channel.sent) == 4                  # the run really produced four events
    assert len(summary.sent) == 1                  # and exactly one summary
    body = summary.sent[0]
    for stage_id in ("spec", "implement", "pr"):
        assert f"| {stage_id} |" in body           # the summary carries the whole run


def test_n4_digest_survives_the_process_boundary(tmp_path):
    """A tick is a process, launchd is the loop. An in-memory collector loses every
    row of every tick that did not itself reach the gate, which is all of them."""
    board = FakeBoardClient(items=[BoardItem(id="A", title="x", status="Todo")])
    runner = FakeStageRunner(board=board)
    config = EngineConfig(stages=_pipeline(), trigger_status="Todo", pr_status="In Review",
                          record=RecordConfig(enabled=False))

    def _digest(transport):
        return DigestReporter(
            name="summary", transport=transport, events=("armed", "stage", "reject", "park", "gate"),
            flush_on=("gate", "park"), state_dir=tmp_path, project="demo",
        )

    early = FakeTransport()
    first = Engine(config, board, runner, state_dir=tmp_path, reporters=[_digest(early)])
    first.tick()                                    # armed
    first.tick()                                    # spec
    assert early.sent == []                         # nothing terminal yet, so nothing sent

    late = FakeTransport()
    second = Engine(config, board, runner, state_dir=tmp_path, reporters=[_digest(late)])
    for _ in range(4):
        second.tick()

    assert len(late.sent) == 1
    assert "| spec |" in late.sent[0]               # a row the FIRST process wrote
    assert "| pr |" in late.sent[0]


def test_n4_digest_flushes_on_park_too(tmp_path):
    """`park` is terminal as much as `gate` is. A digest that only knew the happy
    path would never send for a run that died."""
    summary = FakeTransport()
    engine, board, runner = _engine(
        tmp_path,
        [BoardItem(id="A", title="x", status="Doing", pipeline="implementing")],
        runner=FakeStageRunner(fail_stage="implement"),
        reporters=[
            DigestReporter(
                name="summary", transport=summary, events=("stage", "park"),
                flush_on=("park",), state_dir=tmp_path, project="demo",
            )
        ],
        record=RecordConfig(enabled=False),
    )

    engine.tick()

    assert len(summary.sent) == 1
    assert "**parked**" in summary.sent[0]


def test_n4_digest_starts_empty_for_the_next_run(tmp_path):
    """The spool is cleared on flush: a second run must not re-report the first."""
    summary = FakeTransport()
    reporter = DigestReporter(
        name="summary", transport=summary, events=("stage", "gate"), flush_on=("gate",),
        state_dir=tmp_path, project="demo",
    )
    engine, board, runner = _engine(
        tmp_path,
        [BoardItem(id="A", title="x", status="Todo")],
        reporters=[reporter],
        pr_status="In Review",
        record=RecordConfig(enabled=False),
    )
    _run(engine)
    assert len(summary.sent) == 1

    item = BoardItem(id="A", title="x", status="Doing", pipeline="implementing")
    reporter.emit("stage", item, stage=_pipeline()[1], result=StageResult(ok=True),
                  to="verifying", outcome="pass")
    reporter.emit("gate", item, stage=_pipeline()[2], result=StageResult(ok=True),
                  to="pr-open", status_to="In Review")

    assert len(summary.sent) == 2
    assert summary.sent[1].count("|") < summary.sent[0].count("|")   # the second run is its own


# === N5: one source, two renderings ========================================


class _MeasuredRunner:
    """Returns the parent-observed fields the record cites: duration and criteria."""

    def __init__(self):
        self.ran_stage_ids = []

    def run(self, stage, item):
        self.ran_stage_ids.append(stage.id)
        return StageResult(ok=True, duration_s=42.0, criteria_ref="review.md@abc1234")


def _data_row(body):
    """The one data row of the sticky's table (the separator line is not data)."""
    rows = [ln for ln in body.splitlines() if ln.startswith("|") and "2026-09-02" in ln]
    assert len(rows) == 1, body
    return [c.strip() for c in rows[0].strip("|").split("|")]


def _message_cells(text):
    """The six values of the row the message carries. Its head is not one of them."""
    return [c.strip() for c in text.split("|")[1:-1]]


@pytest.mark.parametrize(
    "run_ref,expected_kind",
    [("cmd:true", "machine"), ("agent:reviewer", "agent")],
)
def test_n5_comment_and_message_carry_the_same_six_values(tmp_path, run_ref, expected_kind):
    """ONE source, two renderings, so the board and the channel can never disagree.

    The parametrisation IS the discriminator: `kind` is derived by the shared
    source from the stage's handler prefix. Changing that one input must move BOTH
    renderings. A reporter with its own private formatter passes the first case and
    fails the second.

    Both renderers get the SAME frozen clock, so `when` is comparable too: the field
    is real, it is just each renderer's own read of the clock in production.
    """
    stage = Stage(id="spec", run=run_ref, on_success="implementing")
    transport = FakeTransport()
    engine, board, runner = _engine(
        tmp_path,
        [BoardItem(id="A", title="x", status="Doing", pipeline="queued", issue_number=7)],
        stages=[stage, Stage(id="pr", run="cmd:gh pr create", on_success="pr-open", gate="human")],
        runner=_MeasuredRunner(),
        reporters=[_stream(transport, events=("stage",), now=lambda: _FROZEN)],
        record=RecordConfig(enabled=True, events=("stage",)),
    )
    engine.recorder._now = lambda: _FROZEN

    engine.tick()

    assert transport.sent, "the reporter never fired"
    comment_cells = _data_row(board.list_comments("A")[0]["body"])
    message_cells = _message_cells(transport.sent[0])

    assert comment_cells[1] == "spec"
    assert comment_cells[2] == expected_kind
    assert comment_cells[3] == "review.md@abc1234"
    assert comment_cells[4] == "42s"
    assert comment_cells[5] == "pass → implementing"
    # and the message says the very same thing, cell for cell
    assert message_cells[-6:] == comment_cells


def test_n5_the_message_names_the_item_the_sticky_is_attached_to(tmp_path):
    """The sticky's identity is its anchor (it hangs on the issue). A free-standing
    message has to carry that identity in the text or it is unattributable.

    Driven through the DEFAULT path (a `report:` block in the project config, built
    by the engine itself, no injected double), because that is the wiring the live
    run uses and nothing else in this file exercises it end to end.
    """
    log = tmp_path / "channel.log"
    cfg = load_pipeline_from_dict(
        {
            "pipeline": {
                "project": "demo-loop",
                "stages": [
                    {"name": "spec", "run": "cmd:true", "on_success": "implementing"},
                    {"name": "implement", "run": "cmd:true", "on_success": "verifying"},
                    {"name": "pr", "run": "cmd:gh pr create", "on_success": "pr-open", "gate": "human"},
                ],
                "report": {"targets": [{"name": "channel", "type": "file", "path": str(log)}]},
            }
        }
    )
    board = FakeBoardClient(items=[BoardItem(id="A", title="x", status="Doing",
                                             pipeline="implementing", issue_number=7)])
    engine = Engine(cfg, board, FakeStageRunner(board=board), state_dir=tmp_path)

    assert [r.name for r in engine.reporters] == ["channel"]
    engine.tick()

    text = log.read_text(encoding="utf-8")
    assert "demo-loop" in text
    assert "#7" in text
    assert "| implement |" in text


# === the port ==============================================================


def test_the_recorder_is_already_a_reporter():
    """The seam names what already existed rather than inventing a second shape."""
    from engine.record import Recorder

    assert isinstance(Recorder(None, RecordConfig()), Reporter)
    assert isinstance(StreamReporter(name="x", transport=FakeTransport(), events=()), Reporter)


def test_the_fan_out_reads_the_recorder_at_call_time(tmp_path):
    """24 tests in test_tick_record.py replace `engine.recorder` AFTER construction.

    A fan-out that froze `[self.recorder, *self.reporters]` in `__init__` would keep
    reporting to the original recorder, and every one of those tests would go green
    against an object nothing measures.
    """

    class Spy:
        def __init__(self):
            self.events = []

        def emit(self, event, item, *, stage=None, result=None, **fields):
            self.events.append(event)

    engine, board, runner = _engine(
        tmp_path, [BoardItem(id="A", title="x", status="Doing", pipeline="implementing")]
    )
    engine.recorder = Spy()

    engine.tick()

    # The start comes BEFORE the end, and the order is measured here too: if
    # `stage_start` landed after `stage` it would be worthless as a heartbeat.
    assert engine.recorder.events == ["stage_start", "stage"]
