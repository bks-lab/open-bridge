---
slug: dark-mode-toggle
type: feature
status: done
priority: P2
created: 2026-06-16
last_updated: 2026-06-22
headline: "Dark-mode toggle shipped — persists via localStorage, falls back to OS preference"
sync:
  github:
    repo: acme-dev/startupxyz-app
    project: { org: acme-dev, number: 2 }
---

# Dark-mode toggle

## Situation

Users asked for a dark theme on the StartupXYZ app. Add a toggle that persists the choice
and respects the OS preference on first load.

## Status

Done — shipped 2026-06-22. The toggle persists via localStorage and falls back to
`prefers-color-scheme` when unset.

## Next Steps

- [x] toggle + persistence
- [x] OS-preference fallback
- [x] shipped
