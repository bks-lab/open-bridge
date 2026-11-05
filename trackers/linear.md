---
name: linear
description: Linear issues via the GraphQL API
requires: []
adapter: scripts/lib/briefing_providers/linear.py
---

# Provider: Linear

Reads work items from Linear through its GraphQL API with a personal API
key. The key never goes into the profile or `bridge-config.yaml`: the
section names an account file, and that file holds a reference URI.

This file documents `scripts/lib/briefing_providers/linear.py`. When the
two disagree, the adapter is right.

## When to use

Use this if your team tracks work in **Linear**. The adapter talks to
Linear's GraphQL API directly, so there is no extra CLI to install and log
in; one HTTP request per run is all it takes.

## Profile section

Add a section to your briefing profile (`workflow/briefings/<id>.yaml`):

```yaml
sections:
  - kind: tracker
    id: linear
    title: "Linear"
    provider: linear
    account_ref: linear-example     # identity/accounts/linear-example.yaml
    query:
      team: ENG                     # optional: one team key, not a list
      limit: 50                     # default 50
      # filter: {...}               # optional: a raw Linear IssueFilter, see below
    # state_map: {"Waiting for vendor": blocked}   # optional: raw state name → normalized
```

All `query` keys are optional:

| Key | Default | Effect |
|---|---|---|
| `filter` | none | A raw Linear `IssueFilter` object. Replaces the default scope (see Collect) |
| `team` | none | One team key, e.g. `ENG`. Adds `team: {key: {eq: ENG}}` to the filter |
| `limit` | `50` | `first:` of the single request. There is no pagination |

`state_map` sits on the section, not per team, and matches the raw state
**name** (`state.name`, e.g. `"In Review"`). It replaces `state` only; the
`category` was already derived from the adapter's own mapping and stays.

### Account file and token

`account_ref` names `identity/accounts/<id>.yaml`:

```yaml
# identity/accounts/linear-example.yaml
id: linear-example
scope: user
display_name: "Linear (example)"
owner: your-handle
token_ref: keychain://example/linear-api-key    # the value lives in the keychain
# base_url: https://api.linear.app/graphql      # default; only for a proxy or a test server
```

`token_ref` is a reference URI (`keychain://`, `azure-keyvault://`,
`1password://`), resolved through the secrets engine at run time
([`rules/secret-placement.md`](../rules/secret-placement.md)). Use a
personal API key from your Linear settings; the briefing only reads.

**The key is sent as `Authorization: <key>`, without `Bearer`.** That is
what Linear expects for personal API keys; `Bearer` belongs to OAuth access
tokens. If the section fails with an authentication error, check first that
the stored value is the bare key with no prefix.
The key appears in no result row and no error line.

## Collect

The adapter sends **one** `POST` to `base_url`. Which query depends on
whether the section sets `query.filter`.

**Without `filter`** (the default) it asks for the issues assigned to you
that are not completed or canceled. Every row gets `assigned_to_me: true`:

```graphql
query($filter: IssueFilter) {
  viewer {
    assignedIssues(first: 50, filter: $filter) {
      nodes {
        identifier title url updatedAt priorityLabel
        state { name type }
        labels { nodes { name } }
        assignee { name }
        project { name }
        team { key }
      }
    }
  }
}
```

with the variables

```json
{"filter": {"state": {"type": {"nin": ["completed", "canceled"]}}}}
```

plus `"team": {"key": {"eq": "ENG"}}` inside `filter` when `query.team` is set.

**With `filter`** it asks `issues(first: <limit>, filter: $filter)` with the
same node fields, passing your filter (plus the team clause) as `$filter`.
Your filter replaces the default completely, so add the state clause
yourself if you still want open issues only. Every row gets
`assigned_to_me: false`, because the adapter cannot tell whose they are.

To see what the adapter sees, send the same request by hand. The key is
read from the environment so it stays out of your shell history:

```bash
curl -s https://api.linear.app/graphql \
  -H "Authorization: $LINEAR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query":"query($filter: IssueFilter) { viewer { assignedIssues(first: 50, filter: $filter) { nodes { identifier title url updatedAt priorityLabel state { name type } labels { nodes { name } } assignee { name } project { name } team { key } } } } }","variables":{"filter":{"state":{"type":{"nin":["completed","canceled"]}}}}}'
```

Each node maps to the shared schema in `trackers/README.md`:

| Normalized field | Source |
|---|---|
| `id` | `identifier`, e.g. `ENG-12` |
| `title` | `title` |
| `raw_state` | `state.name` |
| `state` | see State mapping |
| `type` | always `issue` (see Type mapping) |
| `assignee` | `assignee.name` |
| `assigned_to_me` | `true` for the default scope, `false` with a custom `filter` |
| `url` | `url` |
| `changed_at` | `updatedAt` |
| `project` | `project.name`, falling back to `team.key` |
| `tracker` | `"linear"` |
| `labels` | `labels.nodes[].name` |
| `priority` | `priorityLabel`; `"No priority"` becomes `null` |
| `category` | see Category rules |

## State mapping

The adapter maps Linear's workflow state **type** (`state.type`). Then one
name rule applies: a state whose **name** contains `review` (any case)
becomes `review`, unless the type already mapped to `done` or `removed`.

| `state.type` | state |
|---|---|
| `triage` | `new` |
| `backlog` | `new` |
| `unstarted` | `ready` |
| `started` | `in_progress` (`review` if the name contains "review") |
| `completed` | `done` |
| `canceled` | `removed` |
| any other or missing type | `new` |

A `state_map` on the section overrides the result per raw state name.

## Type mapping

Linear has no issue type field. The adapter always emits `type: issue`;
labels are passed through in `labels` but do not set a type.

## Category rules

Derived from the mapped state:

| state | category |
|---|---|
| `done`, `removed` | `done` |
| `review` | `qa` |
| everything else | `open` |

The default scope never returns completed or canceled issues, so `done`
rows appear only with a custom `filter`.

## Failure modes

Each of these fails the **whole section** with `status: error` and the
reason; the rest of the briefing runs. There is no skipping per team or per
row:

| Condition | Reason shown |
|---|---|
| Account file has no `token_ref` | `linear account file is missing 'token_ref'` |
| `token_ref` cannot be resolved | the secrets engine's message |
| Network error, HTTP error or timeout (default 30 s) | the transport's message |
| GraphQL `errors` in the answer, e.g. a wrong key or `Bearer` prefix | `linear: GraphQL error: <first message>` |
| The answer is not a JSON object | `linear: unexpected answer` |

Zero issues is not an error: the section completes with no rows.

## Example run

Normalized output for the recorded answer in
`scripts/tests/fixtures/briefing/linear/assigned.json` (illustrative data,
default scope, `team: ENG`), first two rows:

```json
[
  {
    "id": "ENG-12",
    "title": "Cache warm-up on deploy",
    "state": "in_progress",
    "raw_state": "In Progress",
    "type": "issue",
    "assignee": "Alice Example",
    "assigned_to_me": true,
    "url": "https://linear.app/example-org/issue/ENG-12",
    "changed_at": "2026-10-03T10:20:00.000Z",
    "project": "Platform",
    "labels": ["backend"],
    "priority": "High",
    "category": "open",
    "tracker": "linear"
  },
  {
    "id": "ENG-13",
    "title": "Document retry policy",
    "state": "ready",
    "raw_state": "Todo",
    "type": "issue",
    "assignee": "Alice Example",
    "assigned_to_me": true,
    "url": "https://linear.app/example-org/issue/ENG-13",
    "changed_at": "2026-10-02T09:00:00.000Z",
    "project": "ENG",
    "labels": [],
    "priority": null,
    "category": "open",
    "tracker": "linear"
  }
]
```

The same recording also shows `In Review` → `review` / `qa` and
`Triage` → `new`.

## Related

- `trackers/README.md`: the shared schema and how a tracker is configured
- `scripts/lib/briefing_providers/linear.py`: the adapter this file documents
- `scripts/tests/test_briefing_providers.py`, `scripts/tests/fixtures/briefing/linear/`: its tests
- [`docs/briefings.md`](../docs/briefings.md) § Tracker providers and § Tokens: references only
- [`rules/secret-placement.md`](../rules/secret-placement.md): why the key is a reference URI
