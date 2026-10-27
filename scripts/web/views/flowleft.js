// SPDX-License-Identifier: MIT
// The cockpit, Not now of Work through (views/flow.js, round 4): every open row that is no point now stands in one of
// its groups (logic.js flowParts leftOut, FLOW_LEFT_OUT): Later (round 6 B, one group for what is put off, hidden until
// a day or due later than the lead time, what waits on others and what rests, each row with its reason in the column
// Why), Ideas and backlog, Streams, Watching (the issues and pull requests, by repository). NotNowBlock is its part at
// the foot of the left column, on every side and in every mode: one button per group with its count, the one open
// marked; on a narrow screen NotNowNarrow folds it under the select. A click shows the group as a list in the middle
// (LeftList, view `left`): Back to overview, its name, count and what it holds, the batch bar with the group's verbs
// (logic.js LEFT_VERBS and leftPlan: Back on, Later, Done, Drop or Let AI do it, Merge where two or more ticked rows
// are open tasks), then a table: a box, the title (it opens the row where it lives: an issue or a pull request on the
// web, a task in the files view, an inbox item in its drawer, a row with steps of its own on a page the info drawer
// that holds them), its kind, when (in Later: why), its area.
// The watched rows stand under a head per repository. No instruction line and no walk bar here.
// For the mouse: no text names a key.
// The rules every component keeps stand at the head of components.js.

import { html } from '../vendor/htm-preact-3.1.1.module.js'
import { activityWhen, formatDay, LEFT_VERBS, leftPlan, pageStepsOf, rowProject, short } from '../logic.js'
import { T, language } from '../text.js'
import { KindTag } from './day.js'
import { ageDays, BatchBar } from './flowlist.js'
import { Btn } from './parts.js'

/** The buttons of the groups of Not now, each with its count, the one open marked */
function GroupButtons({ left, open, c }) {
  const f = T().flow.notnow
  return html`<ul class="flow-side-list">${left.groups.map(g => html`<li key=${g.reason}>
    <button type="button" class=${`flow-notnow-item${open === g.reason ? ' is-on' : ''}`} aria-current=${open === g.reason ? 'true' : undefined}
      onClick=${() => c.flowLeft(g.reason)}>
      <span class="flow-side-name"><span class="flow-side-label">${f.group[g.reason]}</span></span>
      <span class="flow-side-open mono muted">${g.rows.length}</span>
    </button></li>`)}</ul>`
}

/** Not now at the foot of the left column: its count, a button per group that holds a row */
export function NotNowBlock({ left, open = null, c }) {
  const f = T().flow.notnow
  if (!left?.total) return null
  return html`<section class="flow-notnow flow-side-body" aria-labelledby="flow-notnow-h">
    <h3 id="flow-notnow-h" class="flow-side-group label-caps">${f.label} <span class="mono">${left.total}</span></h3>
    <${GroupButtons} left=${left} open=${open} c=${c} />
  </section>`
}

/** Not now on a narrow screen: folded under the select */
export function NotNowNarrow({ left, open = null, c }) {
  const f = T().flow.notnow
  if (!left?.total) return null
  return html`<details class="flow-notnow-narrow">
    <summary><span class="label-caps">${f.label}</span> <span class="mono">${left.total}</span></summary>
    <${GroupButtons} left=${left} open=${open} c=${c} />
  </details>`
}

/** When a row of Not now comes or is due: the day it comes back (Later, or an idea put off) and its due, else its age */
function whenOf(e, reason, s, lang) {
  const f = T().flow
  if (reason === 'later' || e.until) {
    return [e.until ? f.notnow.from(formatDay(e.until, lang)) : null, e.due ? f.notnow.due(activityWhen(e.due, lang)) : null].filter(Boolean).join(' · ')
  }
  const age = ageDays(e.row, s.now || Date.now())
  return age == null ? '' : f.list.age(age)
}

// the day a row of Later rests since: when its task last moved, else the day its inbox id names
const restDay = row => (/^\d{4}-\d{2}-\d{2}/.test(String(row.updated ?? '')) ? String(row.updated).slice(0, 10)
  : /^\d{8}/.test(String(row.inbox_id ?? '')) ? `${row.inbox_id.slice(0, 4)}-${row.inbox_id.slice(4, 6)}-${row.inbox_id.slice(6, 8)}` : null)

/** Why a row of Later is no point now (round 6 B, its entry's kind): until when it is put off, hidden or not due yet,
 *  on whom it waits (its blocker, the person its next step names, else others; an item with your yes on an agent),
 *  what blocks it or since when it rests */
function laterWhy(e, lang) {
  const f = T().flow.notnow
  const w = f.why
  const row = e.row
  const by = String(row.blocked_by ?? row.card?.state?.blocked_by ?? '').trim()
  if (e.kind === 'waiting') {
    if (row.inbox_state === 'approved') return w.approved
    const who = by || String(row.card?.next?.who ?? '').trim()
    return who ? w.waits(who) : w.others
  }
  if (e.kind === 'resting') {
    if (by) return w.blocked(by)
    if (row.bucket === 'drop') return w.park
    const day = restDay(row)
    return day ? w.resting(formatDay(day, lang)) : w.rests
  }
  const until = e.until ? formatDay(e.until, lang) : null
  if (e.why === 'ahead') return w.ahead(activityWhen(e.due, lang), until)
  return [e.why === 'hidden' ? w.hidden(until) : w.deferred(until), e.due ? f.due(activityWhen(e.due, lang)) : null].filter(Boolean).join(' · ')
}

/** A row's title as the way to where it lives: an issue or a pull request on the web, a task in the files view, an
 *  inbox item in its drawer, a row with steps of its own on a page the info drawer that holds them (round 6 B); a row
 *  with none of those as plain text */
function OpenRow({ row, s, c }) {
  const title = short(row.title ?? row.key, 120)
  if (row.inbox_id) return html`<button type="button" class="flow-ov-open" onClick=${() => c.openItem(row.key)}>${title}</button>`
  if (row.task && String(row.key).startsWith('task:')) return html`<button type="button" class="flow-ov-open" onClick=${() => c.openFile(row.task, null)}>${title}</button>`
  const steps = pageStepsOf(row, s)
  if (steps) return html`<button type="button" class="flow-ov-open" onClick=${() => c.openInfo(steps.it, steps.page, steps.section)}>${title}</button>`
  if (row.url) return html`<a class="flow-ov-open" href=${row.url} target="_blank" rel="noopener noreferrer">${title}</a>`
  return html`<span class="flow-ov-open">${title}</span>`
}

/** One group of Not now as a list in the middle, with its batch bar */
export function LeftList({ group, s, c }) {
  const t = T()
  const f = t.flow
  const lang = language()
  const reason = group.reason
  const keys = new Set(group.rows.map(e => e.row.key))
  const picked = new Set((s.ui.flowLeftPicked ?? []).filter(k => keys.has(k)))
  const pickable = group.rows.map(e => ({ id: e.row.key, row: e.row, e }))
  const chosen = group.rows.filter(e => picked.has(e.row.key))
  // the watched rows under a head per repository, the others in one run
  const heads = reason === 'watch' ? [...new Set(group.rows.map(e => e.repo ?? null))] : [undefined]
  const run = async plan => {
    if (plan?.early?.length) c.flowEarly(Object.fromEntries(chosen.filter(e => plan.early.includes(e.row.key)).map(e => [e.row.key, e.until])))
    if (plan?.calls?.length) await c.flowBatch(plan.calls, 'left')
  }
  return html`<section class="flow-overview flow-leftlist" aria-labelledby="flow-left-h">
    <header class="flow-main-head">
      <${Btn} size="sm" variant="secondary" icon="back" cls="flow-back" onClick=${() => c.flowOverview()}>${f.point.back}<//>
      <h2 id="flow-left-h" class="flow-main-title">${f.notnow.group[reason]} <span class="mono muted">${group.rows.length}</span></h2>
    </header>
    <p class="muted small flow-left-sub">${f.notnow.sub[reason]}</p>
    <${BatchBar} pickable=${pickable} chosen=${chosen.map(e => e.row)} onPick=${(ks, on) => c.flowLeftPick(ks, on)} verbs=${LEFT_VERBS[reason] ?? []}
      planOf=${(how, value) => leftPlan(chosen, how, s, value, lang)} onRun=${run} from="left" s=${s} c=${c} />
    ${group.rows.length ? html`<table class="flow-ov-table">
      <thead><tr><th class="flow-ov-pickcol"><span class="sr-only">${f.list.pickAll}</span></th><th>${f.list.cols.point}</th><th>${reason === 'later' ? f.notnow.cols.why : f.notnow.cols.when}</th>
        <th>${f.list.cols.area}</th></tr></thead>
      <tbody>${heads.map(head => html`
        ${head !== undefined ? html`<tr key=${`repo-${head}`} class="flow-ov-group"><th colspan="4" scope="colgroup"><span class="label-caps">${head ?? f.notnow.otherRepo}</span></th></tr>` : null}
        ${group.rows.filter(e => head === undefined || (e.repo ?? null) === head).map(e => {
          const row = e.row
          return html`<tr key=${row.key} class=${`flow-ov-row${picked.has(row.key) ? ' is-picked' : ''}`}>
            <td><input type="checkbox" class="flow-ov-pick" aria-label=${f.list.pick(short(row.title ?? row.key, 60))} checked=${picked.has(row.key)}
              onClick=${() => c.flowLeftPick([row.key], !picked.has(row.key))} /></td>
            <td class="flow-ov-point"><${OpenRow} row=${row} s=${s} c=${c} />
              <span class="flow-ov-sub muted small"><${KindTag} row=${row} s=${s} /></span></td>
            ${reason === 'later' ? html`<td class="flow-ov-stage flow-ov-why small">${laterWhy(e, lang)}</td>`
              : html`<td class="flow-ov-stage small">${whenOf(e, reason, s, lang)}</td>`}
            <td class="flow-ov-area small">${rowProject(row)}</td>
          </tr>`
        })}`)}</tbody>
    </table>` : html`<p class="muted">${f.notnow.empty}</p>`}
  </section>`
}
