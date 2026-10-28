// SPDX-License-Identifier: MIT
// The cockpit, the center: overview and the detail of a row.
// The rules every component keeps stand at the head of components.js.

import { html, useEffect, useState } from '../vendor/htm-preact-3.1.1.module.js'
import {
  detailNeedsLoad, duration, formatDay, indexRows, short,
  stateToken, canTab, settledRefs, statusSplit, tabCloseOffer, tabNextStep, areaScope, homeAreas, startWaiting,
  skipFixable, skipText, queueLiveKeys, queueView, dayQueue, tabStateKey, originOf, workKindOf, itemRow
} from '../logic.js'
import { T, language } from '../text.js'
import { ItemCard, TASK_FACTS_SKIP, describeKey, describeOf } from './card.js'
import { ReviewBlock } from './check.js'
import { KindTag, OriginTag, RowBar, Skeleton } from './day.js'
import { ReturnChip, ReturnPanel } from './home.js'
import { PageSection } from './pages.js'
import { Btn, SkipFix, Chip, Dot, Empty, LinkView, MarkChip, PrioChip, Spinner, StateLine, WalkBar } from './parts.js'
import { TaskSessions } from './sessions.js'

// ---------------------------------------------------------------- center: overview and detail

function Overview({ s, c }) {
  const t = T()
  const m = s.model
  if (!m) return html`<div class="panel panel-pad"><${Skeleton} lines=${6} /></div>`
  // under an area filter the count is the area's, as its line on the overview has it; the rest of the
  // headline (free time, what comes) is the day's
  // with Work through on the count is its own, the start page's line for the area (flow.js startWaiting)
  const area = s.ui.area ? homeAreas(s.tabs?.tabs, m.sections, [], s.now || Date.now())
    .find(a => !a.none && a.name.toLowerCase() === s.ui.area.trim().toLowerCase()) : null
  const waiting = startWaiting(s, s.ui.area) ?? (s.ui.area ? area?.waiting ?? 0 : m.briefing_badge ?? 0)
  const head = html`
    <span class="eyebrow">${t.overviewTitle}</span>
    <h2 class="detail-title">${t.forYouNow(waiting)}${m.headline_rest ? ` · ${m.headline_rest}` : ''}</h2>
    ${m.since ? html`<p class="muted">${m.since}</p>` : null}`
  // the day (dates, status, what happened) stands here, with a work tab too: the overview on Start has none.
  // Under an area filter it keeps to the area as the rows beside it do (the star is the rows' own filter)
  const day = areaScope({ ...s, ui: { ...s.ui, pinnedOnly: false } })
  return html`<div class="panel panel-pad overview">${head}
    <${DayView} s=${day} c=${c} />
    <p class="hint muted">${t.detailEmpty}</p>
  </div>`
}

/** The lines of Small fixes: each one in the page's own sentence for its kind (extras.tend, briefing_view), the
 *  text the server wrote for a kind it has none for and for an older server that sends no facts */
const tendLines = (ex, t) => (Array.isArray(ex.tend) && ex.tend.length ? ex.tend.map(x => t.tend[x.kind]?.(x) ?? x.text) : ex.hygiene)

/** The day: dates, status, what is clear, the small fixes, the workplace and the pages of group day.
 *  In the middle of Today as one panel, or on Start where a work tab exists as one card per block,
 *  where the pages of group day stand as a shelf of their own (DayPages); `pages` false leaves those out
 *  (the overview's day: dates, status and small fixes, the long log stays on Work) */
export function DayView({ s, c, cards = false, pages = true }) {
  const t = T()
  const m = s.model
  if (!m) return html`<${Skeleton} lines=${6} />`
  const ex = m.extras ?? {}
  // the page that lists the proposed tabs, where they open one by one
  const wpPage = (m.pages ?? []).find(p => (p.sections ?? []).some(x => x.kind === 'workplace'))
  const blocks = [
    { id: 'agenda', title: t.agendaTitle, body: (m.agenda ?? []).length
      ? html`<ul class="agenda">${m.agenda.map((a, i) => html`<li key=${i}><span class="mono agenda-when">${a.when}</span><span>${a.title}</span></li>`)}</ul>`
      : html`<${Empty}>${t.empty}<//>` },
    { id: 'status', title: t.statusTitle, body: html`<${StatusList} rows=${m.status} s=${s} c=${c} />` },
    (ex.clear ?? []).length ? { id: 'clear', title: t.clearTitle,
      body: html`<ul class="plain">${ex.clear.map((x, i) => html`<li key=${i}><${StateLine} token="success" word=${x} /></li>`)}</ul>` } : null,
    (ex.hygiene ?? []).length ? { id: 'hygiene', title: t.hygieneTitle,
      body: html`<ul class="plain">${tendLines(ex, t).map((x, i) => html`<li key=${i}><${StateLine} token="warning" word=${x} /></li>`)}</ul>` } : null,
    ex.workplace ? { id: 'workplace', title: t.workplaceTitle,
      body: html`<p class="row-in">${ex.workplace.replace(/\s*\S+\?$/, '')}
        ${wpPage ? html`<${Btn} size="xs" variant="secondary" onClick=${() => c.setPage(wpPage.id)}>${t.workplaceOpen}<//>` : null}</p>` } : null,
  ].filter(Boolean)
  if (cards) {
    return blocks.map(b => html`<article key=${b.id} class=${`hcard day-card day-${b.id}`}>
      <div class="hcard-body"><h3 class="label-caps day-card-title">${b.title}</h3>${b.body}</div>
    </article>`)
  }
  const [agenda, status, ...rest] = blocks
  return html`<div class="day-view">
    ${s.ui?.area ? html`<p class="muted small">${t.allAreas}</p>` : null}
    <div class="ov-grid">
      <div class="ov-block"><h3 class="label-caps">${agenda.title}</h3>${agenda.body}</div>
      <div class="ov-block"><h3 class="label-caps">${status.title}</h3>${status.body}</div>
    </div>
    ${rest.map(b => html`<div key=${b.id} class="ov-block"><h3 class="label-caps">${b.title}</h3>${b.body}</div>`)}
    ${pages ? html`<${DayPages} s=${s} c=${c} />` : null}
  </div>`
}

/** The pages of group day (what happened today), one section each */
export function DayPages({ s, c, shelf = false }) {
  return (s.model?.pages ?? []).filter(p => p.group === 'day').map(p => html`<section key=${p.id}
    class=${shelf ? 'home-shelf day-more' : 'day-more'} aria-label=${p.title}>
    ${shelf ? html`<header class="home-shelf-head"><h2 class="home-shelf-title">${p.title}</h2></header>`
      : html`<h3 class="label-caps day-more-title">${p.title}</h3>`}
    ${(p.sections ?? []).map(sec => html`<${PageSection} key=${sec.id} page=${p} section=${sec} s=${s} c=${c} />`)}
  </section>`)
}

/** Status rows: failures and counts in view, the quiet ones (healthy, nothing to count) under one line */
function StatusList({ rows, s, c }) {
  const t = T()
  const { loud, quiet } = statusSplit(rows)
  const line = (x, i) => html`<li key=${i} title=${x.reason ?? undefined}>
    <${StateLine} token=${x.tone === 'neutral' ? 'on-surface-muted' : x.tone} strong=${x.tone === 'danger'} word=${x.title} />
    <span class="mono muted">${x.state === 'error' ? (x.reason || t.tone.bad) : x.state === 'skipped' ? skipText(x, t) : x.count}</span>
    ${c && skipFixable(x) ? html`<${SkipFix} s=${s} c=${c} title=${x.title} reason=${x.reason} />` : null}</li>`
  return html`<ul class="status-list">${loud.map(line)}</ul>
    ${quiet.length ? html`<details class="status-quiet">
      <summary class="muted">${t.statusQuiet(quiet.length)}</summary>
      <ul class="status-list">${quiet.map(line)}</ul>
    </details>` : null}`
}

/** Where the row comes from, in full: the word, the text as it was written (selectable, nothing cut), the ref,
 *  what kind of report it is, and whether a click in the cockpit filed it; null when nothing is known */
function FromFact({ row }) {
  const t = T()
  const o = originOf(row)
  if (!o && !row.inbox_kind) return null
  return html`<span class="meta-from">${o ? html`<${OriginTag} origin=${{ ...o, ref: null }} />` : null}
    ${o?.raw ? html`<span class="meta-from-raw">${o.raw}</span>` : null}
    ${o?.ref ? html`<span class="mono">${o.ref}</span>` : null}
    ${row.inbox_kind ? html`<span class="muted">${t.item.kindName[row.inbox_kind] ?? row.inbox_kind}</span>` : null}
    ${o?.via_cockpit ? html`<span class="muted">${t.originViaCockpit}</span>` : null}</span>`
}

function MetaList({ row, s }) {
  const t = T()
  // a source is a section id: its title on the dashboard's pages names it in words
  const titles = new Map((s?.model?.pages ?? []).flatMap(p => p.sections ?? []).map(x => [x.id, x.title]))
  const items = [
    ['bucket', row.bucket ? (t.bucket[row.bucket] ?? row.bucket) : null],
    ['section', row.section ? (t.section[row.section] ?? row.section) : null],
    ['gate', row.gate ? (t.gate[row.gate] ?? row.gate) : null],
    ['urgency', row.urgency ? (t.urgency[row.urgency] ?? row.urgency) : null],
    ['priority', row.priority],
    ['area', row.area],
    ['task_type', row.task_type],
    ['due', row.due ? formatDay(row.due, language(), true) : null],
    ['ref', row.ref],
    ['state', row.inbox_state ? (t.item.stateName[row.inbox_state] ?? row.inbox_state) : null],
    ['sources', (row.sources ?? []).map(x => titles.get(x) ?? x).join(', ') || null],
    ['from', FromFact({ row })],
  ].filter(([, v]) => v)
  return html`<dl class="meta">${items.map(([k, v]) => html`<div class="meta-item" key=${k}><dt>${t.meta[k]}</dt><dd>${v}</dd></div>`)}</dl>`
}

export function Segmented({ label, values, current, onPick, busy, u }) {
  return html`<div class="seg" role="group" aria-label=${label}>
    ${values.map(([v, word]) => html`<button type="button" key=${v} class=${`seg-btn${current === v ? ' is-on' : ''}`} data-u=${u ? `${u}-${v}` : undefined}
      aria-pressed=${String(current === v)} disabled=${busy} onClick=${() => current !== v && onPick(v)}>${word}</button>`)}
  </div>`
}

function TeamBlock({ row, s, c }) {
  const t = T()
  const teams = s.model?.teams ?? []
  const busy = !!s.ui.busy[row.key]
  if (row.inbox_id || !row.task) return null
  const team = row.team ? teams.find(x => x.id === row.team.team_id) : null
  const suggestions = (row.team_suggestions ?? []).map(id => teams.find(x => x.id === id)).filter(Boolean)
  if (!team && !suggestions.length) return null
  return html`<div class="block">
    <h3 class="label-caps">${t.teamTitle}</h3>
    ${team ? html`<div class="team-state">
      <span>${t.teamProgress(team.label, row.team.started, team.roles.length)}</span>
      <ol class="roles">${team.roles.map((r, i) => html`<li key=${r.id} class=${i < row.team.started ? 'is-done' : ''}>
        <${Dot} token=${i < row.team.started ? 'success' : 'on-surface-muted'} /><span>${r.name}</span><span class="muted mono">${r.mode}</span></li>`)}</ol>
      ${row.team.next_role
        ? row.team.ready
          ? html`<${Btn} size="xs" variant="primary" busy=${busy} onClick=${() => c.act('team_role', { key: row.key, team: team.id })}>${t.teamNext(row.team.next_role.name)}<//>`
          : html`<p class="muted">${t.waitsForRole(row.team.waiting_for ?? row.team.next_role.name)}</p>`
        : html`<p class="muted">${t.allRolesStarted}</p>`}
    </div>` : null}
    ${suggestions.length ? html`<div class="btn-row">${suggestions.filter(x => !team || x.id !== team.id).map(x => html`
      <${Btn} key=${x.id} size="xs" busy=${busy} title=${x.roles.map(r => r.name).join(', ')}
        onClick=${() => c.act('team_role', { key: row.key, team: x.id })}>${t.teamStart(x.label)}<//>`)}</div>` : null}
  </div>`
}

/** The area of an inbox item without a task: one of the configured areas (workplace.workspaces), or none.
 *  The router gives it one when it is filed; this is where a person puts it right. An item with a task
 *  shows the task's area and has no picker */
function AreaPick({ row, s, c, busy }) {
  const t = T()
  const areas = s.boot?.config?.areas ?? []
  if (!row.inbox_id || row.task || !areas.length) return null
  const current = row.area ?? ''
  const names = current && !areas.includes(current) ? [...areas, current] : areas
  return html`<div class="sub-block">
    <h4 class="sub-title">${t.areaPrefix}</h4>
    <select class="input input-sm area-pick" aria-label=${t.areaPrefix} disabled=${busy} value=${current}
      onChange=${e => { const v = e.currentTarget.value; if (v !== current) c.act('area', v ? { key: row.key, value: v } : { key: row.key }) }}>
      <option value="">${t.areaNone}</option>
      ${names.map(a => html`<option key=${a} value=${a}>${a}</option>`)}
    </select>
  </div>`
}

function ActionsBlock({ row, s, c }) {
  const t = T()
  const busy = !!s.ui.busy[row.key]
  return html`<div class="block block-actions">
    <h3 class="label-caps">${t.actionsTitle}</h3>
    <div class="btn-row"><${RowBar} row=${row} s=${s} c=${c} /></div>
    ${row.task && !row.inbox_id ? html`<${ReviewBlock} row=${row} s=${s} c=${c} />` : null}
    ${row.task && !row.inbox_id ? html`<${TaskSessions} row=${row} s=${s} c=${c} />` : null}
    ${row.inbox_id ? html`<div class="sub-block">
      <h4 class="sub-title">${t.urgencyPrefix}</h4>
      <${Segmented} label=${t.urgencyPrefix} busy=${busy} current=${row.urgency}
        values=${['now', 'today', 'later'].map(v => [v, t.urgency[v]])} onPick=${v => c.act('urgency', { key: row.key, value: v })} />
    </div>
    <${AreaPick} row=${row} s=${s} c=${c} busy=${busy} />` : row.task ? html`<div class="sub-block">
      <h4 class="sub-title">${t.prioPrefix}</h4>
      <${Segmented} label=${t.prioPrefix} busy=${busy} current=${row.priority}
        values=${['P0', 'P1', 'P2', 'P3'].map(v => [v, v])} onPick=${v => c.act('priority', { key: row.key, value: v })} />
    </div>` : null}
    ${(row.adopt_candidates ?? []).length ? html`<div class="sub-block">
      <h4 class="sub-title">${t.adoptTitle}</h4>
      <div class="btn-row">${row.adopt_candidates.map(a => html`<${Btn} key=${a.ref} size="xs" busy=${busy}
        onClick=${() => c.act('adopt', { key: row.key, tab_ref: a.ref })}>${a.workspace} / ${a.name}<//>`)}</div>
    </div>` : null}
  </div>`
}

/** The one close of a tab, wherever a point or a card has one (round 6d; the rule is logic.js tabCloseOffer): with
 *  an open task or inbox item behind the tab Done and close tab (verb tab_done, which the server resolves) and Close
 *  tab only beside it, else Close tab alone; nothing while the tab works or asks. A close whose answers went unseen
 *  arms on the first click (the second-click pattern of RowSteps, falling back after a few seconds). `strong` makes
 *  the lead button primary, `only` leaves out Done and close tab where the place offers its own (FlowAside's Done),
 *  `looking` where the tab's screen stands beside it (the Chat's room: what it handed back is in view, so no second
 *  click), `onClosed` runs after a close or a Done that went through (the Chat walks on) */
export function TabClose({ tab, s, c, size = 'xs', strong = false, only = false, looking = false, onClosed = null }) {
  const t = T()
  const offer = tabCloseOffer(tab, s)
  const [armed, setArmed] = useState(false)
  useEffect(() => {
    if (!armed) return undefined
    const id = setTimeout(() => setArmed(false), 4000)
    return () => clearTimeout(id)
  }, [armed])
  if (!offer) return null
  const busy = !!s.ui?.busy?.[tab.ref]
  const went = r => { if (r?.ok) onClosed?.(r) }
  const close = async () => {
    if (offer.unseen && !looking && !armed) { setArmed(true); return }
    setArmed(false)
    went(await c.act('tab_close', { tab_ref: tab.ref }))
  }
  const both = offer.done && !only
  const word = offer.done ? t.btnCloseTabOnly : t.btnCloseTab
  return html`<span class="tab-close">
    ${both ? html`<${Btn} size=${size} variant=${strong ? 'primary' : 'secondary'} busy=${busy}
      u="tab-done" onClick=${async () => went(await c.act('tab_done', { tab_ref: tab.ref }))}>${t.btnDoneCloseTab}<//>` : null}
    <${Btn} size=${size} variant=${strong && !both ? 'primary' : 'secondary'} busy=${busy} pressed=${armed ? true : undefined}
      u="tab-close" title=${armed ? t.closeTabUnseen : undefined} onClick=${close}>${armed ? t.closeTabSure(word) : word}<//>
  </span>`
}

export function TabControls({ tab, s, c, compact = false, slim = false }) {
  const t = T()
  const busy = !!s.ui.busy[tab.ref]
  const open = s.ui.openMsg === tab.ref
  const [text, setText] = useState('')
  const send = async () => {
    const v = text.trim()
    if (!v) return
    const r = await c.act('tab_send', { tab_ref: tab.ref, text: v })
    if (r) {
      setText('')
      c.setOpenMsg(null)
    }
  }
  const id = `msg-${tab.ref}`
  const settled = !!tab.settled || settledRefs(s.model?.returns, s.tabs?.tabs, s.now || Date.now()).has(tab.ref)
  if (slim) {
    const step = {
      yes: () => html`<${Btn} size="xs" variant="primary" busy=${busy} onClick=${() => c.act('tab_yes', { tab_ref: tab.ref })}>${t.btnYes}<//>`,
      no: () => html`<${Btn} size="xs" variant="secondary" busy=${busy} onClick=${() => c.act('tab_no', { tab_ref: tab.ref })}>${t.btnNo}<//>`,
      go_on: () => html`<${Btn} size="xs" variant="secondary" busy=${busy} onClick=${() => c.act('tab_go_on', { tab_ref: tab.ref })}>${t.btnGoOn}<//>`,
      close: () => html`<${TabClose} tab=${tab} s=${s} c=${c} strong />`,
      jump: () => html`<${Btn} size="xs" variant="ghost" busy=${busy} onClick=${() => c.act('tab_jump', { tab_ref: tab.ref })}>${t.btnToTab}<//>`,
      view: () => html`<${Btn} size="xs" variant="ghost" onClick=${() => c.openTabView(tab.ref)}>${t.btnTabView}<//>`,
    }
    return tabNextStep(tab, v => canTab(s, v), settled).map(k => step[k]())
  }
  return html`<div class="tab-ctl">
    <div class="btn-row">
      ${tab.state === 'needs-you' && canTab(s, 'key') ? html`
        <${Btn} size="xs" variant="primary" busy=${busy} onClick=${() => c.act('tab_yes', { tab_ref: tab.ref })}>${t.btnYes}<//>
        <${Btn} size="xs" variant="secondary" busy=${busy} onClick=${() => c.act('tab_no', { tab_ref: tab.ref })}>${t.btnNo}<//>` : null}
      ${tab.state === 'waiting' && !tab.filed_by && !settled && !tab.is_control ? html`<${Btn} size="xs" variant="secondary" busy=${busy}
        onClick=${() => c.act('tab_go_on', { tab_ref: tab.ref })}>${t.btnGoOn}<//>` : null}
      <${TabClose} tab=${tab} s=${s} c=${c} strong />
      ${canTab(s, 'focus') ? html`<${Btn} size="xs" variant="ghost" busy=${busy} onClick=${() => c.act('tab_jump', { tab_ref: tab.ref })}>${t.btnToTab}<//>` : null}
      ${canTab(s, 'screen') ? html`<${Btn} size="xs" variant="ghost" onClick=${() => c.openTabView(tab.ref)}>${t.btnTabView}<//>` : null}
      ${tab.live ? html`<${Btn} size="xs" variant="ghost" pressed=${open} onClick=${() => c.setOpenMsg(open ? null : tab.ref)}>${t.btnMessage}<//>` : null}
    </div>
    ${open ? html`<div class="field-row">
      <label class="sr-only" for=${id}>${t.msgPlaceholder}</label>
      <input id=${id} class="input" type="text" maxlength="2000" placeholder=${t.msgPlaceholder} value=${text}
        onInput=${e => setText(e.currentTarget.value)} onKeyDown=${e => { if (e.key === 'Enter') send() }} />
      <${Btn} size="xs" variant="primary" icon="send" busy=${busy} disabled=${!text.trim()} onClick=${send}>${t.btnSend}<//>
    </div>` : null}
  </div>`
}

function TabInfo({ row, s, c }) {
  const t = T()
  if (!row.tab) return null
  const tab = (s.tabs?.tabs ?? []).find(x => x.ref === row.tab.ref) ?? { ...row.tab, name: row.task ?? row.tab.ref, workspace: '', last: '' }
  return html`<div class="block tab-info">
    <h3 class="label-caps">${t.tabsTitle}</h3>
    <div class="tab-info-line">
      <${StateLine} token=${stateToken(tabStateKey(tab))} strong=${tab.state === 'needs-you'} word=${t.state[tabStateKey(tab)] ?? tab.state} />
      <span class="muted">${tab.workspace ? `${tab.workspace} / ` : ''}${tab.name}</span>
      ${tab.since_ms ? html`<span class="mono muted">${t.sinceFor(duration(s.now - tab.since_ms))}</span>` : null}
    </div>
    ${tab.last ? html`<p class="tab-last">${tab.last}</p>` : null}
    ${tab.filed_by ? html`<p class="muted"><${StateLine} token="success" word=${t.resultFiledLong} /></p>` : null}
    <${TabControls} tab=${tab} s=${s} c=${c} />
  </div>`
}

/** A failed detail load: what went wrong, and a button that tries again */
export function DetailFailed({ d, onRetry }) {
  const t = T()
  return html`<div class="detail-failed"><${StateLine} token="danger" word=${t.detailFailed(d.error)} />
    <${Btn} size="xs" variant="secondary" icon="reload" onClick=${onRetry}>${t.retry}<//></div>`
}

function InboxDetail({ id, s, c }) {
  const t = T()
  const d = s.details.inbox[id]
  const ver = s.model?.collected_ms ?? 0
  useEffect(() => { if (detailNeedsLoad(d, ver)) c.loadInbox(id) }, [id, ver, d?.stale])
  if (!d || (d.status === 'loading' && !d.data)) return html`<div class="block"><p class="muted"><${Spinner} /> ${t.loadingDetail}</p></div>`
  if (d.status === 'error') return html`<div class="block"><${DetailFailed} d=${d} onRetry=${() => c.loadInbox(id)} /></div>`
  const it = d.data.item ?? {}
  const events = d.data.events ?? []
  return html`<div class="block inbox-detail">
    <h3 class="label-caps">${t.inboxTitle}</h3>
    ${it.summary ? html`<p class="inbox-summary">${it.summary}</p>` : null}
    ${it.detail ? html`<p class="pre">${it.detail}</p>` : null}
    <div class="runs">
      <span class="label-caps">${t.runsLabel}</span>
      ${it.action_display ? html`<code class="runs-cmd">${it.action_display}</code>` : html`<span class="muted">${t.runsNone}</span>`}
    </div>
    ${events.length ? html`<details class="events"><summary>${t.eventsTitle(events.length)}</summary>
      <ol class="event-list">${events.map((e, i) => html`<li key=${i}><span class="mono muted">${String(e.at ?? '').replace('T', ' ').slice(0, 16)}</span>
        <span class="chip">${e.verb}</span><span class="muted">${e.by}</span>${e.until ? html`<span>${t.hiddenUntil(e.until)}</span>` : null}
        ${e.note ? html`<span>${e.note}</span>` : null}</li>`)}</ol></details>` : null}
  </div>`
}

function pageLinesFor(model, slug) {
  for (const p of model?.pages ?? []) for (const sec of p.sections ?? []) for (const it of sec.items ?? []) {
    if (it.task === slug && (it.lines ?? []).length) return it.lines
  }
  return []
}

export function Lines({ lines }) {
  const t = T()
  return html`<ul class="lines">${lines.map((l, i) => html`<li key=${i}><span class="line-kind">${t.lineKind[l.kind] ?? `${l.kind}: `}</span><span>${l.text}</span></li>`)}</ul>`
}

function TaskDetail({ slug, s, c, exclude, carded = false }) {
  const t = T()
  const d = s.details.task[slug]
  const ver = s.model?.collected_ms ?? 0
  useEffect(() => { if (detailNeedsLoad(d, ver)) c.loadTask(slug) }, [slug, ver, d?.stale])
  const byKey = indexRows(s.model)
  const entries = [...byKey.values()].filter(r => r.task === slug && r.key !== exclude && r.key !== `task:${slug}`)
  const lines = pageLinesFor(s.model, slug)
  let body
  if (!d || (d.status === 'loading' && !d.data)) body = html`<p class="muted"><${Spinner} /> ${t.loadingDetail}</p>`
  else if (d.status === 'error') body = html`<${DetailFailed} d=${d} onRetry=${() => c.loadTask(slug)} />`
  else {
    const f = d.data.front ?? {}
    const facts = ['status', 'priority', 'type', 'created', 'last_updated', 'origin', 'blocked_by'].filter(k => f[k])
    body = html`
      ${f.headline && !carded ? html`<p class="task-headline">${f.headline}</p>` : null}
      <dl class="meta">${facts.map(k => html`<div class="meta-item" key=${k}><dt>${t.front[k]}</dt>
        <dd>${k === 'status' ? (t.taskState[f[k]] ?? f[k]) : String(f[k])}</dd></div>`)}</dl>
      <div class="task-sections">
        <h4 class="sub-title">${t.taskSections} <code class="muted">${d.data.path}</code></h4>
        ${(d.data.sections ?? []).map((x, i) => html`<details key=${i} open=${i === 0}><summary>${x.heading}</summary>
          <p class="pre">${x.text}</p>${x.truncated ? html`<p class="muted">${t.truncated}</p>` : null}</details>`)}
      </div>
      ${(d.data.log ?? []).length ? html`<div class="sub-block"><h4 class="sub-title">${t.taskLog}</h4>
        <ol class="log-rows">${d.data.log.map((l, i) => html`<li key=${i}><span class="mono muted">${l.at}</span><span>${l.text}</span></li>`)}</ol></div>` : null}`
  }
  const kindRow = { key: `task:${slug}`, task: slug, work_kind: d?.data?.work_kind ?? byKey.get(`task:${slug}`)?.work_kind }
  // the head word is the kind (task, stream, closed task, ended stream), never "Task" over a stream
  const wk = workKindOf(kindRow, s) ?? 'task'
  return html`<div class="block task-detail">
    <h3 class="label-caps">${t.kind[wk] ?? t.taskTitle}: <span class="mono">${slug}</span></h3>
    <p class="detail-kind"><${KindTag} row=${kindRow} s=${s} /> <${OriginTag} row=${kindRow} origin=${d?.data?.origin ?? byKey.get(`task:${slug}`)?.origin ?? null} /></p>
    ${lines.length ? html`<${Lines} lines=${lines} />` : null}
    ${body}
    ${entries.length ? html`<div class="sub-block"><h4 class="sub-title">${t.taskEntries(wk)}</h4>
      <ul class="entries">${entries.map(r => html`<li key=${r.key} class="entry">
        <button type="button" class="btn-link" onClick=${() => c.select(r.key)}>${short(r.title, 80)}</button>
        <span class="entry-tags"><${KindTag} row=${r} s=${s} /><${OriginTag} row=${r} /></span>
        <span class="btn-row"><${RowBar} row=${r} s=${s} c=${c} pin=${false} /></span></li>`)}</ul></div>` : null}
  </div>`
}

/** The card chips a row detail leaves out: the priority chip and origin tag of its head, and what its MetaList,
 *  TaskDetail or InboxDetail facts below say (area, due, an inbox state, a task's status) */
function rowDetailSkip(row) {
  return ['priority', 'source', row.area ? 'area' : null, row.due ? 'due' : null,
    row.inbox_state || (row.task && !row.inbox_id) ? 'state' : null].filter(Boolean)
}

function RowDetail({ row, s, c }) {
  const t = T()
  const n = s.model?.numbers?.[row.key] ?? row.number
  const openTask = slug => c.select(`task:${slug}`)
  return html`<article class="panel panel-pad detail" aria-labelledby="detail-title">
    <${DetailBack} s=${s} c=${c} />
    <header class="detail-head">
      <span class="detail-eyebrow">${n ? html`<span class="sec-count mono"><span class="sr-only">${t.numberLabel(n)}</span><span aria-hidden="true">${n}</span></span>` : null}
        <span class="eyebrow">${t.section[row.section] ?? row.section}</span></span>
      <h2 class="detail-title" id="detail-title" tabindex="-1">${row.card?.title || row.title}</h2>
      <p class="detail-kind"><${KindTag} row=${row} s=${s} c=${c} link /> <${OriginTag} row=${row} /></p>
      <div class="detail-chips">
        <${ReturnChip} s=${s} rowKey=${[row.key, row.task ? `task:${row.task}` : null]} />
        ${row.tab ? html`<${Chip} token=${stateToken(tabStateKey(row.tab))}>${t.state[tabStateKey(row.tab)] ?? row.tab.state}<//>` : null}
        <${MarkChip} mark=${row.mark} /><${PrioChip} priority=${row.priority} />
        ${row.hidden_until ? html`<span class="chip">${t.hiddenUntil(formatDay(row.hidden_until, language()))}</span>` : null}
      </div>
      <${LinkView} link=${row.link} c=${c} onOpenTask=${openTask} />
      ${row.task ? html`<${Btn} size="xs" variant="ghost" onClick=${() => c.openInner(`task:${row.task}`)}>${t.item.inNet}<//>` : null}
    </header>
    <${ItemCard} card=${row.card} d=${describeOf(s, describeKey(row), row.describe)} dkey=${describeKey(row)} s=${s} c=${c}
      skip=${rowDetailSkip(row)} cls="detail-card" />
    <${ReturnPanel} s=${s} c=${c} keys=${[row.key, row.task ? `task:${row.task}` : null]} />
    <${MetaList} row=${row} s=${s} />
    ${(row.why ?? []).length ? html`<div class="block"><h3 class="label-caps">${t.whyTitle}</h3>
      <ul class="why">${row.why.map((w, i) => html`<li key=${i}>${w}</li>`)}</ul></div>` : null}
    ${row.inbox_id ? html`<${InboxDetail} id=${row.inbox_id} s=${s} c=${c} />` : null}
    <${TabInfo} row=${row} s=${s} c=${c} />
    <${ActionsBlock} row=${row} s=${s} c=${c} />
    ${row.hidden_until ? html`<div class="block"><${Btn} size="xs" onClick=${() => c.act('unhide', { key: row.key })}>${t.btnShowAgain}<//></div>` : null}
    <${TeamBlock} row=${row} s=${s} c=${c} />
    ${row.task ? html`<${TaskDetail} slug=${row.task} s=${s} c=${c} exclude=${row.key} carded=${!row.inbox_id && !!row.card?.summary} />` : null}
  </article>`
}

/** The walk through the list this detail was opened from, as a small bar that stays at the foot of
 *  the column or drawer however long the detail runs: back, where you stand, the next entry with
 *  "next" (key n), and the two after it as plain links. A settled entry drops out at once */
export function NextUp({ s, c, byKey, current, queue = s.ui.queue }) {
  const t = T()
  const live = queueLiveKeys(s.model, s.more)
  const v = current ? queueView(queue, current, e => live.has(e.key)) : null
  if (!v || v.total < 2) return null
  const look = e => s.triage?.items?.[e.key]?.gist || (byKey.get(e.key)?.why ?? [])[0] || undefined
  // kind and source of every entry of the walk; a page item the model holds no row for (By source) reads its own
  const entry = (e, max) => {
    const r = byKey.get(e.key) ?? (e.it ? itemRow(e.it) : null)
    return { key: e.key, title: short(e.title || byKey.get(e.key)?.title || e.key, max), look: look(e), onOpen: () => c.openNext(e),
      sub: r ? html`<span class="entry-tags"><${KindTag} row=${r} s=${s} /><${OriginTag} row=${r} /></span>` : null }
  }
  const [next, ...later] = v.next
  return html`<${WalkBar} label=${t.nextLabel} shortcuts=${s.ui.shortcuts} pos=${[v.pos, v.total]} onPrev=${v.prev ? () => c.openNext(v.prev) : null}
    next=${next ? entry(next, 90) : null} later=${later.map(e => entry(e, 80))} done=${t.nextDone} />`
}

/** Back to the list: "close details" beside a page, "back" on a phone, nothing on a wide briefing */
function DetailBack({ s, c }) {
  const t = T()
  if (s.ui.pageDetail) return html`<${Btn} variant="ghost" size="xs" icon="back" onClick=${c.closePeek}>${t.closeDetail}<//>`
  if (s.layout === 'narrow') return html`<${Btn} variant="ghost" size="xs" icon="back" onClick=${() => c.setPane('day')}>${t.back}<//>`
  return null
}

export function DetailColumn({ s, c, byKey }) {
  const t = T()
  const key = s.ui.selectedKey
  const row = key ? byKey.get(key) : null
  let body
  if (!key) body = html`<${Overview} s=${s} c=${c} />`
  else if (row) body = html`<${RowDetail} key=${row.key} row=${row} s=${s} c=${c} />`
  else if (key.startsWith('task:')) {
    const data = s.details?.task?.[key.slice(5)]?.data
    const wk = data?.work_kind ?? workKindOf({ task: key.slice(5) }, s) ?? 'task'
    body = html`<article class="panel panel-pad detail">
      <${DetailBack} s=${s} c=${c} />
      <header class="detail-head"><span class="eyebrow">${t.kind[wk] ?? t.taskTitle}</span><h2 class="detail-title">${data?.card?.title || key.slice(5)}</h2>
        <p class="detail-kind"><${KindTag} row=${{ key, task: key.slice(5), work_kind: wk }} s=${s} />
          <${OriginTag} origin=${data?.origin ?? null} /></p></header>
      <${ItemCard} card=${data?.card} d=${describeOf(s, key, data?.describe)} dkey=${key} s=${s} c=${c} skip=${TASK_FACTS_SKIP} cls="detail-card" />
      <${TaskDetail} slug=${key.slice(5)} s=${s} c=${c} carded=${!!data?.card?.summary} /></article>`
  } else {
    body = html`<div class="panel panel-pad"><p class="muted">${t.rowGone}</p>
      ${s.ui.pageDetail ? html`<${Btn} size="xs" onClick=${c.closePeek}>${t.closeDetail}<//>`
        : html`<${Btn} size="xs" onClick=${() => c.select(null)}>${t.overviewTitle}<//>`}</div>`
  }
  return html`<div class="col col-detail">
    <div class="detail-scroll">${body}</div>
    ${s.ui.pageDetail ? html`<${NextUp} s=${s} c=${c} byKey=${byKey} current=${key} />`
      : key ? html`<${NextUp} s=${s} c=${c} byKey=${byKey} current=${key} queue=${dayQueue(s.model)} />` : null}
  </div>`
}
