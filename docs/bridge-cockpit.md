---
summary: "The Bridge cockpit, a local web page that watches and steers the whole Bridge: switch it on in bridge-config.yaml (cockpit:), open it with /cockpit or scripts/bridge-cockpit.py, decide rows, steer agent tabs and ask Claude or Codex from the browser. Covers the three columns, the news ticker, the status pages, the task check, the keyboard, the safety model, the relay mod cockpit-relay, the files under .bridge/cockpit/, how to build the briefing profile it shows, and what to do when something is off."
type: guide
last_updated: 2026-10-18
related:
  - bridge-cockpit-dev.md
  - briefings.md
  - workplace.md
  - inbox.md
  - ../bridge-config.yaml.template
  - ../workflow/briefings/_template.yaml
  - ../scripts/bridge-cockpit.py
  - ../mods/cockpit-relay/hooks/relay.ts
---

# The Bridge cockpit

> **Early version (alpha).** The cockpit works and is used daily, but it is young: pages, buttons
> and settings still change, and it is being extended. Expect rough edges, and please report what
> breaks or confuses you as an issue.

Changing the code: [`bridge-cockpit-dev.md`](bridge-cockpit-dev.md).
AI provider routing and worker usage: [`ai-services.md`](ai-services.md).

The cockpit watches and steers the whole Bridge from one browser tab. The
briefing is one part of it: what waits for you, what you can hand off, your
tasks. Around it stand your work (inbox and tasks on one page, ordered by Jev
on a click), the agent tabs and sessions, the workers, the machines and the
tokens of the week. It runs on your own computer, answers only on
`127.0.0.1`, and acts only through the Bridge scripts (`inbox.py`, `task.py`,
`workplace.py` and its terminal driver). Nothing on it costs tokens until you
press a button that asks Claude or opens an agent tab. The relay that hands the
cockpit's questions to your control session is the mod `cockpit-relay`.

Two parts work together:

- the **server**, `scripts/bridge-cockpit.py`: collects the briefing, polls the
  agent tabs, serves the page and runs the verbs you click;
- the **mod** `cockpit-relay` in your Claude Code session (`mods/cockpit-relay`,
  optional): it passes your questions from the page into the session that
  steers the others (the relay, section 5). `/cockpit` is a skill of its own
  (`skills/cockpit`) and needs no mod.

**Status.** Works with Claude Code on macOS, with cmux or tmux as the
terminal (`skills/cmux`, `skills/tmux`). The page steers agent tabs through the
terminal driver of [`workplace.md`](workplace.md) and offers for a tab only
what that driver serves (`caps`). Without a terminal it can steer, the page
still works with the relay and everything else, except the tab actions that
need the driver: keys (Yes, No), reading a tab's screen and jumping to a tab.
The relay then picks the only session with a fresh heartbeat (section 5).

## 1. Switch it on

You need an onboarded Bridge (`bridge-config.yaml` in the repo root, written by
`/bridge-onboard`) and `python3` with PyYAML (`python3 -c 'import yaml'` prints
nothing).

In `bridge-config.yaml`, add a top-level `cockpit:` block:

```yaml
cockpit:
  enabled: true
```

Every other key is optional; `bridge-config.yaml.template` lists them with
their defaults:

| Key | Default | What it does |
|---|---|---|
| `enabled` | `false` | `bridge-cockpit.py` refuses to start until this is `true` |
| `port` | `8797` | the page answers on `http://127.0.0.1:<port>/` |
| `open_in` | `auto` | `auto`: a cmux browser tab inside cmux, else your default browser; `cmux`, `system`, or `none` (print the address only) |
| `relay` | `false` | `true`: the control session takes questions from the page as prompts; needs the `cockpit-relay` mod (below), so it stays off unless asked for |
| `profile` | `briefing.default` | which briefing profile the page shows |
| `tabs_seconds` | `10` | how often the agent tabs are re-read while a page is shown; below 5 counts as 5. A page left in a background browser tab stops the full pass and the ticker, and the tabs are re-read only once a minute until it is shown again |
| `language` | `language.conversation`, else `en` | `de` or `en` for the page's own words |
| `full_minutes` | `10` | while a page is open, the full briefing runs again when the last one is older |
| `voice` | `false` | the browser also speaks a tab that starts waiting for you |
| `launch.target` | `area` | where Let AI do it opens a tab: `area`, `tab`, `workspace` or `auto` ([`workplace.md`](workplace.md)) |
| `triage_daily` | `false` | `true`: the triage sorts every task and inbox item once a day by itself (a small model call, a few cents); otherwise only on "sort again" |
| `chat_layout` | `classic` | `workspaces`: the Chat tab as cmux shows it, see [The chat as cmux](#the-chat-as-cmux) |
| `chat_keep_hours` | `24` | a quick chat nobody touched for this many hours leaves the list into the archive (below); `0` = only the limit of 30 |
| `snapshot_minutes` | `60` | while the server runs, save the cmux layout this often, only when it changed; `0` = only on "Save layout now" |
| `person_name` | none | how Claude and Jev name you; without it they say "the user" |
| `ticker` | off | the news ticker on the start page: Bridge status and AI news feeds (section 3, "The news ticker") |

`language`, `full_minutes`, `voice`, `launch.target` and `snapshot_minutes`
used to be set under `briefing.claude_code_ui`, the block of the retired
briefing card. A config that still has them there keeps working: a key the
`cockpit:` block leaves out is read from `briefing.claude_code_ui`. Move them
when convenient.

The page's default target is `area` (the workspace of the item's area), while
`workplace.py launch` on its own defaults to `tab` (the calling tab's
workspace).

What the page shows comes from your briefing profile; without one of your own
the built-in profile runs. Section 8 shows how to build yours.

### The relay mod (optional)

The page works without any mod. To hand questions to your control session
("To the control session", section 5), install the mod `cockpit-relay` once,
from the Bridge folder, for this Bridge only:

```bash
claude plugin marketplace add ./mods --scope local
claude plugin install cockpit-relay@open-bridge-mods --scope local
```

`--scope local` keeps both to this Bridge (they land in
`.claude/settings.local.json`, which git ignores). Start Claude Code in the
repo root, not a subfolder. Claude Code reads the mod straight from
`mods/cockpit-relay` (`claude plugin list` shows "Read from"); after a pull or
an edit, start a new session or run `/reload-plugins`. More in
[`mods/README.md`](../mods/README.md) and
[`mods/cockpit-relay/README.md`](../mods/cockpit-relay/README.md).

## 2. Open it

In a Claude Code session in the Bridge root, type `/cockpit`. The skill
runs `python3 scripts/bridge-cockpit.py open --json`: the server starts (or the
running one is reused) and the page opens where `open_in` says. The note in
the conversation names only where it opened and `http://127.0.0.1:<port>/`,
never a link with a key or a login code.

From any terminal in the Bridge root:

```bash
python3 scripts/bridge-cockpit.py open      # start if needed, then open the page
python3 scripts/bridge-cockpit.py url       # print a login link (works once, for a minute)
python3 scripts/bridge-cockpit.py status    # running? port, open pages, relay
python3 scripts/bridge-cockpit.py stop      # stop the server
python3 scripts/bridge-cockpit.py autostart on|off|status   # macOS: run from login on
python3 scripts/bridge-cockpit.py new-token # a new key on the next start
```

**Open it by its address.** The key stays the same across restarts (it lives
in `.bridge/cockpit/token`, mode 0600) and no command prints it. `url` (and
`start`) print a login link instead: it carries a code made from the key that
works once and only for a minute. Open it in a browser; it sets a cookie for
three days, and until then the bare address `http://127.0.0.1:<port>/` opens
the page in that browser, so a bookmark is enough. After three days the page
asks for a fresh link (`url`, or `/cockpit`). `new-token` makes a new key on
the next start, which also ends every cookie, and every browser goes through
`url` once more.

**Always there.** Without autostart the server runs until you stop it or the
computer restarts. `autostart on` (macOS) installs a LaunchAgent
(`~/Library/LaunchAgents/ai.open-bridge.cockpit.<hash>.plist`) that starts
`serve` at login and again after a crash, never after `stop`; it keeps the
PATH of the shell that switched it on, since the cockpit calls cmux, gh, git
and claude. `autostart off` removes it. It is off unless you switch it on.

**Try it without a Bridge.** A live demo with invented data runs on the
website: https://bks-lab.github.io/open-bridge/cockpit-demo/. Nothing there
reaches a server and nothing is saved. Add `?theme=light` or `?theme=dark` to
the address (here or on your own cockpit) to force the mode for that one load
without changing your stored choice.

## 3. What you see

The header carries the profile's title, when the briefing was
collected, a loading indicator, reload, the theme switch (auto, light, dark),
help, and a dot for the relay. Under it sits the page bar. In front stand the
tabs of every day: "Start" (a new visit opens on it, a reload stays where it
was), "Today" (the briefing), "Chat", then the profile's pages with the
default `group: main` (Work and Operations in a typical profile). Behind them
come Sessions, Background jobs, Other Bridges (A2A), Tidy up, Jev and every profile page
with `group: more`. While the bar is wide enough every tab stands in it; when
they would overflow, that second group folds, from the last tab forward,
behind a last tab, "More", which carries the name of the page open behind it
and a dot when one of them has something. Alt 1 to Alt 9 follow the same
order. A page with `group: day` has no tab: its sections stand under "What
happened today" in the middle of the Today page.

A page with `group: work` has no tab either: it folds into the Today tab, which
then carries that page's title (Work, say) and a switch over its left column
with three views. **Due** is the four blocks below, and the tab opens on it.
**By source** is the work page itself, its sections as labels. **By Jev** is the
Jev picture (the matrix and the plan) fed by the work page's order, and it
stands only where that page has `jev:` and Jev is on. With such a page the Jev
tab goes too: it is the By Jev view now, and an old link to it or to the work
page opens the matching view. The day moves to Start as well: dates, status,
what is clear or needs tidying and the workplace stand there as cards in a shelf
"The day", above the project chips since those do not filter it, and the pages of
`group: day` close the start page as shelves of their own. The middle of Due
keeps only the headline and a button to Start.

Only one number in the bar carries colour: Today's count of what waits for
you, the same count as the start page's station "waits for you" and the
headline in the middle (the approvals stand in its tooltip and in their own
block). A finding is red wherever it is; every other count is grey. A page
badge that adds up several sections names them in its tooltip. A finding on a
status page also shows as a banner on the Today tab.

The buttons speak four verbs everywhere, also in the Telegram inbox watcher:
**Let AI do it** (an agent tab does it), **Advise** (an agent tab reads and
reports, then waits), **Ask** (a short read-only answer in the chat) and
**Close** (done, not doing, or more). "To tab", "Message" and "View" only stand
where a tab already runs.

### The start page

"Start" is the way in, styled like the project website (DESIGN.md: a
Playfair heading over an eyebrow, cards on hairlines). It greets by
`cockpit.person_name`, repeats the briefing's headline, and carries a field
that asks the chat directly. Findings of a status page and a control session
that is not listening stand under it as signals; each opens its place.

**The news ticker (off by default).** With `cockpit.ticker.enabled` the start
page shows two kinds of items, each in its own place:

- **What happens in the Bridge** stands still as a list in the live section of
  the side card "Today", above the live events: what runs (agent tabs at work, busy
  sessions, the task check, the triage), what waits for you (a tab that asks,
  an answer from a start, rows waiting on you), what is slow (a collect pass
  near its time limit, a source that took too long, a tab running long), what
  fails (an alarm, a failed source or background job, a judge without its key),
  quotas near or over their pace, token outliers, peers and machines that do
  not answer, and the last warning notes. The page builds these from what it
  already holds, so they cost nothing and change the moment the state does. A
  click opens the place it names: the page, the tab, the row or the drawer.
  Red comes before orange, orange before blue. Six rows show; the rest opens
  in place behind "N more". While status rows stand there and no live event
  came yet, the live feed says so in one short line instead of its longer
  "quiet" text.
- **News from feeds** run in one line in the free space right of the
  greeting, level with it: a small head ("News", how many are new, Pause,
  Editor, Refresh) on the eyebrow's line, the band itself on the prompt's,
  with no box, a hairline under it like the greeting's and its ends fading
  out. On a stage narrower than about 1100 pixels (the `home` container, not
  the window) the band drops below the greeting. It carries the newest items
  of the RSS or Atom feeds in `ticker.feeds`, newest first, each with its
  source in small capitals after a coloured dot. The colours are the
  `DESIGN.md` tokens secondary, accent and on-surface, never a state colour;
  they stay three different colours after the fallback chain of
  `design.py`, also with a `DESIGN.md` that names only a few keys. The configured feeds take them in
  turn, so every three feeds show three colours and a feed keeps its colour
  across loads while the list stays the same. The colour groups; the source
  name in the label is what tells feeds apart. A click opens the
  article in a new browser tab; an article opened once steps back to muted
  text in that browser. The defaults are six English AI news feeds.

**The selection without a model** (`ticker.smart`) runs on every read of the
feeds and on every change of its settings, costs nothing and sends nothing
anywhere:

- one story told by several feeds becomes one item (the same address, the same
  title, or with `cluster` a title of another feed sharing most of its words);
  it shows `+2` for two more feeds and names them on hover. A feed never joins
  two of its own items;
- items whose title holds a muted term (`mute`) never show; a term of letters
  only matches whole words, so `AI` leaves "said" alone;
- dated items older than `max_age_hours` leave the band, undated ones stay;
- when more items remain than `max_items`, every feed takes its turn (each
  one's newest, then each one's second newest), so a feed that writes every
  hour cannot push out one that writes every week;
- with `mark_new`, news that came out after your last visit carries a small
  "new" mark and the head counts them. The visit is kept in the browser, and
  a reload is no new visit.

The classic view shows the news band under the greeting and the status list
under the band.

The band moves slowly and stops while the pointer or the keyboard focus is
on it, and with its Pause button (the way for touch and keyboard, kept per
browser); Tab walks through its items. With reduced motion in the system it
stands still and scrolls by hand. Text only: no images, no favicons.

The server reads the feeds, never the page, and only while a page is open:
when the last read is older than `refresh_minutes`, within a few seconds of
opening a page after a long gap, and on the refresh button. A feed that fails
keeps its earlier items and shows its error on the settings page.

**Editor** is a button on the band. Only that click asks Claude Haiku (one
`claude -p` with no tools, a few cents at most) to pick up to `max_picks`
items that match `editor.interests` and, with `shorten`, to cut each title to
one line. The band then shows the picks in that order, plus whatever arrived
after the edit, marked new; the rest stays hidden until the next edit. Haiku
never runs at start, on a timer or on a refresh. The prompt names the muted
terms and how many feeds tell an item. Changing the interests, the number of
picks, `shorten` or the muted terms drops the old edit, and the band shows
every item again until you press the button.

**Your interests** can be proposed on the settings page from the titles of
your open tasks: "Keywords from my tasks" counts their words without a model
(a word in two titles first, a name or product before a plain word), and
"Written by Haiku" asks Haiku for one line of topics, again only on that
click. Either is a proposal shown below the field; "Take as my interests"
saves it, nothing else does.

| Key under `ticker` | Default | What it does |
|---|---|---|
| `enabled` | `false` | the band on the start page; off means no feed is read |
| `max_items` | `30` | feed items shown at most (5 to 100) |
| `per_feed` | `8` | newest items taken from each feed (1 to 30) |
| `refresh_minutes` | `30` | read the feeds again when older, only while a page is open (5 to 1440) |
| `speed` | `normal` | `slow`, `normal` or `fast` |
| `feeds` | six AI news feeds | up to 20 entries of `id`, `name`, `url` (http or https) and `enabled`; a list you set replaces the defaults as a whole |
| `status.enabled` | `true` | show the Bridge's own items in the live section |
| `status.kinds` | all | which of `running`, `waiting`, `slow`, `failing`, `quota`, `offline`, `notes`; none chosen shows no status list |
| `editor.enabled` | `true` | show the Editor button (needs `claude` on the server's path) |
| `editor.interests` | empty | free text, what you want to see (up to 500 characters) |
| `editor.max_picks` | `12` | how many items the editor keeps (1 to 40) |
| `editor.shorten` | `true` | one-line titles from the editor |
| `smart.cluster` | `true` | join one story from several feeds into one item |
| `smart.max_age_hours` | `72` | dated items older than this leave the band (0 keeps all; up to 720) |
| `smart.mark_new` | `true` | mark news that came out after the viewer's last visit |
| `smart.mute` | empty | up to 30 terms (1 to 40 characters) whose items never show |

A value in `bridge-config.yaml` that is out of range keeps its default; a feed
entry with a bad id or address is skipped, and with no valid feed left the
defaults apply. The Settings page (below, under "The model an agent starts
with") changes every key on top of the config.

"Slow" here means what the cockpit can measure: the time a collect pass took,
sources that ran out of time, long-running tabs and agent turns. The cockpit
has no CPU, memory or load source; disk use comes only through `checkup` as a
finding. A real CPU or load signal needs a probe under `workflow/checks/`.

Under the hero stands the overview, a row of tiles where every tile is a
way in. Each gauge in percent that a page carries (a quota, a limit) gets a
wide tile: the value, a bar with a mark where the time window stands, and in
words its share per day against the even share of the window (the budget)
and where it ends at the reset at this pace. The share per day needs the
window's length, which a source names as `meter.window_h`; a window under a
day shows only the projection. A click opens the row's detail. Count tiles
follow: what waits on you, the agent tabs that wait, and every page with a
count, its largest sections underneath (a page with findings names where
they are). A click opens the page.

What stands on the start page is your choice. "Customise" beside the
bridge opens a drawer that leaves the page in view, so every change shows at
once: the view (bridge or tiles, two pictures to pick from), the stations as
one list in their order (a switch each, a grip to drag, arrows for the
keyboard; the bridge has room for 13, Today takes the 14th place), the
sections below, what a click on the core does, and the small details. Every
row says in one line what it does. "All settings" leads to the same editors
on the settings page. The choice lives on the server (`state.json`, key
`home_tiles`, action `home_tiles`), so every browser shows the same. Until
one is made the page keeps lean: the weekly quota, what waits on you, the
page with the tasks, and every shelf.

More it can show, each one switched in "Customise":

- **Next up**: one step, large. A tab that asks you, else the first row
  waiting on you, else the first P0 or P1 task.
- **Pinned**: rows you starred. The star sits on every card and every
  Briefing row; a tab card stars its task. Kept on the server (`pins`).
- **Next date**: a countdown to the next calendar row that has not begun
  (rows carry their start as `at`). A click opens the event: its calendar,
  place and people, "Join" for a meeting link, its steps as buttons ("Prepare",
  or what the calendar section declares, [briefings.md](briefings.md) § Calendar
  steps) and the dates that follow, each a click into its own detail.
- **Closed this week**: tasks under `work/done/` whose `closed:` falls since
  Monday; a click lists them.
- **Options**: a quota's use today with bars of its last days against the
  budget line; a screen preview in tab cards that name no last line (read
  once through the terminal driver); numbers against yesterday; the count of
  waiting tabs in the browser tab's title; a project chip that also filters
  the numbers.
- **Order**: drag a station in the list, or move it one place up or down.

**The bridge.** Unless the tiles view is chosen, the start page draws the
picture of the explainer films: the terminal line (it asks the chat), the
core with its rings, the chosen tiles as stations on curved links, the card
"Today" with the next step. A station's heart line beats by its state (red
fast, green calm). A click on a station opens its inspector beside the
bridge; a row opens whole in the wide drawer. A click on the core runs the
modes chosen under "On a click on Bridge", any combination of: reload (collect again,
the state of the bridge itself), assessment (the AI, in the core's
panel), focus 25 min (all but the next step steps back) and speak (the
browser's speech recognition; which service hears it depends on the
browser).

**The assessment.** It is read first from the page's own data and
laid out as a board, at once and without cost: first (what `focusPick`
chooses), asks you, your yes, at work, answers in, no word, next date, the
tightest quota (one running over its pace before one that is merely high),
findings and can wait. Each field leads where it names. Then Claude gets
exactly that board as lines (`situationText` in `logic.js`) and answers in
three fixed lines, first, then, can wait, which the panel shows as three
rows; an answer of another shape shows as it came. Questions after it go on
in the same conversation.

**The inner room.** Held down a moment, or clicked with the option key, the
core opens the inner room: the knowledge graph of the Bridge in 3D
(`inner.js`, served by `/api/graph` from `graph.py`). Nodes are the config
entries (the root `*.yaml`, `identity/`, `infra/`, `workflow/`), the open
tasks and streams, and every file one of them names that exists. Edges are
repo-relative paths (the rule of `scripts/check-edges.py`), paths relative to
a task's folder in its front matter, and `*_ref`, `*_refs`, `related_*` or
`host:` values that name another entry by its id, the family the key names
first. Templates and examples stay out. The regions (core, identity, infra,
workflow, work, docs, files) grow around the middle, signals run along the
links, and a click flies to a node: its links light, the panel lists what it
points to and what names it, each a hop further, and its text (read only,
only for a node of the graph, `/api/graph/node`). "Journey" (space) wanders
from node to node on its own; `/` searches; the region chips hide a region;
Esc surfaces. The graph is built once a minute at most.

**With AI.** Every start handed to a tab ("Let AI do it", "Advise",
"Collect context") is kept in `launches.json` (`returns.py`), a week long.
Its stage is read from what the Bridge has, nothing is asked of the tab:
started, working, asks you (the tab waits), answer (a filed inbox item, or a
note on its inbox item written after the start), done (its inbox item
closed, or its task moved to `work/done/`), and "no word" when the tab is
gone without an answer. The page follows tab states live and shows the stage
wherever the item appears: a chip on its card, its Briefing row and its row on
every page (Work included), and the whole return panel (steps, the tab's last
line or the answer, the ways on) at the top of its drawer and its detail. A
note comes when an answer comes in.

"With AI" also writes to the item itself, so its own log carries it
for every other reader (the briefing, other sessions, a later look back): a
task gets a dated line in its notes (`task.py note`), an inbox item an event
(`inbox.py note`). One line when the start ran ("With AI: agent
started from the cockpit (do it)"), one when a task's tab filed its answer,
and one when the tab ended without a word. What the agent wrote itself (a
note on, or the close of, its inbox item) and a task's close are not written
again. `/api/inbox` now also
carries the text of a note.

Today and yesterday come from the day book, `days.json` in the state
directory (`daybook.py`): each reading of a quota adds its rise since the one
before, a fall counts as a reset from zero, and each count keeps its last
value of the day. Two weeks are kept. It starts with the first reading, so
the bars and the trend fill in over the following days.

Below sit project chips, made from the workspaces of the agent tabs and the
projects of the rows (area, else the mark), most frequent first. A chip
filters every shelf, and the choice is kept in the browser. The shelves:

- **Continue**: the agent tabs as cards, the ones that need you first. The
  band names the project and shows the last lines of the screen. One click
  brings the tab to the front in the terminal, where the driver can focus;
  otherwise it opens large in the cockpit.
- **Waiting on you**: the first six rows of the Briefing's list, with their
  actions.
- **Tasks**: the task rows of the work backlog. A task whose agent tab is
  open leads straight into that tab; any other offers its actions. A click
  on the title opens the detail beside the page.
- **Quick access**: every other page of the bar, with its badge.

### Today (the briefing)

The status list in the middle has three tones. A source that failed is red
and names its reason; a probe (`report_ok: true`) with rows is orange; any
other count is blue and no alarm. A zero, and a source that only comes with
the full pass, fold under "without findings". Rows, worker schedules and the
detail facts show kinds, gates, states and schedules in words, never the
machine value (`finding`, `your-yes`, `every 300s`). The agent tab column stands
only beside the Today tab and the Chat, where work goes to the AI and comes
back. Every other page folds it into the header's Tabs button and gets the full
width. "Hide" in the column's head folds it there on the Today tab and the Chat
too, and the list of the day takes half of the room it left; "Pin beside" in the
Tabs drawer brings it back. The choice is kept in this browser.

On a wide screen the Today tab has three columns:

- **left, your day**: agent tabs that wait for you first, then the four
  blocks of the briefing: waiting for you, to hand off, backlog, later. Each
  row has its number, a box to select it (only rows you can start), why it is
  there, its mark, priority, urgency, due date, the state of its tab, and its
  main button. A selection gets a bar: Let AI do it, Advise, each in its own
  workspace. "Approve all N" under "AI can take over" asks once, with the count the
  server found, before it approves anything. Rows you hid sit at the bottom
  with "show again".
- **center, the detail** of the row you clicked: its link, its facts, every
  action the row allows (later with a date, hide, drop, urgency, priority, a
  note, a start as a tab, in its area or in its own workspace, team roles,
  assigning a running tab, and for a task its check and Close, see below), the inbox entry with the exact command a yes
  would run (shown before any approve button), the task with its STATUS
  sections and log rows, and the tab with Yes, No, Go on, Close, a message
  and "Go to tab". Asking Claude opens its own window (section 5).
- **right, the agent tabs** as cards, grouped by workspace: needs you,
  waiting, working, terminal. Each card shows its state as a dot and a word,
  how long it has been so, its name and its one next step: Yes and No for a
  question, Go on when it waits, Close for a filed result, else Go to tab.
  "more" opens the card to its last line and every button. The control
  session's tab sits on top and never counts as waiting. "Save layout now"
  and "List" back up the cmux layout.

Narrower, the tabs move into a drawer ("Tabs (n waiting)"); on a phone width
one column with Day, Detail and Tabs to switch between.

A page tab (Status, Dates, Trackers, your own) replaces the left and center
columns with its sections (which section lands on which tab: section 8): when, title, detail, a link,
"ask" for findings, and "start agent" (or "go to tab" when one runs) for a task.
Clicking a task's title opens its full detail beside the page, with every
action of the center column as buttons (the keyboard shortcuts work on the
Today tab only); the page stays where it was, and Escape or "Close details"
goes back to it.

**With AI on the Sessions tab.** The Sessions tab leads with what the AI was
handed, in four groups: **Done, please check** (a start whose item closed or
whose task moved to `work/done/`, or that left an answer, plus every waiting tab
whose own item or task is settled without a start of the cockpit naming it),
**Needs you**, **Working** and **No word**. A settled tab says why ("Done: its
item is closed. The tab can go.") and offers **Close tab** as its one next step,
the same on its session card, in the agent tab column and on its return card;
the server lets a waiting tab close when its result is filed or its item or task
is settled, and refuses it otherwise. The Sessions tab badge reads "AI n" while
something done or a question waits there, else the session count, grey either
way. Each session card now carries its tab's last line and its next step instead
of only "Go to tab". The workplace keeps a tab named after its item once the
item is closed (and a tab named after a task once the task moved to
`work/done/`, two month folders back), which is what lets the cockpit see that
the tab is done.

**A cockpit on a copy says so.** When the cockpit runs on a linked git worktree
(its `.git` is a file) the header carries "Test copy, nothing here stays": what
you start or close there lands in the copy and goes with it. With a `--state-dir`
of its own on the live Bridge it reads "Own state, starts stay here", since the
starts made there never reach the real cockpit's return channel. The tooltip
names the path.

**Sessions.** The Sessions tab shows every Claude Code session running on this
machine as a card, this Bridge first, then other projects: working, ready,
needs you or waiting (the tab's state wins), since when, its cmux tab and
workspace, whether it is on the relay, and its subagents: how many are active
right now with type, description and how long, how many finished in the last
hour, and a running workflow with its agent count. A click on the title or
"Go to tab" jumps there. The tab badge counts the active subagents. A control
tab that is not on the relay says so, which is the usual reason for "Claude
unreachable". Sources, read only: `~/.claude/sessions/<pid>.json` (one file per
running session), the session's `subagents/` and `workflows/` folders under
`~/.claude/projects/`, and the `CMUX_SURFACE_ID` of the process, read once with
`ps` and matched to the tab list; the rest of the environment is dropped. A
subagent counts as active while its transcript grew in the last two minutes.

**Agent tabs.** Let AI do it and Advise open an agent tab per item through
`workplace.py launch` and the terminal driver in the `workplace:` block of
`bridge-config.yaml` ([`workplace.md`](workplace.md)), for cmux for example:

```yaml
workplace:
  driver: {command: ["python3", "${root}/skills/cmux/scripts/cmux_driver.py"]}
  control: {name: Control}
```

`workplace.control.name` names the workspace whose session steers the others
(section 5). A start holds its items until the new tab shows up, so a double
click never opens two tabs, and `workplace.py` itself skips an item whose agent
already runs; the row then offers "Go to tab". A tab in state `shell` (the
command never started, or the agent ended) blocks nothing: its row offers
Restart beside "Go to tab".

**Checking and closing tasks.** "⟳ Check tasks" (on the Check tab, in the
header of Your tasks, and on every page that lists tasks) runs
`task.py review` in the background: a small model reads every task in doing or
review (steps, log, commits, linked issues resolved in one GitHub call) and
recommends close, continue, waiting, stale or unclear; only the unclear ones go
to a stronger model, unchanged tasks come from the cache
(`.bridge/task-review.json`). The rest of the page stays usable meanwhile, and
the finished check arrives as a note with its cost. Rows then carry a verdict
chip (close?, stale?, waiting, unclear?). A task's detail shows the
recommendation with its reason, confidence, model and evidence, with Close …,
Keep open (until the task changes), Check again and, for unclear or guessed
answers, Check closer with the stronger model. The Check tab is the overview of
the last run: a filter per verdict and "changed", sort by verdict, priority or
quiet, and a selection for Close selected, Keep open, Check closer and Start
agent. Close … asks why (done, will not be done, superseded or part of another
task, done elsewhere; several at once also "as the check says", stale ones as
declined), with a note for the log prefilled from the check's evidence, and
names an agent tab still working on it and inbox entries that point at it.
`task.py close` then moves the task to `work/done/`, regenerates the board and
writes a row to `work/log.md`. Close appears for a finite task only, never for
a stream.

What the check reads costs nothing: per task in `work/tasks/` in `doing` or
`review` (`--backlog` adds the backlog) the frontmatter (status, priority,
`blocked_by`, dates, headline), the first open steps, the latest log rows and
notes, the date of the last commit touching the task's folder, its open inbox
items, and the state of every GitHub issue or PR it names (`sync.github`, plus
`owner/repo#N` in `blocked_by`, headline, title and steps). All references of
all tasks are resolved in one `gh api graphql` call; when gh fails they count
as unknown and the check goes on.

Two signals come first, before any model. `own_refs_closed`: every issue and
PR in `sync.github` is closed as completed or merged. That means close, whatever
the model answered, so a weak answer cannot hide a finished task.
`blocker_resolved`: everything `blocked_by` names is closed or merged (a bare
`#N` means the task's own repository, a PR closed without merge counts as not
done). That is a hint for the model and a line on the row, never a close by
itself.

Then a model judges, tiered to stay cheap:

| Pass | Model | Who goes |
|---|---|---|
| 1 | `models.mechanical` (else `models.routine`, else `claude-haiku-5-5`) | every task whose evidence changed, all in one call |
| 2 | `models.directed` (else `models.analysis`, else `claude-sonnet-5-5`) | only the answers that were `unclear`, again in one call |

The aliases `haiku`, `sonnet` and `opus` are mapped to full model ids, and
[`ai-services.md`](ai-services.md) can route the check to another provider. The
verdict is `close`, `continue`, `waiting` (blocked on someone or something
still pending), `stale` (no activity for `work.review.stale_days`, default 21,
and no blocker) or `unclear`, with one sentence of reason in your language and
a confidence. The whole check stays inside 190 s (the second pass gets what is
left) and the page waits 240 s. When the models that answered are not the ones
asked for, the note says so. A stale task closes as declined, since it was
dropped, not finished.

Verdicts are cached in `.bridge/task-review.json` (derived, never committed)
by a hash of the evidence together with the language, the two model ids,
`stale_days` and a prompt version. A task whose evidence did not change keeps
its verdict for `work.review.max_age_days` (default 7) and reaches no model.
Keep open runs `task.py review --keep <slug>`, Check closer
`task.py review --escalate <slugs>` (one call of the directed model past the
cache; the button names its estimated cost, measured by the last run). The
command is a template: any agent that reads the prompt on stdin and prints the
JSON array will do.

```yaml
work:
  review:
    command: "claude -p --model {model} --output-format json --no-session-persistence --setting-sources '' --strict-mcp-config --tools ''"
    max_age_days: 7
    stale_days: 21
```

The overview of the last check (on the page that holds the task check) reads
the run `task.py review` keeps in that file, so opening it costs nothing; only
its buttons call a model. It shows a bar of the verdict counts, then total,
cost, the models that answered, duration and age; a filter chip per verdict
plus "changed" (tasks whose verdict differs from the check before); and per
task its priority, area, title, verdict, confidence, days since the last
activity, the evidence as chips (references with state and date, blocker
resolved, open steps, inbox items) and the reason.

**A tab, large.** "View" on an agent tab's card (or a click on its name)
opens that tab in the middle like the Claude Code CLI: its terminal, read every
1.5 s through the terminal driver (`workplace.py screen`, read only, the last
400 lines), what you typed
marked, the end kept in view unless you scrolled up, and below it Yes, No, Go
on as the tab's state allows and a box that sends a message to it (Enter
sends, Shift+Enter a new line). Escape or a click outside closes it.

**Overview pages and tokens.** A profile page with `overview: true` opens
with a board of tiles: one per section, with its count, its loudest row and a
colour for the worst tone (a quota gauge shows its fullest value, a plain gauge
its counts), plus one for the background jobs of the Background jobs tab and one for the tokens
of the week. A click on a section tile scrolls to that section, the workers
tile opens the Background jobs tab. Below the sections the page shows the tokens of the
last seven days: one bar per day, split into sessions, subagents and programs
(`claude -p`, the workers), and a click on a day lists its models and
projects. The server counts them from the Claude Code transcripts of this
machine (`~/.claude/projects`, `scripts/lib/bridge_cockpit/usage.py`, read on from
where the last count stopped) when the page opens: written tokens as measured,
cache reads and writes beside them, no price. A source that wrote at least
three times its usual day (and 50,000 tokens) is named in orange. A machine
tile whose name runs workers says how many and leads to the Background jobs tab
filtered to it.

**Noise in the inbox.** Below the tokens an overview page shows the inbox
sources a person had to drop from in the last 30 days, most drops first: how
many of how many, the share and the reasons. Under it stand the mute rules in
force, each with Lift. Read from `inbox.py stats` and `inbox.py mute list`
when the page opens and with each new briefing, never on a timer.

**A work page ordered by Jev.** A profile page with `jev:` (its task and inbox
sections together, say) shows a strip over its sections when Jev is on
(`integrations.typesafe`): By area keeps the sections, By Jev puts every row in
one list in Jev's order, each with its rank (its title holds Jev's urgency,
impact and effort, 0 to 3, and whether only you can do it) and its label (the
section), then the rows Jev did not see. Only the click on "Order with Jev"
sends anything (`POST /api/jev/rank` with `force`); opening the page asks the
server for the last order, kept per page in `jev-pages.json` beside the state.
What goes out is title, the triage's one-line gist, the label and the priority.
Rows stay home when their section is in `skip_sections`, when their title,
detail, task, source (who filed an inbox item) or gist holds a `private` word,
or when the triage says they can close or an agent does them. More rows than
one request holds go in batches of 20, at most three. The strip names how many
were left out and why, and the tokens the order took. A work page of `group:
work` has no strip: its By Jev view asks with `daily`, so the first look of a
day orders by itself and every later one that day shows the kept order, and its
button orders anew. The same filter applies to both.

A page holding inbox and task rows together also filters by kind: one chip
per label (Inbox, Task, or a section's short title) with its count, for the
sections, the triage strip and Jev's list alike. Such a page is also where the
task check stands: its own tab goes, and the Task chip shows the check (run,
verdict filter, sort, picking, closing many at once) with the tasks it has not
seen yet below it. A stored link to the old tab lands there.

**Resources.** `scripts/bridge-resources.py` turns what the Bridge declares
into page rows, read only, one `kind: command` section each: `overview` (one
gauge per family), `machines` (`infra/remotes/`, online or offline live from
`tailscale status`, an always-on machine (`capabilities: [arm]`) offline is
red), `workloads --source <file | ssh:host:path>` (the workers of a host that
need a look, worst first, from a `workload reconcile --json` report the host
writes itself with `stamp`; the report's age shows, older than 70 min warns)
and `accounts` (`identity/accounts/`: provider, owner, how many subscriptions,
resource groups, zones, deployments, the portal link and how long ago it was
last checked against the real thing) and `cloud --source …` (what runs in the
cloud accounts now: one head row per account with its resource count and how
many apps run, then each web or function app, zone, Worker, Pages project and
tunnel with its state and a link; stopped is grey, a tunnel down or a failed
deploy red). The cloud report comes from `scripts/cloud-inventory.py`, run once
an hour on the always-on machine as a workload; it asks only accounts that opt
in with `inventory: {enabled: true}` (Cloudflare also `token_ref`, a read-only
token), Azure through the `az` CLI logged in there. Declared is never shown as live. Which
host, which page: the instance's briefing profile. Each listing also lands in
`.bridge/resources/`, where a question to Claude reads it.

**Jev, switched on.** The Jev tab (typed judgments from api.typesafe.ai: urgency,
impact, effort, "only you", a first pick) exists only when `bridge-config.yaml`
says `integrations.typesafe: {enabled: true, key_ref: keychain://<service>/<account>}`.
Without it there is no tab and `POST /api/jev/run` answers 404 `jev_off`;
everything else works the same. Switched on without a key, the tab says what
is missing. The model carries `jev: {enabled, ready, reason}`, so any other
place that wants Jev asks the same switch. It rates by itself at most once a
day (kept in `jev.json`), "Rate again" always; the API reports tokens, not a
price, and the page says so.

Requests name a versioned model, `jev-1.14.0` by default, never an alias such as
`jev-latest`: an alias moves when TypeSafe ships a release, and the answers move
with it without any change here. `integrations.typesafe.model` picks another
version (`jev-<major>.<minor>[.<patch>]`); anything else keeps the default. A new
answer set invalidates the day's cached rating, because the model is part of
what `jev.json` keys on.

**What leaves the machine when Jev is on.** Nothing goes out while
`integrations.typesafe` is off. Switched on, a request to api.typesafe.ai
carries today's date, the name from `cockpit.person_name` (else "the user"),
the sentence `integrations.typesafe.person`, and rows of the dashboard, never a
detail text, a file, a path, a log line or an inbox event:

- **The Jev tab** sends up to 20 rows it shows (briefing sections first, then
  tasks) with only these fields where a row has them: title, why, priority,
  urgency, due, area, gate, bucket, section, task type, inbox state. It sends
  every such row; it has no private filter.
- **A work page with `jev:`** sends only a row's title, the triage's one-line
  gist, its section and its priority. It leaves out the sections in
  `skip_sections`, every row whose title, detail, task, source or gist holds a
  `private` word, and the rows the triage says can go or an agent does.

- **Auto for the model of a start** (`cockpit.launch_model`, below) sends
  only an item's title, kind and priority.

Keep rows that must not leave the machine off the Jev tab's dashboard, or
leave Jev off.

**The model an agent starts with (off by default).** `cockpit.launch_model`
lets a start pick Haiku, Sonnet or Opus and an effort, by hand or by a
recommendation. Nothing changes while `enabled` is false: no choice on the
page, no flag added to the agent's command, no judge asked. Each part has its
own switch:

| Key | Default | What |
|---|---|---|
| `enabled` | `false` | the master switch |
| `manual` | `true` | pick Haiku, Sonnet or Opus by hand at every start |
| `auto` | `false` | the choice Auto: a judge recommends a model, shown before the start, which you can override |
| `effort` | `false` | also pick the effort (`low`, `medium`, `high`, `xhigh`); Auto recommends one too |
| `default_model` | `sonnet` | the model when nothing is picked, Auto is off or no judge answers |
| `default_effort` | none | the effort then; none leaves Claude Code's own default |
| `max_model` | `opus` | the strongest model Auto may recommend; a hand pick is never capped |
| `router` | `chain` | the judge: `chain` asks Jev when it is on and has a key, else Haiku; `jev` or `haiku` only that one |
| `triage_jev` | `false` | the daily check also asks Jev how complex each item an AI may do is (below) |
| `jev_model` | `jev-1.14.0` | the Jev version, else `integrations.typesafe.model` |
| `jev_bands` | five bands | Jev's complexity score (0 to 3) to model and effort, the first band the score stays below |
| `haiku_map` | four entries | Haiku's level (0 to 3) to model and effort |

The judge answers one question per item: how complex the work is, on four
levels described as situations (a lookup, a contained change, a change across
files or an investigation, design or open goals). Code maps the answer to a
model, never the judge itself (`scripts/lib/model_route.py`). A judge that
fails or leaves an item open hands on, and the last word is the default, so a
start never fails over its model. Jev answers in a fraction of a second, Haiku
in several seconds: the page fetches the recommendation as soon as an item's
start block shows (`POST /api/route`) and sends the concrete model with the
click. The click itself never waits for a judge: Auto without a fetched
recommendation starts with the default. With `manual` off a model the page
sends counts as Auto's recommendation and stays under `max_model`. The effort
"Standard" adds no flag and leaves Claude Code's own. Only an item's title, kind and priority go to the
judge, never its detail or a path.

The page **Settings** (behind More) has three areas: Start page, Appearance
and Model choice. Model choice shows every key above in three cards (the
main switch, the choice by hand, Auto) and changes it on top of the config;
Auto's details show only while Auto is on, and the Jev and Haiku tables carry
a scale from 0 to 3 that shows which model each rating gets. A change is kept
in `.bridge/cockpit/launch.json`, marked as changed on the page, and a banner
with "Reset" goes back to the config. The page never
writes `bridge-config.yaml`. A fourth area, News ticker, carries the news band and the live status of the start page (above): the switch, speed and amounts, the status kinds, the editor's interests, and the feed list, where rows are added, removed or switched off and saved as a whole. A feed that failed at its last read shows its error there. Those changes go to `.bridge/cockpit/ticker.json`, with their own "Reset". Every start records its model, effort and who
chose it (`chosen`, `recommended`, `status`, `check`, `jev`, `haiku`, `default`) in
`launches.json`, the data to tune the bands with later.

**Where Auto's pick comes from, first wins.** A task's own `model:` (and
`effort:`) in its STATUS.md frontmatter, set by hand. Then the daily check:
triage judges every item once anyway, and for what an AI may do (`doer` ai or
either) it also gives the `level` of the same four situations, in the same
call, so the pick costs nothing extra and rests on the item's whole evidence,
not its title. With `triage_jev` on (and Jev on with a key) Jev scores those
items too and its score counts; turning it on later scores the items already
checked without asking Haiku again. Then a judge's recommendation fetched for
the row, then the default. The check keeps both numbers in
`.bridge/triage.json` and never writes a task.

Jev ships as CORE, as an optional integration: `scripts/lib/bridge_cockpit/jev.py`
and `scripts/web/jev/` are on the scripts allowlist, but the page loads
`jev/page.js` and `jev/jev.css` with `import()` only once the switch is on, so
a Bridge without it never fetches them. The questions carry no person: they ask
in the dashboard's language about `cockpit.person_name` (else "the user"),
and `integrations.typesafe.person` adds one sentence about them. The quick chat
names the same person. `scripts/tests/test_bridge_cockpit_core.py` holds this: every
file a CORE dashboard file loads statically is CORE itself, no CORE dashboard
file names an instance (a person, a host, a profile id), and a bare Bridge
without cmux, Jev or resources answers every endpoint the page needs.

**Let AI do it on any row.** A row with neither an inbox item nor a task behind it (a
GitHub issue, an application, a deadline from a protocol) also has Let AI do it: it
files the row to the inbox first (`inbox.py add`, free, closed by a person,
with the source and its link as detail), starts the agent on that item, and
takes the row out of the briefing for 30 days, since the inbox item now stands
for it. "Ask Claude" stays beside it for a quick look.

**The same on the other pages.** A row on Status, Dates, Trackers or More that is a
finding (red or yellow) or a tracker row has Let AI do it, Advise and Close as well,
in the table and in its detail. It is keyed `item:<page>/<section>/<row id>` (a hash of
the title when the source gives no id). Let AI do it files it to the inbox under the
key `briefing:<profile>:<section>:<row id>`, the one `to_inbox` uses, so an item the
briefing already filed for that row is reused instead of doubled (under any profile's
name, since the cockpit's profile often extends the briefing's). After every full pass
the cockpit closes the items it filed this way whose row is gone (the probe is green
again); a section that failed or was cut short closes nothing. The briefing's own sweep
does the same when it runs with `--file`. A row without a source id is filed for a
person to close. The row leaves its page for 30 days, or for the day you choose with
Later. Rows that need no one (a gauge, an appointment, a commit count, a log line) get no
buttons; a section can switch it for all its rows with `actionable: true|false` in its
page entry (docs/briefings.md).

**GitHub work with steps.** A `github-work` section (docs/briefings.md § GitHub
work) on a page with `view: board` lists one row per issue or pull request
under its board: the board's status (the field `board.status_field` of its
registry names, default `Status`), its priority as a chip when the registry
names a `board.priority_field`, the pull requests that close it, the task of
this Bridge that syncs it. The rows of a board sort by state, by priority (P1
before P2 before P3, a row without one last; offered only when a row carries
one) or newest first. Above the rows stand its figures (open, yours,
wanting your review, your open PRs, in progress, in review, blocked, quiet,
yours without a task, closed and merged lately), a tile per board with its open cards per state as a
bar and the switch Off · Mine · All, and the people the rows are with; a click
on any of them filters the rows, a second clears it. Opening a row reads its
issue or pull request (description, last comments, labels, boards, review and
checks) and shows its steps as buttons. Its "Steps ▾" menu starts an agent tab
on the row with everything the agent needs in its prompt: Analyse, Implement,
Review the PR, Make it a task, Sync status, Remind, plus the section's own
`row_steps`. The tab is
filed as an inbox item under `tracker:<step>:<row id>`, and the row then names
that item: its tab's state shows on the row and "Open tab" jumps to it, as on a
task row. Any other item whose key ends in the row id (a daily radar's, say)
attaches to the row the same way and never adds a row. An issue assigned to you
that no live task or stream syncs carries a "no task" chip and counts in its
figure, so Make it a task and Analyse are one click away, and Implement too
when no pull request closes it. A row whose issue a
task syncs opens that task's tab instead. No step
writes to GitHub by itself; the prompt sends board changes through
`github-projects-manager` and keeps merging with you.

**Dates as an agenda.** A calendar section with `view: agenda` (docs/briefings.md
§ Dashboard pages) opens with its figures: today and how long it is busy,
tomorrow, the next seven days, collisions, the next event with a countdown, the
longest free block left today, and what other sections on the page say is
overdue or due this week. Below, Agenda, Week and Month switch the view (the
choice is kept in the browser). The agenda lists the events by day under a head
with a bar of the busy hours and a now mark; each event shows its time and
length, calendar, place or "online" with Join, its people and what it collides
with, and its steps (Prepare, the series' own) as buttons. The week is a grid
from Monday to Sunday with the events placed by time and side by side where
they overlap (on a narrow screen it falls back to the agenda); the month shows
each day's count and first titles, and a click on a day opens its week. Calendar
chips, "only mine" (without the information calendars) and a search filter all
three. An opened event lists when, how long, its calendar, place, meeting and
people.

**Close in two clicks.** Every row of the Briefing that can end, its detail,
a task row on a page and a selection carry "Close ▾" with two outcomes,
Done and Not doing it (a task also "Other reason …", the full dialog). What
it does depends on the row: a finite task closes through `task.py close`
(not doing it as declined), an inbox item closes or drops, and any other row
(a GitHub issue, an application, a deadline from a protocol, an upstream)
leaves the briefing for good with its outcome while its source stays as it is:
the issue stays open. Such a row waits under the hidden rows marked "done" or
"not doing it", and "show again" brings it back; no date does. A stream never
closes, so it has no Close.

**Dropping asks why.** Drop on an inbox row opens a small dialog with four
reasons: not worth it this time (preselected, so Enter keeps it one keystroke),
a duplicate, never this kind again, this source is too loud. The last two
leave a mute rule (`inbox.py drop --reason`, docs/inbox.md), and the dialog
says what the rule covers before anything is written. The command box (`c`)
and a drop of several rows drop without a reason, as before.

**Undo and history.** Right after a close, drop or hide the note offers
"Undo" for ten seconds. For a task it restores the status the task had before
the close (backlog, doing or review, read from its STATUS.md); an entry without
one reopens as doing. "History" in the header lists everything the dashboard
closed, dropped, settled or hid, by day, each with its way back: a task "open
again" (`task.py reopen`, back to doing) or "still to be done" (back to the
backlog with a note), an inbox item "open again" (`inbox.py reopen`), any other
row "show again". What was taken back says when. Closes from before the history
existed are filled in once from `audit.log`; one that was opened again since
shows as taken back.

**Drawings.** Three places draw what a table only listed:

- The Check tab opens with the check as a drawn line: tasks, then each model
  with how many tasks it answered and what it cost (a dashed rail to the
  stronger model, labelled "only the unclear ones"), then the verdicts with how
  many to close. While a check runs, light points travel the first rail and a
  bar measures it against the duration of the last check; a finished check sends
  one packet along the whole line and the verdicts light up once. A bar under
  it splits the verdicts by share in verdict order (unclear striped, so it never
  depends on telling two yellows apart); a click on a share filters by it.
- The Sessions tab leads with three counters (sessions, working, subagents),
  and each card with running subagents gets a lane: one bar per subagent from
  its start to now, the lane as wide as the oldest one needs (10 to 60
  minutes). A card rings once when a subagent starts or the session starts
  needing you.
- A page row whose source hands a gauge (`meter`, see
  [`briefings.md`](briefings.md) § Dashboard pages) gets a bar: a quota against
  its maximum with a mark for how much of its time window has passed, and
  "ahead of the time" in words when it runs faster than that; costs without a
  maximum against the largest one in the section. The LLM tab of this Bridge
  uses both. A section whose every row has a gauge with a maximum shows as
  tiles with a half circle: the ranges from `warn` and `bad` as an outer ring,
  the value as the inner arc, a needle for the time passed, and "on pace" or
  "ahead of the time" in words.

Numbers count to their value, bars grow to theirs, the line under the active
page tab glides to the next. Every movement is a damped spring from
`scripts/web/motion.js`, the formulas of the explainer films, on `transform`
and `opacity` only. With "reduce motion" set in the system, everything stands
at its end state at once and nothing moves by itself.

Toasts report every action, and the notes drawer keeps the last 20. A tab that
starts waiting for you is announced; with `voice: true` the browser also says
it.

**Triage on the task and inbox pages.** `scripts/triage.py run` sorts every
task that is not done (streams never close and are left out) and every open
inbox item: one line of what it is about (`gist`), whether it can go
(`verdict`; for a task the task check's verdict wins where it judged), and who
does it (`doer`: the AI with its `effort` as one to three dots, you with a
short `why`, or "the AI prepares, you confirm"). For what the AI may do it
also rates how complex it is (`level`, and `jev` with `launch_model.triage_jev`),
which Auto turns into a model. The mechanical model tier
answers in batches of 20; an item is asked again only when its evidence
changed or its answer is older than `work.review.max_age_days`, so a run costs
cents. Hard rules stand over every answer: an inbox gate `only-you`, a
question or decision put to you, and anything outbound (send, publish, merge,
deploy, pay, credentials) is never the AI's. It runs on "sort again" (`POST
/api/triage/run`), and once a day by itself only with `cockpit.triage_daily:
true` (off by default: nothing costs tokens without a click). It keeps the last run in
`.bridge/triage.json` and shows it in every task and inbox row (the gist first,
the title beneath). A strip on top of those pages filters by All, Can go, AI
can do it, Needs you, Unclear with counts, and closes everything closable in
two clicks after naming it (the `settle` verb, so the history can undo it). An
inbox row on a page carries its item id (`inbox`), which is how a row finds its
triage.

A command row that offers steps of its own (`actions`, docs/briefings.md) shows
an "Action" menu: two clicks run one through `row_action {page, section, index,
action}`, which calls `briefing.py act` and voids the section's cache. A step
whose command returned an undo token is in the history and in the toast with
"take back" (`row_undo {section, row, action}`), the same way as a close.

### The chat as cmux

With `cockpit.chat_layout: workspaces` the Chat tab is laid out like the terminal you work in.

- **On the left** stand the workspaces in the terminal's order, pinned ones first. Each shows its colour, its state, its unread count and, when its folder is another Bridge's clone, that Bridge's name. Below each workspace are its tabs, most urgent first. The quick chats sit in the control workspace (`workplace.control`), the newest six and "all" for the rest.
- **Below the workspaces** come the other Bridges on this machine that have no workspace, and the A2A agents.
- **On the right** is what you picked:
  - a tab's terminal, read every 1.5 s, with "Write" to open it in its window with the message box and keys;
  - a quick chat with its box;
  - an agent with its conversations;
  - a Bridge's folder and how to work in it.

The workspaces come from the terminal driver's optional verb `workspaces` (cmux: `workspace list`, `sidebar-state`, `list-notifications`, all read only), asked with each tab poll. A driver without the verb still shows the workspaces, grouped from the tabs.

The other Bridges are the entries in `infra/instances/` that meet four conditions:

- `relationship` is `sibling` or `downstream`;
- they are not `read-only-from-here`;
- they are not `dormant` or `archived`;
- one of `location.path`, `location.mac_clone` or `location.local_clone` exists as a folder here.

Only the registry and that the folder exists are read, nothing inside the other Bridge (`rules/multi-instance-isolation.md`). This layout writes nothing new: typing into a tab still goes through its window, with the checks it has there.

### Keyboard

When the focus is not in a text field:

| Key | Action |
|---|---|
| `j` / `k` | next / previous row |
| `Enter` | show the row in the center |
| `x` | select the row |
| `a` `v` `c` `b` `w` | Let AI do it, Advise, Drop, Later (tomorrow), Let AI do it in its own workspace |
| `r` | reload, fresh |
| `/` | the command box |
| `g` then `t` | the agent tabs |
| `Alt` + `1` to `9` | the page tabs |
| `?` | help |

The row keys (`j` `k` `Enter` `x` and the five letters) act on the Briefing
page only; the others work on every page. A text field keeps every key,
`Alt` + a digit included, because on many keyboards that is how a bracket
or a pipe is typed: leave the field with `Esc` first, for instance after
the Chat page put the cursor in its box.

The command box in the header takes row codes: `3a`, or `1a 4v 6b`, the
number a row shows and the letter of the table above. A row
with a running tab jumps there instead of starting a second one, and `a` or
`w` is refused for an entry only you can do, a row that waits for someone else,
and a yes already given.

## 4. Safety model

The page can approve inbox entries and start agents, so it is built to do
nothing a stranger could trigger:

- the server binds `127.0.0.1` only, never every interface;
- the key is made once and kept in `.bridge/cockpit/token` across restarts
  (`new-token` makes a new one on the next start). No command and no skill
  prints it: a link from `url`, `start` or `open` carries a login code made
  from the key (HMAC-SHA256), which works once and only within a minute. The
  server swaps the code for a cookie (`HttpOnly`, `SameSite=Strict`, named
  after the port, `bw_token_<port>`, so two Bridges on one computer keep their
  own) whose value is also derived from the key and dated, so the cookie is
  not the key and the server stops taking it after three days; the address
  bar keeps no code;
- every request must name `127.0.0.1:<port>` or `localhost:<port>` as its
  host, every click must come from the page itself (`Origin`, a second value
  derived from the key in a header, `Sec-Fetch-Site`), and the page allows no frames,
  no scripts from elsewhere and no external addresses at all;
- the page sends verbs, never commands: a fixed list (approve, defer, drop,
  close, settle (done or not doing), urgency, priority, note, check tasks, keep open, close task, launch, adopt, send, key,
  close tab, snapshot, ticker settings, ticker refresh, ticker edit, ticker profile), every id
  checked again before it reaches a script, every argument a separate word,
  texts after `--`;
- the news ticker reads only the feed addresses you wrote into
  `cockpit.ticker.feeds` or saved on the settings page (an address in your
  own network is allowed because you chose it), only over http or https, with
  no user name in the address, at most three redirects, eight seconds and 2 MB
  per feed (a gzip body sent unasked is unpacked to the same 2 MB). A feed
  that declares a DOCTYPE or an entity is refused before it is parsed. The server never opens an item's link. Titles are stripped of markup
  and control characters and shown as text; a link becomes an anchor only when
  it is http or https, and opens with `noopener` and no referrer. Feed text
  reaches Claude only as the one prompt of the Editor button, a read-only Haiku
  call with no tools, and what comes back is used only as item numbers and
  short titles. The titles of your open tasks reach Haiku only on the button
  "Written by Haiku", and its answer is shown as text to take or drop;
- a Markdown answer (Chat, Other Bridges) is read into plain objects and drawn
  as elements, never parsed as HTML, so text in an answer cannot become markup
  or script; a link keeps only http, https and mailto and opens with
  `noopener` and no referrer;
- a script runs only from the Bridge's own list (`briefing.py`, `inbox.py`,
  `workplace.py`, `task.py`, `bridge-resources.py`, `triage.py` and the cmux
  layout script), besides the read-only quick chat and the A2A shapes of
  section 5; whatever the page does to an agent tab goes through
  `workplace.py` and its terminal driver;
- nothing goes out without your click, and an inbox action approved on the
  page still runs only at the next `inbox.py run`, on the machine named in
  `inbox.runner` ([`inbox.md`](inbox.md));
- the server collects with `--no-save`: the page never moves the "since last
  time" baseline of your text briefing;
- every POST except `/api/reload` and `/api/presence` (whether a page is
  visible, sent on every tab switch) leaves one line in `.bridge/cockpit/audit.log`,
  never a text and never the key: a write action through `/api/action` (time,
  verb, rows, exit codes), a question through `/api/ask` (`ask`, kind, `via`,
  relay or conversation id, character count), `/api/route` (`route`, number of
  rows, judge), `/api/jev/run` and `/api/jev/rank` (`jev_run`, `jev_rank`,
  requests, rows and model sent to Jev) and a triage run (`triage`, click or
  daily, number of items, model; a click while one runs says `started=false`).
  Read-only verbs and requests refused before anything happened leave none;
- a question for Claude carries a signature (HMAC-SHA256) made with
  `relay.key`, which lives outside the Bridge in a folder only you can open
  (`~/.local/state/bridge-cockpit/`, or `$BRIDGE_COCKPIT_KEY_DIR`). The session
  submits only questions whose signature checks out, so a program that can
  merely write files into the repository (an agent tab, for example) cannot
  hand the control session a prompt. The prompt names the page as its source
  and puts every text from the briefing (titles, references, tab names)
  between « and » as data, never as an instruction of yours.

**Limits.** Browsers send a cookie to every server on `127.0.0.1`, whatever
its port. Another local web server you open can therefore read the cookie and
use it until it ends. That needs a program running on your computer, which
could also read `server.json`; stop the dashboard (`bridge-cockpit.py stop`) when
you test web code you do not trust on this computer.

## 5. Asking Claude: the relay

"Ask Claude", "Follow up" and the free question need a model. There are no
canned prompts in the window: you ask straight away, the box has the cursor.
"Ask Claude" (in the header, on a row, on a page item) opens the chat window,
and each chat is a short Claude session of its own (`scripts/lib/bridge_cockpit/quick.py`): `claude -p` in this Bridge's
folder with Haiku 5.5 by default (Sonnet or Opus picked in the window, the
choice kept in the browser), only the tools Read, Grep and Glob and none of
the user's settings, so it can read tasks, board and log and change nothing.
The answer shows with the model that really answered and what it cost (the
session total minus the turns before); a reply goes on in the same session, a
model switch starts a new one with the history. Every message picks its way
with one of two buttons: "Ask" (Enter) is the quick read-only answer above,
"Solve in cmux" (Cmd or Ctrl Enter) gives it to a real Claude session in a
cmux tab, which may act. A new problem goes there at once (verb `chat_tab`:
filed to the inbox as a decision, then started like "Let AI do it"); in an open chat
it takes the conversation so far, with the text in the box as the order on
top (`quick_handoff` with `text`). Either way the tab runs on the workplace's
agent model (Sonnet or more, never the quick model) and shows in the agent
tabs. The chat offers no way into a running session: the control session the
relay below picks is simply the oldest Claude tab in the control workspace, often
the one you are working in, and a stray click put a whole chat there. With
`cockpit.relay: false` no tab counts as the control session at all, "Advise"
on a row without a task files it to the inbox and starts a reporting tab, and a
question `via` control answers `relay_disabled`. An answer that arrives while
the chat is not in view shows as a note with "View".

The answer streams: the CLI runs with `--output-format stream-json --verbose
--include-partial-messages`, and the text so far plus the file it is reading
reach the page as the `quick_live` event, at most every 0.3 s. Chats are kept
in the state dir (`quick.json`, the last 30), so a chat goes on after a
restart of the dashboard; one that was answering when it stopped says so.
No chat is ever dropped: the 31st pushes the oldest, a chat untouched for
`chat_keep_hours` (a day by default) leaves on the next look at the list, and
"remove chat" (or the × beside a chat in the sidebar of the chat as cmux) takes
one, into the archive `chats/quick-YYYY-MM.jsonl` in the state dir (one line
per chat, whole, with `why`: `overflow`, `expired` or `removed`; A2A
conversations go to `chats/agents-YYYY-MM.jsonl`). When the archive cannot be
written, the chat stays in its list, and an expiry is tried again an hour later. Deleting for good means deleting that file by hand. The
Chat tab lists every kept chat (first question, when, model, cost) and opens
one with its box ready; "As a tab" in the window moves the open chat there.

**Markdown answers.** An answer in the Chat and an answer from another Bridge
on the Other Bridges tab show as formatted text: headings, paragraphs, lists
(nested, numbered, ticked), code blocks, quotes, tables, bold, italic, strike,
inline code and links. A link becomes clickable only when it is http, https
or mailto; any other address stays plain text. Raw HTML in an answer is never
markup, it shows as the characters it is (`scripts/web/markdown.js`, drawn by
`views/prose.js`).

**Other Bridges** (`scripts/lib/bridge_cockpit/agents.py`). Where `infra/a2a-peers/` holds
a peer, the Other Bridges tab lists each with what its public agent card says (name,
skills, protocol version; fetched in the background, kept five minutes, never a
token) and opens a conversation with it. A message goes out only on a click,
as a question (as typed) or a task (wrapped with what is expected back),
through `skills/a2a/scripts/a2a.py ask --json --wait 90`, which resolves the
peer's token itself; the runner lets through only that shape and `get`. A
follow up continues the peer's A2A context. A peer that holds a task for its
owner's approval answers with a state that is not final: the turn shows as
held, the tab wears a dot, and "look again" reads the task with `a2a.py get`
without sending anything new. Conversations are kept in `agents.json` in the
state dir, and one that leaves the list goes to the archive (see the Chat). Without a peer there is no tab. The quick chat's system text names
`infra/a2a-peers/` too, so it can suggest asking an agent; it sends nothing
itself.

**Folding the list of agents.** The list of agents beside a conversation
folds away with its button, so the conversation gets the whole width; the
button brings it back. The choice is kept in this browser only
(`localStorage`), so another browser or computer keeps its own.

The control session itself has its own window ("View" on its card, or
"Control session" in the question window): its terminal, live, and a box that
reaches it through the relay. That is the way for a question that needs the
day's context or should act at once.

1. The server builds the prompt from what the page shows (only the free box
   takes your own text), puts a marker in front, `[web:<id>]`, and a line that
   it comes from the local cockpit, and files it for exactly one
   session.
2. Which session: every Claude Code session with the `cockpit-relay` mod
   installed (section 1) and the relay on writes a heartbeat every 5 seconds,
   naming the tab it runs in (the cmux surface, else the tmux pane). The
   server picks the one whose tab is the control tab: the oldest Claude tab in
   the control workspace (`workplace.control.name`) that has the relay on. A
   session that started before the cockpit was switched on never heartbeats,
   so the next one in that workspace takes over instead of the page staying
   offline. Without a terminal driver that lists the tabs, without a control
   workspace, or when no tab of the control workspace is open, it picks the only session
   with a fresh heartbeat; with several and no control tab it picks none and
   says so. Only interactive sessions take part: a `claude -p` run or an SDK
   session never heartbeats.
3. That session submits the question as a prompt of its own, framed as a
   message from the `cockpit-relay` plugin, never as your own words. It submits
   only while no turn runs and no other web question is open, one at a time,
   and never twice: the server addresses each question to one session, and
   that session marks it as handled before it submits.
4. When that turn ends, the session writes the answer back, and the page
   shows it as plain text. A turn that was stopped or failed brings no answer
   of its own and shows none.

A question waits at most 10 minutes for its turn; after that it expires and
is never asked. A question whose turn has not ended after 30 minutes (often a
permission prompt in that session) shows as stuck, and the next one may go;
when that turn ends after all, its answer still arrives. A question that a
hook of the session refuses shows as failed. When the session ends, its
heartbeat says so at once and no question is addressed to it anymore.
Agent tabs never relay.

**Offline.** When no session can take the question, the page says why (relay
off, no session with the mod, no control tab among several sessions) and
offers the text to copy. When the control tab waits for input, "Type into the
control tab" sends the text there directly.
When no session in the control workspace answers, "Start Claude in Bridge"
(beside the relay state in the header, in the Claude window and on the Sessions
tab) runs `workplace.py control --yes`: a new Claude tab in the control
workspace, the workspace created first when it is missing. Nothing is closed
or moved. The new session heartbeats after about half a minute, and the page
uses it at once: the control tab is picked again from the fresh heartbeats at
every read, not only at the next tab poll.

**Known limits.** When a turn shows no text at all, the session takes the
first such turn starting within 60 seconds of the submit as the answer. A
turn that shows any other text (a prompt you type in that moment) is never
taken for the web question.
Approve, start and every other action never go through Claude: they are the
fixed verbs of section 4.

## 6. Files

Everything lives under `.bridge/cockpit/` in the Bridge root, which git ignores:

| File | What |
|---|---|
| `token` | the key, kept across restarts until `new-token` (readable by you only) |
| `server.json` | the running server: pid, port, key (readable by you only) |
| `server.log` | errors, never a key, cookie or request body |
| `audit.log` | one line per write action, question, route, Jev request and triage run |
| `history.json` | what was closed, dropped, settled or hid, with its undo (readable by you only) |
| `state.json` | rows hidden on the page, team runs started from the page |
| `view.json` | the last briefing, shown at once on the next start until a fresh one arrives |
| `launches.json` | the starts of the last days for the return channel, with model, effort and who chose them |
| `launch.json` | the settings page's changes to `cockpit.launch_model` (only keys that differ from the config) |
| `ticker.json` | the settings page's changes to `cockpit.ticker` (only keys that differ from the config) |
| `ticker-cache.json` | the news ticker's last feed items, each feed's state and the last editor result, shown at once on the next start |
| `relay/inbox/` | questions for a session (written by the server) |
| `relay/done/` | what became of each (written by that session) |
| `relay/heartbeat/` | one file per Claude Code session with the relay on |

The server deletes relay files after a day, heartbeats after an hour. The
`relay/` folder is readable by you only. The signing key `relay.key` is the
one file outside the Bridge: `~/.local/state/bridge-cockpit/` (folder and file
readable by you only), or the folder `$BRIDGE_COCKPIT_KEY_DIR` names; delete it
to get a new one at the next start.

## 7. Ports

The default is `8797`. Other Bridge services use ports near it; if `8797` is
taken on your computer, pick another in `cockpit.port` (1024 to 65535).

## 8. Build your briefing profile

The page reloads by itself: a change in the inbox or the tasks refreshes the
rows within seconds, and the full briefing runs every `full_minutes` while a
page is open. What it collects comes from your briefing profile,
`workflow/briefings/<id>.yaml` ([`briefings.md`](briefings.md)). The page shows
the profile `cockpit.profile` names, else `briefing.default`, else the one with
`default: true`, else the only one there is.

The cockpit serves itself from the briefing and adds to it: give it a profile
of its own that `extends` your briefing profile ([`briefings.md`](briefings.md),
"Which profile runs"). It takes every section of the briefing, so the Briefing
tab shows the same rows, and adds the sections only the cockpit shows (the
token use, the machines and accounts of a Betrieb page) and the `view.pages`.
`/briefing` in the terminal keeps the lean briefing profile and does not
collect what only the pages need.

```yaml
# workflow/briefings/cockpit.yaml
schema_version: 1
scope: user
id: cockpit
title: Cockpit
extends: morning
sections:
  - {kind: command, id: res-machines, argv: ["python3", "scripts/bridge-resources.py", "machines"], bucket: none}
view:
  pages:
    - {id: work, title: Work, sections: [inbox, tasks]}
    - {id: ops, title: Ops, overview: true, sections: [res-machines]}
```

With `cockpit: {profile: cockpit}` the cockpit runs it.

Without a profile of your own the built-in one runs (inbox, advice, tasks,
calendar, activity, and the trackers you enabled). It has no view, so the
cockpit asks for the triage view itself: the Today tab shows your inbox,
the advice and your tasks, the calendar and the activity sit on their tabs.
That is enough to try it; for your own sources, tabs and marks, copy the
template:

```bash
cp workflow/briefings/_template.yaml workflow/briefings/morning.yaml
python3 scripts/briefing.py validate          # names every problem
python3 scripts/briefing.py collect --json    # what the cockpit receives
```

Edit `for:` and the `owners:` of the `github-mine` section (your GitHub org or
user) before you collect, or delete that section if you do not use GitHub.
Otherwise it answers without error and stays empty.

Each section is one source: the inbox, your tasks, a calendar, a tracker
(GitHub, GitLab, Jira, Azure DevOps, Linear), today's commits, or any program
of your own that prints JSON (`kind: command`). The kinds and their keys are in
[`briefings.md`](briefings.md).

### Tabs and columns

Without `view.pages` the kind decides the tab: `command` sections (your own
probes) on Status, calendars on Dates, trackers on Trackers, commits and
activity on a page of their own, inbox, advice and tasks on the Today tab itself, any
other kind on More. To choose yourself, merge these keys into the `view:`
block your profile already has, and add the two sections the template leaves
commented out:

```yaml
view:
  pages:
    - id: github
      title: GitHub
      sections: [github-mine]                  # the template's tracker section
    - id: today
      title: Today
      sections:
        - calendar                             # a section without id: its kind
        - commits
        - {id: activity, badge: false}
    - id: systems
      title: Systems
      sections:
        - {id: probes, alarm: true, empty: "all green"}

sections:
  # ... the template's sections, then:
  - kind: commits
    days: 7
  - kind: command                              # any program printing JSON items
    id: probes
    title: "Probes"
    argv: ["python3", "tools/probes.py"]
```

A page names sections by id; `validate` says which id it cannot find. A page
with `group: more` folds behind the "More" tab when the bar is narrow; a page
with `group: day` gets no tab and stands as "What happened today" in the
middle of the Today page (section 3); `overview: true` and `jev:` are in
section 3 as well.

Every row has the same columns: when, title, detail, link. A page entry
overrides them per section (`when`, `detail`, `link` name an item field),
`empty` is the text for nothing (default "nothing"), `alarm: true` turns every
row into a red finding and nothing more, `badge: false` keeps a section out of
the number on its tab. A task's open steps are the unchecked boxes, else the
bullets under a "Next steps" heading in STATUS.md; a profile names headings in
another language with the tasks section's `step_headings`.

### Marks for customers and projects

```yaml
view:
  marks:
    - {label: ACME, match: [acme, acme-portal], color: magenta}
    - {label: Beta, match: beta-corp, color: cyan}
```

A row whose title, id, project, repo, task, context, area, labels or url (its
link) contains one of the words gets the label in front, on the page and in
the text briefing. The first mark that fits wins. Customers change; keep them
here.

### Fast despite slow sources

A tracker can take 20 seconds. `cache_minutes` on a section reuses its last
good answer for that long, and the section then says how old it is
("measured 08:46"). It says so only when that time differs from the as-of
time in the header, so a screen shows one time unless a source really is
older. A row you put off or settled leaves its section's count, its finding,
the tab badge and the alarm along with the table:

```yaml
sections:
  - kind: tracker
    id: github-mine
    provider: github
    query: {assignee: "@me", kinds: [issues, prs]}
    cache_minutes: 5
```

Reload (`r`) always asks every source fresh, except GitHub while its budget is
spent: then no section asks it until the reset, and a tracker section shows
its last rows with a line saying so ("GitHub limit reached, not asked until
10:27"). A failure is never kept, and nothing cached crosses midnight
(docs/briefings.md § GitHub's budget is shared).

### Words

The page's own buttons and help come in German and English
(`cockpit.language`). The briefing's words (headline, tab names, "today") are
yours: set them in `view.labels`, for example
`labels: {page_status: Systeme, today: heute}`.

Opening a `file://` link on the page is not possible; the page shows its path
to copy.

## 9. When something is off

| You see | Why, and what to do |
|---|---|
| the page says to open it with the link from `bridge-cockpit.py url` | first visit in this browser, the cookie is gone or older than three days, or `new-token` made a new key: run `python3 scripts/bridge-cockpit.py url` and open that link within a minute, or `/cockpit` |
| the bare address does not answer | the server is not running: `python3 scripts/bridge-cockpit.py start`, or `autostart on` so it runs from login |
| `/cockpit` is an unknown command | the session does not run in the Bridge root, or `skills/cockpit` is missing in this Bridge; `python3 scripts/bridge-cockpit.py open` works from any terminal |
| `/cockpit` or `open` says the cockpit is off | `cockpit.enabled` is not `true` or the `cockpit:` block has an invalid value |
| the port is taken | another program uses it: set `cockpit.port`, then open again |
| the server did not come up | read `.bridge/cockpit/server.log` |
| relay offline: "no heartbeat" | no Claude Code session with the `cockpit-relay` mod runs here (section 1, `claude plugin list`), `cockpit.relay` is `false`, or the session started before you switched the cockpit on: start a new Claude Code session (`/reload-plugins` reads the config again only when the mod itself changed) |
| relay offline: "no control" or "ambiguous" | several sessions run and none is the control tab: open the control workspace (`workplace.control.name`) in your terminal, or keep one session |
| a question stays "stuck" | the control session waits for a permission prompt or a long turn; answer it there |
| a question is "rejected" | its signature did not check out: it was not written by this server, or `relay.key` changed since; ask again |
| the header says "connection lost" | the server stopped or restarted; the rows shown no longer update: `python3 scripts/bridge-cockpit.py open` |
| a tab button answers "The terminal cannot do that for a tab" | the terminal driver does not serve that verb (`python3 scripts/workplace.py caps --json`), or no driver is set in `workplace.driver` ([`workplace.md`](workplace.md)) |
| "Save layout now" answers "cmux is not available" | the server cannot find the cmux CLI: start it from inside cmux, or set `CMUX_BUNDLED_CLI_PATH`; without cmux there is no layout to save |
| the tab column says "Tab state not current since …" | `workplace.py status` failed; the reason is shown |
| "Nothing waits for you" and empty tabs | the profile has no sections for it: run `python3 scripts/briefing.py collect --json` and look at `pages` |
| a tracker tab is empty but not failing | check its `query` (`owners`, `repos`): the template's placeholders find nothing |
| the page shows an old state | it is the last briefing of today until the fresh run ends; reload (`r`) asks every source fresh |
| no news band on the start page | `cockpit.ticker.enabled` is not `true` (or switched off on Settings), or no feed was read so far; the first read starts within seconds of opening the page. The status list in the live section shows only while there is something to say |
| a feed shows an error on Settings | the address does not answer with RSS or Atom within eight seconds, is larger than 2 MB, or declares a DOCTYPE; open it in the browser and check it, or switch it off. The other feeds and its own earlier items stay |
| no Editor button on the band | `editor.enabled` is off, or the server cannot find `claude`; it also stays greyed while an edit runs |
| an item you expected is missing | a muted term matches its title, it is older than `smart.max_age_hours`, or it joined another feed's item (hover the `+N`) |
| a feed says "not XML" | the address returns something other than a feed (an HTML page, a login); open it in the browser |
| the editor hides items you want | it shows only its picks and what came after; sharpen `editor.interests`, or press Editor again. Changing the interests shows every item until the next edit |
| the ticker shows no CPU or memory warnings | the cockpit has no such source. "Slow" covers collect passes, sources, tabs and agent turns; disk only comes through `checkup` |
