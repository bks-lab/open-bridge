---
summary: "Parallel-builder subagent workflow for multi-page html-canvas kits, plus the quality/voice/accessibility bar every deliverable must clear"
type: reference
last_updated: 2026-06-01
related:
  - skills/html-canvas/SKILL.md
  - rules/promote-safety.md
---

# html-canvas — Build Workflow & Quality Bar

## Single page
Copy `assets/shell.html`, fill the placeholders, compose `<main>` from
`references/sections.md`, paste any behaviours from `interactivity.md` (+
`animations.css` if you want motion). Render light **and** dark, **and** DE **and**
EN before calling it done. File it under `work/tasks/<slug>/deliverables/`.

## Multi-page / multi-board kit — parallel builders
A kit (e.g. 8 boards, an N-section explainer split per author) builds in three
phases with subagents sharing a **byte-identical shell** — never one serial pass.
This is the proven pattern from the 12-board reference set (1 audit → 6 parallel
builders on a shared CSS contract → 1 adversarial review).

**Phase 0 — Convention audit (one agent, blocking).** Read DESIGN.md (token SoT),
SOUL.md (voice), and decide the per-page structure. Emit a **shared contract**
every builder pastes verbatim: (a) the `:root` + `html.dark` token block (run
`design-to-css.py`); (b) the base styles + theme/lang pre-paint + controllers from
`shell.html`; (c) the print block; (d) the CSS for the section blocks the kit uses.
This contract is the *only* coupling between builders — it is what guarantees the
kit looks like one set.

**Phase 1 — Parallel builders (N agents, one message).** Each agent owns exactly
one output file and gets: the shared contract (paste-verbatim), its page's source
data, and which section blocks to compose. Builders never edit each other and
never re-derive tokens/toggles — they assemble blocks and author the DE/EN
dual-span content. Spawn via the `Task` tool / cmux workspaces; emit all calls in
one message so they run concurrently.

**Phase 2 — Adversarial review (one agent, blocking).** Prompt posture:
*"Assume NOTHING is intentional — find real mistakes."* Stratify P0/P1/P2, every
finding = location + concrete fix, no praise. Check against four sources:
1. **Factual fidelity** vs the source data — list every divergence; any field with
   no source gets an explicit caveat, never silently kept (verify-before-claim).
2. **DESIGN.md** — system-stack Inter / no Google Fonts; accent gradient only on
   1–2 accent words + wordmark; weight-300 large headings; 1px hairlines; readable
   token contrast in **both** light and dark.
3. **SOUL.md** — no hero-arc, no hype words, no marketing slogans; the user is
   the sender (recipients in 3rd person, never addressed directly).
4. **HTML correctness** — balanced tags; `grid-template-columns` count matches
   child count; theme toggle (localStorage + T) **and** lang toggle (localStorage +
   L) present and working; anchors resolve; `prefers-reduced-motion` disables motion.

**Phase 3 — Integrate (orchestrator).** Fix all P0+P1; write the `index.html`
launcher (card grid + "which page for which meeting"); render every page light+dark
and DE+EN; document in `work/tasks/<slug>/STATUS.md`; commit scope-split (the
template/script are CORE/promotable; the generated per-document HTML is USER-tier
under `work/`, kept out of any shared/upstream repo — see
[`rules/promote-safety.md`](../../../rules/promote-safety.md)).

## Data-driven kits — build script, not hand-HTML
When a dataset exists (JSON/YAML/board export), don't hand-write the HTML — fill a
`{{placeholder}}` copy of the shell with a deterministic single-pass build script
(`html.escape` every injected value, `ensure_ascii=False` so umlauts stay native
UTF-8). Output is then reproducible and consistent across regenerations. Model:
`skills/dashboard/assets/dashboard-template.html` + its render script.

---

## The quality bar (applies to every deliverable)

**Tokens & type**
- Pull every colour/type/spacing token from DESIGN.md (`design-to-css.py`). Never
  hand-pick a brand colour; if a token is missing, add it to DESIGN.md first.
- "large = light": headings ≥24px ride `font-weight:300` (card titles/buttons 500).
- Accent gradient only on 1–2 accent words + the wordmark, on a solid surface.
  **Never** `linear-gradient(135deg,cyan,purple)` on text — that's the AI-slop tell.
- **No Google Fonts / any third-party font CDN** — GDPR. System-stack Inter
  (`--font-sans`) or a data-URI-inlined self-hosted woff2.

**Behaviour**
- Light/dark toggle (button + T + localStorage + anti-FOUC pre-paint + OS default
  when unset) and DE/EN toggle (button + L + localStorage) ship on every page —
  they're the shell defaults; don't reinvent them.
- Single-file, offline, zero external dependencies — even QR/charts from bundled or
  inline code. Footer documents source path + regenerate command + key hints.
- `prefers-reduced-motion` cleanly kills all motion; print/PDF is first-class (hide
  chrome, force reveals visible, force light palette regardless of theme).

**Colour = meaning**
- Page chrome stays DESIGN.md neutrals + the one indigo accent. Semantic
  lens/actor colours are the only "colour carries meaning" exception and always
  ship a legend. Status reads by **shape** (`● ◐ ✗ –`), colour second.
- De-emphasis = full-contrast text + a tag, never opacity-dimming.

**Voice & content (SOUL.md)**
- No hero-arc/hype/marketing slogans; system description + stack + scale; conditional
  phrasing for the uncertain; limitations disclosed upfront.
- The user is the **sender**; address recipients in the 3rd person, never directly.
- Verify-before-claim: every generated fact traces to a source or sits under an
  explicit caveat. Never keep an absent-from-source field silently.
- **Language:** default to the conversation language; author DE **and** EN as
  first-class equals. Repo/OSS-shipped artifacts must be English regardless — the
  lang toggle must never assume German is the base.

**UTF-8** — native umlauts/€/—/… in all authored text; never HTML-entities or ASCII
substitutes for content. (The `&rarr;`/`&darr;` arrow *glyphs* are a deliberate icon
choice, not text content — those are fine.)

**Accessibility baseline**
- `:focus-visible` ring on every interactive element; toggles are real `<button>`s
  with `aria-label`. Keyboard handlers ignore keystrokes inside form fields.
- Inline SVG diagrams carry `role="img"` + `aria-label`; decorative arrow glyphs
  `aria-hidden`. Status glyphs carry `role="img"` + `aria-label`.
- Reading length capped (body ≤70ch, lead ≤68ch); `scroll-padding-top` clears any
  sticky nav. `.vh` utility for screen-reader-only text.

---

## Optional: portability into a design tool (not a requirement)
A clean, flat html-canvas page also imports reasonably into Figma via
`html.to.design` — useful, but **not** a goal that should shape the design. If a
specific deliverable is *meant* to become an editable Figma frame, keep that one
page flat: solid fills + 1px borders instead of shadows/gradients, real arrow/divider
elements instead of `::before`/`::after`, layout via flex/grid+gap instead of
`position:absolute`, and light as the default (the dark toggle is browser-only and
ignored on import). That's a per-deliverable choice you make when asked — the skill
itself optimizes for good HTML first; importability is a side benefit of clean,
flat markup, never the deciding constraint.
