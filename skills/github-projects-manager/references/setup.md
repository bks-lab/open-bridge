# Project Setup: a New Board

Advisory guide for setting up a GitHub Project that grows with the workflow,
and for registering it so every skill reads the same field values. Creating the
board and its fields changes the board's schema: propose each step, get an
explicit yes, then write (`governance.md` K4).

## Detection

When the user first mentions GitHub Projects, or a board is referenced that has
no `workflow/projects/<slug>.yaml`:

1. Check which projects exist: `gh project list --owner {org} --limit 100`
2. Projects exist but have no registry file: suggest registering them (Step 3)
3. No projects: guide through creation

## Two-Structure Pattern

Most teams benefit from separating operational and technical work:

### Operational projects (management, planning)
- For: meetings, proposals, admin tasks, client coordination
- Fields: Status, Priority, Item Type, Assignment, Due Date
- Workflow: Pending, Accepted, In Progress, Done
- Board view: group by Status, sort by Priority

### Technical projects (code, bugs, features)
- For: code changes, bug fixes, features, deployments
- Fields: Status, Stage, Priority, Size, Item Type, Blocked, Application
- Workflow: Backlog, Ready, In Progress, In Review, Done
- Board view: group by Stage, sort by Priority and Size

**Advisory:** suggest the pattern, let the user decide. One project is fine for
small teams.

## Setup Flow

### Step 1: Create the project (if needed)

```bash
gh project create --owner {org} --title "{name}"
```

Naming suggestions:
- `{org-name} Operations` (operational)
- `{project-name}` (technical)

### Step 2: Configure fields

Suggest fields based on the project type and show what each does. Fields are
created with `createProjectV2Field` (`graphql-patterns.md` § Field Schema
Operations); the `gh project` CLI does not create single-select options.

**Essential (both types):**

| Field | Type | Values | Why |
|-------|------|--------|-----|
| Status | Single Select | New, In Progress, In Review, Done, Declined | Track state |
| Priority | Single Select | Critical, High, Medium, Low, Backlog | Triage quickly |
| Item Type | Single Select | Bug, Feature, Task, Docs, Spike | Categorize work |

**Technical projects add:**

| Field | Type | Values | Why |
|-------|------|--------|-----|
| Stage | Single Select | Backlog, Ready, In Progress, In Review, Done | Dev workflow |
| Size | Single Select | XS (1h), S (2-4h), M (1d), L (2-3d), XL (1w+) | Estimate effort |
| Blocked | Single Select | Not Blocked, Waiting on External, Waiting on Internal | Flag blockers |

**Emoji prefixes** make boards scannable:
```
🆕 New  🏗 In Progress  👀 In Review  ✅ Done  ❌ Declined
🔴 Critical  🟠 High  🟡 Medium  🟢 Low  ⚪ Backlog
🐛 Bug  ✨ Feature  📋 Task  📝 Docs  🔬 Spike
```

Whatever the user picks, the exact option strings (emoji included) go into the
registry file in Step 3. Every later write reads them from there.

### Step 3: Register the board in `workflow/projects/<slug>.yaml`

1. Copy `workflow/projects/_template.yaml` to `workflow/projects/<slug>.yaml`.
2. Fill `identity`, `project` (`org`, `number`, `issue_repo`), `fields` with the
   exact option strings from the live board, `state_map`, and `governance`
   (`level`, `rules`, `review_states`, `done_states`).
3. Take the field values from the board, not from memory:
   ```bash
   gh project field-list {number} --owner {org} --limit 100 --format json
   ```
4. Validate:
   ```bash
   check-jsonschema --schemafile workflow/projects/_schema.yaml \
                    workflow/projects/<slug>.yaml
   ```

Full field reference: `workflow/projects/README.md`.

### Step 4: Set up views

Suggest useful board views:
- **Active Work**: filter Status is not Done and not Declined
- **My Tasks**: filter Assignee = @me
- **Blocked**: filter Blocked is not "Not Blocked"
- **Sprint**: group by Iteration (if using sprints)

### Step 5: Label taxonomy

Suggest labels for the issue repo:

```bash
gh label create "bug" --color "d73a4a" --repo {org}/{repo}
gh label create "feature" --color "0075ca" --repo {org}/{repo}
gh label create "docs" --color "0052cc" --repo {org}/{repo}
gh label create "priority:critical" --color "b60205" --repo {org}/{repo}
gh label create "priority:high" --color "d93f0b" --repo {org}/{repo}
```

## When to suggest setup

- The user creates their first issue: "Want me to help set up a proper board?"
- The user mentions sprint or planning: "I can help configure project views."
- Issues exist that are on no board: "These issues aren't on any board. Add them?"
- During `/briefing` when no `workflow/projects/*.yaml` exists: brief mention, don't nag.
