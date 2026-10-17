"""The 5 record hooks in tick.py — and the one invariant that outranks the record.

THE HARDEST INVARIANT: a record write must never decide whether work advances.
Every hook fires AFTER its latch and goes through `emit_guarded`. Unguarded, a
raising hook lands in the dispatch loop's outer guard → `res.skipped` → the item
re-dispatches next poll WITHOUT rolling back the `set_pipeline` that already
landed. A permanently failing sink (a 403, a deleted issue) therefore re-runs the
most expensive stage on every poll forever, while reporting a successful advance
as a skip.

Every test here asserts the hook ACTUALLY FIRED (`recorder.calls`) before asserting
what survived it. Without that assert, each one would pass against an engine with no
hooks at all — proving nothing.
"""
import pytest

from engine.board import FakeBoardClient
from engine.config import EngineConfig, RecordConfig
from engine.interfaces import BoardItem, Stage, StageResult
from engine.runner import FakeStageRunner
from engine.tick import Engine


class SpyRecorder:
    """Captures every emit. `boom=True` makes the sink permanently, loudly broken."""

    def __init__(self, boom=False):
        self.events = []
        self.boom = boom

    def emit(self, event, item, *, stage=None, result=None, **fields):
        self.events.append({
            "event": event,
            "item": item.id,
            "stage": getattr(stage, "id", None),
            "result": result,
            **fields,
        })
        if self.boom:
            raise RuntimeError("gh failed (403): resource not accessible by integration")

    # helpers ------------------------------------------------------------
    @property
    def calls(self):
        return len(self.events)

    def of(self, event):
        return [e for e in self.events if e["event"] == event]


def _pipeline():
    return [
        Stage(id="spec", run="cmd:true", on_success="implementing"),
        Stage(id="implement", run="cmd:true", on_success="verifying"),
        Stage(id="pr", run="cmd:gh pr create --draft", on_success="pr-open", gate="human"),
    ]


def _reject_pipeline():
    return [
        Stage(id="spec", run="cmd:true", on_success="implementing"),
        Stage(id="implement", run="cmd:true", on_success="verifying"),
        Stage(id="review", run="cmd:true", on_success="pr-ready", reject_to="implement"),
        Stage(id="pr", run="cmd:gh pr create --draft", on_success="pr-open", gate="human"),
    ]


def _engine(tmp_path, items, stages=None, prs=None, runner=None, **cfg):
    board = FakeBoardClient(items=items, prs=prs)
    runner = runner or FakeStageRunner(board=board)
    config = EngineConfig(stages=stages or _pipeline(), trigger_status="Todo", **cfg)
    return Engine(config, board, runner, state_dir=tmp_path), board, runner


# === the key test ==========================================================


def test_record_failure_never_converts_advance_to_skip(tmp_path):
    """The advance happened. It must be REPORTED as an advance.

    `res.skipped` is not cosmetic: it is what the next tick and the ledger read. A
    successful advance reported as a skip, with no rollback, is worse than a missing
    record — it is a wrong one, in the artifact that exists to be right.
    """
    engine, board, runner = _engine(
        tmp_path, [BoardItem(id="A", title="x", status="Doing", pipeline="implementing")]
    )
    engine.recorder = SpyRecorder(boom=True)

    res = engine.tick()

    # TWO since 2026-09-02: a stage reports its start and its end. Both go through
    # the same guarded seam, and BOTH must be allowed to fail without turning the
    # advance into a skip. The number stays exact: a `>= 1` would also pass against
    # an engine that reports only once, which is precisely what should be noticed.
    assert engine.recorder.calls == 2               # both hooks fired (red without hooks)
    assert board.pipeline_of("A") == "verifying"    # the advance stood
    assert "A" in res.dispatched
    assert "A" not in res.skipped                   # and was reported as one
    assert "record" in res.notes                    # the failure went to the ledger


def test_record_write_failure_does_not_block_transition(tmp_path):
    """Same guard, driven across a whole run: a permanently broken sink must not
    keep an item from reaching the gate, and must not re-run a single stage."""
    engine, board, runner = _engine(
        tmp_path, [BoardItem(id="A", title="x", status="Todo")], pr_status="In Review"
    )
    engine.recorder = SpyRecorder(boom=True)

    for _ in range(6):
        engine.tick()

    assert engine.recorder.calls >= 4
    assert board.pipeline_of("A") == "pr-open"
    assert board.status_of("A") == "In Review"
    assert runner.ran_stage_ids == ["spec", "implement", "pr"]   # nothing re-ran


def test_record_failure_does_not_block_the_park_transition(tmp_path):
    """The park sites write the record too, and a park is a TERMINAL state: a hook
    that hijacked it would leave the item in-flight and re-dispatching."""
    engine, board, runner = _engine(
        tmp_path, [BoardItem(id="A", title="x", status="Doing", pipeline="implementing")]
    )
    runner.run = lambda stage, item: StageResult(ok=False, notes="boom")
    engine.recorder = SpyRecorder(boom=True)

    res = engine.tick()

    assert engine.recorder.of("park")
    assert board.pipeline_of("A") == "parked"
    assert "A" in res.parked


# === the 5 events ==========================================================


def test_armed_event_fires_after_the_latch(tmp_path):
    engine, board, _ = _engine(
        tmp_path, [BoardItem(id="A", title="x", status="Todo")], working_status="In Progress"
    )
    engine.recorder = SpyRecorder()

    engine.tick()

    armed = engine.recorder.of("armed")
    assert len(armed) == 1
    assert armed[0]["to"] == "queued"
    assert armed[0]["status_to"] == "In Progress"
    assert armed[0]["stage"] is None   # no stage is resolved at ARM — never invent one


def test_stage_pass_is_recorded(tmp_path):
    engine, board, _ = _engine(
        tmp_path, [BoardItem(id="A", title="x", status="Doing", pipeline="implementing")]
    )
    engine.recorder = SpyRecorder()

    engine.tick()

    passes = engine.recorder.of("stage")
    assert len(passes) == 1
    assert passes[0]["stage"] == "implement"
    assert passes[0]["outcome"] == "pass"
    assert passes[0]["to"] == "verifying"
    assert passes[0]["result"] is not None   # duration + criteria_ref ride on it


def test_retry_is_recorded(tmp_path):
    """A retry is INVISIBLE today: no board write, no notes append, `result.notes`
    discarded, an anonymous entry in `res.skipped` indistinguishable from a lock
    skip. It is exactly the "which stage is weak" signal the record exists to give.
    """
    stages = [
        Stage(id="spec", run="cmd:true", on_success="implementing"),
        Stage(id="implement", run="cmd:true", on_success="verifying", retry=2),
        Stage(id="pr", run="cmd:gh pr create --draft", on_success="pr-open", gate="human"),
    ]
    engine, board, runner = _engine(
        tmp_path,
        [BoardItem(id="A", title="x", status="Doing", pipeline="implementing")],
        stages=stages,
    )
    runner.run = lambda stage, item: StageResult(ok=False, notes="flaky")
    engine.recorder = SpyRecorder()

    engine.tick()

    retries = [e for e in engine.recorder.of("stage") if e.get("outcome") == "retry"]
    assert len(retries) == 1
    assert retries[0]["stage"] == "implement"
    assert retries[0]["attempt"] == 1
    assert retries[0]["of"] == 2
    assert board.pipeline_of("A") == "implementing"   # unmoved: the stage re-runs


def test_rewind_is_recorded(tmp_path):
    stages = [
        Stage(id="spec", run="cmd:true", on_success="implementing"),
        Stage(
            id="implement",
            run="cmd:true",
            on_success="verifying",
            on_fail="rewind",
            rewind_to="queued",
        ),
        Stage(id="pr", run="cmd:gh pr create --draft", on_success="pr-open", gate="human"),
    ]
    engine, board, runner = _engine(
        tmp_path,
        [BoardItem(id="A", title="x", status="Doing", pipeline="implementing")],
        stages=stages,
        max_rounds=3,
    )
    runner.run = lambda stage, item: StageResult(ok=False, notes="crash")
    engine.recorder = SpyRecorder()

    engine.tick()

    rewinds = [e for e in engine.recorder.of("stage") if e.get("outcome") == "rewind"]
    assert len(rewinds) == 1
    assert rewinds[0]["to"] == "queued"
    assert board.pipeline_of("A") == "queued"


def test_reject_is_recorded_with_its_round(tmp_path):
    engine, board, runner = _engine(
        tmp_path,
        [BoardItem(id="A", title="x", status="Doing", pipeline="verifying")],
        stages=_reject_pipeline(),
        max_rounds=3,
        runner=None,
    )
    engine.runner = FakeStageRunner(
        board=board, reject_stage="review", reject_to="implement", annotation="no negative-path test"
    )
    engine.recorder = SpyRecorder()

    engine.tick()

    rejects = engine.recorder.of("reject")
    assert len(rejects) == 1
    assert rejects[0]["round"] == 1
    assert rejects[0]["max_rounds"] == 3
    assert rejects[0]["to"] == "implementing"          # the before-key, not the stage id
    assert "no negative-path test" in rejects[0]["note"]


def test_both_gate_paths_emit(tmp_path):
    """Two call sites reach the SAME end state — a PR open, the human column handed
    over, the engine stopped. One advances (`res.dispatched`), the other short-cuts
    an already-open PR (`res.skipped`). A record that only knew the first would show
    a run that simply stops, with no gate row, on every re-tick of a finished item.
    """
    engine_a, board_a, _ = _engine(
        tmp_path / "a", [BoardItem(id="A", title="x", status="Doing", pipeline="verifying")]
    )
    engine_a.recorder = SpyRecorder()
    engine_a.tick()

    engine_b, board_b, runner_b = _engine(
        tmp_path / "b",
        [BoardItem(id="B", title="x", status="Doing", pipeline="verifying")],
        prs=["B"],
    )
    engine_b.recorder = SpyRecorder()
    res_b = engine_b.tick()

    advance = engine_a.recorder.of("gate")
    assert len(advance) == 1
    assert not advance[0].get("skipped")
    assert board_a.pipeline_of("A") == "pr-open"

    idempotent = engine_b.recorder.of("gate")
    assert len(idempotent) == 1
    assert idempotent[0]["skipped"] is True
    assert runner_b.pr_create_calls == 0        # no second PR
    assert "B" in res_b.skipped
    assert board_b.pipeline_of("B") == "pr-open"


def test_gate_stage_does_not_also_emit_a_stage_pass(tmp_path):
    """One transition, one row. `gate` already says `pass → pr-open`; a `stage` row
    beside it would report the PR stage twice in the sticky."""
    engine, _, _ = _engine(
        tmp_path, [BoardItem(id="A", title="x", status="Doing", pipeline="verifying")]
    )
    engine.recorder = SpyRecorder()

    engine.tick()

    assert len(engine.recorder.of("gate")) == 1
    assert engine.recorder.of("stage") == []


def test_gate_passes_the_pr_url_from_the_stage_notes(tmp_path):
    """pr.sh echoes ONLY the PR URL to stdout, captured as result.notes. The gate
    hook must lift it and pass `pr=<url>` so the record's own row LINKS the PR —
    otherwise the reader is left to hunt the Development panel. The advancing gate
    (the common path) has the pr stage's result in scope; this is where it happens.
    """
    url = "https://github.com/bks-lab/open-bridge/pull/118"

    def run(stage, item):
        if stage.id == "pr":
            return StageResult(ok=True, pr_opened=True, notes=f"[pr] diag to stderr\n{url}")
        return StageResult(ok=True)

    engine, board, runner = _engine(
        tmp_path, [BoardItem(id="A", title="x", status="Doing", pipeline="verifying")]
    )
    runner.run = run
    engine.recorder = SpyRecorder()

    engine.tick()

    gate = engine.recorder.of("gate")
    assert len(gate) == 1
    assert gate[0].get("pr") == url, "only the http line is lifted, never raw notes"


def test_gate_pr_url_reaches_the_rendered_sticky(tmp_path):
    """End-to-end against the real Recorder: the URL the run opened is IN the one
    sticky the issue shows — the fix's whole point."""
    url = "https://github.com/bks-lab/open-bridge/pull/118"

    def run(stage, item):
        if stage.id == "pr":
            board.open_pr(item.id)
            return StageResult(ok=True, pr_opened=True, notes=url)
        return StageResult(ok=True)

    engine, board, runner = _engine(
        tmp_path,
        [BoardItem(id="A", title="x", status="Doing", pipeline="verifying", issue_number=114)],
        record=RecordConfig(enabled=True),
    )
    runner.run = run

    engine.tick()

    comments = board.comments_of("A")
    assert len(comments) == 1
    body = comments[0]["text"]
    assert url in body and "pr-open" in body and "**STOP**" in body


def test_gate_notes_without_a_url_adds_no_pr_text(tmp_path):
    """result.notes on other paths carries argv+stderr of a crashed subprocess. The
    gate reaches ok=True only, but the http-only lift is what keeps a non-URL note
    (or an accidental future stdout change) out of the public row."""
    def run(stage, item):
        if stage.id == "pr":
            return StageResult(ok=True, pr_opened=True, notes="gh: something inert happened")
        return StageResult(ok=True)

    engine, board, runner = _engine(
        tmp_path, [BoardItem(id="A", title="x", status="Doing", pipeline="verifying")]
    )
    runner.run = run
    engine.recorder = SpyRecorder()

    engine.tick()

    gate = engine.recorder.of("gate")
    assert len(gate) == 1
    assert not gate[0].get("pr"), "a note with no http line must not reach the row"


# === park: the reason is the engine's own words ============================


def test_park_reason_is_engine_authored_not_res_notes(tmp_path):
    """`res.notes` carries `{e!r}` of a GhCliError — which embeds argv AND stderr.

    On a public repo that republishes the worker's stderr and, with it, whatever a
    token-bearing command printed when it failed. The ledger is the channel for
    that (launchd, local); the record is a channel to the world. `result.notes` is
    no better: it is the crashed subprocess's own output.
    """
    poison = "GhCliError(argv=['gh', '-H', 'Authorization: token ghp_AAAABBBBCCCCDDDDEEEE'])"  # pragma: allowlist secret
    engine, board, runner = _engine(
        tmp_path, [BoardItem(id="A", title="x", status="Doing", pipeline="implementing")]
    )
    runner.run = lambda stage, item: StageResult(ok=False, notes=poison)
    engine.recorder = SpyRecorder()

    res = engine.tick()

    parks = engine.recorder.of("park")
    assert len(parks) == 1
    reason = parks[0]["reason"]
    assert "ghp_" not in reason
    assert "Authorization" not in reason
    assert "implement" in reason and "failed" in reason   # the engine's own words
    assert parks[0]["stage"] == "implement"
    assert poison in res.notes    # the detail survives — in the LOCAL ledger only


def test_arm_park_records_no_stage(tmp_path):
    """At the ARM-time park sites no stage is resolved. Borrowing the first stage's
    id would be invention in a row whose whole job is attribution."""
    bad = "A; rm -rf ~"
    engine, board, _ = _engine(tmp_path, [BoardItem(id=bad, title="bad", status="Todo")])
    engine.recorder = SpyRecorder()

    engine.tick()

    parks = engine.recorder.of("park")
    assert len(parks) == 1
    assert parks[0]["stage"] is None
    assert "invalid item id" in parks[0]["reason"]


def test_every_park_site_records(tmp_path):
    """Eight sites park; eight sites must record. A site that writes `parked` without
    a row makes the sticky read as a run that simply stopped mid-stage."""
    engine, board, runner = _engine(
        tmp_path,
        [BoardItem(id="A", title="x", status="Doing", pipeline="verifying")],
        stages=_reject_pipeline(),
        max_rounds=1,
    )
    engine.runner = FakeStageRunner(
        board=board, reject_stage="review", reject_to="implement", reject_rounds=5
    )
    engine.recorder = SpyRecorder()

    engine.tick()   # review rejects, round 1 == cap → park

    parks = engine.recorder.of("park")
    assert len(parks) == 1
    assert parks[0]["stage"] == "review"
    assert "rounds exhausted" in parks[0]["reason"]
    assert board.pipeline_of("A") == "parked"


# === the record is off by default ==========================================


def test_disabled_record_emits_nothing(tmp_path):
    """`record.enabled: False` is the default and must be today's engine exactly —
    no comment, no edit, on any event."""
    engine, board, _ = _engine(
        tmp_path, [BoardItem(id="A", title="x", status="Todo")], working_status="In Progress"
    )

    for _ in range(6):
        engine.tick()

    assert board.pipeline_of("A") == "pr-open"
    assert board.comments_of("A") == []


def test_enabled_record_opens_one_sticky_and_edits_it(tmp_path):
    """Wired end-to-end against the real Recorder + the real board port.

    Edits never re-notify; a new comment mails every subscriber. That asymmetry is
    the entire cost model, so "one comment per run" is a property worth pinning.
    """
    engine, board, _ = _engine(
        tmp_path,
        [BoardItem(id="A", title="x", status="Todo", issue_number=114)],
        working_status="In Progress",
        record=RecordConfig(enabled=True),
    )

    for _ in range(6):
        engine.tick()

    comments = board.comments_of("A")
    assert len(comments) == 1                       # ONE notification for the whole run
    body = comments[0]["text"]
    assert body.startswith("<!-- board-pilot:run item=A -->")
    assert "armed" in body and "pr-open" in body
    assert "**STOP**" in body


def test_record_never_reports_a_token_count(tmp_path):
    """`tokens` is hardcoded to 0 on both real paths and sits one attribute access
    away in every hook's scope. Printing it reads as "this run was free"."""
    engine, board, _ = _engine(
        tmp_path,
        [BoardItem(id="A", title="x", status="Todo", issue_number=114)],
        record=RecordConfig(enabled=True),
    )

    for _ in range(6):
        engine.tick()

    body = board.comments_of("A")[0]["text"]
    assert "token" not in body.lower().split("### not recorded here")[0]


# === tick.py's reject comment — the third unscanned channel =================


def test_reject_note_is_scrubbed_before_posting(tmp_path):
    """Raw reviewer LLM output, posted verbatim to a world-readable repo.

    `_NOTE_PROMPT_CAP` bounds what the PROMPT asks a stage to read — never what the
    engine posts. Nothing scanned this channel before.
    """
    secret = "ghp_AAAABBBBCCCCDDDDEEEEFFFFGGGG1234"  # pragma: allowlist secret
    engine, board, _ = _engine(
        tmp_path,
        [BoardItem(id="A", title="x", status="Doing", pipeline="verifying")],
        stages=_reject_pipeline(),
        max_rounds=3,
    )
    engine.runner = FakeStageRunner(
        board=board,
        reject_stage="review",
        reject_to="implement",
        annotation=f"drop the token {secret} from the header",
    )

    engine.tick()

    body = board.comments_of("A")[-1]["text"]
    assert secret not in body
    assert "[redacted:secret]" in body
    assert "drop the token" in body and "from the header" in body   # per-SPAN, not a stub


def test_reject_note_scan_never_blocks_the_latch(tmp_path):
    """Redact-and-post, never refuse-to-post.

    Refusing would leave the item with `bounces > 0` and no note — which the
    blind-rework guard then parks. A false-positive match would cost a whole run.
    Termination is decoupled from the comment: the counter and the latch land
    first, and the comment is best-effort after them.
    """
    engine, board, runner = _engine(
        tmp_path,
        [BoardItem(id="A", title="x", status="Doing", pipeline="verifying")],
        stages=_reject_pipeline(),
        max_rounds=3,
    )
    engine.runner = FakeStageRunner(
        board=board,
        reject_stage="review",
        reject_to="implement",
        annotation="ghp_AAAABBBBCCCCDDDDEEEEFFFFGGGG1234",   # ENTIRELY a secret  # pragma: allowlist secret
    )

    res = engine.tick()

    assert board.pipeline_of("A") == "implementing"   # the latch landed
    assert board.bounces_of("A") == 1                 # the round counted
    assert "A" in res.rejected
    assert board.comments_of("A")                     # and the note was still posted


def test_benign_reject_note_passes_through_unchanged(tmp_path):
    """The negative path. A gate that redacts everything is not a gate — it is a
    blindfold, and `Bounces` climbs behind it while the producer reworks against
    nothing."""
    note = "no negative-path test for scrub(); add one that asserts (text, []) for a clean body"
    engine, board, _ = _engine(
        tmp_path,
        [BoardItem(id="A", title="x", status="Doing", pipeline="verifying")],
        stages=_reject_pipeline(),
        max_rounds=3,
    )
    engine.runner = FakeStageRunner(
        board=board, reject_stage="review", reject_to="implement", annotation=note
    )

    engine.tick()

    body = board.comments_of("A")[-1]["text"]
    assert body.endswith(note)                # byte-identical
    assert "redacted" not in body
    assert engine.runner.last_annotation_for("implement") is None   # not re-run yet


def test_reject_note_scan_honours_the_off_knob(tmp_path):
    """`record.scan: off` is a deliberate, documented opt-out — and a private-repo
    operator has a real reason for it: a redaction the producer cannot read is
    feedback it cannot act on. Hiding an unswitchable scrub behind a switch that
    says `off` is the same config-lies-about-code drift this layer exists to kill.
    """
    secret = "ghp_AAAABBBBCCCCDDDDEEEEFFFFGGGG1234"  # pragma: allowlist secret
    engine, board, _ = _engine(
        tmp_path,
        [BoardItem(id="A", title="x", status="Doing", pipeline="verifying")],
        stages=_reject_pipeline(),
        max_rounds=3,
        record=RecordConfig(scan="off"),
    )
    engine.runner = FakeStageRunner(
        board=board, reject_stage="review", reject_to="implement", annotation=secret
    )

    engine.tick()

    assert secret in board.comments_of("A")[-1]["text"]
