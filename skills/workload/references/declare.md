# declare: writing a declaration

`declare` writes one file under `workflow/workloads/<id>.yaml` and touches no
machine. The conversational half is this document; the deterministic half is the
subcommand, which scaffolds from `workflow/workloads/_template.yaml` and keeps
its comments.

Nothing is written before the human has confirmed the summary at the end.

## The interview, in this order

The order is not cosmetic. Each answer narrows the next question, and asking
them the other way round produces combinations that have to be taken back.

### 1. What is it, in one sentence

Becomes `purpose`. A declaration whose purpose reads "runs the script" explains
nothing a year later. Name the outcome, not the mechanism.

`title` is optional and falls back to `id`. The `id` is a stable slug, matches
the filename, and never changes: it is what the ownership stamp on the machine
records.

### 2. Which machine

Becomes `placement.host` and must resolve against `infra/remotes/<host>.yaml`.
The host decides the platform, and the platform decides which runtimes are even
available. Ask this before the runtime, never after.

`local` is allowed and means the machine the skill runs on; its platform is
detected, never assumed.

### 3. What shape of run is it (`kind`)

| kind | The question it answers | The schedule field it needs |
|---|---|---|
| `recurring` | at which appointments does it happen | `rrule` + `delivery_at` |
| `interval` | how often does it repeat | `every_sec` |
| `daemon` | it is meant to be up, all the time | none |
| `agent` | it listens for something inbound | none |
| `watch` | it reacts to a path changing | `watch_paths` |
| `oneshot` | it happens once, at a time | `at` |

`kind` and `runtime` are separate on purpose. An existing inventory calls both a
06:30 weekday report and an "every 900 seconds" poller "scheduled", and they are
not the same thing: one has appointments, the other only a cadence. Keeping them
apart is what lets a later view draw appointment ticks for one and a cadence band
for the other without inventing times that never existed.

### 4. What carries it (`runtime`)

The host's platform has already removed most of the answers:

| platform | available |
|---|---|
| macos | `launchd`, `launchd-system`, `cron`, `dispatcher` |
| linux | `systemd`, `cron`, `dispatcher` |

Plus `manual` and `external`, which are available everywhere and are never
provisioned: they exist so a run somebody starts by hand, or one a third party
platform manages, is still visible. See `backends.md` for what each one can
carry and what it promises.

Two combinations are refused rather than approximated, and both refusals name
the remedy: `oneshot` on `launchd` or `systemd` (a run that happens once has no
appointment to repeat), and `daemon` or `watch` on `cron`.

### 5. Who owns it (`owner`)

`bridge` means this skill may create, replace and retire it. `human` and
`foreign` mean it is documented so it is visible, and never touched. An owner
that is not `bridge` makes every later command read-only for that declaration,
which is the point: the inventory is only honest if the things nobody controls
are in it too.

### 6. What runs (`execution`)

`command` is an argv array, never a shell string.

`placement.interpreter` is emitted **verbatim** when present. It is the client
path a permission grant hangs off, so nothing resolves, normalises or
"stabilises" it: a resolved path is a different client with no grant. This is the
opposite of the rule for the unit file path, which is physically resolved before
it is loaded, because a service manager refuses a symlinked unit path.

#### The process keeps its name

Verbatim emission is what happens **after** a path is chosen. Choosing one is a
separate act, and it has one rule: **the path carries no version number.**

Two independent failures hang on that character sequence, and both are silent.

1. **The file goes away.** A versioned directory exists in order to be replaced.
   The upgrade that installs the successor deletes the one the declaration
   names, and the unit starts nothing.
2. **The grant goes away with it.** macOS keys a privacy grant on the literal
   client path, so the next version is a client nobody ever answered a prompt
   about. The run is then not denied. It is shown nothing, which arrives as an
   empty inbox, an empty calendar, a quiet day.

This is measured rather than argued. A real user TCC database holds six
consecutive rows for the same tool under `.../versions/<version>`, five of them
granting nothing, because every update wrote a path whose prompt had never been
answered. The same database carries one binary twice, once under a package
manager path that moves with every upgrade and once under a stable path that
does not. Both gates refuse the first shape; a segment with no dot is not a
version, so `report2` and `python3` pass untouched.

The signature does not rescue this. A Developer-ID signature makes the stored
requirement content independent, so a grant survives the binary CHANGING at one
path, but nothing makes it survive the path itself moving. An ad-hoc signature
pins the content hash on top, so even editing the file at a stable path ends the
grant. The practical shape that follows: put the stable, granted client at a
path you control (a frozen copy under a `bin` directory of your own), keep
that file frozen, and let all the churn live behind it in
the script or module it starts, which the grant system never sees.

#### `placement.privacy_grants`

Declare the macOS panes this run depends on, and only if it depends on them:

```yaml
placement:
  interpreter: /opt/bridge/bin/uv-calendar   # your own frozen copy, not a shared one
  privacy_grants: [full-disk-access]
```

It claims nothing about the machine. macOS lets no program read the grant
database, so a declaration says what a run NEEDS and never what it HAS; anything
else would be a guessed all-clear, which is worse than silence.

It changes two things. The interpreter stops being free: a grant needs a client
path, so one is required, and the interpreters the whole machine shares are
refused. Granting Full Disk Access to `/usr/bin/python3` does not grant it to
this workload, it grants it to every python script the box will ever run. That
scar is already paid here once, by a calendar exporter that needed a total read
and would have handed the same total read to an internet reachable agent through
a shared interpreter. The fix was a second frozen copy at its own path.

And it lets `reconcile` answer a question nothing else can. The stamp records
the client path as it stood at provisioning, so when the declaration later names
a different one, the grant is still on the old path and the report says so, with
both paths and the pane to open. Where a stamp predates that field it says it
cannot tell, rather than passing in silence.

#### Running one by hand proves nothing about the job

A command started from an interactive session inherits **that session's**
identity, not the unit's. Read a protected path from a terminal and you are
measuring the terminal; read it over ssh and you are measuring sshd, which holds
Full Disk Access and will answer yes to a question the real job answers no to.

The only honest probe is a run in the service manager's own context: a temporary
unit, loaded, result written to a file, then unloaded and removed. That is also
why the workload's own program path matters more than it looks. Under launchd
the client is the unit's own executable, so a job provisioned once keeps its own
grant and is unaffected by whatever the tooling around it updates to.

For every kind the Bridge both owns and executes (`recurring`, `interval`,
`watch`, `oneshot`) three fields are mandatory and the invariant gate refuses the
file without them:

- `timeout_sec`: a real deadline. A run without one held a machine for three
  and a half hours and nobody noticed until the next morning.
- `response.evidence`: how a run proves it happened.
- an owner of `bridge`, which is what makes the other two enforceable.

`isolation` defaults to `process-group`, `single_flight` to `true`, `on_timeout`
to `report`. Each of those defaults is an incident, so an absent field arrives as
the safe value and never as nothing.

### 7. How does it answer (`response`)

The normal case is silence. A report that arrives says nothing, or the channel is
muted within two weeks and then missing when it counts.

`notify_on` picks what breaks the silence: `failure` (non-zero), `timeout` (the
deadline expired), `missing` (the run did not happen at all). The third is the
important one: an absent run is the failure nobody sees.

`transient_exit_codes` names the codes a run uses for "failed, try again next
tick", usually `75` (EX_TEMPFAIL, for example a fetch while the network is
briefly gone). The first such failure right after a clean run wakes nobody; a
second failure in a row does, and so does a first run with no clean run before
it. Only the program's own `failed` verdict counts: an `expired` run was cut off
by a deadline and speaks at once. Codes not listed speak at once, so name only
the code the script really reserves for a blip and keep everything critical off
the list. Without the field every failure speaks at once.

`evidence` says how much the run can actually prove:

| evidence | It claims |
|---|---|
| `exit-code` | only the exit status; the guard writes no trace line |
| `log-trace` | one line per run, so an absent run is detectable at all |
| `delivery-receipt` | the run printed a receipt token, captured beside the trace |

Do not declare more than the command delivers. A receipt field over a command
that prints no receipt is exactly the green tick that checks nothing.

**`evidence` and `notify_on` are coupled, and the gate enforces it.** The guard
writes the trace line only where `notify_on` asks about `missing` or `failure`.
So a declaration naming `log-trace` or `delivery-receipt` with neither of those
is naming a proof nothing will produce, and `validate` refuses it.

That refusal exists because the silent version happened: a run was declared
with `log-trace` and an empty `notify_on` on purpose (it sits on a laptop, so a
push on every failed run would be loudest when it means least). Both gates
passed it, it was provisioned, it ran, it exited zero and wrote nothing, and
`reconcile` then called it `in_sync` because a trace that was never written
looks exactly like one nobody has read yet.

Two ways out, and they are different answers, not a preference:

- add `missing` to `notify_on`, if an absent run should actually be reported;
- or say `exit-code`, if the service manager's exit status really is the proof.

**And a promise to report a failure needs a script that can return one.** Where
`notify_on` asks about `failure` and `execution.command` names a script that
lies inside this repository, `validate` reads that file and refuses it when its
last line is a bare `exit 0`. Such a script returns zero however the run went,
so the guard writes `verdict=ok`, and every link after it works faultlessly on
an input that never arrives.

The measurement that produced this rule: 441 traces over three days, all
`verdict=ok`, not one non-zero exit, across three runs whose wrappers could not
have produced one. Two of them even carried a written reason for the `exit 0`,
and it confused retrying with reporting. Not retrying is a fair decision; a
failure that cannot be said out loud is a different thing.

**Three shapes, three rules, one sentence.** The same defect wears three faces,
and each has its own predicate rather than one widened one:

- the last line of the script is a bare `exit 0`;
- the handler of an EXIT trap ends in `exit 0` and runs over the top of
  whatever the last line returned;
- the script catches a return value and then has no exit left that could carry
  it.

Measured against the six real repairs of one day, each broken version is caught
by exactly one rule and each repaired version by none, and against a corpus of
eighty five shell scripts the two added rules have no hit at all. A script that
fits two of them is reported ONCE, in the order of certainty: the last line of
a file is the plainest fact, an EXIT trap is next, and reachability is the one
that approximates control flow by position in a file.

Each rule stays silent where it cannot know. Reachability says nothing under
`set -e` (the script then ends on the failing command itself, before the catch
line is reached) nor after an `exec` (the process image is replaced), nor when
a loud exit follows, including one inside the body of a function called after
the catch. The trap rule says nothing about a handler bound only to SIGNALS: a
stop on request is not a failure and such a handler should end in zero, and
widening it would forbid exactly the repair that produced this rule.

What the trap rule cannot know, and reports anyway: whether the trap is still
armed when the script ends. A later `trap - EXIT` at the top level is invisible
to it.

Four silences are deliberate as well: nothing promised, no path inside this
repository (it may be a path on another machine whose home is not this one), a
file that is not there (a different fact, and reporting an absence as a
violation would fire on every machine that keeps the file elsewhere), and bytes
that do not decode (a binary has no last line).

### The files a guarded run leaves behind

All of them sit in the stamp directory, named after the id:

| file | written when | bounded by |
|---|---|---|
| `<id>.guard.sh` | at provision | rendered, not grown |
| `<id>.stamp.json` | at provision | one record |
| `<id>.trace` | one line per run, where the evidence is a trace | one line per run |
| `<id>.out` | every run, unless the evidence is a receipt | truncated per run, capped at 256 KiB |
| `<id>.receipt` | where `evidence: delivery-receipt` | one run's output |

`<id>.out` is what a run SAID. It exists because a service manager hands a unit
no output destination unless one is named, and this skill names none: without
it the run speaks into `/dev/null`. That is expensive for any command that
warns and then exits zero, which is a common shape for a report that does not
retry.

It is deliberately not `StandardOutPath`. A service manager appends there and
never rotates, and unrotated log files are one of the conditions this skill was
built to end. Truncating at the start of each run bounds the file across runs;
the cap after the run bounds it within one, which truncation alone does not.

### 8. Who hears about it (`recipients`)

**Recipients stay references.** A declaration carries `mandant:` or `person:`
and never an address. Two reasons, and the first is the hard one:

1. A file with a plain address in it is not promotable. It carries a person into
   whatever tier the file reaches, and the scope router cannot take that back.
2. An address changes in one place then, not in every declaration that names it.

The invariant gate refuses any other key under a recipient.

### 9. How do we know it is still there (`reconcile`)

Optional, and the precedence is: a declared `probe` wins, else a `check_ref` into
`workflow/checks/`, else the backend's own default probe.

`expect` is a pattern, not a sentence: a plain substring, `re:` for a regular
expression, `not:` for something that must be absent, or a leading comparison
operator for a numeric compare. An expect written as prose cannot be evaluated
and comes back as `unknown` with that reason stated. That is deliberate: a prose
expect judged by a matcher is a coin flip dressed as a check.

A probe that still carries an unresolved `<placeholder>` is never run, for the
same class of reason: running it would resolve a literal hostname.

## `delivery_at` means the DELIVERY

For a `recurring` run, `delivery_at` is when the result is due and
`duration_estimate_min` is how long the run takes, so the unit fires at
`delivery_at` minus `duration_estimate_min`.

This is the field most likely to surprise somebody moving an existing job: a job
that used to name its START time will, once declared this way, deliver earlier
than it does today. Say so before the move, or it reads as a regression.

The subtraction can cross midnight. `00:10` minus twenty minutes is `23:50` on
the previous day, and every backend carries the day shift with it.

`timezone` is an IANA zone. Where a backend can only place an appointment in the
machine's own zone, a differing declared zone is refused rather than silently
drifting by an hour at the next daylight saving change.

## Before the file is written

Show the human the resolved summary and wait:

- id, host, kind, runtime, owner
- the resolved start time, and for a recurring run the sentence "the result is
  due at X, so it starts at Y"
- what the runtime guarantees natively and what a guard script will supply, and
  above all what nothing can supply on that runtime
- the recipients as references, spelled out as the references they are
- whether the file will be created or overwritten

Then write, then run `workload validate <id>`. The declaration is validated
twice by design: by the hand-written invariant gate in the engine, and, under
`--strict`, by `check-jsonschema` against `_schema.yaml`. Two gates reading the
same document would be one gate with a second name, so the first is written by
hand and can fail differently. When the external validator is not installed that
is reported as `schema_validator_absent`, never skipped quietly, and it exits 1:
a gate that could not run has not passed. The same holds when `_schema.yaml`
itself is missing — reported as `schema_missing`, once and not per declaration,
and deliberately not as `invalid`: the declarations were never read, and calling
them refused sends you to fix a file that is in order.
