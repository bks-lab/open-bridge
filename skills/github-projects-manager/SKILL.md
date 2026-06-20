---
name: github-projects-manager
description: >-
  Execute GitHub Projects V2 operations — issue creation with automatic project
  board placement, custom field updates (single-select, text, number, date),
  batch field transitions, and board queries. Reads field schemas from
  workflow/projects/*.yaml configs. Works with gh CLI + GraphQL mutations.
  Trigger: "create issue", "set field", "update billing scope", "batch update
  approval", "board query", "add to project", "set status", "classify issue".
metadata:
  scope: core
  tools: [Bash, Read, Glob, Grep]
---

# GitHub Projects Manager

Execution layer for GitHub Projects V2 operations. The `project-advisor`
skill handles governance and decision-making; this skill handles the
actual CLI and GraphQL commands.

## When to use

- Creating issues and adding them to project boards
- Setting or updating custom project fields (Status, Priority, Billing
  Scope, Approval, Root Cause, Person Days, etc.)
- Batch field transitions (e.g. "set Approval to Submitted on 16 items")
- Querying board state (items by status, field counts, stale items)
- Converting drafts to issues

## Loading sequence

1. Identify the target project (from caller context, issue URL, or `#number`)
2. Read `workflow/projects/{slug}.yaml` for field values, governance rules, and
   state mappings
3. If a bound context exists (e.g. `workflow/contexts/customer-a.yaml`),
   read `project_custom_fields` for field-specific overrides and
   readonly field lists

## Issue Creation (3-step atomic)

Every issue creation follows this exact sequence — no shortcuts:

```
Step 1: gh issue create --repo {org}/{issue_repo} --title --body --label
Step 2: gh project item-add {number} --owner {org} --url {issue_url}
Step 3: Verify — confirm the item appears on the board
```

After creation, immediately classify with at minimum:
- `Status` (from project config default)
- All billing fields if the project has them (Billing Scope, Root Cause,
  Approval)

## Field Updates

### Approach: `gh project item-edit` (preferred)

For standard project fields, use the `gh project item-edit` CLI command.
This is simpler than GraphQL and works for single-select and number fields:

```bash
# Single-select field
gh project item-edit --project-id "$PROJECT_ID" \
  --id "$ITEM_ID" \
  --field-id "$FIELD_ID" \
  --single-select-option-id "$OPTION_ID"

# Number field
gh project item-edit --project-id "$PROJECT_ID" \
  --id "$ITEM_ID" \
  --field-id "$FIELD_ID" \
  --number 0.5

# Text field
gh project item-edit --project-id "$PROJECT_ID" \
  --id "$ITEM_ID" \
  --field-id "$FIELD_ID" \
  --text "E16"
```

### Resolving IDs

Before setting fields, resolve all required IDs:

```bash
# Get Project ID from item-add output, or:
PROJECT_ID=$(gh api graphql -f query='
  query($org: String!, $num: Int!) {
    organization(login: $org) {
      projectV2(number: $num) { id }
    }
  }' -f org="$ORG" -F num=$NUM \
  --jq '.data.organization.projectV2.id')

# Get all field IDs + option IDs in one call:
gh project field-list $NUM --owner $ORG --format json \
  | jq -r '.fields[] | "\(.name) | \(.id) | \(.options // [] | map("\(.name)=\(.id)") | join("; "))"'
```

Cache field IDs for the duration of a run — they don't change between
calls within the same session.

### Fallback: GraphQL mutations

For complex operations or when `gh project item-edit` fails, use the
GraphQL patterns documented in `references/graphql-patterns.md`.

## Batch Operations

For batch field updates (e.g. transitioning 16 items from
`Org Internal` to `Submitted`):

1. Resolve field + option IDs once
2. Get all item IDs for the target issues
3. Run updates in parallel (`&` + `wait`) — max 10 concurrent
4. Verify all updated items after `wait` completes
5. Report: `Updated N/M items successfully`

## Bound Context Integration

When called by a coordinator skill (e.g. `customer-a-coordinator`), the
caller provides:
- Project number and org
- Which fields to set and with which values
- A bound context path (e.g. `workflow/contexts/customer-a.yaml`)

Read `project_custom_fields` from the bound context for:
- Exact field names and valid options
- Readonly fields (DO NOT WRITE)
- Field naming conventions (e.g. English-only for CustomerA)

## Rules

1. **Config-first**: Always read `workflow/projects/{slug}.yaml` before any
   operation. Never hardcode field values, emojis, or status names.
2. **Verify after write**: Every create or update must be verified.
3. **Respect readonly fields**: If a field is in `project_fields_readonly`,
   never write to it even if the caller requests it.
4. **Atomic transitions**: Batch updates are all-or-nothing. If one
   fails, report the failure — don't silently skip.
5. **No issue closure without review**: Per governance, issues go through
   "In Review" before "Done" — never skip to Done directly.

## Error Recovery

| Error | Cause | Fix |
|-------|-------|-----|
| "Could not resolve to a ProjectV2" | Wrong project number or org | Check `workflow/projects/{slug}.yaml` |
| "Resource not accessible" | Token lacks project scope | `gh auth refresh -s project` |
| "Field value not found" | Emoji mismatch or typo | Re-read field-list, use exact option name |
| "Item not found" | Issue not on board yet | Run `gh project item-add` first |
| Invalid option ID | Schema drift | Re-fetch `gh project field-list` |

## Reference

- `references/graphql-patterns.md` — Full GraphQL mutation and query patterns
- `workflow/projects/{slug}.yaml` — Per-project field configs
- `project-advisor` skill — Governance rules and decision framework
