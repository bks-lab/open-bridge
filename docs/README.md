---
summary: "Curated entry-points into the open-bridge documentation."
type: readme
last_updated: 2026-06-11
---

# Docs — What's important?

Curated entry-points. For the full inventory, scan the directory.

This file was previously named `docs/_MOC.md` — per AGENTS.md
"Documentation Navigation" we now use `README.md` (industry standard)
instead of a bespoke `_MOC.md` / `index.md` convention.

## Architecture & onboarding

- The onboarding wizard lives in the `bridge-onboard` skill (`skills/bridge-onboard/`) — trigger via `/bridge-onboard`.
- [`feature-tour.md`](feature-tour.md) — per-cluster-wrapper "create your first X" guide (post-onboarding).
- [`structure.md`](structure.md) — Cluster-wrapper layout in prose form (Default-to-Folder).
- [`repo-layout.md`](repo-layout.md) — Visualisations. Primary view `repo-layout/c-prime.html`, brain-metaphor variants v1–v4 as alternatives.
- [`extension-model.md`](extension-model.md) — how CORE extends, how USER customises.
- [`multi-instance.md`](multi-instance.md) — running multiple Bridge instances.

## Subsystems

- [`bridge-deck.md`](bridge-deck.md) — pixel-art visualizer (coming soon).
- [`channels.md`](channels.md), [`remotes.md`](remotes.md) — outbound transports + machine fleet.
- [`calendar.md`](calendar.md), [`mandants.md`](mandants.md) — scheduled outbound + recipient groups.
- [`personas.md`](personas.md) — user identities (tax data, signatures, paths).
- Task Management (log/board/tasks lifecycle) — [`AGENTS.md` § Task Management](../AGENTS.md) (operational source of truth).

## Operations

- Promoting CORE changes from user branch — [`rules/operations.md`](../rules/operations.md) (path allowlist/routing) + [`rules/promote-safety.md`](../rules/promote-safety.md) (content scan).
