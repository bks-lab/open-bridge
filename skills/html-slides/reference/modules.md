# Deck Modules: optional features and the plugin API

Read this when a deck needs a feature the engine does not carry by default (a
presenter window, drawing, step reveals, a reading view), or when writing such a
module. A deck that names no module carries none of their bytes and behaves
exactly as before.

## Using a module

```bash
python3 skills/html-slides/scripts/new-deck.py --title "Review" --slides slides.html \
    --out deck.html --with presenter --with steps     # or: --with all
```

- A module is `assets/modules/<name>.js`, optionally with `assets/modules/<name>.css`.
  The set of names is whatever that folder holds; an unknown name is refused with
  the list of available ones.
- `--with` is repeatable and `--with all` takes every module. Each module gets one
  marker region, `<!-- deck-module:<name>:start -->` to `:end`, in `<body>` after the
  engine and the stage, sorted by name. Inside it the CSS sits in a `<style>` of its
  own, never in a shared stylesheet (a marker inside CSS would void the next rule,
  `reference/deck-build.md`), followed by the script.
- `--refresh` keeps the set of modules a deck carries and refreshes their code from
  the current files; it never adds or drops one, and refuses `--with`. A module whose
  file is gone stops the refresh before anything is written.

### The shipped modules

| Module | What it adds | Keys | Section |
|---|---|---|---|
| `draw` | laser pointer and a pen or marker on the slide | Q, D (then C, Z, H) | § Module: draw |
| `morph` | elements with the same `data-morph` glide from one slide to the next | none | § Module: morph |
| `presenter` | presenter window, time budget per slide, rehearsal, floating timer | P, Shift+P | § Module: presenter |
| `read` | reading view: the slides of the track as one document with notes | R | § Module: read |
| `steps` | `data-step` reveals and `data-lines` code walkthroughs, the step in the link | none | § Module: steps |

## The plugin API

A module is a plain script that registers itself once:

```js
SlideDeck.use({
  name: 'presenter',                    // unique; a second module with this name is ignored
  keys: { p: function (e) { return true; } },
  step: function (dir) { return false; },
  transition: function (fromSlide, toSlide, apply) { apply(); },
  help: [{ key: 'P', de: 'Referentenansicht', en: 'Presenter view' }],
  init: function (api) {}
});
```

| Field | Contract |
|---|---|
| `name` | Unique string. `use()` with a name already registered does nothing. |
| `keys` | Map of `event.key.toLowerCase()` to a handler (`p`, `escape`, `arrowright`). Return `true` when the key is handled: the engine then calls `preventDefault()` and does nothing else with it. Any other return value lets the key fall through to the next module and then the engine. Modules are asked in registration order, before the engine's own keys, so a module can take Escape while its view is open. Keys with Ctrl, Cmd or Alt, keys inside inputs, editable regions and `data-key-ignore`, and every key while the B / W cover is up never reach a module. |
| `step` | `function (dir)`, `dir` is `+1` or `-1`. Called on every forward or backward move (arrows, Space, Page keys, swipe, `data-deck="next"`, `SlideDeck.next()`), before the slide changes. Return `true` to consume the move (a fragment revealed or hidden); the module then reports the new step with `SlideDeck.setStep(n)`. Home, End, `goTo` and the number jump never step. |
| `transition` | `function (fromSlide, toSlide, apply)`, around a navigation from one slide to another. It must call `apply()` exactly once; `apply({instant: true})` places the new slide without the smooth scroll, which a view transition needs (`document.startViewTransition(() => apply({instant: true}))`). Extra calls are ignored, and a transition that never applies is applied by the engine after 1.5 s. Not called for the first placement, a track change, a deep link on load, a scroll by wheel or touch (the browser moves those), or under reduced motion. Several modules with a transition nest in registration order. |
| `help` | Rows for the `?` overlay, `{key, de, en}`; the deck language picks the text. `key` is split on spaces into keys (`'Shift+P'`, `'D Esc'`). |
| `init` | `function (api)`, called once when the deck is ready, or at once when `use()` runs later. `api` is `window.SlideDeck`. |

A handler that throws does not stop the deck: the error is rethrown asynchronously
and the engine goes on as if the handler had returned `false`.

### What a module can read and call

| `SlideDeck.` | Returns or does |
|---|---|
| `state()` | `{index, id, step, track, theme, lang, notes}`: 0-based index among the slides the active track shows, the slide id (`''` without one), the current step, the active track (`all` when none), `light` or `dark` as shown, `de` or `en`, whether the notes panel is open |
| `slides()` | the slides the active track shows, in order (a copy of the list) |
| `setStep(n)` / `step()` | set or read the step of the active slide. A slide change resets it to 0; `setStep` emits `stepchange` and keeps the deep link current |
| `setLang('de'\|'en')`, `setTheme('light'\|'dark')` | switch language or theme, as the keys L and T do |
| `reducedMotion()` | `true` under `prefers-reduced-motion: reduce` |
| `pauseTracking()` / `resumeTracking()` | for a module that shows the deck as a document (`read`). Paused, scroll no longer picks the active slide, the scroll keys (arrows, Space, Page Up/Down, Home, End) and swipes are left to the page, and no slide is `inert`; module keys, `goTo`, the number jump and T, L, F, B / W still work. `resumeTracking()` takes the active slide from the scroll position at once (the step stays when it is the same slide) and marks the other slides `inert` again |
| `on(event, fn)` | `ready`, `slidechange {index, count, slide}`, `trackchange {track, count}`, `stepchange {index, step, slide}`, `themechange {theme}`, `langchange {lang}`; each is also dispatched on `document` as `slidedeck:<event>` |
| `goTo(i)`, `next()`, `prev()`, `current()`, `count()`, `track()`, `setTrack()`, `toggleTheme()`, `toggleNotes()`, `toggleHelp()`, `strings()` | the engine API of `reference/slide-types.md` § Engine Contract |

### Steps and the deep link

The engine owns the step number; a module owns what a step means. The address
reads `#<id>.<step>` (or `#<n>.<step>` for a slide without an id) while the step is
above 0, and `#<id>` otherwise. On load and on a hash change the engine reads the
step before `init` runs, so a module renders `state().step` in `init` and follows
`stepchange` afterwards. An id that itself contains a dot is matched whole first:
`#v1.2` is the slide `v1.2`, `#v1.2.1` its step 1.

Coming back to a slide with steps is the module's call: the `slidechange` handler
can `setStep(max)` when the previous slide was the next one, so stepping back
starts with everything shown.

## Rules for a module

- **One file, no network, no dependency.** It is spliced inline, so neither file may
  contain a closing `script` or `style` tag, not even in a comment (new-deck.py
  refuses it).
- **Off means absent.** Do nothing visible until the user asks (a key, a
  `data-deck` button, a deck option). A module only listed with `--with` must leave
  the deck looking and behaving as before.
- **Colours from the deck tokens** (`var(--accent)`, `var(--surface)`, ...), never
  hex or rgb; text through `data-de` / `data-en` pairs or the `de` / `en` help rows.
- **Reduced motion is already handled** for CSS: the engine zeroes every animation
  and transition under `prefers-reduced-motion`. A script-driven animation checks
  `SlideDeck.reducedMotion()` and goes to its end state.
- **Print**: hide module chrome in `@media print`; the slides print as they are.
- **Storage** only behind `try`/`catch`, keyed by the deck id (`data-deck-id`, else
  the file path), and never required: a blocked storage must not break the module.
- **English** source and comments; German only in the `de` strings.

## Testing a module

`tests/engine_testlib.py` builds a probe deck with modules spliced exactly as
`--with` does:

```python
from engine_testlib import module_deck, open_deck, slide

def test_p_opens_the_view(open_html):
    page = open_deck(open_html, module_deck(["presenter"], [slide("One"), slide("Two")]))
    page.keyboard.press("p")
    ...
```

`module_deck(modules, slides=9, root=None, **deck_options)` takes the module names
and, like `deck()`, a slide count or a list of slide markup plus `html_attrs`,
`deck_attrs` and `lang`. `root` is the folder holding the module files: the shipped
modules by default, `MODULE_FIXTURES` (`tests/fixtures/modules/`) for test-only
modules such as `probe.js`, which `tests/test_engine_plugins.py` uses to pin the
API itself. `with_modules(html, modules, root)` adds modules to any spliced deck.

## Module: presenter

A presenter window for a second screen, a time budget per slide and per track, a
rehearsal that records how long each slide really took, and an optional floating
timer. Build with `new-deck.py --with presenter`; nothing changes in the deck until
P is pressed.

```html
<section class="slide" id="problem" data-time="90"> ... <aside class="notes">...</aside></section>
```

| Attribute | Effect |
|---|---|
| `data-time` on a slide | its budget in seconds (`90`) or as `m:ss` (`1:30`). A slide without one has no budget and adds nothing to the plan. |
| `data-deck-id` on the deck | names the deck for the stored rehearsals (else the file path), as for tracks and language |

**Keys in the deck.** `P` opens the presenter window, or brings it to the front when it
is open. `Shift+P` opens or closes the floating timer; the row appears in the `?` help
only where the browser has Document Picture-in-Picture, and elsewhere the key does
nothing. A blocked pop-up is reported in a notice on the deck (`.deck-presenter-toast`).

**The presenter window** shows the current slide and what comes next as live previews,
the notes of the current slide, the clock, the elapsed time, the budget of this slide
and the plan of the active track. Its keys: `→ ↓ Space PgDn` next, `← ↑ PgUp` back,
`Home End`, digits + `Enter` jump, `S` start or pause, `X` reset, `R` start or stop a
rehearsal, `A` plan vs actual, `+ -` notes size (kept per browser), `Esc` closes the
table. A click on the next preview advances. Labels follow the deck language, colours
and fonts are the deck tokens (`--bg`, `--text`, `--accent`, `--green`, `--amber`,
`--red`, ...) sent with every update, so a theme switch in the deck repaints the window.

**Next means next:** the next preview is a copy of the deck moved to the current slide
and step and then sent `next()`, so with the `steps` module it shows the next step of
the same slide, and at the end of the deck it says so. The previews are two copies of
the document as it was loaded (`srcdoc`, marked `data-deck-preview`, which turns this
module into a preview helper: no chrome, no smooth scroll). A live stage on a slide
therefore runs in the previews too.

**Timer and budget.** The deck owns the timer, so a presenter window opened in the
middle of a talk shows the true elapsed time. It starts with the first slide change
(not with a track switch) or `S`. Time is charged to the slide on screen while the
timer runs, across visits. A budget reads `ok`, `low` once a fifth or less of it is
left, and `over` when it is used up (`data-state` on `[data-pp=slide-budget]` and
`[data-pp=total-budget]`, green, amber, red from the tokens). The plan is the sum of
the budgets of the slides the active track shows, recomputed on every track change,
and the pace line says how far ahead or behind the plan the talk is at this slide
(within 5 s reads "on time").

**Rehearsal.** `R` resets the timer and records: every slide change and the stop save
the actual seconds per slide for the active track to `localStorage` under
`deck-rehearsal:<deck id>`, one record per track (`{at, track, rows: [{key, title,
plan, actual}]}`, the key is the slide id, else `n<position>`). Stopping opens the
plan vs actual table (`A` brings it back); a row is `over` when the slide took longer
than its budget. Copy puts the table on the clipboard as tab-separated text. Blocked
storage keeps the record for the session only.

**Sync.** The presenter page is a Blob URL opened with `window.open`, so it works
offline and survives a reload of its window. Both sides use `postMessage` on the
window reference and check the sender: the deck accepts only the window it opened (or,
after its own reload, a window whose `opener` is this tab saying hello), the window
only its `opener`; the origin must be the page's own, or `"null"` when the page itself
is opaque (`file://` sends `"null"`, and cannot be named as a target, so `*` is used).
The deck sends deck content only between that window's hello and its bye. A
`BroadcastChannel` named `deck-presenter:<deck id>` carries the same messages where it
exists, which keeps the link when the opener reference is lost; there commands must
name the deck instance. Every message carries sender id and sequence number, so one
that arrives on both paths counts once. When the deck reloads, the window waits and
says hello every 2 s until the new deck answers.

**Floating timer.** `Shift+P` asks `documentPictureInPicture.requestWindow()` for a
small always-on-top window with the elapsed time, the slide budget and a pause button.
It suits presenting from one screen, for example sharing only the deck tab in a call:
the floating window is not part of the shared tab.

**Off and print.** Without P nothing is added. The notice is hidden in print; the
presenter window and the floating timer are separate windows and never print with the
deck. The module has no animation of its own.

## Module: draw

`--with draw`. A laser pointer and a pen on the slide, for pointing at and marking up
a slide while presenting. Nothing is added to the page until it is used.

| Key | While | Does |
|---|---|---|
| D | any time | drawing on or off; the active slide takes a canvas, the cursor turns to a crosshair, a badge names the tool and its keys and then dims |
| Q | any time | laser pointer on or off: a dot in the accent colour follows the pointer, with a short fading trail; the cursor is hidden over the deck |
| Esc | drawing or laser | leaves the mode (before the engine closes a panel) |
| C / Shift+C | drawing | clears the active slide / every slide |
| Z | drawing | undoes the last stroke on the active slide |
| H | drawing | switches between pen and marker (wide, translucent) |

D and Q exclude each other. C, Z and H fall through to the deck while not drawing.
A button with `data-deck="draw"` or `data-deck="laser"` toggles the same modes, for
touch screens without a keyboard.

- **Ink stays with its slide.** Each slide drawn on gets a `canvas.deck-draw` as its
  last child; strokes are kept in slide coordinates (shares of width and height) for
  as long as the deck is open, so they survive navigation, a resize and a theme
  switch, and they are not stored anywhere. Leaving the mode keeps the ink visible
  until C clears it; only the active slide's canvas takes the pointer.
- **Colour** is `var(--accent)` as the slide resolves it, read again on every theme
  switch, so the ink follows light and dark. The marker is the same colour at 35 %
  opacity. A stylus sets the pen width by pressure (Pointer Events).
- Arrows, Space and the number jump still move the deck while drawing; a stroke on a
  touch screen never counts as a swipe. Alt+click zoom scales the canvas with the
  slide content, so ink stays on what it marks.
- **Reduced motion**: no laser trail, the dot alone. **Print**: canvas, laser and
  badge are hidden; slides print without ink.
- **Reading view** (`read` module): under `:root.deck-read` canvas, laser and badge are
  hidden, opening the view ends drawing or laser mode, and D, Q and the buttons wait
  for the slide view. The ink is kept and shows again with the slides.
- Keys D and Q are free in the engine and in the other shipped modules (P presenter,
  R read).
- `window.SlideDeckDraw = {mode(), tool(), strokes(i), setMode('draw'|'laser'|'off'),
  clear(all)}` for a presenter view, a stage or a test: `mode()` is `off`, `draw` or
  `laser`, `strokes(i)` counts the strokes on slide `i` of the active track.

Tests: `tests/test_module_draw.py`.

## Module: steps

Step reveals inside a slide and code walkthroughs. Forward moves (arrows, Space,
Page keys, swipe, `next()`) reveal the next step before the slide changes; backward
moves hide it again. Each step is written to the deep link (`#<id>.<step>`), so a
link or a reload lands on the same step.

| Markup | Effect |
|---|---|
| `data-step` | the element appears on the next step, in document order |
| `data-step="2"` | the element appears on step 2; elements with the same number appear together |
| `data-steps` on a container | each child is a step of its own (a list built up item by item) |
| `data-step-effect="rise"` | the element slides up as it appears |
| `data-step-effect="dim"` | the element dims once a later step is shown (the current point stands out) |
| `data-step-effect="highlight"` | the element takes the accent colour while it is the latest step |
| `data-lines="1-3\|5\|*"` on a `pre` or `code` | one line group per step: the first group is highlighted when the block is shown, each further group takes the next step, `*` shows every line; groups take ranges and commas (`1,4-6`) |

- A code block with `data-lines` is split into one `span.code-line` per line when
  the deck starts; highlight spans that cross a line break are copied into each
  line, so `kw`, `str`, `cm` and `hl` keep their colours. A code block that itself
  carries `data-step` appears first, then walks its lines.
- `data-step-effect` on a `data-steps` container applies to all its children.
- Moving back onto a slide (backward key, swipe, `prev()`) starts at its last step, so
  stepping back never shows a half built slide. A jump (number, dot, `goTo`, Home,
  End), a deep link or a wheel scroll lands on step 0, or on the step the link names.
- A step past the slide's last one in a link shows the last step.
- Without the module every element shows, so the same slides read complete in a deck
  that does not load it. Print and the PDF show every step and every line undimmed.
- Classes the module sets, for a deck's own CSS: `step-hidden`, `step-shown`,
  `step-current`, `step-past`; lines get `is-on` or `is-dim`.

## Module: morph

Animated continuity between two slides: elements that carry the same
`data-morph="name"` on the slide left and the slide reached glide from their old
place and size to the new one, and the rest of the screen cross-fades.

```html
<section class="slide" id="before"> ... <div class="card" data-morph="pipeline">...</div></section>
<section class="slide" id="after">  ... <div class="card wide" data-morph="pipeline">...</div></section>
```

- It uses `document.startViewTransition` around the engine's slide change
  (`transition` hook with `apply({instant: true})`). Each shared name becomes a
  `view-transition-name` (`morph-<name>`, other characters turned into `_`) for the
  length of the transition only, and is cleared afterwards.
- A name counts once per slide: when two elements on one slide share it, the first
  one morphs. Elements in speaker notes never morph.
- A slide pair without a shared name moves as before (smooth scroll, no view
  transition). A jump between slides that are not neighbours morphs too, when the
  two slides share a name.
- Any key during a morph finishes it at once (`skipTransition()`), so fast presses
  never queue animations.
- No View Transitions support, or `prefers-reduced-motion: reduce`: the change is
  instant, nothing else differs.
- `data-morph-duration="600"` (milliseconds) on the deck or `<html>` sets the
  duration; the default is 450 ms.
- `steps` and `morph` work together: the steps of a slide are walked first, the
  morph runs on the move to the next slide.

## Module: read

`--with read`. Key R, or any `data-deck="read"` button, lays the slides of the active
track out as one document: each slide at its own look but growing with its content,
a head above it with its number and a "present from here" button, its speaker notes
below it. The deck scrolls freely (no snap), and the arrows, Space, Page keys, Home
and End scroll it instead of changing slides. A bar at the bottom right names the
view and holds a Present button, plus a DE / EN switch in a bilingual deck; a thin
bar at the top shows how far the reader is.

| Situation | What happens |
|---|---|
| R or Esc while reading | back to the slide view at the exact slide and step the deck was on; Esc closes the help or a zoom first |
| "present from here" on a slide | back to the slide view at that slide |
| digits + Enter, or a `goto` button, while reading | scrolls the document there, and that slide becomes the one to return to |
| T, L, F, B / W, `?` while reading | work as in the slide view; F rebuilds the document for the new track |
| `data-read-default` on the deck or `<html>` | the deck opens in the reading view: the variant for a copy that is sent to be read (`new-deck.py --with read --deck-attr data-read-default=`). A deep link still picks the slide it opens at; `data-read-default="off"` keeps the slide view. The presenter's previews of such a copy still show slides |
| print, `render-pdf.cjs` | unchanged: the layout rules are screen only, so the slides print one per page and the reading chrome is hidden |

For other modules: while reading, `<html>` has the class `deck-read`, and `document`
gets `deckread:change` with `{read: true|false}` on every switch. The view shows every
`[data-step]` and `[data-steps] > *` element (with any `data-step-effect` undone) and
every `.reveal` at its end state, and every line of a `data-lines` block at full
strength; the step state returns with the slide view. A module with its own overlay
hides it under `:root.deck-read`, as `draw` does.

How it stays out of the engine's way: opening calls `SlideDeck.pauseTracking()`, so
the engine stops reading the document's scroll as a slide change, leaves the scroll
keys to the page and marks no slide `inert`. Closing scrolls to the slide to return
to and calls `SlideDeck.resumeTracking()`, which takes that slide and marks the others
`inert` again. A slide's own scroll listener keeps firing while reading.
