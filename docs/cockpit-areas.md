---
summary: "The cockpit's areas: the project chips, the Areas lines of the start page and their numbers, where each number leads, the one area filter over Work, Chat and Sessions, and why a tab gone idle is finished rather than waiting on you."
type: guide
last_updated: 2026-10-25
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

Below sit project chips, made from the workspaces of the agent tabs and the
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
What has no area stands last as **No area**; its name and numbers lead to the
same pages without a filter. There is one area filter in the whole cockpit:
the name, a chip or a jump set it, the start page views, Work, Chat and
Sessions all show it, and a project chosen on the start page before carries
over.

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
while dates, status and tidying stay for all areas and say so; Chat the area's tabs (the control tab stays; `n` walks only
them), Sessions the sessions whose tab, else whose folder, is in the area,
and the starts of its rows. A section counts what it shows; rows still to
load say "(area filtered)". The keys act only on rows the page shows: a new
filter empties the picks and lets go of a focus or an open row it hides. A
bar over these pages, and over the start page's other views, names it
("Area: ACME ✕"); the ✕ shows every area again, and so does `Esc` once an
open row or the picks are closed. The
page tabs' badges and the header always count everything. On Work the same
bar carries the star "Only pinned", which keeps the rows you pinned.

A tab that went idle is finished, not waiting on you (its badge reads "done", and the header's Tabs button does not count it): the
walk through the tabs skips it, and By status lists it under "Finished, to
review".
