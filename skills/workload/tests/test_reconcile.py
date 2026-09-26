"""reconcile: is it still there, asked of three sources and never of a status field.

classify() is pure, so the whole state machine is provable without a machine.
The two verdicts that matter most are retired_but_live (the loudest) and unknown
(which must never collapse into absent: that collapse is how seventeen jobs were
once wrongly declared overdue).
"""

from __future__ import annotations

import dataclasses
import json
import shlex
import unittest
from unittest import mock

from tests.conftest import (
    CORPUS,
    DERIVED,
    FIXTURE_HOME,
    FIXTURE_TZ,
    FIXTURE_UID,
    FakeCompleted,
    FakeHost,
    MachineGuard,
    RecordingRunner,
    SKILL_DIR,
    completed_from,
    declared_digest,
    make_repo,
    marker_digest_in,
    mod,
    read_output,
    stamp_json,
)

model = mod("engine.model")
errors = mod("engine.errors")
render_mod = mod("engine.render")
base = mod("engine.backends.base")
reconcile = mod("engine.reconcile")
probe = mod("engine.probe")
inventory = mod("engine.inventory")
source = mod("engine.source")
stamp_mod = mod("engine.stamp")
report_mod = mod("engine.report")
config = mod("engine.config")

def _utc_now_stamp() -> str:
    """Now, in the exact shape the guard script writes. UTC, never local."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64


class ReconcileBase(MachineGuard):

    def ctx(self, **overrides):
        kwargs = dict(uid=FIXTURE_UID, home=FIXTURE_HOME,
                      stamp_dir=f"{FIXTURE_HOME}/.bridge/workloads",
                      dispatcher_registry=None, host_timezone=FIXTURE_TZ)
        kwargs.update(overrides)
        return base.RenderContext(**kwargs)

    def host(self, slug="host-a"):
        return FakeHost.from_fixture(slug)

    def load(self, name):
        for folder in (CORPUS, DERIVED):
            path = folder / f"{name}.yaml"
            if path.exists():
                return model.load_declaration(path)
        raise AssertionError(name)

    def live(self, unit_ref, **overrides):
        # marker_observed defaults to True because a LiveUnit built here stands
        # for what the machine ANSWERED. A test that means "nobody ever looked"
        # says so by passing marker_observed=False, and that difference is the
        # whole point of the field: without it, "read and absent" and "never
        # read" are one value and every conclusion drawn from the marker is a
        # guess. See TheMarkerIsNeverInferredFromNotLooking.
        fields = dict(
            runtime="launchd",
            unit_ref=unit_ref,
            path=f"{FIXTURE_HOME}/Library/LaunchAgents/{unit_ref.rsplit('/', 1)[-1]}.plist",
            marker_id=None,
            marker_digest=None,
            marker_observed=True,
            enabled=True,
            running=True,
            raw="",
        )
        fields.update(overrides)
        # A unit's marker names a declaration; its digest therefore belongs to
        # that declaration. Setting both by hand to one placeholder describes a
        # machine that cannot exist, and hid the fact that nothing compared the
        # value against the file. A test that MEANS drift passes a digest of its
        # own, which is what DIGEST_B is for.
        if fields.get("marker_id") and "marker_digest" not in overrides:
            fields["marker_digest"] = declared_digest(fields["marker_id"],
                                                      default=DIGEST_A)
        return reconcile.LiveUnit(**fields)

    def stamp(self, workload_id, **overrides):
        fields = dict(
            stamp_version=1,
            workload_id=workload_id,
            host="host-a",
            declaration=f"workflow/workloads/{workload_id}.yaml",
            # Derived, not pinned: this stamp claims THIS declaration, and a
            # placeholder here made a stamp from a different file look identical.
            declaration_digest=declared_digest(workload_id, default=DIGEST_A),
            artifact_digest=DIGEST_A,
            runtime="launchd",
            unit_ref=f"gui/{FIXTURE_UID}/bridge.{workload_id}",
            files=(f"{FIXTURE_HOME}/Library/LaunchAgents/bridge.{workload_id}.plist",),
            provisioned_at="2026-08-22T10:00:00+02:00",
            adopted=False,
            retired=None,
        )
        fields.update(overrides)
        return stamp_mod.Stamp(**fields)

    def host_obs(self, units=(), stamps=None, reachable=True, error=None,
                 failed_runtimes=frozenset(), disabled=None):
        return reconcile.HostObservation(
            host="host-a", reachable=reachable, error=error,
            live_units=tuple(units), stamps=dict(stamps or {}),
            failed_runtimes=frozenset(failed_runtimes),
            disabled=dict(disabled or {}))

    def inv(self, slug="host-a"):
        return inventory.load_inventory(FakeHost.from_fixture(slug))

    def states_for(self, findings, workload_id):
        return {f.state for f in findings if f.workload_id == workload_id}

    def only_state(self, findings, workload_id):
        states = self.states_for(findings, workload_id)
        self.assertEqual(len(states), 1, f"{workload_id} produced {states}")
        return next(iter(states))


#: States no scenario in `TheThirteenStates` can reach, and the class that
#: covers each instead. `classify` is pure over one machine's answers;
#: `source_drift` compares the machine against the REPOSITORY, which is a
#: second place and therefore a second reader.
OUTSIDE_CLASSIFY = {
    model.WorkloadState.source_drift: "TheProgramMayNotBeTheOneThatIsKept",
}


class TheThirteenStates(ReconcileBase):
    """Every member of the closed enum, driven by a scenario that produces it.

    Fifteen since the trace is read back. The name stays: renaming it on every
    growth would break every reference to it, and the count lives in the
    assertion, not in the title.
    """

    def scenarios(self):
        st = model.WorkloadState
        wid = "block-style-report"
        w = self.load(wid)
        unit = f"gui/{FIXTURE_UID}/bridge.{wid}"
        stamped = self.stamp(wid)
        provisioned = self.load("calendar-export")

        return [
            ("in_sync", st.in_sync, [w],
             self.host_obs([self.live(unit, marker_id=wid)],
                           {wid: stamped}), wid),
            ("not_provisioned", st.not_provisioned, [w], self.host_obs(), wid),
            ("absent", st.absent, [w],
             self.host_obs(stamps={wid: stamped}), wid),
            # A DAEMON, deliberately: only a kind that is supposed to be running
            # can be stopped. A cadence run is idle between firings, and this
            # scenario used to reach `stopped` through a recurring declaration,
            # which is the very confusion OnlyAThingThatShouldBeRunningCanBeStopped
            # exists for.
            ("stopped", st.stopped, [self.load("elevated-daemon")],
             self.host_obs([self.live("system/bridge.elevated-daemon",
                                      marker_id="elevated-daemon",
                                      running=False,
                                      runtime="launchd-system")],
                           {"elevated-daemon": self.stamp(
                               "elevated-daemon",
                               unit_ref="system/bridge.elevated-daemon",
                               runtime="launchd-system")}), "elevated-daemon"),
            ("drifted", st.drifted, [w],
             self.host_obs([self.live(unit, marker_id=wid, marker_digest=DIGEST_B)],
                           {wid: stamped}), wid),
            ("unstamped", st.unstamped, [w],
             self.host_obs([self.live(unit)]), wid),
            ("retired_but_live", st.retired_but_live, [self.load("voice-channel")],
             self.host_obs([self.live(f"gui/{FIXTURE_UID}/bridge.voice-channel",
                                      marker_id="voice-channel")]), "voice-channel"),
            ("observed", st.observed, [self.load("chat-channel")], self.host_obs(),
             "chat-channel"),
            ("unknown", st.unknown, [w],
             self.host_obs(reachable=False, error="ssh: connect timed out"), wid),
            ("orphan_stamp", st.orphan_stamp, [],
             self.host_obs(stamps={"long-gone": self.stamp("long-gone")}), "long-gone"),
            ("unmanaged", st.unmanaged, [],
             self.host_obs([self.live("gui/4242/com.example.mesh")]), "com.example.mesh"),
            ("inventory_missing", st.inventory_missing, [w],
             self.host_obs([self.live(unit, marker_id=wid)],
                           {wid: stamped}), wid),
            ("inventory_stale", st.inventory_stale, [], self.host_obs(), "stale-entry"),
            # The same file, the other answer: this entry names nothing either
            # and says so itself, with a date and a reason.
            ("intentionally_absent", st.intentionally_absent, [], self.host_obs(),
             "parked-on-purpose"),
            # Bytes perfect, and the machine will still not start it. This is
            # the one verdict that is invisible in everything else the report
            # reads: the unit is there, the marker is there, the digests match.
            ("disabled", st.disabled, [w],
             self.host_obs([self.live(unit, marker_id=wid)], {wid: stamped},
                           disabled={unit: True}), wid),
            # The two the trace brought. Both need a live, stamped unit AND a
            # trace, because a unit that is not there is never told about its
            # cadence.
            ("last_run_failed", st.last_run_failed, [provisioned],
             self.traced_obs("calendar-export", rc=1), "calendar-export"),
            ("overdue", st.overdue, [provisioned],
             # Days back, in UTC: the trace stamp is UTC and the comparison
             # happens in UTC, and a local-time value here would sit in the
             # future for two hours every summer and quietly never fire.
             self.traced_obs("calendar-export", rc=0,
                             when="2026-01-01T00:00:00Z"), "calendar-export"),
            # The sixteenth, and the only one whose evidence is a comparison of
            # two records rather than a reading of one: the declaration says
            # where the program is, the stamp says where it was when a human
            # last answered a prompt about it.
            ("grant_orphaned", st.grant_orphaned, [self.granted("/opt/bridge/bin/neu")],
             self.host_obs([self.live(f"gui/{FIXTURE_UID}/bridge.calendar-export",
                                      marker_id="calendar-export")],
                           {"calendar-export": self.stamp(
                               "calendar-export",
                               interpreter="/opt/bridge/bin/alt")}), "calendar-export"),
        ]

    def granted(self, interpreter, grants=("full-disk-access",)):
        """calendar-export, re-pointed at another client path."""
        w = self.load("calendar-export")
        object.__setattr__(w.placement, "interpreter", interpreter)
        object.__setattr__(w.placement, "privacy_grants", tuple(grants))
        return w

    def traced_obs(self, wid, *, rc=0, when=None):
        when = when or _utc_now_stamp()
        unit = self.live(f"gui/{FIXTURE_UID}/bridge.{wid}", marker_id=wid)
        obs = self.host_obs([unit], {wid: self.stamp(wid)})
        line = f"{when} workload={wid} rc={rc} duration_sec=1 verdict=ok\n"
        return dataclasses.replace(obs, traces={wid: line})

    def test_each_scenario_lands_on_its_state(self):
        inv = self.inv()
        seen = set()
        for name, expected, workloads, obs, subject in self.scenarios():
            with self.subTest(state=name):
                findings = reconcile.classify(workloads, obs, inv, {})
                states = self.states_for(findings, subject)
                self.assertIn(expected, states, f"{subject} produced {states}")
                seen.add(expected)
        self.assertEqual(seen, set(model.WorkloadState) - set(OUTSIDE_CLASSIFY),
                         "the enum grew without a scenario, which is how a state stops "
                         "being tested while still being reported")

    def test_what_no_scenario_can_reach_is_named_and_covered_elsewhere(self):
        """The exception to the rule above, spelled out rather than implied.

        `classify` is pure over what one machine answered. One state cannot be
        produced there because its second side is the REPOSITORY, and a rule
        that quietly tolerated such a state would tolerate the next one too.
        So the exception is a list, each entry names the class that covers it,
        and that name is resolved here: a pointer nobody follows rots.
        """
        import sys

        self.assertTrue(OUTSIDE_CLASSIFY, "an empty exception list is not an exception")
        for state, covered_by in OUTSIDE_CLASSIFY.items():
            with self.subTest(state=state.value):
                self.assertTrue(
                    hasattr(sys.modules[__name__], covered_by),
                    f"{state.value} points at {covered_by}, which does not exist")

    def test_the_severities_match_the_contract(self):
        st, sev = model.WorkloadState, model.Severity
        expected = {
            st.in_sync: sev.info,
            st.not_provisioned: sev.info,
            st.absent: sev.high,
            st.stopped: sev.high,
            st.drifted: sev.medium,
            st.unstamped: sev.high,
            st.retired_but_live: sev.high,
            st.observed: sev.info,
            st.unknown: sev.medium,
            st.orphan_stamp: sev.medium,
            st.unmanaged: sev.info,
            st.inventory_missing: sev.medium,
            st.inventory_stale: sev.info,
            # Info, and it must never be more: a decision that was written down
            # is the one thing on this page that needs nobody.
            st.intentionally_absent: sev.info,
            # Medium: it needs a person, and it is not high because nothing has
            # failed. Something was switched off and the file still says it
            # runs, which is a disagreement rather than an incident.
            st.disabled: sev.medium,
            # Both high: a run that ended non zero and a run that never came are
            # the two things the whole trace exists to surface.
            st.last_run_failed: sev.high,
            st.overdue: sev.high,
            # High as well, and for a harder reason than the other two: this one
            # produces no error anywhere. A client with no grant is not denied,
            # it is shown nothing, so the run exits zero on an empty result.
            st.grant_orphaned: sev.high,
        }
        inv = self.inv()
        for name, state, workloads, obs, subject in self.scenarios():
            with self.subTest(state=name):
                findings = [f for f in reconcile.classify(workloads, obs, inv, {})
                            if f.workload_id == subject and f.state == state]
                self.assertTrue(findings)
                self.assertEqual(findings[0].severity, expected[state])

    def test_every_finding_carries_a_repair_hint(self):
        inv = self.inv()
        for name, state, workloads, obs, subject in self.scenarios():
            if state in (model.WorkloadState.in_sync, model.WorkloadState.observed):
                continue
            with self.subTest(state=name):
                for f in reconcile.classify(workloads, obs, inv, {}):
                    if f.workload_id == subject and f.state == state:
                        self.assertTrue(f.hint, f"{state} says what is odd but not what to do")


class UnknownNeverCollapses(ReconcileBase):
    """An unreachable host means we do not know, which is not the same as gone."""

    def test_an_unreachable_host_yields_unknown_not_absent(self):
        w = self.load("block-style-report")
        obs = self.host_obs(reachable=False, error="ssh: connect timed out",
                            stamps={})
        findings = reconcile.classify([w], obs, self.inv(), {})
        states = self.states_for(findings, w.id)
        self.assertIn(model.WorkloadState.unknown, states)
        self.assertNotIn(model.WorkloadState.absent, states)
        self.assertNotIn(model.WorkloadState.not_provisioned, states)

    def test_the_reason_is_carried_into_the_finding(self):
        w = self.load("block-style-report")
        obs = self.host_obs(reachable=False, error="ssh: connect timed out")
        findings = [f for f in reconcile.classify([w], obs, self.inv(), {})
                    if f.workload_id == w.id]
        self.assertIn("timed out", " ".join(f.detail for f in findings))

    def test_an_unevaluatable_expect_yields_unknown(self):
        w = self.load("voice-channel")
        verdicts = {w.id: probe.Verdict.unknown}
        obs = self.host_obs()
        findings = reconcile.classify([w], obs, self.inv(), verdicts)
        self.assertIn(model.WorkloadState.unknown, self.states_for(findings, w.id))

    def test_a_failing_probe_is_not_the_same_as_a_missing_unit(self):
        w = self.load("block-style-report")
        obs = self.host_obs([self.live(f"gui/{FIXTURE_UID}/bridge.{w.id}",
                                       marker_id=w.id)],
                            {w.id: self.stamp(w.id)})
        findings = reconcile.classify([w], obs, self.inv(),
                                      {w.id: probe.Verdict.fail})
        states = self.states_for(findings, w.id)
        self.assertIn(model.WorkloadState.stopped, states)
        self.assertNotIn(model.WorkloadState.absent, states)


class TwoOwnershipSignals(ReconcileBase):
    """A stamp and a marker. Two blind procedures that can only agree prove nothing."""

    def test_a_stamp_without_a_marker_is_drift(self):
        w = self.load("block-style-report")
        obs = self.host_obs([self.live(f"gui/{FIXTURE_UID}/bridge.{w.id}")],
                            {w.id: self.stamp(w.id)})
        findings = reconcile.classify([w], obs, self.inv(), {})
        self.assertIn(model.WorkloadState.drifted, self.states_for(findings, w.id))
        self.assertIn("marker", " ".join(f.detail for f in findings
                                         if f.workload_id == w.id).lower())

    def test_a_marker_without_a_stamp_is_drift(self):
        w = self.load("block-style-report")
        obs = self.host_obs([self.live(f"gui/{FIXTURE_UID}/bridge.{w.id}",
                                       marker_id=w.id)])
        findings = reconcile.classify([w], obs, self.inv(), {})
        self.assertIn(model.WorkloadState.drifted, self.states_for(findings, w.id))
        self.assertIn("stamp", " ".join(f.detail for f in findings
                                        if f.workload_id == w.id).lower())

    def test_neither_signal_is_never_overwritten(self):
        w = self.load("block-style-report")
        obs = self.host_obs([self.live(f"gui/{FIXTURE_UID}/bridge.{w.id}")])
        findings = reconcile.classify([w], obs, self.inv(), {})
        self.assertIn(model.WorkloadState.unstamped, self.states_for(findings, w.id))


class DeclaredAndMissing(ReconcileBase):

    def test_declared_and_provisioned_but_gone(self):
        w = self.load("block-style-report")
        obs = self.host_obs(stamps={w.id: self.stamp(w.id)})
        findings = [f for f in reconcile.classify([w], obs, self.inv(), {})
                    if f.workload_id == w.id]
        self.assertEqual(self.only_state(findings, w.id), model.WorkloadState.absent)
        self.assertEqual(findings[0].severity, model.Severity.high)

    def test_declared_and_never_provisioned_is_only_information(self):
        w = self.load("block-style-report")
        findings = [f for f in reconcile.classify([w], self.host_obs(), self.inv(), {})
                    if f.workload_id == w.id]
        self.assertEqual(findings[0].state, model.WorkloadState.not_provisioned)
        self.assertEqual(findings[0].severity, model.Severity.info)


class LiveButNotDeclared(ReconcileBase):

    def test_an_undeclared_unit_is_counted_and_never_touched(self):
        obs = self.host_obs([self.live("gui/4242/com.example.mesh"),
                             self.live("gui/4242/com.example.other")])
        findings = reconcile.classify([], obs, self.inv(), {})
        unmanaged = [f for f in findings if f.state == model.WorkloadState.unmanaged]
        self.assertEqual(len(unmanaged), 2)
        for f in unmanaged:
            self.assertEqual(f.severity, model.Severity.info)

    def test_a_stamp_without_a_declaration_is_an_orphan(self):
        obs = self.host_obs(stamps={"long-gone": self.stamp("long-gone")})
        findings = reconcile.classify([], obs, self.inv(), {})
        self.assertIn(model.WorkloadState.orphan_stamp,
                      {f.state for f in findings})

    def test_a_foreign_owner_is_observed_not_unmanaged(self):
        w = self.load("public-funnel")
        findings = [f for f in reconcile.classify([w], self.host_obs(), self.inv(), {})
                    if f.workload_id == w.id]
        self.assertEqual(findings[0].state, model.WorkloadState.observed)


class ReconcileIsReadOnly(ReconcileBase):

    def test_no_step_in_the_read_path_changes_anything(self):
        runner = RecordingRunner()
        runner.add("list", completed_from("launchctl-list.txt"))
        runner.add("print-disabled", completed_from("launchctl-print-disabled.txt"))
        runner.add("cat", FakeCompleted(stdout=stamp_json()))
        root = make_repo(self.tmpdir())
        cfg = config.load_config(root)
        reconcile.observe_host(self.host(), cfg, timeout_sec=10, runner=runner)
        self.assert_no_mutation(runner)

    def test_an_unreachable_host_sets_the_flag_instead_of_raising(self):
        runner = RecordingRunner()
        runner.add("", raises=errors.StepTimeout(argv=("ssh",), timeout_sec=10,
                                                 partial_stdout="", partial_stderr=""))
        root = make_repo(self.tmpdir())
        cfg = config.load_config(root)
        obs = reconcile.observe_host(self.host("host-c"), cfg, timeout_sec=10, runner=runner)
        self.assertFalse(obs.reachable)
        self.assertTrue(obs.error)

    def test_one_dead_host_does_not_abort_the_whole_report(self):
        root = make_repo(self.tmpdir(),
                         declarations=("block-style-report", "linux-timer-report"))
        cfg = config.load_config(root)
        runner = RecordingRunner()
        runner.add("host-c", raises=errors.StepTimeout(argv=("ssh",), timeout_sec=10,
                                                       partial_stdout="", partial_stderr=""))
        runner.add("list", completed_from("launchctl-list.txt"))
        rep = reconcile.run(root, cfg, hosts=None, probe=False, timeout_sec=10, runner=runner)
        ids = {f.workload_id for f in rep.findings}
        self.assertIn("block-style-report", ids)
        self.assertIn("linux-timer-report", ids)

    def test_the_exit_code_is_one_when_anything_is_odd(self):
        st, sev = model.WorkloadState, model.Severity
        from tests.conftest import mod as _mod

        report = _mod("engine.report")
        rep = report.Report(findings=[
            report.Finding(workload_id="x", state=st.absent, severity=sev.high,
                           detail="gone", hint="provision it", source="machine")])
        self.assertEqual(rep.exit_code, 1)

    def test_unmanaged_units_are_only_listed_when_asked(self):
        obs = self.host_obs([self.live(f"gui/4242/com.example.{i}") for i in range(30)])
        findings = reconcile.classify([], obs, self.inv(), {})
        rendered = mod("engine.report").render_table(
            mod("engine.report").Report(findings=findings), verbose=False)
        self.assertNotIn("com.example.7", rendered,
                         "on a real box this is dozens of lines nobody reads")
        verbose = mod("engine.report").render_table(
            mod("engine.report").Report(findings=findings), verbose=True)
        self.assertIn("com.example.7", verbose)


class AReconcileReportSaysWhatItCovered(ReconcileBase):
    """A green that does not say what it looked at is a pass over an empty scan.

    `report._with_header` writes that rule down in prose and `validate` keeps it.
    `reconcile.run` returned `Report(findings=findings)` with no header at all,
    so a mistyped id answered `clean: nothing found that needs a hand` and exit 0
    over a tree holding seven live declarations: a typo read exactly like a
    healthy fleet. Nothing in this suite watched reconcile for it.
    """

    def _runner(self):
        runner = RecordingRunner()
        runner.add("list", completed_from("launchctl-list.txt"))
        runner.add("print-disabled", completed_from("launchctl-print-disabled.txt"))
        return runner

    def test_a_name_that_matches_nothing_never_reads_like_a_healthy_fleet(self):
        root = make_repo(self.tmpdir(),
                         declarations=("block-style-report", "linux-timer-report"))
        cfg = config.load_config(root)

        nothing = reconcile.run(root, cfg, ids=("no-such-workload",), probe=False,
                                timeout_sec=10, runner=self._runner())
        everything = reconcile.run(root, cfg, probe=False,
                                   timeout_sec=10, runner=self._runner())

        self.assertEqual(list(nothing.findings), [],
                         "the mistyped id has to reach the clean path, or this "
                         "test is measuring something else")
        empty = report_mod.render_table(nothing)
        full = report_mod.render_table(everything)

        self.assertNotEqual(
            empty.strip(), report_mod.CLEAN_LINE,
            "a mistyped id printed the clean line and nothing else, which is the "
            "same green two healthy declarations get")
        self.assertNotEqual(
            empty.splitlines()[0], full.splitlines()[0],
            "the coverage line has to be derived from the run: a constant says "
            "the same thing about nothing and about two declarations")
        self.assertIn("0 declaration", empty.splitlines()[0],
                      "the run over nothing has to say zero, in the first line")
        self.assertIn("2 declaration", full.splitlines()[0],
                      "the run over two has to say two, in the first line")


class TheTwoCurrenciesAreNeverCompared(ReconcileBase):
    """The marker and the stamp speak the same currency, or nothing works.

    The marker sits INSIDE the rendered file, so it can only ever carry the
    DECLARATION digest: the artifact digest covers the bytes the marker is part
    of, and a value cannot contain its own hash. Comparing the marker against
    the stamp's artifact digest made in_sync unreachable for every real
    declaration, and reconcile returned 1 forever with a repair hint that
    reproduced the same state.

    Everything below draws its comparison value out of the REAL rendered bytes
    instead of setting both sides to one constant.
    """

    def rendered(self, name, host="host-a"):
        w = self.load(name)
        return w, render_mod.render(w, self.host(host), self.ctx())

    def test_the_backends_write_the_declaration_digest_into_the_marker(self):
        for name, host in (("block-style-report", "host-a"),
                           ("linux-timer-report", "host-b"),
                           ("cron-cadence", "host-b")):
            with self.subTest(workload=name):
                w, artifact = self.rendered(name, host)
                self.assertEqual(marker_digest_in(artifact), model.declaration_digest(w))
                self.assertNotEqual(
                    marker_digest_in(artifact), artifact.digest,
                    "if these two were ever equal the marker would contain its own hash")

    def test_a_freshly_provisioned_run_reads_as_in_sync(self):
        provision = mod("engine.provision")
        wid = "block-style-report"
        w, artifact = self.rendered(wid)
        stamp = provision._stamp_for(w, self.host(), artifact, adopted=False)
        unit = self.live(artifact.unit_ref, marker_id=w.id,
                         marker_digest=marker_digest_in(artifact))
        findings = reconcile.classify([w], self.host_obs([unit], {wid: stamp}),
                                      self.inv(), {})
        states = self.states_for(findings, wid)
        self.assertIn(model.WorkloadState.in_sync, states,
                      f"a run that was just provisioned correctly produced {states}")
        self.assertNotIn(model.WorkloadState.drifted, states)

    def test_a_unit_made_from_another_declaration_still_reads_as_drift(self):
        provision = mod("engine.provision")
        wid = "block-style-report"
        w, artifact = self.rendered(wid)
        stamp = provision._stamp_for(w, self.host(), artifact, adopted=False)
        unit = self.live(artifact.unit_ref, marker_id=w.id, marker_digest=DIGEST_B)
        findings = reconcile.classify([w], self.host_obs([unit], {wid: stamp}),
                                      self.inv(), {})
        self.assertIn(model.WorkloadState.drifted, self.states_for(findings, wid))


class ProbeResolution(ReconcileBase):

    def test_the_declared_probe_wins(self):
        root = make_repo(self.tmpdir(), declarations=("daily-health-report",))
        cfg = config.load_config(root)
        w = self.load("daily-health-report")
        spec = probe.resolve_probe(w, self.host(), None, root, cfg)
        self.assertIn("launchctl print", spec.command)

    def test_a_qualified_check_ref_resolves(self):
        root = make_repo(self.tmpdir(), declarations=("checked-report",))
        cfg = config.load_config(root)
        w = self.load("checked-report")
        spec = probe.resolve_probe(w, self.host(), None, root, cfg)
        self.assertIn("curl", spec.command)

    def test_a_bare_check_id_in_two_groups_raises_instead_of_picking_one(self):
        root = make_repo(self.tmpdir(), declarations=("ambiguous-check-report",))
        cfg = config.load_config(root)
        w = self.load("ambiguous-check-report")
        with self.assertRaises(errors.CheckRefAmbiguous) as ctx:
            probe.resolve_probe(w, self.host(), None, root, cfg)
        self.assert_error(ctx, "check-ref-ambiguous", "sample", "storage")

    def test_without_either_the_backend_default_is_used(self):
        # `assertTrue(spec.command)` alone said only that SOMETHING came back. A
        # hardcoded answer in resolve_probe passed it, because a hardcoded answer
        # is also truthy. Which of the three sources answered is the whole
        # subject of this class, so the source is what is asserted, and the
        # command has to be the one the backend really supplies.
        root = make_repo(self.tmpdir(), declarations=("calendar-export",))
        cfg = config.load_config(root)
        w = self.load("calendar-export")
        host = self.host()
        artifact = render_mod.render(w, host, self.ctx())
        spec = probe.resolve_probe(w, host, artifact, root, cfg)

        self.assertEqual(spec.source, "backend-default",
                         f"the probe came from {spec.source!r}, not from the backend")
        backend = mod("engine.backends").get_backend(w.placement.runtime)
        expected = backend.default_probe(artifact, host)
        self.assertEqual(spec.command,
                         shlex.join(tuple(str(a) for a in expected.argv)),
                         "the command is not the one the backend supplies")
        self.assertIn(artifact.unit_ref, spec.command,
                      "the backend default has to ask about THIS unit")

    def test_an_unresolvable_probe_says_so_instead_of_inventing_one(self):
        # The control under the case above: with no artifact there is nothing to
        # derive a target from, and a manufactured command would read as a check.
        root = make_repo(self.tmpdir(), declarations=("calendar-export",))
        cfg = config.load_config(root)
        w = self.load("calendar-export")
        spec = probe.resolve_probe(w, self.host(), None, root, cfg)
        self.assertEqual(spec.source, "unresolved")
        self.assertEqual(spec.command, "")
        self.assertTrue(spec.reason, "an unresolved probe has to say why")


class WhatCannotBeEvaluated(ReconcileBase):

    def test_an_unresolved_placeholder_is_refused(self):
        w = self.load("public-funnel")
        spec = probe.ProbeSpec(command=w.reconcile.probe, expect=w.reconcile.expect,
                               source="declaration")
        ok, reason = probe.is_evaluatable(spec)
        self.assertFalse(ok)
        self.assertIn("<funnel>", reason)

    def test_a_placeholder_probe_is_never_executed(self):
        w = self.load("public-funnel")
        spec = probe.ProbeSpec(command=w.reconcile.probe, expect=w.reconcile.expect,
                               source="declaration")
        runner = RecordingRunner()
        done, verdict = probe.run_probe(spec, self.host(), timeout_sec=10, runner=runner)
        self.assertEqual(verdict, probe.Verdict.unknown)
        self.assertEqual(runner.calls, [],
                         "running it would resolve a literal hostname")

    def test_prose_instead_of_a_pattern_is_refused(self):
        w = self.load("voice-channel")
        spec = probe.ProbeSpec(command=w.reconcile.probe, expect=w.reconcile.expect,
                               source="declaration")
        ok, reason = probe.is_evaluatable(spec)
        self.assertFalse(ok, "evaluating prose is a coin flip dressed as a check")
        self.assertTrue(reason)

    def test_the_machine_readable_forms_are_all_evaluatable(self):
        for expect in ("state = running", "re:state = .*", "not:running", ">=1", "== 0"):
            with self.subTest(expect=expect):
                spec = probe.ProbeSpec(command="/bin/true", expect=expect, source="declaration")
                ok, reason = probe.is_evaluatable(spec)
                self.assertTrue(ok, f"{expect!r} was refused: {reason}")


class EvaluatingAProbe(ReconcileBase):

    def spec(self, expect):
        return probe.ProbeSpec(command="/bin/true", expect=expect, source="declaration")

    def test_plain_text_is_a_substring_after_whitespace_normalisation(self):
        done = FakeCompleted(rc=0, stdout="\tstate   =  running\n")
        self.assertEqual(probe.evaluate(self.spec("state = running"), done), probe.Verdict.pass_)

    def test_a_substring_that_is_absent_fails(self):
        done = FakeCompleted(rc=0, stdout="state = not running")
        self.assertEqual(probe.evaluate(self.spec("state = running"), done), probe.Verdict.fail)

    def test_the_regex_prefix(self):
        done = FakeCompleted(rc=0, stdout="pid = 5511")
        self.assertEqual(probe.evaluate(self.spec("re:pid = [0-9]+"), done), probe.Verdict.pass_)

    def test_the_negation_prefix(self):
        done = FakeCompleted(rc=0, stdout="everything is fine")
        self.assertEqual(probe.evaluate(self.spec("not:error"), done), probe.Verdict.pass_)
        done = FakeCompleted(rc=0, stdout="error: everything is not fine")
        self.assertEqual(probe.evaluate(self.spec("not:error"), done), probe.Verdict.fail)

    def test_the_numeric_operators(self):
        cases = [(">=20", "42", probe.Verdict.pass_), (">=20", "3", probe.Verdict.fail),
                 ("<90", "12", probe.Verdict.pass_), ("==0", "0", probe.Verdict.pass_),
                 ("!=0", "0", probe.Verdict.fail)]
        for expect, out, want in cases:
            with self.subTest(expect=expect, out=out):
                self.assertEqual(probe.evaluate(self.spec(expect),
                                                FakeCompleted(rc=0, stdout=out + "\n")), want)

    def test_a_non_numeric_answer_to_a_numeric_expect_is_unknown_not_fail(self):
        done = FakeCompleted(rc=0, stdout="no such file\n")
        self.assertEqual(probe.evaluate(self.spec(">=20"), done), probe.Verdict.unknown)

    def test_no_output_at_all_is_never_a_pass(self):
        done = FakeCompleted(rc=0, stdout="")
        self.assertNotEqual(probe.evaluate(self.spec("state = running"), done),
                            probe.Verdict.pass_)

    def test_a_missing_result_is_unknown(self):
        self.assertEqual(probe.evaluate(self.spec("state = running"), None),
                         probe.Verdict.unknown)

    def test_a_user_authored_probe_runs_through_sh_c_and_is_bounded(self):
        spec = self.spec("state = running")
        spec = probe.ProbeSpec(command="launchctl print gui/4242/x | grep state",
                               expect="state = running", source="declaration")
        runner = RecordingRunner()
        runner.add("sh", FakeCompleted(stdout="state = running"))
        probe.run_probe(spec, self.host(), timeout_sec=7, runner=runner)
        self.assertTrue(runner.calls)
        argv = runner.calls[0]["argv"]
        self.assertEqual(argv[:2], ("/bin/sh", "-c"))
        self.assertEqual(runner.calls[0]["kwargs"].get("timeout_sec"), 7)

    def test_a_timed_out_probe_is_unknown(self):
        spec = self.spec("state = running")
        runner = RecordingRunner()
        runner.add("", raises=errors.StepTimeout(argv=("/bin/sh",), timeout_sec=5,
                                                 partial_stdout="", partial_stderr=""))
        done, verdict = probe.run_probe(spec, self.host(), timeout_sec=5, runner=runner)
        self.assertEqual(verdict, probe.Verdict.unknown)


class TheInventory(ReconcileBase):

    def test_unknown_keys_in_a_service_entry_do_not_crash_the_reader(self):
        entries = inventory.load_inventory(self.host())
        self.assertIn("dispatcher", entries)

    def test_matching_prefers_the_label(self):
        entries = inventory.load_inventory(self.host())
        entry = entries["calendar-export"]
        self.assertTrue(inventory.match(entry, {"label": "bridge.calendar-export"}))
        self.assertFalse(inventory.match(entry, {"label": "bridge.something-else"}))

    def test_matching_falls_back_to_the_slug_when_there_is_no_label(self):
        entries = inventory.load_inventory(self.host())
        entry = entries["chat-channel"]          # label: null in the inventory
        self.assertTrue(inventory.match(entry, {"slug": "chat-channel"}))
        self.assertFalse(inventory.match(entry, {"slug": "something-else"}))

    def test_matching_falls_back_to_the_command_path_last(self):
        entries = inventory.load_inventory(self.host())
        entry = entries["dispatcher"]
        self.assertTrue(inventory.match(entry, {"command": "/opt/bridge/bin/dispatcher.sh"}))
        self.assertFalse(inventory.match(entry, {"command": "/opt/bridge/bin/other.sh"}))

    def test_an_ambiguous_match_is_never_a_guess(self):
        entries = inventory.load_inventory(self.host())
        with self.assertRaises(errors.AmbiguousInventoryMatch) as ctx:
            inventory.match_one(entries, {"label": None, "slug": None})
        self.assert_error(ctx, "ambiguous-inventory-match")

    def test_a_declared_and_live_run_missing_from_the_inventory_is_reported(self):
        w = self.load("block-style-report")
        obs = self.host_obs([self.live(f"gui/{FIXTURE_UID}/bridge.{w.id}",
                                       marker_id=w.id)],
                            {w.id: self.stamp(w.id)})
        findings = inventory.inventory_delta(obs, self.inv(), [w])
        self.assertIn(model.WorkloadState.inventory_missing, {f.state for f in findings})

    def test_an_inventory_entry_with_nothing_behind_it_is_reported(self):
        findings = inventory.inventory_delta(self.host_obs(), self.inv(), [])
        stale = [f for f in findings if f.state == model.WorkloadState.inventory_stale]
        self.assertTrue(stale)
        self.assertIn("stale-entry", " ".join(f.workload_id + f.detail for f in stale))

    def test_the_proposed_patch_is_printed_never_written(self):
        import yaml

        host_file = (SKILL_DIR / "tests" / "fixtures" / "hosts" / "host-a.yaml")
        before = host_file.read_bytes()
        w = self.load("block-style-report")
        obs = self.host_obs([self.live(f"gui/{FIXTURE_UID}/bridge.{w.id}",
                                       marker_id=w.id)],
                            {w.id: self.stamp(w.id)})
        findings = inventory.inventory_delta(obs, self.inv(), [w])
        snippet = inventory.proposed_patch(findings)
        self.assertEqual(host_file.read_bytes(), before,
                         "this skill owns the declarations, not the host inventory")
        parsed = yaml.safe_load(snippet)
        self.assertTrue(parsed)
        self.assertIn("block-style-report", snippet)


class TheCoverageLineCountsProbesThatRan(ReconcileBase):
    """"probed" came out of the FLAG, so it said nothing about the run.

    `_probe_group` skips every declaration that resolves no probe of its own,
    and that is the COMMON case, not the exception: a declaration without
    `reconcile.probe` and without `check_ref` gets none, because deriving the
    backend default here would mean rendering the artifact. Three such runs
    therefore produced an empty verdict map, no outbound probe at all, and a
    header reading `3 declaration(s) reconciled on 1 host(s), probed`.

    That line was introduced one round earlier so a run over nothing could not
    read like a healthy fleet. It then said exactly the same thing about three
    unprobed runs as about three probed ones. So the number is taken from the
    probes that RAN, and a probe refused before execution is not one of them.
    """

    #: Neither declares a probe or a check, so neither can be asked anything.
    UNPROBED = ("block-style-report", "midnight-report", "umlaut-report")
    #: One declared probe, one resolvable check reference. Both really run.
    PROBED = ("daily-health-report", "checked-report")

    def _runner(self):
        runner = RecordingRunner()
        runner.add("list", completed_from("launchctl-list.txt"))
        runner.add("print-disabled", completed_from("launchctl-print-disabled.txt"))
        return runner

    def header_for(self, declarations, probe=True, runner=None):
        root = make_repo(self.tmpdir(), declarations=declarations)
        cfg = config.load_config(root)
        runner = runner or self._runner()
        rep = reconcile.run(root, cfg, probe=probe, timeout_sec=10, runner=runner)
        return rep.header, runner

    def probe_calls(self, runner, needles):
        return [c["joined"] for c in runner.calls
                if any(n in c["joined"] for n in needles)]

    # -- the defect ---------------------------------------------------------

    def test_a_run_in_which_no_probe_ran_never_claims_it_probed(self):
        header, runner = self.header_for(self.UNPROBED)
        self.assertEqual(self.probe_calls(runner, ("bridge.dispatcher", "agent-reachable")), [],
                         "a probe went out, so this case is not measuring an unprobed run")
        self.assertNotIn(", probed", header,
                         "three declarations nobody asked anything read as probed")
        self.assertIn(f"0 of {len(self.UNPROBED)} health-probed", header)

    def test_the_line_says_out_loud_which_half_did_not_happen(self):
        # Renamed together with the sentence it guards. It used to demand the
        # words `live source`, which is how the line came to say `nothing here
        # was asked of a live source` about a run that had listed the units,
        # read the stamps and read the traces. A bare zero is still a number a
        # reader skims past, so the line still has to spell something out --
        # just the true half.
        header, _ = self.header_for(self.UNPROBED)
        self.assertIn("inspected", header,
                      "a bare zero is a number a reader skims past")
        self.assertIn("no health verdict", header)

    # -- the Gegenprobe -----------------------------------------------------

    def test_a_run_in_which_every_probe_ran_counts_them(self):
        # Without this half the fix could be a constant "0 of N" and the case
        # above would still pass.
        header, runner = self.header_for(self.PROBED)
        self.assertTrue(self.probe_calls(runner, ("bridge.dispatcher", "agent-reachable")),
                        "no probe went out, so there is nothing to count here")
        self.assertIn(f"{len(self.PROBED)} of {len(self.PROBED)} health-probed", header)

    def test_the_probed_and_the_unprobed_run_never_read_the_same(self):
        # The differential. Two runs over the same NUMBER of declarations, one
        # asked and one not: identical first lines are the whole defect.
        probed, _ = self.header_for(self.PROBED)
        unprobed, _ = self.header_for(self.UNPROBED[:len(self.PROBED)])
        self.assertNotEqual(probed, unprobed)

    # -- what does not count ------------------------------------------------

    def test_a_probe_refused_before_it_ran_is_not_coverage(self):
        # public-funnel carries an unresolved <funnel> placeholder, so run_probe
        # refuses to execute it and hands back unknown. An unknown nobody ran is
        # not something that was asked of a machine.
        header, runner = self.header_for(("public-funnel",))
        self.assertNotIn("funnel/health", runner.joined_calls,
                         "the placeholder probe was executed, which resolves a "
                         "literal hostname")
        self.assertIn("0 of 1 health-probed", header)

    def test_no_probe_says_so_in_its_own_words(self):
        header, runner = self.header_for(self.PROBED, probe=False)
        self.assertIn("--no-probe", header)
        self.assertEqual(self.probe_calls(runner, ("bridge.dispatcher", "agent-reachable")), [])

    # -- inspection is not the same thing as a health probe -----------------

    def test_zero_probes_does_not_claim_the_machine_went_unread(self):
        """The sentence said more than the number meant, and a page repeated it.

        A run with no health probe still ASKS the machine: it lists the units,
        reads the ownership stamp and reads the trace the guard wrote. Those are
        live reads and the findings are built from them. The line nevertheless
        said `nothing here was asked of a live source`, which is simply false,
        and the moment it was rendered onto a dashboard it became a banner
        telling the reader to distrust findings that came off the machine.

        The distinction the line has to carry: no health VERDICT was taken, the
        state was still read.
        """
        header, _ = self.header_for(self.UNPROBED)
        self.assertNotIn(
            "nothing here was asked of a live source", header,
            "the units were listed, the stamps were read and the traces were "
            "read; calling that `nothing` is the opposite overclaim")
        self.assertIn("0 of", header, "the count still has to be there")
        for word in ("inspect", "health"):
            with self.subTest(word=word):
                self.assertIn(word, header.lower(),
                              "the line has to name what DID happen and what "
                              "did not, or the reader guesses")

    def test_an_unreachable_host_really_did_go_unread(self):
        """The Gegenprobe, and the case the old sentence was right about."""
        header = reconcile._coverage(
            [self.load("calendar-export")], {"host-a": []}, True, 0, reached=0)
        self.assertIn("no host answered", header,
                      "when no host answered, nothing WAS read, and that is a "
                      "different sentence than `no health probe ran`")


if __name__ == "__main__":
    unittest.main()


class TheMarkerIsNeverInferredFromNotLooking(ReconcileBase):
    """Enumeration cannot see a marker, so it must not be read as its absence.

    `launchctl list` prints three columns and no environment, so
    `parse_discovery` has nothing to fill `marker_id` with. Reading that None
    as "the unit carries no marker" made every correctly provisioned run report
    drift forever, with a repair hint (`provision it again`) that reproduced the
    same state on the next pass.

    This is the same mistake the file already names one field over, in
    `TheTwoCurrenciesAreNeverCompared`, and the same one `HostObservation`
    guards against for a whole host: "a workload carried by one of them cannot
    be judged absent, only unknown". A marker deserves the same rule.

    Everything below drives the REAL observation path. A test that hands
    `classify` a LiveUnit it built itself cannot see this defect, because it
    constructs the very state the machine can never reach.
    """

    LISTING = (
        "uid=4242\n"
        "PID\tStatus\tLabel\n"
        "5511\t0\tbridge.calendar-export\n"
        "5512\t0\tcom.example.mesh\n"
    )
    STAMPED_REF = "gui/4242/bridge.calendar-export"

    def printed(self, marker_id="calendar-export", digest=None):
        """A realistic `launchctl print`, with the marker where launchd puts it."""
        digest = digest or declared_digest("calendar-export")
        lines = [f"{self.STAMPED_REF} = {{", "\tstate = running", "\tprogram = /bin/sh"]
        if marker_id is not None:
            lines += ["\tenvironment = {",
                      f"\t\t{'BRIDGE_WORKLOAD'} => {marker_id}",
                      f"\t\t{'BRIDGE_WORKLOAD_DIGEST'} => {digest}",
                      "\t}"]
        lines.append("}")
        return "\n".join(lines)

    def observed(self, printed=None):
        """observe_host over one stamped unit, through the real code path."""
        runner = RecordingRunner()
        runner.add("launchctl list", FakeCompleted(stdout=self.LISTING))
        runner.add("print-disabled", completed_from("launchctl-print-disabled.txt"))
        runner.add("cat", FakeCompleted(stdout=stamp_json()))
        if printed is not None:
            runner.add("launchctl print gui", FakeCompleted(stdout=printed))
        root = make_repo(self.tmpdir())
        cfg = config.load_config(root)
        obs = reconcile.observe_host(self.host(), cfg, timeout_sec=10, runner=runner)
        return obs, runner

    def stamped_unit(self, obs):
        for u in obs.live_units:
            if u.unit_ref == self.STAMPED_REF:
                return u
        raise AssertionError(
            f"the stamped unit was not enumerated at all; got "
            f"{[u.unit_ref for u in obs.live_units]}")

    # -- the model ---------------------------------------------------------
    def test_enumeration_reports_the_marker_as_unread_not_as_absent(self):
        obs, _ = self.observed()
        unit = self.stamped_unit(obs)
        self.assertFalse(
            getattr(unit, "marker_observed", None),
            "enumeration must not claim it looked")
        self.assertIsNotNone(
            getattr(unit, "marker_observed", None),
            "a unit needs a field that separates 'not looked' from 'looked and absent'; "
            "without it None means both and the comparison has to guess")

    # -- the observation ---------------------------------------------------
    def test_the_machine_is_asked_for_the_marker_of_a_unit_a_stamp_claims(self):
        obs, runner = self.observed(printed=self.printed())
        asked = [c["joined"] for c in runner.calls if "launchctl print" in c["joined"]
                 and "print-disabled" not in c["joined"]]
        self.assertTrue(
            asked,
            "a stamp claims this unit, and the second ownership signal sits inside "
            "it; enumeration cannot carry it, so something has to ask")
        unit = self.stamped_unit(obs)
        self.assertEqual(unit.marker_id, "calendar-export")
        self.assertTrue(getattr(unit, "marker_observed", False))

    def test_an_unclaimed_unit_is_not_inspected(self):
        _, runner = self.observed(printed=self.printed())
        joined = runner.joined_calls
        self.assertNotIn(
            "com.example.mesh", joined,
            "no stamp claims it, so asking would be a read this skill has no reason "
            "to make; on a real box that is a thousand extra calls")

    # -- the comparison ----------------------------------------------------
    def test_a_stamped_unit_whose_marker_was_never_read_is_not_called_drift(self):
        w = self.load("calendar-export")
        unit = self.live(self.STAMPED_REF, marker_id=None, marker_observed=False)
        findings = reconcile.classify(
            [w], self.host_obs([unit], {"calendar-export": self.stamp("calendar-export")}),
            self.inv(), {})
        states = self.states_for(findings, "calendar-export")
        self.assertNotIn(
            model.WorkloadState.drifted, states,
            "nothing looked, so nothing drifted. Calling it drift sends the reader to "
            "provision, which changes nothing and reports the same state again")

    def test_a_marker_that_was_read_and_is_absent_is_still_drift(self):
        w = self.load("calendar-export")
        unit = self.live(self.STAMPED_REF, marker_id=None, marker_observed=True)
        findings = reconcile.classify(
            [w], self.host_obs([unit], {"calendar-export": self.stamp("calendar-export")}),
            self.inv(), {})
        self.assertIn(
            model.WorkloadState.drifted, self.states_for(findings, "calendar-export"),
            "the rule itself is right: a unit somebody else replaced carries a stamp "
            "and no marker, and that must stay visible")

    # -- end to end --------------------------------------------------------
    def test_a_correctly_provisioned_unit_reads_as_in_sync_through_observation(self):
        obs, _ = self.observed(printed=self.printed())
        w = self.load("calendar-export")
        findings = reconcile.classify([w], obs, self.inv(), {})
        states = self.states_for(findings, "calendar-export")
        self.assertIn(
            model.WorkloadState.in_sync, states,
            f"provision reported already-in-sync for this same object; reconcile "
            f"produced {states}. Two commands of one skill disagreeing about one "
            f"unit is worse than either being wrong")
        self.assertNotIn(model.WorkloadState.drifted, states)


class OnlyAThingThatShouldBeRunningCanBeStopped(ReconcileBase):
    """`running is False` means trouble for a daemon and nothing for a cadence.

    A daemon that is not running is down. An interval, recurring, watch or
    oneshot run is not running almost all of the time, by design: it fires, it
    ends, it waits. Judging all six kinds by one signal reported a healthy job
    forty-five seconds after a successful run as `high stopped`, and the repair
    hint told the reader to bootout and bootstrap a unit that was fine. A tool
    that cries about a healthy thing is a tool people stop reading.

    Same shape as the marker defect one class up: a signal that answers the
    question for ONE kind, applied to all of them.
    """

    def scene(self, name, running, *, unit_ref=None, runtime="launchd"):
        w = self.load(name)
        ref = unit_ref or f"gui/{FIXTURE_UID}/bridge.{w.id}"
        unit = self.live(ref, marker_id=w.id, running=running, runtime=runtime)
        st = self.stamp(w.id, unit_ref=ref, runtime=runtime)
        return w, self.host_obs([unit], {w.id: st})

    def states_of(self, name, running, **kw):
        w, obs = self.scene(name, running, **kw)
        return self.states_for(reconcile.classify([w], obs, self.inv(), {}), w.id)

    def test_a_cadence_between_two_runs_is_not_stopped(self):
        for name in ("calendar-export", "voicememo-notify"):
            with self.subTest(workload=name):
                states = self.states_of(name, running=False)
                self.assertNotIn(
                    model.WorkloadState.stopped, states,
                    "it fires and ends; not running is where it spends its life")

    def test_a_daemon_that_is_not_running_is_still_stopped(self):
        states = self.states_of("elevated-daemon", running=False,
                                unit_ref="system/bridge.elevated-daemon",
                                runtime="launchd-system")
        self.assertIn(
            model.WorkloadState.stopped, states,
            "a daemon is the one kind for which 'not running' means down")

    def test_a_daemon_that_runs_is_not_reported(self):
        states = self.states_of("elevated-daemon", running=True,
                                unit_ref="system/bridge.elevated-daemon",
                                runtime="launchd-system")
        self.assertNotIn(model.WorkloadState.stopped, states)

    def test_a_failing_probe_still_means_stopped_whatever_the_kind(self):
        probe = mod("engine.probe")
        w, obs = self.scene("calendar-export", running=True)
        findings = reconcile.classify([w], obs, self.inv(), {w.id: probe.Verdict.fail})
        self.assertIn(
            model.WorkloadState.stopped, self.states_for(findings, w.id),
            "the declaration named this probe as the question to ask; a fail is an "
            "answer somebody asked for, not an inference from the kind")


class TheTraceIsReadBackOrTheEvidenceIsDecoration(ReconcileBase):
    """The guard script writes one line per run. Something has to read it.

    The wrapper says it plainly in its own comment: "One line per run: this is
    what makes an absent run detectable at all. Without it, nothing
    distinguishes a run that failed from a run that never started." It writes
    that line faithfully and nothing in the engine ever reads it back, so the
    sentence describes a capability the skill does not have.

    That is the third member of the family this file keeps finding: a signal
    that exists and is never consulted. `missing` is listed in `notify_on` as
    "the one nobody has today", and it stayed that way.

    What is deliberately NOT claimed here: an expected firing can only be
    computed where the declaration states a cadence outright, which is `interval`
    and its `every_sec`. A recurring run needs an RRULE engine the skill does not
    carry on purpose, so for those kinds the answer is "cannot say", said out
    loud, and never a quiet pass.
    """

    STATE_DIR = f"{FIXTURE_HOME}/.bridge/workloads"

    def trace_line(self, wid, *, rc=0, when="2026-08-23T08:00:00Z", verdict="ok"):
        return f"{when} workload={wid} rc={rc} duration_sec=1 verdict={verdict}\n"

    def observed_with(self, traces, *, wid="calendar-export"):
        """A host observation carrying the traces it read back."""
        unit = self.live(f"gui/{FIXTURE_UID}/bridge.{wid}", marker_id=wid)
        obs = self.host_obs([unit], {wid: self.stamp(wid)})
        return dataclasses.replace(obs, traces=traces)

    def states(self, wid, traces, now=None):
        w = self.load(wid)
        obs = self.observed_with(traces, wid=wid)
        findings = reconcile.classify([w], obs, self.inv(), {}, now=now)
        return self.states_for(findings, wid)

    # -- the read ----------------------------------------------------------
    def test_the_trace_is_read_off_the_host(self):
        runner = RecordingRunner()
        runner.add("launchctl list", FakeCompleted(stdout="uid=4242\n"))
        runner.add("print-disabled", completed_from("launchctl-print-disabled.txt"))
        runner.add("cat", FakeCompleted(stdout=stamp_json()))
        root = make_repo(self.tmpdir())
        cfg = config.load_config(root)
        obs = reconcile.observe_host(self.host(), cfg, timeout_sec=10, runner=runner)
        self.assertTrue(
            hasattr(obs, "traces"),
            "the observation has nowhere to put what the guard script wrote")
        self.assertIn(
            ".trace", runner.joined_calls,
            "the guard script writes one line per run and nothing asks for it")

    # -- a run that failed -------------------------------------------------
    def test_the_newest_line_deciding_it_failed_is_reported(self):
        states = self.states("calendar-export",
                             {"calendar-export": self.trace_line("calendar-export", rc=1)},
                             now="2026-08-23T08:01:00Z")
        self.assertIn(
            model.WorkloadState.last_run_failed, states,
            "the run ended non zero and said so in writing; a report that calls "
            "this in_sync is worse than no report")

    def test_a_run_that_succeeded_is_not_reported(self):
        states = self.states("calendar-export",
                             {"calendar-export": self.trace_line("calendar-export", rc=0)},
                             now="2026-08-23T08:01:00Z")
        self.assertNotIn(model.WorkloadState.last_run_failed, states)

    def test_only_the_newest_line_decides(self):
        older = self.trace_line("calendar-export", rc=1, when="2026-08-23T07:00:00Z")
        newest = self.trace_line("calendar-export", rc=0, when="2026-08-23T08:00:00Z")
        states = self.states("calendar-export", {"calendar-export": older + newest},
                             now="2026-08-23T08:01:00Z")
        self.assertNotIn(
            model.WorkloadState.last_run_failed, states,
            "it failed an hour ago and has run cleanly since; reporting the old "
            "failure forever is how a report becomes noise")

    # -- a daemon that crashed once and runs again -------------------------
    def test_a_started_line_after_old_failures_clears_the_failure(self):
        lines = (self.trace_line("calendar-export", rc=2, when="2026-08-10T17:16:19Z", verdict="failed")
                 + self.trace_line("calendar-export", rc=0, when="2026-08-23T07:05:31Z", verdict="started"))
        states = self.states("calendar-export", {"calendar-export": lines}, now="2026-08-23T08:01:00Z")
        self.assertNotIn(model.WorkloadState.last_run_failed, states,
                         "it started again after the crash and has not ended since")

    def test_a_failure_after_the_start_is_still_reported(self):
        lines = (self.trace_line("calendar-export", rc=0, when="2026-08-23T07:05:31Z", verdict="started")
                 + self.trace_line("calendar-export", rc=1, when="2026-08-23T07:30:00Z", verdict="failed"))
        states = self.states("calendar-export", {"calendar-export": lines}, now="2026-08-23T08:01:00Z")
        self.assertIn(model.WorkloadState.last_run_failed, states)

    # -- a run that said "try again" -------------------------------------
    # 2026-09-26: two suppliers end with 75 (EX_TEMPFAIL) when GitHub does not
    # answer for a moment, and every one of those rang a phone although the
    # next tick an hour later went through. A declaration may name such codes;
    # the first one stays quiet, a second failure in a row speaks. Everything
    # not named keeps speaking on the first run, because critical things must.
    def states_transient(self, lines, codes=(75,)):
        w = self.load("calendar-export")
        w = dataclasses.replace(
            w, response=dataclasses.replace(w.response, transient_exit_codes=tuple(codes)))
        obs = self.observed_with({"calendar-export": "".join(lines)})
        findings = reconcile.classify([w], obs, self.inv(), {}, now="2026-08-23T08:01:00Z")
        return self.states_for(findings, w.id)

    def test_a_first_transient_failure_after_a_clean_run_stays_quiet(self):
        states = self.states_transient([
            self.trace_line("calendar-export", rc=0, when="2026-08-23T07:00:00Z"),
            self.trace_line("calendar-export", rc=75, when="2026-08-23T08:00:00Z", verdict="failed")])
        self.assertNotIn(model.WorkloadState.last_run_failed, states,
                         "the run said 'try again' once; the next tick decides")

    def test_a_second_failure_in_a_row_speaks(self):
        states = self.states_transient([
            self.trace_line("calendar-export", rc=75, when="2026-08-23T07:00:00Z", verdict="failed"),
            self.trace_line("calendar-export", rc=75, when="2026-08-23T08:00:00Z", verdict="failed")])
        self.assertIn(model.WorkloadState.last_run_failed, states,
                      "twice in a row is no longer a blip")

    def test_a_transient_code_as_the_only_run_speaks(self):
        states = self.states_transient([
            self.trace_line("calendar-export", rc=75, when="2026-08-23T08:00:00Z", verdict="failed")])
        self.assertIn(model.WorkloadState.last_run_failed, states,
                      "with no clean run before it there is nothing to lean on")

    def test_a_code_not_named_transient_speaks_at_once(self):
        states = self.states_transient([
            self.trace_line("calendar-export", rc=0, when="2026-08-23T07:00:00Z"),
            self.trace_line("calendar-export", rc=65, when="2026-08-23T08:00:00Z", verdict="failed")])
        self.assertIn(model.WorkloadState.last_run_failed, states,
                      "65 means a human is needed; that must not wait an hour")

    def test_without_the_field_every_failure_speaks_at_once(self):
        states = self.states_transient([
            self.trace_line("calendar-export", rc=0, when="2026-08-23T07:00:00Z"),
            self.trace_line("calendar-export", rc=75, when="2026-08-23T08:00:00Z", verdict="failed")],
            codes=())
        self.assertIn(model.WorkloadState.last_run_failed, states)

    def test_an_expired_run_is_never_transient(self):
        states = self.states_transient([
            self.trace_line("calendar-export", rc=0, when="2026-08-23T07:00:00Z"),
            self.trace_line("calendar-export", rc=75, when="2026-08-23T08:00:00Z", verdict="expired")])
        self.assertIn(model.WorkloadState.last_run_failed, states,
                      "a deadline cut the run off; that is not the program asking to retry")


    # -- a run that never came --------------------------------------------
    def test_a_cadence_that_stopped_firing_is_overdue(self):
        # calendar-export declares every_sec 900, so two cadences is 1800s.
        states = self.states("calendar-export",
                             {"calendar-export": self.trace_line("calendar-export")},
                             now="2026-08-23T09:00:00Z")
        self.assertIn(
            model.WorkloadState.overdue, states,
            "an hour without a line from a fifteen minute cadence is the absence "
            "the whole trace exists to make visible")

    def test_a_cadence_that_just_fired_is_not_overdue(self):
        states = self.states("calendar-export",
                             {"calendar-export": self.trace_line("calendar-export")},
                             now="2026-08-23T08:05:00Z")
        self.assertNotIn(model.WorkloadState.overdue, states)

    def test_a_translatable_recurrence_is_answered_rather_than_shrugged_at(self):
        """Rewritten 2026-08-24, and the old assertion is the point.

        It used to read "a recurring run needs an RRULE engine this skill
        deliberately does not carry; guessing would be worse than admitting
        it", and it held a real limitation as though it were a rule. The
        limitation was smaller than it looked: the run was never missing an
        engine, it was missing a MOMENT, and the hour and weekday set were
        already there, in the two functions the unit file is rendered from.

        A customer facing report was migrated on 2026-08-24 declaring
        `notify_on: [missing]`, and this shrug is what it got.
        """
        states = self.states("daily-health-report",
                             {"daily-health-report": self.trace_line("daily-health-report")},
                             now="2026-08-30T08:00:00Z")
        self.assertIn(
            model.WorkloadState.overdue, states,
            "a run with a translatable recurrence, whose newest line is a week "
            "old, is overdue and can be said to be")

    def test_a_recurrence_outside_the_translated_subset_still_says_so(self):
        # The refusal survives, and must: approximating a rule the renderer
        # refuses would put a number nobody declared into a report as a
        # measurement.
        states = self.states(
            "exotic-recurrence-watched",
            {"exotic-recurrence-watched": self.trace_line("exotic-recurrence-watched")},
            now="2026-08-30T08:00:00Z")
        self.assertNotIn(model.WorkloadState.overdue, states,
                         "an untranslatable recurrence was approximated")
        self.assertIn(
            model.WorkloadState.unknown, states,
            "it asked for missing detection and cannot get it. Saying nothing "
            "would read as 'nothing wrong'")

    # -- nobody is spammed -------------------------------------------------
    def test_a_workload_that_did_not_ask_is_not_reported(self):
        # voicememo-notify asks for `failure` and NOT for `missing`, and it
        # declares a fallback cadence, so its absence COULD be computed. It is
        # not, because nobody asked. An alarm nobody asked for is the alarm that
        # gets switched off, and then it is missing when it counts.
        states = self.states("voicememo-notify",
                             {"voicememo-notify": self.trace_line("voicememo-notify")},
                             now="2026-08-30T08:00:00Z")
        self.assertNotIn(model.WorkloadState.overdue, states)
        self.assertNotIn(model.WorkloadState.unknown, states)

    def test_the_same_workload_still_gets_what_it_did_ask_for(self):
        states = self.states("voicememo-notify",
                             {"voicememo-notify": self.trace_line("voicememo-notify", rc=2)},
                             now="2026-08-30T08:00:00Z")
        self.assertIn(
            model.WorkloadState.last_run_failed, states,
            "it asked for failure, and silence about a non zero run would be the "
            "same defect one field over")

    def test_a_unit_that_is_gone_is_not_also_told_about_its_cadence(self):
        # The absence is the story. Adding "and by the way I cannot work out
        # your cadence" to a unit that is not there is the noise that makes a
        # report stop being read.
        w = self.load("block-style-report")
        obs = self.host_obs(stamps={w.id: self.stamp(w.id)})
        states = self.states_for(
            reconcile.classify([w], obs, self.inv(), {}), w.id)
        self.assertEqual(
            states, {model.WorkloadState.absent},
            "a gone unit gets one finding, and it is that it is gone")


class EveryStateDecidesWhetherTheTraceSpeaks(ReconcileBase):
    """The completeness check the suppression never had.

    The rule lived inside one `if` as four members. That reads as a list of
    examples, and a list of examples has no opinion about the state somebody
    adds next year: it joins the JUDGED side by default and in silence. Which is
    how a deliberately retired workload came to be reported `high overdue` for a
    run nobody wanted, in the same report that said it was retired and gone.

    So the two sides are named and compared against the enum. This is the cheap
    class of test that was missing everywhere: not another example, a table that
    cannot be completed by accident.
    """

    def test_every_state_decides_whether_the_trace_speaks(self):
        quiet, loud = reconcile.TRACE_SAYS_NOTHING_IN, reconcile.TRACE_SPEAKS_IN
        every = set(model.WorkloadState)
        missing = sorted(s.value for s in every - quiet - loud)
        self.assertEqual(
            missing, [],
            "these states say nothing about whether the run's own trace is "
            "worth reading beside them, so they took the loud answer by "
            "default: " + ", ".join(missing))

    def test_no_state_is_on_both_sides(self):
        both = sorted(s.value for s in
                      reconcile.TRACE_SAYS_NOTHING_IN & reconcile.TRACE_SPEAKS_IN)
        self.assertEqual(both, [], "a state cannot be quiet and loud at once")

    def test_the_two_sides_are_spelled_out_and_not_derived(self):
        # The counter control, and it has to read the SOURCE. If the loud side
        # were computed as "every state minus the quiet ones", the completeness
        # case above would pass on any enum for ever and prove nothing, and no
        # assertion over the VALUES could tell the two apart: a written list and
        # a derived one hold exactly the same members today.
        source = (SKILL_DIR / "engine" / "reconcile.py").read_text(encoding="utf-8")
        self.assertIn("TRACE_SPEAKS_IN = frozenset({", source,
                      "the loud side has to be a written list; derived from the "
                      "quiet one it would grow silently with the enum, which is "
                      "the defect this whole class exists for")


class ARetiredRunIsNotLate(ReconcileBase):
    """Nobody is waiting for a run that was deliberately stopped.

    The trace outlives the workload on purpose: it is the record of what
    happened. But reading it against a RETIRED declaration produces the two
    loudest findings this skill has for something that is behaving exactly as
    intended. The report said `retired and gone from the machine` and
    `high overdue` about the same id, in the same run, three lines apart.

    Found by retiring the three probes on a real machine and looking at what
    came back afterwards. The suppression list already covered absent and
    not-provisioned units; retired ones land on `in_sync`, so they walked past
    it.
    """

    def retired(self, wid="calendar-export"):
        w = self.load(wid)
        object.__setattr__(w, "retired", {"at": "2026-08-23T09:29:34+02:00",
                                          "reason": "the probe served its purpose"})
        return w

    def findings_for(self, w, *, rc, when, live=False):
        """`live=False` is the case that was observed: retired AND gone.

        A retired workload that is still loaded is `retired_but_live`, which the
        suppression already covered. The one that walked past it is the one that
        did exactly what it was told: it stopped, and the report then called it
        late for a run nobody wanted.
        """
        unit_ref = f"gui/{FIXTURE_UID}/bridge.{w.id}"
        units = [self.live(unit_ref, marker_id=w.id)] if live else []
        obs = self.host_obs(units=units,
                            stamps={w.id: self.stamp(w.id, unit_ref=unit_ref)})
        line = f"{when} workload={w.id} rc={rc} duration_sec=1 verdict=ok\n"
        obs = dataclasses.replace(obs, traces={w.id: line})
        return reconcile.classify([w], obs, self.inv(), {})

    def test_a_retired_run_is_never_overdue(self):
        states = {f.state for f in self.findings_for(
            self.retired(), rc=0, when="2026-01-01T00:00:00Z")}
        self.assertNotIn(model.WorkloadState.overdue, states,
                         "it was stopped on purpose, so nothing is waiting for it")

    def test_a_retired_runs_last_failure_is_history_not_news(self):
        states = {f.state for f in self.findings_for(
            self.retired(), rc=1, when=_utc_now_stamp())}
        self.assertNotIn(model.WorkloadState.last_run_failed, states,
                         "the last run of a retired workload is a record, and "
                         "there is no run after it to fix")

    def test_a_live_one_is_still_judged(self):
        # The counter control, and the whole worth of the two above: a
        # suppression that fires on everything reports a quiet machine for the
        # same reason an empty one does.
        states = {f.state for f in self.findings_for(
            self.load("calendar-export"), rc=1, when=_utc_now_stamp(), live=True)}
        self.assertIn(model.WorkloadState.last_run_failed, states)


class TheGrantDoesNotFollowARename(ReconcileBase):
    """Moving the interpreter moves the program and leaves the grant behind.

    A privacy grant is issued to a literal path, and macOS lets nothing read or
    write that database, so the only party that can notice the path moved is the
    one holding both records: the declaration says where the program is now, the
    stamp says where it was when a human last answered a prompt about it.

    The failure this catches is silent in the worst way. The renamed program
    starts, runs, exits zero and reads an empty result, because a client with no
    grant is not denied, it is simply shown nothing. That reads as an empty
    inbox, an empty calendar, a quiet day.
    """

    def scene(self, *, declared, stamped, grants=("full-disk-access",)):
        w = self.load("calendar-export")
        object.__setattr__(w.placement, "interpreter", declared)
        object.__setattr__(w.placement, "privacy_grants", tuple(grants))
        unit_ref = f"gui/{FIXTURE_UID}/bridge.{w.id}"
        fields = {} if stamped is _ABSENT else {"interpreter": stamped}
        st = self.stamp(w.id, unit_ref=unit_ref,
                        declaration_digest=model.declaration_digest(w), **fields)
        obs = self.host_obs(
            units=[self.live(unit_ref, marker_id=w.id,
                             marker_digest=st.artifact_digest)],
            stamps={w.id: st})
        return reconcile.classify([w], obs, self.inv(), {})

    def text(self, findings, state=None):
        return " ".join(
            f"{f.state} {f.detail} {f.hint or ''}" for f in findings
            if state is None or f.state == state)

    def test_a_moved_interpreter_is_reported_and_both_paths_are_named(self):
        findings = self.scene(declared="/opt/bridge/bin/uv-calendar-neu",
                              stamped="/opt/bridge/bin/uv-calendar")
        self.assertIn(model.WorkloadState.grant_orphaned,
                      {f.state for f in findings},
                      "the program moved and the grant did not; nothing said so")
        text = self.text(findings, model.WorkloadState.grant_orphaned)
        self.assertIn("/opt/bridge/bin/uv-calendar", text,
                      "the old path is where the grant still sits, and a repair "
                      "that cannot name it cannot be performed")
        self.assertIn("/opt/bridge/bin/uv-calendar-neu", text,
                      "the new path is the one a human has to grant")
        self.assertIn("full-disk-access", text,
                      "naming the pane is the only reason the field is a closed list")

    def test_an_unmoved_interpreter_says_nothing(self):
        findings = self.scene(declared="/opt/bridge/bin/uv-calendar",
                              stamped="/opt/bridge/bin/uv-calendar")
        self.assertNotIn(model.WorkloadState.grant_orphaned,
                         {f.state for f in findings})

    def test_a_rename_without_a_declared_grant_is_ordinary_drift(self):
        findings = self.scene(declared="/opt/bridge/bin/b",
                              stamped="/opt/bridge/bin/a", grants=())
        self.assertNotIn(
            model.WorkloadState.grant_orphaned, {f.state for f in findings},
            "with no grant declared there is nothing to orphan, and a rename is "
            "already reported as drift by the digest")

    def test_a_stamp_that_never_recorded_one_admits_it_cannot_tell(self):
        findings = self.scene(declared="/opt/bridge/bin/uv-calendar-neu",
                              stamped=_ABSENT)
        text = self.text(findings)
        # Asserted on the STATE, not on words. The first version of this looked
        # for a phrase that appears in the honest answer too, so it failed while
        # the rule was right -- a test measuring its own wording rather than the
        # behaviour it is named after.
        self.assertNotIn(
            model.WorkloadState.grant_orphaned, {f.state for f in findings},
            "an older stamp holds no interpreter, so claiming the grant is "
            "orphaned would be a guess dressed as a reading")
        self.assertIn(
            "cannot tell", text,
            "and passing in silence would be the same guess with the opposite "
            "sign: this is exactly the case marker_observed exists for")


_ABSENT = object()


class TheRunsThatWereObservedReachTheReport(MachineGuard):
    """A calendar draws plan against actual, and the actual half is the trace.

    `reconcile` reads every guard trace on the host and then kept them to
    itself: the report carried findings only, so a page built from it could draw
    what a declaration INTENDS and nothing about whether it ever happened. Plan
    alone on a timeline is the most confident possible drawing of an unverified
    claim, and this skill exists because declared state is not state.

    They cannot travel inside the findings either: a healthy run produces no
    finding at all, and that is exactly the run whose last firing the reader
    wants to see.
    """

    def test_a_report_with_nothing_observed_has_an_empty_mapping(self):
        self.assertEqual(report_mod.Report(findings=[], header="").runs, {},
                         "None here would make every reader guard against it, "
                         "and one of them would forget")

    def test_a_trace_on_the_host_arrives_in_the_report(self):
        """End to end, because the dataclass cases above prove only a field.

        The needle for this sits in `reconcile`, so a case that builds its own
        Report cannot fail when the collection stops happening. This one runs
        the real path with a machine that answers with a trace.
        """
        root = make_repo(self.tmpdir(), declarations=("calendar-export",))
        cfg = config.load_config(root)
        runner = RecordingRunner()
        runner.add("list", completed_from("launchctl-list.txt"))
        runner.add("print-disabled", completed_from("launchctl-print-disabled.txt"))
        runner.add(".trace", FakeCompleted(rc=0, stdout=(
            "==== calendar-export.trace\n"
            "2026-08-23T05:20:00Z workload=calendar-export rc=0 duration_sec=1 verdict=ok\n")))
        rep = reconcile.run(root, cfg, probe=False, timeout_sec=10, runner=runner)
        self.assertEqual(rep.runs.get("calendar-export"),
                         ("2026-08-23T05:20:00Z", 0),
                         "the traces were read off the machine and then kept "
                         "inside reconcile, so nothing downstream can tell a run "
                         "that fired from one that never has")

    def test_the_newest_stamp_and_its_return_code_are_both_carried(self):
        rep = report_mod.Report(
            findings=[], header="",
            runs={"issue-radar": ("2026-08-23T05:20:00Z", 0)})
        when, rc = rep.runs["issue-radar"]
        self.assertTrue(when.endswith("Z"), "the stamp travels as the host wrote it, in UTC")
        self.assertEqual(rc, 0,
                         "a run that happened and failed is not the same picture "
                         "as one that happened and worked")


class NotAskedIsNotAbsent(ReconcileBase):
    """An inventory entry is only stale if every domain was actually enumerated.

    The sentence `neither a declaration nor the machine knows it` is a claim
    about the machine, and its repair hint says to DROP the entry. Both are
    earned only by a complete look. On 2026-08-23 an incomplete look made that
    claim about two root daemons that were running, one of them the emergency
    ssh on a second port: following the hint would have deleted the record of
    the only backup way into that machine.

    `HostObservation.failed_runtimes` already carried the right idea in its own
    docstring, `a workload carried by one of them cannot be judged absent, only
    unknown`. It was read for workloads and ignored for the inventory.
    """

    def test_a_complete_look_may_still_call_an_entry_stale(self):
        findings = inventory.inventory_delta(self.host_obs(), self.inv(), [])
        self.assertTrue([f for f in findings
                         if f.state == model.WorkloadState.inventory_stale])

    def test_an_incomplete_look_never_calls_an_entry_stale(self):
        obs = self.host_obs(failed_runtimes={"launchd-system"})
        findings = inventory.inventory_delta(obs, self.inv(), [])
        self.assertEqual(
            [f for f in findings if f.state == model.WorkloadState.inventory_stale], [],
            "an entry was called stale although a whole runtime was never enumerated")

    def test_and_it_says_which_look_was_missing_instead_of_going_quiet(self):
        obs = self.host_obs(failed_runtimes={"launchd-system"})
        findings = inventory.inventory_delta(obs, self.inv(), [])
        said = " ".join(f.detail for f in findings)
        self.assertIn("launchd-system", said)
        self.assertNotIn("drop the entry", " ".join(f.hint or "" for f in findings))


class EachAppointmentIsReconciledOnItsOwn(ReconcileBase):
    """Two units from one declaration are two answers, never one.

    Before this, `find_unit` returned the FIRST unit whose marker named the
    declaration, and `read_stamps` keyed its result by workload id. Both are
    right for a declaration with one unit and wrong for a declaration with two:
    the second unit would be claimed by nobody and reported as running on the
    machine with no declaration behind it, while its stamp would have been
    overwritten by the first one's on the way in.

    The failure mode is the worse of the two possible ones. A missing unit is
    loud; a unit reported as FOREIGN while its own declaration sits in the
    repository teaches a reader that the report is unreliable, and the next
    genuinely undeclared unit is skipped past.

    The state key is the unit, not the declaration: `<id>` for a single
    appointment, `<id>.<name>` where there are several. The ownership MARKER
    keeps the declaration id, because it answers a different question, namely
    whose unit this is, and both units belong to the same declaration.
    """

    def test_every_unit_of_a_declaration_is_found(self):
        w = self.load("twice-daily-report")
        units = [
            self.live("gui/501/bridge.twice-daily-report.morning",
                           marker_id="twice-daily-report"),
            self.live("gui/501/bridge.twice-daily-report.midday",
                           marker_id="twice-daily-report"),
        ]
        found = inventory.find_units(w, units)
        self.assertEqual(
            sorted(u.unit_ref for u in found),
            ["gui/501/bridge.twice-daily-report.midday",
             "gui/501/bridge.twice-daily-report.morning"],
            "one of the two units was not recognised as belonging to its own "
            "declaration and would be reported as foreign")

    def test_every_unit_is_found_without_marker_and_without_stamp(self):
        """Rule 3 alone, which is the case the other test never reaches.

        The test above sets marker_id and therefore measures Rule 1. Rule 3 is
        what carries a declaration whose ownership signals are BOTH gone: a
        fresh machine, a restored one, a changed stamp_dir. Until 2026-08-25 it
        compared the label against the id by string ends, so
        `bridge.<id>.<appointment>` matched neither `== id` nor `endswith .id`
        nor `startswith id.`, and a multi appointment declaration lost its own
        units to the unmanaged pile while reporting itself as never
        provisioned. The two loud failures cancel into one quiet wrong picture.
        """
        w = self.load("twice-daily-report")
        units = [
            self.live("gui/501/bridge.twice-daily-report.morning"),
            self.live("gui/501/bridge.twice-daily-report.midday"),
        ]
        found = inventory.find_units(w, units)
        self.assertEqual(
            sorted(u.unit_ref for u in found),
            ["gui/501/bridge.twice-daily-report.midday",
             "gui/501/bridge.twice-daily-report.morning"])

    def test_a_foreign_unit_that_merely_ends_in_the_id_is_not_claimed(self):
        """The other half of the same rule, and it has to change with it.

        `endswith("." + id)` is not anchored at the front, so a unit under a
        completely different prefix was claimed by this declaration. That is
        how a superseded unit and its successor were both reported in sync
        against ONE stamp on 2026-08-25. Loosening the rule for appointments
        without anchoring the front trades one wrong match for another.
        """
        w = self.load("daily-health-report")
        foreign = self.live("gui/501/com.foreign.scheduler.daily-health-report")
        self.assertEqual(inventory.find_units(w, [foreign]), ())
        self.assertIsNone(inventory.find_unit(w, [foreign]))

    def test_a_single_appointment_declaration_still_finds_exactly_one(self):
        w = self.load("daily-health-report")
        units = [self.live(f"gui/501/bridge.{w.id}", marker_id=w.id)]
        self.assertEqual(len(inventory.find_units(w, units)), 1)

    def test_find_unit_keeps_answering_with_one_for_the_callers_that_want_one(self):
        w = self.load("daily-health-report")
        units = [self.live(f"gui/501/bridge.{w.id}", marker_id=w.id)]
        self.assertIsNotNone(inventory.find_unit(w, units))

    def test_the_state_key_names_the_unit_and_not_the_declaration(self):
        w = self.load("twice-daily-report")
        keys = {model.state_key(w, a) for a in w.schedule.appointments}
        self.assertEqual(keys, {"twice-daily-report.morning",
                                "twice-daily-report.midday"},
                         "both units share a state key, so their stamps and "
                         "their traces overwrite each other")

    def test_a_single_appointment_keeps_the_bare_declaration_id_as_its_key(self):
        # Nothing already on a machine may be renamed by this feature.
        w = self.load("daily-health-report")
        only = w.schedule.appointments[0]
        self.assertEqual(model.state_key(w, only), w.id)
        self.assertEqual(model.state_key(w, None), w.id)

    def test_two_stamps_of_one_declaration_both_survive_the_read(self):
        made = [
            self.stamp("twice-daily-report",
                       unit_ref="gui/501/bridge.twice-daily-report.morning"),
            self.stamp("twice-daily-report",
                       unit_ref="gui/501/bridge.twice-daily-report.midday"),
        ]
        kept = stamp_mod.by_unit(made)
        self.assertEqual(len(kept), 2,
                         "one stamp replaced the other on the way in, so one "
                         f"unit reads as never provisioned: {kept}")


class BothUnitsGetTheirOwnVerdict(ReconcileBase):
    """Two units, two sentences. One verdict for a pair is a verdict for neither.

    Measured on a real machine, 2026-08-24, right after the two-appointment
    migration: the report carried exactly ONE line about a run that is two
    units, and it happened to be about the later one. The earlier unit was
    never assessed at all, so it could have been unloaded, disabled or drifted
    and the report would have looked exactly the same.

    The claiming was already fixed at that point, which is what makes this the
    dangerous shape rather than the loud one: the missing unit was not reported
    as foreign, it was not reported at all, and a report that stays silent
    about something reads as a report that found nothing wrong with it.
    """

    def two_units(self, matching=False):
        digest = {"marker_digest": DIGEST_A} if matching else {}
        return [
            self.live("gui/501/bridge.twice-daily-report.morning",
                      marker_id="twice-daily-report", **digest),
            self.live("gui/501/bridge.twice-daily-report.midday",
                      marker_id="twice-daily-report", **digest),
        ]

    def findings(self):
        w = self.load("twice-daily-report")
        obs = self.host_obs(units=self.two_units())
        return w, reconcile.classify([w], obs, self.inv(), {})

    def verdicts(self):
        w, findings = self.findings()
        return [f for f in findings if f.workload_id == w.id]

    def test_every_unit_is_named_in_a_verdict_of_its_own(self):
        said = " ".join(getattr(f, "detail", "") for f in self.verdicts())
        for name in ("morning", "midday"):
            self.assertIn(f"twice-daily-report.{name}", said,
                          f"nothing was said about the {name} unit; silence "
                          "about a unit reads as nothing being wrong with it")

    def test_a_unit_is_judged_against_its_own_history(self):
        """The midday unit's failure must not be looked up under the run's name.

        Traces are filed per unit, because the guard names them after its state
        key. Looked up by the DECLARATION instead, the lookup finds nothing at
        all and the failed run vanishes from the report entirely: not reported
        wrong, reported not at all.
        """
        w = self.load("twice-daily-report")
        units = self.two_units(matching=True)
        stamps = {
            u.unit_ref: self.stamp(
                w.id, unit_ref=u.unit_ref,
                state_key=f"{w.id}.{u.unit_ref.rsplit('.', 1)[-1]}")
            for u in units}
        obs = self.host_obs(units=units, stamps=stamps)
        # Only the MIDDAY unit has a history, and its last run failed.
        obs = dataclasses.replace(obs, traces={
            # UTC with a literal Z, which is what wrapper.trace() writes.
            f"{w.id}.midday":
                f"2026-08-24T10:33:00Z workload={w.id} rc=7 "
                f"duration_sec=12 verdict=failed\n"})
        findings = reconcile.classify([w], obs, self.inv(), {})
        said = " ".join(str(getattr(f, "detail", "")) for f in findings)
        self.assertIn(
            "ended with 7", said,
            "the failed run was not reported at all, because its history was "
            f"looked up under the declaration instead of the unit: {said}")
        # And the sentence names WHICH of the two failed. Two appointments
        # answer different people; "the last run of <declaration> failed"
        # leaves a reader unable to tell which of them it was.
        self.assertIn(f"{w.id}.midday ended with 7", said,
                      f"the failure does not say which appointment it was: {said}")
        self.assertNotIn(f"{w.id}.morning ended with", said,
                         "a unit with no history of its own was reported as "
                         "having failed, on its sibling's trace")

    def test_neither_unit_is_reported_as_undeclared(self):
        _, findings = self.findings()
        stray = [f for f in findings
                 if "no declaration claims" in getattr(f, "detail", "")]
        self.assertEqual(stray, [],
                         "a unit was called foreign while its own declaration "
                         f"sits in the repository: {[f.detail for f in stray]}")


class ARecurringRunCanBeOverdueToo(ReconcileBase):
    """`missing` was asked for and never delivered, for every recurring run.

    Measured on the live report on 2026-08-24, right after a customer facing
    report was migrated: it declared `notify_on: [failure, missing]`, its guard
    wrote a trace on every run, and the reconcile line said

        asked for missing detection, and its kind states no cadence this skill
        can work out without a recurrence engine

    Honest, and useless. The declaration asked a question the report answered
    with a shrug, on a run whose silence is exactly what nobody would notice.

    What was actually missing was not a recurrence engine but a MOMENT: when
    was this appointment last due. `previous_due` answers it from the same two
    functions the unit file is rendered from, so the check and the machine
    cannot disagree about when a job fires.

    The tolerance is DERIVED and not chosen: a run due at 06:30 with a deadline
    of an hour cannot be called missing before 07:30, because until then it may
    legitimately still be running. Anything tighter would report a slow run as
    a missing one, which is the false alarm that teaches a reader to ignore the
    real one.
    """

    NOW = "2026-08-24T13:00:00Z"          # Monday, 15:00 Europe/Berlin

    def findings(self, *, trace, now=None):
        w = self.load("twice-daily-report")
        unit_ref = "gui/501/bridge.twice-daily-report.morning"
        unit = self.live(unit_ref, marker_id=w.id)
        stamps = {unit_ref: self.stamp(w.id, unit_ref=unit_ref,
                                       state_key=f"{w.id}.morning")}
        obs = self.host_obs(units=[unit], stamps=stamps)
        obs = dataclasses.replace(obs, traces={f"{w.id}.morning": trace})
        return reconcile.classify([w], obs, self.inv(), {}, now=now or self.NOW)

    def sentences(self, **kw):
        return " ".join(str(getattr(f, "detail", "")) for f in self.findings(**kw))

    def states(self, **kw):
        """The VERDICTS. `overdue` is a state and never appears in the sentence,
        so a test that greps the prose for it is green whatever happens."""
        return {f.state for f in self.findings(**kw)
                if f.workload_id == "twice-daily-report"}

    def line(self, wanted, **kw):
        return [f for f in self.findings(**kw)
                if wanted in str(getattr(f, "detail", ""))]

    def test_a_run_that_missed_its_appointment_is_reported(self):
        # The morning run was due at 06:30 local. Its newest line is from the
        # day before, so it did not run this morning.
        trace = ("2026-08-23T04:30:11Z workload=twice-daily-report rc=0 "
                 "duration_sec=12 verdict=ok\n")
        self.assertIn(model.WorkloadState.overdue, self.states(trace=trace),
                      f"a missed appointment produced no finding: "
                      f"{self.sentences(trace=trace)}")

    def test_the_finding_names_the_moment_it_was_due(self):
        said = self.sentences(
            trace="2026-08-23T04:30:11Z workload=twice-daily-report rc=0 "
                  "duration_sec=12 verdict=ok\n")
        self.assertIn("2026-08-24", said,
                      "the finding does not say WHEN it was due, so nobody can "
                      f"check it: {said}")

    def midday_unit_findings(self, trace, now=None):
        """The MIDDAY unit alone. The morning one is a different question and a
        different trace, and judging this unit against the morning hour is the
        exact confusion this measures."""
        w = self.load("twice-daily-report")
        unit_ref = "gui/501/bridge.twice-daily-report.midday"
        unit = self.live(unit_ref, marker_id=w.id)
        stamps = {unit_ref: self.stamp(w.id, unit_ref=unit_ref,
                                       state_key=f"{w.id}.midday")}
        obs = self.host_obs(units=[unit], stamps=stamps)
        obs = dataclasses.replace(obs, traces={f"{w.id}.midday": trace})
        return reconcile.classify([w], obs, self.inv(), {}, now=now or self.NOW)

    def test_the_midday_unit_is_judged_against_the_midday_hour(self):
        """Each unit against ITS OWN appointment, or the pair is meaningless.

        The trace here is from 06:39, which is a perfectly good morning run and
        no midday run at all. Judged against the morning appointment the unit
        looks healthy; judged against its own, it missed 12:30 by two and a
        half hours.

        Judged the wrong way round the report is exactly inverted: the midday
        unit would be called missing every morning, and the morning unit would
        never be called missing at all.
        """
        states = {f.state for f in self.midday_unit_findings(
            "2026-08-24T04:39:02Z workload=twice-daily-report rc=0 "
            "duration_sec=540 verdict=ok\n")
            if f.workload_id == "twice-daily-report"}
        self.assertIn(
            model.WorkloadState.overdue, states,
            "the midday unit was judged against the morning appointment, so a "
            "morning run counted as proof that the midday run happened")

    def test_a_run_that_kept_its_appointment_is_not_reported(self):
        trace = ("2026-08-24T04:39:02Z workload=twice-daily-report rc=0 "
                 "duration_sec=540 verdict=ok\n")
        self.assertNotIn(model.WorkloadState.overdue, self.states(trace=trace),
                         f"a run that happened was called missing: "
                         f"{self.sentences(trace=trace)}")

    def test_a_run_still_inside_its_deadline_is_not_yet_called_missing(self):
        # 06:35 local, five minutes after the appointment, with an hour of
        # deadline declared. It may simply still be running.
        kw = dict(trace="2026-08-23T04:30:11Z workload=twice-daily-report rc=0 "
                        "duration_sec=12 verdict=ok\n",
                  now="2026-08-24T04:35:00Z")
        self.assertNotIn(model.WorkloadState.overdue, self.states(**kw),
                         "a run was called missing while it could still have "
                         f"been running: {self.sentences(**kw)}")

    def test_the_shrug_is_gone_for_a_translatable_recurrence(self):
        said = self.sentences(
            trace="2026-08-24T04:39:02Z workload=twice-daily-report rc=0 "
                  "duration_sec=540 verdict=ok\n")
        self.assertNotIn("without a recurrence engine", said,
                         "the declaration still gets a shrug for a question it "
                         f"asked and that is now answerable: {said}")

    def test_an_untranslatable_recurrence_still_gets_an_honest_refusal(self):
        # The refusal must survive. Approximating a rule the renderer refuses
        # would put a number nobody declared into a report as a measurement.
        w = self.load("exotic-recurrence")
        obs = self.host_obs(units=[], stamps={})
        said = " ".join(str(getattr(f, "detail", ""))
                        for f in reconcile.classify([w], obs, self.inv(), {},
                                                    now=self.NOW))
        self.assertNotIn("overdue", said,
                         f"a recurrence outside the translated subset was "
                         f"approximated instead of refused: {said}")


class TheMachineCanBeBehindTheFile(ReconcileBase):
    """A stamp proves what the machine was built FROM, never what the file says NOW.

    Both digest comparisons inside `_classify_one` live on the machine: a
    marker inside the unit against a stamp beside it, written in the same
    second by the same provision. Edit a declaration and skip provisioning and
    the two still agree with each other, while the box runs the older file.
    Until this class existed nothing read the declaration on disk, so the whole
    premise of the skill (never trust a declared state, ask the source) stopped
    one step short of asking whether the machine's answer still answered the
    current question.

    The edit used here is `timeout_sec`, because it is the ordinary case: the
    same field was changed on a real declaration the day before this was
    written, and a report that stays green about it is exactly the failure.
    """

    def edited(self, name="calendar-export", timeout_sec=4242):
        """The declaration as the file will look AFTER an edit, not before."""
        w = self.load(name)
        object.__setattr__(w.execution, "timeout_sec", timeout_sec)
        return w

    def obs_for(self, name="calendar-export", **unit_overrides):
        """A stamped, live unit built from the file as it stands on disk."""
        ref = f"gui/{FIXTURE_UID}/bridge.{name}"
        unit = self.live(ref, marker_id=name, **unit_overrides)
        return self.host_obs([unit], {ref: self.stamp(name, unit_ref=ref)})

    def test_an_edited_declaration_is_reported_against_its_stamp(self):
        findings = reconcile.classify([self.edited()], self.obs_for(), self.inv(), {})
        self.assertIn(
            model.WorkloadState.drifted, self.states_for(findings, "calendar-export"),
            "the file on disk no longer matches what the unit was built from, and "
            "nothing on the machine can notice that on its own")

    def test_an_untouched_declaration_is_not_called_drift(self):
        findings = reconcile.classify(
            [self.load("calendar-export")], self.obs_for(), self.inv(), {})
        drift = [f for f in findings
                 if f.workload_id == "calendar-export"
                 and f.state is model.WorkloadState.drifted]
        self.assertEqual(
            drift, [],
            "a correctly provisioned run must stay quiet, or the finding becomes "
            "the noise every reader learns to skip")

    def test_the_finding_says_the_declaration_moved_not_the_machine(self):
        findings = reconcile.classify([self.edited()], self.obs_for(), self.inv(), {})
        drift = [f for f in findings
                 if f.workload_id == "calendar-export"
                 and f.state is model.WorkloadState.drifted]
        self.assertTrue(drift, "no drift finding at all")
        self.assertEqual(
            [f.source for f in drift], ["declaration"],
            "two different faults share the state `drifted`: somebody replaced the "
            "unit on the machine, or we changed the file and never told the machine. "
            "The remedy is the same command, the story is not, and `source` is the "
            "only thing that separates them for a reader")

    def test_the_more_specific_verdict_survives_beside_it(self):
        """The reason this is its own finding and not another link in the chain."""
        w = self.edited("elevated-daemon")
        ref = "system/bridge.elevated-daemon"
        unit = self.live(ref, marker_id="elevated-daemon", running=False,
                         runtime="launchd-system")
        obs = self.host_obs([unit], {ref: self.stamp(
            "elevated-daemon", unit_ref=ref, runtime="launchd-system")})
        states = self.states_for(reconcile.classify([w], obs, self.inv(), {}),
                                 "elevated-daemon")
        self.assertIn(
            model.WorkloadState.stopped, states,
            "a daemon that is not running is the louder fact. Folded into the "
            "verdict chain, the drift check would have returned first and this "
            "would never have been said")
        self.assertIn(
            model.WorkloadState.drifted, states,
            "and the drift is still true at the same time; a chain can only ever "
            "tell one of the two")

    def test_a_run_with_two_units_reports_the_drift_once(self):
        """The file moved once, so it is said once.

        Measured on a real machine on 2026-08-25: a changed declaration
        produced two identical sentences, one per unit, because the check sat
        inside the per-unit loop. It does not belong there. An outdated
        declaration is a fact about the FILE, exactly like `inventory_missing`
        is a fact about the register, and neither is decided per appointment.

        Two identical lines are not a crisis, they are a habit: a report that
        repeats itself is one somebody starts skimming.
        """
        w = self.edited("twice-daily-report")
        refs = ["gui/501/bridge.twice-daily-report.morning",
                "gui/501/bridge.twice-daily-report.midday"]
        units = [self.live(ref, marker_id=w.id) for ref in refs]
        stamps = {ref: self.stamp(w.id, unit_ref=ref,
                                  state_key=f"{w.id}.{ref.rsplit('.', 1)[-1]}")
                  for ref in refs}
        drift = [f for f in reconcile.classify([w], self.host_obs(units, stamps),
                                               self.inv(), {})
                 if f.state is model.WorkloadState.drifted
                 and f.source == "declaration"]
        self.assertEqual(
            len(drift), 1,
            f"the declaration moved once and was reported {len(drift)} times")
        self.assertEqual(
            drift[0].appointment, "",
            "it carries no appointment, because it was never decided per one")

    def test_a_retired_declaration_is_not_measured_against_its_stamp(self):
        w = self.load("voice-channel")
        self.assertTrue(w.is_retired, "fixture is meant to be a retired declaration")
        object.__setattr__(w.execution, "timeout_sec", 4242)
        ref = f"gui/{FIXTURE_UID}/bridge.voice-channel"
        obs = self.host_obs([], {ref: self.stamp("voice-channel", unit_ref=ref)})
        drift = [f for f in reconcile.classify([w], obs, self.inv(), {})
                 if f.workload_id == "voice-channel"
                 and f.state is model.WorkloadState.drifted]
        self.assertEqual(
            drift, [],
            "a run that was deliberately stopped is not supposed to match its "
            "stamp any more; asking sends the reader to provision a retired job")

    def test_no_report_says_both_things_about_one_run(self):
        """The sentence next to it must not claim what it never looked at.

        Found on a real machine the moment the drift finding first existed: the
        report carried `matches the declaration and the stamp` one line above
        `runs from an older declaration than the file on disk`, about the same
        run, in the same run of the same command. Both came from comparisons
        that were individually right; the first was simply describing more than
        it had done.
        """
        said = [str(getattr(f, "detail", ""))
                for f in reconcile.classify([self.edited()], self.obs_for(),
                                            self.inv(), {})
                if f.workload_id == "calendar-export"]
        joined = " | ".join(said)
        self.assertIn("older declaration", joined, "the drift finding is missing")
        self.assertNotIn(
            "matches the declaration", joined,
            f"one report, two sentences, opposite claims about the same run: "
            f"{joined}")

    def test_a_stamp_without_a_digest_is_not_turned_into_drift(self):
        findings = reconcile.classify(
            [self.edited()],
            self.host_obs([self.live(f"gui/{FIXTURE_UID}/bridge.calendar-export",
                                     marker_id="calendar-export")],
                          {f"gui/{FIXTURE_UID}/bridge.calendar-export":
                           self.stamp("calendar-export",
                                      unit_ref=f"gui/{FIXTURE_UID}/bridge.calendar-export",
                                      declaration_digest="")}),
            self.inv(), {})
        drift = [f for f in findings
                 if f.workload_id == "calendar-export"
                 and f.state is model.WorkloadState.drifted
                 and f.source == "declaration"]
        self.assertEqual(
            drift, [],
            "a stamp with no digest cannot say what it was made from; calling that "
            "an outdated declaration invents a comparison that never happened")


class AFindingSaysWhichAppointmentItIsAbout(ReconcileBase):
    """Prose is not an interface.

    A run with several appointments is several units, and the appointment name
    lives today ONLY inside `detail`, spelled into the sentence through the
    state key. Anything that has to route, dampen or count per unit would have
    to take that sentence apart again. A sentence changes for a reader; a
    parser reading it breaks in silence. This skill has already lost a run
    twice to exactly that shape, a second derivation of a name drifting from
    the first.
    """

    REFS = {"morning": "gui/501/bridge.twice-daily-report.morning",
            "midday": "gui/501/bridge.twice-daily-report.midday"}

    def two(self, *, traces=None):
        w = self.load("twice-daily-report")
        units = [self.live(ref, marker_id=w.id) for ref in self.REFS.values()]
        stamps = {ref: self.stamp(w.id, unit_ref=ref,
                                  state_key=f"{w.id}.{name}")
                  for name, ref in self.REFS.items()}
        obs = self.host_obs(units, stamps)
        if traces:
            obs = dataclasses.replace(obs, traces=traces)
        return w, obs

    def named(self, findings, wid="twice-daily-report"):
        """Every verdict about a UNIT of this run.

        `inventory_missing` is excluded on purpose and measured separately
        below: it is decided per DECLARATION, not per unit.
        """
        return {getattr(f, "appointment", None) for f in findings
                if f.workload_id == wid
                and f.state is not model.WorkloadState.inventory_missing}

    def test_each_unit_of_a_run_names_its_own_appointment(self):
        w, obs = self.two()
        found = self.named(reconcile.classify([w], obs, self.inv(), {}))
        self.assertEqual(
            found, {"morning", "midday"},
            "two units produced findings that cannot be told apart by field, "
            "so a caller holding one of them does not know which of two times "
            "it is about")

    def test_a_run_with_one_unnamed_appointment_leaves_the_field_empty(self):
        w = self.load("daily-health-report")
        ref = f"gui/{FIXTURE_UID}/bridge.{w.id}"
        obs = self.host_obs([self.live(ref, marker_id=w.id)],
                            {ref: self.stamp(w.id, unit_ref=ref)})
        found = self.named(reconcile.classify([w], obs, self.inv(), {}), w.id)
        self.assertEqual(
            found, {""},
            "a run with one appointment has no name to carry, and inventing one "
            "would rename something already on a machine")

    def test_an_inventory_finding_is_about_the_run_and_names_no_time(self):
        """The one verdict here that carries no appointment, held as a known limit.

        `inventory_missing` says the machine's register does not list this run.
        It is decided once per declaration, yet its sentence names ONE unit,
        the one that happened to be found first. With two units a register can
        list one label and miss the other, so the sentence is thinner than it
        reads. Leaving the field empty is the honest answer for a verdict that
        was never taken per unit; filling it with the first unit's name would
        make it look measured.

        Written down here so the next person meets it as a decision instead of
        discovering it while acting on the finding.
        """
        w, obs = self.two()
        inventory_findings = [f for f in reconcile.classify([w], obs, self.inv(), {})
                              if f.state is model.WorkloadState.inventory_missing]
        self.assertTrue(inventory_findings, "the fixture no longer produces one")
        self.assertEqual(
            [getattr(f, "appointment", None) for f in inventory_findings], [""],
            "either it started carrying a name, and then it has to be decided "
            "per unit to deserve one, or the field changed shape")

    def test_a_trace_finding_carries_the_appointment_too(self):
        # The two findings the trace brings are exactly the ones a caller would
        # want to route per unit: one time failed, the other did not.
        line = "2026-01-01T00:00:00Z workload=twice-daily-report.midday rc=1 duration_sec=1 verdict=fail\n"
        w, obs = self.two(traces={"twice-daily-report.midday": line})
        failed = [f for f in reconcile.classify([w], obs, self.inv(), {})
                  if f.state is model.WorkloadState.last_run_failed]
        self.assertTrue(failed, "the failing trace produced no finding at all")
        self.assertEqual(
            [getattr(f, "appointment", None) for f in failed], ["midday"],
            "the midday run failed and the morning one did not; a finding that "
            "cannot say which is a finding nobody can act on")


class ALocalReadNeverHappensQuietly(ReconcileBase):
    """A named host read locally has to say so in the report itself.

    It is the one decision in this skill that could answer about the WRONG
    machine while looking entirely normal: everything downstream reads the same
    way whether the answers came over ssh or from the box underfoot. The marker
    that causes it is a file a human writes, so the cheapest guard against a
    wrong one is a reader noticing.

    Measured through `run` and its header rather than through `_coverage`
    alone: the seam between resolving a host and printing what was done is
    exactly where such a sentence gets lost.
    """

    def test_the_report_header_names_the_machine_that_answered_for_itself(self):
        import os
        from unittest import mock
        root = self.repo_with_one()
        home = self.tmpdir()
        (home / ".bridge").mkdir(parents=True, exist_ok=True)
        (home / ".bridge" / "host-identity").write_text("host-a\n", encoding="utf-8")
        runner = RecordingRunner()
        cfg = config.load_config(root)
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            rep = reconcile.run(root, cfg, hosts=["host-a"], probe=False, runner=runner)
        self.assertIn(
            "locally", rep.header.lower(),
            f"the run answered about host-a from this machine and the report "
            f"does not mention it:\n{rep.header}")

    def repo_with_one(self):
        """A repo that actually carries a declaration on host-a.

        Without one, `run` never resolves a host at all and the header says so,
        which would have made the test above pass for the wrong reason.
        """
        import shutil
        root = make_repo(self.tmpdir())
        target = root / "workflow" / "workloads"
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy(CORPUS / "calendar-export.yaml", target / "calendar-export.yaml")
        return root

    def test_an_ordinary_run_does_not_claim_a_local_read(self):
        root = self.repo_with_one()
        runner = RecordingRunner()
        cfg = config.load_config(root)
        rep = reconcile.run(root, cfg, hosts=["host-a"], probe=False, runner=runner)
        self.assertNotIn(
            "locally", rep.header.lower(),
            "the control: a sentence that is always there says nothing")


class ARenamedUnitIsNotSilently(ReconcileBase):
    """Provisioned under one name, would now be created under another.

    Reachable since 2026-08-25, when `workloads.label_prefix` was finally wired
    to the backends: until then the knob was read and never applied, so it could
    not move a name. Making it live makes this trap live with it, which is why
    the guard belongs to the same change.

    Nothing else in the module can see it. `_declaration_drift` compares the
    DECLARATION digest, and changing a configuration moves no declaration.
    Every comparison in the classify chain came off the machine and agrees with
    itself. So the report would read in_sync while the very next `provision`
    created a SECOND unit beside the running one and left the first unmanaged.
    """

    def stamped_under(self, name, workload_id):
        ref = f"gui/{FIXTURE_UID}/{name}"
        return ref, self.host_obs([], {ref: self.stamp(workload_id, unit_ref=ref)})

    def findings_for(self, w, obs, wid):
        """Only the NAMING drift, not every drift.

        The stamp helper carries a synthetic declaration digest, so
        `_declaration_drift` fires in these fixtures too. A control that counted
        every `drifted` finding would be red for the wrong reason and would
        make the three cases above prove nothing about this guard.
        """
        return [f for f in reconcile.classify([w], obs, self.inv(), {})
                if f.workload_id == wid
                and f.state is model.WorkloadState.drifted
                and "would now be created as" in (f.detail or "")]

    def test_the_rename_is_reported(self):
        w = model.load_declaration(DERIVED / "adopted-prefix-daemon.yaml")
        _, obs = self.stamped_under("bridge.legacy-poller", "legacy-poller")
        drift = self.findings_for(w, obs, "legacy-poller")
        self.assertTrue(drift, "a run that would be created under a different "
                               "name than it carries was reported as fine")

    def test_it_names_both_the_old_and_the_new_name(self):
        w = model.load_declaration(DERIVED / "adopted-prefix-daemon.yaml")
        _, obs = self.stamped_under("bridge.legacy-poller", "legacy-poller")
        detail = " ".join(f.detail for f in self.findings_for(w, obs, "legacy-poller"))
        self.assertIn("bridge.legacy-poller", detail)
        self.assertIn("org.example.scheduler.legacy-poller", detail)

    def test_it_warns_that_provisioning_would_ADD_a_unit(self):
        w = model.load_declaration(DERIVED / "adopted-prefix-daemon.yaml")
        _, obs = self.stamped_under("bridge.legacy-poller", "legacy-poller")
        hint = " ".join(f.hint or "" for f in self.findings_for(w, obs, "legacy-poller"))
        self.assertIn("ADD", hint)

    def test_a_name_that_still_matches_is_silent(self):
        # The control. Without it a guard that fires on everything would pass
        # all three cases above and prove nothing.
        w = model.load_declaration(DERIVED / "adopted-prefix-daemon.yaml")
        _, obs = self.stamped_under("org.example.scheduler.legacy-poller",
                                    "legacy-poller")
        self.assertEqual(self.findings_for(w, obs, "legacy-poller"), [])


class ARunWithTwoAppointmentsWritesTwoTraces(ReconcileBase):
    """The guard names a trace after the STATE KEY, not after the id.

    So a run with two appointments writes `<id>.morning.trace` and
    `<id>.midday.trace`, and NEITHER of them is called `<id>.trace`. Reading
    the bare id therefore found nothing for such a run: on the live page every
    scheduled job carried a diamond for its last firing and the one with two
    appointments carried none, which reads as a job that has never fired.
    """

    def workload(self):
        return model.load_declaration(DERIVED / "twice-daily-report.yaml")

    def keys(self, w):
        from engine.backends import base as base_mod

        return [model.state_key(w, a) for a in (base_mod.appointments_of(w) or (None,))]

    def obs(self, traces):
        import types

        return types.SimpleNamespace(traces=dict(traces))

    def test_the_premise_the_fixture_really_has_two_appointments(self):
        keys = self.keys(self.workload())
        self.assertEqual(len(keys), 2, f"the fixture has {len(keys)} appointment(s)")

    def test_no_trace_is_filed_under_the_bare_id(self):
        w = self.workload()
        self.assertNotIn(w.id, self.keys(w),
                         "if a bare id were among the keys this case could "
                         "pass while the bug it names is still there")

    def test_both_appointment_traces_are_read(self):
        w = self.workload()
        erste, zweite = self.keys(w)
        texts = reconcile._traces_of(w, self.obs({
            erste: "2026-08-26T06:30:00Z workload=x rc=0 duration_sec=1 verdict=ok\n",
            zweite: "2026-08-26T12:30:00Z workload=x rc=1 duration_sec=1 verdict=failed\n",
        }))
        self.assertEqual(set(texts), {erste, zweite})
        self.assertIn("verdict=failed", texts[zweite])

    def test_the_newest_across_both_is_the_last_run(self):
        w = self.workload()
        erste, zweite = self.keys(w)
        texts = reconcile._traces_of(w, self.obs({
            erste: "2026-08-26T06:30:00Z workload=x rc=0 duration_sec=1 verdict=ok\n",
            zweite: "2026-08-26T12:30:00Z workload=x rc=1 duration_sec=1 verdict=failed\n",
        }))
        newest = reconcile._newest_trace("\n".join(texts.values()))
        self.assertIsNotNone(newest, "a run with two appointments got no last run at all")
        when, rc = newest
        self.assertEqual(when.strftime("%H:%M"), "12:30")
        self.assertEqual(rc, 1)


class TheStripIsWhatTheMachineWroteDown(ReconcileBase):
    """A history, and every part of it taken from the line rather than rebuilt."""

    def zeile(self, stamp, rc, verdict):
        return f"{stamp} workload=x rc={rc} duration_sec=2 verdict={verdict}"

    def test_it_reads_oldest_first(self):
        strip = reconcile._trace_strip({"x": "\n".join([
            self.zeile("2026-08-26T09:00:00Z", 0, "ok"),
            self.zeile("2026-08-24T09:00:00Z", 0, "ok"),
            self.zeile("2026-08-25T09:00:00Z", 0, "ok"),
        ])})
        self.assertEqual([e[0][:10] for e in strip],
                         ["2026-08-24", "2026-08-25", "2026-08-26"],
                         "the strip is not in time order, so a reader counting "
                         "backwards counts the wrong way")

    def test_the_verdict_comes_from_the_line_and_is_not_derived_from_rc(self):
        # `expired` and a non zero return are DIFFERENT facts: one says a
        # deadline cut the run off, the other says the program said no.
        # Rebuilding the word from rc would lose that, and the two look
        # identical afterwards.
        strip = reconcile._trace_strip({"x": self.zeile("2026-08-26T09:00:00Z", 143, "expired")})
        self.assertEqual(strip[0][2], "expired")

    def test_it_keeps_the_newest_and_says_how_many(self):
        viele = "\n".join(self.zeile(f"2026-07-{d:02d}T09:00:00Z", 0, "ok")
                          for d in range(1, 31))
        strip = reconcile._trace_strip({"x": viele})
        self.assertEqual(len(strip), reconcile.STRIP_MAX)
        self.assertEqual(strip[-1][0][:10], "2026-07-30",
                         "the cap threw away the newest runs instead of the oldest")

    def test_each_entry_names_the_file_it_came_from(self):
        strip = reconcile._trace_strip({
            "x.morning": self.zeile("2026-08-26T06:00:00Z", 0, "ok"),
            "x.midday": self.zeile("2026-08-26T12:00:00Z", 1, "failed"),
        })
        self.assertEqual(strip[-1][3], "x.midday",
                         '"the midday one failed" is a different sentence from '
                         '"it failed"')

    def test_a_line_nobody_can_parse_is_dropped_and_not_guessed_at(self):
        strip = reconcile._trace_strip({"x": "not a trace line at all\n"
                                             + self.zeile("2026-08-26T09:00:00Z", 0, "ok")})
        self.assertEqual(len(strip), 1)



class TheMachineHasToHaveBeenUp(ReconcileBase):
    """A run due while the box was OFF left no line because nothing was running.

    `overdue` there is a false accusation, and the loudest one this skill has:
    severity high, with an instruction to bootout and bootstrap a unit that is
    perfectly fine. Taken from the neighbouring operations page on 2026-08-27,
    which had carried the distinction from the start ("vor dem letzten
    Hochfahren, kein Urteil moeglich") while this one had not.

    Every case asserts its PREMISE first. Without that, a guard that silences
    everything reads exactly like a guard that silences the right thing, and
    this one silences the loudest verdict in the skill.
    """

    STATE_DIR = f"{FIXTURE_HOME}/.bridge/workloads"

    def trace_line(self, wid, *, rc=0, when="2026-08-23T08:00:00Z", verdict="ok"):
        return f"{when} workload={wid} rc={rc} duration_sec=1 verdict={verdict}\n"

    def scene(self, wid, traces, *, now, booted=None):
        w = self.load(wid)
        unit = self.live(f"gui/{FIXTURE_UID}/bridge.{wid}", marker_id=wid)
        obs = self.host_obs([unit], {wid: self.stamp(wid)})
        obs = dataclasses.replace(obs, traces=traces)
        if booted is not None:
            obs = dataclasses.replace(obs, booted_at=booted)
        return [f for f in reconcile.classify([w], obs, self.inv(), {}, now=now)
                if f.workload_id == wid]

    # -- an appointment ----------------------------------------------------
    #: 06:10 Europe/Berlin, so 04:10Z. A week-old line and a Sunday morning
    #: `now` puts the last firing well behind it.
    APPOINTMENT = dict(wid="daily-health-report", now="2026-08-30T08:00:00Z")

    def appointment(self, booted=None):
        wid = self.APPOINTMENT["wid"]
        return self.scene(wid, {wid: self.trace_line(wid)},
                          now=self.APPOINTMENT["now"], booted=booted)

    def test_premise_without_a_boot_moment_it_is_still_overdue(self):
        states = {f.state for f in self.appointment()}
        self.assertIn(model.WorkloadState.overdue, states,
                      "premise: this scene no longer produces the verdict the "
                      "guard below is supposed to hold back, so nothing here "
                      "measures the guard")

    def test_an_appointment_that_fell_while_the_machine_was_off_is_not_overdue(self):
        states = {f.state for f in self.appointment(booted="2026-08-30T05:00:00Z")}
        self.assertNotIn(
            model.WorkloadState.overdue, states,
            "the machine came up an hour AFTER the appointment and the run was "
            "still reported as having missed it, at severity high, with an "
            "instruction to reload a unit that is fine")

    def test_it_says_so_rather_than_falling_silent(self):
        """"Nothing can be judged" and "nothing is wrong" are different answers
        and must never print the same."""
        found = self.appointment(booted="2026-08-30T05:00:00Z")
        states = {f.state for f in found}
        self.assertIn(model.WorkloadState.unknown, states,
                      "the verdict was dropped instead of replaced, so a run "
                      "nobody can judge reads as a healthy one")
        said = " ".join(str(f.detail) for f in found)
        self.assertIn("came up at", said,
                      "the sentence does not name the boot moment, so a reader "
                      "cannot check the claim that produced the silence")

    def test_a_machine_that_was_up_the_whole_time_is_still_judged(self):
        # Well before the run's own newest line, so it is before the last
        # firing whichever weekday that turns out to be. Picking a boot moment
        # by eye from the hour alone got this wrong once: the run does not fire
        # every day, so "the morning of the same day" was still AFTER the last
        # appointment and the guard fired correctly on a case meant to prove it
        # does not.
        states = {f.state for f in self.appointment(booted="2026-08-01T00:00:00Z")}
        self.assertIn(
            model.WorkloadState.overdue, states,
            "the boot moment lies before the appointment, so the machine was "
            "up for it and the silence is the run's own")

    def test_an_unreadable_boot_moment_changes_no_verdict(self):
        """Empty and unreadable both mean "not known", and not known is the
        answer that changes nothing. Anything else lets one bad line from one
        machine silence a report."""
        for bad in ("", "yesterday", "2026-13-45T99:99:99Z"):
            states = {f.state for f in self.appointment(booted=bad)}
            self.assertIn(model.WorkloadState.overdue, states,
                          f"a boot moment of {bad!r} silenced a real verdict")

    # -- and it may only ever take a verdict AWAY --------------------------
    def test_a_silence_that_was_already_justified_stays_a_silence(self):
        """The half of this guard that was wrong for half an hour.

        Written at the top of the function it fired on every path that was
        ALREADY silent for a reason of its own, and turned a justified silence
        into a sentence. Measured on the live page on 2026-08-27: one weekly
        report, provisioned on the Wednesday AFTER its Sunday appointment,
        which the provisioning rule had correctly said nothing about, acquired
        a verdict the moment this shipped. A guard against a false claim that
        manufactures a second claim is not a guard.
        """
        wid = self.APPOINTMENT["wid"]
        w = self.load(wid)
        unit = self.live(f"gui/{FIXTURE_UID}/bridge.{wid}", marker_id=wid)
        # No trace at all, and provisioned AFTER the last appointment: the
        # older rule already answers this one, and answers it with silence.
        obs = self.host_obs([unit], {wid: self.stamp(
            wid, provisioned_at="2026-08-30T09:00:00+02:00")})
        obs = dataclasses.replace(obs, traces={},
                                  booted_at="2026-08-30T05:00:00Z")
        found = [f for f in reconcile.classify([w], obs, self.inv(), {},
                                               now=self.APPOINTMENT["now"])
                 if f.workload_id == wid]
        said = " ".join(str(f.detail) for f in found)
        self.assertNotIn(
            "came up at", said,
            "a run nothing was being claimed about acquired a sentence saying "
            "nothing can be claimed about it")
        self.assertNotIn(model.WorkloadState.overdue, {f.state for f in found},
                         "premise: the older rule no longer holds this one back")

    def test_a_healthy_cadence_gains_nothing_after_a_reboot(self):
        """The same half, on the other branch, and worse there: every declared
        cadence on a machine rebooted five minutes ago would have grown one
        sentence saying nothing was wrong with it."""
        wid = self.CADENCE["wid"]
        found = self.scene(
            wid,
            # A line from five minutes ago: healthy by any reading.
            {wid: self.trace_line(wid, when="2026-08-23T08:55:00Z")},
            now=self.CADENCE["now"], booted="2026-08-23T08:55:00Z")
        said = " ".join(str(f.detail) for f in found)
        self.assertNotIn(
            "came up at", said,
            "a healthy run on a freshly booted machine was told that its "
            "silence says nothing, and it had not been silent")

    # -- a cadence ---------------------------------------------------------
    #: calendar-export declares every_sec 900, so the window is 1800s. The
    #: newest line is at 08:00Z and `now` is an hour past it.
    CADENCE = dict(wid="calendar-export", now="2026-08-23T09:00:00Z")

    def cadence(self, booted=None):
        wid = self.CADENCE["wid"]
        return self.scene(wid, {wid: self.trace_line(wid)},
                          now=self.CADENCE["now"], booted=booted)

    def test_premise_a_cadence_that_stopped_is_still_overdue(self):
        self.assertIn(model.WorkloadState.overdue,
                      {f.state for f in self.cadence()},
                      "premise: this scene no longer produces the verdict")

    def test_a_cadence_is_not_judged_before_the_machine_has_been_up_that_long(self):
        """A machine cannot have produced a longer history than its own uptime.
        Judging anyway reports every job on the box as overdue for the first
        half hour after a reboot, which is when a reader most needs the report
        to be worth reading."""
        states = {f.state for f in self.cadence(booted="2026-08-23T08:55:00Z")}
        self.assertNotIn(
            model.WorkloadState.overdue, states,
            "the machine has been up for five minutes and a thirty minute "
            "silence was held against the run")
        self.assertIn(model.WorkloadState.unknown, states,
                      "the verdict was dropped rather than replaced")

    def test_a_cadence_on_a_long_running_machine_is_still_judged(self):
        self.assertIn(
            model.WorkloadState.overdue,
            {f.state for f in self.cadence(booted="2026-08-23T05:00:00Z")},
            "the machine has been up four hours and a thirty minute silence "
            "from a fifteen minute cadence is the absence the trace exists for")


class WhenDidThisMachineComeUp(ReconcileBase):
    """The read itself, and the trap that makes a wrong answer look right.

    macOS answers `{ sec = 1787577316, usec = 750092 } Mon Aug 24 15:15:16 2026`.
    The obvious extraction, `.*sec *= *\\([0-9]*\\)`, is GREEDY: it walks past
    `sec` and matches inside `usec`. Measured on two machines on 2026-08-27,
    where it returned 750092 and 149827, and both look like a plausible epoch
    at a glance.

    So the shell only fetches and the parsing happens in Python, where the same
    expression is correct without any care at all, because `re.search` matches
    leftmost. The word boundary in it is a belt and NOT the guard: the mutation
    battery removed it on 2026-08-27 and every case here stayed green, which is
    the honest answer and the reason this docstring no longer claims otherwise.
    """

    MACOS = "{ sec = 1787577316, usec = 750092 } Mon Aug 24 15:15:16 2026\n"
    LINUX = "1787577316\n"

    def read(self, stdout, raises=None):
        runner = RecordingRunner()
        runner.add("kern.boottime", FakeCompleted(stdout=stdout), raises=raises)
        return reconcile.read_boot_time(self.host(), timeout_sec=10, runner=runner)

    def test_the_seconds_are_read_and_never_the_microseconds(self):
        self.assertEqual(self.read(self.MACOS), "2026-08-24T13:15:16Z",
                         "the microsecond field was read as an epoch, which "
                         "lands in 1970 and silences every verdict on the box")

    def test_a_bare_epoch_is_read_too(self):
        self.assertEqual(self.read(self.LINUX), "2026-08-24T13:15:16Z",
                         "the other platform this skill carries answers a bare "
                         "integer and was not understood")

    def test_both_platforms_answer_the_same_moment(self):
        """One step asks both, because a machine only answers one of them and
        the other writes nothing. If the two ever parsed differently, a report
        about a mac and a report about a linux box would disagree about the
        same instant."""
        self.assertEqual(self.read(self.MACOS), self.read(self.LINUX))

    def test_nothing_readable_is_empty_and_never_a_guess(self):
        for text in ("", "no such sysctl\n", "sec = later\n", "42\n"):
            self.assertEqual(
                self.read(text), "",
                f"{text!r} produced a boot moment, and a guessed one is worse "
                "than none: it silences real alarms on a machine that never "
                "went down")

    def test_a_machine_that_will_not_answer_is_not_an_error(self):
        """One unreadable fact must not abort a report about everything else on
        the box."""
        self.assertEqual(self.read("", raises=errors.StepFailed("no")), "")

    def test_the_observation_carries_it(self):
        runner = RecordingRunner()
        runner.add("launchctl list", FakeCompleted(stdout="uid=4242\n"))
        runner.add("print-disabled", completed_from("launchctl-print-disabled.txt"))
        runner.add("kern.boottime", FakeCompleted(stdout=self.MACOS))
        runner.add("cat", FakeCompleted(stdout=stamp_json()))
        root = make_repo(self.tmpdir())
        cfg = config.load_config(root)
        obs = reconcile.observe_host(self.host(), cfg, timeout_sec=10, runner=runner)
        self.assertEqual(
            getattr(obs, "booted_at", ""), "2026-08-24T13:15:16Z",
            "the machine was asked when it came up and the answer went nowhere")


class AnAbsenceSomebodyDecidedIsNotDrift(ReconcileBase):
    """An inventory entry that says why it is gone has not drifted away.

    Measured against a live inventory on 2026-08-27: of the sixteen entries
    the page reported as drifted, NINE carried
    `intentionally_absent` with a date and a reason a person had written down,
    among them a security bar and two backups parked on a failing disk. The
    page called nine decisions unfinished business, and the advice under each
    of them was to delete the record of the decision.

    The field is the CORE one from open-bridge#159 and nothing else. The flat
    German keys of this instance's own inventory stay unread here on purpose: a
    `scope: core` skill that learns one operator's vocabulary has stopped being
    generic, and the nested block is the half the schema checks.
    """

    def deltas(self, **kw):
        return inventory.inventory_delta(self.host_obs(**kw), self.inv(), [])

    def test_a_decided_absence_is_not_reported_as_drift(self):
        stale = {f.workload_id for f in self.deltas()
                 if f.state == model.WorkloadState.inventory_stale}
        self.assertNotIn("parked-on-purpose", stale)

    def test_it_stays_on_the_page_with_its_date_and_its_reason(self):
        mine = [f for f in self.deltas() if f.workload_id == "parked-on-purpose"]
        self.assertEqual(len(mine), 1, f"expected exactly one finding, got {mine}")
        self.assertIs(mine[0].state, model.WorkloadState.intentionally_absent)
        self.assertIn("2026-08-06", mine[0].detail)
        self.assertIn("the reason a reader needs", mine[0].detail)

    def test_nobody_is_asked_to_delete_the_record_of_a_decision(self):
        mine = [f for f in self.deltas() if f.workload_id == "parked-on-purpose"]
        self.assertNotIn("drop the entry", " ".join(f.hint or "" for f in mine))

    def test_a_decided_absence_wakes_nobody(self):
        mine = [f for f in self.deltas() if f.workload_id == "parked-on-purpose"]
        self.assertEqual({f.severity for f in mine}, {model.Severity.info})

    def test_a_block_nobody_can_read_does_not_silence_the_drift(self):
        """`intentionally_absent: "parkiert"`, written by hand.

        A typo that switches a report off is the dangerous direction, and it is
        the same rule the operations evaluator settled on in
        scripts/bridge-ops-evaluate.py: a non mapping is not a decision.
        """
        stale = {f.workload_id for f in self.deltas()
                 if f.state == model.WorkloadState.inventory_stale}
        self.assertIn("broken-absence", stale)

    def test_the_flat_keys_of_one_instance_are_not_the_core_field(self):
        stale = {f.workload_id for f in self.deltas()
                 if f.state == model.WorkloadState.inventory_stale}
        self.assertIn("voice-channel", stale,
                      "geparkt_seit/geparkt_grund is this instance's own "
                      "vocabulary; a core skill may not learn it")

    def test_a_look_that_missed_a_runtime_still_names_the_decided_ones(self):
        """The unlooked guard holds back a CLAIM ABOUT THE MACHINE.

        A decided absence makes no such claim: it repeats what the file says.
        Holding it back with the others would lose the one row that needed no
        looking at all.
        """
        found = {f.workload_id for f in self.deltas(failed_runtimes={"launchd-system"})}
        self.assertIn("parked-on-purpose", found)


class NothingCanRunWhileItIsOnTheOffList(ReconcileBase):
    """`in_sync` was a statement about bytes, and it was the only one made.

    A unit can match its stamp and the artifact it was rendered from, sit in
    the machine's persistent off-list, and never start again. Nothing in this
    report asked. The list was read by `provision`, which refuses to switch on
    what a person switched off, and never by the pass that says how the machine
    is, so the two disagreed by construction.

    It is the persistent list precisely because a stop written there SURVIVES A
    REBOOT: this skill's own `retire` uses bootout plus disable for that reason,
    and an inventory on this network records a run stopped with bootout alone
    that came back at the next reboot and sent seven messages nobody wanted. No
    declared run is on the list today; the guard is for the direction the page
    fails in, which is silently claiming health.
    """

    def obs(self, *, off=True, wid="calendar-export"):
        unit = self.live(f"gui/{FIXTURE_UID}/bridge.{wid}", marker_id=wid)
        return self.host_obs([unit], {wid: self.stamp(wid)},
                             disabled={unit.unit_ref: off})

    def findings(self, *, off=True, workloads=None):
        w = self.load("calendar-export")
        return reconcile.classify(workloads if workloads is not None else [w],
                                  self.obs(off=off), self.inv(), {})

    def states(self, **kw):
        return {f.state for f in self.findings(**kw)
                if f.workload_id == "calendar-export"}

    def test_a_declared_unit_on_the_off_list_is_reported(self):
        self.assertIn(model.WorkloadState.disabled, self.states(),
                      "the machine says it will not start it and the page "
                      "said in_sync")

    def test_it_says_that_a_reboot_will_not_change_it(self):
        said = " ".join(f.detail for f in self.findings()
                        if f.state == model.WorkloadState.disabled)
        self.assertIn("reboot", said,
                      "without it a reader tries the obvious repair first, "
                      "and the obvious repair is the one thing that cannot work")

    def test_it_needs_a_person(self):
        sev = {f.severity for f in self.findings()
               if f.state == model.WorkloadState.disabled}
        self.assertEqual(sev, {model.Severity.medium})

    def test_a_unit_that_is_not_on_the_list_gains_nothing(self):
        self.assertNotIn(model.WorkloadState.disabled, self.states(off=False))

    def test_an_unread_list_is_not_read_as_permission(self):
        """None means nobody answered, and it must never mean `not disabled`.

        The same distinction `parse_disabled` already draws for provision: not
        asked is not absent.
        """
        self.assertNotIn(model.WorkloadState.disabled, self.states(off=None))

    def test_a_retired_declaration_gains_nothing(self):
        """A retired run is disabled ON PURPOSE, by this skill, in that order.

        Reporting it would turn every clean retirement into a finding that
        needs a person, which is how a page teaches a reader to skip its own
        loudest section.
        """
        retired = dataclasses.replace(
            self.load("calendar-export"),
            retired=model.Retired(at="2026-08-01", reason="superseded"))
        states = {f.state for f in self.findings(workloads=[retired])
                  if f.workload_id == "calendar-export"}
        self.assertNotIn(model.WorkloadState.disabled, states)

    def test_a_unit_that_is_gone_and_on_the_list_says_both(self):
        """The second case, and the one that is INVISIBLE in `launchctl list`.

        A unit booted out and disabled is not loaded, so a read driven by live
        units never asks about it. It is reported `absent`, at high, with a
        hint to provision it again, and `provision` then refuses for exactly
        the reason nothing had read. Two sentences, because they are two facts:
        it is not there, and it is not coming back on its own.
        """
        wid = "calendar-export"
        stamp = self.stamp(wid)
        obs = self.host_obs(stamps={wid: stamp},
                            disabled={stamp.unit_ref: True})
        states = {f.state for f in reconcile.classify([self.load(wid)], obs,
                                                      self.inv(), {})
                  if f.workload_id == wid}
        self.assertIn(model.WorkloadState.absent, states)
        self.assertIn(model.WorkloadState.disabled, states)

    def late(self, *, off, wid="calendar-export"):
        """A run whose last line is from January, with the off-list either way."""
        unit = self.live(f"gui/{FIXTURE_UID}/bridge.{wid}", marker_id=wid)
        obs = self.host_obs([unit], {wid: self.stamp(wid)},
                            disabled={unit.unit_ref: True} if off else {})
        obs = dataclasses.replace(obs, traces={
            wid: f"2026-01-01T00:00:00Z workload={wid} rc=0 "
                 "duration_sec=1 verdict=ok\n"})
        return reconcile.classify([self.load(wid)], obs, self.inv(), {})

    def test_a_silence_from_a_unit_nothing_will_start_is_not_an_overdue(self):
        """The loudest verdict here, aimed at the one thing that cannot help.

        `overdue` is high and its hint says to bootout and bootstrap the unit.
        Both are wrong for a unit somebody switched off: its bytes are already
        correct, and reprovisioning it is refused by `provision` for exactly
        the reason this finding names.
        """
        states = {f.state for f in self.late(off=True)}
        self.assertNotIn(model.WorkloadState.overdue, states)
        self.assertIn(model.WorkloadState.disabled, states)

    def test_and_it_says_so_rather_than_going_quiet(self):
        said = " ".join(f.detail for f in self.late(off=True)
                        if f.state == model.WorkloadState.unknown)
        self.assertIn("off-list", said,
                      "`nothing can be judged` and `nothing is wrong` must "
                      "never print the same")

    def test_a_run_nobody_switched_off_is_still_called_late(self):
        """The counterweight. A guard that swallows every overdue is worse
        than the false accusation it was built to stop."""
        self.assertIn(model.WorkloadState.overdue,
                      {f.state for f in self.late(off=False)})


class TheOffListIsAskedOncePerQUESTION(ReconcileBase):
    """One call per DISTINCT question, not one per unit.

    The two runtimes ask it differently, and that difference is real rather
    than cosmetic: launchd keeps the list per domain, so one read answers for
    every unit in it, while systemd keeps it per unit. Memoising the ANSWER by
    the argv gets both right without either backend having to describe itself:
    identical questions are asked once, and different questions are asked.

    Without it a machine carrying thirty declarations would take thirty
    identical round trips, over ssh, on every render of the page.
    """

    def ask(self, refs, runtime="launchd"):
        runner = RecordingRunner()
        runner.add("print-disabled", completed_from("launchctl-print-disabled.txt"))
        stamps = {f"w{i}": self.stamp(f"w{i}", unit_ref=ref, runtime=runtime)
                  for i, ref in enumerate(refs)}
        out = reconcile.read_disabled(self.host(), stamps,
                                      timeout_sec=10, runner=runner)
        return out, runner

    def test_one_domain_is_asked_once_for_all_of_its_units(self):
        _, runner = self.ask([f"gui/{FIXTURE_UID}/bridge.one",
                              f"gui/{FIXTURE_UID}/bridge.two",
                              f"gui/{FIXTURE_UID}/bridge.three"])
        asked = [c for c in runner.calls if "print-disabled" in c["joined"]]
        self.assertEqual(len(asked), 1, f"asked {len(asked)} times: {runner.joined_calls}")

    def test_and_every_one_of_them_gets_its_own_answer(self):
        out, _ = self.ask([f"gui/{FIXTURE_UID}/bridge.voice-channel",
                           f"gui/{FIXTURE_UID}/bridge.other"])
        self.assertIs(out[f"gui/{FIXTURE_UID}/bridge.voice-channel"], True)
        self.assertIs(out[f"gui/{FIXTURE_UID}/bridge.other"], False)

    def test_a_second_domain_is_a_second_question(self):
        _, runner = self.ask([f"gui/{FIXTURE_UID}/bridge.one", "system/com.example.mesh"])
        asked = [c for c in runner.calls if "print-disabled" in c["joined"]]
        self.assertEqual(len(asked), 2, "two domains were answered from one read")

    def test_only_what_a_stamp_claims_is_asked_about(self):
        """A machine answers with a thousand units nobody here declared.

        Asking the off-list about every one of them is the same mistake
        `_read_markers` already refuses to make, and on a real box it would be
        the difference between one call and a thousand. Measured on one such
        machine: 1019 live units, 31 of them claimed by a stamp.
        """
        runner = RecordingRunner()
        runner.add("print-disabled", completed_from("launchctl-print-disabled.txt"))
        mine = f"gui/{FIXTURE_UID}/bridge.calendar-export"
        out = reconcile.read_disabled(
            self.host(),
            {"calendar-export": self.stamp("calendar-export", unit_ref=mine)},
            timeout_sec=10, runner=runner)
        self.assertIn(mine, out)
        self.assertNotIn("gui/4242/com.example.mesh", out)

    def test_a_machine_that_will_not_answer_is_not_an_error(self):
        runner = RecordingRunner()
        runner.add("print-disabled", raises=errors.StepFailed("no such domain"))
        ref = f"gui/{FIXTURE_UID}/bridge.calendar-export"
        out = reconcile.read_disabled(
            self.host(),
            {"calendar-export": self.stamp("calendar-export", unit_ref=ref)},
            timeout_sec=10, runner=runner)
        self.assertEqual(out, {},
                         "one unreadable fact aborted a report about everything "
                         "else on the box")

    def test_the_observation_carries_the_answer_and_not_just_the_field(self):
        """An empty dict is what an unwired read returns too.

        The first version of this asserted the TYPE, which a defaulted field
        satisfies without anything ever having asked the machine.
        """
        runner = RecordingRunner()
        runner.add("print-disabled", completed_from("launchctl-print-disabled.txt"))
        # One step asks the uid and lists in the same breath, so one stdout
        # carries both. Without the uid the domain is `gui//` and no unit
        # matches its own stamp, which is a green test measuring nothing.
        runner.add("launchctl list", FakeCompleted(
            stdout="uid=4242\n" + read_output("launchctl-list.txt")))
        runner.add("kern.boottime", FakeCompleted(stdout="1787577316\n"))
        runner.add("cat", FakeCompleted(stdout=stamp_json()))
        root = make_repo(self.tmpdir())
        cfg = config.load_config(root)
        obs = reconcile.observe_host(self.host(), cfg, timeout_sec=10, runner=runner)
        self.assertIn("print-disabled", runner.joined_calls,
                      "the off-list was never asked for")
        self.assertEqual(dict(getattr(obs, "disabled", {})),
                         {"gui/4242/bridge.calendar-export": False},
                         "the machine answered and the answer went nowhere")


class OneRootOwnedUnitDoesNotBlindTheHost(ReconcileBase):
    """Issue #179: one `launchd-system` stamp took down the view of every run.

    The read of the persistent off-list inherited `requires_elevation` from the
    backend, and on the system backend that flag is there for the WRITE plan.
    The runner refused, as it must, and the refusal was not caught, so
    `observe_host` raised and `reconcile`, `view` and `publish` printed nothing
    for the host at all. Measured on a host with 57 declarations: two system
    domain entries, zero output for the other 55, and a page that went stale
    rather than red.

    Reading a domain's off-list answers unprivileged, the system domain
    included: `launchctl print-disabled system` returned 0 as an ordinary user
    on the two machines it was asked on. So the read carries no elevation, and a
    read that ever does need it degrades to ONE unanswered entry with a note,
    the way an unreachable host already degrades to `unknown`.
    """

    MINE = f"gui/{FIXTURE_UID}/bridge.calendar-export"
    ROOTS = "system/com.example.mesh"

    class RefusesLikeTheRealExecutor(RecordingRunner):
        """RecordingRunner, plus the one refusal `exec.run_step` makes before anything runs.

        Every other runner in this suite answers an elevated step as if it had run.
        So a READ that asked for elevation passed here and aborted on a machine:
        nothing in the suite could see the difference between the two.
        """

        def __call__(self, argv=None, *args, step=None, **kwargs):
            real = step if step is not None else (argv if hasattr(argv, "argv") else None)
            if getattr(real, "requires_elevation", False):
                raise errors.ElevationRequired(step=" ".join(str(a) for a in real.argv),
                                               purpose=real.purpose)
            return super().__call__(argv, *args, step=step, **kwargs)


    class ReadsOnlyWithElevation:
        """A backend whose off-list genuinely cannot be read without a person."""

        name = "elevated-read"
        platforms = ()

        def disabled_list_steps(self, a, h):
            return (model.Step(argv=("read-root-only-off-list",),
                               purpose="read an off-list only root may read",
                               requires_elevation=True),)

        def parse_disabled(self, outs, unit_ref):
            return False

    def system_stamp(self):
        raw = json.loads(stamp_json())
        raw.update(workload_id="mesh", runtime="launchd-system", unit_ref=self.ROOTS,
                   declaration="workflow/workloads/mesh.yaml",
                   files=["/Library/LaunchDaemons/com.example.mesh.plist"])
        return json.dumps(raw)

    def test_every_other_entry_on_the_host_is_still_reported(self):
        runner = self.RefusesLikeTheRealExecutor()
        runner.add("print-disabled", completed_from("launchctl-print-disabled.txt"))
        runner.add("launchctl list", FakeCompleted(
            stdout="uid=4242\n" + read_output("launchctl-list.txt")))
        runner.add("kern.boottime", FakeCompleted(stdout="1787577316\n"))
        runner.add("cat", FakeCompleted(stdout=stamp_json() + "\n" + self.system_stamp()))
        cfg = config.load_config(make_repo(self.tmpdir()))
        obs = reconcile.observe_host(self.host(), cfg, timeout_sec=10, runner=runner)
        self.assertTrue(obs.reachable)
        self.assertIn(self.MINE, obs.stamps,
                      "a root-owned neighbour erased the ordinary run from the report")
        self.assertIs(dict(obs.disabled).get(self.MINE), False)
        self.assertIs(dict(obs.disabled).get(self.ROOTS), False,
                      "the system domain's off-list was not read, so the one "
                      "root-owned run is judged on less than the machine said")

    def test_reading_the_system_off_list_asks_for_no_elevation(self):
        system = mod("engine.backends").BACKENDS["launchd-system"]
        steps = system.disabled_list_steps(reconcile._Claim(unit_ref=self.ROOTS), self.host())
        self.assertTrue(steps, "no off-list read at all is not a fix")
        self.assertEqual([s.argv for s in steps if s.requires_elevation], [],
                         "a read inherited the flag that belongs to the write plan")
        self.assertTrue(system.requires_elevation,
                        "the counterweight: CHANGING the system domain still "
                        "needs a person, and that must not have moved")

    def test_a_read_that_does_need_elevation_is_one_gap_not_a_dead_host(self):
        backends = mod("engine.backends")
        stamps = {"calendar-export": self.stamp("calendar-export", unit_ref=self.MINE),
                  "guarded": self.stamp("guarded", unit_ref="guarded/unit",
                                        runtime="elevated-read")}
        runner = self.RefusesLikeTheRealExecutor()
        runner.add("print-disabled", completed_from("launchctl-print-disabled.txt"))
        notes = []
        with mock.patch.dict(backends.BACKENDS, {"elevated-read": self.ReadsOnlyWithElevation()}):
            out = reconcile.read_disabled(self.host(), stamps, timeout_sec=10,
                                          runner=runner, notes=notes)
        self.assertIs(out.get(self.MINE), False, "the answerable entry lost its answer")
        self.assertNotIn("guarded/unit", out,
                         "not asked is not absent: an unread list is no answer")
        said = " ".join(notes)
        self.assertIn("guarded/unit", said)
        self.assertIn("elevation", said,
                      "`nothing can be judged` and `nothing is wrong` must never "
                      "print the same")
        self.assertNotIn("read-root-only-off-list", runner.joined_calls,
                         "an elevated step reached the runner")


class WhereARunSaysWhatItSaid(MachineGuard):
    """The first question after a cross on the strip, and the page had no answer.

    The guard captures stdout and stderr of every run into `<state_key>.out`
    beside the trace it already reads back, so the path is DERIVABLE and was
    never derived. A reader who saw `failed` had to know the convention, or ask.

    The directory travels in the report rather than being rebuilt by the
    renderer: it is configuration, the run that read the machine already
    resolved it, and a second resolution of the same setting is how a page
    comes to print a path nobody reads from.
    """

    def test_the_report_carries_the_directory_it_read_from(self):
        root = make_repo(self.tmpdir(), declarations=("calendar-export",))
        cfg = config.load_config(root)
        runner = RecordingRunner()
        runner.add("list", completed_from("launchctl-list.txt"))
        rep = reconcile.run(root, cfg, probe=False, timeout_sec=10, runner=runner)
        self.assertEqual(getattr(rep, "state_dir", ""), cfg.stamp_dir,
                         "the renderer would have to guess the directory, and "
                         "a guessed path on a page reads exactly like a read one")


class TheProgramMayNotBeTheOneThatIsKept(MachineGuard):
    """`in_sync` is about the unit and the artifact, and the program is neither.

    A wrapper that sits outside the repository and has come apart from its twin
    runs happily forever: a change in the repository never reaches it, and no
    error appears anywhere. Measured on one machine on 2026-08-25, five such
    pairs, and two watchdogs that existed only on that box, a hundred and
    thirty lines ahead of the repository's copy.

    In no two of those five was the same side the right one, so nothing here
    decides that. It records that two exist and whether they have come apart.
    """

    def build(self, root, command):
        w = model.load_declaration(root / "workflow" / "workloads" / "calendar-export.yaml")
        return dataclasses.replace(
            w, execution=dataclasses.replace(w.execution, command=tuple(command)))

    def repo(self, files=()):
        root = make_repo(self.tmpdir(), declarations=("calendar-export",))
        for rel, body in files:
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body, encoding="utf-8")
        return root

    def look(self, root, command, digests=None):
        return source.findings([self.build(root, command)], root, digests or {})

    def test_a_program_inside_the_repository_is_never_a_finding(self):
        """Drift is structurally impossible there, so there is nothing to say."""
        root = self.repo([("infra/remotes/host-a/scripts/run.sh", "echo one\n")])
        self.assertEqual(
            self.look(root, ["/bin/bash", f"{root}/infra/remotes/host-a/scripts/run.sh"]),
            [])

    def test_a_copy_that_has_come_apart_from_its_twin_is_reported(self):
        root = self.repo([("infra/remotes/host-a/scripts/run.sh", "echo one\n")])
        found = self.look(root, ["/bin/bash", "/opt/elsewhere/run.sh"],
                          {"/opt/elsewhere/run.sh": "0" * 64})
        self.assertEqual([f.state for f in found],
                         [model.WorkloadState.source_drift])
        self.assertEqual(found[0].severity, model.Severity.medium)
        self.assertIn("does not reach this run", found[0].detail)

    def test_a_stale_copy_in_a_hidden_folder_is_not_the_twin(self):
        """2026-09-26: a leftover agent worktree under .claude/worktrees/ held an
        older copy of the same script. It sorts before infra/, became the twin,
        and a copy that matched the real source byte for byte was reported as
        drifted. Hidden folders hold working copies, never the kept original."""
        import hashlib
        body = "echo kept\n"
        root = self.repo([(".claude/worktrees/wf-1/infra/remotes/host-a/scripts/run.sh", "echo stale\n"),
                          ("infra/remotes/host-a/scripts/run.sh", body)])
        same = hashlib.sha256(body.encode()).hexdigest()
        self.assertEqual(
            self.look(root, ["/bin/bash", "/opt/elsewhere/run.sh"], {"/opt/elsewhere/run.sh": same}),
            [], "the copy on the machine equals the kept source; nothing drifted")

    def test_a_program_found_only_in_a_hidden_folder_has_no_twin(self):
        root = self.repo([(".claude/worktrees/wf-1/scripts/only.sh", "echo x\n")])
        found = self.look(root, ["/bin/bash", "/opt/elsewhere/only.sh"])
        self.assertEqual([f.state for f in found], [model.WorkloadState.source_drift])
        self.assertIn("one disk only", found[0].detail)

    def test_and_it_decides_nothing_about_which_side_is_right(self):
        root = self.repo([("infra/remotes/host-a/scripts/run.sh", "echo one\n")])
        found = self.look(root, ["/bin/bash", "/opt/elsewhere/run.sh"],
                          {"/opt/elsewhere/run.sh": "0" * 64})
        self.assertIn("does not decide", found[0].hint,
                      "in no two measured pairs was the same side the right one")

    def test_a_copy_that_still_agrees_says_nothing(self):
        body = "echo one\n"
        root = self.repo([("infra/remotes/host-a/scripts/run.sh", body)])
        same = source.digest_of(root / "infra/remotes/host-a/scripts/run.sh")
        self.assertEqual(
            self.look(root, ["/bin/bash", "/opt/elsewhere/run.sh"],
                      {"/opt/elsewhere/run.sh": same}),
            [], "a sentence per healthy run is how a section stops being read")

    def test_a_program_with_no_twin_at_all_is_the_dangerous_one(self):
        root = self.repo()
        found = self.look(root, ["/bin/bash", "/opt/elsewhere/only-here.sh"],
                          {"/opt/elsewhere/only-here.sh": "0" * 64})
        self.assertEqual([f.state for f in found],
                         [model.WorkloadState.source_drift])
        self.assertIn("one disk only", found[0].detail,
                      "this is the case a disk failure takes with it, and it "
                      "must not read like the case where two copies disagree")

    def test_a_digest_nobody_read_is_not_a_verdict(self):
        """Not asked is not absent, the same rule the off-list carries."""
        root = self.repo([("infra/remotes/host-a/scripts/run.sh", "echo one\n")])
        self.assertEqual(self.look(root, ["/bin/bash", "/opt/elsewhere/run.sh"]), [])

    def test_a_shared_interpreter_is_not_the_program(self):
        """Otherwise nearly every run on the machine is a copy of /bin/bash."""
        root = self.repo()
        self.assertEqual(source.program_of(self.build(root, ["/bin/bash"])), "")
        self.assertEqual(
            source.program_of(self.build(root, ["/usr/bin/env", "python3", "x.py"])), "")

    def test_a_retired_declaration_is_not_asked_about(self):
        root = self.repo()
        w = dataclasses.replace(
            self.build(root, ["/bin/bash", "/opt/elsewhere/only-here.sh"]),
            retired=model.Retired(at="2026-08-01", reason="superseded"))
        self.assertEqual(source.findings([w], root, {}), [])

    def test_one_segment_of_a_path_is_not_an_identity(self):
        """A bare basename matching somewhere is a coincidence.

        Without the floor, any program whose name happens to exist anywhere in
        the repository would count as the repository's own file, and the check
        would go quiet exactly where two copies are most likely.
        """
        root = self.repo([("run.sh", "echo one\n")])
        self.assertEqual(source.in_repository("/opt/elsewhere/run.sh", root), "")


class TheProgramMapReachesTheReport(MachineGuard):
    """The healthy answer has to travel too, or the page can only shout.

    A finding fires for the exception; the map carries all of them, and a
    column of "in this repository" is what makes the one row that says
    something else legible. It travels in the report for the same reason the
    state directory does: the run that read the machine already resolved both
    sides, and a renderer has neither.
    """

    def test_a_run_carries_where_every_program_sits(self):
        root = make_repo(self.tmpdir(), declarations=("calendar-export",))
        cfg = config.load_config(root)
        runner = RecordingRunner()
        runner.add("list", completed_from("launchctl-list.txt"))
        rep = reconcile.run(root, cfg, probe=False, timeout_sec=10, runner=runner)
        self.assertIn("calendar-export", getattr(rep, "programs", {}),
                      "the comparison was made and its answer went nowhere")


class TheDigestsAreAskedOfTheMachine(MachineGuard):
    """One step for every program, because the alternative is a round trip each.

    The paths are few (one per declaration), the machine is often reached over
    ssh, and a call per run would put the cost of this check on every render of
    the page.
    """

    def ask(self, stdout, raises=None, commands=(("/bin/bash", "/opt/elsewhere/run.sh"),)):
        root = make_repo(self.tmpdir(), declarations=("calendar-export",))
        base = model.load_declaration(
            root / "workflow" / "workloads" / "calendar-export.yaml")
        loads = [dataclasses.replace(
            base, execution=dataclasses.replace(base.execution, command=tuple(c)))
            for c in commands]
        runner = RecordingRunner()
        runner.add("shasum", FakeCompleted(stdout=stdout), raises=raises)
        out = reconcile.read_program_digests(FakeHost.from_fixture("host-a"), loads,
                                             timeout_sec=10, runner=runner)
        return out, runner

    def test_the_digest_and_the_path_are_read_back(self):
        out, _ = self.ask("%s  /opt/elsewhere/run.sh\n" % ("a" * 64))
        self.assertEqual(out, {"/opt/elsewhere/run.sh": "a" * 64})

    def test_every_program_is_asked_for_in_one_step(self):
        _, runner = self.ask("", commands=(("/bin/bash", "/opt/elsewhere/one.sh"),
                                           ("/bin/bash", "/opt/elsewhere/two.sh")))
        asked = [c for c in runner.calls if "shasum" in c["joined"]]
        self.assertEqual(len(asked), 1, f"asked {len(asked)} times")
        self.assertIn("one.sh", asked[0]["joined"])
        self.assertIn("two.sh", asked[0]["joined"])

    def test_a_line_that_is_not_a_digest_is_not_read_as_one(self):
        """`shasum` writes its refusals to the same stream on some systems."""
        out, _ = self.ask("shasum: /opt/elsewhere/run.sh: No such file or directory\n")
        self.assertEqual(out, {})

    def test_nothing_to_ask_about_costs_no_step(self):
        _, runner = self.ask("", commands=(("/bin/bash",),))
        self.assertEqual([c for c in runner.calls if "shasum" in c["joined"]], [])

    def test_a_machine_that_will_not_answer_is_not_an_error(self):
        out, _ = self.ask("", raises=errors.StepFailed("no such host"))
        self.assertEqual(out, {})
