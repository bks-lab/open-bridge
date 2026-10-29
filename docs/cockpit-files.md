---
summary: "The cockpit's Files tab: three columns as Work through (the list, the open record, its point's buttons), a search over every record first, Ask the AI with a block list (cockpit.files_search), one task at a time as a file, its queue, next step and drawers, the search across every task, asking a file, the suggestion, the workflow runs as results, the files under the area filter, every task as a file in the one list, and the switches cockpit.work_view, cockpit.focus_to_files, cockpit.files_scope and cockpit.files_search."
type: guide
last_updated: 2026-10-29
related:
  - bridge-cockpit.md
  - cockpit-areas.md
  - work-system.md
  - ../scripts/web/files.js
  - ../scripts/web/views/dossier.js
---

# The Files tab

> Part of [the Bridge cockpit](bridge-cockpit.md). The code is `scripts/web/files.js`,
> `views/dossier.js`, `text-files.js` and `files.css`; the tests are
> `scripts/tests/bridge_cockpit_files.test.mjs`,
> `scripts/tests/bridge_cockpit_files_count.test.mjs` and
> `scripts/tests/bridge_cockpit_files_all.test.mjs` (the list on the server:
> `scripts/tests/test_bridge_cockpit_files_all.py`).

**Files** is a tab of its own on every Bridge, with or without a work page,
right after the work tab (de: Akten). It is no view of the work tab any more: the
work tab's switch never offers it, and a stored or configured `files` view opens
this tab once and leaves the work tab on the view it falls back to.

**Three columns, as Arbeit > Abarbeiten** (Work through, round 6d). The tab has
one layout. The left column holds the search, "Walk through the active records",
the chips and the list of records; the middle shows the open record; the right
column is Work through's own side column (`views/flowside.js FlowAside`) for the
point that record is in Work through, with the same buttons (Let AI do it,
Advise, Done, Later, Drop, To tab and View where a tab exists, the tab's close
when it neither works nor asks (Done and close tab where its task or item is
still open), then Details and the fields; `files.js recordPoint` picks that point). No button stands twice: a
step in the walk has its verbs only on the right. A closed record, or a task no
row names, has no right column, since its buttons would act on nothing. A click
in the list opens the record beside it (`openRecord` in app.js) and marks it in
the list, which keeps where it was scrolled; Previous record and Next record then
walk the list in its order, while "Walk through the active records" walks the queue as
before. The head of an open record has one button, "Close the record" (de: Akte
schließen). The question to the AI stands in one place, under the chips of the
left column, whether a record is open or not, so the search stays the first
thing there. The eyebrow of a record says where it was opened: "Opened from the
search" when words stand in the field or the search results hold it, else
"Opened from the list". On a narrow screen the columns stack at the widths Work
through stacks (1180 px: the side column under the middle; 960 px: one column);
in one column an open record and its buttons come first, above the list, so a
click in the list shows its record at once. The middle holds only the open
record or the hint to pick one, never a second list.

## The search first

The tab opens on a search in its left column. A large field takes the focus, with "Walk through
the active records (n)" beside it, which starts the walk over the queue, one file
at a time. Under it stand chips, each group under its small label: **Area** (the
areas the records name, at most 12), **State** (open, done, all; open at first)
and **Kind** (task or stream; a closed record counts by what it was, so Task with
State all lists the closed tasks too), and the records changed last, newest first
(at most 30 shown, "30 of 120 shown"). Typing narrows the list at once, over
title, slug, area and theme, and over the text of every STATUS.md through the
same search as below (`/api/find`, a moment after the last key), with the line
that matched under the record as plain text (no Markdown marks, a table row's
cells joined by a dot, never a `slug:` line). A click opens the record as a file
in the middle (below), and the list with the words typed stays beside it.
The field is the one search of the tab: an opened record has no second one.

The records come from `GET /api/records`, a read: every folder of `work/tasks/`,
`work/streams/` and `work/done/`, its front matter read in place (status,
priority, area or context, the last change, title, kind), newest first, at most
2000. A record's area comes from one place for the list and the opened record:
the area of its row, else of its file of `model.files`, else the one its front
matter names (`area`, else `context`).

**Ask the AI** (de: Die KI fragen) stands under the chips where
`cockpit.files_search.enabled` is true: a field of its own for the question and
a button "Ask the AI about these n records". It sends that question, or a
default one when the field is empty, with at most 12 of the records listed to a
model, in one call with no tools, no settings and no session (the verb
`files_ask`), and only on the click; the search words are never the question.
A page with `search: true` asks the history the same way, with the same switch,
budget and block list (the verb `timeline_ask`, see "A page's search" in
[`bridge-cockpit.md`](bridge-cockpit.md)).
The answer stands under it with a link to each record it names. Before the click
a line says what a click sends, which words keep others private and how many
questions are left today ("A click sends 2 records to the AI. 1 record stays
private: insurance. 19 questions left today."); with none left the button
waits, and with no record listed the line says so and nothing about privacy.
The block list is `cockpit.files_search.block`: a record whose area (front
matter and row), context, theme, path, title or the text that would go (the
start of its STATUS.md, with its front matter and `related:`) holds one of its
words, case folded, is dropped on the server before the request is built, so it
never reaches the prompt. A word also matches inside a longer one (`tax` holds
back `taxonomy` too): the list holds back more, never less. `GET /api/records`
names, per record, the words that hold it (`held`, only with the question on and
a block list), so the count before the click is the server's. When every record
sent is gone since the page read them, the answer is "the records have changed,
search again", not the block list. The calls of a day are capped
by `budget_per_day` (20) and counted in `.bridge/cockpit/flow-activity.json`;
the model is `model`, else the service `cockpit-files` of `workflow/ai-services/`
(default Haiku).

```yaml
cockpit:
  files_search:
    enabled: true
    budget_per_day: 20
    block: [insurance, health, tax, family]
```

## One task at a time

The walk shows one task at a time as
a file, on one framed surface in the middle column, with "Close the record"
above it. On the surface: an eyebrow (File, "2 of 16", status, kind and
priority, the slug on the right), the task's title as the one heading, and the
situation in one sentence (the `headline` of its STATUS.md, else what the
triage made of it, always with where that comes from and its date). Under it
the next step as the one strong block (its verbs stand in the right column), then the
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

A link to a task inside this tab opens it here. Anywhere else (a
point of Work through, Not now, a card, the start page) an open task opens in
the Files tab with that record open (`files.js fileClick`): in the walk where
the queue holds it, else beside it. Only where `cockpit.work_views` keeps no
`files` does a task open in the item drawer over the page, as before.

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
page cannot count them. With `cockpit.files_scope: all` (below) that sentence
goes, since the backlog stands in the list on the left like every other record.
Under an area that hides some, **Show every area**
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

The search (the field of the start, or a search from elsewhere such as the command box) searches every
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

**Switching the default.** Keys of the `cockpit:` block ([section 1 of the cockpit page](bridge-cockpit.md#1-switch-it-on)) let
the Files tab go further, each off by default:

- `work_view: files` no longer names a view of the work tab: the first visit of
  the work tab after it opens the Files tab once, and the work tab keeps the view
  it falls back to (`due`, `source`, `jev` and `flow` name its views).
- `focus_to_files: true` lets the focus on the start page lead on into Files
  when it runs out: its calm card says "Continue with the files" in place of
  "Open the tasks", and its last step offers the same where the bar would say
  "That was the last one in this list"; `n` on the last step goes there too.
  The focus itself keeps what it walks (P0 and P1 of the tasks).

- `files_scope: all` makes every task and stream a file (below). The default
  `active` keeps the queue alone, as it always was.
- `files_search` switches on Ask the AI and holds its block list (above).

They take effect with the next start of the cockpit (`bridge-cockpit.py stop`,
then `open`) and a reload of the page. The page says which page and view it opened: every opening of a tab, the work
tab's view switch, the search of the command box and the focus's way on leave
one `page_view` line in the audit log, with the page id (`@files` for this tab)
and, on the work tab, `view=` (`due`, `area`, `jev` or `flow`; [section 4 of the cockpit page](bridge-cockpit.md#4-safety-model)),
so how often each is used can be counted, for instance with
`grep -c ' page_view @files' .bridge/cockpit/audit.log`.

## Every task as a file

With `cockpit.files_scope: all` every task and stream is a file, and the queue
is only the order the view walks them in. Every record, the backlog too, stands
in the one list on the left; the middle holds no second list (round 6d took out
the chips Active, Waiting, Resting, Backlog and All, which counted apart from
that list). A click on a file opens it the way the list does: one in the queue
is walked to, any other opens beside it. A file outside the queue that rests
(its tooltip names what blocks it), is dropped, is put off (with the day it
comes back) or waits says so as a chip on its cover; a file of the queue never
does, since its place says why it is there. Closed tasks never become files
here; the search finds them.

The server sends the list apart from the rows (`model.files`), so nothing that
reads the rows changes: one read of `workplace.py tasks --all --json` per pass
that reads the tasks, of which the rows, the WIP count and the focus keep the
`doing` and `review` ones they always had. The list goes out with every poll,
so each file carries only what the cover and its reason chip read: `slug`,
`kind` (`task` or `stream`), `status`, `area_names` (the workspace the task
maps to and its aliases, as the rows have them), `priority`, `title`,
`updated`, `blocked_by`, `bucket` (of the row that stands for it, none for a
backlog task), `deferred` and `deferred_until`. The cover of an opened file
reads its headline, next step and progress from the task itself
(`/api/task`), so they stay out of the list. With `active` the argv stays `tasks --json` and `model.files` is
`null`. In the demo page `?files_scope=all` shows it.

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
