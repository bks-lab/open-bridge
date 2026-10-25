---
summary: "Plan the day's work as workspaces with one agent tab per task, and steer the tabs from one place, through a driver so the same Bridge works with any terminal tool or none."
type: guide
last_updated: 2026-10-17
related:
  - ../scripts/workplace.py
  - ../scripts/task.py
  - inbox.md
  - ../skills/briefing/references/control.md
  - ../skills/cmux/SKILL.md
  - bridge-cockpit.md
---

# Workplace

One agent per task, each in its own terminal tab, grouped into workspaces (one per
client, one for the platform, one for everything else), and one place from which you
see and steer all of them. The briefing proposes the day ("two clients, five tabs,
want the whole day open?"), you say yes, and the tabs open with an agent that already
read its task.

```bash
python3 scripts/workplace.py propose            # the plan: workspaces, tabs, why
python3 scripts/workplace.py open               # dry run
python3 scripts/workplace.py open --yes         # hand the plan to the driver
python3 scripts/workplace.py launch --items a,b # dry run: one tab per task slug or inbox id
python3 scripts/workplace.py status             # every tab: task, state, last line
python3 scripts/workplace.py tasks              # every active task: area, priority, blocked, stale
python3 scripts/workplace.py teams              # team recipes: ordered role tabs on one task
python3 scripts/workplace.py send <tab> <text>  # type into one tab
python3 scripts/workplace.py adopt <tab> <slug> # name an open tab after its task
python3 scripts/workplace.py rename <ref> -- <title>            # name one tab of your own (its live ref only)
python3 scripts/workplace.py rename-workspace <ws_ref> -- <title> # name one workspace (its live ref only)
python3 scripts/workplace.py control --yes      # a new agent tab in the control workspace (workplace.control.command, default claude)
```

## Plan and driver are separate on purpose

The **plan** is CORE and knows no terminal. It reads the active tasks
(`work/tasks/`, `work/streams/`, status doing or review), ranks them by recent log
activity, recency and priority, puts each into a workspace (slug pattern first, then
the task's `context:`, then the default workspace) and caps the day at
`max_workspaces` with `max_tabs` each. Blocked tasks and tasks resting longer than
`stale_days` get no tab; the plan names them instead. Every new tab carries the
command that starts its agent (`agent.new`, default Claude Code), a resumable one
the command that resumes the last session (`agent.resume`).

The **driver** is everything a terminal does: list the tabs that are open, open the
plan, type into a tab, rename one. Terminal tools differ completely here, so the
driver is a command the instance points at, and the plan never imports it.
A driver is optional. Without one (`driver: none`) the plan prints the commands to
start by hand, `status` has nothing to report and `send` says so: the same Bridge,
the same plan, no dependency.

## Which terminal: one you can steer through an API

**Recommendation: a terminal the Bridge can drive through an API.** The workplace
needs four things from the terminal: list the tabs that are open (and which agent
waits for you), open a tab with a command in a named workspace, type into a tab, and
rename one. A terminal that only a person can click through gives the Bridge none of
them; it can then only print the commands (`driver: none`).

| Terminal | Steerable through | Driver |
|---|---|---|
| [cmux](https://github.com/manaflow-ai/cmux) (macOS) | CLI and socket API: workspaces, tabs, splits, sidebar status, notifications | ships as [`skills/cmux`](../skills/cmux/SKILL.md), the reference driver |
| tmux, in any terminal app (iTerm, Terminal, Ghostty, VS Code) | `tmux` commands (sessions, windows, `send-keys`, `list-panes`, `capture-pane`) | ships as [`skills/tmux`](../skills/tmux/SKILL.md) |
| WezTerm | `wezterm cli` (spawn, send-text, list) | write one (below) |
| kitty | remote control (`kitten @ launch`, `send-text`, `ls`) | write one (below) |
| none of these | | `driver: none`: the plan prints the commands to start by hand |

cmux is the recommendation because it was built for running many coding agents
side by side: workspaces with colors, tab status the agent itself reports (working,
waiting, needs you), notifications, and an API for all of it. It is also the driver
that ships and is tested, and so far the only one: every workplace feature,
`launch`, teams and the tab steering (`status`, `send`, `adopt`) included, and the
cockpit's tab actions built on them ([`bridge-cockpit.md`](bridge-cockpit.md)), has run
with Claude Code as the agent and cmux as the terminal; `skills/tmux` ships a
second driver. Other agents and
terminals are untested until an issue for that combination says otherwise. The
others are good choices too; their driver is a small program speaking the protocol
below, and the plan, the briefing and the inbox stay exactly the same.

## Configuration

```yaml
workplace:
  driver: none                       # or {command: ["python3", "path/to/driver.py"]}
  control: {name: Control}           # the workspace whose session steers the others; the
                                     # cockpit hands it questions through the relay;
                                     # optional `command:` starts an
                                     # agent there when a driver creates the workspace
  workspaces:
    - {name: Bigcorp, contexts: [bigcorp], color: "#1565C0", description: "client work for Bigcorp"}
    - {name: Platform, slugs: ["platform-*"], aliases: [Infra]}
    - {name: Misc, default: true}
  limits: {max_workspaces: 4, max_tabs: 3, stale_days: 10, activity_days: 7}
  tab_names: {payments-incident: Payments}
  team_names: {build: Build, review: Review}   # team or role id -> display name
  teams: {}                          # add or replace team recipes (see Teams below)
  router: {command: "..."}           # only for launch --target auto (see below)
  agent: {new: "claude -n {slug} {prompt}", resume: "claude --resume {session}"}
```

A workspace entry takes `name` (required), `contexts` and `slugs` (which tasks go
there), `default`, `color`, `description` (one line a router reads to place work)
and `aliases` (other titles under which the terminal may already show that
workspace, so an existing one is reused rather than opened twice).

A task can name its workspace itself with `area:` in its STATUS.md head (a
workspace's `name` or one of its `aliases`, any case). That wins over `slugs` and
`contexts`; an `area:` that names no workspace is ignored and the rules decide.
The cockpit's start page groups its areas by the same match.

`agent.new` gets `{slug}` and `{prompt}` (a short instruction to read the task's
STATUS.md, log rows, commits and open inbox items, report in eight lines and wait),
`agent.resume` gets `{session}`. Any agent CLI that takes a prompt fits.

## Writing a driver

A driver is a program that reads one JSON object on stdin and writes one on stdout,
the same shape `agents/_runtime/approval.py` uses for owner approval:

| Request | Answer |
|---|---|
| `{"verb": "tabs"}` | `{"tabs": [{"name", "workspace", "ref", "state", "last"}]}`, state one of `working`, `waiting`, `needs-you`, `shell`; optionally `id` (a stable tab id), `is_self` (the tab the caller runs in), `ws_ref` (the driver's own name for the tab's workspace: `workspace:2` in cmux, the session id `$2` in tmux) and `state_source` (`hook` or `glyph`: where the state was read. A state read off the title's status glyph is lost once the tab has a title of its own, so the cockpit offers no rename for such an agent tab) |
| `{"verb": "sessions"}` | `{"sessions": {"<tab name>": "<session id>"}}` |
| `{"verb": "open", "plan": {...}, "only": [...] or null, "resume": bool, "here": ref or null}` | `{"report": ["line", ...]}` |
| `{"verb": "launch", "tabs": [{"label", "slug", "command", "workspace", "aliases"}], "target": "tab" \| "workspace" \| "area", "here": ref \| null}`: one `target` key with one of three values, never `auto` (the CLI splits `--target auto` into one `workspace` call and one `area` call) | `{"report": ["line", ...]}` |
| `{"verb": "send", "tab": ref, "text": "..."}` | `{"report": [...]}` |
| `{"verb": "rename", "tab": ref, "title": "..."}` | `{"report": [...]}` |
| `{"verb": "caps"}` | `{"caps": ["tabs", "sessions", "open", "launch", "send", "rename", ...]}`: the verbs this driver serves. A driver that answers no `caps` counts as serving the six above |
| `{"verb": "focus", "tab": ref}` | `{"report": [...]}`: the tab comes to the front |
| `{"verb": "key", "tab": ref, "key": k}` | `{"report": [...]}`: one key into the tab, `k` one of `enter`, `escape`, `y`, `n`, `1` to `9` |
| `{"verb": "screen", "tab": ref, "lines": n}` | `{"text": "..."}`: the last `n` lines the tab shows, plain text, read only |
| `{"verb": "close", "tab": ref}` | `{"report": [...]}`: closes that one tab, only ever on an explicit request |
| `{"verb": "workspaces"}` | `{"workspaces": [{"ref", "title", "color", "color_name", "description", "pinned", "cwd", "branch", "dirty", "pr", "unread", "latest", "statuses"}]}`: the workspaces as the terminal shows them, read only (`workplace.py workspaces --json`; the cockpit's chat as cmux) |
| `{"verb": "control", "control": {...}, "command": "...", "root": "..."}` | `{"report": [...]}`: a new agent tab in the control workspace, which is created when it is missing (`workplace.py control --yes`) |
| `{"verb": "rename_workspace", "workspace": ws_ref, "title": "..."}` | `{"report": [...]}`: one workspace gets that title (cmux: `workspace rename`; tmux: `rename-session` on the session id, with `:` and `.` turned into `_` as tmux does). A ref the terminal does not know is an error, never a guess |
| `{"verb": "move_tab", "tab": ref, "workspace": ws_ref, "index": n}` | `{"report": [...]}`: one tab into another workspace, nothing focused; `index` (from 0) is optional (cmux: `move-surface --focus false`; tmux: `move-window -d` into the session, without an index). The last tab of a workspace is never moved (an `ERROR` line instead): the terminal would drop the emptied workspace |
| `{"verb": "set_color", "workspace": ws_ref, "color": name or null}` | `{"report": [...]}`: a palette colour by its name (see below), `null` takes the colour off (cmux: `workspace-action set-color` with the hex, `clear-color`; tmux has none) |
| `{"verb": "set_description", "workspace": ws_ref, "text": "..." or null}` | `{"report": [...]}`: one line of description, `null` takes it off (cmux: `workspace-action set-description`, `clear-description`; tmux has none) |

Every verb after `caps` is optional. A terminal that cannot do one leaves it out of
`caps`, and whoever steers the tabs (`workplace.py`, the cockpit) offers only
what the driver serves. With them the cockpit steers any terminal the same way:
jump to a tab, answer a question with a key, read what a tab shows, close a
finished one. A `ref` is the driver's own name for a tab (`surface:3` in cmux,
`%3` in tmux): letters, digits and `:%_.@/-`, at most 64 characters.

Rules every driver keeps: it never closes a tab or a workspace on its own (only
`close`, which a person asked for); a tab that is already
open is reused, never opened twice; `here` is the calling tab, which becomes the
control tab and moves last so no workspace is ever left empty. A driver that fails or
answers something unreadable is reported as a line, never raised, so the plan always
stands. A step the terminal refused is a report line starting with `ERROR`, never a
success line; `open --yes`, `send` and `adopt` then exit 1, so a script or workload
sees the failure the person reads. Names the workplace manages stay as they are. A tab of a task, an inbox item or a
team role is found by its name (the status rows and the session snapshots go by
it), and the plan finds a workspace by its configured name, alias or the control
name (`workplace.workspaces`, `workplace.control`). So the two rename commands
take a live ref only, never a name or a part of one, and refuse (exit 2) to give a
tab a managed name or the name another open tab has, to rename a task, inbox or team tab, to rename a configured
workspace or give a workspace a configured name or one in use, and an empty title,
one over 80 characters or one with a control character:

```bash
python3 scripts/workplace.py rename surface:5 -- Scratch pad
python3 scripts/workplace.py rename-workspace workspace:2 -- Research
```

The title goes after `--`, so a title that starts with a dash is no flag.

Three more commands arrange the workspaces, again by live refs only (exit 2 for a
name, a part of one, a ref that is not open, a verb the driver does not announce in
its `caps`). A configured workspace keeps the colour and description its config
gives it, since opening the plan sets them again:

```bash
python3 scripts/workplace.py move-tab surface:5 workspace:3 [--index 0]
python3 scripts/workplace.py workspace-color workspace:3 Teal        # or --clear
python3 scripts/workplace.py workspace-description workspace:3 -- Release work   # or --clear
```

A description is one line of at most 120 characters. Colours come from one
palette, `COLORS` in `workplace.py`, the sixteen names cmux knows with the hex it
stores for each:

| Name | Hex | Name | Hex | Name | Hex | Name | Hex |
|---|---|---|---|---|---|---|---|
| Red | `#C0392B` | Olive | `#4A5C18` | Blue | `#1565C0` | Magenta | `#AD1457` |
| Crimson | `#922B21` | Green | `#196F3D` | Navy | `#1A5276` | Rose | `#880E4F` |
| Orange | `#A04000` | Teal | `#006B6B` | Indigo | `#283593` | Brown | `#7B3F00` |
| Amber | `#7D6608` | Aqua | `#0E6B8C` | Purple | `#6A1B9A` | Charcoal | `#3E4B5E` |

A workspace in the `workspaces` answer reports its colour as the hex (`color`) and,
for a palette hex, its name (`color_name`, `null` for any other colour). Colours are
compared by that name, never by the hex as typed.

A driver ships as an optional skill or with the tool itself; the plan never
imports it. `skills/cmux` is the reference driver, active only where cmux is
installed:

```yaml
workplace:
  driver: {command: ["python3", "${root}/skills/cmux/scripts/cmux_driver.py"]}
```

`driver: {command: [...]}` may use `${root}` for the repository root.

## From the briefing to open tabs

With a driver configured, the briefing's `workplace` section proposes one tab per
task, grouped into workspaces. On the person's yes, `workplace.py open --yes`
opens them through the driver; `status`, `send` and `adopt` steer them afterwards.

## Launching chosen items

`workplace.py launch --items A,B [--mode report|go|context] [--target tab|workspace|area|auto]
[--team T --role R] [--here <ref>] [--model haiku|sonnet|opus] [--effort low|medium|high|xhigh]
[--yes] [--json]` opens one new agent tab (or one
new workspace) per item the person picked. An item is
an active task slug (a directory in `work/tasks/` or `work/streams/`) or an open
inbox item id; an unknown or closed item is an error line, the others still launch,
and the exit code is 1. Without `--yes` it is a dry run that prints, per item, its label,
where the tab would go (`-> this workspace`, `-> new workspace`, `-> <workspace> (area)`)
and the command. Labels are unique within one launch.

`--model` and `--effort` go to the agent as `claude --model <id> --effort <level>`.
An agent template may place them itself with `{model}` and `{effort}`; an empty slot
goes with its flag, so `claude --model {model} -n {slug} {prompt}` starts without
`--model` when none is asked. A template without the slot gets the flag appended,
but only when its program is `claude`, and never beside a `--model` or `--effort`
the template fixes itself: the template wins, and the entry says so in `pick_note`.
`agent.model` (`haiku`, `sonnet`, `opus`) and `agent.effort` name what a launch
that asks for none starts with, the open plan's tabs too; without them, and
without both flags, the command is exactly the template's. The cockpit sets them
from `cockpit.launch_model` (docs/bridge-cockpit.md).

Each tab starts the configured `agent.new` command on an ASCII prompt, by `--mode`:

| Mode | The tab |
|---|---|
| `report` (default) | reads the item, prints at most eight lines and waits; an inbox item already done or overtaken it closes with its finding noted, and changes nothing else |
| `go` | starts on the next step right away, asks before anything that leaves the machine, and closes an inbox item once it is settled; an item already done or overtaken it closes without asking (its finding noted, `reopen` undoes it), and local follow-ups that only record a decision it makes itself |
| `context` | looks for what someone picking the item up would miss (log rows, related inbox items, commits, issues, mails, meeting notes), shows the facts with their sources and writes the essentials back as one note (`task.py note` or `inbox.py note`), changing nothing else |

A task tab that reaches a result, a question only the person can answer, or a draft
files it once into the inbox (`inbox.py add --from tab:<slug> --kind result|question|draft
--gate only-you --closer person --key tab-<slug>-<topic>`), because the inbox is how
it reaches the briefing and every other reader.

`--target` decides where the tabs go:

| Target | Where |
|---|---|
| `tab` (default) | the workspace of the calling tab (`--here`, else the caller the driver reports); the cmux driver refuses when it cannot find one and never falls back to the selected workspace |
| `workspace` | one new workspace per item, named after its label |
| `area` | the workspace of the item's area, the same one `open` would choose (`workspaces:` by the task's `area:`, then slug, then context, then the default): a task by its own STATUS, an inbox item by the task it is linked to, an unlinked inbox item into the default workspace. A missing area workspace is created once, found by `name` or any of its `aliases`, and the tab goes into it as a named tab |
| `auto` | a router decides area and own workspace per item (below); the driver then gets `workspace` for the items that get their own and `area` for the rest |

The driver receives, per tab, `label` (the tab title), `slug` (the agent session
name), `command` (the full shell command), `workspace` (the area's workspace name)
and `aliases` (its other names). No target ever closes anything. Area names and
aliases match a workspace title regardless of case.

A `command` may be several KB, since it carries the whole prompt. A driver must never type it
raw into a new tab: the tab's shell may still be starting, its terminal then keeps at
most 1024 bytes of a line (MAX_CANON on macOS), and the rest, the Enter included, is
lost, so nothing runs. The cmux driver writes the command to a private launcher file
(`~/.cmuxterm/commands/`, mode 0600, pruned after 7 days) and types only
`/bin/sh '<file>'`. The file first creates a start marker; a tab whose marker does not
appear within `CMUX_LAUNCH_WAIT_SEC` (default 20) becomes an `ERROR` line, never reported
as started. It keeps its label: after a slow shell start the line may still run, and the
label is how a later click finds that agent. Each opened tab's report line names where it
went: `tab <label> (<ref>) in <workspace>`. A restored terminal tab, which is only a `cd`,
has its launcher file sourced (`. '<file>'`), so the directory change reaches the tab's
own shell.

`launch --yes` skips an item whose agent already runs: an item whose agent tab is
open already (a task tab, the same team role, or an inbox item's tab, in any state but
`shell`) is skipped with `already open: <label> (<ref>)`, and `--json` marks it
`"skipped": "open"` with the tab's `ref`. A tab in state `shell` holds no agent (its
command never ran, or the agent ended) and does not block; so a tab that is still starting
(a shell until its agent comes up) does not block either, and a second click from another
session in those seconds can open a second tab. `--again` opens a second tab
on purpose. The router gets at most 45 s, then the rules of `area` stand.

`--target auto` asks a router where each item belongs: one call for all items, with the
configured `workspaces:` (name and description) and one line per item (the task's
`headline:`, else the heading of its STATUS.md, or the inbox summary). It answers with an area per item and whether the item deserves a
workspace of its own (a large piece over several days); everything else goes into its
area's workspace as a tab. The router is any command that reads the prompt on stdin and
prints the JSON answer, so a small model is enough:

```yaml
workplace:
  router: {command: "claude -p --model <small model id> --setting-sources '' --tools '' --no-session-persistence"}
```

Without a router, or when it fails or names a workspace that is not configured, the
rules of `--target area` stand and nothing gets its own workspace. A dry run with
`--target auto` asks the router too, so it can show the answer: each line reads
`-> <workspace> (router: <why>)` or `-> new workspace (router: <why>)`, and `--json`
keeps `own` and `why` per item. That is one router call, a model call if the router is
one.

Every agent tab, launched or opened by the plan, starts with `BRIDGE_TAB_SLUG=<slug>` in
its environment, so a session, or any tool running in that tab, can tell it was started for
one item rather than as a free session. `status` names the task (`slug`) or inbox item (`item`) a tab works on, and keeps naming it once the item is closed or the task moved to `work/done/` (two month folders back), so a done tab can be told from a working one; an open item with the same label wins.
A task tab's slug is the task slug; an inbox item's tab gets `inbox-<short id>`.
The cockpit ([`bridge-cockpit.md`](bridge-cockpit.md)) reads `slug` and `item` from
`status` to tie a tab to the task or inbox row it works on, and uses the same driver
verbs for its tab buttons; without a driver it starts nothing and hands over the
command to start by hand. The relay mod `mods/cockpit-relay` reads `BRIDGE_TAB_SLUG`
itself: in a launched tab it never heartbeats, so an agent tab never takes the
cockpit's questions.

The same router places inbox items: `workplace.py place --items <id>[,<id>]` or
`place --unplaced` (every open item with neither a task nor an area) asks it once which
workspace each item belongs to and writes the answer as the item's `area`
([`inbox.md`](inbox.md)); `--dry-run` writes nothing. `inbox.py add` starts it for a new
item when `inbox.place_on_add` is true. An inbox item without a task then launches into
its area's workspace instead of the default one.

`workplace.py tasks [--json]` lists every active task flat, sorted by priority and then
activity: label, area, priority, score, `blocked_by`, and `stale` (no activity for longer
than `limits.stale_days`). `propose` decides which of them get a tab today; `tasks` is the
whole list, for any UI or script that drives `workplace.py`.

## Teams: several role tabs on one task

`workplace.py teams [--json]` lists the team recipes: an ordered group of roles that work
on one task, each in its own tab. Five ship as defaults: `build` (implement, review) for
features, bugs and refactors; `tdd` (tests, implement, review); `research` (evidence,
counter, summary); `reply` (context, draft, never sent) for customer communication; and
`ops` (diagnose read-only, then fix after asking). `team_names` in the `workplace:` block
renames teams and roles for display, `teams` adds or replaces whole recipes, each
`{id: {label, for_types: [...], roles: [{id, name, mode, brief}]}}` with `mode` `report`
or `go`. A `go` role starts on its part right away; a `report` role reports what it finds
in at most eight lines and changes nothing on its own. `--mode` does not apply to a role
tab: given together with `--team` it is ignored, with a note on stderr.

`launch --items <slug> --team <id> --role <id>` opens one role's tab, labelled
`<task label> · <team label> <role name>` with the session name `<slug>--<team>-<role>`
(both carry the team, since `build` and `tdd` share role names), in the same workspace
rules as any launch. Roles start one at
a time, when the person asks for the next one; they hand over through
`<task dir>/team.md`, where each role appends what it did and what the next one needs.
`status` names the task, team and role of such a tab, by its label or by the session
name the agent later titles it with. Inbox items have no team.

## Where tab state comes from

`status` shows what only the terminal knows: is the agent working, waiting for input,
or asking for a permission. What a tab has *achieved* (a finding, a question for you,
a draft, a result) does not come from the terminal: the agent files it in the inbox
(`docs/inbox.md`), the same place a scheduled job or a peer Bridge files theirs. That
keeps status equally good with any driver, and with none.
