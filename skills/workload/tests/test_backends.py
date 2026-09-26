"""backends: per backend bytes, step plans and refusal sets.

The step plan assertions are the ones with scars behind them: a replace that
uses kickstart does not reload a changed unit, a disable that is only a bootout
does not survive a reboot, and an uninstall that renames a file loses the why.
"""

from __future__ import annotations

import dataclasses
import plistlib
import shlex
import unittest

from tests.conftest import (
    engine_sources,
    CORPUS,
    DERIVED,
    FIXTURE_HOME,
    FIXTURE_TZ,
    FIXTURE_UID,
    FakeHost,
    MachineGuard,
    SKILL_DIR,
    assert_golden,
    read_output,
    mod,
)

model = mod("engine.model")
errors = mod("engine.errors")
render_mod = mod("engine.render")
base = mod("engine.backends.base")
backends = mod("engine.backends")
launchd = mod("engine.backends.launchd")
systemd = mod("engine.backends.systemd")
cron = mod("engine.backends.cron")
dispatcher = mod("engine.backends.dispatcher")
inert = mod("engine.backends.inert")
wrapper = mod("engine.backends.wrapper")
config = mod("engine.config")

REASON = "superseded by the timer unit"


def as_text(content) -> str:
    return content.decode("utf-8") if isinstance(content, bytes) else content


def joined(steps) -> str:
    return "\n".join(" ".join(str(a) for a in s.argv) for s in steps)


#: The hostile values every backend is measured against. One list, used by the
#: systemd case AND the launchd case, because the point is not that each format
#: survives its own test: it is that the SAME declaration means the same thing
#: on both. A value that only one of them carries is a workload that moves from
#: a Mac to a Linux box and quietly runs with half its configuration.
HOSTILE_ENV = {
    "GREETING": "hallo welt",
    "QUOTED": 'he said "hi" twice',
    "TRAILING_BACKSLASH": "ends with a backslash \\",
    "DOLLAR": "$HOME and ${PATH}",
    "EQUALS": "a=b=c",
    "TABBED": "left\tright",
    "EMPTY": "",
}


def read_systemd_environment(text: str):
    """Read `Environment=` back out of a unit the way systemd reads it.

    Not a substring check. `Environment=` takes a SPACE SEPARATED list of
    assignments (systemd.exec(5)); an assignment may be wrapped in double
    quotes as a whole, which is how a value containing a space is written
    (`Environment="VAR1=word1 word2"`), and inside the quotes a backslash
    escapes the next character.

    Returns (variables, malformed). A token that does not read back as
    `NAME=value` lands in `malformed` rather than being ignored, because that
    is the failure being measured: systemd drops such a token and starts the
    service anyway, so the damage is a service running with a value it was
    never given, and nothing anywhere says so.
    """
    variables: dict = {}
    malformed: list = []
    for line in text.splitlines():
        if not line.startswith("Environment="):
            continue
        rest = line[len("Environment="):]
        for token in _split_systemd_words(rest):
            name, sep, value = token.partition("=")
            if not sep or not model.ENV_NAME_PATTERN.match(name):
                malformed.append(token)
                continue
            variables[name] = value
    return variables, malformed


def _split_systemd_words(rest: str) -> list:
    """One `Environment=` right hand side into its assignments."""
    words: list = []
    index = 0
    while index < len(rest):
        if rest[index].isspace():
            index += 1
            continue
        word = []
        quoted = False
        while index < len(rest):
            char = rest[index]
            if char == "\\" and index + 1 < len(rest):
                word.append(rest[index + 1])
                index += 2
                continue
            if char == '"':
                quoted = not quoted
                index += 1
                continue
            if char.isspace() and not quoted:
                break
            word.append(char)
            index += 1
        words.append("".join(word))
    return words


class BackendBase(MachineGuard):

    def ctx(self, **overrides):
        kwargs = dict(uid=FIXTURE_UID, home=FIXTURE_HOME,
                      stamp_dir=f"{FIXTURE_HOME}/.bridge/workloads",
                      dispatcher_registry=None, host_timezone=FIXTURE_TZ)
        kwargs.update(overrides)
        return base.RenderContext(**kwargs)

    def load(self, name):
        for folder in (CORPUS, DERIVED):
            path = folder / f"{name}.yaml"
            if path.exists():
                return model.load_declaration(path)
        raise AssertionError(name)

    def artifact(self, name, host="host-a", **ctx_overrides):
        return render_mod.render(self.load(name), FakeHost.from_fixture(host),
                                 self.ctx(**ctx_overrides))


class ReplaceIsBootoutThenBootstrap(BackendBase):
    """Every schedule change is bootout then bootstrap. Never kickstart."""

    def test_the_string_kickstart_appears_nowhere_in_a_replace_plan(self):
        a = self.artifact("block-style-report")
        steps = launchd.LAUNCHD_USER.replace_steps(a, FakeHost.from_fixture("host-a"))
        self.assertNotIn("kickstart", joined(steps),
                         "kickstart does not reload a changed unit")

    def test_the_order_is_bootout_then_write_then_bootstrap(self):
        a = self.artifact("block-style-report")
        steps = launchd.LAUNCHD_USER.replace_steps(a, FakeHost.from_fixture("host-a"))
        text = joined(steps).splitlines()
        out = next(i for i, line in enumerate(text) if "bootout" in line)
        strap = next(i for i, line in enumerate(text) if "bootstrap" in line)
        self.assertLess(out, strap)

    def test_bootstrap_targets_the_unit_file_by_path(self):
        a = self.artifact("block-style-report")
        steps = launchd.LAUNCHD_USER.replace_steps(a, FakeHost.from_fixture("host-a"))
        strap = [s for s in steps if "bootstrap" in " ".join(s.argv)][0]
        self.assertIn(".plist", " ".join(strap.argv))
        self.assertIn(f"gui/{FIXTURE_UID}", " ".join(strap.argv))

    def test_install_and_replace_differ_only_by_the_bootout(self):
        a = self.artifact("block-style-report")
        host = FakeHost.from_fixture("host-a")
        install = joined(launchd.LAUNCHD_USER.install_steps(a, host))
        self.assertNotIn("bootout", install)
        self.assertIn("bootstrap", install)


class DisableIsPersistentAndCarriesTheReason(BackendBase):

    def test_disable_is_more_than_a_bootout(self):
        a = self.artifact("block-style-report")
        steps = launchd.LAUNCHD_USER.disable_steps(a, FakeHost.from_fixture("host-a"),
                                                   reason=REASON)
        # The verb as an argv WORD, not as a substring. A plan that renames the
        # unit file to `<name>.disabled` also contains the letters of `disable`,
        # and that is precisely the move this refuses: a rename does not survive
        # a reboot as an off switch, and it loses the why.
        words = {token for step in steps for token in step.argv}
        self.assertIn("disable", words,
                      "only disable survives a reboot, a bootout alone does not")
        self.assertIn("bootout", words, "nothing stops the running copy now")
        text = joined(steps)
        for renamer in ("mv ", ".bak", ".broken", ".disabled", ".old"):
            self.assertNotIn(renamer, text,
                             "a renamed unit file loses the why; disable plus "
                             "reason does not")

    def test_the_reason_is_recorded_somewhere_in_the_plan(self):
        a = self.artifact("block-style-report")
        steps = launchd.LAUNCHD_USER.disable_steps(a, FakeHost.from_fixture("host-a"),
                                                   reason=REASON)
        blob = joined(steps) + " " + " ".join(s.purpose for s in steps)
        self.assertIn(REASON, blob, "a disable without its reason is a rename with extra steps")

    def test_uninstall_never_renames_a_file(self):
        a = self.artifact("block-style-report")
        text = joined(launchd.LAUNCHD_USER.uninstall_steps(a, FakeHost.from_fixture("host-a")))
        for renamer in ("mv ", ".bak", ".broken", ".disabled", ".old"):
            self.assertNotIn(renamer, text,
                             "a renamed unit file loses the why, disable plus reason does not")


class TwoLaunchdDomains(BackendBase):

    def test_both_instances_come_from_one_implementation(self):
        self.assertIs(type(launchd.LAUNCHD_USER), type(launchd.LAUNCHD_SYSTEM))
        self.assertIsNot(launchd.LAUNCHD_USER, launchd.LAUNCHD_SYSTEM)

    def test_the_user_domain_needs_no_elevation(self):
        a = self.artifact("block-style-report")
        steps = launchd.LAUNCHD_USER.install_steps(a, FakeHost.from_fixture("host-a"))
        self.assertFalse(any(s.requires_elevation for s in steps))
        self.assertIn("LaunchAgents", joined(steps))

    def test_the_system_domain_is_elevated_and_never_run_by_the_skill(self):
        a = self.artifact("elevated-daemon")
        steps = launchd.LAUNCHD_SYSTEM.install_steps(a, FakeHost.from_fixture("host-a"))
        self.assertTrue(any(s.requires_elevation for s in steps),
                        "no sudo, ever: the plan is printed for a human")
        self.assertIn("LaunchDaemons", joined(steps))

    def test_the_system_domain_is_not_gui(self):
        a = self.artifact("elevated-daemon")
        steps = launchd.LAUNCHD_SYSTEM.install_steps(a, FakeHost.from_fixture("host-a"))
        self.assertNotIn("gui/", joined(steps))


class AnAdoptedUnitKeepsTheNameTheMachineAlreadyUses(BackendBase):
    """The label prefix is per declaration, so a hand made unit can be adopted.

    WHY A PREFIX AND NOT A FREE LABEL. Everything downstream relies on the
    declaration id being the tail of the label: inventory matching, the
    ownership stamp key, the trace file, the guard script name. A free form
    label breaks that relationship for every one of them at once. A prefix
    keeps it.

    AND IT IS ENOUGH, measured rather than argued: on a live machine carrying
    55 hand made units every single label decomposed into
    <prefix>.<id>[.<appointment>], three-segment prefixes and units whose last
    segment is an appointment name included.

    Without this, `adopt` could only ever take over a unit that already happens
    to carry this instance's own prefix, which is exactly the unit nobody makes
    by hand. Its own docstring promises "a hand made unit becomes owned".
    """

    def test_the_declared_prefix_wins_over_the_instance_default(self):
        w = self.load("adopted-prefix-daemon")
        self.assertEqual(launchd.LAUNCHD_USER.label(w),
                         "org.example.scheduler.legacy-poller")

    def test_the_id_stays_the_tail_of_the_label(self):
        w = self.load("adopted-prefix-daemon")
        self.assertTrue(launchd.LAUNCHD_USER.label(w).endswith("." + w.id))

    def test_a_declaration_without_the_field_is_unchanged(self):
        w = self.load("elevated-daemon")
        self.assertEqual(launchd.LAUNCHD_SYSTEM.label(w), "bridge.elevated-daemon")

    def test_the_unit_file_carries_the_declared_label(self):
        a = self.artifact("adopted-prefix-daemon")
        self.assertIn("org.example.scheduler.legacy-poller", as_text(a.files[0].content))

    def test_the_steps_address_the_declared_label(self):
        a = self.artifact("adopted-prefix-daemon")
        steps = launchd.LAUNCHD_USER.install_steps(a, FakeHost.from_fixture("host-a"))
        self.assertIn("org.example.scheduler.legacy-poller", joined(steps))


class SystemdReadsTheSameFieldTheSameWay(BackendBase):
    """One field, both naming backends, or the seam is a per backend surprise.

    A declaration that carries its own prefix means the same thing everywhere:
    the unit already exists under a hand made name. A backend that quietly
    ignores it would render a name nothing on the machine answers to, and
    `adopt` would then report nothing to adopt for a unit that is right there.
    """

    def test_the_prefix_reaches_the_service_name(self):
        w = self.load("adopted-prefix-daemon")
        self.assertEqual(systemd.SYSTEMD.unit_ref(w),
                         "org.example.scheduler.legacy-poller.service")

    def test_the_id_stays_the_last_part_before_dot_service(self):
        w = self.load("adopted-prefix-daemon")
        self.assertTrue(systemd.SYSTEMD.unit_ref(w).endswith(f".{w.id}.service"))

    def test_without_the_field_the_name_is_unchanged(self):
        # No existing systemd unit may be renamed by this feature.
        w = self.load("elevated-daemon")
        self.assertEqual(systemd.SYSTEMD.unit_ref(w), "elevated-daemon.service")


class LaunchdKinds(BackendBase):

    def test_oneshot_is_refused_and_points_at_the_dispatcher(self):
        w = self.load("contract-review-reminder")
        with self.assertRaises(errors.UnsupportedKind) as ctx:
            launchd.LAUNCHD_USER.render(w, FakeHost.from_fixture("host-a"), self.ctx())
        self.assert_error(ctx, "unsupported-kind", "oneshot", "dispatcher")

    def test_the_golden_plist(self):
        a = self.artifact("block-style-report")
        unit = [f for f in a.files if str(f.path).endswith(".plist")][0]
        assert_golden(self, "launchd-user-recurring.plist", as_text(unit.content))

    def test_the_golden_guard_script(self):
        a = self.artifact("block-style-report")
        guard = [f for f in a.files if not str(f.path).endswith(".plist")][0]
        assert_golden(self, "launchd-user-recurring.guard.sh", as_text(guard.content))

    def test_the_unit_file_is_executable_only_where_it_should_be(self):
        a = self.artifact("block-style-report")
        for f in a.files:
            if str(f.path).endswith(".plist"):
                self.assertEqual(f.mode, 0o644)
            else:
                self.assertEqual(f.mode, 0o755)


class Systemd(BackendBase):

    def host(self):
        return FakeHost.from_fixture("host-b")

    def test_a_recurring_run_produces_a_service_and_a_timer(self):
        a = self.artifact("linux-timer-report", host="host-b")
        names = sorted(str(f.path).rsplit("/", 1)[-1] for f in a.files)
        self.assertTrue(any(n.endswith(".service") for n in names), names)
        self.assertTrue(any(n.endswith(".timer") for n in names), names)

    def test_the_units_land_in_the_user_directory(self):
        a = self.artifact("linux-timer-report", host="host-b")
        for f in a.files:
            self.assertIn(".config/systemd/user", str(f.path))

    def test_oncalendar_carries_the_lead_not_the_delivery_time(self):
        a = self.artifact("linux-timer-report", host="host-b")
        timer = [f for f in a.files if str(f.path).endswith(".timer")][0]
        text = as_text(timer.content)
        self.assertIn("06:10", text)
        self.assertNotIn("06:30", text)

    def test_the_native_guarantees_are_actually_written_into_the_unit(self):
        a = self.artifact("linux-timer-report", host="host-b")
        service = [f for f in a.files if str(f.path).endswith(".service")][0]
        text = as_text(service.content)
        self.assertIn("RuntimeMaxSec", text)
        self.assertIn("KillMode=control-group", text)

    def test_the_marker_sits_in_both_places(self):
        a = self.artifact("linux-timer-report", host="host-b")
        service = as_text([f for f in a.files if str(f.path).endswith(".service")][0].content)
        self.assertIn(f'Environment="{model.MARKER_ENV_ID}=', service)
        self.assertIn("X-BridgeWorkload=", service)

    def test_a_watch_produces_a_path_unit(self):
        w = model.load_declaration(CORPUS / "voicememo-notify.yaml")
        object.__setattr__(w.placement, "runtime", "systemd") if False else None
        # Rendering the watch case goes through the backend directly, so the
        # declaration's own runtime does not have to be edited.
        a = systemd.SYSTEMD.render(w, self.host(), self.ctx())
        self.assertTrue(any(str(f.path).endswith(".path") for f in a.files),
                        [str(f.path) for f in a.files])

    def test_the_golden_service_unit(self):
        a = self.artifact("linux-timer-report", host="host-b")
        service = [f for f in a.files if str(f.path).endswith(".service")][0]
        assert_golden(self, "systemd-recurring.service", as_text(service.content))


class EnvironmentSurvivesTheUnitFile(BackendBase):
    """A declared value arrives on the machine as the value that was declared.

    The scar: `Environment=` was assembled as one line of `k=v` joined by
    spaces, and systemd splits that line ON SPACES. A declared
    `GREETING: "hallo welt"` therefore set GREETING to `hallo` and handed
    `welt` to systemd as an assignment of its own, which it drops. The service
    started with half its configuration, said nothing, and the deviation was
    invisible exactly where reconcile looks: the unit exists, it runs, and it
    carries the right digest.

    Every case here READS THE UNIT BACK with `read_systemd_environment` and
    compares whole values. Asking whether `hallo welt` appears somewhere in the
    text passes under the broken form too, which is how this survived.
    """

    def with_env(self, name, env, host="host-b"):
        w = self.load(name)
        w = dataclasses.replace(
            w, execution=dataclasses.replace(w.execution, env=dict(env)))
        return systemd.SYSTEMD.render(w, FakeHost.from_fixture(host), self.ctx())

    def service_of(self, artifact) -> str:
        return as_text([f for f in artifact.files
                        if str(f.path).endswith(".service")][0].content)

    def test_a_value_with_a_space_arrives_whole(self):
        a = self.with_env("linux-timer-report", {"GREETING": "hallo welt"})
        variables, malformed = read_systemd_environment(self.service_of(a))
        self.assertEqual(malformed, [],
                         "systemd would drop these tokens and start anyway")
        self.assertEqual(variables.get("GREETING"), "hallo welt")

    def test_every_hostile_value_arrives_whole(self):
        a = self.with_env("linux-timer-report", HOSTILE_ENV)
        variables, malformed = read_systemd_environment(self.service_of(a))
        self.assertEqual(malformed, [])
        for name, value in HOSTILE_ENV.items():
            with self.subTest(variable=name):
                self.assertEqual(variables.get(name), value)

    def test_the_unit_carries_the_declared_set_and_the_marker_and_nothing_else(self):
        # Whole-set equality, not "is it in there": a variable that appears
        # twice, or one nobody declared, is as wrong as a truncated value.
        a = self.with_env("linux-timer-report", HOSTILE_ENV)
        variables, _ = read_systemd_environment(self.service_of(a))
        expected = dict(HOSTILE_ENV)
        expected[model.MARKER_ENV_ID] = "linux-timer-report"
        self.assertEqual(set(variables), set(expected) | {model.MARKER_ENV_DIGEST})
        for name, value in expected.items():
            self.assertEqual(variables[name], value)

    def test_one_variable_per_line_so_a_reader_sees_each_one(self):
        a = self.with_env("linux-timer-report", HOSTILE_ENV)
        lines = [line for line in self.service_of(a).splitlines()
                 if line.startswith("Environment=")]
        self.assertEqual(len(lines), len(HOSTILE_ENV) + 2,
                         "one line per variable, plus the two marker variables")

    def test_a_declaration_cannot_rename_the_owner_of_its_own_unit(self):
        # Ownership is read back out of this variable. A declaration that sets
        # it is not configuring a run, it is claiming somebody else's unit.
        a = self.with_env("linux-timer-report",
                          {model.MARKER_ENV_ID: "somebody-elses-workload"})
        variables, _ = read_systemd_environment(self.service_of(a))
        self.assertEqual(variables[model.MARKER_ENV_ID], "linux-timer-report")

    def test_a_line_break_in_a_value_is_refused_by_name(self):
        with self.assertRaises(errors.DeclarationError) as ctx:
            self.with_env("linux-timer-report", {"BROKEN": "one\nRuntimeMaxSec=1"})
        self.assert_error(ctx, "declaration-invalid", "execution.env.BROKEN")

    def test_an_id_carrying_a_path_never_becomes_a_file_path(self):
        # The id is not written INTO the unit here, it decides WHICH FILE the
        # unit is. A slash puts the bytes somewhere nobody declared, so the
        # refusal has to sit in front of the path, not inside the content.
        for hostile in ("../../elsewhere/report", "two words", 'q"uote'):
            with self.subTest(id=hostile):
                w = dataclasses.replace(self.load("linux-timer-report"), id=hostile)
                with self.assertRaises(errors.DeclarationError) as ctx:
                    systemd.SYSTEMD.render(w, FakeHost.from_fixture("host-b"), self.ctx())
                self.assert_error(ctx, "declaration-invalid", hostile)
                with self.assertRaises(errors.DeclarationError) as ctx:
                    launchd.LAUNCHD_USER.render(w, FakeHost.from_fixture("host-a"),
                                                self.ctx())
                self.assert_error(ctx, "declaration-invalid", hostile)

    def test_a_line_break_in_the_title_cannot_add_a_directive(self):
        w = self.load("linux-timer-report")
        w = dataclasses.replace(w, title="report\nExecStartPre=/bin/rm -rf /tmp/x")
        with self.assertRaises(errors.DeclarationError) as ctx:
            systemd.SYSTEMD.render(w, FakeHost.from_fixture("host-b"), self.ctx())
        self.assert_error(ctx, "declaration-invalid", "title")

    def test_a_line_break_in_a_watched_path_cannot_add_a_directive(self):
        w = self.load("voicememo-notify")
        w = dataclasses.replace(
            w, schedule=dataclasses.replace(
                w.schedule, watch_paths=("/tmp/in\nUnit=other.service",)))
        with self.assertRaises(errors.DeclarationError) as ctx:
            systemd.SYSTEMD.render(w, FakeHost.from_fixture("host-b"), self.ctx())
        self.assert_error(ctx, "declaration-invalid", "schedule.watch_paths[0]")


class ALocatorReachesTheUnitAsItStands(BackendBase):
    """`execution.env` carries a reference, and the reference is what arrives.

    The field takes `keychain://…` and its siblings and the schema enforces
    that shape, which reads like a promise that something here fetches the
    secret. Nothing does, and nothing should: resolving would put a live
    credential into a unit file on disk, which is the one place it must never
    be. The program named in `execution.command` resolves its own locator at
    run time.

    That sentence was nowhere. A field with a schema, a validator and an error
    message, and no statement of who acts on it, is read by the next person as
    whichever half they need. So the contract is pinned here, in both backends,
    rather than asserted in prose alone.
    """

    LOCATOR = {"API_TOKEN": "keychain://service/api-token"}

    def rendered(self, backend, host, env):
        w = self.load("linux-timer-report")
        w = dataclasses.replace(
            w, execution=dataclasses.replace(w.execution, env=dict(env)))
        return backend.render(w, FakeHost.from_fixture(host), self.ctx())

    def test_launchd_hands_over_the_locator_and_not_a_secret(self):
        plist = self.rendered(launchd.LAUNCHD_USER, "host-a", self.LOCATOR)
        env = plistlib.loads(plist.files[0].content.encode("utf-8"))["EnvironmentVariables"]
        self.assertEqual(
            env["API_TOKEN"], "keychain://service/api-token",
            "the value changed on its way into the unit. Either a secret was "
            "resolved into a file on disk, or the reference was mangled")

    def test_systemd_hands_over_the_same_locator(self):
        unit = self.rendered(systemd.SYSTEMD, "host-b", self.LOCATOR)
        service = as_text([f for f in unit.files
                           if str(f.path).endswith(".service")][0].content)
        env, malformed = read_systemd_environment(service)
        self.assertEqual(malformed, [])
        self.assertEqual(env["API_TOKEN"], "keychain://service/api-token")

    def test_no_backend_tries_to_resolve_a_locator(self):
        # A resolver would have to know the scheme. None of them may.
        for path in engine_sources():
            text = path.read_text(encoding="utf-8")
            for verb in ("security find-generic-password", "az keyvault secret show",
                         "op read"):
                self.assertNotIn(
                    verb, text,
                    f"{path.name} resolves a locator. The value would then land "
                    f"in a unit file on disk, which is what the reference form "
                    f"exists to prevent")


class TheTwoBackendsReadTheSameDeclarationTheSameWay(BackendBase):
    """The point of E1 stated as one assertion: one declaration, one meaning.

    A quoting bug does not announce itself as a bug. It announces itself as a
    workload that behaves differently after it is moved, with both units
    present, both running, and both carrying the digest of the same file.
    """

    def rendered(self, backend, host, env):
        w = self.load("linux-timer-report")
        w = dataclasses.replace(
            w, execution=dataclasses.replace(w.execution, env=dict(env)))
        return backend.render(w, FakeHost.from_fixture(host), self.ctx())

    def test_both_backends_hand_the_run_the_same_environment(self):
        unit = self.rendered(systemd.SYSTEMD, "host-b", HOSTILE_ENV)
        service = as_text([f for f in unit.files
                           if str(f.path).endswith(".service")][0].content)
        from_systemd, malformed = read_systemd_environment(service)
        self.assertEqual(malformed, [])

        plist = self.rendered(launchd.LAUNCHD_USER, "host-a", HOSTILE_ENV)
        from_launchd = plistlib.loads(
            plist.files[0].content.encode("utf-8"))["EnvironmentVariables"]

        self.assertEqual(from_systemd, from_launchd,
                         "the same declaration means two different things")


class TheLaunchdPlistCarriesValuesUnchanged(BackendBase):
    """launchd's format escapes for us; the cases still measure it.

    A format that happens to be safe today is not a proof, and it is the half
    of the comparison that makes the systemd case readable: these are the same
    values, and this is what arriving intact looks like.
    """

    def with_env(self, env):
        w = self.load("block-style-report")
        w = dataclasses.replace(
            w, execution=dataclasses.replace(w.execution, env=dict(env)))
        return launchd.LAUNCHD_USER.render(w, FakeHost.from_fixture("host-a"), self.ctx())

    def environment_of(self, artifact) -> dict:
        plist = plistlib.loads(artifact.files[0].content.encode("utf-8"))
        return plist["EnvironmentVariables"]

    def test_every_hostile_value_arrives_whole(self):
        variables = self.environment_of(self.with_env(HOSTILE_ENV))
        for name, value in HOSTILE_ENV.items():
            with self.subTest(variable=name):
                self.assertEqual(variables.get(name), value)

    def test_the_plist_is_still_a_plist_after_a_value_with_a_quote_in_it(self):
        # The refusal that matters here is the parser's: a value that broke the
        # XML would be caught by nothing else, because nobody reads a plist by
        # eye before it is written.
        artifact = self.with_env({"QUOTED": '</string><key>Label</key><string>other'})
        plist = plistlib.loads(artifact.files[0].content.encode("utf-8"))
        self.assertEqual(plist["Label"], "bridge.block-style-report")

    def test_a_declaration_cannot_rename_the_owner_of_its_own_unit(self):
        variables = self.environment_of(
            self.with_env({model.MARKER_ENV_ID: "somebody-elses-workload"}))
        self.assertEqual(variables[model.MARKER_ENV_ID], "block-style-report")

    def test_the_guard_script_beside_it_hands_over_the_same_values(self):
        # The guard script is the THIRD place a declared value is written into
        # a generated file, and the only one of the three that is executed as
        # code. Read back with the shell's own splitting rules, not by looking
        # for the value in the text: `GREETING='hallo welt'` and
        # `GREETING=hallo welt` both contain it, and only one of them is right.
        artifact = self.with_env(HOSTILE_ENV)
        guard = [f for f in artifact.files if str(f.path).endswith(".guard.sh")][0]
        assignments = {}
        for line in as_text(guard.content).splitlines():
            if line.startswith(("#", "export ")) or "=" not in line:
                continue
            name = line.partition("=")[0]
            if name not in HOSTILE_ENV:
                continue
            assignments[name] = shlex.split(line)[0].partition("=")[2]
        self.assertEqual(assignments, dict(HOSTILE_ENV))

    def test_a_line_break_in_an_argument_is_refused_here_too(self):
        # A plist would hold it. systemd's ExecStart= would not, and a
        # declaration that means two things on two machines is the failure.
        w = self.load("block-style-report")
        w = dataclasses.replace(w, execution=dataclasses.replace(
            w.execution, command=("/bin/true\nExecStartPre=/bin/false",)))
        with self.assertRaises(errors.DeclarationError) as ctx:
            launchd.LAUNCHD_USER.render(w, FakeHost.from_fixture("host-a"), self.ctx())
        self.assert_error(ctx, "declaration-invalid", "execution.command[0]")

    def test_a_line_break_is_refused_here_too_so_the_declaration_travels(self):
        # A plist could carry it. It is refused anyway: a value only one
        # backend can hold is a declaration that means two things.
        with self.assertRaises(errors.DeclarationError) as ctx:
            self.with_env({"BROKEN": "one\ntwo"})
        self.assert_error(ctx, "declaration-invalid", "execution.env.BROKEN")


class Cron(BackendBase):

    def host(self):
        return FakeHost.from_fixture("host-b")

    def test_a_cadence_becomes_a_crontab_line(self):
        a = self.artifact("cron-cadence", host="host-b")
        text = "".join(as_text(f.content) for f in a.files)
        self.assertIn("*/15 * * * *", text)

    def test_percent_is_escaped(self):
        # An unescaped % ends the command and feeds the rest to stdin.
        a = self.artifact("cron-cadence", host="host-b")
        text = "".join(as_text(f.content) for f in a.files)
        self.assertIn("\\%", text)

    def test_path_is_set_explicitly(self):
        a = self.artifact("cron-cadence", host="host-b")
        text = "".join(as_text(f.content) for f in a.files)
        self.assertIn("PATH=", text, "cron has no login PATH")

    def test_only_the_own_block_is_rewritten(self):
        existing = read_output("crontab-existing.txt")
        merged = cron.merge_block(existing, "*/30 * * * * /bin/true\n", "cron-cadence",
                                 "sha256:4444")
        self.assertIn("/opt/local/bin/rotate-logs.sh", merged,
                      "a hand written crontab line was lost")
        self.assertIn("/opt/local/bin/another-hand-written-one.sh", merged)
        self.assertIn("*/30 * * * * /bin/true", merged)
        self.assertNotIn("*/15 * * * *", merged)

    def test_the_block_is_delimited_by_the_shared_markers(self):
        merged = cron.merge_block("", "*/30 * * * * /bin/true\n", "cron-cadence", "sha256:4444")
        self.assertIn(model.CRON_BEGIN, merged)
        self.assertIn(model.CRON_END, merged)
        self.assertIn("cron-cadence", merged)

    def test_removing_the_block_leaves_the_foreign_lines_alone(self):
        existing = read_output("crontab-existing.txt")
        stripped = cron.merge_block(existing, None, "cron-cadence", None)
        self.assertIn("/opt/local/bin/rotate-logs.sh", stripped)
        self.assertNotIn(model.CRON_BEGIN, stripped)

    def test_cron_refuses_a_daemon(self):
        with self.assertRaises(errors.UnsupportedKind) as ctx:
            cron.CRON.render(self.load("cron-daemon-refused"), self.host(), self.ctx())
        self.assert_error(ctx, "unsupported-kind", "daemon", "cron")

    def test_cron_refuses_a_watch(self):
        with self.assertRaises(errors.UnsupportedKind) as ctx:
            cron.CRON.render(self.load("voicememo-notify"), self.host(), self.ctx())
        self.assert_error(ctx, "unsupported-kind", "watch", "cron")

    def test_cron_promises_nothing_natively(self):
        self.assertEqual(cron.CRON.guarantees, frozenset())

    def test_the_golden_cron_block(self):
        a = self.artifact("cron-cadence", host="host-b")
        block = [f for f in a.files if "cron" in str(f.path)][0]
        assert_golden(self, "cron-cadence.crontab", as_text(block.content))

    def test_an_id_that_would_split_its_own_marker_is_refused(self):
        # The id is this backend's unit NAME: it is written into the BEGIN
        # marker and read back out of it with `split()`, so a space there makes
        # the block unfindable and it can never be replaced or removed again --
        # the crontab keeps a line nobody can reach. The two service-manager
        # backends assert the same thing about their unit names.
        for hostile in ("cron cadence", "../elsewhere/cadence"):
            with self.subTest(id=hostile):
                w = dataclasses.replace(self.load("cron-cadence"), id=hostile)
                with self.assertRaises(errors.DeclarationError) as ctx:
                    cron.CRON.render(w, self.host(), self.ctx())
                self.assert_error(ctx, "declaration-invalid", hostile)

    def test_the_marker_of_a_slug_is_found_again(self):
        # The negative control. A refusal that refused every id would satisfy
        # the case above and leave the backend unable to render at all.
        a = self.artifact("cron-cadence", host="host-b")
        text = "".join(as_text(f.content) for f in a.files)
        head = [line for line in text.splitlines() if line.startswith(model.CRON_BEGIN)]
        self.assertEqual(len(head), 1, text)
        self.assertIn("cron-cadence", head[0].split())


class Dispatcher(BackendBase):

    def test_an_unconfigured_dispatcher_refuses_clearly(self):
        with self.assertRaises(errors.DispatcherNotConfigured) as ctx:
            dispatcher.DISPATCHER.render(self.load("contract-review-reminder"),
                                         FakeHost.from_fixture("host-a"),
                                         self.ctx(dispatcher_registry=None))
        self.assert_error(ctx, "dispatcher-not-configured", "dispatcher_registry")

    def test_a_configured_dispatcher_writes_one_registry_entry(self):
        a = dispatcher.DISPATCHER.render(
            self.load("contract-review-reminder"), FakeHost.from_fixture("host-a"),
            self.ctx(dispatcher_registry=f"{FIXTURE_HOME}/.bridge/dispatcher.yaml"))
        self.assertEqual(len(a.files), 1, "the dispatcher owns one registry, not one file per run")
        self.assertIn("contract-review-reminder", as_text(a.files[0].content))

    def test_the_marker_is_a_field_in_the_registry_entry(self):
        a = dispatcher.DISPATCHER.render(
            self.load("contract-review-reminder"), FakeHost.from_fixture("host-a"),
            self.ctx(dispatcher_registry=f"{FIXTURE_HOME}/.bridge/dispatcher.yaml"))
        self.assertIn(model.MARKER_ENV_ID.lower().replace("_", "-"),
                      as_text(a.files[0].content).lower().replace("_", "-"))

    def test_the_guarantees_are_read_from_config_not_from_the_code(self):
        # Today's dispatcher promises nothing. When it improves, config says so
        # and no source file changes.
        root = self.tmpdir()
        (root / "bridge-config.yaml").write_text(
            "workloads:\n"
            "  dispatcher_registry: /tmp/registry.yaml\n"
            "  dispatcher_guarantees: [deadline, process_group_kill]\n",
            encoding="utf-8")
        cfg = config.load_config(root)
        upgraded = dispatcher.build(cfg)
        g = model.Guarantee
        self.assertEqual(set(upgraded.guarantees), {g.deadline, g.process_group_kill})

    def test_the_default_dispatcher_promises_nothing(self):
        root = self.tmpdir()
        (root / "bridge-config.yaml").write_text("workloads: {}\n", encoding="utf-8")
        cfg = config.load_config(root)
        self.assertEqual(set(dispatcher.build(cfg).guarantees), set())


class Inert(BackendBase):

    def test_manual_and_external_refuse_to_render(self):
        for name, wid in (("manual", "chat-channel"), ("external", "public-funnel")):
            with self.subTest(runtime=name):
                backend = backends.get_backend(name)
                with self.assertRaises(errors.NotProvisionable) as ctx:
                    backend.render(self.load(wid), FakeHost.from_fixture("host-a"), self.ctx())
                self.assert_error(ctx, "not-provisionable", wid)

    def test_they_still_answer_a_probe_and_a_discovery(self):
        for name in ("manual", "external"):
            with self.subTest(runtime=name):
                backend = backends.get_backend(name)
                steps = backend.discover_steps(FakeHost.from_fixture("host-a"))
                self.assertIsInstance(steps, tuple)

    def test_they_install_nothing(self):
        # The name is about STEPS. This used to read `guarantees`, which is a
        # different property entirely: an inert backend whose `install_steps`
        # returned real launchd calls passed the test named after exactly the
        # thing it was doing. Every family that can change a machine is asked
        # here, and it is handed a real artifact so an implementation cannot pass
        # by refusing to look at its arguments.
        host = FakeHost.from_fixture("host-a")
        artifact = self.artifact("block-style-report")
        families = (
            ("install_steps", lambda b: b.install_steps(artifact, host)),
            ("replace_steps", lambda b: b.replace_steps(artifact, host)),
            ("uninstall_steps", lambda b: b.uninstall_steps(artifact, host)),
            ("disable_steps", lambda b: b.disable_steps(artifact, host, REASON)),
        )
        for name in ("manual", "external"):
            backend = backends.get_backend(name)
            for family, call in families:
                with self.subTest(runtime=name, family=family):
                    steps = tuple(call(backend))
                    self.assertEqual(
                        steps, (),
                        f"{name}.{family} wants to run "
                        f"{joined(steps)!r} on a machine this backend may never "
                        f"touch")
            with self.subTest(runtime=name, family="provisionable"):
                self.assertFalse(backend.provisionable,
                                 f"{name} declares itself provisionable, so the "
                                 f"planner would offer to create it")
            with self.subTest(runtime=name, family="guarantees"):
                self.assertEqual(backend.guarantees, frozenset())


class TheGuardScript(BackendBase):

    def script(self, name="block-style-report"):
        a = self.artifact(name)
        return as_text([f for f in a.files if not str(f.path).endswith(".plist")][0].content)

    def test_it_is_posix_sh_without_bashisms(self):
        text = self.script()
        self.assertTrue(text.startswith("#!/bin/sh"), text.splitlines()[:1])
        for bashism in ("[[", "function ", "local ", "declare ", "$'"):
            self.assertNotIn(bashism, text, f"/bin/sh on macOS is not bash, found {bashism!r}")

    def test_it_does_not_reach_for_timeout(self):
        # timeout(1) is absent on a stock macOS.
        self.assertNotIn("timeout ", self.script())

    def test_it_kills_its_own_process_group(self):
        text = self.script()
        self.assertIn("TERM", text)
        self.assertIn("KILL", text)
        self.assertIn("-$", text.replace("- $", "-$"))

    def test_the_run_is_put_into_its_own_session_deterministically(self):
        # `set -m` is a fallback, never the plan.
        # dash refuses job control without a controlling terminal, and that is
        # exactly how cron starts things; on Debian /bin/sh IS dash and cron is
        # the backend that is always wrapped. Measured there, the run and the
        # guard shared one group, the watchdog took the branch that ends only
        # the direct child, the grandchild kept the output pipe and the caller
        # blocked past every deadline. `setsid` removes the guesswork where it
        # matters.
        text = self.script()
        # The REACH, not the word: a script that mentions setsid inside a branch
        # it never enters is exactly as broken as one that never mentions it.
        self.assertIn("command -v setsid", text,
                      "the run relies on the shell arranging a group for it, which "
                      "dash does not do without a terminal")
        self.assertIn("setsid ", text, "nothing is actually started through setsid")
        self.assertLess(text.index("command -v setsid"), text.index("set -m"),
                        "the fallback is reached for first, so the deterministic "
                        "route never runs where it is needed")

    def test_the_fallback_still_exists_for_machines_without_setsid(self):
        # A stock macOS ships no setsid, so removing the shell route would leave
        # the platform this skill is actually tested on with nothing.
        self.assertIn("set -m", self.script())

    def test_single_flight_is_an_atomic_mkdir_with_a_liveness_check(self):
        text = self.script()
        self.assertIn("mkdir", text)
        self.assertIn("kill -0", text)

    def test_the_trace_line_carries_what_the_evidence_field_promises(self):
        text = self.script()
        for field in ("rc", "duration_sec", "verdict"):
            self.assertIn(field, text)

    def test_exit_code_evidence_writes_no_trace(self):
        text = self.script("process-isolation-report")
        self.assertNotIn("verdict", text,
                         "evidence: exit-code claims nothing, so it must write no trace line")

    def test_the_wrapper_sets_an_explicit_path(self):
        self.assertIn("PATH=", self.script())

    def test_the_marker_is_exported_for_the_wrapped_run(self):
        self.assertIn(model.MARKER_ENV_ID, self.script())


class TheGuardScriptIsTheOnePlaceAValueIsExecuted(BackendBase):
    """Two holes in the guard script that the unit-file rounds did not reach.

    The two service-manager backends write a declared value into a file. The
    guard script writes it into a file that is then RUN as shell, and two
    strings reached it unquoted:

      * `w.id` -- quoted in the ownership assignment, and interpolated raw
        inside double quotes in four state-file paths, where a `"` ends the
        string and everything after it is the next command;
      * every environment KEY -- written bare on the left of an assignment AND
        again after `export`, so a key carrying `;` runs its command twice.

    Both were measured, not suspected. `id='rep"; touch <file>; #'` produced
    `TRACE_FILE="$STATE_DIR/rep"; touch <file>; #.trace"`, and the env key
    `'OK; touch <file>; X'` produced that command on two separate lines.

    Neither is fixed by quoting at the point of writing: the id decides FILE
    NAMES as well, and a shell has no escape for a name on the left of an
    assignment. So both are refused before a byte is rendered, which is the same
    answer the unit-file backends give.
    """

    def script_of(self, artifact) -> str:
        return as_text([f for f in artifact.files
                        if str(f.path).endswith(".guard.sh")][0].content)

    def rendered(self, w):
        return launchd.LAUNCHD_USER.render(w, FakeHost.from_fixture("host-a"), self.ctx())

    def test_an_id_that_closes_the_quote_is_refused_before_a_byte_is_written(self):
        for hostile in ('rep"; echo owned; #', "../../elsewhere/report", "two words"):
            with self.subTest(id=hostile):
                w = dataclasses.replace(self.load("block-style-report"), id=hostile)
                with self.assertRaises(errors.DeclarationError) as ctx:
                    self.rendered(w)
                self.assert_error(ctx, "declaration-invalid", hostile)

    def test_an_environment_key_that_is_a_command_is_refused(self):
        # It appeared TWICE in the script, once as an assignment and once after
        # `export`, so the command ran twice.
        w = self.load("block-style-report")
        w = dataclasses.replace(w, execution=dataclasses.replace(
            w.execution, env={"OK; echo owned; X": "1"}))
        with self.assertRaises(errors.DeclarationError) as ctx:
            self.rendered(w)
        self.assert_error(ctx, "declaration-invalid", "execution.env")

    def test_a_plain_id_and_a_plain_key_still_render(self):
        # The negative control. A refusal that refused everything would satisfy
        # both cases above and leave the skill unable to render anything.
        w = self.load("block-style-report")
        w = dataclasses.replace(w, execution=dataclasses.replace(
            w.execution, env={"TOKEN": "keychain://token"}))
        text = self.script_of(self.rendered(w))
        self.assertIn("TOKEN=keychain://token", text)
        self.assertIn("block-style-report", text)

    def test_the_path_the_wrapper_writes_to_is_refused_on_its_own(self):
        # `guard_path` is public and is asked where the file goes; the id decides
        # the FILE and not merely its text, so the refusal has to live in it and
        # not only in the backend that usually calls it first.
        for hostile in ("../../elsewhere/report", 'rep"; echo owned; #'):
            with self.subTest(id=hostile):
                w = dataclasses.replace(self.load("block-style-report"), id=hostile)
                with self.assertRaises(errors.DeclarationError) as ctx:
                    wrapper.guard_path(w, self.ctx())
                self.assert_error(ctx, "declaration-invalid", hostile)

    def test_the_wrapper_refuses_a_hostile_id_on_its_own(self):
        # The path helper above refuses first, so it is STUBBED OUT here. That is
        # the whole point of the case: `wrap` interpolates the id raw inside
        # double quotes in four state-file paths further down, in the one
        # generated file that is executed rather than read, and that refusal may
        # not hang on a sibling function somebody may change tomorrow.
        import importlib
        from unittest import mock

        real = importlib.import_module("engine.backends.wrapper")
        hostile = 'rep"; echo owned; #'
        w = dataclasses.replace(self.load("block-style-report"), id=hostile)
        with mock.patch.object(real, "guard_path",
                               lambda *a, **kw: f"{FIXTURE_HOME}/.bridge/workloads/x.guard.sh"):
            with self.assertRaises(errors.DeclarationError) as ctx:
                real.wrap(w, self.ctx(), base.command_of(w),
                          supplied=real.SUPPLIABLE, digest="sha256:" + "0" * 64)
        self.assert_error(ctx, "declaration-invalid", hostile)

    def test_the_wrapper_still_renders_when_the_path_helper_is_stubbed(self):
        # The negative control of the case above: with the same stub in place a
        # plain declaration still produces a script, so the red there comes from
        # the id and not from the stub.
        import importlib
        from unittest import mock

        real = importlib.import_module("engine.backends.wrapper")
        w = self.load("block-style-report")
        with mock.patch.object(real, "guard_path",
                               lambda *a, **kw: f"{FIXTURE_HOME}/.bridge/workloads/x.guard.sh"):
            rendered = real.wrap(w, self.ctx(), base.command_of(w),
                                 supplied=real.SUPPLIABLE, digest="sha256:" + "0" * 64)
        self.assertIn("block-style-report", as_text(rendered.content))

    def test_every_state_file_path_in_the_script_is_the_slug_and_nothing_else(self):
        # The four paths that carried the raw id. Read as whole lines: asking
        # whether the slug appears somewhere passes under the broken form too.
        import re

        text = self.script_of(self.artifact("block-style-report"))
        paths = re.findall(r'"\$STATE_DIR/([^"]*)"', text)
        self.assertTrue(paths, "no state file path in the guard script to check")
        for found in paths:
            with self.subTest(path=found):
                self.assertRegex(found, r"^block-style-report\.[a-z]+$")


class AddingAFifthBackend(BackendBase):
    """One file plus one registry line, and render.py does not change."""

    def test_a_stub_backend_flows_through_render_unchanged(self):
        g = model.Guarantee

        class StubBackend:
            name = "stub"
            platforms = frozenset({"macos", "linux"})
            kinds = frozenset({"interval"})
            guarantees = frozenset({g.deadline, g.process_group_kill,
                                    g.single_flight, g.missing_detection})

            def render(self, w, h, ctx):
                return base.Artifact(
                    runtime="stub", unit_ref="stub/" + w.id,
                    files=(base.RenderedFile(path="/tmp/stub.conf", mode=0o644,
                                             content="stub\n"),),
                    digest="sha256:" + "0" * 64,
                    guarantees_native=self.guarantees,
                    guarantees_wrapped=frozenset(), notes="")

            def install_steps(self, a, h, **kw):
                return ()

            def replace_steps(self, a, h, **kw):
                return ()

            def disable_steps(self, a, h, **kw):
                return ()

            def uninstall_steps(self, a, h, **kw):
                return ()

            def default_probe(self, a, h):
                return model.Step(argv=("/bin/true",), purpose="stub probe")

            def discover_steps(self, h):
                return ()

            def parse_discovery(self, outs):
                return []

        original = dict(backends.BACKENDS)
        backends.BACKENDS["stub"] = StubBackend()
        self.addCleanup(lambda: (backends.BACKENDS.clear(), backends.BACKENDS.update(original)))

        w = self.load("calendar-export")
        object.__setattr__(w.placement, "runtime", "stub")
        artifact = render_mod.render(w, FakeHost.from_fixture("host-a"), self.ctx())
        self.assertEqual(artifact.runtime, "stub")
        self.assertEqual(set(artifact.guarantees_wrapped), set(),
                         "a backend that promises everything needs no wrapper")


class NoInstanceNamesInAnyBackend(MachineGuard):

    def test_the_backends_carry_no_instance_literal(self):
        from tests.conftest import forbidden_literals

        found = sorted((SKILL_DIR / "engine" / "backends").glob("*.py"))
        self.assertTrue(found, "no backends to scan, so this check proves nothing")
        for path in found:
            text = path.read_text(encoding="utf-8")
            for literal in forbidden_literals():
                with self.subTest(file=path.name, literal=literal):
                    self.assertNotIn(literal, text)


if __name__ == "__main__":
    unittest.main()


class TwoDomainsAreTwoQuestions(BackendBase):
    """The system domain is not the calling session, and asking one about the other
    invents units that do not exist while hiding the ones that do.

    Measured on a live machine 2026-08-23: both launchd backends ran
    `launchctl list`, which enumerates the CALLING SESSION. The system instance
    then stamped `system/` onto every user agent it found. The report carried
    579 units in `gui/501` and the same 579 under `system`, so every user agent
    was also claimed to be a root daemon, and two real root daemons
    (an ssh watchdog and an emergency ssh on a second port) were invisible.
    Their inventory entries were therefore reported as stale with the sentence
    'neither a declaration nor the machine knows it' and the repair hint
    'drop the entry', which would have deleted the record of the only backup
    way into that machine.
    """

    def _pair(self):
        user, system = launchd.build(config.Config())
        return user, system

    def test_the_two_domains_do_not_ask_the_same_question(self):
        user, system = self._pair()
        host = FakeHost.from_fixture("host-a")
        self.assertNotEqual(
            joined(user.discover_steps(host)),
            joined(system.discover_steps(host)),
            "both launchd domains enumerated with the same command, so one of "
            "them answered about the other's units")

    def test_the_system_domain_reads_the_system_domain(self):
        _, system = self._pair()
        text = joined(system.discover_steps(FakeHost.from_fixture("host-a")))
        self.assertIn("launchctl print system", text)
        self.assertNotIn("launchctl list", text)

    def test_a_session_listing_never_becomes_a_root_daemon(self):
        """The exact shape of the bug: feed the system backend what the user
        session prints, and it must not report `system/<label>` for it."""
        _, system = self._pair()
        session = "uid=501\nPID\tStatus\tLabel\n1234\t0\tcom.example.user-agent\n"
        units = system.parse_discovery((session,))
        self.assertEqual(
            [u.unit_ref for u in units], [],
            "a `launchctl list` listing was read as system-domain units")

    def test_the_system_block_is_read_and_bounded(self):
        _, system = self._pair()
        printed = (
            "system = {\n"
            "\ttype = system\n"
            "\tservices = {\n"
            "\t\t     892      - \tcom.example.emergency\n"
            "\t\t       0      0 \tcom.example.watchdog\n"
            "\t\t       0   (pe) \tcom.example.parked\n"
            "\t}\n"
            "\tendpoints = {\n"
            "\t\t       0      - \tcom.example.not-a-service\n"
            "\t}\n"
            "}\n"
        )
        units = system.parse_discovery((printed,))
        self.assertEqual(
            [u.unit_ref for u in units],
            ["system/com.example.emergency",
             "system/com.example.watchdog",
             "system/com.example.parked"],
            "the services block was not read, or a neighbouring block leaked in")
        running = {u.unit_ref: u.running for u in units}
        self.assertTrue(running["system/com.example.emergency"])
        self.assertFalse(running["system/com.example.watchdog"])

class WhatARunSaidIsKept(BackendBase):
    """A run's output goes somewhere bounded, or the run cannot be diagnosed.

    FOUND BY MIGRATING, 2026-08-24. The old unit for the daily health report
    named StandardOutPath and StandardErrorPath; the rendered one names
    neither, so under launchd the run's output goes to /dev/null. That report
    prints `WARN: email_ops fehlgeschlagen` and then exits ZERO, because it
    deliberately does not retry. The warning was the only signal that the mail
    never left, and the migration threw it away.

    Why not simply add StandardOutPath: launchd appends to it and never
    rotates. This project exists partly because 1428 unrotated log files were
    found on one machine. An unbounded file is a different defect, not a fix.

    So the guard redirects instead, into a file it TRUNCATES at the start of
    every run and caps afterwards. One run's worth, bounded twice, at a path
    derived from the id like the trace and the stamp beside it.

    What these tests prove: the redirect exists, it truncates rather than
    appends, and the file is capped. What they do NOT prove: that anybody
    reads it. That is what the `reconcile` hint is for.
    """

    def script(self, name="block-style-report"):
        a = self.artifact(name)
        return as_text([f for f in a.files
                        if not str(f.path).endswith(".plist")][0].content)

    def test_a_plain_run_has_its_output_captured(self):
        text = self.script()
        self.assertIn("OUT_FILE=", text,
                      "the run's output is not redirected anywhere, so under a "
                      "service manager it goes to /dev/null and a warning on a "
                      "zero exit is lost")

    def test_the_capture_truncates_and_never_appends(self):
        text = self.script()
        self.assertNotIn('>> "$OUT_FILE"', text,
                         "appending is how a log file grows until somebody "
                         "notices it in a disk report years later")
        self.assertIn('> "$OUT_FILE" 2>&1', text,
                      "stderr has to go in with it: the warning this exists "
                      "for is printed there")

    def test_one_chatty_run_cannot_fill_the_disk(self):
        # Truncating per run bounds the file across runs, not within one. A
        # single verbose run is still unbounded without this.
        text = self.script()
        self.assertIn("tail -c", text,
                      "a single run with verbose output is still unbounded; "
                      "the file needs a ceiling after the run as well")

    def test_the_path_sits_beside_the_trace_and_the_stamp(self):
        text = self.script()
        self.assertRegex(text, r'OUT_FILE="\$STATE_DIR/[^"]+\.out"',
                         "a path outside the state directory is one more place "
                         "nobody thinks to look")

    def test_a_delivery_receipt_still_owns_the_redirect(self):
        # Where the evidence IS the output, the receipt file is that capture,
        # and a second copy beside it would be two files claiming one truth.
        from engine.backends import wrapper as wrap
        src = io_read()
        self.assertIn('redirect = \' > "$RECEIPT_FILE" 2>&1\'', src,
                      "the receipt is no longer the redirect target where it "
                      "is the declared evidence")
        self.assertIn("elif command_present:", src,
                      "the plain capture must be the OTHER branch, not an "
                      "extra file written alongside the receipt")


class AKindWithoutADeadlineIsKeptToo(BackendBase):
    """The same defect as the class above, in the branch it never reached.

    FOUND BY MIGRATING AGAIN, 2026-08-30, and that is the point of writing it
    down here rather than as a footnote: the 2026-08-24 fix covered the path
    that has a deadline, because everything that had migrated by then had one.
    The first daemon moved on 2026-08-26 and nobody looked, because its wrapper
    happened to redirect its own output. Two more followed with the same luck.

    The fourth did not. It runs `python3 -m http.server`, which prints every
    request it serves to stderr. Its old unit named
    StandardErrorPath and that WAS its access log; the rendered unit names
    none, so from the moment it moved the log was dead. Measured, not inferred:
    the last line in that file carries the minute of the cutover, and a request
    ten minutes later left no byte anywhere.

    A daemon has no deadline by contract, so `redirect` was computed inside the
    `if deadline:` arm and the other arm ran the command bare. `OUT_FILE` was
    still defined for it and still capped afterwards, so the guard prepared a
    file, trimmed it, and never wrote a word into it.

    WHAT THIS COSTS, said plainly, because truncate-per-run is not free for a
    kind that does not end: a daemon that runs for a month writes into one file
    for a month, and the cap only bites when it finally exits. That is the same
    unbounded shape the class above refuses for StandardOutPath. It is accepted
    here because the alternative on the table is not a bounded file, it is no
    file: today the output is discarded entirely. Bounded across restarts beats
    lost always, and a rotation that a foreground guard cannot perform while it
    is blocked in `wait` is a separate piece of work.
    """

    def script(self, name="watched-daemon"):
        a = self.artifact(name)
        return as_text([f for f in a.files
                        if not str(f.path).endswith(".plist")][0].content)

    def test_a_daemon_writes_a_started_line_before_it_runs(self):
        # A daemon writes its trace only when it ends. One that crashed in a
        # loop and then ran cleanly for weeks kept "the last run failed" as its
        # newest line, and reconcile reported a healthy service as broken for
        # twelve days. The start line is what makes "it is running now" the
        # newest thing the trace says.
        text = self.script()
        self.assertIn("trace 0 0 started", text)
        self.assertLess(text.index("trace 0 0 started"), text.index('> "$OUT_FILE" 2>&1'),
                        "the start line has to come before the run, not after it")

    def test_a_run_that_ends_writes_no_started_line(self):
        # A cadence run ends every time and its end line already says how it
        # went; a start line there would only double every entry.
        a = self.artifact("block-style-report")
        text = as_text([f for f in a.files if not str(f.path).endswith(".plist")][0].content)
        self.assertNotIn("trace 0 0 started", text)

    def test_a_daemon_redirects_into_the_file_the_guard_prepared_for_it(self):
        text = self.script()
        self.assertIn('> "$OUT_FILE" 2>&1', text,
                      "a daemon's output goes nowhere: the guard defines "
                      "OUT_FILE and caps it, but never redirects into it, so "
                      "everything the run prints is discarded")

    def test_the_daemon_does_not_prepare_a_file_it_never_writes(self):
        # The two halves must agree. Either the file is written and capped, or
        # neither: a cap on a file nobody fills is dead code that reads like a
        # working capture, which is how this went unnoticed for four days.
        text = self.script()
        if "OUT_FILE=" in text:
            self.assertIn('> "$OUT_FILE" 2>&1', text,
                          "OUT_FILE is defined and capped but never written")

    def test_the_redirect_is_decided_once_for_both_arms(self):
        # The defect was structural, not a typo: the value lived inside one
        # arm of `if deadline:`, so the other arm could not use it however
        # correct it was. Holding the decision above the branch is what stops
        # the next kind without a deadline from inheriting the same silence.
        src = io_read()
        head, _, tail = src.partition("    if deadline:\n        # stderr goes")
        self.assertIn("redirect = ", head,
                      "the redirect is still computed inside the deadline arm, "
                      "so any kind without a deadline runs bare no matter what "
                      "the value says")


def io_read():
    from pathlib import Path
    here = Path(__file__).resolve().parent.parent
    return (here / "engine" / "backends" / "wrapper.py").read_text(encoding="utf-8")


class SeveralAppointmentsBecomeSeveralUnits(BackendBase):
    """One declaration, one unit per appointment, and each keeps its own history.

    A launchd unit has exactly ONE command and exactly ONE environment. So two
    appointments that answer different distribution lists cannot share a unit,
    however much they share an analysis. That is the runtime's constraint, not
    a preference, and the honest place to meet it is here: the declaration
    stays one file, which is what a person maintains, and the backend renders
    the units, which are artifacts rebuilt from it at any time.

    The naming is `<label>.<appointment>`, from the DECLARED appointment name.
    Nothing derives it from the time: the unit, its ownership stamp and its
    trace are all named after it, and a name built from the clock would orphan
    all three the day somebody moves the run ten minutes.

    Each unit keeps its OWN trace, because "did the midday run happen" and
    "did the morning run happen" are two questions and one shared history
    cannot answer both. That is what makes `missing` detection work per
    appointment instead of accepting one run as proof of two.
    """

    def artifacts(self, spec="twice-daily-report"):
        return render_mod.render_all(self.load(spec),
                                     FakeHost.from_fixture("host-a"), self.ctx())

    def test_one_declaration_renders_one_unit_per_appointment(self):
        made = self.artifacts()
        self.assertEqual(len(made), 2,
                         "two appointments did not become two units, so one of "
                         "them never fires")

    def test_each_unit_is_named_after_its_declared_appointment(self):
        labels = sorted(a.unit_ref.rsplit("/", 1)[-1] for a in self.artifacts())
        self.assertEqual(
            labels,
            ["bridge.twice-daily-report.midday", "bridge.twice-daily-report.morning"],
            "the units are not named after their appointments, so nobody can "
            "tell on the machine which time a unit answers")

    def test_a_single_appointment_declaration_still_renders_exactly_one_unit(self):
        # The whole point of normalising the shorthand: nothing about an
        # existing declaration may change because this feature exists.
        made = self.artifacts("block-style-report")
        self.assertEqual(len(made), 1)
        self.assertTrue(made[0].unit_ref.endswith("bridge.block-style-report"),
                        f"a single appointment grew a suffix: {made[0].unit_ref}")

    def test_each_unit_fires_only_at_its_own_appointment(self):
        import plistlib
        times = {}
        for art in self.artifacts():
            unit = [f for f in art.files if str(f.path).endswith(".plist")][0]
            body = unit.content if isinstance(unit.content, bytes) else unit.content.encode()
            data = plistlib.loads(body)
            name = art.unit_ref.rsplit(".", 1)[-1]
            times[name] = sorted({(e["Hour"], e["Minute"])
                                  for e in data["StartCalendarInterval"]})
        self.assertEqual(times.get("morning"), [(6, 30)])
        self.assertEqual(times.get("midday"), [(12, 30)])

    def test_each_unit_carries_its_appointments_own_weekdays(self):
        import plistlib
        for art in self.artifacts():
            unit = [f for f in art.files if str(f.path).endswith(".plist")][0]
            body = unit.content if isinstance(unit.content, bytes) else unit.content.encode()
            data = plistlib.loads(body)
            days = sorted({e["Weekday"] for e in data["StartCalendarInterval"]})
            self.assertEqual(days, [1, 2, 3, 4, 5, 6],
                             f"{art.unit_ref} does not carry its own day set")

    def test_the_two_units_keep_separate_traces(self):
        traces = set()
        for art in self.artifacts():
            guard = [f for f in art.files if str(f.path).endswith(".sh")]
            if not guard:
                continue
            text = guard[0].content
            text = text.decode() if isinstance(text, bytes) else text
            for line in text.splitlines():
                if line.strip().startswith("TRACE_FILE="):
                    traces.add(line.strip())
        self.assertEqual(len(traces), 2,
                         "both units write the same trace file, so one run "
                         f"would be read as proof that both happened: {traces}")

    def test_a_trace_line_names_the_unit_and_not_only_the_declaration(self):
        """A line has to still say which run it is about outside its filename.

        The FILE already carries the appointment; the LINE inside it named only
        the declaration, so both units wrote sentences that read identically.
        A filename is context, and context is the first thing lost when
        somebody copies a line into a ticket, greps across both files, or
        merges them into one timeline. Two derivations of one name that
        disagree is the shape this skill has already lost runs to twice.
        """
        said = set()
        for art in self.artifacts():
            guard = [f for f in art.files if str(f.path).endswith(".sh")]
            if not guard:
                continue
            text = guard[0].content
            text = text.decode() if isinstance(text, bytes) else text
            for line in text.splitlines():
                if "BRIDGE_WORKLOAD_TRACE_ID=" in line:
                    said.add(line.strip())
        self.assertEqual(
            len(said), 2,
            f"both units write the same name into their trace lines, so a line "
            f"lifted out of its file cannot say which of two times it is about: "
            f"{said}")

    def test_the_two_units_carry_the_same_declaration_digest(self):
        # They come from ONE declaration. A digest per unit would make a
        # single edit look like two unrelated changes.
        digests = {a for art in self.artifacts()
                   for f in art.files
                   for a in [str(f.content)]
                   if "BRIDGE_WORKLOAD_DIGEST" in str(f.content)}
        joined = " ".join(digests)
        found = {tok for tok in joined.replace('"', " ").replace("<", " ").replace(">", " ").split()
                 if tok.startswith("sha256:")}
        self.assertEqual(len(found), 1,
                         f"the two units disagree about the declaration they came from: {found}")

    def test_asking_for_one_unit_where_there_are_two_refuses_instead_of_guessing(self):
        # `render` answers with THE unit. Where a declaration has several, an
        # answer of "the first one" would be a guess that reads as a fact.
        w = self.load("twice-daily-report")
        with self.assertRaises(Exception) as caught:
            render_mod.render(w, FakeHost.from_fixture("host-a"), self.ctx())
        self.assertIn("appointment", str(caught.exception).lower(),
                      f"the refusal does not say why: {caught.exception}")


class TheRunIsToldWhichAppointmentFired(BackendBase):
    """A command that answers two lists has to learn which one it is answering.

    Two appointments of one run render two units, and a launchd unit has one
    command and one environment. So the difference between them cannot live in
    the argv, which is shared, and it must not live in a second copy of the
    script either: that is exactly the nine-line wrapper this whole change came
    from, kept alive under a new name.

    The guard names the appointment in the environment. Not the clock: a run
    delayed past its hour would then answer the wrong distribution list, and a
    machine that was asleep does exactly that. The unit KNOWS which appointment
    it is, because it was rendered for one, so the fact is passed rather than
    worked out.

    A single-appointment run exports nothing new. Its command has never seen
    this variable and must not start seeing an empty one, which reads as an
    appointment named "" rather than as no appointments at all.
    """

    APPOINTMENT_ENV = "BRIDGE_WORKLOAD_APPOINTMENT"

    def guards(self, spec="twice-daily-report"):
        out = {}
        for art in render_mod.render_all(self.load(spec),
                                         FakeHost.from_fixture("host-a"), self.ctx()):
            guard = [f for f in art.files if str(f.path).endswith(".guard.sh")]
            if guard:
                text = guard[0].content
                out[art.unit_ref] = text.decode() if isinstance(text, bytes) else text
        return out

    def test_each_guard_names_its_own_appointment(self):
        named = {}
        for ref, text in self.guards().items():
            for line in text.splitlines():
                if line.startswith(f"{self.APPOINTMENT_ENV}="):
                    named[ref.rsplit(".", 1)[-1]] = line.split("=", 1)[1].strip().strip("'\"")
        self.assertEqual(named, {"morning": "morning", "midday": "midday"},
                         f"the guards do not say which appointment fired: {named}")

    def test_the_variable_is_exported_and_not_merely_assigned(self):
        for ref, text in self.guards().items():
            self.assertRegex(
                text, rf"export .*\b{self.APPOINTMENT_ENV}\b",
                f"{ref} assigns the appointment but never exports it, so the "
                "command it wraps never sees it")

    def test_a_single_appointment_run_exports_nothing_new(self):
        # An empty value reads as an appointment named "", which is a different
        # statement from "this run has no named appointments".
        for text in self.guards("block-style-report").values():
            self.assertNotIn(self.APPOINTMENT_ENV, text,
                             "a run with one appointment grew an environment "
                             "variable its command has never seen")


class WhenWasThisAppointmentLastDue(BackendBase):
    """Missing detection for a recurring run needs a MOMENT, not a cadence.

    An interval states how long it may be since the last run outright. A
    recurring run cannot: between 06:30 and 12:30 the legitimate gap is six
    hours, between Saturday midday and Monday morning it is forty two. So the
    question "is it overdue" has no answer in seconds, and the skill said so
    honestly rather than inventing one.

    But it does not need a recurrence engine to answer it. It needs the most
    recent moment the run was DUE, and every ingredient is already here: the
    hour and minute come from `start_of` and the weekday set from
    `weekdays_of`, which are the two functions the unit file itself is rendered
    from. So the check and the machine cannot disagree about when a job fires,
    which is the same rule the calendar drawing follows.

    Three properties this has to keep. It answers in the DECLARED zone, because
    an appointment is wall clock and a trace is UTC, and comparing them without
    a zone is wrong for half the year. It answers per APPOINTMENT, because two
    times of day are two questions. And it refuses, rather than approximating,
    for any recurrence outside the translated subset -- the same refusal the
    renderer already makes, from the same function.
    """

    def due(self, spec, name, now_iso, zone="Europe/Berlin"):
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo
        w = self.load(spec)
        appointment = [a for a in base.appointments_of(w) if a.name == name][0]
        now = datetime.strptime(now_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return base.previous_due(w, appointment, now, ZoneInfo(zone))

    def test_the_morning_appointment_on_a_weekday_afternoon(self):
        # Monday 2026-08-24, 15:00 local (13:00 UTC). The morning run was due
        # this morning at 06:30 local, which is 04:30 UTC.
        got = self.due("twice-daily-report", "morning", "2026-08-24T13:00:00Z")
        self.assertEqual(got.isoformat(), "2026-08-24T04:30:00+00:00")

    def test_the_midday_appointment_before_it_has_fired_today(self):
        # Monday 08:00 local. Midday has not come yet today, so the last time
        # it was due is the PREVIOUS day it runs on, Saturday 12:30 local.
        got = self.due("twice-daily-report", "midday", "2026-08-24T06:00:00Z")
        self.assertEqual(got.isoformat(), "2026-08-22T10:30:00+00:00")

    def test_a_day_the_run_does_not_fire_on_is_skipped(self):
        # The fixture runs Monday to Saturday. Asked on a Sunday, the answer is
        # Saturday, never "yesterday" as a reflex.
        got = self.due("twice-daily-report", "morning", "2026-08-23T13:00:00Z")
        self.assertEqual(got.isoformat(), "2026-08-22T04:30:00+00:00")

    def test_it_is_computed_in_the_declared_zone_and_not_in_utc(self):
        # AT THE DATE BOUNDARY, which is the only place the zone actually
        # decides anything and therefore the only place worth measuring. My
        # first version of this test asked at three in the afternoon, where the
        # UTC date and the local date agree, and it was green with the zone
        # conversion deleted.
        #
        # It also needs a DAILY appointment, not a weekly one: shifting the
        # search window by a day still finds the same weekday, so a weekly run
        # hides the error too. Only a daily one, where the specific DATE
        # decides, makes it visible. My second version used a weekly fixture
        # and was green with the conversion deleted as well.
        #
        # 2026-08-24T23:00Z is TUESDAY 01:00 in Berlin. The run fires at 00:30
        # local every day, so it was last due 30 minutes ago: Tuesday 00:30
        # local, which is 2026-08-24T22:30Z. Read in UTC the walk starts on the
        # Monday and lands a whole day earlier.
        got = self.due("early-daily-report", "", "2026-08-24T23:00:00Z")
        self.assertEqual(
            got.isoformat(), "2026-08-24T22:30:00+00:00",
            f"the due moment is a whole day out: {got.isoformat()}")

    def test_the_two_appointments_answer_differently(self):
        morning = self.due("twice-daily-report", "morning", "2026-08-24T13:00:00Z")
        midday = self.due("twice-daily-report", "midday", "2026-08-24T13:00:00Z")
        self.assertNotEqual(morning, midday,
                            "both appointments were given the same due moment, "
                            "so one of the two questions is unanswered")

    def test_a_recurrence_outside_the_translated_subset_is_refused(self):
        # The same refusal the renderer makes, from the same function. An
        # approximation here would be a number nobody declared, presented as a
        # measurement.
        w = self.load("exotic-recurrence")
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo
        now = datetime(2026, 8, 24, 13, tzinfo=timezone.utc)
        with self.assertRaises(Exception):
            for a in base.appointments_of(w):
                base.previous_due(w, a, now, ZoneInfo("Europe/Berlin"))


class AFileTooBigForOneCommandLineTravelsInParts(MachineGuard):
    """The gate counts a file against the SHELL's limit; the connection is smaller.

    A multiplexed ssh session carries one request in one packet and refuses
    past about 256 KiB with `mux_client_request_session: write packet: Broken
    pipe`, which names neither the file nor the size nor the reason. Measured
    on 2026-08-27 with a 274 KiB page that the size gate had passed and the
    machine would not take, twice in a row, with the same unreadable error.

    Nothing here proves the parts arrived. The caller's read-back does, and
    that is what makes splitting safe at all: a half delivered file fails the
    comparison exactly like a corrupted one.
    """

    def file(self, body, path="/tmp/page.html"):
        return base.RenderedFile(path=path, mode=0o644, content=body)

    def bodies(self, steps):
        """The here-document payload of each step, in order."""
        out = []
        for step in steps:
            script = step.argv[2]
            head, _, rest = script.partition("\n")
            delimiter = head.rsplit("'", 2)[-2]
            out.append(rest.split(delimiter)[0])
        return out

    def test_a_small_file_is_still_one_step(self):
        """A unit file must not grow a second command line for nothing."""
        self.assertEqual(len(base.write_file_steps(self.file("one\ntwo\n"))), 1)

    def test_a_large_one_is_several(self):
        body = "".join(f"line {n}\n" for n in range(400))
        steps = base.write_file_steps(self.file(body), chunk_bytes=200)
        self.assertGreater(len(steps), 1)

    def test_the_first_truncates_and_the_rest_append(self):
        body = "".join(f"line {n}\n" for n in range(400))
        steps = base.write_file_steps(self.file(body), chunk_bytes=200)
        self.assertIn("cat > ", steps[0].argv[2])
        for step in steps[1:]:
            self.assertIn("cat >> ", step.argv[2],
                          "a later part truncated the file the earlier ones wrote")

    def test_the_parts_are_exactly_the_file(self):
        body = "".join(f"line {n}\n" for n in range(400))
        steps = base.write_file_steps(self.file(body), chunk_bytes=200)
        self.assertEqual("".join(self.bodies(steps)), body)

    def test_a_split_never_falls_inside_a_line(self):
        """Every part travels as a here-document, and one of those ends every
        line it carries.

        Two failures, one cause. The mild one puts a newline into the file that
        was never in it. The loud one is that the closing delimiter stops
        standing on a line of its own, so the shell never sees it and reads the
        rest of the command as file content. Both are asserted, because the
        first is what the reassembled bytes show and the second is what the
        machine actually does with the script.
        """
        body = "".join(f"line {n}\n" for n in range(400))
        steps = base.write_file_steps(self.file(body), chunk_bytes=200)
        for part in self.bodies(steps):
            self.assertTrue(part.endswith("\n"))
        for step in steps:
            script = step.argv[2]
            delimiter = script.partition("\n")[0].rsplit("'", 2)[-2]
            self.assertIn(f"\n{delimiter}", script,
                          "the closing delimiter is glued to the last line, so "
                          "the shell never sees it")

    def test_a_single_line_longer_than_the_limit_is_not_cut(self):
        body = "x" * 500 + "\n"
        steps = base.write_file_steps(self.file(body), chunk_bytes=100)
        self.assertEqual(len(steps), 1)
        self.assertEqual("".join(self.bodies(steps)), body)

    def test_the_directory_is_made_once_and_the_mode_set_once_at_the_end(self):
        body = "".join(f"line {n}\n" for n in range(400))
        steps = base.write_file_steps(self.file(body), chunk_bytes=200)
        scripts = [step.argv[2] for step in steps]
        self.assertEqual(sum("mkdir -p " in s for s in scripts), 1)
        self.assertEqual(sum("chmod " in s for s in scripts), 1)
        self.assertIn("chmod ", scripts[-1],
                      "the mode was set before the file was finished")
