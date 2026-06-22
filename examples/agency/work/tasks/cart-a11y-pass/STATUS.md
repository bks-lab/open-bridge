---
slug: cart-a11y-pass
type: bug
status: review
priority: P2
created: 2026-06-19
last_updated: 2026-06-23
sync:
  github:
    repo: acme-dev/bigcorp-frontend
    issues: [208]
    project: { org: acme-dev, number: 1 }
---

# BigCorp storefront — cart accessibility pass

## Situation

The cart modal traps neither focus nor Escape, and the quantity stepper has no labels —
it fails keyboard and screen-reader use.

## Status

Fixes done and pushed as PR #214: focus-trap on the modal, Escape to close, aria-labels on
the stepper. In review.

## Next Steps

- [ ] address review comments on PR #214
- [ ] re-run axe-core in CI
- [ ] merge once green (maintainer's call)
