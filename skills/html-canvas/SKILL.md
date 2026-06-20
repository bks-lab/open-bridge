---
name: html-canvas
description: >-
  Build rich, polished SINGLE-FILE HTML deliverables — explainers, reference
  pages, concept/architecture visualizations, use-case kits, multi-section
  documents — with a light/dark theme toggle, a DE/EN language toggle, tasteful
  animations, and DESIGN.md-driven tokens, all offline with zero dependencies.
  Use whenever the user wants content turned into a good-looking HTML page or kit,
  or says 'create an HTML page', 'visualize this as HTML', 'explainer', 'html kit',
  'single-file html', 'html with light and dark', 'theme toggle',
  'language toggle', 'analyze this repo as an explainer' — even if unnamed. Ships a
  copy-paste shell, a section-block catalog, an animation layer, optional JS
  behaviours, a DESIGN.md→CSS token generator, and a parallel-builder workflow.
  NOT for live Bridge ops dashboards (bridge-dashboard), repo/ecosystem maps
  (bridge-explorer), or slide decks / styled emails / PDFs / marketing
  landing pages (use the dedicated skills if your Bridge ships them).
metadata:
  scope: core
  version: 1.0.0
  last_updated: 2026-06-01
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

**One page:** copy `assets/shell.html` → fill the `{{placeholders}}` → compose
`<main>` from the blocks in `references/sections.md` → add behaviours from
`references/interactivity.md` and motion from `assets/animations.css` if wanted.
Render light **and** dark, DE **and** EN, then file under
`work/tasks/<slug>/deliverables/`.

**A kit (many pages/boards):** use the parallel-builder workflow in
`references/build-workflow.md` — one convention audit emits a shared shell, N
builders run concurrently on it, one adversarial reviewer checks every page, then
integrate + write an index launcher. This is how the 12-board sets get built
consistently.

**Tokens:** regenerate the CSS variable layer from the design system with
```bash
python3 skills/html-canvas/scripts/design-to-css.py --out /tmp/tokens.css
```
and paste it over the shell's brand-token block. Never hand-pick a brand colour;
if a token is missing, add it to `DESIGN.md` first, then regenerate.

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
| `references/repo-analysis.md` | Repo/doc → Architecture-Spec → sections: doc-scan + offered subagent fan-out + spec→block mapping | Building an architecture explainer from a repo |
| `scripts/repo-scan.py` | Deterministic repo inventory (languages, entry points, deps, docs) — the factual seed | Before analyzing any repo |

## Non-negotiables (full list in `references/build-workflow.md`)

- **No Google Fonts / any third-party font CDN** — GDPR. System-stack Inter or a
  data-URI-inlined woff2.
- **DESIGN.md is the colour SoT** — tokens only, never hand-picked hex. "large =
  light" (headings ≥24px → weight 300). Accent gradient only on 1–2 accent words +
  the wordmark; never the cyan→purple-on-text AI-slop tell.
- **Colour = meaning, not decoration** — neutral chrome + one indigo accent;
  semantic lens/actor colours are the only exception and always ship a legend;
  status reads by shape (`● ◐ ✗ –`) first.
- **SOUL.md voice** — no hero-arc/hype/slogans; the user is the sender (recipients
  in 3rd person); verify-before-claim (unsourced facts get an explicit caveat).
- **Accessibility + reduced-motion + print** are part of "done", not extras.

> A clean flat page also happens to import reasonably into Figma — that's a side
> benefit of good markup, **not** a mode or a constraint. See the optional note in
> `references/build-workflow.md` if a specific deliverable is meant for Figma.
