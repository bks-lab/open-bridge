"""The vocabulary, and the repository side of the world.

Declarations go in, typed objects come out, plus the enums, constants and
digests every other module speaks. This module knows nothing about machines,
subprocesses or unit file formats: it is the half of the skill that can be
reasoned about without a box.

Three things here are deliberate rather than convenient.

* ``validate`` is HAND WRITTEN and never reads the JSON schema file. Two gates
  that read the same document are one gate with a second name; this one exists
  precisely so it can fail differently.
* Schema defaults are materialised at load time. ``isolation``,
  ``single_flight`` and ``on_timeout`` each encode an incident, so an absent
  field has to arrive as the safe value, never as ``None``.
* Writing back into a declaration is a surgical line edit. A dump round trip
  would silently drop the comments and the editor hint line that carry the why.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from collections.abc import Mapping
from typing import Optional

import yaml

SCHEMA_VERSION = 1


# ── The closed enums ─────────────────────────────────────────────────────────

class WorkloadState(str, Enum):
    """Nineteen members, closed. A new situation maps onto one of these, or the
    enum grows deliberately together with a test.

    Three of them were added late and for the same reason: something on the
    machine was writing an answer nobody read. The trace gave the last two, a
    line per run that made a failed run and a missing run look like a healthy
    one. The stamp gave the sixteenth, the client path a privacy grant hangs
    off, which stays where it was when the declaration names a new one.
    """

    in_sync = "in_sync"
    not_provisioned = "not_provisioned"
    absent = "absent"
    stopped = "stopped"
    drifted = "drifted"
    unstamped = "unstamped"
    retired_but_live = "retired_but_live"
    observed = "observed"
    unknown = "unknown"
    orphan_stamp = "orphan_stamp"
    unmanaged = "unmanaged"
    inventory_missing = "inventory_missing"
    inventory_stale = "inventory_stale"
    #: The inventory names it, nothing runs it, AND the entry itself says that
    #: is on purpose: `intentionally_absent: {since, reason}`, the field
    #: open-bridge#159 put into the host contract. Without it a decision that
    #: was written down reads exactly like a record nobody maintained, and the
    #: advice under it is to delete the decision.
    intentionally_absent = "intentionally_absent"
    #: The unit exists, its bytes match, and the service manager's PERSISTENT
    #: off-list holds it, so it will not start and a reboot will not change
    #: that. `in_sync` is a statement about bytes and was the only one made.
    disabled = "disabled"
    #: The program a unit CALLS is not the repository's own file, and the copy
    #: on the machine has come apart from it. `in_sync` never looked: it
    #: compares the unit against the artifact it was rendered from, and the
    #: program is neither.
    source_drift = "source_drift"
    #: The newest line the guard script wrote for this run ended non zero.
    last_run_failed = "last_run_failed"
    #: No line for longer than the run's own schedule allows. For `interval`
    #: that is the declared cadence. For a recurring appointment it is the
    #: moment it was last due, computed from the same two functions the unit
    #: file is rendered from, so the check and the machine cannot disagree
    #: about when a run fires. A recurrence outside the translated subset is
    #: refused rather than approximated.
    overdue = "overdue"
    #: The interpreter moved after provisioning, and a privacy grant was
    #: declared. The grant is still on the old path; the new one holds none, and
    #: a client with no grant is not denied, it is shown nothing.
    grant_orphaned = "grant_orphaned"


class Severity(str, Enum):
    high = "high"
    medium = "medium"
    info = "info"


class Guarantee(str, Enum):
    """The currency between what a declaration demands and what a backend
    natively provides."""

    deadline = "deadline"
    process_group_kill = "process_group_kill"
    single_flight = "single_flight"
    missing_detection = "missing_detection"


# ── The ownership vocabulary ─────────────────────────────────────────────────
# Render writes these, reconcile reads them back. A second copy in either place
# would drift apart, so they live here and nowhere else.

MARKER_ENV_ID = "BRIDGE_WORKLOAD"
MARKER_ENV_DIGEST = "BRIDGE_WORKLOAD_DIGEST"
#: Which appointment fired, exported by the guard ONLY where a run has several.
#: The command needs it because two appointments share one argv and answer two
#: distribution lists; passed rather than worked out from the clock, since a
#: run delayed past its hour (a machine that was asleep) would otherwise answer
#: the wrong list. A single-appointment run does not export it at all: an empty
#: value reads as an appointment named "", which is a different statement.
MARKER_ENV_APPOINTMENT = "BRIDGE_WORKLOAD_APPOINTMENT"
CRON_BEGIN = "# >>> bridge-workload"
CRON_END = "# <<< bridge-workload"
STAMP_SUFFIX = ".stamp.json"
STAMP_VERSION = 1


# ── The allowed values, spelled out once ─────────────────────────────────────

SCOPES = ("core", "org", "personal", "user")
KINDS = ("recurring", "interval", "daemon", "watch", "agent", "oneshot")

#: The kinds that are supposed to be running RIGHT NOW. Everything else
#: fires, ends and waits, so "not running" is where it spends its life and
#: says nothing about its health. Judging all six by one signal reported a
#: cadence job as stopped forty-five seconds after a successful run.
CONTINUOUS_KINDS = ("daemon", "agent")
RUNTIMES = ("launchd", "launchd-system", "systemd", "cron", "dispatcher", "manual", "external")
OWNERS = ("bridge", "human", "foreign")
ISOLATIONS = ("process-group", "process")
ON_TIMEOUTS = ("report", "kill-silent")
EVIDENCE = ("exit-code", "log-trace", "delivery-receipt")
NOTIFY_ON = ("failure", "timeout", "missing")

TOP_LEVEL_KEYS = ("schema_version", "scope", "id", "title", "purpose", "persona_ref",
                  "system", "placement", "schedule", "execution", "response",
                  "reconcile", "retired", "learned_from")

#: Kinds the Bridge both owns AND executes, so they need a deadline and evidence.
EXECUTED_KINDS = ("recurring", "interval", "watch", "oneshot")

#: Which schedule field each kind is answered by.
SCHEDULE_FOR_KIND = {
    "recurring": "rrule",
    "interval": "every_sec",
    "watch": "watch_paths",
    "oneshot": "at",
}

#: The four keys that FIRE something. Exactly one of them may stand in a
#: schedule, and it has to be the one the kind uses: two triggers in one
#: declaration means the backend picks which one wins and the file no longer
#: says what runs. A `oneshot` carrying `every_sec` reads to a human as a
#: recurring job and fires once; a `watch` carrying an `rrule` reads as
#: scheduled and fires on a path.
TRIGGER_KEYS = ("rrule", "every_sec", "watch_paths", "at")

#: The one named exception, and it is a pairing rather than a second trigger: a
#: path watcher can fire before the file it watches has finished materialising,
#: so the cadence is the safety net that catches the run the watch missed. That
#: is a launchd unit with WatchPaths AND StartInterval.
EXTRA_TRIGGER_FOR_KIND = {"watch": ("every_sec",)}

#: Cosmetic fields: a typo fix or a provision timestamp is not drift.
COSMETIC_FIELDS = ("title", "purpose", "learned_from", "provisioned_at")


# ── What a declared value may be, before it is written into a file ───────────
# Every generated artifact of this skill is LINE BASED and every one of them
# writes declared values into it: a systemd directive, a crontab line, a shell
# assignment in the guard script. A value that carries a line break does not
# arrive escaped there, it arrives as the NEXT directive. So the shape of a
# value is an invariant of the declaration, not a detail of one renderer, and
# it is decided once, here, where both the gate and the backends can read it.

#: The id is not only a name. It becomes a unit file NAME, a launchd label, a
#: systemd `Unit=` reference and a path element inside the guard script, in
#: every case unquoted. A slug is the only shape that means the same thing in
#: all four. Written out by hand rather than read off the declaration schema:
#: the two gates carry the same rule on purpose and still fail differently.
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")

#: A POSIX environment variable name. The KEY is never quoted by anybody: it is
#: written bare on the left of `Environment=NAME=...` and bare on the left of a
#: shell assignment in the guard script. A key that is not a name is executable
#: text in the second place and a parse error in the first.
ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#: Refused in every declared value that reaches a generated file, with the name
#: to say out loud. A NUL cannot be represented in any of the three formats at
#: all; the two line breaks end the directive they sit in and hand whatever
#: follows to the parser as a new one.
FORBIDDEN_IN_VALUES = (
    ("\x00", "a NUL byte"),
    ("\n", "a line break"),
    ("\r", "a carriage return"),
)

#: Absolute, in the three places a path is handed to a SERVICE MANAGER rather
#: than to a login shell: the interpreter, the working directory and argv[0].
#: A service manager starts a unit with a short PATH and no shell, so `claude`
#: resolves to something else than it does in a terminal, or to nothing, and a
#: tilde is a literal character nobody expands. On macOS a relative interpreter
#: is additionally a DIFFERENT TCC client, with none of the grants the real one
#: has. The declaration schema carries the same `^/` on all three; this is the
#: hand written half of it, spelled out here rather than read off that document,
#: so the two gates hold the same rule and still fail differently.
ABSOLUTE_PATH_PATTERN = re.compile(r"^/")

#: A path SEGMENT that is nothing but a version number. Two independent silent
#: failures hang on it, which is why it is refused rather than warned about.
#:
#: The file goes away. A versioned directory exists in order to be replaced, so
#: the next upgrade removes the one the declaration names and the unit starts
#: nothing at all.
#:
#: And on macOS the privacy grant goes away with it. TCC keys a grant on the
#: literal client path, so a new version is a new client that was never granted
#: anything. Measured, not assumed: six consecutive claude versions each hold
#: their own row under `.local/share/claude/versions/<version>`, and five of
#: them grant nothing, because each update wrote a path nobody had answered a
#: prompt for. The same database carries rclone twice, once under a Cellar path
#: that moves and once under a stable one that does not.
#:
#: The optional trailing group is Homebrew's revision suffix (`1.10.1_1`). The
#: optional leading `v` is the other common spelling. A segment with no dot is
#: not a version: `report2` and `python3` stay untouched on purpose, because a
#: digit in a name is not a version number and refusing one would be a guess.
VERSION_SEGMENT_PATTERN = re.compile(r"(?:^|/)(v?\d+(?:\.\d+)+(?:[._-][A-Za-z0-9]+)?)(?:/|$)")

#: Privacy grants a workload can declare it depends on, named after the pane a
#: human has to open to give one. A closed list, because the value's whole job
#: is to send a person to the right place: a typo would send them to a pane that
#: does not exist, and they would find nothing and conclude the grant is fine.
#: Nothing here is checked against the machine. macOS protects the TCC database
#: from being read or written by anything but itself, so a declaration can say
#: what it NEEDS and never what it HAS.
PRIVACY_GRANTS = (
    "full-disk-access", "calendar", "contacts", "reminders", "photos",
    "automation", "accessibility", "screen-recording", "microphone", "camera",
    "files-and-folders", "bluetooth", "local-network",
)

#: Interpreters the whole machine already shares. A grant is issued to a PATH,
#: so granting one of these does not grant it to this workload: it grants it to
#: every program that will ever run at that path, including the ones somebody
#: else chooses. Full Disk Access on `/usr/bin/python3` is Full Disk Access for
#: every python script on the box.
#:
#: This scar is already paid. The calendar exporter needs a total read, and a
#: shared `uv` would have handed the same total read to an internet reachable
#: agent whose file tool takes absolute paths. The fix was a second frozen copy
#: at its own path, which is what a dedicated client means here.
#:
#: The same list is spelled out in the declaration schema, deliberately and in
#: the same order. Both gates hold this rule and fail differently; if one moves,
#: the other moves with it.
SHARED_INTERPRETERS = (
    "/bin/sh", "/bin/bash", "/bin/zsh", "/bin/dash", "/bin/ksh",
    "/usr/bin/env", "/usr/bin/python3", "/usr/bin/perl", "/usr/bin/ruby",
    "/usr/bin/osascript", "/usr/bin/swift",
    "/opt/homebrew/bin/python3", "/opt/homebrew/bin/bash", "/opt/homebrew/bin/zsh",
    "/usr/local/bin/python3", "/usr/local/bin/bash",
)

#: An environment VALUE is a locator, never a value. Refused because it IS a
#: value, not because it looks like a key: a declaration is a tracked file, so a
#: secret pasted here travels twice, verbatim into the unit on the machine and
#: into git along with the declaration. What it does not do is resolve anything
#: -- the process receives the locator and resolves it itself -- and a secret
#: TYPED as a locator is well formed and passes. Same closed list as the schema.
ENV_VALUE_PATTERN = re.compile(r"^(azure-keyvault|keychain|1password|keepass|op|vault|file)://\S+$")

#: A recipient is a reference, and these two shapes are what make that sentence
#: true instead of merely stated. A slug has no `@`, no dot, no space and no
#: capital, so an address, a phone number and a written-out name are refused by
#: the FORM, with nothing guessing what a person looks like. Neither pattern
#: checks that the slug exists: only a read of identity/mandants/<slug>.yaml
#: answers that, and this gate reads no other file.
MANDANT_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
#: A persona slug, or one of exactly two reserved answers. The leading
#: underscore is what keeps them apart for good: the persona schema requires
#: ^[a-z][a-z0-9-]*$, so no persona can ever be called `_shared`, and the
#: collision cannot be introduced later by naming one.
PERSONA_PATTERN = re.compile(r"^(_shared|_infrastructure|[a-z][a-z0-9-]*)$")
PERSON_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

#: Which larger thing a run is a part of. Same shape rule as the hat above and
#: the same reason for a reserved answer: `_standalone` is a run somebody looked
#: at and found to stand alone, while absent is a run nobody classified. The two
#: carry different advice, so they must not print the same.
SYSTEM_PATTERN = re.compile(r"^(_standalone|[a-z][a-z0-9-]*)$")


def unsafe_reason(value) -> str:
    """Why this value cannot be written into a generated file, or "".

    One predicate, read by the hand written gate AND by the backends, so the
    refusal a declaration meets and the refusal a caller building a Workload in
    code meets are the same refusal and cannot drift apart.
    """
    text = str(value)
    for char, name in FORBIDDEN_IN_VALUES:
        if char in text:
            return f"carries {name}, which ends the directive it is written into"
    return ""


def ensure_id_safe(w) -> str:
    """The id, refused at the moment it becomes a path and a unit reference.

    The backstop under the gate's slug rule, for the same reason
    `ensure_unit_safe` is one: `render` is reachable with a Workload nobody
    validated, and the id is not written into a file there, it decides WHICH
    FILE. A slash puts the unit somewhere else entirely; a space splits the
    reference the loader is later handed back.
    """
    from .errors import DeclarationError

    if not ID_PATTERN.match(str(w.id)):
        raise DeclarationError(
            f"{w.id!r} is not a slug, and the id is written unquoted into the "
            f"unit file name, the label and the paths inside the guard script; "
            f"it must match {ID_PATTERN.pattern}",
            id=str(w.id), key_path="id")
    return str(w.id)


def ensure_env_name(name, *, workload_id: str = "") -> str:
    """The raising form of the environment NAME rule, at the moment of writing.

    The gate refuses such a name long before this, and the backends have their
    own reasons to care: `Environment=NAME=` takes the name bare, and the guard
    script writes it bare on the left of a shell assignment AND after `export`,
    where anything that is not a name is simply the next command -- twice. That
    is the one place in this skill where a declared string is executed rather
    than written, so it gets a backstop of its own rather than a hope that
    everybody validated first.
    """
    from .errors import DeclarationError

    if not ENV_NAME_PATTERN.match(str(name)):
        raise DeclarationError(
            f"{workload_id or '<workload>'}: execution.env: {name!r} is not an "
            f"environment variable name; it is written unquoted into a unit file "
            f"and into a shell assignment, so it must match {ENV_NAME_PATTERN.pattern}",
            id=workload_id, key_path="execution.env")
    return str(name)


def ensure_unit_safe(value, *, key_path: str, workload_id: str = "") -> str:
    """The raising form of `unsafe_reason`, for the moment of writing a file.

    The gate refuses such a value long before this, and says so per key path.
    This is the backstop underneath it: `render` is also reachable with a
    Workload nobody validated, and emitting a broken unit file there would put
    the damage on a machine instead of in an error message.
    """
    from .errors import DeclarationError

    reason = unsafe_reason(value)
    if reason:
        raise DeclarationError(
            f"{workload_id or '<workload>'}: {key_path}: {reason}; "
            f"a unit file is line based and cannot carry it",
            id=workload_id, key_path=key_path)
    return str(value)


# ── One outbound call ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Step:
    """One call to the outside. argv only, never a shell string.

    A user authored probe becomes ``('/bin/sh', '-c', cmd)`` at the caller, so
    the single shell in this skill stays explicit and visible.
    """

    argv: tuple = ()
    purpose: str = ""
    expect_rc: tuple = (0,)
    timeout_sec: Optional[int] = None
    requires_elevation: bool = False


# ── The declaration, mirrored one to one ─────────────────────────────────────

@dataclass(frozen=True)
class Placement:
    host: str = ""
    kind: str = ""
    runtime: str = ""
    owner: str = ""
    provisioned_at: Optional[str] = None
    interpreter: Optional[str] = None
    privacy_grants: tuple = ()
    port: Optional[int] = None
    #: The label prefix for THIS declaration, when the unit on the machine
    #: already carries a foreign one. None = the instance default from config.
    #:
    #: A PREFIX and not a whole label, on purpose: everything downstream relies
    #: on the declaration id being the tail of the label (inventory matching,
    #: the ownership stamp key, the trace file, the guard script name). A free
    #: form label would break that relationship for all of them at once.
    #: Measured against a live machine carrying 55 hand made units: every one
    #: decomposed into <prefix>.<id>[.<appointment>], three-segment prefixes
    #: and appointment tails included. So a prefix is enough, and enough is
    #: the point.
    label_prefix: Optional[str] = None


@dataclass(frozen=True)
class Appointment:
    """One time this run answers, with the recurrence that belongs to it.

    The NAME is declared, never derived from the time: the unit on the machine,
    its ownership stamp and its trace are all named after it, and a name built
    from the clock would orphan all three the day somebody moves the run ten
    minutes. A declaration with a single appointment leaves the name empty,
    because nothing has to be told apart from anything.
    """

    name: str = ""
    at: Optional[str] = None
    rrule: Optional[str] = None
    duration_estimate_min: Optional[int] = None


@dataclass(frozen=True)
class Schedule:
    rrule: Optional[str] = None
    every_sec: Optional[int] = None
    watch_paths: tuple = ()
    at: Optional[str] = None
    delivery_at: Optional[str] = None
    duration_estimate_min: Optional[int] = None
    timezone: Optional[str] = None
    #: ALWAYS the full list, whichever spelling the file used. The shorthand
    #: (rrule + delivery_at) normalises to one unnamed entry here, so no reader
    #: downstream has to ask which spelling it was looking at. A schedule with
    #: no appointment at all (interval, watch, daemon) leaves it empty.
    appointments: tuple = ()


@dataclass(frozen=True)
class Execution:
    command: tuple = ()
    working_dir: Optional[str] = None
    env: Mapping = field(default_factory=dict)
    timeout_sec: Optional[int] = None
    isolation: str = "process-group"
    single_flight: bool = True
    on_timeout: str = "report"


@dataclass(frozen=True)
class Recipient:
    mandant: str = ""
    person: Optional[str] = None
    #: Appointment names this recipient belongs to. Empty means every one of
    #: them, which is what almost every recipient is. It exists so that a run
    #: answering two lists at two times can say so instead of claiming that
    #: everybody gets everything.
    only_at: tuple = ()


@dataclass(frozen=True)
class Response:
    evidence: Optional[str] = None
    recipients: tuple = ()
    notify_on: tuple = ()
    notify_via: Optional[str] = None
    #: Exit codes the run uses for "failed, try again next tick" (75 is
    #: EX_TEMPFAIL). The first such failure after a clean run wakes nobody; a
    #: second failure in a row does. Codes not named here speak at once.
    transient_exit_codes: tuple = ()


@dataclass(frozen=True)
class ReconcileSpec:
    probe: Optional[str] = None
    expect: Optional[str] = None
    check_ref: Optional[str] = None
    hint: Optional[str] = None


@dataclass(frozen=True)
class Retired:
    at: str = ""
    reason: str = ""
    superseded_by: Optional[str] = None


@dataclass(frozen=True)
class Workload:
    id: str
    purpose: str
    placement: Placement
    schema_version: int = SCHEMA_VERSION
    scope: str = "user"
    title: Optional[str] = None
    #: Whose hat this run wears. A persona slug, `_shared`, `_infrastructure`,
    #: or None for UNDECIDED, which is a third state and not a synonym for
    #: either reserved answer.
    persona_ref: Optional[str] = None
    #: Which larger thing this run is a part of. A slug, `_standalone`, or None
    #: for UNDECIDED. Membership is carried, never derived: two runs belong
    #: together because both say so, not because their names rhyme.
    system: Optional[str] = None
    schedule: Schedule = field(default_factory=Schedule)
    execution: Execution = field(default_factory=Execution)
    response: Response = field(default_factory=Response)
    reconcile: ReconcileSpec = field(default_factory=ReconcileSpec)
    retired: Optional[Retired] = None
    learned_from: Optional[str] = None
    source_path: Optional[Path] = None
    raw: Mapping = field(default_factory=dict)
    #: False when the declaration carries no schedule block at all. The typed
    #: object is always present so no caller has to guard against None.
    has_schedule: bool = False

    @property
    def is_retired(self) -> bool:
        return self.retired is not None

    @property
    def is_bridge_owned(self) -> bool:
        return self.placement.owner == "bridge"

    @property
    def display_title(self) -> str:
        return self.title or self.id


# ── Loading ──────────────────────────────────────────────────────────────────

def _fail(source, detail, **fields):
    from .errors import DeclarationError

    raise DeclarationError(f"{source}: {detail}", source=str(source), **fields)


def _enum(raw, key_path, value, allowed, source):
    if value not in allowed:
        _fail(source, f"{key_path}: unknown value {value!r}, allowed: {', '.join(allowed)}")
    return value


def _mapping(value, key_path, source) -> dict:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        _fail(source, f"{key_path}: expected a mapping, found {type(value).__name__}")
    return dict(value)


def _tuple(value) -> tuple:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(value)
    return (value,)


def load_declaration(path: Path) -> Workload:
    """One declaration file in, one typed Workload out.

    Raises DeclarationError naming the file and the key path on unparseable
    YAML, an unsupported schema_version, an unknown enum value or an unknown
    top level key. Cross field rules are NOT checked here: that is validate().
    """
    path = Path(path)
    name = path.name
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        _fail(name, f"cannot be read: {exc}")
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        _fail(name, f"unparseable YAML: {str(exc).splitlines()[0]}")
    if not isinstance(raw, Mapping):
        _fail(name, "expected a mapping at the top level")

    unknown = [key for key in raw if key not in TOP_LEVEL_KEYS]
    if unknown:
        _fail(name, f"unknown top level key(s): {', '.join(sorted(unknown))}")
    if raw.get("schema_version") != SCHEMA_VERSION:
        _fail(name, f"schema_version: expected {SCHEMA_VERSION}, found {raw.get('schema_version')!r}")

    for required in ("id", "purpose", "placement"):
        if raw.get(required) in (None, ""):
            _fail(name, f"{required}: required and missing")

    scope = _enum(raw, "scope", raw.get("scope", "user"), SCOPES, name)
    placement = _placement(_mapping(raw.get("placement"), "placement", name), name)
    schedule_raw = raw.get("schedule")
    schedule = _schedule(_mapping(schedule_raw, "schedule", name), name)
    execution = _execution(_mapping(raw.get("execution"), "execution", name), name)
    response = _response(_mapping(raw.get("response"), "response", name), name)
    reconcile = ReconcileSpec(**_known(_mapping(raw.get("reconcile"), "reconcile", name),
                                       ("probe", "expect", "check_ref", "hint"),
                                       "reconcile", name))
    retired_raw = raw.get("retired")
    retired = None
    if retired_raw is not None:
        retired = Retired(**_known(_mapping(retired_raw, "retired", name),
                                   ("at", "reason", "superseded_by"), "retired", name))

    return Workload(
        id=str(raw["id"]),
        purpose=str(raw["purpose"]),
        placement=placement,
        schema_version=int(raw["schema_version"]),
        scope=scope,
        title=raw.get("title"),
        persona_ref=raw.get("persona_ref"),
        system=raw.get("system"),
        schedule=schedule,
        execution=execution,
        response=response,
        reconcile=reconcile,
        retired=retired,
        learned_from=raw.get("learned_from"),
        source_path=path,
        raw=dict(raw),
        has_schedule=schedule_raw is not None,
    )


def _known(mapping, allowed, key_path, source) -> dict:
    unknown = [key for key in mapping if key not in allowed]
    if unknown:
        _fail(source, f"{key_path}: unknown key(s): {', '.join(sorted(unknown))}")
    return {key: mapping[key] for key in allowed if key in mapping}


def _placement(raw, source) -> Placement:
    values = _known(raw, ("host", "kind", "runtime", "owner", "provisioned_at",
                          "interpreter", "privacy_grants", "port", "label_prefix"),
                    "placement", source)
    for required in ("host", "kind", "runtime", "owner"):
        if not values.get(required):
            _fail(source, f"placement.{required}: required and missing")
    return Placement(
        host=str(values["host"]),
        kind=_enum(raw, "placement.kind", values["kind"], KINDS, source),
        runtime=_enum(raw, "placement.runtime", values["runtime"], RUNTIMES, source),
        owner=_enum(raw, "placement.owner", values["owner"], OWNERS, source),
        provisioned_at=values.get("provisioned_at"),
        interpreter=values.get("interpreter"),
        privacy_grants=_tuple(values.get("privacy_grants")),
        port=values.get("port"),
        label_prefix=_label_prefix(values.get("label_prefix"), source),
    )


#: Reverse-DNS segments, the shape launchd and systemd both accept in a name.
#: Checked HERE and not only in the schema, because render is reachable with a
#: declaration nobody validated, and a malformed prefix would then put a broken
#: unit file on a machine instead of an error in a terminal.
_PREFIX_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*(\.[A-Za-z0-9][A-Za-z0-9_-]*)*$")


def _label_prefix(value, source) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        _fail(source, "placement.label_prefix: empty; omit the key instead of "
                      "declaring an empty prefix")
    if not _PREFIX_RE.match(text):
        _fail(source, f"placement.label_prefix: {text!r} is not a dotted name; "
                      "expected segments of letters, digits, hyphen or underscore, "
                      "for example com.example or org.example.scheduler")
    return text


def _schedule(raw, source) -> Schedule:
    values = _known(raw, ("rrule", "every_sec", "watch_paths", "at", "delivery_at",
                          "duration_estimate_min", "timezone", "appointments"),
                    "schedule", source)
    declared = _tuple(values.get("appointments"))
    if declared:
        appointments = tuple(
            Appointment(
                name=str(_mapping(entry, "schedule.appointments", source).get("name", "")),
                at=_mapping(entry, "schedule.appointments", source).get("at"),
                rrule=_mapping(entry, "schedule.appointments", source).get("rrule"),
                duration_estimate_min=_mapping(
                    entry, "schedule.appointments", source).get("duration_estimate_min"),
            )
            for entry in declared)
    elif values.get("rrule") or values.get("delivery_at"):
        # The shorthand is not a second data model. One unnamed appointment,
        # and every reader downstream sees the same shape either way.
        appointments = (Appointment(name="",
                                    at=values.get("delivery_at"),
                                    rrule=values.get("rrule"),
                                    duration_estimate_min=values.get("duration_estimate_min")),)
    else:
        appointments = ()
    return Schedule(
        rrule=values.get("rrule"),
        every_sec=values.get("every_sec"),
        watch_paths=_tuple(values.get("watch_paths")),
        at=values.get("at"),
        delivery_at=values.get("delivery_at"),
        duration_estimate_min=values.get("duration_estimate_min"),
        timezone=values.get("timezone"),
        appointments=appointments,
    )


def _execution(raw, source) -> Execution:
    values = _known(raw, ("command", "working_dir", "env", "timeout_sec", "isolation",
                          "single_flight", "on_timeout"), "execution", source)
    isolation = values.get("isolation", "process-group")
    on_timeout = values.get("on_timeout", "report")
    return Execution(
        command=_tuple(values.get("command")),
        working_dir=values.get("working_dir"),
        env=dict(values.get("env") or {}),
        timeout_sec=values.get("timeout_sec"),
        isolation=_enum(raw, "execution.isolation", isolation, ISOLATIONS, source),
        single_flight=bool(values.get("single_flight", True)),
        on_timeout=_enum(raw, "execution.on_timeout", on_timeout, ON_TIMEOUTS, source),
    )


def _response(raw, source) -> Response:
    values = _known(raw, ("evidence", "recipients", "notify_on", "notify_via",
                          "transient_exit_codes"),
                    "response", source)
    evidence = values.get("evidence")
    if evidence is not None:
        _enum(raw, "response.evidence", evidence, EVIDENCE, source)
    notify_on = _tuple(values.get("notify_on"))
    for item in notify_on:
        _enum(raw, "response.notify_on", item, NOTIFY_ON, source)
    recipients = []
    for entry in _tuple(values.get("recipients")):
        entry = _mapping(entry, "response.recipients", source)
        _known(entry, ("mandant", "person", "only_at"), "response.recipients", source)
        recipients.append(Recipient(mandant=str(entry.get("mandant", "")),
                                    person=entry.get("person"),
                                    only_at=_tuple(entry.get("only_at"))))
    transient = _tuple(values.get("transient_exit_codes"))
    for code in transient:
        if isinstance(code, bool) or not isinstance(code, int) or not 1 <= code <= 255:
            _fail(source, f"response.transient_exit_codes: {code!r} is not an exit code "
                          "from 1 to 255; 0 is success and never transient")
    return Response(evidence=evidence, recipients=tuple(recipients),
                    notify_on=notify_on, notify_via=values.get("notify_via"),
                    transient_exit_codes=transient)


def load_all(root: Path, cfg) -> list:
    """Every declaration under cfg.dir, sorted by id.

    One broken file fails the whole call. A silently skipped declaration is
    exactly how a run disappears without anyone noticing.
    """
    from .errors import DuplicateWorkloadId, IdFilenameMismatch

    folder = Path(root) / cfg.dir
    loaded = [load_declaration(path) for path in sorted(folder.glob("*.yaml"))
              if not path.name.startswith("_")]
    # Duplicates first: two files claiming one id is the more dangerous of the
    # two mistakes, because whichever loses is invisible rather than wrong.
    seen: dict = {}
    for workload in loaded:
        first = seen.get(workload.id)
        if first is not None:
            raise DuplicateWorkloadId(
                f"two declarations claim the id {workload.id!r}: "
                f"{Path(first.source_path).name} and {Path(workload.source_path).name}",
                id=workload.id)
        seen[workload.id] = workload
    for workload in loaded:
        name = Path(workload.source_path).name
        if workload.id != Path(workload.source_path).stem:
            raise IdFilenameMismatch(
                f"{name}: declares id {workload.id!r}, which does not match the filename",
                path=str(workload.source_path), id=workload.id)
    return [seen[key] for key in sorted(seen)]


# ── The hand written invariant gate ──────────────────────────────────────────

def _finding(source, key_path, detail, hint):
    from . import report

    return report.Finding(workload_id="", state=None, severity=Severity.high,
                          detail=f"{key_path}: {detail}", hint=hint,
                          source=source, key_path=key_path)


def collision_finding(*, source, key_path, detail, hint):
    """A cross-declaration finding, in the same shape as every other one.

    Public because it is raised from `cli`, which sees all declarations at
    once; `_finding` above is the module-private form for the per-declaration
    gate. Same constructor either way, so both read alike in one report.
    """
    return _finding(source, key_path, detail, hint)


def script_finding(*, source, key_path, detail, hint):
    """A finding about the FILE a declaration points at, in the same shape.

    Public for the same reason as `collision_finding`: it is raised from `cli`,
    which knows the repository root. `validate` below deliberately reads no
    file at all, and giving it one would mean giving it a root, a reachability
    and a deadline it has never had.
    """
    return _finding(source, key_path, detail, hint)


# An `exit 0` that no condition guards: at the start of the line, so an
# indented one inside an `if` or a function body is NOT this. That narrowness
# is the point. A finding here is meant to be true, not frequent.
_BARE_EXIT_ZERO = re.compile(r"^exit\s+0\s*(?:#.*)?$")


def ends_in_bare_exit_zero(text: str) -> bool:
    """Is the last line of this script an `exit 0` nothing can prevent?

    A run that promises to report its failure needs a return value that can
    carry one. A script ending this way returns zero however it went, the
    guard writes `verdict=ok`, and the notification that was declared can
    never fire. Measured on this instance: 441 of 441 runs since 2026-08-24
    carried `verdict=ok` and not one non-zero exit, while two of the wrappers
    behind them could not have produced one.

    WHAT THIS DOES NOT SEE, said here rather than discovered later. Of the four
    real cases repaired on 2026-08-26 it catches two. It misses a script that
    computes a return value and never uses it (the last line was `fi`), and one
    whose EXIT trap ends in `exit 0` and overwrites the value the last line
    had. Both are the same defect in a different shape, and both need their own
    predicate rather than a widened one: a rule that guesses is worse here than
    a rule that is silent, because the answer arrives while somebody is
    deciding whether to trust a report.
    """
    for line in reversed(text.splitlines()):
        stripped = line.rstrip()
        if not stripped.strip() or stripped.lstrip().startswith("#"):
            continue
        return bool(_BARE_EXIT_ZERO.match(stripped))
    return False


# ── The other two shapes of the same defect ──────────────────────────────────
#
# `ends_in_bare_exit_zero` above catches a script whose LAST line throws the
# return value away. Measured against the four real repairs of 2026-08-26 it
# catches two. The two below are the other two, and each needs its own
# predicate rather than a widened one: a rule that guesses is worse here than
# a rule that is silent, because its answer arrives while somebody is deciding
# whether to trust a report.
#
# All three are TEXT RULES and not analysis. They approximate control flow by
# position in a file, and every one of them is built to be silent where it
# cannot know. The corpus they were measured against is 85 shell scripts: the
# first shape has exactly one hit there and it is not a defect, the second has
# none.

#: `VAR=$?` on a line of its own, with the declaration keywords bash allows.
_CAPTURED_STATUS = re.compile(
    r"^[ \t]*(?:local[ \t]+|declare[ \t]+[-\w]+[ \t]+|typeset[ \t]+[-\w]+[ \t]+)?"
    r"[A-Za-z_][A-Za-z0-9_]*=\$\?[ \t]*(?:#.*)?$")

#: An exit that can carry something other than zero: a variable, `$?`, or a
#: literal that is not zero.
_LOUD_EXIT = re.compile(
    r"\bexit[ \t]+(?:\"?\$\{?[A-Za-z_][A-Za-z0-9_]*\}?\"?|\"?\$\?\"?|[1-9][0-9]*)\b")

#: The head of a shell function, in both spellings.
_FUNC_HEAD = re.compile(r"^[ \t]*(?:function[ \t]+)?([A-Za-z_][A-Za-z0-9_]*)[ \t]*\(\)[ \t]*\{")

#: `set -e` and friends. Only the minus form: `set +e` turns it OFF.
_ERREXIT = re.compile(r"^[ \t]*set[ \t]+(?:-[a-zA-Z]*e[a-zA-Z]*\b|-o[ \t]+errexit\b)")

#: `exec prog`. The process image is replaced, the child answers, and an exit
#: after it would be unreachable.
_EXEC = re.compile(r"^[ \t]*exec[ \t]+\S")

#: A `trap` line, and the handler plus the signal list it binds.
_TRAP = re.compile(r"^[ \t]*trap[ \t]+(?P<rest>.+?)[ \t]*$")
_TRAP_HEAD = re.compile(r"""^('[^']*'|"[^"]*"|\S+)[ \t]+(.*)$""")


def _naked(line: str) -> str:
    """A line without its comment.

    An earlier draft also cut `${...}` out before counting braces, on the
    reasoning that a one line function body could vanish into its own
    expansion. Measured across ninety real scripts and every historical
    version of the six repaired ones, that changed not a single answer, and a
    guard that never fires is a claim nobody can check. It was removed rather
    than kept as insurance: the comment above it described a scar this code
    never had.
    """
    return line.split("#", 1)[0]


def _effective(lines) -> list:
    """Lines that carry something: no blanks, no comments."""
    return [line for line in lines if line.strip() and not line.lstrip().startswith("#")]


def _function_bodies(text: str) -> dict:
    """name -> body lines, one nesting level deep.

    One level and not more, and that limit is stated rather than discovered:
    a function that calls a SECOND function with a loud exit is not seen, and
    the rule then reports a script that is in fact sound. It errs towards
    reporting rather than towards silence in exactly this one place, which is
    why the corpus was measured by hand before the rule was wired in.
    """
    lines = text.splitlines()
    out: dict = {}
    index = 0
    while index < len(lines):
        head = _FUNC_HEAD.match(lines[index])
        if not head:
            index += 1
            continue
        depth = _naked(lines[index]).count("{") - _naked(lines[index]).count("}")
        body = []
        cursor = index + 1
        if depth <= 0:                      # a one line function: `f() { ...; }`
            out[head.group(1)] = [lines[index]]
            index += 1
            continue
        while cursor < len(lines) and depth > 0:
            naked = _naked(lines[cursor])
            depth += naked.count("{") - naked.count("}")
            if depth > 0:
                body.append(lines[cursor])
            cursor += 1
        out[head.group(1)] = body
        index = cursor
    return out


def computes_a_status_it_can_never_return(text: str) -> bool:
    """Does this script catch a return value and then have no way to give it back?

    The shape a wrapper had until 2026-08-26: it ran a program, wrote the
    result into `EXIT_CODE`, printed a sentence about it, and ended on `fi`.
    Whatever happened, the script returned zero, the guard wrote `verdict=ok`,
    and the failure notification it had declared could never fire. 441 traces
    over three days, all `ok`, not one non-zero exit.

    THREE SILENCES, each of them a case where the rule cannot know:

    - `set -e`: the script then ends on the failing command itself, before the
      catch line is ever reached, and its return value is that command's.
    - `exec prog`: the process image is replaced and no later exit is reached.
    - a loud exit after the last catch, including one inside the body of a
      function that is called after it. One nesting level, stated above.
    """
    lines = text.splitlines()
    for line in lines:
        if _ERREXIT.match(line) or _EXEC.match(line):
            return False

    letzter = -1
    for index, line in enumerate(lines):
        if _CAPTURED_STATUS.match(line):
            letzter = index
    if letzter < 0:
        return False

    bodies = _function_bodies(text)
    loud_functions = {name for name, body in bodies.items()
                      if any(_LOUD_EXIT.search(_naked(b)) for b in body)}
    for line in lines[letzter + 1:]:
        naked = _naked(line)
        if _LOUD_EXIT.search(naked):
            return False
        if any(re.search(rf"\b{re.escape(name)}\b", naked) for name in loud_functions):
            return False
    return True


def an_exit_trap_overwrites_the_status(text: str) -> bool:
    """Does an EXIT trap end in a bare `exit 0` and eat what the script returned?

    The shape the bot wrapper had until 2026-08-26: its last line returned the
    child's value correctly, and a handler bound to EXIT ran afterwards and
    exited zero over the top of it. The script could not fail no matter how the
    run went, and the repair was to split the signal handler from the EXIT one.

    TWO SILENCES:

    - a handler bound only to SIGNALS. A stop on request is not a failure, and
      such a handler SHOULD end in zero. Told apart by the signal list of the
      trap line and never by the body, because widening it to every handler
      would forbid exactly the repair that was built.
    - a handler whose last statement is not an exit at all, so an `exit 0`
      somewhere inside it hangs on a condition and says nothing about how the
      handler ends.

    What it cannot know, and reports anyway: whether the trap is still armed
    when the script ends. A later `trap - EXIT` at the top level, or a second
    trap replacing the first, are invisible here.
    """
    bodies = _function_bodies(text)
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        trap = _TRAP.match(line.split("#", 1)[0].rstrip())
        if not trap:
            continue
        head = _TRAP_HEAD.match(trap.group("rest"))
        if not head:
            continue
        handler, signals = head.group(1), head.group(2).split()
        if not any(sig.strip("\"'").upper() in ("EXIT", "0") for sig in signals):
            continue
        body = bodies.get(handler.strip("\"'"))
        if body is None:
            # An inline handler: the whole thing is one string.
            inline = handler.strip("\"'")
            if _BARE_EXIT_ZERO.match(inline.split(";")[-1].strip()):
                return True
            continue
        effective = _effective(body)
        if not effective:
            continue
        # The indentation of the last statement is NOT consulted, unlike in the
        # rule for a whole file. Inside a body whose boundaries are already
        # known, the last statement is the last statement: for it to be indented
        # deeper than the first, some block would have to be unclosed, which is
        # not valid shell. An earlier draft did check, changed no answer across
        # ninety real scripts, and would have gone silent on a handler with
        # merely uneven indentation, which is the defect and not an exception.
        if _BARE_EXIT_ZERO.match(effective[-1].strip()):
            return True
    return False


def _check_label_prefix(placement, add) -> None:
    """A prefix is a dotted name, and BOTH gates have to say so.

    The parser refuses a malformed one at load time, which protects `render`.
    That is not enough here: the acceptance contract of this skill is that no
    declaration the schema refuses passes the hand written gate, because
    `provision.plan` asks THIS gate and never the schema, and a machine without
    check-jsonschema would otherwise follow the quiet one.

    An empty segment is the case worth naming: a leading or doubled dot makes a
    label launchd accepts and nobody can address afterwards, because every later
    call by the same name means a different thing.
    """
    value = placement.get("label_prefix")
    if value is None:
        return
    if not isinstance(value, str) or not value.strip():
        add("placement.label_prefix", "empty or not a string",
            "omit the key instead of declaring an empty prefix")
        return
    if not _PREFIX_RE.match(value.strip()):
        add("placement.label_prefix", f"{value!r} is not a dotted name",
            "segments of letters, digits, hyphen or underscore, joined by single "
            "dots, for example com.example or org.example.scheduler")


def _check_named_process(placement, add) -> None:
    """The client keeps its name, and does not lend it to the whole machine.

    Two rules over one field. The first holds for every workload: a versioned
    path is removed by the upgrade that creates its successor, so the unit
    starts nothing and says nothing. The second holds only where a privacy
    grant is declared, because that is the only case where the path is also an
    identity somebody answered a prompt about.
    """
    interpreter = placement.get("interpreter")
    grants = placement.get("privacy_grants")
    grants = tuple(grants) if isinstance(grants, (list, tuple)) else ((grants,) if grants else ())

    if isinstance(interpreter, str):
        found = VERSION_SEGMENT_PATTERN.search(interpreter)
        if found:
            segment = found.group(1)
            add("placement.interpreter",
                f"the path carries a version segment ({segment!r}), so it names "
                f"a file that is meant to be replaced",
                "point it at a path that does not move: a frozen copy under "
                "~/.local/bin, or a symlink target you control. The upgrade that "
                "installs the next version deletes this one, and on macOS it "
                "also orphans every privacy grant issued to this exact path")

    if not grants:
        return

    unknown = [g for g in grants if g not in PRIVACY_GRANTS]
    if unknown:
        add("placement.privacy_grants",
            f"{', '.join(map(repr, unknown))} is not a grant this system knows",
            "name the pane a human opens to give it, one of: "
            + ", ".join(PRIVACY_GRANTS))

    if not interpreter:
        add("placement.interpreter",
            "required when privacy_grants is declared, because a grant is "
            "issued to a client PATH and there is none here",
            "name the absolute path of the program the grant hangs on")
    elif interpreter in SHARED_INTERPRETERS:
        add("placement.privacy_grants",
            f"{interpreter} is shared by the whole machine, so granting it "
            f"grants {', '.join(grants)} to every program that runs there, not "
            f"to this workload",
            "give this workload its own copy at its own path and grant that "
            "one. A shared interpreter cannot hold a grant for a single caller")


def _check_unit_values(raw, placement, execution, add) -> None:
    """The shape of every declared value that reaches a generated file.

    Split out of `validate` so the list of places is readable as a list: each
    entry is a value some renderer writes into a unit file, a crontab line or
    the guard script, and every one of them is line based.
    """
    for key_path, value in (("title", raw.get("title")),
                            ("placement.interpreter", placement.get("interpreter")),
                            ("execution.working_dir", execution.get("working_dir"))):
        if value is None:
            continue
        reason = unsafe_reason(value)
        if reason:
            add(key_path, reason, "put the value on one line")

    command = execution.get("command")
    if isinstance(command, (list, tuple)):
        for index, item in enumerate(command):
            reason = unsafe_reason(item)
            if reason:
                add(f"execution.command[{index}]", reason, "put the argument on one line")

    # The three paths a SERVICE MANAGER is handed, and it hands them on to no
    # shell: nothing here expands a tilde and nothing resolves a name against a
    # login PATH. Only argv[0] is held to it -- the arguments after it carry
    # flags and values, and a rule over those would be a guess.
    for key_path, value in (("placement.interpreter", placement.get("interpreter")),
                            ("execution.working_dir", execution.get("working_dir"))):
        if value is None:
            continue
        if not ABSOLUTE_PATH_PATTERN.match(str(value)):
            add(key_path, f"{value!r} is not an absolute path",
                "a service manager starts the unit with no login shell, so a "
                "tilde stays a character and a relative path is resolved "
                "against whatever directory it happened to start in")
    if isinstance(command, (list, tuple)) and command:
        if not ABSOLUTE_PATH_PATTERN.match(str(command[0])):
            add("execution.command[0]", f"{command[0]!r} is not an absolute path",
                "PATH under a service manager is not a login PATH, so a bare "
                "name resolves to something else than it does in a terminal, "
                "or to nothing")

    schedule = raw.get("schedule") if isinstance(raw.get("schedule"), Mapping) else {}
    paths = schedule.get("watch_paths")
    if isinstance(paths, (list, tuple)):
        for index, item in enumerate(paths):
            reason = unsafe_reason(item)
            if reason:
                add(f"schedule.watch_paths[{index}]", reason, "put the path on one line")

    env = execution.get("env")
    if env is not None and not isinstance(env, Mapping):
        add("execution.env", f"expected a mapping, found {type(env).__name__}",
            "write it as name: value pairs")
        return
    for name in sorted(env or {}):
        if not ENV_NAME_PATTERN.match(str(name)):
            # The name is never quoted by anybody: it is written bare on the
            # left of `Environment=NAME=...` and bare on the left of a shell
            # assignment in the guard script, where anything that is not a name
            # is simply the next command.
            add("execution.env",
                f"{name!r} is not an environment variable name: it must match "
                f"{ENV_NAME_PATTERN.pattern}",
                "the name is written unquoted into a unit file and into a shell "
                "assignment, so it carries letters, digits and underscores only")
        elif str(name) in (MARKER_ENV_ID, MARKER_ENV_DIGEST):
            # Ownership is read back out of exactly these two variables. A
            # declaration that sets one of them is not configuring a run, it is
            # renaming who the running unit belongs to.
            add("execution.env",
                f"{name} is the ownership marker this skill reads back off the "
                f"machine, so a declaration must not set it",
                "choose another name; the marker says which declaration a live "
                "unit belongs to and is not a free variable")
        value = (env or {})[name]
        reason = unsafe_reason(value)
        if reason:
            add(f"execution.env.{name}", reason, "put the value on one line")
        elif not ENV_VALUE_PATTERN.match(str(value)):
            # Refused because it IS a value, not because it looks like a key.
            # The declaration is a tracked file, so a secret pasted here travels
            # verbatim into the unit on the machine AND into git. A secret typed
            # AS a locator is well formed and passes: this is a shape rule.
            add(f"execution.env.{name}",
                "a value, where only a reference may stand",
                "write a locator the process resolves itself: "
                "azure-keyvault://, keychain://, 1password://, op://, vault:// "
                "or file://")



#: Shape of an appointment name. The unit on the machine, its stamp and its
#: trace are all named `<label>.<name>`, so the name has to survive a file
#: system, a launchd label and a shell word without quoting.
APPOINTMENT_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,31}$")


def _check_appointments(schedule, response, add) -> None:
    """Several appointments in one declaration, and who belongs to which.

    Four rules, each of which was a way for the file to say something untrue:

    * ONE spelling per shape. A file carrying both `appointments` and the
      shorthand says two different things about when it fires, and a backend
      would pick one of them silently.
    * Every appointment is NAMED, and named uniquely. Two appointments sharing
      a name render to one unit file, where the second quietly replaces the
      first, and neither the report nor the machine would say so.
    * Every appointment carries its own time and its own recurrence. Inheriting
      one from the other reads as "the same" and is the first thing to drift
      when one of the two changes.
    * `only_at` names an appointment that exists. Pointed at a name nothing
      carries, a recipient gets nothing while the file still reads as though
      they were on the list.
    """
    schedule = schedule or {}
    appointments = schedule.get("appointments")
    names: list = []

    if appointments not in (None, "", [], {}):
        if not isinstance(appointments, (list, tuple)):
            add("schedule.appointments", "expected a list of appointments",
                "write one entry per time of day")
            appointments = ()
        for key in ("rrule", "delivery_at", "duration_estimate_min"):
            if schedule.get(key) not in (None, "", [], {}):
                add(f"schedule.{key}",
                    "a declaration carries EITHER the single-appointment "
                    "shorthand or the appointments list, never both",
                    f"delete schedule.{key}, or delete schedule.appointments")
        for index, entry in enumerate(appointments):
            where = f"schedule.appointments[{index}]"
            if not isinstance(entry, Mapping):
                add(where, "expected a mapping", "use name, at and rrule")
                continue
            name = entry.get("name")
            if name in (None, ""):
                add(f"{where}.name", "required",
                    "name the appointment; the unit, the stamp and the trace "
                    "are all named after it")
            elif not APPOINTMENT_NAME_PATTERN.match(str(name)):
                add(f"{where}.name", f"not a slug: {name!r}",
                    "lower case letters, digits and hyphens, starting with a letter")
            elif str(name) in names:
                add(f"{where}.name", f"duplicate appointment name {name!r}",
                    "two appointments with one name render to ONE unit file, "
                    "where the second silently replaces the first")
            if name not in (None, ""):
                names.append(str(name))
            for key in ("at", "rrule"):
                if entry.get(key) in (None, "", [], {}):
                    add(f"{where}.{key}", "required",
                        f"write {key} out for this appointment; inheriting it "
                        f"from another one is read as 'the same' and drifts")

    for index, entry in enumerate((response or {}).get("recipients") or ()):
        if not isinstance(entry, Mapping):
            continue
        only_at = entry.get("only_at")
        if only_at in (None, "", [], {}):
            continue
        if not names:
            add(f"response.recipients[{index}].only_at",
                "there are no named appointments for this to point at",
                "delete only_at, or declare schedule.appointments")
            continue
        for wanted in _tuple(only_at):
            if str(wanted) not in names:
                add(f"response.recipients[{index}].only_at",
                    f"no appointment named {wanted!r}; this recipient would get "
                    f"nothing while the file reads as though they were on the list",
                    f"use one of: {', '.join(names)}")


def validate(raw: Mapping, *, source: str) -> list:
    """The invariant gate, written by hand and independent of the JSON schema.

    Empty list means valid. Everything checked here is a cross field rule the
    loader deliberately does not enforce.
    """
    found: list = []

    def add(key_path, detail, hint):
        found.append(_finding(source, key_path, detail, hint))

    if not isinstance(raw, Mapping):
        add("<document>", "expected a mapping at the top level", "rewrite the file")
        return found

    placement = raw.get("placement") if isinstance(raw.get("placement"), Mapping) else {}
    schedule = raw.get("schedule") if isinstance(raw.get("schedule"), Mapping) else None
    execution = raw.get("execution") if isinstance(raw.get("execution"), Mapping) else {}
    response = raw.get("response") if isinstance(raw.get("response"), Mapping) else {}
    kind = placement.get("kind")
    owner = placement.get("owner")

    if raw.get("schema_version") != SCHEMA_VERSION:
        add("schema_version", f"expected {SCHEMA_VERSION}", "bump the declaration, not the skill")
    if not raw.get("id"):
        add("id", "required and missing", "give it the slug the filename carries")
    elif not ID_PATTERN.match(str(raw.get("id"))):
        # Not cosmetics. The id becomes a unit file name, a launchd label, a
        # systemd `Unit=` reference and a path element inside the guard script,
        # unquoted in all four. A space splits the reference, a slash writes the
        # file somewhere else, a quote or a dollar sign is read by the shell
        # that sources the guard.
        add("id", f"{raw.get('id')!r} is not a slug: it must match "
                  f"{ID_PATTERN.pattern}",
            "the id is written unquoted into unit names, labels and paths, so "
            "it carries lowercase letters, digits and hyphens and nothing else")
    if len(str(raw.get("purpose") or "")) < 8:
        add("purpose", "required, at least 8 characters",
            "one sentence on what this exists for")

    _check_label_prefix(placement, add)

    # Values that are written into a generated file, checked for the shapes
    # that do not survive being written there. A line break in any of them is
    # not escaped by the renderer, it becomes the next directive.
    _check_unit_values(raw, placement, execution, add)

    # The client keeps its name across an update, and keeps it to itself.
    _check_named_process(placement, add)

    # kind <-> schedule matrix
    wanted = SCHEDULE_FOR_KIND.get(kind)
    # A recurring run carries its recurrence EITHER in the shorthand `rrule` or
    # in `appointments`, one entry per time of day. Asking only for `rrule`
    # refused the list outright, which would have made the second spelling
    # unusable for the exact case it was written for.
    carries_appointments = bool(kind == "recurring" and schedule
                                and schedule.get("appointments"))
    if wanted:
        if not schedule:
            add("schedule", f"kind {kind} needs a schedule carrying {wanted}",
                f"add schedule.{wanted}")
        elif schedule.get(wanted) in (None, "", [], {}) and not carries_appointments:
            add(f"schedule.{wanted}", f"required for kind {kind}",
                f"add schedule.{wanted} or change the kind")
    if wanted and schedule:
        # The other half of the matrix above, and the half that was missing.
        # Requiring the right key never said the WRONG ones must be absent, so
        # a declaration could carry two triggers and read as neither.
        allowed = {wanted, *EXTRA_TRIGGER_FOR_KIND.get(kind, ())}
        for key in TRIGGER_KEYS:
            if key in allowed or schedule.get(key) in (None, "", [], {}):
                continue
            add(f"schedule.{key}",
                f"kind {kind} fires on {wanted}, so {key} is a second trigger",
                f"delete schedule.{key}, or declare the kind that fires on it")
    if kind in ("daemon", "agent") and schedule:
        add("schedule", f"kind {kind} runs continuously and must carry no schedule",
            "delete the schedule block or change the kind")
    if kind == "interval" and schedule and schedule.get("delivery_at") is not None:
        add("schedule.delivery_at",
            "a cadence job has no appointment, so delivery_at is meaningless here",
            "delete delivery_at, or declare it as kind recurring with an rrule")

    _check_appointments(schedule, response, add)

    # anything the Bridge owns AND executes needs a deadline and evidence
    if owner == "bridge" and kind in EXECUTED_KINDS:
        if not execution.get("command"):
            add("execution.command", "required for a bridge owned run", "name the argv")
        if not execution.get("timeout_sec"):
            add("execution.timeout_sec",
                "required for a bridge owned run: a run without a deadline can hang unbounded",
                "set a hard deadline in seconds")
        if not response.get("evidence"):
            add("response.evidence", "required for a bridge owned run",
                "declare what counts as proof this ran and landed")

    # A named evidence that nothing will produce.
    #
    # `required_guarantees` derives the trace from `notify_on`, so the guard
    # writes one only where somebody asked to be TOLD. But `evidence` answers
    # what the proof IS and `notify_on` answers who hears about it: two
    # questions on one switch. A declaration could therefore name `log-trace`,
    # ask for no notification, pass both gates, be provisioned, run, exit zero
    # and write nothing, and `reconcile` would call it in sync, because a trace
    # that was never written looks exactly like one nobody has read yet.
    #
    # Found on 2026-08-24 by building the refresher for the workload page,
    # which deliberately notifies about nothing because it sits on a laptop.
    #
    # The remedy is NOT an extra trace for every run: a file nobody reads is
    # cost without a reader, and that decision above stands. It is to break the
    # promise HERE, which is where the comment beside required_guarantees
    # already said this belonged.
    evidence = str(response.get("evidence") or "")
    if evidence in TRACE_BACKED_EVIDENCE:
        heard = set(response.get("notify_on") or ())
        if not (heard & TRACE_WRITING_NOTIFICATIONS):
            add("response.evidence",
                f"{evidence!r} is written by the guard only where response."
                f"notify_on asks about `missing` or `failure`; with neither, "
                f"nothing writes it and the declared proof never exists",
                "either add `missing` to response.notify_on, or say "
                "`exit-code`, which is what the service manager gives you "
                "for free")

    # recipients are references, never plaintext
    for index, entry in enumerate(response.get("recipients") or ()):
        if not isinstance(entry, Mapping):
            add(f"response.recipients[{index}]", "expected a mapping", "use mandant and person")
            continue
        # `only_at` is the third allowed key and the only one that is not a
        # reference to a person: it names appointments, and its own contents are
        # checked against the declared ones in _check_appointments. It has to be
        # listed here too, because this gate is what keeps a plaintext address
        # out, and a key it does not know is refused rather than ignored.
        extra = [key for key in entry if key not in ("mandant", "person", "only_at")]
        if extra:
            add(f"response.recipients[{index}]",
                f"unknown key(s) {', '.join(sorted(extra))}: a recipient is a reference, "
                f"never a plaintext address",
                "keep mandant and person, move the address into the mandant file")
        if not entry.get("mandant"):
            add(f"response.recipients[{index}].mandant", "required", "name the mandant slug")
        # The shape is what makes "a reference, never a plaintext address" true
        # rather than merely written down. A slug has no `@`, no dot, no space
        # and no capital, so an address, a number and a written-out name are
        # refused by the form and nothing guesses what a person looks like.
        for key, pattern in (("mandant", MANDANT_PATTERN), ("person", PERSON_PATTERN)):
            value = entry.get(key)
            if value is None:
                continue
            if not pattern.match(str(value)):
                add(f"response.recipients[{index}].{key}",
                    f"{value!r} is not a slug: it must match {pattern.pattern}",
                    f"name the {key} key and keep the address, the number and "
                    f"the person's name in the mandant file")

    # The hat is a REFERENCE into identity/personas/, so the same shape rule as
    # recipients: a written-out name has a space and a capital and is refused by
    # the form, without anything having to guess what a name looks like.
    persona = raw.get("persona_ref")
    if persona is not None and not PERSONA_PATTERN.match(str(persona)):
        add("persona_ref",
            f"{persona!r} is not a persona slug: it must match {PERSONA_PATTERN.pattern}",
            "name the slug under identity/personas/, or _shared / _infrastructure")

    # The system a run belongs to. Same shape rule, and deliberately no read:
    # a system of one is legitimate while the second half is still being built,
    # so "no other declaration names this" is not an error to raise here.
    system = raw.get("system")
    if system is not None and not SYSTEM_PATTERN.match(str(system)):
        add("system",
            f"{system!r} is not a system slug: it must match {SYSTEM_PATTERN.pattern}",
            "name the system this run is part of, or _standalone")

    # retiring means a reason, because a rename loses the why
    retired = raw.get("retired")
    if retired is not None:
        if not isinstance(retired, Mapping):
            add("retired", "expected a mapping with at and reason", "write both fields")
        else:
            if not retired.get("at"):
                add("retired.at", "required", "record when it was retired")
            if len(str(retired.get("reason") or "")) < 8:
                add("retired.reason", "required, at least 8 characters",
                    "record why, this outlives everyone's memory")

    return found


@dataclass(frozen=True)
class SchemaVerdict:
    """What the second, independent gate answered."""

    verdict: str
    detail: str = ""
    argv: tuple = ()


def validate_with_schema(path: Path, schema: Path, runner) -> SchemaVerdict:
    """The SECOND gate: an external validator, resolved on PATH, never hardcoded.

    An absent tool is reported as ``schema_validator_absent`` rather than
    skipped: a check nobody ran is not a green check.

    An absent SCHEMA is its own answer for the same reason, and it is checked
    FIRST. Handed a path that is not there, check-jsonschema fails to build a
    validator and exits non-zero, which read as ``invalid`` -- so a repository
    missing its contract reported EVERY declaration as refused, named a file
    inside somebody's virtualenv as the objection, and told the human to fix a
    declaration that was never read. The contract is this skill's own artefact,
    so its absence is named before a machine prerequisite is.
    """
    if not Path(schema).is_file():
        return SchemaVerdict(verdict="schema_missing",
                             detail=f"no declaration contract at {schema}")
    tool = shutil.which("check-jsonschema")
    if not tool:
        return SchemaVerdict(verdict="schema_validator_absent",
                             detail="check-jsonschema is not on PATH")
    argv = (tool, "--schemafile", str(schema), str(path))
    done = runner(list(argv), timeout_sec=60)
    rc = getattr(done, "rc", 1)
    if rc == 0:
        return SchemaVerdict(verdict="valid", argv=argv)
    return SchemaVerdict(verdict="invalid", argv=argv,
                         detail=(getattr(done, "stdout", "") or getattr(done, "stderr", "")))


# ── What the runtime has to supply ───────────────────────────────────────────

#: Evidence kinds that exist only because the guard writes a line for them.
#: Named once, because the gate and the guarantee derivation must agree about
#: which they are: two literals of the same set drift, and the drift here is
#: silent (a declaration promising proof that never appears).
TRACE_BACKED_EVIDENCE = frozenset({"log-trace", "delivery-receipt"})

#: The notifications whose answer can only come from that line.
TRACE_WRITING_NOTIFICATIONS = frozenset({"missing", "failure"})


def required_guarantees(w: Workload) -> frozenset:
    """What the declaration demands of whichever backend carries it."""
    required = set()
    if w.execution.timeout_sec:
        required.add(Guarantee.deadline)
    # `process_group_kill` exists to enforce a DEADLINE: it is what makes an
    # expired one kill the grandchildren too. A kind that never ends has no
    # deadline, so demanding it there demands the enforcement of a rule with no
    # trigger, and `backends/wrapper.py` says so in the other direction by
    # offering the guarantee only for a kind that ends. Requirement and
    # possibility were derived from two different facts, and the collision made
    # every daemon unprovisionable with a refusal that named the backend.
    if w.execution.isolation == "process-group" and w.placement.kind not in CONTINUOUS_KINDS:
        required.add(Guarantee.process_group_kill)
    if w.execution.single_flight:
        required.add(Guarantee.single_flight)
    # `missing` always, `failure` only where the declared evidence can carry it.
    #
    # The trace is the ONLY place a non zero run is written down, so a
    # declaration that asks to hear about failures is asking for the line that
    # records them. Tying this to `missing` alone meant a workload asking for
    # `failure` got no trace at all, and its failed run left nothing behind that
    # any reader could find. That was found by building the probe meant to prove
    # failures arrive: it wrote not a single line.
    #
    # Why `failure` is conditional and `missing` is not: a run that never happens
    # leaves nothing anywhere, so the trace is the only possible answer. A run
    # that failed at least left an exit code with the service manager. A
    # declaration that names `exit-code` as its evidence and still asks for
    # `failure` is asking for something its own evidence choice does not give,
    # and that contradiction belongs in validate, not in a silent extra
    # requirement here. It is not caught today.
    wants = set(w.response.notify_on or ())
    traceable = getattr(w.response, "evidence", "") in ("log-trace", "delivery-receipt")
    if "missing" in wants or ("failure" in wants and traceable):
        required.add(Guarantee.missing_detection)
    return frozenset(required)


# ── Digests ──────────────────────────────────────────────────────────────────

def _semantic(w: Workload) -> dict:
    return {
        "schema_version": w.schema_version,
        "scope": w.scope,
        "id": w.id,
        "placement": {
            "host": w.placement.host,
            "kind": w.placement.kind,
            "runtime": w.placement.runtime,
            "owner": w.placement.owner,
            "interpreter": w.placement.interpreter,
            "port": w.placement.port,
        },
        "schedule": {
            "rrule": w.schedule.rrule,
            "every_sec": w.schedule.every_sec,
            "watch_paths": list(w.schedule.watch_paths),
            "at": w.schedule.at,
            "delivery_at": w.schedule.delivery_at,
            "duration_estimate_min": w.schedule.duration_estimate_min,
            "timezone": w.schedule.timezone,
            # The normalised list, not the raw field, so the digest sees a
            # moved appointment whichever spelling the file used. Left out, a
            # report moved by six hours would read as no change at all.
            "appointments": [
                {"name": a.name, "at": a.at, "rrule": a.rrule,
                 "duration_estimate_min": a.duration_estimate_min}
                for a in w.schedule.appointments],
        },
        "execution": {
            "command": list(w.execution.command),
            "working_dir": w.execution.working_dir,
            "env": dict(w.execution.env),
            "timeout_sec": w.execution.timeout_sec,
            "isolation": w.execution.isolation,
            "single_flight": w.execution.single_flight,
            "on_timeout": w.execution.on_timeout,
        },
        "response": {
            "evidence": w.response.evidence,
            "recipients": [{"mandant": r.mandant, "person": r.person}
                           for r in w.response.recipients],
            "notify_on": list(w.response.notify_on),
            "notify_via": w.response.notify_via,
        },
        "reconcile": {
            "probe": w.reconcile.probe,
            "expect": w.reconcile.expect,
            "check_ref": w.reconcile.check_ref,
            "hint": w.reconcile.hint,
        },
        "retired": None if w.retired is None else {
            "at": w.retired.at,
            "reason": w.retired.reason,
            "superseded_by": w.retired.superseded_by,
        },
    }



def state_key(w, appointment=None) -> str:
    """What the state of ONE unit is filed under: `<id>`, or `<id>.<name>`.

    Every per-unit file goes through this one function: the ownership stamp,
    the guard script, the trace, the captured output, the expiry flag. One
    derivation, so they cannot drift apart, which is the failure this whole
    round was called on.

    The ownership MARKER deliberately does NOT use it. The marker answers
    "whose unit is this", and both appointments of a run belong to the same
    declaration; the state files answer "did THIS one happen", which is a
    different question for each of them.
    """
    name = getattr(appointment, "name", "") or ""
    return f"{w.id}.{name}" if name else str(w.id)


def canonical_payload(w: Workload) -> bytes:
    """Sorted key JSON over the SEMANTIC fields only.

    A retyped comment, a better title or a provision timestamp must never read
    as drift, so the cosmetic fields are excluded by construction.
    """
    return json.dumps(_semantic(w), sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def declaration_digest(w: Workload) -> str:
    return "sha256:" + hashlib.sha256(canonical_payload(w)).hexdigest()


# ── Surgical writes back into a declaration ──────────────────────────────────

_KEY_LINE = re.compile(r"^(?P<indent> *)(?P<dash>- +)?(?P<key>[A-Za-z_][A-Za-z0-9_]*):"
                       r"(?P<rest>.*)$")


def _render_value(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return json.dumps(list(value), ensure_ascii=False)
    return json.dumps(str(value), ensure_ascii=False)


def _split_comment(rest: str):
    """Value and trailing comment of one `key:` line, quote aware."""
    quotes = 0
    for index, char in enumerate(rest):
        if char in "\"'":
            quotes += 1
        if char == "#" and quotes % 2 == 0 and (index == 0 or rest[index - 1] in " \t"):
            return rest[:index], rest[index:]
    return rest, ""


def _set_value(line: str, value) -> str:
    """Replace the value on one `key:` line, keeping the trailing comment where
    it stood. A comment carries the why, so it survives every write."""
    match = _KEY_LINE.match(line)
    body, comment = _split_comment(match.group("rest"))
    rendered = _render_value(value)
    head = (f"{match.group('indent')}{match.group('dash') or ''}"
            f"{match.group('key')}: {rendered}")
    if not comment:
        return head
    return head + " " * max(1, len(body) - 1 - len(rendered)) + comment


def _find_key(lines, key, indent, start, end):
    for index in range(start, end):
        match = _KEY_LINE.match(lines[index])
        if match and match.group("dash") is None and match.group("key") == key \
                and len(match.group("indent")) == indent:
            return index
    return None


def _block_bounds(lines, index, indent):
    for candidate in range(index + 1, len(lines)):
        line = lines[candidate]
        if not line.strip():
            continue
        if len(line) - len(line.lstrip(" ")) <= indent:
            return index + 1, candidate
    return index + 1, len(lines)


def _child_indent(lines, start, end, fallback):
    for index in range(start, end):
        line = lines[index]
        if line.strip() and not line.lstrip().startswith("#"):
            return len(line) - len(line.lstrip(" "))
    return fallback


def patch_declaration(path: Path, key_path: tuple, value) -> None:
    """Rewrite exactly one value, keeping every comment and every other line.

    Refuses inside a flow style mapping (``placement: {host: ..., kind: ...}``),
    which several real declarations use: a line patcher cannot touch those
    safely, so the caller prints the snippet for a human instead.
    """
    from .errors import UnpatchableDeclaration

    path = Path(path)
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    dotted = ".".join(key_path)
    snippet = _snippet(key_path, value)
    start, end, indent = 0, len(lines), 0

    for depth, key in enumerate(key_path):
        index = _find_key(lines, key, indent, start, end)
        last = depth == len(key_path) - 1
        if index is None:
            if not last:
                raise UnpatchableDeclaration(
                    f"{path.name}: {dotted}: no block mapping named {key!r} to edit. "
                    f"Paste this by hand:\n{snippet}", path=str(path), key_path=dotted)
            lines.insert(end, " " * indent + f"{key}: {_render_value(value)}")
            break
        if last:
            lines[index] = _set_value(lines[index], value)
            break
        body, _ = _split_comment(_KEY_LINE.match(lines[index]).group("rest"))
        if body.strip().startswith(("{", "[")):
            raise UnpatchableDeclaration(
                f"{path.name}: {dotted}: {key!r} is written in flow style, which a line "
                f"patcher cannot edit without mangling the file. Paste this by hand:\n{snippet}",
                path=str(path), key_path=dotted)
        start, end = _block_bounds(lines, index, indent)
        indent = _child_indent(lines, start, end, indent + 2)

    path.write_text("\n".join(lines) + ("\n" if text.endswith("\n") else ""), encoding="utf-8")


def _snippet(key_path: tuple, value) -> str:
    out = []
    for depth, key in enumerate(key_path[:-1]):
        out.append("  " * depth + f"{key}:")
    out.append("  " * (len(key_path) - 1) + f"{key_path[-1]}: {_render_value(value)}")
    return "\n".join(out)


def write_retired(path: Path, at: str, reason: str, superseded_by=None) -> None:
    """Append the retired block. Presence of the block is what retired means."""
    from .errors import AlreadyRetired, ReasonTooShort

    path = Path(path)
    if len(str(reason or "").strip()) < 8:
        raise ReasonTooShort(reason=reason, minimum=8, path=str(path))
    text = path.read_text(encoding="utf-8")
    raw = yaml.safe_load(text) or {}
    if isinstance(raw, Mapping) and raw.get("retired") is not None:
        raise AlreadyRetired(
            f"{raw.get('id', path.stem)}: already carries a retired block "
            f"({raw['retired'].get('reason', 'no reason recorded')})",
            id=raw.get("id", path.stem))
    block = ["", "retired:", f"  at: {_render_value(at)}",
             f"  reason: {_render_value(reason)}"]
    if superseded_by:
        block.append(f"  superseded_by: {_render_value(superseded_by)}")
    path.write_text(text.rstrip("\n") + "\n" + "\n".join(block) + "\n", encoding="utf-8")


# ── Scaffolding a new declaration ────────────────────────────────────────────

#: Template values that name an instance, and the placeholder each becomes when
#: the caller supplied nothing. Nothing concrete is ever invented here.
_SCAFFOLD_PLACEHOLDERS = {
    "host": "<host>",
    "kind": "<kind>",
    "runtime": "<runtime>",
    "owner": "<owner>",
    "title": "<title>",
    "mandant": "<mandant-slug>",
    "person": "<person-key>",
}
_SCAFFOLD_FIELDS = ("id", "title", "purpose", "host", "kind", "runtime", "owner",
                    "command", "timeout_sec", "mandant", "person")
_UID_IN_TARGET = re.compile(r"(gui/)\d+(/)")
_VARIANT_LINE = re.compile(r"^(?P<indent> *)(?P<hash># *)?"
                           r"(?P<key>rrule|every_sec|watch_paths|at):")
_VARIANT_HINT = ("  # exactly one of rrule / every_sec / watch_paths / at, "
                 "matching the kind above")
#: An interval job has no appointment, so these two must not be scaffolded in.
_APPOINTMENT_KEYS = ("delivery_at", "duration_estimate_min")


def _in_schedule(line: str, inside: bool) -> bool:
    """True while the line belongs to the schedule block.

    Scoped on purpose: `at:` also appears inside the commented retired example,
    and pruning schedule variants there would eat a different block's lines.
    """
    if line.startswith("schedule:"):
        return True
    if inside and line.strip() and not line.startswith(" "):
        return False
    return inside


def _drop_or_keep(line: str, kind, out: list):
    """The schedule line to emit, or None when the declared kind rules it out."""
    wanted = SCHEDULE_FOR_KIND.get(kind)
    variant = _VARIANT_LINE.match(line)
    if variant:
        if variant.group("key") == wanted:
            return line.replace("# ", "", 1) if variant.group("hash") else line
        if wanted is None and _VARIANT_HINT not in out:
            out.append(_VARIANT_HINT)
        return None
    match = _KEY_LINE.match(line)
    if kind == "interval" and match and match.group("key") in _APPOINTMENT_KEYS:
        return None
    return line


def scaffold(id: str, root=None, **fields) -> str:
    """A new declaration text, built from the template, comments and all.

    Whatever the caller did not supply stays a visible placeholder. Inventing a
    host, a kind or a command would be a declaration nobody wrote.

    `root` is the repository the declaration is being written INTO. Without it
    the template was resolved from the skill's own location, so `declare --root
    <elsewhere>` wrote a file into one repository out of another repository's
    template -- and `--root` exists precisely for the case where those two are
    not the same tree.
    """
    from . import config
    from .errors import TemplateMissing

    base = Path(root) if root is not None else Path(config.find_repo_root())
    template = base / config.DEFAULT_DIR / "_template.yaml"
    if not template.exists():
        raise TemplateMissing(f"no declaration template at {template}", path=str(template))

    given = dict(fields)
    given["id"] = id
    kind = given.get("kind")
    out: list = []
    inside = False
    for line in template.read_text(encoding="utf-8").splitlines():
        inside = _in_schedule(line, inside)
        if inside:
            kept = _drop_or_keep(line, kind, out)
            if kept is None:
                continue
            line = kept
        match = _KEY_LINE.match(line)
        key = match.group("key") if match else None
        if key in _SCAFFOLD_FIELDS and key in given and given[key] is not None:
            line = _set_value(line, given[key])
        elif key in _SCAFFOLD_PLACEHOLDERS:
            line = _set_value(line, _SCAFFOLD_PLACEHOLDERS[key])
        out.append(_UID_IN_TARGET.sub(r"\1<uid>\2", line))
    return "\n".join(out) + "\n"
