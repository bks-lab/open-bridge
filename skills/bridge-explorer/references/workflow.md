# Ecosystem Explorer

Interactive visualization of the org ecosystem in the cmux browser.

**Trigger:** `/explorer`

## Workflow

### 1. Extract data from ecosystem.yaml

Read `ecosystem.yaml` and extract:

**Repos** — All repos from `base`, `customers.*.repos`, `customers.*.packages`, `partners.*.repos`, `internal`, `personal`:
- `name`: repo name (short, e.g. "outbound-operator" instead of "customer-a-network-outbound-operator")
- `type`: function-app, package, tool, docs, web, infra
- `lang`: python, rust, typescript, javascript, go or null
- `color`: color by group (base=#6366f1..#c4b5fd, customer-a=#22c55e..#86efac, packages=#06b6d4..#a5f3fc, partner=#ec4899, internal=#f472b6..#fb7185, personal=#f59e0b)
- `group`: base, customer-a, packages, partner, internal, personal
- `deps`: array of dependency names (from `depends_on`), only when present

**Workspaces** — from `workspaces`:
- `name`, `repos_count`

**Skills** — from `skills.*` (all categories, short form without prefix):
- Flat array of skill names

**Infra** — from `customers.customer-a.infra`:
- Azure Functions: `{ name, status: "running", color: "#22c55e" }`
- Elasticsearch: `{ name: "elasticsearch", status: "healthy", color: "#22c55e" }`
- KeyVault: `{ name, status: "ok", color: "#22c55e" }`

**Activity** — last 8-10 git commits from this Bridge repo:
```bash
git log --oneline -10 --format='%ar|%s'
```
- `time`: relative time ("2h ago" → "14:30" format)
- `msg`: commit message
- `tag`: commit/deploy/issue/skill depending on content (feat/fix→commit, deploy→deploy, issue/bug→issue, skill→skill)
- `delay`: staggered (0, 600, 1200, ...)

**Stats:**
- `repos`: count of all repos
- `skills`: count of all skills (count from skills.* categories)
- `customers`: number of customers (customers.*)
- `functions`: number of Azure Functions

**Branch:**
```bash
git branch --show-current
```

### 2. Generate HTML

Read the template from `docs/templates/ecosystem-explorer.html`.

Replace the `ECOSYSTEM_DATA` placeholder block (the entire `const ECOSYSTEM_DATA = { ... };`) with the extracted data as a JSON object:

```javascript
const ECOSYSTEM_DATA = {
  repos: [ /* populated data */ ],
  workspaces: [ /* populated data */ ],
  skills: [ /* populated data */ ],
  infra: [ /* populated data */ ],
  activity: [ /* populated data */ ],
  stats: { repos: N, skills: N, customers: N, functions: N },
  branch: "user/alice"
};
```

Write the result to `work/ecosystem-explorer.html`.

### 3. Open in the cmux browser

```bash
# cmux available?
cmux ping

# Open browser split
cmux browser open-split "file://$(pwd)/work/ecosystem-explorer.html"

# Notification
cmux notify --title "Ecosystem Explorer" --body "Dashboard live"
```

If cmux is not available: `open work/ecosystem-explorer.html` as fallback.

### 4. Set sidebar status

```bash
cmux set-status explorer "live" --icon globe --color "#6366f1"
```

## Pattern for new dashboards

This skill follows the **Template + Skill Pattern**:

```
docs/templates/{name}.html     ← HTML template with DATA placeholder
skills/{name}/SKILL.md         ← Skill: read data → fill template → open in cmux
work/{name}.html               ← Generated HTML (transient, USER path)
```

Everything under `docs/templates/` and `skills/` is CORE (promotable).
Generated files under `work/` are transient and belong to the USER branch.
