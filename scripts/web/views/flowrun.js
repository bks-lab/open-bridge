// SPDX-License-Identifier: MIT
// The cockpit, Running now of Work through (views/flow.js, round 4): what runs is no point to decide, so it stands
// apart from the walk, the overview's table, the boxes and the batch (logic.js flowParts `lane`): a start of the
// cockpit at work, a session linked to a task (by hand, by its own task tab, or recognised from what it did lately)
// whose tab works or waits at its prompt, a task's own tab at work. RunningRow is its part on top of the left column
// (round 5), one row like a group of Not now: its name, its count, a dot that pulses while an entry works; a click
// shows every entry in the middle (view `running`, RunningStrip under a head of its own). RunningStrip also stands on
// top of the overview, the entries of the side entered, each with its tab, its stage, since when, how it is known, To
// tab as the strong way and View, and a box where it has a task of its own: the box is only for merging (and Done)
// with the points ticked in the overview, a batch never starts, puts off or drops what runs (logic.js laneRows,
// batchPlan); a title opens the entry in the middle as view `run`. On a narrow screen, where the left column is a
// select, RunningNarrow folds one compact line per entry (dot, title, tab and stage) under one line over the middle.
// For the mouse: no text names a key.
// The rules every component keeps stand at the head of components.js.

import { html } from '../vendor/htm-preact-3.1.1.module.js'
import { duration, laneRows, short, stageTone } from '../logic.js'
import { T } from '../text.js'
import { TabWays } from './flowside.js'
import { Dot } from './parts.js'

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

/** An entry's dot: it pulses while its agent works, a tab waiting at its prompt is calm */
const LaneDot = ({ x }) => html`<${Dot} token=${stageTone(x.stage === 'waiting' ? 'waiting' : 'working')} pulse=${x.stage === 'working' || x.stage === 'started'} />`

/** The lines of Running now, compact: dot, title (a click opens it in the middle), the tab and its stage */
function LaneLines({ lane, s, c, on }) {
  return html`<ul class="flow-run-list">${lane.map(x => {
    const w = laneWords(x, s)
    const here = on === x.id
    return html`<li key=${x.id} class=${`flow-run-item${here ? ' is-on' : ''}`}>
      <${LaneDot} x=${x} />
      <span class="flow-run-text">
        <button type="button" class="flow-run-open" aria-current=${here ? 'true' : undefined} onClick=${() => c.flowRun(x.id)}>${short(w.title, 80)}</button>
        <span class="flow-run-meta muted">${[w.tab, w.stage].filter(Boolean).join(' · ')}</span>
      </span>
    </li>`
  })}</ul>`
}

/** Running now on top of the left column, one row in the style of a group of Not now: its name, its count, a dot
 *  that pulses while an entry works; a click shows the entries in the middle (view `running`), marked while they or
 *  one of them stand there; nothing while nothing runs */
export function RunningRow({ lane, c, on = false }) {
  const f = T().flow
  if (!lane?.length) return null
  const working = lane.some(x => x.stage === 'working' || x.stage === 'started')
  return html`<div class="flow-run flow-side-body">
    <button type="button" class=${`flow-notnow-item flow-run-cat${on ? ' is-on' : ''}`} aria-current=${on ? 'true' : undefined} onClick=${() => c.flowRunning()}>
      <${Dot} token=${stageTone(working ? 'working' : 'waiting')} pulse=${working} />
      <span class="flow-side-name"><span class="flow-side-label">${f.run.label}</span></span>
      <span class="flow-side-open mono muted">${lane.length}</span>
    </button>
  </div>`
}

/** Running now on a narrow screen: one line with the count and the first title, folded open by a click */
export function RunningNarrow({ lane, s, c, on = null }) {
  const f = T().flow
  if (!lane?.length) return null
  return html`<details class="flow-run-narrow">
    <summary><span class="label-caps">${f.run.label}</span> <span class="mono">${lane.length}</span> <span class="muted">${short(laneWords(lane[0], s).title, 60)}</span></summary>
    <${LaneLines} lane=${lane} s=${s} c=${c} on=${on} />
  </details>`
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
