# Deck Build: generator, regions, presets

Read this when building, refreshing or restyling a deck, or when writing a preset.
`scripts/new-deck.py` is the only supported way to assemble a deck; this file says
what it writes and why.

## The command

```bash
python3 skills/html-slides/scripts/new-deck.py --title "Quarterly review" --out deck.html \
    [--title-de "Quartalsbericht" --title-en "Quarterly review"] \
    [--slides slides.html] [--preset SLUG] [--design DESIGN.md | --context NAME | --persona ID] \
    [--lang en|de] [--with-stage] [--with NAME ... | --with all] [--blocks a,b | --blocks all] \
    [--deck-attr data-NAME=VALUE ...] [--no-embed-fonts] [--force] [--no-verify]

python3 skills/html-slides/scripts/new-deck.py --refresh deck.html [--out other.html] \
    [--preset SLUG] [--design DESIGN.md | --context NAME | --persona ID] [--blocks a,b] \
    [--embed-fonts | --no-embed-fonts] [--no-verify]

python3 skills/html-slides/scripts/new-deck.py --list    # presets, modules, blocks
```

`--title-de` and `--title-en` put both languages on the title slide (a
`data-de` / `data-en` pair the engine switches with L); `<title>` takes the one of
`--lang`. `--title` alone serves both.

`--slides` is an HTML fragment of `<section class="slide ...">` elements
(`reference/slide-types.md`). An existing `--out` is refused unless `--force`.
`--deck-attr` puts an engine option on the deck element (`data-tracks-default=short`,
`data-back-href=page.html`, `data-counter-format=padded`; the list is the Engine
Contract in `reference/slide-types.md`). It is a build flag: the deck element lies
outside the marker regions, so a refresh keeps whatever it carries, and `--refresh`
with `--deck-attr` is refused rather than writing a copy without the option. A refresh
keeps the order of the module regions the deck already has (module order decides which
key wins and how transitions nest). The report line names the modules the deck carries.

The DESIGN.md lookup stops at the project root (the first folder above the output
with `.git` or `bridge-config.yaml`); without one only the output folder counts, so
a stray DESIGN.md in a temp or home folder never brands a deck. `--design` names it
outright, `--context` and `--persona` name it through the `design_ref` of
`workflow/contexts/<name>.yaml` or `identity/personas/<id>.yaml` (resolved by the
Bridge, `scripts/designs.py`, as `html-canvas/scripts/new-page.py` does), and every
run prints which one it used.
Every splice is read back and compared before the file is written.

**The gate runs after every build and refresh:** `html-canvas/scripts/verify-page.py`
on the written file, static, with `--allow-sample` and the design the deck wears, and
the run exits with its result (1 on an error, the file is written either way).
`--no-verify` skips it, for tests and scripted pipelines that run the gate themselves
(never for a deck that goes out). The browser pass (`--deck`) stays a separate step before
delivery.

### The recorded design

A design deck writes the design it wears into its token region, below the preset
line: `/* design-source: <id> */` for a design under `identity/designs/`, or the
path inside the Bridge for any other DESIGN.md of the Bridge. A refresh reads it
back instead of resolving afresh, so a deck built with `--design <id>` far from any
repository refreshes without `--design`; `--design`, `--context` or `--persona` on
the refresh replaces it. The gate reads the same line, so the standalone
`verify-page.py deck.html` checks against the right design and never silently
skips the hex check. A recorded label that points outside the Bridge, or at a
file that is neither under `identity/designs/` nor a `DESIGN.md`, is refused by
refresh and gate alike (pass `--design`). A DESIGN.md outside the Bridge (a target repository's own) is
not recorded: the walk up from the deck finds it again. A style preset deck records
no design.

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
| `deck-blocks` | `<style>` | only with `--blocks`: the block list (`/* blocks: a, b */`), the alias layer from the canvas token names onto the deck tokens, the CSS of the blocks and what they require, slide fit rules (`reference/blocks.md`) |
| `slide-stage:css` | `<style>` | `assets/slide-stage.css`, only with `--with-stage` |
| `slide-engine:js` | `<body>` | `assets/slide-engine.js`, byte for byte |
| `slide-stage:js` | `<body>` | `assets/slide-stage.js`, only with `--with-stage` |
| `deck-blocks:js` | `<body>` | only when a chosen block has a behaviour (`glossary`, `alt-table`): its part of `html-canvas/assets/sections.js` |
| `deck-module:NAME` | `<body>` | `assets/modules/NAME.css` in its own `<style>` (when the module has one), then `assets/modules/NAME.js`, only with `--with NAME`; one region per module, sorted by name, after the engine and the stage (`reference/modules.md`) |

The engine assets carry a version stamp on their first line (`slide-engine v2`),
so an old copy is recognisable without a diff.

Inside a stylesheet CSS skips only the `<!--` and `-->` of a marker, not the name
between them, so the name would glue onto the next selector and void that rule.
Every region inside `<style>` therefore opens with an empty rule `{}` that
swallows it. **Deck-specific CSS goes into a second `<style>` element of its own**,
never inside a region and never directly after a region's end marker.

## Refresh

`--refresh deck.html` rewrites only the regions a deck already carries, from the
current assets, DESIGN.md and preset. Text outside them is never touched, and a
second run gives the same bytes. The only region a refresh can add is
`deck-blocks:js`, when `--blocks` swaps the set for one that needs a script (below). The modules a deck carries
stay its set: their code is refreshed, none is added or dropped, and `--with` on a
refresh is refused (build the slides into a fresh deck to change the set). A module
whose file is gone is an error, and nothing is written. The preset is read back
from the `deck-preset` comment unless `--preset` names another, the design from the
`design-source` comment unless `--design`, `--context` or `--persona` names another.
The block set is read back from the `deck-blocks` region; `--blocks` on a refresh
swaps it, and is refused on a deck built without `--blocks`. Use it after an engine update, a DESIGN.md change, or to
restyle a deck.

A deck without markers predates the generator. It keeps working (its engine is
embedded), and the engine reads its old names (`data-spur`, `window.slideEngine`,
`window.__slideEngine`). To bring it up to date, build a fresh deck with its
slides as `--slides`; the compatibility fixtures under `tests/fixtures/compat/`
show which old patterns stay supported.

## Presets

**Choice:** `--preset` when given; else `design` when a DESIGN.md is given
(`--design`, `--context`, `--persona`) or found walking up from the output path;
else the style preset marked `default: true`. On `--refresh` the preset is read
back from the deck. `--list` shows every preset, the default marked.

**`design`** holds no colour and names no typeface. Colours come from DESIGN.md
through `presets/design.map.yaml` and `html-canvas/scripts/design-to-css.py`
(`--map`, `--selectors`, `--region deck-tokens`; the adapter is documented in
`html-canvas/references/theme-contract.md`); families and weights come from the
DESIGN.md typography roles. Decoration (gradient zones, backdrop blur) shows only
behind the class `fx`, see `reference/rules.md`.

**What a DESIGN.md may add for a deck.** Each part is opt-in; a design without it
builds the deck it built before.

| In DESIGN.md | The deck |
|---|---|
| colour roles `highlight`, `glow` | the arc under a heading (`.slide__arc`) in its own colour with a second, wider glow; without them the arc is the accent |
| colour role `gradient-via` | a middle stop for the gradient numbers (`--stat-gradient`), between `gradient-from` and `gradient-to` |
| `components.slide-display`, `slide-heading`, `slide-body`, `slide-label` | the type cut of that role: `fontWeight`, `letterSpacing`, `lineHeight`, from `typography: "{typography.<role>}"` and/or given directly. Sizes stay with the engine. Without them the preset's quiet cut (weight 500) stays |
| `components.slide-arc.width` | the arc's line width in px (default 1px) |
| `components.knowledge-term` | how a knowledge term looks: `html-canvas/references/knowledge.md` § Term mark |

```yaml
components:
  slide-heading: {typography: "{typography.h2}"}
  slide-body: {fontWeight: 300, lineHeight: 1.4}
  slide-arc: {width: 2px}
```

A wrong reference or value stops the build with the component's name.

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
button to switch. `new-deck.py --theme-default dark|light` writes
`data-theme-default` onto `<html>`: the deck then opens in that theme until the
viewer picks one, whatever the OS says (a brand made for the dark). The attribute
sits outside the regions, so a refresh keeps it. The pre-paint region applies it before the first paint. The
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
