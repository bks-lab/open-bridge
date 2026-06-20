# Governance Rules — Project Management

Portable rules for managing GitHub Projects. Three severity levels.

## Rule Hierarchy

| Level | Meaning | Enforcement |
|-------|---------|-------------|
| **K** (Critical) | Never break — data loss or workflow corruption | Block action, explain why |
| **W** (Workflow) | Standard process — skip only with explicit reason | Warn, proceed if user insists |
| **B** (Best Practice) | Recommended — improves quality over time | Suggest, don't block |

## Critical Rules (K)

**K1: Never close issues directly**
→ Always move to "In Review" first. Only the user sets "Done".
Why: Prevents premature closure, ensures human verification.

**K2: Never delete issues**
→ Use "Declined" status instead. History matters.
Why: Audit trail, context for future decisions.

**K3: Mandatory comment on status change to "In Review"**
→ Explain what was done and why it's ready for review.
Why: Reviewer needs context without reading the full thread.

**K4: Never update project field options**
→ Don't use `updateProjectV2Field` with `singleSelectOptions` — it DESTROYS all existing values.
Why: GraphQL API replaces the entire option set, not appending. Catastrophic data loss.

**K5: Always verify after adding to project**
→ After `gh project item-add`, confirm item is actually on the board.
Why: Silent failures happen (wrong project number, permissions, etc.).

## Workflow Rules (W)

**W1: Set assignee when starting work**
→ In Progress without Assignee = inconsistent state.

**W2: Remove assignee for external blockers**
→ If blocked by external party, clear assignee + set Blocked status.
Why: Makes "my tasks" view accurate.

**W3: Link related issues**
→ Cross-reference related issues in comments or body.
Why: Context travels with the issue.

**W4: One issue per change**
→ Don't bundle unrelated work in one issue.
Why: Clean tracking, clear scope.

**W5: Issues in the right repo**
→ Code bugs → code repo. Docs → docs repo. Process → operations repo.
Why: Issues close to the code they describe.

## Best Practices (B)

**B1: Add size estimate**
→ Even rough (S/M/L) helps with sprint planning.

**B2: Use labels consistently**
→ Same label set across repos in one project.

**B3: Triage weekly**
→ During `/briefing` or `/archive`, review stale items.

**B4: Close Done items monthly**
→ Don't let Done items accumulate. Archive or close.

**B5: Draft → Issue conversion**
→ Use drafts for ideas, convert to real issues when scoped.

## Board Health Validation

Run periodically (during `/briefing` or on request):

| Rule | Check | Severity |
|------|-------|----------|
| R1 | In Progress without Assignee | K (error) |
| R2 | In Review without Assignee | K (error) |
| R3 | Blocked + has Assignee (contradiction) | W (warn) |
| R4 | Active without Assignee + not Blocked | W (warn) |
| R5 | New/Backlog + has Assignee | B (info — premature?) |
| R6 | Stale: no update in 14+ days while Active | W (warn) |
| R7 | Done but issue still open on GitHub | B (info — close?) |

```bash
# Example health check
gh project item-list {number} --owner {org} --format json | jq '
  .items[] |
  select(.status == "🏗 In Progress" and (.assignees | length == 0)) |
  {title: .content.title, url: .content.url, status: .status}
'
```

## Adapting Rules to Your Workflow

These rules are starting points. Customize based on your team:

- **Solo developer:** K1-K2 still matter. W1 less relevant (you're the only assignee).
- **Small team (2-5):** All rules apply. W2 especially important for visibility.
- **Client projects:** Add W rules for external communication (update client on status changes).
- **Open source:** Add B rules for contributor experience (issue templates, first-timer labels).

Store your customized rules in `protocols/standing-orders/project-governance.md`.
