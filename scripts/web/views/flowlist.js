// SPDX-License-Identifier: MIT
// The cockpit, the List of Work through (views/flow.js, Focus or List over the tabs): every point of the theme or area
// picked as a row with a box to pick it, its kind, stage, area and age, and a suggestion with half a sentence of why
// (logic.js flowSuggestion: the day's triage first, else what the themes run said in its one call), each naming where
// it comes from. Take the suggestions picks the rows whose suggestion is done, drop or later (never Let AI do it);
// the boxes and All pick by hand. The batch buttons Done, Later until and Drop because (one reason for all) or Take
// the suggestions plan what goes (logic.js batchPlan), the plan says itself in one line with Confirm, and only then
// does anything go out (app.js flowBatch, each call quiet, one note with one undo for all). Afterwards Undo the batch
// takes every point back. Let AI do it in a batch starts a point only with its own sentence and while fewer than
// cockpit.flow.max_running run; the rest stays out, and the line says how many.
// For the mouse: no text names a key.
// The rules every component keeps stand at the head of components.js.

import { html, useState } from '../vendor/htm-preact-3.1.1.module.js'
import { batchPlan, batchPreselect, batchSummary, DAY, dropReasonWord, flowSettings, flowSuggestion, formatDay, isoDate, nextMonday,
  projectTone, rowProject, short } from '../logic.js'
import { T, language } from '../text.js'
import { KindTag } from './day.js'
import { Btn } from './parts.js'

/** The rows of the list: one per point with a row, a reports card by each of its reports; a tab alone has no row to
 *  decide on and stands without a box */
export function listRows(points) {
  return points.flatMap(x => (x.kind === 'reports' ? x.rows.map(r => ({ id: r.key, row: r, x })) : [{ id: x.row?.key ?? x.id, row: x.row ?? null, x }]))
}

/** How old a row is in days: an inbox id starts with its day, a task names when it was made or last moved */
function ageDays(row, nowMs) {
  const id = String(row?.inbox_id ?? '')
  const day = /^\d{8}/.test(id) ? `${id.slice(0, 4)}-${id.slice(4, 6)}-${id.slice(6, 8)}` : String(row?.created ?? row?.updated ?? '').slice(0, 10)
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return null
  const then = new Date(`${day}T00:00:00`).getTime()
  return Math.max(0, Math.round((new Date(`${isoDate(nowMs)}T00:00:00`).getTime() - then) / DAY))
}

/** A suggestion as a chip: its verb (Later with its day), its half sentence, where it comes from on hover */
function Suggestion({ sug, s }) {
  const f = T().flow.list
  const lang = language()
  if (!sug) return html`<span class="muted small">${f.none}</span>`
  const from = sug.from === 'triage' ? f.from.triage(formatDay(String(sug.at ?? '').slice(0, 10), lang)) : f.from.themes
  const word = sug.verb === 'later' && sug.until ? f.laterUntil(formatDay(sug.until, lang)) : f.verb[sug.verb]
  const why = sug.verb === 'drop' && sug.drop ? dropReasonWord(sug.drop, lang) : sug.reason
  return html`<span class=${`flow-sug flow-sug-${sug.verb}`} title=${from}>
    <span class="flow-sug-verb">${word}</span>${why ? html`<span class="flow-sug-why">${short(why, 90)}</span>` : null}</span>`
}

export function FlowList({ points, s, c, titleFor = null }) {
  const t = T()
  const f = t.flow
  const w = f.list
  const lang = language()
  const nowMs = s.now || Date.now()
  const rows = listRows(points)
  const pickable = rows.filter(r => r.row)
  const [picked, setPicked] = useState(() => new Set())
  const [panel, setPanel] = useState(null)       // later or drop: the batch buttons that open a choice
  const [plan, setPlan] = useState(null)         // the plan waiting for Confirm
  const [other, setOther] = useState('')
  const keys = new Set(pickable.map(r => r.id))
  const chosen = pickable.filter(r => picked.has(r.id) && keys.has(r.id)).map(r => r.row)
  const all = pickable.length > 0 && chosen.length === pickable.length
  const pick = id => setPicked(p => { const n = new Set(p); if (n.has(id)) n.delete(id); else n.add(id); return n })
  const ask = (how, value = '') => { setPanel(null); setPlan(batchPlan(chosen, how, s, value, lang)) }
  const take = () => {
    const pre = batchPreselect(pickable.map(r => r.row), s)
    // what the person picked besides (a start, say) stays picked: Take adds, it never takes a pick away
    const next = new Set([...picked].filter(k => keys.has(k)))
    for (const k of pre) next.add(k)
    setPicked(next)
    setPlan(batchPlan(pickable.filter(r => next.has(r.id)).map(r => r.row), 'suggested', s, '', lang))
  }
  const confirm = async () => {
    const calls = plan?.calls ?? []
    setPlan(null)
    setPicked(new Set())
    await c.flowBatch(calls)
  }
  const done = s.ui.flowBatch
  const from = new Set(rows.map(r => flowSuggestion(r.row, s)?.from).filter(Boolean))
  const day = s.triage?.last?.at ? formatDay(String(s.triage.last.at).slice(0, 10), lang) : null
  const reasons = flowSettings(s).drop_reasons
  if (!rows.length) return html`<section class="flow-list" aria-label=${w.label}><p class="muted">${w.empty}</p></section>`
  return html`<section class="flow-list" aria-label=${w.label}>
    <div class="flow-list-bar" role="toolbar" aria-label=${w.label}>
      <label class="flow-check"><input type="checkbox" checked=${all} onChange=${() => setPicked(all ? new Set() : new Set(pickable.map(r => r.id)))} />
        <span>${w.pickAll}</span></label>
      <${Btn} size="sm" variant="primary" icon="spark" onClick=${take}>${w.take}<//>
      <span class="muted small">${w.picked(chosen.length)}</span>
      <span class="flow-list-verbs">
        <${Btn} size="sm" variant="secondary" disabled=${!chosen.length} onClick=${() => ask('done')}>${f.verbs.done}<//>
        <${Btn} size="sm" variant="secondary" disabled=${!chosen.length} pressed=${panel === 'later'} onClick=${() => setPanel(panel === 'later' ? null : 'later')}>${w.later} ▾<//>
        <${Btn} size="sm" variant="secondary" disabled=${!chosen.length} pressed=${panel === 'drop'} onClick=${() => setPanel(panel === 'drop' ? null : 'drop')}>${w.drop} ▾<//>
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
    <p class="flow-list-from muted small">${[from.has('triage') && day ? w.from.triage(day) : null, from.has('themes') ? w.from.themes : null, w.honest]
      .filter(Boolean).join(' · ')}</p>
    <ul class="flow-rows">${rows.map(r => {
      const row = r.row
      const sug = row ? flowSuggestion(row, s) : null
      const age = row ? ageDays(row, nowMs) : null
      const area = row ? rowProject(row) : r.x.tab?.workspace ?? ''
      const title = row?.title ?? (titleFor ? titleFor(r.x) : r.x.tab?.name) ?? ''
      return html`<li key=${r.id} class=${`flow-row${row && picked.has(r.id) ? ' is-picked' : ''}`}>
        ${row ? html`<input type="checkbox" class="flow-row-pick" aria-label=${w.pick(short(title, 60))} checked=${picked.has(r.id)} onChange=${() => pick(r.id)} />`
          : html`<span class="flow-row-pick" aria-hidden="true"></span>`}
        <span class="flow-row-title">${short(title, 100)}</span>
        <span class="flow-row-kind">${row ? html`<${KindTag} row=${row} s=${s} />` : null}</span>
        <span class="flow-row-stage muted small">${f.kind[r.x.stage === 'idle' ? 'idle' : r.x.group]}</span>
        <span class="flow-row-area small">${area ? html`<span class=${`home-area-dot tk-${projectTone(area)}`} aria-hidden="true"></span>${area}` : null}</span>
        <span class="flow-row-age mono muted small">${age == null ? '' : w.age(age)}</span>
        <span class="flow-row-sug">${row ? html`<${Suggestion} sug=${sug} s=${s} />` : null}</span>
      </li>`
    })}</ul>
  </section>`
}
