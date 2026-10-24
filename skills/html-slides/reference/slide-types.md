# Slide Types Reference

11 slide types with full HTML examples. Read this file when writing the slides; the decks are assembled by `scripts/new-deck.py`.

## Color System

Available accent colors for `var(--{color})` and `var(--{color}-dim)`:

| Color | Use for |
|-------|---------|
| `accent` / `green` | Default, positive, success, new |
| `red` | Problems, warnings, "before" state |
| `amber` | Caution, strings, configuration |
| `cyan` | Info, keywords, technical details |

Add custom semantic colors by extending `:root` with additional `--{name}` / `--{name}-dim` pairs.

With the `design` preset (a DESIGN.md is present) these colours are status colours
and carry state only: a heading or label colour and a glow taken from them give way
to the heading colour and the accent, so write `accent` there. Buttons take
`.slide__btn` (and `.slide__btn--primary` for the one main action) inside
`.slide__actions`; the primary one is the brand's `primary` fill.

## Slide Types

### 1. Title Slide
Center-aligned, large display text, accent-colored heading. Use for opening slide.

```html
<section class="slide slide--title slide--with-grid">
  <div class="reveal">
    <p class="slide__subtitle" style="margin-bottom:clamp(16px,2vh,32px);">{subtitle}</p>
  </div>
  <h1 class="slide__display reveal">{Main Title}</h1>
  <div class="reveal">
    <p class="slide__subtitle" style="margin-top:clamp(16px,2vh,32px);">{tagline}</p>
  </div>
</section>
```

### 2. Section Divider
Big faded number in background, heading + subtitle. Use to introduce new sections.

```html
<section class="slide slide--divider" style="background-image:radial-gradient(ellipse at 80% 60%, var(--{color}-dim) 0%, transparent 40%);">
  <span class="slide__number" aria-hidden="true">{01}</span>
  <div>
    <h2 class="slide__heading reveal" style="color:var(--{color});">{Section Title}</h2>
    <p class="slide__subtitle reveal" style="margin-top:12px;">{Section subtitle}</p>
  </div>
</section>
```

### 3. Content (Text + Aside)
3:2 grid with bullet list left, optional visual right. Main workhorse slide.

```html
<section class="slide slide--content" style="background-image:radial-gradient(ellipse at 20% 80%, var(--{color}-dim) 0%, transparent 45%);">
  <div class="slide__inner">
    <div>
      <p class="slide__label reveal" style="color:var(--{color});">{Label}</p>
      <h2 class="slide__heading reveal">{Heading}</h2>
      <ul class="slide__bullets">
        <li class="reveal">{Point 1}</li>
        <li class="reveal">{Point 2}</li>
      </ul>
    </div>
    <div class="slide__aside reveal">
      <!-- Optional: SVG diagram, small code block, or icon -->
    </div>
  </div>
</section>
```

### 4. Split (Two Panels)
Side-by-side comparison. Use for before/after, pros/cons.

```html
<section class="slide slide--split">
  <div class="slide__panels">
    <div class="slide__panel slide__panel--primary">
      <p class="slide__label reveal" style="color:var(--red);">{Left Label}</p>
      <h2 class="slide__heading reveal" style="font-size:clamp(22px,3.5vw,36px);">{Left Title}</h2>
      <ul class="slide__bullets" style="margin-top:16px;">
        <li class="reveal">{item}</li>
      </ul>
    </div>
    <div class="slide__panel slide__panel--secondary">
      <p class="slide__label reveal" style="color:var(--green);">{Right Label}</p>
      <h2 class="slide__heading reveal" style="font-size:clamp(22px,3.5vw,36px);">{Right Title}</h2>
      <ul class="slide__bullets" style="margin-top:16px;">
        <li class="reveal">{item}</li>
      </ul>
    </div>
  </div>
</section>
```

### 5. Table
Full-width data table with header and hover effects. The card is as tall as its rows.

```html
<section class="slide slide--table" style="background-image:radial-gradient(ellipse at 70% 30%, var(--cyan-dim) 0%, transparent 40%);">
  <p class="slide__label reveal">{Label}</p>
  <h2 class="slide__heading reveal" style="font-size:clamp(22px,3.5vw,36px);">{Title}</h2>
  <div class="table-wrap reveal" style="margin-top:clamp(8px,1.5vh,20px);">
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
<section class="slide slide--code" style="background-image:radial-gradient(ellipse at 50% 80%, var(--accent-dim) 0%, transparent 40%);">
  <h2 class="slide__heading reveal" style="text-align:center;font-size:clamp(22px,3.5vw,36px);">{Title}</h2>
  <div class="slide__code-block reveal" style="margin-top:clamp(12px,2vh,24px); max-width:900px;">
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

```html
<section class="slide">
  <p class="slide__label reveal">{Label}</p>
  <h2 class="slide__heading reveal" style="font-size:clamp(22px,3.5vw,36px);">{Title}</h2>
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
Gradient (or image) background under a veil in the theme background, text at the bottom; reads in light and dark. Use for the final "Questions?" slide.

```html
<section class="slide slide--bleed">
  <div class="slide__bg slide__bg--gradient"></div>
  <div class="slide__scrim"></div>
  <div class="slide__content">
    <p class="slide__label reveal" style="color:var(--accent);">{call to action}</p>
    <h2 class="slide__heading reveal" style="font-size:clamp(32px,6vw,64px);">{Closing Text}</h2>
    <p class="slide__subtitle reveal" style="margin-top:12px;">{subtitle}</p>
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

## Engine Contract

What `assets/slide-engine.js` (first line `slide-engine v2`) reads from the markup. Options sit on `.deck` or on `<html>`; the deck wins. `new-deck.py --deck-attr data-NAME=VALUE` (repeatable) writes them onto the deck element, so the fragment stays plain `<section>` elements.

| Markup | Effect |
|---|---|
| `<html lang="de">` | Controls, help, ARIA texts in German; any other language falls back to English |
| `data-counter-format="padded"` | Counter reads `01 / 09` |
| `data-dots="off"` | No dot navigation |
| `data-back-href="{url}"` plus optional `data-back-label` | A back link in the top left corner |
| `data-deep-link="off"` | Do not keep the slide in the address |
| `data-track="{name}"` on a slide | The slide belongs to that track (several names separated by spaces); slides without one belong to every track. Old decks: `data-spur` |
| `data-tracks-default="{name}"` | Track shown at start; key F switches between it and all slides. The name need not appear on any slide: a track named here (or in the cycle) shows the untagged slides plus the slides tagged with it |
| `data-tracks-cycle="{a} {b} all"` | Order key F cycles through |
| `data-deck-id="{id}"` | Storage key for the chosen track; defaults to the file path |
| `data-tracks-labels="{name}={label} ..."` | What the track badge and `SlideDeck.trackLabel()` show for a track name, for a deck in another language than its track names; `data-track`, storage and links keep the name |
| `data-key-ignore` on any element | Keys pressed inside it are left alone (also inputs, text areas, editable regions) |
| `data-deck="next"`, `prev`, `theme`, `notes`, `help`, `track`, `track:{name}`, `goto:{n}`, `goto:#{id}` on a button | Declarative controls, no script needed. `goto:{n}` counts the slides the active track shows, so in a deck with tracks prefer `goto:#{id}`. A `track:{name}` button carries `aria-pressed`, true while its track is active |
| `class="reveal"` | The only entrance class: it starts hidden and appears when its slide is entered; print shows it at once |
| `<aside class="notes">` in a slide | Speaker notes for key N |

Keys: arrows, Space and Shift+Space, Page Up and Down, Home, End, T (theme), F (track), N (notes), ? (help), Esc (close); the `?` help lists them, with V when the deck has a stage. Keys with Ctrl, Cmd or Alt are ignored.

Deep link: the address keeps `#<id>` when the active slide has an id, else `#<n>`, the 1-based position among the slides the active track shows. Both forms are read on load and on a hash change. Give the slides people link to an id: `#<n>` depends on the track a viewer has stored, `#<id>` does not.

With the stage module (`new-deck.py --with-stage`) a slide can run a live page: key V, `data-stage` buttons and the `.stage` element are documented in `reference/stage.md`. While focus is inside the stage frame, only V, Esc, Page Up and Page Down reach the deck; click outside the frame to use the other keys.

Script API: `window.SlideDeck` with `goTo(i)`, `next()`, `prev()`, `current()`, `count()`, `setTrack(name)`, `track()`, `trackLabel(name?)`, `toggleTheme()`, `toggleNotes()`, `toggleHelp()`, `strings()` and `on(event, fn)` for `ready`, `slidechange` and `trackchange` (detail `{track, label, count}`). Indexes are 0-based among the slides the active track shows. Old decks reaching for `window.slideEngine` or `window.__slideEngine`, or calling `new SlideEngine()`, get the same single instance.

A filter that would leave no slide shows all of them. Print and PDF always show every slide, one per 297 x 167 mm page. Screens of at least 1500 x 880 and 2200 x 1200 zoom slide content; under 700 px height or 768 px width a slide grows with its content.
