---
summary: "Curated entry-points into the open-bridge documentation."
type: readme
last_updated: 2026-07-02
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
- [`repo-layout.md`](repo-layout.md) — Visualisations. The primary C-prime view is generated on demand; brain-metaphor variants v1–v4 are alternatives.
- [`extension-model.md`](extension-model.md) — how CORE extends, how USER customises.
- [`multi-instance.md`](multi-instance.md) — running multiple Bridge instances.
- [`knowledge-repo-pattern.md`](knowledge-repo-pattern.md) — pairing a Bridge instance with an optional knowledge/documentation repo.
- [`skill-distribution-architecture.md`](skill-distribution-architecture.md) — ADR: where skills live across the tier model (framework repo vs org overlay marketplace).

## Subsystems

- [`bridge-deck.md`](bridge-deck.md) — pixel-art visualizer (coming soon).
- [`channels.md`](channels.md), [`remotes.md`](remotes.md) — outbound transports + machine fleet.
- [`calendar.md`](calendar.md), [`mandants.md`](mandants.md) — scheduled outbound + recipient groups.
- [`personas.md`](personas.md) — user identities (tax data, signatures, paths).
- [`doc-system.md`](doc-system.md) — document intake & filing (scan, name, tag, file, audit).
- [`transcription-worker.md`](transcription-worker.md) — bring-your-own transcription worker: the `/debrief` ↔ pipeline contract + the no-worker manual path. Reference implementation: `skills/meeting-transcription/`.
- [`cloud-accounts.md`](cloud-accounts.md) — cloud-account inventory convention (read the inventory file before any cloud op).
- [`memory.md`](memory.md) — file-based memory model (one fact per file, MEMORY.md as a lean index).
- [`work-system.md`](work-system.md) — Task Management concept: log/board/tasks lifecycle (KIND folder vs `status:` field).
- Task Management (log/board/tasks lifecycle) — [`AGENTS.md` § Task Management](../AGENTS.md) (operational source of truth).

## Operations

- Promoting CORE changes from user branch — [`rules/operations.md`](../rules/operations.md) (path allowlist/routing) + [`rules/promote-safety.md`](../rules/promote-safety.md) (content scan).
- [`releasing.md`](releasing.md) — maintainer runbook for cutting a release (CHANGELOG bump, tag, validation + GitHub release).
