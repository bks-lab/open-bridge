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
// line says how many. Since round 4 the bar is one part (BatchBar) the lists of Not now take as well, with their own
// verbs, and with Merge where two or more ticked rows are open tasks (MergePanel: which one stays, the one with more
// activity suggested); a square of Prio lists its points in Jev's order as one band.
// For the mouse: no text names a key.
// The rules every component keeps stand at the head of components.js.

import { html, useEffect, useState } from '../vendor/htm-preact-3.1.1.module.js'
import { activityWhen, batchPlan, batchPreselect, batchSummary, DAY, dropReasonWord, flowDrive, flowSettings, flowSuggestion, FLOW_BANDS, FLOW_YOU,
  formatDay, isoDate, jevWhy, mergeable, mergeKeep, nextMonday, pointBand, rowProject, short, stageTone } from '../logic.js'
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

/** The rows of a side grouped by band, in FLOW_BANDS order: [{band, rows}], each row {id, row, x} (listRows). `one`
 *  puts every row in one band of that name in the order given (Prio: a square by Jev's rank, the unrated by due) */
export function bandsOf(points, one = null) {
  const rows = listRows(points)
  if (one) return rows.length ? [{ band: one, rows }] : []
  return FLOW_BANDS.map(band => ({ band, rows: rows.filter(r => pointBand(r.x) === band) })).filter(b => b.rows.length)
}

/** The area of a row of the list: its row's project, else the workspace of its tab */
export const rowArea = r => (r.row ? rowProject(r.row) : r.x?.tab?.workspace ?? '')

/** How old a row is in days: an inbox id starts with its day, a task names when it was made or last moved */
export function ageDays(row, nowMs) {
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
  const day = at => formatDay(typeof at === 'number' ? isoDate(at) : String(at ?? '').slice(0, 10), lang)
  const from = sug.from === 'triage' ? f.from.triage(day(sug.at)) : sug.from === 'jev' ? f.from.jev(day(sug.at)) : f.from.themes
  const word = sug.verb === 'later' && sug.until ? f.laterUntil(formatDay(sug.until, lang)) : f.verb[sug.verb]
  const why = sug.verb === 'drop' && sug.drop && sug.from !== 'jev' ? dropReasonWord(sug.drop, lang) : sug.reason || jevWhy(sug, lang)
  return html`<span class=${`flow-sug flow-sug-${sug.verb}`} title=${from}>
    <span class="flow-sug-verb">${word}</span>${why ? html`<span class="flow-sug-why">${short(why, 90)}</span>` : null}</span>`
}

// the most feeds the merge panel reads for its counts of activity (the loader of the Activity tab)
const MERGE_FEEDS = 10

/** Merge, under the batch bar: which of the ticked tasks stays (a radio each with its activity and when it last moved,
 *  the one with more activity suggested once the feeds came; a pick of the person's holds), what happens to the
 *  others, Merge and Cancel. The merge goes out as one batch with one undo (app.js flowMerge); as Confirm does, it
 *  unticks the rows it took first (`onPick`), so an undo brings them back unticked */
export function MergePanel({ rows, s, c, onClose, onPick = () => {}, from = 'overview' }) {
  const t = T()
  const f = t.flow.merge
  const lang = language()
  const list = mergeable(rows)
  const keys = list.map(r => r.key)
  const [pick, setPick] = useState(null)
  useEffect(() => { for (const k of keys.slice(0, MERGE_FEEDS)) c.loadActivity(k) }, [keys.join(',')])
  const feeds = Object.fromEntries(keys.map(k => [k, s.details?.activity?.[k]?.data ?? null]))
  const ready = keys.slice(0, MERGE_FEEDS).every(k => feeds[k])
  const keep = keys.includes(pick) ? pick : ready ? mergeKeep(list, feeds) : keys[0]
  const kept = list.find(r => r.key === keep)
  const others = keys.filter(k => k !== keep)
  const run = async () => {
    onClose()
    onPick(keys, false)
    await c.flowMerge(keep, others, from)
  }
  return html`<div class="verbbar-panel flow-merge" role="group" aria-labelledby="flow-merge-h">
    <p id="flow-merge-h" class="label-caps">${f.title}</p>
    ${ready ? html`<p class="muted small">${f.proposal}</p>` : null}
    <ul class="flow-merge-list">${list.map(r => {
      const feed = feeds[r.key]
      const moved = feed?.facts?.moved ?? r.updated ?? null
      return html`<li key=${r.key}><label class="flow-check">
        <input type="radio" name="flow-merge-keep" value=${r.key} checked=${r.key === keep} onClick=${() => setPick(r.key)} />
        <span class="flow-merge-title">${short(r.title ?? r.key, 90)}</span>
        <span class="muted small">${[feed ? f.activity(Number(feed.counts?.all) || 0) : null, moved ? `${t.flow.fields.moved} ${activityWhen(moved, lang)}` : null]
          .filter(Boolean).join(' · ')}</span>
      </label></li>`
    })}</ul>
    <p class="small">${f.explain(kept?.title ?? keep, others.length)}</p>
    <div class="verbbar-acts">
      <${Btn} size="sm" variant="primary" disabled=${!others.length} busy=${!!s.ui.busy?.[others.join(',')]} onClick=${run}>${f.run}<//>
      <${Btn} size="sm" variant="ghost" onClick=${onClose}>${t.flow.list.cancel}<//>
    </div>
  </div>`
}

/** The batch bar of a list: All, Tick the suggestions (the overview's), how many are ticked, the verbs of the list
 *  (`verbs`: suggested, back, do, done, later, drop), Merge where two or more ticked rows are open tasks (enabled only
 *  when every ticked row is one), the line to confirm, then the batch's one undo. `planOf(how, value)` plans what goes
 *  (logic.js batchPlan or leftPlan), `onRun(plan)` sends it; nothing goes out before Confirm */
export function BatchBar({ pickable, chosen, onPick, verbs, planOf, onRun, suggest = false, from = 'overview', s, c }) {
  const t = T()
  const f = t.flow
  const w = f.list
  const lang = language()
  const nowMs = s.now || Date.now()
  const [panel, setPanel] = useState(null)       // later, drop or merge: the batch buttons that open a choice
  const [plan, setPlan] = useState(null)         // the plan waiting for Confirm
  const [other, setOther] = useState('')
  const all = pickable.length > 0 && chosen.length === pickable.length
  const pre = suggest ? batchPreselect(pickable.map(r => r.row), s) : []
  const suggested = suggest ? batchPlan(chosen, 'suggested', s, '', lang) : null
  const counts = suggested ? (TABLES[lang] ?? TABLES.en).flow.batch.counts(suggested) : null
  const ask = (how, value = '') => { setPanel(null); setPlan(planOf(how, value)) }
  const confirm = async () => {
    const p = plan
    setPlan(null)
    onPick(chosen.map(r => r.key), false)
    await onRun(p)
  }
  // the bar's own batch; one of the instruction line says itself under that line, never twice
  const done = (s.ui.flowBatch?.from ?? 'overview') === from ? s.ui.flowBatch : null
  const reasons = flowSettings(s).drop_reasons
  const merging = mergeable(chosen)
  const canMerge = merging.length >= 2 && merging.length === chosen.length
  const verb = v => {
    const off = !chosen.length
    if (v === 'suggested') return html`<${Btn} key=${v} size="sm" variant="primary" disabled=${!suggested?.calls.length} onClick=${() => ask('suggested')}>${w.run}<//>`
    if (v === 'later' || v === 'drop') {
      const word = v === 'later' ? f.verbs.later : f.verbs.drop
      return html`<${Btn} key=${v} size="sm" variant="secondary" disabled=${off} pressed=${panel === v} onClick=${() => setPanel(panel === v ? null : v)}>${word} ▾<//>`
    }
    const word = v === 'back' ? f.notnow.back : v === 'do' ? f.verbs.do : f.verbs.done
    return html`<${Btn} key=${v} size="sm" variant="secondary" disabled=${off} onClick=${() => ask(v)}>${word}<//>`
  }
  return html`<div class="flow-ov-top">
    <div class="flow-ov-bar" role="toolbar" aria-label=${w.label}>
      <label class="flow-check"><input type="checkbox" class="flow-ov-all" checked=${all} disabled=${!pickable.length}
        onClick=${() => onPick(pickable.map(r => r.id), !all)} /><span>${w.pickAll}</span></label>
      ${suggest ? html`<${Btn} size="sm" variant="secondary" icon="spark" disabled=${!pre.length} onClick=${() => onPick(pre, true)}>${w.tick(pre.length)}<//>` : null}
      <span class="flow-ov-sum muted small" role="status">${chosen.length ? w.ticked(chosen.length, counts) : w.nothing}</span>
      <span class="flow-ov-verbs">
        ${verbs.map(verb)}
        ${merging.length >= 2 ? html`<${Btn} size="sm" variant="secondary" disabled=${!canMerge} pressed=${panel === 'merge'} title=${canMerge ? undefined : f.merge.only}
          onClick=${() => setPanel(panel === 'merge' ? null : 'merge')}>${f.merge.button} ▾<//>` : null}
      </span>
    </div>
    ${merging.length >= 2 && !canMerge ? html`<p class="muted small flow-merge-only">${f.merge.only}</p>` : null}
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
    ${panel === 'merge' && canMerge ? html`<${MergePanel} rows=${chosen} s=${s} c=${c} from=${from} onClose=${() => setPanel(null)} onPick=${onPick} />` : null}
    ${plan ? html`<div class="flow-list-confirm" role="alert">
      <span>${batchSummary(plan, lang)}</span>
      <${Btn} size="sm" variant="primary" disabled=${!plan.calls.length && !plan.early?.length} onClick=${confirm}>${w.confirm}<//>
      <${Btn} size="sm" variant="ghost" onClick=${() => setPlan(null)}>${w.cancel}<//>
    </div>` : null}
    ${done && !done.running && done.n ? html`<div class="flow-list-done" role="status"><span>${w.ran(done.n)}</span>
      ${done.undo?.length ? html`<${Btn} size="sm" variant="secondary" icon="back" onClick=${() => c.flowBatchUndo()}>${w.undo}<//>` : null}</div>` : null}
  </div>`
}

export function FlowOverview({ points, picked, titleFor, kindFor, band = null, s, c }) {
  const t = T()
  const f = t.flow
  const w = f.list
  const lang = language()
  const nowMs = s.now || Date.now()
  const bands = bandsOf(points, band)
  const rows = bands.flatMap(b => b.rows)
  const pickable = rows.filter(r => r.row)
  const chosen = pickable.filter(r => picked.has(r.id)).map(r => r.row)
  const from = new Set(rows.map(r => flowSuggestion(r.row, s)?.from).filter(Boolean))
  const day = s.triage?.last?.at ? formatDay(String(s.triage.last.at).slice(0, 10), lang) : null
  if (!rows.length) return html`<section class="flow-overview" aria-label=${w.label}><p class="muted">${w.empty}</p></section>`
  return html`<section class="flow-overview" aria-label=${w.label}>
    <${BatchBar} pickable=${pickable} chosen=${chosen} onPick=${(keys, on) => c.flowPick(keys, on)} verbs=${['suggested', 'done', 'later', 'drop']}
      planOf=${(how, value) => batchPlan(chosen, how, s, value, lang)} onRun=${plan => c.flowBatch(plan?.calls ?? [])} suggest s=${s} c=${c} />
    <p class="flow-list-from muted small">${[from.has('triage') && day ? w.from.triage(day) : null, from.has('themes') ? w.from.themes : null,
      from.has('jev') ? w.from.jev(formatDay(isoDate(nowMs), lang)) : null, w.honest].filter(Boolean).join(' · ')}</p>
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
