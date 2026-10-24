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

## Module: steps (`--with steps`)

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

## Module: morph (`--with morph`)

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
