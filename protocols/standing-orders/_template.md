---
name: order-name
scope: always                  # always | per-repo | per-context
enforcement: advisory          # advisory | blocking | hook-warned (needs a backing check in scripts/hooks/pre-commit)
applies_to: []                 # sub-agent names (empty = all agents)
load: on-trigger               # eager | on-trigger (default: eager)
fires_unprompted: false        # true: must act while nobody says its vocabulary; --check then refuses on-trigger
triggers: ["a phrase", "another phrase"]   # required for on-trigger: what fetches this body
summary: "One line. It stays in context permanently, so keep it under 200 chars."
---
# Order Title

<!-- Keep `load: eager` ONLY when the order bites while nobody says its own
     vocabulary (a logging duty, a security floor). Everything else is
     on-trigger: the summary above stays in context, the body arrives when the
     trigger lands. Validate with `python3 scripts/standing-orders.py --check`. -->

## Rules

- {Rule 1: what must happen}
- {Rule 2: what must happen}

## Violations

{What counts as a violation of this order?}
