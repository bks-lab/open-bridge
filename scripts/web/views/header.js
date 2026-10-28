// SPDX-License-Identifier: MIT
// The cockpit, the header and the page bar.
// The rules every component keeps stand at the head of components.js.

import { html, useEffect, useLayoutEffect, useRef, useState } from '../vendor/htm-preact-3.1.1.module.js'
import { agentLoad, aiWaiting, attentionTabs, canTab, checkInFlow, tabsButtonCount, etaSeconds, jobCounts, pageWarnings, sessionCounts, sessionsInFlow, short, railOn, railShown, workPageOf } from '../logic.js'
import { T } from '../text.js'
import {
  AGENTS_PAGE, CHAT_PAGE, CHECK_PAGE, FILES_PAGE, JEV_PAGE, SESSIONS_PAGE, SETTINGS_PAGE, START_PAGE, WORKERS_PAGE, briefingTitle, chatAsWorkspaces,
  litTab, morePages, pageOrder, parentOf, reviewHomeOf, tabBadgeOf,
} from './nav.js'
import { AgentMark, agentBadge } from './agents.js'
import { usePopover } from './pages.js'
import { Btn, Dot, Icon, Spinner, StateLine, useRoving, useTween } from './parts.js'

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
  return pageWarnings(s, t).map(w => html`<span class="hdr-warn" key=${w.word} title=${w.title ?? w.word}>
    <${StateLine} token=${w.token} strong=${w.token === 'danger'} word=${w.word} /></span>`)
}

/** When the data was collected, as the button that collects it again (↻ on it; there is no reload button of its
 *  own), the warnings before it. `brief`: the mark alone, for a narrow header whose line below shows the time and
 *  the warnings. While a fresh pass runs it waits, so a second click starts no second pass */
export function AsOf({ s, c, brief = false }) {
  const t = T()
  const m = s.model
  const words = m ? `${t.sourceAsOf(m.collected_at)}${m.is_full ? '' : ` ${t.noTracker}`}` : s.conn === 'open' ? t.loading : t.connWait
  const busy = !!s.loading?.pass && !!s.loading?.fresh
  // the tooltip names the key r only while the shortcuts are on (app.js keydown): off, the key does nothing
  const reload = s.ui?.shortcuts ? `${t.reloadTitle} (r)` : t.reloadTitle
  return html`<span class="hdr-asof">
    ${brief ? null : html`<${Warnings} s=${s} />`}
    <button type="button" class="asof-btn" title=${`${words} · ${reload}`} aria-label=${`${words}, ${t.reloadTitle}`}
      disabled=${busy} aria-busy=${busy ? 'true' : undefined} onClick=${() => c?.reload?.()}>
      ${brief ? null : html`<span class="muted asof-text">${words}</span>`}<${Icon} name="reload" size=${14} /></button>
  </span>`
}

/** A control session runs but does not listen to the relay (it is on, not online): the questions of the page cannot reach it */
export function relayDeaf(s) {
  const r = s.relay ?? {}
  return !!r.enabled && r.reason !== 'disabled' && !r.online && (s.sessions?.sessions ?? []).some(x => x.tab?.is_control && !x.relay)
}

export function RelayBadge({ s, c }) {
  const t = T()
  const r = s.relay ?? {}
  // the relay off there is no control session at all: nothing to report in the header
  if (!r.enabled || r.reason === 'disabled') return null
  let token = 'on-surface-muted'
  let word = t.relay.offline
  let title = r.reason ? t.relayReason[r.reason] : null
  // a control session runs but does not listen: say so, and the click shows it where the control session is told
  // about: the Chat where Running now lists the sessions (round 6: it leaves the control session out), else the
  // Sessions page
  const deaf = relayDeaf(s)
  if (!r.enabled || r.reason === 'disabled') word = t.relay.disabled
  else if (r.online && r.session?.busy) { token = 'warning'; word = t.relay.busy }
  else if (r.online) { token = 'success'; word = t.relay.online }
  else if (deaf) { token = 'warning'; word = t.relay.deaf; title = t.sessionControlNoRelay }
  return deaf
    ? html`<button type="button" class="hdr-relay btn-link" title=${title} onClick=${() => c.setPage(sessionsInFlow(s) ? CHAT_PAGE : SESSIONS_PAGE)}><${StateLine} token=${token} word=${word} /></button>`
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

/** What the head of the Chat says of the control session (round 6, from the Sessions page): why the relay has
 *  nobody to ask, with the button that starts one (canStartControl), and that a control session runs but does not
 *  listen (relayDeaf); nothing while the relay is ready or off */
export function ControlNotice({ s, c }) {
  const t = T()
  const start = canStartControl(s)
  const deaf = relayDeaf(s)
  if (!start && !deaf) return null
  return html`${start ? html`<p class="banner chat-control"><${StateLine} token="warning" word=${t.relayReason[s.relay.reason]} />
      <${StartControl} s=${s} c=${c} size="sm" /></p>` : null}
    ${deaf ? html`<p class="banner chat-control"><${StateLine} token="warning" word=${t.sessionControlNoRelay} /></p>` : null}`
}

/** What works in this Bridge's tabs right now: busy sessions, subagents active in the last 2 minutes and
 *  workflows that are not paused (logic.js agentLoad). Sessions elsewhere on this machine only in the
 *  tooltip. A click opens the Sessions page, which is Running now where Work through lists them (app.js setPage) */
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

/** A quick chat that makes the chat tab spin: a file's suggested next step is not one (its file shows it, no list does) */
export const chatRunning = x => !!x.running && x.place !== 'suggest'

/** What the Chat tab signals: 'quick' while a quick chat answers, else as cmux what the agents signal (the
 *  agents are an area inside the Chat there, agents.js agentBadge); null for nothing. Classic: the Agents tab wears theirs */
export function chatTabSignal(s) {
  if ((s.quick?.convs ?? []).some(chatRunning)) return 'quick'
  return chatAsWorkspaces(s) ? agentBadge(s) : null
}

/** The mark of chatTabSignal on the Chat tab */
export function ChatTabMark({ kind }) {
  return kind === 'quick' ? html`<${Spinner} />` : html`<${AgentMark} kind=${kind} />`
}

// the topics of the look-up card (views/settings.js LookupCard), in its order
const LOOKUP_TOPICS = ['rows', 'act', 'keys', 'trust']

/** Help, "?", the last part of the header (decision 6, menue.md): a menu with Explain first (the notes over the page;
 *  the key ? with the shortcuts on), then the topics of the look-up card under Settings, Appearance (c.openLookup
 *  opens it on that topic), then the tour. A pick closes the menu */
function HelpMenu({ s, c }) {
  const t = T()
  const [open, setOpen] = useState(false)
  const box = usePopover(open, setOpen)
  const pick = fn => () => { setOpen(false); fn() }
  const explain = s.ui.shortcuts ? `${t.hints.buttonTitle} (?)` : t.hints.buttonTitle
  return html`<span class="settle hdr-help" ref=${box}>
    <button type="button" class="btn btn-ghost btn-sm" aria-haspopup="menu" aria-expanded=${String(open)}
      aria-label=${t.helpTitle} title=${t.helpTitle} onClick=${() => setOpen(!open)}><${Icon} name="help" /></button>
    ${open ? html`<span class="settle-menu help-menu" role="menu" aria-label=${t.helpTitle}>
      <button type="button" role="menuitem" class="settle-item" title=${explain} onClick=${pick(() => c.setHints(true))}>
        <${Icon} name="bulb" size=${14} /><span>${t.hints.button}</span></button>
      <span class="settle-hint label-caps muted" role="presentation">${t.settings.lookupTitle}</span>
      ${LOOKUP_TOPICS.map(id => html`<button key=${id} type="button" role="menuitem" class="settle-item"
        onClick=${pick(() => c.openLookup(id))}><span>${t.help.tabs[id]}</span></button>`)}
      <button type="button" role="menuitem" class="settle-item" onClick=${pick(() => c.tourStart())}><span>${t.tour.again}</span></button>
    </span>` : null}
  </span>`
}

/** The header as the menu has it (decision 6, menue.md): the as-of time (the reload button), Tabs, Ask, History,
 *  Notes (the bell, the notes' own list; the history keeps them by day too) beside the state of what runs, and Help
 *  last, with Explain as its first item. The colours and the look-up card stand in Settings, Appearance */
export function Header({ s, c }) {
  const t = T()
  // the Tabs button counts the tabs that want you; a finished (idle) one waits on nobody
  const waiting = tabsButtonCount(s.tabs?.tabs)
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
      <${AsOf} s=${s} c=${c} brief=${s.layout === 'narrow'} />
      ${s.layout === 'narrow' ? null : s.ui.shortcuts ? html`<${CommandBox} c=${c} />` : null}
      ${s.layout === 'medium' || (s.layout === 'wide' && !railOn(s)) ? html`<${Btn} variant=${waiting ? 'primary' : 'secondary'} size="sm" icon="tabs"
        onClick=${() => c.setDrawer(s.ui.drawer === 'tabs' ? null : 'tabs')} pressed=${s.ui.drawer === 'tabs'} cls="hdr-tabs">${t.tabsButton(waiting)}<//>` : null}
      <${Btn} variant=${(s.quick?.convs ?? []).some(chatRunning) ? 'primary' : 'secondary'}
        size="sm" icon="send" onClick=${() => c.openAsk()} title=${t.claudeOpenTitle} label=${t.askTitle} cls="hdr-ask">${t.askTitle}<//>
      <${Btn} variant="ghost" size="sm" icon="history" title=${t.historyTitle} label=${t.historyTitle}
        pressed=${s.ui.drawer === 'history'} onClick=${() => s.ui.drawer === 'history' ? c.setDrawer(null) : c.openHistory()} cls="hdr-history"><span class="hide-narrow">${t.historyButton}</span><//>
      <${Btn} variant="ghost" size="sm" icon="bell" label=${t.notesTitle} title=${t.notesTitle}
        onClick=${() => c.setDrawer(s.ui.drawer === 'notes' ? null : 'notes')} pressed=${s.ui.drawer === 'notes'} cls="hdr-notes" />
      ${s.layout === 'narrow' ? null : html`<${AgentsChip} s=${s} c=${c} />`}
      ${s.layout === 'narrow' ? null : html`<${RelayBadge} s=${s} c=${c} />`}
      ${s.layout === 'narrow' ? null : html`<${StartControl} s=${s} c=${c} short />`}
      <${HelpMenu} s=${s} c=${c} />
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
  // a page chosen from More or by key: its tab scrolls into the bar's view on a narrow screen (review C21)
  useEffect(() => {
    tabsRef.current?.querySelector('.ptab.is-active')?.scrollIntoView?.({ inline: 'nearest', block: 'nearest' })
  }, [s.ui.page])
  useLayoutEffect(() => {
    const el = tabsRef.current?.querySelector('.ptab.is-active')
    if (!el) { if (box) setBox(null); return }
    const next = { x: el.offsetLeft + 12, w: Math.max(0, el.offsetWidth - 24) }
    if (!box || box.x !== next.x || box.w !== next.w) setBox(next)
  })
  const order = pageOrder(s)
  const more = morePages(s)
  // a sub page has no tab: the tab of the page it stands under stays lit while it is open
  const lit = litTab(s)
  const [open, setOpen] = useState(false)
  const moreBox = usePopover(open, setOpen)
  // every tab stands in the bar while the bar is wide enough; only when they overflow do the pages
  // of the `more` group fold behind a "More" menu, from the last one forward and only as many as do not fit.
  // A resize unfolds and measures again
  const navRef = useRef(null)
  const [foldN, setFoldN] = useState(0)
  const foldable = order.filter(id => more.has(id) && id !== lit)
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
  const made = new Map()   // id -> { label, badge, flag, keyHint }, drawn below in tab order
  // the tooltip names the tab's Alt key only while the shortcuts are on (app.js); `flag` is the colour the badge
  // carries for a reason (a finding, a warning), which More wears for the tabs folded behind it
  const tab = (id, label, badge, flag = null) => {
    const i = order.indexOf(id)
    made.set(id, { label, badge, flag, keyHint: s.ui.shortcuts && i >= 0 && i < 9 ? `${label} (Alt ${i + 1})` : undefined })
    return null
  }
  const button = id => { const x = made.get(id); return html`<button key=${id} type="button" role="tab" class=${`ptab${lit === id ? ' is-active' : ''}`}
    aria-selected=${String(lit === id)} onClick=${() => c.setPage(id)} title=${x.keyHint}>
    <span>${x.label}</span>${x.badge}</button>` }
  // what waits for you: Today and Work through carry the same number, no counter of their own
  const n = s.model?.briefing_badge ?? 0
  const aiLeft = aiWaiting(s.model?.returns, s.tabs?.tabs, s.now || Date.now())   // what the AI left for you (sessions page)
  const toClose = s.model?.review?.last?.to_close ?? 0
  // the Sessions tab shows the number the Sessions station shows, the running agents stand in its tooltip. Where
  // Work through lists the live sessions in Running now (round 6) the tab goes, its AI badge with it: what the AI left
  // stands there as points already (a start that asks or finished), Running now counts what runs
  const sess = sessionCounts(s.sessions?.sessions)
  const sessTab = !sessionsInFlow(s)
  const agentsInChat = chatAsWorkspaces(s)
  // the background jobs: an outage is red, upkeep no colour at all
  const jobs = jobCounts(s.workers?.data)
  return html`<nav class="pagebar" aria-label=${t.pagesLabel} ref=${navRef}>
    <div class="pagebar-tabs" role="tablist" ref=${tabsRef} onKeyDown=${keys.onKeyDown}>
      ${box ? html`<${TabMarker} box=${box} />` : null}
      ${tab(START_PAGE, t.startTab, null)}
      ${tab('briefing', briefingTitle(s), n > 0 ? html`<span class="pbadge" title=${t.badgeWaiting(n, s.model?.counts?.give ?? 0)}><${Dot} token="warning" /><span class="mono">${n}</span></span>` : null)}
      ${tab(FILES_PAGE, t.filesTab, null)}
      ${sessTab ? tab(SESSIONS_PAGE, t.sessionsTab, aiLeft > 0
        ? html`<span class="pbadge is-quiet" title=${t.aiWaitingTitle(aiLeft)}><span>${t.aiBadge}</span> <span class="mono">${aiLeft}</span></span>`
        : sess.sessions > 0
        ? html`<span class="pbadge is-quiet" title=${sess.agents ? t.home.agentsLine(sess.agents) : undefined}><span class="mono">${sess.sessions}</span></span>` : null) : null}
      ${s.workers?.status === 'none' ? null : tab(WORKERS_PAGE, t.workersTab, jobs.failing
        ? html`<span class="pbadge" title=${t.overviewWorkers(jobs.ok, jobs.all, jobs.failing, jobs.upkeep)}><${Dot} token="danger" /><span class="mono">${jobs.failing}</span></span>` : null,
        jobs.failing ? 'danger' : null)}
      ${tab(CHAT_PAGE, t.chatTab, html`<${ChatTabMark} kind=${chatTabSignal(s)} />`)}
      ${(s.agents?.peers ?? []).length && !agentsInChat ? tab(AGENTS_PAGE, t.agentsTab, html`<${AgentMark} kind=${agentBadge(s)} />`, agentBadge(s) === 'waiting' ? 'warning' : null) : null}
      ${reviewHomeOf(s) || checkInFlow(s) ? null : tab(CHECK_PAGE, t.reviewTab, s.model?.review?.running ? html`<${Spinner} />`
        : toClose > 0 ? html`<span class="pbadge"><span class="mono">${toClose}</span></span>` : null)}
      ${s.jev?.enabled && !workPageOf(s.model?.pages)?.jev ? tab(JEV_PAGE, 'Jev', s.jev.ready ? null : html`<${Dot} token="warning" />`, s.jev.ready ? null : 'warning') : null}
      ${pages.map(p => { const b = tabBadgeOf(s, p); return tab(p.id, p.title, html`<${PageBadge} badge=${b} title=${badgeTitle(p)} />`, b?.kind === 'bad' ? 'danger' : null) })}
      ${tab(SETTINGS_PAGE, t.settings.title, null)}
      ${order.filter(id => made.has(id) && !folded.has(id)).map(button)}
      ${fold ? html`<${MoreTab} items=${order.filter(id => folded.has(id) && made.has(id)).map(id => ({ id, ...made.get(id) }))}
        s=${s} c=${c} lit=${lit} open=${open} setOpen=${setOpen} box=${moreBox} />` : null}
    </div>
  </nav>`
}

/** The last tab of the bar: opens the pages that stand behind it. While one of them is open the tab
 *  carries its name; else the strongest colour a tab behind it carries for a reason, a finding red, a warning
 *  amber, as a dot. A grey count, a green ok or a running agent is no reason */
function MoreTab({ items, s, c, lit, open, setOpen, box }) {
  const t = T()
  const current = items.find(x => x.id === lit)
  const flags = items.filter(x => x.id !== lit).map(x => x.flag)
  const flag = flags.includes('danger') ? 'danger' : flags.includes('warning') ? 'warning' : null
  const pick = id => { setOpen(false); c.setPage(id) }
  // the bar scrolls sideways and would clip a menu inside it, so the menu stands fixed under the tab
  const [at, setAt] = useState(null)
  const toggle = e => { const r = e.currentTarget.getBoundingClientRect(); setAt({ top: r.bottom + 4, left: Math.max(8, Math.min(r.left, window.innerWidth - 248)) }); setOpen(!open) }
  return html`<span class="ptab-more" ref=${box}>
    <button type="button" role="tab" class=${`ptab${current ? ' is-active' : ''}`} aria-selected=${String(!!current)}
      aria-haspopup="menu" aria-expanded=${String(open)} onClick=${toggle}>
      <span>${current ? current.label : t.morePages}</span>${current ? current.badge : flag ? html`<${Dot} token=${flag} />` : null}
      <span aria-hidden="true">▾</span></button>
    ${open ? html`<span class="settle-menu more-menu" role="menu" style=${at ? { top: `${at.top}px`, left: `${at.left}px` } : undefined}>
      ${items.map(x => html`<button key=${x.id} type="button" role="menuitem" class=${`settle-item${x.id === lit ? ' is-on' : ''}`}
        title=${x.keyHint} onClick=${() => pick(x.id)}><span>${x.label}</span>${x.badge}</button>`)}
    </span>` : null}
  </span>`
}

/** "‹ Operations" at the head of a sub page: the way back to the page it stands under (parentOf), none elsewhere */
export function ParentLink({ s, c }) {
  const t = T()
  const up = parentOf(s, s.ui.page)
  const page = up ? (s.model?.pages ?? []).find(p => p.id === up) : null
  if (!page) return null
  return html`<button type="button" class="btn-link page-up" aria-label=${t.parentBackLabel(page.title)}
    onClick=${() => c.setPage(up)}>${t.parentBack(page.title)}</button>`
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
