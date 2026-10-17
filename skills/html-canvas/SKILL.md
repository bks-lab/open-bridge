---
name: html-canvas
description: >-
  Builds single-file HTML documents: explainers, reference pages, architecture visualizations, light/dark and DE/EN toggles, DESIGN.md tokens. Also running models: simulations with a clock. NOT marketing pages or ops dashboards (creative-design-stack), not ecosystem maps (bridge-explorer). Trigger: "create an HTML page", "explainer", "html kit", "theme toggle", "simulate this".
metadata:
  scope: core
  version: 1.1.0
  last_updated: 2026-08-30
---

# html-canvas

Generate **rich single-file HTML** that reads well, themes light/dark, switches
DE/EN, and pulls every colour from DESIGN.md — the genre we keep hand-building
(explainers, reference kits, concept/architecture pages, use-case boards,
multi-section docs). One file, offline, no external dependencies, native UTF-8.

> **Scope:** `html-canvas` owns *content-as-document* — bilingual
> explainers, reference/concept/architecture pages, multi-section docs — with
> first-class light/dark + DE/EN toggles and a DESIGN.md-token section catalog.
> Marketing / landing / pitch pages belong to a style-picker design skill,
> if your Bridge ships one.

## The three controls every deliverable ships

These are the point of the skill — they come baked into the shell, don't reinvent them:

1. **Light / Dark** — button + key `T` + `localStorage`, anti-FOUC pre-paint in
   `<head>`, OS preference when unset. Applied via the `.dark` class on `<html>`
   (DESIGN.md convention).
2. **DE / EN** — button + key `L` + `localStorage`. Every translatable run ships
   as `data-de`/`data-en` siblings; the swap is pure CSS. Default = the
   conversation language. (Repo/OSS-shipped artifacts stay English regardless.)
3. **Print / PDF** — first-class: chrome hidden, reveals forced visible, dark
   pages forced to a light palette for clean paper.

## How to build

**One page:** generate the shell with tokens (`design-to-css.py --shell --out page.html`,
see Tokens below) → fill the `{{placeholders}}` → compose
`<main>` from the blocks in `references/sections.md` → add behaviours from
`references/interactivity.md` and motion from `assets/animations.css` if wanted.
Render light **and** dark, DE **and** EN, then file under
`work/tasks/<slug>/deliverables/`.

**A kit (many pages/boards):** use the parallel-builder workflow in
`references/build-workflow.md` — one convention audit emits a shared shell, N
builders run concurrently on it, one adversarial reviewer checks every page, then
integrate + write an index launcher. This is how the 12-board sets get built
consistently.

**Tokens:** generate the CSS variable layer from the design system with
```bash
python3 skills/html-canvas/scripts/design-to-css.py --shell --out page.html
```
That writes a copy of the shell whose region between `design-tokens:begin` and
`design-tokens:end` holds the instance's DESIGN.md values. The committed shell
holds CSS system colours there and nothing else, because this skill is CORE and
ships to instances with other brands. Everything below the region is derived
from those tokens (`var()` and `color-mix()`), never a colour of its own. Bare CSS
for other pages: `design-to-css.py --out tokens.css`. Never hand-pick a brand
colour; if a token is missing, add it to `DESIGN.md` first, then regenerate.

## Simulations: when the page has to RUN

Some things flatten in a diagram: a queue forming, a gate sending work back, two
agents disagreeing, a plan reaching a human at step six. Those get a **running
model** instead: a clock, a stage, controls, a protocol. Full playbook:
`references/simulation.md`. Never hand-build one; assemble it:

```bash
python3 skills/html-canvas/scripts/new-simulation.py --list
python3 skills/html-canvas/scripts/new-simulation.py --archetype flow --lang de \
    --title-de "…" --title-en "…" --out work/tasks/<slug>/deliverables/x.html
```

That splices the shell, `simulation.css`, `sim-engine.js` and one archetype into a
single offline file, asserting every splice. Then edit only the `MODEL` block.

**Two archetypes ship runnable.** `flow` (SVG stage: routes, stations with
capacity, queues, a gate, outcomes) and `worklist` (no geometry: a plan executed
step by step, protocol plus state strip). *console*, *dossier* and *exchange* are
documented as deltas from those two, not as separate engines.

**Four things make the difference between a running model and a lie**, all
enforced by the engine and spelled out in the reference: the engine never authors
user-visible text (a runtime string breaks the DE/EN swap); reduced motion and
print get the **computed end state**, never an empty stage; criticality always
rides colour **plus** a glyph and a word; and any page a viewer could mistake for
a live system carries the three-column provenance block (model, stock that
exists today, not built yet). The third column is the one that gets dropped and
the one that matters.

## Repo / project → architecture explainer

Turn a codebase (or its existing architecture doc) into a sectioned architecture
explainer. Full playbook: `references/repo-analysis.md`. Two paths:

- **Scan a doc** (cheap) — the repo already has an architecture/design doc → read it
  as the source, extract the spec, render. (The doc-driven path.)
- **Scan a repo/project** (offered, opt-in) — no doc, or you want ground-truth from
  code → **offer** a subagent fan-out (one agent per facet: modules, data model,
  flows, deps, …), synthesize an Architecture Spec, then render. It's heavy, so it's
  an offer, never automatic.

Always seed with facts first: `python3 skills/html-canvas/scripts/repo-scan.py <repo>`.
**Verify against code** — every component/edge/flow cites a real path; unsourced
architecture goes under a caveat ("unverified"), never stated as fact.

## Bundled resources

| File | What | Read it when |
|------|------|--------------|
| `assets/shell.html` | The starting template: tokens + theme + DE/EN + print + base styles | Always — it's the skeleton you copy |
| `references/sections.md` | ~20 copy-paste section blocks (headers, flows, swimlanes, matrices, KPIs, timelines, callouts, …) | Composing `<main>` |
| `references/interactivity.md` | Optional vanilla JS: scroll-reveal, slide engine, count-up, filtering, data hydration | Adding behaviour |
| `assets/animations.css` | Optional motion layer, all `prefers-reduced-motion`-gated | Adding animation |
| `references/build-workflow.md` | Parallel-builder workflow + the full quality/voice/accessibility bar | Multi-page kits, or before calling any page done |
| `scripts/design-to-css.py` | DESIGN.md → `:root` + `html.dark` CSS custom properties | (Re)generating tokens |
| `references/simulation.md` | Running models: archetypes, the engine API, the four honesty rules, the traps, the acceptance list | Anything that has to run rather than be read |
| `assets/sim-engine.js` | The engine: clock with watchdog, controls, protocol feed, SVG route helpers, seeded RNG | Pasted in by the assembler; read it to extend a model |
| `assets/simulation.css` | The visual layer for a running model, in shell tokens only | Same |
| `assets/sim-flow.html` · `assets/sim-worklist.html` | The two runnable archetype fragments (model + markup + page CSS) | Starting a simulation, or lifting one part into another |
| `scripts/new-simulation.py` | Assembles shell + layer + engine + archetype into one single-file page, asserting every splice | Always, when building a simulation |
| `references/repo-analysis.md` | Repo/doc → Architecture-Spec → sections: doc-scan + offered subagent fan-out + spec→block mapping | Building an architecture explainer from a repo |
| `scripts/repo-scan.py` | Deterministic repo inventory (languages, entry points, deps, docs) — the factual seed | Before analyzing any repo |

## Non-negotiables (full list in `references/build-workflow.md`)

- **No Google Fonts / any third-party font CDN**: GDPR. Self-hosted or a
  data-URI-inlined woff2, else the system stack DESIGN.md names as fallback.
- **DESIGN.md is the colour SoT**: tokens only, never hand-picked hex, and never
  pasted by hand: `design-to-css.py --shell --out page.html` fills the shell's
  marked token region. The shell itself carries no brand value. Type follows the
  DESIGN.md typography roles (weights, sizes, display face vs sans); a gradient on
  text or fill is never a default.
- **Colour = meaning, not decoration**: neutral chrome + the brand accent;
  semantic lens/actor colours are the only exception and always ship a legend;
  status reads by shape (`● ◐ ✗ –`) first.
- **SOUL.md voice** — no hero-arc/hype/slogans; the user is the sender (recipients
  in 3rd person); verify-before-claim (unsourced facts get an explicit caveat).
- **Accessibility + reduced-motion + print** are part of "done", not extras. For a
  running model, reduced motion and print mean the **computed end state**, not a
  stopped or empty one.

> A clean flat page also happens to import reasonably into Figma — that's a side
> benefit of good markup, **not** a mode or a constraint. See the optional note in
> `references/build-workflow.md` if a specific deliverable is meant for Figma.
