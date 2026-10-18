---
name: tmux
description: 'Optional, only for tmux users: the workplace driver that lets scripts/workplace.py and the cockpit steer agent tabs in tmux, inside any terminal app (iTerm, Terminal, Ghostty, VS Code). Trigger: "tmux driver", "workplace with tmux", "agent tabs in tmux", "cockpit without cmux".'
metadata:
  scope: core
---

# tmux

A second terminal driver beside [`skills/cmux`](../cmux/SKILL.md). It speaks the
workplace JSON protocol (docs/workplace.md § Writing a driver), so the plan, the
briefing, the inbox and the cockpit work the same in any terminal app that runs
tmux.

**Optional.** It needs the `tmux` binary (`$BRIDGE_TMUX_BIN`, else `tmux` on
PATH, else Homebrew's path). Without it the driver answers an error, which
`scripts/workplace.py` reads as "tab view unknown", never as "no tabs open".

## Wire it

```yaml
workplace:
  driver: {command: ["python3", "${root}/skills/tmux/scripts/tmux_driver.py"]}
```

Then `python3 scripts/workplace.py open --yes [--here "$TMUX_PANE"]`, `launch`,
`status`, `send` and `adopt` steer the tabs, exactly as with cmux.
`BRIDGE_TMUX_SOCKET=<name>` points the driver at a separate server
(`tmux -L <name>`); the tests use that so they never touch your own tmux.

## Mapping

| Workplace | tmux |
|---|---|
| workspace | session (`:` and `.` in a name become `_`, as tmux does) |
| tab | window, its name is the tab name |
| `ref` / `id` | pane id of the window's active pane, `%3` |
| `is_self` | the window holds `$TMUX_PANE` of the caller |
| `ws_ref` | the session id, `$2`; it stays when the session is renamed |
| `state` | read from the pane: no agent process below the pane is `shell`; `esc to interrupt` is `working`; a permission or numbered choice prompt is `needs-you`; else `waiting` |
| `sessions` | `--resume <uuid>`, `-r <uuid>` or `--session-id <uuid>` in the agent's process args |

All fourteen verbs are served: `tabs`, `sessions`, `open`, `launch`, `send`,
`rename`, `control`, `caps`, `focus`, `key`, `screen`, `close`, `rename_workspace`,
`move_tab`. `rename_workspace` renames the session by its id, with `:` and `.`
turned into `_` as tmux does, and refuses a name another session has after that
same change. `move_tab` moves a window into another session (`move-window -d`,
without an index) and never the last window of a session. tmux has no workspace
colour or description, so `set_color` and `set_description` are not offered.

## What it guarantees

- It never closes a window or a session on its own. `close` kills one pane on
  request, and refuses the last pane of the server, which would end the server.
- It never moves the last window out of a session (tmux destroys an emptied
  session); such a tab is renamed where it is and the report says so.
- `open` and `control` reuse a window of the same name in the target session.
  `launch` does not, like cmux: `workplace.py` already skips an agent that runs,
  and `--again` asks for a second tab on purpose.
- `launch --target tab` opens in the caller's session (`here`, else
  `$TMUX_PANE`) and refuses when neither is known, never the attached session.
- A command over 1000 bytes goes into a private launcher file
  (`~/.cache/bridge-tmux/commands/`, mode 0600, pruned after 7 days), since tmux
  carries a command in one message of at most 16 KB. Every command keeps a shell
  open after the agent exits.
- A step tmux refuses is an ERROR line, never a success line. No server running
  is a true "no tabs".

## Limits, honestly

- **State is read from the screen**, not reported by the agent: cmux gets it from
  Claude Code's hooks. A new agent UI wording can misread a state until the
  patterns in `tmux_driver.py` follow it.
- **No colors, descriptions or ordering** for workspaces: tmux has no sidebar.
  The plan's order and colors are not applied.
- **No notifications.** cmux can flag a tab that needs you; in tmux the
  cockpit has to poll `tabs`.
- **`focus` needs an attached client.** Without one the window is selected and
  shows on the next `tmux attach`; with several clients only the first switches.
- **A workspace created only to receive moved tabs keeps its starting shell
  window**, since tmux cannot create a session around an existing window.
- Untested with agents other than Claude Code and Codex.
