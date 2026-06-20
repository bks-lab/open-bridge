---
scope: core
description: Cross-skill gates for generated visual deliverables — theme toggle on every HTML page, every figure carries its source
---

# Visual Output — gates for generated deliverables

Any skill that emits a user-facing visual deliverable (HTML pages, slide
decks, dashboards, reports) obeys these gates — on top of the palette,
typography, and spacing tokens in [`../DESIGN.md`](../DESIGN.md). `DESIGN.md`
governs *how it looks*; this rule governs *two behaviours it must have*. The
gates apply to **every** such deliverable, including hand-built ones — not
only the output of `html-slides`, `creative-design-stack`, or `bridge-dashboard`.

## Gate 1 — every HTML page has a user-selectable light/dark toggle

A silent `@media (prefers-color-scheme)` is **not enough**. Every HTML
presentation or page ships a manual override the user can flip, with the OS
preference as the fallback. Beamers and foreign screens are unpredictably
bright or dark; control belongs *in the deck*, reachable mid-talk.

Required pattern (same one baked into `html-slides`):

1. **Inline head script before the CSS** — sets the theme class from
   `localStorage` (or OS preference) so there is no flash of the wrong theme.
2. **`:root.theme-light` / `:root.theme-dark` overrides** plus a media-query
   fallback gated on `:not(.theme-dark):not(.theme-light)` — so the manual
   choice always wins and the OS preference applies only when none is set.
3. **A toggle control top-right** (sun/moon SVG), a **`T` key binding**, and
   **`localStorage` persistence** of the choice.

`html-slides`, `creative-design-stack`, and `html-canvas` emit this
automatically. A hand-built page must copy the same three pieces. An existing
deck without it gets patched retroactively on request.

## Gate 2 — every figure carries its source

Every figure, metric, amount, or market value in a deliverable carries
**where it came from** — a concrete document path or a named market source,
not a bare number. Provenance is the point: the reader (and a later session)
must be able to trace any number back.

- **Markdown** — tables get a **source column** (short tags like `contract` /
  `summary` plus a legend listing the file paths), or a `**Sources:**` line.
- **HTML dashboards** — the same figures appear here too, **not only in the
  Markdown**: a facts / key-figures section with a `.src` "Sources:" line
  carrying the document paths or links.
- **Web-researched values** (e.g. a market value) always carry source + year
  + range, and the "asking price ≠ sale price" caveat where relevant.

The HTML surface is not optional: if a deliverable has a Markdown version with
sourced figures, the HTML dashboard reproduces them — the user wants the
key figures visually at hand, not buried in Markdown prose.

## Related

- [`../DESIGN.md`](../DESIGN.md) — palette, typography, spacing tokens (read before generating any visual)
- `feedback_no_google_fonts_only_open` (memory) — never embed Google Fonts in generated HTML/email/slides/PDF
