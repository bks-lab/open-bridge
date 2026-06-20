# /bridge — Status Dashboard

Health check: shows the current state of the Bridge setup.

**Trigger:** `/bridge`, `/status`, or `/status --html`

## Arguments

| Argument | Meaning | Default |
|----------|---------|---------|
| `--html` | Also open HTML dashboard | false |

## Workflow

### 1. Collect Data (parallel)

1. **Branch:** `git branch --show-current`
2. **Config:** Check `bridge-config.yaml` exists, read theme
3. **Ecosystem:** Check `ecosystem.yaml` exists, count projects/repos
4. **Agents:** Count files in `agents/` (excluding `_templates/`, `presets/`, and `active/`)
5. **Standing orders:** Count files in `protocols/standing-orders/` (excluding `_template.md`, `README.md`)
6. **Work:** Check work system state (log.md, board.md, active count)
7. **Repos:** For each repo in ecosystem.yaml, check if local path exists
8. **Contexts:** `ls -d contexts/*/context.yaml 2>/dev/null | wc -l`
9. **Core branch:** detect the repo's default/core branch (per `rules/session-start.md`: `gh repo view --json defaultBranchRef -q .defaultBranchRef.name` → `git symbolic-ref --short refs/remotes/origin/HEAD` → `git config init.defaultBranch` → `main`)

### 2. Render (use theme wording)

```
The Bridge — Status
══════════════════════════════════════

  Branch:        user/alice              ✓
  Config:        bridge-config.yaml      ✓
  Theme:         professional            ✓
  Ecosystem:     8 repos, 2 projects     ✓
  Contexts:      {N} (customer-a, org-platform, ...)   ✓
  Agents:        3 specialists           ✓
  Standing orders: 8 loaded              ✓
  Task Management: active (2 doing, 1 backlog)   ✓

  Repos ({present}/{total}):
  ✓ my-api             ${projects_root}/my-api
  ✓ my-frontend        ${projects_root}/my-frontend
  ✗ shared-utils       (not found locally)

── Problems ──────────────────────────────────────────────────

  ⚠ shared-utils missing locally
  ⚠ Calendar-week shift: work/log.md is week 11, today is week 12

── Actions ──────────────────────────────────────────────────

  /checkin          Start briefing
  work disable      Disable work system
  git clone ...     Clone missing repos
```

### 3. Rendering rules

- Sections without problems: compact display (no "No problems")
- Repos: list missing ones explicitly only when < 3, otherwise summary
- Work system not active: instead of details just "not active — say 'set up work'"
- Branch == detected core branch (step 9): warning "You are on the core branch ({core}). Switch to user/{name} or start onboarding."
- No `bridge-config.yaml`: "Not set up. Start onboarding?"

### 4. Problems

- No `ecosystem.yaml` → "Run /bridge in a fresh clone to start setup."
- No config → "Starting onboarding..."
- On the core branch (current == detected core, step 9) → "Create a user branch: git checkout -b user/{name}"
- Missing repos → show clone commands

### 5. HTML Output (with --html)

Generate HTML from `docs/templates/` (same pattern as the onboarding template).
Save to `/tmp/org-status.html` and open it.

Content: all sections above as a visual dashboard with color coding
(green=OK, red=problem, amber=warning).
