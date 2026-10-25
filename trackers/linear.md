---
name: linear
description: Linear issues via the GraphQL API
requires: []
config_key: integrations.linear
---

# Provider: Linear

Collects issues from Linear using its GraphQL API and normalizes them into the shared tracker schema defined in `trackers/README.md`.

The provider is read-only. Store the Linear API key in an approved secure location; never include credentials in this playbook or `bridge-config.yaml`.

## When to use

Use this provider when a team tracks bugs, tasks, features, and other work items in Linear and wants those items included in the briefing.

## Config schema

Add the following configuration to `bridge-config.yaml`:

```yaml
integrations:
  linear:
    enabled: true
    # Optional: Linear team IDs or keys to collect from.
    teams: []
    # Optional: maximum number of issues to collect.
    limit: 50
    # Optional: team-specific workflow state overrides.
    state_map:
      TEAM_ID:
       "In Progress": in_progress
         "Ready for QA": in_progress
    # Optional: labels used to identify items needing QA.
    qa_labels:
      - needs-qa
      - needs-testing
      - qa-queue
```

The API key must be supplied through a secure mechanism, such as an environment variable or an approved secret store. Do not place the API key in this configuration.

Configuration fields other than `enabled` are optional. If no teams are configured, collect only from teams the authenticated user is authorized to access, subject to the provider's configured limits.

## Collect

1. Read the `integrations.linear` configuration.
2. Check whether the provider is enabled.
3. Obtain the Linear API key from the configured secure location.
4. Send authenticated GraphQL requests to Linear's API endpoint.
5. Query issues for the configured teams and request the fields needed for normalization, including the issue identifier, title, URL, workflow state, assignee, labels, priority, project, and update timestamp.
6. Follow GraphQL pagination until the configured limit is reached or no further page is available.
7. Normalize each issue according to the shared schema in `trackers/README.md`.
8. Apply the configured state overrides, type mapping, and category rules.
9. Return the normalized items to the briefing provider interface.

The provider must be read-only. It must not create, update, or delete Linear issues.

## State mapping

Map Linear workflow state types to the normalized state enum:

| Linear workflow state type | Normalized state |
| -------------------------- | ---------------- |
| `backlog`                  | `new`            |
| `unstarted`                | `ready`          |
| `started`                  | `in_progress`    |
| `completed`                | `done`           |
| `canceled`                 | `removed`        |

Use the Linear workflow state name as `raw_state`.

A team-specific `state_map` override may map customized workflow state names to normalized states. Apply a matching team-specific override before using the default mapping. Only use values permitted by the normalized state enum in `trackers/README.md`.

If a workflow state cannot be mapped, preserve its original name in `raw_state` and use a documented, safe fallback rather than inventing a normalized state.

## Type mapping

Normalize the issue type using available type information and labels:

| Linear issue type or label | Normalized type |
| -------------------------- | --------------- |
| Bug, defect, or incident   | `bug`           |
| Feature or enhancement     | `feature`       |
| Epic                       | `epic`          |
| Story or user story        | `story`         |
| Task or chore              | `task`          |
| No matching type           | `issue`         |

Use case-insensitive matching. If no explicit issue type is available, use the labels as a fallback. If no rule matches, use `issue`.

## Category rules

The normalized `category` must be one of `open`, `qa`, or `done`.

| Condition                                              | Category |
| ------------------------------------------------------ | -------- |
| Normalized state is `done`                             | `done`   |
| State or labels indicate review or testing is required | `qa`     |
| A configured QA label is present                       | `qa`     |
| Otherwise                                              | `open`   |

Apply the `done` rule first. Do not classify a completed item as `qa` merely because it retains a QA label.

The provider should use the shared schema's definition of `assigned_to_me` when determining whether an item is assigned to the current user.

## Failure modes

| Condition                                | Action                                         |
| ---------------------------------------- | ---------------------------------------------- |
| Provider is disabled                     | Skip the provider                              |
| API key is missing                       | Warn and skip the provider                     |
| Authentication fails                     | Warn and skip the provider                     |
| A team is inaccessible                   | Warn for that team and continue where possible |
| A request exceeds the documented timeout | Warn and skip the affected request             |
| GraphQL returns errors                   | Warn and skip affected results where safe      |
| Response cannot be parsed                | Warn and skip affected results                 |
| No issues are returned                   | Omit the Linear section                        |

A Linear provider failure must never abort `/briefing`. Follow the failure-handling contract in `trackers/README.md`.

## Example run

The following is illustrative normalized output, not a claim that a live Linear workspace was queried:

```json
[
  {
    "id": "ENG-42",
    "title": "Example issue title",
    "state": "in_progress",
    "raw_state": "In Progress",
    "type": "bug",
    "assignee": "Example User",
    "assigned_to_me": false,
    "url": "https://linear.app/example/issue/ENG-42",
    "changed_at": "2026-04-11T12:00:00Z",
    "project": "Example Project",
    "tracker": "linear",
    "labels": ["bug"],
    "priority": null,
    "category": "open"
  }
]
```

A live example should use a free or throwaway workspace and must not expose API keys, private issue details, or other sensitive information.

## Related

* `trackers/README.md` — shared tracker schema and provider contract.
* `trackers/gitlab.md` — reference implementation of the tracker playbook format.
