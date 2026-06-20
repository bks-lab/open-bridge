# Commit Analysis — Time Estimation & Activity Categorization

Used by `/briefing` for git activity breakdown and optionally for time tracking.
Extends the basic 7-day sparkline with work-type classification and session-based
time estimation.

## When to Use

- `/briefing` git activity stream (always: sparklines + commit counts)
- `/briefing --commits YYYY-MM-DD` (detailed: time estimation + activity breakdown)
- Time tracking export (clockify, reports)

## Session-Based Time Estimation

### Algorithm

Group commits into **sessions** using a 2-hour gap threshold:

```
Commits:  09:15  09:45  10:30  ···  14:00  14:30  15:15
          ╰──── Session 1 ────╯     ╰──── Session 2 ────╯
          (gap < 2h between each)   (gap > 2h from Session 1)
```

**Per session:**
- `actual_span` = last_commit_time - first_commit_time
- `estimated_time` = max(actual_span, commit_count × 0.5h)
- `buffered_time` = estimated_time × 1.15 (15% buffer for context-switching)

**Daily total** = sum of all session buffered_times.

### Edge Cases
- Single commit in a session → minimum 0.5h
- Commits spanning midnight → split at 00:00 into two day-blocks
- Merge commits → skip (they don't represent work time)
- Rebase/amend → count as single commit (timestamp of final)

## Activity Categorization

> **Scope:** these icons describe **commit-message classification** (what
> the git history shows). Distinct from the **log-entry activity types**
> in `SKILL.md` (what kind of work the human reports). Some icons overlap
> (🔧, 🐛, 📝, 🧪, 💻) but the meanings differ — don't unify.

Classify each commit by message pattern (first match wins):

| Pattern (case-insensitive) | Category | Symbol |
|---------------------------|----------|--------|
| `fix\|bug\|issue\|error\|crash\|hotfix\|patch` | Bug Fixing | 🐛 |
| `feat\|feature\|implement\|add.*feature` | Feature Development | 🎯 |
| `refactor\|clean\|optimize\|improve\|simplify` | Code Refactoring | 🔧 |
| `doc\|readme\|comment\|documentation\|wiki` | Documentation | 📝 |
| `test\|spec\|coverage\|unit.*test\|e2e` | Testing | 🧪 |
| `merge\|conflict\|rebase` | Integration | 🔄 |
| `config\|setup\|ci\|cd\|deploy\|infra\|docker` | Configuration | ⚙️ |
| `chore\|bump\|update.*dep\|upgrade` | Maintenance | 📦 |
| *(no match)* | Development | 💻 |

**Output per day:**
```
Activity breakdown:
  🎯 Feature Development    3h 15min  (4 commits)
  🐛 Bug Fixing             1h 30min  (2 commits)
  📝 Documentation          0h 45min  (3 commits)
  ──────────────────────────────────
  Total                      5h 30min  (9 commits, 2 sessions)
```

## GitHub API Strategy (3-Fallback)

When querying commits for a specific date across repos:

### Method 1: Events API (< 90 days old)
```bash
gh api "/users/{user}/events?per_page=100" --paginate \
  | jq '[.[] | select(.type == "PushEvent" and .created_at | startswith("{date}"))]'
```
- Fast (3-5 API calls)
- Includes ALL branches (not just default)
- Only available for last 90 days

### Method 2: Org Search (> 90 days, org specified)
```bash
# Iterate repos, then branches, then commits
for repo in $(gh repo list {org} --limit 200 --json name -q '.[].name'); do
  gh api "/repos/{org}/$repo/commits?author={user}&since={date}T00:00:00Z&until={date}T23:59:59Z" \
    2>/dev/null
done
```
- Comprehensive but slow (50-200+ API calls)
- Works for any date range
- Use when Events API is out of range

### Method 3: GraphQL Summary (fallback)
```bash
gh api graphql -f query='
  query($user: String!, $from: DateTime!, $to: DateTime!) {
    user(login: $user) {
      contributionsCollection(from: $from, to: $to) {
        commitContributionsByRepository {
          repository { nameWithOwner }
          contributions(first: 100) {
            nodes { occurredAt commitCount }
          }
        }
      }
    }
  }'
```
- Single API call
- Default branch only (misses feature branches)
- Good enough for overview, not for detailed analysis

### Selection Logic
```
if date is within last 90 days:
    try Method 1 (Events API)
    if fails or incomplete: fall back to Method 2
else:
    use Method 2 (Org Search)
    if timeout or too many repos: fall back to Method 3
```

## User Filtering

When analyzing shared branches, filter by user identity:

```bash
# Check BOTH author and committer (can differ in cherry-picks)
gh api "/repos/{org}/{repo}/commits?since={date}&until={date}" \
  | jq '[.[] | select(
    .author.login == "{user}" or
    .commit.author.email == "{email}" or
    .committer.login == "{user}"
  )]'
```

User identity sources (priority order):
1. Explicit `--user {login}` flag
2. `bridge-config.yaml` → `identity.name`
3. `git config --global user.name`
4. `gh api /user` → `.login`

## Natural Language Date Parsing

| Input | Resolution |
|-------|-----------|
| `today` | current date |
| `yesterday` | current date - 1 |
| `last monday` | most recent Monday |
| `last week` | Monday-Friday of previous week |
| `2026-04-11` | exact date |
| `april 11` | April 11 of current year |

## Integration with Briefing

The sparkline in `/briefing` already shows commit volume. Commit analysis adds:
- Activity type breakdown per repo (which kind of work, not just how many)
- Time estimation per day (how long, not just how many commits)
- Session detection (focused work vs scattered commits)

These feed into:
- Work log entries (auto-categorize by activity type)
- Time tracking exports (clockify integration)
- Weekly archive summaries (what % was bug fixing vs features)
