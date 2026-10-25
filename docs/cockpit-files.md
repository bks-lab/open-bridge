---
summary: "The cockpit's files view: one task at a time as a file on the work tab, its queue, next step and drawers, the search across every task, asking a file, the suggestion, the workflow runs as results, the files under the area filter, and the switches cockpit.work_view and cockpit.focus_to_files."
type: guide
last_updated: 2026-10-25
related:
  - bridge-cockpit.md
  - cockpit-areas.md
  - work-system.md
  - ../scripts/web/files.js
  - ../scripts/web/views/dossier.js
---

# The files view

> Part of [the Bridge cockpit](bridge-cockpit.md). The code is `scripts/web/files.js`,
> `views/dossier.js`, `text-files.js` and `files.css`; the tests are
> `scripts/tests/bridge_cockpit_files.test.mjs` and
> `scripts/tests/bridge_cockpit_files_count.test.mjs`.

**Files** is one more view of the work tab, on every Bridge, with or without a
work page, beside Due and never in its place: Due stays, and stays the view the
tab opens on, unless `cockpit.work_view: files` says otherwise (below). On a Bridge without a work page
this is what makes the tab's view switch appear ("Due | Files"), since without
it the view could not be reached. It shows one task at a time as
a file, on one framed surface centred at a reading width (it stays in the
middle when the sidebar is hidden). Above it stand the view switch and a small
search field. On the surface: an eyebrow (File, "2 of 16", status, kind and
priority, the slug on the right), the task's title as the one heading, and the
situation in one sentence (the `headline` of its STATUS.md, else what the
triage made of it, always with where that comes from and its date). Under it
the next step as the one strong block, with the four verbs as buttons, then the
file's drawers as rows on hairlines, folded: Result, Inbox, History, Files,
References (the `related:` paths of STATUS.md) and Sections, each only when it
holds something, and a question to the file. At the foot of the surface walk
**Previous file** and **Next file**, with the position between them ("2 of
16"; a click on it shows the whole queue, a click on one opens it) and the
title of the next file beside Next. A file taller than the screen keeps that
foot in view. The view is made for the mouse and names no key; with the
shortcuts switched on in the settings, `n` and `p` walk it too.
The queue is the one the focus on the start page walks, in one function
(`queueOf` in logic.js), only wider: a tab that asks about a task comes first,
then a start whose result waits, then a task with an open inbox item, then
every task in `doing` or `review`, whatever its priority (the focus takes only
P0 and P1 of them, and keeps doing so). A file opens only for a task in
`doing` or `review`: one the model knows no status of (a backlog section of a
profile, a task closed since) opens none. A tab, a result or an inbox item
opens its task's file wherever the task's row stands, also one waiting on
someone else; on its own such a task stays out. Backlog, blocked and resting
tasks stay out, and so does what has no task: a loose inbox item stays on
Start. A file is the task's own row, never a board item that names the same
task. The next step is derived and never stored: the tab's question, the
result, the oldest open inbox item of the task (one put off does not count,
one waiting for a yes does), else the `next:` of its STATUS.md, each
with where it comes from and since when; with none of these the file says "No
next step known" rather than making one up. A file a tab asks about keeps the
verbs of its task, the tab named beside them. Every task row of the model
carries `status` and `next` for it (`model.task_next`).

The view says what its queue leaves out, so a short queue explains itself.
Under the head of the file stands one calm line: where the file stands, then
how many active tasks and streams (`doing` or `review`) are not in the queue,
by why ("2 of 2 · 13 more not in the queue: 3 resting, 3 dropped, 3 waiting,
4 deferred"). The reasons, counted in the page from the model it already has
(`queueLeftOut` in files.js): **resting**, a blocked task or one quiet for a
while (bucket `resting`); **dropped**, one the triage put on drop (bucket
`drop`); **waiting**, one waiting on someone else that no tab, result or open
inbox item asks about; **deferred**, one put off, with the day it comes back
(or until it is shown again); and under the filters of Work **in other
areas** and **not pinned**. Each task counts once, under its first reason, and
a filter reason wins over the rest: a deferred task of another area counts as
in other areas. A click on the line lists those tasks by why, each
opening beside the queue like a found file, and ends with one sentence that
backlog tasks are not in the files at all: they never reach the model, so the
page cannot count them. Under an area that hides some, **Show every area**
beside the line lets the filter go. With nothing in the queue, the empty view
names the same reasons and offers the same list; with nothing left out there
is no line.

The Result drawer holds what came back for the task: the starts of the
return channel for the task or its inbox items, as the start page shows them
(with their ways on and their forget), and the workflow runs of the last week
that belong to it. A run belongs to a task only where it names exactly one
open task: `task:<slug>`, `work/tasks/<slug>/` or `work/streams/<slug>/` in
the run's name, summary, arguments or script (an absolute path counts only
under this Bridge's own root), or a name that is the slug. A run that names
two tasks belongs to neither. The session it ran in being linked to the task,
and the folder it ran in ending in the slug, only confirm a mention: alone
they bind nothing, and a session linked to another task undoes it. Only the
runs of this Bridge are read: those whose session ran in the Bridge, a folder
inside it, one of its git worktrees, or a folder that holds no Bridge of its
own (the folder comes from the session's own file). The runs of another
Bridge on the machine, and of a session whose folder is unknown, never reach
this page. Each run says how it
stands, since when, why it belongs here and what it left. A finished run
whose result is not checked yet is a result that waits: it puts the file in
the second place of the queue, its step reads "Check the result of ...", and
the drawer stands open until **Checked** (the verb `run_seen`, kept in
`state.json`, key `runs_seen`). The runs reach the page with the sessions
(`runs` of the `sessions` event), read again every 30 seconds; the script of
a run never leaves the server.

The Files drawer lists the files of the task's folder besides STATUS.md:
every `*.md` and `*.yaml` up to eight folders deep, never in a `video/`,
`deliverables/` or `node_modules/` folder, never a hidden file or a link; the
listing never walks into such a folder. Any name can be read, umlauts and
brackets too, as long as it has no slash, backslash or control character and
does not start with a dot. A long file is read up to its first 40000
characters and says it was cut. A click reads one in
place, Markdown as formatted text and anything else as it stands, with its
path (`GET /api/task?slug=&file=`, which reads only a file that list names).
A folder with only STATUS.md shows no Files drawer.

On top of the Files view stands a search field of its own. It searches every
task, stream and closed task (`work/tasks/`, `work/streams/`, `work/done/`),
`work/log.md` and `work/archive/`: every `*.md` and `*.yaml`, never inside a
`video/` or `deliverables/` folder, never a hidden file, a link or anything
outside the Bridge. The words are plain text, never a pattern, matched without
regard to case one letter at a time ("ß" stays "ß", it never stands for "ss"),
and a file is a hit when its slug, its title and its lines hold every word
between them. A file is one folder, so an open task and a closed one with the
same slug are two files, each with its own hits; a file in a folder that is no
slug (`work/tasks/_briefings/`) is listed by its path, with nothing to open. The
results come by file, best first: the files whose slug or title holds every
word, then those with a hit in their STATUS.md, then the rest, open before
closed; a log row counts for the file its context column or its text names.
A click opens a file, a closed one too: one in the queue is walked to, any
other opens beside the queue on the same surface, with its drawers and "Back to
the queue" at its foot, a closed one by its folder (`GET /api/task?slug=&path=`).
While such a file is open the results fold to one line with the words searched
("Show results" unfolds them, "Clear" drops them). The same
search runs as a command, for a chat session as for a terminal: `python3 scripts/work-find.py gateway september` (`--json` for the
whole answer). It uses `rg` when it is installed and plain Python when not,
with the same answer either way (`GET /api/find?q=` runs that command).

Under the drawers a file takes a question ("Ask this file"): a quick chat of
its own ([section 5 of the cockpit page](bridge-cockpit.md#5-asking-claude-the-relay), read only) with the file's folder and cover sent along as
data. An open task becomes what the chat is about, so the chat leaves its list
once the task closes; a closed one is never named, or the chat would be taken
into the archive at once. With no file open, a question about the results
sends the result list along instead. An open task whose next step nobody
names, in the queue or opened from the search, offers "Suggest next step":
one read-only question whose answer stands in the file and nowhere else (not
in the chat lists, no note, no spinner on the chat tab); "Dismiss" drops it at
any time. Nothing is written until you press Take over, which keeps the step
in STATUS.md as `next: {what: ...}` with a dated note (`task.py next`, the
verb `task_set_next`).

**Switching the default.** Two keys of the `cockpit:` block ([section 1 of the cockpit page](bridge-cockpit.md#1-switch-it-on)) let
the Files view take over step by step, each off by default, so a Bridge that
sets neither sees the work tab as before:

- `work_view: files` opens the work tab on Files (`due`, `source` and `jev`
  name the other views; a view the tab does not offer opens Due). A click on
  the tab's switch still picks another view for this browser, and that click
  holds until the key changes: the first visit after a change opens the view
  the key names, once, whatever was clicked before. Setting the key back to
  `due` brings Due back the same way.
- `focus_to_files: true` lets the focus on the start page lead on into Files
  when it runs out: its calm card says "Continue with the files" in place of
  "Open the tasks", and its last step offers the same where the bar would say
  "That was the last one in this list"; `n` on the last step goes there too.
  The focus itself keeps what it walks (P0 and P1 of the tasks).

Both take effect with the next start of the cockpit (`bridge-cockpit.py stop`,
then `open`) and a reload of the page. The page says which view it opened: every opening of the work
tab, its view switch, the search of the command box and the focus's way on
leave one `page_view` line in the audit log with `view=` (`due`, `area`, `jev`
or `dossier`, the page's ids for Due, By source, By Jev and Files; [section 4 of the cockpit page](bridge-cockpit.md#4-safety-model)),
so how often each view is used can be counted before the default changes, for
instance with
`grep -c ' page_view briefing view=dossier' .bridge/cockpit/audit.log`.

**Files and areas.** The files view keeps to the area filter like the rest of
Work: the queue, its count ("2 of 5"), Previous and Next (and `n`/`p`), and with
them the results, workflow runs and inbox items that put a file in the queue,
hold the area's tasks only. A tab counts with the area by its workspace, or by
the task or inbox item of an area row it works on. A new filter keeps the file
in front where it stands in the new area, else the walk starts at the first
one. An area with nothing open says so and offers **All areas**; with the star
filter on as well it says that and offers to show unpinned files too. The
cover of a file names its area as the areas table does (its dot and name, or
a quiet "No area"); a click shows that area only, and while it is the filter
the chip reads pressed and a click lets it go. The search stays across every
area on purpose (a file hidden by the filter can still be found): each hit
names its area, and under a filter a short line says "Searches in all areas".
A hit of the area opens at its place in the queue; one of another area opens
beside the queue with everything of its own (its area, its results, the
suggestion). "Ask the file" concerns the open file only.
