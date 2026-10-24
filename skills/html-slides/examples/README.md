# html-slides examples

## showcase.slides.html

The slides of the showcase deck: one deck that shows every capability of
html-slides on a slide of its own, the five deck modules included, with one line
on how to use it. The content is neutral and bilingual (DE / EN), it presents the
html-slides and html-canvas skills themselves. A companion page, built with
html-canvas, shows the reading aids of a page and the simulation with its
timeline.

### Capability to slide

Slide numbers count the full track (33 slides); the short track leaves out the
three slides tagged `full`.

| Slide | Id | Capability | How to use it |
|---|---|---|---|
| 1 | `s-title` | Title (untagged, so in every track) | `slide--title` |
| 2 | `s-agenda` | Agenda as an overview slide | `slide--overview`, tiles with `data-deck="goto:#id"` |
| 3, 9, 13, 20, 29 | `s-nav`, `s-look`, `s-types`, `s-present`, `s-live` | Section dividers | `slide--divider` |
| 4 | `s-keys` | Keys, help with the module rows, buttons | `?`, `data-deck="help"`, `data-deck="next"` |
| 5 | `s-deeplink` | Deep link, with a step (track "full") | `deck.html#s-deeplink`, `#s-steps.2`, `data-deep-link="off"` |
| 6 | `s-tracks` | Tracks, with labels for the track names | key F, `data-track`, `data-tracks-default`, `data-tracks-cycle`, `data-tracks-labels` |
| 7 | `s-notes` | Speaker notes | key N, `<aside class="notes">` |
| 8 | `s-livekeys` | Cover, number jump, zoom (engine, always on) | B / W, digits + Enter, Alt+click |
| 10 | `s-theme` | Theme, and the language switched at run time by the engine | key T, key L or `data-deck="lang"`, `data-de` / `data-en` pairs |
| 11 | `s-chrome` | Padded counter, back link | `data-counter-format="padded"`, `data-back-href` |
| 12 | `s-reveal` | Reveal and reduced motion (track "full") | `class="reveal"` |
| 14 to 17 | `s-table`, `s-code`, `s-pipeline`, `s-cheat` | Table of the eleven slide types (jumps by `goto:#id`), code with a colour legend, pipeline, card grid | `slide--table`, `slide--code`, `.pipeline`, `.cheat-grid` |
| 18 | `s-decision` | Decision page excerpt | the html-canvas `decision-page` block, cut to options and pick |
| 19 | `s-terminal` | Terminal mockup (track "full") | `.slide__code-block` |
| 21 | `s-presenter` | Presenter window, time budget per slide, floating timer | `presenter` module: P, Shift+P, `data-time` on every slide |
| 22 | `s-rehearsal` | Rehearsal: plan vs actual | `presenter` module: R and A in the presenter window |
| 23 | `s-draw` | Pen, marker, laser | `draw` module: D, H, Z, C, Q, `data-deck="draw"` / `laser` |
| 24 | `s-steps` | Step reveals and their effects; the step in the link | `steps` module: `data-steps`, `data-step`, `data-step-effect="dim"` / `highlight` / `rise` |
| 25 | `s-walk` | Code walkthrough line by line | `steps` module: `data-lines="1\|2-4\|5\|*"` |
| 26, 27 | `s-morph-a`, `s-morph-b` | Morph between two neighbours | `morph` module: the same `data-morph` names on both slides |
| 28 | `s-read` | Reading view | `read` module: R, `data-deck="read"`, `data-read-default` |
| 30 | `s-stage` | Live stage with a running simulation | `.stage`, key V, `data-stage="maximize"` / `restart` |
| 31 | `s-ship` | Print, PDF and the send copy that opens as a document | `render-pdf.cjs`, `bundle.py`, `data-read-default` |
| 32 | `s-handout` | Print handout with notes pages | `data-print-notes`, `render-pdf.cjs --notes` |
| 33 | `s-end` | Closing | `slide--bleed` |

The companion page (`showcase-seite.html`) carries:

| Section | Capability | Block |
|---|---|---|
| Contents | table of contents with scroll spy, filled from the `h2`s | `toc` (`data-toc="auto"`) |
| Time plan | the planned time per chapter as a chart, with "show as table" | `alt-table` (bar chart) |
| Simulation | the stage simulation in a frame: scenario in the link (`#approach=2`), transport bar, timeline, large view | html-canvas simulation, `flow` archetype |
| Decision, commands, files | decision page, terminal, data table | `decision-page`, `terminal`, `table` |
| Glossary | terms in the text open their definition | `glossary` |
| Print | paper rules, contents left out, every table printed | `print` |

The fragment carries one `<style>` and one small script of its own, both marked as
deck-specific: the styles of the example cards, and a script that writes the
active track into the card on the tracks slide in the active language. The
language switch itself is the engine's (key L, `data-deck="lang"`), with no reload.
The deck options come from `new-deck.py --deck-attr` in step 3. Track "short" is
named only by `data-tracks-cycle`: no slide carries it, it shows the untagged
slides.

## Build

From the repository root, into a folder of your choice (`OUT`). A DESIGN.md found
above `OUT`, or given with `--design`, gives the deck its brand; without one the
default style preset applies.

```bash
OUT=work/showcase; mkdir -p $OUT/build

# 1. the simulation for the stage (archetype flow: scenario values, timeline, table)
python3 skills/html-canvas/scripts/new-simulation.py --archetype flow --lang de \
    --out $OUT/build/showcase-sim.html
cp $OUT/build/showcase-sim.html $OUT/

# 2. the slides plus the simulation as an inert base64 payload; the stage reads
#    data-srcdoc-ref="showcase-sim" first and falls back to data-src
{ cat skills/html-slides/examples/showcase.slides.html
  printf '\n<script type="text/plain" id="showcase-sim" data-encoding="base64">'
  base64 < $OUT/build/showcase-sim.html | tr -d '\n'
  printf '</script>\n'; } > $OUT/build/slides.html

# 3. the deck, with the stage and every module
ATTRS=(--deck-attr data-counter-format=padded --deck-attr data-tracks-default=full
  --deck-attr "data-tracks-cycle=short full" --deck-attr data-deck-id=html-slides-showcase
  --deck-attr data-back-href=showcase-seite.html --deck-attr "data-tracks-labels=short=kurz full=lang")
python3 skills/html-slides/scripts/new-deck.py --title "html-slides Showcase" --lang de \
    --with-stage --with all --slides $OUT/build/slides.html --out $OUT/showcase-deck.html "${ATTRS[@]}"

# 4. the same deck opening in the reading view, folded into the send copy
python3 skills/html-slides/scripts/new-deck.py --title "html-slides Showcase" --lang de \
    --with-stage --with all --slides $OUT/build/slides.html --out $OUT/build/showcase-deck-lesen.html \
    "${ATTRS[@]}" --deck-attr data-read-default=
python3 skills/html-canvas/scripts/bundle.py $OUT/build/showcase-deck-lesen.html \
    --out $OUT/showcase-deck-versand.html

# 5. PDF, and the handout with a notes page after every slide with notes
node skills/html-slides/scripts/render-pdf.cjs $OUT/showcase-deck.html $OUT/showcase-deck.pdf
node skills/html-slides/scripts/render-pdf.cjs $OUT/showcase-deck.html $OUT/showcase-handout.pdf --notes

# 6. the companion page the back link points to, then write its <main> by hand;
#    its simulation frame carries the page as a data: URL with #approach=2
python3 skills/html-canvas/scripts/new-page.py --title "Showcase" --lang de \
    --blocks doc-header,toc,callout,pipeline,alt-table,decision-page,terminal,table,glossary,print \
    --out $OUT/showcase-seite.html

# 7. gate
V="uv run --with playwright python skills/html-canvas/scripts/verify-page.py"
$V $OUT/showcase-deck.html --deck --design DESIGN.md
$V $OUT/showcase-deck-versand.html --deck --design DESIGN.md
$V $OUT/showcase-seite.html --browser --width 1280 --width 600 --design DESIGN.md
```

Without step 2 (the fragment as it is) the stage loads `showcase-sim.html` from
next to the deck. The deck then runs only beside that file, and the gate reports
it as `request-failed`, because it opens the deck alone.

## Known limits

- `bundle.py` folds a stage's `data-src` into the send copy, but the gate opens the
  deck itself alone, so step 2 carries the simulation inside the deck as well.
- The back link is built by the engine at run time, so the bundler does not see
  it: in a send copy it points to a page that is not there.
- `data-tracks-labels` holds one label per track name, not one per language. The
  deck carries the German labels; the card on the tracks slide follows the
  language, while the engine's track badge shows the bare track name after a
  language switch.
- The gate warns that the hidden steps of `s-steps` stay at opacity 0 under
  reduced motion: they are steps not yet reached, and print, PDF and the reading
  view show them.
