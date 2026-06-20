# Execution Patterns — gh CLI & GraphQL

How to execute project operations. All commands read field values from
`workflow/projects/{slug}.yaml` — never hardcode status names, emojis, or priority values.

## Prerequisites

```bash
gh auth status          # Must be authenticated
gh extension list       # Optional: gh-project extension
```

## Load Project Config First

Before ANY operation, load the matching project config:

```
1. Identify project (from user context, issue URL, or explicit #number)
2. Read workflow/projects/{slug}.yaml
3. Use fields.{field}.values for valid options
4. Use governance.rules for enforcement
5. Execute with values from config
```

## Issue Creation

```bash
# Step 1: Create issue in the correct repo (from config project.issue_repo)
gh issue create \
  --repo {config.project.org}/{config.project.issue_repo} \
  --title "{title}" \
  --body "{body}" \
  --label "{labels}"

# Step 2: Add to project board
gh project item-add {config.project.number} \
  --owner {config.project.org} \
  --url {issue_url}

# Step 3: Verify (K5 — always verify)
gh project item-list {config.project.number} \
  --owner {config.project.org} \
  --format json \
  | jq '.items[] | select(.content.url == "{issue_url}")'
```

## Field Updates (CLI-supported fields)

These fields can be updated via `gh project item-edit` or `gh issue edit`:

```bash
# Assignee
gh issue edit {number} --repo {org}/{repo} --add-assignee {username}
gh issue edit {number} --repo {org}/{repo} --remove-assignee {username}

# Labels
gh issue edit {number} --repo {org}/{repo} --add-label "{label}"
gh issue edit {number} --repo {org}/{repo} --remove-label "{label}"

# Title and body
gh issue edit {number} --repo {org}/{repo} --title "{new_title}"
gh issue edit {number} --repo {org}/{repo} --body "{new_body}"

# Close / reopen (only via "In Review" per K1!)
gh issue close {number} --repo {org}/{repo} --comment "{review_comment}"
gh issue reopen {number} --repo {org}/{repo}
```

## Field Updates (GraphQL — for project-level custom fields)

Project V2 custom fields (Status, Priority, Type, Size, Stage, Application,
Blocked, Assignment, Dependency) require GraphQL mutations.

### Step 1: Get Project ID

```bash
PROJECT_ID=$(gh api graphql -f query='
  query($org: String!, $num: Int!) {
    organization(login: $org) {
      projectV2(number: $num) { id }
    }
  }' -f org="{config.project.org}" -F num={config.project.number} \
  --jq '.data.organization.projectV2.id')
```

### Step 2: Get Field ID + Option ID

```bash
# List all fields and their options
gh api graphql -f query='
  query($id: ID!) {
    node(id: $id) {
      ... on ProjectV2 {
        fields(first: 30) {
          nodes {
            ... on ProjectV2SingleSelectField {
              id name
              options { id name }
            }
            ... on ProjectV2Field {
              id name
            }
          }
        }
      }
    }
  }' -f id="$PROJECT_ID"
```

From the response, find the field by name and the option by value.
**Use exact values from `workflow/projects/{slug}.yaml` fields section** — including
emoji prefixes if the project uses them.

### Step 3: Get Item ID (for the issue on the board)

```bash
ITEM_ID=$(gh api graphql -f query='
  query($id: ID!) {
    node(id: $id) {
      ... on ProjectV2 {
        items(first: 100) {
          nodes {
            id
            content { ... on Issue { number url } }
          }
        }
      }
    }
  }' -f id="$PROJECT_ID" \
  --jq ".data.node.items.nodes[] | select(.content.url == \"$ISSUE_URL\") | .id")
```

### Step 4: Update field value

```bash
gh api graphql -f query='
  mutation($project: ID!, $item: ID!, $field: ID!, $value: String!) {
    updateProjectV2ItemFieldValue(input: {
      projectId: $project
      itemId: $item
      fieldId: $field
      value: {singleSelectOptionId: $value}
    }) {
      projectV2Item { id }
    }
  }' -f project="$PROJECT_ID" -f item="$ITEM_ID" \
     -f field="$FIELD_ID" -f value="$OPTION_ID"
```

### Text and Date fields

```bash
# Text field (e.g. "Blocked Reason", "External Link")
gh api graphql -f query='
  mutation($project: ID!, $item: ID!, $field: ID!, $text: String!) {
    updateProjectV2ItemFieldValue(input: {
      projectId: $project
      itemId: $item
      fieldId: $field
      value: {text: $text}
    }) {
      projectV2Item { id }
    }
  }' -f project="$PROJECT_ID" -f item="$ITEM_ID" \
     -f field="$FIELD_ID" -f text="Waiting for customer response"

# Date field (e.g. "Due Date")
# value: {date: "2026-04-30"}
```

## Board Health Validation (R1-R7)

Query all items with their field values:

```bash
gh api graphql -f query='
  query($org: String!, $num: Int!) {
    organization(login: $org) {
      projectV2(number: $num) {
        title
        items(first: 100) {
          nodes {
            id
            fieldValues(first: 20) {
              nodes {
                ... on ProjectV2ItemFieldSingleSelectValue {
                  name
                  field { ... on ProjectV2SingleSelectField { name } }
                }
              }
            }
            content {
              ... on Issue {
                number title state url
                repository { name }
                assignees(first: 5) { nodes { login } }
                updatedAt
              }
            }
          }
        }
      }
    }
  }' -f org="{config.project.org}" -F num={config.project.number}
```

### Validation jq patterns

```bash
# R1: In Progress without Assignee (K-level error)
jq '.data.organization.projectV2.items.nodes[] |
  select(
    (.fieldValues.nodes[] | select(.field.name == "Status") | .name | test("[Ii]n [Pp]rogress")) and
    (.content.assignees.nodes | length == 0)
  ) | {issue: .content.number, title: .content.title, repo: .content.repository.name}'

# R2: In Review without Assignee (K-level error)
# Same pattern, test("[Ii]n [Rr]eview")

# R3: Blocked + has Assignee (W-level warning)
jq '.data.organization.projectV2.items.nodes[] |
  select(
    (.fieldValues.nodes[] | select(.field.name == "Blocked") | .name | test("[Yy]es|Waiting")) and
    (.content.assignees.nodes | length > 0)
  ) | {issue: .content.number, title: .content.title}'

# R6: Stale (14+ days no update, configurable via governance.stale_days)
jq --arg cutoff "$(date -v-14d +%Y-%m-%dT%H:%M:%SZ)" '
  .data.organization.projectV2.items.nodes[] |
  select(
    (.fieldValues.nodes[] | select(.field.name == "Status") | .name | test("[Ii]n [Pp]rogress|[Rr]eady")) and
    (.content.updatedAt < $cutoff)
  ) | {issue: .content.number, title: .content.title, last_update: .content.updatedAt}'

# R7: Done on board but issue still open on GitHub
jq '.data.organization.projectV2.items.nodes[] |
  select(
    (.fieldValues.nodes[] | select(.field.name == "Status") | .name | test("[Dd]one")) and
    (.content.state == "OPEN")
  ) | {issue: .content.number, title: .content.title}'
```

## Filter Syntax (gh project queries)

```bash
# List active items (exclude Done/Declined)
gh project item-list {number} --owner {org} --format json --limit 100 \
  | jq '[.items[] | select(.status | test("Done|Declined") | not)]'

# Items by assignee
gh project item-list {number} --owner {org} --format json \
  | jq '[.items[] | select(.assignees[]? | .login == "{username}")]'

# Items by status
gh project item-list {number} --owner {org} --format json \
  | jq '[.items[] | select(.status | test("In Progress"))]'

# Count by status
gh project item-list {number} --owner {org} --format json \
  | jq '[.items[] | .status] | group_by(.) | map({status: .[0], count: length})'
```

## Draft-to-Issue Conversion

Drafts are project-board items without a backing GitHub issue.

```bash
# 1. List all drafts (items without a repository)
gh project item-list {number} --owner {org} --format json \
  | jq '[.items[] | select(.content.repository == null)]'

# 2. For each draft, create a real issue
gh issue create \
  --repo {org}/{config.project.issue_repo} \
  --title "{exact_draft_title}" \
  --body "{draft_body_or_generated}"

# 3. Add the new issue to the project
gh project item-add {number} --owner {org} --url {new_issue_url}

# 4. Copy field values from draft to new issue (via GraphQL)
# Use the field update pattern above for each field

# 5. Delete the draft
gh project item-delete {number} --owner {org} --id {draft_item_id}
```

**Governance rules for conversion:**
- Always confirm with user before batch conversion
- Use `--dry-run` first to preview
- Set all mandatory fields per project type (K5)
- Verify each new issue is on the board (K5)

## Review Comment Template

When setting status to "In Review" (K3), use the template from
`workflow/projects/{slug}.yaml → review_comment_template`:

```markdown
## Review

**Status**: Ready for review
**Reason**: {describe what was done}
**Evidence**: {link to PR, commit, or documentation}
**Next steps**: {what reviewer should check}

*Set to review on {date}*
```

## Error Recovery

| Error | Cause | Fix |
|-------|-------|-----|
| "Could not resolve to a ProjectV2" | Wrong project number or org | Check workflow/projects/{slug}.yaml |
| "Resource not accessible by integration" | Token lacks project scope | `gh auth refresh -s project` |
| Field value not found | Emoji mismatch or typo | Read exact values from workflow/projects/{slug}.yaml |
| Item not found on board | Silent add failure | Re-run `gh project item-add`, then verify |
| "Cannot delete item" | Item is a real issue, not a draft | Only drafts can be deleted from boards |
