---
name: ado
description: Azure DevOps Boards via the az CLI (WIQL queries)
requires: [az, jq]
config_key: integrations.ado
---

# Provider: Azure DevOps (Boards)

Reads work items from an Azure DevOps project via `az boards query`
with WIQL. Auth comes from `az login` — no PAT in config needed
(though a PAT is optional via `auth.pat_env` if you prefer).

## When to use

Enable this if your team tracks work in **Azure DevOps Boards**
(User Stories, Bugs, Tasks, QA states like "Ready for Testing" /
"In Testing" / "Approved by QA"). Typical for enterprise shops
using the Microsoft stack.

## Config schema

Add to `bridge-config.yaml`:

```yaml
integrations:
  ado:
    enabled: true

    # Your organisation URL — replace with your own
    org: https://dev.azure.com/YOUR-ORG
    project: YOUR-PROJECT
    area_path: YOUR-PROJECT             # optional — narrows queries

    # Auth
    auth:
      method: az-cli                    # az login is enough
      # OR
      # method: pat
      # pat_env: AZURE_DEVOPS_PAT       # read PAT from env var

    # Identity — used to flag assigned_to_me
    # (the WIQL @Me macro resolves this server-side already,
    # but for rendering we still want the name)
    assignee_me: "Lastname, Firstname"

    # Optional — query overrides (defaults below work for most teams)
    queries:
      open: null        # null = use default
      qa: null
      done_window_days: 3
```

A minimal enabled-config only needs `enabled`, `org`, `project`.

## Collect

When `/briefing` Stream B loads this file, Claude runs three WIQL
queries in parallel and merges the results.

### Query 1 — open items assigned to me

```
SELECT [System.Id], [System.Title], [System.State],
       [System.WorkItemType], [System.AssignedTo], [System.ChangedDate],
       [System.Tags], [Microsoft.VSTS.Common.Priority]
FROM WorkItems
WHERE [System.AssignedTo] = @Me
  AND [System.State] NOT IN ('Done', 'Closed', 'Removed', 'Approved by QA')
  AND [System.WorkItemType] IN ('User Story', 'Bug', 'Task')
ORDER BY [System.ChangedDate] DESC
```

Shell:
```bash
az boards query \
  --wiql "<query above>" \
  --org {config.org} -p {config.project} \
  -o json
```

### Query 2 — QA queue (team-wide)

```
SELECT [System.Id], [System.Title], [System.State],
       [System.WorkItemType], [System.AssignedTo], [System.ChangedDate]
FROM WorkItems
WHERE [System.State] IN ('Ready for Testing', 'In Testing')
  AND [System.WorkItemType] IN ('Bug', 'User Story', 'Task')
  AND [System.AreaPath] UNDER '{config.area_path}'
ORDER BY [System.WorkItemType], [System.ChangedDate] DESC
```

This is team-wide on purpose — the QA queue shows what needs testing
regardless of assignee, with items owned by the user highlighted in
the briefing render.

### Query 3 — recently done (rolling window)

**Note:** `@today - N` in WIQL is unreliable on some ADO tenants
(returns empty on weekends/holidays). Use a computed absolute date
instead:

```bash
# Compute the cutoff date dynamically
DONE_DAYS={config.queries.done_window_days}  # default: 3
CUTOFF=$(date -v-${DONE_DAYS}d +%Y-%m-%d)
```

```
SELECT [System.Id], [System.Title], [System.State],
       [System.WorkItemType], [System.ChangedDate]
FROM WorkItems
WHERE [System.AssignedTo] = @Me
  AND [System.State] IN ('Done', 'Approved by QA')
  AND [System.ChangedDate] >= '{CUTOFF}'
  AND [System.WorkItemType] IN ('User Story', 'Bug', 'Task')
ORDER BY [System.ChangedDate] DESC
```

### Normalize

For every row from every query, build the shared schema item:

| Normalized field | Source |
|---|---|
| `id` | `"#" + System.Id` |
| `title` | `System.Title` |
| `raw_state` | `System.State` |
| `state` | from state map below |
| `type` | from `System.WorkItemType` (see type map) |
| `assignee` | `System.AssignedTo` display name |
| `assigned_to_me` | assignee == `config.assignee_me` |
| `url` | `{org}/{project}/_workitems/edit/{id}` |
| `changed_at` | `System.ChangedDate` |
| `project` | `config.project` |
| `tracker` | `"ado"` |
| `labels` | `System.Tags` split on `; ` |
| `priority` | `Microsoft.VSTS.Common.Priority` → `P1`..`P4` |
| `category` | see category rules below |

## State mapping

| raw_state | state |
|---|---|
| `New`, `Proposed` | `new` |
| `Active`, `Committed`, `Approved` | `ready` |
| `In Progress` | `in_progress` |
| `Ready for Testing`, `In Testing` | `review` |
| `Done`, `Approved by QA`, `Closed` | `done` |
| `Removed` | `removed` |
| `Blocked` | `blocked` |
| anything else | `new` (fallback) |

Users can override by adding `state_map:` under `integrations.ado`
in bridge-config.yaml if their process template uses different names.

## Type mapping

| Work Item Type | type |
|---|---|
| `Bug` | `bug` |
| `User Story`, `Product Backlog Item`, `Requirement` | `story` |
| `Task` | `task` |
| `Feature` | `feature` |
| `Epic` | `epic` |
| anything else | `issue` |

## Category rules

| Rule | category |
|---|---|
| Query 3 (recently done) | `done` |
| Query 2 (QA queue) | `qa` |
| Query 1 (open assigned to me) | `open` |

An item that appears in both Query 1 and Query 2 (e.g. assigned to me
AND in "Ready for Testing") gets deduped — the `qa` row wins.

## Failure modes

| Condition | Action |
|---|---|
| `az` not installed (`command -v az` fails) | Warning, skip provider |
| `az account show` fails | Warning with hint to run `az login`, skip |
| `az devops configure --defaults organization=... project=...` missing | Warning, skip |
| WIQL syntax error (bad override) | Warning, fall back to default WIQL |
| Org / project 404 | Warning, skip |
| Single query >10s | Timeout, skip that query, continue with others |
| Zero items across all queries | Briefing omits the ADO section |

None of these abort `/briefing`.

## Adoption checklist for another Bridge user

If you're copying this setup into your own Bridge instance:

1. `az login` and verify `az account show` works
2. Add the `integrations.ado` block to your `bridge-config.yaml` with
   your org URL and project name (both `org:` and `project:` required)
3. Set `integrations.github.enabled: false` if you don't use GitHub
   Projects — otherwise both trackers run and both render
4. Run `/briefing --quick` first — the `--quick` flag skips Stream B,
   so any config issue only shows up once you run `/briefing` without
   the flag (Stream B errors come as warnings, not hard failures)
5. If your ADO process template uses different state names than the
   ones in the state-mapping table above, add a `state_map:` override
   under `integrations.ado`
6. If the default QA queue ("Ready for Testing" / "In Testing") doesn't
   match your team's workflow, override `queries.qa:` with your own WIQL

This file is the reference implementation. It is **not** necessarily
tested against a live ADO tenant inside every Bridge fork — many
maintainers run on GitHub. Issues and improvements from ADO users
are welcome upstream.

## Related

- `trackers/README.md` — the shared contract this file implements
- `trackers/github.md` — sibling provider, for comparison
