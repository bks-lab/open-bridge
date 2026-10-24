# Stage: a live simulation inside a slide

Read this when a slide has to show something running (usually an html-canvas
simulation) instead of a picture of it. The stage is optional: build the deck
with `new-deck.py --with-stage`, or add it to a deck later by building again with
the flag (`--refresh` never adds a region).

## Markup

```html
<section class="slide">
  <h2 class="slide__heading">{Heading}</h2>
  <div class="stage" data-src="run.html" data-title="{What runs}"></div>
  <button type="button" data-stage="restart">{Restart}</button>
  <button type="button" data-stage="maximize">{Large}</button>
</section>
```

| Attribute | Effect |
|---|---|
| `data-src` | relative path of the page to run |
| `data-srcdoc-ref` | id of an inert `<script type="text/plain">` or `<template>` that holds the page itself; base64 when it carries `data-encoding="base64"` (UTF-8 safe). Wins over `data-src` |
| `data-mode="fit"` (default) | the page renders in a logical window (`data-viewport`, default `1440x900`) and is scaled down to the frame, never up: for pictures. The window is the least the page gets: it grows along the axis the frame has to spare, so the page fills the frame instead of sitting between empty bands. Declare the size the page needs to be read, not more: a smaller viewport scales less |
| `data-mode="read"` | no scaling, the page fills the frame and scrolls: for documents |
| `data-title` | accessible name of the frame |
| `data-stage="maximize"`, `data-stage="restart"` on a button in the same slide | the large stage, a fresh run |

Keys: V toggles the large stage of the active slide, Escape leaves it. The large
stage fills the window with CSS, not the browser's full screen interface, so it
works from `file://` and inside frames. Once a click puts focus inside the frame, the
simulation keeps its own keys (arrows, Space, its shortcuts); it hands V, Escape,
Page Up and Page Down back to the deck. Click outside the frame for T, F, N and
the arrows.

## Behaviour

- **Only the active stage runs.** A frame loads when its slide becomes active, so
  the run starts in front of the audience, and unloads two slides away.
- **Fit follows the frame** through a `ResizeObserver`, also when the text above
  it rewraps.
- **Clicks reach the page:** the placeholder ignores pointers and goes once the
  frame is loaded, and no ancestor of the frame carries a transform.
- Labels follow `<html lang>` (de/en). Old decks: `data-buehne`,
  `data-buehne-modus` and `data-buehne-viewport` are read as aliases.

The reasons, one test each, are in the header of `assets/slide-stage.js` and in
`tests/test_stage.py`.

## The contract with the page inside

The deck and the simulation share no code: they talk through `postMessage`
(`stage:ready`, `stage:key`, `stage:maximize`, `stage:restart`, `stage:look`), and each side
accepts a message only from the window it expects (`event.source`). The page side
is built into html-canvas `sim-engine.js` and speaks only when it is framed. The
whole contract: `html-canvas/references/simulation.md`, "Embedding in a slide". Inside a stage
the simulation hides its own toolbar; the stage hands it the deck's theme and
language (`stage:look`) once it is ready and on every switch, so T and L on the
deck reach the page as well.

## Sending a deck with a stage

A stage with `data-src` needs the page next to the deck. For a copy that travels
alone, the bundler (`scripts/inline-assets.py`, which runs html-canvas
`bundle.py`) folds it: the page is bundled first, carried as an inert
`<script type="text/plain" data-encoding="base64">` payload, and the stage's
`data-src` becomes `data-srcdoc-ref` pointing at it. A hand-made payload works the
same way (`data-srcdoc-ref="run-1"` on the stage, the page as base64 UTF-8 in
`<script type="text/plain" id="run-1" data-encoding="base64">`). Open the send
copy from an empty folder to prove it runs.

On paper every stage is loaded (print loads them all), `render-pdf.cjs` waits for
each frame before it writes the PDF, and the `data-stage` buttons are hidden. The
simulation prints its end state.
