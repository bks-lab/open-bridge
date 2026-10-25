// SPDX-License-Identifier: MIT
// The cockpit, the day column: the four blocks of the work tab.
// The rules every component keeps stand at the head of components.js.

import { html, useEffect, useLayoutEffect, useRef, useState } from '../vendor/htm-preact-3.1.1.module.js'
import {
  attentionTabs, duration, formatDay, indexRows, pageWarnings, sectionRows, short, stateToken, canTab, actionRow,
  pageItemActs, workPageOf, workViews, startMode, parseDate, isoDate, launchChoice, rowKind, repoGroups,
  SECTION_ORDER, dueWhen, rowBudgets, whyWithoutDue, tabStateKey
} from '../logic.js'
import { T, language } from '../text.js'
import { CheckButton } from './check.js'
import { AlarmBanner } from './header.js'
import { PinStar, ReturnChip } from './home.js'
import { LaunchPick } from './launch.js'
import { workViewNow } from './nav.js'
import { usePopover } from './pages.js'
import { Btn, Chip, Dot, Empty, MarkChip, PrioChip, StateLine, VerdictChip, useRoving } from './parts.js'

// ---------------------------------------------------------------- left column: the day

const KIND_MARK = { task: '▣', stream: '↻', inbox: '◆', issue: '#', other: '•' }

/** What a row is (rowKind), first on every row and in every head, in one shape that stands apart from the state
 *  chips: the state changes, the kind does not. A report about a task names it; `link` makes that name open the
 *  task (not inside a row's own button, where a second button cannot stand) */
export function KindTag({ row, s, c, link = false }) {
  const t = T()
  const k = rowKind(row)
  const title = k.task ? (indexRows(s?.model).get(`task:${k.task}`)?.title ?? k.task) : null
  const about = k.kind === 'inbox' && k.task
    ? html`<span class="kind-about"> · ${t.kindAbout} ${link && c
      ? html`<button type="button" class="btn-link" onClick=${() => c.select(`task:${k.task}`)}>${short(title, 48)}</button>`
      : short(title, 48)}</span>` : null
  const detail = k.kind === 'issue' ? html` <span class="mono">${k.ref}</span>` : k.kind === 'other' && k.source ? html` · ${k.source}` : null
  return html`<span class=${`kind kind-${k.kind}`} title=${t.kindTitle[k.kind]}>
    <span class="kind-mark" aria-hidden="true">${KIND_MARK[k.kind]}</span><span>${t.kind[k.kind]}${detail}</span></span>${about}`
}

export function RowMeta({ row, s }) {
  const t = T()
  const parts = [html`<${KindTag} row=${row} s=${s} />`]
  if (row.tab) parts.push(html`<${Chip} token=${stateToken(tabStateKey(row.tab))}>${t.state[tabStateKey(row.tab)] ?? row.tab.state}<//>`)
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

/** What one can do with a row, in a panel behind the two doors of its bar, the same on every view. One sentence
 *  field on top; what the sentence becomes depends on the door. "Let AI do it ▾" (part start): the order for the
 *  agent, with the groups that hand the row on (start, advise, ask). "Close ▾" (part settle): a comment, with the
 *  groups that take the row off the list (done or discard, not now, keep a note). Every decision is written where
 *  the row lives, the sentence with it: a task's or stream's notes, an inbox item's notes, the log for any other row
 *  (actions_work.py write_note). Without a sentence each button does what it always did. Several rows (a selection)
 *  get the groups that work on many */
function RowPanel({ rows, s, c, part, close, anchor, seed }) {
  const t = T()
  const [text, setText] = useState(seed ?? '')
  const [asking, setAsking] = useState(null)       // the outcome a stream's end waits on
  const field = useRef(null)
  const first = useRef(null)
  const me = useRef(null)
  const origin = useRef(null)
  // fixed in the window under its door, kept inside the window: a column, a card or a table that clips its
  // content (the detail column does) can no longer cut it off. Above the door when there is more room there
  const [at, setAt] = useState(null)
  const place = () => {
    const a = anchor.current?.getBoundingClientRect()
    const el = me.current
    if (!a || !el) return
    const w = el.offsetWidth
    const h = el.scrollHeight
    const left = Math.max(8, Math.min(a.left, window.innerWidth - w - 8))
    const below = window.innerHeight - a.bottom - 12
    const above = a.top - 12
    // a container (container-type) or a transform on an ancestor makes fixed relative to that ancestor, not to the
    // window (the start page's tiles sit in one): a still point at 0,0 beside the panel says where that lands
    const o = origin.current?.getBoundingClientRect() ?? { left: 0, top: 0 }
    setAt(h <= below || below >= above
      ? { left: left - o.left, top: a.bottom + 4 - o.top, max: below }
      : { left: left - o.left, top: Math.max(8, a.top - 4 - Math.min(h, above)) - o.top, max: above })
  }
  useLayoutEffect(() => {
    place()
    window.addEventListener('resize', place)
    window.addEventListener('scroll', place, true)
    return () => { window.removeEventListener('resize', place); window.removeEventListener('scroll', place, true) }
  }, [])
  const style = at ? { left: `${at.left}px`, top: `${at.top}px`, maxHeight: `${at.max}px` } : { visibility: 'hidden' }
  // the door's own popover moves the focus to the first item after this effect ran (a child's effects run
  // first), so the move waits one turn: the start door types, the close door picks
  useEffect(() => { const id = setTimeout(() => (part === 'start' ? field : first).current?.focus(), 0); return () => clearTimeout(id) }, [])
  const keys = rows.map(r => r.key)
  const one = rows.length === 1 ? rows[0] : null
  const mode = one ? startMode(one) : null
  const x = text.trim()
  const streams = rows.some(r => r.stream)
  const launchable = !!(one && (one.inbox_id || one.task))
  // several rows: the ones an agent can start on (no tab already on it, not approved already)
  const starts = one ? [] : rows.filter(r => (r.inbox_id || r.task) && ['do', 'note', 'restart'].includes(startMode(r)))
  const done = fn => { close(); setText(''); return fn() }
  const settle = outcome => {
    if (streams && asking !== outcome) { setAsking(outcome); return }
    done(() => c.act('settle', { keys, outcome, ...(x ? { text: x } : {}), ...(streams ? { stream: true } : {}) }))
  }
  // Discard on one inbox item without a reason asks why: the reason there can mute a noisy source
  const discard = () => (one?.inbox_id && !x ? done(() => c.askDrop(one)) : settle('not_doing'))
  const [day, setDay] = useState('')
  const [dayErr, setDayErr] = useState('')
  const untilDay = () => {
    const iso = parseDate(day, s.now)
    if (!iso) return setDayErr(t.noDate(day || ' '))
    if (iso <= isoDate(s.now)) return setDayErr(t.pastDate)
    later(r => c.act('later', { key: r.key, until: iso, ...(x ? { text: x } : {}) }))
  }
  const later = fn => done(() => rows.forEach(fn))
  const item = (word, onClick, { token = null, off = false, ref = null } = {}) => html`<button type="button" role="menuitem"
    class="settle-item" disabled=${off} ref=${ref} onClick=${onClick}>${token ? html`<${Dot} token=${token} />` : null}<span>${word}</span></button>`
  const group = (title, body, extra = null) => html`<div class="panel-group" role="group" aria-label=${title}>
    <span class="panel-group-head"><span class="label-caps">${title}</span>${extra}</span><div class="panel-group-body">${body}</div></div>`
  const needsWords = mode === 'note'
  const go = () => c.act('do_it', { keys: one ? keys : starts.map(r => r.key), ...(x ? { note: x } : {}) })
  const canGo = one ? (mode === 'do' || mode === 'restart' || (mode === 'note' && x)) : starts.length
  const startPart = () => html`${one ? group(t.grp.start, mode === 'approved'
      ? item(t.approvedBack, () => done(() => c.act('inbox_reopen', { id: one.inbox_id })))
      : mode === 'tab'
        ? html`${item(t.sendHint, () => done(() => c.act('do_it', { keys, ...(x ? { note: x } : {}) })), { off: !x, token: 'info' })}
            ${item(t.btnTabView, () => done(() => c.openTabView(one.tab.ref)))}`
        : html`${item(mode === 'restart' ? t.action.restart : t.action.do, () => done(() => c.act('do_it', { keys, ...(x ? { note: x } : {}) })), { off: needsWords && !x, token: 'info' })}
            ${item(t.action.advise, () => done(() => c.act('advise', { keys, ...(x ? { note: x } : {}) })))}
            ${launchable ? item(t.btnCollect, () => done(() => c.act('collect_context', { key: one.key, ...(x ? { note: x } : {}) }))) : null}
            ${item(t.btnDoOwnWs, () => done(() => c.act('do_it', { keys, target: 'workspace', ...(x ? { note: x } : {}) })), { off: needsWords && !x })}`,
      mode === 'do' || mode === 'note' || mode === 'restart' ? html`<details class="panel-model">
          <summary class="muted small">${modelWord(s, t)}</summary>
          <${LaunchPick} s=${s} c=${c} items=${[{ key: one.key, title: one.title }]} />
        </details>` : null) : starts.length ? group(t.grp.start, html`${item(t.startManyGo(starts.length), () => done(go), { token: 'info' })}
        ${item(t.action.advise, () => done(() => c.act('advise', { keys: starts.map(r => r.key), ...(x ? { note: x } : {}) })))}
        ${item(t.btnEachOwnWs, () => done(() => c.act('do_it', { keys: starts.map(r => r.key), target: 'workspace', ...(x ? { note: x } : {}) })))}`,
      html`<details class="panel-model">
          <summary class="muted small">${modelWord(s, t)}</summary>
          <${LaunchPick} s=${s} c=${c} items=${starts.map(r => ({ key: r.key, title: r.title }))} />
        </details>`) : null}
    ${one ? group(t.grp.ask, html`${one.bucket === 'waiting' ? item(t.action.follow_up, () => done(() => c.ask('follow_up', { key: one.key }))) : null}
      ${item(t.askChat, () => done(() => c.ask('row', { key: one.key })))}`) : null}`
  const settlePart = () => html`${group(t.grp.close, html`${item(t.settleDone, () => settle('done'), { token: 'success', ref: first })}
      ${item(t.settleNot, discard, { token: 'on-surface-muted' })}
      ${streams ? html`<span class="settle-hint muted small">${t.streamHint}</span>` : null}
      ${rows.some(r => r.task && r.tab?.live) ? html`<span class="settle-hint muted small">${t.taskDoneLiveTab}</span>` : null}`)}
    ${group(t.grp.later, html`${item(t.laterTomorrow, () => later(r => c.laterDays(r, 1, x)))}
      ${item(t.laterMonday, () => later(r => c.laterMonday(r, x)))}
      ${item(t.laterWeek, () => later(r => c.laterDays(r, 7, x)))}
      ${item(t.settleRuns, () => done(() => c.askRunsOn(rows, x)))}
      ${one && one.task && one.bucket === 'waiting' && !one.inbox_id
        ? item(t.settleAgain, () => done(() => c.act('task_running', { slug: one.task }))) : null}
      ${one && one.inbox_id && one.runs ? item(t.settleReopen, () => done(() => c.act('inbox_reopen', { id: one.inbox_id }))) : null}
      <span class="field-row panel-day">
        <input class="input input-date mono" type="text" inputmode="numeric" aria-label=${t.dateLabel} placeholder=${t.datePlaceholder}
          value=${day} aria-invalid=${dayErr ? 'true' : undefined} onInput=${e => { setDay(e.currentTarget.value); setDayErr('') }}
          onKeyDown=${e => { if (e.key === 'Enter') untilDay() }} />
        <${Btn} size="xs" variant="ghost" disabled=${!day.trim()} onClick=${untilDay}>${t.btnUntilDay}<//>
      </span>
      ${dayErr ? html`<span class="field-err small" role="alert">${dayErr}</span>` : null}`)}
    ${group(t.grp.keep, html`${item(t.btnSaveNote, () => done(() => rows.forEach(r => c.act('note', { key: r.key, text: x }))), { off: !x })}
      ${one?.inbox_id ? item(t.settleToTask, () => done(() => c.act('to_task', { key: one.key }))) : null}`)}
    ${rows.some(r => !r.task && !r.inbox_id) ? html`<span class="settle-hint muted small">${t.settleHint}</span>` : null}`
  const still = html`<span class="fixed-origin" ref=${origin} aria-hidden="true"></span>`
  if (asking) {
    return html`${still}<span class="settle-menu row-panel" role="menu" ref=${me} style=${style}>
      <span class="settle-hint small">${t.streamEndAsk}</span>
      ${item(t.streamEndYes, () => settle(asking), { token: asking === 'done' ? 'success' : 'on-surface-muted', ref: first })}
      ${item(t.streamEndNo, () => setAsking(null))}
    </span>`
  }
  return html`${still}<span class="settle-menu row-panel" role="menu" ref=${me} style=${style}>
    ${rows.length > 1 ? html`<ul class="settle-list">${rows.map(r => html`<li key=${r.key}>${r.title}</li>`)}</ul>` : null}
    <label class="start-note">
      <span class="label-caps">${part === 'start' ? t.panelTextStart : t.panelTextSettle}</span>
      <textarea rows="2" ref=${field} value=${text} placeholder=${part !== 'start' ? t.panelSettleHint : needsWords ? t.startNeedsHint : t.panelStartHint}
        onInput=${e => setText(e.currentTarget.value)}
        onKeyDown=${e => { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter' && part === 'start' && canGo) { e.preventDefault(); done(go) } }}></textarea>
    </label>
    ${part === 'start' ? startPart() : settlePart()}
  </span>`
}

/** The model a start here takes, folded to one line: "Model: Auto · Effort: Auto"; a click unfolds the picker */
function modelWord(s, t) {
  const w = t.launch
  const choice = launchChoice(s.launch, s.ui)
  return `${w.label}: ${w.model[choice.model] ?? choice.model} · ${w.effortLabel}: ${w.effort[choice.effort] ?? choice.effort}`
}

/** The start door of the panel: the row's one start button, its word by the row (startMode), and the ▾ beside it.
 *  Waiting and yours-alone rows open the panel at the sentence, since an agent there needs to be told what to do */
export function StartMenu({ row, s, c, size = 'xs' }) {
  const t = T()
  const mode = startMode(row)
  const [open, setOpen] = useState(false)
  const box = usePopover(open, setOpen)
  const busy = !!s.ui.busy[row.key]
  // a click opens the panel, so a sentence can go with every start; only To tab acts at once, it starts nothing
  const word = mode === 'restart' ? t.action.restart : mode === 'approved' ? t.action.approved : t.action.do
  return html`<span class="settle start" ref=${box}>
    ${mode === 'tab' ? html`<span class="btn-split"><${Btn} size=${size} variant="primary" busy=${busy}
        onClick=${() => (canTab(s, 'focus') ? c.act('tab_jump', { tab_ref: row.tab.ref }) : c.openTabView(row.tab.ref))}>${t.action.to_tab}<//>
      <${Btn} size=${size} variant="primary" pressed=${open} label=${t.startMore} onClick=${() => setOpen(!open)}>▾<//></span>`
      : mode === 'approved' ? html`<${Btn} size=${size} variant="ghost" busy=${busy} pressed=${open} onClick=${() => setOpen(!open)}>${word} ▾<//>`
      : mode === 'restart' ? html`<${Btn} size=${size} variant="primary" busy=${busy} pressed=${open} onClick=${() => setOpen(!open)}>${word} ▾<//>`
      : html`<${Btn} size=${size} variant="primary" busy=${busy} pressed=${open} title=${mode === 'note' ? t.startNeedsHint : undefined}
          onClick=${() => setOpen(!open)}>${t.action.do} ▾<//>`}
    ${open ? html`<${RowPanel} rows=${[row]} s=${s} c=${c} part="start" close=${() => setOpen(false)} anchor=${box} />` : null}
  </span>`
}

/** The start door on a selection: "Let AI do it (n) ▾" opens the same panel at the sentence, for every picked
 *  row an agent can start on */
export function StartMany({ rows, s, c, size = 'xs' }) {
  const t = T()
  const [open, setOpen] = useState(false)
  const box = usePopover(open, setOpen)
  const ok = rows.filter(r => r && (r.inbox_id || r.task) && ['do', 'note', 'restart'].includes(startMode(r)))
  if (!ok.length) return null
  const busy = !!s.ui.busy[ok.map(r => r.key).join(',')] || ok.some(r => s.ui.busy[r.key])
  return html`<span class="settle start" ref=${box}>
    <${Btn} size=${size} variant="primary" busy=${busy} pressed=${open} onClick=${() => setOpen(!open)}>${t.startMany(ok.length)} ▾<//>
    ${open ? html`<${RowPanel} rows=${ok} s=${s} c=${c} part="start" close=${() => setOpen(false)} anchor=${box} />` : null}
  </span>`
}

/** The close door of the panel: "Close ▾" on one row, "Close n ▾" on a selection, with done or discard, not now
 *  and a note. `seed` fills the sentence (the check hands its reason for a close) */
export function SettleMenu({ rows, s, c, size = 'xs', seed }) {
  const t = T()
  const [open, setOpen] = useState(false)
  const box = usePopover(open, setOpen)
  const ok = rows.filter(r => (r.settle ?? []).length)
  if (!ok.length) return null
  const busy = !!s.ui.busy[ok.map(r => r.key).join(',')] || ok.some(r => s.ui.busy[r.key])
  const word = ok.length > 1 ? t.settleMany(ok.length) : t.settle
  return html`<span class="settle" ref=${box}>
    <${Btn} size=${size} variant="ghost" busy=${busy} pressed=${open} onClick=${() => setOpen(!open)} label=${word}>${word} ▾<//>
    ${open ? html`<${RowPanel} rows=${ok} s=${s} c=${c} part="settle" close=${() => setOpen(false)} anchor=${box} seed=${seed} />` : null}
  </span>`
}

/** The buttons of a row, one order on every view: start, close, pin. `tab` is an agent tab a view found for the
 *  row's task in the tab list, when the row itself names none */
export function RowBar({ row, s, c, pin = true, size = 'xs', tab = null }) {
  const r = tab && !row.tab ? { ...row, tab: { ref: tab.ref, state: tab.state, live: tab.live ?? tab.state !== 'shell' } } : row
  return html`<${StartMenu} row=${r} s=${s} c=${c} size=${size} /><${SettleMenu} rows=${[r]} s=${s} c=${c} size=${size} />${pin
    ? html`<${PinStar} rowKey=${r.key} s=${s} c=${c} />` : null}`
}

/** The buttons of a page row that is no inbox item or task but a person can hand on: the same bar as a work row.
 *  The server files it to the inbox first and starts on that */
export function PageItemActions({ it, s, c, after }) {
  if (!pageItemActs(it)) return null
  const row = actionRow(it, new Map())
  // `after` runs once a step went through (the detail drawer closes with it)
  const cc = after ? { ...c, act: async (verb, args) => { const r = await c.act(verb, args); if (r?.ok) after(); return r } } : c
  return html`<${RowBar} row=${row} s=${s} c=${cc} pin=${false} />`
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
    <span class="row-num mono"><span class="sr-only">${t.numberLabel(n)}</span><span aria-hidden="true">${n}</span></span>
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
    <span class="row-acts"><${RowBar} row=${row} s=${s} c=${c} /></span>
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
    ${!rows.length ? (section.total === 0 ? html`<${Empty}>${t.empty}<//>` : null)
      // the board section is mostly issues: by repo, so one board's items stand together
      : section.id === 'track' && repoGroups(rows).length > 1
        ? repoGroups(rows).map(g => html`<div class="row-group" key=${g.repo ?? '-'}>
            <h3 class="row-group-head">${g.repo ?? t.otherSources} <span class="sec-count mono">${g.rows.length}</span></h3>
            <ol class="rows">${g.rows.map(r => html`<${RowItem} key=${r.key} row=${r} s=${s} c=${c} />`)}</ol></div>`)
        : html`<ol class="rows">${rows.map(r => html`<${RowItem} key=${r.key} row=${r} s=${s} c=${c} />`)}</ol>`}
  </section>`
}

function TabMini({ tab, s, c }) {
  const t = T()
  const busy = !!s.ui.busy[tab.ref]
  const age = duration(s.now - (tab.since_ms || s.now))
  return html`<li class="tabmini">
    <span class="tabmini-main">
      <${StateLine} token=${stateToken(tabStateKey(tab))} strong=${tab.state === 'needs-you'} word=${t.state[tabStateKey(tab)] ?? tab.state} />
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
  // the picks the page shows (under a filter the model holds only those): the count and the acts agree
  const byKey = indexRows(s.model)
  const rows = s.ui.picked.map(k => byKey.get(k)).filter(Boolean)
  const n = rows.length
  if (!n) return null
  return html`<div class="selbar" role="region" aria-label=${t.picked(n)}>
    <strong>${t.picked(n)}</strong>
    <span class="selbar-acts">
      <${StartMany} rows=${rows} s=${s} c=${c} />
      <${SettleMenu} rows=${rows} s=${s} c=${c} />
      <${Btn} size="xs" variant="ghost" onClick=${c.clearPicks}>${t.btnClear}<//>
    </span>
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
  const keys = useRoving()
  if (views.length < 2) return null
  const view = workViewNow(s)
  return html`<div class="fbar-chips work-switch" role="radiogroup" aria-label=${t.workOrder.viewLabel}
    ref=${keys.ref} onKeyDown=${keys.onKeyDown}>
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
    const warnings = pageWarnings(s, t).filter(w => w.kind !== 'driver')   // not a reason to hold back the day
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
