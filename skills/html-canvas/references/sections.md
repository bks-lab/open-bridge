---
summary: "Copy-paste section building blocks for html-canvas deliverables — headers, flows, data, content, chrome"
type: reference
last_updated: 2026-06-01
related:
  - skills/html-canvas/SKILL.md
  - skills/html-canvas/assets/shell.html
---

# html-canvas — Section Catalog

Drop these into the shell's `<main>`. Every block uses the shell's tokens
(`--ink --muted --line --surface --accent …`) so it themes light/dark for free,
and every text run is authored as `data-de`/`data-en` siblings so it switches
language for free. CSS goes once into the shell's `<style>`; markup goes into
`<main>`.

**Three habits that make these blocks line up and stay honest:**
- **Equal cells line up** — fixed first column + identical `fr` cells
  (`grid-template-columns:170px repeat(N,1fr)`) is what makes sibling rows align.
- **Colour = meaning, never decoration** — page chrome stays neutral + the one
  indigo accent. The semantic lens/actor triads are the *only* coloured-surface
  exception and **always** ship a legend (last block).
- **Shape carries status, not colour alone** — `● ◐ ✗ –` glyphs so meaning
  survives colour-blindness and grayscale print.

## Contents
- Headers — [doc header](#doc-header) · [hero](#hero) · [section opener](#section-opener)
- Flows — [pipeline](#pipeline) · [swimlane](#swimlane) · [C4 boxes](#c4-boxes) · [ladder](#ladder) · [SVG diagram](#svg-diagram) · [message flow A→B](#message-flow)
- Data — [KPI row](#kpi-row) · [matrix](#matrix) · [kanban](#kanban) · [table](#table) · [bar chart](#bar-chart) · [timeline](#timeline)
- Content — [spec card](#spec-card) · [callout](#callout) · [NOT-vs-IS](#not-vs-is) · [chips](#chips) · [people](#people) · [terminal](#terminal) · [collapsible](#collapsible)
- Chrome — [section nav](#section-nav) · [legend](#legend) · [index/launcher](#index)

---

## <a id="doc-header"></a>Document header (eyebrow · title · lead)
Top of any page. Light-weight title, uppercase eyebrow, lead ≤80ch.
```html
<header>
  <div class="eyebrow"><span data-de>Strategie-Überblick</span><span data-en>Strategy overview</span></div>
  <h1><span data-de>Ein Produkt — zwei Linsen</span><span data-en>One product — two lenses</span></h1>
  <p class="lead"><span data-de>Worum es geht …</span><span data-en>What this is about …</span></p>
</header>
```
```css
.eyebrow{font-size:12px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
.lead{font-size:19px;font-weight:300;color:var(--on-surface);max-width:68ch;margin-top:8px}
```

## <a id="hero"></a>Hero (gradient accent word + badge)
Bigger top for landing-ish pages. The gradient touches **one** accent word only
(DESIGN.md: more than 1–2 words + the wordmark cheapens it; cyan→purple on text
is an AI-slop tell — keep it the brand indigo→purple).
```html
<header class="hero">
  <span class="badge">◐ <span data-de>Featured</span><span data-en>Featured</span></span>
  <h1 class="display"><span data-de>Digitale Transformation </span><span data-en>Digital transformation, </span><span class="grad" data-de>intelligent beschleunigt</span><span class="grad" data-en>accelerated</span></h1>
  <p class="lead"><span data-de>…</span><span data-en>…</span></p>
</header>
```
```css
.hero{padding:48px 0}
.display{font-size:clamp(40px,6vw,64px);font-weight:300;line-height:1.05;letter-spacing:-.02em;max-width:20ch}
.grad{background:linear-gradient(120deg,var(--accent-from),var(--accent-to));-webkit-background-clip:text;background-clip:text;color:transparent;font-weight:400}
.badge{display:inline-flex;align-items:center;gap:8px;background:var(--surface-muted);color:var(--on-surface);font-size:13px;padding:6px 14px;border-radius:var(--radius-full);margin-bottom:20px}
```

## <a id="section-opener"></a>Numbered section opener
Magazine rhythm for long docs. Alternating section bg chunks content without dividers.
```html
<section id="kernidee"><div class="wrap narrow">
  <div class="eyebrow"><span class="sec-no">§1</span> <span data-de>Die Kernidee</span><span data-en>The core idea</span></div>
  <h2><span data-de>Vom Prompt zum </span><span data-en>From prompt to </span><span class="grad">Asset</span></h2>
  <p class="lead" data-de>…</p><p class="lead" data-en>…</p>
</div></section>
```
```css
section{padding-block:72px;border-top:1px solid var(--line-subtle)}
section:nth-of-type(even){background:var(--surface-subtle)}
.sec-no{font-family:var(--font-mono);font-weight:700;color:var(--accent-text)}
```

---

## <a id="pipeline"></a>Pipeline / backbone row
Horizontal flow of equal stages joined by **real arrow elements** (so they stay
crisp, theme, and translate — and survive any later copy into a design tool).
```html
<div class="pipe">
  <div class="pbox"><div class="pbox-id">1</div><div class="pbox-t"><span data-de>Quellen</span><span data-en>Sources</span></div></div>
  <span class="arrow" aria-hidden="true">&rarr;</span>
  <div class="pbox"><div class="pbox-id">2</div><div class="pbox-t"><span data-de>Verarbeitung</span><span data-en>Processing</span></div></div>
  <span class="arrow" aria-hidden="true">&rarr;</span>
  <div class="pbox"><div class="pbox-id">3</div><div class="pbox-t"><span data-de>Ausgabe</span><span data-en>Output</span></div></div>
</div>
```
```css
.pipe{display:flex;align-items:stretch;gap:6px;flex-wrap:wrap}
.pbox{flex:1 1 0;min-width:120px;background:var(--surface);border:1px solid var(--line);border-radius:var(--radius-lg);padding:14px;display:flex;flex-direction:column;gap:5px}
.pbox-id{font-family:var(--font-mono);font-size:12px;color:var(--accent-text);font-weight:700}
.arrow{display:flex;align-items:center;color:var(--muted);font-size:20px;flex:none}
```

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
```css
.lane{display:grid;grid-template-columns:130px repeat(2,1fr);gap:10px;border:1px solid var(--line);border-radius:var(--radius-lg);padding:14px;margin-bottom:10px;background:var(--surface-subtle)}
.lane .lane-k{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;align-self:center}
.lane.human{background:var(--human-bg);border-color:var(--human-line)} .lane.human .lane-k{color:var(--human-ink)}
.lane.ai{background:var(--ai-bg);border-color:var(--ai-line)} .lane.ai .lane-k{color:var(--ai-ink)}
.lane.tech{background:var(--tech-bg);border-color:var(--tech-line)} .lane.tech .lane-k{color:var(--tech-ink)}
.lane.tech .cell{font-family:var(--font-mono);font-size:12px;color:var(--tech-ink)}
.cell{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius-md);padding:10px;font-size:13px}
@media(max-width:760px){.lane{grid-template-columns:1fr}}
```

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
```css
.ctx{display:flex;align-items:stretch;gap:14px;justify-content:center;flex-wrap:wrap}
.box{border:1px solid var(--line);border-radius:var(--radius-lg);padding:14px 16px;background:var(--surface);flex:1 1 0;min-width:140px}
.box.core{background:var(--core-bg);border-color:var(--core-line);color:var(--core-ink)}
.box.doc{background:var(--doc-bg);border-color:var(--doc-line);color:var(--doc-ink)}
.box.sch{background:var(--sch-bg);border-color:var(--sch-line);color:var(--sch-ink)}
```

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
```css
.band{display:grid;grid-template-columns:190px 1fr;gap:16px;align-items:center;border:1px solid var(--line);border-radius:var(--radius-lg);padding:16px 18px}
.band.ai{background:var(--ai-bg);border-color:var(--ai-line)} .band.ai .band-l{color:var(--ai-ink)}
.band.core{background:var(--core-bg);border-color:var(--core-line)}
.band-l{font-weight:600} .rung{text-align:center;color:var(--muted);font-size:20px;padding:4px 0}
@media(max-width:620px){.band{grid-template-columns:1fr}}
```

## <a id="svg-diagram"></a>Theme-adaptive inline SVG diagram
Precise hub/flow/ring shapes. `stroke="var(--line)"` / `fill="currentColor"` re-theme
automatically; `<tspan data-de/-en>` translate; wrap for mobile scroll.
```html
<div class="diagram"><svg viewBox="0 0 1000 320" role="img" aria-label="Datenfluss">
  <defs><marker id="arr" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="currentColor"/></marker></defs>
  <rect x="20" y="40" width="240" height="240" rx="12" fill="none" stroke="var(--line)"/>
  <text x="140" y="165" text-anchor="middle" fill="currentColor"><tspan data-de>Quelle</tspan><tspan data-en>Source</tspan></text>
  <line x1="260" y1="160" x2="420" y2="160" stroke="var(--accent)" marker-end="url(#arr)"/>
</svg></div>
```
```css
.diagram{overflow-x:auto;color:var(--ink)} .diagram svg{width:100%;height:auto;min-width:700px}
```

## <a id="message-flow"></a>Message flow A→B (animated)
Communication flowing between two parties: a packet travels A→B (request) and B→A
(response), looping — reads like a conversation. One inline SVG (scales, re-themes).
Needs `animations.css` for the `.msg-fwd`/`.msg-back` packet motion + `.flow-line` ambient
wire (all reduced-motion-gated). Set `--d` to the node distance in px.
```html
<div class="mflow"><svg viewBox="0 0 600 130" role="img" aria-label="Kommunikationsfluss A → B">
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
```css
.mflow svg{width:100%;max-width:600px;height:auto;color:var(--ink)}
.mnode{fill:var(--surface);stroke:var(--line)} .mlabel{fill:var(--ink);font-size:13px;font-weight:500}
```

---

## <a id="kpi-row"></a>KPI metric-card row
Dashboard stat block. Big number rides weight 300 (DESIGN.md stat-display).
Status colour applied inline per card. No icons/sparklines on the number (DESIGN.md).
```html
<div class="metrics">
  <div class="metric"><div class="m-label"><span data-de>Risk-Level</span><span data-en>Risk level</span></div>
    <div class="m-val" style="color:var(--warn)"><span data-de>Mittel</span><span data-en>Medium</span></div>
    <div class="m-sub"><span data-de>Datenmenge pending</span><span data-en>volume pending</span></div></div>
</div>
```
```css
.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px}
.metric{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius-lg);padding:16px 18px}
.m-label{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px}
.m-val{font-size:36px;font-weight:300;color:var(--ink);line-height:1;letter-spacing:-.02em}
.m-sub{font-size:12px;color:var(--muted);margin-top:6px}
```
For an animated count-up, add `data-count-to="83"` and wire the count-up helper (interactivity.md).

## <a id="matrix"></a>Comparison matrix (shape-encoded status)
Decision/capability grid. Cells carry meaning by **shape** + a note, never colour
alone. Disqualified rows = full-contrast text + pill, **never** opacity-dimming.
```html
<div class="tbl-wrap"><table>
  <thead><tr><th>Tool</th><th><span data-de>Lizenz</span><span data-en>License</span></th><th>Export</th></tr></thead>
  <tbody>
    <tr><td class="key">Excalidraw</td>
      <td><span class="glyph full" role="img" aria-label="yes">●</span> <span class="cnote">MIT</span></td>
      <td><span class="glyph part" role="img" aria-label="partial">◐</span> <span class="cnote">SVG/JSON</span></td></tr>
    <tr class="dq"><td class="key">Tool X <span class="dqtag"><span data-de>disqualifiziert</span><span data-en>disqualified</span></span></td>
      <td><span class="glyph none" role="img" aria-label="no">✗</span></td><td><span class="glyph na" role="img" aria-label="n/a">–</span></td></tr>
  </tbody>
</table></div>
```
```css
.glyph{font-size:17px} .glyph.full{color:var(--ok-text)} .glyph.part{color:var(--warn)} .glyph.none{color:var(--danger)} .glyph.na{color:var(--muted)}
.cnote{font-size:12px;color:var(--muted)}
.dqtag{display:inline-block;margin-left:6px;font-size:11px;color:var(--danger);border:1px solid var(--danger);border-radius:var(--radius-full);padding:1px 8px}
```

## <a id="kanban"></a>Status / pipeline kanban
auto-fit columns, status colour on the top border (inline), count pill, dashed-empty.
```html
<div class="kanban">
  <div class="col"><header style="border-top-color:var(--warn)"><h3><span data-de>Rückmeldung</span><span data-en>Replied</span></h3><span class="count">2</span></header>
    <div class="cards"><article class="kcard"><span class="badge age-y">5d</span> …</article></div></div>
</div>
```
```css
.kanban{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}
.col{background:var(--surface-subtle);border-radius:var(--radius-md);border-top:3px solid var(--accent);overflow:hidden}
.col>header{padding:10px 14px;background:var(--surface-muted);display:flex;justify-content:space-between;align-items:center}
.count{background:var(--surface);padding:2px 8px;border-radius:10px;font-size:11px;color:var(--muted)}
.cards{padding:8px;display:flex;flex-direction:column;gap:8px;min-height:60px}
.kcard{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius-md);padding:10px;font-size:13px}
.badge{font-size:11px;padding:1px 7px;border-radius:var(--radius-full);border:1px solid var(--line)}
.age-y{color:var(--warn);border-color:var(--warn)}
```

## <a id="table"></a>Data table
Header is static by default. Only add `th{position:sticky;top:0}` when the table sits inside a `max-height` + `overflow-y:auto` scroll box — on a normally scrolling page a sticky header floats over the rows.
```html
<div class="tbl-wrap"><table>
  <thead><tr><th>ID</th><th><span data-de>Beschreibung</span><span data-en>Description</span></th></tr></thead>
  <tbody><tr><td class="key">UC-5</td><td>…</td></tr></tbody>
</table></div>
```
```css
.tbl-wrap{overflow-x:auto;border:1px solid var(--line);border-radius:var(--radius-lg)}
table{width:100%;border-collapse:collapse;font-size:14px;min-width:560px}
th,td{text-align:left;padding:11px 14px;border-bottom:1px solid var(--line);vertical-align:top}
th{background:var(--surface-muted);color:var(--ink);font-weight:600}
tbody tr:nth-child(even){background:var(--surface-subtle)}
td.key{font-family:var(--font-mono);color:var(--accent-text)}
```

## <a id="bar-chart"></a>CSS-only horizontal bar chart
Before/after benchmark, no chart lib. Inline `width:N%` fills, delta coloured by sign.
```html
<div class="barchart">
  <div class="bar-l"><span data-de>Alt</span><span data-en>Old</span></div><div class="bar-track"><div class="bar-fill old" style="width:80%">12 min</div></div><div class="bar-d"></div>
  <div class="bar-l"><span data-de>Neu</span><span data-en>New</span></div><div class="bar-track"><div class="bar-fill new" style="width:18%">2 min</div></div><div class="bar-d">−83%</div>
</div>
```
```css
.barchart{display:grid;grid-template-columns:auto 1fr auto;gap:14px 20px;align-items:center;font-family:var(--font-mono)}
.bar-track{height:28px;background:var(--surface-subtle);border:1px solid var(--line);border-radius:14px;overflow:hidden}
.bar-fill{height:100%;border-radius:14px;display:flex;align-items:center;padding:0 14px;color:var(--on-primary);font-size:12px;font-weight:600}
.bar-fill.old{background:var(--muted)} .bar-fill.new{background:var(--accent)}
.bar-d{font-weight:700;color:var(--ok-text)}
```

## <a id="timeline"></a>Vertical timeline
Roadmap/changelog. Grid rows + bottom-border separators, `.now/.future` state.
```html
<div class="timeline">
  <div class="tl-row now"><div class="tl-date"><span data-de>Jetzt</span><span data-en>Now</span></div><div>…</div></div>
  <div class="tl-row future"><div class="tl-date">Q3</div><div>…</div></div>
</div>
```
```css
.tl-row{display:grid;grid-template-columns:120px 1fr;gap:24px;padding:12px 0;border-bottom:1px solid var(--line-subtle)}
.tl-row:last-child{border-bottom:none}
.tl-row.now .tl-date{color:var(--accent-text);font-weight:600}
.tl-row.future .tl-date{color:var(--muted);font-style:italic}
```

---

## <a id="spec-card"></a>Spec card (key-value fact sheet)
Fact-sheet, decision record, persona, use-case brief. Mark derived/unconfirmed
fields with an explicit caveat (verify-before-claim) — never keep them silently.
```html
<div class="speccard">
  <div class="k"><span data-de>Primärakteur</span><span data-en>Primary actor</span></div><div>…</div>
  <div class="k"><span data-de>Auslöser</span><span data-en>Trigger</span></div><div>…</div>
</div>
```
```css
.speccard{display:grid;grid-template-columns:150px 1fr;border:1px solid var(--line);border-radius:var(--radius-lg);overflow:hidden}
.speccard>div{padding:9px 13px;border-bottom:1px solid var(--line-subtle);font-size:13.5px}
.speccard .k{background:var(--surface-muted);font-weight:600;color:var(--ink)}
@media(max-width:620px){.speccard{grid-template-columns:1fr}}
```

## <a id="callout"></a>Callout / note (+ warn / caveat variant)
```html
<div class="note"><b>Note</b> …</div>
<div class="note warn"><b><span data-de>Vorbehalt</span><span data-en>Caveat</span></b> <span data-de>Aus der Quelle abgeleitet, nicht bestätigt.</span><span data-en>Derived from source, unconfirmed.</span></div>
```
```css
.note{border-left:3px solid var(--accent);background:var(--accent-soft);padding:14px 18px;border-radius:0 var(--radius-md) var(--radius-md) 0;margin:18px 0;font-size:14.5px}
.note.warn{border-left-color:var(--warn);background:rgba(180,83,9,.08)}
.note b{color:var(--ink)}
```

## <a id="not-vs-is"></a>NOT-vs-IS contrast cards
Anti-hype framing (SOUL.md: no hero arc). "Nicht … sondern …".
```html
<div class="contrast">
  <div class="cc no"><span class="tag"><span data-de>Nicht</span><span data-en>Not</span></span><p>…</p></div>
  <div class="cc yes"><span class="tag"><span data-de>Sondern</span><span data-en>But</span></span><p>…</p></div>
</div>
```
```css
.contrast{display:grid;grid-template-columns:1fr 1fr;gap:24px}
@media(max-width:760px){.contrast{grid-template-columns:1fr}}
.cc{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius-lg);padding:24px}
.cc.no{border-left:3px solid var(--muted)} .cc.yes{border-left:3px solid var(--accent)}
.cc .tag{font-family:var(--font-mono);font-size:11px;letter-spacing:1.5px;text-transform:uppercase;font-weight:600}
.cc.no .tag{color:var(--muted)} .cc.yes .tag{color:var(--accent-text)}
```

## <a id="chips"></a>Chips / entity tags
```html
<div class="chips"><span class="chip">Concept</span><span class="chip new">Skill</span><span class="chip edge">references</span></div>
```
```css
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}
.chip{font-size:13px;font-family:var(--font-mono);padding:6px 12px;border-radius:var(--radius-md);border:1px solid var(--line);background:var(--surface);color:var(--on-surface)}
.chip.new{border-color:var(--accent);background:var(--accent-soft);color:var(--accent-text)}
.chip.edge{background:var(--surface-muted)}
```

## <a id="people"></a>People / avatar grid (initials, no images)
Remember SOUL.md: the user is the **sender**; recipients in 3rd person ("Recipient").
```html
<div class="people">
  <div class="person"><div class="avatar">JD</div><div><div class="p-name">J. Doe</div><div class="p-role"><span data-de>Empfänger</span><span data-en>Recipient</span></div></div></div>
</div>
```
```css
.people{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}
.person{display:flex;align-items:center;gap:12px;padding:12px;background:var(--surface);border:1px solid var(--line);border-radius:var(--radius-lg)}
.avatar{width:40px;height:40px;border-radius:50%;background:var(--accent);color:var(--on-primary);display:flex;align-items:center;justify-content:center;font-weight:700;font-size:14px}
.p-name{font-weight:600;color:var(--ink)} .p-role{font-size:12px;color:var(--muted)}
```

## <a id="terminal"></a>Terminal / code-window mock
Hand-classed syntax spans mapped to status vars.
```html
<div class="term"><div class="term-bar"><span class="td r"></span><span class="td y"></span><span class="td g"></span><span class="term-label">deploy.sh</span></div>
<pre class="term-body"><span class="pr">$</span> deploy uat
<span class="ok">✓ running</span></pre></div>
```
```css
.term{background:var(--code-bg);border:1px solid var(--line);border-radius:var(--radius-lg);overflow:hidden;font-family:var(--font-mono);font-size:clamp(11px,1.3vw,15px)}
.term-bar{display:flex;align-items:center;gap:6px;padding:10px 14px;border-bottom:1px solid var(--line);background:var(--surface-muted)}
/* macOS traffic-light window controls — literal chrome colours, not brand tokens (intentional) */
.td{width:10px;height:10px;border-radius:50%}.td.r{background:#ef4444}.td.y{background:#f59e0b}.td.g{background:#10b981}
.term-label{color:var(--muted);font-size:12px;margin-left:4px}
.term-body{margin:0;padding:14px 16px;color:var(--on-surface);white-space:pre-wrap}
.term-body .pr{color:var(--accent-text)} .term-body .ok{color:var(--ok-text)}
```

## <a id="collapsible"></a>Collapsible (details/summary, zero-JS)
```html
<details class="recipe"><summary><span data-de>Mehr Details</span><span data-en>More detail</span></summary><div class="recipe-body">…</div></details>
```
```css
.recipe{margin-top:16px;border:1px dashed var(--line);border-radius:var(--radius-lg);background:var(--surface-subtle)}
.recipe summary{cursor:pointer;padding:12px 16px;font-weight:500;color:var(--accent-text)}
.recipe[open] summary{border-bottom:1px solid var(--line)}
.recipe-body{padding:14px 16px}
```

---

## <a id="legend"></a>Legend (mandatory when colour carries meaning)
Needs the optional lens/actor triads (uncomment in the shell).
```html
<div class="legend"><span class="lg-label"><span data-de>Legende</span><span data-en>Legend</span></span>
  <span class="chip core"><span class="dot"></span><span data-de>grau — Kern</span><span data-en>grey — core</span></span>
  <span class="chip doc"><span class="dot"></span><span data-de>teal — Linse B</span><span data-en>teal — lens B</span></span>
</div>
```
```css
.legend{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-top:22px}
.lg-label{font-size:12px;color:var(--muted)}
.legend .chip{display:flex;align-items:center;gap:7px;font-size:12px;font-weight:600}
.legend .dot{width:10px;height:10px;border-radius:50%}
.legend .core .dot{background:var(--core-line)} .legend .doc{background:var(--doc-bg);border-color:var(--doc-line);color:var(--doc-ink)} .legend .doc .dot{background:var(--doc-line)}
```

## <a id="index"></a>Index / launcher page
Table-of-contents for a multi-page kit: card grid + "which page for which meeting".
```html
<div class="cards-grid">
  <a class="lcard" href="page-1.html"><span class="lc-t">Page 1</span><span class="lc-m"><span data-de>Strategie-Meeting</span><span data-en>Strategy meeting</span></span></a>
</div>
```
```css
.cards-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
@media(max-width:860px){.cards-grid{grid-template-columns:repeat(2,1fr)}}@media(max-width:560px){.cards-grid{grid-template-columns:1fr}}
.lcard{border:1px solid var(--line);border-radius:var(--radius-lg);padding:16px;background:var(--surface);display:flex;flex-direction:column;gap:3px}
.lc-t{font-size:11px;font-weight:700;letter-spacing:.03em;color:var(--accent-text)}
.lc-m{color:var(--ink)}
```

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
```css
.secnav{position:sticky;top:0;z-index:50;display:flex;gap:18px;flex-wrap:wrap;padding:12px 24px;background:var(--surface);border-bottom:1px solid var(--line)}
.secnav a{color:var(--muted);font-size:14px;text-decoration:none}
.secnav a:hover,.secnav a.active{color:var(--accent-text)}
@media(max-width:620px){.secnav{gap:12px;font-size:13px;overflow-x:auto}}
```
