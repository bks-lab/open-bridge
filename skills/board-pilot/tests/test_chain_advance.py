"""The chained mode: several stages in ONE call, and every reason it must stop.

Today one invocation is exactly one tick, so an armed item needs one wake-up per
stage and a five-stage chain waits four full timer intervals doing nothing. This
file measures the flag that closes that gap (`--max-stages N`) — but the flag is
the small half. The load-bearing half is where it STOPS, because a loop around a
board API with no terminator is exactly how a rate limit gets burned:

  K1  an armed item runs several stages in ONE call;
  K2  at the human gate the call halts and starts NOTHING else;
  K3  a parked item halts;
  K4  the cap ends the call with work still in flight;
  K5  an UNARMED card is never armed by the chain — the whole point of the gate;
  K5c the control for K5: the same card, the same config, the PLAIN invocation,
      which DOES arm it. Without this, K5 would pass against a board that simply
      cannot arm and would measure nothing;
  K6  without the flag the CLI prints the same bytes it always printed;
  K7  a rejected item halts;
  K8  the ticks are spaced, so a failing chain cannot hammer the API;
  K9  the two argv shapes that must be refused rather than guessed at.

The tests drive the REAL `cli.run()` over the in-memory board and the scripted
runner, because the CLI is where the flag lives and the engine is where arming
lives: a test that called `Engine.tick()` directly would prove nothing about the
seam between them, which is the layer the defect would appear in.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from engine import cli
from engine.board import FakeBoardClient
from engine.interfaces import BoardItem
from engine.runner import FakeStageRunner

yaml = pytest.importorskip("yaml")


TRIGGER = "Ready for AI Development"   # the human-owned arming column
WORKING = "In AI Development"

_CHAIN = [
    {"name": "spec", "run": "cmd:true", "on_success": "implementing"},
    {"name": "implement", "run": "cmd:true", "on_success": "verifying"},
    {"name": "verify", "run": "cmd:true", "on_success": "reviewing"},
    {"name": "review", "run": "cmd:true", "on_success": "pr-ready"},
    {"name": "pr", "run": "cmd:gh pr create --draft", "on_success": "pr-open", "gate": "human"},
]


def _reject_chain() -> list:
    """The same chain, but `review` can send an item back to `implement`."""
    chain = [dict(s) for s in _CHAIN]
    chain[3] = dict(chain[3], on_reject={"to": "implement"})
    return chain


def _project(tmp_path, *, stages=None, **pipeline_over):
    data = {
        "board": {"owner": "acme", "project_number": 1, "repo": "acme/widget"},
        "pipeline": {
            "project": "chain",
            "trigger": {"on_status": TRIGGER},
            "working_status": WORKING,
            "park_status": "Blocked",
            "pr_status": "In Review",
            "concurrency": 1,
            "stages": stages or _CHAIN,
        },
    }
    data["pipeline"].update(pipeline_over)
    path = tmp_path / "project.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


@dataclass
class _Run:
    board: FakeBoardClient
    runner: FakeStageRunner
    lines: list      # the parsed one-line-per-tick ledger
    raw: list        # the same lines, unparsed — K6 compares BYTES
    rc: int


def _run(tmp_path, monkeypatch, capsys, *, items, argv, prs=None, stages=None,
         runner_kwargs=None, **pipeline_over) -> _Run:
    board = FakeBoardClient(items=items, prs=prs)
    runner = FakeStageRunner(board=board, **(runner_kwargs or {}))
    # cli imports both adapters INSIDE run(), so the module attribute is the seam.
    monkeypatch.setattr("engine.gh_board.GhBoardClient", lambda **kw: board)
    monkeypatch.setattr("engine.claude_runner.ClaudeStageRunner", lambda **kw: runner)
    project = _project(tmp_path, stages=stages, **pipeline_over)
    full = ["--project", str(project), "--state-dir", str(tmp_path / "state"), *argv]
    capsys.readouterr()
    try:
        rc = cli.run(full)
    except SystemExit as e:
        # argparse rejects an unknown flag by exiting, which would report as an
        # opaque SystemExit. Name what actually happened instead.
        raise AssertionError(
            f"cli.run refused {argv!r}: SystemExit({e.code}) — the chained mode is missing"
        ) from None
    raw = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    return _Run(board=board, runner=runner, lines=[json.loads(ln) for ln in raw], raw=raw, rc=rc)


# --- K1 ------------------------------------------------------------------
def test_k1_armed_item_runs_the_whole_chain_in_one_call(tmp_path, monkeypatch, capsys):
    """One invocation, five stages. Today this takes five wake-ups."""
    run = _run(
        tmp_path, monkeypatch, capsys,
        items=[BoardItem(id="A", title="x", status=WORKING, pipeline="queued")],
        argv=["--max-stages", "6", "--tick-pause", "0"],
    )

    assert run.rc == 0
    assert run.runner.ran_stage_ids == ["spec", "implement", "verify", "review", "pr"]
    assert run.board.pipeline_of("A") == "pr-open"
    assert run.board.status_of("A") == "In Review"
    # the ledger keeps one line per tick — the property the launchd log relies on
    assert [ln["tick"] for ln in run.lines] == [1, 2, 3, 4, 5]
    assert run.lines[-1]["stop"] == "gate"
    assert all(ln["stop"] is None for ln in run.lines[:-1])
    assert all(ln["armed"] == [] for ln in run.lines), "the chain armed something"


# --- K2 ------------------------------------------------------------------
def test_k2_human_gate_halts_the_call_and_starts_nothing_else(tmp_path, monkeypatch, capsys):
    """The gate is a HALT, not merely 'this item has no next stage'.

    B is armed and waiting behind `concurrency: 1`. A reaches the gate on tick 1.
    A loop that only stopped on 'nothing moved' would happily spend the remaining
    four ticks starting B — turning one human release into two running items.
    """
    run = _run(
        tmp_path, monkeypatch, capsys,
        items=[
            BoardItem(id="A", title="a", status=WORKING, pipeline="pr-ready"),
            BoardItem(id="B", title="b", status=WORKING, pipeline="queued"),
        ],
        argv=["--max-stages", "5", "--tick-pause", "0"],
    )

    assert run.runner.ran_stage_ids == ["pr"]
    assert run.board.pipeline_of("A") == "pr-open"
    assert run.board.pipeline_of("B") == "queued", "B was started after the gate"
    assert len(run.lines) == 1
    assert run.lines[0]["stop"] == "gate"


def test_k2b_gate_reached_without_dispatching_also_halts(tmp_path, monkeypatch, capsys):
    """The gate has TWO sites, and the second one is the dangerous one.

    A crash between opening the PR and writing the board leaves an item at the PR
    stage with the PR already open. The engine then hands the column over WITHOUT
    dispatching — so that item consumes no concurrency slot, B is dispatched in
    the very same tick, and a chain that read 'did anything move?' would see B
    moving and keep going. The gate is a gate whichever site reaches it.
    """
    run = _run(
        tmp_path, monkeypatch, capsys,
        items=[
            BoardItem(id="A", title="a", status=WORKING, pipeline="pr-ready"),
            BoardItem(id="B", title="b", status=WORKING, pipeline="queued"),
        ],
        prs={"A"},
        argv=["--max-stages", "5", "--tick-pause", "0"],
    )

    assert run.runner.pr_create_calls == 0            # never opens a second PR
    assert run.board.pipeline_of("A") == "pr-open"
    assert run.runner.ran_stage_ids == ["spec"], "the chain ran on past the gate"
    assert len(run.lines) == 1
    assert run.lines[0]["stop"] == "gate"


# --- K3 ------------------------------------------------------------------
def test_k3_parked_item_halts(tmp_path, monkeypatch, capsys):
    run = _run(
        tmp_path, monkeypatch, capsys,
        items=[BoardItem(id="A", title="x", status=WORKING, pipeline="queued")],
        argv=["--max-stages", "5", "--tick-pause", "0"],
        runner_kwargs={"fail_stage": "implement"},
    )

    assert run.runner.ran_stage_ids == ["spec", "implement"]
    assert str(run.board.pipeline_of("A")).startswith("parked")
    assert run.board.status_of("A") == "Blocked"
    assert len(run.lines) == 2, "the call kept ticking after the park"
    assert run.lines[-1]["stop"] == "parked"


# --- K4 ------------------------------------------------------------------
def test_k4_cap_ends_the_call_with_work_still_in_flight(tmp_path, monkeypatch, capsys):
    """The cap must bite while there is still work — otherwise 'idle' would be
    doing the stopping and the cap would be decorative."""
    run = _run(
        tmp_path, monkeypatch, capsys,
        items=[BoardItem(id="A", title="x", status=WORKING, pipeline="queued")],
        argv=["--max-stages", "2", "--tick-pause", "0"],
    )

    assert run.runner.ran_stage_ids == ["spec", "implement"]
    assert run.board.pipeline_of("A") == "verifying"    # in flight, three stages short
    assert len(run.lines) == 2
    assert run.lines[-1]["stop"] == "max_stages"


# --- K5 ------------------------------------------------------------------
def test_k5_the_chain_never_arms(tmp_path, monkeypatch, capsys):
    """THE assertion of this whole change.

    Arming is the human's act: a person drags the card into the trigger column
    and the NEXT plain tick latches it. The chained mode advances what is already
    armed and nothing else — so a card that falls into the trigger column while a
    chain is running is not swept up by it, and one release stays one release.
    """
    run = _run(
        tmp_path, monkeypatch, capsys,
        items=[BoardItem(id="A", title="x", status=TRIGGER)],   # pipeline is None
        argv=["--max-stages", "5", "--tick-pause", "0"],
    )

    assert run.board.pipeline_of("A") is None, "the chain armed an unarmed card"
    assert run.board.status_of("A") == TRIGGER, "the chain wrote the human column"
    assert run.runner.total_calls == 0
    assert len(run.lines) == 1
    assert run.lines[0]["armed"] == []
    assert run.lines[0]["stop"] == "idle"


def test_k5c_control_the_plain_invocation_does_arm_the_same_card(tmp_path, monkeypatch, capsys):
    """The counter-proof for K5: same card, same config, no flag → armed.

    Without this, K5 would stay green against a board that cannot arm at all, a
    trigger value that never matches, or a runner that never runs — green for the
    wrong reason, and silent about it.
    """
    run = _run(
        tmp_path, monkeypatch, capsys,
        items=[BoardItem(id="A", title="x", status=TRIGGER)],
        argv=["--once"],
    )

    assert run.lines[0]["armed"] == ["A"]
    assert run.board.pipeline_of("A") == "implementing"   # armed AND advanced one stage
    assert run.board.status_of("A") == WORKING
    assert run.runner.ran_stage_ids == ["spec"]


# --- K6 ------------------------------------------------------------------
def test_k6_default_invocation_prints_the_same_bytes(tmp_path, monkeypatch, capsys):
    """No flag → one line, the exact nine keys, nothing added.

    Pinned as BYTES, not as a dict: the chained mode adds fields to the tick
    result and two keys to its own ledger line, and either could leak into the
    line every existing log reader (and every plist in the fleet) already parses.
    """
    run = _run(
        tmp_path, monkeypatch, capsys,
        items=[BoardItem(id="A", title="x", status=TRIGGER)],
        argv=["--once"],
    )

    assert run.raw == [
        '{"armed": ["A"], "dispatched": ["A"], "dry_run": false, "notes": "", '
        '"parked": [], "paused": false, "project": "chain", "rejected": [], "skipped": []}'
    ]


# --- K7 ------------------------------------------------------------------
def test_k7_rejected_item_halts(tmp_path, monkeypatch, capsys):
    """A reject is rework a human may want to see before more money is spent."""
    run = _run(
        tmp_path, monkeypatch, capsys,
        items=[BoardItem(id="A", title="x", status=WORKING, pipeline="queued")],
        argv=["--max-stages", "8", "--tick-pause", "0"],
        stages=_reject_chain(),
        runner_kwargs={"reject_stage": "review", "reject_rounds": 1, "reject_to": "implement"},
        rework={"max_rounds": 3, "bounce_field": "Bounces"},
    )

    assert run.runner.ran_stage_ids == ["spec", "implement", "verify", "review"]
    assert run.board.pipeline_of("A") == "implementing"   # sent back, not advanced
    assert run.board.bounces_of("A") == 1
    assert len(run.lines) == 4
    assert run.lines[-1]["stop"] == "rejected"


# --- K8 ------------------------------------------------------------------
def test_k8_ticks_are_spaced(tmp_path, monkeypatch, capsys):
    """A pause BETWEEN ticks, and none after the last one.

    Without it a chain that fails fast becomes a tight retry loop against the
    GitHub API — the shape that emptied the rate-limit bucket in the first place.
    """
    slept = []
    monkeypatch.setattr("time.sleep", lambda s: slept.append(s))

    run = _run(
        tmp_path, monkeypatch, capsys,
        items=[BoardItem(id="A", title="x", status=WORKING, pipeline="queued")],
        argv=["--max-stages", "3", "--tick-pause", "0.25"],
    )

    assert len(run.lines) == 3
    assert slept == [0.25, 0.25], "expected one pause between ticks and none after the last"


# --- K9 ------------------------------------------------------------------
def _refused(tmp_path, capsys, extra) -> str:
    """Run an argv that must be REFUSED; return the stderr that explains why.

    The stderr matters: "unrecognized arguments" is argparse saying the flag does
    not exist, which is the pre-change state and would let both tests below pass
    while measuring nothing.
    """
    project = _project(tmp_path)
    capsys.readouterr()
    with pytest.raises(SystemExit) as e:
        cli.run(["--project", str(project), "--state-dir", str(tmp_path / "s"), *extra])
    err = capsys.readouterr().err
    assert e.value.code == 2
    assert "unrecognized arguments" not in err, "the flag does not exist yet"
    return err


def test_k9_refuses_a_cap_below_one(tmp_path, capsys):
    """A cap of 0 or -1 is a typo, not an instruction. Refuse it loudly — the cap
    is the terminator, and a silently-corrected one is no terminator at all."""
    err = _refused(tmp_path, capsys, ["--max-stages", "0"])
    assert "--max-stages" in err


def test_k9_refuses_once_together_with_max_stages(tmp_path, capsys):
    """The two flags make opposite claims about how many ticks run. Refuse rather
    than silently letting one win — a plist that grew the new flag without losing
    `--once` would otherwise run a mode nobody chose."""
    err = _refused(tmp_path, capsys, ["--once", "--max-stages", "3"])
    assert "--once" in err


# --- K10 -----------------------------------------------------------------
def test_k10_paused_mid_chain_halts_and_names_the_kill_file(tmp_path, monkeypatch, capsys):
    """`touch PAUSED` stops a chain that is ALREADY RUNNING, and the ledger says so.

    The chained mode is the one caller that can run beside the scheduled unit, so
    two engines end up sharing one state dir: the per-item lock protects the card,
    but prev.json, attempts.json and budget.json are common. PAUSED is the only
    handle that reaches both, and it works here only because the engine re-reads
    the file at the top of EVERY tick rather than once per process.

    What this measures is the STOP LABEL, and only that: the engine bails on its
    own either way, so no stage runs in tick 2 regardless. The label is the whole
    difference between "the operator's kill file took" and "the board ran out of work",
    and the second reading is the dangerous one, because it is what an operator
    concludes when a chain ends quietly with the card still mid-pipeline.
    """
    state = tmp_path / "state"

    def _pause_between_ticks(_seconds):
        state.mkdir(parents=True, exist_ok=True)
        (state / "PAUSED").touch()

    monkeypatch.setattr("time.sleep", _pause_between_ticks)

    run = _run(
        tmp_path, monkeypatch, capsys,
        items=[BoardItem(id="A", title="x", status=WORKING, pipeline="queued")],
        argv=["--max-stages", "5", "--tick-pause", "0.01"],
    )

    assert run.runner.ran_stage_ids == ["spec"], "a stage ran after the kill file appeared"
    assert run.board.pipeline_of("A") == "implementing"   # still in flight, four stages short
    assert len(run.lines) == 2
    assert run.lines[-1]["paused"] is True
    assert run.lines[-1]["stop"] == "paused", (
        "the ledger blamed something other than the kill file. An operator reads "
        "that as a finished board, not as a chain somebody stopped"
    )


# --- K11 -----------------------------------------------------------------
def test_k11_the_gate_wins_over_the_cap_on_the_last_allowed_tick(tmp_path, monkeypatch, capsys):
    """Both terminators are true at once; the ledger must name the human one.

    The item reaches the human gate on the very tick the cap allows last, so
    `gate` and `max_stages` both hold and the ORDER inside stop_reason decides
    which one is printed. No other test pins that order: K1 gates below its cap,
    K4 caps with nothing gated.

    The two readings are opposite instructions. `max_stages` means "run me again
    to continue", and running it again does nothing at all, because a gated item
    sits at the terminal pipeline value and drops out of in-flight, so the next
    call is an idle tick. `gate` means "the draft PR is open, your turn". Getting
    this backwards costs a re-typed command in front of an audience, at the one
    moment in the demo where a person is supposed to take over.
    """
    run = _run(
        tmp_path, monkeypatch, capsys,
        items=[BoardItem(id="A", title="x", status=WORKING, pipeline="pr-ready")],
        argv=["--max-stages", "1", "--tick-pause", "0"],
    )

    assert run.runner.ran_stage_ids == ["pr"]
    assert run.board.pipeline_of("A") == "pr-open"
    assert len(run.lines) == 1
    assert run.lines[0]["stop"] == "gate", (
        "the cap masked the human gate: the ledger tells the operator to re-run "
        "a chain that has nothing left to advance"
    )


# --- K12 -----------------------------------------------------------------
def test_k12_the_cap_bounds_the_loop_even_if_no_stop_reason_ever_fires(tmp_path, monkeypatch, capsys):
    """The cap is implemented TWICE, and K4 only measures one of them.

    `stop_reason` returns "max_stages", and the loop is additionally written as
    `range(1, N + 1)`. Either one alone terminates the call, so K4 stays green
    when the loop bound is replaced by an unbounded counter. Measured, not
    assumed. That leaves the more important half of the pair untested, and this
    is the one property of the whole chained mode that must not have a hole:
    every tick is a board read, and a loop against a board API with no
    terminator is precisely what emptied the rate-limit bucket on 2026-09-02.

    So: neutralise the stop logic entirely and assert the loop still ends after
    exactly N. The escape hatch at 20 exists so a REGRESSION fails as a loud
    assertion rather than hanging the suite forever, which is the failure mode
    that gets a test deleted instead of fixed.
    """
    seen = []

    def _never_stop(result, tick_no, max_ticks):
        seen.append(tick_no)
        return None if tick_no < 20 else "test-escape-hatch"

    monkeypatch.setattr(cli, "stop_reason", _never_stop)

    run = _run(
        tmp_path, monkeypatch, capsys,
        items=[BoardItem(id="A", title="x", status=WORKING, pipeline="queued")],
        argv=["--max-stages", "3", "--tick-pause", "0"],
    )

    assert seen == [1, 2, 3], (
        f"the loop ran {len(seen)} ticks with a cap of 3: the structural bound is gone, "
        "and only stop_reason was holding the call back"
    )
    assert len(run.lines) == 3
    assert run.rc == 0


# --- K13 -----------------------------------------------------------------
# The seam the confirmation page runs across. The page sets the human column and
# then calls the engine, so SOMETHING has to latch the card. Until now that was
# the scheduled 30-second unit — which is exactly the polling the trigger
# architecture removed. Without a way to say "arm once, then drive", pressing the
# button moves the column and the chain then finds nothing armed and stops idle:
# silent, exit 0, no card moved. `--arm-first` is that one arming sweep, and the
# assertion below is that it stays ONE.
def test_k13_arm_first_arms_on_the_opening_tick_and_then_drives(tmp_path, monkeypatch, capsys):
    """One release, one arming sweep, then the chain to the gate."""
    run = _run(
        tmp_path, monkeypatch, capsys,
        items=[BoardItem(id="A", title="x", status=TRIGGER)],   # pipeline is None
        argv=["--max-stages", "6", "--arm-first", "--tick-pause", "0"],
    )

    assert run.rc == 0
    assert run.lines[0]["armed"] == ["A"], "the opening tick did not arm"
    assert all(ln["armed"] == [] for ln in run.lines[1:]), \
        "a later tick armed something — one release must stay one release"
    assert run.runner.ran_stage_ids == ["spec", "implement", "verify", "review", "pr"]
    assert run.board.pipeline_of("A") == "pr-open"
    assert run.lines[-1]["stop"] == "gate"


def test_k13b_arm_first_without_the_cap_is_refused(tmp_path, capsys):
    """A flag that only means something in chained mode must not be ignorable.

    `--tick-pause` may sit unused in a plist harmlessly: it changes nothing. This
    one is a claim about arming, so a plain invocation that carries it would either
    arm (and match) or not (and lie). Refuse instead of guessing.
    """
    err = _refused(tmp_path, capsys, ["--once", "--arm-first"])
    assert "--arm-first" in err
