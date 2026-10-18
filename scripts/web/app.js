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
  CONN_GRACE_MS, DAY, pushNoteState, actionFailNote, attentionTabs, createFailNote, createLoaders, displayedRows, errorText, freshMore, indexRows, invalidateDetails,
  isTypingTarget, isoDate, themeOverride, modalKeyAllowed, createWithBusy, createToastTimers, letterShortcut, planBusy, toastLinger, reviewHome, nextMonday, parseShortcut, planShortcut, railShown, rowByNumber, short, startRefusal,
  upsertRecord, addFeed, feedEvents, workPageOf, withLaunch, routesToFetch, newerTicker, tickerRemember,
  applyQuickLive, quickLiveSnapshot, whenShown,
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
  usage: { status: 'idle', data: null, error: null, days: 7 },   // days: the range the Betrieb page asked for (7, 30, 90)
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
  rooms: null,         // the chat as cmux (state.rooms: layout, root, control, Bridges); null: an older server, the classic chat
  launchRoutes: {},    // per row key the recommendation of Auto: { title, status: loading|ok|error, route }   // null: not known yet, every button shows; a list: only what the terminal driver serves
  notes: [], toasts: [], conn: 'connecting', connMs: Date.now(), now: Date.now(), mock: MOCK,
  layout: 'wide',
  ui: {
    // a new visit opens on the start page, a reload stays where it was; the project chip chosen there is kept
    page: reloaded() ? load('bridge-cockpit.page', START_PAGE) : START_PAGE, homeProject: load('bridge-cockpit.homeProject', null), selectedKey: null,
    coreConv: null, coreBrief: false, focusKey: null, picked: [], expanded: {},
    // the view of the work tab (due, area, jev); a page with jev: outside it reads area and jev the same way
    workView: load('bridge-cockpit.workTab', 'due'),
    workKind: load('bridge-cockpit.workKind', null),
    theme: THEME_OVERRIDE ?? load('bridge-cockpit.theme', 'auto'), drawer: null, item: null, pane: 'day', confirm: null, askFallback: null, pageDetail: false,
    settingsSection: load('bridge-cockpit.settingsSection', 'start'),
    busy: {}, snapshotText: null, openMsg: null, tabView: null, room: null, quickConv: null, agentPeer: null, agentConv: null, agentMode: 'question', agentsListHidden: load('bridge-cockpit.agentsList', 'shown') === 'hidden',
    railHidden: load('bridge-cockpit.rail', 'shown') === 'hidden',
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
    rooms: payload.rooms ?? s.rooms,
    notes: Array.isArray(payload.notes) ? payload.notes.slice(-20).map(n => ({ ...n, ms: 0 })) : s.notes,
  }))
  // the answers being written, whole: a page that connects in the middle of one shows all of it
  if (payload.quick_live) quickLive.set(quickLiveSnapshot(payload.quick_live))
  fixPage()
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
  tabs(tabs) {
    const prev = store.get()
    if (prev.model) noteFeed(feedEvents(prev.model, prev.model, prev.tabs?.tabs, tabs?.tabs, Date.now()))
    store.set(s => ({ ...s, tabs }))
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
    if (r.settled?.length) setUi(ui => ({ picked: ui.picked.filter(k => !r.settled.includes(k)), rvPicked: ui.rvPicked.filter(k => !r.settled.includes(k)) }))
    return r
  }, { rows: p.rows, refuse: p.refuse })
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
    const res = await api.ask(kind, args, { via: 'quick', model: ui.quickModel, ...(conv ? { conv } : {}) })
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

/** A new launch block (or the old one where none came) and an empty recommendation cache */
function clearRoutes(launch) {
  routeGen += 1
  store.set(s => ({ ...s, launch: launch ?? s.launch, launchRoutes: {} }))
}

const ctl = {
  act,
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
  /** Open a row's detail next to the current page (a task on the tasks page); the page stays */
  peek(key, from) {
    const s = store.get()
    peekFrom = from ?? null
    setUi({ selectedKey: key, pageDetail: true, pane: s.layout === 'narrow' ? 'detail' : s.ui.pane })
    requestAnimationFrame(() => {
      if (s.layout === 'narrow') window.scrollTo(0, 0)
      else document.querySelector('.detail-scroll')?.scrollTo?.(0, 0)
      document.getElementById('detail-title')?.focus({ preventScroll: true })
    })
  },
  /** The drawer of an inbox item or task on the Inbox and Tasks pages: `it` is the page row it was
   *  opened from (title, triage, actions), `prev` the item a task was opened from, for the way back */
  openItem(key, it = null, where = {}, prev = null) {
    setUi({ drawer: 'item', item: { key, it, page: where.page ?? null, section: where.section ?? null, prev } })
  },
  closeItem() {
    setUi({ drawer: null, item: null })
  },
  // any other page item (a table row, a resource tile, a gauge): its detail in a drawer
  openInfo(it, page, section) {
    setUi({ drawer: 'info', info: { it, page, section } })
  },
  closeInfo() {
    setUi({ drawer: null, info: null })
  },
  closePeek() {
    setUi({ pageDetail: false, selectedKey: null, pane: 'day' })
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
    setUi({ page: id, pageDetail: false, drawer, pane: s.layout === 'narrow' ? 'day' : s.ui.pane, workersFilter: null })
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
    const latest = (store.get().agents?.convs ?? []).filter(x => x.peer === peer)
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
  // the tokens of the week (usage.py); the Betrieb page reads them when it opens and with each new briefing
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
  setHomeProject: p => { save('bridge-cockpit.homeProject', p ?? ''); setUi({ homeProject: p }) },
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
  // the noise of the inbox (inbox.py stats + mute list); the Betrieb page reads it when it opens and with each new briefing
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
  pickRoom: room => setUi({ room }),
  newQuick: () => setUi({ quickConv: null }),
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
    if (c?.kind === 'task_close') {
      const text = (c.text ?? '').trim()
      const r = await act('task_close', { keys: c.keys, reason: c.reason, ...(text ? { text } : {}) })
      // a closed task is gone: its detail would only fail to load, so go back to the list
      const sel = store.get().ui.selectedKey
      if (r?.settled?.includes(sel)) {
        if (store.get().ui.pageDetail) ctl.closePeek()
        else setUi({ selectedKey: null, pane: 'day' })
      }
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
  /** Ask why before closing; one row gets the four reasons, several also "as the check says" */
  // "runs on": a small dialog asks until when and on what; it acts through runs_on
  askRunsOn(rows) {
    const list = rows.filter(Boolean)
    if (!list.length) return
    setUi({ confirm: { kind: 'runs_on', keys: list.map(r => r.key), titles: list.map(r => r.title), until: null, on: '' } })
  },
  async runsOn() {
    const conf = store.get().ui.confirm
    if (!conf || conf.kind !== 'runs_on' || !conf.until) return
    setUi({ confirm: null })
    await act('runs_on', { keys: conf.keys, until: conf.until, ...(conf.on.trim() ? { on: conf.on.trim() } : {}) })
  },
  askClose(rows) {
    const list = rows.filter(r => r?.closable)
    if (!list.length) return
    const all = [...indexRows(store.get().model).values()]
    const tasks = new Set(list.map(r => r.task))
    const openInbox = all.filter(r => r.inbox_id && tasks.has(r.task)).length
    const one = list.length === 1 ? list[0] : null
    const rv = one?.review
    setUi({ confirm: { kind: 'task_close', keys: list.map(r => r.key), titles: list.map(r => r.title),
      reason: one ? (rv?.verdict === 'stale' ? 'not_doing' : 'done') : 'auto',
      text: rv && (rv.verdict === 'close' || rv.resolved) ? (rv.reason ?? '').slice(0, 400) : '',
      liveTab: list.some(r => r.tab?.live), openInbox } })
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
  laterDays(row, days) {
    return act('later', { key: row.key, until: isoDate(today() + days * DAY) })
  },
  laterMonday(row) {
    return act('later', { key: row.key, until: isoDate(nextMonday(today())) })
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
    const byNumber = rowByNumber(s.model, rowIndex())
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
    said.push(`${label(n, row)}: ${reason === 'approved' ? t.scApproved : reason === 'waiting' ? t.scWaiting : t.scOnlyYou}`)
  }
  for (const { row } of plan.later) await ctl.laterDays(row, 1)
  for (const { row } of plan.drop) await act('drop', { key: row.key })
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
  const s = store.get()
  const rows = displayedRows(s.model, s.ui.expanded, rowIndex(), s.ui.dayHeight ?? 0)
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

function onKey(e) {
  const s = store.get()
  // the inner room keeps its own keys (inner.js)
  if (s.ui.inner) return
  if (e.key === 'Escape') {
    if (s.ui.confirm) return ctl.cancelConfirm()
    if (s.ui.tabView) return setUi({ tabView: null })
    if (s.ui.drawer) return setUi({ drawer: null, item: null })
    if (s.ui.pageDetail && !isTypingTarget(e.target)) return ctl.closePeek()
    if (isTypingTarget(e.target)) e.target.blur()
    return
  }
  // nothing acts on the list hidden behind an open drawer or confirmation (g t still focuses the tabs)
  if (s.ui.tabView) return
  if (!modalKeyAllowed(s.ui, e.key, gPending)) return
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
  if (s.ui.page !== 'briefing') return
  if (key === 'j' || key === 'k') {
    e.preventDefault()
    return moveFocus(key === 'j' ? 1 : -1)
  }
  const focused = s.ui.focusKey ? rowIndex().get(s.ui.focusKey) : null
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
    if (letter) ctl.letter(focused ?? (s.ui.selectedKey ? rowIndex().get(s.ui.selectedKey) : null), letter)
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
      auth: params.get('auth') === '0' ? false : undefined,
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

  const st = await api.state()
  if (st.ok) applyState(st.data)
  else failNote(st)
  api.events(handlers, onConn)

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
