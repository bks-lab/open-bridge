"""The mutation battery: proof that the suite has teeth.

Every entry names a literal inside a source, the softened version of it, and the
ONE test that must turn red when the softening is applied. A suite that stays
green under any of these is not a suite: it would report a proof nobody ran,
which is worse than reporting none.

Each needle is a real defect, not an invented one. Seven were live in this tree
and were found by an audit; two more guard behaviour that had no test at all
until that audit pointed at the gap.

The last block came out of a second audit, which softened the code under six
cases that LOOKED like checks and watched the whole suite stay green. Each of
those six now has its own needle here. One of them names `tests/conftest.py`
rather than an engine source, deliberately: the machine guard is code too, it is
the only thing keeping this suite off live boxes, and in a green run it never
fires, so nothing but a needle would ever notice it had stopped refusing.

A third audit produced the block after that. Three of its findings were real
defects in behaviour rather than weak tests: `reconcile` reported a run over a
mistyped id as clean, `run-tests.sh` scored an all-skipped run green, and a
deadline of `inf` or `nan` reached `proc.wait` as no deadline at all. The rest
were eight more cases whose NAME promised a property their BODY did not measure.
Two of that block's needles name `scripts/tests/tally.awk` and the wrapper: the
runner's own verdict is code, and so is a backend helper that both `render` and
`preflight` reach through.

A needle may only name a test that RUNS in the scratch copy. FIVE cases depend
on files that live in the repository and not in this skill (the declaration
schema, the declaration template, and the surface the leak scan reaches across);
they skip there, by name and with a reason, and naming one of them here would
score a skip as a pass. The count was written down as three, and the tally is
what corrected it: it now prints the skips instead of folding them into the
total, so a detached run says `351/356 green, 5 skipped` where it used to say
`356/356 green`. The same rule is enforced at the other end too, where it
matters most: a run in which EVERY case skipped is red.

`run-tests.sh --mutate` copies the skill into a scratch directory, applies one
mutation at a time, runs the named test there, and asserts it fails. The working
tree is never touched.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Mutation:
    """One softening, and the single test that has to notice it."""

    name: str
    file: str
    search: str
    replace: str
    test: str
    scar: str


#: The tally as it stands, and the tally as it was. The needle
#: `an-all-skipped-run-is-scored-green` swaps one for the other, so the entry is
#: the ACTUAL previous code rather than a paraphrase of it.
TALLY_AS_IT_IS = r"""END {
  printf "\n"
  total = ok + bad + skipped
  if (total == 0) {
    printf "no test cases were collected, which is itself a failure\n"
  } else if (bad > 0) {
    printf "%d of %d FAILED\n", bad, total
  } else if (ok == 0) {
    printf "0 of %d ran: every case was skipped, so this run says nothing\n", total
  } else if (skipped > 0) {
    printf "%d/%d green, %d skipped\n", ok, total, skipped
  } else {
    printf "%d/%d green\n", ok, total
  }
  exit (bad > 0 || ok == 0) ? 1 : 0
}"""

TALLY_AS_IT_WAS = r"""END {
  printf "\n"
  total = ok + bad + skipped
  if (bad == 0 && total > 0) {
    printf "%d/%d green\n", ok, total
  } else if (total == 0) {
    printf "no test cases were collected, which is itself a failure\n"
  } else {
    printf "%d of %d FAILED\n", bad, total
  }
  exit (bad > 0 || total == 0) ? 1 : 0
}"""


MUTATIONS = (
    Mutation(
        name="errexit-does-not-silence-the-unreachable-status",
        file="engine/model.py",
        search="        if _ERREXIT.match(line) or _EXEC.match(line):",
        replace="        if _EXEC.match(line):",
        test="tests.test_cli.AStatusNobodyCanReturnIsNoStatus"
             ".test_errexit_silences_it",
        scar="under `set -e` a script ends on the failing command itself, "
             "before the catch line is ever reached, and its return value is "
             "that command's. Thirty four of eighty five scripts carry the flag",
    ),
    Mutation(
        name="a-loud-exit-inside-a-called-function-is-not-seen",
        file="engine/model.py",
        search="        if any(re.search(rf\"\\b{re.escape(name)}\\b\", naked) for name in loud_functions):",
        replace="        if False:",
        test="tests.test_cli.AStatusNobodyCanReturnIsNoStatus"
             ".test_a_function_with_a_loud_exit_that_is_called_afterwards_silences_it",
        scar="a script whose error path is a function reads as one with no way "
             "out at all, and the gate would refuse work that is sound",
    ),
    Mutation(
        name="a-signal-handler-counts-as-an-exit-trap",
        file="engine/model.py",
        search='        if not any(sig.strip("\\"\'").upper() in ("EXIT", "0") for sig in signals):',
        replace="        if False:",
        test="tests.test_cli.AnExitTrapMayNotEatTheStatus"
             ".test_a_handler_bound_only_to_signals_stays_silent",
        scar="a stop on request is not a failure and its handler SHOULD end in "
             "zero; widening the rule to every handler forbids exactly the "
             "repair that was built on 2026-08-26",
    ),
    Mutation(
        name="two-rules-answer-for-one-script",
        file="engine/cli.py",
        search="    if model.ends_in_bare_exit_zero(text):",
        replace="    if False and model.ends_in_bare_exit_zero(text):",
        test="tests.test_cli.TheThreeShapesDivideTheSameDefect"
             ".test_a_script_that_fits_two_rules_is_reported_once",
        scar="a script can satisfy two of the three rules at once, and two "
             "lines for one defect read as two defects",
    ),
    Mutation(
        name="a-trace-is-looked-up-under-the-bare-id",
        file="engine/reconcile.py",
        search="        key = model.state_key(w, appointment)",
        replace="        key = w.id",
        test="tests.test_reconcile.ARunWithTwoAppointmentsWritesTwoTraces"
             ".test_both_appointment_traces_are_read",
        scar="the guard names a trace after the state key, so a run with two "
             "appointments writes two files and neither is called `<id>.trace`. "
             "On the live page that run carried two rings and no diamond, which "
             "reads as a job that has never fired",
    ),
    Mutation(
        name="the-history-keeps-the-oldest-runs",
        file="engine/reconcile.py",
        search="    kept = entries[-STRIP_MAX:]",
        replace="    kept = entries[:STRIP_MAX]",
        test="tests.test_reconcile.TheStripIsWhatTheMachineWroteDown"
             ".test_it_keeps_the_newest_and_says_how_many",
        scar="a cap that throws away the newest runs leaves a strip that looks "
             "like a history and stopped weeks ago",
    ),
    Mutation(
        name="the-verdict-is-rebuilt-from-the-return-value",
        file="engine/reconcile.py",
        search='                elif token.startswith("verdict="):',
        replace='                elif token.startswith("__never__"):',
        test="tests.test_reconcile.TheStripIsWhatTheMachineWroteDown"
             ".test_the_verdict_comes_from_the_line_and_is_not_derived_from_rc",
        scar="`expired` and a non zero return are different facts: one says a "
             "deadline cut the run off, the other says the program said no",
    ),
    Mutation(
        name="the-strip-is-drawn-newest-first",
        file="engine/view.py",
        search="    for entry in row.strip:",
        replace="    for entry in reversed(row.strip):",
        test="tests.test_view.TheStripSaysHowItHasBeenGoing"
             ".test_the_oldest_run_is_on_the_left",
        scar="a strip that reads right to left looks exactly like one that "
             "reads left to right, and every conclusion drawn from it is "
             "backwards",
    ),
    Mutation(
        name="an-unknown-verdict-vanishes-from-the-strip",
        file="engine/view.py",
        search='        shape = STRIP_SHAPES.get(verdict, STRIP_UNKNOWN)',
        replace='        shape = STRIP_SHAPES.get(verdict, "")',
        test="tests.test_view.TheStripSaysHowItHasBeenGoing"
             ".test_a_verdict_this_page_does_not_know_is_a_mark_and_not_a_gap",
        scar="a fifth verdict from the guard would disappear into the four this "
             "page happens to know, and the strip would be short by exactly the "
             "runs nobody understands",
    ),
    Mutation(
        name="a-daemons-deaths-are-drawn-as-runs",
        file="engine/view.py",
        search='        strip += f\'<div class="meta">{_esc(CONTINUOUS_STRIP_NOTE)}</div>\'',
        replace="        pass",
        test="tests.test_view.ARunThatNeverEndsHasNoRunsToShow"
             ".test_marks_are_named_as_ends_and_not_as_runs",
        scar="the guard of a continuous kind writes a line when the child "
             "returns, so its strip is a list of deaths; drawn without a word, "
             "four crashes read as four healthy firings",
    ),
    Mutation(
        name="a-person-named-in-a-declaration-reaches-the-page",
        file="engine/view.py",
        search='        slug = getattr(recipient, "mandant", "") or ""',
        replace='        slug = getattr(recipient, "person", "") or ""',
        test="tests.test_view.WhoIsDeclaredIsNotWhoWasReached"
             ".test_no_person_slug_reaches_the_page",
        scar="a person is named in a declaration by a slug, and a slug of a "
             "person is a name; this page is read by every device on the "
             "network it is served from",
    ),
    Mutation(
        name="declared-recipients-read-as-delivered-ones",
        file="engine/view.py",
        search='            f"reaches the group {groups}{people}. Declared, not delivered: "',
        replace='            f"reaches the group {groups}{people}. "',
        test="tests.test_view.WhoIsDeclaredIsNotWhoWasReached"
             ".test_the_sentence_says_which_of_the_two_facts_it_is",
        scar="nothing on the execution path reads the recipients, so a line "
             "printing them beside a green mark is the page claiming a delivery "
             "it never measured",
    ),
    Mutation(
        name="a-promise-to-report-a-failure-needs-no-floor",
        file="engine/cli.py",
        search="    findings.extend(_hollow_failure_promises(chosen, root))",
        replace="    findings.extend([])",
        test="tests.test_cli.APromiseToReportAFailureNeedsAFloor"
             ".test_a_hollow_promise_is_a_finding",
        scar="three runs on one machine asked to be told about their failures "
             "while their wrappers ended in a bare `exit 0`. 441 traces in three "
             "days read `verdict=ok` and not one carried a non-zero exit",
    ),
    Mutation(
        name="an-indented-exit-zero-counts-as-unconditional",
        file="engine/model.py",
        search='_BARE_EXIT_ZERO = re.compile(r"^exit\\s+0\\s*(?:#.*)?$")',
        replace='_BARE_EXIT_ZERO = re.compile(r"\\s*exit\\s+0\\s*(?:#.*)?$")',
        test="tests.test_cli.APromiseToReportAFailureNeedsAFloor"
             ".test_an_indented_exit_zero_is_guarded_by_something_and_not_the_case",
        scar="an `exit 0` inside an `if` is guarded by a condition and says "
             "nothing about the value a script returns however the run went; a "
             "rule that guesses is worse here than one that stays silent",
    ),
    Mutation(
        name="a-script-on-another-machine-is-judged-from-here",
        file="engine/cli.py",
        search="            resolved.relative_to(Path(root).resolve())",
        replace="            pass",
        test="tests.test_cli.APromiseToReportAFailureNeedsAFloor"
             ".test_a_path_outside_the_root_is_not_even_picked_as_the_script",
        scar="the path in a declaration is a path on ITS machine. Judging one "
             "from here works by accident wherever the home directory happens to "
             "have the same name, and falls silent on the next box",
    ),
    Mutation(
        name="asking-for-failure-does-not-ask-for-the-evidence",
        file="engine/model.py",
        search='    if "missing" in wants or ("failure" in wants and traceable):',
        replace='    if "missing" in wants:',
        test="tests.test_model.AskingForFailureAsksForTheEvidence"
             ".test_failure_alone_still_requires_the_trace",
        scar="the probe built to prove failures arrive wrote not a single line: "
             "the trace was tied to `missing` alone, so a declaration asking for "
             "`failure` got no place for its failure to be written down",
    ),
    Mutation(
        name="the-trace-is-never-read-back",
        file="engine/reconcile.py",
        search="        traces = read_traces(h, cfg, timeout_sec=timeout_sec, runner=runner) or {}",
        replace="        traces = {}",
        test="tests.test_reconcile.TheTraceIsReadBackOrTheEvidenceIsDecoration"
             ".test_the_trace_is_read_off_the_host",
        scar="the guard script writes one line per run and its own comment calls "
             "that line what makes an absent run detectable at all. Nothing read "
             "it back, so a run that failed and a run that never started were the "
             "same silence",
    ),
    Mutation(
        name="a-failed-run-reads-as-a-clean-one",
        file="engine/reconcile.py",
        search='    if "failure" in wants and newest is not None and newest[1] not in (None, 0) \\',
        replace='    if False and newest is not None and newest[1] not in (None, 0) \\',
        test="tests.test_reconcile.TheTraceIsReadBackOrTheEvidenceIsDecoration"
             ".test_the_newest_line_deciding_it_failed_is_reported",
        scar="the run ended non zero and wrote it down; a report that calls that "
             "in_sync is worse than no report",
    ),
    Mutation(
        name="every-transient-failure-stays-quiet",
        file="engine/reconcile.py",
        search="    return rc_newest in codes and verdict_newest == \"failed\" and rc_before == 0",
        replace="    return rc_newest in codes",
        test="tests.test_reconcile.TheTraceIsReadBackOrTheEvidenceIsDecoration"
             ".test_a_second_failure_in_a_row_speaks",
        scar="a retry request is quiet once; twice in a row is no longer a blip",
    ),
    Mutation(
        name="a-daemon-never-says-it-started",
        file="engine/backends/wrapper.py",
        search='        add("trace 0 0 started")',
        replace='        pass',
        test="tests.test_backends.AKindWithoutADeadlineIsKeptToo"
             ".test_a_daemon_writes_a_started_line_before_it_runs",
        scar="a daemon that crashed once was reported broken for twelve days "
             "because its trace only ever spoke at death",
    ),
    Mutation(
        name="an-absent-run-is-never-noticed",
        file="engine/reconcile.py",
        search="    if late > limit:",
        replace="    if False:",
        test="tests.test_reconcile.TheTraceIsReadBackOrTheEvidenceIsDecoration"
             ".test_a_cadence_that_stopped_firing_is_overdue",
        scar="one job lost 53 of 181 runs silently, and missing was listed in "
             "notify_on as the one nobody has today",
    ),
    Mutation(
        name="a-cadence-nobody-can-compute-passes-quietly",
        file="engine/reconcile.py",
        search="    if cadence is None:\n        # A recurring run states no gap in seconds",
        replace="    if False:\n        # A recurring run states no gap in seconds",
        test="tests.test_reconcile.TheTraceIsReadBackOrTheEvidenceIsDecoration"
             ".test_a_recurrence_outside_the_translated_subset_still_says_so",
        scar="it asked for missing detection and cannot get it; staying silent "
             "reads as nothing wrong, which is the defect this whole file hunts",
    ),
    Mutation(
        name="a-cadence-between-runs-is-called-stopped",
        file="engine/reconcile.py",
        search="    if unit.running is False and _kind_of(w) in model.CONTINUOUS_KINDS:",
        replace="    if unit.running is False:",
        test="tests.test_reconcile.OnlyAThingThatShouldBeRunningCanBeStopped"
             ".test_a_cadence_between_two_runs_is_not_stopped",
        scar="an interval job forty-five seconds after a successful run read as "
             "high stopped, and the hint told the reader to bootout and bootstrap "
             "a unit that was fine. A tool that cries about a healthy thing is a "
             "tool people stop reading",
    ),
    Mutation(
        name="the-marker-is-inferred-from-not-looking",
        file="engine/reconcile.py",
        search="    if looked and has_stamp and not has_marker:",
        replace="    if has_stamp and not has_marker:",
        test="tests.test_reconcile.TheMarkerIsNeverInferredFromNotLooking"
             ".test_a_stamped_unit_whose_marker_was_never_read_is_not_called_drift",
        scar="enumeration prints no environment, so the marker of a launchd or "
             "systemd unit is None until somebody asks. Reading that None as an "
             "absence made every correctly provisioned run report drift forever, "
             "with a repair hint that reproduced the same state on the next pass",
    ),
    Mutation(
        name="nobody-asks-the-machine-for-the-marker",
        file="engine/reconcile.py",
        search="    units = _read_markers(units, stamps, h, timeout_sec=timeout_sec,",
        replace="    units = units or _read_markers(units, stamps, h, timeout_sec=timeout_sec,",
        test="tests.test_reconcile.TheMarkerIsNeverInferredFromNotLooking"
             ".test_the_machine_is_asked_for_the_marker_of_a_unit_a_stamp_claims",
        scar="the second ownership signal sits INSIDE the unit. If observation "
             "never reads it back, the two signals are one signal, and a unit "
             "somebody else replaced under a kept stamp reads as healthy",
    ),
    Mutation(
        name="child-shares-the-caller-group",
        file="engine/exec.py",
        search="start_new_session=True,     # our own group",
        replace="start_new_session=False,    # our own group",
        test="tests.test_exec.TheDeadlineKillsTheProcessGroup"
             ".test_the_child_really_lands_in_a_group_of_its_own",
        scar="without its own session there is no group to kill, and the "
             "deadline can only end the direct child",
    ),
    Mutation(
        name="kill-the-child-instead-of-the-group",
        file="engine/exec.py",
        search="            os.killpg(pgid, sig)",
        replace="            os.kill(proc.pid, sig)",
        test="tests.test_exec.TheDeadlineKillsTheProcessGroup"
             ".test_no_process_of_the_group_is_left_alive",
        scar="a grandchild keeps the output pipe open and the cleanup after it "
             "blocks forever",
    ),
    Mutation(
        name="deadline-becomes-a-return-code",
        file="engine/exec.py",
        search="        raise errors.StepTimeout(\n            argv=argv,",
        replace="        return Completed(rc=124, stdout=_text(out), stderr=_text(err),\n"
                "                         argv=argv, duration_sec=0.0)\n"
                "        raise errors.StepTimeout(\n            argv=argv,",
        test="tests.test_exec.TheDeadlineKillsTheProcessGroup"
             ".test_the_deadline_is_never_returned_as_a_code",
        scar="a code is a value somebody can ignore, and a hang that returns 124 "
             "looks like a run",
    ),
    Mutation(
        name="replace-uses-kickstart",
        file="engine/backends/launchd.py",
        search='            argv=("launchctl", "bootout", a.unit_ref),\n'
               '            purpose=f"unload the running {a.unit_ref}",',
        replace='            argv=("launchctl", "kickstart", a.unit_ref),\n'
                '            purpose=f"unload the running {a.unit_ref}",',
        test="tests.test_backends.ReplaceIsBootoutThenBootstrap"
             ".test_the_string_kickstart_appears_nowhere_in_a_replace_plan",
        scar="kickstart restarts what is loaded, it does not reload a unit whose "
             "file changed, so a schedule change would silently not take",
    ),
    Mutation(
        name="overwrite-an-unstamped-collision",
        file="engine/provision.py",
        search='            return Plan("refuse", "collision-unstamped", (),',
        replace='            return Plan("create", "collision-unstamped", (),',
        test="tests.test_provision.ThePlanDecisionTable"
             ".test_files_without_a_stamp_and_without_a_marker_are_never_overwritten",
        scar="something that belongs to somebody else is overwritten without a word",
    ),
    Mutation(
        name="reprovision-instead-of-noop",
        file="engine/provision.py",
        search='        return Plan("noop", "already-in-sync", (), tuple(warnings))',
        replace='        return Plan("create", "already-in-sync", (), tuple(warnings))',
        test="tests.test_provision.ThePlanDecisionTable.test_the_same_digest_is_a_no_op",
        scar="a second run boots a healthy service out and back in for nothing, "
             "which is what makes the command unsafe to automate",
    ),
    Mutation(
        name="unreachable-reads-as-gone",
        file="engine/reconcile.py",
        search="            state.unknown, sev.medium,\n"
               "            f\"{host_obs.host} did not answer: {host_obs.error}\",",
        replace="            state.absent, sev.high,\n"
                "            f\"{host_obs.host} did not answer: {host_obs.error}\",",
        test="tests.test_reconcile.TheThirteenStates.test_each_scenario_lands_on_its_state",
        scar="unobserved is not gone; that collapse is how seventeen jobs were "
             "once declared overdue",
    ),
    Mutation(
        name="retire-renames-instead-of-disabling",
        file="engine/backends/launchd.py",
        search='                argv=("launchctl", "disable", a.unit_ref),\n'
               '                purpose=f"keep {a.unit_ref} off across reboots, reason: {reason}",',
        replace='                argv=("/bin/sh", "-c",\n'
                '                      f"mv {self._unit_file(a)} {self._unit_file(a)}.disabled"),\n'
                '                purpose=f"keep {a.unit_ref} off across reboots, reason: {reason}",',
        test="tests.test_backends.DisableIsPersistentAndCarriesTheReason"
             ".test_disable_is_more_than_a_bootout",
        scar="only the persistent disable survives a reboot, and a renamed file "
             "has lost the why by the time anybody asks",
    ),
    Mutation(
        name="apply-skips-the-symlink-guard",
        file="engine/provision.py",
        search="            for unit_path in _guarded_paths(artifact):\n"
               "                symlink_guard(unit_path, host, timeout_sec=timeout_sec, runner=runner)",
        replace="            for unit_path in _guarded_paths(artifact):\n"
                "                pass",
        test="tests.test_provision.ApplyRunsItsGuardsBeforeItTouchesAnything"
             ".test_a_symlinked_unit_path_stops_apply_before_any_bootstrap",
        scar="loading a unit from a symlinked path fails outright, and a launch "
             "directory that is a link into a synced folder is a real setup",
    ),
    Mutation(
        name="verify-reads-the-return-code",
        file="engine/provision.py",
        search="    if verdict is probe_mod.Verdict.pass_:\n        return True, evidence, []",
        replace="    if verdict is not None:\n        return True, evidence, []",
        test="tests.test_provision.VerifyReadsTheAnswerNotTheReturnCode"
             ".test_a_probe_that_exits_zero_while_saying_it_is_down_is_not_verified",
        scar="a probe can exit 0 while saying the run is not up, and provision "
             "then reports a stopped run as verified",
    ),
    Mutation(
        name="retire-writes-back-without-proof",
        file="engine/provision.py",
        search="        if verdict is probe_mod.Verdict.pass_:\n"
               "            raise errors.Refused(\n"
               '                code="still-running", workload=w.id, unit=artifact.unit_ref,',
        replace="        if False:\n"
                "            raise errors.Refused(\n"
                '                code="still-running", workload=w.id, unit=artifact.unit_ref,',
        test="tests.test_provision.RetireProvesTheStop"
             ".test_a_service_that_still_answers_blocks_the_retirement",
        scar="the repository records retired while the machine carries on serving",
    ),
    Mutation(
        name="never-auto-enable-turned-off",
        file="engine/provision.py",
        search="    if obs.persistently_disabled is True and not enable:",
        replace="    if False and not enable:",
        test="tests.test_provision.ThePersistentOffList"
             ".test_from_the_machine_answer_all_the_way_to_the_refusal",
        scar="a unit somebody switched off deliberately is switched back on; for "
             "one real declaration that would be a security incident",
    ),
    Mutation(
        name="the-off-list-is-never-read",
        file="engine/provision.py",
        search="    steps = tuple(getattr(backend, \"disabled_list_steps\", lambda a, h: ())(artifact, host))",
        replace="    steps = ()",
        test="tests.test_provision.ThePersistentOffList"
             ".test_the_off_list_is_actually_read_from_the_machine",
        scar="the refusal above exists but can never fire, because nothing ever "
             "asks the machine which units are switched off",
    ),
    Mutation(
        name="the-two-digests-are-compared-again",
        file="engine/reconcile.py",
        search='    if looked and _text(unit.marker_digest) != _text(getattr(stamp, "declaration_digest", None)):',
        replace='    if looked and _text(unit.marker_digest) != _text(getattr(stamp, "artifact_digest", None)):',
        test="tests.test_reconcile.TheTwoCurrenciesAreNeverCompared"
             ".test_a_freshly_provisioned_run_reads_as_in_sync",
        scar="every correctly provisioned run reports drift forever, and the "
             "repair hint reproduces the same state",
    ),
    Mutation(
        name="the-lock-decides-from-a-file",
        file="engine/lock.py",
        search="            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)",
        replace="            pass",
        test="tests.test_provision.TheLockIsExclusive.test_only_one_of_many_racers_holds_it",
        scar="a read followed by a write is two steps, and eight processes at a "
             "barrier all passed the read",
    ),
    # ── the audit of 2026-08-22: six gates that looked like gates ───────────
    Mutation(
        name="an-absent-validator-reads-as-a-pass",
        file="engine/model.py",
        search='        return SchemaVerdict(verdict="schema_validator_absent",\n'
               '                             detail="check-jsonschema is not on PATH")',
        replace='        return SchemaVerdict(verdict="valid",\n'
                '                             detail="check-jsonschema is not on PATH")',
        test="tests.test_model.TheSecondGate"
             ".test_absent_validator_is_reported_never_skipped",
        scar="the second gate reports green for a run that never happened, which "
             "is the one answer a second gate may never give",
    ),
    Mutation(
        name="the-validator-is-run-without-the-file",
        file="engine/model.py",
        search='    argv = (tool, "--schemafile", str(schema), str(path))',
        replace='    argv = (tool, "--schemafile", str(schema))',
        test="tests.test_acceptance.CoreHygiene"
             ".test_every_fixture_is_handed_to_the_validator_and_its_answer_decides",
        scar="the tool is asked about nothing, so it has nothing to object to, and "
             "its silence reads through as a validated corpus",
    ),
    Mutation(
        name="retire-stops-the-unit-before-it-takes-the-lock",
        file="engine/provision.py",
        search="    guard = lock_mod.workload_lock(Path(root), w.id) if root is not None else nullcontext()\n"
               "    with guard:\n"
               '        for step in _steps_of(artifact, "disable_steps", host, lenient=False, reason=reason):\n'
               "            runner(step, host, timeout_sec=timeout_sec)",
        replace='    for step in _steps_of(artifact, "disable_steps", host, lenient=False, reason=reason):\n'
                "        runner(step, host, timeout_sec=timeout_sec)\n"
                "    guard = lock_mod.workload_lock(Path(root), w.id) if root is not None else nullcontext()\n"
                "    with guard:\n"
                "        if True:\n"
                "            pass",
        scar="two sessions each stop the same live service, so a bootout plus a "
             "persistent disable lands twice on a unit one of them still owns, and "
             "both still report a clean refusal",
        test="tests.test_provision.TheLockIsExclusive.test_retire_holds_the_lock_too",
    ),
    Mutation(
        name="adopt-writes-the-record-before-it-takes-the-lock",
        file="engine/provision.py",
        search="    guard = lock_mod.workload_lock(Path(root), w.id) if root is not None else nullcontext()\n"
               "    with guard:\n"
               "        live_digest = (digest_of(list(obs.live_files))\n"
               "                       if len(obs.live_files) == len(artifact.files) and obs.live_files\n"
               "                       else artifact.digest)\n"
               "        stamp_mod.write_stamp(\n"
               "            _stamp_for(w, host, artifact, adopted=True, artifact_digest=live_digest, root=root),\n"
               "            host, ctx, timeout_sec=timeout_sec, runner=runner)",
        replace="    live_digest = (digest_of(list(obs.live_files))\n"
                "                   if len(obs.live_files) == len(artifact.files) and obs.live_files\n"
                "                   else artifact.digest)\n"
                "    stamp_mod.write_stamp(\n"
                "        _stamp_for(w, host, artifact, adopted=True, artifact_digest=live_digest, root=root),\n"
                "        host, ctx, timeout_sec=timeout_sec, runner=runner)\n"
                "    guard = lock_mod.workload_lock(Path(root), w.id) if root is not None else nullcontext()\n"
                "    with guard:\n"
                "        pass",
        scar="two sessions write one ownership record for the same id, which is the "
             "collision the lock exists for and the one thing adopt changes at all",
        test="tests.test_provision.TheLockIsExclusive.test_adopt_holds_the_lock_too",
    ),
    Mutation(
        name="the-machine-guard-denies-nothing",
        file="tests/conftest.py",
        search='_DENY = {"ssh", "scp", "sftp", "launchctl", "systemctl", "systemd-run", "crontab", "sudo"}',
        replace='_DENY = set()',
        test="tests.test_acceptance.TheGuardItself"
             ".test_an_argv_assembled_at_runtime_is_refused_too",
        scar="the one thing keeping this suite off live boxes stops refusing, and "
             "in a green run nothing else would ever notice: an instrumented pass "
             "made three guard decisions and refused none of them",
    ),
    Mutation(
        name="a-clean-report-drops-what-it-covered",
        file="engine/report.py",
        search="    if not rep.findings:\n        return _with_header(rep, CLEAN_LINE)",
        replace="    if not rep.findings:\n        return CLEAN_LINE",
        test="tests.test_model.Reporting.test_a_clean_report_still_says_what_it_covered",
        scar="validate reports the clean line over ZERO declarations and exits 0, so "
             "an empty folder reads exactly like seventy four healthy units",
    ),
    Mutation(
        name="a-call-may-go-out-without-a-deadline",
        file="engine/exec.py",
        search="    deadline = _deadline_or_refuse(argv, timeout_sec)",
        replace="    deadline = timeout_sec",
        test="tests.test_exec.EveryCallCarriesADeadline"
             ".test_a_call_without_a_deadline_is_refused_before_anything_starts",
        scar="proc.wait(timeout=None) waits forever, so the missing deadline does not "
             "fail, it hangs, and the Completed it finally returns looks like a run",
    ),
    Mutation(
        name="the-run-relies-on-the-shell-for-its-group",
        file="engine/backends/wrapper.py",
        search='            add("if command -v setsid >/dev/null 2>&1; then")',
        replace='            add("if false; then")',
        test="tests.test_backends.TheGuardScript"
             ".test_the_run_is_put_into_its_own_session_deterministically",
        scar="dash refuses job control without a terminal, which is exactly how "
             "cron starts things, and cron is the backend that is always wrapped",
    ),
    # ── the audit of 2026-08-22, round three ───────────────────────────────
    #
    # Three real defects in behaviour (D1 to D3) and eight cases whose NAME
    # promised a property their BODY did not measure. Every entry below is the
    # softening that was demonstrated against the old code, put back verbatim,
    # so the repair is only accepted once the mutation that proved the gap turns
    # the repaired test red.
    Mutation(
        name="a-reconcile-over-nothing-reads-as-a-clean-fleet",
        file="engine/reconcile.py",
        # Anchored where the sentence is MADE, not where it is handed on. The
        # call site has now taken this needle's anchor with it three times, for
        # three unrelated reasons; the call site is plumbing and moves, while
        # the sentence is the claim and stays.
        search='        return ("0 declarations reconciled: nothing matched, so this says nothing "',
        replace='        return ("" or "',
        test="tests.test_reconcile.AReconcileReportSaysWhatItCovered"
             ".test_a_name_that_matches_nothing_never_reads_like_a_healthy_fleet",
        scar="`workload reconcile no-such-workload` answers `clean: nothing found "
             "that needs a hand` and exit 0 over a tree with seven live "
             "declarations in it, so a typo reads exactly like a healthy fleet",
    ),
    Mutation(
        name="an-all-skipped-run-is-scored-green",
        file="scripts/tests/tally.awk",
        search=TALLY_AS_IT_IS,
        replace=TALLY_AS_IT_WAS,
        test="tests.test_runner.TheTally"
             ".test_a_run_in_which_everything_was_skipped_is_never_green",
        scar="`./run-tests.sh scaffold` in a detached copy printed `0/2 green` and "
             "exited 0 with nothing having run. A detached copy is where THIS "
             "battery works, so a needle whose test can only skip there would have "
             "been scored red without one assertion executing",
    ),
    Mutation(
        name="an-endless-deadline-is-accepted-as-one",
        file="engine/exec.py",
        search="    if not math.isfinite(seconds) or seconds <= 0:",
        replace="    if seconds <= 0:",
        test="tests.test_exec.EveryCallCarriesADeadline"
             ".test_a_deadline_that_can_never_expire_is_refused_too",
        scar="inf is larger than everything and nan compares False against "
             "everything, so both walk past a `<= 0` test and reach proc.wait as a "
             "deadline that can never fire: the call does not fail, it waits",
    ),
    Mutation(
        name="an-inert-backend-installs-a-real-unit",
        file="engine/backends/inert.py",
        search="    def install_steps(self, a, h) -> tuple:\n        return ()",
        replace='    def install_steps(self, a, h) -> tuple:\n'
                '        return (Step(argv=("launchctl", "bootstrap", "gui/501",\n'
                '                           "/tmp/inert.plist"),\n'
                '                     purpose="install a unit this backend may never create"),)',
        test="tests.test_backends.Inert.test_they_install_nothing",
        scar="a runtime that exists precisely because nothing may be created from "
             "it creates a launchd unit, and the case named after that passed",
    ),
    Mutation(
        name="list-probes-the-machine",
        file="engine/cli.py",
        search='def cmd_list(args) -> int:\n'
               '    """Declarations only. This command never asks a machine anything."""\n'
               "    root, cfg = _bridge(args)",
        replace='def cmd_list(args) -> int:\n'
                '    """Declarations only. This command never asks a machine anything."""\n'
                "    root, cfg = _bridge(args)\n"
                '    _module("exec").run_argv(("/bin/echo", "probing"), timeout_sec=5)',
        test="tests.test_acceptance.TheCommandLine"
             ".test_list_reads_declarations_and_probes_nothing",
        scar="the one read-only command in the skill reaches outwards on every "
             "invocation, and an exit code of 0 says nothing about that",
    ),
    Mutation(
        name="the-enable-flag-is-parsed-and-dropped",
        file="engine/cli.py",
        search="                          enable=args.enable, host=host)",
        replace="                          enable=False, host=host)",
        test="tests.test_provision.ThePersistentOffList"
             ".test_the_enable_flag_is_wired_all_the_way_through_the_command_line",
        scar="the original defect, put back: --enable is parsed and then dropped, "
             "so a refusal a human deliberately lifted still fires and the unit "
             "they meant to bring back stays off",
    ),
    Mutation(
        name="plan-reaches-for-a-machine",
        file="engine/provision.py",
        search="def plan(w, artifact, obs: Observation, *, force=False, accept_degraded=False,\n"
               "         enable=False, host=None) -> Plan:\n"
               '    """Decide, without touching anything, what provisioning this would mean."""\n'
               "    warnings = []",
        replace="def plan(w, artifact, obs: Observation, *, force=False, accept_degraded=False,\n"
                "         enable=False, host=None) -> Plan:\n"
                '    """Decide, without touching anything, what provisioning this would mean."""\n'
                "    import pathlib as _pathlib\n"
                "    import subprocess as _subprocess\n"
                '    _subprocess.run(["/bin/echo", "planning"], capture_output=True)\n'
                '    _pathlib.Path(__file__).with_name("plan.marker").write_text("x", encoding="utf-8")\n'
                "    warnings = []",
        test="tests.test_provision.ThePlanDecisionTable.test_plan_needs_no_machine_at_all",
        scar="the pure decision function starts a process and writes a file, which "
             "is what makes the whole decision table unprovable without a box",
    ),
    Mutation(
        name="preflight-shells-out-through-the-wrapper",
        file="engine/backends/wrapper.py",
        search='    if not getattr(backend, "wrappable", True):\n        return frozenset()',
        replace="    import pathlib as _pathlib\n"
                "    import subprocess as _subprocess\n"
                '    _subprocess.run(["/bin/echo", "supplying"], capture_output=True)\n'
                '    _pathlib.Path(__file__).with_name("supplies.marker").write_text("x", encoding="utf-8")\n'
                '    if not getattr(backend, "wrappable", True):\n        return frozenset()',
        test="tests.test_render.Preflight.test_preflight_touches_nothing",
        scar="preflight calls wrapper.supplies, and the case named `touches "
             "nothing` only ever grepped engine/render.py, which this file is not",
    ),
    Mutation(
        name="render-shells-out-through-the-wrapper",
        file="engine/backends/wrapper.py",
        search='    if not getattr(backend, "wrappable", True):\n        return frozenset()',
        replace="    import pathlib as _pathlib\n"
                "    import subprocess as _subprocess\n"
                '    _subprocess.run(["/bin/echo", "supplying"], capture_output=True)\n'
                '    _pathlib.Path(__file__).with_name("supplies.marker").write_text("x", encoding="utf-8")\n'
                '    if not getattr(backend, "wrappable", True):\n        return frozenset()',
        test="tests.test_render.RenderIsTableDriven.test_render_does_no_io_and_reads_no_clock",
        scar="the same one line reaches render too, through every backend it "
             "dispatches into; the word list it used to be checked against "
             "covered one file and none of them",
    ),
    Mutation(
        name="the-unmet-guarantee-is-dropped-from-the-notes",
        file="engine/render.py",
        search="    if unmet:\n"
               "        # Named, not swallowed: a guarantee nobody answers for is the thing an\n"
               "        # operator has to know about before the run matters.\n"
               '        parts.append("NOT guaranteed by anything here: " + _names(unmet))\n',
        replace="",
        test="tests.test_render.GuaranteeArithmetic"
             ".test_what_stays_unmet_is_recorded_in_the_notes",
        scar="a guarantee nothing answers for disappears from the artifact silently, "
             "and the case named after it used a fixture whose unmet set is empty",
    ),
    Mutation(
        name="the-probe-default-is-hardcoded",
        file="engine/probe.py",
        search="    if artifact is not None:\n"
               "        backend = _backend_for(w)\n"
               "        if backend is not None:\n"
               "            step = backend.default_probe(artifact, h)\n"
               "            return ProbeSpec(command=shlex.join(tuple(str(a) for a in step.argv)),\n"
               '                             expect=_alive_expect(backend, w),\n                             source="backend-default", hint=hint)',
        replace="    if artifact is not None:\n"
                '        return ProbeSpec(command="true", expect=None,\n'
                '                         source="declaration", hint=hint)',
        test="tests.test_reconcile.ProbeResolution"
             ".test_without_either_the_backend_default_is_used",
        scar="the backend is never asked what proves its own unit is up; a truthy "
             "constant satisfied the old `assertTrue(spec.command)` exactly as well",
    ),
    Mutation(
        name="a-second-provision-of-a-real-case-boots-it-again",
        file="engine/provision.py",
        search='        return Plan("noop", "already-in-sync", (), tuple(warnings))',
        replace='        return Plan("create", "already-in-sync", (), tuple(warnings))',
        test="tests.test_acceptance.TheSevenRealCases"
             ".test_provision_then_provision_again_is_a_no_op",
        scar="the same softening as `reprovision-instead-of-noop`, aimed at the "
             "acceptance case that carried this name over a body asserting "
             "marker-without-stamp instead; two tests have to notice it now, and "
             "the one that reads the seven real declarations is the second",
    ),
    # ── round four: the two gates of `validate`, and the report under them ──
    #
    # `cmd_validate` printed the report and ran the second gate AFTERWARDS,
    # throwing its verdicts away as prose. One root, four consequences, and the
    # first four needles below are each of them put back. The last three sit on
    # `report.py`: a Report that accepts a plain sentence fell over inside
    # `by_severity` instead of rendering, which is how `provision --yes`
    # answered a traceback where the contract promises a report.
    Mutation(
        name="second-gate-prints-its-verdicts-and-throws-them-away",
        file="engine/cli.py",
        search="    if args.strict:\n"
               "        findings.extend(_second_gate(root, cfg, chosen))\n"
               "    rep = report.Report(findings=findings, "
               "header=_validate_header(len(chosen), args.strict))\n"
               "    print(report.render_table(rep))\n"
               "    return rep.exit_code",
        replace="    rep = report.Report(findings=findings, "
                "header=_validate_header(len(chosen), args.strict))\n"
                "    print(report.render_table(rep))\n"
                "    if args.strict:\n"
                "        _second_gate(root, cfg, chosen)\n"
                "    return rep.exit_code",
        test="tests.test_cli.TheSecondGateDecidesTheExitCode"
             ".test_the_clean_line_never_stands_over_a_refusal",
        scar="the original defect, put back: the second gate runs AFTER the report "
             "has been printed, so `clean: nothing found that needs a hand` stands "
             "two rows above the refusal a human is meant to act on",
    ),
    Mutation(
        name="the-second-gate-verdict-never-reaches-the-exit-code",
        file="engine/cli.py",
        search="        findings.extend(_second_gate(root, cfg, chosen))",
        replace="        _second_gate(root, cfg, chosen)",
        test="tests.test_cli.TheSecondGateDecidesTheExitCode"
             ".test_a_declaration_the_schema_refuses_never_exits_zero",
        scar="a declaration the schema validator REFUSED exits 0, so `validate "
             "--strict` in a pipeline passes a file no gate accepted",
    ),
    Mutation(
        name="an-absent-schema-validator-is-quiet",
        file="engine/report.py",
        search='        Severity.medium, WorkloadState.unknown, '
               '"the schema gate did not run",',
        replace='        Severity.info, WorkloadState.unknown, '
                '"the schema gate did not run",',
        test="tests.test_cli.TheSecondGateDecidesTheExitCode"
             ".test_an_absent_validator_is_a_finding_and_not_silence",
        scar="on a machine without check-jsonschema -- the normal case on a fresh "
             "clone -- `--strict` becomes a switch with no effect: the absence is "
             "printed and the run still exits 0, which is a check nobody ran "
             "scored as a green check",
    ),
    Mutation(
        name="an-unrecognised-verdict-falls-through-to-silence",
        file="engine/report.py",
        search='UNKNOWN_VERDICT = (Severity.high, WorkloadState.unknown, '
               '"the schema gate answered",',
        replace='UNKNOWN_VERDICT = (Severity.info, WorkloadState.unknown, '
                '"the schema gate answered",',
        test="tests.test_report.TheSchemaVerdictBecomesAFinding"
             ".test_an_answer_this_skill_does_not_know_is_not_a_pass",
        scar="a verdict name the skill has never seen -- a new answer from a newer "
             "check-jsonschema -- is scored as a pass, and the gate goes quiet "
             "exactly when the tool started saying something new",
    ),
    Mutation(
        name="a-report-accepts-anything-and-falls-over-later",
        file="engine/report.py",
        search="        self.findings = notes(self.findings)",
        replace="        self.findings = list(self.findings)",
        test="tests.test_report.APlainSentenceIsNotAFinding"
             ".test_a_sentence_in_a_report_renders_instead_of_raising",
        scar="a Report carrying a plain sentence raises AttributeError inside "
             "by_severity instead of rendering, which is how `provision --yes` "
             "answered a traceback where the contract promises a report",
    ),
    Mutation(
        name="the-report-that-provision-prints-is-never-reached",
        file="engine/report.py",
        search="    return [m if isinstance(m, Finding) else\n"
               "            Finding(workload_id=workload_id, "
               "state=WorkloadState.observed,\n"
               "                    severity=Severity.info, detail=str(m))\n"
               "            for m in messages]",
        replace="    return list(messages)",
        test="tests.test_cli.ProvisionAnswersWithAReport"
             ".test_a_verify_that_does_not_confirm_reports_instead_of_raising",
        scar="a run that went through and was NOT confirmed at the live object "
             "answers a traceback instead of the report that says so",
    ),
    Mutation(
        name="provision-reports-without-saying-which-workload",
        file="engine/cli.py",
        # The `print(` line comes along because the same call now stands twice
        # in cli.py: `retire` and `adopt` answer with a report too, and an anchor
        # that matches both applies to neither.
        search="        print(report.render_table(report.Report(\n"
               "            findings=report.notes(outcome.findings, workload_id=workload.id),",
        replace="    print(report.render_table(report.Report(\n"
                "        findings=list(outcome.findings),",
        test="tests.test_cli.ProvisionAnswersWithAReport"
             ".test_the_report_names_the_workload_it_is_about",
        scar="the notes from a provisioning run name no workload, so on a host "
             "carrying a dozen units the sentence is unattributable",
    ),
    # ── round four: the bolt in front of the only destructive command ──────
    #
    # `retire --yes --dry-run` really stopped a live unit: `cmd_retire` declared
    # --dry-run, then computed `dry_run=not args.yes` and never read it. The
    # bolt is two signals now, and NEITHER is the other's negation, so the three
    # needles below can each take away one half at a time. The two after them
    # put back the layer that acts running without the invariant gate, and the
    # last two put back a coverage line that claimed a probe nobody ran.
    Mutation(
        name="an-unconfirmed-stop-runs-anyway",
        file="engine/provision.py",
        search="    if confirmed is not True:",
        replace="    if confirmed is False:",
        # NOT the end-to-end case: `--yes --dry-run` is refused by the dry run
        # half of the bolt, so that one stays green under this softening and was
        # scoring nothing. This case passes NOTHING for `confirmed`, which is the
        # half this needle is about.
        test="tests.test_provision.TheStopIsNeverAnAccident"
             ".test_a_retirement_nobody_confirmed_is_refused_and_touches_nothing",
        scar="not being told yes reads as a yes, which is exactly what "
             "`retire --yes --dry-run` handed down and how a live unit got booted out",
    ),
    Mutation(
        name="the-dry-run-half-of-the-bolt-is-dropped",
        file="engine/provision.py",
        search='    if dry_run:\n        return False, "dry run, nothing was stopped"\n',
        replace="",
        test="tests.test_provision.TheStopIsNeverAnAccident"
             ".test_an_explicit_dry_run_stops_nothing_even_when_confirmed",
        scar="a run that asked for a preview stops the service anyway",
    ),
    Mutation(
        name="the-unconfirmed-refusal-is-handed-back-instead-of-raised",
        file="engine/provision.py",
        search='        raise errors.Refused(\n            code="unconfirmed-stop",',
        replace='        return Outcome("retire", False, "", (why,))\n'
                '        raise errors.Refused(\n            code="unconfirmed-stop",',
        test="tests.test_provision.TheStopIsNeverAnAccident"
             ".test_the_refusal_is_raised_and_not_returned",
        scar="the caller prints two fields of the Outcome, so the refusal is "
             "invisible and reads as a retirement that happened",
    ),
    Mutation(
        name="provision-skips-the-invariant-gate",
        file="engine/provision.py",
        search="    invalid = model.validate(w.raw or {}, source=str(w.source_path or w.id))",
        replace="    invalid = []",
        test="tests.test_provision.TheInvariantGateGuardsTheLayerThatActs"
             ".test_an_invalid_declaration_never_becomes_a_plan",
        scar="a declaration without execution.timeout_sec becomes a run with no "
             "deadline on a machine, and nothing downstream can see it",
    ),
    Mutation(
        name="the-gate-refuses-without-naming-the-key",
        file="engine/provision.py",
        search='                    tuple(f"{w.id} does not pass the invariant gate: {f.detail}"\n'
               "                          for f in invalid))",
        replace='                    (f"{w.id} does not pass the invariant gate",))',
        test="tests.test_provision.TheInvariantGateGuardsTheLayerThatActs"
             ".test_the_refusal_names_the_key_that_is_wrong",
        scar="the refusal sends a human hunting through the declaration instead "
             "of naming the key that is wrong",
    ),
    Mutation(
        name="the-coverage-word-comes-from-the-flag",
        file="engine/reconcile.py",
        # Re-anchored 2026-08-23: the sentence it pointed at was rewritten when
        # `probed` was split into inspection and health verdict, and the runner
        # caught the dangling anchor -- a needle that matches nothing proves
        # nothing, and reports green while doing it.
        search='    if probed == 0:\n'
               '        return (f"{head}, 0 of {total} health-probed: the machine WAS inspected "\n'
               '                f"(units, ownership stamps, traces), no health verdict was taken")\n'
               '    return f"{head}, {probed} of {total} health-probed"',
        replace='    return f"{head}, probed"',
        test="tests.test_reconcile.TheCoverageLineCountsProbesThatRan"
             ".test_a_run_in_which_no_probe_ran_never_claims_it_probed",
        scar="three declarations nobody asked anything report the same coverage "
             "as three that were really probed",
    ),
    Mutation(
        name="a-probe-that-never-ran-counts-as-coverage",
        file="engine/reconcile.py",
        search="        if done is not None:",
        replace="        if True:",
        test="tests.test_reconcile.TheCoverageLineCountsProbesThatRan"
             ".test_a_probe_refused_before_it_ran_is_not_coverage",
        scar="a placeholder probe that was refused before execution is counted "
             "as a machine that answered",
    ),
    # ── round four: what a declared value does to the file it is written into ──
    #
    # A unit file is line based and systemd splits `Environment=` on whitespace,
    # so a value is not a value once it reaches one: it is more of the file. The
    # first five needles put back the four ways a declaration could write past
    # its own field, the last four the gate that refuses those values before any
    # backend renders them.
    Mutation(
        name="the-whole-environment-on-one-line",
        file="engine/backends/systemd.py",
        search='    lines = [_quote_environment(w, name, value) for name, value in marker.items()]\n'
               '    for name in sorted(declared):\n'
               '        if name in _MARKER_NAMES:\n'
               '            continue\n'
               '        lines.append(_quote_environment(w, name, declared[name]))\n'
               '    return lines',
        replace='    joined = " ".join(f"{k}={v}" for k, v in marker.items())\n'
                '    for name in sorted(declared):\n'
                '        joined += f" {name}={declared[name]}"\n'
                '    return [f"Environment={joined}"]',
        test="tests.test_backends.EnvironmentSurvivesTheUnitFile"
             ".test_a_value_with_a_space_arrives_whole",
        scar="systemd splits Environment= on whitespace, so one shared line turns "
             "GREETING=hallo welt into GREETING=hallo plus a token it drops; the "
             "service then starts with half its configuration and says nothing",
    ),
    Mutation(
        name="an-environment-value-is-written-unquoted",
        file="engine/backends/systemd.py",
        search='    escaped = text.replace("\\\\", "\\\\\\\\").replace(\'"\', \'\\\\"\')\n'
               "    return f'Environment=\"{name}={escaped}\"'",
        replace="    return f'Environment=\"{name}={text}\"'",
        test="tests.test_backends.EnvironmentSurvivesTheUnitFile"
             ".test_every_hostile_value_arrives_whole",
        scar="a quote inside the value ends the quoting early, and everything "
             "after it is read as further assignments",
    ),
    Mutation(
        name="a-declaration-may-rename-its-own-owner-under-systemd",
        file="engine/backends/systemd.py",
        search="        if name in _MARKER_NAMES:\n            continue\n",
        replace="",
        test="tests.test_backends.EnvironmentSurvivesTheUnitFile"
             ".test_a_declaration_cannot_rename_the_owner_of_its_own_unit",
        scar="ownership is read back out of those two variables, so a declaration "
             "that sets one is not configuring a run, it is claiming a unit",
    ),
    Mutation(
        name="a-declaration-may-rename-its-own-owner-under-launchd",
        file="engine/backends/launchd.py",
        search="\"EnvironmentVariables\": _environment(w) | base.marker_env(w, digest),",
        replace="\"EnvironmentVariables\": base.marker_env(w, digest) | _environment(w),",
        test="tests.test_backends.TheLaunchdPlistCarriesValuesUnchanged"
             ".test_a_declaration_cannot_rename_the_owner_of_its_own_unit",
        scar="the same claim in the other backend's idiom: a dict union whose "
             "right side wins, with the declaration on the right",
    ),
    Mutation(
        name="an-argument-may-end-the-exec-line",
        file="engine/backends/launchd.py",
        search="            for index, argument in enumerate(command):\n"
               "                ensure_unit_safe(argument, key_path=f\"execution.command[{index}]\",\n"
               "                                 workload_id=w.id)\n",
        replace="",
        test="tests.test_backends.TheLaunchdPlistCarriesValuesUnchanged"
             ".test_a_line_break_in_an_argument_is_refused_here_too",
        scar="a plist holds an argument with a newline in it and a systemd "
             "ExecStart= does not, so the same declaration runs two different "
             "commands depending on which machine it landed on",
    ),
    Mutation(
        name="an-id-that-is-a-path-still-becomes-a-path",
        file="engine/model.py",
        search="    if not ID_PATTERN.match(str(w.id)):",
        replace="    if False:",
        test="tests.test_backends.EnvironmentSurvivesTheUnitFile"
             ".test_an_id_carrying_a_path_never_becomes_a_file_path",
        scar="the id is not written into the unit, it decides WHICH FILE the unit "
             "is; a slash writes the bytes into a directory nobody declared",
    ),
    Mutation(
        name="a-value-may-end-the-line-it-is-written-into",
        file="engine/model.py",
        search='    text = str(value)\n'
               '    for char, name in FORBIDDEN_IN_VALUES:\n'
               '        if char in text:\n'
               '            return f"carries {name}, which ends the directive it is written into"\n'
               '    return ""',
        replace='    return ""',
        test="tests.test_model.ValuesThatWouldBreakTheFileTheyAreWrittenInto"
             ".test_a_line_break_is_refused_in_every_field_that_reaches_a_file",
        scar="a unit file is line based, so a value carrying a newline does not "
             "arrive escaped in the next line, it arrives as the next directive",
    ),
    Mutation(
        name="the-id-is-taken-as-a-name-and-not-as-a-slug",
        file="engine/model.py",
        search="    elif not ID_PATTERN.match(str(raw.get(\"id\"))):",
        replace="    elif False:",
        test="tests.test_model.ValuesThatWouldBreakTheFileTheyAreWrittenInto"
             ".test_an_id_with_a_space_is_refused",
        scar="the id is written unquoted into a unit file name, a launchd label, "
             "a systemd Unit= reference and a path inside the guard script; a "
             "space splits the reference and a slash writes the file elsewhere",
    ),
    Mutation(
        name="an-environment-name-is-taken-as-given",
        file="engine/model.py",
        search="        if not ENV_NAME_PATTERN.match(str(name)):",
        replace="        if False:",
        test="tests.test_model.ValuesThatWouldBreakTheFileTheyAreWrittenInto"
             ".test_an_environment_name_that_is_a_command_is_refused",
        scar="the name is written bare on the left of Environment=NAME= and bare "
             "on the left of a shell assignment in the guard script, where "
             "anything that is not a name is simply the next command",
    ),
    # ── round four, the seam: the bolt lives in `provision`, the argv arrives
    # in `cli`. It can be defeated from either side, and in two OPPOSITE
    # directions, which is why the middle needle below is the Gegenprobe: the
    # command permanently refusing looks exactly like a command that is safe.
    Mutation(
        name="the-dry-run-flag-is-derived-from-yes-again",
        file="engine/cli.py",
        search="                               dry_run=args.dry_run, confirmed=args.yes,",
        replace="                               dry_run=not args.yes, confirmed=args.yes,",
        test="tests.test_cli.RetireIsWiredToBothHalvesOfTheBolt"
             ".test_yes_together_with_dry_run_stops_nothing",
        scar="the original defect at its own layer: --dry-run is parsed, then "
             "recomputed out of --yes, and `retire --yes --dry-run` boots out a "
             "live unit, disables it persistently and writes the declaration back",
    ),
    Mutation(
        name="the-confirmation-never-reaches-the-bolt",
        file="engine/cli.py",
        search="                               dry_run=args.dry_run, confirmed=args.yes,\n",
        replace="                               dry_run=args.dry_run,\n",
        test="tests.test_cli.RetireIsWiredToBothHalvesOfTheBolt"
             ".test_a_plain_yes_really_stops_the_unit",
        scar="the other direction, and the one no no-case can see: `confirmed` "
             "defaults to None, so retire refuses EVERY argv forever and stops "
             "being a command, while every test that asserts nothing was touched "
             "still passes",
    ),
    Mutation(
        name="retire-runs-outside-the-repository-it-was-given",
        file="engine/cli.py",
        # Retargeted 2026-08-27: the call gained `write_declaration=False` when
        # retire stopped writing the declaration once per unit, so the old
        # literal named nothing and this needle read green while proving
        # nothing.
        search="                                   timeout_sec=args.timeout, root=root,\n"
               "                                   write_declaration=False)",
        replace="                                   timeout_sec=args.timeout,\n"
               "                                   write_declaration=False)",
        test="tests.test_cli.RetireIsWiredToBothHalvesOfTheBolt"
             ".test_the_run_was_held_under_the_workload_lock_of_that_repository",
        scar="without a root the run takes nullcontext() instead of the workload "
             "lock, so two sessions retire the same id at once, and the write "
             "falls back to w.source_path instead of the repository named on the "
             "command line",
    ),
    # ── round four, the other seam: the hand written gate against the
    # declaration schema. Five rules stood in the schema alone, so `validate`
    # answered clean where `validate --strict` refused -- and `provision.plan`
    # asks the quiet one. Each needle takes one of the five back out.
    Mutation(
        name="argv-zero-may-be-relative-again",
        file="engine/model.py",
        search="        if not ABSOLUTE_PATH_PATTERN.match(str(command[0])):",
        replace="        if False:",
        test="tests.test_model.TheHandWrittenGateHoldsWhatTheSchemaHolds"
             ".test_a_relative_argv_zero_is_refused",
        scar="a service manager starts the unit with a short PATH and no login "
             "shell, so `claude` is not the claude a terminal finds; the schema "
             "refuses it and the gate provision asks did not",
    ),
    Mutation(
        name="the-coverage-line-may-call-an-inspected-machine-unread",
        file="engine/reconcile.py",
        search='f"{head}, 0 of {total} health-probed: the machine WAS inspected "',
        replace='f"{head}, 0 of {total} probed: nothing here was asked of a live source "',
        test="tests.test_reconcile.TheCoverageLineCountsProbesThatRan"
             ".test_zero_probes_does_not_claim_the_machine_went_unread",
        scar="the units were listed, the ownership stamps were read and the "
             "traces were read, which is where every finding on such a run "
             "comes from. Calling that `nothing was asked of a live source` is "
             "an overclaim in the pessimistic direction, and rendered onto a "
             "page it becomes a banner telling the reader to distrust findings "
             "that came straight off the machine",
    ),
    Mutation(
        name="the-page-may-render-a-declaration-as-markup",
        file="engine/view.py",
        search="    return html_mod.escape(\"\" if value is None else str(value), quote=True)",
        replace='    return "" if value is None else str(value)',
        test="tests.test_view.DataIsNeverMarkup"
             ".test_a_purpose_that_looks_like_markup_arrives_as_text",
        scar="a declaration is a file a human writes and a finding quotes a "
             "machine, so both are untrusted text; unescaped, anything either "
             "of them says runs in the reader's browser",
    ),
    Mutation(
        name="the-page-may-drop-a-declaration-nobody-reported-on",
        file="engine/view.py",
        search='        verdicts = f\'<span class="unreported">{UNREPORTED}</span>\'',
        replace='        verdicts = f\'<span class="unreported"></span>\'',
        test="tests.test_view.EveryDeclarationAppearsWithItsState"
             ".test_a_declaration_with_no_finding_is_still_listed",
        scar="a workload nobody said anything about is not healthy, it is "
             "unreported, and a blank cell reads as the first one",
    ),
    Mutation(
        name="the-guard-path-may-miss-the-package-manager-again",
        file="engine/backends/wrapper.py",
        search='GUARD_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"',
        replace='GUARD_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"',
        test="tests.test_render.TheGuardPathReachesTheToolsThatAreActuallyInstalled"
             ".test_the_package_manager_prefixes_come_first",
        scar="under the base-system PATH alone `gh` does not resolve at all on a "
             "real machine and `python3` resolves to the system one, which "
             "carries no third party module. A job migrated onto this guard "
             "would swap a working report for an empty one: exit code zero, no "
             "error, and the only symptom a shorter email",
    ),
    Mutation(
        name="a-retired-run-may-be-called-late-again",
        file="engine/reconcile.py",
        search="            if w.is_retired:\n                continue",
        replace="            if False:\n                continue",
        test="tests.test_reconcile.ARetiredRunIsNotLate"
             ".test_a_retired_run_is_never_overdue",
        scar="the report said `retired and gone from the machine` and `high "
             "overdue` about the same id three lines apart: the two loudest "
             "findings this skill has, about something doing exactly what it "
             "was told",
    ),
    Mutation(
        name="the-loud-side-may-be-derived-from-the-quiet-one",
        file="engine/reconcile.py",
        search="TRACE_SPEAKS_IN = frozenset({",
        replace="TRACE_SPEAKS_IN = frozenset(set(model.WorkloadState)) - frozenset({",
        test="tests.test_reconcile.EveryStateDecidesWhetherTheTraceSpeaks"
             ".test_the_two_sides_are_spelled_out_and_not_derived",
        scar="a derived side holds the same members as a written one TODAY, so "
             "no assertion over the values can tell them apart -- and a derived "
             "one grows silently with the enum, which is the whole defect the "
             "table was written to end",
    ),
    Mutation(
        name="a-verified-replace-may-keep-its-rollback-copy",
        file="engine/provision.py",
        search="                _drop_previous(artifact, host, runner=runner, timeout_sec=timeout_sec)",
        replace="                pass",
        test="tests.test_provision.WhatIsLeftOnTheMachine"
             ".test_the_whole_cycle_leaves_nothing_behind",
        scar="the copy exists for exactly one decision and was kept past it, so "
             "every replace left a full copy of the previous unit file behind. "
             "This needle names the END STATE case on purpose: a step list "
             "cannot see a file nobody removed, which is why the defect "
             "survived five hundred and fifty seven green cases",
    ),
    Mutation(
        name="the-rollback-copy-may-outlive-its-job-again",
        file="engine/provision.py",
        search="            _drop_previous(artifact, host, runner=runner, timeout_sec=timeout_sec)\n            findings.append(\"the artifact files and their rollback copies were \"",
        replace="            findings.append(\"the artifact files and their rollback copies were \"",
        test="tests.test_provision.TheRollbackCopyIsNotLitter"
             ".test_retire_removes_the_copy_as_well_as_the_file",
        scar="a retired workload left a complete copy of its own unit file on "
             "the machine: unstamped, unlisted, claimed by nobody, and carrying "
             "whatever the old argv and environment carried",
    ),
    Mutation(
        name="the-remote-payload-is-wrapped-twice-again",
        file="engine/exec.py",
        search='out += [str(target), "--", "/bin/sh", "-c", sh_quote(sh_join(argv))]',
        replace='out += [str(target), "--", "/bin/sh", "-c", sh_join(argv)]',
        test="tests.test_exec.SshArgv"
             ".test_the_remote_shell_receives_the_argv_it_was_given",
        scar="ssh carries no argv: it joins everything after the target with "
             "spaces and hands it to the remote LOGIN shell, which splits it "
             "again. Without the second quoting the remote `sh -c` gets three "
             "words or five, takes only the FIRST as its command string, and "
             "for a step that was already a shell invocation runs a bare "
             "/bin/sh with stdin closed: empty output, exit code zero, and the "
             "host facts arrive as three empty strings the plan is built on",
    ),
    Mutation(
        name="an-unread-host-may-be-read-as-three-empty-strings",
        file="engine/exec.py",
        search='    if not uid.isdigit() or not home.startswith("/"):',
        replace="    if False:",
        test="tests.test_exec.TheHostFactsAreReadOrTheRunStops"
             ".test_an_empty_answer_is_refused",
        scar="the padding turns a short answer into empty strings, so `gui/<uid>` "
             "becomes `gui//`, every path becomes root anchored, and provision "
             "refuses with a collision against a unit that cannot exist; the "
             "step runs with no expected return code and the real failure "
             "exited zero, so nothing marked it",
    ),
    Mutation(
        name="the-interpreter-may-carry-a-version-again",
        file="engine/model.py",
        search="        found = VERSION_SEGMENT_PATTERN.search(interpreter)",
        replace="        found = None",
        test="tests.test_model.TheProcessKeepsItsNameAcrossAnUpdate"
             ".test_a_version_directory_is_refused_and_the_segment_is_named",
        scar="a versioned path names a file that exists in order to be replaced: "
             "the upgrade that installs the successor deletes it, so the unit "
             "starts nothing, and on macOS the new path is a client nobody ever "
             "granted anything to, so a surviving file reads an empty result "
             "instead of being denied",
    ),
    Mutation(
        name="a-shared-interpreter-may-hold-a-grant-again",
        file="engine/model.py",
        search="    elif interpreter in SHARED_INTERPRETERS:",
        replace="    elif False:",
        test="tests.test_model.AGrantedClientIsNotSharedWithTheWholeMachine"
             ".test_a_shared_interpreter_is_refused_for_a_grant_holder",
        scar="a grant is issued to a PATH, so Full Disk Access on /usr/bin/python3 "
             "is Full Disk Access for every python script on the machine, "
             "including the ones somebody else gets to choose",
    ),
    Mutation(
        name="the-grant-may-follow-the-rename-after-all",
        file="engine/reconcile.py",
        search="    if not declared or declared == stamped:",
        replace="    if True:",
        test="tests.test_reconcile.TheGrantDoesNotFollowARename"
             ".test_a_moved_interpreter_is_reported_and_both_paths_are_named",
        scar="the renamed program starts, runs and exits zero on an empty result, "
             "because a client with no grant is not denied, it is shown nothing; "
             "that arrives as an empty inbox rather than an error",
    ),
    Mutation(
        name="an-unrecorded-client-path-may-pass-in-silence",
        file="engine/reconcile.py",
        search="    if stamped is None:",
        replace="    if False:",
        test="tests.test_reconcile.TheGrantDoesNotFollowARename"
             ".test_a_stamp_that_never_recorded_one_admits_it_cannot_tell",
        scar="a stamp written before the field existed holds no answer, and "
             "silence is indistinguishable from `unchanged`: the same collapse "
             "between `read and absent` and `never read` that marker_observed "
             "was added to end",
    ),
    Mutation(
        name="the-interpreter-and-the-working-directory-may-be-relative",
        file="engine/model.py",
        search="        if not ABSOLUTE_PATH_PATTERN.match(str(value)):",
        replace="        if False:",
        test="tests.test_model.TheHandWrittenGateHoldsWhatTheSchemaHolds"
             ".test_a_relative_interpreter_is_refused",
        scar="a relative interpreter is a DIFFERENT TCC client on macOS, with "
             "none of the grants the real one has, and a relative working "
             "directory is resolved against whatever directory the service "
             "manager happened to start in",
    ),
    Mutation(
        name="an-environment-value-may-be-a-value-again",
        file="engine/model.py",
        search="        elif not ENV_VALUE_PATTERN.match(str(value)):",
        replace="        elif False:",
        test="tests.test_model.TheHandWrittenGateHoldsWhatTheSchemaHolds"
             ".test_a_secret_pasted_into_the_environment_is_refused",
        scar="a declaration is a tracked file, so a secret pasted into env "
             "travels twice: verbatim into the unit on the machine and into git "
             "along with the declaration, through the scope router with it",
    ),
    Mutation(
        name="a-recipient-may-be-a-plaintext-address",
        file="engine/model.py",
        search="            if not pattern.match(str(value)):",
        replace="            if False:",
        test="tests.test_model.TheHandWrittenGateHoldsWhatTheSchemaHolds"
             ".test_a_plaintext_address_in_the_mandant_is_refused",
        scar="`a recipient is a reference, never a plaintext address` was checked "
             "over the KEY NAMES only, so a person written out in full passed and "
             "travelled into whatever tier the file reached",
    ),
    Mutation(
        name="a-schedule-may-carry-a-second-trigger",
        file="engine/model.py",
        search="            if key in allowed or schedule.get(key) in (None, \"\", [], {}):\n"
               "                continue\n",
        replace="            continue\n",
        test="tests.test_model.TheHandWrittenGateHoldsWhatTheSchemaHolds"
             ".test_a_oneshot_carrying_a_cadence_is_refused",
        scar="requiring the right key never said the wrong ones must be absent, "
             "so a oneshot carrying a cadence reads to a human as a recurring job "
             "and fires once, and nothing says which of the two the backend took",
    ),
    # ── round four, the third format: the guard script is the only generated
    # file that is RUN. `w.id` reached four of its state-file paths raw inside
    # double quotes, and every environment KEY reached two shell positions bare.
    Mutation(
        name="the-guard-script-takes-the-id-as-it-comes",
        file="engine/backends/wrapper.py",
        search="    safe_id = ensure_id_safe(w)",
        replace="    safe_id = w.id",
        test="tests.test_backends.TheGuardScriptIsTheOnePlaceAValueIsExecuted"
             ".test_the_wrapper_refuses_a_hostile_id_on_its_own",
        scar="an id carrying a double quote ends the string it is interpolated "
             "into and everything after it is the next command, in a file the "
             "service manager then runs",
    ),
    Mutation(
        name="the-guard-script-is-written-wherever-the-id-points",
        file="engine/backends/wrapper.py",
        search="    name = ensure_id_safe(w)",
        replace="    name = str(w.id)",
        test="tests.test_backends.TheGuardScriptIsTheOnePlaceAValueIsExecuted"
             ".test_the_path_the_wrapper_writes_to_is_refused_on_its_own",
        scar="the id decides WHICH FILE the guard script is, so a slash writes "
             "an executable into a directory nobody declared",
    ),
    Mutation(
        name="an-environment-key-reaches-the-shell-as-it-was-declared",
        file="engine/backends/base.py",
        search="    for name in declared:\n"
               "        ensure_env_name(name, workload_id=getattr(w, \"id\", \"\"))\n",
        replace="",
        test="tests.test_backends.TheGuardScriptIsTheOnePlaceAValueIsExecuted"
             ".test_an_environment_key_that_is_a_command_is_refused",
        scar="the key is written bare on the left of a shell assignment and bare "
             "after `export`, so a key carrying a semicolon runs its command "
             "twice, in the file the service manager starts",
    ),
    # ── round four, the integration pass: three guards that no needle reached.
    # The first two are rules INSIDE a block where a second rule fires for the
    # same declaration, so the case that named them was answered by the wrong
    # rule; the third is the battery's own verdict, which scored two needles red
    # whose named test does not exist.
    Mutation(
        name="the-gate-lets-a-declaration-claim-someone-elses-unit",
        file="engine/model.py",
        search="        elif str(name) in (MARKER_ENV_ID, MARKER_ENV_DIGEST):",
        replace="        elif False:",
        test="tests.test_model.ValuesThatWouldBreakTheFileTheyAreWrittenInto"
             ".test_declaring_the_ownership_marker_as_a_variable_is_refused",
        scar="ownership is read back off the machine out of exactly those two "
             "variables, so a declaration that sets one is not configuring a run, "
             "it is claiming a unit that belongs to another declaration",
    ),
    Mutation(
        name="a-red-from-a-test-that-never-loaded-counts-as-a-proof",
        file="scripts/tests/mutate.py",
        search='    if "unittest.loader._FailedTest" in output or '
               '"Failed to import test module" in output:',
        replace="    if False:",
        test="tests.test_runner.TheMutationVerdict"
             ".test_a_red_that_only_says_the_test_could_not_be_loaded_is_no_proof",
        scar="`python -m unittest <name>` exits 1 for a name it cannot load as "
             "well as for a test that failed, so a needle naming a method nobody "
             "wrote is scored red while never executing a line of the behaviour "
             "it claims to guard -- which is how two needles in this very file "
             "passed for a whole round",
    ),
    # ── the sixth finding of the gate round, closed in the integration pass:
    # with no `_schema.yaml` at all the gate ran the validator anyway, the tool
    # failed to build a validator, and EVERY declaration was reported refused.
    Mutation(
        name="the-gate-runs-against-a-contract-that-is-not-there",
        file="engine/model.py",
        search="    if not Path(schema).is_file():",
        replace="    if False:",
        test="tests.test_model.TheSecondGate"
             ".test_a_missing_contract_is_named_and_the_tool_is_never_run",
        scar="a repository whose declaration contract is gone reports every "
             "declaration as REFUSED, names a file inside the validator's own "
             "virtualenv as the objection, and sends a human to fix a "
             "declaration nobody read",
    ),
    Mutation(
        name="a-missing-contract-is-quiet",
        file="engine/report.py",
        search='    "schema_missing": (\n        Severity.medium, WorkloadState.unknown, '
               '"there is no schema to check against",',
        replace='    "schema_missing": (\n        Severity.info, WorkloadState.unknown, '
                '"there is no schema to check against",',
        test="tests.test_report.TheSchemaVerdictBecomesAFinding"
             ".test_every_non_valid_verdict_is_loud",
        scar="the contract is gone, the gate cannot run, and `validate --strict` "
             "still exits 0: the absence is printed and scored as a green check",
    ),
    # ── the same defect as A4, one command further along: `retire` and `adopt`
    # printed two fields of their outcome and dropped the sentences it carried.
    Mutation(
        name="retire-prints-two-fields-and-drops-its-report",
        file="engine/cli.py",
        search='    print(_outcome_report(outcome, workload, host, "retire"))',
        replace='    print(f"retire: {outcome.action}, verified={outcome.verified}")',
        test="tests.test_cli.RetireAndAdoptAnswerWithAReport"
             ".test_a_dry_run_retirement_says_why_nothing_was_stopped",
        scar="`retire --dry-run` answers `verified=False` and nothing else, a "
             "line from which refused, failed and previewed cannot be told "
             "apart, while the outcome it prints from carries the reason",
    ),
    Mutation(
        name="adopt-prints-two-fields-and-drops-its-report",
        file="engine/cli.py",
        search='    print(_outcome_report(outcome, workload, host, "adopt"))',
        replace='    print(f"adopt: {outcome.action}, verified={outcome.verified}")',
        test="tests.test_cli.RetireAndAdoptAnswerWithAReport"
             ".test_a_dry_run_adoption_says_why_nothing_was_recorded",
        scar="the same silence on the command that takes ownership of a unit "
             "somebody built by hand",
    ),
    Mutation(
        name="the-safety-word-on-the-destructive-command-is-undocumented",
        file="SKILL.md",
        search="workload retire     <id> --reason TEXT [--superseded-by ID] "
               "[--keep-artifact] [--yes] [--dry-run]",
        replace="workload retire     <id> --reason TEXT [--superseded-by ID] "
                "[--keep-artifact] [--yes]",
        test="tests.test_acceptance.CoreHygiene"
             ".test_every_flag_the_parser_takes_stands_in_the_command_block",
        scar="`--dry-run` on the one command that stops a running service was "
             "declared by the parser, thrown away one layer down and absent from "
             "the document, so the flag a careful human reaches for was neither "
             "wired nor findable",
    ),
    # ── the command line's own dispatch: `declare` could not be reached at all.
    Mutation(
        name="the-subcommand-is-read-from-the-attribute-a-flag-also-writes",
        file="engine/cli.py",
        search="    handler = COMMANDS.get(args.subcommand)",
        replace='    handler = COMMANDS.get(getattr(args, "command", args.subcommand))',
        test="tests.test_cli.DeclareIsReachableFromTheArgvAHumanTypes"
             ".test_declare_with_a_command_writes_the_declaration",
        scar="`declare --command` writes its argv list into the same attribute "
             "the subcommand uses, so the one documented way to write a new "
             "declaration ends in `TypeError: cannot use 'list' as a dict key`",
    ),
    Mutation(
        name="the-scaffold-is-built-from-another-repositorys-template",
        file="engine/cli.py",
        search="    text = model.scaffold(args.id, root=root, kind=args.kind,",
        replace="    text = model.scaffold(args.id, kind=args.kind,",
        test="tests.test_cli.DeclareIsReachableFromTheArgvAHumanTypes"
             ".test_the_template_that_is_read_is_the_one_in_the_target_repository",
        scar="`declare --root <elsewhere>` writes the file into one repository "
             "out of the template of the tree the skill happens to live in, "
             "which is the one case --root exists for",
    ),
    # ── publish: a served directory belongs to somebody, and two facts are
    # ── not one word.
    Mutation(
        name="a-destination-full-of-someone-elses-files-is-taken-anyway",
        file="engine/publish.py",
        search="    foreign = tuple(e for e in obs.entries if e != MARKER)",
        replace="    foreign = ()",
        test="tests.test_publish.ItRefusesADirectoryItDoesNotOwn"
             ".test_a_directory_full_of_someone_elses_files_is_refused",
        scar="publishing into the root of a served directory succeeds, and then "
             "either the puller that owns it deletes the page at its next sync "
             "or this page overwrites the index of the site already there",
    ),
    Mutation(
        name="the-directory-is-written-before-it-is-claimed",
        file="engine/publish.py",
        search="    runner(claim, host, timeout_sec=timeout_sec)\n"
               "    results = []\n"
               "    for item in planned:\n"
               "        for part in item.writes:\n            runner(part, host, timeout_sec=timeout_sec)\n"
               "        back = runner(item.readback, host, timeout_sec=timeout_sec)\n"
               "        results.append(_verdict(item, back, dest))",
        replace="    results = []\n"
                "    for item in planned:\n"
                "        for part in item.writes:\n            runner(part, host, timeout_sec=timeout_sec)\n"
                "        back = runner(item.readback, host, timeout_sec=timeout_sec)\n"
                "        results.append(_verdict(item, back, dest))\n"
                "    runner(claim, host, timeout_sec=timeout_sec)",
        test="tests.test_publish.ItRefusesADirectoryItDoesNotOwn"
             ".test_a_directory_that_does_not_exist_yet_is_taken_with_a_marker",
        scar="a marker write that fails after the page write leaves a page in an "
             "unclaimed directory, which every later publish refuses as a "
             "stranger's: a permanent lockout on this skill's own output",
    ),
    Mutation(
        name="delivered-is-the-write-return-code-talking-about-itself",
        file="engine/publish.py",
        search='    if (back.stdout or "") != item.content:',
        replace="    if False:",
        test="tests.test_publish.DeliveredIsNotReachable"
             ".test_bytes_that_came_back_different_are_not_delivered",
        scar="a truncated or mangled page reports as delivered, because the only "
             "thing consulted is the return code of the command that wrote it",
    ),
    Mutation(
        name="reachable-is-claimed-without-anyone-fetching-it",
        file="engine/publish.py",
        search="    if body != encoded:",
        replace="    if False:",
        test="tests.test_publish.DeliveredIsNotReachable"
             ".test_a_url_that_serves_other_bytes_is_not_reachable",
        scar="a server pointed at another root answers 200 with somebody else's "
             "page and the run reports the dashboard as reachable",
    ),
    Mutation(
        name="not-asked-is-reported-as-not-reachable",
        file="engine/publish.py",
        search="    if not url:",
        replace="    if False and not url:",
        test="tests.test_publish.DeliveredIsNotReachable"
             ".test_reachable_stays_unknown_when_no_url_was_given",
        scar="a publish with no URL crashes on the fetch instead of saying that "
             "nobody asked, which is the difference between unknown and false",
    ),
    Mutation(
        name="the-dry-run-writes",
        file="engine/publish.py",
        search="    if dry_run:",
        replace="    if False:",
        test="tests.test_publish.TheDryRunIsTheDefaultAndTouchesNothing"
             ".test_a_dry_run_writes_nothing",
        scar="the default invocation writes to a machine, so the one command "
             "that previews before touching a served directory does not preview",
    ),
    Mutation(
        name="a-page-too-large-meets-the-shell-instead-of-a-refusal",
        file="engine/publish.py",
        search="    if len(encoded) > MAX_BYTES:",
        replace="    if False:",
        test="tests.test_publish.APageTooLargeToTravelIsRefusedByName"
             ".test_a_page_that_will_not_fit_in_an_argv_is_refused_before_it_is_tried",
        scar="a large page reaches the shell as one command line and comes back "
             "as an argument list error naming neither the page nor the size",
    ),
    # ── publish, second round: the marker's claim, the files that travel with
    # ── the page, and the neighbours the page links to.
    Mutation(
        name="the-marker-claims-a-fixed-list-instead-of-what-was-delivered",
        file="engine/publish.py",
        search=r'    listed = "".join(f"  - {name}\n" for name in names)',
        replace=r'    listed = f"  - {PAGE_NAME}\n"',
        test="tests.test_publish.TheMarkerSaysWhatIsThereAndWhatWillHappenToIt"
             ".test_the_marker_names_every_file_that_was_delivered",
        scar="the directory's one statement about its own content names the page "
             "and not the files delivered beside it, so it is already incomplete "
             "on the run that wrote it and nobody can tell a leftover from a "
             "file that is current",
    ),
    Mutation(
        name="a-file-left-over-from-an-earlier-publish-is-never-mentioned",
        file="engine/publish.py",
        search="    return tuple(e for e in obs.entries if e != MARKER and e not in delivered)",
        replace="    return ()",
        test="tests.test_publish.TheMarkerSaysWhatIsThereAndWhatWillHappenToIt"
             ".test_a_file_from_an_earlier_publish_is_named_rather_than_left_unsaid",
        scar="a page that dropped out of the output stays in the served "
             "directory and is handed out as though it were current, because "
             "nothing here removes a file and nothing said so",
    ),
    Mutation(
        name="an-oversize-attachment-meets-the-shell-instead-of-a-refusal",
        file="engine/publish.py",
        search="    for name, content in files[1:]:\n"
               '        _refuse_if_too_large(f"the attachment {name}", content)',
        replace="    for name, content in files[1:]:\n"
                "        pass",
        test="tests.test_publish.AttachmentsTravelWithThePageAndAreProvedLikeIt"
             ".test_an_oversize_attachment_is_refused_by_name_and_never_truncated",
        scar="the limit is enforced on the page alone, so a large attachment "
             "reaches the shell as one command line and comes back as an "
             "argument list error naming neither the file nor the size, after "
             "the marker and the page have already been written",
    ),
    Mutation(
        name="two-attachments-under-one-name-are-taken-anyway",
        file="engine/publish.py",
        search="        if name in seen:",
        replace="        if False:",
        test="tests.test_publish.AttachmentsTravelWithThePageAndAreProvedLikeIt"
             ".test_two_attachments_under_one_name_are_refused",
        scar="the second file overwrites the first, both read back equal to what "
             "was sent, and the report shows two files delivered where the "
             "directory holds one",
    ),
    Mutation(
        name="a-file-that-cannot-travel-is-mangled-instead-of-refused",
        file="engine/publish.py",
        search=r'        if not content.endswith("\n"):',
        replace="        if False:",
        test="tests.test_publish.WhatCannotTravelIsRefusedBeforeAMachineIsAsked"
             ".test_a_file_that_does_not_end_on_a_newline_is_refused",
        scar="the here-document adds the closing newline itself and the "
             "read-back then reports a difference the machine never caused, "
             "which points whoever reads it at the wrong end of the wire",
    ),
    Mutation(
        name="an-attachment-that-never-arrived-is-folded-into-the-clean-run",
        file="engine/publish.py",
        search="        return self.ok and all(item.delivered for item in self.attachments)",
        replace="        return self.ok",
        test="tests.test_publish.AttachmentsTravelWithThePageAndAreProvedLikeIt"
             ".test_an_attachment_that_did_not_arrive_leaves_the_page_delivered",
        scar="a run asked for a page and a stylesheet that delivered only the "
             "page reports as having done everything it was asked, and exits 0",
    ),
    Mutation(
        name="the-link-bar-drops-the-sentence-that-says-it-measured-nothing",
        file="engine/view.py",
        search="            + f'<span class=\"meta\">{LINKS_NOTE}</span></nav>')",
        replace='            + "</nav>")',
        test="tests.test_view.TheLinkBarNavigatesAndMeasuresNothing"
             ".test_the_bar_says_that_it_opened_none_of_them",
        scar="a reader takes a link on a dashboard for a link the dashboard "
             "vouches for, so a neighbouring page whose producer stopped running "
             "reads as current because this one points at it",
    ),
    Mutation(
        name="the-configured-neighbours-are-read-and-then-thrown-away",
        file="engine/cli.py",
        search="                            links=view_links(cfg),",
        replace="                            links=(),",
        test="tests.test_cli.TheNeighbourLinksReachThePage"
             ".test_a_configured_bar_arrives_at_the_renderer",
        scar="the block is read and validated one line above and never reaches "
             "the renderer, so the configuration key is a switch with no effect "
             "and nothing anywhere reports it",
    ),
    Mutation(
        name="half-a-link-entry-is-dropped-instead-of-refused",
        file="engine/cli.py",
        search="        if not label or not href:",
        replace="        if False:",
        test="tests.test_cli.TheNeighbourLinksComeFromConfigurationAndNowhereElse"
             ".test_half_an_entry_is_refused_by_name",
        scar="an entry missing its target is dropped without a word and the bar "
             "merely looks short, so the missing link is discovered only when "
             "the page it pointed at is the one somebody needed",
    ),
    # ── the page's own arithmetic, which only the reader's clock can run.
    Mutation(
        name="a-freshness-verdict-is-taken-without-a-declared-cadence",
        file="engine/view.py",
        search="  if (staleAfterMin === null || staleAfterMin === undefined || !(staleAfterMin > 0)) {",
        replace="  if (false) {",
        test="tests.test_view.FreshnessIsTheReadersVerdict"
             ".test_no_verdict_without_a_declared_cadence",
        scar="a page nobody declared a refresh interval for judges itself against "
             "a threshold of zero and shouts stale at every reader for ever",
    ),
    Mutation(
        name="a-page-stamped-in-the-future-is-reported-as-an-age",
        file="engine/view.py",
        search="  if (ms < -60000) { return 'the clocks disagree'; }",
        replace="  if (false) { return 'the clocks disagree'; }",
        test="tests.test_view.FreshnessIsTheReadersVerdict"
             ".test_a_stamp_from_the_future_is_never_reported_as_an_age",
        scar="two machines whose clocks differ produce a dashboard that says the "
             "page was made just now when it was made hours from now, hiding the "
             "clock skew that is the actual finding",
    ),
    Mutation(
        name="a-tilde-is-sent-to-the-machine-as-it-stands",
        file="engine/publish.py",
        search='    if not dest.startswith("~"):\n        return dest',
        replace="    if True:\n        return dest",
        test="tests.test_publish.ATildeIsResolvedAgainstTheMachinesOwnHome"
             ".test_a_leading_tilde_becomes_the_probed_home",
        scar="every path travels inside a quoted shell word, so `~/site` reaches "
             "the machine as a literal tilde and `mkdir -p` makes a directory "
             "called ~ in the home directory. The write and the read-back then "
             "use the same wrong path and agree with each other perfectly",
    ),
    Mutation(
        name="the-home-directory-is-guessed-when-it-was-not-probed",
        file="engine/publish.py",
        search='    if not home:\n        raise errors.DestinationNotResolvable(',
        replace='    if False:\n        raise errors.DestinationNotResolvable(',
        test="tests.test_publish.ATildeIsResolvedAgainstTheMachinesOwnHome"
             ".test_the_home_is_never_guessed",
        scar="an unprobed home turns into an empty prefix, so the destination "
             "becomes an absolute path at the root of the filesystem",
    ),
    Mutation(
        name="an-answer-that-is-not-two-hundred-becomes-a-crash",
        file="engine/publish.py",
        search="    except urllib.error.HTTPError as err:\n        return err.code, (err.read() or b\"\")",
        replace="    except urllib.error.HTTPError as err:\n        raise",
        test="tests.test_publish.TheFetcherItselfIsMeasured"
             ".test_a_status_that_is_not_two_hundred_is_reported_and_not_raised",
        scar="the branch that reports an unreachable page cannot run in the only "
             "implementation that ships, because a 404 leaves the module as a "
             "traceback instead of a finding",
    ),
    Mutation(
        name="the-page-lists-what-the-terminal-counts",
        file="engine/view.py",
        search="        if state in COUNTED_ONLY_VALUES:",
        replace="        if False:",
        test="tests.test_view.ThePageCollapsesWhatTheReportCollapses"
             ".test_a_wall_of_unclaimed_units_is_counted_and_not_listed",
        scar="the same run is one summary line in the terminal and eleven "
             "hundred rows in the browser, so the four declarations the reader "
             "came for sit above two hundred kilobytes of somebody else's daemons",
    ),
    Mutation(
        name="the-collapsed-units-vanish-instead-of-being-counted",
        file="engine/view.py",
        # Retargeted 2026-08-27: the block moved one level in, under the
        # section that introduces it.
        search="        if unclaimed:\n            body.append(",
        replace="        if False:\n            body.append(",
        test="tests.test_view.ThePageCollapsesWhatTheReportCollapses"
             ".test_a_wall_of_unclaimed_units_is_counted_and_not_listed",
        scar="collapsing turns into dropping, and a number that changes between "
             "two renders is the arrival of something nobody declared",
    ),
    # ── the calendar: two questions, each answered where it was already answered.
    Mutation(
        name="the-drawing-works-out-its-own-fire-time",
        file="engine/view.py",
        search="            placed = backend_base.starts_of(w)",
        replace="            placed = ((None, 0, 0, 0),)",
        test="tests.test_view.WhenDoesWhatRun"
             ".test_a_daily_run_sits_at_its_own_hour_on_the_axis",
        scar="the picture and the unit file disagree about when a job fires, and "
             "the picture is the one a human believes",
    ),
    Mutation(
        name="a-run-at-any-hour-fills-the-appointment-it-did-not-keep",
        file="engine/view.py",
        search="        shape, hint = _appointment_shape(w.id, findings)",
        replace='        shape, hint = (("trace", "") if (getattr(rep, "runs", None) or {})'
                ".get(w.id) else _appointment_shape(w.id, findings))",
        test="tests.test_view.ATraceIsNotAnAppointmentKept"
             ".test_a_run_at_another_hour_does_not_fill_the_appointment",
        scar="the live defect this replaced: a 07:20 job whose only trace came "
             "from a verification run at 15:54 was drawn as an appointment kept, "
             "on the first machine the calendar was ever pointed at",
    ),
    Mutation(
        name="a-utc-stamp-is-placed-on-a-local-axis-without-a-zone",
        file="engine/view.py",
        search="    if not zone:\n        return None, \"\", (f\"last run {when}, not placed on the axis: the \"",
        replace="    if False:\n        return None, \"\", (f\"last run {when}, not placed on the axis: the \"",
        test="tests.test_view.ATraceIsNotAnAppointmentKept"
             ".test_without_a_declared_zone_the_run_is_not_placed_at_all",
        scar="the trace is UTC and the axis is the machine's own day, so every "
             "mark sits hours out for half the year and nothing on the page says so",
    ),
    Mutation(
        name="the-ring-and-the-diamond-become-one-mark",
        file="engine/view.py",
        search="    if model.WorkloadState.overdue.value in states:",
        replace="    if False:",
        test="tests.test_view.WhenDoesWhatRun"
             ".test_the_ring_at_an_appointment_says_whether_the_schedule_is_kept",
        scar="the gap, which is the whole reason to look at a calendar of "
             "scheduled runs, is drawn the same as a schedule nobody worries about",
    ),
    Mutation(
        name="a-run-that-cannot-be-placed-leaves-an-empty-lane",
        file="engine/view.py",
        search="            out.append(Lane(**common, note=f\"cannot be placed on the axis: {refusal}\"))",
        replace="            out.append(Lane(**common))",
        test="tests.test_view.WhenDoesWhatRun"
             ".test_a_run_that_cannot_be_placed_says_so_instead_of_leaving_a_gap",
        scar="an undrawable recurrence gets a blank lane, which reads as a job "
             "with nothing scheduled rather than as one nothing could place",
    ),
    Mutation(
        name="a-shape-appears-on-the-axis-that-nothing-explains",
        file="engine/view.py",
        search="        for name, text in SHAPES if name in shown)",
        replace="        for name, text in () if name in shown)",
        test="tests.test_view.WhenDoesWhatRun"
             ".test_every_shape_on_the_page_is_in_the_legend",
        scar="marks whose whole purpose is to be read without colour appear with "
             "nothing saying what they mean",
    ),
    Mutation(
        name="retired-declarations-are-counted-into-what-is-in-service",
        file="engine/view.py",
        search="    in_service = [row for row in declared if not row.retired]",
        replace="    in_service = list(declared)",
        test="tests.test_view.OnlyWhatIsInServiceIsOnTheBoard"
             ".test_a_retired_declaration_is_not_a_row",
        scar="a reader counts the rows to learn how much runs on a machine and "
             "gets the number of declarations ever written instead",
    ),
    Mutation(
        name="an-inventory-entry-is-reported-as-something-on-the-machine",
        file="engine/view.py",
        search="        elif state in INVENTORY_VALUES:",
        replace="        elif False:",
        test="tests.test_view.OnlyWhatIsInServiceIsOnTheBoard"
             ".test_an_inventory_entry_is_not_filed_under_the_machine",
        scar="an entry that exists ONLY in infra/remotes/<host>.yaml is filed "
             "under what the machine carries, which says the opposite of the "
             "finding it renders",
    ),
    Mutation(
        name="the-observed-runs-never-leave-reconcile",
        file="engine/reconcile.py",
        search="                runs[w.id] = (when.strftime(\"%Y-%m-%dT%H:%M:%SZ\"), rc)",
        replace="                pass",
        test="tests.test_reconcile.TheRunsThatWereObservedReachTheReport"
             ".test_a_trace_on_the_host_arrives_in_the_report",
        scar="the timeline can draw what a declaration intends and nothing about "
             "whether it happened, which is the most confident possible drawing "
             "of an unverified claim",
    ),
    Mutation(
        name="the-system-domain-is-asked-with-the-sessions-question",
        file="engine/backends/launchd.py",
        search='        if self.discovery == "domain":\n            # `launchctl print <domain>`',
        replace='        if False:\n            # `launchctl print <domain>`',
        test="tests.test_backends.TwoDomainsAreTwoQuestions"
             ".test_the_system_domain_reads_the_system_domain",
        scar="both launchd domains enumerate with `launchctl list`, which "
             "answers about the calling session, so every user agent is also "
             "reported as a root daemon and every real root daemon is invisible",
    ),
    Mutation(
        name="a-session-listing-is-relabelled-as-the-system-domain",
        file="engine/backends/launchd.py",
        search='        if self.discovery == "domain":\n            return self._parse_domain_print(listing)',
        replace="        if False:\n            pass",
        test="tests.test_backends.TwoDomainsAreTwoQuestions"
             ".test_a_session_listing_never_becomes_a_root_daemon",
        scar="units enumerated in one domain are stamped with the name of the "
             "other, which invents root daemons that do not exist",
    ),
    Mutation(
        name="a-neighbouring-block-leaks-into-the-service-list",
        file="engine/backends/launchd.py",
        search='            if stripped == "}" and (len(line) - len(line.lstrip())) == indent:\n                break',
        replace="            if False:\n                break",
        test="tests.test_backends.TwoDomainsAreTwoQuestions"
             ".test_the_system_block_is_read_and_bounded",
        scar="`launchctl print` carries an endpoints block whose rows look like "
             "service rows, so a mach endpoint becomes a service that can then "
             "be reported missing",
    ),
    Mutation(
        name="an-entry-is-called-stale-although-nothing-looked",
        file="engine/inventory.py",
        search="    if unlooked and unmatched:",
        replace="    if False:",
        test="tests.test_reconcile.NotAskedIsNotAbsent"
             ".test_an_incomplete_look_never_calls_an_entry_stale",
        scar="a runtime that could not be enumerated still produces the sentence "
             "`neither a declaration nor the machine knows it` and the hint to "
             "drop the entry, about services that are running",
    ),
    Mutation(
        name="a-sentence-is-held-on-one-line-like-an-identifier",
        file="engine/view.py",
        # Retargeted 2026-08-27: the ceiling moved from the sentence to the
        # column, so the rule is shorter; the release from nowrap is what
        # this needle has always been about and is still here.
        search=".id .meta { white-space: normal; display: block; margin-top: .1875rem; }",
        replace=".id .meta { display: block; margin-top: .1875rem; }",
        test="tests.test_view.ASentenceIsNotAnIdentifier"
             ".test_the_purpose_is_released_from_the_cells_nowrap",
        scar="the purpose inherits the id cell's nowrap, the first column grows "
             "past the page width, and the column carrying the verdict is cut "
             "off the right edge",
    ),
    Mutation(
        name="a-page-nobody-refreshes-keeps-that-to-itself",
        file="engine/view.py",
        search='<p class="banner" id="norefresh"><strong>Nothing refreshes this ',
        replace='<p class="banner" id="quiet"><strong>Nothing refreshes this ',
        test="tests.test_view.APageNobodyRefreshesSaysSo"
             ".test_without_a_cadence_the_page_says_nothing_refreshes_it",
        scar="a page published once by hand looks exactly like one refreshed a "
             "minute ago; its reader took an eight hour old count for the "
             "present and concluded a service was missing",
    ),
    Mutation(
        name="an-evidence-nothing-writes-passes-the-gate",
        file="engine/model.py",
        search="        if not (heard & TRACE_WRITING_NOTIFICATIONS):",
        replace="        if False:",
        test="tests.test_model.EvidenceNothingWillWrite"
             ".test_a_trace_nobody_will_write_is_refused",
        scar="a declaration names log-trace as its proof, asks for no "
             "notification, and the guard therefore writes no trace: it is "
             "provisioned, runs, exits zero and leaves nothing, while "
             "reconcile calls it in sync",
    ),
    Mutation(
        name="a-run-speaks-into-dev-null",
        file="engine/backends/wrapper.py",
        # Dedented on 2026-08-30 when the decision moved above `if deadline:`.
        # The anchor is the LITERAL, so the move alone silently unhooked this
        # mutation and the harness said so: "the anchor appears 0 times, so the
        # mutation applies to nothing and has been proving nothing". That
        # sentence is the reason the battery exists, and it is worth one line
        # here so the next person who reindents this knows what they break.
        search='        redirect = \' > "$OUT_FILE" 2>&1\'',
        replace='        redirect = ""',
        test="tests.test_backends.WhatARunSaidIsKept"
             ".test_the_capture_truncates_and_never_appends",
        scar="a service manager gives a unit no output destination, so the run "
             "speaks into /dev/null: a health report that warns its mail never "
             "left and then exits zero loses the only sign that it failed",
    ),
    Mutation(
        name="a-daemon-speaks-into-dev-null",
        file="engine/backends/wrapper.py",
        # The SECOND arm, which the mutation above never reached. Softening the
        # use rather than the value: put the old literal back and the arm
        # without a deadline runs bare again, exactly as it did until today.
        search='        add(f"{command}{redirect}")',
        replace='        add(f"{command}{\' > \\"$RECEIPT_FILE\\" 2>&1\' if receipt else \'\'}")',
        test="tests.test_backends.AKindWithoutADeadlineIsKeptToo"
             ".test_a_daemon_redirects_into_the_file_the_guard_prepared_for_it",
        scar="a daemon has no deadline, so it took the other arm and ran with "
             "no redirect at all while the guard still defined its output file "
             "and still capped it: a prepared destination nobody ever wrote "
             "to, and an access log that died at the minute of its migration",
    ),
    Mutation(
        name="one-verbose-run-has-no-ceiling",
        file="engine/backends/wrapper.py",
        search='        add(\'    tail -c "$OUT_CAP_BYTES" "$OUT_FILE" > "$OUT_FILE.cap" 2>/dev/null \\\\\')',
        replace='        add(\'    : \')',
        test="tests.test_backends.WhatARunSaidIsKept"
             ".test_one_chatty_run_cannot_fill_the_disk",
        scar="truncating per run bounds the file across runs but not within "
             "one; a single verbose run can still fill the disk",
    ),
    Mutation(
        name="the-page-rebuilds-the-machines-name-itself",
        file="engine/view.py",
        search="        return str(backend.unit_name(w) or \"\")",
        replace="        return \"bridge.\" + str(w.id)",
        test="tests.test_view.TheTableCarriesBothLabels"
             ".test_the_page_says_so_where_a_runtime_names_nothing",
        scar="a second derivation of a unit name drifts from the backend that "
             "owns it; four hand kept prefix lists doing exactly this filed a "
             "migrated run as foreign software",
    ),
    Mutation(
        name="a-recurring-run-can-never-be-overdue",
        file="engine/reconcile.py",
        # Retargeted 2026-08-27, twice on the same day: the call gained the
        # boot moment in the morning and the off-list in the evening, and each
        # time the old literal named nothing and the needle read green while
        # proving nothing.
        search="        out.extend(_appointment_overdue(w, appointment, newest, stamp, now,\n                                        finding, booted, switched_off))",
        replace="        out.extend([])",
        test="tests.test_reconcile.ARecurringRunCanBeOverdueToo"
             ".test_a_run_that_missed_its_appointment_is_reported",
        scar="a customer facing report declared notify_on missing, its guard "
             "wrote a trace on every run, and the report answered the question "
             "with a shrug on the one run whose silence nobody would notice",
    ),
    Mutation(
        name="the-due-moment-is-read-in-utc-instead-of-the-declared-zone",
        file="engine/backends/base.py",
        search="    local = now.astimezone(zone)",
        replace="    local = now",
        test="tests.test_backends.WhenWasThisAppointmentLastDue"
             ".test_it_is_computed_in_the_declared_zone_and_not_in_utc",
        scar="an appointment is wall clock and a trace is UTC; read in the "
             "wrong zone the answer is off by the offset all year and by an "
             "hour more for half of it, and looks perfectly reasonable",
    ),
    Mutation(
        name="a-day-the-run-does-not-fire-on-counts-anyway",
        file="engine/backends/base.py",
        search="        if days and launchd_weekday not in days:",
        replace="        if False:",
        test="tests.test_backends.WhenWasThisAppointmentLastDue"
             ".test_a_day_the_run_does_not_fire_on_is_skipped",
        scar="asked on a Sunday about a run that fires Monday to Saturday, the "
             "answer would be Sunday, and every Sunday would report a missed run",
    ),
    Mutation(
        name="a-run-still-inside-its-deadline-is-called-missing",
        file="engine/reconcile.py",
        search="    grace = int(backend_base.timeout_of(w) or 0) + OVERDUE_GRACE_SEC",
        replace="    grace = 0",
        test="tests.test_reconcile.ARecurringRunCanBeOverdueToo"
             ".test_a_run_still_inside_its_deadline_is_not_yet_called_missing",
        scar="a slow run reported as a missing one is the false alarm that "
             "teaches a reader to ignore the real one",
    ),
    Mutation(
        name="an-untranslatable-recurrence-is-approximated",
        file="engine/reconcile.py",
        search="    except errors.WorkloadError as refusal:",
        replace="    except ZeroDivisionError as refusal:",
        test="tests.test_reconcile.TheTraceIsReadBackOrTheEvidenceIsDecoration"
             ".test_a_recurrence_outside_the_translated_subset_still_says_so",
        scar="a rule the renderer refuses would be approximated here and "
             "printed as a measurement",
    ),
    Mutation(
        name="every-unit-is-judged-against-the-first-appointments-hour",
        file="engine/reconcile.py",
        search="            mine_appointment = _appointment_of(w, own)",
        replace="            mine_appointment = None",
        test="tests.test_reconcile.ARecurringRunCanBeOverdueToo"
             ".test_the_midday_unit_is_judged_against_the_midday_hour",
        scar="the midday unit would be called missing every morning and the "
             "morning unit would never be",
    ),
    Mutation(
        name="two-unit-names-run-into-one-another",
        file="engine/view.py",
        search='    return "<br>".join(_esc(n) for n in names)',
        replace='    return "\\n".join(_esc(n) for n in names)',
        test="tests.test_view.TheTableNamesEveryUnitAndEveryTime"
             ".test_the_two_names_are_separated_in_the_markup",
        scar="a newline is whitespace to HTML and the cell is nowrap, so two "
             "labels become one unreadable token",
    ),
    Mutation(
        name="a-run-with-two-units-says-it-has-none",
        file="engine/view.py",
        search="        if len(appointments) > 1:\n            names = [str(backend.unit_name(w, a) or \"\") for a in appointments]",
        replace="        if False:\n            names = [str(backend.unit_name(w, a) or \"\") for a in appointments]",
        test="tests.test_view.TheTableNamesEveryUnitAndEveryTime"
             ".test_a_run_with_units_never_says_it_has_none",
        scar="the sentence reserved for a runtime that names nothing was shown "
             "for a run whose two units were loaded and had just delivered; a "
             "reserved word used for something else stops meaning anything",
    ),
    Mutation(
        name="the-when-column-forgets-the-appointments",
        file="engine/view.py",
        search="    if len(appointments) > 1:\n        return \"; \".join(",
        replace="    if False:\n        return \"; \".join(",
        test="tests.test_view.TheTableNamesEveryUnitAndEveryTime"
             ".test_the_when_column_carries_both_times",
        scar="a declaration using appointments carries no rrule and no "
             "delivery_at, so the shorthand branch answered '-' for a run that "
             "fires twice a day",
    ),
    Mutation(
        name="only-one-unit-of-a-run-is-ever-assessed",
        file="engine/reconcile.py",
        search="        for unit in (mine or (None,)):",
        replace="        for unit in (mine or (None,))[:1]:",
        test="tests.test_reconcile.BothUnitsGetTheirOwnVerdict"
             ".test_every_unit_is_named_in_a_verdict_of_its_own",
        scar="the other unit could be unloaded, disabled or drifted and the "
             "report would read the same; silence about a unit is read as "
             "nothing being wrong with it",
    ),
    Mutation(
        name="a-unit-is-judged-against-a-siblings-trace",
        file="engine/reconcile.py",
        search='            key = str(getattr(own, "state_key", "") or "") or w.id',
        replace="            key = w.id",
        test="tests.test_reconcile.BothUnitsGetTheirOwnVerdict"
             ".test_a_unit_is_judged_against_its_own_history",
        scar="reading the morning run's history for the midday unit answers "
             "'it ran' about a run that did not",
    ),
    Mutation(
        name="both-units-write-over-one-anothers-stamp",
        file="engine/stamp.py",
        search='    return (str(getattr(stamp, "state_key", "") or "").strip()\n'
               '            or str(getattr(stamp, "workload_id", "") or ""))',
        replace='    return str(getattr(stamp, "workload_id", "") or "")',
        test="tests.test_provision.EveryUnitFilesItsOwnStamp"
             ".test_two_appointments_write_two_records",
        scar="measured on a real machine: both units provisioned and verified, "
             "ONE stamp on disk, and the surviving unit indistinguishable from "
             "one that had never been provisioned",
    ),
    Mutation(
        name="the-record-is-built-without-its-key",
        file="engine/provision.py",
        search="        state_key=_state_key_for(w, artifact),",
        replace='        state_key="",',
        test="tests.test_provision.EveryUnitFilesItsOwnStamp"
             ".test_two_appointments_write_two_records",
        scar="the reading side used the unit key and the writing side did not, "
             "and the pair was never measured together",
    ),
    Mutation(
        name="the-run-is-never-told-which-appointment-fired",
        file="engine/backends/wrapper.py",
        search="    if appointment_name:\n        add(f\"{MARKER_ENV_APPOINTMENT}=",
        replace="    if False:\n        add(f\"{MARKER_ENV_APPOINTMENT}=",
        test="tests.test_backends.TheRunIsToldWhichAppointmentFired"
             ".test_each_guard_names_its_own_appointment",
        scar="two appointments share one argv and answer two distribution "
             "lists; without the name the command cannot tell them apart and "
             "the difference goes back into a second copy of the script",
    ),
    Mutation(
        name="the-appointment-is-assigned-but-never-exported",
        file="engine/backends/wrapper.py",
        search="        add(f\"export {MARKER_ENV_APPOINTMENT}\")",
        replace="        pass",
        test="tests.test_backends.TheRunIsToldWhichAppointmentFired"
             ".test_the_variable_is_exported_and_not_merely_assigned",
        scar="a shell variable that is set and not exported is invisible to "
             "the command the guard wraps, and the failure is silent",
    ),
    Mutation(
        name="the-shorthand-and-the-list-may-both-be-written",
        file="engine/model.py",
        search='                    "a declaration carries EITHER the single-appointment "',
        replace='                    "" or (',
        test="tests.test_model.OneRunMayKeepSeveralAppointments"
             ".test_two_spellings_of_the_same_schedule_are_refused",
        scar="a file carrying both spellings says two different things about "
             "when it fires, and a backend picks one of them silently",
    ),
    Mutation(
        name="two-appointments-may-share-a-name",
        file="engine/model.py",
        search='            elif str(name) in names:',
        replace='            elif False:',
        test="tests.test_model.OneRunMayKeepSeveralAppointments"
             ".test_two_appointments_may_not_share_a_name",
        scar="two appointments with one name render to ONE unit file, where "
             "the second replaces the first and neither the report nor the "
             "machine says so",
    ),
    Mutation(
        name="only-at-may-name-an-appointment-that-does-not-exist",
        file="engine/model.py",
        search='            if str(wanted) not in names:',
        replace='            if False:',
        test="tests.test_model.OneRunMayKeepSeveralAppointments"
             ".test_only_at_naming_an_appointment_that_does_not_exist_is_refused",
        scar="the recipient gets nothing while the file still reads as though "
             "they were on the list",
    ),
    Mutation(
        name="the-digest-stops-seeing-the-appointments",
        file="engine/model.py",
        search="""            "appointments": [
                {"name": a.name, "at": a.at, "rrule": a.rrule,
                 "duration_estimate_min": a.duration_estimate_min}
                for a in w.schedule.appointments],""",
        replace='            "appointments": [],',
        test="tests.test_model.OneRunMayKeepSeveralAppointments"
             ".test_the_digest_notices_a_changed_appointment",
        scar="a report moved by six hours would read as no change at all, and "
             "drift detection is the whole reason the digest exists",
    ),
    Mutation(
        name="only-the-first-appointment-becomes-a-unit",
        file="engine/render.py",
        search="    return tuple(render(w, h, ctx, appointment=a) for a in appointments)",
        replace="    return (render(w, h, ctx, appointment=appointments[0]),)",
        test="tests.test_backends.SeveralAppointmentsBecomeSeveralUnits"
             ".test_one_declaration_renders_one_unit_per_appointment",
        scar="the second appointment would never be rendered, never be "
             "provisioned and never be missed, because nothing would know it "
             "was owed",
    ),
    Mutation(
        name="both-units-share-one-trace",
        file="engine/backends/wrapper.py",
        search='    state_id = f"{safe_id}.{appointment_name}" if appointment_name else safe_id',
        replace="    state_id = safe_id",
        test="tests.test_backends.SeveralAppointmentsBecomeSeveralUnits"
             ".test_the_two_units_keep_separate_traces",
        scar="one shared history answers neither question: a single fire reads "
             "as proof that both appointments happened",
    ),
    Mutation(
        name="a-second-unit-of-the-same-run-is-reported-as-foreign",
        file="engine/inventory.py",
        search="            seen.add(unit.unit_ref)\n            found.append(unit)",
        replace="            seen.add(unit.unit_ref)\n            found.append(unit)\n            break",
        test="tests.test_reconcile.EachAppointmentIsReconciledOnItsOwn"
             ".test_every_unit_of_a_declaration_is_found",
        scar="a unit called foreign while its own declaration sits in the "
             "repository teaches a reader to stop believing the report",
    ),
    Mutation(
        name="the-state-key-forgets-the-appointment",
        file="engine/model.py",
        search='    return f"{w.id}.{name}" if name else str(w.id)',
        replace="    return str(w.id)",
        test="tests.test_reconcile.EachAppointmentIsReconciledOnItsOwn"
             ".test_the_state_key_names_the_unit_and_not_the_declaration",
        scar="both units file their stamp under one name, so the second "
             "overwrites the first and a running unit reads as never provisioned",
    ),
    Mutation(
        name="the-calendar-draws-only-the-first-appointment",
        file="engine/view.py",
        # Retargeted 2026-08-27: one lane is drawn by `_lane_html` now.
        search="    for mark in (lane.appointments or ()):",
        replace="    for mark in (lane.appointments or ())[:1]:",
        test="tests.test_view.TwoAppointmentsAreTwoMarksOnOneLane"
             ".test_the_page_draws_a_tick_for_every_appointment",
        scar="a dropped appointment makes the lane look exactly like a run "
             "that fires once, so the drawing asserts what the unit files deny",
    ),
    Mutation(
        name="a-silence-with-a-known-cause-is-reported-as-a-mystery",
        file="engine/view.py",
        search="        if asked and row.host and row.host not in asked:",
        replace="        if False:",
        test="tests.test_view.NotReportedIsNotAlwaysAMystery"
             ".test_a_run_placed_on_a_machine_the_page_did_not_ask_says_so",
        scar="`not reported` that always reads the same teaches a reader to "
             "skip it, and the next one is a run that stopped",
    ),
    Mutation(
        name="a-genuine-silence-is-explained-away-as-a-placement",
        file="engine/view.py",
        search="        if asked and row.host and row.host not in asked:",
        replace="        if True:",
        test="tests.test_view.NotReportedIsNotAlwaysAMystery"
             ".test_a_run_on_the_asked_machine_keeps_the_honest_generic_sentence",
        scar="the opposite failure and the worse one: a run on the machine that "
             "WAS asked, silent for an unknown reason, given an invented cause",
    ),
    Mutation(
        name="the-page-forgets-which-machines-it-asked",
        file="engine/cli.py",
        search="                            hosts=tuple(args.host or ()),",
        replace="                            hosts=(),",
        test="tests.test_cli.TheHostFilterReachesThePage"
             ".test_the_machines_named_on_the_command_line_reach_the_renderer",
        scar="the renderer can only explain a silence it was told the shape of; "
             "dropping it at the caller is silent, and a test written against "
             "the renderer alone stays green because it passes the argument "
             "itself",
    ),
    Mutation(
        name="the-reason-goes-back-into-the-verdict-column",
        file="engine/view.py",
        # Retargeted twice. 2026-08-27: the row spans four columns, because
        # six of the ten moved into the panel it opens.
        search='f\'<tr class="why" id="why-{ident}"><td colspan="4">\'',
        replace='f\'<tr class="why" id="why-{ident}" hidden><td colspan="4">\'',
        # Retargeted 2026-08-27. The row became a disclosure, so the property
        # under attack is no longer "does it span the table" (which stays true
        # with `hidden` on it) but "does the page ship it open". The test that
        # measures THAT is the one the needle has to run, or the needle proves
        # the shape of a row while the mutation removes its content.
        test="tests.test_view.TheReasonsAreOneClickAwayNotOneScroll"
             ".test_the_page_ships_expanded",
        scar="a reason rendered but not shown is the same defect as a reason "
             "with no room: the reader gets the verdict and no way to check it. "
             "Since the row became a disclosure this is also how a reader "
             "WITHOUT scripting loses every reason on the page",
    ),
    Mutation(
        name="a-reason-stops-naming-the-verdict-it-explains",
        file="engine/view.py",
        search='f\'<div class="hint"><span class="lead">{_esc(_state(f))}</span>\'',
        replace='f\'<div class="hint"><span class="lead"></span>\'',
        test="tests.test_view.TheVerdictGetsTheRoomItNeeds"
             ".test_each_reason_still_names_its_state",
        scar="one run can carry several findings; once the sentences leave the "
             "cell that held their state word, nothing else maps them back",
    ),
    Mutation(
        name="the-verdict-column-loses-its-floor",
        file="engine/view.py",
        # Retargeted 2026-08-27: the floor is 8rem now that the row carries
        # four columns instead of ten. A floor is the property, not its value.
        search="         min-width: 8rem; display: inline-block; }",
        replace="         display: inline-block; }",
        test="tests.test_view.TheVerdictGetsTheRoomItNeeds"
             ".test_the_verdict_column_has_a_floor",
        scar="seven single token columns take their width unconditionally; "
             "without a floor the ninth column is crushed by the next label "
             "somebody adds, which is exactly how it got too small",
    ),
    Mutation(
        name="the-finding-tables-lose-their-striping",
        file="engine/view.py",
        search=".findings tbody tr:nth-child(even) { background: var(--surface-subtle); }",
        replace="",
        test="tests.test_view.TheVerdictGetsTheRoomItNeeds"
             ".test_a_run_and_its_reasons_stay_one_visual_unit",
        scar="the runs table fix moved striping to whole tbodies; an eighteen "
             "row finding table with a single tbody would then have none",
    ),
    Mutation(
        name="an-undecided-persona-renders-as-an-empty-cell",
        file="engine/view.py",
        search="        return UNDECIDED_PERSONA",
        replace='        return ""',
        test="tests.test_view.TheTableCarriesBothLabels"
             ".test_a_declaration_without_a_persona_says_undecided",
        scar="absent and `_shared` become the same cell, so a run nobody has "
             "assigned reads as one deliberately shared",
    ),
    # The declaration on disk, which nothing compared against until now. Every
    # signal reconcile had lived on the machine and was written in one second by
    # one provision, so the machine could only ever agree with itself.
    Mutation(
        name="the-file-on-disk-is-never-compared",
        file="engine/reconcile.py",
        search="    if declared_now == recorded:\n        return None",
        replace="    return None",
        test="tests.test_reconcile.TheMachineCanBeBehindTheFile"
             ".test_an_edited_declaration_is_reported_against_its_stamp",
        scar="edit a declaration, forget to provision, and the report stays "
             "green about a machine running the older file",
    ),
    Mutation(
        name="both-kinds-of-drift-tell-the-same-story",
        file="engine/reconcile.py",
        search='        hint="provision it again so the machine runs what the declaration says",\n        source="declaration",',
        replace='        hint="provision it again so the machine runs what the declaration says",\n        source="machine",',
        test="tests.test_reconcile.TheMachineCanBeBehindTheFile"
             ".test_the_finding_says_the_declaration_moved_not_the_machine",
        scar="somebody replacing a unit on the box and us editing a file read "
             "as one event, and the reader goes looking on the wrong side",
    ),
    Mutation(
        name="a-retired-declaration-is-measured-anyway",
        file="engine/reconcile.py",
        # Anchored on the retirement half alone: the check moved out of the
        # per-unit loop on 2026-08-25 and the stamp it reads changed name with
        # it, so anchoring on the whole line took the needle along.
        search="        if stamp is not None and not w.is_retired:",
        replace="        if stamp is not None:",
        test="tests.test_reconcile.TheMachineCanBeBehindTheFile"
             ".test_a_retired_declaration_is_not_measured_against_its_stamp",
        scar="a deliberately stopped run reports drift forever and sends the "
             "reader to provision it back to life",
    ),
    Mutation(
        name="a-stamp-without-a-digest-becomes-drift",
        file="engine/reconcile.py",
        search='    recorded = _text(getattr(stamp, "declaration_digest", None))\n    if not recorded:',
        replace='    recorded = _text(getattr(stamp, "declaration_digest", None))\n    if False:',
        test="tests.test_reconcile.TheMachineCanBeBehindTheFile"
             ".test_a_stamp_without_a_digest_is_not_turned_into_drift",
        scar="a comparison that never happened is reported as its outcome",
    ),
    # And the fixture side of the same lesson: the value was a placeholder for
    # as long as nothing read it, and two placeholders matching each other
    # proved nothing about the claim a stamp makes.
    Mutation(
        name="the-fixture-stamp-goes-back-to-a-placeholder",
        file="tests/conftest.py",
        search="            return model.declaration_digest(model.load_declaration(path))",
        replace='            return "sha256:" + "a" * 64',
        test="tests.test_reconcile.TheMachineCanBeBehindTheFile"
             ".test_an_untouched_declaration_is_not_called_drift",
        scar="every correctly provisioned run in the suite would report drift, "
             "which is how the check gets deleted as a false alarm",
    ),
    # The runner's own verdict, again. A case whose METHOD carries a docstring
    # is printed over two lines and the second one names nothing.
    Mutation(
        name="a-documented-case-loses-its-name",
        file="scripts/tests/tally.awk",
        search="/^test[^ ]* \\(.*\\)$/ { pending = ident($2); next }",
        replace="",
        test="tests.test_runner.TheTally"
             ".test_a_documented_case_is_named_by_its_identifier_not_its_prose",
        scar="a case that carries its own reason cannot be found by name in the "
             "transcript, so the one test that explains itself is the one you "
             "cannot look up",
    ),
    Mutation(
        name="a-documented-verdict-is-filed-under-its-prose",
        file="scripts/tests/tally.awk",
        search="  if ($2 ~ /^\\(.*\\)$/) s = ident($2)\n  else                  s = pending",
        replace="  s = ident($2)",
        test="tests.test_runner.TheTally"
             ".test_a_documented_failure_hiding_behind_a_documented_pass_is_still_red",
        scar="two cases opening with the same two words become one, the later "
             "verdict is dropped as a duplicate, and a FAIL behind a PASS exits 0",
    ),
    # The page while somebody is READING it, which is a different question from
    # the page while it is being made.
    Mutation(
        name="the-age-is-computed-once-and-frozen",
        file="engine/view.py",
        search="    tell();\n    setInterval(tell, 30000);",
        replace="    tell();",
        test="tests.test_view.ATabLeftOpenTellsTheTruth"
             ".test_the_age_is_recomputed_while_the_tab_stays_open",
        scar="a tab left open says `just now` at three in the morning and never "
             "reveals its stale banner, which is louder than saying nothing",
    ),
    Mutation(
        name="the-page-polls-at-a-rate-nobody-declared",
        file="engine/view.py",
        search="    if (poll > 0 && typeof fetch === 'function') {",
        replace="    if (typeof fetch === 'function') {",
        test="tests.test_view.ATabLeftOpenTellsTheTruth"
             ".test_without_a_declared_cadence_the_page_never_asks_for_a_newer_copy",
        scar="the same invented number the staleness verdict refuses to draw, "
             "only this one also costs a request every time it fires",
    ),
    Mutation(
        name="an-unreadable-answer-counts-as-newer",
        file="engine/view.py",
        search="  if (isNaN(mine) || isNaN(theirs)) { return false; }",
        replace="  if (isNaN(mine) || isNaN(theirs)) { return true; }",
        test="tests.test_view.ATabLeftOpenTellsTheTruth"
             ".test_an_answer_that_is_not_newer_is_not_reloaded_on",
        scar="a page that is still saying something true is thrown away for "
             "whatever the server happened to hand back",
    ),
    Mutation(
        name="the-poll-looks-for-a-marker-the-renderer-never-writes",
        file="engine/view.py",
        search="""  var key = 'id="stamp" datetime="';""",
        replace="""  var key = 'data-stamp="';""",
        test="tests.test_view.ATabLeftOpenTellsTheTruth"
             ".test_the_page_finds_the_moment_in_a_real_rendering_of_itself",
        scar="renderer and reader are two derivations of one marker; the page "
             "would simply stop refreshing, silently and forever",
    ),
    # Which of several times a finding is about. Prose is not an interface.
    Mutation(
        name="a-verdict-forgets-which-time-it-is-about",
        file="engine/reconcile.py",
        search="                       detail=detail, hint=hint, source=source,\n                       appointment=appointment_name)",
        replace='                       detail=detail, hint=hint, source=source,\n                       appointment="")',
        test="tests.test_reconcile.AFindingSaysWhichAppointmentItIsAbout"
             ".test_each_unit_of_a_run_names_its_own_appointment",
        scar="two units produce verdicts that cannot be told apart by field, so "
             "anything routing or dampening per unit has to parse a sentence",
    ),
    Mutation(
        name="a-failed-run-does-not-say-which-time-failed",
        file="engine/reconcile.py",
        search="                    hint=hint, source=source, appointment=appointment_name),",
        replace='                    hint=hint, source=source, appointment=""),',
        test="tests.test_reconcile.AFindingSaysWhichAppointmentItIsAbout"
             ".test_a_trace_finding_carries_the_appointment_too",
        scar="the midday run failed and the morning one did not, and the finding "
             "cannot say which; that is the one fact somebody woken by it needs",
    ),
    # The sender. Its return value is the only thing standing between a
    # dampened watchdog and a silent one.
    Mutation(
        name="any-exit-counts-as-delivered",
        file="engine/notify.py",
        search="    if rc == 0:",
        replace="    if rc is not None:",
        test="tests.test_notify.TheSenderSpeaksTheWordsItWasGiven"
             ".test_a_non_zero_exit_is_not_delivered",
        scar="a failed send starts the backoff, so the next hours are silent and "
             "nobody was ever told; three months of exactly this are on record",
    ),
    Mutation(
        name="a-crash-counts-as-delivered",
        file="engine/notify.py",
        search='        return Sent(False, f"{type(exc).__name__}: {exc}", tuple(argv))',
        replace='        return Sent(True, f"{type(exc).__name__}: {exc}", tuple(argv))',
        test="tests.test_notify.TheSenderSpeaksTheWordsItWasGiven"
             ".test_a_program_that_is_not_there_is_reported_and_never_raised",
        scar="a missing script reads as a delivered message, which is the worst "
             "of the three possible answers",
    ),
    Mutation(
        name="the-message-loses-part-of-its-declared-template",
        file="engine/notify.py",
        search='    argv = [fill(part) for part in (spec or {}).get("command", ())]',
        replace='    argv = [fill(part) for part in (spec or {}).get("command", ())][:1]',
        test="tests.test_notify.TheSenderSpeaksTheWordsItWasGiven"
             ".test_every_element_of_the_template_reaches_the_program",
        scar="the program is called with its name and nothing else; a call "
             "missing part of its template is not a message but an error nobody "
             "sees. The flags used to be a literal here and the needle pointed "
             "at that literal, so it went hollow the moment they became config",
    ),
    Mutation(
        name="a-value-with-a-space-is-split-into-two-arguments",
        file="engine/notify.py",
        search='    argv = [fill(part) for part in (spec or {}).get("command", ())]',
        replace='    argv = " ".join(fill(part) for part in (spec or {}).get("command", ())).split()',
        test="tests.test_notify.TheSenderSpeaksTheWordsItWasGiven"
             ".test_a_substituted_element_is_never_split_on_its_spaces",
        scar="a two word host becomes two arguments and the program reads the "
             "second as a flag",
    ),
    Mutation(
        name="an-empty-detail-still-sends-its-flag",
        file="engine/notify.py",
        search='    if values["detail"]:',
        replace='    if True:',
        test="tests.test_notify.TheSenderSpeaksTheWordsItWasGiven"
             ".test_the_detail_segment_is_dropped_when_there_is_no_detail",
        scar="a flag arrives with no value behind it and the program reads the "
             "next argument as its value",
    ),
    Mutation(
        name="an-unconfigured-alarm-path-is-invented-instead-of-reported",
        file="engine/notify.py",
        search="    if not raw:\n        return None",
        replace='    if not raw:\n        return {"command": ["bridge-notify.sh"], "detail": []}',
        test="tests.test_notify.TheAlarmPathIsDeclaredAndNeverGuessed"
             ".test_no_notifier_configured_is_an_answer_and_not_a_guess",
        scar="the skill acquires a dependency its own repository does not ship, "
             "which is exactly the shape this replaced",
    ),
    Mutation(
        name="the-off-switch-is-read-and-ignored",
        file="engine/config.py",
        search="    if cfg.enabled:\n        return",
        replace="    if True:\n        return",
        test="tests.test_cli.TheOffSwitchIsRealOrItIsNotDocumented"
             ".test_a_disabled_skill_refuses_every_subcommand",
        scar="an instance that switched the skill off keeps a provisioner that "
             "writes to its machines, and the handbook says otherwise",
    ),
    # The alarm layer: routing, dampening, and the state that carries it.
    Mutation(
        name="nothing-is-ever-actually-sent",
        file="engine/notify.py",
        search='            answer = sender(what=what, where=where, todo=todo, detail=detail)',
        replace='            answer = Sent(True)',
        test="tests.test_notify.TheBackoffIsBoundToDelivery.test_a_delivered_alarm_buys_silence",
        scar="the whole hole this change closes, reopened: the state records a message that was never handed to anybody",
    ),
    Mutation(
        name="the-backoff-starts-before-the-message-arrives",
        file="engine/notify.py",
        search='            if getattr(answer, "delivered", False):',
        replace='            if True:',
        test="tests.test_notify.TheBackoffIsBoundToDelivery.test_a_send_that_never_arrived_buys_nothing",
        scar="exactly the defect still live in claude-cli-health-guard.sh: both channels dead and the next hours quiet, having told nobody anything",
    ),
    Mutation(
        name="an-unreachable-host-counts-as-recovery",
        file="engine/notify.py",
        search='        if key.split("|", 1)[0] in unreachable:',
        replace='        if False:',
        test="tests.test_notify.UnknownNeitherStartsNorEndsAnEpisode.test_an_unreachable_pass_does_not_reopen_a_settled_alarm",
        scar="one flaky ssh hop tears a real ongoing incident in half and announces its second half as new",
    ),
    Mutation(
        name="one-silence-for-every-time-of-day",
        file="engine/notify.py",
        search='    return f"{finding.workload_id}|{getattr(finding, \'appointment\', \'\') or \'\'}|{bucket}"',
        replace='    return f"{finding.workload_id}|{bucket}"',
        test="tests.test_notify.OneKeyPerAppointment.test_the_morning_backoff_does_not_silence_the_midday_alarm",
        scar="the morning alarm buries the midday one under its backoff, and a report that answers at two times is simply never missed at the second",
    ),
    Mutation(
        name="the-day-has-no-ceiling",
        file="engine/notify.py",
        search='        room = cap - int(state.get("delivered_today") or 0)',
        replace='        room = cap',
        test="tests.test_notify.TheDailyCapCountsWhatArrived.test_the_cap_stops_at_the_number_it_names",
        scar="a runaway pass empties a phone, and the reader turns the channel off, which is the only failure mode worse than not sending at all",
    ),
    Mutation(
        name="the-loudest-verdict-waits-for-permission",
        file="engine/notify.py",
        search='    if state in WAKES_ALWAYS:',
        replace='    if False:',
        test="tests.test_notify.SomeThingsAreLouderThanTheDeclaration.test_a_retired_run_that_is_still_live_is_routed_with_an_empty_notify_on",
        scar="a retired run still live is possibly a security incident, and it would sit behind a field nobody edits on the way out",
    ),
    Mutation(
        name="a-flickering-daemon-pages-on-every-restart",
        file="engine/notify.py",
        search='PASSES_BEFORE_ALARM = {"stopped": 2}',
        replace='PASSES_BEFORE_ALARM = {}',
        test="tests.test_notify.OnlyStoppedNeedsASecondLook.test_a_stopped_daemon_needs_two_passes_in_a_row",
        scar="`stopped` is the one verdict read from a live measurement, and every ordinary restart would become an alarm",
    ),
    Mutation(
        name="every-incident-looks-like-the-same-one",
        file="engine/notify.py",
        search='    return hashlib.sha256(str(getattr(finding, "detail", "")).encode("utf-8")).hexdigest()[:16]',
        replace='    return "constant"',
        test="tests.test_notify.TheBackoffIsBoundToDelivery.test_a_new_incident_speaks_through_the_silence",
        scar="a second, genuinely new failure inside the backoff window is swallowed as though the first one were still standing",
    ),
    # REMOVED 2026-08-27 with the code it pointed at, and the battery is what
    # found it: the anchor matched zero times, so it had stopped proving
    # anything. It softened a search through two hardcoded filenames, and the
    # order of that search (the deployed copy before the repository copy,
    # because the working tree is pulled every five minutes and one broken
    # commit would otherwise silence both channels within a single cycle) is
    # instance policy. It is now written as the two paths it actually is, in
    # that instance's `workloads.notify_via`, where a reader can see it.
    Mutation(
        name="the-flag-reaches-nothing",
        file="engine/cli.py",
        search='    if getattr(args, "notify", False):',
        replace='    if False:',
        test="tests.test_cli.SilenceIsTheDefault.test_the_flag_is_what_turns_it_on",
        scar="a flag that exists and does nothing is this change's own defect one level up, and it reads as armed",
    ),
    # Which interpreter runs the skill at all. Measured 2026-08-25: on the
    # machine this skill exists to watch, it did not start.
    Mutation(
        name="the-first-python-on-path-is-taken-on-trust",
        file="workload.sh",
        search='        if can_run "$cand"; then PYTHON="$cand"; break; fi',
        replace='        PYTHON="$cand"; break',
        test="tests.test_launcher.TheLauncherPicksAnInterpreterThatCanActuallyRunIt"
             ".test_an_interpreter_that_cannot_run_the_skill_is_passed_over",
        scar="the first python3 on a non interactive PATH has no yaml there, so "
             "the whole watcher is absent and says nothing about being absent",
    ),
    Mutation(
        name="an-unusable-interpreter-dies-with-an-import-error",
        file="workload.sh",
        search='    can_run "$BRIDGE_PYTHON" || refuse',
        replace='    :',
        test="tests.test_launcher.TheLauncherPicksAnInterpreterThatCanActuallyRunIt"
             ".test_a_named_interpreter_that_cannot_run_it_says_what_is_missing",
        scar="a bare ModuleNotFoundError from the middle of an import chain "
             "sends the reader into the wrong file entirely",
    ),
    # A named host that turns out to be this machine.
    Mutation(
        name="a-marker-for-another-machine-is-accepted",
        file="engine/hosts.py",
        search="    here = bool(mine) and mine == slug",
        replace="    here = bool(mine)",
        test="tests.test_model.AMachineCanBeTheOneItIsAskedAbout"
             ".test_a_marker_naming_another_machine_changes_nothing",
        scar="one machine answers in another's name, which is the worst outcome "
             "this skill has: every verdict downstream reads the same",
    ),
    Mutation(
        name="a-local-read-happens-quietly",
        file="engine/reconcile.py",
        search='    return said + ". " + "; ".join(str(one) for one in read_locally)',
        replace="    return said",
        test="tests.test_reconcile.ALocalReadNeverHappensQuietly"
             ".test_the_report_header_names_the_machine_that_answered_for_itself",
        scar="the marker is a file a human writes, and a reader noticing is the "
             "cheapest guard there is against a wrong one",
    ),
    Mutation(
        name="a-trace-line-names-only-the-declaration",
        file="engine/backends/wrapper.py",
        search='        add(f"BRIDGE_WORKLOAD_TRACE_ID={shlex.quote(state_id)}")',
        replace='        add(f"BRIDGE_WORKLOAD_TRACE_ID={shlex.quote(safe_id)}")',
        test="tests.test_backends.SeveralAppointmentsBecomeSeveralUnits"
             ".test_a_trace_line_names_the_unit_and_not_only_the_declaration",
        scar="both units write sentences that read identically, so a line lifted "
             "out of its file cannot say which of two times it is about",
    ),
    Mutation(
        name="the-file-moving-is-said-once-per-unit",
        file="engine/reconcile.py",
        search="        if stamp is not None and not w.is_retired:",
        replace="        if False:",
        test="tests.test_reconcile.TheMachineCanBeBehindTheFile"
             ".test_a_run_with_two_units_reports_the_drift_once",
        scar="either the fact is lost entirely, or, back inside the unit loop, "
             "it is repeated once per appointment and the report starts "
             "repeating itself",
    ),
    Mutation(
        name="a-run-that-never-ends-is-asked-to-enforce-a-deadline",
        file="engine/model.py",
        search='    if w.execution.isolation == "process-group" and w.placement.kind not in CONTINUOUS_KINDS:',
        replace='    if w.execution.isolation == "process-group":',
        test="tests.test_provision.ARunThatNeverEndsHasNoDeadlineToEnforce"
             ".test_a_daemon_can_be_provisioned_at_all",
        scar="every daemon becomes unprovisionable again, and the refusal reads "
             "`degraded-backend`, which names the backend for a category error "
             "in the declaration: the guarantee enforces a deadline, and a run "
             "that never ends has none",
    ),
    Mutation(
        name="a-daemon-is-proved-by-a-loaded-label",
        file="engine/probe.py",
        search='    return _text(getattr(backend, "alive_expect", None)) or None',
        replace="    return None",
        test="tests.test_provision.ADaemonIsProvedByAProcessNotByALoadedLabel"
             ".test_a_loaded_corpse_is_not_a_running_daemon",
        scar="with no expect the return code decides, and `launchctl print` "
             "answers 0 for a unit the domain merely holds, so provision "
             "reports a dead daemon as verified",
    ),
    Mutation(
        name="every-run-is-asked-for-a-process",
        file="engine/probe.py",
        search="    if kind not in model.CONTINUOUS_KINDS:\n        return None",
        replace="    if False:\n        return None",
        test="tests.test_provision.ADaemonIsProvedByAProcessNotByALoadedLabel"
             ".test_a_run_that_ends_is_still_judged_by_its_return_code",
        scar="a scheduled run is idle between its fires and has no process, so "
             "demanding one would call every healthy report dead",
    ),

    # Vierter Durchgang: der Alarm, der die Messung ablehnt. Beide Nadeln
    # stand for one half of the rule each, because a gate that always fires
    # and one that never fires are the same defect in two directions.
    Mutation(
        name="an-alarm-may-refuse-its-reading",
        file="engine/cli.py",
        search='    if getattr(args, "notify", False) and getattr(args, "no_probe", False):',
        replace="    if False:",
        test="tests.test_cli.AnAlarmThatRefusesToMeasureIsAPromiseWithoutAFloor"
             ".test_notifying_without_probing_is_refused",
        scar="the half-hourly refresher carried --notify and --no-probe "
             "together, so a declared probe reached a page and never an alarm",
    ),
    Mutation(
        name="the-pair-is-refused-even-with-nothing-to-measure",
        file="engine/cli.py",
        search="        named = _declared_probes(root, cfg, args)\n        if named:",
        replace="        named = _declared_probes(root, cfg, args) or ('nothing',)\n        if named:",
        test="tests.test_cli.AnAlarmThatRefusesToMeasureIsAPromiseWithoutAFloor"
             ".test_without_a_declared_probe_the_flags_do_not_contradict",
        scar="a rule about nothing refuses a pair that takes nothing away, and "
             "teaches the reader it is forbidden until the day a probe appears",
    ),
    Mutation(
        name="the-filter-widens-instead-of-narrowing",
        file="engine/view.py",
        search="    if (!hit) { return false; }",
        replace="    if (!hit) { return true; }",
        test="tests.test_view.TheFilterIsArithmeticAndNotDecoration"
             ".test_facets_are_and_across_each_other",
        scar="two facets that OR instead of AND turn every added filter into a "
             "wider result, so a reader narrowing down to one kind on one host "
             "gets more rows with each click and reads the extra ones as matches",
    ),
    Mutation(
        name="an-unfiltered-page-hides-rows",
        file="engine/view.py",
        search="    if (!want || !want.length) { continue; }",
        replace="    if (!want) { continue; }",
        test="tests.test_view.TheFilterIsArithmeticAndNotDecoration"
             ".test_nothing_chosen_matches_everything",
        scar="an empty choice is not a filter. Treated as one it matches "
             "nothing, and the page a reader opens after clearing the filters "
             "is blank with no explanation on it",
    ),
    Mutation(
        name="a-facet-with-one-value-becomes-furniture",
        file="engine/view.py",
        search="        if len(counts) < 2:",
        replace="        if len(counts) < 1:",
        test="tests.test_view.TheFacetBarIsBuiltFromWhatIsThere"
             ".test_a_facet_with_one_value_is_not_drawn",
        scar="a row of buttons offering the single answer every run gives is "
             "not a filter. It teaches a reader that the bar does nothing, and "
             "the day a real facet appears it is read as more of the same",
    ),
    Mutation(
        name="the-filter-bar-appears-before-anything-can-use-it",
        file="engine/view.py",
        # Retargeted 2026-08-27: the bar gained a heading of its own, so the
        # needle grips the attribute rather than the whole line.
        search='''<div class="facets" id="facets" hidden>''',
        replace='''<div class="facets" id="facets">''',
        test="tests.test_view.TheFacetBarIsBuiltFromWhatIsThere"
             ".test_the_bar_ships_hidden",
        scar="without scripting the buttons are dead. A dead control on a page "
             "is worse than no control: a reader clicks it, nothing happens, "
             "and they conclude the data is wrong rather than the page",
    ),
    Mutation(
        name="a-framed-neighbour-passes-as-this-pages-own-reading",
        file="engine/view.py",
        search="""            f'<p class="meta">{PANELS_NOTE} '""",
        replace="""            f'<p class="meta">'""",
        test="tests.test_view.AFramedNeighbourIsShownAndNotAdopted"
             ".test_the_panel_says_it_measured_nothing",
        scar="a page framed inside a dashboard is read as vouched for by the "
             "dashboard. Without the sentence this page would be asserting a "
             "neighbour's numbers, which is the one thing it must never do",
    ),
    Mutation(
        name="the-day-leaves-the-row-it-belongs-to",
        file="engine/view.py",
        # Retargeted twice. The second list is GONE: the day is a column of the
        # run's own row, so a lane can no longer be left standing for a row a
        # filter took away. What is worth attacking now is that the day is in
        # the row at all, which is what closed that whole class of defect.
        search='f\'<td class="day">{_track_html(lane, on)}</td>\'',
        replace="''",
        test="tests.test_view.TheFacetBarIsBuiltFromWhatIsThere"
             ".test_a_run_is_on_the_page_exactly_once_and_carries_its_own_day",
        scar="the run's day is somewhere else on the page or nowhere, and a "
             "reader is back to matching two lists by name to answer one "
             "question about one run",
    ),

    # ── the shell: one place, and progressive all the way down.
    Mutation(
        name="a-framed-neighbour-goes-back-under-the-table",
        file="engine/view.py",
        search='f\'<section class="view" id="{vid}" aria-label="{_esc(label)}">\'',
        replace='f\'<section id="{vid}" aria-label="{_esc(label)}">\'',
        test="tests.test_view.TheShellIsOnePlaceAndNotAStack"
             ".test_a_framed_neighbour_is_a_view_of_its_own",
        scar="a neighbour that is not a view is a letterbox at the foot of "
             "somebody else's document: its own header, its own navigation and "
             "its own scrollbar squeezed into a strip, which is the reading "
             "that came back as everything having been crammed in",
    ),
    Mutation(
        name="a-tab-opens-a-view-that-is-not-there",
        file="engine/view.py",
        search="""    items += [f'<a href="#{vid}" data-view="{vid}">{_esc(label)}</a>'""",
        replace="""    items += [f'<a href="#{vid}" data-view="{vid}-x">{_esc(label)}</a>'""",
        test="tests.test_view.TheShellIsOnePlaceAndNotAStack"
             ".test_every_tab_names_a_view_and_every_view_has_a_tab",
        scar="the bar and the sections disagree about what exists, so a tab "
             "either opens nothing or a whole view can be reached by no control "
             "on the page",
    ),
    Mutation(
        name="the-shell-ships-four-fifths-of-the-page-hidden",
        file="engine/view.py",
        search='f\'<section class="view" id="{vid}" aria-label="{_esc(label)}">\'',
        replace='f\'<section class="view" hidden id="{vid}" aria-label="{_esc(label)}">\'',
        test="tests.test_view.TheShellIsOnePlaceAndNotAStack"
             ".test_nothing_is_hidden_before_a_script_runs",
        scar="a reader without scripting loses every framed page, and the "
             "document that used to be complete is now a fragment with a bar "
             "above it that does nothing",
    ),
    Mutation(
        name="two-views-share-one-identifier",
        file="engine/view.py",
        search="""    candidate, n = stem, 2
    while candidate in taken:""",
        replace="""    candidate, n = stem, 2
    while False:""",
        test="tests.test_view.TheShellIsOnePlaceAndNotAStack"
             ".test_two_labels_that_slugify_alike_stay_two_views",
        scar="two labels that differ only in case or punctuation collapse to "
             "one anchor, and the second view can never be opened; the bar "
             "still shows its tab, so the page looks complete",
    ),
    Mutation(
        name="the-first-tab-loses-the-name-the-caller-chose",
        file="engine/view.py",
        search='"Workloads</span>" + _tabs_html(views, overview_label or OVERVIEW_LABEL)',
        replace='"Workloads</span>" + _tabs_html(views)',
        test="tests.test_view.TheShellIsOnePlaceAndNotAStack"
             ".test_the_first_tab_can_be_named_by_the_caller",
        scar="the bar carries exactly one word out of this file, in this "
             "file's language, next to labels in the reader's",
    ),
    # ── the day: a picture may not assert a beat nobody measured.
    Mutation(
        name="the-cadence-band-beats-again",
        file="engine/view.py",
        # Retargeted 2026-08-27: the rail grew end caps and a weight it can
        # actually be seen at, so the old literal named nothing and the needle
        # was proving nothing while reading green.
        search=""".band.cadence { top: 50%; height: 3px; transform: translateY(-50%);
                background: var(--info); opacity: .85; }""",
        replace=""".band.cadence { top: 30%; bottom: 30%;
                background: repeating-linear-gradient(90deg,
                    var(--info) 0 3px, transparent 3px 14px); opacity: .55; }""",
        test="tests.test_view.TheDayDrawsNoBeatItDidNotMeasure"
             ".test_a_cadence_band_repeats_nothing",
        scar="roughly a hundred evenly spaced marks per lane, the same hundred "
             "for a run every five minutes and a run every hour, which a reader "
             "counts as firings; ten such lanes read as static and the two marks "
             "that were actually measured are lost in it",
    ),
    Mutation(
        name="a-section-heading-counts-the-whole-table",
        file="engine/view.py",
        # Retargeted 2026-08-27: the groups are sections of the table now.
        # Retargeted 2026-09-04: the section list is computed, so the loop hands
        # over a key and its own rows instead of iterating LANE_GROUPS.
        search="""        body.append(_group_head_html(key, title, len(here), on,
                                     with_scale=with_scale))""",
        replace="""        body.append(_group_head_html(key, title, len(in_service), on,
                                     with_scale=with_scale))""",
        test="tests.test_view.TheDayDrawsNoBeatItDidNotMeasure"
             ".test_a_section_counts_only_the_runs_under_it",
        scar="every heading claims the whole day, so three groups of five, ten "
             "and eight all say twenty-three and a reader reads the axis three "
             "times over",
    ),
    Mutation(
        name="the-columns-stop-declaring-their-share",
        file="engine/view.py",
        # Retargeted 2026-08-27 with the shares themselves: the day took the
        # largest of them and the history gave one back.
        search="""'<colgroup><col style="width:26%"><col style="width:36%">'
                '<col style="width:22%"><col style="width:16%"></colgroup>'""",
        replace='""',
        test="tests.test_view.ASentenceIsNotAnIdentifier"
             ".test_a_long_purpose_is_bounded_so_it_cannot_dominate_the_row",
        scar="four columns share the page by content again, three of them hold "
             "one short token each, and the identifier column is squeezed to a "
             "quarter of the measure with every purpose wrapped over four lines",
    ),
    Mutation(
        name="six-identical-verdicts-become-one-and-say-nothing",
        file="engine/view.py",
        search="""            + (f'<span class="times">×{n}</span>' if n > 1 else "")""",
        replace='            + ""',
        test="tests.test_view.TheRunKeepsItsFactsWithoutTenColumns"
             ".test_repeated_verdicts_are_counted_and_never_dropped",
        scar="a run answering at six appointments reads exactly like one "
             "answering at one, so five healthy firings vanish from the page "
             "while the row still looks complete",
    ),
    Mutation(
        name="the-head-is-pinned-inside-its-own-scroll-container",
        file="engine/view.py",
        search="thead th { background: var(--surface); }",
        replace="""thead th { position: sticky; top: var(--topbar); z-index: 6;
           background: var(--surface); }""",
        test="tests.test_view.TheRunKeepsItsFactsWithoutTenColumns"
             ".test_the_head_is_not_pinned_inside_its_own_scroll_container",
        scar="the table sits in a container with overflow-x, which makes it its "
             "own scroll container: the head then sticks to THAT box and is "
             "pinned 3.5rem into the table, covering the first section heading",
    ),
    Mutation(
        name="a-section-count-outlives-its-own-rows",
        file="engine/view.py",
        search='f\'(<span class="n" data-total="{count}">{count}</span>)\'',
        replace='f"({count})"',
        test="tests.test_view.TheDayDrawsNoBeatItDidNotMeasure"
             ".test_a_section_count_is_an_element_the_filter_can_correct",
        scar="a literal cannot be corrected by a filter, so a heading keeps "
             "saying eight above the three rows it has left, which is a number "
             "contradicted by the very thing under it",
    ),
    Mutation(
        name="the-machines-own-units-go-back-into-the-number",
        file="engine/view.py",
        search="            if prefixes and name.startswith(prefixes):",
        replace="            if False:",
        test="tests.test_view.TheMachinesOwnUnitsAreNamedAndNotOnlyCounted"
             ".test_a_configured_prefix_is_named",
        scar="the services somebody actually put on the machine disappear into "
             "a count of nineteen hundred, which is the state this page was in "
             "when its reader went looking for them on a neighbouring page",
    ),
    Mutation(
        name="the-operating-system-is-listed-too",
        file="engine/view.py",
        search="            if prefixes and name.startswith(prefixes):",
        replace="            if True:",
        test="tests.test_view.TheMachinesOwnUnitsAreNamedAndNotOnlyCounted"
             ".test_everything_else_stays_a_number",
        scar="eighteen hundred rows of the operating system's own units, which "
             "is not a longer page but an unreadable one",
    ),
    # ——— The day made legible, 2026-08-27 ————————————————————————————
    # The reader's verdict on the rebuilt page was that the timeline was not
    # visible enough, and measuring it agreed: 270 pixels for twenty-four
    # hours, one ruler at the top that the first scroll took away, two bands
    # drawn so faintly they were the ground, and an appointment section sorted
    # by name. Every one of those is a decision here rather than a taste, so
    # every one gets a needle.
    Mutation(
        name="the-day-is-the-narrow-column-again",
        file="engine/view.py",
        search='<col style="width:26%"><col style="width:36%">',
        replace='<col style="width:36%"><col style="width:26%">',
        test="tests.test_view.TheDayIsTheWidestThingOnThePage"
             ".test_the_day_gets_more_of_the_page_than_any_other_column",
        scar="twenty-four hours in the narrowest usable column of a table "
             "whose subject they are",
    ),
    Mutation(
        name="the-history-takes-the-width-back",
        file="engine/view.py",
        search=".strip { letter-spacing: .04em; font-size: .8125rem;",
        replace=".strip { letter-spacing: .12em; font-size: .9375rem;",
        test="tests.test_view.TheDayIsTheWidestThingOnThePage"
             ".test_the_history_is_set_small_enough_to_stop_taking_the_width",
        scar="a row of identical dots with a hard floor of 365px, taking a "
             "third of the table from the day beside it",
    ),
    Mutation(
        name="the-track-is-thinner-than-its-marks",
        file="engine/view.py",
        search=".track { position: relative; height: 2rem;",
        replace=".track { position: relative; height: 1rem;",
        test="tests.test_view.TheDayIsTheWidestThingOnThePage"
             ".test_the_track_is_tall_enough_for_the_marks_it_carries",
        scar="a diamond standing taller than the day it is supposed to sit in",
    ),
    Mutation(
        name="the-measure-goes-back-to-a-literal",
        file="engine/view.py",
        search=".wrap { max-width: var(--max);",
        replace=".wrap { max-width: 62rem;",
        test="tests.test_view.TheDayIsTheWidestThingOnThePage"
             ".test_the_page_is_given_the_measure_the_table_needs",
        scar="a measure on which no share of the page makes the day a day",
    ),
    Mutation(
        name="one-ruler-at-the-top-again",
        file="engine/view.py",
        # Retargeted 2026-09-04: the ruler follows the section's own answer
        # instead of being re-derived from the band, because on the system
        # axis any section can hold runs that are not on the day.
        search='    scale = "" if not with_scale else (',
        replace='    scale = "" and (',
        test="tests.test_view.TheRulerStaysWithinReachOfItsTracks"
             ".test_every_section_that_draws_a_day_carries_its_own_ruler",
        scar="a reference the first scroll takes away, on a table that cannot "
             "pin it because it is its own scroll container",
    ),
    Mutation(
        name="a-ruler-over-the-runs-that-are-not-on-the-day",
        file="engine/view.py",
        # Retargeted 2026-09-04: the ruler follows the section's own answer
        # instead of being re-derived from the band, because on the system
        # axis any section can hold runs that are not on the day.
        search='    scale = "" if not with_scale else (',
        replace='    scale = "" if False else (',
        test="tests.test_view.TheRulerStaysWithinReachOfItsTracks"
             ".test_the_section_that_places_nothing_carries_no_ruler",
        scar="an hour scale over cells that hold a sentence, inviting the "
             "reading that they are somewhere on it",
    ),
    Mutation(
        name="the-zone-is-taken-from-whoever-is-looking",
        file="engine/view.py",
        search="    zone = zones[0] if len(zones) == 1 else \"\"",
        replace="    zone = zones[0] if zones else \"\"",
        test="tests.test_view.NowComesFromTheMachinesZoneAndNeverTheReaders"
             ".test_a_page_whose_declarations_disagree_states_no_zone",
        scar="one upright line across runs keeping two zones, right for at "
             "most one of them and identical in both",
    ),
    Mutation(
        name="an-unreadable-clock-is-placed-anyway",
        file="engine/view.py",
        search="  if (h > 24 || min > 59) { return null; }",
        replace="  if (false) { return null; }",
        test="tests.test_view.NowComesFromTheMachinesZoneAndNeverTheReaders"
             ".test_the_axis_arithmetic_refuses_what_it_cannot_read",
        scar="a line at a guessed hour, indistinguishable from a measured one",
    ),
    Mutation(
        name="the-hour-comes-from-the-readers-own-offset",
        file="engine/view.py",
        search="      timeZone: zone, hour: '2-digit', minute: '2-digit', hour12: false",
        replace="      hour: '2-digit', minute: '2-digit', hour12: false",
        test="tests.test_view.NowComesFromTheMachinesZoneAndNeverTheReaders"
             ".test_the_hour_is_the_machines_and_not_the_readers",
        scar="a now line that is right in one office and hours out in the next",
    ),
    Mutation(
        name="the-now-line-is-rendered-by-the-server",
        file="engine/view.py",
        search="        f'<td class=\"day\">{_track_html(lane, on)}</td>'",
        replace="        f'<td class=\"day\">{_track_html(lane, on)}"
                "<span class=\"nowline\"></span></td>'",
        test="tests.test_view.NowComesFromTheMachinesZoneAndNeverTheReaders"
             ".test_the_line_is_never_in_the_document_the_server_wrote",
        scar="a line frozen at the moment the page was written, looking "
             "exactly like a live one",
    ),
    Mutation(
        name="the-appointments-are-sorted-by-name-again",
        file="engine/view.py",
        search="    order = getattr(lane, \"order\", None) if lane is not None else None",
        replace="    order = None",
        test="tests.test_view.TheCalendarSectionReadsInClockOrder"
             ".test_an_appointment_section_is_ordered_by_the_hour_it_fires",
        scar="a calendar section in which a 00:30 job sits below a 06:10 one, "
             "so the marks scatter down the column instead of walking across it",
    ),
    Mutation(
        name="a-beat-is-sorted-by-the-words-of-its-label",
        file="engine/view.py",
        search="                            order=float(every) if every else None,",
        replace="                            order=None,",
        test="tests.test_view.TheCalendarSectionReadsInClockOrder"
             ".test_a_beat_is_ordered_by_its_period_and_not_by_its_name",
        scar="every 3600s standing above every 300s",
    ),
    Mutation(
        name="six-appointments-are-six-ands",
        file="engine/view.py",
        search="    return \", \".join(parts[:-1]) + \" and \" + parts[-1]",
        replace="    return \" and \".join(parts)",
        test="tests.test_view.AScheduleOfSixTimesIsAListAndNotSixAnds"
             ".test_more_than_two_become_a_list",
        scar="a schedule the eye leaves after the third time",
    ),
    Mutation(
        name="one-refusal-takes-the-whole-page-down",
        file="engine/view.py",
        search="            marks = []\n            for appointment, hour, minute, shift in placed:",
        replace="            marks = []\n            pass\n        for appointment, hour, minute, shift in placed:",
        test="tests.test_view.ARefusalCostsItsOwnRunASentenceAndNotThePage"
             ".test_the_rest_of_the_page_survives_it",
        scar="one declaration nothing could express in weekdays taking every "
             "other run on the page with it",
    ),
    Mutation(
        name="the-undeclared-units-repeat-one-sentence",
        file="engine/view.py",
        search="            body.append(_units_grid_html(other))",
        replace="            body.append(_finding_table(other))",
        test="tests.test_view.TheMachinesOwnUnitsAreNamedAndNotOnlyCounted"
             ".test_the_same_sentence_is_not_repeated_once_per_unit",
        scar="eleven hundred pixels of one sentence in a section that is "
             "context rather than subject",
    ),
    Mutation(
        name="the-undeclared-units-arrive-in-no-order",
        file="engine/view.py",
        search="        group = sorted(by_state[state],\n                       key=lambda f: getattr(f, \"workload_id\", \"\"))",
        replace="        group = list(by_state[state])",
        test="tests.test_view.TheMachinesOwnUnitsAreNamedAndNotOnlyCounted"
             ".test_the_names_are_in_an_order_a_reader_can_use",
        scar="thirty names in whatever order a service manager returned them",
    ),
    Mutation(
        name="a-name-loses-the-sentence-that-explains-it",
        file="engine/view.py",
        search='            f\'<li title="{_esc(getattr(f, "detail", ""))}">\'',
        replace="            '<li>'",
        test="tests.test_view.TheMachinesOwnUnitsAreNamedAndNotOnlyCounted"
             ".test_every_name_keeps_its_own_sentence",
        scar="a name with nothing saying why it is on the page, which is a "
             "sentence dropped rather than a repetition removed",
    ),
    Mutation(
        name="the-day-is-one-flat-ground-again",
        file="engine/view.py",
        search="             linear-gradient(90deg, var(--surface-muted) 0 25%,",
        replace="             linear-gradient(90deg, var(--surface) 0 25%,",
        test="tests.test_view.TheDayIsTheWidestThingOnThePage"
             ".test_the_hours_at_each_end_stand_on_their_own_ground",
        scar="twenty-four hours ruled evenly, on which midday can only be "
             "found by counting ticks from the left",
    ),
    Mutation(
        name="the-note-names-which-ground-is-darker",
        file="engine/view.py",
        search='                    "of their own so the middle of the day is found without "',
        replace='                    "which is darker so the middle of the day is found without "',
        test="tests.test_view.TheDayIsTheWidestThingOnThePage"
             ".test_the_page_never_names_which_ground_is_darker",
        scar="a sentence that reads perfectly and is the wrong way round for "
             "every reader on the dark theme",
    ),
    # ——— Taken from the operations page next door, 2026-08-27 ————————
    # The reader's call: two pages carrying contradicting numbers about one
    # machine should not stand side by side, so the ideas came over and the
    # numbers did not. The first of them stops a FALSE CLAIM rather than
    # improving a view, and it is the loudest verdict this skill has.
    Mutation(
        name="an-appointment-in-the-dark-is-still-overdue",
        file="engine/reconcile.py",
        # Retargeted 2026-08-27: the guard moved out of the top of its
        # function, so the old literal named nothing.
        search="    if booted is not None and booted > due:\n        return cannot_judge()",
        replace="    if False:\n        return cannot_judge()",
        test="tests.test_reconcile.TheMachineHasToHaveBeenUp"
             ".test_an_appointment_that_fell_while_the_machine_was_off_is_not_overdue",
        scar="a run reported as having missed an appointment that fell while "
             "the machine was off, at severity high, with an instruction to "
             "reload a unit that is perfectly fine",
    ),
    Mutation(
        name="every-appointment-is-in-the-dark",
        file="engine/reconcile.py",
        # Retargeted 2026-08-27: the guard moved out of the top of its
        # function, so the old literal named nothing.
        search="    if booted is not None and booted > due:\n        return cannot_judge()",
        replace="    if booted is not None:\n        return cannot_judge()",
        test="tests.test_reconcile.TheMachineHasToHaveBeenUp"
             ".test_a_machine_that_was_up_the_whole_time_is_still_judged",
        scar="a guard that silences the loudest verdict in the skill for every "
             "run on a machine that has been up for a month",
    ),
    Mutation(
        name="the-machine-being-off-is-a-silence",
        file="engine/reconcile.py",
        # The FINDING, not its hint: the test measures the sentence and the
        # state, and a needle that empties a field neither of them reads is a
        # needle proving nothing. Corrected 2026-08-27, by the battery.
        # Retargeted 2026-08-27: the guard moved out of the top of its
        # function, so the old literal named nothing.
        search="    if booted is not None and booted > due:\n        return cannot_judge()",
        replace="    if booted is not None and booted > due:\n        return []",
        test="tests.test_reconcile.TheMachineHasToHaveBeenUp"
             ".test_it_says_so_rather_than_falling_silent",
        scar="a run nobody can judge with nothing saying what to do about it",
    ),
    Mutation(
        name="a-cadence-is-judged-against-a-machine-that-just-booted",
        file="engine/reconcile.py",
        # Retargeted 2026-08-27: the guard moved out of the top of its
        # function, so the old literal named nothing.
        search="        return (booted is not None\n                and (now - booted).total_seconds() < limit)",
        replace="        return False",
        test="tests.test_reconcile.TheMachineHasToHaveBeenUp"
             ".test_a_cadence_is_not_judged_before_the_machine_has_been_up_that_long",
        scar="every job on the box reported overdue for the first half hour "
             "after a reboot, which is when a report most needs to be readable",
    ),
    Mutation(
        name="an-unreadable-boot-moment-is-guessed",
        file="engine/reconcile.py",
        search='    if not found:\n        return ""\n    try:\n        moment = datetime.fromtimestamp',
        replace='    if not found:\n        return "1970-01-01T00:00:00Z"\n    try:\n        moment = datetime.fromtimestamp',
        test="tests.test_reconcile.WhenDidThisMachineComeUp"
             ".test_nothing_readable_is_empty_and_never_a_guess",
        scar="a machine that would not answer treated as one that has been up "
             "since 1970",
    ),
    Mutation(
        name="the-boot-moment-is-read-and-dropped",
        file="engine/reconcile.py",
        search="    booted = read_boot_time(h, timeout_sec=timeout_sec, runner=runner)",
        replace='    booted = ""',
        test="tests.test_reconcile.WhenDidThisMachineComeUp"
             ".test_the_observation_carries_it",
        scar="the machine asked when it came up and the answer going nowhere",
    ),
    Mutation(
        name="the-page-shades-a-day-no-clock-measured",
        file="engine/view.py",
        search="                left: var(--now, 100%); z-index: 0;",
        replace="                left: var(--now, 50%); z-index: 0;",
        test="tests.test_view.TheDayShowsWhereItHasGotTo"
             ".test_nothing_is_shaded_before_a_clock_has_run",
        scar="a page without scripting asserting where the day has got to, "
             "out of a moment nobody took",
    ),
    Mutation(
        name="half-the-drawing-goes-unexplained",
        file="engine/view.py",
        search='"and the ground behind it is the part of the day that has not "',
        replace='"and it is drawn by your browser. "',
        test="tests.test_view.TheDayShowsWhereItHasGotTo"
             ".test_the_ground_it_draws_is_accounted_for",
        scar="a shading a reader can mistake for data, with nothing on the "
             "page accounting for it",
    ),
    Mutation(
        name="the-age-ships-as-an-attribute-only",
        file="engine/view.py",
        search='f\'datetime="{_esc(lane.trace_at)}">{_esc(lane.trace_at)}</time>\'',
        replace='f\'datetime="{_esc(lane.trace_at)}"></time>\'',
        test="tests.test_view.AStampBecomesADistance"
             ".test_the_absolute_stamp_is_what_ships",
        scar="an empty line where the answer should be, for every reader "
             "without scripting",
    ),
    Mutation(
        name="the-instruction-is-computed-and-dropped-again",
        file="engine/view.py",
        search='        + (f\'<div class="todo">{_esc(getattr(f, "hint", ""))}</div>\'',
        replace='        + (f\'<div class="todo"></div>\'',
        test="tests.test_view.ThePageOpensWithWhatNeedsAPerson"
             ".test_the_skills_own_instruction_reaches_the_runs_own_row",
        scar="this skill's own sentence about what to do next, computed for "
             "every finding and reaching no reader, which is where it sat "
             "until 2026-08-27",
    ),
    Mutation(
        name="an-empty-box-instead-of-an-all-clear",
        file="engine/view.py",
        search='        return (\'<p class="banner" id="allclear"><strong>Nothing here needs a \'',
        replace='        return (\'<section class="open"><ul></ul></section>\' + \'<p hidden id="allclear"><strong>Nothing here needs a \'',
        test="tests.test_view.ThePageOpensWithWhatNeedsAPerson"
             ".test_information_alone_is_a_sentence_and_not_an_empty_box",
        scar="an empty box that teaches a reader to skip the one place on the "
             "page that will one day not be empty",
    ),
    Mutation(
        name="the-answer-arrives-under-the-inventory",
        file="engine/view.py",
        search="    if declared:\n        body.append(_open_html(in_service))",
        replace="    if False:\n        body.append(_open_html(in_service))",
        test="tests.test_view.ThePageOpensWithWhatNeedsAPerson"
             ".test_the_answer_stands_above_the_table_as_a_count",
        scar="a page that opens with an inventory, leaving a reader to work "
             "out whether anything is wrong across twenty-five rows",
    ),
    Mutation(
        name="the-shortcut-names-a-facet-that-is-not-there",
        file="engine/view.py",
        # Umgezogen 2026-09-04 aus `the-anchor-is-derived-twice`. Die Liste
        # ueber der Tabelle ist weg, mit ihr der Link und damit die ZWEITE
        # Ableitung des Ankers, die jene Nadel bewacht hat. Der Defekt kann
        # baulich nicht mehr auftreten, die NAHT aber schon: die Abkuerzung
        # im Banner muss eine Pille benennen, die die Leiste wirklich
        # gezeichnet hat, sonst versteckt ein Druck darauf jede Zeile.
        search='data-value="{ATTENTION_OPEN}" aria-pressed="false">',
        replace='data-value="needs-a-person-x" aria-pressed="false">',
        test="tests.test_view.ThePageOpensWithWhatNeedsAPerson"
             ".test_the_shortcut_names_a_pill_the_bar_actually_carries",
        scar="ein Knopf, der eine Facette benennt, die es nicht gibt: ein "
             "Druck darauf versteckt jede Zeile und die Tabelle sieht leer aus",
    ),
    Mutation(
        name="the-haystack-keeps-its-case",
        file="engine/view.py",
        search='    haystack = " ".join(str(part).lower() for part in (',
        replace='    haystack = " ".join(str(part) for part in (',
        test="tests.test_view.AReaderCanLookForAWordThePillsDoNotHave"
             ".test_every_run_carries_what_a_reader_would_type",
        scar="a search that only finds a word typed the way the declaration "
             "happened to spell it",
    ),
    Mutation(
        name="a-second-word-widens-the-search",
        file="engine/view.py",
        search="    if (text.indexOf(words[i]) === -1) { return false; }",
        replace="    if (text.indexOf(words[i]) === -1) { continue; }",
        test="tests.test_view.AReaderCanLookForAWordThePillsDoNotHave"
             ".test_two_words_narrow_and_never_widen",
        scar="a second word ADDING rows, which reads as a filter that stopped "
             "working",
    ),
    Mutation(
        name="the-search-disappears-with-the-pills",
        file="engine/view.py",
        search='    find = (\'<div class="row"><span class="name">find</span>\'',
        replace='    find = (\'\' if not out else \'<div class="row"><span class="name">find</span>\'',
        test="tests.test_view.AReaderCanLookForAWordThePillsDoNotHave"
             ".test_the_bar_survives_a_page_where_no_facet_discriminates",
        scar="a page whose runs share one kind and one sphere losing the only "
             "control that still works on it",
    ),
    Mutation(
        name="the-sort-keys-are-left-to-the-script",
        file="engine/view.py",
        search='        f\' data-sort-state="{worst}"\'',
        replace="        ''",
        test="tests.test_view.TheTableSortsWithoutLosingItsSections"
             ".test_the_keys_are_rendered_and_never_derived_in_the_script",
        scar="a second opinion in JavaScript about which of two verdicts is "
             "worse, drifting from this one the day a severity is added",
    ),
    Mutation(
        name="the-sort-places-rows-against-a-moving-anchor",
        file="engine/view.py",
        search="        var at = section.head;",
        replace="        var anchor = section.head.nextSibling;\n        var at = section.head;",
        test="tests.test_view.TheTableSortsWithoutLosingItsSections"
             ".test_the_rows_are_moved_along_a_cursor_and_not_a_fixed_anchor",
        scar="a section that comes back in an order that is neither the sort "
             "nor the default, and reads as a sort nobody asked for",
    ),
    Mutation(
        name="two-lists-answer-to-the-name-heads",
        file="engine/view.py",
        search="    var sortHeads = Array.prototype.slice.call(",
        replace="    var heads = Array.prototype.slice.call(",
        test="tests.test_view.TheTableSortsWithoutLosingItsSections"
             ".test_one_list_is_called_heads_and_only_one",
        scar="the filter iterating the table's column headers, hiding all four "
             "on every filter and quietly abandoning the section counts",
    ),
    # ——— The half of that guard that was wrong, 2026-08-27 ————————————
    # Written at the top of its function it also fired on every path that was
    # ALREADY silent for a reason of its own, and turned a justified silence
    # into a sentence. Found by asking why one live run had acquired a verdict,
    # thirty minutes after it shipped. Both needles put it back where it was.
    Mutation(
        name="the-uptime-guard-speaks-over-a-justified-silence",
        file="engine/reconcile.py",
        search="    if newest is None:\n        since = getattr(stamp, \"provisioned_at\", None) if stamp is not None else None\n        if not since:\n            return []",
        replace="    if booted is not None and booted > due:\n        return cannot_judge()\n    if newest is None:\n        since = getattr(stamp, \"provisioned_at\", None) if stamp is not None else None\n        if not since:\n            return []",
        test="tests.test_reconcile.TheMachineHasToHaveBeenUp"
             ".test_a_silence_that_was_already_justified_stays_a_silence",
        scar="a run nothing was being claimed about acquiring a sentence "
             "saying nothing can be claimed about it",
    ),
    Mutation(
        name="the-uptime-guard-speaks-over-a-healthy-cadence",
        file="engine/reconcile.py",
        search="    if newest is None:\n        since = getattr(stamp, \"provisioned_at\", None) if stamp is not None else None\n        if not since:\n            return out",
        replace="    if too_soon_to_tell():\n        return out + cannot_judge()\n    if newest is None:\n        since = getattr(stamp, \"provisioned_at\", None) if stamp is not None else None\n        if not since:\n            return out",
        test="tests.test_reconcile.TheMachineHasToHaveBeenUp"
             ".test_a_healthy_cadence_gains_nothing_after_a_reboot",
        scar="one sentence per declaration on a machine rebooted five minutes "
             "ago, each saying nothing is wrong with a run that is fine",
    ),
    # ------------------------------------------------------------------
    # The block from the audit of 2026-08-27 that compared this page with the
    # neighbouring operations page. Four things that page had and this one did
    # not, and two of the four were not features but wrong answers: nine
    # entries in one inventory were decisions somebody had written down and
    # were reported as drift, and the persistent off-list that decides whether
    # anything can start at all was read by `provision` and never by the pass
    # that says how the machine is.
    # ------------------------------------------------------------------
    Mutation(
        name="a-decision-somebody-wrote-down-is-reported-as-drift",
        file="engine/inventory.py",
        search='    decided = [slug for slug in unmatched\n               if getattr(inventory.get(slug), "decided_absent", False)]',
        replace="    decided = []",
        test="tests.test_reconcile.AnAbsenceSomebodyDecidedIsNotDrift"
             ".test_a_decided_absence_is_not_reported_as_drift",
        scar="nine of sixteen rows on a live page were decisions filed under a "
             "heading that said they had drifted, each advising deletion of "
             "the record of the decision",
    ),
    Mutation(
        name="a-broken-absence-block-is-taken-at-its-word",
        file="engine/inventory.py",
        search="        gone = gone if isinstance(gone, Mapping) else {}",
        replace='        gone = gone if isinstance(gone, Mapping) else {"reason": str(gone)}',
        test="tests.test_reconcile.AnAbsenceSomebodyDecidedIsNotDrift"
             ".test_a_block_nobody_can_read_does_not_silence_the_drift",
        scar="a hand written `intentionally_absent: \"parkiert\"` switching a "
             "report off, which is the one field that suppresses both the "
             "report and the repair",
    ),
    Mutation(
        name="a-decided-absence-waits-for-a-complete-look",
        file="engine/inventory.py",
        search='    decided = [slug for slug in unmatched\n               if getattr(inventory.get(slug), "decided_absent", False)]',
        replace='    decided = [] if (getattr(host_obs, "failed_runtimes", None) or ()) else [\n        slug for slug in unmatched\n        if getattr(inventory.get(slug), "decided_absent", False)]',
        test="tests.test_reconcile.AnAbsenceSomebodyDecidedIsNotDrift"
             ".test_a_look_that_missed_a_runtime_still_names_the_decided_ones",
        scar="the one row that needed no looking at all held back by an "
             "incomplete look, because a guard against a claim about the "
             "machine was applied to a sentence that repeats the file",
    ),
    Mutation(
        name="a-decision-shares-the-drift-heading",
        file="engine/view.py",
        search="    drifted = [f for f in inventory if _state(f) != DECIDED_VALUE]",
        replace="    drifted = list(inventory)",
        test="tests.test_view.ADecisionIsNotAChore"
             ".test_a_decided_absence_alone_still_gets_its_section",
        scar="the reader is told there is work here, and the work is deleting "
             "the record of a decision",
    ),
    Mutation(
        name="the-off-list-is-never-asked-for",
        file="engine/reconcile.py",
        search="    off_list = read_disabled(h, stamps, timeout_sec=timeout_sec,\n                             runner=runner, notes=notes)",
        replace="    off_list = {}",
        test="tests.test_reconcile.TheOffListIsAskedOncePerQUESTION"
             ".test_the_observation_carries_the_answer_and_not_just_the_field",
        scar="a unit whose bytes are perfect and which the machine will never "
             "start, reported as in_sync",
    ),
    Mutation(
        name="an-unread-off-list-is-read-as-permission",
        file="engine/reconcile.py",
        search="            switched_off = bool(ref) and (host_obs.disabled or {}).get(ref) is True",
        replace="            switched_off = bool(ref) and (host_obs.disabled or {}).get(ref) is not False",
        test="tests.test_reconcile.NothingCanRunWhileItIsOnTheOffList"
             ".test_an_unread_list_is_not_read_as_permission",
        scar="not asked read as absent, the same mistake `marker_observed` "
             "exists to prevent, in the direction that silences every overdue",
    ),
    Mutation(
        name="every-unit-asks-the-same-question-again",
        file="engine/reconcile.py",
        search="        if key not in seen:",
        replace="        if True:",
        test="tests.test_reconcile.TheOffListIsAskedOncePerQUESTION"
             ".test_one_domain_is_asked_once_for_all_of_its_units",
        scar="thirty identical round trips over ssh on every render, for a "
             "list that answers once for a whole domain",
    ),
    Mutation(
        name="the-off-list-answers-only-about-what-is-loaded",
        file="engine/reconcile.py",
        search='            ref = (unit.unit_ref if unit is not None\n                   else _text(getattr(own, "unit_ref", "")))',
        replace="            ref = unit.unit_ref if unit is not None else \"\"",
        test="tests.test_reconcile.NothingCanRunWhileItIsOnTheOffList"
             ".test_a_unit_that_is_gone_and_on_the_list_says_both",
        scar="the case that is invisible in `launchctl list`: booted out AND "
             "disabled, reported absent with a repair `provision` refuses for "
             "the very reason nothing had read",
    ),
    Mutation(
        name="a-switched-off-run-is-still-called-late",
        file="engine/reconcile.py",
        search="    late = (now - newest[0]).total_seconds()\n    if late > limit:\n        if switched_off:\n            return out + nothing_was_going_to_run_it()",
        replace="    late = (now - newest[0]).total_seconds()\n    if late > limit:\n        if False:\n            return out + nothing_was_going_to_run_it()",
        test="tests.test_reconcile.NothingCanRunWhileItIsOnTheOffList"
             ".test_a_silence_from_a_unit_nothing_will_start_is_not_an_overdue",
        scar="the loudest verdict here aimed at a unit whose bytes are already "
             "correct, with a repair `provision` refuses for the very reason "
             "the silence exists",
    ),
    Mutation(
        name="the-off-list-finding-needs-nobody",
        file="engine/reconcile.py",
        search="                    workload_id=w.id, state=model.WorkloadState.disabled,\n                    severity=model.Severity.medium,",
        replace="                    workload_id=w.id, state=model.WorkloadState.disabled,\n                    severity=model.Severity.info,",
        test="tests.test_reconcile.NothingCanRunWhileItIsOnTheOffList"
             ".test_it_needs_a_person",
        scar="a run the machine will not start, filed among the ordinary "
             "information of a healthy box",
    ),
    Mutation(
        name="the-log-path-is-built-from-the-id",
        file="engine/view.py",
        search="        key = model.state_key(w, appointment)\n        if key:\n            keys.append(",
        replace="        key = w.id\n        if key:\n            keys.append(",
        test="tests.test_view.TheFirstQuestionAfterACrossIsWhere"
             ".test_a_run_with_two_appointments_names_one_file_per_appointment",
        scar="the same trap the trace fell into: a path that does not exist "
             "for exactly the runs whose logs are hardest to find",
    ),
    Mutation(
        name="a-directory-nobody-configured-is-invented",
        file="engine/view.py",
        search='    directory = str(state_dir or "").rstrip("/")',
        replace='    directory = str(state_dir or "~/.bridge/workloads").rstrip("/")',
        test="tests.test_view.TheFirstQuestionAfterACrossIsWhere"
             ".test_without_a_configured_directory_nothing_is_printed",
        scar="a path this page invented, printed exactly like one it was given",
    ),
    Mutation(
        name="the-report-forgets-where-it-read-from",
        file="engine/reconcile.py",
        search='        state_dir=_text(getattr(cfg, "stamp_dir", "")),',
        replace='        state_dir="",',
        test="tests.test_reconcile.WhereARunSaysWhatItSaid"
             ".test_the_report_carries_the_directory_it_read_from",
        scar="the renderer left to guess a configured directory, which is how "
             "a page comes to print a path nobody reads from",
    ),
    Mutation(
        name="the-undeclared-names-lose-their-verb",
        file="engine/view.py",
        search='                    "part of it. <code>workload adopt &lt;unit&gt;</code> is "',
        replace='                    "part of it. "',
        test="tests.test_view.ANameWithoutAVerbIsNotAnAnswer"
             ".test_the_section_names_the_verb_that_answers_it",
        scar="thirty two names and no way to learn how one of them becomes a "
             "declaration",
    ),
    # ------------------------------------------------------------------
    # The block from reading the retired operations CALENDAR, on 2026-08-27.
    # Its strongest idea was not a calendar idea at all: it recorded whether a
    # service runs from the repository or from a copy of it, after a wrapper in
    # ~/bin had drifted from its twin and a change in the repository never
    # reached the run. The calendar's own idea was the week, where a job that
    # fires on Sundays stops looking like a job that fires this morning.
    # ------------------------------------------------------------------
    Mutation(
        name="one-segment-of-a-path-is-taken-for-an-identity",
        file="engine/source.py",
        search="MIN_SUFFIX_SEGMENTS = 2",
        replace="MIN_SUFFIX_SEGMENTS = 1",
        test="tests.test_reconcile.TheProgramMayNotBeTheOneThatIsKept"
             ".test_one_segment_of_a_path_is_not_an_identity",
        scar="a bare basename matching anywhere in the repository counted as "
             "the repository's own file, and the check went quiet exactly "
             "where two copies are most likely",
    ),
    Mutation(
        name="a-shared-interpreter-counts-as-the-program",
        file="engine/source.py",
        search='        if text.startswith("/") and text not in model.SHARED_INTERPRETERS:',
        replace='        if text.startswith("/"):',
        test="tests.test_reconcile.TheProgramMayNotBeTheOneThatIsKept"
             ".test_a_shared_interpreter_is_not_the_program",
        scar="nearly every run on the machine becomes a copy of /bin/bash, and "
             "the one real pair drowns in them",
    ),
    Mutation(
        name="a-digest-nobody-read-is-a-verdict",
        file="engine/source.py",
        search='    theirs = (digests or {}).get(program, "")',
        replace='    theirs = (digests or {}).get(program, "0" * 64)',
        test="tests.test_reconcile.TheProgramMayNotBeTheOneThatIsKept"
             ".test_a_digest_nobody_read_is_not_a_verdict",
        scar="not asked read as differing, so an unreachable machine reports "
             "every program on it as drifted",
    ),
    Mutation(
        name="a-program-on-one-disk-only-is-not-reported",
        file="engine/source.py",
        search="        if where == WHERE_ONLY_HERE:",
        replace="        if False:",
        test="tests.test_reconcile.TheProgramMayNotBeTheOneThatIsKept"
             ".test_a_program_with_no_twin_at_all_is_the_dangerous_one",
        scar="the case a disk failure takes with it, silent: two watchdogs "
             "existed only on one box, a hundred and thirty lines ahead of "
             "the repository's copy",
    ),
    Mutation(
        name="a-refusal-is-read-as-a-digest",
        file="engine/reconcile.py",
        search="        if len(parts) == 2 and len(parts[0]) == 64:",
        replace="        if len(parts) == 2:",
        test="tests.test_reconcile.TheDigestsAreAskedOfTheMachine"
             ".test_a_line_that_is_not_a_digest_is_not_read_as_one",
        scar="`shasum: no such file` parsed as a digest, so a program that is "
             "not there reads as one that has drifted",
    ),
    Mutation(
        name="where-the-program-sits-never-reaches-the-page",
        file="engine/reconcile.py",
        search="            programs.update(source_mod.described(group, root, digests))",
        replace="            pass",
        test="tests.test_reconcile.TheProgramMapReachesTheReport"
             ".test_a_run_carries_where_every_program_sits",
        scar="the comparison made and its answer dropped, so the page can only "
             "shout about the exception and says nothing about the rest",
    ),
    Mutation(
        name="an-appointment-on-another-day-is-drawn-as-if-it-were-today",
        file="engine/view.py",
        search='        shape = mark.shape if here else "elsewhen"',
        replace="        shape = mark.shape",
        test="tests.test_view.AWeeklyRunIsNotDueEveryDay"
             ".test_an_appointment_on_another_day_is_drawn_apart",
        scar="a run that fires on Sundays drawn on a Thursday exactly like one "
             "that was due that morning, with the weekday only in a text cell "
             "beside the picture",
    ),
    Mutation(
        name="an-empty-weekday-set-means-never",
        file="engine/view.py",
        search="        if weekday is None or not self.weekdays:\n            return True",
        replace="        if weekday is None:\n            return True",
        test="tests.test_view.TheWeekAndTheMonthAreScalesOfTheirOwn"
             ".test_a_run_with_no_weekday_constraint_is_due_on_all_seven",
        scar="`weekdays_of` answers empty for a daily run, and read as `no "
             "days` it empties the week and the month of nearly every job on "
             "the page",
    ),
    Mutation(
        name="the-week-starts-on-sunday-after-all",
        file="engine/view.py",
        search="_WEEK_ORDER = (1, 2, 3, 4, 5, 6, 0)",
        replace="_WEEK_ORDER = (0, 1, 2, 3, 4, 5, 6)",
        test="tests.test_view.TheWeekAndTheMonthAreScalesOfTheirOwn"
             ".test_and_it_marks_only_the_days_the_run_fires_on",
        scar="two conventions meet here, `weekdays_of` counting Sunday as zero "
             "and a week a reader reads Monday first; getting it wrong shifts "
             "every mark by one day and looks entirely plausible",
    ),
    Mutation(
        name="a-month-is-drawn-without-a-date",
        file="engine/view.py",
        search="    if on is None or not any(week or ()):\n        return ()",
        replace="    if not any(week or ()):\n        return ()",
        test="tests.test_view.TheWeekAndTheMonthAreScalesOfTheirOwn"
             ".test_without_a_moment_nothing_is_placed_in_a_week",
        scar="a guessed date puts marks on days nobody measured, and a "
             "calendar for no particular month reads exactly like one for this",
    ),
    Mutation(
        name="what-ran-is-merged-into-what-was-due",
        file="engine/view.py",
        search=' + (" ran" if ran else "")',
        replace=' + ""',
        test="tests.test_view.TheWeekAndTheMonthAreScalesOfTheirOwn"
             ".test_what_actually_ran_is_a_second_mark_from_a_second_source",
        scar="a day that was never scheduled and a day that was scheduled and "
             "missed drawn the same, which is the one comparison a calendar "
             "exists for",
    ),
    Mutation(
        name="the-other-scales-are-built-on-click",
        file="engine/view.py",
        search="    week, month = _week_html(lane, on), _month_html(lane, on)",
        replace='    week, month = "", ""',
        test="tests.test_view.TheWeekAndTheMonthAreScalesOfTheirOwn"
             ".test_all_three_ship_and_one_is_shown",
        scar="a scale that exists only after a click is a scale nobody can "
             "read with scripting off, and this page has to stand alone",
    ),
    Mutation(
        name="the-page-keeps-the-day-it-drew-to-itself",
        file="engine/view.py",
        search="    if on is not None:\n        body.append(",
        replace="    if False:\n        body.append(",
        test="tests.test_view.ThePageNamesTheDayItDrew"
             ".test_the_day_and_the_zone_are_named",
        scar="a grid of hours belongs to no day; without the sentence "
             "yesterday's calendar and today's are the same picture",
    ),
    Mutation(
        name="the-legend-leaves-the-faintest-mark-unexplained",
        file="engine/view.py",
        search='        shown.add("elsewhen")',
        replace="        pass",
        test="tests.test_view.AWeeklyRunIsNotDueEveryDay"
             ".test_the_legend_explains_the_faint_mark",
        scar="a shape nobody explains is a decoration, and this one is the "
             "faintest mark on the page",
    ),
    Mutation(
        name="the-month-ruler-is-left-to-size-itself",
        file="engine/view.py",
        search='    return (f\'<div class="grid month ruler" \'\n'
               '            f\'style="grid-template-columns: repeat({total}, 1fr)">{cells}</div>\')',
        replace='    return f\'<div class="grid month ruler">{cells}</div>\'',
        test="tests.test_view.TheWeekAndTheMonthAreScalesOfTheirOwn"
             ".test_the_month_ruler_and_its_cells_are_told_the_same_grid",
        scar="two grids stacked under one another, one sized to the digits in "
             "it and one to cells with no text: the scale pointed at the wrong "
             "days and looked entirely ordinary doing it",
    ),
    Mutation(
        name="the-month-cells-are-left-to-size-themselves",
        file="engine/view.py",
        search='    return (f\'<div class="grid month" \'\n'
               '            f\'style="grid-template-columns: repeat({total}, 1fr)">{out}</div>\')',
        replace='    return f\'<div class="grid month">{out}</div>\'',
        test="tests.test_view.TheWeekAndTheMonthAreScalesOfTheirOwn"
             ".test_the_month_ruler_and_its_cells_are_told_the_same_grid",
        scar="the other half of the same pair, and either half alone is enough "
             "to put the ruler and the days out of step",
    ),
    # ── the transport under the size gate, found the hard way on 2026-08-27:
    # the gate counts a file against the SHELL's limit and passed a 274 KiB
    # page, which the multiplexed ssh session then refused in one packet with
    # an error naming neither the file nor the size.
    Mutation(
        name="a-page-larger-than-one-packet-goes-as-one",
        file="engine/backends/base.py",
        search="        if current and size + cost > chunk_bytes:",
        replace="        if False:",
        test="tests.test_backends.AFileTooBigForOneCommandLineTravelsInParts"
             ".test_a_large_one_is_several",
        scar="`mux_client_request_session: write packet: Broken pipe`, twice in "
             "a row, on a page the size gate had passed",
    ),
    Mutation(
        name="a-later-part-truncates-what-the-first-wrote",
        file="engine/backends/base.py",
        search='        redirect = ">" if index == 0 else ">>"',
        replace='        redirect = ">"',
        test="tests.test_backends.AFileTooBigForOneCommandLineTravelsInParts"
             ".test_the_first_truncates_and_the_rest_append",
        scar="every part overwriting the one before it, so the file on the "
             "machine is the LAST chunk and nothing else",
    ),
    Mutation(
        name="a-chunk-is-cut-inside-a-line",
        file="engine/backends/base.py",
        search="    for line in body.splitlines(keepends=True):",
        replace="    for line in [body[i:i + 64] for i in range(0, len(body), 64)]:",
        # Retargeted 2026-08-27, minutes after it was written: the reassembled
        # BYTES are identical either way, because grouping slices and grouping
        # lines concatenate to the same text. What breaks is the script, and
        # that is what the named case measures.
        test="tests.test_backends.AFileTooBigForOneCommandLineTravelsInParts"
             ".test_a_split_never_falls_inside_a_line",
        scar="a here-document ends every line it carries, so a cut inside one "
             "puts a newline into the file that was never in it and the "
             "read-back fails on a file that was sent correctly",
    ),
    Mutation(
        name="the-mode-is-set-before-the-file-is-finished",
        file="engine/backends/base.py",
        search="        tail = (\"\\n\" + f\"chmod {format(item.mode, '04o')} \"\n"
               "                + shlex.quote(str(item.path))) if index == len(parts) - 1 else \"\"",
        replace="        tail = (\"\\n\" + f\"chmod {format(item.mode, '04o')} \"\n"
                "                + shlex.quote(str(item.path)))",
        test="tests.test_backends.AFileTooBigForOneCommandLineTravelsInParts"
             ".test_the_directory_is_made_once_and_the_mode_set_once_at_the_end",
        scar="the mode set on a half written file, once per part, which reads "
             "in a printed plan as four separate deliveries",
    ),
    Mutation(
        name="the-read-back-happens-between-the-parts",
        file="engine/publish.py",
        search="        steps.extend(item.writes)\n        steps.append(item.readback)",
        replace="        steps.append(item.writes[0])\n        steps.append(item.readback)\n"
                "        steps.extend(item.writes[1:])",
        test="tests.test_publish.EveryPartOfAPageIsWrittenBeforeItIsReadBack"
             ".test_and_every_one_of_them_comes_before_the_read_back",
        scar="a fragment compared against the whole page, reporting a delivery "
             "that had not happened yet",
    ),
    Mutation(
        name="the-off-list-read-inherits-the-write-flag",
        file="engine/backends/launchd.py",
        search="                purpose=f\"read the persistent off-list of {self._domain_of(a)}\",\n"
               "                expect_rc=(0, 3, 113),\n",
        replace="                purpose=f\"read the persistent off-list of {self._domain_of(a)}\",\n"
                "                expect_rc=(0, 3, 113),\n"
                "                requires_elevation=self.requires_elevation,\n",
        test="tests.test_reconcile.OneRootOwnedUnitDoesNotBlindTheHost"
             ".test_reading_the_system_off_list_asks_for_no_elevation",
        scar="issue #179: two root-owned units on a host of 57 declarations, "
             "and the page for all 57 went stale instead of red",
    ),
    Mutation(
        name="an-elevated-off-list-read-reaches-the-runner",
        file="engine/reconcile.py",
        search="        if key not in seen and any(getattr(s, \"requires_elevation\", False) "
               "for s in steps):\n",
        replace="        if False:\n",
        test="tests.test_reconcile.OneRootOwnedUnitDoesNotBlindTheHost"
             ".test_a_read_that_does_need_elevation_is_one_gap_not_a_dead_host",
        scar="issue #179: the runner's refusal was raised through observe_host, "
             "so one unreadable entry took the report for the whole host with it",
    ),
)