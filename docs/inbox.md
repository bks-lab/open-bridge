---
summary: "The inbox: one place per Bridge where everything that needs a person waits until it is done. Item and event layout, derived states, gates, closing probes, who writes and reads, CLI reference."
type: guide
last_updated: 2026-10-17
related:
  - scripts/inbox.py
  - scripts/tests/test_inbox.py
  - scripts/tests/test_inbox_mute.py
  - work-system.md
  - ../protocols/standing-orders/inbox.md
  - ../work/templates/_schema.inbox-item.yaml
  - ../agents/_runtime/approval.py
  - ../scripts/inbox-approve.py
  - workplace.md
  - always-on-machine.md
---

# Inbox

## Why

A finding, a question from an agent, a decision, a draft waiting for its send:
each used to live wherever it happened to be written down. A sentence in the log,
a chat message, a mail from a scheduled job, a line in a STATUS.md. Nothing
closed them. A briefing that re-read those places reported things as open that
had been solved hours earlier, because the sentence saying "needed" was still
there and the one saying "done" was further down.

The inbox is the single place for everything that needs a person. An item stays
until it is done, and "done" is decided by the live source where possible (the
PR is merged, the file exists), not by someone remembering to cross it out.

## Layout

```
work/inbox/<id>/item.yaml          written once, never changed
work/inbox/<id>/events/*.yaml      one NEW file per change
work/inbox.md                      GENERATED view (python3 scripts/inbox.py render)
```

`item.yaml` carries `schema_version`, `created`, `from`, `kind`, `summary`,
`urgency`, `gate` and optionally `task`, `area`, `due`, `detail`, `key`, `action`
(`argv` and `label`, no shell) and `closes_when`. Schema:
[`work/templates/_schema.inbox-item.yaml`](../work/templates/_schema.inbox-item.yaml),
annotated example: [`work/templates/inbox-item.yaml`](../work/templates/inbox-item.yaml).

Every change is a **new event file**, never an edit. Verbs: `seen`, `note`,
`approve`, `reject`, `drop`, `defer`, `urgency`, `area`, `close`, `executed`, `failed`, `reopen`. Two machines
writing the same inbox through git therefore never touch the same file, and an
item id ends in a random tail, so two machines filing the same thing in the same
minute still create two folders. This is the property the task folders already have, and
`work/board.md` is derived from them for the same reason. The inbox state is
derived from events and never stored.

Kinds: `decision`, `question`, `finding`, `draft`, `result`, `idea`. An `idea`
waits on nobody: it ranks after every other kind and a briefing section can list
ideas apart (`kinds: [idea]`) or leave them out (`skip_kinds: [idea]`). Urgency: `now`,
`today`, `later`.

**Area.** An item linked to a task belongs to that task's area. One without a task may
carry an `area` of its own: the name of a workspace in `workplace.workspaces`
([`workplace.md`](workplace.md)), given with `add --area`, changed with `inbox.py area`
(the last `area` event wins, `--clear` takes it back). A name or alias in any case is stored
as the workspace's name; `area` refuses one that names no workspace, `add` warns and files
the item without it. The cockpit counts the item under that area instead of "No area", its
detail page has a picker to put it right, and a tab started for it opens in that workspace.

With `inbox.place_on_add: true` in `bridge-config.yaml`, an item filed through the CLI
(`inbox.py add`) with neither a task nor an area is placed by the router: `add` starts
`workplace.py place --pending` detached, so the filer never waits. That waits two seconds
for a burst to arrive, takes a lock so only one placer runs, and asks the configured
`workplace.router` once about every open item without a task or an area, each item once
per run; the answer is written as an `area` event by `router` with its reason. An item a
person gave an area meanwhile, or one that closed, is left as it is. Without a router, or
when it fails or names no configured workspace, the item stays without an area. Code that
files through the `Inbox` class (the briefing's own items, which mostly name a task) places
nothing; `workplace.py place --unplaced` catches up on every open item that has none yet
(`--dry-run` shows the answer and writes nothing).

## States

| State | Meaning |
|---|---|
| `open` | nobody has answered |
| `approved` | a person said yes, `run` may execute the action |
| `waiting` | a conditional yes is recorded, `run` executes when the condition holds |
| `deferred` | pushed to a later day with `defer --until` |
| `done` | closed (by a person or by `check`) or executed |
| `dropped` | rejected or dropped |

`open`, `approved` and `waiting` count as active and show in `list`.

A close by mistake is taken back with `reopen`, one more event: the item is `open`
again and every yes before it is void, so an executed action does not run a second
time without a new yes. A later close closes it again.

## Gates

- `free`: the Bridge may act alone. `run` executes the action without a yes. A
  failed free action waits for a person instead of retrying on every tick.
- `your-yes`: acts after a person's yes. A **conditional yes** is
  `approve --when-json '{"gh_pr": "contoso/portal#70", "state": "green"}'`
  ("merge once green"): the item is `waiting`, and `run` executes it when the
  condition holds.
- `only-you`: send, publish, pay. `run` never executes it, whatever was
  recorded, and a conditional yes on it is refused. The item exists so a person
  does the click.

## Probes (`closes_when`)

`check` evaluates each open item's `closes_when` against the live source and
closes what holds. Probes: `path_exists`, `command` (exit code, optional
`expect_exit`), `after` (a date), `gh_pr` (with `state` merged, closed, open or
green), `gh_issue` (with `state`), `task_status` (with `status`), `unseen_for`
(with `hours`), and `all` / `any` to combine them.

`unseen_for` (`{hours: N}`) is for reporters that refile the same `key` on every run
while a condition holds (a daily health report): the item closes when no run has
filed it for N hours, so a fixed finding leaves without anyone clearing a log. It
reads the item's own sightings (`seen` events), so it needs the item and is unknown
without one. A one-shot alarm does not carry it: that item waits for a person.

A probe that cannot be evaluated (no network, a typo, a missing task) is
**unknown, never true**. The item stays open rather than vanishing on an error.

## Every item needs a way out (`closer`)

An item without a probe stays open until somebody remembers it. `closer` says who
ends it instead: `reporter` (the job that filed it closes it by key once the
condition is gone: `inbox.py close --key <key>`), `person`, or `bot` (a watcher
that acts on it). `add` warns about a `finding` or `question` with neither
`closes_when` nor `closer`. It warns rather than refuses, because filers run
unattended and a refusal would lose the finding.

`bot` is also a routing promise: the item goes to a watcher that **looks first**.
It investigates before a person hears about it and ends in one of three ways:
nothing to do (the item closes with the cause as its note), a small fix it
prepares itself (a person only approves the result), or a recommendation with
options for the person. A report that already knows the answer says so when it
files: a finding that only informs (bad data on the sender's side, a delivery that
the retry recovered) stays in the report mail and becomes no item at all.

Each step of that work runs on a model chosen by **weight, not habit**, from
`bridge-config.yaml` `models:` (`reasoning` plans and judges, `analysis` builds
along a given path, `routine` sorts and extracts; the cockpit's `mechanical` and
`directed` names are read ahead of `routine` and `analysis` when set): critical
items and plans go to the reasoning tier, findings that can wait are sorted by
the routine tier, a fix runs on the analysis tier.

An alarm path that announces both the trouble and its end should close by key: the
all-clear carries the alarm's own title, so the receiver rebuilds the key it filed
the alarm under and closes that item rather than filing a new one.

A reporter that repeats an alarm may pass `--quiet-after-close-h N` to `add`. When
somebody closed an item under the same `key` within N hours and the detail is
unchanged (timestamps aside), the new sighting is only recorded as `seen` on the
closed item and nothing new is filed: the person who looked at it already
answered that exact text. A close by a probe or by the reporter's own all-clear
does not count, because then the trouble had ended and its return is news. An
all-clear is a close text that begins with `All clear`, or with one of the words
in `bridge-config.yaml` `inbox.all_clear` for reporters that write another language.

## Who writes

- A scheduled job on an always-on machine (a watcher that finds a red check or
  a stale PR).
- An agent or a terminal tab that reached a point where it needs a person.
- The briefing's own checks, when they find something to act on.
- A peer Bridge, but only through its own front door (an A2A request that a
  local job files), never by writing into this repository.
- The session itself, at the end of a unit of work (see the standing order
  [`inbox`](../protocols/standing-orders/inbox.md)).

**The rule: a finding files an item only when somebody has to act.** Green stays
quiet. Use `--key` for anything that can fire again: a repeat of an open item
with the same key adds a `seen` event, not a second item.

## Who reads

- The briefing, first: it runs `check` and reads the inbox instead of
  re-deriving "open" from the log.
- Phone and e-ink digests, as short views: `python3 scripts/inbox.py list --short`
  prints one line per item.
- A control tab, which can show `work/inbox.md` or the JSON of `list --json`.

## CLI

```bash
python3 scripts/inbox.py add --from homebox/issue-radar --kind decision \
    --summary "PR #70 is green and waits for a merge" --task portal-relaunch \
    --action-json '{"argv": ["gh", "pr", "merge", "70", "-R", "contoso/portal"]}' \
    --closes-when-json '{"gh_pr": "contoso/portal#70", "state": "merged"}'
python3 scripts/inbox.py list [--all] [--json] [--short]   # open items, most urgent first
python3 scripts/inbox.py show <id>                         # item plus its events; an unambiguous id prefix works
python3 scripts/inbox.py approve <id> [--when-json '{...}'] [--text "edited draft"]
python3 scripts/inbox.py reject|close|drop <id> [--note "why"]
python3 scripts/inbox.py drop <id> --reason once|duplicate|family|source   # family and source leave a mute rule
python3 scripts/inbox.py mute list [--json]                 # the mute rules in force
python3 scripts/inbox.py unmute <rule-id>                   # lift one
python3 scripts/inbox.py stats [--days 30] [--json]         # per source: filed, dropped by a person, muted
python3 scripts/inbox.py reopen <id> [--note "why"]           # take a close, drop or reject back
python3 scripts/inbox.py close --key <key> [--note "why"]     # every live item filed under that key
python3 scripts/inbox.py defer <id> --until 2026-10-08
python3 scripts/inbox.py urgency <id> now|today|later       # re-rank; the latest urgency event wins
python3 scripts/inbox.py area <id> <workspace> | --clear    # the area of an item without a task
python3 scripts/inbox.py note <id> "Sam will answer on Monday"
python3 scripts/inbox.py check                             # close what the live source says is done
python3 scripts/inbox.py run [--dry-run]                   # execute what a person released
python3 scripts/inbox.py render                            # regenerate work/inbox.md
python3 scripts/inbox.py validate                          # structure of items and events
python3 scripts/inbox.py sync [--no-push]
```

`--by` (or `$BRIDGE_ACTOR`, default the host name) sets who an event is
attributed to. `add` takes `--area`, `--due`, `--detail`, `--key`, `--urgency` (default
`today`) and `--gate` (default `your-yes`). Items are `from` a machine and job
(`homebox/issue-radar`), not a person.

## Dropping with a reason, and muting a loud source

A drop that says nothing teaches nothing. `drop --reason` records why, as
part of the `drop` event:

| Reason | Means | Leaves |
|---|---|---|
| `once` | not worth it this time | nothing; the key stays dropped as before |
| `duplicate` | already known elsewhere | nothing |
| `family` | never this kind again | a rule: the source plus the key up to its last colon (`health:crash:1a20` mutes `health:crash:`), or the source plus the kind when the key has no family (such a rule leaves keys with a family alone) |
| `source` | this source is too loud | a rule: everything of the source for 30 days (`MUTE_SOURCE_DAYS`) |

A rule is a file of its own under `work/inbox/_mutes/`, so two machines never
write the same file and `sync` carries it to the machine that files. The `_`
keeps the folder out of the item list. A finding that matches a rule is
**still filed** and dropped at once by `mute`, with the rule's id on the
event: nothing is lost, it counts in `stats`, and `reopen` brings it back. An
item filed with `--urgency now` is never muted, so a muted source cannot
swallow an outage, and a muted key that comes back as `now`, or after its rule is gone, is reopened. A source mute ends by itself, a family mute stays until
`unmute` lifts it.

`stats` counts, per source, the items filed in the last N days: how many a
person dropped (with the reasons, `unknown` for a drop without one), how many
a rule muted, how many closed or are still open. `share` is what a person had
to drop out of what was filed, the clicks the source cost; muted items are
counted apart, so a source that was muted and then fixed comes down again.
The loudest source is the filer to sharpen: a stable key, a tighter rule, or
reports that belong in a digest rather than the inbox.

## Two machines, one inbox

`inbox.py sync` stages and commits **only** `work/inbox/`, rebases onto the
upstream and pushes. Nothing else in the working tree is committed, and the push
is refused when the branch carries unpushed commits outside `work/inbox/`: syncing
the inbox never ships unfinished work along with it. Because each change is its
own new file, the rebase has nothing to merge; if it still fails it is aborted
and the commit stays local for the next sync. The generated `work/inbox.md` is
not part of a sync: every render rewrites its time stamp, so two machines
committing it would conflict every time. Commit it like `work/board.md`, from
the one machine you work on, or not at all.

**Exactly one runner.** `run` executes on every machine that calls it, and two
machines would both see an approved item before the other's `executed` event
arrived. Name the one that acts in `bridge-config.yaml`:

```yaml
inbox:
  runner: homebox      # the actor (--by / $BRIDGE_ACTOR / host name) that executes actions
  all_clear: []        # further words an all-clear close text may begin with, besides "All clear"
```

Everywhere else `run` prints "not running" and does nothing. Without the key
every machine runs, which is right for a Bridge on one machine only.

**Trust.** An item can carry a command (`action.argv`, a `command` probe). Anyone
who can push into `work/inbox/` can therefore make the runner execute something,
exactly as anyone who can push a script the runner calls already can: the inbox
is as trusted as the repository, and no more. Peer Bridges never write here.
`list`, `show` and `work/inbox.md` always print the command a yes would run, and
an `only-you` item executes nothing at all, not even a `command` probe.

**Time.** Events are stamped in UTC with an offset and ordered by that, so a
laptop in one time zone and an always-on machine in another agree on what came
first.

## Relation to the approval runtime

[`agents/_runtime/approval.py`](../agents/_runtime/approval.py) holds an agent's
outbound answer until a person approves it. An approver command can file the
held answer as an inbox item (kind `draft`, gate `only-you`) so it shows up where
everything else waits, and the person's `approve --text` releases an edited
version. That bridge is the script `scripts/inbox-approve.py`, written separately
from this model.
