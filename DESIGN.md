---
version: alpha
name: open-bridge
description: Editorial minimalism meets enterprise gravitas — high-contrast neutrals with a single violet-indigo gradient accent. Forks should override `name` and `description` with their own brand voice.

colors:
  # Neutrals — High-contrast editorial palette
  primary: "#111827"              # gray-900 — headlines, core text
  secondary: "#6B7280"             # gray-500 — captions, metadata
  surface: "#FFFFFF"               # page background
  surface-subtle: "#F9FAFB"        # gray-50 — section alternation
  surface-muted: "#F3F4F6"         # gray-100 — chips, inline code bg
  on-primary: "#FFFFFF"            # text on primary surfaces
  on-surface: "#374151"            # gray-700 — body copy
  on-surface-muted: "#6B7280"      # gray-500 — secondary body
  border: "#E5E7EB"                # gray-200 — dividers, card borders
  border-subtle: "#F3F4F6"         # gray-100 — nav, soft separators

  # Accent — Gradient anchors
  accent-from: "#667EEA"           # indigo-400 — gradient start
  accent-to: "#764BA2"             # purple-700 — gradient end
  accent: "#6366F1"                # indigo-500 — --primary-color
  accent-secondary: "#8B5CF6"      # violet-500 — --secondary-color

  # Feature category gradients (geometric icons)
  feature-purple-from: "#9333EA"
  feature-purple-to: "#4F46E5"
  feature-blue-from: "#2563EB"
  feature-blue-to: "#0891B2"
  feature-orange-from: "#EA580C"
  feature-orange-to: "#DC2626"
  feature-pink-from: "#9333EA"
  feature-pink-to: "#DB2777"
  feature-indigo-from: "#4F46E5"
  feature-indigo-to: "#9333EA"

  # Semantic
  success: "#10B981"
  info: "#3B82F6"
  attention: "#8B5CF6"

  # Dark mode pair (applied via .dark class)
  dark-surface: "#111827"          # gray-900
  dark-surface-subtle: "#1F2937"   # gray-800
  dark-surface-muted: "#374151"    # gray-700
  dark-on-surface: "#D1D5DB"       # gray-300
  dark-border: "#374151"           # gray-700
  dark-accent-from: "#A78BFA"      # violet-400 — lifted for contrast
  dark-accent-to: "#818CF8"        # indigo-400

typography:
  display:
    fontFamily: Inter
    fontSize: 72px                 # hero headline
    fontWeight: 300                # font-light is the signature
    lineHeight: 1.05
    letterSpacing: -0.02em
  h1:
    fontFamily: Inter
    fontSize: 48px                 # section headlines
    fontWeight: 300
    lineHeight: 1.1
    letterSpacing: -0.02em
  h2:
    fontFamily: Inter
    fontSize: 36px
    fontWeight: 300
    lineHeight: 1.15
    letterSpacing: -0.01em
  h3:
    fontFamily: Inter
    fontSize: 24px                 # card titles
    fontWeight: 500
    lineHeight: 1.3
  h4:
    fontFamily: Inter
    fontSize: 20px
    fontWeight: 500
    lineHeight: 1.4
  body-xl:
    fontFamily: Inter
    fontSize: 20px                 # hero subtitle, lead
    fontWeight: 300
    lineHeight: 1.6
  body-lg:
    fontFamily: Inter
    fontSize: 18px                 # prose lead
    fontWeight: 400
    lineHeight: 1.6
  body-md:
    fontFamily: Inter
    fontSize: 16px                 # default
    fontWeight: 400
    lineHeight: 1.6
  body-sm:
    fontFamily: Inter
    fontSize: 14px                 # meta, chips
    fontWeight: 400
    lineHeight: 1.5
  label-caps:
    fontFamily: Inter
    fontSize: 14px                 # stat labels, eyebrows
    fontWeight: 500
    lineHeight: 1.2
    letterSpacing: 0.05em          # uppercase tracking
  stat-display:
    fontFamily: Inter
    fontSize: 36px                 # KPI numbers
    fontWeight: 300
    lineHeight: 1
    letterSpacing: -0.02em
  button:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: 500
    lineHeight: 1.25
  code:
    fontFamily: "SF Mono, Monaco, Cascadia Code, Roboto Mono, Consolas, monospace"
    fontSize: 14px
    fontWeight: 400

rounded:
  none: 0px
  sm: 4px                          # chips, inline code
  md: 8px                          # buttons, inputs
  lg: 12px                         # cards (rounded-xl in usage)
  xl: 16px                         # CTA containers (rounded-2xl)
  full: 9999px                     # pills, avatars

spacing:
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 32px
  "2xl": 48px
  "3xl": 64px
  "4xl": 96px                      # section vertical rhythm (py-24)
  "5xl": 128px

components:
  # ——— Buttons ———
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    typography: "{typography.button}"
    rounded: "{rounded.md}"
    padding: 16px 32px
  button-primary-hover:
    backgroundColor: "#1F2937"     # gray-800
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.on-surface}"
    typography: "{typography.button}"
    rounded: "{rounded.md}"
    padding: 16px 32px
  button-secondary-hover:
    backgroundColor: "{colors.surface-subtle}"

  # ——— Navigation ———
  nav-bar:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.on-surface}"
    height: 80px
    padding: 0px 24px
  nav-link:
    textColor: "{colors.on-surface-muted}"
    typography: "{typography.body-md}"
  nav-link-hover:
    textColor: "{colors.primary}"

  # ——— Cards ———
  card-feature:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.on-surface}"
    rounded: "{rounded.lg}"
    padding: 32px
  card-feature-hover:
    backgroundColor: "{colors.surface}"
  card-cta:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.on-surface}"
    rounded: "{rounded.xl}"
    padding: 48px

  # ——— Badges & Chips ———
  badge-featured:
    backgroundColor: "{colors.surface-muted}"
    textColor: "{colors.on-surface}"
    typography: "{typography.body-sm}"
    rounded: "{rounded.full}"
    padding: 8px 16px
  chip-deliverable:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.on-surface}"
    typography: "{typography.body-sm}"
    rounded: "{rounded.full}"
    padding: 4px 12px

  # ——— Process step ———
  step-number:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.primary}"
    rounded: "{rounded.full}"
    size: 64px

  # ——— Inputs ———
  input-text:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.primary}"
    rounded: "{rounded.md}"
    padding: 12px 16px
---

## Overview

**Editorial Minimalism meets Enterprise Gravitas.** This visual identity
communicates strategic clarity through restraint: generous whitespace, hairline
borders, and a single gradient accent that signals transformation without
shouting. The feel is that of a premium consultancy whitepaper crossed with a
modern software product — composed, confident, deliberately unflashy. Forks
are encouraged to retune the accent and prose to match their own brand voice.

Every design choice should reinforce one idea: *complex technology, explained
with calm authority.* Avoid dark patterns, hype gradients on every surface, or
dense dashboards. Let the grid breathe.

**Signature moves**

- `font-weight: 300` on all large headings — lightness is the brand voice.
- A purple→indigo gradient (`#667EEA → #764BA2`) reserved **only** for accent
  words inside headings, the wordmark, and decorative geometric icons. Never on
  body copy, borders, or backgrounds.
- Section rhythm alternates pure white with `bg-gradient-subtle` (near-white to
  `#F9FAFB`). No colored section backgrounds.
- Content is centered with `max-width: 48rem–80rem` wrappers. Edge-to-edge
  layouts are reserved for the hero only.

## Colors

High-contrast neutrals do 95% of the work. The accent gradient is a supporting
character — present, never dominant.

- **Primary `#111827`** — Deep ink for all headlines, body copy, and primary
  buttons. Use on white/subtle surfaces only.
- **Secondary `#6B7280`** — Slate gray for captions, metadata, icon strokes,
  and muted UI chrome.
- **Surface `#FFFFFF`** — Default page background. Pairs with
  `surface-subtle #F9FAFB` for the alternating-section rhythm.
- **Border `#E5E7EB`** — 1px hairlines on cards, nav, and dividers. Never
  heavier than 1px in light mode.
- **Accent Gradient `#667EEA → #764BA2`** — The brand signature gradient. Applied via
  `background-clip: text` to one or two accent words per headline, to the
  secondary half of the wordmark, and as the fill for the six geometric feature
  icons. Using it anywhere else cheapens it.
- **Feature gradients** — Each competency icon gets its own 2-stop gradient
  drawn from the purple/blue/orange families (`feature-*-from/to`). These are
  decorative only; never use them as button or text colors.

### Dark mode

When `.dark` is active on `<html>`, swap surfaces to the `dark-*` tokens:
`surface → #111827`, `surface-subtle → #1F2937`, `on-surface → #D1D5DB`. The
accent gradient lifts to `#A78BFA → #818CF8` so it stays legible against dark
backgrounds. The brand voice does not change — it is still restrained, still
editorial.

### Accessibility

- Primary on Surface: 16.1:1 (AAA)
- On-Surface on Surface: 9.3:1 (AAA)
- Secondary on Surface: 4.8:1 (AA body)
- On-Primary (white) on Primary: 16.1:1 (AAA)

Gradient text must always sit on solid `surface` or `surface-subtle` — never
over imagery or color. The accent gradient is not a guaranteed-contrast color
and must not be used for interactive text targets without a solid fallback.

## Typography

**Inter** is the sole typeface, weights 300 / 400 / 500 / 600 / 700.

> **Never load fonts from Google Fonts (or any third-party font CDN).** It is a
> privacy/GDPR violation — the CDN logs the visitor's IP on every page. Inter is
> open (SIL OFL); ship it **self-hosted** (a local `@font-face` with the woff2
> bundled or referenced relative to the page), or fall back to the system stack
> `Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, Roboto,
> sans-serif` (San Francisco on macOS is the closest cousin). No
> `fonts.googleapis.com` / `fonts.gstatic.com` links, ever — in any generated
> HTML, email, slide, or dashboard.

The defining rule: **large = light**. Any text at 24px or above uses
`font-weight: 300` unless it is a card title (500) or button label (500). This
inversion of the usual "big = bold" convention is the single most important
typographic signal of the brand.

- **Display (72px/300)** — Hero headline. One per page.
- **H1 (48px/300)** — Section headlines. Always paired with a subtitle.
- **H3 (24px/500)** — Card and step titles. Medium weight re-establishes
  hierarchy inside dense grids.
- **Body-xl (20px/300)** — Hero subtitle and section intros. Light weight so it
  reads as continuation of the headline, not as a separate block.
- **Body-md (16px/400)** — All default prose. `line-height: 1.6` is mandatory.
- **Stat-display (36px/300)** — KPIs. Pair with a 14px uppercase `label-caps`
  underneath for the classic consulting-stat presentation.

Headlines commonly mix weights inline: `<span>Digital Transformation</span>`
in `font-weight: 300` followed by `<span class="text-gradient">accelerate
intelligence</span>` in `font-weight: 400`. The gradient span always gets a
one-step-heavier weight so it reads as the focal point.

## Layout

- **Container**: `max-width: 80rem` (1280px) with `padding-inline: 24px`.
  Centered. Hero content narrows further to `max-width: 64rem` (5xl).
- **Section rhythm**: vertical padding is always `96px` top and bottom (`py-24`).
  Never less. Alternate `surface` and `surface-subtle` backgrounds to create
  cadence.
- **Grid**: feature and team cards use CSS grid with `gap: 32px`. Breakpoints
  at 1 / 2 / 3 columns (md/lg) for features, 1 / 2 / 5 for team.
- **Nav**: fixed, 80px tall, full-width translucent (`backdrop-filter: blur`),
  1px bottom border. Content underneath gets no top padding — the hero absorbs
  the nav height through its own `min-height: 100vh`.
- **Asymmetry is banned.** Hero content is center-aligned. Feature and team
  grids are center-aligned within their containers. This is a deliberate choice
  to reinforce editorial composure.

## Elevation & Depth

Elevation is **whisper-quiet**. The brand does not use bold drop shadows,
neumorphism, or layered chrome. Three shadow tiers only:

- **shadow-soft** — `0 4px 6px -1px rgba(0,0,0,0.05), 0 2px 4px -1px rgba(0,0,0,0.03)`.
  Default for cards at rest.
- **shadow-hover** — `0 20px 25px -5px rgba(0,0,0,0.08), 0 10px 10px -5px rgba(0,0,0,0.04)`
  plus `transform: translateY(-2px)`. Applied on hover for features and the
  CTA card only.
- **No shadow** — Nav, buttons, chips, step numbers. Depth here is conveyed
  through 1px borders, not shadows.

In dark mode, soften the shadow alpha (`0.2` / `0.1`) and lean more on border
and surface contrast for separation. Glassmorphism (`backdrop-filter: blur(10px)`
with `rgba(255,255,255,0.1)`) is permitted **only** on the fixed navigation.

## Shapes

- Corners scale with scale: `sm (4px)` for chips, `md (8px)` for buttons and
  inputs, `lg (12px)` for feature/content cards, `xl (16px)` for the CTA
  container.
- The step-number circle and all pill chips use `rounded.full`.
- **Geometric icons** are the one place shape carries meaning. The six
  competency cards each own a distinct primitive — diamond, triangle, circle,
  hexagon, star, and a 4-rhombus "data-mesh" composition — drawn as 100×100
  SVGs filled with their category gradient. The icon is the card's visual
  anchor; never combine it with a photograph or additional illustration.
- Avoid decorative strokes, dashed borders, inner shadows, or textured fills.
  If a surface needs visual interest, use the dotted hero pattern at 2.5%
  opacity — nothing else.

## Components

### Buttons

Two variants, always rectangular with `rounded.md` corners.

- **Primary** — Deep ink (`#111827`) with white text. Default CTA. Hover lifts
  to `#1F2937`. In dark mode the background shifts to `accent #6366F1`.
- **Secondary** — White background, `border 1px border-color`, gray-700 text.
  Used as the lower-priority sibling of a primary CTA.
- Size: 48px tall for marketing pages, 40px for inline/sm variants. Horizontal
  padding is `32px` (md) / `16px` (sm). Never use full-width buttons on desktop.
- Icons inside buttons are 20×20 (`w-5 h-5`), with `margin-left: 8px` when
  trailing, and should translate `+4px` on hover when the button implies
  forward motion (e.g. "Book a consultation").

### Cards

- **Feature card** — white surface, 1px `border-color` border, `rounded.lg`,
  `padding: 32px`. Hover reveals a 4px gradient underline at the bottom edge
  that scales from 0 to 100% width (`transform-origin: left`). The card itself
  lifts `-2px` and swaps to `shadow-hover`.
- **Team card** — 256px-tall gradient portrait with initials placeholder (until
  real photography is supplied), hover-reveals a "View profile" pill. The
  portrait applies `filter: grayscale(1)` at rest and transitions to
  `grayscale(0)` on group hover over 500ms.
- **CTA card** — white/glass surface inside a `surface-subtle` section,
  `rounded.xl`, `padding: 48px`, with a central primary button. No border.

### Navigation

Fixed top bar. Left: wordmark (organization name in two weights — base
in `font-weight: 300`, suffix in `font-weight: 400` with gradient
text-clip). Center: 4 section links in `body-md` with hover lifting
color to `primary`. Right: a primary "Contact" button plus a theme
toggle. Collapses to a hamburger below 768px.

### Process timeline

A vertical rail: 64px-diameter numbered circle on a 2px vertical line
(`border-color`). Each step stacks an `h3` title, a `body-lg` description, and
a wrapping row of deliverable chips. Steps are spaced by `48px` vertically and
the rail hides below 768px (number circles remain).

### Stat blocks

Three-column grid. Each stat is a centered `stat-display` number over a
`label-caps` label in `secondary`. Minimum gap: `32px`. Never decorate stats
with icons, sparklines, or dividers — the restraint is the point.

### Hero badge

A pill-shaped "Featured Insight" chip above the display headline. Background
`surface-muted`, `body-sm` text, arrow glyph (`→`) separating the eyebrow from
the linked teaser. Hover lifts background to `#E5E7EB`.

## Do's and Don'ts

**Do**

- Reserve the accent gradient for 1–2 words per heading and the `-lab` half of
  the wordmark.
- Use `font-weight: 300` on every heading ≥24px. Resist the urge to bold.
- Alternate `surface` and `surface-subtle` to pace long pages. Keep vertical
  rhythm at `py-24`.
- Lead every major section with an H1 + subtitle + short body intro, centered,
  max-width ≤ 48rem.
- Draw placeholder portraits with gradient + initials when real photography is
  unavailable. Keep the grayscale-on-rest, color-on-hover pattern.
- Animate opacity and transform only. Duration `300ms`, easing `ease-out`.

**Don't**

- Never apply the accent gradient to body copy, borders, buttons, or large
  surfaces. It loses meaning when repeated.
- Never mix a second typeface. Inter is the system; hierarchy comes from
  weight and size.
- Never use colored section backgrounds, neon accents, or saturated brand
  colors for non-decorative UI. The accent gradient is the only color event.
- Never stack shadows, add inner glows, or use `box-shadow` blur radii above
  `25px`. Elevation whispers.
- Never right-align or stagger section content. Editorial composure depends on
  centered layouts.
- Never pair the geometric icon with a photograph, emoji, or second
  illustration inside the same card. One visual anchor per card.
- Never animate color transitions — only `transform` and `opacity`. This is
  locked in the stylesheet to prevent dark-mode flicker.

## Maintaining this file

This is a token-level design-system manifest in the
[Google Labs DESIGN.md format (alpha)](https://github.com/google-labs-code/design.md):
YAML front matter holds machine-readable tokens (`version`, `name`,
`description`, `colors`, `typography`, `rounded`, `spacing`, `components`);
the markdown body holds the rationale. Tokens are normative exact values;
prose explains when and why to apply them.

**Section order is fixed.** Prose sections may be omitted but must appear in
this order: Overview, Colors, Typography, Layout, Elevation & Depth, Shapes,
Components, Do's and Don'ts. Duplicate headings are a hard error.

**Token naming conventions**

- Colors: surfaces `surface[-subtle|-muted]`, text `on-*`, accent
  `accent[-from|-to|-secondary]`, icon gradients `feature-<hue>-from/-to`,
  dark-mode counterparts prefixed `dark-`.
- Typography: `display`, `h1`–`h4`, `body-{xl,lg,md,sm}`, `label-caps`,
  `stat-display`, `button`, `code`. The `large = light` rule (≥24px →
  `fontWeight: 300`) is the core brand constraint — prose must change with it.
- Components: lowercase kebab-case; states as sibling entries
  (`button-primary`, `button-primary-hover`), one recipe per visual state.

**Adding a token.** Never hand-pick brand colors in consuming code — if a
token is missing, add it here first, then reference it. New colors go into
`colors:` (with a `dark-` counterpart for surface/text tokens) and get a
mention with role + contrast note in the Colors prose. Components reference
tokens via `{colors.*}` / `{typography.*}` — never raw hex in `components:`.
Renames must update all references in the same commit.

**Consumers.** Skills and agents that emit HTML, PDF, slides, certificates,
dashboards, or styled emails read their palette, typography, and spacing from
this file instead of inventing them. Keep copies in sibling UI-generating
repos byte-identical — one source commit updates them all.

**Change discipline.** One tone — factual: each change is a small, described
commit (e.g. `tokens(colors): tighten accent-from`); lint with
`npx @google/design.md lint DESIGN.md` before committing; on a spec version
bump, update `version:`, re-lint, and diff against the previous revision.
