# Project Setup — Advisory Guide

Help users set up GitHub Projects that grow with their workflow.

## Detection

When a user first mentions GitHub Projects or when ecosystem.yaml has empty `github_projects: []`:

1. Check if any projects exist: `gh project list --owner {org}`
2. If projects exist but not in ecosystem.yaml → suggest adding them
3. If no projects → guide through creation

## Two-Structure Pattern

Most teams benefit from separating operational and technical work:

### Operational Projects (management, planning)
- For: meetings, proposals, admin tasks, client coordination
- Fields: Status, Priority, Item Type, Assignment, Due Date
- Workflow: Pending → Accepted → In Progress → Done
- Board view: group by Status, sort by Priority

### Technical Projects (code, bugs, features)
- For: code changes, bug fixes, features, deployments
- Fields: Status, Stage, Priority, Size, Item Type, Blocked, Application
- Workflow: Backlog → Ready → In Progress → In Review → Done
- Board view: group by Stage, sort by Priority + Size

**Advisory:** Suggest the pattern, let the user decide. One project is fine for small teams.

## Setup Flow

### Step 1: Create Project (if needed)

```bash
gh project create --owner {org} --title "{name}"
```

Suggest naming conventions:
- `{org-name} Operations` (operational)
- `{project-name}` (technical)

### Step 2: Configure Fields

Suggest fields based on project type. Show what each does:

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

### Step 3: Register in ecosystem.yaml

```yaml
github_projects:
  - number: {number}
    name: "{name}"
    org: {org}
    issue_repo: {org}/{repo}  # default repo for new issues
```

### Step 4: Set Up Views

Suggest useful board views:
- **Active Work** — filter: Status != Done, Status != Declined
- **My Tasks** — filter: Assignee = @me
- **Blocked** — filter: Blocked != Not Blocked
- **Sprint** — group by Iteration (if using sprints)

### Step 5: Label Taxonomy

Suggest labels for the issue repo:

```bash
gh label create "bug" --color "d73a4a" --repo {org}/{repo}
gh label create "feature" --color "0075ca" --repo {org}/{repo}
gh label create "docs" --color "0052cc" --repo {org}/{repo}
gh label create "priority:critical" --color "b60205" --repo {org}/{repo}
gh label create "priority:high" --color "d93f0b" --repo {org}/{repo}
```

## Advisory: When to Suggest Setup

- User creates their first issue → "Want me to help set up a proper board?"
- User mentions sprint/planning → "I can help configure project views"
- User has issues without a project → "These issues aren't on any board — add them?"
- During `/briefing` if github_projects is empty → brief mention, don't nag
