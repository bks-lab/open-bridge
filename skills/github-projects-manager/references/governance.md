# Governance Rules and Board Health

Portable rules for managing project boards. They sit on top of the execution
patterns in `SKILL.md`: the execution layer says *how* to write, this file says
*when a write is allowed* and *what a healthy board looks like*. The rules are
tracker-agnostic; the commands shown are for GitHub Projects V2.

Per-board configuration lives in `workflow/projects/{slug}.yaml` under
`governance:` (`level`, `rules`, `review_states`, `done_states`,
`review_comment_template`). Read it before applying anything below. The
config wins over the defaults here.

## Rule Hierarchy

| Level | Meaning | Enforcement |
|-------|---------|-------------|
| **K** (Critical) | Never break: data loss or workflow corruption | Block action, explain why |
| **W** (Workflow) | Standard process: skip only with explicit reason | Warn, proceed if user insists |
| **B** (Best Practice) | Recommended: improves quality over time | Suggest, don't block |

## Governance Levels

`governance.level` in the project config decides how hard each tier bites:

| Level | K rules | W rules | B rules |
|-------|---------|---------|---------|
| `strict` | Enforced | Enforced | Suggested |
| `standard` (default) | Enforced | Suggested | Optional |
| `relaxed` | Enforced | Informational | Informational |

K rules are enforced at every level. The level only moves W and B.

## Named rules in `governance.rules`

The config lists rules by name. Known names and the tier they belong to:

| Name | Tier | Meaning |
|------|------|---------|
| `done_requires_review` | K | Pass through a `review_states` value before any `done_states` value |
| `review_needs_comment` | K | Moving into review needs a comment, built from `review_comment_template` |
| `done_only_by_user` | K | Only a human sets a done state |
| `never_delete` | K | Use the declined state, never delete an issue |
| `assignee_on_in_progress` | W | An item in progress has an assignee |
| `comment_on_status_change` | W | Comment on every status transition |

An unknown name is not an error: treat it as a W rule and say so.

## Critical Rules (K)

**K1: Never close issues directly**
Always move to the review state first. Only the user sets "Done".
Why: prevents premature closure, ensures human verification.

**K2: Never delete issues**
Use the declined state instead. History matters.
Why: audit trail, context for future decisions.

**K3: Mandatory comment on status change to review**
Explain what was done and why it is ready for review. Use the
`review_comment_template` from the project config when there is one (see
*Review comment* below).
Why: the reviewer needs context without reading the full thread.

**K4: Board schema changes only with an explicit yes**
Creating a field, deleting one, or editing the options of a single-select
changes the board's schema. That is the human's call: propose it, get an
explicit yes, then write, and update `workflow/projects/{slug}.yaml` in the
same change. When you do write, follow `SKILL.md` § Field Schema Operations:
`updateProjectV2Field` with `singleSelectOptions` **replaces the entire option
list**, so fetch the live options first, send the full list back with every
existing `id`, and rename by ID, never by delete-and-recreate.
Why: an option left out of the list is deleted, and every item that held it
silently loses its value.

**K5: Always verify after adding to project**
After `gh project item-add`, confirm the item is actually on the board.
Read it off the issue (`repository.issue.projectItems`), not from a
default-limit `item-list`, which truncates silently.
Why: silent failures happen (wrong project number, permissions, truncation).

## Workflow Rules (W)

**W1: Set assignee when starting work**
In progress without an assignee is an inconsistent state.

**W2: Remove assignee for external blockers**
If blocked by an external party, clear the assignee and set the blocked state.
Why: keeps "my tasks" views accurate.

**W3: Link related issues**
Cross-reference related issues in comments or body.
Why: context travels with the issue.

**W4: One issue per change**
Don't bundle unrelated work in one issue.
Why: clean tracking, clear scope.

**W5: Issues in the right repo**
Code bugs go to the code repo, docs to the docs repo, process to the operations
repo.
Why: issues stay close to the code they describe.

## Best Practices (B)

**B1: Add a size estimate.** Even rough (S/M/L) helps with planning.

**B2: Use labels consistently.** Same label set across repos in one project.

**B3: Triage weekly.** During `/briefing` or `/archive`, review stale items.

**B4: Close Done items monthly.** Don't let Done items accumulate.

**B5: Draft to issue conversion.** Use drafts for ideas, convert them to real
issues once scoped (recipe below).

## Board Health Validation (R1 to R7)

Board health has two halves, and they check different things:

| Check | Question | Tool |
|-------|----------|------|
| Hygiene | Is every open issue on the board, and does the board Status agree with the issue's real state? | `scripts/board-audit.sh` (coverage + reconciliation, see `board-audit.md`) |
| Health | Are the items on the board in a consistent state (assignee, staleness)? | R1 to R7 below |

Run both periodically (during `/briefing` or on request). R7 overlaps with the
reconciliation half of `board-audit.sh`; when the script runs, take R7 from its
report instead of repeating it.

| Rule | Check | Severity |
|------|-------|----------|
| R1 | In progress without assignee | K (error) |
| R2 | In review without assignee | K (error) |
| R3 | Blocked and has an assignee (contradiction) | W (warn) |
| R4 | Active without assignee and not blocked | W (warn) |
| R5 | New/backlog and has an assignee | B (info: premature?) |
| R6 | Stale: no update in 14+ days while active | W (warn) |
| R7 | Done on the board but issue still open | B (info: close?) |

Take the status strings from the config (`status_mapping`, `governance.*_states`),
never from the regexes below, which are fallbacks for a board without one.

### Query

Use the paginated board query from `graphql-patterns.md` § Board Query. Loop on
`pageInfo.hasNextPage` and merge the pages into one `items` array before
running the checks, or R1 to R7 report on the first 100 items only. The
patterns below assume the merged array in `items.json`.

```bash
# R1: in progress without assignee (K)
jq '.[] | select(
    (.fieldValues.nodes[] | select(.field.name == "Status") | .name | test("[Ii]n [Pp]rogress")) and
    (.content.assignees.nodes | length == 0)
  ) | {issue: .content.number, title: .content.title, repo: .content.repository.name}' items.json

# R2: in review without assignee (K): same pattern, test("[Ii]n [Rr]eview")

# R3: blocked and has an assignee (W)
jq '.[] | select(
    (.fieldValues.nodes[] | select(.field.name == "Blocked") | .name | test("[Yy]es|Waiting")) and
    (.content.assignees.nodes | length > 0)
  ) | {issue: .content.number, title: .content.title}' items.json

# R6: stale (14+ days without update)
jq --arg cutoff "$(date -u -v-14d +%Y-%m-%dT%H:%M:%SZ)" '.[] | select(
    (.fieldValues.nodes[] | select(.field.name == "Status") | .name | test("[Ii]n [Pp]rogress|[Rr]eady")) and
    (.content.updatedAt < $cutoff)
  ) | {issue: .content.number, title: .content.title, last_update: .content.updatedAt}' items.json

# R7: done on the board but issue still open (B)
jq '.[] | select(
    (.fieldValues.nodes[] | select(.field.name == "Status") | .name | test("[Dd]one")) and
    (.content.state == "OPEN")
  ) | {issue: .content.number, title: .content.title}' items.json
```

`date -v-14d` is BSD/macOS; on GNU use `date -u -d '14 days ago' +%Y-%m-%dT%H:%M:%SZ`.

For a quick look without GraphQL, `gh project item-list` works too, but only
with an explicit `--limit` above the board size (it defaults to 30 and
truncates silently):

```bash
gh project item-list {number} --owner {org} --format json --limit 1000 \
  | jq '[.items[] | .status] | group_by(.) | map({status: .[0], count: length})'
```

## Review comment

When moving an item into a review state (K3), post a comment built from
`governance.review_comment_template` in the project config. Without a template,
use this default:

```markdown
## Review

**Status**: Ready for review
**Reason**: {describe what was done}
**Evidence**: {link to PR, commit, or documentation}
**Next steps**: {what the reviewer should check}

*Set to review on {date}*
```

```bash
gh issue comment {n} --repo {org}/{repo} --body-file review-comment.md
```

Then set the board Status to the review state and verify both by readback.

## Draft to issue conversion

Drafts are board items without a backing issue. Converting one keeps its field
values only if you copy them yourself; `item-delete` on the draft throws them
away.

1. **List the drafts** (explicit `--limit`, see above):
   ```bash
   gh project item-list {number} --owner {org} --format json --limit 1000 \
     | jq '[.items[] | select(.content.type == "DraftIssue")]'
   ```
2. **Record each draft's field values** before touching it (title, body,
   Status, Priority, and every other set field). The draft's values are the
   source; nothing else remembers them.
3. **Create the real issue** in `project.issue_repo` with the exact draft title
   and body, then `gh project item-add` it. Do not parse the create command's
   output for the URL; look the issue up afterwards (see `SKILL.md` § Known traps).
4. **Copy the recorded field values** onto the new item, one
   `gh project item-edit` per field, and verify by readback.
5. **Delete the draft** only after step 4 verified:
   `gh project item-delete {number} --owner {org} --id {draft_item_id}`
   (GraphQL variant: `graphql-patterns.md` § Delete Draft Item).

Conversion rules:
- Confirm with the user before a batch conversion, and show the list first.
- Set every mandatory field for the project type, not only the copied ones.
- Verify each new issue is on the board (K5).

## Adapting Rules to Your Workflow

These rules are starting points. Customize them per team:

- **Solo developer:** K1 and K2 still matter. W1 matters less.
- **Small team (2 to 5):** all rules apply. W2 especially helps visibility.
- **Client projects:** add W rules for external communication.
- **Open source:** add B rules for contributor experience.

Store customized rules in the project config (`governance.rules`) or, for rules
that span boards, in a standing order under `protocols/standing-orders/user/`.
