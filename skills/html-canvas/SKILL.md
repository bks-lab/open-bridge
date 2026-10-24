---
name: html-canvas
description: >-
  Builds single-file HTML documents: explainers, reference pages, architecture visualizations, light/dark and DE/EN toggles, DESIGN.md tokens. Also running models: simulations with a clock. NOT marketing pages or ops dashboards (creative-design-stack), not ecosystem maps (bridge-explorer). Trigger: "create an HTML page", "explainer", "html kit", "theme toggle", "simulate this".
metadata:
  scope: core
  version: 1.2.0
  last_updated: 2026-10-24
---

# html-canvas

Rich **single-file HTML** that reads well, themes light/dark, switches DE/EN and
takes every colour from DESIGN.md: explainers, reference kits, concept and
architecture pages, decision pages, multi-section docs, and simulations that run.
One file, offline, no external dependency, native UTF-8.

This skill also owns the **shared foundation** every HTML skill calls instead of
copying: tokens (`scripts/design-to-css.py`), font embedding
(`scripts/embed-fonts.py`), the quality gate (`scripts/verify-page.py`), the send
bundle (`scripts/bundle.py`) and the theme contract
(`references/theme-contract.md`). `html-slides` builds its decks on them.

## Decision tree

| The request | Do this | Read |
|---|---|---|
| One page (explainer, reference, decision page) | `scripts/new-page.py` (Build path below) | `references/sections.md` |
| Bring an existing page up to date (tokens, fonts, block CSS, language rules) | `new-page.py --refresh page.html` | Build path |
| Something that has to RUN (a queue, a gate, a plan step by step) | `scripts/new-simulation.py` | `references/simulation.md` |
| Many pages that must look like one set | the parallel-builder workflow | `references/build-workflow.md` |
| An architecture explainer from a repo or its docs | `scripts/repo-scan.py`, then the playbook | `references/repo-analysis.md` |
| Behaviour on a page: reveal, count-up, filter, scrollspy | paste the snippet | `references/interactivity.md` |
| A deck to present | use `html-slides` | |
| Send, mail, attach, download folder | `scripts/bundle.py` (Send path below) | |
| Another skill's HTML needs the brand or the theme switch | `design-to-css.py --map/--selectors/--region` | `references/theme-contract.md` |
| An old page with the previous language swap | migrate in place | `references/build-workflow.md` § Migrating |

## Build path: generator first

Never hand-copy `assets/shell.html`: its token region is neutral on purpose.

```bash
python3 skills/html-canvas/scripts/new-page.py --list
python3 skills/html-canvas/scripts/new-page.py --title "Option review" --lang de \
    --blocks doc-header,decision-page,callout --out work/tasks/<slug>/deliverables/review.html
```

That writes one offline file: the shell, the DESIGN.md tokens, the example markup
of each requested block from the 26 blocks in `references/sections.md`, and the CSS
of those blocks once (from `assets/sections.css`). It then runs the static gate and
exits non-zero on errors. Replace the example content, keep the structure.

**Updating an existing page:** `new-page.py --refresh page.html` re-renders only the
marked regions (`design-tokens`, `page-fonts`, `sections`) and normalises the DE/EN
swap rules; `<main>` and every hand-written rule stay. `--blocks` on a refresh swaps
the block set. A page from before the generator has no regions: edit it in place.

**A simulation** is assembled the same way and then only its `MODEL` block is edited:

```bash
python3 skills/html-canvas/scripts/new-simulation.py --archetype flow --lang de \
    --title-de "…" --title-en "…" --out work/tasks/<slug>/deliverables/run.html
```

Two archetypes are built and runnable: `flow` (an SVG stage with routes, stations,
queues, a gate) and `worklist` (a plan executed step by step). *console*, *dossier*
and *exchange* are **not built**: `references/simulation.md` describes them as deltas
from those two, to derive by hand when one is needed. There is no `--refresh` for a
simulation; edit it in place. A simulation can run live inside a slide
(`html-slides`, stage contract in `references/simulation.md`).

## The controls every page ships

Baked into the shell, never reinvented:

1. **Light / dark:** the class `dark` on `<html>`, button and key T, stored as
   `html-canvas-theme`, pre-paint in `<head>`, OS preference while nothing is
   stored. The rule set for every HTML skill: `references/theme-contract.md`.
2. **DE / EN:** button and key L. Every translatable run ships as `data-de` /
   `data-en` siblings and the swap is pure CSS. Default is the conversation
   language; repo- or OSS-shipped pages stay English.
3. **Print / PDF:** chrome hidden, reveals visible, a light palette on paper. A page
   that runs prints its **computed end state**.

## Look: DESIGN.md first

DESIGN.md is the only source of colour and type: `design-to-css.py` fills the token
region, everything else derives through `var()` and `color-mix()`. Never pick a
brand colour by hand; a missing token goes into DESIGN.md first. Without a DESIGN.md
the shell keeps CSS system colours.

**Fonts are optional for a page:** off by default, the page uses the platform stack
DESIGN.md names. `new-page.py --embed-fonts` (or `design-to-css.py --embed-fonts`)
embeds the typefaces as base64 from `assets/fonts/` (Inter, Playfair Display,
JetBrains Mono, so a page matches a deck without `--font-dir`) and any `--font-dir`.
Never a font CDN. The send bundle always embeds.

Every script finds DESIGN.md the same way: the nearest one at or above the page,
never above the project root (the first folder with `.git` or `bridge-config.yaml`);
without such a folder only the page's own folder counts. `--design` names it outright.

## Definition of done

`verify-page.py` is the gate; exit 0 is done, and a requested browser pass that
cannot run is an error, not a pass.

```bash
V=skills/html-canvas/scripts/verify-page.py
python3 $V page.html              # always: external or sibling refs, placeholders, sample text, entities, hex, DE/EN pairs, anchors
python3 $V page.html --browser    # before delivery: opened alone from an empty folder, light/dark x de/en, contrast, reduced motion, print
python3 $V deck.html --deck       # a deck: also overflow per slide and one print page per slide
```

`--browser` and `--deck` need playwright and its chromium (`uv run --with playwright
python $V ...`); without them the run fails as `browser-skipped`. Contrast is read
from the colours behind the text and, where a gradient, an image or a sibling layer
(a scrim) sits behind it, from a screenshot with the text hidden. The text output
names the DESIGN.md it checked against, and a page generated from another one gets
a `design-source` warning.

**Sample text:** `new-page.py` marks every block it inserts with `data-sample`, and
the catalog's stand-in content is a bare `…`. The gate fails both (`sample`) until
the text is written and the attribute dropped; `new-page.py` itself runs the gate
with `--allow-sample`, so a fresh skeleton passes with a warning.
What the gate cannot see (touch targets, focus order, voice) is the checklist in
`references/build-workflow.md`. A dark mode that is not `html.dark`, `.theme-dark`
or `[data-theme="dark"]` is named with `--dark-selector`.

## Send path

```bash
python3 skills/html-canvas/scripts/bundle.py page.html --out page-send.html [--pages]
```

Folds everything the page loads into one file: images, stylesheets, scripts, fonts
(always embedded), iframes as UTF-8 safe base64 payloads, and with `--pages` linked
local pages. Remote resources are refused unless `--allow-remote`; nothing is written
until every reference resolves; a sha256 per source goes to stderr or `--manifest`.
Run the gate on the bundled copy.

## Non-negotiables (full bar in `references/build-workflow.md`)

- **No Google Fonts or any font CDN** (GDPR): embedded woff2 or the system stack.
- **DESIGN.md is the colour source**, tokens only; a gradient on text or fill is
  never a default.
- **Colour means something:** neutral chrome plus the brand accent; semantic
  colours ship a legend; status reads by shape (`● ◐ ✗`) first.
- **SOUL.md voice:** no hero arc, hype or slogans; the user is the sender;
  unsourced facts carry a caveat.
- **Accessibility, reduced motion and print** are part of done. For a running model
  they mean the computed end state, not an empty stage.

## Files

| File | Read it when |
|---|---|
| `scripts/new-page.py`, `assets/sections.css` | building or refreshing a page |
| `references/sections.md` | composing `<main>`: the block catalog |
| `scripts/verify-page.py` | the gate, for pages and decks |
| `scripts/bundle.py` | the send copy |
| `scripts/design-to-css.py` | tokens, also for other consumers (`--map`, `--selectors`, `--region`) |
| `scripts/embed-fonts.py`, `assets/fonts/` | embedding typefaces (woff2 plus OFL licences) |
| `references/theme-contract.md` | the light/dark contract every HTML skill follows |
| `references/build-workflow.md` | multi-page kits, the quality bar, the pre-delivery checklist, migrating old pages |
| `references/interactivity.md` | optional behaviours (reveal, count-up, filter, hydration, scrollspy) |
| `assets/animations.css` | optional motion, gated on reduced motion |
| `references/simulation.md` | running models: archetypes, engine API, honesty rules, stage contract |
| `scripts/new-simulation.py`, `assets/sim-engine.js`, `assets/simulation.css` | assembling and extending a simulation |
| `assets/sim-flow.html`, `assets/sim-worklist.html` | the two runnable archetype fragments |
| `references/repo-analysis.md`, `scripts/repo-scan.py` | an architecture explainer from a repo |
| `assets/shell.html` | the skeleton the generators start from |

## Tests

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --with pytest --with pyyaml --with playwright \
    python -m pytest skills/html-canvas/tests -q -rs
```

Browser tests need playwright and its chromium and skip without them. Every rule the
gate enforces has a broken fixture that must fail and a clean one that must pass.
