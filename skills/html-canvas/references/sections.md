---
summary: "Copy-paste section building blocks for html-canvas deliverables: headers, flows, data, content, chrome"
type: reference
last_updated: 2026-10-24
related:
  - skills/html-canvas/SKILL.md
  - skills/html-canvas/assets/shell.html
  - skills/html-canvas/assets/sections.css
  - skills/html-canvas/scripts/new-page.py
---

# html-canvas: Section Catalog

Drop these into the shell's `<main>`. Every block uses the shell's tokens
(`--ink --muted --line --surface --accent …`) so it themes light/dark for free,
and every text run is authored as `data-de`/`data-en` siblings so it switches
language for free. Markup goes into `<main>`. The CSS of every block lives in ONE
file, `assets/sections.css`, one `/* @block: name */` section per block (a block
names what it needs with `requires:`). Do not paste it by hand:
`scripts/new-page.py --blocks <names>` builds the page, copies each block's CSS
exactly once, and `--refresh <page>` brings an existing page back in line later.

Blocks that MOVE (stage, route, protocol feed, message thread, provenance cards)
are not here: they belong to the running-model layer and live in
`assets/simulation.css` with their playbook in `references/simulation.md`.

**Three habits that make these blocks line up and stay honest:**
- **Equal cells line up**: fixed first column + identical `fr` cells
  (`grid-template-columns:170px repeat(N,1fr)`) is what makes sibling rows align.
- **Colour = meaning, never decoration**: page chrome stays neutral + the
  instance's brand blue from DESIGN.md. The semantic lens/actor triads are the *only* coloured-surface
  exception and **always** ship a legend (last block).
- **Shape carries status, not colour alone**: `● ◐ ✗ ○` glyphs so meaning
  survives colour-blindness and grayscale print.

## Contents
- Headers: [doc header](#doc-header) · [hero](#hero) · [section opener](#section-opener)
- Flows: [pipeline](#pipeline) · [swimlane](#swimlane) · [C4 boxes](#c4-boxes) · [ladder](#ladder) · [SVG diagram](#svg-diagram) · [message flow A→B](#message-flow)
- Data: [KPI row](#kpi-row) · [matrix](#matrix) · [kanban](#kanban) · [table](#table) · [bar chart](#bar-chart) · [timeline](#timeline)
- Decisions: [decision page](#decision-page)
- Content: [spec card](#spec-card) · [callout](#callout) · [NOT-vs-IS](#not-vs-is) · [chips](#chips) · [people](#people) · [terminal](#terminal) · [collapsible](#collapsible)
- Chrome: [section nav](#section-nav) · [legend](#legend) · [index/launcher](#index)

---

## <a id="doc-header"></a>Document header (eyebrow · title · lead)
Top of any page. Eyebrow in the working colour, display-face title, lead ≤80ch.
```html
<header>
  <div class="eyebrow"><span data-de>Strategie-Überblick</span><span data-en>Strategy overview</span></div>
  <h1><span data-de>Ein Produkt, zwei Linsen</span><span data-en>One product, two lenses</span></h1>
  <p class="lead"><span data-de>Worum es geht …</span><span data-en>What this is about …</span></p>
</header>
```
*CSS: block `doc-header` in `assets/sections.css`, included by `new-page.py --blocks doc-header`.*

## <a id="hero"></a>Hero (eyebrow + display title + badge)
Bigger top for landing-ish pages. Left-aligned, editorial. No gradient on any
word: the brand is flat, and the display face alone carries the weight
(DESIGN.md, Do's and Don'ts).
```html
<header class="hero">
  <span class="badge">◐ <span data-de>Featured</span><span data-en>Featured</span></span>
  <div class="eyebrow"><span data-de>Überblick</span><span data-en>Overview</span></div>
  <h1 class="display"><span data-de>Digitale Transformation, intelligent beschleunigt</span><span data-en>Digital transformation, accelerated</span></h1>
  <p class="lead"><span data-de>…</span><span data-en>…</span></p>
</header>
```
*CSS: block `hero` in `assets/sections.css`, included by `new-page.py --blocks hero`.*

## <a id="section-opener"></a>Numbered section opener
Magazine rhythm for long docs. Sections separate by a hairline and space, never by
alternating background colours (DESIGN.md, Layout).
```html
<section id="core-idea"><div class="sec-body">
  <div class="eyebrow"><span class="sec-no">§1</span> <span data-de>Die Kernidee</span><span data-en>The core idea</span></div>
  <h2><span data-de>Vom Prompt zum </span><span data-en>From prompt to </span>Asset</h2>
  <p class="lead" data-de>…</p><p class="lead" data-en>…</p>
</div></section>
```
*CSS: block `section-opener` in `assets/sections.css`, included by `new-page.py --blocks section-opener`.*

---

## <a id="pipeline"></a>Pipeline / backbone row
Horizontal flow of equal stages joined by **real arrow elements** (so they stay
crisp, theme, and translate, and survive any later copy into a design tool).
```html
<div class="pipe">
  <div class="pbox"><div class="pbox-id">1</div><div class="pbox-t"><span data-de>Quellen</span><span data-en>Sources</span></div></div>
  <span class="arrow" aria-hidden="true">&rarr;</span>
  <div class="pbox"><div class="pbox-id">2</div><div class="pbox-t"><span data-de>Verarbeitung</span><span data-en>Processing</span></div></div>
  <span class="arrow" aria-hidden="true">&rarr;</span>
  <div class="pbox"><div class="pbox-id">3</div><div class="pbox-t"><span data-de>Ausgabe</span><span data-en>Output</span></div></div>
</div>
```
*CSS: block `pipeline` in `assets/sections.css`, included by `new-page.py --blocks pipeline`.*

## <a id="swimlane"></a>Three-track swimlane (Human / AI / Tech)
As-Is/To-Be process. The *gap* between the Human and AI lanes is the automation
message. Needs the optional **actor triads** (uncomment in the shell). Tech lane = mono.
```html
<div class="lanes">
  <div class="lane human"><div class="lane-k"><span data-de>Mensch</span><span data-en>Human</span></div>
    <div class="cell"><span data-de>Anfrage prüfen</span><span data-en>Review request</span></div><div class="cell">…</div></div>
  <div class="lane ai"><div class="lane-k">AI</div><div class="cell">…</div><div class="cell">…</div></div>
  <div class="lane tech"><div class="lane-k">Tech</div><div class="cell">api.call()</div><div class="cell">db.write()</div></div>
</div>
```
*CSS: block `swimlane` in `assets/sections.css`, included by `new-page.py --blocks swimlane`.*

## <a id="c4-boxes"></a>C4 / architecture boxes
Flat cards joined by real arrows; lens classes recolor (needs lens triads).
```html
<div class="ctx">
  <div class="box doc"><b><span data-de>Nutzer</span><span data-en>User</span></b></div>
  <span class="arrow" aria-hidden="true">&rarr;</span>
  <div class="box core"><b>System</b></div>
  <span class="arrow" aria-hidden="true">&rarr;</span>
  <div class="box sch"><b>SAP</b></div>
</div>
```
*CSS: block `c4-boxes` in `assets/sections.css`, included by `new-page.py --blocks c4-boxes`.*

## <a id="ladder"></a>Abstraction ladder (banded levels)
Vertical maturity/zoom: vision → capability → use-case → tech, rungs joined by ↓.
Needs the optional lens/actor triads (uncomment in the shell).
```html
<div class="ladder">
  <div class="band ai"><div class="band-l"><span data-de>Ebene 1 · Vision</span><span data-en>Level 1 · Vision</span></div><div>…</div></div>
  <div class="rung" aria-hidden="true">&darr;</div>
  <div class="band core"><div class="band-l"><span data-de>Ebene 2 · Capability</span><span data-en>Level 2 · Capability</span></div><div>…</div></div>
</div>
```
*CSS: block `ladder` in `assets/sections.css`, included by `new-page.py --blocks ladder`.*

## <a id="svg-diagram"></a>Theme-adaptive inline SVG diagram
Precise hub/flow/ring shapes. `stroke="var(--line)"` / `fill="currentColor"` re-theme
automatically; `<tspan data-de/-en>` translate; wrap for mobile scroll.
```html
<div class="diagram"><svg viewBox="0 0 1000 320" role="img" aria-label="Datenfluss" data-aria-de="Datenfluss" data-aria-en="Data flow">
  <defs><marker id="arr" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="currentColor"/></marker></defs>
  <rect x="20" y="40" width="240" height="240" rx="12" fill="none" stroke="var(--line)"/>
  <text x="140" y="165" text-anchor="middle" fill="currentColor"><tspan data-de>Quelle</tspan><tspan data-en>Source</tspan></text>
  <line x1="260" y1="160" x2="420" y2="160" stroke="var(--accent)" marker-end="url(#arr)"/>
</svg></div>
```
*CSS: block `svg-diagram` in `assets/sections.css`, included by `new-page.py --blocks svg-diagram`.*

## <a id="message-flow"></a>Message flow A→B (animated)
Communication flowing between two parties: a packet travels A→B (request) and B→A
(response), looping, so it reads like a conversation. One inline SVG (scales, re-themes).
Needs `animations.css` for the `.msg-fwd`/`.msg-back` packet motion + `.flow-line` ambient
wire (all reduced-motion-gated). Set `--d` to the node distance in px.
```html
<div class="mflow"><svg viewBox="0 0 600 130" role="img" aria-label="Kommunikationsfluss A → B" data-aria-de="Kommunikationsfluss A → B" data-aria-en="Message flow A → B">
  <defs>
    <marker id="aR" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="var(--accent)"/></marker>
    <marker id="aG" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="var(--ok-text)"/></marker>
  </defs>
  <rect class="mnode" x="12" y="40" width="150" height="50" rx="10"/><text class="mlabel" x="87" y="70" text-anchor="middle"><tspan data-de>A · Client</tspan><tspan data-en>A · Client</tspan></text>
  <rect class="mnode" x="438" y="40" width="150" height="50" rx="10"/><text class="mlabel" x="513" y="70" text-anchor="middle"><tspan data-de>B · Dienst</tspan><tspan data-en>B · Service</tspan></text>
  <line class="flow-line" x1="162" y1="56" x2="430" y2="56" stroke="var(--accent)" stroke-width="2" marker-end="url(#aR)"/>
  <line class="flow-line" x1="438" y1="74" x2="170" y2="74" stroke="var(--ok-text)" stroke-width="2" marker-end="url(#aG)"/>
  <circle class="msg-fwd" cx="162" cy="56" r="6" fill="var(--accent)" style="--d:268px"/>
  <circle class="msg-back" cx="438" cy="74" r="6" fill="var(--ok-text)" style="--d:268px"/>
</svg></div>
```
*CSS: block `message-flow` in `assets/sections.css`, included by `new-page.py --blocks message-flow`.*

---

## <a id="kpi-row"></a>KPI metric-card row
Dashboard stat block. Big number in the display face (DESIGN.md stat-display),
label in caps below it. Status is a dot plus a word, never a coloured number:
`warning` misses 4.5:1 as text. No icons/sparklines on the number (DESIGN.md).
```html
<div class="metrics">
  <div class="metric"><div class="m-label"><span data-de>Risk-Level</span><span data-en>Risk level</span></div>
    <div class="m-val"><span data-de>Mittel</span><span data-en>Medium</span></div>
    <div class="m-sub"><span class="dot" style="background:var(--warn)"></span> <span data-de>Achtung</span><span data-en>Watch</span></div>
    <div class="m-sub"><span data-de>Datenmenge pending</span><span data-en>volume pending</span></div></div>
</div>
```
*CSS: block `kpi-row` in `assets/sections.css`, included by `new-page.py --blocks kpi-row`.*
For an animated count-up, add `data-count-to="83"` and wire the count-up helper (interactivity.md).

## <a id="matrix"></a>Comparison matrix (shape-encoded status)
Decision/capability grid. Cells carry meaning by **shape** + a note, never colour
alone. Disqualified rows = full-contrast text + pill, **never** opacity-dimming.
```html
<div class="tbl-wrap"><table>
  <thead><tr><th>Tool</th><th><span data-de>Lizenz</span><span data-en>License</span></th><th>Export</th></tr></thead>
  <tbody>
    <tr><td class="key">Excalidraw</td>
      <td><span class="glyph full" role="img" aria-label="yes" data-aria-de="ja" data-aria-en="yes">●</span> <span class="cnote">MIT</span></td>
      <td><span class="glyph part" role="img" aria-label="partial" data-aria-de="teilweise" data-aria-en="partial">◐</span> <span class="cnote">SVG/JSON</span></td></tr>
    <tr class="dq"><td class="key">Tool X <span class="dqtag"><span data-de>disqualifiziert</span><span data-en>disqualified</span></span></td>
      <td><span class="glyph none" role="img" aria-label="no" data-aria-de="nein" data-aria-en="no">✗</span></td><td><span class="glyph na" role="img" aria-label="n/a" data-aria-de="nicht zutreffend" data-aria-en="n/a">○</span></td></tr>
  </tbody>
</table></div>
```
*CSS: block `matrix` in `assets/sections.css`, included by `new-page.py --blocks matrix`.*

## <a id="kanban"></a>Status / pipeline kanban
auto-fit columns, status colour on the top border (inline), count pill, dashed-empty.
```html
<div class="kanban">
  <div class="col"><header><h3><span data-de>Rückmeldung</span><span data-en>Replied</span></h3><span class="count">2</span></header>
    <div class="cards"><article class="kcard"><span class="badge age-y">5d</span> …</article></div></div>
</div>
```
*CSS: block `kanban` in `assets/sections.css`, included by `new-page.py --blocks kanban`.*

## <a id="table"></a>Data table
Header is static by default. Only add `th{position:sticky;top:0}` when the table sits inside a `max-height` + `overflow-y:auto` scroll box. On a normally scrolling page a sticky header floats over the rows.
```html
<div class="tbl-wrap"><table>
  <thead><tr><th>ID</th><th><span data-de>Beschreibung</span><span data-en>Description</span></th></tr></thead>
  <tbody><tr><td class="key">UC-5</td><td>…</td></tr></tbody>
</table></div>
```
*CSS: block `table` in `assets/sections.css`, included by `new-page.py --blocks table`.*

## <a id="bar-chart"></a>CSS-only horizontal bar chart
Before/after benchmark, no chart lib. Inline `width:N%` fills, delta coloured by sign.
```html
<div class="barchart">
  <div class="bar-l"><span data-de>Alt</span><span data-en>Old</span></div><div class="bar-track"><div class="bar-fill old" style="width:80%">12 min</div></div><div class="bar-d"></div>
  <div class="bar-l"><span data-de>Neu</span><span data-en>New</span></div><div class="bar-track"><div class="bar-fill new" style="width:18%">2 min</div></div><div class="bar-d">−83%</div>
</div>
```
*CSS: block `bar-chart` in `assets/sections.css`, included by `new-page.py --blocks bar-chart`.*

## <a id="timeline"></a>Vertical timeline
Roadmap/changelog. Grid rows + bottom-border separators, `.now/.future` state.
```html
<div class="timeline">
  <div class="tl-row now"><div class="tl-date"><span data-de>Jetzt</span><span data-en>Now</span></div><div>…</div></div>
  <div class="tl-row future"><div class="tl-date">Q3</div><div>…</div></div>
</div>
```
*CSS: block `timeline` in `assets/sections.css`, included by `new-page.py --blocks timeline`.*

---

## <a id="spec-card"></a>Spec card (key-value fact sheet)
Fact-sheet, decision record, persona, use-case brief. Mark derived/unconfirmed
fields with an explicit caveat (verify-before-claim), never keep them silently.
```html
<div class="speccard">
  <div class="k"><span data-de>Primärakteur</span><span data-en>Primary actor</span></div><div>…</div>
  <div class="k"><span data-de>Auslöser</span><span data-en>Trigger</span></div><div>…</div>
</div>
```
*CSS: block `spec-card` in `assets/sections.css`, included by `new-page.py --blocks spec-card`.*

## <a id="callout"></a>Callout / note (+ warn / caveat variant)
```html
<div class="note"><b><span data-de>Hinweis</span><span data-en>Note</span></b> <span data-de>…</span><span data-en>…</span></div>
<div class="note warn"><b><span data-de>Vorbehalt</span><span data-en>Caveat</span></b> <span data-de>Aus der Quelle abgeleitet, nicht bestätigt.</span><span data-en>Derived from source, unconfirmed.</span></div>
```
*CSS: block `callout` in `assets/sections.css`, included by `new-page.py --blocks callout`.*

## <a id="not-vs-is"></a>NOT-vs-IS contrast cards
Anti-hype framing (SOUL.md: no hero arc). "Nicht … sondern …".
```html
<div class="contrast">
  <div class="cc no"><span class="tag"><span data-de>Nicht</span><span data-en>Not</span></span><p>…</p></div>
  <div class="cc yes"><span class="tag"><span data-de>Sondern</span><span data-en>But</span></span><p>…</p></div>
</div>
```
*CSS: block `not-vs-is` in `assets/sections.css`, included by `new-page.py --blocks not-vs-is`.*

## <a id="chips"></a>Chips / entity tags
```html
<div class="chips"><span class="chip">Concept</span><span class="chip new">Skill</span><span class="chip edge">references</span></div>
```
*CSS: block `chips` in `assets/sections.css`, included by `new-page.py --blocks chips`.*

## <a id="people"></a>People / avatar grid (initials, no images)
Remember SOUL.md: the user is the **sender**; recipients in 3rd person ("Recipient").
```html
<div class="people">
  <div class="person"><div class="avatar">JD</div><div><div class="p-name">J. Doe</div><div class="p-role"><span data-de>Empfänger</span><span data-en>Recipient</span></div></div></div>
</div>
```
*CSS: block `people` in `assets/sections.css`, included by `new-page.py --blocks people`.*

## <a id="terminal"></a>Terminal / code-window mock
Hand-classed syntax spans mapped to status vars.
```html
<div class="term"><div class="term-bar"><span class="td r"></span><span class="td y"></span><span class="td g"></span><span class="term-label">deploy.sh</span></div>
<pre class="term-body"><span class="pr">$</span> deploy uat
<span class="ok">✓ running</span></pre></div>
```
*CSS: block `terminal` in `assets/sections.css`, included by `new-page.py --blocks terminal`.*

## <a id="collapsible"></a>Collapsible (details/summary, zero-JS)
```html
<details class="recipe"><summary><span data-de>Mehr Details</span><span data-en>More detail</span></summary><div class="recipe-body">…</div></details>
```
*CSS: block `collapsible` in `assets/sections.css`, included by `new-page.py --blocks collapsible`.*

---

## <a id="decision-page"></a>Decision page (options, criteria, recommendation, open points)
One page that lets a reader decide: the question as the lead, the options as cards,
the criteria as a shape-encoded table (the matrix glyphs, never colour alone), the
recommendation as a callout, and what is still open as a numbered list with owners.
The recommended option carries a heavier line and the word "Recommended". State a
recommendation only when the criteria support it; with none, drop the pick and the
callout and say so. Needs `matrix` and `callout` (new-page.py pulls them in).
```html
<div class="decision">
  <p class="lead"><span data-de>Wie betreiben wir den Berichtsdienst?</span><span data-en>How do we run the reporting service?</span></p>
  <h3 class="dec-h"><span data-de>Optionen</span><span data-en>Options</span></h3>
  <div class="dec-options">
    <article class="dec-opt recommended">
      <span class="dec-tag"><span data-de>Option A</span><span data-en>Option A</span></span>
      <span class="dec-pick"><span aria-hidden="true">●</span> <span data-de>Empfehlung</span><span data-en>Recommended</span></span>
      <h4><span data-de>Verwalteter Dienst</span><span data-en>Managed service</span></h4>
      <p><span data-de>Betrieb beim Anbieter, feste monatliche Kosten.</span><span data-en>Run by the provider, fixed monthly cost.</span></p>
    </article>
    <article class="dec-opt">
      <span class="dec-tag"><span data-de>Option B</span><span data-en>Option B</span></span>
      <h4><span data-de>Eigenbetrieb</span><span data-en>Self-hosted</span></h4>
      <p><span data-de>Volle Kontrolle, aber eigener Bereitschaftsdienst.</span><span data-en>Full control, but our own on-call duty.</span></p>
    </article>
    <article class="dec-opt">
      <span class="dec-tag"><span data-de>Option C</span><span data-en>Option C</span></span>
      <h4><span data-de>Nichts ändern</span><span data-en>Keep as is</span></h4>
      <p><span data-de>Kein Aufwand jetzt, das Problem bleibt.</span><span data-en>No effort now, the problem stays.</span></p>
    </article>
  </div>
  <h3 class="dec-h"><span data-de>Kriterien</span><span data-en>Criteria</span></h3>
  <div class="tbl-wrap dec-criteria"><table>
    <thead><tr><th><span data-de>Kriterium</span><span data-en>Criterion</span></th><th>A</th><th>B</th><th>C</th></tr></thead>
    <tbody>
      <tr><td><span data-de>Betriebsaufwand</span><span data-en>Operating effort</span></td>
        <td><span class="glyph full" role="img" data-aria-de="gut" data-aria-en="good">●</span> <span class="cnote"><span data-de>gering</span><span data-en>low</span></span></td>
        <td><span class="glyph none" role="img" data-aria-de="schlecht" data-aria-en="poor">✗</span> <span class="cnote"><span data-de>hoch</span><span data-en>high</span></span></td>
        <td><span class="glyph part" role="img" data-aria-de="teilweise" data-aria-en="partial">◐</span> <span class="cnote"><span data-de>unverändert</span><span data-en>unchanged</span></span></td></tr>
      <tr><td><span data-de>Kosten pro Jahr</span><span data-en>Cost per year</span></td>
        <td><span class="glyph part" role="img" data-aria-de="teilweise" data-aria-en="partial">◐</span> <span class="cnote">12 k</span></td>
        <td><span class="glyph full" role="img" data-aria-de="gut" data-aria-en="good">●</span> <span class="cnote">8 k</span></td>
        <td><span class="glyph full" role="img" data-aria-de="gut" data-aria-en="good">●</span> <span class="cnote">0</span></td></tr>
      <tr><td><span data-de>Ausfallsicherheit</span><span data-en>Availability</span></td>
        <td><span class="glyph full" role="img" data-aria-de="gut" data-aria-en="good">●</span> <span class="cnote">99,9 %</span></td>
        <td><span class="glyph part" role="img" data-aria-de="teilweise" data-aria-en="partial">◐</span> <span class="cnote">99,0 %</span></td>
        <td><span class="glyph none" role="img" data-aria-de="schlecht" data-aria-en="poor">✗</span> <span class="cnote">98 %</span></td></tr>
    </tbody>
  </table></div>
  <div class="note dec-reco">
    <b><span data-de>Empfehlung</span><span data-en>Recommendation</span></b>
    <span data-de>Option A: geringster Aufwand bei der besten Verfügbarkeit, Mehrkosten von 4 k pro Jahr gegenüber B.</span><span data-en>Option A: least effort at the best availability, 4 k per year more than B.</span>
  </div>
  <h3 class="dec-h"><span data-de>Offene Punkte</span><span data-en>Open points</span></h3>
  <ol class="dec-open">
    <li><span data-de>Vertragslaufzeit des Anbieters klären</span><span data-en>Clarify the provider's contract term</span> <span class="cnote"><span data-de>Eigentümer: Einkauf, bis KW 12</span><span data-en>Owner: procurement, by week 12</span></span></li>
    <li><span data-de>Datenstandort bestätigen lassen</span><span data-en>Get the data location confirmed</span> <span class="cnote"><span data-de>Eigentümer: Datenschutz</span><span data-en>Owner: data protection</span></span></li>
  </ol>
</div>
```
*CSS: block `decision-page` in `assets/sections.css`, included by `new-page.py --blocks decision-page`.*

---

## <a id="legend"></a>Legend (mandatory when colour carries meaning)
Needs the optional lens/actor triads (uncomment in the shell).
```html
<div class="legend"><span class="lg-label"><span data-de>Legende</span><span data-en>Legend</span></span>
  <span class="chip core"><span class="dot"></span><span data-de>grau: Kern</span><span data-en>grey: core</span></span>
  <span class="chip doc"><span class="dot"></span><span data-de>teal: Linse B</span><span data-en>teal: lens B</span></span>
</div>
```
*CSS: block `legend` in `assets/sections.css`, included by `new-page.py --blocks legend`.*

## <a id="index"></a>Index / launcher page
Table-of-contents for a multi-page kit: card grid + "which page for which meeting".
```html
<div class="cards-grid">
  <a class="lcard" href="page-1.html"><span class="lc-t">Page 1</span><span class="lc-m"><span data-de>Strategie-Meeting</span><span data-en>Strategy meeting</span></span></a>
</div>
```
*CSS: block `index` in `assets/sections.css`, included by `new-page.py --blocks index`.*

## <a id="section-nav"></a>Sticky section nav / ToC
For a multi-section document: a sticky bar of in-page anchor links to your `section[id]`s.
The shell already sets `scroll-padding-top:80px` + smooth scroll so anchored headings clear it.
Add the scrollspy from `interactivity.md` to highlight the active section.
```html
<nav class="secnav">
  <a href="#kernidee"><span data-de>Kernidee</span><span data-en>Core idea</span></a>
  <a href="#ablauf"><span data-de>Ablauf</span><span data-en>Flow</span></a>
  <a href="#architektur"><span data-de>Architektur</span><span data-en>Architecture</span></a>
</nav>
```
*CSS: block `section-nav` in `assets/sections.css`, included by `new-page.py --blocks section-nav`.*
