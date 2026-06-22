---
slug: platform-maintenance
type: ops
status: doing
priority: P3
created: 2026-05-02
last_updated: 2026-06-23
sync:
  bridge_only: true
---

# Platform maintenance (stream)

## Situation

A long-running stream for the work that never "finishes": dependency bumps, CI upkeep, and
infra tweaks across the Acme repos. It lives in `work/streams/`, so it does not count
against the WIP cap.

## Status

Ongoing. Latest: bumped CI runners and pinned deps on 2026-06-23.

## Next Steps

- [ ] quarterly dependency audit
- [ ] move the staging deploy to the new runner image
