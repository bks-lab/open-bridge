"""model: the vocabulary and the repo side of the world.

Positive cases run over the seven inventory derived declarations. Every negative
control asserts an error code AND a message substring, because a rejection for
the wrong reason is not a rejection, it is a coincidence.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest import mock

from tests.conftest import (
    CORPUS,
    CORPUS_IDS,
    DERIVED,
    INVALID,
    MachineGuard,
    RecordingRunner,
    SKILL_DIR,
    FakeCompleted,
    declaration,
    load_raw,
    make_repo,
    mod,
)

model = mod("engine.model")
errors = mod("engine.errors")
config = mod("engine.config")
hosts = mod("engine.hosts")
report = mod("engine.report")


def finding_text(finding) -> str:
    """Everything a finding says, whatever shape it has."""
    parts = [str(finding)]
    for attr in ("code", "detail", "hint", "source", "key_path", "message", "state", "severity"):
        value = getattr(finding, attr, None)
        if value is not None:
            parts.append(str(value))
    return " | ".join(parts)


def all_findings_text(findings) -> str:
    return "\n".join(finding_text(f) for f in findings)


class LoadingTheCorpus(MachineGuard):

    def test_loads_all_seven_real_declarations(self):
        for wid in CORPUS_IDS:
            with self.subTest(workload=wid):
                w = model.load_declaration(CORPUS / f"{wid}.yaml")
                self.assertEqual(w.id, wid)
                self.assertEqual(w.schema_version, 1)
                self.assertEqual(w.source_path, CORPUS / f"{wid}.yaml")

    def test_placement_matrix_survives_loading(self):
        expected = {
            "calendar-export": ("interval", "launchd", "bridge"),
            "chat-channel": ("daemon", "manual", "human"),
            "contract-review-reminder": ("oneshot", "dispatcher", "bridge"),
            "daily-health-report": ("recurring", "dispatcher", "bridge"),
            "public-funnel": ("daemon", "external", "foreign"),
            "voice-channel": ("daemon", "launchd", "bridge"),
            "voicememo-notify": ("watch", "launchd", "bridge"),
        }
        for wid, (kind, runtime, owner) in expected.items():
            with self.subTest(workload=wid):
                w = model.load_declaration(CORPUS / f"{wid}.yaml")
                self.assertEqual((w.placement.kind, w.placement.runtime, w.placement.owner),
                                 (kind, runtime, owner))

    def test_schema_defaults_are_materialised_not_left_none(self):
        # voicememo-notify declares neither isolation nor single_flight nor
        # on_timeout. Every one of those defaults is a scar, so a missing field
        # has to arrive as the safe value, never as None.
        w = model.load_declaration(CORPUS / "voicememo-notify.yaml")
        self.assertEqual(w.execution.isolation, "process-group")
        self.assertIs(w.execution.single_flight, True)
        self.assertEqual(w.execution.on_timeout, "report")

    def test_explicit_values_override_the_defaults(self):
        w = model.load_declaration(DERIVED / "process-isolation-report.yaml")
        self.assertEqual(w.execution.isolation, "process")
        self.assertIs(w.execution.single_flight, False)

    def test_delivery_and_duration_survive_as_declared(self):
        w = model.load_declaration(CORPUS / "daily-health-report.yaml")
        self.assertEqual(w.schedule.delivery_at, "06:30")
        self.assertEqual(w.schedule.duration_estimate_min, 20)
        self.assertEqual(w.schedule.timezone, "Europe/Berlin")
        self.assertEqual(w.schedule.rrule, "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR,SA")

    def test_watch_keeps_both_paths_and_cadence(self):
        # The pair is deliberate: a path watcher can fire before a file has
        # finished materialising, so the cadence is the fallback, not a mistake.
        w = model.load_declaration(CORPUS / "voicememo-notify.yaml")
        self.assertEqual(w.schedule.watch_paths, ("/opt/bridge/transcripts/voicememo",))
        self.assertEqual(w.schedule.every_sec, 120)

    def test_is_retired_is_presence_of_the_block(self):
        self.assertTrue(model.load_declaration(CORPUS / "voice-channel.yaml").is_retired)
        for wid in CORPUS_IDS:
            if wid == "voice-channel":
                continue
            with self.subTest(workload=wid):
                self.assertFalse(model.load_declaration(CORPUS / f"{wid}.yaml").is_retired)

    def test_is_bridge_owned(self):
        self.assertTrue(model.load_declaration(CORPUS / "calendar-export.yaml").is_bridge_owned)
        self.assertFalse(model.load_declaration(CORPUS / "chat-channel.yaml").is_bridge_owned)
        self.assertFalse(model.load_declaration(CORPUS / "public-funnel.yaml").is_bridge_owned)

    def test_display_title_falls_back_to_id(self):
        self.assertEqual(model.load_declaration(CORPUS / "chat-channel.yaml").display_title,
                         "chat-channel")
        self.assertEqual(model.load_declaration(CORPUS / "daily-health-report.yaml").display_title,
                         "Daily Health Report")

    def test_raw_is_kept_for_round_trip(self):
        w = model.load_declaration(CORPUS / "daily-health-report.yaml")
        self.assertEqual(w.raw["id"], "daily-health-report")
        self.assertEqual(w.raw["placement"]["host"], "host-a")

    def test_umlauts_survive_loading(self):
        w = model.load_declaration(DERIVED / "umlaut-report.yaml")
        self.assertIn("ä ö ü ß", w.purpose)
        self.assertIn("€", w.purpose)
        self.assertIn("prüfung.sh", w.execution.command[0])


class LoadingAFolder(MachineGuard):

    def test_load_all_returns_sorted_ids_and_skips_underscore_files(self):
        root = make_repo(self.tmpdir(), declarations=CORPUS_IDS)
        wl_dir = root / "workflow" / "workloads"
        (wl_dir / "_template.yaml").write_text("schema_version: 1\n", encoding="utf-8")
        (wl_dir / "_schema.yaml").write_text("schema_version: 1\n", encoding="utf-8")
        (wl_dir / "_tests").mkdir()
        (wl_dir / "_tests" / "sample.yaml").write_text("schema_version: 1\n", encoding="utf-8")
        cfg = config.load_config(root)
        got = [w.id for w in model.load_all(root, cfg)]
        self.assertEqual(got, sorted(CORPUS_IDS))

    def test_one_broken_file_fails_the_whole_call(self):
        # A silently skipped declaration is exactly how a run disappears.
        root = make_repo(self.tmpdir(), declarations=("calendar-export", "negative-broken-yaml"))
        cfg = config.load_config(root)
        with self.assertRaises(errors.DeclarationError) as ctx:
            model.load_all(root, cfg)
        self.assert_error(ctx, "declaration-invalid", "negative-broken-yaml")

    def test_duplicate_ids_are_refused_and_both_files_named(self):
        root = make_repo(self.tmpdir(), declarations=("calendar-export",))
        twin = root / "workflow" / "workloads" / "calendar-export-copy.yaml"
        twin.write_text(
            (CORPUS / "calendar-export.yaml").read_text(encoding="utf-8"), encoding="utf-8")
        cfg = config.load_config(root)
        with self.assertRaises(errors.DuplicateWorkloadId) as ctx:
            model.load_all(root, cfg)
        self.assert_error(ctx, "duplicate-workload-id",
                          "calendar-export.yaml", "calendar-export-copy.yaml")

    def test_id_filename_mismatch_is_refused(self):
        root = make_repo(self.tmpdir(), declarations=("wrong-filename",))
        cfg = config.load_config(root)
        with self.assertRaises(errors.IdFilenameMismatch) as ctx:
            model.load_all(root, cfg)
        self.assert_error(ctx, "id-filename-mismatch",
                          "wrong-filename", "this-id-does-not-match-the-filename")


class RejectingBadDeclarations(MachineGuard):

    def test_broken_yaml_names_the_file(self):
        with self.assertRaises(errors.DeclarationError) as ctx:
            model.load_declaration(INVALID / "negative-broken-yaml.yaml")
        self.assert_error(ctx, "declaration-invalid", "negative-broken-yaml.yaml")

    def test_unknown_runtime_names_key_and_value(self):
        with self.assertRaises(errors.DeclarationError) as ctx:
            model.load_declaration(INVALID / "negative-unknown-runtime.yaml")
        self.assert_error(ctx, "declaration-invalid", "runtime", "podman")

    def test_unknown_top_level_key_is_not_a_feature(self):
        with self.assertRaises(errors.DeclarationError) as ctx:
            model.load_declaration(INVALID / "negative-unknown-top-level-key.yaml")
        self.assert_error(ctx, "declaration-invalid", "statuss")

    def test_wrong_schema_version_names_the_field(self):
        with self.assertRaises(errors.DeclarationError) as ctx:
            model.load_declaration(INVALID / "negative-wrong-schema-version.yaml")
        self.assert_error(ctx, "declaration-invalid", "schema_version")


class TheInvariantGate(MachineGuard):
    """validate() is hand written on purpose, so it cannot fail identically to the schema."""

    def test_all_seven_pass_the_gate(self):
        for wid in CORPUS_IDS:
            with self.subTest(workload=wid):
                found = model.validate(load_raw(wid), source=f"{wid}.yaml")
                self.assertEqual(list(found), [], all_findings_text(found))

    def test_bridge_owned_run_without_a_deadline_is_refused(self):
        found = model.validate(load_raw("negative-no-deadline"), source="x.yaml")
        self.assertTrue(found, "a bridge owned run without timeout_sec passed the gate")
        self.assertIn("timeout_sec", all_findings_text(found))

    def test_interval_with_a_clock_time_is_refused(self):
        found = model.validate(load_raw("negative-interval-with-clock-time"), source="x.yaml")
        self.assertTrue(found, "an interval job carrying delivery_at passed the gate")
        self.assertIn("delivery_at", all_findings_text(found))

    def test_plaintext_recipient_address_is_refused(self):
        found = model.validate(load_raw("negative-plaintext-address"), source="x.yaml")
        self.assertTrue(found, "a plaintext recipient address passed the gate")
        self.assertIn("address", all_findings_text(found))

    def test_retired_without_a_reason_is_refused(self):
        found = model.validate(load_raw("negative-retired-without-reason"), source="x.yaml")
        self.assertTrue(found, "retiring without a reason passed the gate")
        self.assertIn("reason", all_findings_text(found))

    def test_recurring_without_an_rrule_is_refused(self):
        raw = load_raw("daily-health-report")
        raw["schedule"].pop("rrule")
        found = model.validate(raw, source="x.yaml")
        self.assertTrue(found, "a recurring workload without an rrule passed the gate")
        self.assertIn("rrule", all_findings_text(found))

    def test_daemon_carrying_a_schedule_is_refused(self):
        raw = load_raw("voice-channel")
        raw["schedule"] = {"every_sec": 60}
        found = model.validate(raw, source="x.yaml")
        self.assertTrue(found, "a daemon carrying a schedule passed the gate")

    def test_bridge_owned_run_without_evidence_is_refused(self):
        raw = load_raw("daily-health-report")
        raw["response"].pop("evidence")
        found = model.validate(raw, source="x.yaml")
        self.assertTrue(found, "a bridge owned run without evidence passed the gate")
        self.assertIn("evidence", all_findings_text(found))

    def test_the_gate_does_not_read_the_json_schema(self):
        # Two gates that read the same file are one gate with a second name.
        source = (SKILL_DIR / "engine" / "model.py").read_text(encoding="utf-8")
        self.assertNotIn("_schema.yaml", source,
                         "model.validate must be hand written, not derived from the schema file")


class ValuesThatWouldBreakTheFileTheyAreWrittenInto(MachineGuard):
    """The gate over the SHAPE of a value, not only over which fields exist.

    Every artifact this skill generates is line based, and none of the three
    formats escapes for us in every position: a systemd directive takes the
    rest of the line, a shell assignment in the guard script takes the rest of
    the line, and the id is written unquoted into unit names, labels and paths.
    A value that ends its line does not arrive escaped in the next one, it
    arrives as the next DIRECTIVE.

    Each case names the key path, because a refusal that does not say which
    field it means is a refusal somebody guesses at.
    """

    def raw_with(self, **overrides):
        raw = load_raw("daily-health-report")
        for dotted, value in overrides.items():
            head, _, tail = dotted.partition("__")
            if tail:
                raw.setdefault(head, {})[tail] = value
            else:
                raw[head] = value
        return raw

    # -- the id ------------------------------------------------------------

    def test_an_id_with_a_space_is_refused(self):
        found = model.validate(self.raw_with(id="daily health report"), source="x.yaml")
        self.assertTrue(found, "an id with a space passed the gate")
        self.assertIn("id", all_findings_text(found))

    def test_an_id_with_a_slash_is_refused(self):
        # A slash does not name the unit differently, it writes the file into a
        # different directory.
        found = model.validate(self.raw_with(id="../elsewhere/report"), source="x.yaml")
        self.assertTrue(found, "an id carrying a path passed the gate")

    def test_an_id_with_a_dollar_sign_is_refused(self):
        # The guard script writes the id inside double quotes, where a shell
        # expands it.
        found = model.validate(self.raw_with(id="report-$HOME"), source="x.yaml")
        self.assertTrue(found, "an id the shell would expand passed the gate")

    def test_the_slug_rule_is_the_one_the_ids_in_use_already_follow(self):
        for wid in CORPUS_IDS:
            with self.subTest(workload=wid):
                self.assertRegex(wid, model.ID_PATTERN)

    # -- environment names ---------------------------------------------------

    def test_an_environment_name_that_is_a_command_is_refused(self):
        # The NAME is never quoted by anybody: `Environment=NAME=...` and the
        # left hand side of a shell assignment both take it bare.
        #
        # The VALUE is a locator ON PURPOSE. With a plain `1` the OTHER rule in
        # this block -- values must be a locator -- fired as well, under the key
        # path `execution.env.<name>`, and "is execution.env somewhere in the
        # findings" was answered by that one. Measured: with the name rule
        # switched off entirely, this case stayed green.
        raw = self.raw_with()
        raw["execution"]["env"] = {"OK; rm -rf /tmp/gone": "keychain://token"}
        found = model.validate(raw, source="x.yaml")
        self.assertTrue(found, "an environment name carrying a command passed the gate")
        self.assertIn("execution.env", [f.key_path for f in found],
                      "nothing here is about the NAME: " + all_findings_text(found))
        self.assertIn("is not an environment variable name", all_findings_text(found))

    def test_an_environment_name_with_a_space_is_refused(self):
        # Same reason for the locator value as the case above.
        raw = self.raw_with()
        raw["execution"]["env"] = {"TWO WORDS": "keychain://token"}
        found = model.validate(raw, source="x.yaml")
        self.assertTrue(found, "an environment name with a space passed the gate")
        self.assertIn("execution.env", [f.key_path for f in found],
                      "nothing here is about the NAME: " + all_findings_text(found))

    def test_a_plain_environment_name_passes(self):
        # The negative control of the two above: the rule refuses a shape, not
        # the presence of an environment block. The VALUES are locators because
        # a second rule now holds them to that -- this case is about the NAME,
        # so it must not fail for the other reason.
        raw = self.raw_with()
        raw["execution"]["env"] = {"GREETING": "keychain://greeting",
                                   "_UNDER_2": "file:///etc/bridge/two"}
        self.assertEqual(list(model.validate(raw, source="x.yaml")), [])

    def test_declaring_the_ownership_marker_as_a_variable_is_refused(self):
        # Ownership is read back out of exactly this variable. Setting it does
        # not configure the run, it renames who the live unit belongs to.
        # The value is a locator for the same reason as the two cases above: a
        # value that is not one is refused by the OTHER rule in this block, under
        # a key path that CONTAINS the marker name, so asking whether the marker
        # is named anywhere was answered without the marker rule running.
        raw = self.raw_with()
        raw["execution"]["env"] = {model.MARKER_ENV_ID: "keychain://somebody-elses-workload"}
        found = model.validate(raw, source="x.yaml")
        self.assertTrue(found, "a declaration renamed its own owner and passed")
        self.assertIn("execution.env", [f.key_path for f in found],
                      "nothing here is about the marker: " + all_findings_text(found))
        self.assertIn("ownership marker", all_findings_text(found))

    # -- line breaks, wherever a value is written -----------------------------

    def test_a_line_break_is_refused_in_every_field_that_reaches_a_file(self):
        cases = {
            "title": lambda raw: raw.update({"title": "report\nExecStart=/bin/false"}),
            "execution.command": lambda raw: raw["execution"].__setitem__(
                "command", ["/bin/true\nExecStartPre=/bin/false"]),
            "execution.working_dir": lambda raw: raw["execution"].__setitem__(
                "working_dir", "/tmp\nUser=root"),
            "execution.env": lambda raw: raw["execution"].__setitem__(
                "env", {"BROKEN": "one\nRuntimeMaxSec=1"}),
        }
        for key_path, mutate in cases.items():
            with self.subTest(field=key_path):
                raw = self.raw_with()
                mutate(raw)
                found = model.validate(raw, source="x.yaml")
                self.assertTrue(found, f"a line break in {key_path} passed the gate")
                self.assertIn(key_path, all_findings_text(found))

    def test_a_line_break_in_a_watched_path_is_refused(self):
        raw = load_raw("voicememo-notify")
        raw["schedule"]["watch_paths"] = ["/tmp/in\nUnit=other.service"]
        found = model.validate(raw, source="x.yaml")
        self.assertTrue(found, "a line break in a watched path passed the gate")
        self.assertIn("schedule.watch_paths[0]", all_findings_text(found))

    def test_a_nul_byte_is_refused_too(self):
        raw = self.raw_with(title="report\x00hidden")
        found = model.validate(raw, source="x.yaml")
        self.assertTrue(found, "a NUL byte passed the gate")

    def test_the_purpose_is_not_shape_checked_because_it_reaches_no_file(self):
        # A negative control on the SCOPE of the rule. Documentation is allowed
        # to be several lines; extending the refusal to it would be a rule with
        # no failure behind it.
        raw = self.raw_with(purpose="a purpose\nover two lines, which is fine")
        self.assertEqual(list(model.validate(raw, source="x.yaml")), [])

    # -- the same rule, at the moment of writing ------------------------------

    def test_the_backstop_under_the_gate_refuses_the_same_value(self):
        # `render` is reachable with a Workload nobody validated. The predicate
        # is shared, so the two refusals cannot drift apart.
        self.assertEqual(model.unsafe_reason("plain value"), "")
        self.assertTrue(model.unsafe_reason("two\nlines"))
        with self.assertRaises(errors.DeclarationError) as ctx:
            model.ensure_unit_safe("two\nlines", key_path="execution.env.X",
                                   workload_id="some-workload")
        self.assert_error(ctx, "declaration-invalid", "execution.env.X", "some-workload")


class TheSecondGate(MachineGuard):
    """The independent validator: what it is asked, and how each answer is read.

    Each case here pins ONE answer to ONE verdict, and the recorded runner says
    what was really handed outwards. The shape this replaces passed in a
    recorder, never let the gate resolve a tool at all, and then asserted that
    some field was set. That asserts a dataclass has fields: the whole function
    could be replaced by an unconditional pass and the case stayed green.

    PATH is what the gate resolves against, so PATH is what these cases control.
    Nothing here needs the repository around it and nothing needs a validator to
    be installed, which is why the answers stay the same in a copy of the skill
    taken out of the tree.
    """

    def gate_schema(self):
        """A schema path of this test's own, so no repository is needed."""
        path = self.tmpdir() / "_schema.yaml"
        path.write_text("type: object\n", encoding="utf-8")
        return path

    def a_tool_on_path(self):
        """PATH holding one executable named like the validator, and nothing else."""
        directory = self.tmpdir()
        tool = directory / "check-jsonschema"
        tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        tool.chmod(0o755)
        return mock.patch.dict(os.environ, {"PATH": str(directory)})

    def test_absent_validator_is_reported_never_skipped(self):
        runner = RecordingRunner()
        with mock.patch.dict(os.environ, {"PATH": ""}):
            verdict = model.validate_with_schema(
                declaration("daily-health-report"), self.gate_schema(), runner)
        self.assertEqual(
            verdict.verdict, "schema_validator_absent",
            "a gate that could not run has to say so; a check nobody ran is not green")
        self.assertIn("check-jsonschema", verdict.detail,
                      "the report does not name the tool that is missing")
        self.assertEqual(runner.calls, [],
                         f"the gate reported a run for a tool it never found:\n"
                         f"{runner.joined_calls}")

    def test_a_missing_contract_is_named_and_the_tool_is_never_run(self):
        # Handed a schema path that is not there, check-jsonschema fails to BUILD
        # a validator and exits non-zero, which read as `invalid`. A repository
        # missing its contract therefore reported every declaration as refused,
        # named a file inside the tool's own virtualenv as the objection, and
        # sent a human to fix a declaration nobody had read.
        runner = RecordingRunner()
        missing = self.tmpdir() / "_schema.yaml"
        with self.a_tool_on_path():
            verdict = model.validate_with_schema(
                declaration("daily-health-report"), missing, runner)
        self.assertEqual(verdict.verdict, "schema_missing",
                         "an absent contract was reported as something else")
        self.assertIn(str(missing), verdict.detail,
                      "the answer does not say WHICH file is missing")
        self.assertEqual(runner.calls, [],
                         f"the validator was run against a schema that is not there:\n"
                         f"{runner.joined_calls}")

    def test_the_tool_is_really_run_against_the_schema_and_the_file(self):
        path = declaration("daily-health-report")
        schema = self.gate_schema()
        runner = RecordingRunner()
        with self.a_tool_on_path():
            verdict = model.validate_with_schema(path, schema, runner)
        self.assertEqual(len(runner.calls), 1,
                         f"the gate made {len(runner.calls)} calls:\n{runner.joined_calls}")
        joined = runner.calls[0]["joined"]
        for needle in ("check-jsonschema", "--schemafile", str(schema), str(path)):
            self.assertIn(needle, joined, f"the call does not carry {needle!r}: {joined}")
        self.assertTrue(runner.calls[0]["kwargs"].get("timeout_sec"),
                        "the second gate reached outwards without a deadline")
        self.assertEqual(verdict.verdict, "valid")

    def test_a_validator_that_refuses_is_never_read_as_valid(self):
        # The return code is the whole answer, and reading it wrongly is exactly
        # how a gate goes hollow while its name keeps promising.
        runner = RecordingRunner()
        runner.add("check-jsonschema",
                   FakeCompleted(rc=1, stdout="$.purpose: 'x' is too short"))
        with self.a_tool_on_path():
            verdict = model.validate_with_schema(
                declaration("daily-health-report"), self.gate_schema(), runner)
        self.assertEqual(verdict.verdict, "invalid")
        self.assertIn("too short", verdict.detail,
                      "the refusal was recorded without what the validator objected to")

    def test_the_validator_path_is_never_hardcoded(self):
        source = (SKILL_DIR / "engine" / "model.py").read_text(encoding="utf-8")
        self.assertIn("shutil.which", source)
        self.assertNotIn("/.local/bin/check-jsonschema", source)


class RequiredGuarantees(MachineGuard):

    def test_derived_from_the_declaration(self):
        g = model.Guarantee
        w = model.load_declaration(CORPUS / "daily-health-report.yaml")
        self.assertEqual(
            set(model.required_guarantees(w)),
            {g.deadline, g.process_group_kill, g.single_flight, g.missing_detection},
        )

    def test_process_isolation_drops_the_group_kill_requirement(self):
        g = model.Guarantee
        w = model.load_declaration(DERIVED / "process-isolation-report.yaml")
        required = set(model.required_guarantees(w))
        self.assertIn(g.deadline, required)
        self.assertNotIn(g.process_group_kill, required)
        self.assertNotIn(g.single_flight, required)
        self.assertNotIn(g.missing_detection, required)

    def test_missing_detection_only_when_notify_on_asks_for_it(self):
        # voicememo-notify asks for `failure` and names log-trace as its
        # evidence, so it DOES need the line: that is where a non zero run is
        # written down. A declaration that asks for neither does not.
        g = model.Guarantee
        w = model.load_declaration(CORPUS / "voicememo-notify.yaml")
        self.assertIn(g.missing_detection, set(model.required_guarantees(w)))
        object.__setattr__(w.response, "notify_on", ("timeout",))
        self.assertNotIn(g.missing_detection, set(model.required_guarantees(w)))


class Digests(MachineGuard):

    def test_digest_is_deterministic(self):
        a = model.load_declaration(CORPUS / "daily-health-report.yaml")
        b = model.load_declaration(CORPUS / "daily-health-report.yaml")
        self.assertEqual(model.declaration_digest(a), model.declaration_digest(b))
        self.assertTrue(model.declaration_digest(a).startswith("sha256:"))

    def test_key_order_does_not_change_the_digest(self):
        import yaml

        src = CORPUS / "daily-health-report.yaml"
        raw = yaml.safe_load(src.read_text(encoding="utf-8"))
        reordered = dict(reversed(list(raw.items())))
        tmp = self.tmpdir() / "daily-health-report.yaml"
        tmp.write_text(yaml.safe_dump(reordered, sort_keys=False, allow_unicode=True),
                       encoding="utf-8")
        self.assertEqual(
            model.declaration_digest(model.load_declaration(src)),
            model.declaration_digest(model.load_declaration(tmp)),
        )

    def test_cosmetic_fields_do_not_count_as_drift(self):
        import yaml

        src = CORPUS / "daily-health-report.yaml"
        base = model.declaration_digest(model.load_declaration(src))
        raw = yaml.safe_load(src.read_text(encoding="utf-8"))
        raw["title"] = "A Completely Different Title"
        raw["purpose"] = "A typo in the purpose is not a reason to reprovision anything"
        raw["learned_from"] = "some incident"
        raw["placement"]["provisioned_at"] = "2026-08-22T10:00:00+02:00"
        tmp = self.tmpdir() / "daily-health-report.yaml"
        tmp.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
        self.assertEqual(base, model.declaration_digest(model.load_declaration(tmp)))

    def test_a_changed_command_is_drift(self):
        import yaml

        src = CORPUS / "daily-health-report.yaml"
        base = model.declaration_digest(model.load_declaration(src))
        raw = yaml.safe_load(src.read_text(encoding="utf-8"))
        raw["execution"]["command"] = ["/opt/bridge/scripts/something-else.sh"]
        tmp = self.tmpdir() / "daily-health-report.yaml"
        tmp.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
        self.assertNotEqual(base, model.declaration_digest(model.load_declaration(tmp)))

    def test_canonical_payload_is_bytes_and_sorted(self):
        w = model.load_declaration(CORPUS / "daily-health-report.yaml")
        payload = model.canonical_payload(w)
        self.assertIsInstance(payload, bytes)
        self.assertEqual(payload, model.canonical_payload(w))


class PatchingADeclaration(MachineGuard):

    def test_block_style_patch_keeps_comments_and_every_other_line(self):
        src = DERIVED / "block-style-report.yaml"
        target = self.tmpdir() / "block-style-report.yaml"
        before = src.read_text(encoding="utf-8")
        target.write_text(before, encoding="utf-8")

        model.patch_declaration(target, ("placement", "provisioned_at"),
                                "2026-08-22T10:00:00+02:00")
        after = target.read_text(encoding="utf-8")

        self.assertIn("2026-08-22T10:00:00+02:00", after)
        self.assertIn("# trailing comment that must survive a patch", after)
        self.assertIn("# yaml-language-server:", after)
        before_lines = before.splitlines()
        after_lines = after.splitlines()
        self.assertEqual(len(before_lines), len(after_lines),
                         "a surgical patch must not add or drop lines")
        changed = [i for i, (x, y) in enumerate(zip(before_lines, after_lines)) if x != y]
        self.assertEqual(len(changed), 1, f"more than one line changed: {changed}")
        self.assertIn("provisioned_at", after_lines[changed[0]])

    def test_a_patch_never_round_trips_the_file_through_yaml(self):
        source = (SKILL_DIR / "engine" / "model.py").read_text(encoding="utf-8")
        self.assertNotIn("safe_dump", source,
                         "a dump round trip loses the comments and the schema hint line")

    def test_flow_style_is_refused_with_the_snippet_to_paste(self):
        # Six of the seven real declarations write placement in flow style.
        src = CORPUS / "daily-health-report.yaml"
        target = self.tmpdir() / "daily-health-report.yaml"
        before = src.read_text(encoding="utf-8")
        target.write_text(before, encoding="utf-8")
        with self.assertRaises(errors.UnpatchableDeclaration) as ctx:
            model.patch_declaration(target, ("placement", "provisioned_at"),
                                    "2026-08-22T10:00:00+02:00")
        self.assert_error(ctx, "unpatchable-declaration", "placement", "provisioned_at")
        self.assertEqual(target.read_text(encoding="utf-8"), before,
                         "a refused patch must leave the file byte identical")


class RetiringADeclaration(MachineGuard):

    def test_write_retired_appends_the_block(self):
        target = self.tmpdir() / "calendar-export.yaml"
        target.write_text((CORPUS / "calendar-export.yaml").read_text(encoding="utf-8"),
                          encoding="utf-8")
        model.write_retired(target, "2026-08-22", "superseded by the timer unit", None)
        text = target.read_text(encoding="utf-8")
        self.assertIn("retired:", text)
        self.assertIn("superseded by the timer unit", text)
        self.assertIn("2026-08-22", text)
        w = model.load_declaration(target)
        self.assertTrue(w.is_retired)

    def test_superseded_by_is_recorded_when_given(self):
        target = self.tmpdir() / "calendar-export.yaml"
        target.write_text((CORPUS / "calendar-export.yaml").read_text(encoding="utf-8"),
                          encoding="utf-8")
        model.write_retired(target, "2026-08-22", "migrated to the timer unit",
                            "linux-timer-report")
        self.assertIn("linux-timer-report", target.read_text(encoding="utf-8"))

    def test_a_short_reason_is_refused_before_anything_is_written(self):
        target = self.tmpdir() / "calendar-export.yaml"
        before = (CORPUS / "calendar-export.yaml").read_text(encoding="utf-8")
        target.write_text(before, encoding="utf-8")
        with self.assertRaises(errors.ReasonTooShort) as ctx:
            model.write_retired(target, "2026-08-22", "weg", None)
        self.assert_error(ctx, "reason-too-short", "8")
        self.assertEqual(target.read_text(encoding="utf-8"), before)

    def test_retiring_twice_is_refused(self):
        target = self.tmpdir() / "voice-channel.yaml"
        target.write_text((CORPUS / "voice-channel.yaml").read_text(encoding="utf-8"),
                          encoding="utf-8")
        with self.assertRaises(errors.AlreadyRetired) as ctx:
            model.write_retired(target, "2026-08-22", "a second retirement", None)
        self.assert_error(ctx, "already-retired", "voice-channel")


class Scaffolding(MachineGuard):
    """`scaffold` builds from the declaration TEMPLATE, which lives in the repo.

    The template is not part of this skill: it sits under `workflow/workloads/`
    next to the schema, and `scaffold` reaches it through the repository root.
    A copy of the skill taken out of a Bridge therefore has nothing to scaffold
    from, and the mutation battery runs in exactly such a copy. Left alone
    these two cases collapse there with a RepoRootNotFound, which is a red that
    says nothing about the code under test and a trap for the next needle that
    happens to name one of them.

    So the dependency is stated and skipped WITH a reason, rather than being
    discovered as an error somewhere down the line.
    """

    def setUp(self):
        super().setUp()
        if self.template() is None:
            self.skipTest("no workflow/workloads/_template.yaml above this copy of the "
                          "skill: scaffold builds from the template in the repository, "
                          "so a detached copy has nothing to build from")

    def template(self):
        """The declaration template, if this copy of the skill can still see it."""
        try:
            root = Path(config.find_repo_root())
        except errors.RepoRootNotFound:
            return None
        path = root / config.DEFAULT_DIR / "_template.yaml"
        return path if path.exists() else None

    def test_scaffold_keeps_the_template_comments(self):
        text = model.scaffold("new-report", kind="recurring", runtime="launchd", host="host-a")
        self.assertIn("schema_version: 1", text)
        self.assertIn("new-report", text)
        self.assertIn("#", text, "the template comments carry the why and must survive")

    def test_scaffold_never_invents_what_it_was_not_given(self):
        text = model.scaffold("new-report")
        for invented in ("host-a", "recurring", "launchd"):
            self.assertNotIn(f": {invented}\n", text,
                             f"scaffold invented {invented!r} instead of leaving a placeholder")


class OwnershipVocabulary(MachineGuard):

    def test_the_marker_constants_exist_in_exactly_one_place(self):
        self.assertEqual(model.MARKER_ENV_ID, "BRIDGE_WORKLOAD")
        self.assertEqual(model.MARKER_ENV_DIGEST, "BRIDGE_WORKLOAD_DIGEST")
        self.assertEqual(model.STAMP_SUFFIX, ".stamp.json")
        self.assertEqual(model.STAMP_VERSION, 1)
        self.assertIn("bridge-workload", model.CRON_BEGIN)
        self.assertIn("bridge-workload", model.CRON_END)

    def test_the_state_enum_is_closed_at_nineteen(self):
        # It grew by two when the guard script's trace was finally read back.
        # Until then a run that ended non zero and a run that never came read
        # exactly like a healthy one, because nothing ever consulted the line
        # the wrapper writes after every run. The sixteenth arrived the same
        # way: the stamp records which client path a privacy grant was issued
        # to, and a renamed interpreter left the grant behind in silence.
        # The seventeenth is the other half of `inventory_stale`: an entry that
        # names nothing may be a record nobody maintained OR a decision
        # somebody wrote down, and one word for both turns nine decisions into
        # nine chores. The eighteenth came from the same audit: the off-list
        # that decides whether anything can start was read by `provision` and
        # never by the pass that reports how the machine is. The nineteenth
        # came from the same comparison: `in_sync` is about the unit and the
        # artifact, and neither of them is the program the unit calls.
        members = {m.value for m in model.WorkloadState}
        self.assertEqual(members, {
            "in_sync", "not_provisioned", "absent", "stopped", "drifted", "unstamped",
            "retired_but_live", "observed", "unknown", "orphan_stamp", "unmanaged",
            "inventory_missing", "inventory_stale",
            "last_run_failed", "overdue", "grant_orphaned",
            "intentionally_absent", "disabled", "source_drift",
        })

    def test_severity_and_guarantee_enums(self):
        self.assertEqual({m.value for m in model.Severity}, {"high", "medium", "info"})
        self.assertEqual({m.value for m in model.Guarantee},
                         {"deadline", "process_group_kill", "single_flight", "missing_detection"})

    def test_step_defaults(self):
        step = model.Step(argv=("/bin/true",), purpose="a no op")
        self.assertEqual(step.expect_rc, (0,))
        self.assertIsNone(step.timeout_sec)
        self.assertFalse(step.requires_elevation)
        with self.assertRaises(Exception):
            step.argv = ("/bin/false",)  # frozen


class ConfigAndHosts(MachineGuard):

    def test_missing_workloads_block_yields_defaults_never_a_crash(self):
        root = self.tmpdir()
        (root / "bridge-config.yaml").write_text("work:\n  enabled: true\n", encoding="utf-8")
        cfg = config.load_config(root)
        self.assertEqual(cfg.dir, "workflow/workloads")
        self.assertEqual(cfg.label_prefix, "bridge")
        self.assertEqual(cfg.stamp_dir, "~/.bridge/workloads")
        self.assertEqual(cfg.step_timeout_sec, 60)
        self.assertEqual(cfg.probe_timeout_sec, 30)
        self.assertEqual(cfg.ssh_connect_timeout_sec, 10)
        self.assertEqual(tuple(cfg.dispatcher_guarantees), ())
        self.assertIsNone(cfg.dispatcher_registry)

    def test_declared_values_win_over_the_defaults(self):
        root = make_repo(self.tmpdir(), config=(
            "workloads:\n"
            "  dir: workflow/runs\n"
            "  label_prefix: acme\n"
            "  step_timeout_sec: 5\n"
        ))
        cfg = config.load_config(root)
        self.assertEqual(cfg.dir, "workflow/runs")
        self.assertEqual(cfg.label_prefix, "acme")
        self.assertEqual(cfg.step_timeout_sec, 5)

    def test_repo_root_is_found_through_a_symlink(self):
        root = make_repo(self.tmpdir())
        nested = root / "a" / "b"
        nested.mkdir(parents=True)
        self.assertEqual(config.find_repo_root(nested).resolve(), root.resolve())

    def test_repo_root_not_found_is_an_error_not_a_guess(self):
        with self.assertRaises(errors.RepoRootNotFound) as ctx:
            config.find_repo_root(Path("/"))
        self.assert_error(ctx, "repo-root-not-found")

    def test_resolve_host_reads_the_remote_file(self):
        root = make_repo(self.tmpdir())
        host = hosts.resolve_host("host-a", root)
        self.assertEqual(host.platform, "macos")
        self.assertFalse(host.is_local)
        self.assertTrue(host.services)

    def test_local_host_detects_its_platform_instead_of_assuming(self):
        root = make_repo(self.tmpdir())
        host = hosts.resolve_host("local", root)
        self.assertTrue(host.is_local)
        self.assertIn(host.platform, {"macos", "linux", "windows"})

    def test_unknown_host_is_refused(self):
        root = make_repo(self.tmpdir())
        with self.assertRaises(errors.HostUnknown) as ctx:
            hosts.resolve_host("host-that-does-not-exist", root)
        self.assert_error(ctx, "host-unknown", "host-that-does-not-exist")

    def test_the_support_matrix(self):
        root = make_repo(self.tmpdir())
        mac = hosts.resolve_host("host-a", root)
        linux = hosts.resolve_host("host-b", root)
        for runtime in ("launchd", "launchd-system", "cron", "dispatcher"):
            self.assertTrue(hosts.supports(mac, runtime), runtime)
        self.assertFalse(hosts.supports(mac, "systemd"))
        for runtime in ("systemd", "cron", "dispatcher"):
            self.assertTrue(hosts.supports(linux, runtime), runtime)
        self.assertFalse(hosts.supports(linux, "launchd"))

    def test_an_unsupported_platform_supports_nothing(self):
        root = make_repo(self.tmpdir(), hosts=("host-a", "host-b", "host-c", "host-windows"))
        box = hosts.resolve_host("host-windows", root)
        for runtime in ("launchd", "systemd", "cron", "dispatcher"):
            self.assertFalse(hosts.supports(box, runtime), runtime)

    def test_a_remote_file_is_never_read_for_credentials(self):
        source = (SKILL_DIR / "engine" / "hosts.py").read_text(encoding="utf-8")
        for word in ("password", "secret", "token", "keyvault", "keychain"):
            self.assertNotIn(word, source.lower())


class Reporting(MachineGuard):

    def test_exit_code_is_one_when_anything_high_or_medium_is_found(self):
        s, st = model.Severity, model.WorkloadState
        clean = report.Report(findings=[
            report.Finding(workload_id="a", state=st.observed, severity=s.info,
                           detail="seen", hint="", source="declaration"),
        ])
        self.assertEqual(clean.exit_code, 0)
        for severity in (s.medium, s.high):
            noisy = report.Report(findings=[
                report.Finding(workload_id="a", state=st.absent, severity=severity,
                               detail="gone", hint="provision it", source="machine"),
            ])
            self.assertEqual(noisy.exit_code, 1, severity)

    def test_a_clean_report_prints_one_line(self):
        rendered = report.render_table(report.Report(findings=[]))
        self.assertEqual(len([l for l in rendered.splitlines() if l.strip()]), 1)

    def test_a_clean_report_still_says_what_it_covered(self):
        # Silence over nothing is not the same answer as silence over seventy
        # four. The header used to be dropped on exactly the path where it
        # matters most: no findings. `workload validate` then reported the clean
        # line over ZERO declarations and exited 0, and the sentence it was
        # breaking is one this suite writes down about its own scans.
        rep = report.Report(findings=[],
                            header="0 declarations checked: nothing matched")
        rendered = report.render_table(rep)
        self.assertIn("0 declarations checked", rendered,
                      "a clean report that does not say what it covered is a green "
                      "light over an empty scan")
        self.assertIn(report.CLEAN_LINE, rendered)
        self.assertEqual(rendered.splitlines()[0], rep.header,
                         "the header has to come first, as it does on every other path")

    def test_every_finding_line_says_what_to_do(self):
        s, st = model.Severity, model.WorkloadState
        rep = report.Report(findings=[
            report.Finding(workload_id="calendar-export", state=st.absent, severity=s.high,
                           detail="declared and provisioned, nothing on the machine",
                           hint="run provision again", source="machine"),
        ])
        rendered = report.render_table(rep)
        self.assertIn("calendar-export", rendered)
        self.assertIn("run provision again", rendered)

    def test_json_rendering_round_trips(self):
        import json as _json

        s, st = model.Severity, model.WorkloadState
        rep = report.Report(findings=[
            report.Finding(workload_id="a", state=st.unknown, severity=s.medium,
                           detail="host did not answer", hint="check the box", source="machine"),
        ])
        payload = _json.loads(report.render_json(rep))
        self.assertEqual(payload["findings"][0]["state"], "unknown")
        self.assertEqual(payload["findings"][0]["severity"], "medium")


if __name__ == "__main__":
    unittest.main()


class TheHandWrittenGateHoldsWhatTheSchemaHolds(MachineGuard):
    """Four rules the declaration schema carries, and the gate did not.

    They were added on the schema side in the same round and the hand written
    gate did not follow, which put the two gates in open disagreement: `validate`
    answered clean over a declaration `validate --strict` refused. That is worse
    than one gate, because the gate that stayed quiet is the one the LAYER THAT
    ACTS consults -- `provision.plan` calls `model.validate` and never asks the
    schema, which needs a tool that is not installed everywhere. A plaintext
    secret and a relative argv[0] therefore reached a machine through a path on
    which nothing refused them.

    So the four rules are written out here by hand, character for character with
    the schema and reading no part of it. Each case below is one of them, and
    each carries its own negative control: a rule that refuses everything would
    satisfy the positive half of every case in this class.
    """

    def raw_with(self, **overrides):
        raw = load_raw("daily-health-report")
        for dotted, value in overrides.items():
            head, _, tail = dotted.partition("__")
            if tail:
                raw.setdefault(head, {})[tail] = value
            else:
                raw[head] = value
        return raw

    def refusals_for(self, raw) -> str:
        return all_findings_text(model.validate(raw, source="x.yaml"))

    # -- absolute paths ------------------------------------------------------

    def test_a_relative_argv_zero_is_refused(self):
        # A service manager starts a unit with a short PATH and no login shell,
        # so `claude` is not the `claude` a terminal finds.
        raw = self.raw_with()
        raw["execution"]["command"] = ["claude", "-p", "..."]
        text = self.refusals_for(raw)
        self.assertIn("execution.command[0]", text,
                      "a relative argv[0] passed the hand written gate")

    def test_a_tilde_in_argv_zero_is_refused_by_the_same_rule(self):
        # No backend expands a tilde, so `~/bin/x` is a relative path with a
        # character in front of it and needs no rule of its own.
        raw = self.raw_with()
        raw["execution"]["command"] = ["~/bin/report.sh"]
        self.assertIn("execution.command[0]", self.refusals_for(raw))

    def test_only_argv_zero_is_held_to_it(self):
        # The negative control. The arguments after argv[0] are flags and
        # values; a rule over them would be a guess, and a gate that refused
        # them would make every case above pass for the wrong reason.
        raw = self.raw_with()
        raw["execution"]["command"] = ["/opt/bridge/bin/report", "--horizon", "30d"]
        self.assertEqual(list(model.validate(raw, source="x.yaml")), [])

    def test_a_relative_interpreter_is_refused(self):
        raw = self.raw_with()
        raw["placement"]["interpreter"] = "python3"
        self.assertIn("placement.interpreter", self.refusals_for(raw))

    def test_a_relative_working_directory_is_refused(self):
        raw = self.raw_with()
        raw["execution"]["working_dir"] = "~/Developer/example"
        self.assertIn("execution.working_dir", self.refusals_for(raw))

    def test_an_absolute_interpreter_and_working_directory_pass(self):
        raw = self.raw_with()
        raw["placement"]["interpreter"] = "/usr/bin/python3"
        raw["execution"]["working_dir"] = "/opt/bridge"
        self.assertEqual(list(model.validate(raw, source="x.yaml")), [])

    # -- an environment value is a locator -----------------------------------

    def test_a_secret_pasted_into_the_environment_is_refused(self):
        # Refused because it IS a value, not because it looks like a key. The
        # declaration is a tracked file, so this travels verbatim onto the
        # machine AND into git.
        raw = self.raw_with()
        raw["execution"]["env"] = {"API_KEY": "sk-live-not-a-real-key"}
        self.assertIn("execution.env.API_KEY", self.refusals_for(raw))

    def test_every_locator_scheme_the_schema_names_is_accepted_here_too(self):
        # The negative control, and the place the two lists would drift apart.
        for locator in ("azure-keyvault://vault/name", "keychain://item",
                        "1password://vault/item/field", "op://vault/item/field",
                        "keepass://personal/group/entry/password",
                        "vault://secret/path", "file:///etc/bridge/token"):
            with self.subTest(locator=locator):
                raw = self.raw_with()
                raw["execution"]["env"] = {"TOKEN": locator}
                self.assertEqual(list(model.validate(raw, source="x.yaml")), [])

    def test_what_this_rule_does_not_do_is_written_down_as_a_case(self):
        # A secret TYPED as a locator is well formed and passes. This is a shape
        # rule; claiming it stops secret leakage would be the stronger promise
        # nothing here keeps.
        raw = self.raw_with()
        raw["execution"]["env"] = {"API_KEY": "keychain://sk-live-not-a-real-key"}
        self.assertEqual(list(model.validate(raw, source="x.yaml")), [])

    # -- a recipient is a reference ------------------------------------------

    def test_a_plaintext_address_in_the_mandant_is_refused(self):
        raw = self.raw_with()
        raw["response"]["recipients"] = [{"mandant": "a.person@example.com"}]
        self.assertIn("response.recipients[0].mandant", self.refusals_for(raw))

    def test_a_phone_number_in_the_person_is_refused(self):
        raw = self.raw_with()
        raw["response"]["recipients"] = [{"mandant": "example-org",
                                          "person": "+49 170 1234567"}]
        self.assertIn("response.recipients[0].person", self.refusals_for(raw))

    def test_a_written_out_name_is_refused_by_the_form_alone(self):
        # No detector, no word list: a slug has no capital and no space.
        raw = self.raw_with()
        raw["response"]["recipients"] = [{"mandant": "example-org",
                                          "person": "Jane Doe"}]
        self.assertIn("response.recipients[0].person", self.refusals_for(raw))

    def test_the_two_slug_shapes_that_are_in_use_pass(self):
        # The negative control, and the one place the two patterns differ: a
        # person key carries an underscore, a mandant slug does not.
        raw = self.raw_with()
        raw["response"]["recipients"] = [{"mandant": "example-org",
                                          "person": "person_a"}]
        self.assertEqual(list(model.validate(raw, source="x.yaml")), [])

    def test_an_underscore_is_not_allowed_in_the_mandant(self):
        # The two patterns are NOT the same pattern, and this is where that is
        # visible. Reusing one for both would pass every other case here.
        raw = self.raw_with()
        raw["response"]["recipients"] = [{"mandant": "example_org"}]
        self.assertIn("response.recipients[0].mandant", self.refusals_for(raw))

    # -- exactly one trigger, and it is the kind's own ------------------------

    def test_a_oneshot_carrying_a_cadence_is_refused(self):
        # Requiring the RIGHT key never said the wrong ones must be absent. A
        # oneshot carrying every_sec reads to a human as a recurring job and
        # fires once; which of the two the backend takes is not written anywhere.
        raw = self.raw_with()
        raw["placement"]["kind"] = "oneshot"
        raw["schedule"] = {"at": "2026-10-15T09:00:00+02:00", "every_sec": 900,
                           "timezone": "Europe/Berlin"}
        self.assertIn("schedule.every_sec", self.refusals_for(raw))

    def test_a_watcher_carrying_an_rrule_is_refused(self):
        raw = self.raw_with()
        raw["placement"]["kind"] = "watch"
        raw["schedule"] = {"watch_paths": ["/opt/bridge/in"], "rrule": "FREQ=DAILY",
                           "timezone": "Europe/Berlin"}
        self.assertIn("schedule.rrule", self.refusals_for(raw))

    def test_the_one_named_exception_still_passes(self):
        # The negative control, and the only pairing the contract allows: a path
        # watcher may add a fallback cadence, because a watch can fire before
        # the file it watches has finished materialising.
        raw = self.raw_with()
        raw["placement"]["kind"] = "watch"
        raw["schedule"] = {"watch_paths": ["/opt/bridge/in"], "every_sec": 900,
                           "timezone": "Europe/Berlin"}
        self.assertEqual(list(model.validate(raw, source="x.yaml")), [])


class AskingForFailureAsksForTheEvidence(MachineGuard):
    """`failure` is only ever visible in the trace, so asking for one asks for both.

    The guard script writes its trace only when `missing_detection` is required,
    and that was tied to `missing` alone. A declaration that asked for `failure`
    therefore got no trace at all, and the run that ended non zero left nothing
    behind that any reader could find. Found by building the probe that was
    supposed to prove failures arrive: it did not write a single line.
    """

    def w(self, notify_on):
        import copy
        base = model.load_declaration(CORPUS / "calendar-export.yaml")
        return copy.deepcopy(base), notify_on

    def required_for(self, notify_on):
        w = model.load_declaration(CORPUS / "calendar-export.yaml")
        object.__setattr__(w.response, "notify_on", tuple(notify_on))
        return model.required_guarantees(w)

    def test_failure_alone_still_requires_the_trace(self):
        self.assertIn(
            model.Guarantee.missing_detection, self.required_for(("failure",)),
            "the only place a non zero run is written down is the trace; without "
            "it the failure is real and unfindable")

    def test_missing_alone_still_requires_the_trace(self):
        self.assertIn(model.Guarantee.missing_detection,
                      self.required_for(("missing",)))

    def test_a_declaration_that_asks_for_neither_gets_no_trace(self):
        self.assertNotIn(
            model.Guarantee.missing_detection, self.required_for(("timeout",)),
            "a file written on every run of every workload nobody reads is cost "
            "without a reader")


class TheProcessKeepsItsNameAcrossAnUpdate(MachineGuard):
    """An interpreter path that carries a version number is a job with an expiry date.

    Two independent failures hang on the same character sequence, and both are
    silent. The file itself disappears on the next upgrade, because that is what
    a versioned directory is for, so the unit starts nothing. And on macOS the
    privacy grant is keyed on the literal path, so even a path that still exists
    loses every grant the moment the version segment moves.

    Measured in a real TCC database rather than assumed: six consecutive
    claude versions each hold their own row under
    `.local/share/claude/versions/<version>`, five of them granting nothing,
    because every update wrote a new path and therefore a new client. The same
    database carries the counter example one line down, rclone at a versioned
    Cellar path AND at a stable one under `.local/bin`.
    """

    def raw_with(self, **placement):
        raw = load_raw("calendar-export")
        raw["placement"].update(placement)
        return raw

    def refusal(self, interpreter):
        found = model.validate(self.raw_with(interpreter=interpreter),
                               source="probe.yaml")
        return " ".join(finding_text(f) for f in found)

    def test_a_version_directory_is_refused_and_the_segment_is_named(self):
        for path, segment in (
            ("/opt/x/.local/share/claude/versions/2.1.201/claude", "2.1.201"),
            ("/opt/homebrew/Cellar/rclone/1.73.5/bin/rclone", "1.73.5"),
            ("/opt/x/Application Support/Claude/claude-code/2.0.65/claude", "2.0.65"),
            ("/opt/homebrew/Cellar/ical-buddy/1.10.1_1/bin/icalBuddy", "1.10.1_1"),
            ("/Library/Frameworks/Python.framework/Versions/3.13/bin/python3", "3.13"),
        ):
            with self.subTest(path=path):
                text = self.refusal(path)
                self.assertIn("interpreter", text,
                              f"{path} carries a version and was accepted")
                self.assertIn(segment, text,
                              "the refusal has to name the segment that will move, "
                              "or the reader cannot act on it")

    def test_a_stable_path_passes(self):
        for path in ("/opt/bridge/bin/uv-calendar",
                     "/usr/bin/python3",
                     "/opt/homebrew/bin/gh",
                     "/opt/bridge/bin/report2"):
            with self.subTest(path=path):
                self.assertEqual(
                    [f for f in model.validate(self.raw_with(interpreter=path),
                                               source="probe.yaml")
                     if "interpreter" in finding_text(f)],
                    [], f"{path} carries no version and must pass")


class AGrantedClientIsNotSharedWithTheWholeMachine(MachineGuard):
    """A privacy grant is given to a PATH, so every program at that path holds it.

    Granting Full Disk Access to `/usr/bin/python3` does not grant it to this
    workload. It grants it to every python script the machine will ever run,
    including the ones an attacker gets to choose. That is the scar the
    calendar exporter already paid for: a shared `uv` would have handed an
    internet reachable agent the same total read the exporter needs.
    """

    def raw_with(self, grants, interpreter="/opt/bridge/bin/uv-calendar"):
        raw = load_raw("calendar-export")
        raw["placement"]["privacy_grants"] = grants
        if interpreter is None:
            raw["placement"].pop("interpreter", None)
        else:
            raw["placement"]["interpreter"] = interpreter
        return raw

    def text_for(self, grants, interpreter="/opt/bridge/bin/uv-calendar"):
        found = model.validate(self.raw_with(grants, interpreter), source="probe.yaml")
        return " ".join(finding_text(f) for f in found)

    def test_a_shared_interpreter_is_refused_for_a_grant_holder(self):
        for shared in ("/usr/bin/python3", "/bin/bash", "/bin/zsh",
                       "/usr/bin/osascript", "/opt/homebrew/bin/python3"):
            with self.subTest(interpreter=shared):
                text = self.text_for(["full-disk-access"], shared)
                self.assertIn("privacy_grants", text,
                              f"{shared} is shared by the whole machine and was "
                              f"accepted as the holder of a grant")

    def test_a_dedicated_path_is_accepted(self):
        self.assertEqual(
            [f for f in model.validate(self.raw_with(["full-disk-access"]),
                                       source="probe.yaml")
             if "privacy_grants" in finding_text(f)],
            [], "a path used by this workload alone is exactly the right holder")

    def test_a_grant_without_an_interpreter_has_no_client_to_hang_on(self):
        text = self.text_for(["full-disk-access"], None)
        self.assertIn("interpreter", text,
                      "a grant is issued to a client path; without one the "
                      "declaration names something that cannot be granted")

    def test_an_unknown_grant_name_is_refused(self):
        text = self.text_for(["full-disk"])
        self.assertIn("privacy_grants", text,
                      "a typo in a grant name would send the human to a pane "
                      "that does not exist")

    def test_no_grant_declared_leaves_the_interpreter_choice_alone(self):
        raw = load_raw("calendar-export")
        raw["placement"]["interpreter"] = "/bin/bash"
        self.assertEqual(
            [f for f in model.validate(raw, source="probe.yaml")
             if "privacy_grants" in finding_text(f)],
            [], "a workload that needs no grant may share an interpreter with "
                "the rest of the machine; that is what interpreters are for")


class BothGatesKnowTheHat(MachineGuard):
    """persona_ref must pass BOTH gates, and be shape-checked by both.

    Two allowlists describe the same contract: the JSON schema, and the
    hand-written gate in model.py that answers the acting layer (provision.plan
    calls model.validate, never the schema, so it holds on a machine without
    check-jsonschema). A field added to one and not the other is a field that
    validates in CI and is refused on the machine, or the reverse. Here it
    failed loudly on the first run, which is the good version of that failure.

    The shape rule is the same one recipients carry, for the same reason: the
    field is a REFERENCE into identity/personas/, and a written-out name would
    carry a person into a file the scope router moves.
    """

    def _decl(self, **extra):
        base = {
            "schema_version": 1, "scope": "user", "id": "hat-test",
            "purpose": "a declaration used to test the persona reference",
            "placement": {"host": "host-a", "kind": "daemon",
                          "runtime": "launchd", "owner": "human"},
        }
        base.update(extra)
        return base

    def _write(self, raw):
        import tempfile, yaml, pathlib
        d = pathlib.Path(tempfile.mkdtemp())
        f = d / "hat-test.yaml"
        f.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
        return f

    def test_the_hand_gate_accepts_a_persona_slug(self):
        w = model.load_declaration(self._write(self._decl(persona_ref="a-persona")))
        self.assertEqual(w.persona_ref, "a-persona")

    def test_the_hand_gate_accepts_the_two_reserved_answers(self):
        for reserved in ("_shared", "_infrastructure"):
            with self.subTest(reserved=reserved):
                w = model.load_declaration(self._write(self._decl(persona_ref=reserved)))
                self.assertEqual(w.persona_ref, reserved)

    def test_absent_is_a_third_state_and_not_an_error(self):
        w = model.load_declaration(self._write(self._decl()))
        self.assertIsNone(w.persona_ref)

    def test_a_written_out_name_is_refused_by_the_shape(self):
        # The shape rule lives in `validate`, the gate provision.plan calls.
        # The loader's own check is the key ALLOWLIST; naming both here is the
        # point of the class, because a field has to pass both.
        found = model.validate(self._decl(persona_ref="Erika Mustermann"),
                               source="hat-test.yaml")
        self.assertTrue([f for f in found if "persona_ref" in str(f)],
                        "a written-out name passed the hand-written gate")

    def test_an_invented_reserved_word_is_refused(self):
        found = model.validate(self._decl(persona_ref="_everything"),
                               source="hat-test.yaml")
        self.assertTrue([f for f in found if "persona_ref" in str(f)],
                        "an underscore word nobody defined was accepted as reserved")

    def test_and_a_good_one_leaves_the_gate_silent(self):
        for ok in ("a-persona", "_shared", "_infrastructure"):
            with self.subTest(value=ok):
                found = model.validate(self._decl(persona_ref=ok),
                                       source="hat-test.yaml")
                self.assertEqual([f for f in found if "persona_ref" in str(f)], [])


class BothGatesKnowTheSystem(MachineGuard):
    """`system` must pass BOTH gates, exactly like the hat above.

    The field answers a different question from `persona_ref` and the two are
    kept apart on purpose. The hat is about whose work a run is, which decides
    billing, a handover, and what happens when a sphere ends. The system is
    about what breaks with it. On the instance this was written for, one hat
    held twenty of thirty-eight runs and four independent systems sat inside it,
    so the hat could not answer the operating question even in principle.

    Membership is CARRIED and never derived. Deriving it from the name was the
    obvious shortcut and it is wrong on the real data: a puller feeding an agent
    shared no prefix with it in two of three cases, and renaming was already
    ruled out because a launchd label is held deliberately.
    """

    def _decl(self, **extra):
        base = {
            "schema_version": 1, "scope": "user", "id": "system-test",
            "purpose": "a declaration used to test the system reference",
            "placement": {"host": "host-a", "kind": "daemon",
                          "runtime": "launchd", "owner": "human"},
        }
        base.update(extra)
        return base

    def _write(self, raw):
        import tempfile, yaml, pathlib
        d = pathlib.Path(tempfile.mkdtemp())
        f = d / "system-test.yaml"
        f.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
        return f

    def test_the_loader_accepts_a_system_slug(self):
        w = model.load_declaration(self._write(self._decl(system="an-agent")))
        self.assertEqual(w.system, "an-agent")

    def test_the_loader_accepts_the_reserved_answer(self):
        w = model.load_declaration(self._write(self._decl(system="_standalone")))
        self.assertEqual(w.system, "_standalone")

    def test_absent_is_a_third_state_and_not_standalone(self):
        # The whole reason `_standalone` exists. Without it a run nobody
        # classified would read exactly like one somebody looked at and found to
        # run alone, and the advice under those two is not the same.
        w = model.load_declaration(self._write(self._decl()))
        self.assertIsNone(w.system)

    def test_a_written_out_name_is_refused_by_the_shape(self):
        found = model.validate(self._decl(system="Knowledge Agent"),
                               source="system-test.yaml")
        self.assertTrue([f for f in found if "system" in str(f)],
                        "a written-out name passed the hand-written gate")

    def test_an_invented_reserved_word_is_refused(self):
        found = model.validate(self._decl(system="_everything"),
                               source="system-test.yaml")
        self.assertTrue([f for f in found if "system" in str(f)],
                        "an underscore word nobody defined was accepted as reserved")

    def test_and_a_good_one_leaves_the_gate_silent(self):
        for ok in ("an-agent", "loop", "_standalone"):
            with self.subTest(value=ok):
                found = model.validate(self._decl(system=ok),
                                       source="system-test.yaml")
                self.assertEqual([f for f in found if "system" in str(f)], [])

    def test_a_system_of_one_is_not_an_error(self):
        # No cross-file read here, deliberately. While the second half of a
        # system is still being built, the first half naming it is correct and
        # a validator that refused it would push the author to lie or to wait.
        found = model.validate(self._decl(system="half-built"),
                               source="system-test.yaml")
        self.assertEqual([f for f in found if "system" in str(f)], [])

class EvidenceNothingWillWrite(MachineGuard):
    """A declaration may not name an evidence its own artifact never produces.

    FOUND BY USING IT, 2026-08-24. The refresher for the workload page was
    declared with `evidence: log-trace` and, deliberately, `notify_on: []`: it
    sits on a laptop, so a push on every failed run would be loudest exactly
    when it means least. Both gates passed it, it was provisioned, it ran, it
    exited zero, and it wrote no trace at all. `reconcile` then called it
    `in_sync`, because a trace that was never written looks the same as one
    nobody has read yet.

    The cause is a coupling: `required_guarantees` derives the trace from
    `notify_on`, so evidence exists only when somebody asked to be TOLD. But
    `evidence` answers what the proof IS and `notify_on` answers who hears
    about it. Two questions, one switch.

    The remedy is NOT to write a trace for every run: model.py argues, and is
    right, that a file nobody reads is cost without a reader. It is to refuse
    the contradiction at the gate, which is exactly where the comment above
    that code already said it belonged and noted it was not caught.
    """

    def raw(self, evidence, notify_on):
        import copy
        base = copy.deepcopy(load_raw("calendar-export"))
        base["response"]["evidence"] = evidence
        base["response"]["notify_on"] = list(notify_on)
        return base

    def reasons(self, evidence, notify_on):
        found = model.validate(self.raw(evidence, notify_on), source="x.yaml")
        return all_findings_text(found)

    def test_a_trace_nobody_will_write_is_refused(self):
        text = self.reasons("log-trace", [])
        self.assertIn("response.evidence", text,
                      "the declaration names a trace as its proof and nothing "
                      "in the rendered artifact writes one; that promise has to "
                      "break here, not silently on the machine")

    def test_the_reason_names_the_other_half(self):
        # A refusal that does not say WHICH field to change sends the reader
        # to the wrong one. The fix is in notify_on or in evidence, so both
        # have to be in the sentence.
        text = self.reasons("log-trace", [])
        self.assertIn("notify_on", text)

    def test_delivery_receipt_is_the_same_promise(self):
        self.assertIn("response.evidence", self.reasons("delivery-receipt", []))

    def test_asking_to_hear_about_missing_makes_it_honest(self):
        self.assertEqual("", self.reasons("log-trace", ["missing"]))

    def test_asking_to_hear_about_failure_makes_it_honest(self):
        self.assertEqual("", self.reasons("log-trace", ["failure"]))

    def test_an_exit_code_promises_nothing_a_trace_would_have_to_carry(self):
        # The honest way out for a run that wants no push: say the service
        # manager's exit code is the proof, because it is.
        self.assertEqual("", self.reasons("exit-code", []))

    def test_timeout_alone_still_does_not_buy_a_trace(self):
        # Guard on the neighbouring decision, which stays: `timeout` is not a
        # question the trace answers, so it must not quietly satisfy this.
        self.assertIn("response.evidence", self.reasons("log-trace", ["timeout"]))


class OneRunMayKeepSeveralAppointments(MachineGuard):
    """The same work answering at two times of day is one declaration.

    THE CASE, 2026-08-24. A customer health report ran twice a day from two
    scheduler tasks. The second was NINE LINES: it exported two environment
    variables and exec'd the first. Two registry entries, two units, two log
    pairs and two places to change, for one analysis.

    What made it two units rather than one is the runtime's own constraint and
    not a preference: a launchd unit has exactly one command and exactly one
    environment, and the two times answered different distribution lists. So
    the declaration stays ONE file, which is what a person maintains, and the
    backend renders one unit per appointment, which is what the machine needs.

    Two rules hold the shape honest. An appointment's NAME is declared, never
    derived from its time: the unit, the stamp and the trace are named after it,
    and a name built from the clock would orphan all three the day somebody
    moves the report ten minutes. And there is ONE spelling per shape: exactly
    one appointment is written `rrule` + `delivery_at`, several are written
    `appointments`, never both, because a file carrying both says two different
    things about when it fires.
    """

    def test_the_declaration_loads_with_both_appointments(self):
        w = model.load_declaration(declaration("twice-daily-report"))
        names = tuple(a.name for a in w.schedule.appointments)
        self.assertEqual(names, ("morning", "midday"),
                         "the appointments did not survive loading, in order")

    def test_each_appointment_carries_its_own_time_and_recurrence(self):
        w = model.load_declaration(declaration("twice-daily-report"))
        morning, midday = w.schedule.appointments
        self.assertEqual((morning.at, midday.at), ("06:30", "12:30"))
        self.assertTrue(morning.rrule and midday.rrule,
                        "a recurrence is written per appointment, never inherited")

    def test_a_single_appointment_declaration_reads_as_one_appointment(self):
        # The shorthand is not a second data model: every declaration ends up
        # with the same internal shape, so no reader has to ask which it was.
        w = model.load_declaration(declaration("daily-health-report"))
        self.assertEqual(len(w.schedule.appointments), 1,
                         "rrule + delivery_at did not normalise to one appointment")
        only = w.schedule.appointments[0]
        self.assertEqual(only.at, w.schedule.delivery_at)
        self.assertEqual(only.rrule, w.schedule.rrule)
        self.assertEqual(only.name, "",
                         "a single appointment has no name, because nothing has "
                         "to be distinguished from anything")

    def test_two_spellings_of_the_same_schedule_are_refused(self):
        raw = load_raw("twice-daily-report")
        raw["schedule"]["rrule"] = "FREQ=DAILY"
        raw["schedule"]["delivery_at"] = "09:00"
        findings = model.validate(raw, source="two-spellings")
        self.assertTrue(
            any("appointments" in finding_text(f) for f in findings),
            "a declaration carrying BOTH spellings was accepted; a backend "
            f"would then pick one silently. findings={[finding_text(f) for f in findings]}")

    def test_an_appointment_without_a_name_is_refused(self):
        raw = load_raw("twice-daily-report")
        del raw["schedule"]["appointments"][1]["name"]
        findings = model.validate(raw, source="unnamed")
        self.assertTrue(any("name" in finding_text(f) for f in findings),
                        "an unnamed appointment was accepted, and the unit it "
                        "renders to would have no name to be found under")

    def test_two_appointments_may_not_share_a_name(self):
        raw = load_raw("twice-daily-report")
        raw["schedule"]["appointments"][1]["name"] = "morning"
        findings = model.validate(raw, source="duplicate-name")
        self.assertTrue(any("morning" in finding_text(f) for f in findings),
                        "two appointments with one name render to ONE unit "
                        "file, so the second silently replaces the first")

    def test_a_recipient_may_belong_to_one_appointment_only(self):
        w = model.load_declaration(declaration("twice-daily-report"))
        limited = [r for r in w.response.recipients if getattr(r, "only_at", ())]
        self.assertEqual(len(limited), 1,
                         "only_at did not survive loading, so the file claims "
                         "everybody gets every appointment")
        self.assertEqual(tuple(limited[0].only_at), ("morning",))

    def test_only_at_naming_an_appointment_that_does_not_exist_is_refused(self):
        raw = load_raw("twice-daily-report")
        raw["response"]["recipients"][1]["only_at"] = ["evening"]
        findings = model.validate(raw, source="unknown-appointment")
        self.assertTrue(any("evening" in finding_text(f) for f in findings),
                        "only_at pointed at an appointment that does not exist "
                        "and was accepted; that recipient would get nothing and "
                        "the file would still read as though they did")

    def test_only_at_without_any_appointments_is_refused(self):
        raw = load_raw("daily-health-report")
        raw.setdefault("response", {}).setdefault("recipients", [])
        raw["response"]["recipients"] = [{"mandant": "team", "only_at": ["morning"]}]
        findings = model.validate(raw, source="only-at-without-appointments")
        self.assertTrue(any("only_at" in finding_text(f) for f in findings),
                        "only_at was accepted on a declaration with a single "
                        "unnamed appointment, where it can never match")

    def test_the_digest_notices_a_changed_appointment(self):
        # Drift detection compares a digest of the declaration. An appointment
        # left out of it means moving a report by six hours reads as no change.
        import yaml
        before = model.load_declaration(declaration("twice-daily-report"))
        raw = load_raw("twice-daily-report")
        raw["schedule"]["appointments"][1]["at"] = "18:30"
        moved = Path(self.tmpdir()) / "moved.yaml"
        moved.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
        after = model.load_declaration(moved)
        self.assertNotEqual(model.declaration_digest(before),
                            model.declaration_digest(after),
                            "the digest is blind to an appointment's time, so "
                            "moving a report by six hours reads as no change")


class AMachineCanBeTheOneItIsAskedAbout(MachineGuard):
    """The named host and the machine running the skill can be the same one.

    Until now `resolve_host` answered `is_local=False` for every named host, so
    a watcher running ON the box it watches would have to reach itself over
    ssh. That host cannot: measured on 2026-08-24 and again on 2026-08-25,
    `Permission denied (publickey,password,keyboard-interactive)`.

    Setting up a key for it would be a new credential for a problem that needs
    none, and it would be the WRONG measurement besides: this skill's own rule
    says an ssh session has its own identity and its own grants, so the honest
    probe is the one that runs where the service manager runs.

    The machine is recognised by a MARKER it carries, never by its name. The
    repository has that scar: `hostname` on one of these machines returns a
    name the router hands out, and the same rule already governs how a served
    directory is proved to be ours.
    """

    def repo(self):
        return make_repo(self.tmpdir())

    def identity(self, name):
        home = self.tmpdir()
        (home / ".bridge").mkdir(parents=True, exist_ok=True)
        (home / ".bridge" / "host-identity").write_text(name + "\n", encoding="utf-8")
        return home

    def test_a_named_host_is_reached_over_ssh_unless_it_says_otherwise(self):
        host = hosts.resolve_host("host-a", self.repo(), home=self.tmpdir())
        self.assertFalse(
            host.is_local,
            "without a marker the answer must not change; guessing this wrong "
            "means running one machine's commands on another")

    def test_a_machine_that_says_it_is_this_host_is_read_locally(self):
        host = hosts.resolve_host("host-a", self.repo(), home=self.identity("host-a"))
        self.assertTrue(host.is_local, "the marker was ignored")
        self.assertEqual(host.slug, "host-a",
                         "it is still that host: only the way there changed")
        self.assertTrue(host.services,
                        "the register entry has to keep answering; a local read "
                        "must not cost the inventory")

    def test_a_marker_naming_another_machine_changes_nothing(self):
        host = hosts.resolve_host("host-a", self.repo(), home=self.identity("host-b"))
        self.assertFalse(
            host.is_local,
            "a marker for a different machine let this one answer in its name, "
            "which is the worst outcome available here")

    def test_a_local_read_says_so_and_is_never_silent(self):
        host = hosts.resolve_host("host-a", self.repo(), home=self.identity("host-a"))
        said = getattr(host, "local_reason", "")
        self.assertTrue(
            said, "a local read has to be visible. It is the one thing here that "
                  "could quietly answer about the wrong machine, and the cheapest "
                  "guard against that is a reader noticing")
        self.assertIn("host-identity", said,
                      "the sentence has to name the file, so the reader can go "
                      "and look at what made this decision")

    def test_an_empty_or_broken_marker_is_not_an_identity(self):
        home = self.tmpdir()
        (home / ".bridge").mkdir(parents=True, exist_ok=True)
        (home / ".bridge" / "host-identity").write_text("   \n", encoding="utf-8")
        self.assertFalse(hosts.resolve_host("host-a", self.repo(), home=home).is_local)


class TransientExitCodes(MachineGuard):
    """response.transient_exit_codes, added 2026-09-26."""

    def test_codes_are_read(self):
        r = model._response({"notify_on": ["failure"], "transient_exit_codes": [75]}, "x.yaml")
        self.assertEqual(r.transient_exit_codes, (75,))

    def test_default_is_empty(self):
        self.assertEqual(model._response({}, "x.yaml").transient_exit_codes, ())

    def test_zero_and_non_numbers_are_refused(self):
        from engine.errors import DeclarationError
        for bad in ([0], ["75"], [256], [True]):
            with self.subTest(bad=bad), self.assertRaises(DeclarationError):
                model._response({"transient_exit_codes": bad}, "x.yaml")
