"""The command line: what it BINDS, not what it prints.

Printing a verdict and returning it are not the same thing, and every case in
this file exists because they were confused. `validate --strict` ran a second,
independent gate, printed its judgements, and threw them away. A declaration the
schema refused exited 0. A machine without the validator -- the normal case on a
fresh clone -- exited 0 too, so the flag was a switch with no effect. And both
of those answers arrived two rows UNDER the line that says the run was clean.

The second half is the other end of the same wiring: `provision --yes` handed
`Outcome.findings`, a tuple of plain sentences, to `report.Report`, and answered
an AttributeError where the contract promises a report and an exit code of 1.

Nothing here touches a machine. The one process this file starts is a three line
shell script in a temporary directory, named `check-jsonschema` so that the real
`shutil.which` finds it: it is how the wiring from PATH to exit code is measured
without asking anyone to install a tool first.
"""

from __future__ import annotations

import contextlib
import io
import os
import stat
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.conftest import (
    DEFAULT_CONFIG,
    DERIVED,
    CORPUS,
    FakeCompleted,
    MachineGuard,
    RecordingRunner,
    make_repo,
    mod,
    read_output,
)

cli = mod("engine.cli")
model = mod("engine.model")
backends = mod("engine.backends")
config = mod("engine.config")
report = mod("engine.report")
lock_mod = mod("engine.lock")
errors = mod("engine.errors")


def Verdict(verdict, detail=""):
    """What `model.validate_with_schema` returns.

    A function rather than a class: every class in a test file has to stand
    under the machine guard, and a two field record is not a test case.
    """
    return SimpleNamespace(verdict=verdict, detail=detail)


class TheSecondGateDecidesTheExitCode(MachineGuard):
    """`--strict` is a gate or it is decoration. It was decoration."""

    def repo(self, *declarations):
        return make_repo(self.tmpdir(), declarations=declarations or ("calendar-export",))

    def strict(self, root, answer, *extra):
        """Drive `validate --strict` with the second gate answering `answer`.

        The tool call itself belongs to `model`; what is measured here is what
        the command line DOES with the answer, all the way to the exit code.
        """
        import engine.model as model_module

        def fake(path, schema, runner):
            return answer(Path(path)) if callable(answer) else answer

        out = io.StringIO()
        with mock.patch.object(model_module, "validate_with_schema", fake):
            with contextlib.redirect_stdout(out):
                rc = cli.main(["--root", str(root), "validate", "--all", "--strict", *extra])
        return rc, out.getvalue()

    # A1 ---------------------------------------------------------------------
    def test_a_declaration_the_schema_refuses_never_exits_zero(self):
        rc, out = self.strict(self.repo(), Verdict("invalid", "$.schedule.timezone: '+02:00'"))
        self.assertEqual(rc, 1,
                         "the schema gate refused the declaration and the command "
                         f"still exited {rc}:\n{out}")
        self.assertIn("+02:00", out)

    # A5 ---------------------------------------------------------------------
    def test_the_clean_line_never_stands_over_a_refusal(self):
        # The line a human reads first has to be the answer. It used to say
        # "clean" two rows above the refusal that contradicted it.
        _, out = self.strict(self.repo(), Verdict("invalid", "nope"))
        self.assertNotIn(report.CLEAN_LINE, out,
                         f"the clean line stood over a refusal:\n{out}")

    # A2 ---------------------------------------------------------------------
    def test_an_absent_validator_is_a_finding_and_not_silence(self):
        # "a check nobody ran is not a green check". Without this, --strict on a
        # fresh clone is a flag that changes nothing at all.
        rc, out = self.strict(self.repo(),
                              Verdict("schema_validator_absent",
                                      "check-jsonschema is not on PATH"))
        self.assertEqual(rc, 1,
                         f"--strict could not run its gate and exited {rc}:\n{out}")
        self.assertNotIn(report.CLEAN_LINE, out)
        self.assertIn("check-jsonschema", out)

    def test_the_absent_answer_is_said_once_and_not_per_declaration(self):
        # There is one PATH, so the second file cannot answer differently.
        # Repeating it buries the sentence that matters under copies of itself.
        root = self.repo("calendar-export", "daily-health-report", "chat-channel")
        _, out = self.strict(root, Verdict("schema_validator_absent",
                                           "check-jsonschema is not on PATH"))
        self.assertEqual(out.count("the schema gate did not run"), 1, out)

    # A3 ---------------------------------------------------------------------
    def test_a_gate_that_refuses_everything_never_exits_zero(self):
        root = self.repo("calendar-export", "daily-health-report", "chat-channel")
        rc, out = self.strict(root, Verdict("invalid", "refused"))
        self.assertEqual(rc, 1, f"every declaration was refused and rc was {rc}:\n{out}")
        self.assertEqual(out.count("the schema gate refused it"), 3, out)

    # the counter-control ----------------------------------------------------
    def test_a_gate_that_passes_stays_clean_and_exits_zero(self):
        # Without this the four cases above are satisfied by a --strict that
        # simply always fails, which is a different broken switch.
        rc, out = self.strict(self.repo(), Verdict("valid"))
        self.assertEqual(rc, 0, out)
        self.assertIn(report.CLEAN_LINE, out)

    def test_the_first_gate_still_decides_on_its_own(self):
        # --strict adds a gate, it does not replace one. A declaration the hand
        # written invariants refuse stays refused even when the schema is happy.
        root = make_repo(self.tmpdir(), declarations=("negative-no-deadline",))
        rc, out = self.strict(root, Verdict("valid"))
        self.assertEqual(rc, 1, out)

    def test_without_strict_the_second_gate_is_not_run_at_all(self):
        import engine.model as model_module

        asked = []

        def fake(path, schema, runner):
            asked.append(str(path))
            return Verdict("invalid", "refused")

        root = self.repo()
        with mock.patch.object(model_module, "validate_with_schema", fake):
            with contextlib.redirect_stdout(io.StringIO()):
                rc = cli.main(["--root", str(root), "validate", "--all"])
        self.assertEqual(asked, [], f"the second gate ran without --strict: {asked}")
        self.assertEqual(rc, 0)

    def test_the_header_says_that_the_schema_gate_was_asked_for(self):
        # A green that does not say what was looked at is a pass over an empty
        # scan, and that applies to the second gate as much as to the first.
        _, out = self.strict(self.repo(), Verdict("valid"))
        self.assertIn("schema gate", out.splitlines()[0])

    def test_the_answer_is_asked_for_every_chosen_declaration(self):
        seen = []
        root = self.repo("calendar-export", "daily-health-report")

        def answer(path):
            seen.append(path.name)
            return Verdict("valid")

        rc, _ = self.strict(root, answer)
        self.assertEqual(rc, 0)
        self.assertEqual(sorted(seen),
                         ["calendar-export.yaml", "daily-health-report.yaml"])


class TheGateIsReallyResolvedOnPath(MachineGuard):
    """From an executable on PATH to the process exit code, with nothing faked.

    The stand-in above measures the wiring on this side of
    `validate_with_schema`. This case measures the rest of it: that the tool is
    looked up on PATH at all, that its return code is read, and that the answer
    survives as far as the exit code. It starts one local shell script under the
    engine's own deadline and touches no machine.
    """

    def with_stub(self, rc: int, said: str):
        folder = self.tmpdir()
        stub = folder / "check-jsonschema"
        stub.write_text(f'#!/bin/sh\necho "{said}"\nexit {rc}\n', encoding="utf-8")
        stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return folder

    def drive(self, path_value: str):
        root = make_repo(self.tmpdir(), declarations=("calendar-export",))
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"PATH": path_value}):
            with contextlib.redirect_stdout(out):
                rc = cli.main(["--root", str(root), "validate", "--all", "--strict"])
        return rc, out.getvalue()

    def test_a_validator_that_refuses_lands_on_the_exit_code(self):
        rc, out = self.drive(str(self.with_stub(1, "this file is not acceptable")))
        self.assertEqual(rc, 1, out)
        self.assertIn("this file is not acceptable", out)
        self.assertNotIn(report.CLEAN_LINE, out)

    def test_a_validator_that_accepts_leaves_the_run_clean(self):
        rc, out = self.drive(str(self.with_stub(0, "ok")))
        self.assertEqual(rc, 0, out)
        self.assertIn(report.CLEAN_LINE, out)

    def test_an_empty_path_is_the_absent_gate_and_still_exits_one(self):
        rc, out = self.drive(str(self.tmpdir()))
        self.assertEqual(rc, 1, out)
        self.assertIn("check-jsonschema", out)

    def test_a_repository_without_a_contract_is_not_a_repository_of_bad_files(self):
        # Measured before the repair, with the real tool: two declarations, both
        # reported `invalid`, the objection a FileNotFoundError inside the tool's
        # virtualenv, the hint "fix the declaration at the path check-jsonschema
        # names". Every word of that is wrong: the declarations were in order and
        # the contract was gone.
        folder = self.with_stub(0, "ok")
        witness = folder / "the-validator-was-run"
        (folder / "check-jsonschema").write_text(
            f'#!/bin/sh\ntouch "{witness}"\nexit 0\n', encoding="utf-8")
        root = make_repo(self.tmpdir(),
                         declarations=("calendar-export", "daily-health-report"),
                         contract=None)
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"PATH": str(folder)}):
            with contextlib.redirect_stdout(out):
                rc = cli.main(["--root", str(root), "validate", "--all", "--strict"])
        text = out.getvalue()
        self.assertEqual(rc, 1, f"a gate with no contract exited {rc}:\n{text}")
        self.assertNotIn("the schema gate refused it", text)
        self.assertEqual(text.count("no schema to check against"), 1,
                         f"the one fact was said {text.count('no schema to check against')} "
                         f"times:\n{text}")
        self.assertFalse(witness.exists(),
                         "the validator was run against a schema that is not there")


#: A declaration template small enough to write here, carrying a marker no other
#: file in this suite writes. The marker is what makes "which template was read"
#: an answerable question.
THROWAWAY_TEMPLATE = """\
# a throwaway template, and this line is how the answer names itself
schema_version: 1
id: <slug-matches-filename>

placement:
  host: <host>
  kind: recurring
  runtime: dispatcher
  owner: bridge

execution:
  command: ["/absolute/path/to/script.sh"]
  timeout_sec: 600
"""


class APromiseToReportAFailureNeedsAFloor(MachineGuard):
    """A run that asks to be told about a failure must be able to report one.

    The chain was measured end to end on a live machine: wrapper exits
    non-zero, guard writes `verdict=failed`, `reconcile --notify` turns that
    into `last_run_failed`, a message arrives. A script ending in a bare
    `exit 0` breaks the first link, and every link after it then works
    faultlessly on an input that never comes. 441 traces in three days said
    `verdict=ok` while three of the runs behind them could not have said
    anything else.

    The four silences are cases too. A guard that fires where it cannot know
    is worse than one that stays quiet, because its answer arrives exactly
    while somebody is deciding whether to trust a report.
    """

    TRAEGT = 'RC=$?\necho done\nexit "$RC"\n'
    HOHL = "RC=$?\necho done\nexit 0\n"

    def repo(self, *, script=HOHL, notify="[failure, missing]",
             write_script=True, outside=False):
        root = self.tmpdir()
        make_repo(root, declarations=())
        target = root / "scripts" / "report.sh"
        if outside:
            target = self.tmpdir() / "report.sh"
        target.parent.mkdir(parents=True, exist_ok=True)
        if write_script:
            target.write_text(script, encoding="utf-8")
        (root / "workflow" / "workloads" / "promising-report.yaml").write_text(
            "schema_version: 1\n"
            "scope: user\n"
            "id: promising-report\n"
            'purpose: "A report that says it will tell somebody when it fails"\n'
            "placement: {host: host-a, kind: recurring, runtime: launchd, owner: bridge}\n"
            'schedule: {timezone: UTC, rrule: "FREQ=DAILY", delivery_at: "07:00"}\n'
            "execution:\n"
            f'  command: ["/bin/sh", "{target}"]\n'
            "  timeout_sec: 60\n"
            "response:\n"
            "  evidence: log-trace\n"
            f"  notify_on: {notify}\n"
            "  notify_via: example-notify\n",
            encoding="utf-8")
        return root

    def pruefe(self, root):
        """NOT named `run`: that is the method unittest calls to execute a
        case. An earlier draft called it that, and the fourteen cases below
        did not fail, they DISAPPEARED from the tally ("Ran 0 tests") while
        discovery still collected them. A gate that vanishes reads exactly
        like a gate that passed.
        """
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = cli.main(["--root", str(root), "validate", "--all"])
        return rc, out.getvalue()

    # -- the premise: what the predicate itself answers -----------------------
    def test_a_bare_exit_zero_at_the_end_is_the_case(self):
        self.assertTrue(model.ends_in_bare_exit_zero(self.HOHL))

    def test_a_return_value_that_is_carried_is_not_the_case(self):
        self.assertFalse(model.ends_in_bare_exit_zero(self.TRAEGT))

    def test_an_indented_exit_zero_is_guarded_by_something_and_not_the_case(self):
        # Inside an `if` or a function body it is conditional, and this rule is
        # about the value a script returns however the run went.
        #
        # The indented line has to BE the last one, or the case measures
        # nothing: the first draft ended the sample with `fi` and `echo on`,
        # so the indented `exit 0` was never the line under examination and
        # the needle for this anchor survived the whole suite.
        self.assertFalse(model.ends_in_bare_exit_zero("echo on\n    exit 0\n"))

    def test_a_trailing_comment_does_not_hide_it(self):
        self.assertTrue(model.ends_in_bare_exit_zero("echo x\nexit 0  # never fail hard\n"))

    def test_comments_and_blank_lines_after_it_are_skipped(self):
        self.assertTrue(model.ends_in_bare_exit_zero("exit 0\n\n# end\n\n"))

    def test_an_empty_file_is_not_the_case(self):
        self.assertFalse(model.ends_in_bare_exit_zero(""))

    # -- the case ------------------------------------------------------------
    def test_a_hollow_promise_is_a_finding(self):
        rc, out = self.pruefe(self.repo())
        self.assertEqual(rc, 1, f"the promise had no floor and validate exited {rc}:\n{out}")

    def test_the_finding_names_both_halves(self):
        _, out = self.pruefe(self.repo())
        self.assertIn("report.sh", out, f"the finding does not name the script:\n{out}")
        self.assertIn("exit 0", out, f"the finding does not name what is wrong:\n{out}")

    def test_the_clean_line_never_stands_over_it(self):
        _, out = self.pruefe(self.repo())
        self.assertNotIn(report.CLEAN_LINE, out,
                         f"the clean line stood over a hollow promise:\n{out}")

    # -- the control ---------------------------------------------------------
    def test_a_script_that_carries_its_return_value_stays_clean(self):
        rc, out = self.pruefe(self.repo(script=self.TRAEGT))
        self.assertEqual(rc, 0, f"a sound script was refused:\n{out}")

    # -- the four silences ---------------------------------------------------
    def test_without_a_failure_promise_nothing_is_hollow(self):
        rc, out = self.pruefe(self.repo(notify="[missing]"))
        self.assertEqual(rc, 0, f"nothing was promised and it was still refused:\n{out}")

    def test_a_script_outside_this_repository_is_not_judged(self):
        # It may be a path on another machine whose home is not this one.
        rc, out = self.pruefe(self.repo(outside=True))
        self.assertEqual(rc, 0, f"a foreign path was judged from here:\n{out}")

    def test_a_path_outside_the_root_is_not_even_picked_as_the_script(self):
        """The containment itself, measured where nothing else can catch it.

        The end to end case above passes for a SECOND reason as well: with the
        containment gone the loop takes `/bin/sh`, whose bytes do not decode,
        and falls silent there. Two guards in a row mean neither is measured,
        and the needle for this one survived the suite until this case existed.
        """
        root = self.tmpdir()
        make_repo(root, declarations=())
        fremd = self.tmpdir() / "report.sh"
        fremd.write_text(self.HOHL, encoding="utf-8")
        workload = SimpleNamespace(
            execution=SimpleNamespace(command=["/opt/example/bin/sh", str(fremd)]))
        self.assertIsNone(cli._script_inside(workload, root),
                          "a file outside the repository was taken as its script")

    def test_a_missing_file_is_a_different_fact_and_stays_quiet(self):
        rc, out = self.pruefe(self.repo(write_script=False))
        self.assertEqual(rc, 0, f"an absence was reported as a violation:\n{out}")

    def test_bytes_that_do_not_decode_are_not_a_last_line(self):
        root = self.repo()
        (root / "scripts" / "report.sh").write_bytes(b"\x00\xff\xfe binary")
        rc, out = self.pruefe(root)
        self.assertEqual(rc, 0, f"a binary was read for a last line:\n{out}")


class AStatusNobodyCanReturnIsNoStatus(MachineGuard):
    """The second shape: a script catches its return value and never uses it.

    The wrapper that had it ran a program, wrote the result into `EXIT_CODE`,
    printed a sentence about it, and ended on `fi`. Whatever happened, the
    script returned zero. Three of the six real repairs of 2026-08-26 had this
    exact shape, and the rule for the LAST LINE does not see any of them.
    """

    HOHL = "run_it\nEXIT_CODE=$?\nif [ $EXIT_CODE -ne 0 ]; then\n  echo kaputt\nfi\n"
    TRAEGT = 'run_it\nEXIT_CODE=$?\nexit "$EXIT_CODE"\n'

    def frage(self, text):
        return model.computes_a_status_it_can_never_return(text)

    def test_a_caught_status_with_no_exit_left_is_the_case(self):
        self.assertTrue(self.frage(self.HOHL))

    def test_a_status_that_is_returned_is_not_the_case(self):
        self.assertFalse(self.frage(self.TRAEGT))

    def test_a_literal_exit_after_the_catch_is_an_exit(self):
        self.assertFalse(self.frage("run_it\nEXIT_CODE=$?\nexit 3\n"))

    def test_exit_zero_after_the_catch_does_not_count_as_carrying_it(self):
        # `exit 0` carries nothing. It is the first rule's case, not a rescue
        # from this one, and a script with both is reported once.
        self.assertTrue(self.frage("run_it\nEXIT_CODE=$?\necho x\nexit 0\n"))

    def test_errexit_silences_it(self):
        # Under `set -e` the script ends on the failing command itself, before
        # the catch line is reached, and its return value is that command's.
        self.assertFalse(self.frage("set -euo pipefail\nrun_it\nEXIT_CODE=$?\nfi\n"))

    def test_exec_silences_it(self):
        # The process image is replaced; a later exit is unreachable.
        self.assertFalse(self.frage("run_it\nEXIT_CODE=$?\nexec /bin/other\n"))

    def test_a_function_with_a_loud_exit_that_is_called_afterwards_silences_it(self):
        self.assertFalse(self.frage(
            'fehler() {\n  echo x\n  exit 1\n}\nrun_it\nEXIT_CODE=$?\nfehler\n'))

    def test_a_one_line_function_body_is_still_a_body(self):
        # `f() { ...; }` opens and closes on one line, so the brace count never
        # goes above zero and the body has to be taken from that line itself.
        # Without it the loud exit inside disappears and a sound script is
        # reported.
        self.assertFalse(self.frage(
            'fehler() { echo "${RED}x"; exit 1; }\nrun_it\nEXIT_CODE=$?\nfehler\n'))

    def test_a_script_that_catches_nothing_is_not_the_case(self):
        self.assertFalse(self.frage("run_it\necho done\n"))


class AnExitTrapMayNotEatTheStatus(MachineGuard):
    """The third shape: a handler bound to EXIT exits zero over the top.

    The bot wrapper had it. Its last line returned the child's value
    correctly, and the handler ran afterwards and threw it away, so the script
    could not fail no matter how the run went.
    """

    HOHL = 'cleanup() {\n  rm -f x\n  exit 0\n}\ntrap cleanup EXIT\nrun_it\nexit $?\n'
    TRAEGT = ('cleanup() {\n  local rc=$?\n  rm -f x\n  exit "$rc"\n}\n'
              "trap cleanup EXIT\nrun_it\n")
    ZURUF = 'stop() {\n  echo weg\n  exit 0\n}\ntrap stop SIGTERM SIGINT\nrun_it\n'

    def frage(self, text):
        return model.an_exit_trap_overwrites_the_status(text)

    def test_a_handler_bound_to_exit_that_exits_zero_is_the_case(self):
        self.assertTrue(self.frage(self.HOHL))

    def test_a_handler_that_carries_the_value_is_not_the_case(self):
        self.assertFalse(self.frage(self.TRAEGT))

    def test_a_handler_bound_only_to_signals_stays_silent(self):
        # A stop on request is not a failure, and such a handler SHOULD end in
        # zero. Told apart by the signal list and never by the body: widening
        # it to every handler would forbid exactly the repair that was built
        # on 2026-08-26.
        self.assertFalse(self.frage(self.ZURUF))

    def test_the_same_handler_on_signals_and_exit_together_is_the_case(self):
        # This is what the bot wrapper really had: one handler for both, so the
        # deliberate stop and the crash were the same answer.
        self.assertTrue(self.frage(
            'cleanup() {\n  rm -f x\n  exit 0\n}\ntrap cleanup SIGTERM SIGINT EXIT\n'))

    def test_an_exit_zero_inside_a_condition_is_not_how_the_handler_ends(self):
        # The last statement of this body is `fi`, not the `exit 0` above it.
        # The handler can therefore end with whatever the script returned, and
        # a rule that looked anywhere in the body would forbid a sound one.
        self.assertFalse(self.frage(
            'cleanup() {\n  if [ -n "$X" ]; then\n    exit 0\n  fi\n}\n'
            "trap cleanup EXIT\n"))

    def test_an_inline_handler_counts_too(self):
        self.assertTrue(self.frage("trap 'rm -f x; exit 0' EXIT\nrun_it\n"))

    def test_a_script_without_a_trap_is_not_the_case(self):
        self.assertFalse(self.frage("run_it\nexit $?\n"))


class TheThreeShapesDivideTheSameDefect(MachineGuard):
    """Each broken version caught by exactly one rule, each repaired one by none.

    Measured on the six real repairs of 2026-08-26. If two rules claimed the
    same script a reader would get two sentences for one defect, and if a
    repaired version still matched, the gate would refuse work that is sound.
    """

    def rules(self, text):
        return tuple(name for name, frage in (
            ("blank", model.ends_in_bare_exit_zero),
            ("trap", model.an_exit_trap_overwrites_the_status),
            ("no-exit", model.computes_a_status_it_can_never_return),
        ) if frage(text))

    KAPUTT = {
        "blank": "run_it\nEXIT_CODE=$?\necho x\nexit 0\n",
        "trap": 'cleanup() {\n  exit 0\n}\ntrap cleanup EXIT\nrun_it\nexit $?\n',
        "no-exit": "run_it\nEXIT_CODE=$?\nif [ $EXIT_CODE -ne 0 ]; then\n  echo x\nfi\n",
    }

    def test_each_broken_shape_is_claimed_by_at_least_its_own_rule(self):
        for name, text in self.KAPUTT.items():
            with self.subTest(shape=name):
                self.assertIn(name, self.rules(text))

    def test_a_sound_script_is_claimed_by_none_of_them(self):
        sound = ('cleanup() {\n  local rc=$?\n  exit "$rc"\n}\n'
                  'trap cleanup EXIT\nrun_it\nEXIT_CODE=$?\nexit "$EXIT_CODE"\n')
        self.assertEqual(self.rules(sound), ())

    def test_a_script_that_fits_two_rules_is_reported_once(self):
        # The chain answers with ONE sentence. Two lines for one defect read
        # as two defects.
        two = "run_it\nEXIT_CODE=$?\necho x\nexit 0\n"
        self.assertGreaterEqual(len(self.rules(two)), 2,
                                "the sample no longer fits two rules, so this "
                                "case measures nothing")
        sentence = cli._no_floor(Path("example.sh"), two)
        self.assertIsNotNone(sentence)
        self.assertIn("bare `exit 0`", sentence,
                      "the chain answers with the least uncertain rule first")


class DeclareIsReachableFromTheArgvAHumanTypes(MachineGuard):
    """The one documented way to write a new declaration, driven from argv.

    Nothing drove it. `cmd_declare` was called as a function with a namespace
    somebody built by hand, and the namespace argparse REALLY builds could not
    reach it: the subcommand and `declare --command` were the same attribute.
    `workload declare <id> --command ...` ended in `TypeError: cannot use 'list'
    as a dict key` out of the dispatch table, and without `--command` the
    attribute stayed `None` and the top level help was printed as though no
    subcommand had been typed. Measured through the shim, both shapes.
    """

    def repo(self):
        root = make_repo(self.tmpdir())
        (root / "workflow" / "workloads" / "_template.yaml").write_text(
            THROWAWAY_TEMPLATE, encoding="utf-8")
        return root

    def declare(self, *extra):
        root = self.repo()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = cli.main(["--root", str(root), "declare", "sample-report",
                           "--kind", "recurring", "--runtime", "launchd",
                           "--host", "host-a", *extra])
        return rc, root / "workflow" / "workloads" / "sample-report.yaml", out.getvalue()

    def test_declare_with_a_command_writes_the_declaration(self):
        rc, path, out = self.declare("--command", "/usr/bin/true")
        self.assertEqual(rc, 0, out)
        self.assertTrue(path.exists(), f"declare wrote nothing:\n{out}")
        self.assertIn("/usr/bin/true", path.read_text(encoding="utf-8"))

    def test_declare_without_a_command_is_still_a_declare_and_not_the_help(self):
        rc, path, out = self.declare()
        self.assertEqual(rc, 0, out)
        self.assertTrue(path.exists(), f"declare printed the help instead:\n{out}")

    def test_the_template_that_is_read_is_the_one_in_the_target_repository(self):
        # `--root` exists for the case where the repository being written to is
        # not the tree the skill lives in, and the template was resolved from the
        # skill's own location regardless.
        rc, path, out = self.declare("--command", "/usr/bin/true")
        self.assertEqual(rc, 0, out)
        self.assertTrue(path.exists(),
                        f"declare wrote nothing, so no template was read at all:\n{out}")
        self.assertIn("this line is how the answer names itself",
                      path.read_text(encoding="utf-8"),
                      "the scaffold was built from a template outside the target "
                      "repository")


class RetireAndAdoptAnswerWithAReport(MachineGuard):
    """The two commands that were still printing two fields of an outcome.

    `provision` was repaired in the same round; these two carried the identical
    defect one command further along. `retire --dry-run` answered `retire:
    retire, verified=False`, a line from which refused, failed and previewed
    cannot be told apart, while the outcome it printed from had carried the
    sentence "dry run, nothing was stopped" the whole time.
    """

    def drive(self, *argv, print_output="launchctl-print-notfound.txt", print_rc=113):
        root = make_repo(self.tmpdir(), declarations=("calendar-export",))
        runner = RecordingRunner()
        runner.add("id -u", FakeCompleted(stdout=read_output("probe-context.txt")))
        runner.add("launchctl print",
                   FakeCompleted(rc=print_rc, stdout=read_output(print_output)))
        runner.add("cat ", FakeCompleted(rc=1))
        runner.add("shasum", FakeCompleted(stdout=f"{'0' * 64}  x"))
        import engine.exec as exec_module

        out = io.StringIO()
        with mock.patch.object(exec_module, "step_runner", runner):
            with contextlib.redirect_stdout(out):
                rc = cli.main(["--root", str(root), *argv])
        return rc, out.getvalue()

    def retire(self, *extra):
        return self.drive("retire", "calendar-export", "--reason",
                          "superseded by the timer", *extra)

    def test_a_dry_run_retirement_says_why_nothing_was_stopped(self):
        rc, out = self.retire("--dry-run")
        self.assertEqual(rc, 1, out)
        self.assertIn("dry run, nothing was stopped", out,
                      f"the preview kept its reason to itself:\n{out}")

    def test_the_row_names_the_workload_it_is_about(self):
        # The header carries the id, so "somewhere in the output" measures
        # nothing: it is the ROW that has to name it.
        _, out = self.retire("--dry-run")
        row = [line for line in out.splitlines() if "dry run, nothing was stopped" in line]
        self.assertEqual(len(row), 1, out)
        self.assertIn("calendar-export", row[0])

    def test_a_confirmed_retirement_says_it_was_verified_and_what_it_did(self):
        # The counter-control: a report that only ever says "NOT verified"
        # would satisfy the two cases above.
        rc, out = self.retire("--yes")
        self.assertEqual(rc, 0, out)
        self.assertIn("verified at the live object", out)
        self.assertIn("disabled persistently", out)

    def test_retiring_a_run_with_two_appointments_stops_BOTH(self):
        """The comment above the loop in `cmd_retire` states the requirement:
        "Every unit, because a run stopped by half is still running." A guard
        one layer down defeated it.

        `write_retired` refuses a declaration that already carries a `retired:`
        block, which is right when a human retires the same run twice. But the
        loop calls it once per APPOINTMENT, so the first unit writes the block
        and the second call raises `AlreadyRetired` against the file the first
        one just wrote. Six appointments meant one unit stopped and five left
        loaded, with the failure arriving after the repository already said
        retired: exactly the half-stopped state the comment forbids.
        """
        root = make_repo(self.tmpdir(), declarations=("twice-daily-report",))
        runner = RecordingRunner()
        runner.add("id -u", FakeCompleted(stdout=read_output("probe-context.txt")))
        runner.add("launchctl print",
                   FakeCompleted(rc=113, stdout=read_output("launchctl-print-notfound.txt")))
        runner.add("cat ", FakeCompleted(rc=1))
        runner.add("shasum", FakeCompleted(stdout=f"{'0' * 64}  x"))
        import engine.exec as exec_module

        out = io.StringIO()
        with mock.patch.object(exec_module, "step_runner", runner):
            with contextlib.redirect_stdout(out):
                rc = cli.main(["--root", str(root), "retire", "twice-daily-report",
                               "--reason", "superseded by the timer", "--yes"])
        text = out.getvalue()

        self.assertNotIn("already carries a retired block", text,
                         "the second appointment tripped over the block the first "
                         f"one wrote, so it was never stopped:\n{text}")
        self.assertEqual(rc, 0, text)

        # Both units named, not just the first. A report that mentions one and
        # returns 0 would satisfy the assertion above while leaving a unit loaded.
        declaration_file = root / "workflow" / "workloads" / "twice-daily-report.yaml"
        written = declaration_file.read_text(encoding="utf-8")
        self.assertEqual(written.count("\nretired:"), 1,
                         "the retired block was written once per appointment "
                         f"instead of once per declaration:\n{written}")

    def test_retiring_an_already_retired_run_is_still_refused(self):
        """The counter-control. Whatever fixes the case above must not simply
        drop the guard: retiring a run that a human already retired is a
        mistake worth naming, and it is the reason `AlreadyRetired` exists."""
        root = make_repo(self.tmpdir(), declarations=("twice-daily-report",))
        path = root / "workflow" / "workloads" / "twice-daily-report.yaml"
        path.write_text(path.read_text(encoding="utf-8").rstrip("\n") +
                        '\n\nretired:\n  at: "2020-01-01T00:00:00+00:00"\n'
                        '  reason: "retired by a human last year"\n',
                        encoding="utf-8")
        runner = RecordingRunner()
        runner.add("id -u", FakeCompleted(stdout=read_output("probe-context.txt")))
        runner.add("launchctl print",
                   FakeCompleted(rc=113, stdout=read_output("launchctl-print-notfound.txt")))
        runner.add("cat ", FakeCompleted(rc=1))
        runner.add("shasum", FakeCompleted(stdout=f"{'0' * 64}  x"))
        import engine.exec as exec_module

        out = io.StringIO()
        with mock.patch.object(exec_module, "step_runner", runner):
            with contextlib.redirect_stdout(out):
                rc = cli.main(["--root", str(root), "retire", "twice-daily-report",
                               "--reason", "superseded by the timer", "--yes"])
        text = out.getvalue()
        self.assertNotEqual(rc, 0, f"a second retirement passed silently:\n{text}")

    def test_a_dry_run_adoption_says_why_nothing_was_recorded(self):
        rc, out = self.drive("adopt", "calendar-export",
                             print_output="launchctl-print-no-marker.txt", print_rc=0)
        self.assertEqual(rc, 1, out)
        self.assertIn("dry run, nothing was recorded", out,
                      f"the preview kept its reason to itself:\n{out}")

    def test_an_adoption_says_what_it_recorded(self):
        rc, out = self.drive("adopt", "calendar-export", "--yes",
                             print_output="launchctl-print-no-marker.txt", print_rc=0)
        self.assertEqual(rc, 0, out)
        self.assertIn("adopted as it stands", out)


class ProvisionAnswersWithAReport(MachineGuard):
    """`--yes` produced a traceback wherever it had anything at all to say.

    Every path below is one that reaches `Outcome.findings` with something in
    it, which is exactly where `report.Report` used to fall over.
    """

    def drive(self, *extra, declaration="calendar-export", routes=()):
        root = make_repo(self.tmpdir(), declarations=(declaration,))
        runner = RecordingRunner()
        runner.add("id -u", FakeCompleted(stdout=read_output("probe-context.txt")))
        runner.add("launchctl print",
                   FakeCompleted(rc=113, stdout=read_output("launchctl-print-notfound.txt")))
        runner.add("cat ", FakeCompleted(rc=1))
        for needle, completed in routes:
            runner.add(needle, completed)
        import engine.exec as exec_module

        out = io.StringIO()
        with mock.patch.object(exec_module, "step_runner", runner):
            with contextlib.redirect_stdout(out):
                rc = cli.main(["--root", str(root), "provision", declaration,
                               "--yes", *extra])
        return rc, out.getvalue()

    def test_a_dry_run_reports_instead_of_raising(self):
        rc, out = self.drive("--dry-run")
        self.assertEqual(rc, 1, out)
        self.assertIn("dry run, nothing was touched", out)

    def test_the_report_names_the_workload_it_is_about(self):
        # "somewhere in the output" measures nothing here: the header above the
        # report already carries the id. It is the ROW that has to say which
        # workload the sentence belongs to, or a note on a host carrying a dozen
        # units is unattributable.
        _, out = self.drive("--dry-run")
        row = [line for line in out.splitlines() if "dry run, nothing was touched" in line]
        self.assertEqual(len(row), 1, out)
        self.assertIn("calendar-export", row[0],
                      f"the note in the report names no workload:\n{out}")

    def test_the_line_a_human_reads_first_says_what_it_covered(self):
        # The preflight really was clean, so the clean line is not wrong -- but
        # bare, as the first line of a run that goes on to say it was never
        # verified, it reads as the verdict. A clean line has to name its
        # subject, and the outcome has to say so where it is looked for.
        _, out = self.drive("--dry-run")
        first = out.strip().splitlines()[0].strip()
        self.assertNotEqual(first, report.CLEAN_LINE,
                            f"a bare clean opened a run that was never verified:\n{out}")
        self.assertIn("NOT verified", out)

    def test_an_elevation_plan_reports_instead_of_raising(self):
        # The second of the three paths that reach `Outcome.findings` with
        # something in it. This skill never takes elevation, so the steps are
        # printed for a person -- and printing them used to end in a traceback.
        rc, out = self.drive(declaration="elevated-daemon")
        self.assertEqual(rc, 1, out)
        self.assertIn("elevation required", out)
        self.assertIn("no sudo, ever", out)

    def test_a_verify_that_does_not_confirm_reports_instead_of_raising(self):
        # The third path, and the one that matters most: the run went through,
        # the live source did not confirm it, and the answer has to be a report
        # saying so with an exit code of 1. It was a traceback.
        rc, out = self.drive()
        self.assertEqual(rc, 1, out)
        self.assertIn("did not confirm", out)
        self.assertIn("NOT verified", out)

    def test_the_promised_exit_code_of_one_is_reachable_at_all(self):
        # It was not: the traceback came out before any exit code did, so the
        # contract in SKILL.md could not be satisfied from the command line.
        rc, _ = self.drive("--dry-run")
        self.assertEqual(rc, 1)


class RetireIsWiredToBothHalvesOfTheBolt(MachineGuard):
    """The seam between `cli.cmd_retire` and `provision.may_stop`.

    The bolt lives in `provision`, and `test_provision` proves it there. It can
    still be defeated from here, in two opposite directions, and a single case
    catches neither:

      * `dry_run=not args.yes` -- the original defect. `--yes --dry-run` becomes
        a real stop, and `--dry-run` alone becomes an unconfirmed one.
      * `confirmed` never passed -- the bolt then refuses FOREVER, `retire`
        stops being a command, and every no-case above still passes.

    So the three argv a human can type are all driven end to end here, and the
    middle one is the Gegenprobe: without it the whole command could be dead and
    this file would still be green.
    """

    def repo(self):
        root = make_repo(self.tmpdir(), declarations=("calendar-export",))
        return root, root / "workflow" / "workloads" / "calendar-export.yaml"

    def stopped(self):
        """The machine answering that the unit is gone, so a stop is provable."""
        runner = RecordingRunner()
        runner.add("print", FakeCompleted(
            rc=113, stdout=read_output("launchctl-print-notfound.txt")))
        runner.add("id -u", FakeCompleted(stdout=read_output("probe-context.txt")))
        return runner

    def drive(self, *flags):
        import engine.exec as exec_module

        root, path = self.repo()
        before = path.read_text(encoding="utf-8")
        runner = self.stopped()
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(exec_module, "step_runner",
                               lambda step, host, **kw: runner(step.argv, step=step, **kw)):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = cli.main(["--root", str(root), "retire", "calendar-export",
                               "--reason", "superseded by the timer", *flags])
        return rc, runner, path, before, out.getvalue() + err.getvalue()

    def assert_untouched(self, runner, path, before):
        for verb in ("bootout", "disable", "rm ", ".stamp.json"):
            self.assertNotIn(verb, runner.joined_calls,
                             f"a run that was not meant to act ran {verb!r}")
        self.assertEqual(path.read_text(encoding="utf-8"), before,
                         "the declaration was written back by a run that acted on nothing")

    def test_yes_together_with_dry_run_stops_nothing(self):
        rc, runner, path, before, text = self.drive("--yes", "--dry-run")
        self.assertNotEqual(rc, 0, f"a run that stopped nothing exited clean:\n{text}")
        self.assert_untouched(runner, path, before)

    def test_neither_flag_is_refused_and_says_which_two_words_are_missing(self):
        # `dry_run` derived from `yes` would make this a silent preview instead.
        rc, runner, path, before, text = self.drive()
        self.assertEqual(rc, 3, f"an unconfirmed stop is a guard refusal:\n{text}")
        self.assertIn("unconfirmed-stop", text)
        self.assert_untouched(runner, path, before)

    def test_a_plain_yes_really_stops_the_unit(self):
        # The Gegenprobe. Without it `confirmed` could simply never be passed:
        # the command would refuse every argv, and both cases above would pass.
        rc, runner, path, _, text = self.drive("--yes")
        self.assertEqual(rc, 0, f"a proven stop did not exit clean:\n{text}")
        self.assertIn("bootout", runner.joined_calls)
        self.assertIn("disable", runner.joined_calls)
        self.assertIn("retired:", path.read_text(encoding="utf-8"))

    def test_the_run_was_held_under_the_workload_lock_of_that_repository(self):
        # `root` was not passed on that same line either. Without it the run
        # takes `nullcontext()` instead of the lock, so two sessions retire the
        # same id at once, and the write falls back to `w.source_path` rather
        # than the repository the caller named. The declaration alone does not
        # measure that -- in this fixture the two paths are the same file -- so
        # the LOCK is what is asserted: it exists only under a real root.
        _, _, path, _, _ = self.drive("--yes")
        self.assertIn("retired:", path.read_text(encoding="utf-8"))
        lock = path.parents[2] / lock_mod.LOCK_DIR / "calendar-export.lock"
        self.assertTrue(lock.exists(),
                        f"no workload lock under the root that was named: {lock}")


class ADryPublishSaysWhichProofsAreArmed(MachineGuard):
    """Both proofs read "not asked" after a dry run, because it reaches neither.
    So the dry run has to name the one that is armed, or a forgotten `--url` and
    a present one print the same thing and the missing reachability check is
    discovered by the run that was supposed to take it."""

    def outcome(self):
        publish = mod("engine.publish")
        return publish.Outcome(
            action="publish", delivered=False, reachable=None,
            steps=publish.steps_for("<html></html>\n", "~/site/workloads"),
            evidence="dry run: 3 step(s) prepared, nothing written")

    def test_the_url_it_would_check_is_named(self):
        said = cli._publish_report(self.outcome(),
                                   url="http://host-a:8080/workloads/", wrote=False)
        self.assertIn("http://host-a:8080/workloads/", said)
        self.assertIn("reachable: not asked", said)

    def test_without_a_url_nothing_pretends_a_check_is_coming(self):
        said = cli._publish_report(self.outcome(), url=None, wrote=False)
        self.assertNotIn("would fetch", said)

    def test_a_real_run_does_not_offer_a_preview_of_what_already_happened(self):
        said = cli._publish_report(self.outcome(), url="http://host-a:8080/",
                                   wrote=True)
        self.assertNotIn("would", said)


class TheHostFilterReachesThePage(MachineGuard):
    """`--host` decides what was asked, and the page has to be told.

    The renderer can explain a silence about a run placed on a machine nobody
    reconciled, but only if it is told which machines WERE reconciled. That
    hand-over is one keyword in `_page`, it is invisible when it goes missing,
    and a test written against the renderer alone stays green without it: it
    passes the argument itself.

    So this measures the seam rather than either side of it. Found on
    2026-08-24 by a mutation that emptied the hand-over and was not caught.
    """

    def rendered_with(self, argv_host):
        seen = {}
        view = cli._module("view")
        real = view.render

        def spy(rep, workloads, **kw):
            seen.update(kw)
            return real(rep, workloads, **kw)

        root = make_repo(self.tmpdir())
        out = io.StringIO()
        with mock.patch.object(view, "render", spy):
            with contextlib.redirect_stdout(out):
                with contextlib.redirect_stderr(io.StringIO()):
                    cli.main(["--root", str(root), "view", "--no-probe",
                              "--now", "2026-08-24T12:00:00+02:00", *argv_host])
        return seen

    def test_the_machines_named_on_the_command_line_reach_the_renderer(self):
        seen = self.rendered_with(["--host", "host-a"])
        self.assertEqual(tuple(seen.get("hosts") or ()), ("host-a",),
                         "the renderer was not told which machine was asked, "
                         "so it cannot explain a silence about any other")

    def test_naming_no_machine_hands_over_no_machine(self):
        # Nothing was excluded, so there is nothing for the page to explain.
        seen = self.rendered_with([])
        self.assertEqual(tuple(seen.get("hosts") or ()), (),
                         "the page was told a filter existed where none did")


class SilenceIsTheDefault(MachineGuard):
    """`reconcile` looks. It does not speak unless it is asked to.

    The second half is the load bearing one: without the flag the notify STATE
    must not be touched either. An investigating run from another machine would
    otherwise meet an empty state file and reset the dampening of an alarm that
    had already been confirmed, and nothing anywhere would raise an error.
    Looking and might-beep are two commands, the way `provision --yes` and
    `retire --yes` already are in this skill.

    Measured through `cli.main` and its printed output rather than by patching
    the notifier: the command builds its own module handle, so a patch on the
    test's handle proves the patch works and nothing about the wiring. That
    exact shape already let one seam go unmeasured in this suite today.
    """

    def drive(self, *argv):
        root = make_repo(self.tmpdir())
        runner = RecordingRunner()
        import engine.exec as exec_module
        out = io.StringIO()
        with mock.patch.object(exec_module, "step_runner", runner):
            with contextlib.redirect_stdout(out):
                cli.main(["--root", str(root), "reconcile", "--no-probe", *argv])
        return root, out.getvalue()

    def state_files(self, root):
        folder = root / ".bridge"
        return sorted(p.name for p in folder.glob("notify*")) if folder.exists() else []

    def test_a_reconcile_without_the_flag_says_nothing_to_anybody(self):
        _root, out = self.drive()
        self.assertNotIn(
            "notify:", out,
            f"reconcile reached for the notifier without being asked. A command "
            f"somebody types to LOOK must not be able to page anyone:\n{out}")

    def test_a_reconcile_without_the_flag_leaves_no_state_behind(self):
        root, _out = self.drive()
        self.assertEqual(
            self.state_files(root), [],
            "an investigating run wrote notify state, so it silently reset the "
            "dampening of an alarm that had already been confirmed elsewhere")

    def test_the_flag_is_what_turns_it_on(self):
        root, out = self.drive("--notify")
        self.assertIn(
            "notify:", out,
            f"the flag exists and reaches nothing, which is this whole change's "
            f"own defect one level up:\n{out}")
        self.assertEqual(
            self.state_files(root), ["notify-state.json"],
            "asked to notify, it remembered nothing, so the next pass repeats "
            "every message it just sent")


class TwoDeclarationsMustNotResolveToOneUnit(MachineGuard):
    """A label collision is INVISIBLE rather than wrong, which is why it is here.

    Possible since `placement.label_prefix` exists: prefix `a.b` with id `c`
    and prefix `a` with id `b` plus an appointment named `c` both produce
    `a.b.c`. Whichever declaration loses does not fail; it silently claims the
    other one's unit, ownership stamp and trace, and reconcile then reports one
    of them as in sync against the other one's evidence.

    The check runs over ALL declarations even when `--id` names one, because a
    collision is a property of the set and a filter must not be able to hide it.
    """

    def _load(self, *names):
        return [self.load(name) for name in names]

    def load(self, name):
        for folder in (CORPUS, DERIVED):
            path = folder / f"{name}.yaml"
            if path.exists():
                return model.load_declaration(path)
        raise AssertionError(name)

    def test_the_collision_is_found(self):
        findings = cli._label_collisions(
            self._load("prefix-collision-a", "prefix-collision-b"))
        self.assertEqual(len(findings), 1, "one collision, reported once")
        self.assertIn("org.example.legacy.poller", findings[0].detail)

    def test_both_ids_are_named_so_a_human_knows_where_to_look(self):
        findings = cli._label_collisions(
            self._load("prefix-collision-a", "prefix-collision-b"))
        self.assertIn("legacy", findings[0].detail)
        self.assertIn("poller", findings[0].detail)

    def test_the_finding_says_what_to_do(self):
        findings = cli._label_collisions(
            self._load("prefix-collision-a", "prefix-collision-b"))
        self.assertIn("label_prefix", findings[0].hint + findings[0].key_path)

    def test_declarations_that_do_not_collide_stay_silent(self):
        self.assertEqual(
            cli._label_collisions(self._load("prefix-collision-a")), [])

    def test_a_runtime_without_unit_names_is_not_a_collision(self):
        # manual and external give a run no name on the machine, so several of
        # them must not be read as claiming one unit.
        inert = [w for w in self._load("prefix-collision-a")]
        self.assertEqual(cli._label_collisions(inert), [])


class TheConfiguredLabelPrefixReachesTheMachine(MachineGuard):
    """`workloads.label_prefix` was read from the config and never applied.

    `configure(cfg)` exists in the backend registry, rebuilds every backend from
    the live configuration, and had NO CALLER anywhere in the skill. The
    registry therefore held the instances from `build(None)`, that is the
    built-in default. An instance that set its own prefix in bridge-config.yaml
    got `bridge.<id>` anyway: no error, no warning, no trace in the report.

    The test that was supposed to cover this is called "the label prefix comes
    from config" and asserts the DEFAULT, so it could never see the gap. A test
    whose name is a promise has to keep it.

    Every command goes through `_bridge`, which is why the wiring belongs there
    and is measured here rather than per command.
    """

    def restore_backends(self):
        backends.configure(config.Config())

    def root_with_prefix(self, prefix):
        root = make_repo(self.tmpdir(), declarations=("block-style-report",),
                         config=f"workloads:\n  label_prefix: {prefix}\n")
        return root

    def bridge(self, root):
        self.addCleanup(self.restore_backends)
        return cli._bridge(SimpleNamespace(root=str(root)))

    def test_a_configured_prefix_reaches_the_rendered_unit(self):
        root = self.root_with_prefix("acme")
        _, cfg = self.bridge(root)
        self.assertEqual(cfg.label_prefix, "acme")
        w = model.load_all(root, cfg)[0]
        self.assertEqual(backends.get_backend("launchd").label(w),
                         "acme.block-style-report")

    def test_the_default_is_unchanged_when_nothing_is_configured(self):
        root = make_repo(self.tmpdir(), declarations=("block-style-report",))
        _, cfg = self.bridge(root)
        w = model.load_all(root, cfg)[0]
        self.assertEqual(backends.get_backend("launchd").label(w),
                         "bridge.block-style-report")

    def test_a_declaration_prefix_still_wins_over_the_configured_one(self):
        # Two knobs, one order: the declaration describes a unit that already
        # exists, the config describes what THIS instance creates.
        root = self.root_with_prefix("acme")
        _, cfg = self.bridge(root)
        w = model.load_declaration(
            DERIVED / "adopted-prefix-daemon.yaml")
        self.assertEqual(backends.get_backend("launchd").label(w),
                         "org.example.scheduler.legacy-poller")


class AnAlarmThatRefusesToMeasureIsAPromiseWithoutAFloor(MachineGuard):
    """`--notify` with `--no-probe` asks to be told without taking the reading.

    Found on a live machine on 2026-08-26. The half-hourly refresher calls
    reconcile twice on purpose, so that a failed publish cannot take the alarm
    with it. The first call carries `--notify`, and it also carried
    `--no-probe`; the second one probes and never notifies. The verdict a
    declaration paid for with its own `reconcile.probe` therefore reached a
    page and nothing else, and a run that was up but had stopped answering was
    red on a web page nobody was watching at three in the morning.

    Every link works: a failed probe classifies as `stopped` at high severity,
    `stopped` sits in the `failure` bucket, and a declaration asking for
    `failure` gets a message. The chain was simply never given an input,
    which is the same shape as a wrapper ending in a bare `exit 0`.

    The contradiction only exists where something declared a probe. Where
    nothing did, `--no-probe` asks to skip a measurement that was never going
    to happen, and refusing that would be a rule about nothing.

    Nothing here reaches a machine, and that is itself one of the cases: the
    refusal has to land before the first reading, or it arrives as one more
    line under a report that already looks like an answer.
    """

    MIT_SONDE = (
        "reconcile:\n"
        '  probe: "curl -fsS -m 10 http://127.0.0.1:8012/health"\n'
        '  expect: "ok"\n')
    MIT_CHECK_REF = "reconcile:\n  check_ref: sample\n"

    def repo(self, *, reconcile_block=MIT_SONDE, second=""):
        root = self.tmpdir()
        make_repo(root, declarations=())
        self.write(root, "watched-agent", reconcile_block)
        if second:
            self.write(root, "second-agent", second)
        return root

    def write(self, root, wid, reconcile_block):
        (root / "workflow" / "workloads" / f"{wid}.yaml").write_text(
            "schema_version: 1\n"
            "scope: user\n"
            f"id: {wid}\n"
            f'purpose: "A run that named the question it wants asked"\n'
            "placement: {host: host-a, kind: agent, runtime: launchd, owner: bridge}\n"
            "execution:\n"
            '  command: ["/bin/sh", "/tmp/agent.sh"]\n'
            "response:\n"
            "  evidence: log-trace\n"
            "  notify_on: [failure]\n"
            "  notify_via: example-notify\n"
            + reconcile_block,
            encoding="utf-8")

    def pruefe(self, root, *flags):
        """Returns (rc, said, reached_machine).

        `reached_machine` is how the ALLOWED cases prove themselves, and it is
        not a trick: MachineGuard turns the first real `ssh` into an
        AssertionError, so a command that gets that far is a command that was
        not stopped at the gate. There is no runner seam through `cli.main`,
        and inventing one for a flag check would be a second way in that
        nothing else uses.

        NOT named `run`: unittest calls that one, and a case that shadows it
        does not fail, it vanishes from the tally while discovery still counts
        it. Paid for once already, in the class above.
        """
        out, err = io.StringIO(), io.StringIO()
        reached = False
        rc = None
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = cli.main(["--root", str(root), "reconcile", "--all", *flags])
        except AssertionError as exc:
            if "tried to exec" not in str(exc):
                raise
            reached = True
        return rc, out.getvalue() + err.getvalue(), reached

    # -- the contradiction itself --------------------------------------------
    def test_notifying_without_probing_is_refused(self):
        rc, _, reached = self.pruefe(self.repo(), "--notify", "--no-probe")
        self.assertEqual(rc, 3)
        self.assertFalse(reached)

    def test_the_refusal_names_the_declaration_that_paid_for_the_probe(self):
        _, said, _r = self.pruefe(self.repo(), "--notify", "--no-probe")
        self.assertIn("watched-agent", said)

    def test_the_refusal_names_both_flags_so_the_reader_knows_which_to_drop(self):
        _, said, _r = self.pruefe(self.repo(), "--notify", "--no-probe")
        self.assertIn("--no-probe", said)
        self.assertIn("--notify", said)

    def test_a_check_ref_counts_as_a_declared_probe(self):
        rc, said, _r = self.pruefe(
            self.repo(reconcile_block=self.MIT_CHECK_REF), "--notify", "--no-probe")
        self.assertEqual(rc, 3)
        self.assertIn("watched-agent", said)

    def test_every_declaration_that_paid_is_named_and_not_just_the_first(self):
        root = self.repo(second=self.MIT_CHECK_REF)
        _, said, _r = self.pruefe(root, "--notify", "--no-probe")
        self.assertIn("watched-agent", said)
        self.assertIn("second-agent", said)

    # -- the silences, which are cases too ------------------------------------
    def test_without_a_declared_probe_the_flags_do_not_contradict(self):
        # A rule about nothing is worse than no rule: it teaches the reader
        # that the pair is forbidden, and the next repository has a probe.
        root = self.repo(reconcile_block="")
        _rc, said, reached = self.pruefe(root, "--notify", "--no-probe")
        self.assertNotIn("refused", said.lower())
        self.assertTrue(reached, "it was stopped at the gate instead of getting on with it")

    def test_looking_without_notifying_stays_free(self):
        # Reading is always allowed. The pair is a promise, a single flag is not.
        _rc, said, reached = self.pruefe(self.repo(), "--no-probe")
        self.assertNotIn("refused", said.lower())
        self.assertTrue(reached, "it was stopped at the gate instead of getting on with it")

    # -- where the refusal lands ----------------------------------------------
    def test_the_refusal_lands_before_the_first_reading(self):
        # MachineGuard raises on any real exec. Reaching a machine would end
        # this case with its AssertionError rather than a refusal, which is
        # exactly the difference between a gate and a remark under a report.
        rc, said, reached = self.pruefe(self.repo(), "--notify", "--no-probe")
        self.assertFalse(reached)
        self.assertNotIn("tried to exec", said)
        self.assertEqual(rc, 3)


CONFIG_WITH_LINKS = """\
work:
  enabled: true
workloads:
  enabled: true
  dir: workflow/workloads
  stamp_dir: "$HOME/.bridge/workloads"
  label_prefix: bridge
  step_timeout_sec: 60
  probe_timeout_sec: 30
  ssh_connect_timeout_sec: 10
  view:
    links:
      - label: Operations
        href: ../betrieb/
      - label: Services
        href: ../betrieb/dienste.html
"""


class TheNeighbourLinksComeFromConfigurationAndNowhereElse(MachineGuard):
    """The bar of other pages is instance data, so the core skill may not hold it.

    A host name, a port or a path written into `view.py` would travel to every
    Bridge that pulls this skill and point each of them at somebody else's
    machine. So the targets are read from the `workloads:` block, the bar is
    absent when nothing is configured, and a half-written entry is refused by
    name rather than quietly dropped: a link nobody notices is missing is a
    link nobody misses until the page it pointed at is the one that was needed.
    """

    def cfg_for(self, text):
        root = make_repo(self.tmpdir(), config=text)
        return config.load_config(root)

    def test_the_configured_entries_come_back_as_label_and_target(self):
        got = cli.view_links(self.cfg_for(CONFIG_WITH_LINKS))
        self.assertEqual(got, (("Operations", "../betrieb/"),
                               ("Services", "../betrieb/dienste.html")))

    def test_a_configuration_without_the_block_yields_no_bar_and_no_error(self):
        # A Bridge that has never configured this must still be able to render.
        self.assertEqual(cli.view_links(self.cfg_for(DEFAULT_CONFIG)), ())

    def test_a_configuration_file_that_is_not_there_is_not_a_crash(self):
        cfg = config.Config(source=str(self.tmpdir() / "bridge-config.yaml"))
        self.assertEqual(cli.view_links(cfg), ())

    def test_half_an_entry_is_refused_by_name(self):
        broken = CONFIG_WITH_LINKS.replace("        href: ../betrieb/\n", "", 1)
        with self.assertRaises(errors.ConfigError) as caught:
            cli.view_links(self.cfg_for(broken))
        said = str(caught.exception)
        self.assertIn("view.links[0]", said,
                      "the refusal has to say WHICH entry, or a list of six "
                      "sends somebody hunting")
        self.assertIn("href", said)

    def test_a_block_that_is_not_a_list_is_refused_rather_than_ignored(self):
        broken = CONFIG_WITH_LINKS.replace(
            "    links:\n"
            "      - label: Operations\n"
            "        href: ../betrieb/\n"
            "      - label: Services\n"
            "        href: ../betrieb/dienste.html\n",
            "    links: ../betrieb/\n")
        with self.assertRaises(errors.ConfigError):
            cli.view_links(self.cfg_for(broken))


class TheNeighbourLinksReachThePage(MachineGuard):
    """The seam, not either side of it.

    `view_links` can be perfect and `_page` can forget to hand the answer over,
    and a test written against the renderer alone stays green: it passes the
    argument itself. That is the exact shape of the gap `--host` left open in
    this same function on 2026-08-24.
    """

    def rendered_with(self, text):
        seen = {}
        view = cli._module("view")
        real = view.render

        def spy(rep, workloads, **kw):
            seen.update(kw)
            return real(rep, workloads, **kw)

        root = make_repo(self.tmpdir(), config=text)
        out = io.StringIO()
        with mock.patch.object(view, "render", spy):
            with contextlib.redirect_stdout(out):
                with contextlib.redirect_stderr(io.StringIO()):
                    cli.main(["--root", str(root), "view", "--no-probe",
                              "--now", "2026-08-24T12:00:00+02:00"])
        return seen, out.getvalue()

    def test_a_configured_bar_arrives_at_the_renderer(self):
        seen, _ = self.rendered_with(CONFIG_WITH_LINKS)
        self.assertEqual(tuple(seen.get("links") or ()),
                         (("Operations", "../betrieb/"),
                          ("Services", "../betrieb/dienste.html")))

    def test_the_written_page_carries_the_bar(self):
        # All the way to the bytes on disk, because that is what a browser gets.
        root = make_repo(self.tmpdir(), config=CONFIG_WITH_LINKS)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with contextlib.redirect_stderr(io.StringIO()):
                cli.main(["--root", str(root), "view", "--no-probe",
                          "--now", "2026-08-24T12:00:00+02:00"])
        page = (root / ".bridge" / "workloads.html").read_text(encoding="utf-8")
        self.assertIn('<nav class="links"', page)
        self.assertIn("../betrieb/", page)

    def test_no_configuration_hands_over_no_bar(self):
        seen, _ = self.rendered_with(DEFAULT_CONFIG)
        self.assertEqual(tuple(seen.get("links") or ()), ())


class ThePublishReportNamesEveryFileItCarried(MachineGuard):
    """A count would let a run in which the stylesheet failed read exactly like
    its mirror image, and the two need different repairs."""

    def outcome(self, *attachments, **kw):
        publish = mod("engine.publish")
        return publish.Outcome(
            action="publish", delivered=True, reachable=None,
            attachments=tuple(attachments),
            evidence="delivered to host-a:/site/workloads/index.html", **kw)

    def delivery(self, name, delivered, evidence=""):
        publish = mod("engine.publish")
        return publish.Delivery(name=name, delivered=delivered, evidence=evidence)

    def test_each_attachment_stands_on_a_line_of_its_own(self):
        said = cli._publish_report(
            self.outcome(self.delivery("style.css", True),
                         self.delivery("data.json", False, "data.json could not be "
                                                           "read back: rc=1")),
            url=None, wrote=True)
        self.assertIn("attached style.css: delivered", said)
        self.assertIn("attached data.json: NOT delivered", said)
        self.assertIn("rc=1", said)

    def test_a_report_without_baggage_says_nothing_about_any(self):
        said = cli._publish_report(self.outcome(), url=None, wrote=True)
        self.assertNotIn("attached", said)

    def test_what_was_left_behind_is_named_with_its_consequence(self):
        # The other half of the corrected marker: nothing here removes a file,
        # so a page dropped from the output goes on being served.
        said = cli._publish_report(self.outcome(leftovers=("dienste.html",)),
                                   url=None, wrote=True)
        self.assertIn("dienste.html", said)
        self.assertIn("older than this page", said)

    def test_a_real_run_still_offers_no_preview_of_what_already_happened(self):
        # The word `would` belongs to the dry run alone, and the new lines must
        # not smuggle it into a report about work that is finished.
        said = cli._publish_report(
            self.outcome(self.delivery("style.css", True), leftovers=("old.html",)),
            url="http://host-a:8080/", wrote=True)
        self.assertNotIn("would", said)


class TheExitCodeCountsEveryFileThatWasAskedFor(MachineGuard):
    """`complete`, not `ok`, decides what the process returns.

    The page keeps its own verdict when an attachment fails, and that is the
    point of separating them. The RUN does not: it was asked for three files
    and delivered two. Measured through `cli.main` and not on the `Outcome`,
    because the property and the line that reads it are two things, and this
    file exists mostly because of flags that were parsed and then dropped one
    layer down.
    """

    def drive(self, outcome):
        import engine.cli as cli_module
        import engine.publish as publish_module

        root = make_repo(self.tmpdir())
        with mock.patch.object(cli_module, "_context",
                               lambda *a, **kw: SimpleNamespace(home="/home/x")):
            with mock.patch.object(publish_module, "publish",
                                   lambda *a, **kw: outcome):
                with contextlib.redirect_stdout(io.StringIO()) as out:
                    rc = cli.main(["--root", str(root), "publish", "--no-probe",
                                   "--to", "host-a", "--dest", "/srv/site",
                                   "--now", "2026-08-24T12:00:00+02:00", "--yes"])
        return rc, out.getvalue()

    def outcome(self, *attachments):
        publish = mod("engine.publish")
        return publish.Outcome(action="publish", delivered=True, reachable=True,
                               evidence="delivered", attachments=attachments)

    def delivery(self, name, delivered, evidence=""):
        return mod("engine.publish").Delivery(name=name, delivered=delivered,
                                              evidence=evidence)

    def test_a_run_that_delivered_everything_exits_clean(self):
        rc, _ = self.drive(self.outcome(self.delivery("style.css", True)))
        self.assertEqual(rc, 0)

    def test_a_run_that_lost_an_attachment_does_not_exit_clean(self):
        rc, said = self.drive(self.outcome(self.delivery("style.css", False, "rc=1")))
        self.assertEqual(rc, 1,
                         "the page was fine, so the run reported itself clean "
                         "and the file that never arrived is a line nobody has "
                         "to read")
        self.assertIn("style.css", said)

    def test_a_directory_this_run_did_not_sweep_is_not_a_failure(self):
        # A leftover is information. Turning it into an exit code would make
        # every second publish look broken.
        publish = mod("engine.publish")
        rc, said = self.drive(publish.Outcome(action="publish", delivered=True,
                                              reachable=True, evidence="delivered",
                                              leftovers=("dienste.html",)))
        self.assertEqual(rc, 0)
        self.assertIn("dienste.html", said)

    def test_a_clean_directory_gets_no_line_about_leftovers(self):
        _, said = self.drive(self.outcome())
        self.assertNotIn("left behind", said)


class TheOffSwitchIsRealOrItIsNotDocumented(MachineGuard):
    """`workloads.enabled: false` has to stop the skill, or SKILL.md has to stop
    saying it does.

    It said it: "Guard. `workloads.enabled` must not be `false`". The loader
    parsed the key, the dataclass carried it, the shipped example set it to
    `true`, and no line of code ever asked. An instance that switched the skill
    off had a skill that kept running, and the only way to find that out was to
    try it.

    The refusal is a Refused, so it leaves through exit code 3, which is the
    code the handbook already gives to a guard.
    """

    OFF = "workloads:\n  enabled: false\n  dir: workflow/workloads\n"
    ON = "workloads:\n  enabled: true\n  dir: workflow/workloads\n"
    ABSENT = "work:\n  enabled: true\n"

    def repo(self, config):
        return make_repo(self.tmpdir(), declarations=("calendar-export",), config=config)

    def run_cli(self, root, *argv):
        err = io.StringIO()
        out = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
            rc = cli.main(["--root", str(root), *argv])
        return rc, out.getvalue() + err.getvalue()

    #: One read, one that would write, and one that would reach a machine. The
    #: guard sits in the single function every subcommand passes through, and
    #: three different shapes are what prove that rather than assert it.
    COMMANDS = (
        ("list",),
        ("show", "calendar-export"),
        ("validate", "--all"),
        ("reconcile", "--all", "--no-probe"),
        ("provision", "calendar-export", "--dry-run"),
        ("retire", "calendar-export", "--reason", "switched off for the test"),
    )

    def test_a_disabled_skill_refuses_every_subcommand(self):
        root = self.repo(self.OFF)
        for argv in self.COMMANDS:
            with self.subTest(command=argv[0]):
                rc, text = self.run_cli(root, *argv)
                self.assertEqual(
                    rc, 3,
                    f"`{argv[0]}` ran with workloads.enabled false and exited "
                    f"{rc}:\n{text}")

    def test_the_refusal_names_the_key_and_the_file_it_read(self):
        root = self.repo(self.OFF)
        _, text = self.run_cli(root, "list")
        self.assertIn("workloads.enabled", text,
                      f"the refusal does not name the key that caused it:\n{text}")
        self.assertIn("bridge-config.yaml", text,
                      f"the refusal does not say which file it read:\n{text}")

    def test_an_absent_block_is_defaults_and_never_a_refusal(self):
        # A Bridge that has never configured this skill still has to be able to
        # run it. Absence is not a `false`.
        rc, text = self.run_cli(self.repo(self.ABSENT), "list")
        self.assertNotEqual(rc, 3, f"a missing workloads block was read as off:\n{text}")

    def test_the_switch_on_is_not_a_refusal(self):
        rc, text = self.run_cli(self.repo(self.ON), "list")
        self.assertNotEqual(rc, 3, f"an enabled skill refused itself:\n{text}")


class WhatShowSaysAboutRights(MachineGuard):
    """`show` muss die Rechte NENNEN, sonst war der ganze Block umsonst.

    Das Argument fuer den `rights:`-Block war, dass die Schicht, die ueber
    Laeufe berichtet, ihn zeigen kann, statt dass er in Zeile 331 eines
    Wrapper-Skripts steht. Ein Block, den nichts rendert, ist dieser Wrapper
    mit einer schoeneren Adresse.
    """

    def lines(self, raw):
        # Die gemeinsame Ableitung, nicht die des Kommandos: `show` im Terminal
        # und die veroeffentlichte Ansicht im Browser lesen dieselbe Funktion.
        from engine import model as m
        return m.rights_summary(raw)

    def test_the_view_reads_the_same_summary_as_the_terminal(self):
        """Zwei Zusammenfassungen desselben Blocks driften, und die, die driftet,
        ist immer die, die niemand aufruft."""
        from engine import view
        import inspect
        self.assertIn("model.rights_summary", inspect.getsource(view.rows),
                      "die Ansicht baut sich ihre eigene Fassung")

    def test_an_absent_block_says_it_is_declaration_only(self):
        # Nicht schweigen: die Abwesenheit ist eine Aussage, und zwar die
        # strengste, die es hier gibt.
        self.assertEqual(["rights: not declared (declaration only; this skill does not enforce it)"],
                         self.lines({}))

    def test_a_star_reads_as_any_host_not_as_a_star(self):
        # `fetch=*` in einer Zeile voller Kommata liest sich wie ein Eintrag
        # unter vielen. Es ist die weiteste Erlaubnis, die dieser Block kennt.
        out = "\n".join(self.lines({"rights": {"standing": {
            "tools": "WebFetch", "read_scope": "a", "fetch_scope": ["*"],
            "reaches_humans": False}}}))
        self.assertIn("fetch=any host", out)

    def test_bare_bash_is_found_in_every_spelling(self):
        from engine import model as m
        for tools in ("Bash", "Read,Bash", "Read Bash", "Bash(*)", "Read, Bash(*) ,Glob",
                      "Read\tBash Glob"):
            self.assertTrue(m.RIGHTS_GENERIC_SHELL_PATTERN.search(tools), tools)
        for tools in ("Bash(python3 /p/x.py:*)", "Read,Bash(python3 /p/x.py:*)", "Read,Glob",
                      "Read Bash(echo hi:*)"):
            self.assertFalse(m.RIGHTS_GENERIC_SHELL_PATTERN.search(tools), tools)

    def test_a_home_relative_scope_is_refused(self):
        from engine import model as m
        self.assertFalse(m.RIGHTS_SCOPE_PATTERN.match("~/notes"))
        self.assertTrue(m.RIGHTS_SCOPE_PATTERN.match("notes/~x"))

    def test_a_level_that_reaches_people_says_who_and_how_often(self):
        out = "\n".join(self.lines({"rights": {
            "standing": {"tools": "Read", "read_scope": "a", "reaches_humans": False},
            "escalation": {"reaches_humans": True,
                           "unlocked_by": {"no_progress_ticks": 3},
                           "recipients": [{"mandant_ref": "someone",
                                           "channel_ref": "somewhere"}],
                           "caps": {"total": 3}}}}))
        self.assertIn("REACHES someone/somewhere", out)
        self.assertIn("total=3", out)
        self.assertIn("no_progress_ticks=3", out)

    def test_the_way_out_is_printed_because_it_is_part_of_the_permission(self):
        out = "\n".join(self.lines({"rights": {
            "standing": {"tools": "Read", "read_scope": "a", "reaches_humans": False},
            "stop": {"flag": "~/x.stop"}, "reply": {"flag": "~/x.reply"},
            "consent": {"flag": "~/x.consent"}}}))
        self.assertIn("rights.stop: ~/x.stop", out)
        self.assertIn("rights.consent: ~/x.consent", out)
        self.assertIn("rights.reply: ~/x.reply", out)


class ViewJsonIsOneDocumentOnStdout(MachineGuard):
    """`view --json` is read by a program, so stdout carries the document and
    nothing else: the honest sentence moves to stderr, and no page is written."""

    def test_stdout_parses_and_no_page_is_written(self):
        import json

        root = make_repo(self.tmpdir(), declarations=("calendar-export",))
        out, err = io.StringIO(), io.StringIO()
        # The machine is not the subject here, and the guard refuses ssh: the
        # report comes from a stub, the declarations from the repository.
        reconcile = cli._module("reconcile")
        stub = mod("engine.report").Report(findings=[], header="0 of 1 machine(s) probed")
        with mock.patch.object(reconcile, "run", lambda *a, **kw: stub), \
                contextlib.redirect_stdout(out):
            with contextlib.redirect_stderr(err):
                cli.main(["--root", str(root), "view", "--no-probe", "--json",
                          "--host", "host-a",
                          "--now", "2026-08-24T12:00:00+02:00"])
        doc = json.loads(out.getvalue())
        self.assertEqual(doc["schema"], 1)
        self.assertEqual(doc["host"], "host-a")
        self.assertEqual(doc["generated_at"], "2026-08-24T12:00:00+02:00")
        self.assertTrue(doc["runs"], "the repository's declarations are missing")
        self.assertTrue(err.getvalue().strip(), "the reconcile sentence was dropped")
        self.assertFalse((root / ".bridge" / "workloads.html").exists(),
                         "--json wrote the page as well")
