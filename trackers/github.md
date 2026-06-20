---
name: github
description: GitHub Projects V2 + Issues via the gh CLI
requires: [gh, jq]
config_key: integrations.github
---

# Provider: GitHub

Reads work items from GitHub Projects V2 and optionally from plain
GitHub issues for extra repositories. Uses the `gh` CLI for auth +
transport (no PAT in config needed — `gh auth status` must be green).

## When to use

Enable this if your team tracks work in **GitHub Projects V2** boards
and/or plain GitHub issues. This is the default provider for anyone
hosting code on GitHub.

## Config schema

Add to `bridge-config.yaml`:

```yaml
integrations:
  github:
    enabled: true

    # Option A — list projects explicitly
    projects:
      - { org: my-org,  number: 18, name: "Main Board" }
      - { org: my-org,  number: 25, name: "Operations" }

    # Option B — defer to ecosystem.yaml.github_projects
    # projects: ecosystem

    # Optional — extra repos whose issues should be included
    # even if the issue isn't on any project board
    extra_repos:
      - my-org/some-repo
      - my-org/other-repo

    # Optional — used to flag assigned_to_me
    assignee_me: my-github-username

    # Optional — max items per project (default 50)
    limit: 50
```

All fields except `enabled` are optional. An enabled-but-empty config
still works (the provider will emit zero items and briefing skips the
section).

## Collect

When `/briefing` Stream B loads this file, Claude runs:

### 1. Resolve the project list

```
if config.projects == "ecosystem":
    projects = read ecosystem.yaml.github_projects
else:
    projects = config.projects
```

### 2. For each project — fetch items

```bash
gh project item-list {number} --owner {org} --format json --limit {limit}
```

Parse the JSON. Each item has `content` (Issue or PR), `status`,
`assignees`, `labels`, `updatedAt`, `url`.

### 3. For each extra_repo — fetch open issues

```bash
gh issue list --repo {repo} --state open \
  --json number,title,state,labels,assignees,updatedAt,url,author \
  --limit {limit}
```

Deduplicate against project items (same URL = same item).

### 4. Normalize each item

Map each raw item to the shared schema in `trackers/README.md`:

| Normalized field | Source |
|---|---|
| `id` | `"#" + content.number` |
| `title` | `content.title` |
| `raw_state` | `status` (project) or `state` (issue) |
| `state` | from state map below |
| `type` | from labels (see type rules) |
| `assignee` | `assignees[0].login` |
| `assigned_to_me` | `assignee_me` ∈ `assignees[*].login` |
| `url` | `content.url` |
| `changed_at` | `updatedAt` |
| `project` | project.name or project.number |
| `tracker` | `"github"` |
| `labels` | `labels[*].name` |
| `priority` | label starting with `priority:` or `P1`/`P2` |
| `category` | see category rules below |

### 5. Emit the combined list

## State mapping

Map the GitHub project-status label → normalized state:

| raw_state | state |
|---|---|
| `Backlog` | `new` |
| `Todo`, `Ready`, `To Do` | `ready` |
| `In Progress`, `Doing` | `in_progress` |
| `In Review`, `Review`, `Code Review` | `review` |
| `Done`, `Closed`, `Completed` | `done` |
| `Blocked` | `blocked` |
| anything else | `new` (fallback) + log a warning |

A user can override this mapping by adding `state_map:` under
`integrations.github` in bridge-config.yaml.

## Type mapping

Derive `type` from labels, first match wins:

| Label pattern | type |
|---|---|
| `bug`, `defect`, `incident` | `bug` |
| `feature`, `enhancement` | `feature` |
| `epic` | `epic` |
| `story`, `user-story` | `story` |
| `task`, `chore` | `task` |
| (none of the above) | `issue` |

## Category rules

| Rule | category |
|---|---|
| `state == done` | `done` |
| `state == review` AND `assigned_to_me == true` | `qa` |
| any label in `["needs-qa", "needs-testing", "qa-queue"]` | `qa` |
| otherwise | `open` |

QA mapping is deliberately conservative for GitHub because most teams
don't run a formal "Ready for Testing" column. Users who do can add
their own label-based rules here.

## Failure modes

| Condition | Action |
|---|---|
| `gh` not installed (`command -v gh` fails) | Warning, skip provider |
| `gh auth status` not green | Warning with hint to run `gh auth login`, skip |
| Project not accessible (404 / 403) | Warning for that project only, continue with other projects |
| Single command >10s | Timeout, skip that command, continue |
| JSON parse error | Warning, skip that command's items |
| Zero items across everything | Briefing omits the GitHub section |

None of these abort `/briefing`.

## Example run

With a config like
`projects: [{org: my-org, number: 7}]` and `assignee_me: alice`,
a run produces normalized items in this shape:

```json
[
  {
    "id": "#42",
    "title": "Example issue title",
    "state": "in_progress",
    "raw_state": "In Progress",
    "type": "bug",
    "assignee": "alice",
    "assigned_to_me": true,
    "url": "https://github.com/my-org/some-repo/issues/42",
    "changed_at": "2026-01-15T12:00:00Z",
    "project": "Main Board",
    "tracker": "github",
    "labels": ["bug"],
    "priority": null,
    "category": "open"
  }
]
```

## Related

- `trackers/README.md` — the shared contract this file implements
- `ecosystem.yaml` — source for `projects: ecosystem`
- `skills/project-advisor/` — governance rules for issue creation and board health (write-side uses `github-projects-manager` skill)
