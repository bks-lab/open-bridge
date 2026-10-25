---
name: gitlab
description: GitLab issues via the glab CLI
requires: [glab]
adapter: scripts/lib/briefing_providers/gitlab.py
---

# Provider: GitLab

Reads work items from GitLab Issues through the `glab` CLI, which handles
auth and transport with its own login (`glab auth status` must be green).
No token goes into the profile or `bridge-config.yaml`.

This file documents `scripts/lib/briefing_providers/gitlab.py`. When the
two disagree, the adapter is right.

## When to use

Use this if your team tracks work in **GitLab Issues**, on GitLab.com or a
self-managed instance. The CLI path was chosen because `glab` already
carries the login, so the Bridge stores no credential.

## Profile section

Add a section to your briefing profile (`workflow/briefings/<id>.yaml`):

```yaml
sections:
  - kind: tracker
    id: gitlab
    title: "GitLab"
    provider: gitlab
    query:
      repos:                    # required: GitLab projects as group/project
        - my-group/my-project
        - my-group/sub-group/other-project
      assignee: "@me"           # default "@me"; or a username
      state: opened             # opened (default) | closed
      labels: [bug]             # optional: every label must be present
      limit: 50                 # per repo, default 50
    # state_map: {"opened": ready}   # optional: raw state → normalized
```

`assigned_to_me` is true when your own GitLab login is among the
assignees. Your login comes from `integrations.gitlab.assignee_me` in
`bridge-config.yaml` when set, else from `glab api user`. Without either,
an `assignee: "@me"` query counts as yours.

**Without a profile** the built-in briefing still reads
`integrations.gitlab` (`enabled`, `repos`, `limit`) from
`bridge-config.yaml` and turns it into this section. That fallback exists
for Bridges configured before profiles; new setups use the section.

## Collect

For each repo in `query.repos` the adapter runs one command:

```bash
glab issue list --repo {repo} --assignee {assignee} \
  --output json --per-page {limit} [--closed] [--label {label} ...]
```

`--closed` is added for `state: closed`, one `--label` per label. Run the
same command by hand to see what the adapter sees.

Each issue maps to the shared schema in `trackers/README.md`:

| Normalized field | Source |
|---|---|
| `id` | `{repo}#{iid}`, e.g. `my-group/my-project#42` |
| `title` | `title` |
| `raw_state` | `state` (`opened` / `closed`) |
| `state` | see State mapping |
| `type` | see Type mapping |
| `assignee` | `assignees[0].username` |
| `assigned_to_me` | your login ∈ `assignees[*].username` (see above) |
| `url` | `web_url` |
| `changed_at` | `updated_at` |
| `project` | the repo path |
| `tracker` | `"gitlab"` |
| `labels` | `labels[*]` |
| `priority` | first label starting with `priority:`, or `P0` ... `P9` |
| `category` | see Category rules |

## State mapping

GitLab issues have only two raw states, so labels refine them. Label
matching ignores case. First match wins, top to bottom:

| raw_state / label | state |
|---|---|
| `closed` | `done` |
| label `blocked` | `blocked` |
| label `in-review`, `review`, `in review` | `review` |
| label `in-progress`, `doing`, `in progress` | `in_progress` |
| `opened`, no matching label | `ready` |

A `state_map` on the section overrides this.

## Type mapping

Derived from labels (ignoring case), first match wins:

| Label | type |
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
| `state == review` | `qa` |
| any label in `needs-qa`, `needs-testing`, `qa-queue` | `qa` |
| otherwise | `open` |

## Failure modes

Each of these makes the section show `status: error` with the reason; the
rest of the briefing runs:

| Condition | Reason shown |
|---|---|
| `query.repos` missing or empty | `query.repos is required` |
| `glab` not installed, not logged in, or the repo not reachable | the CLI's message |
| Command slower than the timeout (default 30 s) | timeout |
| Answer is not JSON, or not a list | `not JSON` / `unexpected answer` |

Zero issues is not an error: the section completes with no rows.

## Example run

With `repos: [my-group/my-project]` and the default `assignee: "@me"`, a
run produces items in this shape (illustrative):

```json
[
  {
    "id": "my-group/my-project#42",
    "title": "Example issue title",
    "state": "ready",
    "raw_state": "opened",
    "type": "bug",
    "assignee": "alice",
    "assigned_to_me": true,
    "url": "https://gitlab.example.com/my-group/my-project/-/issues/42",
    "changed_at": "2026-01-15T12:00:00Z",
    "project": "my-group/my-project",
    "tracker": "gitlab",
    "labels": ["bug"],
    "priority": null,
    "category": "open"
  }
]
```

## Related

- `trackers/README.md`: the shared schema and how a tracker is configured
- `scripts/lib/briefing_providers/gitlab.py`: the adapter this file documents
- `scripts/tests/test_briefing_providers.py`, `scripts/tests/fixtures/briefing/gitlab/`: its tests
- `docs/briefings.md` § Tracker providers: the query keys of every provider
