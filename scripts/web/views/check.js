// SPDX-License-Identifier: MIT
// The cockpit, the task check.
// The rules every component keeps stand at the head of components.js.

import { html, useRef } from '../vendor/htm-preact-3.1.1.module.js'
import {
  formatClock, formatDay, indexRows, isoDate, short, VERDICT_ORDER, centsText, confidenceDots, reviewRows,
  verdictCounts, verdictToken, checkFlow, runProgress, verdictSegments,
} from '../logic.js'
import { flash, flowAlpha, flowPoints, nowSec } from '../motion.js'
import { T, language } from '../text.js'
import { Segmented } from './detail.js'
import { KindTag, OriginTag, SettleMenu, StartMany } from './day.js'
import { Btn, CountNum, Dot, Empty, PrioChip, StateLine, useClock, useHits, useTween } from './parts.js'

// ---------------------------------------------------------------- task check

/** The drawn check (DESIGN.md form 3): tasks, the model tiers, the verdicts, as stations on one rail.
 *  The stations are the resting state; light points run on the first rail while a check runs, and a
 *  finished check sends one packet along the whole rail to the verdicts, which light up once */
function CheckFlow({ s }) {
  const t = T()
  const lang = language()
  const rv = s.model?.review ?? {}
  const flow = checkFlow(rv.last)
  const running = rv.running
  const arrivals = useHits(rv.last?.reviewed_at, (a, b) => !!b && !running)
  const arrivedAt = useRef(null)
  const seen = useRef(arrivals)
  if (arrivals !== seen.current) { seen.current = arrivals; arrivedAt.current = nowSec() }
  const since = arrivedAt.current == null ? Infinity : nowSec() - arrivedAt.current
  const now = useClock(!!running || since < 3)
  const dt = arrivedAt.current == null ? Infinity : now - arrivedAt.current
  const stations = flow ? [
    { id: 'tasks', label: t.flowTasks, n: flow.total, sub: flow.cached ? t.flowCached(flow.cached) : null },
    ...flow.tiers.map(x => ({ id: x.model, mono: true, label: x.model, n: x.answered,
      sub: `${t.flowAnswered} · ${x.cost_ct == null ? t.flowCostUnknown : t.reviewCost(centsText(x.cost_ct, lang), true)}`,
      exception: x.fromPrev })),
    { id: 'verdicts', label: t.flowVerdicts, n: flow.total, end: true,
      sub: (rv.keys ?? []).length < flow.total ? t.flowClosedSince(flow.total - (rv.keys ?? []).length) : null },
  ] : []
  const rails = Math.max(0, stations.length - 1)
  const STEP = 0.55
  const glow = flash(dt, [rails * STEP], 2.2)
  const prog = runProgress(running, Date.now(), rv.last?.duration_sec)
  const points = running ? flowPoints(now, 3) : []
  const railDots = i => {
    if (running) return i === 0 ? points.map(u => [u, flowAlpha(u)]) : []
    if (dt > rails * STEP + 0.4) return []
    const u = Math.min(1, Math.max(0, (dt - i * STEP) / STEP))
    return u > 0 && u < 1 ? [[u, flowAlpha(u)]] : []
  }
  if (!flow && !running) return null
  return html`<div class="flow-wrap">
    ${flow ? html`<ol class="flow" aria-label=${t.flowLabel}>
      ${stations.map((st, i) => html`
        ${i > 0 ? html`<li class=${`flow-rail${st.exception ? ' is-exception' : ''}`} aria-hidden=${st.exception ? undefined : 'true'} key=${`r${i}`}>
          <span class="flow-line"></span><span class="flow-arrow"></span>
          ${railDots(i - 1).map(([u, a], k) => html`<span class="flow-dot" key=${k} style=${{ '--u': u.toFixed(4), opacity: a.toFixed(3) }}></span>`)}
          ${st.exception ? html`<span class="flow-rail-label mono">${t.flowUnclear}</span>` : null}
        </li>` : null}
        <li class=${`flow-st${st.end ? ' is-end' : ''}`} key=${st.id}>
          ${st.end && glow > 0.01 ? html`<span class="flow-glow" aria-hidden="true" style=${{ opacity: glow.toFixed(3) }}></span>` : null}
          <span class=${`flow-st-label${st.mono ? ' mono' : ' label-caps'}`}>${st.label}</span>
          <${CountNum} value=${st.n} cls="flow-num" />
          ${st.sub ? html`<span class="muted small">${st.sub}</span>` : null}
          ${st.end && rv.last?.to_close ? html`<${StateLine} token="danger" strong word=${t.reviewToClose(rv.last.to_close)} />` : null}
        </li>`)}
    </ol>` : null}
    ${prog ? html`<div class="flow-progress">
      <span class="flow-track" aria-hidden="true"><span class="flow-fill" style=${{ transform: `scaleX(${prog.frac.toFixed(4)})` }}></span></span>
      <span class="muted small">${t.flowRunning(Math.round(prog.sec), Math.round(prog.expected))}${prog.over ? ` · ${t.flowOver}` : ''}</span>
    </div>` : null}
  </div>`
}

/** One verdict's share of the bar: grows from the left on the first show, glides when the counts change */
function VerdictSeg({ verdict, seg, onPick, title }) {
  const x = useTween(seg ? seg.x : 1, { start: 0 })
  const w = useTween(seg ? seg.w : 0, { start: 0 })
  if (w < 0.0005) return null
  return html`<span class=${`vbar-seg vs-${verdict}`} title=${title} onClick=${onPick}
    style=${{ transform: `translateX(${(x * 100).toFixed(3)}%) scaleX(${w.toFixed(5)})` }}></span>`
}

/** The verdicts as one bar in verdict order; the filter buttons below carry the words and the keyboard */
function VerdictBar({ counts, c }) {
  const t = T()
  const segs = verdictSegments(counts)
  if (!segs.length) return null
  return html`<div class="vbar" aria-hidden="true">${VERDICT_ORDER.map(v => {
    const seg = segs.find(x => x.verdict === v)
    return html`<${VerdictSeg} key=${v} verdict=${v} seg=${seg} title=${seg ? `${t.verdictName[v]} ${seg.n}` : ''}
      onPick=${() => c.setReview({ rvFilter: v })} />`
  })}</div>`
}

/** "Check tasks", or the caller's `label`; while a check runs it says so with the seconds, the server allows one at a time */
export function CheckButton({ s, c, size = 'sm', variant = 'secondary', label = null }) {
  const t = T()
  const running = s.model?.review?.running
  const sec = running ? Math.max(0, Math.round((s.now - running.started_ms) / 1000)) : 0
  return html`<${Btn} size=${size} variant=${variant} disabled=${!!running} busy=${!!s.ui.busy.task_review}
    onClick=${() => c.review()}>${running ? t.reviewing(sec) : label ?? t.btnReviewAll}<//>`
}

function reviewStripText(s) {
  const t = T()
  const last = s.model?.review?.last
  if (!last) return null
  const lang = language()
  const at = Date.parse(last.reviewed_at ?? '')
  const when = Number.isFinite(at) ? formatDay(isoDate(at), lang) + ' ' + formatClock(at, lang).slice(0, 5) : ''
  return t.reviewStrip(last.reviewed ?? 0, t.reviewCost(centsText(last.cost_ct, lang), last.cost_known),
    (last.models ?? []).join(', ') || '-', Math.round(last.duration_sec ?? 0), when)
}

/** On a page that lists tasks: the check in one line, and the way to its overview */
export function ReviewStrip({ s, c }) {
  const t = T()
  const rv = s.model?.review ?? {}
  const toClose = rv.last?.to_close ?? 0
  return html`<div class="panel panel-pad review-strip">
    <${CheckButton} s=${s} c=${c} size="xs" />
    ${rv.last ? html`<span class="muted small">${reviewStripText(s)}</span>` : html`<span class="muted small">${t.rvNoRun}</span>`}
    ${toClose ? html`<${StateLine} token="danger" strong word=${t.reviewToClose(toClose)} />` : null}
    ${rv.last ? html`<button type="button" class="btn-link" onClick=${() => c.openReview()}>${t.reviewOpen}</button>` : null}
  </div>`
}

/** In a task's detail: the recommendation with its reason and evidence, and what to do about it */
export function ReviewBlock({ row, s, c }) {
  const t = T()
  const rv = row.review
  const running = !!s.model?.review?.running
  const busy = !!s.ui.busy[row.key]
  const closer = s.model?.review?.last?.escalate_ct
  return html`<div class="sub-block review-block">
    <h4 class="sub-title">${t.reviewTitle}</h4>
    ${rv ? html`<div class="review-rec">
        <div class="review-head">
          <${StateLine} token=${verdictToken(rv.verdict)} strong word=${t.verdictName[rv.verdict] ?? rv.verdict} />
          <span class="muted small conf" title=${t.confidence[rv.confidence] ?? ''}>${confidenceDots(rv.confidence)} ${t.confidence[rv.confidence] ?? ''}</span>
          ${rv.model ? html`<span class="muted small mono">${String(rv.model).replace('claude-', '')}</span>` : null}
          ${rv.kept ? html`<span class="chip">${t.keptMark}</span>` : null}
          ${rv.changed && rv.previous_verdict ? html`<span class="chip chip-active">${t.changedMark(t.verdictName[rv.previous_verdict] ?? rv.previous_verdict)}</span>` : null}
        </div>
        ${rv.reason ? html`<p class="review-reason">${rv.reason}</p>` : null}
        ${(rv.closed_refs ?? []).length ? html`<p class="small"><${StateLine} token="success" word=${t.signalClosed(rv.closed_refs.join(', '))} /></p>` : null}
        ${(rv.chips ?? []).length ? html`<div class="chip-row">${rv.chips.map((ch, i) => html`<span class="chip" key=${i}>${t.chip(ch)}</span>`)}</div>` : null}
      </div>`
      : html`<p class="muted small">${t.reviewNone}</p>`}
    <div class="btn-row">
      ${rv && rv.verdict !== 'continue' && !rv.kept ? html`<${Btn} size="xs" variant="secondary" busy=${busy} disabled=${running}
        onClick=${() => c.keep([row.key])}>${t.btnKeep}<//>` : null}
      <${Btn} size="xs" variant="secondary" disabled=${running} busy=${busy} onClick=${() => c.review([row.key], false, !!rv)}>
        ${running ? t.reviewing(Math.max(0, Math.round((s.now - s.model.review.running.started_ms) / 1000))) : rv ? t.btnCheckAgain : t.btnCheckOne}<//>
      ${rv && closer != null && (rv.verdict === 'unclear' || rv.confidence === 'low') ? html`<${Btn} size="xs" variant="secondary" disabled=${running} busy=${busy}
        onClick=${() => c.review([row.key], true)}>${t.btnCheckCloser(t.reviewCost(centsText(closer, language()), true))}<//>` : null}
    </div>
  </div>`
}

/** The overview of the last check: filter per verdict, sort, select, act on many at once (reads only the last run) */
export function ReviewPage({ s, c }) {
  const t = T()
  return html`<div class="col col-page">
    <header class="page-head">
      <h2 class="detail-title">${t.reviewTitle}</h2>
      <${CheckButton} s=${s} c=${c} variant="primary" />
    </header>
    <${ReviewBody} s=${s} c=${c} />
  </div>`
}

/** The check itself: its run, the verdict filter and sort, what is picked, the table. Its own tab, or the
 *  tasks label of the page where inbox and tasks stand together (then with the run button on top), or the middle of
 *  Work through (views/flowleft.js CheckList: its own `intro`, the plain line in place of the model's, and `compact`:
 *  the verdicts first, how it ran folded into one line under the table) */
export function ReviewBody({ s, c, inline = false, intro = null, compact = false }) {
  const t = T()
  const byKey = indexRows(s.model)
  const rv = s.model?.review ?? {}
  const all = (rv.keys ?? []).map(k => byKey.get(k)).filter(r => r?.review)
  const counts = verdictCounts(all)
  const filter = s.ui.rvFilter in counts ? s.ui.rvFilter : 'all'
  const rows = reviewRows(all, filter, s.ui.rvSort)
  const picked = s.ui.rvPicked.filter(k => byKey.has(k))
  const pickedRows = picked.map(k => byKey.get(k))
  const running = !!rv.running
  const lang = language()
  const allShown = rows.length > 0 && rows.every(r => picked.includes(r.key))
  const filters = [['all', t.filterAll], ...VERDICT_ORDER.map(v => [v, t.verdictName[v]]), ['changed', t.filterChanged]]
    .filter(([id]) => id === 'all' || counts[id] > 0)
  return html`
    <div class="panel panel-pad review-top">
      ${inline ? html`<header class="psec-head"><h2 class="sec-title">${t.reviewTitle}</h2><${CheckButton} s=${s} c=${c} size="xs" /></header>` : null}
      ${intro ?? html`<p class="muted small">${t.reviewIntro}</p>`}
      ${compact ? null : html`<${CheckFlow} s=${s} />`}
      ${rv.last && !compact ? html`<p class="small">${reviewStripText(s)}${rv.last.mismatch ? html` · <${StateLine} token="warning" word=${t.reviewMismatch} />` : null}</p>` : null}
      ${compact && rv.running ? html`<${CheckFlow} s=${s} />` : null}
      ${rv.error ? html`<p><${StateLine} token="danger" strong word=${t.reviewFailedLine(rv.error)} /></p>` : null}
      ${all.length ? html`<${VerdictBar} counts=${counts} c=${c} /><div class="review-bar" role="group" aria-label=${t.rvCol.verdict}>
          ${filters.map(([id, label]) => html`<button key=${id} type="button" aria-pressed=${String(filter === id)}
            class=${`btn btn-xs ${filter === id ? 'btn-primary' : 'btn-secondary'}`} onClick=${() => c.setReview({ rvFilter: id })}>
            ${id !== 'all' && id !== 'changed' ? html`<${Dot} token=${verdictToken(id)} />` : null}
            <span class="btn-label">${label} <span class="mono">${counts[id]}</span></span></button>`)}
        </div>
        <${Segmented} label=${t.sortLabel} current=${s.ui.rvSort}
          values=${['verdict', 'priority', 'activity'].map(v => [v, t.sortBy[v]])} onPick=${v => c.setReview({ rvSort: v })} />` : null}
    </div>
    ${picked.length ? html`<div class="panel panel-pad review-bulk" role="toolbar" aria-label=${t.bulkLabel(picked.length)}>
      <${StartMany} rows=${pickedRows} s=${s} c=${c} />
      <${SettleMenu} rows=${pickedRows} s=${s} c=${c} />
      <${Btn} size="xs" variant="secondary" disabled=${running} busy=${!!s.ui.busy[picked.join(',')]} onClick=${() => c.keep(picked)}>${t.bulkKeep(picked.length)}<//>
      <${Btn} size="xs" variant="secondary" disabled=${running} onClick=${() => c.review(picked, true)}>
        ${t.bulkCloser(picked.length, t.reviewCost(centsText(rv.last?.escalate_ct, lang), rv.last?.escalate_ct != null))}<//>
      <button type="button" class="btn-link" onClick=${() => c.setReview({ rvPicked: [] })}>${t.bulkClear}</button>
    </div>` : null}
    <section class="panel panel-pad psec">
      ${!rv.last ? html`<${Empty}>${t.rvNoRun}<//>` : !rows.length ? html`<${Empty}>${t.rvEmpty}<//>` : html`<div class="table-wrap" tabindex="0" role="region" aria-label=${t.reviewTitle}>
        <table class="tbl tbl-review">
          <thead><tr>
            <th scope="col" class="c-pick"><input type="checkbox" checked=${allShown} aria-label=${t.selectAll}
              onChange=${() => c.setReview({ rvPicked: allShown ? picked.filter(k => !rows.some(r => r.key === k)) : [...new Set([...picked, ...rows.map(r => r.key)])] })} /></th>
            <th scope="col">${t.rvCol.task}</th><th scope="col">${t.rvCol.verdict}</th><th scope="col" class="c-quiet">${t.rvCol.quiet}</th>
            <th scope="col">${t.rvCol.evidence}</th><th scope="col">${t.rvCol.reason}</th>
          </tr></thead>
          <tbody>${rows.map((r, i) => html`<tr key=${r.key} class=${`row-in${r.review.kept ? ' is-kept' : ''}`} style=${{ '--i': Math.min(i, 12) }}>
            <td class="c-pick"><input type="checkbox" checked=${picked.includes(r.key)} aria-label=${t.rvPick(short(r.title, 40))}
              onChange=${() => c.toggleRvPick(r.key)} /></td>
            <td class="c-task"><button type="button" class="btn-link info-open" title=${t.openDetail} onClick=${e => c.peek(r.key, e.currentTarget, rows.map(x => ({ how: 'peek', key: x.key, title: x.title })))}>${short(r.title, 80)}</button>
              <span class="row-meta"><${KindTag} row=${r} s=${s} /><${OriginTag} row=${r} /><${PrioChip} priority=${r.priority} />${r.area ? html`<span class="meta-area">${r.area}</span>` : null}</span></td>
            <td class="c-verdict"><${StateLine} token=${verdictToken(r.review.verdict)} strong=${r.review.verdict === 'close'} word=${t.verdictName[r.review.verdict]} />
              <span class="muted small conf" title=${t.confidence[r.review.confidence] ?? ''}>${confidenceDots(r.review.confidence)}</span>
              ${r.review.kept ? html`<span class="chip">${t.keptMark}</span>` : null}
              ${r.review.changed && r.review.previous_verdict ? html`<span class="chip chip-active">${t.changedMark(t.verdictName[r.review.previous_verdict] ?? r.review.previous_verdict)}</span>` : null}</td>
            <td class="c-quiet mono">${t.rvDays(r.review.days_since_activity)}</td>
            <td><span class="chip-row">${(r.review.chips ?? []).map((ch, i) => html`<span class="chip" key=${i}>${t.chip(ch)}</span>`)}</span></td>
            <td class="c-reason">${r.review.reason}</td>
          </tr>`)}</tbody>
        </table>
      </div>`}
    </section>
    ${compact && rv.last ? html`<details class="panel panel-pad review-how">
      <summary class="small"><span class="label-caps">${t.flow.check.how}</span> ${reviewStripText(s)}${rv.last.mismatch ? html` · <${StateLine} token="warning" word=${t.reviewMismatch} />` : null}</summary>
      <${CheckFlow} s=${s} />
    </details>` : null}`
}
