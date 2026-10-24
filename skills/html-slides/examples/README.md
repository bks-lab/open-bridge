# html-slides examples

## showcase.slides.html

The slides of the showcase deck: one deck that shows every capability of
html-slides on a slide of its own, with one line on how to use it. The content is
neutral, it presents the html-slides and html-canvas skills themselves.

| Slide | Capability | How to use it |
|---|---|---|
| 1 | Title (untagged, so in every track) | `slide--title` |
| 2 | Agenda as an overview slide | `slide--overview`, tiles with `data-deck="goto:#id"` |
| 3, 8, 12, 19 | Section dividers | `slide--divider` |
| 4 | Keys and help, buttons | `?`, `data-deck="help"`, `data-deck="next"`, `.slide__btn` in `.slide__actions` |
| 5 | Deep link (track "full" only) | `deck.html#s-deeplink` (a slide id holds in every track), `#5`, `data-deep-link="off"` |
| 6 | Tracks, with German labels for the track names | key F, `data-track`, `data-tracks-default`, `data-tracks-cycle`, `data-tracks-labels` |
| 7 | Speaker notes | key N, `<aside class="notes">` |
| 9 | Theme and language | key T (light and dark from DESIGN.md), key L, `data-de` / `data-en` pairs |
| 10 | Padded counter, back link | `data-counter-format="padded"`, `data-back-href` |
| 11 | Reveal and reduced motion (track "full") | `class="reveal"` |
| 13 to 16 | Table of all eleven slide types (jumps by `goto:#id`), code with a colour legend, pipeline, card grid | `slide--table`, `slide--code`, `.pipeline`, `.cheat-grid` |
| 17 | Decision page excerpt | the html-canvas `decision-page` block, cut to options and pick |
| 18 | Terminal mockup (track "full") | `.slide__code-block` |
| 20 | Live stage with a running simulation | `.stage`, key V, `data-stage="maximize"` / `restart` |
| 21 | Print, PDF and the send path | `render-pdf.cjs`, `bundle.py` |
| 22 | Closing | `slide--bleed` |

The fragment carries one `<style>` and two small scripts of its own, all marked as
deck-specific: the swap rules for the language pairs and the language switch (key L
stores the choice and reloads, because the engine localises its controls once at
start; the engine lists L in the `?` help of a bilingual deck, and the script sets `data-tracks-labels` for the active language before the engine reads it). The deck options come from
`new-deck.py --deck-attr` in step 3. Track "short" is named only by
`data-tracks-cycle`: no slide carries it, it shows the untagged slides.

## Build

From the repository root, into a folder of your choice (`OUT`). A DESIGN.md found
above `OUT`, or given with `--design`, gives the deck its brand; without one the
default style preset applies.

```bash
OUT=work/showcase; mkdir -p $OUT/build

# 1. the simulation for the stage (archetype flow)
python3 skills/html-canvas/scripts/new-simulation.py --archetype flow --lang de \
    --out $OUT/build/showcase-sim.html

# 2. the slides plus the simulation as an inert base64 payload; the stage reads
#    data-srcdoc-ref="showcase-sim" first and falls back to data-src
{ cat skills/html-slides/examples/showcase.slides.html
  printf '\n<script type="text/plain" id="showcase-sim" data-encoding="base64">'
  base64 < $OUT/build/showcase-sim.html | tr -d '\n'
  printf '</script>\n'; } > $OUT/build/slides.html

# 3. the deck
python3 skills/html-slides/scripts/new-deck.py --title "html-slides Showcase" --lang de \
    --with-stage --slides $OUT/build/slides.html --out $OUT/showcase-deck.html \
    --deck-attr data-counter-format=padded --deck-attr data-tracks-default=full \
    --deck-attr "data-tracks-cycle=short full" --deck-attr data-deck-id=html-slides-showcase \
    --deck-attr data-back-href=showcase-seite.html

# 4. the companion page the back link points to, then write its <main> by hand
python3 skills/html-canvas/scripts/new-page.py --title "Showcase" --lang de \
    --blocks doc-header,callout,pipeline,decision-page,terminal,table \
    --out $OUT/showcase-seite.html

# 5. gate, send copy, PDF
V="uv run --with playwright python skills/html-canvas/scripts/verify-page.py"
$V $OUT/showcase-deck.html --deck --design DESIGN.md
$V $OUT/showcase-seite.html --browser --design DESIGN.md
python3 skills/html-canvas/scripts/bundle.py $OUT/showcase-deck.html --out $OUT/showcase-deck-versand.html
node skills/html-slides/scripts/render-pdf.cjs $OUT/showcase-deck.html $OUT/showcase-deck.pdf
```

Without step 2 (the fragment as it is) the stage loads `showcase-sim.html` from
next to the deck. The deck then runs only beside that file, and the gate reports
it as `request-failed`, because it opens the deck alone.

## Known limits

- `bundle.py` folds a stage's `data-src` into the send copy, but the gate opens the
  deck itself alone, so step 2 carries the simulation inside the deck as well.
- The back link is built by the engine at run time, so the bundler does not see
  it: in a send copy it points to a page that is not there.
