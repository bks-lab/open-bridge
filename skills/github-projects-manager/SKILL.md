---
name: github-projects-manager
description: >-
  Execute GitHub Projects V2 operations — issue creation with automatic project
  board placement, custom field updates (single-select, text, number, date),
  batch field transitions, board queries, and board-hygiene audits (coverage:
  open issues not on the board; reconciliation: board Status vs the issue's real
  state/close-reason). Reads field schemas from workflow/projects/*.yaml configs.
  Works with gh CLI + GraphQL mutations. Trigger: "create issue", "set field",
  "update billing scope", "batch update approval", "board query", "add to
  project", "set status", "classify issue", "audit board", "board hygiene",
  "reconcile board", "orphan issues", "issues not on the board", "is everything
  on the board", "declined but not closed".
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
- **Auditing board hygiene** — coverage (open issues that never made it onto
  the board) and reconciliation (board Status disagreeing with the issue's
  real state / close-reason). See *Board Hygiene* below.

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

**Connectedness is not optional.** An issue that exists but is not on the board
is invisible to everyone who works from the board. Step 2 + 3 are mandatory —
never `gh issue create` without adding to the project and confirming it landed.
The same applies when you *touch* an existing issue for this project: if it is
not on the board, add it. Periodically verify the whole set with the coverage
audit (*Board Hygiene* below) — orphaned issues are a silent failure mode.

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

## Board Hygiene (audit + reconcile)

Beyond creating and updating, this skill **verifies the board tells the truth**.
Two read-only checks, both driven by `workflow/projects/{slug}.yaml`:

- **Coverage** — open issues in the project's tracked repos that are not on the
  board (orphans). A per-issue check is `projectItems.totalCount == 0`.
- **Reconciliation** — the board Status vs the issue's real `state` /
  `stateReason`. Classify each Status into `declined | done | active` from the
  config's `status_mapping`, then:

  | Board class | Issue must be | Mismatch |
  |-------------|---------------|----------|
  | declined | `CLOSED` + `NOT_PLANNED` | OPEN → close not_planned · CLOSED/COMPLETED → **human decides** |
  | done | `CLOSED` | OPEN → finish or move board off done |
  | active | `OPEN` | CLOSED → stale board |

Run both with the tested helper (config-first — pass the Status strings from
`status_mapping`, not guesses):

```bash
scripts/board-audit.sh --owner "$ORG" --project "$NUM" \
  --declined "<status_mapping.declined>" --done "<status_mapping.done>" \
  --repos "<audit.coverage_repos, comma-joined>"
```

All four inputs come from `workflow/projects/{slug}.yaml` — `project.org`,
`project.number`, `status_mapping.declined/done`, and the optional
`audit.coverage_repos` list. Nothing board-specific is baked into the skill.

**Contradictions are never auto-fixed** — "declined but closed as completed" or
"closed but board still active" go to the human (board wrong, or issue wrong?).
Repair primitives (add-to-board, close as not_planned, change an already-closed
issue's reason without reopening, set board Status, archived-repo issues) and
the full recipes live in `references/board-audit.md`.

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
6. **Connectedness is mandatory**: every issue this skill creates or touches
   for a project must be on that project's board. Orphans are a silent failure —
   run the coverage audit periodically, not just at create time.
7. **Reconcile, don't assume**: board Status and issue state must agree
   (declined↔closed/not_planned, done↔closed, active↔open). Fix the clear
   direction; route genuine contradictions to the human — never auto-flip a
   closed issue's meaning or a customer board's Status on a guess.

## Error Recovery

| Error | Cause | Fix |
|-------|-------|-----|
| "Could not resolve to a ProjectV2" | Wrong project number or org | Check `workflow/projects/{slug}.yaml` |
| "Resource not accessible" | Token lacks project scope | `gh auth refresh -s project` |
| "Field value not found" | Emoji mismatch or typo | Re-read field-list, use exact option name |
| "Item not found" | Issue not on board yet | Run `gh project item-add` first |
| Invalid option ID | Schema drift | Re-fetch `gh project field-list` |
| "type String! was provided invalid value" | Digit-only option ID sent with `-F` (coerced to Int) | Use `-f value=$OPTION_ID` (string), not `-F` |
| Orphans miscounted / wrong | `comm` fed `sort -n` (numeric) input | Sort both lists with `LC_ALL=C sort` (lexical) before `comm` |

## Reference

- `references/graphql-patterns.md` — Full GraphQL mutation and query patterns
- `references/board-audit.md` — Coverage + reconciliation rules, repair
  primitives (close-reason change, archived-repo issues), gotchas
- `scripts/board-audit.sh` — Read-only board-hygiene checker (coverage + reconcile)
- `workflow/projects/{slug}.yaml` — Per-project field configs
- `project-advisor` skill — Governance rules and decision framework
