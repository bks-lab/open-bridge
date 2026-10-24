# Deck Build: generator, regions, presets

Read this when building, refreshing or restyling a deck, or when writing a preset.
`scripts/new-deck.py` is the only supported way to assemble a deck; this file says
what it writes and why.

## The command

```bash
python3 skills/html-slides/scripts/new-deck.py --title "Quarterly review" --out deck.html \
    [--slides slides.html] [--preset SLUG] [--design DESIGN.md] [--lang en|de] \
    [--with-stage] [--deck-attr data-NAME=VALUE ...] [--no-embed-fonts] [--force]

python3 skills/html-slides/scripts/new-deck.py --refresh deck.html [--out other.html] \
    [--preset SLUG] [--design DESIGN.md] [--embed-fonts | --no-embed-fonts]
```

`--slides` is an HTML fragment of `<section class="slide ...">` elements
(`reference/slide-types.md`). An existing `--out` is refused unless `--force`.
`--deck-attr` puts an engine option on the deck element (`data-tracks-default=short`,
`data-back-href=page.html`, `data-counter-format=padded`; the list is the Engine
Contract in `reference/slide-types.md`). It is a build flag: the deck element lies
outside the marker regions, so a refresh keeps whatever it carries.

The DESIGN.md lookup stops at the project root (the first folder above the output
with `.git` or `bridge-config.yaml`); without one only the output folder counts, so
a stray DESIGN.md in a temp or home folder never brands a deck. `--design` names it
outright, and every run prints which one it used.
Every splice is read back and compared before the file is written.

## Marker regions

A deck holds two kinds of text. The slides belong to the author. Everything else
is generated and lives in a region the tool owns,
`<!-- NAME:start -->CONTENT<!-- NAME:end -->`:

| Region | Where | Holds |
|---|---|---|
| `deck-prepaint` | `<head>` | the pre-paint theme script (sets `.theme-light` / `.theme-dark` before the first paint) |
| `deck-fonts` | `<head>` | base64 `@font-face` rules from `html-canvas/scripts/embed-fonts.py` |
| `deck-tokens` | `<style>` | colour and font variables; the first line names the preset (`/* deck-preset: <slug> */`) |
| `slide-engine:css` | `<style>` | `assets/slide-engine.css`, byte for byte |
| `deck-preset-css` | `<style>` | the preset's `css_overrides` |
| `slide-stage:css` | `<style>` | `assets/slide-stage.css`, only with `--with-stage` |
| `slide-engine:js` | `<body>` | `assets/slide-engine.js`, byte for byte |
| `slide-stage:js` | `<body>` | `assets/slide-stage.js`, only with `--with-stage` |

The engine assets carry a version stamp on their first line (`slide-engine v2`),
so an old copy is recognisable without a diff.

Inside a stylesheet CSS skips only the `<!--` and `-->` of a marker, not the name
between them, so the name would glue onto the next selector and void that rule.
Every region inside `<style>` therefore opens with an empty rule `{}` that
swallows it. **Deck-specific CSS goes into a second `<style>` element of its own**,
never inside a region and never directly after a region's end marker.

## Refresh

`--refresh deck.html` rewrites only the regions a deck already carries, from the
current assets, DESIGN.md and preset. Text outside them is never touched, no
region is added, and a second run gives the same bytes. The preset is read back
from the `deck-preset` comment unless `--preset` names another. Use it after an
engine update, a DESIGN.md change, or to restyle a deck.

A deck without markers predates the generator. It keeps working (its engine is
embedded), and the engine reads its old names (`data-spur`, `window.slideEngine`,
`window.__slideEngine`). To bring it up to date, build a fresh deck with its
slides as `--slides`; the compatibility fixtures under `tests/fixtures/compat/`
show which old patterns stay supported.

## Presets

**Choice:** `--preset` when given; else `design` when a DESIGN.md is given
(`--design`) or found walking up from the output path; else the style preset
marked `default: true`. On `--refresh` the preset is read back from the deck.

**`design`** holds no colour and names no typeface. Colours come from DESIGN.md
through `presets/design.map.yaml` and `html-canvas/scripts/design-to-css.py`
(`--map`, `--selectors`, `--region deck-tokens`; the adapter is documented in
`html-canvas/references/theme-contract.md`); families and weights come from the
DESIGN.md typography roles. Decoration (gradient zones, backdrop blur) shows only
behind the class `fx`, see `reference/rules.md`.

**Style presets** carry their own palette and fonts in YAML. They are for a deck
that should not wear the house brand, and the fallback without DESIGN.md. The
tokens a style preset defines, per mode (`colors.dark`, `colors.light`):

```
bg surface surface2 surface-elevated border border-bright text text-dim
accent accent-dim code-bg code-text green green-dim red red-dim
amber amber-dim cyan cyan-dim
```

The generator writes them as dark defaults on `:root`, light on `:root.theme-light`,
and light again under `@media (prefers-color-scheme: light)` for
`:root:not(.theme-dark):not(.theme-light)`. The light rules appear twice on
purpose: once for the explicit choice, once as the OS fallback.

**Writing a preset:** read `presets/_template.yaml` for the schema; the tests in
`tests/test_presets.py` enforce it, and only one preset may be `default: true`. To
derive one from a design reference, extract fonts and colours and fill the
template. A new font family needs its woff2 files and licence under
`assets/fonts/` first.

## Theme

The engine keeps the deck's own contract: `.theme-dark` or `.theme-light` on
`<html>`, the choice stored as `slide-theme` in `localStorage` (every access in
`try`/`catch`), the OS preference while nothing is stored, key T and the toggle
button to switch. The pre-paint region applies it before the first paint. The
general rule set, and the `.dark` class every other HTML skill uses, is
`html-canvas/references/theme-contract.md`.

## Fonts

Embedded by default, because a style preset depends on its typefaces. Every
weight a preset names is embedded as its real cut, never synthesised; a weight
with no file is reported on stderr. `--no-embed-fonts` leaves the region holding a
comment and the deck on its fallback stacks; on `--refresh`, `--embed-fonts` adds
fonts to a deck that had none. A preset whose roles are all `system_only: true`
has nothing to embed. `scripts/font-face.py <slug>` prints the same block on its
own. Fonts are found in this skill's `assets/fonts/`, then in html-canvas's
bundled fonts.
