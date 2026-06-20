---
name: project-advisor
description: >-
  Governance and execution for GitHub and ADO projects — reads per-project
  configs from workflow/projects/*.yaml for field values, governance rules, and state
  mappings. Handles issue creation, field updates, board health validation.
  Trigger: "create issue", "board health", "project setup",
  "check governance", "update field", "convert drafts".
metadata:
  scope: core
---

# Project Advisor

Governance layer for project management. Reads per-project configuration
from `workflow/projects/*.yaml` to know field values, governance rules, and state
mappings. Actual execution (creating issues, updating fields) goes through
the `github-projects-manager` skill.

**This skill is cross-cutting** — applies to every repo that uses GitHub
Projects or Azure DevOps Boards, not just The Bridge.

## Project Registry

Configuration lives in `workflow/projects/*.yaml`. Each file defines one project:
- Field values (status, priority, type, size, stage, etc.)
- Governance rules (K/W/B levels, per-rule overrides)
- State mappings (project status → normalized state for trackers)
- Review comment templates

```
projects/
├── _schema.yaml              # Schema documentation
├── _template.yaml            # Blank template for new projects
├── examples/                 # Neutralized examples (CORE layer)
│   ├── operational.yaml      # Type A: management, coordination
│   ├── technical.yaml        # Type B: software development
│   ├── minimal.yaml          # Type C: workshops, experiments
│   └── ado-project.yaml      # Azure DevOps integration
└── {slug}.yaml               # Actual project configs (USER layer)
```

**When creating issues or updating fields:** always read the matching
`workflow/projects/{slug}.yaml` first. Use the field values defined there — never
hardcode emojis, status names, or priority values.

## When This Skill Activates

- User asks about project setup or structure
- User wants to validate board health or check governance
- Crew-advisor detects untracked work that should be an issue
- After issue creation (verify governance rules were followed)

## Decision Tree

```
User intent?
├─ "Set up a GitHub project"         → references/setup.md
├─ "Create issue" / "Track this"     → Issue Governance (below) + references/execution.md
├─ "Show board" / "What's active?"   → Board Overview (below)
├─ "Check board health"              → references/governance.md (R1-R7) + execution.md (jq queries)
├─ "Update issue status/fields"      → references/execution.md (CLI + GraphQL patterns)
├─ "Convert drafts to issues"        → references/execution.md (Draft-to-Issue section)
├─ "Add a new project"               → Create workflow/projects/{slug}.yaml from _template
└─ General project question           → Answer from governance.md + project config
```

## Issue Governance (guided flow)

When creating an issue (execution patterns in `references/execution.md`):

1. **Load project config**
   - Match context to `workflow/projects/*.yaml` (by project number or name)
   - Read `fields:` for valid values, `governance:` for rules
   - If no config exists: offer to create one from `_template.yaml`

2. **Determine project type** from config `project.type`:
   - `operational` → has assignment + dependency fields
   - `technical` → has stage + size fields
   - `custom` → minimal fields, check what's available

3. **Propose issue** (use field values from config):
   ```
   Issue proposal:
     Title: {derived from conversation}
     Repo: {from config project.issue_repo}
     Project: #{number} {name}
     Fields: (per config)
       Status: {config fields.status.default}
       Priority: {suggested from config values}
       Type: {suggested from config values}

   [y] Create  [e] Edit  [n] Cancel
   ```

4. **Create** via `github-projects-manager` skill

5. **Verify** — confirm issue is on the board after creation

## Board Overview

Query active items (exclude done_states from config), show grouped
by status with assignee and priority.

## Field Update Rules

Read `governance.rules` from project config. At minimum:

**K-level (Critical — from config `governance.level: strict|standard`):**
- `done_requires_review`: must go through review_states before done_states
- `review_needs_comment`: mandatory comment using `review_comment_template`
- `done_only_by_user`: only human can mark done
- `never_delete`: use Declined, never delete

**W-level (Workflow):**
- `assignee_on_in_progress`: must have assignee when in progress
- `comment_on_status_change`: comment on every transition

See `references/governance.md` for the full K/W/B rule set with
board health validation checks (R1-R7).

## Governance Levels

| Level | K rules | W rules | B rules |
|-------|---------|---------|---------|
| `strict` | Enforced | Enforced | Suggested |
| `standard` | Enforced | Suggested | Optional |
| `relaxed` | Enforced | Informational | Informational |

## Integration with Bridge

- **Trackers:** `state_map` in project config feeds into tracker normalization
- **Task Management:** When creating a work task, offer to also create an issue
- **Crew Advisor:** When untracked work detected, suggest task + issue creation
- **Promote:** After promoting CORE changes, suggest linking to issues
