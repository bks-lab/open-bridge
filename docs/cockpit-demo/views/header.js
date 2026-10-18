// SPDX-License-Identifier: MIT
// The cockpit, the header and the page bar.
// The rules every component keeps stand at the head of components.js.

import { html, useEffect, useLayoutEffect, useRef, useState } from '../vendor/htm-preact-3.1.1.module.js'
import { agentLoad, aiWaiting, attentionTabs, canTab, etaSeconds, pageWarnings, sessionCounts, short, railShown, workPageOf } from '../logic.js'
import { T } from '../text.js'
import {
  AGENTS_PAGE, CHAT_PAGE, CHECK_PAGE, JEV_PAGE, SESSIONS_PAGE, SETTINGS_PAGE, START_PAGE, WORKERS_PAGE, briefingTitle, morePages,
  pageOrder, reviewHomeOf,
} from './nav.js'
import { usePopover } from './pages.js'
import { Btn, Dot, Spinner, StateLine, useRoving, useTween } from './parts.js'

// ---------------------------------------------------------------- header and page bar

function LoadingIndicator({ s }) {
  const t = T()
  const ld = s.loading ?? {}
  if (ld.pass) {
    const eta = etaSeconds(ld, s.now)
    return html`<span class="hdr-status" role="status">
      <${Spinner} /><span>${t.loadingWhat(t.pass[ld.pass] ?? ld.pass)}${eta ? t.seconds(eta) : ''}</span>
      ${ld.queued ? html`<span class="muted">, ${t.queued(t.pass[ld.queued] ?? ld.queued)}</span>` : null}
    </span>`
  }
  // a failed pass is a warning of AsOf (pageWarnings): it stays visible at every width
  return null
}

/** The warnings a narrow screen must show too (lost connection, stale model, failed pass): dot plus word */
function Warnings({ s }) {
  const t = T()
  return pageWarnings(s, t).map(w => html`<span class="hdr-warn" key=${w.word} title=${w.word}>
    <${StateLine} token=${w.token} strong=${w.token === 'danger'} word=${w.word} /></span>`)
}

export function AsOf({ s }) {
  const t = T()
  const m = s.model
  if (!m) {
    return html`<span class="hdr-asof"><${Warnings} s=${s} />
      <span class="muted asof-text">${s.conn === 'open' ? t.loading : t.connWait}</span></span>`
  }
  return html`<span class="hdr-asof" title=${m.is_full ? '' : t.noTracker}>
    <${Warnings} s=${s} />
    <span class="muted asof-text">${t.sourceAsOf(m.collected_at)}${m.is_full ? '' : ` ${t.noTracker}`}</span>
  </span>`
}

export function RelayBadge({ s, c }) {
  const t = T()
  const r = s.relay ?? {}
  // the relay off there is no control session at all: nothing to report in the header
  if (!r.enabled || r.reason === 'disabled') return null
  let token = 'on-surface-muted'
  let word = t.relay.offline
  let title = r.reason ? t.relayReason[r.reason] : null
  // a control session runs but does not listen: say so, and the click shows it on the sessions page
  const deaf = !r.online && (s.sessions?.sessions ?? []).some(x => x.tab?.is_control && !x.relay)
  if (!r.enabled || r.reason === 'disabled') word = t.relay.disabled
  else if (r.online && r.session?.busy) { token = 'warning'; word = t.relay.busy }
  else if (r.online) { token = 'success'; word = t.relay.online }
  else if (deaf) { token = 'warning'; word = t.relay.deaf; title = t.sessionControlNoRelay }
  return deaf
    ? html`<button type="button" class="hdr-relay btn-link" title=${title} onClick=${() => c.setPage(SESSIONS_PAGE)}><${StateLine} token=${token} word=${word} /></button>`
    : html`<span class="hdr-relay" title=${title ?? word}><${StateLine} token=${token} word=${word} /></span>`
}

/** The relay has nobody to ask: a session can be started in the control workspace with one click, by any
 *  terminal driver that opens a control tab (workplace.py control) */
export function canStartControl(s) {
  const r = s.relay ?? {}
  return !!r.enabled && !r.online && (r.reason === 'no_heartbeat' || r.reason === 'no_control')
    && (canTab(s, 'control') || canTab(s, 'launch'))
}

export function StartControl({ s, c, size = 'xs', short: brief = false }) {
  const t = T()
  if (!canStartControl(s)) return null
  return html`<${Btn} size=${size} variant="primary" busy=${!!s.ui.busy.start_control} title=${t.startControlTitle}
    onClick=${() => c.act('start_control', {})}>${brief ? t.btnStartControlShort : t.btnStartControl}<//>`
}

/** What works in this Bridge's tabs right now: busy sessions, subagents active in the last 2 minutes and
 *  workflows that are not paused (logic.js agentLoad). Sessions elsewhere on this machine only in the
 *  tooltip. A click opens the Sessions page */
export function AgentsChip({ s, c }) {
  const t = T()
  const { total, elsewhere } = agentLoad(s.sessions?.sessions, s.tabs?.tabs)
  if (total.busy + total.subagents + total.workflows <= 0) return null
  return html`<button type="button" class="hdr-agents btn-link small" title=${t.header.workingTitle(total.workflowAgents, elsewhere.busy + elsewhere.subagents)}
    onClick=${() => c.setPage(SESSIONS_PAGE)}>${t.header.working(total.busy, total.subagents, total.workflows)}</button>`
}

function CommandBox({ c }) {
  const t = T()
  const [value, setValue] = useState('')
  const submit = async e => {
    e.preventDefault()
    if (!value.trim()) return
    if (await c.runCommand(value)) setValue('')
  }
  return html`<form class="cmd" onSubmit=${submit} role="search">
    <label class="sr-only" for="command-box">${t.commandLabel}</label>
    <input id="command-box" class="cmd-input mono" type="text" autocomplete="off" spellcheck="false"
      placeholder=${t.commandPlaceholder} value=${value} onInput=${e => setValue(e.currentTarget.value)}
      title=${t.commandHint} aria-describedby="command-hint" />
    <span id="command-hint" class="sr-only">${t.commandHint}</span>
    <kbd class="cmd-kbd" aria-hidden="true">/</kbd>
  </form>`
}

export function Header({ s, c }) {
  const t = T()
  const themeIcon = s.ui.theme === 'dark' ? 'moon' : s.ui.theme === 'light' ? 'sun' : 'auto'
  const waiting = attentionTabs(s.tabs?.tabs).length
  return html`<header class="hdr">
    <div class="hdr-id">
      <span class="eyebrow">${t.appName}</span>
      <div class="hdr-name"><h1 class="hdr-title">${t.cockpit}</h1>
        ${s.mock ? html`<span class="hdr-demo" title=${t.mockNote}><span class="hdr-demo-long">${t.demoBadge}</span><span class="hdr-demo-short">${t.demoBadgeShort}</span></span>` : null}
        ${s.boot?.scratch ? html`<span class="hdr-demo hdr-scratch" role="note"
          title=${s.boot.scratch.kind === 'copy' ? t.scratchCopy(s.boot.scratch.root) : t.scratchState(s.boot.scratch.state_dir)}>
          <span class="hdr-demo-long">${s.boot.scratch.kind === 'copy' ? t.scratchBadge : t.stateBadge}</span>
          <span class="hdr-demo-short">${s.boot.scratch.kind === 'copy' ? t.scratchBadgeShort : t.stateBadgeShort}</span></span>` : null}</div>
    </div>
    <span class="hdr-headline" aria-hidden="true"></span>
    <div class="hdr-right">
      <${LoadingIndicator} s=${s} />
      ${s.layout === 'narrow' ? null : html`<${AsOf} s=${s} />`}
      ${s.layout === 'narrow' ? null : html`<${CommandBox} c=${c} />`}
      ${s.layout === 'medium' || (s.layout === 'wide' && !railShown(s.ui.page, s.rooms?.layout, s.ui.railHidden)) ? html`<${Btn} variant=${waiting ? 'primary' : 'secondary'} size="sm" icon="tabs"
        onClick=${() => c.setDrawer(s.ui.drawer === 'tabs' ? null : 'tabs')} pressed=${s.ui.drawer === 'tabs'}>${t.tabsButton(waiting)}<//>` : null}
      <${Btn} variant="ghost" size="sm" icon="reload" title=${t.reloadTitle} label=${t.reloadTitle}
        busy=${!!s.loading?.pass && s.loading?.fresh} onClick=${c.reload} cls="hdr-reload"><span class="hide-narrow">${t.reload}</span><//>
      <${Btn} variant=${(s.quick?.convs ?? []).some(x => x.running) ? 'primary' : 'secondary'}
        size="sm" icon="send" onClick=${() => c.openAsk()} title=${t.claudeOpenTitle} label=${t.askTitle} cls="hdr-ask">${t.askTitle}<//>
      <${Btn} variant="ghost" size="sm" icon="history" title=${t.historyTitle} label=${t.historyTitle}
        pressed=${s.ui.drawer === 'history'} onClick=${() => s.ui.drawer === 'history' ? c.setDrawer(null) : c.openHistory()}><span class="hide-narrow">${t.historyButton}</span><//>
      ${s.layout === 'narrow' ? null : html`<${AgentsChip} s=${s} c=${c} />`}
      ${s.layout === 'narrow' ? null : html`<${RelayBadge} s=${s} c=${c} />`}
      ${s.layout === 'narrow' ? null : html`<${StartControl} s=${s} c=${c} short />`}
      <${Btn} variant="ghost" size="sm" icon=${themeIcon} label=${`${t.themeLabel}: ${t.theme[s.ui.theme]}`}
        title=${`${t.themeLabel}: ${t.theme[s.ui.theme]}`} onClick=${c.cycleTheme} />
      <${Btn} variant="ghost" size="sm" icon="bell" label=${t.notesTitle} title=${t.notesTitle}
        onClick=${() => c.setDrawer(s.ui.drawer === 'notes' ? null : 'notes')} pressed=${s.ui.drawer === 'notes'} />
      <${Btn} variant="ghost" size="sm" icon="help" label=${t.helpTitle} title=${`${t.helpTitle} (?)`}
        onClick=${() => c.setDrawer('help')} />
    </div>
  </header>`
}

/** What a page's count adds up from: each counting section with its title, for the badge's tooltip */
function badgeTitle(page) {
  const t = T()
  const parts = (page?.sections ?? []).filter(x => x.weight > 0).map(x => t.badgePart(x.weight, x.title))
  return parts.length > 1 ? parts.join(', ') : undefined
}

export function PageBadge({ badge, title }) {
  const t = T()
  if (!badge || badge.kind === 'none') return null
  if (badge.kind === 'bad') return html`<span class="pbadge" title=${t.badgeFindings(badge.n)}><${Dot} token="danger" /><span class="mono">${badge.n}</span></span>`
  // a plain count stays grey: only Today's "waits for you" and a real finding carry colour in the bar
  if (badge.kind === 'count') return html`<span class="pbadge is-quiet" title=${title}><span class="mono">${badge.n}</span></span>`
  return html`<span class="pbadge"><${Dot} token="success" /><span>${t.badgeOk}</span></span>`
}

/** The line under the active page tab; it glides to the next tab and bends when the target changes
 *  in mid move (the film's tab marker, springTo) */
function TabMarker({ box }) {
  const x = useTween(box.x, { w: 14 })
  const w = useTween(box.w, { w: 14 })
  return html`<span class="ptab-marker" aria-hidden="true" style=${{ transform: `translateX(${x.toFixed(1)}px) scaleX(${(w / 100).toFixed(4)})` }}></span>`
}

export function PageBar({ s, c }) {
  const t = T()
  const pages = s.model?.pages ?? []
  const tabsRef = useRef(null)
  const keys = useRoving(tabsRef)
  const [box, setBox] = useState(null)
  useLayoutEffect(() => {
    const el = tabsRef.current?.querySelector('.ptab.is-active')
    if (!el) { if (box) setBox(null); return }
    const next = { x: el.offsetLeft + 12, w: Math.max(0, el.offsetWidth - 24) }
    if (!box || box.x !== next.x || box.w !== next.w) setBox(next)
  })
  const order = pageOrder(s)
  const more = morePages(s)
  const [open, setOpen] = useState(false)
  const moreBox = usePopover(open, setOpen)
  // every tab stands in the bar while the bar is wide enough; only when they overflow do the pages
  // of the `more` group fold behind a "More" menu, from the last one forward and only as many as do not fit.
  // A resize unfolds and measures again
  const navRef = useRef(null)
  const [foldN, setFoldN] = useState(0)
  const foldable = order.filter(id => more.has(id) && id !== s.ui.page)
  const folded = new Set(foldable.slice(Math.max(0, foldable.length - foldN)))
  const fold = folded.size > 0
  useLayoutEffect(() => {
    const nav = navRef.current
    if (nav && foldN < foldable.length && nav.scrollWidth > nav.clientWidth + 1) setFoldN(n => n + 1)
  })
  useEffect(() => {
    const again = () => setFoldN(0)
    window.addEventListener('resize', again)
    return () => window.removeEventListener('resize', again)
  }, [])
  const made = new Map()   // id -> { label, badge, keyHint }, drawn below in tab order
  const tab = (id, label, badge) => {
    const i = order.indexOf(id)
    made.set(id, { label, badge, keyHint: i >= 0 && i < 9 ? `${label} (Alt ${i + 1})` : undefined })
    return null
  }
  const button = id => { const x = made.get(id); return html`<button key=${id} type="button" role="tab" class=${`ptab${s.ui.page === id ? ' is-active' : ''}`}
    aria-selected=${String(s.ui.page === id)} onClick=${() => c.setPage(id)} title=${x.keyHint}>
    <span>${x.label}</span>${x.badge}</button>` }
  const n = s.model?.briefing_badge ?? 0
  const aiLeft = aiWaiting(s.model?.returns, s.tabs?.tabs, s.now || Date.now())   // what the AI left for you (sessions page)
  const toClose = s.model?.review?.last?.to_close ?? 0
  // the Sessions tab shows the number the Sessions station shows, the running agents stand in its tooltip
  const sess = sessionCounts(s.sessions?.sessions)
  return html`<nav class="pagebar" aria-label=${t.pagesLabel} ref=${navRef}>
    <div class="pagebar-tabs" role="tablist" ref=${tabsRef} onKeyDown=${keys.onKeyDown}>
      ${box ? html`<${TabMarker} box=${box} />` : null}
      ${tab(START_PAGE, t.startTab, null)}
      ${tab('briefing', briefingTitle(s), n > 0 ? html`<span class="pbadge" title=${t.badgeWaiting(n, s.model?.counts?.give ?? 0)}><${Dot} token="warning" /><span class="mono">${n}</span></span>` : null)}
      ${tab(SESSIONS_PAGE, t.sessionsTab, aiLeft > 0
        ? html`<span class="pbadge is-quiet" title=${t.aiWaitingTitle(aiLeft)}><span>${t.aiBadge}</span> <span class="mono">${aiLeft}</span></span>`
        : sess.sessions > 0
        ? html`<span class="pbadge is-quiet" title=${sess.agents ? t.home.agentsLine(sess.agents) : undefined}><span class="mono">${sess.sessions}</span></span>` : null)}
      ${s.workers?.status === 'none' ? null : tab(WORKERS_PAGE, t.workersTab, s.workers?.data?.stats?.with_findings
        ? html`<span class="pbadge" title=${t.home.workersFindings(s.workers.data.stats.with_findings)}><${Dot} token="warning" /><span class="mono">${s.workers.data.stats.with_findings}</span></span>` : null)}
      ${tab(CHAT_PAGE, t.chatTab, (s.quick?.convs ?? []).some(x => x.running) ? html`<${Spinner} />` : null)}
      ${(s.agents?.peers ?? []).length ? tab(AGENTS_PAGE, t.agentsTab, (s.agents?.convs ?? []).some(x => x.running) ? html`<${Spinner} />`
        : (s.agents?.convs ?? []).some(x => x.turns?.[x.turns.length - 1]?.waiting) ? html`<${Dot} token="warning" />` : null) : null}
      ${reviewHomeOf(s) ? null : tab(CHECK_PAGE, t.reviewTab, s.model?.review?.running ? html`<${Spinner} />`
        : toClose > 0 ? html`<span class="pbadge"><span class="mono">${toClose}</span></span>` : null)}
      ${s.jev?.enabled && !workPageOf(s.model?.pages)?.jev ? tab(JEV_PAGE, 'Jev', s.jev.ready ? null : html`<${Dot} token="warning" />`) : null}
      ${pages.map(p => tab(p.id, p.title, html`<${PageBadge} badge=${p.badge} title=${badgeTitle(p)} />`))}
      ${tab(SETTINGS_PAGE, t.settings.title, null)}
      ${order.filter(id => made.has(id) && !folded.has(id)).map(button)}
      ${fold ? html`<${MoreTab} items=${order.filter(id => folded.has(id) && made.has(id)).map(id => ({ id, ...made.get(id) }))}
        s=${s} c=${c} open=${open} setOpen=${setOpen} box=${moreBox} />` : null}
    </div>
  </nav>`
}

/** The last tab of the bar: opens the pages that stand behind it. While one of them is open the tab
 *  carries its name; a page behind it with a finding shows a dot */
function MoreTab({ items, s, c, open, setOpen, box }) {
  const t = T()
  const current = items.find(x => x.id === s.ui.page)
  const flagged = items.some(x => x.badge && x.id !== s.ui.page)
  const pick = id => { setOpen(false); c.setPage(id) }
  // the bar scrolls sideways and would clip a menu inside it, so the menu stands fixed under the tab
  const [at, setAt] = useState(null)
  const toggle = e => { const r = e.currentTarget.getBoundingClientRect(); setAt({ top: r.bottom + 4, left: Math.max(8, Math.min(r.left, window.innerWidth - 248)) }); setOpen(!open) }
  return html`<span class="ptab-more" ref=${box}>
    <button type="button" role="tab" class=${`ptab${current ? ' is-active' : ''}`} aria-selected=${String(!!current)}
      aria-haspopup="menu" aria-expanded=${String(open)} onClick=${toggle}>
      <span>${current ? current.label : t.morePages}</span>${current ? current.badge : flagged ? html`<${Dot} token="warning" />` : null}
      <span aria-hidden="true">▾</span></button>
    ${open ? html`<span class="settle-menu more-menu" role="menu" style=${at ? { top: `${at.top}px`, left: `${at.left}px` } : undefined}>
      ${items.map(x => html`<button key=${x.id} type="button" role="menuitem" class=${`settle-item${x.id === s.ui.page ? ' is-on' : ''}`}
        title=${x.keyHint} onClick=${() => pick(x.id)}><span>${x.label}</span>${x.badge}</button>`)}
    </span>` : null}
  </span>`
}

export function AlarmBanner({ s, c }) {
  const t = T()
  const alarms = s.model?.alarms ?? []
  if (!alarms.length) return null
  return html`<div class="alarm" role="alert">
    ${alarms.map(a => html`<div class="alarm-line" key=${`${a.page_id}/${a.section_title}`}>
      <${StateLine} token="danger" strong word=${t.alarmUnder(a.count, `${a.section_title} (${a.page_title})`)} />
      <button type="button" class="btn-link" onClick=${() => c.setPage(a.page_id)}>${t.alarmOpen(a.page_title)}</button>
    </div>`)}
  </div>`
}
