// SPDX-License-Identifier: MIT
// Preact + htm components of the cockpit (contract section 7).
// Rendering goes only through htm templates, so every text is escaped; nothing here
// sets raw HTML. Components read the store snapshot `s` and call the controller `c`;
// they never decide which action applies to a row, the server's model says so.

import { html, useEffect, useLayoutEffect, useRef, useState } from './vendor/htm-preact-3.1.1.module.js'
import {
  DAY, attentionTabs, clockTime, detailNeedsLoad, duration, etaSeconds, formatClock, formatDay, groupTabs, indexRows,
  isoDate, markToken, nextFocusIndex, nextMonday, noteToken, pageWarnings, parseDate, prioToken, sessionCounts,
  sectionRows, short, startRefusal, stateToken, toneToken,
  VERDICT_ORDER, centsText, confidenceDots, reviewRows, verdictCounts, verdictToken,
  agentLane, checkFlow, gaugeArc, gaugeBands, gaugePoint, gaugeSection, laneWindow, meterScale, meterText, meterView,
  canTab, chatStamp, runProgress, screenLines, TONE_FILTERS, FILTER_TONE, actionRow, pageItemActs, filterRows, groupRows, tagFacets, toneFilter, runToken, serious, statusSplit, detailText, scheduleText, dayNoteText, railShown, tabNextStep, previewText, weekdayNames, triageKey, triageShows, verdictSegments, linkParts, probeText, newestFirst, filterWorkers, groupBySystem, stripMark, workerFacets, workerTone,
  sectionTile, tokenText, usageBars, usageToday, USAGE_SOURCES, jevList, workKinds, reviewHome, workPageOf, workViewOf, workViews,
  greetingPart, homeCatalog, homeChosen, homeContinue, homeProjects, inProject, meterPace, projectTone, tabOfTask,
  countInProject, focusPick, moveId, nextEvent, upcomingEvents, untilText, STAGE, stageDust, stageSpots, clockLeft, pulseSpeed,
  liveStage, stageTone, RETURN_STAGES, MAX_STATIONS, situation, situationText, parseVerdict, TASK_LANES, taskLane,
} from './logic.js'
import { flash, flowAlpha, flowPoints, nowSec, reducedMotion, settled, springTo } from './motion.js'
import { T, language } from './text.js'
import { TriageBar, TriageGist } from './triage.js'
import { InnerRoom } from './inner.js'

// Jev is an optional integration (integrations.typesafe): its page and stylesheet load only once it is
// switched on and has its key, so a Bridge without it never fetches them
export const JEV_PAGE = '@jev'
let jevPage = null      // the loaded module, or { failed: true }
function useJevPage(enabled) {
  const [, tick] = useState(0)
  useEffect(() => {
    if (!enabled || jevPage) return
    const css = document.createElement('link')
    css.rel = 'stylesheet'
    css.href = 'jev/jev.css'
    document.head.appendChild(css)
    import('./jev/page.js').then(m => { jevPage = m }, () => { jevPage = { failed: true } }).then(() => tick(n => n + 1))
  }, [enabled])
  return jevPage
}

const ASK_MAX = 4000
const TAB_MSG_MAX = 2000     // actions.py tab_send: check_text(..., 2000)
export const CHECK_PAGE = '@check'      // the task check's own page; profile pages never start with @
export const SESSIONS_PAGE = '@sessions'
export const WORKERS_PAGE = '@workers'
export const CHAT_PAGE = '@chat'
export const AGENTS_PAGE = '@agents'
export const START_PAGE = '@start'     // the start screen: greeting, projects, cards that lead into the work

/** Every page with whether it stands behind More: the fixed pages, then the profile's. The system
 *  views (Workers, Agents, Check, Jev) and profile pages with `group: more` go behind More */
/** The page the task check stands on, when inbox and tasks share one (then the check has no tab of its own) */
function reviewHomeOf(s) {
  return reviewHome(s.model?.pages, T().workOrder.kinds)
}

function pageList(s) {
  // In front the few tabs of every day: Start, Today, Chat and the profile's main pages (Work, Operations).
  // Everything else stands behind them and folds behind More only when the bar has no room for it.
  // The Workers tab only where a worker view exists, Agents only where this Bridge knows an A2A peer;
  // a page of group `day` has no tab, its sections stand under the day list of Today (DayColumn)
  return [{ id: START_PAGE }, { id: 'briefing' }, { id: CHAT_PAGE }, { id: SESSIONS_PAGE, more: true },
    ...(s.workers?.status === 'none' ? [] : [{ id: WORKERS_PAGE, more: true }]),
    ...((s.agents?.peers ?? []).length ? [{ id: AGENTS_PAGE, more: true }] : []), ...(reviewHomeOf(s) ? [] : [{ id: CHECK_PAGE, more: true }]),
    ...(s.jev?.enabled && !workPageOf(s.model?.pages)?.jev ? [{ id: JEV_PAGE, more: true }] : []),
    ...(s.model?.pages ?? []).filter(p => p.group !== 'day' && p.group !== 'work').map(p => ({ id: p.id, more: p.group === 'more' }))]
}

/** The name of the briefing's tab: the title of the work page where one folds into it, else Today */
function briefingTitle(s) {
  return workPageOf(s.model?.pages)?.title || T().briefing
}

/** The view the briefing's tab shows: what is due, by source or by Jev (logic.js workViewOf); on any
 *  other tab what is due, so nothing there changes */
export function workViewNow(s) {
  return s.ui?.page === 'briefing' ? workViewOf(s.ui.workView, workPageOf(s.model?.pages), s.jev) : 'due'
}

/** Whether the main area shows a page rather than the day's three columns */
const onPageOf = s => s.ui.page !== 'briefing' || workViewNow(s) !== 'due'

/** Every page in tab bar order: the tabs in front, then those behind More. Alt 1 to Alt 9 follow this order */
export function pageOrder(s) {
  const list = pageList(s)
  return [...list.filter(p => !p.more), ...list.filter(p => p.more)].map(p => p.id)
}

/** The pages behind the bar's More menu */
export function morePages(s) {
  return new Set(pageList(s).filter(p => p.more).map(p => p.id))
}

// ---------------------------------------------------------------- motion (motion.js, from the explainer films)

/** A number that follows its target with the film spring; a new target in mid move bends the path.
 *  `start` makes the first render run up from there. Under reduced motion the target stands at once */
function useTween(target, { start, w = 9, zeta = 0.95 } = {}) {
  const o = { w, zeta }
  const st = useRef(null)
  const [, tick] = useState(0)
  const still = reducedMotion()
  if (st.current === null) {
    const from = start ?? target
    st.current = { from, to: target, moves: from !== target && !still ? [[nowSec(), target]] : [] }
    if (still) st.current.from = target
  }
  const m = st.current
  if (target !== m.to) {
    if (still) { m.from = target; m.moves = [] } else m.moves = [...m.moves, [nowSec(), target]]
    m.to = target
  }
  useEffect(() => {
    if (!m.moves.length) return undefined
    let id = requestAnimationFrame(function step() {
      if (settled(nowSec(), m.moves, o)) { m.from = m.to; m.moves = []; tick(n => n + 1); return }
      tick(n => n + 1)
      id = requestAnimationFrame(step)
    })
    return () => cancelAnimationFrame(id)
  }, [m.moves])
  return m.moves.length ? springTo(nowSec(), m.from, m.moves, o) : m.to
}

/** Seconds on the page clock, a new render every frame while `active`; reduced motion never ticks */
function useClock(active) {
  const [T, setT] = useState(nowSec)
  useEffect(() => {
    if (!active || reducedMotion()) return undefined
    let id = requestAnimationFrame(function step() { setT(nowSec()); id = requestAnimationFrame(step) })
    return () => cancelAnimationFrame(id)
  }, [active])
  return T
}

/** A counter for each time `value` changes and `counts(before, value)` says it counts; keyed elements replay their hit once */
function useHits(value, counts = () => true) {
  const last = useRef(value)
  const n = useRef(0)
  if (value !== last.current) {
    if (last.current !== undefined && counts(last.current, value)) n.current += 1
    last.current = value
  }
  return n.current
}

/** A number counting to its value in tabular figures, so nothing beside it moves */
function CountNum({ value, start = 0, cls = '' }) {
  const v = useTween(Number(value) || 0, { start })
  return html`<span class=${`num ${cls}`}>${v.toFixed(0)}</span>`
}

// ---------------------------------------------------------------- small parts

const ICONS = {
  history: 'M3 12a9 9 0 1 0 2.6-6.4L3 8M3 3v5h5M12 7v5l3 2',
  reload: 'M20 11a8 8 0 1 0-2.34 5.66M20 4v7h-7',
  help: 'M9.1 9a3 3 0 0 1 5.8 1c0 2-3 2.5-3 4.5M12 18h.01M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z',
  sun: 'M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4',
  moon: 'M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z',
  auto: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 3v18',
  bell: 'M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9M10.3 21a1.94 1.94 0 0 0 3.4 0',
  close: 'M18 6 6 18M6 6l12 12',
  external: 'M15 3h6v6M10 14 21 3M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6',
  copy: 'M9 9h11v11H9zM5 15H4V4h11v1',
  chevronDown: 'M6 9l6 6 6-6',
  chevronRight: 'M9 6l6 6-6 6',
  back: 'M15 18l-6-6 6-6',
  tabs: 'M3 5h18v14H3zM15 5v14',
  send: 'M22 2 11 13M22 2l-7 20-4-9-9-4 20-7z',
  spark: 'M12 3v4M12 17v4M3 12h4M17 12h4',
  mic: 'M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3zM5 11a7 7 0 0 0 14 0M12 18v3',
}

function Icon({ name, size = 16 }) {
  return html`<svg class="icon" width=${size} height=${size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
    stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
    <path d=${ICONS[name]} /></svg>`
}

/** Status dot; the written word always sits beside it (state never by color alone) */
function Dot({ token, pulse }) {
  return html`<span class=${`dot tk-${token}${pulse ? ' dot-pulse' : ''}`} aria-hidden="true"></span>`
}

function Btn({ variant = 'secondary', size = 'sm', onClick, disabled, busy, title, pressed, children, label, icon, cls = '' }) {
  return html`<button type="button" class=${`btn btn-${variant} btn-${size} ${cls}`} onClick=${onClick}
    disabled=${disabled || busy} aria-busy=${busy ? 'true' : undefined} title=${title} aria-label=${label}
    aria-pressed=${pressed === undefined ? undefined : String(!!pressed)}>
    ${icon ? html`<${Icon} name=${icon} />` : null}${children ? html`<span class="btn-label">${children}</span>` : null}
  </button>`
}

function Chip({ token, children, title, cls = '' }) {
  return html`<span class=${`chip ${token ? `chip-tk tk-${token}` : ''} ${cls}`} title=${title}>
    ${token ? html`<${Dot} token=${token} />` : null}<span>${children}</span></span>`
}

function StateLine({ token, word, strong }) {
  return html`<span class=${`state-line${strong ? ' is-strong' : ''}`}><${Dot} token=${token} /><span>${word}</span></span>`
}

function MarkChip({ mark }) {
  if (!mark) return null
  return html`<${Chip} token=${markToken(mark.color)} cls="chip-mark">${mark.label}<//>`
}

function PrioChip({ priority }) {
  if (!priority) return null
  return html`<span class=${`prio tk-${prioToken(priority)}`} title=${`${T().meta.priority} ${priority}`}>${priority}</span>`
}

/** The check's verdict on a task row; nothing for "continue" or a recommendation kept open */
function VerdictChip({ review }) {
  if (!review || review.kept || review.verdict === 'continue') return null
  return html`<${Chip} token=${verdictToken(review.verdict)} title=${review.reason ?? undefined}>${T().verdictTag[review.verdict] ?? review.verdict}<//>`
}

function Empty({ children }) {
  return html`<p class="empty">${children}</p>`
}

function Spinner() {
  return html`<span class="spinner" aria-hidden="true"></span>`
}

function LinkView({ link, c, onOpenTask }) {
  const t = T()
  if (!link) return null
  if (link.kind === 'web') {
    return html`<a class="link-out" href=${link.href} target="_blank" rel="noopener noreferrer">
      <span class="link-text">${short(link.href, 64)}</span><${Icon} name="external" size=${14} /></a>`
  }
  const m = /^work\/(?:tasks|streams)\/([a-z0-9][a-z0-9-]*)\/STATUS\.md$/.exec(link.path ?? '')
  return html`<span class="link-file">
    ${m && onOpenTask
      ? html`<button type="button" class="btn-link mono" onClick=${() => onOpenTask(m[1])}>${link.path}</button>`
      : html`<code>${link.path}</code>`}
    <${Btn} variant="ghost" size="xs" icon="copy" label=${t.copyPath} title=${t.copyPath} onClick=${() => c.copy(link.path)} />
  </span>`
}

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

function AsOf({ s }) {
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

function RelayBadge({ s, c }) {
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

/** The relay has nobody to ask: a session can be started in the control workspace with one click */
function canStartControl(s) {
  const r = s.relay ?? {}
  return !!r.enabled && !r.online && (r.reason === 'no_heartbeat' || r.reason === 'no_control') && !!s.cmux?.ok
}

function StartControl({ s, c, size = 'xs', short: brief = false }) {
  const t = T()
  if (!canStartControl(s)) return null
  return html`<${Btn} size=${size} variant="primary" busy=${!!s.ui.busy.start_control} title=${t.startControlTitle}
    onClick=${() => c.act('start_control', {})}>${brief ? t.btnStartControlShort : t.btnStartControl}<//>`
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

function Header({ s, c }) {
  const t = T()
  const themeIcon = s.ui.theme === 'dark' ? 'moon' : s.ui.theme === 'light' ? 'sun' : 'auto'
  const waiting = attentionTabs(s.tabs?.tabs).length
  return html`<header class="hdr">
    <div class="hdr-id">
      <span class="eyebrow">${t.appName}</span>
      <div class="hdr-name"><h1 class="hdr-title">${t.cockpit}</h1>
        ${s.mock ? html`<span class="hdr-demo" title=${t.mockNote}><span class="hdr-demo-long">${t.demoBadge}</span><span class="hdr-demo-short">${t.demoBadgeShort}</span></span>` : null}</div>
    </div>
    <span class="hdr-headline" aria-hidden="true"></span>
    <div class="hdr-right">
      <${LoadingIndicator} s=${s} />
      ${s.layout === 'narrow' ? null : html`<${AsOf} s=${s} />`}
      ${s.layout === 'narrow' ? null : html`<${CommandBox} c=${c} />`}
      ${s.layout === 'medium' || (s.layout === 'wide' && !railShown(s.ui.page)) ? html`<${Btn} variant=${waiting ? 'primary' : 'secondary'} size="sm" icon="tabs"
        onClick=${() => c.setDrawer(s.ui.drawer === 'tabs' ? null : 'tabs')} pressed=${s.ui.drawer === 'tabs'}>${t.tabsButton(waiting)}<//>` : null}
      <${Btn} variant="ghost" size="sm" icon="reload" title=${t.reloadTitle} label=${t.reloadTitle}
        busy=${!!s.loading?.pass && s.loading?.fresh} onClick=${c.reload} cls="hdr-reload"><span class="hide-narrow">${t.reload}</span><//>
      <${Btn} variant=${(s.quick?.convs ?? []).some(x => x.running) ? 'primary' : 'secondary'}
        size="sm" icon="send" onClick=${() => c.openAsk()} title=${t.claudeOpenTitle} label=${t.askTitle} cls="hdr-ask">${t.askTitle}<//>
      <${Btn} variant="ghost" size="sm" icon="history" title=${t.historyTitle} label=${t.historyTitle}
        pressed=${s.ui.drawer === 'history'} onClick=${() => s.ui.drawer === 'history' ? c.setDrawer(null) : c.openHistory()}><span class="hide-narrow">${t.historyButton}</span><//>
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

function PageBadge({ badge, title }) {
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

function PageBar({ s, c }) {
  const t = T()
  const pages = s.model?.pages ?? []
  const tabsRef = useRef(null)
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
  const toClose = s.model?.review?.last?.to_close ?? 0
  // the Sessions tab shows the number the Sessions station shows, the running agents stand in its tooltip
  const sess = sessionCounts(s.sessions?.sessions)
  return html`<nav class="pagebar" aria-label=${t.pagesLabel} ref=${navRef}>
    <div class="pagebar-tabs" role="tablist" ref=${tabsRef}>
      ${box ? html`<${TabMarker} box=${box} />` : null}
      ${tab(START_PAGE, t.startTab, null)}
      ${tab('briefing', briefingTitle(s), n > 0 ? html`<span class="pbadge" title=${t.badgeWaiting(n, s.model?.counts?.give ?? 0)}><${Dot} token="warning" /><span class="mono">${n}</span></span>` : null)}
      ${tab(SESSIONS_PAGE, t.sessionsTab, sess.sessions > 0
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

function AlarmBanner({ s, c }) {
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

// ---------------------------------------------------------------- left column: the day

function RowMeta({ row, s }) {
  const t = T()
  const parts = []
  if (row.tab) parts.push(html`<${Chip} token=${stateToken(row.tab.state)}>${t.state[row.tab.state] ?? row.tab.state}<//>`)
  if (row.starting) parts.push(html`<${Chip} token="info">${t.startingTab}<//>`)
  const liveSessions = row.task && !row.inbox_id ? (s?.sessions?.sessions ?? []).filter(x => x.task === row.task).length : 0
  if (liveSessions) parts.push(html`<span class="chip chip-task">${t.sessionsOnTask(liveSessions)}</span>`)
  if (row.mark) parts.push(html`<${MarkChip} mark=${row.mark} />`)
  if (row.priority) parts.push(html`<${PrioChip} priority=${row.priority} />`)
  if (row.review) parts.push(html`<${VerdictChip} review=${row.review} />`)
  if (row.urgency === 'now' || row.urgency === 'today') parts.push(html`<${Chip} token=${row.urgency === 'now' ? 'danger' : 'warning'}>${t.urgency[row.urgency]}<//>`)
  if (row.due) parts.push(html`<span class="meta-due">${t.dueOn(formatDay(row.due, language()))}</span>`)
  if (row.is_new) parts.push(html`<span class="chip chip-active">${t.isNew}</span>`)
  else if (row.is_changed) parts.push(html`<span class="chip chip-active">${t.isChanged}</span>`)
  if (row.area && row.area !== row.mark?.label) parts.push(html`<span class="meta-area">${row.area}</span>`)
  const why = (row.why ?? []).slice(0, 2).join(' · ')
  return html`<span class="row-meta">${parts}${why ? html`<span class="meta-why">${why}</span>` : null}</span>`
}

function RowActions({ row, s, c, all = false }) {
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
function SettleMenu({ rows, s, c, size = 'xs' }) {
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
function PageItemActions({ it, s, c, after }) {
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
      <${RowMeta} row=${row} s=${s} />
      <${ReturnChip} s=${s} rowKey=${[row.key, row.task ? `task:${row.task}` : null]} />
    </button>
    <span class="row-acts"><${RowActions} row=${row} s=${s} c=${c} /><${SettleMenu} rows=${[row]} s=${s} c=${c} /><${PinStar} rowKey=${row.key} s=${s} c=${c} /></span>
  </li>`
}

function Section({ section, s, c, byKey }) {
  const t = T()
  const expanded = !!s.ui.expanded[section.id]
  const rows = sectionRows(section, expanded, byKey)
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
function WorkSwitch({ s, c }) {
  const t = T()
  const views = workViews(workPageOf(s.model?.pages), s.jev)
  if (views.length < 2) return null
  const view = workViewNow(s)
  return html`<div class="fbar-chips work-switch" role="radiogroup" aria-label=${t.workOrder.viewLabel}>
    ${views.map(v => html`<button type="button" role="radio" key=${v} aria-checked=${String(view === v)}
      class=${`fchip${view === v ? ' is-on' : ''}`} onClick=${() => c.setWorkView(v)}>${t.workOrder.views[v]}</button>`)}
  </div>`
}

function DayColumn({ s, c, byKey }) {
  const t = T()
  const m = s.model
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
  const order = ['now', 'give', 'work', 'later']
  return html`<div class="col col-day">
    <div class="panel day-panel">
      <${WorkSwitch} s=${s} c=${c} />
      <${SelectionBar} s=${s} c=${c} />
      <${AlarmBanner} s=${s} c=${c} />
      <div class="day-counts muted"><span class="day-asof">${t.sourceAsOf(m.collected_at)}</span></div>
      ${s.layout === 'wide' ? null : html`<${WaitingTabs} s=${s} c=${c} />`}
      ${total === 0 && !attentionTabs(s.tabs?.tabs).length ? html`<div class="callout">${t.emptyHint}</div>` : null}
      ${total === 0 ? null : order.map(id => {
        const sec = (m.sections ?? []).find(x => x.id === id)
        return sec ? html`<${Section} key=${id} section=${sec} s=${s} c=${c} byKey=${byKey} />` : null
      })}
      <${HiddenList} s=${s} c=${c} />
    </div>
  </div>`
}

function Skeleton({ lines = 5 }) {
  return html`<div class="skeleton" aria-hidden="true">${Array.from({ length: lines }, (_, i) => html`<span key=${i} class="skel-line"></span>`)}</div>`
}

// ---------------------------------------------------------------- center: overview and detail

function Overview({ s, c }) {
  const t = T()
  const m = s.model
  if (!m) return html`<div class="panel panel-pad"><${Skeleton} lines=${6} /></div>`
  const head = html`
    <span class="eyebrow">${t.overviewTitle}</span>
    <h2 class="detail-title">${t.forYouNow(m.briefing_badge ?? 0)}${m.headline_rest ? ` · ${m.headline_rest}` : ''}</h2>
    ${m.since ? html`<p class="muted">${m.since}</p>` : null}`
  // with a work tab the day (dates, status, what happened) stands on Start; here only the headline and the way there
  if (workPageOf(m.pages)) {
    return html`<div class="panel panel-pad overview">${head}
      <p class="row-in muted">${t.dayOnStart}
        <${Btn} size="xs" variant="secondary" onClick=${() => c.setPage(START_PAGE)}>${t.dayOnStartOpen}<//></p>
      <p class="hint muted">${t.detailEmpty}</p>
    </div>`
  }
  return html`<div class="panel panel-pad overview">${head}
    <${DayView} s=${s} c=${c} />
    <p class="hint muted">${t.detailEmpty}</p>
  </div>`
}

/** The day: dates, status, what is clear, what needs tidying, the workplace and the pages of group day.
 *  In the middle of Today as one panel, or on Start where a work tab exists as one card per block,
 *  where the pages of group day stand as a shelf of their own (DayPages) */
function DayView({ s, c, cards = false }) {
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
    { id: 'status', title: t.statusTitle, body: html`<${StatusList} rows=${m.status} />` },
    (ex.clear ?? []).length ? { id: 'clear', title: t.clearTitle,
      body: html`<ul class="plain">${ex.clear.map((x, i) => html`<li key=${i}><${StateLine} token="success" word=${x} /></li>`)}</ul>` } : null,
    (ex.hygiene ?? []).length ? { id: 'hygiene', title: t.hygieneTitle,
      body: html`<ul class="plain">${ex.hygiene.map((x, i) => html`<li key=${i}><${StateLine} token="warning" word=${x} /></li>`)}</ul>` } : null,
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
    <div class="ov-grid">
      <div class="ov-block"><h3 class="label-caps">${agenda.title}</h3>${agenda.body}</div>
      <div class="ov-block"><h3 class="label-caps">${status.title}</h3>${status.body}</div>
    </div>
    ${rest.map(b => html`<div key=${b.id} class="ov-block"><h3 class="label-caps">${b.title}</h3>${b.body}</div>`)}
    <${DayPages} s=${s} c=${c} />
  </div>`
}

/** The pages of group day (what happened today), one section each */
function DayPages({ s, c, shelf = false }) {
  return (s.model?.pages ?? []).filter(p => p.group === 'day').map(p => html`<section key=${p.id}
    class=${shelf ? 'home-shelf day-more' : 'day-more'} aria-label=${p.title}>
    ${shelf ? html`<header class="home-shelf-head"><h2 class="home-shelf-title">${p.title}</h2></header>`
      : html`<h3 class="label-caps day-more-title">${p.title}</h3>`}
    ${(p.sections ?? []).map(sec => html`<${PageSection} key=${sec.id} page=${p} section=${sec} s=${s} c=${c} />`)}
  </section>`)
}

/** Status rows: failures and counts in view, the quiet ones (healthy, nothing to count) under one line */
function StatusList({ rows }) {
  const t = T()
  const { loud, quiet } = statusSplit(rows)
  const line = (x, i) => html`<li key=${i} title=${x.reason ?? undefined}>
    <${StateLine} token=${x.tone === 'neutral' ? 'on-surface-muted' : x.tone} strong=${x.tone === 'danger'} word=${x.title} />
    <span class="mono muted">${x.state === 'error' ? (x.reason || t.tone.bad) : x.state === 'skipped' ? t.skippedSection : x.count}</span></li>`
  return html`<ul class="status-list">${loud.map(line)}</ul>
    ${quiet.length ? html`<details class="status-quiet">
      <summary class="muted">${t.statusQuiet(quiet.length)}</summary>
      <ul class="status-list">${quiet.map(line)}</ul>
    </details>` : null}`
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
  ].filter(([, v]) => v)
  return html`<dl class="meta">${items.map(([k, v]) => html`<div class="meta-item" key=${k}><dt>${t.meta[k]}</dt><dd>${v}</dd></div>`)}</dl>`
}

function DateBlock({ row, s, c }) {
  const t = T()
  const [text, setText] = useState('')
  const [err, setErr] = useState('')
  const busy = !!s.ui.busy[row.key]
  const now = s.now
  const pick = verb => {
    const iso = parseDate(text, now)
    if (!iso) return setErr(t.noDate(text || ' '))
    if (iso <= isoDate(now)) return setErr(t.pastDate)
    setErr('')
    setText('')
    c.act(verb, { key: row.key, until: iso })
  }
  const id = `date-${row.key}`
  return html`<div class="block">
    <h3 class="label-caps">${t.laterTitle}</h3>
    <div class="btn-row">
      <${Btn} size="xs" busy=${busy} onClick=${() => c.act('later', { key: row.key, until: isoDate(now + DAY) })}>${t.btnTomorrow}<//>
      <${Btn} size="xs" busy=${busy} onClick=${() => c.act('later', { key: row.key, until: isoDate(nextMonday(now)) })}>${t.btnMonday}<//>
      <${Btn} size="xs" busy=${busy} onClick=${() => c.act('later', { key: row.key, until: isoDate(now + 7 * DAY) })}>${t.btnWeek}<//>
    </div>
    <div class="field-row">
      <label class="sr-only" for=${id}>${t.dateLabel}</label>
      <input id=${id} class="input input-date mono" type="text" inputmode="numeric" placeholder=${t.datePlaceholder} value=${text}
        aria-invalid=${err ? 'true' : undefined} onInput=${e => { setText(e.currentTarget.value); setErr('') }}
        onKeyDown=${e => { if (e.key === 'Enter') pick('later') }} />
      <${Btn} size="xs" busy=${busy} onClick=${() => pick('later')}>${t.btnLater}<//>
      <${Btn} size="xs" variant="ghost" busy=${busy} onClick=${() => pick('hide')}>${t.btnHideUntil}<//>
    </div>
    ${err ? html`<p class="field-err" role="alert"><${StateLine} token="danger" word=${err} /></p>` : null}
  </div>`
}

function Segmented({ label, values, current, onPick, busy }) {
  return html`<div class="seg" role="group" aria-label=${label}>
    ${values.map(([v, word]) => html`<button type="button" key=${v} class=${`seg-btn${current === v ? ' is-on' : ''}`}
      aria-pressed=${String(current === v)} disabled=${busy} onClick=${() => current !== v && onPick(v)}>${word}</button>`)}
  </div>`
}

function NoteBlock({ row, s, c }) {
  const t = T()
  const [text, setText] = useState('')
  const busy = !!s.ui.busy[row.key]
  const id = `note-${row.key}`
  const send = async () => {
    const v = text.trim()
    if (!v) return
    const r = await c.act('note', { key: row.key, text: v })
    if (r) setText('')
  }
  return html`<div class="block">
    <label class="label-caps" for=${id}>${t.noteLabel}</label>
    <div class="field-row">
      <input id=${id} class="input" type="text" maxlength="2000" placeholder=${t.notePlaceholder} value=${text}
        onInput=${e => setText(e.currentTarget.value)} onKeyDown=${e => { if (e.key === 'Enter') send() }} />
      <${Btn} size="xs" busy=${busy} disabled=${!text.trim()} onClick=${send}>${t.btnNote}<//>
    </div>
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

function ActionsBlock({ row, s, c }) {
  const t = T()
  const busy = !!s.ui.busy[row.key]
  const launch = !!(row.inbox_id || row.task)
  const startable = launch && row.inbox_state !== 'approved' && !startRefusal(row) && !(row.tab && row.tab.live)
  const ids = (row.actions ?? []).map(a => a.id)
  return html`<div class="block block-actions">
    <h3 class="label-caps">${t.actionsTitle}</h3>
    <div class="btn-row">
      <${RowActions} row=${row} s=${s} c=${c} all />
      <${SettleMenu} rows=${[row]} s=${s} c=${c} />
      ${!ids.includes('drop') ? html`<${Btn} size="xs" variant="ghost" busy=${busy} onClick=${() => c.act('drop', { key: row.key })}>${t.action.drop}<//>` : null}
      ${!ids.includes('ask') ? html`<${Btn} size="xs" variant="ghost" busy=${!!s.ui.busy['ask:row']} onClick=${() => c.ask('row', { key: row.key })}>${t.askChat}<//>` : null}
      ${row.bucket === 'waiting' && !ids.includes('follow_up') ? html`<${Btn} size="xs" variant="ghost" onClick=${() => c.ask('follow_up', { key: row.key })}>${t.action.follow_up}<//>` : null}
    </div>
    ${row.task && !row.inbox_id ? html`<${ReviewBlock} row=${row} s=${s} c=${c} />` : null}
    ${row.task && !row.inbox_id ? html`<${TaskSessions} row=${row} s=${s} c=${c} />` : null}
    ${startable ? html`<div class="sub-block">
      <h4 class="sub-title">${t.startTitle}</h4>
      <div class="btn-row">
        <${Btn} size="xs" variant="secondary" busy=${busy} onClick=${() => c.act('do_it', { keys: [row.key], target: 'workspace' })}>${t.btnDoOwnWs}<//>
        <${Btn} size="xs" variant="ghost" busy=${busy} onClick=${() => c.act('do_it', { keys: [row.key], target: 'tab' })}>${t.where.tab}<//>
        <${Btn} size="xs" variant="ghost" busy=${busy} onClick=${() => c.act('do_it', { keys: [row.key], target: 'area' })}>${t.where.area}<//>
        <${Btn} size="xs" variant="ghost" busy=${busy} onClick=${() => c.act('collect_context', { key: row.key })}>${t.btnCollect}<//>
      </div>
    </div>` : null}
    ${row.inbox_id ? html`<div class="sub-block">
      <h4 class="sub-title">${t.urgencyPrefix}</h4>
      <${Segmented} label=${t.urgencyPrefix} busy=${busy} current=${row.urgency}
        values=${['now', 'today', 'later'].map(v => [v, t.urgency[v]])} onPick=${v => c.act('urgency', { key: row.key, value: v })} />
    </div>` : row.task ? html`<div class="sub-block">
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

function TabControls({ tab, s, c, compact = false, slim = false }) {
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
  if (slim) {
    const step = {
      yes: () => html`<${Btn} size="xs" variant="primary" busy=${busy} onClick=${() => c.act('tab_yes', { tab_ref: tab.ref })}>${t.btnYes}<//>`,
      no: () => html`<${Btn} size="xs" variant="secondary" busy=${busy} onClick=${() => c.act('tab_no', { tab_ref: tab.ref })}>${t.btnNo}<//>`,
      go_on: () => html`<${Btn} size="xs" variant="secondary" busy=${busy} onClick=${() => c.act('tab_go_on', { tab_ref: tab.ref })}>${t.btnGoOn}<//>`,
      close: () => html`<${Btn} size="xs" variant="secondary" busy=${busy} onClick=${() => c.act('tab_close', { tab_ref: tab.ref })}>${t.btnCloseTab}<//>`,
      jump: () => html`<${Btn} size="xs" variant="ghost" busy=${busy} onClick=${() => c.act('tab_jump', { tab_ref: tab.ref })}>${t.btnToTab}<//>`,
      view: () => html`<${Btn} size="xs" variant="ghost" onClick=${() => c.openTabView(tab.ref)}>${t.btnTabView}<//>`,
    }
    return tabNextStep(tab, v => canTab(s, v)).map(k => step[k]())
  }
  return html`<div class="tab-ctl">
    <div class="btn-row">
      ${tab.state === 'needs-you' && canTab(s, 'key') ? html`
        <${Btn} size="xs" variant="primary" busy=${busy} onClick=${() => c.act('tab_yes', { tab_ref: tab.ref })}>${t.btnYes}<//>
        <${Btn} size="xs" variant="secondary" busy=${busy} onClick=${() => c.act('tab_no', { tab_ref: tab.ref })}>${t.btnNo}<//>` : null}
      ${tab.state === 'waiting' && !tab.filed_by && !tab.is_control ? html`<${Btn} size="xs" variant="secondary" busy=${busy}
        onClick=${() => c.act('tab_go_on', { tab_ref: tab.ref })}>${t.btnGoOn}<//>` : null}
      ${tab.state === 'waiting' && tab.filed_by && canTab(s, 'close') ? html`<${Btn} size="xs" variant="secondary" busy=${busy}
        onClick=${() => c.act('tab_close', { tab_ref: tab.ref })}>${t.btnCloseTab}<//>` : null}
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
      <${StateLine} token=${stateToken(tab.state)} strong=${tab.state === 'needs-you'} word=${t.state[tab.state] ?? tab.state} />
      <span class="muted">${tab.workspace ? `${tab.workspace} / ` : ''}${tab.name}</span>
      ${tab.since_ms ? html`<span class="mono muted">${t.sinceFor(duration(s.now - tab.since_ms))}</span>` : null}
    </div>
    ${tab.last ? html`<p class="tab-last">${tab.last}</p>` : null}
    ${tab.filed_by ? html`<p class="muted"><${StateLine} token="success" word=${t.resultFiledLong} /></p>` : null}
    <${TabControls} tab=${tab} s=${s} c=${c} />
  </div>`
}

/** A failed detail load: what went wrong, and a button that tries again */
function DetailFailed({ d, onRetry }) {
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

function Lines({ lines }) {
  const t = T()
  return html`<ul class="lines">${lines.map((l, i) => html`<li key=${i}><span class="line-kind">${t.lineKind[l.kind] ?? `${l.kind}: `}</span><span>${l.text}</span></li>`)}</ul>`
}

function TaskDetail({ slug, s, c, exclude }) {
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
      ${f.headline ? html`<p class="task-headline">${f.headline}</p>` : null}
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
  return html`<div class="block task-detail">
    <h3 class="label-caps">${t.taskTitle}: <span class="mono">${slug}</span></h3>
    ${lines.length ? html`<${Lines} lines=${lines} />` : null}
    ${body}
    ${entries.length ? html`<div class="sub-block"><h4 class="sub-title">${t.taskEntries}</h4>
      <ul class="entries">${entries.map(r => html`<li key=${r.key} class="entry">
        <button type="button" class="btn-link" onClick=${() => c.select(r.key)}>${short(r.title, 80)}</button>
        <span class="btn-row"><${RowActions} row=${r} s=${s} c=${c} all /></span></li>`)}</ul></div>` : null}
  </div>`
}

function RowDetail({ row, s, c }) {
  const t = T()
  const n = s.model?.numbers?.[row.key] ?? row.number
  const openTask = slug => c.select(`task:${slug}`)
  return html`<article class="panel panel-pad detail" aria-labelledby="detail-title">
    <${DetailBack} s=${s} c=${c} />
    <header class="detail-head">
      <span class="detail-eyebrow">${n ? html`<span class="sec-count mono" aria-label=${t.numberLabel(n)}>${n}</span>` : null}
        <span class="eyebrow">${t.section[row.section] ?? row.section}</span></span>
      <h2 class="detail-title" id="detail-title" tabindex="-1">${row.title}</h2>
      <div class="detail-chips">
        <${ReturnChip} s=${s} rowKey=${[row.key, row.task ? `task:${row.task}` : null]} />
        ${row.tab ? html`<${Chip} token=${stateToken(row.tab.state)}>${t.state[row.tab.state]}<//>` : null}
        <${MarkChip} mark=${row.mark} /><${PrioChip} priority=${row.priority} />
        ${row.hidden_until ? html`<span class="chip">${t.hiddenUntil(formatDay(row.hidden_until, language()))}</span>` : null}
      </div>
      <${LinkView} link=${row.link} c=${c} onOpenTask=${openTask} />
      ${row.task ? html`<${Btn} size="xs" variant="ghost" onClick=${() => c.openInner(`task:${row.task}`)}>${t.item.inNet}<//>` : null}
    </header>
    <${ReturnPanel} s=${s} c=${c} keys=${[row.key, row.task ? `task:${row.task}` : null]} />
    <${MetaList} row=${row} s=${s} />
    ${(row.why ?? []).length ? html`<div class="block"><h3 class="label-caps">${t.whyTitle}</h3>
      <ul class="why">${row.why.map((w, i) => html`<li key=${i}>${w}</li>`)}</ul></div>` : null}
    ${row.inbox_id ? html`<${InboxDetail} id=${row.inbox_id} s=${s} c=${c} />` : null}
    <${TabInfo} row=${row} s=${s} c=${c} />
    <${ActionsBlock} row=${row} s=${s} c=${c} />
    ${row.hidden_until ? html`<div class="block"><${Btn} size="xs" onClick=${() => c.act('unhide', { key: row.key })}>${t.btnShowAgain}<//></div>` : null}
    <${DateBlock} row=${row} s=${s} c=${c} />
    <${TeamBlock} row=${row} s=${s} c=${c} />
    ${row.task || row.inbox_id ? html`<${NoteBlock} row=${row} s=${s} c=${c} />` : null}
    ${row.task ? html`<${TaskDetail} slug=${row.task} s=${s} c=${c} exclude=${row.key} />` : null}
  </article>`
}

/** Back to the list: "close details" beside a page, "back" on a phone, nothing on a wide briefing */
function DetailBack({ s, c }) {
  const t = T()
  if (s.ui.pageDetail) return html`<${Btn} variant="ghost" size="xs" icon="back" onClick=${c.closePeek}>${t.closeDetail}<//>`
  if (s.layout === 'narrow') return html`<${Btn} variant="ghost" size="xs" icon="back" onClick=${() => c.setPane('day')}>${t.back}<//>`
  return null
}

function DetailColumn({ s, c, byKey }) {
  const t = T()
  const key = s.ui.selectedKey
  const row = key ? byKey.get(key) : null
  let body
  if (!key) body = html`<${Overview} s=${s} c=${c} />`
  else if (row) body = html`<${RowDetail} key=${row.key} row=${row} s=${s} c=${c} />`
  else if (key.startsWith('task:')) {
    body = html`<article class="panel panel-pad detail">
      <${DetailBack} s=${s} c=${c} />
      <header class="detail-head"><span class="eyebrow">${t.taskTitle}</span><h2 class="detail-title">${key.slice(5)}</h2></header>
      <${TaskDetail} slug=${key.slice(5)} s=${s} c=${c} /></article>`
  } else {
    body = html`<div class="panel panel-pad"><p class="muted">${t.rowGone}</p>
      ${s.ui.pageDetail ? html`<${Btn} size="xs" onClick=${c.closePeek}>${t.closeDetail}<//>`
        : html`<${Btn} size="xs" onClick=${() => c.select(null)}>${t.overviewTitle}<//>`}</div>`
  }
  return html`<div class="col col-detail">
    <div class="detail-scroll">${body}</div>
  </div>`
}

// ---------------------------------------------------------------- right column: agent tabs

/** Cost of a turn in cents, in the page language: 0.0021 $ -> "0,21 ct" */
function costText(usd, lang) {
  return usd == null ? '' : `${centsText(usd * 100, lang)} ct`
}

/** Three dots that rise in turn while Claude thinks (a spring per dot, offset by a third) */
function Thinking({ label }) {
  const T0 = useClock(true)
  return html`<span class="thinking" aria-live="polite"><span class="thinking-dots" aria-hidden="true">${[0, 1, 2].map(i => {
    const k = (Math.sin((T0 * 2 * Math.PI) / 1.1 - i * 0.9) + 1) / 2
    return html`<span key=${i} style=${{ transform: `translateY(${(-4 * k).toFixed(2)}px)`, opacity: (0.35 + 0.65 * k).toFixed(3) }}></span>`
  })}</span><span class="muted small">${label}</span></span>`
}

/** The message box of a chat or a tab: Enter sends, Shift+Enter breaks the line */
/** A text box with its send button. `alt` adds a second way to send ({ label, title, onSend, ready, busy }):
 *  Enter takes the first, Cmd or Ctrl Enter the second */
function SendBox({ id, label, value, setValue, onSend, max, placeholder, busy, disabled, sendLabel, autofocus = true, alt = null }) {
  const t = T()
  return html`<div class="field-row tabview-send">
    <label class="sr-only" for=${id}>${label}</label>
    <textarea id=${id} class="input" rows="2" maxlength=${max} placeholder=${placeholder} value=${value} data-autofocus=${autofocus ? '' : undefined}
      onInput=${e => setValue(e.currentTarget.value)}
      onKeyDown=${e => {
        if (e.key !== 'Enter' || e.shiftKey) return
        e.preventDefault()
        if (alt && (e.metaKey || e.ctrlKey)) { if (alt.ready) alt.onSend() } else onSend()
      }}></textarea>
    <span class="send-btns">
      <${Btn} size="sm" variant=${alt ? 'secondary' : 'primary'} icon="send" busy=${busy} disabled=${!value.trim() || disabled} onClick=${onSend}>${sendLabel ?? t.btnSend}<//>
      ${alt ? html`<${Btn} size="sm" variant="primary" icon="tabs" busy=${alt.busy} disabled=${!alt.ready} title=${alt.title} onClick=${alt.onSend}>${alt.label}<//>` : null}
    </span>
  </div>`
}

/** The turns of one chat; the turn being answered shows its text while it is written and what it reads */
function ChatThread({ s, conv }) {
  const t = T()
  const lang = language()
  const live = conv ? s.quickLive?.[conv.id] : null
  return conv.turns.map((x, i) => {
    const open = !x.a && !x.error && i === conv.turns.length - 1 && conv.running
    return html`<div class="qturn row-in" key=${i} style=${{ '--i': 0 }}>
      <div class="qq">${x.q}</div>
      ${x.a ? html`<div class="qa">${x.a}</div>`
        : x.error ? html`<p><${StateLine} token="danger" word=${x.error === 'interrupted' ? t.quickInterrupted : t.quickFailed(x.error)} /></p>`
        : open && live?.text ? html`<div class="qa is-live">${live.text}<span class="qcaret" aria-hidden="true"></span></div>` : null}
      ${open ? html`<${Thinking} label=${live?.doing ? t.quickReading(live.doing)
        : live?.text ? t.quickWriting : t.quickThinking(t.quickModel[x.model_asked] ?? x.model_asked)} />` : null}
      ${x.a ? html`<div class="qmeta mono small muted">${x.model ?? x.model_asked}${x.cost_usd != null ? ` · ${costText(x.cost_usd, lang)}` : ''}</div>` : null}
    </div>`
  })
}

/** Hand on, the cost so far, and the box for the next question (a reply goes on in the open chat) */
function ChatFoot({ s, c, conv, autofocus }) {
  const t = T()
  const lang = language()
  const [text, setText] = useState('')
  const model = s.ui.quickModel ?? s.quick?.default ?? 'haiku'
  const last = conv?.turns?.[conv.turns.length - 1]
  const total = conv ? conv.turns.reduce((n, x) => n + (x.cost_usd ?? 0), 0) : 0
  const costKnown = !conv || conv.turns.every(x => !x.a || x.cost_usd != null)
  const asked = last?.model_asked
  const send = async () => {
    const v = text.trim()
    if (!v || conv?.running) return
    if (await c.ask('free', { text: v })) setText('')
  }
  // the second way: a real Claude session in a cmux tab, which may act. A new problem opens one at once;
  // an open chat goes on there with what was said so far, and the text in the box as the order on top
  const answered = !!(conv && last?.a && !conv.running)
  const solve = async () => {
    const v = text.trim()
    if (conv ? !answered : !v) return
    const r = conv ? await c.act('quick_handoff', { conv: conv.id, to: 'tab', ...(v ? { text: v } : {}) }) : await c.act('chat_tab', { text: v })
    if (r) setText('')
  }
  const solveBusy = conv ? !!s.ui.busy[`quick:${conv.id}`] : !!s.ui.busy.chat_tab
  // no "to the control session" button: one stray click put a whole chat into the session at the
  // terminal (14.10.); a chat that needs acting goes to its own tab with "Get it done"
  return html`<footer class="tabview-foot">
    ${answered ? html`<div class="btn-row quick-next">
      <span class="muted small quick-total">${costKnown ? t.quickTotal(costText(total, lang)) : t.quickCostUnknown}${asked && asked !== model ? ` · ${t.quickSwitch(t.quickModel[model])}` : ''}</span>
    </div>` : null}
    <${SendBox} id="quick-input" label=${t.askLabel} value=${text} setValue=${setText} onSend=${send} max=${ASK_MAX} autofocus=${autofocus}
      placeholder=${conv ? t.quickReply : t.quickPlaceholder} busy=${!!s.ui.busy['ask:free']} disabled=${!!conv?.running} sendLabel=${t.chatAsk}
      alt=${{ label: t.chatSolve, title: t.chatSolveTitle, onSend: solve, busy: solveBusy, ready: conv ? answered : !!text.trim() }} />
    <p class="muted small chat-hint">${t.chatSolveHint}</p>
  </footer>`
}

function ModelPick({ s, c }) {
  const t = T()
  const model = s.ui.quickModel ?? s.quick?.default ?? 'haiku'
  return html`<${Segmented} label=${t.quickModelLabel} current=${model} values=${(s.quick?.models ?? ['haiku', 'sonnet', 'opus']).map(m => [m, t.quickModel[m] ?? m])}
      onPick=${m => c.setQuickModel(m)} /><span class="muted small">${t.quickModelHint[model] ?? ''}</span>
      ${s.ui.quickModel != null ? html`<button type="button" class="btn-link small" onClick=${() => c.setQuickModel(null)}>${t.quickServiceDefault}</button>` : null}`
}

/** The end of the thread stays in view while an answer grows */
function useStickToEnd(conv, live) {
  const body = useRef(null)
  const last = conv?.turns?.[conv.turns.length - 1]
  useLayoutEffect(() => { if (body.current) body.current.scrollTop = body.current.scrollHeight },
    [conv?.id, conv?.turns?.length, last?.a, conv?.running, live?.text?.length, live?.doing])
  return body
}

/** The chat window: ask straight away (the box has the cursor), the answer shows while it is written,
 *  a reply goes on in the same session (Haiku unless picked), recent chats one click away, and "As a tab"
 *  keeps it on the Chat tab. When it turns into work it goes to an agent tab (Sonnet or more) or to the
 *  control session. Nothing here changes a file */
function QuickChat({ s, c }) {
  const t = T()
  const q = s.quick ?? {}
  const convs = q.convs ?? []
  const conv = convs.find(x => x.id === s.ui.quickConv) ?? null
  const body = useStickToEnd(conv, conv ? s.quickLive?.[conv.id] : null)
  const dialog = useFocusOnOpen(true)
  return html`<div class="overlay overlay-center" onClick=${e => { if (e.target === e.currentTarget) c.closeTabView() }}>
    <div class="dialog tabview quickchat" role="dialog" aria-modal="true" aria-labelledby="quick-title" ref=${dialog}>
      <header class="tabview-head">
        <h2 class="sec-title tabview-title" id="quick-title">${t.askTitle}</h2>
        <${ModelPick} s=${s} c=${c} />
        <span class="tabview-live"></span>
        <button type="button" class="btn-link small" title=${t.quickAsTabTitle} onClick=${c.chatAsTab}>${t.quickAsTab}</button>
        ${s.tabs?.control?.ref ? html`<button type="button" class="btn-link small" onClick=${c.openClaude}>${t.quickToControl}</button>` : null}
        <${Btn} variant="ghost" size="xs" icon="close" label=${t.close} onClick=${c.closeTabView} />
      </header>
      ${convs.length ? html`<nav class="quick-convs" aria-label=${t.quickChats}>
        <button type="button" class=${`chip quick-conv${!conv ? ' is-on' : ''}`} onClick=${c.newQuick}>+ ${t.quickNew}</button>
        ${convs.slice(0, 8).map(x => html`<button type="button" key=${x.id} class=${`chip quick-conv${x.id === conv?.id ? ' is-on' : ''}`}
          title=${x.turns[0]?.q} onClick=${() => c.pickQuick(x.id)}>${x.running ? html`<${Dot} token="info" pulse /> ` : null}${short(x.turns[0]?.q ?? '', 34)}</button>`)}
      </nav>` : null}
      <div class="tabview-body quick-body" ref=${body} tabindex="-1" role="log" aria-label=${t.quickHistory}>
        ${q.config_error || !q.available ? html`<p><${StateLine} token="warning" word=${q.config_error ?? t.quickUnavailable} /></p>` : null}
        ${!conv ? html`<div class="quick-empty"><p class="muted">${t.quickIntro}</p></div>` : html`<${ChatThread} s=${s} conv=${conv} />`}
      </div>
      <${ChatFoot} key=${conv?.id ?? 'new'} s=${s} c=${c} conv=${conv} autofocus />
    </div>
  </div>`
}

/** The Chat tab: every kept chat on the left (first question, when, model, cost), the open one on the
 *  right with its box ready; a chat goes on where it stopped, also after a restart of the dashboard */
function ChatPage({ s, c }) {
  const t = T()
  const lang = language()
  const q = s.quick ?? {}
  const convs = q.convs ?? []
  const conv = convs.find(x => x.id === s.ui.quickConv) ?? null
  const body = useStickToEnd(conv, conv ? s.quickLive?.[conv.id] : null)
  const [forgetArmed, setForgetArmed] = useState(null)
  useEffect(() => { document.getElementById('quick-input')?.focus() }, [conv?.id])
  return html`<div class="col col-page chatpage">
    <header class="page-head"><h2 class="detail-title">${t.chatTab}</h2><${ModelPick} s=${s} c=${c} />
      ${conv && !conv.running ? html`<button type="button" class=${`chip quick-conv agent-forget${forgetArmed === conv.id ? ' is-armed' : ''}`}
        title=${t.quickForgetHint} onBlur=${() => setForgetArmed(null)}
        onClick=${() => forgetArmed === conv.id ? c.quickForget(conv.id) : setForgetArmed(conv.id)}>${forgetArmed === conv.id ? t.quickForgetSure : t.quickForget}</button>` : null}</header>
    <div class="chat-grid">
      <nav class="panel chat-list" aria-label=${t.quickChats}>
        <button type="button" class=${`chat-item chat-new${!conv ? ' is-on' : ''}`} onClick=${c.newQuick}>+ ${t.quickNew}</button>
        ${convs.length ? convs.map(x => {
          const costKnown = x.turns.every(y => !y.a || y.cost_usd != null)
          const cost = costKnown ? x.turns.reduce((n, y) => n + (y.cost_usd ?? 0), 0) : null
          const lastTurn = x.turns[x.turns.length - 1]
          return html`<button type="button" key=${x.id} class=${`chat-item${x.id === conv?.id ? ' is-on' : ''}`} onClick=${() => c.pickQuick(x.id)}
            aria-current=${x.id === conv?.id ? 'true' : undefined}>
            <span class="chat-item-q">${x.running ? html`<${Dot} token="info" pulse /> ` : null}${short(x.turns[0]?.q ?? '', 70)}</span>
            <span class="chat-item-meta mono small muted">${[chatStamp(x.last_ms ?? x.started_ms, s.now, lang), t.quickTurns(x.turns.length),
              t.quickModel[lastTurn?.model_asked] ?? lastTurn?.model_asked, !costKnown ? t.quickCostUnknown : cost ? costText(cost, lang) : null].filter(Boolean).join(' · ')}</span>
          </button>`
        }) : html`<p class="muted small chat-none">${t.quickNoChats}</p>`}
      </nav>
      <section class="panel chat-main" aria-label=${t.askTitle}>
        <div class="tabview-body quick-body" ref=${body} tabindex="-1" role="log" aria-label=${t.quickHistory}>
          ${q.config_error || !q.available ? html`<p><${StateLine} token="warning" word=${q.config_error ?? t.quickUnavailable} /></p>` : null}
          ${!conv ? html`<div class="quick-empty"><p class="muted">${t.quickIntro}</p></div>` : html`<${ChatThread} s=${s} conv=${conv} />`}
        </div>
        <${ChatFoot} key=${conv?.id ?? 'new'} s=${s} c=${c} conv=${conv} autofocus=${false} />
      </section>
    </div>
  </div>`
}

// ---------------------------------------------------------------- A2A agents

const REACH_TONE = { ok: 'ok', refused: 'bad', failed: 'bad', unreachable: 'warn', unknown: 'dim' }

/** One agent as a card: who it is from its card, what it may do, whether the last call went through */
function AgentCard({ p, on, c, s, held = 0 }) {
  const t = T()
  const card = p.card ?? {}
  const tone = REACH_TONE[p.reach] ?? 'dim'
  return html`<button type="button" class=${`agent-card rt-${tone}${on ? ' is-on' : ''}`} onClick=${() => c.pickAgent(p.id)}
    aria-current=${on ? 'true' : undefined}>
    <span class="agent-head"><span class=${`rdot rdot-${tone}`} aria-hidden="true"></span>
      <span class="agent-name" title=${card.name || p.id}>${card.name || p.id}</span></span>
    <span class="agent-id mono small muted">${p.id}</span>
    <span class="agent-sum">${p.summary || card.description}</span>
    <span class="agent-meta small">
      ${p.reach !== 'ok' ? html`<span class=${`agent-reach is-${tone}`}>${t.agentReach[p.reach] ?? p.reach}</span>` : null}
      ${held ? html`<span class="agent-reach is-warn">${t.agentHeld(held)}</span>` : null}
      ${p.last_ms ? html`<span class="muted">${t.agentLast(chatStamp(p.last_ms, s.now, language()))}</span>` : null}
    </span>
  </button>`
}

/** The agent's card as a profile: who and which version, where and how it is reached, what it takes
 *  and gives, its skills with their whole description and examples; an example fills the message box */
function AgentProfile({ p, onExample }) {
  const t = T()
  const card = p.card ?? {}
  const [skill, setSkill] = useState(null)
  const facts = [
    [t.agentFact.version, card.version], [t.agentFact.protocol, [card.binding, card.protocol && `A2A ${card.protocol}`].filter(Boolean).join(' · ')],
    [t.agentFact.provider, card.provider?.name], [t.agentFact.endpoint, card.endpoint],
    [t.agentFact.access, [p.needs_token ? t.agentToken : t.agentOpen, p.network ? t.agentNet[p.network] ?? p.network : null].filter(Boolean).join(' · ')],
    [t.agentFact.modes, card.input?.length ? `${card.input.join(', ')} → ${(card.output ?? []).join(', ')}` : null],
    [t.agentFact.gate, p.usage?.human_gate], [t.agentFact.allowed, p.usage?.allowed?.length ? p.usage.allowed.map(x => t.agentModes[x] ?? x).join(', ') : null],
    [t.agentFact.owner, p.owner],
  ].filter(([, v]) => v)
  return html`<div class="agent-profile row-in">
    <header class="agent-profile-head">
      <div><h3 class="agent-profile-name">${card.name || p.id}</h3>
        ${card.description ? html`<p class="agent-profile-desc">${card.description}</p>` : null}</div>
      <span class="btn-row">
        ${card.streaming ? html`<span class="chip">${t.agentStreaming}</span>` : null}
        ${card.docs ? html`<a class="btn btn-ghost btn-xs" href=${card.docs} target="_blank" rel="noopener noreferrer"><${Icon} name="external" size=${13} /><span class="btn-label">${t.agentDocs}</span></a>` : null}
      </span>
    </header>
    ${p.card_error ? html`<p><${StateLine} token="warning" word=${t.agentCardError(p.card_error)} /></p>` : null}
    ${p.last_error ? html`<p><${StateLine} token="danger" word=${t.agentFailed(p.last_error)} /></p>` : null}
    <dl class="agent-facts">${facts.map(([k, v]) => html`<div key=${k}><dt>${k}</dt><dd class=${k === t.agentFact.endpoint ? 'mono' : ''}>${v}</dd></div>`)}</dl>
    ${card.skills?.length ? html`<h4 class="label-caps">${t.agentSkills(card.skills.length)}</h4>
      <ul class="agent-skill-cards">${card.skills.map((k, i) => {
        const open = skill === i
        return html`<li key=${k.id || k.name} class=${`agent-skill${open ? ' is-open' : ''}`}>
          <button type="button" class="agent-skill-head" aria-expanded=${String(open)} onClick=${() => setSkill(open ? null : i)}>
            <strong>${k.name}</strong>${k.tags?.length ? html`<span class="agent-tags">${k.tags.map(x => html`<span key=${x} class="chip">${x}</span>`)}</span>` : null}
            <span class="agent-skill-chev" aria-hidden="true">${open ? '▾' : '▸'}</span></button>
          <p class=${`agent-skill-desc${open ? '' : ' is-clamped'}`}>${k.description}</p>
          ${open && k.examples?.length ? html`<div class="agent-examples"><span class="muted small">${t.agentExamples}</span>
            ${k.examples.map(x => html`<button type="button" key=${x} class="fchip" onClick=${() => onExample(x)}>${x}</button>`)}</div>` : null}
        </li>`
      })}</ul>` : null}
  </div>`
}

/** A conversation with one agent: question or task, sent only on a click; a held answer waits for the
 *  agent's owner, is looked at again every minute by the server, and on a click */
function AgentThread({ conv, peer, c, s }) {
  const t = T()
  return conv.turns.map((x, i) => {
    const last = i === conv.turns.length - 1
    return html`<div class="qturn row-in" key=${i} style=${{ '--i': 0 }}>
      <div class="qq">${x.mode === 'task' ? html`<span class="chip agent-mode">${t.agentModes.task}</span> ` : null}${x.q}</div>
      ${x.a && !x.waiting ? html`<div class="qa">${x.a}</div>` : null}
      ${x.error ? html`<p><${StateLine} token="danger" word=${x.error === 'interrupted' ? t.quickInterrupted : t.agentFailed(x.error)} /></p>` : null}
      ${last && conv.running ? html`<div class="qdoing"><${Thinking} label=${x.waiting ? t.agentLooking : t.agentSent} /></div>` : null}
      ${last && !conv.running && x.waiting ? html`<div class="agent-held">
        <${StateLine} token="warning" strong word=${t.agentWaiting} />
        ${x.a ? html`<p class="muted small">${x.a}</p>` : null}
        ${peer?.usage?.human_gate ? html`<p class="small">${t.agentWhereGate(peer.usage.human_gate)}</p>` : null}
        <p class="btn-row">
          <${Btn} size="xs" variant="secondary" busy=${!!s.ui.busy[`quick:${conv.id}`]} onClick=${() => c.agentPoll(conv.id)}>${t.agentPoll}<//></p>
      </div>` : null}
    </div>`
  })
}

function AgentsPage({ s, c }) {
  const t = T()
  const lang = language()
  const a = s.agents ?? {}
  const peers = a.peers ?? []
  const convs = a.convs ?? []
  const conv = convs.find(x => x.id === s.ui.agentConv) ?? null
  const peerId = conv?.peer ?? s.ui.agentPeer ?? peers[0]?.id
  const peer = peers.find(p => p.id === peerId) ?? peers[0]
  const mine = convs.filter(x => x.peer === peer?.id)
  const [text, setText] = useState('')
  const [profile, setProfile] = useState(false)
  const [forgetArmed, setForgetArmed] = useState(null)
  const body = useStickToEnd(conv, null)
  useEffect(() => { c.loadAgents() }, [])
  // a draft belongs to the agent it was written for: switching agents never carries it over
  useEffect(() => { setProfile(false); setText('') }, [peer?.id])
  const mode = s.ui.agentMode
  const send = async () => {
    const v = text.trim()
    if (!v || !peer || conv?.running) return
    if (await c.agentSend(peer.id, v, mode, conv?.id)) setText('')
  }
  const example = v => { setText(v); document.getElementById('agent-input')?.focus() }
  const showProfile = !conv || profile
  return html`<div class="col col-page agentspage">
    <header class="page-head"><h2 class="detail-title">${t.agentsTab}</h2>
      <span class="muted small">${t.agentsIntro}</span></header>
    <div class="agents-grid">
      <nav class="agents-list" aria-label=${t.agentsTab}>
        ${peers.map(p => html`<${AgentCard} key=${p.id} p=${p} on=${p.id === peer?.id} c=${c} s=${s}
          held=${convs.filter(x => x.peer === p.id && !x.running && x.turns.at(-1)?.waiting).length} />`)}
      </nav>
      <section class="panel chat-main" aria-label=${peer?.card?.name || peer?.id}>
        <header class="agent-convs">
          <button type="button" class=${`chip quick-conv${!conv ? ' is-on' : ''}`} onClick=${() => c.newAgentChat(peer.id)}>+ ${t.quickNew}</button>
          ${mine.slice(0, 8).map(x => html`<button type="button" key=${x.id} class=${`chip quick-conv${x.id === conv?.id ? ' is-on' : ''}`}
            onClick=${() => c.pickAgentConv(x.id)} title=${x.turns[0]?.q}>${x.running ? html`<${Dot} token="info" pulse /> `
              : x.turns.at(-1)?.waiting ? html`<${Dot} token="warning" /> ` : null}${short(x.turns[0]?.q ?? '', 36)}
            <span class="muted"> · ${chatStamp(x.last_ms ?? x.started_ms, s.now, lang)}</span></button>`)}
          ${conv ? html`<button type="button" class=${`chip quick-conv agent-profile-toggle${profile ? ' is-on' : ''}`} aria-expanded=${String(profile)}
            onClick=${() => setProfile(!profile)}>${t.agentProfile}</button>` : null}
          ${conv && !conv.running ? html`<button type="button" class=${`chip quick-conv agent-forget${forgetArmed === conv.id ? ' is-armed' : ''}`}
            title=${t.agentForgetHint} onBlur=${() => setForgetArmed(null)}
            onClick=${() => forgetArmed === conv.id ? c.agentForget(conv.id) : setForgetArmed(conv.id)}>${forgetArmed === conv.id ? t.agentForgetSure : t.agentForget}</button>` : null}
        </header>
        <div class="tabview-body quick-body" ref=${body} tabindex="-1" role="log" aria-label=${t.quickHistory}>
          ${peer && showProfile ? html`<${AgentProfile} key=${peer.id} p=${peer} onExample=${example} />` : null}
          ${conv ? html`<${AgentThread} conv=${conv} peer=${peer} c=${c} s=${s} />` : null}
        </div>
        <footer class="tabview-foot">
          <div class="btn-row agent-modes" role="radiogroup" aria-label=${t.agentModeLabel}>
            ${['question', 'task'].map(m => html`<button type="button" role="radio" key=${m} aria-checked=${String(mode === m)}
              class=${`fchip${mode === m ? ' is-on' : ''}`} onClick=${() => c.setAgentMode(m)}>${t.agentModes[m]}</button>`)}
            <span class="muted small">${t.agentModeHint[mode]}</span>
          </div>
          <${SendBox} id="agent-input" label=${t.agentSendLabel} value=${text} setValue=${setText} onSend=${send} max=${4000}
            placeholder=${t.agentPlaceholder(peer?.card?.name || peer?.id || '')} busy=${!!s.ui.busy[conv ? `quick:${conv.id}` : 'a2a_ask']}
            disabled=${!!conv?.running || !peer} sendLabel=${t.agentSendBtn} autofocus=${false} />
        </footer>
      </section>
    </div>
  </div>`
}

/** One agent tab large in the middle, like the Claude Code CLI: its terminal read every 1.5 s while
 *  the page is visible, the end in view unless you scrolled up, and below it the message box and the
 *  buttons the tab's state allows. Read only through the terminal driver (screen); sending goes through tab_send */
function TabView({ s, c }) {
  const t = T()
  const claude = s.ui.tabView === '@control'
  const ref = claude ? s.tabs?.control?.ref ?? null : s.ui.tabView
  const tab = (s.tabs?.tabs ?? []).find(x => x.ref === ref) ?? null
  const isControl = claude || !!tab?.is_control
  const relay = s.relay ?? {}
  const fb = s.ui.askFallback
  const [screen, setScreen] = useState(null)
  const [err, setErr] = useState(null)
  const [text, setText] = useState('')
  const body = useRef(null)
  const stick = useRef(true)
  const dialog = useFocusOnOpen(true)
  useEffect(() => {
    let alive = true
    let timer = null
    if (!ref) return undefined
    const pull = async () => {
      if (document.visibilityState === 'visible') {
        const res = await c.tabScreen(ref)
        if (!alive) return
        if (res.ok) { setScreen(res.data); setErr(null) } else setErr(res.error?.message || res.error?.code || '?')
      }
      if (alive) timer = setTimeout(pull, 1500)
    }
    pull()
    return () => { alive = false; clearTimeout(timer) }
  }, [ref])
  useLayoutEffect(() => {
    const el = body.current
    if (el && stick.current) el.scrollTop = el.scrollHeight
  }, [screen?.text])
  const onScroll = e => { const el = e.currentTarget; stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40 }
  const busy = !!s.ui.busy[ref]
  const state = tab?.state ?? screen?.state
  const send = async () => {
    const v = text.trim()
    if (!v) return
    // to the control session through the relay when it is on (it waits for the end of a turn), else typed in
    const r = isControl && relay.online ? await c.askControl('free', { text: v }, v)
      : ref ? await c.act('tab_send', { tab_ref: ref, text: v }) : false
    if (r) { setText(''); stick.current = true }
  }
  const lines = screenLines(screen?.text)
  return html`<div class="overlay overlay-center" onClick=${e => { if (e.target === e.currentTarget) c.closeTabView() }}>
    <div class="dialog tabview" role="dialog" aria-modal="true" aria-labelledby="tabview-title" ref=${dialog}>
      <header class="tabview-head">
        ${state ? html`<${StateLine} token=${stateToken(state)} strong=${state === 'needs-you'} word=${t.state[state] ?? state} />` : null}
        <h2 class="sec-title tabview-title" id="tabview-title">${isControl ? t.controlSession : tab?.name ?? screen?.name ?? ref}</h2>
        <span class="muted small">${tab?.workspace ?? screen?.workspace ?? ''}</span>
        <span class="tabview-live muted small" aria-live="off">${err ? html`<${StateLine} token="danger" word=${t.tabViewFailed(err)} />`
          : screen ? t.tabViewLive : t.loading}</span>
        ${ref && canTab(s, 'focus') ? html`<${Btn} size="xs" variant="ghost" busy=${busy} onClick=${() => c.act('tab_jump', { tab_ref: ref })}>${t.btnToTab}<//>` : null}
        <${Btn} variant="ghost" size="xs" icon="close" label=${t.close} onClick=${c.closeTabView} />
      </header>
      ${claude && !ref ? html`<div class="tabview-off">
        <${StateLine} token="warning" strong word=${t.relayReason[relay.reason] ?? t.relay.offline} />
        <p class="muted small">${t.claudeNoSession}</p>
        <div class="btn-row"><${StartControl} s=${s} c=${c} size="sm" /></div>
      </div>` : null}
      ${fb ? html`<div class="callout ask-fallback" role="region" aria-label=${t.askOfflineTitle}>
        <strong>${t.askOfflineTitle}</strong>
        <div class="btn-row">
          <${Btn} size="xs" icon="copy" onClick=${() => c.copy(fb.text || fb.record?.preview || '')}>${t.askCopy}<//>
          ${fb.fallback?.available && fb.record ? html`<${Btn} size="xs" variant="primary"
            onClick=${() => c.act('ask_via_tab', { relay_id: fb.record.id })}>${t.askViaTab}<//>` : null}
          <${Btn} size="xs" variant="ghost" icon="close" label=${t.close} onClick=${() => c.setAskFallback(null)} />
        </div>
      </div>` : null}
      ${!claude || ref ? html`<div class="tabview-body" ref=${body} onScroll=${onScroll} tabindex="0" role="log" aria-label=${t.tabViewLog}>
        ${lines.length ? lines.map((l, i) => html`<div key=${i} class=${`tl tl-${l.kind}`}>${l.text || ' '}</div>`)
          : html`<p class="muted">${screen ? t.tabViewEmpty : t.loading}</p>`}
      </div>` : html`<div></div>`}
      <footer class="tabview-foot">
        ${state === 'needs-you' && canTab(s, 'key') ? html`<div class="btn-row">
          <${Btn} size="xs" variant="primary" busy=${busy} onClick=${() => c.act('tab_yes', { tab_ref: ref })}>${t.btnYes}<//>
          <${Btn} size="xs" variant="secondary" busy=${busy} onClick=${() => c.act('tab_no', { tab_ref: ref })}>${t.btnNo}<//>
        </div>` : null}
        ${state === 'waiting' && tab && !tab.filed_by && !tab.is_control ? html`<div class="btn-row">
          <${Btn} size="xs" variant="secondary" busy=${busy} onClick=${() => c.act('tab_go_on', { tab_ref: ref })}>${t.btnGoOn}<//></div>` : null}
        <${SendBox} id="tabview-input" label=${t.msgPlaceholder} value=${text} setValue=${setText} onSend=${send} busy=${busy}
          max=${isControl ? ASK_MAX : TAB_MSG_MAX} placeholder=${isControl ? t.askPlaceholder : t.tabViewPlaceholder} />
      </footer>
    </div>
  </div>`
}

/** A session tab as a card. In the agent tab column it is slim: state, name and its one next step; a
 *  click on more opens the preview and every control */
function TabCard({ tab, s, c, byKey, slim = false }) {
  const t = T()
  const [open, setOpen] = useState(false)
  const full = !slim || open
  const rowKey = tab.slug ? `task:${tab.slug}` : null
  const hasRow = rowKey && byKey.has(rowKey)
  const age = duration(s.now - (tab.since_ms || s.now))
  const ageText = tab.long === 'waiting' ? t.waitingFor(age) : tab.long === 'running' ? t.runningFor(age) : t.sinceFor(age)
  const shell = tab.state === 'shell'
  return html`<article class=${`tabcard st-${tab.state}${shell ? ' is-shell' : ''}${tab.is_control ? ' is-control' : ''}${full ? '' : ' is-slim'}`}>
    <header class="tabcard-head">
      ${tab.is_control
        ? html`<button type="button" class="btn-link" onClick=${c.openClaude}><${StateLine} token="on-surface-muted" word=${t.controlSession} /></button>`
        : html`<${StateLine} token=${stateToken(tab.state)} strong=${tab.state === 'needs-you'} word=${t.state[tab.state] ?? tab.state} />`}
      <span class="tabcard-age mono">${ageText}</span>
      ${tab.long ? html`<span class="chip chip-warn-outline">${t.tabLong}</span>` : null}
    </header>
    <h3 class="tabcard-name">${hasRow
      ? html`<button type="button" class="btn-link" title=${t.showTab(tab.name)} onClick=${() => c.select(rowKey)}>${tab.name}</button>`
      : html`<button type="button" class="btn-link" title=${t.btnTabView} onClick=${() => c.openTabView(tab.ref)}>${tab.name}</button>`}</h3>
    ${full && previewText(tab.last) ? html`<p class="tab-last clamp2" title=${tab.last}>${previewText(tab.last)}</p>` : null}
    ${full && (tab.slug || tab.team || tab.role || tab.filed_by) ? html`<div class="chips">
      ${tab.slug ? html`<span class="chip"><span class="muted">${t.tabChips.task}</span> ${tab.slug}</span>` : null}
      ${tab.team ? html`<span class="chip"><span class="muted">${t.tabChips.team}</span> ${tab.team}</span>` : null}
      ${tab.role ? html`<span class="chip"><span class="muted">${t.tabChips.role}</span> ${tab.role}</span>` : null}
      ${tab.filed_by ? html`<${Chip} token="success">${t.resultFiled}<//>` : null}
    </div>` : null}
    ${full ? html`<${TabControls} tab=${tab} s=${s} c=${c} />` : html`<div class="btn-row"><${TabControls} tab=${tab} s=${s} c=${c} slim /></div>`}
    ${slim ? html`<button type="button" class="btn-link tabcard-more" aria-expanded=${String(open)}
      onClick=${() => setOpen(!open)}>${open ? t.cardLess : t.cardMore}</button>` : null}
  </article>`
}

function SnapshotPanel({ s, c }) {
  const t = T()
  if (!s.cmux?.ok) return null
  return html`<section class="snap" aria-labelledby="snap-title">
    <h3 class="label-caps" id="snap-title">${t.snapshotTitle}</h3>
    <div class="btn-row">
      <${Btn} size="xs" busy=${!!s.ui.busy.snapshot} onClick=${() => c.snapshot(false)}>${t.btnSave}<//>
      <${Btn} size="xs" variant="ghost" busy=${!!s.ui.busy.snapshot_list} onClick=${() => c.snapshot(true)}>${t.btnList}<//>
    </div>
    ${s.ui.snapshotText ? html`<p class="pre small">${s.ui.snapshotText}</p>` : null}
  </section>`
}

function TabsColumn({ s, c, byKey, inDrawer }) {
  const t = T()
  const tabs = s.tabs?.tabs ?? []
  const control = tabs.find(x => x.is_control)
  const groups = groupTabs(tabs)
  const waiting = tabs.filter(x => x.waiting && !x.is_control).length
  const working = tabs.filter(x => x.state === 'working' && !x.is_control).length
  return html`<div class=${`col col-tabs${inDrawer ? ' in-drawer' : ''}`} id="tabs-column" tabindex="-1" aria-labelledby="tabs-title">
    <div class="panel panel-pad tabs-panel">
      <header class="tabs-head">
        <h2 class="sec-title" id="tabs-title">${t.tabsTitle} <span class="sec-count mono">${tabs.filter(x => !x.is_control).length}</span></h2>
        <span class="muted small">${waiting ? t.waitCount(waiting) : ''}${waiting && working ? ' · ' : ''}${working ? t.workingCount(working) : ''}</span>
        ${s.tabs?.at_ms ? html`<span class="muted small mono" title=${t.asOf}>${formatClock(s.tabs.at_ms, language())}</span>` : null}
        ${inDrawer ? html`<${Btn} variant="ghost" size="xs" icon="close" label=${t.close} onClick=${() => c.setDrawer(null)} />` : null}
      </header>
      ${!s.cmux?.ok ? html`<p class="banner"><${StateLine} token="warning" word=${t.cmuxMissing(s.cmux?.error ?? '')} /></p>` : null}
      ${s.tabs?.error ? html`<p class="banner"><${StateLine} token="danger" strong word=${t.tabsStale(s.tabs.error.since, s.tabs.error.message)} /></p>` : null}
      ${control ? html`<${TabCard} tab=${control} s=${s} c=${c} byKey=${byKey} slim />` : null}
      ${groups.length ? groups.map(g => html`<section class="tabgroup" key=${g.workspace}>
        <h3 class="mono-label">${g.workspace || '·'}</h3>
        <div class="tabgrid">${g.tabs.map(tab => html`<${TabCard} key=${tab.ref} tab=${tab} s=${s} c=${c} byKey=${byKey} slim />`)}</div>
      </section>`) : html`<${Empty}>${t.tabsEmpty}<//>`}
      <${SnapshotPanel} s=${s} c=${c} />
    </div>
  </div>`
}

// ---------------------------------------------------------------- pages

/** A row's gauge: the fill grows to its value, a thin mark shows how much of the time window has passed,
 *  and when the value runs ahead of the time it says so in words */
function MeterBar({ meter, scale, tone }) {
  const t = T()
  const lang = language()
  const v = meterView(meter, scale)
  const frac = useTween(v.frac, { start: 0 })
  const shown = useTween(meter.value, { start: 0 })
  const fill = tone === 'bad' ? 'danger' : tone === 'warn' ? 'warning' : v.relative ? 'secondary' : 'info'
  return html`<div class="meter">
    <span class="meter-track" aria-hidden="true">
      <span class=${`meter-fill tk-${fill}`} style=${{ transform: `scaleX(${Math.max(0, frac).toFixed(4)})` }}></span>
      ${v.pace != null ? html`<span class="meter-pace" style=${{ '--p': v.pace.toFixed(4) }}></span>` : null}
    </span>
    <span class="meter-text num">${meterText(meter, shown, lang)}</span>
    ${v.pace != null ? html`<span class="muted small">${t.meterPace(Math.round(v.pace * 100))}</span>` : null}
    ${v.ahead ? html`<${StateLine} token="warning" word=${t.meterAhead} />` : null}
  </div>`
}

/** A half-circle gauge (DESIGN.md tokens): the source's ranges as an outer ring, the value as the inner
 *  arc, a needle where the time window stands. The number and the words below carry the state, the color
 *  only repeats it */
function Gauge({ meter, label }) {
  const lang = language()
  const f = useTween(Math.min(1, meter.value / meter.max), { start: 0 })
  const shown = useTween(meter.value, { start: 0 })
  const bands = gaugeBands(meter)
  const token = meter.bad != null && meter.value >= meter.bad ? 'danger'
    : meter.warn != null && meter.value >= meter.warn ? 'warning' : 'secondary'
  const mark = (x, r0, r1) => { const [a, b] = gaugePoint(x, r0); const [c2, d] = gaugePoint(x, r1); return { x1: a, y1: b, x2: c2, y2: d } }
  const tick = (x, text) => {
    const [tx, ty] = gaugePoint(x, 104)
    const end = x <= 0.001 || x >= 0.999
    return html`<text x=${(end ? (x < 0.5 ? 10 : 190) : tx).toFixed(1)} y=${(end ? 116 : Math.min(108, ty + 3)).toFixed(1)} class="g-label"
      text-anchor=${end ? 'middle' : x < 0.4 ? 'end' : x > 0.6 ? 'start' : 'middle'}>${text}</text>`
  }
  const unit = meter.unit === '%' ? ' %' : ''
  return html`<svg class="gauge" viewBox="-26 0 252 120" role="img" aria-label=${label}>
    ${bands.length ? bands.map(b => html`<path key=${b.token} d=${gaugeArc(b.from, b.to, 90)} class=${`g-band tk-${b.token}`} />`)
      : html`<path d=${gaugeArc(0, 1, 90)} class="g-band g-band-none" />`}
    <path d=${gaugeArc(0, 1, 72)} class="g-track" />
    ${f > 0.002 ? html`<path d=${gaugeArc(0, f, 72)} class=${`g-value tk-${token}`} />` : null}
    ${meter.elapsed != null ? html`<line ...${mark(meter.elapsed, 56, 96)} class="g-pace" />` : null}
    ${tick(0, `0${unit}`)}
    ${meter.warn != null ? tick(meter.warn / meter.max, `${Math.round(meter.warn)}${unit}`) : null}
    ${meter.bad != null ? tick(meter.bad / meter.max, `${Math.round(meter.bad)}${unit}`) : null}
    ${tick(1, `${Math.round(meter.max)}${unit}`)}
    <text x="100" y="96" text-anchor="middle" class="g-num">${meter.unit
      ? meterText(meter, shown, lang).replace(' %', '\u202f%') : String(Math.round(shown))}</text>
  </svg>`
}

/** A section of gauges as tiles: title, the gauge, when it resets, how much time has passed */
function GaugeTile({ it, page, section, c }) {
  const t = T()
  const v = meterView(it.meter, 0)
  const title = it.title.replace(/:\s*[\d.,]+\s*%?\s*$/, '')
  return html`<li class="gtile card-opens" tabindex="0" onClick=${e => { if (rowClickOpens(e)) c.openInfo(it, page, section) }}
    onKeyDown=${e => { if (e.key === 'Enter' && e.target === e.currentTarget) { e.preventDefault(); c.openInfo(it, page, section) } }}>
    <h3 class="gtile-title">${it.tone ? html`<${StateLine} token=${toneToken(it.tone)} strong=${it.tone === 'bad'} word=${title} />` : title}</h3>
    <${Gauge} meter=${it.meter} label=${it.title} />
    <div class="gtile-foot small">
      ${it.when ? html`<span class="muted">${t.gaugeResets(it.when)}</span>` : null}
      ${v.pace != null ? html`<span class="muted">${t.meterPace(Math.round(v.pace * 100))}</span>` : null}
      ${v.pace != null ? html`<${StateLine} token=${v.ahead ? 'warning' : 'success'} word=${v.ahead ? t.meterAhead : t.meterOnPace} />` : null}
    </div>
    ${it.ask ? html`<div class="btn-row"><${Btn} size="xs" variant="ghost" onClick=${() => c.ask('info', { page, section, index: it.index })}>${t.btnAsk}<//></div>` : null}
  </li>`
}

/** A command row's own steps (an application: followed up, turned down, ...) in two clicks; each is
 *  run by its section's command and can be taken back from the toast or the history */
function RowSteps({ it, page, section, s, c }) {
  const t = T()
  const [open, setOpen] = useState(false)
  const box = usePopover(open, setOpen)
  const busy = !!s.ui.busy.row_action
  const pick = action => { setOpen(false); c.act('row_action', { page, section, index: it.index, action }) }
  return html`<span class="settle" ref=${box}>
    <${Btn} size="xs" variant="ghost" busy=${busy} pressed=${open} title=${t.rowStepsTitle} onClick=${() => setOpen(!open)}>${t.rowSteps} ▾<//>
    ${open ? html`<span class="settle-menu" role="menu">${it.actions.map(a => html`<button type="button" role="menuitem" key=${a.id}
      class="settle-item" onClick=${() => pick(a.id)}><span>${a.label}</span></button>`)}</span>` : null}
  </span>`
}

function InfoRow({ it, page, section, s, c, byKey, scale = 0, lead = null }) {
  const t = T()
  const tri = s.triage?.items?.[triageKey(it)] ?? null
  const [open, setOpen] = useState(false)
  const tone = it.tone ?? null
  // an inbox item or task opens its drawer: a click anywhere on the row but its controls, or Enter on the row
  const itemKey = (section === 'tasks' || section === 'inbox' || it.inbox) ? triageKey(it) : null
  // an inbox item or task opens its own drawer, every other row the general detail
  const openIt = () => (itemKey ? c.openItem(itemKey, it, { page, section }) : c.openInfo(it, page, section))
  // the detail line in words, without the priority the chip beside the title already shows
  const detail = detailText(it.detail, t).split(' · ').filter(p => p !== it.priority).join(' · ')
  return html`<tr class=${`${tone ? `tone-${tone}` : ''} row-opens`} tabindex="0"
    onClick=${e => { if (rowClickOpens(e)) openIt() }}
    onKeyDown=${e => { if (e.key === 'Enter' && e.target === e.currentTarget) { e.preventDefault(); openIt() } }}>
    <td class="c-when mono">${it.when}</td>
    <td class=${`c-item${tri ? ' has-gist' : ''}`}>
      ${tri ? html`<${TriageGist} tri=${tri} keyRow=${actionRow(it, byKey)} c=${c} s=${s} />` : null}
      <div class="info-title">
        ${lead ? html`${lead.rank ? html`<span class="jrank mono" title=${lead.judge ? t.workOrder.judge(lead.judge) : undefined}>${lead.rank}</span>` : null}<span class="chip jlabel">${lead.label}</span>` : null}
        ${itemKey ? html`<button type="button" class="btn-link info-open" title=${t.item.open}
            aria-haspopup="dialog" onClick=${openIt}>
            ${tone ? html`<${StateLine} token=${toneToken(tone)} strong=${tone === 'bad'} word=${it.title} />` : it.title}</button>`
          : it.task && byKey.has(`task:${it.task}`) ? html`<button type="button" class="btn-link info-open" title=${t.openDetail}
            aria-haspopup="true" onClick=${e => c.peek(`task:${it.task}`, e.currentTarget)}>
            ${tone ? html`<${StateLine} token=${toneToken(tone)} strong=${tone === 'bad'} word=${it.title} />` : it.title}</button>`
          : tone ? html`<${StateLine} token=${toneToken(tone)} strong=${tone === 'bad'} word=${it.title} />` : html`<span>${it.title}</span>`}
        <${MarkChip} mark=${it.mark} /><${PrioChip} priority=${it.priority} />
        ${it.task ? html`<${VerdictChip} review=${byKey.get(`task:${it.task}`)?.review} />` : null}
        ${it.state ? html`<span class="chip">${t.taskState[it.state] ?? it.state}</span>` : null}
        ${it.tab ? html`<${Chip} token=${stateToken(it.tab.state)}>${t.state[it.tab.state] ?? it.tab.state}<//>` : null}
        ${it.starting ? html`<${Chip} token="info">${t.startingTab}<//>` : null}
        <${ReturnChip} s=${s} rowKey=${[itemKey, it.task ? `task:${it.task}` : null]} />
      </div>
      ${detail ? html`<div class="info-detail muted">${detail}</div>` : null}
      ${it.meter ? html`<${MeterBar} meter=${it.meter} scale=${scale} tone=${tone} />` : null}
      ${open && (it.lines ?? []).length ? html`<${Lines} lines=${it.lines} />` : null}
    </td>
    <td class="c-acts"><span class="btn-row">
      ${it.link?.kind === 'web' ? html`<a class="btn btn-ghost btn-xs" href=${it.link.href} target="_blank" rel="noopener noreferrer">
        <${Icon} name="external" size=${14} /><span class="btn-label">${t.openLink}</span></a>` : null}
      ${it.link?.kind === 'file' ? html`<${Btn} size="xs" variant="ghost" icon="copy" cls="act-quiet" title=${it.link.path} onClick=${() => c.copy(it.link.path)}>${t.copyPath}<//>` : null}
      <${PageItemActions} it=${it} s=${s} c=${c} />
      ${it.ask ? html`<${Btn} size="xs" variant="ghost" cls="act-quiet" onClick=${() => c.ask('info', { page, section, index: it.index })}>${t.btnAsk}<//>` : null}
      ${it.task ? html`<${Btn} size="xs" variant="secondary" busy=${!!s.ui.busy[`task:${it.task}`]}
        title=${it.tab && it.tab.live ? undefined : t.btnStartAgentTitle} onClick=${() => (it.tab && it.tab.live ? c.act('tab_jump', { tab_ref: it.tab.ref }) : c.act('start_agent', { keys: [`task:${it.task}`] }))}>
        ${it.tab && it.tab.live ? t.btnToTab : t.btnOpenTab}<//>`
      // an inbox item of its own (a finding, a decision) gets an agent that goes at it at once
      : it.inbox && !(it.lines ?? []).some(l => l.kind === 'look') ? html`<${Btn} size="xs" variant="secondary" busy=${!!s.ui.busy[`inbox:${it.inbox}`]}
        title=${it.tab && it.tab.live ? undefined : t.btnStartAgentTitle} onClick=${() => (it.tab && it.tab.live ? c.act('tab_jump', { tab_ref: it.tab.ref }) : c.act('start_agent', { keys: [`inbox:${it.inbox}`] }))}>
        ${it.tab && it.tab.live ? t.btnToTab : t.btnOpenTab}<//>` : null}
      ${(it.lines ?? []).length ? html`<${Btn} size="xs" variant="ghost" cls=${open ? '' : 'act-quiet'} pressed=${open} onClick=${() => setOpen(!open)}>${t.btnLines}<//>` : null}
      ${it.actions?.length && it.row_id ? html`<${RowSteps} it=${it} page=${page} section=${section} s=${s} c=${c} />` : null}
      ${actionRow(it, byKey) && (it.inbox || section === 'tasks' || byKey.has(`task:${it.task}`)) ? html`<${SettleMenu} rows=${[actionRow(it, byKey)]} s=${s} c=${c} />` : null}
    </span></td>
  </tr>`
}

// ---------------------------------------------------------------- drawn sections: tiles and mosaic

/** Symbols for drawn rows: a source names a family (a device type, a cloud service, a provider), the
 *  page draws a plain line icon; anything unknown is a box */
const RES_ICONS = {
  laptop: 'M4 6h16v10H4zM2 19h20',
  monitor: 'M3 4h18v12H3zM8 20h8M12 16v4',
  server: 'M4 4h16v6H4zM4 14h16v6H4zM8 7h.01M8 17h.01',
  router: 'M3 14h18v6H3zM7 17h.01M11 17h.01M8 14 5 8M16 14l3-6',
  phone: 'M7 2h10v20H7zM11 18h2',
  robot: 'M6 8h12v10H6zM12 4v4M9 12h.01M15 12h.01M9 15h6',
  printer: 'M6 3h12v6H6zM4 9h16v8H4zM8 14h8v7H8z',
  usb: 'M9 2h6v8H9zM7 10h10v12H7z',
  gear: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1-1.9 1.9-.1-.1a1.6 1.6 0 0 0-2.7 1.1V20h-2.6v-.2a1.6 1.6 0 0 0-2.7-1.1l-.1.1-1.9-1.9.1-.1A1.6 1.6 0 0 0 4.6 15H4v-2.6h.2a1.6 1.6 0 0 0 1.1-2.7l-.1-.1 1.9-1.9.1.1a1.6 1.6 0 0 0 2.7-1.1V4h2.6v.2a1.6 1.6 0 0 0 2.7 1.1l.1-.1 1.9 1.9-.1.1a1.6 1.6 0 0 0 1.1 2.7h.2V15z',
  bolt: 'M13 2 4 14h7l-1 8 9-12h-7l1-8z',
  globe: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18',
  page: 'M6 2h9l5 5v15H6zM14 2v6h6',
  tunnel: 'M3 20v-8a9 9 0 0 1 18 0v8M7 20v-8a5 5 0 0 1 10 0v8',
  cloud: 'M7 18h10a4 4 0 0 0 .5-8A6 6 0 0 0 6 9a4.5 4.5 0 0 0 1 9z',
  mail: 'M3 5h18v14H3zM3 6l9 7 9-7',
  box: 'M4 7l8-4 8 4v10l-8 4-8-4zM4 7l8 4 8-4M12 11v10',
}
const ICON_OF = {
  macos: 'laptop', windows: 'monitor', linux: 'server', saas: 'cloud', router: 'router', 'kvm-over-ip': 'monitor',
  'smart-device': 'phone', robot: 'robot', '3d-printer': 'printer', 'usb-toolkit': 'usb', worker: 'gear',
  'function app': 'bolt', 'web app': 'globe', zone: 'globe', pages: 'page', tunnel: 'tunnel', account: 'cloud',
  azure: 'cloud', cloudflare: 'cloud', aws: 'cloud', gcp: 'cloud', m365: 'cloud', tailscale: 'cloud', ionos: 'globe',
  google: 'mail', icloud: 'mail', microsoft365: 'mail', exchange: 'mail', imap: 'mail',
}
function ResIcon({ name, size = 18 }) {
  const d = RES_ICONS[ICON_OF[name] ?? name] ?? RES_ICONS.box
  return html`<svg class="res-icon" width=${size} height=${size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
    stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d=${d} /></svg>`
}

/** A small menu that closes on Escape or a click outside it; returns the ref for its box */
function usePopover(open, setOpen) {
  const box = useRef(null)
  useEffect(() => {
    if (!open) return undefined
    const away = e => { if (box.current && !box.current.contains(e.target)) setOpen(false) }
    const esc = e => { if (e.key === 'Escape') { e.stopPropagation(); setOpen(false) } }
    document.addEventListener('pointerdown', away)
    document.addEventListener('keydown', esc, true)
    return () => { document.removeEventListener('pointerdown', away); document.removeEventListener('keydown', esc, true) }
  }, [open])
  return box
}

/** Search, state, group and tags: what a drawn section shows; the counts say what each choice holds */
function useRowFilter(items, initTags = {}) {
  const [q, setQ] = useState('')
  const [tone, setTone] = useState('all')
  const [group, setGroup] = useState(null)
  const [tags, setTags] = useState(initTags)
  const filter = { q, tone, group, tags }
  const counts = Object.fromEntries(TONE_FILTERS.map(([k]) => [k, filterRows(items, { ...filter, tone: k }).length]))
  return {
    q, setQ, tone, setTone, group, setGroup, tags, counts,
    shown: filterRows(items, filter),
    groups: [...new Set(items.map(it => it.group).filter(Boolean))],
    facets: tagFacets(items, filter),
    setTag: (k, v) => setTags(x => ({ ...x, [k]: x[k] === v ? null : v })),
    active: !!(q.trim() || tone !== 'all' || group || Object.values(tags).some(Boolean)),
    reset: () => { setQ(''); setTone('all'); setGroup(null); setTags({}) },
  }
}

function FilterBar({ f, label, groups = true }) {
  const t = T()
  return html`<div class="fbar" role="search" aria-label=${label}>
    <input class="input fbar-q" type="search" placeholder=${t.filterSearch} value=${f.q} onInput=${e => f.setQ(e.currentTarget.value)}
      aria-label=${t.filterSearch} />
    <span class="fbar-chips" role="group" aria-label=${t.filterState}>${TONE_FILTERS.map(([k]) => html`<button type="button" key=${k}
      class=${`fchip${f.tone === k ? ' is-on' : ''}`} aria-pressed=${String(f.tone === k)} disabled=${k !== 'all' && !f.counts[k]}
      onClick=${() => f.setTone(k)}>${k !== 'all' ? html`<span class=${`fdot fdot-${FILTER_TONE[k]}`} aria-hidden="true"></span>` : null}${t.filterTone[k]} <span class="mono">${f.counts[k]}</span></button>`)}</span>
    ${groups && f.groups.length > 1 && f.groups.length <= 14 ? html`<span class="fbar-chips" role="group" aria-label=${t.filterGroup}>
      ${f.groups.map(g => html`<button type="button" key=${g} class=${`fchip fchip-g${f.group === g ? ' is-on' : ''}`} aria-pressed=${String(f.group === g)}
        onClick=${() => f.setGroup(f.group === g ? null : g)}>${g}</button>`)}</span>` : null}
    ${f.facets.map(x => html`<span class="fbar-chips fbar-facet" role="group" aria-label=${x.key} key=${x.key}>
      <span class="fbar-key">${x.key}</span>
      ${x.values.map(([v, n]) => html`<button type="button" key=${v} class=${`fchip fchip-g${f.tags[x.key] === v ? ' is-on' : ''}`}
        aria-pressed=${String(f.tags[x.key] === v)} disabled=${!n && f.tags[x.key] !== v} onClick=${() => f.setTag(x.key, v)}>${v} <span class="mono">${n}</span></button>`)}
    </span>`)}
    ${f.active ? html`<${Btn} size="xs" variant="ghost" icon="close" onClick=${f.reset}>${t.filterReset}<//>` : null}
  </div>`
}

const ACCOUNT_STATUSES = [['active', 'success'], ['paused', 'warning'], ['disabled', 'on-surface-muted']]

/** An account's state in two clicks: active, paused or switched off, written into its file */
function StatusMenu({ it, page, section, c }) {
  const t = T()
  const [open, setOpen] = useState(false)
  const box = usePopover(open, setOpen)
  const now = it.account.status
  const pick = status => { setOpen(false); if (status !== now) c.act('account_status', { page, section, index: it.index, status }) }
  return html`<span class="settle" ref=${box}>
    <${Btn} size="xs" variant="ghost" pressed=${open} onClick=${() => setOpen(!open)}>${t.acctStatus[now] ?? now} ▾<//>
    ${open ? html`<span class="settle-menu is-left" role="menu">
      ${ACCOUNT_STATUSES.map(([k, token]) => html`<button type="button" role="menuitemradio" aria-checked=${String(k === now)} key=${k}
        class="settle-item" onClick=${() => pick(k)}><${Dot} token=${token} /><span>${t.acctStatus[k]}</span>
        ${k === now ? html`<span class="muted small">${t.acctNow}</span>` : null}</button>`)}
      <span class="settle-hint muted small">${t.acctHint}</span>
    </span>` : null}
  </span>`
}

/** One drawn row: symbol, name, state as dot and word, what it is, the way to it */
function ResTile({ it, page, section, c, i, services }) {
  const t = T()
  const tone = it.tone ?? 'ok'
  return html`<article class=${`rtile rt-${tone} row-in card-opens`} style=${{ '--i': Math.min(i, 14) }} tabindex="0"
    onClick=${e => { if (rowClickOpens(e)) c.openInfo(it, page, section) }}
    onKeyDown=${e => { if (e.key === 'Enter' && e.target === e.currentTarget) { e.preventDefault(); c.openInfo(it, page, section) } }}>
    <header class="rtile-head">
      <span class="rtile-icon"><${ResIcon} name=${it.icon} /></span>
      <h4 class="rtile-title" title=${it.title}>${it.title}</h4>
      <span class=${`rdot rdot-${tone}`} aria-hidden="true"></span>
    </header>
    ${it.detail ? html`<p class="rtile-detail">${it.detail}</p>` : null}
    ${it.meter ? html`<${MeterBar} meter=${it.meter} scale=${0} tone=${it.tone} />` : null}
    <footer class="rtile-foot">
      ${services ? html`<${Btn} size="xs" variant="secondary" onClick=${services.open}>${t.resServices(services.n)}<//>` : null}
      ${it.account?.status ? html`<${StatusMenu} it=${it} page=${page} section=${section} c=${c} />` : null}
      ${it.link?.kind === 'web' ? html`<a class="btn btn-ghost btn-xs" href=${it.link.href} target="_blank" rel="noopener noreferrer">
        <${Icon} name="external" size=${13} /><span class="btn-label">${t.openLink}</span></a>` : null}
      ${it.ask ? html`<${Btn} size="xs" variant="ghost" onClick=${() => c.ask('info', { page, section, index: it.index })}>${t.btnAsk}<//>` : null}
    </footer>
  </article>`
}

/** Everything one account runs, as a filterable list: by kind, state, group, region, and by name */
function ResDrawer({ d, page, c, onClose }) {
  const t = T()
  const f = useRowFilter(d.rows, d.tags ?? {})
  const dialog = useFocusOnOpen(true)
  useEffect(() => {
    const esc = e => { if (e.key === 'Escape') { e.stopPropagation(); onClose() } }
    document.addEventListener('keydown', esc, true)
    return () => document.removeEventListener('keydown', esc, true)
  }, [])
  const keys = [...new Set(d.rows.flatMap(it => Object.keys(it.tags ?? {})))]
  const head = d.head
  return html`<div class="overlay overlay-center" onClick=${e => { if (e.target === e.currentTarget) onClose() }}>
    <div class="dialog rdrawer" role="dialog" aria-modal="true" aria-labelledby="rdrawer-title" ref=${dialog}>
      <header class=${`rdrawer-head rt-${head?.tone ?? 'ok'}`}>
        <span class="rtile-icon"><${ResIcon} name=${head?.icon ?? 'account'} size=${22} /></span>
        <div class="rgroup-main"><h2 class="sec-title rdrawer-title" id="rdrawer-title">${d.title}</h2>
          ${head?.detail ? html`<p class="rtile-detail">${head.detail}</p>` : null}</div>
        <div class="btn-row">
          ${head?.link?.kind === 'web' ? html`<a class="btn btn-ghost btn-xs" href=${head.link.href} target="_blank" rel="noopener noreferrer">
            <${Icon} name="external" size=${13} /><span class="btn-label">${t.openLink}</span></a>` : null}
          ${head ? html`<${Btn} size="xs" variant="ghost" onClick=${() => c.ask('info', { page, section: d.section, index: head.index })}>${t.btnAsk}<//>` : null}
          <${Btn} variant="ghost" size="xs" icon="close" label=${t.close} onClick=${onClose} />
        </div>
      </header>
      <div class="rdrawer-filter"><${FilterBar} f=${f} label=${t.filterLabel} groups=${false} /></div>
      <div class="rdrawer-body" tabindex="0" role="region" aria-label=${d.title}>
        ${f.shown.length ? html`<table class="tbl rdrawer-tbl">
          <thead><tr><th scope="col">${t.resName}</th>${keys.map(k => html`<th scope="col" key=${k}>${k}</th>`)}<th scope="col" class="c-acts"></th></tr></thead>
          <tbody>${f.shown.map(it => html`<tr key=${it.index}>
            <td><span class="rdrawer-name"><span class=${`rdot rdot-${it.tone ?? 'ok'}`} aria-hidden="true"></span>
              <${ResIcon} name=${it.icon} size=${14} /><span>${it.title}</span></span></td>
            ${keys.map(k => html`<td key=${k} class=${it.tags?.[k] && f.tags[k] !== it.tags[k] ? 'rdrawer-tag' : 'muted'}>
              ${it.tags?.[k] ? html`<button type="button" class="linkish" onClick=${() => f.setTag(k, it.tags[k])}>${it.tags[k]}</button>` : ''}</td>`)}
            <td class="c-acts"><span class="btn-row">
              ${it.link?.kind === 'web' ? html`<a class="btn btn-ghost btn-xs" href=${it.link.href} target="_blank" rel="noopener noreferrer"
                aria-label=${`${t.openLink}: ${it.title}`}><${Icon} name="external" size=${13} /></a>` : null}
              <${Btn} size="xs" variant="ghost" onClick=${() => c.ask('info', { page, section: d.section, index: it.index })}>${t.btnAsk}<//>
            </span></td></tr>`)}</tbody></table>` : html`<${Empty}>${t.filterNone}<//>`}
      </div>
      <footer class="rdrawer-foot muted small">${t.resShown(f.shown.length, d.rows.length)}</footer>
    </div>
  </div>`
}

/** The rows of the account a head row stands for, in any section of the page */
function accountRows(sections, id) {
  for (const sec of sections ?? []) {
    const items = sec.items ?? []
    const head = items.find(x => x.icon === 'account' && x.account?.id === id)
    if (head) return { title: head.title, head, section: sec.id, rows: items.filter(x => x !== head && x.group === head.group) }
  }
  return null
}

const MANY = 6     // a group with more rows than this shows its head, its problems, and the rest in the list

/** Cards in groups: a group's own head row (an account with its counts) leads it, the rest are tiles;
 *  a large group shows only what needs a look, the whole of it opens as a list */
function TilesView({ items, page, section, sections, c }) {
  const t = T()
  const f = useRowFilter(items)
  const [drawer, setDrawer] = useState(null)
  const groups = []
  for (const it of f.shown) {
    const key = it.group ?? ''
    let g = groups.find(x => x.key === key)
    if (!g) groups.push(g = { key, head: null, rows: [] })
    if (it.icon === 'account' && !g.head) g.head = it
    else g.rows.push(it)
  }
  const servicesOf = it => {
    if (!it.account?.id || it.icon === 'account') return null
    const d = accountRows(sections, it.account.id)
    return d && d.rows.length ? { n: d.rows.length, open: () => setDrawer(d) } : null
  }
  return html`<div class="rview">
    <${FilterBar} f=${f} label=${t.filterLabel} />
    ${!f.shown.length ? html`<${Empty}>${t.filterNone}<//>` : groups.map(g => {
      const all = items.filter(it => (it.group ?? '') === g.key && it !== g.head)
      const n = k => all.filter(toneFilter(k)).length
      const big = g.head && all.length > MANY && !f.active
      const tiles = big ? g.rows.filter(toneFilter('problems')) : g.rows
      const open = tags => setDrawer({ title: g.head.title, head: g.head, section, rows: all, tags })
      const kindKey = Object.keys(all[0]?.tags ?? {})[0]
      const kinds = kindKey ? Object.entries(all.reduce((m, it) => ({ ...m, [it.tags?.[kindKey]]: (m[it.tags?.[kindKey]] ?? 0) + 1 }), {}))
        .filter(([k]) => k !== 'undefined').sort((a, b) => b[1] - a[1]) : []
      return html`<section class="rgroup" key=${g.key}>
        ${g.head ? html`<header class=${`rgroup-head is-card rt-${g.head.tone ?? 'ok'}`}>
            <span class="rtile-icon"><${ResIcon} name=${g.head.icon} size=${22} /></span>
            <div class="rgroup-main"><h3 class="rgroup-title">${g.head.title}</h3>
              ${g.head.detail ? html`<p class="rtile-detail">${g.head.detail}</p>` : null}
              ${g.head.meter ? html`<${MeterBar} meter=${g.head.meter} scale=${0} tone=${g.head.tone} />` : null}
              ${all.length ? html`<div class="rgroup-kinds">${kinds.map(([k, m]) => html`<button type="button" key=${k} class="fchip fchip-g"
                onClick=${() => open({ [kindKey]: k })}>${k} <span class="mono">${m}</span></button>`)}</div>` : null}</div>
            <div class="btn-row rgroup-acts">
              ${all.length ? html`<${Btn} size="xs" variant="primary" onClick=${() => open({})}>${t.resServices(all.length)}<//>` : null}
              ${g.head.link?.kind === 'web' ? html`<a class="btn btn-secondary btn-xs" href=${g.head.link.href} target="_blank" rel="noopener noreferrer">
                <${Icon} name="external" size=${13} /><span class="btn-label">${t.openLink}</span></a>` : null}
              <${Btn} size="xs" variant="ghost" onClick=${() => c.ask('info', { page, section, index: g.head.index })}>${t.btnAsk}<//>
            </div>
          </header>`
          : g.key ? html`<header class="rgroup-head"><h3 class="rgroup-title">${g.key}</h3>
            <span class="rgroup-count">${['ok', 'problems', 'off'].filter(k => n(k)).map(k => html`<span key=${k} class="rgroup-n">
              <span class=${`fdot fdot-${FILTER_TONE[k]}`} aria-hidden="true"></span>${t.filterTone[k]} <span class="mono">${n(k)}</span></span>`)}</span></header>` : null}
        ${big && tiles.length ? html`<h4 class="label-caps mosaic-sub">${t.mosaicProblems(tiles.length)}</h4>` : null}
        ${tiles.length ? html`<div class="rtiles">${tiles.map((it, i) => html`<${ResTile} key=${it.index} it=${it} i=${i} page=${page}
          section=${section} c=${c} services=${servicesOf(it)} />`)}</div>` : null}
      </section>`
    })}
    ${drawer ? html`<${ResDrawer} d=${drawer} page=${page} c=${c} onClose=${() => setDrawer(null)} />` : null}
  </div>`
}

/** Every row as one small square, coloured and patterned by its state; a click shows it, the rows that
 *  need a look follow as tiles. Rows with a gauge (a summary) stand on top */
function MosaicView({ items, page, section, c }) {
  const t = T()
  const heads = items.filter(it => it.meter)
  const cells = items.filter(it => !it.meter)
  const f = useRowFilter(cells)
  const [pick, setPick] = useState(null)
  const picked = cells.find(it => it.index === pick) ?? null
  const legend = [...new Set(cells.map(it => it.group).filter(Boolean))].map(g => ({ g, n: cells.filter(it => it.group === g).length,
    tone: cells.find(it => it.group === g)?.tone ?? 'ok' }))
  const [allProblems, setAllProblems] = useState(false)
  const problemsAll = f.shown.filter(it => it.tone === 'bad' || it.tone === 'warn')
  // red always shows; of the rest the first six, the others one click away
  const problems = allProblems ? problemsAll : problemsAll.filter((it, i) => it.tone === 'bad' || i < 6)
  return html`<div class="rview">
    ${heads.map(h => html`<div class=${`mosaic-head rt-${h.tone ?? 'ok'}`} key=${h.index}>
      <div><h3 class="rgroup-title">${h.title}</h3>${h.detail ? html`<p class="rtile-detail">${h.detail}</p>` : null}</div>
      <${MeterBar} meter=${h.meter} scale=${0} tone=${h.tone} /></div>`)}
    <${FilterBar} f=${f} label=${t.filterLabel} groups=${false} />
    <div class="mosaic" role="list" aria-label=${section}>${f.shown.map((it, i) => html`<button type="button" role="listitem" key=${it.index}
      class=${`mcell mc-${it.tone ?? 'ok'}${pick === it.index ? ' is-picked' : ''}`} style=${{ '--i': Math.min(i, 60) }}
      title=${`${it.title}: ${it.group ?? ''}`} aria-label=${`${it.title}, ${it.group ?? ''}`}
      onClick=${() => setPick(pick === it.index ? null : it.index)}></button>`)}</div>
    <div class="mosaic-legend">${legend.map(l => html`<button type="button" key=${l.g} class=${`fchip fchip-g${f.group === l.g ? ' is-on' : ''}`}
      onClick=${() => f.setGroup(f.group === l.g ? null : l.g)}><span class=${`mcell mcell-sm mc-${l.tone}`} aria-hidden="true"></span>${l.g} <span class="mono">${l.n}</span></button>`)}</div>
    ${picked ? html`<div class="rtiles"><${ResTile} it=${picked} i=${0} page=${page} section=${section} c=${c} /></div>` : null}
    ${problemsAll.length && !picked ? html`<h4 class="label-caps mosaic-sub">${t.mosaicProblems(problemsAll.length)}</h4>
      <div class="rtiles">${problems.map((it, i) => html`<${ResTile} key=${it.index} it=${it} i=${i} page=${page} section=${section} c=${c} />`)}</div>
      ${problemsAll.length > problems.length || allProblems ? html`<${Btn} size="xs" variant="ghost" icon="chevronDown"
        onClick=${() => setAllProblems(!allProblems)}>${allProblems ? t.mosaicFewer : t.mosaicAll(problemsAll.length)}<//>` : null}` : null}
  </div>`
}

/** Rows under their group (a log under its task), the busiest first; each group shows its newest
 *  rows, the rest one click away */
function GroupsView({ items, page, section, c }) {
  const t = T()
  const [open, setOpen] = useState({})
  const groups = groupRows(items).sort((a, b) => b.rows.length - a.rows.length)
  return html`<div class="gview">${groups.map((g, gi) => {
    const all = !!open[g.key]
    const rows = all ? g.rows : g.rows.slice(0, 3)
    return html`<section class="gview-group row-in" key=${g.key} style=${{ '--i': Math.min(gi, 14) }}>
      <header class="gview-head">
        <h3 class="gview-title">${g.key || t.groupOther}</h3>
        <span class="gview-count mono">${g.rows.length}</span>
        ${g.rows[0]?.when ? html`<span class="muted small">${t.groupLast(g.rows[0].when)}</span>` : null}
      </header>
      <ul class="gview-rows">${rows.map(it => html`<li key=${it.index} class=${`gview-row card-opens${it.tone === 'dim' ? ' is-dim' : ''}`} tabindex="0"
        onClick=${e => { if (rowClickOpens(e)) c.openInfo(it, page, section) }}
        onKeyDown=${e => { if (e.key === 'Enter' && e.target === e.currentTarget) { e.preventDefault(); c.openInfo(it, page, section) } }}>
        <span class="gview-when mono">${it.when}</span><span class="gview-text">${it.title}</span>
        ${it.ask ? html`<${Btn} size="xs" variant="ghost" onClick=${() => c.ask('info', { page, section, index: it.index })}>${t.btnAsk}<//>` : null}
      </li>`)}</ul>
      ${g.rows.length > 3 ? html`<${Btn} size="xs" variant="ghost" icon="chevronDown"
        onClick=${() => setOpen({ ...open, [g.key]: !all })}>${all ? t.mosaicFewer : t.mosaicAll(g.rows.length)}<//>` : null}
    </section>`
  })}</div>`
}

function PageSection({ page, section, s, c }) {
  const byKey = indexRows(s.model)
  const t = T()
  const more = section.whole ? null : s.more[`${page.id}/${section.id}`]   // whole: the caller already took every row
  // a task or inbox section follows the triage filter on top of its page
  const all = more ? more.items : (section.items ?? [])
  const items = section.kind === 'tasks' || section.kind === 'inbox'
    ? all.filter(it => triageShows(it, s.triage?.items, s.ui.triageFilter)) : all
  const left = more ? 0 : section.more ?? 0
  const scale = meterScale(items)
  // nothing found: a section that says so in one quiet line, or none at all when the profile asks
  const quiet = !items.length && section.status !== 'error' && section.status !== 'skipped'
  if (quiet && section.hide_empty) return null
  if (quiet) {
    return html`<section class="panel psec psec-quiet" aria-labelledby=${`ps-${page.id}-${section.id}`}>
      <h2 class="sec-title" id=${`ps-${page.id}-${section.id}`}>${section.title}</h2>
      <${StateLine} token=${section.alarm ? 'success' : 'info'} word=${section.empty || t.empty} />
      ${section.as_of ? html`<span class="muted small">${t.sourceAsOf(section.as_of)}</span>` : null}
    </section>`
  }
  let body
  if (section.status === 'skipped') body = html`<p class="muted"><${StateLine} token="info" word=${t.skippedSection} /></p>`
  else if (section.status === 'error') body = html`<p><${StateLine} token="danger" strong word=${t.unreadable(section.reason || '')} /></p>`
  else if (section.view === 'tiles') body = html`<${TilesView} items=${items} page=${page.id} section=${section.id} sections=${page.sections} c=${c} />`
  else if (section.view === 'groups') body = html`<${GroupsView} items=${items} page=${page.id} section=${section.id} c=${c} />`
  else if (section.view === 'mosaic') body = html`<${MosaicView} items=${items} page=${page.id} section=${section.id} c=${c} />`
  else if (gaugeSection(items)) {
    body = html`<ul class="gtiles">${items.map(it => html`<${GaugeTile} key=${it.index} it=${it} page=${page.id} section=${section.id} c=${c} />`)}</ul>`
  } else {
    const row = it => html`<${InfoRow} key=${it.index} it=${it} page=${page.id} section=${section.id} s=${s} c=${c} byKey=${byKey} scale=${scale} />`
    // a task list in lanes: being worked on, runs on (quiet until a day), waits for your yes; one lane, no heads
    const lanes = section.kind === 'tasks' ? TASK_LANES.map(id => [id, items.filter(it => taskLane(it) === id)]).filter(([, l]) => l.length) : []
    body = html`<div class="table-wrap" tabindex="0" role="region" aria-label=${section.title}>
      <table class="tbl">
        <thead><tr><th scope="col" class="c-when">${t.col.when}</th><th scope="col">${t.col.item}</th><th scope="col" class="c-acts">${t.col.actions}</th></tr></thead>
        ${lanes.length > 1 ? lanes.map(([id, list]) => html`<tbody key=${id} class=${`lane-${id}`}>
          <tr class="lane-head"><th scope="rowgroup" colspan="3"><span class="label-caps">${t.lane[id]}</span> <span class="sec-count mono">${list.length}</span></th></tr>
          ${list.map(row)}</tbody>`)
          : html`<tbody>${items.map(row)}</tbody>`}
      </table>
    </div>`
  }
  return html`<section class="panel panel-pad psec" aria-labelledby=${`ps-${page.id}-${section.id}`}>
    <header class="psec-head">
      <h2 class="sec-title" id=${`ps-${page.id}-${section.id}`}>${section.title}
        ${section.status !== 'skipped' && section.status !== 'error' ? html`<span class="sec-count mono">${section.total ?? section.count}</span>` : null}</h2>
      ${section.bad ? html`<${StateLine} token="danger" strong word=${t.badgeFindings(section.bad)} />` : null}
      ${section.as_of ? html`<span class="muted small">${t.sourceAsOf(section.as_of)}</span>` : null}
    </header>
    ${body}
    ${left > 0 ? html`<${Btn} size="xs" variant="ghost" icon="chevronDown" onClick=${() => c.loadMore(page.id, section.id)}>${t.btnMore(left)}<//>` : null}
  </section>`
}

// ---------------------------------------------------------------- page overview (Betrieb): tiles, tokens of the week

/** Scroll to a section of the open page (the overview tiles jump there) */
function jumpTo(id) {
  const el = document.getElementById(id)
  if (el) el.scrollIntoView({ behavior: reducedMotion() ? 'auto' : 'smooth', block: 'start' })
}

function BoardTile({ title, tone, big, sub, note, onClick, label }) {
  return html`<li><button type="button" class=${`otile tk-${tone}`} onClick=${onClick} aria-label=${label}>
    <span class="otile-head"><${Dot} token=${tone === 'neutral' ? 'on-surface-muted' : tone} /><span class="otile-title">${title}</span></span>
    <span class="otile-big num">${big}</span>
    ${sub ? html`<span class="otile-sub">${sub}</span>` : null}
    ${note ? html`<span class="otile-note">${note}</span>` : null}
  </button></li>`
}

/** The board on top of a page with `overview: true`: a tile per section and per live source (workers, tokens),
 *  each a click away from its details. The running sessions stand in the tab column beside it */
function OverviewBoard({ page, s, c }) {
  const t = T()
  const lang = language()
  const tiles = []
  const stats = s.workers?.data?.stats
  if (stats) {
    const bad = stats.with_findings ?? 0
    const all = stats.in_service ?? 0
    tiles.push(html`<${BoardTile} key="@w" title=${t.workersTab} tone=${bad ? 'warning' : 'success'} big=${bad || all}
      sub=${t.overviewWorkers(all - bad, all, bad)} label=${t.overviewJump(t.workersTab)} onClick=${() => c.openWorkers({})} />`)
  }
  const u = s.usage?.data
  if (u) {
    const day = usageToday(u)
    tiles.push(html`<${BoardTile} key="@u" title=${t.usageTitle} tone=${u.outliers?.length ? 'warning' : 'neutral'} big=${tokenText(day.today, lang)}
      sub=${day.usual == null ? null : t.usageUsual(tokenText(day.usual, lang))}
      note=${u.outliers?.length ? t.usageOutlier(t.usageSource[u.outliers[0].source], u.outliers[0].factor) : null}
      label=${t.overviewJump(t.usageTitle)} onClick=${() => jumpTo(`usage-${page.id}`)} />`)
  }
  for (const sec of page.sections ?? []) {
    const x = sectionTile(sec)
    if (sec.hide_empty && !x.count && x.state === 'ok') continue
    const sub = x.state === 'error' ? t.unreadable(x.note || '') : x.state === 'skipped' ? t.skippedSection
      : x.peak ? t.overviewPeak(x.peak.title, x.peak.percent)
      : x.counts ? x.counts.map(g => `${g.title} ${Math.round(g.value)}/${Math.round(g.max)}`).join(', ')
      : x.loud ? null : (x.count ? null : sec.empty)
    tiles.push(html`<${BoardTile} key=${sec.id} title=${sec.title} tone=${x.tone} big=${x.peak ? `${x.peak.percent} %` : x.loud || x.count}
      sub=${sub} note=${x.state === 'ok' ? x.note : null} label=${t.overviewJump(sec.title)} onClick=${() => jumpTo(`ps-${page.id}-${sec.id}`)} />`)
  }
  return html`<ul class="oboard" aria-label=${page.title}>${tiles}</ul>`
}

/** The written tokens of the last seven days, a bar per day split by who asked; a click on a day shows its
 *  models and projects. Read when the page opens and with every new briefing, never on a timer */
function UsageCard({ page, s, c }) {
  const t = T()
  const lang = language()
  useEffect(() => { c.loadUsage() }, [s.model?.seq ?? 0])
  const u = s.usage ?? {}
  const data = u.data
  const [pick, setPick] = useState(null)
  const bars = usageBars(data)
  const sel = (data?.days ?? []).find(d => d.day === pick) ?? data?.days?.[data.days.length - 1]
  const names = weekdayNames(lang)
  const dayName = iso => { const d = new Date(`${iso}T12:00:00`); return names[(d.getDay() + 6) % 7] }
  const sum = f => USAGE_SOURCES.reduce((a, k) => a + (sel?.sources?.[k]?.[f] ?? 0), 0)
  return html`<section class="panel panel-pad psec usage" id=${`usage-${page.id}`} aria-labelledby=${`usage-${page.id}-t`}>
    <header class="psec-head">
      <h2 class="sec-title" id=${`usage-${page.id}-t`}>${t.usageTitle}</h2>
      <span class="muted small">${t.usageWhere}</span>
    </header>
    ${!data ? html`<p class="muted">${u.status === 'error' ? t.unreadable(u.error || '') : t.usageLoading}</p>`
      : !bars.max ? html`<${Empty}>${t.usageNone}<//>` : html`
      ${(data.outliers ?? []).map(o => html`<p key=${o.source}><${StateLine} token="warning" strong word=${t.usageOutlier(t.usageSource[o.source], o.factor)} /></p>`)}
      <div class="ubars" role="group" aria-label=${t.usageTitle}>
        ${bars.days.map(d => html`<button type="button" key=${d.day} class=${`ubar${sel?.day === d.day ? ' is-on' : ''}`}
            aria-pressed=${sel?.day === d.day} aria-label=${`${t.usageDayOf(formatDay(d.day, lang))}: ${tokenText(d.total, lang)}`}
            onClick=${() => setPick(d.day)}>
          <span class="ubar-n mono">${tokenText(d.total, lang)}</span>
          <span class="ubar-col">${d.parts.map(p => html`<span key=${p.source} class=${`ubar-part us-${p.source}`}
            style=${{ height: `${(p.frac * 100).toFixed(2)}%` }} title=${`${t.usageSource[p.source]}: ${tokenText(p.value, lang)}`}></span>`)}</span>
          <span class="ubar-day">${dayName(d.day)}</span>
        </button>`)}
      </div>
      <ul class="ulegend">${USAGE_SOURCES.map(k => html`<li key=${k}><span class=${`ukey us-${k}`} aria-hidden="true"></span>
        ${t.usageSource[k]} <span class="mono">${tokenText(sel?.sources?.[k]?.output ?? 0, lang)}</span></li>`)}</ul>
      ${sel ? html`<div class="uday">
        <h3 class="uday-title">${formatDay(sel.day, lang)}</h3>
        <div class="uday-cols">
          <div><span class="label-caps">${t.usageModels}</span>
            <ul class="ulist">${(sel.models ?? []).map(m => html`<li key=${m.model}><span>${m.model.replace(/^claude-/, '')}</span><span class="num">${tokenText(m.output, lang)}</span></li>`)}</ul></div>
          <div><span class="label-caps">${t.usageProjects}</span>
            <ul class="ulist">${(sel.projects ?? []).map(p => html`<li key=${p.project}><span>${p.project}</span><span class="num">${tokenText(p.output, lang)}</span></li>`)}</ul></div>
        </div>
        <p class="muted small">${t.usageInput(tokenText(sum('input'), lang), tokenText(sum('cache_read'), lang), tokenText(sum('cache_write'), lang))}</p>
      </div>` : null}`}
  </section>`
}

// ---------------------------------------------------------------- a work page in the order of Jev

/** Which kind of row a page with inbox and task rows shows: all, or one label (inbox, task, ...) */
function KindBar({ kinds, active, c }) {
  const t = T()
  const total = kinds.reduce((a, k) => a + k.n, 0)
  const chip = (label, n, on) => html`<button type="button" role="radio" key=${label ?? '@all'} aria-checked=${String(on)}
    class=${`fchip${on ? ' is-on' : ''}`} onClick=${() => c.setWorkKind(label)}>${label ?? t.workOrder.kindAll} <span class="mono">${n}</span></button>`
  return html`<div class="panel panel-pad tri-bar" role="group" aria-label=${t.workOrder.kindFilter}>
    <span class="fbar-chips" role="radiogroup" aria-label=${t.workOrder.kindFilter}>
      ${chip(null, total, !active)}${kinds.map(k => chip(k.label, k.n, active?.label === k.label))}
    </span></div>`
}

/** The strip on a page with `jev:`: by area or by Jev, and the click that orders it. Nothing goes to Jev
 *  by itself: on open the page only asks the server for the last order */
function WorkOrder({ page, s, c }) {
  const t = T()
  const lang = language()
  const st = s.jevOrder[page.id]
  useEffect(() => { if (st === undefined) c.jevRank(page.id, false) }, [page.id])
  const order = st?.order ?? null
  const view = order && s.ui.workView === 'jev' ? 'jev' : 'area'
  const tokens = order?.usage && order.usage.input_tokens != null ? tokenText((order.usage.input_tokens ?? 0) + (order.usage.output_tokens ?? 0), lang) : null
  return html`<div class="panel panel-pad tri-bar jorder" role="group" aria-label=${t.workOrder.label}>
    <span class="fbar-chips" role="radiogroup" aria-label=${t.workOrder.label}>
      ${['area', 'jev'].map(v => html`<button type="button" role="radio" key=${v} aria-checked=${String(view === v)}
        class=${`fchip${view === v ? ' is-on' : ''}`} disabled=${v === 'jev' && !order} onClick=${() => c.setWorkView(v)}>
        ${v === 'area' ? t.workOrder.byArea : t.workOrder.byJev}</button>`)}
    </span>
    <span class="tri-run">
      <span class="muted small">${st?.running ? t.workOrder.running : order ? html`${t.workOrder.last(order, lang, tokens)}<span class="jleft"><span class="jsep"> · </span>${t.workOrder.left(order.skipped)}</span>` : t.workOrder.never}</span>
      <button type="button" class=${`btn ${order ? 'btn-ghost' : 'btn-secondary'} btn-xs`} disabled=${!!st?.running} aria-busy=${st?.running ? 'true' : undefined}
        title=${t.workOrder.what} onClick=${() => c.jevRank(page.id, true)}><span class="btn-label">${order ? t.workOrder.rerun : t.workOrder.run}</span></button>
    </span>
    ${st?.error ? html`<p class="jerr"><${StateLine} token="danger" word=${t.workOrder.failed(st.error)} /></p>` : null}
  </div>`
}

/** Every row of the page in one list: Jev's order first, each row with its rank and its label, then the
 *  rows Jev did not see. A section with more rows than shown loads them, so the list is whole */
function JevList({ page, s, c }) {
  const t = T()
  const byKey = indexRows(s.model)
  useEffect(() => {
    for (const sec of page.sections ?? []) if ((sec.more ?? 0) > 0 && !s.more[`${page.id}/${sec.id}`]) c.loadMore(page.id, sec.id)
  }, [page.id])
  const sections = (page.sections ?? []).map(sec => {
    const all = s.more[`${page.id}/${sec.id}`]?.items ?? sec.items ?? []
    return { ...sec, items: all.filter(it => triageShows(it, s.triage?.items, s.ui.triageFilter)) }
  })
  const list = jevList(sections, s.jevOrder[page.id]?.order, t.workOrder.kinds)
  const rows = entries => html`<div class="table-wrap" tabindex="0" role="region" aria-label=${page.title}>
    <table class="tbl"><thead><tr><th scope="col" class="c-when">${t.col.when}</th><th scope="col">${t.col.item}</th><th scope="col" class="c-acts">${t.col.actions}</th></tr></thead>
      <tbody>${entries.map(r => html`<${InfoRow} key=${`${r.section}/${r.it.index}`} it=${r.it} page=${page.id} section=${r.section} s=${s} c=${c}
        byKey=${byKey} lead=${{ rank: r.rank, label: r.label, judge: r.judge }} />`)}</tbody></table></div>`
  return html`
    <section class="panel panel-pad psec" aria-labelledby=${`ps-${page.id}-jev`}>
      <header class="psec-head"><h2 class="sec-title" id=${`ps-${page.id}-jev`}>${t.workOrder.byJev}
        <span class="sec-count mono">${list.ranked.length}</span></h2></header>
      ${list.ranked.length ? rows(list.ranked) : html`<${Empty}>${t.filterNone}<//>`}
    </section>
    ${list.rest.length ? html`<section class="panel panel-pad psec" aria-labelledby=${`ps-${page.id}-jrest`}>
      <header class="psec-head"><h2 class="sec-title" id=${`ps-${page.id}-jrest`}>${t.workOrder.rest(list.rest.length)}</h2></header>
      ${rows(list.rest)}
    </section>` : null}`
}

// ---------------------------------------------------------------- the start page

/** The title of a page in the bar, fixed or from the profile */
function pageTitleOf(s, id) {
  const t = T()
  const fixed = { briefing: briefingTitle(s), [SESSIONS_PAGE]: t.sessionsTab, [WORKERS_PAGE]: t.workersTab, [CHAT_PAGE]: t.chatTab,
    [AGENTS_PAGE]: t.agentsTab, [CHECK_PAGE]: t.reviewTab, [JEV_PAGE]: 'Jev' }
  return fixed[id] ?? (s.model?.pages ?? []).find(p => p.id === id)?.title ?? id
}

/** On the start page an object opens whole: an inbox item or a task in the wide drawer with every detail
 *  and action, over the page instead of beside it, so nothing on the page gets squeezed. Other rows have
 *  only the detail column */
function openWhole(c, row, el) {
  return /^(inbox|task):/.test(row.key) ? c.openItem(row.key, row) : c.peek(row.key, el)
}

/** The starts handed to a tab, each with where it stands now */
function returnsOf(s) {
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
function ReturnCard({ r, s, c }) {
  const t = T()
  const h = t.home
  const ago = duration((s.now || Date.now()) - r.at_ms)
  const tab = (s.tabs?.tabs ?? []).find(x => x.ref === r.tab?.ref) ?? null
  const row = indexRows(s.model).get(r.key)
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
    <div class="hcard-acts">
      ${r.result?.key ? html`<${Btn} size="xs" variant="primary" onClick=${() => c.openItem(r.result.key, null)}>${h.returnOpenAnswer}<//>` : null}
      ${tab ? html`<${Btn} size="xs" variant=${r.result?.key ? 'secondary' : 'primary'} onClick=${() => jumpToTab(s, c, tab.ref)}>${h.toTab}<//>
        <${Btn} size="xs" variant="ghost" onClick=${() => c.openTabView(tab.ref)}>${h.view}<//>` : null}
      ${!tab && row && r.live === 'lost' ? html`<${RowActions} row=${row} s=${s} c=${c} />` : null}
    </div>
  </article>`
}

/** The newest start of any of these rows in the return channel */
function returnFor(s, keys) {
  const want = new Set((Array.isArray(keys) ? keys : [keys]).filter(Boolean))
  return returnsOf(s).find(x => want.has(x.key)) ?? null
}

/** A chip on a card or a row: the agent is at it, it asks, or its answer came */
function ReturnChip({ s, rowKey }) {
  const r = returnFor(s, rowKey)
  if (!r || r.live === 'done') return null
  return html`<span class=${`chip chip-tk tk-${stageTone(r.live)} rchip`}><${Dot} token=${stageTone(r.live)} pulse=${r.live === 'working'} />
    <span>${T().home.returnStage[r.live]}</span></span>`
}

/** The return channel inside a task or an inbox item: the steps, what the tab said last or its answer, and
 *  the ways on. Shown wherever the item opens, so its state is never only on the start page */
function ReturnPanel({ s, c, keys }) {
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
function jumpToTab(s, c, ref) {
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
function PinStar({ rowKey, s, c }) {
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
 *  the page, and a task with an agent tab leads straight into that tab */
function HomeRowCard({ row, s, c, tab, big = false }) {
  const t = T()
  const n = s.model?.numbers?.[row.key] ?? row.number
  const project = row.area || row.area_names?.[0] || row.mark?.label || ''
  return html`<article class=${`hcard hcard-row${big ? ' hcard-focus' : ''}`}>
    <div class="hcard-row-head">
      ${n != null ? html`<span class="hcard-num mono" aria-label=${t.numberLabel(n)}>${n}</span>` : null}
      ${project ? html`<span class=${`hcard-proj tk-${projectTone(project)}`}>${project}</span>` : null}
      <${PrioChip} priority=${row.priority} />
      <${ReturnChip} s=${s} rowKey=${row.key} />
      <span class="hcard-head-end"><${PinStar} rowKey=${row.key} s=${s} c=${c} /></span>
    </div>
    <button type="button" class="hcard-row-main" title=${t.home.openRow(short(row.title, 60))}
      onClick=${e => openWhole(c, row, e.currentTarget)}>
      <span class=${`hcard-title ${big ? 'clamp2' : 'clamp3'}`}>${row.title}</span>
    </button>
    <${RowMeta} row=${row} s=${s} />
    <div class="hcard-acts">
      ${tab ? html`<${Btn} size="xs" variant="primary" busy=${!!s.ui.busy[tab.ref]} onClick=${() => jumpToTab(s, c, tab.ref)}>${t.home.toTab}<//>`
        : html`<${RowActions} row=${row} s=${s} c=${c} />`}
      <${SettleMenu} rows=${[row]} s=${s} c=${c} />
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
function pct(v, lang) {
  return v.toLocaleString(lang === 'de' ? 'de-DE' : 'en-GB', { maximumFractionDigits: v < 10 ? 1 : 0 })
}

/** A quota's last days as small bars against the budget line; today is the last bar */
function DayBars({ days, budget, label }) {
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
function pageParts(s, p) {
  if (p.badge?.kind === 'bad') return (s.model?.alarms ?? []).filter(a => a.page_id === p.id).map(a => `${a.section_title} ${a.count}`)
  return (p.sections ?? []).filter(x => (x.total ?? x.count ?? 0) > 0)
    .sort((a, b) => (b.total ?? b.count) - (a.total ?? a.count)).slice(0, 3).map(x => `${x.title} ${x.total ?? x.count}`)
}

/** The next date as a tile: how long until it begins, its title and time; a click opens it */
function NextTile({ s, c }) {
  const h = T().home
  const next = nextEvent(s.model, s.now || Date.now())
  if (!next) return html`<${CountTile} n="·" label=${h.nextNone} onClick=${() => {}} title=${h.nextNone} />`
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

/** The name of a catalog entry in the chooser */
function catalogLabel(x) {
  const h = T().home
  if (x.kind === 'quota' || x.kind === 'page') return x.label
  return { 'c:waiting': h.waitingNow, 'c:tabs': h.tabsWaiting, 'c:next': h.nextTitle, 'c:done': h.doneTitle,
    's:focus': h.focusTitle, 's:pinned': h.pinnedTitle, 's:continue': h.continueTitle, 's:waiting': h.waitingTitle,
    's:tasks': h.tasksTitle, 's:starts': h.startTitle, 'o:today': h.optToday, 'o:preview': h.optPreview,
    'o:trend': h.optTrend, 'o:title': h.optTitle, 'o:project': h.optProject, 'o:classic': h.optClassic, 'o:pulse': h.optPulse,
    'c:agents': h.agentsTitle, 'c:returns': h.returnsTitle, 's:returns': h.returnsTitle, 'c:workers': T().workersTab, 'k:scan': h.coreScan, 'k:brief': h.briefTitle, 'k:focus': h.coreFocus,
    'k:voice': h.coreVoice }[x.id] ?? x.id
}

/** The chooser: every tile, shelf and option, a click switches one on or off; the tiles shown can move
 *  left or right. Kept on the server with what it offered, so a new tile later comes with its default */
function HomeChooser({ c, catalog, chosen }) {
  const h = T().home
  const ids = catalog.map(x => x.id)
  const save = list => c.setHomeTiles(list, ids)
  const toggle = id => save(chosen.includes(id) ? chosen.filter(x => x !== id) : [...chosen, id])
  const byId = new Map(catalog.map(x => [x.id, x]))
  const order = chosen.filter(id => ['quota', 'count', 'page'].includes(byId.get(id)?.kind))
  const group = (title, kinds) => {
    const list = catalog.filter(x => kinds.includes(x.kind))
    return list.length ? html`<div class="chooser-group"><h3 class="label-caps">${title}</h3><div class="chooser-chips">
      ${list.map(x => html`<button type="button" key=${x.id} class=${`home-chip${chosen.includes(x.id) ? ' is-on' : ''}`}
        aria-pressed=${String(chosen.includes(x.id))} onClick=${() => toggle(x.id)}>${chosen.includes(x.id) ? '✓ ' : '+ '}${catalogLabel(x)}</button>`)}
    </div></div>` : null
  }
  return html`<div class="chooser panel panel-pad">
    <p class="muted small">${h.chooseHint}</p>
    ${group(h.quotaTitle, ['quota'])}
    ${group(h.countsTitle, ['count', 'page'])}
    ${group(h.shelvesTitle, ['shelf'])}
    ${group(h.optionsTitle, ['option'])}
    ${group(h.coreModes, ['core'])}
    ${order.length > 1 ? html`<div class="chooser-group"><h3 class="label-caps">${h.orderTitle}</h3><div class="chooser-chips">
      ${order.map((id, i) => html`<span class="order-chip" key=${id}>
        <button type="button" class="btn-link" disabled=${i === 0} aria-label=${h.moveLeft(catalogLabel(byId.get(id)))}
          onClick=${() => save(moveId(chosen, id, -1))}><${Icon} name="back" size=${14} /></button>
        <span>${catalogLabel(byId.get(id))}</span>
        <button type="button" class="btn-link" disabled=${i === order.length - 1} aria-label=${h.moveRight(catalogLabel(byId.get(id)))}
          onClick=${() => save(moveId(chosen, id, 1))}><${Icon} name="chevronRight" size=${14} /></button>
      </span>`)}
    </div></div>` : null}
  </div>`
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
function shownTiles(catalog, chosen) {
  const byId = new Map(catalog.map(x => [x.id, x]))
  return chosen.map(id => byId.get(id)).filter(x => x && ['quota', 'count', 'page'].includes(x.kind))
}

function HomeOverview({ s, c, catalog, chosen, project }) {
  const h = T().home
  const [edit, setEdit] = useState(false)
  const shown = shownTiles(catalog, chosen)
  const tile = tileMaker(s, c, chosen, project)
  return html`<section class="home-shelf" aria-labelledby="home-overview">
    <header class="home-shelf-head"><h2 class="home-shelf-title" id="home-overview">${h.overviewTitle}</h2>
      <${Btn} size="xs" variant=${edit ? 'primary' : 'ghost'} pressed=${edit} onClick=${() => setEdit(!edit)}>${edit ? h.chooseDone : h.choose}<//></header>
    ${edit ? html`<${HomeChooser} c=${c} catalog=${catalog} chosen=${chosen} />` : null}
    ${shown.length ? html`<div class="kgrid">${shown.map(tile)}</div>` : edit ? null : html`<${Empty}>${h.chooseEmpty}<//>`}
  </section>`
}

// ---------------------------------------------------------------- the bridge stage (the explainer films' picture)

/** A station of the stage: what a chosen tile says, short enough to hang on a link */
function stationOf(x, s, c, chosen, project) {
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
      onClick: () => c.openInfo(next.it, next.page, next.section) } : { id: x.id, label: h.nextTitle, value: '·', sub: h.nextNone, tone: null, onClick: null }
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
function leadOf(m) {
  const head = String(m.headline ?? '')
  const n = m.counts?.now
  return n != null && /^\d+\s/.test(head) ? head.replace(/^\d+/, String(n)) : head
}

/** The terminal line of the films, as the field that asks the Bridge: the greeting stands where the
 *  cursor waits, until you type */
function StagePrompt({ s, c, greeting }) {
  const t = T()
  const [text, setText] = useState('')
  const [focus, setFocus] = useState(false)
  const busy = !!s.ui.busy['ask:free']
  const send = async e => {
    e.preventDefault()
    const v = text.trim()
    if (v && await c.ask('free', { text: v })) setText('')
  }
  return html`<form class="stage-prompt" onSubmit=${send} role="search">
    <span class="stage-caret" aria-hidden="true">›</span>
    <span class="stage-field">
      <input type="text" class="stage-input" value=${text} onInput=${e => setText(e.currentTarget.value)}
        onFocus=${() => setFocus(true)} onBlur=${() => setFocus(false)} aria-label=${t.home.askPlaceholder} maxlength=${ASK_MAX} />
      ${!text && !focus ? html`<span class="stage-ghost" aria-hidden="true">${greeting}<span class="stage-cursor"></span></span>` : null}
      ${!text && focus ? html`<span class="stage-ghost is-hint" aria-hidden="true">${t.home.askPlaceholder}</span>` : null}
    </span>
    ${text.trim() ? html`<button type="submit" class="btn btn-primary btn-sm" disabled=${busy} aria-busy=${busy ? 'true' : undefined}
      aria-label=${t.askSend}><${Icon} name="send" /></button>` : null}
  </form>`
}

/** The card on the right of the films: today's next step first, then what waits on you */
/** How an event of the live feed reads, its tone, and where a click on it leads */
function FeedLine({ e, s, c }) {
  const h = T().home
  const byKey = indexRows(s.model)
  const row = e.key ? byKey.get(e.key) : null
  const tone = { new: 'info', urgent: 'warning', gone: 'success', tabAsks: 'warning', answer: 'success', lost: 'danger', alarm: 'danger' }[e.kind] ?? 'muted'
  const go = e.ref ? () => jumpToTab(s, c, e.ref) : e.page ? () => c.setPage(e.page) : row ? el => openWhole(c, row, el) : null
  const clock = new Date(e.at).toLocaleTimeString(language() === 'de' ? 'de-DE' : 'en-GB', { hour: '2-digit', minute: '2-digit' })
  return html`<li class=${`feed-line tk-${tone}`}>
    <span class="feed-time mono">${clock}</span><span class="stage-dot" aria-hidden="true"></span>
    ${go ? html`<button type="button" class="feed-text" onClick=${ev => go(ev.currentTarget)}><b>${h.feed[e.kind] ?? e.kind}</b> ${short(e.title, 70)}</button>`
      : html`<span class="feed-text"><b>${h.feed[e.kind] ?? e.kind}</b> ${short(e.title, 70)}</span>`}
  </li>`
}

/** Rows that came in a little while ago carry "new" */
function freshKeys(s, ms = 15 * 60000) {
  const now = s.now || Date.now()
  return new Set((s.feed ?? []).filter(e => e.kind === 'new' && now - e.at < ms).map(e => e.key))
}

function StageCard({ s, c, tabs }) {
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
  const row = (r, lead) => html`<div class=${`stage-row${lead ? ' is-lead' : ''}${fresh.has(r.key) ? ' is-new' : ''}`} key=${r.key}>
    <span class=${`stage-dot tk-${dot(r)}`} aria-hidden="true"></span>
    <button type="button" class="stage-row-main" onClick=${e => openWhole(c, r, e.currentTarget)} title=${h.openRow(short(r.title, 60))}>
      <span class="stage-row-title">${fresh.has(r.key) ? html`<span class="new-tag">${h.isNew}</span>` : null}${r.priority ? html`<em class=${`tk-${dot(r)}`}>${r.priority} </em>` : null}${short(r.title, lead ? 120 : 80)}</span>
      ${sub(r) ? html`<span class="stage-row-sub">${sub(r)}</span>` : null}
      <${ReturnChip} s=${s} rowKey=${r.key} />
    </button>
    ${lead ? html`<span class="stage-pill">${h.focusTitle}</span>` : null}
    ${lead ? html`<div class="stage-row-acts">
      ${tabOfTask(tabs, r.task) ? html`<${Btn} size="xs" variant="primary" onClick=${() => jumpToTab(s, c, tabOfTask(tabs, r.task).ref)}>${h.toTab}<//>`
        : html`<${RowActions} row=${r} s=${s} c=${c} />`}
      <${SettleMenu} rows=${[r]} s=${s} c=${c} /><${PinStar} rowKey=${r.key} s=${s} c=${c} /></div>` : null}
  </div>`
  return html`<section class="stage-card" aria-labelledby="stage-card-title">
    <header class="stage-card-head"><h2 id="stage-card-title">${h.cardTitle}</h2><small class="mono">${stamp}</small></header>
    ${pick?.kind === 'tab' ? html`<div class="stage-row is-lead">
      <span class="stage-dot tk-warning dot-pulse" aria-hidden="true"></span>
      <button type="button" class="stage-row-main" onClick=${() => jumpToTab(s, c, pick.tab.ref)} title=${h.openTab(pick.tab.name)}>
        <span class="stage-row-title">${pick.tab.name}</span><span class="stage-row-sub">${pick.tab.workspace} · ${t.state[pick.tab.state] ?? pick.tab.state}</span>
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
      ${(s.feed ?? []).length ? html`<ol class="feed-list">${(s.feed ?? []).slice(0, 7).map(e => html`<${FeedLine} key=${`${e.kind}${e.key ?? e.ref ?? e.title}${e.at}`} e=${e} s=${s} c=${c} />`)}</ol>`
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
    const acts = r => tabOfTask(tabs, r.task)
      ? html`<${Btn} size="xs" variant="primary" onClick=${() => jumpToTab(s, c, tabOfTask(tabs, r.task).ref)}>${h.toTab}<//>`
      : html`<${RowActions} row=${r} s=${s} c=${c} /><${SettleMenu} rows=${[r]} s=${s} c=${c} /><${PinStar} rowKey=${r.key} s=${s} c=${c} />`
    body = html`${head(h.waitingNow, String(rows.length))}
      ${rows.slice(0, 8).map((r, i) => html`<${InspectRow} key=${r.key} tone=${r.urgency === 'now' ? 'danger' : r.urgency === 'today' ? 'warning' : 'info'}
        title=${short(r.title, i ? 90 : 140)} sub=${r.area || r.mark?.label || ''} onClick=${e => openWhole(c, r, e.currentTarget)}>${i === 0 ? acts(r) : null}<//>`)}
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
      ${list.slice(0, 8).map(tb => html`<${InspectRow} key=${tb.ref} tone=${stateToken(tb.state)} title=${tb.name}
        sub=${`${tb.workspace || '·'} · ${t.state[tb.state] ?? tb.state}`} side=${duration(s.now - (tb.since_ms || s.now))}
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
      ${week.items.map(i => html`<${InspectRow} key=${i.slug} tone="success" title=${i.title} sub=${i.slug}
        side=${i.closed.slice(5).split('-').reverse().join('.')} />`)}`
  } else if (x.page) {
    const p = x.page
    const secs = (p.sections ?? []).filter(sec => (sec.items ?? []).length)
    body = html`${head(p.title, String(p.badge?.n ?? 0))}
      <div class="inspect-parts">${(p.sections ?? []).filter(sec => (sec.total ?? sec.count ?? 0) > 0).map(sec => html`<span key=${sec.id} class="chip">
        ${sec.title} <span class="mono">${sec.total ?? sec.count}</span></span>`)}</div>
      ${secs.flatMap(sec => sec.items.slice(0, 4).map(it => ({ it, sec }))).slice(0, 8).map(({ it, sec }) => html`<${InspectRow}
        key=${`${sec.id}/${it.index}`} tone=${it.tone === 'bad' ? 'danger' : it.tone === 'warn' ? 'warning' : 'info'}
        title=${short(it.title, 90)} sub=${[sec.title, it.when].filter(Boolean).join(' · ')} onClick=${() => c.openInfo(it, p.id, sec.id)} />`)}
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

/** Speech into the bridge: the browser's own speech recognition, one sentence, then it goes to the core.
 *  Which service hears it depends on the browser */
function useVoice(onText) {
  const [listening, setListening] = useState(false)
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
    r.onerror = () => setListening(false)
    rec.current = r
    setListening(true)
    r.start()
    return true
  }
  const stop = () => { rec.current?.stop(); setListening(false) }
  return { available: !!Ctor, listening, start, stop }
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
  const live = conv ? s.quickLive?.[conv.id] : null
  if (!turn || (!turn.a && !turn.error)) {
    return html`<div class="verdict"><${Thinking} label=${live?.doing ? T().quickReading(live.doing) : h.sit.weighing} /></div>`
  }
  if (turn.error) return html`<p><${StateLine} token="danger" word=${T().quickFailed(turn.error)} /></p>`
  const v = parseVerdict(turn.a)
  if (!v) return html`<div class="verdict"><div class="qa">${turn.a}</div></div>`
  return html`<ol class="verdict">${['first', 'then', 'later'].map(k => html`<li key=${k} class=${`verdict-row is-${k}`}>
    <span class="label-caps">${h.sit.verdict[k]}</span><span>${v[k]}</span></li>`)}</ol>`
}

function CoreInspector({ s, c, onClose, voice, onAsk, onWeigh }) {
  const t = T()
  const h = t.home
  const relay = s.relay ?? {}
  const loading = !!s.loading?.pass
  const workers = s.workers?.data?.stats
  const agents = (s.sessions?.sessions ?? []).reduce((n, x) => n + (x.agents?.running_count ?? 0) + (x.workflows?.length ?? 0), 0)
  const conv = (s.quick?.convs ?? []).find(x => x.id === s.ui.coreConv) ?? null
  const live = conv ? s.quickLive?.[conv.id] : null
  const left = s.ui.focusUntil ? clockLeft(s.ui.focusUntil, Date.now()) : null
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
    ${left ? html`<${InspectRow} tone="info" title=${h.focusRunning(left)} sub=${h.focusHint}>
      <${Btn} size="xs" variant="ghost" onClick=${() => c.setFocus(null)}>${h.focusEnd}<//><//>` : null}
    ${voice.listening ? html`<${InspectRow} tone="warning" title=${h.voiceListening} sub=${h.voiceWhere}>
      <${Btn} size="xs" variant="ghost" onClick=${voice.stop}>${h.voiceStop}<//><//>` : null}
    ${brief ? html`<h3 class="label-caps core-sub">${h.briefTitle}</h3>
      <${SituationBoard} s=${s} c=${c} />
      <h3 class="label-caps core-sub">${h.sit.verdictTitle}</h3>
      <div class="core-brief">${conv ? html`<${Verdict} s=${s} conv=${conv} />
        ${conv.turns.length > 1 ? html`<${ChatThread} s=${s} conv=${{ ...conv, turns: conv.turns.slice(1) }} />` : null}`
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
      <div class="core-brief">${conv ? html`<${ChatThread} s=${s} conv=${conv} />` : html`<p class="muted small">${h.briefWaiting}</p>`}
        ${live?.doing ? html`<p class="muted small">${live.doing}</p>` : null}</div>` : null}
    <form class="core-ask" onSubmit=${send}>
      <input type="text" class="core-ask-input" value=${text} onInput=${e => setText(e.currentTarget.value)}
        placeholder=${conv ? h.briefFollow : h.askPlaceholder} aria-label=${h.askPlaceholder} maxlength=${ASK_MAX} />
      ${voice.available ? html`<${Btn} size="xs" variant=${voice.listening ? 'primary' : 'ghost'} pressed=${voice.listening}
        onClick=${voice.listening ? voice.stop : voice.start} label=${h.voiceStart} icon="mic" />` : null}
      <button type="submit" class="btn btn-primary btn-xs" disabled=${busy || !text.trim()} aria-label=${t.askSend}><${Icon} name="send" /></button>
    </form>
  </section>`
}

const DUST = stageDust(70, 41)

/** The stage: the core with its rings, the chosen tiles as stations on curved links with packets running
 *  in, the terminal line top left, the card on the right */
function BridgeStage({ s, c, catalog, chosen, project, edit, setEdit }) {
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
  // while a focus runs the clock ticks every second (s.now moves only every 15 s)
  const [, tick] = useState(0)
  useEffect(() => {
    if (!s.ui.focusUntil) return undefined
    const id = setInterval(() => tick(n => n + 1), 1000)
    return () => clearInterval(id)
  }, [s.ui.focusUntil])
  const focusLeft = s.ui.focusUntil ? clockLeft(s.ui.focusUntil, Date.now()) : null
  const coreAsk = async (text, conv) => { setSel('@core'); return c.askQuiet(text, conv) }
  const voice = useVoice(text => coreAsk(text))
  // a click on the core runs every mode chosen for it; with a focus running and focus chosen it ends the focus
  // one mode now: the core's panel opens and shows what it does
  const runMode = id => {
    setSel('@core')
    setWave(n => n + 1)
    if (id === 'k:scan') c.reload()
    if (id === 'k:focus') c.setFocus(focusLeft ? null : Date.now() + 25 * 60000)
    if (id === 'k:brief') {
      // the picture of the day: the board from the page's data at once, and Claude weighs exactly that data
      c.setCoreBrief(true)
      coreAsk(h.briefAsk(situationText(situation(s.model, tabs, Date.now()), Date.now(), lang)))
    }
    if (id === 'k:voice') voice.start()
  }
  // a click on the core opens its panel with the picture of the day as a board (the page's data, at once, free);
  // scan, Claude's verdict and speech join when chosen for it. A focus is never started by it: that is its own chip
  const runCore = () => {
    setSel('@core')
    setWave(n => n + 1)
    if (!on.has('k:brief')) c.setCoreBrief(true)
    for (const id of ['k:scan', 'k:brief', 'k:voice']) if (on.has(id)) runMode(id)
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
  const ids = catalog.map(x => x.id)
  const toggleMode = id => c.setHomeTiles(on.has(id) ? chosen.filter(x => x !== id) : [...chosen, id], ids)
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
  const greeting = `${h.greeting[greetingPart(now.getHours())]}${person ? `, ${person}` : ''}`
  const eyebrow = [h.stageName, now.toLocaleDateString(lang === 'de' ? 'de-DE' : 'en-GB', { weekday: 'long', day: 'numeric', month: 'long' }),
    now.toLocaleTimeString(lang === 'de' ? 'de-DE' : 'en-GB', { hour: '2-digit', minute: '2-digit' })].join(' · ')
  const working = tabs.filter(x => x.state === 'working' && !x.is_control).length
  const relayDown = s.relay?.enabled && !s.relay?.online
  const ticks = Array.from({ length: 72 }, (_, i) => i)
  const pctX = x => `${(x / STAGE.w * 100).toFixed(2)}%`
  const pctY = y => `${(y / STAGE.h * 100).toFixed(2)}%`
  return html`<section class=${`stage${s.loading?.pass ? ' is-scan' : ''}${focusLeft ? ' is-focus' : ''}${voice.listening ? ' is-listening' : ''}`} aria-label=${h.stageName}>
    <div class="stage-sky" aria-hidden="true">
      <svg viewBox="0 0 1000 560" preserveAspectRatio="xMidYMid slice" class="stage-svg">
        ${DUST.map((d, i) => html`<circle key=${i} cx=${d.x.toFixed(1)} cy=${d.y.toFixed(1)} r=${d.r.toFixed(2)} class="dust" style=${{ opacity: d.o.toFixed(2) }} />`)}
      </svg>
    </div>
    <div class="stage-term">
      <span class="stage-eyebrow">${eyebrow}</span>
      <${StagePrompt} s=${s} c=${c} greeting=${greeting} />
      ${s.model?.headline ? html`<p class="stage-lead">${leadOf(s.model)}</p>` : null}
      ${(s.model?.alarms ?? []).length || relayDown ? html`<div class="home-signals">
        ${(s.model?.alarms ?? []).map(a => html`<button type="button" class="home-signal tk-danger" key=${a.page_id + a.section_title}
          onClick=${() => c.setPage(a.page_id)}><${Dot} token="danger" /><span>${h.alarm(a.count, `${a.section_title} (${a.page_title})`)}</span></button>`)}
        ${relayDown ? html`<button type="button" class="home-signal tk-warning" onClick=${c.openClaude}>
          <${Dot} token="warning" /><span>${h.controlOffline}</span></button>` : null}
      </div>` : null}
      <div class="stage-tools">
        <${Btn} size="xs" variant=${edit ? 'primary' : 'ghost'} pressed=${edit} onClick=${() => setEdit(!edit)}>${edit ? h.chooseDone : h.choose}<//>
      </div>
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
          <text x=${STAGE.cx} y=${STAGE.cy + 7} class=${`core-name${focusLeft ? ' is-clock' : ''}`} text-anchor="middle">${focusLeft ?? 'Bridge'}</text>
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
        <div class="core-modes" role="group" aria-label=${h.coreModes}>
          <span class="core-modes-label">${h.coreModes}</span>
          ${['k:scan', 'k:brief', 'k:focus', 'k:voice'].filter(id => id !== 'k:voice' || voice.available).map(id => html`<span key=${id}
            class=${`core-mode${on.has(id) ? ' is-on' : ''}${id === 'k:focus' && focusLeft ? ' is-running' : ''}`}>
            <button type="button" class="core-mode-run" title=${h.modeRun(catalogLabel({ id }))}
              onClick=${() => runMode(id)}>${id === 'k:focus' && focusLeft ? h.focusRunning(focusLeft) : catalogLabel({ id })}</button>
            ${id === 'k:focus' ? null : html`<button type="button" class="core-mode-pin" aria-pressed=${String(on.has(id))} title=${on.has(id) ? h.modeInCore : h.modeNotInCore}
              aria-label=${on.has(id) ? h.modeInCore : h.modeNotInCore} onClick=${() => toggleMode(id)}></button>`}
          </span>`)}
        </div>
      </div>
      <div class="stage-side">
        ${sel === '@core' ? html`<${CoreInspector} s=${s} c=${c} onClose=${() => setSel(null)} voice=${voice} onAsk=${coreAsk} onWeigh=${() => runMode('k:brief')} />`
          : selIdx >= 0 ? html`<${StageInspector} x=${tiles[selIdx]} st=${stations[selIdx]} s=${s} c=${c} tabs=${tabs} onClose=${() => setSel(null)} />`
          : html`<${StageCard} s=${s} c=${c} tabs=${tabs} />`}
      </div>
    </div>
  </section>`
}

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

function HomePage({ s, c }) {
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
  const day = now.toLocaleDateString(lang === 'de' ? 'de-DE' : 'en-GB', { weekday: 'long', day: 'numeric', month: 'long' })
  const person = s.server?.person
  const workPage = (s.model?.pages ?? []).find(p => (p.sections ?? []).some(x => x.kind === 'tasks'))?.id ?? 'briefing'
  const relayDown = s.relay?.enabled && !s.relay?.online
  const catalog = homeCatalog(s.model, { workers: s.workers?.status !== 'none' })
  const chosen = homeChosen(s.model, s.home)
  const on = new Set(chosen)
  const starts = pageOrder(s).filter(id => id !== START_PAGE && !on.has(`p:${id}`))
  const pageBadge = id => (s.model?.pages ?? []).find(p => p.id === id)?.badge
  const byKey = indexRows(s.model)
  const pinned = (s.home?.pins ?? []).map(k => byKey.get(k)).filter(Boolean).filter(r => inProject(r, project))
  const [edit, setEdit] = useState(false)
  const chips = projects.length > 1 ? html`<div class="home-chips" role="toolbar" aria-label=${h.projectsLabel}>
      <button type="button" class=${`home-chip${project ? '' : ' is-on'}`} aria-pressed=${String(!project)} onClick=${() => c.setHomeProject(null)}>${h.all}</button>
      ${projects.map(p => html`<button type="button" key=${p} class=${`home-chip${project === p ? ' is-on' : ''}`} aria-pressed=${String(project === p)}
        onClick=${() => c.setHomeProject(project === p ? null : p)}><span class=${`home-chip-dot tk-${projectTone(p)}`} aria-hidden="true"></span>${p}</button>`)}
    </div>` : null
  const backs = returnsOf(s).filter(r => inProject(byKey.get(r.key) ?? {}, project) || !project)
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
      ${pinned.map(row => html`<${HomeRowCard} key=${row.key} row=${row} s=${s} c=${c} tab=${tabOfTask(tabs, row.task)} />`)}
    <//>` : null}
    ${on.has('s:continue') ? html`<${HomeShelf} id="home-continue" title=${h.continueTitle} count=${cont.length} empty=${h.continueEmpty}
      more=${h.seeAll(cont.length)} onMore=${cont.length > 8 ? () => c.setDrawer('tabs') : null}>
      ${cont.slice(0, 8).map(tab => html`<${HomeTabCard} key=${tab.ref} tab=${tab} s=${s} c=${c} preview=${on.has('o:preview')} />`)}
    <//>` : null}
    ${on.has('s:waiting') ? html`<${HomeShelf} id="home-waiting" title=${h.waitingTitle} count=${waiting.length} empty=${h.waitingEmpty}
      more=${h.seeAll(waiting.length)} onMore=${waiting.length > 6 ? () => c.setPage('briefing') : null}>
      ${waiting.slice(0, 6).map(row => html`<${HomeRowCard} key=${row.key} row=${row} s=${s} c=${c} tab=${tabOfTask(tabs, row.task)} />`)}
    <//>` : null}
    ${on.has('s:tasks') ? html`<${HomeShelf} id="home-tasks" title=${h.tasksTitle} count=${tasks.length} empty=${h.tasksEmpty}
      more=${h.seeAll(tasks.length)} onMore=${tasks.length > 8 ? () => c.setPage(workPage) : null}>
      ${tasks.slice(0, 8).map(row => html`<${HomeRowCard} key=${row.key} row=${row} s=${s} c=${c} tab=${tabOfTask(tabs, row.task)} />`)}
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
  if (!on.has('o:classic')) {
    return html`<div class=${`col col-page home bridge-home${s.ui.focusUntil && clockLeft(s.ui.focusUntil, s.now || Date.now()) ? ' in-focus' : ''}`}>
      <${BridgeStage} s=${s} c=${c} catalog=${catalog} chosen=${chosen} project=${project} edit=${edit} setEdit=${setEdit} />
      ${edit ? html`<${HomeChooser} c=${c} catalog=${catalog} chosen=${chosen} />` : null}
      ${daily}
      ${chips}
      ${shelves}
      ${diary}
    </div>`
  }
  return html`<div class="col col-page home">
    <header class="home-hero">
      <p class="home-eyebrow">${day}</p>
      <h1 class="home-title">${h.greeting[greetingPart(now.getHours())]}${person ? `, ${person}` : ''}.</h1>
      ${s.model?.headline ? html`<p class="home-lead">${leadOf(s.model)}</p>` : null}
      <${HomeAsk} s=${s} c=${c} />
      ${(s.model?.alarms ?? []).length || relayDown ? html`<div class="home-signals">
        ${(s.model?.alarms ?? []).map(a => html`<button type="button" class="home-signal tk-danger" key=${a.page_id + a.section_title}
          onClick=${() => c.setPage(a.page_id)}><${Dot} token="danger" /><span>${h.alarm(a.count, `${a.section_title} (${a.page_title})`)}</span></button>`)}
        ${relayDown ? html`<button type="button" class="home-signal tk-warning" onClick=${c.openClaude}>
          <${Dot} token="warning" /><span>${h.controlOffline}</span></button>` : null}
      </div>` : null}
    </header>
    ${chips}
    ${on.has('s:focus') ? html`<${HomeFocus} s=${s} c=${c} tabs=${tabs} />` : null}
    <${HomeOverview} s=${s} c=${c} catalog=${catalog} chosen=${chosen} project=${project} />
    ${daily}
    ${shelves}
    ${diary}
  </div>`
}

function PageView({ s, c }) {
  const t = T()
  const jev = useJevPage(!!(s.jev?.enabled && s.jev?.ready))
  if (s.ui.page === START_PAGE) return html`<${HomePage} s=${s} c=${c} />`
  if (s.ui.page === CHECK_PAGE) return html`<${ReviewPage} s=${s} c=${c} />`
  if (s.ui.page === SESSIONS_PAGE) return html`<${SessionsPage} s=${s} c=${c} />`
  if (s.ui.page === WORKERS_PAGE) return html`<${WorkersPage} s=${s} c=${c} />`
  if (s.ui.page === CHAT_PAGE) return html`<${ChatPage} s=${s} c=${c} />`
  if (s.ui.page === AGENTS_PAGE && (s.agents?.peers ?? []).length) return html`<${AgentsPage} s=${s} c=${c} />`
  const view = workViewNow(s)
  const work = view === 'due' ? null : workPageOf(s.model?.pages)
  if (view === 'jev') {
    const JevWork = jev?.JevWork
    // rows only the work page holds (an idea, a debrief point) stay in the picture by their key
    const extra = (work.sections ?? []).flatMap(sec => (s.more[`${work.id}/${sec.id}`]?.items ?? sec.items ?? []).map(triageKey)).filter(Boolean)
    return JevWork ? html`<${JevWork} s=${s} c=${c} page=${work} extra=${extra} top=${html`<${WorkSwitch} s=${s} c=${c} />`} />`
      : html`<div class="col col-page"><${WorkSwitch} s=${s} c=${c} /><div class="panel panel-pad"><p class="muted">${jev?.failed ? t.jevNotReady.load_failed : t.loading}</p></div></div>`
  }
  if (s.ui.page === JEV_PAGE && s.jev?.enabled) {
    const JevPage = jev?.JevPage
    return s.jev.ready && JevPage ? html`<${JevPage} s=${s} c=${c} />` : s.jev.ready ? html`<div class="col col-page"><div class="panel panel-pad"><p class="muted">${jev?.failed ? t.jevNotReady.load_failed : t.loading}</p></div></div>` : html`<div class="col col-page">
      <header class="page-head"><h2 class="detail-title">Jev</h2></header>
      <div class="panel panel-pad"><p><${StateLine} token="warning" strong word=${t.jevNotReady[s.jev.reason] ?? s.jev.reason} /></p>
        <p class="muted small">${t.jevHowTo}</p></div></div>`
  }
  const whole = work ?? (s.model?.pages ?? []).find(p => p.id === s.ui.page)
  if (!whole) return html`<div class="col col-page"><div class="panel panel-pad"><${Empty}>${t.pageEmpty}<//></div></div>`
  // a page with inbox and task rows filters by kind; everything below sees only the chosen sections
  const kinds = workKinds(whole.sections, t.workOrder.kinds)
  const kind = kinds.find(k => k.label === s.ui.workKind) ?? null
  // the task check stands under the tasks label of the page where inbox and tasks stand together; once it
  // has run, its table takes the place of the plain task list
  const home = reviewHomeOf(s)
  const checkHere = !!kind && home?.page === whole.id && home.label === kind.label && s.ui.workView !== 'jev'
  const checked = checkHere && !!s.model?.review?.last
  const seen = new Set(checked ? s.model.review.keys ?? [] : [])
  // a task the check has seen stands in its table; the plain list keeps only the ones it has not seen yet
  const unseen = sec => {
    const items = (s.more[`${whole.id}/${sec.id}`]?.items ?? sec.items ?? []).filter(it => !it.task || !seen.has(`task:${it.task}`))
    return { ...sec, items, total: items.length, more: 0, whole: true }
  }
  const page = kind ? { ...whole, sections: whole.sections.filter(sec => kind.sections.includes(sec.id))
    .map(sec => (checked && sec.kind === 'tasks' ? unseen(sec) : sec)) } : whole
  return html`<div class="col col-page">
    <header class="page-head">
      ${work ? html`<${WorkSwitch} s=${s} c=${c} />` : html`<h2 class="detail-title">${page.title}</h2>`}
      <${PageBadge} badge=${page.badge} />
    </header>
    ${page.overview ? html`<${OverviewBoard} page=${page} s=${s} c=${c} />` : null}
    ${kinds.length > 1 ? html`<${KindBar} kinds=${kinds} active=${kind} c=${c} />` : null}
    ${page.sections?.some(sec => sec.kind === 'tasks' || sec.kind === 'inbox') ? html`<${TriageBar} s=${s} c=${c} byKey=${indexRows(s.model)}
      items=${(kind ? whole.sections.filter(sec => kind.sections.includes(sec.id)) : whole.sections)
        .filter(sec => sec.kind === 'tasks' || sec.kind === 'inbox').flatMap(sec => s.more[`${whole.id}/${sec.id}`]?.items ?? sec.items ?? [])} />` : null}
    ${checkHere ? html`<${ReviewBody} s=${s} c=${c} inline />`
      : page.sections?.some(sec => sec.kind === 'tasks' && (sec.items ?? []).some(it => it.task)) ? html`<${ReviewStrip} s=${s} c=${c} />` : null}
    ${page.jev && !work && s.jev?.enabled && s.jev?.ready ? html`<${WorkOrder} page=${page} s=${s} c=${c} />` : null}
    ${page.jev && !work && s.jev?.enabled && s.jev?.ready && s.ui.workView === 'jev' && s.jevOrder[page.id]?.order ? html`<${JevList} page=${page} s=${s} c=${c} />`
      : (page.sections ?? []).length ? page.sections.map(sec => html`<${PageSection} key=${sec.id} page=${page} section=${sec} s=${s} c=${c} />`)
      : html`<div class="panel panel-pad"><${Empty}>${t.pageEmpty}<//></div>`}
    ${page.overview ? html`<${UsageCard} page=${page} s=${s} c=${c} />` : null}
  </div>`
}

// ---------------------------------------------------------------- sessions

/** What a session is doing, in one word: its tab's attention state wins over busy or idle */
function sessionState(x) {
  const tabState = x.tab?.state
  if (tabState === 'needs-you' || tabState === 'waiting') return [tabState, stateToken(tabState)]
  return [x.status, x.status === 'busy' ? 'success' : 'on-surface-muted']
}

/** One running subagent in the lane: it enters from the right edge and its bar reaches up to now */
function LaneBar({ a }) {
  const x0 = useTween(a.x0, { start: 1 })
  return html`<span class="lane-row"><span class=${`lane-bar${a.older ? ' is-older' : ''}`}
    style=${{ transform: `translateX(${(x0 * 100).toFixed(3)}%) scaleX(${Math.max(0.004, 1 - x0).toFixed(4)})` }}></span></span>`
}

/** The running subagents of a session over the last 10 to 60 minutes (laneWindow), one bar each, in the order of the list */
function AgentLane({ agents, now }) {
  const t = T()
  const span = laneWindow(agents, now)
  const lane = agentLane(agents, now, span)
  if (!lane.length) return null
  return html`<div class="lane" aria-hidden="true">
    ${lane.map(a => html`<${LaneBar} key=${a.id} a=${a} />`)}
    <span class="lane-axis mono"><span>${t.laneFrom(Math.round(span / 60000))}</span><span>${t.laneNow}</span></span>
  </div>`
}

function SessionCard({ x, i = 0, s, c }) {
  const t = T()
  const [state, token] = sessionState(x)
  const title = x.tab?.name || x.name
  const jump = x.tab ? () => c.act('tab_jump', { tab_ref: x.tab.ref }) : null
  const agents = x.agents ?? { running: [], running_count: 0, done_recent: 0 }
  const busy = x.tab ? !!s.ui.busy[x.tab.ref] : false
  const newAgent = useHits(agents.running_count, (a, b) => b > a)
  const alert = useHits(state, (a, b) => b === 'needs-you')
  return html`<li class=${`sess row-in${state === 'needs-you' ? ' is-alert' : state === 'busy' ? ' is-busy' : ''}`} style=${{ '--i': Math.min(i, 12) }}>
    ${alert ? html`<span class="hit hit-alert" key=${`a${alert}`} aria-hidden="true"></span>` : null}
    ${newAgent ? html`<span class="hit" key=${`n${newAgent}`} aria-hidden="true"></span>` : null}
    <div class="sess-head">
      <${StateLine} token=${token} strong=${state === 'needs-you'} word=${t.sessionStatus[state] ?? state} />
      <span class="muted small">${t.sessionSince(duration(s.now - (x.since_ms || s.now)))}</span>
      ${x.tab?.is_control ? html`<span class="chip">${t.sessionControl}</span>` : null}
      ${x.remote ? html`<span class="chip" title=${t.sessionRemote}>claude.ai</span>` : null}
      ${x.relay ? html`<${Chip} token="success" title=${t.sessionRelayTitle}>${t.sessionRelay}<//>` : null}
    </div>
    ${x.tab?.is_control && !x.relay ? html`<p class="small"><${StateLine} token="warning" word=${t.sessionControlNoRelay} /></p>` : null}
    ${jump ? html`<button type="button" class="sess-title btn-link" title=${t.sessionJumpTitle(title)} onClick=${jump}>${short(title, 70)}</button>`
      : html`<span class="sess-title">${short(title, 70)}</span>`}
    <div class="sess-where muted small">
      ${x.tab ? html`<span>${x.tab.workspace}</span>` : html`<span>${t.sessionNoTab}</span>`}
      <span class="mono">${x.id}</span>
      <span>${t.sessionStarted(duration(s.now - (x.started_ms || s.now)))}</span>
    </div>
    ${agents.running_count || agents.done_recent ? html`<div class="sess-agents">
      ${agents.running_count ? html`<span class="sess-count is-on"><${CountNum} value=${agents.running_count} cls="mono" /> ${t.agentsWord(agents.running_count)}</span>` : null}
      ${agents.done_recent ? html`<span class="muted small">${t.agentsDone(agents.done_recent)}</span>` : null}
    </div>` : null}
    <${AgentLane} agents=${agents.running} now=${s.now} />
    ${agents.running.length ? html`<ul class="sess-agent-list">${agents.running.map(a => html`<li key=${a.id} class="row-in">
        <${Dot} token="success" pulse />
        <span class="mono small">${a.type}</span>
        <span class="sess-agent-desc">${a.description ?? ''}</span>
        <span class="muted small">${t.agentFor(duration(s.now - a.since_ms))}${a.background ? ` · ${t.agentBackground}` : ''}</span>
      </li>`)}${agents.running_count > agents.running.length ? html`<li class="muted small">${t.moreAgents(agents.running_count - agents.running.length)}</li>` : null}</ul>` : null}
    ${(x.workflows ?? []).map((w, i) => html`<div class="small" key=${i}><${StateLine} token="info" word=${t.workflowLine(w.name, w.agents)} /></div>`)}
    <div class="btn-row sess-foot">
      ${jump ? html`<${Btn} size="xs" variant="secondary" busy=${busy} onClick=${jump}>${t.sessionJump}<//>` : null}
      <${SessionTask} x=${x} s=${s} c=${c} />
    </div>
  </li>`
}

/** The open tasks a session can belong to: every task row of the briefing and of the pages, by slug */
function openTasks(s) {
  const out = new Map()
  for (const r of indexRows(s.model).values()) if (r.task && !r.inbox_id && !out.has(r.task)) out.set(r.task, r.title)
  for (const p of s.model?.pages ?? []) for (const sec of p.sections ?? []) {
    if (sec.kind !== 'tasks') continue
    for (const it of sec.items ?? []) if (it.task && !out.has(it.task)) out.set(it.task, it.title)
  }
  return [...out].map(([slug, title]) => ({ slug, title })).sort((a, b) => a.slug.localeCompare(b.slug))
}

/** Which task a session works on: a task tab links itself, any other is linked here by hand */
function SessionTask({ x, s, c }) {
  const t = T()
  if (!x.sid) return null
  const tasks = openTasks(s)
  return html`<span class="sess-task small">
    ${x.task ? html`<span class="chip chip-task" title=${t.sessionTaskTitle}>${t.sessionTask(x.task)}</span>
      <button type="button" class="btn-link small" onClick=${() => c.act('session_unlink', { session: x.sid })}>${t.sessionUnlink}</button>`
      : html`<select class="input input-sm sess-task-pick" aria-label=${t.sessionLinkLabel} title=${t.sessionLinkLabel}
          onChange=${e => { const slug = e.currentTarget.value; if (slug) c.act('session_link', { session: x.sid, slug }) }}>
          <option value="">${t.sessionLinkLabel}</option>
          ${tasks.map(k => html`<option key=${k.slug} value=${k.slug}>${short(k.title || k.slug, 48)}</option>`)}
        </select>`}
  </span>`
}

/** A task's sessions: the live ones lead to their tab, an ended one goes on in a new tab (claude --resume) */
function TaskSessions({ row, s, c }) {
  const t = T()
  if (!row.task) return null
  const links = (s.sessions?.links ?? []).filter(l => l.task === row.task)
  if (!links.length) return null
  const live = new Map((s.sessions?.sessions ?? []).map(x => [x.sid, x]))
  return html`<div class="sub-block">
    <h4 class="sub-title">${t.taskSessions(links.length)}</h4>
    <ul class="plain task-sessions">${links.slice(0, 6).map(l => {
      const x = live.get(l.sid)
      return html`<li key=${l.sid} class="row-in">
        <${StateLine} token=${x ? 'success' : 'on-surface-muted'} word=${x ? t.sessionLive : t.sessionEnded} />
        <span class="task-session-name">${short(l.name || l.sid.slice(0, 8), 60)}</span>
        ${x?.tab ? html`<${Btn} size="xs" variant="secondary" onClick=${() => c.act('tab_jump', { tab_ref: x.tab.ref })}>${t.btnToTab}<//>`
          : x ? null : html`<${Btn} size="xs" variant="secondary" busy=${!!s.ui.busy[row.key]} onClick=${() => c.act('session_resume', { session: l.sid })}>${t.sessionResume}<//>`}
      </li>`
    })}</ul>
  </div>`
}

/** Every running Claude Code session, grouped by project, this Bridge first */
function SessionsPage({ s, c }) {
  const t = T()
  const list = s.sessions?.sessions ?? []
  const groups = []
  for (const x of list) {
    const g = groups.find(g => g.project === x.project && g.here === x.here)
    if (g) g.items.push(x)
    else groups.push({ project: x.project, here: x.here, items: [x] })
  }
  const busy = list.filter(x => x.status === 'busy').length
  const agents = list.reduce((n, x) => n + (x.agents?.running_count ?? 0), 0)
  return html`<div class="col col-page">
    <header class="page-head">
      <h2 class="detail-title">${t.sessionsTitle}</h2>
      <${StartControl} s=${s} c=${c} size="sm" />
    </header>
    ${list.length ? html`<dl class="stats" aria-label=${t.sessionsSummary(list.length, busy, agents)}>
      <div><dt>${t.statSessions}</dt><dd><${CountNum} value=${list.length} /></dd></div>
      <div><dt>${t.statBusy}</dt><dd><${CountNum} value=${busy} /></dd></div>
      <div><dt>${t.statAgents}</dt><dd><${CountNum} value=${agents} /></dd></div>
    </dl>` : null}
    ${canStartControl(s) ? html`<p class="sess-intro"><${StateLine} token="warning" word=${t.relayReason[s.relay.reason]} /></p>` : null}
    <p class="muted small sess-intro">${t.sessionsIntro}</p>
    ${!list.length ? html`<div class="panel panel-pad"><${Empty}>${t.sessionsEmpty}<//></div>` : html`<div class="sess-groups">${groups.map(g => html`<section class="panel panel-pad psec" key=${`${g.here}/${g.project}`}
      style=${{ flex: `${g.items.length} 1 ${Math.min(g.items.length, 3) * 330}px` }}>
      <header class="psec-head"><h3 class="sec-title">${g.project}${g.here ? html` <span class="chip">${t.sessionHere}</span>` : null}
        <span class="sec-count mono">${g.items.length}</span></h3></header>
      <ul class="sess-grid">${g.items.map((x, i) => html`<${SessionCard} key=${x.pid} x=${x} i=${i} s=${s} c=${c} />`)}</ul>
    </section>`)}</div>`}
  </div>`
}

// ---------------------------------------------------------------- workers (workload view --json)

/** The run's day on a 24 hour line: its appointments as dots, the last recorded run as a triangle,
 *  now as a line. A run without appointments (a daemon, a watcher) says what it is instead */
function DayAxis({ day, nowPct }) {
  const marks = day?.marks ?? []
  if (!marks.length && day?.trace_pct == null) return html`<span class="dayaxis-note">${dayNoteText(day?.note, language())}</span>`
  return html`<span class="dayaxis" aria-hidden="true">
    <span class="dayaxis-line"></span>
    ${[25, 50, 75].map(q => html`<span class="dayaxis-q" key=${q} style=${{ '--p': q / 100 }}></span>`)}
    ${marks.slice(0, 48).map((m, i) => html`<span class="dayaxis-m" key=${i} title=${m.label} style=${{ '--p': (m.at_pct ?? 0) / 100 }}></span>`)}
    ${day?.trace_pct != null ? html`<span class="dayaxis-t" title=${dayNoteText(day.trace_label, language())} style=${{ '--p': day.trace_pct / 100 }}></span>` : null}
    <span class="dayaxis-now" style=${{ '--p': nowPct }}></span>
  </span>`
}

function RunStrip({ strip, continuous }) {
  const t = T()
  const last = (strip ?? []).slice(-14)
  if (!last.length) return html`<span class="muted small">${t.workerNoRuns}</span>`
  return html`<span class="strip" title=${continuous ? t.workerContinuous : t.workerStrip(last.length)}>
    ${last.map((e, i) => { const [shape, tone] = stripMark(e); return html`<span key=${i} class=${`strip-m sm-${tone}`} title=${`${e.at ?? ''} ${e.verdict ?? ''}`}>${shape}</span>` })}</span>`
}

function WorkerRow({ r, nowPct, c, i }) {
  const t = T()
  const [open, setOpen] = useState(false)
  const tone = workerTone(r)
  const top = (r.findings ?? []).find(serious) ?? (r.findings ?? [])[0]
  const days = weekdayNames(language())
  const week = r.week?.length === 7 ? [...r.week.slice(1), r.week[0]] : []
  return html`<li class=${`wrow rt-${tone} row-in${open ? ' is-open' : ''}`} style=${{ '--i': Math.min(i, 16) }}>
    <button type="button" class="wrow-main" aria-expanded=${String(open)} onClick=${() => setOpen(!open)}>
      <span class=${`rdot rdot-${tone}`} aria-hidden="true"></span>
      <span class="wrow-name"><strong>${r.title || r.id}</strong><span class="muted small">${r.purpose ?? ''}</span></span>
      <span class="wrow-when"><span class="small" title=${r.when ?? ''}>${scheduleText(r.when, language())}</span><${DayAxis} day=${r.day} nowPct=${nowPct} /></span>
      <span class="wrow-strip"><${RunStrip} strip=${r.strip} continuous=${r.continuous} /></span>
      <span class="wrow-state"><span class=${`chip chip-tk tk-${runToken(tone)}`}>
        <${Dot} token=${runToken(tone)} /><span>${t.workerState[r.state] ?? r.state}</span></span></span>
    </button>
    ${open ? html`<div class="wrow-detail">
      <dl class="wmeta">
        ${[['unit', r.unit], ['host', r.host], ['kind', t.workerKind[r.kind] ?? r.kind], ['runtime', r.runtime], ['sphere', r.sphere], ['owner', r.owner],
          ['program', r.program ? `${r.program}${r.program_where ? ` (${r.program_where})` : ''}` : ''], ['log', r.log]]
          .filter(([, v]) => v).map(([k, v]) => html`<div key=${k}><dt>${t.workerField[k]}</dt><dd class="mono small">${v}</dd></div>`)}
      </dl>
      ${week.length ? html`<div class="wweek" aria-label=${t.workerWeek}>${week.map((on, k) => html`<span key=${k} class=${`wday${on ? ' is-on' : ''}`}>${days[k]}</span>`)}
        ${(r.ran_days ?? []).length ? html`<span class="muted small">${t.workerRanDays(r.ran_days.length)}</span>` : null}</div>` : null}
      ${(r.findings ?? []).some(f => f.severity !== 'info') ? html`<ul class="wfind">${r.findings.filter(f => f.severity !== 'info').map((f, k) => html`<li key=${k}>
        <${StateLine} token=${f.severity === 'high' ? 'danger' : f.severity === 'medium' ? 'warning' : 'info'} strong=${f.severity === 'high'}
          word=${`${t.workerState[f.state] ?? f.state}: ${f.detail ?? ''}`} />
        ${f.hint ? html`<p class="muted small wfind-hint">${t.workerHint(f.hint)}</p>` : null}</li>`)}</ul>` : null}
      <div class="btn-row">
        <${Btn} size="xs" variant="secondary" onClick=${() => c.ask('free', { text: t.workerAsk(r.id, r.host, t.workerState[r.state] ?? r.state, top?.detail ?? '') })}>${t.btnAsk}<//>
      </div>
    </div>` : null}
  </li>`
}

/** Every declared run of the always-on machines, drawn by this page from `workload view --json` */
function WorkersPage({ s, c }) {
  const t = T()
  const w = s.workers ?? {}
  useEffect(() => { c.loadWorkers() }, [s.model?.seq ?? 0])
  const [flt, setFlt] = useState(() => ({ q: '', kind: null, sphere: null, state: null, host: null, attention: false, ...(s.ui.workersFilter ?? {}) }))
  const view = w.data
  const runs = (view?.runs ?? []).filter(r => !r.retired)
  const shown = filterWorkers(runs, flt)
  const facets = workerFacets(runs, flt)
  const groups = groupBySystem(shown, view?.systems)
  const now = new Date()
  const nowPct = (now.getHours() * 60 + now.getMinutes()) / 1440
  const at = Date.parse(view?.generated_at ?? '')
  const set = patch => setFlt(f => ({ ...f, ...patch }))
  const facetRow = name => {
    const vals = Object.entries(facets[name] ?? {}).sort((a, b) => b[1] - a[1])
    if (vals.length < 2 && !flt[name]) return null
    return html`<div class="wfacet"><span class="label-caps">${t.workerFacet[name]}</span>
      <span class="fbar-chips">${vals.map(([v, n]) => html`<button type="button" key=${v} class=${`fchip${flt[name] === v ? ' is-on' : ''}`}
        aria-pressed=${String(flt[name] === v)} onClick=${() => set({ [name]: flt[name] === v ? null : v })}>
        ${name === 'state' ? html`<span class=${`fdot fdot-${workerTone({ state: v })}`} aria-hidden="true"></span>` : null}
        ${name === 'state' ? (t.workerState[v] ?? v) : name === 'kind' ? (t.workerKind[v] ?? v) : v} <span class="mono">${n}</span></button>`)}</span></div>`
  }
  return html`<div class="col col-page">
    <header class="page-head">
      <h2 class="detail-title">${t.workersTab}</h2>
      ${view ? html`<span class="muted small">${t.workersFrom(view.host, Number.isFinite(at) ? formatClock(at, language()).slice(0, 5) : '?')}</span>` : null}
      <button type="button" class="btn-link small" onClick=${() => c.loadWorkers()}>${t.reload}</button>
    </header>
    ${w.status === 'none' ? html`<div class="panel panel-pad"><p class="muted">${t.workersNone}</p></div>` : !view
      ? html`<div class="panel panel-pad"><${Skeleton} lines=${6} /></div>` : html`
      <dl class="stats">
        <div><dt>${t.workerStat.in_service}</dt><dd><${CountNum} value=${view.stats?.in_service ?? runs.length} /></dd></div>
        <div><dt>${t.workerStat.with_findings}</dt><dd><${CountNum} value=${view.stats?.with_findings ?? 0} /></dd></div>
        <div><dt>${t.workerStat.not_reported}</dt><dd><${CountNum} value=${view.stats?.not_reported ?? 0} /></dd></div>
        <div><dt>${t.workerStat.retired}</dt><dd><${CountNum} value=${view.stats?.retired ?? 0} /></dd></div>
      </dl>
      <section class="panel panel-pad wfilters">
        <div class="fbar">
          <input class="input fbar-q" type="search" placeholder=${t.filterSearch} aria-label=${t.filterSearch} value=${flt.q}
            onInput=${e => set({ q: e.currentTarget.value })} />
          <button type="button" class=${`fchip${flt.attention ? ' is-on' : ''}`} aria-pressed=${String(flt.attention)}
            onClick=${() => set({ attention: !flt.attention })}><span class="fdot fdot-warn" aria-hidden="true"></span>${t.workerAttention}</button>
          <span class="muted small">${t.workersShown(shown.length, runs.length)}</span>
        </div>
        ${['state', 'kind', 'sphere', 'host'].map(facetRow)}
      </section>
      ${!shown.length ? html`<div class="panel panel-pad"><${Empty}>${t.filterNone}<//></div>` : groups.map(g => {
        const n = k => g.runs.filter(r => workerTone(r) === k).length
        return html`<section class="panel panel-pad wgroup" key=${g.id}>
          <header class="rgroup-head"><h3 class="rgroup-title">${g.id === '_standalone' || !g.title ? t.workerAlone : g.id === '_undecided' ? t.workerUndecided : g.title}</h3>
            <span class="sec-count mono">${g.runs.length}</span>
            <span class="rgroup-count">${['ok', 'warn', 'bad', 'dim'].filter(k => n(k)).map(k => html`
              <span key=${k} class="rgroup-n"><span class=${`fdot fdot-${k}`} aria-hidden="true"></span><span class="mono">${n(k)}</span></span>`)}</span>
          </header>
          <ul class="wlist rview">${g.runs.map((r, i) => html`<${WorkerRow} key=${r.id} r=${r} i=${i} nowPct=${nowPct} c=${c} />`)}</ul>
        </section>`
      })}
      ${(view.elsewhere?.undeclared?.counted ?? 0) ? html`<p class="muted small">${t.workersElsewhere(view.elsewhere.undeclared.counted)}</p>` : null}`}
  </div>`
}

// ---------------------------------------------------------------- task check

/** The drawn check (DESIGN.md form 3): tasks, the model tiers, the verdicts, as stations on one rail.
 *  The stations are the resting state; light points run on the first rail while a check runs, and a
 *  finished check sends one packet along the whole rail to the verdicts, which light up once */
function CheckFlow({ s }) {
  const t = T()
  const lang = language()
  const rv = s.model?.review ?? {}
  const flow = checkFlow(rv.last)
  const running = rv.running
  const arrivals = useHits(rv.last?.reviewed_at, (a, b) => !!b && !running)
  const arrivedAt = useRef(null)
  const seen = useRef(arrivals)
  if (arrivals !== seen.current) { seen.current = arrivals; arrivedAt.current = nowSec() }
  const since = arrivedAt.current == null ? Infinity : nowSec() - arrivedAt.current
  const now = useClock(!!running || since < 3)
  const dt = arrivedAt.current == null ? Infinity : now - arrivedAt.current
  const stations = flow ? [
    { id: 'tasks', label: t.flowTasks, n: flow.total, sub: flow.cached ? t.flowCached(flow.cached) : null },
    ...flow.tiers.map(x => ({ id: x.model, mono: true, label: x.model, n: x.answered,
      sub: `${t.flowAnswered} · ${x.cost_ct == null ? t.flowCostUnknown : t.reviewCost(centsText(x.cost_ct, lang), true)}`,
      exception: x.fromPrev })),
    { id: 'verdicts', label: t.flowVerdicts, n: flow.total, end: true,
      sub: (rv.keys ?? []).length < flow.total ? t.flowClosedSince(flow.total - (rv.keys ?? []).length) : null },
  ] : []
  const rails = Math.max(0, stations.length - 1)
  const STEP = 0.55
  const glow = flash(dt, [rails * STEP], 2.2)
  const prog = runProgress(running, Date.now(), rv.last?.duration_sec)
  const points = running ? flowPoints(now, 3) : []
  const railDots = i => {
    if (running) return i === 0 ? points.map(u => [u, flowAlpha(u)]) : []
    if (dt > rails * STEP + 0.4) return []
    const u = Math.min(1, Math.max(0, (dt - i * STEP) / STEP))
    return u > 0 && u < 1 ? [[u, flowAlpha(u)]] : []
  }
  if (!flow && !running) return null
  return html`<div class="flow-wrap">
    ${flow ? html`<ol class="flow" aria-label=${t.flowLabel}>
      ${stations.map((st, i) => html`
        ${i > 0 ? html`<li class=${`flow-rail${st.exception ? ' is-exception' : ''}`} aria-hidden=${st.exception ? undefined : 'true'} key=${`r${i}`}>
          <span class="flow-line"></span><span class="flow-arrow"></span>
          ${railDots(i - 1).map(([u, a], k) => html`<span class="flow-dot" key=${k} style=${{ '--u': u.toFixed(4), opacity: a.toFixed(3) }}></span>`)}
          ${st.exception ? html`<span class="flow-rail-label mono">${t.flowUnclear}</span>` : null}
        </li>` : null}
        <li class=${`flow-st${st.end ? ' is-end' : ''}`} key=${st.id}>
          ${st.end && glow > 0.01 ? html`<span class="flow-glow" aria-hidden="true" style=${{ opacity: glow.toFixed(3) }}></span>` : null}
          <span class=${`flow-st-label${st.mono ? ' mono' : ' label-caps'}`}>${st.label}</span>
          <${CountNum} value=${st.n} cls="flow-num" />
          ${st.sub ? html`<span class="muted small">${st.sub}</span>` : null}
          ${st.end && rv.last?.to_close ? html`<${StateLine} token="danger" strong word=${t.reviewToClose(rv.last.to_close)} />` : null}
        </li>`)}
    </ol>` : null}
    ${prog ? html`<div class="flow-progress">
      <span class="flow-track" aria-hidden="true"><span class="flow-fill" style=${{ transform: `scaleX(${prog.frac.toFixed(4)})` }}></span></span>
      <span class="muted small">${t.flowRunning(Math.round(prog.sec), Math.round(prog.expected))}${prog.over ? ` · ${t.flowOver}` : ''}</span>
    </div>` : null}
  </div>`
}

/** One verdict's share of the bar: grows from the left on the first show, glides when the counts change */
function VerdictSeg({ verdict, seg, onPick, title }) {
  const x = useTween(seg ? seg.x : 1, { start: 0 })
  const w = useTween(seg ? seg.w : 0, { start: 0 })
  if (w < 0.0005) return null
  return html`<span class=${`vbar-seg vs-${verdict}`} title=${title} onClick=${onPick}
    style=${{ transform: `translateX(${(x * 100).toFixed(3)}%) scaleX(${w.toFixed(5)})` }}></span>`
}

/** The verdicts as one bar in verdict order; the filter buttons below carry the words and the keyboard */
function VerdictBar({ counts, c }) {
  const t = T()
  const segs = verdictSegments(counts)
  if (!segs.length) return null
  return html`<div class="vbar" aria-hidden="true">${VERDICT_ORDER.map(v => {
    const seg = segs.find(x => x.verdict === v)
    return html`<${VerdictSeg} key=${v} verdict=${v} seg=${seg} title=${seg ? `${t.verdictName[v]} ${seg.n}` : ''}
      onPick=${() => c.setReview({ rvFilter: v })} />`
  })}</div>`
}

/** "Check tasks"; while a check runs it says so with the seconds, the server allows one at a time */
function CheckButton({ s, c, size = 'sm', variant = 'secondary' }) {
  const t = T()
  const running = s.model?.review?.running
  const sec = running ? Math.max(0, Math.round((s.now - running.started_ms) / 1000)) : 0
  return html`<${Btn} size=${size} variant=${variant} disabled=${!!running} busy=${!!s.ui.busy.task_review}
    onClick=${() => c.review()}>${running ? t.reviewing(sec) : t.btnReviewAll}<//>`
}

function reviewStripText(s) {
  const t = T()
  const last = s.model?.review?.last
  if (!last) return null
  const lang = language()
  const at = Date.parse(last.reviewed_at ?? '')
  const when = Number.isFinite(at) ? formatDay(isoDate(at), lang) + ' ' + formatClock(at, lang).slice(0, 5) : ''
  return t.reviewStrip(last.reviewed ?? 0, t.reviewCost(centsText(last.cost_ct, lang), last.cost_known),
    (last.models ?? []).join(', ') || '-', Math.round(last.duration_sec ?? 0), when)
}

/** On a page that lists tasks: the check in one line, and the way to its overview */
function ReviewStrip({ s, c }) {
  const t = T()
  const rv = s.model?.review ?? {}
  const toClose = rv.last?.to_close ?? 0
  return html`<div class="panel panel-pad review-strip">
    <${CheckButton} s=${s} c=${c} size="xs" />
    ${rv.last ? html`<span class="muted small">${reviewStripText(s)}</span>` : html`<span class="muted small">${t.rvNoRun}</span>`}
    ${toClose ? html`<${StateLine} token="danger" strong word=${t.reviewToClose(toClose)} />` : null}
    ${rv.last ? html`<button type="button" class="btn-link" onClick=${() => c.openReview()}>${t.reviewOpen}</button>` : null}
  </div>`
}

/** In a task's detail: the recommendation with its reason and evidence, and what to do about it */
function ReviewBlock({ row, s, c }) {
  const t = T()
  const rv = row.review
  const running = !!s.model?.review?.running
  const busy = !!s.ui.busy[row.key]
  const closer = s.model?.review?.last?.escalate_ct
  return html`<div class="sub-block review-block">
    <h4 class="sub-title">${t.reviewTitle}</h4>
    ${rv ? html`<div class="review-rec">
        <div class="review-head">
          <${StateLine} token=${verdictToken(rv.verdict)} strong word=${t.verdictName[rv.verdict] ?? rv.verdict} />
          <span class="muted small conf" title=${t.confidence[rv.confidence] ?? ''}>${confidenceDots(rv.confidence)} ${t.confidence[rv.confidence] ?? ''}</span>
          ${rv.model ? html`<span class="muted small mono">${String(rv.model).replace('claude-', '')}</span>` : null}
          ${rv.kept ? html`<span class="chip">${t.keptMark}</span>` : null}
          ${rv.changed && rv.previous_verdict ? html`<span class="chip chip-active">${t.changedMark(t.verdictName[rv.previous_verdict] ?? rv.previous_verdict)}</span>` : null}
        </div>
        ${rv.reason ? html`<p class="review-reason">${rv.reason}</p>` : null}
        ${(rv.closed_refs ?? []).length ? html`<p class="small"><${StateLine} token="success" word=${t.signalClosed(rv.closed_refs.join(', '))} /></p>` : null}
        ${(rv.chips ?? []).length ? html`<div class="chip-row">${rv.chips.map((ch, i) => html`<span class="chip" key=${i}>${t.chip(ch)}</span>`)}</div>` : null}
      </div>`
      : html`<p class="muted small">${t.reviewNone}</p>`}
    <div class="btn-row">
      ${row.closable ? html`<${Btn} size="xs" variant=${rv?.verdict === 'close' || rv?.resolved ? 'danger-solid' : 'danger'} busy=${busy}
        onClick=${() => c.askClose([row])}>${t.btnCloseTask}<//>` : null}
      ${rv && rv.verdict !== 'continue' && !rv.kept ? html`<${Btn} size="xs" variant="secondary" busy=${busy} disabled=${running}
        onClick=${() => c.keep([row.key])}>${t.btnKeep}<//>` : null}
      <${Btn} size="xs" variant="secondary" disabled=${running} busy=${busy} onClick=${() => c.review([row.key], false, !!rv)}>
        ${running ? t.reviewing(Math.max(0, Math.round((s.now - s.model.review.running.started_ms) / 1000))) : rv ? t.btnCheckAgain : t.btnCheckOne}<//>
      ${rv && closer != null && (rv.verdict === 'unclear' || rv.confidence === 'low') ? html`<${Btn} size="xs" variant="secondary" disabled=${running} busy=${busy}
        onClick=${() => c.review([row.key], true)}>${t.btnCheckCloser(t.reviewCost(centsText(closer, language()), true))}<//>` : null}
    </div>
  </div>`
}

/** The overview of the last check: filter per verdict, sort, select, act on many at once (reads only the last run) */
function ReviewPage({ s, c }) {
  const t = T()
  return html`<div class="col col-page">
    <header class="page-head">
      <h2 class="detail-title">${t.reviewTitle}</h2>
      <${CheckButton} s=${s} c=${c} variant="primary" />
    </header>
    <${ReviewBody} s=${s} c=${c} />
  </div>`
}

/** The check itself: its run, the verdict filter and sort, what is picked, the table. Its own tab, or the
 *  tasks label of the page where inbox and tasks stand together (then with the run button on top) */
function ReviewBody({ s, c, inline = false }) {
  const t = T()
  const byKey = indexRows(s.model)
  const rv = s.model?.review ?? {}
  const all = (rv.keys ?? []).map(k => byKey.get(k)).filter(r => r?.review)
  const counts = verdictCounts(all)
  const filter = s.ui.rvFilter in counts ? s.ui.rvFilter : 'all'
  const rows = reviewRows(all, filter, s.ui.rvSort)
  const picked = s.ui.rvPicked.filter(k => byKey.has(k))
  const pickedRows = picked.map(k => byKey.get(k))
  const closable = pickedRows.filter(r => r.closable)
  const running = !!rv.running
  const lang = language()
  const allShown = rows.length > 0 && rows.every(r => picked.includes(r.key))
  const filters = [['all', t.filterAll], ...VERDICT_ORDER.map(v => [v, t.verdictName[v]]), ['changed', t.filterChanged]]
    .filter(([id]) => id === 'all' || counts[id] > 0)
  return html`
    <div class="panel panel-pad review-top">
      ${inline ? html`<header class="psec-head"><h2 class="sec-title">${t.reviewTitle}</h2><${CheckButton} s=${s} c=${c} size="xs" /></header>` : null}
      <p class="muted small">${t.reviewIntro}</p>
      <${CheckFlow} s=${s} />
      ${rv.last ? html`<p class="small">${reviewStripText(s)}${rv.last.mismatch ? html` · <${StateLine} token="warning" word=${t.reviewMismatch} />` : null}</p>` : null}
      ${rv.error ? html`<p><${StateLine} token="danger" strong word=${t.reviewFailedLine(rv.error)} /></p>` : null}
      ${all.length ? html`<${VerdictBar} counts=${counts} c=${c} /><div class="review-bar" role="group" aria-label=${t.rvCol.verdict}>
          ${filters.map(([id, label]) => html`<button key=${id} type="button" aria-pressed=${String(filter === id)}
            class=${`btn btn-xs ${filter === id ? 'btn-primary' : 'btn-secondary'}`} onClick=${() => c.setReview({ rvFilter: id })}>
            ${id !== 'all' && id !== 'changed' ? html`<${Dot} token=${verdictToken(id)} />` : null}
            <span class="btn-label">${label} <span class="mono">${counts[id]}</span></span></button>`)}
        </div>
        <${Segmented} label=${t.sortLabel} current=${s.ui.rvSort}
          values=${['verdict', 'priority', 'activity'].map(v => [v, t.sortBy[v]])} onPick=${v => c.setReview({ rvSort: v })} />` : null}
    </div>
    ${picked.length ? html`<div class="panel panel-pad review-bulk" role="toolbar" aria-label=${t.bulkLabel(picked.length)}>
      ${closable.length ? html`<${Btn} size="xs" variant="danger" onClick=${() => c.askClose(closable)}>${t.bulkClose(closable.length)}<//>` : null}
      <${Btn} size="xs" variant="secondary" disabled=${running} busy=${!!s.ui.busy[picked.join(',')]} onClick=${() => c.keep(picked)}>${t.bulkKeep(picked.length)}<//>
      <${Btn} size="xs" variant="secondary" disabled=${running} onClick=${() => c.review(picked, true)}>
        ${t.bulkCloser(picked.length, t.reviewCost(centsText(rv.last?.escalate_ct, lang), rv.last?.escalate_ct != null))}<//>
      <${Btn} size="xs" variant="secondary" onClick=${() => c.act('advise', { keys: picked })}>${t.bulkStart(picked.length)}<//>
      <button type="button" class="btn-link" onClick=${() => c.setReview({ rvPicked: [] })}>${t.bulkClear}</button>
    </div>` : null}
    <section class="panel panel-pad psec">
      ${!rv.last ? html`<${Empty}>${t.rvNoRun}<//>` : !rows.length ? html`<${Empty}>${t.rvEmpty}<//>` : html`<div class="table-wrap" tabindex="0" role="region" aria-label=${t.reviewTitle}>
        <table class="tbl tbl-review">
          <thead><tr>
            <th scope="col" class="c-pick"><input type="checkbox" checked=${allShown} aria-label=${t.selectAll}
              onChange=${() => c.setReview({ rvPicked: allShown ? picked.filter(k => !rows.some(r => r.key === k)) : [...new Set([...picked, ...rows.map(r => r.key)])] })} /></th>
            <th scope="col">${t.rvCol.task}</th><th scope="col">${t.rvCol.verdict}</th><th scope="col" class="c-quiet">${t.rvCol.quiet}</th>
            <th scope="col">${t.rvCol.evidence}</th><th scope="col">${t.rvCol.reason}</th>
          </tr></thead>
          <tbody>${rows.map((r, i) => html`<tr key=${r.key} class=${`row-in${r.review.kept ? ' is-kept' : ''}`} style=${{ '--i': Math.min(i, 12) }}>
            <td class="c-pick"><input type="checkbox" checked=${picked.includes(r.key)} aria-label=${t.rvPick(short(r.title, 40))}
              onChange=${() => c.toggleRvPick(r.key)} /></td>
            <td class="c-task"><button type="button" class="btn-link info-open" title=${t.openDetail} onClick=${e => c.peek(r.key, e.currentTarget)}>${short(r.title, 80)}</button>
              <span class="row-meta"><${PrioChip} priority=${r.priority} />${r.area ? html`<span class="meta-area">${r.area}</span>` : null}</span></td>
            <td class="c-verdict"><${StateLine} token=${verdictToken(r.review.verdict)} strong=${r.review.verdict === 'close'} word=${t.verdictName[r.review.verdict]} />
              <span class="muted small conf" title=${t.confidence[r.review.confidence] ?? ''}>${confidenceDots(r.review.confidence)}</span>
              ${r.review.kept ? html`<span class="chip">${t.keptMark}</span>` : null}
              ${r.review.changed && r.review.previous_verdict ? html`<span class="chip chip-active">${t.changedMark(t.verdictName[r.review.previous_verdict] ?? r.review.previous_verdict)}</span>` : null}</td>
            <td class="c-quiet mono">${t.rvDays(r.review.days_since_activity)}</td>
            <td><span class="chip-row">${(r.review.chips ?? []).map((ch, i) => html`<span class="chip" key=${i}>${t.chip(ch)}</span>`)}</span></td>
            <td class="c-reason">${r.review.reason}</td>
          </tr>`)}</tbody>
        </table>
      </div>`}
    </section>`
}

// ---------------------------------------------------------------- overlays

function Toasts({ s, c }) {
  const t = T()
  return html`<div class="toasts" role="status" aria-live="polite" aria-atomic="false">
    ${s.toasts.map(x => html`<div class="toast" key=${x.id}>
      <${Dot} token=${noteToken(x.tone)} />
      <span class="toast-text">${x.text}</span>
      ${x.action === 'undo' && x.undo?.length ? html`<${Btn} size="xs" variant="primary"
          onClick=${() => { c.dismissToast(x.id); x.undo.forEach(u => c.undo(u.undo)) }}>${T().undoToast}<//>` : null}
      ${x.action === 'agent' ? html`<${Btn} size="xs" variant="primary" onClick=${() => { c.dismissToast(x.id); c.openAgentConv(x.conv) }}>${t.btnTabView}<//>` : null}
      ${x.action === 'claude' || x.action === 'ask' ? html`<${Btn} size="xs" variant="primary"
          onClick=${() => { c.dismissToast(x.id); x.action === 'ask' ? c.openAsk(x.conv) : c.openClaude() }}>${t.btnTabView}<//>`
        : html`<span class="mono muted small">${x.at}</span>`}
      <button type="button" class="icon-btn" aria-label=${t.close} onClick=${() => c.dismissToast(x.id)}><${Icon} name="close" size=${14} /></button>
    </div>`)}
  </div>`
}

const FOCUSABLE = 'button:not([disabled]), [href], input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'

/**
 * An aria-modal dialog keeps the focus: it moves in on open, Tab and Shift+Tab cycle inside it,
 * and on close it goes back to the element that opened the dialog.
 */
function useFocusOnOpen(open) {
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

function Drawer({ title, onClose, children, side = 'right', id }) {
  const t = T()
  const ref = useFocusOnOpen(true)
  return html`<div class="overlay" onClick=${e => { if (e.target === e.currentTarget) onClose() }}>
    <aside class=${`drawer drawer-${side}`} role="dialog" aria-modal="true" aria-labelledby=${`${id}-title`} ref=${ref}>
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
function rowClickOpens(e) {
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

/** The task an inbox item belongs to, in three lines, and the way into it */
function ItemTaskCard({ slug, s, c, onOpen }) {
  const t = T()
  const d = useItemDetail('task', slug, s, c)
  const f = d?.data?.front ?? {}
  return html`<div class="idrawer-task">
    <div class="idrawer-task-head"><span class="label-caps">${t.item.task}</span><code class="muted">${slug}</code>
      ${f.status ? html`<span class="chip">${t.taskState[f.status] ?? f.status}</span>` : null}</div>
    ${d?.data ? html`${f.headline ? html`<p class="idrawer-task-title">${f.headline}</p>` : null}
      ${f.next ? html`<p class="small"><span class="line-kind">${t.lineKind.next}</span>${f.next}</p>` : null}
      ${f.blocked_by ? html`<p class="small"><span class="line-kind">${t.lineKind.blocked}</span>${f.blocked_by}</p>` : null}`
      : html`<${DetailState} d=${d} onRetry=${() => c.loadTask(slug)} />`}
    <${Btn} size="xs" variant="secondary" onClick=${onOpen}>${t.item.openTask}<//>
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
        ${it.from ? html`<${Fact} label=${t.item.from}>${it.from}<//>` : null}
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
function TaskBody({ slug, cur, s, c }) {
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
    ${f.next ? html`<section class="idrawer-sec"><h3 class="label-caps">${t.front.next}</h3><p class="idrawer-next"><${Linked} text=${String(f.next)} /></p></section>` : null}
    <section class="idrawer-sec"><h3 class="label-caps">${t.item.facts}</h3>
      <dl class="meta idrawer-facts">${facts.map(k => html`<${Fact} key=${k} label=${t.front[k]}>
        ${k === 'status' ? (t.taskState[f[k]] ?? f[k]) : String(f[k])}<//>`)}</dl>
      ${f.origin ? html`<p class="small idrawer-origin"><span class="line-kind">${t.lineKind.origin}</span><${Linked} text=${String(f.origin)} /></p>` : null}
    </section>
    <section class="idrawer-sec"><h3 class="label-caps">${t.item.related}</h3>
      ${related.length ? html`<ul class="entries">${related.map(r => html`<li key=${r.id} class="entry">
        <button type="button" class="btn-link" onClick=${() => c.openItem(`inbox:${r.id}`, { inbox: r.id, task: slug, title: r.summary }, where, cur)}>
          ${short(r.summary ?? r.id, 90)}</button>
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
function ItemDrawer({ s, c, byKey }) {
  const t = T()
  const ref = useFocusOnOpen(true)
  const cur = s.ui.item
  const key = cur.key
  const isInbox = key.startsWith('inbox:')
  const id = key.slice(isInbox ? 6 : 5)
  const it = cur.it ?? {}
  const tri = s.triage?.items?.[key] ?? null
  const own = byKey.get(key)
  const row = own ?? actionRow(isInbox ? { inbox: id, title: it.title, task: it.task } : { task: id, title: it.title }, byKey)
  const data = s.details[isInbox ? 'inbox' : 'task'][id]?.data
  const title = (isInbox ? data?.item?.summary : data?.front?.headline) || it.title || id
  const slug = isInbox ? (data?.item?.task ?? it.task) : id
  // a close from inside the drawer ends the item: the drawer goes with it
  const cc = { ...c, act: async (verb, args) => { const r = await c.act(verb, args); if (r?.ok && (verb === 'settle' || verb === 'do_it')) c.closeItem(); return r } }
  const asks = it.ask && cur.page && cur.section && it.index != null
  // the row's own buttons may already start it (or jump to its tab): then no second "Get it done" beside them
  const ownStarts = (own?.actions ?? []).some(a => ['do', 'restart', 'to_tab'].includes(a.id))
  return html`<div class="overlay" onClick=${e => { if (e.target === e.currentTarget) c.closeItem() }}>
    <aside class="drawer drawer-right idrawer" role="dialog" aria-modal="true" aria-labelledby="idrawer-title" ref=${ref}>
      <header class="idrawer-head">
        <div class="idrawer-head-main">
          <span class="eyebrow">${isInbox ? t.inboxTitle : t.taskTitle}</span>
          <h2 class="idrawer-title" id="idrawer-title">${title}</h2>
        </div>
        <${Btn} variant="ghost" size="xs" icon="close" label=${t.item.close} onClick=${c.closeItem} />
      </header>
      <div class="btn-row idrawer-actions">
        ${cur.prev ? html`<${Btn} size="xs" variant="ghost" icon="back" onClick=${() => c.openItem(cur.prev.key, cur.prev.it, { page: cur.prev.page, section: cur.prev.section }, cur.prev.prev)}>${t.item.backTo}<//>` : null}
        ${own ? html`<${RowActions} row=${own} s=${s} c=${cc} all />` : null}
        ${ownStarts ? null : slug && s.details.task[slug]?.data?.kind !== 'done' ? html`<${Btn} size="xs" variant="secondary" busy=${!!s.ui.busy[`task:${slug}`]} title=${t.btnStartAgentTitle}
          onClick=${() => c.act('start_agent', { keys: [`task:${slug}`] })}>${t.btnOpenTab}<//>`
          : isInbox && data?.item?.state !== 'approved' ? html`<${Btn} size="xs" variant="secondary" busy=${!!s.ui.busy[key]} title=${t.btnStartAgentTitle}
          onClick=${() => c.act('start_agent', { keys: [key] })}>${t.btnOpenTab}<//>` : null}
        ${asks ? html`<${Btn} size="xs" variant="ghost" onClick=${() => c.ask('info', { page: cur.page, section: cur.section, index: it.index })}>${t.btnAsk}<//>` : null}
        ${row ? html`<${SettleMenu} rows=${[row]} s=${s} c=${cc} />` : null}
        ${slug ? html`<${Btn} size="xs" variant="ghost" onClick=${() => c.openInner(`task:${slug}`)}>${t.item.inNet}<//>` : null}
        ${own && !isInbox ? html`<${Btn} size="xs" variant="ghost" onClick=${() => { c.closeItem(); c.peek(key) }}>${t.item.more}<//>` : null}
      </div>
      <div class="idrawer-body">
        <${ReturnPanel} s=${s} c=${c} keys=${[key, slug ? `task:${slug}` : null]} />
        ${slug ? html`<section class="idrawer-sec"><${TaskSessions} row=${{ task: slug, key: `task:${slug}` }} s=${s} c=${c} /></section>` : null}
        ${tri ? html`<section class="idrawer-sec idrawer-tri"><h3 class="label-caps">${t.item.about}</h3>
          <${TriageGist} tri=${tri} keyRow=${row} c=${cc} s=${s} />
          ${tri.reason ? html`<p class="muted small">${tri.reason}</p>` : null}</section>` : null}
        ${isInbox ? html`<${InboxBody} key=${id} id=${id} cur=${cur} s=${s} c=${c} />` : html`<${TaskBody} key=${id} slug=${id} cur=${cur} s=${s} c=${c} />`}
      </div>
    </aside>
  </div>`
}

/** The detail of any page item that is not an inbox item or task: everything the row carries, its link,
 *  its own steps, its account status and "ask". It follows the item as the page holds it now */
function InfoDrawer({ s, c }) {
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
  const others = sec?.kind === 'calendar'
    ? upcomingEvents(s.model, s.now || Date.now()).filter(e => !(e.it.at === cur.at && e.it.title === cur.title)).slice(0, 15)
    : []
  return html`<div class="overlay" onClick=${e => { if (e.target === e.currentTarget) close() }}>
    <aside class="drawer drawer-right idrawer" role="dialog" aria-modal="true" aria-labelledby="info-title" ref=${ref}>
      <header class="idrawer-head">
        <div class="idrawer-head-main">
          <span class="eyebrow">${[pg?.title, sec?.title].filter(Boolean).join(' · ')}</span>
          <h2 class="idrawer-title" id="info-title">${cur.tone ? html`<${StateLine} token=${toneToken(cur.tone)} strong=${cur.tone === 'bad'} word=${cur.title} />` : cur.title}</h2>
        </div>
        <${Btn} variant="ghost" size="xs" icon="close" label=${t.item.close} onClick=${close} />
      </header>
      <div class="btn-row idrawer-actions">
        ${cur.link?.kind === 'web' ? html`<a class="btn btn-secondary btn-xs" href=${cur.link.href} target="_blank" rel="noopener noreferrer">
          <${Icon} name="external" size=${14} /><span class="btn-label">${t.openLink}</span></a>` : null}
        ${cur.link?.kind === 'file' ? html`<${Btn} size="xs" variant="ghost" icon="copy" title=${cur.link.path} onClick=${() => c.copy(cur.link.path)}>${t.copyPath}<//>` : null}
        ${sess ? html`<${Btn} size="xs" variant="primary" busy=${!!s.ui.busy[sess.tab.ref]} onClick=${() => c.act('tab_jump', { tab_ref: sess.tab.ref })}>${t.btnToTab}<//>
          <${Btn} size="xs" variant="secondary" onClick=${() => { close(); c.openTabView(sess.tab.ref) }}>${t.infoViewTab}<//>` : null}
        ${cur.task ? html`<${Btn} size="xs" variant="secondary" onClick=${() => c.openItem(`task:${cur.task}`, cur, { page, section })}>${t.infoOpenTask}<//>` : null}
        ${onHost.length ? html`<${Btn} size="xs" variant="secondary" onClick=${() => { close(); c.openWorkers({ host: cur.title }) }}>${t.workersOpen}<//>` : null}
        ${cur.actions?.length && cur.row_id ? html`<${RowSteps} it=${cur} page=${page} section=${section} s=${s} c=${c} />` : null}
        ${cur.account?.status ? html`<${StatusMenu} it=${cur} page=${page} section=${section} c=${c} />` : null}
        <${PageItemActions} it=${cur} s=${s} c=${c} after=${close} />
        ${cur.ask ? html`<${Btn} size="xs" variant="ghost" onClick=${() => { close(); c.ask('info', { page, section, index: cur.index }) }}>${t.btnAsk}<//>` : null}
      </div>
      <div class="idrawer-body">
        ${onHost.length ? html`<section class="idrawer-sec"><${StateLine} token=${onHostBad ? 'warning' : 'success'} word=${t.workersOnHost(onHost.length, onHostBad)} /></section>` : null}
        ${cur.detail ? html`<section class="idrawer-sec"><p class="info-detail-full"><${Linked} text=${detailText(cur.detail, t)} /></p></section>` : null}
        ${cur.meter ? html`<section class="idrawer-sec"><${MeterBar} meter=${cur.meter} scale=${0} tone=${cur.tone} /></section>` : null}
        ${facts.length ? html`<section class="idrawer-sec"><dl class="meta">${facts.map(([k, v]) => html`<${Fact} key=${k} label=${k}>${v}<//>`)}</dl></section>` : null}
        ${(cur.lines ?? []).length ? html`<section class="idrawer-sec"><${Lines} lines=${cur.lines} /></section>` : null}
        ${others.length ? html`<section class="idrawer-sec"><h3 class="label-caps">${t.infoMoreDates}</h3>
          <ul class="agenda">${others.map(e => html`<li key=${`${e.section}:${e.it.at}:${e.it.title}`}>
            <span class="mono agenda-when">${e.it.when}</span>
            <button type="button" class="btn-link" onClick=${() => c.openInfo(e.it, e.page, e.section)}>${e.it.title}</button></li>`)}</ul></section>` : null}
        ${!cur.detail && !cur.meter && !facts.length && !(cur.lines ?? []).length ? html`<p class="muted">${t.infoNothingMore}</p>` : null}
      </div>
    </aside>
  </div>`
}

function TabsDrawer({ s, c, byKey }) {
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

/** What the dashboard closed, dropped, settled or hid, newest first and by day; each item can be taken back */
function HistoryDrawer({ s, c }) {
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
          <span class="hist-what"><span class="chip">${t.histKind[it.kind] ?? it.kind}</span>
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

function NotesDrawer({ s, c }) {
  const t = T()
  const notes = s.notes.slice().reverse()
  return html`<${Drawer} id="notes" title=${t.notesTitle} onClose=${() => c.setDrawer(null)}>
    ${notes.length ? html`<ol class="notes">${notes.map((n, i) => html`<li key=${i} class="note">
      <span class="mono muted small">${n.at}</span>
      <${StateLine} token=${noteToken(n.tone)} word=${n.text} />
    </li>`)}</ol>` : html`<${Empty}>${t.notesEmpty}<//>`}
  <//>`
}

function HelpDialog({ c }) {
  const t = T()
  const ref = useFocusOnOpen(true)
  return html`<div class="overlay overlay-center" onClick=${e => { if (e.target === e.currentTarget) c.setDrawer(null) }}>
    <div class="dialog dialog-wide" role="dialog" aria-modal="true" aria-labelledby="help-title" ref=${ref}>
      <header class="drawer-head">
        <h2 class="sec-title" id="help-title">${t.helpTitle}</h2>
        <${Btn} variant="ghost" size="xs" icon="close" label=${t.close} onClick=${() => c.setDrawer(null)} />
      </header>
      <div class="help-grid">
        <section>
          <h3 class="label-caps">${t.keysTitle}</h3>
          <dl class="keys">${t.keys.map(([k, v]) => html`<div key=${k}><dt><kbd>${k}</kbd></dt><dd>${v}</dd></div>`)}</dl>
          <p class="muted small">${t.commandHint}</p>
        </section>
        <section>
          <dl class="help-text">${t.helpText.map(([k, v]) => html`<div key=${k}><dt>${k}</dt><dd>${v}</dd></div>`)}</dl>
        </section>
      </div>
    </div>
  </div>`
}

function ConfirmDialog({ s, c }) {
  const t = T()
  const conf = s.ui.confirm
  const ref = useFocusOnOpen(!!conf)
  if (!conf) return null
  if (conf.kind === 'task_close') return html`<${CloseDialog} conf=${conf} c=${c} dialogRef=${ref} />`
  if (conf.kind === 'runs_on') return html`<${RunsOnDialog} conf=${conf} s=${s} c=${c} dialogRef=${ref} />`
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

/** Closing asks why: the reason goes into STATUS.md and the log, not-doing and superseded close as declined */
function CloseDialog({ conf, c, dialogRef }) {
  const t = T()
  const n = conf.keys.length
  const reasons = n > 1 ? ['auto', 'done', 'not_doing', 'superseded', 'elsewhere'] : ['done', 'not_doing', 'superseded', 'elsewhere']
  const declined = conf.reason === 'not_doing' || conf.reason === 'superseded'
  return html`<div class="overlay overlay-center">
    <div class="dialog dialog-wide" role="dialog" aria-modal="true" aria-labelledby="confirm-title" ref=${dialogRef}>
      <h2 class="sec-title" id="confirm-title">${t.closeAsk(n)}</h2>
      <ul class="close-list">${conf.titles.slice(0, 6).map((title, i) => html`<li key=${i}>${short(title, 90)}</li>`)}
        ${n > 6 ? html`<li class="muted">+${n - 6}</li>` : null}</ul>
      <fieldset class="close-reasons">
        <legend class="label-caps">${t.closeReasonLabel}</legend>
        ${reasons.map(r => html`<label key=${r} class="radio-line">
          <input type="radio" name="close-reason" value=${r} checked=${conf.reason === r} data-autofocus=${conf.reason === r ? '' : undefined}
            onChange=${() => c.setConfirm({ reason: r })} />
          <span>${t.closeReason[r]}</span></label>`)}
        ${declined ? html`<p class="muted small">${t.closeDeclinedHint}</p>` : null}
      </fieldset>
      <label class="field">
        <span class="label-caps">${t.closeTextLabel}</span>
        <textarea class="input" rows="3" maxlength="2000" value=${conf.text ?? ''}
          onInput=${e => c.setConfirm({ text: e.currentTarget.value })}></textarea>
        <span class="muted small">${t.closeTextHint}</span>
      </label>
      ${conf.liveTab ? html`<p><${StateLine} token="warning" word=${t.taskDoneLiveTab} /></p>` : null}
      ${conf.openInbox ? html`<p><${StateLine} token="warning" word=${t.taskDoneInbox(conf.openInbox)} /></p>` : null}
      <div class="btn-row dialog-acts">
        <button type="button" class="btn btn-secondary btn-sm" onClick=${c.cancelConfirm}><span class="btn-label">${t.approveNo}</span></button>
        <button type="button" class="btn btn-danger btn-sm" onClick=${c.confirmYes}><span class="btn-label">${t.closeYes(n)}</span></button>
      </div>
    </div>
  </div>`
}

function AuthPanel() {
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

function BootPanel({ s, c }) {
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

function MobileSwitch({ s, c }) {
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

// ---------------------------------------------------------------- root

export function App({ store, ctl }) {
  const [s, setS] = useState(store.get())
  useLayoutEffect(() => {
    // subscribe, then catch up with whatever changed between the first render and now
    const off = store.subscribe(setS)
    setS(store.get())
    return off
  }, [])
  ctl.setAskFallback = v => store.set(x => ({ ...x, ui: { ...x.ui, askFallback: v } }))
  useHomeTitle(s)
  if (s.boot.status === 'unauthorized') return html`<${AuthPanel} />`
  if (s.boot.status !== 'ok') return html`<${BootPanel} s=${s} c=${ctl} />`
  const byKey = indexRows(s.model)
  const onPage = onPageOf(s)
  const layout = s.layout
  const peek = onPage && s.ui.pageDetail && !!s.ui.selectedKey
  const pane = onPage && !peek && s.ui.pane === 'detail' ? 'day' : s.ui.pane
  // a wide page that shows sessions itself or needs the width folds the tab column to its header button
  const rail = layout === 'wide' && railShown(s.ui.page)
  const tabsDrawer = layout === 'medium' || (layout === 'wide' && !rail)
  const showTabsCol = rail || (layout === 'narrow' && pane === 'tabs')
  const main = onPage
    ? html`<${PageView} s=${s} c=${ctl} />${peek ? html`<${DetailColumn} s=${s} c=${ctl} byKey=${byKey} />` : null}`
    : html`<${DayColumn} s=${s} c=${ctl} byKey=${byKey} /><${DetailColumn} s=${s} c=${ctl} byKey=${byKey} />`
  // the page tabs keep their own row on every width: in the header of a wide screen they shared the room
  // with the tools, and the widest screen showed the fewest tabs
  return html`<div class="shell">
    <a class="skip" href="#main">${T().skip}</a>
    <${Header} s=${s} c=${ctl} />
    <${PageBar} s=${s} c=${ctl} />
    ${layout === 'narrow' ? html`<${MobileSwitch} s=${s} c=${ctl} />` : null}
    <main id="main" class=${`main layout-${layout}${onPage ? ' on-page' : ''}${peek ? ' with-detail' : ''}${layout === 'wide' && !rail ? ' no-rail' : ''}`} data-pane=${pane}>
      ${main}
      ${showTabsCol ? html`<${TabsColumn} s=${s} c=${ctl} byKey=${byKey} />` : null}
    </main>
    ${tabsDrawer && s.ui.drawer === 'tabs' ? html`<${TabsDrawer} s=${s} c=${ctl} byKey=${byKey} />` : null}
    ${s.ui.drawer === 'notes' ? html`<${NotesDrawer} s=${s} c=${ctl} />` : null}
    ${s.ui.drawer === 'history' ? html`<${HistoryDrawer} s=${s} c=${ctl} />` : null}
    ${s.ui.drawer === 'help' ? html`<${HelpDialog} c=${ctl} />` : null}
    ${s.ui.drawer === 'item' && s.ui.item ? html`<${ItemDrawer} s=${s} c=${ctl} byKey=${byKey} />` : null}
    ${s.ui.drawer === 'info' && s.ui.info ? html`<${InfoDrawer} s=${s} c=${ctl} />` : null}
    ${s.ui.tabView === '@ask' ? html`<${QuickChat} s=${s} c=${ctl} />` : s.ui.tabView ? html`<${TabView} s=${s} c=${ctl} />` : null}
    ${s.ui.inner ? html`<${InnerRoom} s=${s} c=${ctl} focus=${s.ui.innerFocus} onClose=${ctl.closeInner}
      onTab=${ref => { ctl.closeInner(); jumpToTab(s, ctl, ref) }} />` : null}
    <${ConfirmDialog} s=${s} c=${ctl} />
    <${Toasts} s=${s} c=${ctl} />
  </div>`
}
