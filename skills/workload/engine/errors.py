"""Exception tree for the workload skill.

Two properties make this file load bearing for every other module.

1. ``code`` is a stable kebab string. Tests assert on it, so a refusal for the
   wrong reason still fails. Never rename one to make a test pass; the code is
   the contract.
2. ``exit_code`` is where the process exit map lives, so the command line stays
   pure wiring. 2 = usage, config or declaration; 3 = refused by a guard;
   4 = unreachable or timed out. A timed out call is a REPORTED error and can
   therefore never share the clean run's 0.

Every error accepts either a finished message or a set of named fields, and
composes a message out of the fields when none was given. The fields also land
as attributes, so a caller can act on ``err.rc`` or ``err.argv`` without parsing
prose back out of a string.
"""

from __future__ import annotations

_MAX_FIELD_CHARS = 200


def _short(value) -> str:
    """One readable line for a field, however large the value is."""
    if isinstance(value, (list, tuple)):
        text = " ".join(str(item) for item in value)
    else:
        text = str(value)
    first = text.strip().splitlines()[0] if text.strip() else text
    if len(first) > _MAX_FIELD_CHARS:
        first = first[:_MAX_FIELD_CHARS] + "..."
    return first


class WorkloadError(Exception):
    """Base of the tree. Carries a code, an exit code and its named fields."""

    code = "workload-error"
    exit_code = 1
    summary = "workload error"

    def __init__(self, message=None, *, code=None, exit_code=None, **fields):
        self.fields = dict(fields)
        for key, value in self.fields.items():
            setattr(self, key, value)
        if code is not None:
            self.code = code
        if exit_code is not None:
            self.exit_code = exit_code
        self.message = message if message is not None else self._compose()
        super().__init__(self.message)

    def _compose(self) -> str:
        parts = [self.summary]
        parts.extend(f"{key}={_short(value)}" for key, value in self.fields.items())
        return ", ".join(parts)


# ── 2: usage, config, declaration ────────────────────────────────────────────

class ConfigError(WorkloadError):
    code = "config-invalid"
    exit_code = 2
    summary = "configuration is not usable"


class RepoRootNotFound(ConfigError):
    code = "repo-root-not-found"
    summary = "no repository root above the starting point"


class HostUnknown(ConfigError):
    code = "host-unknown"
    summary = "no such host in the remote inventory"


class DeclarationError(ConfigError):
    code = "declaration-invalid"
    summary = "declaration is not usable"


class DuplicateWorkloadId(ConfigError):
    code = "duplicate-workload-id"
    summary = "two declarations claim the same id"


class IdFilenameMismatch(ConfigError):
    code = "id-filename-mismatch"
    summary = "the id and the filename disagree"


class UnpatchableDeclaration(ConfigError):
    code = "unpatchable-declaration"
    summary = "this key cannot be edited in place"


class AlreadyRetired(ConfigError):
    code = "already-retired"
    summary = "the declaration is retired already"


class ReasonTooShort(ConfigError):
    code = "reason-too-short"
    summary = "a reason outlives everyone's memory and needs at least 8 characters"


class TemplateMissing(ConfigError):
    code = "template-missing"
    summary = "the declaration template is missing"


class CheckRefAmbiguous(ConfigError):
    code = "check-ref-ambiguous"
    summary = "a bare check id exists in more than one group"


class AmbiguousInventoryMatch(ConfigError):
    code = "ambiguous-inventory-match"
    summary = "the inventory entry matches more than one candidate"


class InvalidTimeout(ConfigError):
    code = "invalid-timeout"
    summary = "the deadlines are nested wrongly"


class HostFactsUnreadable(ConfigError):
    """The machine did not answer the three facts render must not guess.

    A `ConfigError` and not a `Refused`: nothing was refused, the reading did
    not happen. It has its own class because the failure it replaces exited
    ZERO with empty output, so no return code and no exception marked it, and
    the empty values travelled into the plan as if they had been read.
    """

    code = "host-facts-unreadable"
    summary = "the host did not answer uid, home and zone"


# ── 3: refused by a guard ────────────────────────────────────────────────────

class Refused(WorkloadError):
    code = "refused"
    exit_code = 3
    summary = "refused"


class AlarmWithoutMeasurement(Refused):
    code = "alarm-without-measurement"
    summary = "asked to raise an alarm while refusing to take the reading it rests on"


class Disabled(Refused):
    code = "disabled"
    summary = "the configuration switches this skill off"


class UnknownBackend(Refused):
    code = "unknown-backend"
    summary = "no backend is registered under that runtime"


class UnsupportedRuntime(Refused):
    code = "unsupported-runtime"
    summary = "this platform cannot carry that runtime"


class UnsupportedKind(Refused):
    code = "unsupported-kind"
    summary = "this backend cannot carry that kind"


class UnsupportedRecurrence(Refused):
    code = "unsupported-recurrence"
    summary = "this backend cannot express that recurrence, and an approximation is worse"


class UnsupportedTimezone(Refused):
    code = "unsupported-timezone"
    summary = "this backend runs in the machine's own zone only"


class NotProvisionable(Refused):
    code = "not-provisionable"
    summary = "declared so it is visible, never created from here"


class DispatcherNotConfigured(Refused):
    code = "dispatcher-not-configured"
    summary = "no dispatcher registry is configured"


class ElevationRequired(Refused):
    code = "elevation-required"
    summary = "this step needs elevation, so it is printed for a human instead of run"


class SymlinkedUnitPath(Refused):
    code = "symlinked-unit-path"
    summary = "the unit path is a symlink, which the service manager refuses"


class LockHeld(Refused):
    code = "lock-held"
    summary = "another session holds this workload"


class NothingToAdopt(Refused):
    code = "nothing-to-adopt"
    summary = "nothing live matches the declaration"


class DestinationNotOurs(Refused):
    code = "destination-not-ours"
    summary = ("that directory already belongs to something else, so publishing "
               "into it would either destroy its content or lose the page at the "
               "next sync")


class DestinationNotResolvable(Refused):
    code = "destination-not-resolvable"
    summary = ("the destination cannot be turned into a real path on that "
               "machine, and a tilde reaching a quoted shell word is the name "
               "of a directory rather than a home directory")


class PageTooLarge(Refused):
    code = "page-too-large"
    summary = ("a line of the page does not fit into one command line, and the "
               "connection would refuse it with an error that names neither the "
               "page nor the size")


class StepFailed(WorkloadError):
    code = "step-failed"
    exit_code = 1
    summary = "step failed"


# ── 4: unreachable or timed out ──────────────────────────────────────────────

class Unreachable(WorkloadError):
    code = "unreachable"
    exit_code = 4
    summary = "the host did not answer"


class StepTimeout(Unreachable):
    code = "step-timeout"
    summary = "the deadline expired, so the call was killed as a process group"
