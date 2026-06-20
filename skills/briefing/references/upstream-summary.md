# Upstream Summary — Semantic Diff Analysis

When checking for upstream updates (during `/briefing` or `/archive`), replace the
flat `git log --oneline` output with a structured, category-grouped summary.

> **When this applies:** "Upstream" here means a separate fork-source repo
> (typically `bks-lab/open-bridge` for OSS forks, or your org's
> `<your-org>/<your-org>-bridge` overlay if you have one) configured as
> a git remote named `upstream`.
> This is **distinct from "Origin-CORE drift"** — `HEAD..origin/development`
> within the same fork — which `/briefing` Phase 0 handles directly without
> reading this file.
>
> **Seed-repo instances skip this entirely.** When `bridge-config.yaml` has no
> `upstream:` block (the open-bridge / Seed-repo setup), there's nothing to
> sync from — this whole file is a no-op. The `/briefing` decision tree
> already routes around it; don't load this file unless prerequisites pass.

## Prerequisites

All three must hold, else skip:

1. `bridge-config.yaml` contains an `upstream:` block.
2. A git remote named `upstream` exists: `git remote -v | grep '^upstream'`.
3. Check interval respected: `upstream.last_check` + `upstream.check_interval_days`
   from `bridge-config.yaml` (default: 7 days).

## Algorithm

### Step 1: Fetch

```bash
git fetch upstream development 2>/dev/null
```

If no `upstream` remote, check if `origin` is a fork. If so, suggest adding upstream.
If `origin` IS the source repo (not a fork), skip entirely.

### Step 2: Get changed files

```bash
git diff --name-only development..upstream/development
```

If empty: "Upstream is up to date." — done.

### Step 3: Group by path prefix

Map each changed file to a category using the **first matching** prefix:

| Path Prefix | Category | Icon |
|-------------|----------|------|
| `protocols/standing-orders/` | Standing Orders | 📌 |
| `themes/` | Themes | 🎨 |
| `skills/` | Skills | 🧠 |
| `rules/` | Rules | 📏 |
| `docs/` | Documentation | 📖 |
| `examples/` | Examples | 📦 |
| `CLAUDE.md` | Core Docs | 📄 |
| `README.md` | Core Docs | 📄 |
| `CONTRIBUTING.md` | Core Docs | 📄 |
| `.github/` | CI/CD | ⚙️ |
| *(everything else)* | Other | 📁 |

### Step 4: Count new vs modified per category

For each file in the diff:
- **New:** file exists in `upstream/development` but not in `development`
- **Modified:** file exists in both but content differs

```bash
# Check if a file is new or modified
for file in $(git diff --name-only development..upstream/development); do
  if git cat-file -e development:"$file" 2>/dev/null; then
    echo "modified: $file"
  else
    echo "new: $file"
  fi
done
```

### Step 5: Conflict prediction

```bash
git merge-tree $(git merge-base development upstream/development) development upstream/development
```

Parse output for lines containing `CONFLICT`. Extract conflicting file paths.

- **No conflicts:** clean merge expected
- **Conflicts found:** list each conflicting file with a brief reason

### Step 6: Date range

```bash
# Oldest commit not yet merged
git log development..upstream/development --format='%ai' --reverse | head -1 | cut -d' ' -f1
```

This gives the "since" date for the summary header.

### Step 7: Present summary

**Clean merge:**
```
Upstream Update: 8 changes across 4 categories (since 2026-04-03)

  📌 Standing Orders: +1 new (code-standards), 1 modified (task-sync)
  🎨 Themes:         +1 new (professional-de)
  ⌨️ Commands:        1 modified (promote — Phase 7 added)
  📖 Documentation:   2 modified (work-system, structure)

  Conflict check: ✅ clean merge expected

  [m] Merge now  [d] Show full diff  [s] Skip
```

**With conflicts:**
```
Upstream Update: 8 changes across 4 categories (since 2026-04-03)

  📌 Standing Orders: +1 new (code-standards), 1 modified (task-sync)
  🎨 Themes:         +1 new (professional-de)
  ⌨️ Commands:        1 modified (promote — Phase 7 added)
  📖 Documentation:   2 modified (work-system, structure)

  Conflict check: ⚠️ 2 files would conflict
    - CLAUDE.md (your local edits vs upstream changes)
    - protocols/standing-orders/task-sync.md

  [d] Show diff  [s] Skip  [f] Force merge (manual resolution)
```

### File name extraction

For the per-category detail (e.g. "+1 new (health-check)"), extract a human-readable
name from the file path:
- Strip the category prefix and file extension
- Use the basename: `protocols/standing-orders/drift-advisory.md` → `drift-advisory`
- If >3 files in one category, show the first 2 and `+N more`

## User actions

| Choice | Action |
|--------|--------|
| `[m]` Merge | `git merge upstream/development` into local `development`, then offer `git merge development` on user branch |
| `[d]` Diff | `git diff development..upstream/development` — full diff output |
| `[s]` Skip | Update `upstream.last_check` timestamp, continue without merging |
| `[f]` Force | Only shown when conflicts exist. Run merge, user resolves conflicts manually |

## After check

Always update `bridge-config.yaml`:
```yaml
upstream:
  last_check: "2026-04-10T09:30:00+02:00"
```
