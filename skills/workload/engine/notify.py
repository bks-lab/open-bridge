"""The one adapter that knows how to speak, and the exit code is the fact.

The program is DECLARED, never named here. `workloads.notify_via` carries the
argv template of whatever an instance uses to reach a person: its path, its
flags, and the words that fill them. This module substitutes and executes, and
that is the whole of its knowledge.

It used to hold a filename, searched at two fixed paths, called with three
flags in a language this repository is not written in. The key that was supposed
to steer it was parsed, stored, serialised into the JSON output, and read by
nothing. So a fresh clone had an alarm path that could not exist, and an
instance that configured one was ignored.

The return code is LOAD BEARING. Zero means at least one channel really
delivered. Everything that dampens repeats hangs off that answer, so reading a
failure as a success buys silence and pays nothing for it.

The scar is in this repository twice. A watchdog reported into the void for
three months because its send function returned success while its channel had
been off since May. And the second guard on that machine still starts its 24
hour silence on the DECISION to notify rather than on a confirmed delivery, so a
total failure of both channels goes quiet for a day.

This module knows nothing about WHEN to speak or WHOM to tell. Recipients belong
to the configured program; a second place naming them would be a second list to
keep in step.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass

from .errors import ConfigError


#: Distinguishes "caller said nothing" from "caller said: there is none".
_UNSET = object()


@dataclass(frozen=True)
class Sent:
    """What happened, never what was attempted."""

    delivered: bool
    reason: str = ""
    argv: tuple = ()


def _default_runner(argv, *, timeout_sec, **_):
    from engine import exec as exec_mod
    return exec_mod.run_argv(argv, timeout_sec=timeout_sec)


#: The words a template may ask for. Anything else stays as it stands, so a
#: literal brace in somebody's flag is not silently eaten.
PLACEHOLDERS = ("what", "where", "todo", "detail")


def argv_for(spec, *, what: str, where: str, todo: str, detail: str = "") -> list:
    """The program and its words, from the declared template. Pure.

    Substitution is PER ELEMENT and never on a joined string: a value with a
    space stays one argument. Joining and re-splitting would turn a two word
    host into two arguments, and the program would read the second as a flag.

    The `detail` segment is appended only when there is detail, because a flag
    whose value is empty is a flag with a missing value, and most programs read
    the next argument instead.
    """
    values = {"what": str(what), "where": str(where), "todo": str(todo),
              "detail": str(detail)}

    def fill(element) -> str:
        text = str(element)
        for name in PLACEHOLDERS:
            text = text.replace("{" + name + "}", values[name])
        return text

    argv = [fill(part) for part in (spec or {}).get("command", ())]
    if values["detail"]:
        argv += [fill(part) for part in (spec or {}).get("detail", ())]
    return argv


def notifier_spec(cfg):
    """The declared alarm path, or None when an instance has not declared one.

    None is an ANSWER. Inventing a filename here is how a skill acquires a
    dependency its own repository does not ship, which is exactly what the
    previous shape did.
    """
    raw = getattr(cfg, "notify_via", None)
    if not raw:
        return None
    if not isinstance(raw, Mapping):
        raise ConfigError(
            "workloads.notify_via: expected a mapping with a `command` list, "
            f"found {type(raw).__name__}", source="bridge-config.yaml")
    command = raw.get("command")
    if not isinstance(command, (list, tuple)) or not command:
        raise ConfigError(
            "workloads.notify_via.command: expected a non empty list, the "
            "program first and then its flags", source="bridge-config.yaml")
    detail = raw.get("detail") or ()
    if not isinstance(detail, (list, tuple)):
        raise ConfigError(
            "workloads.notify_via.detail: expected a list appended only when "
            "there is detail to send", source="bridge-config.yaml")
    return {"command": [_expanded(part) for part in command],
            "detail": [_expanded(part) for part in detail]}


def _expanded(element) -> str:
    """A leading `~/` becomes the home directory, and nothing else changes.

    The argv is handed to a process and never to a shell, so a tilde would
    arrive as a literal directory name and the program would be reported
    missing. Done here, at the boundary that reads the configuration, because
    `argv_for` is pure and stays that way.
    """
    text = str(element)
    return os.path.expanduser(text) if text.startswith("~/") else text


def send(*, argv, runner=None, timeout_sec: int = 60) -> Sent:
    """Run the declared program with the words it was given. Never raises.

    The caller is a watchdog, so it may not be taken down by the thing it uses
    to complain: every failure comes back as an answer.
    """
    argv = [str(a) for a in (argv or ())]
    if not argv:
        return Sent(delivered=False, reason="no notifier configured", argv=())
    run = runner or _default_runner
    try:
        done = run(argv, timeout_sec=timeout_sec)
    except Exception as exc:                      # noqa: BLE001 - see docstring
        return Sent(False, f"{type(exc).__name__}: {exc}", tuple(argv))

    rc = getattr(done, "rc", None)
    if rc is None:
        rc = getattr(done, "returncode", None)
    if rc == 0:
        return Sent(True, "", tuple(argv))
    # Named, because a caller writing this into a state file wants to know
    # WHICH failure it was on the next run.
    said = (getattr(done, "stderr", "") or getattr(done, "stdout", "") or "").strip()
    tail = said.splitlines()[-1] if said else ""
    return Sent(False, f"exit {rc}{': ' + tail if tail else ''}", tuple(argv))


# ── which verdict wakes somebody, and on whose say-so ────────────────────────
#
# Four sets, written out rather than derived from severity. Severity measures
# attention while READING a report; this measures whether a phone should ring
# at three in the morning, and the two are different questions about the same
# verdict. Written out, growing the enum breaks a test instead of silently
# adding a state that either shouts or disappears.

#: The run happened and went wrong.
WAKES_ON_FAILURE = None
#: The run did not happen at all.
WAKES_ON_MISSING = None
#: Louder than the declaration, and sent WITHOUT asking `notify_on`.
WAKES_ALWAYS = None
#: Not trouble, or trouble a person handles at a keyboard rather than in bed.
WAKES_NOBODY = None


def _sets():
    from engine import model
    st = model.WorkloadState
    failure = {
        st.last_run_failed,   # the trace says so in the run's own words
        st.stopped,           # a thing that should be running fell over. Not
                              # `missing`: it did not skip an appointment, it
                              # went down.
    }
    missing = {
        st.overdue,           # its appointment passed and no line was written
        st.absent,            # the strongest form of "it did not come": the
                              # unit is not on the machine at all. It shares
                              # the channel with overdue without ever firing
                              # alongside it, because reconcile excludes trace
                              # findings for absent outright.
    }
    always = {
        st.retired_but_live,  # the loudest thing this skill says, and possibly
                              # a security incident. Nobody edits notify_on on
                              # the way out while retiring a run, so an opt-in
                              # gate here is a gate the retiring hand never
                              # touched.
        st.grant_orphaned,    # the run ends rc=0 and is simply shown nothing,
                              # so no trace can ever carry it. It is already
                              # opt-in through another field: it exists only
                              # where `placement.privacy_grants` is declared.
    }
    nobody = set(st) - failure - missing - always
    return failure, missing, always, nobody


WAKES_ON_FAILURE, WAKES_ON_MISSING, WAKES_ALWAYS, WAKES_NOBODY = _sets()

#: What each bucket is called in `response.notify_on`. `integrity` has no word
#: in that vocabulary on purpose, and that is exactly why it does not ask.
_ASKED_AS = {"failure": "failure", "missing": "missing"}


def route(finding, workload) -> str | None:
    """Which bucket this verdict belongs to, or None if nobody is woken.

    `unknown` is in WAKES_NOBODY and never routes. The reconcile driving this
    reaches its hosts over ssh from a laptop, so a closed lid produces
    `unknown` for every run on every host at once; seventeen jobs were once
    wrongly called overdue by exactly that collapse.
    """
    state = getattr(finding, "state", None)
    if state in WAKES_ALWAYS:
        return "integrity"
    for bucket, word in _ASKED_AS.items():
        if state in (WAKES_ON_FAILURE if bucket == "failure" else WAKES_ON_MISSING):
            response = getattr(workload, "response", None)
            asked = tuple(getattr(response, "notify_on", ()) or ()) if response else ()
            return bucket if word in asked else None
    return None


# ── dampening: what stops the same thing being said every half hour ──────────

#: Wall clock silence per key. Four hours and not watchdog.sh's twenty four:
#: that number is calibrated for nine keepalive services on a fifteen minute
#: tick with ONE key per service. Here the key is already per appointment, so
#: the same number would turn a whole day's outage of a five minute run into a
#: single message. To be re-measured after the first weeks in service.
BACKOFF_HOURS = 4

#: Re-measured, TWICE. A weekly job failed once and did not run again before
#: its next scheduled appointment five days later: the SAME sentence,
#: unchanged, fired every 4h for two days straight (11 deliveries, streak=104
#: in the live state file), through a chat thread where the recipient asked
#: TWICE to stop repeating it and it kept going regardless. A flat interval
#: cannot tell "still broken, as expected until the next run" from "broken
#: again, new information" - only the fingerprint can, and it already does
#: that job.
#:
#: The first correction made the wait GROW instead of staying flat (doubling,
#: capped at 48h) and shipped believing that closed it. It did not: the very
#: next scheduled repeat still went out on the still-flat first doubling step,
#: read to the recipient as "you said this was fixed and it happened again",
#: and a cap that still fires every two days is still "the whole week" to
#: someone who has already been told once. Growing the wait answers "how
#: annoying is each repeat" when the actual question was "how many times may
#: an unchanged, already-acknowledged fact be repeated at all": two, ever, per
#: fingerprint - the first telling and one reminder in case it was missed.
#: After that this key is fully quiet until the fingerprint itself changes
#: (it resolves, or it breaks differently); the workloads page stays the
#: living record for as long as that silence lasts.
MAX_REPEATS = 2

#: Messages that actually ARRIVED, per day, across everything. Six and not
#: eight, because a phone is more easily worn out than a dashboard.
DAILY_CAP = 6

#: Only `stopped` waits for a second look. A line already written to disk does
#: not become truer by being read twice, and `overdue` carries its grace
#: upstream in reconcile. `stopped` reads a live measurement that flickers
#: around a restart, which is exactly the case watchdog.sh's DEBOUNCE_RUNS=2
#: was written for.
PASSES_BEFORE_ALARM = {"stopped": 2}

_ORDER = {"integrity": 0, "failure": 1, "missing": 2}


@dataclass(frozen=True)
class Dispatched:
    """What this pass did. Never what it meant to do."""

    sent: int = 0
    suppressed: int = 0
    note: str = ""


def fingerprint(finding) -> str:
    """What makes this the SAME trouble as last time, or a new one.

    It is the verdict's own sentence, hashed. Not the timestamp parsed back out
    of it: the sentence already contains the trace stamp for a failed run and
    the computed due moment for a missing one, so parsing would be a second
    derivation of a value the first one already carries, and this skill has
    lost runs twice to exactly that pair.

    For a verdict with no anchor in it (a retired unit still live, a moved
    grant) the sentence is constant, so the fingerprint is constant and the
    wall clock alone decides. That is the intended behaviour, not a gap.

    The cost is honest and small: rewording a sentence makes one alarm read as
    new, once.

    ONE EXCEPTION, for a failed run: its sentence carries the stamp of THAT run,
    and a run that fails again every five minutes made a new fingerprint at
    every pass, so neither the backoff nor the two-tellings cap ever applied
    (2026-10-07: the same two findings at 07:43, 08:13, 08:44, 09:14). A stamp
    is when it failed, not what failed. For a failure the stamps are blanked
    before hashing, so the same exit code on the same run is one incident, and
    a changed exit code is still a new one. `missing` keeps its due moment: a
    new missed appointment is new news.
    """
    import hashlib
    import re
    detail = str(getattr(finding, "detail", ""))
    if getattr(finding, "state", None) in WAKES_ON_FAILURE:
        detail = re.sub(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?(\.\d+)?"
                        r"(Z|[+-]\d{2}:?\d{2})?", "<stamp>", detail)
    return hashlib.sha256(detail.encode("utf-8")).hexdigest()[:16]


def _key(finding, bucket) -> str:
    return f"{finding.workload_id}|{getattr(finding, 'appointment', '') or ''}|{bucket}"


def _load_state(path):
    """The remembered state, and whether it survived. Never raises."""
    import json
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"keys": {}, "day": "", "delivered_today": 0}, ""
    except Exception as exc:                       # noqa: BLE001
        # A torn write resets every streak and backoff at once, so the next
        # pass re-announces everything already settled. That storm has to be
        # readable AS a lost state and not as a real multi-incident.
        return ({"keys": {}, "day": "", "delivered_today": 0},
                f"previous notify state was unreadable ({type(exc).__name__}), "
                f"counters start again")
    if not isinstance(raw, dict):
        return ({"keys": {}, "day": "", "delivered_today": 0},
                "previous notify state was not an object, counters start again")
    raw.setdefault("keys", {})
    raw.setdefault("day", "")
    raw.setdefault("delivered_today", 0)
    return raw, ""


def _save_state(path, state) -> None:
    """Written through a temporary file, like both existing watchdogs.

    A target path written in place and caught mid-write by a reboot leaves
    exactly the broken file `_load_state` has to recover from, without anybody
    having made that happen on purpose.
    """
    import json
    import os
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


#: In front of the all-clear's title. Followed by the alarm's own title, verbatim: a
#: receiver that filed the alarm under a key made of that title (the inbox does) finds it
#: again by stripping this prefix. The default; `workloads.notify_text.recovered_prefix`
#: replaces it, and a receiver keyed on the prefix has to know the configured one too.
RECOVERED_PREFIX = "recovered: "

#: Every word a message is made of, in English. An instance writes its own
#: under `workloads.notify_text` in bridge-config.yaml; what it leaves out falls
#: back to these, key by key (and `problems` entry by entry), so a half
#: translated configuration still never produces an empty title.
#:
#: Added 2026-10-13, after a day of alarms titled with nothing but a job's name
#: over "ended with 143, and said so in its own trace at 2026-10-13T02:59:51+00:00".
#: The run had been cut off by its time limit at 04:59 local time, and nothing in
#: the message said so.
TEXT_DEFAULTS = {
    "title_one": "{title}: {problem}",
    "title_many_failed": "{n} runs failed",
    "title_many": "{n} runs need attention",
    "line": "{name}: {problem}{when}{after}",
    "line_plain": "{name}: {detail}",
    "line_todo": "\n  what to do: {todo}",
    "when": ", {moment}",
    "after": " after {minutes} min",
    "moment": "{weekday} {day:02d}.{month:02d}. {hour:02d}:{minute:02d}",
    "weekdays": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    "timezone": "",
    "todo_none": "no repair is recorded for this verdict",
    "todo_mixed": "each run below names its own repair",
    "capped": "further findings are suppressed for the rest of today; "
              "the full picture stays on the workloads page",
    "recovered_prefix": RECOVERED_PREFIX,
    "recovered_line": "{name}: was: {said}",
    "recovered_todo": "nothing to do, it works again",
    "unknown_host": "unknown host",
    #: Repair sentence per problem key (see `problems`), used when the
    #: declaration has no `reconcile.hint`. Empty: the finding's own sentence.
    "todos": {},
    "problems": {
        "timed_out": "run cut off, time limit exceeded",
        "killed": "run killed",
        "transient": "network or temporary failure",
        "not_found": "program not found",
        "not_executable": "program not executable",
        "failed": "run failed (exit {rc})",
        "failed_no_rc": "run failed",
        "stopped": "not running, or its check says the effect is missing",
        "overdue": "did not run when it was due",
        "absent": "gone from the machine",
        "retired_but_live": "retired, yet still live on the machine",
        "grant_orphaned": "its privacy grant points at another program",
        "other": "{state}",
    },
}


def texts(cfg) -> dict:
    """The configured words over the defaults. Never raises on a missing block."""
    raw = getattr(cfg, "notify_text", None) if cfg is not None else None
    merged = dict(TEXT_DEFAULTS)
    merged["problems"] = dict(TEXT_DEFAULTS["problems"])
    merged["todos"] = dict(TEXT_DEFAULTS["todos"])
    if isinstance(raw, Mapping):
        for key, value in raw.items():
            if key in ("problems", "todos") and isinstance(value, Mapping):
                merged[key].update({str(k): str(v) for k, v in value.items()})
            elif value is not None:
                merged[str(key)] = value
    return merged


def _problem_key(finding) -> str:
    """Which trouble this is, named by what the machine recorded, never guessed."""
    state = getattr(getattr(finding, "state", None), "value", "") or ""
    if state != "last_run_failed":
        return state or "other"
    rc = getattr(finding, "rc", None)
    verdict = getattr(finding, "verdict", "") or ""
    if verdict == "expired" or rc == 143:
        return "timed_out"
    if rc is None:
        return "failed_no_rc"
    return {137: "killed", 75: "transient", 127: "not_found",
            126: "not_executable"}.get(rc, "failed")


def problem(finding, text) -> str:
    phrases = text["problems"]
    key = _problem_key(finding)
    phrase = phrases.get(key) or phrases.get("other", "{state}")
    state = getattr(getattr(finding, "state", None), "value", "") or "unknown"
    return phrase.format(rc=getattr(finding, "rc", None), state=state)


def moment(stamp: str, tz: str, text) -> str:
    """A trace stamp (UTC) as the reader's wall clock. "" when it cannot be read."""
    from datetime import datetime, timezone
    try:
        when = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return ""
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    zone = None
    if tz:
        try:
            from zoneinfo import ZoneInfo
            zone = ZoneInfo(tz)
        except Exception:                          # noqa: BLE001 - unknown zone: host time
            zone = None
    local = when.astimezone(zone) if zone else when.astimezone()
    days = list(text.get("weekdays") or TEXT_DEFAULTS["weekdays"])
    return text["moment"].format(weekday=days[local.weekday() % len(days)], day=local.day,
                                 month=local.month, hour=local.hour, minute=local.minute)


def _name_of(finding, workload) -> str:
    title = str(getattr(workload, "title", "") or workload.id)
    appointment = getattr(finding, "appointment", "") or ""
    return f"{title} ({appointment})" if appointment else title


def _todo_of(finding, workload, text) -> str:
    # The DECLARATION's repair sentence first: it is written for this run, in the
    # operator's words ("65 means a human: local changes in the clone..."). The
    # finding's own is the machine's general advice and the fallback.
    declared = getattr(getattr(workload, "reconcile", None), "hint", None)
    configured = (text.get("todos") or {}).get(_problem_key(finding), "")
    return (str(declared or "").strip() or configured
            or str(getattr(finding, "hint", "") or "") or text["todo_none"])


def _has_run_facts(finding) -> bool:
    return getattr(finding, "rc", None) is not None or bool(getattr(finding, "at", ""))


def said_of(finding, text) -> str:
    """What the line says about the trouble, kept for the all-clear."""
    return problem(finding, text) if _has_run_facts(finding) else str(finding.detail)


def compose(entries, *, capped: bool = False, text=None):
    """`_compose`, but a configured sentence that does not format never crashes.

    A typo such as `{nmae}` in `workloads.notify_text` would raise KeyError and
    take the whole notify pass down with it. It is logged and the DEFAULT words
    are used, so the alert still goes out.
    """
    try:
        return _compose(entries, capped=capped, text=text)
    except (KeyError, IndexError, ValueError) as exc:
        logging.getLogger(__name__).warning(
            "notify_text does not format (%s: %s); using the default text",
            type(exc).__name__, exc)
        return _compose(entries, capped=capped, text=texts(None))


def _compose(entries, *, capped: bool = False, text=None):
    """One message out of everything this pass found. Pure.

    Bundled rather than one message per finding: several failures in one pass
    usually share one cause, and N messages burn N of the day's places for one
    incident. Each LINE still names its own run and appointment, so bundling
    costs no detail.

    The title names the TROUBLE, not only the job: one run reads "<title>:
    <problem>", several read "<n> runs failed" with one line each. A finding
    without run facts (a verdict that is not a trace line) keeps its own
    sentence in its line, because nothing better is known about it.
    """
    text = text or texts(None)
    first = entries[0]
    finding, workload, _bucket = first
    if len(entries) == 1:
        what = text["title_one"].format(title=_name_of(finding, workload),
                                        problem=problem(finding, text))
    else:
        all_failed = all(getattr(getattr(f, "state", None), "value", "") == "last_run_failed"
                         for f, _w, _b in entries)
        what = text["title_many_failed" if all_failed else "title_many"].format(n=len(entries))
    host = str(getattr(getattr(workload, "placement", None), "host", "") or "")
    where = host or text["unknown_host"]
    todos = [_todo_of(f, w, text) for f, w, _b in entries]
    shared = len(set(todos)) == 1
    todo = todos[0] if shared else text["todo_mixed"]
    lines = []
    for (one, w, _bucket), own_todo in zip(entries, todos):
        name = _name_of(one, w)
        if _has_run_facts(one):
            tz = getattr(getattr(w, "schedule", None), "timezone", None) or text.get("timezone") or ""
            at = moment(one.at, tz, text) if getattr(one, "at", "") else ""
            minutes = (getattr(one, "duration_sec", None) or 0) // 60
            line = text["line"].format(
                name=name, problem=problem(one, text),
                when=text["when"].format(moment=at) if at else "",
                after=text["after"].format(minutes=minutes) if minutes >= 1 else "")
        else:
            line = text["line_plain"].format(name=name, detail=one.detail)
        if not shared:
            line += text["line_todo"].format(todo=own_todo)
        lines.append(line)
    if capped:
        lines.append(text["capped"])
    return what, where, todo, "\n".join(lines)


def compose_recovery(entries, text=None):
    """The all-clear for alarms that were told and have since ended. Pure.

    `entries` are remembered state entries of ONE delivered message (same `alarm_what`),
    each carrying what it said, so neither the workload nor the old finding is needed.
    Added 2026-10-07: an alarm arrived in the middle of a failure and the end of the failure
    was never announced, so the reader had to open a page to find out.
    """
    text = text or texts(None)
    first = entries[0]
    what = text["recovered_prefix"] + str(first.get("alarm_what") or first.get("title") or "a run")
    where = first.get("host") or text["unknown_host"]
    lines = [text["recovered_line"].format(
                 name=e.get("name") or e.get("who") or "?",
                 said=e.get("said") or e.get("detail") or "n/a")
             for e in entries]
    return what, where, text["recovered_todo"], "\n".join(lines)


def _sender_for(spec):
    def send_one(*, what, where, todo, detail):
        return send(argv=argv_for(spec, what=what, where=where, todo=todo,
                                  detail=detail))
    return send_one


def dispatch(report, workloads, *, state_path, now, cfg=None, sender=None,
             cap: int = DAILY_CAP, backoff_hours: int = BACKOFF_HOURS,
             max_repeats: int = MAX_REPEATS) -> Dispatched:
    """One pass: route, dampen, say it once, and remember only what arrived."""
    by_id = {w.id: w for w in (workloads or ())}
    state, note = _load_state(state_path)
    text = texts(cfg)

    if sender is None:
        spec = notifier_spec(cfg)
        if spec is None:
            # Being unable to speak is itself the one thing this layer may never
            # be quiet about, so it comes back as a visible note that names the
            # key a reader has to set, rather than as an exception nobody
            # catches or a filename nobody chose.
            note = (note + '; ' if note else '') + (
                'no alarm path: workloads.notify_via is not configured, so '
                'nothing can be said')
            _save_state(state_path, state)
            return Dispatched(sent=0, suppressed=0, note=note)
        sender = _sender_for(spec)

    day = now.date().isoformat()
    if state.get("day") != day:
        state["day"] = day
        state["delivered_today"] = 0

    findings = list(getattr(report, "findings", ()) or ())
    # A host that did not answer is not news AND not recovery. Its runs keep
    # their remembered state untouched: counted as recovery, a flaky ssh hop
    # would tear a real ongoing incident in half and announce its second half
    # as new.
    unreachable = {f.workload_id for f in findings
                   if getattr(f, "state", None) in WAKES_NOBODY
                   and getattr(f, "state", None) is _unknown()}

    seen, candidates, suppressed = set(), [], 0
    for finding in findings:
        workload = by_id.get(getattr(finding, "workload_id", None))
        if workload is None:
            continue
        bucket = route(finding, workload)
        if bucket is None:
            continue
        key = _key(finding, bucket)
        seen.add(key)
        entry = dict(state["keys"].get(key) or {})

        needed = PASSES_BEFORE_ALARM.get(getattr(finding.state, "value", ""), 1)
        streak = int(entry.get("streak") or 0) + 1
        entry["streak"] = streak
        state["keys"][key] = entry
        if streak < needed:
            suppressed += 1
            continue

        if _waits_for_a_run(finding, workload, entry, report, now):
            suppressed += 1
            continue

        mark = fingerprint(finding)
        same = entry.get("fingerprint") == mark
        if same and int(entry.get("repeats") or 0) >= max_repeats:
            # Told, and told again. A THIRD identical message answers no
            # question the first two did not already answer, so this key
            # stays quiet regardless of the wall clock until the fingerprint
            # itself moves - the same rule the daily cap already applies at a
            # coarser grain, just per incident instead of per day.
            suppressed += 1
            continue
        if same and _within(entry.get("last_alert_at"), now, backoff_hours):
            suppressed += 1
            continue
        candidates.append((finding, workload, bucket, key, mark))

    # Everything that had a key and no longer has a finding recovered, unless
    # its host simply could not be asked this time.
    recovered = []
    for key in list(state["keys"]):
        if key in seen:
            continue
        if key.split("|", 1)[0] in unreachable:
            continue
        if state["keys"][key].get("last_alert_at"):
            # Only an alarm that ARRIVED earns an all-clear. The key stays until
            # the all-clear is delivered, so a failed send is tried again.
            recovered.append(key)
            continue
        state["keys"].pop(key, None)

    sent = 0
    pass_titles = set()
    if candidates:
        candidates.sort(key=lambda c: _ORDER.get(c[2], 9))
        room = cap - int(state.get("delivered_today") or 0)
        if room <= 0:
            suppressed += len(candidates)
            candidates = []
        else:
            capped = int(state.get("delivered_today") or 0) + 1 >= cap
            what, where, todo, detail = compose(
                [(f, w, b) for f, w, b, _k, _m in candidates], capped=capped, text=text)
            pass_titles.add(what)
            answer = sender(what=what, where=where, todo=todo, detail=detail)
            if getattr(answer, "delivered", False):
                sent = 1
                state["delivered_today"] = int(state.get("delivered_today") or 0) + 1
                stamp = now.isoformat()
                # ONLY after a confirmed delivery. The whole point.
                for _f, _w, _b, key, mark in candidates:
                    prior = state["keys"][key]
                    # Escalation survives only across the SAME fingerprint. A
                    # different sentence is different news and earns the
                    # prompt cadence back, exactly like backoff already did
                    # for the wall clock silence itself.
                    prior_repeats = int(prior.get("repeats") or 0) if prior.get(
                        "fingerprint") == mark else 0
                    named = f"{_w.id}.{_f.appointment}" if getattr(_f, "appointment", "") else str(_w.id)
                    state["keys"][key] = {"fingerprint": mark, "last_alert_at": stamp,
                                          "streak": prior.get("streak", 1),
                                          "repeats": prior_repeats + 1,
                                          "who": named, "detail": _f.detail,
                                          "name": _name_of(_f, _w),
                                          "said": said_of(_f, text),
                                          # Every title it was ever told under: each one
                                          # may be a separate item at the receiver.
                                          "alarm_whats": sorted(set(
                                              (prior.get("alarm_whats") or []) + [what])),
                                          "title": str(getattr(_w, "title", "") or _w.id),
                                          "host": str(getattr(getattr(_w, "placement", None),
                                                              "host", "") or "")}
            else:
                note = (note + "; " if note else "") + f"send failed: {answer.reason}"

    # One all-clear per alarm TITLE that ended. A title still carried by a key that is
    # failing (a bundled alarm, or the same run moving bucket) has NOT ended: its receiver
    # would close an item for trouble that is still there (review 2026-10-07). Such a title
    # is simply forgotten by the recovered key and cleared later by the key that still has it.
    held = set(pass_titles)
    for key in seen:
        held.update((state["keys"].get(key) or {}).get("alarm_whats") or [])
    groups = {}
    for key in recovered:
        entry = state["keys"][key]
        owed = [t for t in (entry.get("alarm_whats") or [entry.get("title") or ""]) if t not in held]
        entry["alarm_whats"] = owed
        if not owed:
            continue
        if _within(entry.get("clear_tried_at"), now, backoff_hours):
            suppressed += 1
            continue                # a failed all-clear waits like a failed alarm, not every pass
        for title in owed:
            groups.setdefault((title, entry.get("host") or ""), []).append(key)
    for (title, _host), keys in sorted(groups.items()):
        if cap - int(state.get("delivered_today") or 0) <= 0:
            suppressed += 1         # the cap counts what arrived, all-clears included
            continue
        entries = [dict(state["keys"][k], alarm_what=title) for k in keys]
        what, where, todo, detail = compose_recovery(entries, text=text)
        answer = sender(what=what, where=where, todo=todo, detail=detail)
        if getattr(answer, "delivered", False):
            sent += 1
            state["delivered_today"] = int(state.get("delivered_today") or 0) + 1
            for k in keys:
                state["keys"][k]["alarm_whats"] = [t for t in state["keys"][k]["alarm_whats"] if t != title]
        else:
            for k in keys:
                state["keys"][k]["clear_tried_at"] = now.isoformat()
            note = (note + "; " if note else "") + f"all-clear not sent: {answer.reason}"
    for key in recovered:
        if not state["keys"][key].get("alarm_whats"):
            state["keys"].pop(key, None)

    _save_state(state_path, state)
    return Dispatched(sent=sent, suppressed=suppressed, note=note)


def _waits_for_a_run(finding, workload, entry, report, now) -> bool:
    """True while a probe disagreement has not yet met the run that should fix it.

    2026-10-13 02:11: a new release of a tool appeared, the probe ("installed equals
    the newest tag") said no, and an alarm went out. The run that installs releases
    was due at 04:15. For a run that is idle between firings `stopped` can only come from
    its probe, and a probe disagreeing BEFORE the next firing is the world moving,
    not the run failing.

    So the first sighting is remembered, and the alarm waits until the machine's
    own trace shows a run AFTER it. If that run never comes, `overdue` says so on
    its own channel; if it comes and fails, `last_run_failed` does. A daemon is
    supposed to be up now, so it never waits here.
    """
    from datetime import datetime, timezone
    from engine import model
    if getattr(finding, "state", None) is not model.WorkloadState.stopped:
        return False
    kind = getattr(getattr(workload, "placement", None), "kind", "")
    if str(getattr(kind, "value", kind) or "") in model.CONTINUOUS_KINDS:
        return False
    since = entry.get("probe_since") or now.isoformat()
    entry["probe_since"] = since
    run = (getattr(report, "runs", None) or {}).get(finding.workload_id)
    if not run or not run[0]:
        return True
    try:
        ran = datetime.fromisoformat(str(run[0]).replace("Z", "+00:00"))
        first = datetime.fromisoformat(since)
    except ValueError:
        return False
    if ran.tzinfo is None:
        ran = ran.replace(tzinfo=timezone.utc)
    if first.tzinfo is None:
        first = first.replace(tzinfo=timezone.utc)
    return ran <= first


def _unknown():
    from engine import model
    return model.WorkloadState.unknown


def _within(stamp, now, hours) -> bool:
    from datetime import datetime, timedelta
    if not stamp:
        return False
    try:
        then = datetime.fromisoformat(str(stamp))
    except ValueError:
        return False
    return now - then < timedelta(hours=hours)
