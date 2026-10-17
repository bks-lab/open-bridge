"""The engine — one poll = one `tick()`.

Per tick (cheap, no LLM in the loop itself):
  1. bail if PAUSED or the token ceiling is reached;
  2. ARM: every item sitting in the trigger column with no pipeline yet gets
     pipeline = "queued" (the board pipeline field is the durable marker, so a
     wiped snapshot can never re-arm an in-flight item);
  3. advance each in-flight item by exactly ONE stage (confirmed-advance: the next
     tick re-reads the board), under a per-item lock, up to `concurrency`;
  4. the gated PR stage opens a PR at most once (idempotent), sets the human
     status to `pr_status`, and STOPS — the engine NEVER sets `done_status`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from . import snapshot
from .guards import AttemptCounter, TokenBudget, is_paused, valid_item_id
from .interfaces import reject_comment
from .lock import Lock
from .record import Recorder, emit_guarded
from .report import build_reporters
from .scan import scrub

# Last-resort cap for the rewind edge. `validate_chain` demands a positive
# max_rounds for a REJECT edge but says nothing about a rewind edge, so a config
# that declares one without any rework budget loads silently — and then spends
# without bound. This default is what stands between a forgotten YAML key and an
# open-ended bill; it is deliberately not configurable-to-None.
_DEFAULT_BACKWARD_ROUNDS = 3


def _is_transient_board_error(exc) -> bool:
    """True only when the error POSITIVELY claims it clears on its own.

    Duck-typed (`exc.is_transient()`), never an isinstance against GhCliError:
    the engine core must not import the build-stage gh adapter (cli.py treats
    it as optional and would lose its friendly missing-adapter message), and
    the in-memory Fake raises plain exceptions. Anything without the method —
    or answering False — is permanent, so unknown shapes stay loud (fail-closed).
    """
    probe = getattr(exc, "is_transient", None)
    return bool(probe()) if callable(probe) else False


def _http_line(text: str) -> str:
    """The LAST line of a stage's stdout that begins an http(s) URL, else "".

    pr.sh writes ONLY the PR URL to stdout (its diagnostics go to stderr), captured
    as `result.notes`. This is the safe lift of that URL. Raw `result.notes` is never
    surfaced onto the board — on a crashed subprocess it embeds argv + stderr and
    could republish a token (transparency.md §7) — so only a line that IS a URL is
    taken, and even a future stdout change cannot leak an argv line through this.
    """
    for line in reversed((text or "").splitlines()):
        stripped = line.strip()
        if stripped.startswith(("https://", "http://")):
            return stripped
    return ""


@dataclass
class TickResult:
    armed: list = field(default_factory=list)
    dispatched: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    parked: list = field(default_factory=list)
    rejected: list = field(default_factory=list)
    # Items that reached the HUMAN GATE this tick — the draft PR is open and the
    # engine has stopped on purpose. Both gate sites report here: the advancing
    # one (in `dispatched`) and the PR-idempotency one (in `skipped`), which is
    # exactly why neither of those two lists can stand in for this one. A caller
    # chaining ticks needs to tell "stopped at the gate" from "still working",
    # and the only other way to learn it is another board read.
    gated: list = field(default_factory=list)
    paused: bool = False
    notes: str = ""


class Engine:
    def __init__(self, config, board, runner, state_dir, paused_file=None, reporters=None,
                 report_send=False):
        self.cfg = config
        self.board = board
        self.runner = runner
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.prev_path = self.state_dir / "prev.json"
        self.lockdir = self.state_dir / "locks"
        self.paused_file = Path(paused_file) if paused_file else (self.state_dir / "PAUSED")
        self.budget = TokenBudget(ceiling=config.token_ceiling, state_file=self.state_dir / "budget.json")
        # durable per-(item,stage) retry attempt counter (distinct from the board
        # bounce counter used by the reject edge)
        self.attempts = AttemptCounter(state_file=self.state_dir / "attempts.json")

        # pipeline state BEFORE stage[i] → stage[i].  Initial armed state is "queued".
        # Also build the reverse map stage-id → before-key, so a reject edge can
        # name a STAGE-ID and the engine resolves it to the pipeline value to set.
        self._stage_by_before: dict = {}
        self._before_by_stage_id: dict = {}
        before = "queued"
        for s in config.stages:
            self._stage_by_before[before] = s
            self._before_by_stage_id[s.id] = before
            before = s.on_success
        self._terminal = config.stages[-1].on_success if config.stages else "pr-open"
        self._has_reject_edge = any(getattr(s, "reject_to", None) for s in config.stages)
        self._has_rewind_edge = any(
            s.on_fail == "rewind" and getattr(s, "rewind_to", None) for s in config.stages
        )
        # BOTH backward edges spend the same durable per-item rework budget, so both
        # need the board Number field to exist and both need it zeroed at ARM. Keying
        # this off the reject edge alone left a rewind-only config with no preflight
        # and no terminator at all — the one shape that spends without bound.
        self._has_backward_edge = self._has_reject_edge or self._has_rewind_edge

        # Backward-edge preflight (fail-closed at startup): the durable bounce Number
        # field is the ONLY per-item terminator for a backward edge. If the operator
        # never hand-added it to the board, set_number would KeyError inside the
        # dispatch loop forever (swallowed → skip-and-retry → costly stage re-runs
        # every poll, unbounded spend). Verify ONCE that the field exists and raise
        # loudly if absent. Duck-typed so the in-memory Fake (no live board) is a
        # no-op; only the real GhBoardClient performs the field-list check.
        if self._has_backward_edge:
            preflight = getattr(self.board, "preflight_reject_field", None)
            if callable(preflight):
                preflight(self.cfg.bounce_field)

        # Option preflight (fail-closed at startup): `_option_id` KeyErrors on any
        # value the board does not carry as a live option, and that raise lands inside
        # the dispatch loop where the outer guard swallows it into a skip — so the item
        # never advances and the expensive stage re-dispatches on every poll, forever.
        # Board options cannot be created from YAML (a human adds them by hand), which
        # makes a missing option the EXPECTED first-run state, not an exotic one. One
        # field-list read here turns that silent burn into a startup error naming the
        # field and the value. Duck-typed like the preflight above: the in-memory Fake
        # has no live board to check against.
        preflight_options = getattr(self.board, "preflight_options", None)
        if callable(preflight_options):
            preflight_options(self._writable_pipeline_values(), self._writable_status_values())

        # Built even when the record is DISABLED, on purpose: the constructor validates
        # `sticky_marker`, and a marker that renders as a reject note turns every record
        # row into forged feedback for the autonomous producer. config.validate_transparency
        # already checks the record block's other values while disabled for the same reason
        # — a typo is still a typo the moment someone flips the switch. A disabled emit
        # returns before it touches the sink, so this costs a board with no record nothing.
        # The two field names are display prose for the record; they live on the board
        # client rather than in EngineConfig, so duck-type them off it and let the Fake
        # (which has neither) fall back to generic defaults rather than fail.
        # The record narrates the run in its own sticky by re-reading each stage's
        # evidence files. Resolve the per-item template exactly as the runner does —
        # {state_dir} substituted here, {item_id} left for the Recorder — so both point
        # at the same files. None (the default) = no narration, today's engine exactly.
        ev = getattr(getattr(config, "evidence", None), "dir", None)
        record_evidence_dir = (
            os.path.abspath(os.path.expanduser(ev.replace("{state_dir}", str(self.state_dir))))
            if ev else None
        )
        self.recorder = Recorder(
            self.board,
            config.record,
            status_field=getattr(self.board, "status_field", "Status"),
            pipeline_field=getattr(self.board, "pipeline_field", "Pipeline"),
            evidence_dir=record_evidence_dir,
            project=getattr(config, "project", ""),
        )

        # The outward sinks, built from `pipeline.report:` unless a caller injects
        # its own. An absent block yields an empty list, and an empty list is the
        # whole no-config story: the fan-out iterates it, calls nothing, and a
        # project that never declared `report:` behaves exactly as it did before.
        # Construction is cheap and offline by contract (interfaces.Reporter), the
        # same property that lets the Recorder above be built while disabled.
        self.reporters = (
            list(reporters)
            if reporters is not None
            else build_reporters(
                getattr(config, "report", ()) or (),
                state_dir=self.state_dir,
                status_field=getattr(self.board, "status_field", "Status"),
                pipeline_field=getattr(self.board, "pipeline_field", "Pipeline"),
                project=getattr(config, "project", ""),
                # The card's step counter reads this and nothing else, so the count
                # is the chain the engine actually runs. Not built here would mean
                # the number lives in prose, which is where it went stale before.
                chain=[s.id for s in config.stages],
                # DISARMED unless the CALLER says otherwise, and the default is what
                # makes the gate real: a library caller, a test and every path that
                # is not the CLI's explicit --report-send rehearses. The flag decides
                # one thing only, whether bytes leave; it never widens an event
                # filter and never resolves an address here (a sink that read its
                # secret at construction would fail engine start on a box where the
                # variable is merely not exported yet).
                armed=bool(report_send),
            )
        )

    def _writable_pipeline_values(self) -> list:
        """Every pipeline value the engine can WRITE — the preflight's subject.

        Derived from the chain rather than listed in config: a hand-kept list would
        drift the moment a stage is added, and drift in a guard is worse than no guard.
        """
        values = ["queued"]                       # the ARM latch
        for s in self.cfg.stages:
            values.append(s.on_success)           # forward edge (the last one = terminal)
            if s.on_fail == "rewind" and getattr(s, "rewind_to", None):
                values.append(s.rewind_to)        # backward edge: a written value too
            target = getattr(s, "reject_to", None)
            if target:
                # the reject edge names a STAGE-ID; the engine writes that stage's
                # before-key, which is what has to exist as a board option.
                before = self._before_by_stage_id.get(target)
                if before:
                    values.append(before)
        values.append("parked")                   # every park site writes the bare option
        return [v for v in dict.fromkeys(values) if v]

    def _writable_status_values(self) -> list:
        """The human-column values the engine can write. `working_status`/`park_status`
        are None until a config opts in, and an unset knob must not force a field-list
        read for a value the engine never writes."""
        return [
            v
            for v in dict.fromkeys(
                [self.cfg.pr_status, self.cfg.working_status, self.cfg.park_status]
            )
            if v
        ]

    def _emit(self, event, item, res, **kwargs):
        """The ONLY way this module reports anything, to EVERY sink.

        All eight state-machine call sites land here, which is what lets an outward
        sink see the WHOLE run (armed, park and gate are authored by the engine and
        no stage ever observes them) without the engine learning anything about
        channels, addresses or delivery. The sticky board comment is simply the
        first entry in the list.

        `self.recorder` is read HERE, at call time, and never frozen into a list at
        construction: 24 tests replace `engine.recorder` after the engine is built,
        and a frozen list would keep reporting to the original object while every
        one of them went green against something nothing measures.

        Each sink is guarded SEPARATELY. `emit_guarded` already takes its receiver
        as a parameter, so its invariant (a report never decides whether work
        advances) holds per sink with nothing changed about it. One shared guard
        would let the first failure swallow every later sink in the same emit.

        `res` is an explicit PARAMETER, never reached out for from an enclosing
        scope: an earlier design referenced it implicitly, which raises NameError
        INSIDE the hook — i.e. it produced exactly the damage the hook exists to
        avoid (a successful advance reported as a skip, with no rollback).
        """
        for sink in (self.recorder, *self.reporters):
            emit_guarded(sink, res, event, item, **kwargs)

    def _arm_notes(self, item, stage, res):
        """Give the runner a note sink bound to THIS item and stage.

        Notes go to the outward reporters ONLY, never to `self.recorder`. The
        sticky comment is the ledger of state changes; a row per muttered sentence
        stops being a ledger and eats a body cap that the run record needs.

        A runner that knows nothing of notes simply never calls back, so every
        other instance of this engine is unaffected. Setting the attribute is
        wrapped because a runner is a PORT: an implementation may legitimately
        refuse attributes, and a report seam must never decide whether work runs.
        """
        def sink(stage_, item_, text):
            for reporter in self.reporters:
                emit_guarded(reporter, res, "note", item_, stage=stage_, note=text)

        try:
            self.runner.on_note = sink
        except Exception:  # noqa: BLE001 - see the docstring
            pass

    def _set_human_status(self, res, item, value):
        """Write the human column, best-effort. Returns what LANDED (None if nothing).

        Best-effort because this column is a DISPLAY of state the pipeline field
        already holds durably. Letting a cosmetic write raise would hand it the power
        to divert the state machine: at ARM the outer guard would report a latched
        item as skipped, at a park it would skip the site's `dispatched += 1` and the
        park's own record row, and at the dispatch heal it would stall an item forever
        behind a write that advances nothing. Every call site writes the pipeline field
        FIRST, so a failure here loses the label, never the state.

        It returns the landed value because the record prints the transition. A row
        claiming `"Todo"→"In Progress"` for a write that 403'd is a lie in the one
        artifact that exists to be true.
        """
        if not value:
            return None
        try:
            self.board.set_status(item.id, value)
            return value
        except Exception as e:
            res.notes = (res.notes + f"; status {item.id}: {e!r}").lstrip("; ")
            return None

    def _park(self, res, item, ledger, *, reason, stage=None, reset_keys=()):
        """The ONE place an item is parked. Writes; never decides what a park COSTS.

        Concurrency accounting (`dispatched += 1`) deliberately stays at the call
        sites: the nine park sites do NOT agree on it, and folding that decision in
        here would silently rewrite it. The reject path charges a slot because a
        review actually ran and returned a verdict; the whole crash path does not, so
        one card failing every tick cannot starve a `concurrency: 1` board. See
        tests/test_park_invariants.py, which pins all nine on both axes.

        Order is load-bearing: the pipeline write IS the park (durable, engine-owned),
        so it goes first and a failure propagates before anything else claims the item
        parked. The attempt resets follow only once it lands — a failing park leaves
        the counts intact for the next tick, still bounded.

        Two texts, never one:
          ledger — may carry `{e!r}`; stays in `res.notes`, the launchd ledger.
          reason — ENGINE-AUTHORED, goes to the board. `res.notes` embeds argv and
                   stderr of a GhCliError, and `result.notes` is the crashed
                   subprocess's own output; posting either republishes a worker's
                   stderr — and whatever a token-bearing command printed — to a
                   world-readable repo.
        """
        self.board.set_pipeline(item.id, "parked")
        for key in reset_keys:
            self.attempts.reset(key)
        res.parked.append(item.id)
        res.notes = (res.notes + f"; {ledger}").lstrip("; ")
        self._set_human_status(res, item, self.cfg.park_status)
        self._emit("park", item, res, stage=stage, reason=reason)

    # test/ops helper: seed the prev snapshot
    def prime_prev(self, mapping: dict) -> None:
        snapshot.save_atomic(self.prev_path, mapping)

    def _next_stage(self, pipeline):
        return self._stage_by_before.get(pipeline)

    def _is_inflight(self, pipeline) -> bool:
        return bool(pipeline) and pipeline != self._terminal and not pipeline.startswith("parked")

    def tick(self, arm: bool = True) -> TickResult:
        """One tick. `arm=False` advances what is ALREADY armed, and arms nothing.

        The default is the whole engine as it always was, and every scheduled run
        keeps it. `arm=False` exists for a caller that chains several ticks inside
        one invocation (cli's --max-stages): repeating the ARM phase there would
        turn ONE human release into an arming sweep of every card that happens to
        land in the trigger column while the chain runs. Arming stays what it has
        always been — a person moves a card, and the next scheduled tick latches
        it.
        """
        res = TickResult()

        if is_paused(self.paused_file):
            res.paused = True
            res.notes = "PAUSED file present"
            return res
        if self.budget.exceeded():
            res.notes = "token ceiling reached"
            return res

        try:
            items = self.board.fetch_items()
        except Exception as e:
            # Same rule as the cli.py preflight seam: TRANSIENT (rate limit,
            # 5xx, network down — the error itself says it clears) skips THIS
            # tick with a quiet ledger note; the poll timer is the retry.
            # Everything else is PERMANENT (BoardTruncated, bad auth/scope,
            # unknown shapes): every future tick fails identically, so a quiet
            # exit-0 skip would wedge the whole pipeline invisibly — nothing
            # arms, nothing advances, launchd sees a healthy unit. Raise.
            if not _is_transient_board_error(e):
                raise
            res.notes = f"board fetch failed: {e!r}"
            return res
        cur_status = {i.id: i.status for i in items}

        # --- ARM ---
        # Gated on `not i.pipeline`, NOT on the status column — which is why the engine
        # may now write that column at all. Every pipeline write below (and at all nine
        # park sites) sets a non-empty value and nothing ever clears the field, so once
        # an item is latched the second conjunct is False for the rest of its life and
        # the status value cannot re-arm it. tests/test_arm.py drives the worst config
        # that exists — `working_status == trigger_status` — and it still does not re-arm.
        #
        # `items if arm else ()` rather than an `if arm:` around the block: the whole
        # phase below stays byte-identical, so the one thing this parameter can do is
        # skip it entirely. It cannot arm differently, only not at all.
        for i in (items if arm else ()):
            if i.status == self.cfg.trigger_status and not i.pipeline:
                try:
                    if not valid_item_id(i.id):
                        # Park with the BARE board option; the reason rides in notes, never
                        # as an option suffix. A compound "parked:bad-id" is not a live
                        # single-select value, so the write would KeyError, the item would
                        # never actually park, and it would re-dispatch forever.
                        self._park(res, i, f"arm {i.id}: invalid item id", reason="invalid item id")
                        continue
                    if self.cfg.require_issue and i.issue_number is None:
                        # A draft card carries no issue, so it can hold no `Closes #N`, no
                        # PR link and no comment: arming it burns every expensive stage on
                        # something that can never reach a PR, then has nowhere to report.
                        # REFUSED, not parked — a park is a write that outlives the defect
                        # (convert the draft to a real issue and the card would stay
                        # `parked` until a human cleared Pipeline by hand). Skipping
                        # self-heals the moment the card grows an issue, and says so on
                        # every tick until someone fixes the board.
                        res.skipped.append(i.id)
                        res.notes = (
                            res.notes + f"; arm {i.id}: no issue behind it (draft card) — refusing to arm"
                        ).lstrip("; ")
                        continue
                    if Lock(self.lockdir, i.id).held_by_alive():
                        # The ARM loop runs OUTSIDE the per-item lock the dispatch loop
                        # takes. Without this check, a human clearing Pipeline mid-run
                        # re-arms the item and zeroes its bounce counter UNDER a running
                        # stage — the rework budget resets to 0 and the cap stops bounding
                        # anything. `held_by_alive()` and not `acquire()`: acquiring would
                        # STEAL a dead lock, which is right for a dispatcher about to do
                        # the work and wrong for a loop that must only stand back.
                        res.skipped.append(i.id)
                        res.notes = (
                            res.notes + f"; arm {i.id}: item lock held by a live worker"
                        ).lstrip("; ")
                        continue
                    if self._has_backward_edge:
                        # Reset the durable bounce counter so a re-armed item starts a
                        # fresh rework budget (never re-escalates on a stale count).
                        # BEFORE the latch, because this reset is write-once-or-never:
                        # ARM is the only place it happens. Reset after the latch and a
                        # failing write leaves the item armed forever with a STALE count
                        # and no second chance to clear it. Reset first, and the failure
                        # simply leaves the item unarmed for the next tick to retry.
                        self.board.set_number(i.id, self.cfg.bounce_field, 0)
                    self.board.set_pipeline(i.id, "queued")   # THE LATCH — armed as of here
                    # Only after the latch: a status write that landed while the latch
                    # failed is the roach motel — the card leaves the free column while
                    # the engine does not consider it armed, so it never dispatches and
                    # nobody picks it up either.
                    status_to = self._set_human_status(res, i, self.cfg.working_status)
                    res.armed.append(i.id)
                    self._emit("armed", i, res, to="queued", status_to=status_to)
                except Exception as e:  # a board write failed (e.g. 403) — note, skip, retry next tick
                    res.skipped.append(i.id)
                    res.notes = (res.notes + f"; arm {i.id}: {e!r}").lstrip("; ")

        # re-read so armed pipeline values are visible
        # ... but only when there WAS an ARM phase. With `arm=False` nothing has
        # written to the board since the fetch above, so a second read returns the
        # same rows at the price of another API round trip — and a chained call
        # makes that price N times per invocation, against the same rate-limit
        # bucket the chain exists to stop hammering.
        if arm:
            try:
                items = self.board.fetch_items()
            except Exception as e:
                # Deliberately BROADER than the first fetch guard: a permanent
                # failure here hits the identical call at the NEXT tick's first
                # fetch, which raises loudly — so this site cannot wedge quietly.
                # Swallowing keeps this tick's ARM ledger rows and the snapshot
                # instead of losing them to a raise after work already landed.
                res.notes = (res.notes + f"; re-fetch: {e!r}").lstrip("; ")
                snapshot.save_atomic(self.prev_path, cur_status)
                return res
        inflight = [i for i in items if self._is_inflight(i.pipeline)]

        dispatched = 0
        for i in inflight:
            if dispatched >= self.cfg.concurrency:
                break
            if not valid_item_id(i.id):
                self._park(res, i, f"dispatch {i.id}: invalid item id", reason="invalid item id")
                continue

            lock = Lock(self.lockdir, i.id)
            if not lock.acquire():
                res.skipped.append(i.id)  # a live worker holds it — idempotent no-op
                continue
            try:
                # A human setting done_status mid-flight is a TERMINAL signal: halt
                # this item and leave every field where the person left it.
                # `_is_inflight` tracks `pipeline` only, so without this the card runs
                # on and the gate stamps pr_status over the human's Done — including
                # down the PR-idempotency path below, which writes the status without
                # dispatching anything. "The engine never SETS done_status" was never
                # the same promise as "the engine STOPS when a human sets it".
                # Deliberately NOT a park: Done is the human's terminal state, not the
                # engine's failure state, and parking would repaint a finished card as
                # broken. No slot is consumed because no work was done.
                if self.cfg.done_status and i.status == self.cfg.done_status:
                    res.skipped.append(i.id)
                    res.notes = (
                        res.notes + f"; halt {i.id}: human set status {self.cfg.done_status!r}"
                    ).lstrip("; ")
                    continue

                # Blind rework: a reject round landed on the durable counter but no
                # note reached the item (the best-effort comment write failed, or the
                # authenticated read-back denied it). Re-dispatching asks the producer
                # to redo the work while telling it nothing about what was wrong — it
                # returns the same output, bounces again, and burns the entire rework
                # budget producing nothing, while the ledger reports a healthy reject
                # loop the whole way down. Park: the same information, made loud, for
                # zero spend. Fires before the runner, so it costs no slot.
                #
                # Gated on the REJECT edge, because only a reject produces a note. Both
                # backward edges bump the same durable counter, but a rewind is a CRASH
                # recovery: no reviewer ran, so no note exists to lose, and an ungated
                # check would read every rewind as a lost note and park the item on its
                # first crash — silently disabling the rewind edge it shares a counter
                # with. Where BOTH edges exist the two are indistinguishable from the
                # counter alone, and this stays fail-closed on purpose: it parks (loud,
                # zero spend, human-recoverable) rather than risk a real blind rework.
                if self._has_reject_edge and i.bounces > 0 and not (i.annotation or "").strip():
                    self._park(
                        res,
                        i,
                        f"park {i.id}: bounced {i.bounces}x but no reject note reached it "
                        f"(lost comment or denied read-back) — refusing a blind rework",
                        reason=f"bounced {i.bounces}x with no reject note — refusing a blind rework",
                    )
                    continue

                stage = self._next_stage(i.pipeline)
                if stage is None:
                    res.skipped.append(i.id)
                    continue

                # PR idempotency: never open a second PR for the same item
                if stage.gate == "human" and self.board.pr_exists(i.id):
                    self.board.set_pipeline(i.id, stage.on_success)
                    self.board.set_status(i.id, self.cfg.pr_status)
                    # The SAME end state as the gate advance below — PR open, human
                    # column handed over, engine stopped — reached without dispatching.
                    # A record that only knew the advancing site would show a run that
                    # simply stops, with no gate row, whenever a re-tick takes this path.
                    self._emit(
                        "gate", i, res, stage=stage,
                        to=stage.on_success, status_to=self.cfg.pr_status, skipped=True,
                    )
                    res.skipped.append(i.id)
                    res.gated.append(i.id)
                    continue

                # Self-heal the human column, immediately before the work that justifies
                # it: an in-flight item whose status drifted (a person dragged the card
                # back to a free column) keeps running, because `pipeline` owns the state
                # machine — so the board advertises as unclaimed a story an agent is about
                # to spend an LLM run on, and someone picks it up in parallel.
                #
                # Placement is on both sides:
                #   AFTER the Done halt, which reads the same `i.status` this overwrites —
                #     heal first and the halt would consult the value the engine just
                #     wrote, erasing the human's terminal signal before it was ever seen;
                #   AFTER every exit above that has its own correct column (a park, an
                #     already-open PR) — healing those to "an agent owns this" costs a
                #     board write only to contradict it a line later, and leaves a parked
                #     card mislabelled if the park's own best-effort write then fails.
                if self.cfg.working_status and i.status != self.cfg.working_status:
                    self._set_human_status(res, i, self.cfg.working_status)

                # THE HEARTBEAT, and it must land BEFORE the run. A stage is a
                # model run and takes minutes; every other event of this engine
                # reports a completion. If the start landed afterwards it would be
                # indistinguishable in time from `stage` and worthless as a sign of
                # life. `_emit` guards each sink separately, so a failing sink
                # cannot hold up the stage.
                self._emit("stage_start", i, res, stage=stage)

                # Hand the runner a way to speak WHILE it works. A stage is a
                # model run of several minutes and reports only on exit, so the
                # channel would otherwise show one "dispatched" card and then
                # nothing, which is indistinguishable from a hang.
                self._arm_notes(i, stage, res)
                result = self.runner.run(stage, i)
                self.budget.add(getattr(result, "tokens", 0) or 0)

                attempt_key = f"{i.id}::{stage.id}"

                # --- REJECT EDGE (first branch; ok=False ignores verdict) ---------
                # A clean review run that returns verdict=="reject" returns the item
                # to an upstream producer with a durable bounce + best-effort note.
                # A CRASH (ok=False) never counts as a reviewer → falls through to
                # the on_fail handling below.
                if result.ok and getattr(result, "verdict", None) == "reject" and getattr(stage, "reject_to", None):
                    target_id = getattr(result, "reject_to", None) or stage.reject_to
                    before_key = self._before_by_stage_id.get(target_id)
                    if before_key is None:
                        # unresolvable target (should be caught at load) → park, never loop
                        self._park(
                            res,
                            i,
                            f"park {i.id}: reject target {target_id!r} unresolved",
                            reason=f"reject target {target_id!r} resolves to no stage",
                            stage=stage,
                        )
                        dispatched += 1
                        continue
                    bf = self.cfg.bounce_field
                    eff_max = getattr(stage, "max_rounds", None) or self.cfg.max_rounds
                    # 1) durable counter FIRST (source of truth — never len(comments)).
                    #    FAIL-CLOSED: the board Number write is the ONLY per-item
                    #    terminator for this edge. If it raises (missing/misnamed
                    #    field, persistent 4xx/5xx), do NOT fall through to the generic
                    #    skip-and-retry — that re-runs the expensive review every poll
                    #    forever. Instead back off onto the LOCAL durable counter and
                    #    park once it reaches the same rework budget, so the costly
                    #    review can never re-run unbounded when the counter write fails.
                    bounce_key = f"{attempt_key}::bounce-write"
                    try:
                        n = int(self.board.get_number(i.id, bf) or 0) + 1
                        self.board.set_number(i.id, bf, n)
                    except Exception as e:
                        local = self.attempts.bump(bounce_key)
                        cap = eff_max
                        if cap is None or local >= cap:
                            # park FIRST; only clear the durable backstop once the park
                            # write lands (a failing park propagates to the outer guard
                            # and the count survives for the next tick — still bounded).
                            self._park(
                                res,
                                i,
                                f"park {i.id}: bounce-counter write failed at {stage.id} "
                                f"({e!r}); local backstop exhausted ({local}/{cap})",
                                reason=f"bounce-counter write failed at {stage.id}; "
                                       f"local backstop exhausted ({local}/{cap})",
                                stage=stage,
                                reset_keys=(attempt_key, bounce_key),
                            )
                        else:
                            # leave the pipeline where it is (review re-runs), but the
                            # local counter climbs toward the park cap — BOUNDED, never
                            # the unbounded skip-and-retry the generic except would give.
                            res.skipped.append(i.id)
                            res.notes = (
                                res.notes
                                + f"; bounce {i.id}: counter write failed at {stage.id} "
                                  f"({e!r}); local backstop {local}/{cap}"
                            ).lstrip("; ")
                        dispatched += 1
                        continue
                    # board write succeeded → drop any local backstop count
                    self.attempts.reset(bounce_key)
                    if eff_max is not None and n >= eff_max:
                        # rounds exhausted → terminal park.
                        self._park(
                            res,
                            i,
                            f"park {i.id}: reject rounds exhausted ({n}/{eff_max}) at {stage.id}",
                            reason=f"reject rounds exhausted ({n}/{eff_max}) at {stage.id}",
                            stage=stage,
                            reset_keys=(attempt_key,),
                        )
                        dispatched += 1
                        continue
                    # 2) the latch — set pipeline back to the producer's before-key
                    self.board.set_pipeline(i.id, before_key)
                    # 3) best-effort comment — its failure must NOT block the advance
                    #    and must NOT affect the count (termination is decoupled).
                    #    REDACT-AND-POST, never refuse-to-post: this is raw reviewer LLM
                    #    output going to a world-readable repo, and nothing scanned it
                    #    before (_NOTE_PROMPT_CAP bounds what the PROMPT reads, never
                    #    what the engine posts). Refusing on a hit would leave the item
                    #    with bounces > 0 and no note — which the blind-rework guard
                    #    above then parks, so one false positive would cost a whole run.
                    #    scan.py redacts per SPAN, so a false positive costs one
                    #    placeholder instead. The `off` knob is honoured: a redaction the
                    #    producer cannot read is feedback it cannot act on, and that is a
                    #    real private-repo tradeoff for an operator to make deliberately.
                    note = result.annotation or ""
                    if self.cfg.record.scan == "redact":
                        note, hits = scrub(note)
                        if hits:
                            rules = ", ".join(sorted({h.rule for h in hits}))
                            res.notes = (
                                res.notes + f"; redacted {i.id}: {len(hits)} hit(s) in the reject note ({rules})"
                            ).lstrip("; ")
                    try:
                        self.board.comment(i.id, reject_comment(n, note))
                    except Exception as e:
                        res.notes = (res.notes + f"; comment {i.id}: {e!r}").lstrip("; ")
                    self.attempts.reset(attempt_key)
                    res.rejected.append(i.id)
                    self._emit(
                        "reject", i, res, stage=stage, result=result,
                        to=before_key, round=n, max_rounds=eff_max, note=note,
                    )
                    dispatched += 1   # a reject counts against concurrency
                    continue

                if result.ok:
                    self.attempts.reset(attempt_key)  # fresh retries if it re-enters this stage
                    self.board.set_pipeline(i.id, stage.on_success)
                    if stage.gate == "human":
                        # reached the PR gate → hand the human column over and STOP.
                        # The engine NEVER sets done_status.
                        self.board.set_status(i.id, self.cfg.pr_status)
                        # The pr stage echoes its PR URL as stdout → result.notes. Lift
                        # it so the record's own gate row LINKS the PR, instead of
                        # leaving the reader to hunt the Development panel. Only the http
                        # line, never raw notes (transparency.md §7).
                        # `gate` and not `stage`: one transition, one row. The gate row
                        # already says `pass → <terminal>`; a stage row beside it would
                        # report the PR stage twice in the sticky.
                        self._emit(
                            "gate", i, res, stage=stage, result=result,
                            to=stage.on_success, status_to=self.cfg.pr_status,
                            pr=_http_line(getattr(result, "notes", "")),
                        )
                        res.gated.append(i.id)
                    else:
                        self._emit(
                            "stage", i, res, stage=stage, result=result,
                            to=stage.on_success, outcome="pass",
                        )
                    res.dispatched.append(i.id)
                    dispatched += 1
                else:
                    # crash / ok=False — a stage that did NOT run cleanly never counts
                    # as a reviewer, so verdict is ignored here; route to on_fail.
                    if stage.retry and stage.retry > 0 and self.attempts.get(attempt_key) < stage.retry:
                        # absorb one retry: bump the durable counter, leave the pipeline
                        # in place so the SAME stage re-runs next tick.
                        attempt = self.attempts.bump(attempt_key)
                        res.skipped.append(i.id)
                        # Without this row a retry is INVISIBLE: no board write, no notes
                        # append, `result.notes` discarded, and an anonymous entry in
                        # res.skipped indistinguishable from a lock skip. It is exactly
                        # the "which stage is weak" signal the record exists to give.
                        self._emit(
                            "stage", i, res, stage=stage, result=result,
                            outcome="retry", attempt=attempt, of=stage.retry,
                        )
                    elif stage.on_fail == "rewind" and stage.rewind_to:
                        # The backward edge MUST terminate. It carries no counter of
                        # its own: retries are spent by definition here (so the local
                        # attempt counter is reset on the way through) and the token
                        # budget is inert, which left the tick count as the only bound
                        # — and nothing bounds the tick count. Route it through the
                        # SAME durable board counter the reject edge uses: both are
                        # backward edges spending the same rework budget, and that
                        # budget belongs to the ITEM, not to the edge that consumed it.
                        bf = self.cfg.bounce_field
                        eff_max = (
                            getattr(stage, "max_rounds", None)
                            or self.cfg.max_rounds
                            or _DEFAULT_BACKWARD_ROUNDS
                        )
                        try:
                            n = int(self.board.get_number(i.id, bf) or 0) + 1
                            self.board.set_number(i.id, bf, n)
                        except Exception as e:
                            # FAIL-CLOSED: no durable count = no terminator, and
                            # falling through to the generic skip-and-retry would
                            # re-run the crashed stage every poll with nothing
                            # counting — the original defect through a side door.
                            # Unlike the reject edge (a HEALTHY review whose rework
                            # budget is worth protecting across a transient board
                            # error) this stage just crashed, so there is no work in
                            # flight to preserve. Park rather than rewind uncounted.
                            self._park(
                                res,
                                i,
                                f"park {i.id}: {stage.id} failed and the bounce-counter "
                                f"write failed ({e!r}) — no durable terminator",
                                reason=f"{stage.id} failed and the bounce-counter write "
                                       f"failed — no durable terminator",
                                stage=stage,
                                reset_keys=(attempt_key,),
                            )
                            continue
                        self.attempts.reset(attempt_key)  # retries spent → take the backward edge
                        if n >= eff_max:
                            self._park(
                                res,
                                i,
                                f"park {i.id}: rewind rounds exhausted ({n}/{eff_max}) at {stage.id}",
                                reason=f"rewind rounds exhausted ({n}/{eff_max}) at {stage.id}",
                                stage=stage,
                            )
                        else:
                            self.board.set_pipeline(i.id, stage.rewind_to)
                            res.skipped.append(i.id)
                            self._emit(
                                "stage", i, res, stage=stage, result=result,
                                outcome="rewind", to=stage.rewind_to,
                            )
                    else:
                        # Terminal park on a non-retryable failure — bare board option +
                        # reason in notes, so a blocked push / hollow analysis surfaces in
                        # the log instead of silently looping (the board has no "parked:*").
                        # `result.notes` is the crashed subprocess's OWN output: it goes to
                        # the local ledger and never to the board, so the posted reason is
                        # the engine's own words about its own decision.
                        detail = (result.notes or "").strip().replace(chr(10), " ")[:200]
                        self._park(
                            res,
                            i,
                            f"park {i.id}: {stage.id} failed: {detail}",
                            reason=f"{stage.id} failed and declares no retry",
                            stage=stage,
                            reset_keys=(attempt_key,),
                        )
            except Exception as e:  # board/gh failure mid-dispatch — note, skip, retry next tick
                res.skipped.append(i.id)
                res.notes = (res.notes + f"; dispatch {i.id}: {e!r}").lstrip("; ")
            finally:
                lock.release()

        snapshot.save_atomic(self.prev_path, cur_status)
        return res
