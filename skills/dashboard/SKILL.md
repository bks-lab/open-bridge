---
name: dashboard
description: >-
  Project dashboard showing GitHub/ADO tasks, git activity, and deployment
  status. Auto-detects project context from CWD, ecosystem.yaml, and
  workflow/projects/*.yaml.
  Trigger: "/dashboard", "/dashboard --all", "/dashboard --html",
  "show dashboard", "show tasks", "what is up", "project status".
metadata:
  scope: core
---

# Dashboard

Render a project dashboard in the terminal showing tasks, recent git activity,
and deployment status. Reads project configuration from the **Project Registry**
(`workflow/projects/*.yaml`) and repo metadata from `ecosystem.yaml`.

## Decision Tree

```
User wants to...
├── Dashboard for current project    → /dashboard (auto-detect)
├── Dashboard for all projects       → /dashboard --all
├── Dashboard with HTML view         → /dashboard --html
├── Specific project dashboard       → /dashboard {name}
└── Questions about project status   → Answer from data, don't render full dashboard
```

## Commands

| Command | Behavior |
|---------|----------|
| `/dashboard` | Auto-detect project, terminal output |
| `/dashboard --all` | All projects, global view |
| `/dashboard --html` | Terminal + HTML in iTerm2 split-pane |

## Workflow

1. **Detect project** — Read `references/data-sources.md` for the 4-phase
   auto-detection algorithm (CLAUDE.md section → git remote → CWD → --all)
2. **Fetch data** — Read `references/data-sources.md` § Data Fetching for the
   5 parallel data sources (tasks, commits, sparklines, health, issues)
3. **Render terminal** — Read `references/terminal-rendering.md` for layout rules
4. **Render HTML** (if --html) — Read `references/html-template.md` for specs

## Terminal Layout (quick reference)

### Single-Project

```
{project.name} Dashboard

╭──────────────────────────────────────────────────────────────────────────╮
│  {Focus: last In-Progress task title or last commit message}             │
│  Last commit {relative_time} on {branch}                                 │
╰──────────────────────────────────────────────────────────────────────────╯

  {repo}    {commit_msg_short}                              {Xh} ago

── Tasks ({n} open) ────────────────────────────────────────────────────────

  #{id}   {title_max40}                      {status}   {assignee}
       + {n} in Backlog

── Git ────────────────────────────────────────────────────────────────────

  {repo_short}   {branch}   {sparkline}   {n} commits (7d)

── Deployment ─────────────────────────────────────────────────────────────

  {app_name}   {status}   build {date}
```

### Global (--all)

```
Dashboard (Global)

╭──────────────────────────────────────────────────────────────────────────╮
│  {n} projects active  |  {n} open Tasks  |  {n} In Progress              │
╰──────────────────────────────────────────────────────────────────────────╯

── {Project1} ({n} open) ──────────────────────────────────────────────────

  #{id}   {title}                            {status}   {assignee}
       + {n} more
```

### Display Rules
- Max 5 tasks per project in single view, 3 in global view
- Task title: max 40 chars, truncate with `..`
- Omit Deployment section if no health_checks configured
- Omit Git section if no local repo found
- Filter out done_states from project config

## Integration with Bridge

- **/briefing** Stream B uses the same GitHub data — dashboard is the visual companion
- **Project Registry** (`workflow/projects/*.yaml`) is the single source of truth for
  field values, status mappings, and health check URLs
- **ecosystem.yaml** provides repo paths and org structure for auto-detection
