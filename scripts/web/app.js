// SPDX-License-Identifier: MIT
// Entry of the cockpit: bootstrap, one small store, the live event
// stream, the controller the components call, keyboard handling and the routing
// between the Briefing and the profile pages.
//
// The server owns the domain: it decides sections, actions, waiting tabs and what is
// approvable. This file keeps only view state (selection, picked rows, expanded
// sections, page, theme, drawers) and sends verbs.

import { html, render } from './vendor/htm-preact-3.1.1.module.js'
import { createApi } from './api.js'
import { AGENTS_PAGE, App, CHAT_PAGE, CHECK_PAGE, SETTINGS_PAGE, START_PAGE, WORKERS_PAGE, pageOrder, quickLive } from './components.js'
import {
  CONN_GRACE_MS, DAY, pushNoteState, actionFailNote, replyRefusal, attentionTabs, createFailNote, createLoaders, displayedRows, errorText, freshMore, indexRows, invalidateDetails,
  isTypingTarget, isoDate, themeOverride, modalKeyAllowed, createWithBusy, createToastTimers, letterShortcut, planBusy, toastLinger, reviewHome, nextMonday, parseShortcut, planShortcut, railShown, rowByNumber, short, startRefusal,
  upsertRecord, addFeed, feedEvents, workPageOf, withLaunch, routesToFetch, newerTicker, tickerRemember,
  applyQuickLive, quickLiveSnapshot, whenShown, pruneAnswered, organizeGroups, organizeTicks, roomsOf, askContext,
  listedChats, tabWalkView, walkRefs, inProject, AREA_PAGES, areaScope, scopeKeep, scopeRow, escapeStep, TOUR_VERSION, tourIndex, tourOffered, tourSteps, queueLiveKeys, queueView, dayQueue, workViewOf,
  focusIndex, homeChosen, homeListParts, homeQueue, homeView, openStream, mergePages,
} from './logic.js'
import { T, language, setControl, setLanguage } from './text.js'

const params = new URLSearchParams(window.location.search)
const MOCK = params.get('mock') === '1'
// ?theme=light|dark forces the mode for this load and is never saved (the website demo); theme.js does the same
const THEME_OVERRIDE = themeOverride(window.location.search)

// ---------------------------------------------------------------- storage (per viewer, optional)

function load(key, fallback) {
  try {
    // a choice made while the cockpit was still the web dashboard (bridge-web.*) carries over once
    const v = window.localStorage.getItem(key) ?? window.localStorage.getItem(key.replace(/^bridge-cockpit\./, 'bridge-web.'))
    return v === null ? fallback : v
  } catch {
    return fallback
  }
}

/** Whether this load is the browser's reload of the page, not a new visit (a bookmark, a new tab) */
function reloaded() {
  try { return window.performance?.getEntriesByType?.('navigation')?.[0]?.type === 'reload' } catch { return false }
}

/** The news ticker's marks in this browser: the ids of the news opened, and since when a news item counts
 *  as new (the visit before this one; a reload is no new visit). A convenience, never state */
function loadTickerRead() {
  try {
    const v = JSON.parse(window.localStorage.getItem('bridge-cockpit.tickerRead') ?? '[]')
    return Array.isArray(v) ? v.filter(x => typeof x === 'string').slice(-300) : []
  } catch {
    return []
  }
}

function tickerSince() {
  const last = Number(load('bridge-cockpit.tickerVisit', 0)) || 0
  if (reloaded()) return Number(load('bridge-cockpit.tickerSince', 0)) || 0
  save('bridge-cockpit.tickerSince', String(last))
  save('bridge-cockpit.tickerVisit', String(Date.now()))
  return last
}

/** The live feed, kept in this browser so a reload does not empty it; a convenience, never state */
function loadFeed() {
  try {
    const v = JSON.parse(window.localStorage.getItem('bridge-cockpit.feed') ?? '[]')
    return Array.isArray(v) ? v.filter(e => e && typeof e.kind === 'string' && Number.isFinite(e.at)).slice(0, 50) : []
  } catch {
    return []
  }
}

function noteFeed(events) {
  if (!events.length) return
  store.set(s => ({ ...s, feed: addFeed(s.feed ?? [], events, 50) }))
  save('bridge-cockpit.feed', JSON.stringify(store.get().feed))
}

function save(key, value) {
  try {
    window.localStorage.setItem(key, value)
  } catch { /* storage blocked: the choice lasts for this page only */ }
}

// ---------------------------------------------------------------- store

function createStore(initial) {
  let state = initial
  const subs = new Set()
  return {
    get: () => state,
    set(fn) {
      const next = typeof fn === 'function' ? fn(state) : { ...state, ...fn }
      if (next === state) return
      state = next
      for (const s of subs) s(state)
    },
    subscribe(fn) {
      subs.add(fn)
      return () => subs.delete(fn)
    },
  }
}

const store = createStore({
  boot: { status: 'loading', error: null, version: null, config: {}, scratch: null, warnings: [] },
  server: null, model: null, tabs: { at_ms: 0, tabs: [], error: null, control: null }, sessions: { at_ms: 0, sessions: [] },
  quick: { available: false, default: 'haiku', models: ['haiku', 'sonnet', 'opus'], convs: [] },
  agents: { peers: [], convs: [] },
  triage: { items: {}, last: null, running: null },
  history: [],
  jev: { enabled: false, ready: false, reason: 'off' },
  workers: { status: 'idle', data: null, error: null },
  usage: { status: 'idle', data: null, error: null, days: 7 },   // days: the range the overview page asked for (7, 30, 90)
  costs: { status: 'idle', data: null, error: null },   // the cloud costs per account (cloud-costs.py, read by bridge-resources.py costs)
  noise: { status: 'idle', data: null, error: null },   // the loud inbox sources and the mute rules (inbox.py stats)
  jevOrder: {},   // per page with `jev:`: { order, error, running }
  home: { tiles: null, seen: null, pins: [] },
  feed: loadFeed(),   // the live feed of the start page: what happened while the page was open (logic.js feedEvents)   // the start page's choice, what it offered, the pinned rows (server, state.json)
  loading: { pass: null }, relay: { enabled: false, online: false, reason: null, session: null, records: [] },
  cmux: { ok: true, error: null },
  driver: { caps: null },
  launch: null,        // the model an agent tab starts with (state.launch); null: an older server, the choice stays hidden
  ticker: null,        // the news ticker (state.ticker); null: an older server, the band and its settings stay hidden
  guide: null,         // the decision guide of waiting tabs (state.guide); null: an older server, the guide stays hidden
  tour: null,          // the first-run tour (state.tour): { enabled, done }; null: an older server, it never starts by itself
  rooms: null,         // the chat as cmux (state.rooms: layout, root, control, Bridges); null: an older server, the classic chat
  launchRoutes: {},    // per row key the recommendation of Auto: { title, status: loading|ok|error, route }   // null: not known yet, every button shows; a list: only what the terminal driver serves
  notes: [], toasts: [], conn: 'connecting', connMs: Date.now(), now: Date.now(), mock: MOCK,
  layout: 'wide',
  ui: {
    // a new visit opens on the start page, a reload stays where it was; the project chip chosen there is kept
    page: reloaded() ? load('bridge-cockpit.page', START_PAGE) : START_PAGE, selectedKey: null,
    // the area Work, Chat and Sessions show (logic.js areaScope), Work's star filter, the news on the start page
    // one area filter: the project chosen on the start page before it was one carries over
    area: load('bridge-cockpit.area', '') || load('bridge-cockpit.homeProject', '') || null, pinnedOnly: load('bridge-cockpit.pinnedOnly', '0') === '1',
    tickerOnStart: load('bridge-cockpit.tickerOnStart', '0') === '1',
    coreConv: null, coreBrief: false, focusKey: null, picked: [], expanded: {}, sent: [],
    // the view of the work tab (due, area, jev); a page with jev: outside it reads area and jev the same way
    workView: load('bridge-cockpit.workTab', 'due'),
    workKind: load('bridge-cockpit.workKind', null),
    theme: THEME_OVERRIDE ?? load('bridge-cockpit.theme', 'auto'), drawer: null, item: null, pane: 'day', confirm: null, askFallback: null, pageDetail: false, queue: null, focusAt: null,
    settingsSection: load('bridge-cockpit.settingsSection', 'start'),
    busy: {}, snapshotText: null, openMsg: null, tabView: null, room: null, quickConv: null, agentPeer: null, agentConv: null, agentMode: 'question', agentsListHidden: load('bridge-cockpit.agentsList', 'shown') === 'hidden',
    railHidden: load('bridge-cockpit.rail', 'shown') === 'hidden',
    // keyboard shortcuts wait until switched on in the settings (this browser only): a stray letter acts on nothing
    shortcuts: load('bridge-cockpit.shortcuts', 'off') === 'on',
    // the order of the workspaces in the chat as cmux: the terminal's (default) or the most urgent first; kept in this browser
    roomsSort: ['urgency', 'status'].find(v => v === load('bridge-cockpit.roomsSort', 'terminal')) ?? 'terminal',
    guideView: ['guide', 'both', 'screen'].includes(load('bridge-cockpit.guideView', 'both')) ? load('bridge-cockpit.guideView', 'both') : 'both',
    answered: {},   // per tab ref the answer the page sent last: { hash, q, ms } (views/reply.js)
    renaming: null,  // the tab or workspace whose name is being typed: { kind: 'tab' | 'ws', id: ref } (views/rooms.js)
    // organize with AI (views/organize.js): { busy, applying, proposal, ticks: { id: true }, result } while open
    organize: null,
    // the first-run tour (views/tour.js): { step, from } while it runs, from: the page to go back to
    tour: null,
    hints: false,   // the explain overlay (views/hints.js): notes over the page, open or not
    tickerPaused: load('bridge-cockpit.tickerPaused', '0') === '1', tickerRead: loadTickerRead(), tickerSince: tickerSince(), quickModel: load('bridge-cockpit.quickModel', null),
    launchModel: load('bridge-cockpit.launchModel', null), launchEffort: load('bridge-cockpit.launchEffort', null), rvFilter: 'all', rvSort: 'verdict', rvPicked: [],
  },
  details: { inbox: {}, task: {} },
  more: {},
})

const setUi = patch => store.set(s => ({ ...s, ui: { ...s.ui, ...(typeof patch === 'function' ? patch(s.ui) : patch) } }))

let api = null
let toastSeq = 0
let peekFrom = null      // the title a side detail was opened from: focus goes back there on close

// ---------------------------------------------------------------- notes and toasts

function pushNote(note, { toast = true, linger = 6000 } = {}) {
  if (!note || !note.text) return
  const now = Date.now()
  store.set(s => {
    const next = pushNoteState(s, { ...note, at: note.at ?? clock(now) }, now, toastSeq + 1, toast)
    if (next.dup) {
      // a toast of the same text is still up (the server's note event is often first): a twin that brings
      // an action, an undo, gives it to that toast and keeps it up as long as its own would stay
      const twin = note.action && s.toasts.find(t => t.text === note.text && !t.action)
      if (!twin) return s
      toastTimers.start(twin.id, toastLinger(twin.tone, linger))
      return { ...s, toasts: s.toasts.map(t => t === twin ? { ...t, action: note.action, conv: note.conv ?? null, undo: note.undo ?? null, copy: note.copy ?? null } : t) }
    }
    if (next.toast) {
      toastSeq = next.toast.id
      toastTimers.start(next.toast.id, toastLinger(next.toast.tone, linger))
    }
    return { ...s, notes: next.notes, toasts: next.toasts }
  })
}

function dismissToast(id) {
  toastTimers.stop(id)
  store.set(s => ({ ...s, toasts: s.toasts.filter(t => t.id !== id) }))
}

// a toast waits while the pointer or the focus is inside it, a bad one until it is dismissed (logic.js)
const toastTimers = createToastTimers({ expire: dismissToast })

function clock(ms) {
  const d = new Date(ms)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

const failNote = createFailNote(
  () => store.set(s => ({ ...s, boot: { ...s.boot, status: 'unauthorized' } })),
  res => pushNote({ text: errorText(res.error, T()), tone: 'bad' }))

// ---------------------------------------------------------------- theme and layout

const darkQuery = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null

function applyTheme(mode) {
  const dark = mode === 'dark' || (mode === 'auto' && !!darkQuery?.matches)
  const root = document.documentElement
  root.classList.toggle('dark', dark)
  root.classList.toggle('light', !dark)
  root.setAttribute('data-theme-mode', mode)
}

darkQuery?.addEventListener?.('change', () => applyTheme(store.get().ui.theme))

const wideQuery = window.matchMedia('(min-width: 1280px)')
const mediumQuery = window.matchMedia('(min-width: 900px)')

function updateLayout() {
  const layout = wideQuery.matches ? 'wide' : mediumQuery.matches ? 'medium' : 'narrow'
  store.set(s => (s.layout === layout ? s : { ...s, layout, ui: { ...s.ui, drawer: layout === 'wide' && s.ui.drawer === 'tabs' ? null : s.ui.drawer } }))
}
wideQuery.addEventListener('change', updateLayout)
mediumQuery.addEventListener('change', updateLayout)

// Safari on macOS in full screen reports a viewport that starts below its toolbar but draws the toolbar
// lower than that, over the top of the header. Full screen here is the window filling the screen with
// browser chrome still above the page; the page's own fullscreen API is not involved.
const IS_SAFARI = /Safari\//.test(navigator.userAgent) && !/Chrome|Chromium|Edg\//.test(navigator.userAgent)

function updateChromeGap() {
  const full = IS_SAFARI && window.screenY === 0 && window.outerHeight === screen.height && window.innerHeight < window.outerHeight
  document.documentElement.classList.toggle('safari-fullscreen', full)
}
window.addEventListener('resize', updateChromeGap)
updateChromeGap()

// ---------------------------------------------------------------- live events

function applyState(payload) {
  store.set(s => ({
    ...s,
    server: payload.server ?? s.server,
    model: payload.model ?? null,
    more: freshMore(s.more, payload.model ?? null),
    tabs: payload.tabs ?? s.tabs,
    sessions: payload.sessions ?? s.sessions,
    quick: payload.quick ?? s.quick,
    agents: payload.agents ?? s.agents,
    triage: payload.triage ?? s.triage,
    jev: payload.jev ?? s.jev,
    loading: payload.loading ?? s.loading,
    relay: payload.relay ?? s.relay,
    cmux: payload.cmux ?? s.cmux,
    driver: payload.driver ?? s.driver,
    home: payload.home ?? s.home,
    launch: payload.launch ?? s.launch,
    ticker: payload.ticker ?? s.ticker,
    guide: payload.guide ?? s.guide,
    tour: payload.tour ?? s.tour,
    rooms: payload.rooms ?? s.rooms,
    notes: Array.isArray(payload.notes) ? payload.notes.slice(-20).map(n => ({ ...n, ms: 0 })) : s.notes,
  }))
  // the answers being written, whole: a page that connects in the middle of one shows all of it
  if (payload.quick_live) quickLive.set(quickLiveSnapshot(payload.quick_live))
  fixPage()
  offerTour()
}

let tourOffer = true   // a visit offers the tour once, on its first state; Help and Settings start it again

/** The first-run tour on a first visit: the server says it never ended and the config leaves it on */
function offerTour() {
  const s = store.get()
  if (!tourOffer || !s.tour) return
  tourOffer = false
  if (tourOffered(s.tour) && !s.ui.tour) setUi({ tour: { id: 'welcome', from: s.ui.page } })
}

/** A stored page that the profile no longer has falls back to the Briefing ('@check' is the page's own) */
function fixPage() {
  const s = store.get()
  if (s.model && s.ui.page === CHECK_PAGE && !pageOrder(s).includes(CHECK_PAGE)) ctl.openReview()   // the check moved onto a page
  else if (s.model && !pageOrder(s).includes(s.ui.page)) setUi({ page: 'briefing' })
}

const handlers = {
  hello(p) {
    if (p?.language && p.language !== language()) {
      setLanguage(p.language)
      document.documentElement.lang = language()
      store.set(s => ({ ...s }))
    }
  },
  state: applyState,
  view(model) {
    // the return channel: an answer that was not there before is worth a note
    const had = new Map((store.get().model?.returns ?? []).map(r => [r.key, r.stage]))
    for (const r of model?.returns ?? []) {
      if (had.size && had.has(r.key) && !['result', 'done'].includes(had.get(r.key)) && ['result', 'done'].includes(r.stage)) {
        pushNote({ text: T().home.returnArrived(r.title), tone: 'ok' }, { linger: 12000 })
      }
    }
    const prev = store.get()
    noteFeed(feedEvents(prev.model, model, prev.tabs?.tabs, prev.tabs?.tabs, Date.now()))
    store.set(s => ({ ...s, model, more: freshMore(s.more, model) }))
    fixPage()
  },
  // only the pages that changed (review C34): put in by id and handled as a whole view; one that cannot be
  // put in (an older seq, an unknown page) asks for the whole state once
  view_pages(ev) {
    const model = mergePages(store.get().model, ev)
    if (model) return handlers.view(model)
    if ((store.get().model?.seq ?? 0) < (ev?.seq ?? 0)) api.state().then(st => (st.ok ? applyState(st.data) : failNote(st)))
  },
  tabs(tabs) {
    const prev = store.get()
    if (prev.model) noteFeed(feedEvents(prev.model, prev.model, prev.tabs?.tabs, tabs?.tabs, Date.now()))
    store.set(s => ({ ...s, tabs, ui: { ...s.ui, answered: pruneAnswered(s.ui.answered, Date.now()) } }))
  },
  quick(q) {
    const before = store.get().quick?.convs ?? []
    store.set(s => ({ ...s, quick: q }))
    // an answer that comes while the chat is not in view says so, with the way back to it
    const ui = store.get().ui
    const inView = ui.tabView === '@ask' || (ui.page === CHAT_PAGE && !ui.tabView)
    for (const c of q?.convs ?? []) {
      const was = before.find(b => b.id === c.id)
      const last = c.turns?.[c.turns.length - 1]
      if (was?.running && !c.running && last?.a && !(inView && ui.quickConv === c.id)) answeredNote(last.q, 'ask', c.id)
    }
  },
  triage(tr) {
    store.set(s => ({ ...s, triage: tr }))
  },
  agents(a) {
    const before = store.get().agents?.convs ?? []
    store.set(s => ({ ...s, agents: a }))
    // an agent that answers while its conversation is not in view says so, with the way to it
    const ui = store.get().ui
    for (const c of a?.convs ?? []) {
      const was = before.find(b => b.id === c.id)
      const last = c.turns?.[c.turns.length - 1]
      const inView = ui.page === AGENTS_PAGE && !ui.tabView && ui.agentConv === c.id
      if (was?.running && !c.running && (last?.a || last?.waiting) && !inView) {
        pushNote({ text: T().agentAnswered(c.peer, last.waiting), tone: last.waiting ? 'info' : 'ok', action: 'agent', conv: c.id }, { linger: 20000 })
      }
    }
  },
  // the answer while it is written: the new piece of its text and what it reads; null when the turn is
  // over. It goes to its own small store, so only the chat re-renders, not the page (views/chat.js)
  quick_live(p) {
    quickLive.set(applyQuickLive(quickLive.get(), p))
  },
  sessions(sessions) {
    store.set(s => ({ ...s, sessions }))
  },
  loading(loading) {
    store.set(s => ({ ...s, loading }))
  },
  note(n) {
    pushNote(n)
  },
  relay(record) {
    const before = (store.get().relay?.records ?? []).find(r => r.id === record?.id)
    store.set(s => ({ ...s, relay: { ...s.relay, records: upsertRecord(s.relay.records, record) } }))
    // an answer that arrives while the Claude window is closed says so, with the way to it
    if (record?.status === 'answered' && before?.status !== 'answered' && store.get().ui.tabView !== '@control') {
      answeredNote(record.preview, 'claude')
    }
  },
  // the model choice changed (a save here or in another browser): the new block, the old recommendations go
  launch(l) {
    clearRoutes(l)
  },
  // the news ticker changed: new items, a refresh or an edit ended, settings saved here or in another browser
  ticker(tk) {
    store.set(s => (newerTicker(s.ticker, tk) ? { ...s, ticker: tk } : s))
  },
  // the decision guide changed: a reading started or ended, a tab left, the switches changed here or elsewhere
  guide(g) {
    store.set(s => (newerTicker(s.guide, g) ? { ...s, guide: g } : s))
  },
  // the first-run tour ended or was offered again, in this or another browser
  tour(tr) {
    // ended in another tab of this page: the offer open here closes too, the page goes back where it began
    const s = store.get()
    if (tr?.done && !s.tour?.done && s.ui.tour) ctl.tourClose()
    store.set(x => ({ ...x, tour: tr ?? x.tour }))
  },
  // the start page's choice of tiles, made in this or another browser
  home(h) {
    store.set(s => ({ ...s, home: h ?? s.home }))
  },
  relay_state(rs) {
    store.set(s => ({ ...s, relay: { ...s.relay, ...rs, records: s.relay.records } }))
  },
  alert(a) {
    const t = T()
    const text = a.kind === 'tab_long' ? t.tabLongToast(a.name) : t.tabToast(a.name, t.state[a.state] ?? a.state)
    pushNote({ text, tone: 'warn' })
    if (a.kind === 'tab_waiting' && store.get().boot.config?.voice) {
      try {
        const u = new SpeechSynthesisUtterance(t.voiceWaiting(a.name))
        u.lang = language()
        window.speechSynthesis.speak(u)
      } catch { /* no speech in this browser */ }
    }
  },
}

let probeTimer = null

/** "Claude answered to «...»" with the way to the answer; the question without its [web:...] tag, cut at 60 */
function answeredNote(q, action, conv) {
  const x = String(q ?? '').replace(/^\[web:[^\]]*\]\s*/, '')
  pushNote({ text: T().claudeAnswered(x.length > 60 ? `${x.slice(0, 60)}…` : x), tone: 'ok', action, conv }, { linger: 20000 })
}
let graceTimer = null
function onConn(conn) {
  // A reconnect attempt after a loss stays 'down' until the stream is open again: no flicker.
  store.set(s => {
    const next = conn === 'connecting' && s.conn === 'down' ? 'down' : conn
    return s.conn === next ? s : { ...s, conn: next, connMs: Date.now(), now: Date.now() }
  })
  clearTimeout(graceTimer)
  // the warning shows once the stream has not been open for CONN_GRACE_MS: re-render then
  if (conn !== 'open') graceTimer = setTimeout(() => store.set(s => ({ ...s, now: Date.now() })), CONN_GRACE_MS + 100)
  if (conn === 'down' && !probeTimer) {
    // the stream was refused: a restarted server has a new token, then the page needs the new link
    probeTimer = setTimeout(async () => {
      probeTimer = null
      const res = await api.bootstrap()
      if (res.status === 401) store.set(s => ({ ...s, boot: { ...s.boot, status: 'unauthorized' } }))
      else if (res.ok) api.setCsrf(res.data.csrf)
    }, 1500)
  }
}

// ---------------------------------------------------------------- controller

function rowIndex() {
  return indexRows(store.get().model)
}

// the refusal of an action, by the args object it was sent with, for reply() to show where it was asked
// (logic.js replyRefusal: a step that failed keeps its own note)
const refusals = new WeakMap()

async function act(verb, args = {}) {
  // a bulk leaves out the rows already in flight and says so, and marks each of the others busy (logic.js planBusy)
  const p = planBusy(verb, args, store.get().ui.busy)
  if (p.skipped.length) pushNote({ text: T().busySkipped(p.skipped.length), tone: 'warn' })
  if (p.refused) return null
  return withBusy(p.key, verb, async () => {
    // a start carries the chosen model and effort, only while launch is on (logic.js withLaunch)
    const st = store.get()
    const res = await api.action(verb, withLaunch(verb, p.args, st.launch, st.ui, st.launchRoutes))
    if (!res.ok) {
      // a refusal after a step that wrote (a row filed and hidden, then the start refused) still offers its undo
      if (res.data?.undo?.length) pushNote({ text: errorText(res.error, T()), tone: 'bad', action: 'undo', undo: res.data.undo }, { linger: 10000 })
      else if (res.status === 401) failNote(res)
      else pushNote(actionFailNote(res, T()))
      if (res.error) refusals.set(args, replyRefusal(res))
      return null
    }
    const r = res.data
    if (r.confirm) return r
    // a close, drop or hide can be taken back for a few seconds right here, and later from the history
    if (r.undo?.length && r.ok) {
      pushNote({ text: r.note || T().undoDone, tone: 'ok', action: 'undo', undo: r.undo }, { linger: 10000 })
      if (store.get().ui.drawer === 'history') ctl.loadHistory()
    } else if (r.note) pushNote({ text: r.note, tone: r.ok ? 'ok' : 'bad' })
    if (r.relay) store.set(s => ({ ...s, relay: { ...s.relay, records: upsertRecord(s.relay.records, r.relay) } }))
    // the task facts and inbox events of the touched row changed on disk: fetch them again when shown
    const touched = (p.args.key ? [p.args.key] : p.args.keys ?? []).map(k => rowIndex().get(k)).filter(Boolean)
    if (touched.length) store.set(s => ({ ...s, details: touched.reduce(invalidateDetails, s.details) }))
    if (r.settled?.length) {
      setUi(ui => ({ picked: ui.picked.filter(k => !r.settled.includes(k)), rvPicked: ui.rvPicked.filter(k => !r.settled.includes(k)) }))
      // a row that left the list takes its open detail along: back to the list, whatever closed it
      const sel = store.get().ui.selectedKey
      if (sel && r.settled.includes(sel)) {
        if (store.get().ui.pageDetail) ctl.closePeek()
        else setUi({ selectedKey: null, pane: 'day' })
      }
    }
    return r
  }, { rows: p.rows, refuse: p.refuse })
}

/** An answer to a tab (views/reply.js): act(), and a refusal comes back as { refused, error } as well, so
 *  the reply shows it beside the field and keeps what was typed */
async function reply(verb, args) {
  const sent = { ...args }
  const r = await act(verb, sent)
  return r ?? refusals.get(sent) ?? null
}

/** Mark `key` busy while fn runs, and clear it however fn ends; a row action already busy runs nothing and says so (logic.js) */
const withBusy = createWithBusy(() => store.get().ui.busy, f => setUi(ui => ({ busy: f(ui.busy) })), () => pushNote({ text: T().busyAlready, tone: 'warn' }))

// the api is made at boot, after this line runs, so the loaders reach it through a forwarder
const loaders = createLoaders({ api: { get: p => api.get(p), post: (p, b) => api.post(p, b) }, set: store.set, fail: failNote, withBusy })

/** A question to Claude: a short session of its own (Haiku unless picked), shown in the question window.
 *  A free question in the window goes on in the open conversation; anything else starts a new one */
async function ask(kind, args = {}) {
  const ui = store.get().ui
  return withBusy(`ask:${kind}`, kind, async () => {
    const onChat = ui.page === CHAT_PAGE && !ui.tabView
    const conv = kind === 'free' && (ui.tabView === '@ask' || onChat) ? ui.quickConv : null
    // a free question carries what the page shows right now, as data beside it (the core asks without it)
    const context = kind === 'free' ? askContext(store.get(), language()) : ''
    const res = await api.ask(kind, context ? { ...args, context } : args, { via: 'quick', model: ui.quickModel, ...(conv ? { conv } : {}) })
    if (res.ok && res.data?.conv) {
      // asked on the Chat tab it stays there, from anywhere else the chat window opens on it
      setUi(onChat && kind === 'free' ? { quickConv: res.data.conv } : { tabView: '@ask', quickConv: res.data.conv, openMsg: null })
      return true
    }
    failNote(res)
    return false
  })
}

/** A message to the control session itself, through the relay (its own window, "View" on its card) */
async function askControl(kind, args = {}, localText = '') {
  return withBusy(`ask:${kind}`, kind, async () => {
    const res = await api.ask(kind, args, { via: 'control' })
    if (res.ok && res.data?.record) {
      store.set(s => ({ ...s, relay: { ...s.relay, records: upsertRecord(s.relay.records, res.data.record) }, ui: { ...s.ui, askFallback: null } }))
      pushNote({ text: T().askQueued, tone: 'ok' }, { toast: true })
      // the answer comes in the control session: show it there at once, live, with room to reply
      setUi({ tabView: '@control', openMsg: null })
      return true
    }
    if (res.status === 409 && res.error?.code === 'relay_offline') {
      const record = res.data?.record ?? null
      setUi({ tabView: '@control', askFallback: { record, fallback: res.data?.fallback ?? { available: false, tab: null }, text: localText || record?.preview || '' } })
      pushNote({ text: T().errors.relay_offline, tone: 'warn' })
      return false
    }
    failNote(res)
    return false
  })
}

async function copy(text) {
  try {
    await navigator.clipboard.writeText(text)
    pushNote({ text: T().askCopied, tone: 'ok' })
    return true
  } catch {
    pushNote({ text: T().askCopyFailed, tone: 'warn' })
    return false
  }
}

async function loadDetail(kind, id) {
  // `ver` ties the entry to the collect run it was read for; the old data stays visible meanwhile
  const ver = store.get().model?.collected_ms ?? 0
  store.set(s => ({ ...s, details: { ...s.details, [kind]: { ...s.details[kind],
    [id]: { status: 'loading', ver, data: s.details[kind][id]?.data ?? null } } } }))
  const res = kind === 'inbox' ? await api.inbox(id) : await api.task(id)
  const entry = res.ok ? { status: 'ok', data: res.data, ver } : { status: 'error', error: errorText(res.error, T()), ver }
  if (res.status === 401) failNote(res)
  store.set(s => ({ ...s, details: { ...s.details, [kind]: { ...s.details[kind], [id]: entry } } }))
}

function today() {
  return Date.now()
}

/** The launch block after a save: from the answer where it carries one, else read from the state; the
 *  cached recommendations go, since the switches or bands behind them may have changed */
async function freshLaunch(r) {
  const launch = r.launch ?? (await api.state()).data?.launch
  clearRoutes(launch)
}

// the generation of the recommendation cache: every clear counts it up, so an answer to a request sent
// before the clear is dropped instead of bringing back a recommendation made under the old settings
let routeGen = 0

/** The ticker block an answer carries, into the store unless a newer one is already there (the event of
 *  the same change can arrive first); the answer itself goes back to the caller */
function tickerAnswer(r) {
  store.set(s => {
    if (newerTicker(s.ticker, r?.ticker)) return { ...s, ticker: r.ticker }
    return s
  })
  return r
}

/** The guide block an answer carries, into the store unless a newer one is already there */
function guideAnswer(r) {
  if (r?.guide) store.set(s => (newerTicker(s.guide, r.guide) ? { ...s, guide: r.guide } : s))
  return r
}

/** A new launch block (or the old one where none came) and an empty recommendation cache */
function clearRoutes(launch) {
  routeGen += 1
  store.set(s => ({ ...s, launch: launch ?? s.launch, launchRoutes: {} }))
}

const ctl = {
  act,
  reply,
  ask,
  copy,
  dismissToast,
  pauseToast: (id, why) => toastTimers.pause(id, why),
  resumeToast: (id, why) => toastTimers.resume(id, why),
  reload: async () => {
    const res = await api.reload(true)
    if (res.ok && res.data?.loading) store.set(s => ({ ...s, loading: res.data.loading }))
    else if (!res.ok) failNote(res)
  },
  select(key) {
    const s = store.get()
    setUi({ selectedKey: key, focusKey: key, pageDetail: false, pane: s.layout === 'narrow' ? 'detail' : s.ui.pane })
    if (s.ui.page !== 'briefing') setUi({ page: 'briefing' })
    if (s.layout === 'narrow') requestAnimationFrame(() => window.scrollTo(0, 0))
    else requestAnimationFrame(() => document.querySelector('.detail-scroll')?.scrollTo?.(0, 0))
  },
  /** Open a row's detail next to the current page (a task on the tasks page); the page stays.
   *  `queue` is the list it was opened from, so the detail's foot offers the next one */
  peek(key, from, queue = null, { keepFocus = false } = {}) {
    const s = store.get()
    // the next of a list keeps the title the list was left from, so closing goes back there
    peekFrom = from ?? (queue ? peekFrom : null)
    setUi({ selectedKey: key, pageDetail: true, queue, pane: s.layout === 'narrow' ? 'detail' : s.ui.pane })
    requestAnimationFrame(() => {
      if (s.layout === 'narrow') window.scrollTo(0, 0)
      else document.querySelector('.detail-scroll')?.scrollTo?.(0, 0)
      // walking a list keeps the focus on its "next" button, so Enter goes on to the one after
      if (!keepFocus) document.getElementById('detail-title')?.focus({ preventScroll: true })
    })
  },
  /** The drawer of an inbox item or task on the Inbox and Tasks pages: `it` is the page row it was
   *  opened from (title, triage, actions), `prev` the item a task was opened from, for the way back */
  openItem(key, it = null, where = {}, prev = null, queue = null) {
    setUi({ drawer: 'item', item: { key, it, page: where.page ?? null, section: where.section ?? null, prev }, queue })
  },
  closeItem() {
    setUi({ drawer: null, item: null, queue: null })
  },
  /** The next entry of the list a detail was opened from (ui.queue), opened the way its list opens it:
   *  beside the page ('peek') or in the item drawer ('item'); the queue stays, so the flow goes on */
  openNext(next) {
    const queue = store.get().ui.queue
    if (!next) return
    // a row of the Today list opens in the center, as its click does
    if (next.how === 'select') return ctl.select(next.key)
    if (next.how === 'item') {
      setUi({ pageDetail: false, selectedKey: null })
      return ctl.openItem(next.key, next.it ?? null, next.where ?? {}, null, queue)
    }
    if (store.get().ui.drawer === 'item') setUi({ drawer: null, item: null })
    ctl.peek(next.key, null, queue, { keepFocus: true })
  },
  // any other page item (a table row, a resource tile, a gauge): its detail in a drawer
  openInfo(it, page, section) {
    setUi({ drawer: 'info', info: { it, page, section } })
  },
  closeInfo() {
    setUi({ drawer: null, info: null })
  },
  closePeek() {
    setUi({ pageDetail: false, selectedKey: null, queue: null, pane: 'day' })
    const back = peekFrom
    peekFrom = null
    if (back?.isConnected) requestAnimationFrame(() => back.focus())
  },
  focusRow(key) {
    if (store.get().ui.focusKey !== key) setUi({ focusKey: key })
  },
  togglePick(key) {
    setUi(ui => ({ picked: ui.picked.includes(key) ? ui.picked.filter(k => k !== key) : [...ui.picked, key] }))
  },
  clearPicks: () => setUi({ picked: [] }),
  toggleSection: id => setUi(ui => ({ expanded: { ...ui.expanded, [id]: !ui.expanded[id] } })),
  jevRun: (force, cacheOnly) => api.post('/api/jev/run', { force: !!force, ...(cacheOnly ? { cache_only: true } : {}) }),   // Jev tab, scripts/web/jev/page.js
  setPage(id) {
    const s = store.get()
    // a page of group day has no tab: a tile or link to it opens Today, where its sections stand
    if ((s.model?.pages ?? []).some(p => p.id === id && p.group === 'day')) id = 'briefing'
    // the work page and the Jev tab are views of the work tab where a page of group work exists
    const work = workPageOf(s.model?.pages)
    if (work && (id === work.id || (id === '@jev' && work.jev))) {
      const view = id === work.id ? 'area' : 'jev'
      save('bridge-cockpit.workTab', view)
      setUi({ workView: view })
      id = 'briefing'
    }
    save('bridge-cockpit.page', id)
    // a page with the tab column beside it closes the tab drawer a folded page opened
    const drawer = s.layout === 'wide' && railShown(id, s.rooms?.layout, s.ui.railHidden) && s.ui.drawer === 'tabs' ? null : s.ui.drawer
    setUi({ page: id, pageDetail: false, queue: null, drawer, pane: s.layout === 'narrow' ? 'day' : s.ui.pane, workersFilter: null })
  },
  // the task check: on the page where inbox and tasks stand together (its tasks label chosen), else its own tab
  openReview() {
    const home = reviewHome(store.get().model?.pages, T().workOrder.kinds)
    if (!home) return ctl.setPage(CHECK_PAGE)
    ctl.setPage(home.page)
    ctl.setWorkKind(home.label)
    ctl.setWorkView('area')
  },
  // the Workers tab with a filter set (the machine whose workers a tile or a drawer asked for)
  openWorkers(filter) {
    ctl.setPage(WORKERS_PAGE)
    setUi({ workersFilter: filter ?? null })
  },
  setTheme(mode) {
    save('bridge-cockpit.theme', mode)
    applyTheme(mode)
    setUi({ theme: mode })
  },
  setShortcuts(on) {
    save('bridge-cockpit.shortcuts', on ? 'on' : 'off')
    setUi({ shortcuts: on })
  },
  cycleTheme() {
    const order = ['auto', 'light', 'dark']
    ctl.setTheme(order[(order.indexOf(store.get().ui.theme) + 1) % order.length])
  },
  setDrawer: name => setUi({ drawer: name }),
  // the settings page at one of its areas (start, look, launch), kept for the next visit
  setSettingsSection(id) {
    save('bridge-cockpit.settingsSection', id)
    setUi({ settingsSection: id })
  },
  openSettings(id) {
    if (id) ctl.setSettingsSection(id)
    ctl.setPage(SETTINGS_PAGE)
    setUi({ drawer: null })
  },
  setPane(pane) {
    setUi({ pane })
    requestAnimationFrame(() => window.scrollTo(0, 0))
  },
  setOpenMsg: ref => setUi({ openMsg: ref }),
  // the tab view: one agent tab large in the middle, its terminal read every 1.5 s (views/tabs.js TabView)
  openTabView: ref => setUi({ tabView: ref, openMsg: null }),
  openClaude: () => setUi({ tabView: '@control', openMsg: null }),
  // the Workers tab: the kept worker view, read again on every visit and every new model
  // with loadHistory and triageRun (logic.js createLoaders): a failed answer leaves a note or signs out
  ...loaders,
  // an agent opens on its latest conversation; "new chat" starts empty
  openHistory: () => { setUi({ drawer: 'history' }); ctl.loadHistory() },
  // the inverse of a close: a task back with the status it had (the toast), or as doing or backlog by choice
  undo: async (u, as = u.args?.as ?? 'doing') => {
    const args = u.verb === 'task_reopen' ? { ...u.args, as, ...(as === 'backlog' ? { note: T().undoBacklogNote } : {}) } : { ...u.args }
    const r = await act(u.verb, args)
    ctl.loadHistory()
    return r
  },
  pickAgent: peer => {
    const a = store.get().agents ?? {}
    const latest = listedChats(a.convs, a.keep_hours, Date.now()).filter(x => x.peer === peer)
      .sort((a, b) => (b.last_ms ?? 0) - (a.last_ms ?? 0))[0]
    setUi({ agentPeer: peer, agentConv: latest?.id ?? null })
  },
  newAgentChat: peer => setUi({ agentPeer: peer, agentConv: null }),
  pickAgentConv: conv => {
    const c = (store.get().agents?.convs ?? []).find(x => x.id === conv)
    setUi({ agentConv: conv, agentPeer: c?.peer ?? store.get().ui.agentPeer })
  },
  openAgentConv: conv => {
    const c = (store.get().agents?.convs ?? []).find(x => x.id === conv)
    save('bridge-cockpit.page', AGENTS_PAGE)
    setUi({ page: AGENTS_PAGE, tabView: null, agentConv: conv, agentPeer: c?.peer ?? null })
  },
  setAgentMode: mode => setUi({ agentMode: mode }),
  // the list of agents beside the conversation folds away for more room; kept in this browser
  toggleAgentsList: () => {
    const hidden = !store.get().ui.agentsListHidden
    save('bridge-cockpit.agentsList', hidden ? 'hidden' : 'shown')
    setUi({ agentsListHidden: hidden })
  },
  // the agent tab column beside the work and the chat folds behind the header's Tabs button; kept in this browser.
  // Pinned back from its drawer, the drawer closes: the column stands beside the page again
  toggleRail: () => {
    const hidden = !store.get().ui.railHidden
    save('bridge-cockpit.rail', hidden ? 'hidden' : 'shown')
    setUi({ railHidden: hidden, drawer: hidden ? store.get().ui.drawer : null })
  },
  // an answer that went out to a tab from the page: its row says so until the tab moved on (views/reply.js)
  // the mark carries the occurrence of the question (logic.js answerMark), so the same words asked again are not hidden
  markAnswered: (ref, mark) => setUi(ui => ({ answered: { ...pruneAnswered(ui.answered, Date.now()), [ref]: { ...mark, ms: mark?.ms ?? Date.now() } } })),
  // a name of its own for a tab or a workspace: the field stands in its sidebar row until saved or cancelled
  startRename: (kind, id) => setUi({ renaming: { kind, id } }),
  stopRename: () => setUi({ renaming: null }),
  // organize with AI: one proposal at a time; nothing is ticked until a person ticks it, nothing applied unticked
  organizePropose: async () => {
    if (store.get().ui.organize?.busy) return
    setUi({ organize: { busy: true, applying: false, proposal: null, ticks: {}, result: null } })
    const r = await act('organize_propose', {})
    setUi(ui => (ui.organize ? { organize: r?.proposal ? { ...ui.organize, busy: false, proposal: r.proposal } : null } : {}))
  },
  organizeToggle: id => setUi(ui => (ui.organize ? { organize: { ...ui.organize, ticks: organizeTicks.toggle(ui.organize.ticks, id) } } : {})),
  organizeTickAll: () => setUi(ui => (ui.organize ? { organize: { ...ui.organize, ticks: organizeTicks.all(ui.organize.proposal) } } : {})),
  organizeTickGroup: (ref, on) => setUi(ui => {
    const o = ui.organize
    const group = o && organizeGroups(o.proposal, roomsOf(store.get())).find(g => g.ref === ref)
    return group ? { organize: { ...o, ticks: organizeTicks.group(o.ticks, group, on) } } : {}
  }),
  organizeApply: async () => {
    const o = store.get().ui.organize
    const items = organizeTicks.ids(o?.ticks, o?.proposal)
    if (!o || o.applying || !items.length) return
    setUi({ organize: { ...o, applying: true } })
    const r = await act('organize_apply', { proposal: o.proposal.id, items })
    setUi(ui => (ui.organize ? { organize: { ...ui.organize, applying: false, ticks: {},
      result: r ? { applied: r.applied ?? [], skipped: r.skipped ?? [], failed: r.failed ?? [] } : ui.organize.result } } : {}))
  },
  organizeClose: () => setUi({ organize: null }),
  setRoomsSort: sort => {
    save('bridge-cockpit.roomsSort', sort)
    setUi({ roomsSort: sort })
  },
  // the walk through the tabs that want you (logic.js tabWalkView): Work through starts it on the first,
  // a tab picked in the sidebar starts it there; the open tab's bar goes on without taking a new order
  // the walk through the tabs that want you, of the area only when one is chosen
  startWalk: () => {
    const refs = walkRefs(areaScope(store.get()).tabs?.tabs)
    if (refs.length) setUi({ room: { kind: 'tab', id: refs[0] }, tabWalk: refs })
  },
  walkTab: (ref, { focus = false } = {}) => { if (ref) setUi({ room: { kind: 'tab', id: ref }, walkFocus: focus }) },
  walkFocused: () => setUi({ walkFocus: false }),
  // the focus of the start page moves to this entry of its queue (views/focus.js, logic.js focusIndex)
  focusWalk: (id, i) => setUi({ focusAt: { id, i } }),
  // the task and inbox pages: filter by the triage, sort again on a click (scripts/web/triage.js)
  // the day column's height, measured by the column itself: how many rows its sections fill up to
  setDayHeight: px => { if (store.get().ui.dayHeight !== px) setUi({ dayHeight: px }) },
  setTriageFilter: f => setUi({ triageFilter: f }),
  // sending is always the user's click: nothing here goes out on its own
  agentSend: async (peer, text, mode, conv) => {
    const r = await act('a2a_ask', { peer, text, mode, ...(conv ? { conv } : {}) })
    if (r?.conv) setUi({ agentConv: r.conv, agentPeer: peer })
    return !!r
  },
  agentPoll: conv => act('a2a_poll', { conv }),
  // removes the conversation here only; the agent is not told
  agentForget: async conv => {
    const r = await act('a2a_forget', { conv })
    if (r) setUi(ui => ({ agentConv: ui.agentConv === conv ? null : ui.agentConv }))
    return !!r
  },
  loadWorkers: async () => {
    store.set(s => ({ ...s, workers: { ...s.workers, status: s.workers.data ? 'ok' : 'loading' } }))
    const res = await api.get('/api/workers')
    store.set(s => ({ ...s, workers: res.ok ? { status: res.data.view ? 'ok' : 'none', data: res.data.view, error: null }
      : { status: res.status === 404 ? 'none' : 'error', data: s.workers.data, error: res.error?.message ?? null } }))
  },
  // the tokens of the week (usage.py); the overview page reads them when it opens and with each new briefing
  // the order of a work page by Jev: without force only the last one (nothing leaves the machine), with force a new one
  jevRank: async (page, force) => {
    if (force) store.set(s => ({ ...s, jevOrder: { ...s.jevOrder, [page]: { ...(s.jevOrder[page] ?? {}), running: true, error: null } } }))
    const res = await api.post('/api/jev/rank', { page, force: !!force })
    store.set(s => ({ ...s, jevOrder: { ...s.jevOrder, [page]: res.ok ? { order: res.data.order, error: null, running: false }
      : { order: s.jevOrder[page]?.order ?? null, error: res.error?.message ?? 'error', running: false } } }))
    if (force && res.ok && res.data.order) ctl.setWorkView('jev')
  },
  setWorkView: v => { save('bridge-cockpit.workTab', v); setUi({ workView: v }) },
  // the Jev view of the work tab: the first request of a day orders by itself (daily), the button orders anew
  jevWork: async (page, force) => {
    const res = await api.post('/api/jev/rank', { page, force: !!force, daily: !force })
    if (res.ok) store.set(s => ({ ...s, jevOrder: { ...s.jevOrder, [page]: { order: res.data.order, error: null, running: false } } }))
    return res
  },
  setWorkKind: k => { save('bridge-cockpit.workKind', k); setUi({ workKind: k }) },
  // the project chip of the start page, kept for the next visit
  // the start page's tiles: shown at once, kept on the server; a refused save puts the old choice back
  async setHomeTiles(ids, seen) {
    const before = store.get().home
    store.set(s => ({ ...s, home: { ...s.home, tiles: ids, seen: seen ?? s.home?.seen ?? null } }))
    if (!await act('home_tiles', { ids, ...(seen ? { seen } : {}) })) store.set(s => ({ ...s, home: before }))
  },
  // a question from the bridge's core: it stays in the core's panel, no chat window opens
  askQuiet: (text, conv) => withBusy('ask:core', 'free', async () => {
    const res = await api.ask('free', { text }, { via: 'quick', place: 'core', model: store.get().ui.quickModel, ...(conv ? { conv } : {}) })
    if (res.ok && res.data?.conv) { setUi({ coreConv: res.data.conv }); return res.data.conv }
    failNote(res)
    return null
  }),
  // whether the core's conversation is a picture of the day (its first answer is the verdict in three lines)
  setCoreBrief: on => setUi(on ? { coreBrief: true, coreConv: null } : { coreBrief: false }),
  // a row pinned to the start page or taken off; shown at once, kept on the server
  async pin(key, on) {
    const before = store.get().home
    store.set(s => ({ ...s, home: { ...s.home, pins: on ? [...(s.home?.pins ?? []).filter(k => k !== key), key] : (s.home?.pins ?? []).filter(k => k !== key) } }))
    if (!await act('pin', { key, on })) store.set(s => ({ ...s, home: before }))
  },
  // the inner room behind the core: the knowledge graph, read when it opens
  // focus: a row key (task:<slug>) or a node path the room flies to once the net stands
  openInner: (focus = null) => setUi({ inner: true, innerFocus: typeof focus === 'string' ? focus : null, drawer: null, item: null, tabView: null }),
  closeInner: () => setUi({ inner: false, innerFocus: null }),
  graph: () => api.get('/api/graph'),
  graphNode: id => api.get(`/api/graph/node?id=${encodeURIComponent(id)}`),
  // a new filter empties the picks and lets go of a focus or a selection it hides (logic.js scopeKeep)
  setArea: a => {
    save('bridge-cockpit.area', a ?? '')
    save('bridge-cockpit.homeProject', '')
    const s = store.get()
    const ui = { ...s.ui, area: a || null, picked: [] }
    setUi({ area: ui.area, ...scopeKeep({ ...s, ui }) })
  },
  setPinnedOnly: on => {
    save('bridge-cockpit.pinnedOnly', on ? '1' : '0')
    const s = store.get()
    const ui = { ...s.ui, pinnedOnly: !!on, picked: [] }
    setUi({ pinnedOnly: ui.pinnedOnly, ...scopeKeep({ ...s, ui }) })
  },
  setTickerOnStart: on => { save('bridge-cockpit.tickerOnStart', on ? '1' : '0'); setUi({ tickerOnStart: !!on }) },
  // a number of the areas (logic.js areaJump): the area as the filter, then its page, Work in the view
  // asked for; the tabs that want you are walked from the first, the area's only
  goArea: (area, to) => {
    ctl.setArea(area)
    if (to?.view) ctl.setWorkView(to.view)
    ctl.setPage(to?.page ?? 'briefing')
    if (to?.walk) {
      const refs = walkRefs((store.get().tabs?.tabs ?? []).filter(t => inProject(t, area)))
      if (refs.length) setUi({ room: { kind: 'tab', id: refs[0] }, tabWalk: refs })
    }
  },
  // days: 7, 30 or 90; without it the range asked for last
  loadUsage: async days => {
    const n = [7, 30, 90].includes(days) ? days : store.get().usage.days ?? 7
    store.set(s => ({ ...s, usage: { ...s.usage, days: n, status: s.usage.data ? 'ok' : 'loading' } }))
    const res = await api.get(`/api/usage?days=${n}`)
    // an answer for a range no longer asked for is dropped
    if (store.get().usage.days !== n) return
    store.set(s => ({ ...s, usage: res.ok ? { status: 'ok', data: res.data.usage, error: null, days: n }
      : { status: 'error', data: s.usage.data, error: res.error?.message ?? null, days: n } }))
  },
  // the cloud costs (bridge-resources.py costs -> costs-view.json); read when the card shows, with each new
  // briefing and on its reload button. 404 or no view: nothing collected yet
  loadCosts: async () => {
    store.set(s => ({ ...s, costs: { ...s.costs, status: s.costs.data ? 'ok' : 'loading' } }))
    const res = await api.get('/api/costs')
    store.set(s => ({ ...s, costs: res.ok ? { status: res.data.view ? 'ok' : 'none', data: res.data.view ?? null, error: null }
      : { status: res.status === 404 ? 'none' : 'error', data: s.costs.data, error: res.error?.message ?? null } }))
  },
  // the noise of the inbox (inbox.py stats + mute list); the overview page reads it when it opens and with each new briefing
  loadNoise: async () => {
    store.set(s => ({ ...s, noise: { ...s.noise, status: s.noise.data ? 'ok' : 'loading' } }))
    const res = await api.get('/api/inbox/noise')
    store.set(s => ({ ...s, noise: res.ok && res.data.noise ? { status: 'ok', data: res.data.noise, error: null }
      : { status: 'error', data: s.noise.data, error: res.ok ? null : res.error?.message ?? null } }))
  },
  async unmute(id) {
    if (await act('inbox_unmute', { id })) ctl.loadNoise()
  },
  openAsk: conv => setUi(ui => ({ tabView: '@ask', openMsg: null, quickConv: conv === undefined ? ui.quickConv : conv })),
  // the chat as a tab of its own: the open conversation goes along, the window closes
  chatAsTab: () => { save('bridge-cockpit.page', CHAT_PAGE); setUi({ page: CHAT_PAGE, tabView: null, pageDetail: false }) },
  pickQuick: conv => setUi({ quickConv: conv }),
  // the chat as cmux: what the right side shows ({ kind: 'ws' | 'tab' | 'chat' | 'agent' | 'bridge', id })
  pickRoom: room => setUi(room?.kind === 'tab' ? { room, tabWalk: walkRefs(store.get().tabs?.tabs) } : { room }),
  newQuick: () => setUi({ quickConv: null }),
  // what a chat_tab start from the chat answered (inbox item and launch outcome), for its status line; the last few
  noteSent: rec => setUi(ui => ({ sent: [...(ui.sent ?? []).slice(-4), rec] })),
  // removes a chat with the Bridge from the list and from the server's file; nothing else knew of it
  quickForget: async conv => {
    const r = await act('quick_forget', { conv })
    if (r) setUi(ui => ({ quickConv: ui.quickConv === conv ? null : ui.quickConv }))
    return !!r
  },
  setQuickModel: m => { save('bridge-cockpit.quickModel', m); setUi({ quickModel: m }) },
  // the model and effort an agent tab starts with: one choice for every start block, kept in this browser
  setLaunchModel: m => { save('bridge-cockpit.launchModel', m); setUi({ launchModel: m }) },
  setLaunchEffort: e => { save('bridge-cockpit.launchEffort', e); setUi({ launchEffort: e }) },
  // the recommendation of Auto for the rows in view: once per key, again when a title changed; a failure stays quiet
  launchRoute: async items => {
    const keys = routesToFetch(items, store.get().launchRoutes)
    if (!keys.length) return
    const titles = new Map(items.map(x => [x.key, x.title]))
    const put = fn => store.set(s => ({ ...s, launchRoutes: { ...s.launchRoutes, ...Object.fromEntries(keys.map(k => [k, fn(k)])) } }))
    const gen = routeGen
    put(k => ({ title: titles.get(k), status: 'loading' }))
    const res = await api.route(keys)
    if (gen !== routeGen) return   // the cache was cleared meanwhile: this answer belongs to the old settings
    const routes = res.ok ? res.data?.routes ?? {} : {}
    put(k => (routes[k] ? { title: titles.get(k), status: 'ok', route: routes[k] } : { title: titles.get(k), status: 'error' }))
  },
  // the settings page: a change saves at once, only what changed; the state then carries the new values
  saveLaunch: async settings => {
    const r = await act('launch_settings', { settings })
    if (r) await freshLaunch(r)
    return r
  },
  resetLaunch: async () => {
    const r = await act('launch_settings_reset', {})
    if (r) await freshLaunch(r)
    return r
  },
  // the news ticker: settings save at once, the refresh and the editor return at once and end with a ticker event.
  // The editor (Claude Haiku) runs only from its button: nothing else calls tickerEdit
  saveTicker: async settings => tickerAnswer(await act('ticker_settings', { settings })),
  resetTicker: async () => tickerAnswer(await act('ticker_settings_reset', {})),
  // their answer carries the state of the start, and the thread's closing event can come before it: the
  // store takes both states from the ticker events alone, in order, and the button shows busy in between
  tickerRefresh: async () => act('ticker_refresh', {}),
  tickerEdit: async () => act('ticker_edit', {}),
  // the interest profile: keywords from the open tasks at once, or (llm) Haiku's line, only on its button;
  // a proposal the settings show until the owner saves it into the interests
  tickerProfile: async llm => tickerAnswer(await act('ticker_profile', { llm: !!llm })),
  // the decision guide: a reading returns at once and ends with a guide event; the switches save at once
  // what a waiting tab's pane in the chat shows: the reading, both, or the terminal; kept in this browser
  setGuideView: v => { save('bridge-cockpit.guideView', v); setUi({ guideView: v }) },
  guideRead: async ref => guideAnswer(await act('guide_read', { tab_ref: ref })),
  saveGuide: async patch => guideAnswer(await act('guide_settings', patch)),
  resetGuide: async () => guideAnswer(await act('guide_settings_reset', {})),
  // the first-run tour: a step opens its page; the end goes back to where it began and is kept on the server
  tourStart: () => setUi(ui => ({ tour: { id: 'welcome', from: ui.page }, hints: false, drawer: null, item: null, tabView: null })),
  // the explain overlay: notes over the page as it stands; drawers and the tab window close, so it sees the page
  setHints: on => setUi(on ? { hints: true, drawer: null, item: null, tabView: null } : { hints: false }),
  tourGo(n) {
    const s = store.get()
    const step = tourSteps(s)[n]
    if (!s.ui.tour || !step) return
    if (step.page && step.page !== s.ui.page) {
      ctl.setPage(step.page)
      // the page a step shows is the tour's, not the person's: a reload mid-tour opens where it began
      if (s.ui.tour.from) save('bridge-cockpit.page', s.ui.tour.from)
    }
    setUi(ui => ({ tour: { ...ui.tour, id: step.id }, drawer: null, tabView: null }))
  },
  // the tour closes and the page goes back to where it began; nothing is sent
  tourClose() {
    const from = store.get().ui.tour?.from
    setUi({ tour: null })
    if (from && from !== store.get().ui.page) ctl.setPage(from)
  },
  async tourEnd(how) {
    ctl.tourClose()
    const r = await act('tour_done', { how, v: TOUR_VERSION })
    if (r?.tour) store.set(s => ({ ...s, tour: r.tour }))
  },
  async tourReset() {
    const r = await act('tour_reset', {})
    if (r?.tour) store.set(s => ({ ...s, tour: r.tour }))
  },
  setTickerPaused: on => { save('bridge-cockpit.tickerPaused', on ? '1' : '0'); setUi({ tickerPaused: !!on }) },
  tickerOpened: id => {
    const read = tickerRemember(store.get().ui.tickerRead, id)
    save('bridge-cockpit.tickerRead', JSON.stringify(read))
    setUi({ tickerRead: read })
  },
  askControl,
  setAskFallback: fb => setUi({ askFallback: fb }),
  closeTabView: () => setUi({ tabView: null }),
  tabScreen: (ref, since) => api.tabScreen(ref, since),
  github: (ref, fresh) => api.github(ref, fresh),
  loadInbox: id => loadDetail('inbox', id),
  loadTask: slug => loadDetail('task', slug),
  async loadMore(pageId, sectionId) {
    const ver = store.get().model?.collected_ms
    const res = await api.page(pageId, sectionId)
    if (!res.ok) return failNote(res)
    // kept only while the model shows the same run (freshMore drops it on the next one)
    store.set(s => (s.model?.collected_ms === ver
      ? { ...s, more: { ...s.more, [`${pageId}/${sectionId}`]: { ...res.data, ver } } } : s))
  },
  async approveAll(keys) {
    const r = await act('approve_all', { keys, confirm: false })
    if (r?.confirm) setUi({ confirm: { kind: 'approve_all', count: r.confirm.count, keys } })
  },
  async confirmYes() {
    const c = store.get().ui.confirm
    setUi({ confirm: null })
    if (c?.kind === 'approve_all') await act('approve_all', { keys: c.keys, confirm: true })
    if (c?.kind === 'drop') {
      const r = await act('drop', { key: c.key, reason: c.reason })
      if (r?.muted) ctl.loadNoise()
    }
  },
  cancelConfirm: () => setUi({ confirm: null }),
  /** Ask why before dropping an inbox report; the item's source and key say what a mute would cover.
   *  The dialog opens at once, the item fills in when it has been read */
  async askDrop(row) {
    if (!row?.inbox_id) return
    setUi({ confirm: { kind: 'drop', key: row.key, title: row.title, reason: 'once', item: null } })
    const res = await api.inbox(row.inbox_id)
    if (res.ok) setUi(ui => ({ confirm: ui.confirm?.kind === 'drop' && ui.confirm.key === row.key ? { ...ui.confirm, item: res.data.item } : ui.confirm }))
  },
  // "runs on": a small dialog asks until when and on what; it acts through runs_on
  askRunsOn(rows, on = '') {
    const list = rows.filter(Boolean)
    if (!list.length) return
    setUi({ confirm: { kind: 'runs_on', keys: list.map(r => r.key), titles: list.map(r => r.title), until: null, on } })
  },
  async runsOn() {
    const conf = store.get().ui.confirm
    if (!conf || conf.kind !== 'runs_on' || !conf.until) return
    setUi({ confirm: null })
    await act('runs_on', { keys: conf.keys, until: conf.until, ...(conf.on.trim() ? { on: conf.on.trim() } : {}) })
  },
  setConfirm: patch => setUi(ui => ({ confirm: ui.confirm ? { ...ui.confirm, ...patch } : null })),
  review(keys, escalate = false, fresh = false) {
    return act('task_review', { ...(keys?.length ? { keys } : {}), ...(escalate ? { escalate: true } : {}),
      ...(fresh ? { fresh: true } : {}) })
  },
  keep: keys => act('task_keep', { keys }),
  setReview: patch => setUi(patch),
  toggleRvPick(key) {
    setUi(ui => ({ rvPicked: ui.rvPicked.includes(key) ? ui.rvPicked.filter(k => k !== key) : [...ui.rvPicked, key] }))
  },
  async snapshot(list) {
    const r = await act(list ? 'snapshot_list' : 'snapshot', {})
    if (r && list) setUi({ snapshotText: r.note })
  },
  // text: the person's sentence, which the server keeps where the row lives
  laterDays(row, days, text = '') {
    return act('later', { key: row.key, until: isoDate(today() + days * DAY), ...(text ? { text } : {}) })
  },
  laterMonday(row, text = '') {
    return act('later', { key: row.key, until: isoDate(nextMonday(today())), ...(text ? { text } : {}) })
  },
  rowAction(row, id) {
    switch (id) {
      case 'restart':
      case 'do':
        return act('do_it', { keys: [row.key] })
      case 'to_tab':
        return row.tab ? act('tab_jump', { tab_ref: row.tab.ref }) : null
      case 'drop':
        return row.inbox_id ? ctl.askDrop(row) : act('drop', { key: row.key })
      case 'done':
        return act('done', { key: row.key })
      case 'advise':
        return act('advise', { keys: [row.key] })
      case 'follow_up':
        return ask('follow_up', { key: row.key })
      case 'ask':
        return ask('row', { key: row.key })
      default:
        return null   // 'approved' is a label, not an action
    }
  },
  /** a v c b w on one row, refused like the mod's shortcuts */
  async letter(row, letter) {
    const t = T()
    if (!row) return pushNote({ text: t.noRow, tone: 'warn' })
    const plan = planShortcut([{ n: row.number || 0, letter }], () => row)
    return runPlan(plan)
  },
  async runCommand(text) {
    const codes = parseShortcut(text)
    if (!codes) {
      pushNote({ text: T().notCode(text.trim()), tone: 'warn' })
      return false
    }
    const s = store.get()
    const byNumber = rowByNumber(s.model, indexRows(areaScope(s).model))   // a number of a hidden row finds nothing
    await runPlan(planShortcut(codes, n => byNumber.get(n)))
    return true
  },
  focusCommand() {
    document.getElementById('command-box')?.focus()
  },
}

async function runPlan(plan) {
  const t = T()
  const said = []
  const label = (n, row) => `${n} (${short(row.title, 30)})`
  for (const n of plan.missing) said.push(t.scMissing(n))
  for (const { n, row } of plan.jump) {
    await act('tab_jump', { tab_ref: row.tab.ref })
    said.push(t.scHasTab(n, short(row.title, 30)))
  }
  for (const { n, row, reason } of plan.refused) {
    said.push(`${label(n, row)}: ${{ approved: t.scApproved, waiting: t.scWaiting, stream: t.scStream }[reason] ?? t.scOnlyYou}`)
  }
  for (const { row } of plan.later) await ctl.laterDays(row, 1)
  if (plan.decline.length) await act('settle', { keys: plan.decline.map(x => x.row.key), outcome: 'not_doing' })
  // an inbox entry asks why first, like the Drop button; one dialog at a time, so the first one
  const [ask, ...rest] = plan.askDrop
  if (ask) await ctl.askDrop(ask.row)
  for (const { n, row } of rest) said.push(`${label(n, row)}: ${t.scDropOne}`)
  if (plan.do.length) await act('do_it', { keys: plan.do.map(x => x.row.key) })
  if (plan.ws.length) await act('do_it', { keys: plan.ws.map(x => x.row.key), target: 'workspace' })
  if (plan.advise.length) await act('advise', { keys: plan.advise.map(x => x.row.key) })
  if (said.length) pushNote({ text: t.scResult(said.join(' · ')), tone: plan.refused.length || plan.missing.length ? 'warn' : 'info' })
}

// ---------------------------------------------------------------- keyboard (contract 7.3)

let gPending = false
let gTimer = null

function focusRowElement(key) {
  const el = document.querySelector(`[data-key="${CSS.escape(key)}"] .row-main`)
  if (el) {
    el.focus({ preventScroll: true })
    el.scrollIntoView({ block: 'nearest' })
  }
}

function moveFocus(step) {
  // the rows the page shows under its filters, never one they hide
  const s = areaScope(store.get())
  const rows = displayedRows(s.model, s.ui.expanded, indexRows(s.model), s.ui.dayHeight ?? 0)
  if (!rows.length) return
  const at = rows.findIndex(r => r.key === s.ui.focusKey)
  const next = at < 0 ? (step > 0 ? 0 : rows.length - 1) : Math.min(rows.length - 1, Math.max(0, at + step))
  const key = rows[next].key
  setUi({ focusKey: key })
  requestAnimationFrame(() => focusRowElement(key))
}

function focusTabs() {
  const s = store.get()
  if (s.layout === 'medium' || (s.layout === 'wide' && !railShown(s.ui.page, s.rooms?.layout, s.ui.railHidden))) setUi({ drawer: 'tabs' })
  else if (s.layout === 'narrow') setUi({ pane: 'tabs' })
  requestAnimationFrame(() => document.getElementById('tabs-column')?.focus())
}

// g a: to the start page, the focus on its areas (the chosen one, else the first line); a drawer open
// over the page closes, and with the shelf switched off the start page shows without a focus
function focusAreas() {
  if (store.get().ui.drawer) setUi({ drawer: null, item: null })
  if (store.get().ui.page !== START_PAGE) ctl.setPage(START_PAGE)
  const go = () => {
    const list = document.getElementById('home-areas-list')
    ;(list?.querySelector('button.home-area-pick[aria-pressed="true"]') ?? list?.querySelector('button.home-area-pick'))?.focus()
  }
  requestAnimationFrame(() => requestAnimationFrame(go))
}

function onKey(e) {
  const s = store.get()
  // the inner room keeps its own keys (inner.js)
  if (s.ui.inner) return
  // the tour keeps the keys while it runs: Escape skips it, the arrows go on and back
  if (s.ui.tour) {
    const n = tourSteps(s).length
    const i = tourIndex(s)
    if (e.key === 'Escape') ctl.tourEnd(i === n - 1 ? 'finished' : 'skipped')   // Esc on the last step is its Done
    else if (e.altKey || e.metaKey || e.ctrlKey) return   // Alt Left is the browser's back, never a step
    else if (e.key === 'ArrowRight' && i < n - 1) { e.preventDefault(); ctl.tourGo(i + 1) }
    else if (e.key === 'ArrowLeft' && i > 0) { e.preventDefault(); ctl.tourGo(i - 1) }
    return
  }
  // the explain overlay: Escape closes it, no other key acts on the page beneath
  if (s.ui.hints) {
    if (e.key === 'Escape') ctl.setHints(false)
    return
  }
  if (e.key === 'Escape') {
    if (s.ui.confirm) return ctl.cancelConfirm()
    if (s.ui.organize) return s.ui.organize.applying ? undefined : ctl.organizeClose()
    if (s.ui.tabView) return setUi({ tabView: null })
    if (s.ui.drawer) return setUi({ drawer: null, item: null, queue: s.ui.pageDetail ? s.ui.queue : null })
    if (s.ui.pageDetail && !isTypingTarget(e.target)) return ctl.closePeek()
    // with nothing open over it, Escape on Work, Chat or Sessions closes an open row or the picks first,
    // then lifts the area filter
    const step = isTypingTarget(e.target) ? null : escapeStep(s.ui)
    if (step === 'selection') return setUi({ selectedKey: null, picked: [] })
    if (step === 'area') return ctl.setArea(null)
    if (isTypingTarget(e.target)) e.target.blur()
    return
  }
  if (!s.ui.shortcuts) return
  // nothing acts on the list hidden behind an open drawer or confirmation (g t still focuses the tabs)
  if (s.ui.tabView) return
  if (!modalKeyAllowed(s.ui, e.key, gPending) || s.ui.organize) return
  if (isTypingTarget(e.target)) return
  if (e.altKey && !e.metaKey && !e.ctrlKey && /^Digit[1-9]$/.test(e.code)) {
    const ids = pageOrder(s)
    const id = ids[Number(e.code.slice(5)) - 1]
    if (id) {
      e.preventDefault()
      ctl.setPage(id)
    }
    return
  }
  if (e.metaKey || e.ctrlKey || e.altKey) return
  if (gPending) {
    gPending = false
    clearTimeout(gTimer)
    if (e.key === 't') {
      e.preventDefault()
      focusTabs()
    }
    if (e.key === 'a') {
      e.preventDefault()
      focusAreas()
    }
    return
  }
  const key = e.key
  if (key === '?') {
    e.preventDefault()
    return setUi({ drawer: 'help' })
  }
  if (key === '/') {
    e.preventDefault()
    return ctl.focusCommand()
  }
  if (key === 'r') {
    e.preventDefault()
    return ctl.reload()
  }
  if (key === 'g') {
    gPending = true
    gTimer = setTimeout(() => { gPending = false }, 1500)
    return
  }
  // n / p in a detail opened from a list (beside the page or in the item drawer): walk that list
  // (the Today list walks its own rows: a row picked there is open in the center)
  const today = s.ui.page === 'briefing' && workViewOf(s.ui.workView, workPageOf(s.model?.pages), s.jev) === 'due'
    && !s.ui.pageDetail && !s.ui.drawer && !!s.ui.selectedKey
  const walking = today || (s.ui.queue?.length && (s.ui.drawer === 'item' || (s.ui.pageDetail && !s.ui.drawer)))
  if ((key === 'n' || key === 'p') && walking) {
    const cur = s.ui.drawer === 'item' ? s.ui.item?.key : s.ui.selectedKey
    const shown = areaScope(s)   // the walk keeps to what the filters show
    const live = queueLiveKeys(shown.model, shown.more)
    const v = queueView(today ? dayQueue(shown.model) : s.ui.queue, cur, x => live.has(x.key))
    const to = key === 'n' ? v?.next[0] : v?.prev
    e.preventDefault()
    if (to) ctl.openNext(to)
    return
  }
  // n / p on the Chat page: the walk through the tabs that want you, as the open tab's bar walks it
  if ((key === 'n' || key === 'p') && s.ui.page === CHAT_PAGE) {
    const cur = s.ui.room?.kind === 'tab' ? s.ui.room.id : null
    const v = cur ? tabWalkView(areaScope(s).tabs?.tabs, s.ui.tabWalk, cur) : null
    e.preventDefault()
    if (!cur || !v) return key === 'n' ? ctl.startWalk() : undefined
    const to = key === 'n' ? v.next[0] : v.prev
    return to ? ctl.walkTab(to.key, { focus: true }) : undefined
  }
  // n / p on the start page in the focus view: the same walk its bar takes
  if ((key === 'n' || key === 'p') && s.ui.page === START_PAGE && !s.ui.drawer && !s.ui.pageDetail
    && homeView(homeChosen(s.model, s.home)) === 'focus') {
    const queue = homeQueue(homeListParts(s.tabs?.tabs ?? [], s.model, { pins: s.home?.pins ?? [] }))
    const to = focusIndex(queue, s.ui.focusAt) + (key === 'n' ? 1 : -1)
    e.preventDefault()
    return queue[to] ? ctl.focusWalk(queue[to].id, to) : undefined
  }
  // j / k in the areas of the start page walk its lines; Enter is the button's own click
  const areas = document.activeElement?.closest?.('#home-areas-list')
  if (areas && (key === 'j' || key === 'k')) {
    const lines = [...areas.querySelectorAll('button.home-area-pick')]
    const at = lines.indexOf(document.activeElement)
    e.preventDefault()
    return lines[Math.min(lines.length - 1, Math.max(0, at + (key === 'j' ? 1 : -1)))]?.focus()
  }
  if (s.ui.page !== 'briefing') return
  if (key === 'j' || key === 'k') {
    e.preventDefault()
    return moveFocus(key === 'j' ? 1 : -1)
  }
  // a row the filters hide is not there for the keys (scopeRow)
  const focused = scopeRow(s, s.ui.focusKey)
  if (key === 'Enter') {
    const active = document.activeElement
    if (focused && (!active || active === document.body)) {
      e.preventDefault()
      ctl.select(focused.key)
    }
    return
  }
  if (key === 'x' && focused) {
    e.preventDefault()
    if (focused.selectable) ctl.togglePick(focused.key)
    return
  }
  if (key.length === 1 && 'avcbw'.includes(key)) {
    e.preventDefault()
    // a held key repeats its keydown: only the first press acts
    const letter = letterShortcut(e)
    if (letter) ctl.letter(focused ?? scopeRow(s, s.ui.selectedKey), letter)
  }
}

// ---------------------------------------------------------------- boot

function Root() {
  return html`<${App} store=${store} ctl=${ctl} />`
}

async function boot() {
  applyTheme(store.get().ui.theme)
  updateLayout()
  let transport
  if (MOCK) {
    const mock = await import('./mock.js')
    transport = mock.createMockTransport({
      lang: params.get('lang') || 'en', offline: params.get('offline') === '1', empty: params.get('empty') === '1',
      auth: params.get('auth') === '0' ? false : undefined, tour: params.get('tour') === '1',
    })
  }
  api = createApi(transport)
  render(html`<${Root} />`, document.getElementById('app'))

  const b = await api.bootstrap()
  if (b.status === 401) {
    store.set(s => ({ ...s, boot: { ...s.boot, status: 'unauthorized' } }))
    return
  }
  if (!b.ok) {
    store.set(s => ({ ...s, boot: { ...s.boot, status: 'error', error: errorText(b.error, T()) } }))
    return
  }
  api.setCsrf(b.data.csrf)
  setLanguage(b.data.language)
  setControl(b.data.config?.control)
  document.documentElement.lang = language()
  store.set(s => ({ ...s, boot: { status: 'ok', error: null, version: b.data.version, config: b.data.config ?? {}, scratch: b.data.scratch ?? null,
    warnings: Array.isArray(b.data.config_warnings) ? b.data.config_warnings : [] } }))
  if (MOCK) pushNote({ text: T().mockNote, tone: 'info' }, { toast: false })

  openStream(api, handlers, onConn, { apply: applyState, fail: failNote })

  document.addEventListener('keydown', onKey)
  // durations and "as of" ages move on without new data; a hidden tab skips the ticks and catches up
  // the moment it is in view again
  const tick = whenShown(document, () => store.set(s => ({ ...s, now: Date.now() })))
  setInterval(tick, 15000)
  document.addEventListener('visibilitychange', tick)
  ctl.loadWorkers()   // for the Workers tab's badge; the tab reads it again when opened
  setInterval(whenShown(document, () => { const g = store.get(); if (g.loading?.pass || g.model?.review?.running) tick() }), 1000)
}

// exported for the components' retry button
ctl.retry = () => window.location.reload()
ctl.attentionTabs = () => attentionTabs(store.get().tabs?.tabs)
ctl.startRefusal = startRefusal

boot()
