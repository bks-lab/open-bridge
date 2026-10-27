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
// The card carries content only (round 3, nothing twice): its kind in its head (the state, the only place it stands),
// its title, what its tab asks with one set of answers, a start's result, the live tab's screen; who works on it is a
// field on the right, the criteria stand in Description. Under it the
// tabs of the point (views/flowtabs.js: Description, Steps, Activity, Related), then at the foot the instruction line
// (views/flowinstruct.js, cockpit.flow.instruct) over the files view's walk bar (views/dossier.js Walk), which after
// the last point leads to the first point of the next theme where something is open. Right, only while a point or an
// entry of Running now is open (round 6 B: the overview, a list and the grid take the width, their hint under them),
// what you can do and the fields (views/flowside.js FlowAside: the suggestion, the verbs, who works on it, the source).
// To tab remembers the jump (ui.flowJump, in memory only): once the page is in view again return_after_s later, the
// return card asks how it went (app.js). Round 4: every open row stands exactly once (logic.js flowParts). What runs
// stands in Running now (views/flowrun.js: one row on top of the left column that shows every entry in the middle as
// view `running`, since round 6 every live session there as a compact card, the entries of the side on top of the
// overview, never in the walk; a title opens one in the middle
// as view `run`, its card, its tabs and its instruction line, without the walk bar, its way back to the list it came
// from); what is no point now stands in Not now at the foot of the left column (views/flowleft.js), a group of it as a
// list in the middle (view `left`) with its own batch. Round 5: the left column lists no point, the middle does; what
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
// the server orders anew only on the day's first ask). No title opens a drawer or another view. For the mouse: the
// page names no key.
// The rules every component keeps stand at the head of components.js.

import { html, useEffect, useRef, useState } from '../vendor/htm-preact-3.1.1.module.js'
import {
  duration, flowDrive, flowDriver, flowMode, flowParts, flowQueue, flowSettings, flowSides, focusIndex, guideOf, instructScope, laneRows, pointsIn, runningOf,
  prepTargets, previewText, prioOn, restSuggestions, resultText, short, stageTone, tabOfTask, themesToAsk, workPageOf,
} from '../logic.js'
import { T } from '../text.js'
import { NoModel, WorkSwitch } from './day.js'
import { Walk } from './dossier.js'
import { LeftList } from './flowleft.js'
import { FlowOverview, listRows, walkOrder } from './flowlist.js'
import { PrioGrid, PrioSource } from './flowprio.js'
import { RunningStrip, SessionCards } from './flowrun.js'
import { FlowAside, FlowSide, SideDot, sideName } from './flowside.js'
import { InstructLine } from './flowinstruct.js'
import { PointTabs } from './flowtabs.js'
import { Calm, Hero } from './focus.js'
import { GuideTree } from './guide.js'
import { Btn, Dot } from './parts.js'
import { AskLine, TabReply } from './reply.js'
import { VerbBar } from './verbbar.js'

// the lines of a live tab's screen a card shows
const SCREEN_LINES = 12

/** The last lines of a tab's screen, the way they stood */
const tailLines = (text, n = SCREEN_LINES) => String(text ?? '').split('\n').map(previewText).filter(Boolean).slice(-n)

/** A card's title in the walk bar and the strip under it */
function cardTitle(x) {
  const f = T().flow
  if (x.kind === 'back') return f.back(x.jump.title)
  if (x.kind === 'start') return x.start.title
  if (x.kind === 'tab') return x.tab.name
  if (x.kind === 'reports') return f.reports(x.rows.length)
  return x.row.title
}

/** A card's kind in a word: its group, a quiet start by its stage */
const cardKind = x => T().flow.kind[x.stage === 'idle' ? 'idle' : x.group]

/** What a tab asks, answered on the card: the answers to its question as one row of buttons (a dialog's options, yes
 *  and no, go on, a field), and the decision guide's steps folded under one button, without the guide's own line what
 *  it is about (the card's title says it). The way to the tab stands on the right (views/flowside.js TabWays, which
 *  remembers the jump), so neither repeats it */
function AskBlock({ tab, s, c }) {
  const f = T().flow.guide
  const [open, setOpen] = useState(false)
  if (!tab) return null
  const guide = guideOf(s, tab).status !== 'off'
  return html`<div class="flow-askblock">
    <${TabReply} tab=${tab} s=${s} c=${c} compact noJump />
    ${guide ? html`<button type="button" class="btn-link flow-guide-toggle" aria-expanded=${String(open)} onClick=${() => setOpen(!open)}>${open ? f.hide : f.show}</button>` : null}
    ${guide && open ? html`<${GuideTree} tab=${tab} s=${s} c=${c} bare about=${false} />` : null}
  </div>`
}

/** The return card: back from a tab the page jumped to, how did it go. Its answers stand on the right; every one
 *  forgets the jump */
function BackCard({ x, s }) {
  const f = T().flow
  const ago = duration((s.now || Date.now()) - x.jump.at)
  return html`<article class="fx-hero tk-info" aria-labelledby="flow-title">
    <header class="fx-hero-top"><span class="fx-kind"><${Dot} token="info" />${f.kind.back}</span><span class="mono muted small">${ago}</span></header>
    <h2 id="flow-title" class="fx-title">${f.back(x.jump.title)}</h2>
    <p class="flow-ask">${f.backAsk}</p>
    ${!x.row && x.jump.key ? html`<p class="muted small">${f.backGone}</p>` : null}
  </article>`
}

/** A start of the return channel that wants you: its tab asks, it finished (or went quiet), or it got lost. The card
 *  says what came back (the result line, without its own head word) and what its tab asks; since when it runs is the
 *  field Who works on it, the criteria of its brief stand in Description, what to do with it stands on the right */
function StartCard({ x, s, c }) {
  const t = T()
  const f = t.flow
  const r = x.start
  const tab = x.tab
  const lines = r.result?.text ? [] : tailLines(tab?.last ?? r.tab?.last)
  return html`<article class=${`fx-hero tk-${stageTone(x.stage === 'idle' ? 'result' : x.stage)}`} aria-labelledby="flow-title">
    <header class="fx-hero-top"><span class="fx-kind"><${Dot} token=${stageTone(x.stage === 'idle' ? 'result' : x.stage)} />${cardKind(x)}</span></header>
    <h2 id="flow-title" class="fx-title">${r.title}</h2>
    ${r.result?.text ? html`<p class="flow-answer"><span class="label-caps">${r.result.kind === 'note' ? f.result : t.home.returnAnswer}</span> ${short(resultText(r.result.text), 400)}</p>` : null}
    ${x.stage === 'idle' && !r.result?.text ? html`<p class="muted">${f.idleSub}</p>` : null}
    ${x.group === 'lost' ? html`<p class="muted">${f.lostSub}</p>` : null}
    ${x.group === 'asks' ? html`<${AskLine} tab=${tab} />` : null}
    ${lines.length && x.group !== 'asks' ? html`<pre class="fx-screen mono">${lines.join('\n')}</pre>` : null}
    ${x.group === 'asks' ? html`<${AskBlock} tab=${tab} s=${s} c=${c} />` : null}
  </article>`
}

/** The reports as one card: each folds open with its reasons and Seen; all of them seen at once stands on the right */
function ReportsCard({ x, s, c }) {
  const f = T().flow
  return html`<article class="fx-hero tk-muted" aria-labelledby="flow-title">
    <header class="fx-hero-top"><span class="fx-kind"><${Dot} token="muted" />${f.kind.reports}</span></header>
    <h2 id="flow-title" class="fx-title">${f.reports(x.rows.length)}</h2>
    <ul class="flow-reports">${x.rows.map(r => html`<li key=${r.key}><details>
      <summary>${r.title}</summary>
      ${(r.why ?? []).length ? html`<ul class="fx-why">${r.why.slice(0, 4).map(w => html`<li key=${w}>${w}</li>`)}</ul>` : null}
      <div class="fx-do"><${Btn} size="xs" variant="secondary" busy=${!!s.ui.busy?.[r.key]}
        onClick=${() => c.act('settle', { keys: [r.key], outcome: 'done' })}>${f.seen}<//></div>
    </details></li>`)}</ul>
  </article>`
}

/** The card in front, by its kind, content only: a question or a task in the hero of the start page focus without its
 *  foot and without the facts the fields say, a tab that asks with its answers, a start, the return card, the reports */
function Card({ x, n, s, c }) {
  const f = T().flow
  const tabs = s.tabs?.tabs ?? []
  if (x.kind === 'back') return html`<${BackCard} x=${x} s=${s} />`
  if (x.kind === 'start') return html`<${StartCard} x=${x} s=${s} c=${c} />`
  if (x.kind === 'reports') return html`<${ReportsCard} x=${x} s=${s} c=${c} />`
  if (x.kind === 'tab') {
    return html`<${Hero} x=${{ kind: 'tab', id: x.tab.ref, tab: x.tab }} n=${n} tabOf=${() => null} s=${s} c=${c} kindWord=${f.kind.asks} openable=${false}
      foot=${false} facts=${false} screen=${SCREEN_LINES} sub=${x.tab.ask?.text ? short(x.tab.ask.text.split('\n').find(Boolean), 200) : null}>
      <${AskBlock} tab=${x.tab} s=${s} c=${c} />
    <//>`
  }
  const row = x.row
  const tab = row.task ? tabOfTask(tabs, row.task) : null
  const sub = x.task ? f.forTask(x.task.title) : null
  return html`<${Hero} x=${{ kind: 'row', id: row.key, row }} n=${n} tabOf=${() => tab} s=${s} c=${c} kindWord=${f.kind[x.group]} sub=${sub} openable=${false}
    foot=${false} facts=${false} screen=${SCREEN_LINES} />`
}

/** Nothing open: the calm card, and up to three ideas or backlog tasks to start, each with Let AI do it */
function Rest({ s, c }) {
  const f = T().flow
  const ideas = restSuggestions(s, 3)
  return html`<${Calm} s=${s} c=${c} title=${f.rest.title} sub=${f.rest.sub} action=${false} />
    <section class="flow-rest" aria-labelledby="flow-rest">
      <h2 id="flow-rest" class="label-caps">${f.rest.suggest}</h2>
      ${ideas.length ? html`<ul>${ideas.map(row => html`<li key=${row.key}><span class="flow-rest-title">${short(row.title, 90)}</span>
        <${VerbBar} row=${row} s=${s} c=${c} verbs=${['do']} primary="do" /></li>`)}</ul>` : html`<p class="muted small">${f.rest.none}</p>`}
    </section>`
}

// a word of a list as the start of a sentence
const upFirst = t => (t ? t[0].toUpperCase() + t.slice(1) : t)

/** A point in progress, or an entry of Running now: its state in its head (its dot pulses while an agent works on it,
 *  logic.js flowDrive) and the last lines of that tab's screen. Who works on it and since when is a field on the right,
 *  where its verbs stand too */
function DoingCard({ x, s }) {
  const f = T().flow
  const d = flowDrive(x, s)
  const row = x.row
  const lines = tailLines(d.tab?.last ?? x.start?.tab?.last)
  const live = d.by !== 'none' && (d.stage === 'working' || d.stage === 'started')
  const title = row?.title ?? x.title ?? x.start?.title ?? ''
  const token = d.by === 'none' ? 'muted' : stageTone(d.stage === 'needs-you' ? 'asks' : d.stage ?? 'working')
  // an entry of Running now says so in its head with its stage, and why it stands there and not as a point
  const kind = x.lane ? [f.run.label, f.doing.stage[d.stage] ?? d.stage].filter(Boolean).join(' · ') : f.kind.doing
  return html`<article class=${`fx-hero tk-${token === 'muted' ? 'muted' : 'info'}`} aria-labelledby="flow-title">
    <header class="fx-hero-top"><span class="fx-kind"><${Dot} token=${token} pulse=${live} />${kind}</span></header>
    <h2 id="flow-title" class="fx-title">${title}</h2>
    ${x.lane ? html`<p class="muted small">${[upFirst(f.run.how[x.how]), f.run.cardWhy].filter(Boolean).join('. ')}</p>` : null}
    ${lines.length ? html`<pre class="fx-screen mono">${lines.join('\n')}</pre>` : null}
  </article>`
}

/** Brings the top of the middle back into the page column where it scrolled up out of sight: the column that
 *  scrolls is the page's (.col), on a narrow screen the window */
function intoView(el) {
  if (!el?.getBoundingClientRect || !el.scrollIntoView) return
  const col = el.closest?.('.col')?.getBoundingClientRect?.()
  if (el.getBoundingClientRect().top < Math.max(0, col?.top ?? 0) - 1) el.scrollIntoView({ block: 'start' })
}

/** A point's title and its kind in a word, for the tabs, the walk and the list */
const pointTitle = x => (x.group === 'doing' ? x.row?.title ?? x.title ?? x.start?.title ?? x.tab?.name ?? '' : cardTitle(x))
const pointKind = x => (x.group === 'doing' ? T().flow.kind.doing : cardKind(x))

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
  const runs = runningOf(parts)
  const i = focusIndex(queue, s.ui.flowAt)
  // the middle: the point open, an entry of Running now, a group of Not now, else the overview; what went (a point
  // decided, a start that finished, a group emptied) falls back to the overview
  const running = s.ui.flowView === 'run' ? parts.lane.find(e => e.id === s.ui.flowRunId) ?? null : null
  const group = s.ui.flowView === 'left' ? parts.leftOut.groups.find(g => g.reason === s.ui.flowLeft) ?? null : null
  const view = running ? 'run' : group ? 'left' : s.ui.flowView === 'running' && runs.n ? 'running'
    : s.ui.flowView === 'point' && queue.length ? 'point' : 'overview'
  const x = view === 'point' ? queue[i] ?? null : view === 'run' ? running : null
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
  // new order is Ask Jev again's click (round 6 B)
  const work = prioOn(s) ? workPageOf(s.model?.pages) : null
  const order = work ? s.jevOrder?.[work.id] : null
  useEffect(() => { if (work && order === undefined) c.flowPrioOrder(work.id) }, [work?.id, order === undefined])
  const name = sideName(entered, mode)
  // what the instruction line speaks for: the point or the entry open, else the ticked points or every point of the side
  const scope = view === 'left' ? null : instructScope(x, queue, picked, entered ? name : null, s)
  const counts = parts.counts
  const grid = mode === 'prio' && !entered
  // what opens in the middle comes into view: its top scrolled up out of the page column is brought back (round 5)
  const main = useRef(null)
  useEffect(() => { requestAnimationFrame(() => intoView(main.current)) }, [view, group?.reason, running?.id, side, view === 'point' ? x?.id : null])
  // back from an entry of Running now: to the list it was opened from (ui.flowRunFrom), else to the overview
  const fromRunning = view === 'run' && s.ui.flowRunFrom === 'running'
  const card = x ? (x.group === 'doing' ? html`<${DoingCard} x=${x} s=${s} />` : html`<${Card} x=${x} n=${queue.length} s=${s} c=${c} />`) : null
  return html`<div class="col col-page flow">
    <header class="page-head flow-head">
      <${WorkSwitch} s=${s} c=${c} />
      <p class="muted small">${[f.count(counts.points, runs.n, counts.left), decided ? f.decided(decided) : null].filter(Boolean).join(' · ')}</p>
    </header>
    ${driver ? null : html`<p class="flow-nodriver muted small">${f.noDriver}</p>`}
    <div class=${`flow-grid${x ? '' : ' no-aside'}`}>
      <${FlowSide} sides=${sides} entered=${entered} mode=${mode} all=${all} view=${view} running=${runs} left=${parts.leftOut}
        run=${running?.id ?? null} open=${group?.reason ?? null} s=${s} c=${c} />
      <section class=${`flow-main${x ? ' is-point' : ''}`} aria-label=${f.title} ref=${main}>
        ${view === 'left' ? html`<${LeftList} key=${group.reason} group=${group} s=${s} c=${c} /><p class="muted small flow-main-hint">${f.notnow.hint}</p>`
          : view === 'running' ? html`<header class="flow-main-head">
              <${Btn} size="sm" variant="secondary" icon="back" cls="flow-back" onClick=${() => c.flowOverview()}>${f.point.back}<//>
              <h2 id="flow-running-h" class="flow-main-title">${f.run.label} <span class="mono muted">${runs.n}</span></h2>
            </header>
            <${RunningStrip} lane=${runs.loose} picked=${picked} bare s=${s} c=${c} />
            <${SessionCards} sessions=${runs.sessions} picked=${picked} s=${s} c=${c} />`
          : view === 'run' ? html`<header class="flow-main-head">
              <${Btn} size="sm" variant="secondary" icon="back" cls="flow-back" onClick=${() => (fromRunning ? c.flowRunning() : c.flowOverview())}>${fromRunning ? f.run.back : f.point.back}<//>
              <span class="flow-main-theme muted">${f.run.label}</span>
            </header>
            <div class="flow-point">
              <div class="flow-card" key=${x.id}>${card}</div>
              <${PointTabs} x=${x} s=${s} c=${c} />
            </div>
            <div class="flow-dock"><${InstructLine} key=${x.id} scope=${scope} s=${s} c=${c} /></div>`
          : view === 'overview' ? html`<header class="flow-main-head"><h2 class="flow-main-title">${entered ? html`<${SideDot} side=${entered} />` : null}${name}</h2></header>
            <${RunningStrip} lane=${lane} picked=${picked} s=${s} c=${c} />
            ${grid ? html`<${PrioSource} order=${order} n=${all.length} /><${PrioGrid} sides=${sides} points=${all} s=${s} c=${c} />
              <p class="muted small flow-main-hint">${f.prio.hint}</p>`
              : !all.length ? html`<${Rest} s=${s} c=${c} />`
              : html`<${FlowOverview} key=${side} points=${queue} running=${runRows} picked=${picked} titleFor=${pointTitle} kindFor=${pointKind}
                band=${band} s=${s} c=${c} />`}
            ${all.length ? html`<div class="flow-dock"><${InstructLine} scope=${scope} s=${s} c=${c} /></div>` : null}`
          : html`<header class="flow-main-head">
              <${Btn} size="sm" variant="secondary" icon="back" cls="flow-back" onClick=${() => c.flowOverview()}>${f.point.back}<//>
              <span class="flow-main-theme muted">${name}</span>
            </header>
            ${picked.size ? html`<div class="flow-picked-line"><span class="muted small">${f.point.ticked(picked.size)}</span>
              <${Btn} size="sm" variant="secondary" onClick=${() => c.flowOverview()}>${f.point.see}<//></div>` : null}
            <div class="flow-point">
              <div class="flow-card" key=${x.id}>${card}</div>
              <${PointTabs} x=${x} s=${s} c=${c} />
            </div>
            <div class="flow-dock">
              <${InstructLine} key=${x.id} scope=${scope} s=${s} c=${c} />
              <${Walk} queue=${queue} i=${i} s=${s} c=${c} go=${go} words=${{ ...f.walk2, queue: t.dossier.walk.queue }} titleFor=${pointTitle}
                tagsOf=${() => null} whyOf=${pointKind} done=${f.walk2.last} onwards=${onwards} cls="flow-walk" />
            </div>`}
      </section>
      ${x ? html`<${FlowAside} x=${x} s=${s} c=${c} />` : null}
    </div>
  </div>`
}
