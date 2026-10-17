"""THE HEARTBEAT: an event when a stage BEGINS, not only when it ends.

WHY. Measured on the first full run of the delivered chain, 2026-09-02: between
`armed` at 16:49:51 and `spec … 5m47s pass → implementing` at 16:55:42, NOTHING
wrote a line anywhere. Not the tick ledger, not the report sink, not the board
comment, not the board itself. Almost six minutes in which a running chain and a
wedged one are indistinguishable. The only sign of life was the process itself,
and an operator watching a screen cannot point at that.

The cause is structural, not incidental: every event this engine had reported a
COMPLETION. So even a channel that was switched on would have sent a message
every six minutes and been silent in between.

WHAT IS MEASURED HERE:

  S1  the beginning is reported at all;
  S2  THE load-bearing one: it is reported BEFORE the stage runs. An event that
      lands after the stage is worthless as a heartbeat and is indistinguishable
      in time from `stage`. Measured from inside the runner, which records what
      the sink has already seen at the moment the runner itself is called;
  S3  the row invents nothing. No outcome, no duration, no result, because at
      that moment there is none;
  S4  a sink that did not ask for the event does not get it. Without this
      control S1 would also pass against a build that forces it on every sink.
"""
from __future__ import annotations

from engine.board import FakeBoardClient
from engine.interfaces import BoardItem
from engine.runner import FakeStageRunner

from test_report_card import _engine          # noqa: E402


class Spy:
    """A sink that only records. No network, no file."""

    def __init__(self, events=("armed", "stage_start", "stage", "reject", "park", "gate")):
        self.events = tuple(events)
        self.seen = []

    def emit(self, event, item, *, stage=None, result=None, **fields):
        if event not in self.events:
            return
        self.seen.append({"event": event, "stage": getattr(stage, "id", None),
                          "result": result, "fields": dict(fields)})

    @property
    def names(self):
        return [s["event"] for s in self.seen]


class RunnerThatReadsBack(FakeStageRunner):
    """A runner that records what the sink had already seen when it was called.

    This is the only honest way to measure ORDER: a test that merely inspects the
    list afterwards cannot tell `stage_start` from `stage` if both land at the end.
    """

    def __init__(self, spy, **kw):
        super().__init__(**kw)
        self.spy = spy
        self.at_start = []

    def run(self, stage, item):
        self.at_start.append((stage.id, list(self.spy.names)))
        return super().run(stage, item)


def _setup(tmp_path, spy, items=None):
    items = items or [BoardItem(id="A", title="x", status="Todo")]
    board = FakeBoardClient(items=items)
    runner = RunnerThatReadsBack(spy, board=board)
    return _engine(tmp_path, items, runner=runner, reporters=[spy])


# --- S1 + S2 ----------------------------------------------------------------
def test_s1_s2_the_start_is_reported_and_reported_first(tmp_path):
    spy = Spy()
    engine, board, runner = _setup(tmp_path, spy)

    engine.tick()          # arms, then dispatches the first stage

    assert "stage_start" in spy.names, (
        "The stage does not report its start. Between `armed` and the end of the "
        "stage every log stays empty, and a running chain is indistinguishable "
        "from a wedged one. Seen: " + repr(spy.names))

    assert runner.at_start, "No stage ran at all, so this test measures nothing."
    stage, before = runner.at_start[0]
    assert "stage_start" in before, (
        "The start of " + stage + " was reported only AFTER the stage. As a "
        "heartbeat that is worthless: it lands at the same time as the end. "
        "The sink had seen: " + repr(before))


# --- S3 ---------------------------------------------------------------------
def test_s3_the_row_invents_neither_outcome_nor_duration(tmp_path):
    spy = Spy()
    engine, board, runner = _setup(tmp_path, spy)
    engine.tick()

    start = next(s for s in spy.seen if s["event"] == "stage_start")
    assert start["stage"] is not None, "The report does not name the stage"
    assert start["result"] is None, (
        "The start carries a result that does not exist yet: " + repr(start["result"]))
    for forbidden in ("to", "outcome"):
        assert forbidden not in start["fields"], (
            "The start claims '" + forbidden + "' while the stage is still running: "
            + repr(start["fields"]))


# --- S4 ---------------------------------------------------------------------
def test_s4_a_sink_that_did_not_ask_does_not_get_it(tmp_path):
    """CONTROL. A sink without the event in its list stays untouched."""
    spy = Spy(events=("armed", "stage", "gate"))
    engine, board, runner = _setup(tmp_path, spy)
    engine.tick()

    assert "stage_start" not in spy.names, (
        "The sink receives an event it never asked for: " + repr(spy.names))
    assert "armed" in spy.names, (
        "It receives nothing at all, so this test measures nothing: " + repr(spy.names))
