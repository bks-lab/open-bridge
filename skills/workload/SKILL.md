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
workload view       [<id>...] [--host H] [--no-probe] [--out PATH] --now STAMP [--poll-sec S] [--group-by band|system]
workload publish    [<id>...] [--host H] [--no-probe] --to HOST --dest DIR --now STAMP [--page-name NAME] [--attach PATH]... [--url URL] [--stale-after-min N] [--poll-sec S] [--group-by band|system] [--yes]
workload retire     <id> --reason TEXT [--superseded-by ID] [--keep-artifact] [--yes] [--dry-run]
```

Exit codes: `0` clean, `1` findings or applied-but-unverified, `2` usage or
declaration error, `3` refused by a guard, `4` unreachable or a deadline expired.
The `4` exists so an expired deadline can never be mistaken for a clean run.

Four of those are worth spelling out, because each one used to be a `0`:

- `validate --strict` exits `1` when `check-jsonschema` is not installed, and
  when `_schema.yaml` is not there at all. A gate that could not run has not
  passed, and the two absences are reported as different sentences: the missing
  contract is never reported as a refused declaration.
- `provision --yes --dry-run` exits `1` by construction. Nothing was applied, so
  nothing was verified, and this skill reports success only from the live object.
- `retire` without `--yes` exits `3` and stops nothing: not being told yes is not
  a yes, and this is the only command that stops a running service. It is the one
  place where a bare command line does not preview: ask for the preview with
  `--dry-run`, which reports what it would do and exits `1`.
- `--group-by` decides which question the table is sectioned by, and there are
  two because there are two questions. `band` (the default) sections by WHEN a
  run fires and draws byte for byte the page this drew before the flag existed.
  `system` sections by WHAT a run is a part of, read off the declarations' own
  `system:` field, which is how an agent, its tunnel and the puller that feeds
  it appear as one block instead of three rows in three different sections.

  The default does not move, and that is the point: an axis that silently
  re-sectioned an operations page would make every reader re-learn a page they
  already knew, for a question they may not have been asking.

  A heading and its rows are paired by ONE attribute, which the page's own
  script compares literally in order to hide a heading whose rows were all
  filtered away. Both halves therefore come out of `_sections` and are never
  computed twice; keyed apart, every heading would count zero rows and the
  table would vanish the first time somebody typed in the search box. That
  invariant is asserted on BOTH axes, not on the new one alone.

  A run naming no system is NOT folded in with the ones that stand alone on
  purpose. `_standalone` was looked at, absent was not, and only one of the two
  asks the reader for anything.

- `view` and `publish` render the same page: a 24 hour calendar first, then
  what is in service, then what is retired as a counted sentence, then the
  entries a machine's inventory file names that nothing knows, then a count of
  the units no declaration claims. Every run carries a strip of its last
  recorded firings, oldest on the left, one shape per verdict and every shape
  in the legend: the newest run alone cannot tell a job that has been clean for
  a month from one that failed twice this week and happened to succeed just
  before somebody looked. For a kind that never ends the strip says what its
  marks are, because that guard writes a line when the run STOPS, so its
  history is a list of deaths and an empty strip is the good case. Retired declarations are not rows: a reader
  counts rows to learn how much runs here. On the calendar the ring at a
  declared time is `reconcile`'s verdict about the schedule and the diamond is
  the machine's own trace, two marks from two sources, neither derived from the
  other. A run is placed only where the declaration states a time zone, because
  the trace is UTC and the axis is the machine's day.

- **A run is never called overdue for an appointment that fell while the
  machine was off.** `reconcile` reads when the box last came up (`kern.boottime`
  on macOS, `btime` on Linux) and holds the verdict back where the appointment
  lies before it, or where a cadence window is longer than the machine's own
  uptime. It is a SENTENCE and not a silence: the state becomes `unknown` and
  the reason names both moments, because "nothing can be judged here" and
  "nothing is wrong here" must never print the same. A machine that will not
  say answers empty, and empty changes nothing: every verdict then behaves
  exactly as it did before there was a boot moment, because the cheap guess
  (assume it has been up forever) silences nothing while the other one silences
  every real alarm.

  The parsing happens in Python and the shell only fetches. `sysctl -n
  kern.boottime` answers `{ sec = …, usec = … }`, and the obvious extraction is
  greedy: `.*sec *= *` walks past `sec` and matches inside `usec`. Measured on
  two machines, where it returned 750092 and 149827 and both look like a
  plausible epoch at a glance.

  It may only ever take a verdict AWAY, which is why it is reached from the
  `overdue` returns and not from the top of the function. Written at the top
  for half an hour, it also fired on every path that was already silent for a
  reason of its own: a weekly report provisioned after its last appointment,
  which the provisioning rule had correctly said nothing about, acquired a
  verdict, and every healthy cadence on a freshly rebooted machine would have
  grown one sentence saying nothing was wrong with it. A guard against a false
  claim that manufactures a second claim is not a guard.

  On the machine it was written for it currently changes nothing at all, and
  that is the correct outcome rather than a disappointing one: it fires only
  where an `overdue` would otherwise be false.

- `publish` is dry without `--yes`, and it answers with TWO facts rather than
  one word. `delivered` means the bytes are on the machine, proved by reading
  them back off it. `reachable` means a browser gets them, proved by fetching
  `--url` and comparing. Without a `--url` reachable stays *not asked* rather
  than false: a file in the wrong directory lands perfectly and is never served,
  and one word for both hides exactly that gap. It refuses a destination that
  holds files it did not write, because a served directory usually belongs to a
  puller or another view already, and publishing into it either destroys their
  output or loses the page at their next sync. Ownership is a marker file
  inside the directory, read before every publish, never the directory's name.

- `--attach PATH`, repeatable, puts a static file of your own beside the rendered
  page. Each one is written byte for byte, read back off the machine and
  compared exactly as the page is, and each gets its own line in the report
  rather than a count, because one delivered and one refused would otherwise
  look the same. `MAX_BYTES` is 512 KiB **per file**, attachments included, so a
  page some other producer renders large does not become deliverable by calling
  it an attachment. Refused before a machine is touched: a path that is not a
  file, content that is not UTF-8 text, a missing final newline (the transport is
  a quoted here-document and would add the byte itself, so the read-back would
  report a difference the machine never caused), two attachments sharing a base
  name, a name equal to the marker, and a name carrying a separator. The marker
  names every delivered file, so the directory has one truth about its contents
  and one place that writes it. Page and attachment stay separate facts: the page
  can be delivered and reachable while an attachment failed, and only a run where
  everything asked for arrived exits `0`.
- Nothing here ever removes a file. The report therefore counts what it found in
  the directory and did not deliver, and names those files (`left behind:`), also
  on a dry run. An attachment dropped from a later call does not disappear from
  the server, it stops being refreshed, and those are different things.
- `workloads.view.links` in `bridge-config.yaml` puts a row of links to
  neighbouring pages on the rendered view. It is navigation and nothing else: no
  tile, no dot, no age, no state class, because this run neither renders nor
  measures those pages and a link on a dashboard is otherwise read as vouched for
  by the dashboard. Without the key there is no row and nothing breaks; half an
  entry is refused by name rather than quietly dropped.

  ```yaml
  workloads:
    view:
      links:
        - label: Operations
          href: ../betrieb/
      panels:
        - label: "Services on the machine"
          href: ../betrieb/dienste.html
  ```
- `workloads.view.panels` has the same shape and FRAMES a neighbour instead of
  linking it. A link says a page exists; a frame puts it in front of the reader,
  costs a request and takes vertical room, so which one a neighbour deserves is
  written down per entry rather than inferred. Each framed neighbour is a VIEW
  of its own, reached from the bar at the top and given the whole window.

  **Prefer not to frame at all.** A neighbour's page carries its own header,
  its own navigation and its own stamp, and no arrangement changes that: as a
  footer it was a letterbox in the middle of this document, and as a view it is
  still a second design behind one bar. Measured against a reader on
  2026-08-27, twice, in those words. Where the neighbour's value is DATA rather
  than a document, the answer is almost always to render what this skill's own
  probe already measured — see `workloads.view.machine_units` below, which
  replaced two framed pages with a section this run draws itself. Frame only a
  genuine document that nothing here produces. The switch is progressive like everything else here: without scripting
  every section is on the page and the bar is a set of jump links into it, so a
  reader without it loses nothing. Each view has a readable anchor
  (`#view-<label>`), so a tab can be linked to and not only clicked.
- `workloads.view.machine_units` is a list of label prefixes, and it decides
  which of the machine's undeclared units are NAMED on the page instead of
  folded into a count. Measured on one machine: 1834 of its units belonged to
  the operating system and 32 to its owner. Listing all of them is unreadable;
  counting all of them says nothing about the ones somebody put there
  themselves; and deciding which is which by the shape of a name is the kind of
  guess this skill exists to refuse. So an instance says, and a bridge that has
  said nothing keeps the count, which is the honest default. The heading then
  states BOTH numbers, because one total over a shorter list is read as the
  length of that list.

  Nothing is adopted here either: every named row is this run's own finding
  about a unit it probed itself, not a figure read off somebody else's page.

  They are NAMES IN A GRID, grouped by verdict, and not a table. As a table
  each of the thirty-two carried the same sentence with the name already in the
  cell beside it, which is about eleven hundred pixels of one sentence in a
  section that is context rather than subject. Each name keeps that sentence on
  the cursor, so nothing was dropped, only stopped from being said again, and
  they are sorted, because thirty names in whatever order a service manager
  returned them can only be read from the top.
- `workloads.view.overview_label` names the FIRST tab, the one the shell
  supplies itself. Every other tab is named by the entry that asked for it, so
  without this key the bar would carry exactly one word out of this skill, in
  this skill's language, beside labels in the reader's. Absent means the
  default.

  A frame is not adoption, and adoption was always the line rather than
  adjacency. Nothing is parsed out of the framed page, no figure of it is
  repeated as a number of this one, and what the reader sees is the neighbour's
  own rendering under the neighbour's own moment. The frame says so in its own
  sentence, because a page inside a dashboard is otherwise read as vouched for
  by the dashboard. It also sidesteps the size limit honestly: nothing is
  copied, so a neighbour far over 512 KiB is framed without ever travelling
  through `publish`, and `loading="lazy"` leaves it unfetched until somebody
  scrolls to it.
- A filter bar is built from the runs on the page, never from a list in this
  skill: a facet is drawn only where it has more than one value, so `host` and
  `runtime` appear by themselves the day a second machine or a second runtime
  arrives, and stay away while they would only be furniture. Within a facet the
  values are OR, across facets they are AND. Filters hide rows and their
  calendar lanes together, because a lane left standing for a hidden row is a
  mark belonging to nothing, and a calendar group heading goes with its last
  lane: a heading counting ten runs above none is the one number on the page
  that contradicts what is under it.
- The calendar groups its lanes by what they ARE: on an o'clock, on a cadence,
  or up the whole time. Twenty-three lanes in one flat list are read as texture
  rather than as information, and the three are drawn differently anyway.
- **A cadence is drawn as a rail and never as a beat.** It used to be a stripe
  repeating on a fixed period, the same period for a run every five minutes and
  a run every hour: roughly a hundred evenly spaced marks per lane, which a
  reader counts as firings, and ten such lanes together drown the marks that
  were actually measured. A cadence has no o'clock to sit at, so the drawing
  claims no moment and the beat is a word in the lane's own label, where it
  came from. [`rules/visual-output.md`](../../rules/visual-output.md) Gate 3.

  It carries a cap at each end, and both bands are drawn at a weight a reader
  can actually see. The first rail was two pixels at half opacity and the
  continuous band was a fill at two tenths, which over a light ground is the
  ground: eighteen of twenty-five runs on the instance this was measured on are
  one of those two shapes, so what was invisible was most of the picture. A
  drawing that asserts nothing and a drawing nobody can see are not the same
  achievement.
- **One row per run, and it carries that run's own day.** The 24 hour axis was
  a picture above the table until 2026-08-27, so every declaration was on the
  page twice, once as a lane and once as a row, each holding half of what is
  known about it; a reader with one question about one run had to match them by
  name. The axis is a column now and the three kinds of day are sections of
  the table. A whole class of defect went with the second list: a lane can no
  longer be left standing for a row a filter took away, because it is the same
  element.

  A section heading states its count as an ELEMENT, and so does the page total.
  Taking a heading away when its last row goes is only half of it: with three
  of eight rows left it kept saying eight, which is a number contradicted by
  the very rows under it.

  Repeated verdicts are COUNTED, not stacked and not dropped. A run with six
  appointments carries six findings; stacked they made one row three hundred
  pixels tall to say one thing six times, and dropped, six healthy appointments
  would read exactly like one.

  The table head is deliberately NOT sticky. It sits in a container with
  `overflow-x`, which makes that container the scrollport, so a sticky head
  pins itself into the table and covers the first section heading. Removing the
  overflow instead would let a long history push the whole page sideways. The
  hour ruler is therefore drawn into every SECTION HEADING rather than once at
  the top: it needs no stickiness to stay within a screen of the tracks it
  measures, and it costs one line per section. The section for runs nothing
  could place gets no ruler, because an hour scale over cells holding a
  sentence invites the reading that they are somewhere on it.

- **Nothing is called `in_sync` before the persistent off-list has been
  asked.** `in_sync` is a statement about BYTES: it compares what sits on the
  machine with what the declaration renders. A unit whose bytes are perfect can
  sit in the service manager's persistent off-list and never start again, and
  that list is where a stop is written precisely because it SURVIVES A REBOOT
  (this skill's own `retire` uses bootout plus disable for that reason).
  `provision` read the list from the beginning, to refuse switching on what a
  person switched off; the pass that reports how the machine IS never asked, so
  the two disagreed by construction. `reconcile` now asks it, driven by the
  STAMPS and not by what is loaded, because the two states it covers differ: a
  unit can be loaded AND on the list, which runs now and never comes back after
  a reboot, or booted out AND on the list, which is reported `absent` with a
  hint to provision it again that `provision` then refuses for the very reason
  nothing had read. The second is not in `launchctl list` at all, so a read
  driven by live units would have covered one case of two. It asks about what a
  stamp claims and never about the thousand units a box carries (measured on one
  machine: 1019 live, 31 claimed), and memoises the answer BY THE ARGV: launchd
  keeps the list per domain, so one read answers for every unit in it, while
  systemd keeps it per unit, and memoising the QUESTION gets both right without
  either backend describing itself. An unread list leaves no answer at all
  rather than a False, for the same reason `marker_observed` exists. A unit on
  the list is a `disabled` finding at medium, and it TAKES A VERDICT AWAY as
  well: a silence from something nothing was going to start is no longer
  `overdue`, under the same rule as the uptime guard, and the sentence names the
  off-list instead. A retired declaration gains nothing, because this skill
  disables one itself and reporting it would turn every clean retirement into a
  finding that needs a person.

- **The program a run CALLS is not the artifact it was rendered from, and
  `in_sync` only ever looked at the second.** A wrapper that lives outside the
  repository and has drifted from its twin runs happily forever: a change in
  the repository never reaches it, and no error appears anywhere. Measured on
  one machine on 2026-08-25, five such pairs, and two watchdogs that existed
  only on that box, a hundred and thirty lines ahead of the repository's copy,
  one disk failure from gone. Three answers, and the third is the dangerous
  one: `in this repository` (the program's path ends in a path the repository
  carries, so drift is structurally impossible), `a copy` (it sits elsewhere
  and the repository holds a file of that name, so the digests decide), and
  `only on the machine`. NOTHING HERE DECIDES WHICH SIDE IS RIGHT: in no two of
  those five pairs was it the same side, once the repository's version was the
  maintained one and once the machine's. Noticing that two exist and have come
  apart is the machine's half; deciding is a person's. A shared interpreter is
  not a program but the language one is written in, and counting `/bin/bash`
  would make almost every run a copy. The path is matched on its SUFFIX rather
  than against a configured repository root: the root belongs to the machine,
  the check runs wherever `reconcile` was started, and a configured root would
  be a second opinion about a fact the path already carries. The healthy answer
  is printed on every row too, because a column of "in this repository" is what
  makes the one exception legible.

- **An inventory entry that says why it is gone has not drifted.**
  `intentionally_absent: {since, reason}` is the CORE field from
  open-bridge#159, and reading it splits one heading into two: an entry that
  names nothing may be a record nobody maintained OR a decision somebody wrote
  down, and one word for both told a reader there was work here whose only
  content was deleting the record of the decision. Measured on a live inventory
  on 2026-08-27, nine of sixteen rows were the second kind. Only the nested
  English field is read: a `scope: core` skill that learns one operator's
  vocabulary has stopped being generic, and that block is the half the schema
  checks. A NON MAPPING is not a decision, the same rule the neighbouring
  operations evaluator settled on, because this is the field that suppresses
  both the report and the repair and a typo must not switch either off. The
  incomplete-look guard does not apply to it: that guard holds back a claim
  about the MACHINE, and this sentence only repeats the file.

- **A row names the file its run writes into.** The guard captures stdout and
  stderr of every run into `<state_key>.out` beside the trace the page already
  draws, so the path was derivable from two facts the page held and was never
  derived: a reader who saw a cross had a convention to remember. One path per
  appointment, never `<id>.out`, which is the same trap the trace fell into.
  The directory travels in the report rather than being resolved a second time
  by the renderer, and with none configured nothing is printed, because a path
  this page invented would read exactly like one it was given. Named and never
  opened, and the page says so.

- **What is undeclared gets a verb, once.** The context section lists what the
  run found that no declaration claims and states that this skill touches none
  of it. That is complete about the past and leaves the reader's only question
  unanswered, so the lede names `workload adopt <unit>`. In the lede and not
  per row: those names differ in nothing this run measured, so a sentence each
  would be one template repeated thirty times.

- **A file too big for one command line travels in parts.** The size gate
  counts a file against the SHELL's limit. The connection has a smaller one:
  a multiplexed ssh session carries one request in one packet and refuses past
  about 256 KiB with `mux_client_request_session: write packet: Broken pipe`,
  an error that names neither the file nor the size nor the reason. Measured on
  2026-08-27 with a 274 KiB page the gate had passed and the machine would not
  take, twice in a row. The write is therefore split at LINE boundaries, first
  part truncating and the rest appending, because every part travels as a
  here-document and one of those ends every line it carries: a cut inside a
  line would put a newline into the file that was never in it. Nothing in the
  splitting proves the parts arrived, and it does not have to: the read-back
  does, and a half delivered file fails that comparison exactly like a
  corrupted one. That is what makes splitting safe to do at all.

- **A day, a week and a month, and a weekly run is not due every day.**
  Measured on the live page on a Thursday: a run that fires on Sundays drew a
  ring at 10:00 whose hover read "nothing says this schedule is behind",
  identical to a run that really was due that morning. The row's text cell said
  "10:00 Sun", so the page was not silent; the DRAWING asserted an appointment
  today, and the drawing is why the axis exists. The verdict logic never had it
  wrong, because `previous_due` reads the same weekday set: the judgement knew
  and the picture did not. Such a mark is now drawn faintly and says which days
  it does fire on, and it is DRAWN rather than dropped, because an empty lane
  reads as a run with nothing scheduled, which is the other wrong answer.

  The week and the month are the scales that make a rhythm legible at all: a
  weekly job on a 24 hour axis is a ring at an hour with its day in a text cell
  beside the picture. Both are RENDERED and one is shown, so a reader without
  scripting keeps the day; a scale that only exists after a click is a scale
  nobody can read with the script off. Two facts per cell and never merged: DUE
  comes from the same weekday set the unit file is rendered from, and RAN from
  what the machine wrote down, so a day that was never scheduled and a day that
  was scheduled and missed cannot look the same. What ran reaches back only as
  far as the recorded strip, which is capped, and the legend says so. The page
  NAMES the day it drew and the zone it drew it in, and the script adds the
  reader's own day when the two have parted: a grid of hours belongs to no day,
  and without the sentence yesterday's calendar and today's are one picture.

- **The page opens with what needs a person, not with an inventory** — as a
  COUNT and a way to the rows, never as a second copy of them. Every finding
  this skill produces carries a HINT, its own sentence about what to do next,
  and until 2026-08-27 no renderer had ever put one on a page. It now sits in
  the row the finding belongs to, next to the finding itself.

  Until 2026-09-04 the opening block instead wrote every finding out in full, a
  second time: the same detail and the same hint that its own row already
  carried. Measured on the live page, twenty-five entries over a table holding
  the same twenty-five. That is not a summary, it is a second account, and on
  the day the two disagree one of them is wrong with no way to tell which. The
  opening line now states how many findings on how many runs, and offers the
  `attention` facet as the way there; the reader filters the table they already
  have instead of reading a copy of it.

  The shortcut PRESSES the pill rather than filtering on its own, so the pill's
  state and the table can never disagree, and it is drawn only where the pill
  exists — a facet appears from two values up, so on a page where every run
  needs a person there is no pill and therefore no button.

  An all clear is a SENTENCE and not an empty box, and it says what it is a
  statement about ("what was measured, never a promise about what was not"),
  because an empty box teaches a reader to skip the one place that will one day
  not be empty.

- **The header states when each machine came up and how far the evidence
  reaches back.** Both are what make a silence readable: "nothing ran at 06:00"
  is perfectly true and reads as an alarm on a box that came up at 09:00. A
  machine that would not say is named as such, because leaving it out makes a
  page about a silent machine look exactly like a page about one that has been
  up for a month.

- **The day says where it has got to.** An upright line at now, and the part of
  the day that has not happened yet on a ground of its own, so a track stops
  looking the same at 03:00 and at 23:00. Both are script-only and drawn from
  the zone the declarations state, never from the reader's offset, and both are
  accounted for in the sentence under the table. Each run also says how long
  ago its last trace was; the absolute stamp is what SHIPS, so a reader without
  scripting gets an answer rather than an empty line, and the clock turns it
  into a distance.

- **The table can be searched, opened and sorted.** A facet can only offer the
  words this skill files a run under; the word somebody remembers is usually in
  the purpose, so one lowercased haystack per row carries the identifier, the
  purpose, the unit, the schedule and the labels. Two words NARROW (an OR there
  makes a second word add rows, which reads as a filter that stopped working),
  the search ANDs with the pills, and it survives a page where every pill offers
  one value, which is the page where it is the only control that works.

  Sorting happens WITHIN each section and never across them: the sections say
  what a run IS, and a sort that dissolved them would answer neither question.
  A third click restores the order the page was built in. The keys are RENDERED,
  because which of two verdicts is worse is a decision of the renderer, and a
  second copy of it in the script drifts silently.

- **The day is the widest column on the page, and that took width from
  somewhere.** It was about 270 pixels for twenty-four hours, which is a
  footnote about a day rather than a day; the reader said so and measuring
  agreed. Two things had to change together. The declared shares now give the
  day the largest of them, and the recorded strip is set small: that strip is
  `white-space: nowrap` with one glyph per recorded run, so it has a hard floor
  of about twenty-four glyphs, and at reading size that floor was 365 pixels of
  identical dots taking a third of the table unconditionally. Widening the
  column without lowering the floor moves nothing.

- **Inside a section, runs are in the order they fire.** Alphabetical made the
  one section that IS a calendar unreadable as one: a 00:30 job sat below a
  06:10 one, so the marks scattered down the column instead of walking across
  it. Appointments sort by the hour, cadences by the period as a NUMBER (`every
  3600s` sorts above `every 300s` as a string), and a run with no order of its
  own keeps its name, which is at least the same on every render.

- **The upright line at "now" is drawn only where the declarations agree about
  the time zone.** The axis is the machine's day. A line taken from the
  reader's own offset is right in one office and hours out in the next and
  looks identical in both, so the hour is computed in the zone the declarations
  state; where they state more than one, no line is drawn and the page says
  which zones disagreed. It is script-only for the same reason the age in the
  header is: it is a fact only a running clock knows, and a server-rendered one
  would be frozen at the moment the page was written while looking live.
- **A row is four columns, and the rest of a run is one click down.** What a
  run IS (unit, host, kind, runtime, owner, sphere) does not change between two
  readings and does not deserve a column every other row must make room for;
  what it DID does. Ten single-token columns squeezed the identifier into a
  quarter of the measure and wrapped every purpose over four lines while three
  of them floated in white. The columns declare their share and are never
  fixed: a fixed layout would clip a history longer than its column and drop
  recorded runs without saying so.
- Four counts head the page, each one counted off the very rows below it. A
  summary reaching for a figure the table does not carry is how a headline and
  its own detail come to disagree.
- **Both labels, and neither is guessed.** A row carries the sphere the run
  belongs to (`persona_ref`, with *undecided* as its own word, because an empty
  cell reads as one of the reserved answers) and the name the machine knows it
  by. That name is asked of the backend that assigns it, never rebuilt in the
  view: a second derivation of a name drifts from the first, and where a runtime
  names nothing the page says so instead of inventing one.
- **Declared and delivered never share a mark.** A declaration names its
  recipients and nothing on the execution path reads them, so the page says the
  group and says which of the two facts that is, every time. It names no person:
  a person is named in a declaration by a slug, a slug of a person is a name,
  and this page is read by every device on the network it is served from.
- The reason row under each run is a disclosure: one click instead of one
  scroll. The page SHIPS expanded and unfiltered and the script collapses it, so
  a reader without scripting gets the long document rather than a table whose
  reasons are all hidden and whose buttons do nothing.

- `--stale-after-min` belongs to `publish` alone, and the command lines above
  say so because the parser does: handed to `view` it is a usage error, not a
  quietly ignored word. A `view` page therefore carries no freshness verdict at
  all: its own stamp, the age the reader's browser computes from it, and a plain
  sentence saying that no cadence was declared for this page. That third part is
  a banner the renderer appends in exactly this case, and it is what keeps a page
  published once by hand from reading like one refreshed a minute ago.
  *(A judgement, clearly not the state of the code: the switch would fit `view`
  too, because a file written once is opened again hours later and looks
  identical. The renderer already accepts the value from either command, so the
  wiring is one line in the parser. Until that line exists, do not put the switch
  on a `view` command line.)*

- `retire` and `adopt` answer with the same report shape as `provision`: the
  header says whether the result was verified at the live object, and the rows
  say what happened. They used to print two fields of the outcome, from which
  refused, failed and previewed cannot be told apart.

## Decision tree

| The request is about | Read |
|---|---|
| writing a new declaration, which questions to ask, what stays a reference | [`references/declare.md`](references/declare.md) |
| provisioning, adopting, retiring, a refusal code, moving an existing service | [`references/provision.md`](references/provision.md) |
| "is it still there", the state list, what `unknown` means | [`references/reconcile.md`](references/reconcile.md) |
| which runtime can carry what, and how to add another one | [`references/backends.md`](references/backends.md) |

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
