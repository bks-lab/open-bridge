# cmux: local orchestration reference

Loaded from `skills/cmux/SKILL.md` for tabs, splits, spawning agents, sidebar,
wait-for, the observe protocol, buffers, settings, browser limits and the socket
API. Session inventory and recovery: [`sessions.md`](sessions.md).

`<bridge root>` below is the Bridge repository root; `skills/cmux/scripts/...`
paths are relative to it.

## Quick reference

```bash
# List workspaces
cmux list-workspaces

# Create a named workspace with an agent and a prompt (no focus steal).
# The output is "OK workspace:N": capture the ref with grep.
WS=$(cmux new-workspace --command "bash $TMPDIR/launch-agent.sh" 2>&1 | grep -oE 'workspace:[0-9]+')
cmux rename-workspace --workspace "$WS" "workspace-name"
# Do NOT select the new workspace right after the rename: that has closed a
# freshly created workspace.

# Resume a session in a named workspace (no focus steal)
WS=$(cmux new-workspace --command "claude --resume <session-id>" 2>&1 | grep -oE 'workspace:[0-9]+')
cmux rename-workspace --workspace "$WS" "workspace-name"

# Never pass complex prompts inline, use a launcher script:
# cat > "$TMPDIR/launch-agent.sh" << 'LAUNCHER'
# #!/usr/bin/env bash
# exec claude "Simple prompt text without backticks or dollar signs"
# LAUNCHER
# Reason: inline --command "claude \"$(...)\"" puts the prompt through shell
# interpretation; backticks, $() and quotes cause parse errors in the new workspace.

# Rename / select
cmux rename-workspace --workspace workspace:N "Name"
cmux select-workspace --workspace workspace:N
```

Closing (`close-workspace`, `close-surface`) exists, but nothing in this skill
closes a tab or workspace it did not create itself in the same run. The workplace
driver never closes anything.

## Spawning an agent (recommended path)

For a named agent session, prefer `scripts/spawn-workspace.sh`. It writes the
prompt to a file to dodge shell quoting, verifies the agent actually started, and
restores the caller's focus: three things a hand-chained `new-workspace` +
`rename-workspace` + `select-workspace` gets wrong in subtle ways.

```bash
# Minimal: blank agent session in a named workspace
skills/cmux/scripts/spawn-workspace.sh my-agent

# Common case: prompt and working directory.
# Without --model the spawned agent INHERITS the default model. Do not pin one
# out of habit (pinning silently downgrades every spawned tab); pass --model only
# as a deliberate override, e.g. a cheaper model for bulk pattern matching.
skills/cmux/scripts/spawn-workspace.sh my-agent \
  --cwd /path/to/repo \
  --prompt "$(cat "$TMPDIR/my-prompt.txt")"
```

The script prints `VERIFIED: Claude running in workspace workspace:N` on success;
capture the ref for later `wait-for` / `sidebar-state` calls:

```bash
WS_REF=$(skills/cmux/scripts/spawn-workspace.sh my-agent --prompt "..." \
         | grep -oE 'workspace:[0-9]+' | head -1)
```

Fall back to raw `cmux new-workspace --command ...` only when the script cannot
express what you need (non-agent commands, exotic wrappers).

| Flag | Purpose |
|------|---------|
| `<name>` (positional) | Workspace title |
| `--prompt "..."` | Initial prompt (written to a file, survives quoting) |
| `--cwd <path>` | Working directory (default: the Bridge root) |
| `--status-file <path>` | `STATUS.md` path: prepends a work-tracking instruction |
| `--model <model>` | Optional override; no flag = inherit the default |

Prompt and launcher files go to `$CMUX_TMPDIR` (default `~/.claude/cmux-tmp`), a
stable user-owned directory, so one permission rule covers every spawn; files
older than a day are cleaned on each run. The launcher falls back to a login shell
when the agent exits, so the tab survives.

## Key patterns

- **Send to any workspace:** `cmux send --workspace workspace:N "text" && cmux send-key --workspace workspace:N enter`
- **Read an agent's screen:** `cmux read-screen --workspace workspace:N` or `--surface surface:S`
- **With scrollback:** `cmux read-screen --surface surface:S --scrollback --lines 200`
- **Find a workspace by name:** `cmux find-window "agent-name" --select`
- **Find by content:** `cmux find-window --content "error" --select`

> **Before any `new-surface` / `new-split` / `browser open`:** use
> `scripts/cmux-open.sh` (SKILL.md, rule on the target workspace). The raw
> commands below are only safe with an explicit `--workspace`.

## Splitting within a workspace

Run several agents **side by side in one workspace** instead of opening workspaces.

```bash
cmux new-split right                              # horizontal split
cmux new-split down                               # vertical split
cmux new-split right --workspace workspace:N      # split in a given workspace

cmux new-pane --direction right                            # new terminal pane
cmux new-pane --type browser --direction down --url URL    # browser below

cmux new-surface                                  # new terminal tab in the current pane
cmux new-surface --type browser --url URL         # browser tab in the current pane
cmux new-surface --pane pane:P                    # tab in a given pane

cmux send --surface surface:X "claude 'Your prompt here'"
cmux send-key --surface surface:X enter
```

### Pattern: an agent becomes the orchestrator of its workspace

```bash
# 1. You are in the LEFT pane. Split RIGHT for the first sub-agent:
RIGHT=$(cmux new-split right 2>&1 | grep -oE 'surface:[0-9]+')
cmux send --surface "$RIGHT" "claude 'Research: find all API endpoints that need updating'"
cmux send-key --surface "$RIGHT" enter

# 2. Optional: split the right pane DOWN for a second sub-agent:
BOTTOM=$(cmux new-split down --surface "$RIGHT" 2>&1 | grep -oE 'surface:[0-9]+')
cmux send --surface "$BOTTOM" "claude 'Write tests for the new authentication module'"
cmux send-key --surface "$BOTTOM" enter

# Layout:
# +--------------+--------------+
# |              |  sub-agent 1 |
# |  you         |  (research)  |
# |  (orchestr.) +--------------+
# |              |  sub-agent 2 |
# |              |  (tests)     |
# +--------------+--------------+

# 3. Watch (non-intrusive) and follow up:
cmux read-screen --surface "$RIGHT"
cmux send --surface "$RIGHT" "focus on the auth endpoints specifically"
cmux send-key --surface "$RIGHT" enter
```

Sub-agents raise a cmux notification when their session ends (Stop hook);
Cmd+Shift+U jumps to the latest one.

**Split or in-session sub-agent?** An in-session sub-agent suits short tasks that
should inherit your context. A cmux split suits longer tasks: own session,
observable, survives compaction.

## Sidebar metadata

Agents report their state in the sidebar; the orchestrator reads it with
`sidebar-state` instead of parsing `read-screen`.

```bash
cmux set-status build "compiling" --icon hammer --color "#ff9500"
cmux set-status build "done" --icon checkmark --color "#30d158"
cmux clear-status build

cmux set-progress 0.3 --label "Step 2/7..."
cmux clear-progress

cmux log "Starting research"                       # levels: info, progress, success, warning, error
cmux log --level success --source agent -- "Found 42 results"
cmux clear-log

cmux sidebar-state --workspace workspace:N         # status, progress, logs, git, cwd (key=value text)
```

## Notifications

```bash
cmux notify --title "Task complete" --body "Research finished"
cmux notify --title "Error" --subtitle "build" --body "Tests failed"
cmux notify --title "Done" --body "Ready for review" --workspace workspace:N
```

## Synchronization (wait-for)

```bash
cmux wait-for data-ready --timeout 60     # agent B blocks until signaled
cmux wait-for --signal data-ready         # agent A signals when done
```

Signals are queued persistently, so for N parallel agents spawn all first, then
`wait-for` each unique signal name in any order.

## Observe protocol

The lifecycle every orchestrated agent signals; the orchestrator relies on these
signals instead of screen parsing.

```bash
# Start
cmux set-status task "starting" --icon sparkle
cmux set-progress 0.0 --label "Initializing"
# Progress
cmux set-progress 0.4 --label "Step 2/5: writing tests"
# Done (mandatory on success)
cmux set-progress 1.0 --label "Done"
cmux set-status task "done" --icon checkmark --color "#30d158"
cmux wait-for --signal {slug}-done
cmux notify --title "{slug}" --body "Result: {summary}"
# Error (mandatory on failure)
cmux set-status task "error" --icon xmark --color "#ff3b30"
cmux wait-for --signal {slug}-error
cmux notify --title "{slug}" --body "Error: {error_summary}"
```

Observation hierarchy for orchestrators:

```
Layer 1: PUSH, wait-for signals + notify      preferred
Layer 2: STRUCTURED PULL, sidebar-state        fallback
Layer 3: RAW PULL, read-screen + scrollback    debugging only
```

Never use `read-screen` to decide whether an agent is done; use signals.

**Result files.** Signals say *when*; a result file says *what*. Screen scraping
is brittle (ANSI codes, wrapping, truncated scrollback). Quick runs write to
`$TMPDIR/{slug}-result.{txt,json}`; work-system tasks to
`work/tasks/{slug}/result.{json,md}`, which survives reboots and moves with the
task. The agent writes the file *before* the done signal; a missing file after
`wait-for` returned is a protocol violation.

**Prompt framing.** Current models refuse prompts that look like prompt injection:
rigid "execute exactly these steps" lists, "no explanations" suppressions,
openers like "You are running under the X protocol". Frame the prompt as talking
to a colleague: one sentence of context, the task in natural language, the cmux
signals as a status convention rather than a mandatory script, and an escape
hatch ("if something looks off, tell me").

### End-to-end example (orchestrator view)

```bash
SLUG="quick-check"
RESULT_FILE="$TMPDIR/${SLUG}-result.txt"
PROMPT_FILE="$TMPDIR/${SLUG}-prompt.txt"

# Unquoted heredoc on purpose: ${SLUG} and ${RESULT_FILE} expand before writing.
cat > "$PROMPT_FILE" << PROMPT
Hi, I'm running a small automation task and need your help.

Context: I track agents through a lightweight status convention, plain \`cmux\`
CLI calls that post to a sidebar, so I don't have to scrape screens.

Task: <one or two sentences: what to compute, what to write to ${RESULT_FILE}.>

Once the result file is written, run these so I can see you're done:

    cmux set-progress 1.0 --label "Done"
    cmux set-status task "done" --icon checkmark --color "#30d158"
    cmux wait-for -S ${SLUG}-done
    cmux notify --title "${SLUG}" --body "Done"

Write the file first, then the signals. If something looks off or you'd do it
differently, tell me, no need to force the script.
PROMPT

WS_REF=$(skills/cmux/scripts/spawn-workspace.sh "$SLUG" --cwd "$(pwd)" \
  --prompt "$(cat "$PROMPT_FILE")" | grep -oE 'workspace:[0-9]+' | head -1)

if cmux wait-for "${SLUG}-done" --timeout 180; then
  cat "$RESULT_FILE"
else
  cmux sidebar-state --workspace "$WS_REF"                        # layer 2
  cmux read-screen --workspace "$WS_REF" --scrollback --lines 80  # layer 3
fi
# The workspace was spawned by this run; close it only if the user wants it gone.
```

## Markdown viewer

```bash
cmux markdown open plan.md                        # live-reloading viewer next to the pane
cmux markdown open STATUS.md --workspace workspace:N
```

## Surface (tab) management

```bash
cmux list-panes --workspace workspace:N
cmux list-pane-surfaces --workspace workspace:N
cmux tree --workspace workspace:N                  # full hierarchy
cmux tree --all                                    # all windows

cmux move-surface --surface surface:S --workspace workspace:N
cmux reorder-surface --surface surface:S --index 0
cmux rename-tab --surface surface:S "New name"

cmux drag-surface-to-split --surface surface:S left|right|up|down
cmux break-pane --workspace workspace:N --pane pane:M
cmux join-pane --target-pane pane:T --surface surface:S
cmux resize-pane --pane pane:P -R --amount 20
cmux swap-pane --pane pane:A --target-pane pane:B
cmux focus-pane --pane pane:P
```

## Buffers (share data between agents)

```bash
cmux set-buffer --name results "$(cat "$TMPDIR/analysis.json")"
cmux paste-buffer --name results --surface surface:S
cmux list-buffers
```

## Settings and config

- **Primary config:** `~/.config/cmux/cmux.json` (JSONC, schema `cmux.schema.json`).
  A key set here overrides the GUI value (the toggle then shows as file-managed);
  omit a key to fall back to the GUI. Defaults live in the schema.
- **Legacy, do not use:** `~/.config/cmux/settings.json` and the app-support
  `settings.json`, which the app rewrites on update.
- **Apply live:** `cmux reload-config` (no restart). Run `cmux config check`
  first and back up `cmux.json` with a timestamp.
- **Discovery:** `cmux settings path`, `cmux docs settings`; grep the schema
  instead of guessing. Terminal behaviour (font, theme, keybinds) is Ghostty
  (`~/.config/ghostty/config`), not cmux.
- **Working-directory trap:** a new *workspace* inherits its cwd through the cmux
  key `app.workspaceInheritWorkingDirectory`; a new *tab or split* inherits from
  the focused surface via OSC-7 (Ghostty). A running agent emits no shell prompt,
  so a new tab next to it falls back to home. Fix: `working-directory = inherit`
  in the Ghostty config, or always `cd` explicitly.

## Browser limits

For browser automation, prefer the [`browser`](../../browser/SKILL.md) skill: Playwright
drives Chrome, or any Chromium with a local CDP address, outside cmux; its
`references/from-cmux.md` maps the verbs below. The cmux browser (`browser_*` MCP tools,
`--type browser` panes) reads, clicks, scrapes the DOM and runs in-page `fetch`. Two
hard limits:

- **No file downloads.** A `<a download>` click navigates the page to the `blob:`
  URL instead of saving a file. Use Playwright (`page.waitForEvent('download')`)
  for real downloads.
- **Screenshots may return no image data.** To check a rendered page visually,
  render to PNG with Playwright
  (`playwright screenshot --channel chrome --viewport-size "1280,880" <url> out.png`)
  and read the image. DOM checks passing is not the same as "looks right".

## Traps (each cost real effort to find)

- **"Tab" is a surface, not a workspace.** See the vocabulary table in SKILL.md.
- **`read-screen` shows a stale frame after `send-key`.** The screen only
  refreshes when visible text arrives, so an `escape` or `ctrl+u` that did clear
  the input looks as if nothing happened. Verify by sending one harmless
  character with `cmux send` and reading again: if only that character shows,
  the clear worked. Before typing into someone else's running session: clear,
  verify with the probe, send the text, read again, and only then `enter`. A
  draft found in someone else's input field is their unsent intent: save and
  report it, never submit or overwrite it.
- **`CMUX_WORKSPACE_ID` can be stale.** In a long-running session it can point to
  a workspace that no longer exists (`not_found: Workspace not found`,
  `identify` returns `caller: null`), while `CMUX_SURFACE_ID` is still right.
  `cmux --id-format both tree --all | grep "$CMUX_SURFACE_ID"` finds the real
  workspace and pane; then address `new-surface --workspace workspace:N --pane
  pane:P` explicitly.
- **`--command` re-encodes non-ASCII**, `send` does not. `cmux_layout.py` and
  the driver write such commands to a UTF-8 file and source it.
- **A tab whose only process is the agent closes when the agent exits**, and an
  otherwise empty workspace goes with it. Append `; exec "$SHELL" -l`.
- **A shell update prompt can swallow the first character** of a `--command` in a
  fresh tab (`laude --resume`). Verify the start (`ps`) and re-send.
- `claude --resume` needs the **full** session UUID; a prefix opens a filtered picker.
- Interrupt with `cmux send-key ... ctrl+c` (with the plus), not `C-c`.
- Surface and workspace refs are window-scoped; disambiguate with `--window <id>`.
- `cmux top --all --json` reports only the **selected** surface per pane; use
  `cmux list-pane-surfaces` to see every tab.
- `cmux events --cursor-file <path> --reconnect` is a crash-resumable event stream
  (ring buffer of about 4000 events); prefer it over polling.

## Environment variables

| Variable | Description |
|----------|-------------|
| `CMUX_WORKSPACE_ID` | Auto-set: current workspace (default for `--workspace`); can be stale |
| `CMUX_SURFACE_ID` | Auto-set: current surface (default for `--surface`) |
| `CMUX_SOCKET_PATH` | Override the socket path (default: auto-discovered) |

## Socket API

Programmatic control via a Unix socket (auto-discovered by the CLI), newline-terminated JSON.

| Method | Purpose |
|--------|---------|
| `workspace.list` | List all workspaces |
| `workspace.create` | Create a workspace |
| `workspace.select` | Switch to a workspace |
| `surface.send_text` | Send text to a terminal |
| `surface.send_key` | Send a key (enter, tab, escape) |
| `notification.create` | Push a notification |

`--json` is a **global** flag placed before the command: `cmux --json
list-workspaces` works, `cmux list-workspaces --json` does not. Exceptions:
`identify` always returns JSON, `sidebar-state` never does. Docs:
https://www.cmux.dev/docs/api
