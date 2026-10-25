// SPDX-License-Identifier: MIT
// The cockpit, the bridge stage on the start page (the explainer films' picture).
// The rules every component keeps stand at the head of components.js.

import { html, useEffect, useRef, useState } from '../vendor/htm-preact-3.1.1.module.js'
import {
  duration, indexRows, sessionCounts, short, stateToken, workerTone, homeContinue, inProject, meterPace, tabOfTask,
  countInProject, focusPick, nextEvent, untilText, STAGE, stageDust, stageSpots, speechError, pulseSpeed,
  MAX_STATIONS, situation, situationText, parseVerdict, tickerStatusItems, homeRowQueue, greetingText, dayLabel, tabStateKey,
  itemRow, workPageOf,
} from '../logic.js'
import { flash } from '../motion.js'
import { T, language } from '../text.js'
import { ChatThread, Thinking, useQuickLive } from './chat.js'
import { KindTag, OriginTag, RowBar } from './day.js'
import {
  DayBars, PinStar, ReturnCard, ReturnChip, jumpToTab, openWhole, pageParts, pageTitleOf, pct, returnsOf, shownTiles,
} from './home.js'
import { AGENTS_PAGE, ASK_MAX, SESSIONS_PAGE, WORKERS_PAGE, briefingTitle } from './nav.js'
import { Btn, Dot, Icon, StateLine } from './parts.js'
import { TickerBand, TickerStatusList } from './ticker.js'

// ---------------------------------------------------------------- the bridge stage (the explainer films' picture)

/** A station of the stage: what a chosen tile says, short enough to hang on a link */
export function stationOf(x, s, c, chosen, project) {
  const t = T()
  const h = t.home
  const lang = language()
  const on = new Set(chosen)
  const counts = s.model?.counts ?? {}
  const scope = on.has('o:project') && project ? project : null
  const before = on.has('o:trend') && !scope ? s.model?.days?.counts ?? {} : {}
  const trend = (id, n) => before[id] ? h.trend(before[id].before, n - before[id].before) : ''
  const tabs = s.tabs?.tabs ?? []
  if (x.kind === 'quota') {
    const m = x.it.meter
    const pace = meterPace(m)
    const book = on.has('o:today') ? s.model?.days?.quota?.[x.id] : null
    const tone = m.bad != null && m.value >= m.bad ? 'danger' : (m.warn != null && m.value >= m.warn) || pace?.over ? 'warning' : 'success'
    const sub = [book ? h.today(pct(book.today, lang)) : null, pace?.perDay != null ? h.perDay(pct(pace.perDay, lang)) : null].filter(Boolean).join(' · ')
    return { id: x.id, label: x.label, value: `${pct(m.value, lang)} %`, sub, tone, onClick: () => c.openInfo(x.it, x.page, x.section) }
  }
  if (x.id === 'c:next') {
    const next = nextEvent(s.model, s.now || Date.now())
    return next ? { id: x.id, label: next.it.title, value: h.inTime(untilText(next.ms - (s.now || Date.now()))), sub: next.it.when, tone: 'info',
      onClick: () => c.openInfo(next.it, next.page, next.section) } : { id: x.id, label: h.nextTitle, value: h.nextNoneShort, sub: '', tone: null, onClick: null }
  }
  if (x.id === 'c:done') {
    const week = s.model?.week ?? { count: 0, items: [] }
    return { id: x.id, label: h.doneTitle, value: String(week.count), sub: week.items[0] ? short(week.items[0].title, 30) : '', tone: 'success', onClick: null }
  }
  if (x.id === 'c:returns') {
    const list = returnsOf(s).filter(r => r.live !== 'done')
    const count = st => list.filter(r => r.live === st).length
    const tone = count('lost') ? 'danger' : count('asks') ? 'warning' : count('result') ? 'success' : list.length ? 'info' : null
    return { id: x.id, label: h.returnsTitle, value: String(list.length),
      sub: [count('result') ? h.returnCount.result(count('result')) : null, count('asks') ? h.returnCount.asks(count('asks')) : null,
        count('working') ? h.returnCount.working(count('working')) : null, count('lost') ? h.returnCount.lost(count('lost')) : null].filter(Boolean).join(' · '),
      tone, onClick: null }
  }
  if (x.id === 'c:agents') {
    const sessions = s.sessions?.sessions ?? []
    const n = sessionCounts(s.sessions?.sessions).agents
    // the station counts your sessions; how many subagents run in them is its small line (the other
    // Bridges, A2A, have their own tab and are not counted here)
    return { id: x.id, label: h.agentsTitle, value: String(sessions.length), sub: n ? h.agentsLine(n) : '',
      tone: n ? 'info' : sessions.some(y => y.status === 'busy') ? 'success' : null, onClick: () => c.setPage(SESSIONS_PAGE) }
  }
  if (x.id === 'c:workers') {
    const st = s.workers?.data?.stats
    if (!st) return { id: x.id, label: t.workersTab, value: '·', sub: '', tone: null, onClick: () => c.setPage(WORKERS_PAGE) }
    return { id: x.id, label: t.workersTab, value: String(st.in_service ?? 0), sub: h.workersFindings(st.with_findings ?? 0),
      tone: st.with_findings ? 'warning' : 'success', onClick: () => c.setPage(WORKERS_PAGE) }
  }
  if (x.id === 'c:waiting') {
    const nowRows = (s.model?.sections ?? []).find(r => r.id === 'now')?.rows ?? []
    const n = scope ? countInProject(nowRows, scope) : counts.now ?? 0
    return { id: x.id, label: h.waitingNow, value: String(n), sub: trend(x.id, n), tone: n ? 'warning' : null, onClick: () => c.setPage('briefing') }
  }
  if (x.id === 'c:tabs') {
    const n = scope ? tabs.filter(tb => tb.waiting && !tb.is_control && inProject(tb, scope)).length : counts.waiting_tabs ?? 0
    return { id: x.id, label: t.tabsTitle, value: String(n), sub: h.tabsWaitingShort, tone: n ? 'warning' : null, onClick: () => c.setDrawer('tabs') }
  }
  const p = x.page
  // a page a partial run left out for now: the station waits for it instead of breaking the stage
  if (!p) return { id: x.id, label: x.label ?? x.id, value: '·', sub: '', tone: null, onClick: null }
  const bad = p.badge?.kind === 'bad'
  const n = scope ? countInProject((p.sections ?? []).flatMap(sec => sec.items ?? []), scope) : p.badge?.n ?? 0
  return { id: x.id, label: p.title, value: String(n), sub: bad ? pageParts(s, p)[0] ?? h.finding(n) : trend(x.id, n) || (pageParts(s, p)[0] ?? ''),
    tone: bad ? 'danger' : p.badge?.warn ? 'warning' : n ? 'info' : null, onClick: () => c.setPage(p.id) }
}

/** The day's lead line: its leading count is the "do" rows, the Now section the station "waits for you" counts
 *  (a partial run keeps the older headline, whose count can lag behind the rows) */
export function leadOf(m) {
  const head = String(m.headline ?? '')
  const n = m.counts?.now
  return n != null && /^\d+\s/.test(head) ? head.replace(/^\d+/, String(n)) : head
}

/** The terminal line of the films, as the field that asks the Bridge: the greeting stands where the
 *  cursor waits, until you type */
export function StagePrompt({ s, c, greeting }) {
  const t = T()
  const h = t.home
  const [text, setText] = useState('')
  const [focus, setFocus] = useState(false)
  // speech fills the field, the person reads it and sends it as a typed question
  const voice = useVoice(heard => setText(was => (was.trim() ? `${was.trim()} ${heard}` : heard).slice(0, ASK_MAX)))
  const busy = !!s.ui.busy['ask:free']
  const send = async e => {
    e.preventDefault()
    const v = text.trim()
    if (v && await c.ask('free', { text: v })) setText('')
  }
  return html`<form class=${`stage-prompt${voice.listening ? ' is-listening' : ''}`} onSubmit=${send} role="search">
    <span class="stage-caret" aria-hidden="true">›</span>
    <span class="stage-field">
      <input type="text" class="stage-input" value=${text} onInput=${e => setText(e.currentTarget.value)}
        onFocus=${() => setFocus(true)} onBlur=${() => setFocus(false)} aria-label=${t.home.askPlaceholder} maxlength=${ASK_MAX} />
      ${!text && !focus ? html`<span class="stage-ghost" aria-hidden="true">${greeting}<span class="stage-cursor"></span></span>` : null}
      ${!text && focus ? html`<span class="stage-ghost is-hint" aria-hidden="true">${t.home.askPlaceholder}</span>` : null}
    </span>
    ${voice.available ? html`<${Btn} size="sm" variant=${voice.listening ? 'primary' : 'ghost'} pressed=${voice.listening}
      onClick=${voice.listening ? voice.stop : voice.start} label=${voice.listening ? h.voiceStop : h.voiceStart}
      title=${voice.listening ? h.voiceStop : h.voiceStart} icon="mic" />` : null}
    ${text.trim() ? html`<button type="submit" class="btn btn-primary btn-sm" disabled=${busy} aria-busy=${busy ? 'true' : undefined}
      aria-label=${t.askSend}><${Icon} name="send" /></button>` : null}
  </form>
  ${voice.listening ? html`<p class="stage-voice muted small" role="status">${h.voiceListening}. ${h.voiceWhere}</p>`
    : voice.error ? html`<p class="stage-voice small tk-warning" role="alert">${h.voiceError[voice.error]}</p>` : null}`
}

/** The card on the right of the films: today's next step first, then what waits on you */
/** How an event of the live feed reads, its tone, and where a click on it leads */
export function FeedLine({ e, s, c }) {
  const h = T().home
  const byKey = indexRows(s.model)
  const row = e.key ? byKey.get(e.key) : null
  const tone = { new: 'info', urgent: 'warning', gone: 'success', tabAsks: 'warning', answer: 'success', lost: 'danger', alarm: 'danger' }[e.kind] ?? 'muted'
  const go = e.ref ? () => jumpToTab(s, c, e.ref) : e.page ? () => c.setPage(e.page) : row ? el => openWhole(c, row, el) : null
  // a work row's event names what the row is and where it comes from, after the event word
  const tags = row ? html` <span class="entry-tags"><${KindTag} row=${row} s=${s} /><${OriginTag} row=${row} /></span>` : null
  const clock = new Date(e.at).toLocaleTimeString(language() === 'de' ? 'de-DE' : 'en-GB', { hour: '2-digit', minute: '2-digit' })
  return html`<li class=${`feed-line tk-${tone}`}>
    <span class="feed-time mono">${clock}</span><span class="stage-dot" aria-hidden="true"></span>
    ${go ? html`<button type="button" class="feed-text" onClick=${ev => go(ev.currentTarget)}><b>${h.feed[e.kind] ?? e.kind}</b>${tags} ${short(e.title, 70)}</button>`
      : html`<span class="feed-text"><b>${h.feed[e.kind] ?? e.kind}</b>${tags} ${short(e.title, 70)}</span>`}
  </li>`
}

/** Rows that came in a little while ago carry "new" */
function freshKeys(s, ms = 15 * 60000) {
  const now = s.now || Date.now()
  return new Set((s.feed ?? []).filter(e => e.kind === 'new' && now - e.at < ms).map(e => e.key))
}

function StageCard({ s, c, tabs, onWeigh }) {
  const t = T()
  const h = t.home
  const pick = focusPick(tabs, s.model)
  const nowRows = (s.model?.sections ?? []).find(x => x.id === 'now')?.rows ?? []
  const rest = nowRows.filter(r => r.key !== pick?.row?.key).slice(0, pick ? 3 : 4)
  const lang = language()
  const stamp = new Date(s.now || Date.now()).toLocaleString(lang === 'de' ? 'de-DE' : 'en-GB', { weekday: 'short', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
  const dot = r => r.priority === 'P0' || r.urgency === 'now' ? 'danger' : r.urgency === 'today' ? 'warning' : 'info'
  const sub = r => [r.area || r.mark?.label, ...(r.why ?? []).slice(0, 1)].filter(Boolean).join(' · ')
  const fresh = freshKeys(s)
  // the rows in the order they stand here: a row opened here walks on through them, as the lists do
  const queue = homeRowQueue([...(pick?.kind === 'row' ? [pick.row] : []), ...rest])
  const row = (r, lead) => html`<div class=${`stage-row${lead ? ' is-lead' : ''}${fresh.has(r.key) ? ' is-new' : ''}`} key=${r.key}>
    <span class=${`stage-dot tk-${dot(r)}`} aria-hidden="true"></span>
    <button type="button" class="stage-row-main" onClick=${e => openWhole(c, r, e.currentTarget, queue)} title=${h.openRow(short(r.title, 60))}>
      <span class="stage-row-title">${fresh.has(r.key) ? html`<span class="new-tag">${h.isNew}</span>` : null}${r.priority ? html`<em class=${`tk-${dot(r)}`}>${r.priority} </em>` : null}${short(r.title, lead ? 120 : 80)}</span>
      <span class="stage-row-sub"><${KindTag} row=${r} s=${s} /><${OriginTag} row=${r} />${sub(r) ? html` ${sub(r)}` : null}</span>
      <${ReturnChip} s=${s} rowKey=${r.key} />
    </button>
    ${lead ? html`<span class="stage-pill">${h.focusTitle}</span>` : null}
    ${lead ? html`<div class="stage-row-acts">
      <${RowBar} row=${r} s=${s} c=${c} tab=${tabOfTask(tabs, r.task)} /></div>` : null}
  </div>`
  return html`<section class="stage-card" aria-labelledby="stage-card-title">
    <header class="stage-card-head"><h2 id="stage-card-title">${h.cardTitle}</h2>
      <span class="stage-card-tools"><small class="mono">${stamp}</small>
        ${onWeigh ? html`<${Btn} size="xs" variant="ghost" cls="stage-weigh" onClick=${onWeigh} title=${h.sit.weigh} icon="spark">${h.weighDay}<//>` : null}</span></header>
    ${pick?.kind === 'tab' ? html`<div class="stage-row is-lead">
      <span class="stage-dot tk-warning dot-pulse" aria-hidden="true"></span>
      <button type="button" class="stage-row-main" onClick=${() => jumpToTab(s, c, pick.tab.ref)} title=${h.openTab(pick.tab.name)}>
        <span class="stage-row-title">${pick.tab.name}</span><span class="stage-row-sub">${pick.tab.workspace} · ${t.state[tabStateKey(pick.tab)] ?? pick.tab.state}</span>
      </button>
      <span class="stage-pill">${h.focusTitle}</span>
      <div class="stage-row-acts"><${Btn} size="xs" variant="primary" onClick=${() => jumpToTab(s, c, pick.tab.ref)}>${h.toTab}<//>
        <${Btn} size="xs" variant="ghost" onClick=${() => c.openTabView(pick.tab.ref)}>${h.view}<//></div>
    </div>` : pick ? row(pick.row, true) : null}
    ${rest.map(r => row(r, false))}
    ${!pick && !rest.length ? html`<p class="stage-row-sub">${h.focusEmpty}</p>` : null}
    ${nowRows.length > rest.length + (pick?.row ? 1 : 0) ? html`<button type="button" class="btn-link stage-more" onClick=${() => c.setPage('briefing')}>
      ${h.seeAll(nowRows.length)}<${Icon} name="chevronRight" size=${14} /></button>` : null}
    <div class="feed">
      <h3 class="label-caps feed-head"><span class="feed-live" aria-hidden="true"></span>${h.liveTitle}</h3>
      <${TickerStatusList} s=${s} c=${c} />
      ${(s.feed ?? []).length ? html`<ol class="feed-list">${(s.feed ?? []).slice(0, 7).map(e => html`<${FeedLine} key=${`${e.kind}${e.key ?? e.ref ?? e.title}${e.at}`} e=${e} s=${s} c=${c} />`)}</ol>`
        : tickerStatusItems(s, s.now || Date.now()).length ? html`<p class="stage-row-sub">${h.liveQuiet}</p>`
        : html`<p class="stage-row-sub">${h.liveEmpty}</p>`}
    </div>
  </section>`
}

/** One line of the inspector: a dot, the title, a small line under it, something on the right; a click acts */
function InspectRow({ tone, title, sub, side, onClick, children }) {
  return html`<div class="stage-row inspect-row">
    <span class=${`stage-dot tk-${tone ?? 'info'}`} aria-hidden="true"></span>
    ${onClick ? html`<button type="button" class="stage-row-main" onClick=${onClick}>
      <span class="stage-row-title">${title}</span>${sub ? html`<span class="stage-row-sub">${sub}</span>` : null}</button>`
      : html`<span class="stage-row-main"><span class="stage-row-title">${title}</span>${sub ? html`<span class="stage-row-sub">${sub}</span>` : null}</span>`}
    ${side != null ? html`<span class="inspect-side num">${side}</span>` : html`<span></span>`}
    ${children ? html`<div class="stage-row-acts">${children}</div>` : null}
  </div>`
}

/** The inspector: what a station stands for, opened beside the bridge instead of leaving the page. Every
 *  line in it leads on; the button at the foot opens the whole page */
function StageInspector({ x, st, s, c, tabs, onClose }) {
  const t = T()
  const h = t.home
  const lang = language()
  const head = (title, big) => html`<header class="stage-card-head">
    <h2 id="stage-card-title" class="clamp2">${title}</h2>
    <button type="button" class="btn-link inspect-close" onClick=${onClose} aria-label=${t.close}><${Icon} name="close" /></button>
  </header>${big ? html`<p class="inspect-big num">${big}</p>` : null}`
  const foot = (label, fn) => fn ? html`<div class="inspect-foot"><${Btn} size="sm" variant="primary" onClick=${fn}>${label}<//></div>` : null
  let body = null
  if (x.kind === 'quota') {
    const m = x.it.meter
    const pace = meterPace(m)
    const book = s.model?.days?.quota?.[x.id]
    const fill = Math.max(0, Math.min(1, m.value / m.max))
    body = html`${head(x.label, `${pct(m.value, lang)} %`)}
      <span class=${`ktile-bar tk-${st.tone}`} aria-hidden="true">
        <span class="ktile-fill" style=${{ transform: `scaleX(${fill.toFixed(4)})` }}></span>
        ${m.elapsed != null ? html`<span class="ktile-time" style=${{ left: `${(m.elapsed * 100).toFixed(1)}%` }}></span>` : null}
      </span>
      ${book ? html`<${InspectRow} tone=${pace?.budget && book.today > pace.budget ? 'warning' : 'success'} title=${h.today(pct(book.today, lang))}
        sub=${h.lastDays}>${book.days.length ? html`<${DayBars} days=${book.days} budget=${pace?.budget} label=${h.lastDays} />` : null}<//>` : null}
      ${pace?.perDay != null ? html`<${InspectRow} tone=${pace.perDay > pace.budget ? 'warning' : 'success'} title=${h.perDay(pct(pace.perDay, lang))}
        sub=${h.budget(pct(pace.budget, lang))} side=${pace.perDay > pace.budget ? h.overBudget : h.inBudget} />` : null}
      ${pace ? html`<${InspectRow} tone=${pace.over ? 'warning' : 'info'} title=${h.projected(pct(pace.projected, lang))} sub=${x.it.when ? h.reset(x.it.when) : ''} />` : null}
      ${foot(h.details, () => c.openInfo(x.it, x.page, x.section))}`
  } else if (x.id === 'c:waiting') {
    const rows = (s.model?.sections ?? []).find(r => r.id === 'now')?.rows ?? []
    // the morning round from the start page: the first row carries its buttons, and once it is settled
    // the next one moves up and carries them; a row whose task already has a tab leads to that tab
    const acts = r => html`<${RowBar} row=${r} s=${s} c=${c} tab=${tabOfTask(tabs, r.task)} />`
    const queue = homeRowQueue(rows.slice(0, 8))
    body = html`${head(h.waitingNow, String(rows.length))}
      ${rows.slice(0, 8).map((r, i) => html`<${InspectRow} key=${r.key} tone=${r.urgency === 'now' ? 'danger' : r.urgency === 'today' ? 'warning' : 'info'}
        title=${short(r.title, i ? 90 : 140)} sub=${html`<${KindTag} row=${r} s=${s} /><${OriginTag} row=${r} />${r.area || r.mark?.label ? html` ${r.area || r.mark?.label}` : null}`} onClick=${e => openWhole(c, r, e.currentTarget, queue)}>${i === 0 ? acts(r) : null}<//>`)}
      ${!rows.length ? html`<p class="stage-row-sub">${h.focusEmpty}</p>` : null}
      ${foot(h.openPage(briefingTitle(s)), () => c.setPage('briefing'))}`
  } else if (x.id === 'c:returns') {
    const list = returnsOf(s)
    body = html`${head(h.returnsTitle, st.value)}
      <div class="rlist">${list.map(r => html`<${ReturnCard} key=${r.key} r=${r} s=${s} c=${c} />`)}</div>
      ${!list.length ? html`<p class="stage-row-sub">${h.returnsEmpty}</p>` : null}`
  } else if (x.id === 'c:agents') {
    const sessions = s.sessions?.sessions ?? []
    body = html`${head(h.agentsTitle, st.value)}
      ${sessions.slice(0, 8).map(y => html`<${InspectRow} key=${y.id} tone=${(y.agents?.running_count ?? 0) ? 'info' : y.status === 'busy' ? 'success' : 'muted'}
        title=${y.tab?.name ?? y.name ?? y.project} sub=${[y.project, y.status, (y.agents?.running_count ?? 0) ? h.agentsLine(y.agents.running_count) : null].filter(Boolean).join(' · ')}
        side=${duration(s.now - (y.since_ms || s.now))} onClick=${() => c.setPage(SESSIONS_PAGE)} />`)}
      ${(s.agents?.peers ?? []).map(pe => html`<${InspectRow} key=${pe.id} tone=${pe.reach === 'ok' ? 'success' : 'muted'} title=${pe.id}
        sub=${pe.summary ? short(pe.summary, 80) : ''} onClick=${() => c.setPage(AGENTS_PAGE)} />`)}
      ${foot(h.openPage(t.sessionsTab), () => c.setPage(SESSIONS_PAGE))}`
  } else if (x.id === 'c:workers') {
    const runs = (s.workers?.data?.runs ?? []).filter(r => !['ok', 'dim'].includes(workerTone(r)))
    body = html`${head(t.workersTab, st.value)}
      ${s.workers?.data?.stats ? html`<p class="stage-row-sub">${h.workersFindings(s.workers.data.stats.with_findings ?? 0)}</p>` : null}
      ${runs.slice(0, 8).map(r => html`<${InspectRow} key=${r.id} tone=${workerTone(r) === 'bad' ? 'danger' : 'warning'} title=${r.title}
        sub=${short(r.findings?.[0]?.detail ?? r.state ?? '', 90)} side=${r.host} onClick=${() => c.setPage(WORKERS_PAGE)} />`)}
      ${foot(h.openPage(t.workersTab), () => c.setPage(WORKERS_PAGE))}`
  } else if (x.id === 'c:tabs') {
    const list = homeContinue(tabs, null)
    body = html`${head(t.tabsTitle, String(list.length))}
      ${list.slice(0, 8).map(tb => html`<${InspectRow} key=${tb.ref} tone=${stateToken(tabStateKey(tb))} title=${tb.name}
        sub=${`${tb.workspace || '·'} · ${t.state[tabStateKey(tb)] ?? tb.state}`} side=${duration(s.now - (tb.since_ms || s.now))}
        onClick=${() => c.openTabView(tb.ref)}><${Btn} size="xs" variant="primary" onClick=${() => jumpToTab(s, c, tb.ref)}>${h.toTab}<//><//>`)}
      ${foot(t.tabsTitle, () => c.setDrawer('tabs'))}`
  } else if (x.id === 'c:next') {
    const now = s.now || Date.now()
    const items = (s.model?.pages ?? []).flatMap(p => (p.sections ?? []).filter(sec => sec.kind === 'calendar')
      .flatMap(sec => (sec.items ?? []).map(it => ({ it, page: p.id, section: sec.id, ms: it.at ? Date.parse(it.at) : NaN }))))
      .filter(e => Number.isFinite(e.ms) && e.ms > now).sort((a, b) => a.ms - b.ms)
    body = html`${head(h.nextTitle, items[0] ? h.inTime(untilText(items[0].ms - now)) : '·')}
      ${items.slice(0, 6).map(e => html`<${InspectRow} key=${e.it.title + e.ms} tone="info" title=${e.it.title}
        sub=${[e.it.when, e.it.detail].filter(Boolean).join(' · ')} side=${untilText(e.ms - now)} onClick=${() => c.openInfo(e.it, e.page, e.section)} />`)}
      ${!items.length ? html`<p class="stage-row-sub">${h.nextNone}</p>` : null}
      ${items[0] ? foot(h.openPage(pageTitleOf(s, items[0].page)), () => c.setPage(items[0].page)) : null}`
  } else if (x.id === 'c:done') {
    const week = s.model?.week ?? { count: 0, items: [] }
    body = html`${head(h.doneTitle, String(week.count))}
      ${week.items.map(i => html`<${InspectRow} key=${i.slug} tone="success" title=${i.title}
        sub=${html`<${KindTag} row=${{ key: `task:${i.slug}`, task: i.slug, work_kind: i.work_kind ?? 'done' }} s=${s} /> ${i.slug}`}
        side=${i.closed.slice(5).split('-').reverse().join('.')} />`)}`
  } else if (x.page) {
    const p = x.page
    const secs = (p.sections ?? []).filter(sec => (sec.items ?? []).length)
    // the work page's items are work rows: they carry their kind and their source like every other work row
    const work = p.group === 'work' || p.id === workPageOf(s.model?.pages)?.id
    body = html`${head(p.title, String(p.badge?.n ?? 0))}
      <div class="inspect-parts">${(p.sections ?? []).filter(sec => (sec.total ?? sec.count ?? 0) > 0).map(sec => html`<span key=${sec.id} class="chip">
        ${sec.title} <span class="mono">${sec.total ?? sec.count}</span></span>`)}</div>
      ${secs.flatMap(sec => sec.items.slice(0, 4).map(it => ({ it, sec }))).slice(0, 8).map(({ it, sec }) => html`<${InspectRow}
        key=${`${sec.id}/${it.index}`} tone=${it.tone === 'bad' ? 'danger' : it.tone === 'warn' ? 'warning' : 'info'}
        title=${short(it.title, 90)} sub=${work ? html`<${KindTag} row=${itemRow(it)} s=${s} /><${OriginTag} row=${itemRow(it)} /> ${[sec.title, it.when].filter(Boolean).join(' · ')}`
          : [sec.title, it.when].filter(Boolean).join(' · ')} onClick=${() => c.openInfo(it, p.id, sec.id)} />`)}
      ${foot(h.openPage(p.title), () => c.setPage(p.id))}`
  }
  return html`<section class="stage-card inspect" aria-labelledby="stage-card-title">${body}</section>`
}

/** A station's heart line: one beat drawn twice and slid along, faster the worse the station stands */
function HeartLine({ tone }) {
  const beat = pulseSpeed(tone)
  if (!beat) return null
  const one = 'H18 l3 -5 l4 11 l4 -13 l3 9 l2 -2 H60'
  return html`<svg class="heart" viewBox="0 0 120 16" aria-hidden="true" preserveAspectRatio="none">
    <g class="heart-run" style=${{ animationDuration: `${beat * 2}s` }}>
      <path d=${`M0 8 ${one} ${one.replace(/H18/, 'H78').replace(/H60/, 'H120')}`} />
    </g></svg>`
}

/** Speech into the question line: the browser's own speech recognition, one sentence, handed to onText.
 *  Which service hears it depends on the browser. An error stays as its cause until the next start */
function useVoice(onText) {
  const [listening, setListening] = useState(false)
  const [error, setError] = useState(null)
  const rec = useRef(null)
  const Ctor = typeof window !== 'undefined' ? (window.SpeechRecognition || window.webkitSpeechRecognition) : null
  const start = () => {
    if (!Ctor || listening) return false
    const r = new Ctor()
    r.lang = language() === 'de' ? 'de-DE' : 'en-GB'
    r.interimResults = false
    r.maxAlternatives = 1
    r.onresult = e => { const text = e.results?.[0]?.[0]?.transcript; if (text) onText(text) }
    r.onend = () => setListening(false)
    r.onerror = e => { setError(speechError(e?.error)); setListening(false) }
    rec.current = r
    setError(null)
    setListening(true)
    try { r.start() } catch { setError('other'); setListening(false); return false }
    return true
  }
  const stop = () => { rec.current?.stop(); setListening(false) }
  return { available: !!Ctor, listening, error, start, stop }
}

/** The core's own panel: how the Bridge itself stands (control session, terminal driver, last collection,
 *  probes, workers, agents), the picture Claude drew of the day, and the focus span */
/**
 * The picture of the day as a board: each field one question of the day with its number and the first thing in it,
 * a click leads there. Read from the page's own data, so it stands at once and costs nothing.
 */
function SituationBoard({ s, c }) {
  const h = T().home
  const now = s.now || Date.now()
  const sit = situation(s.model, s.tabs?.tabs ?? [], now)
  const byKey = indexRows(s.model)
  const openRow = r => el => openWhole(c, byKey.get(r.key) ?? r, el)
  const tab = t => () => jumpToTab(s, c, t.ref)
  const ret = r => () => c.openItem(r.key)
  const first = sit.first
  const fields = [
    { id: 'first', tone: first ? 'warning' : 'success', label: h.sit.first, n: null,
      line: first ? (first.kind === 'tab' ? h.sit.tabAsks(first.tab.name) : first.row.title) : h.sit.nothing,
      go: first ? (first.kind === 'tab' ? tab(first.tab) : openRow(first.row)) : null, wide: true },
    // the same rows the station "waits for you" counts, so the board is never emptier than the stage
    { id: 'now', tone: sit.now.length ? 'warning' : 'muted', label: h.sit.now, n: sit.now.length,
      line: (sit.now.find(r => r.key !== first?.row?.key) ?? sit.now[0])?.title, go: sit.now.length ? () => c.setPage('briefing') : null },
    { id: 'asking', tone: sit.asking.length ? 'warning' : 'muted', label: h.sit.asking, n: sit.asking.length,
      line: sit.asking[0]?.name, go: sit.asking[0] ? tab(sit.asking[0]) : null },
    { id: 'give', tone: sit.give.length ? 'warning' : 'muted', label: h.sit.give, n: sit.give.length,
      line: sit.give[0]?.title, go: sit.give[0] ? openRow(sit.give[0]) : null },
    { id: 'working', tone: sit.working.length ? 'info' : 'muted', label: h.sit.working, n: sit.working.length,
      line: sit.working[0]?.name, go: sit.working[0] ? tab(sit.working[0]) : null },
    { id: 'answers', tone: sit.answers.length ? 'success' : 'muted', label: h.sit.answers, n: sit.answers.length,
      line: sit.answers[0]?.title, go: sit.answers[0] ? ret(sit.answers[0]) : null },
    sit.lost.length ? { id: 'lost', tone: 'danger', label: h.sit.lost, n: sit.lost.length, line: sit.lost[0].title, go: ret(sit.lost[0]) } : null,
    { id: 'next', tone: sit.next ? 'info' : 'muted', label: h.sit.next, n: null,
      line: sit.next ? `${h.inTime(untilText(sit.next.ms - now))} · ${sit.next.it.title}` : h.nextNone,
      go: sit.next ? () => c.openInfo(sit.next.it, sit.next.page, sit.next.section) : null },
    sit.quota ? { id: 'quota', tone: sit.quota.bad ? 'danger' : sit.quota.over || sit.quota.warn ? 'warning' : 'success', label: h.sit.quota,
      n: `${pct(sit.quota.value, language())} %`, line: [sit.quota.label, sit.quota.perDay != null ? h.perDay(pct(sit.quota.perDay, language())) : null].filter(Boolean).join(' · '),
      go: () => c.openInfo(sit.quota.it, sit.quota.page, sit.quota.section) } : null,
    { id: 'alarms', tone: sit.alarms.length ? 'danger' : 'success', label: h.sit.alarms, n: sit.alarms.length,
      line: sit.alarms[0] ? `${sit.alarms[0].section_title} · ${sit.alarms[0].page_title}` : h.sit.clean,
      go: sit.alarms[0] ? () => c.setPage(sit.alarms[0].page_id) : null },
    { id: 'later', tone: 'muted', label: h.sit.later, n: sit.later.length, line: sit.later[0]?.title,
      go: sit.later[0] ? openRow(sit.later[0]) : null },
  ].filter(Boolean)
  return html`<div class="sit-board">${fields.map(f => {
    const body = html`<span class="label-caps sit-label"><span class=${`stage-dot tk-${f.tone}`} aria-hidden="true"></span>${f.label}</span>
      ${f.n !== null ? html`<b class="sit-n num">${f.n}</b>` : null}
      <span class="sit-line">${f.line ? short(f.line, f.wide ? 110 : 60) : h.sit.nothing}</span>`
    return f.go ? html`<button type="button" key=${f.id} class=${`sit-field tk-${f.tone}${f.wide ? ' is-wide' : ''}`} onClick=${e => f.go(e.currentTarget)}>${body}</button>`
      : html`<div key=${f.id} class=${`sit-field tk-${f.tone}${f.wide ? ' is-wide' : ''}`}>${body}</div>`
  })}</div>`
}

/** Claude's verdict on the picture: its three lines as three rows, any other answer as it came */
function Verdict({ s, conv }) {
  const h = T().home
  const turn = conv?.turns?.[0]
  const live = useQuickLive(conv?.id)
  if (!turn || (!turn.a && !turn.error)) {
    return html`<div class="verdict"><${Thinking} label=${live?.doing ? T().quickReading(live.doing) : h.sit.weighing} /></div>`
  }
  if (turn.error) return html`<p><${StateLine} token="danger" word=${T().quickFailed(turn.error)} /></p>`
  const v = parseVerdict(turn.a)
  if (!v) return html`<div class="verdict"><div class="qa">${turn.a}</div></div>`
  return html`<ol class="verdict">${['first', 'then', 'later'].map(k => html`<li key=${k} class=${`verdict-row is-${k}`}>
    <span class="label-caps">${h.sit.verdict[k]}</span><span>${v[k]}</span></li>`)}</ol>`
}

function CoreInspector({ s, c, onClose, onAsk, onWeigh }) {
  const t = T()
  const h = t.home
  const relay = s.relay ?? {}
  const loading = !!s.loading?.pass
  const workers = s.workers?.data?.stats
  const agents = (s.sessions?.sessions ?? []).reduce((n, x) => n + (x.agents?.running_count ?? 0) + (x.workflows?.length ?? 0), 0)
  const conv = (s.quick?.convs ?? []).find(x => x.id === s.ui.coreConv) ?? null
  const live = useQuickLive(conv?.id)
  const [text, setText] = useState('')
  const busy = !!s.ui.busy['ask:core']
  const send = async e => {
    e.preventDefault()
    const v = text.trim()
    if (!v) return
    if (!conv) c.setCoreBrief(false)
    if (await onAsk(v, conv?.id)) setText('')
  }
  const brief = s.ui.coreBrief
  return html`<section class="stage-card inspect core-panel" aria-labelledby="stage-card-title">
    <header class="stage-card-head">
      <h2 id="stage-card-title">Bridge</h2>
      <button type="button" class="btn-link inspect-close" onClick=${onClose} aria-label=${t.close}><${Icon} name="close" /></button>
    </header>
    ${brief ? html`<h3 class="label-caps core-sub">${h.briefTitle}</h3>
      <${SituationBoard} s=${s} c=${c} />
      <h3 class="label-caps core-sub">${h.sit.verdictTitle}</h3>
      <div class="core-brief">${conv ? html`<${Verdict} s=${s} conv=${conv} />
        ${conv.turns.length > 1 ? html`<${ChatThread} s=${s} c=${c} conv=${{ ...conv, turns: conv.turns.slice(1) }} />` : null}`
        : busy ? html`<${Thinking} label=${h.sit.weighing} />`
        : html`<${Btn} size="xs" variant="ghost" onClick=${onWeigh}>${h.sit.weigh}<//>`}</div>
      <${Btn} size="xs" variant="ghost" onClick=${() => c.openInner()}>${h.sit.toNet}<//>` : null}
    <h3 class="label-caps core-sub">${h.coreState}</h3>
    ${relay.enabled ? html`<${InspectRow} tone=${relay.online ? 'success' : 'warning'} title=${t.controlSession}
      sub=${relay.online ? h.coreOnline : h.controlOffline}>
      ${!relay.online ? html`<${Btn} size="xs" variant="primary" busy=${!!s.ui.busy.start_control} onClick=${() => c.act('start_control')}>${h.coreStart}<//>` : null}<//>` : null}
    <${InspectRow} tone=${s.cmux?.ok || Array.isArray(s.driver?.caps) && s.driver.caps.length ? 'success' : 'warning'} title=${h.coreDriver}
      sub=${Array.isArray(s.driver?.caps) ? s.driver.caps.join(' · ') : '·'} />
    <${InspectRow} tone=${loading ? 'info' : s.model?.stale ? 'warning' : 'success'} title=${loading ? h.coreCollecting : h.coreCollected(s.model?.collected_at ?? '·')}
      sub=${s.model?.is_full ? h.coreFull : h.coreQuick}>
      <${Btn} size="xs" variant="ghost" busy=${loading} onClick=${c.reload}>${t.reload}<//><//>
    ${(s.model?.alarms ?? []).map(a => html`<${InspectRow} key=${a.page_id + a.section_title} tone="danger" title=${h.alarm(a.count, a.section_title)}
      sub=${a.page_title} onClick=${() => c.setPage(a.page_id)} />`)}
    ${workers ? html`<${InspectRow} tone=${workers.with_findings ? 'warning' : 'success'} title=${h.workersLine(workers.in_service ?? 0)}
      sub=${h.workersFindings(workers.with_findings ?? 0)} onClick=${() => c.setPage(WORKERS_PAGE)} />` : null}
    <${InspectRow} tone=${agents ? 'info' : 'muted'} title=${h.agentsLine(agents)} sub=${h.sessionsLine((s.sessions?.sessions ?? []).length)}
      onClick=${() => c.setPage(SESSIONS_PAGE)} />
    ${!brief && (conv || busy) ? html`<h3 class="label-caps core-sub">${h.askTitle}</h3>
      <div class="core-brief">${conv ? html`<${ChatThread} s=${s} c=${c} conv=${conv} />` : html`<p class="muted small">${h.briefWaiting}</p>`}
        ${live?.doing ? html`<p class="muted small">${live.doing}</p>` : null}</div>` : null}
    <form class="core-ask" onSubmit=${send}>
      <input type="text" class="core-ask-input" value=${text} onInput=${e => setText(e.currentTarget.value)}
        placeholder=${conv ? h.briefFollow : h.askPlaceholder} aria-label=${h.askPlaceholder} maxlength=${ASK_MAX} />
      <button type="submit" class="btn btn-primary btn-xs" disabled=${busy || !text.trim()} aria-label=${t.askSend}><${Icon} name="send" /></button>
    </form>
  </section>`
}

const DUST = stageDust(70, 41)

/** The stage: the core with its rings, the chosen tiles as stations on curved links with packets running
 *  in, the terminal line top left, the card on the right */
export function BridgeStage({ s, c, catalog, chosen, project }) {
  const t = T()
  const h = t.home
  const lang = language()
  const tabs = s.tabs?.tabs ?? []
  // one place of the ring is Today's own station, so the chosen tiles get one fewer
  const tiles = shownTiles(catalog, chosen).slice(0, MAX_STATIONS - 1)
  const compact = tiles.length > 10
  const stations = tiles.map(x => stationOf(x, s, c, chosen, project))
  // the station looked at (its inspector stands beside the bridge) and the one under the pointer
  const [sel, setSel] = useState(null)
  const [hot, setHot] = useState(null)
  const [wave, setWave] = useState(0)
  // a station whose number moved shows by how much, for two minutes
  const seen = useRef(new Map())
  const born = useRef(Date.now())
  const selIdx = tiles.findIndex(x => x.id === sel)
  const on = new Set(chosen)
  const pulse = on.has('o:pulse')
  const coreAsk = async (text, conv) => { setSel('@core'); return c.askQuiet(text, conv) }
  // one mode now: the core's panel opens and shows what it does
  const runMode = id => {
    setSel('@core')
    setWave(n => n + 1)
    if (id === 'k:scan') c.reload()
    if (id === 'k:brief') {
      // the picture of the day: the board from the page's data at once, and Claude weighs exactly that data
      c.setCoreBrief(true)
      coreAsk(h.briefAsk(situationText(situation(s.model, tabs, Date.now()), Date.now(), lang)))
    }
  }
  // a click on the core opens its panel with the picture of the day as a board (the page's data, at once, free);
  // scan and Claude's verdict join when chosen for it in the chooser
  const runCore = () => {
    setSel('@core')
    setWave(n => n + 1)
    if (!on.has('k:brief')) c.setCoreBrief(true)
    for (const id of ['k:scan', 'k:brief']) if (on.has(id)) runMode(id)
  }
  // held down a moment (or with the option key) the core opens the inner room instead: the net behind the bridge
  const press = useRef(null)
  const [charging, setCharging] = useState(false)
  const pressStart = e => {
    if (e.button) return
    setCharging(true)
    press.current = setTimeout(() => { press.current = 'fired'; setCharging(false); c.openInner() }, 800)
  }
  const pressEnd = () => {
    if (press.current && press.current !== 'fired') { clearTimeout(press.current); press.current = null }
    setCharging(false)
  }
  const coreClick = e => {
    if (press.current === 'fired') { press.current = null; return }
    if (e.altKey) { c.openInner(); return }
    runCore()
  }
  useEffect(() => () => { if (press.current && press.current !== 'fired') clearTimeout(press.current) }, [])
  const nowMs = s.now || Date.now()
  for (const st of stations) {
    const v = Number(st.value)
    const was = seen.current.get(st.id)
    if (!Number.isFinite(v)) continue
    if (!was) seen.current.set(st.id, { v, diff: 0, at: 0 })
    else if (was.v !== v) seen.current.set(st.id, Date.now() - born.current < 30000 ? { v, diff: 0, at: 0 } : { v, diff: v - was.v, at: Date.now() })
  }
  const bubble = id => { const x = seen.current.get(id); return x && x.diff && nowMs - x.at < 120000 ? x.diff : 0 }
  // Today is a station of the ring too: the block beside the bridge shows one thing, Today or the station
  // looked at, and a click on Today brings it back
  const today = { id: '@today', label: h.cardTitle, tone: 'info', sub: '',
    value: new Date(nowMs).toLocaleDateString(lang === 'de' ? 'de-DE' : 'en-GB', { weekday: 'short', day: '2-digit', month: '2-digit' }) }
  const ring = [today, ...stations]
  const ringSel = sel === null ? 0 : selIdx >= 0 ? selIdx + 1 : -1
  const spots = stageSpots(ring.length)
  const now = new Date(s.now || Date.now())
  const person = s.server?.person
  const greeting = greetingText(now.getHours(), person, h.greeting)
  const eyebrow = [h.stageName, dayLabel(now, lang),
    now.toLocaleTimeString(lang === 'de' ? 'de-DE' : 'en-GB', { hour: '2-digit', minute: '2-digit' })].join(' · ')
  const working = tabs.filter(x => x.state === 'working' && !x.is_control).length
  const relayDown = s.relay?.enabled && !s.relay?.online
  const ticks = Array.from({ length: 72 }, (_, i) => i)
  const pctX = x => `${(x / STAGE.w * 100).toFixed(2)}%`
  const pctY = y => `${(y / STAGE.h * 100).toFixed(2)}%`
  return html`<section class=${`stage${s.loading?.pass ? ' is-scan' : ''}`} aria-label=${h.stageName}>
    <div class="stage-sky" aria-hidden="true">
      <svg viewBox="0 0 1000 560" preserveAspectRatio="xMidYMid slice" class="stage-svg">
        ${DUST.map((d, i) => html`<circle key=${i} cx=${d.x.toFixed(1)} cy=${d.y.toFixed(1)} r=${d.r.toFixed(2)} class="dust" style=${{ opacity: d.o.toFixed(2) }} />`)}
      </svg>
    </div>
    <div class="stage-term">
      <div class="stage-greet">
        <span class="stage-eyebrow">${eyebrow}</span>
        <${StagePrompt} s=${s} c=${c} greeting=${greeting} />
        ${s.model?.headline ? html`<p class="stage-lead">${leadOf(s.model)}</p>` : null}
        ${(s.model?.alarms ?? []).length || relayDown ? html`<div class="home-signals">
          ${(s.model?.alarms ?? []).map(a => html`<button type="button" class="home-signal tk-danger" key=${a.page_id + a.section_title}
            onClick=${() => c.setPage(a.page_id)}><${Dot} token="danger" /><span>${h.alarm(a.count, `${a.section_title} (${a.page_title})`)}</span></button>`)}
          ${relayDown ? html`<button type="button" class="home-signal tk-warning" onClick=${c.openClaude}>
            <${Dot} token="warning" /><span>${h.controlOffline}</span></button>` : null}
        </div>` : null}
      </div>
      ${s.ui.tickerOnStart ? html`<${TickerBand} s=${s} c=${c} only="news" />` : null}
    </div>
    <div class="stage-body">
      <div class="stage-bridge-box">
        <svg viewBox=${`0 0 ${STAGE.w} ${STAGE.h}`} class="stage-svg stage-bridge" aria-hidden="true">
          ${spots.map((p, i) => html`<g key=${ring[i].id} class=${`link tk-${ring[i].tone ?? 'muted'}${hot === i || ringSel === i ? ' is-hot' : ''}`}>
            <path d=${p.path} class="link-line" id=${`link-${i}`} />
            ${(ring[i].tone && ring[i].tone !== 'success' && ring[i].tone !== 'info') || hot === i || ringSel === i ? html`<circle r="2.6" class="packet">
              <animateMotion dur=${`${(hot === i || ringSel === i ? 1.2 : 3.2 + (i % 4) * 0.7).toFixed(1)}s`} begin=${`${(i * 0.53).toFixed(2)}s`} repeatCount="indefinite" keyPoints="1;0" keyTimes="0;1" calcMode="linear">
                <mpath href=${`#link-${i}`} /></animateMotion></circle>` : null}
          </g>`)}
          <g class="core" transform=${`translate(${STAGE.cx} ${STAGE.cy}) scale(1 ${STAGE.squash})`}>
            ${ticks.map(i => {
              const a = i / ticks.length * Math.PI * 2
              const r1 = 112, r2 = i % 6 === 0 ? 124 : 118
              return html`<line key=${i} x1=${(r1 * Math.cos(a)).toFixed(1)} y1=${(r1 * Math.sin(a)).toFixed(1)} x2=${(r2 * Math.cos(a)).toFixed(1)} y2=${(r2 * Math.sin(a)).toFixed(1)} class="tick" />`
            })}
            <circle r="104" class="ring" />
            <g class="sweep"><path d="M0 -104 A104 104 0 0 1 44 -94 L36 -77 A85 85 0 0 0 0 -85 Z" class="sweep-arc" /></g>
            <circle r="76" class="ring ring-inner" />
            <circle r="52" class="core-fill" />
            ${wave ? [0, 1, 2].map(k => html`<circle key=${`${wave}-${k}`} r="56" class="wave" style=${{ animationDelay: `${k * 0.35}s` }} />`) : null}
          </g>
          <text x=${STAGE.cx} y=${STAGE.cy + 7} class="core-name" text-anchor="middle">Bridge</text>
        </svg>
        ${ring.map((st, i) => html`<button type="button" key=${st.id} class=${`station tk-${st.tone ?? 'muted'}${ringSel === i ? ' is-sel' : ''}${compact ? ' is-compact' : ''}`}
          style=${{ left: pctX(spots[i].x), top: pctY(spots[i].y) }} aria-pressed=${String(ringSel === i)} title=${st.label}
          onClick=${() => st.id === '@today' ? setSel(null) : setSel(sel === st.id ? null : st.id)} onMouseEnter=${() => setHot(i)} onMouseLeave=${() => setHot(null)}
          onFocus=${() => setHot(i)} onBlur=${() => setHot(null)}>
          <b aria-hidden="true"></b>
          ${bubble(st.id) ? html`<span class=${`station-bubble${bubble(st.id) > 0 ? ' is-up' : ' is-down'}`}>${bubble(st.id) > 0 ? '+' : ''}${bubble(st.id)}</span>` : null}
          <span class="station-text"><span class="station-label">${st.label}</span>
            <span class="station-value num">${st.value}</span>${st.sub ? html`<small>${st.sub}</small>` : null}
            ${pulse ? html`<${HeartLine} tone=${st.tone} />` : null}</span>
          <span class="station-flash" key=${s.model?.seq ?? 0} aria-hidden="true"></span>
        </button>`)}
        <button type="button" class=${`core-button${sel === '@core' ? ' is-sel' : ''}${charging ? ' is-charging' : ''}`} style=${{ left: pctX(STAGE.cx), top: pctY(STAGE.cy) }}
          onClick=${coreClick} onPointerDown=${pressStart} onPointerUp=${pressEnd} onPointerLeave=${pressEnd} onPointerCancel=${pressEnd}
          onContextMenu=${e => e.preventDefault()} onKeyDown=${e => { if (e.key === 'Enter' && e.altKey) { e.preventDefault(); c.openInner() } }}
          title=${h.coreTitle} aria-label=${h.coreTitle}></button>
        <span class="stage-hub">${h.hubLine(tabs.filter(x => !x.is_control).length, working, s.model?.counts?.work ?? 0)}</span>
      </div>
      <div class="stage-side">
        ${sel === '@core' ? html`<${CoreInspector} s=${s} c=${c} onClose=${() => setSel(null)} onAsk=${coreAsk} onWeigh=${() => runMode('k:brief')} />`
          : selIdx >= 0 ? html`<${StageInspector} x=${tiles[selIdx]} st=${stations[selIdx]} s=${s} c=${c} tabs=${tabs} onClose=${() => setSel(null)} />`
          : html`<${StageCard} s=${s} c=${c} tabs=${tabs} onWeigh=${() => runMode('k:brief')} />`}
      </div>
    </div>
  </section>`
}
