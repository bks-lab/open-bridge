---
summary: "The cockpit's areas: the project chips, the Areas lines of the start page and their numbers, where each number leads, the one area filter over Work, Chat and Sessions, and why a tab gone idle is finished rather than waiting on you."
type: guide
last_updated: 2026-10-31
related:
  - bridge-cockpit.md
  - cockpit-files.md
  - workplace.md
  - ../scripts/web/areas.js
  - ../scripts/web/views/home.js
---

# The areas

> Part of [the Bridge cockpit](bridge-cockpit.md), on its start page. The code is
> `scripts/web/areas.js`, the area parts of `views/home.js`, `text-areas.js` and `areas.css`;
> the tests are `scripts/tests/bridge_cockpit_areas.test.mjs`.

On the start page sit project chips, made from the workspaces of the agent tabs and the
projects of the rows (area, else the mark), most frequent first. A chip
filters every shelf, and the choice is kept in the browser.

The **Areas** shelf (on by default, first among the shelves) stands above the
chips: one line per area, in the order of the chips, with five numbers.
*Waiting on you* counts the area's rows in "now" and its agent tabs that want
you (needs you, or waits and is not finished; a row and the tab working on it
count once); *running* its tabs at work; *to
review* its tabs that went idle and the starts handed to an agent whose answer
came (a start and its idle tab count once); *overdue* its rows past their due
day; *tasks* its open task rows, each task once. The control tab and bare
shells count for nothing. An area with every number at zero is left out; one
with nothing but tasks stays, damped, so it can still be picked. A line is a
button: it picks that area as the chips do, a second click (or the line "All")
shows everything again. With the shelf on and a line for every chip, the lines
replace the chips. In the overview a name opens the area's files instead (Work,
view Files, the filter set, for this visit: the view the work tab opens on stays).
Under an area, Chat lists only the workspaces that hold one of the area's tabs or carry
its name, and an area without any agent tab says so in the bar ("No agent tab in X") with
a button that shows every area again. What has no area stands last as **No area**; its name and numbers lead to the
same pages without a filter. An inbox item counts under its task's area, else under
the area it was given ([`inbox.md`](inbox.md): `--area`, or the router when it is
filed); only one with neither is *No area*. There is one area filter in the whole cockpit:
the name, a chip or a jump set it, the start page views, Work, Chat and
Sessions all show it, and a project chosen on the start page before carries
over.

**On the bridge** (the start page's stage view) the areas are one bar of pills under
the greeting instead of the shelf and the chips below the stage, so the filter stands
in the first screen beside what it filters. *All* comes first, then each area with
something open, what waits on you first, then what is at work, then the most open,
*No area* last. A pill shows one figure: what waits on you (in the warning colour),
else how many tabs work there, else its tasks, else its tabs at rest; its title names
all of them. An area whose only open tab is an empty shell has no pill. The areas of
`workplace.workspaces` with nothing open wait behind *+n quiet*, which opens them in
place. A pill picks the area like a line of the shelf (a second click shows every
area again), and the Today card beside the bridge follows it. An alias of a workspace
is never an area of its own: a task under an alias counts under the workspace's
name. An issue or pull request without an area takes the area of the workspace
whose `repos:` match its repository ([`workplace.md`](workplace.md)).

**Every number is a jump** to the page that holds those things, with the area
as its filter: *waiting on you* opens Chat and walks the area's tabs that want
you one by one when only tabs wait (Chat shows tabs, not rows); rows, or rows
and tabs, open Work on what is due, where "now" leads; *running* and *to review* open
Sessions (the sessions and the starts handed to an agent); *overdue* opens
Work on what is due; *tasks* opens Work in the view it was left in. A zero
leads nowhere.

**The area filter** (kept in the browser) acts on Work, Chat and Sessions: Work
keeps the rows of the area (the folded ones and the hidden ones too), its
page items and, in the tab column beside it, the area's tabs; the middle's
headline counts what waits in the area (as its line on the overview does),
while status and tidying stay for all areas and say so; Chat the area's tabs (the control tab stays; `n` walks only
them), Sessions the sessions whose tab, else whose folder, is in the area,
and the starts of its rows. A section counts what it shows; rows still to
load say "(area filtered)". The keys act only on rows the page shows: a new
filter empties the picks and lets go of a focus or an open row it hides. A
bar over these pages, and over the start page's other views, names it
("Area: ACME ✕"); the ✕ shows every area again, and so does `Esc` once an
open row or the picks are closed. A page tab's count follows the filter, a tab's red
findings and the rest of the header count everything. On Work the same
bar carries the star "Only pinned", which keeps the rows you pinned.

**Beyond Work, Chat and Sessions.** The address `?ws=<area or workspace id>` opens the
cockpit under that filter. The log keeps the rows whose tag stands in the area: its name,
an alias, a context or a repo of its `workplace.workspaces` entry, a star allowed; an area
with none of these keeps every row. Dates follow `sources.calendars` of the area's workspace
([`workspaces.md`](workspaces.md)): no such key, no filter; an empty list, no dates, and the
page says so. The cost card opens on `sources.cost_center`. These pages carry the bar too.
The filter stands in the browser only: it changes what the page shows, not what the server
sends, and it keeps nothing from a session. That is the job of a workspace's `boundary`.

**The picker** stands in the header on every page: All and each active workspace, a child
under its parent. A click sets the one area filter.

**Active and shown.** Settings, Workspaces lists every area with its rules in one line,
two switches and Delete. *Active* is the stronger one: a resting workspace leaves the picker
and the bar, and its rules no longer hold. *Shown* only takes an area out of the bar, the
chips and the shelf, it stays in the picker. Neither deletes anything, background runs go on,
and the line All still counts it. The switches are kept in `.bridge/cockpit/workspaces.json`,
so they hold in every browser and make no commit. A workspace archived with
`workspace.py archive` rests, and waking it restores its file. A child rests with its parent
and leaves the bar with it, its switch then held.

**Delete** takes any area but the default, where everything without an area lands. It says
first what it touches and offers the last button only when nothing stops it: an open tab of
the area, a child, or a clone with unsaved work. It removes the workspace's file through
`workspace.py delete`, then the area's entry from `bridge-config.yaml` through
`workspace.py area-remove`, line by line so comments stay, with a copy of both under
`.bridge/trash/`. The page writes the config only here. Tasks of the area fall to the
default area, records keep their name, and nothing else goes.

A tab that went idle is finished, not waiting on you (its badge reads "done", and the header's Tabs button does not count it): the
walk through the tabs skips it, and By status lists it under "Finished, to
review".
