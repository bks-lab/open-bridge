---
summary: "Repo layout visualisations for The Bridge — primary view is c-prime.html (editorial cluster/top-level map), brain-metaphor variants v1-v4 render the same data alternatively."
type: moc
last_updated: 2026-05-09
related:
  - skills/bridge-explorer/SKILL.md
  - skills/bridge-explorer/references/repo-layout.md
  - docs/repo-layout/regions.yaml
  - docs/structure.md
  - CLAUDE.md
---

# Repo Layout — Visualisations

## Why this exists

The cluster-wrapper layout (`identity/`/`infra/`/`workflow/` with
default-to-folder per config type) is the load-bearing rule of this
repo. This page indexes every visual rendering of it. They are the
visual companions to [`CLAUDE.md` → Layout](../CLAUDE.md) and
[`docs/structure.md`](structure.md) — same truth, different modalities.

## Primary view

The primary view (`c-prime`) is the canonical editorial map. It shows
the top-level + the three cluster-wrappers as cards with all folder
contents and layer annotation (CORE / USER / gitignored). Single-file
HTML, dark/light toggle, no external dependencies. Rendered on demand
by `/bridge-explorer` from
[`docs/repo-layout/regions.yaml`](repo-layout/regions.yaml) — not
committed.

## Alternative brain-metaphor variants

Four brain-metaphor renderings + one "stable" snapshot. All share the
same description set (`regions.yaml`) and carry a banner at the top
linking back to the c-prime view. Use these when conveying the layout
conceptually — the brain metaphor carries CORE/USER hemispheres
didactically.

| Variant | Metaphor | Stack | Size | Best for |
|---------|----------|-------|------|----------|
| v1 | Hemisphere brain (CORE = left, USER = right) — static | HTML/CSS/SVG | ~63 KB | Quick reference, slide embed |
| v2 | Brain with anatomical region labels + side panel | HTML/CSS/SVG | ~80 KB | Onboarding for new contributors |
| v3 | Particle brain with heatmap + dependency arcs (experimental) | HTML/CSS + JS | ~190 KB | Live exploration, info-layer experimentation |
| v4 | Sagittal cross-section — two columns, dense | HTML/CSS | ~50 KB | Print, reference card |

(`v3-stable` was removed on 2026-05-02 — c-prime took over its role as the calm live-exploration view.)

## How to regenerate

Via the `bridge-explorer` skill:

- `/bridge-explorer repo`
- "repo layout", "core/user split", "where do files live"

The skill reads `docs/repo-layout/regions.yaml` (single source of truth
for descriptions + ownership) plus the live state of the working tree
and emits the HTMLs again. To change a region description, edit
`regions.yaml` and regenerate — never hand-patch the HTML.

## Where the files live

**Committed (CORE):**
- `docs/repo-layout/regions.yaml` — region IDs, owner (core/user),
  display_name, oneliner, what. Single source of truth for all
  visualisations.
- `docs/repo-layout/build-constellation.py` — generator script used by
  the `bridge-explorer` skill (refreshes the constellation data block
  of an already-rendered `network.html`).

**Rendered HTMLs (NOT committed — generated on demand):**
The HTML views — the primary cluster-card view, the brain-metaphor
variants, and an optional control-center `index.html` — are rendered on
demand by `/bridge-explorer` from `regions.yaml` plus the live working
tree. They are intentionally not tracked in the repo: rendered output
drifts quickly and can embed instance-specific content. If you need a
view, regenerate it; if you serve one from a remote machine (see below),
sync the freshly rendered file there instead of committing it.

## How to access over the network (optional)

Locally, render via `/bridge-explorer` and `open` the generated file.
If you also want rendered visualizations reachable from your other
machines, run a small HTTP server on one of your remotes
(`infra/remotes/`) serving a directory of rendered HTML, and declare it
as a channel under `infra/channels/` so the Bridge knows where to sync
freshly rendered files. Nothing for this ships with open-bridge — add
the network layer only if you need it.

## CORE/USER split — Source of truth

The authoritative table lives in [`CLAUDE.md` → Layout](../CLAUDE.md)
and [`docs/structure.md`](structure.md). Visualisations render that.
On conflicts, CLAUDE.md wins; `regions.yaml` must follow.
