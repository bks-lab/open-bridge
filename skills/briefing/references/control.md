# Briefing as the control room: inbox first, one thing first, every line a lever

The rest of `workflow.md` gathers. This file decides what the person sees first and
what they can do from it. It runs in two places: **Phase 0.5** (before the streams)
and **Phase 4** (the top of the output). Model of the inbox: `docs/inbox.md`.
Workplace: `docs/workplace.md`. The always-on machine: `docs/always-on-machine.md`.

## The rule this file exists for

**Nothing is reported as open from the log.** A log row saying "needed" is history;
whether it is still needed is a question for the live source. A briefing that read
the log reported three things as open that had been solved hours earlier. Open is
what the inbox says after `check`, plus what a tracker or calendar says live.

## Phase 0.5: settle the inbox (always, also with `--quick`)

```bash
python3 scripts/inbox.py check            # close what the live source says is done
python3 scripts/inbox.py run --dry-run    # what a person already released and is ready
python3 scripts/inbox.py run              # execute it (free, a yes, or a yes whose condition holds)
```

`run` never executes an `only-you` item (send, publish, pay), whatever was recorded,
and never anything nobody released. Report every `ran` and every `failed` line
in the output; a `failed` item is back to open and belongs on top. When
`inbox.runner` names another machine, `run` says "not running" and the briefing
shows the `--dry-run` list as "ready, waiting for <runner>" instead.
No `work/inbox/` yet: skip silently; the first item creates it.

## After the streams: advise

**With a profile, skip this section:** an `advise` section next to a `calendar`
section gets the calendar from the engine (`briefing.py collect`/`render`), so
the collision check already ran. The commands below are for a Bridge without a
profile, or a profile without an `advise` section.

Once Stream C has today's and tomorrow's calendar, write it as a JSON list of
`{"title", "start", "end"}` to a temp file and run:

```bash
python3 skills/briefing/scripts/advise.py --file --calendar-json "$TMP/calendar.json"
python3 skills/briefing/scripts/advise.py --json --calendar-json "$TMP/calendar.json"
```

`--file` turns collisions, quiet tasks, long blocks and WIP over the cap into inbox
items under stable keys (a repeat stays one item; a finding that is gone closes its
own item). The `--json` run adds the report-only lines (`waiting`, `due`). Without a
calendar the collision check is skipped, everything else runs. Thresholds:
`briefing.advise` in bridge-config.yaml.

Then `python3 scripts/inbox.py list --json` is the source for the top of the output.

## Phase 4 with a view: the script's shape is the output, not the whole briefing

When the profile has `view.style` other than `sources` (or the person asked for
`--style`), run `python3 scripts/briefing.py render [<id>] --file`. The buckets,
the order, the numbering, the Calendar block and the housekeeping are computed
there (docs/briefings.md § Views). `--file` already opened today's day block,
wrote the briefing's log row and regenerated the board; do not do those again.

**Show the rendered text verbatim** at the top of your answer: in a code block,
except for `style: report`, whose Markdown goes in as it is so its tables render.
The person does not see tool output: a table that summarises the view, or "see
above", is a briefing they never got. Do not regroup, re-sort, shorten or drop
rows. With `view.overview: file` the Boards and Activity blocks are in the file
housekeeping names; do not paste the file as well unless the person asks for it,
the short copy is the point.

**Then the owed streams, and only those.** The view covers what the profile's
sections cover. `python3 scripts/briefing.py owed [<id>]` names every stream
that applies to this Bridge and that no section covers, each with the way to run
it; housekeeping repeats the list. Run exactly those, the way `owed` says, and
nothing else: a stream it does not name is covered or does not apply, and running
it again by hand (a second PR search, your own config queries) only adds
improvised commands that can fail. What an owed stream finds goes below the view
as rows in the same bucket words, numbered on from the view's last number.

**Never a second row for something the view shows.** A detail that sharpens a
row (the disk is at 99 %, not just over 90 %) is a note on that row by its
number ("zu 3: ..."), not a new row. Green stays one sentence ("Backups: all
clear"). The morning of 2026-10-06 showed why both rules exist: first the view
looked complete and the streams were skipped, then a test run listed the same
disk twice and redid a PR search the profile already ran.

**A finding about a run is yours to check, not the person's.** "Look at the
first run of X" is never a row for the person: read the run's log or trace,
then report the result in one sentence, and only a deviation becomes a row.
Filing such a check needs a `closes_when`, or it is not filed.

**Read the view before you hand it over.** The script computes the shape; whether
a row makes sense is yours to see. Before showing it, go through the rows once:

- A report (`finding`, `result`) in Do or Delegate that the Bridge can verify (a
  crash, a probe, a nightly run, a missing job): check it now, say the result as
  a note on its number ("on 4: running again since 21:10, item closed") and close
  the item when it is settled. A green result is one sentence, not a row.
- A draft waiting for release: read the drafted text. An error message, an empty
  answer or a text that does not answer the question is said on the row, never
  passed on as "waits for your yes".
- A row whose title states a hope ("wait for X's answer") while its detail names
  an action and a date ("no answer by the 8th: chase"): say the action, and file
  the item as waiting (`inbox.py defer <id> --until <date> --on "<who>"`) so the
  next run puts it under waiting on others.
- A line that still reads like a machine (a file name, a command, a slug): say it
  in the person's words in your note, and fix the source that wrote it.

These notes go under the view, numbered by the rows they speak to; they are not a
second copy of the view. The morning of 2026-11-07 is why: a draft whose text was
the runtime's error message stood first as "waits for your release", and five
reports the Bridge could have checked stood as the person's work.

**Close with the receipt**, one line: `Steps: inbox ✓ · view ✓ · <owed stream>
✓/skipped (why) · ...`, listing exactly the streams `owed` named. A stream the
profile covers is not listed. A stream that runs by hand every morning belongs
in the profile: propose a `command` section with `covers:` and `report_ok: true`
after the second time.

Two things are yours besides:

- **Why the first row is first**, in one sentence under the headline, when the
  derived reason (due, back on, waiting N days) does not already say it.
- **The answers.** Every numbered row, in every bucket and every style, takes
  the same four answers, the cockpit's four: **do** / "mach", **later** /
  "später" (with an optional day: "3 later monday", "3 später in einer Woche",
  "3 später 3.12.", "3 später merkliste"; no day is tomorrow), **done** /
  "erledigt", **obsolete** / "veraltet". A letter picks them in that order:
  "3a" do, "3b" later, "3c" done, "3d" obsolete. Several in one line work:
  "1 mach, 3 später montag, 5 veraltet". The words of the answers before them
  stay accepted and mean one of the four: ja, yes, los, go, nachfassen, nudge
  are do; einplanen, schedule, nicht jetzt, not now, warten, wait, behalten,
  keep are later (einplanen with a day puts it on that day); parken, park are
  later onto the watch list; streichen, drop are obsolete. Read a reply with
  `scripts/lib/answers.py` (`answers.parse(text, today)`): it gives each
  number its answer and, for later, the day (`9999-12-31` is the watch list).
  A number this print left out (a cockpit card names every row's number) is
  read from `briefing.py collect <id> --max-items 500 --json`, where every row
  carries its `nr`.
  What the answer does to the row is `answers.effect(answer, row, until)`, the
  table below in code: run its `cli` commands from the repo root. Its `cockpit`
  part is the act the page's card sends for the same answer; the page keeps its
  own copy (`scripts/web/buckets.js`), and the shared cases in
  `scripts/tests/fixtures/answers/effects.json` hold the two to the same act,
  so the same word does the same thing on the same row in the chat and on the
  page.
- **Do is the Bridge's next step**, the one the row's next sentence names: a
  task gets an agent on its next step and moves to "I'll do" as running; an
  inbox item gets its yes and runs (`only-you` gets no yes and never runs: a
  note says "do it", prepare it and say "you press send", as the cockpit does;
  an item whose yes is given already starts now: `inbox.py run`); a point waiting on someone else gets a nudge written as a
  DRAFT for the person, never sent, which then stands in Do as a ready draft;
  a row an agent tab asks about is answered in the tab with the tab's own
  answer.

A stream that runs every morning belongs in the profile, not in this list: a
`command` section with `report_ok: true` turns it into rows and an all-clear
line the engine computes. Propose that when the same stream is added by hand on
two runs.

"Not this again" on a row is a `mutes:` entry in the profile matching that row
(`{section: <id>, when: {...}}`): propose the entry, write it on a yes, run
`briefing.py validate`. A task under housekeeping without a next step gets one
proposed (`next: {what, who, due}` in its STATUS.md), not guessed into a bucket.

## Phase 4: the top of the output

Without a view (`style: sources`, the default), render these three sections
ABOVE everything else in `workflow.md` § Phase 4.

```
── One thing first ────────────────────────────────────────────────────────

  {summary}
  {why it is first: urgency, due, collision, what waits on it}
  → {proposed action}            [{gate}]   do · later · done · obsolete

── Waiting for you ({N}) ──────────────────────────────────────────────────

  1. {urgency} {kind}  {summary}  [{task}]  → {action or "decide"}  [{gate}]
  2. ...
  Ran since last briefing: {items closed by `check` or executed by `run`}

── Workplace today ────────────────────────────────────────────────────────

  {output of: python3 scripts/workplace.py propose}
  [a] open all · [b] only <workspaces> · [c] nothing
```

**One thing first** is the first item of `inbox.py list` (ordered by urgency, then
decisions before findings, then due), unless an advise finding of urgency `now`
exists. Say WHY it is first in one line. If nothing is open: "Nothing waits for
you", and the section shows the most active task instead.

**Waiting for you** lists the rest, at most 7 lines; more collapse to a count. Group
by task when three or more share one. Never list an item twice because a tracker
also shows it: the inbox line wins and the tracker section drops its duplicate.

**Workplace today** appears only when bridge-config.yaml has a `workplace:` block.
Opening needs the person's answer: show the dry run (`workplace.py open`), then
`workplace.py open --yes` or `--only A,B --yes`. The driver decides how tabs open;
with driver `none` the person gets the commands to start themselves.

## Every line is a lever

| Gate | Meaning | What the briefing may do |
|---|---|---|
| `free` | the Bridge may act alone | do it now and report it (regenerate, read, close a stale advise item) |
| `your-yes` | acts after a yes | ask; on yes run it, on "yes once X" record a conditional yes |
| `only-you` | send, publish, pay | prepare (draft, branch), never execute; say "you press send" |

Answers map onto the inbox, never onto memory or a log sentence:

| The person says | Do |
|---|---|
| do / mach / `a` (ja, los, nachfassen) on an inbox item | `inbox.py approve <id>` then `inbox.py run` |
| do / mach on a task | start an agent on its `next.what`; the task stands in "I'll do" as running |
| do / mach on a waiting point | write the nudge as a DRAFT for the person (mail-draft), never send it |
| yes once {condition} | `inbox.py approve <id> --when-json '<probe>'` (only `your-yes`; `run` executes it later) |
| later / später [day] / `b` on an inbox item | `inbox.py defer <id> --until <date>` (watch list: `--until 9999-12-31`) |
| later on a task, a stream or an issue | a day: `briefing.py hide task:<slug> --until <date>` (an issue `ref:<owner/repo#n>`), the cockpit's own record; watch list (merkliste, parken) on a task: `task.py status <slug> backlog --note "Parked: <why>"` |
| later on a waiting point | a day: out of sight until then and counted as later, back with the same person, a task `task.py wait <slug> --until <date>`, an inbox item `inbox.py defer <id> --until <date> --on "<who>"`; the watch list is the watch list there too (a task to the backlog as above, an inbox item `--until 9999-12-31` without `--on`) |
| done / erledigt / `c` | an inbox item `inbox.py close <id> --note "<how>"` (if the probe missed it, fix the probe); a task `task.py close <slug>`; a stream is done for this time, `briefing.py hide task:<slug> --until <tomorrow> --done` (counted as done today, it runs on); an issue or PR `briefing.py dismiss ref:<owner/repo#n> --outcome done`, never closed on GitHub |
| obsolete / veraltet / `d` (streichen), on any numbered row | the cockpit's Obsolete: an inbox item `inbox.py drop <id> --note "veraltet" --reason outdated`; a task `task.py close <slug> --declined --reason "Wird nicht gemacht: veraltet"`; a stream the same with `--stream`; an issue or PR `briefing.py dismiss ref:<owner/repo#n> --outcome not_doing`, never closed on GitHub; a row an agent tab asks about is answered in the tab, unless it asks about an inbox item |
| status | `workplace.py status` plus the open count per task from the inbox |
| tell {tab}: {text} | `workplace.py send <tab> <text>`; show what goes where first unless the person named both |

A condition is a probe (`docs/inbox.md` § Probes): "once it is green" on a PR is
`{"gh_pr": "owner/repo#N", "state": "green"}`.

## Offer the arm

When an item or task waits on something outside (a blocked task, a PR waiting
for checks, a reply that has not come, a service that should come back), and
a file in `infra/remotes/` lists `arm` under `capabilities` (a machine that is
always on and keeps a Bridge clone, `docs/always-on-machine.md`), offer once per item:

```
  Should {machine} watch this and file an item when it moves?   [your-yes]
```

On yes, declare the watcher through the `workload` skill with `reports_to: inbox`
and a `closes_when` matching the item. Without such a machine, say nothing: the
offer only appears where it can be kept.

## Write back

Whatever stays open at the end of the briefing is an item, not a sentence: a
promise made in a meeting, a "check tomorrow", a reply owed. File it with
`inbox.py add` and a `closes_when` wherever the live source can tell. Then
`inbox.py render` regenerates `work/inbox.md` next to `work/board.md`.
