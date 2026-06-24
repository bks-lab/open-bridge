# Ecosystem Discovery — Repo Scan Algorithm

> **Scope note (2026-05-16):** This file describes only the
> **repo-detection** part of discovery. The broader system scan
> (apps, mesh-VPN, mail accounts, finance apps, documents structure)
> moved to [`system-discovery.md`](system-discovery.md) as Phase B of
> the wizard, and this file is now invoked as a sub-step from there
> (matching `evidence.developer.*` in the scan output).

Used during `/bridge-onboard` Phase B and `/bridge --rescan` to detect
repos automatically.

## Step 1: Find Local Repos

```bash
find ${projects_root} -maxdepth 2 -name .git -type d | sed 's|/.git$||'
```

Produces a list of directories containing git repos. Skip hidden directories and
common non-project paths (node_modules, .cache, vendor).

## Step 2: Detect Remote Origin + Org

For each discovered repo:

```bash
git -C "$repo" remote get-url origin 2>/dev/null
```

Parse the URL to extract org and repo name:
- `https://github.com/{org}/{name}.git` → org=`{org}`, name=`{name}`
- `git@github.com:{org}/{name}.git` → same extraction
- Other hosts (GitLab, Bitbucket): record host + org

## Step 3: Language Detection

Count files by extension in each repo (top-level + one level deep):

| Extensions | Language |
|-----------|----------|
| `*.py` | python |
| `*.ts`, `*.tsx` | typescript |
| `*.js`, `*.jsx` | javascript |
| `*.rs` | rust |
| `*.go` | go |
| `*.java` | java |
| `*.rb` | ruby |
| `*.cs` | csharp |

Highest file count wins. Ties: pick the first match. If no code files found,
check for `Dockerfile`, `*.yaml`/`*.yml`, `*.md` → type `infra`, `config`, or `docs`.

## Step 4: GitHub Repo Discovery (optional)

If `gh` CLI is available and authenticated:

```bash
gh repo list {org} --limit 50 --json name,description,primaryLanguage
```

Compare with local repos. Uncloned repos appear as suggestions:
- Show name + description
- Offer: `gh repo clone {org}/{name} ${projects_root}/{name}`

Skip if `gh` is not installed — note in output and continue.

## Step 5: Preview Table

Present results as a markdown table for user confirmation:

```
Repo                Language     Org          Local Path
────────────────    ──────────   ──────────   ─────────────────────────────
my-api              python       acme-corp    ~/Developer/acme/my-api
frontend            typescript   acme-corp    ~/Developer/acme/frontend
infra               (config)     acme-corp    ~/Developer/acme/infra
─ not cloned ─
docs-site           javascript   acme-corp    (offer clone)
```

User confirms → generate `ecosystem.yaml` entries from the scan results.
User edits → adjust before generating.
