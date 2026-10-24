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
fragment that is the geometry constants, `ITEMS`, `D`, `TXT` and the `Sim.params`
block; in `worklist` it is `PLAN`, `TXT` and `Sim.params`. Everything below the
`STAGE` marker is machinery you rarely touch, except `snapshot()` / `restore()`
when the model grows a new piece of state (see "Timeline" below).

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
var P = Sim.params({ approach: { value: 3, min: 1, max: 5 } });   // OPTIONAL, read from the hash
var clock = new Sim.Clock({
  step:      function (dt) { /* advance the model by dt ms; return true when done */ },
  render:    function () { /* paint; called once per frame, not once per step */ },
  reset:     function () { /* back to the starting state */ },
  marker:    function () { /* OPTIONAL: a value that changes once per discrete step */ },
  snapshot:  function () { /* OPTIONAL: a COPY of the model state */ },
  restore:   function (s) { /* OPTIONAL: the way back to that copy */ },
  seed:      42,                                   // OPTIONAL: clock.random, reseeded on reset
  onState:   function (s) { controls.state(s); }   // idle | running | paused | done
});
P.bind(clock);                                     // a changed value forgets the run and resets
var controls = new Sim.Controls(clock);            // buttons, scrubber, link, keys
Sim.boot(clock, { note: '[data-sim-reduced-note]', autostart: 6000, params: P });
```

`step` is **pure model work with no DOM**. That is what lets the same function
serve the animated run, the reduced-motion fast-forward, the print path and every
seek on the timeline. The clock calls it with one fixed `dt` (the `tick`, 20 ms of
model time by default), never with the frame time.

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
| `Sim.params(defs)` | scenario and control values, kept in the URL hash |
| `Sim.link()` | the address of exactly this view: values plus position |
| `Sim.Table(el, opts)` | the state as a table, behind a "show as table" toggle |
| `Sim.active` | `{clock, params}` of the booted simulation, for probes and tests |

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
half-truth. Under reduced motion the clock also **never starts by itself**: no
autostart, not after the reader scrubs back, and `stage:restart` computes the run
again instead of playing it. Step, back and the scrubber move through the run;
play runs only on an explicit press.

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

## Timeline, scenario links and the table

All of this is optional markup. A page without it runs as before, and the engine
removes any control the model cannot serve rather than leaving it dead.

### Timeline: fixed ticks, a seek, a snapshot ring buffer

The clock advances the model in **whole ticks of one size** (`tick`, default 20 ms
of model time). Frame time and speed only decide how many ticks run per frame. So
the state at tick n is one state: a live run paused at n, a seek to n and a replay
from the start to n paint the same picture. That is what makes a scrubber honest.

| Clock member | What it does |
|---|---|
| `clock.ticks`, `clock.time()` | the position, in ticks and in model ms |
| `clock.length()` | ticks in the whole run; a dry run computes it once and fills the ring buffer |
| `clock.seek(n)` | go to tick n and stay paused (idle at 0, done at the end) |
| `clock.back()` | one discrete step back: to the previous `marker` change, or one model second |
| `clock.single()` | one discrete step forward: ticks until `marker` changes |
| `clock.forget()` | drop the ring buffer, the markers and the length: the model changed |
| `clock.ring()` | the snapshots held right now (for probes) |
| `clock.on(fn)` | hear every repaint and state change (the scrubber uses it) |
| `clock.random` | with `seed`: a `Sim.rng` reseeded on reset and restored with each snapshot |

With `snapshot()` and `restore(s)` the clock keeps a **ring buffer** of the newest
`snapKeep` (96) snapshots, one every `snapEvery` ticks (about 500 ms of model
time). A seek restores the nearest snapshot at or before n and replays the few
ticks after it; without the pair it replays from the start, slower and still
right. `snapshot()` returns a **copy**: indices instead of object references, no
DOM nodes, plus `feed.snapshot()` when the model writes a feed (`Sim.Feed` keeps
its rows as data for exactly this). Every piece of state the model writes in
`step` belongs in it, including attributes `step` sets on nodes; the flow
archetype carries each token's `data-level` for that reason. A missing field does
not throw: it shows a scrubbed position that a replay would not reach. The test
`test_sim_timeline.py` compares both paths, with the ring switched off for the
reference, and goes red when one field is dropped.

The legacy `stepOnce` (a step outside the clock) still works, but such a run
cannot be replayed, so it gets no scrubber and no back button. Use `marker`.

Markup, inside the transport row:

```html
<div class="sim-timeline" data-sim-timeline>
  <input type="range" min="0" max="0" value="0" step="1" data-sim-scrub
         aria-label="Timeline" data-aria-de="Zeitleiste" data-aria-en="Timeline">
  <span class="sim-timeline__time" data-sim-scrub-time>00:00 / 00:00</span>
  <button class="sim-btn" type="button" data-sim-copy-link>
    <span data-state-idle>…</span><span data-state-copied>…</span><span data-state-manual>…</span>
  </button>
  <input class="sim-link" type="text" readonly data-sim-link hidden aria-label="Link to this view">
</div>
```

plus `<button data-sim-back>` in the bar. Keys: Space runs, S or the right arrow
steps, the left arrow steps back, R resets, 1 2 3 pick the speed. The scrubber's
`aria-valuetext` and readout come from the clock's `format(ms)` (default mm:ss of
model time; flow passes its own model clock so both readouts agree).

### Scenario and control values in the link

`Sim.params(defs)` declares the values a reader may change. Each is a number
(`min`, `max`), a choice (`options`), a boolean, or a string; `seed` also reseeds
`clock.random`. Bind a control with `data-sim-param="name"` on a `<select>`, an
`<input>` (range, number, checkbox) or a group of `button[data-value]` (the
bilingual choice: an `<option>` cannot hold a DE/EN pair), and show a number with
`data-sim-param-out="name"`.

The values live in the URL hash, **only where they differ from the default**:
`#approach=2&speed=0.5`. An untouched page keeps a clean address, and a hash
without `=` is an ordinary anchor and is left alone. The hash is read once, when
`Sim.params` runs, so the model's first `blank()` already sees the restored
values; an invalid value is ignored and the default kept. `speed` (written by the
speed buttons) and `t` are reserved. `Sim.link()`, and the copy-link button,
adds `t=<tick>`: a page opened with it stands **paused at that tick** and never
starts by itself, also under reduced motion (the "computed to its end" note stays
hidden, because it is not the end). Without a clipboard the button shows the link
selected in `[data-sim-link]` instead.

### The state as a table

`new Sim.Table(tableEl, {columns, rows})` renders the model's state as rows and
columns: the text alternative to a stage, for a screen reader, for a reader who
wants the numbers, and for a page pasted into a document. Columns are
`{de, en}` labels, `rows()` returns arrays of plain or `{de, en}` values, the first
cell becomes the row header. Call `table.render()` at the end of `render()`; while
hidden it costs nothing. The toggle is a `[data-sim-table-toggle]` button whose
`aria-controls` names the shown and hidden element, with `aria-expanded` kept in
step and a label of one span per state (`data-state-off`, `data-state-on`). Flow
lists one row per item (where it is, what the gate said, its outcome); worklist
lists the plan (who, what, level, done or pending).

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
| `stage:theme` | slide to simulation | `theme`: `dark` or `light` | the slide's theme, sent on every change and once after `stage:ready`. The frame follows it and does **not** store it, so a standalone visit keeps its own preference |
| `stage:lang` | slide to simulation | `lang`: `de` or `en` | the slide's language, same rules. The frame relabels its T and L buttons and aria labels through the shell's own `storage` listener, without writing storage |

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
- [ ] A scrubbed position equals a replay to the same tick (the timeline test
      does this; a new piece of model state needs a line in `snapshot()`).
- [ ] A copied link reopens the same values and the same position, paused.
- [ ] "Show as table" lists the state, and no cell shows both languages.
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
