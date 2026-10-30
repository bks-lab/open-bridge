# Standing Orders

Standing Orders are **always-on rules** that apply to every session — permanent behavioral rules loaded at session start.

## How They Work

1. At session start (when `work.enabled: true`), all standing orders are loaded
2. Each order specifies which sub-agents it applies to (`applies_to:` — sub-agent names, empty = all)
3. When dispatching a sub-agent, its matching standing orders are included in its prompt
4. Orders with `enforcement: blocking` cause active warnings on violations

## Scope and load are two questions

`scope: always` says an order **applies** always: it is matched against every
sub-agent dispatch, then filtered by `applies_to` (sub-agent names, empty = all).
`load:` says when its **body** is read (below). `protocols/` stays top-level:
`standing-orders/` ships the CORE defaults, and user-authored orders live in
`standing-orders/user/`. AGENTS.md § Standing Orders keeps only the summary.

## Schema

Each standing order is a markdown file with YAML frontmatter:

```yaml
---
name: order-name
scope: always                 # always | per-repo | per-context
enforcement: advisory         # advisory | blocking | hook-warned
applies_to: []                # sub-agent names (empty = all agents)
load: eager                   # eager | on-trigger (default: eager)
fires_unprompted: false       # true: --check refuses load: on-trigger
triggers: []                  # required for on-trigger: what fetches the body
summary: ""                   # required for on-trigger: the line that stays in context
---
```

### Scope

| Value | Meaning |
|-------|---------|
| `always` | Applies in every session, every repo |
| `per-repo` | Only when a matching repo is active |
| `per-context` | Only in specific contexts |

### Load

Skills have always worked this way: the description stays in context, the body
arrives on invocation. Orders now do too.

| Value | Meaning |
|-------|---------|
| `eager` | The body is read at session start. The default, so an unmigrated order keeps working exactly as before. |
| `on-trigger` | Only `summary` and `triggers` stay in context; the body is read when the vocabulary comes up. Requires both fields. |

Keep an order `eager` only when it bites while nobody says its own vocabulary:
a logging duty, a security floor. Everything else is `on-trigger`. The index a
session actually carries is `python3 scripts/standing-orders.py --index`;
`--check` refuses an order that says `on-trigger` and names no trigger, because
such a file reads as enforced in the tree and is absent from every session.

An order that must act while nobody says its vocabulary says so with
`fires_unprompted: true`, and `--check` then refuses `load: on-trigger` for it.
The reason used to live only in a comment beside `load: eager`; an order that
lost it moved behind triggers that are spoken only after the question it
answers has been asked, and loaded in none of the sessions it existed for. A
trigger check cannot see that, because the triggers are there.

### Enforcement

| Value | Meaning |
|-------|---------|
| `advisory` | Claude follows the rule |
| `blocking` | Claude actively warns when it detects a violation |
| `hook-warned` | A tracked repo git hook (`scripts/hooks/pre-commit`) prints a warning to stderr when it detects a violation — but always exits 0, so the commit itself is never blocked. Tool-agnostic (fires for any tool that shells out to `git commit`); compliance is a nudge, not hard-enforced |

## Creating Standing Orders

Copy `_template.md`, fill in frontmatter and rules. Place in this directory.

## Built-in Orders

| Order | Enforcement | Purpose |
|-------|-------------|---------|
| board-task-criteria | advisory | When a log entry should escalate to a Board task (A/B/C class model) |
| code-standards | advisory | Code quality guidelines |
| document-work | hook-warned | Log all significant actions to work/log.md |
| drift-advisory | advisory | Surface drift between declared state and live reality |
| feature-discovery | advisory | Proactively suggest relevant Bridge features |
| security-baseline | advisory | Security practices |
| task-sync | hook-warned | Route task changes across project/context/mandant; enforce dual-doku |
| work-board-reconciliation | advisory | Keep task folders and STATUS.md / board coherent |
