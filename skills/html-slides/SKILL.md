---
name: html-slides
description: >-
  Builds single-file HTML slide decks from any content: DESIGN.md brand or a style preset, light/dark, embedded fonts, tracks, speaker notes, live stages, offline; PDF export, a quality gate and an anonymity check before sending. Trigger: "create a presentation", "make slides", "slide deck", "html slides", "PowerPoint alternative", "/slides".
metadata:
  scope: core
  version: 2.1.0
  last_updated: 2026-10-24
---

# HTML Slide Deck Generator

Single-file HTML presentations: a scroll-snap engine with keyboard, tracks,
speaker notes and deep links, the Bridge's DESIGN.md brand or one of
10 style presets, light and dark, fonts embedded, nothing fetched from a network. The
foundation (tokens, fonts, the quality gate, the send bundle) is shared with
`html-canvas` and called from there, never copied: this skill needs
`skills/html-canvas/` next to it.

## Decision tree

| The request | Do this | Read |
|---|---|---|
| A new deck | `scripts/new-deck.py` (Build path below) | `reference/slide-types.md`, `reference/rules.md` |
| Bring an existing deck up to date: newer engine, changed DESIGN.md, other preset | `new-deck.py --refresh deck.html` | `reference/deck-build.md` |
| Edit the slides of an existing deck | edit them by hand (outside the marker regions), then the gate | `reference/slide-types.md` |
| A different cut of one deck (prep vs. live, short vs. long) | `data-track` on slides, key F | `reference/slide-types.md` § Engine Contract |
| Speaker notes, a clickable agenda | `<aside class="notes">`, slide type 10 (Overview) | `reference/slide-types.md` |
| A running simulation inside a slide | `new-deck.py --with-stage`, a `.stage` element | `reference/stage.md` |
| Presenting live: blank screen, jump to a slide number, zoom, language switch, notes handout | built in: keys B / W, digits + Enter, Alt+click, L, `data-print-notes` | `reference/slide-types.md` § Engine Contract |
| An optional deck feature (one of the 5 modules below) or writing one | `new-deck.py --with NAME` (or `--with all`), `SlideDeck.use()` | `reference/modules.md` |
| A presenter view on a second screen, a time budget per slide, a rehearsal with plan vs actual | `--with presenter`, `data-time="90"` on slides, key P | `reference/modules.md` § Module: presenter |
| Point at or mark up a slide while presenting: laser pointer, pen, marker | `--with draw`, keys Q and D | `reference/modules.md` § Module: draw |
| Reveal points one by one, walk through code line by line | `--with steps`, `data-step`, `data-lines` | `reference/modules.md` § Module: steps |
| Morph an element from one slide to the next | `--with morph`, `data-morph="name"` | `reference/modules.md` § Module: morph |
| A deck handed over to be read, not presented: every slide with its notes as one document | `--with read`, key R; a send copy opens in it with `--deck-attr data-read-default=` | `reference/modules.md` § Module: read |
| Pick a look | DESIGN.md (default) or a style preset by name | `reference/deck-build.md` § Presets |
| A deck in no house brand, or no DESIGN.md exists | `--preset <slug>` | `presets/_template.yaml`, `assets/discovery-menu.html` |
| PDF, mail, customer, external | the send path below | `reference/output-formats.md` |
| A new style preset | fill `presets/_template.yaml` | `reference/deck-build.md` § Presets |
| A page to read, not a deck to present | use `html-canvas` instead | |

## Build path: generator first

Never hand-assemble a deck. The generator writes every generated part between
markers, asserts each splice, and keeps the deck refreshable.

```bash
python3 skills/html-slides/scripts/new-deck.py --title "Quarterly review" --lang en \
    --slides slides.html --out work/tasks/<slug>/deliverables/deck.html
```

1. **Plan the content** against the density limits in `reference/rules.md`:
   title, sections, content slides, closing. Split, never cram.
2. **Write the slides** as one HTML fragment of `<section class="slide ...">`
   elements, from the 11 slide types in `reference/slide-types.md`. Without
   `--slides` the deck gets one title slide to fill in.
3. **Generate** with `new-deck.py`. Engine options (tracks, counter format, back
   link) go on the deck element with `--deck-attr data-NAME=VALUE`. It splices the pre-paint theme script, the
   embedded fonts, the tokens, `assets/slide-engine.css` and `assets/slide-engine.js`
   (first line `slide-engine v2`), plus the stage module with `--with-stage` and
   each deck module named by `--with` (`reference/modules.md`).
   `--lang de` localises the controls, the help and the ARIA texts.
4. **Run the gate** (Definition of done), then open the file in the browser.

**Updating an existing deck:** `new-deck.py --refresh deck.html` rewrites only the
marker regions the deck already carries (engine, tokens, fonts, preset CSS, stage, modules)
from the current assets, DESIGN.md and preset. The slides are never touched, and a
second run gives the same bytes. A deck from before the generator has no markers:
leave it as it is (its engine is embedded and keeps working), or move its slides
into a fresh `new-deck.py --slides` build. Details: `reference/deck-build.md`.

## Look: DESIGN.md first, style presets as fallback

- **DESIGN.md wins.** When one is found walking up from the output path, or given
  with `--design`, the `design` preset is the default: colours through
  `presets/design.map.yaml` and `html-canvas/scripts/design-to-css.py`, families and
  weights from DESIGN.md typography. Nothing is hand-picked. The preset also holds
  the brand rules a slide's markup cannot break: headings in the heading colour,
  status colours for state only (a chapter colour or glow from a snippet gives
  way), 1px lines, code in the mono family on the muted surface, no shadow or
  texture. `.fx` on `<html>`, the deck or a slide brings the decoration back.
- **Style presets** (`--preset swiss-modern` and the others) are for a deck that
  should not carry the house brand, and the fallback without DESIGN.md (the one
  marked `default: true`). Offer the picker `assets/discovery-menu.html` when the
  user wants to choose; no answer means the default.
- **Theme contract:** the engine keeps `.theme-dark` / `.theme-light` on `<html>`,
  stored as `slide-theme`, the OS preference while nothing is stored, key T
  toggles. The shared rule set is `html-canvas/references/theme-contract.md`.
- **Fonts are embedded by default** (style presets depend on their typefaces);
  `--no-embed-fonts` leaves the deck on its fallback stacks. A send copy always
  embeds.

## Definition of done

`verify-page.py` from html-canvas is the gate. Exit 0 is done; a requested browser
pass that cannot run is an error, not a pass.

```bash
V=skills/html-canvas/scripts/verify-page.py
python3 $V deck.html --design DESIGN.md   # always: no external or sibling file, no placeholder, no stray hex
uv run --with playwright python $V deck.html --design DESIGN.md --deck   # before delivery: renders it,
                                          # contrast per theme, overflow per slide, one print page per slide
```

Pass the same `--design` the deck was built with. Without it the gate takes the
nearest DESIGN.md at or above the deck, but never above the project root (the
first folder with `.git` or `bridge-config.yaml`), and says which one it used.
A deck built from another DESIGN.md gets a `design-source` warning. `--deck`
needs playwright and its chromium; a bare `python3` without them fails as
`browser-skipped`.

A style preset deck is off brand by definition: while a DESIGN.md is in reach,
the gate reports its preset colours as `hex` errors. That is the one known
exception; every other finding gets fixed.

## Send path

| Trigger | Action |
|---|---|
| "send to customer", "external", "check before sending" | `scripts/check-anonymity.py deck.html`, resolve every hit (exit 1 on hits) |
| "as PDF", "print", "attachment" | `node scripts/render-pdf.cjs deck.html deck.pdf [--theme light]`, one 16:9 page per slide |
| The deck loads local files (images, a stage page next to it) | `scripts/inline-assets.py deck.html deck-send.html`, which runs the shared `html-canvas/scripts/bundle.py` |
| Mail the deck | anonymity check, gate, bundle, PDF, then check the bundled copy again |

An instance names its own wordlist in `bridge-config.yaml` under
`html_slides.anonymity_wordlist`, never in this skill. Order and options:
`reference/output-formats.md`.

## Files

| File | Read it when |
|---|---|
| `scripts/new-deck.py` | building or refreshing any deck |
| `reference/deck-build.md` | marker regions, preset choice, fonts, refresh, writing a preset |
| `reference/slide-types.md` | writing slides; the Engine Contract (options, keys, API) |
| `reference/rules.md` | planning content: the DESIGN.md rule, anti-slop list, density limits |
| `reference/stage.md` | a live simulation inside a slide |
| `reference/modules.md` | deck modules: `--with`, the plugin API `SlideDeck.use()`, writing and testing one |
| `reference/output-formats.md` | PDF, bundle, anonymity check, the package to send |
| `presets/_template.yaml` | the preset schema, before writing one |
| `assets/slide-engine.css`, `assets/slide-engine.js` | extending the engine (then add a test) |
| `assets/slide-stage.css`, `assets/slide-stage.js` | extending the stage (same) |
| `assets/modules/` | the deck modules (`draw`, `morph`, `presenter`, `read`, `steps`), one `.js` and `.css` each |
| `assets/fonts/`, `scripts/font-face.py` | preset fonts (woff2 plus OFL licences) |
| `scripts/check-anonymity.py`, `scripts/render-pdf.cjs`, `scripts/inline-assets.py` | the send path |

## Tests

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --with pytest --with pyyaml --with playwright \
    python -m pytest skills/html-slides/tests -q -rs
```

Browser tests need playwright and its chromium and skip without them; the
render-pdf tests also need node playwright. Changing the engine, a preset or a
count in these docs means running them; `tests/test_docs.py` holds the counts to
the tree.
