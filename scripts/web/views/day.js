// SPDX-License-Identifier: MIT
// The cockpit, the day column: the four blocks of the work tab.
// The rules every component keeps stand at the head of components.js.

import { html, useEffect, useRef, useState } from '../vendor/htm-preact-3.1.1.module.js'
import {
  attentionTabs, duration, formatDay, indexRows, pageWarnings, sectionRows, short, stateToken, canTab, actionRow,
  pageItemActs, workPageOf, workViews,
  SECTION_ORDER, dueWhen, rowBudgets, whyWithoutDue,
} from '../logic.js'
import { T, language } from '../text.js'
import { CheckButton } from './check.js'
import { AlarmBanner } from './header.js'
import { PinStar, ReturnChip } from './home.js'
import { LaunchPick } from './launch.js'
import { workViewNow } from './nav.js'
import { usePopover } from './pages.js'
import { Btn, Chip, Dot, Empty, MarkChip, PrioChip, StateLine, VerdictChip } from './parts.js'

// ---------------------------------------------------------------- left column: the day

export function RowMeta({ row, s }) {
  const t = T()
  const parts = []
  if (row.tab) parts.push(html`<${Chip} token=${stateToken(row.tab.state)}>${t.state[row.tab.state] ?? row.tab.state}<//>`)
  if (row.starting) parts.push(html`<${Chip} token="info">${t.startingTab}<//>`)
  const liveSessions = row.task && !row.inbox_id ? (s?.sessions?.sessions ?? []).filter(x => x.task === row.task).length : 0
  if (liveSessions) parts.push(html`<span class="chip chip-task">${t.sessionsOnTask(liveSessions)}</span>`)
  const topic = s?.triage?.items?.[row.key]?.topic
  if (topic && t.topic[topic]) parts.push(html`<span class="chip chip-topic" title=${t.topicTitle}>${t.topic[topic]}</span>`)
  if (row.mark) parts.push(html`<${MarkChip} mark=${row.mark} />`)
  if (row.priority) parts.push(html`<${PrioChip} priority=${row.priority} />`)
  if (row.review) parts.push(html`<${VerdictChip} review=${row.review} />`)
  if (row.urgency === 'now' || row.urgency === 'today') parts.push(html`<${Chip} token=${row.urgency === 'now' ? 'danger' : 'warning'}>${t.urgency[row.urgency]}<//>`)
  const due = dueWhen(row.due, s?.now ?? Date.now())
  if (due) {
    const word = due.kind === 'overdue' ? t.dueOverdue(due.days) : due.kind === 'today' ? t.dueToday : due.kind === 'tomorrow' ? t.dueTomorrow
      : t.dueOn(formatDay(row.due, language()))
    parts.push(due.kind === 'overdue' || due.kind === 'today'
      ? html`<${Chip} token=${due.kind === 'overdue' ? 'danger' : 'warning'} cls="meta-due">${word}<//>`
      : html`<span class="meta-due">${word}</span>`)
  }
  if (row.is_new) parts.push(html`<span class="chip chip-active">${t.isNew}</span>`)
  else if (row.is_changed) parts.push(html`<span class="chip chip-active">${t.isChanged}</span>`)
  if (row.area && row.area !== row.mark?.label) parts.push(html`<span class="meta-area">${row.area}</span>`)
  const why = (row.due ? whyWithoutDue(row.why) : row.why ?? []).slice(0, 2).join(' · ')
  return html`<span class="row-meta">${parts}${why ? html`<span class="meta-why">${why}</span>` : null}</span>`
}

export function RowActions({ row, s, c, all = false }) {
  const t = T()
  const busy = !!s.ui.busy[row.key]
  const list = (row.actions ?? []).filter(a => all || a.primary || a.id === 'approved')
  return list.map(a => a.id === 'approved'
    ? html`<span class="chip chip-done" key=${a.id}><${Dot} token="success" /><span>${t.action.approved}</span></span>`
    : html`<${Btn} key=${a.id} size="xs" variant=${a.primary ? 'primary' : a.dim ? 'ghost' : 'secondary'} busy=${busy}
        onClick=${() => c.rowAction(row, a.id)}>${t.action[a.id] ?? a.id}<//>`)
}

/** Close in two clicks: "Close" opens the two outcomes, a click on one settles the row. A task also
 *  offers the longer dialog with every reason. Escape or a click outside closes the menu */
export function SettleMenu({ rows, s, c, size = 'xs' }) {
  const t = T()
  const [open, setOpen] = useState(false)
  const box = usePopover(open, setOpen)
  const ok = rows.filter(r => (r.settle ?? []).length)
  if (!ok.length) return null
  const keys = ok.map(r => r.key)
  const busy = !!s.ui.busy[keys.join(',')] || ok.some(r => s.ui.busy[r.key])
  const pick = outcome => { setOpen(false); c.act('settle', { keys, outcome }) }
  const tasks = ok.filter(r => r.closable)
  return html`<span class="settle" ref=${box}>
    <${Btn} size=${size} variant="ghost" busy=${busy} pressed=${open} onClick=${() => setOpen(!open)}
      label=${ok.length > 1 ? t.settleMany(ok.length) : t.settle}>${ok.length > 1 ? t.settleMany(ok.length) : t.settle} ▾<//>
    ${open ? html`<span class="settle-menu" role="menu">
      <button type="button" role="menuitem" class="settle-item" onClick=${() => pick('done')}>
        <${Dot} token="success" /><span>${t.settleDone}</span></button>
      <button type="button" role="menuitem" class="settle-item" onClick=${() => pick('not_doing')}>
        <${Dot} token="on-surface-muted" /><span>${t.settleNot}</span></button>
      <button type="button" role="menuitem" class="settle-item" onClick=${() => { setOpen(false); c.askRunsOn(ok) }}>
        <${Dot} token="info" /><span>${t.settleRuns}</span></button>
      ${ok.length === 1 && ok[0].task && ok[0].bucket === 'waiting' && !ok[0].inbox_id ? html`<button type="button" role="menuitem" class="settle-item"
        onClick=${() => { setOpen(false); c.act('task_running', { slug: ok[0].task }) }}><${Dot} token="success" /><span>${t.settleAgain}</span></button>` : null}
      ${ok.length === 1 && ok[0].inbox_id && ok[0].runs ? html`<button type="button" role="menuitem" class="settle-item"
        onClick=${() => { setOpen(false); c.act('inbox_reopen', { id: ok[0].inbox_id }) }}><${Dot} token="success" /><span>${t.settleAgain}</span></button>` : null}
      ${ok.length === 1 && ok[0].inbox_id ? html`<button type="button" role="menuitem" class="settle-item"
        onClick=${() => { setOpen(false); c.act('to_task', { key: ok[0].key }) }}><${Dot} token="info" /><span>${t.settleToTask}</span></button>` : null}
      ${tasks.length === ok.length ? html`<button type="button" role="menuitem" class="settle-item settle-more"
        onClick=${() => { setOpen(false); c.askClose(tasks) }}><span>${t.settleMore}</span></button>` : null}
      ${ok.some(r => !r.task && !r.inbox_id) ? html`<span class="settle-hint muted small">${t.settleHint}</span>` : null}
    </span>` : null}
  </span>`
}

/** The buttons of a page row that is no inbox item or task but a person can hand on: the same Do it, Advise
 *  and Settle as a work row. The server files it to the inbox first and starts on that */
export function PageItemActions({ it, s, c, after }) {
  const t = T()
  if (!pageItemActs(it)) return null
  const row = actionRow(it, new Map())
  const busy = !!s.ui.busy[it.key]
  // `after` runs once a step went through (the detail drawer closes with it)
  const run = verb => Promise.resolve(c.rowAction(row, verb)).then(r => { if (r?.ok) after?.() })
  const cc = after ? { ...c, act: async (verb, args) => { const r = await c.act(verb, args); if (r?.ok) after(); return r } } : c
  return html`<${Btn} size="xs" variant="primary" busy=${busy} onClick=${() => run('do')}>${t.action.do}<//>
    <${Btn} size="xs" variant="secondary" busy=${busy} onClick=${() => run('advise')}>${t.action.advise}<//>
    <${SettleMenu} rows=${[row]} s=${s} c=${cc} />`
}

/** What the small model says a row is about (triage.py gist), when it says more than the title */
function gistOf(row, s) {
  const gist = String(s.triage?.items?.[row.key]?.gist ?? '').trim()
  const norm = x => x.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').trim()
  if (!gist || norm(row.title).startsWith(norm(gist)) || norm(gist).startsWith(norm(row.title))) return null
  return gist
}

function RowItem({ row, s, c }) {
  const t = T()
  const selected = s.ui.selectedKey === row.key
  const focused = s.ui.focusKey === row.key
  const picked = s.ui.picked.includes(row.key)
  const n = s.model?.numbers?.[row.key] ?? row.number
  return html`<li class=${`row${selected ? ' is-selected' : ''}${focused ? ' is-focused' : ''}${row.tab?.waiting ? ' is-waiting' : ''}`} data-key=${row.key}>
    <span class="row-num mono" aria-label=${t.numberLabel(n)}>${n}</span>
    ${row.selectable
      ? html`<input class="row-pick" type="checkbox" checked=${picked} aria-label=${t.select(short(row.title, 40))}
          onChange=${() => c.togglePick(row.key)} />`
      : html`<span class="row-pick-gap" aria-hidden="true"></span>`}
    <button type="button" class="row-main" aria-current=${selected ? 'true' : undefined}
      onClick=${() => c.select(row.key)} onFocus=${() => c.focusRow(row.key)}>
      <span class="row-title">${short(row.title, 110)}</span>
      ${gistOf(row, s) ? html`<span class="row-gist">${gistOf(row, s)}</span>` : null}
      <${RowMeta} row=${row} s=${s} />
      <${ReturnChip} s=${s} rowKey=${[row.key, row.task ? `task:${row.task}` : null]} />
    </button>
    <span class="row-acts"><${RowActions} row=${row} s=${s} c=${c} /><${SettleMenu} rows=${[row]} s=${s} c=${c} /><${PinStar} rowKey=${row.key} s=${s} c=${c} /></span>
  </li>`
}

function Section({ section, s, c, byKey, budget = 0 }) {
  const t = T()
  const expanded = !!s.ui.expanded[section.id]
  const rows = sectionRows(section, expanded, byKey, budget)
  const all = section.rows?.length ?? section.total
  const hiddenCount = Math.max(0, section.total - rows.length)
  // "approve all n" counts every row of the section, also the ones the compact view leaves out
  const approvable = section.id === 'give'
    ? (section.rows ?? rows).map(r => r.key).filter(k => (s.model?.approvable ?? []).includes(k)) : []
  return html`<section class="sec" aria-labelledby=${`sec-${section.id}`}>
    <header class="sec-head">
      <h2 class="sec-title" id=${`sec-${section.id}`}>${t.section[section.id] ?? section.id}
        <span class="sec-count mono">${section.total}</span></h2>
      <span class="sec-tools">
        ${section.id === 'work' ? html`<${CheckButton} s=${s} c=${c} size="xs" />` : null}
        ${approvable.length > 1 ? html`<${Btn} size="xs" variant="secondary" busy=${!!s.ui.busy[approvable.join(',')]}
          onClick=${() => c.approveAll(approvable)}>${t.approveAll(approvable.length)}<//>` : null}
        ${hiddenCount > 0 || expanded
          ? html`<button type="button" class="btn-link" aria-expanded=${String(expanded)} onClick=${() => c.toggleSection(section.id)}>
              ${expanded ? t.btnCompact : rows.length ? t.allN(all) : t.showN(section.total)}</button>` : null}
      </span>
    </header>
    ${rows.length
      ? html`<ol class="rows">${rows.map(r => html`<${RowItem} key=${r.key} row=${r} s=${s} c=${c} />`)}</ol>`
      : section.total === 0 ? html`<${Empty}>${t.empty}<//>` : null}
  </section>`
}

function TabMini({ tab, s, c }) {
  const t = T()
  const busy = !!s.ui.busy[tab.ref]
  const age = duration(s.now - (tab.since_ms || s.now))
  return html`<li class="tabmini">
    <span class="tabmini-main">
      <${StateLine} token=${stateToken(tab.state)} strong=${tab.state === 'needs-you'} word=${t.state[tab.state] ?? tab.state} />
      <span class="tabmini-name" title=${tab.last}>${tab.workspace} / ${tab.name}</span>
      <span class="tabmini-age mono">${age}</span>
      ${tab.long ? html`<span class="chip chip-warn-outline">${t.tabLong}</span>` : null}
    </span>
    <span class="tabmini-acts">
      ${tab.state === 'needs-you' && canTab(s, 'key') ? html`
        <${Btn} size="xs" variant="primary" busy=${busy} onClick=${() => c.act('tab_yes', { tab_ref: tab.ref })}>${t.btnYes}<//>
        <${Btn} size="xs" variant="secondary" busy=${busy} onClick=${() => c.act('tab_no', { tab_ref: tab.ref })}>${t.btnNo}<//>` : null}
      ${canTab(s, 'focus') ? html`<${Btn} size="xs" variant="ghost" busy=${busy} onClick=${() => c.act('tab_jump', { tab_ref: tab.ref })}>${t.btnToTab}<//>` : null}
    </span>
  </li>`
}

function WaitingTabs({ s, c }) {
  const t = T()
  const [all, setAll] = useState(false)
  const list = attentionTabs(s.tabs?.tabs)
  if (!list.length) return null
  const shown = all ? list : list.slice(0, 4)
  const long = list.filter(x => x.long).length
  return html`<section class="sec sec-tabs" aria-labelledby="sec-waiting-tabs">
    <header class="sec-head">
      <h2 class="sec-title" id="sec-waiting-tabs">${t.tabsWaitingTitle} <span class="sec-count mono">${list.length}</span>
        ${long ? html`<span class="muted sec-sub"> ${t.longCount(long)}</span>` : null}</h2>
      ${list.length > 4 ? html`<button type="button" class="btn-link" aria-expanded=${String(all)} onClick=${() => setAll(!all)}>
        ${all ? t.btnCompact : t.allN(list.length)}</button>` : null}
    </header>
    <ul class="tabminis">${shown.map(tab => html`<${TabMini} key=${tab.ref} tab=${tab} s=${s} c=${c} />`)}</ul>
  </section>`
}

function SelectionBar({ s, c }) {
  const t = T()
  const n = s.ui.picked.length
  if (!n) return null
  const keys = s.ui.picked
  const busy = !!s.ui.busy[keys.join(',')]
  return html`<div class="selbar" role="region" aria-label=${t.picked(n)}>
    <strong>${t.picked(n)}</strong>
    <span class="selbar-acts">
      <${Btn} size="xs" variant="primary" busy=${busy} onClick=${() => c.act('do_it', { keys })}>${t.action.do}<//>
      <${Btn} size="xs" variant="secondary" busy=${busy} onClick=${() => c.act('advise', { keys })}>${t.action.advise}<//>
      <${Btn} size="xs" variant="secondary" busy=${busy} onClick=${() => c.act('do_it', { keys, target: 'workspace' })}>${t.btnEachOwnWs}<//>
      <${SettleMenu} rows=${keys.map(k => indexRows(s.model).get(k)).filter(Boolean)} s=${s} c=${c} />
      <${Btn} size="xs" variant="ghost" onClick=${c.clearPicks}>${t.btnClear}<//>
    </span>
    <${LaunchPick} s=${s} c=${c} items=${keys.map(k => ({ key: k, title: indexRows(s.model).get(k)?.title ?? '' }))} />
  </div>`
}

function HiddenList({ s, c }) {
  const t = T()
  const list = s.model?.hidden ?? []
  if (!list.length) return null
  return html`<details class="hidden-rows">
    <summary>${t.hiddenTitle(list.length)}</summary>
    <ul>
      ${list.map(r => html`<li key=${r.key} class="hidden-row">
        <button type="button" class="btn-link hidden-title" onClick=${() => c.select(r.key)}>${short(r.title, 70)}</button>
        <span class="muted">${r.settled_as ? t.settledAs[r.settled_as] : t.hiddenUntil(formatDay(r.hidden_until, language()))}</span>
        <${Btn} size="xs" variant="ghost" busy=${!!s.ui.busy[r.key]} onClick=${() => c.act('unhide', { key: r.key })}>${t.btnShowAgain}<//>
      </li>`)}
    </ul>
  </details>`
}

/** The views of the work tab as one row of chips: what is due, by source, by Jev */
export function WorkSwitch({ s, c }) {
  const t = T()
  const views = workViews(workPageOf(s.model?.pages), s.jev)
  if (views.length < 2) return null
  const view = workViewNow(s)
  return html`<div class="fbar-chips work-switch" role="radiogroup" aria-label=${t.workOrder.viewLabel}>
    ${views.map(v => html`<button type="button" role="radio" key=${v} aria-checked=${String(view === v)}
      class=${`fchip${view === v ? ' is-on' : ''}`} onClick=${() => c.setWorkView(v)}>${t.workOrder.views[v]}</button>`)}
  </div>`
}

/** The day column reports its height, so its sections fill the room it has (logic.js rowBudgets) */
function useDayHeight(c, on) {
  const ref = useRef(null)
  useEffect(() => {
    const el = ref.current
    if (!el || typeof ResizeObserver === 'undefined') return undefined
    const report = () => c.setDayHeight(Math.round(el.clientHeight / 32) * 32)
    const ro = new ResizeObserver(report)
    ro.observe(el)
    report()
    return () => ro.disconnect()
  }, [on])
  return ref
}

export function DayColumn({ s, c, byKey }) {
  const t = T()
  const m = s.model
  const colRef = useDayHeight(c, !!m)
  if (!m) {
    // without a model a failed pass or a lost connection is said, not an endless skeleton
    const warnings = pageWarnings(s, t)
    if (warnings.length) {
      return html`<div class="col col-day"><div class="panel panel-pad">${warnings.map(w => html`<p key=${w.word}>
        <${StateLine} token=${w.token} strong word=${w.word} /></p>`)}</div></div>`
    }
    return html`<div class="col col-day" aria-busy="true"><div class="panel panel-pad"><${Skeleton} lines=${7} /></div></div>`
  }
  const total = (m.sections ?? []).reduce((a, x) => a + (x.total ?? 0), 0)
  const budgets = rowBudgets(m.sections, s.ui.expanded ?? {}, s.ui.dayHeight ?? 0)
  return html`<div class="col col-day" ref=${colRef}>
    <div class=${`panel day-panel${s.ui.picked.length ? ' is-picking' : ''}`}>
      <${WorkSwitch} s=${s} c=${c} />
      <${SelectionBar} s=${s} c=${c} />
      <${AlarmBanner} s=${s} c=${c} />
      <div class="day-counts muted"><span class="day-asof">${t.sourceAsOf(m.collected_at)}</span></div>
      ${s.layout === 'wide' ? null : html`<${WaitingTabs} s=${s} c=${c} />`}
      ${total === 0 && !attentionTabs(s.tabs?.tabs).length ? html`<div class="callout">${t.emptyHint}</div>` : null}
      ${total === 0 ? null : SECTION_ORDER.map(id => {
        const sec = (m.sections ?? []).find(x => x.id === id)
        return sec ? html`<${Section} key=${id} section=${sec} s=${s} c=${c} byKey=${byKey} budget=${budgets[id] ?? 0} />` : null
      })}
      <${HiddenList} s=${s} c=${c} />
    </div>
  </div>`
}

export function Skeleton({ lines = 5 }) {
  return html`<div class="skeleton" aria-hidden="true">${Array.from({ length: lines }, (_, i) => html`<span key=${i} class="skel-line"></span>`)}</div>`
}
