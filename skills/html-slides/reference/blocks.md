# Blocks: html-canvas sections on a slide

Read this when a slide should look like a canvas page: a KPI row, a comparison
matrix, a timeline, a swimlane, a decision, a glossary. The blocks are the section
catalog of `html-canvas` (`html-canvas/references/sections.md`, CSS in
`html-canvas/assets/sections.css`, behaviour in `html-canvas/assets/sections.js`);
a deck uses them as they are, never a copy.

## Build with blocks

```bash
python3 skills/html-slides/scripts/new-deck.py --title "Quarterly review" --out deck.html \
    --blocks kpi-row,matrix,timeline [--slides slides.html]
python3 skills/html-slides/scripts/new-deck.py --list      # every block, and which a deck refuses
```

- `--blocks a,b` takes block names, `--blocks all` every block a deck can hold.
  Requirements resolve as in `new-page.py` (`decision-page` brings `table`, `matrix`,
  `callout`, `doc-header`), each block's CSS once.
- Without `--slides` the deck gets its title slide and one sample slide per block:
  the catalog markup under a `slide__label`, in a `div.blk`, the slide marked
  `data-sample`. Write the content and drop the attribute; until then the send gate
  (`verify-page.py` without `--allow-sample`) fails. With `--slides` no sample slide
  is added: the deck gets the CSS and script, the slides use the markup.
- The deck records the set (`/* blocks: a, b */`), so `--refresh` keeps the block CSS
  current with html-canvas. `--refresh --blocks c,d` swaps the set of a deck built
  with `--blocks`; the slides are not touched.

## What a deck refuses

| Block | Why | Use instead |
|---|---|---|
| `hero` | the title slide opens a deck | slide type 1 (Title) |
| `section-opener` | its rule styles every `<section>`, so every slide | slide type 2 (Section Divider) |
| `section-nav`, `toc`, `index` | the deck has its own navigation and overview | keys, dots, counter; slide type 10 (Overview) |
| `print` | the engine prints one slide per page | nothing to do |

Named, they are refused with this reason; `--blocks all` leaves them out and says so.
The canvas animation layer (`animations`, which `message-flow` requires on a page)
never reaches a deck: its `.reveal` would fight the engine's. `--blocks message-flow`
adds the `motion` module instead, which runs the flow while its slide is on screen
(`reference/modules.md` § Module: motion).

## Tokens: one block, every preset

A block reads the canvas token names; the region opens with an alias layer that maps
them onto the deck tokens, on `:root` and on every `.slide`:

| Canvas | Deck |
|---|---|
| `--ink`, `--on-surface`, `--heading` | `--text` (`--heading` only for a style preset; the design preset keeps its own) |
| `--muted` | `--text-dim` |
| `--raised`, `--surface-subtle` | `--surface` |
| `--surface-muted` | `--surface2` |
| `--line`, `--line-subtle`, `--line-strong` | `--border`, `--border`, `--border-bright` |
| `--accent-text`, `--accent-line`, `--secondary` | `--accent` |
| `--accent-soft`, `--accent-subtle` | `--accent-dim` |
| `--ok`, `--ok-text`, `--warn`, `--danger`, `--info` | `--green`, `--green`, `--amber`, `--red`, `--cyan` |
| `--on-primary` | `--bg` for a style preset; the design preset keeps the brand's |
| `--radius-*`, `--shadow-*` | fixed radii, no resting shadow |

So the same block follows a style preset and the design preset, light and dark, and
holds no colour of its own. A deck's own CSS that targets a block uses the deck
tokens, in a `<style>` of its own (`reference/deck-build.md`).

## A block slide

```html
<section class="slide slide--content">
  <p class="slide__label"><span data-de>Kennzahlen</span><span data-en>Metrics</span></p>
  <h2 class="slide__heading">Where the quarter landed</h2>
  <div class="blk">
    <div class="metrics">
      <div class="metric"><div class="m-label">Runs</div><div class="m-val"><span data-count="1200">1200</span></div></div>
      <div class="metric"><div class="m-label">Failures</div><div class="m-val">3</div></div>
    </div>
  </div>
</section>
```

- One block per slide, a heading above it that says what the block shows. A label is
  optional; the sample slides carry the block's name there.
- `div.blk` is the wrapper; on a slide it has no page margin and spans the slide.
  Two blocks on one slide keep their distance on their own.
- The fit rules in the region keep a block on a 16:9 slide: tables and diagrams lose
  their page minimum width, the terminal sets its text in the deck's code colours,
  and a decision page closes up its gaps.
- Motion (`--with motion`): `data-count` on a number, `data-stagger` on a row of
  cards, `data-draw` on a diagram.
- Glossary: terms in any slide (`<a href="#gl-key" data-term="key">`) open the
  definition as a popover over the slide, in the slide view and in the reading view;
  the list itself goes on a closing slide. `alt-table` switches chart and table on
  the slide. Both follow the language switch (key L).

## Density

The limits in `reference/rules.md` hold for a block slide too, and a block made for a
page holds more than a slide shows at a glance:

| Block | On one slide |
|---|---|
| `kpi-row` | up to 4 metrics |
| `matrix`, `table` | up to 6 rows and 5 columns; more goes to an appendix slide or `alt-table` |
| `timeline` | up to 5 rows |
| `swimlane`, `ladder` | 3 lanes or bands |
| `pipeline`, `c4-boxes` | up to 5 boxes |
| `kanban` | 3 columns, 3 cards each |
| `decision-page` | fits as sampled (3 options, 3 criteria, 2 open points); beyond that split it: options and criteria on one slide, recommendation and open points on the next |
| `glossary` | up to 6 entries per slide |

`verify-page.py deck.html --deck` measures every slide at 1280x720 and 1920x1080
(`slide-overflow`); a block slide that overflows is split, never shrunk below the
deck's type sizes.
