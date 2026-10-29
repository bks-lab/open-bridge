// SPDX-License-Identifier: MIT
// The cockpit, the time range of a log page (views/logpage.js, a page whose `view: log` section is the work log):
// the presets, the range in words, Back, the bar width and a bar chart of the log rows per bar. A drag picks a
// range snapped to the bars, a click zooms into one bar, hovering names the bar, its count and its busiest contexts.
// Mouse first: no key does anything here, and none is named. The rows come from /api/logrange (s.logRange, loaded
// by the page), today's from the section until it answers; the buckets are counted here (logic.js), so a zoom,
// another width or the typed words never ask the server again.
// The rules every component keeps stand at the head of components.js.

import { html, useEffect, useLayoutEffect, useRef, useState } from '../vendor/htm-preact-3.1.1.module.js'
import { RANGE_PRESETS, shiftDays, chartGeometry, clockTime, dayStart, dayTime, isoDate, logRangeRows, logTodayRows,
  niceMax, rangeCounts, rangeDay, rangeEdges, rangeOf, rangeOneDay, rangeSlice, rangeStep, rangeStepAuto, rangeSteps,
  rangeTicks, shortDay } from '../logic.js'
import { T, language } from '../text.js'

/** The kinds the chart of Every day stacks, bottom up, each with its colour token */
export const RANGE_KINDS = [['did', 'var(--accent)'], ['discussed', 'var(--warning)'], ['closed', 'var(--success)'], ['transcript', 'var(--secondary)']]
const CHART_H = 150
const MARGIN = { l: 38, r: 10, t: 12, b: 24 }
const WIDTH = 720           // until the chart is measured (and in a test, which has no layout)

// ---------------------------------------------------------------- the range of a page, shared by its head and its body

const RANGE_STATES = new Map()        // page id -> { range, back, step }
const rangeListeners = new Map()     // page id -> the setters of the components that show it
const todayRange = () => ({ range: { preset: 'today' }, back: [], step: 'auto' })

function publishRange(id, value) {
  RANGE_STATES.set(id, value)
  for (const set of rangeListeners.get(id) ?? []) set(value)
}

/** The range of a log page as [{range, back, step}, set]: `range` a preset ({preset}) or {from, to}, `back` the RANGE_STATES
 *  before, `step` the bar width chosen. The page's head and its body stand apart and read the same one; the body
 *  (`open`) starts it at Today each time the page opens */
export function useLogRange(id, open = false) {
  const [value, setValue] = useState(() => {
    if (open || !RANGE_STATES.has(id)) RANGE_STATES.set(id, todayRange())
    return RANGE_STATES.get(id)
  })
  useEffect(() => {
    const set = rangeListeners.get(id) ?? new Set()
    rangeListeners.set(id, set)
    set.add(setValue)
    if (open) publishRange(id, RANGE_STATES.get(id))
    else setValue(RANGE_STATES.get(id))
    return () => set.delete(setValue)
  }, [id])
  // the one that sets it shows it at once, also before its effect has subscribed it (a click right after the page stood)
  return [value, next => {
    const v = typeof next === 'function' ? next(RANGE_STATES.get(id) ?? todayRange()) : next
    publishRange(id, v)
    setValue(v)
  }]
}

// ---------------------------------------------------------------- what a page's range holds

/** The days a range needs from the server: from (null for All, from the log's first day) and to, both included */
export function rangeDays(cur) {
  return { from: cur.preset === 'all' ? null : isoDate(cur.from), to: isoDate(cur.to - 1) }
}

/** Whether what the page loaded (s.logRange) holds the days a range needs, or is on its way */
export function rangeHeld(have, want) {
  if (!have || have.status === 'error') return false
  const from = have.status === 'ok' ? have.data?.from ?? have.from : have.from
  const to = have.status === 'ok' ? have.data?.to ?? have.to : have.to
  if (want.from === null) return have.from === null && to >= want.to
  return (have.from === null || (from ?? '') <= want.from) && (to ?? '') >= want.to
}

/** The log section a page's range follows (the work log drawn as `view: log`) and the rail's commits section */
export function rangeSections(page) {
  const secs = page?.sections ?? []
  return { log: secs.find(sec => sec.view === 'log' && sec.kind === 'activity' && sec.place !== 'rail') ?? null,
    commits: secs.find(sec => sec.kind === 'commits' && sec.place === 'rail') ?? null }
}

const rowsKept = new WeakMap()     // the answer of /api/logrange -> its rows, sorted once

/** The range resolved and its rows: {cur, asc (every row known, oldest first), rows (those of the range, newest first),
 *  first, repos, held, compact} from the loaded answer where it holds the range, else today's rows of the section */
export function rangeView(page, s, state) {
  const now = s.now || Date.now()
  const data = s.logRange?.status === 'ok' || s.logRange?.status === 'loading' ? s.logRange?.data ?? null : null
  const first = data?.first ? dayTime(data.first, '00:00') : null
  const cur = rangeOf(state.range, now, first)
  const want = rangeDays(cur)
  const held = !!data && (want.from === null ? true : (data.from ?? '') <= want.from) && (data.to ?? '') >= want.to
  const { log } = rangeSections(page)
  let asc
  if (held || (data && !rangeOneDay(cur.from, cur.to))) {
    if (!rowsKept.has(data)) rowsKept.set(data, logRangeRows(data))
    asc = rowsKept.get(data)
  } else {
    asc = logTodayRows(s.more?.[`${page.id}/${log?.id}`]?.items ?? log?.items ?? [], now)
  }
  // compact: the rows came from the range's answer without their text (they carry an id), not from the section
  return { cur, asc, rows: rangeSlice(asc, cur.from, cur.to), first, repos: data?.repos ?? null, held, want, now,
    compact: asc.length > 0 && asc[0].id != null }
}

// ---------------------------------------------------------------- words

/** A range in words: one whole day, days, or the hours of one day or across days */
export function rangeText(from, to, lang) {
  const w = T().logRange
  const mid = ms => { const d = new Date(ms); return d.getHours() === 0 && d.getMinutes() === 0 }
  if (mid(from) && mid(to)) {
    if (shiftDays(from, 1) === to) return `${rangeDay(from, lang)}, ${w.wholeDay}`
    return `${rangeDay(from, lang, false)} ${w.to} ${rangeDay(to - 1, lang)}`
  }
  if (dayStart(from) === dayStart(to - 1)) return `${rangeDay(from, lang)}, ${clockTime(from)} ${w.to} ${mid(to) ? '24:00' : clockTime(to)}`
  return `${rangeDay(from, lang, false)} ${clockTime(from)} ${w.to} ${rangeDay(to, lang, false)} ${mid(to) ? '00:00' : clockTime(to)}`
}

/** One bar in words: its week, its day, or its hours */
function barText(a, b, step, lang) {
  const w = T().logRange
  if (step.min === 10080) return w.week(shortDay(a, lang), shortDay(b - 1, lang))
  if (step.min === 1440) return rangeDay(a, lang)
  const end = new Date(b)
  return `${rangeDay(a, lang, false)}, ${clockTime(a)} ${w.to} ${end.getHours() === 0 && end.getMinutes() === 0 ? '24:00' : clockTime(b)}`
}

// ---------------------------------------------------------------- the panel

/** The range panel: presets, the range and its count, Back, the bar width, the chart and its key.
 *  `series` [{kind, items}] what the bars count (one kind, or the kinds of Every day stacked), `count` the words of the
 *  count, `contexts(items)` the busiest contexts of a bar's rows for its tooltip */
export function RangePanel({ page, cur, state, set, series, count, keyText, stacked = false, now }) {
  const w = T().logRange
  const lang = language()
  const auto = rangeStepAuto(cur.from, cur.to)
  const step = rangeStep(cur.from, cur.to, state.step)
  const pick = range => set(st => ({ ...st, back: [...st.back, st.range], range }))
  const back = () => set(st => (st.back.length ? { ...st, range: st.back[st.back.length - 1], back: st.back.slice(0, -1) } : st))
  return html`<section class="panel logr" aria-label=${w.label}>
    <div class="logr-top">
      <div class="logr-presets" role="group" aria-label=${w.presetsLabel}>
        ${RANGE_PRESETS.map(p => html`<button type="button" key=${p} aria-pressed=${String(cur.preset === p)} class=${cur.preset === p ? 'is-on' : ''}
          onClick=${() => { if (cur.preset !== p) pick({ preset: p }) }}>${w.preset[p]}</button>`)}
      </div>
      <span class="logr-label">${rangeText(cur.from, cur.to, lang)}</span>
      <span class="logr-count muted small">${count}</span>
      ${state.back.length ? html`<button type="button" class="logr-back" onClick=${back}>${w.back}</button>` : null}
      <span class="logr-spacer"></span>
      <label class="logr-step muted small">${w.barsPer}
        <select value=${state.step === 'auto' || step.key !== state.step ? 'auto' : step.key}
          onChange=${e => set(st => ({ ...st, step: e.currentTarget.value }))}>
          <option value="auto">${w.auto(w.step[auto.key])}</option>
          ${rangeSteps(cur.from, cur.to).map(st => html`<option key=${st.key} value=${st.key}>${w.step[st.key]}</option>`)}
        </select></label>
    </div>
    <${RangeChart} page=${page} cur=${cur} step=${step} series=${series} stacked=${stacked} now=${now}
      onPick=${(from, to) => { if (from !== cur.from || to !== cur.to) pick({ from, to }) }} />
    <div class="logr-foot muted small">
      ${stacked ? RANGE_KINDS.map(([k, color]) => html`<span class="logr-key" key=${k}><i style=${{ background: color }}></i>${w.kinds[k]}</span>`)
        : html`<span class="logr-key"><i style=${{ background: RANGE_KINDS[0][1] }}></i>${keyText}</span>`}
      <span>${w.hint}</span>
    </div>
  </section>`
}

/** The busiest contexts of some rows, three at most: `billing 3 · docs 1` */
function busiest(items) {
  const n = new Map()
  for (const it of items) if (it.group) n.set(it.group, (n.get(it.group) ?? 0) + 1)
  return [...n].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, 3).map(([k, v]) => `${k} ${v}`).join(' · ')
}

/** The bar chart: the bars of the range on the local calendar (stacked by kind for Every day), weekends shaded where
 *  the bars are a day or less, what has not happened yet hatched, the line of now, the axis; the pointer zooms */
function RangeChart({ page, cur, step, series, stacked, now, onPick }) {
  const w = T().logRange
  const lang = language()
  const box = useRef(null)
  const [width, setWidth] = useState(WIDTH)
  // the drag as drawn, and as the pointer handlers read it at once (two events can come before the next render)
  const [drag, setDragState] = useState(null)
  const dragNow = useRef(null)
  const setDrag = value => { dragNow.current = value; setDragState(value) }
  const [hover, setHover] = useState(null)
  useLayoutEffect(() => {
    const measure = () => { const cw = box.current?.clientWidth; if (cw > 0) setWidth(cw) }
    measure()
    if (typeof window === 'undefined' || !window.addEventListener) return undefined
    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  }, [])
  const edges = rangeEdges(cur.from, cur.to, step)
  const g = chartGeometry(edges, width, MARGIN)
  const ph = CHART_H - MARGIN.t - MARGIN.b
  const counts = series.map(sr => ({ kind: sr.kind, counts: rangeCounts(sr.items, edges) }))
  const totals = edges.slice(1).map((_, i) => counts.reduce((sum, sr) => sum + sr.counts[i], 0))
  const max = niceMax(Math.max(1, ...totals))
  const y = n => MARGIN.t + ph - n / max * ph
  const span = edges[edges.length - 1] - edges[0]
  const last = edges[edges.length - 1]
  const xOf = e => e.clientX - (box.current?.getBoundingClientRect?.().left ?? 0)
  const rowsOf = (i0, i1) => series.flatMap(sr => sr.items).filter(it => it.ts >= edges[i0] && it.ts < edges[i1 + 1])
  const sel = drag ? [g.barAt(Math.min(drag.x0, drag.x1)), g.barAt(Math.max(drag.x0, drag.x1))] : null
  const tip = sel ? { x: (drag.x0 + drag.x1) / 2, head: rangeText(edges[sel[0]], edges[sel[1] + 1], lang), n: rowsOf(sel[0], sel[1]).length }
    : hover !== null ? { x: hover.x, head: barText(edges[hover.i], edges[hover.i + 1], step, lang), n: totals[hover.i] ?? 0,
      ctx: busiest(rowsOf(hover.i, hover.i)) } : null
  const hatch = `logr-hatch-${page.id}`
  // weekends, behind the bars: where a bar is a day or less and the range spans days
  const weekends = []
  if (step.min <= 1440 && span >= 2 * 86400000 && span <= 45 * 86400000) {
    for (let d = dayStart(edges[0]); d < last; d = shiftDays(d, 1)) {
      const wd = new Date(d).getDay()
      if (wd === 0 || wd === 6) weekends.push([Math.max(d, edges[0]), Math.min(shiftDays(d, 1), last)])
    }
  }
  const bars = []
  for (let i = 0; i < edges.length - 1; i++) {
    let base = 0
    const x0 = g.x(edges[i]), x1 = g.x(edges[i + 1]), bw = x1 - x0, gap = Math.min(2, bw * 0.18)
    for (const sr of counts) {
      const n = sr.counts[i]
      if (!n) continue
      const kind = RANGE_KINDS.find(([k]) => k === sr.kind) ?? RANGE_KINDS[0]
      bars.push(html`<rect key=${`${i}-${sr.kind}`} class=${`logr-bar${hover?.i === i && !drag ? ' is-hover' : ''}`} data-i=${i} data-kind=${sr.kind} data-n=${n}
        x=${x0 + gap / 2} y=${y(base + n)} width=${Math.max(1, bw - gap)} height=${y(base) - y(base + n)} rx=${bw > 6 && !stacked ? 2 : 0}
        fill=${kind[1]} />`)
      base += n
    }
  }
  const ticks = rangeTicks(edges, width, lang)
  const nowX = now >= edges[0] && now <= last ? g.x(now) : null
  const up = e => {
    const d = dragNow.current
    if (!d) return
    const a = Math.min(d.x0, xOf(e)), b = Math.max(d.x0, xOf(e))
    setDrag(null)
    if (b - a < 5) {
      const i = g.barAt(a)
      if (step.min > 15 || edges.length > 2) onPick(edges[i], edges[i + 1])
      return
    }
    onPick(edges[g.barAt(a)], edges[g.barAt(b) + 1])
  }
  return html`<div class="logr-chart" ref=${box} data-edges=${edges.join(',')}
      onPointerDown=${e => { if (e.button !== 0) return; e.currentTarget.setPointerCapture?.(e.pointerId); const x = xOf(e); setHover(null); setDrag({ x0: x, x1: x }) }}
      onPointerMove=${e => { const x = xOf(e); if (dragNow.current) setDrag({ ...dragNow.current, x1: x }); else setHover({ i: g.barAt(x), x }) }}
      onPointerUp=${up}
      onPointerLeave=${() => { if (!dragNow.current) setHover(null) }}
      onPointerCancel=${() => setDrag(null)}>
    <svg viewBox=${`0 0 ${width} ${CHART_H}`} width="100%" height=${CHART_H} aria-hidden="true" focusable="false">
      <defs><pattern id=${hatch} width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
        <rect width="6" height="6" fill="var(--surface-raised)" /><line x1="0" y1="0" x2="0" y2="6" stroke="var(--border)" stroke-width="3" /></pattern></defs>
      ${weekends.map(([a, b]) => html`<rect key=${`w${a}`} class="logr-weekend" x=${g.x(a)} y=${MARGIN.t} width=${Math.max(0, g.x(b) - g.x(a))} height=${ph} />`)}
      ${now < last ? html`<rect class="logr-future" x=${g.x(Math.max(now, edges[0]))} y=${MARGIN.t} width=${Math.max(0, g.x(last) - g.x(Math.max(now, edges[0])))}
        height=${ph} fill=${`url(#${hatch})`} opacity="0.6" />` : null}
      ${[max, max / 2].map(v => html`<g key=${`g${v}`}><line class="logr-grid" x1=${MARGIN.l} x2=${g.right} y1=${y(v)} y2=${y(v)} />
        <text x=${MARGIN.l - 6} y=${y(v) + 4} text-anchor="end">${Number.isInteger(v) ? v : v.toFixed(1)}</text></g>`)}
      <line class="logr-axis" x1=${MARGIN.l} x2=${g.right} y1=${MARGIN.t + ph} y2=${MARGIN.t + ph} />
      <text x=${MARGIN.l - 6} y=${MARGIN.t + ph + 4} text-anchor="end">0</text>
      ${bars}
      ${nowX !== null ? html`<line class="logr-now" x1=${nowX} x2=${nowX} y1=${MARGIN.t} y2=${MARGIN.t + ph} />
        <text class="logr-nowtext" x=${nowX > g.right - 40 ? nowX - 4 : nowX + 4} y=${MARGIN.t + 9} text-anchor=${nowX > g.right - 40 ? 'end' : 'start'}>${w.now}</text>` : null}
      ${ticks.map(tk => {
        const x = g.x(tk.ms)
        if (x < MARGIN.l - 1 || x > g.right + 1) return null
        return html`<g key=${`t${tk.ms}`}><line class="logr-tick" x1=${x} x2=${x} y1=${MARGIN.t + ph} y2=${MARGIN.t + ph + 4} />
          <text class=${tk.mid ? 'is-mid' : ''} x=${Math.min(Math.max(x, MARGIN.l + 18), g.right - 18)} y=${CHART_H - 6} text-anchor="middle">${tk.label}</text></g>`
      })}
      ${sel ? html`<rect class="logr-sel" x=${g.x(edges[sel[0]])} y=${MARGIN.t} width=${g.x(edges[sel[1] + 1]) - g.x(edges[sel[0]])} height=${ph} />` : null}
    </svg>
    ${tip ? html`<div class="logr-tip" role="presentation" style=${{ left: `${Math.min(Math.max(tip.x, 90), width - 90)}px`, top: `${MARGIN.t}px` }}>
      ${tip.head}: <b>${tip.n}</b> ${w.linesWord(tip.n)}${tip.ctx ? html`<br /><span class="logr-tipctx">${tip.ctx}</span>` : null}</div>` : null}
  </div>`
}

/** The moment an entry of the other history stands at (noon without a time), for the bars */
export function eventTimes(events) {
  return (events ?? []).map(e => ({ ...e, ts: dayTime(e.date, e.time), group: e.source }))
}

