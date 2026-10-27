// SPDX-License-Identifier: MIT
// The cockpit, Running now of Work through (views/flow.js, round 4): what runs is no point to decide, so it stands
// apart from the walk, the overview's table, the boxes and the batch (logic.js flowParts `lane`): a start of the
// cockpit at work, a session linked to a task (by hand, by its own task tab, or recognised from what it did lately)
// whose tab works or went quiet at its prompt (finished; one waiting that is not quiet yet needs you and is a point,
// logic.js tabStage), a task's own tab at work or finished. Round 6: every live session stands here too, with a task
// or without one and with a terminal driver or without one (flowParts `sessions`, logic.js runningOf), as a compact
// card of the Sessions page (views/sessions.js SessionCard: its state read off the live tab, a quiet one finished,
// the title as the jump to its tab, where it runs, its agents as a count and a lane, two lines of its tab, one next
// step, the task to link); a lane entry in a session's tab is that card's, so it stands once. RunningRow is its part
// on top of the left column (round 5), one row like a group of Not now: its name, its count (the cards and the
// entries no card holds), a dot that pulses while one works; a click shows them in the middle (view `running`: the
// entries no card holds as rows, then SessionCards).
// RunningStrip also stands on top of the overview, the entries of the side entered, each with its tab, its stage,
// since when, how it is known, To tab as the strong way and View, and a box where it has a task of its own: the box is
// only for merging (and Done) with the points ticked in the overview, a batch never starts, puts off or drops what
// runs (logic.js laneRows, batchPlan); a title opens the entry in the middle as view `run`. A session card keeps the
// box and the title of its entry; View in chat opens its tab's room in the Chat where the Chat lays out its tabs
// (chat_layout workspaces), else View stays the tab's overlay. On a narrow screen, where the left column is a select,
// RunningNarrow folds one compact line per card and entry under one line over the middle.
// For the mouse: no text names a key.
// The rules every component keeps stand at the head of components.js.

import { html } from '../vendor/htm-preact-3.1.1.module.js'
import { duration, laneRows, short, stageTone } from '../logic.js'
import { T } from '../text.js'
import { TabWays } from './flowside.js'
import { CHAT_PAGE, chatAsWorkspaces } from './nav.js'
import { Btn, Dot } from './parts.js'
import { SessionCard } from './sessions.js'

/** The words of an entry of Running now: its title, its tab's name, its stage, since when and how it is known */
export function laneWords(x, s) {
  const f = T().flow
  const nowMs = s.now || Date.now()
  return {
    title: x.row?.title ?? x.title ?? x.start?.title ?? x.tab?.name ?? '',
    tab: x.tab?.name ?? '',
    stage: f.doing.stage[x.stage] ?? x.stage ?? '',
    since: Number.isFinite(x.at) ? f.since(duration(nowMs - x.at)) : '',
    how: f.run.how[x.how] ?? '',
  }
}

/** An entry's dot: it pulses while its agent works, a tab waiting at its prompt or finished is calm */
const LaneDot = ({ x }) => html`<${Dot} token=${stageTone(x.stage === 'waiting' || x.stage === 'idle' ? 'idle' : 'working')} pulse=${x.stage === 'working' || x.stage === 'started'} />`

/** The lines of Running now, compact: dot, title (a click opens it in the middle), the tab and its stage; a session
 *  card's line opens its entry where it has one, else the cards */
function LaneLines({ running, s, c, on }) {
  const f = T().flow
  const lines = [...running.sessions.map(v => ({ id: v.entry?.id ?? v.id, x: v.entry ?? v, title: v.entry ? laneWords(v.entry, s).title : sessionTitle(v),
    meta: [v.tab?.name, f.doing.stage[v.stage] ?? v.stage].filter(Boolean), open: () => (v.entry ? c.flowRun(v.entry.id) : c.flowRunning()) })),
  ...running.loose.map(x => { const w = laneWords(x, s); return { id: x.id, x, title: w.title, meta: [w.tab, w.stage].filter(Boolean), open: () => c.flowRun(x.id) } })]
  return html`<ul class="flow-run-list">${lines.map(l => {
    const here = on === l.id
    return html`<li key=${l.id} class=${`flow-run-item${here ? ' is-on' : ''}`}>
      <${LaneDot} x=${l.x} />
      <span class="flow-run-text">
        <button type="button" class="flow-run-open" aria-current=${here ? 'true' : undefined} onClick=${l.open}>${short(l.title, 80)}</button>
        <span class="flow-run-meta muted">${l.meta.join(' · ')}</span>
      </span>
    </li>`
  })}</ul>`
}

/** A session card's title: its tab's name, else the session's own name */
const sessionTitle = v => v.session?.tab?.name || v.session?.name || v.session?.id || ''

/** Running now on top of the left column, one row in the style of a group of Not now: its name, its count (logic.js
 *  runningOf: the session cards and the entries no card holds), a dot that pulses while one works; a click shows them
 *  in the middle (view `running`), marked while they or one of them stand there; nothing while nothing runs */
export function RunningRow({ running, c, on = false }) {
  const f = T().flow
  if (!running?.n) return null
  return html`<div class="flow-run flow-side-body">
    <button type="button" class=${`flow-notnow-item flow-run-cat${on ? ' is-on' : ''}`} aria-current=${on ? 'true' : undefined} onClick=${() => c.flowRunning()}>
      <${Dot} token=${stageTone(running.working ? 'working' : 'waiting')} pulse=${running.working} />
      <span class="flow-side-name"><span class="flow-side-label">${f.run.label}</span></span>
      <span class="flow-side-open mono muted">${running.n}</span>
    </button>
  </div>`
}

/** Running now on a narrow screen: one line with the count and the first title, folded open by a click */
export function RunningNarrow({ running, s, c, on = null }) {
  const f = T().flow
  if (!running?.n) return null
  const first = running.sessions[0] ? sessionTitle(running.sessions[0]) : laneWords(running.loose[0], s).title
  return html`<details class="flow-run-narrow">
    <summary><span class="label-caps">${f.run.label}</span> <span class="mono">${running.n}</span> <span class="muted">${short(first, 60)}</span></summary>
    <${LaneLines} running=${running} s=${s} c=${c} on=${on} />
  </details>`
}

/** The live sessions in the view `running`, one compact SessionCard each (round 6): a session without a driver
 *  without its tab; one whose tab holds a lane entry with a task of its own the box for a merge (`picked` as the
 *  overview's) and the entry's title, which opens it in the middle; one without a task says so beside the picker.
 *  View in chat (and View) opens its tab's room in the Chat where the Chat lays out its tabs, else the tab's overlay */
export function SessionCards({ sessions, s, c, picked = new Set() }) {
  const f = T().flow
  if (!sessions?.length) return null
  const boxes = new Map(laneRows(sessions.map(v => v.entry).filter(Boolean)).map(r => [r.x.id, r.row.key]))
  const rooms = chatAsWorkspaces(s)
  const inChat = ref => { c.setPage(CHAT_PAGE); c.pickRoom({ kind: 'tab', id: ref }) }
  // the card's View goes to the Chat too: the controller with that one way changed (a proxy, so a recorder stays one)
  const cv = rooms ? new Proxy(c, { get: (o, k) => (k === 'openTabView' ? inChat : o[k]) }) : c
  return html`<ul class="sess-grid flow-sessions" aria-label=${f.run.sessions}>${sessions.map((v, i) => {
    // the card reads its state off its tab: the live one, whose quiet (idle) says finished, not waiting
    const x = v.tab ? { ...v.session, tab: { ...(v.session.tab ?? {}), state: v.tab.state, idle: v.tab.idle === true } } : { ...v.session, tab: null }
    const key = v.entry ? boxes.get(v.entry.id) ?? null : null
    const title = v.entry ? laneWords(v.entry, s).title : ''
    const lead = key ? html`<input type="checkbox" class="flow-ov-pick" aria-label=${f.list.pick(short(title, 60))}
      checked=${picked.has(key)} onClick=${() => c.flowPick([key], !picked.has(key))} />` : null
    const more = v.entry ? html`<button type="button" class="flow-run-open small" onClick=${() => c.flowRun(v.entry.id)}>${short(title, 90)}</button>`
      : x.task ? null : html`<span class="muted small">${f.run.noTask}</span>`
    const foot = rooms && v.tab ? html`<${Btn} size="xs" variant="ghost" onClick=${() => inChat(v.tab.ref)}>${f.run.inChat}<//>` : null
    return html`<${SessionCard} key=${v.id} x=${x} i=${i} s=${s} c=${cv} compact lead=${lead} more=${more} foot=${foot} />`
  })}</ul>`
}

/** Running now on top of the overview: the entries of the side entered (every one at the level of all), each with its
 *  tab, stage, since when and how, To tab the strong way and View; a box on an entry with a task of its own, in the
 *  same selection as the overview's (`picked`, ui.flowPicked), for a merge with a point. `bare`: the view `running`,
 *  whose head names it, so no head of its own, why the boxes are there as a line */
export function RunningStrip({ lane, s, c, picked = new Set(), bare = false }) {
  const f = T().flow
  if (!lane?.length) return null
  const boxes = new Set(laneRows(lane).map(r => r.x.id))
  return html`<section class=${`flow-runstrip${bare ? ' is-bare' : ''}`} aria-labelledby=${bare ? 'flow-running-h' : 'flow-runstrip-h'}>
    ${bare ? (boxes.size ? html`<p class="flow-runstrip-why muted small">${f.run.boxWhy}</p>` : null)
      : html`<h3 id="flow-runstrip-h" class="label-caps">${f.run.label} <span class="mono">${lane.length}</span>
      ${boxes.size ? html` <span class="flow-runstrip-why muted small">${f.run.boxWhy}</span>` : null}</h3>`}
    <ul class="flow-runstrip-list">${lane.map(x => {
      const w = laneWords(x, s)
      const key = boxes.has(x.id) ? x.row.key : null
      return html`<li key=${x.id} class=${`flow-runstrip-row${key && picked.has(key) ? ' is-picked' : ''}`}>
        ${key ? html`<input type="checkbox" class="flow-ov-pick flow-runstrip-pick" aria-label=${f.list.pick(short(w.title, 60))}
          checked=${picked.has(key)} onClick=${() => c.flowPick([key], !picked.has(key))} />` : html`<span class="flow-runstrip-pick" aria-hidden="true"></span>`}
        <${LaneDot} x=${x} />
        <span class="flow-runstrip-text">
          <button type="button" class="flow-run-open" onClick=${() => c.flowRun(x.id)}>${short(w.title, 120)}</button>
          <span class="muted small">${[w.tab, w.stage, w.since, w.how].filter(Boolean).join(' · ')}</span>
        </span>
        <span class="flow-runstrip-acts"><${TabWays} tab=${x.tab} row=${x.row} title=${w.title} s=${s} c=${c} strong /></span>
      </li>`
    })}</ul>
  </section>`
}
