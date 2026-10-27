// SPDX-License-Identifier: MIT
// The cockpit, the overview of Work through (views/flow.js): what the middle shows on entering a theme or area, and at
// the level of all of them. Every point as a row of a table, grouped as the left column groups them (Needs you, In
// progress, Tasks, Reports), with a box, its title (a click opens the point), its stage, its area and a suggestion
// with half a sentence of why (logic.js flowSuggestion: the day's triage first, else what the themes run said in its
// one call); a line over the table names where the suggestions come from. On top, sticky, the batch bar: All, Tick the
// suggestions (the rows whose suggestion is done, drop or later, never Let AI do it), how many are ticked and what
// their suggestions would do, Run the suggestions, and for all ticked the same Done, Later until or Drop because (one
// reason for all). The boxes are one selection with the left column's (ui.flowPicked). A batch plans what goes
// (logic.js batchPlan), says itself in one line with Confirm, and only then does anything go out (app.js flowBatch,
// each call quiet, one toast); afterwards Undo the batch, once, takes every point back. Let AI do it in a batch starts
// a point only with its own sentence and while fewer than cockpit.flow.max_running run; the rest stays out, and the
// line says how many.
// For the mouse: no text names a key.
// The rules every component keeps stand at the head of components.js.

import { html, useState } from '../vendor/htm-preact-3.1.1.module.js'
import { batchPlan, batchPreselect, batchSummary, DAY, dropReasonWord, flowDrive, flowSettings, flowSuggestion, FLOW_BANDS, FLOW_YOU,
  formatDay, isoDate, nextMonday, pointBand, rowProject, short, stageTone } from '../logic.js'
import { T, TABLES, language } from '../text.js'
import { KindTag } from './day.js'
import { Btn, Dot } from './parts.js'

/** The rows of a list: one per point with a row, a reports card by each of its reports; a tab alone has no row to
 *  decide on and stands without a box. Each {id, row, x} */
export function listRows(points) {
  return points.flatMap(x => (x.kind === 'reports' ? x.rows.map(r => ({ id: r.key, row: r, x })) : [{ id: x.row?.key ?? x.id, row: x.row ?? null, x }]))
}

/** A point's dot: what it is and where it stands, as the agent tabs show theirs */
export function pointTone(x, s) {
  if (x.group === 'doing') {
    const d = flowDrive(x, s)
    return { token: d.by === 'none' ? 'muted' : stageTone(d.stage === 'needs-you' ? 'asks' : d.stage ?? 'working'), pulse: d.stage === 'working' }
  }
  if (FLOW_YOU.includes(x.group)) return { token: x.group === 'result' ? 'success' : x.group === 'lost' ? 'danger' : 'warning', pulse: x.group === 'asks' }
  return { token: x.group === 'reports' ? 'muted' : 'info', pulse: false }
}

/** The rows of a side grouped by band, in FLOW_BANDS order: [{band, rows}], each row {id, row, x} (listRows) */
export function bandsOf(points) {
  const rows = listRows(points)
  return FLOW_BANDS.map(band => ({ band, rows: rows.filter(r => pointBand(r.x) === band) })).filter(b => b.rows.length)
}

/** The area of a row of the list: its row's project, else the workspace of its tab */
export const rowArea = r => (r.row ? rowProject(r.row) : r.x.tab?.workspace ?? '')

/** How old a row is in days: an inbox id starts with its day, a task names when it was made or last moved */
function ageDays(row, nowMs) {
  const id = String(row?.inbox_id ?? '')
  const day = /^\d{8}/.test(id) ? `${id.slice(0, 4)}-${id.slice(4, 6)}-${id.slice(6, 8)}` : String(row?.created ?? row?.updated ?? '').slice(0, 10)
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return null
  const then = new Date(`${day}T00:00:00`).getTime()
  return Math.max(0, Math.round((new Date(`${isoDate(nowMs)}T00:00:00`).getTime() - then) / DAY))
}

/** A suggestion as a chip: its verb (Later with its day), its half sentence, where it comes from on hover; the
 *  overview's table and the open point (views/flow.js PointAdvice) draw it alike */
export function Suggestion({ sug, s }) {
  const f = T().flow.list
  const lang = language()
  if (!sug) return html`<span class="muted small">${f.none}</span>`
  const from = sug.from === 'triage' ? f.from.triage(formatDay(String(sug.at ?? '').slice(0, 10), lang)) : f.from.themes
  const word = sug.verb === 'later' && sug.until ? f.laterUntil(formatDay(sug.until, lang)) : f.verb[sug.verb]
  const why = sug.verb === 'drop' && sug.drop ? dropReasonWord(sug.drop, lang) : sug.reason
  return html`<span class=${`flow-sug flow-sug-${sug.verb}`} title=${from}>
    <span class="flow-sug-verb">${word}</span>${why ? html`<span class="flow-sug-why">${short(why, 90)}</span>` : null}</span>`
}

export function FlowOverview({ points, picked, titleFor, kindFor, s, c }) {
  const t = T()
  const f = t.flow
  const w = f.list
  const lang = language()
  const nowMs = s.now || Date.now()
  const bands = bandsOf(points)
  const rows = bands.flatMap(b => b.rows)
  const pickable = rows.filter(r => r.row)
  const [panel, setPanel] = useState(null)       // later or drop: the batch buttons that open a choice
  const [plan, setPlan] = useState(null)         // the plan waiting for Confirm
  const [other, setOther] = useState('')
  const chosen = pickable.filter(r => picked.has(r.id)).map(r => r.row)
  const all = pickable.length > 0 && chosen.length === pickable.length
  const pre = batchPreselect(pickable.map(r => r.row), s)
  const suggested = batchPlan(chosen, 'suggested', s, '', lang)
  const counts = (TABLES[lang] ?? TABLES.en).flow.batch.counts(suggested)
  const ask = (how, value = '') => { setPanel(null); setPlan(batchPlan(chosen, how, s, value, lang)) }
  const confirm = async () => {
    const calls = plan?.calls ?? []
    setPlan(null)
    c.flowPick(chosen.map(r => r.key), false)
    await c.flowBatch(calls)
  }
  const done = s.ui.flowBatch
  const from = new Set(rows.map(r => flowSuggestion(r.row, s)?.from).filter(Boolean))
  const day = s.triage?.last?.at ? formatDay(String(s.triage.last.at).slice(0, 10), lang) : null
  const reasons = flowSettings(s).drop_reasons
  if (!rows.length) return html`<section class="flow-overview" aria-label=${w.label}><p class="muted">${w.empty}</p></section>`
  return html`<section class="flow-overview" aria-label=${w.label}>
    <div class="flow-ov-top">
      <div class="flow-ov-bar" role="toolbar" aria-label=${w.label}>
        <label class="flow-check"><input type="checkbox" class="flow-ov-all" checked=${all} onClick=${() => c.flowPick(pickable.map(r => r.id), !all)} />
          <span>${w.pickAll}</span></label>
        <${Btn} size="sm" variant="secondary" icon="spark" disabled=${!pre.length} onClick=${() => c.flowPick(pre, true)}>${w.tick(pre.length)}<//>
        <span class="flow-ov-sum muted small" role="status">${chosen.length ? w.ticked(chosen.length, counts) : w.nothing}</span>
        <span class="flow-ov-verbs">
          <${Btn} size="sm" variant="primary" disabled=${!suggested.calls.length} onClick=${() => ask('suggested')}>${w.run}<//>
          <${Btn} size="sm" variant="secondary" disabled=${!chosen.length} onClick=${() => ask('done')}>${f.verbs.done}<//>
          <${Btn} size="sm" variant="secondary" disabled=${!chosen.length} pressed=${panel === 'later'} onClick=${() => setPanel(panel === 'later' ? null : 'later')}>${f.verbs.later} ▾<//>
          <${Btn} size="sm" variant="secondary" disabled=${!chosen.length} pressed=${panel === 'drop'} onClick=${() => setPanel(panel === 'drop' ? null : 'drop')}>${f.verbs.drop} ▾<//>
        </span>
      </div>
      ${panel === 'later' ? html`<div class="verbbar-panel verbbar-acts" role="group" aria-label=${f.later.label}>
        <${Btn} size="sm" variant="secondary" onClick=${() => ask('later', isoDate(nowMs + DAY))}>${f.later.tomorrow}<//>
        <${Btn} size="sm" variant="secondary" onClick=${() => ask('later', isoDate(nextMonday(nowMs)))}>${f.later.monday}<//>
        <${Btn} size="sm" variant="secondary" onClick=${() => ask('later', isoDate(nowMs + 7 * DAY))}>${f.later.week}<//>
      </div>` : null}
      ${panel === 'drop' ? html`<div class="verbbar-panel" role="group" aria-label=${f.drop.label}>
        <div class="verbbar-acts">${reasons.map(x => html`<${Btn} key=${x} size="sm" variant="secondary" onClick=${() => ask('drop', dropReasonWord(x, lang))}>${dropReasonWord(x, lang)}<//>`)}</div>
        <span class="field-row"><input class="input" type="text" maxlength="200" aria-label=${f.drop.other} placeholder=${f.drop.other} value=${other}
          onInput=${e => setOther(e.currentTarget.value)} />
          <${Btn} size="sm" variant="primary" disabled=${!other.trim()} onClick=${() => ask('drop', other.trim())}>${f.drop.send}<//></span>
      </div>` : null}
      ${plan ? html`<div class="flow-list-confirm" role="alert">
        <span>${batchSummary(plan, lang)}</span>
        <${Btn} size="sm" variant="primary" disabled=${!plan.calls.length} onClick=${confirm}>${w.confirm}<//>
        <${Btn} size="sm" variant="ghost" onClick=${() => setPlan(null)}>${w.cancel}<//>
      </div>` : null}
      ${done && !done.running && done.n ? html`<div class="flow-list-done" role="status"><span>${w.ran(done.n)}</span>
        ${done.undo?.length ? html`<${Btn} size="sm" variant="secondary" icon="back" onClick=${() => c.flowBatchUndo()}>${w.undo}<//>` : null}</div>` : null}
    </div>
    <p class="flow-list-from muted small">${[from.has('triage') && day ? w.from.triage(day) : null, from.has('themes') ? w.from.themes : null, w.honest]
      .filter(Boolean).join(' · ')}</p>
    <table class="flow-ov-table">
      <thead><tr><th class="flow-ov-pickcol"><span class="sr-only">${w.pickAll}</span></th><th>${w.cols.point}</th><th>${w.cols.stage}</th>
        <th>${w.cols.area}</th><th>${w.cols.suggestion}</th></tr></thead>
      <tbody>${bands.map(b => html`<tr key=${`band-${b.band}`} class="flow-ov-group"><th colspan="5" scope="colgroup"><span class="label-caps">${f.groups[b.band]}</span></th></tr>
        ${b.rows.map(r => {
          const row = r.row
          const title = row?.title ?? titleFor(r.x)
          const age = row ? ageDays(row, nowMs) : null
          const area = rowArea(r)
          const tone = pointTone(r.x, s)
          return html`<tr key=${r.id} class=${`flow-ov-row${row && picked.has(r.id) ? ' is-picked' : ''}`}>
            <td>${row ? html`<input type="checkbox" class="flow-ov-pick" aria-label=${w.pick(short(title, 60))} checked=${picked.has(r.id)}
              onClick=${() => c.flowPick([r.id], !picked.has(r.id))} />` : null}</td>
            <td class="flow-ov-point"><button type="button" class="flow-ov-open" onClick=${() => c.flowGo(r.x.id, points.indexOf(r.x))}>${short(title, 120)}</button>
              ${row ? html`<span class="flow-ov-sub muted small"><${KindTag} row=${row} s=${s} />${age == null ? '' : html` <span class="mono">${w.age(age)}</span>`}</span>` : null}</td>
            <td class="flow-ov-stage small"><${Dot} token=${tone.token} pulse=${tone.pulse} /> ${kindFor(r.x)}</td>
            <td class="flow-ov-area small">${area}</td>
            <td class="flow-ov-sug">${row ? html`<${Suggestion} sug=${flowSuggestion(row, s)} s=${s} />` : null}</td>
          </tr>`
        })}`)}</tbody>
    </table>
  </section>`
}
