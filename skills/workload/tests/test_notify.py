"""notify: the one adapter that knows how to speak, and the exit code is the fact.

Written before the sender existed. The property that carries everything else
is the LAST one here: a non zero exit must not be read as delivery. The scar is
concrete and in this repo: a watchdog reported into the void for three months
because its send function returned success while its channel had been off since
May, and a second guard still starts its 24 hour silence on the DECISION to
notify rather than on a confirmed delivery.
"""

from __future__ import annotations

import dataclasses
import unittest
from types import SimpleNamespace

from tests.conftest import (
    CORPUS,
    DERIVED,
    FakeCompleted,
    MachineGuard,
    RecordingRunner,
    SKILL_DIR,
    engine_sources,
    mod,
)

notify = mod("engine.notify")
model = mod("engine.model")
report_mod = mod("engine.report")


def load(name):
    for folder in (CORPUS, DERIVED):
        path = folder / f"{name}.yaml"
        if path.exists():
            return model.load_declaration(path)
    raise AssertionError(name)


class TheSenderSpeaksTheWordsItWasGiven(MachineGuard):
    """The program and its flags come from configuration, never from this code.

    They used to be a literal here: a hardcoded script name searched at two
    fixed paths, called with three German flags, inside a file that carries
    `scope: core` and ships to an English repository which does not contain that
    script at all. `workloads.notify_via` existed the whole time, was parsed,
    stored and serialised, and no line ever read it. A fresh clone therefore had
    a skill whose alarm path could not exist, and an instance that configured
    one was ignored.

    Every scar of the old class is kept below, restated against the template
    instead of against three particular flags.
    """

    SPEC = {
        "command": ["/opt/bin/notify", "--subject", "{what}", "--host", "{where}",
                    "--action", "{todo}"],
        "detail": ["--body", "{detail}"],
    }

    def send(self, runner, **over):
        args = dict(what="twice-daily-report.midday", where="host-a",
                    todo="read the unit's log", detail="due 06:30, no line since")
        args.update(over)
        return notify.send(argv=notify.argv_for(self.SPEC, **args), runner=runner)

    def test_every_element_of_the_template_reaches_the_program(self):
        runner = RecordingRunner()
        self.send(runner)
        argv = runner.calls[0]["argv"]
        self.assertEqual(argv[0], "/opt/bin/notify",
                         "the configured program is not the one that ran")
        for flag in ("--subject", "--host", "--action", "--body"):
            self.assertIn(flag, argv,
                          f"{flag} was declared and dropped; a call missing part of "
                          f"its template is not a message, it is an error nobody sees")

    def test_a_placeholder_is_substituted_and_never_left_standing(self):
        runner = RecordingRunner()
        self.send(runner)
        argv = runner.calls[0]["argv"]
        leftover = [a for a in argv if "{" in a and "}" in a]
        self.assertEqual(leftover, [],
                         f"placeholders survived into the argv: {leftover}")
        self.assertIn("twice-daily-report.midday", argv)
        self.assertIn("host-a", argv)

    def test_the_words_are_passed_as_arguments_and_not_pasted_into_a_shell(self):
        runner = RecordingRunner()
        self.send(runner, what="a title with 'quotes' and $VARS and ; rm -rf /")
        argv = runner.calls[0]["argv"]
        self.assertIn("a title with 'quotes' and $VARS and ; rm -rf /", argv,
                      "the text has to arrive as ONE argv element. Pasted into a "
                      "shell string, a detail taken from a machine's own output "
                      "becomes a command")

    def test_a_substituted_element_is_never_split_on_its_spaces(self):
        # The substitution happens per element, so a value with spaces stays
        # one element. Building the argv by joining and re-splitting would turn
        # a two word host into two arguments and the program would read the
        # second as a flag.
        argv = notify.argv_for(self.SPEC, what="w", where="two words",
                               todo="t", detail="")
        self.assertIn("two words", argv)

    def test_the_detail_segment_is_dropped_when_there_is_no_detail(self):
        argv = notify.argv_for(self.SPEC, what="w", where="h", todo="t", detail="")
        self.assertNotIn("--body", argv,
                         "an empty detail still sent its flag, so the program "
                         "received a flag with a missing value")

    def test_a_zero_exit_is_the_only_thing_that_counts_as_delivered(self):
        runner = RecordingRunner().add("notify", FakeCompleted(rc=0))
        self.assertTrue(self.send(runner).delivered)

    def test_a_non_zero_exit_is_not_delivered(self):
        # THE one that matters. Everything that dampens repeats hangs off this
        # answer, so reading a failure as a success buys silence with nothing.
        runner = RecordingRunner().add("notify", FakeCompleted(rc=1))
        answer = self.send(runner)
        self.assertFalse(
            answer.delivered,
            "a failed send read as a delivery is how a backoff starts without "
            "anybody having been told anything")
        self.assertTrue(answer.reason, "a failure has to say something about itself")

    def test_a_program_that_is_not_there_is_reported_and_never_raised(self):
        runner = RecordingRunner().add("notify", raises=FileNotFoundError("nope"))
        answer = self.send(runner)
        self.assertFalse(answer.delivered)
        self.assertIn("nope", answer.reason)

    def test_a_send_that_blows_up_is_still_an_answer(self):
        runner = RecordingRunner().add("notify", raises=OSError("broken pipe"))
        answer = self.send(runner)
        self.assertFalse(
            answer.delivered,
            "the caller is a watchdog. It may not be taken down by the thing it "
            "uses to complain")

    def test_the_adapter_adds_no_recipient_of_its_own(self):
        runner = RecordingRunner()
        self.send(runner)
        joined = " ".join(c["joined"] for c in runner.calls)
        for shape in ("@", "+49", "chat_id"):
            self.assertNotIn(
                shape, joined,
                f"{shape!r} in the argv means this adapter decided who gets the "
                f"message. It does not: the configured program owns that, and a "
                f"second place naming recipients is a second list to keep in step")


class TheAlarmPathIsDeclaredAndNeverGuessed(MachineGuard):
    """No program name lives in this skill's code.

    The previous shape searched `~/bin` and then the repository for one fixed
    filename, with a real and well argued reason for that order. The reason is
    instance policy, so it belongs in that instance's configuration, where it
    can be written down as the two paths it actually is. What may not stay in a
    `scope: core` skill is the filename itself.
    """

    def spec_from(self, block):
        return notify.notifier_spec(SimpleNamespace(notify_via=block))

    def test_the_configured_command_is_the_one_that_runs(self):
        spec = self.spec_from({"command": ["/opt/bin/mine", "{what}"]})
        argv = notify.argv_for(spec, what="w", where="h", todo="t", detail="")
        self.assertEqual(argv[0], "/opt/bin/mine")

    def test_a_home_relative_program_is_expanded(self):
        """`~/bin/...` is what a person writes, and exec does not know it.

        The argv is handed to a process, not to a shell, so a leading tilde
        would arrive as a literal directory name and the program would be
        reported missing. Expanded here, at the boundary that reads the
        configuration, rather than in the pure builder.
        """
        import os
        spec = self.spec_from({"command": ["~/bin/mine", "{what}"]})
        self.assertEqual(spec["command"][0],
                         os.path.expanduser("~/bin/mine"),
                         "a tilde survived into the argv, so the program is "
                         "looked for in a directory literally called ~")
        self.assertEqual(spec["command"][1], "{what}",
                         "expansion touched a placeholder element")

    def test_no_notifier_configured_is_an_answer_and_not_a_guess(self):
        self.assertIsNone(
            self.spec_from(None),
            "an unconfigured alarm path must come back as absent. Inventing a "
            "filename is how a skill acquires a dependency its repository does "
            "not ship")

    def test_nothing_that_ships_names_a_notifier_program(self):
        """Code AND the documentation beside it, because both are the contract.

        The tests are excluded on purpose and only there: a mutation names a
        filename as its payload, which is the point of that mutation. Anything
        an instance receives may not.
        """
        surface = list(engine_sources())
        surface.append(SKILL_DIR / "SKILL.md")
        surface += sorted((SKILL_DIR / "references").glob("*.md"))
        self.assertGreater(len(surface), 5, "the surface scan found almost nothing")
        for path in surface:
            self.assertNotIn(
                "bridge-notify", path.read_text(encoding="utf-8"),
                f"{path.name} names a notifier program. The program is declared "
                f"in `workloads.notify_via`; a name here is a dependency this "
                f"repository does not ship")

    def test_a_dispatch_without_a_configured_notifier_says_so(self):
        import tempfile
        from datetime import datetime, timezone
        from pathlib import Path as _P
        with tempfile.TemporaryDirectory() as tmp:
            said = notify.dispatch(
                report_mod.Report(findings=[report_mod.Finding(
                    workload_id="twice-daily-report",
                    state=model.WorkloadState.last_run_failed,
                    severity=model.Severity.high, detail="d", hint="h",
                    source="machine", appointment="midday")],
                    header="h", runs={}),
                [load("twice-daily-report")],
                state_path=_P(tmp) / "s.json",
                now=datetime(2026, 8, 24, 12, tzinfo=timezone.utc),
                cfg=SimpleNamespace(notify_via=None))
            self.assertEqual(said.sent, 0)
            self.assertIn(
                "notify_via", (said.note or ""),
                "it stayed quiet about being unable to speak, and it did not name "
                "the key a reader has to set. Silence is the one failure mode "
                "this layer may never have")


# ── routing: which verdict wakes somebody, and on whose say-so ───────────────

class EveryStateDecidesWhetherItWakesSomebody(MachineGuard):
    """The closed enum, and a decision for every single member.

    An enum member with no decision is not neutral: it silently falls into
    whatever the last `if` does. This class exists so that growing the enum
    breaks a test instead of quietly adding a state that either shouts or
    disappears.
    """

    def test_the_four_buckets_together_cover_the_enum_exactly(self):
        covered = (notify.WAKES_ON_FAILURE | notify.WAKES_ON_MISSING
                   | notify.WAKES_ALWAYS | notify.WAKES_NOBODY)
        self.assertEqual(
            covered, set(model.WorkloadState),
            "a state that belongs to no bucket takes whatever the fall-through "
            "does, and nobody decided that")

    def test_no_state_sits_in_two_buckets(self):
        buckets = [notify.WAKES_ON_FAILURE, notify.WAKES_ON_MISSING,
                   notify.WAKES_ALWAYS, notify.WAKES_NOBODY]
        for i, one in enumerate(buckets):
            for other in buckets[i + 1:]:
                self.assertEqual(
                    one & other, set(),
                    f"{one & other} is in two buckets, so one run produces two "
                    f"messages about one fact")

    def test_unknown_wakes_nobody(self):
        self.assertIn(
            model.WorkloadState.unknown, notify.WAKES_NOBODY,
            "`unknown` means the machine did not answer. The reconcile that "
            "drives this runs over ssh from a laptop, so a closed lid produces "
            "it for every run on every host at once. Seventeen jobs were once "
            "wrongly called overdue by exactly this collapse")

    def test_the_healthy_states_wake_nobody(self):
        for state in (model.WorkloadState.in_sync, model.WorkloadState.observed,
                      model.WorkloadState.not_provisioned):
            self.assertIn(state, notify.WAKES_NOBODY, f"{state} is not trouble")


class ADeclarationThatAsksToBeToldIsTold(MachineGuard):
    """The hole itself: today `notify_on` is read and nothing is sent."""

    def finding(self, state, **over):
        args = dict(workload_id="twice-daily-report", state=state,
                    severity=model.Severity.high, detail="d", hint="h",
                    source="machine", appointment="midday")
        args.update(over)
        return report_mod.Finding(**args)

    def test_a_run_that_asks_about_failure_is_routed_when_its_run_failed(self):
        w = load("twice-daily-report")
        bucket = notify.route(self.finding(model.WorkloadState.last_run_failed), w)
        self.assertEqual(
            bucket, "failure",
            "the declaration says notify_on: [failure, missing] and its last run "
            "ended non zero; a field that reads like a promise and routes nothing "
            "is the whole defect this closes")

    def test_a_missing_run_is_routed_as_missing(self):
        w = load("twice-daily-report")
        self.assertEqual(notify.route(self.finding(model.WorkloadState.overdue), w),
                         "missing")

    def test_a_run_that_never_asked_is_never_routed(self):
        w = load("silent-by-choice")
        self.assertIsNone(
            notify.route(self.finding(model.WorkloadState.last_run_failed), w),
            "silence is the declared default, and a run whose notify_on is empty "
            "chose it on purpose. Ignoring that turns a laptop that travels into "
            "a half-hourly alarm")

    def test_asking_only_about_missing_does_not_get_failure_alarms(self):
        w = load("only-missing-asked")
        self.assertIsNone(
            notify.route(self.finding(model.WorkloadState.last_run_failed), w))
        self.assertEqual(
            notify.route(self.finding(model.WorkloadState.overdue), w), "missing")


class SomeThingsAreLouderThanTheDeclaration(MachineGuard):
    """Two verdicts route WITHOUT asking notify_on, and that is deliberate.

    Opt-in fails exactly where the declaration is out of date. Nobody edits
    notify_on on the way out while retiring a run, so `retired_but_live` (the
    loudest thing this skill can say, and possibly a security incident) would
    be gated behind a field the retiring hand never touched.

    `grant_orphaned` is worse: the run it describes ends rc=0 and simply gets
    shown nothing, so no trace will ever carry it. A gate in front of a state
    the gate's own vocabulary cannot name is a permanent blind spot.
    """

    def finding(self, state):
        return report_mod.Finding(workload_id="silent-run", state=state,
                                  severity=model.Severity.high, detail="d",
                                  hint="h", source="machine")

    def test_a_retired_run_that_is_still_live_is_routed_with_an_empty_notify_on(self):
        w = load("silent-by-choice")
        self.assertEqual(tuple(w.response.notify_on), (),
                         "fixture must have an empty notify_on for this to mean anything")
        self.assertEqual(
            notify.route(self.finding(model.WorkloadState.retired_but_live), w),
            "integrity")

    def test_a_moved_grant_is_routed_with_an_empty_notify_on(self):
        w = load("silent-by-choice")
        self.assertEqual(
            notify.route(self.finding(model.WorkloadState.grant_orphaned), w),
            "integrity",
            "the run ends rc=0 and is shown nothing, so its own trace can never "
            "carry this; behind an opt-in it would be invisible forever")


# ── dampening: what stops the same thing being said every half hour ──────────

class DispatchBase(MachineGuard):
    """One pass of the alarm layer, against a sender the test controls."""

    def setUp(self):
        super().setUp()
        import tempfile
        from pathlib import Path as _P
        self._tmp = tempfile.TemporaryDirectory()
        self.state = _P(self._tmp.name) / "notify-state.json"
        self.addCleanup(self._tmp.cleanup)
        self.sent = []

    def sender(self, rc=0):
        def send(**kw):
            self.sent.append(kw)
            return notify.Sent(rc == 0, "" if rc == 0 else f"exit {rc}")
        return send

    def finding(self, state=None, wid="twice-daily-report", appointment="midday",
                detail="the midday run ended with 1 at 2026-08-24T12:40:00Z"):
        return report_mod.Finding(
            workload_id=wid, state=state or model.WorkloadState.last_run_failed,
            severity=model.Severity.high, detail=detail,
            hint="read the unit's log", source="machine", appointment=appointment)

    def rep(self, *findings):
        return report_mod.Report(findings=list(findings), header="h", runs={})

    def at(self, hour=12, day=24):
        from datetime import datetime, timezone
        return datetime(2026, 8, day, hour, 0, tzinfo=timezone.utc)

    def once(self, *findings, rc=0, now=None, workloads=None, **kw):
        """One pass of the alarm layer.

        NOT called `run`: `unittest.TestCase.run` is how a case executes
        itself, so a helper by that name swallows the call and setUp never
        happens. Every test then fails on a missing attribute rather than on
        what it measures.
        """
        return notify.dispatch(
            self.rep(*findings), workloads or [load("twice-daily-report")],
            state_path=self.state, now=now or self.at(), sender=self.sender(rc), **kw)


class TheBackoffIsBoundToDelivery(DispatchBase):
    """The scar this whole layer is built around.

    `claude-cli-health-guard.sh` starts its 24 hour silence on the DECISION to
    notify. If both its channels are dead it stays quiet for a day having told
    nobody anything. `watchdog.sh` does it right and only records an alert
    after a confirmed delivery. This copies watchdog.
    """

    def test_a_delivered_alarm_buys_silence(self):
        self.once(self.finding())
        self.once(self.finding())
        self.assertEqual(
            len(self.sent), 1,
            "the same unchanged trouble was reported twice; at a half-hourly "
            "cadence that is 48 identical messages a day")

    def test_a_send_that_never_arrived_buys_nothing(self):
        self.once(self.finding(), rc=1)
        self.once(self.finding())
        self.assertEqual(
            len(self.sent), 2,
            "a failed send started the silence, so the next hours are quiet and "
            "nobody was ever told. That is three months of a real outage in this "
            "repository's own history")

    def test_a_new_incident_speaks_through_the_silence(self):
        from datetime import timedelta
        self.once(self.finding())
        # INSIDE the backoff window, and genuinely different (another exit code). Since
        # stamps are blanked for failures, a new stamp alone is the same incident on
        # purpose; only a changed sentence is new news, and it must not wait.
        self.once(self.finding(detail="the midday run ended with 2 at 2026-08-24T13:40:00Z"),
                  now=self.at() + timedelta(hours=1))
        self.assertEqual(
            len(self.sent), 2,
            "the run failed DIFFERENTLY an hour later. A wall clock backoff alone "
            "would swallow the second failure as though it were the first one "
            "still standing")


class AnUnchangedFingerprintIsToldAtMostTwice(DispatchBase):
    """The scar named in the code, TWICE. A weekly job failed once, did not
    run again before its next scheduled appointment, and the identical
    sentence went out every 4h for two days (11 deliveries, streak=104 in the
    live state file) - through a thread where the recipient asked twice to
    stop repeating it and it kept going regardless.

    A first correction made the wait GROW instead of staying flat. It still
    fired again on schedule at the still-flat first doubling step, arrived
    right after the fix was reported done, and answered the wrong question:
    growing the wait says how annoying each repeat is, not how many times an
    already-acknowledged fact may be repeated at all. This one caps the
    COUNT: the original telling plus one reminder, then quiet until the
    fingerprint itself changes.
    """

    def base(self, day=24, hour=12):
        from datetime import datetime, timezone
        return datetime(2026, 8, day, hour, tzinfo=timezone.utc)

    def plus(self, hours):
        from datetime import timedelta
        return self.base() + timedelta(hours=hours)

    def test_the_first_two_deliveries_both_go_out(self):
        self.once(self.finding(), now=self.plus(0))
        self.once(self.finding(), now=self.plus(4))
        self.assertEqual(len(self.sent), 2,
                         "one reminder is still owed after the first telling; "
                         "a message that might have been missed deserves one "
                         "more chance to be seen")

    def test_a_third_identical_repeat_never_goes_out_no_matter_how_long_it_waits(self):
        self.once(self.finding(), now=self.plus(0))
        self.once(self.finding(), now=self.plus(4))
        for t in (8, 12, 100, 100 * 24):
            self.once(self.finding(), now=self.plus(t))
        self.assertEqual(
            len(self.sent), 2,
            "an unchanged, already-told fact kept arriving no matter how far "
            "out the wall clock ran; two tellings is the whole budget for one "
            "unresolved incident, not a slower drip that never actually ends")

    def test_a_different_fingerprint_gets_its_own_two_tellings(self):
        self.once(self.finding(), now=self.plus(0))
        self.once(self.finding(), now=self.plus(4))
        self.once(self.finding(), now=self.plus(8))  # capped out, held back
        self.assertEqual(len(self.sent), 2)
        self.once(self.finding(detail="a genuinely different failure"), now=self.plus(9))
        self.once(self.finding(detail="a genuinely different failure"), now=self.plus(13))
        self.assertEqual(
            len(self.sent), 4,
            "new information about the SAME appointment must not be held back "
            "by a DIFFERENT, already exhausted incident's cap")

    def test_state_recorded_before_this_field_existed_is_not_read_as_already_capped(self):
        # A live state file recorded before this change carries fingerprint/
        # last_alert_at/streak but no `repeats`. The transition pass must not
        # read that absence as "already told twice".
        import json
        self.once(self.finding(), now=self.plus(0))
        raw = json.loads(self.state.read_text(encoding="utf-8"))
        for entry in raw["keys"].values():
            entry.pop("repeats", None)
        self.state.write_text(json.dumps(raw), encoding="utf-8")

        self.once(self.finding(), now=self.plus(4))
        self.assertEqual(len(self.sent), 2,
                         "a migrated entry without `repeats` was treated as "
                         "already capped out and the honest second telling "
                         "never went out")


class AFailingRunThatKeepsRunningIsOneIncident(DispatchBase):
    """The scar of 2026-10-07. A run every five minutes failed with the same
    exit code all morning, and the alarm layer, passing every half hour, told
    the recipient the same two findings at 07:43, 08:13, 08:44 and 09:14.

    The sentence of a failed run carries the stamp of that run, so every new
    run made a new fingerprint: neither the backoff nor the two-tellings cap
    ever applied. A stamp is WHEN it failed, not WHAT failed. Same exit code on
    the same run is the same trouble, however often it runs again.
    """

    def detail(self, minute):
        return (f"the last run of inbox-runner ended with 75, and said so in its "
                f"own trace at 2026-10-07T05:{minute:02d}:05+00:00")

    def test_new_stamps_with_the_same_exit_code_are_told_once_per_backoff_not_every_pass(self):
        from datetime import datetime, timedelta, timezone
        t0 = datetime(2026, 10, 7, 5, 43, tzinfo=timezone.utc)
        for i in range(8):                       # 8 passes, half an hour apart
            self.once(self.finding(detail=self.detail(i * 5)),
                      now=t0 + timedelta(minutes=30 * i))
        self.assertEqual(
            len(self.sent), 1,
            "a run that fails again every five minutes read as NEW news at "
            "every pass because its stamp moved; the recipient got the same "
            "failure four times before nine o'clock")

    def test_over_a_whole_day_it_is_told_twice_and_then_never_again(self):
        from datetime import datetime, timedelta, timezone
        t0 = datetime(2026, 10, 7, 5, 43, tzinfo=timezone.utc)
        for i in range(30):                      # 15 hours of half-hourly passes
            self.once(self.finding(detail=self.detail(i % 60)),
                      now=t0 + timedelta(minutes=30 * i))
        self.assertEqual(len(self.sent), 2,
                         "the telling and one reminder, then quiet")

    def test_a_different_exit_code_is_still_new_news(self):
        from datetime import datetime, timedelta, timezone
        t0 = datetime(2026, 10, 7, 5, 43, tzinfo=timezone.utc)
        self.once(self.finding(detail=self.detail(0)), now=t0)
        self.once(self.finding(detail=self.detail(5)), now=t0 + timedelta(minutes=30))
        self.once(self.finding(detail=self.detail(10).replace("with 75", "with 1")),
                  now=t0 + timedelta(minutes=60))
        self.assertEqual(len(self.sent), 2,
                         "stripping the stamp must not hide a changed exit code")


class OneKeyPerAppointment(DispatchBase):
    """Two appointments under one declaration are two separate silences."""

    def test_the_morning_backoff_does_not_silence_the_midday_alarm(self):
        self.once(self.finding(appointment="morning"))
        self.once(self.finding(appointment="morning"), self.finding(appointment="midday"))
        self.assertEqual(
            len(self.sent), 2,
            "one key per declaration lets the morning alarm bury the midday one "
            "under its backoff, and the midday report is simply never missed")

    def test_the_same_appointment_twice_is_one_alarm(self):
        self.once(self.finding(appointment="morning"))
        self.once(self.finding(appointment="morning"))
        self.assertEqual(len(self.sent), 1)


class OnlyStoppedNeedsASecondLook(DispatchBase):
    """A written line does not get truer by being read twice.

    `stopped` is the exception: it reads `running is False` or a probe verdict,
    a LIVE measurement that flickers around a restart. Everything else here is
    a line somebody already wrote to disk, or an appointment that already has
    its grace built in upstream.
    """

    def test_a_failed_run_is_reported_on_the_very_first_pass(self):
        self.once(self.finding())
        self.assertEqual(
            len(self.sent), 1,
            "a blanket two-pass threshold doubles the latency of every real "
            "alarm and buys nothing for evidence that is already on disk")

    def test_a_stopped_daemon_needs_two_passes_in_a_row(self):
        w = load("watched-daemon")
        f = self.finding(state=model.WorkloadState.stopped, wid=w.id, appointment="")
        self.once(f, workloads=[w])
        self.assertEqual(self.sent, [], "one live reading is a flicker, not an outage")
        self.once(f, workloads=[w])
        self.assertEqual(len(self.sent), 1, "two in a row is the outage")


class AnAlarmThatWasToldIsAlsoToldWhenItEnds(DispatchBase):
    """2026-10-07: a puller failed for hours, the alarm arrived mid-way, and the
    all-clear never did. The reader had to open the workloads page to learn the
    trouble was gone."""

    def test_a_delivered_alarm_that_resolves_sends_one_all_clear(self):
        self.once(self.finding())
        self.once()
        self.assertEqual(len(self.sent), 2, "alarm, then all-clear")
        self.assertIn("recovered", self.sent[1]["what"])
        self.assertIn("midday", self.sent[1]["detail"])
        self.assertIn("ended with 1", self.sent[1]["detail"],
                      "the all-clear names what was wrong, so it can be matched to the alarm")

    def test_the_all_clear_names_the_alarm_exactly(self):
        """The inbox closes the alarm's item by a key made of the alarm's title, so the
        all-clear must carry that title verbatim behind a fixed prefix."""
        self.once(self.finding())
        self.once()
        self.assertEqual(self.sent[1]["what"], notify.RECOVERED_PREFIX + self.sent[0]["what"])
        self.assertEqual(self.sent[1]["where"], self.sent[0]["where"])

    def test_two_alarms_end_as_two_all_clears(self):
        self.once(self.finding(appointment="morning"))
        self.once(self.finding(appointment="morning"),
                  self.finding(appointment="midday", detail="midday broke differently"),
                  now=self.at(hour=18))
        self.once(now=self.at(hour=19))
        clears = [s for s in self.sent if s["what"].startswith(notify.RECOVERED_PREFIX)]
        self.assertEqual(sorted(c["what"] for c in clears),
                         sorted(notify.RECOVERED_PREFIX + s["what"] for s in self.sent
                                if not s["what"].startswith(notify.RECOVERED_PREFIX)))

    def test_only_the_titles_not_yet_cleared_are_retried(self):
        self.once(self.finding(appointment="morning"))
        self.once(self.finding(appointment="morning"),
                  self.finding(appointment="midday", detail="midday broke differently"),
                  now=self.at(hour=18))
        calls = []

        def flaky(**kw):
            calls.append(kw)
            ok = len(calls) == 1                      # first all-clear arrives, second does not
            return notify.Sent(ok, "" if ok else "exit 1")
        notify.dispatch(self.rep(), [load("twice-daily-report")], state_path=self.state,
                        now=self.at(hour=19), sender=flaky)
        self.sent.clear()
        self.once(now=self.at(hour=20))
        self.assertEqual(self.sent, [], "a failed all-clear waits for the backoff")
        self.once(now=self.at(hour=19 + notify.BACKOFF_HOURS))
        self.assertEqual([s["what"] for s in self.sent], [calls[1]["what"]],
                         "the title already cleared must not be cleared twice")

    def test_the_all_clear_is_sent_once(self):
        self.once(self.finding())
        self.once()
        self.once()
        self.assertEqual(len(self.sent), 2)

    def test_an_alarm_that_never_arrived_has_no_all_clear(self):
        self.once(self.finding(), rc=1)
        self.once()
        self.assertEqual(len(self.sent), 1, "only the failed attempt, nothing to retract")

    def test_a_finding_that_was_never_alarmed_has_no_all_clear(self):
        w = load("watched-daemon")
        f = self.finding(state=model.WorkloadState.stopped, wid=w.id, appointment="")
        self.once(f, workloads=[w])          # first pass: still waiting for a second look
        self.once(workloads=[w])
        self.assertEqual(self.sent, [])

    def test_an_unreachable_pass_is_not_an_all_clear(self):
        self.once(self.finding())
        self.once(self.finding(state=model.WorkloadState.unknown, detail="host-a did not answer"))
        self.assertEqual(len(self.sent), 1)

    def test_an_all_clear_that_did_not_arrive_is_tried_again_after_the_backoff(self):
        self.once(self.finding())
        self.once(rc=1, now=self.at(hour=13))
        self.once(now=self.at(hour=14))
        self.assertEqual(len(self.sent), 2, "a failed all-clear is not retried every pass")
        self.once(now=self.at(hour=13 + notify.BACKOFF_HOURS))
        self.assertEqual([s["what"] for s in self.sent].count(self.sent[1]["what"]), 2)
        self.once(now=self.at(hour=23))
        self.assertEqual(len(self.sent), 3, "delivered on the retry, then quiet")

    def test_no_all_clear_while_another_run_under_the_same_title_still_fails(self):
        """Review 07.10.: a bundled alarm "X (a) and 1 more" covers a and b. a recovers while b
        still fails: the all-clear for that title would close its inbox item too early."""
        a = self.finding(appointment="morning")
        b = self.finding(appointment="midday", detail="midday broke too")
        self.once(a, b)
        self.once(b, now=self.at(hour=13))
        self.assertEqual(len(self.sent), 1, "b still carries the title, nothing has ended")
        self.once(now=self.at(hour=14))
        self.assertEqual(len(self.sent), 2)
        self.assertEqual(self.sent[1]["what"], notify.RECOVERED_PREFIX + self.sent[0]["what"])

    def test_an_all_clear_counts_against_the_daily_cap(self):
        for i in range(notify.DAILY_CAP - 1):
            self.once(self.finding(appointment=f"a{i}", detail=f"d{i}"), now=self.at(hour=8 + i))
        self.once(now=self.at(hour=8 + notify.DAILY_CAP))
        delivered = len(self.sent)
        self.assertLessEqual(delivered, notify.DAILY_CAP, "all-clears must not double the day's messages")


class UnknownNeitherStartsNorEndsAnEpisode(DispatchBase):
    """An unreachable host is not news, and it is not recovery either."""

    def test_an_unreachable_pass_does_not_reopen_a_settled_alarm(self):
        self.once(self.finding())
        self.once(self.finding(state=model.WorkloadState.unknown,
                              detail="host-a did not answer"))
        self.once(self.finding())
        self.assertEqual(
            len(self.sent), 2 - 1,
            "the host being away for one pass counted as recovery, so the same "
            "unchanged trouble was announced a second time as though it were new")


class TheDailyCapCountsWhatArrived(DispatchBase):
    """Measured in this repository: sent=8, suppressed=72, delivered 0."""

    def test_undelivered_attempts_do_not_use_up_the_day(self):
        for i in range(8):
            self.once(self.finding(detail=f"failure number {i}"), rc=1)
        self.once(self.finding(detail="the real one"))
        self.assertEqual(
            len(self.sent), 9,
            "a cap on INTENTIONS was exhausted after eleven runs while nothing "
            "had actually gone out, and silenced every real alarm on the machine "
            "for the rest of that day")

    def test_the_cap_is_a_day_and_not_a_lifetime(self):
        for i in range(8):
            self.once(self.finding(detail=f"trouble {i}"))
        before = len(self.sent)
        self.once(self.finding(detail="a new day"), now=self.at(day=25))
        self.assertGreater(
            len(self.sent), before,
            "without a day boundary the first bad day is the last day this ever "
            "spoke, and nobody notices because silence is its normal state")

    def test_the_cap_stops_at_the_number_it_names(self):
        """The half the neighbouring test does not measure.

        Checking only that the LAST message announces the suppression leaves
        the ceiling itself unmeasured: with no ceiling at all, every further
        message still carries the announcement, and the test stays green while
        the phone keeps ringing. A mutation found exactly that.
        """
        for i in range(notify.DAILY_CAP + 3):
            self.once(self.finding(detail=f"trouble {i}"))
        self.assertEqual(
            len(self.sent), notify.DAILY_CAP,
            f"the cap says {notify.DAILY_CAP} and {len(self.sent)} went out. A "
            f"runaway pass empties a phone, and the reader turns the channel "
            f"off, which is worse than never having sent anything")

    def test_the_message_that_uses_up_the_day_says_so(self):
        said = []
        for i in range(9):
            out = self.once(self.finding(detail=f"trouble {i}"))
            said.append(out)
        last = [c for c in self.sent][-1]
        self.assertIn(
            "suppress", " ".join(str(v) for v in last.values()).lower(),
            "a cap reached reads exactly like nothing being wrong. The difference "
            "between `there was nothing` and `I have stopped telling you` is the "
            "whole reason this layer exists")


class AStateFileThatWasNeverThereOrIsBroken(DispatchBase):

    def test_a_first_pass_without_any_state_delivers_and_writes_one(self):
        self.once(self.finding())
        self.assertEqual(len(self.sent), 1,
                         "a first pass that stays quiet out of caution swallows "
                         "the very finding that triggered it")
        self.assertTrue(self.state.exists(), "nothing was remembered for next time")
        import json
        json.loads(self.state.read_text(encoding="utf-8"))

    def test_a_broken_state_file_is_not_silent_amnesia(self):
        self.state.write_text('{"half": ', encoding="utf-8")
        out = self.once(self.finding())
        self.assertEqual(len(self.sent), 1, "it crashed instead of reporting")
        import json
        json.loads(self.state.read_text(encoding="utf-8"))
        self.assertIn(
            "state", (getattr(out, "note", "") or "").lower(),
            "a torn write resets every counter at once and the next pass "
            "re-announces everything already settled. Without a visible note "
            "that storm reads like a real multi-incident")


# ── what the message SAYS: 2026-10-13, read on a phone ───────────────────────
#
# Three alarms arrived that day titled with nothing but a self-update job's
# name, with "ended with 143, and said so in its own trace at
# 2026-10-13T02:59:51+00:00" underneath. The run had been cut off by its own
# time limit at 04:59 local time; nothing in the message said so. Another
# arrived as "<job> (afternoon) and 6 more". The title named a job, never the
# trouble.

def failed(wid="twice-daily-report", appointment="midday", rc=143, verdict="expired",
           duration_sec=2686, at="2026-10-13T02:59:51Z", hint="read the unit's log"):
    return report_mod.Finding(
        workload_id=wid, state=model.WorkloadState.last_run_failed,
        severity=model.Severity.high,
        detail=f"the last run of {wid} ended with {rc}, and said so in its own trace at {at}",
        hint=hint, source="machine", appointment=appointment,
        rc=rc, verdict=verdict, duration_sec=duration_sec, at=at)


def wl(wid="tool-update", title="tool self update", tz="Europe/Berlin", hint=None):
    return SimpleNamespace(
        id=wid, title=title,
        placement=SimpleNamespace(host="host-a", kind="recurring"),
        schedule=SimpleNamespace(timezone=tz),
        reconcile=SimpleNamespace(hint=hint))


CUSTOM = {
    "title_many_failed": "{n} jobs broke",
    "weekdays": ["MO", "TU", "WE", "TH", "FR", "SA", "SU"],
    "after": " / {minutes}m",
    "problems": {"timed_out": "job cut off at its limit",
                 "failed": "job broke (code {rc})"},
    "recovered_prefix": "Back to normal: ",
    "recovered_todo": "Nothing to do.",
}


class TheTitleNamesTheTrouble(MachineGuard):

    def compose(self, *entries, text=None):
        return notify.compose(list(entries), text=notify.texts(
            SimpleNamespace(notify_text=text)))

    def test_an_unknown_placeholder_falls_back_to_the_default_text(self):
        # A typo in a configured sentence must not take the notify pass down.
        entries = [(failed(), wl(), "failure")]
        with self.assertLogs("engine.notify", level="WARNING"):
            got = self.compose(*entries, text={"title_one": "{nmae} broke"})
        self.assertEqual(got, notify.compose(entries, text=notify.texts(None)))

    def test_one_failed_run_says_what_went_wrong_in_the_title(self):
        what, _where, _todo, _detail = self.compose(
            (failed(appointment=""), wl(), "failure"))
        self.assertEqual(what, "tool self update: run cut off, time limit exceeded")

    def test_the_appointment_stays_in_the_title(self):
        what, *_ = self.compose((failed(), wl(), "failure"))
        self.assertEqual(what, "tool self update (midday): run cut off, time limit exceeded")

    def test_the_moment_is_local_time_and_never_iso_utc(self):
        _what, _where, _todo, detail = self.compose((failed(), wl(), "failure"))
        self.assertIn("Tue 13.10. 04:59", detail)
        self.assertNotIn("2026-10-13T", detail)

    def test_the_duration_of_a_cut_off_run_is_named(self):
        _what, _where, _todo, detail = self.compose((failed(), wl(), "failure"))
        self.assertIn("after 44 min", detail)

    def test_every_exit_code_that_has_a_meaning_gets_it(self):
        cases = {(137, "failed"): "run killed",
                 (75, "failed"): "network or temporary failure",
                 (127, "failed"): "program not found",
                 (126, "failed"): "program not executable",
                 (1, "failed"): "run failed (exit 1)",
                 (143, "failed"): "run cut off, time limit exceeded"}
        for (rc, verdict), said in cases.items():
            what, *_ = self.compose(
                (failed(appointment="", rc=rc, verdict=verdict, duration_sec=7), wl(), "failure"))
            self.assertEqual(what, f"tool self update: {said}", (rc, verdict))

    def test_several_runs_are_counted_in_the_title_and_listed_one_per_line(self):
        what, _where, _todo, detail = self.compose(
            (failed(wid="a", appointment="", rc=1, verdict="failed"), wl("a", "Run A"), "failure"),
            (failed(wid="b", appointment="", rc=1, verdict="failed"), wl("b", "Run B"), "failure"))
        self.assertEqual(what, "2 runs failed")
        self.assertNotIn("more", what)
        lines = [x for x in detail.splitlines() if x.strip()]
        self.assertTrue(any(x.startswith("Run A: run failed (exit 1)") for x in lines), lines)
        self.assertTrue(any(x.startswith("Run B: run failed (exit 1)") for x in lines), lines)

    def test_a_mix_of_verdicts_is_not_called_failed(self):
        missing = report_mod.Finding(
            workload_id="b", state=model.WorkloadState.overdue, severity=model.Severity.high,
            detail="b was due", hint="h", source="machine")
        what, *_ = self.compose(
            (failed(wid="a", appointment=""), wl("a", "Run A"), "failure"),
            (missing, wl("b", "Run B"), "missing"))
        self.assertEqual(what, "2 runs need attention")

    def test_the_declared_hint_beats_the_machine_sentence(self):
        _what, _where, todo, _detail = self.compose(
            (failed(), wl(hint="tail ~/Library/Logs/tool-update.log"), "failure"))
        self.assertEqual(todo, "tail ~/Library/Logs/tool-update.log")

    def test_without_a_declared_hint_the_finding_hint_is_kept(self):
        _what, _where, todo, _detail = self.compose((failed(), wl(), "failure"))
        self.assertEqual(todo, "read the unit's log")

    def test_a_configured_todo_per_problem_beats_the_machine_sentence(self):
        _what, _where, todo, _detail = self.compose(
            (failed(rc=1, verdict="failed"), wl(), "failure"),
            text={"todos": {"failed": "open the run's output first"}})
        self.assertEqual(todo, "open the run's output first")

    def test_the_declared_hint_still_beats_a_configured_todo(self):
        _what, _where, todo, _detail = self.compose(
            (failed(rc=1, verdict="failed"), wl(hint="declared"), "failure"),
            text={"todos": {"failed": "configured"}})
        self.assertEqual(todo, "declared")

    def test_a_finding_without_run_facts_keeps_its_own_sentence(self):
        bare = report_mod.Finding(
            workload_id="tool-update", state=model.WorkloadState.last_run_failed,
            severity=model.Severity.high, detail="the run ended with 9 somewhere",
            hint="h", source="machine")
        what, _where, _todo, detail = self.compose((bare, wl(), "failure"))
        self.assertEqual(what, "tool self update: run failed")
        self.assertIn("the run ended with 9 somewhere", detail)

    def test_the_words_come_from_configuration(self):
        what, _where, _todo, detail = self.compose(
            (failed(), wl(), "failure"), text=CUSTOM)
        self.assertEqual(what, "tool self update (midday): job cut off at its limit")
        self.assertIn("TU 13.10. 04:59", detail)
        self.assertIn("/ 44m", detail)

    def test_configured_words_merge_over_the_defaults(self):
        what, *_ = self.compose((failed(appointment="", rc=127, verdict="failed"), wl(), "failure"),
                                text=CUSTOM)
        self.assertEqual(what, "tool self update: program not found",
                         "a problem the configuration does not name falls back to the default, "
                         "never to an empty title")

    def test_the_skill_ships_english_defaults_only(self):
        source = (SKILL_DIR / "engine" / "notify.py").read_text(encoding="utf-8")
        for word in CUSTOM["problems"].values():
            self.assertNotIn(word.split(" (")[0], source,
                             "an instance's words belong in its bridge-config.yaml")


class TheAllClearSpeaksTheConfiguredWords(DispatchBase):

    def test_the_all_clear_uses_the_configured_prefix_and_todo(self):
        cfg = SimpleNamespace(notify_via=None, notify_text=CUSTOM)
        notify.dispatch(self.rep(failed()), [load("twice-daily-report")], state_path=self.state,
                        now=self.at(), cfg=cfg, sender=self.sender())
        notify.dispatch(self.rep(), [load("twice-daily-report")], state_path=self.state,
                        now=self.at(hour=13), cfg=cfg, sender=self.sender())
        self.assertEqual(len(self.sent), 2)
        self.assertEqual(self.sent[1]["what"], "Back to normal: " + self.sent[0]["what"])
        self.assertEqual(self.sent[1]["todo"], "Nothing to do.")
        self.assertIn("job cut off at its limit", self.sent[1]["detail"],
                      "the all-clear names what was wrong in the same words as the alarm")


class AProbeDisagreementWaitsForTheRunThatShouldFixIt(DispatchBase):
    """2026-10-13 02:11: a new release of a tool appeared, the probe ("installed equals
    newest tag") said no, and an alarm went out. The run that installs releases
    was due at 04:15. For a run that is not supposed to be running between its
    firings, `stopped` can only come from its probe, and a probe disagreeing
    BEFORE the next firing is the world moving, not the run failing."""

    def stopped(self):
        return report_mod.Finding(
            workload_id="twice-daily-report", state=model.WorkloadState.stopped,
            severity=model.Severity.high, detail="its probe says otherwise",
            hint="h", source="machine")

    def pass_(self, now, runs=None):
        rep = report_mod.Report(findings=[self.stopped()], header="h", runs=runs or {})
        notify.dispatch(rep, [load("twice-daily-report")], state_path=self.state,
                        now=now, sender=self.sender())

    def test_no_alarm_while_no_run_has_happened_since_it_was_first_seen(self):
        old = {"twice-daily-report": ("2026-08-23T04:15:00Z", 0)}
        for hour in (12, 13, 14, 15):
            self.pass_(self.at(hour=hour), runs=old)
        self.assertEqual(self.sent, [])

    def test_the_alarm_comes_once_a_run_after_first_sight_left_it_wrong(self):
        self.pass_(self.at(hour=12), runs={"twice-daily-report": ("2026-08-23T04:15:00Z", 0)})
        self.pass_(self.at(hour=13), runs={"twice-daily-report": ("2026-08-23T04:15:00Z", 0)})
        self.pass_(self.at(hour=14), runs={"twice-daily-report": ("2026-08-24T13:30:00Z", 0)})
        self.assertEqual(len(self.sent), 1)

    def test_a_continuous_run_is_not_held_back(self):
        w = load("watched-daemon")
        f = dataclasses.replace(self.stopped(), workload_id=w.id)
        for hour in (12, 13):
            notify.dispatch(report_mod.Report(findings=[f], header="h", runs={}), [w],
                            state_path=self.state, now=self.at(hour=hour), sender=self.sender())
        self.assertEqual(len(self.sent), 1, "a daemon that is down is down now")


if __name__ == "__main__":
    unittest.main()
