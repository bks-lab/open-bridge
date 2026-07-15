# HTML Dashboard Template — Specification

## Overview

The dashboard is generated as a self-contained HTML file and displayed via an iTerm2 split pane.

**Template**: `skills/dashboard/assets/dashboard-template.html`
**Output**: `{cwd}/.dashboard-view.html`

## Placeholders

| Placeholder | Description | Example |
|---|---|---|
| `{{TITLE}}` | Dashboard title | `Acme-Lab Dashboard` or `CustomerA Dashboard` |
| `{{TIMESTAMP}}` | Generation timestamp | `2026-02-23 14:30` |
| `{{SUMMARY_HTML}}` | Summary statistics | See below |
| `{{PROJECTS_HTML}}` | All project cards | See below |

## Data format

The fetch script returns JSON, which is passed between data fetching and HTML generation.

### Project JSON schema

```json
{
  "generated_at": "2026-02-23T14:30:00",
  "projects": [
    {
      "name": "CustomerA",
      "tasks": {
        "total_open": 8,
        "in_progress": 2,
        "items": [
          {
            "id": "#107",
            "title": "Outbound Credit Note Support",
            "status": "in-progress",
            "assignee": "alice"
          }
        ]
      },
      "repos": [
        {
          "short_name": "outbound-op",
          "branch": "development",
          "sparkline_values": [1, 3, 5, 7, 5, 3, 2],
          "commit_count": 12,
          "last_commit_time": "2026-02-22T16:30:00"
        }
      ],
      "deployments": [
        {
          "name": "Inbound PRE",
          "status": "ok",
          "time": "2026-02-22T10:00:00"
        }
      ]
    }
  ]
}
```

### Status values

| Task Status | `data-status` | Color |
|---|---|---|
| In Progress | `in-progress` | `#4fc3f7` (blue) |
| Ready / New | `ready`, `new` | `#81c784` (green) |
| In Review | `review` | `#ffb74d` (amber) |
| Backlog | `backlog` | `#9e9e9e` (grey) |
| Blocked | `blocked` | `#ef5350` (red) |

| Deploy Status | CSS class | Color |
|---|---|---|
| OK | `deploy-ok` | `#81c784` (green) |
| Error | `deploy-error` | `#ef5350` (red, pulsing) |
| Pending | `deploy-pending` | `#ffb74d` (amber) |

### GitHub Projects status mapping

GitHub Projects V2 status fields map to `data-status`:

```
"In progress"       → in-progress
"Ready"             → ready
"New"               → new
"In review"         → review
"Backlog"           → backlog
"Blocked"           → blocked
"Done"              → (not displayed)
```

## HTML generation

### Summary Bar

```html
<div class="summary-stat">
  <span class="summary-value">{total_open}</span>
  <span class="summary-label">Open</span>
</div>
<div class="summary-divider"></div>
<div class="summary-stat">
  <span class="summary-value">{total_in_progress}</span>
  <span class="summary-label">In Progress</span>
</div>
<div class="summary-divider"></div>
<div class="summary-stat">
  <span class="summary-value">{total_projects}</span>
  <span class="summary-label">Projects</span>
</div>
```

### Project card

Per project the following HTML block is generated:

```html
<section class="project-card" data-project="{name_lowercase}">
  <!-- Header -->
  <div class="card-header">
    <h2>{name}</h2>
    <div class="card-stats">
      <span class="stat-highlight">{in_progress}</span> active |
      {total_open} open
    </div>
  </div>

  <!-- Tasks (max 5 visible, rest behind the backlog toggle) -->
  <div class="tasks">
    <!-- Active tasks (in-progress, review, ready) -->
    <div class="task" data-status="{status}">
      <span class="task-id">{id}</span>
      <span class="task-title">{title}</span>
      <span class="task-status">{status_label}</span>
      <span class="task-assignee">{assignee}</span>
    </div>

    <!-- If > 5 tasks: backlog toggle -->
    <button class="backlog-toggle">▾ + {N} more</button>
    <div class="backlog-tasks">
      <!-- Backlog / low-priority tasks here -->
    </div>
  </div>

  <!-- Git Activity -->
  <div class="card-section">
    <div class="section-label">Git Activity</div>
    <div class="git-activity">
      <div class="repo-sparkline">
        <span class="repo-name">{short_name}</span>
        <span class="branch">{branch}</span>
        <svg class="sparkline" data-values="{comma_separated_values}"></svg>
        <span class="commit-count">{N} commits</span>
      </div>
    </div>
  </div>

  <!-- Deployments (only when present) -->
  <div class="card-section">
    <div class="section-label">Deployments</div>
    <div class="deployments">
      <div class="deploy-item deploy-{status}">
        <span class="deploy-name">{name}</span>
        <span class="deploy-status">{STATUS}</span>
        <span class="deploy-time" data-timestamp="{iso_time}">{time}</span>
      </div>
    </div>
  </div>
</section>
```

### Task sorting

Tasks are displayed in the following order:
1. `in-progress` (actively worked on)
2. `review` (under review)
3. `ready` / `new` (ready)
4. `blocked` (blocked)
5. `backlog` (hidden in the toggle)

### Sparkline data

The `data-values` contain commit counts of the last 7 days (Mon-Sun).
JavaScript in the template renders SVG bars from them automatically.

## iTerm2 integration

### Workflow

```
Step 1: generate HTML
  - Read the template: skills/dashboard/assets/dashboard-template.html
  - Replace placeholders with the generated data
  - Write the file: {cwd}/.dashboard-view.html

Step 2: update the Dynamic Profile URL
  - Profile "Web Browser" must exist (setup in CLAUDE.md)
  - The URL is set via the profile parameter "Initial URL"

Step 3: open the iTerm2 split pane
  /tmp/iterm2-env/bin/python3 -c "
  import iterm2, json, os

  PROFILE_DIR = os.path.expanduser(
      '~/Library/Application Support/iTerm2/DynamicProfiles')
  PROFILE_FILE = os.path.join(PROFILE_DIR, 'web-browser.json')

  async def main(connection):
      # Set the URL in the dynamic profile
      url = 'file:///{cwd}/.dashboard-view.html'
      profile_data = {
          'Profiles': [{
              'Name': 'Web Browser',
              'Guid': 'WEB-BROWSER-PROFILE-001',
              'Custom Command': 'Browser',
              'Initial URL': url,
              'Dynamic Profile Parent Name': 'Default'
          }]
      }
      with open(PROFILE_FILE, 'w') as f:
          json.dump(profile_data, f, indent=2)

      # Open the split pane
      app = await iterm2.async_get_app(connection)
      session = app.current_terminal_window.current_tab.current_session
      await session.async_split_pane(vertical=True, profile='Web Browser')

  iterm2.run_until_complete(main)
  "
```

### Prerequisites

1. **iTerm2 Browser Plugin**: `/Applications/iTermBrowserPlugin.app`
2. **Python venv**: `/tmp/iterm2-env/` with `pip install iterm2`
3. **Dynamic Profile**: created/updated automatically

### Refresh

On a subsequent `/dashboard` invocation:
1. The HTML is regenerated and overwritten
2. The browser pane is NOT reopened (check if already open)
3. If the pane is open: the page refreshes on next focus

## Scope modes

### Global (default)
- Shows all projects from the CLAUDE.md dashboard config
- Title: `Acme-Lab Dashboard`

### Project-specific
- Auto-detected when CWD is inside a configured repo
- Shows only the relevant project, with more detail
- Title: `{Project name} Dashboard`

### Override via argument
```
/dashboard                  → Global (all projects)
/dashboard customer-a        → CustomerA only
/dashboard --global         → Explicit global
```
