// SPDX-License-Identifier: MIT
// Jev page of the briefing dashboard (test tab): what the dashboard holds right now goes to
// TypeSafe's Jev through the server (POST /api/jev/run, the key never reaches the page), and the
// answers come back as a priority picture. Kept in its own folder so it does not collide with the
// dashboard's code; the hooks outside are one tab, one route and one controller method.
//
// The picture is a scene in the manner of the explainer films (skills/explainer-video): every frame
// is a pure function of the time since its play started. The first answer plays in full: the core
// that read the tasks releases each one with a spring onto its place in an urgency/impact matrix,
// the plan runs in row by row, the first task gets its rings. A later answer does not start over:
// every task glides from where it stands to its new place, bars and rows follow. One clock drives
// the whole page and sleeps when nothing moves. Preact renders the structure at its resting state;
// the frame function only sets transform, opacity and the SVG attributes it alone owns.
//
// Jumps go through the dashboard's controller like everywhere else: a title opens the task's
// detail beside the page (c.peek), the button beside it goes to the agent's tab (tab_jump) or asks
// for advice (advise), a dot in the matrix opens the same detail.

import { html, useEffect, useLayoutEffect, useRef, useState } from '../vendor/htm-preact-3.1.1.module.js'
import { clamp, countTo, cursorOn, flash, flowAlpha, noise1, nowSec, o3, ramp, reducedMotion, ripples, spring, track, trackAt, tracking, typed, win } from './motion.js'
import { CORE, H, W, X0, X1, Y0, Y1, costLine, launch, liveItems, orderPlan, pendingTitles, place, rowJump, tokenText } from './logic.js'
import { indexRows } from '../logic.js'
import { T as dashText, language } from '../text.js'

export { pendingTitles, place }
export const JEV_PAGE = '@jev'

const DUR = 6.4         // the first play, seconds
const GLIDE = 2.2       // a later answer: every task on its way to the new place
const FOCUS_T = 2.9     // the first task gets its rings
const EMPH = { w: 16, zeta: 1 }

const TEXT = {
  de: {
    tab: 'Jev', title: 'Jev bewertet deinen Tag', reading: n => `Jev liest ${n} Aufgaben`, rereading: 'Jev liest neu',
    sub: 'Was gerade im Dashboard steht, geht an die Jev-API: Dringlichkeit, Wirkung, Aufwand und „nur du“ je Aufgabe, dazu eine Wahl, womit du anfängst.',
    subWork: 'Posteingang und Aufgaben gehen an die Jev-API, nur Titel, Kurzfassung, Etikett und Priorität. Privates, ausgenommene Bereiche und was ein Agent erledigt bleiben hier. Jev ordnet einmal am Tag von selbst.',
    rerun: 'Neu bewerten', replay: 'Abspielen', urgency: 'Dringlichkeit →', impact: 'Wirkung →',
    quads: { now: 'Jetzt selbst', plan: 'Einplanen', hand: 'Abgeben', drop: 'Loslassen' },
    first: t => `Jev sagt: zuerst „${t}“`, plan: 'Fahrplan', me: 'du', delegate: 'abgeben',
    effort: ['Minuten', '< 1 h', '½ Tag', 'Tage'], tasks: 'Aufgaben', judgments: 'Urteile', ms: 'ms',
    cached: 'aus dem Zwischenspeicher', empty: 'Im Dashboard steht gerade nichts, was Jev bewerten könnte.',
    error: 'Jev hat nicht geantwortet', legendSize: 'Größe = Priorität', legendRing: 'Ring = Sicherheit',
    quick: n => `${n} schnelle Gewinne`, mine: n => `${n} nur für dich`, give: n => `${n} abgebbar`, sure: 'sicher',
    stale: 'seither geändert', staleTitle: 'Das Dashboard hat sich seit dieser Bewertung geändert. Jev bewertet von selbst einmal am Tag, neu bewerten geht jederzeit.',
    gone: 'Nichts aus dieser Bewertung steht noch im Dashboard.', from: 'von', tokens: 'Tokens', today: 'heute',
    ratings: n => (n === 1 ? '1 Bewertung' : `${n} Bewertungen`), noPrice: 'Kosten: von der API nicht genannt',
    noPriceTitle: 'Die Jev-API meldet nur Tokens (usage.input_tokens, usage.output_tokens), keinen Preis. Hier wird nichts geschätzt.',
    noTokens: 'Tokens: von der API nicht genannt', unknownPart: n => `${n} ohne Zählung`,
  },
  en: {
    tab: 'Jev', title: 'Jev rates your day', reading: n => `Jev is reading ${n} tasks`, rereading: 'Jev is reading again',
    sub: 'What the dashboard holds right now goes to the Jev API: urgency, impact, effort and "only you" per task, plus a choice of where to start.',
    subWork: 'Inbox and tasks go to the Jev API, only title, gist, label and priority. Private rows, skipped sections and what an agent does stay here. Jev orders once a day by itself.',
    rerun: 'Rate again', replay: 'Replay', urgency: 'Urgency →', impact: 'Impact →',
    quads: { now: 'Do it now', plan: 'Schedule', hand: 'Hand off', drop: 'Let go' },
    first: t => `Jev says: start with "${t}"`, plan: 'Plan', me: 'you', delegate: 'hand off',
    effort: ['minutes', '< 1 h', '½ day', 'days'], tasks: 'tasks', judgments: 'judgments', ms: 'ms',
    cached: 'from cache', empty: 'The dashboard holds nothing Jev could rate right now.',
    error: 'Jev did not answer', legendSize: 'size = priority', legendRing: 'ring = confidence',
    quick: n => `${n} quick wins`, mine: n => `${n} only you`, give: n => `${n} to hand off`, sure: 'sure',
    stale: 'changed since', staleTitle: 'The dashboard changed since this rating. Jev rates by itself once a day; rating again works any time.',
    gone: 'Nothing from this rating is on the dashboard any more.', from: 'from', tokens: 'tokens', today: 'today',
    ratings: n => (n === 1 ? '1 rating' : `${n} ratings`), noPrice: 'Cost: not given by the API',
    noPriceTitle: 'The Jev API reports tokens only (usage.input_tokens, usage.output_tokens), no price. Nothing is estimated here.',
    noTokens: 'Tokens: not given by the API', unknownPart: n => `${n} without a count`,
  },
}
const tx = () => TEXT[language() === 'de' ? 'de' : 'en']

const short = (s, n) => (s && s.length > n ? s.slice(0, n - 1).trimEnd() + '…' : s || '')

const QUADS = [
  { id: 'now', x: CORE.x, y: Y1, w: X1 - CORE.x, h: CORE.y - Y1, ax: X1 - 12, ay: Y1 + 22, anchor: 'end', ox: CORE.x, oy: CORE.y },
  { id: 'plan', x: X0, y: Y1, w: CORE.x - X0, h: CORE.y - Y1, ax: X0 + 12, ay: Y1 + 22, anchor: 'start', ox: CORE.x, oy: CORE.y },
  { id: 'hand', x: CORE.x, y: CORE.y, w: X1 - CORE.x, h: Y0 - CORE.y, ax: X1 - 12, ay: Y0 - 12, anchor: 'end', ox: CORE.x, oy: CORE.y },
  { id: 'drop', x: X0, y: CORE.y, w: CORE.x - X0, h: Y0 - CORE.y, ax: X0 + 12, ay: Y0 - 12, anchor: 'start', ox: CORE.x, oy: CORE.y },
]

/** ?jevT=2.4 freezes the first play at that T: for checking single frames, as web-check does in the films */
const FROZEN = (() => {
  if (typeof location === 'undefined') return null
  const v = new URLSearchParams(location.search).get('jevT')
  return v != null && isFinite(+v) ? +v : null
})()

/** The last answer survives a change of page tab: coming back shows the picture at rest instead of
 *  playing it again, and asks the server only whether it is still current. One per source: the Jev
 *  tab ('tab') and the Jev view of each work page (its id) */
const keptBy = {}

// ---------------------------------------------------------------- clock

/** One requestAnimationFrame loop for the frame function draw(now), which returns true while
 *  something still moves. It draws on every commit before paint, so a render never shows a value
 *  the frame owns at its markup state, and sleeps when nothing moves. kick() draws at once and
 *  keeps the loop going while the frame says so */
function useFrames(draw) {
  const ref = useRef({ draw, raf: 0 })
  ref.current.draw = draw
  const kick = useRef(() => {
    const st = ref.current
    const step = () => { st.raf = 0; if (st.draw(nowSec())) st.raf = requestAnimationFrame(step) }
    if (st.draw(nowSec()) && !st.raf) st.raf = requestAnimationFrame(step)
  }).current
  useLayoutEffect(() => { kick() })
  useEffect(() => () => cancelAnimationFrame(ref.current.raf), [])
  return kick
}

const still = () => FROZEN != null || reducedMotion()

const PULSE = 1.3
/** A ring that leaves the core once per PULSE seconds while Jev reads, grows and fades (ripples) */
function pulse(el, now, strength) {
  if (!el) return
  const [r] = ripples(now, [now - (now % PULSE)], { grow: 1.5, life: PULSE })
  el.setAttribute('transform', `translate(${CORE.x} ${CORE.y}) scale(${r.scale.toFixed(3)}) translate(${-CORE.x} ${-CORE.y})`)
  el.setAttribute('opacity', (r.alpha * 0.7 * strength).toFixed(3))
}

/** "HH:MM" of a time in ms, in the page's language */
const clockOf = ms => (ms ? new Date(ms).toLocaleTimeString(language() === 'de' ? 'de-DE' : 'en-GB', { hour: '2-digit', minute: '2-digit' }) : '')

// ---------------------------------------------------------------- reading (no answer yet)

function ThinkingScene({ titles }) {
  const ref = useRef(null)
  const t0 = useRef(nowSec()).current
  const n = titles.length
  const pos = titles.map((_, i) => {
    const a = -Math.PI / 2 + (i / Math.max(1, n)) * Math.PI * 2
    return { x: CORE.x + Math.cos(a) * 320, y: CORE.y + Math.sin(a) * 215 }
  })
  useFrames(now => {
    const root = ref.current
    if (!root) return false
    // under reduced motion nothing starts on its own: the still frame shows wires, titles and core
    const T = still() ? 1 : now - t0
    const moving = !still()
    // the orbits turn on the page clock, so they go on without a jump when the answer takes over
    root.querySelector('[data-k=spin1]')?.setAttribute('transform', `rotate(${moving ? ((now * 38) % 360).toFixed(2) : 0} ${CORE.x} ${CORE.y})`)
    root.querySelector('[data-k=spin2]')?.setAttribute('transform', `rotate(${moving ? ((-now * 24) % 360).toFixed(2) : 0} ${CORE.x} ${CORE.y})`)
    const breathe = moving ? 1 + 0.06 * Math.sin(T * 2.4) : 1
    root.querySelector('[data-k=core]')?.setAttribute('transform', `translate(${CORE.x} ${CORE.y}) scale(${breathe.toFixed(4)})`)
    root.querySelectorAll('[data-chip]').forEach(el => {
      const i = +el.dataset.chip
      const k = moving ? spring(T, 0.05 * i, { w: 8, zeta: 0.9 }) : 1
      const dx = moving ? noise1(T * 0.6 + i * 3.1, 7) * 6 : 0, dy = moving ? noise1(T * 0.5 + i, 3) * 5 : 0
      el.setAttribute('transform', `translate(${(pos[i].x + dx).toFixed(1)} ${(pos[i].y + dy).toFixed(1)}) scale(${(0.6 + 0.4 * k).toFixed(3)})`)
      el.setAttribute('opacity', (k * (moving ? 0.55 + 0.45 * (0.5 + 0.5 * noise1(T * 0.8 + i * 1.7, 11)) : 0.85)).toFixed(3))
    })
    root.querySelectorAll('[data-spark]').forEach(el => {
      const i = +el.dataset.spark
      const u = ((T * 0.55 + i * 0.137) % 1 + 1) % 1
      const k = o3(u)
      el.setAttribute('cx', (pos[i].x + (CORE.x - pos[i].x) * k).toFixed(1))
      el.setAttribute('cy', (pos[i].y + (CORE.y - pos[i].y) * k).toFixed(1))
      el.setAttribute('opacity', moving ? (flowAlpha(u) * ramp(T, 0.3 + 0.05 * i, 0.4)).toFixed(3) : '0')
    })
    pulse(root.querySelector('[data-k=pulse]'), now, moving ? 1 : 0)
    return moving
  })
  const t = tx()
  return html`<g ref=${ref} class="jev-thinking">
    ${pos.map((p, i) => html`<line key=${'l' + i} class="jev-wire" x1=${p.x} y1=${p.y} x2=${CORE.x} y2=${CORE.y} />`)}
    ${pos.map((_, i) => html`<circle key=${'s' + i} data-spark=${i} r="3.2" class="jev-spark" opacity="0" />`)}
    ${titles.map((title, i) => html`<g key=${'c' + i} data-chip=${i} opacity="0">
      <text class="jev-chip" text-anchor=${pos[i].x < CORE.x - 40 ? 'end' : pos[i].x > CORE.x + 40 ? 'start' : 'middle'}>${short(title, 22)}</text></g>`)}
    <circle data-k="pulse" class="jev-pulse" cx=${CORE.x} cy=${CORE.y} r="52" opacity="0" />
    <${Core} />
    <text class="jev-reading" x=${CORE.x} y=${CORE.y + 130} text-anchor="middle">${t.reading(n)}</text>
  </g>`
}

/** The core with its two orbits; `data-k` names are what the frame functions move */
function Core({ hidden }) {
  return html`<g data-k="core-wrap" opacity=${hidden ? 0 : 1}>
    <g data-k="spin1"><circle cx=${CORE.x} cy=${CORE.y} r="74" class="jev-orbit" pathLength="100" /></g>
    <g data-k="spin2"><circle cx=${CORE.x} cy=${CORE.y} r="92" class="jev-orbit jev-orbit-2" pathLength="100" /></g>
    <g data-k="core" transform=${`translate(${CORE.x} ${CORE.y})`}><circle r="48" class="jev-core" /><text class="jev-core-label" y="5" text-anchor="middle">Jev</text></g>
  </g>`
}

// ---------------------------------------------------------------- the answer (markup at rest)

function Matrix({ items, first, spots, emph, onDot }) {
  const t = tx()
  const fs = first ? spots.get(first.key) : null
  return html`<g class="jev-result">
    ${QUADS.map(q => html`<g key=${q.id} data-quad=${q.id}>
      <rect class=${`jev-quad jev-quad-${q.id}`} x=${q.x + 3} y=${q.y + 3} width=${q.w - 6} height=${q.h - 6} rx="14" />
      <rect class=${`jev-quad jev-quad-${q.id}`} data-qflash=${q.id} x=${q.x + 3} y=${q.y + 3} width=${q.w - 6} height=${q.h - 6} rx="14" opacity="0" /></g>`)}
    ${QUADS.map(q => html`<text key=${'q' + q.id} data-qlabel=${q.id} class=${`jev-qlabel jev-qlabel-${q.id}`} x=${q.ax} y=${q.ay} text-anchor=${q.anchor}></text>`)}
    <line data-axis="x" class="jev-axis" x1=${X0} y1=${Y0} x2=${X1} y2=${Y0} pathLength="1" stroke-dasharray="1" stroke-dashoffset="0" />
    <line data-axis="y" class="jev-axis" x1=${X0} y1=${Y0} x2=${X0} y2=${Y1} pathLength="1" stroke-dasharray="1" stroke-dashoffset="0" />
    <text class="jev-axis-label" x=${X1} y=${Y0 + 30} text-anchor="end">${t.urgency}</text>
    <text class="jev-axis-label" x=${X0 - 18} y=${Y1} text-anchor="end" transform=${`rotate(-90 ${X0 - 18} ${Y1})`}>${t.impact}</text>
    ${items.map((it, i) => html`<line key=${'t' + it.key} data-trail=${i} class=${`jev-trail jev-${it.who}`} x1=${CORE.x} y1=${CORE.y} x2=${CORE.x} y2=${CORE.y} opacity="0" />`)}
    ${items.map((it, i) => html`<circle key=${'s' + it.key} data-spark=${i} r="3.2" class="jev-spark" opacity="0" />`)}
    <circle data-k="pulse" class="jev-pulse" cx=${CORE.x} cy=${CORE.y} r="52" opacity="0" />
    ${[0, 1, 2].map(j => html`<circle key=${'r' + j} data-ripple=${j} r=${fs ? fs.r + 6 : 0} class="jev-ripple" opacity="0" />`)}
    ${items.map((it, i) => ({ it, i })).reverse().map(({ it, i }) => {
      const sp = spots.get(it.key)
      const on = emph(it.key)
      return html`<g key=${it.key} data-dot=${i} transform=${`translate(${sp.x.toFixed(1)} ${sp.y.toFixed(1)})`}
        class=${`jev-dot jev-${it.who}${on ? ' is-hover' : ''}${it.key === first?.key ? ' is-first' : ''}`} onClick=${e => onDot(it, e)}>
        <circle class="jev-dot-glow" data-glow=${i} r=${sp.r + 10} opacity="0" />
        <circle class="jev-dot-ring" r=${sp.r + 4} pathLength="1" stroke-dasharray="1" stroke-dashoffset=${(1 - (it.confidence ?? 0)).toFixed(4)} data-conf=${i} />
        <circle class="jev-dot-core" r=${sp.r} />
        <text class="jev-dot-rank" y="4" text-anchor="middle">${it.rank}</text>
        <text data-label=${i} opacity=${it.rank <= 4 ? 1 : 0} class="jev-dot-label" y="4"
          x=${sp.x > X1 - 220 ? -(sp.r + 9) : sp.r + 9} text-anchor=${sp.x > X1 - 220 ? 'end' : 'start'}>${short(it.title, it.rank <= 4 ? 26 : 44)}</text>
        <title>${it.title}</title>
      </g>`
    })}
    ${fs ? html`<g data-k="crown" transform=${`translate(${fs.x.toFixed(1)} ${(fs.y - fs.r - 14).toFixed(1)})`}><path class="jev-crown" d="M-11 4 L-11 -6 L-5 -1 L0 -9 L5 -1 L11 -6 L11 4 Z" /></g>` : null}
    <${Core} hidden />
  </g>`
}

function PlanList({ items, byKey, s, c, emph, setHover, listRef }) {
  const t = tx()
  const d = dashText()
  return html`<ol class="jev-plan" ref=${listRef}>
    ${items.map((it, i) => {
      const row = byKey.get(it.key)
      const jump = rowJump(row)
      const selected = s.ui.pageDetail && s.ui.selectedKey === it.key
      return html`<li key=${it.key} data-row=${i} data-key=${it.key}
        class=${`jev-row${emph(it.key) ? ' is-hover' : ''}${selected ? ' is-selected' : ''}`}
        onMouseEnter=${() => setHover(it.key)} onMouseLeave=${() => setHover(null)}>
        <span class=${`jev-rank mono jev-${it.who}`} data-rank=${i}>${it.rank}</span>
        <span class="jev-row-main">
          ${row ? html`<button type="button" class="btn-link jev-row-title" data-open=${it.key} title=${d.openDetail} aria-expanded=${String(selected)}
              onFocus=${() => setHover(it.key)} onBlur=${() => setHover(null)} onClick=${e => c.peek(it.key, e.currentTarget)}>${it.title}</button>`
            : html`<span class="jev-row-title">${it.title}</span>`}
          <span class="jev-row-meta">
            <span class=${`jev-pill jev-${it.who}`}>${it.who === 'me' ? t.me : t.delegate}</span>
            <span class="jev-pill">${t.effort[Math.min(3, Math.round(it.effort * 3))]}</span>
            <span class="jev-pill">${t.quads[it.quadrant]}</span>
            ${it.confidence != null ? html`<span class="jev-conf mono" title=${t.legendRing}><span data-pct=${i} data-to=${Math.round(it.confidence * 100)}></span> % ${t.sure}</span>` : null}
          </span>
          <span class="jev-bar"><span class=${`jev-bar-fill jev-${it.who}`} data-bar=${i} style=${{ transform: `scaleX(${(it.priority ?? 0).toFixed(4)})` }}></span></span>
        </span>
        ${jump ? html`<button type="button" class=${`btn btn-ghost btn-xs jev-row-act${jump.verb === 'advise' ? ' is-quiet' : ''}`} aria-busy=${String(!!s.ui.busy[jump.busy])}
            disabled=${!!s.ui.busy[jump.busy]} onFocus=${() => setHover(it.key)} onBlur=${() => setHover(null)}
            onClick=${() => c.act(jump.verb, jump.args)}><span class="btn-label">${jump.verb === 'tab_jump' ? d.btnToTab : d.action.advise}</span></button>` : null}
      </li>`
    })}
  </ol>`
}

function Headline({ items, data, headRef }) {
  const t = tx()
  const quick = items.filter(it => it.effort < 0.34 && it.impact >= 0.5).length
  const mine = items.filter(it => it.who === 'me').length
  const nums = [items.length, data.questions ?? 0, data.took_ms ?? 0]
  const cost = costLine(data)
  return html`<div class="jev-head" ref=${headRef}>
    <p class="jev-first"><span data-k="line"></span><span class="jev-cursor" data-k="cursor" aria-hidden="true" style=${{ opacity: 0 }}>▍</span></p>
    <div class="jev-stats">
      ${data.at_ms ? html`<span>${t.from} <b class="mono">${clockOf(data.at_ms)}</b></span>` : null}
      ${[t.tasks, t.judgments, t.ms].map((label, i) => html`<span key=${label}><b class="mono" data-num=${i} data-to=${nums[i]}></b> ${label}</span>`)}
      ${cost ? html`<span class="jev-cost" title=${t.noPriceTitle}>
          <span class="jev-cost-glow" data-k="costglow" aria-hidden="true" style=${{ opacity: 0 }}></span>
          <b class="mono jev-num-wide" data-num="3" data-to=${cost.tokens} data-fmt="tok"></b> ${t.tokens}
          <span class="jev-cost-today">· ${t.today} <b class="mono jev-num-wide" data-num="4" data-to=${cost.today} data-fmt="tok"></b>${' '}(${t.ratings(cost.ratings)}${cost.unknown ? `, ${t.unknownPart(cost.unknown)}` : ''})</span></span>
        <span class="jev-price" title=${t.noPriceTitle}>${t.noPrice}</span>`
        : html`<span class="jev-price" title=${t.noPriceTitle}>${t.noTokens}</span>`}
      <span class="jev-chipline">
        <span class="jev-pill jev-me" data-chip="0">${t.mine(mine)}</span>
        <span class="jev-pill jev-delegate" data-chip="1">${t.give(items.length - mine)}</span>
        <span class="jev-pill jev-quick" data-chip="2">${t.quick(quick)}</span>
      </span>
    </div>
  </div>`
}

// ---------------------------------------------------------------- page

export function JevPage({ s, c, ask = null, extra = null, store = 'tab', top = null }) {
  const t = tx()
  const kept = keptBy[store] ?? null
  const [st, setSt] = useState(() => ({ data: kept, reading: false, err: null }))
  const [hover, setHover] = useState(null)
  const seq = useRef(0)
  const live = useRef(true)
  // what is playing: the first answer in full ('intro'), a new answer gliding from where the tasks
  // stood ('update'), or the picture at rest ('rest', for an answer seen before)
  const play = useRef({ mode: kept ? 'rest' : 'intro', t0: nowSec(), from: new Map(), nums: null, firstChanged: false,
    firstKey: kept ? liveItems(kept.plan, s.model, extra).first?.key ?? null : null })
  const dataRef = useRef(st.data)
  dataRef.current = st.data
  const motion = useRef({ pos: new Map(), emph: new Map(), bars: new Map(), flip: new Map(), tops: new Map(), read: null, nums: null })
  const svgRef = useRef(null), headRef = useRef(null), listRef = useRef(null)

  const byKey = indexRows(s.model)
  const plan = st.data?.plan
  const { items, first } = liveItems(plan, s.model, extra)
  const spots = new Map(items.map(it => [it.key, place(it)]))
  const selected = s.ui.pageDetail ? s.ui.selectedKey : null
  const emph = key => key === hover || key === selected
  const titles = pendingTitles(s.model)

  /** Start the play of a new answer: from the current picture when there is one */
  const startPlay = (data, prev) => {
    const m = motion.current
    const had = !!prev?.plan?.items?.length
    const firstKey = liveItems(data.plan, s.model, extra).first?.key ?? null
    play.current = had
      ? { mode: 'update', t0: nowSec(), from: new Map(m.pos), nums: m.nums, firstChanged: firstKey !== play.current.firstKey, firstKey }
      : { mode: 'intro', t0: nowSec(), from: new Map(), nums: null, firstChanged: true, firstKey }
  }

  /** Ask the server for the rating. It rates by itself at most once a day and otherwise answers
   *  the kept one (also after a restart), so the page can ask on every visit and every new model;
   *  force is the button. "Reading" shows at once for the button and only after a moment for a
   *  background check, so a kept answer never flashes the reading scene */
  const run = async (force = false) => {
    const my = ++seq.current
    if (force) setSt(x => ({ ...x, reading: true, err: null }))
    const slow = force ? null : setTimeout(() => { if (live.current && my === seq.current) setSt(x => ({ ...x, reading: true })) }, 350)
    const res = await (ask ? ask(force) : c.jevRun(force))
    clearTimeout(slow)
    if (!live.current || my !== seq.current) return   // a newer request or a page change won
    if (res.ok && res.data) {
      const prev = dataRef.current
      const same = prev && prev.digest === res.data.digest && prev.at_ms === res.data.at_ms
      if (!same && !res.data.empty) startPlay(res.data, prev)
      // the same rating keeps its object (no new play) but takes the fresh note and day total
      keptBy[store] = same ? { ...prev, changed: res.data.changed, today: res.data.today, cached: res.data.cached } : res.data
      setSt({ reading: false, err: null, data: keptBy[store] })
    } else {
      const msg = res.data?.error?.message || res.error?.message || ''
      setSt(x => ({ ...x, reading: false, err: msg || t.error }))
    }
  }

  // every visit and every new model asks; the server spends a request only on the first of a day
  useEffect(() => { if (s.model) run() }, [s.model?.seq ?? 0])
  useEffect(() => () => { live.current = false }, [])

  const replay = () => {
    play.current = { ...play.current, mode: 'intro', t0: nowSec(), firstChanged: true }
    kick()
  }

  // ---- the one frame function of the answer: matrix, headline and plan list
  const kick = useFrames(now => {
    const m = motion.current
    const P = play.current
    const calm = still()
    const T = FROZEN ?? (calm ? 1e6 : now - P.t0)
    const intro = P.mode === 'intro'
    const Ti = intro ? Math.min(T, DUR) : DUR
    const glide = P.mode === 'update' && !calm
    let busy = !calm && (intro ? T < DUR : glide ? T < GLIDE : false)

    m.read = track(m.read, st.reading && plan ? 1 : 0, now, calm)
    const read = trackAt(m.read, now)
    busy = busy || tracking(m.read) || (st.reading && !!plan && !calm) || (intro && !calm && T < DUR)

    const root = svgRef.current
    if (root && plan) {
      root.querySelectorAll('[data-axis]').forEach((el, i) =>
        el.setAttribute('stroke-dashoffset', (1 - spring(Ti, 0.1 + i * 0.15, { w: 7, zeta: 1 })).toFixed(4)))
      root.querySelectorAll('[data-quad]').forEach((el, i) => {
        const k = spring(Ti, 0.35 + i * 0.12, { w: 8, zeta: 0.95 })
        const q = QUADS[i]
        el.setAttribute('transform', `translate(${q.ox} ${q.oy}) scale(${k.toFixed(4)}) translate(${-q.ox} ${-q.oy})`)
        el.setAttribute('opacity', Math.min(1, k * 1.2).toFixed(3))
      })
      root.querySelectorAll('[data-qlabel]').forEach((el, i) => {
        el.textContent = typed(Ti, tx().quads[QUADS[i].id], 0.55 + i * 0.14, 0.45)
      })
      // a quadrant lights up briefly as its tasks land in it
      const Tq = intro ? Ti : glide ? T : 1e6
      root.querySelectorAll('[data-qflash]').forEach(el => {
        const hits = items.map((it, i) => (it.quadrant === el.dataset.qflash
          ? (intro ? launch(i, items.length) + 0.45 : 0.05 + i * 0.035 + 0.6) : null)).filter(h => h != null)
        el.setAttribute('opacity', (calm ? 0 : 0.6 * flash(Tq, hits, 3.5)).toFixed(3))
      })
      // the core: it held the tasks while Jev read and shrinks away as it releases them; it comes
      // back while Jev reads again, and turns its orbits
      const out = spring(Ti, 1.35, { w: 7, zeta: 1 })
      const core = Math.max(1 - out, read)
      const wrap = root.querySelector('.jev-result > [data-k=core-wrap]')
      if (wrap) {
        wrap.setAttribute('opacity', core.toFixed(3))
        const breathe = calm ? 1 : 1 + 0.05 * Math.sin(now * 2.4) * read
        wrap.querySelector('[data-k=core]')?.setAttribute('transform', `translate(${CORE.x} ${CORE.y}) scale(${(core * breathe).toFixed(4)})`)
        const spin = calm ? 0 : now
        wrap.querySelector('[data-k=spin1]')?.setAttribute('transform', `rotate(${((spin * 38) % 360).toFixed(2)} ${CORE.x} ${CORE.y}) translate(${CORE.x} ${CORE.y}) scale(${core.toFixed(4)}) translate(${-CORE.x} ${-CORE.y})`)
        wrap.querySelector('[data-k=spin2]')?.setAttribute('transform', `rotate(${((-spin * 24) % 360).toFixed(2)} ${CORE.x} ${CORE.y}) translate(${CORE.x} ${CORE.y}) scale(${core.toFixed(4)}) translate(${-CORE.x} ${-CORE.y})`)
      }
      const pos = new Map()
      items.forEach((it, i) => {
        const sp = spots.get(it.key)
        const from = intro ? CORE : (P.from.get(it.key) ?? CORE)
        const isNew = !intro && !P.from.has(it.key)
        const s0 = intro ? launch(i, items.length) : 0.05 + i * 0.035
        const k = calm || P.mode === 'rest' ? 1 : intro ? spring(Ti, s0, { w: 8.5, zeta: 0.68 }) : spring(T, s0, { w: 7.5, zeta: 0.95 })
        // while Jev reads again every task leans a little toward the core
        const lean = 0.12 * read
        const x0 = from.x + (sp.x - from.x) * k, y0 = from.y + (sp.y - from.y) * k
        const x = x0 + (CORE.x - x0) * lean, y = y0 + (CORE.y - y0) * lean
        pos.set(it.key, { x, y, r: sp.r })
        m.emph.set(it.key, track(m.emph.get(it.key), emph(it.key) ? 1 : 0, now, calm))
        const e = trackAt(m.emph.get(it.key), now, EMPH)
        busy = busy || tracking(m.emph.get(it.key))
        // a dot pops in with a little overshoot of its own and rests at its size
        const grow = (intro || isNew) && !calm ? spring(intro ? Ti : T, s0, { w: 10, zeta: 0.62 }) : 1
        const dot = root.querySelector(`[data-dot="${i}"]`)
        if (dot) {
          dot.setAttribute('transform', `translate(${x.toFixed(1)} ${y.toFixed(1)}) scale(${(grow * (1 + 0.16 * e)).toFixed(3)})`)
          dot.setAttribute('opacity', (Math.min(1, intro || isNew ? k * 3 : 1) * (1 - 0.45 * read)).toFixed(3))
        }
        root.querySelector(`[data-glow="${i}"]`)?.setAttribute('opacity', e.toFixed(3))
        // and sends light points along an invisible wire into it
        const spark = root.querySelector(`[data-spark="${i}"]`)
        if (spark) {
          const u = ((now * 0.6 + i * 0.137) % 1 + 1) % 1
          const q = o3(u)
          spark.setAttribute('cx', (x + (CORE.x - x) * q).toFixed(1))
          spark.setAttribute('cy', (y + (CORE.y - y) * q).toFixed(1))
          spark.setAttribute('opacity', (calm ? 0 : flowAlpha(u) * read).toFixed(3))
        }
        const trail = root.querySelector(`[data-trail="${i}"]`)
        if (trail) {
          trail.setAttribute('x1', from.x.toFixed(1)); trail.setAttribute('y1', from.y.toFixed(1))
          trail.setAttribute('x2', x.toFixed(1)); trail.setAttribute('y2', y.toFixed(1))
          const tw = intro ? win(Ti, s0, s0 + 0.55, 0.3) : glide ? win(T, s0, s0 + 0.5, 0.25) : 0
          trail.setAttribute('opacity', (0.55 * tw).toFixed(3))
        }
        root.querySelector(`[data-conf="${i}"]`)?.setAttribute('stroke-dashoffset',
          (1 - (it.confidence ?? 0) * (intro ? spring(Ti, s0 + 0.5, { w: 6, zeta: 1 }) : 1)).toFixed(4))
        const label = root.querySelector(`[data-label="${i}"]`)
        if (label) {
          const base = it.rank <= 4 ? (intro || isNew ? ramp(intro ? Ti : T, s0 + 0.6, 0.4) : 1) : 0
          label.setAttribute('opacity', Math.max(base, e).toFixed(3))
        }
      })
      m.pos = pos
      pulse(root.querySelector('.jev-result > [data-k=pulse]'), now, calm ? 0 : read)
      // the first task: two rings when it arrives, the crown follows it to its place
      const fp = first ? pos.get(first.key) : null
      if (fp) {
        const hits = intro ? [FOCUS_T, FOCUS_T + 0.32] : P.firstChanged && glide ? [0.9, 1.22] : []
        const rs = ripples(intro ? T : glide ? T : 1e6, hits, { grow: 2.2, life: 1.1 })
        root.querySelectorAll('[data-ripple]').forEach((el, j) => {
          const r = rs[j] ?? { alpha: 0, scale: 1 }
          el.setAttribute('r', (fp.r + 6).toFixed(1))
          el.setAttribute('transform', `translate(${fp.x.toFixed(1)} ${fp.y.toFixed(1)}) scale(${r.scale.toFixed(3)})`)
          el.setAttribute('opacity', (calm ? 0 : r.alpha * 0.9).toFixed(3))
        })
        if (hits.length && !calm) busy = busy || T < hits[hits.length - 1] + 1.6
        const crown = root.querySelector('[data-k=crown]')
        if (crown) {
          const k = intro ? spring(Ti, FOCUS_T, { w: 9, zeta: 0.7 }) : 1
          crown.setAttribute('transform', `translate(${fp.x.toFixed(1)} ${(fp.y - fp.r - 14 - 10 * (1 - k)).toFixed(1)}) scale(${clamp(0, 1.2, k).toFixed(3)})`)
          crown.setAttribute('opacity', (Math.min(1, k * 1.5) * (1 - 0.45 * read)).toFixed(3))
        }
      }
    }

    // the headline: in the first play it types and counts; a new first task types again, the
    // numbers count from where they stood
    const head = headRef.current
    if (head && plan) {
      const line = head.querySelector('[data-k=line]')
      const text = first ? tx().first(short(first.title, 70)) : ''
      const typeAt = intro ? 2.7 : P.firstChanged && glide ? 0.3 : null
      if (line) line.textContent = typeAt == null || calm ? text : typed(intro ? Ti : T, text, typeAt, 1.1)
      const cur = head.querySelector('[data-k=cursor]')
      if (cur) cur.style.opacity = typeAt != null && !calm && (intro ? Ti : T) > typeAt - 0.1 && cursorOn(intro ? Ti : T, typeAt, 1.1) ? '1' : '0'
      if (typeAt != null && !calm) busy = busy || (intro ? Ti : T) < typeAt + 3.2
      // the counters run up from zero, or from where they stood; the tokens count last and longest,
      // and the cost line lights up once when they arrive
      const nums = []
      const lang = language()
      head.querySelectorAll('[data-num]').forEach((el, i) => {
        const to = +el.dataset.to
        const from = intro ? 0 : P.nums?.[i] ?? to
        const at = intro ? (i >= 3 ? 1.0 : 0.2 + i * 0.15) : 0.1
        const v = calm || P.mode === 'rest' ? to : countTo(intro ? Ti : T, to, at, i >= 3 ? 1.6 : intro ? 1.2 : 0.8, from)
        el.textContent = el.dataset.fmt === 'tok' ? tokenText(v, lang) : String(Math.round(v))
        nums.push(v)
      })
      m.nums = nums
      const glow = head.querySelector('[data-k=costglow]')
      if (glow) {
        const hit = intro ? 2.75 : glide ? 1.0 : null
        glow.style.opacity = (calm || hit == null ? 0 : flash(intro ? Ti : T, [hit], 2.2)).toFixed(3)
        if (hit != null && !calm) busy = busy || (intro ? Ti : T) < hit + 2
      }
      head.querySelectorAll('[data-chip]').forEach((el, i) => {
        const k = intro ? spring(Ti, 3.6 + i * 0.12, { w: 9, zeta: 0.9 }) : 1
        el.style.opacity = Math.min(1, k * 1.3).toFixed(3)
        el.style.transform = `translateY(${((1 - k) * 8).toFixed(1)}px)`
      })
    }

    // the plan: rows run in during the first play, move to their new rank on a spring later on,
    // bars follow their priority
    const list = listRef.current
    if (list && plan) {
      list.querySelectorAll('[data-row]').forEach(el => {
        const i = +el.dataset.row
        const key = el.dataset.key
        const k = intro ? spring(Ti, 2.0 + i * 0.11, { w: 8, zeta: 0.95 }) : 1
        const f = m.flip.get(key)
        const dy = f ? trackAt(f, now, { w: 11, zeta: 0.95 }) : 0
        busy = busy || tracking(f)
        el.style.opacity = (Math.min(1, k * 1.2) * (1 - 0.3 * read)).toFixed(3)
        el.style.transform = `translate(${((1 - k) * -22).toFixed(1)}px, ${dy.toFixed(1)}px)`
        const it = items[i]
        // the rank badge pops in after its row, the confidence counts up with the bar
        const badge = el.querySelector('[data-rank]')
        if (badge) badge.style.transform = `scale(${(intro && !calm ? spring(Ti, 2.1 + i * 0.11, { w: 12, zeta: 0.55 }) : 1).toFixed(3)})`
        const pct = el.querySelector('[data-pct]')
        if (pct) {
          const to = +pct.dataset.to
          m.pcts = m.pcts ?? new Map()
          m.pcts.set(key, track(m.pcts.get(key), to, now, calm || intro))
          const base = trackAt(m.pcts.get(key), now, { w: 7, zeta: 0.95 })
          busy = busy || tracking(m.pcts.get(key))
          pct.textContent = String(Math.round(intro && !calm ? countTo(Ti, base, 2.25 + i * 0.11, 0.9) : base))
        }
        const bar = el.querySelector('[data-bar]')
        if (bar && it) {
          m.bars.set(key, track(m.bars.get(key), it.priority ?? 0, now, calm || intro))
          const b = trackAt(m.bars.get(key), now, { w: 7, zeta: 0.95 })
          busy = busy || tracking(m.bars.get(key))
          bar.style.transform = `scaleX(${((intro ? spring(Ti, 2.2 + i * 0.11, { w: 7, zeta: 0.95 }) : 1) * b).toFixed(4)})`
        }
      })
    }
    return busy && FROZEN == null
  })

  // rows that changed place in the list start from where they stood (FLIP), measured before paint
  const flipSeen = useRef(null)
  const listId = `${st.data?.digest ?? ''}|${items.map(it => it.key).join(',')}`
  useLayoutEffect(() => {
    const list = listRef.current
    const m = motion.current
    if (!list) { m.tops = new Map(); return }
    const now = nowSec()
    const tops = new Map()
    list.querySelectorAll('[data-row]').forEach(el => tops.set(el.dataset.key, el.offsetTop))
    const changed = flipSeen.current !== null && flipSeen.current !== listId
    flipSeen.current = listId
    if (changed && play.current.mode !== 'intro' && !still()) {
      for (const [key, top] of tops) {
        const was = m.tops.get(key)
        if (was != null && was !== top) m.flip.set(key, { from: was - top + trackAt(m.flip.get(key), now), to: 0, moves: [[now, 0]] })
      }
    }
    m.tops = tops
    if (changed) kick()
  })

  const onDot = (it, e) => {
    if (!byKey.has(it.key)) return
    const from = listRef.current?.querySelector(`[data-open="${CSS.escape(it.key)}"]`) ?? e.currentTarget
    c.peek(it.key, from)
  }

  const thinking = !plan && (st.reading || st.err)
  const calmNow = still()
  return html`<div class="col col-page jev-page">
    <header class="page-head jev-top">
      <div>
        ${top ?? html`<h2 class="detail-title">${t.title}</h2>`}
        <p class="muted small jev-sub">${ask ? t.subWork : t.sub}</p>
      </div>
      <div class="jev-actions">
        ${plan && items.length && !calmNow ? html`<button type="button" class="btn btn-ghost btn-sm" onClick=${replay}>${t.replay}</button>` : null}
        <button type="button" class="btn btn-primary btn-sm" disabled=${st.reading} aria-busy=${String(st.reading)}
          onClick=${() => run(true)}><span class="btn-label">${t.rerun}</span></button>
      </div>
    </header>
    ${st.err ? html`<div class="jev-error" role="alert">${t.error}: ${st.err}</div>` : null}
    ${st.data?.empty ? html`<div class="panel panel-pad muted">${t.empty}</div>` : html`
    <div class="jev-grid">
      <div class="jev-stage panel">
        ${plan ? html`<${Headline} items=${items} data=${st.data} headRef=${headRef} />` : null}
        <svg class="jev-svg" viewBox=${`0 0 ${W} ${H}`} role="img" aria-label=${t.title} preserveAspectRatio="xMidYMid meet">
          <defs>
            <radialGradient id="jev-core-fill" cx="50%" cy="40%" r="60%">
              <stop offset="0%" class="jev-stop-a" /><stop offset="100%" class="jev-stop-b" />
            </radialGradient>
          </defs>
          ${thinking ? html`<${ThinkingScene} titles=${titles} />`
            : plan ? html`<g ref=${svgRef}><${Matrix} items=${items} first=${first} spots=${spots} emph=${emph} onDot=${onDot} /></g>` : null}
        </svg>
        ${plan ? html`<div class="jev-legend muted small" aria-live="polite">
          <span><i class="jev-swatch jev-me"></i>${t.me}</span><span><i class="jev-swatch jev-delegate"></i>${t.delegate}</span>
          <span>${t.legendSize}</span><span>${t.legendRing}</span>
          ${plan.model ? html`<span class="mono">· ${plan.model}</span>` : null}
          ${st.reading ? html`<span class="jev-note">· ${t.rereading}</span>`
            : !items.length ? html`<span class="jev-note">· ${t.gone}</span>`
            : st.data.changed ? html`<span class="jev-note" title=${t.staleTitle}>· ${t.stale}</span>` : null}
        </div>` : null}
      </div>
      <aside class="jev-side panel">
        <h3 class="jev-side-title">${t.plan}</h3>
        ${plan ? html`<${PlanList} items=${items} byKey=${byKey} s=${s} c=${c} emph=${emph} setHover=${setHover} listRef=${listRef} />`
          : html`<ol class="jev-plan jev-plan-ghost">${titles.slice(0, 7).map((x, i) => html`<li key=${i} class="jev-row"><span class="jev-rank mono">·</span><span class="jev-row-title muted">${x}</span></li>`)}</ol>`}
      </aside>
    </div>`}
  </div>`
}

/** The Jev view of the work tab: the same picture, fed by the order of the work page (POST /api/jev/rank
 *  with daily), so the page's private filter applies and Jev orders once a day by itself. `extra` are the
 *  keys of rows only the work page holds, so they stay in the picture; `top` is the tab's view switch */
export function JevWork({ s, c, page, extra, top }) {
  const ask = async force => {
    const res = await c.jevWork(page.id, force)
    if (!res.ok) return res
    const data = orderPlan(res.data.order) ?? { ok: true, empty: true, plan: { items: [], first: null } }
    return { ok: true, data: { ...data, today: res.data.today } }
  }
  return html`<${JevPage} s=${s} c=${c} ask=${ask} extra=${extra} store=${page.id} top=${top} />`
}
