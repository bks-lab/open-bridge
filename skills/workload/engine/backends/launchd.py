"""launchd, in two domains built from one implementation.

The user domain (`gui/<uid>`) is what the skill provisions. The system domain
is planned and printed, never executed: no sudo, ever, on a machine carrying
live services.

Three things here are scars, not style:
  * a replace is bootout then bootstrap, never kickstart, because kickstart
    does not reload a unit whose file changed
  * a disable is a persistent `launchctl disable` PLUS the reason, because only
    disable survives a reboot and a renamed file loses the why
  * the domain target carries the uid discovered on the host, never a number
    written into this file
"""

from __future__ import annotations

import plistlib
import shlex

from engine.model import (
    Guarantee,
    Step,
    declaration_digest,
    state_key as model_state_key,
    ensure_id_safe,
    ensure_unit_safe,
)

from . import base, wrapper

#: How long a replace waits for launchd to let go of the old unit before it
#: loads the new one. `launchctl bootout` returns while the old process is still
#: shutting down, and a bootstrap in that window fails with "5: Input/output
#: error" and leaves the unit unloaded. Measured on a unit whose TERM handler
#: takes 3 s: gone after 3.3 s. Thirty seconds covers a slow daemon with room.
UNLOAD_WAIT_SEC = 30


def unload_wait_step(unit_ref: str, *, wait_sec: float | None = None,
                     elevated: bool = False) -> Step:
    """A step that returns once launchd no longer knows `unit_ref`.

    Polls `launchctl print` every 0.1 s and fails after `wait_sec`, so a unit
    that never unloads stops the replace instead of racing it.
    """
    wait = UNLOAD_WAIT_SEC if wait_sec is None else wait_sec
    tries = max(1, int(round(wait * 10)))
    ref = shlex.quote(unit_ref)
    script = (
        f"i=0; while launchctl print {ref} >/dev/null 2>&1; do "
        f"i=$((i+1)); if [ \"$i\" -ge {tries} ]; then "
        f"echo 'launchd still holds {unit_ref} after {wait}s' >&2; exit 1; fi; "
        f"sleep 0.1; done; exit 0"
    )
    return Step(
        argv=("/bin/sh", "-c", script),
        purpose=f"wait until launchd has let go of {unit_ref}",
        timeout_sec=int(wait) + 15,
        requires_elevation=elevated,
    )

#: launchd will not start a second copy of a job whose previous run is still
#: going, so single flight comes free. It promises nothing else: there is no
#: run deadline, no group kill, and its run counter resets, which is what makes
#: an absent run unprovable from launchd alone.
NATIVE_GUARANTEES = frozenset({Guarantee.single_flight})

_CONTINUOUS = frozenset({"daemon", "agent"})


class LaunchdBackend:
    """One implementation. The two instances below differ only by their data."""

    def __init__(self, name, unit_dir, domain, guard_dir=None,
                 requires_elevation=False, label_prefix=base.DEFAULT_LABEL_PREFIX,
                 discovery="session"):
        self.name = name
        self.unit_dir = unit_dir
        self.domain = domain
        self.guard_dir = guard_dir
        self.requires_elevation = requires_elevation
        self.label_prefix = label_prefix
        #: Which question enumeration asks. "session" is `launchctl list`, whose
        #: answer is the CALLING SESSION and therefore only ever the user domain.
        #: "domain" is `launchctl print <domain>`, which answers about the domain
        #: named. The two are not interchangeable, and treating them as one is a
        #: scar: on 2026-08-23 both instances ran `launchctl list` and the system
        #: instance stamped `system/` onto every user agent it came back with, so
        #: the report doubled every unit and hid every real root daemon.
        self.discovery = discovery
        self.platforms = frozenset({"macos"})
        self.kinds = frozenset({"recurring", "interval", "daemon", "watch", "agent"})
        self.guarantees = NATIVE_GUARANTEES
        self.wrappable = True
        self.provisionable = True
        self.kind_remedy = ("a run that happens once has no appointment to "
                            "repeat; carry it with runtime dispatcher instead")

    # -- naming ------------------------------------------------------------

    def label(self, w, appointment=None) -> str:
        """`<prefix>.<id>`, plus `.<appointment>` where a run has several.

        The suffix comes from the DECLARED appointment name and from nowhere
        else. A name derived from the time would rename the unit, orphan its
        ownership stamp and orphan its trace the day somebody moves the run ten
        minutes, and every one of those failures is silent.

        A declaration with a single appointment gets no suffix at all, so
        nothing that already exists on a machine is renamed by this feature.
        """
        if appointment is None:
            appointment = base.only_appointment(w)
        suffix = getattr(appointment, "name", "") or ""
        # The declaration may carry its OWN prefix, for a unit that already
        # exists on the machine under a hand made name. Without it `adopt`
        # could only ever take over a unit that happens to carry this
        # instance's prefix, which is exactly the unit nobody makes by hand.
        # The id stays the tail either way, and that is what inventory
        # matching and the stamp key rely on.
        prefix = getattr(w.placement, "label_prefix", None) or self.label_prefix
        return f"{prefix}.{w.id}" + (f".{suffix}" if suffix else "")

    def unit_name(self, w, appointment=None) -> str:
        """What the machine calls this run, for a reader holding both.

        The page shows a declaration id and the unit is named otherwise, so
        anyone comparing the page with `launchctl list` had to know the
        mapping. Asked here rather than rebuilt in the view: a second
        derivation of a name is exactly how a migrated run was filed as
        foreign software on 2026-08-24, by four hand kept lists that had
        already drifted apart.
        """
        return self.label(w, appointment)

    def domain_target(self, ctx) -> str:
        return self.domain.replace("<uid>", str(ctx.uid))

    def unit_ref(self, w, ctx, appointment=None) -> str:
        return f"{self.domain_target(ctx)}/{self.label(w, appointment)}"

    def unit_path(self, w, ctx, appointment=None) -> str:
        directory = self.unit_dir.replace("<home>", str(ctx.home))
        return f"{directory}/{self.label(w, appointment)}.plist"

    def guard_directory(self, ctx):
        if self.guard_dir is None:
            return None
        return self.guard_dir.replace("<prefix>", self.label_prefix)

    # -- render ------------------------------------------------------------

    def render(self, w, h, ctx, appointment=None) -> base.Artifact:
        base.ensure_kind(self, w, self.kind_remedy)
        ensure_id_safe(w)
        if appointment is None:
            appointment = base.only_appointment(w)
        digest = declaration_digest(w)
        command = base.command_of(w)
        supplied = wrapper.supplies(w, self)

        files = []
        guard_path = None
        if supplied:
            guard = wrapper.wrap(w, ctx, command, guard_dir=self.guard_directory(ctx),
                                 supplied=supplied, digest=digest,
                                 appointment=appointment)
            guard_path = guard.path
            files.append(guard)
            program = wrapper.guard_argv(guard.path)
        else:
            program = command

        plist = {
            "Label": self.label(w, appointment),
            # The marker on the RIGHT of the union, so it wins: ownership is
            # read back out of exactly these two variables, and a declaration
            # that set one would not be configuring a run, it would be claiming
            # somebody else's unit. The declaration gate refuses the collision
            # by name, so nothing is silently lost; this is the order under it.
            "EnvironmentVariables": _environment(w) | base.marker_env(w, digest),
        }
        if program:
            # Refused here for the same reason the environment is: a plist can
            # hold an argument with a newline in it and a systemd `ExecStart=`
            # cannot, and a declaration that means two things on two machines
            # is the failure this whole pass is about. A NUL is refused by
            # plistlib itself, but as a bare ValueError naming neither the
            # workload nor the field.
            for index, argument in enumerate(command):
                ensure_unit_safe(argument, key_path=f"execution.command[{index}]",
                                 workload_id=w.id)
            plist["ProgramArguments"] = [str(a) for a in program]
        working_dir = base.working_dir_of(w)
        if working_dir and not guard_path:
            plist["WorkingDirectory"] = ensure_unit_safe(
                working_dir, key_path="execution.working_dir", workload_id=w.id)
        plist.update(self._trigger(w, ctx, appointment))

        unit = base.RenderedFile(
            path=self.unit_path(w, ctx, appointment),
            mode=0o644,
            content=plistlib.dumps(plist, sort_keys=True).decode("utf-8"),
        )
        # The unit comes first, so a caller asking for "the unit" takes files[0].
        ordered = tuple([unit] + files)

        notes = ""
        if not program:
            notes = ("the declaration names no command, so this unit carries "
                     "none either and cannot be loaded as it stands; it is "
                     "rendered to keep the run visible")
        return base.Artifact(
            runtime=self.name,
            unit_ref=self.unit_ref(w, ctx, appointment),
            state_key=model_state_key(w, appointment),
            files=ordered,
            digest=base.digest_of(ordered),
            guarantees_native=self.guarantees,
            guarantees_wrapped=frozenset(supplied),
            notes=notes,
        )

    def _trigger(self, w, ctx, appointment=None) -> dict:
        kind = w.placement.kind
        if kind in _CONTINUOUS:
            # A daemon is meant to be up, so loading it starts it.
            return {"KeepAlive": True, "RunAtLoad": True}

        # RunAtLoad stays false everywhere else: a bootstrap at 15:00 must not
        # fire the 06:10 report.
        trigger = {"RunAtLoad": False}
        if kind == "recurring":
            base.ensure_local_timezone(w, ctx, self)
            hour, minute, shift = base.start_of(w, appointment)
            days = base.weekdays_of(w, shift, appointment)
            if days:
                trigger["StartCalendarInterval"] = [
                    {"Hour": hour, "Minute": minute, "Weekday": day} for day in days
                ]
            else:
                trigger["StartCalendarInterval"] = [{"Hour": hour, "Minute": minute}]
            return trigger

        if kind == "watch":
            trigger["WatchPaths"] = [str(p) for p in w.schedule.watch_paths]
            # A path watcher can fire before a file has finished arriving, so a
            # declared cadence beside it is a fallback, not a contradiction.
            if getattr(w.schedule, "every_sec", None):
                trigger["StartInterval"] = int(w.schedule.every_sec)
            return trigger

        trigger["StartInterval"] = int(w.schedule.every_sec)
        return trigger

    # -- step plans --------------------------------------------------------

    def _domain_of(self, a) -> str:
        return a.unit_ref.rsplit("/", 1)[0]

    def _unit_file(self, a) -> str:
        return str(a.files[0].path)

    def _write_steps(self, a) -> list:
        return [base.write_file_step(f, elevated=self.requires_elevation) for f in a.files]

    def install_steps(self, a, h) -> tuple:
        steps = self._write_steps(a)
        steps.append(Step(
            argv=("launchctl", "bootstrap", self._domain_of(a), self._unit_file(a)),
            purpose=f"load {a.unit_ref}",
            requires_elevation=self.requires_elevation,
        ))
        return tuple(steps)

    def replace_steps(self, a, h) -> tuple:
        # bootout FIRST, then the new bytes, then bootstrap. kickstart is not
        # here on purpose: it restarts what is loaded, it does not reload a
        # changed unit, so a schedule change silently would not take. The wait
        # after the bootout is not optional: see UNLOAD_WAIT_SEC.
        steps = [Step(
            argv=("launchctl", "bootout", a.unit_ref),
            purpose=f"unload the running {a.unit_ref}",
            expect_rc=(0, 3, 113),
            requires_elevation=self.requires_elevation,
        ), unload_wait_step(a.unit_ref, elevated=self.requires_elevation)]
        steps.extend(self._write_steps(a))
        steps.append(Step(
            argv=("launchctl", "bootstrap", self._domain_of(a), self._unit_file(a)),
            purpose=f"load {a.unit_ref} again, with the new bytes",
            requires_elevation=self.requires_elevation,
        ))
        return tuple(steps)

    def disable_steps(self, a, h, reason: str) -> tuple:
        return (
            Step(
                argv=("launchctl", "bootout", a.unit_ref),
                purpose=f"stop {a.unit_ref} now, reason: {reason}",
                expect_rc=(0, 3, 113),
                requires_elevation=self.requires_elevation,
            ),
            Step(
                argv=("launchctl", "disable", a.unit_ref),
                purpose=f"keep {a.unit_ref} off across reboots, reason: {reason}",
                requires_elevation=self.requires_elevation,
            ),
        )

    def uninstall_steps(self, a, h) -> tuple:
        paths = " ".join(base.shell_command([str(f.path)]) for f in a.files)
        return (Step(
            argv=("/bin/sh", "-c", f"rm -f {paths}"),
            purpose=f"remove the files of {a.unit_ref}",
            requires_elevation=self.requires_elevation,
        ),)

    # -- reading the live source ------------------------------------------

    #: What `launchctl print` has to show for a run that never ends. The
    #: command answers 0 for a unit the domain merely HOLDS, so for a daemon
    #: the return code says "launchd knows this label" and nothing about the
    #: program. A pid says a process exists. Anchored to the start of a line so
    #: it cannot match a word ending in `pid` further inside the report.
    alive_expect = r"re:(?m)^\s*pid\s*=\s*[0-9]+"

    def default_probe(self, a, h) -> Step:
        return Step(
            argv=("launchctl", "print", a.unit_ref),
            purpose=f"ask launchd about {a.unit_ref}",
            expect_rc=(0, 3, 113),
        )

    def inspect_steps(self, a, h) -> tuple:
        return (self.default_probe(a, h),)

    def parse_inspection(self, outs, unit_ref: str = ""):
        """One `launchctl print` into a LiveUnit, or None when it is not there."""
        text = base.text_of(outs[0] if isinstance(outs, (list, tuple)) else outs)
        if not text.strip() or "Could not find service" in text:
            return None
        from engine.reconcile import LiveUnit

        head = text.split("=", 1)[0].strip() if "=" in text else ""
        return LiveUnit(
            runtime=self.name,
            unit_ref=head or unit_ref,
            path=_value_after(text, "path = "),
            marker_id=_marker(text, base.MARKER_ENV_ID),
            marker_digest=_marker(text, base.MARKER_ENV_DIGEST),
            # `launchctl print` carries the environment, so this one looked.
            marker_observed=True,
            # `launchctl print` says nothing about the persistent off-list, so
            # this claims nothing about it either: `disabled_list_steps` is the
            # read that answers that question.
            enabled=None,
            running="state = running" in text,
            raw=text,
        )

    def disabled_list_steps(self, a, h) -> tuple:
        # A separate, domain-wide read, because `launchctl print` does not carry
        # the persistent off-list at all. Without this step the refusal that
        # protects a deliberately stopped unit can never fire.
        #
        # A READ, so it never carries `requires_elevation`: on this backend that
        # flag belongs to the write plan. `launchctl print-disabled system`
        # answers an ordinary user, and inheriting the flag here made one
        # root-owned unit abort the report for every run on its host (#179).
        return (
            Step(
                argv=("launchctl", "print-disabled", self._domain_of(a)),
                purpose=f"read the persistent off-list of {self._domain_of(a)}",
                expect_rc=(0, 3, 113),
            ),
        )

    def parse_disabled(self, outs, unit_ref: str):
        """True, False, or None when nobody answered.

        The distinction matters: None means the off-list was not read, and a
        provision run must not read that as permission to switch something on.
        """
        text = base.text_of(outs[0] if isinstance(outs, (list, tuple)) else outs)
        if not text.strip():
            return None
        label = base.label_of(unit_ref).lower()
        for line in text.lower().splitlines():
            stripped = line.strip()
            if stripped.startswith(f'"{label}"') and "=> disabled" in stripped:
                return True
        return False

    def discover_steps(self, h) -> tuple:
        # `id -u` is asked on the host, so no uid is written into this file.
        #
        # The persistent off-list is NOT read here. It is a domain-wide read of
        # its own (`disabled_list_steps`), and enumeration is not where it is
        # needed: what must never be switched back on is decided per unit, while
        # provisioning one. Enumerating carries no such decision.
        if self.discovery == "domain":
            # `launchctl print <domain>` answers about the domain named, and it
            # answers unprivileged: reading a domain is not the same permission
            # as changing one. `launchctl list` would answer about the session
            # this ssh call opened, which is a different machine-fact entirely.
            return (
                Step(
                    argv=("/bin/sh", "-c",
                          f'printf "uid=%s\\n" "$(id -u)"; launchctl print {self.domain}'),
                    purpose=f"enumerate the services of the {self.domain} domain",
                ),
            )
        return (
            Step(
                argv=("/bin/sh", "-c", 'printf "uid=%s\\n" "$(id -u)"; launchctl list'),
                purpose="enumerate the loaded jobs of the calling session",
            ),
        )

    def parse_discovery(self, outs) -> list:
        from engine.reconcile import LiveUnit

        listing = _text_of(outs[0] if outs else "")
        if self.discovery == "domain":
            return self._parse_domain_print(listing)
        uid = ""
        units = []
        for line in listing.splitlines():
            if line.startswith("uid="):
                uid = line.partition("=")[2].strip()
                continue
            columns = line.split("\t")
            if len(columns) != 3 or columns[0] == "PID":
                continue
            pid, _, label = (c.strip() for c in columns)
            units.append(LiveUnit(
                runtime=self.name,
                unit_ref=f"{self.domain.replace('<uid>', uid)}/{label}",
                path=None,
                marker_id=None,
                marker_digest=None,
                # None, not True: enumeration does not ask whether a label is
                # on the persistent off-list, and claiming it is on either side
                # would be an answer nobody gave.
                enabled=None,
                running=pid not in ("-", ""),
                raw=line,
            ))
        return units

    def _parse_domain_print(self, listing: str) -> list:
        """The `services = { ... }` block of `launchctl print <domain>`.

        Bounded by the block, not by the shape of a line: the same output
        carries `endpoints = { ... }` whose rows look identical, and an
        unbounded reader turns a mach endpoint into a service that can then be
        reported missing. The closing brace is matched at the indent the block
        opened on, so a nested block cannot end it early.
        """
        from engine.reconcile import LiveUnit

        units = []
        indent = None
        for line in listing.splitlines():
            stripped = line.strip()
            if indent is None:
                if stripped == "services = {":
                    indent = len(line) - len(line.lstrip())
                continue
            if stripped == "}" and (len(line) - len(line.lstrip())) == indent:
                break
            head, tab, label = line.rpartition("\t")
            label = label.strip()
            if not tab or not label:
                continue
            columns = head.split()
            if len(columns) != 2:
                continue
            pid = columns[0]
            units.append(LiveUnit(
                runtime=self.name,
                unit_ref=f"{self.domain}/{label}",
                path=None,
                marker_id=None,
                marker_digest=None,
                # None, not True: see the session parser. Enumeration does not
                # read the persistent off-list in either domain.
                enabled=None,
                running=pid not in ("-", "0", ""),
                raw=line,
            ))
        return units


def _environment(w) -> dict:
    """The declared environment, refused where it could not be written at all.

    A plist escapes for us, so a space or a quote arrives here intact where the
    same value would split a systemd `Environment=` line. The refusal is kept
    anyway, and deliberately: a declaration has to mean the SAME thing on both
    backends. A value that only one of them can carry is a workload that moves
    from a Mac to a Linux box and quietly runs with half its configuration.

    A control character is also the one shape plistlib itself refuses, and it
    refuses it as a bare ValueError with no workload and no key path in it.
    """
    return {name: ensure_unit_safe(value, key_path=f"execution.env.{name}",
                                   workload_id=w.id)
            for name, value in base.env_of(w).items()}


def _text_of(out) -> str:
    if out is None:
        return ""
    if isinstance(out, str):
        return out
    return getattr(out, "stdout", "") or ""


def _value_after(text: str, needle: str):
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(needle):
            return stripped[len(needle):].strip()
    return None


def _marker(text: str, key: str):
    # The two marker keys share a prefix, so the arrow is part of the needle.
    return _value_after(text, f"{key} => ")


def build(cfg) -> tuple:
    """Both instances, parameterised from configuration."""
    prefix = getattr(cfg, "label_prefix", base.DEFAULT_LABEL_PREFIX)
    user = LaunchdBackend(
        name="launchd",
        unit_dir="<home>/Library/LaunchAgents",
        domain="gui/<uid>",
        guard_dir=None,
        requires_elevation=False,
        label_prefix=prefix,
    )
    system = LaunchdBackend(
        name="launchd-system",
        unit_dir="/Library/LaunchDaemons",
        domain="system",
        # A unit that runs as root must not read its guard out of somebody's
        # home directory, so the system domain keeps its own.
        guard_dir="/usr/local/lib/<prefix>/workloads",
        requires_elevation=True,
        label_prefix=prefix,
        # Reading the system domain needs no elevation; only changing it does.
        # `requires_elevation` above governs the WRITE plan, never the read.
        discovery="domain",
    )
    return user, system


#: The registry holds these two. `configure(cfg)` in the package replaces them
#: with instances built from the live configuration.
LAUNCHD_USER, LAUNCHD_SYSTEM = build(None)
