"""The evidence tee: the ENGINE writes the evidence, never the evaluated stage.

Why this file exists at all. Letting `$EVIDENCE_FILE` be written by the stage and
then labelling it "captured output, not a summary" is a lie an existence check
cannot catch: a stage that TYPES `5 passed in 0.15s` into the file passes exactly
like one that ran pytest. So the parent tees `proc.stdout` / `proc.stderr` /
`proc.returncode` — values it read from the pipe itself — into
`<evidence_dir>/<stage_id>/`. The output is unforgeable by the stage's text
because the stage never gets to author it.

These are pure/offline like the rest of the runner suite: they drive `python3`
argv, no `claude` binary, no network.
"""
import hashlib
import sys

from engine.claude_runner import ClaudeStageRunner
from engine.interfaces import BoardItem, Stage

# What a dishonest stage would like the record to say, and what really happened.
LIE = "5 passed in 0.15s"
TRUTH = "2 failed, 3 passed"


def _py(code: str) -> str:
    """A cmd: handler running inline python.

    Single-quoted for shlex, so `code` must contain no single quotes — inside them
    shlex does no escape processing, which is exactly why the argv stays literal.
    """
    return f"cmd:{sys.executable} -c '{code}'"


def _runner(tmp_path, **kw):
    return ClaudeStageRunner(
        repo="", branch_template="b/{item_id}", project="p",
        evidence_dir=str(tmp_path / "ev" / "{item_id}"), **kw
    )


# -- the key test ---------------------------------------------------------
def test_evidence_written_by_engine_not_stage(tmp_path):
    """A stage that writes a LIE into its own would-be evidence path is overruled.

    The discriminator: this stage claims success (`5 passed`, exit 0) in the file
    while really printing `2 failed` and exiting 1. An engine that merely CHECKS
    the file reports the lie; an engine that tees from the pipe reports the truth.
    """
    code = (
        "import os,sys; "
        'd=os.path.join(os.environ["EVIDENCE_DIR"], "verify"); '
        "os.makedirs(d, exist_ok=True); "
        'open(os.path.join(d,"stdout"),"w").write("' + LIE + '"); '
        'open(os.path.join(d,"exit_code"),"w").write("0"); '
        'sys.stdout.write("' + TRUTH + '"); '
        "sys.exit(1)"
    )
    r = _runner(tmp_path)
    item = BoardItem(id="A", title="t", status="Todo")
    stage = Stage(id="verify", run=_py(code), on_success="x", evidence=True)

    res = r.run(stage, item)

    stage_dir = tmp_path / "ev" / "A" / "verify"
    stdout = (stage_dir / "stdout").read_text()
    # The engine's read from the pipe replaced what the stage typed there.
    assert stdout == TRUTH
    assert LIE not in stdout
    # The exit code belongs to the engine, not to the stage's claim about it.
    assert (stage_dir / "exit_code").read_text().strip() == "1"
    assert res.ok is False
    assert res.evidence_dir == str(stage_dir)


def test_evidence_captures_stderr_on_success(tmp_path):
    """Today stderr is dropped on success and stdout on failure (claude_runner.py
    :211/:213). The sink keeps both on both paths — that loss is the whole reason
    real test output cannot ride `result.notes`."""
    code = (
        "import sys; "
        'sys.stdout.write("out"); sys.stderr.write("warn: deprecated"); '
        "sys.exit(0)"
    )
    r = _runner(tmp_path)
    item = BoardItem(id="A", title="t", status="Todo")
    stage = Stage(id="verify", run=_py(code), on_success="x", evidence=True)

    res = r.run(stage, item)

    stage_dir = tmp_path / "ev" / "A" / "verify"
    assert res.ok is True
    assert (stage_dir / "stdout").read_text() == "out"
    assert (stage_dir / "stderr").read_text() == "warn: deprecated"
    assert (stage_dir / "exit_code").read_text().strip() == "0"


def test_no_evidence_dir_when_stage_does_not_declare_evidence(tmp_path):
    """The negative control for the evidence gate: `evidence: true` is opt-in per
    stage, so a stage that never declared it is not an evidence source."""
    r = _runner(tmp_path)
    item = BoardItem(id="A", title="t", status="Todo")
    stage = Stage(id="implement", run=_py("pass"), on_success="x")  # evidence defaults False

    res = r.run(stage, item)

    assert res.ok is True
    assert res.evidence_dir is None
    assert not (tmp_path / "ev" / "A" / "implement").exists()


# -- duration -------------------------------------------------------------
def test_duration_is_recorded(tmp_path):
    """A retry is invisible without it: today the engine captures no timestamps at
    all (`grep -rE 'time\\.|monotonic|perf_counter' engine/` → only lock.py)."""
    r = _runner(tmp_path)
    item = BoardItem(id="A", title="t", status="Todo")
    stage = Stage(id="verify", run=_py("import time; time.sleep(0.05)"), on_success="x")

    res = r.run(stage, item)

    assert res.ok is True
    assert res.duration_s is not None
    assert res.duration_s >= 0.05          # it really wrapped the child
    assert res.duration_s < 60             # and it is a duration, not a wall-clock epoch


# -- env ------------------------------------------------------------------
def test_bounces_exported_to_stage_env(tmp_path):
    """Exported NOWHERE today — so no stage can state its own rework round, which
    is the one number the reject edge durably tracks."""
    r = _runner(tmp_path)
    item = BoardItem(id="A", title="t", status="Todo", bounces=2)
    assert r._item_env(item)["BOUNCES"] == "2"


def test_bounces_exported_as_zero_for_a_fresh_item(tmp_path):
    r = _runner(tmp_path)
    item = BoardItem(id="A", title="t", status="Todo")
    assert r._item_env(item)["BOUNCES"] == "0"


def test_evidence_dir_exported_is_the_item_dir_not_the_stage_dir(tmp_path):
    """The pr stage builds the dossier from EVERY prior stage's evidence, so the
    exported dir is the item's, and each stage tees into a `<stage_id>/` child."""
    r = _runner(tmp_path)
    item = BoardItem(id="A", title="t", status="Todo")
    assert r._item_env(item)["EVIDENCE_DIR"] == str(tmp_path / "ev" / "A")


# -- criteria -------------------------------------------------------------
def test_criteria_file_exported_and_ref_hashed_at_dispatch(tmp_path):
    """`criteria` is the tuning knob: the record must cite the standard that was
    APPLIED, so the ref is hashed at dispatch, not re-derived later from a file
    that may have moved on."""
    cdir = tmp_path / "criteria"
    cdir.mkdir()
    (cdir / "review.md").write_text("Reject if any public function lacks a test.\n")

    r = ClaudeStageRunner(
        repo="", branch_template="b/{item_id}", project="p", criteria_dir=str(cdir)
    )
    item = BoardItem(id="A", title="t", status="Todo")
    stage = Stage(
        id="review",
        run=_py('import os; assert open(os.environ["CRITERIA_FILE"]).read().startswith("Reject if")'),
        on_success="x",
        criteria="review.md",
    )

    res = r.run(stage, item)

    assert res.ok is True                       # the stage really read the file
    # The expected sha is computed HERE, independently of the engine's helper —
    # it is git's blob hash, so `git show <sha>` resolves the ref once the file is
    # committed, which is the documented tuning loop.
    content = b"Reject if any public function lacks a test.\n"
    blob = hashlib.sha1(b"blob %d\0" % len(content) + content).hexdigest()
    assert res.criteria_ref == f"review.md@{blob[:7]}"


def test_no_criteria_ref_when_stage_declares_none(tmp_path):
    r = ClaudeStageRunner(repo="", branch_template="b/{item_id}", project="p")
    item = BoardItem(id="A", title="t", status="Todo")
    stage = Stage(id="implement", run=_py("pass"), on_success="x")

    res = r.run(stage, item)

    assert res.criteria_ref is None
    assert "CRITERIA_FILE" not in r._item_env(item, stage)


def test_missing_criteria_file_fails_closed_without_spawning(tmp_path):
    """A stage that declares `criteria:` and finds no file would review against
    NOTHING — silently, which is the exact blindness the knob exists to remove.
    Refuse before the spawn: no LLM spend, and the notes name the path."""
    r = ClaudeStageRunner(
        repo="", branch_template="b/{item_id}", project="p", criteria_dir=str(tmp_path / "criteria")
    )
    item = BoardItem(id="A", title="t", status="Todo")
    stage = Stage(id="review", run=_py("pass"), on_success="x", criteria="absent.md")

    res = r.run(stage, item)

    assert res.ok is False
    assert "absent.md" in res.notes
    assert r.log == []                          # nothing was ever spawned


# -- the two gates stay separate ------------------------------------------
def _verdict_cmd():
    code = (
        "import os, json; "
        'open(os.environ["VERDICT_FILE"], "w").write('
        'json.dumps({"verdict": "reject", "annotation": "add a test"}))'
    )
    return f"cmd:{sys.executable} -c '{code}'"


def test_verdict_still_gated_when_stage_has_no_reject_edge(tmp_path):
    """Verdict is GATED, evidence is UNGATED — different files, different readers.

    Landing the evidence sink must not widen the verdict gate: only a stage
    declaring an on_reject edge has its sidecar consulted, else a producer that
    echoes a verdict could forge a spurious backward transition.
    """
    r = _runner(tmp_path)
    item = BoardItem(id="A", title="t", status="Todo")
    # evidence: true, but NO reject edge — and the command writes a verdict anyway.
    stage = Stage(id="verify", run=_verdict_cmd(), on_success="x", evidence=True)

    res = r.run(stage, item)

    assert res.ok is True
    assert res.verdict is None                                   # gate held
    assert (tmp_path / "ev" / "A" / "verify" / "exit_code").exists()   # sink ran anyway


def test_verdict_still_read_when_stage_declares_reject_edge(tmp_path):
    """The other half of the same gate — the evidence sink did not break it."""
    r = _runner(tmp_path)
    item = BoardItem(id="A", title="t", status="Todo")
    stage = Stage(
        id="review", run=_verdict_cmd(), on_success="x", reject_to="implement", evidence=True
    )

    res = r.run(stage, item)

    assert res.verdict == "reject"
    assert res.annotation == "add a test"


# -- the failure NOTE, which is a different stream question ----------------
# The tee above keeps BOTH streams for a stage that declares `evidence: true`.
# `result.notes` is the short line that reaches the board comment and the channel
# card, and it kept only stderr. On 2026-09-03 a stage failed with an empty stderr
# and its whole diagnosis on stdout, so the board read `rc=1` and nothing else.
def test_notes_fall_back_to_stdout_when_a_failing_stage_left_stderr_empty(tmp_path):
    """A failing child does not have to use stderr, and the claude CLI does not.

    The discriminator is that the message is on stdout ONLY: a note built from
    stderr alone passes an "is it non-empty" check identically and still says
    nothing.
    """
    runner = _runner(tmp_path)
    stage = Stage(id="s", run=_py("import sys; print(\"API Error: 529 Overloaded\"); sys.exit(1)"),
                  on_success="next")
    item = BoardItem(id="I1", title="t", url="u", status="s", pipeline="p")

    res = runner.run(stage, item)

    assert res.ok is False
    assert "529" in res.notes, (
        f"the diagnosis was dropped because it came on stdout: {res.notes!r}")


def test_notes_still_prefer_stderr_when_a_stage_writes_both(tmp_path):
    """The counter-test: stdout is a FALLBACK, not a second channel.

    A stage that logs progress to stdout and its error to stderr must not have the
    error pushed out of a 2000-char note by its own chatter.
    """
    runner = _runner(tmp_path)
    stage = Stage(
        id="s",
        run=_py("import sys; print(\"progress chatter\"); "
                "sys.stderr.write(\"the real reason\"); sys.exit(3)"),
        on_success="next")
    item = BoardItem(id="I1", title="t", url="u", status="s", pipeline="p")

    res = runner.run(stage, item)

    assert res.ok is False
    assert "rc=3" in res.notes and "the real reason" in res.notes
    assert "progress chatter" not in res.notes, (
        "stdout crowded into a note that already had the reason")
