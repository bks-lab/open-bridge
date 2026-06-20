# Task-Reconciliation — Match Action Items to Existing Issues

This reference is used by **`/debrief`** (Phase 4) and is callable from
**`/briefing`** Stream C when the user opts to process a transcript.

## Purpose

Before creating new GitHub issues from a meeting's action items, compare
them to **existing open issues** in the relevant project(s). Prefer
`UPDATE` over `CREATE` — one enriched comment on the right issue beats
three fragmented new ones.

## Inputs

| Input | Source |
|---|---|
| `action_items` | Phase 3 (7-category extraction) |
| `reconcile_projects` | `classification.md` → `meeting_types.{type}.reconcile_projects` |
| Project schema + `repo_map` | `workflow/projects/{slug}.yaml` |
| Available assignees | `gh api repos/{repo}/assignees` |
| Mandant-to-GitHub handle map | optional `identity/mandants/{id}.yaml` `github:` field (fallback: ask user) |

## Minimum Principle (hard rule)

**Aim for 1–5 issue operations per meeting, not per action item.**

- Group related micro-tasks (e.g. three outgoing mails of the same thread)
  into **one comment on the parent issue**, not three new issues.
- Info-only items ("Internship starts in 1 week", "vendor audit proof ok")
  belong in the **protocol**, not in issues.
- Calendar blocks (`/calendar add …`) are not issues.

If the user ever says "too much", obey immediately — issues are cheap to
add later, expensive to clean up.

## Process

### Step 1 — Pre-load open issues

For each project in `reconcile_projects`, run:

```bash
gh project item-list <N> --owner <org> --format json --limit 200 \
  | jq '.items[] | {id, status, num: .content.number, title: .content.title,
                    repo: .content.repository, url: .content.url,
                    assignees: .content.assignees}'
```

Cache result. The `id` here is the **Project Item ID** (`PVTI_...`), needed
for field updates. The `num` is the issue number in the source repo.

### Step 2 — Score matches

For each action item compute confidence against cached issues:

| Signal | Weight | How |
|---|---|---|
| Title keyword overlap | 50 % | Longest common n-grams, ignoring stop-words |
| Owner match | 20 % | Action-item owner == existing assignee |
| Topic/label match | 20 % | Action context == existing label |
| Recency | 10 % | Issues updated in last 30 d score higher |

Thresholds: `≥70 %` → **HIGH** (auto-propose UPDATE), `40–70 %` → **MEDIUM**
(propose UPDATE, offer CREATE alternative), `<40 %` → **NO match** (propose
CREATE only if action is real — see minimum principle).

### Step 3 — Build decision matrix (Checkpoint 2)

Present a compact table first, details beneath. Each row shows operation,
target, reason. Columns:

```
# | Op | Target | Action item | Assignee | Reason
```

Per-row gates: `[y]` apply · `[e]` edit · `[s]` skip · `[n]` flip CREATE↔UPDATE

### Step 4 — Fetch field & option IDs (once per project)

Only needed before the first field-changing mutation:

```bash
gh api graphql -f query='query {
  organization(login: "<org>") { projectV2(number: <N>) {
    id
    fields(first: 50) { nodes {
      ... on ProjectV2FieldCommon { id name }
      ... on ProjectV2SingleSelectField { id name options { id name } }
    } }
  } }
}'
```

Cache: `project_id`, each `field_id`, and `option_id` for the options we
plan to set.

### Step 5 — Execute approved operations

Run these **in parallel** — they are independent:

**Add a comment to an issue**
```bash
gh issue comment <num> -R <repo> --body "..."
```

**Add an assignee**
```bash
gh issue edit <num> -R <repo> --add-assignee <handle>
```

**Set a single-select project field**
```bash
gh api graphql -f query='mutation {
  updateProjectV2ItemFieldValue(input: {
    projectId: "<project_id>",
    itemId: "<item_id>",
    fieldId: "<field_id>",
    value: { singleSelectOptionId: "<option_id>" }
  }) { projectV2Item { id } }
}'
```

**Create a new issue** (only when no match + minimum-principle passed):
Use execution patterns from `skills/github-projects-manager/`. Fields come
from `workflow/projects/{slug}.yaml` defaults, not hardcoded.

### Step 6 — Collect results for downstream phases

Return to the caller a structured list:

```yaml
operations:
  - op: UPDATE
    issue: 42
    repo: my-org/wiki
    url: https://github.com/my-org/wiki/issues/42
    comment_url: https://github.com/.../issuecomment-0000000001
    fields_changed: [status, assignees]
  - op: CREATE
    issue: 72
    ...
```

The URLs feed directly into **Phase 6 protocol generation** and **Phase 7
distribution email**.

## Governance compliance

Read `workflow/projects/{slug}.yaml` → `governance` before any UPDATE. Respect:

- `assignee_on_in_progress: true` — if moving to "In Progress", set assignee
- `comment_on_status_change: true` — add a comment when status changes
- `done_only_by_user: true` — never set Done; use "In Review" and let user confirm
- `all_fields_required: true` — new issues must have every required field

## Integration

Called from:
- `skills/debrief/references/full-workflow.md` Phase 4
- `skills/briefing/references/workflow.md` Stream C (indirectly via `/debrief`)

Depends on:
- `workflow/projects/{slug}.yaml` (schema, governance, repo_map)
- `skills/github-projects-manager/` (for CREATE execution)
- `gh` CLI with project + repo scopes
