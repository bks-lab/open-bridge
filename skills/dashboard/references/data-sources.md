# Dashboard Data Sources & Processing

## Auto-Detection Algorithm

Detect the active project in this order (first match wins):

### Phase 1: CLAUDE.md Dashboard Section
Read `CLAUDE.md` in CWD. Look for `## Dashboard` section with YAML:
```yaml
## Dashboard
github_project: 18
owner: my-org
```
If found, load matching `workflow/projects/*.yaml` by number. Skip remaining phases.

### Phase 2: Git Remote → Project Registry Lookup
```bash
git remote get-url origin 2>/dev/null
```
Extract `org/repo`, then match against `workflow/projects/*.yaml`:
- Check each config's `project.issue_repo`
- Check `ecosystem.yaml` for repos mapped to that project number

### Phase 3: CWD Path → ecosystem.yaml
Match CWD path against `ecosystem.yaml` repo paths:
- `local_root` + repo name patterns
- Explicit `local_path` entries
- Resolve to project number via `ecosystem.yaml → github_projects`

### Phase 4: --all Flag
Load ALL `workflow/projects/*.yaml` files. Show global view.

## Data Fetching

Read project config FIRST, then fetch data in parallel:

```bash
# 1. GitHub Project tasks (from config: project.number, project.org)
gh project item-list {config.project.number} \
  --owner {config.project.org} --format json --limit 50

# 2. Recent commits (per repo from ecosystem.yaml, if local)
git -C {repo_path} log --oneline --since="7 days ago" -10

# 3. Commit frequency for sparklines
git -C {repo_path} log --format="%ad" --date=short --since="7 days ago"

# 4. Health checks (from config: health_checks[].url, 3s timeout)
curl -s --max-time 3 {config.health_checks[].url}

# 5. Open issues (from config: project.issue_repo)
gh issue list --repo {config.project.org}/{repo} \
  --state open --json number,title,labels,assignees --limit 10
```

**Skip git commands** for repos not cloned locally.
**Health check timeouts** don't block — show "timeout" status.

## Data Processing

### Task Status Mapping
Use `state_map` from `workflow/projects/{slug}.yaml` to normalize statuses.
Strip emoji prefixes for clean display.

### Sparkline Generation
Count commits per day over last 7 days:
`▁▂▃▄▅▆▇█` (0 = `▁`, max = `█`, linear scale, 7 chars)

### Relative Time
"2h ago", "1d ago", "yesterday", "3d ago"

## Error Handling

- `gh` not authenticated → print `gh auth login` hint, git-only data
- No git repo → skip git sections, show tasks only
- No project detected → list available projects from `workflow/projects/*.yaml`
- Health check timeout → show `timeout`, don't block
- No `workflow/projects/*.yaml` found → suggest creating one from `_template.yaml`
