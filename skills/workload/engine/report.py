"""Findings, and the two ways they are shown.

Surface discipline: a clean run prints ONE line. Every other line says what is
odd and what to do about it, in that order, because a monitoring line nobody
can act on trains everyone to ignore the next one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .model import Severity, WorkloadState

#: Which severities are worth an exit code of their own.
LOUD = (Severity.high, Severity.medium)

CLEAN_LINE = "clean: nothing found that needs a hand"


@dataclass(frozen=True)
class Finding:
    """One thing worth saying, and the repair that answers it."""

    workload_id: str = ""
    state: WorkloadState | None = None
    severity: Severity = Severity.info
    detail: str = ""
    hint: str = ""
    source: str = ""
    key_path: str = ""
    #: Which appointment of the run this is about, empty where the run has
    #: one. It is a FIELD and not a phrase inside `detail` because anything
    #: routing, dampening or counting per unit would otherwise have to take
    #: a sentence apart, and a sentence changes for a reader while a parser
    #: reading it breaks in silence.
    appointment: str = ""
    #: The run a `last_run_failed` is about, as the guard wrote it: exit code,
    #: the guard's own verdict (`expired` is a deadline, not the program saying
    #: no), seconds it ran, and its moment in UTC. Fields for the same reason
    #: `appointment` is one: the notifier renders "cut off by its time limit
    #: after 44 min, Tue 04:59" from them, and taking `detail` apart to get
    #: there would break in silence the day the sentence changes.
    rc: int | None = None
    verdict: str = ""
    duration_sec: int | None = None
    at: str = ""

    @property
    def state_value(self) -> str:
        return self.state.value if self.state is not None else "invalid"

    def __str__(self) -> str:
        head = f"{self.workload_id}: " if self.workload_id else ""
        tail = f" -> {self.hint}" if self.hint else ""
        return f"{head}{self.state_value}: {self.detail}{tail}"


@dataclass
class Report:
    findings: list = field(default_factory=list)
    header: str = ""
    #: What the machine's own traces said, keyed by workload id, as
    #: ``(stamp, rc)`` with the stamp exactly as the host wrote it (UTC).
    #:
    #: Not a finding, and deliberately not carried as one: a healthy run
    #: produces no finding at all, and that is precisely the run whose last
    #: firing a reader wants to see on a timeline. Plan drawn without it is the
    #: most confident possible picture of an unverified claim, in a skill whose
    #: whole premise is that declared state is not state.
    runs: dict = field(default_factory=dict)
    #: The last runs of each declaration, keyed by workload id, oldest first,
    #: as ``(stamp, rc, verdict, state_key)``.
    #:
    #: A separate field rather than a longer ``runs``: that one answers "when
    #: did it last fire", which every reader of this report already asks, and
    #: widening it would have changed the shape under all of them. This one
    #: answers "how has it been going", and the two questions have different
    #: answers for a run that failed twice and then succeeded.
    #:
    #: Capped where it is filled, not here. The page travels as one argument of
    #: a command line with a hard limit, and the trace files on the machine are
    #: never rotated, so an uncapped history fails on the host rather than in a
    #: test.
    history: dict = field(default_factory=dict)
    #: When each machine last came up, keyed by host slug, ISO UTC. Empty for a
    #: machine that would not say, and absent for one nobody asked.
    #:
    #: A report level fact rather than a finding, for the same reason `runs` is:
    #: a healthy machine produces no finding, and it is exactly the machine
    #: whose uptime a reader needs in order to know how much the silence on the
    #: page is worth. A page that says "nothing ran at 06:00" without saying
    #: "this box came up at 09:00" is technically true and read as an alarm.
    booted: dict = field(default_factory=dict)
    #: The directory the guard writes its trace and its captured output into,
    #: as configured. Carried so a renderer can NAME the log of a run without
    #: rebuilding the setting: two resolutions of one path drift, and a page
    #: printing a path nobody reads from is worse than a page printing none.
    #: Empty means nobody configured one, and nothing is then printed.
    state_dir: str = ""
    #: `{id: (program, where)}`: the program each declaration runs and whether
    #: it is this repository's own file, a copy of one, or a file that exists
    #: on one disk. Carried so the page can print the HEALTHY answer too: a
    #: column of "in this repository" is what makes the one exception legible.
    programs: dict = field(default_factory=dict)

    def __post_init__(self):
        """Nothing but a `Finding` survives construction.

        `provision.Outcome.findings` is a tuple of plain sentences, and a
        sentence has no `.severity`. Handed straight to this class it reached
        `by_severity` and raised `AttributeError`, so `provision --yes`
        answered a traceback on every path that had anything at all to report:
        a dry run, an elevation plan, a verify that did not confirm. The
        contract promises a report and an exit code of 1 there, and neither was
        reachable from the command line.

        The coercion is a BACKSTOP against that traceback, not a way to state a
        severity. A caller that means `high` builds a `Finding` and says so.
        """
        self.findings = notes(self.findings)

    @property
    def exit_code(self) -> int:
        return 1 if any(f.severity in LOUD for f in self.findings) else 0

    def by_severity(self) -> list:
        order = {Severity.high: 0, Severity.medium: 1, Severity.info: 2}
        return sorted(self.findings, key=lambda f: (order.get(f.severity, 3), f.workload_id))


def notes(messages, *, workload_id: str = "") -> list:
    """Plain sentences from a run, as findings. A `Finding` passes through.

    They become `info` deliberately. A sentence carries no severity claim, and
    inventing a loud one here would decide an exit code from prose. The commands
    that produce these decide their own exit from evidence: `provision` from
    whether the live object confirmed the change, never from this list.
    """
    return [m if isinstance(m, Finding) else
            Finding(workload_id=workload_id, state=WorkloadState.observed,
                    severity=Severity.info, detail=str(m))
            for m in messages]


#: What the second gate's answers mean here. `valid` is the only silence.
#: Everything else is a finding, INCLUDING the answer that the validator was
#: never installed: `--strict` whose gate did not run has not passed it, and a
#: line of prose over an exit code of 0 is exactly the green a check nobody ran
#: produces. The `invalid` row carries no state, which `Finding.state_value`
#: renders as `invalid` -- the same shape the hand written gate uses for a
#: declaration that was read and refused.
SCHEMA_VERDICTS = {
    "invalid": (Severity.high, None, "the schema gate refused it",
                "fix the declaration at the path check-jsonschema names"),
    "schema_validator_absent": (
        Severity.medium, WorkloadState.unknown, "the schema gate did not run",
        "install check-jsonschema, or drop --strict rather than read it as a pass"),
    #: The contract itself is gone. Deliberately NOT `invalid`: the declaration
    #: was never read, and saying it was refused sends a human to fix a file that
    #: is in order. It is the same severity as the absent tool, and for the same
    #: reason -- a gate that could not run has not passed.
    "schema_missing": (
        Severity.medium, WorkloadState.unknown, "there is no schema to check against",
        "restore the declaration contract; until it is back, --strict has nothing "
        "to hold a declaration to"),
}

#: An answer this module does not know is not a pass either.
UNKNOWN_VERDICT = (Severity.high, WorkloadState.unknown, "the schema gate answered",
                   "an answer this skill does not recognise is not a green gate")


def finding_for_schema_verdict(workload_id: str, verdict, *, source: str = ""):
    """One finding for one second-gate answer, or None when it said `valid`.

    This is where the second gate stops being decoration. It used to print its
    verdict and return None, so `validate --strict` exited 0 over a declaration
    the schema had refused, and did it two lines under the clean line.
    """
    name = getattr(verdict, "verdict", "")
    if name == "valid":
        return None
    severity, state, detail, hint = SCHEMA_VERDICTS.get(name, UNKNOWN_VERDICT)
    # One line per finding is the surface contract, and a validator that
    # answers in several lines would otherwise break the column silently.
    said = " ".join((getattr(verdict, "detail", "")
                     or (name if name not in SCHEMA_VERDICTS else "")).split())
    return Finding(workload_id=workload_id, state=state, severity=severity,
                   detail=f"{detail}: {said}" if said else detail,
                   hint=hint, source=source)


#: States that are counted rather than listed. On a real machine `unmanaged` is
#: dozens of entries per host, and a report nobody reads to the end trains
#: everyone to skip the line that mattered.
COUNTED_ONLY = (WorkloadState.unmanaged,)


def _with_header(rep: Report, body: str) -> str:
    """The header belongs to the answer, and most of all on the clean path.

    A green that does not say WHAT was looked at is a pass over an empty scan,
    which is the same failure as a check nobody ran. Dropping the header exactly
    when there is nothing to report is how ``validate`` came to say "clean" over
    zero declarations without once saying zero.
    """
    return f"{rep.header}\n{body}" if rep.header else body


def render_table(rep: Report, *, verbose: bool = False) -> str:
    """One line per finding, under the header that says what was covered.

    A clean report is the header plus a single line, and that is the whole
    point: silence is the normal case, but silence over nothing is not the same
    answer as silence over seventy four units.

    Without ``verbose`` the counted-only states are summarised in one line
    instead of listed. They are never dropped: a number that changes is still a
    signal, and hiding them entirely would be a different lie.
    """
    if not rep.findings:
        return _with_header(rep, CLEAN_LINE)
    lines = []
    counted = 0
    for finding in rep.by_severity():
        if not verbose and finding.state in COUNTED_ONLY:
            counted += 1
            continue
        lines.append(f"  {finding.severity.value:<6} {finding.state_value:<17} "
                     f"{finding.workload_id or finding.source}: {finding.detail}"
                     f"{('  -> ' + finding.hint) if finding.hint else ''}")
    if counted:
        lines.append(f"  info   {WorkloadState.unmanaged.value:<17} "
                     f"{counted} unit(s) on the machine that no declaration claims"
                     f"  -> pass --verbose to list them; this skill never touches them")
    if rep.header:
        lines.insert(0, rep.header)
    if not lines:
        return _with_header(rep, CLEAN_LINE)
    return "\n".join(lines)


def render_json(rep: Report) -> str:
    payload = {
        "header": rep.header,
        "exit_code": rep.exit_code,
        "findings": [
            {
                "workload_id": f.workload_id,
                "state": f.state.value if f.state is not None else None,
                "severity": f.severity.value,
                "detail": f.detail,
                "hint": f.hint,
                "source": f.source,
                "key_path": f.key_path,
            }
            for f in rep.by_severity()
        ],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False)
