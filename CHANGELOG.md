# Changelog

All notable changes to open-bridge are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and versions follow
[Semantic Versioning](https://semver.org/). open-bridge is in the `0.x`
series: APIs, conventions, and layout may change between minor releases.

The current version is the latest entry below and the latest
[GitHub release](https://github.com/bks-lab/open-bridge/releases) — the
release badge in the README reads it live.

## [0.2.0] — public preview

First public-preview release of open-bridge, the open-source layer of the
two-pole Bridge setup (open-bridge ↔ your private Bridge, with an optional
org overlay).

- Cluster-wrapper layout (`identity/`, `infra/`, `workflow/`) with
  default-to-folder per config type.
- Agent-agnostic skill discovery (`.claude/skills`, `.agents/skills`,
  `.github/skills`) — Claude Code, Codex, Gemini CLI, Copilot CLI, Cursor.
- Work system (board, log, STATUS), protocols, named sub-agents, themes,
  project registry, onboarding wizard.
- OSS governance stack: MIT License (code and content), DCO, trademark
  policy, security policy, code of conduct.
- Removed the legacy crew-role taxonomy (eight fixed roles as
  `crew_roles` in protocols, `agents.default_roles` in bridge-config,
  role vocabularies in themes). Protocols now declare `agents:` — a
  list of concrete sub-agent names with a `general-purpose` fallback;
  themes map user-facing labels only.
- Removed the unused situational-protocol/alert dispatch layer
  (standing orders remain): the ten example protocols in `protocols/`,
  `protocols/_templates/`, the `bridge-alert` and `bridge-mission`
  skills, `docs/protocol-catalog.md`, `docs/orchestrator.md`,
  `docs/observe-protocol.md`, the `work/active-protocol.yaml`
  mechanic, and the `alerts:` vocabulary block in themes. Standing
  orders, the work system, briefing/debrief/archive, and the
  calendar/mandants/channels/remotes surfaces are the core narrative.

### Added
- `bridge-contribute` skill — dedicated `/contribute` entry point for the
  community: scans your branch, enforces the mandatory two-layer
  content-safety gate, and opens a fork-based PR back to
  `bks-lab/open-bridge` (split out of `bridge-promote`).
- `work/templates/week-summary.md` — the weekly-summary template `/archive`
  builds from now ships.
- `work/_learning/_schema.proposal.yaml` — proposal frontmatter schema
  (mirrors the producer schema in `task-close-postmortem`).
- Example instances for every config type: `examples/agency/` gained
  `identity/accounts/cloud-provider.yaml` and `infra/backups/topology.yaml`;
  `rules/file-creation.md` peer-example column now points only at files
  that ship.
- Top-level `imports/` drop-zone ships (`.gitkeep`), matching `.gitignore`
  and `docs/structure.md`.

### Changed
- README: directory structure now matches the shipped tree (`scripts/`,
  `bin/`, root policy files, real `work/` contents), skill tree updated.
- `bridge-promote` is now strictly commit-level; file-level contribution
  flow moved to `bridge-contribute`.
- Documentation truth pass: docs no longer reference files that are not
  shipped. Visualization HTML variants are documented as rendered on
  demand (not committed); `build-constellation.py` now explains the
  missing-render case instead of crashing; the calendar fire-loop and
  Bridge-Deck integrations are consistently framed as optional companion
  features (not yet public); `bridge-audit`'s agent-identity check matches
  the templates-only shipping design; briefing's backup-health step works
  from `topology.yaml`/`_state.yaml` directly; rename-registry and
  leak-check vocabulary entries repaired and pruned to shipped paths.
- Genericization pass: internal roadmap dates, personal device/channel
  names, and a personal job-application pipeline removed from shipped docs
  and example lists; placeholder examples (`lab-device`, `news-digest`,
  `router`, `network-reconcile`) used instead.

### Removed
- Documentation reduction pass (fewer docs over more docs): deleted the
  pointer-only `docs/promote-rules.md` (rules live in `rules/operations.md`
  + `rules/promote-safety.md`), `DESIGN-md-guide.md` (condensed into
  DESIGN.md § Maintaining this file), and two unreferenced HTML templates.
  `docs/bridge-deck.md` reduced to a coming-soon stub; `docs/remotes.md` and
  `docs/channels.md` trimmed to concept + pointers (schemas/workflows live
  in templates and skills); experimental v3 UI narrative removed from the
  bridge-explorer reference.
- `cloudflare-ops` skill (provider tooling without Bridge relevance).
- `playwright-fanout` skill (generic test tool without Bridge relevance).
- All bridge-deck references in the README (the renderer repo is not yet
  public — internal docs keep a "coming soon" note).

Early and evolving — no stability guarantees yet. Pin a release tag for
reproducibility.
