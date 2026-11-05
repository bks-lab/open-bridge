---
scope: core
description: Cross-skill gates for generated visual deliverables — theme toggle on every HTML page, every figure carries its source
---

# Visual Output — gates for generated deliverables

Any skill that emits a user-facing visual deliverable (HTML pages, slide
decks, dashboards, reports) obeys these gates — on top of the palette,
typography, and spacing tokens of its design: the one
`python3 scripts/designs.py resolve` names for the work (a context's or
persona's `design_ref`, the theme's design, else [`../DESIGN.md`](../DESIGN.md);
see [§ Designs in this Bridge](../DESIGN.md#designs-in-this-bridge)). The design
governs *how it looks*; this rule governs *two behaviours it must have*. The
gates apply to **every** such deliverable, including hand-built ones — not
only the output of `html-slides` or `creative-design-stack`.

## Gate 1 — every HTML page has a user-selectable light/dark toggle

A silent `@media (prefers-color-scheme)` is **not enough**. Every HTML page
ships a manual override the user can flip (OS preference as fallback):
beamers and foreign screens are unpredictably bright or dark, and control
belongs *in the deck*, reachable mid-talk.

Required pattern (same one baked into `html-slides`):

1. **Inline head script before the CSS** — sets the theme class from
   `localStorage` (or OS preference) so there is no flash of the wrong theme.
2. **`:root.theme-light` / `:root.theme-dark` overrides** plus a media-query
   fallback gated on `:not(.theme-dark):not(.theme-light)` — so the manual
   choice always wins and the OS preference applies only when none is set.
3. **A toggle control top-right** (sun/moon SVG), a **`T` key binding**, and
   **`localStorage` persistence** of the choice.

`html-slides`, `creative-design-stack`, and `html-canvas` emit this
automatically. A hand-built page must copy the same three pieces. An existing
deck without it gets patched retroactively on request.

## Gate 2 — every figure carries its source

Every figure, metric, amount, or market value in a deliverable carries
**where it came from** — a concrete document path or a named market source,
not a bare number. Provenance is the point: the reader (and a later session)
must be able to trace any number back.

- **Markdown** — tables get a **source column** (short tags like `contract` /
  `summary` plus a legend listing the file paths), or a `**Sources:**` line.
- **HTML dashboards** — the same figures appear here too, **not only in the
  Markdown**: a facts / key-figures section with a `.src` "Sources:" line
  carrying the document paths or links.
- **Web-researched values** (e.g. a market value) always carry source + year
  + range, and the "asking price ≠ sale price" caveat where relevant.

The HTML surface is not optional: if a deliverable has a Markdown version with
sourced figures, the HTML dashboard reproduces them — the user wants the
key figures visually at hand, not buried in Markdown prose.

## Gate 3: a drawing states what it measured, and shape carries the meaning

A figure is believed faster than a sentence and is almost never diffed, so a
picture is the cheapest place in a repository to assert something nobody
measured. Two rules follow, and both have already cost a real defect here.

**Two questions get two marks, never one.** Where a drawing shows both an
intention and an observation (a plan against what happened, a target against a
reading, a schedule against a run), each mark comes from the source that owns
that question, and neither is derived from the other. Collapsing them looks
tidier and is a claim: the `workload` calendar drew a job that fires at 07:20
and never had as an appointment kept, because its mark asked "is there a trace
at all" and put that answer on the appointment. The only trace came from a
verification run eight hours later. Matching an observation to an intention
needs a history and a tolerance; where either is missing, draw both marks and
let the reader see the distance between them.

**Anything that cannot be placed says so.** An empty lane, an unlabelled gap or
a silently dropped point reads as "nothing scheduled here", which is a different
statement from "nothing here could place this". Name the reason in the drawing.

**A value in one frame is not placed on an axis in another.** A stamp written in
UTC on an axis showing a machine's local day is wrong for half the year and
looks perfectly reasonable all of it. Convert only from a declared, checked
offset; where none is declared, leave the mark off and say why.

**Colour never carries a meaning alone.** Every mark that means something also
differs in shape (hollow, filled, dashed, dotted, diamond, band), and every
shape that appears is in a legend generated from the same list the marks are
drawn from, so a shape cannot reach the page without an explanation. Roughly one
reader in twelve does not separate red from green.

## Gate 4: a generated page is plain text all the way down

An escape written for the target language sits inside a HOST language literal
and is consumed by the host FIRST. The source reads correctly, because it is
correct, in the wrong language.

Measured 2026-08-24. A stylesheet inside a Python triple-quoted string carried
the CSS escape for a middle dot, written as a backslash and `00B7`. Python reads
a backslash followed by two zeros as an OCTAL escape long before any browser
reads CSS, so the value carried a real NUL byte. The page carried it, and
`workload publish` died inside `subprocess` with `embedded null byte`, an error
naming neither CSS, nor the stylesheet, nor the character. It then happened a
SECOND time within the hour, in the comment written to explain the first.

**Write the character, never an escape for it.** This is the general UTF-8 house
rule, and this is the one case where breaking it is silent rather than merely
ugly. Where an escape genuinely has to survive into the target, double the
backslash or make the literal raw, and say in a comment which language is meant
to read it.

**The gate is mechanical, and narrow so it can be hard.** No control character
may appear in a string that becomes markup, a stylesheet or a script. There is
no legitimate instance of that, so it fails the build rather than warning. It
deliberately does NOT flag escapes as such: a NUL used as a field separator, an
ANSI sequence written for a terminal, an escape inside a regular expression each
have the right consumer and are correct. A guard that cries wolf gets switched
off, and then it guards nothing.

    python3 scripts/check-generated-output.py

Runs in CI and pre-commit. Contract:
`scripts/tests/test_generated_output_escapes.py`.

**A generator also proves it about its own artifact.** The source scan sees
Python string literals; it cannot see a shell heredoc, a JS template literal, or
a byte that arrived from data. So the renderer's own suite asserts the rendered
page carries no control character and survives a round trip as a process
argument, which is the operation that actually failed. See
`ThePageIsPlainTextAllTheWayDown` in `skills/workload/tests/test_view.py`.

## Related

- [`../DESIGN.md`](../DESIGN.md): the default design and the index to `identity/designs/`; read the design `scripts/designs.py resolve` names before generating any visual
- `skills/workload/engine/view.py` — the calendar Gate 3 came out of
- `feedback_no_google_fonts_only_open` (memory) — never embed Google Fonts in generated HTML/email/slides/PDF
