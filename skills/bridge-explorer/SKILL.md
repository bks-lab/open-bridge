---
name: bridge-explorer
description: >-
  Bridge visualizations — ecosystem (repos, workspaces, skills, infra), repo
  layout (CORE/USER split, 4 brain-metaphor variants v1–v4), and constellation
  (5-layer information network with hub-out routing). Single-file HTML,
  dark/light, opens in browser. Descriptions sourced from
  docs/repo-layout/regions.yaml.
  Trigger: "/bridge-explorer", "explorer",
  "show ecosystem", "repos overview", "repo layout", "core/user split",
  "where do files live", "repo structure", "network diagram", "constellation",
  "information flow", "how is everything linked".
metadata:
  scope: core
---

# Bridge Explorer

Visualize Bridge state as interactive HTML dashboards.
Read the referenced file ONLY when triggered.

## Decision Tree

```
User wants to...
├── Ecosystem visualization            → Read references/workflow.md
├── CORE/USER repo split visual        → Read references/repo-layout.md
│   (triggers: "repo layout", "core/user", "where do files live",
│    "repo structure"; pick variant v1–v4 or c-prime, see below)
├── Information flow / network         → Render + open the network variant
│   (triggers: "network diagram", "constellation", "how is everything linked",
│    "how does the bridge distribute information", "layers")
└── Questions about ecosystem          → Read ecosystem.yaml directly
```

## Repo-layout variants

All variants render the same CORE/USER + cluster-wrapper split, sourced from
`docs/repo-layout/regions.yaml` (single source of truth — edit there, all
variants pick up on regenerate).

**Constellation (`network`) is generated, not hand-edited.** Its nodes/edges/flows
live in `regions.yaml` under `constellation:` (schema v3). After editing them run:

```
python3 docs/repo-layout/build-constellation.py
```

This injects the JS data block into `network.html` between the `CONSTELLATION-DATA`
markers and bumps the version badge. **Precondition:** `network.html` must have been
rendered first — the script refreshes the data block of an existing rendered file;
on a fresh clone there is no `network.html` yet, so render it via this skill first.
Wire it into your deploy pipeline so the served HTML never drifts from
`regions.yaml` by hand.

| Variant | Lens |
|---------|------|
| c-prime | Editorial cluster/top-level map (primary, dense) |
| network | **Constellation** — 5-ring information network (hub → brain → synapses → memory → state → world), 4 sectors (Meta · Operations · CustomerA · Identity), bundled edges, named flows |
| v1 | Hemispheric brain (CORE left, USER right) — static SVG |
| v2 | Brain with anatomical region labels + side panel |
| v3 | Interactive brain — click region for drill-down |
| v4 | Minimal two-column schematic — dense, print-friendly |

User-facing MOC: [`docs/repo-layout.md`](../../docs/repo-layout.md).

