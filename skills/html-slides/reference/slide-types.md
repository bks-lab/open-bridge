# Slide Types Reference

16 slide types with full HTML examples (types 12 to 16 are the keynote forms). Read this file when writing the slides; the decks are assembled by `scripts/new-deck.py`.

## Color System

A slide declares its chapter colour with `data-tone` on the `<section>` (never an inline
`style`): `<section class="slide slide--content" data-tone="green">`. Values:

| Tone | Use for |
|------|---------|
| `accent` (default) | Default, the preset's own colour |
| `green` | Positive, success, new |
| `red` | Problems, warnings, "before" state |
| `amber` | Caution, strings, configuration |
| `cyan` | Info, keywords, technical details |

A style preset renders a tone as the label colour (the heading on a divider) plus a
soft glow behind the slide. In the examples below `{color}` stands for one of these
values. A split panel takes `data-tone` too and colours its label only. Slide
spacing and size come from classes, not inline styles: `.slide__heading--sm` and
`.slide__heading--xl` set the heading size, and a heading, subtitle, bullet list,
code block or table that follows each other keep their distance on their own.

The decoration (a tone's glow, the title glow, the `slide--with-grid` dot texture and
the `slide__bg--gradient` backdrop) is on in a style preset. With the `design` preset
(a DESIGN.md is present) the tone is quiet: the label takes the accent, the headings
the heading colour, and the decoration is off; `.fx` on `<html>`, the `.deck` or one
`.slide` brings it back. Status colours carry state only there. Old decks with inline
`style="color:var(--green)"` or a `radial-gradient` background keep working, and the
design preset neutralises them the same way. Buttons take
`.slide__btn` (and `.slide__btn--primary` for the one main action) inside
`.slide__actions`; the primary one is the brand's `primary` fill.

## Slide Types

### 1. Title Slide
Center-aligned, large display text, accent-colored heading. Use for opening slide.

```html
<section class="slide slide--title slide--with-grid">
  <div class="reveal">
    <p class="slide__subtitle">{subtitle}</p>
  </div>
  <h1 class="slide__display reveal">{Main Title}</h1>
  <div class="reveal">
    <p class="slide__subtitle">{tagline}</p>
  </div>
</section>
```

### 2. Section Divider
Big faded number in background, heading + subtitle. Use to introduce new sections.

```html
<section class="slide slide--divider" data-tone="{color}">
  <span class="slide__number" aria-hidden="true">{01}</span>
  <div>
    <h2 class="slide__heading reveal">{Section Title}</h2>
    <p class="slide__subtitle reveal">{Section subtitle}</p>
  </div>
</section>
```

### 3. Content (Text + Aside)
3:2 grid with bullet list left, optional visual right. Main workhorse slide.

```html
<section class="slide slide--content" data-tone="{color}">
  <div class="slide__inner">
    <div>
      <p class="slide__label reveal">{Label}</p>
      <h2 class="slide__heading reveal">{Heading}</h2>
      <ul class="slide__bullets">
        <li class="reveal">{Point 1}</li>
        <li class="reveal">{Point 2}</li>
      </ul>
    </div>
    <div class="slide__aside reveal">
      <!-- Optional aside: SVG diagram, small code block, icon, or a picture -->
      <img class="slide__image" src="{image-path}" alt="{what the picture shows}">
    </div>
  </div>
</section>
```

### 4. Split (Two Panels)
Side-by-side comparison. Use for before/after, pros/cons.

```html
<section class="slide slide--split">
  <div class="slide__panels">
    <div class="slide__panel slide__panel--primary" data-tone="red">
      <p class="slide__label reveal">{Left Label}</p>
      <h2 class="slide__heading slide__heading--sm reveal">{Left Title}</h2>
      <ul class="slide__bullets">
        <li class="reveal">{item}</li>
      </ul>
    </div>
    <div class="slide__panel slide__panel--secondary" data-tone="green">
      <p class="slide__label reveal">{Right Label}</p>
      <h2 class="slide__heading slide__heading--sm reveal">{Right Title}</h2>
      <ul class="slide__bullets">
        <li class="reveal">{item}</li>
      </ul>
    </div>
  </div>
</section>
```

### 5. Table
Full-width data table with header and hover effects. The card is as tall as its rows.

```html
<section class="slide slide--table" data-tone="cyan">
  <p class="slide__label reveal">{Label}</p>
  <h2 class="slide__heading slide__heading--sm reveal">{Title}</h2>
  <div class="table-wrap reveal">
    <div class="table-scroll">
      <table class="data-table">
        <thead><tr><th>Col 1</th><th>Col 2</th></tr></thead>
        <tbody>
          <tr><td>data</td><td>data</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</section>
```

### 6. Code Block
Centered code with filename badge and syntax highlighting via CSS classes.

```html
<section class="slide slide--code" data-tone="accent">
  <h2 class="slide__heading slide__heading--sm reveal">{Title}</h2>
  <div class="slide__code-block reveal">
    <span class="slide__code-filename">{filename}</span>
    <pre><code><span class="kw">keyword</span> <span class="str">"string"</span> <span class="cm"># comment</span> <span class="hl">highlighted</span></code></pre>
  </div>
</section>
```

Syntax classes: `.hl` (accent/green), `.cm` (dim/comment), `.str` (amber), `.kw` (cyan); with the `design` preset they take the brand scale instead (`.kw` accent, `.str` accent mixed into the code text, `.hl` the heading colour), so no status colour reads as syntax.

### 7. Pipeline / Flow Diagram
Horizontal steps with arrows between them.

```html
<section class="slide slide--with-grid">
  <p class="slide__label reveal">{Label}</p>
  <h2 class="slide__heading reveal">{Title}</h2>
  <div class="pipeline reveal">
    <div class="pipeline__step">
      <div class="pipeline__num">01</div>
      <div class="pipeline__name">{Step Name}</div>
      <div class="pipeline__desc">{Description}</div>
      <div class="pipeline__file">{command or file}</div>
    </div>
    <div class="pipeline__arrow">
      <svg viewBox="0 0 24 24" width="20" height="20"><path d="M5 12h14m-4-4l4 4-4 4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
    </div>
    <!-- repeat steps -->
  </div>
</section>
```

### 8. Card Grid (Scenarios / Cheat Sheet)
2x2 grid of cards. Use `.scenario-grid` + `.scenario-card` or `.cheat-grid` + `.cheat-card`.
Add `cards--tinted` to the grid (`<div class="cheat-grid cards--tinted">`) for soft cards on an
accent tint with a hairline and a larger radius, the keynote look.

```html
<section class="slide">
  <p class="slide__label reveal">{Label}</p>
  <h2 class="slide__heading slide__heading--sm reveal">{Title}</h2>
  <div class="cheat-grid">
    <div class="cheat-card reveal">
      <div class="cheat-card__title">{Card Title}</div>
      <div class="cheat-card__item">1. <code>command</code></div>
      <div class="cheat-card__item">2. <code>command</code></div>
    </div>
    <!-- more cards -->
  </div>
</section>
```

### 9. Closing / Full-Bleed
Image (or gradient) background under a veil in the theme background, text at the bottom; reads in light and dark. Use for the final "Questions?" slide. The image is an `<img class="slide__bg" alt="">` that fills the slide (cover, behind the scrim), never an inline `background-image`; for a gradient use `<div class="slide__bg slide__bg--gradient"></div>` instead of the `<img>`.

```html
<section class="slide slide--bleed">
  <img class="slide__bg" src="{image-path}" alt="">
  <div class="slide__scrim"></div>
  <div class="slide__content">
    <p class="slide__label reveal">{call to action}</p>
    <h2 class="slide__heading slide__heading--xl reveal">{Closing Text}</h2>
    <p class="slide__subtitle reveal">{subtitle}</p>
  </div>
</section>
```

### 10. Overview
Clickable agenda: each tile jumps to a slide. `data-deck="goto:<n>"` takes the 1-based slide number the counter shows; `goto:#<id>` targets a slide by its id and keeps working when slides move.

```html
<section class="slide slide--overview">
  <p class="slide__label reveal">{Label}</p>
  <h2 class="slide__heading reveal">{Overview Title}</h2>
  <nav class="overview-grid reveal" aria-label="{Overview Title}">
    <button type="button" class="overview-tile" data-deck="goto:3">
      <span class="overview-tile__num">03</span>
      <span class="overview-tile__title">{Section Title}</span>
      <span class="overview-tile__desc">{One line on what the section shows}</span>
    </button>
    <button type="button" class="overview-tile" data-deck="goto:5">
      <span class="overview-tile__num">05</span>
      <span class="overview-tile__title">{Section Title}</span>
    </button>
    <!-- one tile per section -->
  </nav>
</section>
```

### 11. Content with Speaker Notes
Any slide may carry an `<aside class="notes">`. It never shows on the slide or in print; key N opens a notes panel that follows navigation. Keep the slide to its result sentence and put what to say in the notes.

```html
<section class="slide slide--content">
  <div class="slide__inner">
    <div>
      <p class="slide__label reveal">{Label}</p>
      <h2 class="slide__heading reveal">{Heading}</h2>
      <p class="slide__body reveal">{One result sentence, with <code>inline code</code> if it names one}</p>
      <div class="slide__actions reveal">
        <button type="button" class="slide__btn slide__btn--primary" data-deck="notes">{Main action} <span class="slide__btn-arrow" aria-hidden="true">→</span></button>
        <button type="button" class="slide__btn" data-deck="next">{Other action}</button>
      </div>
    </div>
  </div>
  <aside class="notes">
    <p>{What to say, in two or three short sentences}</p>
    <p>{The question to expect, and the answer}</p>
  </aside>
</section>
```

## Keynote Forms

Types 12 to 16 give a deck the look of a corporate keynote: a photo half panel, big
gradient numbers, a glowing arc under a heading, a quote, a result card on a decision
slide and a numbered agenda. Every one is optional markup: a deck that uses none of
these classes renders exactly as before. All colours come from the deck tokens, so they
follow the preset or DESIGN.md in light and dark. With the `design` preset the arc still
shows (the markup is the opt-in), the quote bar is a hairline and the numbers and result
values take the one display cut.

### 12. Media Split (Photo Half Panel)
A photo fills one side of the slide edge to edge, full height, no frame (`object-fit: cover`);
the text column keeps the slide padding on the other side. `data-media="right"` (default) or
`"left"` picks the side, `data-media-size="1/3|2/5|1/2"` the photo's share (default `2/5`).
Under 768 px wide the photo stacks above the text at a fixed height; print keeps it side by
side. An AI image slot works the same way: `<img class="slide__media" data-image-prompt="..."
data-image-ratio="4:3" alt="...">` without a `src` shows the surface colour in the same box
until `html-canvas/scripts/gen-images.py` fills it.

```html
<section class="slide slide--media" data-media="right" data-media-size="2/5">
  <img class="slide__media" src="{image-path}" alt="{what the picture shows}">
  <div class="slide__content">
    <p class="slide__label reveal">{Label}</p>
    <h2 class="slide__heading reveal">{Heading}</h2>
    <div class="slide__arc reveal" aria-hidden="true"></div>
    <ul class="slide__bullets">
      <li class="reveal">{Point 1}</li>
      <li class="reveal">{Point 2}</li>
      <li class="reveal">{Point 3}</li>
    </ul>
  </div>
</section>
```

### 13. Key Numbers (Gradient Stats)
Up to four big numbers side by side, each with its label under it. The number is a text
gradient from the accent to the accent mixed towards the text colour, so both ends read at
least as well as the accent; print, forced colours and a browser without
`background-clip: text` get the solid accent. `slide__stat--solid` keeps one number solid.
The `.slide__arc` under the heading is a thin glowing curve, decorative (`aria-hidden`),
hidden under forced colours; `slide__arc--center` centres it.

```html
<section class="slide">
  <p class="slide__label reveal">{Label}</p>
  <h2 class="slide__heading reveal">{Heading}</h2>
  <div class="slide__arc reveal" aria-hidden="true"></div>
  <div class="slide__stats reveal">
    <div class="slide__stat">
      <span class="slide__stat-value">{98%}</span>
      <span class="slide__stat-label">{what the number counts}</span>
    </div>
    <div class="slide__stat">
      <span class="slide__stat-value">{4 min}</span>
      <span class="slide__stat-label">{what the number counts}</span>
    </div>
    <div class="slide__stat">
      <span class="slide__stat-value">{12}</span>
      <span class="slide__stat-label">{what the number counts}</span>
    </div>
  </div>
</section>
```

A deck built with `--blocks kpi-row` gets the same numbers on the metric cards with
`metrics--gradient` on the block container:

```html
<div class="metrics metrics--gradient">
  <div class="metric"><div class="m-label">{Label}</div><div class="m-val">{18,400}</div><div class="m-sub">{context}</div></div>
</div>
```

### 14. Quote
One statement in large light type (the body family, weight 300) behind an accent bar, its
source below. Keep it to two or three lines.

```html
<section class="slide slide--quote">
  <blockquote class="slide__quote reveal">
    <p>{The sentence worth remembering}</p>
    <footer class="slide__quote-source">{Name, role}</footer>
  </blockquote>
</section>
```

### 15. Decision with Result Card
The content slide with a result card as its aside: a tall rounded card on a soft accent
tint, a small caps label and one or more values; an arc between two values separates them.

```html
<section class="slide slide--content">
  <div class="slide__inner">
    <div>
      <p class="slide__label reveal">{Label}</p>
      <h2 class="slide__heading reveal">{The decision}</h2>
      <ul class="slide__bullets">
        <li class="reveal">{Reason 1}</li>
        <li class="reveal">{Reason 2}</li>
      </ul>
    </div>
    <div class="slide__aside reveal">
      <div class="slide__result">
        <p class="slide__result-label">{Result today}</p>
        <p class="slide__result-value">{First result}</p>
        <div class="slide__arc" aria-hidden="true"></div>
        <p class="slide__result-value">{Second result}</p>
      </div>
    </div>
  </div>
</section>
```

### 16. Numbered Agenda
A numbered list with a small boxed number (01, 02, ...) drawn by a CSS counter, a title in
`<strong>` and an optional description line. `slide__numbered--2col` sets two columns, one
again under 768 px.

```html
<section class="slide">
  <p class="slide__label reveal">{Label}</p>
  <h2 class="slide__heading reveal">{Agenda Title}</h2>
  <ol class="slide__numbered slide__numbered--2col reveal">
    <li><strong>{Item title}</strong><span>{One line on it}</span></li>
    <li><strong>{Item title}</strong><span>{One line on it}</span></li>
    <li><strong>{Item title}</strong><span>{One line on it}</span></li>
    <li><strong>{Item title}</strong></li>
  </ol>
</section>
```

## Engine Contract

What `assets/slide-engine.js` (first line `slide-engine v2`) reads from the markup. Options sit on `.deck` or on `<html>`; the deck wins. `new-deck.py --deck-attr data-NAME=VALUE` (repeatable) writes them onto the deck element, so the fragment stays plain `<section>` elements.

| Markup | Effect |
|---|---|
| `<html lang="de">` | Controls, help, ARIA texts in German; any other language falls back to English |
| `<span data-de>…</span><span data-en>…</span>` pairs | A bilingual deck: only the active language shows (before the engine runs, `<html lang>` decides). Key L and `data-deck="lang"` switch, the choice is kept per deck id, and `data-aria-de` / `data-aria-en` give `aria-label` and `title` per language. A deck without a pair has no L key; `SlideDeck.setLang()` still relabels the controls. An element with both attributes shows in both languages |
| `data-print-notes` | Print and PDF add a notes page after every slide that has `<aside class="notes">` (`render-pdf.cjs --notes` sets it for one render) |
| `data-counter-format="padded"` | Counter reads `01 / 09` |
| `data-dots="off"` | No dot navigation |
| `data-back-href="{url}"` plus optional `data-back-label` | A back link in the top left corner, "← Back to page" (DE "← Zurück zur Seite") unless the label names the page |
| `data-deep-link="off"` | Do not keep the slide in the address |
| `data-track="{name}"` on a slide | The slide belongs to that track (several names separated by spaces); slides without one belong to every track. Old decks: `data-spur` |
| `data-tracks-default="{name}"` | Track shown at start; key F switches between it and all slides. The name need not appear on any slide: a track named here (or in the cycle) shows the untagged slides plus the slides tagged with it |
| `data-tracks-cycle="{a} {b} all"` | Order key F cycles through |
| `data-deck-id="{id}"` | Storage key for the chosen track; defaults to the file path |
| `data-tracks-labels="{name}={label} ..."` | What the track badge, the presenter window and `SlideDeck.trackLabel()` show for a track name, for a deck in another language than its track names; `data-track`, storage and links keep the name. `data-tracks-labels-de` and `data-tracks-labels-en` (same form) win in that language, so a bilingual deck names a track in both; the gate pairs them, so set both or neither. A label is one word (pairs are split at spaces) |
| `data-key-ignore` on any element | Keys pressed inside it are left alone (also inputs, text areas, editable regions) |
| `data-deck="next"`, `prev`, `theme`, `notes`, `help`, `lang`, `track`, `track:{name}`, `goto:{n}`, `goto:#{id}` on a button | Declarative controls, no script needed. `goto:{n}` counts the slides the active track shows, so in a deck with tracks prefer `goto:#{id}`. A `track:{name}` button carries `aria-pressed`, true while its track is active |
| `class="reveal"` | The only entrance class: it starts hidden and appears when its slide is entered; print shows it at once |
| `<aside class="notes">` in a slide | Speaker notes for key N |

Keys: arrows, Space and Shift+Space, Page Up and Down, Home, End, T (theme), F (track), N (notes), L (language, bilingual decks only), ? (help), Esc (close); the `?` help lists them, with V when the deck has a stage and the rows of every deck module. Keys with Ctrl, Cmd or Alt are ignored.

Presenting live, always on:

| Input | Effect |
|---|---|
| B, W | A black or white screen over everything; B on black or W on white lifts it, so does any other key, which then does nothing else, or a click |
| digits, then Enter | Jump to slide n of the active track (the counter's number); Backspace corrects, Esc or any other key drops the number, three seconds without a key too |
| Alt+click | Zoom 2x around the pointer on the active slide; the next click, Esc or a slide change resets |

Accessibility: every slide is `role="group"` with `aria-roledescription` "slide" and `aria-label` "n / total"; every slide but the active one is `inert` (all stay in the DOM for scroll-snap, print shows them all), so browser find (Cmd+F), Tab and a screen reader's browse mode reach the active slide only, in every deck since skill version 2.1.0, with or without modules; to search or read a deck through, use the reading view (`--with read`, key R) or the PDF; a polite live region announces each slide change. Under `prefers-reduced-motion` every animation and transition of the deck, its modules included, ends at once, scrolling jumps and module transitions are skipped.

Deep link: the address keeps `#<id>` when the active slide has an id, else `#<n>`, the 1-based position among the slides the active track shows; while a deck module reports a step above 0 it adds `.<step>` (`#<id>.2`). Every form is read on load and on a hash change. Give the slides people link to an id: `#<n>` depends on the track a viewer has stored, `#<id>` does not.

With the stage module (`new-deck.py --with-stage`) a slide can run a live page: key V, `data-stage` buttons and the `.stage` element are documented in `reference/stage.md`. While focus is inside the stage frame, only V, Esc, Page Up, Page Down, T and L reach the deck; click outside the frame to use the other keys.

Script API: `window.SlideDeck` with `goTo(i)`, `next()`, `prev()`, `current()`, `count()`, `setTrack(name)`, `track()`, `trackLabel(name?)`, `toggleTheme()`, `setTheme(t)`, `setLang(l)`, `toggleNotes()`, `toggleHelp()`, `strings()`, `slides()`, `state()`, `setStep(n)`, `step()`, `reducedMotion()`, `use(module)` and `on(event, fn)` for `ready`, `slidechange`, `trackchange` (detail `{track, label, count}`), `stepchange`, `themechange` and `langchange`. `next()` and `prev()` first offer the move to the deck modules as a step. Modules and the plugin API: `reference/modules.md`. Indexes are 0-based among the slides the active track shows. Old decks reaching for `window.slideEngine` or `window.__slideEngine`, or calling `new SlideEngine()`, get the same single instance.

A filter that would leave no slide shows all of them. Print and PDF always show every slide, one per 297 x 167 mm page. Screens of at least 1500 x 880 and 2200 x 1200 zoom slide content; under 700 px height or 768 px width a slide grows with its content.
