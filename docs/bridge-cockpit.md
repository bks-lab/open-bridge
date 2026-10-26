---
summary: "The Bridge cockpit, a local web page that watches and steers the whole Bridge: switch it on in bridge-config.yaml (cockpit:), open it with /cockpit or scripts/bridge-cockpit.py, decide rows, steer agent tabs and ask Claude or Codex from the browser. Covers the three columns, the news ticker, the status pages, the task check, the keyboard, the safety model, the relay mod cockpit-relay, the files under .bridge/cockpit/, how to build the briefing profile it shows, and what to do when something is off."
type: guide
last_updated: 2026-10-25
related:
  - bridge-cockpit-dev.md
  - briefings.md
  - workplace.md
  - inbox.md
  - cloud-costs.md
  - cockpit-areas.md
  - cockpit-files.md
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
| `open_in` | `auto` | `auto`: a cmux browser tab inside cmux, else your default browser; `cmux`, `system`, or `none` (print a login link, good once within a minute; with `--json` only the port) |
| `relay` | `false` | `true`: the control session takes questions from the page as prompts; needs the `cockpit-relay` mod (below), so it stays off unless asked for |
| `profile` | `briefing.default` | which briefing profile the page shows |
| `tabs_seconds` | `10` | how often the agent tabs are re-read while a page is shown; below 5 counts as 5. A page left in a background browser tab stops the full pass and the ticker, and the tabs are re-read only once a minute until it is shown again |
| `language` | `language.conversation`, else `en` | `de` or `en` for the page's own words |
| `full_minutes` | `10` | while a page is open, the full briefing runs again when the last one is older |
| `voice` | `false` | the browser also speaks a tab that starts waiting for you |
| `launch.target` | `area` | where Let AI do it opens a tab: `area`, `tab`, `workspace` or `auto` ([`workplace.md`](workplace.md)) |
| `triage_daily` | `false` | `true`: the triage sorts every task and inbox item once a day by itself (a small model call, a few cents); otherwise only on "sort again" |
| `chat_layout` | `classic` | `workspaces`: the Chat tab as cmux shows it, see [The chat as cmux](#the-chat-as-cmux) |
| `chat_keep_hours` | `24` | quick chats and A2A agent conversations untouched this long go to the archive (below); 0 keeps them, then only the limit of 30 applies |
| `work_view` | `due` | the view the work tab opens on: `due`, `source` (By source), `jev` (By Jev) or `files` (Files), see [The files view](cockpit-files.md); a view the tab does not offer opens Due. A click on the tab's switch still picks another for this browser, until the key changes |
| `focus_to_files` | `false` | `true`: when the focus on the start page runs out, its calm card and its last step lead on into the Files view of the work tab rather than to the tasks |
| `files_scope` | `active` | which tasks are files in the Files view: `active` the `doing` and `review` ones, as before; `all` every task and stream but the closed ones, the queue on top and the rest behind it on the chips Active, Waiting, Resting, Backlog and All, see [Every task as a file](cockpit-files.md#every-task-as-a-file). Any other value keeps `active` and is named in `status` |
| `origin_map` | none | your own source names, mapped to a category the work tab shows: a name or a quoted glob (`"*-health"`) to one of `github`, `tracker`, `calendar`, `bot`, `session`, `skill`, `work`, `person`, `bridge`, `other`. It comes before the built-in rules; a wrong category or a repeated name is ignored and named in `status`. It stays on the server, the page never sees it (see [Where a row comes from](#where-a-row-comes-from)) |
| `describe` | `auto: off` | each item's brief (goal, story, acceptance) written and kept by a small model, see [Each item's brief](#each-items-brief): `auto` is `off`, `missing` (items without a brief) or `stale` (also briefs whose text moved on); `budget_per_hour` (`20`) caps the calls of an hour; `kinds` (`[task, stream, inbox]`) names what the pass takes; `effort` (`medium`) is how long the model may think, `low`, `medium` or `high`. The button on a card works with `auto: off` too |
| `a2a_sources` | none | further sources of A2A peers beside `infra/a2a-peers/`: a list of `{name, script}`, `script` a skill's own `skills/<skill>/scripts/<name>.py` that reaches agents another way (an access proxy, a broker) and keeps its own credentials. At most four; a bad entry is ignored and named in `status`. Contract under [Peers from a script](#5-asking-claude-the-relay) |
| `snapshot_minutes` | `60` | while the server runs, save the cmux layout this often, only when it changed; `0` = only on "Save layout now" |
| `idle_minutes` | `10` | a tab the terminal reports as waiting that has been still this long and whose last words ask nothing (no question mark, no options, nothing typed in its prompt) is done, not waiting: it leaves "waits for you" and counts as "to review" in its area; a tab whose item or task is settled is done at once; it reads the tab's screen, so without a terminal driver that serves screens (or with the questions off) only the settled rule applies and every other tab keeps waiting; an idle tab raises no "waits for an hour" and the decision guide does not read it; `0` = off |
| `person_name` | none | how Claude and Jev name you; without it they say "the user" |
| `launch_model` | off | the model an agent tab starts with, and whether a judge recommends one (section 3, "The model an agent starts with") |
| `ticker` | off | the news ticker on the start page: Bridge status and AI news feeds (section 3, "The news ticker") |
| `tour` | `true` | the first-run tour: a first visit offers a short introduction of the page; `false` never offers it by itself (Help and Settings still start it), see [The first-run tour](#the-first-run-tour) |
| `session_guide` | off | the decision guide: Claude Haiku reads a waiting tab's session and offers its next steps as buttons, in the chat and on the Sessions page (section 3, "The decision guide") |
| `usage.remotes` | the machines of `infra/instances` | other machines whose token use the overview page adds in (`infra/remotes` names; `[]` for none), see the overview page, "Tokens" |
| `usage.host` | the infra/remotes entry whose hostname or Bonjour name matches | this machine's name on the token card and in the history file |
| `usage.remote_file` | `~/.bridge/resources/usage.json` | the file `scripts/usage-export.py` writes on those machines |

Migration note: `language`, `full_minutes`, `voice`, `launch.target` and
`snapshot_minutes` used to be set under `briefing.claude_code_ui`, the block
of the retired briefing card. The cockpit no longer reads that block; a key
left there takes its default above. Move them under `cockpit:`.

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
never a link with a key or a login code. It then reads `status --json` once:
`can_launch: false` means no terminal driver starts agent tabs (`workplace.driver`),
so it says so and offers to set the driver; the header of the page shows "agent
tabs cannot start" for as long as that holds.

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
come Sessions, Background jobs, A2A connections (only with the classic chat: with
`chat_layout: workspaces` the agents are an area of the Chat, see [The chat as
cmux](#the-chat-as-cmux)), Tidy up, Jev and every profile page with `group: more`. While the bar is wide enough every tab stands in it; when
they would overflow, that second group folds, from the last tab forward,
behind a last tab, "More", which carries the name of the page open behind it
and a dot when one of them has something. Alt 1 to Alt 9 follow the same
order. A page with `group: day` has no tab: its sections stand under "What
happened today" in the middle of the Today page.

A page with `group: work` has no tab either: it folds into the Today tab, which
then carries that page's title (Work, say) and a switch over its left column
with three views. **Due** is the four blocks below, and the tab opens on it
unless `cockpit.work_view` names another view.
**By source** is the work page itself, its sections as labels. **By Jev** is the
Jev picture (the matrix and the plan) fed by the work page's order, and it
stands only where that page has `jev:` and Jev is on. With such a page the Jev
tab goes too: it is the By Jev view now, and an old link to it or to the work
page opens the matching view. The day moves to Start as well: dates, status,
what is clear or needs tidying and the workplace stand there as cards in a shelf
"The day", above the areas and the project chips since those do not filter it, and the pages of
`group: day` close the start page as shelves of their own. Both show in the
bridge and tiles views only; the overview has no shelves. The middle of Due
shows the day in full in every case (headline, dates, status, what is clear or
needs tidying, the workplace, the pages of `group: day`), under the same area
filter as the rows beside it.

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

### Where a row comes from

Every work row carries two tags, in this order, as words and never as colour alone:

- **What it is.** Task, Stream, Closed task or Ended stream (Closed alone for an older search hit that cannot
  say which of the two); Report (an inbox item), always followed by
  "about ▣ Task: X" or "about ↻ Stream: X" when it belongs to one; Issue, with the same "about" when a task
  or stream syncs it; or Item. A stream's tag also has a dashed border, a second cue beside the word.
- **Where it comes from.** One word and a short detail: GitHub (with the repository), the name of another
  board (GitLab, Azure Boards), Calendar, Bot (a scheduled run, a notifier, a check, a bot, a machine),
  Session (an agent session or tab: Claude, Codex and the like), Skill (a skill run such as a briefing or
  meeting notes), From task or From stream (filed while working on it), By hand (a person), Bridge (started
  here, no other source written down: `task.py`'s own "Ad-hoc <date>") or Other source. A task whose origin is
  free text no rule knows (a call, a meeting, a mail) reads Other source with that text, and a row with no
  source at all reads "Other source · unknown", so no work row goes without the tag. The text as it was
  written stands in the tooltip and in full in the detail's "Source" row, so the word never hides anything.
  The drawers, the walk bars, the check table, the live feed and the history say Task or Stream the same way.

The source of an inbox item is who filed it, not what it is about: a radar job that files about an issue reads
"Bot · radar job" and shows the issue number beside it. A row you sent to the inbox from the cockpit takes the
source of the page row it came from (a GitHub row stays GitHub) and its detail says "filed from the cockpit".

The rules, first match wins: your `cockpit.origin_map`; `bridge-cockpit` (By hand, filed from the cockpit); a
`tab:` or `tab-` name (Session); an agent tool (`claude`, `codex`, `gemini`, `copilot`, `cursor`, `opencode`, also
with `-session`); a `-session` suffix or a second part `session` or `chat` (`laptop/session`); `github`, a GitHub
link or an `owner/repo#n` (GitHub); a leading `bridge/` (the rest is read again, else Bot); an open task or stream
slug (From task, From stream); a run this Bridge declares (`workflow/workloads/`, `infra/channels/`, `agents/` with
an `agent.yaml`) or a machine of `infra/remotes/` (Bot); an agent tool by its longer name (`claude-code`); the shape
`<machine>/<job>` (Bot; the first part is dropped from the detail only when it is a machine this Bridge knows); a
skill folder of this Bridge (Skill); a closed task or ended stream slug; a script of the Bridge itself
(`scripts/*.py`, `skills/*/scripts/*.py`, such as `cloud-costs`) or a name ending in `-bot`, `-notifier`,
`-autorun`, `-watcher`, `-probe`, `-monitor` and the like (Bot); anything else is Other source with its text. A
task's own origin is GitHub only when it starts with the link or the `owner/repo#n` (a PR mentioned in the middle
is no origin). A board row is named by its provider first (a GitLab row is never called GitHub), a GitHub link or
`owner/repo#n` only when no provider is known. Map your own names when a word is wrong:

```yaml
cockpit:
  origin_map:
    notes-bot: bot
    "*-health": bot        # globs need quotes
    alex: person
```

### The files view

**Files** is one more view of the work tab, beside Due: one task at a time as a file, with its next
step, its drawers, a search across every task and a question to the file. It has a page of its own:
[`cockpit-files.md`](cockpit-files.md).

### The start page

**The overview (the default).** Start is a slim control view with three
parts and nothing else:

1. One head line: the day, "N waiting on you (6 tabs, 3 entries)" (the
   first number of the line All, so what has no area counts too; a click
   leads where that number leads, without a filter), the findings of a status page
   and a control session that is not listening as signals (each opens its
   place). The page carries no settings link of its own: Settings sits in the page bar.
2. The **Areas** as a table ([`cockpit-areas.md`](cockpit-areas.md)): the column heads once on top; on a
   narrow screen each line wraps and every number carries its label (the
   table keeps its table roles for screen readers). With the shelf switched
   off a line says where it went.
3. One line **Next up**: the next calendar row that has not begun and the
   quota the defaults take (the first with a window of a day or more), each a
   link to its detail.

Between the table and Next up the overview can show four **parts**, each off
until switched on under Settings, Start page, "Parts of the overview" (saved
with the rest of the start page, `home_tiles` ids `d:waiting`, `d:guide`,
`d:tabs`, `d:day`; a choice made before they existed does not get them):
*Waiting on you* (the section of Work, with its actions and the star),
*Decision guide* (the reading of the next tab that waits on you, the chat's
own card with its guards, Next and Previous through the others), *Agent
tabs* (the cards beside Work) and *The day* (dates, status and tidying up of
the middle of Work; commits and the log of today stay there). They stand
in the order chosen there (arrows move one); on a wide screen the guide and
the tabs stand side by side. Each follows the area filter as Work does, the
bar over the page then names the filter, and a part with nothing in it
stays away. With Waiting on you on, the row keys (`j` `k` `Enter` and the
letters) act on its rows, only those it shows; `x` does not pick there.

Everything else lives on its own page. The other views (bridge, tiles,
list, focus) and every shelf stay a choice under Settings, Start page; a
shelf chosen shows only in those views, and Settings says so beside it
("not in the overview"). A choice saved before the overview existed has no view option
set and so shows the overview; one that picked tiles, list or focus keeps
it. The bridge is now the option `o:stage`, off by default, and the Pinned
shelf is no longer among the defaults (Work filters by the star instead).

**The other views.** "Start" in them is styled like the project website (DESIGN.md: a
Playfair heading over an eyebrow, cards on hairlines). It greets by
`cockpit.person_name`, repeats the briefing's headline, and carries a field
that asks the chat directly. Findings of a status page and a control session
that is not listening stand under it as signals; each opens its place.

**The news ticker (off by default).** With `cockpit.ticker.enabled` the
cockpit shows two kinds of items, each in its own place. The news band is off
the start page unless Settings, News ticker, "On the start page" is on (kept
in this browser only); then it runs as one thin line under the head line,
and under the greeting in the bridge and tiles views:

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

The classic view shows the status list under the greeting, the news band
above it when it is switched on for the start page.

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

What stands on the start page is your choice, all of it in one place:
Settings, Start page, reached through Settings in the page bar like every
other setting. In this order: the view (overview, bridge, tiles, list or focus, five
pictures to pick from), the parts of the overview, then the tiles and
sections of the other views: the stations as one list in their order (a
switch each, a grip to drag, arrows for the keyboard; the bridge has room for
13, Today takes the 14th place), the sections below, what a click on the
core does; last the options. Every row says in one line what it does. The choice lives on the server (`state.json`, key
`home_tiles`, action `home_tiles`), so every browser shows the same. Until
one is made the page shows the overview; the other views then show the first quota of a window of a
day or more, what waits on you, With the AI, the agent tabs, the background
jobs, the next date, the page with the tasks, every shelf but Pinned and every option but the views.

More it can show, each one switched in Settings, Start page:

- **Next up**: one step, large. A tab that asks you, else the first row
  waiting on you, else the first P0 or P1 task.
- **Pinned**: rows you starred. The star sits on every card and every
  Briefing row; a tab card stars its task. Kept on the server (`pins`). Off
  by default: Work has the star filter "Only pinned" in its bar instead.
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

**The bridge.** With the bridge view chosen (`o:stage`), the start page draws the
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

**The list.** The third view (Settings, Start page, View: List) draws no
stage. Under the greeting the chosen stations stand as a strip of numbers;
below them one list of what needs you, each thing once: the next step leads
(a tab that asks for a task's work leads as that task, the tab on it), then
the tabs that ask, the rows waiting on you, "With the AI", the tabs at work,
pinned rows, tasks, and folded at the end the tabs that rest. A tab that
belongs to a shown row stands on that row and is not listed again. An empty
block is not drawn. Beside the list: the dates of today and tomorrow and the
live feed. The section switches apply to the blocks; Quick access has no
place there. A row opens with the rows the list shows as its queue, so the
bar under its detail walks on through them, as on the other lists; the tiles
and the bridge do the same with the rows they show.

**Focus.** The fourth view shows only the one next step, large: its kind,
title, project, the last lines of its tab's screen or why it waits, and its
actions. Under it the same bar as the lists: back, where you stand ("2 of 5"),
the next one with Next, keys `n` and `p`; at the end it says so instead of
starting over. The step in front is held by what it is, not by its place: a
tab that starts asking moves to the front without changing the card, and once
the step is settled the next one moves up into its place. Below it the queue
(the tabs that ask, the rows waiting on you, the P0 and P1 tasks) as small
cards, a click brings one forward. Beside it today as a timeline from now to midnight and what
the AI does (tabs working, resting, results in). It has no stations and no
sections to choose.

**The assessment.** It is read first from the page's own data and
laid out as a board, at once and without cost: first (what `focusPick`
chooses), asks you, your yes, at work, answers in, no word, next date, the
tightest quota (one running over its pace before one that is merely high),
findings and can wait. Each field leads where it names. Then Claude gets
exactly that board as lines (`situationText` in `logic.js`) and answers in
three fixed lines, first, then, can wait, which the panel shows as three
rows; an answer of another shape shows as it came. Questions after it go on
in the same conversation. That conversation belongs to the core (`/api/ask`
with `place: core`): it stays out of the chat lists, and the next assessment
or question typed in the core's panel takes its place, the last one going to
the archive with `why: replaced`.

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

The project chips, the **Areas** lines with their numbers, where each number leads, the one area
filter over Work, Chat and Sessions and why a tab gone idle counts as finished have a page of their
own: [`cockpit-areas.md`](cockpit-areas.md).

`g` then `a` jumps to the
start page and puts the focus on the area lines; `j` and `k` move there, `Enter`
picks. The shelves:

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
  main button. A selection gets a bar with the same two doors as a row: Let
  AI do it (n) ▾ with one order for all of them (start, advise, each in its own
  workspace, the model), Close n ▾ with one comment for all (done, discard, not
  now, a note). "Approve all N" under "AI can take over" asks once, with the count the
  server found, before it approves anything. Rows you hid sit at the bottom
  with "show again".
- **center, the detail** of the row you clicked: its link, its facts, every
  action the row allows (later with a date, hide, drop, urgency, priority, a
  note, a start as a tab, in its area or in its own workspace, team roles,
  assigning a running tab, and for a task its check and Close, see below), the
  inbox entry with the exact command a yes
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
columns with its sections (which section lands on which tab: section 8): when,
title, detail, a link,
"ask" for findings, and "start agent" (or "go to tab" when one runs) for a task.
Clicking a task's title opens its full detail beside the page, with every
action of the center column as buttons (the keyboard shortcuts work on the
Today tab only); the page stays where it was, and Escape or "Close details"
goes back to it.

**Working through a list.** A detail opened from a list (the Today list, Jev's
plan and its list view, a section of a work page, the task check) carries that
list with it; the Today list walks all its rows in section order, the ones
folded behind "more" included.
A small bar stays at the foot of the detail column or the item drawer however
long the detail runs: back, where you stand ("2 of 13"), the next entry with
**Next**, and the two after it as plain links. The order is the one the list
shows (Jev's rank, the lanes from top to bottom). An entry settled meanwhile
drops out at once, and the last one says so. After **Next** the focus stays on
the button, so `Enter` goes on to the one after; the drawer starts each entry at
its top. Settling an item in the drawer ("Close", "Let AI do it") opens the
next one instead of closing the drawer. With the keyboard shortcuts on, `n` and
`p` walk the list, in the drawer too. On a phone the bar sits at the bottom of
the screen and shows the next title on its own line.

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
recommendation with its reason, confidence, model and evidence, with Close ▾,
Keep open (until the task changes), Check again and, for unclear or guessed
answers, Check closer with the stronger model. The Check tab is the overview of
the last run: a filter per verdict and "changed", sort by verdict, priority or
quiet, and a selection for Let AI do it (n) ▾, Close n ▾, Keep open and Check
closer. Both doors work as on every other row: Close ▾ on a
task the check would close starts with the check's reason in the sentence, and
the panel names an agent tab still working on it. `task.py close` then moves
the task to `work/done/`, regenerates the board and writes a row to
`work/log.md`.

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
opens that tab in the middle like the Claude Code CLI: its terminal, read
through the terminal driver (`workplace.py screen`, read only, the last 400
lines) every 1.5 s right after a change and slower, up to every 5 s, while it
stays the same. The page sends the hash of the screen it holds
(`/api/tab/screen?ref=...&since=<hash>`) and the server answers `unchanged`
without the text when nothing moved; it keeps one read per tab for a second, so
several pages on one tab share one driver call. What you typed is
marked, the end stays in view unless you scrolled up, and below it stand Yes, No, Go
on as the tab's state allows and a box that sends a message to it (Enter
sends, Shift+Enter a new line). Escape or a click outside closes it.

**Overview pages and tokens.** A profile page with `overview: true` opens
with a board of tiles: one per section, with its count, its loudest row and a
colour for the worst tone (a quota gauge shows its fullest value, a plain gauge
its counts), plus one for the background jobs of the Background jobs tab, one for the tokens
of the week and, when the page places the cost card, one for the cloud costs
(yesterday, the month so far and seven small bars). A click on a section tile
scrolls to that section, the cost tile to the cost card, the workers
tile opens the Background jobs tab.

**Where the live cards go.** Three cards are not sections but live views:
`costs` (cloud costs), `usage` (tokens) and `noise` (noise in the inbox). A
page places them with `cards:`, each after one of its sections or, without
`after`, at the end, in the listed order:

```yaml
cards:
  - {id: costs, after: systems}
  - {id: usage, after: systems}
  - {id: noise}
```

A page with `overview: true` and no `cards:` shows tokens and noise at the end,
as before. A card named twice stands where it is first named; when the page
shows Jev's order instead of its sections, cards placed after a section move to
the end.

**Tokens.** The token card shows one bar per day over 7, 30 or 90 days (chips;
`/api/usage?days=N`, any other number goes to the nearest of the three), split
by Bridge, model, source (sessions, subagents and programs: `claude -p`, the
workers) or project, the three largest and the rest. A click on a day lists its
models and projects. The server counts them from the Claude Code transcripts of
this machine (`~/.claude/projects`, `scripts/lib/bridge_cockpit/usage.py`, read
on from where the last count stopped) when the page opens: written tokens as
measured, cache reads and writes beside them, no price. A record belongs to the
Bridge in `infra/instances/` whose `location.path` is the longest prefix of the
session's folder, else to "no Bridge". The transcripts are read for the last
eight days only; every closed day is kept in
`.bridge/resources/usage-days.json` (120 days), which is where 30 and 90 days
come from. A source that wrote at least three times its usual day (and 50,000
tokens) is named in orange; that check reads this machine's last seven days.

"Per Bridge" lists every Bridge with its machine, its output tokens, its top
models and a small line per day, also Bridges on other machines. Each of those
machines runs `scripts/usage-export.py --out ~/.bridge/resources/usage.json`
as a workload (daily or hourly); the cockpit reads that file over ssh
(`ssh:<host>:<path>`, read on a thread of its own, kept 10 minutes, never on a
page request). Which machines: `cockpit.usage.remotes` in `bridge-config.yaml`
(a list of `infra/remotes/` slugs), else every `location.host` of
`infra/instances/` that has an `infra/remotes/<host>.yaml` and is not this
machine. The file is `cockpit.usage.remote_file`, default
`~/.bridge/resources/usage.json`. A machine that does not answer stays in the
list as "not reachable" with the reason; it never breaks the local view. Right
after a start, before its first read has finished, a machine shows as "being
read", not as unreachable. A history file that cannot be read is moved aside as
`usage-days.json.bad-<time>` instead of being overwritten.

```yaml
cockpit:
  usage:
    remotes: [my-server]
    remote_file: ~/.bridge/resources/usage.json
```

**Cloud costs.** The cost card shows what the cloud accounts cost per day over
7 days, 30 days or the month: one stacked bar per day (the three most expensive
accounts and the rest; the last two days lighter and marked provisional,
because providers settle late), a click on a day lists its accounts and their
top groups, and one row per account with yesterday, the month so far and a
budget bar (forecast as a marker; orange when the forecast passes the budget,
red when the month so far does). It names when it was measured and on which
machine, and warns when the report is older than 36 hours. The numbers come
from `scripts/cloud-costs.py`, run daily on the always-on machine as a
workload, which asks every account in `identity/accounts/` with
`costs: {enabled: true}` (Azure, AWS and Google through their CLIs logged in
there, OpenAI and Anthropic through an admin key by `key_ref`) and adds the
fixed costs of `identity/contracts/` with `costs: {enabled: true}`, all in EUR
at the ECB rate. `bridge-resources.py costs --source <file | ssh:host:path>`
reads the report into `.bridge/resources/costs-view.json`, which
`GET /api/costs` serves. An account whose login or key is missing says so with
the command to run ("Copy command"): on that machine as is, for an ssh source
wrapped in `ssh -t <host> '…'`; for an admin key the command stores it through
the `secrets` skill, never in the conversation. Without a report the card says
what to declare. What each provider needs: [`cloud-costs.md`](cloud-costs.md).

**Noise in the inbox.** The noise card shows the inbox
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
"Standard" adds no flag and leaves Claude Code's own. Only an item's title, kind
and priority go to the
judge, never its detail or a path.

The page **Settings** (behind More) has three areas: Start page, Appearance
and Model choice. Model choice shows every key above in three cards (the
main switch, the choice by hand, Auto) and changes it on top of the config;
Auto's details show only while Auto is on, and the Jev and Haiku tables carry
a scale from 0 to 3 that shows which model each rating gets. A change is kept
in `.bridge/cockpit/launch.json`, marked as changed on the page, and a banner
with "Reset" goes back to the config. The page never
writes `bridge-config.yaml`. A fourth area, News ticker, carries the news band
and the live status of the start page (above): the switch, speed and amounts,
the status kinds, the editor's interests, and the feed list, where rows are
added, removed or switched off and saved as a whole. A feed that failed at its
last read shows its error there. Those changes go to
`.bridge/cockpit/ticker.json`, with their own "Reset". Every start records its
model, effort and who
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
when no pull request closes it. A board's draft card (no issue behind it) is a
row with a dashed icon and a "draft card" chip, no number and no link; it offers
Analyse and Make it a task only, and opening it reads nothing from GitHub. A row whose issue a
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

**Two doors on every row.** Every row of the Briefing, its detail, a row on a
page, the check and a selection carry the same two buttons, and each opens the
row panel with only its own part. Both start with one sentence field, and the
door says what the sentence becomes:

- **Let AI do it ▾**: the order for the agent. Start, Advise, Collect context,
  in its own workspace, the model; Follow up and Ask in the chat. The sentence
  goes on the item as "Start note: ..." before the agent starts and reads it
  first; a row whose agent tab already runs gets it typed into that tab and
  kept on the item as well. `Cmd` or `Ctrl` with `Enter` starts.
- **Close ▾**: a comment. Done and Discard; not now (tomorrow, Monday, a week,
  runs on, a day of your own); keep a note; for an inbox entry, make it a task.

What Close does depends on the row: a finite task closes through
`task.py close` (Discard as declined), a stream asks once before it ends, an
inbox item closes or drops, and any other row (a GitHub issue, an application,
a deadline from a protocol, an upstream) leaves the briefing for good with its
outcome while its source stays as it is: the issue stays open. Such a row waits
under the hidden rows marked "done" or "not doing it", and "show again" brings
it back; no date does.

**Every decision is written where the row lives**, the sentence with it, so
the briefing, other sessions and a later look back read it without the page: a
task or stream gets a dated line in its notes (`task.py note`; a close also
its reason in STATUS.md and a row in `work/log.md`), an inbox item a note
(`inbox.py note`, its close, drop and defer record themselves), and any other
row a row in `work/log.md` (`task.py log`), since it has no place of its own
here. Not now on a task writes "Later until <day>" even without a sentence:
the page only hides the row, the task keeps why it was put off.

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

A note that names its place leads there. It carries `go`, one small closed
union: `{kind: tab, ref}` (the tab, brought to the front where the driver can,
else shown large here), `{kind: row, key}` (a row of the model, opened whole;
one that is gone opens Today), `{kind: item, key}` (an inbox item or a task in
the item drawer), `{kind: page, id}`, `{kind: conv, id}` (an A2A
conversation), `{kind: ask, id}` (a chat with the Bridge) and `{kind: claude}`
(the control session). The server builds it with `ctx.note(text, bad, go)`
and `App.note(text, tone, go)` and sends it with the note, in the action
result and in the `note` event; `actions_base.note_go` keeps only the field of
the kind and drops any other shape, as `logic.js noteGo` does on the page. A
toast or a notes drawer entry with `go` is one button: a click dismisses the
toast (or closes the drawer) and goes there; the close X and Undo stay apart
and never navigate. Tab alerts lead to their tab, a start that answered to its
row, an answered chat or agent to its conversation, and the band's status
list uses the same targets for its notes. At most four toasts stand at once:
one more does not vanish silently, a last compact toast says "+N more" and
opens the notes drawer, where every note still is.

**Triage on the task and inbox pages.** `scripts/triage.py run` sorts every
task that is not done (streams never close and are left out), every open
inbox item and, since the cockpit hands over its view (`--view`), every board,
application and issue row of the work tab, read with the issue's state and the
start of its text or the application's STATUS.md: one line of what it is about
(`gist`, saying what the title leaves out), what kind of work it is (`topic`,
shown as a chip on the work tab), whether it can go
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

### Each item's brief

A brief says what an item is for and when it is done: a `goal` (one sentence of
what is different afterwards), a user `story` {as, want, so_that} when one fits,
and two to five `acceptance` criteria, checkable outcomes rather than steps (a
stream has none). Its shape and limits are `card_fields.py`; a task keeps it in
the `brief:` block of its STATUS.md (`task.py brief`), an inbox item in its
`describe` event (`inbox.py describe`).

The small model writes it (service `cockpit-describe` in
`workflow/ai-services/`, default `haiku` resolved to its full id; one call
without tools, settings or session, a fixed JSON schema with the limits of a
brief). The model may think before it answers, at the effort
`cockpit.describe.effort` names (`--effort`, `low`, `medium` or `high`,
default `medium`). One call at `medium` on 2026-10-26 thought for about 2500 of
its 2900 output tokens and cost about $0.002, so 20 calls an hour cost near
$0.04. The
item goes in as data: a few frontmatter fields, its heading, the start of the
body, its two last sections and its open inbox items, about 6000 characters.
`by` names the model that answered as `modelUsage` reports it; another one than
asked for is flagged as `model_mismatch`.

The model keeps a brief up to date by itself as long as no person changed it.
Once a person did, it only proposes: describe_apply takes a proposal over, as
it is or as the person changed it (`edited: true`), describe_discard drops it.
A brief changed by hand in the file counts as a person's too: `.bridge/describe.json`
keeps the hash of each brief as describe wrote it, and the next pass marks a
changed one `edited: true` without a model call. A brief is stale when its
`basis` is no longer the item's text. That file is kept per machine, while
STATUS.md travels through git: on another machine or in a fresh clone a brief
describe wrote has no hash, so it counts as a person's (the model only
proposes for it, and a hand edit of it is not marked). What the gate left out
of a brief it still wrote (a text over its limit, fewer than two criteria for
a task) is kept as the card's `warnings`.

**References.** A criterion has to make sense from the card alone, so the data
carries `references`: what a reader can reach from the item
(`scripts/lib/bridge_cockpit/brief_refs.py`). That is the repository the task is
bound to (`sync.github.repo`, else its context's `sync.defaults.github.repo` or
`repos[].github`), its issues as `owner/repo#n` and its board, URLs and
`owner/repo#n` of the text, a bare `#n` of the text written as `owner/repo#n`
when exactly one repository is known ("Board #18" is a board, never an issue),
paths the text names that exist, the files of the task folder, and the slugs of
other tasks that exist; for an inbox item its detail, its `closes_when` probe and
its task. At most 24, scrubbed like the rest; one the scrub changes is left out.
The rules say: cite only from that list, exactly as written; never a bare `#n`,
never "the list" or "the report §6" without saying what and where; when the text
names something only vaguely, describe it in words; and when a criterion is
about a listed reference (the epic the task is bound to), cite it exactly, so
the card can link it. After the answer every
reference the brief names is checked against the list. One that does not resolve
(a bare `#n` with no or two repositories, a section such as §6 without a place
beside it, a path that does not exist, an issue number the text never names)
does not stop the write, since a brief with a goal beats none: it is kept in
`warnings` ("Unresolved reference: §6", in the cockpit's language), the card
shows the gap "points at something that cannot be found", and with
`auto: stale` the brief counts as stale for one more try of the pass on this
text, never more. A section of a law ("§ 14 UStG", "§ 3 Abs. 2"), words such as
"Soll/Ist/Delta", tool names such as "Node.js", a plain word in backticks and a
colour such as "#a1b2c3" are no references. What is reachable is read with the
item, again once its STATUS.md, its folder or a folder right inside it changed,
so a file made later in the folder is found.

**Prompt version.** describe.json stores the version of the rules
(`PROMPT_VERSION` in `describe.py`) with every brief describe writes. A brief
describe wrote from an older version (or before there was one) that nobody
changed counts as stale, so `auto: stale` writes it again within the budget of
the hour. A person's brief is never rewritten for it. The view's `stale_why`
says which reason holds: `basis` (the text moved on), `prompt` or `refs`.

"Describe" on a card (`describe_run {key}`) asks for one item now. With

```yaml
cockpit:
  describe:
    auto: missing        # or stale
    budget_per_hour: 20
    effort: medium       # low, medium or high
```

a pass of the server every ten minutes takes the items without a brief (and,
with `stale`, the stale ones), proposes at most once per text for a brief a
person wrote, does not ask again for a text whose answer failed, stays within
the calls of the hour (clicks count, but are never refused) and never runs two
calls at once. A card reads `written` (`ai`, `human` or none), `stale`, the
waiting `proposal`, `running`, `last_error`, `stale_why` and `refs` (what the
stored brief names, resolved) from `describe.state_for`.

### One card for every item

Every task, stream and inbox item looks the same wherever it opens: in the
middle column, in the drawer of the Inbox and Tasks pages and in the files view.
It has one title there (a task's H1, never its headline), and under it, each
only when the item has it:

- the **goal**, set apart and first: what is different once it is done;
- the **user story** as one sentence ("As a reader of the docs, I want one
  index of every page, so that I never search the folder");
- the **acceptance criteria** as a short list to read. They are not ticked: the
  steps checklist of STATUS.md stays the only thing to tick;
- the **next step** with who takes it and by when;
- chips for the state, the owner, the priority, the due day, the area and the
  source, the progress of the steps (2 of 5), and quiet hints for what is
  missing: no goal yet, a placeholder step, no next step, an entry about a task
  that is closed already (with "Close this entry" beside it; there is no verb
  that moves an inbox entry to another task, so the card offers no "reassign"),
  a brief that points at something that cannot be found.

Where the goal or a criterion names a reference, it is a link: an issue,
pull request or URL opens on GitHub or the web in a new tab, a task slug opens
the task in the files view, a file of a task folder is read in place under the
brief (as the Files drawer reads it), and any other path shows as code with a
copy button. A reference nobody can reach stays text, with a quiet "not found"
on hover and for a screen reader. The parts come from the card's `brief_refs`.

A check or an info row shows only what it has, so it stays small. A list row
shows the card's title. Its goal stands under the title on the start page, and
on Today in place of a missing triage gist. A detail head leaves out the chips
its facts list says further down (a task's status and priority, an inbox
item's state and due day).

Text a model wrote and no person edited carries a small **AI**; the model and
the day show on hover and are its label for a screen reader. Once the item changed past it, **outdated** stands
beside it, saying why on hover: the item changed, an older version of the rules
wrote it, or it names something that cannot be found and is tried once more.

**Describe with AI** on a task, stream or inbox item asks the small model for
its goal, story and criteria now. While no person edited the brief, it is
written straight into the item. Once a person did, the model only proposes: the
proposal shows in the card with **Apply**, **Edit** and **Discard**. Edit
opens a small form (the goal, the three parts of the story, up to five
criteria) and saves what you wrote as your own text; nothing changes in the
item before Apply or Save. A newer proposal replaces an open form. After Apply
or Discard the focus goes back to Describe with AI. Only one describe runs at a
time, so while one runs, the button waits on every card. A failed try shows like
any other failed action.

A command row that offers steps of its own (`actions`, docs/briefings.md) shows
an "Action" menu: two clicks run one through `row_action {page, section, index,
action}`, which calls `briefing.py act` and voids the section's cache. A step
whose command returned an undo token is in the history and in the toast with
"take back" (`row_undo {section, row, action}`), the same way as a close.

### The chat as cmux

With `cockpit.chat_layout: workspaces` the Chat tab is laid out like the terminal you work in.

- **On top of the left side** stands a switch between two areas, "Work" and
  "A2A (n)", where n is the number of A2A peers. Work is everything below; A2A
  lists the agents as cards (reach dot, held answers, when the last call was) and
  shows the picked agent's conversation on the right, with its bar, its card and
  its box, as the A2A connections tab does in the classic chat. The choice is kept
  in this browser (`bridge-cockpit.chatArea`). Without a peer there is no switch
  and the Chat shows Work. There is then no A2A connections tab: every way to an
  agent (a toast "an agent answered", the band's "agent not reachable", an agent
  on the start page, a stored page) opens the Chat on its A2A area with that agent
  or conversation picked. The way back works the same: a tab, a workspace, a chat or
  a Bridge picked from anywhere (Work through, the start page's waiting tabs) opens
  the Chat on Work, even when it was left on A2A. So the signal is not lost with
  the tab, the Chat tab and the A2A switch wear it: a spinner while an agent
  answers, a dot while an answer is held for its owner.
- **In Work, on top**, "Waiting for you" lists the tabs that wait for
  you or need you, the most urgent first (the control tab never), each with its
  workspace, its question and the answers, see [Answering a tab from
  here](#answering-a-tab-from-here). A click anywhere in a row opens its tab on
  the right; a click on one of its answers or its text field does only that. A
  tab that has been in one state unusually long (`long`: working for an hour, or
  a filed result waiting a long time) stands there too, without a question and
  without answer buttons, so it is not forgotten. While the pointer or the focus
  is in the group its rows keep their order, and a tab that starts asking is
  added at the end; the sorted order comes back when the pointer leaves, so a
  click never lands on a row that was pushed under it.
- **Below it** stand the workspaces in the terminal's order, pinned ones first.
  Each shows its colour, its state, its unread count and, when its folder is
  another Bridge's clone, that Bridge's name. Below each workspace are its tabs,
  most urgent first. The quick chats sit in the control workspace
  (`workplace.control`), the newest six and "all" for the rest.
- **Below the workspaces** come the other Bridges on this machine that have no
  workspace ("Bridges on this machine"). The A2A agents stand in their own area.
- **On the right** is what you picked:
  - a tab's terminal, read every 1.5 s to 5 s (slower while it stays the same),
    with "Write" to open it in its window with the message box and keys;
  - a quick chat with its box. The box is one input: a chip under it says where
    Enter goes, "Asks here, read only" or "Starts an agent tab". The guess reads
    the first words: a trailing `?` or a question word (what, how, which, ... /
    was, wie, welche, ...) asks, an order word (fix, create, set up, ... / mach,
    erstelle, leg an, ...) starts a tab, anything unclear asks. A leading `?` or
    `!` decides it and is dropped from the text. A click on the chip picks the
    other route and holds it until the box is empty again, however the guess
    changes while you type on. Cmd or Ctrl Enter starts a tab at once, whatever
    the chip says. Once the chat is handed on, the chip gives way to a status
    line (see [5. Asking Claude](#5-asking-claude-the-relay)). There is no
    countdown and no timer;
  - an agent with its conversations;
  - a Bridge's folder and how to work in it.

**Chats leave on their own.** A chat started from a briefing row or handed to a
tab leaves when its item closes, once it has been quiet for 10 minutes. The chat
keeps what it is about (`about`: the row, and the inbox item or task behind it,
or the inbox item it was handed on as). On the tab poll, at most once a minute
and at once after a verb that closes, drops or reopens an item, the cockpit
looks whether that item has ended after the chat started: an inbox item closed,
executed, dropped or rejected and not reopened since, or a task moved to
`work/done/`. Such a chat goes to the archive with `why: settled`. Never one
that is still answering, one without an item (a free question), one that was
touched in the last 10 minutes, or one whose item was closed before the chat
began or at a time its event does not name. A chat that changes while the files
are read stays. When the archive cannot be written the chat stays, and the next
try comes an hour later. A2A conversations follow `chat_keep_hours` like the
quick chats, except one still sending or one whose task waits for the other
Bridge's owner.

The workspaces come from the terminal driver's optional verb `workspaces` (cmux:
`workspace list`, `sidebar-state`, `list-notifications`, all read only), asked
with each tab poll. A driver without the verb still shows the workspaces,
grouped from the tabs.

**What works where.** A tab and a workspace show a small count when something
runs in them: the subagents with one icon, the workflows with another, and in
the tooltip the busy sessions too. Three numbers count:

- a session that is busy;
- a subagent whose transcript changed within the last 120 s;
- a workflow that is not paused.

The counts come from the Sessions scan, which reads every Claude session on this
machine. A session is joined to its tab by the tab's id and to its workspace by
the workspace ref (`ws_ref`, carried on the session's tab), so two workspaces
with the same title never share a count. A session that sits in no tab of this
Bridge (another folder, another Bridge here) counts nowhere in the sidebar; the
header names it only in its tooltip ("elsewhere on this machine"). The header
chip ("3 working · 5 subagents · 2 workflows") adds up this Bridge's tabs and
opens the Sessions page on a click.

**Order.** Three ways, picked at the top of the sidebar and kept in this
browser. "Terminal order" keeps the terminal's order. "Most urgent first" orders
the workspaces by their most urgent tab (needs you, waiting, working), then
pinned, then the terminal's order, then the title; a workspace with only shells
or no tabs comes last, and the control tab does not count. "By status" drops the
workspaces and lists every tab under its status, so you can walk them top to
bottom: "Needs you", "Done, answer or close", "Working", "Terminal", each with
its count, and inside each the tab that has been in that state longest first;
each row names its workspace. The control session and the quick chats stand
below. "Waiting for you" is left out in this order, since its tabs head the
first two groups.

**Working through the tabs.** "Work through (n)" beside the order choice (in
every order) opens the first tab that needs you or waits, in the order By status
lists them; a tab picked in the sidebar starts the walk there. At the foot of
the open tab stands the same bar the lists have under a detail: back, "2 of 5",
the next tab with its workspace and Next, the two after it as links (keys `n`
and `p` on the Chat page, when shortcuts are on). An answer that reached the
tab, or "Close tab" in its head (for a tab that waits or is a bare terminal),
goes on to the next tab by itself, as settling an entry does in the lists. The
walk keeps the order it began with: a tab answered meanwhile keeps its place
while it is open, a closed one drops out, and a tab that starts waiting later
comes at the end. A tab that changes its status starts its time again, so it
goes last in its new group. While the pointer or the keyboard focus is inside
the sidebar the order holds still, so a row never moves away under the hand;
counts and states still update, and the new order applies when the pointer
leaves. Only a click on the toggle itself reorders at once, since that change is
the one the hand asked for.

The other Bridges are the entries in `infra/instances/` that meet four conditions:

- `relationship` is `sibling` or `downstream`;
- they are not `read-only-from-here`;
- they are not `dormant` or `archived`;
- one of `location.path`, `location.mac_clone` or `location.local_clone` exists as a folder here.

Only the registry and that the folder exists are read, nothing inside the other
Bridge (`rules/multi-instance-isolation.md`).

**Renaming.** A tab or a workspace of your own gets a new name from here: the
pencil beside its title on the right, or a double click on it in the sidebar,
puts a field in its place in the sidebar (Enter or Save takes it, Esc or Cancel
keeps the old one, an empty name is not taken). The terminal driver renames it
(`workplace.py rename` and `rename-workspace`; renaming a workspace needs the
driver's optional verb `rename_workspace`, without it no pencil shows). The
cockpit refuses, and says why:

- the control session, and the control workspace;
- a tab of a task, an inbox item or a team role: the workplace knows it by that
  name, so it keeps it;
- an agent tab whose state the terminal reads off its title glyph (cmux without
  a hook): with a name of its own it would read as a shell from then on;
- a name another tab or workspace already has, a configured workspace
  (`workplace.workspaces`) and the name of one, an empty name and one over 80
  characters. A name is refused, never cut.

The audit line names the tab or workspace ref only, never the name. With the
workspace list on, a renamed workspace is read again at the next poll.

**Organize with AI.** "Organize with AI" in the head of the sidebar (shown when
the driver renames tabs) asks the model once for a tidier order: shorter names
for tabs and workspaces, which tab belongs in which workspace, a colour and a
one-line description per workspace. It is one call without tools, settings or
session, Haiku unless `workflow/ai-services/cockpit-organize.yaml` picks another
Claude model (Codex is not offered). The proposal comes back grouped by
workspace, each item with its old value struck through, the new one and why;
nothing is ticked, and nothing changes until you tick items and press "Apply".
Afterwards it lists what was applied, what was skipped because it changed
meanwhile, and what failed.

- **This Bridge only.** The model sees only the workspaces whose folder lies in
  this Bridge or in a repo it registers (`ecosystem*.yaml`), by the longest
  matching folder, so a workspace in another Bridge's clone stays out, and only
  their tabs; never the control session or its workspace. It reads titles, task
  slugs, states, 90 characters of a tab's last line, 200 of its question and the
  last two folder names, all scrubbed: no screen, no full path (a home folder in
  a name or a line is shown as `~`), no key.
- **Left alone.** Tabs of a task, an inbox item or a team role keep their names
  and their places (the plan moves them back), configured workspaces
  (`workplace.workspaces`) keep name, colour and description, a name that is
  managed or in use is never proposed, an agent tab whose state is read off its
  title glyph is not renamed, and the last tab of a workspace is never moved.
  Items the driver cannot carry out (`move_tab`, `set_color`, `set_description`
  are optional verbs; tmux has no colours or descriptions) are not offered.
  Reordering workspaces is not part of it.
- One proposal at a time, kept for 15 minutes in memory; the audit log gets counts only.

#### Answering a tab from here

A tab that waits shows what it asks, read off its screen, so it can be answered without opening it:

- **A dialog** (needs you) shows one button per option it offers, labelled with
  that option's own words ("Yes", "Yes, allow all edits during this session",
  "No, keep planning"), and the button presses that option's number. "Yes" is
  never a bare "press 1" on a choice or a plan approval. A dialog takes no free
  text from here; "Open tab" goes to the tab. A dialog that could not be read (a
  driver without `screen`, a screen that reads as nothing) offers "Open tab" and
  the plain Yes and No.
- **A tab that waits** with a yes or no question (its last words end with `?`)
  shows Yes and No, which type those words. Every waiting tab offers "Go on"
  (not when its result is filed) and a field to type an answer, behind one click
  in the sidebar.
- **What a tab asks** is read by the tab poll through the driver's optional verb
  `screen`: only for the tabs that wait or need you, again only when a tab's
  state, last line or since-time changed or its question is a minute old, at
  most four screens and three seconds per poll, the tabs that need you first. A
  poll without such a tab asks the driver nothing. The question goes out with
  the tabs (`tabs.tabs[].ask`: text, options, a hash, whether it reads as yes or
  no, whether something is typed in the tab) and never rebuilds the briefing.
- **After an answer** the row stays where it stood for one more poll, greyed,
  with what was answered, or "Moved on" when the tab went on by itself, so a
  click never lands on the row that slid up into its place. The tab's pane on
  the right and its window show the same question and buttons.

#### The decision guide

Off until `cockpit.session_guide.enabled` (or the switch under Settings,
"Decision guide") turns it on. Then a tab that waits for you gets a short
reading by Claude Haiku: what the session is about, where it stands, what
exactly it waits for, and two to four next steps, the recommended one marked.
The page draws that as a small tree, the reading on the left and one branch per
step on the right. A click on a branch never sends: it puts the step's words in
a box under the tree, where they can be read and edited, and Send types them
into the tab (a dialog's step: Press presses its number). Cancel or a second
click on the branch leaves it. Cmd or Ctrl Enter in the box sends as well.

- **What it is about** heads the reading: one line Haiku writes from the
  session's first ask, its title, the task it belongs to and the latest turns,
  so a tab named only "Claude Code" is recognised at a glance. Beside it stand
  the session's folder and its task's headline (a task tab's own, or the task
  linked on the Sessions page); the ask the session was started with shows on
  hover. While Haiku still reads, the session's title, its task's headline or
  its first ask stand in. The sidebar and the session cards show this line
  first, then where the session stands.
- **A waiting tab**: each step carries the words it types into the tab, shown
  under it ("Sends: ..."). The click goes through `tab_send` with the question's
  hash, the tab's state and its name, so it reaches the tab only while it still
  asks what was read (the same guard as the answers above).
- **A dialog** (needs you): each step names one of the dialog's own numbered
  options and presses it through `tab_option`; Haiku cannot add an option the
  dialog does not show.
- **A step that reaches beyond the session** (push, merge, delete, deploy, send,
  publish and their German words in the words it sends, not where they are
  negated as in "commit, but do not push", or one Haiku marks so) is marked, and
  its box says so before it is sent. The last branch, "Answer yourself", opens
  an empty box (on a dialog, which takes no words, it opens the tab).
- **Into the session**: beside every reading, "To tab" makes the terminal jump
  to the tab (driver verb `focus`), "Watch" opens the tab's live screen with its
  message box here, and "What was read" unfolds what Haiku read: the ask the
  session was started with, the ask before the last, the last ask and the
  agent's words after it (drawn as text from Markdown), or the end of the
  screen.
- **In the chat as cmux** a switch in the tab pane's head picks what a waiting
  tab shows: "Reading" (the reading takes the pane), "Both" (the reading above
  the terminal, scrolling in a row of its own; the default) or "Terminal" (the
  question off the screen and the terminal, as without the guide). The sidebar's
  "Waiting for you" follows it: with "Terminal" its rows show the screen's
  words. The choice is kept in this browser.
- **Where it shows**: in the chat as cmux, the reading's first sentence under
  each row of "Waiting for you" and the whole tree in a tab's pane on the right;
  in the classic chat, the sentence on a slim tab card and the tree once "more"
  opens it; on the Sessions page, "Where you are needed" on top lists every
  waiting tab with its tree (a tab whose result is filed stays out, "With AI"
  offers it), and each session card carries the sentence.
- **When it reads**: with `auto` (the default once on) a tab is read as soon as
  it waits with a question the tab poll has read and no reading answers yet, at
  most `per_hour` such readings an hour (30 by default); never the control tab,
  never a tab whose result is filed. "Read with Haiku" and "Read again" read any
  waiting tab at once and do not count. One reading runs at a time. A reading
  made for another question than the tab asks now shows greyed as stale, without
  steps; a failed one says why and is not retried by itself.
- **What Haiku reads**: the session's transcript
  (`~/.claude/projects/<folder>/<session id>.jsonl`, found through the Sessions
  scan), of which only the session's title, its first ask, the last ask, the one
  before it and the agent's words after the last ask are kept, plus the headline
  of the task it belongs to: no tool calls, tool output, thinking, reminders,
  meta lines or subagents, at most about 5000 characters. A tab without a
  transcript gives the end of its screen instead. The cockpit's key is taken out
  before and after. The call is one `claude -p` with Haiku, no tools, no
  settings, no session (`model_route.haiku_argv`). The footer names the source,
  the cost and the age of the reading.

| Key | Default | What |
|---|---|---|
| `session_guide.enabled` | `false` | the guide at all |
| `session_guide.auto` | `true` | read a tab by itself when it starts waiting with a new question; `false`: only on the button |
| `session_guide.per_hour` | `30` | the most readings `auto` starts in an hour (1 to 1000) |

The settings page switches `enabled` and `auto` on top of the config, kept in
`.bridge/cockpit/guide.json`, with its own "Reset to config".

### The first-run tour

The first time the page opens it offers a short tour, the way other tools introduce
themselves: a welcome with "Start the tour" and "Skip", then one step per area with
that area lit up and the rest dimmed: the tabs on top, Start, Today, the agent tabs
(not on a narrow screen), Ask, Sessions, Help and settings. Next and Back go
through it (also the arrow keys), a step opens the page it shows, and the end goes
back to the page where it began. Skip or `Esc` ends it at any step.

How it ended (finished or skipped, with the date) is kept on the server in
`state.json`, key `tour`, so another browser does not offer it again. Help ("Start
the tour") and Settings, Appearance, Introduction start it again at any time; Settings
can also offer it again on the next visit (verb `tour_reset`). `cockpit.tour:
false` switches the offer off for a Bridge whose people know the page; the buttons
still start it. In mock mode it stays closed unless the link carries `&tour=1`.

### Explain this page

"Explain" in the header (the bulb; also in Help) lays notes over the page as it
stands: each area the page shows gets a numbered note beside it, a ring around it
(an ellipse for a button or a chip, a frame for a row or a column) and an arrow from
the note to the ring. Every page explains its own parts: Start, Today, Chat,
Sessions, Background jobs, A2A connections, Tidy up, Jev and Settings each have their
own list, and a page of the briefing profile explains the parts it is built from
(the count beside its title, the overview tiles, the sorting bars, a section's
head, its rows, the GitHub figures and boards, the quota gauges, the costs, the
dates). The notes come in rounds so none covers another: the page first, the header
(views, As of, Reload, Ask, History, Claude, Notes, Help) in a round of its own after
it, read from left to right. Next, Back and the arrow keys page through the rounds,
and the bar says which round shows and how many areas stand further down (scroll,
and they follow). An area the page does not show right now is left out. A click
anywhere or `Esc` closes it, and its bar starts the tour. It sends nothing and keeps
nothing.

### Help

Help (`?` in the header) shows one topic at a time, in tabs: **This page** lists
the same explanations as the notes, for the parts this page shows, and the header
below them; **Rows** says what a row's mark and its section mean; **Acting** covers
the panel, Let AI do it, Advise, Close and Ask; **Keys** has the shortcuts, or how
to switch them on; **Costs and safety** says what spends tokens and what leaves the
machine. Its title row starts the tour and shows the notes on the page.

### Keyboard

The shortcuts are off until switched on under Settings, Appearance, Keyboard
shortcuts (kept in this browser only). Off, no key acts on the page and the
command box is not in the header; `Esc` still closes a dialog or a drawer, and
`Cmd` or `Ctrl` with `Enter` in the panel's sentence still starts. On, when
the focus is not in a text field:

| Key | Action |
|---|---|
| `j` / `k` | next / previous row |
| `Enter` | show the row in the center |
| `x` | select the row |
| `a` `v` `c` `b` `w` | Let AI do it, Advise, Discard, Later (tomorrow), Let AI do it in its own workspace |
| `r` | reload, fresh |
| `/` | the command box |
| `g` then `t` | the agent tabs |
| `g` then `a` | the start page, the focus on its Areas; there `j` / `k` move and `Enter` picks |
| `Esc` | also: on Work, Chat or Sessions with nothing open, show every area again |
| `n` / `p` | the next / previous entry of the walk you are in: a detail opened from a list, the Today list, the Chat page's tabs, the focus on the start page, the Files view |
| `Alt` + `1` to `9` | the page tabs |
| `?` | help |

The row keys (`j` `k` `Enter` `x` and the five letters) act on the Briefing
page only; `n` and `p` act while a detail opened from a list is open (the item
drawer included), on the Today list with a row open in the center, on the
Chat page (where `n` starts the walk through the tabs that want you), on
the start page in the focus view (with `cockpit.focus_to_files`, `n` on its
last step opens the Files view) and in the Files view of the work tab; the others work on every page. A text field keeps every key,
`Alt` + a digit included, because on many keyboards that is how a bracket
or a pipe is typed: leave the field with `Esc` first, for instance after
the Chat page put the cursor in its box.

The command box in the header takes row codes: `3a`, or `1a 4v 6b`, the
number a row shows and the letter of the table above. A row
with a running tab jumps there instead of starting a second one, and `a` or
`w` is refused for an entry only you can do, a row that waits for someone else,
and a yes already given.
A text that starts with `?` is no code but a search: `?gateway september`
opens the work tab on its Files view with what the search found, for this
visit only: the next load opens the work tab on the view it had before. Every
code stays as it was.

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
  close, settle (done or not doing), urgency, priority, note, check tasks, keep
  open, close task, launch, adopt, send, key,
  close tab, snapshot, ticker settings, ticker refresh, ticker edit, ticker
  profile, guide read, guide settings), every id
  checked again before it reaches a script, every argument a separate word,
  texts after `--`;
- the news ticker reads only the feed addresses you wrote into
  `cockpit.ticker.feeds` or saved on the settings page (an address in your
  own network is allowed because you chose it), only over http or https, with
  no user name in the address, at most three redirects, eight seconds and 2 MB
  per feed (a gzip body sent unasked is unpacked to the same 2 MB). A feed
  that declares a DOCTYPE or an entity is refused before it is parsed. The
  server never opens an item's link. Titles are stripped of markup
  and control characters and shown as text; a link becomes an anchor only when
  it is http or https, and opens with `noopener` and no referrer. Feed text
  reaches Claude only as the one prompt of the Editor button, a read-only Haiku
  call with no tools, and what comes back is used only as item numbers and
  short titles. The titles of your open tasks reach Haiku only on the button
  "Written by Haiku", and its answer is shown as text to take or drop;
- the decision guide sends nothing of its own: its buttons are the guarded
  replies `tab_send` and `tab_option`, a dialog step only one of the dialog's
  own numbers, and a step that pushes, merges, deletes, deploys or sends takes
  a second click. What Haiku reads of a session is its last turns without tool
  output or thinking, scrubbed of the cockpit's key, in one call without tools;
  what comes back is shown as text and used only as button labels and the words
  a button types;
- a Markdown answer (Chat, A2A connections) is read into plain objects and drawn
  as elements, never parsed as HTML, so text in an answer cannot become markup
  or script; a link keeps only http, https and mailto and opens with
  `noopener` and no referrer;
- a script runs only from the Bridge's own list (`briefing.py`, `inbox.py`,
  `workplace.py`, `task.py`, `bridge-resources.py`, `triage.py` and the cmux
  layout script). Besides those the server starts only these exact shapes:
  the read-only quick chat (`claude -p` with Read, Grep and Glob), the A2A
  shapes of section 5, `codex exec --sandbox read-only`, the Haiku judge of how
  complex an item is (no tools, no settings, no session), "Organize with AI"
  (one call, no tools, it keeps only tab refs and task slugs from the answer)
  and `/bin/ps eww -o command= -p <pid>` with a pid of digits only, for the
  Sessions page. The cmux CLI is never called directly: whatever the page does
  to an agent tab goes through `workplace.py` and its terminal driver;
- an answer to a tab reaches only the question you saw. It carries the hash
  of that question, the tab's name (unless that name is empty or longer than
  120 characters, which the check does not take) and the state it was in. Before anything is
  sent the server polls the tabs again, refuses when the tab is gone, has
  another name (its ref was given to another tab after a terminal restart) or
  is in another state, then reads the tab's screen fresh (never the poll's
  copy) and refuses when the question there has another hash. A text answer is
  also refused when something is already typed in the tab's prompt, so your
  words never land on half a sentence; that screen read happens for every text
  answer the page sends when the driver serves `screen`, also to a tab with no
  question read (a filed one). A text answer never goes into a dialog, which
  takes only its options (a typed digit would pick one past that check). A
  refusal sends nothing and says so
  ("The tab moved on before the answer, nothing was sent.");
- "Organize with AI" changes only what you ticked, of a proposal that is at
  most 15 minutes old. Before it applies anything the server polls the tabs and
  reads the workspaces again; an item whose value is no longer the one it was
  proposed from is skipped, never forced. Moves go first and the tabs of a
  workspace are counted again before each, so the last tab of a workspace never
  leaves it. A tab that has meanwhile become a task, inbox or team tab is
  skipped too, neither renamed nor moved. Each item goes through its own
  `workplace.py` command (live refs
  only, the driver's verb checked again), outside the write lock so other
  actions are not held up, within two minutes for the whole apply. One apply
  runs at a time; a second one meanwhile is refused. Nothing is closed;
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
  `GET /api/find` is a read: it runs `scripts/work-find.py` through the
  runner's allowlist with the words as one argument after `--`, leaves no
  line, and refuses a query shorter than 2 or longer than 200 characters or
  one with a control character before anything runs.
  `/api/seen` is the page's own measure: opening a page or a view of it
  leaves `page_view`, the page id and `view=` (the work tab's view, the start
  page's view, else `-`), nothing more. The first line waits for the model, so
  a remembered view is measured as what it is.
  Read-only verbs and requests refused before anything happened leave none;
- a question for Claude carries a signature (HMAC-SHA256) made with
  `relay.key`, which lives outside the Bridge in a folder only you can open
  (`~/.local/state/bridge-cockpit/`, or `$BRIDGE_COCKPIT_KEY_DIR`). The session
  submits only questions whose signature checks out, so a program that can
  write files into the repository but cannot read your own files cannot
  hand the control session a prompt. It does not stop a program that runs as
  you: an agent tab can read `relay.key` and the cockpit's `token` like any of
  your files, so the signature keeps out other users and sandboxed tools, not
  your own sessions. The signature covers the question's
  expiry too, so nobody can keep it alive longer. The way back is signed
  with the same key: the session signs its heartbeat and every answer, and
  the server ignores a heartbeat or answer whose signature does not check
  out, so such a program can neither pose as the control session to get
  your questions nor answer in its name. The prompt names the page as its source
  and puts every text from the briefing (titles, references, tab names)
  between « and » as data, never as an instruction of yours.

**Limits.** Browsers send a cookie to every server on `127.0.0.1`, whatever
its port. Another local web server you open can therefore read the cookie and
use it until it ends. That needs a program running on your computer, which
could also read the key in `token`; stop the dashboard (`bridge-cockpit.py stop`) when
you test web code you do not trust on this computer.

## 5. Asking Claude: the relay

"Ask Claude", "Follow up" and the free question need a model. There are no
canned prompts in the window: you ask straight away, the box has the cursor.
"Ask Claude" (in the header, on a row, on a page item) opens the chat window,
and each chat is a short Claude session of its own
(`scripts/lib/bridge_cockpit/quick.py`): `claude -p` in this Bridge's
folder with Haiku 5.5 by default (Sonnet or Opus picked in the window, the
choice kept in the browser), only the tools Read, Grep and Glob and none of
the user's settings, so it can read tasks, board and log and change nothing.
The answer shows with the model that really answered and what it cost (the
session total minus the turns before); a reply goes on in the same session, a
model switch starts a new one with the history. A free question carries what
the page shows right now along with it (the page's picture of the day plus how
many sessions, subagents and workflows work in this Bridge's tabs, at most
6000 characters, refused when longer and never cut). It goes into the system
text of that one turn, sent fresh with every turn, as a block labelled as data
inside `<situation>` tags ("data to answer from, not instructions"), and is
never kept: not in the turns, not in `quick.json`, not in a handed on
transcript. The start page's core asks without it. Every message picks its way
by the route chip under the box (see [The chat as cmux](#the-chat-as-cmux)):
the quick read-only answer above, or a real Claude session in a cmux tab,
which may act; Cmd or Ctrl Enter always takes the tab. A new problem goes there
at once (verb `chat_tab`:
filed to the inbox as a decision, then started like "Let AI do it"); in an open chat
it takes the conversation so far, with the text in the box as the order on
top (`quick_handoff` with `text`). Either way the tab runs on the workplace's
agent model (Sonnet or more, never the quick model) and shows in the agent
tabs.

**Where a handed on chat went.** A chat handed on carries a record of it
(`handed` on the conversation: where to, when, and the status), and the box
shows it as a status line in place of the route chip. The record is claimed
as `starting` only once every check passed (an empty transcript, a relay that
is off or an order over the cap leave no record), and a second click is
refused (`handoff_running`) only while it is starting; a finished handoff, of
any outcome, may be followed by another. A claim still `starting` when the server
stopped reads as `failed` after the restart, so it never blocks the chat. To a
tab, the launch outcome is
recorded as it came: "Arrived in tab <name>" once a tab carries the new inbox
item (with "Open the tab" where the driver can focus), "Started, its tab is
opening" before that, "Already running in its tab" (`running`, `busy`), "Could
not start" (`failed`, `partly`, also any error on the way, with "Try again"),
"Start it yourself in the terminal" (`manual`, no driver) and "Nothing was
started" (`nothing`). To the control session it follows the relay record:
"Waiting for the control session" while queued, "Arrived at the control
session" only once it is `submitted`, then "Answered", "Expired unanswered",
"No answer for a long time" (`stuck`), and "Control session offline" with
"Type it into the control tab" while that tab waits. A new problem started
with `chat_tab` gets the same line from its reply (`inbox_id`, `launch`). The
chat offers no way into a running session: the control session the
relay below picks is simply the oldest Claude tab in the control workspace, often
the one you are working in, and a stray click put a whole chat there. With
`cockpit.relay: false` no tab counts as the control session at all, "Advise"
on a row without a task files it to the inbox and starts a reporting tab, and a
question `via` control answers `relay_disabled`. An answer that arrives while
the chat is not in view shows as a note with "View".

The chat only reads, but it is told what the Bridge can do: its system text
names the "Let AI do it" button and says to point there when something needs
doing, never that the Bridge cannot act, and never to hand the person a list of
steps an agent could do. When no terminal driver serves `launch`, it says so
instead and names `workplace.driver`. Asked to remind, it ends the answer with
a line `[[remind: YYYY-MM-DD | what]]` (or `[[remind: what]]` for now); the
page turns that line into a card, and its button files the reminder (verb
`chat_remind`: a free inbox item, kept out of sight until the day like
"Later"). The model never writes it itself: the click does.

The answer streams: the CLI runs with `--output-format stream-json --verbose
--include-partial-messages`, and the new text plus the file it is reading
reach the page as the `quick_live` event, at most every 0.3 s. An event
carries only the text added since the one before (`at` says where it goes,
`seq` orders them); a new message in the stream comes whole (`full`), and so
does the `quick_live` key of the state a page gets when it connects, so a page
that reconnects mid-answer still shows all of it. The page keeps the live text
in a small store of its own: a piece re-renders the chat, not the page, and a
hidden tab skips the page's clock ticks until it is in view again. Chats are kept
in the state dir (`quick.json`, the last 30), so a chat goes on after a
restart of the dashboard; one that was answering when it stopped says so.
No chat is ever dropped: the 31st pushes the oldest, a chat untouched for
`chat_keep_hours` (a day by default) leaves on the next look at the list, and
"remove chat" (or the × beside a chat in the sidebar of the chat as cmux) takes
one, into the archive `chats/quick-YYYY-MM.jsonl` in the state dir (one line
per chat, whole, with `why`: `overflow`, `expired`, `replaced` or `removed`; A2A
conversations go to `chats/agents-YYYY-MM.jsonl`, `expired` past
`chat_keep_hours` like a chat, unless
one still sends or waits for the peer's owner; a chat about an item also leaves as `settled`, see
[The chat as cmux](#the-chat-as-cmux)). When the archive cannot be
written, the chat stays in its list, and an expiry is tried again an hour later.
An open page hides an expired chat at once (`keep_hours` in the `quick` and the `agents` state),
before the server has archived it. Deleting for good means deleting that file by hand. The
Chat tab lists every kept chat (first question, when, model, cost) and opens
one with its box ready; "As a tab" in the window moves the open chat there.

**Markdown answers.** An answer in the Chat and an answer from another Bridge
on the A2A connections tab show as formatted text: headings, paragraphs, lists
(nested, numbered, ticked), code blocks, quotes, tables, bold, italic, strike,
inline code and links. A link becomes clickable only when it is http, https
or mailto; any other address stays plain text. Raw HTML in an answer is never
markup, it shows as the characters it is (`scripts/web/markdown.js`, drawn by
`views/prose.js`).

**A2A connections** (`scripts/lib/bridge_cockpit/agents.py`). Where `infra/a2a-peers/` holds
a peer, the A2A connections tab lists each with what its public agent card says (name,
skills, protocol version; fetched in the background, kept five minutes, never a
token) and opens a conversation with it. A message goes out only on a click,
as a question (as typed) or a task (wrapped with what is expected back),
through `skills/a2a/scripts/a2a.py ask --json --wait 90`, which resolves the
peer's token itself; the runner lets through only that shape and `get`. A
follow up continues the peer's A2A context. A peer that holds a task for its
owner's approval answers with a state that is not final: the turn shows as
held, the tab wears a dot, and "look again" reads the task with `a2a.py get`
without sending anything new. Conversations are kept in `agents.json` in the
state dir, and one that leaves the list goes to the archive (see the Chat).
Without a peer there is no tab. With `chat_layout: workspaces` there is no tab
either: the same page stands in the Chat as its A2A area (see [The chat as
cmux](#the-chat-as-cmux)). The quick chat's system text names
`infra/a2a-peers/` too, so it can suggest asking an agent; it sends nothing
itself.

**Peers from a script** (`cockpit.a2a_sources`). Some agents are not reached by
a public card and a bearer: they sit behind an access proxy or a broker, and
`skills/a2a` cannot speak to them. A skill that can names its script in
`cockpit.a2a_sources`, and its peers join the list beside the peer files, with
"through <name>" under access. The cockpit calls that script only in four
shapes and reads the last JSON line it prints:

| Call | Answer |
|---|---|
| `peers --json` | `{"peers": [{"id", "summary"?, "owner"?}, ...]}` |
| `card --json <peer>` | `{"card": {<agent card>}}` |
| `ask --json --wait 90 [--context <id>] <peer> -- <text>` | as `a2a.py ask --json` |
| `get --json <peer> <task>` | as `a2a.py get --json` |

The script is a skill of the Bridge, so it is found under `--root`, also for a
cockpit run from another checkout. It keeps its credentials to itself; nothing it is given or prints
carries one, and the card summary keeps only scheme names. The list of peers is
read again every five minutes or on "check again", and a source that fails
keeps its last list. A peer file of the same name wins over a source's peer.

**The agent bar.** Above the conversation stands the chosen agent: its name,
the dot of its last check, and what failed (card not readable, last message not
delivered), so a failure shows with the card folded away. Every agent in the
list carries its own "Show card" button, and the bar carries one too: it picks
that agent and opens its card. The card opens by itself while no conversation
is open, and folds under one.

**When a card or a message fails.** An agent whose card cannot be read, or
whose last message did not go out, says so in plain words instead of the raw
error: which step failed (the card, or the last message), the reason (the
address does not resolve, which on a tailnet usually means this machine is not
in the owner's tailnet; nothing answers; the token is refused; no card at that
address; a fault on the far side; not a card; the token is not set up here),
and what to do about it, with the raw text folded away under "Detail". Without
a card the profile still shows what the peer file knows: its summary, the card
address, how it is reached and who owns it. "Check again" fetches every card
anew, also one inside its five minutes (`/api/agents?fresh=1`); the line beside
it says when the card was last checked.

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

Everything lives under `.bridge/cockpit/` in the Bridge root, which git ignores.
The last column says whether a file holds inbox, task or chat text (titles,
gists, questions, answers): those are the files to think of when you back up,
share or clean up.

| File | What | Inbox or chat text |
|---|---|---|
| `token` | the key, kept across restarts until `new-token` (readable by you only) | no |
| `server.json` | the running server: pid, port, version, never the key (readable by you only) | no |
| `server.log` | errors, dated, never a key, cookie or request body; kept to one backup (`server.log.1`) | no |
| `stdout.log` | what the process itself prints: the dated line of each start, and a crash before the server is up | no |
| `audit.log` | one line per write action, question, route, Jev request and triage run | no: ids and counts only, though an inbox id carries a slug of its title |
| `history.json` | what was closed, dropped, settled or hid, with its undo (readable by you only) | yes: the titles |
| `state.json` | rows hidden on the page, rows marked done or not doing, team runs started from the page, the start page's tiles and pins, how the first-run tour ended, the workflow runs marked as checked | yes: the title of each row marked done or not doing |
| `view.json` | the last briefing, shown at once on the next start until a fresh one arrives | yes: the whole briefing |
| `days.json` | the day book: each quota's use per day and the counts of each day (section 3), two weeks | no: numbers under ids |
| `launches.json` | the starts of the last days for the return channel, with model, effort and who chose them | yes: the titles |
| `launch.json` | the settings page's changes to `cockpit.launch_model` (only keys that differ from the config) | no |
| `ticker.json` | the settings page's changes to `cockpit.ticker` (only keys that differ from the config) | no |
| `guide.json` | the settings page's switches of `cockpit.session_guide` (only those that differ from the config) | no |
| `ticker-cache.json` | the news ticker's last feed items, each feed's state and the last editor result, shown at once on the next start | no: news items only |
| `quick.json` | the chats, the last 30, with every question and answer (readable by you only) | yes: the chats |
| `chats/` | every chat and agent conversation that left its list, whole, one file a month (`quick-YYYY-MM.jsonl`, `agents-YYYY-MM.jsonl`), never deleted (folder and files readable by you only) | yes: the chats |
| `agents.json` | the conversations with other Bridges and A2A agents (readable by you only) | yes: the conversations |
| `jev.json` | Jev's last rating and today's token total | yes: the titles it rated |
| `jev-pages.json` | Jev's order per page | yes: the titles |
| `relay/inbox/` | questions for a session (written by the server) | yes: the questions |
| `relay/done/` | what became of each (written by that session) | yes: the answers |
| `relay/heartbeat/` | one file per Claude Code session with the relay on | no |

Beside it in `.bridge/`, written by the scripts the cockpit runs and read by
the cockpit (git ignores them too):

| File | What | Inbox or chat text |
|---|---|---|
| `.bridge/triage.json` | the last triage run (`scripts/triage.py`): per task and inbox item a gist, a verdict and who does it | yes: titles and gists |
| `.bridge/describe.json` | describe (`describe.py`): per item the hash of the brief as it was written, the waiting proposal, the last error and cost, and the calls of the last hour (the budget) | yes: proposed goals and criteria |
| `.bridge/task-review.json` | the last task check (`task.py review`): per task a verdict and its reason | yes: task titles and reasons |
| `.bridge/resources/workers-view.json` | the full worker view of the Resources section (`scripts/bridge-resources.py workers`) | no |
| `.bridge/resources/costs-view.json` | the last cloud cost report with its source, read time and age (`scripts/bridge-resources.py costs`) | no |
| `.bridge/resources/usage-days.json` | the token counts of each closed day per source, model, project and Bridge, 120 days | no: numbers under model, project and Bridge names |

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
token use, the machines and accounts of an overview page) and the `view.pages`.
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

The Files view calls an open or closed task a file ("File", "Files", "Next
step", "Search the files"); in German the page says "Akte" and "Akten". Like
every word of the page itself they come from the page's own table in both
languages (`scripts/web/text.js`), not from the profile.

Opening a `file://` link on the page is not possible; the page shows its path
to copy.

## 9. When something is off

| You see | Why, and what to do |
|---|---|
| the page says to open it with the link from `bridge-cockpit.py url` | first visit in this browser, the cookie is gone or older than three days, or `new-token` made a new key: run `python3 scripts/bridge-cockpit.py url` and open that link within a minute, or `/cockpit` |
| the bare address does not answer | the server is not running: `python3 scripts/bridge-cockpit.py start`, or `autostart on` so it runs from login |
| `/cockpit` is an unknown command | the session does not run in the Bridge root, or `skills/cockpit` is missing in this Bridge; `python3 scripts/bridge-cockpit.py open` works from any terminal |
| `/cockpit` or `open` says the cockpit is off | `cockpit.enabled` is not `true` or the `cockpit:` block has an invalid value |
| `status` prints `warning:` lines, or the settings page shows a box "The config has keys the cockpit does not use as written" | the `cockpit:` block has a key the cockpit does not know (a typo such as `tab_seconds`) or a value it cannot use (`open_in: browser`); the cockpit runs with the fallback each line names. Fix the key in `bridge-config.yaml` and restart (`stop`, then `open`). Only a bad `port` stops the start |
| the port is taken | another program uses it: set `cockpit.port`, then open again |
| the server did not come up | read `.bridge/cockpit/stdout.log`, then `server.log` |
| relay offline: "no heartbeat" | no Claude Code session with the `cockpit-relay` mod runs here (section 1, `claude plugin list`), `cockpit.relay` is `false`, or the session started before you switched the cockpit on: start a new Claude Code session (`/reload-plugins` reads the config again only when the mod itself changed). A session that still runs a mod from before a pull may write heartbeats the server cannot verify (the mod signs them since version 0.2.0): run `/reload-plugins` there |
| relay offline: "no control" or "ambiguous" | several sessions run and none is the control tab: open the control workspace (`workplace.control.name`) in your terminal, or keep one session |
| a question stays "stuck" | the control session waits for a permission prompt or a long turn; answer it there |
| a question is "rejected" | its signature did not check out: it was not written by this server, or `relay.key` changed since; ask again |
| the header says "connection lost" | the server stopped or restarted; the rows shown no longer update: `python3 scripts/bridge-cockpit.py open` |
| a section reads "cannot run on this machine: ..." | the source is missing here (a calendar without icalBuddy, for one): "Let AI do it" beside it files the reason and starts an agent tab that fixes it. "arrives with the full briefing" instead means only that this pass left it out |
| "Let AI do it" answers "Not started: agent tabs need a connected terminal" | no driver is set in `workplace.driver`: nothing started, and the message's "Copy command" puts the commands for a terminal of your own on the clipboard |
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
