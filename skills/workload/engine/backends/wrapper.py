"""The guard script: what a backend does not promise, supplied around the run.

Four promises can be missing, and every one of them has a scar behind it:

  deadline            a run without one held a machine for three and a half
                      hours and nobody noticed until the next morning
  process group kill  ending only the direct child leaves a grandchild holding
                      the output pipe, and the cleanup then blocks forever,
                      which is the exact shape of that hang
  single flight       one job lost 53 of 181 runs to overlapping starts, in
                      silence
  missing detection   a run that never happened is the failure nobody sees; a
                      trace line per run is what makes its absence visible

The script is POSIX sh. Not bash: `/bin/sh` on macOS is not bash, and a bashism
here fails at 06:10 on a machine nobody is watching. It does not reach for
`timeout(1)` either, because a stock macOS does not ship it.
"""

from __future__ import annotations

import shlex

from . import base
from engine.model import (
    MARKER_ENV_APPOINTMENT,
    MARKER_ENV_DIGEST,
    MARKER_ENV_ID,
    Guarantee,
    ensure_id_safe,
    required_guarantees,
)

#: What a guard script can supply at all. `missing_detection` is on this list
#: only because the trace line makes an absent run provable; see `supplies`.
SUPPLIABLE = frozenset({
    Guarantee.deadline,
    Guarantee.process_group_kill,
    Guarantee.single_flight,
    Guarantee.missing_detection,
})

#: Kinds with no per-run boundary. A daemon has no run that ends, so a deadline
#: around it would not guard the run, it would end the service.
CONTINUOUS_KINDS = frozenset({"daemon", "agent"})

#: Evidence levels under which the script writes a trace line. `exit-code`
#: claims nothing beyond the exit status, so it writes nothing: a trace under
#: that evidence would be a stronger claim than the declaration makes.
TRACING_EVIDENCE = frozenset({"log-trace", "delivery-receipt"})

#: Ceiling for the captured output of ONE run, in bytes. Truncating at the
#: start of each run bounds the file across runs; this bounds it within one,
#: which truncation alone does not. 256 KiB holds a long report and refuses a
#: runaway.
OUT_CAP_BYTES = 262144


#: The PATH every guard script names. A service manager hands its unit no login
#: PATH at all, so a bare tool name inside a command resolves to nothing unless
#: this line exists -- and to the WRONG thing unless the package manager
#: prefixes come first. See the comment the guard itself carries.
GUARD_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"


def supplies(w, backend) -> frozenset:
    """What a guard script would add for this workload on this backend.

    Empty means no guard script is written at all: there is nothing to add, or
    nothing to wrap around (a declaration without a command), or the backend is
    not one that runs a command line of ours (a registry entry has no wrapper).
    """
    if not getattr(backend, "wrappable", True):
        return frozenset()
    if not base.command_of(w):
        return frozenset()

    possible = set()
    if w.placement.kind not in CONTINUOUS_KINDS and base.timeout_of(w):
        possible.add(Guarantee.deadline)
        possible.add(Guarantee.process_group_kill)
    possible.add(Guarantee.single_flight)
    if base.evidence_of(w) in TRACING_EVIDENCE:
        possible.add(Guarantee.missing_detection)

    return frozenset((required_guarantees(w) & possible) - backend.guarantees)


def guard_path(w, ctx, guard_dir=None, appointment=None) -> str:
    """Where the guard script is WRITTEN. The id decides the file, not its text.

    Same reason as the unit path in the two service-manager backends: a slash in
    the id does not name the file differently, it puts the bytes in a directory
    nobody declared.
    """
    directory = guard_dir or ctx.stamp_dir
    # One guard per UNIT. Two appointments render DIFFERENT guards (their trace
    # files differ), so one path for both would have the second overwrite the
    # first and leave one unit running the other one's script.
    name = ensure_id_safe(w)
    appointment_name = getattr(appointment, "name", "") or ""
    if appointment_name:
        name = f"{name}.{appointment_name}"
    return f"{directory.rstrip('/')}/{name}.guard.sh"


def guard_argv(path: str) -> tuple:
    """How a unit invokes the guard. `/bin/sh` exists everywhere sh exists."""
    return ("/bin/sh", path)


def wrap(w, ctx, inner, *, guard_dir=None, supplied=None, digest: str = "",
         appointment=None) -> base.RenderedFile:
    """Render the guard script for `inner`, supplying exactly `supplied`."""
    supplied = frozenset(supplied if supplied is not None else SUPPLIABLE)
    path = guard_path(w, ctx, guard_dir, appointment)
    directory = path.rsplit("/", 1)[0]
    deadline = Guarantee.deadline in supplied
    group_kill = Guarantee.process_group_kill in supplied
    single_flight = Guarantee.single_flight in supplied
    traced = Guarantee.missing_detection in supplied
    receipt = traced and base.evidence_of(w) == "delivery-receipt"
    command_present = bool(base.command_of(w))
    # The id is written into this script in two shapes, and only one of them was
    # quoted. `shlex.quote` covers the assignment; the four state file paths
    # below interpolate it INSIDE double quotes, where a `"` ends the string and
    # everything after it is the next command. `render` is reachable with a
    # Workload nobody validated, so the slug rule is asserted here rather than
    # hoped for upstream, and after it holds every one of those paths is a slug.
    safe_id = ensure_id_safe(w)
    quoted_id = shlex.quote(safe_id)
    # The MARKER keeps the declaration id: it answers "whose unit is this", and
    # both appointments belong to the same declaration. The STATE FILES are
    # named after the unit instead, because "did the midday run happen" and
    # "did the morning run happen" are two questions and one shared trace
    # answers neither: a single fire would read as proof of both, and `missing`
    # would never be raised for the one that did not.
    appointment_name = getattr(appointment, "name", "") or ""
    state_id = f"{safe_id}.{appointment_name}" if appointment_name else safe_id

    out = []
    add = out.append
    add("#!/bin/sh")
    add(f"# Guard script for the workload {safe_id!r}, rendered by the workload skill.")
    add("#")
    add("# Do not edit. It is rendered from the workload's own file, and an edit")
    add("# here is reported as drift on the next pass, never taken as an")
    add("# improvement. It supplies what the backend underneath does not promise:")
    for guarantee in sorted(str(g.value if hasattr(g, "value") else g) for g in supplied):
        add(f"#   {guarantee}")
    add("set -u")
    add("")
    add("# A service manager gives no login PATH. Naming it is the difference")
    add("# between a run and a line in a log nobody reads.")
    add("#")
    add("# The package manager prefixes come FIRST, and that is the half this")
    add("# line was missing. `/usr/bin:/bin:/usr/sbin:/sbin` reaches the base")
    add("# system and almost nothing an operator installs: measured on a real")
    add("# machine, `gh` did not resolve at all under it and `python3` resolved")
    add("# to the system one, which carries no third party module. A job moved")
    add("# onto this guard would have swapped a working report for an empty")
    add("# one, exit code zero and no error anywhere.")
    add("#")
    add("# Both prefixes, and no platform branch: /opt/homebrew/bin is Apple")
    add("# Silicon, /usr/local/bin is Intel and most Linux boxes, and a")
    add("# directory that does not exist costs a lookup and nothing else.")
    add("# Ahead of /usr/bin rather than behind it, because behind it changes")
    add("# nothing for a name the base system also ships, which is the case")
    add("# that actually matters.")
    add(f"PATH={GUARD_PATH}")
    add("export PATH")
    add("")
    add(f"{MARKER_ENV_ID}={quoted_id}")
    add(f"{MARKER_ENV_DIGEST}={shlex.quote(digest)}")
    add(f"export {MARKER_ENV_ID} {MARKER_ENV_DIGEST}")
    if appointment_name:
        add(f"{MARKER_ENV_APPOINTMENT}={shlex.quote(appointment_name)}")
        add(f"export {MARKER_ENV_APPOINTMENT}")
    for key in sorted(base.env_of(w)):
        add(f"{key}={shlex.quote(str(base.env_of(w)[key]))}")
        add(f"export {key}")
    add("")
    add(f"STATE_DIR={shlex.quote(directory)}")
    add('mkdir -p "$STATE_DIR" || exit 71')

    if deadline:
        add(f"DEADLINE_SEC={int(base.timeout_of(w))}")
        add(f"EXPIRED_FLAG=\"$STATE_DIR/{state_id}.expired\"")
        add('rm -f "$EXPIRED_FLAG"')
    if traced:
        add(f"TRACE_FILE=\"$STATE_DIR/{state_id}.trace\"")
    if receipt:
        add(f"RECEIPT_FILE=\"$STATE_DIR/{state_id}.receipt\"")
    elif command_present:
        # What the run SAID, kept for exactly as long as it is the newest
        # thing said.
        #
        # A service manager hands a unit no output destination unless one is
        # named, and this renderer named none: under launchd the run spoke
        # into /dev/null. Found on 2026-08-24 while moving a daily health
        # report off its old unit, which DID name StandardOutPath. That report
        # prints `WARN: email_ops fehlgeschlagen` and then exits ZERO on
        # purpose, because it does not retry. The warning was the only sign
        # that the mail never left, and the move discarded it.
        #
        # Why not StandardOutPath: launchd appends there and never rotates.
        # This skill exists partly because 1428 unrotated log files were found
        # on one machine; an unbounded file is a different defect, not a fix.
        #
        # Bounded twice, on purpose. Truncating at the start bounds it ACROSS
        # runs, and the cap after the run bounds it WITHIN one, which
        # truncation alone does not: a single verbose run can still write a
        # gigabyte.
        add(f"OUT_FILE=\"$STATE_DIR/{state_id}.out\"")
        add(f"OUT_CAP_BYTES={OUT_CAP_BYTES}")
    add("")

    if traced:
        add("# One line per run: this is what makes an absent run detectable at")
        add("# all. Without it, nothing distinguishes a run that failed from a")
        add("# run that never started.")
        # The name the LINE carries. Not the ownership marker above, which
        # answers a different question: whose unit this is, and both units
        # of a run belong to the same declaration. A line, unlike a file,
        # travels: it gets copied into a ticket, grepped across both
        # files, merged into one timeline. Naming only the declaration
        # made the two units write sentences that read identically.
        add(f"BRIDGE_WORKLOAD_TRACE_ID={shlex.quote(state_id)}")
        add("trace() {")
        if receipt:
            add("    receipt=$(tail -n 1 \"$RECEIPT_FILE\" 2>/dev/null || printf '')")
            add("    printf '%s workload=%s rc=%s duration_sec=%s verdict=%s receipt=%s\\n' \\")
            add("        \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\" \"$BRIDGE_WORKLOAD_TRACE_ID\" \\")
            add("        \"$1\" \"$2\" \"$3\" \"$receipt\" >> \"$TRACE_FILE\"")
        else:
            add("    printf '%s workload=%s rc=%s duration_sec=%s verdict=%s\\n' \\")
            add("        \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\" \"$BRIDGE_WORKLOAD_TRACE_ID\" \\")
            add("        \"$1\" \"$2\" \"$3\" >> \"$TRACE_FILE\"")
        add("}")
        add("")

    if single_flight:
        add(f"LOCK_DIR=\"$STATE_DIR/{safe_id}.lock\"")
        add("# mkdir is atomic on every POSIX filesystem, which a test-then-write")
        add("# is not. A directory whose holder is gone is reclaimed; a live one")
        add("# ends this run before it starts anything.")
        add('if mkdir "$LOCK_DIR" 2>/dev/null; then')
        add("    :")
        add("else")
        add("    holder=$(cat \"$LOCK_DIR/pid\" 2>/dev/null || printf '')")
        add('    if [ -n "$holder" ] && kill -0 "$holder" 2>/dev/null; then')
        if traced:
            add("        trace 0 0 skipped")
        add("        exit 0")
        add("    fi")
        add('    rm -rf "$LOCK_DIR"')
        add('    mkdir "$LOCK_DIR" 2>/dev/null || exit 75')
        add("fi")
        add('printf \'%s\\n\' "$$" > "$LOCK_DIR/pid"')
        add("trap 'rm -rf \"$LOCK_DIR\"' EXIT")
        add("")

    command = base.shell_command(inner)
    working_dir = base.working_dir_of(w)
    if working_dir:
        add(f"cd {shlex.quote(str(working_dir))} || exit 72")
    add("started=$(date +%s)")

    # stderr goes in with stdout: the warning this capture exists for is
    # printed there, and splitting them would need a second file to keep
    # bounded for no gain.
    #
    # DECIDED ABOVE THE BRANCH, and that placement is the whole fix. It used to
    # live inside the `if deadline:` arm, so a kind that has no deadline ran
    # bare however correct the value was. A daemon has none by contract, and
    # the file above was still defined for it and still capped below it: the
    # guard prepared a destination, trimmed it, and never wrote a word.
    #
    # Found on 2026-08-30 by migrating a static file server, a
    # `python3 -m http.server` whose old unit named StandardErrorPath. That field WAS its access log,
    # because http.server prints every request it serves to stderr. The last
    # line in that file carries the minute of the cutover; a request ten
    # minutes later left no byte anywhere. The three daemons that moved before
    # it escaped only because their own wrappers redirect, which is luck and
    # not a guarantee.
    #
    # WHAT IT COSTS FOR A KIND THAT DOES NOT END, said out loud rather than
    # discovered later: truncating at the start bounds the file across runs,
    # and a daemon has one run that lasts weeks, so the cap below only bites
    # when it finally exits. That is the same unbounded shape this file refuses
    # for StandardOutPath a few lines up. It is taken anyway, because the
    # choice here is not between bounded and unbounded, it is between a bounded
    # file and NO file. Rotating underneath a guard that is blocked in `wait`
    # is a different piece of work and does not belong in the branch that
    # decides where the bytes go.
    if receipt:
        redirect = ' > "$RECEIPT_FILE" 2>&1'
    elif command_present:
        redirect = ' > "$OUT_FILE" 2>&1'
    else:
        redirect = ""

    # A kind that does not end writes its trace only when it dies. A daemon
    # that crashed in a loop and then ran cleanly for weeks kept "failed" as
    # its newest line, and reconcile called a healthy service broken for twelve
    # days. A line at START makes "running since" the newest thing it says; a
    # later crash still writes its own `failed` after it.
    if traced and w.placement.kind in CONTINUOUS_KINDS:
        add("trace 0 0 started")
        add("")

    if deadline:
        if group_kill:
            add("# The run needs a process group of its own, or the watchdog can")
            add("# only end the direct child and a grandchild keeps the output")
            add("# pipe open. `setsid` puts it in one deterministically, and it")
            add("# is reached for FIRST because the shell route is not reliable:")
            add("# dash refuses job control without a controlling terminal, which")
            add("# is exactly how cron starts things, and there /bin/sh IS dash.")
            add("# Started without job control on purpose, so the background job")
            add("# is not already a group leader and setsid does not fork away")
            add("# from the pid this script waits on.")
            add("if command -v setsid >/dev/null 2>&1; then")
            add(f"    setsid {command}{redirect} &")
            add("else")
            add("    # No setsid (a stock macOS has none). Monitor mode is the")
            add("    # fallback where the shell can arrange it; the watchdog reads")
            add("    # the group back and decides from what it actually finds.")
            add("    set -m 2>/dev/null || :")
            add(f"    {command}{redirect} &")
            add("    set +m 2>/dev/null || :")
            add("fi")
        else:
            add(f"{command}{redirect} &")
        add("CHILD=$!")
        add("# No timeout(1): a stock macOS does not ship it. A watchdog that")
        add("# counts in whole seconds needs nothing but sh, ps and sleep.")
        add("(")
        add("    waited=0")
        add('    while [ "$waited" -lt "$DEADLINE_SEC" ]; do')
        add('        kill -0 "$CHILD" 2>/dev/null || exit 0')
        add("        sleep 1")
        add("        waited=$((waited + 1))")
        add("    done")
        add('    kill -0 "$CHILD" 2>/dev/null || exit 0')
        add('    : > "$EXPIRED_FLAG"')
        if group_kill:
            add('    run_group=$(ps -o pgid= -p "$CHILD" 2>/dev/null | tr -d " ")')
            add('    own_group=$(ps -o pgid= -p $$ 2>/dev/null | tr -d " ")')
            add('    if [ -n "$run_group" ] && [ "$run_group" != "$own_group" ]; then')
            add("        # The run has a group to itself: end it whole. A")
            add("        # grandchild holding the output pipe dies with it, which")
            add("        # is the difference between a cleanup and a hang.")
            add("        kill -TERM -$run_group 2>/dev/null")
            add("        sleep 2")
            add("        kill -KILL -$run_group 2>/dev/null")
            add('    elif [ "$own_group" = "$$" ]; then')
            add("        # One group for this whole run, and it belongs to nobody")
            add("        # else: a service manager starts each job that way. The")
            add("        # guard goes down with it, so the record is written first.")
            if traced:
                add('        trace 143 "$DEADLINE_SEC" expired')
            if base.on_timeout_of(w) != "kill-silent":
                add("        printf '%s reached its deadline of %ss and was ended\\n' \\")
                add("            \"$" + MARKER_ENV_ID + "\" \"$DEADLINE_SEC\" >&2")
            add("        kill -TERM -$own_group 2>/dev/null")
            add("        sleep 2")
            add("        kill -KILL -$own_group 2>/dev/null")
            add("    else")
            add("        # Shared group, and not ours to end: killing it would")
            add("        # take the caller down too. Only the run itself is ended,")
            add("        # and the shortfall is said out loud rather than hidden.")
            add("        printf '%s: no process group of its own, only the run "
                "itself was ended\\n' \\")
            add("            \"$" + MARKER_ENV_ID + "\" >&2")
            add('        kill -TERM "$CHILD" 2>/dev/null')
            add("        sleep 2")
            add('        kill -KILL "$CHILD" 2>/dev/null')
            add("    fi")
        else:
            add('    kill -TERM "$CHILD" 2>/dev/null')
            add("    sleep 2")
            add('    kill -KILL "$CHILD" 2>/dev/null')
        add(") &")
        add("WATCHDOG=$!")
        add("# stderr of `wait` is dropped because a shell with job control")
        add("# announces a signalled job there, and that announcement carries the")
        add("# whole watchdog into the service log on every deadline.")
        add('wait "$CHILD" 2>/dev/null')
        add("rc=$?")
        add('kill "$WATCHDOG" 2>/dev/null')
        add('wait "$WATCHDOG" 2>/dev/null')
    else:
        add(f"{command}{redirect}")
        add("rc=$?")

    if command_present and not receipt:
        # After the run, never during it: a pipe here would sit between the
        # guard and the pid it waits on, and the watchdog reads that group
        # back to decide what to end.
        add('if [ -s "$OUT_FILE" ]; then')
        add('    tail -c "$OUT_CAP_BYTES" "$OUT_FILE" > "$OUT_FILE.cap" 2>/dev/null \\')
        add('        && mv -f "$OUT_FILE.cap" "$OUT_FILE" \\')
        add('        || rm -f "$OUT_FILE.cap"')
        add("fi")
        add("")

    add("finished=$(date +%s)")
    add("duration=$((finished - started))")
    add("")

    if deadline:
        add('if [ -f "$EXPIRED_FLAG" ]; then')
        add('    rm -f "$EXPIRED_FLAG"')
        if base.on_timeout_of(w) != "kill-silent":
            add("    # An expired deadline is a reported error, never silence.")
            add("    printf '%s reached its deadline of %ss and was ended\\n' \\")
            add("        \"$" + MARKER_ENV_ID + "\" \"$DEADLINE_SEC\" >&2")
        if traced:
            add('    trace "$rc" "$duration" expired')
        add('    exit "$rc"')
        add("fi")
    if traced:
        add('if [ "$rc" -eq 0 ]; then')
        add('    trace "$rc" "$duration" ok')
        add("else")
        add('    trace "$rc" "$duration" failed')
        add("fi")
    add('exit "$rc"')

    return base.RenderedFile(path=path, mode=0o755, content="\n".join(out) + "\n")
