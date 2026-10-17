"""Between two cards a stage is silent for minutes, and silence reads as stalled.

The second run of the demo spent 7m03s inside `review` and 5m22s inside `spec`.
During those minutes the channel showed one card saying `running · dispatched, no
result yet`, and nothing else. A viewer three metres from a screen cannot tell
that from a hang, and the person who owns the run cannot either.

Two separate defects hide in that silence, and this sheet measures both.

THE FIRST is that a card never says WHERE IT IS. `Step 3 of 5` is a number, not a
story: it does not say that the tests already ran, nor that a pull request comes
next. Everything needed is already in the card's own arguments — `chain` and
`current` — so the fix invents no new plumbing and no second declaration of the
chain. That matters: the count already has exactly one source (`len(chain)`), and
a hand-written "previous stage" list would be a second one, wrong on the day
somebody inserts a stage.

THE SECOND is that a running stage has no way to say anything at all. The engine
learns what happened only when the child exits, because `_spawn` reads the pipe
once, at the end. A note channel fixes that: the child appends lines to a file it
is handed, a follower relays each new line as it appears, and the engine reports
it as a `note` event.

Three properties make the difference between a note channel and a liability, and
each has its own counter-test below:

  * a note is NOT a state change. It never reaches the ledger, never advances a
    stage, and a broken follower must not be able to fail a run that worked.
  * a note is UNTRUSTED TEXT. It is written by a stage, and a stage that runs a
    model can echo whatever the model produced, secrets included. It goes through
    the same scrub and the same clamp as every other cell.
  * a note that arrives after the child exits must still be delivered. Dropping
    the tail loses exactly the last line, which is the one that says how it ended.
"""
import pytest

from engine import card, notes, record


# === the journey line: where this card sits in the chain ===================

CHAIN = ("spec", "implement", "verify", "review", "pr")


def test_j1_the_line_names_the_previous_the_current_and_the_next_stage():
    line = card.journey(CHAIN, "review", card.DEFAULT_LABELS)
    assert "verify" in line, "the stage that just finished is not named"
    assert "review" in line
    assert "pr" in line, "the stage that comes next is not named"


def test_j2_the_first_stage_has_no_previous_and_says_so_by_omission():
    """Inventing a predecessor for the first stage would claim work that never
    happened. The line simply starts at `now`."""
    line = card.journey(CHAIN, "spec", card.DEFAULT_LABELS)
    assert "spec" in line
    assert "implement" in line
    assert "pr" not in line, "a stage two places away has no business on this card"


def test_j3_the_last_stage_has_no_next():
    line = card.journey(CHAIN, "pr", card.DEFAULT_LABELS)
    assert "review" in line and "pr" in line


def test_j4_a_stage_outside_the_chain_yields_no_line_instead_of_a_wrong_one():
    """At ARM no stage is resolved. A line built from an unresolved position would
    put the first stage's name on a card describing something that has not run."""
    assert card.journey(CHAIN, None, card.DEFAULT_LABELS) == ""
    assert card.journey(CHAIN, "nonexistent", card.DEFAULT_LABELS) == ""
    assert card.journey((), "spec", card.DEFAULT_LABELS) == ""


def test_j5_the_line_is_renamed_by_the_same_dictionary_as_every_other_word():
    """`say()` already renames engine-authored words per instance. The journey
    line is engine-authored, so it goes through the same door. A second renaming
    mechanism would be a second place to keep in sync."""
    words = {"verify": "tests ran", "review": "second opinion"}
    line = card.say(card.journey(CHAIN, "review", card.DEFAULT_LABELS), words)
    assert "tests ran" in line and "second opinion" in line
    assert "verify" not in line


def test_j6_the_card_carries_the_line(fake_item_fields):
    built = card.build_card(
        "stage", incident="INC-004", title="t", chain=CHAIN, current="review",
        fields=fake_item_fields)
    text = repr(built)
    assert "verify" in text and "pr" in text


# === the note event: a stage speaks while it runs ==========================


def test_n1_a_note_renders_as_its_own_text():
    got = record.outcome_text("note", _Item(), _Stage("review"), {"note": "read 4 files"})
    assert got == "read 4 files"


def test_n2_a_note_is_marked_as_the_agent_speaking_not_the_machine_deciding():
    """`kind` already separates a measured exit code from a model's words. A note
    is words. Labelling it `machine` would dress an opinion as a measurement."""
    row = record.row_fields("note", _Item(), _Stage("review"), None, {"note": "hm"})
    assert row["kind"] == "agent"
    assert row["took"] == "—", "a note has no duration; a blank one reads as instant"
    assert row["stage"] == "review"


def test_n3_a_note_is_scrubbed_and_clamped_like_every_other_cell():
    """THE SECURITY ASSERTION. A note is written by a stage that runs a model, so
    it is untrusted text on a path that ends in a channel and a comment."""
    lang = "x" * 5000
    row = record.row_fields("note", _Item(), _Stage("s"), None, {"note": lang})
    assert len(row["outcome"]) < 5000, "an unclamped note can blow the comment body"

    row = record.row_fields(
        "note", _Item(), _Stage("s"), None,
        {"note": "token ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa done"})
    assert "ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" not in row["outcome"]


def test_n4_note_is_a_known_event_everywhere_it_is_filtered():
    """A target declaring `events: [note]` must validate. An unknown event name is
    refused by config, which is right — and would silently drop every note."""
    from engine.config import EVENTS
    assert "note" in EVENTS


# === the follower: how a line gets out of a running child ==================
#
# COALESCING, added 03.09. after the third live run. The channel took 26 cards for
# one run, and several of them landed in the same second: `criteria read` and
# `planner started` are written microseconds apart, and the three notes of the
# `pr` stage inside fifteen seconds. The operator's words: they want to be told,
# but several inside one second make no sense — put them in one message.
#
# So the follower BUFFERS. It relays a burst once nothing new has arrived for
# `hold_s`, and it relays regardless after `max_hold_s`, because a stage that
# writes a line every four seconds would otherwise never flush and the channel
# would go quiet exactly when there is most to say.


def test_f1_lines_appended_while_the_child_runs_are_relayed(tmp_path):
    target = tmp_path / "notes"
    seen = []
    halt = {"stop": False}
    now = {"t": 0.0}

    def tick(_):
        now["t"] += 10.0          # past hold_s, so every burst flushes
        if len(seen) == 0:
            target.write_text("first\n", encoding="utf-8")
        elif len(seen) == 1:
            target.write_text("first\nsecond\n", encoding="utf-8")
        else:
            halt["stop"] = True

    notes.follow(target, seen.append, lambda: halt["stop"],
                 sleep=tick, poll_s=0, clock=lambda: now["t"])
    assert seen == [["first"], ["second"]]


def test_f2_a_missing_file_is_not_an_error(tmp_path):
    seen = []
    halt = {"n": 0}

    def tick(_):
        halt["n"] += 1

    notes.follow(tmp_path / "never", seen.append,
                 lambda: halt["n"] >= 2, sleep=tick, poll_s=0)
    assert seen == []


def test_f3_the_last_lines_are_read_after_the_child_exits(tmp_path):
    """THE ONE THAT MATTERS. A follower that sees its stop flag and returns has
    dropped whatever the child wrote in its final second, which is the line that
    says how the stage ended."""
    target = tmp_path / "notes"
    target.write_text("early\n", encoding="utf-8")
    seen = []

    def tick(_):
        target.write_text("early\nlast breath\n", encoding="utf-8")

    notes.follow(target, seen.append, lambda: True, sleep=tick, poll_s=0)
    flat = [z for b in seen for z in b]
    assert flat == ["early", "last breath"]


def test_f4_a_failing_receiver_never_stops_the_follower(tmp_path):
    """A note is an observation. A sink that throws while relaying one must not be
    able to take the run with it, and must not silence what comes after."""
    target = tmp_path / "notes"
    target.write_text("a\n", encoding="utf-8")
    seen = []

    def receive(lines):
        if lines == ["a"]:
            raise RuntimeError("channel down")
        seen.append(lines)

    # Only wait at first, so "a" goes out alone and fails on the way. Then "b"
    # arrives and must still get through.
    got = _script(tmp_path, receive, [("wait", 10.0), ("write", ["b"]),
                                      ("wait", 10.0)], target=target)
    assert seen == [["b"]], repr(seen)


def test_f5_blank_lines_and_absurd_lengths_do_not_reach_the_channel(tmp_path):
    target = tmp_path / "notes"
    target.write_text("\n   \n" + "y" * 3000 + "\nreal\n", encoding="utf-8")
    seen = []
    notes.follow(target, seen.append, lambda: True, sleep=lambda _: None, poll_s=0)
    flat = [z for b in seen for z in b]
    assert "real" in flat
    assert all(z.strip() for z in flat), "a blank note is a card with nothing on it"
    assert all(len(z) <= notes.MAX_LEN for z in flat)


# --- the coalescing itself -------------------------------------------------


def _script(tmp_path, receive, steps, *, target=None, **kw):
    """Drive the follower through a script of steps.

    A step is ("wait", seconds) OR ("write", [lines]), and the separation is the
    point: waiting and writing in the same step would mean the follower never SEES
    the pause, and then the probe measures the script, not the coalescing.
    """
    target = target or (tmp_path / "notes")
    content = []
    if target.exists():
        content = target.read_text(encoding="utf-8").splitlines()
    now = {"t": 0.0}
    rest = list(steps)

    def tick(_):
        if not rest:
            now["t"] += 1.0
            return
        kind, value = rest.pop(0)
        if kind == "wait":
            now["t"] += value
        else:
            content.extend(value)
            target.write_text("\n".join(content) + "\n", encoding="utf-8")

    notes.follow(target, receive, lambda: not rest, sleep=tick, poll_s=0,
                 clock=lambda: now["t"], **kw)
    return None


def _run(tmp_path, steps, **kw):
    seen = []
    _script(tmp_path, seen.append, steps, **kw)
    return seen


def test_c1_lines_written_at_the_same_moment_become_one_message(tmp_path):
    """`criteria read` and `planner started` are microseconds apart in spec.sh.
    They were two cards. They are one now."""
    got = _run(tmp_path, [("write", ["criteria read: spec.md", "planner started"]),
                           ("wait", 10.0)])
    assert got and got[0] == ["criteria read: spec.md", "planner started"], repr(got)
    assert len(got) == 1


def test_c2_a_line_far_later_is_its_own_message(tmp_path):
    """Coalescing must not become swallowing. Two minutes apart is two events."""
    got = _run(tmp_path, [("write", ["suite started"]), ("wait", 120.0),
                           ("write", ["suite green: 379 passed"]), ("wait", 120.0)])
    assert [b[0] for b in got] == ["suite started", "suite green: 379 passed"], repr(got)


def test_c3_a_steady_trickle_still_gets_flushed(tmp_path):
    """THE COUNTER-TEST TO THE WINDOW. A stage that writes a line every four
    seconds would never fall quiet, and a pure quiet-window would hold everything
    until the stage ends: the channel goes silent exactly when most happens."""
    steps = []
    for i in range(10):
        steps += [("write", [f"line {i}"]), ("wait", 4.0)]
    steps.append(("wait", 30.0))
    got = _run(tmp_path, steps, hold_s=5.0, max_hold_s=20.0)
    assert len(got) >= 2, "nothing was flushed while the trickle ran: " + repr(got)
    flat = [z for b in got for z in b]
    assert flat == [f"line {i}" for i in range(10)], "lines were lost: " + repr(flat)


def test_c4_nothing_is_lost_when_the_stage_ends_mid_window(tmp_path):
    """The tail must go out even when the quiet window has not elapsed."""
    target = tmp_path / "notes"
    target.write_text("pull request ready\n", encoding="utf-8")
    seen = []
    notes.follow(target, seen.append, lambda: True, sleep=lambda _: None,
                 poll_s=0, clock=lambda: 0.0)
    assert [z for b in seen for z in b] == ["pull request ready"]


# === the wiring: from a running child to the channel, and no further =======


class NotingRunner:
    """A stage that speaks twice while it works, then passes."""

    def __init__(self):
        self.on_note = None

    def run(self, stage, item):
        from engine.interfaces import StageResult
        if self.on_note:
            self.on_note(stage, item, "reading contract/severity.json")
            self.on_note(stage, item, "the rank matters, not the membership")
        return StageResult(ok=True, notes="", duration_s=1.0)


def _wired(tmp_path, reporters, runner):
    from engine.board import FakeBoardClient
    from engine.config import EngineConfig, RecordConfig
    from engine.interfaces import BoardItem, Stage
    from engine.tick import Engine
    board = FakeBoardClient(items=[BoardItem(id="A", title="t", status="Todo")])
    config = EngineConfig(
        stages=[Stage(id="spec", run="cmd:true", on_success="implementing")],
        trigger_status="Todo", record=RecordConfig(enabled=False))
    return Engine(config, board, runner, state_dir=tmp_path, reporters=reporters)


class Catcher:
    """A reporter double that remembers every event it was handed."""

    name = "channel"

    def __init__(self, boom=False):
        self.seen = []
        self.boom = boom

    def emit(self, event, item, *, stage=None, result=None, **fields):
        self.seen.append((event, fields.get("note")))
        if self.boom:
            raise RuntimeError("webhook failed (502)")

    def notes(self):
        return [n for e, n in self.seen if e == "note"]


def test_w1_a_note_reaches_the_channel_while_the_stage_is_still_running(tmp_path):
    fang = Catcher()
    motor = _wired(tmp_path, [fang], NotingRunner())
    motor.tick()

    assert fang.notes() == ["reading contract/severity.json",
                            "the rank matters, not the membership"]


def test_w2_a_note_never_reaches_the_ledger(tmp_path):
    """THE LINE THIS FEATURE MUST NOT CROSS. The sticky record is the ledger of
    state changes. A row per muttered sentence is no longer a ledger, and the
    board comment has a hard body cap that notes would eat."""
    fang = Catcher()
    motor = _wired(tmp_path, [fang], NotingRunner())
    schreiber = Catcher()
    motor.recorder = schreiber
    motor.tick()

    assert fang.notes(), "the channel saw no note at all, so this proves nothing"
    assert schreiber.notes() == [], "a note was written into the ledger"


def test_w3_a_broken_channel_on_a_note_does_not_fail_the_stage(tmp_path):
    """A note is an observation. A sink that throws while relaying one must not be
    able to turn a successful advance into a skip."""
    motor = _wired(tmp_path, [Catcher(boom=True)], NotingRunner())
    res = motor.tick()

    assert res.dispatched == ["A"], "the stage did not advance"
    assert res.skipped == []


def test_w4_a_runner_that_knows_nothing_of_notes_still_runs(tmp_path):
    """Every other instance of this engine has a runner that never calls back.
    Nothing may change for them."""
    from engine.runner import FakeStageRunner
    from engine.board import FakeBoardClient
    from engine.interfaces import BoardItem
    board = FakeBoardClient(items=[BoardItem(id="A", title="t", status="Todo")])
    fang = Catcher()
    motor = _wired(tmp_path, [fang], FakeStageRunner(board=board))
    res = motor.tick()

    assert res.dispatched == ["A"]
    assert fang.notes() == []


def test_r1_the_child_is_handed_a_path_and_what_it_writes_comes_back(tmp_path):
    """THE HALF THE DETERMINISTIC SUITE NORMALLY CANNOT SEE. `claude_runner` only
    runs against a real shell, so this one spawns one: a `cmd:` stage that appends
    to the path it was handed, and the line must arrive."""
    from engine.claude_runner import ClaudeStageRunner
    from engine.interfaces import BoardItem, Stage

    heard = []
    runner = ClaudeStageRunner(repo=str(tmp_path), branch_template="b/{item_id}",
                               project="p")
    runner.on_note = lambda stage, item, text: heard.append(text)
    stage_def = Stage(id="s", on_success="next",
                        run='cmd:bash -c echo\\ hello\\ >>\\ "$STAGE_NOTES"')
    result = runner.run(stage_def, BoardItem(id="A", title="t", status="Todo"))

    assert result.ok, "the stage itself failed: " + str(result.notes)
    assert heard == ["hello"], "what the child wrote never came back: " + repr(heard)


# === the collision the journey line walks straight into ====================


def test_j7_a_stage_name_never_leaks_into_the_outcome(fake_item_fields):
    """THE DEFECT THIS TEST WAS WRITTEN FOR, found while rendering a sample card.

    The obvious way to say "verify" in German is to add `verify: Tests` to the
    card's word dictionary. That dictionary is applied to the OUTCOME too, and the
    outcome carries the values that are really in the board column: `pass →
    pr-ready`, `pass → verifying`. `say()` replaces whole words and a hyphen is a
    word boundary, so `pr: Pull-Request` silently rewrote `pr-ready` into
    `Pull-Request-ready` — a card claiming a column value that does not exist.

    So stage names get their OWN mapping, applied only where a stage name is
    inserted, and the word dictionary keeps its hands off the pipeline values.
    """
    built = card.build_card(
        "stage", incident="INC-004", title="t", chain=CHAIN, current="review",
        fields={**fake_item_fields, "outcome": "pass → pr-ready"},
        names={"verify": "Tests", "review": "Zweitmeinung", "pr": "Pull-Request"},
        words={"pass": "passed"})
    blocks = [b["text"] for b in built["attachments"][0]["content"]["body"]
              if b.get("type") == "TextBlock"]

    assert any("Tests" in t and "Pull-Request" in t for t in blocks), \
        "the journey line did not use the stage names: " + repr(blocks)
    assert any(t == "passed → pr-ready" for t in blocks), \
        "the pipeline value was rewritten: " + repr(blocks)


def test_j8_without_a_name_a_stage_keeps_its_own(fake_item_fields):
    """A partial mapping is the normal case: an instance names the stages it cares
    about. An unmapped one must appear as itself, never blank."""
    line = card.journey(CHAIN, "review", card.DEFAULT_LABELS, names={"verify": "Tests"})
    assert "Tests" in line and "review" in line and "pr" in line
# --- doubles ---------------------------------------------------------------


class _Item:
    id = "PVTI_x"
    title = "t"
    status = "In AI Development"
    url = "https://example.invalid/1"


class _Stage:
    def __init__(self, sid):
        self.id = sid
        self.run = "cmd:true"
        self.criteria = None


@pytest.fixture
def fake_item_fields():
    return {"stage": "review", "kind": "machine", "criteria": "review.md@abc",
            "took": "7m03s", "outcome": "pass → pr-ready"}


