---
summary: Tracker provider contract, how a briefing reads work items from external systems through adapters
type: reference
last_updated: 2026-10-25
---

# Trackers

A **tracker** is a source of work items (issues, tickets, stories, tasks)
in an external system: GitHub Projects, Azure Boards, Linear, Jira, etc.

A briefing reads trackers through `kind: tracker` sections of the person's
briefing profile (`workflow/briefings/<id>.yaml`, [docs/briefings.md](../docs/briefings.md)).
The adapters that run them live in `scripts/lib/briefing_providers/`
(github, github-board, gitlab, ado, jira, linear), each tested against
recorded answers, and all emit the normalized schema below. The markdown
files in this directory are the **documentation** of each system: its
commands, state mappings and failure modes. They were once the runtime
(an agent re-read them every briefing); the adapters replaced that, because
a playbook a run can skip is a tracker nobody checked.

## Why a pluggable abstraction

Not every Bridge user is on GitHub. A user at a company running Azure
DevOps adds an `ado` section to their briefing profile instead of (or in
addition to) a `github` one, and `/briefing` renders the same way without
touching any workflow code. A new tracker is a new adapter module with
recorded answers and a test, plus a playbook here that documents it
(see Adding a provider).

## File layout

```
trackers/
  README.md        ← you are here — contract + schema
  github.md        ← working provider: gh CLI
  ado.md           ← example provider: az boards (Azure DevOps)
  gitlab.md        ← provider: glab CLI (GitLab issues)
```

Each playbook documents the adapter of the same name in
`scripts/lib/briefing_providers/`. When the two disagree, the adapter is
right and the playbook is the bug.

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

## How a tracker is configured

A tracker is a `kind: tracker` section in a briefing profile
(`workflow/briefings/<id>.yaml`). The section names the adapter and
carries the adapter's keys:

```yaml
sections:
  - kind: tracker
    id: gitlab-team
    title: "GitLab"
    provider: gitlab                  # module in scripts/lib/briefing_providers/
    query: {repos: [my-group/my-project], limit: 50}
    # account_ref: identity/accounts/<id>.yaml   # only for token based APIs (jira, linear)
    # state_map: {"Waiting for vendor": blocked}  # raw state → normalized, overrides the default
    max: 10
```

The keys each provider understands are in the table in
[`docs/briefings.md` § Tracker providers](../docs/briefings.md#tracker-providers)
and in the docstring at the top of the adapter. `python3 scripts/briefing.py
validate` checks every profile.

**Legacy fallback.** A Bridge without any profile gets a built-in briefing,
which still reads `integrations.github`, `integrations.gitlab` and
`integrations.ado` from `bridge-config.yaml` (`builtin_profile()` in
`scripts/briefing.py`). That fallback covers only those three. Every
other provider, and every profile, is configured as a section.

## Playbook structure

Each `{name}.md` documents one adapter and has this structure:

```markdown
---
name: <provider-name>
description: <one line>
requires: [<CLI tools the adapter calls, e.g. glab; [] for an HTTP API>]
adapter: scripts/lib/briefing_providers/<module>.py
---

# Provider: <Name>

## When to use
<one paragraph; for an API, say why this path (API or CLI) was chosen>

## Profile section
<a YAML example of the section, the query keys with defaults, and for a
token based API the account file (`account_ref` → `token_ref`, `base_url`)>

## Collect
<the exact command or request the adapter sends, so a person can rerun it
by hand when debugging, and the field mapping into the schema above>

## State mapping
<table: raw state → normalized state, including the fallback>

## Type mapping
<how `type` is derived, or that it is fixed>

## Category rules
<which items go to open / qa / done>

## Failure modes
<what makes the section fail, and what the person sees>

## Example run
<normalized output from a real run, redacted, or marked as illustrative>
```

## Adding a provider

1. Write the adapter `scripts/lib/briefing_providers/<module>.py` with a
   `collect(section, ctx)` that returns normalized items and raises
   `source_error(...)` on failure. Use `ctx.run` for a CLI and `ctx.http`
   plus `ctx.account` / `ctx.secret` for an API, never a subprocess or a
   token of its own.
2. Record answers under `scripts/tests/fixtures/briefing/<provider>/` and
   test normalization and failures in `scripts/tests/test_briefing_providers.py`.
3. Add the provider to the table in `docs/briefings.md`.
4. Add `trackers/<name>.md` documenting the adapter, and list it in File
   layout above.

A playbook alone does nothing: no code reads `trackers/*.md` at run time.

## Failure semantics (never-block rule)

A provider that cannot answer raises a source error. The section then
shows `status: error` with the reason, and the rest of the briefing runs:

- CLI not installed or not logged in → error section
- Missing or malformed section keys, missing `token_ref` → error section
- Network error or timeout (default 30 s per call) → error section
- API error answer (HTTP or GraphQL errors) → error section

Any secret read through the engine is scrubbed from the reason. A failing
provider **never** aborts `/briefing`: "Never block. Always let the user
continue working."

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

- **No credentials in `trackers/*.md` or in a profile.** CLI based
  providers (`gh`, `glab`, `az`) use the CLI's own login. Token based APIs
  (Jira, Linear) take `account_ref`, an `identity/accounts/<id>.yaml` whose
  `token_ref` is a reference URI (`keychain://`, `azure-keyvault://`, ...)
  resolved through the secrets engine at run time
  ([`rules/secret-placement.md`](../rules/secret-placement.md)).
- **No credentials in `bridge-config.yaml`.** `validate` refuses a profile
  with a credential named key holding a plain value.
- Trackers are **read-only** for `/briefing`. Write operations
  (creating issues, moving cards) live in dedicated skills like
  `github-projects-manager`.

## Related

- `skills/briefing/references/workflow.md` — Stream B workflow that consumes these providers
- `docs/briefings.md` § Tracker providers: the query keys of every provider
- `scripts/lib/briefing_providers/`: the adapters these playbooks document
- `bridge-config.yaml`: `integrations.github|gitlab|ado`, read only by the built-in briefing (see Legacy fallback)
- `ecosystem.yaml` — `github_projects:` list can be referenced by the github provider via `projects: ecosystem`

- `workflow/projects/<slug>.yaml` — per-board write config consumed by `github-projects-manager`. The `state_map` block defined there feeds back into the normalized item schema above (each tracker's playbook MAY override `state_map` per-project from this registry).
