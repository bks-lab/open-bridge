---
name: workload
description: >-
  Manages the whole life of a declared run on a machine: declare, provision,
  reconcile, adopt, and retire it. Declarations live in
  workflow/workloads/<id>.yaml; state reads from the live service manager
  (launchd, systemd, cron), never a status field. Trigger: "workload", "declare
  a run", "is the job still there", "reconcile the machine", "retire the job".
metadata:
  scope: core
allowed-tools:
  - Bash(python3:*)
  - Read
  - Grep
  - Glob
---

# Workload

One declared run, on one machine, with an owner. The declaration in
`workflow/workloads/<id>.yaml` is the source of truth; the unit file on the
machine is an artifact and may be rebuilt from the declaration at any time.

The engine is `skills/workload/engine/` behind the shim `skills/workload/workload.sh`.
The data is the declaration plus `_schema.yaml` and `_template.yaml` next to it.
Nothing instance specific lives in the code: hosts come from `infra/remotes/`,
paths and prefixes from the `workloads:` block of `bridge-config.yaml`.

## Guard

`workloads.enabled` must not be `false` in `bridge-config.yaml`. A missing block
means defaults, never a crash. A `false` refuses every subcommand with exit `3`
and names the key and the file it read.

`reconcile --notify` speaks through the program declared in
`workloads.notify_via`, never through a name this skill knows:

```yaml
workloads:
  notify_via:
    command: ["~/bin/my-notifier", "--subject", "{what}", "--host", "{where}",
              "--action", "{todo}"]
    detail:  ["--body", "{detail}"]        # appended only when there is detail
```

Substitution is per argv element, so a value with a space stays one argument.
With no `notify_via`, `--notify` sends nothing and says so, naming the key: an
alarm path this skill invented would be a dependency the repository does not
ship.

## Reporting

A watcher or poller that notices something a person must act on declares
`reports_to: inbox` and files it with `inbox.py add --key <stable-key>` and a
`closes_when` probe (`references/declare.md` § 7, `docs/workloads.md`).

## Commands

```
workload list       [--host H] [--kind K] [--runtime R] [--owner O] [--scope S] [--retired] [--json]
workload show       <id> [--render] [--json]
workload validate   [<id>...] [--all] [--strict]
workload declare    <id> --kind K --runtime R --host H [--title T] [--purpose P] [--command ARGV...] [--timeout-sec N] [--force]
workload render     <id> [--offline --uid U --home P]
workload provision  <id> [--dry-run] [--yes] [--force] [--accept-degraded] [--enable]
workload adopt      <id> [--yes]        # a hand made unit: declare its placement.label_prefix
workload reconcile  [<id>...] [--all] [--host H] [--no-probe] [--verbose] [--propose-inventory] [--json] [--notify]
workload view       [<id>...] [--host H] [--no-probe] [--out PATH] --now STAMP [--poll-sec S] [--group-by band|system] [--json]
workload publish    [<id>...] [--host H] [--no-probe] --to HOST --dest DIR --now STAMP [--page-name NAME] [--attach PATH]... [--url URL] [--stale-after-min N] [--poll-sec S] [--group-by band|system] [--yes]
workload retire     <id> --reason TEXT [--superseded-by ID] [--keep-artifact] [--yes] [--dry-run]
```

Exit codes: `0` clean, `1` findings or applied-but-unverified, `2` usage or
declaration error, `3` refused by a guard, `4` unreachable or a deadline expired.
The `4` exists so an expired deadline can never be mistaken for a clean run.

Why each exit is what it is, and what `view`, `publish`, `retire` and `adopt`
promise in detail: [`references/commands.md`](references/commands.md).

## Decision tree

| The request is about | Read |
|---|---|
| writing a new declaration, which questions to ask, what stays a reference | [`references/declare.md`](references/declare.md) |
| provisioning, adopting, retiring, a refusal code, moving an existing service | [`references/provision.md`](references/provision.md) |
| "is it still there", the state list, what `unknown` means | [`references/reconcile.md`](references/reconcile.md) |
| which runtime can carry what, and how to add another one | [`references/backends.md`](references/backends.md) |
| what a command guarantees: an exit code, `view`/`publish` output, `retire`/`adopt` reports | [`references/commands.md`](references/commands.md) |

Read a reference only when its row is the one that applies.

## The four rules that shape everything here

1. **Every outbound call carries a deadline, and an expired one is a reported
   error.** Never silence, never a synthetic return code somebody can ignore.
2. **A deadline kills the process group, not the direct child.** A grandchild
   that survives keeps the output pipe open and the cleanup after it blocks
   forever.
3. **Nothing is started that is still running.** On the control plane a kernel
   lock per id; on the run plane the guard script's single flight.
4. **State is evidenced, never read off a declared field or an exit code.**
   `reconcile` asks the live source; `provision` proves the result at the live
   object before it reports success.

## Secrets: the locator travels, the value never does

`execution.env` takes a reference and nothing else (`keychain://…`,
`azure-keyvault://…`, `op://…`), and the schema enforces that shape. **The
reference is what reaches the unit file, unchanged.** Nothing here resolves it,
and nothing here may: a resolved secret would be written into a unit file on
disk, which is the one place it must not be. The program named in
`execution.command` resolves its own locator at run time, in its own process.

Say it out loud when writing a declaration, because the field reads like a
promise that somebody fetches the value. Pinned in both backends by
`tests/test_backends.ALocatorReachesTheUnitAsItStands`.

## What this skill does NOT do

- **No general-purpose visualisation, and no data from anywhere else.** This
  skill is not a dashboard renderer. `view` and
  `publish` do draw, calendar and history strips included, but only this skill's
  own material: the declarations under `workflow/workloads/`, the `services[]`
  inventory in `infra/remotes/<host>.yaml`, and what `reconcile` read off the
  machines in the same run. Nothing computed elsewhere earns a row. A configured
  panel is not an exception to that: it FRAMES a neighbour's page, parses nothing
  out of it and repeats none of its numbers, so nothing is adopted and nothing is
  drawn twice. The rule protects against asserting what no probe in this run
  verified and against two renderers of one number drifting apart; a frame does
  neither. A figure some
  other producer computed is not adopted, because the page would then assert
  something no probe in that run verified, and a second renderer of the same
  numbers drifts from the first the day one of them is fixed. Another page about
  the same machines stays its own program with its own output directory, which is
  the other half of why `publish` refuses a destination it does not own.
- **No general RRULE evaluation.** Each backend translates a restricted subset
  into its own idiom and refuses everything else by name. An RRULE parser that
  silently understands only `FREQ=DAILY` turns every weekly entry into a single
  fire, and the calendar looks plausible afterwards. General recurrence belongs
  to the dispatcher.
- **No sudo, ever.** A run that needs elevation yields a printed plan for a
  person, and a later run verifies the result. Escalating silently on a machine
  carrying live services is not on the table.
- **No writes to `infra/remotes/`.** `reconcile --propose-inventory` prints a
  `services[]` snippet for a human to paste. This skill owns
  `workflow/workloads/`, not the host inventory.
- **No probe registry of its own.** `workflow/checks/` stays separate: a probe is
  not work, it is the question whether the work is there. Merging them would put
  the inspector inside the thing it inspects.
- **No secrets.** Neither a declaration nor the ownership stamp carries a
  credential, and the stamp carries no user name either.

## Files

| Path | What it is |
|---|---|
| `workload.sh` | shim: resolves its own real path, then runs the engine |
| `engine/` | the implementation, stdlib plus PyYAML and nothing else |
| `tests/`, `run-tests.sh` | the suite, plus `--mutate` for the proof that it has teeth |
| `workflow/workloads/_schema.yaml` | the contract a declaration is validated against |
| `workflow/workloads/_template.yaml` | what `declare` scaffolds from, comments and all |
