# reconcile: is it still there

Read-only, always. `reconcile` may propose an inventory patch; it never applies
one, and no step it runs may change anything.

It asks three sources and never a declared status field:

| Source | Says |
|---|---|
| `workflow/workloads/*.yaml` | what should be there |
| the machine, asked live | what is there |
| `infra/remotes/<host>.yaml` `services[]` | what the inventory knows |

`classify()` is pure, so the whole state machine is provable without a machine.

## The thirteen states

The enum is closed. A new situation maps onto one of these, or the enum grows
deliberately together with a scenario that produces it.

### Anchored on the declaration

| state | severity | Means | Repair |
|---|---|---|---|
| `in_sync` | info | the unit matches its stamp and the artifact it was provisioned from | nothing |

### Which verdict wakes somebody

`reconcile --notify` sends what the declarations asked to be told about,
through the one notification path the instance declared in
`workloads.notify_via` (a program and its argv template). It is OFF by
default: a command somebody types to LOOK must not page anyone, and without the
flag the dampening state is not touched either.

| bucket | verdicts | gated by `notify_on` |
|---|---|---|
| `failure` | `last_run_failed`, `stopped` | yes, needs `failure` |
| `missing` | `overdue`, `absent` | yes, needs `missing` |
| `integrity` | `retired_but_live`, `grant_orphaned` | **no** |
| nobody | everything else, including `unknown` | n/a |

**A daemon that failed and has been up since is history.** The guard writes its
line when the run ENDS, so a `daemon` or `agent` that the service manager reports
running now started after its newest line. When that line is a failure at least
ten minutes old (`RESTARTED_MARGIN_SEC`, so a crash loop between two restarts
still speaks), the report carries one calm `info` note ("restarted after exit 75
at ... and has been running since") instead of `last_run_failed`. Guards rendered
since the `started` line need no such reading; older ones on a machine do. A
scheduled run keeps the rule above: idle between firings, `running` says nothing.

**`notify_on` does not cover everything that speaks, and that is deliberate.**
Opt-in fails exactly where the declaration is out of date: nobody edits
`notify_on` on the way out while retiring a run, so `retired_but_live` (the
loudest thing this skill says, and possibly a security incident) would sit
behind a field the retiring hand never touched. `grant_orphaned` is worse still
— the run it describes ends `rc=0` and is simply shown nothing, so no trace can
ever carry it. A gate in front of a state the gate's own vocabulary cannot name
is a permanent blind spot. `grant_orphaned` is already opt-in through another
field: it exists only where `placement.privacy_grants` is declared.

`unknown` never wakes anybody, and it counts as neither a hit nor a recovery.
The reconcile driving this reaches its hosts over ssh, so one closed laptop lid
produces `unknown` for every run on every host at once.

Dampening, all of it per `(run, appointment, bucket)`:

- a **fingerprint** of the verdict's own sentence decides what counts as the
  same trouble; a changed one speaks through the silence, so a second failure
  six hours later is not swallowed as the first one still standing
- **4 hours** of wall clock silence per key, not watchdog.sh's 24: that number
  is calibrated for one key per service, and here the key is already per
  appointment
- **6 delivered messages a day**, counting what ARRIVED and never what was
  attempted. A cap on intentions was once exhausted after eleven runs with
  nothing having gone out, and silenced the whole machine for the rest of that
  day
- only `stopped` waits for a **second consecutive pass**; it reads a live
  measurement that flickers around a restart, while everything else here is a
  line already written to disk
- the backoff is recorded **only after a confirmed delivery** (`exit 0`)
| `drifted` (source `declaration`) | medium | the file on disk has changed since this was provisioned | provision it again |
| `not_provisioned` | info | declared, never provisioned | run `provision` when it should exist |
| `absent` | high | provisioned once, and nothing carries it any more | provision again, or retire the declaration if it is meant to be gone |
| `stopped` | high | present but not running, or its probe says otherwise | read the unit's log, then bootout and bootstrap. Never kickstart |
| `drifted` | medium | the unit is not what the stamp records, or only one of the two ownership signals is there | provision again so both signals agree |
| `unstamped` | high | a matching unit exists with neither stamp nor marker | `adopt` it to take ownership without downtime. It is never overwritten |
| `retired_but_live` | high | the declaration is retired and the unit is nonetheless there | bootout and disable with the retirement reason, then verify it stopped |
| `observed` | info | owner `human` or `foreign`, or runtime `manual` or `external` | nothing. Documented so it is visible, never touched |
| `unknown` | medium | nobody could answer | see below |

`retired_but_live` is the loudest thing this skill can say. There is a real
declaration for which a start would be a security incident, and the point of
retiring something is undone the moment it comes back.

### Anchored on the machine

| state | severity | Means | Repair |
|---|---|---|---|
| `orphan_stamp` | medium | an ownership stamp with no declaration behind it | restore the declaration, or retire the workload so the stamp goes with it |
| `unmanaged` | info | a live unit that no declaration claims | declare it to make it visible, or leave it alone. This skill never touches it |

`unmanaged` is counted rather than listed. On a real machine it is dozens of
entries per host, and a report nobody reads to the end trains everyone to skip
the line that mattered. `--verbose` lists them. It is never dropped: a count that
changes is still a signal.

### Anchored on the inventory

| state | severity | Means | Repair |
|---|---|---|---|
| `inventory_missing` | medium | declared and live, but no `services[]` entry | add the entry. `--propose-inventory` prints the snippet |
| `inventory_stale` | info | a `services[]` entry with neither a declaration nor a live unit | remove the entry, or find out what happened to it |

Matching an inventory entry goes by label, then by slug, then by the command
path. An ambiguous match yields `unknown` rather than a guess: an inventory
holds seventy entries per host and a wrong pairing invents drift that is not
there.

## `unknown` never collapses into `absent`

This is the rule the state machine exists to hold. Four situations produce
`unknown`, and every one of them means "nobody answered", not "it is gone":

1. **The host did not answer.** Unreachable, or the connection deadline expired.
2. **The probe expired.** An expired deadline is unknown, never a fail.
3. **The expect cannot be evaluated.** One real declaration expects a German
   sentence rather than a pattern. Judging prose with a matcher is a coin flip
   dressed as a check, so it comes back as unknown with that reason.
4. **The probe carries an unresolved placeholder.** One real declaration probes a
   URL whose host is still `<placeholder>`. Running it would resolve a literal
   hostname, so it is not run at all.

Both of the last two are declarations that exist today, and they are a case to
build for rather than a defect to fix in them. Collapsing unknown into absent is
how seventeen jobs were once declared overdue when they were merely unobserved.

An unreachable host degrades only its own workloads. It never aborts the report
about the other machines.

## The probe

Precedence: the declaration's own `probe`, else `reconcile.check_ref` into
`workflow/checks/`, else the backend's default probe.

A `check_ref` is `<group>/<check-id>`. A bare id that exists in more than one
group raises rather than picking one: two disk-free checks measure different
volumes on different hosts, and picking either would be a guess.

`expect` uses the same vocabulary the check registry already uses, so an operator
learns one language and not two:

| expect | Meaning |
|---|---|
| (none) | the exit code decides |
| plain text | substring of stdout, whitespace normalised |
| `re:...` | regular expression search |
| `not:...` | the substring must be ABSENT |
| `>= <= > < == !=` | numeric compare; a non-numeric answer is unknown, never fail |

A declared probe is a user-authored shell string and runs as the one explicit
shell in this skill: bounded by a deadline, in its own session, killed as a
process group. Empty output alone is never treated as proof of anything.

## Reading the output

One line per finding: what is odd, then what to do about it. A clean report is a
single line, and that is the point. Exit code `1` when any high or medium finding
exists, `4` when every requested host was unreachable.
