// SPDX-License-Identifier: MIT
// The cockpit, the start page as focus (the view "Focus" in the settings, beside bridge, tiles and list).
// Only the one next step, large, with what it is about; under it the bar every list walks with (back,
// where you stand, Next, keys n and p), the queue after it as cards; beside it today as a timeline from
// now to midnight and what the AI is doing.
// The rules every component keeps stand at the head of components.js.

import { html } from '../vendor/htm-preact-3.1.1.module.js'
import {
  duration, focusIndex, homeListParts, homeQueue, previewText, projectTone, short, stateToken, untilText,
  upcomingEvents, greetingText, dayLabel, workPageId, rowProject, tabStateKey
} from '../logic.js'
import { T, language } from '../text.js'
import { KindTag, OriginTag, RowBar } from './day.js'
import { jumpToTab, openWhole, returnsOf, PinStar, ReturnChip } from './home.js'
import { Btn, Dot, Icon, PrioChip, StateLine, WalkBar } from './parts.js'
import { StagePrompt } from './stage.js'

const AFTER_MAX = 6

/** What a queue entry is, in a word over its title: a tab, a row of the inbox (`now` holds their keys), a task */
function kindOf(x, now) {
  return x.kind === 'tab' ? 'tab' : now.has(x.row.key) ? 'row' : 'task'
}

/** The keys of the rows that wait on you */
function nowKeys(s) {
  return new Set(((s.model?.sections ?? []).find(x => x.id === 'now')?.rows ?? []).map(r => r.key))
}

function projectOf(x) {
  return x.kind === 'tab' ? x.tab.workspace : rowProject(x.row)
}

/** The last lines of a tab's screen, the way they stood */
function screenLines(text, n = 4) {
  return String(text ?? '').split('\n').map(previewText).filter(Boolean).slice(-n)
}

/** The one next step, large: its kind, its title, where it belongs, what it is about, and the way to act.
 *  The files view (dossier.js) shows its next step in it: `title` in place of the entry's own, `kindWord` in
 *  place of its kind, `sub` a line under the title (where the step comes from and since when) */
export function Hero({ x, n, tabOf, s, c, title = null, kindWord = null, sub = null }) {
  const t = T()
  const f = t.home.focus
  const kind = kindOf(x, nowKeys(s))
  const project = projectOf(x)
  const tab = x.kind === 'tab' ? x.tab : tabOf(x.id)
  const tone = x.kind === 'tab' || tab?.state === 'needs-you' ? 'warning' : x.row.priority === 'P0' ? 'danger' : 'accent'
  const lines = tab ? screenLines(tab.last) : []
  const why = x.kind === 'row' ? x.row.why ?? [] : []
  const open = el => (x.kind === 'tab' ? jumpToTab(s, c, x.tab.ref) : openWhole(c, x.row, el))
  return html`<article class=${`fx-hero tk-${tone}${n > 1 ? ' has-more' : ''}${n > 2 ? ' has-many' : ''}`} aria-labelledby="fx-title">
    <header class="fx-hero-top">
      <span class="fx-kind"><${Dot} token=${tone === 'accent' ? 'info' : tone} pulse=${kind === 'tab'} />${kindWord ?? f.kind[kind]}</span>
    </header>
    <h2 id="fx-title" class="fx-title">
      <button type="button" onClick=${e => open(e.currentTarget)}>${x.kind === 'row' && x.row.priority && title == null ? html`<${PrioChip} priority=${x.row.priority} /> ` : null}${title ?? (x.kind === 'tab' ? x.tab.name : x.row.title)}</button>
    </h2>
    ${sub ? html`<p class="fx-sub muted small">${sub}</p>` : null}
    <div class="fx-meta">
      ${x.kind === 'tab' ? null : html`<${KindTag} row=${x.row} s=${s} /><${OriginTag} row=${x.row} />`}
      ${project ? html`<span class=${`fx-proj tk-${projectTone(project)}`}>${project}</span>` : null}
      ${tab ? html`<${StateLine} token=${stateToken(tabStateKey(tab))} strong word=${x.kind === 'tab' ? t.state[tabStateKey(tab)] ?? tab.state : `${t.home.list.tab} ${tab.name}: ${t.state[tabStateKey(tab)] ?? tab.state}`} />
        <span class="mono muted">${duration(s.now - (tab.since_ms || s.now))}</span>` : null}
      ${x.kind === 'row' ? html`<${ReturnChip} s=${s} rowKey=${x.row.key} />` : null}
    </div>
    ${lines.length ? html`<pre class="fx-screen mono">${lines.join('\n')}</pre>` : null}
    ${why.length ? html`<ul class="fx-why">${why.slice(0, 4).map(w => html`<li key=${w}>${w}</li>`)}</ul>` : null}
    <footer class="fx-acts">
      <div class="fx-do">
        ${x.kind === 'tab' ? html`<${Btn} variant="primary" onClick=${() => jumpToTab(s, c, x.tab.ref)}>${t.home.toTab}<//>
          <${Btn} variant="secondary" onClick=${() => c.openTabView(x.tab.ref)}>${t.home.view}<//>`
          : html`<${RowBar} row=${x.row} s=${s} c=${c} tab=${tab} pin=${false} size="sm" /><${PinStar} rowKey=${x.row.key} s=${s} c=${c} />`}
      </div>
    </footer>
  </article>`
}

/** Nothing waits: a calm card, the way to the tasks, or with cockpit.focus_to_files into the files view of the
 *  work tab. The files view gives its own words and no way on (`action` false), since it stands there already */
export function Calm({ s, c, title = null, sub = null, action = true }) {
  const f = T().home.focus
  const workPage = workPageId(s.model)
  const files = !!s.work?.focus_to_files
  return html`<article class="fx-hero fx-calm tk-success">
    <span class="fx-calm-ring" aria-hidden="true"><${Icon} name="spark" size=${28} /></span>
    <h2 class="fx-title">${title ?? f.nothing}</h2>
    <p class="muted">${sub ?? (files ? f.nothingSubFiles : f.nothingSub)}</p>
    ${action ? html`<div class="fx-acts">${files ? html`<${Btn} variant="primary" icon="forward" onClick=${() => c.openFiles()}>${f.toFiles}<//>`
      : html`<${Btn} variant="secondary" onClick=${() => c.setPage(workPage)}>${f.toWork}<//>`}</div>` : null}
  </article>`
}

/** The queue after the step in front, a small card each, at most six; a click brings it to the front.
 *  `title` names the strip (the files view calls it Next), `kindWord` the word over a card */
export function After({ queue, i, onPick, s, title = null, kindWord = null }) {
  const f = T().home.focus
  const now = nowKeys(s)
  const rest = queue.map((x, k) => ({ x, k })).filter(({ k }) => k !== i).slice(0, AFTER_MAX)
  if (!rest.length) return null
  return html`<section class="fx-after" aria-labelledby="fx-after">
    <h2 id="fx-after" class="label-caps">${title ?? f.after} <span class="sec-count mono">${queue.length - 1}</span></h2>
    <ol class="fx-after-list">${rest.map(({ x, k }) => html`<li key=${x.id}>
      <button type="button" class=${`fx-card tk-${x.kind === 'tab' ? 'warning' : x.row.priority === 'P0' ? 'danger' : 'info'}`} onClick=${() => onPick(k)}>
        <span class="fx-card-n mono">${k + 1}</span>
        <span class="fx-card-kind">${kindWord ? kindWord(x) : f.kind[kindOf(x, now)]}</span>
        <span class="fx-card-title">${short(x.kind === 'tab' ? x.tab.name : x.row.title, 70)}</span>
        ${x.kind === 'tab' ? null : html`<span class="fx-card-tags"><${KindTag} row=${x.row} s=${s} /><${OriginTag} row=${x.row} /></span>`}
        ${projectOf(x) ? html`<span class=${`fx-proj tk-${projectTone(projectOf(x))}`}>${projectOf(x)}</span>` : null}
      </button></li>`)}</ol>
  </section>`
}

/** Today from now to midnight: a line with the hour of now on top and each date on it */
function Timeline({ s, c }) {
  const f = T().home.focus
  const lang = language()
  const nowMs = s.now || Date.now()
  const end = new Date(nowMs)
  end.setHours(24, 0, 0, 0)
  const list = upcomingEvents(s.model, nowMs, 8).filter(x => x.ms < end.getTime())
  const clock = ms => new Date(ms).toLocaleTimeString(lang === 'de' ? 'de-DE' : 'en-GB', { hour: '2-digit', minute: '2-digit' })
  return html`<section class="fx-side-part" aria-labelledby="fx-today">
    <h2 id="fx-today" class="label-caps">${f.today}</h2>
    <ol class="fx-line">
      <li class="fx-line-now"><span class="fx-line-time mono">${clock(nowMs)}</span><span class="fx-line-dot" aria-hidden="true"></span><b>${f.nowMark}</b></li>
      ${list.map((x, k) => html`<li key=${`${x.page}${x.it.title}${x.ms}`} class=${k === 0 ? 'is-next' : ''}>
        <span class="fx-line-time mono">${clock(x.ms)}</span><span class="fx-line-dot" aria-hidden="true"></span>
        <button type="button" onClick=${() => c.openInfo(x.it, x.page, x.section)}>
          <span>${x.it.title}</span>${k === 0 ? html`<small class="muted">${T().home.inTime(untilText(x.ms - nowMs))}</small>` : null}
        </button></li>`)}
      ${list.length ? null : html`<li class="fx-line-none muted small"><span></span><span class="fx-line-dot" aria-hidden="true"></span>${f.noDates}</li>`}
    </ol>
  </section>`
}

/** What the AI does meanwhile, three numbers, each leads to the tabs */
function Crew({ s, c }) {
  const f = T().home.focus
  const tabs = (s.tabs?.tabs ?? []).filter(x => !x.is_control && x.state !== 'shell')
  const results = returnsOf(s).filter(r => r.live === 'result').length
  const n = [['working', tabs.filter(x => x.state === 'working').length, 'info'],
    ['resting', tabs.filter(x => x.state === 'waiting').length, 'muted'], ['results', results, 'success']]
  return html`<section class="fx-side-part" aria-labelledby="fx-ai">
    <h2 id="fx-ai" class="label-caps">${f.ai}</h2>
    <div class="fx-crew">${n.map(([k, v, tone]) => html`<button type="button" key=${k} class=${`fx-crew-n tk-${tone}`} onClick=${() => c.setDrawer('tabs')}>
      <b class="num">${v}</b><span>${f[k]}</span></button>`)}</div>
  </section>`
}

/** The parts and the queue the focus walks, the same the page and the keys n and p read */
const focusParts = s => homeListParts(s.tabs?.tabs ?? [], s.model, { pins: s.home?.pins ?? [] })
export const focusQueue = s => homeQueue(focusParts(s))

/** The bar under the step in front, the one the lists have: back, where you stand, Next. `walk` moves
 *  (c.focusWalk on the start page, c.dossierWalk in the files view); `done` stands in place of the end line */
export function FocusWalk({ queue, i, s, c, walk = null, done = null }) {
  const t = T()
  // one step has no bar to walk; the way on (cockpit.focus_to_files) still stands under it
  if (queue.length < 2) return done ? html`<p class="fx-onward">${done}</p>` : null
  const go = walk ?? c.focusWalk
  const entry = k => {
    const x = queue[k]
    return { key: x.id, title: short(x.kind === 'tab' ? x.tab.name : x.row.title, 90),
      sub: x.kind === 'tab' ? x.tab.workspace : html`<${KindTag} row=${x.row} s=${s} />`,
      onOpen: () => go(x.id, k) }
  }
  const later = [i + 2, i + 3].filter(k => k < queue.length).map(entry)
  return html`<${WalkBar} label=${t.nextLabel} shortcuts=${s.ui.shortcuts} pos=${[i + 1, queue.length]}
    onPrev=${i > 0 ? () => go(queue[i - 1].id, i - 1) : null} next=${i + 1 < queue.length ? entry(i + 1) : null}
    later=${later} done=${done ?? t.nextDone} />`
}

export function HomeFocusView({ s, c }) {
  const h = T().home
  const now = new Date(s.now || Date.now())
  const person = s.server?.person
  const parts = focusParts(s)
  const queue = homeQueue(parts)
  // held by its id: a tab that starts asking moves to the front without changing the card; once the step
  // in front is settled, the next one moves up into its place (logic.js focusIndex)
  const i = focusIndex(queue, s.ui.focusAt)
  const day = dayLabel(now, language())
  // with cockpit.focus_to_files the end of the walk leads on into the files view of the work tab (n does too, app.js)
  const onward = s.work?.focus_to_files
    ? html`<button type="button" class="btn-link" onClick=${() => c.openFiles()}>${h.focus.toFiles}</button>` : null
  return html`<div class="col col-page home fx">
    <header class="fx-head">
      <p class="home-eyebrow">${day}</p>
      <${StagePrompt} s=${s} c=${c} greeting=${greetingText(now.getHours(), person, h.greeting)} />
    </header>
    <div class="fx-main">
      <div class="fx-work">
        <p class="fx-label label-caps">${h.focus.now}</p>
        ${queue.length ? html`<${Hero} key=${queue[i].id} x=${queue[i]} n=${queue.length} tabOf=${parts.tabOf} s=${s} c=${c} />
          <${FocusWalk} queue=${queue} i=${i} s=${s} c=${c} done=${onward} />` : html`<${Calm} s=${s} c=${c} />`}
        <${After} queue=${queue} i=${i} onPick=${k => c.focusWalk(queue[k].id, k)} s=${s} />
      </div>
      <aside class="fx-side">
        <${Timeline} s=${s} c=${c} />
        <${Crew} s=${s} c=${c} />
      </aside>
    </div>
  </div>`
}
