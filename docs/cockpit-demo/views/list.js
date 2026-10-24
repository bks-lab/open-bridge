// SPDX-License-Identifier: MIT
// The cockpit, the start page as one list (the view "List" in the settings, beside the bridge and the tiles).
// What needs you, each thing once and in the order you take it; the chosen numbers as a strip on top; the
// dates and the live feed beside it. No stage, no empty block: a block with nothing in it is not drawn.
// The rules every component keeps stand at the head of components.js.

import { html } from '../vendor/htm-preact-3.1.1.module.js'
import {
  duration, greetingPart, homeCatalog, homeChosen, homeListParts, homeProjects, homeRowQueue, indexRows, inProject, previewText, projectTone,
  short, stateToken, tickerStatusItems, untilText, upcomingEvents,
} from '../logic.js'
import { T, language } from '../text.js'
import { KindTag, RowBar } from './day.js'
import { jumpToTab, openWhole, returnsOf, shownTiles, ReturnCard, ReturnChip, PinStar } from './home.js'
import { Btn, Dot, Icon, PrioChip, StateLine } from './parts.js'
import { FeedLine, StagePrompt, leadOf, stationOf } from './stage.js'
import { TickerStatusList } from './ticker.js'

const DATES_MAX = 4

/** One chosen number in the strip: a station of the bridge as a small card; a quota carries its bar */
function Kpi({ x, st }) {
  const m = x.kind === 'quota' ? x.it.meter : null
  const fill = m ? Math.max(0, Math.min(1, m.value / m.max)) : 0
  return html`<button type="button" class=${`hl-kpi${st.tone ? ` tk-${st.tone}` : ''}${st.onClick ? '' : ' is-static'}`}
    onClick=${st.onClick ?? undefined} title=${[st.label, st.sub].filter(Boolean).join(' · ')}>
    <span class="hl-kpi-n num">${st.value}</span>
    <span class="hl-kpi-label">${short(st.label, 30)}</span>
    ${m ? html`<span class="hl-kpi-bar" aria-hidden="true"><span style=${{ transform: `scaleX(${fill.toFixed(4)})` }}></span>
      ${m.elapsed != null ? html`<i style=${{ left: `${(m.elapsed * 100).toFixed(1)}%` }}></i>` : null}</span>`
      : st.sub ? html`<span class="hl-kpi-sub">${short(st.sub, 34)}</span>` : null}
  </button>`
}

/** A tab as one line: its state, name, project and, with the preview on, the last line of its screen */
function TabLine({ tab, s, c, lead = false, preview = true }) {
  const t = T()
  const w = t.home.list
  const busy = !!s.ui.busy[tab.ref]
  // an idle tab rests; "waits" is kept for what waits on you
  const word = tab.state === 'waiting' ? w.rest : t.state[tab.state] ?? tab.state
  const last = preview || lead ? previewText(tab.last) : ''
  return html`<li class=${`hl-line st-${tab.state}${lead ? ' is-lead' : ''}`}>
    <span class="hl-line-mark"><${Dot} token=${stateToken(tab.state)} pulse=${tab.state === 'needs-you'} /></span>
    <button type="button" class="hl-line-main" onClick=${() => jumpToTab(s, c, tab.ref)} disabled=${busy} title=${t.home.openTab(tab.name)}>
      <span class="hl-line-title">${tab.name}</span>
      <span class="hl-line-sub">
        ${tab.workspace ? html`<span class=${`hl-proj tk-${projectTone(tab.workspace)}`}>${tab.workspace}</span>` : null}
        <span class="hl-kind">${w.tab}</span>
        <${StateLine} token=${stateToken(tab.state)} strong=${tab.state === 'needs-you'} word=${word} />
        <span class="mono muted">${duration(s.now - (tab.since_ms || s.now))}</span>
      </span>
      ${last ? html`<span class="hl-line-last mono">${short(last, lead ? 220 : 140)}</span>` : null}
    </button>
    <span class="hl-line-acts">
      <${Btn} size="xs" variant=${tab.state === 'needs-you' ? 'primary' : 'secondary'} busy=${busy} onClick=${() => jumpToTab(s, c, tab.ref)}>${t.home.toTab}<//>
      <${Btn} size="xs" variant="ghost" onClick=${() => c.openTabView(tab.ref)}>${t.home.view}<//>
    </span>
  </li>`
}

/** An inbox row or a task as one line: its state as a dot, priority, title, its number as a reference ("#3", what
 *  "3a" in the command box means), what it is, where it belongs, and the state of its tab
 *  when one works on it (that tab is not listed again); its actions on the right. `walk` hands over the
 *  queue of the page's rows, so its detail walks on */
function RowLine({ row, tab, s, c, lead = false, walk = null }) {
  const t = T()
  const w = t.home.list
  const n = s.model?.numbers?.[row.key] ?? row.number
  const project = row.area || row.area_names?.[0] || row.mark?.label || ''
  const why = (row.why ?? [])[0]
  const tabWord = tab ? (tab.state === 'waiting' ? w.rest : t.state[tab.state] ?? tab.state) : ''
  return html`<li class=${`hl-line${lead ? ' is-lead' : ''}`}>
    <span class="hl-line-mark"><${Dot} token=${row.priority === 'P0' ? 'danger' : tab?.state === 'needs-you' ? 'warning' : 'info'} /></span>
    <button type="button" class="hl-line-main" onClick=${e => openWhole(c, row, e.currentTarget, walk?.())} title=${t.home.openRow(short(row.title, 60))}>
      <span class="hl-line-title">${row.priority ? html`<${PrioChip} priority=${row.priority} /> ` : null}${short(row.title, lead ? 160 : 110)}</span>
      <span class="hl-line-sub">
        ${project ? html`<span class=${`hl-proj tk-${projectTone(project)}`}>${project}</span>` : null}
        ${n != null ? html`<span class="hl-num mono"><span class="sr-only">${t.numberLabel(n)}</span><span aria-hidden="true">#${n}</span></span>` : null}
        <${KindTag} row=${row} s=${s} />
        ${tab ? html`<${StateLine} token=${stateToken(tab.state)} strong=${tab.state === 'needs-you'} word=${w.onTab(tab.name, tabWord)} />` : null}
        ${why ? html`<span class="muted">${short(why, 70)}</span>` : null}
        <${ReturnChip} s=${s} rowKey=${row.key} />
      </span>
    </button>
    <span class="hl-line-acts"><${RowBar} row=${row} s=${s} c=${c} tab=${tab} pin=${false} /><${PinStar} rowKey=${row.key} s=${s} c=${c} /></span>
  </li>`
}

/** A block of lines with its title and count; nothing at all when it is empty. `fold` draws it closed,
 *  for what you rarely need (the tabs that rest) */
function Block({ id, title, count, more, onMore, fold = false, hint, children }) {
  if (!children?.length) return null
  const head = html`<h2 id=${id}>${title} <span class="sec-count mono">${count ?? children.length}</span>${hint ? html` <span class="hl-hint muted">${hint}</span>` : null}</h2>`
  if (fold) return html`<details class="hl-block is-quiet"><summary class="hl-block-head">${head}<${Icon} name="chevronDown" size=${14} /></summary>
    <ul class="hl-list" aria-labelledby=${id}>${children}</ul></details>`
  return html`<section class="hl-block" aria-labelledby=${id}>
    <header class="hl-block-head">${head}
      ${onMore ? html`<button type="button" class="btn-link home-more" onClick=${onMore}>${more}<${Icon} name="chevronRight" size=${14} /></button>` : null}</header>
    <ul class="hl-list">${children}</ul>
  </section>`
}

/** The dates still to come today and tomorrow, the first with how long until it */
function Dates({ s, c }) {
  const w = T().home.list
  const nowMs = s.now || Date.now()
  const end = new Date(nowMs)
  end.setHours(24 * 2, 0, 0, 0)
  const today = new Date(nowMs).toDateString()
  const list = upcomingEvents(s.model, nowMs, DATES_MAX).filter(x => x.ms < end.getTime())
  return html`<section class="hl-side-part" aria-labelledby="hl-dates">
    <h2 id="hl-dates" class="label-caps">${w.dates}</h2>
    ${list.length ? html`<ol class="hl-dates">${list.map((x, i) => html`<li key=${`${x.page}${x.section}${x.it.title}${x.ms}`}>
      <button type="button" class="hl-date" onClick=${() => c.openInfo(x.it, x.page, x.section)}>
        <span class="hl-date-when mono">${new Date(x.ms).toDateString() === today ? '' : `${w.tomorrow} `}${x.it.when}</span>
        <span class="hl-date-title">${x.it.title}</span>
        ${i === 0 ? html`<span class="hl-date-in muted small">${T().home.inTime(untilText(x.ms - nowMs))}</span>` : null}
      </button></li>`)}</ol>` : html`<p class="muted small">${w.noDates}</p>`}
  </section>`
}

/** What happened lately: the ticker's standing lines, then the feed */
function Live({ s, c }) {
  const w = T().home.list
  const feed = s.feed ?? []
  const standing = tickerStatusItems(s, s.now || Date.now()).length
  return html`<section class="hl-side-part" aria-labelledby="hl-live">
    <h2 id="hl-live" class="label-caps feed-head"><span class="feed-live" aria-hidden="true"></span>${w.live}</h2>
    <${TickerStatusList} s=${s} c=${c} />
    ${feed.length ? html`<ol class="feed-list">${feed.slice(0, 12).map(e => html`<${FeedLine} key=${`${e.kind}${e.key ?? e.ref ?? e.title}${e.at}`} e=${e} s=${s} c=${c} />`)}</ol>`
      : standing ? null : html`<p class="muted small">${w.quiet}</p>`}
  </section>`
}

export function HomeList({ s, c }) {
  const t = T()
  const h = t.home
  const w = h.list
  const lang = language()
  const now = new Date(s.now || Date.now())
  const tabsAll = (s.tabs?.tabs ?? []).filter(x => !x.is_control && x.state !== 'shell')
  const rowsOf = id => (s.model?.sections ?? []).find(x => x.id === id)?.rows ?? []
  const projects = homeProjects(tabsAll, [...rowsOf('now'), ...rowsOf('work').filter(r => r.task)])
  const project = projects.find(p => p.toLowerCase() === String(s.ui.homeProject ?? '').toLowerCase()) ?? null
  const catalog = homeCatalog(s.model, { workers: s.workers?.status !== 'none' })
  const chosen = homeChosen(s.model, s.home)
  const on = new Set(chosen)
  const byKey = indexRows(s.model)
  const parts = homeListParts(tabsAll, s.model, { project, pins: on.has('s:pinned') ? s.home?.pins ?? [] : [] })
  const backs = returnsOf(s).filter(r => r.live !== 'done' && (!project || inProject(byKey.get(r.key) ?? {}, project)))
  const strip = shownTiles(catalog, chosen)
  const preview = on.has('o:preview')
  const relayDown = s.relay?.enabled && !s.relay?.online
  const alarms = s.model?.alarms ?? []
  const person = s.server?.person
  const greeting = `${h.greeting[greetingPart(now.getHours())]}${person ? `, ${person}` : ''}`
  const day = now.toLocaleDateString(lang === 'de' ? 'de-DE' : 'en-GB', { weekday: 'long', day: 'numeric', month: 'long' })
  const workPage = (s.model?.pages ?? []).find(p => (p.sections ?? []).some(x => x.kind === 'tasks'))?.id ?? 'briefing'
  // read on the click: the queue is built below from the same lines
  const walk = () => queue
  const row = (r, lead = false) => html`<${RowLine} key=${r.key} row=${r} tab=${parts.tabOf(r.key)} s=${s} c=${c} lead=${lead} walk=${walk} />`
  const tab = (x, lead = false) => html`<${TabLine} key=${x.ref} tab=${x} s=${s} c=${c} lead=${lead} preview=${preview} />`

  // the one next step leads; the rest of what needs you follows: the tabs that ask, then the rows
  const lead = on.has('s:focus') && parts.lead ? (parts.lead.kind === 'tab' ? tab(parts.lead.tab, true) : row(parts.lead.row, true)) : null
  // with "Next up" off, its pick stands in line again where it belongs: a tab or an inbox row with what
  // waits on you, a task of the backlog first among the tasks
  const back = !lead ? parts.lead : null
  const backRow = back?.kind === 'row' ? back.row : null
  const backTask = backRow && !rowsOf('now').some(r => r.key === backRow.key) ? backRow : null
  const ask = on.has('s:waiting')
  const askingAll = ask ? [...(back?.kind === 'tab' ? [back.tab] : []), ...parts.asking] : []
  const waitingAll = ask ? [...(backRow && !backTask ? [backRow] : []), ...parts.waiting] : []
  const tasks = [...(backTask ? [backTask] : []), ...parts.tasks]
  const needs = [...(lead ? [lead] : []), ...askingAll.map(x => tab(x)), ...waitingAll.slice(0, 8).map(r => row(r))]
  const needsN = (lead ? 1 : 0) + askingAll.length + waitingAll.length
  // the rows in the order the page shows them: a row opened here walks on through them, as the lists do
  const queue = homeRowQueue([...(lead && parts.lead.kind === 'row' ? [parts.lead.row] : []), ...waitingAll,
    ...(on.has('s:pinned') ? parts.pinned : []), ...(on.has('s:tasks') ? tasks : [])])

  return html`<div class="col col-page home hl">
    <header class="hl-head">
      <div class="hl-hello">
        <p class="home-eyebrow">${day}</p>
        <${StagePrompt} s=${s} c=${c} greeting=${greeting} />
        ${s.model?.headline ? html`<p class="hl-lead muted">${leadOf(s.model)}</p>` : null}
      </div>
      <div class="hl-strip">
        ${strip.length ? html`<div class="hl-kpis">${strip.map(x => html`<${Kpi} key=${x.id} x=${x} st=${stationOf(x, s, c, chosen, project)} />`)}</div>` : null}
        <${Btn} size="xs" variant="ghost" icon="sliders" onClick=${() => c.setDrawer('customize')}>${w.customize}<//>
      </div>
      ${alarms.length || relayDown ? html`<div class="home-signals">
        ${alarms.map(a => html`<button type="button" class="home-signal tk-danger" key=${a.page_id + a.section_title}
          onClick=${() => c.setPage(a.page_id)}><${Dot} token="danger" /><span>${h.alarm(a.count, `${a.section_title} (${a.page_title})`)}</span></button>`)}
        ${relayDown ? html`<button type="button" class="home-signal tk-warning" onClick=${c.openClaude}><${Dot} token="warning" /><span>${h.controlOffline}</span></button>` : null}
      </div>` : null}
      ${projects.length > 1 ? html`<div class="home-chips" role="toolbar" aria-label=${h.projectsLabel}>
        <button type="button" class=${`home-chip${project ? '' : ' is-on'}`} aria-pressed=${String(!project)} onClick=${() => c.setHomeProject(null)}>${h.all}</button>
        ${projects.map(p => html`<button type="button" key=${p} class=${`home-chip${project === p ? ' is-on' : ''}`} aria-pressed=${String(project === p)}
          onClick=${() => c.setHomeProject(project === p ? null : p)}><span class=${`home-chip-dot tk-${projectTone(p)}`} aria-hidden="true"></span>${p}</button>`)}
      </div>` : null}
    </header>

    <div class="hl-main">
      <div class="hl-work">
        ${needs.length ? html`<${Block} id="hl-needs" title=${w.needsYou} count=${needsN}
          more=${h.seeAll(waitingAll.length)} onMore=${waitingAll.length > 8 ? () => c.setPage('briefing') : null}>${needs}<//>`
          : ask ? html`<p class="hl-clear"><${StateLine} token="success" strong word=${w.allClear} /></p>` : null}
        ${on.has('s:returns') ? html`<${Block} id="hl-backs" title=${w.withAi}>
          ${backs.slice(0, 6).map(r => html`<li class="hl-card-li" key=${r.key}><${ReturnCard} r=${r} s=${s} c=${c} /></li>`)}<//>` : null}
        ${on.has('s:continue') ? html`<${Block} id="hl-running" title=${w.running}>${parts.running.map(x => tab(x))}<//>` : null}
        ${on.has('s:pinned') ? html`<${Block} id="hl-pinned" title=${w.pinned}>${parts.pinned.map(r => row(r))}<//>` : null}
        ${on.has('s:tasks') ? html`<${Block} id="hl-tasks" title=${w.tasks} count=${tasks.length}
          more=${h.seeAll(tasks.length)} onMore=${tasks.length > 8 ? () => c.setPage(workPage) : null}>
          ${tasks.slice(0, 8).map(r => row(r))}<//>` : null}
        ${on.has('s:continue') ? html`<${Block} id="hl-resting" title=${w.resting} hint=${w.restHint} fold>${parts.resting.map(x => tab(x))}<//>` : null}
      </div>
      <aside class="hl-side">
        <${Dates} s=${s} c=${c} />
        <${Live} s=${s} c=${c} />
      </aside>
    </div>
  </div>`
}
