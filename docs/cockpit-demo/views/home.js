// SPDX-License-Identifier: MIT
// The cockpit, the start page.
// The rules every component keeps stand at the head of components.js.

import { html, useEffect, useRef, useState } from '../vendor/htm-preact-3.1.1.module.js'
import {
  attentionTabs, duration, indexRows, short, stateToken, canTab, previewText, workPageOf, homeCatalog, homeChosen,
  homeContinue, homeProjects, homeView, inProject, meterPace, projectTone, tabOfTask, countInProject, focusPick,
  nextEvent, untilText, liveStage, stageTone, homeRowQueue, RETURN_STAGES, greetingText, dayLabel, workPageId,
  rowProject,
} from '../logic.js'
import { T, language } from '../text.js'
import { RowBar, RowMeta } from './day.js'
import { DayPages, DayView } from './detail.js'
import { PageBadge } from './header.js'
import {
  AGENTS_PAGE, ASK_MAX, CHAT_PAGE, CHECK_PAGE, JEV_PAGE, SESSIONS_PAGE, SETTINGS_PAGE, START_PAGE, WORKERS_PAGE, briefingTitle,
  pageOrder,
} from './nav.js'
import { HomeFocusView } from './focus.js'
import { HomeList } from './list.js'
import { Btn, Dot, Empty, Icon, PrioChip, StateLine } from './parts.js'
import { BridgeStage, leadOf, stationOf } from './stage.js'
import { TickerBand, TickerStatusList } from './ticker.js'

// ---------------------------------------------------------------- the start page

/** The title of a page in the bar, fixed or from the profile */
export function pageTitleOf(s, id) {
  const t = T()
  const fixed = { briefing: briefingTitle(s), [SESSIONS_PAGE]: t.sessionsTab, [WORKERS_PAGE]: t.workersTab, [CHAT_PAGE]: t.chatTab,
    [AGENTS_PAGE]: t.agentsTab, [CHECK_PAGE]: t.reviewTab, [JEV_PAGE]: 'Jev', [SETTINGS_PAGE]: t.settings.title }
  return fixed[id] ?? (s.model?.pages ?? []).find(p => p.id === id)?.title ?? id
}

/** On the start page an object opens whole: an inbox item or a task in the wide drawer with every detail
 *  and action, over the page instead of beside it, so nothing on the page gets squeezed. Other rows have
 *  only the detail column. `queue` is the list it was opened from (logic.js homeRowQueue), so the foot of
 *  the detail walks on through it as the lists do */
export function openWhole(c, row, el, queue = null) {
  return /^(inbox|task):/.test(row.key) ? c.openItem(row.key, row, {}, null, queue) : c.peek(row.key, el, queue)
}

/** The starts handed to a tab, each with where it stands now */
export function returnsOf(s) {
  const now = s.now || Date.now()
  const tabs = s.tabs?.tabs ?? []
  return (s.model?.returns ?? []).map(r => ({ ...r, live: liveStage(r, tabs, now) }))
}

/** The steps of a start, the one it stands on lit; a lost start shows where it broke off */
function ReturnSteps({ stage }) {
  const h = T().home
  const at = RETURN_STAGES.indexOf(stage)
  return html`<ol class=${`rsteps${stage === 'lost' ? ' is-lost' : ''}`} aria-label=${h.returnStage[stage] ?? stage}>
    ${RETURN_STAGES.map((x, i) => html`<li key=${x} class=${i < at ? 'is-past' : i === at ? `is-now tk-${stageTone(x)}` : ''}>
      <span class="rstep-dot" aria-hidden="true"></span><span class="rstep-label">${h.returnStage[x]}</span></li>`)}
  </ol>`
}

/** One start in the return channel: what, how long ago, where it stands, the tab's last line, the answer,
 *  and the ways on: to the tab, its screen, the answer itself, taking it off the list */
export function ReturnCard({ r, s, c }) {
  const t = T()
  const h = t.home
  const ago = duration((s.now || Date.now()) - r.at_ms)
  const tab = (s.tabs?.tabs ?? []).find(x => x.ref === r.tab?.ref) ?? null
  const row = indexRows(s.model).get(r.key)
  // settled (its item closed, its task done) and its tab only waits: the tab can go
  const closable = r.live === 'done' && tab && !tab.is_control && tab.state === 'waiting' && canTab(s, 'close')
  return html`<article class=${`rcard tk-${stageTone(r.live)}`}>
    <header class="rcard-head">
      <span class="rcard-mode">${h.returnMode[r.mode] ?? r.mode}</span>
      <span class="mono muted small">${h.returnAgo(ago)}</span>
      <button type="button" class="btn-link inspect-close" title=${h.returnForget} aria-label=${h.returnForget}
        onClick=${() => c.act('return_forget', { key: r.key })}><${Icon} name="close" size=${14} /></button>
    </header>
    <button type="button" class="rcard-title" onClick=${e => (row ? openWhole(c, row, e.currentTarget) : null)} disabled=${!row}>${r.title}</button>
    <${ReturnSteps} stage=${r.live} />
    ${r.result?.text ? html`<p class="rcard-answer"><span class="label-caps">${h.returnAnswer}</span> ${short(r.result.text, 280)}</p>`
      : r.tab?.last || tab?.last ? html`<p class="rcard-last mono">${short(previewText(tab?.last ?? r.tab.last), 160)}</p>` : null}
    ${r.live === 'lost' ? html`<p class="rcard-answer"><span class="label-caps">${h.returnStage.lost}</span> ${h.returnLostHint}</p>` : null}
    ${closable ? html`<p class="small"><${StateLine} token="success" word=${h.returnSettled} /></p>` : null}
    <div class="hcard-acts">
      ${closable ? html`<${Btn} size="xs" variant="primary" busy=${!!s.ui.busy[tab.ref]}
        onClick=${() => c.act('tab_close', { tab_ref: tab.ref })}>${t.btnCloseTab}<//>` : null}
      ${r.result?.key ? html`<${Btn} size="xs" variant=${closable ? 'secondary' : 'primary'} onClick=${() => c.openItem(r.result.key, null)}>${h.returnOpenAnswer}<//>` : null}
      ${tab ? html`<${Btn} size="xs" variant=${r.result?.key || closable ? 'secondary' : 'primary'} onClick=${() => jumpToTab(s, c, tab.ref)}>${h.toTab}<//>
        <${Btn} size="xs" variant="ghost" onClick=${() => c.openTabView(tab.ref)}>${h.view}<//>` : null}
      ${!tab && row && r.live === 'lost' ? html`<${RowBar} row=${row} s=${s} c=${c} pin=${false} />` : null}
    </div>
  </article>`
}

/** The newest start of any of these rows in the return channel */
function returnFor(s, keys) {
  const want = new Set((Array.isArray(keys) ? keys : [keys]).filter(Boolean))
  return returnsOf(s).find(x => want.has(x.key)) ?? null
}

/** A chip on a card or a row: the agent is at it, it asks, or its answer came */
export function ReturnChip({ s, rowKey }) {
  const r = returnFor(s, rowKey)
  if (!r || r.live === 'done') return null
  return html`<span class=${`chip chip-tk tk-${stageTone(r.live)} rchip`}><${Dot} token=${stageTone(r.live)} pulse=${r.live === 'working'} />
    <span>${T().home.returnStage[r.live]}</span></span>`
}

/** The return channel inside a task or an inbox item: the steps, what the tab said last or its answer, and
 *  the ways on. Shown wherever the item opens, so its state is never only on the start page */
export function ReturnPanel({ s, c, keys }) {
  const h = T().home
  const r = returnFor(s, keys)
  if (!r) return null
  const tab = (s.tabs?.tabs ?? []).find(x => x.ref === r.tab?.ref) ?? null
  const ago = duration((s.now || Date.now()) - r.at_ms)
  return html`<section class=${`return-panel tk-${stageTone(r.live)}`} aria-label=${h.returnsTitle}>
    <header class="return-panel-head"><h3 class="label-caps">${h.returnsTitle}</h3>
      <span class="muted small">${h.returnMode[r.mode] ?? r.mode} · ${h.returnAgo(ago)}</span></header>
    <${ReturnSteps} stage=${r.live} />
    ${r.result?.text ? html`<p class="rcard-answer"><span class="label-caps">${h.returnAnswer}</span> ${r.result.text}</p>`
      : tab?.last || r.tab?.last ? html`<p class="rcard-last mono">${short(previewText(tab?.last ?? r.tab.last), 220)}</p>` : null}
    ${r.live === 'lost' ? html`<p class="rcard-answer">${h.returnLostHint}</p>` : null}
    <div class="hcard-acts">
      ${r.result?.key ? html`<${Btn} size="xs" variant="primary" onClick=${() => c.openItem(r.result.key, null)}>${h.returnOpenAnswer}<//>` : null}
      ${tab ? html`<${Btn} size="xs" variant=${r.result?.key ? 'secondary' : 'primary'} onClick=${() => jumpToTab(s, c, tab.ref)}>${h.toTab}<//>
        <${Btn} size="xs" variant="ghost" onClick=${() => c.openTabView(tab.ref)}>${h.view}<//>` : null}
    </div>
  </section>`
}

/** One click into a tab: the terminal brings it to the front where it can, else it opens large here */
export function jumpToTab(s, c, ref) {
  return canTab(s, 'focus') ? c.act('tab_jump', { tab_ref: ref }) : c.openTabView(ref)
}

/** A section of the start page: eyebrow title with its count, a link to the whole list, the cards */
function HomeShelf({ id, title, count, more, onMore, empty, children }) {
  return html`<section class="home-shelf" aria-labelledby=${id}>
    <header class="home-shelf-head">
      <h2 class="home-shelf-title" id=${id}>${title}${count != null ? html` <span class="sec-count mono">${count}</span>` : null}</h2>
      ${onMore ? html`<button type="button" class="btn-link home-more" onClick=${onMore}>${more}<${Icon} name="chevronRight" size=${14} /></button>` : null}
    </header>
    ${children?.length ? html`<div class="home-grid">${children}</div>` : html`<${Empty}>${empty}<//>`}
  </section>`
}

/** The star that pins a row to the start page, or takes it off */
export function PinStar({ rowKey, s, c }) {
  const h = T().home
  const on = (s.home?.pins ?? []).includes(rowKey)
  return html`<button type="button" class=${`pin-star${on ? ' is-on' : ''}`} aria-pressed=${String(on)}
    title=${on ? h.unpin : h.pin} aria-label=${on ? h.unpin : h.pin} onClick=${() => c.pin(rowKey, !on)}>${on ? '★' : '☆'}</button>`
}

/** The last lines of a tab's screen, read once through the terminal driver when the tab names none itself */
function useTabPreview(tab, c, on) {
  const [text, setText] = useState('')
  useEffect(() => {
    if (!on || previewText(tab.last)) return
    let live = true
    c.tabScreen(tab.ref).then(res => {
      if (!live || !res?.ok) return
      const lines = String(res.data?.text ?? '').split('\n').map(previewText).filter(Boolean)
      setText(lines.slice(-3).join(' · '))
    })
    return () => { live = false }
  }, [tab.ref, tab.since_ms, on])
  return previewText(tab.last) || text
}

/** An agent tab as a card: the band carries its project and the last lines of its screen, like a thumbnail */
function HomeTabCard({ tab, s, c, preview }) {
  const t = T()
  const age = duration(s.now - (tab.since_ms || s.now))
  const busy = !!s.ui.busy[tab.ref]
  const screen = useTabPreview(tab, c, preview)
  return html`<article class=${`hcard st-${tab.state}`}>
    <button type="button" class=${`hcard-thumb tk-${projectTone(tab.workspace)}`} title=${t.home.openTab(tab.name)}
      disabled=${busy} onClick=${() => jumpToTab(s, c, tab.ref)}>
      <span class="hcard-ws">${tab.workspace || '·'}</span>
      ${screen ? html`<span class="hcard-screen mono">${screen}</span>` : null}
      <span class="hcard-badge"><${StateLine} token=${stateToken(tab.state)} strong=${tab.state === 'needs-you'} word=${t.state[tab.state] ?? tab.state} /></span>
      <span class="hcard-age mono">${age}</span>
    </button>
    <div class="hcard-body">
      <h3 class="hcard-title clamp2">${tab.name}</h3>
      <div class="hcard-acts">
        <${Btn} size="xs" variant="primary" busy=${busy} onClick=${() => jumpToTab(s, c, tab.ref)}>${t.home.toTab}<//>
        <${Btn} size="xs" variant="ghost" onClick=${() => c.openTabView(tab.ref)}>${t.home.view}<//>
        ${tab.slug ? html`<${PinStar} rowKey=${`task:${tab.slug}`} s=${s} c=${c} />` : null}
      </div>
    </div>
  </article>`
}

/** A row as a card (waiting on you, a task): its number, title and meta; a click shows its detail beside
 *  the page, and a task with an agent tab leads straight into that tab; `queue` is the shelves' rows, so
 *  its detail walks on through them */
function HomeRowCard({ row, s, c, tab, big = false, queue = null }) {
  const t = T()
  const n = s.model?.numbers?.[row.key] ?? row.number
  const project = rowProject(row)
  return html`<article class=${`hcard hcard-row${big ? ' hcard-focus' : ''}`}>
    <div class="hcard-row-head">
      ${n != null ? html`<span class="hcard-num mono"><span class="sr-only">${t.numberLabel(n)}</span><span aria-hidden="true">${n}</span></span>` : null}
      ${project ? html`<span class=${`hcard-proj tk-${projectTone(project)}`}>${project}</span>` : null}
      <${PrioChip} priority=${row.priority} />
      <${ReturnChip} s=${s} rowKey=${row.key} />
      <span class="hcard-head-end"><${PinStar} rowKey=${row.key} s=${s} c=${c} /></span>
    </div>
    <button type="button" class="hcard-row-main" title=${t.home.openRow(short(row.title, 60))}
      onClick=${e => openWhole(c, row, e.currentTarget, queue)}>
      <span class=${`hcard-title ${big ? 'clamp2' : 'clamp3'}`}>${row.title}</span>
    </button>
    <${RowMeta} row=${row} s=${s} />
    <div class="hcard-acts">
      <${RowBar} row=${row} s=${s} c=${c} tab=${tab} pin=${false} />
    </div>
  </article>`
}

/** The one next step, large: a tab that asks you, else what waits on you first, else a P0 or P1 task */
function HomeFocus({ s, c, tabs }) {
  const h = T().home
  const pick = focusPick(tabs, s.model)
  return html`<section class="home-shelf" aria-labelledby="home-focus">
    <header class="home-shelf-head"><h2 class="home-shelf-title" id="home-focus">${h.focusTitle}</h2></header>
    ${!pick ? html`<${Empty}>${h.focusEmpty}<//>` : pick.kind === 'tab'
      ? html`<div class="home-focus"><${HomeTabCard} tab=${pick.tab} s=${s} c=${c} preview=${true} /></div>`
      : html`<div class="home-focus"><${HomeRowCard} row=${pick.row} s=${s} c=${c} tab=${tabOfTask(tabs, pick.row.task)} big /></div>`}
  </section>`
}

function HomeAsk({ s, c }) {
  const t = T()
  const [text, setText] = useState('')
  const busy = !!s.ui.busy['ask:free']
  const send = async e => {
    e.preventDefault()
    const v = text.trim()
    if (v && await c.ask('free', { text: v })) setText('')
  }
  return html`<form class="home-ask" onSubmit=${send} role="search">
    <${Icon} name="spark" size=${18} />
    <input type="text" class="home-ask-input" value=${text} onInput=${e => setText(e.currentTarget.value)}
      placeholder=${t.home.askPlaceholder} aria-label=${t.home.askPlaceholder} maxlength=${ASK_MAX} />
    <button type="submit" class="btn btn-primary btn-sm" disabled=${busy || !text.trim()} aria-busy=${busy ? 'true' : undefined}
      aria-label=${t.askSend}><${Icon} name="send" /></button>
  </form>`
}

/** A number for people: one decimal under ten, none above, the comma where the language has it */
export function pct(v, lang) {
  return v.toLocaleString(lang === 'de' ? 'de-DE' : 'en-GB', { maximumFractionDigits: v < 10 ? 1 : 0 })
}

/** A quota's last days as small bars against the budget line; today is the last bar */
export function DayBars({ days, budget, label }) {
  const top = Math.max(budget ?? 0, ...days.map(d => d.used), 1)
  return html`<span class="daybars" role="img" aria-label=${label}>
    ${budget ? html`<span class="daybars-budget" style=${{ bottom: `${(budget / top * 100).toFixed(1)}%` }}></span>` : null}
    ${days.map(d => html`<span key=${d.date} class=${`daybar${budget && d.used > budget ? ' is-over' : ''}`}
      style=${{ transform: `scaleY(${Math.max(0.02, d.used / top).toFixed(3)})` }} title=${`${d.date}: ${d.used} %`}></span>`)}
  </span>`
}

/** A quota as a dashboard tile: the label, the big number, the bar with where the time stands, and in
 *  words its share per day against the budget and where it ends at the reset; with "today" on, what it
 *  used today and on its last days. A click opens its detail */
function QuotaTile({ q, s, c, today }) {
  const t = T()
  const h = t.home
  const lang = language()
  const m = q.it.meter
  const pace = meterPace(m)
  const book = today ? s.model?.days?.quota?.[q.id] : null
  const label = q.label
  const tone = m.bad != null && m.value >= m.bad ? 'danger' : (m.warn != null && m.value >= m.warn) || pace?.over ? 'warning' : 'success'
  const fill = Math.max(0, Math.min(1, m.value / m.max))
  const overToday = book && pace?.budget && book.today > pace.budget
  return html`<button type="button" class=${`ktile ktile-quota tk-${tone}`} title=${h.openPage(label)}
    onClick=${() => c.openInfo(q.it, q.page, q.section)}>
    <span class="ktile-label">${label}</span>
    <span class="ktile-row">
      <span class="ktile-big num">${pct(m.value, lang)}<small> %</small></span>
      ${book ? html`<span class="ktile-today">
        <${StateLine} token=${overToday ? 'warning' : 'success'} strong word=${h.today(pct(book.today, lang))} />
        ${book.days.length > 1 ? html`<${DayBars} days=${book.days} budget=${pace?.budget} label=${h.lastDays} />` : null}
      </span>` : null}
    </span>
    <span class="ktile-bar" aria-hidden="true">
      <span class="ktile-fill" style=${{ transform: `scaleX(${fill.toFixed(4)})` }}></span>
      ${m.elapsed != null ? html`<span class="ktile-time" style=${{ left: `${(m.elapsed * 100).toFixed(1)}%` }}></span>` : null}
    </span>
    ${pace?.perDay != null ? html`<span class="ktile-line">
      <${StateLine} token=${pace.perDay > pace.budget ? 'warning' : 'success'} strong
        word=${`${h.perDay(pct(pace.perDay, lang))} · ${pace.perDay > pace.budget ? h.overBudget : h.inBudget}`} /></span>
      <span class="ktile-sub">${h.budget(pct(pace.budget, lang))}</span>` : null}
    ${pace ? html`<span class="ktile-sub">${h.projected(pct(pace.projected, lang))}</span>` : null}
    ${q.it.when ? html`<span class="ktile-sub muted">${h.reset(q.it.when)}</span>` : null}
  </button>`
}

/** A count as a dashboard tile: the big number, what it counts, what makes it up, and with "trend" on how
 *  it stood the day before; a click opens it */
function CountTile({ n, label, parts, tone, onClick, title, before, scope }) {
  const h = T().home
  const diff = before ? n - before.before : 0
  return html`<button type="button" class=${`ktile${tone ? ` tk-${tone}` : ''}`} onClick=${onClick} title=${title}>
    <span class="ktile-big num">${n}</span>
    <span class="ktile-label">${label}${scope ? html` <span class="muted">${h.inProject(scope)}</span>` : null}</span>
    ${before ? html`<span class=${`ktile-trend${diff > 0 ? ' is-up' : diff < 0 ? ' is-down' : ''}`}>
      ${diff > 0 ? '▲' : diff < 0 ? '▼' : '='} ${h.trend(before.before, diff)}</span>` : null}
    ${parts?.length ? html`<span class="ktile-parts">${parts.map(x => html`<span key=${x}>${x}</span>`)}</span>` : null}
  </button>`
}

/** What makes up a page's number: its largest sections, or for a page with findings where they are */
export function pageParts(s, p) {
  if (p.badge?.kind === 'bad') return (s.model?.alarms ?? []).filter(a => a.page_id === p.id).map(a => `${a.section_title} ${a.count}`)
  return (p.sections ?? []).filter(x => (x.total ?? x.count ?? 0) > 0)
    .sort((a, b) => (b.total ?? b.count) - (a.total ?? a.count)).slice(0, 3).map(x => `${x.title} ${x.total ?? x.count}`)
}

/** The next date as a tile: how long until it begins, its title and time; a click opens it */
function NextTile({ s, c }) {
  const h = T().home
  const next = nextEvent(s.model, s.now || Date.now())
  if (!next) return html`<${CountTile} n=${h.nextNoneShort} label=${h.nextNone} onClick=${() => {}} title=${h.nextNone} />`
  return html`<button type="button" class="ktile tk-secondary" title=${next.it.title}
    onClick=${() => c.openInfo(next.it, next.page, next.section)}>
    <span class="ktile-label muted">${h.nextTitle}</span>
    <span class="ktile-big ktile-big-sm num">${h.inTime(untilText(next.ms - (s.now || Date.now())))}</span>
    <span class="ktile-label clamp2">${next.it.title}</span>
    <span class="ktile-sub">${next.it.when}${next.it.detail ? ` · ${next.it.detail}` : ''}</span>
  </button>`
}

/** The tasks closed this week as a tile; a click shows them */
function DoneTile({ s }) {
  const h = T().home
  const [open, setOpen] = useState(false)
  const week = s.model?.week ?? { count: 0, items: [] }
  return html`<button type="button" class="ktile tk-success" aria-expanded=${String(open)} onClick=${() => setOpen(!open)}>
    <span class="ktile-big num">${week.count}</span>
    <span class="ktile-label">${h.doneTitle}</span>
    <span class="ktile-parts ktile-list">${(open ? week.items : week.items.slice(0, 3)).map(x => html`<span key=${x.slug}>${short(x.title, 48)}</span>`)}</span>
  </button>`
}

/** The name of a catalog entry, on the stage and in the settings */
export function catalogLabel(x) {
  const h = T().home
  if (x.kind === 'quota' || x.kind === 'page') return x.label
  return { 'c:waiting': h.waitingNow, 'c:tabs': h.tabsWaiting, 'c:next': h.nextTitle, 'c:done': h.doneTitle,
    's:focus': h.focusTitle, 's:pinned': h.pinnedTitle, 's:continue': h.continueTitle, 's:waiting': h.waitingTitle,
    's:tasks': h.tasksTitle, 's:starts': h.startTitle, 'o:today': h.optToday, 'o:preview': h.optPreview,
    'o:trend': h.optTrend, 'o:title': h.optTitle, 'o:project': h.optProject, 'o:classic': h.optClassic, 'o:list': h.optList, 'o:focusview': h.optFocusView, 'o:pulse': h.optPulse,
    'c:agents': h.agentsTitle, 'c:returns': h.returnsTitle, 's:returns': h.returnsTitle, 'c:workers': T().workersTab, 'k:scan': h.coreScan, 'k:brief': h.briefTitle }[x.id] ?? x.id
}

/** The tile of a catalog entry: a quota, a count, the next date, the week, a page. `hud` draws a quota as a ring */
function tileMaker(s, c, chosen, project, hud = false) {
  const t = T()
  const h = t.home
  const on = new Set(chosen)
  const counts = s.model?.counts ?? {}
  const before = on.has('o:trend') ? s.model?.days?.counts ?? {} : {}
  // with a project chosen and the option on, the counts count that project only (no trend: the day book is whole)
  const scope = on.has('o:project') && project ? project : null
  const tabs = s.tabs?.tabs ?? []
  const nowRows = (s.model?.sections ?? []).find(x => x.id === 'now')?.rows ?? []
  return x => {
    if (x.kind === 'quota') return html`<${QuotaTile} key=${x.id} q=${x} s=${s} c=${c} today=${on.has('o:today')} ring=${hud} />`
    if (x.id === 'c:next') return html`<${NextTile} key=${x.id} s=${s} c=${c} />`
    if (x.id === 'c:done') return html`<${DoneTile} key=${x.id} s=${s} />`
    if (x.id === 'c:waiting') {
      const n = scope ? countInProject(nowRows, scope) : counts.now ?? 0
      return html`<${CountTile} key=${x.id} n=${n} label=${h.waitingNow} tone=${n ? 'warning' : null} scope=${scope}
        before=${scope ? null : before[x.id]} title=${h.openPage(briefingTitle(s))} onClick=${() => c.setPage('briefing')} />`
    }
    if (x.id === 'c:tabs') {
      const n = scope ? tabs.filter(tb => tb.waiting && !tb.is_control && inProject(tb, scope)).length : counts.waiting_tabs ?? 0
      return html`<${CountTile} key=${x.id} n=${n} label=${h.tabsWaiting} tone=${n ? 'warning' : null} scope=${scope}
        before=${scope ? null : before[x.id]} parts=${!scope && counts.working_tabs ? [h.tabsWorking(counts.working_tabs)] : []}
        title=${t.tabsTitle} onClick=${() => c.setDrawer('tabs')} />`
    }
    const p = x.page
    if (!p) {
      // a count the stage draws as a station (returns, agents, workers) and that has no page of its own
      const st = stationOf(x, s, c, chosen, project)
      return html`<${CountTile} key=${x.id} n=${st.value} label=${st.label} tone=${st.tone}
        parts=${st.sub ? [st.sub] : []} title=${st.label} onClick=${st.onClick ?? undefined} />`
    }
    const bad = p.badge?.kind === 'bad'
    const n = scope ? countInProject((p.sections ?? []).flatMap(sec => sec.items ?? []), scope) : p.badge?.n ?? 0
    return html`<${CountTile} key=${x.id} n=${n} label=${bad && !scope ? `${p.title}: ${h.finding(n)}` : p.title} scope=${scope}
      tone=${bad ? 'danger' : p.badge?.warn ? 'warning' : null} parts=${scope ? [] : pageParts(s, p)} before=${scope ? null : before[x.id]}
      title=${h.openPage(p.title)} onClick=${() => c.setPage(p.id)} />`
  }
}

/** The tiles chosen, in their order */
export function shownTiles(catalog, chosen) {
  const byId = new Map(catalog.map(x => [x.id, x]))
  return chosen.map(id => byId.get(id)).filter(x => x && ['quota', 'count', 'page'].includes(x.kind))
}

function HomeOverview({ s, c, catalog, chosen, project }) {
  const h = T().home
  const shown = shownTiles(catalog, chosen)
  const tile = tileMaker(s, c, chosen, project)
  return html`<section class="home-shelf" aria-labelledby="home-overview">
    <header class="home-shelf-head"><h2 class="home-shelf-title" id="home-overview">${h.overviewTitle}</h2>
      <${Btn} size="xs" variant="ghost" icon="sliders" onClick=${() => c.setDrawer('customize')}>${h.choose}<//></header>
    ${shown.length ? html`<div class="kgrid">${shown.map(tile)}</div>` : html`<${Empty}>${h.chooseEmpty}<//>`}
  </section>`
}

// ---------------------------------------------------------------- the start page itself

/** The browser tab's title counts the agent tabs that wait on you, when that option is on */
export function useHomeTitle(s) {
  const base = useRef(null)
  const on = homeChosen(s.model, s.home).includes('o:title')
  const n = attentionTabs(s.tabs?.tabs).length
  useEffect(() => {
    if (base.current === null) base.current = document.title
    document.title = on && n ? `(${n}) ${base.current}` : base.current
  }, [on, n])
}

/** The start page in the view chosen: list and focus are pages of their own, the bridge and the tiles share one */
export function HomePage({ s, c }) {
  const view = homeView(homeChosen(s.model, s.home))
  if (view === 'list') return html`<${HomeList} s=${s} c=${c} />`
  if (view === 'focus') return html`<${HomeFocusView} s=${s} c=${c} />`
  return html`<${HomeBoard} s=${s} c=${c} />`
}

function HomeBoard({ s, c }) {
  const t = T()
  const h = t.home
  const lang = language()
  const tabs = s.tabs?.tabs ?? []
  const rowsOf = id => (s.model?.sections ?? []).find(x => x.id === id)?.rows ?? []
  const waitingAll = rowsOf('now')
  const tasksAll = rowsOf('work').filter(r => r.task)
  const projects = homeProjects(tabs, [...waitingAll, ...tasksAll])
  const project = projects.find(p => p.toLowerCase() === String(s.ui.homeProject ?? '').toLowerCase()) ?? null
  const cont = homeContinue(tabs, project)
  const waiting = waitingAll.filter(r => inProject(r, project))
  const tasks = tasksAll.filter(r => inProject(r, project))
  const now = new Date(s.now || Date.now())
  const day = dayLabel(now, lang)
  const person = s.server?.person
  const workPage = workPageId(s.model)
  const relayDown = s.relay?.enabled && !s.relay?.online
  const catalog = homeCatalog(s.model, { workers: s.workers?.status !== 'none' })
  const chosen = homeChosen(s.model, s.home)
  const on = new Set(chosen)
  const starts = pageOrder(s).filter(id => id !== START_PAGE && !on.has(`p:${id}`))
  const pageBadge = id => (s.model?.pages ?? []).find(p => p.id === id)?.badge
  const byKey = indexRows(s.model)
  const pinned = (s.home?.pins ?? []).map(k => byKey.get(k)).filter(Boolean).filter(r => inProject(r, project))
  const chips = projects.length > 1 ? html`<div class="home-chips" role="toolbar" aria-label=${h.projectsLabel}>
      <button type="button" class=${`home-chip${project ? '' : ' is-on'}`} aria-pressed=${String(!project)} onClick=${() => c.setHomeProject(null)}>${h.all}</button>
      ${projects.map(p => html`<button type="button" key=${p} class=${`home-chip${project === p ? ' is-on' : ''}`} aria-pressed=${String(project === p)}
        onClick=${() => c.setHomeProject(project === p ? null : p)}><span class=${`home-chip-dot tk-${projectTone(p)}`} aria-hidden="true"></span>${p}</button>`)}
    </div>` : null
  const backs = returnsOf(s).filter(r => inProject(byKey.get(r.key) ?? {}, project) || !project)
  // the row cards in the order the shelves show them: a card opened here walks on through them
  const queue = homeRowQueue([...(on.has('s:pinned') ? pinned : []), ...(on.has('s:waiting') ? waiting.slice(0, 6) : []),
    ...(on.has('s:tasks') ? tasks.slice(0, 8) : [])])
  // with a work tab the day lives here: dates, status, what happened today
  const daily = workPageOf(s.model?.pages) ? html`<${HomeShelf} id="home-day" title=${h.dayTitle} empty="">
      ${DayView({ s, c, cards: true })}
    <//>` : null
  // what happened today is long and read last, so it closes the page
  const diary = daily ? html`<${DayPages} s=${s} c=${c} shelf />` : null
  const shelves = html`
    ${on.has('s:returns') ? html`<${HomeShelf} id="home-returns" title=${h.returnsTitle} count=${backs.filter(r => r.live !== 'done').length} empty=${h.returnsEmpty}>
      ${backs.slice(0, 8).map(r => html`<${ReturnCard} key=${r.key} r=${r} s=${s} c=${c} />`)}
    <//>` : null}
    ${on.has('s:pinned') ? html`<${HomeShelf} id="home-pinned" title=${h.pinnedTitle} count=${pinned.length} empty=${h.pinnedEmpty}>
      ${pinned.map(row => html`<${HomeRowCard} key=${row.key} row=${row} s=${s} c=${c} tab=${tabOfTask(tabs, row.task)} queue=${queue} />`)}
    <//>` : null}
    ${on.has('s:continue') ? html`<${HomeShelf} id="home-continue" title=${h.continueTitle} count=${cont.length} empty=${h.continueEmpty}
      more=${h.seeAll(cont.length)} onMore=${cont.length > 8 ? () => c.setDrawer('tabs') : null}>
      ${cont.slice(0, 8).map(tab => html`<${HomeTabCard} key=${tab.ref} tab=${tab} s=${s} c=${c} preview=${on.has('o:preview')} />`)}
    <//>` : null}
    ${on.has('s:waiting') ? html`<${HomeShelf} id="home-waiting" title=${h.waitingTitle} count=${waiting.length} empty=${h.waitingEmpty}
      more=${h.seeAll(waiting.length)} onMore=${waiting.length > 6 ? () => c.setPage('briefing') : null}>
      ${waiting.slice(0, 6).map(row => html`<${HomeRowCard} key=${row.key} row=${row} s=${s} c=${c} tab=${tabOfTask(tabs, row.task)} queue=${queue} />`)}
    <//>` : null}
    ${on.has('s:tasks') ? html`<${HomeShelf} id="home-tasks" title=${h.tasksTitle} count=${tasks.length} empty=${h.tasksEmpty}
      more=${h.seeAll(tasks.length)} onMore=${tasks.length > 8 ? () => c.setPage(workPage) : null}>
      ${tasks.slice(0, 8).map(row => html`<${HomeRowCard} key=${row.key} row=${row} s=${s} c=${c} tab=${tabOfTask(tabs, row.task)} queue=${queue} />`)}
    <//>` : null}
    ${on.has('s:starts') && starts.length ? html`<section class="home-shelf" aria-labelledby="home-starts">
      <header class="home-shelf-head"><h2 class="home-shelf-title" id="home-starts">${h.startTitle}</h2></header>
      <nav class="home-starts" aria-labelledby="home-starts">
        ${starts.map(id => html`<button type="button" key=${id} class="home-start" onClick=${() => c.setPage(id)}>
          <span>${pageTitleOf(s, id)}</span>${pageBadge(id) ? html`<${PageBadge} badge=${pageBadge(id)} />` : null}
          <${Icon} name="chevronRight" size=${14} /></button>`)}
      </nav>
    </section>` : null}`
  // the bridge stage of the films is the start page; the tiles of before stay a choice ("classic")
  if (homeView(chosen) === 'stage') {
    return html`<div class=${`col col-page home bridge-home`}>
      <${BridgeStage} s=${s} c=${c} catalog=${catalog} chosen=${chosen} project=${project} />
      ${daily}
      ${chips}
      ${shelves}
      ${diary}
    </div>`
  }
  return html`<div class="col col-page home">
    <header class="home-hero">
      <p class="home-eyebrow">${day}</p>
      <h1 class="home-title">${greetingText(now.getHours(), person, h.greeting)}.</h1>
      ${s.model?.headline ? html`<p class="home-lead">${leadOf(s.model)}</p>` : null}
      <${HomeAsk} s=${s} c=${c} />
      ${(s.model?.alarms ?? []).length || relayDown ? html`<div class="home-signals">
        ${(s.model?.alarms ?? []).map(a => html`<button type="button" class="home-signal tk-danger" key=${a.page_id + a.section_title}
          onClick=${() => c.setPage(a.page_id)}><${Dot} token="danger" /><span>${h.alarm(a.count, `${a.section_title} (${a.page_title})`)}</span></button>`)}
        ${relayDown ? html`<button type="button" class="home-signal tk-warning" onClick=${c.openClaude}>
          <${Dot} token="warning" /><span>${h.controlOffline}</span></button>` : null}
      </div>` : null}
    </header>
    <${TickerBand} s=${s} c=${c} only="news" />
    <${TickerStatusList} s=${s} c=${c} />
    ${chips}
    ${on.has('s:focus') ? html`<${HomeFocus} s=${s} c=${c} tabs=${tabs} />` : null}
    <${HomeOverview} s=${s} c=${c} catalog=${catalog} chosen=${chosen} project=${project} />
    ${daily}
    ${shelves}
    ${diary}
  </div>`
}
