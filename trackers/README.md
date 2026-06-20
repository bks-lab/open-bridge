---
summary: Tracker provider contract — how /briefing Stream B reads work items from external systems
type: reference
last_updated: 2026-04-11
---

# Trackers

A **tracker** is a source of work items (issues, tickets, stories, tasks)
in an external system: GitHub Projects, Azure Boards, Linear, Jira, etc.

`/briefing` Stream B fans out over **all enabled trackers in parallel**,
collects their items, and renders them in the terminal dashboard. Each
tracker is one markdown file in this directory — the file is a
**playbook** that tells Claude what commands to run and how to normalize
the output. There are no executable scripts. Claude is the runtime.

## Why a pluggable abstraction

Not every Bridge user is on GitHub. A user at a company running Azure
DevOps can enable `ado.md` instead of (or in addition to) `github.md`
and `/briefing` renders the same way without touching any workflow
code. New trackers (`linear.md`, `jira.md`, `gitlab.md`, …) are just
new files here.

## File layout

```
trackers/
  README.md        ← you are here — contract + schema
  github.md        ← working provider: gh CLI
  ado.md           ← example provider: az boards (Azure DevOps)
```

New provider = new `{name}.md` file matching the contract below.

## Normalized item schema

Every provider emits items with this shape. Claude merges the output
of all enabled providers into one flat list, sorted by
`(category, changed_at DESC)`, and renders it.

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | string | yes | Display id, e.g. `#1234` or `PROJ-42` |
| `title` | string | yes | Item title |
| `state` | enum | yes | Normalized: `new` \| `ready` \| `in_progress` \| `review` \| `done` \| `blocked` \| `removed` |
| `raw_state` | string | yes | Original label from the tracker (e.g. `"Ready for Testing"`) |
| `type` | enum | yes | `bug` \| `story` \| `task` \| `feature` \| `epic` \| `issue` |
| `assignee` | string\|null | no | Display name of assignee |
| `assigned_to_me` | bool | no | True if the current user owns this item |
| `url` | string | yes | Link to the item in the source system |
| `changed_at` | iso8601 | yes | Last modification timestamp |
| `project` | string | no | Project / board name |
| `tracker` | string | yes | Provider name (e.g. `github`, `ado`) — set by the provider |
| `labels` | [string] | no | Tags / labels |
| `priority` | string\|null | no | Priority label if any |
| `category` | enum | yes | `open` \| `qa` \| `done` — bucket for rendering |

### Category semantics

- `open` — normal working queue, rendered in the main "Tracker" section
- `qa` — items the user needs to test or review, rendered in a dedicated
  "QA Queue" section across all providers (inspired by the ADO
  "Ready for Testing" / "In Testing" flow)
- `done` — recently completed, rendered in the "Recently done" section

A provider can emit items in multiple categories from the same run
(e.g. an ADO run emits open + qa + done in one go).

## Provider interface

Each `{name}.md` file has this structure:

```markdown
---
name: <provider-name>
description: <one-line for Stream B discovery>
requires: [<cli tools needed, e.g. gh or az>]
config_key: integrations.<name>   # where to read config from bridge-config.yaml
---

# Provider: <Name>

## When to use

<one paragraph>

## Config schema

<YAML block showing the integrations.<name> section a user should add
to bridge-config.yaml>

## Collect

<step-by-step instructions for Claude: which commands to run,
which flags, how to loop over projects, how to normalize the output
into the schema above>

## State mapping

<table: raw_state → normalized state>

## Category mapping

<rules: which items go to category open / qa / done>

## Failure modes

<what to do if the CLI is not installed, not authenticated, times out>
```

## Discovery rule

At `/briefing` Stream B time:

```
for each file in trackers/*.md (except README.md):
  name = filename without .md
  enabled = bridge-config.yaml → integrations.{name}.enabled
  if enabled is true:
    load trackers/{name}.md
    follow its Collect steps
    collect normalized items
```

No hardcoded list anywhere. Drop a new `linear.md` in, set
`integrations.linear.enabled: true`, it works.

## Failure semantics (never-block rule)

- CLI not installed → warning, skip provider, continue briefing
- CLI not authenticated → warning, skip provider, continue briefing
- Malformed config → warning, skip provider, continue briefing
- Network error or timeout (>10s per command) → warning, skip, continue
- Zero items returned → section omitted (not "no data")

A failing provider **never** aborts `/briefing`. This matches the
standing rule in `skills/briefing/references/workflow.md`:
"Never block. Always let the user continue working."

## Rendering rules

Single provider enabled → section title stays natural:

```
── GitHub (7 open) ─────────────────────────────────────────
  #42   Example issue title                  In Progress   me
```

Two or more providers enabled → subsection per provider:

```
── Tracker: GitHub (5 open) ────────────────────────────────
  #42   …
── Tracker: Azure Boards (12 open) ─────────────────────────
  #1234 …
```

QA-category items render in their own section **across** providers:

```
── QA Queue (3 bugs + 2 stories) ───────────────────────────
  [ADO #1234]  Bug title                     Ready for Testing   me
  [ADO #1235]  Another bug                   In Testing          someone
  [GH  #42  ]  Story title                   In Review           me
```

Rendering details (column widths, truncation, ordering) live in
`skills/briefing/references/workflow.md`, not here.

## Security notes

- **No credentials in `trackers/*.md`.** Provider playbooks describe
  which CLI to call; the CLI handles auth via its own state
  (`gh auth status`, `az login`, env vars, keyring).
- **No credentials in `bridge-config.yaml`.** Reference env vars or
  keyvault URIs if needed.
- Trackers are **read-only** for `/briefing`. Write operations
  (creating issues, moving cards) live in dedicated skills like
  `project-advisor`.

## Related

- `skills/briefing/references/workflow.md` — Stream B workflow that consumes these providers
- `bridge-config.yaml` — user-level `integrations.<name>` blocks enable providers
- `ecosystem.yaml` — `github_projects:` list can be referenced by the github provider via `projects: ecosystem`

- `workflow/projects/<slug>.yaml` — per-board write config consumed by `project-advisor` + `github-projects-manager`. The `state_map` block defined there feeds back into the normalized item schema above (each tracker's playbook MAY override `state_map` per-project from this registry).
