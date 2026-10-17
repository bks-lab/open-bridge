"""End to end over the seven real cases, plus the discipline this skill ships under.

The lifecycle table is the acceptance criterion: for each inventory derived
declaration it states what the whole chain must do, including the three that
must refuse. The hygiene block at the bottom is what keeps the skill promotable:
a single instance name anywhere in this tree, fixtures included, and it stops
being core.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from tests.conftest import (
    CONFIG_REL,
    CORPUS,
    CORPUS_IDS,
    DERIVED,
    FIXTURE_HOME,
    FIXTURE_TZ,
    FIXTURE_UID,
    FakeCompleted,
    FakeHost,
    MachineGuard,
    RecordingRunner,
    ROUTER_REL,
    RouterUnavailable,
    SKILL_DIR,
    blocklist_hits,
    companion_dirs,
    completed_from,
    core_files_outside_the_skill,
    engine_sources,
    forbidden_literals,
    instance_name_hits,
    load_promote_router,
    make_repo,
    mod,
    promote_blocklist,
    read_output,
    repo_root,
    skill_text_files,
)

model = mod("engine.model")
errors = mod("engine.errors")
render_mod = mod("engine.render")
base = mod("engine.backends.base")
provision = mod("engine.provision")
reconcile = mod("engine.reconcile")
report = mod("engine.report")
config = mod("engine.config")
cli = mod("engine.cli")

#: id -> what the whole chain has to do with it. Three of the seven refuse, and
#: each refuses for its own reason.
LIFECYCLE = {
    "calendar-export": ("provision", None),
    "voicememo-notify": ("provision", None),
    "daily-health-report": ("refuse", "degraded-backend"),
    "contract-review-reminder": ("refuse", "degraded-backend"),
    "voice-channel": ("refuse", "retired-declaration"),
    "chat-channel": ("not-provisionable", None),
    "public-funnel": ("not-provisionable", None),
}


class TheSevenRealCases(MachineGuard):

    def ctx(self, **overrides):
        kwargs = dict(uid=FIXTURE_UID, home=FIXTURE_HOME,
                      stamp_dir=f"{FIXTURE_HOME}/.bridge/workloads",
                      dispatcher_registry=f"{FIXTURE_HOME}/.bridge/dispatcher.yaml",
                      host_timezone=FIXTURE_TZ)
        kwargs.update(overrides)
        return base.RenderContext(**kwargs)

    def test_the_table_covers_every_corpus_case(self):
        self.assertEqual(set(LIFECYCLE), set(CORPUS_IDS))

    def test_each_case_reaches_its_declared_outcome(self):
        host = FakeHost.from_fixture("host-a")
        for wid, (outcome, reason) in LIFECYCLE.items():
            with self.subTest(workload=wid):
                w = model.load_declaration(CORPUS / f"{wid}.yaml")
                if outcome == "not-provisionable":
                    with self.assertRaises(errors.NotProvisionable):
                        render_mod.render(w, host, self.ctx())
                    continue
                artifact = render_mod.render(w, host, self.ctx())
                obs = provision.Observation(
                    reachable=True, present=False, enabled=True, running=False,
                    persistently_disabled=False,
                    file_digests={str(f.path): None for f in artifact.files},
                    stamp=None, marker_id=None, marker_digest=None)
                plan = provision.plan(w, artifact, obs)
                if outcome == "refuse":
                    self.assertEqual(plan.action, "refuse")
                    self.assertEqual(plan.reason_code, reason)
                else:
                    self.assertEqual(plan.action, "create")

    def after_a_provision(self, w, artifact, *, host, stamped: bool):
        """What the machine looks like once this workload has been provisioned.

        `marker_digest` is the digest of the DECLARATION, because that is what a
        backend really writes into the unit: the artifact digest cannot live in
        there, it covers the very bytes the marker is part of.
        """
        return provision.Observation(
            reachable=True, present=True, enabled=True, running=True,
            persistently_disabled=False,
            file_digests={str(f.path): base.digest_of([f]) for f in artifact.files},
            stamp=(provision._stamp_for(w, host, artifact, adopted=False)
                   if stamped else None),
            marker_id=w.id,
            marker_digest=model.declaration_digest(w))

    def test_provision_then_provision_again_is_a_no_op(self):
        # The name means what it says now. It used to sit over a body that set
        # `stamp=None` and asserted refuse/marker-without-stamp -- a real
        # assertion about a DIFFERENT property, under a name nobody would read
        # twice. Running provision twice changing nothing is the condition for
        # being allowed to automate it at all, so it is worth its own case.
        host = FakeHost.from_fixture("host-a")
        for wid in ("calendar-export", "voicememo-notify"):
            with self.subTest(workload=wid):
                w = model.load_declaration(CORPUS / f"{wid}.yaml")
                artifact = render_mod.render(w, host, self.ctx())
                after = self.after_a_provision(w, artifact, host=host, stamped=True)
                plan = provision.plan(w, artifact, after)
                self.assertEqual(plan.action, "noop",
                                 f"a second provision of {wid} would {plan.action} "
                                 f"({plan.reason_code}) a healthy unit")
                self.assertEqual(list(plan.steps), [],
                                 "a no-op that still carries steps is not a no-op")

    def test_a_unit_that_is_ours_but_unstamped_is_adopted_never_overwritten(self):
        # This is the assertion the case above used to carry under the wrong
        # name. It is about ownership, not about repetition: the marker says the
        # unit is ours, the ownership record is missing, and provisioning over it
        # would destroy the only evidence of who made it.
        host = FakeHost.from_fixture("host-a")
        for wid in ("calendar-export", "voicememo-notify"):
            with self.subTest(workload=wid):
                w = model.load_declaration(CORPUS / f"{wid}.yaml")
                artifact = render_mod.render(w, host, self.ctx())
                after = self.after_a_provision(w, artifact, host=host, stamped=False)
                plan = provision.plan(w, artifact, after)
                self.assertEqual(plan.action, "refuse")
                self.assertEqual(plan.reason_code, "marker-without-stamp")

    def test_the_whole_chain_for_one_case(self):
        wid = "calendar-export"
        root = make_repo(self.tmpdir(), declarations=(wid,))
        cfg = config.load_config(root)
        host = FakeHost.from_fixture("host-a")
        w = model.load_all(root, cfg)[0]
        artifact = render_mod.render(w, host, self.ctx())

        runner = RecordingRunner()
        runner.add("print", completed_from("launchctl-print-running.txt"))
        runner.add("list", completed_from("launchctl-list.txt"))
        runner.add("print-disabled", completed_from("launchctl-print-disabled.txt"))

        obs = provision.observe(w, host, artifact, self.ctx(), timeout_sec=10, runner=runner)
        plan = provision.plan(w, artifact, obs)
        dry = provision.apply(plan, w, host, artifact, self.ctx(), dry_run=True,
                              timeout_sec=10, runner=RecordingRunner(), root=root)
        self.assertFalse(dry.verified)

        outcome = provision.apply(plan, w, host, artifact, self.ctx(), dry_run=False,
                                  timeout_sec=10, runner=runner, root=root)
        self.assertIn(outcome.action, {"create", "replace", "noop"})

        rep = reconcile.run(root, cfg, hosts=["host-a"], probe=False,
                            timeout_sec=10, runner=runner)
        self.assertIsInstance(rep.exit_code, int)

        retire_runner = RecordingRunner()
        retire_runner.add("print", FakeCompleted(
            rc=113, stdout=read_output("launchctl-print-notfound.txt")))
        provision.retire(w, host, artifact, self.ctx(), reason="acceptance run cleanup",
                         dry_run=False, confirmed=True, timeout_sec=10,
                         runner=retire_runner, root=root)
        self.assertIn("retired:",
                      (root / "workflow" / "workloads" / f"{wid}.yaml").read_text(encoding="utf-8"))


class TheCommandLine(MachineGuard):

    def repo(self, *declarations):
        return make_repo(self.tmpdir(), declarations=declarations or CORPUS_IDS)

    def test_list_reads_declarations_and_probes_nothing(self):
        # Both halves of the name, measured. The body used to be `assertEqual(rc,
        # 0)` and nothing else: a `run_argv` planted inside `cmd_list` wrote a
        # marker file while this test ran and it stayed green. An exit code of 0
        # is satisfied by every path through the command, including one that
        # probed the whole fleet first.
        #
        # `run_argv` is the single door outwards: run_step, step_runner and
        # probe_context all end up in it, so recording it records every call.
        import contextlib
        import io

        import engine.exec as exec_module

        outbound = []

        def record(argv, **kwargs):
            outbound.append(tuple(str(a) for a in argv))
            raise AssertionError(f"list reached outwards: {argv!r}")

        root = self.repo()
        cfg = config.load_config(root)
        buf = io.StringIO()
        with mock.patch.object(exec_module, "run_argv", record):
            with contextlib.redirect_stdout(buf):
                rc = cli.main(["--root", str(root), "list"])
        printed = buf.getvalue()

        self.assertEqual(rc, 0)
        self.assertEqual(outbound, [],
                         f"list executed {len(outbound)} call(s) outwards: {outbound}")
        # ... and it did read the declarations, rather than probing nothing by
        # doing nothing at all.
        expected = sorted(w.id for w in model.load_all(root, cfg) if not w.is_retired)
        self.assertTrue(expected, "the fixture repo has to hold declarations")
        for workload_id in expected:
            self.assertIn(workload_id, printed,
                          f"list printed no line for {workload_id}")

    def test_list_says_it_only_read_the_declarations(self):
        # Otherwise we quietly reinvent the status field the schema omits.
        import io
        import contextlib

        root = self.repo()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cli.main(["--root", str(root), "list"])
        self.assertIn("declar", buf.getvalue().lower())

    def test_an_unreadable_declaration_exits_two_and_names_the_file(self):
        import io
        import contextlib

        root = self.repo("calendar-export", "negative-broken-yaml")
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            rc = cli.main(["--root", str(root), "list"])
        self.assertEqual(rc, 2)
        self.assertIn("negative-broken-yaml", buf.getvalue())

    def test_validate_is_clean_on_the_corpus(self):
        root = self.repo()
        self.assertEqual(cli.main(["--root", str(root), "validate", "--all"]), 0)

    def test_validate_over_nothing_says_it_checked_nothing(self):
        # A scan over an empty folder may not read like a scan that found
        # nothing. Both exit 0, and only the wording separates them. Before this
        # the whole answer was the clean line, so a Bridge with an empty
        # declaration folder got the same green as one with seventy four
        # healthy units.
        import contextlib
        import io

        root = make_repo(self.tmpdir(), declarations=())
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli.main(["--root", str(root), "validate", "--all"])
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertNotEqual(out.strip(), report.CLEAN_LINE,
                            "validate reported clean over zero declarations without "
                            "saying that it had checked zero")
        self.assertIn("0", out.splitlines()[0])

    def test_validate_finds_the_negative_controls(self):
        root = self.repo("negative-no-deadline")
        self.assertEqual(cli.main(["--root", str(root), "validate", "--all"]), 1)

    def test_provision_without_yes_changes_nothing(self):
        # And "nothing" is measured, not inferred from an exit code. The exit
        # code alone is the weak half: 0 and 3 are both accepted here, so every
        # path through the command satisfies it. What has to hold is that the
        # one door outwards was never opened, so the door itself is recorded.
        # The machine guard is the backstop under it, but a backstop that never
        # fires in a green run is not evidence that nothing was attempted.
        import engine.exec as exec_module

        outbound = []

        def record(argv, **kwargs):
            outbound.append(tuple(str(a) for a in argv))
            raise AssertionError(f"a read only command reached outwards: {argv!r}")

        root = self.repo("calendar-export")
        with mock.patch.object(exec_module, "run_argv", record):
            rc = cli.main(["--root", str(root), "provision", "calendar-export",
                           "--dry-run"])
        self.assertIn(rc, (0, 3))
        self.assertEqual(outbound, [],
                         f"provision without --yes executed {len(outbound)} call(s): "
                         f"{outbound}")

    def test_the_exit_code_map(self):
        self.assertEqual(cli.exit_code_for(report.Report(findings=[])), 0)
        s, st = model.Severity, model.WorkloadState
        noisy = report.Report(findings=[report.Finding(
            workload_id="x", state=st.absent, severity=s.high,
            detail="gone", hint="provision it", source="machine")])
        self.assertEqual(cli.exit_code_for(noisy), 1)
        self.assertEqual(cli.exit_code_for(errors.DeclarationError("bad", source="x.yaml")), 2)
        self.assertEqual(cli.exit_code_for(errors.Refused("no", code="disabled-refused")), 3)
        self.assertEqual(cli.exit_code_for(errors.StepTimeout(
            argv=("ssh",), timeout_sec=5, partial_stdout="", partial_stderr="")), 4)

    def test_a_deadline_is_never_mistaken_for_a_clean_run(self):
        timeout = errors.StepTimeout(argv=("ssh",), timeout_sec=5,
                                     partial_stdout="", partial_stderr="")
        self.assertNotEqual(cli.exit_code_for(timeout), 0)

    def test_the_cli_holds_no_logic(self):
        source = (SKILL_DIR / "engine" / "cli.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name not in {"main", "exit_code_for"}:
                body = [n for n in node.body if not isinstance(n, ast.Expr)]
                self.assertLessEqual(
                    len(body), 12,
                    f"{node.name} in cli.py grew a body; logic belongs in a module")


class CoreHygiene(MachineGuard):
    """What keeps this skill promotable, checked mechanically."""

    def sources(self):
        """Every engine source, and never an empty list.

        A scan over nothing passes for the wrong reason, which is the same
        failure mode as a check nobody runs.
        """
        found = sorted((SKILL_DIR / "engine").rglob("*.py"))
        self.assertTrue(found, "no engine sources to scan, so this check proves nothing")
        return found

    def test_no_instance_name_anywhere_in_the_skill(self):
        for path in skill_text_files():
            text = path.read_text(encoding="utf-8", errors="replace")
            for literal in forbidden_literals():
                with self.subTest(file=str(path.relative_to(SKILL_DIR)), literal=literal):
                    self.assertNotIn(literal, text)

    # ── the surface the scan above does NOT cover ────────────────────────────
    # The skill directory is not the promotable surface. The declaration
    # contract and the template live outside it, the promote router calls both
    # of them core, and both travel to the public repository with the skill.
    # Nothing read them: every forbidden literal at once was placed in both and
    # this suite reported 337 green, while the same poison INSIDE the skill was
    # caught at once. The four cases below close that, and the last two hold
    # without a repository so they still run in the scratch copy.

    def poisoned_body(self) -> str:
        """A file carrying every forbidden literal, built FROM the denylist.

        Generated, never typed: this file is itself scanned by the case above,
        and a fixture spelled out here would either trip that scan or drift
        away from the list it is supposed to represent.
        """
        return "# " + " ".join(forbidden_literals()) + "\n"

    def fake_root(self, body: str, name: str = "_schema.yaml"):
        """A throwaway root carrying ONE file in the directory this skill owns."""
        root = self.tmpdir()
        folder = root / companion_dirs()[0]
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / name
        target.write_text(body, encoding="utf-8")
        return root, target

    def test_no_instance_name_in_the_core_files_that_ship_with_the_skill(self):
        # NO DOCSTRING on purpose: unittest -v prints one instead of the test id,
        # and the skip below has to be nameable in the run output.
        root = repo_root()
        if root is None:
            self.skipTest(
                "no Bridge root above this copy of the skill, so there is no "
                "promote router to ask and no file outside the skill to read; "
                "reported here rather than passed off as a clean surface")
        files = core_files_outside_the_skill(root)
        self.assertTrue(
            files,
            f"the router named no core file under {companion_dirs()}, so this "
            f"scan covers nothing and its pass would mean nothing")
        for path in files:
            with self.subTest(file=str(path.relative_to(root))):
                hits = instance_name_hits(path)
                self.assertEqual(
                    [], hits,
                    f"{path.relative_to(root)} ships to the public repository "
                    f"with this skill and carries {hits}")

    def test_the_scanned_surface_really_reaches_past_the_skill_directory(self):
        # The widening is only real while it moves files. Anchored on the one
        # file the suite already depends on: the contract the fixtures are
        # validated against is outside this directory, so it must be inside the
        # surface and outside the older scan. (No docstring — see above.)
        root = repo_root()
        schema = self.real_schema()
        if root is None or schema is None:
            self.skipTest(
                "no Bridge root or no declaration contract above this copy of "
                "the skill, so there is nothing outside it to reach")
        self.assertNotIn(schema, skill_text_files(),
                         "the contract sits inside the skill after all, so the "
                         "older scan already covered it and this one adds nothing")
        self.assertIn(schema, core_files_outside_the_skill(root),
                      "the contract this skill is validated against is not in the "
                      "scanned surface, so the widening moves no file")

    def test_a_poisoned_core_file_outside_the_skill_is_seen(self):
        # Hermetic: a throwaway root, an injected router, no repository needed.
        # This is the case the real scan cannot make on demand, and the one the
        # old scan failed silently. (No docstring — see above.)
        root, target = self.fake_root(self.poisoned_body())
        found = core_files_outside_the_skill(root, classify=lambda rel: "core")
        self.assertEqual([target], found,
                         "a core file outside the skill was not collected at all")
        self.assertTrue(
            instance_name_hits(target),
            "a file outside the skill carrying every forbidden literal read as clean")

    def test_the_router_answer_decides_what_is_scanned(self):
        # The tier comes from the router, never from the path. Same file, two
        # answers, two outcomes. (No docstring — see above.)
        root, target = self.fake_root(self.poisoned_body())
        self.assertEqual([], core_files_outside_the_skill(root, classify=lambda rel: "user"))
        self.assertEqual([target], core_files_outside_the_skill(root, classify=lambda rel: "core"))

    def test_a_router_that_cannot_be_asked_is_reported_never_ignored(self):
        # Three ways for the router to fall over. None of them may read as an
        # empty surface, because an empty surface is indistinguishable from a
        # clean one. (No docstring — see above.)
        missing = self.tmpdir()
        self.assertIsNone(repo_root(missing))
        with self.assertRaises(RouterUnavailable):
            load_promote_router(missing)
        with self.assertRaises(RouterUnavailable):
            core_files_outside_the_skill(missing)

        broken = self.tmpdir()
        (broken / ROUTER_REL).parent.mkdir(parents=True, exist_ok=True)
        (broken / ROUTER_REL).write_text(
            "import a_module_that_is_not_installed_anywhere\n", encoding="utf-8")
        with self.assertRaises(RouterUnavailable):
            load_promote_router(broken)

        gutted = self.tmpdir()
        (gutted / ROUTER_REL).parent.mkdir(parents=True, exist_ok=True)
        (gutted / ROUTER_REL).write_text("VALUE = 1\n", encoding="utf-8")
        with self.assertRaises(RouterUnavailable):
            load_promote_router(gutted)

    def test_the_schema_id_host_is_exempt_and_nothing_else_is(self):
        # The exemption exists because a schema publishes itself under the
        # project's own host, which carries the project's name. That line is a
        # self reference; two dozen sibling schemas in this tree carry the same
        # one. Everything below is the fence around it. (No docstring — see above.)
        header = '$schema: "https://json-schema.org/draft/2020-12/schema"\n'
        hostable = [lit for lit in forbidden_literals() if "/" not in lit]
        self.assertTrue(hostable, "no literal can stand in a host, so this proves nothing")
        for literal in hostable:
            with self.subTest(literal=literal):
                in_host = header + f'$id: "https://{literal}.example/schemas/x.yaml"\n'
                self.assertEqual(
                    [], instance_name_hits(Path("x.yaml"), in_host),
                    "a project host in a schema identifier is a self reference")
                in_path = header + f'$id: "https://example.test/{literal}/x.yaml"\n'
                self.assertTrue(
                    instance_name_hits(Path("x.yaml"), in_path),
                    "one column further along the same URL is not the host")
                self.assertTrue(
                    instance_name_hits(Path("x.yaml"), in_host + f"# {literal}\n"),
                    "the same letters in a comment are a leak again")
                self.assertTrue(
                    instance_name_hits(Path("x.yaml"), in_host + f"purpose: {literal}\n"),
                    "the same letters in a value are a leak again")
                not_a_schema = f'$id: "https://{literal}.example/schemas/x.yaml"\n'
                self.assertTrue(
                    instance_name_hits(Path("x.yaml"), not_a_schema),
                    "a file that is not a schema gets no identifier exemption")
        for literal in (lit for lit in forbidden_literals() if "/" in lit):
            with self.subTest(literal=literal):
                self.assertTrue(
                    instance_name_hits(Path("x.yaml"), header + f'$id: "https://x{literal}y/z"\n'),
                    "a literal carrying a separator can never be a host")

    def test_every_open_names_its_encoding(self):
        # Declarations carry umlauts, and a default encoding is a platform lottery.
        for path in self.sources():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "open":
                    kwargs = {k.arg for k in node.keywords}
                    self.assertIn("encoding", kwargs,
                                  f"{path.name}:{node.lineno} opens a file without an encoding")

    def test_the_stack_is_stdlib_plus_pyyaml(self):
        allowed = set(sys.stdlib_module_names) | {"yaml", "engine", "tests"}
        for path in self.sources():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                roots = []
                if isinstance(node, ast.Import):
                    roots = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    roots = [node.module.split(".")[0]]
                for root in roots:
                    self.assertIn(root, allowed,
                                  f"{path.name} imports {root!r}, which is not stdlib or PyYAML")

    def test_no_rrule_library_sneaks_in(self):
        # A general recurrence evaluation belongs to the dispatcher. Each backend
        # translates a restricted subset and refuses the rest.
        for path in self.sources():
            text = path.read_text(encoding="utf-8")
            for name in ("dateutil", "croniter", "recurrent"):
                self.assertNotIn(name, text)

    def test_no_shell_true_anywhere(self):
        for path in self.sources():
            self.assertNotIn("shell=True", path.read_text(encoding="utf-8"))

    def test_no_sudo_anywhere(self):
        for path in self.sources():
            text = path.read_text(encoding="utf-8")
            self.assertNotIn('"sudo"', text)
            self.assertNotIn("'sudo'", text)

    def test_the_skill_declares_itself_core(self):
        text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("name: workload", text)
        self.assertIn("scope: core", text)

    def test_the_skill_says_what_it_does_not_do(self):
        text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8").lower()
        for absent in ("visualis", "rrule", "sudo", "infra/remotes"):
            self.assertIn(absent, text,
                          f"SKILL.md does not say that {absent} is out of scope")

    def test_the_references_exist(self):
        for name in ("declare", "provision", "reconcile", "backends"):
            path = SKILL_DIR / "references" / f"{name}.md"
            self.assertTrue(path.exists(), f"missing reference {path}")

    def test_the_shim_resolves_its_own_real_path(self):
        text = (SKILL_DIR / "workload.sh").read_text(encoding="utf-8")
        self.assertIn("PYTHONPATH", text)
        self.assertIn("engine.cli", text)

    def real_schema(self):
        """The declaration contract, if this copy of the skill can still see it.

        Resolved by walking up rather than by counting directory levels. The
        skill is also COPIED out of the repository (the mutation battery does
        exactly that), and a hardcoded ``parents[1]`` turns such a copy into a
        check that quietly measures the wrong tree.
        """
        for base in (SKILL_DIR, *SKILL_DIR.parents):
            candidate = base / "workflow" / "workloads" / "_schema.yaml"
            if candidate.exists():
                return candidate
        return None

    def test_the_corpus_is_what_it_says_it_is(self):
        # Identity, and only identity: the fixtures are these seven files.
        # Deliberately separate from the schema check below. Four hand picked
        # fields used to stand in for a validator here, and a fixture that lost
        # its purpose or grew a field the contract forbids passed both of the
        # probes an audit fired at it.
        import yaml

        seen = set()
        for path in sorted(CORPUS.glob("*.yaml")):
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            self.assertEqual(raw["id"], path.stem)
            seen.add(raw["id"])
        self.assertEqual(seen, set(CORPUS_IDS),
                         "the acceptance corpus changed size, which is a deliberate act")

    def test_every_fixture_is_handed_to_the_validator_and_its_answer_decides(self):
        # The corpus is checked by ASKING, and by asking about each file.
        # Hermetic on purpose: a stub on PATH stands in for the tool and the
        # answer is recorded, so this holds in a copy of the skill that cannot
        # see the repository and on a machine with no validator installed. The
        # run against the REAL schema is the case below; this one guards the two
        # halves that case cannot guard everywhere: that every fixture is
        # really submitted, and that a refusal is really what sinks it.
        directory = self.tmpdir()
        stub = directory / "check-jsonschema"
        stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        stub.chmod(0o755)
        schema = directory / "_schema.yaml"
        schema.write_text("type: object\n", encoding="utf-8")

        runner = RecordingRunner()
        runner.add("check-jsonschema",
                   FakeCompleted(rc=1, stdout="$.purpose: 'x' is too short"))
        paths = sorted(CORPUS.glob("*.yaml"))
        self.assertEqual(len(paths), len(CORPUS_IDS))
        with mock.patch.dict(os.environ, {"PATH": str(directory)}):
            for path in paths:
                with self.subTest(fixture=path.name):
                    verdict = model.validate_with_schema(path, schema, runner)
                    self.assertEqual(
                        verdict.verdict, "invalid",
                        f"the validator refused {path.name} and the gate read it as "
                        f"{verdict.verdict!r}")
        self.assertEqual(len(runner.calls), len(paths),
                         f"{len(runner.calls)} calls for {len(paths)} fixtures")
        for path, call in zip(paths, runner.calls):
            self.assertIn(str(path), call["joined"],
                          f"the validator was run without {path.name}, so it judged "
                          f"nothing and its silence would read as a pass")

    def test_the_fixtures_still_validate_against_the_real_schema(self):
        # The copy is faithful only while it passes the contract it was drawn
        # from. The validator is really executed here, and in the same run a
        # deliberately broken copy of one fixture has to come back REFUSED.
        # Without that second half a wrong schema path, an unread answer or a
        # validator that judges nothing all read as a clean corpus, which is
        # exactly what the four hand picked field checks used to do.
        #
        # The contract lives in the repository, not in this skill, so a copy of
        # the skill taken out of a Bridge skips this with a reason instead of
        # reporting a green it cannot earn. NO DOCSTRING on purpose: unittest -v
        # prints one instead of the test id, and a skip nobody can name is not
        # the visible skip this is meant to be.
        import yaml

        schema = self.real_schema()
        if schema is None:
            self.skipTest("no workflow/workloads/_schema.yaml above this copy of the "
                          "skill: the fixture contract lives in the repository, so a "
                          "detached copy cannot check the fixtures against it")
        exec_mod = mod("engine.exec")
        paths = sorted(CORPUS.glob("*.yaml"))
        first = model.validate_with_schema(paths[0], schema, exec_mod.run_argv)
        if first.verdict == "schema_validator_absent":
            self.skipTest("check-jsonschema is not on PATH, so the second gate cannot "
                          "run here; its absence is reported, never passed off as green")
        for path in paths:
            with self.subTest(fixture=path.name):
                verdict = model.validate_with_schema(path, schema, exec_mod.run_argv)
                self.assertEqual(verdict.verdict, "valid",
                                 f"{path.name}: {verdict.detail}")

        # The control that gives the green above its meaning. A gate is only
        # worth its pass when it can be made to fail on demand.
        raw = yaml.safe_load(paths[0].read_text(encoding="utf-8"))
        raw["purpose"] = "x"
        broken = self.tmpdir() / paths[0].name
        broken.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True),
                          encoding="utf-8")
        control = model.validate_with_schema(broken, schema, exec_mod.run_argv)
        self.assertEqual(control.verdict, "invalid",
                         "the validator accepted a declaration the schema forbids, so "
                         "the pass above proves nothing about the corpus")

    def test_every_flag_the_parser_takes_stands_in_the_command_block(self):
        # A flag the parser accepts and the document does not name is a feature
        # that exists only for whoever wrote it. `retire --dry-run` was one:
        # declared, parsed, thrown away one layer down, and absent from the
        # command block, so the safety word on the destructive command was
        # neither documented nor wired. Four more were undocumented beside it.
        text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        parser = cli._parser()
        subcommands = [a for a in parser._actions
                       if hasattr(a, "choices") and isinstance(a.choices, dict)]
        self.assertEqual(len(subcommands), 1, "the parser grew a second subcommand set")
        for name, sub in subcommands[0].choices.items():
            with self.subTest(command=name):
                lines = [line for line in text.splitlines()
                         if line.strip().startswith(f"workload {name}")]
                self.assertTrue(lines, f"SKILL.md documents no `workload {name}` at all")
                flags = {option for action in sub._actions
                         for option in action.option_strings} - {"-h", "--help"}
                missing = sorted(flag for flag in flags if flag not in lines[0])
                self.assertEqual(
                    [], missing,
                    f"`workload {name}` takes {missing} and the command block does "
                    f"not name them")

    def gate_of_the_instance(self):
        """The promote gate's own lists, or the reason there are none to ask."""
        root = repo_root()
        if root is None or not (root / CONFIG_REL).is_file():
            self.skipTest("no Bridge configuration above this copy of the skill, so "
                          "the promote gate's lists cannot be asked; reported here "
                          "rather than passed off as a clean surface")
        rules = promote_blocklist(root)
        if not rules:
            self.skipTest("this instance configures no blocklist at all, so this scan "
                          "would pass over nothing")
        return root, rules

    def test_no_core_file_of_this_skill_trips_the_promote_blocklist(self):
        # The scan above asks whether this tree carries an instance NAME. This
        # one asks the different question the promote gate asks: whether any
        # core file matches the instance's own blocklist -- case insensitively,
        # word-level, patterns included, and over every destination at once.
        #
        # The two answers came apart in this very file. `tests/conftest.py`
        # spells its denylist in fragments so it does not trip its own scan, and
        # two of those fragments still carried the three letter organisation
        # token whole, which the gate matches as a word. Not a leak: a blocking
        # false alarm, and one that came back at every promote attempt until
        # somebody split the fragment again. (No docstring -- see above.)
        root, rules = self.gate_of_the_instance()
        classify = load_promote_router(root)
        files = [path for path in skill_text_files()
                 if classify(path.relative_to(root).as_posix()) == "core"]
        files += core_files_outside_the_skill(root)
        self.assertTrue(files, "the router called no file of this skill core, so this "
                               "scan covers nothing and its pass would mean nothing")
        for path in files:
            with self.subTest(file=str(path.relative_to(root))):
                hits = blocklist_hits(path.read_text(encoding="utf-8", errors="replace"),
                                      rules)
                self.assertEqual(
                    [], hits,
                    f"{path.relative_to(root)} would be refused by the promote gate "
                    f"of this instance at {hits}")

    def test_the_blocklist_scan_still_finds_a_poisoned_file(self):
        # The counter-control, and it is the whole worth of the case above: a
        # scan that fires on nothing reports a clean tree for the same reason a
        # scan over an empty file list does. (No docstring -- see above.)
        #
        # The poison is built from the instance's OWN listed words, not from
        # `forbidden_literals()`: those are fictional stand-ins that no real
        # blocklist contains, so a poison made of them passed every configured
        # instance's gate and this case failed wherever it could run at all
        # (upstream it is skipped, there is no configuration there). A string
        # rule matches its own word; a pattern rule cannot be turned back into a
        # matching line, so an instance listing only patterns is skipped by name.
        _, rules = self.gate_of_the_instance()
        words = [label for label, expression in rules if expression.search(str(label))]
        if not words:
            self.skipTest("this instance's blocklist has only patterns, and a pattern "
                          "cannot be turned into a line that is known to match it")
        poisoned = "# " + " ".join(str(w) for w in words) + "\n"
        self.assertTrue(
            blocklist_hits(poisoned, rules),
            "a line carrying this instance's own names passed the promote gate's "
            "lists, so the clean answer next door says nothing")

    def test_the_two_gates_hold_the_same_rules_word_for_word(self):
        # Six shapes are written down TWICE: once in the declaration contract,
        # once by hand in `engine.model`, on purpose -- two gates that read the
        # same file are one gate with a second name. The price of that is drift,
        # and drift here is not cosmetic: `provision.plan` consults the HAND
        # WRITTEN one, so a rule that exists only in the schema is a rule the
        # layer that acts never applies, and one that exists only in the gate is
        # a declaration `--strict` refuses after `validate` called it clean.
        # Both have already happened in this tree, in the same round.
        #
        # The contract lives in the repository, so a detached copy skips this
        # with a reason. NO DOCSTRING on purpose: unittest -v prints one instead
        # of the test id, and a skip nobody can name is not a visible skip.
        import functools
        import yaml

        schema = self.real_schema()
        if schema is None:
            self.skipTest("no workflow/workloads/_schema.yaml above this copy of the "
                          "skill: the contract lives in the repository, so a detached "
                          "copy has nothing to compare the hand written gate against")
        raw = yaml.safe_load(schema.read_text(encoding="utf-8"))

        def at(*keys):
            try:
                return functools.reduce(lambda node, key: node[key], keys, raw)
            except (KeyError, IndexError, TypeError):
                self.fail(f"the contract carries no rule at {'.'.join(map(str, keys))} "
                          f"any more, so the hand written gate now holds a rule the "
                          f"schema dropped")

        both = {
            "id": (at("properties", "id", "pattern"), model.ID_PATTERN),
            "execution.env (name)": (
                at("properties", "execution", "properties", "env",
                   "propertyNames", "pattern"), model.ENV_NAME_PATTERN),
            "execution.env (value)": (
                at("properties", "execution", "properties", "env",
                   "additionalProperties", "pattern"), model.ENV_VALUE_PATTERN),
            "response.recipients[].mandant": (
                at("properties", "response", "properties", "recipients", "items",
                   "properties", "mandant", "pattern"), model.MANDANT_PATTERN),
            "response.recipients[].person": (
                at("properties", "response", "properties", "recipients", "items",
                   "properties", "person", "pattern"), model.PERSON_PATTERN),
            "placement.interpreter": (
                at("properties", "placement", "properties", "interpreter", "pattern"),
                model.ABSOLUTE_PATH_PATTERN),
            "execution.working_dir": (
                at("properties", "execution", "properties", "working_dir", "pattern"),
                model.ABSOLUTE_PATH_PATTERN),
            "execution.command[0]": (
                at("properties", "execution", "properties", "command",
                   "prefixItems", 0, "pattern"), model.ABSOLUTE_PATH_PATTERN),
            # The version segment: same shape, and the gate needs the capture
            # group to NAME the segment in its refusal, so the contract carries
            # the group too rather than an equivalent spelling of it.
            "placement.interpreter (version segment)": (
                at("properties", "placement", "properties", "interpreter",
                   "not", "pattern"), model.VERSION_SEGMENT_PATTERN),
            # The rights shapes were doubled like the rest and compared like
            # none of them, which is the drift this test exists to catch. Added
            # when `fetch_scope` arrived, because a host list that means one
            # thing to the contract and another to the acting gate bounds
            # nothing.
            "rights (generic shell)": (
                at("$defs", "rights_toolstring", "not", "pattern"),
                model.RIGHTS_GENERIC_SHELL_PATTERN),
            "rights (scope)": (
                at("$defs", "rights_relpath", "pattern"), model.RIGHTS_SCOPE_PATTERN),
            "rights (recipient slug)": (
                at("$defs", "rights_slug", "pattern"), model.MANDANT_PATTERN),
            "rights (fetch host)": (
                at("$defs", "rights_level", "properties", "fetch_scope",
                   "items", "pattern"), model.RIGHTS_HOST_PATTERN),
            "rights.stop.flag": (
                at("properties", "rights", "properties", "stop", "properties",
                   "flag", "pattern"), model.RIGHTS_STOP_FLAG_PATTERN),
            "rights.reply.flag": (
                at("properties", "rights", "properties", "reply", "properties",
                   "flag", "pattern"), model.RIGHTS_STOP_FLAG_PATTERN),
            "rights.consent.flag": (
                at("properties", "rights", "properties", "consent", "properties",
                   "flag", "pattern"), model.RIGHTS_STOP_FLAG_PATTERN),
        }
        for key_path, (in_schema, in_gate) in both.items():
            with self.subTest(rule=key_path):
                self.assertEqual(
                    in_schema, in_gate.pattern,
                    f"{key_path}: the contract says {in_schema!r} and the hand "
                    f"written gate says {in_gate.pattern!r}; one of the two gates "
                    f"now accepts what the other refuses")

        # The shared interpreter list is the seventh doubled rule and the only
        # one that is not a regex, so it is compared here rather than above. It
        # is also the one most likely to drift, because adding an interpreter is
        # a one line edit that feels local: a name added to the gate alone makes
        # `--strict` accept what `validate` refuses, and a name added to the
        # contract alone hands a grant to the whole machine on any box without
        # check-jsonschema installed.
        in_contract = None
        for rule in raw.get("allOf", []):
            candidate = (rule.get("then", {}).get("properties", {})
                             .get("placement", {}).get("properties", {})
                             .get("interpreter", {}).get("not", {}).get("enum"))
            if candidate is not None:
                in_contract = candidate
                break
        self.assertIsNotNone(
            in_contract,
            "the contract no longer refuses a shared interpreter for a grant "
            "holder, so the hand written gate holds that rule alone")
        self.assertEqual(
            list(in_contract), list(model.SHARED_INTERPRETERS),
            "the two gates disagree about which interpreters the machine shares")

    def test_every_test_class_in_the_suite_stands_under_the_guard(self):
        # The guard only protects what inherits it, so that is what is checked.
        # This replaced a scan for two spellings of one literal. A scan over
        # source text sees the shape a call was TYPED in; it cannot see an argv
        # assembled from a variable, a bare Popen or an os.system, and all three
        # reach a real machine exactly as well as the spelling it looked for.
        # What actually keeps this suite off the boxes is MachineGuard, and the
        # only thing worth asserting mechanically is that nothing sits outside it.
        guarded = {"MachineGuard"}
        outside = []
        for path in sorted((SKILL_DIR / "tests").rglob("test_*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            # Module level only. A helper class nested inside a test body is a
            # fixture, not a case, and the runner never collects it.
            for node in tree.body:
                if not isinstance(node, ast.ClassDef):
                    continue
                bases = {b.id for b in node.bases if isinstance(b, ast.Name)}
                if bases & guarded:
                    guarded.add(node.name)          # a base class of its own
                else:
                    outside.append(f"{path.name}:{node.name}({', '.join(sorted(bases))})")
        self.assertEqual(outside, [],
                         "these test classes do not inherit MachineGuard, so nothing "
                         "stops them reaching a real machine: " + ", ".join(outside))


class TheGuardItself(MachineGuard):
    """The riegel, exercised. Nothing else in this tree ever trips it.

    An instrumented run of the whole suite made three guard decisions and refused
    none of them: the branch that would stop a real ssh had never once executed,
    and every other test here draws its entire safety from it. A guard nobody
    fires is a guard nobody has tested.

    The denied programs are matched by BASENAME on the resolved argv, which is
    why a full path and an argv built at runtime are both in the table: source
    text is not what reaches a machine.
    """

    DENIED = (
        ["ssh", "host-a", "true"],
        ["/usr/bin/ssh", "host-a", "true"],
        ["scp", "a.txt", "host-a:/tmp/a.txt"],
        ["sftp", "-b", "/dev/null", "host-a"],
        ["launchctl", "print", "gui/4242/bridge.x"],
        ["systemctl", "--user", "status", "bridge-x.timer"],
        ["systemd-run", "--version"],
        ["crontab", "-l"],
        ["sudo", "-n", "/usr/bin/true"],
        ["/bin/sh", "-c", "launchctl print gui/4242/bridge.x"],
    )
    # Every entry is a READ, deliberately. The guard refuses by program, never by
    # verb, so a read proves the same branch a write would. And if a mutation
    # ever softens the guard, this table is what runs for real on the machine
    # under the suite. It must be inert when that happens.

    def test_the_table_covers_every_program_the_guard_names(self):
        # Otherwise a name added to the deny list arrives with no case behind it,
        # and the list grows into a claim nobody checks.
        from tests import conftest

        covered = {os.path.basename(argv[0]) for argv in self.DENIED}
        covered |= {"launchctl"}          # also reached through the sh -c entry
        self.assertEqual(sorted(conftest._DENY - covered), [],
                         "these denied programs have no case in DENIED: "
                         f"{sorted(conftest._DENY - covered)}")

    def test_subprocess_run_refuses_every_denied_program(self):
        for argv in self.DENIED:
            with self.subTest(argv=argv):
                with self.assertRaises(AssertionError) as ctx:
                    subprocess.run(argv, capture_output=True)
                self.assertIn("tried to exec", str(ctx.exception))

    def test_popen_refuses_every_denied_program(self):
        # subprocess.run is the shape a source scan looks for. Popen is the one
        # it does not, and call/check_output/check_call all arrive through here.
        for argv in self.DENIED:
            with self.subTest(argv=argv):
                with self.assertRaises(AssertionError) as ctx:
                    subprocess.Popen(argv, stdout=subprocess.PIPE)
                self.assertIn("tried to exec", str(ctx.exception))

    def test_an_argv_assembled_at_runtime_is_refused_too(self):
        # Nothing in this file spells the program out, and the guard still sees
        # it: that difference is the whole reason the wordlist was retired.
        program = "".join(["s", "s", "h"])
        argv = [program] + ["host-a", "--", "true"]
        with self.assertRaises(AssertionError):
            subprocess.run(argv, capture_output=True)

    def test_os_system_and_os_popen_are_closed_too(self):
        # Neither goes through subprocess, so patching subprocess alone leaves a
        # second door open.
        with self.assertRaises(AssertionError):
            os.system("ssh host-a true")
        with self.assertRaises(AssertionError):
            os.popen("ssh host-a true")

    def test_a_harmless_local_call_still_runs(self):
        # A guard that refuses everything is not a guard, it is a broken suite:
        # test_exec.py has to be able to start /bin/sh under its own deadline.
        done = subprocess.run(["/bin/echo", "still local"],
                              capture_output=True, text=True)
        self.assertEqual(done.stdout.strip(), "still local")

    def test_the_guard_is_put_back_when_a_test_ends(self):
        # Otherwise one case's patch leaks into every later case in the process.
        before_run, before_popen = subprocess.run, subprocess.Popen
        before_system, before_os_popen = os.system, os.popen

        class Probe(MachineGuard):
            def runTest(self):
                pass

        case = Probe()
        case.setUp()
        self.assertIsNot(subprocess.run, before_run, "the guard did not arm")
        case.doCleanups()
        self.assertIs(subprocess.run, before_run)
        self.assertIs(subprocess.Popen, before_popen)
        self.assertIs(os.system, before_system)
        self.assertIs(os.popen, before_os_popen)


if __name__ == "__main__":
    unittest.main()


class TheTwoGatesAnswerTheSameWay(CoreHygiene):
    """The seam between the hand written gate and the declaration schema.

    They are two independent implementations on purpose: two gates that read the
    same document are one gate with a second name, and this one exists so it can
    fail differently. What that buys is only worth something while they agree on
    the VERDICT for anything this skill would actually start.

    For one round they did not. Rules lived in the schema alone -- absolute
    paths, an environment value that is a locator, a recipient that is a slug,
    and a schedule carrying only its own kind's trigger -- so `validate`
    answered clean where `validate --strict` refused. That is worse than having
    one gate, because the quiet one is the gate the LAYER THAT ACTS consults:
    `provision.plan` calls `model.validate` and never the schema, which needs a
    tool that is not installed everywhere. A plaintext secret, a relative
    argv[0] and a oneshot carrying a cadence all reached a machine on a path
    where nothing refused them.

    The two are NOT equal in coverage and this case does not pretend otherwise.
    The schema is a document gate and carries shape, type, enum and
    `additionalProperties` rules over every field including the ones that are
    only ever documentation; the hand written gate carries cross field rules
    over what this skill RUNS. So the invariant asserted here is the one that is
    both true and load bearing:

        no declaration the schema refuses may pass the hand written gate while
        being a run this skill would start.

    "Would start" is read off the declaration: owner `bridge`, and a runtime
    that is not one of the inert ones. Everything else is documented, never
    touched, and the schema being stricter about it is a difference and not a
    disagreement.

    It reads the schema's own negative controls, which live in the repository
    rather than in this skill, so a detached copy skips it by name instead of
    reporting a green it cannot earn.
    """

    def controls(self):
        for base in (SKILL_DIR, *SKILL_DIR.parents):
            folder = base / "workflow" / "workloads" / "_tests" / "invalid"
            if folder.is_dir():
                return sorted(folder.glob("*.yaml"))
        return []

    def would_be_started(self, raw) -> bool:
        """Whether this skill would ever create a unit for this declaration."""
        from engine.reconcile import INERT_RUNTIMES

        placement = raw.get("placement")
        placement = placement if isinstance(placement, dict) else {}
        return (placement.get("owner") == "bridge"
                and placement.get("runtime") not in INERT_RUNTIMES)

    def test_no_declaration_the_schema_refuses_is_started_over_a_clean_gate(self):
        # NO DOCSTRING on purpose: unittest -v prints one instead of the test id,
        # and the skip below has to be nameable in the run output.
        import yaml

        controls = self.controls()
        if not controls:
            self.skipTest("no workflow/workloads/_tests/invalid/ above this copy of "
                          "the skill: the schema's own negative controls live in the "
                          "repository, so a detached copy cannot compare the gates")
        compared = 0
        for path in controls:
            try:
                raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            except yaml.YAMLError:
                # A file the parser refuses reaches neither gate, so it is not a
                # case about the two of them agreeing.
                continue
            if not isinstance(raw, dict) or not self.would_be_started(raw):
                continue
            compared += 1
            with self.subTest(control=path.name):
                self.assertTrue(
                    model.validate(raw, source=path.name),
                    f"{path.name}: the schema refuses this declaration, the hand "
                    f"written gate answers clean, and it is a run this skill would "
                    f"start -- so `provision` follows the quiet gate onto a machine")
        self.assertTrue(compared, "no control was compared, so this proves nothing")

    def test_the_corpus_the_schema_accepts_is_accepted_here_too(self):
        # The other direction, and the control that gives the case above its
        # meaning: a gate that refused everything would satisfy it completely.
        import yaml

        for path in sorted(CORPUS.glob("*.yaml")):
            with self.subTest(fixture=path.name):
                raw = yaml.safe_load(path.read_text(encoding="utf-8"))
                self.assertEqual(
                    model.validate(raw, source=path.name), [],
                    f"{path.name}: the schema accepts this declaration and the hand "
                    f"written gate refuses it")

    def test_the_controls_the_gate_deliberately_does_not_carry_are_named(self):
        # The difference in coverage, written down as a list rather than left as
        # a silence. Every entry is a declaration this skill would never start,
        # so the schema being stricter about it costs nothing on a machine -- and
        # a NEW name appearing here is a rule that was added to the document gate
        # and not to the gate `provision` asks.
        import yaml

        controls = self.controls()
        if not controls:
            self.skipTest("no workflow/workloads/_tests/invalid/ above this copy of "
                          "the skill: the controls live in the repository")
        quiet = []
        for path in controls:
            try:
                raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            except yaml.YAMLError:
                continue
            if isinstance(raw, dict) and not model.validate(raw, source=path.name):
                quiet.append(path.name)
        for name in quiet:
            with self.subTest(control=name):
                raw = yaml.safe_load(
                    next(p for p in controls if p.name == name).read_text(encoding="utf-8"))
                self.assertFalse(
                    self.would_be_started(raw),
                    f"{name} passes the hand written gate AND would be started, so "
                    f"it belongs in the case above and not on this list")

    def test_both_gates_know_the_same_top_level_keys(self):
        # The OTHER direction, and the one the cases above cannot see. They ask
        # whether a declaration the schema REFUSES gets started anyway. A key
        # that exists in one allowlist and not the other fails the opposite way
        # and just as quietly:
        #
        #   only in the schema  -> `load_declaration` refuses it as an unknown
        #                          top level key, so a declaration that passes
        #                          CI is rejected on the machine.
        #   only in TOP_LEVEL_KEYS -> the loader takes it and the document gate
        #                          refuses it under `additionalProperties: false`,
        #                          so it runs here and fails every downstream
        #                          instance that validates.
        #
        # Both were reachable by adding a field to one file and forgetting the
        # other, which is a two-file edit nobody's review catches by reading.
        import yaml

        schema_path = self.real_schema()
        if schema_path is None:
            self.skipTest("no workflow/workloads/_schema.yaml above this copy of the "
                          "skill: the document gate lives in the repository, so a "
                          "detached copy cannot compare the two allowlists")
        schema = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
        self.assertIs(schema.get("additionalProperties"), False,
                      "this comparison is only load bearing while the schema closes "
                      "the top level; an open schema accepts keys the loader refuses")
        documented = set(schema.get("properties") or {})
        self.assertTrue(documented, "the schema declares no top level properties, so "
                                    "this check would pass over nothing")
        self.assertEqual(documented, set(model.TOP_LEVEL_KEYS),
                         "the document gate and the loader disagree about which top "
                         "level keys exist: "
                         f"only in the schema {sorted(documented - set(model.TOP_LEVEL_KEYS))}, "
                         f"only in TOP_LEVEL_KEYS {sorted(set(model.TOP_LEVEL_KEYS) - documented)}")


class EveryConfigKeySteersSomething(MachineGuard):
    """A key the loader parses and nothing ever consults is not a setting.

    It reads like one from the outside: it has a name, a default, a place in the
    config file and a line in the handbook. It simply does not do anything, and
    that is invisible from every side except this one. Two were found this way
    on 2026-08-27:

      * `workloads.enabled` was documented in SKILL.md as the guard of the whole
        skill and consulted by no line of code, so an instance that switched the
        skill off kept running it.
      * `workloads.notify_via` was parsed, stored and serialised into the JSON
        output, while the alarm path picked its program from two hardcoded
        names, one of which a fresh clone does not have.

    The receiver list is what makes this sharp rather than reassuring. Searching
    for the bare word finds `unit.enabled` in the provisioner and reports a key
    as live that nothing reads from the CONFIGURATION. A test that cannot fail
    for the case it was written for is worse than no test.
    """

    RECEIVERS = r"(?:cfg|config|conf|ctx|context)"

    def field_names(self):
        source = (SKILL_DIR / "engine" / "config.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "Config":
                names = [n.target.id for n in node.body
                         if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)]
                # `source` is where the block was read from, for error messages.
                return [n for n in names if n != "source"]
        self.fail("engine/config.py no longer declares a Config dataclass")

    def test_no_config_key_is_decoration(self):
        fields = self.field_names()
        self.assertGreater(len(fields), 3, "the field scan found almost nothing")
        # config.py is scanned too, and that is deliberate. A key may legitimately
        # be consumed by the loader's own module (the enabled guard is), and the
        # receiver pattern below still tells the two apart: a declaration reads
        # `enabled: bool = True` and a default reads `defaults.enabled`, neither
        # of which is a configuration object being asked for its value.
        sources = engine_sources()
        self.assertTrue(sources, "no engine sources to scan")
        text = "\n".join(p.read_text(encoding="utf-8") for p in sources)
        dead = []
        for name in fields:
            pattern = re.compile(
                rf"{self.RECEIVERS}\.{name}\b"
                rf"|getattr\(\s*{self.RECEIVERS}\s*,\s*[\"']{name}[\"']")
            if not pattern.search(text):
                dead.append(name)
        self.assertEqual(
            dead, [],
            "these configuration keys are parsed and never read by anything "
            f"outside config.py, so setting them changes nothing: {dead}")
