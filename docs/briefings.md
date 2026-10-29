---
summary: "Briefing profiles: each person describes the briefing they want in workflow/briefings/<id>.yaml (sections, trackers, queries, inbox rules, and a view: how it is shown); scripts/briefing.py executes it and the agent advises on the result. Section kinds, provider query keys, selection, views (sources, triage, brevity, plan), change marks, inbox rules, org profiles."
type: guide
last_updated: 2026-10-29
related:
  - bridge-cockpit.md
  - ../workflow/briefings/_schema.yaml
  - ../workflow/briefings/_template.yaml
  - ../scripts/briefing.py
  - ../scripts/tests/test_briefing.py
  - ../scripts/tests/test_briefing_providers.py
  - ../scripts/lib/briefing_view.py
  - ../scripts/tests/test_briefing_view.py
  - ../trackers/README.md
  - ../skills/briefing/references/workflow.md
  - ../skills/briefing/references/control.md
  - inbox.md
  - workplace.md
---

# Briefing profiles

Every person who uses a Bridge wants a different morning. One works from
GitHub issues, one from a Jira project, one from a customer's Azure board and
a calendar. A **briefing profile** says which, in a file the person owns:

```
workflow/briefings/morning.yaml     # plain /briefing
workflow/briefings/acme.yaml        # /briefing acme, before the customer call
workflow/briefings/weekly.yaml      # /briefing weekly, Friday afternoon
```

`scripts/briefing.py` runs the profile: every section with its own time limit,
side by side (each is its own program or service), the result in the order
written. The agent then advises on and renders what came back
(`skills/briefing/references/control.md`). Collection is code, not prose an
agent re-reads each morning, because a prose step can be skipped and nobody
notices: on one observed morning the trackers were not queried at all.

## Commands

```bash
python3 scripts/briefing.py list                  # the profiles, the default, their offer_on phrases
python3 scripts/briefing.py show [<id>]           # the resolved profile (also the built-in one)
python3 scripts/briefing.py offer "<text>"        # profiles whose offer_on matches the text
python3 scripts/briefing.py collect [<id>] --json --file
python3 scripts/briefing.py render [<id>] --file  # the morning run: collect, file, bookkeeping, view
python3 scripts/briefing.py render [<id>]         # collect + terminal text in the profile's view
python3 scripts/briefing.py render --style plan   # another view for this one run
python3 scripts/briefing.py collect --skip tracker --skip calendar   # the quick mode
python3 scripts/briefing.py collect --only tracker --only calendar   # only these kinds, the rest listed as skipped
python3 scripts/briefing.py collect --json --max-items 500   # every row, for a dashboard that pages itself
python3 scripts/briefing.py collect --fresh       # ask every source now, whatever cache_minutes allows
python3 scripts/briefing.py collect --json --setup  # also the cockpit's Setup page (scripts/bridge-setup.py)
python3 scripts/briefing.py owed [<id>]           # streams the profile does not cover, and how to run them
python3 scripts/briefing.py validate              # every profile; exit 1 on a problem
```

## Which profile runs

1. The id given (`/briefing acme`).
2. bridge-config.yaml `briefing.default`: the person's own choice, which wins
   over a flag in a file that may come from a shared overlay.
3. The profile with `default: true` (at most one; `validate` refuses two).
4. The only profile, when there is one.
5. Several and none chosen: `collect` exits 2 and names them; the agent asks.
6. No profile at all: the **built-in** one, equal to the briefing before
   profiles existed (inbox, advise, tasks, the trackers enabled under
   `integrations.*`, calendar when a tool is installed, activity, and the
   day's tabs when a `workplace:` block is configured). Existing Bridges keep
   working without a file.

`offer_on` lists phrases on which the Bridge proposes a profile by name
("good morning" → morning, "acme" → acme). That is how a Bridge with several
profiles offers the right one instead of the person having to remember ids.

`extends: <id>` builds one profile on another: the base's sections first (a
section with the same id is replaced by the profile's own), then its own; the
base's `view` key by key, the profile's own keys winning; the base's `mutes`
added. `id`, `title`, `default` and `offer_on` stay the profile's own, so an
extending profile never becomes the default briefing by accident. This is how
the cockpit works on top of the briefing: a profile `cockpit` with
`extends: morning` takes every section of the morning briefing and adds what
only the cockpit shows (resources, token use) and its pages, while
`/briefing` keeps running the lean morning profile. The cockpit picks it with
`cockpit.profile` ([`bridge-cockpit.md`](bridge-cockpit.md) § 8).

## Section kinds

| kind | Shows | Keys |
|---|---|---|
| `inbox` | open inbox items, most urgent first ([inbox](inbox.md)) | `max` |
| `advise` | the advice checks: collisions, quiet and blocked tasks, WIP | `max` |
| `workplace` | the day's tab plan: one tab per task, grouped into workspaces, opened on your yes through the configured driver (cmux ships as `skills/cmux`) ([workplace](workplace.md)) | `max` |
| `tasks` | `work/tasks/*/STATUS.md` | `status` (default doing, review), `contexts`, `max` |
| `activity` | `work/log.md` rows of the last days | `days` (default 7), `max` |
| `commits` | commits per repository per day as a sparkline (`▁▃█▂`), busiest first, by local committer date (the date `--since` filters on, so a rebase or another time zone lands on the right day). Repositories without commits in the window are left out; one that cannot be read is named under housekeeping; reaching the time limit fails the section instead of hiding repositories | `days` (1 or more, default 7), `repos` (registered names or paths; default: every clone the ecosystem files register, plus this Bridge; a clone is `local_path`, else `local_root` + the repository name from `github:`, and a file without `local_root` uses the one in `ecosystem.yaml`; `${var}` from bridge-config `identity:`), `author` (`me` = each repository's git user.email), `all_branches` (every local branch) |
| `calendar` | events in local time; also handed to `advise` for collisions. `ics` converts UTC and `TZID` times but lists a recurring event (RRULE) on its first date only: use `icalbuddy` or a `command` for recurring calendars | `provider` (auto, icalbuddy, ics, command), `days`, `path` (ics), `argv` (command), `exclude_calendars` (icalbuddy), `info_calendars` (calendar names whose events are information, not a commitment: see Calendar and all clear), `event_steps` and `prepare` (see Calendar steps) |
| `tracker` | work items from an external system | `provider`, `query`, `account_ref`, `state_map`, `max`, `to_inbox` |
| `command` | any program printing a JSON list of items | `argv`, `max`, `to_inbox` |

Every section takes `id` (stable name, defaults to the kind; two sections of
one kind need distinct ids), `title`, `max` and `to_inbox`. Items follow the
normalized schema of [`trackers/README.md`](../trackers/README.md).

## Tracker providers

Each provider is a module under `scripts/lib/briefing_providers/`, tested
against recorded answers (`scripts/tests/fixtures/briefing/<provider>/`).
`trackers/*.md` stay as the documentation of each system.

| provider | Reaches it through | `query` keys |
|---|---|---|
| `github` | `gh search` (gh's own login) | `assignee` (default `@me`), `owners`, `repos`, `kinds` (issues, prs), `state`, `labels`, `review_requested`, `authored` (true: your own open PRs, with their age), `others_prs` (N: colleagues' open, non-draft PRs in `owners`/`repos` updated in the last N days, bots and your own left out), `limit` |
| `github-board` | one lean GraphQL query per board (`gh project item-list` only when it cannot answer), boards from `github_projects:` in the ecosystem files, state maps and the board's fields from `workflow/projects/` (the same code as `scripts/tracker-sync.py`; see below). GitHub filters before the limit (`filter`, default `is:open`): gh lists the oldest cards first, so without it a board with more cards than `limit` lost its newest, open ones. Draft cards are rows too (type `draft`, no number, no link, never their text), so with every card shown the counts and the rows agree. With `summary: true` on the section, also one line per board with its open cards per state, counted before `assigned_to_me` and the other filters, with the section's `state_map` applied; a status no map knows (Parked, Canceled) is not open work, and a board that filled `limit` says so | `boards`, `assigned_to_me`, `states`, `include_done`, `filter` (the board's filter syntax; `""` for every card), `limit` |
| `github-work` | both of the above, merged: one row per issue or pull request (see GitHub work) | every `github` key, plus `boards` (the others start switched off), `cards` (`mine`, default, or `all` open cards), `filter`, `board_limit`, `links` (false: do not ask which pull requests close an issue), `done_days` (N, default 7: also count your issues closed and pull requests merged in the last N days; 0 asks none) |
| `gitlab` | `glab issue list` | `repos` (required), `assignee`, `state`, `labels`, `limit` |
| `ado` | `az boards query` (WIQL) | `wiql`, `organization`, `project`, `limit` |
| `jira` | REST API | `jql` (default: assigned to you, not done), `fields`, `limit` |
| `linear` | GraphQL API | `filter`, `team`, `limit` |

`state_map` on a section maps a raw state to a normalized one
(`{"Waiting for vendor": blocked}`) and overrides the provider's default.

**Which fields a board card reads.** Two optional keys in the board's registry
(`workflow/projects/<slug>.yaml`, block `board:`, the block board-pilot reads too)
name them:

- `board.status_field`: the single-select field that carries the board's
  lifecycle, default `Status`. A board whose lifecycle lives in a custom column
  (`status_field: Workflow`) shows that column's value on its rows, maps it
  through the registry's `state_map` and counts its cards per state by it.
  Without the key the built-in `Status` is read, as before.
- `board.priority_field`: a single-select priority field (`priority_field:
  Priority` with P1, P2, P3). When set, the query asks that one field more and
  each row carries the option name as `priority` (shown as a column wherever a
  view shows priority, and as a chip on the cockpit's GitHub page, which can
  sort by it). No default: a board without the key asks nothing more and its
  rows carry no priority.

Both go into the same lean query, so a board costs the same few points either
way.

### Tokens: references only

`gh`, `glab` and `az` use their own login; the profile carries no credential.
Jira and Linear need a token, and it never goes into the profile:
`account_ref` names an `identity/accounts/<id>.yaml` with the endpoint and a
`token_ref` **reference URI**, which `scripts/briefing.py` resolves through
the secrets engine at run time ([`rules/secret-placement.md`](../rules/secret-placement.md)).

```yaml
# identity/accounts/jira-example.yaml
id: jira-example
scope: user
display_name: "Jira (example)"
owner: your-handle
base_url: https://example.atlassian.net
email: you@example.com                       # Cloud basic auth
token_ref: keychain://example/jira-token     # the value lives in the keychain
# auth: bearer                               # Data Center personal access token
```

`validate` refuses a profile with a credential-named key holding a plain
value, and any value read through the engine is scrubbed from error lines.

## Views

The sections say where the data comes from. The `view:` block says how the
reader sees it, and every person picks their own:

| `style` | What the reader gets |
|---|---|
| `sources` | One block per section, in profile order. The default: a profile without `view:` looks as it always did. |
| `triage` | Every row sorted by what to do with it: **do** (you, now), **plan** (you, no date), **delegate** (the Bridge does it), **waiting** (on someone else, with how long), **drop** (park it?). A thing two sources carry (the same issue on GitHub and on a board) is one row naming both. Housekeeping comes last. |
| `brevity` | The bottom line, then the top three with why each matters, then how many more. For a phone or a busy day. |
| `plan` | Your rows laid into today's free calendar gaps, what the Bridge does meanwhile, and when the day ends. |
| `report` | Markdown that reads like a report, by exception: one **status** line naming only what failed (✗) or needs a look (⚠, a `report_ok` section with rows) and the green ones in one go (✓), the calendar (a table from two events on), the **first** rows in bold, then each bucket as a short numbered list. A bucket shows `view.report.per_bucket` rows (default 5), taken in turn from each source so one source cannot fill it, and counts the rest. Tables only where rows compare. Issue and PR ids are links; internal ids stay out. |

```yaml
view:
  style: triage            # sources | triage | brevity | plan | report
  headline: true           # one bottom line on top: asks for you today (and the other Do rows apart), free until, next hard date
  dayline: true            # the workday as one line: · free, █ busy, ▲ now (not in brevity)
  report: {top: 3, per_bucket: 5}   # style report: rows in bold first, rows per bucket
  overview: inline         # inline | file: Boards and Activity below the buckets, or in a file
  agenda: true             # Calendar block: every event from now through the lookahead, overlaps marked
  since_last: true         # "since 07:18: 2 new, 1 changed"
  lookahead_days: 1        # due within today + 1 day counts as now; deferred items coming back show
  max_items: 12            # the whole briefing, then "+N more" and an explicit end
  answer_keys: true        # numbered rows, letters per bucket: answer "1a 3b"
  hygiene: bottom          # bottom | hide
  color: auto              # colour only where it means something; none = never
  width: 100               # rows wrap at a word, never cut inside one
  labels: {end: "That's all for today."}
  buckets:                 # order, titles, answer letters; a bucket left out is hidden and counted
    - {id: do, title: "Do (you, today)", options: [yes, later, drop]}
    - {id: delegate, title: "I'll do"}
    - {id: plan}
    - {id: waiting, nudge_after_days: 7}
    - {id: drop}
  plan:                    # style plan only
    workday: {start: "08:00", end: "17:00"}
    default_minutes: 30

mutes:                     # rows the person never wants again; the briefing says how many it hid
  - {section: advise, when: {check: quiet}}
```

`render --style <style>` shows one run another way without touching the file;
`collect --json` carries the computed view under `view` for the agent. A new
profile copied from the template starts with `triage`; a profile without a
`view:` block keeps one block per section.

Two overview blocks sit below the buckets, never in them, since they say what
moved rather than what to do: **Boards** (one line per board of a `github-board`
section with `summary: true`, boards without open cards left out) and
**Activity** (the `commits` sections' sparklines). `brevity` leaves both out. With
`view.overview: file` they leave the printed text altogether: `render` writes them
to `.bridge/briefings/<id>.overview.txt` and housekeeping names the file (label
`overview_file`). Meant for a briefing an agent copies into a chat by hand, where
a long block is the part that gets copied wrong.

Small aids for reading at a glance: each bucket header says how many rows it
holds (`── Plan · 4 ──`, also when `max_items` shows fewer), the day line puts
the calendar in one row, and in a colour terminal an issue id is a link (OSC 8)
to its page. A first run (no previous snapshot) marks nothing as new, since
there is nothing to compare with.

**Which bucket a row lands in** is a fixed rule, so the shape never depends on
which agent renders it:

| Source | Bucket |
|---|---|
| inbox item, urgency `now`/`today`, or due within the lookahead | do |
| inbox item otherwise | plan |
| inbox item deferred and back within the lookahead | do if only you can or it is due within the lookahead, else plan |
| inbox item the briefing filed from a tracker row (`to_inbox`) | the same row as that tracker row, not a second one |
| inbox item waiting for a condition (`waits_for`, [inbox.md](inbox.md)) | waiting, worded "Waiting for: …" (label `waiting_for`) |
| inbox item filed by "ask about this row" (key `ask:<inbox id>` or `ask:<owner/repo#n>`) | part of the row it asks about |
| task with `next: {who: bridge}` | delegate |
| task with `next: {who: me}` (or the profile's `for`) | do if `next.due` is within the lookahead, else plan |
| task with `next.who` naming anyone else | waiting, with days since `last_updated` |
| task with `blocked_by` | waiting, with days since `blocked_since` (else `last_updated`); a nudge once `nudge_after_days` passed |
| task without a next step | housekeeping: "N tasks without a next step" |
| advice `quiet` | drop (the task shows once, there) |
| advice `collision` | do · `wip`: housekeeping · `blocked`, `waiting`, `due`: carried by their row |
| tracker row in review or `category: qa` | do · `blocked`: waiting · done/removed: left out · else plan |
| tracker rows with `untasked: true` | housekeeping: "<section>: assigned to you without a task: N" (label `untasked`), beside their own rows |
| a section that failed | housekeeping, with its reason |
| calendar | the headline, the Calendar block and the plan; activity: the since line; workplace: one line |
| two calendar events within the lookahead that overlap | do ("A and B overlap"), and both are marked in the Calendar block |
| an overlap with an info event (`info_calendars`) | no row: the Calendar block marks both entries "alongside …" and tags the info event |

When two sources carry the same thing, the row takes the more urgent bucket of
the two, unless a section forces its own. Only ids that name their repository
(`owner/repo#12`) are merged across sections; any other id (a command's `1`, an
ADO number) stays apart per section. A section's `max:` still caps how many rows
it contributes. A section can force its rows into one bucket (`bucket: delegate`),
which wins over the derived bucket, or keep them out of the view (`bucket: none`).
Advice that repeats a row (`blocked`, `waiting`, `due`) is folded into that row
and stands alone only when no such row is shown.

**One matter, one line.** When a task has an inbox line in a shown bucket, that
line wins: a tracker or command row about the same task (its `task`, or
`about_task`, which a GitHub row gets from the task whose `sync.github` names
it) becomes part of it, adding its source, its link, its date and its reasons
instead of a line of its own. The task's own row (its next step, or what blocks
it) joins as a reason too, but only while the inbox line stands in a bucket at
least as urgent as that row, so a next step due today never hides behind an item
put off for later. Two inbox items of one task stay two lines, since each is a
lever of its own; of several, the most urgent takes the folded rows. A command
row is folded only when it names its task (`task` or `about_task` on the item).

**The headline count.** "N asks for you today" counts the asks among the Do rows
(every row that is no inbox item, and of the inbox only an ask). When Do holds
more, reports and ideas filed for today, they are counted apart ("· 3 reports",
label `do_reports`), so the number never stands unexplained above a longer list. Housekeeping (failed sources,
muted rows) shows in every style, `brevity` included; `plan` shows every row
somewhere (laid out, meanwhile, waiting, drop, later), so it has no "+N more". The next step of a task is a frontmatter field
in its STATUS.md: `next: {what: "Draft the request", who: bridge, due: 2026-10-07,
estimate_min: 20}` (`who`: `bridge`, `me`, or a person).

**Labels.** Every word the reader sees has a label name, so a profile can speak
the person's language: `yours_today` and `do_reports` (each with a `_one` singular for a count of
one; a profile that sets only the plural gets it for one too), `free_until`, `free_rest`, `busy_until`,
`next_date`, `since`, `today`, `tomorrow`, `due`, `back_on`, `only_you`,
`collides`, `waiting_days`, `waiting_for`, `with`, `task`, `next_step`, `nudge`, `new`, `housekeeping`,
`no_next`, `muted`, `hidden`, `error`, `workplace`, `more`, `end`, `why`,
`meanwhile`, `later`, `shutdown`, `activity_title`, `commits`, `boards_title`,
`st_new`, `st_ready`, `st_in_progress`, `st_review`, `st_blocked`, `agenda_title`,
`clashes`, `clash_row`, `parallel`, `info_tag`, `all_clear`, `owed`, `overview_file`, `untasked`, the Setup page's `page_setup`, `section_setup_checks`, `section_setup_available` and `section_setup_on` (the `setup_*` words of its rows come from `scripts/bridge-setup.py` in the Bridge's language and are not renamed by a profile), and for `report` `report_title`, `lage`, `first_title`, `bucket_more` and the table columns `col_when`, `col_what`, `col_note`, `col_board`, `col_repo`, `col_branch`, `col_days`, `col_commits`. Placeholders in braces stay as they are: a label may use only the placeholders
its default has (`validate` names them), and one that would not format falls
back to the default wording instead of breaking the briefing.

**Calendar and all clear.** "Free until 16:00" alone hides what is at 16:00, so
the Calendar block lists every event from now through `lookahead_days`, and two
events that overlap are marked there and become one do row. A section with
`report_ok: true` says `<title>: all clear` under the headline when it completed
with nothing open: a green source must read differently from one that never ran.
A failed or skipped section never claims it; its failure is housekeeping. Rows
the person muted count as nothing open. The line belongs to the views; `sources`
shows the section with its count `(0)` instead. The same event from two
calendars is listed once, and events that overlap in a chain (A with B, B with C)
are one do row naming all of them; `plan` lays events out itself and gets no
such row.

**Info calendars.** Some calendars say what others do, not what the reader
committed to: a family calendar, a shared team rota. List them on the calendar
section as `info_calendars: [Family]`. Their events stay in the Calendar block,
tagged `[info]`, and an overlap with one is marked `alongside <title>` on both
entries, but it never becomes a do row, never makes the headline say "busy",
never blocks a slot in `plan`, and never raises an advise collision. Two
ordinary events still clash as before, and an info event in the same chain is
named beside them, not in the row. `icalbuddy` lists the events under the
calendar they come from (`-sc`) and matches the names; `ics` matches the file's
`X-WR-CALNAME`; a `command` marks an event `"info": true` or names its
`"calendar"`. An event that is in an info calendar and in an ordinary one counts
as ordinary.

**What an event carries.** Each calendar row names its `calendar`, and where the
source has them its `location`, its `attendees` and a meeting link as `url`
(Teams, Zoom, Google Meet, Webex, Whereby, Jitsi), found in the event's URL,
location or notes. The notes themselves never leave the provider; only that link
does. A `command` provider may hand the same fields through.

**Calendar steps.** A calendar row offers steps a dashboard shows as buttons on
the opened event. Each starts an agent tab: the step's prompt is filed as an
inbox item under the event (`event:<step>:<start> <title>`, so a second click
finds the same item) and launched like Do it. Built in is `prepare` on every
event of the reader's own that has not begun: the tab gathers what bears on the
event (tasks, inbox, log, earlier meeting notes, mails, issues) and writes a
short brief, read only. A section adds its own:

```yaml
- kind: calendar
  provider: icalbuddy
  event_steps:
    - id: prepare                 # stands in for the built-in prepare on these events
      label: "Prepare the weekly"
      match: "^Team weekly$"      # a pattern on the title, case does not matter
      calendars: [Work]           # optional
      prompt: "Prepare the team weekly of {date}: the open board items and last week's notes, one line each."
    - id: followup
      label: "Follow up"
      match: "weekly"
      phase: after                # before (default): not begun yet; after: over
      prompt: "/debrief the team weekly of {date}"
  prepare: true                   # false: no built-in prepare step
```

`{title}` `{date}` `{time}` `{start}` `{end}` `{calendar}` `{location}`
`{attendees}` are filled in from the event. `briefing.py act <profile> <section>
<row-id> <step>` asks the calendar again and answers only when the event still
offers the step: `{"did": ..., "launch": {"summary", "prompt", "key"}}`, which
the cockpit files and starts. The step itself runs nothing.

**GitHub work.** A `github` and a `github-board` section side by side show the
same card twice, and they disagree: the search says `open`, the board `In
Progress`. A `github-work` section asks both side by side and keeps one row per
issue or pull request: the board's status wins, the search adds what only it
knows (asked to review, your own pull request and its age), and each row names
its `board` (name, slug, number, org and its `workflow/projects/` file), a
`group` (the board, else the repository), and the open pull requests that close
it (`prs`, one GraphQL call for all rows). A pull request that closes an issue
in the list stands in that issue's row instead of one of its own, unless you
were asked to review it.

`link` (default true for the GitHub providers `github`, `github-board` and
`github-work`; `link: false` turns it off) adds what this Bridge knows about a row:
the task whose `sync.github` names it (a task in `work/tasks/` becomes the row's
`task`, so a dashboard opens or jumps to its tab; a stream is only named, as
`linked_task`) and the newest active inbox item whose key ends in the row id
(`inbox`): the item a step, Do it or a `to_inbox` rule filed for it, whose tab a
dashboard then shows on the row. Any other filer whose key ends in `:<row id>`
attaches the same way (a daily radar that files `<source>:<anything>:<owner/repo>#<n>`,
say): the item joins the row and never adds one of its own.

With `link` on, every row also carries `untasked`, a boolean: true for an open
issue assigned to you that no task or stream names in `sync.github` (a pull
request never is; a task or stream that is `done` tracks nothing, and one that
is not wins the link over it). A board card counts as yours by
`integrations.github.assignee_me` or else the login the search already asked
for. When the tasks could not be read, `untasked` is left out and the row
carries `unknown: [untasked]`, because unknown is not the same as untracked:
the figure is not shown, and an item a rule on `untasked` filed earlier stays
open instead of closing and coming back as new. Such a row offers Analyse, Make
it a task, and Implement when no pull request closes it, a dashboard marks it
with a **no task** chip, and the text briefing says how many there are
(`2 assigned issues without a task`, the `untasked` label in the bucketed
styles). That count is information, never an order to create tasks: an assigned
issue is itself the task, and the tracker is where it stays. A rule `{when: {untasked: true}}` files them; a profile
whose rows a radar already files needs no such rule, since both items would
attach to the one row.

Each board of a `github-work` section has a switch a person sets on a
dashboard: **off** (not asked, costs nothing), **mine** (your cards) or **all**
(every open card). The choice is kept in `.bridge/github-boards.json`, beside the
profile and never in it, and wins over `boards` and `cards`. The same file may
hold the person's `default` for boards not switched yet (a board new in the
registry, say), which wins over the profile as well; without it the profile
decides. The section's `summary` names every registered board with its mode and
that default, a board switched off without counts. The cockpit hides a board
switched off from its GitHub page and lists every board, with the default, in
its settings (area GitHub boards).

A dashboard shows figures above the rows (`metrics` of the page section: open,
yours, wanting your review, your open pull requests with the oldest one's age,
in progress, in review, blocked, quiet for 14 days, yours without a task, and
what you closed and merged in the last `done_days`), the boards as tiles with their open cards per
state, and the people the rows are with; each is a filter on the rows. A row
carries `flags` (what the figures count) and `who` (its assignee).

`briefing.py detail <owner/repo#n>` prints one issue or pull request as a
dashboard opens it: body, the last five comments, labels, assignees, the boards
it sits on with their status, the pull requests that close it, and for a pull
request its branch, size, review decision, requested reviewers and checks (the
failing and running ones by name). One GraphQL call of about one point, kept ten
minutes (`.bridge/briefing-cache/github-detail/`, `--fresh` asks again), under
the same block as every section: while GitHub is blocked it shows the last kept
detail, said to be old.

Every row of a GitHub provider that is not done offers steps, which a dashboard
shows like a calendar row's. Built in: **Analyse** on every row, **Implement**
on an issue without a pull request, **Review the PR** on a pull request or an
issue that has one, **Make it a task** on an issue no task syncs, **Sync status**
on a row on a board or with a task, **Remind** on a row someone else is
assigned to (a short reminder drafted as a comment that mentions them, or a
mail or chat draft; nothing is posted or sent without a yes). Each starts an agent tab whose prompt
carries the row's facts (link, status, board, its config file, the task, the
pull requests) and an instruction with its gates: read only and drafts until a
yes for Analyse and Review, a feature branch and a draft pull request for
Implement, board fields only through the `github-projects-manager` skill, never a
merge. A board's **draft card** (a project item without an issue or pull
request behind it) is a row too, id `draft:<board slug>:<project item id>` and
type `draft`, with its title, status and assignees but no number and no link,
and never its text. It offers only Analyse and Make it a task, each told that
there is no issue and that the card's text stays where it is; a section's own
step reaches it only when its `types` name `draft`. `default_steps: false` turns
the built-in steps off; a section adds its own. `cards: all` brings every open card of the boards; a card that is
not yours (`others`: neither assigned to you nor opened by you, nor found by your search) is a row of the page and its
filters only, never a row of the briefing's buckets, so the work view keeps to yours as with `cards: mine`:

```yaml
- kind: tracker
  id: github-work
  provider: github-work
  query: {owners: [example-org], others_prs: 14, cards: mine}
  cache_minutes: 5
  row_steps:
    - id: implement              # stands in for the built-in Implement
      label: "Run the pipeline"
      types: [issue]             # optional: issue, pr, draft
      boards: [example-board]    # optional: board slugs
      states: [ready]            # optional: normalized states
      match: "^feat"             # optional: a pattern on the title
      prompt: "/board-pilot {id} on {board_slug}"
```

`{id}` `{title}` `{url}` `{type}` `{state}` `{status}` `{board}` `{board_slug}`
`{board_config}` `{task}` `{prs}` are filled in. `briefing.py act <profile>
<section> <row-id> <step>` reads the rows the page was drawn from (the section's
kept answer of today, else it asks again) and answers only when the row still
offers the step: `{"did": ..., "launch": {"summary", "prompt", "key"}}` with the
key `tracker:<step>:<row id>`, so a second click finds the same inbox item and
the row names it. The step itself runs nothing and writes nothing to GitHub.

**Owed streams.** A profile covers some of the playbook's streams; the rest
are still run by the agent. `briefing.py owed [<id>]` names every stream that
applies to this Bridge (`prs`, `meetings`, `imports`, `upstream`,
`applications`, `channels`, `backups`) and that no section covers, each with how
to run it, and the view repeats the list under housekeeping (label `owed`). A
section declares what it covers with `covers: [meetings]`; a github tracker with
`others_prs` covers `prs` by itself. So the agent runs exactly the gaps, instead
of guessing which ones exist.

The upstream stream ships its own source, so it can live in the profile instead
of being run by hand:

```yaml
  - kind: command
    id: upstream
    title: "Upstreams"
    argv: ["python3", "skills/briefing/scripts/upstream_items.py"]
    covers: [upstream]
    report_ok: true
```

It fetches each CORE upstream through the remote whose URL names it and counts
the commits not merged yet, and reads org overlays through
`scripts/overlay.py status --json`. An upstream it cannot reach is a row, never
"in sync".

**Bookkeeping.** `--file` also does what the playbook once left to the agent,
because a step a run can skip is a step nobody did: it opens today's day block in
`work/log.md` when missing, writes the briefing's log row into today's block (inside its table, wherever the
block stands; a second filing run within 30 minutes replaces the row instead of
adding one),
regenerates `work/board.md` through `scripts/gen-board.py`, and names an overdue
archive (`scripts/archive-buckets.py`) under housekeeping. A step that fails is a
housekeeping line, never an abort.

**Feedback.** "Not this again" on a row becomes a `mutes:` entry matching it
(same matching as `to_inbox`). The briefing still says how many rows it hid,
so a mute never makes something disappear without a trace.

## Dashboard pages

Setting the dashboard up, step by step: [`bridge-cockpit.md`](bridge-cockpit.md)
(section 8 builds the profile).

A dashboard (the cockpit, `scripts/bridge-cockpit.py`, a local web page) shows the
briefing as one page and every other section on tabs beside it. Which section
stands on which tab differs per person, so the profile says it:

```yaml
view:
  pages:
    - id: systems
      title: Systems
      sections:
        - {id: probes, alarm: true, empty: "all probes green"}
        - {id: upstream, empty: "nothing behind"}
    - id: dates
      title: Dates
      group: more            # cockpit: after the daily tabs, folded behind More when the bar is too narrow
      overview: true         # cockpit: opens it with a tile per section, each a jump to it
      search: true           # cockpit: a search over its rows, every day before and Ask AI (bridge-cockpit.md)
      sections: [calendar, deadlines]
    - id: github
      title: GitHub
      sections:
        - {id: github-work, view: board}   # one row per issue or PR, under its board, with steps
    - id: day
      title: Daily log
      search: true
      sections:
        - {id: activity, view: log}        # cockpit: the log by hour, its contexts as topic chips beside it
        - {id: commits, place: rail}       # cockpit: in the column beside the log, as repository tiles
    - id: work
      title: Work
      jev:                   # cockpit with Jev on: orders the rows on a click, never by itself
        skip_sections: [applications]   # these rows never go out
        private: [private, family]      # nor rows whose title, detail, task, source or gist holds one
      sections: [inbox, tasks, applications]
  page_rest: show          # a section no page names goes to the tab "More"; hide leaves it out
```

`collect --json` carries the result as `pages`: every row in the same four
columns, **when** (a date, today as its time), **title**, **detail** and a
**link**. A column stays empty only when the item has nothing for it.

| Kind | when | detail | dimmed |
|---|---|---|---|
| `calendar` | start | "until HH:MM", the calendar, "info" | started already |
| `tracker` | `due`, else `changed_at` | PR, state, project (when the id does not name it and the view is not `board`), priority, note, the pull requests that close it, its task | |
| `command` | `due` | `raw_state` or `state` (every row is a finding: yellow, `blocked` red) | |
| `commits` | today's commits | sparkline and branch, busiest first | none today |
| `activity` | `changed_at` | project | an earlier day |
| `inbox` | `due`, else `changed_at` | kind, gate (`urgency: now` yellow) | |
| `tasks` | `due`, else `changed_at` | priority, project, `blocked_by` (blocked: yellow) | |
| any other | `due`, else `changed_at` | state, project | |

A page lists every row a section found, not only the briefing's first few
(`max:`); the dashboard pages through them. A source may set a row's colour
itself with `tone: bad | warn | dim | none` on the item (a usage figure is
information, not a finding).

A row may also carry a gauge, `meter: {value, max, unit, elapsed}`: `value` a
number from 0, `max` above 0 (without it the rows of a section are scaled against
each other, for costs or sizes), `unit` up to eight characters (`%`, `$`, `GB`)
and `elapsed` from 0 to 1, how much of the time window behind the value has
passed (a quota that resets). With a `max`, `warn` and `bad` say where those ranges begin
(in the value's unit); a section whose rows all have a `max` shows as gauges. The cockpit draws it as a bar with a mark at
`elapsed` and says in words when the value runs ahead of the time; the terminal
card ignores it. A gauge with a value it cannot read is dropped, a bad `max`,
`unit` or `elapsed` only loses that field.

`view: board` keeps the table and sets its rows under their `group`, one head
per group in the order the rows first name them (a `github-work` row's group is
its board, else its repository). `view: groups` lists short rows under each
group instead.

`view: log` draws a section (an `activity` section, whose rows carry the glyph
of their activity type as `glyph`) as a log under its hours, its contexts as
topic chips that filter it. `place: rail` (`main` is the default) sets a section
in a narrow column beside the page's main one, its rows as compact tiles. A page
with either takes the cockpit's log layout ([bridge-cockpit.md](bridge-cockpit.md),
"A page's log layout").

`view: agenda` on a calendar section draws it as a calendar: by day, as a week
grid (Monday to Sunday) or as a month, with figures on top. Every calendar row
carries its facts as `cal` (`start`, `end`, `day`, `minutes`, `all_day`,
`calendar`, `info`, `where`, `online`, `people`, `past`, `running`, and
`overlaps`: the titles of the events it collides with; information calendars
and all-day events collide with nothing), and the page section carries
`cal_figures`: events today, tomorrow and in the next seven days, today's busy
minutes, how many collide, the next event, the longest free block left today
between 08:00 and 20:00, and the information events of the week counted apart.
A `command` row whose first column is a date (`when:` or its `due`) carries it
as `due_at`, so the same page counts what is overdue or due this week.

For a drawn section (`view: tiles | mosaic`) a row may say more: `group` and
`icon` place and mark it, `tags: {label: value}` (up to six short strings) give
the filter chips (a label with two to sixteen values gets a row of them), and
`account: {id, status}` marks a row as the account `identity/accounts/<id>.yaml`.
On such a row the cockpit offers its status menu (active, paused, disabled,
written into the file by `scripts/bridge-resources.py set-status`), and a group
whose head row (`icon: account`) carries the same id opens all its rows as one
filterable list. A tile shows the row's `when` as a line of its own under the
title when it has one (a `commits` row: "16 today"), and its `url` as the open
link when the row has no web link of its own and the url is http(s).

A `command` row may also offer steps of its own: `actions: [{id, label}]` (up to
eight; `id` lowercase letters, digits, `_` and `-`, the label as the cockpit
shows it) next to its `id`. Its section then names how a step runs:
`actions_argv: [..., "{id}", "{action}"]`, a list like `argv` in which `{id}` and
`{action}` each stand as a whole argument (validation refuses anything else).
`briefing.py act <profile> <section> <row-id> <action>` asks the section again and
runs the step only when that row still offers it, then prints the command's JSON.
When that JSON carries `undo: "restore:..."`, the token goes back to the same
command unchecked by act (the row may be gone by then), so the command itself
must check it. A step whose effect only shows later (a machine rebooting) may carry
`recheck: [seconds, ...]`: the cockpit then reads that section again after each wait
(whole seconds from 15 to 1800, eight at most) and stops after the last, so the row
moves on without a standing poll. The cockpit shows the steps as a two-click menu on the row
and keeps every step in its history, with "take back" where an undo came back.
A page entry with `steps: buttons` sets every step out as a button of its own, on the row,
on a tile and in the detail: the first click arms it ("Switch off: sure?"), the second runs it,
and an armed button falls back after a few seconds. For a handful of steps that should be in
sight, such as the power switches of a machine; the default `menu` keeps a long list short.
Example: the rows of a job-application tracker (followed up, turned down, ...).

Each row also says where it leads. **url** is a web address, or a file of this
Bridge as a `file://` link when the item's `url` (or the field a page entry's
`link` names) holds a path inside this Bridge that exists (a task's
`STATUS.md`, a protocol). A path outside the Bridge never becomes a link; a web
address loses any user and password, and one whose query carries a key (`code=`,
`token=`, `sig=`, …) is left out, because "ask" hands the link to the agent. `commits` link to the repository's commit list when its
`origin` is a web host; an `activity` row whose context is a task or stream links
to its `STATUS.md`. **task** names the task a row belongs to (an activity row, a
proposed tab, a task), so a dashboard can jump to its tab or open one. **ask** is
true for a finding (red or yellow), a tracker row and an inbox row: worth handing
to the agent.

A page entry overrides that per section: `when` and `link` name an item field,
`detail` one field or a list, `empty` the text for nothing (default
"nothing"), and `alarm: true` makes every row a red finding, nothing more (for
an empty section that reads as good news, set `empty:` too, for example
`empty: "all green"`); `badge: false`
keeps a section out of the number on its tab; `hide_empty: true` leaves a section off its tab
while it has no rows (an empty section without it shows as one quiet line); `hide_ok: true`
draws a section only while one of its rows is bad or its source fails, and it still counts
toward its tab and its alarm (a cloud section the account tiles read, say);
`actionable: true|false` says whether the dashboard offers Get it done, Advise and Close
on every row of the section. Without it, a row is actionable when it is a finding (red or
yellow) or a tracker row; a row that already has an inbox item or a task keeps that path.
Every row also carries `id`, its source id, which keys the item the dashboard files for it.
A page with `under: <page id>` is a sub page of that page: no tab of its own; in the cockpit
its parent becomes a folder with a bar of its places under the tabs (the overview, then each
sub page in the order `view.pages` lists them) and a ▾ at its tab with the same places, and
`overview: true` on the sub page gives it a head card of one line per section, and no token or noise card unless
its own `cards:` names one (they stand on the folder's overview). It names another page of `view.pages`,
not itself, one level deep, and neither side has `group: work` or `group: day`; `validate`
says which rule an entry breaks. The cockpit's own Background jobs page is placed the same
way by an entry of `id` and `under` only: `{id: "@workers", under: ops}`.
`view.page_skip: [<section id>, ...]` keeps sections off every page, the rest page
included, while they still run: a section that only feeds a file another page reads. Each section
also says what it adds to its tab's badge (`weight`: rows not dimmed, for
`commits` today's commits; `bad`: red rows).

Without `view.pages`, the kind decides: `command` on Status, `calendar` on Dates,
`tracker` on Trackers, `commits` and `activity` on Today, any other kind on More.
The kinds the briefing page shows itself (`inbox`, `advise`, `tasks`) stay off the
tabs unless a page names them. Tab names come from the labels `page_status`,
`page_dates`, `page_trackers`, `page_today`, `page_more`; `validate` names a page
section the profile does not have. Two page ids are taken: `briefing` (the
briefing page itself) and `more` (the page for the rest).

**The Setup page.** `collect --setup` (the cockpit passes it, the terminal briefing never does)
appends three `command` sections of `scripts/bridge-setup.py`: `setup-checks` (what still keeps the
cockpit from working well, findings only), `setup-available` (the onboarding catalogue's features
that are off, with the steps `later` and `silence` through `actions_argv`) and `setup-on` (what is
on, dim). All three are `bucket: none`, so they never reach the briefing's buckets. `pages` gives
them a page of their own, id `setup` (label `page_setup`, `bridge-setup` when a profile page has
that id) in the group `settings`, never the rest page; a dashboard shows that group in its
settings (the cockpit: Settings, Setup) instead of a tab, and a profile cannot set the group:
`setup-available` with `actionable: true` and `badge: false`, `setup-on` with `actionable: false`
and `badge: false`. A profile may name any of the three in `view.pages` and place it on a page of
its own; a page of its own with the id `setup` that names one of them takes the ones it does not name. The three ids are
reserved: `validate` refuses a profile section that takes one. `act <profile> setup-available <id>
<step>` works whether or not the run collected the page. Model and safety: [`bridge-cockpit.md`](bridge-cockpit.md)
§ The Setup page.

A dashboard can load in two runs: first a run of its own with
`--skip tracker --skip command` (the kinds that wait on a service; a few
seconds), then a full run. That first run is not the terminal's quick mode
(`--skip tracker --skip calendar`): it keeps the calendar, because the headline
needs it. Sections run side by side, so the full run is no slower than one with
`--only`, and it is the only run where the headline and the advice see the inbox
and the calendar together. `collect` keeps no rows from an earlier run: a section
a run leaves out comes back `skipped` with no items, so a dashboard that wants to
show the earlier rows meanwhile keeps them itself. Such a section carries
`left_out: true`: it comes with the next full run. A section skipped without it
cannot run on this machine at all (a calendar with `provider: auto` and no
icalBuddy), keeps its `reason`, and shows in the view's status rows whatever its
kind, the calendar included, so a missing source is never just an empty section.
The cockpit (`scripts/lib/bridge_cockpit/collector.py`) does exactly that: after a click it
runs only the first part again and keeps every section it left out, the headline
included, from the earlier run, so a click never waits for a tracker.

A slow source can keep its answer: `cache_minutes: 5` on a section makes the
next runs answer from its last good result until five minutes have passed
(`.bridge/briefing-cache/<profile>/<section>.json`). A failure is never kept, a
section whose configuration changed asks again, and `collect --fresh` always
asks. The page section then carries `as_of`, the time its source last
answered, so a dashboard can say how old the rows are. Measured on one Bridge:
a full run of 26 s took 2.3 s with GitHub and the health probes cached. A
`github-board` row gets the date its issue or PR last changed from one GraphQL
call for all rows, since a board listing carries none.

**GitHub's budget is shared.** Every program on the account draws on the same
hourly budget (5000 GraphQL points, plus 30 searches a minute): the cockpit, the
briefing, board pollers, agents. Three rules keep a briefing from draining it:

- A burst (GitHub's secondary limit) is retried after a short wait, twice. A
  spent budget ("API rate limit already exceeded") is not: the first such answer
  writes `.bridge/briefing-cache/github-limit.json` with the reset that
  `gh api rate_limit` names (a call that costs nothing; without an answer a
  quarter of an hour, never more than 65 minutes), and until then no `gh` call
  of any section leaves this Bridge, a reload (`--fresh`) included. Sections
  that run side by side stop at their next call.
- A tracker section with `cache_minutes` that cannot answer (blocked, failed,
  timed out) shows its last kept answer of the last 12 hours instead of an
  error, marked `stale` with the reason and, when blocked, the time it asks
  again. Stale rows file nothing to the inbox and close nothing. A run that
  leaves trackers out (`--skip tracker`, the cockpit's quick pass) shows the
  same kept answer, marked as being refreshed, instead of nothing.
- Ask less often: GitHub sections rarely need `cache_minutes` below 10 or 15.
  `github-board` filters before the limit (`is:open`), which on large boards
  cuts a listing from hundreds of cards to the open ones.

`view.marks` puts a label in front of every row that names one of its words:

```yaml
view:
  marks:
    - {label: ACME, match: [acme, acme-portal], color: magenta}
    - {label: Beta, match: beta-corp}
```

A word matches anywhere in the row's title, id, project, repo, task, context,
area, labels or url (its link), whatever its case, never the name of its source; the
first mark that fits wins. The mark is in the JSON as `mark` on the briefing's
rows and the page rows alike. Of the text views, triage, brevity and report draw
it as `[LABEL]` in front of the title; sources and plan leave it out. Customers
and projects come and go, so they belong in the profile, never in code.

### Your settings, and where they live

Everything a person tunes lives in their own files (USER tier); the code reads
it and carries no names or customers of its own. A few display defaults stay
fixed in the cockpit, for example an hour before a tab counts as long-running.

| What | Where |
|---|---|
| Sections, sources, queries, `cache_minutes` per section | `workflow/briefings/<id>.yaml` `sections:` |
| Tabs and their columns (`when`, `detail`, `link`, `empty`, `alarm`, `badge`) | same profile, `view.pages`, `view.page_rest` |
| Marks in front of rows (customers, projects) | same profile, `view.marks` |
| Wording of the briefing (headline, tab names, "today") | same profile, `view.labels` |
| Cockpit on or off, port, profile, voice, poll interval, how old the full run may be, layout backup, launch target | `bridge-config.yaml` `cockpit:` |
| Language of the cockpit's own words (`de`, `en`) | `cockpit.language`, else `language.conversation`, else English |
| Name of the control workspace: the workspace whose session steers the others and takes the cockpit's questions through the relay | `bridge-config.yaml` `workplace.control.name` ([workplace](workplace.md)) |

The cockpit's own words (buttons, help) sit in one German and one English
table in `scripts/web/text.js`, the prompts it sends in
`scripts/lib/bridge_cockpit/text.py`; a profile's labels never mix with them.
`bridge-config.yaml.template` lists every `cockpit:` key with its default.

**Works with Claude Code, in cmux or tmux.** The pages are plain
data; the cockpit draws them in the browser, and its tab actions go through
the terminal driver of [`workplace.md`](workplace.md). Other agents (Codex,
Gemini CLI, Copilot) and other terminals (WezTerm, kitty) have not been tried;
that work is to be tracked as issues, one per combination.

## Change marks

The time limit (`timeout_sec`, default 30 s) covers a whole section, all of
its calls together, so a slow tracker costs at most that. A `github-board`
section asks up to four boards side by side, so it takes about as long as its
slowest boards, not all of them added up.
A `gh` call that fails on a GitHub rate limit is tried again after 5 and then
15 seconds, each stretched at random by up to half so calls running side by
side do not retry in the same second, as long as the wait still fits that
limit: such errors come in bursts when several sessions query at once, and
clear within seconds.

Each run is compared with the previous run of the same profile on the same
machine (`.bridge/briefings/<id>.last.json`, derived, not committed). Rows
carry `new` and `changed`, so a briefing can lead with what moved since
yesterday instead of repeating the whole list. A run in which a section
failed keeps that section's last good snapshot, so a lookup that failed
today does not make every row look new tomorrow.

## Inbox rules

`to_inbox` turns rows that need a person into [inbox](inbox.md) items:

```yaml
to_inbox:
  - when: {state: blocked}                         # every listed field must match
    urgency: now                                   # now | today (default) | later
  - when: {category: qa, assigned_to_me: true}     # a list value means "any of"
  - when: {untasked: true}                         # yours, and no task syncs it (link on)
```

A rule matches any field a row carries: `state`, `category`, `raw_state`,
`type`, `assigned_to_me`, `untasked` and the rest of what its provider writes.

The key is `briefing:<profile>:<section>:<item>`, so a repeat is one item,
and a dropped key stays quiet. When the row is gone, the item closes on the
next run **in which that section completed**; an errored section closes
nothing, because a failed lookup is no evidence that the row is gone (the
same rule the advice checks follow). For the same reason a row whose
`unknown` names a field a rule asks about keeps the item that rule filed.
Filing needs `--file`, which the briefing workflow passes.

## Profiles shared by an org

A profile with `scope: org` can ship in an org overlay, so a whole team gets
the same morning shape. `assignee: "@me"` resolves on each person's machine
to their own login, so one shared GitHub section gives every colleague their
own issues and pull requests across the org, and a `github-board` section
with `assigned_to_me: true` their own cards on the team's boards. A person
who wants something else sets `briefing.default` to their own profile; the
config wins over the shared file's `default: true`.

## Writing your own source

Anything without a provider is a `command` section: a program that prints a
JSON list (or JSON lines) of items in the normalized schema, run from the
Bridge root. Beyond that schema, the dashboard pages read three optional item
fields (§ Dashboard pages): `due`, the date in the `when` column (for a
`command` row the only one); `tone`, the row's colour (`bad`, `warn`, `dim`, or
`none` for information that is no finding); and `task`, the slug of the task the
row belongs to. A source that turns out to be useful to others is a new module
under `scripts/lib/briefing_providers/` with recorded answers and tests.

## Example

[`examples/portfolio/workflow/briefings/`](../examples/portfolio/workflow/briefings/)
has a morning profile (inbox, advice, a client board whose blocked cards
become inbox items, the person's own GitHub work, calendar) and a second
profile for one client's weekly call.
