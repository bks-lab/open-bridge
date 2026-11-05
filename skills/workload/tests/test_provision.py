"""provision: the only module that changes a machine.

plan() is pure, so the decision table is driven row by row without a box in
sight. Everything that executes accepts an injected `runner`, which is what lets
the whole file record instead of act. That injection is part of the contract:
real services run on these machines.
"""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

from tests.conftest import (
    CORPUS,
    DERIVED,
    INVALID,
    FIXTURE_HOME,
    FIXTURE_TZ,
    FIXTURE_UID,
    FakeCompleted,
    FakeHost,
    MachineGuard,
    RecordingRunner,
    SKILL_DIR,
    SandboxRunner,
    completed_from,
    forbidden_literals,
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
provision = mod("engine.provision")
stamp_mod = mod("engine.stamp")
lock_mod = mod("engine.lock")
config = mod("engine.config")

OTHER_DIGEST = "sha256:" + "b" * 64


class ProvisionBase(MachineGuard):
    """Observation field names below are the contract, not a suggestion."""

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

    def repo_with(self, name):
        root = make_repo(self.tmpdir(), declarations=(name,))
        return root, root / "workflow" / "workloads" / f"{name}.yaml"

    def artifact(self, name="block-style-report", host="host-a"):
        return render_mod.render(self.load(name), self.host(host), self.ctx())

    def stamp_for(self, w, artifact, **overrides):
        fields = dict(
            stamp_version=1,
            workload_id=w.id,
            host="host-a",
            declaration=f"workflow/workloads/{w.id}.yaml",
            declaration_digest=model.declaration_digest(w),
            artifact_digest=artifact.digest,
            runtime=artifact.runtime,
            unit_ref=artifact.unit_ref,
            files=tuple(str(f.path) for f in artifact.files),
            provisioned_at="2026-08-22T10:00:00+02:00",
            adopted=False,
            retired=None,
        )
        fields.update(overrides)
        return stamp_mod.Stamp(**fields)

    def observation(self, artifact=None, **overrides):
        fields = dict(
            reachable=True,
            present=False,
            enabled=True,
            running=False,
            persistently_disabled=False,
            file_digests={},
            stamp=None,
            marker_id=None,
            marker_digest=None,
        )
        if artifact is not None:
            fields["file_digests"] = {str(f.path): None for f in artifact.files}
        fields.update(overrides)
        return provision.Observation(**fields)

    def provisioned(self, w, artifact, **overrides):
        """The state a successful provision leaves behind.

        `marker_digest` is the DECLARATION digest, because that is what every
        backend actually writes into the unit. Setting it to the artifact digest
        here would be a fixture inventing an equality the production code can
        never produce, and it hid a bug that made every provisioned run report
        drift forever.
        """
        per_file = base.digest_of
        fields = dict(
            present=True,
            running=True,
            file_digests={str(f.path): per_file([f]) for f in artifact.files},
            stamp=self.stamp_for(w, artifact),
            marker_id=w.id,
            marker_digest=model.declaration_digest(w),
        )
        fields.update(overrides)
        return self.observation(artifact, **fields)


class ThePlanDecisionTable(ProvisionBase):

    def test_nothing_there_creates(self):
        w, a = self.load("block-style-report"), self.artifact()
        plan = provision.plan(w, a, self.observation(a))
        self.assertEqual(plan.action, "create")

    def test_the_same_digest_is_a_no_op(self):
        # Running provision twice must change nothing. That is the condition for
        # being allowed to automate it at all.
        w, a = self.load("block-style-report"), self.artifact()
        plan = provision.plan(w, a, self.provisioned(w, a))
        self.assertEqual(plan.action, "noop")
        self.assertEqual(list(plan.steps), [])

    def test_a_different_digest_replaces(self):
        w, a = self.load("block-style-report"), self.artifact()
        obs = self.provisioned(w, a, stamp=self.stamp_for(w, a, artifact_digest=OTHER_DIGEST),
                               marker_digest=OTHER_DIGEST)
        plan = provision.plan(w, a, obs)
        self.assertEqual(plan.action, "replace")

    def test_files_without_a_stamp_and_without_a_marker_are_never_overwritten(self):
        w, a = self.load("block-style-report"), self.artifact()
        obs = self.observation(a, present=True, running=True,
                               file_digests={str(f.path): OTHER_DIGEST for f in a.files})
        plan = provision.plan(w, a, obs)
        self.assertEqual(plan.action, "refuse")
        self.assertEqual(plan.reason_code, "collision-unstamped")

    def test_a_marker_naming_another_workload_is_refused(self):
        w, a = self.load("block-style-report"), self.artifact()
        obs = self.observation(a, present=True, running=True, marker_id="some-other-workload",
                               marker_digest=OTHER_DIGEST)
        plan = provision.plan(w, a, obs)
        self.assertEqual(plan.action, "refuse")
        self.assertEqual(plan.reason_code, "collision-foreign-workload")

    def test_a_file_edited_since_the_stamp_is_refused_without_force(self):
        w, a = self.load("block-style-report"), self.artifact()
        edited = {str(f.path): OTHER_DIGEST for f in a.files}
        obs = self.provisioned(w, a, file_digests=edited)
        plan = provision.plan(w, a, obs)
        self.assertEqual(plan.action, "refuse")
        self.assertEqual(plan.reason_code, "foreign-edit")

    def test_force_turns_a_foreign_edit_into_a_replace(self):
        w, a = self.load("block-style-report"), self.artifact()
        edited = {str(f.path): OTHER_DIGEST for f in a.files}
        obs = self.provisioned(w, a, file_digests=edited)
        plan = provision.plan(w, a, obs, force=True)
        self.assertEqual(plan.action, "replace")

    def test_a_persistently_disabled_unit_is_never_auto_enabled(self):
        # One real declaration exists whose start would be a security incident.
        w, a = self.load("block-style-report"), self.artifact()
        obs = self.provisioned(w, a, persistently_disabled=True, running=False)
        plan = provision.plan(w, a, obs)
        self.assertEqual(plan.action, "refuse")
        self.assertEqual(plan.reason_code, "disabled-refused")
        self.assertNotIn("enable", " ".join(" ".join(s.argv) for s in plan.steps))

    def test_a_retired_declaration_is_refused(self):
        w = self.load("voice-channel")
        a = render_mod.render(w, self.host(), self.ctx())
        plan = provision.plan(w, a, self.observation(a))
        self.assertEqual(plan.action, "refuse")
        self.assertEqual(plan.reason_code, "retired-declaration")

    def test_a_declaration_the_bridge_does_not_own_is_refused(self):
        w = self.load("chat-channel")
        plan = provision.plan(w, None, self.observation())
        self.assertEqual(plan.action, "refuse")
        self.assertEqual(plan.reason_code, "not-owned")

    def test_a_backend_that_cannot_carry_a_demanded_guarantee_is_refused(self):
        w = self.load("contract-review-reminder")
        a = render_mod.render(w, self.host(), self.ctx(
            dispatcher_registry=f"{FIXTURE_HOME}/.bridge/dispatcher.yaml"))
        plan = provision.plan(w, a, self.observation(a))
        self.assertEqual(plan.action, "refuse")
        self.assertEqual(plan.reason_code, "degraded-backend")

    def test_accept_degraded_downgrades_the_refusal_to_a_warning(self):
        w = self.load("contract-review-reminder")
        a = render_mod.render(w, self.host(), self.ctx(
            dispatcher_registry=f"{FIXTURE_HOME}/.bridge/dispatcher.yaml"))
        plan = provision.plan(w, a, self.observation(a), accept_degraded=True)
        self.assertEqual(plan.action, "create")
        self.assertTrue(plan.warnings, "a degraded backend that is accepted must still say so")

    def test_elevation_yields_a_printed_manual_plan(self):
        w = self.load("elevated-daemon")
        a = render_mod.render(w, self.host(), self.ctx())
        plan = provision.plan(w, a, self.observation(a))
        self.assertEqual(plan.action, "manual")
        self.assertTrue(plan.steps, "a manual plan without steps tells the human nothing")

    def test_plan_needs_no_machine_at_all(self):
        # Purity is what makes the whole table above provable, and it used to be
        # "asserted" by a dead assignment nothing read
        # (`real = provision.run_step if hasattr(...) else None`) plus
        # `assertIsNotNone(plan.reason_code)` on a field that is a required str
        # and can never be None. plan() was taught to start a process AND write a
        # file, and this test stayed green through both.
        #
        # `assert_pure` shuts those doors at subprocess and at the calls that put
        # bytes on disk, below the engine, so an argv assembled at runtime is
        # caught as well as a spelled-out one.
        w, a = self.load("block-style-report"), self.artifact()
        observation = self.observation(a)
        plan = self.assert_pure(lambda: provision.plan(w, a, observation),
                                what="plan()")
        self.assertEqual(plan.action, "create")
        self.assertEqual(plan.reason_code, "nothing-provisioned")

    def test_an_unreachable_host_never_produces_a_create(self):
        w, a = self.load("block-style-report"), self.artifact()
        plan = provision.plan(w, a, self.observation(a, reachable=False))
        self.assertNotEqual(plan.action, "create",
                            "not knowing what is there is not the same as nothing being there")


class Observing(ProvisionBase):

    def test_observation_reads_the_marker_back_out_of_the_live_unit(self):
        w, a = self.load("block-style-report"), self.artifact()
        runner = RecordingRunner()
        runner.add("print", completed_from("launchctl-print-running.txt"))
        runner.add("shasum", FakeCompleted(stdout="deadbeef  x"))
        obs = provision.observe(w, self.host(), a, self.ctx(), timeout_sec=10, runner=runner)
        self.assertEqual(obs.marker_id, "calendar-export")
        self.assertTrue(obs.marker_digest.startswith("sha256:"))
        self.assert_no_mutation(runner)

    def test_observation_never_derives_state_from_the_declaration(self):
        w, a = self.load("block-style-report"), self.artifact()
        runner = RecordingRunner()
        runner.add("print", FakeCompleted(rc=113, stdout=read_output("launchctl-print-notfound.txt")))
        obs = provision.observe(w, self.host(), a, self.ctx(), timeout_sec=10, runner=runner)
        self.assertFalse(obs.present)
        self.assertFalse(obs.running)

    def test_a_stopped_unit_is_reported_as_present_and_not_running(self):
        w, a = self.load("block-style-report"), self.artifact()
        runner = RecordingRunner()
        runner.add("print", completed_from("launchctl-print-stopped.txt"))
        obs = provision.observe(w, self.host(), a, self.ctx(), timeout_sec=10, runner=runner)
        self.assertTrue(obs.present)
        self.assertFalse(obs.running)


class Applying(ProvisionBase):

    def test_a_dry_run_touches_nothing(self):
        w, a = self.load("block-style-report"), self.artifact()
        runner = RecordingRunner()
        plan = provision.plan(w, a, self.observation(a))
        root = make_repo(self.tmpdir(), declarations=())
        outcome = provision.apply(plan, w, self.host(), a, self.ctx(),
                                  dry_run=True, timeout_sec=10, runner=runner, root=root)
        self.assertEqual(runner.calls, [])
        self.assertFalse(outcome.verified)

    def test_the_order_is_steps_then_stamp_then_verify(self):
        # The needle is "launchctl print" and not "print": the generated guard
        # script writes its trace line with printf, and a bare "print" would
        # find that write step instead of the verify call. Narrower, not softer.
        w, a = self.load("block-style-report"), self.artifact()
        runner = RecordingRunner()
        runner.add("launchctl print", completed_from("launchctl-print-running.txt"))
        plan = provision.plan(w, a, self.observation(a))
        root = make_repo(self.tmpdir())
        provision.apply(plan, w, self.host(), a, self.ctx(),
                        dry_run=False, timeout_sec=10, runner=runner, root=root)
        bootstrap = runner.index_of("bootstrap")
        stamp = runner.index_of(".stamp.json")
        verify = runner.index_of("launchctl print")
        self.assertLess(bootstrap, stamp)
        self.assertLess(stamp, verify)

    def test_success_is_never_reported_without_a_passing_verify(self):
        w, a = self.load("block-style-report"), self.artifact()
        runner = RecordingRunner()
        runner.add("print", FakeCompleted(rc=113,
                                          stdout=read_output("launchctl-print-notfound.txt")))
        plan = provision.plan(w, a, self.observation(a))
        root = make_repo(self.tmpdir())
        outcome = provision.apply(plan, w, self.host(), a, self.ctx(),
                                  dry_run=False, timeout_sec=10, runner=runner, root=root)
        self.assertFalse(outcome.verified)

    def test_a_failed_verify_after_a_replace_restores_the_previous_files(self):
        w, a = self.load("block-style-report"), self.artifact()
        runner = RecordingRunner()
        runner.add("print", FakeCompleted(rc=113,
                                          stdout=read_output("launchctl-print-notfound.txt")))
        obs = self.provisioned(w, a, stamp=self.stamp_for(w, a, artifact_digest=OTHER_DIGEST),
                               marker_digest=OTHER_DIGEST)
        plan = provision.plan(w, a, obs)
        self.assertEqual(plan.action, "replace")
        root = make_repo(self.tmpdir())
        outcome = provision.apply(plan, w, self.host(), a, self.ctx(),
                                  dry_run=False, timeout_sec=10, runner=runner, root=root)
        self.assertFalse(outcome.verified)
        self.assertIn(".prev", runner.joined_calls,
                      "a failed replace has to put the previous files back")
        self.assertIn("restore", " ".join(str(f) for f in outcome.findings).lower())

    def test_a_failed_verify_after_a_replace_loads_the_previous_unit_again(self):
        """Putting the old file back is half a rollback: launchd still holds the
        new unit until something unloads it and loads the old bytes."""
        w, a = self.load("block-style-report"), self.artifact()
        runner = RecordingRunner()
        runner.add("print", FakeCompleted(rc=113,
                                          stdout=read_output("launchctl-print-notfound.txt")))
        obs = self.provisioned(w, a, stamp=self.stamp_for(w, a, artifact_digest=OTHER_DIGEST),
                               marker_digest=OTHER_DIGEST)
        plan = provision.plan(w, a, obs)
        root = make_repo(self.tmpdir())
        provision.apply(plan, w, self.host(), a, self.ctx(),
                        dry_run=False, timeout_sec=10, runner=runner, root=root)
        straps = [c["joined"] for c in runner.calls if "launchctl bootstrap" in c["joined"]]
        self.assertEqual(len(straps), 2,
                         "after the restore the previous unit has to be loaded again")
        restore = next(i for i, c in enumerate(runner.calls)
                       if ".prev" in c["joined"] and "mv " in c["joined"])
        self.assertTrue(any("launchctl bootstrap" in c["joined"]
                            for c in runner.calls[restore:]))

    def test_a_failed_bootstrap_during_a_replace_brings_the_previous_unit_back(self):
        """The real failure: bootout succeeded, the bootstrap of the new bytes
        failed, and the run stopped there. The unit stayed unloaded, a
        production service was down until a human put the old file back."""
        w, a = self.load("block-style-report"), self.artifact()

        class FirstBootstrapFails(RecordingRunner):
            straps = 0

            def __call__(inner, argv=None, *args, step=None, **kwargs):
                text = " ".join(str(x) for x in getattr(argv, "argv", argv or ()))
                if "bootstrap" in text:
                    inner.straps += 1
                    if inner.straps == 1:
                        inner.calls.append({"argv": (), "joined": text, "kwargs": kwargs,
                                            "step": argv})
                        raise errors.StepFailed(argv=("launchctl", "bootstrap"), rc=5,
                                                stderr="Bootstrap failed: 5: Input/output error")
                return RecordingRunner.__call__(inner, argv, *args, step=step, **kwargs)

        runner = FirstBootstrapFails()
        obs = self.provisioned(w, a, stamp=self.stamp_for(w, a, artifact_digest=OTHER_DIGEST),
                               marker_digest=OTHER_DIGEST)
        plan = provision.plan(w, a, obs)
        self.assertEqual(plan.action, "replace")
        root = make_repo(self.tmpdir())
        with self.assertRaises(errors.StepFailed) as caught:
            provision.apply(plan, w, self.host(), a, self.ctx(),
                            dry_run=False, timeout_sec=10, runner=runner, root=root)
        self.assertEqual(runner.straps, 2, "the previous unit must be bootstrapped again")
        calls = runner.joined_calls
        self.assertIn(".prev", calls, "the previous files must be put back")
        self.assertLess(calls.index("mv "), calls.rindex("bootstrap"))
        self.assertIn("previous", str(caught.exception).lower())

    def test_a_verify_timeout_leaves_the_outcome_unverified(self):
        w, a = self.load("block-style-report"), self.artifact()
        runner = RecordingRunner()
        # "launchctl print", so the expiry lands on the verify call and not on
        # the guard script write, whose printf also contains "print".
        runner.add("launchctl print", raises=errors.StepTimeout(argv=("launchctl", "print"),
                                                                timeout_sec=5,
                                                                partial_stdout="",
                                                                partial_stderr=""))
        plan = provision.plan(w, a, self.observation(a))
        root = make_repo(self.tmpdir())
        outcome = provision.apply(plan, w, self.host(), a, self.ctx(),
                                  dry_run=False, timeout_sec=10, runner=runner, root=root)
        self.assertFalse(outcome.verified)

    def test_verify_asks_the_declared_probe(self):
        w, a = self.load("block-style-report"), self.artifact()
        runner = RecordingRunner()
        runner.add("print", completed_from("launchctl-print-running.txt"))
        provision.verify(w, self.host(), a, self.ctx(), timeout_sec=10, runner=runner)
        self.assertTrue(runner.calls, "verify did not ask anything")
        self.assert_no_mutation(runner)


class TheLock(ProvisionBase):

    def test_two_sessions_never_provision_the_same_id(self):
        root = self.tmpdir()
        with lock_mod.workload_lock(root, "block-style-report"):
            with self.assertRaises(errors.LockHeld) as ctx:
                with lock_mod.workload_lock(root, "block-style-report"):
                    pass
            self.assert_error(ctx, "lock-held", str(os.getpid()))

    def test_different_ids_do_not_block_each_other(self):
        root = self.tmpdir()
        with lock_mod.workload_lock(root, "one"):
            with lock_mod.workload_lock(root, "two"):
                pass

    def test_a_stale_lock_is_reclaimed(self):
        root = self.tmpdir()
        lock_dir = root / ".bridge" / "workload-locks"
        lock_dir.mkdir(parents=True)
        (lock_dir / "block-style-report.lock").write_text("999999\n", encoding="utf-8")
        with lock_mod.workload_lock(root, "block-style-report"):
            pass

    def test_the_lock_is_released_even_when_the_body_raises(self):
        root = self.tmpdir()
        with self.assertRaises(ValueError):
            with lock_mod.workload_lock(root, "block-style-report"):
                raise ValueError("boom")
        with lock_mod.workload_lock(root, "block-style-report"):
            pass


class TheStamp(ProvisionBase):

    def test_it_round_trips(self):
        w, a = self.load("block-style-report"), self.artifact()
        original = self.stamp_for(w, a)
        text = stamp_mod.to_json(original)
        self.assertTrue(text.endswith("\n"), "a file without a trailing newline is a nuisance")
        self.assertEqual(stamp_mod.from_json(text), original)

    def test_the_json_keys_are_sorted(self):
        w, a = self.load("block-style-report"), self.artifact()
        keys = list(json.loads(stamp_mod.to_json(self.stamp_for(w, a))).keys())
        self.assertEqual(keys, sorted(keys))

    def test_it_carries_no_username_and_no_secret(self):
        from tests.conftest import forbidden_literals

        w, a = self.load("block-style-report"), self.artifact()
        text = stamp_mod.to_json(self.stamp_for(w, a))
        for literal in forbidden_literals():
            self.assertNotIn(literal, text)
        for word in ("password", "token", "secret"):
            self.assertNotIn(word, text.lower())

    def test_writing_is_atomic(self):
        w, a = self.load("block-style-report"), self.artifact()
        runner = RecordingRunner()
        stamp_mod.write_stamp(self.stamp_for(w, a), self.host(), self.ctx(),
                              timeout_sec=10, runner=runner)
        joined = runner.joined_calls
        self.assertIn("mv", joined, "a stamp written in place can be truncated by a crash")

    def test_the_stamp_dir_expands_on_the_host(self):
        w, a = self.load("block-style-report"), self.artifact()
        runner = RecordingRunner()
        stamp_mod.write_stamp(self.stamp_for(w, a), self.host(), self.ctx(),
                              timeout_sec=10, runner=runner)
        joined = runner.joined_calls
        for literal in forbidden_literals():
            self.assertNotIn(literal, joined,
                             "the stamp path must expand on the host, not here")
        self.assertIn(".bridge/workloads", joined)

    def test_reading_is_read_only(self):
        runner = RecordingRunner()
        runner.add("cat", FakeCompleted(stdout=stamp_json()))
        root = self.tmpdir()
        (root / "bridge-config.yaml").write_text("workloads: {}\n", encoding="utf-8")
        cfg = config.load_config(root)
        stamps = stamp_mod.read_stamps(self.host(), cfg, timeout_sec=10, runner=runner)
        # Keyed by the UNIT, not by the declaration: a run with several
        # appointments files one record per unit, and keying by the declaration
        # made the second replace the first, so a running unit read as never
        # provisioned. The declaration is still on every record.
        self.assertEqual(
            sorted(str(st.workload_id) for st in stamps.values()),
            ["calendar-export"],
            "the record no longer names the declaration it belongs to")
        self.assertTrue(all(key == st.unit_ref for key, st in stamps.items()),
                        f"a record is filed under something other than its unit: {stamps}")
        self.assert_no_mutation(runner)


class Adopting(ProvisionBase):
    """The zero downtime entry ramp for something that exists by hand."""

    def test_adopt_writes_only_the_stamp(self):
        w, a = self.load("block-style-report"), self.artifact()
        runner = RecordingRunner()
        runner.add("print", completed_from("launchctl-print-no-marker.txt"))
        runner.add("shasum", FakeCompleted(stdout=f"{OTHER_DIGEST[7:]}  x"))
        root = make_repo(self.tmpdir())
        provision.adopt(w, self.host(), a, self.ctx(), timeout_sec=10,
                        dry_run=False, runner=runner, root=root)
        joined = runner.joined_calls
        self.assertIn(".stamp.json", joined)
        # Whole argv words, not substrings: `launchctl print-disabled` is the
        # READ that tells us whether somebody switched this off deliberately,
        # and it happens to contain the letters of `disable`.
        words = {token for call in runner.calls for token in call["argv"]}
        for verb in ("bootstrap", "bootout", "kickstart", "disable", "enable"):
            self.assertNotIn(verb, words,
                             f"adopt restarted something ({verb}); it must not")

    def test_adopt_records_what_is_actually_there(self):
        w, a = self.load("block-style-report"), self.artifact()
        runner = RecordingRunner()
        runner.add("print", completed_from("launchctl-print-no-marker.txt"))
        runner.add("shasum", FakeCompleted(stdout=f"{OTHER_DIGEST[7:]}  x"))
        root = make_repo(self.tmpdir())
        outcome = provision.adopt(w, self.host(), a, self.ctx(), timeout_sec=10,
                                  dry_run=False, runner=runner, root=root)
        self.assertTrue(outcome.verified)
        self.assertIn("adopted", str(outcome.action) + " " + runner.joined_calls)

    def test_an_adopted_hand_made_unit_is_replaced_without_force(self):
        """A hand made unit has no guard script, the render has one. Adopt used
        to fall back to the RENDERED digest when the file counts differed, so the
        stamp claimed the bridge's own version was on the machine. The next
        provision then saw "stamp equals render, files differ" and refused with
        foreign-edit, although nobody had touched anything since the adopt. Found
        three times in one morning on real machines; each needed --force."""
        from unittest import mock
        w, a = self.load("block-style-report"), self.artifact()
        self.assertGreater(len(a.files), 1, "the case needs a render with a guard script")
        unit = next(f for f in a.files if str(f.path).endswith(".plist"))
        runner = RecordingRunner()
        runner.add("launchctl print", completed_from("launchctl-print-no-marker.txt"))
        runner.add(f"cat {unit.path}", FakeCompleted(stdout="<plist>made by hand</plist>\n"))
        for f in a.files:
            if f is not unit:
                runner.add(f"cat {f.path}", FakeCompleted(rc=1, stdout=""))
        captured = []
        root = make_repo(self.tmpdir())
        with mock.patch.object(provision.stamp_mod, "write_stamp",
                               side_effect=lambda st, *x, **k: captured.append(st)):
            provision.adopt(w, self.host(), a, self.ctx(), timeout_sec=10,
                            dry_run=False, runner=runner, root=root)
        self.assertEqual(len(captured), 1)
        stamp = captured[0]
        self.assertNotEqual(stamp.artifact_digest, a.digest,
                            "the stamp must record what is there, not what would be rendered")

        live = provision.RenderedFile(path=unit.path, mode=unit.mode,
                                      content="<plist>made by hand</plist>\n")
        digests = {str(f.path): None for f in a.files}
        digests[str(unit.path)] = base.digest_of([live])
        obs = self.observation(a, present=True, running=True, stamp=stamp,
                               file_digests=digests)
        self.assertEqual(provision.plan(w, a, obs).action, "replace")

    def test_adopt_refuses_when_nothing_is_there(self):
        w, a = self.load("block-style-report"), self.artifact()
        runner = RecordingRunner()
        runner.add("print", FakeCompleted(rc=113,
                                          stdout=read_output("launchctl-print-notfound.txt")))
        root = make_repo(self.tmpdir())
        with self.assertRaises(errors.NothingToAdopt) as ctx:
            provision.adopt(w, self.host(), a, self.ctx(), timeout_sec=10,
                            dry_run=False, runner=runner, root=root)
        self.assert_error(ctx, "nothing-to-adopt", "block-style-report")

    def test_the_refusal_names_the_way_out(self):
        """"Nothing found" reads as "does not exist", and it usually is not.

        `adopt` uebernimmt von Hand Angelegtes, und von Hand angelegte Einheiten
        almost never carry this instance's prefix. A reader who does not know
        the way out puts a SECOND unit next to the one already there, so the way
        out belongs in the message and not only in the schema.
        """
        w, a = self.load("block-style-report"), self.artifact()
        runner = RecordingRunner()
        runner.add("print", FakeCompleted(rc=113,
                                          stdout=read_output("launchctl-print-notfound.txt")))
        root = make_repo(self.tmpdir())
        with self.assertRaises(errors.NothingToAdopt) as ctx:
            provision.adopt(w, self.host(), a, self.ctx(), timeout_sec=10,
                            dry_run=False, runner=runner, root=root)
        self.assertIn("label_prefix", str(ctx.exception))


class Retiring(ProvisionBase):
    """Disable plus a reason, in this order, and never a rename."""

    def runner_ok(self):
        runner = RecordingRunner()
        runner.add("print", FakeCompleted(rc=113,
                                          stdout=read_output("launchctl-print-notfound.txt")))
        return runner

    def test_the_order_is_bootout_disable_verify_declaration_stamp(self):
        w, a = self.load("calendar-export"), self.artifact("calendar-export")
        root, path = self.repo_with("calendar-export")
        runner = self.runner_ok()
        provision.retire(w, self.host(), a, self.ctx(), reason="superseded by the timer",
                         dry_run=False, confirmed=True, timeout_sec=10,
                         runner=runner, root=root)
        self.assertLess(runner.index_of("bootout"), runner.index_of("disable"))
        self.assertLess(runner.index_of("disable"), runner.index_of("print"))
        self.assertIn("retired:", path.read_text(encoding="utf-8"))

    def test_the_reason_reaches_the_machine_and_the_declaration(self):
        w, a = self.load("calendar-export"), self.artifact("calendar-export")
        root, path = self.repo_with("calendar-export")
        runner = self.runner_ok()
        reason = "replaced by the timer unit on the linux box"
        provision.retire(w, self.host(), a, self.ctx(), reason=reason,
                         dry_run=False, confirmed=True, timeout_sec=10,
                         runner=runner, root=root)
        self.assertIn(reason, path.read_text(encoding="utf-8"))
        blob = runner.joined_calls + " ".join(
            str(c["step"].purpose) for c in runner.calls if c.get("step") is not None)
        self.assertIn(reason, blob)

    def test_nothing_is_ever_renamed(self):
        w, a = self.load("calendar-export"), self.artifact("calendar-export")
        root, _ = self.repo_with("calendar-export")
        runner = self.runner_ok()
        provision.retire(w, self.host(), a, self.ctx(), reason="superseded by the timer",
                         dry_run=False, confirmed=True, timeout_sec=10,
                         runner=runner, root=root)
        for renamer in (".bak", ".broken", ".disabled", ".old"):
            self.assertNotIn(renamer, runner.joined_calls)

    def test_a_failing_step_stops_before_the_declaration_is_written(self):
        # Otherwise the repo claims retired while the box still runs it.
        w, a = self.load("calendar-export"), self.artifact("calendar-export")
        root, path = self.repo_with("calendar-export")
        before = path.read_text(encoding="utf-8")
        runner = RecordingRunner()
        runner.add("disable", raises=errors.StepFailed(argv=("launchctl", "disable"), rc=1,
                                                       stderr="Operation not permitted"))
        with self.assertRaises(errors.StepFailed):
            provision.retire(w, self.host(), a, self.ctx(), reason="superseded by the timer",
                             dry_run=False, confirmed=True, timeout_sec=10,
                             runner=runner, root=root)
        self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_a_short_reason_is_refused(self):
        w, a = self.load("calendar-export"), self.artifact("calendar-export")
        root, _ = self.repo_with("calendar-export")
        runner = self.runner_ok()
        with self.assertRaises(errors.ReasonTooShort) as ctx:
            provision.retire(w, self.host(), a, self.ctx(), reason="weg",
                             dry_run=False, confirmed=True, timeout_sec=10,
                             runner=runner, root=root)
        self.assert_error(ctx, "reason-too-short", "8")
        self.assertEqual(runner.calls, [], "a refused retire must not touch the machine first")

    def test_keep_artifact_leaves_the_files_in_place(self):
        w, a = self.load("calendar-export"), self.artifact("calendar-export")
        root, _ = self.repo_with("calendar-export")
        runner = self.runner_ok()
        provision.retire(w, self.host(), a, self.ctx(), reason="superseded by the timer",
                         keep_artifact=True, dry_run=False, confirmed=True, timeout_sec=10,
                         runner=runner, root=root)
        self.assertNotIn("rm ", runner.joined_calls)

    def test_superseded_by_is_carried_into_the_declaration(self):
        w, a = self.load("calendar-export"), self.artifact("calendar-export")
        root, path = self.repo_with("calendar-export")
        runner = self.runner_ok()
        provision.retire(w, self.host(), a, self.ctx(), reason="superseded by the timer",
                         superseded_by="linux-timer-report", dry_run=False, confirmed=True,
                         timeout_sec=10, runner=runner, root=root)
        self.assertIn("linux-timer-report", path.read_text(encoding="utf-8"))


class TheOwnershipMarkerIsReadAsWhatItIs(ProvisionBase):
    """Everything here draws the marker out of the REAL rendered bytes.

    The marker carries the DECLARATION digest, because it sits inside the file
    the artifact digest covers. A fixture that sets it to the artifact digest
    invents an equality production never produces, and it hid the fact that the
    `marker-without-stamp` branch could not be reached at all: a unit provably
    ours that had lost its ownership record was booted out and rewritten instead
    of adopted.
    """

    def test_a_unit_that_is_ours_by_its_marker_is_never_rewritten(self):
        w, a = self.load("block-style-report"), self.artifact()
        obs = self.observation(
            a, present=True, running=True, marker_id=w.id,
            marker_digest=marker_digest_in(a),
            file_digests={str(f.path): base.digest_of([f]) for f in a.files})
        plan = provision.plan(w, a, obs)
        self.assertEqual(plan.action, "refuse")
        self.assertEqual(plan.reason_code, "marker-without-stamp")
        self.assertNotIn("bootout", " ".join(" ".join(s.argv) for s in plan.steps))

    def test_observation_reads_the_same_digest_the_render_wrote(self):
        w, a = self.load("block-style-report"), self.artifact()
        plist = [f for f in a.files if str(f.path).endswith(".plist")][0]
        printed = (f"{a.unit_ref} = {{\n\tstate = running\n\tenvironment = {{\n"
                   f"\t\t{model.MARKER_ENV_ID} => {w.id}\n"
                   f"\t\t{model.MARKER_ENV_DIGEST} => {marker_digest_in(a)}\n\t}}\n}}\n")
        self.assertIn(marker_digest_in(a), plist.content)
        runner = RecordingRunner()
        runner.add("launchctl print-disabled", FakeCompleted(stdout=""))
        runner.add("launchctl print", FakeCompleted(stdout=printed))
        obs = provision.observe(w, self.host(), a, self.ctx(), timeout_sec=10, runner=runner)
        self.assertEqual(obs.marker_id, w.id)
        self.assertEqual(obs.marker_digest, model.declaration_digest(w))


class ThePersistentOffList(ProvisionBase):
    """A unit somebody switched off deliberately is never switched back on.

    The refusal existed but could never fire: the only call in the observe path
    was `launchctl print`, whose output does not carry the off-list at all, so
    the field it was read from was always False. It is a read of its own now.
    """

    OFF_LIST = ('disabled services = {\n'
                '\t"bridge.block-style-report" => disabled\n'
                '\t"com.example.mesh" => enabled\n'
                '}\n')

    def runner_with_off_list(self, text):
        runner = RecordingRunner()
        runner.add("print-disabled", FakeCompleted(stdout=text))
        runner.add("launchctl print", completed_from("launchctl-print-running.txt"))
        return runner

    def test_the_off_list_is_actually_read_from_the_machine(self):
        w, a = self.load("block-style-report"), self.artifact()
        runner = self.runner_with_off_list(self.OFF_LIST)
        obs = provision.observe(w, self.host(), a, self.ctx(), timeout_sec=10, runner=runner)
        self.assertTrue(runner.called_with("print-disabled"),
                        "nothing asked for the persistent off-list, so the refusal "
                        "that protects a deliberately stopped unit cannot fire")
        self.assertIs(obs.persistently_disabled, True)
        self.assert_no_mutation(runner)

    def test_from_the_machine_answer_all_the_way_to_the_refusal(self):
        w, a = self.load("block-style-report"), self.artifact()
        runner = self.runner_with_off_list(self.OFF_LIST)
        obs = provision.observe(w, self.host(), a, self.ctx(), timeout_sec=10, runner=runner)
        plan = provision.plan(w, a, obs)
        self.assertEqual(plan.action, "refuse")
        self.assertEqual(plan.reason_code, "disabled-refused")
        self.assertEqual(plan.steps, ())

    def test_a_unit_that_is_not_on_the_list_is_not_refused(self):
        w, a = self.load("block-style-report"), self.artifact()
        runner = self.runner_with_off_list('disabled services = {\n'
                                           '\t"com.example.mesh" => enabled\n}\n')
        obs = provision.observe(w, self.host(), a, self.ctx(), timeout_sec=10, runner=runner)
        self.assertIs(obs.persistently_disabled, False)
        self.assertNotEqual(provision.plan(w, a, obs).reason_code, "disabled-refused")

    def test_an_unread_off_list_is_unknown_and_not_a_permission(self):
        w, a = self.load("block-style-report"), self.artifact()
        runner = self.runner_with_off_list("")
        obs = provision.observe(w, self.host(), a, self.ctx(), timeout_sec=10, runner=runner)
        self.assertIsNone(obs.persistently_disabled)

    def test_the_enable_flag_is_wired_all_the_way_through_the_command_line(self):
        # It was parsed and then dropped, so the refusal could not be lifted even
        # deliberately. This test used to look for that with an AST scan for ANY
        # call anywhere in cli.py passing a keyword named `enable` -- which
        # `enable=False` satisfies exactly as well as `enable=args.enable`. The
        # original defect, put back, left it green.
        #
        # So it is measured instead, from the argv the user types to the plan
        # that comes out: without the flag the run is refused, with it that
        # refusal is gone, and both answers come through `cli.main`.
        import contextlib
        import io

        import engine.exec as exec_module
        from unittest import mock

        cli = mod("engine.cli")
        root = make_repo(self.tmpdir(), declarations=("block-style-report",))

        def drive(*extra):
            runner = self.runner_with_off_list(self.OFF_LIST)
            runner.add("id -u", FakeCompleted(stdout=read_output("probe-context.txt")))
            out, err = io.StringIO(), io.StringIO()
            with mock.patch.object(exec_module, "step_runner", runner):
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    rc = cli.main(["--root", str(root), "provision", "block-style-report",
                                   "--yes", "--dry-run", *extra])
            return rc, out.getvalue() + err.getvalue()

        _, refused = drive()
        self.assertIn("disabled-refused", refused,
                      "a unit on the persistent off-list was not refused at the "
                      "command line at all, so this test cannot see the flag work")

        _, lifted = drive("--enable")
        self.assertNotIn("disabled-refused", lifted,
                         "--enable was parsed and then dropped: the refusal a human "
                         "deliberately lifted still fired")

    def test_the_module_parses_no_service_manager_output_itself(self):
        # Every format belongs to its backend. A reader here is a fifth backend
        # that cannot be added without editing this file.
        source = (SKILL_DIR / "engine" / "provision.py").read_text(encoding="utf-8")
        for vocabulary in ("state = running", "activestate", "=> disabled",
                           "unitfilestate"):
            self.assertNotIn(vocabulary, source.lower(),
                             f"provision.py reads a service manager format ({vocabulary})")


class VerifyReadsTheAnswerNotTheReturnCode(ProvisionBase):
    """Rule 4 on the provision side.

    A probe can exit 0 and say, in as many words, that the thing is not running.
    Deciding on the return code reported such a run as verified, and provision
    exited 0 for a workload that was down.
    """

    def probed(self):
        """A declaration that states what a healthy answer looks like."""
        root = self.tmpdir()
        source = (DERIVED / "block-style-report.yaml").read_text(encoding="utf-8")
        target = root / "probed-report.yaml"
        target.write_text(
            source.replace("id: block-style-report", "id: probed-report")
                  .replace("title: Block Style Report", "title: Probed Report")
            + '\nreconcile:\n  probe: "launchctl print gui/0/bridge.probed-report"\n'
              '  expect: "state = running"\n',
            encoding="utf-8")
        w = model.load_declaration(target)
        return w, render_mod.render(w, self.host(), self.ctx())

    def test_a_probe_that_exits_zero_while_saying_it_is_down_is_not_verified(self):
        w, a = self.probed()
        runner = RecordingRunner(default=FakeCompleted(
            rc=0, stdout=read_output("launchctl-print-stopped.txt")))
        verified, _evidence, trouble = provision._verified(
            w, self.host(), a, self.ctx(), timeout_sec=10, runner=runner)
        self.assertFalse(verified,
                         "the live source said 'state = not running' and the run was "
                         "still reported as verified")
        self.assertTrue(trouble)

    def test_the_declared_expect_is_what_decides(self):
        w, a = self.probed()
        runner = RecordingRunner(default=FakeCompleted(
            rc=0, stdout=read_output("launchctl-print-running.txt")))
        verified, evidence, _trouble = provision._verified(
            w, self.host(), a, self.ctx(), timeout_sec=10, runner=runner)
        self.assertTrue(verified)
        self.assertTrue(evidence)

    def test_a_probe_nobody_can_evaluate_is_unverified_and_says_why(self):
        w = self.load("public-funnel")   # probes https://<placeholder>/health
        verdict, _evidence, why = provision.ask_live_source(
            w, self.host(), None, timeout_sec=10, runner=RecordingRunner())
        self.assertEqual(verdict, mod("engine.probe").Verdict.unknown)
        self.assertTrue(why)


class WhatIsLeftOnTheMachine(ProvisionBase):
    """The end state, measured, instead of the step list, asserted.

    This is the layer the suite did not have, and every defect found on
    2026-08-23 lived in it. Five hundred and fifty seven cases all asked the
    same shape of question -- which steps were issued -- and a step list cannot
    see what a run LEAVES BEHIND. The rollback copy that nothing removed was
    invisible to every one of them, because each step they expected was in fact
    issued; the one that should have followed simply did not exist.

    So the file steps run for real here, against a throwaway home, and the
    assertion is the set of files that remain. A cycle of create, replace and
    retire has to end with nothing of this workload's on disk.
    """

    def sandbox(self):
        # `.resolve()` because /var is a symlink to /private/var on macOS and
        # the symlink guard is right to refuse a unit path that is not its own
        # physical path. The sandbox has to be a real directory, not a test that
        # switches the guard off.
        home = Path(self.tmpdir()).resolve()
        ctx = base.RenderContext(
            uid=FIXTURE_UID, home=str(home),
            stamp_dir=f"{home}/.bridge/workloads",
            dispatcher_registry=None, host_timezone=FIXTURE_TZ)
        w = self.load("calendar-export")
        return home, ctx, w, render_mod.render(w, self.host(), ctx)

    def runner_for(self, home, *, gone=False):
        runner = SandboxRunner(home)
        runner.add("print", FakeCompleted(
            rc=113 if gone else 0,
            stdout=read_output("launchctl-print-notfound.txt" if gone
                               else "launchctl-print-running.txt")))
        return runner

    def test_a_create_leaves_exactly_the_artifact_and_the_stamp(self):
        home, ctx, w, a = self.sandbox()
        root, _ = self.repo_with("calendar-export")
        runner = self.runner_for(home)
        provision.apply(provision.Plan("create", "nothing-provisioned", (), ()),
                        w, self.host(), a, ctx, dry_run=False, timeout_sec=10,
                        runner=runner, root=root)
        runner.assert_only_service_managers(self)
        expected = {str(Path(str(f.path)).relative_to(home)) for f in a.files}
        expected.add(".bridge/workloads/calendar-export.stamp.json")
        self.assertEqual(runner.tree(), expected,
                         "a create wrote something nobody declared, or missed "
                         "something it did declare")

    def test_the_whole_cycle_leaves_nothing_behind(self):
        home, ctx, w, a = self.sandbox()
        root, _ = self.repo_with("calendar-export")

        runner = self.runner_for(home)
        provision.apply(provision.Plan("create", "nothing-provisioned", (), ()),
                        w, self.host(), a, ctx, dry_run=False, timeout_sec=10,
                        runner=runner, root=root)
        provision.apply(provision.Plan("replace", "artifact-drift", (), ()),
                        w, self.host(), a, ctx, dry_run=False, timeout_sec=10,
                        runner=runner, root=root)

        # Measured HERE, before the retirement, and the mutation battery is why.
        # The first version of this case only looked at the end of the cycle,
        # and retire sweeps the rollback copies too -- so a replace that kept
        # its own copy was masked by the later sweep and the needle survived.
        # A stage whose mistake a later stage cleans up has to be measured at
        # that stage or not at all.
        after_replace = runner.tree()
        self.assertEqual(
            [f for f in after_replace if f.endswith(provision.PREVIOUS_SUFFIX)], [],
            "the replace verified, so its rollback copy had done its job and "
            f"should be gone; still there: {sorted(after_replace)}")

        gone = self.runner_for(home, gone=True)
        provision.retire(w, self.host(), a, ctx, reason="the probe served its purpose",
                         dry_run=False, confirmed=True, timeout_sec=10,
                         runner=gone, root=root)
        gone.assert_only_service_managers(self)

        left = gone.tree()
        # The stamp survives on purpose: it is the record that this was ours and
        # is now retired, and reconcile reads it to stay quiet about the id
        # rather than calling it an orphan. Everything else must be gone.
        self.assertEqual(
            left, {".bridge/workloads/calendar-export.stamp.json"},
            "after a full cycle these files were still on the machine, claimed "
            f"by nobody: {sorted(left)}")


class TheRollbackCopyIsNotLitter(ProvisionBase):
    """`.prev` is a rollback copy with a job, and it kept outliving the job.

    A replace copies each artifact file to `<path>.prev` so a failed verify can
    put the old one back. On a FAILED verify it is consumed by the restore. On a
    successful one nothing removed it, and retire removed only the files the
    stamp names, so a retired workload left a complete copy of its own unit file
    behind: unstamped, unlisted, owned by nobody, and carrying whatever the old
    argv and environment carried.

    Found on a real machine after the three probes were retired: the units were
    gone, the stamps said retired, and a `bridge.probe-tick.plist.prev` sat in
    the launch directory. The same file sat on the second machine too.
    """

    def prev_paths(self, artifact):
        return [str(f.path) + provision.PREVIOUS_SUFFIX for f in artifact.files]

    def runner_stopped(self):
        """The machine answering that the unit is gone, so a stop is provable."""
        runner = RecordingRunner()
        runner.add("print", FakeCompleted(
            rc=113, stdout=read_output("launchctl-print-notfound.txt")))
        runner.add("id -u", FakeCompleted(stdout=read_output("probe-context.txt")))
        return runner

    def runner_replacing(self):
        """The machine answering that the unit is there and ours."""
        runner = RecordingRunner()
        runner.add("id -u", FakeCompleted(stdout=read_output("probe-context.txt")))
        return runner

    def test_a_successful_replace_clears_the_copy_it_made(self):
        w, a = self.load("calendar-export"), self.artifact("calendar-export")
        root, _ = self.repo_with("calendar-export")
        runner = self.runner_replacing()
        provision.apply(
            provision.Plan("replace", "artifact-drift", (), ()),
            w, self.host(), a, self.ctx(), dry_run=False, timeout_sec=10,
            runner=runner, root=root)
        joined = runner.joined_calls
        for prev in self.prev_paths(a):
            self.assertIn(prev, joined,
                          "the rollback copy served its purpose and nothing "
                          "ever removes it, so every replace leaves one behind")
            self.assertIn("rm", joined, "and it has to be removed, not renamed")

    def test_retire_removes_the_copy_as_well_as_the_file(self):
        w, a = self.load("calendar-export"), self.artifact("calendar-export")
        root, _ = self.repo_with("calendar-export")
        runner = self.runner_stopped()
        provision.retire(w, self.host(), a, self.ctx(),
                         reason="the probe served its purpose",
                         dry_run=False, confirmed=True,
                         timeout_sec=10, runner=runner, root=root)
        joined = runner.joined_calls
        for prev in self.prev_paths(a):
            self.assertIn(prev, joined,
                          "the workload is gone and a full copy of its unit file "
                          "stayed on the machine, owned by nobody")

    def test_keeping_the_artifact_keeps_its_copy_too(self):
        # The counter control. `--keep-artifact` means leave the machine alone,
        # and a sweep that fires anyway would be the opposite of that.
        w, a = self.load("calendar-export"), self.artifact("calendar-export")
        root, _ = self.repo_with("calendar-export")
        runner = self.runner_stopped()
        provision.retire(w, self.host(), a, self.ctx(),
                         reason="kept on purpose, only the record is retired",
                         dry_run=False, confirmed=True, keep_artifact=True,
                         timeout_sec=10, runner=runner, root=root)
        for prev in self.prev_paths(a):
            self.assertNotIn(prev, runner.joined_calls,
                             "--keep-artifact leaves the machine alone")


class RetireProvesTheStop(ProvisionBase):
    """The declaration is written last, and only against proof.

    The stop gate used to know three service-manager phrases and nothing else,
    so a workload whose probe speaks any other language passed it silently: the
    repository recorded `retired:` while the machine carried on serving.
    """

    def serving(self):
        root = self.tmpdir()
        source = (DERIVED / "block-style-report.yaml").read_text(encoding="utf-8")
        target = root / "serving-report.yaml"
        target.write_text(
            source.replace("id: block-style-report", "id: serving-report")
                  .replace("title: Block Style Report", "title: Serving Report")
            + '\nreconcile:\n  probe: "curl -sS -o /dev/null -w %{http_code} '
              'http://127.0.0.1:9/health"\n  expect: "200"\n',
            encoding="utf-8")
        w = model.load_declaration(target)
        repo = make_repo(self.tmpdir(), declarations=())
        (repo / "workflow" / "workloads" / "serving-report.yaml").write_text(
            target.read_text(encoding="utf-8"), encoding="utf-8")
        return w, render_mod.render(w, self.host(), self.ctx()), repo

    def test_a_service_that_still_answers_blocks_the_retirement(self):
        w, a, repo = self.serving()
        path = repo / "workflow" / "workloads" / "serving-report.yaml"
        before = path.read_text(encoding="utf-8")
        runner = RecordingRunner(default=FakeCompleted(rc=0, stdout="200"))
        with self.assertRaises(errors.Refused) as ctx:
            provision.retire(w, self.host(), a, self.ctx(), reason="security bar, keep it shut",
                             dry_run=False, confirmed=True, timeout_sec=10,
                             runner=runner, root=repo)
        self.assert_error(ctx, "still-running", "serving-report")
        self.assertEqual(path.read_text(encoding="utf-8"), before,
                         "the repository claimed retired while the machine kept serving")

    def test_a_stop_that_cannot_be_proven_blocks_it_too(self):
        w, a, repo = self.serving()
        path = repo / "workflow" / "workloads" / "serving-report.yaml"
        before = path.read_text(encoding="utf-8")
        runner = RecordingRunner()
        runner.add("curl", raises=errors.StepTimeout(argv=("curl",), timeout_sec=5,
                                                     partial_stdout="", partial_stderr=""))
        with self.assertRaises(errors.Refused) as ctx:
            provision.retire(w, self.host(), a, self.ctx(), reason="security bar, keep it shut",
                             dry_run=False, confirmed=True, timeout_sec=10,
                             runner=runner, root=repo)
        self.assert_error(ctx, "stop-unproven", "serving-report")
        self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_a_service_that_stopped_answering_is_written_back(self):
        w, a, repo = self.serving()
        path = repo / "workflow" / "workloads" / "serving-report.yaml"
        runner = RecordingRunner(default=FakeCompleted(rc=7, stdout="000"))
        outcome = provision.retire(w, self.host(), a, self.ctx(),
                                   reason="security bar, keep it shut",
                                   dry_run=False, confirmed=True, timeout_sec=10,
                                   runner=runner, root=repo)
        self.assertTrue(outcome.verified)
        self.assertIn("retired:", path.read_text(encoding="utf-8"))


class ApplyRunsItsGuardsBeforeItTouchesAnything(ProvisionBase):

    def test_a_symlinked_unit_path_stops_apply_before_any_bootstrap(self):
        # The guard was only ever called on its own in a test, so removing the
        # call from apply changed nothing anybody could see.
        w, a = self.load("block-style-report"), self.artifact()
        runner = RecordingRunner()
        runner.add("pwd -P", FakeCompleted(stdout="/Volumes/Sync/LaunchAgents\n"))
        runner.add("launchctl print", completed_from("launchctl-print-running.txt"))
        plan = provision.plan(w, a, self.observation(a))
        root = make_repo(self.tmpdir())
        with self.assertRaises(errors.SymlinkedUnitPath) as ctx:
            provision.apply(plan, w, self.host(), a, self.ctx(), dry_run=False,
                            timeout_sec=10, runner=runner, root=root)
        self.assert_error(ctx, "symlinked-unit-path")
        self.assertNotIn("bootstrap", runner.joined_calls,
                         "a unit was loaded from a path the service manager refuses")
        self.assertNotIn(".stamp.json", runner.joined_calls)


class TheLockIsExclusive(ProvisionBase):
    """Rule 3 on the control plane, and it was a suggestion rather than a rule.

    A read followed by a write is two steps, and two sessions can both pass the
    read. Eight processes at a barrier held the same lock at once.
    """

    RACERS = 8

    def test_only_one_of_many_racers_holds_it(self):
        # The measurement the read-then-write lock could not survive.
        # Eight processes released at one barrier. With a pid read followed by a
        # write, seven of eight passed the read and all of them wrote: the file
        # said one name while eight sessions believed it said theirs. Nothing
        # short of concurrency shows that, which is why this test forks.
        import importlib
        import time

        real = importlib.import_module("engine.lock")
        root = self.tmpdir()
        go = root / "go"
        verdicts = root / "verdicts"
        verdicts.mkdir()

        kids = []
        for index in range(self.RACERS):
            pid = os.fork()
            if pid == 0:                                  # pragma: no cover - child
                code = 3
                try:
                    while not go.exists():
                        time.sleep(0.005)
                    with real.workload_lock(root, "raced"):
                        (verdicts / f"held-{index}").write_text("", encoding="utf-8")
                        time.sleep(1.0)
                        code = 0
                except errors.LockHeld:
                    code = 2
                except BaseException:
                    code = 3
                os._exit(code)
            kids.append(pid)

        go.write_text("go", encoding="utf-8")
        outcomes = []
        for pid in kids:
            _, status = os.waitpid(pid, 0)
            outcomes.append(os.waitstatus_to_exitcode(status))

        held = sorted(p.name for p in verdicts.iterdir())
        self.assertEqual(len(held), 1,
                         f"{len(held)} of {self.RACERS} processes held the same lock "
                         f"at once: {held}")
        self.assertEqual(outcomes.count(0), 1)
        self.assertEqual(outcomes.count(2), self.RACERS - 1,
                         f"a racer failed for the wrong reason: {outcomes}")

    def test_the_exclusion_is_a_kernel_lock_and_not_a_read(self):
        # Structural, and it is the half a race cannot show reliably: a lock
        # that decides from a pid FILE is racy however carefully it is written.
        import ast

        source = (SKILL_DIR / "engine" / "lock.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and getattr(node.func, "attr", None) == "flock"]
        self.assertTrue(calls, "lock.py takes no kernel lock, so it only reads a file")
        self.assertIn("LOCK_NB", source,
                      "a blocking acquire turns a held lock into a hang instead of a "
                      "refusal that names the holder")

    def test_retire_holds_the_lock_too(self):
        # And the refusal has to come BEFORE the first word to the machine.
        # The exception alone is the weaker half. Retire stops a unit for good:
        # bootout, then a persistent disable. If the lock is only consulted
        # after that loop has run, two sessions each stop the same live service
        # and the second one boots out something the first already owns, while
        # both still report a clean refusal. So the assertion is the untouched
        # machine, not the raised error. The sibling case above spells the same
        # rule for a refused reason.
        w, a = self.load("calendar-export"), self.artifact("calendar-export")
        root = make_repo(self.tmpdir(), declarations=("calendar-export",))
        runner = RecordingRunner()
        runner.add("print", FakeCompleted(
            rc=113, stdout=read_output("launchctl-print-notfound.txt")))
        with lock_mod.workload_lock(root, "calendar-export"):
            with self.assertRaises(errors.LockHeld):
                provision.retire(w, self.host(), a, self.ctx(),
                                 reason="superseded by the timer",
                                 dry_run=False, confirmed=True,
                                 timeout_sec=10, runner=runner, root=root)
        self.assertEqual(
            runner.calls, [],
            f"the refused retire had already talked to the machine before it "
            f"looked at the lock:\n{runner.joined_calls}")

    def test_adopt_holds_the_lock_too(self):
        # Adopt reads the machine first, and reading is free. Writing is not.
        # The one thing adopt changes is the ownership record, and two sessions
        # writing one record for the same id is the exact collision the lock
        # exists for. So this does not demand an untouched runner (observe has
        # legitimately run), it demands that nothing MUTATING happened, which is
        # what a stamp write would be.
        w, a = self.load("block-style-report"), self.artifact()
        root = make_repo(self.tmpdir())
        runner = RecordingRunner()
        runner.add("print", completed_from("launchctl-print-no-marker.txt"))
        with lock_mod.workload_lock(root, "block-style-report"):
            with self.assertRaises(errors.LockHeld):
                provision.adopt(w, self.host(), a, self.ctx(), timeout_sec=10,
                                dry_run=False, runner=runner, root=root)
        self.assert_no_mutation(runner)
        self.assertNotIn(
            "BRIDGE_WORKLOAD_STAMP", runner.joined_calls,
            "the refused adopt wrote the ownership record anyway, which is the one "
            "thing the lock is there to serialise")


class TheSymlinkGuard(ProvisionBase):
    """launchctl bootstrap on a symlinked path fails with Error 5."""

    def test_a_symlinked_unit_path_is_refused(self):
        runner = RecordingRunner()
        runner.add("pwd", FakeCompleted(stdout="/Volumes/Sync/LaunchAgents\n"))
        with self.assertRaises(errors.SymlinkedUnitPath) as ctx:
            provision.symlink_guard(f"{FIXTURE_HOME}/Library/LaunchAgents/bridge.x.plist",
                                    self.host(), timeout_sec=10, runner=runner)
        self.assert_error(ctx, "symlinked-unit-path", "LaunchAgents")

    def test_an_honest_path_passes(self):
        runner = RecordingRunner()
        runner.add("pwd", FakeCompleted(stdout=f"{FIXTURE_HOME}/Library/LaunchAgents\n"))
        provision.symlink_guard(f"{FIXTURE_HOME}/Library/LaunchAgents/bridge.x.plist",
                                self.host(), timeout_sec=10, runner=runner)

    def test_it_resolves_with_pwd_not_with_readlink(self):
        # BSD readlink -f support is not universal.
        runner = RecordingRunner()
        runner.add("pwd", FakeCompleted(stdout=f"{FIXTURE_HOME}/Library/LaunchAgents\n"))
        provision.symlink_guard(f"{FIXTURE_HOME}/Library/LaunchAgents/bridge.x.plist",
                                self.host(), timeout_sec=10, runner=runner)
        self.assertIn("pwd -P", runner.joined_calls)
        self.assertNotIn("readlink -f", runner.joined_calls)

    def test_the_interpreter_path_obeys_the_opposite_rule(self):
        # placement.interpreter is the TCC client path and must be emitted
        # verbatim. A resolved path is a different client with no grant.
        w = self.load("calendar-export")
        a = render_mod.render(w, self.host(), self.ctx())
        blob = "".join(
            f.content.decode("utf-8") if isinstance(f.content, bytes) else f.content
            for f in a.files)
        self.assertIn("/opt/bridge/bin/uv-calendar", blob)


class TheInvariantGateGuardsTheLayerThatActs(ProvisionBase):
    """Rule 1 does not hold because `validate` exists. It holds where it is ASKED.

    Only the `validate` command ever asked it. `provision` rendered and placed
    whatever `load_declaration` accepted, and `load_declaration` checks types and
    enums and deliberately not cross field rules. So a declaration missing
    `execution.timeout_sec` became a run with NO DEADLINE on a machine, and
    nothing said a word.

    It could not be caught further down either, which is the part worth writing
    out: `required_guarantees` derives the deadline demand FROM `timeout_sec`, so
    a missing deadline demands nothing, `wrapper.supplies` writes no guard
    script, and the unmet set that feeds the `degraded-backend` refusal is empty.
    With the default `process-group` isolation the process-group demand caught
    the case by accident; the fixture here sets `isolation: process` and takes
    that accident away.
    """

    FIXTURE = "negative-no-deadline-process.yaml"

    def no_deadline(self):
        return model.load_declaration(INVALID / self.FIXTURE)

    def with_a_deadline(self):
        """The same declaration, one key added. The Gegenprobe hangs off this."""
        text = (INVALID / self.FIXTURE).read_text(encoding="utf-8")
        text = text.replace("  isolation: process",
                            "  timeout_sec: 60\n  isolation: process")
        path = self.tmpdir() / "with-a-deadline.yaml"
        path.write_text(text.replace("id: negative-no-deadline-process",
                                     "id: with-a-deadline"), encoding="utf-8")
        return model.load_declaration(path)

    # -- the premise --------------------------------------------------------

    def test_the_fixture_really_is_invalid(self):
        # Without this the four cases below could all be measuring a valid file.
        found = model.validate(self.no_deadline().raw, source=self.FIXTURE)
        self.assertTrue(found, "the fixture stopped being invalid, so nothing here "
                               "is a test")
        self.assertIn("execution.timeout_sec", " ".join(f.detail for f in found))

    def test_nothing_downstream_of_the_gate_would_have_noticed(self):
        # This is the reason the gate has to sit in plan() and not be left to
        # the guarantee arithmetic: the arithmetic has nothing to work with.
        w = self.no_deadline()
        a = render_mod.render(w, self.host(), self.ctx())
        demanded = {g.value for g in model.required_guarantees(w)}
        self.assertNotIn("deadline", demanded,
                         "a missing deadline demands a deadline, so the degraded "
                         "refusal would have caught this and the gate is untested")
        unmet = (frozenset(model.required_guarantees(w))
                 - frozenset(a.guarantees_native) - frozenset(a.guarantees_wrapped))
        self.assertEqual(unmet, frozenset(),
                         "something is unmet, so the degraded refusal covers this case")
        self.assertNotIn(".guard.sh", " ".join(str(f.path) for f in a.files),
                         "a guard script was written, so the run would have had a "
                         "deadline after all")

    # -- the gate -----------------------------------------------------------

    def test_an_invalid_declaration_never_becomes_a_plan(self):
        w = self.no_deadline()
        a = render_mod.render(w, self.host(), self.ctx())
        plan = provision.plan(w, a, self.observation(a))
        self.assertEqual(plan.action, "refuse")
        self.assertEqual(plan.reason_code, "invalid-declaration")

    def test_the_refusal_names_the_key_that_is_wrong(self):
        w = self.no_deadline()
        a = render_mod.render(w, self.host(), self.ctx())
        plan = provision.plan(w, a, self.observation(a))
        self.assertIn("execution.timeout_sec", " ".join(plan.warnings),
                      "a refusal that does not name the key sends a human hunting")

    def test_the_gate_still_needs_no_machine(self):
        # plan() is pure, and a gate that reads a file or starts a process would
        # take that away from the whole decision table.
        w = self.no_deadline()
        a = render_mod.render(w, self.host(), self.ctx())
        observation = self.observation(a)
        plan = self.assert_pure(lambda: provision.plan(w, a, observation),
                                what="plan() with the invariant gate")
        self.assertEqual(plan.reason_code, "invalid-declaration")

    # -- the Gegenprobe -----------------------------------------------------

    def test_the_same_declaration_with_a_deadline_plans_normally(self):
        # The gate refuses THIS declaration, not every declaration. Without this
        # half, a plan() that returned "refuse" unconditionally would pass above.
        w = self.with_a_deadline()
        self.assertEqual(model.validate(w.raw, source="with-a-deadline.yaml"), [])
        a = render_mod.render(w, self.host(), self.ctx())
        plan = provision.plan(w, a, self.observation(a))
        self.assertEqual(plan.action, "create")
        self.assertEqual(plan.reason_code, "nothing-provisioned")


class TheStopIsNeverAnAccident(ProvisionBase):
    """The bolt in front of the only command that stops a running service.

    `retire` took one boolean and trusted it. `cli.cmd_retire` declared
    --dry-run, then computed `dry_run=not args.yes` and never read
    `args.dry_run`, so `workload retire <id> --reason ... --yes --dry-run` ran
    `launchctl bootout`, `launchctl disable`, deleted the guard script and wrote
    `retired:` into the declaration. Exit code 0, not one word of warning. The
    safety word on the destructive command did nothing.

    So the decision is taken here now, from TWO signals that are not each other's
    negation, and it is fail closed on both: an explicit dry run stops nothing,
    and neither does a run nobody confirmed. `confirmed=None` is the caller
    saying nothing, and saying nothing is not saying yes.
    """

    def runner_stopped(self):
        """The machine answering that the unit is gone, so a stop is provable."""
        runner = RecordingRunner()
        runner.add("print", FakeCompleted(
            rc=113, stdout=read_output("launchctl-print-notfound.txt")))
        runner.add("id -u", FakeCompleted(stdout=read_output("probe-context.txt")))
        return runner

    def assert_untouched(self, runner, path, before):
        for verb in ("bootout", "disable", "rm ", ".stamp.json"):
            self.assertNotIn(verb, runner.joined_calls,
                             f"a run that was not meant to act ran {verb!r}")
        self.assertEqual(path.read_text(encoding="utf-8"), before,
                         "the declaration was written back by a run that acted on nothing")

    # -- the two noes -------------------------------------------------------

    def test_an_explicit_dry_run_stops_nothing_even_when_confirmed(self):
        w, a = self.load("calendar-export"), self.artifact("calendar-export")
        root, path = self.repo_with("calendar-export")
        before = path.read_text(encoding="utf-8")
        runner = self.runner_stopped()
        outcome = provision.retire(w, self.host(), a, self.ctx(),
                                   reason="superseded by the timer",
                                   dry_run=True, confirmed=True,
                                   timeout_sec=10, runner=runner, root=root)
        self.assertFalse(outcome.verified)
        self.assert_untouched(runner, path, before)

    def test_a_retirement_nobody_confirmed_is_refused_and_touches_nothing(self):
        w, a = self.load("calendar-export"), self.artifact("calendar-export")
        root, path = self.repo_with("calendar-export")
        before = path.read_text(encoding="utf-8")
        runner = self.runner_stopped()
        with self.assertRaises(errors.Refused) as ctx:
            provision.retire(w, self.host(), a, self.ctx(),
                             reason="superseded by the timer",
                             dry_run=False, timeout_sec=10, runner=runner, root=root)
        self.assert_error(ctx, "unconfirmed-stop")
        self.assert_untouched(runner, path, before)

    def test_the_refusal_is_raised_and_not_returned(self):
        # cli.cmd_retire prints two fields of the Outcome and nothing else, so a
        # refusal handed back as findings would be invisible at the command line.
        w, a = self.load("calendar-export"), self.artifact("calendar-export")
        root, _ = self.repo_with("calendar-export")
        with self.assertRaises(errors.Refused) as ctx:
            provision.retire(w, self.host(), a, self.ctx(), reason="superseded by the timer",
                             dry_run=False, confirmed=False,
                             timeout_sec=10, runner=self.runner_stopped(), root=root)
        self.assertEqual(ctx.exception.exit_code, 3, "a guard refusal exits 3")

    # -- the yes ------------------------------------------------------------

    def test_a_confirmed_retirement_without_a_dry_run_really_stops_it(self):
        # The Gegenprobe. Without it the bolt could simply have disabled the
        # command and every case above would still pass.
        w, a = self.load("calendar-export"), self.artifact("calendar-export")
        root, path = self.repo_with("calendar-export")
        runner = self.runner_stopped()
        outcome = provision.retire(w, self.host(), a, self.ctx(),
                                   reason="superseded by the timer",
                                   dry_run=False, confirmed=True,
                                   timeout_sec=10, runner=runner, root=root)
        self.assertTrue(outcome.verified)
        self.assertIn("bootout", runner.joined_calls)
        self.assertIn("disable", runner.joined_calls)
        self.assertIn("retired:", path.read_text(encoding="utf-8"))

    # -- the table ----------------------------------------------------------

    def test_the_two_signals_are_not_each_others_negation(self):
        # The whole defect in one line: a caller that owns one boolean and
        # derives the other has exactly one place to get it wrong.
        table = {
            (True, True): False,      # --yes --dry-run: the case that stopped a service
            (True, False): False,
            (True, None): False,
            (False, True): True,      # the only yes on this table
            (False, False): False,
            (False, None): False,     # nobody said anything, which is not a yes
        }
        for (dry_run, confirmed), expected in table.items():
            may, why = provision.may_stop(dry_run=dry_run, confirmed=confirmed)
            self.assertEqual(may, expected,
                             f"dry_run={dry_run}, confirmed={confirmed} decided {may}")
            self.assertEqual(bool(why), not expected,
                             "a refusal without a reason tells the human nothing")

    def test_the_command_line_cannot_stop_a_service_while_asking_for_a_dry_run(self):
        # End to end, from the argv a human types. `--dry-run` beside `--yes` was
        # parsed and then thrown away one layer down, and this is the run that
        # booted out a live unit. It is asserted HERE, at the layer that acts, so
        # the safety does not hang on the wiring in a file this module does not own.
        import contextlib
        import io

        import engine.exec as exec_module
        from unittest import mock

        cli = mod("engine.cli")
        root, path = self.repo_with("calendar-export")
        before = path.read_text(encoding="utf-8")
        runner = self.runner_stopped()

        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(exec_module, "step_runner",
                               lambda step, host, **kw: runner(step.argv, step=step, **kw)):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = cli.main(["--root", str(root), "retire", "calendar-export",
                               "--reason", "superseded by the timer", "--yes", "--dry-run"])

        self.assertNotEqual(rc, 0, "a run that stopped nothing exited clean")
        self.assert_untouched(runner, path, before)


if __name__ == "__main__":
    unittest.main()


class EveryUnitFilesItsOwnStamp(ProvisionBase):
    """Two units of one run are two ownership records, or one of them is lost.

    MEASURED ON A REAL MACHINE, 2026-08-24, minutes after this feature landed.
    Both units of a migrated report were provisioned and verified, and the
    machine carried exactly ONE stamp file, named after the declaration. The
    later unit had written over the earlier one's record on its way in, so the
    earlier unit was running, correct, and indistinguishable from one that had
    never been provisioned at all.

    The reading side already used the unit's state key; the WRITING side still
    used the declaration id, and the pair of them was never measured together.
    A test that renders is not a test that writes.

    `state_key` on the record is what closes it, and it is defaulted to the
    workload id so that every stamp written before this field existed still
    means exactly what it meant.
    """

    def stamps_written(self, spec="twice-daily-report"):
        """Every path a provision of `spec` would write a stamp to."""
        render = mod("engine.render")
        w = self.load(spec)
        paths = []
        for artifact in render.render_all(w, self.host(), self.ctx()):
            record = provision._stamp_for(w, self.host(), artifact,
                                          adopted=False, root=None)
            paths.append(stamp_mod.stamp_file(self.ctx().stamp_dir, record))
        return paths

    def test_two_appointments_write_two_records(self):
        paths = self.stamps_written()
        self.assertEqual(len(set(paths)), 2,
                         "both units file their record under one path, so the "
                         f"second overwrites the first: {paths}")

    def test_each_record_is_named_after_its_own_unit(self):
        names = sorted(p.rsplit("/", 1)[-1] for p in self.stamps_written())
        for name in names:
            self.assertRegex(name, r"twice-daily-report\.(morning|midday)\.",
                             f"a record is not named after its unit: {name}")

    def test_a_single_appointment_run_keeps_the_bare_name(self):
        # Nothing already on a machine may be renamed by this.
        paths = self.stamps_written("block-style-report")
        self.assertEqual(len(paths), 1)
        self.assertTrue(paths[0].endswith("block-style-report.stamp.json"),
                        f"the ordinary case was renamed: {paths[0]}")


class ARunThatNeverEndsHasNoDeadlineToEnforce(ProvisionBase):
    """A daemon the bridge owns could not be provisioned at all, and the refusal
    named the wrong thing.

    `required_guarantees` derived `process_group_kill` from `execution.isolation`
    alone, whose schema default is `process-group` and which therefore holds for
    every declaration nobody thought about. The guard offers that guarantee only
    together with `deadline`, and only for a kind that ENDS
    (`backends/wrapper.py`); launchd carries neither natively. The demand was
    unmeetable by construction, so every daemon ended in
    `refuse / degraded-backend`, a code that reads as a property of the backend
    while the cause is a category error: `process_group_kill` exists to enforce a
    deadline, and a run that never ends has none.

    The two derivations of one fact are the point, not the refusal. The wrapper
    is the authority on when the guarantee is POSSIBLE; the requirement was
    derived somewhere else, from a field whose default nobody chose.
    """

    NAME = "long-running-poller"
    FINITE = "block-style-report"

    def daemon(self):
        return self.load(self.NAME)

    # -- the premise --------------------------------------------------------

    def test_the_fixture_is_a_bridge_owned_daemon_with_a_command(self):
        # Without every part of this, the cases below could be measuring
        # something else entirely: an unowned run, a retired one, or one that
        # renders no unit because it has nothing to run.
        w = self.daemon()
        self.assertEqual(w.placement.kind, "daemon")
        self.assertTrue(w.is_bridge_owned)
        self.assertFalse(w.is_retired)
        self.assertTrue(base.command_of(w), "no command, so there is no plan to measure")
        self.assertFalse(model.validate(w.raw, source=self.NAME),
                         "the fixture stopped passing the invariants")

    def test_the_default_isolation_is_in_force(self):
        # The whole finding hangs off a default nobody typed. If the fixture
        # ever spells `isolation` out, this test is measuring a choice instead.
        self.assertEqual(self.daemon().execution.isolation, "process-group")

    def test_the_guard_cannot_supply_it_for_a_kind_that_never_ends(self):
        # The authority the requirement has to agree with.
        w = self.daemon()
        a = render_mod.render(w, self.host(), self.ctx())
        offered = set(a.guarantees_native) | set(a.guarantees_wrapped)
        self.assertNotIn(model.Guarantee.process_group_kill, offered)

    # -- the case -----------------------------------------------------------

    def test_a_run_that_never_ends_does_not_demand_it(self):
        self.assertNotIn(model.Guarantee.process_group_kill,
                         model.required_guarantees(self.daemon()))

    def test_a_daemon_can_be_provisioned_at_all(self):
        w = self.daemon()
        a = render_mod.render(w, self.host(), self.ctx())
        plan = provision.plan(w, a, self.observation(a))
        self.assertNotEqual(plan.reason_code, "degraded-backend",
                            "the daemon path is still nailed shut")
        self.assertEqual(plan.action, "create")

    def test_nothing_is_left_unmet(self):
        w = self.daemon()
        a = render_mod.render(w, self.host(), self.ctx())
        unmet = (frozenset(model.required_guarantees(w))
                 - frozenset(a.guarantees_native) - frozenset(a.guarantees_wrapped))
        self.assertEqual(unmet, frozenset())

    # -- the control --------------------------------------------------------

    def test_a_run_that_ends_still_demands_it(self):
        # The narrow fix must not become a blanket switch. A finite run keeps
        # its process-group demand, which is the whole reason the field exists.
        w = self.load(self.FINITE)
        self.assertNotIn(w.placement.kind, model.CONTINUOUS_KINDS,
                         "the control stopped being a finite run")
        self.assertEqual(w.execution.isolation, "process-group")
        self.assertIn(model.Guarantee.process_group_kill, model.required_guarantees(w))


class ADaemonIsProvedByAProcessNotByALoadedLabel(ProvisionBase):
    """`provision` reported a daemon as verified while it was dead.

    The backend default probe is `launchctl print <ref>`, and
    `probe.resolve_probe` handed it out with `expect=None`. With no expect,
    `probe.evaluate` falls back to the return code, and that command answers 0
    for a unit that is merely LOADED. Measured on a live machine on 2026-08-26:
    a loaded, not running unit returns 0.

    `ask_live_source` warns about precisely this in its own docstring: "a probe
    can exit 0 while saying, in as many words, that the thing is not running".
    The sentence was true one level below the place it was written.

    For a run that ends, the return code IS the answer, and nothing here
    changes that. For one that never ends there is no return code to have, so
    the only honest evidence is a process.
    """

    NAME = "long-running-poller"
    FINITE = "block-style-report"

    LOADED_AND_DEAD = "\n".join((
        "gui/4242/bridge.long-running-poller = {",
        "\tactive count = 0",
        "\tstate = not running",
        "\tlast exit code = 0",
        "}",
    ))
    LOADED_AND_ALIVE = "\n".join((
        "gui/4242/bridge.long-running-poller = {",
        "\tactive count = 1",
        "\tpid = 4711",
        "\tstate = running",
        "}",
    ))

    def ask(self, name, stdout, rc=0):
        w = self.load(name)
        a = render_mod.render(w, self.host(), self.ctx())
        runner = RecordingRunner(default=FakeCompleted(rc=rc, stdout=stdout))
        return provision.ask_live_source(w, self.host(), a, timeout_sec=5, runner=runner)

    # -- the premise --------------------------------------------------------

    def test_the_dead_answer_really_does_return_zero(self):
        # Without this the case below could be passing because of an rc, which
        # would make it a test of nothing.
        verdict, _, _ = self.ask(self.FINITE, self.LOADED_AND_DEAD)
        self.assertEqual(verdict, mod("engine.probe").Verdict.pass_,
                         "rc 0 no longer passes, so the premise of this class is gone")

    # -- the case -----------------------------------------------------------

    def test_a_loaded_corpse_is_not_a_running_daemon(self):
        verdict, _, why = self.ask(self.NAME, self.LOADED_AND_DEAD)
        self.assertEqual(verdict, mod("engine.probe").Verdict.fail,
                         f"a dead daemon was confirmed as healthy ({why})")

    def test_a_process_is(self):
        verdict, evidence, why = self.ask(self.NAME, self.LOADED_AND_ALIVE)
        self.assertEqual(verdict, mod("engine.probe").Verdict.pass_,
                         f"a running daemon was not confirmed ({why})")
        self.assertTrue(evidence)

    def test_verify_refuses_to_call_a_corpse_provisioned(self):
        w = self.load(self.NAME)
        a = render_mod.render(w, self.host(), self.ctx())
        runner = RecordingRunner(default=FakeCompleted(rc=0, stdout=self.LOADED_AND_DEAD))
        ok, _, notes = provision._verified(w, self.host(), a, self.ctx(),
                                           timeout_sec=5, runner=runner)
        self.assertFalse(ok, "provision would report a dead daemon as verified")
        self.assertTrue(notes)

    # -- the control --------------------------------------------------------

    def test_a_run_that_ends_is_still_judged_by_its_return_code(self):
        # The same corpse text, asked about a run that ends. Nothing about a
        # finite run may change: its probe answers about a unit that is
        # supposed to be idle between fires, and demanding a pid there would
        # call every healthy scheduled run dead.
        verdict, _, _ = self.ask(self.FINITE, self.LOADED_AND_DEAD)
        self.assertEqual(verdict, mod("engine.probe").Verdict.pass_)

    def test_a_declared_probe_still_wins_over_the_backend_default(self):
        # The precedence in resolve_probe is the contract. A daemon that
        # declares its own probe must keep it, or this fix would silently
        # overrule every hand written expectation.
        w = self.load("voice-channel")
        self.assertTrue(getattr(w.reconcile, "probe", ""),
                        "the control fixture lost its declared probe")
        spec = mod("engine.probe").resolve_probe(
            w, self.host(), None, Path("."), None)
        self.assertEqual(spec.source, "declaration")
