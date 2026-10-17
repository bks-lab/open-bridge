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

`agent.new` gets `{slug}` and `{prompt}` (a short instruction to read the task's
STATUS.md, log rows, commits and open inbox items, report in eight lines and wait),
`agent.resume` gets `{session}`. Any agent CLI that takes a prompt fits.

## Writing a driver

A driver is a program that reads one JSON object on stdin and writes one on stdout,
the same shape `agents/_runtime/approval.py` uses for owner approval:

| Request | Answer |
|---|---|
| `{"verb": "tabs"}` | `{"tabs": [{"name", "workspace", "ref", "state", "last"}]}`, state one of `working`, `waiting`, `needs-you`, `shell`; optionally `id` (a stable tab id) and `is_self` (the tab the caller runs in) |
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

The last five are optional. A terminal that cannot do one leaves it out of
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
sees the failure the person reads. A driver ships as an optional skill or with the tool itself; the plan never
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
Without both flags the command is exactly the template's. The cockpit sets them
from `cockpit.launch_model` (docs/bridge-cockpit.md).

Each tab starts the configured `agent.new` command on an ASCII prompt, by `--mode`:

| Mode | The tab |
|---|---|
| `report` (default) | reads the item, prints at most eight lines and waits |
| `go` | starts on the next step right away, asks before anything that leaves the machine, and closes an inbox item once it is settled |
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
| `area` | the workspace of the item's area, the same one `open` would choose (`workspaces:` by slug, then context, then the default): a task by its own STATUS, an inbox item by the task it is linked to, an unlinked inbox item into the default workspace. A missing area workspace is created once, found by `name` or any of its `aliases`, and the tab goes into it as a named tab |
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
