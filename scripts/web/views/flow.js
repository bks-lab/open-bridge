// SPDX-License-Identifier: MIT
// The cockpit, Work through: a view of the work tab (cockpit.flow.enabled, logic.js workViews 'flow'), laid out as cmux
// lays out a workspace. Left the themes the server's small model gives the open points across the areas, or the areas
// themselves, the one entered marked (views/flowside.js FlowSide, a table of contents). The middle shows the overview
// of the theme entered, or of all of them (views/flowlist.js FlowOverview: a table of the points with a suggestion each
// and the batch bar), until a title opens a point (ui.flowView): Back to overview, a line while points are ticked, the
// point as a card, held by its id (logic.js focusIndex) so the next one moves up after a decision, in the queue's fixed
// order (logic.js flowQueue: the return card after a jump to a tab, the tabs that ask, what an agent finished, a start
// that got lost, the questions for you; then what is in progress; then the tasks in review; the reports as one card),
// walked the way the overview lists them (views/flowlist.js walkOrder, one order for both, round 6 B).
// The open point is the one point view (views/flowpoint.js PointView, stage 1 of 04.11.2026: every way to an item or a
// task lands there, the Files tab shows the same): the card carries content only (round 3, nothing twice): its kind in
// its head (the state, the only place it stands) with the kind of row and Pin, its title, its headline and its next
// step, what its tab asks with one set of answers, a start's result, the live tab's screen; who works on it is a field
// on the right, the criteria stand in Description. Under it the tabs of the point (views/flowtabs.js: Description,
// Steps, Activity, Related), then at the foot the instruction line with Instruct or Ask (views/flowinstruct.js) over
// the files view's walk bar (views/dossier.js Walk), which after the last point leads to the first point of the next
// theme where something is open. Right, only while a point or an
// entry of Running now is open (round 6 B: the overview, a list and the grid take the width, their hint under them),
// what you can do and the fields (views/flowside.js FlowAside: the suggestion, the verbs, who works on it, the source).
// To tab remembers the jump (ui.flowJump, in memory only): once the page is in view again return_after_s later, the
// return card asks how it went (app.js). Round 4: every open row stands exactly once (logic.js flowParts). What runs
// stands in Running now (views/flowrun.js: one row on top of the left column that shows every entry in the middle as
// view `running`, since round 6 every live session at work there as a compact card; never over an overview and never
// in the walk, one count for the head and the column, a row of a list an agent works on only marked; a title opens one in the middle
// as view `run`, its card, its tabs and its instruction line, without the walk bar, its way back to the list it came
// from); what is no point now stands in Not now at the foot of the left column (views/flowleft.js), a group of it as a
// list in the middle (view `left`) with its own batch, a title of it the row in the one point view (ui.flowLeftAt,
// stage 1: To the list leads back, the walk walks the group); the finished AI runs a group of their own under Running
// now (stage 2, views/flowleft.js ReadRow and ReadList, view `read`, one of them the run in the one point view with
// ui.flowReadAt, To the list leads back; they never stand in the queue nor among what needs you); a row that stands
// nowhere on the page opens as a point
// of its own (view `solo`, ui.flowSolo, logic.js soloPoint: another area's, a closed task, a settled item, read only
// without an open row; Back leads to the overview, or to the reports card it was opened from). Stage 3: a row a way
// opened from a list (the task check, a page's rows, the start page, the Due list: ui.flowList, logic.js pointList)
// walks that list, and To the list leads back to where it stood, whichever of these views it opened in; under it Check tasks,
// the task check in the middle (view `check`,
// round 6 c, views/flowleft.js CheckList). Round 5: the left column lists no point, the middle does; what
// opens in the middle is brought into view where the page scrolled its top away. Prio orders the left column by Jev's
// squares (views/flowprio.js: the 2x2 grid at the level of all squares). With nothing open the calm card offers up to
// three ideas to start; before the first state the page says it loads, or why not (round 6 B). Without a terminal
// driver the cards of the agents, the entries of Running now and every way to a tab stay out; its session cards stay.
// The agents' cards: a tab that asks carries the answers to its question (views/reply.js), the decision guide
// (views/guide.js) folded under one button, each through the reply verbs that guard the tab; a finished or quiet start
// its result line (the criteria of its brief stand in Description, to check yourself); Done and close the tab, Improve
// (words to the tab while it lives, else a new start) and Runs on stand on the right. When a point is opened, the
// briefs of the next points that miss one are written ahead (cockpit.flow.prep_ahead, c.flowPrep: one at a time,
// once per key), and points without a theme ask for theirs (c.flowThemesAuto, once per key), in every order of the
// left column, as does Jev's daily order of the work page where Jev orders it (c.flowPrioOrder, once per page load;
// the server orders anew only on the day's first ask; with Haiku alone it reads the kept order and orders nothing). No
// title opens a drawer or another view: what the item drawer held stands in the one view (stage 1), a report of the
// reports card opens alone in it (Open). For the mouse: the page names no key.
// The rules every component keeps stand at the head of components.js.

import { html, useEffect, useRef } from '../vendor/htm-preact-3.1.1.module.js'
import {
  flowDriver, flowMode, flowParts, flowQueue, flowSettings, flowSides, focusIndex, instructScope, laneRows, leftWalk, pointListAt, pointsIn,
  runningOf, prepTargets, prioLoaded, prioOn, restSuggestions, short, soloPoint, themesToAsk, workPageOf, personOf, pointName
} from '../logic.js'
import { T } from '../text.js'
import { NoModel, WorkSwitch } from './day.js'
import { CheckList, LeftList, ReadList } from './flowleft.js'
import { FlowOverview, listRows, walkOrder } from './flowlist.js'
import { PrioGrid, PrioSource } from './flowprio.js'
import { RunningStrip, SessionCards } from './flowrun.js'
import { FlowAside, FlowSide, SideDot, sideName } from './flowside.js'
import { InstructLine } from './flowinstruct.js'
import { PointView, pointStandWord, pointTitle, useSoloLoad } from './flowpoint.js'
import { Calm } from './focus.js'
import { Btn } from './parts.js'
import { VerbBar } from './verbbar.js'

/** Nothing open: the calm card, and up to three ideas or backlog tasks to start, each with Let AI do it */
function Rest({ s, c }) {
  const f = T().flow
  const ideas = restSuggestions(s, 3)
  return html`<${Calm} s=${s} c=${c} title=${f.rest.title} sub=${f.rest.sub} action=${false} />
    <section class="flow-rest" aria-labelledby="flow-rest">
      <h2 id="flow-rest" class="label-caps">${f.rest.suggest}</h2>
      ${ideas.length ? html`<ul>${ideas.map(row => html`<li key=${row.key}><span class="flow-rest-title">${short(pointName(row), 90)}</span>
        <${VerbBar} row=${row} s=${s} c=${c} verbs=${['do']} primary="do" /></li>`)}</ul>` : html`<p class="muted small">${f.rest.none}</p>`}
    </section>`
}

/** Brings the top of the middle back into the page column where it scrolled up out of sight: the column that
 *  scrolls is the page's (.col), on a narrow screen the window */
function intoView(el) {
  if (!el?.getBoundingClientRect || !el.scrollIntoView) return
  const col = el.closest?.('.col')?.getBoundingClientRect?.()
  if (el.getBoundingClientRect().top < Math.max(0, col?.top ?? 0) - 1) el.scrollIntoView({ block: 'start' })
}

/** The page; before the first state (or without one: the connection gone, a pass failed) it says so, as Due does,
 *  never the calm card's All decided over an empty queue (round 6 B) */
export function FlowPage({ s, c }) {
  if (s.model) return html`<${FlowBody} s=${s} c=${c} />`
  return html`<div class="col col-page flow"><header class="page-head flow-head"><${WorkSwitch} s=${s} c=${c} /></header><${NoModel} s=${s} cls="flow-nostate" /></div>`
}

function FlowBody({ s, c }) {
  const t = T()
  const f = t.flow
  const parts = flowParts(s)
  const all = flowQueue(parts, 'all')
  const mode = flowMode(s)
  const sides = flowSides(s, all, mode)
  // the theme, area or square entered (level two of the left column), else the level of all of them
  const entered = sides.find(x => x.id !== 'all' && x.id === s.ui.flowSide?.[mode]) ?? null
  const side = entered?.id ?? 'all'
  // how the overview bands its points (Prio: a square by Jev's rank, Not rated yet by due), and the walk in that order:
  // Next goes the way the overview lists them (round 6 B, views/flowlist.js walkOrder)
  const band = mode === 'prio' && entered ? (entered.id === 'none' ? 'due' : 'rank') : null
  const queue = walkOrder(pointsIn(all, side, s, mode), band)
  const lane = pointsIn(parts.lane, side, s, mode)
  // one count of Running now for the head and the left column (runningOf), and no strip of it over any overview
  const runs = runningOf(parts)
  const i = focusIndex(queue, s.ui.flowAt)
  // the middle: the point open, an entry of Running now, a group of Not now (its list, or one of its rows as a point,
  // ui.flowLeftAt, stage 1), a point of its own (ui.flowSolo, stage 1), the task check, else the overview; what went (a
  // point decided, a start that finished, a group emptied) falls back to the overview, a row that left its group to
  // the next row of that group, or to its list
  const running = s.ui.flowView === 'run' ? parts.lane.find(e => e.id === s.ui.flowRunId) ?? null : null
  const group = s.ui.flowView === 'left' ? parts.leftOut.groups.find(g => g.reason === s.ui.flowLeft) ?? null : null
  const leftQueue = group && s.ui.flowLeftAt ? leftWalk(parts, group.reason) : []
  const li = focusIndex(leftQueue, s.ui.flowLeftAt)
  const solo = s.ui.flowView === 'solo' ? s.ui.flowSolo ?? null : null
  const soloEntry = useSoloLoad(solo, s, c)
  const alone = solo ? soloPoint(s, solo) : null
  // stage 2: the finished AI runs, their list or one of them (ui.flowReadAt), held as the queue holds a point
  const reading = s.ui.flowView === 'read' && parts.read.length
  const ri = focusIndex(parts.read, s.ui.flowReadAt)
  const view = running ? 'run' : group ? (leftQueue.length ? 'leftPoint' : 'left') : solo ? 'solo'
    : reading ? (s.ui.flowReadAt ? 'readPoint' : 'read') : s.ui.flowView === 'check' ? 'check'
    : s.ui.flowView === 'running' && runs.n ? 'running' : s.ui.flowView === 'point' && queue.length ? 'point' : 'overview'
  const x = view === 'point' ? queue[i] ?? null : view === 'run' ? running : view === 'leftPoint' ? leftQueue[li] ?? null : view === 'solo' ? alone
    : view === 'readPoint' ? parts.read[ri] ?? null : null
  const driver = flowDriver(s)
  // the boxes: every point with a row, and what runs with a task of its own (for a merge and Done only)
  const runRows = laneRows(lane)
  // (the view `running` shows every entry, so its boxes count at every side)
  const keys = new Set([...listRows(queue).filter(r => r.row).map(r => r.id), ...(view === 'running' ? laneRows(parts.lane) : runRows).map(r => r.id)])
  const picked = new Set((s.ui.flowPicked ?? []).filter(k => keys.has(k)))
  const go = k => c.flowGo(queue[k].id, k)
  const decided = s.ui.flowDecided ?? 0
  // after the last point of a theme or area: the first point of the next one below it where something is open
  const at = sides.findIndex(v => v.id === side)
  const nextSide = entered ? sides.slice(at + 1).find(v => v.id !== 'all' && v.open) ?? sides.slice(1, Math.max(1, at)).find(v => v.open) : null
  const onwards = nextSide ? { title: f.walk2.nextSide(sideName(nextSide, mode)), word: f.walk2.toSide, onGo: () => c.flowSide(nextSide.id, 'point') } : null
  // the point in front changed: the briefs of the next points are written ahead, where one is missing or stale
  const ahead = flowSettings(s).prep_ahead
  const prep = view === 'point' && x ? prepTargets(queue, i, ahead, s) : []
  useEffect(() => { if (prep.length) c.flowPrep(prep) }, [x?.id, ahead])
  // the points without a theme get theirs when the view shows them, once per key on this page load (app.js), in every
  // order of the left column: the themes run's suggestions stand in the overview in Areas and Prio too (round 6 B)
  const ask = themesToAsk(all, s)
  useEffect(() => { if (ask.length) c.flowThemesAuto(ask) }, [ask.join(',')])
  // Jev's daily order of the work page (Prio's squares, Jev's suggestions in every order): asked once per page load in
  // every order where Jev orders that page and none is there; the server orders anew only on the day's first ask, a
  // new order is a click on Read in with Jev or Read in with Haiku at Prio's foot (round 6 B; Haiku never by itself)
  const work = prioOn(s) ? workPageOf(s.model?.pages) : null
  const order = work ? s.jevOrder?.[work.id] : null
  // only once the page has read what it shows (prioLoaded): the day's order of an early snapshot would rank too little
  const loaded = prioLoaded(s)
  useEffect(() => { if (work && order === undefined && loaded) c.flowPrioOrder(work.id) }, [work?.id, order === undefined, loaded])
  const name = sideName(entered, mode)
  // what the instruction line speaks for: the point or the entry open, else the ticked points or every point of the side;
  // nothing on a point of its own that is closed (its verbs act on nothing), Ask still asks about it
  const scope = view === 'left' || view === 'read' || view === 'check' || (view === 'solo' && (!x || x.readOnly)) ? null
    : instructScope(x, queue, picked, entered ? name : null, s)
  const counts = parts.counts
  const grid = mode === 'prio' && !entered
  // what opens in the middle comes into view: its top scrolled up out of the page column is brought back (round 5)
  const main = useRef(null)
  useEffect(() => { requestAnimationFrame(() => intoView(main.current)) }, [view, group?.reason, running?.id, side, ['point', 'leftPoint', 'solo', 'readPoint'].includes(view) ? x?.id : null])
  // back from an entry of Running now: to the list it was opened from (ui.flowRunFrom), else to the overview
  const fromRunning = view === 'run' && s.ui.flowRunFrom === 'running'
  // the point in the middle, the one view of it (views/flowpoint.js), by where it was opened: a point of the queue
  // walks the queue (after its last, the next theme), an entry of Running now walks nothing, a row of Not now walks its
  // group and goes back to its list, a point of its own goes back where it came from (the reports card, else the
  // overview)
  const walk2 = { words: { ...f.walk2, queue: t.dossier.walk.queue }, titleFor: pointTitle, tagsOf: () => null, whyOf: pointStandWord, cls: 'flow-walk' }
  // stage 3: a row opened from a list walks that list and goes back to where it stood, wherever it opened
  const list = pointListAt(s.ui.flowList, x)
  const listBack = s.ui.flowList ? { word: f.one.backList, onClick: () => c.flowListBack() } : null
  const listWalk = list ? { ...walk2, queue: list.items.map(e => ({ id: e.key, title: e.title || e.key })), i: list.i, go: k => c.flowListGo(k),
    titleFor: e => e.title, whyOf: () => '', done: f.walk2.last } : null
  const placed = !x ? null : view === 'run'
    ? { back: { word: fromRunning ? f.run.back : f.point.back, onClick: () => (fromRunning ? c.flowRunning() : c.flowOverview()) }, theme: f.run.label }
    : view === 'leftPoint'
      ? { back: { word: f.one.backList, onClick: () => c.flowLeft(group.reason) }, theme: f.notnow.group[group.reason],
        walk: { ...walk2, queue: leftQueue, i: li, go: k => c.flowLeftOpen(leftQueue[k].id, k), done: f.walk2.last } }
      : view === 'solo'
        ? { back: { word: f.point.back, onClick: () => (solo.from ? c.flowGo(solo.from, 0) : c.flowOverview()) }, theme: f.one.solo }
      : view === 'readPoint'
        ? { back: { word: f.one.backList, onClick: () => c.flowRead() }, theme: f.read.label,
          walk: { ...walk2, queue: parts.read, i: ri, go: k => c.flowReadOpen(parts.read[k].id, k), done: f.walk2.last } }
        : { back: { word: f.point.back, onClick: () => c.flowOverview() }, theme: name,
          above: picked.size ? html`<div class="flow-picked-line"><span class="muted small">${f.point.ticked(picked.size)}</span>
            <${Btn} size="sm" variant="secondary" onClick=${() => c.flowOverview()}>${f.point.see}<//></div>` : null,
          walk: { ...walk2, queue, i, go, done: f.walk2.last, onwards } }
  const point = placed && list ? { ...placed, back: listBack, walk: listWalk, above: null } : placed
  return html`<div class="col col-page flow">
    <header class="page-head flow-head">
      <${WorkSwitch} s=${s} c=${c} />
      <p class="muted small">${[f.count(counts.points, runs.n, counts.left), decided ? f.decided(decided) : null].filter(Boolean).join(' · ')}</p>
    </header>
    ${driver || personOf(s) ? null : html`<p class="flow-nodriver muted small">${f.noDriver}</p>`}
    <div class=${`flow-grid${x ? '' : ' no-aside'}`}>
      <${FlowSide} sides=${sides} entered=${entered} mode=${mode} all=${all} view=${view} running=${runs} left=${parts.leftOut}
        run=${running?.id ?? null} open=${group?.reason ?? null} read=${parts.read} s=${s} c=${c} />
      <section class=${`flow-main${x ? ' is-point' : ''}`} aria-label=${f.title} ref=${main}>
        ${point ? html`<${PointView} x=${x} ...${point} scope=${scope} n=${view === 'point' ? queue.length : 1} s=${s} c=${c} />`
          : view === 'solo' ? html`<header class="flow-main-head">
              <${Btn} size="sm" variant="secondary" icon="back" cls="flow-back" onClick=${listBack?.onClick ?? (() => c.flowOverview())}>${listBack?.word ?? f.point.back}<//></header>
            <p class="muted" role="status">${soloEntry?.status === 'error' || (soloEntry?.data && !alone) ? f.one.gone : f.one.loading}</p>`
          : view === 'left' ? html`<${LeftList} key=${group.reason} group=${group} s=${s} c=${c} /><p class="muted small flow-main-hint">${f.notnow.hint}</p>`
          : view === 'read' ? html`<${ReadList} read=${parts.read} c=${c} />`
          : view === 'check' ? html`<${CheckList} s=${s} c=${c} />`
          : view === 'running' ? html`<header class="flow-main-head">
              <${Btn} size="sm" variant="secondary" icon="back" cls="flow-back" onClick=${() => c.flowOverview()}>${f.point.back}<//>
              <h2 id="flow-running-h" class="flow-main-title">${f.run.label} <span class="mono muted">${runs.n}</span></h2>
            </header>
            <${RunningStrip} lane=${runs.loose} picked=${picked} bare s=${s} c=${c} />
            <${SessionCards} sessions=${runs.sessions} picked=${picked} s=${s} c=${c} />`
          : view === 'overview' ? html`<header class="flow-main-head"><h2 class="flow-main-title">${entered ? html`<${SideDot} side=${entered} />` : null}${name}</h2></header>
            ${grid ? html`<${PrioSource} order=${order} n=${all.length} /><${PrioGrid} sides=${sides} points=${all} s=${s} c=${c} />
              <p class="muted small flow-main-hint">${f.prio.hint}</p>`
              : !all.length ? html`<${Rest} s=${s} c=${c} />`
              : html`<${FlowOverview} key=${side} points=${queue} running=${runRows} picked=${picked} titleFor=${pointTitle} kindFor=${pointStandWord}
                band=${band} s=${s} c=${c} />`}
            ${all.length ? html`<div class="flow-dock"><${InstructLine} scope=${scope} s=${s} c=${c} /></div>` : null}`
          : null}
      </section>
      ${x ? html`<${FlowAside} x=${x} s=${s} c=${c} />` : null}
    </div>
  </div>`
}
