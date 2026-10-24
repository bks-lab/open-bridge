---
summary: "Running models for html-canvas: five archetypes, the clock engine, and the traps that make a simulation lie"
type: reference
last_updated: 2026-10-24
related:
  - skills/html-canvas/SKILL.md
  - skills/html-canvas/assets/sim-engine.js
  - skills/html-canvas/assets/simulation.css
  - skills/html-canvas/scripts/new-simulation.py
---

# html-canvas: Simulations

A simulation is a page that **runs**: a clock advances a model, a stage shows
where things are, and a protocol says what happened. It is a different genre from
the rest of this skill, which describes a system in prose and diagrams. Reach for
it when the thing worth showing is a **behaviour over time** that a static
picture flattens: a queue forming, a gate rejecting work, two agents disagreeing,
a plan taking a decision at step six.

Two layers exist and they are not the same thing:

| Layer | What it is | Use it for |
|---|---|---|
| `assets/animations.css` | decoration on a static page: scroll reveal, ticker, ambient packet, pulse | making a document feel alive |
| `assets/simulation.css` + `assets/sim-engine.js` | mechanism: a clock, state, controls, a stage that changes | making a model actually run |

A page may take either, both, or neither.

---

## Do not hand-build one

```bash
python3 skills/html-canvas/scripts/new-simulation.py --list
python3 skills/html-canvas/scripts/new-simulation.py \
    --archetype flow --lang de \
    --title-de "Eine Meldung im Durchlauf" --title-en "One report through the run" \
    --out work/tasks/<slug>/deliverables/run.html
```

That splices `shell.html` (tokens, light/dark, DE/EN, print), `simulation.css`,
`sim-engine.js` and one archetype fragment into **one offline file**. Every splice
asserts its anchor and the result is checked before it is written, because a
quietly missed splice produces a page that opens fine and never runs.

Then edit the `MODEL` block at the top of the last `<script>`. In the `flow`
fragment that is the geometry constants, `ITEMS`, `D` and `TXT`; in `worklist` it
is `PLAN` and `TXT`. Everything below the `STAGE` marker is machinery you rarely
touch.

---

## Pick an archetype

| Archetype | Shipped | The question it answers | Shape |
|---|---|---|---|
| **flow** | `assets/sim-flow.html` | where does work pile up, and what happens at the gate | SVG stage, routes, stations with capacity, queues, branch outcomes |
| **worklist** | `assets/sim-worklist.html` | what is the sequence of decisions, and where does a person enter | no geometry: a plan, a protocol, a state strip |
| *console* | derive from `worklist` | what does a day of this look like at volume | seeded generator, counters per operating hour, capped log, meters |
| *dossier* | derive from `worklist` | what does one case actually contain at each station | one record built up card by card, step navigation |
| *exchange* | derive from `worklist` | what do two agents say to each other, and who decides | scripted message thread, a record that changes as it runs |

The three underived ones are deltas, not new engines. **console** adds
`Sim.rng(seed)` and generates items instead of listing them; give it a seed
constant and a weighted class table, and read counters per operating hour rather
than per run. **dossier** replaces the feed with cards and wires the step button
to move between stations. **exchange** uses `.sim-thread` / `.sim-msg` from
`simulation.css` and drives a `SCRIPT` array of `{who, at, text, changes}`.

---

## The engine

One global, `Sim`. Full source with comments: `assets/sim-engine.js`.

```js
var clock = new Sim.Clock({
  step:      function (dt) { /* advance the model by dt ms; return true when done */ },
  render:    function () { /* paint; called once per frame, not once per step */ },
  reset:     function () { /* back to the starting state */ },
  stepOnce:  function () { /* OPTIONAL: one discrete step; return true when done */ },
  onState:   function (s) { controls.state(s); }   // idle | running | paused | done
});
var controls = new Sim.Controls(clock);            // buttons + Space/S/R/1/2/3
Sim.boot(clock, { note: '[data-sim-reduced-note]', autostart: 6000 });
```

`step` is **pure model work with no DOM**. That is what lets the same function
serve the animated run, the reduced-motion fast-forward and the print path.

| Helper | What it is for |
|---|---|
| `Sim.pair(v)` / `Sim.put(el, v)` | write `{de, en}` as two sibling nodes; `put` skips the write when nothing changed |
| `Sim.svg` / `Sim.svgText` | create SVG nodes; `svgText` writes a bilingual `<tspan>` pair |
| `Sim.routeD(points, r)` | orthogonal path with rounded corners: reads as a route, not as wiring |
| `Sim.alongRoute(path, t, inset)` | a point 0..1 along a route, held clear of both ends |
| `Sim.centreOf(el, sel)` | the measured centre of a drawn shape |
| `Sim.show(el, bool)` | visibility that works on SVG (see the traps) |
| `Sim.Feed(el)` | protocol rows, newest first, capped, level glyph plus level word |
| `Sim.rng(seed)` | seeded random with `.int` `.pick` `.weighted` |
| `Sim.flight(layer)` | a packet travelling between two DOM anchors |
| `Sim.afterFonts(fn)` | run geometry measurement after the webfont has landed |

---

## Four rules that decide whether the thing is honest

**1. The engine never authors user-visible text.** The shell swaps DE/EN in pure
CSS by showing one of two sibling nodes. A string written by JS at runtime has no
sibling, so it freezes in one language and silently breaks the toggle for that
one label. Every text the model produces arrives as `{de: ..., en: ...}`; ids,
clock readings and counts pass through as plain strings. The only exception is
the four level words, which the engine owns so a row cannot lose its second
channel.

**2. Reduced motion means the finished run, not an empty stage.** `Sim.boot`
computes the whole run and paints the end state, then reveals a note that says
why the page looks finished. Printing takes the same path. Anything else prints a
half-truth.

**3. Criticality rides two channels, always.** Colour plus a glyph plus a word.
Colour alone fails in print, in a grey slide, and for a large share of readers. A
waiting state also takes a dash pattern, because "amber" is not a state a reader
can name.

**4. A simulation that could be mistaken for a live system carries the
provenance block.** Three columns, not two: what is **model**, what is **stock**
that genuinely exists today (with a path or a source), and what is **not built
yet**. The third column is the one that gets dropped and the one that matters:
leaving it out is the actual dishonesty, not the simulation.

---

## Traps

Each of these was paid for once. Most fail **silently**, which is why they are
worth reading before rather than after.

**Timing**

- `requestAnimationFrame` stops in a window that is not being painted: a
  background tab, a second screen, a shared desktop. That is exactly the setting
  a simulation gets demonstrated in. `Sim.Clock` runs a 200 ms watchdog on the
  same wall clock as a second driver, so no time is counted twice.
- A long pause produces a huge `dt` and the model teleports. Catch-up is capped
  at 1200 ms and every step sees at most a 60 ms slice.
- A model that never reports done hangs the fast-forward. `Sim.Clock` stops at a
  guard and calls `onGuard`; it never fails quietly.

**SVG**

- `hidden` is a property of `HTMLElement`. `SVGElement` does not have it, so
  `el.hidden = true` on an SVG node does nothing and throws nothing. Use
  `Sim.show()`.
- A class rule carrying its own `display` beats the `[hidden]` attribute on
  specificity. `simulation.css` ships an explicit `[hidden]{display:none
  !important}` for that reason.
- The language swap hides only the **inactive** language, with rules at
  (0,4,0), so a pair keeps its native display (`li` stays a list item, `td` a
  cell) and a class rule that sets `display` on a pair can no longer show both
  languages at once. Do not add a rule that forces `display` back onto the
  inactive node with higher specificity or `!important`. Pages assembled before
  this change: see "Migrating an older page" in `references/build-workflow.md`.
- `getBBox()` before the webfont has landed measures the fallback face and is
  wrong in every direction. Measure inside `Sim.afterFonts()`.
- Positions come from the **drawing**, never from arithmetic. Distributing steps
  over a route length puts a token between two stations the first time the layout
  moves, and it reads as a stall. A step declares which station it belongs to and
  the station is measured where it was drawn.
- A token parked exactly on the route's start point shows nothing during the
  first step. Inset the travel at both ends (`Sim.alongRoute`).
- Waiting tokens drawn **on** the route collide with an arriving one and the
  queue reads as a single item. Draw them beside it.

**Rendering**

- Rewriting text every frame re-lays-out the page sixty times a second. `Sim.put`
  writes only on change.
- Two consecutive steps at the same station move nothing, so travel alone cannot
  show that the second one is running. Give the token a per-step bar that fills
  over the step's own duration, and let it carry the running step only. A full
  bar on a finished item is a loud stripe that says nothing.
- **The end state is a state.** It is what a printed page and a reduced-motion
  visitor see. Place finished items explicitly; a branch that only handles
  "moving" and "queued" leaves the final stage empty while every counter reads
  correctly, and that combination stays green in a test that only reads counters.

**Content**

- An unseeded generator shows a different picture on every reload: the screenshot
  cannot be retaken, the reviewer cannot point at what they saw, and a defect
  cannot be repeated. One seed constant at the top.
- Never offer a control that does nothing. `Sim.Controls` removes the single-step
  button when the model passes no `stepOnce`.

---

## Embedding in a slide: the stage contract

A simulation can run live inside a slide. The slide side is
`html-slides/assets/slide-stage.js` (a "stage"); the simulation side is built
into `sim-engine.js`. The two never share code or globals: they talk through
`postMessage`, and this section is the whole contract between them. Either side
may be rebuilt as long as it keeps to it.

The engine speaks **only when it is framed** (`window.parent !== window`). A
page opened on its own posts nothing, listens to nothing, and removes its
`[data-sim-maximize]` button, because a control with no stage to enlarge is a
dead control. Both archetypes ship that button with `hidden`.

| Message | Direction | Payload | Meaning |
|---|---|---|---|
| `stage:ready` | simulation to slide | `contract: 1`, `title` | sent once, by `Sim.boot`, after the first frame is painted. A page with its own boot calls `Sim.stage.ready(clock)` |
| `stage:key` | simulation to slide | `key`: `v`, `Escape`, `PageDown` or `PageUp` | a key the slide owns was pressed while focus sat inside the frame. Space, R, S and the digits stay with the simulation |
| `stage:maximize` | simulation to slide | optional `on` (boolean) | the maximize button was pressed; without `on` it means toggle |
| `stage:maximize` | slide to simulation | `on` (boolean) | the slide reports the resulting state; the engine mirrors it as `data-sim-maximized="yes"` or `"no"` on `<html>` and as `aria-pressed` on the button |
| `stage:restart` | slide to simulation | none | reset the run in place and start it again (under reduced motion: compute it to the end). The slide falls back to reloading the frame when no `stage:ready` has arrived |
| `stage:look` | slide to simulation | `dark` (boolean), `lang` (`de` or `en`) | the slide's theme and language, sent after `stage:ready` and on every change; the engine sets `.dark` and `data-lang` on `<html>` and stores nothing. A framed page carries `data-sim-embedded="yes"` and hides its own toolbar, because theme, language and print belong to the slide |

Every message is a plain object with a `type` string; anything else is ignored.

**Check `event.source`, never the origin.** Each side accepts a message only
when `event.source` is the window it expects: the simulation compares it with
`window.parent`, the slide with the `contentWindow` of one of its own frames. A
sibling frame can post to either side, and a page loaded through `srcdoc` or
from `file://` has no origin worth comparing, so the window is the only check
that holds. For the same reason messages go out with target origin `'*'`, and
they carry nothing a foreign listener could misuse.

What the slide does with it, and why, is documented in the header of
`slide-stage.js` (lazy loading, fit and read modes, the large stage without the
browser's full screen interface). The tests on both sides are
`html-canvas/tests/test_stage_child.py` and `html-slides/tests/test_stage.py`.

---

## Before calling one done

The general bar in `references/build-workflow.md` still applies. On top of it,
measure these against the rendered page rather than the source:

- [ ] The run finishes. Counters add up to the item count, nothing is left in a
      queue or in work.
- [ ] The **end state** shows items where they ended, not an empty stage.
- [ ] Reduced motion: the page arrives finished, the note is visible, the
      protocol is complete.
- [ ] `beforeprint` reaches the same end state. Controls are hidden on paper.
- [ ] Reset returns every counter, the clock and the protocol to the start.
- [ ] **No element shows both languages at once.** This one is a query, so run it
      rather than eyeballing it:
      ```js
      [...document.querySelectorAll('[data-de]')].filter(de => {
        const en = de.nextElementSibling;
        return en && en.hasAttribute('data-en')
          && getComputedStyle(de).display !== 'none'
          && getComputedStyle(en).display !== 'none';
      })
      ```
- [ ] Every protocol row carries a glyph and a word, not colour alone.
- [ ] The provenance block names something real in all three columns.
- [ ] Light and dark both read. No console error in either.
- [ ] Visible text follows the target language's punctuation conventions and the
      user's style rules, **including strings the model emits at runtime**.

And the one that catches what the list above cannot: **break the code on purpose
and confirm the check goes red.** A green assertion that stays green after the
defect is introduced measured nothing. Five probes on this layer during its own
build, all five bit, and the defect they did not cover (an empty end stage) was
found by looking at the rendered image instead.
