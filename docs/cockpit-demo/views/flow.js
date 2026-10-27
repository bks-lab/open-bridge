// SPDX-License-Identifier: MIT
// The cockpit, Work through: a view of the work tab (cockpit.flow.enabled, logic.js workViews 'flow'), laid out as cmux
// lays out a workspace. Left the themes the server's small model gives the open points across the areas, or the areas
// themselves (views/flowside.js FlowSide); over the card Focus or List, and in Focus the open points of the group
// picked as tabs, in the queue's fixed order (logic.js flowQueue: the return card after a jump to a tab, the tabs that
// ask, what an agent finished, a start that got lost, the questions for you; then what is in progress; then the tasks
// in review; the reports as one tab). The point in front stands as a card with its verbs (views/verbbar.js), held by
// its id (logic.js focusIndex) so the next one moves up after a decision; a point in progress says who works on it and
// since when (logic.js flowDrive), with To tab, View, Done, Later and Drop, and Let AI do it to go on where no tab
// works. Under the card the files view's walk bar (views/dossier.js Walk), and after the last point it leads to the
// next group where something is open. Right the details to pull in (views/flowside.js FlowDetails). List shows the
// group as rows with suggestions and a batch (views/flowlist.js). To tab remembers the jump (ui.flowJump, in memory
// only): once the page is in view again return_after_s later, the return card asks how it went (app.js). What the
// queue leaves out stands in a drawer with why; with nothing open the calm card offers up to three ideas to start.
// Without a terminal driver the cards of the agents and every way to a tab stay out.
// The agents' cards: a tab that asks carries the answers to its question (views/reply.js) and the decision guide
// (views/guide.js), each through the reply verbs that guard the tab; a finished or quiet start its result line and
// the criteria of its brief as a plain list to check yourself (no tick, nothing judges them), with Done and close
// the tab, Improve (words to the tab while it lives, else a new start) and Runs on. When a card comes to the front,
// the briefs of the next cards that miss one are written ahead (cockpit.flow.prep_ahead, c.flowPrep: one at a time,
// once per key), and points without a theme ask for theirs (c.flowThemesAuto, once per key). No title opens a drawer
// or another view. For the mouse: the page names no key.
// The rules every component keeps stand at the head of components.js.

import { html, useEffect, useState } from '../vendor/htm-preact-3.1.1.module.js'
import {
  canTab, duration, errorText, flowAction, flowDrive, flowDriver, flowMode, flowParts, flowQueue, flowSettings, flowSides, focusIndex,
  formatDay, isoDate, pointsIn, prepTargets, previewText, replySend, restSuggestions, short, stageTone, tabOfTask, themesToAsk, DAY,
} from '../logic.js'
import { T, language } from '../text.js'
import { WorkSwitch } from './day.js'
import { Segmented } from './detail.js'
import { Walk } from './dossier.js'
import { FlowList } from './flowlist.js'
import { FlowDetails, FlowSide, FlowTabs, sideName } from './flowside.js'
import { Calm, Hero } from './focus.js'
import { GuideTree } from './guide.js'
import { TAB_MSG_MAX } from './nav.js'
import { Btn, Dot } from './parts.js'
import { AskLine, TabReply } from './reply.js'
import { VerbBar } from './verbbar.js'

/** The last lines of a tab's screen, the way they stood */
const tailLines = (text, n = 4) => String(text ?? '').split('\n').map(previewText).filter(Boolean).slice(-n)

/** A card's title in the walk bar and the strip under it */
function cardTitle(x) {
  const f = T().flow
  if (x.kind === 'back') return f.back(x.jump.title)
  if (x.kind === 'start') return x.start.title
  if (x.kind === 'tab') return x.tab.name
  if (x.kind === 'reports') return f.reports(x.rows.length)
  return x.row.title
}

// the verbs on a card whose tab asks: no start, the tab takes no sentence while it asks (actions_work.py start_noted)
const ASKING_VERBS = ['advise', 'done', 'later', 'drop']

/** A card's kind in a word: its group, a quiet start by its stage */
const cardKind = x => T().flow.kind[x.stage === 'idle' ? 'idle' : x.group]

/** What a tab asks, answered on the card: the answers to its question as buttons (a dialog's options, yes and no,
 *  go on, a field) and the decision guide's steps. The card carries its own way to the tab (TabWays, which
 *  remembers the jump), so neither repeats it */
function AskBlock({ tab, s, c }) {
  if (!tab) return null
  return html`<div class="flow-askblock">
    <${TabReply} tab=${tab} s=${s} c=${c} compact noJump />
    <${GuideTree} tab=${tab} s=${s} c=${c} bare />
  </div>`
}

/** To tab and View for a tab of a card: the jump is remembered for the return card (c.flowJump) */
function TabWays({ tab, row, title, s, c }) {
  const f = T().flow
  if (!tab || !flowDriver(s)) return null
  return html`<${Btn} size="sm" variant="secondary" onClick=${() => c.flowJump({ key: row?.key ?? null, ref: tab.ref, title: title ?? tab.name })}>${f.toTab}<//>
    <${Btn} size="sm" variant="ghost" onClick=${() => c.openTabView(tab.ref)}>${f.view}<//>`
}

/** The return card: back from a tab the page jumped to, how did it go. Every answer forgets the jump */
function BackCard({ x, s, c }) {
  const f = T().flow
  const ago = duration((s.now || Date.now()) - x.jump.at)
  const back = () => c.flowBack()
  const rest = html`<${Btn} size="sm" variant="secondary" onClick=${back}>${f.runsOn}<//>
    <${Btn} size="sm" variant="ghost" onClick=${back}>${f.notYet}<//>`
  return html`<article class="fx-hero tk-info" aria-labelledby="flow-title">
    <header class="fx-hero-top"><span class="fx-kind"><${Dot} token="info" />${f.kind.back}</span><span class="mono muted small">${ago}</span></header>
    <h2 id="flow-title" class="fx-title">${f.back(x.jump.title)}</h2>
    <p class="flow-ask">${f.backAsk}</p>
    <footer class="fx-acts">${x.row
      ? html`<${VerbBar} row=${x.row} s=${s} c=${c} verbs=${['done', 'later', 'drop']} primary="done" onDone=${back} extra=${rest} />`
      : html`${x.jump.key ? html`<p class="muted small">${f.backGone}</p>` : null}<div class="fx-do">${rest}</div>`}</footer>
  </article>`
}

/** Improve on a finished card: what is still to do, as words to the tab while its agent waits there (tab_send
 *  through the reply guard), else as the sentence of a new start (do_it, never without one) */
function Improve({ row, tab, s, c, onDone }) {
  const t = T()
  const f = t.flow.improve
  const [text, setText] = useState('')
  const [note, setNote] = useState(null)
  const busy = !!s.ui?.busy?.[tab ? tab.ref : row.key]
  const v = text.trim()
  const go = async () => {
    if (!v) return
    setNote(null)
    if (tab) {
      const { verb, args } = replySend(tab, v)
      const r = await c.reply(verb, args)
      if (r?.refused) { setNote(errorText(r.error, t)); return }
      if (!r?.ok) { if (r?.note) setNote(r.note); return }
    } else {
      const a = flowAction('do', row, v)
      if (!a || !(await c.act(a.verb, a.args))?.ok) return
      c.flowDecided()
    }
    setText('')
    onDone?.()
  }
  const id = `flow-improve-${row.key}`
  return html`<div class="flow-improve verbbar-panel">
    <label class="label-caps" for=${id}>${tab ? f.toTab : f.anew}</label>
    <textarea id=${id} class="input textarea" rows="2" maxlength=${TAB_MSG_MAX} value=${text} onInput=${e => setText(e.currentTarget.value)}></textarea>
    <div class="verbbar-acts">
      <${Btn} size="sm" variant="primary" busy=${busy} disabled=${!v} onClick=${go}>${tab ? f.send : f.restart}<//>
      ${note ? html`<span class="small verbbar-err" role="status">${note}</span>` : null}
    </div>
  </div>`
}

/** A start of the return channel that wants you: its tab asks, it finished (or went quiet), or it got lost. One whose
 *  item is not in the list (put off, resting) has no verbs; finished or lost, it can still be taken off the list */
function StartCard({ x, s, c }) {
  const t = T()
  const f = t.flow
  const r = x.start
  const row = x.row
  const tab = x.tab
  const ago = duration((s.now || Date.now()) - r.at_ms)
  const lines = r.result?.text ? [] : tailLines(tab?.last ?? r.tab?.last)
  const tomorrow = isoDate((s.now || Date.now()) + DAY)
  const finished = x.group === 'result'
  const [fix, setFix] = useState(false)
  // words to the tab while its agent waits there, else a new start with them (a quiet tab is back at its shell)
  const live = !!tab && tab.state === 'waiting' && canTab(s, 'send')
  const criteria = finished ? (row?.card?.acceptance ?? []).filter(Boolean) : []
  const doneClose = async () => {
    const res = await c.act('settle', { keys: [row.key], outcome: 'done' })
    if (res?.ok && tab) await c.act('tab_close', { tab_ref: tab.ref })
  }
  const forget = html`<${Btn} size="sm" variant="ghost" onClick=${() => c.act('return_forget', { key: r.key })}>${t.home.returnForget}<//>`
  const acts = x.group === 'lost'
    ? (row ? html`<${VerbBar} row=${row} s=${s} c=${c} verbs=${['do', 'done', 'drop']} primary="do" words=${{ do: f.verbs.restart }} extra=${forget} />`
      : html`<div class="fx-do">${forget}</div>`)
    : html`${finished && row ? html`<div class="fx-do">
        ${tab ? html`<${Btn} size="sm" variant="primary" onClick=${doneClose}>${f.doneClose}<//>` : null}
        <${Btn} size="sm" variant="secondary" pressed=${fix} onClick=${() => setFix(!fix)}>${f.improve.button} ▾<//>
        <${Btn} size="sm" variant="secondary" onClick=${() => c.act('runs_on', { keys: [row.key], until: tomorrow })}>${f.runsOn}<//>
        ${r.result?.key ? html`<${Btn} size="sm" variant="ghost" onClick=${() => c.openItem(r.result.key, null)}>${t.home.returnOpenAnswer}<//>` : null}
      </div>
      ${fix ? html`<${Improve} row=${row} tab=${live ? tab : null} s=${s} c=${c} onDone=${() => setFix(false)} />` : null}` : null}
      ${x.group === 'asks' ? html`<${AskBlock} tab=${tab} s=${s} c=${c} />` : null}
      ${row ? html`<${VerbBar} row=${row} s=${s} c=${c} verbs=${finished ? (tab ? ['later', 'drop'] : ['done', 'later', 'drop']) : ASKING_VERBS}
        extra=${html`<${TabWays} tab=${tab} row=${row} title=${r.title} s=${s} c=${c} />`} />`
        : html`<div class="fx-do"><${TabWays} tab=${tab} row=${row} title=${r.title} s=${s} c=${c} />${finished ? forget : null}</div>`}`
  return html`<article class=${`fx-hero tk-${stageTone(x.stage === 'idle' ? 'result' : x.stage)}`} aria-labelledby="flow-title">
    <header class="fx-hero-top"><span class="fx-kind"><${Dot} token=${stageTone(x.stage === 'idle' ? 'result' : x.stage)} />${cardKind(x)}</span>
      <span class="mono muted small">${f.started(ago)}</span></header>
    <h2 id="flow-title" class="fx-title">${r.title}</h2>
    ${r.result?.text ? html`<p class="flow-answer"><span class="label-caps">${r.result.kind === 'note' ? f.result : t.home.returnAnswer}</span> ${short(r.result.text, 400)}</p>` : null}
    ${x.stage === 'idle' && !r.result?.text ? html`<p class="muted">${f.idleSub}</p>` : null}
    ${x.group === 'lost' ? html`<p class="muted">${f.lostSub}</p>` : null}
    ${x.group === 'asks' ? html`<${AskLine} tab=${tab} />` : null}
    ${lines.length && x.group !== 'asks' ? html`<pre class="fx-screen mono">${lines.join('\n')}</pre>` : null}
    ${criteria.length ? html`<section class="flow-criteria" aria-labelledby="flow-criteria">
      <h3 id="flow-criteria" class="label-caps">${f.criteria}</h3>
      <ul>${criteria.map((line, k) => html`<li key=${k}>${line}</li>`)}</ul>
    </section>` : null}
    <footer class="fx-acts">${acts}</footer>
  </article>`
}

/** The reports as one card: each folds open with its reasons and Seen, or all of them seen at once */
function ReportsCard({ x, s, c }) {
  const f = T().flow
  const keys = x.rows.map(r => r.key)
  return html`<article class="fx-hero tk-muted" aria-labelledby="flow-title">
    <header class="fx-hero-top"><span class="fx-kind"><${Dot} token="muted" />${f.kind.reports}</span></header>
    <h2 id="flow-title" class="fx-title">${f.reports(x.rows.length)}</h2>
    <ul class="flow-reports">${x.rows.map(r => html`<li key=${r.key}><details>
      <summary>${r.title}</summary>
      ${(r.why ?? []).length ? html`<ul class="fx-why">${r.why.slice(0, 4).map(w => html`<li key=${w}>${w}</li>`)}</ul>` : null}
      <div class="fx-do"><${Btn} size="xs" variant="secondary" busy=${!!s.ui.busy?.[r.key]}
        onClick=${() => c.act('settle', { keys: [r.key], outcome: 'done' })}>${f.seen}<//></div>
    </details></li>`)}</ul>
    <footer class="fx-acts"><div class="fx-do"><${Btn} size="sm" variant="primary" busy=${!!s.ui.busy?.[keys.join(',')]}
      onClick=${() => c.act('settle', { keys, outcome: 'done' })}>${f.allSeen}<//></div></footer>
  </article>`
}

/** The card in front, by its kind: a question or a task in the hero of the start page focus with the verbs, a tab
 *  that asks with its ways to the tab, a start, the return card, the reports */
function Card({ x, n, s, c }) {
  const f = T().flow
  const tabs = s.tabs?.tabs ?? []
  if (x.kind === 'back') return html`<${BackCard} x=${x} s=${s} c=${c} />`
  if (x.kind === 'start') return html`<${StartCard} x=${x} s=${s} c=${c} />`
  if (x.kind === 'reports') return html`<${ReportsCard} x=${x} s=${s} c=${c} />`
  if (x.kind === 'tab') {
    const acts = html`<${AskBlock} tab=${x.tab} s=${s} c=${c} />
      <div class="fx-do"><${TabWays} tab=${x.tab} row=${x.row} s=${s} c=${c} /></div>
      ${x.row ? html`<${VerbBar} row=${x.row} s=${s} c=${c} verbs=${ASKING_VERBS} />` : null}`
    return html`<${Hero} x=${{ kind: 'tab', id: x.tab.ref, tab: x.tab }} n=${n} tabOf=${() => null} s=${s} c=${c} kindWord=${f.kind.asks} openable=${false}
      sub=${x.tab.ask?.text ? short(x.tab.ask.text.split('\n').find(Boolean), 200) : null} acts=${acts} />`
  }
  const row = x.row
  const tab = row.task ? tabOfTask(tabs, row.task) : null
  const sub = x.task ? f.forTask(x.task.title) : null
  return html`<${Hero} x=${{ kind: 'row', id: row.key, row }} n=${n} tabOf=${() => tab} s=${s} c=${c} kindWord=${f.kind[x.group]} sub=${sub} openable=${false}
    acts=${html`<${VerbBar} row=${row} s=${s} c=${c} extra=${html`<${TabWays} tab=${tab} row=${row} title=${row.title} s=${s} c=${c} />`} />`} />`
}

/** What the queue leaves out, folded under one line: by why, each with its day when it was put off */
function LeftOut({ left }) {
  const f = T().flow
  const [open, setOpen] = useState(false)
  if (!left.total) return null
  const lang = language()
  return html`<section class="flow-left">
    <button type="button" class="btn-link" aria-expanded=${String(open)} onClick=${() => setOpen(!open)}>${f.left.button(left.total)} ${open ? '▾' : '▸'}</button>
    ${open ? html`<div class="flow-left-list" role="group" aria-label=${f.left.title}>${left.groups.map(g => html`<div key=${g.reason} class="flow-left-group">
      <p class="label-caps">${f.left.reason[g.reason]}</p>
      <ul>${g.rows.map(({ row, until }) => html`<li key=${row.key}>${short(row.title, 90)}${until ? html` <span class="muted small">${f.left.until(formatDay(until, lang))}</span>` : null}</li>`)}</ul>
    </div>`)}</div>` : null}
  </section>`
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

/** A point in progress: who works on it and since when (flowDrive), the last lines of its tab, To tab and View, and
 *  Done, Later until, Drop because; without a tab at work Let AI do it too, to go on with it (a start with a sentence,
 *  as the verb always sends) */
function DoingCard({ x, s, c }) {
  const t = T()
  const f = t.flow
  const d = flowDrive(x, s)
  const nowMs = s.now || Date.now()
  const row = x.row
  const ago = d.since_ms ? duration(nowMs - d.since_ms) : null
  const word = f.doing.stage[d.stage] ?? t.state[d.stage] ?? d.stage
  const who = d.by === 'tab' ? f.doing.tab(d.tab.name, word, ago) : d.by === 'start' ? f.doing.start(word, ago ?? '') : d.by === 'session'
    ? f.doing.session(d.tab?.name ?? '', ago) : f.doing.none(d.days)
  const lines = tailLines(d.tab?.last ?? x.start?.tab?.last, 6)
  const live = d.by !== 'none' && d.stage === 'working'
  const title = row?.title ?? x.title ?? x.start?.title ?? ''
  const token = d.by === 'none' ? 'muted' : stageTone(d.stage === 'needs-you' ? 'asks' : d.stage ?? 'working')
  return html`<article class=${`fx-hero tk-${token === 'muted' ? 'muted' : 'info'}`} aria-labelledby="flow-title">
    <header class="fx-hero-top"><span class="fx-kind"><${Dot} token=${token} pulse=${live} />${f.kind.doing}</span></header>
    <h2 id="flow-title" class="fx-title">${title}</h2>
    <p class="flow-who"><span class="label-caps">${f.doing.who}</span> ${who}</p>
    ${lines.length ? html`<pre class="fx-screen mono">${lines.join('\n')}</pre>` : null}
    <footer class="fx-acts">
      ${row ? html`<${VerbBar} row=${row} s=${s} c=${c} verbs=${live ? ['done', 'later', 'drop'] : ['do', 'done', 'later', 'drop']}
        primary=${live ? 'done' : 'do'} words=${live ? {} : { do: f.doing.goOn }}
        extra=${html`<${TabWays} tab=${d.tab} row=${row} title=${title} s=${s} c=${c} />`} />`
        : html`<div class="fx-do"><${TabWays} tab=${d.tab} row=${null} title=${title} s=${s} c=${c} /></div>`}
    </footer>
  </article>`
}

/** A point's title and its kind in a word, for the tabs, the walk and the list */
const pointTitle = x => (x.group === 'doing' ? x.row?.title ?? x.title ?? x.start?.title ?? x.tab?.name ?? '' : cardTitle(x))
const pointKind = x => (x.group === 'doing' ? T().flow.kind.doing : cardKind(x))

export function FlowPage({ s, c }) {
  const t = T()
  const f = t.flow
  const parts = flowParts(s)
  const all = flowQueue(parts, 'all')
  const mode = flowMode(s)
  const sides = flowSides(s, all, mode)
  const side = sides.some(x => x.id === s.ui.flowSide?.[mode]) ? s.ui.flowSide[mode] : 'all'
  const queue = pointsIn(all, side, s, mode)
  const i = focusIndex(queue, s.ui.flowAt)
  const x = queue[i] ?? null
  const driver = flowDriver(s)
  const show = s.ui.flowShow === 'list' ? 'list' : 'focus'
  const go = k => c.flowGo(queue[k].id, k)
  const decided = s.ui.flowDecided ?? 0
  const doing = parts.doing.length
  // after the last point of a theme or area: the next one below it where something is open
  const at = sides.findIndex(v => v.id === side)
  const nextSide = side === 'all' ? null : sides.slice(at + 1).find(v => v.id !== 'all' && v.open) ?? sides.slice(1, Math.max(1, at)).find(v => v.open)
  const onwards = nextSide ? { title: f.walk2.nextSide(sideName(nextSide, mode)), word: f.walk2.toSide, onGo: () => c.flowSide(nextSide.id) } : null
  // the card in front changed: the briefs of the next cards are written ahead, where one is missing or stale
  const ahead = flowSettings(s).prep_ahead
  useEffect(() => {
    const keys = prepTargets(queue, i, ahead, s)
    if (keys.length) c.flowPrep(keys)
  }, [x?.id, ahead])
  // the points without a theme get theirs when the view shows them, once per key on this page load (app.js)
  const ask = mode === 'themes' ? themesToAsk(all, s) : []
  useEffect(() => { if (ask.length) c.flowThemesAuto(ask) }, [ask.join(',')])
  return html`<div class="col col-page flow">
    <header class="page-head flow-head">
      <${WorkSwitch} s=${s} c=${c} />
      <p class="muted small">${[f.progress(doing, Math.max(0, all.length - doing)), decided ? f.decided(decided) : null].filter(Boolean).join(' · ')}</p>
    </header>
    ${driver ? null : html`<p class="flow-nodriver muted small">${f.noDriver}</p>`}
    <div class=${`flow-grid is-${show}`}>
      <${FlowSide} sides=${sides} side=${side} mode=${mode} points=${all} s=${s} c=${c} />
      <section class="flow-main" aria-label=${f.title}>
        <div class="flow-main-top">
          <${Segmented} label=${f.show.label} values=${[['focus', f.show.focus], ['list', f.show.list]]} current=${show} onPick=${v => c.flowShow(v)} />
          <span class="muted small">${f.tabs.count(queue.length)}</span>
        </div>
        ${show === 'list' ? html`<${FlowList} key=${side} points=${queue} s=${s} c=${c} titleFor=${pointTitle} />`
          : x ? html`<${FlowTabs} points=${queue} i=${i} titleFor=${pointTitle} kindFor=${pointKind} go=${go} s=${s} />
            <div class="flow-card" key=${x.id}>${x.group === 'doing' ? html`<${DoingCard} x=${x} s=${s} c=${c} />` : html`<${Card} x=${x} n=${queue.length} s=${s} c=${c} />`}</div>
            <${Walk} queue=${queue} i=${i} s=${s} c=${c} go=${go} words=${{ ...f.walk2, queue: t.dossier.walk.queue }} titleFor=${pointTitle}
              tagsOf=${() => null} whyOf=${pointKind} done=${f.walk2.last} onwards=${onwards} cls="flow-walk" />`
          : html`<${Rest} s=${s} c=${c} />`}
      </section>
      ${show === 'focus' ? html`<${FlowDetails} x=${x} s=${s} c=${c} />` : null}
    </div>
    <${LeftOut} left=${parts.leftOut} />
  </div>`
}
