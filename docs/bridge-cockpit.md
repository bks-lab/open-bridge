---
summary: "The Bridge cockpit, a local web page that watches and steers the whole Bridge: switch it on in bridge-config.yaml (cockpit:), open it with /cockpit or scripts/bridge-cockpit.py, decide rows, steer agent tabs and ask Claude or Codex from the browser. Covers the three columns, the Files tab, the news ticker, the status pages and their folders, the task check, the GitHub filters, a page's search over every day before with Ask AI, the keyboard, the safety model, the Setup page, the relay mod cockpit-relay, the files under .bridge/cockpit/, how to build the briefing profile it shows, and what to do when something is off."
type: guide
last_updated: 2026-10-29
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
| `chat_keep_hours` | `24` | quick chats and A2A agent conversations untouched this long go to the archive (below); a chat handed to a tab stays this long after the latest of its handoff, its result and its item's end; 0 keeps them, then only the limit of 30 applies. An empty chat names the time it keeps a question ("Questions stay in the list for 7 days" with `168`) |
| `work_view` | `due` | the view the work tab opens on: `due`, `source` (By source), `jev` (By Jev) or `flow` (Work through, with `flow.enabled`); a view the tab does not offer opens Work through where the tab offers it, else the first view kept. `files` names no view of the work tab any more: the first visit of the work tab opens the Files tab once ([The Files tab](#the-files-tab)), and the work tab keeps the view it falls back to. A click on the tab's switch still picks another for this browser, until the key changes |
| `work_views` | `[due, source, jev, files, flow]` | the views the work tab's switch offers, in this order whatever the list's; an unknown word is left out, not a list or nothing left offers all. `files` is no view of the switch: it stands for the Files tab, right after the work tab, and is always kept (every link that opens a task's file leads there). With one view left the switch does not show. A `work_view` the list leaves out opens Work through where it is kept and on, else the first view kept; no way stores a view switched off, so a jump to the work page or to Jev lands there too. Recommended once Work through holds everything: `[files, flow]`: the work tab shows Work through alone, the Sessions tab goes (Running now lists the sessions) and the task check is the row Check tasks under Not now, with no tab of its own |
| `focus_to_files` | `false` | `true`: when the focus on the start page runs out, its calm card and its last step lead on into the Files view of the work tab rather than to the tasks |
| `files_scope` | `active` | which tasks are files in the Files view: `active` the `doing` and `review` ones, as before; `all` every task and stream but the closed ones, the queue as the order of the walk and every one in the list on the left, see [Every task as a file](cockpit-files.md#every-task-as-a-file). Any other value keeps `active` and is named in `status` |
| `files_search.enabled` | `false` | Ask AI on the start of the Files tab: one model call without tools, only on a click, over at most 12 of the records listed, see [The Files tab](#the-files-tab). Off, the button does not show and the verb refuses |
| `files_search.budget_per_day` | `20` | how many questions a day may go to the model; `0` none |
| `files_search.model` | none | the model, `haiku`, `sonnet` or `opus`; none: the service `cockpit-files` of `workflow/ai-services/` (default Haiku) |
| `files_search.block` | `[]` | words that keep a record private: a record whose area (front matter and row), context, theme, path, title or the text that would go (the start of its STATUS.md, front matter and `related:` included) holds one, case folded, never reaches the model; the server drops it before the request is built, and the page says how many stay back and by which words (the records carry the server's decision, so the count before the click is the server's). A word also matches inside a longer one: `Steuer` holds back a record on `Steuerung` too, it holds back more, never less. At most 50 words of 60 characters |
| `origin_map` | none | your own source names, mapped to a category the work tab shows: a name or a quoted glob (`"*-health"`) to one of `github`, `tracker`, `calendar`, `bot`, `session`, `skill`, `work`, `person`, `bridge`, `other`. It comes before the built-in rules; a wrong category or a repeated name is ignored and named in `status`. It stays on the server, the page never sees it (see [Where a row comes from](#where-a-row-comes-from)) |
| `describe` | `auto: off` | each item's brief (goal, story, acceptance) written and kept by a small model, see [Each item's brief](#each-items-brief): `auto` is `off`, `missing` (items without a brief) or `stale` (also briefs whose text moved on); `budget_per_hour` (`20`) caps the calls of an hour; `kinds` (`[task, stream, inbox]`) names what the pass takes; `effort` (`medium`) is how long the model may think, `low`, `medium` or `high`. The button on a card works with `auto: off` too |
| `flow.enabled` | `false` | the view Work through of the work tab: everything open grouped by theme or area, one point at a time as a card with five verbs, or as a list with suggestions and a batch, see [Work through](#work-through-flow). Off, the view does not exist |
| `flow.drop_reasons` | `[resolves_itself, not_needed, someone_else, not_worth_it]` | the reasons "Drop because" offers to click, beside a free field; the four keys are worded by the page in both languages, a reason of your own (1 to 80 characters, at most 12) stands as written |
| `flow.return_after_s` | `20` | after "To tab" on a card, how many seconds later (at most 4 hours) the page asks how it went once it is in view again; `0` asks at the first return. Switching apps without "To tab" never asks |
| `flow.prep_ahead` | `2` | how many cards after the one in front get their brief prepared (`describe_run`, within `describe.budget_per_hour`), only when it is missing or stale; `0` prepares none |
| `flow.max_running` | `4` | how many started agents may run before Let AI do it asks "4 are running already. Start anyway?" (at least 1); a batch of the list starts no more than that |
| `flow.rank_max_age_days` | `7` | a Jev rank older than this many days does not order the tasks (the triage's `next_rank` is left out), the plain order takes over; at least 1 |
| `flow.themes.enabled` | `false` | Work through groups its points by themes a small model gives them, across the areas (Themes beside Areas at the top of its left column), and suggests a decision for each in the same call, see [Work through](#work-through-flow). Off, the areas group them |
| `flow.themes.max_themes` | `8` | the most themes there may be, the ones a person made included (2 to 20) |
| `flow.themes.budget_per_day` | `6` | how many runs a day may order the themes, the click "Order themes again" included; once spent, the areas group what has no theme yet until the next day |
| `flow.themes.model` | none | the model of the themes, `haiku`, `sonnet` or `opus`; none: the service `cockpit-themes` of `workflow/ai-services/` (default Haiku) |
| `flow.rerank_per_day` | `3` | how often a day a click on "order again" may ask Jev anew; `0` only the order of the day's first call. Reserved: the page has no such button yet, so nothing reads it |
| `flow.ahead_days` | `2` | a point with a due day further ahead than this many days, and not urgency now, waits under Not now, Later, until that many days before it (a due with a time counts by its day); `0` waits for the day itself, `366` shows everything at once as before |
| `flow.infer_sessions` | `true` | with `flow.enabled`, a live Claude session in a tab that names one open task in the end of its own transcript (`task.py <verb> <slug>`, `work/tasks/<slug>/`, `task:<slug>`) runs under Running now as work on it, without a link by hand; only the slug and the sign leave the server. A link by hand or a start from the cockpit wins, Not this task undoes it for good |
| `flow.summary.enabled` | `false` | the summary on top of a point's Activity tab: a click on "Summarise since last week" has a small model sum up what happened to the point in at most three sentences, see [Work through](#work-through-flow). Off, the button does not show |
| `flow.summary.budget_per_day` | `10` | how many summaries a day may call the model; a point whose rows did not change answers the kept one without a call and without counting. `0` calls none |
| `flow.summary.model` | none | the model of the summary, `haiku`, `sonnet` or `opus`; none: the service `cockpit-activity` of `workflow/ai-services/` (default Haiku) |
| `flow.instruct.enabled` | `false` | the instruction line at the foot of Work through: a sentence a small model turns into steps of the verbs there are, shown as "This is how I understood it" and run only on a click, see [Work through](#work-through-flow). Off, the line does not show |
| `flow.instruct.budget_per_day` | `30` | how many sentences a day may go to the model; `0` none |
| `flow.instruct.model` | none | the model of the instruction line, `haiku`, `sonnet` or `opus`; none: the service `cockpit-instruct` of `workflow/ai-services/` (default Haiku) |
| `flow.attach.enabled` | `false` | Attach a document at the foot of a point's Activity: the file goes into the deliverables folder of the point's open task (never elsewhere), see [Work through](#work-through-flow). Off, the button does not show and the route refuses |
| `flow.attach.max_mb` | `10` | the largest document Attach takes, in megabytes (1 to 25); the page checks the size before it sends |
| `flow.prio.fallback` | `none` | `haiku`: a read-in with Jev on a click that fails (Jev busy, 5xx, a timeout, no key; never a refusal such as 401 or 403) runs Haiku instead, while `flow.prio.haiku.enabled`, within its budget, and Prio's foot says so; the daily order never falls back. `none`: the failure stands |
| `flow.prio.haiku.enabled` | `false` | **Read in with Haiku** at Prio's foot: a small Claude model ranks the points as Jev does, see [Work through](#work-through-flow). Off, the button does not show and the route refuses (`prio_off`). Haiku needs no Jev: `integrations.typesafe` may be off |
| `flow.prio.haiku.budget_per_day` | `6` | how many read-ins a day Haiku may run (the fallback included); `0` none. A run is counted before the call, also when it fails |
| `flow.prio.haiku.model` | none | the model of Read in with Haiku, `haiku`, `sonnet` or `opus`; none: the service `cockpit-prio` of `workflow/ai-services/` (default Haiku) |
| `a2a_sources` | none | further sources of A2A peers beside `infra/a2a-peers/`: a list of `{name, script}`, `script` a skill's own `skills/<skill>/scripts/<name>.py` that reaches agents another way (an access proxy, a broker) and keeps its own credentials. At most four; a bad entry is ignored and named in `status`. Contract under [Peers from a script](#5-asking-claude-the-relay) |
| `snapshot_minutes` | `60` | while the server runs, save the cmux layout this often, only when it changed; `0` = only on "Save layout now" |
| `idle_minutes` | `10` | a tab the terminal reports as waiting that has been still this long and whose last words ask nothing (no question mark, no options, nothing typed in its prompt) is done, not waiting: it leaves "waits for you" and counts as "to review" in its area; a tab whose item or task is settled is done at once; it reads the tab's screen, so without a terminal driver that serves screens (or with the questions off) only the settled rule applies and every other tab keeps waiting; an idle tab raises no "waits for an hour" and the decision guide does not read it; `0` = off |
| `person_name` | none | how Claude and Jev name you; without it they say "the user". With `flow.enabled`, a task whose next step names you is yours, not one that waits on others |
| `launch_model` | off | the model an agent tab starts with, and whether a judge recommends one (section 3, "The model an agent starts with") |
| `ticker` | off | the news ticker on the start page: Bridge status and AI news feeds (section 3, "The news ticker") |
| `tour` | `true` | the first-run tour: a first visit offers a short introduction of the page; `false` never offers it by itself (Settings, Help and Explain still start it), see [The first-run tour](#the-first-run-tour) |
| `setup` | `true` | the Setup page: what still keeps the cockpit from working well, and the catalogue's features that are off, each with how it is switched on; `false` collects no such page, see [The Setup page](#the-setup-page) |
| `session_guide` | off | the decision guide: Claude Haiku reads a waiting tab's session and offers its next steps as buttons, in the chat and on the Sessions page (section 3, "The decision guide") |
| `usage.remotes` | the machines of `infra/instances` | other machines whose token use the overview page adds in (`infra/remotes` names; `[]` for none), see the overview page, "Tokens" |
| `usage.host` | the infra/remotes entry whose hostname or Bonjour name matches | this machine's name on the token card and in the history file |
| `usage.remote_file` | `~/.bridge/resources/usage.json` | the file `scripts/usage-export.py` writes on those machines |
| `usage.clicks` | `true` | the click origin log: which control was used from which page, view and area, by name and count, never its words or what it was about (`usage.jsonl`, section 6); `scripts/cockpit-usage.py` reads it. `false` writes nothing; any other value warns and keeps `true` |

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
collected as a button with ↻ on it (a click collects every source fresh; while
a fresh pass runs it waits), the warnings before it (connection lost, a stale
model, a failed pass: at every width, below 1280 pixels only the time gives way
and stays in the tooltip), a loading indicator, Tabs, Ask, History, Notes (the
bell: what the cockpit reported lately, newest first), a dot for the relay, and
Help (`?`) last: Explain first in it, then the topics of the look-up card and the
tour. The colours (auto, light, dark) and the look-up card stand in Settings,
Appearance. Under it sits the page bar. In front stand the
tabs of every day: "Start" (a new visit opens on it, a reload stays where it
was), "Today" (the briefing), "Files" (the records, a search first, see [The Files
tab](#the-files-tab)), "Chat", then the profile's pages with the
default `group: main` (Work and Operations in a typical profile). Behind them
come Sessions (only without Work through: with it, Running now lists the
sessions, see below), Background jobs (unless the profile places it under a page,
see Sub pages), A2A connections (only with the classic chat: with
`chat_layout: workspaces` the agents are an area of the Chat, see [The chat as
cmux](#the-chat-as-cmux)), Check tasks (only without Work through: with it, the
check is a row under Not now, see [Today](#today-the-briefing), Checking and closing tasks), Jev and every profile page with `group: more`. While the bar is wide enough every tab stands in it; when
they would overflow, that second group folds, from the last tab forward,
behind a last tab, "More", which carries the name of the page open behind it,
else a dot in the strongest colour a tab behind it wears for a reason: red for
a finding or a background job that is down, amber for a warning (an A2A agent
waiting, Jev not ready). A grey count, a green ok or a running agent is no
reason. Alt 1 to Alt 9 follow the same order; a tooltip names them only while
the shortcuts are on. A page with `group: day` has no tab: its sections stand under "What
happened today" in the middle of the Today page.

A page with `group: work` has no tab either: it folds into the Today tab, which
then carries that page's title (Work, say) and a switch over its left column
with its views (none when only one is left). **Due** is the four blocks below, and the tab opens on it
unless `cockpit.work_view` names another view. A view the switch does not offer
(`cockpit.work_views`) falls back to Work through where it is on, in the page and
on the server, and is never stored.
**By source** is the work page itself, its sections as labels. **By Jev** is the
Jev picture (the matrix and the plan) fed by the work page's order, and it
stands only where that page has `jev:` and Jev is on. With such a page the Jev
tab goes too: it is the By Jev view now, and an old link to it or to the work
page opens the matching view. The day moves to Start as well: dates, status,
what is clear, the small fixes and the workplace stand there as cards in a shelf
"The day", above the areas and the project chips since those do not filter it, and the pages of
`group: day` close the start page as shelves of their own. Both show in the
bridge and tiles views only; the overview has no shelves. "The day" is a shelf
like the others (Settings, Start page), on until switched off; the panel of the
bridge's core repeats what of it concerns the briefing itself: a source that
failed, was skipped or found something, the small fixes and the workplace. The
pages of `group: day` have no switch: without Due they have no other place, and
a link to one opens the start page instead of Work. The middle of Due
shows the day in full in every case (headline, dates, status, what is clear,
the small fixes, the workplace, the pages of `group: day`), under the same area
filter as the rows beside it. **Small fixes** (de: Kleine Handgriffe) holds
what runs beside the work: tasks without a next step, issues assigned to you
with no task, a source that failed, rows muted or in a group the profile does
not show; each line is one sentence that says what to do ("2 tasks have no next
step (a, b). Open it and write one in."), worded from the facts the view
carries (`tend`), the server's text for a kind the page has no sentence for.

Only one number in the bar carries colour: Today's count of what waits for
you, the same count as the start page's station "waits for you" and the
headline in the middle (the approvals stand in its tooltip and in their own
block). It counts the rows of Now that ask you: every row that is no inbox
item, and of the inbox only the asks (decision, question, draft). An idea or a
report filed for today still stands in Now, it is just not counted, so the
section's own head can show the larger number ([inbox.md § Arts](inbox.md#arts)).
The start page's lists named "waiting on you" show the same asks.
With Work through on, the count is Work through's instead: its points that
need you, less the finished starts (see "The numbers come from Work through"
under [The start page](#the-start-page)), so the bar, the start page and Work
through show one number.
A finding is red wherever it is; every other count is grey. A page
badge that adds up several sections names them in its tooltip; a row put off or
settled weighs in it no more than it counts. A finding on a
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

### The Files tab

**Files** is a tab of its own, right after the work tab. While no record is open, the search and its list take the
whole width, the records in columns; once one opens, the tab is laid out in the three columns of Work through. The left
column holds a large search field with **Walk through the active records (n)** beside it, chips for area, state and
kind (task or stream, a closed one by what it was), each group under its label, and the records changed last with the
matching line as plain text; a click opens a record in the middle as a file with its next step, its drawers and a
question to the file, while the list stays where it was (the field is the one search). The right column carries the
buttons of that record's point in Work through, the same ones, never a second set; **Close the record** in the
middle's head closes it. With `cockpit.files_search` on (off by default) a
question to the AI has its own field and a button "Ask the AI about these n records"; a line under it says what a
click sends, how many stay private and how many questions are left today, and the search words are never the
question. It has a page of its own: [`cockpit-files.md`](cockpit-files.md).

### Work through (`@flow`)

**Work through** is a view of the work tab, last in its switch beside Due, By
source and By Jev, there only with `cockpit.flow.enabled: true`
(`cockpit.work_view: flow` opens the tab on it). It is laid out as cmux lays
out a workspace:

- **Left**, like the workspace sidebar or a mail app's folders, a table of
  contents that lists no point. First the **themes** a
  small model gives the open points across the areas (`cockpit.flow.themes`,
  below), or the **areas** (`workplace.workspaces`, the same names and colours
  as the cmux workspaces; Themes and Areas switch at the top while the themes
  are on): one entry per theme or area that holds a point, with its colour,
  how many need you (in the warning tone) and how many are open, **No theme
  yet** or **No area** last, under **All themes** (or All areas), and **Order
  themes again** at the foot. A click enters one: the list stays as it is, the
  one entered marked, All leads back, and its points stand in the middle only.
  A theme entered can be renamed. With Jev or Haiku a third order, **Prio**, stands
  beside Themes and Areas (below). On top stands **Running now** as one row
  with its count while an agent works (below), its only place: no strip of it
  stands over an overview, and the head line counts the same number. At the foot **Check tasks** as a
  block of its own with what the last check left to decide ("2 to decide",
  "nothing to decide"; "running" during a run, "not run yet" before the first),
  and under it **Not now** with its groups (below): a click on Check tasks shows
  the check in the middle, with Back, a run button that says it asks the AI and
  what the last run cost ("Check again (about 0.33 ct)"), one plain line of what
  it does, then the verdict filter, the sort, closing many at once and the table,
  and under it how the check ran folded into one line (its stations inside); no
  right column, instruction line or walk bar beside it. What counts to decide is
  a task whose verdict is close or stale and that nobody kept open; waiting,
  unclear and continue only say how it stands.
  What one of them opens in the middle is scrolled into view.
  On a narrow screen the list is one select over the middle, Running now a
  strip over it and Not now folded under it.
- **In the middle**, on entering a theme (and at the level of all of them),
  its **overview**: every point as a row of a table, grouped as on the left,
  with its box, title, stage, area and the suggestion with half a sentence of
  why (below), a line over it naming where the suggestions come from, and on
  top the sticky batch bar. A click on a title opens the
  **point**: on top **Back to overview** with the theme's name beside it, a
  line "n ticked" with **See in the overview** while points are ticked, then
  the point as a card that carries its content only: its kind in its head (the
  one place its state stands), the title, the tab's question with one row of
  answers (the decision guide folded under **Show the decision guide**), what
  came back, the last lines of its tab's screen. Who works on it and since when
  is a field on the right, the criteria of its brief stand in Description. Under
  the card the point's **tabs** (below), at the
  foot the **instruction line** (below, while it is on) and under it the files
  view's walk bar
  (**Previous point**, "n of m", the next title, **Next point**). After the
  last point of a theme or area it leads to the first point of the next one
  where something is open. Neither the title nor anything else opens the item
  drawer or another view.
- **Right**, only while a point or an entry is open (the overview and a list
  of Not now take its width), **What you can do**: the AI's suggestion as
  one sentence (on an open point the only place it stands; the overview shows
  it as a column, because there one picks without a point open), then the verbs under each other in one style, the suggested
  one the strong button. While an agent tab is on the point (at work, asking, or
  waiting at its prompt) **To tab** leads and **View** follows, and neither
  Let AI do it nor Give your yes stands there: no second agent starts beside
  it, as the instruction line and a batch have it. On a finished start the verb
  the AI suggests is the strong one too, else Done and close the tab. Under it
  the **Fields**, like the sidebar of an issue tracker:
  **Theme** (to change, with the themes on), **Area**, **Who works on it**,
  **Prio** (Jev's quadrant and rank while Jev's order of the point is younger
  than `rank_max_age_days`, else the day's triage rank, else the priority),
  **Urgent**, **Important** and **Effort** as small bars (only with Jev's
  order), **Due**, **Source** (its chip, **STATUS.md** that opens the task in
  the item drawer over the page, an issue or a pull request by its ref on the web),
  **Created** and **Moved** (the newest row of its Activity). There is no Status
  field: the card's head says it, and
  who works on it and the source stand only here. A row with steps of its own
  on a page (an application) has **Steps ▾**, which opens the info drawer that
  holds them. Under the verbs of every point or entry with a row stands
  **Details**: an inbox item or a task opens its item drawer, with every verb Due
  has (urgency, area, as a task, follow up, gather info, own workspace, advise as
  a tab, take over a tab), any other row its detail column beside the page (Prio,
  area, urgency, take over a tab). The reports carry it on each report in the
  card, beside Seen.

Before the first state arrives the middle shows the loading or warning block
Due shows, never "All decided". A click on a tab's name (the tab column, the
Chat) opens what it works on here: its point, its entry under Running now or
its group of Not now. Jev's daily order and the themes are asked for in every
mode, once a load; "Ask Jev again" stays a click. The pill "Only pinned" does
not stand here, it filters nothing in this view. **Next point** follows the
order of the overview.

The three columns stand side by side down to a width of 1180 pixels; below
that the right column stands under the middle, and on a narrow screen the left
column becomes a select on top and the tab bar scrolls sideways.

The head says "N points · R running · M not now" (the running part only while
something runs) and how many were decided here. The three add up to everything
open: every row of the sections and every hidden row not decided here, with
`cockpit.files_scope: all` every task and stream of the files view, every task
a page names whose folder is open (`model.task_rows` that are closable or a
stream: a stream of folders without a STATUS.md of its own too), and every
inbox item a page lists that is put off past the briefing's window
(`model.deferred`, only with Work through on: the idea shelf, what runs on),
each once. The server sends the same number as `model.counts.flow_open`.

The points come in groups whose order is fixed in the code; nothing moves a
point across a group, a Jev rank only orders inside one:

| # | Group | What | Order inside |
|---|---|---|---|
| 1 | Back from a tab | the return card after **To tab** (below) | one |
| 2 | A tab asks | a start whose tab asks, and every tab that wants you (needs-you, or waiting at its prompt and not quiet yet: the rule of the rest of the cockpit), with or without a task | the oldest question first |
| 3 | Finished or quiet | a start of the return channel with its answer or result line, and one whose tab went quiet (stage `idle`) | the oldest first |
| 4 | Tab gone | a start without a tab and without a word | the newest first |
| 5 | A question for you | an inbox item that asks (art `ask`), with or without a task | a due day first, then the oldest |
| 6 | In progress | every task with status doing that no agent works on right now (what runs stands under Running now) | by `next_rank`, a Jev view of a work page, priority, age |
| 7 | In review | the tasks in review, every priority | as the tasks above |
| 8 | Issues and PRs | an issue or pull request in Now (urgency now or today, or to do) | a due day first, then priority |
| 9 | Reports | the reports (art `report`), as one tab | the oldest first |

Groups 1 to 5 **need you**: the left column counts them. Every open row stands
exactly once: on a point, under Running now or in one group of Not now; a start,
a tab or a question about a task takes that task out of the others. A tab that
asks brings the task of the session linked to it (by hand, by its task tab or
recognised): while it asks, the task stands once, as that card, and goes back
to Running now once the tab works again or went quiet. A doing
task with an agent at work stands under Running now; without one it is **In
progress**, and the field **Who works on it** says "Nobody works on it right
now, last moved N days ago" (its `updated` day, the `last_updated` of its
STATUS.md). The right column offers **To tab** and **View** (the strong one
while a tab is at work or asks), **Done**, **Later until** and **Drop
because**, and without a tab at work **Let AI go on with it** (a start with a
sentence, as always). Ideas and backlog tasks come back only when nothing is
open: the calm card offers up to three to start.

**Running now.** What an agent works on right now is not a point and never
part of the walk, the overview's table or a batch. It stands on top of the left
column as one row with its count and a dot that pulses while an entry works,
and only there (one count, the same in the head line and on the start page's
areas); a click lists every entry in the middle, each with its tab, stage,
since when, how it is known, **To tab** and **View**. A row of a list an agent
is at work on carries a small "running" marker. An entry opened from that list goes back to it. An entry with a task of its own has a box there, in the same
selection as the overview's: it is only for **Merge** with a point (the one an
agent works on is suggested to stay, so no folder moves from under it) and
**Done**; a batch never starts, puts off or drops what runs, its line says
"stays out". That is a start of the cockpit that runs, a live session at
work that works on a task, and a task's own tab at work. A tab quiet at its
prompt (stage `idle`, "finished") runs no more: its task stands as a point
again (In progress, Who works on it says finished), a start that finished is a
card To look at; one waiting that is not quiet yet wants you and is a point. In
the middle every live Claude session of the machine at work stands
there too, with a task or without one and even without a terminal driver, as a
compact card of the Sessions page (state, title as the jump to its tab, its
agents, two lines of its tab, one next step, a task to link), one card per tab;
an entry in a session's tab is that card, and **View in chat** opens the tab in
the Chat where the Chat lays out its tabs (`chat_layout: workspaces`). A tab
that asks is a point (A tab asks), never here. A start that ended with a note does not
vanish: it stays as a card **To look at** with that note (headed Question when
the note asks) and, while the chat it was handed from is still kept, **Open
the question it came from** (each start remembers its chat, `conv` in
`launches.json`); **Take off the list** removes it. A start that ended
without a note leaves as before. A note headed `Question:` or `Frage:` keeps
its start at the stage `asks`, also once its tab is gone, until a tab works on
it again or the item closes; a tab still for over a minute after that note,
with nothing asked on its screen, was answered in the terminal and stands
`idle`. Which
task a session works on: a link by hand (the Sessions page), else its tab's own
task (every start from the cockpit), else, with `flow.infer_sessions` (on by
default), the task it is **recognised** on. For that the server reads the end
of the session's own transcript (`~/.claude/projects/<folder>/<session id>.jsonl`,
the last 256 KiB, further up to 4 MiB while nothing decides, at most 400
events) and takes the newest message or tool call that names exactly one open
task: `task.py <verb> <slug>`, `work/tasks/<slug>/` (relative, or under the
Bridge's root written absolute or as `~/...`) or `task:<slug>`. A tool's
result never counts (a listing names many tasks), a line that names two is
skipped. Only sessions of this Bridge in a tab are read, at most 12 per scan,
never another Bridge's; no model is asked, and of the text only the slug leaves
the server. A click on a title opens the entry in the middle with its card,
its tabs and the instruction line; the right column offers To tab first, View,
Done, Later and Drop, and for a session **Not this task**: it unlinks the
session and remembers that it does not work on that task (`session_unlink`,
kept in `state.json` as `session_refused`), so it is not recognised on it
again; Link on the Sessions page takes that back. The Sessions page marks a
recognised task as such.

**No Sessions tab beside it.** Where the work tab offers Work through
(`cockpit.flow.enabled`, kept by `cockpit.work_views`) the bar has no Sessions
tab and no "AI n" badge: every way to the Sessions page (a link, a note, the
band, the tour, an area's number, the header chip, a page an older cockpit
stored) opens Running now. What the badge counted stands here as points already.
A Bridge without Work through keeps the tab and its page.

**Not now.** At the foot of the left column, every open row that is no point
and does not run, in four groups and one line: **Later** holds what is put off
(hidden until a day, put off in the inbox, or due later than the lead time),
what waits on others (on a person or a run, and an item the Bridge runs on its
own after your yes; a task whose next step names you, `cockpit.person_name` or
"me", waits on nobody else and is a point) and what rests (blocked, quiet for
long, up for parking, a task whose status is unknown), in that order, each row
with its reason in the column **Why** ("put off until", "waits on", "blocked:",
"resting since"); **Ideas and backlog** (ideas of the inbox, also one put off
with the day it comes back, and backlog tasks), **Streams** (they come through
their inbox items) and **Watching** (issues and pull requests that are not in
Now, by repository). A watched row that stands on a GitHub list of a page (the
row's `on_board`) is folded into one quiet line "n on GitHub" (the page's
title): a click opens that page at that list, and the line counts its rows, so
the head's sum stays whole. A checkup warning, an application, a follow-up
point, a row that needs you or one put off never fold. A click on a group shows
its list in the middle: a box, the title, its kind, when (from or until a day,
due; in Later, why), its area, and the batch bar with the verbs the group
offers. A title opens the row where it lives: an issue or pull request on the
web, a task in the item drawer, an inbox item in its card, a row with steps of
its own on a page in the info drawer.

| Group | Verbs of its batch bar |
|---|---|
| Later | Back on (each row by why it waits), Later, Done, Drop |
| Ideas and backlog | Let AI do it, Later, Done, Drop |
| Streams | Later |
| Watching | Later, Done, Drop |

**Back on** takes a row up again: a hidden row shows (`unhide`), a deferred
item opens (`inbox_reopen`), a blocked task runs on (`task_running` clears its
blocker), a resting one is kept (`task_keep`); a task that waits on someone
else's next step has nothing to clear, so it stays out and the line says so.
A point due later than the lead time
shows now, in this browser only (kept as `bridge-cockpit.flowEarly` until its
day). In Later each row that can come back carries Back on as a button of its
own too, one click without ticking it first. Back on carries no undo; put the
row off again instead. A row decided
here (done, not doing) is open no longer: it is listed nowhere and not counted.

**Not too early** (`flow.ahead_days`, default 2). A point due further ahead
than that, and not of urgency now, waits under Later until that many days
before its day, then it is a point again; a due with a time counts by its day.
With 2, an item due on Sunday at 19:00 stands under Later "from Friday" until
Friday. `0` waits for the day itself.

**Merge.** When two or more ticked rows of a batch bar (the overview or a Not
now list) are open finite tasks, **Merge** opens a panel under the bar: which
task stays, a choice per task with its count of activity and when it last
moved, one an agent works on suggested, else the one with the most activity. **Merge** in it closes the
others as merged into the one that stays (`flow_merge`, through `task.py
merge`, see [`work-system.md`](work-system.md)): their headline, goal, notes and
open steps come over as one section of the kept task, their documents stay
where they are and are linked from it, and each closes with `outcome: merged`
and `merged_into`. The Activity of both shows the decision. **Undo the batch**
takes every merge back (`task_unmerge`, one per merged task, also from the
history): both STATUS.md files come back byte for byte as they were before the
merge (`task.py merge` keeps them in `.bridge/task-merges.json`; a brief the
describe pass wrote meanwhile does not count as a change), so no note and no new
`last_updated` stays behind and no brief turns stale. A file changed since is
edited instead: the section, the tagged `related:` lines and the merge's note
leave the kept task, the merged one opens again with the status it had and its
blocker, and the undo writes no note of its own (only its log row). The notes a
merge, its undo and a reopen after it wrote never come over into a later merged
section. `related:` in any block style (indented or not, an item over two lines)
stays readable; a list the merge could not extend safely stays as it was, with
a warning. A section changed by hand since cannot be
taken back (`merge_changed`); streams and inbox items do not merge
(`merge_not_task`), and with any of them ticked the button stays grey and says
so.

**Prio** (while a work page with `jev:` exists and Jev or Haiku can read in).
A third order beside Themes and Areas, kept in this browser: the open points by
the quadrants of an Eisenhower matrix as a 2x2 grid in the middle, columns
urgent and not urgent, rows important and not important. Each square shows its
count, how many of its points only you can do (only where the ranker said so,
never because of the square), its first four titles and a suggestion; **Not
rated yet** stands under the grid while points have no rating (new since the
read-in). A click on a square enters it, its points in the ranker's rank, the
walk too.

Two rankers read in, both at all times at the foot of Prio's left column:
**Read in with Jev** (TypeSafe, while `integrations.typesafe` is on and has its
key) and **Read in with Haiku** (a small Claude model, `prio.py`, the service
`cockpit-prio`, while `flow.prio.haiku.enabled`, within
`flow.prio.haiku.budget_per_day`; it works with Jev off). Either takes every
point the view shows: tasks, inbox items, tabs, issues and pull requests,
meeting references, what runs under Running now, also the points the triage
marked. The page only names the points by key: the server looks each one up
in what it knows itself (its rows, the work page's sections, its tabs), drops a
key it cannot place, and holds back a point of a section in `skip_sections` and
one whose title, detail, task, source or gist on the server holds a `private`
word; the foot says how many the private words held back. Only the same thing
goes once: one key twice, or a tab that works on a task of its own (that task);
a title alike is never a reason. Per point only title, kind, status, due in
words ("tomorrow", "in 3 days", "overdue 2 days", computed in code), whether an
agent works on it, its age in days, the triage's one-line gist, the section's
label and the priority leave the machine, all from the server's item, never a
path, a detail text or an item id; all in one request (above 60 points in
batches of 60, at most three). A view too big for one Haiku prompt drops the
gists, then the points of the lowest priority, and counts them as left out.
Both answer the same per point (urgency, impact and effort on four levels, only
you or not, a rank; Haiku adds half a sentence of why), so the grid works the
same; a point left without urgency or impact gets no square and stands under
Not rated yet. The order names its ranker: the foot reads "Haiku, 29 Oct 14:10,
18 points", and the newest order wins whichever ranker made it. With
`flow.prio.fallback: haiku` a Jev read-in on a click that fails runs Haiku
instead and the foot says so. Without a click Jev orders once a day by itself
(the first view of the day once the tabs, sessions and triage are read, as the
Jev view does); it never falls back, and when it fails no reload asks again that
day, only a click. Haiku never runs by itself. An order counts
only while it is younger than `flow.rank_max_age_days`. The ranker also feeds
the suggestions, after the triage and the themes: Let AI do it for a point that
is urgent and not important, and Drop for one that is neither, but never for a
point an agent works on or a task in progress or review that moved within the
last seven days, and **Tick the suggestions** never ticks a ranker's Drop.

**Themes** (`cockpit.flow.themes.enabled: true`). A small model (`themes.py`,
one `claude -p` call with the points as data: title, kind, area and the goal of
the brief) gives every open point one of a few themes, two or three words in
the instance's language, across the areas, and in the same call a suggestion for
each point (below). The result is kept (`.bridge/cockpit/flow-themes.json`):
points that come later are given the themes there are, a new theme only where
none fits, never more than `max_themes`. The page asks only when the view shows
points without a theme (each once per page load), and **Order themes again**
orders every point anew; there is no timer. Where the work tab offers no By
source, **Sort again** stands beside it in every order of the left column: the
daily triage asked anew for what changed (below), the button By source carries in
its strip. Every run counts against
`budget_per_day`; once it is spent, what has no theme yet stands under **No
theme yet** until the next day. A point you move to another theme or a new one,
and a theme you rename, stay as you set them through every later run. With the
themes off, without a Claude model, or on an older server, the areas group
the points.

**The overview and its batch.** Every point of the theme as a row: a box, the
title (with its kind and age under it), stage, area, and a **suggestion** with
half a sentence of why: Done, Drop
(with a reason of `cockpit.flow.drop_reasons`), Later until a day, Let AI do it,
or Needs you. It comes from the day's triage first (verdict close, stale or
waiting, else who does it), while that is at most two days old, and from the
task check's verdict on a task (close is Done, stale Drop, waiting Later until
Monday; kept says nothing): where both judged, the newer speaks, and the line
under the suggestion names the check and its day; else from the themes run. The line over the rows says where the suggestions come from and
that they are only suggestions. **Tick the suggestions** ticks the rows whose
suggestion is Done, Drop or Later (never Let AI do it); the boxes and **All**
tick by hand, and the bar says what the ticked ones would do ("2 ticked: 1 done,
1 drop"). **Run the suggestions** takes each ticked row's own suggestion;
**Done**, **Later until** and **Drop because** (one reason for all) do the same
for all ticked rows. Nothing goes out before the one line that says what will
happen ("2 done, 1 drop: No longer needed, 1 later until 31.10.") is confirmed.
Then each call goes out in turn (`settle` for many keys at once, `later` and
`shelve` one by one), one toast says how many were decided, and **Undo the
batch**, once, in the overview, takes every one of them back through the undo
each verb returned. The server's note of each step lands in the notes, not as a
toast of its own. Let AI do it in a batch starts a point only with its own sentence and
only while fewer than `cockpit.flow.max_running` run; the rest stays out, and
the line says so. A point an agent already works on (a start of the cockpit
that is not over, or a tab of its task) is never suggested for Let AI do it,
and a batch starts no second agent on it. Later and Drop sent to all or to the
ticked rows leave such a row out too (`working`); on the one point open they act.

The five verbs stand in the right column under each other, the suggested one
as the primary button (the triage's verdict, else Advise on a question and Let
AI do it on a task the AI may do). A verb sent from a suggestion, a batch or the
instruction line says so (`by`: `suggestion`, `batch`, `instruction`; a click of
your own sends none): the history, the start and the audit line keep it and
Activity shows it as who decided; nothing acts on it:

| Verb | Sends |
|---|---|
| Let AI do it | `do_it` with a sentence, always: the field is filled with the title and the request to end with a note "Result: ...", and Start stays grey while it is empty. A start with a sentence never approves an item's own action; an item that needs your yes keeps **Give your yes** beside the verbs |
| Advise | a read-only quick question about the row; the answer shows in the card, with **Start from it**. The answer names the card's own button, Let AI do it, and no key (the quick question goes out with `origin: flow`) |
| Done | `settle` done |
| Later until | `later`: tomorrow, Monday, next week or a date |
| Drop because | a reason from `cockpit.flow.drop_reasons` or typed, never without one: a task is shelved (`shelve`, an idea in the inbox and the task declined, taken back by reopening it), anything else settled as not doing with the reason. A stream's own row offers neither Drop nor Done; an inbox item about a stream is decided like any other item |

**Let AI do it** shows the model and its effort under the start sentence (the
picker of every start, while `cockpit.launch_model` is on): with Auto, the
router's recommendation for this card is fetched once (`/api/route`) and kept
for the page's life. Once `cockpit.flow.max_running` agents run (the entries
of In progress at work), Start asks first: "4 are running already. Start anyway?". One
click starts one item; there is no start of several at once.

**A tab asks.** The card shows the question the tab poll read (`asks.py`) and
its answers as buttons, the same as everywhere a tab is answered: a dialog's
options (`tab_option`), yes and no, go on, a field for an answer of your own.
With the decision guide on, its steps stand under them. Every answer names
the question it answers, so nothing reaches a tab that moved on; once sent,
the card leaves the queue until the tab asks anew. The right column offers no
start (the tab takes no sentence while it asks): **To tab** first, **View**,
then the other verbs. A tab that waits at its prompt with nothing asked on its
screen (no question, no options, nothing typed) is headed **A tab waits** (de:
Tab wartet) instead, so the head never says it asks beside its close.

**Finished or quiet.** A finished start shows its answer, or its result line
(a note "Result: ..." on its task since the start), and a quiet one says that
no question was read. Under it the criteria of the item's brief as a plain list
to check yourself: nothing ticks them and nothing judges them. The right
column offers **Done and close the tab**, **Improve** (what is still to do: sent to the tab
while its agent waits there, else a new start with those words), **Runs on**
and **Drop because**. A lost start offers **Start again**.

**Briefs ahead.** When a point is opened, the next
`cockpit.flow.prep_ahead` points whose brief is missing or stale get it written
(`describe_run` with `ahead: true`), one at a time, each key once per page
load, never on a timer, and quietly: no toast for them. A refusal (the hour's budget spent, a brief being
written already) ends the round; the cards not asked for yet are asked for
when a later card comes up. These runs keep within `describe.budget_per_hour`;
a click on a card's Describe button still always runs.

**The return card.** **To tab** on a card remembers the jump, in the page's
memory only (a reload forgets it). When the page is in view again at least
`cockpit.flow.return_after_s` seconds later (and within four hours), the card
**Back from the tab ...: How did it go?** stands in front, with Done, Runs on,
Later until, Drop because and Not yet; any answer forgets the jump. Switching
to another app and back without To tab never brings it.

**The tabs under the card**, as an issue tracker has them: **Description**
(the goal, the story and the criteria of the point's brief; its source stands in
the fields), **Steps** with how many of how many are done (the checklist of
STATUS.md, read only), **Activity** with how many rows it holds, and **Related**
with how many (the other rows of the same task, the paths STATUS.md names). The
tab you pick stays from point to point (remembered in this browser); a tab the
point lacks falls back to Description, and a point with one tab only and the
Reports card have no bar. The panes read at most about 820 pixels wide.

**Activity** is one list of everything that happened to the point, newest first,
read from what the Bridge keeps anyway (`activity.py`); nothing is asked of a
tab. Each row says when, what kind, what (a change as the old value struck
through, then the new one; a decision taken back says so) and who or what did it
(you, an AI suggestion taken, a batch, the instruction line, the themes run, an
agent, the Bridge, git). The filters count their rows:

| Filter | Rows |
|---|---|
| All | every row below |
| Notes | the notes of its task (`task.py note`), an inbox item's notes, the rows of `work/log.md` that name the task (one that repeats a note of the same day is left out) |
| Documents | the files in the task's `deliverables/` (any type, eight folders deep, no dotfiles, no links), new or changed: when git added and last changed each, else the file's own times; a document attached from here says so. Each is a link that opens it in a new tab |
| State | a change of `status:` (as git has it, and the working tree against the last commit), an inbox item's state, a move to another theme, each decision of the page (done, not doing, later until, dropped with its reason, hidden) and whether it was taken back, when it was created, and who drives it (the starts of agents, linked sessions) |
| Agents | the starts of the return channel with their result, the workflow runs of the task, linked sessions; a live tab links to the page's view of it |
| Code | the issues and pull requests of `sync.github`, and the GitHub issues, pull requests and commits its notes and log rows name, each once (the one that is the row's own source stands in the fields) |

An inbox item that names a task shows that task's documents too. At most 200
rows show; the counts are taken before that. Git is optional: without it, or
when a call fails, the file times stand in. The list is read when the point
opens (its count and its fields need it) and kept for 20 seconds; a verb on the
row, a note or an attachment reads it anew.

On top, with `cockpit.flow.summary.enabled`, **Summarise since last week**: a
small model sums up the rows of the last seven days (none: the newest 40, at most
60) in at most three sentences, in the instance's language, shown with its model
and time and kept per point (`flow-activity.json`). The same rows answer the
kept summary without a call; once rows came since it reads **outdated** and the
button asks again. Each call counts against `budget_per_day`, one runs at a time,
and a refusal says itself in place, never as a toast. At the foot a one-line
field **Write a note** with **Add note** (the verb `note`, as everywhere) and,
with `cockpit.flow.attach.enabled` on a point with an open task, **Attach a
document**: the page checks the size against `max_mb` first, the server writes
the file flat into the task's `deliverables/` under a safe name (no folder, no
path, a name already there gets `-2` up to `-99`), leaves a note "Attached:
deliverables/<name>" on the task, and the list shows it as attached. An inbox
item that names a task attaches to that task; a point without one offers no
button.

**The instruction line** (`cockpit.flow.instruct.enabled`, off by default), at
the foot of the middle above the walk bar, one row while it is empty: one
sentence to the Bridge in place of a few clicks. Above it what it speaks for:
on a point that point ("For: <title>", and "a reply goes to its live tab" while
its tab waits at its prompt), on the Reports card its reports, in the overview
the ticked points or all points of the theme (at most 50 go, and the label says
so). A point with no item behind it (a tab alone, a start whose item is not in
the list) has no line. **Send** hands the sentence
and the points (their titles, kinds, the verbs each offers and whether a tab
runs, nothing more) to a
small model that answers with steps of the verbs there are: Done, Later until a
day, Drop because, Let AI do it with a sentence, a reply to the point's tab while
it waits at its prompt (a tab that asks a choice is answered on the card). A
mail becomes a start of Let AI do it whose sentence asks for a draft with the
mail-draft skill, a draft only, never sent. The server checks every step against
what each point offers, the day and the scope, and runs nothing. The page shows
**This is how I understood it**: the steps in words, each point that drops out
of a step struck through in it with why (a reply to a tab that asks a choice
says to answer it on the card), what was unclear; **Run** sends the steps
through the same verbs and their undo
(quiet, one toast, with `by: instruction`, a start never where an agent works
already nor past `max_running`, Later and Drop not on a row an agent works on
unless the sentence spoke for that one point), and **Undo the instruction** stands under the
line once; **Change** puts the sentence back into the field, **Discard** drops
the plan. Opening another point or the overview drops the plan too. Every call
counts against `budget_per_day`, one runs at a time.

**Without a terminal driver** the cards of the agents (groups 1 to 4), Running
now and every way to a tab stay out. A start then hands out the
commands to start it by hand.

**Upgrading.** Opt-in, nothing changes until the key is set: without
`cockpit.flow.enabled: true` the view does not exist. Work through was a tab of
its own (page `@flow`) and is a view of the work tab now: a stored page `@flow`
or a link to it opens the work tab in that view, and `cockpit.work_view` takes
`flow`. The chips and the lane Running are gone; the left column and the overview
stand for them, and doing tasks moved from the decision cards to In progress.
The themes are a second opt-in (`cockpit.flow.themes.enabled`, off by default):
four new verbs (`flow_themes_run`, `flow_theme_move`, `flow_theme_new`,
`flow_theme_rename`), the state's key `themes` and the event `themes`; a page
that does not read them is not affected. `/api/ask` takes two optional fields,
`origin` (`flow`: the answer names the card's verb and no key) and `keys`
(true only while the page has its shortcuts on: only then does the answer name
Cmd Enter); a page that sends neither gets an answer that names no key. The page
adds the verb `shelve` and `describe_run`'s `ahead` (from the first version);
every other page, view, verb and endpoint stays as it was. The tabs under the
card, Activity, the right column and the instruction line came later: see
[Upgrading: the tabs, Activity and the instruction line](#upgrading-the-tabs-activity-and-the-instruction-line).
Running now, Not now, Merge, Prio and the lead time came in a later version:
see [Upgrading: Running now, Not now, Merge and Prio](#upgrading-running-now-not-now-merge-and-prio).
To try it in the demo, open the work tab and pick Work through (`?work=flow`
opens it there); `?flow=0` shows the demo without it, `?work_page=1` adds the
work page that Prio orders, and `?views=files,flow` narrows the switch.

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

**The numbers come from Work through** (when `cockpit.flow` is on). Each line
of the areas is what Work through shows under that area as its filter, read
from the same function (`flowParts` under `areaScope`, scripts/web/flow.js
`flowAreas`), so nothing is counted by a second rule:

| Column | What Work through holds |
|---|---|
| waiting | the tabs that ask, the questions, the lost starts and the return card (its groups that need you, less the finished starts); the tabs among them make the "tabs" of the head line |
| running | what Running now lists: what is at work, never a finished (quiet) session |
| to review | the finished starts |
| overdue | the points and entries of Running now past their date |
| tasks | the tasks, the doing and the issues of the walk |

What Work through puts under Not now (put off, given your yes, waiting on
others, resting, blocked, due later than the lead time, ideas, streams,
watched issues) counts in no column, and a tab answered here stops waiting at
once. A row of two areas stands in both lines; the line All counts what Work
through shows unfiltered, each thing once, so it can be less than the sum of
the lines. The head line, the tile "waiting" and the work tab's count in the
page bar are the line All's waiting; the overview of Work ("N for you now")
is the line of the area it is filtered to. Under an area Work through holds
that area's open tasks a page names and items put off past the window only
(`task_rows`, `deferred`), no other area's. A click on waiting, to review or overdue
opens Work through on its overview under that area, running opens Running now.
Without Work through the start page keeps its own count (`homeAreas`: the asks
of Now and the tabs that want you, the line All their sum).

Between the table and Next up the overview can show four **parts**, each off
until switched on under Settings, Start page, "Parts of the overview" (saved
with the rest of the start page, `home_tiles` ids `d:waiting`, `d:guide`,
`d:tabs`, `d:day`; a choice made before they existed does not get them):
*Waiting on you* (the section of Work, with its actions and the star),
*Decision guide* (the reading of the next tab that waits on you, the chat's
own card with its guards, Next and Previous through the others), *Agent
tabs* (the cards beside Work) and *The day* (dates, status and small fixes of
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
  click opens the place it names: the page, the tab, the row or the drawer. A
  source, the pass, the load or the triage opens the day column of Due, or,
  where the work tab offers no Due, Start with the day's status in view.
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
started, working, asks you (a dialog the terminal reports, or a question read
off the tab's screen: a question mark, numbered options, words typed in its
prompt), quiet (`idle`: the tab stopped working and the words read off its
screen ask nothing, or its agent left the shell; most likely through; a tab
whose screen was not read keeps asking), answer (a filed inbox item, a note on its inbox item
written after the start, or a note on its task since the day of the start that
begins with `Result:`, in German `Ergebnis:`, and stands after the cockpit's
own start line of that day), done (its inbox item closed, or
its task moved to `work/done/`), and "no word" when the tab is gone without an
answer. An agent tells its result in one line with
`task.py note <slug> -- "Result: ..."`; the cockpit writes no line of its own
for it. The page follows tab states live and shows the stage
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
handed, in five groups: **Done, please check** (a start that left an answer or a
result, or whose tab went quiet), **Settled, the tab can go** (a start whose
item closed or whose task moved to `work/done/`, only while its tab is still
open, plus every waiting tab whose own item or task is settled without a start
of the cockpit naming it; a settled start without a tab stands nowhere),
**Needs you**, **Working** and **No word**. A settled tab says why ("Done: its
item is closed. The tab can go.") and offers **Close tab** as its one next step,
the same on its session card, in the agent tab column and on its return card.
Since round 6d every tab that neither works nor asks can be closed (see **One
close for every tab** below). The Sessions tab badge reads "AI n" while
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

**One close for every tab.** A tab that waits or is back at its shell, asks
nothing (no question, no options, nothing typed in its prompt; its last words
alone ask nothing, the rule of the quiet tabs) unless its item or task is
settled already, and is not the control tab has the same close wherever it stands: a
point of Work through (Abarbeiten) and the aside of a record on the Files tab,
Running now and its session cards, a return card, a tab card and the head of a
tab open in the Chat (the lines of Waiting for you stay one line each and lead
there). With an open task or
inbox item behind the tab it is **Done and close tab** (de: Erledigt und Tab
schließen) with **Close tab only** beside it, else **Close tab** alone. Done and
close tab ends each of them the way Done does (`task.py close`: status done,
moved to `work/done/YYYY-MM/`, board and log row; `inbox.py close` with the
done note) and closes the tab only when every end went through; otherwise the
tab stays open and the message names what is not done. A close of a tab that
handed back something nobody has looked at here yet (it filed a row, or a start
of it holds a result) asks once more ("Close tab: sure?") on the first click,
and falls back after a few seconds; in the head of a tab open in the Chat, where
its screen stands beside the button, it closes at once. Where a point offers its
own Done for the same row, only one Done stands there. The server sends what
stands behind a tab as `behind` (`{task, item}`, null for the control tab): its
task, or for a tab known by its name alone (no task in its binding) the task of
the session working in it, the one its head names, and its inbox item.

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

**Checking and closing tasks.** "⟳ Check tasks" (in Work through the button
of Check tasks, where Work through is on; else on the Check tasks tab; in the
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
answers, Check closer with the stronger model. Check tasks (the row in Work
through, or the tab without it) is the overview of the last run: a filter per verdict and "changed", sort by verdict, priority or
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
    skip_sections: []   # briefing section ids the triage leaves out
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

**A page's search.** A profile page with `search: true` carries a search field
above its sections with three modes beside it; switching keeps the text. In
**Today** typing two characters or more filters the page's own rows to those
that hold every word, in every section at once, its head counting the hits (a
section that drew only its first rows loads the rest first, so the filter covers
all of today; a section of groups shows every match unfolded, one without a
match says "Nothing matches the filter", and with no hit at all a line offers
**Every day**). **Every day** (on the switch, on Enter, and as one types, once
the typing pauses) leaves the rows as they are and asks the history with the same words
(`GET /api/timeline`, `scripts/work-find.py --history`): every line that holds
every word in the log rows of `work/log.md` and `work/archive/` (an old row with
only its time takes the day from the `## <weekday> DD.MM` head above it and the
year from the file's name), the meeting notes of a day
(`work/archive/days/YYYY-MM/DD_*.md`, the time from the nearest `## HH:MM`
head), the meeting folders `<work.meetings.home_dir>/YYYY-MM-DD-<slug>/`
(default `work/tasks/_meetings`), the closed tasks (`work/done/`, the day they
closed) and the raw meeting transcripts in `work.meetings.raw_record_dir` under
`doc_sensor.onedrive_root` (`*.md` whose name carries the day and the time, no
link followed, nothing over 2 MB). The lines stand as a timeline by day, newest
first, each with its time, what it is (log, meeting, closed, transcript), where
it stands and the line; a meeting folder, a closed task, a transcript or one
meeting of a day brings at most three lines and says how many more it holds,
the words stand marked, and a closed task opens in the Files tab. With
`cockpit.files_search` on, the mode **Ask AI** (Enter or its button, the
questions left today beside it) asks when it was done or discussed (the verb
`timeline_ask`): a first
call turns the question into search terms and maybe a range of days, the
server picks the 60 lines that hold the most of them, every line a word of
`files_search.block` names in its path, source or text stays back before
anything is built, and a second call answers from the rest with the days and
the lines it names. Both calls run without tools, settings or session, count
as one question of `files_search.budget_per_day`, and take its model.

**A page's log layout.** A section with `view: log` draws its rows as a log:
under sticky hour heads (`13:00`; an earlier day's row under its date), each
row its time, the glyph of its activity type, its context as a chip and its
text clamped to two lines (a click opens it in full and offers its detail; a row of a task, or whose context
names a task, a stream or a closed one of this Bridge, carries a file mark and offers **Open its file**, a closed
one by its newest folder under `work/done/`),
the typed words marked, the first 100 rows and a button for the next ones. A
section with `place: rail` stands in a narrow column beside the main one, its
rows as tiles two to a row: the name, the `when` with its leading number large
(a `commits` row: "3 today"), the sparkline at the start of its detail as bars,
the rest (the branch) and the row's web page as the tile's link; a dim row
(nothing today) is named in one quiet line below. A page with either key takes
the layout: its head names the day, the title and how many log lines in how
many topics (the page's plain count stays on its tab, a finding keeps its mark); the search bar (with `search: true`) spans both columns; the rail
also carries the log's contexts as topic chips with their counts, and a chip
filters the log to its topic together with the typed words (the head of the
log counts the hits and names the topic). In **Every day** the timeline stands
in the main column in place of the log, in **Ask AI** the answer stands above
it; the rail stays. Under 900 pixels the columns stack, the rail first.

```yaml
view:
  pages:
    - id: day
      title: Daily log
      search: true
      sections:
        - {id: activity, view: log}      # the log by hour, topic chips beside it
        - {id: commits, place: rail}     # repository tiles in the rail
```

**Overview pages and tokens.** A profile page with `overview: true` opens
with a board of tiles: one per section, with its count, its loudest row and a
colour for the worst tone (a quota gauge shows its fullest value, a plain gauge
its counts), plus one for the background jobs (only where Background jobs keep a
tab of their own; under a page they stand in its folder bar), one for the tokens
of the week and, when the page places the cost card, one for the cloud costs
(yesterday, the month so far and seven small bars). A click on a section tile
scrolls to that section, the cost tile to the cost card, the workers
tile opens the Background jobs tab on every job. A sub page with `overview: true`
(Sub pages, below) has no tiles: it heads with one card of one line per section
drawn (a dot, the title, what it says: "1 fine, 1 off", "4 warnings: <section>"),
where neighbours that say the same of their one row fold into one line; a click
jumps to the section. Jobs, tokens and costs do not stand there.

**Only an outage is red.** A background job counts as down when the engine
files it with severity high (gone, disabled, stopped, its last run failed),
as upkeep when medium (drifted, a unit without its marker, a program outside
the repository). Only the jobs that are down colour anything: the Background
jobs tab or its place in the folder bar (a red count, none for upkeep), its tile on Start
(red with the count, neutral with upkeep alone, green when nothing), the news
band. The tile's line reads "3 down, 25 to tend, 59 of 87 fine". The engine's
own page keeps its own count.

**Sub pages and folders.** A profile page with `under: <page>` has no tab: the
page it stands under becomes a folder. Under the tabs, on the folder and on each
of its pages, stands one bar of its places: "Overview" (the folder page itself),
then each sub page in the order `view.pages` lists them, each with a dot and a
short note ("1 down", "4 warnings", "unreadable"), the open one marked. The bar
is the way back on every width (it scrolls sideways on a narrow screen). The
folder's tab keeps its badge, lit while a sub page is open and red with the
outages and findings of its sub pages (upkeep and warnings never colour it), and
carries a small ▾ beside its name with the same places and marks; a click on the
tab itself always opens the overview. The Background jobs page is placed the same
way with an entry of its own, `{id: "@workers", under: <page>}`. A place is red
with findings or an unreadable source (Background jobs only with an outage),
orange with warnings (one by its title, several as "n warnings in <section>"),
else neutral, and green only where an alarm section of that page reports nothing,
so rows that nothing measures live never look in order. Drop the line `under:`
and the page is a tab again, in the place its listing gives it.

**Machines.** The overview of a folder lists each machine once, right under its
head: every host a background job runs on, and every machine a sub page names in
a row of its own that names a known machine (a job's host, or a machine of
`bridge-resources.py machines`, read by the row's source id `machine:<name>`):
by its tag `Remote`, its id `pc:<name>`, else its title. A line names the
machine, "always on" for the always-on one, else its state from the inventory
without the device word ("Windows 11 Pro · offline"), how many jobs run there,
how many are down and to tend, and a chip for each sub page that names it with
what it says there ("Lab: off"); a machine no job runs on still has its line
when a sub page names it. A click
on the line opens Background jobs filtered to that machine (or the page that
names it when no job runs there), a chip opens its page. Machines nothing runs on
and no sub page names (a printer, a watch) are not listed.

**Background jobs.** Every way in shows every job, grouped by machine: the
always-on machine first, then those with an outage, then by the most jobs, each
with its count, "n down" and "n to tend" in its head. Inside a machine stand its
systems, those with an outage first, each job worst first; a row names its kind
before its purpose (appointment, interval, service, agent, watcher), and under its schedule
the last run and the next one ("last run 21:01 · next run 06:05", the day in
front when not today). Only findings are marked. The head names every machine
the list holds, a line under it says the scheduled workflows are these jobs too,
and the search answers to a job's kind in both languages and to the words a
person uses for them: every job to "worker" and "job", an appointment or
interval to "workflow". The count of units a machine runs without a declaration
stands only while the filter leaves a job. The chips filter by machine
first, then by state, kind and area; "Only with a finding" and "Only outages"
are filters there, off by default. The figures on top count In service, Down,
To tend, Not reported and Retired. An open job row offers two things.
**Analyse in a tab** (verb `worker_advise {host, id}`) files the job to the
inbox under the fixed key `worker:<host>:<id>` with a brief the server builds
from `workers-view.json` (job, machine, unit, kind, schedule, program, log,
last and next run, every finding with its hint) and starts a reporting tab
that reads the job's declaration, checks unit and log live, names the cause
and proposes a fix without changing anything. The click is an order: it goes
on the item as its start note, so the tab never closes the item on its own,
not even as overtaken, and asks before it closes (the same rule as a handoff
with an order, below). A second click finds the same item; an item the person
dropped for that job is opened again first. While the item is open and its tab
is there the row says "in a tab" with **Open tab**; just started it says
"starting"; with no tab left it says "tab ended" and offers the analysis again.
Once it ended, its result from the return channel stands under the findings,
and the closed row says "result in". A finding reads as the job wrote it,
quoted after its state. **Ask** asks the quick chat about the job (kind
`worker`): the server words the question from the view, the finding quoted at
its end on one line of at most 300 characters, and ties it to the row
(`about.key: worker:<host>:<id>`), which the question keeps when it is handed
on (the item is added beside it). A row asked before shows that question
instead of a second one, as "question open", "answered", "no answer" (its last
turn failed) or, once handed on, the marker every question list shows (in its
tab, done, asks you, tab ended), with **Open** and a quiet **Ask again** beside
it; a page row (`InfoRow`) does the same under its own key. A job with a high or medium finding has **Seen** on its open row, last after Analyse in a tab and Ask (a page row
that is bad or warn has it among its buttons, "Settled this time: grey until the finding
changes"): the finding as it stands now turns grey with the day and the close note, and counts
toward no red tile, no badge and no alarm; a new finding (another fingerprint: state and
detail, so a new failure time; a span of time in the words, "4210s ago" or "3 h ago", counts as
one mark, so a finding that only grows older stays seen) is red again, and **Show again** takes it back. A seen row offers no new analysis while no item of it is open. Closing the inbox
item of a job (key `worker:<host>:<id>`, which is the item Analyse in a tab files, or a question handed over
about it) does the same
with its close note, when the close came after the job's newest failure; the cockpit sees that close on
its next look at the inbox, an item that was already there included. A close it read once stays read on
every machine, so Show again holds. The decision lives in
`work/cockpit/settled/` beside the hides, as act `ack`. A section with `hide_ok: true` is drawn only while one of
its rows is bad or its source fails; it still feeds the page's number, the
alarm and what other cards read from it ([`briefings.md`](briefings.md)
§ Dashboard pages).

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
as before; a sub page (`under:` a folder) shows none, since they stand on the
folder's overview. A card named twice stands where it is first named; when the page
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
What goes out is title, kind, status, the triage's one-line gist, the label and
the priority. Rows stay home when their section is in `skip_sections` or when
their title, detail, task, source (who filed an inbox item) or gist holds a
`private` word; what the triage marked goes too, and a row without an inbox item
or a task by its page key. More rows than one request holds (60) go in batches,
at most three. Prio's read-in on Work through sends the points of its view
instead (see Prio above). The strip names how many
were left out and why, and the tokens the order took. A work page of `group:
work` has no strip: its By Jev view asks with `daily`, so the first look of a
day orders by itself and every later one that day shows the kept order, and its
button orders anew. The same filter applies to both.

A page holding inbox and task rows together also filters by kind: one chip
per label (Inbox, Task, or a section's short title) with its count, for the
sections, the triage strip and Jev's list alike. Without Work through such a
page is also where the task check stands (with Work through on, the check is its
row under Not now, and this page shows one line with a link there): its own tab goes, and the Task chip shows the check (run,
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

- **The Jev tab** sends up to 60 rows it shows (briefing sections first, then
  tasks) with only these fields where a row has them: title, why, priority,
  urgency, due, area, gate, bucket, section, task type, inbox state. It sends
  every such row; it has no private filter.
- **A work page with `jev:`** sends only a row's title, kind, status, the
  triage's one-line gist, its section and its priority. It leaves out the
  sections in `skip_sections` and every row whose title, detail, task, source
  or gist holds a `private` word.
- **Prio's read-in** (Work through) sends per point title, kind, status, due in
  words, running, age in days and the gist, held back only by the work page's
  `private` words; with Read in with Haiku the same goes to Claude instead.

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

The page **Settings** (behind More) opens on Setup ([The Setup page](#the-setup-page)) and has
the areas Start page, Appearance and Model choice. Model choice shows every key above in three cards (the
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

**One decision under both keys.** An issue that stands in the work tab (keyed
`ref:<id>`) and on a GitHub page (`item:<page>/<section>/<id>`) is one row to
decide: Later, Done and Show again from either side act under both keys, on the
page, in its "more" list and in Work through, and the work row names the GitHub
list it stands in as `on_board: {page, section}` (null where none). A new
decision replaces what the other key held, so one issue never holds two dates.
Only a tracker list twins: a command list or an alarm section keeps its rows, so
a Later in Work through never takes a failing probe off its page or its alarm.

**GitHub work with steps.** A `github-work` section (docs/briefings.md § GitHub
work) on a page with `view: board` lists one row per issue or pull request
under its board: the board's status (the field `board.status_field` of its
registry names, default `Status`), its priority as a chip when the registry
names a `board.priority_field`, the pull requests that close it, the task of
this Bridge that syncs it. The rows of a board sort by state, by priority (P1
before P2 before P3, a row without one last; offered only when a row carries
one) or newest first. Every row of the section is loaded (up to 300, where a
plain table stops at 50 with "more n"), so search and filter see them all.
Above the rows stand only the figures that have a cause and a count above
zero (wanting your review, blocked, quiet, yours without a task); a click on one
filters the rows, a second clears it. Under them a filter bar: **Board** (each
board, and "no board"), **Assigned to** ("Me" first, then every assignee by
count, "nobody" last), **Opened by** ("Me", then every author; a draft card names
its creator), **Repository**, **Kind** (issue, pull request, draft
card) and **Board status** (the column, rows on a board only, one option whatever its case), each a compact
select that shows only with two values or more among all rows (one that another
choice narrowed to a single value keeps its place with that value), every option
with how many rows it would leave given the other choices. The choices combine with each other,
with the figures and with the search (which also reads author and board); "n of N
rows" and "Reset all filters" stand beside them while one is set. The choice is
kept per section in this browser. Your own login is read from the rows (the
author of a row you opened, else the one assignee of a row assigned to you);
where no row says, the login stands beside Me. A row names repo#number (no GitHub chip beside it, the ref says so), its
column, up to three labels with "+n" for the rest, "assigned: @a, @b" (up to three,
or "nobody assigned") and "opened by @x" ("opened by you" for yours), and for a pull request draft,
review and checks (80 rows at most, yours before a teammate's card and pull
requests first among them, read in the call that finds the pull requests that
close an issue, no extra call). "Group by board" (on by default)
switches to one flat list where each row names its board. A click on a name on a
row sets that filter (Assigned to or Opened by) beside the other choices; a
Person kept before round 6d reads back as Assigned to. The line "n on
GitHub" in Work through leads here with the filter cleared, so the page shows
the rows it counted. Under each board's head in the list stand its facts: whose cards
(yours or every card), how many are open on the board, the count per state
with its dot, and the cut where the board was read only in part. Which cards a
board loads (Off, Mine, All) is set in Settings, GitHub boards ("Which boards to
load" above the rows leads there). With All a teammate's card stands here and in
the filters, never among the rows of Work. Opening a row reads its
issue or pull request (description, last comments, labels, boards, review and
checks) and shows its steps as buttons. A row has one start, a split button: its
lead step on the left, ▾ beside it with the other steps, and **To tab** in the
lead's place while an agent works on the row; **Close** stands beside it. The
steps start an agent tab
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
§ Dashboard pages) opens with two figures: the events that collide (a click
filters the list to them) and the longest free block left today. The next
event stands on Start, due rows in Work, where Later holds them. Below, Agenda,
Week and Month switch the view (the choice is kept in the browser); the month
is offered once the loaded dates span four weeks, and a month kept from before
shows the agenda until then. The agenda lists the events by day under a head
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

**A settled row stays settled on every machine.** That a row is hidden until a
day, or out of the briefing as done or not doing, is itself written to
`work/cockpit/settled/`, which git tracks: one new file per decision, written
once and never changed, the way the inbox records its events. Two machines that
settle rows and sync through git only ever add different files, so a rebase has
nothing to merge. "Show again" and an undo are a file of their own too
(`act: unsettle`), never a deletion, since a file removed on one machine while
the other still holds it is exactly the conflict this layout avoids. For each
row the newest file decides. The page reads the folder on every pass and the
watcher notices when a pull brings a new file, so a row settled elsewhere
leaves the page within seconds. Commit the folder with the rest of `work/`; see
"Upgrading: settled rows in git" in section 6.

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
closed, dropped, settled or hid, by day, each with its way back: a task back
to the status it had ("open again" to doing, "back in review", or "still to be
done", back to the backlog with a note; an entry from before this knew no
status and reopens as doing), an inbox item "open again" (`inbox.py reopen`),
any other row "show again". Above each day's entries stand its notes
("Notes (n)", the newest first, today's under "Today, <day>"): the toasts of
that day, each a click to the place it names; the bell in the header lists the
same notes, newest first.
What was taken back says when. Closes from before the history
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

Toasts report every action, and the history keeps the last 20 notes under
their day (`at_ms` dates a note). A tab that starts waiting for you is announced
as a toast only while that tab is out of sight (not while its tab view is open,
nor while the Chat shows it as the room of its area); the note lands in the
history either way, and a tab running over an hour always toasts. With
`voice: true` the browser also says it.

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
toast or a note in the history with `go` is one button: a click dismisses the
toast (or closes the history) and goes there; the close X and Undo stay apart
and never navigate. Tab alerts lead to their tab, a start that answered to its
row, an answered chat or agent to its conversation, and the band's status
list uses the same targets for its notes. At most four toasts stand at once:
one more does not vanish silently, a last compact toast says "+N more" and
opens the history, where every note still is.

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

A section that only adds noise or cost can be left out of the triage:
`work.review.skip_sections` lists briefing section ids (the `sources` of a row),
for example `[applications]`. Its tracker rows (a board card, an issue, an
application, a date: a `ref` with no task and no inbox item) are not sent to a
model and are not in `.bridge/triage.json`, so they keep the bucket the
briefing gave them and carry no triage mark. A row that two sections carry is
skipped only when both are listed. Open tasks and inbox items are judged from
their own lists whatever section shows them, so the key does not leave those out.

**Upgrading.** Opt-in, nothing changes until the key is set: an instance that
does not have `work.review.skip_sections` judges every row as before. To leave
a section out, add its id under `work.review` in `bridge-config.yaml`, then
run "sort again"; rows already in the cache from that section simply stop
being listed.

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

"Describe" on a card (`describe_run {key}`) asks for one item now; it counts
against the budget but is never refused. The Work through page writes the
briefs of its next cards ahead (`describe_run {key, ahead: true}`): those runs
are refused with `describe_budget` once the hour's budget is spent. With

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
action}`, which calls `briefing.py act` and voids the section's cache, and again
after each wait of a `recheck` the step returned (docs/briefings.md). A step
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
- **Over it all**, where it applies: why the relay is off, with the start
  control, and that the control session does not listen to it (the header's
  relay badge leads here where Work through lists the sessions); "no terminal
  driver" and "tab list not current since" with the reason, as the tab column
  shows them. A tab open on the right names its task ("Task <title>", from the
  tab's own task or the newest live session in it), which opens in the item
  drawer over the Chat. Its head also says where it came from, "from: <title>"
  (de: aus: <Titel>), for the question, background job, inbox item or other task
  it was started from: a click opens the question in the Chat, the job on the
  Background jobs page, the item or task in the drawer. The same words stand as
  a second line of the tab's row in the sidebar. Where the origin is the tab's
  own task only the task link shows. The head carries the tab's close (above,
  **One close for every tab**) beside it.
- **In Work, near the top**, "Waiting for you" lists the tabs that wait for
  you or need you, the most urgent first (the control tab never), one short entry
  each: its dot, its name and how long it has been in its state (one word more
  only where that state is not waiting), and under it one line of where it
  stands, its workspace and what it asks or its last words, so two tabs of one
  name read apart; its whole question is the entry's tooltip. How long survives
  a restart of the server (`tabs-seen.json`). A click on the line opens the tab on the right,
  where its question and the answers stand, see [Answering a tab from
  here](#answering-a-tab-from-here); the list itself answers nothing and closes
  nothing: a tab that asks nothing closes from its head on the right, which then
  opens the next one, so the list stays one line a tab. In its workspace below the same
  tab is a grey row saying "waiting", so it is not read twice. A
  tab that has been in one state unusually long (`long`: working for an hour, or
  a filed result waiting a long time) stands there too, so it is not
  forgotten. While the pointer or the focus
  is in the group its rows keep their order, and a tab that starts asking is
  added at the end; the sorted order comes back when the pointer leaves, so a
  click never lands on a row that was pushed under it.
- **Below it** stand the workspaces in the terminal's order, pinned ones first.
  Each shows its colour, its state, its unread count and, when its folder is
  another Bridge's clone, that Bridge's name. Below each workspace are its tabs,
  most urgent first.
- **The questions** (de: Fragen) have a section of their own directly under
  "Waiting for you", above the workspaces, in every sort mode (with "By status",
  right under the order bar), so a question just asked is found without
  scrolling: open and handed questions first, then the answered ones, newest
  first in each. Its head has "+ New question". A question stays in the list
  `chat_keep_hours` after it last moved (its last turn, its handoff or what came
  back from it) and then stands in the archive. Each carries
  its title (below) on a line of its own and under it, once handed on, its marker
  and its time. "Earlier questions too"
  also reads the archive (`GET /api/chats/archive?days=7`, read only: at most
  14 days and 60 questions, newest first, without the ones you removed); those
  stand greyed, have no ×, and open read only, and an archive with none says so.
- **Below the workspaces** come the other Bridges on this machine that have no
  workspace ("Bridges on this machine"). The A2A agents stand in their own area.
- **On the right** is what you picked:
  - a tab's terminal, read every 1.5 s to 5 s (slower while it stays the same),
    with "Write" to open it in its window with the message box and keys;
  - a quick chat with its box. The box is one field, "Question or order" (de:
    Frage oder Auftrag), with two buttons that never change: **Ask** (de: Fragen)
    asks here, read only, and **Let AI do it** (de: AI machen lassen) starts an
    agent tab. Nothing guesses from the words any more, and no chip or hint
    stands under the field. On the Chat page the header's Ask puts the cursor
    into this field instead of opening a window. The field and the buttons name
    no keys (the cockpit is used by mouse first); Enter asks and Cmd or Ctrl
    Enter starts the tab still. Once the chat is handed on, a status line stands
    under the field (see [5. Asking Claude](#5-asking-claude-the-relay)). There
    is no countdown and no timer;
  - an agent with its conversations;
  - a Bridge's folder and how to work in it.

**The Chat opens where you were.** Every room you pick, a tab, a workspace, a
question or a Bridge, is kept in this browser (`bridge-cockpit.chatRoom`), and
the Chat opens there next time. A kept tab or workspace that is gone opens the
chat instead. With nothing kept the Chat picks once, as soon as the questions
and the tabs are read: an open question or one answered within the hour, else
the first tab that waits for you. It never switches on its own after that.

**Chats leave on their own.** A chat started from a briefing row leaves when its
item closes, once it has been quiet for 10 minutes. A chat handed to a tab stays
`chat_keep_hours` (a day by default; 0 keeps it) after the latest of its
handoff, what came back from its item and the item's end, so its result can
still be read there. The chat
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
chip ("3 working · 5 subagents · 2 AI runs") adds up this Bridge's tabs and
opens the Sessions page on a click. It says AI runs, not workflows, for the
Claude workflows of a session: to a person the workflows are what the machines
run, under Background jobs, which its tooltip names.

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
tab, or the close in its head (for a tab that neither works nor asks),
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

### The Setup page

The first time someone opens the cockpit it should help them set the Bridge up; opened again later,
the same place should say what still keeps the cockpit from working well. That place is the area
**Setup** (de: Einrichtung) of **Settings**, the first of its areas. It is made of three ordinary
`command` sections of `scripts/bridge-setup.py`, which the cockpit collects with `briefing.py
collect --setup` (`cockpit.setup: false` leaves them and the area out). They travel as a page of
the view like any other (id `setup`, group `settings`), so a row keeps its key, its filing and its
sweep, but that page has no tab and no place behind More: Settings, Setup draws its sections with
the same rows and steps a page has. A finding of the checks shows without opening Settings: the
Settings tab carries the count (red for a red finding, and More wears its colour when Settings is
folded behind it), and a link, a tile or the band that names the page opens Settings at Setup:

- **What keeps the cockpit from working well** (`setup-checks`): a row only when something is
  actually wrong, none when all is well. Task management is off (`work.enabled`), so the work pages
  stay empty; no terminal driver starts agent tabs, so Let AI do it starts nothing (asked through
  `workplace.py caps`, the same answer `bridge-cockpit.py status` reads; no answer is no finding);
  no machine is named in `inbox.runner`, so a yes given on the page runs on whichever machine calls
  `inbox.py run` ([`inbox.md`](inbox.md)); only the built-in briefing profile, or a profile copied
  from `workflow/briefings/_template.yaml` that still holds a placeholder of the template (such as
  `your-org` in the owners of its GitHub section), which finds nothing and reports no error; GitHub
  switched on but `gh` missing or not signed in (red); and the keys of the `cockpit:` block that do
  not work as written (the warnings of `status`); a service that is switched on but whose
  `workflow/ai-services/` file names a provider its code cannot run, or cannot be used
  (`provider_gaps` of `status`, [`ai-services.md`](ai-services.md)).
  Each detail says what to do, with the exact key or command.
- **Can be switched on** (`setup-available`): the features of the onboarding catalogue that are off
  here and offered (Jev only with a key configured, the relay only when `mods/cockpit-relay/`
  exists, the Bridge-Deck never), each with the step that switches it on, in the order
  `purpose.focus` gives. A feature put off shows dim with its date until `remind_after` and then as
  before; one silenced, or declined during onboarding, never shows.
- **Switched on** (`setup-on`): what is on, information only.

A finding gets the steps every finding has: Let AI do it, Advise, Close and Later. Let AI do it files
the row to the inbox and starts an agent tab on it; once the problem is fixed the row is gone, and
after the next full pass the cockpit closes the item it filed, so a fixed problem disappears by
itself. A row of the catalogue offers Let AI do it too, and the agent tab runs the catalogue's own
step for it (`/bridge-onboard --add <feature>`, or the config key it names), where the person
confirms. Its own steps are the onboarding's decisions, **Ask again in 30 days** and **Not for
me**; the cockpit's Later beside them only hides the row on this page until a day.

What the page never does: switch a feature on, or write `bridge-config.yaml`. Its checks read only
this Bridge's files (so `discovery.mode: confined` holds), with two probes of five seconds each:
the terminal driver through the Bridge's own `workplace.py`, and `gh auth status` only while
`integrations.github.enabled` is true. It never scans the machine. The one write is Ask again in 30
days and Not for me: `work/onboarding-state.yaml`, in the schema of the onboarding's Discovery State
(`deferred` with `remind_after` 30 days on, or `silenced`), through `briefing.py act` like any step
of a command row. A file it cannot read, or one that is not a mapping, is refused and left as it
is; a step reads, changes and replaces it under a lock (`.bridge/setup.lock`), so two clicks side
by side lose nothing, and the file keeps its mode, but not its comments. The undo token carries
what stood there before (status, `remind_after`, `decided_at`) and a digest of what the step
wrote: the script restores that entry exactly, and refuses once the entry changed since. The catalogue
behind the page is `skills/bridge-onboard/references/features.yaml`, one entry per feature of
`feature-catalog.md`; a test holds the two equal. A profile can place any of the three sections
on a page of its own (`view.pages`), where it stands with a tab as before and counts there; the
ids are reserved, so no profile section may take one.

The first visit's welcome offers **Set up first** beside Start the tour and Skip while the checks
have a row: it opens Settings at Setup and closes the welcome without ending the tour, so the next
visit offers the tour again.

### The first-run tour

The first time the page opens it offers a short tour, the way other tools introduce
themselves: a welcome with "Start the tour" and "Skip", then one step per area with
that area lit up and the rest dimmed: the tabs on top, Start, Today, the agent tabs
(not on a narrow screen), Ask, Sessions (Running now where Work through lists the
sessions), Help and settings. Next and Back go
through it (also the arrow keys), a step opens the page it shows, and the end goes
back to the page where it began. Skip or `Esc` ends it at any step. While the Setup page has a finding the welcome also offers
**Set up first** ([The Setup page](#the-setup-page)).

How it ended (finished or skipped, with the date) is kept on the server in
`state.json`, key `tour`, so another browser does not offer it again. Help in the
header, Settings, Appearance, Introduction and the bar of Explain start it again at
any time; Settings
can also offer it again on the next visit (verb `tour_reset`). `cockpit.tour:
false` switches the offer off for a Bridge whose people know the page; the buttons
still start it. In mock mode it stays closed unless the link carries `&tour=1`.

### Explain this page

"Explain", the first item of Help in the header (`?` with the shortcuts on), lays notes over the page as it
stands: each area the page shows gets a numbered note beside it, a ring around it
(an ellipse for a button or a chip, a frame for a row or a column) and an arrow from
the note to the ring. Every page explains its own parts: Start, Today, Chat,
Files, Sessions, Background jobs, A2A connections, Check tasks, Jev and Settings each have
their own list (Settings at its area Setup one of the three lists there), and a page of the briefing profile explains the parts it is built from
(the count beside its title, the overview tiles, the sorting bars, a section's
head, its rows, the GitHub figures, filters and boards, the quota gauges, the costs, the
dates, the folder bar, the machines and a sub page's head card). The notes come in rounds so none covers another: the page first, the header
(views, As of, Tabs, Ask, History, Notes, Claude, Help) in a round of its own after
it, read from left to right. Next, Back and the arrow keys page through the rounds,
and the bar says which round shows and how many areas stand further down (scroll,
and they follow). An area the page does not show right now is left out. A click
anywhere or `Esc` closes it, and its bar starts the tour. It sends nothing.

**What bothers you here?** (de: Was stört hier?) in the bar opens a short field
(300 characters). While it is open, a click on a note picks that area instead of
closing the window, and a click beside the notes closes nothing, so a slight miss
never loses the sentence; **Cancel** closes the field. **Note it** keeps the sentence with the page, view and area
as a proposal in `work/_learning/proposals/` for the next round of
`/bridge-learn` (verb `explain_note`); the window says it was noted and that
nothing was sent. The audit line names the place, never the sentence.

**What the page is used for.** With `cockpit.usage.clicks` on (the default) the
page counts which control was clicked from which page, view and area, by the
control's name (its `data-u` or its own classes, never its words), and sends
the counts in small batches (`POST /api/clicks`, every 30 seconds while the
page shows and when it hides). The server keeps only those names and drops any
event that holds words, an item key or a path. `scripts/cockpit-usage.py`
counts this log and `audit.log` since its last run (14 days on the first,
`--days n` or `--since YYYY-MM-DD`) and proposes, at most 10 a run and never
twice for one topic, what may go: pages no longer opened, areas and controls
not used (judged only over 14 days the click log covers), pages left again
within 5 seconds, and back and forth between two pages. Each becomes a proposal
in `work/_learning/proposals/` for `/bridge-learn`; `--dry-run` writes nothing.
Nothing runs it on a timer: run it at the start of a round.

### Look up

The card **Look up** in Settings, Appearance (between Keyboard shortcuts and
Introduction; Help in the header opens it on any of its topics) shows one topic
at a time: **Rows** says what a row's mark and
its section mean; **Acting** covers the panel, Let AI do it, Advise, Close and
Ask; **Keys** lists the shortcuts while they are on, and while they are off says
only that they are off and where to switch them on (mouse first: no key named;
the Help menu offers Keys only while they are on);
**Costs and safety** says what spends tokens and what leaves the
machine. What a part of the page is for, Explain shows on the page itself.

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
| `?` | explain this page |

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
  close, settle (done or not doing), shelve (a task parked as an idea, with its
  reason), urgency, priority, note, attach (a document into a task's
  deliverables), merge (open tasks into one, and its undo), check tasks, keep
  open, close task, files ask, launch,
  adopt, send, key,
  close tab, done and close tab, finding seen, explain note, snapshot, ticker
  settings, ticker refresh, ticker edit, ticker profile, guide read, guide
  settings), every id
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
  (one call, no tools, it keeps only tab refs and task slugs from the answer),
  the summary of a point's Activity, the instruction line of Work through and
  Ask AI on the Files tab (each one call with no tools, no settings and no
  session, its own JSON schema; Ask AI sends at most 12 records as data, never
  one the block list of `cockpit.files_search` holds, and keeps only the record
  numbers its answer names;
  the instruction line's answer is only a plan the page shows, checked against
  the verbs each point offers, and nothing runs before your click on Run), two
  read-only `git log` shapes over one task's `deliverables/` and its
  `STATUS.md` (five seconds each, the folder checked against
  `work/tasks/<slug>` or `work/streams/<slug>`)
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
- a document of a task (`GET /api/flow/doc`) is served only from below that
  task's `deliverables/`, with no link on the way and only a regular file, and
  never runs as a page of the cockpit: an HTML file opens sandboxed (its
  scripts cannot reach the cockpit, the network or a form), an image or a text
  file under a policy that loads nothing else, a PDF in the browser's viewer,
  anything else as a download. An attached document (`POST /api/flow/attach`,
  off unless `cockpit.flow.attach.enabled`) goes only into the deliverables
  folder of an open task, as a new file (never over one), under a name cleaned
  of paths and odd characters, within `max_mb`; this one route takes a larger
  body, every other POST stays at 64 KB. Its audit line names the row and the
  size, never the file's name;
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
- the Setup page switches nothing on and never writes `bridge-config.yaml`: its rows are
  `briefing.py` command sections of `scripts/bridge-setup.py`, which reads only this Bridge's files
  and probes `gh` only while GitHub is switched on; its one write is Ask again in 30 days and Not for me into
  `work/onboarding-state.yaml`, through the same row step and undo as any command row, no verb of
  its own ([The Setup page](#the-setup-page));
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
  `GET /api/timeline` is the same kind of read: `scripts/work-find.py
  --history` through the runner, the words one argument after `--`, the
  transcripts' folder only where the config names one that exists.
  `GET /api/records` is a read too: the records of the Files tab's list
  (every task, stream and closed task, its front matter read in place, newest
  first, at most 2000), no runner call and no line. So is
  `GET /api/chats/archive?days=n`: the questions of the archive of the last
  1 to 14 days, at most 60, never the removed ones.
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
by the button you click (see [The chat as cmux](#the-chat-as-cmux)): Ask for
the quick read-only answer above, Let AI do it for a real Claude session in a
cmux tab, which may act. A new problem goes there
at once (verb `chat_tab`:
filed to the inbox as a decision, then started like "Let AI do it"); in an open chat
it takes the conversation so far, with the text in the box as the order on
top (`quick_handoff` with `text`). Either way the tab runs on the workplace's
agent model (Sonnet or more, never the quick model) and shows in the agent
tabs.

**Where a handed on chat went.** A chat handed on carries a record of it
(`handed` on the conversation: where to, when, and the status), and the box
shows it as a status line under the field. The record is claimed
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
with `chat_tab` gets the same line from its reply (`inbox_id`, `launch`). **Open the tab** opens the tab in the cockpit (its
room in the Chat as cmux, else its window); **Show in the terminal** beside it,
where the driver can focus, is the second way. A tab that waits on you says
"Its tab asks you". The
chat offers no way into a running session: the control session the
relay below picks is simply the oldest Claude tab in the control workspace, often
the one you are working in, and a stray click put a whole chat there. With
`cockpit.relay: false` no tab counts as the control session at all, "Advise"
on a row without a task files it to the inbox and starts a reporting tab, and a
question `via` control answers `relay_disabled`. An answer that arrives while
the chat is not in view shows as a note with "View".

**What came back.** On each sweep the cockpit copies onto the chat what came
from its inbox item since the handoff (`handed.outcome`: `{text, closed,
at_ms, asks}`, quick.py `handoff_outcome`; the person's own start note does
not count). The status line then reads "Result: ..." (a note, closed or not),
"Asks you: ..." (a note headed `Question:` or `Frage:`) or "Done, without a
note"; the same text stands under the last turn, and every question list marks
the chat (logic.js `askOutcome`, `askMark`). An order typed with the handoff
(`quick_handoff` with `text`) goes on the new item as "Start note: ..." and
the tab starts with it, told never to close the item on its own: it writes its
result as a note `Result: ...` and asks before closing with a note
`Question: ...`. Its prompt then keeps no rule to close on its own (neither "close
it when settled" nor the rule for an overtaken item), so the two never disagree.
Every start of an inbox item with a start note gets that rule, and so does "Let
AI do it" or "Advise" with a note typed on an inbox row, and Analyse in a tab on
a job. A second handoff while the first tab is still starting or already at
work writes the order once, as the start note, and says to type it into that
tab too. A handoff whose tab is gone three minutes after the start without a
word (as Work's "Tab gone") reads "Tab ended without a word" with **Start
again** and **Open the item**, and its question carries the marker "tab ended"
instead of "in its tab".

**Titles of questions.** A question is named by what it is about: the job with
its machine and state, and for a failure its day ("chat-bot · mini · last run
failed 10/16"; a question about a job from before it carried that is read from
its own opening words, never the trace copied into it), else the row, task or
inbox item it was asked on, else
its first sentence (or the title in «» of a row's prompt), cut at a word.
Titles that read alike carry when they were asked ("today 07:34", "yesterday
...", "20.10. ..."). The question window, the Chat page, the cmux sidebar and
the head of an open chat use them. The question opened last is kept in this
browser (`bridge-cockpit.lastAsk`), so a reload and the header's Ask open it
again; a follow up goes on in it only while the server still lists it.

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

Everything lives under `.bridge/cockpit/` in the Bridge root, which git ignores,
except the record of settled rows in `work/cockpit/settled/` (below).
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
| `usage.jsonl` | the click origin log (`cockpit.usage.clicks`): per minute which control from which page, view and area, with the verb it sent and a count; rotated at 256 KB to `usage.jsonl.1`; read by `scripts/cockpit-usage.py` | no: names from the code and counts only |
| `usage-run.json` | when `scripts/cockpit-usage.py` last ran without `--dry-run`, the start of its next period | no |
| `history.json` | what was closed, dropped, settled or hid, with its undo (readable by you only) | yes: the titles |
| `state.json` | team runs started from the page, the start page's tiles and pins, how the first-run tour ended, the workflow runs marked as checked, the sessions said not to work on a task (`session_refused`: per session id the slugs Not this task named, at most 8 each); and this machine's copy of the rows hidden or marked done or not doing (the shared record is `work/cockpit/settled/`, below) | yes: the title of each row marked done or not doing |
| `view.json` | the last briefing, shown at once on the next start until a fresh one arrives | yes: the whole briefing |
| `days.json` | the day book: each quota's use per day and the counts of each day (section 3), two weeks | no: numbers under ids |
| `launches.json` | the starts of the last days for the return channel, with model, effort and who chose them | yes: the titles |
| `tabs-seen.json` | since when each agent tab is in its state, so how long a tab has waited survives a restart of the server | no: tab ids and times only |
| `launch.json` | the settings page's changes to `cockpit.launch_model` (only keys that differ from the config) | no |
| `ticker.json` | the settings page's changes to `cockpit.ticker` (only keys that differ from the config) | no |
| `guide.json` | the settings page's switches of `cockpit.session_guide` (only those that differ from the config) | no |
| `ticker-cache.json` | the news ticker's last feed items, each feed's state and the last editor result, shown at once on the next start | no: news items only |
| `quick.json` | the chats, the last 30, with every question and answer (readable by you only) | yes: the chats |
| `chats/` | every chat and agent conversation that left its list, whole, one file a month (`quick-YYYY-MM.jsonl`, `agents-YYYY-MM.jsonl`), never deleted (folder and files readable by you only) | yes: the chats |
| `agents.json` | the conversations with other Bridges and A2A agents (readable by you only) | yes: the conversations |
| `jev.json` | Jev's last rating and today's token total | yes: the titles it rated |
| `jev-pages.json` | the order per page, by Jev or by Haiku (Prio's read-in: which ranker made it, when, how many points, held back, merged, the fallback if one ran) | yes: the titles and Haiku's reasons |
| `flow-prio.json` | the read-ins with Haiku of the last day (`prio.py`, `cockpit.flow.prio.haiku.budget_per_day`): the time and cost of each call | no |
| `flow-themes.json` | the themes of Work through (`themes.py`, `cockpit.flow.themes`): the themes with their names, the theme of each open point and whether a person placed it, the suggestion for each point with its half sentence of why, the runs of the last day (the budget), and the last 500 moves of a point from one theme to another (the names as they were, by the AI or a person) for its Activity | yes: theme names and the reasons of the suggestions |
| `flow-activity.json` | Activity of Work through (`activity.py`): the summary of each point kept with the fingerprint of the rows it read, and the calls of the summary, of the instruction line and of Ask AI on the Files tab (under `files`) per day (their budgets) | yes: the summaries |
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
| `.bridge/task-merges.json` | each merge not taken back (`task.py merge`): both STATUS.md files as they were before and after it, so `task.py unmerge` puts them back byte for byte; an undo removes its entry | yes: the whole text of both tasks |
| `.bridge/resources/workers-view.json` | the full worker view of the Resources section (`scripts/bridge-resources.py workers`) | no |
| `.bridge/resources/costs-view.json` | the last cloud cost report with its source, read time and age (`scripts/bridge-resources.py costs`) | no |
| `.bridge/resources/usage-days.json` | the token counts of each closed day per source, model, project and Bridge, 120 days | no: numbers under model, project and Bridge names |

One folder the cockpit writes is **not** under `.bridge/` but tracked, because
it must reach every machine:

| File | What | Inbox or chat text |
|---|---|---|
| `work/cockpit/settled/` | every hide ("not now until <day>"), every row marked done or not doing, every finding marked seen, every "show again", one YAML file each (`<UTC stamp>-<seq>-<rand>-<act>.yaml`, or `legacy-<hash>-<act>.yaml` for an entry migrated from `state.json`), written once, never changed; the newest file for a row decides | yes: the row titles |

### Upgrading: Work through as a view, its themes and the advice

Nothing has to be done by hand; each point is opt-in or read only by a page
that knows it:

1. **No tab `@flow`.** Work through is the last view of the work tab while
   `cockpit.flow.enabled` is true. A page stored as `@flow`, or a link to it,
   opens the work tab in that view; `cockpit.work_view: flow` opens it there
   too. Off, a stored `flow` view opens Due.
2. **Themes.** `cockpit.flow.themes` (off by default) adds `flow-themes.json`
   to the cockpit's folder, the verbs `flow_themes_run`, `flow_theme_move`,
   `flow_theme_new` and `flow_theme_rename`, the state's `themes` and the
   event `themes`. Without them the view groups by area.
3. **The advice of a card.** `/api/ask` takes `origin` (`flow`) and `keys`
   (true or false), both optional and kept by the conversation: asked from a
   card the answer names the card's button and no key, elsewhere it names Cmd
   Enter only with `keys: true`. An older page sends neither and its answers
   name no key any more.

See [Work through](#work-through-flow).

### Upgrading: the tabs, Activity and the instruction line

Nothing has to be done by hand. With `cockpit.flow.enabled: false` nothing
changes at all: every new route and verb answers `409 flow_off`, the verbs
before they read their arguments (a bad argument does not turn it into a 400).

1. **The page.** On an open point of Work through the card carries its content
   only; the verbs moved to the right column (What you can do, under each
   other) and the detail blocks gave way to the tabs under the card and the
   Fields. The tab picked is kept in the browser as `bridge-cockpit.flowTab`.
2. **New routes, read only or behind their own key.** `GET /api/flow/activity`
   (the list of a point) and `GET /api/flow/doc` (a document of a task) need
   only `cockpit.flow.enabled`; `POST /api/flow/attach` also
   `cockpit.flow.attach.enabled` (off by default). A page that does not call
   them is not affected.
3. **New verbs.** `flow_activity_summary` (`cockpit.flow.summary`) and
   `flow_instruct` (`cockpit.flow.instruct`), both off by default, within a
   daily budget, one call at a time, their model from the block or the
   services `cockpit-activity` and `cockpit-instruct` of `workflow/ai-services/`
   (Haiku when none is declared); `flow_attach`, the verb behind the attach
   route. The state gains `flow_ai` (what is left of both budgets today, and
   whether an instruction is being read), which an older page skips. A step of
   the plan names why a point drops out of it (`skipped[].why`): `not_offered`,
   `bad_day`, `unknown_point`, `no_tab`, and `asks` for a reply to a tab that
   asks a choice; a page that does not know a why shows it as it comes.
4. **`by` on four verbs.** `do_it`, `later`, `shelve` and `settle` take an
   optional `by` (`suggestion`, `batch`, `instruction`); the history entry, the
   start and the audit line keep it. Without it the click counts as your own,
   as before.
5. **Files.** `flow-activity.json` joins the cockpit's folder; `flow-themes.json`
   gains `moves`, the last 500 moves of a point between themes; an older
   version ignores them and leaves them out the next time it writes the file,
   so Activity then starts its theme rows anew. Both are runtime files under
   `.bridge/cockpit/`, safe to delete.
6. **Git, optional.** Activity reads two `git log` shapes per task when git is
   there; without it the documents and status changes take the files' own
   times.

See [Work through](#work-through-flow).

### Upgrading: Running now, Not now, Merge and Prio

Nothing has to be done by hand. With `cockpit.flow.enabled: false` no
transcript is read, `flow_merge` answers `409 flow_off` and the page has no
Work through view. One thing changes there too, on the Sessions page: Unlink of
the session of a task's own tab now holds (before, the next poll linked it
again), because `session_unlink` remembers the refusal; the live sessions carry
`task_how` and `task_since_ms` for their links. With Work through on, the view
changes in these ways:

1. **What runs no longer counts as a point.** A start at work, a session at
   work on a task and a task's own tab stand under Running now, out of the
   walk, the overview and the batch. The head says points, running and not
   now, which add up to `model.counts.flow_open`.
2. **Sessions are recognised.** `flow.infer_sessions` is on by default: a live
   session of this Bridge in a tab is read at the end of its own transcript
   (only its messages and tool calls, never a tool's result, no model call)
   for the one open task it names. `sessions_state().sessions[]` gains
   `task_how` (`hand`, `tab`, `seen`) and `task_since_ms`; `task` is the task
   in effect. A link by hand or a start from the cockpit wins.
   `session_unlink` also records a refusal (`session_refused` in `state.json`)
   and answers `session: {sid, refused}`; `session_link` drops it. Set
   `flow.infer_sessions: false` to read no transcript; a refusal holds then
   too, so unlinking a task tab's session keeps it unlinked.
3. **Settled rows are no longer listed.** A hidden row decided here (done, not
   doing) used to show under the old Left out drawer; it is open no longer and
   stands nowhere. The drawer itself gave way to Not now.
4. **Due later waits.** `flow.ahead_days` is 2 by default: a point due further
   ahead than two days, and not of urgency now, waits under Not now, Later,
   until two days before. `366` shows everything at once as before.
5. **Issues in Now are points.** An issue or pull request in the section Now
   (urgency now or today, or to do) is a point of the new group Issues and PRs;
   every other one stands under Watching.
6. **Merge.** Two new verbs, `flow_merge` (behind the flow gate) and its undo
   `task_unmerge` (no gate, only an undo the server handed out), two new error
   codes, `merge_not_task` and `merge_changed`, and the history items `merged`
   and `merged_in`. `task.py` gains `merge`, `unmerge` and `close --merged-into`;
   STATUS.md gains `outcome: merged` and `merged_into`
   ([`work-system.md`](work-system.md)). A task closed as merged keeps its
   `blocked_by` and `blocked_since`; a plain close still drops them. `task.py
   merge` writes `.bridge/task-merges.json`, and `unmerge` restores both files
   from it byte for byte while neither changed since (a brief aside), else it
   edits them as before, now without a note of its own; `unmerge` answers
   `restored`. A merge made before this version has no entry there, so its undo
   takes the edit path.
7. **Rows carry `updated` and `until`.** Task rows carry their STATUS.md
   `last_updated`, deferred inbox rows the day they come back; both are null
   elsewhere, and a reader that does not know them skips them.
8. **Work views.** `cockpit.work_views` (default all five) names the views of
   the work tab's switch, and `work_state()` sends them as `views`; `files` is
   always kept. An older server sends no `views` and the page offers all, as
   before. Once Work through holds everything, `[files, flow]` is enough.
9. **Everything a page shows is in it.** With Work through on the model gains
   `deferred`: the inbox items a page lists (the idea shelf, what runs on) that
   are put off past the briefing's window, as rows (`inbox_state: deferred`,
   `until`), which the verbs reach like any other. Work through also places the
   open tasks of `task_rows` (a stream of folders without a STATUS.md of its own
   too), and a page task carries its `status` from the task list.
   `model.counts.flow_open` counts both, also with Work through off (it is one
   number). An idea put off now stands under Ideas and backlog with its day,
   not under Later.
10. **Running now, Back on, Prio.** An entry of Running now with a task of its
   own has a box for Merge and Done with the points; a batch leaves what runs
   out of a start, Later and Drop (`working`). Back on runs a task again only
   where a blocker stands; a task whose next step names you
   (`cockpit.person_name`, sent as `work.person` while Work through is on) is a
   point, not Waits on others. Prio has Read in with Jev and Read in with
   Haiku at the foot of its left column (`cockpit.flow.prio`; Haiku is off
   until `flow.prio.haiku.enabled`).
   A finished tab no longer counts under Running now, and Running now stands
   only in the left column. A session linked to a task that closed (done, merged) counts as no
   task from then on and is recognised again; the link itself stays for resume.

### Upgrading: one place for each thing

Nothing has to be done by hand: each change is code, and a few profile keys let
a Bridge go further.

1. **The work tab's views.** A view the switch does not offer falls back to
   Work through where it is on (in the page and in `config.py`), and no way
   stores it. `cockpit.work_view: flow` with `cockpit.work_views: [files, flow]`
   leaves Work through and Files; without By source the task check is a tab of
   its own again (Tidy up, behind More only when the bar is full), the triage's
   Sort again stands at the foot of Work through's left column, the band's
   notes on a source, the pass or the triage open the day's status on Start, and
   Explain on the switch names only the views it offers.
2. **Sessions.** With Work through on there is no Sessions tab, and every way to
   it opens Running now. A tab waiting at its prompt and not quiet yet is a
   point (A tab asks); a quiet one (`idle`) stays under Running now as finished.
3. **The header.** As the menu decision has it: no theme or reload button,
   the as-of time reloads; the notes stand under the bell and in the history
   under their day (a note carries `at_ms`; one from an older server counts as
   today's); Help, last, holds Explain first, the look-up topics and the tour,
   so Explain has no button of its own; the colours and Look up stand in
   Settings, Appearance, and `?` opens Explain.
4. **Operations.** `under: <page>` on a profile page and the entry
   `{id: "@workers", under: <page>}` make sub pages, `hide_ok: true` on a
   section entry hides it while all is clear. Delete a section from `sections:`
   rather than only from its page, or `page_rest: show` puts it on a tab More.
   The states `stopped` and `last_run_failed` are red.
5. **GitHub.** A section in the board view loads up to 300 rows; work rows
   carry `on_board`; a decision holds under `ref:<id>` and
   `item:<page>/<section>/<id>` alike.
6. **Dates.** Two figures, and the month only from four weeks of dates. To keep
   due rows off the dates page, take their section off the page and add it to
   `view.page_skip`, since `page_rest: show` would put it on a tab More.

### Upgrading: Files as a tab, the check in Work through, Operations as a folder

Nothing has to be done by hand: each change is code, and the profile keys
below only go further.

1. **Files is a tab.** The work tab's switch no longer offers Files; the Files
   tab stands right after the work tab and opens on its search. A stored or
   configured `files` view (`cockpit.work_view: files`, or a click kept in the
   browser) opens the Files tab once and is replaced by the view the work tab
   falls back to. Every link that opened a task's file opens the tab with that
   record; only a Bridge whose `work_views` keeps no `files` still shows the
   item drawer. With `work_views: [files, flow]` the work tab shows Work
   through alone, without a switch. The page reads the records from the new
   read-only `GET /api/records`, so page and server go together.
2. **Ask AI on the records.** `cockpit.files_search` is a new block, off by
   default: `enabled`, `budget_per_day` (20), `model` and `block`, a list of
   words that keep a record from the model. The verb `files_ask` refuses while
   it is off; its calls count in `flow-activity.json` under `files`.
3. **The task check.** Where Work through is on, the check is the row Check
   tasks above Not now, and its tab goes; a stored page, the ticker, Start and
   every link to it land there. With By source on as well, the check no longer
   stands on that page, which shows one line with a link to Work through.
   Without Work through nothing changes but the name: the tab is Check tasks
   (de: Aufgaben prüfen), no longer Tidy up.
4. **Operations as a folder.** A page with sub pages draws the folder bar on
   top in place of its sub page tiles and the "‹ <parent>" link, and its tab
   carries a ▾ with the same places. The order in `view.pages` is the order of
   the tabs and of the bar. `overview: true` on a sub page gives it a head card
   in place of the tiles. Background jobs always open on every job, grouped by
   machine; a filter kept from before is cleared on the way in.
5. **GitHub.** Rows carry the optional fields `author`, `by_me`, `board`,
   `also_on` and, for a pull request, `pr: {draft, review, checks}`; people and
   labels go up to 10 each, and `untasked` now reaches the page. A reader that
   does not know them skips them. The filters of a section are kept in this
   browser (`bridge-cockpit.ghFilter`), the grouping too
   (`bridge-cockpit.ghGroup`). Board cards of every person come with
   `cards: all` on the section's query or with All in Settings, GitHub boards.
   A card that is not yours (`others`: neither assigned to you nor opened by
   you, nor found by your search) stands on the GitHub page and in its filters
   only, never among the rows of Work, so `cards: all` leaves Due and Work
   through as `cards: mine` had them. Board columns spelled two ways ("In
   Progress", "In progress") are one option of the filter.
6. **Small fixes.** The block of the day once titled Housekeeping (de:
   Aufräumen) is Small fixes (de: Kleine Handgriffe), and each line is a
   sentence that says what to do. The view carries the lines as facts beside
   their text (`tend`: kind, n, names, title, reason); a page of this version
   words a known kind itself, an older one keeps the text.
7. **Smaller.** A sub page with `overview: true` and no `cards:` has no token
   and noise cards any more. The help menu shows Keyboard only while the
   shortcuts are on. The header counts Claude workflows as "AI runs". A drawn
   list shows its When column only where a row has a time.

### Upgrading: quiet tabs and the result line

The return channel used to call every start whose tab stopped working
`asks`, also a tab that was long through. Nothing has to be done by hand:

1. **A new stage `idle`.** `model.returns[].stage` is `asks` only when the
   tab shows a dialog (needs-you) or a question on its screen, or when its
   screen was not read (no driver that serves screens, the questions off, not
   read yet); a still tab whose words read ask nothing, or a tab back at its
   shell, is `idle`. A page of this version shows it as
   "quiet" and files it under "Done, please check". A client that does not
   know `idle` treats a still tab as asking, as before, because it reads the
   tab's state live.
2. **A task's result line.** A note on the task, since the day of the start
   and after the cockpit's own start line of that day, that begins with
   `Result:` (or `Ergebnis:`) turns its start into `result` with `{kind: note}`.
   Older notes and notes with another head change nothing.
3. **Triage rows carry `next_rank` and `rank_at`.** Jev's rank of the row from
   the newest order of a work page, `null` without one or when it is older than
   `cockpit.flow.rank_max_age_days`. Readers that do not know the fields skip
   them.
4. **`cockpit.flow`.** New keys, all with defaults, read only by the Work
   through area, which stays off until `cockpit.flow.enabled: true`: the page
   sorts its tasks by `next_rank`, prepares `prep_ahead` briefs and asks
   before a start once `max_running` agents run. `rerank_per_day` is read by
   no code yet.
5. **`describe_run` takes `ahead`.** Optional, false by default: a run the Work
   through page asks for ahead of a card keeps within
   `describe.budget_per_hour` and is refused with `describe_budget` once it is
   spent. A click sends no `ahead` and runs as before.

### Upgrading: Files in three columns, jobs analysed in a tab, questions found again

Nothing has to be done by hand: each change is code, and the one profile key
below only changes how long a chat stays.

1. **Files.** The Files tab has one layout, the three columns of Work through:
   list on the left, the open record in the middle, its point's buttons on the
   right. The separate start page and the page that replaced the list are
   gone; every link that opened a record lands in this layout, and the head
   button is Close the record (de: Akte schließen).
2. **Background jobs.** New verb `worker_advise {host, id}`, refused
   (`not_applicable`) for a job `workers-view.json` does not hold or one that
   is retired; it files under `worker:<host>:<id>` and starts mode `report`.
   `GET /api/workers` adds `advise: {inbox, state}` to a job filed under its
   key. The quick chat takes the kind `worker {host, id}` (`stale_row` for a
   job the view no longer holds), with `about: {kind: worker, key, inbox}`;
   the page no longer words a job's question itself. A handoff keeps that
   `about` and adds the new item as `inbox`. `worker_advise` writes a start
   note and starts with `--start-note`, and reopens an item of its key that
   was dropped.
3. **Handoff with an order.** `quick_handoff` with `text` writes the order on
   the new item as "Start note: ..." and starts the tab with `--start-note`;
   when that note cannot be written the tab starts without it, as before. An
   inbox start with a start note tells the agent never to close on its own,
   and its prompt drops the rules to close (settled, overtaken). The go prompt
   asks every question to begin with `Question:`.
4. **What came back.** A handed chat gets `handed.outcome` on the sweep
   (`{text, closed, at_ms, asks}`); a reader that does not know it skips it.
   `model.returns[].result` carries `asks: true` for a note headed
   `Question:` or `Frage:` (only when true), and a note "Start note: ..." is
   no answer any more. Each launch row keeps `conv`, the chat it came from.
5. **`chat_keep_hours`.** It now also says how long a chat handed to a tab
   stays after the latest of its handoff, its outcome and its item's end (24
   hours by default, 0 keeps it); other chats still leave 10 minutes after
   their item ended. To have handed chats leave as quickly as before, set it
   low, which also shortens how long untouched chats are kept.
6. **Questions.** New read only `GET /api/chats/archive?days=n` (1 to 14,
   at most 60, without removed, replaced or placed ones). The page keeps the
   question opened last in this browser under `bridge-cockpit.lastAsk`.

### Upgrading: a close for every tab, the Chat in two buttons, the cockpit's use counted

Each change is code; two config keys are worth a look, and one script is new.

1. **`chat_keep_hours: 168`** (recommended) keeps a question a week in the
   Chat's Questions; the default stays 24 hours. An empty chat names the time.
2. **`cockpit.usage.clicks`** (new, `true`): the click origin log
   `usage.jsonl` beside `audit.log`. Set it to `false` to write nothing.
3. **`scripts/cockpit-usage.py`** (new) counts that log and `audit.log` and
   files proposals under `work/_learning/proposals/` (source type
   `cockpit-usage` in `work/_learning/_schema.proposal.yaml`). It keeps its
   last run in `usage-run.json`; nothing starts it on its own.
4. **Tabs.** New verb `tab_done {tab_ref}` (cap `close`) ends the open task and
   the open inbox item behind a tab through Done, then closes it; a partial end
   keeps the tab open (`tab_done_partial`). `tab_close` no longer needs a filed
   result or a settled item: it closes any tab that waits or is back at its
   shell, asks nothing (unless settled) and is not the control tab. A tab
   whose screen holds only its last words asks nothing (`model.asks_something`,
   `logic.js asksSomething`). Each tab
   of `GET /api/state` carries `behind: {task, item}` (null for the control tab).
5. **Chat.** The route chip, its word lists and the leading `?` or `!` are
   gone: a text that starts with `?` is sent as it is. The server's verbs
   (`ask`, `chat_tab`, `quick_handoff`) are unchanged. The browser keeps the
   room picked last under `bridge-cockpit.chatRoom`.
6. **Seen.** New verbs `finding_ack {key, note}` and `finding_unack {key}` for
   a job (`worker:<host>:<id>`) or a page row (`item:<key>`), kept as act `ack`
   in `work/cockpit/settled/`. `GET /api/workers` adds `acked` to a job whose
   finding was marked seen as it still stands. Closing an inbox item under
   `worker:<host>:<id>` marks the job seen with its close note, and an agent
   tab started with an order now writes a close note fit for that.
7. **GitHub.** The filter Person is split into **Assigned to** and **Opened
   by**; a Person kept in this browser reads back as Assigned to.
8. **Explain.** New verb `explain_note {text, page, view, area}` and
   `POST /api/clicks {events}` (at most 60 events; no audit line, as presence).

### Upgrading: settled rows in git

Before this change a hidden or settled row lived only in `.bridge/cockpit/state.json`,
so another machine showed it again. Nothing has to be done by hand:

1. **Migration is automatic.** On its first start the server copies every
   `hidden` and `dismissed` entry of `state.json` into `work/cockpit/settled/`
   as `legacy-<hash>-<act>.yaml`. The name is the hash of the entry, so a second
   start writes nothing, and two machines holding the same entry write the same
   file (git adds it once). A row the folder already decides is not copied, so
   a row taken back on one machine does not return from another machine's old
   `state.json`. `state.json` itself is left as it is.
2. **Commit the folder.** `git add work/cockpit/settled && git commit` on each
   machine, then pull and push as usual (`git pull --rebase`). The files never
   conflict. Until they are committed and pulled, the other machine simply does
   not know them yet.
3. **Going back.** The cockpit keeps writing `hidden` and `dismissed` in
   `state.json` beside the folder, so an older version reads this machine's
   decisions unchanged after a downgrade. What it cannot see are the decisions
   made on other machines since; they are back in force when you upgrade again.
   To drop the shared record as well, remove the folder
   (`git rm -r work/cockpit/settled`) once the older version runs; while the new
   one runs, its next start would fill the folder again from `state.json`.

If `work/cockpit/settled/` cannot be written (a read-only checkout), the cockpit
keeps working from `state.json` alone, as before, and copies what it missed at
a later start.

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
middle of the Today page (section 3); `overview: true`, `jev:` and `under:`
(a sub page, Sub pages) are in section 3 as well.

Every row has the same columns: when, title, detail, link. A page entry
overrides them per section (`when`, `detail`, `link` name an item field),
`empty` is the text for nothing (default "nothing"), `alarm: true` turns every
row into a red finding and nothing more, `badge: false` keeps a section out of
the number on its tab, `hide_ok: true` draws it only while a row is bad. A task's open steps are the unchecked boxes, else the
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
