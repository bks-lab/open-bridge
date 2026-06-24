# Changelog

All notable changes to open-bridge are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and versions follow
[Semantic Versioning](https://semver.org/). open-bridge is in the `0.x`
series: APIs, conventions, and layout may change between minor releases.

The current version is the latest entry below and the latest
[GitHub release](https://github.com/bks-lab/open-bridge/releases) — the
release badge in the README reads it live.

## [0.3.1](https://github.com/bks-lab/open-bridge/compare/v0.3.0...v0.3.1) (2026-06-24)


### Fixed

* **bridge-onboard:** generic capability detection, drop memory-scan from onboarding ([#40](https://github.com/bks-lab/open-bridge/issues/40)) ([e4a4e26](https://github.com/bks-lab/open-bridge/commit/e4a4e2686bf4ef168fc45330f4b935681484a16d))

## [0.3.0](https://github.com/bks-lab/open-bridge/compare/v0.2.0...v0.3.0) (2026-06-24)


### Added

* populate the agency example's work board ([#33](https://github.com/bks-lab/open-bridge/issues/33)) ([4f85de8](https://github.com/bks-lab/open-bridge/commit/4f85de8b662747baec96b960c88d3080847adc38))


### Documentation

* add Demo to nav on explore + concepts pages ([#34](https://github.com/bks-lab/open-bridge/issues/34)) ([968035f](https://github.com/bks-lab/open-bridge/commit/968035fb07449f9456c037e8d175b0350ded8cb3))
* animated live-session demo (4 scenes) ([#31](https://github.com/bks-lab/open-bridge/issues/31)) ([e269681](https://github.com/bks-lab/open-bridge/commit/e269681fea8953a0e259850c38f9d37dab676669))
* animated session GIF as the README hero ([#35](https://github.com/bks-lab/open-bridge/issues/35)) ([bfc5941](https://github.com/bks-lab/open-bridge/commit/bfc59419d514e54892b9af2c56d5c8f930a141f3))
* close doc-index drift (standing-orders table, docs/README, agency example) ([ef43d62](https://github.com/bks-lab/open-bridge/commit/ef43d62622dce7e6dff6481a2431a2fa2ea45b9e))
* **community:** SUPPORT.md, issue-template config, OG/social preview ([69abb68](https://github.com/bks-lab/open-bridge/commit/69abb6885be531e2a7a1c2b7ed6cf5eb8e50cd41))
* fix audit findings — dead command, drift, English-only, frontmatter ([8692aaf](https://github.com/bks-lab/open-bridge/commit/8692aaf825a8557005b2f68f091371824799bb67))
* fix second-pass audit findings — anchors, private link, shipped-vs-documented, /onboard ([913d56f](https://github.com/bks-lab/open-bridge/commit/913d56fa67c039222ac0c2ae120d8dfd1b901035))
* **landing:** add "a day with it" use-cases + what-is-a-bridge / multi-bridge ([5b75469](https://github.com/bks-lab/open-bridge/commit/5b754691b2b3b66eceb6cd8b7882afa110d1116a))
* **landing:** benefit-led copy overhaul + knowledge-constellation hero ([fcd580d](https://github.com/bks-lab/open-bridge/commit/fcd580dfec2e82413d4b2f6c78cb44f7f13a68b6))
* **landing:** drop the duplicate static constellation (lives on Explore now) ([1a1bb4e](https://github.com/bks-lab/open-bridge/commit/1a1bb4e955870bbb4749f2fc6c008a3b0fd9f687))
* **landing:** elevate landing page + fully-English README ([8fe398e](https://github.com/bks-lab/open-bridge/commit/8fe398e3fbbbd43a61313f20d7d2351865fca5bb))
* **landing:** simpler hero net + full constellation in substrate ([0d619ed](https://github.com/bks-lab/open-bridge/commit/0d619ed7468524aa6edd27ea9535f005d98774fa))
* **landing:** sticky in-page nav + remove all German terms + onboarding-does-setup + condense ([9d3d211](https://github.com/bks-lab/open-bridge/commit/9d3d21151744abfae5b5cee31b5297d75e4bf955))
* link the live demo from the landing page ([#32](https://github.com/bks-lab/open-bridge/issues/32)) ([b502d8b](https://github.com/bks-lab/open-bridge/commit/b502d8b8cba5c723ecd4564492bb78c6fe2cae7b))
* **pages:** serve the landing page via GitHub Pages ([36fdfa3](https://github.com/bks-lab/open-bridge/commit/36fdfa3f67305d3678c708990ef9b90f1f360c85))
* **site:** mini-site — Explore constellation + Concepts deep-dive + shared nav ([6aac5ed](https://github.com/bks-lab/open-bridge/commit/6aac5ed7fe40194a70004eb03c927d28c71a22d8))

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
