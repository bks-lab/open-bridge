---
name: github-projects-manager
description: >-
  The only write path to GitHub Projects V2, plus its governance: issue creation with board placement, field updates, batch transitions, board queries, audits, health checks, new-board setup. Reads schemas and rules from workflow/projects/*.yaml. Trigger: "create issue", "set field", "board query", "audit board", "board health", "project setup", "is everything on the board".
metadata:
  scope: core
  tools: [Bash, Read, Glob, Grep]
---

# GitHub Projects Manager

Execution and governance layer for GitHub Projects V2. This skill runs the
actual CLI and GraphQL commands, and it decides when a write is allowed: the
K/W/B governance rules, the board health checks (R1 to R7) and the setup of a
new board live in `references/governance.md` and `references/setup.md`.

## Decision tree

```
User intent?
├─ "Create issue" / "Track this"   → Issue Creation (below) + governance.md K rules
├─ "Set field" / "Set status"      → Field Updates (below); into review → governance.md § Review comment
├─ "Show board" / "What's active?" → Board query (graphql-patterns.md § Board Query)
├─ "Audit board" / "Reconcile"     → Board Hygiene (below), scripts/board-audit.sh
├─ "Board health" / "Governance"   → references/governance.md (R1 to R7)
├─ "Convert drafts to issues"      → references/governance.md § Draft to issue conversion
├─ "Set up a project" / new board  → references/setup.md
└─ Change fields or options        → Field Schema Operations (below), human gate
```

## When to use

- Creating issues and adding them to project boards
- Setting or updating custom project fields (Status, Priority, Billing
  Scope, Approval, Root Cause, Person Days, etc.)
- Batch field transitions (e.g. "set Approval to Submitted on 16 items")
- Querying board state (items by status, field counts, stale items)
- Converting drafts to issues, keeping their field values
- Checking governance and board health (R1 to R7) and setting up new boards
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

When the request comes from conversation rather than from a calling skill
that already fixed the values, propose first and create on a yes: title, target
repo (`project.issue_repo`), project, and the field values taken from the
config (`fields.status.default`, a suggested Priority and Type). The governance
level and rules in the config's `governance:` block decide what is mandatory
(`references/governance.md`).

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
This is simpler than GraphQL and works for single-select, text, number and
date fields. Two forms — prefer the **by-name** form for one-off edits, the
**by-ID** form for batches:

```bash
# By name — no ID lookups at all. Field name and (for single-select) the exact
# option name, both straight out of workflow/projects/{slug}.yaml.
gh project item-edit $NUM --owner "$ORG" \
  --url https://github.com/{org}/{repo}/issues/{n} \
  --field "Priority" --value "🟡 Medium"

# Remove a value (leave the field empty) — there is no "empty" option to select
gh project item-edit $NUM --owner "$ORG" --url "$ISSUE_URL" \
  --field "Priority" --clear
```

`--url` is the **issue** URL, not the project URL; `--owner` selects the
project, so the two may have different owners (that is the normal case on a
repo-spanning board).

```bash
# By ID — worth the three lookups only when you edit many items in one run
# and cache the IDs.
gh project item-edit --project-id "$PROJECT_ID" \
  --id "$ITEM_ID" \
  --field-id "$FIELD_ID" \
  --single-select-option-id "$OPTION_ID"

gh project item-edit --project-id "$PROJECT_ID" \
  --id "$ITEM_ID" --field-id "$FIELD_ID" --number 0.5

gh project item-edit --project-id "$PROJECT_ID" \
  --id "$ITEM_ID" --field-id "$FIELD_ID" --text "E16"

gh project item-edit --project-id "$PROJECT_ID" \
  --id "$ITEM_ID" --field-id "$FIELD_ID" --date "2026-08-07"
```

For a non-draft issue, **one field value per invocation** — three fields means
three calls.

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
gh project field-list $NUM --owner $ORG --limit 100 --format json \
  | jq -r '.fields[] | "\(.name) | \(.id) | \(.options // [] | map("\(.name)=\(.id)") | join("; "))"'
```

> **`--limit` is not optional.** `gh project field-list` and `gh project
> item-list` both default to **30** and truncate **silently** — no warning, no
> non-zero exit, just a short list that looks complete. A board with 33 fields
> returns 30 of them; a board with 377 items returns 30. Every audit, every
> coverage diff and every "the field does not exist" conclusion drawn from a
> default-limit call is wrong on any board past 30. Always pass `--limit`, and
> cross-check the real size against `items { totalCount }` / `fields
> { totalCount }` in GraphQL before trusting a count.

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

## Field Schema Operations (changing the board itself)

Everything above writes *values*. Adding a field, or renaming/adding/removing
the options of a single-select, changes the board's **schema** — a different
class of operation with a different blast radius, and one the `gh project` CLI
does not cover at all. GraphQL only: `createProjectV2Field`,
`updateProjectV2Field`, `deleteProjectV2Field`. Mutations and a worked
rename recipe: `references/graphql-patterns.md` § Field Schema Operations.

Three rules, all of them learned the expensive way:

1. **`singleSelectOptions` replaces the entire option list.** The input is not a
   patch. An option you pass **with** its existing `id` is renamed/recolored in
   place and every item keeping that value follows along. An option you pass
   **without** an `id` is created. An option you simply **leave out is deleted**,
   and every item that held it silently loses its value. Always fetch the live
   options first and send the full list back.
2. **Rename by ID, never by delete-and-recreate.** Renaming through the IDs is
   lossless: item values, saved views and the board's built-in workflows all
   reference the option ID, not the name. Delete-and-recreate looks identical in
   the UI and throws the data away.
3. **A schema change is the human's call, not yours.** Field values are routine;
   the shape of someone's board is not. Propose, get an explicit yes, then write —
   especially when the board belongs to someone else. Afterwards, update
   `workflow/projects/{slug}.yaml` in the same breath: `fields`, the `*_mapping`
   blocks, `state_map`, `governance.review_states` / `done_states`, and
   `ids.option_ids`. A registry that still describes the old shape is worse than
   no registry, because it reads as verified.

Verify a schema change by re-reading the items, not the field: the question is
never "did the option get renamed" (the mutation response already says so) but
"did every item keep its value".

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

Hygiene checks the board against the issues. **Health** checks the items
against each other and the governance rules (in progress without assignee,
blocked with assignee, stale items): R1 to R7 in `references/governance.md`.
Run both for a full board review.

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
8. **Never trust a default limit**: pass `--limit` on every `field-list` /
   `item-list` call and paginate every GraphQL `items` / `fields` connection. A
   truncated read is indistinguishable from a complete one.
9. **Schema changes are gated and paired**: creating a field or editing its
   options needs an explicit human yes, and the matching
   `workflow/projects/{slug}.yaml` update in the same change.

## Known traps

Four failure modes that all produce *plausible* output, which is why they survive
review. Each one was paid for once. They live with the tool rather than with any
one caller, because every path that writes to a board hits the same `gh`.

- **Never parse the output of a writing `gh` command.** A hook may append a log
  reminder to **stdout** after any `gh` call with remote effect, so
  `URL=$(gh issue create … | tail -1)` yields the hook line instead of the URL. One
  script reported four failures this way while all four issues had been created;
  a retry would have produced four duplicates. Verify success **against the target
  state** (`gh issue list`, `projectItems` on the issue), never against the return
  value of the writing command.
- **`gh project item-list --limit` truncates silently.** At `--limit 100` three of
  four freshly added items were missing; at `--limit 200` all were there. A missing
  item is therefore **not** proof of a failed `item-add`. The reliable read is the
  item ID straight off the issue: `repository.issue.projectItems` via GraphQL.
- **`item-add` sets no Status.** After adding, set Status, Item Type and Priority
  explicitly and confirm by readback, or the item sits on the board without a column.
- **`--project` on `gh issue create` is unreliable.** Create first, then attach:
  `gh issue create`, then `gh project item-add <N> --owner <org> --url <issue-url>`.

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
| Field or item "missing" that exists in the UI | `field-list` / `item-list` truncated at the default limit of 30 | Re-run with `--limit`, confirm against `totalCount` |
| Items lost their single-select value after a field edit | `updateProjectV2Field` sent a partial option list — omitted options were deleted | Fetch live options first, resend the full list with existing `id`s |

## Reference

- `references/graphql-patterns.md` — Full GraphQL mutation and query patterns
- `references/board-audit.md` — Coverage + reconciliation rules, repair
  primitives (close-reason change, archived-repo issues), gotchas
- `scripts/board-audit.sh` — Read-only board-hygiene checker (coverage + reconcile)
- `workflow/projects/{slug}.yaml` — Per-project field configs
- `references/governance.md`: K/W/B rules, governance levels, board health
  (R1 to R7), review comment, draft to issue conversion
- `references/setup.md`: new board, fields, registry entry, views, labels
