# Standing Orders

Standing Orders are **always-on rules** that apply to every session — permanent behavioral rules loaded at session start.

## How They Work

1. At session start (when `work.enabled: true`), all standing orders are loaded
2. Each order specifies which sub-agents it applies to (`applies_to:` — sub-agent names, empty = all)
3. When dispatching a sub-agent, its matching standing orders are included in its prompt
4. Orders with `enforcement: blocking` cause active warnings on violations

## Schema

Each standing order is a markdown file with YAML frontmatter:

```yaml
---
name: order-name
scope: always                 # always | per-repo | per-context
enforcement: advisory         # advisory | blocking
applies_to: []                # sub-agent names (empty = all agents)
---
```

### Scope

| Value | Meaning |
|-------|---------|
| `always` | Applies in every session, every repo |
| `per-repo` | Only when a matching repo is active |
| `per-context` | Only in specific contexts |

### Enforcement

| Value | Meaning |
|-------|---------|
| `advisory` | Claude follows the rule |
| `blocking` | Claude actively warns when it detects a violation |

## Creating Standing Orders

Copy `_template.md`, fill in frontmatter and rules. Place in this directory.

## Built-in Orders

| Order | Enforcement | Purpose |
|-------|-------------|---------|
| board-task-criteria | advisory | When a log entry should escalate to a Board task (A/B/C class model) |
| code-standards | advisory | Code quality guidelines |
| document-work | blocking | Log all significant actions to work/log.md |
| drift-advisory | advisory | Surface drift between declared state and live reality |
| feature-discovery | advisory | Proactively suggest relevant Bridge features |
| security-baseline | advisory | Security practices |
| task-sync | blocking | Route task changes across project/context/mandant; enforce dual-doku |
| work-board-reconciliation | advisory | Keep task folders and STATUS.md / board coherent |
