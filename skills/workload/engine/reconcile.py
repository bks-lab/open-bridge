"""Is it still there? Asked of three sources, never of a declared status field.

The three sources are the declaration under ``workflow/workloads/``, the live
machine, and the ``services[]`` inventory of ``infra/remotes/<host>.yaml``.
A ``status:`` field is not among them on purpose: a declared state is never the
truth, the service manager is.

The module is strictly read only. It may propose an inventory patch; it never
applies one, and no step it runs may change anything on a machine.

``classify`` is pure, so the whole state machine is provable without a box.
Two verdicts carry the weight:

* ``retired_but_live``, a declaration marked retired whose unit is nonetheless
  running. The loudest thing this skill can say, because for one real
  declaration a start would be a security incident.
* ``unknown``, meaning an unreachable host, an expired probe, an expect nobody
  can evaluate, a placeholder nobody resolved. It must never collapse into
  ``absent``; that collapse is how seventeen jobs were once declared overdue
  when they were merely unobserved.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from engine import errors
from engine import inventory as inventory_mod
from engine import source as source_mod
from engine import model
from engine import probe as probe_mod
from engine import report as report_mod
from engine.backends import base as backend_base
from engine.errors import StepFailed, StepTimeout
from engine.report import Finding, Report

#: A run declared with one of these runtimes, or owned by anyone but the
#: Bridge, is documented so it is visible. It is never provisioned, never touched.
INERT_RUNTIMES = ("manual", "external")


@dataclass(frozen=True)
class LiveUnit:
    """One thing found ON the machine, whether the Bridge made it or not.

    ``marker_id`` is the ownership marker read back out of the unit itself. It
    is the second, independent signal beside the stamp on the host: two blind
    procedures that can only agree would prove nothing.
    """

    runtime: str
    unit_ref: str
    path: str | None = None
    marker_id: str | None = None
    marker_digest: str | None = None
    #: Whether the marker was actually READ, as opposed to never asked for.
    #: `launchctl list` and `systemctl list-timers` print no environment, so a
    #: unit that came out of enumeration alone carries None in `marker_id`
    #: because nobody looked, not because the marker is gone. Without this flag
    #: the two are one value, and the comparison has to guess: it guessed
    #: "absent", and every correctly provisioned run reported drift forever,
    #: with a repair hint that reproduced the same state on the next pass.
    #: cron and the dispatcher enumerate BY reading the file that carries the
    #: marker, so for them enumeration is observation and this is True.
    marker_observed: bool = False
    enabled: bool | None = None
    running: bool | None = None
    raw: str = ""


@dataclass(frozen=True)
class HostObservation:
    """What one machine answered, plus whether it answered at all."""

    host: str
    reachable: bool = True
    error: str | None = None
    live_units: tuple[LiveUnit, ...] = ()
    stamps: Mapping[str, Any] = field(default_factory=dict)
    #: The guard script's trace, keyed by workload id, raw. One line per run.
    #: Without reading it back, a run that failed and a run that never started
    #: are the same silence.
    traces: Mapping[str, str] = field(default_factory=dict)
    notes: tuple[str, ...] = ()
    #: Runtimes whose discovery could not be completed. A workload carried by
    #: one of them cannot be judged absent, only unknown.
    failed_runtimes: frozenset[str] = frozenset()
    #: When this machine last came up, in ISO UTC, or empty where it would not
    #: say. Read because an appointment that fell while the box was OFF left no
    #: line for a reason that has nothing to do with the run, and calling that
    #: `overdue` is a false accusation of the loudest kind this skill has.
    #: Empty changes nothing anywhere: every verdict treats an unknown boot
    #: exactly as it behaved before this field existed.
    booted_at: str = ""
    #: Which of the CLAIMED units sit in the service manager's persistent
    #: off-list, keyed by unit reference: True, False, or absent where nobody
    #: answered. Absent is not False, for the same reason `marker_observed`
    #: exists: not asked is not absent, and reading silence as permission is
    #: how a report claims health it never measured.
    disabled: Mapping[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Observation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _Claim:
    """What the inspection seam needs, and nothing else.

    Every backend's ``default_probe`` reads exactly one attribute off the
    artifact it is handed, and that is the unit reference. Passing a whole
    artifact here would mean rendering one, which needs the declaration, and
    observation deliberately does not have it: a host is observed for what it
    carries, never for what somebody meant it to carry.
    """

    unit_ref: str


def _read_markers(units, stamps, h, *, timeout_sec, runner, notes):
    """Ask the machine for the marker of every unit a stamp claims.

    Enumeration cannot carry it: `launchctl list` prints three columns and
    `systemctl list-timers` prints a schedule, and neither prints an
    environment. Only the units a stamp names are asked, so this costs one call
    per declared workload and never one per unit on the box.

    A unit that cannot be inspected keeps ``marker_observed`` False, and that is
    the whole point: not looking must never read as an absence.
    """
    from engine import backends

    claimed = {}
    for st in (stamps or {}).values():
        ref = _text(getattr(st, "unit_ref", ""))
        if ref:
            claimed[ref] = _name(getattr(st, "runtime", ""))
    if not claimed:
        return units

    out = []
    for unit in units:
        if unit.unit_ref not in claimed or unit.marker_observed:
            out.append(unit)
            continue
        backend = None
        for name, candidate in _backends_for(backends, ""):
            if name == (claimed[unit.unit_ref] or unit.runtime):
                backend = candidate
                break
        if backend is None or not hasattr(backend, "inspect_steps"):
            notes.append(f"{unit.runtime}: no way to read the marker of {unit.unit_ref}")
            out.append(unit)
            continue
        try:
            outs = [_run_step(runner, h, step, timeout_sec=timeout_sec)
                    for step in backend.inspect_steps(_Claim(unit_ref=unit.unit_ref), h)]
            seen = backend.parse_inspection(tuple(outs), unit.unit_ref)
        except (StepFailed, StepTimeout) as exc:
            notes.append(f"{unit.runtime}: could not read the marker of "
                         f"{unit.unit_ref} ({exc})")
            out.append(unit)
            continue
        except Exception as exc:                      # a backend that cannot read
            notes.append(f"{unit.runtime}: marker of {unit.unit_ref} unreadable ({exc})")
            out.append(unit)
            continue
        if seen is None:
            out.append(unit)
            continue
        out.append(replace(
            unit,
            marker_id=seen.marker_id,
            marker_digest=seen.marker_digest,
            marker_observed=bool(getattr(seen, "marker_observed", False)),
            path=unit.path or seen.path,
        ))
    return out



def read_traces(h, cfg, *, timeout_sec, runner=None) -> dict:
    """Every guard-script trace on the host, keyed by workload id. Read only.

    Same shape as the stamps: one shell step, everything at once, missing files
    are not an error. The guard script writes `<state_dir>/<id>.trace`, one line
    per run, and until this existed nothing ever read it back.
    """
    from engine import exec as exec_mod
    from engine import stamp as stamp_mod

    directory = stamp_mod.dir_expr(cfg.stamp_dir)
    script = (
        f'for f in {directory}/*.trace; do '
        '[ -f "$f" ] || continue; '
        'printf "==== %s\n" "${f##*/}"; cat "$f"; done 2>/dev/null || true'
    )
    step = model.Step(
        argv=("/bin/sh", "-c", script),
        purpose="read every run trace on the host",
        expect_rc=(),
    )
    out = _run_step(runner, h, step, timeout_sec=timeout_sec)
    text = getattr(out, "stdout", "") or ""
    traces: dict[str, str] = {}
    current = None
    for line in text.splitlines():
        if line.startswith("==== "):
            current = line[5:].strip()
            if current.endswith(".trace"):
                current = current[: -len(".trace")]
            traces[current] = ""
            continue
        if current is not None:
            traces[current] += line + "\n"
    return traces



#: Both platforms this skill carries, asked in one step, and PARSED HERE.
#:
#: The shell only fetches, and that is the whole point. Doing the extraction
#: there means a `sed` quoted through `sh -c` and then through ssh, and the
#: obvious pattern is wrong in a way that still returns a number: `.*sec *= *`
#: is greedy, so it walks past `sec` and matches the `usec` field. Measured on
#: two machines on 2026-08-27, where it returned 750092 and 149827, and both
#: look like a plausible epoch at a glance. The same expression in Python is
#: correct without any care at all, because `re.search` matches leftmost.
BOOT_TIME_SCRIPT = ("sysctl -n kern.boottime 2>/dev/null; "
                    "awk '/^btime/{print $2}' /proc/stat 2>/dev/null")


def read_boot_time(h, *, timeout_sec, runner=None) -> str:
    """When the machine last came up, in ISO UTC, or empty where it will not say.

    Empty is an honest answer and it changes nothing: every verdict that reads
    this behaves, without a boot moment, exactly as it did before there was
    one. A GUESSED boot time would be worse than none, because the guess that
    is cheap to make (assume it has been up forever) silences nothing while the
    other one (assume it just came up) silences every real alarm on a machine
    that never went down.

    macOS answers `{ sec = 1787577316, usec = 750092 } Mon Aug 24 15:15:16 2026`
    and Linux answers a bare integer. The word boundary is a belt rather than
    the guard: `re.search` matches leftmost, so the first `sec =` is already
    the right one, and the failure this is written against belongs to the
    shell. See `BOOT_TIME_SCRIPT`.
    """
    import re as _re
    from datetime import datetime, timezone

    step = model.Step(
        argv=("/bin/sh", "-c", BOOT_TIME_SCRIPT),
        purpose="read when this machine last came up",
        expect_rc=(),
    )
    try:
        out = _run_step(runner, h, step, timeout_sec=timeout_sec)
    except (StepFailed, StepTimeout, OSError):
        return ""
    text = getattr(out, "stdout", "") or ""
    found = _re.search(r"\bsec\s*=\s*(\d+)", text)
    if not found:
        found = _re.search(r"^\s*(\d{6,})\s*$", text, _re.M)
    if not found:
        return ""
    try:
        moment = datetime.fromtimestamp(int(found.group(1)), tz=timezone.utc)
    except (ValueError, OSError, OverflowError):
        return ""
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def observe_host(h, cfg, *, timeout_sec: int | None = None, runner=None) -> HostObservation:
    """Enumerate one machine read only: live units first, then the stamps.

    An unreachable host sets the flag and returns; it never raises, because one
    dead box must not abort a report about the other five.
    """
    # Imported here, not at module import: a backend's parse_discovery builds
    # LiveUnit from this module, so a top-level import would close the cycle.
    from engine import backends

    timeout_sec = timeout_sec or getattr(cfg, "step_timeout_sec", 60)
    platform = _name(getattr(h, "platform", ""))
    slug = _name(getattr(h, "slug", "")) or "local"

    units: list[LiveUnit] = []
    notes: list[str] = []
    failed: set[str] = set()
    seen: set[tuple[str, str]] = set()

    for name, backend in _backends_for(backends, platform):
        try:
            steps = tuple(backend.discover_steps(h))
        except Exception as exc:                      # a backend that cannot look
            failed.add(name)
            notes.append(f"{name}: no discovery ({exc})")
            continue
        outs = []
        try:
            for step in steps:
                if getattr(step, "requires_elevation", False):
                    # No sudo, ever. What needs elevation is reported, not run.
                    notes.append(f"{name}: skipped a step that needs elevation")
                    continue
                outs.append(_run_step(runner, h, step, timeout_sec=timeout_sec))
        except StepTimeout as exc:
            return HostObservation(host=slug, reachable=False, error=str(exc),
                                   notes=tuple(notes))
        except StepFailed as exc:
            failed.add(name)
            notes.append(f"{name}: discovery failed ({exc})")
            continue
        try:
            found = backend.parse_discovery(tuple(outs)) or []
        except Exception as exc:
            failed.add(name)
            notes.append(f"{name}: discovery output could not be read ({exc})")
            continue
        for unit in found:
            key = (_name(unit.runtime), unit.unit_ref)
            if key in seen:
                continue
            seen.add(key)
            units.append(unit)

    stamps: Mapping[str, Any] = {}
    try:
        from engine import stamp as stamp_mod

        stamps = stamp_mod.read_stamps(h, cfg, timeout_sec=timeout_sec, runner=runner) or {}
    except StepTimeout as exc:
        return HostObservation(host=slug, reachable=False, error=str(exc),
                               live_units=tuple(units), notes=tuple(notes))
    except (StepFailed, OSError) as exc:
        notes.append(f"stamps: could not be read ({exc})")

    units = _read_markers(units, stamps, h, timeout_sec=timeout_sec,
                          runner=runner, notes=notes)

    traces: Mapping[str, str] = {}
    try:
        traces = read_traces(h, cfg, timeout_sec=timeout_sec, runner=runner) or {}
    except StepTimeout as exc:
        notes.append(f"traces: could not be read ({exc})")
    except (StepFailed, OSError) as exc:
        notes.append(f"traces: could not be read ({exc})")

    # Last, and never fatal: a machine that will not say when it came up is
    # still a machine worth reporting on, and the verdicts fall back to what
    # they said before this was read.
    booted = read_boot_time(h, timeout_sec=timeout_sec, runner=runner)

    # Same rule, same place: read last, never fatal, and about the units a
    # stamp claims rather than everything the box carries.
    off_list = read_disabled(h, stamps, timeout_sec=timeout_sec,
                             runner=runner, notes=notes)

    return HostObservation(host=slug, reachable=True, error=None,
                           live_units=tuple(units), stamps=dict(stamps),
                           traces=dict(traces), booted_at=booted,
                           disabled=dict(off_list),
                           notes=tuple(notes), failed_runtimes=frozenset(failed))


def _backends_for(backends, platform: str):
    """Every distinct backend that can carry something on this platform."""
    out = []
    seen = set()
    for name, backend in sorted(getattr(backends, "BACKENDS", {}).items()):
        if id(backend) in seen:
            continue
        platforms = {_name(p) for p in getattr(backend, "platforms", ()) or ()}
        if platform and platforms and platform not in platforms:
            continue
        seen.add(id(backend))
        out.append((name, backend))
    return out


def _run_step(runner, h, step, *, timeout_sec: int):
    """One read-only step against a host, under a deadline (rule 1)."""
    if runner is not None:
        return runner(step, timeout_sec=getattr(step, "timeout_sec", None) or timeout_sec)

    from engine import exec as execution

    return execution.run_step(step, h, default_timeout_sec=timeout_sec)


# ---------------------------------------------------------------------------
# The state machine
# ---------------------------------------------------------------------------

#: How many declared cadences may pass without a line before a run counts as
#: overdue. Two, deliberately generous: the trace stamp comes from the host and
#: the comparison happens here, so a little clock skew must never raise an alarm.
OVERDUE_CADENCES = 2


#: How many runs of one declaration the history carries, newest kept.
#:
#: A number rather than "all of them", for two reasons that both bite on the
#: machine and not in a test: the rendered page travels as ONE argument of a
#: command line under a hard size limit, and the guard never rotates a trace
#: file, so a five minute poller had 441 lines after three days on a real
#: machine. Twenty four is a day of such a poller and months of a daily
#: report, which is the span a reader actually looks back over.
STRIP_MAX = 24


def read_disabled(h, stamps, *, timeout_sec, runner=None, notes=None) -> dict:
    """Which claimed units the machine will refuse to start. Read only.

    Driven by the STAMPS and not by what is loaded, which is the difference
    between covering one case and covering both. A unit can be loaded AND on
    the list, which runs now and never comes back after a reboot; and a unit
    can be booted out AND on the list, which is reported as `absent` with a
    hint to provision it again that `provision` then refuses, for the very
    reason nothing here had read. The second one is not in `launchctl list` at
    all, so a read driven by live units would answer about the first case only.

    Only what a stamp claims, for the same reason as `_read_markers`: a real
    machine answers with a thousand units nobody here declared, and asking
    about all of them would turn one question into a thousand.

    The answer is memoised BY THE ARGV, which is what makes one implementation
    correct for two runtimes without either having to describe itself. launchd
    keeps the list per domain, so its question is identical for every unit in
    that domain and is asked once; systemd keeps it per unit, so its question
    differs and each one is asked. Identical questions are asked once.

    Never raises. One unreadable fact must not abort a report about everything
    else on the box, and an unread list stays ABSENT rather than False.
    """
    from engine import backends

    claimed = {}
    for st in (stamps or {}).values():
        ref = _text(getattr(st, "unit_ref", ""))
        if ref:
            claimed[ref] = _name(getattr(st, "runtime", ""))
    if not claimed:
        return {}

    known = dict(_backends_for(backends, ""))
    answers: dict[str, Any] = {}
    seen: dict[tuple, Any] = {}
    for ref, runtime in claimed.items():
        backend = known.get(runtime)
        if backend is None or not hasattr(backend, "disabled_list_steps"):
            continue
        try:
            steps = tuple(backend.disabled_list_steps(_Claim(unit_ref=ref), h))
        except Exception:                              # a backend that cannot ask
            continue
        if not steps:
            continue
        key = tuple(tuple(step.argv) for step in steps)
        if key not in seen and any(getattr(s, "requires_elevation", False) for s in steps):
            # No sudo, ever, and the same rule `observe_host` and `provision`
            # apply: what needs elevation is noted, not run. Raised instead, it
            # took the whole host's report down for one entry (#179).
            if notes is not None:
                notes.append(f"{runtime}: the persistent off-list of {ref} "
                             f"needs elevation to read, so it was not read")
            seen[key] = None
        if key not in seen:
            try:
                seen[key] = tuple(
                    _run_step(runner, h, step, timeout_sec=timeout_sec)
                    for step in steps)
            except (StepFailed, StepTimeout, OSError) as exc:
                if notes is not None:
                    notes.append(f"{runtime}: the persistent off-list of "
                                 f"{ref} could not be read ({exc})")
                seen[key] = None
        outs = seen[key]
        if outs is None:
            continue
        try:
            verdict = backend.parse_disabled(outs, ref)
        except Exception:
            continue
        if verdict is not None:
            answers[ref] = verdict
    return answers


#: How the host is asked for a digest. Two spellings, because macOS ships
#: `shasum` and most Linuxes ship `sha256sum`, and asking for both in one line
#: costs nothing while a wrong guess costs the whole answer. Output is
#: `<digest>  <path>` either way, which is what the parser reads.
PROGRAM_DIGEST_TOOL = "shasum -a 256 %s 2>/dev/null || sha256sum %s 2>/dev/null"


def read_program_digests(h, workloads, *, timeout_sec, runner=None, notes=None) -> dict:
    """The digest of every program these declarations name, ON THE HOST.

    One step for all of them: the paths are few (one per declaration, and most
    declarations share none), and a call per program would be a round trip per
    run on a machine reached over ssh.

    A file that is not there answers nothing and is simply absent from the
    result. Never raises: one unreadable fact must not abort a report about
    everything else on the box.
    """
    from engine import exec as exec_mod
    from engine import source as source_mod

    paths = sorted({source_mod.program_of(w) for w in (workloads or ())
                    if not getattr(w, "is_retired", False)} - {""})
    if not paths:
        return {}
    quoted = " ".join(exec_mod.sh_quote(p) for p in paths)
    step = model.Step(
        argv=("/bin/sh", "-c", PROGRAM_DIGEST_TOOL % (quoted, quoted)),
        purpose="read the digest of every program these declarations name",
        expect_rc=(),
    )
    try:
        out = _run_step(runner, h, step, timeout_sec=timeout_sec)
    except (StepFailed, StepTimeout, OSError) as exc:
        if notes is not None:
            notes.append(f"programs: their digests could not be read ({exc})")
        return {}
    found = {}
    for line in (getattr(out, "stdout", "") or "").splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and len(parts[0]) == 64:
            found[parts[1].strip()] = parts[0].strip()
    return found


def _traces_of(w, obs) -> dict:
    """Every trace this declaration writes, keyed by its state key.

    A run with two appointments writes TWO files, and NEITHER of them is
    called `<id>.trace`: the guard names them after the state key, which is
    `<id>.<appointment>`. Reading the bare id therefore found nothing at all
    for such a run. It was visible on the page and had been for days: every
    scheduled job carried a diamond for its last firing, and the one with two
    appointments carried two rings and no diamond, which reads as a run that
    has never fired rather than one nobody looked up.
    """
    from engine.backends import base as base_mod

    out = {}
    for appointment in (base_mod.appointments_of(w) or (None,)):
        key = model.state_key(w, appointment)
        out[key] = (obs.traces or {}).get(key, "") or ""
    return out


def _trace_strip(texts: dict) -> tuple:
    """The last runs across every appointment, oldest first, newest kept.

    Each entry is `(stamp, rc, verdict, state_key)`. The state key rides along
    because a run with two appointments produces one strip out of two files,
    and "the 06:30 one failed" is a different sentence from "it failed".

    The verdict is taken from the line rather than derived from `rc`. The guard
    writes four of them and `expired` is not the same fact as a non zero
    return: one says a deadline cut the run off, the other says the program
    said no. Rebuilding it here would be a second derivation of something the
    machine already stated, which is the mistake this skill keeps finding.
    """
    from datetime import datetime, timezone

    entries = []
    for key, text in (texts or {}).items():
        for line in (text or "").splitlines():
            parts = line.split()
            if len(parts) < 3 or not parts[1].startswith("workload="):
                continue
            try:
                when = datetime.strptime(parts[0], "%Y-%m-%dT%H:%M:%SZ").replace(
                    tzinfo=timezone.utc)
            except ValueError:
                continue
            rc, verdict = None, ""
            for token in parts:
                if token.startswith("rc="):
                    try:
                        rc = int(token[3:])
                    except ValueError:
                        rc = None
                elif token.startswith("verdict="):
                    verdict = token[len("verdict="):]
            entries.append((when, rc, verdict, key))
    entries.sort(key=lambda e: e[0])
    kept = entries[-STRIP_MAX:]
    return tuple((w.strftime("%Y-%m-%dT%H:%M:%SZ"), rc, verdict, key)
                 for w, rc, verdict, key in kept)


def _newest_trace(text: str):
    """The last line the guard script wrote, as (when, rc), or None.

    Format, written by wrapper.trace():
        2026-08-23T08:00:00Z workload=<id> rc=<n> duration_sec=<n> verdict=<x>
    """
    from datetime import datetime, timezone

    newest = None
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) < 3 or not parts[1].startswith("workload="):
            continue
        rc = None
        for token in parts:
            if token.startswith("rc="):
                try:
                    rc = int(token[3:])
                except ValueError:
                    rc = None
                break
        try:
            when = datetime.strptime(parts[0], "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc)
        except ValueError:
            continue
        if newest is None or when >= newest[0]:
            newest = (when, rc)
    return newest


def _transient_blip(w, text: str) -> bool:
    """True when the newest run failed with a code the declaration calls
    transient AND the run before it was clean.

    Added 2026-09-26: suppliers that end with 75 when GitHub is briefly
    unreachable rang a phone for every blip, although the next tick went
    through. Only the named codes, only the program's own `failed` verdict
    (an `expired` run was cut off by a deadline, that is not a retry request),
    and only with a clean run right before it. A second failure in a row, a
    first run without history, and every code not named keep speaking at once.
    """
    response = getattr(w, "response", None)
    codes = tuple(getattr(response, "transient_exit_codes", ()) or ()) if response else ()
    if not codes:
        return False
    runs = [(when, rc, verdict) for when, rc, verdict, _ in _trace_strip({"_": text})]
    if len(runs) < 2:
        return False
    (_, rc_before, _), (_, rc_newest, verdict_newest) = runs[-2], runs[-1]
    return rc_newest in codes and verdict_newest == "failed" and rc_before == 0


def _notify_on(w) -> tuple:
    response = getattr(w, "response", None)
    return tuple(getattr(response, "notify_on", ()) or ()) if response else ()


def _cadence_sec(w):
    """The declared cadence, or None when the declaration does not state one.

    Only `interval` states it outright. A recurring run carries an RRULE, and
    working out its previous firing needs an engine this skill deliberately does
    not carry: the recurrence belongs to the dispatcher, not to the provisioner.
    Returning None here is what makes the difference between "not overdue" and
    "cannot say", and those two must never be printed the same way.
    """
    if _kind_of(w) != "interval":
        return None
    schedule = getattr(w, "schedule", None)
    every = getattr(schedule, "every_sec", None) if schedule is not None else None
    return int(every) if every else None


#: States in which the run's own trace is not worth a second sentence, and the
#: states in which it is. Split out and named because the decision used to live
#: inside one `if` as four members, which reads as a list of examples rather
#: than a decision about all sixteen. A state added to the enum then joined the
#: JUDGED side by default and in silence -- which is exactly how a workload that
#: had been deliberately retired came to be reported as `high overdue` for a run
#: nobody wanted.
#:
#: `test_every_state_decides_whether_the_trace_speaks` holds the two sets
#: together and against the enum, so a seventeenth state cannot be added without
#: someone answering this question for it.
TRACE_SAYS_NOTHING_IN = frozenset({
    model.WorkloadState.absent,             # the absence IS the story
    model.WorkloadState.not_provisioned,    # there is nothing to have run
    model.WorkloadState.unknown,            # nobody read the machine
    model.WorkloadState.retired_but_live,   # the loud finding is already the right one
    model.WorkloadState.orphan_stamp,       # no declaration to judge against
    model.WorkloadState.unmanaged,          # not ours; we do not read its runs
    model.WorkloadState.inventory_missing,  # a bookkeeping gap, not a run
    model.WorkloadState.inventory_stale,    # ditto, and about the file not the run
    model.WorkloadState.intentionally_absent,  # ditto, and the file explains itself
    model.WorkloadState.observed,           # documented, never executed by us
    model.WorkloadState.grant_orphaned,     # the grant is the story; the empty result follows from it
})

#: The other side of the same decision, spelled out rather than derived, so the
#: two are compared instead of one being defined as "the rest".
TRACE_SPEAKS_IN = frozenset({
    model.WorkloadState.in_sync,            # in sync AND its last run failed is a real pair
    model.WorkloadState.stopped,            # it should be up; what did its last run say
    model.WorkloadState.drifted,            # the bytes moved; the runs still matter
    model.WorkloadState.unstamped,          # ours by marker, and still running
    # Never a primary state today: the off-list is read ALONGSIDE `in_sync`,
    # because the bytes really do match and that is a separate fact. The answer
    # is nevertheless "speaks": what a unit wrote before somebody switched it
    # off is still its record, and the one thing the trace must not do here is
    # call it late, which the off-list guard handles on its own.
    model.WorkloadState.disabled,
    # Never a primary state either: it is a fact about a FILE beside the run,
    # and the run's own record is untouched by it. If it ever became primary,
    # the trace is exactly what a reader would want next.
    model.WorkloadState.source_drift,
    model.WorkloadState.last_run_failed,    # produced BY the trace
    model.WorkloadState.overdue,            # produced BY the trace
})


def _grant_findings(w, stamp, finding):
    """Did the client path move out from under the grant.

    Only ever asked where the declaration says a grant is needed. Everywhere
    else a renamed interpreter is ordinary drift, which the digest already
    reports, and saying it twice in different words would read as two problems.
    """
    grants = tuple(getattr(w.placement, "privacy_grants", ()) or ())
    if not grants or stamp is None:
        return []

    state, sev = model.WorkloadState, model.Severity
    declared = w.placement.interpreter
    stamped = getattr(stamp, "interpreter", None)

    if stamped is None:
        # Said out loud rather than passed over. A stamp written before this
        # field existed holds no answer, and silence here is indistinguishable
        # from "unchanged" -- the same collapse marker_observed was added to
        # end. The repair is cheap and is named.
        return [finding(
            state.unknown, sev.info,
            f"{w.id} declares {', '.join(grants)}, and its stamp predates the "
            f"field that records the client path, so this cannot tell whether "
            f"the grant still sits on the path that runs",
            "re-provision once to record it, or check the grant by hand in "
            "System Settings, Privacy & Security",
            source="machine")]

    if not declared or declared == stamped:
        return []

    return [finding(
        state.grant_orphaned, sev.high,
        f"{w.id} now runs {declared}, but it was provisioned as {stamped} and "
        f"the {', '.join(grants)} grant still sits on {stamped}",
        f"grant {', '.join(grants)} to {declared} in System Settings, Privacy & "
        f"Security. Until then the run is not denied, it is shown nothing, which "
        f"arrives as an empty result rather than an error",
        source="machine")]



#: How long past an appointment a run may still be running before its silence
#: means anything. Added to the declared deadline rather than replacing it: a
#: run due at 06:30 with an hour of deadline cannot be called missing before
#: 07:30, because until then it may legitimately still be working. The margin
#: on top covers launchd's own scheduling slop and a machine that woke late.
OVERDUE_GRACE_SEC = 600



def _appointment_of(w, stamp):
    """The appointment a unit answers, from its state key. None where there is
    only one, which is the case the rest of the code already handles."""
    appointments = backend_base.appointments_of(w)
    if len(appointments) <= 1:
        return appointments[0] if appointments else None
    key = str(getattr(stamp, "state_key", "") or "")
    name = key[len(str(w.id)) + 1:] if key.startswith(f"{w.id}.") else ""
    for appointment in appointments:
        if appointment.name == name:
            return appointment
    return None


def _appointment_overdue(w, appointment, newest, stamp, now, finding, booted=None,
                         switched_off=False):
    """Did this appointment happen. Empty when the question cannot be answered.

    Four ways it stays silent, and each is a different fact:
      * the recurrence is outside the translated subset, so the renderer would
        refuse it too and an approximation here would be a number nobody
        declared, printed as a measurement;
      * the declaration names no zone, and an appointment is wall clock while a
        trace is UTC, so without one the comparison is wrong by the offset;
      * it is simply too early to tell;
      * the machine was OFF when the appointment came round.
    The first two and the last are worth a sentence; the third is not news.
    """
    from datetime import datetime, timezone

    state, sev = model.WorkloadState, model.Severity
    who = str(getattr(stamp, "state_key", "") or "") or w.id

    zone_name = getattr(w.schedule, "timezone", None) if w.schedule else None
    if not zone_name:
        return [finding(
            state.unknown, sev.info,
            f"{who} asked for missing detection and names no timezone; an "
            f"appointment is wall clock and a trace is UTC, so the two cannot "
            f"be compared",
            "add schedule.timezone", source="declaration")]
    try:
        from zoneinfo import ZoneInfo

        zone = ZoneInfo(str(zone_name))
    except Exception as exc:
        return [finding(
            state.unknown, sev.info,
            f"{who} names the timezone {zone_name!r}, which this host cannot "
            f"resolve ({exc})",
            "check the zone name against the tzdata of the host", source="machine")]

    if appointment is None:
        appointment = backend_base.appointments_of(w)[:1]
        appointment = appointment[0] if appointment else None

    try:
        due = backend_base.previous_due(w, appointment, now, zone)
    except errors.WorkloadError as refusal:
        return [finding(
            state.unknown, sev.info,
            f"{who} asked for missing detection, and its recurrence is outside "
            f"what this skill translates: {refusal}",
            "let the dispatcher answer it, or state a recurrence in the "
            "translated subset", source="declaration")]

    if due is None:
        return []

    # DERIVED, never chosen: until the deadline has run out, a silent run may
    # simply still be working.
    grace = int(backend_base.timeout_of(w) or 0) + OVERDUE_GRACE_SEC
    if (now - due).total_seconds() <= grace:
        return []

    if newest is not None and newest[0] >= due:
        return []

    # THE MACHINE HAS TO HAVE BEEN UP. A run due while the box was off left no
    # line because nothing was running, not because anything is broken, and
    # `overdue` is the loudest verdict this skill has: severity high, with an
    # instruction to bootout and bootstrap a unit that is fine. The
    # neighbouring operations page has carried this distinction from the start
    # ("vor dem letzten Hochfahren, kein Urteil moeglich") and this one had not.
    #
    # It is a SENTENCE and not a silence: "nothing can be judged here" and
    # "nothing is wrong here" are different answers and must never print the
    # same. The state is `unknown`, which the page already draws as the dotted
    # ring it has a legend entry for.
    #
    # It may only ever DOWNGRADE AN OVERDUE, which is why it is reached from
    # the two `overdue` returns below and not from the top of the function.
    # Written at the top for half an hour on 2026-08-27, it also fired on every
    # path that was ALREADY silent for a reason of its own, and turned a
    # justified silence into a sentence: measured on the live page, one weekly
    # report provisioned after its last appointment, which the rule below had
    # correctly said nothing about for two days, acquired a verdict. A guard
    # against a false claim that manufactures a second claim is not a guard.
    def cannot_judge():
        return [finding(
            state.unknown, sev.info,
            f"{who} was due at {due.isoformat()}, and this machine came up at "
            f"{booted.isoformat()}, so nothing here can say whether it ran",
            "nothing to do: the appointment fell while the machine was down",
            source="machine")]

    # The other explained silence, under exactly the same rule and reached from
    # exactly the same two returns: a unit in the persistent off-list wrote no
    # line because nothing was going to start it.
    def nothing_was_going_to_run_it():
        return [finding(
            state.unknown, sev.info,
            f"{who} was due at {due.isoformat()} and the unit is in this "
            f"machine's persistent off-list, so nothing was going to start it",
            "nothing to do here: the off-list is reported as its own finding",
            source="machine")]

    if newest is None:
        since = getattr(stamp, "provisioned_at", None) if stamp is not None else None
        if not since:
            return []
        try:
            planted = datetime.fromisoformat(str(since))
        except ValueError:
            return []
        if planted.tzinfo is None:
            planted = planted.replace(tzinfo=timezone.utc)
        if planted >= due:
            return []
        if switched_off:
            return nothing_was_going_to_run_it()
        if booted is not None and booted > due:
            return cannot_judge()
        return [finding(
            state.overdue, sev.high,
            f"{who} was provisioned at {since} and has not written a single "
            f"line since, though it was due at {due.isoformat()}",
            "read the unit's log: it was set up and never ran", source="machine")]

    if switched_off:
        return nothing_was_going_to_run_it()
    if booted is not None and booted > due:
        return cannot_judge()
    return [finding(
        state.overdue, sev.high,
        f"{who} was due at {due.isoformat()} and its newest line is from "
        f"{newest[0].isoformat()}, so that run did not happen",
        "read the unit's log, then bootout and bootstrap it, never kickstart",
        source="machine")]


def _declaration_drift(w, stamp, appointment_name: str = "") -> "Finding | None":
    """Has the DECLARATION moved on since this was provisioned?

    ORTHOGONAL to every verdict in `_classify_one`, and therefore a finding of
    its own rather than one more branch in that chain. A unit can be running,
    stopped, or holding an orphaned grant AND be built from last week's file.
    Folded into the chain, this question would either hide the more specific
    answer or be hidden by it, and both are worse than two sentences.
    `_trace_findings` sits beside the chain for the same reason.

    Why it is needed at all: both digest comparisons inside `_classify_one`
    live on the MACHINE, a marker inside the unit against a stamp beside it,
    written in the same second by the same provision. Neither can notice the
    file changing afterwards. Edit a yaml, forget to provision, and every
    signal on the machine still agrees with every other one, so the report
    reads green about a box running an older declaration.

    That is this skill's own premise turned inward. It refuses to trust a
    declared `status:` and asks the machine instead; without this it then never
    asks whether the machine's answer is still an answer to the CURRENT
    question. `source="declaration"` is what separates the two kinds of drift
    for a reader: the machine changed under us, or we changed and never told
    the machine.
    """
    recorded = _text(getattr(stamp, "declaration_digest", None))
    if not recorded:
        # A stamp with no digest cannot say what it was made from. That is a
        # different fault, and `_classify_one` already speaks about it.
        return None
    declared_now = _text(model.declaration_digest(w))
    if declared_now == recorded:
        return None
    return Finding(
        workload_id=w.id,
        state=model.WorkloadState.drifted,
        severity=model.Severity.medium,
        detail=(f"{w.id} runs from an older declaration than the file on disk: the "
                f"stamp was made from {recorded}, the file now reads {declared_now}"),
        hint="provision it again so the machine runs what the declaration says",
        source="declaration",
        appointment=appointment_name)


def _naming_drift(w, stamp, appointment_name: str = "") -> "Finding | None":
    """Would this run be provisioned under a DIFFERENT name than it carries?

    A second kind of drift, and it became reachable on 2026-08-25 when
    `workloads.label_prefix` was finally wired to the backends. Until then the
    knob was read and never applied, so it could not move a name; now it can,
    and nothing else in this module would notice.

    `_declaration_drift` cannot see it: it compares the DECLARATION digest, and
    changing the configuration moves no declaration. Every comparison in
    `_classify_one` came off the machine and agrees with itself. So the report
    would read `in_sync` while the very next `provision` created a SECOND unit
    beside the first, leaving the old one running and unmanaged. A duplicate
    that nobody was warned about is worse than a stale one, which is why this
    is high rather than medium.

    Runtimes that name nothing on the machine answer with an empty set and are
    passed over: there is no name to have drifted.
    """
    recorded = _text(getattr(stamp, "unit_ref", None))
    if not recorded:
        return None
    names = inventory_mod.unit_names_of(w)
    if not names:
        return None
    carried = inventory_mod.label_of(recorded)
    if carried in names:
        return None
    return Finding(
        workload_id=w.id,
        state=model.WorkloadState.drifted,
        severity=model.Severity.high,
        detail=(f"{w.id} was provisioned as {carried}, but this declaration would "
                f"now be created as {' or '.join(sorted(names))}"),
        hint=("provisioning again would ADD a unit beside the running one. Retire "
              "the old one first, or restore the name (workloads.label_prefix in "
              "the configuration, placement.label_prefix in the declaration)"),
        source="declaration",
        appointment=appointment_name)


def _trace_findings(w, text, stamp, now, finding, appointment=None, booted=None,
                    switched_off=False):
    """What the run itself wrote, read back. Empty when nobody asked."""
    from datetime import datetime, timezone

    state, sev = model.WorkloadState, model.Severity
    wants = _notify_on(w)
    out = []
    if not wants:
        return out

    newest = _newest_trace(text or "")

    if "failure" in wants and newest is not None and newest[1] not in (None, 0) \
            and not _transient_blip(w, text or ""):
        # Named after the UNIT where a run has several appointments. Naming the
        # declaration leaves a reader unable to tell WHICH of two times failed,
        # and two appointments can answer two different sets of people.
        who = str(getattr(stamp, "state_key", "") or "") or w.id
        out.append(finding(
            state.last_run_failed, sev.high,
            f"the last run of {who} ended with {newest[1]}, and said so in its own "
            f"trace at {newest[0].isoformat()}",
            "read the unit's log for that run before provisioning anything again",
            source="machine"))

    if "missing" not in wants:
        return out

    if now is None:
        now = datetime.now(timezone.utc)
    elif isinstance(now, str):
        now = datetime.strptime(now, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)

    cadence = _cadence_sec(w)
    if cadence is None:
        # A recurring run states no gap in seconds, and it does not have to.
        # What missing detection needs is the MOMENT it was last due, and that
        # comes out of the same two functions the unit file is rendered from.
        out.extend(_appointment_overdue(w, appointment, newest, stamp, now,
                                        finding, booted, switched_off))
        return out

    limit = cadence * OVERDUE_CADENCES

    # The same fact as in the appointment branch, from the other direction, and
    # under the same rule: it may only DOWNGRADE AN OVERDUE. A machine that has
    # been up for less than the window cannot have produced a longer history
    # than its own uptime, so whatever is missing was missing while nothing was
    # running. Reached from the two `overdue` paths and not from the top: at
    # the top it also fired for every HEALTHY run on the box, so a machine
    # rebooted five minutes ago would have grown one sentence per declaration
    # saying nothing was wrong with any of them.
    def too_soon_to_tell():
        return (booted is not None
                and (now - booted).total_seconds() < limit)

    def cannot_judge():
        return [finding(
            state.unknown, sev.info,
            f"{w.id} has a cadence of {cadence}s and this machine came up at "
            f"{booted.isoformat()}, which is less than {limit}s ago, so its "
            f"silence so far says nothing",
            "nothing to do: the machine has not been up long enough to tell",
            source="machine")]

    # The second reason a silence is explained rather than reported, under the
    # same rule as the first: it may only DOWNGRADE AN OVERDUE, never add a
    # sentence to a healthy run. A unit in the persistent off-list did not
    # write a line because nothing was going to start it, and `overdue` is the
    # loudest verdict here, with an instruction to reprovision a unit whose
    # bytes are already correct. The off-list is reported on its own, so this
    # says the cause and points at that finding rather than repeating it.
    def nothing_was_going_to_run_it():
        return [finding(
            state.unknown, sev.info,
            f"{w.id} has written nothing for longer than its cadence allows, "
            f"and the unit is in this machine's persistent off-list, so "
            f"nothing was going to start it",
            "nothing to do here: the off-list is reported as its own finding",
            source="machine")]

    if newest is None:
        since = getattr(stamp, "provisioned_at", None) if stamp is not None else None
        if not since:
            return out
        try:
            planted = datetime.fromisoformat(str(since))
        except ValueError:
            return out
        if planted.tzinfo is None:
            planted = planted.replace(tzinfo=timezone.utc)
        if (now - planted).total_seconds() > limit:
            if switched_off:
                return out + nothing_was_going_to_run_it()
            if too_soon_to_tell():
                return out + cannot_judge()
            out.append(finding(
                state.overdue, sev.high,
                f"{w.id} was provisioned at {since} and has not written a single "
                f"line since, though its cadence is {cadence}s",
                "read the unit's log: it was set up and never ran", source="machine"))
        return out

    late = (now - newest[0]).total_seconds()
    if late > limit:
        if switched_off:
            return out + nothing_was_going_to_run_it()
        if too_soon_to_tell():
            return out + cannot_judge()
        out.append(finding(
            state.overdue, sev.high,
            f"{w.id} last wrote a line {int(late)}s ago and its declared cadence "
            f"is {cadence}s",
            "read the unit's log, then bootout and bootstrap it, never kickstart",
            source="machine"))
    return out



def _moment(text):
    """An ISO stamp as an aware datetime, or None on anything unreadable.

    None everywhere means "not known", which is the answer that changes no
    verdict. Raising here would let one unreadable line from one machine abort
    a report about five.
    """
    from datetime import datetime, timezone

    if not text:
        return None
    try:
        moment = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def classify(workloads: Sequence, host_obs: HostObservation,
             inventory: Mapping[str, Any], probe_verdicts: Mapping[str, Any],
             *, now=None) -> list[Finding]:
    """Declaration x machine x inventory -> findings. Pure.

    Declaration anchored findings come first, so the caller can read the first
    line about a workload as its verdict; machine and inventory anchored ones
    follow.
    """
    workloads = list(workloads or ())
    verdicts = dict(probe_verdicts or {})
    units = list(host_obs.live_units or ())
    stamps = dict(host_obs.stamps or {})

    findings: list[Finding] = []
    claimed: set[str] = set()

    # ONE derivation for the whole report. Parsed here rather than at each of
    # the three sites that read it, because three parsers of one string is how
    # two of them come to disagree about a machine that answered once.
    booted = _moment(getattr(host_obs, "booted_at", ""))

    for w in workloads:
        # The stamp of THIS declaration, whichever unit filed it. A run with
        # several appointments has one record per unit; picking any of them for
        # the unit search is enough, because rule 1 (the ownership marker) and
        # rule 3 (the label) both find every unit on their own.
        #
        # That sentence was only HALF true until 2026-08-25: rule 3 compared
        # string ends and never matched `<prefix>.<id>.<appointment>`, so with
        # both ownership signals gone a multi appointment declaration lost its
        # own units. Rule 3 now compares against the names the backend would
        # actually produce, appointments included, so the claim holds.
        stamp = next((st for st in stamps.values()
                      if getattr(st, "workload_id", None) == w.id), None)
        mine = inventory_mod.find_units(w, units, stamp)
        for sibling in mine:
            claimed.add(sibling.unit_ref)
        # ONE VERDICT PER UNIT. A run with several appointments is several
        # units, and a single sentence about the pair is a sentence about
        # neither: measured on a real machine on 2026-08-24, the report carried
        # one line, about whichever unit was found first, and the other was
        # never assessed. It could have been unloaded, disabled or drifted and
        # the report would have read the same. Silence about a unit is read as
        # nothing being wrong with it.
        #
        # Each unit is matched to ITS OWN stamp, by unit reference: the records
        # are filed per unit and a shared one would make the second unit look
        # provisioned because the first is.
        for unit in (mine or (None,)):
            own = (stamps.get(unit.unit_ref) if unit is not None else None) or stamp
            # ONE derivation of the appointment for every finding about this
            # unit, taken from the stamp's state key by the same function the
            # trace already used. Deriving it twice is how the pair drifts.
            mine_appointment = _appointment_of(w, own)
            appointment_name = str(getattr(mine_appointment, "name", "") or "")
            primary = _classify_one(w, own, unit, host_obs, verdicts.get(w.id),
                                    appointment_name)
            findings.append(primary)

            # THE OFF-LIST, and it is read HERE, before the two refusals below.
            # `in_sync` is a statement about BYTES: it compares what is on the
            # machine with what the declaration renders, and a unit whose bytes
            # are perfect can sit in the persistent off-list and never start.
            # `provision` read that list from the beginning, to refuse switching
            # on what a person switched off; the pass that reports how the
            # machine IS never asked, so the two disagreed by construction.
            #
            # Before the refusals because the OTHER case is a unit that is not
            # loaded at all: reported `absent`, with a hint to provision it
            # again that `provision` then refuses for exactly this reason. Both
            # cases are the same fact and both are worth the sentence.
            #
            # Absent is not False: a list nobody read leaves no key here, and
            # reading that silence as "not disabled" would be the mistake
            # `marker_observed` exists to prevent.
            ref = (unit.unit_ref if unit is not None
                   else _text(getattr(own, "unit_ref", "")))
            switched_off = bool(ref) and (host_obs.disabled or {}).get(ref) is True
            if switched_off and not w.is_retired:
                findings.append(Finding(
                    workload_id=w.id, state=model.WorkloadState.disabled,
                    severity=model.Severity.medium,
                    detail=(f"{ref} sits in the persistent off-list of "
                            f"{host_obs.host}, so it will not start, and a reboot "
                            f"will not change that: that is what the persistent "
                            f"list is for"),
                    hint=("provision it again with --enable if it should run, or "
                          "retire the declaration if the stop was meant to last"),
                    source="machine", appointment=appointment_name))

            # A unit that is not there needs no second sentence about its
            # cadence: the absence IS the story, and anything added to it is the
            # noise that makes a report stop being read.
            if primary.state in TRACE_SAYS_NOTHING_IN:
                continue
            # And nobody is waiting for a run that was deliberately stopped. The
            # trace outlives the workload on purpose, as the record of what
            # happened, but read against a RETIRED declaration it produces the
            # two loudest findings this skill has for something behaving exactly
            # as intended. The report said `retired and gone from the machine`
            # and `high overdue` about the same id, three lines apart, on a real
            # machine. A retired one that is still loaded is a different case
            # and is caught by `retired_but_live` in the set above.
            if w.is_retired:
                continue
            # The trace of THIS unit. Traces are already filed per unit, because
            # the guard names them after its state key; looking one up by the
            # declaration would read the morning run's history for the midday
            # unit and answer "it ran" about a run that did not.
            key = str(getattr(own, "state_key", "") or "") or w.id
            # What the run itself wrote, read back. A workload can be in_sync
            # AND have failed its last run, so these are additional findings and
            # never replace the state above.
            # WHICH appointment this unit answers, read back from its state
            # key. Without it every unit would be judged against the first
            # appointment's hour, so the midday unit would be called missing
            # every morning and the morning unit would never be.
            findings.extend(_trace_findings(
                w, (host_obs.traces or {}).get(key, ""), own, now,
                lambda st, sv, detail, hint, source: Finding(
                    workload_id=w.id, state=st, severity=sv, detail=detail,
                    hint=hint, source=source, appointment=appointment_name),
                appointment=mine_appointment, booted=booted,
                switched_off=switched_off))

        # ONCE per declaration, after the units, and deliberately NOT inside the
        # loop above. An outdated declaration is a fact about the FILE, the same
        # way `inventory_missing` is a fact about the register: neither is
        # decided per appointment. Inside the loop it produced two identical
        # sentences for a run with two units, measured on a real machine on
        # 2026-08-25. Two identical lines are not a crisis, they are a habit,
        # and a report that repeats itself is one somebody starts skimming.
        #
        # Only where a stamp exists at all: without one there is nothing to
        # compare the file against, and a retired declaration is not supposed to
        # match anything any more.
        if stamp is not None and not w.is_retired:
            moved = _declaration_drift(w, stamp)
            if moved is not None:
                findings.append(moved)
            renamed = _naming_drift(w, stamp)
            if renamed is not None:
                findings.append(renamed)

        # The other thing the machine records and nobody read: which client path
        # a privacy grant was issued to. Unsuppressed on purpose -- a workload
        # that is absent or unprovisioned still has a grant sitting somewhere,
        # and that is exactly when somebody is about to re-provision it. Once per
        # DECLARATION, because a grant belongs to the interpreter and every
        # appointment of a run shares one.
        findings.extend(_grant_findings(
            w, stamp,
            lambda st, sv, detail, hint, source: Finding(
                workload_id=w.id, state=st, severity=sv, detail=detail,
                hint=hint, source=source)))

    declared = {w.id for w in workloads}
    # Over the RECORDS, not over the keys. The keys are unit references now,
    # because two units of one declaration each keep their own record; the
    # question here is still about the declaration, and the record carries it.
    for workload_id in sorted({str(getattr(st, "workload_id", "") or "")
                               for st in stamps.values()}):
        if not workload_id or workload_id in declared:
            continue
        findings.append(Finding(
            workload_id=workload_id, state=model.WorkloadState.orphan_stamp,
            severity=model.Severity.medium,
            detail=(f"{host_obs.host} carries a stamp for {workload_id!r}, "
                    f"but no declaration does"),
            hint="restore the declaration or retire the workload so the stamp goes with it",
            source="machine"))

    for unit in units:
        if unit.unit_ref in claimed:
            continue
        findings.append(Finding(
            workload_id=inventory_mod.label_of(unit.unit_ref),
            state=model.WorkloadState.unmanaged, severity=model.Severity.info,
            detail=f"{unit.unit_ref} runs on {host_obs.host} and no declaration claims it",
            hint="declare it to make it visible, or leave it alone: this skill never touches it",
            source="machine"))

    findings.extend(inventory_mod.inventory_delta(host_obs, inventory, workloads))
    return findings



def _kind_of(w) -> str:
    """The declared kind, or "" when there is no declaration to ask."""
    placement = getattr(w, "placement", None)
    return _name(getattr(placement, "kind", "")) if placement is not None else ""


def _classify_one(w, stamp, unit, host_obs: HostObservation, verdict,
                  appointment_name: str = "") -> Finding:
    state = model.WorkloadState
    sev = model.Severity
    unknown_verdict = verdict is not None and verdict == probe_mod.Verdict.unknown

    def finding(st, severity, detail, hint="", source="declaration"):
        return Finding(workload_id=w.id, state=st, severity=severity,
                       detail=detail, hint=hint, source=source,
                       appointment=appointment_name)

    if _is_observed_only(w):
        return finding(
            state.observed, sev.info,
            f"owned by {_name(w.placement.owner)} and carried by "
            f"{_name(w.placement.runtime)}: documented, never provisioned",
            source="declaration")

    if not host_obs.reachable:
        return finding(
            state.unknown, sev.medium,
            f"{host_obs.host} did not answer: {host_obs.error}",
            "make the host reachable, then reconcile again. Unobserved is not gone",
            source="machine")

    if w.is_retired:
        if unit is not None:
            return finding(
                state.retired_but_live, sev.high,
                f"the declaration is retired, yet {unit.unit_ref} is present on "
                f"{host_obs.host}",
                "bootout and disable it with the retirement reason, then verify it is stopped",
                source="machine")
        if unknown_verdict:
            return finding(
                state.unknown, sev.medium,
                f"retired, and the probe could not be evaluated on {host_obs.host}",
                "resolve the probe or its expect, then reconcile again", source="machine")
        return finding(state.in_sync, sev.info,
                       "retired and gone from the machine", source="machine")

    if unknown_verdict:
        return finding(
            state.unknown, sev.medium,
            f"the probe for {w.id} could not be evaluated on {host_obs.host}",
            "resolve the probe placeholder or replace the prose expect with a pattern",
            source="machine")

    if unit is None:
        if _name(w.placement.runtime) in host_obs.failed_runtimes:
            return finding(
                state.unknown, sev.medium,
                f"{host_obs.host} could not be enumerated for "
                f"{_name(w.placement.runtime)}, so nothing is known about {w.id}",
                "fix the discovery error above, then reconcile again", source="machine")
        if stamp is not None or _text(getattr(w.placement, "provisioned_at", None)):
            return finding(
                state.absent, sev.high,
                f"provisioned once, but nothing on {host_obs.host} carries it any more",
                "provision it again, or retire the declaration if it is meant to be gone",
                source="machine")
        return finding(
            state.not_provisioned, sev.info,
            "declared and never provisioned",
            "run provision when it should exist", source="declaration")

    has_stamp = stamp is not None
    has_marker = bool(unit.marker_id)
    # Whether anybody LOOKED. Every conclusion below that rests on the marker
    # being absent needs this, or it is an inference from silence. The same
    # rule this module already applies to a whole host ("Unobserved is not
    # gone") applies to the second ownership signal.
    looked = bool(getattr(unit, "marker_observed", False))

    if not looked and has_stamp:
        # The stamp claims it and the marker was never read. Nothing here is
        # evidence of drift, so fall through to the checks that DID observe
        # something. The digest comparison below is skipped for the same
        # reason: a value nobody read cannot disagree with anything.
        pass
    elif not has_stamp and not has_marker and not looked:
        return finding(
            state.unknown, sev.info,
            f"{unit.unit_ref} matches the declaration, and neither signal was read",
            "reconcile again from a host that can inspect it", source="machine")
    elif not has_stamp and not has_marker:
        return finding(
            state.unstamped, sev.high,
            f"{unit.unit_ref} matches the declaration but carries neither a stamp "
            f"nor an ownership marker",
            "adopt it to take ownership without downtime. It is never overwritten",
            source="machine")
    if looked and has_stamp and not has_marker:
        return finding(
            state.drifted, sev.medium,
            f"{unit.unit_ref} has a stamp on {host_obs.host} but no ownership marker "
            f"inside the unit",
            "provision it again so both ownership signals agree", source="machine")
    if not has_stamp:
        return finding(
            state.drifted, sev.medium,
            f"{unit.unit_ref} carries the ownership marker but there is no stamp on "
            f"{host_obs.host}",
            "provision it again so both ownership signals agree", source="machine")
    # Both sides of this comparison are DECLARATION digests, and that is not a
    # detail. The marker sits INSIDE the rendered file, so it can never carry
    # the artifact digest: that digest covers the very bytes the marker is part
    # of, and a value cannot contain its own hash. The stamp records both, so
    # the marker is compared against the declaration digest the stamp kept, and
    # the artifact digest is compared against the files, which is what
    # `provision.plan` does. Comparing the two currencies against each other
    # made every correctly provisioned run report drift forever.
    if looked and _text(unit.marker_digest) != _text(getattr(stamp, "declaration_digest", None)):
        return finding(
            state.drifted, sev.medium,
            f"the unit on {host_obs.host} was made from a different declaration than "
            f"the stamp records ({unit.marker_digest} against "
            f"{getattr(stamp, 'declaration_digest', None)})",
            "provision it again to put the declared artifact back", source="machine")

    if verdict is not None and verdict == probe_mod.Verdict.fail:
        return finding(
            state.stopped, sev.high,
            f"{unit.unit_ref} is present on {host_obs.host} but its probe says otherwise",
            "read the unit's log, then bootout and bootstrap it, never kickstart",
            source="machine")
    # Only for a kind that is SUPPOSED to be running. A cadence run is idle
    # between firings by design, and calling that stopped sends the reader to
    # bootout a healthy unit. The probe verdict above is different: the
    # declaration named that question itself, so its answer counts for any kind.
    if unit.running is False and _kind_of(w) in model.CONTINUOUS_KINDS:
        return finding(
            state.stopped, sev.high,
            f"{unit.unit_ref} is present on {host_obs.host} but not running",
            "read the unit's log, then bootout and bootstrap it, never kickstart",
            source="machine")

    # "matches the stamp", never "matches the declaration". Everything this
    # chain compared came off the MACHINE: the marker inside the unit, the
    # stamp beside it, the files themselves. Whether the file on disk still
    # says the same thing is asked by `_declaration_drift`, and it can answer
    # no while every comparison here answers yes. The old wording claimed
    # both, so a report could carry "matches the declaration" one line above
    # "runs from an older declaration than the file on disk" about the same
    # run. Measured on a real machine the moment the second sentence existed.
    return finding(state.in_sync, sev.info,
                   f"{unit.unit_ref} matches its stamp and the artifact it was "
                   f"provisioned from",
                   source="machine")


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def run(root: Path, cfg, *, hosts: Sequence[str] | None = None,
        ids: Sequence[str] | None = None, probe: bool = True,
        timeout_sec: int | None = None, runner=None) -> Report:
    """Reconcile the declarations against every host they name.

    Each host is observed at most once. One unreachable host degrades only its
    own workloads to ``unknown`` and never aborts the report.
    """
    from engine import hosts as hosts_mod

    timeout_sec = timeout_sec or getattr(cfg, "step_timeout_sec", 60)
    workloads = model.load_all(root, cfg)
    if ids:
        wanted = set(ids)
        workloads = [w for w in workloads if w.id in wanted]
    if hosts:
        on = set(hosts)
        workloads = [w for w in workloads if _name(w.placement.host) in on]

    by_host: dict[str, list] = {}
    for w in workloads:
        by_host.setdefault(_name(w.placement.host), []).append(w)

    findings: list[Finding] = []
    read_locally: list = []
    #: The newest trace per workload, for the half of a timeline that is not
    #: intent. Empty for a workload the host never ran or never answered about.
    runs: dict = {}
    history: dict = {}
    #: When each machine last came up. Carried to the report because it is what
    #: makes a silence readable: the verdicts already use it to hold back a
    #: false `overdue`, and a reader needs the same fact to judge the rest.
    booted: dict = {}
    #: `{id: (program, where)}` for every declaration that names a program.
    programs: dict = {}
    #: The ids whose probe actually RAN. Not the ones a flag hoped for.
    probed_ids: set[str] = set()
    for slug in sorted(by_host):
        group = by_host[slug]
        try:
            host = hosts_mod.resolve_host(slug, root)
            if getattr(host, "local_reason", ""):
                # Collected, not printed here: a local read has to reach the
                # HEADER, the line a reader sees before any finding. Buried
                # among findings it would be one info line among twenty, and
                # this is the one decision that could answer about the wrong
                # machine while looking entirely ordinary.
                read_locally.append(host.local_reason)
        except Exception as exc:
            # One call, one catch. A host nobody can resolve becomes a reported
            # finding for its workloads, never a swallowed error and never a
            # reason to abandon the other hosts.
            for w in group:
                findings.append(Finding(
                    workload_id=w.id, state=model.WorkloadState.unknown,
                    severity=model.Severity.medium,
                    detail=f"host {slug!r} could not be resolved: {exc}",
                    hint=f"add infra/remotes/{slug}.yaml or correct placement.host",
                    source="declaration"))
            continue

        obs = observe_host(host, cfg, timeout_sec=timeout_sec, runner=runner)
        entries = inventory_mod.load_inventory(host)
        verdicts = {}
        if probe and obs.reachable:
            verdicts, asked = _probe_group(group, host, root, cfg, runner=runner)
            probed_ids |= asked
        findings.extend(classify(group, obs, entries, verdicts))
        # After `classify`, and outside it, because this one needs the
        # REPOSITORY and `classify` is pure over the machine's answers. It is
        # also the one question here whose two sides live in different places:
        # the program on the box and the file that is supposed to be it.
        if obs.reachable:
            # ONE read, two readers. The findings say what needs a person and
            # the map says where every program sits; deriving the digests twice
            # would be two round trips and, worse, two answers.
            digests = read_program_digests(host, group, timeout_sec=timeout_sec,
                                           runner=runner)
            findings.extend(source_mod.findings(group, root, digests))
            programs.update(source_mod.described(group, root, digests))
        if getattr(obs, "booted_at", ""):
            booted[slug] = obs.booted_at
        # The trace is read for every group anyway; keeping it here is what lets
        # a timeline draw the actual half against the declared one.
        for w in group:
            texts = _traces_of(w, obs)
            newest = _newest_trace("\n".join(texts.values()))
            if newest is not None:
                when, rc = newest
                runs[w.id] = (when.strftime("%Y-%m-%dT%H:%M:%SZ"), rc)
            strip = _trace_strip(texts)
            if strip:
                history[w.id] = strip

    return report_mod.Report(
        findings=findings, runs=runs, history=history, booted=booted,
        state_dir=_text(getattr(cfg, "stamp_dir", "")), programs=programs,
        header=_coverage(workloads, by_host, probe, len(probed_ids),
                         read_locally=tuple(read_locally)))


def _coverage(workloads, by_host, probe: bool, probed: int = 0, *, reached=None,
              read_locally=()) -> str:
    """The coverage sentence, plus any machine that answered for itself.

    A wrapper rather than a branch inside, because the sentence below has five
    exits. Added to one of them, the note would go missing in exactly the
    branches where something is already unusual, which are the ones worth
    reading.
    """
    said = _coverage_core(workloads, by_host, probe, probed, reached=reached)
    if not read_locally:
        return said
    return said + ". " + "; ".join(str(one) for one in read_locally)


def _coverage_core(workloads, by_host, probe: bool, probed: int = 0, *,
                   reached=None) -> str:
    """What this run actually looked at, said before anything it found.

    The clean line on its own is not an answer. `report._with_header` writes the
    rule down and `validate` keeps it; reconcile returned a headerless report and
    so answered a mistyped id with "clean: nothing found that needs a hand" and
    exit 0, over a tree with seven live declarations in it. A typo read exactly
    like a healthy fleet.

    The word `probed` used to come out of the FLAG, which made this line the same
    mistake one layer up: `_probe_group` skips every declaration that resolves no
    probe of its own, so three unprobed runs read exactly like three probed ones.
    The count is therefore taken from the probes that RAN, and a probe refused
    before execution (a placeholder, prose instead of a pattern) does not count
    as one, because it asked no live source anything.

    And then it overclaimed in the OTHER direction, which is the third version
    of the same mistake. With no health probe it said `nothing here was asked of
    a live source`, and that is false: the units were listed, the ownership
    stamps were read and the traces the guard wrote were read, which is where
    every finding on such a run comes from. Two different questions were wearing
    one word. INSPECTION reads the state and always happens where a host
    answers; a PROBE takes a health verdict and only happens where a declaration
    resolves one. The line now says which of the two did not happen, and
    `reached` separates the case where genuinely nothing was read because no
    host answered at all.
    """
    if not workloads:
        return ("0 declarations reconciled: nothing matched, so this says nothing "
                "about any machine")
    total = len(workloads)
    head = f"{total} declaration(s) reconciled on {len(by_host)} host(s)"
    if reached is not None and reached == 0:
        return (f"{head}, but no host answered, so nothing at all was read and "
                f"this says nothing about any machine")
    if not probe:
        return (f"{head}, inspected but not health-probed, --no-probe was given")
    if probed == 0:
        return (f"{head}, 0 of {total} health-probed: the machine WAS inspected "
                f"(units, ownership stamps, traces), no health verdict was taken")
    return f"{head}, {probed} of {total} health-probed"


def _probe_group(group: Iterable, host, root: Path, cfg, *, runner=None) -> tuple:
    """(verdicts, ids actually asked). One probe per workload, at most.

    Deriving a backend default here would mean rendering the artifact, which
    needs a host context; the live observation already answers the same
    question, so a missing probe is silence rather than a manufactured unknown.

    The second half of the return value is what keeps the coverage line honest.
    Silence here is the common case, not the exception, and a header that said
    "probed" from the flag alone reported a run over nothing in the same words
    as a run over a fleet.
    """
    verdicts = {}
    asked: set[str] = set()
    timeout = getattr(cfg, "probe_timeout_sec", 30)
    connect = getattr(cfg, "ssh_connect_timeout_sec", None)
    for w in group:
        try:
            spec = probe_mod.resolve_probe(w, host, None, root, cfg)
        except Exception:
            # An ambiguous check ref, an unreadable registry: a probe that
            # cannot even be resolved is unknown, which is surfaced. It is
            # never a pass.
            verdicts[w.id] = probe_mod.Verdict.unknown
            continue
        if spec.source == "unresolved":
            continue
        done, verdict = probe_mod.run_probe(spec, host, timeout_sec=timeout,
                                            runner=runner, connect_timeout_sec=connect)
        verdicts[w.id] = verdict
        if done is not None:
            # `run_probe` returns None where it refused to execute at all. That
            # is an unknown, and an unknown nobody ran is not coverage.
            asked.add(w.id)
    return verdicts, frozenset(asked)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_observed_only(w) -> bool:
    if _name(getattr(w.placement, "runtime", "")) in INERT_RUNTIMES:
        return True
    is_bridge = getattr(w, "is_bridge_owned", None)
    if is_bridge is None:
        return _name(getattr(w.placement, "owner", "")) != "bridge"
    return not is_bridge


def _name(value) -> str:
    return str(getattr(value, "value", value))


def _text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()
