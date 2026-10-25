// SPDX-License-Identifier: MIT
// The cockpit, overlays: drawers, dialogs, toasts, the boot and auth panels.
// The rules every component keeps stand at the head of components.js.

import { html, useEffect, useRef, useState } from '../vendor/htm-preact-3.1.1.module.js'
import {
  DAY, attentionTabs, clockTime, detailNeedsLoad, formatDay, isoDate, nextFocusIndex, nextMonday, noteToken, short,
  toneToken, actionRow, serious, detailText, linkParts, probeText, newestFirst, upcomingEvents, muteScope, rowActionKey, hintsFor, nextInQueue, itemRow,
  workKindOf, noteGo,
} from '../logic.js'
import { T, language } from '../text.js'
import { TriageGist } from '../triage.js'
import { INBOX_FACTS_SKIP, ItemCard, TASK_FACTS_SKIP, cardOf, describeKey, describeOf } from './card.js'
import { KindTag, OriginTag, PageItemActions, RowBar } from './day.js'
import { DetailFailed, Lines, NextUp, Segmented } from './detail.js'
import { AsOf, RelayBadge } from './header.js'
import { ReturnPanel, goTo } from './home.js'
import {
  AGENTS_PAGE, CHAT_PAGE, CHECK_PAGE, JEV_PAGE, SESSIONS_PAGE, START_PAGE, WORKERS_PAGE, briefingTitle, onPageOf,
} from './nav.js'
import { MeterBar, RowSteps, StatusMenu } from './pages.js'
import { GH_REF, GitHubDetail } from './github.js'
import { CalendarFacts } from './dates.js'
import { Btn, Dot, Empty, Icon, Spinner, StateLine, useRoving } from './parts.js'
import { TaskSessions } from './sessions.js'
import { TabsColumn } from './tabs.js'

// ---------------------------------------------------------------- overlays

export function Toasts({ s, c }) {
  const t = T()
  const more = s.toastsMore ?? 0
  return html`<div class="toasts" role="status" aria-live="polite" aria-atomic="false">
    ${s.toasts.map(x => {
      const go = noteGo(x.go)
      return html`<div class="toast" key=${x.id}
        onMouseEnter=${() => c.pauseToast(x.id, 'hover')} onMouseLeave=${() => c.resumeToast(x.id, 'hover')}
        onfocusin=${() => c.pauseToast(x.id, 'focus')} onfocusout=${() => c.resumeToast(x.id, 'focus')}>
      <${Dot} token=${noteToken(x.tone)} />
      ${go ? html`<button type="button" class="toast-text toast-go" title=${t.noteGo}
          onClick=${e => { c.dismissToast(x.id); goTo(s, c, go, e.currentTarget) }}>
          <span>${x.text}</span><${Icon} name="chevronRight" size=${14} /></button>`
        : html`<span class="toast-text">${x.text}</span>`}
      ${x.action === 'undo' && x.undo?.length ? html`<${Btn} size="xs" variant="primary"
          onClick=${() => { c.dismissToast(x.id); x.undo.forEach(u => c.undo(u.undo)) }}>${t.undoToast}<//>` : null}
      ${x.action === 'copy' && x.copy ? html`<${Btn} size="xs" variant="primary" onClick=${() => c.copy(x.copy)}>${t.copyCommand}<//>` : null}
      <span class="mono muted small">${x.at}</span>
      <button type="button" class="icon-btn" aria-label=${t.close} onClick=${() => c.dismissToast(x.id)}><${Icon} name="close" size=${14} /></button>
    </div>`
    })}
    ${more > 0 && s.toasts.length ? html`<button type="button" class="toast toast-more" onClick=${() => c.openNotes()}>${t.toastsMore(more)}</button>` : null}
  </div>`
}

const FOCUSABLE = 'button:not([disabled]), [href], input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'

/**
 * An aria-modal dialog keeps the focus: it moves in on open, Tab and Shift+Tab cycle inside it,
 * and on close it goes back to the element that opened the dialog.
 */
export function useFocusOnOpen(open) {
  const ref = useRef(null)
  useEffect(() => {
    const root = ref.current
    if (!open || !root) return undefined
    const opener = document.activeElement
    const target = root.querySelector('[data-autofocus]') ?? root.querySelector(FOCUSABLE)
    target?.focus()
    const onTab = e => {
      if (e.key !== 'Tab') return
      const items = [...root.querySelectorAll(FOCUSABLE)].filter(el => el.getClientRects().length > 0)
      e.preventDefault()
      const next = nextFocusIndex(items.length, items.indexOf(document.activeElement), e.shiftKey)
      if (next >= 0) items[next].focus()
    }
    document.addEventListener('keydown', onTab, true)
    return () => {
      document.removeEventListener('keydown', onTab, true)
      if (opener && opener !== document.body && document.contains(opener)) opener.focus?.()
    }
  }, [open])
  return ref
}

/** A drawer at the side; `clear` leaves the page behind it unshaded, for a drawer whose changes show there */
export function Drawer({ title, onClose, children, side = 'right', id, cls = '', clear = false }) {
  const t = T()
  const ref = useFocusOnOpen(true)
  return html`<div class=${`overlay${clear ? ' is-clear' : ''}`} onClick=${e => { if (e.target === e.currentTarget) onClose() }}>
    <aside class=${`drawer drawer-${side} ${cls}`} role="dialog" aria-modal="true" aria-labelledby=${`${id}-title`} ref=${ref}>
      <header class="drawer-head">
        <h2 class="sec-title" id=${`${id}-title`}>${title}</h2>
        <${Btn} variant="ghost" size="xs" icon="close" label=${t.close} onClick=${onClose} />
      </header>
      <div class="drawer-body">${children}</div>
    </aside>
  </div>`
}

/** A click on a page row opens its drawer, unless it landed on one of the row's own controls or ended
 *  a text selection */
export function rowClickOpens(e) {
  if (e.defaultPrevented || !e.target?.closest) return false
  if (e.target.closest('button, a, input, select, textarea, summary, label, [role=menu], [role=menuitem]')) return false
  return !String(window.getSelection?.() ?? '')
}

/** A text with its http(s) URLs as links that open in a new tab */
function Linked({ text }) {
  return linkParts(text).map((p, i) => p.href
    ? html`<a key=${i} href=${p.href} target="_blank" rel="noopener noreferrer">${p.text}</a>` : p.text)
}

/** One detail (inbox item or task) for the drawer: read once, again after an action touched it or a
 *  newer collect run came in; never on a timer */
function useItemDetail(kind, id, s, c) {
  const d = s.details[kind][id]
  const ver = s.model?.collected_ms ?? 0
  useEffect(() => { if (id && detailNeedsLoad(d, ver)) (kind === 'inbox' ? c.loadInbox : c.loadTask)(id) }, [kind, id, ver, d?.stale])
  return d
}

function DetailState({ d, onRetry }) {
  const t = T()
  if (!d || (d.status === 'loading' && !d.data)) return html`<p class="muted"><${Spinner} /> ${t.item.loading}</p>`
  if (d.status === 'error') return html`<${DetailFailed} d=${d} onRetry=${onRetry} />`
  return null
}

function Fact({ label, children }) {
  return html`<div class="meta-item"><dt>${label}</dt><dd>${children}</dd></div>`
}

function stamp(value) {
  return String(value ?? '').replace('T', ' ').slice(0, 16)
}

/** The task or stream an inbox item belongs to, in three lines, and the way into it; its kind tag and the
 *  button say which of the two it is, never "task" on a stream */
function ItemTaskCard({ slug, s, c, onOpen }) {
  const t = T()
  const d = useItemDetail('task', slug, s, c)
  const f = d?.data?.front ?? {}
  const kindRow = { key: `task:${slug}`, task: slug, work_kind: d?.data?.work_kind ?? null }
  const wk = workKindOf(kindRow, s) ?? 'task'
  return html`<div class="idrawer-task">
    <div class="idrawer-task-head"><${KindTag} row=${kindRow} s=${s} /><code class="muted">${slug}</code>
      ${f.status ? html`<span class="chip">${t.taskState[f.status] ?? f.status}</span>` : null}</div>
    ${d?.data ? html`${f.headline ? html`<p class="idrawer-task-title">${f.headline}</p>` : null}
      ${f.next ? html`<p class="small"><span class="line-kind">${t.lineKind.next}</span>${f.next}</p>` : null}
      ${f.blocked_by ? html`<p class="small"><span class="line-kind">${t.lineKind.blocked}</span>${f.blocked_by}</p>` : null}`
      : html`<${DetailState} d=${d} onRetry=${() => c.loadTask(slug)} />`}
    <${Btn} size="xs" variant="secondary" onClick=${onOpen}>${t.item.openKind[wk] ?? t.item.openKind.task}<//>
  </div>`
}

function InboxBody({ id, cur, s, c }) {
  const t = T()
  const d = useItemDetail('inbox', id, s, c)
  const where = { page: cur.page, section: cur.section }
  if (!d?.data) return html`<${DetailState} d=${d} onRetry=${() => c.loadInbox(id)} />`
  const it = d.data.item ?? {}
  const events = newestFirst(d.data.events)
  const closes = probeText(it.closes_when, t)
  return html`
    ${it.detail ? html`<section class="idrawer-sec"><h3 class="label-caps">${t.item.detail}</h3>
      <p class="pre idrawer-text"><${Linked} text=${it.detail} /></p>
      ${it.detail_truncated ? html`<p class="muted small">${t.truncated}</p>` : null}</section>` : null}
    <section class="idrawer-sec"><h3 class="label-caps">${t.item.facts}</h3>
      <dl class="meta idrawer-facts">
        ${it.created ? html`<${Fact} label=${t.item.created}>${stamp(it.created)}<//>` : null}
        ${it.from ? html`<${Fact} label=${t.item.from}><${OriginTag} origin=${d.data.origin ?? null} /> <span class="meta-from-raw">${it.from}</span><//>` : null}
        ${it.kind ? html`<${Fact} label=${t.item.kind}>${t.item.kindName[it.kind] ?? it.kind}<//>` : null}
        ${it.state ? html`<${Fact} label=${t.item.state}>${t.item.stateName[it.state] ?? it.state}<//>` : null}
        ${it.urgency ? html`<${Fact} label=${t.item.urgency}>${t.urgency[it.urgency] ?? it.urgency}<//>` : null}
        ${it.gate ? html`<${Fact} label=${t.item.gate}>${t.gate[it.gate] ?? it.gate}<//>` : null}
        ${it.due ? html`<${Fact} label=${t.item.due}>${stamp(it.due)}<//>` : null}
        <${Fact} label=${t.item.closer}>${it.closer ? (t.item.closerKind[it.closer] ?? it.closer) : closes ? t.item.closerKind.probe : t.item.none}<//>
      </dl>
      <div class="runs idrawer-closes"><span class="label-caps">${t.item.closesWhen}</span>
        <span class=${closes ? '' : 'muted'}>${closes ?? t.item.noProbe}</span></div>
      ${it.action_display ? html`<div class="runs"><span class="label-caps">${t.item.runs}</span><code class="runs-cmd">${it.action_display}</code></div>` : null}
      <p class="muted small idrawer-ids">${it.key ? html`<span>${t.item.key}: <code>${it.key}</code></span>` : null}
        <span>${t.item.id}: <code>${id}</code></span></p>
    </section>
    ${it.task ? html`<section class="idrawer-sec"><${ItemTaskCard} slug=${it.task} s=${s} c=${c}
      onOpen=${() => c.openItem(`task:${it.task}`, { task: it.task, title: it.task }, where, cur)} /></section>` : null}
    <section class="idrawer-sec"><h3 class="label-caps">${t.item.events}</h3>
      ${events.length ? html`<ol class="event-list">${events.map((e, i) => html`<li key=${i}>
        <span class="mono muted">${stamp(e.at)}</span><span class="chip">${t.item.verb[e.verb] ?? e.verb}</span>
        ${e.by ? html`<span class="muted">${e.by}</span>` : null}${e.until ? html`<span>${t.hiddenUntil(e.until)}</span>` : null}
        ${e.note ? html`<span class="idrawer-note"><${Linked} text=${e.note} /></span>` : null}</li>`)}</ol>`
        : html`<p class="muted small">${t.item.noEvents}</p>`}
    </section>`
}

/** STATUS.md in its sections: those that start within the first 4000 characters open, the rest folded */
function TaskBody({ slug, cur, s, c, carded = false }) {
  const t = T()
  const d = useItemDetail('task', slug, s, c)
  const where = { page: cur.page, section: cur.section }
  if (!d?.data) return html`<${DetailState} d=${d} onRetry=${() => c.loadTask(slug)} />`
  const f = d.data.front ?? {}
  const facts = ['status', 'priority', 'type', 'created', 'last_updated', 'blocked_by'].filter(k => f[k])
  let used = 0
  const sections = (d.data.sections ?? []).map(x => { const open = used < 4000; used += x.text.length; return { ...x, open } })
  const related = d.data.inbox ?? []
  return html`
    ${f.next && !carded ? html`<section class="idrawer-sec"><h3 class="label-caps">${t.front.next}</h3><p class="idrawer-next"><${Linked} text=${String(f.next)} /></p></section>` : null}
    <section class="idrawer-sec"><h3 class="label-caps">${t.item.facts}</h3>
      <dl class="meta idrawer-facts">${facts.map(k => html`<${Fact} key=${k} label=${t.front[k]}>
        ${k === 'status' ? (t.taskState[f[k]] ?? f[k]) : String(f[k])}<//>`)}</dl>
      ${f.origin || d.data.origin ? html`<p class="small idrawer-origin"><span class="line-kind">${t.lineKind.origin}</span><${OriginTag} origin=${d.data.origin ?? null} />
        ${f.origin ? html` <${Linked} text=${String(f.origin)} />` : null}</p>` : null}
    </section>
    <section class="idrawer-sec"><h3 class="label-caps">${t.item.related(d.data.work_kind ?? workKindOf({ task: slug }, s))}</h3>
      ${related.length ? html`<ul class="entries">${related.map(r => html`<li key=${r.id} class="entry">
        <button type="button" class="btn-link" onClick=${() => c.openItem(`inbox:${r.id}`, { inbox: r.id, task: slug, title: r.summary }, where, cur)}>
          ${short(r.summary ?? r.id, 90)}</button>
        <span class="entry-tags"><${OriginTag} origin=${r.origin ?? null} /></span>
        <span class="btn-row">${r.urgency ? html`<span class="chip">${t.urgency[r.urgency] ?? r.urgency}</span>` : null}
          ${r.gate ? html`<span class="chip">${t.gate[r.gate] ?? r.gate}</span>` : null}</span></li>`)}</ul>`
        : html`<p class="muted small">${t.item.none}</p>`}
    </section>
    <section class="idrawer-sec task-sections"><h3 class="label-caps">${t.item.status} <code class="muted">${d.data.path}</code></h3>
      ${sections.map((x, i) => html`<details key=${i} open=${x.open}><summary>${x.heading}</summary>
        <p class="pre"><${Linked} text=${x.text} /></p>${x.truncated ? html`<p class="muted">${t.truncated}</p>` : null}</details>`)}
    </section>
    ${(d.data.log ?? []).length ? html`<section class="idrawer-sec"><h3 class="label-caps">${t.taskLog}</h3>
      <ol class="log-rows">${newestFirst(d.data.log).map((l, i) => html`<li key=${i}><span class="mono muted">${l.at}</span><span>${l.text}</span></li>`)}</ol></section>` : null}`
}

/** The drawer of an inbox item or a task on the Inbox and Tasks pages: everything to decide on it at a
 *  glance, with the row's actions. Reading only; the actions are the row's own */
export function ItemDrawer({ s, c, byKey }) {
  const t = T()
  const ref = useFocusOnOpen(true)
  const cur = s.ui.item
  const key = cur.key
  // the next of a list opens in the same drawer: it starts at its top, not where the last one was left
  useEffect(() => { ref.current?.querySelector('.idrawer-body')?.scrollTo?.(0, 0) }, [key])
  const isInbox = key.startsWith('inbox:')
  const id = key.slice(isInbox ? 6 : 5)
  const it = cur.it ?? {}
  const tri = s.triage?.items?.[key] ?? null
  const own = byKey.get(key)
  const data = s.details[isInbox ? 'inbox' : 'task'][id]?.data
  const made = own ? null : actionRow(isInbox ? { inbox: id, title: it.title, task: it.task } : { task: id, title: it.title }, byKey)
  // a row built here knows from the item whether its yes is given already, so its start button says so
  const row = own ?? (made && isInbox && data?.item?.state ? { ...made, inbox_state: data.item.state } : made)
  // one title everywhere: the card's (the row's own, else the detail's), the same in the list and the files view;
  // a task's headline is its summary, never its title
  const card = cardOf(own, data)
  const title = card?.title || (isInbox ? data?.item?.summary : null) || it.title || id
  // what it is and where it comes from: the model's row, else what the item's own detail says (a stream opened
  // only by its key is a stream here too, not "Task")
  const kindRow = { ...(row ?? { key, inbox_id: isInbox ? id : null, task: isInbox ? (data?.item?.task ?? it.task ?? null) : id }),
    ...(row?.work_kind || isInbox ? {} : { work_kind: data?.work_kind ?? it.work_kind ?? null }),
    ...(row?.origin ? {} : { origin: data?.origin ?? it.origin ?? null }) }
  const slug = isInbox ? (data?.item?.task ?? it.task) : id
  // a close from inside the drawer ends the item: the drawer goes with it, or on to the next of its list
  const next = nextInQueue(s.ui.queue, key, e => e.key !== key)
  const cc = { ...c, act: async (verb, args) => {
    const r = await c.act(verb, args)
    if (r?.ok && (verb === 'settle' || verb === 'do_it')) { if (next) c.openNext(next); else c.closeItem() }
    return r
  } }
  const asks = it.ask && cur.page && cur.section && it.index != null
  return html`<div class="overlay" onClick=${e => { if (e.target === e.currentTarget) c.closeItem() }}>
    <aside class="drawer drawer-right idrawer" role="dialog" aria-modal="true" aria-labelledby="idrawer-title" ref=${ref}>
      <header class="idrawer-head">
        <div class="idrawer-head-main">
          <span class="eyebrow idrawer-kinds"><${KindTag} row=${kindRow} s=${s} /><${OriginTag} row=${kindRow} /></span>
          <h2 class="idrawer-title" id="idrawer-title">${title}</h2>
        </div>
        <${Btn} variant="ghost" size="xs" icon="close" label=${t.item.close} onClick=${c.closeItem} />
      </header>
      <div class="btn-row idrawer-actions">
        ${cur.prev ? html`<${Btn} size="xs" variant="ghost" icon="back" onClick=${() => c.openItem(cur.prev.key, cur.prev.it, { page: cur.prev.page, section: cur.prev.section }, cur.prev.prev)}>${t.item.backTo}<//>` : null}
        ${row ? html`<${RowBar} row=${row} s=${s} c=${cc} />` : null}
        ${asks ? html`<${Btn} size="xs" variant="ghost" onClick=${() => c.ask('info', { page: cur.page, section: cur.section, index: it.index })}>${t.btnAsk}<//>` : null}
        ${slug ? html`<${Btn} size="xs" variant="ghost" onClick=${() => c.openInner(`task:${slug}`)}>${t.item.inNet}<//>` : null}
        ${own && !isInbox ? html`<${Btn} size="xs" variant="ghost" onClick=${() => { c.closeItem(); c.peek(key) }}>${t.item.more}<//>` : null}
      </div>
      <div class="idrawer-body">
        <${ItemCard} card=${card} d=${describeOf(s, key, own?.describe, data?.describe)} dkey=${key} s=${s} c=${cc}
          skip=${isInbox ? INBOX_FACTS_SKIP : TASK_FACTS_SKIP} cls="idrawer-sec idrawer-card" />
        <${ReturnPanel} s=${s} c=${c} keys=${[key, slug ? `task:${slug}` : null]} />
        ${slug ? html`<section class="idrawer-sec"><${TaskSessions} row=${{ task: slug, key: `task:${slug}` }} s=${s} c=${c} /></section>` : null}
        ${tri ? html`<section class="idrawer-sec idrawer-tri"><h3 class="label-caps">${t.item.about}</h3>
          <${TriageGist} tri=${tri} keyRow=${row} c=${cc} s=${s} />
          ${tri.reason ? html`<p class="muted small">${tri.reason}</p>` : null}</section>` : null}
        ${isInbox ? html`<${InboxBody} key=${id} id=${id} cur=${cur} s=${s} c=${c} />` : html`<${TaskBody} key=${id} slug=${id} cur=${cur} s=${s} c=${c} carded=${!!card?.next} />`}
      </div>
      <${NextUp} s=${s} c=${c} byKey=${byKey} current=${key} />
    </aside>
  </div>`
}

/** The detail of any page item that is not an inbox item or task: everything the row carries, its link,
 *  its own steps, its account status and "ask". It follows the item as the page holds it now */
export function InfoDrawer({ s, c }) {
  const t = T()
  const ref = useFocusOnOpen(true)
  const { it, page, section } = s.ui.info
  const pg = (s.model?.pages ?? []).find(x => x.id === page)
  const sec = pg?.sections?.find(x => x.id === section)
  const cur = sec?.items?.find(x => x.index === it.index && x.title === it.title) ?? it
  const facts = [[t.infoFacts.when, cur.when], [t.infoFacts.state, cur.state], [t.infoFacts.priority, cur.priority],
    [t.infoFacts.group, cur.group], ...Object.entries(cur.tags ?? {})].filter(([, v]) => v)
  const close = () => c.closeInfo()
  // a row that names a running Claude session (the LLM page lists them by name) reaches its cmux tab
  const sess = (s.sessions?.sessions ?? []).find(x => x.tab && (x.name === cur.title || x.tab.name === cur.title))
  // a row named like a machine the workers run on (the Maschinen tiles) leads to its workers
  const onHost = (s.workers?.data?.runs ?? []).filter(r => !r.retired && r.host === cur.title)
  const onHostBad = onHost.filter(r => (r.findings ?? []).some(serious)).length
  // an opened event lists the ones after it too, each a click into its own detail
  const dated = sec?.kind === 'calendar'
  // a GitHub row opens its issue or pull request: what it says, who is on it, its steps as buttons
  const ghRef = sec?.kind === 'tracker' && GH_REF.test(cur.row_id ?? '') ? cur.row_id : null
  const others = dated
    ? upcomingEvents(s.model, s.now || Date.now()).filter(e => !(e.it.at === cur.at && e.it.title === cur.title)).slice(0, 15)
    : []
  return html`<div class="overlay" onClick=${e => { if (e.target === e.currentTarget) close() }}>
    <aside class="drawer drawer-right idrawer" role="dialog" aria-modal="true" aria-labelledby="info-title" ref=${ref}>
      <header class="idrawer-head">
        <div class="idrawer-head-main">
          <span class="eyebrow">${[pg?.title, sec?.title].filter(Boolean).join(' · ')}</span>
          <span class="idrawer-kinds"><${KindTag} row=${itemRow(cur)} s=${s} /><${OriginTag} row=${itemRow(cur)} /></span>
          <h2 class="idrawer-title" id="info-title">${cur.tone ? html`<${StateLine} token=${toneToken(cur.tone)} strong=${cur.tone === 'bad'} word=${cur.title} />` : cur.title}</h2>
        </div>
        <${Btn} variant="ghost" size="xs" icon="close" label=${t.item.close} onClick=${close} />
      </header>
      <div class="btn-row idrawer-actions">
        ${cur.link?.kind === 'web' ? html`<a class="btn btn-secondary btn-xs" href=${cur.link.href} target="_blank" rel="noopener noreferrer">
          <${Icon} name="external" size=${14} /><span class="btn-label">${dated ? t.joinMeeting : t.openLink}</span></a>` : null}
        ${cur.link?.kind === 'file' ? html`<${Btn} size="xs" variant="ghost" icon="copy" title=${cur.link.path} onClick=${() => c.copy(cur.link.path)}>${t.copyPath}<//>` : null}
        ${sess ? html`<${Btn} size="xs" variant="primary" busy=${!!s.ui.busy[sess.tab.ref]} onClick=${() => c.act('tab_jump', { tab_ref: sess.tab.ref })}>${t.btnToTab}<//>
          <${Btn} size="xs" variant="secondary" onClick=${() => { close(); c.openTabView(sess.tab.ref) }}>${t.infoViewTab}<//>` : null}
        ${cur.task ? html`<${Btn} size="xs" variant="secondary" onClick=${() => c.openItem(`task:${cur.task}`, cur, { page, section })}>${t.infoOpenTask}<//>` : null}
        ${onHost.length ? html`<${Btn} size="xs" variant="secondary" onClick=${() => { close(); c.openWorkers({ host: cur.title }) }}>${t.workersOpen}<//>` : null}
        ${cur.actions?.length && cur.row_id ? (dated || ghRef
          // an event's or a GitHub row's steps start an agent tab and change nothing, so each is a button of its own
          ? cur.actions.map(a => html`<${Btn} key=${a.id} size="xs" variant="primary" busy=${!!s.ui.busy[rowActionKey({ page, section, index: cur.index })]}
              onClick=${() => c.act('row_action', { page, section, index: cur.index, action: a.id })}>${a.label}<//>`)
          : html`<${RowSteps} it=${cur} page=${page} section=${section} s=${s} c=${c} as=${sec?.steps ?? 'menu'} />`) : null}
        ${cur.account?.status ? html`<${StatusMenu} it=${cur} page=${page} section=${section} c=${c} />` : null}
        <${PageItemActions} it=${cur} s=${s} c=${c} after=${close} />
        ${cur.ask ? html`<${Btn} size="xs" variant="ghost" onClick=${() => { close(); c.ask('info', { page, section, index: cur.index }) }}>${t.btnAsk}<//>` : null}
      </div>
      <div class="idrawer-body">
        <${ItemCard} card=${cur.card} d=${describeOf(s, describeKey(cur))} dkey=${describeKey(cur)} s=${s} c=${c}
          skip=${['source', 'summary', 'state']} cls="idrawer-sec idrawer-card" />
        ${ghRef ? html`<${GitHubDetail} gref=${ghRef} c=${c} />` : null}
        ${onHost.length ? html`<section class="idrawer-sec"><${StateLine} token=${onHostBad ? 'warning' : 'success'} word=${t.workersOnHost(onHost.length, onHostBad)} /></section>` : null}
        ${cur.detail && !cur.cal ? html`<section class="idrawer-sec"><p class="info-detail-full"><${Linked} text=${detailText(cur.detail, t)} /></p></section>` : null}
        ${cur.meter ? html`<section class="idrawer-sec"><${MeterBar} meter=${cur.meter} scale=${0} tone=${cur.tone} /></section>` : null}
        ${cur.cal ? html`<${CalendarFacts} it=${cur} />` : null}
        ${facts.length && !cur.cal ? html`<section class="idrawer-sec"><dl class="meta">${facts.map(([k, v]) => html`<${Fact} key=${k} label=${k}>${v}<//>`)}</dl></section>` : null}
        ${(cur.lines ?? []).length && !cur.cal ? html`<section class="idrawer-sec"><${Lines} lines=${cur.lines} /></section>` : null}
        ${others.length ? html`<section class="idrawer-sec"><h3 class="label-caps">${t.infoMoreDates}</h3>
          <ul class="agenda">${others.map(e => html`<li key=${`${e.section}:${e.it.at}:${e.it.title}`}>
            <span class="mono agenda-when">${e.it.when}</span>
            <button type="button" class="btn-link" onClick=${() => c.openInfo(e.it, e.page, e.section)}>${e.it.title}</button>
            ${e.it.detail ? html`<span class="muted small">${detailText(e.it.detail, t)}</span>` : null}</li>`)}</ul></section>` : null}
        ${!ghRef && !cur.cal && !cur.detail && !cur.meter && !facts.length && !(cur.lines ?? []).length ? html`<p class="muted">${t.infoNothingMore}</p>` : null}
      </div>
    </aside>
  </div>`
}

export function TabsDrawer({ s, c, byKey }) {
  const ref = useFocusOnOpen(true)
  return html`<div class="overlay" onClick=${e => { if (e.target === e.currentTarget) c.setDrawer(null) }}>
    <aside class="drawer drawer-right drawer-tabs" role="dialog" aria-modal="true" aria-labelledby="tabs-title" ref=${ref}>
      <${TabsColumn} s=${s} c=${c} byKey=${byKey} inDrawer /></aside></div>`
}

/** The undo buttons of one closed item: a task comes back open, or only as still to be done */
function UndoButtons({ it, c, busy }) {
  const t = T()
  const u = it.undo
  if (!u) return null
  if (u.verb === 'task_reopen') return html`<span class="btn-row">
    <${Btn} size="xs" variant="secondary" busy=${busy} onClick=${() => c.undo(u, 'doing')}>${t.undoReopen}<//>
    <${Btn} size="xs" variant="ghost" busy=${busy} onClick=${() => c.undo(u, 'backlog')}>${t.undoBacklog}<//></span>`
  return html`<span class="btn-row"><${Btn} size="xs" variant="secondary" busy=${busy} onClick=${() => c.undo(u)}>${u.verb === 'unhide' ? t.undoShow : u.verb === 'row_undo' ? t.undoStep : t.undoReopen}<//></span>`
}

/** The word of a history line: a task's line says Stream for a stream (the server keeps work_kind on it; an older
 *  line asks the task list), never Task on a stream */
function histWord(it, s) {
  if (it.kind !== 'task') return it.kind
  const wk = it.work_kind ?? workKindOf({ task: it.ident ?? String(it.key ?? '').replace(/^task:/, '') }, s)
  return /stream/.test(wk ?? '') ? 'stream' : 'task'
}

/** What the dashboard closed, dropped, settled or hid, newest first and by day; each item can be taken back */
export function HistoryDrawer({ s, c }) {
  const t = T()
  const lang = language()
  const entries = s.history ?? []
  const days = []
  for (const e of entries) {
    const day = isoDate(e.at_ms)
    let d = days.find(x => x.day === day)
    if (!d) days.push(d = { day, entries: [] })
    d.entries.push(e)
  }
  const busyOf = u => !!s.ui.busy[u.verb]
  return html`<${Drawer} id="history" title=${t.historyTitle} onClose=${() => c.setDrawer(null)}>
    <p class="muted small">${t.historyIntro}</p>
    ${days.length ? days.map(d => html`<section class="hist-day" key=${d.day}>
      <h3 class="label-caps">${formatDay(d.day, lang)}</h3>
      <ol class="hist">${d.entries.flatMap(e => e.items.map((it, i) => html`<li key=${`${e.id}-${i}`} class=${`hist-item${it.undone_ms ? ' is-undone' : ''}`}>
        <span class="mono muted small">${clockTime(e.at_ms)}</span>
        <div class="hist-main">
          <span class="hist-what"><span class="chip">${t.histKind[histWord(it, s)] ?? it.kind}</span>
            <span class=${`hist-did hist-${it.did?.startsWith('hidden') ? 'hidden' : it.did}`}>${t.histDid(it.did)}</span>
            ${e.backfilled ? html`<span class="muted small">${t.histBackfilled}</span>` : null}</span>
          <span class="hist-title">${it.title}</span>
          ${it.undone_ms ? html`<span class="small"><${StateLine} token="success" word=${t.histUndone(clockTime(it.undone_ms))} /></span>`
            : html`<${UndoButtons} it=${it} c=${c} busy=${it.undo ? busyOf(it.undo) : false} />`}
        </div>
      </li>`))}</ol>
    </section>`) : html`<${Empty}>${t.historyEmpty}<//>`}
  <//>`
}

export function NotesDrawer({ s, c }) {
  const t = T()
  const notes = s.notes.slice().reverse()
  return html`<${Drawer} id="notes" title=${t.notesTitle} onClose=${() => c.setDrawer(null)}>
    ${notes.length ? html`<ol class="notes">${notes.map((n, i) => {
      const go = noteGo(n.go)
      // an entry that names its place leads there; the drawer closes first, so an item drawer can open
      return html`<li key=${i} class="note">
      <span class="mono muted small">${n.at}</span>
      ${go ? html`<button type="button" class="note-go" title=${t.noteGo}
          onClick=${e => { c.setDrawer(null); goTo(s, c, go, e.currentTarget) }}>
          <${StateLine} token=${noteToken(n.tone)} word=${n.text} /><${Icon} name="chevronRight" size=${14} /></button>`
        : html`<${StateLine} token=${noteToken(n.tone)} word=${n.text} />`}
    </li>`
    })}</ol>` : html`<${Empty}>${t.notesEmpty}<//>`}
  <//>`
}

/** Whether the page shows an area now; without a document to ask (a render elsewhere) every one counts */
function onPage(target) {
  if (typeof document === 'undefined' || !document.querySelector) return true
  try {
    // as the overlay counts it: a part in a hidden pane has no size and gets no note, so no line here either
    const r = document.querySelector(target)?.getBoundingClientRect?.()
    return !!r && r.width > 0 && r.height > 0
  } catch { return false }
}

const HELP_TABS = ['page', 'rows', 'act', 'keys', 'trust']

/** Help: one topic at a time, this page first. Its parts are the explain overlay's (logic.js hintsFor) as a
 *  list, so the notes and the help never say two different things */
export function HelpDialog({ s, c }) {
  const t = T()
  const h = t.help
  const ref = useFocusOnOpen(true)
  const [tab, setTab] = useState('page')
  const keys = useRoving()
  const hints = hintsFor(s).filter(x => onPage(x.target))
  const list = items => html`<dl class="help-cards">${items.map(x => html`<div key=${x.id}>
    <dt>${t.hints.items[x.id].title}</dt><dd>${t.hints.items[x.id].body}</dd></div>`)}</dl>`
  const topics = items => html`<dl class="help-text">${items.map(([k, v]) => html`<div key=${k}><dt>${k}</dt><dd>${Array.isArray(v)
    ? html`<ul class="plain help-list">${v.map(x => html`<li key=${x}>${x}</li>`)}</ul>` : v}</dd></div>`)}</dl>`
  const own = hints.filter(x => x.group === 'page')
  const body = tab === 'page' ? html`<p class="muted small">${h.pageLead}</p>
      ${own.length ? list(own) : html`<p class="muted small">${h.pageNone}</p>`}
      <h3 class="label-caps help-sub">${h.headTitle}</h3>
      ${list(hints.filter(x => x.group === 'head'))}`
    : tab === 'keys' ? (s.ui.shortcuts ? html`<dl class="keys">${t.keys.map(([k, v]) => html`<div key=${k}><dt><kbd>${k}</kbd></dt><dd>${v}</dd></div>`)}</dl>
        <p class="muted small">${t.commandHint}</p>
        <p class="muted small">${t.keysOn} <button type="button" class="btn-link" onClick=${() => c.openSettings('look')}>${t.settings.keysTitle}</button></p>`
      : html`<p class="muted small">${t.keysOff} <button type="button" class="btn-link" onClick=${() => c.openSettings('look')}>${t.settings.keysTitle}</button></p>`)
    : topics(t.helpTopics[tab])
  return html`<div class="overlay overlay-center" onClick=${e => { if (e.target === e.currentTarget) c.setDrawer(null) }}>
    <div class="dialog help-dialog" role="dialog" aria-modal="true" aria-labelledby="help-title" ref=${ref}>
      <header class="drawer-head help-head">
        <h2 class="sec-title" id="help-title">${t.helpTitle}</h2>
        <span class="btn-row help-tour">
          <button type="button" class="btn btn-secondary btn-xs" title=${t.tour.helpLine} onClick=${() => c.tourStart()}><span class="btn-label">${t.tour.again}</span></button>
          <button type="button" class="btn btn-ghost btn-xs" onClick=${() => c.setHints(true)}><${Icon} name="bulb" size=${14} /><span class="btn-label">${t.hints.helpButton}</span></button>
        </span>
        <${Btn} variant="ghost" size="xs" icon="close" label=${t.close} onClick=${() => c.setDrawer(null)} />
      </header>
      <div class="seg help-tabs" role="tablist" aria-label=${h.tabsLabel} ref=${keys.ref} onKeyDown=${keys.onKeyDown}>${HELP_TABS.map(id => html`<button type="button" key=${id}
        role="tab" id=${`help-tab-${id}`} aria-selected=${String(tab === id)} aria-controls="help-pane" data-autofocus=${tab === id ? '' : undefined}
        class=${`seg-btn${tab === id ? ' is-on' : ''}`} onClick=${() => setTab(id)}>${h.tabs[id]}</button>`)}</div>
      <div class="help-pane" id="help-pane" role="tabpanel" aria-labelledby=${`help-tab-${tab}`}>${body}</div>
    </div>
  </div>`
}

export function ConfirmDialog({ s, c }) {
  const t = T()
  const conf = s.ui.confirm
  const ref = useFocusOnOpen(!!conf)
  if (!conf) return null
  if (conf.kind === 'runs_on') return html`<${RunsOnDialog} conf=${conf} s=${s} c=${c} dialogRef=${ref} />`
  if (conf.kind === 'drop') return html`<${DropDialog} conf=${conf} c=${c} dialogRef=${ref} />`
  return html`<div class="overlay overlay-center">
    <div class="dialog" role="alertdialog" aria-modal="true" aria-labelledby="confirm-title" ref=${ref}>
      <h2 class="sec-title" id="confirm-title">${t.approveAsk(conf.count)}</h2>
      <div class="btn-row dialog-acts">
        <button type="button" class="btn btn-secondary btn-sm" data-autofocus onClick=${c.cancelConfirm}><span class="btn-label">${t.approveNo}</span></button>
        <button type="button" class="btn btn-primary btn-sm" onClick=${c.confirmYes}><span class="btn-label">${t.approveYes}</span></button>
      </div>
    </div>
  </div>`
}

/** "Runs on": until when it stays quiet and, if it helps, on what it waits; on that day it comes back by itself */
function RunsOnDialog({ conf, s, c, dialogRef }) {
  const t = T()
  const now = s.now || Date.now()
  const presets = [[t.runsTomorrow, isoDate(now + DAY)], [t.runsThreeDays, isoDate(now + 3 * DAY)],
    [t.runsNextWeek, isoDate(nextMonday(now))], [t.runsTwoWeeks, isoDate(now + 14 * DAY)]]
  const n = conf.keys.length
  return html`<div class="overlay overlay-center">
    <div class="dialog" role="dialog" aria-modal="true" aria-labelledby="confirm-title" ref=${dialogRef}>
      <h2 class="sec-title" id="confirm-title">${t.runsAsk(n)}</h2>
      <ul class="close-list">${conf.titles.slice(0, 4).map((title, i) => html`<li key=${i}>${short(title, 90)}</li>`)}
        ${n > 4 ? html`<li class="muted">+${n - 4}</li>` : null}</ul>
      <fieldset class="close-reasons">
        <legend class="label-caps">${t.runsUntil}</legend>
        <div class="chip-row">${presets.map(([label, day]) => html`<button type="button" key=${day}
          class=${`chip${conf.until === day ? ' is-on' : ''}`} onClick=${() => c.setConfirm({ until: day })}>${label}</button>`)}
          <input type="date" class="input input-date" value=${conf.until ?? ''} min=${isoDate(now + DAY)}
            aria-label=${t.runsUntil} onInput=${e => c.setConfirm({ until: e.currentTarget.value || null })} /></div>
      </fieldset>
      <label class="field">
        <span class="label-caps">${t.runsOnLabel}</span>
        <input class="input" maxlength="200" value=${conf.on} placeholder=${t.runsOnPlaceholder} data-autofocus
          onInput=${e => c.setConfirm({ on: e.currentTarget.value })} />
      </label>
      <p class="muted small">${t.runsHint}</p>
      <div class="btn-row dialog-acts">
        <button type="button" class="btn btn-secondary btn-sm" onClick=${c.cancelConfirm}><span class="btn-label">${t.approveNo}</span></button>
        <button type="button" class="btn btn-primary btn-sm" disabled=${!conf.until} onClick=${c.runsOn}><span class="btn-label">${t.runsConfirm}</span></button>
      </div>
    </div>
  </div>`
}

/** Dropping a report asks why: two of the reasons leave a mute rule (inbox.py), and the dialog says what it
 *  covers before anything is written. Enter on the preselected "not worth it" keeps a drop one keystroke away */
function DropDialog({ conf, c, dialogRef }) {
  const t = T()
  const scope = muteScope(conf.item, conf.reason)
  const what = scope?.key_prefix ? t.dropScopeKey(scope.key_prefix) : scope?.kind ? t.dropScopeKind(scope.kind) : ''
  return html`<div class="overlay overlay-center">
    <div class="dialog dialog-wide" role="dialog" aria-modal="true" aria-labelledby="confirm-title" ref=${dialogRef}>
      <h2 class="sec-title" id="confirm-title">${t.dropAsk}</h2>
      <ul class="close-list"><li>${short(conf.title, 90)}</li></ul>
      <fieldset class="close-reasons">
        <legend class="label-caps">${t.dropReasonLabel}</legend>
        ${['once', 'duplicate', 'family', 'source'].map(r => html`<label key=${r} class="radio-line">
          <input type="radio" name="drop-reason" value=${r} checked=${conf.reason === r} data-autofocus=${conf.reason === r ? '' : undefined}
            onChange=${() => c.setConfirm({ reason: r })} />
          <span>${t.dropReason[r]}</span></label>`)}
        ${scope ? html`<p class="small">${scope.days ? t.dropScopeSource(scope.source, scope.days) : t.dropScopeFamily(scope.source, what)}</p>
          <p class="muted small">${t.dropScopeNow}</p>` : null}
      </fieldset>
      <div class="btn-row dialog-acts">
        <button type="button" class="btn btn-secondary btn-sm" onClick=${c.cancelConfirm}><span class="btn-label">${t.approveNo}</span></button>
        <button type="button" class="btn btn-danger btn-sm" disabled=${(conf.reason === 'family' || conf.reason === 'source') && !scope}
          onClick=${c.confirmYes}><span class="btn-label">${t.dropYes}</span></button>
      </div>
    </div>
  </div>`
}

export function AuthPanel() {
  const t = T()
  return html`<main class="center-page">
    <div class="panel panel-pad auth">
      <span class="eyebrow">${t.appName}</span>
      <h1 class="detail-title">${t.authTitle}</h1>
      <p>${t.authText}</p>
      <pre class="code-block"><code>${t.authCommand}</code></pre>
    </div>
  </main>`
}

export function BootPanel({ s, c }) {
  const t = T()
  if (s.boot.status === 'error') {
    return html`<main class="center-page"><div class="panel panel-pad auth" role="alert">
      <span class="eyebrow">${t.appName}</span>
      <h1 class="detail-title">${t.bootFailed}</h1>
      <p><${StateLine} token="danger" word=${s.boot.error ?? t.errors.network} /></p>
      <${Btn} variant="primary" size="sm" icon="reload" onClick=${c.retry}>${t.retry}<//>
    </div></main>`
  }
  return html`<main class="center-page" aria-busy="true"><div class="panel panel-pad auth">
    <span class="eyebrow">${t.appName}</span><p class="muted"><${Spinner} /> ${t.loading}</p></div></main>`
}

export function MobileSwitch({ s, c }) {
  const t = T()
  const onPage = onPageOf(s)
  const page = onPage ? (s.ui.page === START_PAGE ? { title: t.startTab } : s.ui.page === CHECK_PAGE ? { title: t.reviewTab } : s.ui.page === SESSIONS_PAGE ? { title: t.sessionsTab } : s.ui.page === WORKERS_PAGE ? { title: t.workersTab } : s.ui.page === CHAT_PAGE ? { title: t.chatTab } : s.ui.page === AGENTS_PAGE ? { title: t.agentsTab } : s.ui.page === JEV_PAGE ? { title: 'Jev' } : s.ui.page === 'briefing' ? { title: briefingTitle(s) } : (s.model?.pages ?? []).find(p => p.id === s.ui.page)) : null
  const waiting = attentionTabs(s.tabs?.tabs).length
  const peek = onPage && s.ui.pageDetail && !!s.ui.selectedKey
  const items = onPage
    ? [['day', page?.title ?? t.pane.day], ...(peek ? [['detail', t.pane.detail]] : []),
        ['tabs', waiting ? `${t.pane.tabs} (${waiting})` : t.pane.tabs]]
    : [['day', t.pane.day], ['detail', t.pane.detail], ['tabs', waiting ? `${t.pane.tabs} (${waiting})` : t.pane.tabs]]
  const current = onPage && !peek && s.ui.pane === 'detail' ? 'day' : s.ui.pane
  // On a phone the header has no room for them: the relay state and the warnings (lost connection,
  // stale model, failed pass) get their own line here, each a dot plus its written word.
  return html`<div class="mobile-switch">
    <div class="mobile-status"><${RelayBadge} s=${s} /><${AsOf} s=${s} /></div>
    <${Segmented} label=${t.pagesLabel} current=${current} values=${items} onPick=${v => c.setPane(v)} />
  </div>`
}
