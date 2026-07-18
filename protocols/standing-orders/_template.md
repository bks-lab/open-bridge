---
name: order-name
scope: always                  # always | per-repo | per-context
enforcement: advisory          # advisory | blocking | hook-warned (needs a backing check in scripts/hooks/pre-commit)
applies_to: []                 # sub-agent names (empty = all agents)
---
# Order Title

## Rules

- {Rule 1: what must happen}
- {Rule 2: what must happen}

## Violations

{What counts as a violation of this order?}
