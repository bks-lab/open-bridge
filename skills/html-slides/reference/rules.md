# Design Rules

Read this file when planning the content and when writing the slides.

## DESIGN.md wins

When the Bridge has a `DESIGN.md`, it is the only source of colour and type in a
deck. `scripts/new-deck.py` then defaults to the `design` preset: colours reach
the deck through `presets/design.map.yaml` and `html-canvas/scripts/design-to-css.py`,
families and weights through DESIGN.md typography and `embed-fonts.py`. Nothing in
the deck is hand-picked, and `html-canvas/scripts/verify-page.py` holds it to that
(a hex value DESIGN.md does not declare is an error).

- A style preset (every preset except `design`) is chosen by name, for a deck
  that should not carry the house brand, or where no DESIGN.md exists.
- The rules below that name fonts or colours apply to **style presets only**.
  DESIGN.md is a decision already taken: if it names Inter, the deck uses Inter.
- The `design` preset sets display type to weight 500 with `-0.01em` tracking,
  and keeps decoration (gradient zones, backdrop blur) behind the class `fx` on
  `<html>`, the `.deck` or one `.slide`. Without `fx` a slide stays flat.

## Anti-AI-Slop Blacklist

| Category | Banned | Why |
|----------|--------|-----|
| Fonts (style presets only) | Inter (not Inter Tight), Roboto, Arial as display font | Generic, instantly recognizable as AI output. Inter Tight is exempt: distinct optical size. A family DESIGN.md names is never banned |
| Colors (style presets only) | `#6366f1` (indigo), purple gradients on white | Tailwind defaults, template look. DESIGN.md colours are used as declared |
| Layouts | Identical 3-card grids without variation | SaaS landing page cliche |
| Decoration | Gradient blobs unrelated to content | Filler, not intentional design |
| Icons | Generic icon sets as slide main element | Placeholder instead of real content |

## Positive Design Rules

- Every preset has a `personality`, and generated slides must match it
- Font pairings must have contrast (display ≠ body family, except when both are the same optical family like Inter Tight)
- Minimum 2 different slide types per deck
- Color accents used deliberately, not everywhere
- No two presentations should look identical: vary the slide type mix even with the same preset

## Content-Density Limits

**Rule: Always split, never cram.**

| Slide Type | Limit | On Exceed |
|------------|-------|-----------|
| Title | 1 heading + 1 subtitle | Shorten, never wrap |
| Content | Max 6 bullets | Split into 2 slides |
| Split | Max 4 items per side | Split or convert to table |
| Card Grid | Max 6 cards | Second card grid slide |
| Code | Max 20 lines | Cut to essence |
| Table | Max 8 visible rows | Scroll hint or split |
| Pipeline | Max 6 steps | Group or split to 2 slides |

## General Design Rules

1. **Every element that should animate** gets class `reveal`
2. **Background gradients** via inline `style` with `radial-gradient` for subtle color zones (with the `design` preset they show only behind `.fx`)
3. **Grid backgrounds** via `slide--with-grid` class for dot pattern
4. **10-15 slides** is ideal for a focused presentation
5. **Decorative SVGs** can be added with `class="slide__decor"` (absolute positioned, pointer-events:none)
