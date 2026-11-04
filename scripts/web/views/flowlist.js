// SPDX-License-Identifier: MIT
// The cockpit, the overview of Work through (views/flow.js): what the middle shows on entering a theme or area, and at
// the level of all of them. Every point as a row of a table, in bands by who takes the next step (stage 4, logic.js
// pointBand: Check-in, Needs you, The Bridge does), with a box, its name (logic.js pointName; a click opens the point),
// where it stands muted under it (pointStand, else its kind and, for a task nobody works on, when it last moved) and
// its next step with who takes it as a chip and the day it asks again or is due (pointStep). The walk bar of an open
// point goes the order of the table (walkOrder). Nothing ticked, one hint line says ticking shows the batch buttons and
// offers Tick the suggestions (the rows whose suggestion is done, drop or later, never Let AI do it); once a row is
// ticked, sticky, the batch bar: All, how many are ticked and what their suggestions would do, Run the suggestions,
// and for all ticked the same Done, In progress (with whom, until when), Later until or Drop because (one reason for
// all). Each band has a box of its own over its rows. The boxes are one selection with the left column's (ui.flowPicked). A batch plans what goes
// (logic.js batchPlan), says itself in one line with Confirm, and only then does anything go out (app.js flowBatch,
// each call quiet, one toast); afterwards Undo the batch, once, takes every point back. Let AI do it in a batch starts
// a point only with its own sentence and while fewer than cockpit.flow.max_running run; the rest stays out, and the
// line says how many. Since round 4 the bar is one part (BatchBar) the lists of Not now take as well, with their own
// verbs, and with Merge where two or more ticked rows are open tasks (MergePanel: which one stays, the one with more
// activity suggested); a square of Prio lists its points in Jev's order as one band.
// For the mouse: no text names a key.
// The rules every component keeps stand at the head of components.js.

import { html, useEffect, useState } from '../vendor/htm-preact-3.1.1.module.js'
import { activityWhen, atWork, batchPlan, batchPreselect, batchSummary, checkinDays, DAY, dropReasonWord, flowDrive, flowSettings, flowSuggestion, FLOW_BANDS,
  FLOW_YOU, formatDay, isoDate, jevWhy, personOf, mergeable, mergeKeep, nextMonday, nextWho, pointBand, pointName, pointStand, pointStep, rankerName,
  rowProject, rowRunning, short, stageTone, workWho } from '../logic.js'
import { T, TABLES, language } from '../text.js'
import { KindTag } from './day.js'
import { Btn, Dot, WhoChip } from './parts.js'

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

/** The rows of a side grouped by band, in FLOW_BANDS order: [{band, rows}], each row {id, row, x} (listRows); stage 4
 *  bands them by who takes the next step (logic.js pointBand, a report by its own row). `one` puts every row in one
 *  band of that name in the order given (Prio: a square by Jev's rank, the unrated by due) */
export function bandsOf(points, one = null) {
  const rows = listRows(points)
  if (one) return rows.length ? [{ band: one, rows }] : []
  return FLOW_BANDS.map(band => ({ band, rows: rows.filter(r => pointBand(r.x, r.row) === band) })).filter(b => b.rows.length)
}

/** The points of a side in the order the overview lists them (bandsOf, `one` as there), each once: the order the walk
 *  bar goes, so Next leads to the row under the one open (round 6 B) */
export function walkOrder(points, one = null) {
  const out = []
  for (const b of bandsOf(points ?? [], one)) for (const r of b.rows) if (!out.includes(r.x)) out.push(r.x)
  return out
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

/** Where a suggestion comes from, in words: the triage or the task check of a day, Jev's order, the themes run */
export function sugFrom(sug, lang) {
  const f = T().flow.list
  const day = at => formatDay(typeof at === 'number' ? isoDate(at) : String(at ?? '').slice(0, 10), lang)
  return sug.from === 'triage' ? f.from.triage(day(sug.at)) : sug.from === 'check' ? f.from.check(day(sug.at))
    : sug.from === 'jev' ? f.from.jev(day(sug.at), rankerName(sug.ranker)) : f.from.themes
}

/** A suggestion's half sentence of why: a drop by its reason, else what the suggestion says, else Jev's square */
export const sugWhy = (sug, lang) => (sug.verb === 'drop' && sug.drop && sug.from !== 'jev' ? dropReasonWord(sug.drop, lang) : sug.reason || jevWhy(sug, lang))

/** A suggestion as a chip: its verb (Later with its day), its half sentence, where it comes from on hover; the
 *  overview's table and the open point (views/flow.js PointAdvice) draw it alike where Work through is off */
export function Suggestion({ sug, s }) {
  const f = T().flow.list
  const lang = language()
  if (!sug) return html`<span class="muted small">${f.none}</span>`
  const from = sugFrom(sug, lang)
  const word = sug.verb === 'later' && sug.until ? f.laterUntil(formatDay(sug.until, lang)) : f.verb[sug.verb]
  const why = sugWhy(sug, lang)
  return html`<span class=${`flow-sug flow-sug-${sug.verb}`} title=${from}>
    <span class="flow-sug-verb">${word}</span>${why ? html`<span class="flow-sug-why">${short(why, 90)}</span>` : null}</span>`
}

// the most feeds the merge panel reads for its counts of activity (the loader of the Activity tab)
const MERGE_FEEDS = 10

/** Merge, under the batch bar: which of the ticked tasks stays (a radio each with its activity and when it last moved,
 *  one an agent works on suggested, else the one with more activity once the feeds came; a pick of the person's
 *  holds), what happens to the others, Merge and Cancel. The merge goes out as one batch with one undo (app.js flowMerge); as Confirm does, it
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
  const working = new Set(list.filter(r => atWork(r, s)).map(r => r.key))
  const keep = keys.includes(pick) ? pick : ready || working.size ? mergeKeep(list, ready ? feeds : {}, working) : keys[0]
  const kept = list.find(r => r.key === keep)
  const others = keys.filter(k => k !== keep)
  const run = async () => {
    onClose()
    onPick(keys, false)
    await c.flowMerge(keep, others, from)
  }
  return html`<div class="verbbar-panel flow-merge" role="group" aria-labelledby="flow-merge-h">
    <p id="flow-merge-h" class="label-caps">${f.title}</p>
    ${working.has(keep) && !keys.includes(pick) ? html`<p class="muted small">${f.proposalRunning}</p>` : ready ? html`<p class="muted small">${f.proposal}</p>` : null}
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
  const [panel, setPanel] = useState(null)       // later, drop, work or merge: the batch buttons that open a choice
  const [plan, setPlan] = useState(null)         // the plan waiting for Confirm
  const [other, setOther] = useState('')
  const [who, setWho] = useState(null)           // In progress for the ticked rows (stage 4): with whom
  // All ticks the rows of the list; a row ticked from elsewhere (an entry of Running now) does not count for it
  const ids = new Set(chosen.map(r => r.key))
  const all = pickable.length > 0 && pickable.every(r => ids.has(r.id))
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
  const merging = personOf(s) ? [] : mergeable(chosen)      // a merge is no verb of a person's (access.py)
  const canMerge = merging.length >= 2 && merging.length === chosen.length
  const verb = v => {
    const off = !chosen.length
    if (v === 'suggested') return html`<${Btn} key=${v} size="sm" variant="primary" disabled=${!suggested?.calls.length} onClick=${() => ask('suggested')}>${w.run}<//>`
    if (v === 'later' || v === 'drop' || v === 'work') {
      const word = v === 'later' ? f.verbs.later : v === 'work' ? f.simple.work : f.verbs.drop
      return html`<${Btn} key=${v} size="sm" variant="secondary" disabled=${off} pressed=${panel === v} onClick=${() => setPanel(panel === v ? null : v)}>${word} ▾<//>`
    }
    const word = v === 'back' ? f.notnow.back : v === 'do' ? f.verbs.do : f.verbs.done
    return html`<${Btn} key=${v} size="sm" variant="secondary" disabled=${off} onClick=${() => ask(v)}>${word}<//>`
  }
  // stage 4: the bar stands only while a row is ticked (count, its verbs, clear); before, one line says so
  const days = checkinDays(nowMs)
  return html`<div class="flow-ov-top">
    ${chosen.length ? html`<div class="flow-ov-bar is-ticked" role="toolbar" aria-label=${w.label}>
      <label class="flow-check"><input type="checkbox" class="flow-ov-all" checked=${all} disabled=${!pickable.length}
        onClick=${() => onPick(pickable.map(r => r.id), !all)} /><span>${w.pickAll}</span></label>
      <span class="flow-ov-sum muted small" role="status">${w.ticked(chosen.length, counts)}</span>
      <span class="flow-ov-verbs">
        ${verbs.map(verb)}
        ${merging.length >= 2 ? html`<${Btn} size="sm" variant="secondary" disabled=${!canMerge} pressed=${panel === 'merge'} title=${canMerge ? undefined : f.merge.only}
          onClick=${() => setPanel(panel === 'merge' ? null : 'merge')}>${f.merge.button} ▾<//>` : null}
        <${Btn} size="sm" variant="ghost" icon="close" label=${w.clear} onClick=${() => onPick(chosen.map(r => r.key), false)} />
      </span>
    </div>` : html`<p class="flow-ov-hint muted small">${w.hintTick}${suggest && pre.length ? html` · <button type="button" class="btn-link flow-ov-tick"
      onClick=${() => onPick(pre, true)}>${w.tick(pre.length)}</button>` : null}</p>`}
    ${merging.length >= 2 && !canMerge ? html`<p class="muted small flow-merge-only">${f.merge.only}</p>` : null}
    ${panel === 'later' ? html`<div class="verbbar-panel verbbar-acts" role="group" aria-label=${f.later.label}>
      <${Btn} size="sm" variant="secondary" onClick=${() => ask('later', isoDate(nowMs + DAY))}>${f.later.tomorrow}<//>
      <${Btn} size="sm" variant="secondary" onClick=${() => ask('later', isoDate(nextMonday(nowMs)))}>${f.later.monday}<//>
      <${Btn} size="sm" variant="secondary" onClick=${() => ask('later', isoDate(nowMs + 7 * DAY))}>${f.later.week}<//>
    </div>` : null}
    ${panel === 'work' ? html`<div class="verbbar-panel flow-work" role="group" aria-label=${f.simple.work}>
      <p class="label-caps">${f.simple.whoLabel}</p>
      <div class="flow-work-chips">${workWho(s).filter(p => p !== 'bridge').map(p => html`<${Btn} key=${p} size="xs" variant="secondary"
        pressed=${who === p} onClick=${() => setWho(p)}>${p === 'me' ? f.simple.me : nextWho(p, s, lang)}<//>`)}</div>
      <p class="label-caps">${f.simple.whenLabel}</p>
      <div class="flow-work-chips">${[3, 7, 14].map(d => html`<${Btn} key=${d} size="xs" variant="secondary" disabled=${!who}
        onClick=${() => ask('work', { who, until: days[d] })}>${f.simple.inDays(d)}<//>`)}</div>
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
      ${done.undo?.length && !personOf(s) ? html`<${Btn} size="sm" variant="secondary" icon="back" onClick=${() => c.flowBatchUndo()}>${w.undo}<//>` : null}</div>` : null}
  </div>`
}

export function FlowOverview({ points, picked, titleFor, kindFor, band = null, running = [], s, c }) {
  const t = T()
  const f = t.flow
  const w = f.list
  const lang = language()
  const bands = bandsOf(points, band)
  const person = !!personOf(s)       // their list: the points and the verbs that are theirs, no AI's suggestion
  const rows = bands.flatMap(b => b.rows)
  const pickable = rows.filter(r => r.row)
  // the ticked points, and what runs ticked on the strip above (logic.js laneRows): for a merge or Done
  const chosen = [...pickable, ...running].filter(r => picked.has(r.id)).map(r => r.row)
  const day = v => formatDay(String(v).slice(0, 10), lang)
  if (!rows.length) return html`<section class="flow-overview" aria-label=${w.label}><p class="muted">${w.empty}</p></section>`
  // stage 4: a row says three things, its name, where it stands under it, and its next step with who takes it beside
  return html`<section class="flow-overview" aria-label=${w.label}>
    <${BatchBar} pickable=${pickable} chosen=${chosen} onPick=${(keys, on) => c.flowPick(keys, on)} verbs=${person ? ['done', 'later', 'drop'] : ['suggested', 'done', 'work', 'later', 'drop']}
      planOf=${(how, value) => batchPlan(chosen, how, s, value, lang)} onRun=${plan => c.flowBatch(plan?.calls ?? [])} suggest=${!person} s=${s} c=${c} />
    <table class="flow-ov-table">
      <thead><tr><th class="flow-ov-pickcol"><span class="sr-only">${w.pickAll}</span></th><th>${w.cols.point}</th><th>${w.cols.step}</th></tr></thead>
      <tbody>${bands.map(b => {
        const ids = b.rows.filter(r => r.row).map(r => r.id)
        const all = ids.length > 0 && ids.every(id => picked.has(id))
        return html`<tr key=${`band-${b.band}`} class="flow-ov-group"><th colspan="3" scope="colgroup"><span class="flow-ov-grouphead">
          ${ids.length ? html`<input type="checkbox" class="flow-ov-grouppick" aria-label=${w.pickGroup(f.groups[b.band])} checked=${all}
            onClick=${() => c.flowPick(ids, !all)} />` : null}<span class="label-caps">${f.groups[b.band]}</span></span></th></tr>
        ${b.rows.map(r => {
          const row = r.row
          const title = row ? pointName(row) : titleFor(r.x)
          const stand = row ? pointStand(row, s) : null
          const step = row ? pointStep(row, s) : null
          // without a stand: its kind, and for a task in progress nobody works on, when it last moved
          const drive = row && !stand && r.x.group === 'doing' ? flowDrive(r.x, s) : null
          const idle = drive?.by === 'none' ? f.doing.none(drive.days) : null
          // an agent at work on it: a small marker only (what runs stands under Running now, never as a strip here)
          const runs = row ? rowRunning(row, s) : false
          const when = step?.check ? f.simple.asksOn(day(step.check)) : step?.due ? f.simple.dueOn(day(step.due)) : null
          return html`<tr key=${r.id} class=${`flow-ov-row${row && picked.has(r.id) ? ' is-picked' : ''}`}>
            <td>${row ? html`<input type="checkbox" class="flow-ov-pick" aria-label=${w.pick(short(title, 60))} checked=${picked.has(r.id)}
              onClick=${() => c.flowPick([r.id], !picked.has(r.id))} />` : null}</td>
            <td class="flow-ov-point"><button type="button" class="flow-ov-open" onClick=${() => c.flowGo(r.x.id, points.indexOf(r.x))}>${short(title, 120)}</button>
              ${runs ? html`<span class="flow-ov-running small"><${Dot} token="info" pulse /> ${f.list.running}</span>` : null}
              <span class="flow-ov-stand muted small">${stand ? short(stand, 160) : idle ? `${kindFor(r.x)} · ${idle}` : kindFor(r.x)}</span></td>
            <td class="flow-ov-step small">${step ? html`<span>${short(step.what, 90)}</span> <${WhoChip} who=${step.who} s=${s} />${when
              ? html`<span class="flow-ov-when muted">${when}</span>` : null}` : null}</td>
          </tr>`
        })}`})}</tbody>
    </table>
  </section>`
}
