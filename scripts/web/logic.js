// SPDX-License-Identifier: MIT
// Pure helpers of the cockpit: dates, durations, shortcut codes, mark
// colors and small read-only views over the server model. No DOM, no network, no
// state; the frontend test imports this file directly under node.
//
// The server decides everything about the domain (which section a row is in, which
// actions apply, whether a tab waits). These helpers only format and look things up.
import { TABLES } from './text.js'
import { inProject } from './areas.js'

// the areas, the files view and the Work through page live in files of their own; every name passes on from here
export * from './areas.js'
export * from './files.js'
export * from './flow.js'

/** The words of one language (text.js, rules/language-policy.md section 3); English for any other */
const tableOf = lang => (TABLES[lang] ?? TABLES.en).logic

export const DAY = 86400000

export function pad(n) {
  return String(n).padStart(2, '0')
}

/** Local calendar date of an epoch millisecond value, as YYYY-MM-DD */
export function isoDate(ms) {
  const d = new Date(ms)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** Local HH:MM of an epoch millisecond value */
export function clockTime(ms) {
  const d = new Date(ms)
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** The next Monday after `ms` (a Monday gives the Monday a week later), as epoch ms. */
export function nextMonday(ms) {
  const day = new Date(ms).getDay()
  return ms + ((8 - day) % 7 || 7) * DAY
}

/** "2026-10-14", "14.10." or "14.10.2026" as YYYY-MM-DD, else null.
 * A date without a year that already passed this year means next year. */
export function parseDate(text, now) {
  const t = String(text ?? '').trim()
  if (/^\d{4}-\d{2}-\d{2}$/.test(t)) return isoDate(new Date(`${t}T12:00:00`).getTime()) === t ? t : null
  const m = /^(\d{1,2})\.(\d{1,2})\.?(\d{4})?$/.exec(t)
  if (!m) return null
  const year = m[3] ? Number(m[3]) : new Date(now).getFullYear()
  const probe = new Date(year, Number(m[2]) - 1, Number(m[1]))
  if (probe.getMonth() !== Number(m[2]) - 1 || probe.getDate() !== Number(m[1])) return null
  const date = `${year}-${pad(Number(m[2]))}-${pad(Number(m[1]))}`
  return !m[3] && date < isoDate(now) ? `${year + 1}-${pad(Number(m[2]))}-${pad(Number(m[1]))}` : date
}

/** "7 min", "1:05 h"; negative is 0. */
export function duration(ms) {
  const min = Math.max(0, Math.floor(ms / 60000))
  return min < 60 ? `${min} min` : `${Math.floor(min / 60)}:${pad(min % 60)} h`
}

/** Collapse whitespace and cut to `max` characters with an ellipsis */
/** One line of at most `max`, cut at a word when one ends in the last third, never mid word otherwise */
export function short(text, max) {
  const line = String(text ?? '').replace(/\s+/g, ' ').trim()
  if (line.length <= max) return line
  let cut = line.slice(0, Math.max(1, max - 1))
  const space = cut.lastIndexOf(' ')
  if (space >= Math.floor(max * 2 / 3)) cut = cut.slice(0, space).replace(/[ ,;:·-]+$/, '')
  return cut + '…'
}

/** The mod's shortcut codes: "1a", "3b 4v". Letters: a do it, b later tomorrow, c drop,
 * v advise me, w do it in its own workspace. */
export const SHORTCUT = /^\d+[abcvw](\s+\d+[abcvw])*$/

/** Parsed codes as [{n, letter}], or null when the text is not a code line */
export function parseShortcut(text) {
  const t = String(text ?? '').trim().toLowerCase()
  if (!SHORTCUT.test(t)) return null
  return t.split(/\s+/).map(code => ({ n: Number(code.slice(0, -1)), letter: code.slice(-1) }))
}

/** Where a row comes from, as the server classified it (lib/bridge_cockpit/origin.py): the category, a word key
 * (a board's name, the kind of a task or stream), a short detail, the raw text as written, a ref, and whether a click
 * in the cockpit filed it. The page never parses a source itself */
export const ORIGIN_CATEGORIES = ['github', 'tracker', 'calendar', 'bot', 'session', 'skill', 'work', 'person', 'bridge', 'other']
export const WORK_KINDS = ['task', 'stream', 'done_task', 'done_stream']

export function originOf(row) {
  const o = row?.origin ?? null
  return o && ORIGIN_CATEGORIES.includes(o.category) ? o : null
}

/** Whether the task or stream a row is, or is about, is a task, a stream, a closed task or an ended stream: the
 * server's work_kind, else the task row of that slug (indexRows), else the stream flag of an older server */
export function workKindOf(row, s) {
  if (WORK_KINDS.includes(row?.work_kind)) return row.work_kind
  const slug = row?.task ?? row?.about_task ?? null
  if (slug) {
    const k = indexRows(s?.model).get(`task:${slug}`)?.work_kind
    if (WORK_KINDS.includes(k)) return k
  }
  if (row?.task) return row.stream ? 'stream' : 'task'
  if (row?.about_task) return row.about_kind === 'stream' ? 'stream' : 'task'
  return null
}

/** What a row is, the second axis beside its section (which says what it needs from you): 'task' finite work
 * under work/tasks/, 'stream' long-running work under work/streams/, 'done_task' and 'done_stream' the same once
 * closed under work/done/, 'inbox' a report in the inbox, 'issue' an issue on a board (owner/repo#n), each of these
 * two with `task` and `taskKind` for the task or stream it is about, 'other' an item of another briefing source
 * (an application, a deadline, a check). Shown first on every row (views/day.js KindTag) */
export function rowKind(row, s) {
  if (row?.inbox_id) {
    const task = row.task ?? row.about_task ?? null
    return { kind: 'inbox', task, taskKind: task ? workKindOf(row, s) : null }
  }
  if (typeof row?.ref === 'string' && /^[\w.-]+\/[\w.-]+#\d+$/.test(row.ref)) {
    const task = row.about_task ?? row.task ?? null
    return { kind: 'issue', ref: row.ref, task, taskKind: task ? workKindOf(row, s) : null }
  }
  // 'done': closed under work/done/ with no word on whether it was a task or a stream (an older server's search hit)
  if (row?.task) return { kind: row.work_kind === 'done' ? 'done' : workKindOf(row, s) ?? 'task', task: row.task }
  return { kind: 'other', source: row?.sources?.[0] ?? null }
}

/** The work kind of a place under work/ (a search hit's path): a task, a stream, or 'done' for closed under
 * work/done/, where the path alone cannot say whether it was a task or a stream (the server's work_kind can) */
export function placeKind(path) {
  const m = /^work\/(tasks|streams|done)\//.exec(String(path ?? ''))
  return m ? { tasks: 'task', streams: 'stream', done: 'done' }[m[1]] : null
}

/** A page item (By source, the Jev list, a board row) in the shape KindTag and OriginTag read: an inbox item, an
 * issue (its board facts or its row id), a task, else an item; with the task or stream a board row is about */
export function itemRow(it) {
  const gh = it?.gh ?? null
  const id = typeof it?.row_id === 'string' && /^[\w.-]+\/[\w.-]+#\d+$/.test(it.row_id) ? it.row_id : null
  const ref = gh?.repo && Number.isInteger(gh?.number) ? `${gh.repo}#${gh.number}` : id
  const about = it?.task ? null : (gh?.task ?? null)
  return { key: it?.key ?? null, inbox_id: it?.inbox && !ref ? it.inbox : null, task: it?.task ?? null, ref,
    about_task: about, about_kind: it?.about_kind ?? (about ? (gh?.stream ? 'stream' : 'task') : null),
    work_kind: it?.work_kind ?? null, origin: it?.origin ?? null, stream: false, sources: [] }
}

/** The rows of a section by the repo of their issue (owner/repo#n), in the order a repo first shows up; rows
 * without an issue form a last group with repo null. The day list groups the board section this way */
export function repoGroups(rows) {
  const groups = new Map()
  for (const r of rows ?? []) {
    const k = rowKind(r)
    const repo = k.kind === 'issue' ? k.ref.split('#')[0] : null
    if (!groups.has(repo)) groups.set(repo, [])
    groups.get(repo).push(r)
  }
  const out = [...groups].filter(([repo]) => repo !== null).map(([repo, list]) => ({ repo, rows: list }))
  return groups.has(null) ? [...out, { repo: null, rows: groups.get(null) }] : out
}

/** Which start button a row shows, the same on every view (views/day.js StartMenu):
 * 'tab' its agent tab runs (go there), 'restart' the tab died, 'approved' the yes is given (take it back),
 * 'note' waiting or yours alone (a start needs a sentence of yours), 'do' everything else. */
export function startMode(row) {
  if (row?.tab) return row.tab.live ? 'tab' : 'restart'
  if (row?.inbox_state === 'approved') return 'approved'
  if (row?.bucket === 'waiting' || (row?.inbox_id && row?.gate === 'only-you')) return 'note'
  return 'do'
}

/** Why a/w (start) is refused on a row, as in the mod's shortcut hook and card buttons:
 * 'approved', 'waiting', 'only_you', or null when starting is fine. */
export function startRefusal(row) {
  if (!row) return null
  if (row.inbox_state === 'approved') return 'approved'
  if (row.bucket === 'waiting') return 'waiting'
  if (row.inbox_id && row.gate === 'only-you') return 'only_you'
  return null
}

/**
 * Turn parsed codes into a plan, the way the mod's shortcut hook does (register.tsx):
 * rows with a live tab jump instead of a/v/w; a/w refused for only-you, waiting and
 * approved rows; all a rows together, all w rows together, all v rows together; b per row.
 * c is Discard from the close menu: an inbox row asks why (`askDrop`, one at a time), a task or
 * any other closable row closes as not doing, a stream never closes and is refused.
 * `rowFor(n)` returns the row numbered n or undefined.
 */
export function planShortcut(codes, rowFor) {
  const plan = { missing: [], jump: [], refused: [], do: [], ws: [], advise: [], later: [], decline: [], askDrop: [] }
  for (const { n, letter } of codes) {
    const row = rowFor(n)
    if (!row) {
      plan.missing.push(n)
      continue
    }
    if (row.tab && row.tab.live && 'avw'.includes(letter)) plan.jump.push({ n, row })
    else if ('aw'.includes(letter) && startRefusal(row)) plan.refused.push({ n, row, reason: startRefusal(row) })
    else if (letter === 'b') plan.later.push({ n, row })
    else if (letter === 'c' && row.inbox_id) plan.askDrop.push({ n, row })
    else if (letter === 'c' && (row.settle ?? []).length) plan.decline.push({ n, row })
    else if (letter === 'c') plan.refused.push({ n, row, reason: 'stream' })
    else if (letter === 'v') plan.advise.push({ n, row })
    else if (letter === 'w') plan.ws.push({ n, row })
    else plan.do.push({ n, row })
  }
  return plan
}

/** The letter of a single-key row shortcut (a v c b w), or null; an auto-repeat keydown is none */
export function letterShortcut(e) {
  if (!e || e.repeat) return null
  const key = e.key
  return typeof key === 'string' && key.length === 1 && 'avcbw'.includes(key) ? key : null
}

/** The keys of a bulk action that are not busy yet: a row already in flight is skipped */
export function freeKeys(keys, busy) {
  return keys.filter(k => !busy?.[k])
}

/** The busy key of one row's step (row_action): its page, section and index, so one row in flight leaves the others free */
export function rowActionKey({ page, section, index }) {
  return `row_action:${page}:${section}:${index}`
}

/** The busy key of an action: its row, tab or conversation, the joined keys of a bulk, else the verb */
export function busyKey(verb, args) {
  if (verb === 'row_action' && args?.index != null) return rowActionKey(args)
  return args?.key ?? args?.tab_ref ?? (args?.keys ? args.keys.join(',') : args?.conv ? `quick:${args.conv}` : verb)
}

// a toggle on the start page, carrying a row key but no action on the row: a quick second flip still goes
const BUSY_TOGGLES = new Set(['pin'])

/**
 * How `act` holds an action against the busy map. `key` is busyKey of the args as asked, so the
 * bulk buttons that check the joined list stay busy; `args` and `rows` leave out the rows already
 * in flight, named in `skipped`; `refused` when nothing is left to send. `refuse` only for an
 * action on rows (a key, a tab, a bulk): settings and questions are not held back.
 */
export function planBusy(verb, args = {}, busy = {}) {
  const key = busyKey(verb, args)
  const bulk = !!args.keys?.length
  const rows = bulk ? freeKeys(args.keys, busy) : []
  const skipped = bulk ? args.keys.filter(k => !rows.includes(k)) : []
  const onRows = bulk || args.key != null || args.tab_ref != null
  return {
    key, rows, skipped,
    args: bulk ? { ...args, keys: rows } : args,
    refused: bulk && !rows.length,
    refuse: onRows && !BUSY_TOGGLES.has(verb),
  }
}

/**
 * `withBusy(key, what, fn, { rows, refuse })`: mark `key` (and each row key of a bulk) busy while
 * fn runs, and clear them however fn ends. With `refuse`, a key or row already busy runs nothing,
 * calls `onRefused(keys)` and returns null, so a shortcut, which bypasses the disabled button,
 * cannot send the same row action twice. Without it, as for settings and questions, fn always runs.
 * `getBusy()` reads the busy map, `updateBusy(f)` replaces it with f(busy).
 */
export function createWithBusy(getBusy, updateBusy, onRefused = () => {}) {
  return async function withBusy(key, what, fn, { rows = [], refuse = false } = {}) {
    const keys = [...new Set([key, ...rows])]
    const busy = getBusy() ?? {}
    if (refuse && keys.some(k => busy[k])) {
      onRefused(keys)
      return null
    }
    updateBusy(b => ({ ...b, ...Object.fromEntries(keys.map(k => [k, what])) }))
    try {
      return await fn()
    } finally {
      updateBusy(b => {
        const next = { ...b }
        for (const k of keys) delete next[k]
        return next
      })
    }
  }
}

/** What a failed answer does: a 401 goes to the sign-in page, anything else leaves an error note */
export function createFailNote(onUnauthorized, onError) {
  return res => (res?.status === 401 ? onUnauthorized(res) : onError(res))
}

/** The busy key of a triage run, so a second click while one is pending sends nothing */
export const TRIAGE_BUSY = 'triage_run'

/** The triage counts as running while the server says so and while its request is still out */
export function triageRunning(s) {
  return !!s.triage?.running || !!s.ui?.busy?.[TRIAGE_BUSY]
}

/** The loads of the Workers tab, the history drawer and the triage run; a failed answer goes to `fail`,
 *  never into an empty list that reads as "nothing there" */
export function createLoaders({ api, set, fail, withBusy }) {
  return {
    // `fresh` is "check again": the server fetches every card anew, the answer comes as the agents event
    loadAgents: async (fresh = false) => {
      const res = await api.get(fresh ? '/api/agents?fresh=1' : '/api/agents')
      if (!res.ok) return fail(res)
      set(s => ({ ...s, agents: { peers: res.data.peers ?? [], convs: res.data.convs ?? [],
        ...(res.data.keep_hours != null ? { keep_hours: res.data.keep_hours } : {}) } }))
    },
    loadHistory: async () => {
      const res = await api.get('/api/history')
      if (!res.ok) return fail(res)
      set(s => ({ ...s, history: res.data.entries ?? [] }))
    },
    triageRun: fresh => withBusy(TRIAGE_BUSY, 'triage', async () => {
      const res = await api.post('/api/triage/run', { fresh: !!fresh })
      // 409 with a state is the server's answer to a run already on: show that run, it is no error
      const already = res.status === 409 && res.data?.triage
      if (!res.ok && !already) return fail(res)
      if (res.data?.triage) set(s => ({ ...s, triage: res.data.triage }))
    }, { refuse: true }),
  }
}

/** Design token for a profile mark color name. Never put a profile value into CSS. */
export function markToken(color) {
  const c = typeof color === 'string' ? color.trim().toLowerCase() : ''
  if (c === 'red') return 'danger'
  if (c === 'yellow' || c === 'orange') return 'warning'
  if (c === 'green') return 'success'
  if (c === 'blue' || c === 'cyan') return 'info'
  if (c === 'magenta' || c === 'purple') return 'secondary'
  return 'on-surface-muted'
}

/** Design token for a priority: P0 danger, P1 warning, P2 info, else muted */
export function prioToken(priority) {
  return { P0: 'danger', P1: 'warning', P2: 'info' }[priority] ?? 'on-surface-muted'
}

/** Where a board priority stands in its order: the number in it (P0, P1, "Prio 2"), then the usual words,
 *  then any other word, a row without one last */
export function prioRank(priority) {
  if (!priority) return 1000
  const n = String(priority).match(/\d+/)
  if (n) return Number(n[0])
  const word = { critical: 0, urgent: 0, highest: 0, high: 1, medium: 2, normal: 2, low: 3, lowest: 4 }[String(priority).toLowerCase()]
  return 100 + (word ?? 50)
}

// the work's own order on a GitHub page: what is stuck or waits on a review first, what nobody started last
const GH_STATE_RANK = { blocked: 0, review: 1, in_progress: 2, ready: 3, new: 4 }

/** The rows of one board in the order the person picked: by state (the work's order), newest first, or by
 *  the board's priority (P1 before P2 before P3, equal ones in the work's order); newest first breaks a tie */
export function ghSortRows(rows, by) {
  const at = it => it.gh?.changed ?? ''
  const state = it => GH_STATE_RANK[it.gh?.state] ?? 5
  return [...rows].sort((a, b) => by === 'recent'
    ? at(b).localeCompare(at(a))
    : (by === 'priority' ? prioRank(a.gh?.priority) - prioRank(b.gh?.priority) : 0) || state(a) - state(b) || at(b).localeCompare(at(a)))
}

/** Design token for an item tone */
export function toneToken(tone) {
  return { bad: 'danger', warn: 'warning', dim: 'on-surface-muted' }[tone] ?? 'info'
}

/** Design token for a drawn state (ok, warn, bad, dim): a resource, a worker, a run */
export function runToken(tone) {
  return { ok: 'success', warn: 'warning', bad: 'danger' }[tone] ?? 'on-surface-muted'
}

/** A finding that asks for a look: high or medium */
export const serious = f => f?.severity === 'high' || f?.severity === 'medium'

/** Design token for a note tone (ok, info, warn, bad) */
export function noteToken(tone) {
  return { ok: 'success', warn: 'warning', bad: 'danger' }[tone] ?? 'info'
}

/** The state a tab shows: 'idle' for one that waits but is finished (the server's `idle`), else its state */
export const tabStateKey = tab => (tab?.state === 'waiting' && tab.idle ? 'idle' : tab?.state)

/** The number on the header's Tabs button: the tabs that want you (wantsYou), not the finished ones */
export const tabsButtonCount = tabs => (tabs ?? []).filter(wantsYou).length

/** Design token for a tab state */
export function stateToken(state) {
  return { 'needs-you': 'danger', waiting: 'warning', working: 'success' }[state] ?? 'on-surface-muted'
}

export const SECTION_ORDER = ['now', 'give', 'work', 'track', 'later']

/** Every row of the model by key: the rows of all sections plus the hidden rows */
export function indexRows(model) {
  const byKey = new Map()
  if (!model) return byKey
  for (const s of model.sections ?? []) for (const r of s.rows ?? []) byKey.set(r.key, r)
  for (const r of model.hidden ?? []) if (!byKey.has(r.key)) byKey.set(r.key, r)
  for (const r of model.task_rows ?? []) if (!byKey.has(r.key)) byKey.set(r.key, r)
  return byKey
}

/** The live describe views (the `describe` event, an action's answer) a new model leaves standing: those of keys
 *  it carries no row of, since a row of the model carries its own describe view (a run the live event alone
 *  reported, of an item without a row, keeps its `running` until the server says otherwise) */
export function liveDescribeAfter(describe, model) {
  const rows = indexRows(model)
  return Object.fromEntries(Object.entries(describe ?? {}).filter(([k]) => !rows.has(k)))
}

/** The rows a section shows: every row when expanded, else the compact keys */
export function sectionRows(section, expanded, byKey, budget = 0) {
  if (!section) return []
  if (expanded) return section.rows ?? []
  const compact = (section.compact ?? []).map(k => byKey.get(k)).filter(Boolean)
  // room left in the column: the section fills up in its own order, the compact rows always stand
  if (budget <= compact.length) return compact
  const keys = new Set(compact.map(r => r.key))
  const more = (section.rows ?? []).filter(r => !keys.has(r.key)).slice(0, budget - compact.length)
  const order = new Map((section.rows ?? []).map((r, i) => [r.key, i]))
  return [...compact, ...more].sort((a, b) => (order.get(a.key) ?? 0) - (order.get(b.key) ?? 0))
}

/** How many rows a section of the day list may show beyond its compact ones: the room the column has,
 *  shared in section order. `heightPx` is the column's height, `rowPx` one row; the folded sections
 *  (compact empty: board rows, later) take nothing, they stay closed until opened */
export function rowBudgets(sections, expanded, heightPx, rowPx = 64, chromePx = 220) {
  let left = Math.max(0, Math.floor((heightPx - chromePx) / rowPx))
  const out = {}
  for (const id of SECTION_ORDER) {
    const sec = (sections ?? []).find(x => x.id === id)
    if (!sec) continue
    const base = expanded[id] ? (sec.rows ?? []).length : (sec.compact ?? []).length
    left -= base
    out[id] = 0
    if (!expanded[id] && base > 0) {
      const extra = Math.max(0, Math.min(left, (sec.rows ?? []).length - base))
      out[id] = base + extra
      left -= extra
    }
  }
  return out
}

/** When a due date falls, against today: overdue (with the days since), today, tomorrow, else later
 *  (with the days to go); null without a date. A time of day is left out, a day counts as a whole */
export function dueWhen(due, nowMs) {
  if (typeof due !== 'string' || !/^\d{4}-\d{2}-\d{2}/.test(due)) return null
  const day = s => { const [y, m, d] = s.slice(0, 10).split('-').map(Number); return Date.UTC(y, m - 1, d) }
  const n = new Date(nowMs)
  const today = Date.UTC(n.getFullYear(), n.getMonth(), n.getDate())
  const days = Math.round((day(due) - today) / 86400000)
  if (days < 0) return { kind: 'overdue', days: -days }
  return { kind: days === 0 ? 'today' : days === 1 ? 'tomorrow' : 'later', days }
}

// the word a why line starts with when it names the due date, in every language of the page
const DUE_WORDS = new RegExp(`^(${Object.values(TABLES).map(t => t.dueWord).filter(Boolean).join('|')})\\b`, 'i')

/** The why lines without the one that names the due date again: the row shows the date itself */
export function whyWithoutDue(why) {
  return (why ?? []).filter(w => !DUE_WORDS.test(String(w).trim()))
}

/** All displayed rows in card order (now, give, work, track, later), for j/k navigation; `heightPx` the day
 *  column's height, so the keys walk the same rows the column fills up to (rowBudgets) */
export function displayedRows(model, expanded, byKey, heightPx = 0) {
  if (!model) return []
  const out = []
  const budgets = rowBudgets(model.sections, expanded, heightPx)
  for (const id of SECTION_ORDER) {
    const s = (model.sections ?? []).find(x => x.id === id)
    out.push(...sectionRows(s, !!expanded[id], byKey, budgets[id] ?? 0))
  }
  return out
}

/** Number to row, from model.numbers */
export function rowByNumber(model, byKey) {
  const out = new Map()
  for (const [key, n] of Object.entries(model?.numbers ?? {})) {
    const r = byKey.get(key)
    if (r) out.set(n, r)
  }
  return out
}

const STATE_ORDER = { 'needs-you': 0, waiting: 1, working: 2, shell: 3 }

/** Tabs grouped by workspace, each group sorted needs-you, waiting, working, shell;
 * groups ordered by their most urgent tab, then by name. The control tab is left out. */
export function groupTabs(tabs) {
  const groups = new Map()
  for (const t of tabs ?? []) {
    if (t.is_control) continue
    const ws = t.workspace || ''
    if (!groups.has(ws)) groups.set(ws, [])
    groups.get(ws).push(t)
  }
  const rank = t => STATE_ORDER[t.state] ?? 4
  const out = [...groups.entries()].map(([workspace, list]) => ({
    workspace, tabs: list.slice().sort((a, b) => rank(a) - rank(b) || String(a.name).localeCompare(String(b.name))),
  }))
  out.sort((a, b) => rank(a.tabs[0]) - rank(b.tabs[0]) || a.workspace.localeCompare(b.workspace))
  return out
}

/** A text as one single-quoted shell word: a path to paste stays one argument, whatever it holds */
export function shellQuote(text) {
  return `'${String(text).replace(/'/g, "'\\''")}'`
}

/** The state a workspace shows: its most urgent tab, else what the terminal's sidebar says (claude_code) */
const SIDEBAR_STATE = { waiting: 'waiting', 'needs input': 'needs-you', running: 'working' }

/** The chat as cmux shows it (cockpit.chat_layout: workspaces): the workspaces in the terminal's order,
 *  pinned first, each with its tabs (most urgent first), the Bridge it belongs to when its folder is
 *  another Bridge's clone, and the quick chats in the control workspace; then the other Bridges on this
 *  machine that have no workspace, and the A2A agents. A workspace the list does not name (or no list
 *  at all) still shows from its tabs, marked known: false */
/** The chats a list shows, quick chats and A2A conversations alike: none with a place of its own (the start page's
 *  core and a file's suggested next step: their panels show them, a new one replaces the last) and none untouched past keep_hours (the server archives it with its
 *  next look); one still answering, or an A2A task its owner still holds, always */
export function listedChats(convs, keepHours, nowMs) {
  const cutoff = keepHours > 0 && Number.isFinite(nowMs) ? nowMs - keepHours * 3600000 : null
  return (convs ?? []).filter(x => !x.place && (x.running || x.turns?.at(-1)?.waiting || cutoff == null
    || (x.last_ms ?? x.started_ms) >= cutoff))
}

export function roomsOf(s) {
  const r = s.rooms ?? {}
  const tabs = (s.tabs?.tabs ?? []).filter(t => !t.is_control || t.workspace)
  const listed = s.tabs?.workspaces ?? []
  const bridges = r.bridges ?? []
  const chats = listedChats(s.quick?.convs, s.quick?.keep_hours, s.now)
  // the longest Bridge folder the workspace lies in; the real folder (symlinks resolved by the server) first
  const bridgeOf = w => {
    const cwd = w.cwd_real || w.cwd
    const hits = bridges.filter(b => cwd && b.path && (cwd === b.path || cwd.startsWith(`${b.path}/`)))
    return hits.sort((a, b) => b.path.length - a.path.length)[0] ?? null
  }
  const mine = (t, w) => (t.ws_ref && w.ref ? t.ws_ref === w.ref : t.workspace === w.title)
  const rank = t => STATE_ORDER[t.state] ?? 4
  const load = agentLoad(s.sessions?.sessions, s.tabs?.tabs)
  const index = new Map()   // room -> its place in the terminal's list; rooms built from tabs have none
  const room = (w, known) => {
    const own = tabs.filter(t => mine(t, w)).sort((a, b) => rank(a) - rank(b) || String(a.name).localeCompare(String(b.name)))
      .map(t => ({ ...t, load: load.byTab[t.ref] ?? noLoad() }))
    const side = (w.statuses ?? []).find(x => x.name === 'claude_code')
    const state = own.length && rank(own[0]) < 2 ? own[0].state : SIDEBAR_STATE[String(side?.text ?? '').toLowerCase()] ?? (own.length ? own[0].state : null)
    // a room built from tabs (no workspace list, e.g. tmux) takes the workspace ref its tabs all share
    const ref = w.ref ?? (own.length && own.every(t => t.ws_ref && t.ws_ref === own[0].ws_ref) ? own[0].ws_ref : null)
    const sum = ref ? load.byWorkspace[ref] ?? noLoad() : own.reduce((n, t) => addLoad(n, t.load), noLoad())
    return { ...w, ref, key: w.ref ?? `title:${w.title}`, known, tabs: own, state, load: sum, unread: w.unread ?? 0, bridge: bridgeOf(w), chats: r.control && w.title === r.control ? chats : [] }
  }
  const out = listed.map((w, i) => ({ w, i })).sort((a, b) => (b.w.pinned ? 1 : 0) - (a.w.pinned ? 1 : 0) || a.i - b.i)
    .map(x => { const w = room(x.w, true); index.set(w, x.i); return w })
  for (const t of tabs) {
    if (t.workspace && !out.some(w => mine(t, w))) out.push(room({ ref: null, title: t.workspace }, false))
  }
  // on request (a per-viewer toggle) the rooms stand by their most urgent tab; a room of shells or of no
  // tabs comes last, and the control tab, which never waits for you, does not count. Without the toggle
  // the terminal's order stays
  if (s.ui?.roomsSort === 'urgency') {
    const urgency = w => Math.min(3, ...w.tabs.filter(t => !t.is_control).map(rank))
    const at = w => index.get(w) ?? Infinity
    out.sort((a, b) => urgency(a) - urgency(b) || (b.pinned ? 1 : 0) - (a.pinned ? 1 : 0) || at(a) - at(b)
      || String(a.title).localeCompare(String(b.title)))
  }
  const placed = out.some(w => w.chats.length || (r.control && w.title === r.control))
  return {
    workspaces: out,
    chats: placed ? [] : chats,
    // a workspace the area filter left out still has its Bridge: that one is no "other" Bridge either
    bridges: bridges.filter(b => !out.some(w => w.bridge?.id === b.id)
      && !(s.tabs?.hidden_workspaces ?? []).some(w => bridgeOf(w)?.id === b.id)),
    agents: s.agents?.peers ?? [],
    waiting: tabs.filter(wantsYou).length,
  }
}

/** Tabs that want attention (waiting or long), most urgent first, without the control tab */
export function attentionTabs(tabs) {
  return (tabs ?? []).filter(t => !t.is_control && (t.waiting || t.long))
    .sort((a, b) => (STATE_ORDER[a.state] ?? 4) - (STATE_ORDER[b.state] ?? 4) || (a.since_ms ?? 0) - (b.since_ms ?? 0))
}

const STATUS_GROUPS = ['needs-you', 'waiting', 'working', 'idle', 'shell']

/** Whether a tab wants you: it needs you, or waits and has not gone idle (finished, nothing asked; the
 *  server's `idle`), and is not the control tab. Its state stays 'waiting' when idle, so a test on the
 *  state alone counts finished tabs as waiting */
export const wantsYou = t => !!t && !t.is_control && (t.state === 'needs-you' || (t.state === 'waiting' && !t.idle))

/** Every tab under its status, in the order you walk them (ui.roomsSort: status): needs you, waiting,
 *  working, idle (waiting but finished), terminal, each the longest in its state first, then by name. A state the list does not know
 *  stands with the terminals; the control tab, which never waits for you, is left out. [{ state, tabs }],
 *  no group for a status without tabs */
export function statusQueue(tabs) {
  const by = new Map(STATUS_GROUPS.map(x => [x, []]))
  for (const t of tabs ?? []) {
    if (!t.is_control) by.get(t.state === 'waiting' && t.idle ? 'idle' : by.has(t.state) ? t.state : 'shell').push(t)
  }
  const since = t => (Number.isFinite(t.since_ms) ? t.since_ms : Infinity)
  return STATUS_GROUPS.map(state => ({ state, tabs: by.get(state).sort((a, b) => since(a) - since(b) || String(a.name).localeCompare(String(b.name))) }))
    .filter(g => g.tabs.length)
}

/** Whether a tab wants you (wantsYou), under the name the views know */
export const tabWaits = wantsYou

/** The tabs that want you, in the order By status lists them: the walk on the Chat page */
export const walkRefs = tabs => statusQueue(tabs).filter(g => g.state === 'needs-you' || g.state === 'waiting')
  .flatMap(g => g.tabs.filter(wantsYou).map(t => t.ref))

/** The walk through the tabs as the lists walk theirs (queueView): the order taken when the walk began
 *  (ui.tabWalk), then every tab that started waiting since, at the end. A tab answered meanwhile keeps
 *  its place while it is open, a closed one drops out. Entries { key: ref, title, workspace }; null when
 *  `current` is not in the walk */
export function tabWalkView(tabs, snapshot, current, more = 2) {
  const byRef = new Map((tabs ?? []).map(t => [t.ref, t]))
  const start = snapshot ?? []
  const refs = [...start, ...walkRefs(tabs).filter(r => !start.includes(r))]
  const queue = refs.map(ref => ({ key: ref, title: byRef.get(ref)?.name ?? null, workspace: byRef.get(ref)?.workspace ?? null }))
  return queueView(queue, current, e => tabWaits(byRef.get(e.key)), more)
}

/** The two numbers of the running Claude sessions, one source for the Sessions tab and the start station:
 *  how many sessions there are, and how many subagents and workflows run in them */
export function sessionCounts(sessions) {
  const list = sessions ?? []
  return { sessions: list.length, agents: list.reduce((n, x) => n + (x.agents?.running_count ?? 0) + (x.workflows?.length ?? 0), 0) }
}

const noLoad = () => ({ sessions: 0, busy: 0, subagents: 0, workflows: 0 })
const addLoad = (a, b) => ({ sessions: a.sessions + b.sessions, busy: a.busy + b.busy, subagents: a.subagents + b.subagents,
  workflows: a.workflows + b.workflows })

/** What works where, for the sidebar and the header: per tab ref and per workspace ref the sessions, the
 *  busy ones, the subagents active in the last 2 minutes and the workflows that are not paused. A session
 *  without a tab of this Bridge (another folder, another Bridge on this machine) counts in `elsewhere`
 *  only, never in `total`. A workspace is joined by its ref (two workspaces may share a title); the title
 *  only when no ref is known at all */
export function agentLoad(sessions, tabs) {
  const out = { byTab: {}, byWorkspace: {}, unmapped: [], total: null, elsewhere: null }
  const refOf = new Map((tabs ?? []).filter(t => t?.ref).map(t => [t.ref, t.ws_ref]))
  const sums = () => ({ busy: 0, subagents: 0, workflows: 0, workflowAgents: 0 })
  const total = sums()
  const elsewhere = sums()
  for (const x of sessions ?? []) {
    const running = (x.workflows ?? []).filter(w => String(w?.status ?? '').toLowerCase() !== 'paused')
    const one = { sessions: 1, busy: x.status === 'busy' ? 1 : 0, subagents: x.agents?.running_count ?? 0, workflows: running.length }
    const into = x.tab ? total : elsewhere
    into.busy += one.busy
    into.subagents += one.subagents
    into.workflows += one.workflows
    into.workflowAgents += running.reduce((n, w) => n + (w.agents ?? 0), 0)
    if (!x.tab) { out.unmapped.push(x); continue }
    out.byTab[x.tab.ref] = addLoad(out.byTab[x.tab.ref] ?? noLoad(), one)
    const ws = x.tab.ws_ref || refOf.get(x.tab.ref) || `title:${x.tab.workspace}`
    out.byWorkspace[ws] = addLoad(out.byWorkspace[ws] ?? noLoad(), one)
  }
  out.total = total
  out.elsewhere = elsewhere
  return out
}

/** Seconds left of a running pass, from its remembered duration; null when unknown */
export function etaSeconds(loading, now) {
  if (!loading?.pass || !loading.eta_ms) return null
  const left = loading.eta_ms - (now - (loading.started_ms || now))
  return Math.max(1, Math.round(left / 1000))
}

/** Is the keyboard focus in a text field (then the single-key shortcuts stay off) */
export function isTypingTarget(el) {
  if (!el) return false
  const tag = (el.tagName || '').toLowerCase()
  if (tag === 'textarea' || tag === 'select') return true
  if (tag === 'input') {
    const type = (el.type || 'text').toLowerCase()
    return !['checkbox', 'radio', 'button', 'submit', 'reset'].includes(type)
  }
  return el.isContentEditable === true
}

/** Display a YYYY-MM-DD date with Intl in the page language; the raw text if unparsable */
export function formatDay(iso, lang, withYear = false) {
  if (typeof iso !== 'string' || !/^\d{4}-\d{2}-\d{2}/.test(iso)) return iso ?? ''
  const d = new Date(`${iso.slice(0, 10)}T12:00:00`)
  if (Number.isNaN(d.getTime())) return iso
  try {
    const opts = withYear ? { day: 'numeric', month: 'short', year: 'numeric' } : { weekday: 'short', day: 'numeric', month: 'short' }
    return new Intl.DateTimeFormat(lang, opts).format(d)
  } catch {
    return iso
  }
}

/** Local HH:MM:SS of an epoch ms value, via Intl */
/** Why an A2A card could not be read or a message not delivered, as one reason the page explains in
 *  plain words (text.js agentTrouble): the name does not resolve (often: this machine is not in the
 *  peer's tailnet), nothing answers, the token is refused, no card at that address, the far side
 *  fails, the answer is no card, the token is not set up here, or something else (the raw text stays) */
export function a2aTrouble(err) {
  if (!err) return null
  const e = String(err)
  if (/nodename|servname|name or service not known|getaddrinfo|no address associated/i.test(e)) return 'name'
  if (/refused the call|\b40[13]\b|token missing/i.test(e)) return 'token'
  if (/secrets is not installed|credential|keychain/i.test(e)) return 'secret'
  if (/\b404\b/.test(e)) return 'nocard'
  if (/\b5\d\d\b/.test(e)) return 'server'
  if (/^timeout$|timed out|connection refused|unreachable|host is down|no route/i.test(e)) return 'down'
  if (/expecting value|json|no json-rpc|unsupported protocol/i.test(e)) return 'garbled'
  return 'other'
}

/** The host of a card address, for the explanation of an unreadable card */
export function a2aHost(url) {
  try { return new URL(url).hostname || null } catch { return null }
}

/** When a chat was last used, short: the time today, else day and time ("14:05", "9.10. 14:05") */
export function chatStamp(ms, nowMs, lang) {
  if (typeof ms !== 'number' || !Number.isFinite(ms)) return ''
  const d = new Date(ms)
  const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`
  if (isoDate(ms) === isoDate(nowMs)) return hm
  return String(lang).startsWith('de') ? `${d.getDate()}.${d.getMonth() + 1}. ${hm}` : `${d.getMonth() + 1}/${d.getDate()} ${hm}`
}

export function formatClock(ms, lang) {
  try {
    return new Intl.DateTimeFormat(lang, { hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' }).format(new Date(ms))
  } catch {
    return clockTime(ms)
  }
}

// where a note leads (its `go`), the same small union the server sends (actions_base.py note_go): each kind with
// the one field it needs and its pattern; the band's status targets (tickerStatusItems) are the same shape
// a row key as ROW_KEY_RE takes it: the part after the kind may hold slashes but never a ".." segment
const GO_FIELDS = {
  tab: ['ref', /^[A-Za-z0-9%][A-Za-z0-9:%_.@/-]{0,63}$/],
  row: ['key', /^(inbox|task|ref|title|item):(?!(?:.*\/)?\.\.(?:\/|$)).{1,240}$/],
  item: ['key', /^(inbox|task):(?!(?:.*\/)?\.\.(?:\/|$)).{1,240}$/],
  page: ['id', /^@?[a-z0-9][a-z0-9_-]{0,63}$/],
  conv: ['id', /^g[0-9a-f]{10}$/],
  ask: ['id', /^q[0-9a-f]{10}$/],
  claude: null,
}

/** A note's target with the field of its kind only; anything else (an unknown kind, a broken field) null */
export function noteGo(go) {
  if (!go || typeof go !== 'object' || typeof go.kind !== 'string' || !Object.hasOwn(GO_FIELDS, go.kind)) return null
  const spec = GO_FIELDS[go.kind]
  if (!spec) return { kind: go.kind }
  const [field, re] = spec
  const v = go[field]
  return typeof v === 'string' && re.test(v) && !/[\x00-\x1f]/.test(v) ? { kind: go.kind, [field]: v } : null
}

/** Notes keep the newest `max` entries; an entry equal in text and tone to a toast still on screen is
 * dropped (the server broadcasts action notes that the POST also returns). Once that toast is gone the
 * same text is news again: a retry that fails the same way shows again. */
export function addNote(notes, note, now, toasts = [], max = 20) {
  if (toasts.some(t => t.text === note.text && t.tone === note.tone)) return notes
  return [...notes, { ...note, ms: now }].slice(-max)
}

// the toasts that stand at once; one more is counted in `toastsMore`, shown as one last "+N more" toast
export const TOAST_MAX = 4

/** What a pushed note does to `{ notes, toasts, toastsMore }`: a new note and, unless `toast` is false, a
 * toast with `id`. Four stay up; one pushed out is counted in `toastsMore`, never lost without a word (the
 * notes in the history keep it), and named in `out`, so its timer stops. The oldest toast without an action goes
 * first, so an Undo stays within its few seconds; only when every one has an action does the oldest go. A
 * note a visible toast already shows changes neither and comes back with `dup` set, so the caller can hand
 * a twin's action and target to that toast (giveTwin). Its `go` is kept only as noteGo takes it. */
export function pushNoteState({ notes, toasts, toastsMore = 0 }, note, now, id, toast = true) {
  const tone = note.tone ?? 'info'
  const go = noteGo(note.go)
  const next = addNote(notes, { at: note.at, text: note.text, tone, go }, now, toasts)
  if (next === notes) return { notes, toasts, toastsMore, out: [], dup: true }
  if (!toast) return { notes: next, toasts, toastsMore, out: [], dup: false }
  const t = { id, text: note.text, tone, at: note.at, action: note.action ?? null, undo: note.undo ?? null, copy: note.copy ?? null, go }
  const kept = [...toasts, t]
  const out = []
  while (kept.length > TOAST_MAX) {
    const plain = kept.findIndex(x => !x.action)
    out.push(kept.splice(plain >= 0 ? plain : 0, 1)[0].id)
  }
  return { notes: next, toasts: kept, toastsMore: toastsMore + out.length, out, toast: t, dup: false }
}

/** A note whose text a toast still up shows (pushNoteState `dup`; the server's note event is often first):
 * the twin hands that toast the action it lacks (an undo, a copy) and the place it lacks, never replaces
 * either. `{ toasts, id }` with the id whose timer starts again, or null when it has nothing to give. */
export function giveTwin(toasts, note) {
  const go = noteGo(note.go)
  const twin = toasts.find(t => t.text === note.text && ((note.action && !t.action) || (go && !t.go)))
  if (!twin) return null
  const gives = note.action && !twin.action ? { action: note.action, undo: note.undo ?? null, copy: note.copy ?? null } : {}
  return { toasts: toasts.map(t => (t === twin ? { ...t, ...gives, go: t.go ?? go } : t)), id: twin.id }
}

/** A toast dismissed: the "+N more" toast goes with the last of the others */
export function dismissState({ toasts, toastsMore = 0 }, id) {
  const left = toasts.filter(t => t.id !== id)
  return { toasts: left, toastsMore: left.length ? toastsMore : 0 }
}

/** The notes in the history opened from the "+N more" toast: the count goes, the toasts still up stay */
export function notesOpenedState() {
  return { toastsMore: 0 }
}

/** Whether a tab alert makes a toast or only a note in the history: a tab that starts waiting toasts while it is out
 *  of sight, not while its tab view is open or the Chat shows it in its work area (no tab view over it); a tab past
 *  the hour always toasts */
export function alertToasts(s, alert) {
  if (alert?.kind !== 'tab_waiting') return true
  const ui = s?.ui ?? {}
  const ref = alert.ref
  if (!ref) return true
  if (ui.tabView) return ui.tabView !== ref
  return !(ui.page === '@chat' && ui.chatArea !== 'a2a' && ui.room?.kind === 'tab' && ui.room.id === ref)
}

/** Insert or replace a relay record by id; newest first */
export function upsertRecord(records, record) {
  const rest = (records ?? []).filter(r => r.id !== record.id)
  return [record, ...rest].sort((a, b) => (b.created_ms ?? 0) - (a.created_ms ?? 0)).slice(0, 20)
}

/** The note of a refused action. A verb that ran and failed in a step brings its own note (also sent as the `note`
 *  event): that one stands alone, with the commands to copy when nothing could start them (`manual`). The generic
 *  "the action failed" beside it read as a second, different answer (18.10.) */
export function actionFailNote(res, table) {
  const data = res?.data
  if (data && typeof data.note === 'string' && data.note && !data.error) {
    const manual = Array.isArray(data.manual) ? data.manual.filter(x => typeof x === 'string' && x) : []
    return manual.length ? { text: data.note, tone: 'bad', action: 'copy', copy: manual.join('\n') } : { text: data.note, tone: 'bad' }
  }
  return { text: errorText(res?.error, table), tone: 'bad' }
}

/** What a reply (views/reply.js, views/guide.js) gets back from a failed action: a verb that ran and failed in a
 *  step (the driver refused the send) its own result, so the field shows its note; a refusal { refused, error } */
export function replyRefusal(res) {
  const data = res?.data
  if (data && data.ok === false && typeof data.note === 'string' && data.note && !data.error) return data
  return { refused: true, error: res?.error }
}

/** A line of its own [[remind: YYYY-MM-DD | what]] or [[remind: what]]: the chat's way to propose a reminder */
const REMIND_RE = /^[ \t]*\[\[remind:[ \t]*(?:(\d{4}-\d{2}-\d{2})[ \t]*\|[ \t]*)?([^\]\n|][^\]\n]{0,299}?)[ \t]*\]\][ \t]*$/gm

/** An answer's reminder markers as cards, and the answer without them */
export function chatReminders(answer) {
  const reminders = []
  const text = String(answer ?? '').replace(REMIND_RE, (_, date, what) => {
    reminders.push({ date: date ?? null, text: what.trim() })
    return ''
  }).replace(/\n{3,}/g, '\n\n').trim()
  return { text, reminders }
}

/** The chat_remind arguments of a card: its day when that is after today, else it goes to the inbox at once */
export function reminderArgs(reminder, today) {
  return reminder.date && reminder.date > today ? { text: reminder.text, until: reminder.date } : { text: reminder.text }
}

/** Text of an API error in the page language; `table` is T() */
export function errorText(error, table) {
  if (!error) return table.errors.unknown
  const entry = table.errors[error.code]
  // an entry written as a function gets the whole error: its message, or the CLI it names
  const base = (typeof entry === 'function' ? entry(error) : entry) ?? error.message ?? table.errors.unknown
  return error.field ? `${base} (${table.errorField(error.field)})` : base
}

// ---------------------------------------------------------------- connection, warnings, details, focus

/** Not open for this long: the page says the connection is lost (ms) */
export const CONN_GRACE_MS = 3000

/** The live stream is lost: refused ('down') at once, any other state than open after CONN_GRACE_MS */
export function connLost(conn, sinceMs, now) {
  if (conn === 'open') return false
  if (conn === 'down') return true
  return now - (sinceMs ?? now) >= CONN_GRACE_MS
}

/**
 * The states the page must never hide, at any width: a lost connection (the data shown no longer
 * updates), a model from the last run, a pass that failed. Each is a dot plus a written word.
 */
export function pageWarnings(s, t) {
  const out = []
  // no driver serves `launch`: every "Let AI do it" fails until workplace.driver is set (18.10.); not known yet is no warning
  const caps = s.driver?.caps
  if (Array.isArray(caps) && !caps.includes('launch')) out.push({ token: 'warning', word: t.noDriver, title: t.noDriverTitle, kind: 'driver' })
  if (connLost(s.conn, s.connMs, s.now)) out.push({ token: 'warning', word: t.connLost })
  if (s.model?.stale) out.push({ token: 'warning', word: t.staleModel })
  const ld = s.loading ?? {}
  if (ld.last_error && !ld.pass) out.push({ token: 'danger', word: t.loadFailed(short(ld.last_error.message ?? '', 48)) })
  return out
}

/**
 * A single-key shortcut acts on the list behind the overlay, so none runs while a confirmation or a
 * drawer is open; `g` then `t` (focus the tabs) still does. Escape is handled before this check.
 */
export function modalKeyAllowed(ui, key, gPending) {
  if (ui?.confirm) return false
  if (!ui?.drawer) return true
  // n and p act on the item drawer itself: they walk the list it was opened from
  if (ui.drawer === 'item' && ui.queue?.length && (key === 'n' || key === 'p')) return true
  return key === 'g' || (gPending && (key === 't' || key === 'a'))
}

/** The list a detail was opened from (ui.queue), seen from its open entry: where it stands (pos of
 *  total), the one before and the next `more + 1` after it. `alive` says whether an entry still exists
 *  (a settled one leaves the model and neither counts nor shows); the open entry counts even when it
 *  is gone itself, so the place it held stays. Null when the key is not in the queue */
export function queueView(queue, key, alive = () => true, more = 2) {
  const list = (queue ?? []).filter(e => e.key === key || alive(e))
  const i = list.findIndex(e => e.key === key)
  if (i < 0) return null
  return { pos: i + 1, total: list.length, prev: list[i - 1] ?? null, next: list.slice(i + 1, i + 2 + more) }
}

/** The entry after the open one that still exists, or null */
export const nextInQueue = (queue, key, alive = () => true) => queueView(queue, key, alive, 0)?.next[0] ?? null

/** The queue of the Today list (the briefing): every row in section order, the ones folded behind
 *  "more" included, so a detail opened there walks the whole day; each opens in the center */
export function dayQueue(model) {
  return SECTION_ORDER.flatMap(id => (model?.sections ?? []).find(x => x.id === id)?.rows ?? [])
    .map(r => ({ how: 'select', key: r.key, title: r.title }))
}

/** Every key a queue entry can still open: the briefing's rows and every inbox item or task the pages
 *  hold now (`more`: the rows a section loaded beyond its first ones) */
export function queueLiveKeys(model, more = {}) {
  const keys = new Set(indexRows(model).keys())
  const rows = [...(model?.pages ?? []).flatMap(p => (p.sections ?? []).flatMap(sec => sec.items ?? [])),
    ...Object.values(more ?? {}).flatMap(m => m?.items ?? [])]
  for (const it of rows) { const k = triageKey(it); if (k) keys.add(k) }
  return keys
}

/**
 * A detail (task or inbox entry) is fetched again when there is none, when an action touched it
 * (`stale`) or when a newer collect run came in (`ver`, the model's collected_ms). A failed load
 * waits for the retry button instead of trying on every render.
 */
export function detailNeedsLoad(entry, ver) {
  if (!entry) return true
  if (entry.status !== 'ok') return false
  return !!entry.stale || entry.ver !== ver
}

/** Marks the details of a row's inbox entry, task and Activity (Work through) as stale (after an action on that row) */
export function invalidateDetails(details, row) {
  if (!row || (!row.inbox_id && !row.task)) return details
  const mark = (table, id) => (id && table?.[id] ? { ...table, [id]: { ...table[id], stale: true } } : table ?? {})
  return { ...details, inbox: mark(details.inbox, row.inbox_id), task: mark(details.task, row.task), activity: mark(details.activity, row.key) }
}

/** The "more" lists fetched for the run the model shows; one from an older run would freeze the section */
export function freshMore(more, model) {
  const ver = model?.collected_ms
  const keep = Object.entries(more ?? {}).filter(([, v]) => model && v && v.ver === ver)
  return keep.length === Object.keys(more ?? {}).length ? more : Object.fromEntries(keep)
}

/** Where Tab moves inside a dialog of `count` focusable elements: around the ends, -1 when there is none */
export function nextFocusIndex(count, at, shift) {
  if (count <= 0) return -1
  if (at < 0) return shift ? count - 1 : 0
  return shift ? (at - 1 + count) % count : (at + 1) % count
}

/** Where an arrow key moves in a radio group, a tab list or a menu of `count` options: the arrows step
 *  around the ends, Home and End jump, any other key or an empty group gives -1 */
export function rovingIndex(count, at, key) {
  if (count <= 0) return -1
  if (key === 'Home') return 0
  if (key === 'End') return count - 1
  const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[key]
  if (!step) return -1
  if (at < 0) return step > 0 ? 0 : count - 1
  return (at + step + count) % count
}

// ---------------------------------------------------------------- task check (task.py review)

export const VERDICT_ORDER = ['close', 'stale', 'unclear', 'waiting', 'continue']

/** Design token for a check verdict: close and stale want a decision, waiting is information */
export function verdictToken(verdict) {
  return { close: 'danger', stale: 'warning', unclear: 'warning', waiting: 'info', continue: 'success' }[verdict] ?? 'on-surface-muted'
}

/** Filled and empty dots for a confidence, ●●○ */
export function confidenceDots(confidence) {
  const n = { high: 3, medium: 2, low: 1 }[confidence] ?? 0
  return '●'.repeat(n) + '○'.repeat(3 - n)
}

/** Rows that carry a verdict, filtered ('all', a verdict, 'changed') and sorted ('verdict', 'priority', 'activity') */
export function reviewRows(rows, filter = 'all', sort = 'verdict') {
  const rank = { P0: 0, P1: 1, P2: 2, P3: 3 }
  const vi = r => { const i = VERDICT_ORDER.indexOf(r.review.verdict); return i < 0 ? 9 : i }
  const quiet = r => (r.review.days_since_activity ?? -1)
  const keep = rows.filter(r => r?.review && (filter === 'all' || (filter === 'changed' ? r.review.changed : r.review.verdict === filter)))
  const by = {
    verdict: (a, b) => vi(a) - vi(b) || (rank[a.priority] ?? 4) - (rank[b.priority] ?? 4) || quiet(b) - quiet(a),
    priority: (a, b) => (rank[a.priority] ?? 4) - (rank[b.priority] ?? 4) || vi(a) - vi(b),
    activity: (a, b) => quiet(b) - quiet(a) || vi(a) - vi(b),
  }[sort] ?? (() => 0)
  return keep.slice().sort((a, b) => by(a, b) || String(a.title).localeCompare(String(b.title)))
}

/** Count per verdict, plus 'all' and 'changed' */
export function verdictCounts(rows) {
  const out = { all: 0, changed: 0 }
  for (const v of VERDICT_ORDER) out[v] = 0
  for (const r of rows) {
    if (!r?.review) continue
    out.all += 1
    out[r.review.verdict] = (out[r.review.verdict] ?? 0) + 1
    if (r.review.changed) out.changed += 1
  }
  return out
}

/** Cents as text in the page language, 0.42 -> "0,42" (de) */
export function centsText(ct, lang) {
  const n = Number(ct ?? 0)
  const text = n < 0.1 && n > 0 ? '<0.1' : n.toFixed(n < 10 ? 2 : 1)
  return lang === 'de' ? text.replace('.', ',') : text
}

// ---------------------------------------------------------------- drawings (check flow, verdict bar, agent lanes)

/** The drawn check: who answered how many. A tier draws from the one before it when that one was asked
 *  too (it cost something), since only its unclear answers go on; otherwise straight from the tasks */
export function checkFlow(last) {
  if (!last) return null
  const tiers = (last.tiers ?? []).map((x, i, all) => ({
    ...x, fromPrev: i > 0 && all[i - 1].cost_ct != null && x.answered > 0 && all[i - 1].cost_ct > 0,
  }))
  return { total: last.reviewed ?? 0, cached: last.cached ?? 0, tiers }
}

/** Segments of the verdict bar in VERDICT_ORDER: start and width as fractions of all counted rows */
export function verdictSegments(counts) {
  const total = VERDICT_ORDER.reduce((n, v) => n + (counts?.[v] ?? 0), 0)
  if (!total) return []
  let x = 0
  return VERDICT_ORDER.filter(v => (counts[v] ?? 0) > 0).map(v => {
    const seg = { verdict: v, n: counts[v], x, w: counts[v] / total }
    x += seg.w
    return seg
  })
}

/** The lane's width: the oldest running agent plus a quarter, in whole 5 minutes, 10 to 60 minutes */
export function laneWindow(agents, now) {
  const oldest = Math.max(0, ...(agents ?? []).map(a => now - (a.since_ms ?? now)))
  const five = 300000
  return Math.min(12 * five, Math.max(2 * five, Math.ceil(oldest * 1.25 / five) * five))
}

/** Where the running subagents of a session sit in a lane of the last windowMs: the start as a fraction
 *  (each runs on to the right edge), an agent older than the window starts at its left edge and says so */
export function agentLane(agents, now, windowMs = 1800000) {
  const from = now - windowMs
  return (agents ?? []).map(a => {
    const start = Math.max(from, Math.min(now, a.since_ms ?? now))
    return { id: a.id, x0: (start - from) / windowMs, older: (a.since_ms ?? now) < from }
  })
}

/** A running check against the last one: elapsed seconds and a fraction that stays below 1 until it ends */
export function runProgress(running, now, lastSec) {
  if (!running) return null
  const sec = Math.max(0, (now - running.started_ms) / 1000)
  const expected = lastSec > 0 ? lastSec : 60
  return { sec, expected, frac: Math.min(0.97, sec / expected), over: sec > expected }
}

/** The largest value among a section's gauges that have no max of their own: they compare to each other */
export function meterScale(items) {
  return Math.max(0, ...(items ?? []).map(it => (it?.meter && !it.meter.max ? it.meter.value : 0)))
}

/** A gauge as the page draws it: the fill as a fraction, the time already passed, and whether the value
 *  runs ahead of the time (more than 5 points), which is the reason to look at a quota at all */
export function meterView(meter, scale) {
  if (!meter) return null
  const top = meter.max ?? scale
  const frac = top > 0 ? Math.min(1, meter.value / top) : 0
  const pace = typeof meter.elapsed === 'number' ? meter.elapsed : null
  return { frac, pace, ahead: pace != null && frac > pace + 0.05, relative: !meter.max }
}

/** The gauge's value as text: 74 %, $12.50, 10 / 1000 EUR */
export function meterText(meter, value, lang) {
  const n = (x, d) => { const s = x.toFixed(d); return lang === 'de' ? s.replace('.', ',') : s }
  if (meter.unit === '%') return `${n(value, 0)} %`
  if (meter.unit === '$') return `$${value.toFixed(2)}`      // as the sources write dollars, with a point
  const d = Number.isInteger(meter.value) ? 0 : 2
  const max = meter.max != null && meter.unit !== '%' ? ` / ${n(meter.max, Number.isInteger(meter.max) ? 0 : 2)}` : ''
  return `${n(value, d)}${max}${meter.unit ? ` ${meter.unit}` : ''}`
}

/** A point on the gauge's half circle (center 100,100 in a 200 by 112 box): f 0 is the left end, 1 the right */
export function gaugePoint(f, r) {
  const a = Math.PI * (1 - Math.min(1, Math.max(0, f)))
  return [100 + r * Math.cos(a), 100 - r * Math.sin(a)]
}

/** The SVG path of the half circle's arc from f0 to f1 at radius r; empty when there is nothing to draw */
export function gaugeArc(f0, f1, r) {
  if (!(f1 > f0)) return ''
  const [x0, y0] = gaugePoint(f0, r)
  const [x1, y1] = gaugePoint(f1, r)
  return `M ${x0.toFixed(2)} ${y0.toFixed(2)} A ${r} ${r} 0 0 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`
}

/** The colored ranges of a gauge, only where the source named warn or bad: good, warning, bad */
export function gaugeBands(meter) {
  if (!meter?.max || (meter.warn == null && meter.bad == null)) return []
  const f = x => x / meter.max
  const cuts = [['success', 0], ...(meter.warn != null ? [['warning', f(meter.warn)]] : []),
    ...(meter.bad != null ? [['danger', f(meter.bad)]] : [])]
  return cuts.map(([token, from], i) => ({ token, from, to: i + 1 < cuts.length ? cuts[i + 1][1] : 1 }))
}

/** A section turns into gauge tiles when every row carries a gauge with its own max */
export function gaugeSection(items) {
  return (items ?? []).length > 0 && items.every(it => it?.meter?.max)
}

/** The tab view reads a tab's screen this often right after a change, and slows down to the ceiling
 *  while it stays the same */
export const SCREEN_POLL_MS = 1500
export const SCREEN_POLL_MAX_MS = 5000

/** One answer of the tab view's screen read against the screen it holds: { screen, delay }. An unchanged
 *  screen (unchanged, or the same hash in full) keeps the held object, so the view does not render again,
 *  and waits half as long again before the next read; a change is taken and the pace is fast again */
export function screenPoll(prev, data, delay = SCREEN_POLL_MS) {
  const same = !!prev && (!!data?.unchanged || (!!prev.hash && data?.hash === prev.hash))
  if (!same) return { screen: data, delay: SCREEN_POLL_MS }
  return { screen: prev, delay: Math.min(SCREEN_POLL_MAX_MS, Math.round(delay * 1.5)) }
}

/** A Claude Code terminal as chat lines: what you typed (❯ or >), what Claude says (⏺), tool output (⎿),
 *  the rest as it stands. Blank runs collapse to one, so the stream reads like a chat */
export function screenLines(text) {
  const out = []
  let kind = 'plain'
  for (const raw of String(text ?? '').split('\n')) {
    const line = raw.replace(/\s+$/, '')
    const lead = line.trimStart()
    if (!line) {
      if (out.length && out[out.length - 1].text !== '') out.push({ kind: 'gap', text: '' })
      continue
    }
    if (/^[❯>]\s/.test(lead)) kind = 'user'
    else if (lead.startsWith('⏺')) kind = 'claude'
    else if (lead.startsWith('⎿')) kind = 'tool'
    else if (/^[─━═╭╰│]/.test(lead)) kind = 'frame'
    else if (kind === 'frame' || kind === 'tool') kind = 'plain'
    out.push({ kind, text: line })
  }
  while (out.length && out[out.length - 1].kind === 'gap') out.pop()
  return out
}

// ---------------------------------------------------------------- workers tab (workload view --json)

const WORKER_TONE = { in_sync: 'ok', observed: 'ok', intentionally_absent: 'dim', 'not reported': 'dim', not_provisioned: 'dim', absent: 'bad', disabled: 'bad',
  drifted: 'warn', inventory_missing: 'warn', source_drift: 'warn', inventory_stale: 'warn' }

/** A run's state as a tone: ok, warn, bad, dim; anything unknown is warn, never silently ok */
export function workerTone(run) {
  if (run?.retired) return 'dim'
  return WORKER_TONE[run?.state] ?? (run?.state ? 'warn' : 'ok')
}

/** How a recorded run is drawn: a shape and a tone, never colour alone */
export function stripMark(entry) {
  return { ok: ['●', 'ok'], failed: ['✗', 'bad'], expired: ['◑', 'warn'], skipped: ['○', 'dim'] }[entry?.verdict] ?? ['?', 'warn']
}

/** Counts per facet value over the runs a filter leaves when that facet itself is not applied */
export function workerFacets(runs, filter = {}) {
  const out = {}
  for (const facet of ['kind', 'sphere', 'state', 'host']) {
    const rest = filterWorkers(runs, { ...filter, [facet]: null })
    out[facet] = {}
    for (const r of rest) {
      const v = r[facet] || '?'
      out[facet][v] = (out[facet][v] ?? 0) + 1
    }
  }
  return out
}

/** Search, facets and "only with a finding" */
export function filterWorkers(runs, { q = '', kind = null, sphere = null, state = null, host = null, attention = false } = {}) {
  const needle = q.trim().toLowerCase()
  return (runs ?? []).filter(r => (!kind || r.kind === kind) && (!sphere || r.sphere === sphere)
    && (!state || r.state === state) && (!host || r.host === host)
    && (!attention || (r.findings ?? []).some(serious))
    && (!needle || `${r.id} ${r.title ?? ''} ${r.purpose ?? ''} ${r.system ?? ''}`.toLowerCase().includes(needle)))
}

/** Runs grouped by system in the order the view lists its systems, the rest after them */
export function groupBySystem(runs, systems = []) {
  const order = new Map((systems ?? []).map((s, i) => [s.id, i]))
  const groups = new Map()
  for (const r of runs) {
    const key = r.system || ''
    if (!groups.has(key)) groups.set(key, { id: key, title: (systems ?? []).find(s => s.id === key)?.title ?? key, runs: [] })
    groups.get(key).runs.push(r)
  }
  return [...groups.values()].sort((a, b) => (order.get(a.id) ?? 999) - (order.get(b.id) ?? 999) || a.id.localeCompare(b.id))
}

// ---------------------------------------------------------------- drawn sections: search, state, group, tags

/** State filters of a drawn section, by the row's tone */
export const TONE_FILTERS = [['all', () => true], ['problems', it => it.tone === 'bad' || it.tone === 'warn'],
  ['ok', it => !it.tone], ['off', it => it.tone === 'dim']]
/** The tone a state filter stands for, for its dot */
export const FILTER_TONE = { ok: 'ok', problems: 'warn', off: 'dim' }
export const toneFilter = key => (TONE_FILTERS.find(([k]) => k === key) ?? TONE_FILTERS[0])[1]

/** Rows that pass the search, the state, the group and every chosen tag ({label: value}) */
export function filterRows(items, { q = '', tone = 'all', group = null, tags = {} } = {}) {
  const needle = q.trim().toLowerCase()
  const keep = toneFilter(tone)
  return (items ?? []).filter(it => keep(it) && (!group || it.group === group)
    && Object.entries(tags).every(([k, v]) => !v || it.tags?.[k] === v)
    && (!needle || `${it.title} ${it.detail ?? ''} ${it.group ?? ''} ${Object.values(it.tags ?? {}).join(' ')}`
      .toLowerCase().includes(needle)))
}

/** The tag labels worth a row of chips: each with its values and how many rows each would leave,
 *  counted with that label's own choice off. A label with one value, or more than max, is left out */
export function tagFacets(items, filter = {}, max = 16) {
  const keys = [...new Set((items ?? []).flatMap(it => Object.keys(it.tags ?? {})))]
  const out = []
  for (const key of keys) {
    const all = new Set((items ?? []).map(it => it.tags?.[key]).filter(Boolean))
    if (all.size < 2 || all.size > max) continue
    const rest = filterRows(items, { ...filter, tags: { ...(filter.tags ?? {}), [key]: null } })
    const n = {}
    for (const it of rest) if (it.tags?.[key]) n[it.tags[key]] = (n[it.tags[key]] ?? 0) + 1
    out.push({ key, values: [...all].sort((a, b) => (n[b] ?? 0) - (n[a] ?? 0) || a.localeCompare(b)).map(v => [v, n[v] ?? 0]) })
  }
  return out
}

/** Rows under their group, groups in the order their first row comes (newest first for a log);
 *  rows without a group gather under '' at the end */
export function groupRows(items) {
  const groups = new Map()
  for (const it of items ?? []) {
    const key = it.group ?? ''
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key).push(it)
  }
  const out = [...groups].map(([key, rows]) => ({ key, rows }))
  return [...out.filter(g => g.key), ...out.filter(g => !g.key)]
}

/** Short weekday names Monday first, from the platform for the page's language ("Mo", "Di" / "Mon", "Tue") */
export function weekdayNames(lang) {
  const f = new Intl.DateTimeFormat(lang, { weekday: 'short' })
  return Array.from({ length: 7 }, (_, k) => f.format(new Date(2024, 0, 1 + k)).replace(/\.$/, ''))
}

// ---------------------------------------------------------------- triage: what a row is, whether it can go, who does it

export const TRIAGE_FILTERS = ['all', 'close', 'ai', 'you', 'unclear']

/** The key a task or inbox row is sorted under (scripts/triage.py), or null for any other row */
export function triageKey(it) {
  // an inbox row names its task too: the row is the item
  return it?.inbox ? `inbox:${it.inbox}` : it?.task ? `task:${it.task}` : null
}

function triageMatch(tri, f) {
  if (f === 'close') return tri?.verdict === 'close'
  if (f === 'ai') return tri?.doer === 'ai'
  if (f === 'you') return tri?.doer === 'you'
  if (f === 'unclear') return !tri || tri.verdict === 'unclear'
  return true
}

/** Whether a row stays under a filter; a row that is neither task nor inbox item always stays */
export function triageShows(it, map, f) {
  const key = triageKey(it)
  return !key || f === 'all' || !f || triageMatch((map ?? {})[key], f)
}

/** How many sorted rows each filter would show; `all` counts every row */
export function triageCounts(items, map) {
  const out = { all: (items ?? []).length, close: 0, ai: 0, you: 0, unclear: 0 }
  for (const it of items ?? []) {
    const key = triageKey(it)
    if (!key) continue
    for (const f of TRIAGE_FILTERS.slice(1)) if (triageMatch((map ?? {})[key], f)) out[f] += 1
  }
  return out
}

/** The AI's effort as 0 to 3 dots */
export const effortDots = e => ({ small: 1, medium: 2, large: 3 })[e] ?? 0

/** Whether a row of the Status, Dates, Trackers or More page offers Do it, Advise and Settle: the page says so
 *  (`actionable`), and a row with an inbox item or a task of its own keeps that path */
export function pageItemActs(it) {
  return !!(it?.actionable && it.key && !it.inbox && !it.task)
}

/** The row a page item acts through: the briefing's own row when it has one, else one made from the
 *  item (an inbox item or a task the page lists but the briefing does not); the server checks it again */
export function actionRow(it, byKey) {
  const key = triageKey(it)
  if (!key) return pageItemActs(it) ? { key: it.key, title: it.title, settle: ['done', 'not_doing'] } : null
  const own = byKey?.get(key)
  if (own) return own
  // an inbox item that runs on (put off with what it waits on) is no row of the day: it can open again
  return it.inbox ? { key, title: it.title, inbox_id: it.inbox, settle: ['done', 'not_doing'],
    runs: (it.lines ?? []).some(l => l.kind === 'look') }
    : { key, title: it.title, task: it.task, settle: ['done', 'not_doing'], closable: true }
}

// ---------------------------------------------------------------- item drawer

const URL_RE = /\bhttps?:\/\/[^\s<>"'`]+/g

/** A text in pieces: plain runs and http(s) links, a trailing period or bracket left outside the link */
export function linkParts(value) {
  const text = typeof value === 'string' ? value : ''
  const out = []
  let at = 0
  for (const m of text.matchAll(URL_RE)) {
    let href = m[0]
    while (/[.,;:!?)\]}]$/.test(href)) href = href.slice(0, -1)
    if (m.index > at) out.push({ text: text.slice(at, m.index) })
    out.push({ href, text: href })
    at = m.index + href.length
  }
  if (at < text.length) out.push({ text: text.slice(at) })
  return out
}

function probeDate(value) {
  const m = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}:\d{2}))?/.exec(String(value ?? ''))
  return m ? `${m[3]}.${m[2]}.${m[1]}${m[4] ? ` ${m[4]}` : ''}` : String(value ?? '')
}

/** How an inbox item closes on its own (its closes_when probe), in the page's words; null without one */
export function probeText(spec, t) {
  if (!spec || typeof spec !== 'object' || Array.isArray(spec)) return null
  const p = t.probe
  for (const combine of ['all', 'any']) {
    if (Array.isArray(spec[combine])) {
      return spec[combine].map(x => probeText(x, t) ?? p.unknown).join(combine === 'all' ? ` ${p.and} ` : ` ${p.or} `)
    }
  }
  if ('gh_pr' in spec) return p.ghPr(String(spec.gh_pr), String(spec.state ?? 'merged'))
  if ('gh_issue' in spec) return p.ghIssue(String(spec.gh_issue), String(spec.state ?? 'closed'))
  if ('task_status' in spec) return p.taskStatus(String(spec.task_status), String(spec.status ?? 'done'))
  if ('path_exists' in spec) return p.pathExists(String(spec.path_exists))
  if ('after' in spec) return p.after(probeDate(spec.after))
  if ('unseen_for' in spec) return p.unseenFor(String(spec.unseen_for?.hours ?? '?'))
  if ('command' in spec) return p.command(Array.isArray(spec.command) ? spec.command.join(' ') : String(spec.command))
  return p.unknown
}

/** Events newest first; one without a time goes last. The input is left as it is */
export function newestFirst(events) {
  return [...(events ?? [])].sort((a, b) => String(b?.at ?? '').localeCompare(String(a?.at ?? '')))
}

/** What a skipped section or status row says: one left out of this pass comes with the full one, any other cannot
 *  run on this machine and says why (a missing calendar tool read "comes with the full briefing", 18.10.) */
export function skipText(x, t) {
  return x.left_out ? t.skippedSection : t.cannotRun(x.reason || '')
}

/** A skipped section an agent tab can fix: one that cannot run here, not one left out on purpose */
export function skipFixable(x) {
  return (x?.status ?? x?.state) === 'skipped' && !x.left_out
}

/** The overview's status rows, each with the tone it is drawn in: a source that failed (danger, with
 *  its reason), a probe with findings (warning), any other count (info) in view, in that order; the
 *  quiet ones (nothing to count, or a source that comes with the full pass) folded away */
export function statusSplit(rows) {
  const toned = (rows ?? []).map(x => ({
    ...x,
    tone: x.state === 'error' ? 'danger' : x.state === 'skipped' ? (x.left_out ? 'neutral' : 'warning')
      : !(Number(x.count) > 0) ? 'success' : x.probe ? 'warning' : 'info',
  }))
  const rank = ['danger', 'warning', 'info']
  const loud = rank.flatMap(tone => toned.filter(x => x.tone === tone))
  return { loud, quiet: toned.filter(x => !rank.includes(x.tone)) }
}

const WEEK = ['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU']

function weekdays(list, lang) {
  const idx = list.map(d => WEEK.indexOf(d))
  if (idx.some(i => i < 0)) return null
  const names = tableOf(lang).days
  const run = idx.length > 2 && idx.every((v, k) => k === 0 || v === idx[k - 1] + 1)
  return run ? `${names[list[0]]} ${tableOf(lang).sched.to} ${names[list[list.length - 1]]}` : list.map(d => names[d]).join(', ')
}

/** A run's schedule as `workload view` writes it (every 300s, FREQ=...;BYDAY=... at HH:MM, continuous,
 *  N path(s) watched) in words; anything else stays as it came */
export function scheduleText(when, lang = 'en') {
  const L = tableOf(lang).sched
  const w = String(when ?? '').trim()
  let m = w.match(/^every (\d+)s$/)
  if (m) {
    const sec = Number(m[1])
    const amount = sec < 60 || sec % 60 ? `${sec} s` : sec % 3600 ? `${sec / 60} min` : `${sec / 3600} h`
    return `${L.every} ${amount}`
  }
  if (w === 'continuous') return L.continuous
  m = w.match(/^(\d+) path\(s\) watched$/)
  if (m) return L.watched(Number(m[1]))
  const parts = w.split(/;\s*(?=FREQ=)/)
  const rules = parts.map(p => p.match(/^FREQ=(DAILY|WEEKLY)(?:;BYDAY=([A-Z,]+))? at (\d\d:\d\d)$/))
  if (!w || rules.some(r => !r)) return w
  const out = []
  for (const [, freq, days, at] of rules) {
    const head = freq === 'DAILY' ? L.daily : weekdays((days ?? '').split(','), lang === 'de' ? 'de' : 'en')
    if (!head) return w
    const same = out.find(o => o.head === head)
    if (same) same.times.push(at)
    else out.push({ head, times: [at] })
  }
  return out.map(o => `${o.head} ${o.times.join(', ')}`).join('; ')
}

/** The note under a run's day axis (`workload view`) in words, the last run in local time */
export function dayNoteText(note, lang = 'en') {
  const L = tableOf(lang).notes
  return String(note ?? '').split(/;\s*/).filter(Boolean).map(part => {
    if (part === 'nothing says this schedule is behind') return L.behind
    if (part === 'nothing here can judge this schedule') return L.judge
    if (part.startsWith('fires when a path changes')) return L.path
    let m = part.match(/^last run (\d\d:\d\d) local\b/)
    if (m) return L.last(m[1])
    m = part.match(/^last run (\d{4}-\d\d-\d\dT[\d:.]+Z)/)
    if (m) {
      const d = new Date(m[1])
      if (!Number.isNaN(d.getTime())) return L.last(d.toLocaleTimeString(lang, { hour: '2-digit', minute: '2-digit' }))
    }
    return part
  }).join(' · ')
}

/** A row's detail line (`a · b`) with the inbox kind and gate the server writes as machine words in the
 *  page's language; every other part stays */
export function detailText(detail, t) {
  return String(detail ?? '').split(' · ').map(p => t.item?.kindName?.[p] ?? t.gate?.[p] ?? p).join(' · ')
}

// The pages where work is handed to the AI and comes back: only there the agent tab column stands beside
// the page; everywhere else it folds to its header button and the page keeps the full width
// The chat as cmux (chat layout workspaces) holds the tabs itself, so it needs no column beside it
const RAIL = new Set(['briefing', '@chat'])
export function railShown(page, chatLayout = 'classic', hidden = false) {
  return !hidden && RAIL.has(page) && !(page === '@chat' && chatLayout === 'workspaces')
}

/** railShown for the state as it is: Work through (a view of the work tab) has its own columns, the details of
 *  the point in front on the right, so the tab column folds there too */
export function railOn(s, hidden = s?.ui?.railHidden) {
  return railShown(s?.ui?.page, s?.rooms?.layout, hidden) && !(s?.ui?.page === 'briefing' && workViewIn(s) === 'flow')
}

/** The one next step a slim tab card offers, as action keys: answer a question, go on, close a tab
 *  that filed its result or whose start is settled, else go to the tab; `can(right)` says what this cockpit
 *  may do with a tab (canTab) */
export function tabNextStep(tab, can, settled = false) {
  const own = !tab.is_control
  const finished = !!tab.filed_by || settled
  if (tab.state === 'needs-you' && can('key')) return ['yes', 'no']
  if (tab.state === 'waiting' && own && finished && can('close')) return ['close']
  if (tab.state === 'waiting' && own && !tab.filed_by) return ['go_on']
  if (can('focus')) return ['jump']
  return can('screen') ? ['view'] : []
}

/** The time a page section names beside its title: only when its source measured at another time than
 *  the pass the header names, so one screen shows one as-of time unless a source really is older */
export function sectionStamp(asOf, collectedAt) {
  return asOf && asOf !== collectedAt ? asOf : null
}

/** A tab's screen text as one plain line: no code fences, prompt marks, box rules or runs of blanks */
export function previewText(text) {
  return String(text ?? '').replace(/```/g, ' ').replace(/[\u2500-\u257f\u276f\u203a]+/g, ' ').replace(/\s+/g, ' ').trim()
}

// ---------------------------------------------------------------- the overview page: overview tiles, tokens of the week

/** A token count short in the words of text.js: 950, 340k, 1.2M, 1.6B (en), the decimal comma for de */
export function tokenText(n, lang) {
  const v = Math.max(0, Number(n) || 0)
  const U = tableOf(lang).tokens
  if (v < 1000) return String(Math.round(v))
  if (v < 1e6) return `${Math.round(v / 1000)}${U.k}`
  const [d, unit] = v < 1e9 ? [1e6, U.m] : [1e9, U.b]
  const m = (v / d).toFixed(v / d < 10 ? 1 : 0)
  return `${lang === 'de' ? m.replace('.', ',') : m}${unit}`
}

/** One tile of a page overview: how many rows its section has, how many are loud (bad or warn) and the first of
 *  them, the fullest gauge when the section is gauges, and one tone for the tile */
export function sectionTile(section) {
  const items = section?.items ?? []
  const count = section?.total ?? section?.count ?? items.length
  if (section?.status === 'error') return { count, loud: 0, tone: 'danger', note: section.reason || null, peak: null, counts: null, state: 'error' }
  if (section?.status === 'skipped') return { count, loud: 0, tone: section.left_out ? 'neutral' : 'warning', note: section.reason || null, peak: null, counts: null, state: 'skipped' }
  const loud = items.filter(it => it.tone === 'bad' || it.tone === 'warn')
  let peak = null
  let tone = loud.some(it => it.tone === 'bad') ? 'danger' : loud.length ? 'warning' : 'neutral'
  // a gauge with limits is a quota (higher is worse): the tile shows the fullest; one without is a count
  if (gaugeSection(items) && items.some(it => it.meter.warn != null || it.meter.bad != null)) {
    const top = items.reduce((a, it) => (it.meter.value / it.meter.max > a.meter.value / a.meter.max ? it : a))
    peak = { title: String(top.title ?? '').replace(/:\s*[\d.,]+\s*%?$/, ''), percent: Math.round((top.meter.value / top.meter.max) * 100) }
    const m = top.meter
    if (tone === 'neutral') tone = m.bad != null && m.value >= m.bad ? 'danger' : m.warn != null && m.value >= m.warn ? 'warning' : 'success'
  } else if (tone === 'neutral' && section?.alarm && count === 0) tone = 'success'
  const counts = gaugeSection(items) && !peak ? items.map(it => ({ title: it.title, value: it.meter.value, max: it.meter.max })) : null
  return { count, loud: loud.length, tone, note: loud[0]?.title ?? null, peak, counts, state: 'ok' }
}

export const USAGE_SOURCES = ['session', 'subagent', 'worker']

/** Today's written tokens and the usual day (the mean of the earlier days with any use; null without one) */
export function usageToday(usage) {
  const days = usage?.days ?? []
  if (!days.length) return { today: 0, usual: null }
  const earlier = days.slice(0, -1).map(d => d.output ?? 0).filter(n => n > 0)
  return { today: days[days.length - 1].output ?? 0, usual: earlier.length ? Math.round(earlier.reduce((a, b) => a + b, 0) / earlier.length) : null }
}

// ---------------------------------------------------------------- live cards on a page, stacked bars, cloud costs

/** Where a page's live cards stand: `after` maps a section id to the cards right after it, `end` the cards at the
 *  end of the page. A page without `cards:` keeps what `overview: true` alone drew (usage and noise at the end);
 *  a card after a section the page does not show goes to the end */
export function cardPlan(page) {
  const cards = Array.isArray(page?.cards) ? page.cards
    : page?.overview ? [{ id: 'usage', after: null }, { id: 'noise', after: null }] : []
  const ids = new Set((page?.sections ?? []).map(sec => sec.id))
  const plan = { after: {}, end: [] }
  const seen = new Set()
  for (const c of cards) {
    if (seen.has(c.id)) continue   // a card stands once, where it is first named
    seen.add(c.id)
    if (c.after && ids.has(c.after)) (plan.after[c.after] ??= []).push(c.id)
    else plan.end.push(c.id)
  }
  return plan
}

/** The key of the summed rest in a stacked bar (the fourth colour) */
export const SERIES_REST = '@rest'

/** Stacked bars over days: `partsOf(day)` gives {key: value}; the three largest keys over all days keep their
 *  own colour and the rest is summed (at most four series), or `order` fixes the keys. Each part is a share of
 *  the largest day; zero parts are left out */
export function stackBars(days, partsOf, { n = 3, order = null } = {}) {
  const rows = (days ?? []).map(d => ({ d, v: partsOf(d) ?? {} }))
  const sums = {}
  for (const { v } of rows) for (const [k, x] of Object.entries(v)) sums[k] = (sums[k] ?? 0) + (Number(x) || 0)
  // SERIES_REST in a day's parts (what a capped list left out) is never a named series, always in the rest
  const ranked = Object.keys(sums).filter(k => sums[k] > 0 && k !== SERIES_REST).sort((a, b) => sums[b] - sums[a])
  const top = order ?? ranked.slice(0, n)
  const rest = !order && (ranked.length > n || sums[SERIES_REST] > 0)
  const keys = rest ? [...top, SERIES_REST] : top
  const out = rows.map(({ d, v }) => {
    const parts = top.map(k => ({ key: k, value: Number(v[k]) || 0 }))
    if (rest) parts.push({ key: SERIES_REST, value: Object.entries(v).filter(([k]) => !top.includes(k)).reduce((a, [, x]) => a + (Number(x) || 0), 0) })
    const total = Object.values(v).reduce((a, x) => a + (Number(x) || 0), 0)
    return { day: d.day, provisional: d.provisional === true, total, parts }
  })
  const max = Math.max(0, ...out.map(d => d.total))
  return {
    keys, max, total: out.reduce((a, d) => a + d.total, 0),
    days: out.map(d => ({ ...d, parts: d.parts.filter(p => p.value > 0).map(p => ({ ...p, frac: max ? p.value / max : 0 })) })),
  }
}

/** Which day labels a bar chart writes: all of them when they fit `room`, else every k-th, counted back from
 *  the newest day so today always has its label */
export function shownLabels(count, room = 10) {
  const step = Math.max(1, Math.ceil(count / room))
  return Array.from({ length: Math.max(0, count) }, (_, i) => (count - 1 - i) % step === 0)
}

/** The points of a sparkline polyline over `w` x `h`, the largest value at the top */
export function sparkPoints(values, w = 60, h = 16) {
  const v = (values ?? []).map(x => Math.max(0, Number(x) || 0))
  if (!v.length) return ''
  const max = Math.max(...v)
  const y = x => +(max ? h - (x / max) * h : h).toFixed(1)
  if (v.length === 1) return `0,${y(v[0])} ${w},${y(v[0])}`
  return v.map((x, i) => `${+((i * w) / (v.length - 1)).toFixed(1)},${y(x)}`).join(' ')
}

const MONEY_SIGN = { EUR: '€', USD: '$' }

/** An amount in the words of each language: 1,23 € and 1.234,50 € in German, €1.23 and €1,234.50 in English;
 *  a whole amount without decimals (a budget of 50 €) */
export function moneyText(n, lang, currency = 'EUR') {
  const v = Number(n) || 0
  const whole = Math.abs(v - Math.round(v)) < 0.005
  const [int, dec] = Math.abs(v).toFixed(whole ? 0 : 2).split('.')
  const [group, point] = lang === 'de' ? ['.', ','] : [',', '.']
  const num = int.replace(/\B(?=(\d{3})+(?!\d))/g, group) + (dec ? point + dec : '')
  const sign = v < 0 ? '-' : ''
  const cur = MONEY_SIGN[currency] ?? currency
  if (lang === 'de') return `${sign}${num} ${cur}`
  return MONEY_SIGN[currency] ? `${sign}${cur}${num}` : `${sign}${cur} ${num}`
}

/** The budget bar of an account as shares of one width: the month so far (fill), the forecast (a marker) and the
 *  budget, which is the full width until the month runs past it. Null without a budget */
export function budgetBar(acc) {
  const budget = Number(acc?.budget_month) || 0
  if (budget <= 0) return null
  const mtd = Number(acc.month_to_date) || 0
  const fc = acc.forecast_month == null ? null : Number(acc.forecast_month) || 0
  const scale = Math.max(budget, mtd, fc ?? 0)
  return { fill: mtd / scale, forecast: fc == null ? null : fc / scale, budget: budget / scale,
    tone: mtd > budget ? 'danger' : fc != null && fc > budget ? 'warning' : 'success' }
}

const isoDay = d => d.toISOString().slice(0, 10)
const dayShift = (iso, n) => { const d = new Date(`${iso}T00:00:00Z`); d.setUTCDate(d.getUTCDate() + n); return isoDay(d) }

/** The days a cost range covers, oldest first: the last 7 or 30 days, or the calendar month, ending today */
export function costWindow(costs, range) {
  const today = costs?.today
  if (typeof today !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(today)) return []
  const n = range === 'month' ? Number(today.slice(8, 10)) : range === '30' ? 30 : 7
  return Array.from({ length: n }, (_, i) => dayShift(today, i - n + 1))
}

/** Every account's amount per day, as {day: {account id: entry}}; failed accounts have none */
function costByDay(costs) {
  const by = {}
  for (const a of costs?.accounts ?? []) {
    if (!a.ok) continue
    for (const d of a.days ?? []) (by[d.day] ??= {})[a.id] = d
  }
  return by
}

/** The cost bars of a range: a bar per day, the three dearest accounts of the range and the rest; a day is
 *  provisional when any account says so (providers settle late) */
export function costBars(costs, range) {
  const by = costByDay(costs)
  const days = costWindow(costs, range).map(day => ({ day, provisional: Object.values(by[day] ?? {}).some(e => e.provisional) }))
  return stackBars(days, d => Object.fromEntries(Object.entries(by[d.day] ?? {}).map(([id, e]) => [id, Number(e.amount) || 0])))
}

/** One day's accounts, dearest first, each with its three largest groups */
export function costDay(costs, day) {
  return (costs?.accounts ?? []).filter(a => a.ok).map(a => {
    const e = (a.days ?? []).find(d => d.day === day)
    return { id: a.id, name: a.display_name || a.id, provider: a.provider, amount: Number(e?.amount) || 0, provisional: e?.provisional === true,
      groups: Object.entries(e?.groups ?? {}).map(([g, v]) => [g, Number(v) || 0]).filter(([, v]) => v > 0).sort((x, y) => y[1] - x[1]).slice(0, 3) }
  }).filter(x => x.amount > 0).sort((x, y) => y.amount - x.amount)
}

/** The sum over a range and the month so far, over every account that answered */
export function costTotals(costs, range) {
  const ok = (costs?.accounts ?? []).filter(a => a.ok)
  return { range: costBars(costs, range).total, month: ok.reduce((a, x) => a + (Number(x.month_to_date) || 0), 0) }
}

/** What an account cost yesterday (null when it did not answer or has no such day) */
export function costYesterday(acc, today) {
  if (!acc?.ok || !today) return null
  const e = (acc.days ?? []).find(d => d.day === dayShift(today, -1))
  return e ? Number(e.amount) || 0 : null
}

/** One tone per account: a failed one warns, the budget bar decides the rest, no budget is neutral */
export function costTone(acc) {
  if (!acc?.ok) return 'warning'
  return budgetBar(acc)?.tone ?? 'neutral'
}

const TONE_RANK = { neutral: 0, success: 1, warning: 2, danger: 3 }

/** The overview tile: yesterday and the month so far over all accounts, seven small bars, the worst tone
 *  (a stale file warns at least) */
export function costBoard(costs) {
  const accounts = costs?.accounts ?? []
  const week = costBars(costs, '7').days
  const max = Math.max(0, ...week.map(d => d.total))
  let tone = accounts.reduce((t, a) => (TONE_RANK[costTone(a)] > TONE_RANK[t] ? costTone(a) : t), accounts.length ? 'success' : 'neutral')
  if (tone === 'neutral' && accounts.length) tone = 'success'
  if (costs?.stale && TONE_RANK[tone] < TONE_RANK.warning) tone = 'warning'
  return {
    yesterday: accounts.reduce((a, x) => a + (costYesterday(x, costs?.today) ?? 0), 0),
    month: costTotals(costs, 'month').month, tone,
    week: week.map(d => ({ day: d.day, total: d.total, frac: max ? d.total / max : 0, provisional: d.provisional })),
  }
}

/** The token ranges and the ways to split them on the overview page */
export const USAGE_RANGES = [7, 30, 90]
export const USAGE_DIMS = ['bridge', 'model', 'source', 'project']
/** The key of the tokens no Bridge instance claims */
export const NO_BRIDGE = '@none'

/** A day's written tokens split by one dimension, as {key: tokens}; a Bridge on two machines is one key.
 *  usage.py lists at most eight models, projects or Bridges per day: what the list leaves out of the day's
 *  output goes to SERIES_REST, so every dimension sums to the same day */
export function usageParts(day, dim) {
  if (dim === 'source') return Object.fromEntries(USAGE_SOURCES.map(k => [k, day?.sources?.[k]?.output ?? 0]))
  const list = dim === 'model' ? day?.models : dim === 'project' ? day?.projects : day?.bridges
  const field = dim === 'model' ? 'model' : dim === 'project' ? 'project' : 'bridge'
  const out = {}
  let listed = 0
  for (const x of list ?? []) {
    const k = x[field] ?? NO_BRIDGE
    out[k] = (out[k] ?? 0) + (x.output ?? 0)
    listed += x.output ?? 0
  }
  const left = (Number(day?.output) || 0) - listed
  if (left > 0) out[SERIES_REST] = left
  return out
}

// ---------------------------------------------------------------- the noise of the inbox

/** How long a source mute lasts; inbox.py MUTE_SOURCE_DAYS says the same */
export const MUTE_SOURCE_DAYS = 30

/** What a drop for `reason` mutes, the rule inbox.py writes: `family` is the source plus the key up to its
 *  last colon (or the kind when the key has no family), `source` the whole source for a while. Null for a
 *  reason that leaves no rule, or an item without a source */
export function muteScope(item, reason) {
  const source = item?.from
  if (!source || (reason !== 'family' && reason !== 'source')) return null
  if (reason === 'source') return { source, days: MUTE_SOURCE_DAYS }
  const key = String(item.key ?? '').replace(/:+$/, '')
  return key.includes(':') ? { source, key_prefix: key.slice(0, key.lastIndexOf(':') + 1) } : { source, kind: item.kind }
}

/** The rows of the noise card: the sources a person dropped from, most clicks first, at most `max` */
export function noiseRows(noise, max = 8) {
  return (noise?.sources ?? []).filter(r => (r.dropped ?? 0) > 0)
    .sort((a, b) => b.dropped - a.dropped || b.share - a.share || String(a.source).localeCompare(String(b.source)))
    .slice(0, max).map(r => ({ ...r, percent: Math.round((r.share ?? 0) * 100) }))
}

// ---------------------------------------------------------------- a work page in the order of Jev

/** The label a row of a work page carries: its kind's word for a section named after its kind
 *  (inbox, tasks, workplace), else the section title up to its bracket */
export function workLabel(section, kinds) {
  if (section?.id && section.id === section.kind && kinds?.[section.kind]) return kinds[section.kind]
  return String(section?.title ?? section?.id ?? '').split(' (')[0].trim()
}

const level = v => (typeof v === 'number' ? Math.round(Math.max(0, Math.min(1, v)) * 3) : null)

/** The page of group `work`: it has no tab of its own, it is the "by source" view of the work tab */
export function workPageOf(pages) {
  return (pages ?? []).find(p => p?.group === 'work') ?? null
}

/** The views of the work tab: what is due (the four blocks) always, by source where a work page exists,
 *  by Jev where that page asks for an order and Jev is switched on and has its key, the files (one task
 *  at a time, views/dossier.js) always, and Work through (views/flow.js) last while cockpit.flow.enabled is on
 *  (`flow`): extra views, the default only where cockpit.work_view says so. `allowed`, the words of
 *  cockpit.work_views (work_state views), keeps only the views it names; nothing left, or an older server that sends
 *  none, keeps them all */
export function workViews(page, jev, flow = false, allowed = null) {
  const all = ['due', ...(page ? ['area'] : []), ...(page?.jev && jev?.enabled && jev?.ready ? ['jev'] : []), 'dossier', ...(flow ? ['flow'] : [])]
  if (!Array.isArray(allowed)) return all
  const ids = new Set(allowed.map(workViewId).filter(Boolean))
  const kept = all.filter(v => ids.has(v))
  return kept.length ? kept : all
}

/** The view the work tab shows: the remembered one where it can, else the first view kept (what is due by default) */
export function workViewOf(view, page, jev, flow = false, allowed = null) {
  const views = workViews(page, jev, flow, allowed)
  return views.includes(view) ? view : views[0]
}

/** The view of the work tab under the state: workViewOf with the work page, Jev, cockpit.flow.enabled and
 *  cockpit.work_views of `s` */
export function workViewIn(s) {
  return workViewOf(s?.ui?.workView, workPageOf(s?.model?.pages), s?.jev, s?.work?.flow?.enabled === true, s?.work?.views ?? null)
}

/** Where a page id leads that is a view now: the Work through page (@flow, a stored page or a link of an older
 *  page) is the work tab in its view Work through; null for every other id */
export function flowPageFor(id) {
  return id === '@flow' ? { page: 'briefing', view: 'flow' } : null
}

// cockpit.work_view names a view by the word the docs use; the page has its own ids for them
const WORK_VIEW_IDS = { due: 'due', source: 'area', jev: 'jev', files: 'dossier', flow: 'flow' }

/** The view id a word of cockpit.work_view names, or null for anything else */
export function workViewId(word) {
  return typeof word === 'string' && Object.hasOwn(WORK_VIEW_IDS, word) ? WORK_VIEW_IDS[word] : null
}

/** The view the work tab opens on at the start of a visit: `remembered` (the last click on its switch, or null),
 *  `seen` (the config word this browser saw last, or null) and `configured` (the config word the server sends).
 *  A config that changed since this browser last saw it wins once over the remembered view; after that a click
 *  holds again. "due" counts as what a browser saw before there was a config, so the default changes nothing.
 *  Returns { view, seen }, `seen` the word to keep (null: nothing to keep, an older server or an unknown word) */
export function workViewStart(remembered, seen, configured) {
  const id = workViewId(configured)
  if (!id) return { view: remembered ?? 'due', seen: seen ?? null }
  const changed = configured !== (workViewId(seen) ? seen : 'due')
  return { view: changed ? id : remembered ?? id, seen: configured }
}

/** workViewStart over what a browser remembers, `stored` { workTab, workTabSeen } (the last click on the switch,
 *  the config word seen last). Returns { view, writes }, writes holding only the entries that change */
export function workViewWrites(stored, configured) {
  const start = workViewStart(stored?.workTab ?? null, stored?.workTabSeen ?? null, configured)
  const writes = {}
  if (start.seen && start.seen !== stored?.workTabSeen) writes.workTabSeen = start.seen
  if (start.view !== (stored?.workTab ?? null)) writes.workTab = start.view
  return { view: start.view, writes }
}

/** The rows of a work page for the order of Jev: `ranked` in Jev's order, `rest` (not sent, or new since)
 *  in page order. A row standing in two sections shows once, in the first. Each entry: {it, section, label,
 *  rank, judge}, judge being Jev's levels 0 to 3 and whether only the person can do it */
export function jevList(sections, order, kinds) {
  const byKey = new Map((order?.items ?? []).map(x => [x.key, x]))
  const seen = new Set()
  const ranked = []
  const rest = []
  for (const sec of sections ?? []) {
    for (const it of sec.items ?? []) {
      const key = triageKey(it)
      const mark = key ?? `${sec.id}:${it.index}`
      if (seen.has(mark)) continue
      seen.add(mark)
      const o = key ? byKey.get(key) : null
      const row = { it, section: sec.id, label: workLabel(sec, kinds), rank: o?.rank ?? null, judge: null }
      if (o) {
        row.judge = { urgency: level(o.urgency), impact: level(o.impact), effort: level(o.effort),
          onlyMe: typeof o.only_me === 'number' ? o.only_me >= 0.5 : null }
        ranked.push(row)
      } else rest.push(row)
    }
  }
  ranked.sort((a, b) => a.rank - b.rank)
  return { ranked: order ? ranked : [], rest: order ? rest : [...ranked, ...rest] }
}

/** The kinds of rows a page holds, for its filter: one entry per label (a section's kind word or its short
 *  title) with its count and sections, empty sections left out. Only for a page holding inbox and task rows
 *  together, else none */
export function workKinds(sections, kinds) {
  const list = sections ?? []
  if (!list.some(s => s.kind === 'inbox') || !list.some(s => s.kind === 'tasks')) return []
  const out = []
  for (const sec of list) {
    const n = sec.total ?? (sec.items ?? []).length
    if (!n) continue
    const label = workLabel(sec, kinds)
    const k = out.find(x => x.label === label)
    if (k) { k.n += n; k.sections.push(sec.id) } else out.push({ label, n, sections: [sec.id] })
  }
  return out
}

/** Where the task check stands when inbox and tasks share a page: that page and the label of its tasks
 *  section ({page, label}), else null and the check keeps a tab of its own */
export function reviewHome(pages, kinds) {
  for (const p of pages ?? []) {
    const tasks = (p.sections ?? []).find(sec => sec.kind === 'tasks')
    if (tasks && workKinds(p.sections, kinds).length) return { page: p.id, label: workLabel(tasks, kinds) }
  }
  return null
}

/** Whether the terminal driver can do this to a tab (focus, key, screen, close); not known yet counts as yes */
export function canTab(s, verb) {
  const caps = s?.driver?.caps
  return !Array.isArray(caps) || caps.includes(verb)
}

/** Whether a tab may get a name of its own (actions.py v_tab_rename): the driver renames tabs, it is not the
 *  control session, the workplace does not know it by its name (a task, inbox item or team role), and its
 *  state is not read off its title glyph, which goes with a title of its own (a shell has none to lose) */
export function canRename(s, tab) {
  if (!tab || !canTab(s, 'rename') || tab.is_control) return false
  if (tab.slug || tab.item || tab.team) return false
  return !(tab.state_source === 'glyph' && tab.state !== 'shell')
}

/** Whether a workspace (a room of roomsOf) may get a name of its own: the driver renames workspaces, the
 *  room has a ref (a tmux room built from tabs takes the session id they share), and it is not the control
 *  workspace. Configured workspace names the server refuses (it knows the config) */
export function canRenameWorkspace(s, room) {
  if (!room?.ref || !canTab(s, 'rename_workspace')) return false
  const control = s?.rooms?.control ?? s?.tabs?.control?.name
  if (control && String(room.title ?? '').toLowerCase() === String(control).toLowerCase()) return false
  return !(room.tabs ?? []).some(t => t.is_control)
}

// ---------------------------------------------------------------- organize with AI (views/organize.js)

/** The items of an organize proposal grouped by the workspace they touch (a tab item by the workspace the tab
 *  is in), in the order of the rooms; each item with readable from and to (workspace titles for a move, colour
 *  names, '' for nothing) and its subject (the tab's or the workspace's name). A workspace the rooms no longer
 *  show keeps its group under its ref */
export function organizeGroups(proposal, rooms) {
  const spaces = rooms?.workspaces ?? []
  const byRef = new Map(spaces.filter(w => w.ref).map(w => [w.ref, w]))
  const tabOf = new Map(spaces.flatMap(w => (w.tabs ?? []).map(t => [t.ref, { tab: t, ws: w.ref }])))
  const titleOf = ref => byRef.get(ref)?.title ?? ref
  const groups = new Map()
  for (const it of proposal?.items ?? []) {
    const isTab = it.kind === 'tab_title' || it.kind === 'tab_move'
    const found = isTab ? tabOf.get(it.ref) : null
    const ref = isTab ? (it.kind === 'tab_move' ? it.from : found?.ws ?? it.ref) : it.ref
    const text = v => (v == null ? '' : String(v))
    const item = { ...it, subject: isTab ? found?.tab.name ?? it.ref : titleOf(it.ref),
      fromText: it.kind === 'tab_move' ? titleOf(it.from) : text(it.from), toText: it.kind === 'tab_move' ? titleOf(it.to) : text(it.to) }
    if (!groups.has(ref)) groups.set(ref, { ref, title: titleOf(ref), items: [] })
    groups.get(ref).items.push(item)
  }
  const at = ref => { const i = spaces.findIndex(w => w.ref === ref); return i < 0 ? Infinity : i }
  return [...groups.values()].sort((a, b) => at(a.ref) - at(b.ref))
}

/** The ticks of an organize proposal, { id: true }: nothing is ticked until a person ticks it */
export const organizeTicks = {
  all: proposal => Object.fromEntries((proposal?.items ?? []).map(i => [i.id, true])),
  group: (ticks, group, on) => ({ ...ticks, ...Object.fromEntries(group.items.map(i => [i.id, !!on])) }),
  toggle: (ticks, id) => ({ ...ticks, [id]: !ticks?.[id] }),
  /** the ticked ids the proposal holds, in its order: never one it does not hold */
  ids: (ticks, proposal) => (proposal?.items ?? []).filter(i => ticks?.[i.id]).map(i => i.id),
  groupState: (ticks, group) => {
    const n = group.items.filter(i => ticks?.[i.id]).length
    return n === 0 ? 'none' : n === group.items.length ? 'all' : 'some'
  },
  canApply: (ticks, proposal) => organizeTicks.ids(ticks, proposal).length > 0,
}

// ---------------------------------------------------------------- answering a waiting tab (views/reply.js)

/** The tab states a reply may name as `expect` (actions.py TAB_STATES) */
const REPLY_STATES = new Set(['needs-you', 'waiting', 'working'])

/** A tab name the server's check takes (actions.py `tab_name`): 1 to 120 characters, no control
 *  characters. A title of only a status glyph reads as '', a long one is past it: such a reply goes
 *  without the name rather than being refused every time */
// eslint-disable-next-line no-control-regex
const CONTROL_CHARS = /[\u0000-\u001f\u007f]/
const nameOk = name => typeof name === 'string' && name.length >= 1 && name.length <= 120 && !CONTROL_CHARS.test(name)

/** What every reply to `tab` carries beyond its own args: the question it answers (seen, when one was
 *  read) and the tab's name, so the server sends nothing once the tab moved on (actions.py guard_fresh) */
function replyGuard(tab) {
  return { ...(tab.ask?.hash ? { seen: tab.ask.hash } : {}), ...(nameOk(tab.name) ? { name: tab.name } : {}) }
}

/** What ui.answered keeps of an answer sent to `tab`: the question (hash) and the occurrence of it (the
 *  tab's state and since when it is in that state), so the same words asked again later are a new question */
export function answerMark(tab, q, now) {
  return { hash: tab?.ask?.hash ?? null, q, ms: now, since: tab?.since_ms ?? null, state: tab?.state ?? null }
}

/** Whether `mark` (answerMark) answered the question `tab` shows now: the same hash, the same state, the
 *  same since. A tab that worked and asks again has a new since and gets its buttons back */
export function isAnswered(mark, tab) {
  return !!(mark?.hash && tab?.ask?.hash === mark.hash && mark.state === tab.state && mark.since === (tab.since_ms ?? null))
}

/** A typed answer to `tab`: tab_send with the state the tab is in now, the question and the name */
export function replySend(tab, text) {
  return { verb: 'tab_send', args: { tab_ref: tab.ref, text, ...(REPLY_STATES.has(tab.state) ? { expect: tab.state } : {}), ...replyGuard(tab) } }
}

/** The answers the page offers a tab, the server enforcing each (actions.py): { buttons: [{id, verb, args,
 *  label}], textBox }. A dialog (needs-you) gets one button per option it shows, never free text and never
 *  a bare yes for a choice; one that could not be read gets the tab and today's yes and no. A waiting tab
 *  gets yes and no as words only when it asks a yes or no question, go on unless its result is filed, and
 *  the text box. The control session answers through its own box. Each control needs its driver right */
export function replyOptions(tab, s, t = TABLES.en) {
  const none = { buttons: [], textBox: false }
  if (!tab) return none
  const r = t.reply
  const key = canTab(s, 'key')
  const send = canTab(s, 'send')
  const buttons = []
  const ask = tab.ask ?? null
  if (tab.state === 'needs-you') {
    const options = ask?.options ?? []
    if (options.length) {
      if (key) for (const o of options) buttons.push({ id: `option-${o.n}`, verb: 'tab_option', label: o.label, args: { tab_ref: tab.ref, n: o.n, ...replyGuard(tab) } })
      if (canTab(s, 'focus')) buttons.push({ id: 'open', verb: 'tab_jump', label: r.openTab, args: { tab_ref: tab.ref } })
    } else {
      if (canTab(s, 'focus')) buttons.push({ id: 'open', verb: 'tab_jump', label: r.openTab, args: { tab_ref: tab.ref } })
      if (key) {
        buttons.push({ id: 'yes', verb: 'tab_yes', label: r.yes, args: { tab_ref: tab.ref, ...replyGuard(tab) } })
        buttons.push({ id: 'no', verb: 'tab_no', label: r.no, args: { tab_ref: tab.ref, ...replyGuard(tab) } })
      }
    }
    return { buttons, textBox: false }
  }
  if (tab.state !== 'waiting' || tab.is_control || !send) return none
  if (ask?.yes_no) {
    buttons.push({ id: 'yes', ...replySend(tab, r.yesText), label: r.yes })
    buttons.push({ id: 'no', ...replySend(tab, r.noText), label: r.no })
  }
  if (!tab.filed_by) buttons.push({ id: 'goOn', verb: 'tab_go_on', label: r.goOn, args: { tab_ref: tab.ref, ...replyGuard(tab) } })
  return { buttons, textBox: true }
}

// ---------------------------------------------------------------- the decision guide (guide.py)

/** Which question a reading of the guide answers: the hash of the question the tab poll read, else the
 *  state and since when the tab is in it (guide.py key_of) */
export function guideKey(tab) {
  return tab?.ask?.hash ?? `${tab?.state}:${Math.trunc(tab?.since_ms || 0)}`
}

/** The guide's reading of `tab`: { status, entry }. off: the guide is off or the tab does not wait for
 *  you; none: not read yet; running; error; stale: read for another question or state than the tab shows
 *  now; fresh: its options answer what the tab asks now */
export function guideOf(s, tab) {
  const g = s?.guide
  // by state on purpose: an idle tab can still be answered, so the guide reads it too
  if (!g?.enabled || !tab || tab.is_control || (tab.state !== 'needs-you' && tab.state !== 'waiting')) return { status: 'off', entry: null }
  const entry = g.entries?.[tab.ref] ?? null
  if (!entry) return { status: 'none', entry }
  if (entry.running) return { status: 'running', entry }
  if (entry.key !== guideKey(tab) || entry.state !== tab.state) return { status: 'stale', entry }
  if (entry.error) return { status: 'error', entry }
  return { status: 'fresh', entry }
}

/** The buttons of a fresh reading, each through a reply verb that guards the tab (actions.py guard_fresh):
 *  a waiting tab's option types its words (tab_send with the question's hash, the state and the name), a
 *  dialog's option presses its number (tab_option, only with the hash it was read for). [{ id, verb, args,
 *  label, why, send, n, risky, picked }]; none without the driver's right */
export function guideChoices(tab, entry, s) {
  if (!tab || !entry) return []
  const options = entry.options ?? []
  if (tab.state === 'needs-you') {
    if (!canTab(s, 'key') || !tab.ask?.hash) return []
    return options.map((o, i) => ({ o, i })).filter(({ o }) => Number.isInteger(o.n)).map(({ o, i }) => ({
      id: `guide-${o.n}`, verb: 'tab_option', args: { tab_ref: tab.ref, n: o.n, ...replyGuard(tab) },
      label: o.label, why: o.why ?? '', send: null, n: o.n, risky: !!o.risky, picked: entry.pick === i }))
  }
  if (!canTab(s, 'send')) return []
  return options.map((o, i) => ({ o, i })).filter(({ o }) => typeof o.send === 'string' && o.send).map(({ o, i }) => ({
    id: `guide-${i}`, ...replySend(tab, o.send), label: o.label, why: o.why ?? '', send: o.send, n: null,
    risky: !!o.risky, picked: entry.pick === i }))
}

/** How long the page remembers an answer it sent to a tab (ui.answered), long enough for the tab poll
 *  to show that the tab moved on */
export const ANSWERED_KEEP_MS = 120000

/** ui.answered without the answers older than ANSWERED_KEEP_MS; the same object when nothing went */
export function pruneAnswered(answered, now) {
  const all = Object.entries(answered ?? {})
  const kept = all.filter(([, v]) => now - (v?.ms ?? 0) < ANSWERED_KEEP_MS)
  return kept.length === all.length ? (answered ?? {}) : Object.fromEntries(kept)
}

/** No terminal driver lists the tabs (neither cmux nor a driver serving `tabs`, such as tmux); before the
 *  driver answered, one counts as there */
export function noTabDriver(s) {
  return !s?.cmux?.ok && !canTab(s, 'tabs')
}

// ---------------------------------------------------------------- the start page

/** The part of the day a greeting names: night before 5 and from 22, early to 11, day to 17, evening after */
export function greetingPart(hour) {
  if (hour < 5 || hour >= 22) return 'night'
  if (hour < 11) return 'early'
  if (hour < 17) return 'day'
  return 'evening'
}

/** The page that holds the tasks (a section of kind tasks), else the briefing: where "to the tasks" leads */
export function workPageId(model) {
  return (model?.pages ?? []).find(p => (p.sections ?? []).some(x => x.kind === 'tasks'))?.id ?? 'briefing'
}

/** The start page's greeting: the part of the day from `greetings` (text.js home.greeting), the name after it */
export function greetingText(hours, person, greetings) {
  return `${greetings[greetingPart(hours)]}${person ? `, ${person}` : ''}`
}

/** The date over a start page view: weekday, day and month in the page's language */
export function dayLabel(date, lang) {
  return date.toLocaleDateString(lang === 'de' ? 'de-DE' : 'en-GB', { weekday: 'long', day: 'numeric', month: 'long' })
}

/** The cards of "continue": the agent tabs of the project without the control tab and bare shells,
 *  the ones that need you first, then waiting, then working; within a state the longest first */
export function homeContinue(tabs, project) {
  const rank = t => STATE_ORDER[t.state] ?? 4
  return (tabs ?? []).filter(t => !t.is_control && t.state !== 'shell' && inProject(t, project))
    .sort((a, b) => rank(a) - rank(b) || (a.since_ms ?? 0) - (b.since_ms ?? 0))
}

/** The agent tab that works on a task, by the task's slug */
export function tabOfTask(tabs, slug) {
  if (!slug) return null
  return (tabs ?? []).find(t => t.slug === slug) ?? null
}

/** What a gauge's pace means: its share per day against the even share of its window (the budget),
 *  and where it ends at the reset if it goes on like this. Too early in the window (under 2 %) or
 *  without a window there is nothing to reckon; a window under a day has no share per day */
export function meterPace(meter) {
  const e = meter?.elapsed
  if (!meter?.max || e == null || e < 0.02) return null
  const projected = meter.value / e
  const days = meter.window_h >= 24 ? meter.window_h / 24 : null
  const perDay = days ? meter.value / (e * days) : null
  const budget = days ? meter.max / days : null
  return { perDay, budget, projected, over: projected > meter.max }
}

/** A label as part of a tile id: lower case, no accents, words joined by hyphens */
export function tileSlug(text) {
  return String(text ?? '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase()
    .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 60)
}

const HOME_SHELVES = ['areas', 'focus', 'returns', 'pinned', 'continue', 'waiting', 'tasks', 'starts']
const HOME_OPTIONS = ['today', 'preview', 'trend', 'title', 'project', 'pulse', 'stage', 'classic', 'list', 'focusview']
const HOME_CORE = ['scan', 'brief']   // what a click on the bridge's core does; several combine
// the parts the overview can show under its table, each off until chosen (Settings, Start page)
export const DESK_PARTS = ['waiting', 'guide', 'tabs', 'day']
// the control view (areas) is the start page; the bridge, tiles, list and focus are a choice, the pinned shelf too
// (Work filters by the star). A choice saved before o:stage existed has no view option and so gets the control view
const OFF_BY_DEFAULT = new Set(['o:stage', 'o:classic', 'o:list', 'o:focusview', 'k:brief', 's:pinned'])

/** Everything the start page can show, in the order it offers it: each gauge in percent of a page (a quota),
 *  the counts of the day, every page of the profile, the shelves, and the options that change how things
 *  show. Ids are stable across loads */
export function homeCatalog(model, { workers = true } = {}) {
  const out = []
  for (const p of model?.pages ?? []) {
    for (const sec of p.sections ?? []) {
      for (const it of sec.items ?? []) {
        if (it.meter?.unit !== '%' || !it.meter.max) continue
        const label = String(it.title ?? '').replace(/:\s*[\d.,]+\s*%\s*$/, '')
        out.push({ id: `q:${sec.id}:${tileSlug(label)}`, kind: 'quota', label, it, page: p.id, section: sec.id })
      }
    }
  }
  for (const id of ['c:waiting', 'c:returns', 'c:tabs', 'c:agents', 'c:workers', 'c:next', 'c:done']) {
    if (id !== 'c:workers' || workers) out.push({ id, kind: 'count' })
  }
  for (const p of model?.pages ?? []) out.push({ id: `p:${p.id}`, kind: 'page', label: p.title, page: p })
  for (const x of HOME_SHELVES) out.push({ id: `s:${x}`, kind: 'shelf' })
  for (const x of HOME_OPTIONS) out.push({ id: `o:${x}`, kind: 'option' })
  for (const x of HOME_CORE) out.push({ id: `k:${x}`, kind: 'core' })
  for (const x of DESK_PARTS) out.push({ id: `d:${x}`, kind: 'desk' })
  return out
}

/** What a page shows before anyone chose: the first quota of a window of a day or more, what waits on you,
 *  the next date, the page with the tasks, every shelf and every option */
function homeDefaults(model, all) {
  const quota = firstQuota(all)
  const work = (model?.pages ?? []).find(p => (p.sections ?? []).some(sec => sec.kind === 'tasks'))
  return new Set([quota?.id, 'c:waiting', 'c:returns', 'c:agents', 'c:workers', 'c:next', work ? `p:${work.id}` : null,
    ...HOME_SHELVES.map(x => `s:${x}`), ...HOME_OPTIONS.map(x => `o:${x}`), ...HOME_CORE.map(x => `k:${x}`)]
    .filter(x => x && !OFF_BY_DEFAULT.has(x)))
}

function firstQuota(all) {
  return all.find(x => x.kind === 'quota' && x.it.meter.window_h >= 24) ?? all.find(x => x.kind === 'quota') ?? null
}

/** The quota "next up" names: the one the defaults take, the first with a window of a day or more */
export function homeQuota(model) {
  return firstQuota(homeCatalog(model))
}

/** What the start page shows, in its order: the choice made ({tiles, seen} from the server), else the
 *  defaults. A choice keeps its order; an entry the chooser had not offered yet when it was made comes with
 *  its default, at the end; an id that no longer exists drops out */
export function homeChosen(model, saved) {
  const all = homeCatalog(model)
  const known = new Set(all.map(x => x.id))
  const defaults = homeDefaults(model, all)
  if (!Array.isArray(saved?.tiles)) return all.map(x => x.id).filter(id => defaults.has(id))
  const seen = new Set(saved.seen ?? [])
  const kept = saved.tiles.filter(id => known.has(id))
  const added = all.map(x => x.id).filter(id => !seen.has(id) && !kept.includes(id) && defaults.has(id))
  return [...kept, ...added]
}

/** The ids of a list `among` picks keep their places, and fill them in a new order */
function refill(list, among, order) {
  let i = 0
  return list.map(id => (among(id) ? order[i++] : id))
}

/** An id moved one place earlier (-1) or later (+1) among the ids `among` picks, past whatever stands
 *  between them in the list (the stations of the start page between its shelves and options) */
export function moveAmong(list, among, id, step) {
  const order = list.filter(among)
  const i = order.indexOf(id)
  const j = i + step
  if (i < 0 || j < 0 || j >= order.length) return list
  const next = order.slice()
  next[i] = order[j]
  next[j] = id
  return refill(list, among, next)
}

/** An id dropped on another among the ids `among` picks: it takes that one's place, the ones between move by one */
export function dropAmong(list, among, id, target) {
  const order = list.filter(among)
  const from = order.indexOf(id)
  const to = order.indexOf(target)
  if (from < 0 || to < 0 || from === to) return list
  const next = order.filter(x => x !== id)
  next.splice(to, 0, id)
  return refill(list, among, next)
}

const HOME_VIEWS = { list: 'o:list', focus: 'o:focusview', tiles: 'o:classic', stage: 'o:stage' }   // in the order one wins over the next

/** The start page's view from what is chosen: the list, the focus, the tiles of before, the bridge, else
 *  the control view ('areas': one head line, the areas, next up) */
export function homeView(chosen) {
  const on = new Set(chosen ?? [])
  return Object.keys(HOME_VIEWS).find(v => on.has(HOME_VIEWS[v])) ?? 'areas'
}

/** The chosen list with one view picked: every view option out, the picked one at the end */
export function homeViewSet(chosen, view) {
  const all = Object.values(HOME_VIEWS)
  const rest = (chosen ?? []).filter(id => !all.includes(id))
  return HOME_VIEWS[view] ? [...rest, HOME_VIEWS[view]] : rest
}

/** The parts of the list view, each thing once in the order the page reads: the one next step, the tabs
 *  that ask you, the rows that wait on you, the pinned rows, the tasks, then the tabs that work and the
 *  ones that rest. A tab that belongs to a shown row stands on that row (`tabOf`), not again on its own */
export function homeListParts(tabs, model, { project = null, pins = [] } = {}) {
  const live = (tabs ?? []).filter(x => !x.is_control && x.state !== 'shell' && inProject(x, project))
  const rows = id => ((model?.sections ?? []).find(x => x.id === id)?.rows ?? []).filter(r => inProject(r, project))
  const pick = focusPick(live, { ...model, sections: [{ id: 'now', rows: rows('now') }, { id: 'work', rows: rows('work') }] })
  // a tab that asks for a row's work leads as that row, the tab on it
  const owner = pick?.kind === 'tab' && pick.tab.slug ? [...rows('now'), ...rows('work')].find(r => r.task === pick.tab.slug) : null
  const lead = owner ? { kind: 'row', row: owner } : pick
  const seenRows = new Set(lead?.kind === 'row' ? [lead.row.key] : [])
  const take = list => list.filter(r => !seenRows.has(r.key) && seenRows.add(r.key))
  const waiting = take(rows('now'))
  const byKey = new Map([...rows('now'), ...rows('work')].map(r => [r.key, r]))
  const pinned = take((pins ?? []).map(k => byKey.get(k)).filter(Boolean))
  const tasks = take(rows('work').filter(r => r.task))
  const shown = [...(lead?.kind === 'row' ? [lead.row] : []), ...waiting, ...pinned, ...tasks]
  const bound = new Map(shown.map(r => [r.key, tabOfTask(live, r.task)]).filter(([, tb]) => tb))
  const seenTabs = new Set([...(lead?.kind === 'tab' ? [lead.tab.ref] : []), ...[...bound.values()].map(tb => tb.ref)])
  const free = state => live.filter(x => x.state === state && !seenTabs.has(x.ref))
  // resting by state on purpose: a tab gone idle rests there too, it asks nothing
  return { lead, asking: free('needs-you'), waiting, pinned, tasks, running: free('working'), resting: free('waiting'),
    tabOf: key => bound.get(key) ?? null }
}

/** The one queue every walk takes, in one order: a tab that asks, a result that waits, an open inbox item,
 *  then the tasks; what merely runs or rests is not yours to take. `scope` picks whose parts it reads:
 *  - 'focus' (the start page, homeListParts): its lead first, then the tabs that ask, the rows that wait on
 *    you, and of the tasks only P0 and P1, as the focus has always shown it;
 *  - 'dossier' (the files view, dossierParts): one entry per task (a file), at the place of the first reason
 *    that names it, every priority; a file is {kind: 'dossier', id, slug, row, reason, tab?, result?, item?},
 *    `row` its task row. A tab, a result or an item opens a file from `files`, a task on its own only from
 *    `tasks`. Backlog, blocked and resting tasks stand in neither, so no file opens for them */
export function queueOf(parts, { scope = 'focus' } = {}) {
  if (scope === 'dossier') {
    // a file is its task row: the row keyed task:<slug> where one stands, else the first that names the task
    const bySlug = new Map()
    for (const r of [...(parts?.files ?? []), ...(parts?.tasks ?? [])]) {
      if (!bySlug.has(r.task) || (r.key === `task:${r.task}` && bySlug.get(r.task).key !== r.key)) bySlug.set(r.task, r)
    }
    const files = new Map()
    const add = (slug, reason, extra) => {
      if (!slug || !bySlug.has(slug) || files.has(slug)) return
      const row = bySlug.get(slug)
      files.set(slug, { kind: 'dossier', id: row.key, slug, row, reason, ...extra })
    }
    for (const t of parts?.asking ?? []) add(t.slug, 'tab', { tab: t })
    for (const r of parts?.results ?? []) add(r.slug, 'result', { result: r })
    for (const r of parts?.waiting ?? []) add(r.task, 'inbox', { item: r })
    for (const r of parts?.tasks ?? []) add(r.task, 'task', {})
    return [...files.values()]
  }
  const tab = x => ({ kind: 'tab', id: x.ref, tab: x })
  const row = r => ({ kind: 'row', id: r.key, row: r })
  const lead = parts?.lead ? [parts.lead.kind === 'tab' ? tab(parts.lead.tab) : row(parts.lead.row)] : []
  return [...lead, ...(parts?.asking ?? []).map(tab), ...(parts?.waiting ?? []).map(row),
    ...(parts?.tasks ?? []).filter(r => /^P[01]$/.test(r.priority ?? '')).map(row)]
}

/** The queue of the focus view, from the parts of the list: the one queue in its focus scope */
export function homeQueue(parts) {
  return queueOf(parts, { scope: 'focus' })
}

/** The rows of a start-page list in the order it shows them, as the queue a detail opened there walks
 *  through (ui.queue): an inbox item or task opens in its drawer, any other row beside the page, the way
 *  the start page opens them (views/home.js openWhole); a row listed twice counts once */
export function homeRowQueue(rows) {
  const seen = new Set()
  return (rows ?? []).filter(r => r?.key && !seen.has(r.key) && seen.add(r.key))
    .map(r => ({ how: /^(inbox|task):/.test(r.key) ? 'item' : 'peek', key: r.key, title: r.title, it: r, where: {} }))
}

/** Where the focus view stands in its queue (homeQueue): on the entry it was moved to (`at`, from
 *  ui.focusAt) wherever that entry stands now; once that entry is settled, on the place it held, so the
 *  next moves up into it; at the start on the first */
export function focusIndex(queue, at) {
  const n = (queue ?? []).length
  if (!n || !at) return 0
  const i = queue.findIndex(x => x.id === at.id)
  return i >= 0 ? i : Math.min(Math.max(0, at.i ?? 0), n - 1)
}

/** Where n or p moves a focus walk from `at`: { to } the step it reaches, { files: true } for n past the last
 *  step where cockpit.focus_to_files (`toFiles`) leads on into the files view, else null */
export function focusStep(queue, at, key, toFiles = false) {
  const to = focusIndex(queue, at) + (key === 'n' ? 1 : -1)
  if (queue?.[to]) return { to }
  return key === 'n' && toFiles ? { files: true } : null
}

/** The one next step of the start page: a tab that asks you, else the first row waiting on you, else the
 *  first P0 or P1 task of the backlog; nothing when there is none */
export function focusPick(tabs, model) {
  const asking = (tabs ?? []).find(t => !t.is_control && t.state === 'needs-you')
  if (asking) return { kind: 'tab', tab: asking }
  const rows = id => (model?.sections ?? []).find(x => x.id === id)?.rows ?? []
  const first = rows('now')[0]
  if (first) return { kind: 'row', row: first }
  const task = rows('work').find(r => r.task && /^P[01]$/.test(r.priority ?? ''))
  return task ? { kind: 'row', row: task } : null
}

/** The next date that has not begun, from every calendar section of the pages (rows with `at`) */
export function nextEvent(model, nowMs) {
  return upcomingEvents(model, nowMs, 1)[0] ?? null
}

/** Every coming event of the calendar sections, soonest first, at most `limit`: the list beside an opened one */
export function upcomingEvents(model, nowMs, limit = Infinity) {
  const out = []
  for (const p of model?.pages ?? []) {
    for (const sec of p.sections ?? []) {
      if (sec.kind !== 'calendar') continue
      for (const it of sec.items ?? []) {
        const ms = it.at ? Date.parse(it.at) : NaN
        if (Number.isFinite(ms) && ms > nowMs) out.push({ it, ms, page: p.id, section: sec.id })
      }
    }
  }
  return out.sort((a, b) => a.ms - b.ms).slice(0, limit)
}

/** How long until a moment, in words a countdown reads: minutes, then hours and minutes, then days and hours */
export function untilText(ms) {
  const min = Math.floor(Math.max(0, ms) / 60000)
  const h = Math.floor(min / 60)
  if (h >= 24) return `${Math.floor(h / 24)} d ${h % 24} h`
  return h ? `${h} h ${min % 60} min` : `${min} min`
}

/** Whether a row counts as waiting for you (briefing_view.asks_you): every row that is no inbox item, and of the
 *  inbox only the asks. An idea or a report filed for today stands in Now, it just asks nothing of you; an inbox
 *  row without its art (an older server) is an ask */
export function asksYou(row) {
  return !row?.inbox_id || (row.art ?? 'ask') === 'ask'
}

/** How many of a page's items belong to a project (by mark or area) */
export function countInProject(items, project) {
  return (items ?? []).filter(it => inProject(it, project)).length
}

/** The bridge of the start page (the explainer films' picture): a viewBox of 680 by 520 with the core in
 *  the middle, its rings squashed a little as seen from above */
export const STAGE = { w: 680, h: 520, cx: 340, cy: 255, rx: 250, ry: 192, squash: 0.92, rim: 128 }
export const MAX_STATIONS = 14   // beyond ten the ring widens and the stations draw compact

/** Where up to fourteen stations stand around the core: spread over an ellipse, clockwise, each with the
 *  curved link from the core's rim to it (an SVG path); more than ten widen the ellipse */
export function stageSpots(n) {
  const k = Math.min(n, MAX_STATIONS)
  const rx = k > 10 ? 292 : STAGE.rx
  const ry = k > 10 ? 210 : STAGE.ry
  const out = []
  // the stations stand between the angles, so none sits straight above or below the core
  for (let i = 0; i < k; i++) {
    const a = -Math.PI / 2 + ((i + 0.5) / k) * Math.PI * 2
    const x = STAGE.cx + rx * Math.cos(a)
    const y = STAGE.cy + ry * Math.sin(a)
    const from = { x: STAGE.cx + STAGE.rim * Math.cos(a), y: STAGE.cy + STAGE.rim * STAGE.squash * Math.sin(a) }
    // the bend: halfway, pushed sideways a little, always to the same side
    const mx = (from.x + x) / 2 - Math.sin(a) * 28
    const my = (from.y + y) / 2 + Math.cos(a) * 28
    const f = v => v.toFixed(1)
    out.push({ x, y, from, path: `M${f(from.x)} ${f(from.y)} Q${f(mx)} ${f(my)} ${f(x)} ${f(y)}` })
  }
  return out
}

/** The dust of the stage: n points from a fixed seed, so every render draws the same sky */
export function stageDust(n, seed = 1) {
  let v = seed >>> 0 || 1
  const rnd = () => ((v = (v * 1664525 + 1013904223) >>> 0) / 4294967296)
  return Array.from({ length: n }, () => ({ x: rnd() * STAGE.w, y: rnd() * STAGE.h, r: 0.6 + rnd() * 0.9, o: 0.25 + rnd() * 0.5 }))
}

/** The beat of a station's heart line, in seconds: fast and uneven when red, calmer the better it goes;
 *  a station with nothing to say has no beat */
export function pulseSpeed(tone) {
  return { danger: 0.75, warning: 1.4, info: 2.6, success: 3.6 }[tone] ?? null
}

/** What a speech recognition error says to the person: the microphone was refused, nothing was heard, the
 *  service could not be reached, or something else. Stopped by hand says nothing */
export function speechError(code) {
  if (code === 'aborted') return null
  if (['not-allowed', 'service-not-allowed', 'audio-capture'].includes(code)) return 'denied'
  if (code === 'no-speech') return 'nothing'
  if (code === 'network') return 'network'
  return 'other'
}

export const RETURN_STAGES = ['started', 'working', 'asks', 'result', 'done']

/** Where a start stands now: the server knows the answer and the close; the tab's state the page sees itself,
 *  so a tab that just began to wait shows at once, not with the next collection. A still tab asks unless the
 *  server read its screen and found no question (`idle`); a dialog (needs-you) always asks */
export function liveStage(r, tabs, nowMs) {
  if (r.stage === 'result' || r.stage === 'done') return r.stage
  const mine = (tabs ?? []).filter(t => !t.is_control && (t.ref === r.tab?.ref || t.slug === r.item || t.item === r.item))
  if (mine.some(t => t.state !== 'working')) return r.stage === 'idle' && !mine.some(t => t.state === 'needs-you') ? 'idle' : 'asks'
  if (mine.length) return 'working'
  return nowMs - r.at_ms < 180000 ? 'started' : 'lost'
}

/** The starts handed to the AI by what they want of you: done, answered or gone quiet and to check, a
 *  question, at work, or gone without a word. Newest first within a group, as the server sends them */
export function aiGroups(returns, tabs, nowMs) {
  const g = { check: [], asks: [], working: [], lost: [] }
  for (const r of returns ?? []) {
    const live = liveStage(r, tabs, nowMs)
    const to = live === 'done' || live === 'result' || live === 'idle' ? 'check' : live === 'asks' ? 'asks' : live === 'lost' ? 'lost' : 'working'
    g[to].push({ ...r, live })
  }
  return g
}

/** The tabs whose start is settled (its inbox item closed, its task done): nothing is left for them to do */
export function settledRefs(returns, tabs, nowMs) {
  const open = new Set((tabs ?? []).map(t => t.ref))
  return new Set((returns ?? []).filter(r => r.tab?.ref && open.has(r.tab.ref) && liveStage(r, tabs, nowMs) === 'done').map(r => r.tab.ref))
}

/** What the AI left for you: checks whose tab is still open, tabs settled on their own, and the questions */
export function aiWaiting(returns, tabs, nowMs) {
  const g = aiGroups(returns, tabs, nowMs)
  const open = new Set((tabs ?? []).map(t => t.ref))
  const done = new Set(g.check.filter(r => r.tab?.ref && open.has(r.tab.ref)).map(r => r.tab.ref))
  for (const t of tabs ?? []) if (t.settled && t.state === 'waiting' && !t.is_control) done.add(t.ref)
  return done.size + g.asks.length
}

/** The tone of a stage: an answer is good news, a question waits on you, work runs, a lost start is red */
export function stageTone(stage) {
  return { started: 'info', working: 'info', asks: 'warning', idle: 'muted', result: 'success', done: 'success', lost: 'danger' }[stage] ?? 'muted'
}

/** What happened between two states of the page, for the live feed: rows that came and went, a row turned
 *  urgent, a tab that now asks you, an answer in the return channel, a new finding. The first state has no
 *  before, so nothing happened yet */
export function feedEvents(prev, next, prevTabs, nextTabs, at) {
  if (!prev || !next) return []
  const out = []
  const rows = m => new Map((m.sections ?? []).filter(x => x.id === 'now').flatMap(x => x.rows ?? []).map(r => [r.key, r]))
  const a = rows(prev)
  const b = rows(next)
  for (const [key, r] of b) {
    const was = a.get(key)
    if (!was) out.push({ kind: 'new', key, title: r.title, at })
    else if (r.urgency === 'now' && was.urgency !== 'now') out.push({ kind: 'urgent', key, title: r.title, at })
  }
  for (const [key, r] of a) if (!b.has(key)) out.push({ kind: 'gone', key, title: r.title, at })
  const tabs = new Map((prevTabs ?? []).map(t => [t.ref, t]))
  for (const t of nextTabs ?? []) {
    const was = tabs.get(t.ref)
    if (was && !t.is_control && t.state === 'needs-you' && was.state !== 'needs-you') out.push({ kind: 'tabAsks', ref: t.ref, title: t.name, at })
  }
  const stage = new Map((prev.returns ?? []).map(r => [r.key, r.stage]))
  for (const r of next.returns ?? []) {
    const was = stage.get(r.key)
    if (was && was !== r.stage && (r.stage === 'result' || r.stage === 'done')) out.push({ kind: 'answer', key: r.key, title: r.title, at })
    if (was && was !== r.stage && r.stage === 'lost') out.push({ kind: 'lost', key: r.key, title: r.title, at })
  }
  const alarms = new Set((prev.alarms ?? []).map(x => `${x.page_id}/${x.section_title}`))
  for (const x of next.alarms ?? []) {
    if (!alarms.has(`${x.page_id}/${x.section_title}`)) out.push({ kind: 'alarm', page: x.page_id, title: x.section_title, at })
  }
  return out
}

/** The feed with new events in front, at most `cap`; an event that repeats the newest of its kind and row
 *  is dropped */
export function addFeed(feed, events, cap = 50) {
  const out = [...feed]
  for (const e of events) {
    if (out.some(x => x.kind === e.kind && (x.key ?? x.ref ?? x.title) === (e.key ?? e.ref ?? e.title))) continue
    out.unshift(e)
  }
  return out.sort((x, y) => y.at - x.at).slice(0, cap)
}

// ---------------------------------------------------------------- the inner room: the knowledge graph in 3D

/** The regions of the net, in the order of their anchors (graph.py `group`) */
export const GRAPH_GROUPS = ['core', 'identity', 'infra', 'workflow', 'work', 'docs', 'other']

/** A small seeded random, so one tree always grows into the same net */
export function seeded(seed = 7) {
  let x = seed >>> 0 || 1
  return () => { x ^= x << 13; x >>>= 0; x ^= x >>> 17; x ^= x << 5; x >>>= 0; return x / 4294967296 }
}

/**
 * The net to lay out: each region gets an anchor on a sphere (the core in the middle), each node starts near its
 * region's anchor. pos and vel are flat [x, y, z, ...]; adj lists each node's neighbours both ways.
 */
export function seedGraph(nodes, edges, { radius = 260, seed = 7 } = {}) {
  const rnd = seeded(seed)
  const index = new Map(nodes.map((n, i) => [n.id, i]))
  const outer = GRAPH_GROUPS.filter(g => g !== 'core')
  const anchors = { core: [0, 0, 0] }
  outer.forEach((g, i) => {
    // a Fibonacci sphere: the regions spread evenly around the core
    const y = 1 - (i + 0.5) / outer.length * 2
    const r = Math.sqrt(1 - y * y)
    const a = i * Math.PI * (3 - Math.sqrt(5))
    anchors[g] = [Math.cos(a) * r * radius, y * radius, Math.sin(a) * r * radius]
  })
  const pos = new Float32Array(nodes.length * 3)
  nodes.forEach((n, i) => {
    const [ax, ay, az] = anchors[n.group] ?? anchors.other
    pos[i * 3] = ax + (rnd() - 0.5) * 120
    pos[i * 3 + 1] = ay + (rnd() - 0.5) * 120
    pos[i * 3 + 2] = az + (rnd() - 0.5) * 120
  })
  const adj = nodes.map(() => [])
  const links = []
  for (const e of edges) {
    const a = index.get(e.s), b = index.get(e.t)
    if (a === undefined || b === undefined || a === b) continue
    links.push([a, b])
    adj[a].push(b)
    adj[b].push(a)
  }
  return { nodes, index, anchors, pos, vel: new Float32Array(nodes.length * 3), adj, links }
}

/** One step of the forces: nodes push apart, links pull, each node is drawn a little to its region. The motion left */
export function stepGraph(g, { repel = 1800, spring = 0.02, length = 46, pull = 0.004, damp = 0.82 } = {}) {
  const { pos, vel, nodes, links, anchors } = g
  const n = nodes.length
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      const dx = pos[i * 3] - pos[j * 3], dy = pos[i * 3 + 1] - pos[j * 3 + 1], dz = pos[i * 3 + 2] - pos[j * 3 + 2]
      const d2 = dx * dx + dy * dy + dz * dz + 25
      if (d2 > 90000) continue
      const f = repel / (d2 * Math.sqrt(d2))
      vel[i * 3] += dx * f; vel[i * 3 + 1] += dy * f; vel[i * 3 + 2] += dz * f
      vel[j * 3] -= dx * f; vel[j * 3 + 1] -= dy * f; vel[j * 3 + 2] -= dz * f
    }
  }
  for (const [a, b] of links) {
    const dx = pos[b * 3] - pos[a * 3], dy = pos[b * 3 + 1] - pos[a * 3 + 1], dz = pos[b * 3 + 2] - pos[a * 3 + 2]
    const d = Math.sqrt(dx * dx + dy * dy + dz * dz) || 1
    const f = (d - length) * spring / d
    vel[a * 3] += dx * f; vel[a * 3 + 1] += dy * f; vel[a * 3 + 2] += dz * f
    vel[b * 3] -= dx * f; vel[b * 3 + 1] -= dy * f; vel[b * 3 + 2] -= dz * f
  }
  let moved = 0
  for (let i = 0; i < n; i++) {
    const [ax, ay, az] = anchors[nodes[i].group] ?? anchors.other
    for (let k = 0; k < 3; k++) {
      vel[i * 3 + k] = (vel[i * 3 + k] + ([ax, ay, az][k] - pos[i * 3 + k]) * pull) * damp
      pos[i * 3 + k] += vel[i * 3 + k]
      moved += Math.abs(vel[i * 3 + k])
    }
  }
  return n ? moved / n : 0
}

/** Where a point of the net stands on the screen: x, y, its depth, and how large things near it draw (0 behind) */
export function projectPoint(x, y, z, cam, w, h) {
  const px = x - cam.target[0], py = y - cam.target[1], pz = z - cam.target[2]
  const cy = Math.cos(cam.yaw), sy = Math.sin(cam.yaw), cp = Math.cos(cam.pitch), sp = Math.sin(cam.pitch)
  const x1 = px * cy - pz * sy
  const z1 = px * sy + pz * cy
  const y2 = py * cp - z1 * sp
  const z2 = py * sp + z1 * cp
  const depth = z2 + cam.dist
  if (depth < 8) return { x: 0, y: 0, depth, scale: 0 }
  const f = (Math.min(w, h) * 0.9) / Math.tan((cam.fov ?? 1) / 2) / 2
  const scale = f / depth
  return { x: w / 2 + x1 * scale, y: h / 2 + y2 * scale, depth, scale }
}

/** The next stop of a journey: a neighbour not yet visited, the best connected first; else a jump to an unseen node */
export function nextHop(g, cur, visited, rnd = Math.random) {
  const fresh = (g.adj[cur] ?? []).filter(j => !visited.has(j))
  if (fresh.length) {
    fresh.sort((a, b) => g.adj[b].length - g.adj[a].length)
    return fresh[Math.floor(rnd() * Math.min(3, fresh.length))]
  }
  const rest = g.nodes.map((_, i) => i).filter(i => !visited.has(i) && g.adj[i].length)
  if (rest.length) return rest[Math.floor(rnd() * rest.length)]
  const any = g.adj[cur] ?? []
  return any.length ? any[Math.floor(rnd() * any.length)] : cur
}

/** The nodes a search finds, best first: the id itself, then the start of a name, then anywhere in name, title or path */
export function graphFind(nodes, q, max = 8) {
  const s = String(q ?? '').trim().toLowerCase()
  if (!s) return []
  const rank = n => {
    const label = n.label.toLowerCase()
    if (label === s) return 0
    if (label.startsWith(s)) return 1
    if (label.includes(s)) return 2
    if ((n.title ?? '').toLowerCase().includes(s)) return 3
    if (n.id.toLowerCase().includes(s)) return 4
    return 9
  }
  return nodes.map((n, i) => ({ i, r: rank(n), d: n.degree ?? 0 })).filter(x => x.r < 9)
    .sort((a, b) => a.r - b.r || b.d - a.d).slice(0, max).map(x => x.i)
}

// ---------------------------------------------------------------- the picture of the day (Lagebild): data first, then a verdict

/**
 * The picture of the day as data, from what the page already holds: what to start with, who waits for you, what runs,
 * which starts answered or went quiet, the next date, the tightest quota, the findings, and what can wait.
 */
export function situation(model, tabs, nowMs) {
  const rows = id => (model?.sections ?? []).find(x => x.id === id)?.rows ?? []
  const live = (tabs ?? []).filter(t => !t.is_control && t.state !== 'shell')
  const returns = model?.returns ?? []
  let quota = null
  for (const p of model?.pages ?? []) {
    for (const sec of p.sections ?? []) {
      for (const it of sec.items ?? []) {
        const m = it.meter
        if (m?.unit !== '%' || !m.max) continue
        const pace = meterPace(m)
        const share = m.value / m.max
        const label = String(it.title ?? '').replace(/:\s*[\d.,]+\s*%\s*$/, '')
        const q = { label, value: m.value, max: m.max, perDay: pace?.perDay ?? null, over: !!pace?.over,
          bad: m.bad != null && m.value >= m.bad, warn: m.warn != null && m.value >= m.warn, it, page: p.id, section: sec.id }
        if (!quota || (q.over || q.bad) > (quota.over || quota.bad) || ((q.over || q.bad) === (quota.over || quota.bad) && share > quota.value / quota.max)) quota = q
      }
    }
  }
  return {
    first: focusPick(tabs, model),
    now: rows('now'),
    give: rows('give'),
    work: rows('work'),
    later: rows('later'),
    asking: live.filter(t => t.state === 'needs-you'),
    waiting: live.filter(t => t.state === 'waiting' && wantsYou(t)),
    idle: live.filter(t => t.state === 'waiting' && t.idle),
    working: live.filter(t => t.state === 'working'),
    answers: returns.filter(r => r.stage === 'result'),
    lost: returns.filter(r => r.stage === 'lost'),
    next: nextEvent(model, nowMs),
    alarms: model?.alarms ?? [],
    quota,
  }
}

/** The picture as plain lines for Claude: only what is there, each list cut short, so the verdict rests on the page's data */
export function situationText(sit, nowMs, lang = 'de') {
  const names = (list, f, n = 4) => list.slice(0, n).map(f).join('; ') + (list.length > n ? tableOf(lang).situation.more(list.length - n) : '')
  const title = r => String(r.title ?? r.name ?? r.key ?? '').replace(/\s+/g, ' ').slice(0, 90)
  const row = r => `${r.priority ? `${r.priority} ` : ''}${title(r)}`
  const L = tableOf(lang).situation
  const out = []
  if (sit.now.length) out.push(`${L.now}: ${names(sit.now, row)}`)
  if (sit.asking.length) out.push(`${L.asking}: ${names(sit.asking, title)}`)
  if (sit.give.length) out.push(`${L.give}: ${names(sit.give, row)}`)
  if (sit.work.length) out.push(`${L.work}: ${names(sit.work, row, 5)}`)
  if (sit.working.length) out.push(`${L.working}: ${names(sit.working, title)}`)
  if (sit.answers.length) out.push(`${L.answers}: ${names(sit.answers, title)}`)
  if (sit.lost.length) out.push(`${L.lost}: ${names(sit.lost, title)}`)
  if (sit.next) out.push(`${L.next}: ${title(sit.next.it)} ${L.inT} ${untilText(sit.next.ms - nowMs)}`)
  if (sit.quota) out.push(`${L.quota}: ${sit.quota.label} ${Math.round(sit.quota.value)} %${sit.quota.perDay != null ? `, ${Math.round(sit.quota.perDay)} % ${L.per}` : ''}${sit.quota.over ? `, ${L.over}` : ''}`)
  if (sit.alarms.length) out.push(`${L.alarms}: ${names(sit.alarms, a => `${a.section_title} (${a.count})`)}`)
  if (sit.later.length) out.push(`${L.later}: ${sit.later.length}`)
  return out.join('\n')
}

/** The most the server takes as the situation of a free question (actions.py CONTEXT_MAX): longer is refused there */
export const CONTEXT_MAX = 6000

/** What a free question in the chat carries along (actions.py ask `context`): the page's picture of the day
 *  plus what works in this Bridge's tabs right now, so "how many agents run" has an answer. '' when it
 *  would not fit: the question goes without it rather than being refused */
export function askContext(s, lang = 'de') {
  const picture = situationText(situation(s?.model, s?.tabs?.tabs, s?.now), s?.now, lang)
  const { total } = agentLoad(s?.sessions?.sessions, s?.tabs?.tabs)
  const out = [picture, tableOf(lang).situation.load(total.busy, total.subagents, total.workflows)].filter(Boolean).join('\n')
  return out.length <= CONTEXT_MAX ? out : ''
}

// ---------------------------------------------------------------- the chat's one input: where Enter goes

/** Where a text typed into the chat goes: `quick` (a read-only answer here) or `tab` (an agent tab that may
 *  act), and why: a leading ? or ! (`prefix`, stripped), the first words (`words`: a trailing ? or a
 *  question word asks, an order word starts a tab, in English and German), or `default` (unclear asks).
 *  The word lists are language data in text.js (route) */
export function routeOf(raw) {
  const text = String(raw ?? '').trim()
  if (text.startsWith('?')) return { to: 'quick', by: 'prefix', text: text.slice(1).trim() }
  if (text.startsWith('!')) return { to: 'tab', by: 'prefix', text: text.slice(1).trim() }
  const lists = key => Object.values(TABLES).flatMap(t => t.route?.[key] ?? []).map(w => w.toLowerCase())
  const filler = new Set(lists('fillerWords'))
  let words = text.toLowerCase().replace(/[.,:;!?]+/g, ' ').split(/\s+/).filter(Boolean)
  while (words.length > 1 && filler.has(words[0])) words = words.slice(1)
  // a list entry of two words matches the first two, or its first word alone (German puts the particle last:
  // "leg eine Aufgabe an")
  const hit = list => list.some(w => w === words[0] || w === words.slice(0, 2).join(' ') || (w.includes(' ') && w.split(' ')[0] === words[0]))
  if (text.endsWith('?') || hit(lists('questionWords'))) return { to: 'quick', by: 'words', text }
  if (hit(lists('orderWords'))) return { to: 'tab', by: 'words', text }
  return { to: 'quick', by: 'default', text }
}

const HANDOFF_FAILED = new Set(['failed', 'partly', 'aborted', 'error', 'rejected'])

/** The status line of a chat that was handed on (quick.py `handed`, or the page's own record of a chat_tab
 *  reply): `word` is a key of text.js handoff, `tone` a state token, `action` what a button beside it does
 *  (retry, jump to the tab, ask_via_tab). The control route reads its relay record; the tab route finds the
 *  tab that carries the inbox item. null without a record */
export function handoffStatus(handed, relayRecords, tabs) {
  if (!handed?.status) return null
  const out = (word, tone, action = null, extra = {}) => ({ word, tone, action, ...extra })
  if (handed.status === 'starting') return out('starting', 'info')
  if (handed.to === 'control') {
    const rec = (relayRecords ?? []).find(r => r?.id && r.id === handed.relay_id)
    const status = rec?.status ?? handed.status
    if (status === 'queued') return out('waiting', 'info')
    if (status === 'submitted') return out('arrived', 'success')
    if (status === 'answered') return out('answered', 'success')
    if (status === 'sent_to_tab') return out('sentToTab', 'success')
    if (status === 'expired') return out('expired', 'warning', 'retry')
    if (status === 'stuck') return out('stuck', 'warning')
    if (status === 'offline') {
      const waiting = (tabs ?? []).some(t => t?.is_control && t.state === 'waiting')
      return out('offline', 'warning', waiting && handed.relay_id ? 'ask_via_tab' : 'retry')
    }
    return out('failed', 'danger', 'retry')
  }
  const tab = handed.inbox_id ? (tabs ?? []).find(t => t?.item === handed.inbox_id) : null
  if (tab && ['started', 'running', 'busy'].includes(handed.status)) return out('inTab', 'success', 'jump', { ref: tab.ref, tab: tab.name })
  if (handed.status === 'started') return out('started', 'info')
  if (handed.status === 'running' || handed.status === 'busy') return out('running', 'info')
  if (handed.status === 'manual') return out('manual', 'warning')
  if (handed.status === 'nothing') return out('nothing', 'warning', 'retry')
  if (HANDOFF_FAILED.has(handed.status)) return out('failed', 'danger', 'retry')
  return out('failed', 'danger', 'retry')
}

const VERDICT_KEYS = { first: ['zuerst', 'first'], then: ['dann', 'then'], later: ['kann warten', 'can wait'] }

/** Claude's verdict in its three fixed lines (first, then, can wait), or null when the answer has another shape */
export function parseVerdict(text) {
  const out = {}
  for (const line of String(text ?? '').split('\n')) {
    const clean = line.replace(/^[\s*#>-]+/, '').replace(/\*\*/g, '').trim()
    for (const [k, words] of Object.entries(VERDICT_KEYS)) {
      const w = words.find(x => clean.toLowerCase().startsWith(`${x}:`))
      if (w && !out[k]) out[k] = clean.slice(w.length + 1).trim()
    }
  }
  return out.first && out.then && out.later ? out : null
}

const LIVE_RANK = { asks: 0, alarm: 1, answer: 2, working: 3, lost: 4, warn: 5 }

/**
 * What is alive in the net right now, by node: a task whose agent tab works or waits, a start handed to a tab that
 * answered or went quiet, a worker whose declared run has a finding. One state per node, the most pressing.
 */
export function graphLive(g, tabs, returns, runs) {
  const out = new Map()
  const put = (i, v) => {
    if (i === undefined) return
    const was = out.get(i)
    if (!was || LIVE_RANK[v.tone] < LIVE_RANK[was.tone]) out.set(i, v)
  }
  const task = slug => slug ? g.index.get(`work/tasks/${slug}/STATUS.md`) ?? g.index.get(`work/streams/${slug}/STATUS.md`) : undefined
  for (const t of tabs ?? []) {
    if (t.is_control || !t.slug) continue
    if (wantsYou(t)) put(task(t.slug), { tone: 'asks', text: t.name, ref: t.ref })
    else if (t.state === 'waiting' && t.idle) put(task(t.slug), { tone: 'answer', text: t.name, ref: t.ref })   // finished: to check
    else if (t.state === 'working') put(task(t.slug), { tone: 'working', text: t.name, ref: t.ref })
  }
  for (const r of returns ?? []) {
    if (r.stage === 'result') put(task(r.item), { tone: 'answer', text: r.title, key: r.key })
    else if (r.stage === 'lost') put(task(r.item), { tone: 'lost', text: r.title, key: r.key })
  }
  for (const run of runs ?? []) {
    if (run.retired) continue
    const i = g.index.get(`workflow/workloads/${run.id}.yaml`)
    if (run.severity === 'high') put(i, { tone: 'alarm', text: run.title ?? run.id })
    else if (run.severity === 'medium') put(i, { tone: 'warn', text: run.title ?? run.id })
  }
  return out
}

/** The lane of a task row on a work page: review (waits for your yes), runs (waits on someone or something,
 *  task.py wait or a blocked_by), next (backlog), now (being worked on). In the order a page shows them */
export const TASK_LANES = ['now', 'runs', 'review', 'next']
export function taskLane(it) {
  if (it?.state === 'review') return 'review'
  if ((it?.lines ?? []).some(l => l.kind === 'blocked' || l.kind === 'look')) return 'runs'
  if (it?.state === 'backlog') return 'next'
  return 'now'
}

/** The theme a page address forces for this one load: `?theme=light` or `?theme=dark`, else null.
 *  The static demo on the website uses it; the choice is never saved. theme.js repeats this rule,
 *  because a classic script in <head> cannot import a module. */
export function themeOverride(search) {
  if (typeof search !== 'string') return null
  const mode = new URLSearchParams(search).get('theme')
  return mode === 'light' || mode === 'dark' ? mode : null
}

// ---------------------------------------------------------------- the model an agent tab starts with (launch)

/** The verbs that start an agent: only these carry a model and an effort, and only while launch is on */
export const START_VERBS = ['do_it', 'advise', 'start_agent', 'collect_context', 'team_role', 'session_resume', 'chat_tab', 'quick_handoff']
export const LAUNCH_MODELS = ['haiku', 'sonnet', 'opus']
export const LAUNCH_EFFORTS = ['low', 'medium', 'high', 'xhigh']

/** What the start picker offers under the server's switches (state.launch), or null while launch is off or
 *  the server does not know it yet. Auto comes first where it is on; without manual choice it stands alone,
 *  read only. 'standard' is no effort flag at all: the CLI's own default */
export function launchOptions(launch) {
  if (!launch?.enabled) return null
  const models = launch.models?.length ? launch.models : LAUNCH_MODELS
  const efforts = launch.efforts?.length ? launch.efforts : LAUNCH_EFFORTS
  return {
    models: [...(launch.auto ? ['auto'] : []), ...(launch.manual ? models : [])],
    efforts: launch.effort ? [...(launch.auto ? ['auto'] : []), 'standard', ...efforts] : [],
    readOnly: !launch.manual,
  }
}

/** The model and effort chosen now: the stored pick where the switches still offer it, else Auto while Auto
 *  is on, else the configured defaults */
export function launchChoice(launch, ui) {
  const opts = launchOptions(launch) ?? { models: [], efforts: [] }
  const model = !opts.readOnly && opts.models.includes(ui?.launchModel) ? ui.launchModel
    : launch?.auto ? 'auto' : launch?.default_model ?? 'sonnet'
  const effort = opts.efforts.includes(ui?.launchEffort) ? ui.launchEffort
    : launch?.auto ? 'auto' : launch?.default_effort ?? 'standard'
  return { model, effort }
}

/** The args a start sends: the very same object while launch is off or for any other verb, so nothing
 *  changes for a server without it. On, the choice goes along; Auto with a recommendation cached for the
 *  one row started sends its concrete model and effort, so the server need not route again. An effort
 *  goes along only while the effort switch is on, Standard as 'standard' */
export function withLaunch(verb, args, launch, ui, routes) {
  if (!launch?.enabled || !START_VERBS.includes(verb)) return args
  const { model, effort } = launchChoice(launch, ui)
  const keys = args?.keys ?? (args?.key ? [args.key] : [])
  const hit = keys.length === 1 ? routes?.[keys[0]] : null
  const rec = model === 'auto' && hit?.status === 'ok' ? hit.route : null
  const out = { ...args, model: rec ? rec.model : model }
  if (launch.effort) {
    const e = effort === 'auto' && rec ? rec.effort : effort
    if (e) out.effort = e   // 'standard' goes out as such: the server then passes no effort flag
  }
  return out
}

/** The rows whose recommendation is still to fetch: none yet, or one for an older title. A failed one stays
 *  quiet (no retry loop); the server takes at most 20 keys */
export function routesToFetch(items, cache) {
  return (items ?? []).filter(x => x?.key && (!cache?.[x.key] || cache[x.key].title !== x.title)).map(x => x.key).slice(0, 20)
}

/** "Auto: Sonnet · high (Jev, level 1.2)": a recommendation in the page language, null without one */
export function routeText(route, t, lang) {
  if (!route) return null
  const w = t.launch
  const level = route.level == null ? '' : Number(route.level).toLocaleString(lang === 'de' ? 'de-DE' : 'en-US', { maximumFractionDigits: 2 })
  const by = route.routed_by === 'jev' ? (level ? w.byJevLevel(level) : 'Jev') : route.routed_by === 'haiku' ? 'Haiku'
    : route.routed_by === 'check' ? w.byCheck : route.routed_by === 'status' ? 'STATUS' : w.byDefault
  return `Auto: ${w.model[route.model] ?? route.model}${route.effort ? ` · ${w.effort[route.effort] ?? route.effort}` : ''} (${by})`
}

/** One setting as the partial the server saves: 'standard' is no effort (null), a name without its blanks */
export function launchPatch(key, value) {
  if (key === 'default_effort') return { [key]: value === 'standard' ? null : value }
  if (typeof value === 'string') return { [key]: value.trim() }
  return { [key]: value }
}

/** A Jev model name the server accepts: jev-1.14.0 or jev-2.0 */
export function jevModelValid(v) {
  return /^jev-\d+\.\d+(\.\d+)?$/.test(String(v ?? '').trim())
}

/** What is wrong with the Jev bands, or null: every bound 0 to 3 and rising, the last one open ("else") */
export function bandsProblem(bands) {
  const list = bands ?? []
  if (!list.length || list[list.length - 1].below != null) return 'last'
  const bounds = list.slice(0, -1).map(b => b.below)
  if (bounds.some(b => typeof b !== 'number' || !Number.isFinite(b) || b < 0 || b > 3)) return 'range'
  if (bounds.some((b, i) => i > 0 && b <= bounds[i - 1])) return 'order'
  return null
}

/** The model the daily check implies for a row the AI may do, as the server reckons it (model_route.py
 *  from_check): Jev's score through the bands where triage_jev is on and Jev gave one, else Haiku's level
 *  through the Haiku levels, then at most max_model. Null for a row you do, without a number, or while
 *  launch or its Auto is off. The effort only where the effort switch is on */
export function checkPick(tri, launch) {
  if (!tri || !launch?.enabled || !launch.auto || (tri.doer !== 'ai' && tri.doer !== 'either')) return null
  const st = launch.settings ?? {}
  const jev = tri.jev
  let pick = null
  if (st.triage_jev && typeof jev === 'number' && Number.isFinite(jev) && jev >= 0 && jev <= 3) {
    pick = (st.jev_bands ?? []).find(b => b.below == null || jev < b.below) ?? null
  } else if (Number.isInteger(tri.level) && tri.level >= 0 && tri.level <= 3) {
    pick = (st.haiku_map ?? [])[tri.level] ?? null
  }
  if (!pick) return null
  const top = LAUNCH_MODELS.indexOf(st.max_model ?? 'opus')
  const model = top >= 0 && LAUNCH_MODELS.indexOf(pick.model) > top ? LAUNCH_MODELS[top] : pick.model
  return { model, effort: launch.effort ? pick.effort ?? null : null }
}

/** "Sonnet · high": a check's pick in the page language */
export function checkPickText(pick, t) {
  if (!pick) return null
  return `${t.launch.model[pick.model] ?? pick.model}${pick.effort ? ` · ${t.launch.effort[pick.effort] ?? pick.effort}` : ''}`
}

// ---------------------------------------------------------------- the news ticker (views/ticker.js)

/** The kinds of status the ticker can mix in, in the order the settings offer them */
export const TICKER_KINDS = ['running', 'waiting', 'slow', 'failing', 'quota', 'offline', 'notes']
// how long a loud note counts as news in the band
const TICKER_NOTE_MS = 15 * 60000
const TICKER_TONE_RANK = { bad: 0, warn: 1, info: 2, ok: 3 }
// the result items of the resource and token probes that say a machine, a cloud or a model source is down
const TICKER_DOWN = /^(machine:|cloud:|workers:error)|^llm:.*:error$/

/** What runs, what waits, what is slow or failing, read from the start page's own store. Each item names
 *  its kind (cat), tone, text key with its values, and where a click leads (null: nowhere). Only the
 *  kinds in `kinds` come out */
export function tickerStatus(s, now, kinds = TICKER_KINDS) {
  const out = []
  const add = (id, cat, tone, key, vars = [], target = null) => out.push({ id: `st:${id}`, cat, tone, key, vars, target })
  const model = s?.model ?? {}
  const tk = s?.ticker ?? {}
  // 1 findings on a page
  for (const a of model.alarms ?? []) add(`alarm:${a.page_id}:${a.section_title}`, 'failing', 'bad', 'alarm', [a.count, `${a.section_title} (${a.page_title})`], { kind: 'page', id: a.page_id })
  // 2 the quotas, against their marks and their pace
  for (const q of homeCatalog(model).filter(x => x.kind === 'quota')) {
    const m = q.it.meter
    const tone = m.bad != null && m.value >= m.bad ? 'bad' : (m.warn != null && m.value >= m.warn) || meterPace(m)?.over ? 'warn' : null
    if (tone) add(q.id, 'quota', tone, 'quota', [q.label, Math.round(m.value)], { kind: 'info', it: q.it, page: q.page, section: q.section })
  }
  // 3 token use far over the usual
  for (const o of tk.perf?.outliers ?? []) add(`outlier:${o.source}`, 'quota', 'warn', 'outlier', [o.source, o.factor], { kind: 'page', id: '@sessions' })
  // 4 and 5 the briefing pass: failed, or running far longer than it should
  const ld = s?.loading ?? {}
  if (ld.last_error) add('load-failed', 'failing', 'bad', 'loadFailed', [short(ld.last_error.message ?? '', 60)], { kind: 'page', id: 'briefing' })
  if (ld.pass && ld.started_ms && now - ld.started_ms > Math.max(1.5 * (ld.eta_ms || 0), 30000)) {
    add('load-slow', 'slow', 'warn', 'loadSlow', [duration(now - ld.started_ms)])
  }
  // 6 the last pass, against the collect time limit
  const pass = (tk.perf?.passes ?? []).at(-1)
  const limit = tk.limits?.timeout_ms ?? 0
  if (pass && limit && pass.took_ms >= 0.9 * limit) add('pass-slow', 'slow', 'bad', 'passSlow', [Math.round(pass.took_ms / 1000)], { kind: 'page', id: 'briefing' })
  else if (pass && pass.took_ms >= 60000) add('pass-slow', 'slow', 'warn', 'passSlow', [Math.round(pass.took_ms / 1000)], { kind: 'page', id: 'briefing' })
  // 7 a source of the briefing in error: out of time is slow, anything else failing
  for (const x of model.status ?? []) {
    if (skipFixable(x)) add(`source:${x.title}`, 'failing', 'warn', 'sourceCannotRun', [x.title, short(x.reason ?? '', 60)], { kind: 'page', id: 'briefing' })
    if (x.state !== 'error') continue
    if (/took longer|time limit/i.test(x.reason ?? '')) add(`source:${x.title}`, 'slow', 'warn', 'sourceSlow', [x.title], { kind: 'page', id: 'briefing' })
    else add(`source:${x.title}`, 'failing', 'bad', 'sourceFailed', [x.title, short(x.reason ?? '', 60)], { kind: 'page', id: 'briefing' })
  }
  // 8 to 10 the page itself
  if (model.stale) add('stale', 'failing', 'warn', 'stale')
  if (s?.conn === 'down') add('conn', 'offline', 'bad', 'connDown')
  if (s?.tabs?.error) add('tabs-error', 'failing', 'bad', 'tabsError', [], { kind: 'drawer', id: 'tabs' })
  // 11 to 13 the agent tabs; the control tab is not news
  const tabs = (s?.tabs?.tabs ?? []).filter(t => !t.is_control)
  for (const t of tabs) if (t.long) add(`tab-long:${t.ref}`, 'slow', 'warn', 'tabLong', [t.name], { kind: 'tab', ref: t.ref })
  for (const t of tabs) if (t.waiting) add(`tab-waits:${t.ref}`, 'waiting', 'warn', 'tabWaits', [t.name], { kind: 'tab', ref: t.ref })
  const working = tabs.filter(t => t.state === 'working')
  if (working.length > 3) add('tabs-work', 'running', 'info', 'tabsWork', [working.length], { kind: 'drawer', id: 'tabs' })
  else for (const t of working) add(`tab-works:${t.ref}`, 'running', 'info', 'tabWorks', [t.name], { kind: 'tab', ref: t.ref })
  // 14 Claude sessions at work, their subagents and workflows
  const sessions = s?.sessions?.sessions ?? []
  const busy = sessions.filter(x => x.status === 'busy').length
  const agents = sessionCounts(sessions).agents
  if (busy + agents > 0) add('sessions', 'running', 'info', 'sessions', [busy, agents], { kind: 'page', id: '@sessions' })
  // 15 the work handed to the AI, where it stands now
  const stageRule = { started: ['running', 'info', 'returnWorks'], working: ['running', 'info', 'returnWorks'],
    asks: ['waiting', 'warn', 'returnAsks'], result: ['waiting', 'ok', 'returnResult'], lost: ['failing', 'warn', 'returnLost'] }
  for (const r of model.returns ?? []) {
    const rule = stageRule[liveStage(r, s?.tabs?.tabs, now)]
    // an answer opens the answer; a tab only while it is still open, else the row the start came from
    const tabOpen = r.tab?.ref && (s?.tabs?.tabs ?? []).some(t => t.ref === r.tab.ref)
    const target = r.result?.key ? { kind: 'item', key: r.result.key } : tabOpen ? { kind: 'tab', ref: r.tab.ref } : { kind: 'row', key: r.key }
    if (rule) add(`return:${r.key}`, rule[0], rule[1], rule[2], [r.title], target)
  }
  // 16 what waits on you
  if ((model.counts?.now ?? 0) > 0) add('waits', 'waiting', 'warn', 'waitsForYou', [model.counts.now], { kind: 'page', id: 'briefing' })
  // 17 the task check
  const rv = model.review ?? {}
  if (rv.running) add('review', 'running', 'info', 'reviewRuns', [], { kind: 'review' })
  else if (rv.error) add('review', 'failing', 'bad', 'reviewFailed', [], { kind: 'review' })
  if (!rv.running && (rv.last?.to_close ?? 0) > 0) add('to-close', 'waiting', 'info', 'toClose', [rv.last.to_close], { kind: 'review' })
  // 18 the daily check
  if (s?.triage?.running) add('triage', 'running', 'info', 'triageRuns', [], { kind: 'page', id: 'briefing' })
  else if (s?.triage?.error) add('triage', 'failing', 'bad', 'triageFailed', [], { kind: 'page', id: 'briefing' })
  // 19 and 20 the agents of other Bridges
  for (const p of s?.agents?.peers ?? []) {
    if (['refused', 'failed', 'unreachable'].includes(p.reach)) add(`peer:${p.id}`, 'offline', 'warn', 'peerDown', [p.name ?? p.id], { kind: 'page', id: '@agents' })
  }
  for (const c of s?.agents?.convs ?? []) {
    const last = c.turns?.at(-1)
    const since = last?.at_ms ?? c.last_ms ?? c.started_ms ?? now
    if (c.running && now - since > 150000) add(`conv:${c.id}`, 'slow', 'warn', 'convSlow', [c.peer], { kind: 'conv', id: c.id })
    else if (!c.running && last?.waiting) add(`conv:${c.id}`, 'waiting', 'warn', 'convWaits', [c.peer], { kind: 'conv', id: c.id })
  }
  // 21 the background jobs
  for (const run of s?.workers?.data?.runs ?? []) {
    if (run.retired) continue
    const lastRun = (run.strip ?? []).at(-1)
    const tone = workerTone(run) === 'bad' || ['failed', 'expired'].includes(lastRun?.verdict) ? 'bad' : workerTone(run) === 'warn' ? 'warn' : null
    if (tone) add(`job:${run.id}`, 'failing', tone, tone === 'bad' ? 'jobFailed' : 'jobWarn', [run.title ?? run.id], { kind: 'workers' })
  }
  // 22 machines, clouds and model sources that are down, from the pages of the profile
  for (const p of model.pages ?? []) {
    for (const sec of p.sections ?? []) {
      for (const it of sec.items ?? []) {
        if (it.tone === 'bad' && typeof it.id === 'string' && TICKER_DOWN.test(it.id)) {
          add(`down:${it.id}`, 'offline', 'bad', 'offline', [it.title], { kind: 'info', it, page: p.id, section: sec.id })
        }
      }
    }
  }
  // 23 and 24 Jev and the control session
  if (s?.jev?.enabled && !s.jev.ready) add('jev', 'failing', 'warn', 'jevNotReady', [], { kind: 'page', id: '@jev' })
  if (s?.relay?.enabled && !s.relay.online) add('relay', 'offline', 'warn', 'controlOffline', [], { kind: 'claude' })
  // 25 the last loud notes of the last quarter hour; a server note replayed on load carries ms 0 and stays out
  const loud = (s?.notes ?? []).filter(x => (x.tone === 'bad' || x.tone === 'warn') && x.ms && now - x.ms < TICKER_NOTE_MS)
  for (const n of loud.slice(-3)) {
    add(`note:${n.at ?? ''}:${n.text}`, 'notes', n.tone, 'note', [n.text], noteGo(n.go))
  }
  const want = new Set(kinds ?? TICKER_KINDS)
  return out.filter(x => want.has(x.cat))
}

/** Where a page target of the band leads: every page the controller routes itself (the tab row, a page
 *  of group work or day, Jev wherever it lives, the agents wherever a peer is: as cmux they are the Chat's
 *  A2A area, app.js setPage); Today only for a name that exists nowhere */
export function tickerPage(s, id, order = []) {
  const known = order.includes(id) || id === '@jev' || (id === '@agents' && (s?.agents?.peers ?? []).length > 0)
    || (s?.model?.pages ?? []).some(p => p.id === id)
  return known ? id : 'briefing'
}

/** Whether a ticker state may replace the one in the store: never an older one by rev, so an answer that
 *  arrives after the event that ended its thread cannot bring back a spinning Refresh or a busy Editor */
export function newerTicker(cur, next) {
  if (!next) return false
  if (typeof cur?.rev === 'number' && typeof next.rev === 'number') return next.rev >= cur.rev
  return true
}

/** The words of a status item in a text table */
export function tickerText(it, t) {
  const v = t.ticker.status[it.key]
  // a token source reads as the usage page names it (Subagents, not subagent)
  const vars = it.key === 'outlier' ? [t.usageSource?.[it.vars?.[0]] ?? it.vars?.[0], ...(it.vars ?? []).slice(1)] : it.vars ?? []
  return typeof v === 'function' ? v(...vars) : String(v ?? it.key)
}

/** The status items, loudest first (bad, warn, info, ok, then rule order). Nothing while the ticker is
 *  off, its status is switched off or no kind is chosen */
export function tickerStatusItems(s, now) {
  const tk = s?.ticker
  if (!tk?.enabled) return []
  const st = tk.settings?.status ?? {}
  if (st.enabled === false) return []
  return tickerStatus(s, now, st.kinds ?? TICKER_KINDS)
    .map((x, i) => ({ ...x, kind: 'status', i }))
    .sort((a, b) => (TICKER_TONE_RANK[a.tone] ?? 4) - (TICKER_TONE_RANK[b.tone] ?? 4) || a.i - b.i)
}

/** The feed items in the server's order, only those with a title and a safe address. Nothing while off */
export function tickerFeedItems(s) {
  const tk = s?.ticker
  if (!tk?.enabled) return []
  return (tk.items ?? []).filter(x => x && x.title && tickerUrlValid(x.url)).map(x => ({ ...x, kind: 'feed' }))
}

/** Everything the ticker knows: the status items, then the feed items, each id once */
export function tickerItems(s, now) {
  const seen = new Set()
  return [...tickerStatusItems(s, now), ...tickerFeedItems(s)].filter(x => (seen.has(x.id) ? false : seen.add(x.id)))
}

/** The tokens a feed's source label takes: secondary, accent and on-surface, no state tone (DESIGN.md: state
 *  colours only where the data IS a state). After design.py's fallback chain each resolves to a value of its
 *  own in both modes, also from a DESIGN.md that names only a few keys (border-strong would fall back to
 *  secondary there). Secondary and accent may sit close in one mode, so style.css tints each chip to a
 *  strength of its own as well. The colour groups; the source name in the chip is what tells a feed apart */
export const TICKER_SOURCE_TOKENS = ['secondary', 'accent', 'on-surface']

/** FNV-1a with a final mix, since the low bits of a plain string hash put most ids on the same token */
function sourceHash(id) {
  let h = 2166136261
  for (const ch of String(id ?? '')) { h ^= ch.codePointAt(0); h = Math.imul(h, 16777619) }
  h ^= h >>> 16
  h = Math.imul(h, 0x85ebca6b)
  h ^= h >>> 13
  return h >>> 0
}

/** The token of a feed's source label, the same for the same feed on every load. Given the configured
 *  feed ids in order, the feeds take the tokens in turn: each starts at its hash and walks on past a token
 *  an earlier feed of the same round took, so every round of three feeds shows three colours. An id
 *  outside the order keeps its plain hash */
export function tickerSourceToken(id, order) {
  const n = TICKER_SOURCE_TOKENS.length
  const list = (order ?? []).map(String)
  const at = list.indexOf(String(id ?? ''))
  if (at < 0) return TICKER_SOURCE_TOKENS[sourceHash(id) % n]
  let used = new Set()
  let slot = 0
  for (let i = 0; i <= at; i++) {
    if (used.size === n) used = new Set()
    slot = sourceHash(list[i]) % n
    while (used.has(slot)) slot = (slot + 1) % n
    used.add(slot)
  }
  return TICKER_SOURCE_TOKENS[slot]
}

/** Seconds for one pass of the band: its width at the chosen speed in px/s, 20 s to 600 s */
export function tickerDuration(widthPx, speed) {
  const pxs = { slow: 40, normal: 70, fast: 110 }[speed] ?? 70
  return Math.round(Math.max(20, Math.min(600, (Number(widthPx) || 0) / pxs)))
}

/** Where the band stands, in ms of its new pass, when its duration changes (new items, another speed):
 *  the same share of the pass as before, so it neither jumps nor starts over. Unknown: from the start */
export function tickerResume(currentMs, oldSec, newSec) {
  if (!Number.isFinite(currentMs) || !(oldSec > 0) || !(newSec > 0)) return 0
  const share = (currentMs % (oldSec * 1000)) / (oldSec * 1000)
  return Math.round(share * newSec * 1000)
}

/** One ticker setting as the partial the server saves. A key inside status or editor sends that whole block
 *  with the one value changed; text without its blanks; the feed list as a whole */
export function tickerPatch(key, value, current = {}) {
  const clean = v => (typeof v === 'string' ? v.trim() : v)
  if (key === 'feeds') {
    return { feeds: (value ?? []).map(f => ({ id: clean(f.id), name: clean(f.name), url: clean(f.url), enabled: f.enabled !== false })) }
  }
  const [block, sub] = key.split('.')
  if (sub) return { [block]: { ...(current?.[block] ?? {}), [sub]: clean(value) } }
  return { [key]: clean(value) }
}

// eslint-disable-next-line no-control-regex
const TICKER_CTRL = /[\u0000-\u001f\u007f]/

/** The muted terms from the settings field: split at commas and line ends, blanks squeezed, each 1 to 40
 *  characters, once each ignoring case, at most 30 (the server's rules) */
export function tickerMuteTerms(text) {
  const out = []
  const seen = new Set()
  for (const raw of String(text ?? '').split(/[,\n]/)) {
    const term = raw.replace(/\s+/g, ' ').trim()
    if (!term || term.length > 40 || TICKER_CTRL.test(term) || seen.has(term.toLowerCase())) continue
    seen.add(term.toLowerCase())
    out.push(term)
    if (out.length >= 30) break
  }
  return out
}

/** Whether a news item came out after the viewer's last visit (since, ms): never on a first visit, never
 *  for an item without a date */
export function tickerIsNew(it, since) {
  return Number.isFinite(since) && since > 0 && Number.isFinite(it?.published_ms) && it.published_ms > since
}

/** The ids of the news the viewer opened, the newest last, at most cap */
export function tickerRemember(list, id, cap = 300) {
  if (!id) return list ?? []
  return [...(list ?? []).filter(x => x !== id), id].slice(-cap)
}

/** An http or https URL without a user name, blanks or control characters, at most 500 long */
function tickerUrlValid(url) {
  if (typeof url !== 'string' || !url || url.length > 500 || /\s/.test(url) || TICKER_CTRL.test(url)) return false
  let u
  try { u = new URL(url) } catch { return false }
  return (u.protocol === 'http:' || u.protocol === 'https:') && !!u.hostname && !u.username && !u.password
}

/** A feed the server would take: an id like openai or tech-review, a name of 1 to 60 characters, a good URL */
export function tickerFeedValid(feed) {
  if (!feed || typeof feed !== 'object') return false
  const name = typeof feed.name === 'string' ? feed.name.trim() : ''
  return /^[a-z0-9][a-z0-9-]{0,39}$/.test(String(feed.id ?? '').trim()) && name.length >= 1 && name.length <= 60
    && !TICKER_CTRL.test(feed.name) && tickerUrlValid(String(feed.url ?? '').trim())
}

// ---------------------------------------------------------------- toast timers

/** How long a toast stays: a `bad` one until it is dismissed (null), every other its own linger */
export function toastLinger(tone, linger) {
  return tone === 'bad' ? null : linger
}

/**
 * The timers of the toasts. `start(id, ms)` lets a toast go after ms (null: never), `pause(id, why)`
 * holds it while the pointer (`hover`) or the focus (`focus`) is inside it, `resume(id, why)` lets
 * it run on with the time it had left once every reason has gone, `stop(id)` forgets it.
 */
export function createToastTimers({ setTimer = setTimeout, clearTimer = clearTimeout, now = Date.now, expire }) {
  const all = new Map()   // id -> { left, until, timer, held: Set }
  const run = (id, t) => {
    t.until = now() + t.left
    t.timer = setTimer(() => { all.delete(id); expire(id) }, t.left)
  }
  return {
    start(id, ms) {
      const old = all.get(id)
      if (old?.timer != null) clearTimer(old.timer)
      all.delete(id)
      if (ms == null) return
      const t = { left: ms, until: 0, timer: null, held: old?.held ?? new Set() }
      all.set(id, t)
      if (!t.held.size) run(id, t)
    },
    pause(id, why) {
      const t = all.get(id)
      if (!t) return
      if (!t.held.size && t.timer != null) {
        clearTimer(t.timer)
        t.timer = null
        t.left = Math.max(0, t.until - now())
      }
      t.held.add(why)
    },
    resume(id, why) {
      const t = all.get(id)
      if (!t || !t.held.delete(why) || t.held.size) return
      run(id, t)
    },
    stop(id) {
      const t = all.get(id)
      if (t?.timer != null) clearTimer(t.timer)
      all.delete(id)
    },
  }
}

// ---------------------------------------------------------------- the answer while it is written

const LIVE_KEEP = 20000   // the most of a live text the page keeps, as the server sends it (quick.py LIVE_KEEP)

/** The live texts after one `quick_live` event: a piece is appended where it says it goes (`at`), once;
 *  a whole text (`full`, a new message) takes the old one's place; text and doing null end the turn. An
 *  event the page already has (its `seq` is not newer) or one that does not continue the text changes
 *  nothing, so the same map comes back */
export function applyQuickLive(map, p) {
  if (!p?.conv) return map
  if (p.text == null && p.doing == null) {
    if (!(p.conv in map)) return map
    const { [p.conv]: _, ...rest } = map
    return rest
  }
  const cur = map[p.conv]
  const seq = Number(p.seq) || 0
  if (cur && seq <= cur.seq) return map
  const piece = String(p.text ?? '')
  const at = Number(p.at) || 0
  let text
  if (p.full) text = piece
  else if (at === (cur ? cur.end : 0)) text = (cur ? cur.text : '') + piece
  else return map
  return { ...map, [p.conv]: { seq, end: at + piece.length, text: text.slice(-LIVE_KEEP), doing: p.doing ?? null } }
}

/** The live texts of the state a page gets when it connects: each one whole */
export function quickLiveSnapshot(snap) {
  let map = {}
  for (const p of Object.values(snap ?? {})) map = applyQuickLive(map, { ...p, full: true })
  return map
}

/** A render tick that runs only while the tab is in view: a hidden tab has nothing to draw */
export function whenShown(doc, fn) {
  return () => { if (!doc?.hidden) fn() }
}

/** Who measured the cost view: the host of every report it merges (one collector per machine), else its host or
 *  source, so a card fed by two machines names both. */
export function costSources(view) {
  const hosts = (view?.sources ?? []).map(x => x?.host || x?.source).filter(Boolean)
  return [...new Set(hosts)].join(', ') || view?.host || view?.source || ''
}

// ---------------------------------------------------------------- the first-run tour (views/tour.js)

/** The tour's version: a later tour with other steps counts up; tour_done keeps the one that ended */
export const TOUR_VERSION = 1

/** Whether this visit offers the tour by itself: the server knows it (an older one sends no `tour`), the
 *  config leaves it on (cockpit.tour) and it never ended, finished or skipped, in any browser; or it ended
 *  for an older tour than this page's (`version`) */
export function tourOffered(tour, version = TOUR_VERSION) {
  if (!tour || tour.enabled === false) return false
  return !tour.done || !(tour.done.v >= version)
}

/** The running tour's place in this state's steps: the step it stands on is kept by id, so a layout that
 *  drops a step (narrow) does not move it onto another; an id the steps lack falls back to the first */
export function tourIndex(s) {
  const i = tourSteps(s).findIndex(x => x.id === s?.ui?.tour?.id)
  return i < 0 ? 0 : i
}

/** The tour's steps in order. A step names its texts (text.js tour.steps.<id>), the page it opens and the
 *  area it lights (a CSS selector); one without a target stands in the middle. The tab column is left out
 *  where the layout shows none (narrow: its own switch at the foot) */
export function tourSteps(s) {
  const narrow = s?.layout === 'narrow'
  return [
    { id: 'welcome' },
    { id: 'pages', target: '.pagebar' },
    { id: 'start', page: '@start', target: '#main' },
    { id: 'work', page: 'briefing', target: '#main' },
    ...(narrow ? [] : [{ id: 'tabs', target: '#tabs-column, .hdr-tabs' }]),
    { id: 'ask', target: '.hdr-ask' },
    { id: 'sessions', page: '@sessions', target: '#main' },
    { id: 'explain', target: '.hdr-explain' },
    { id: 'done' },
  ]
}

/** Where the tour's box stands beside the lit area `rect` ({top, left, width, height}, null: none): below
 *  when it fits, else above, else beside it (a tall column), else inside it at its top (the whole page);
 *  always 16px off the edges */
export function tourPlace(rect, box, view, gap = 12) {
  const margin = 16
  const clampX = x => Math.max(margin, Math.min(x, view.width - box.width - margin))
  const clampY = y => Math.max(margin, Math.min(y, view.height - box.height - margin))
  if (!rect) return { side: 'center', top: (view.height - box.height) / 2, left: (view.width - box.width) / 2 }
  const left = clampX(rect.left + rect.width / 2 - box.width / 2)
  const below = rect.top + rect.height + gap
  if (below + box.height <= view.height - margin) return { side: 'below', top: below, left }
  const above = rect.top - gap - box.height
  if (above >= margin) return { side: 'above', top: above, left }
  // a tall column: beside it, its top in line with the area's
  const top = clampY(rect.top)
  if (rect.left - gap - box.width >= margin) return { side: 'left', top, left: rect.left - gap - box.width }
  if (rect.left + rect.width + gap + box.width <= view.width - margin) return { side: 'right', top, left: rect.left + rect.width + gap }
  return { side: 'inside', top: clampY(rect.top + gap * 2), left: clampX(rect.left + rect.width - box.width - gap * 2) }
}

// ---------------------------------------------------------------- the explain overlay (views/hints.js)

// the areas the overlay can point at, per page, in the order they matter. Each id has its words in text.js
// hints.items.<id>; an area the page does not show is left out when drawn. The page comes first, the header
// on every page in a round of its own after it, so its notes never take the page's room
const HINTS = {
  '@start': [['prompt', '.stage-prompt'], ['signals', '.home-signals'], ['ticker', '.ticker'],
    ['stations', '.station'], ['core', '.core-button'], ['today', '.stage-card'], ['projects', '.home-chips'],
    ['tabCards', '.hcard:not(.hcard-row)'], ['rowCards', '.hcard-row'], ['starts', '.home-starts']],
  briefing: [['alarm', '.col-day .alarm'], ['secHead', '.col-day .sec-head'], ['rowMain', '.col-day .row-main'],
    ['rowActs', '.col-day .row-acts'], ['secTools', '.col-day .sec-tools'], ['hiddenRows', '.col-day .hidden-rows'],
    ['detail', '.col-detail'], ['tabcol', '#tabs-column'], ['tabWait', '#tabs-column .tabcard.st-needs-you'], ['snap', '#tabs-column .snap']],
  '@chat': [['chatModel', '.chatpage > .page-head .seg'], ['chatList', '.chat-list'], ['chatBox', '.tabview-send'],
    ['launch', '.launch-pick'], ['tabcol', '#tabs-column']],
  '@sessions': [['stats', '.stats'], ['guideBoard', '.guide-board'], ['guideRoot', '.guide-root'],
    ['guideBranches', '.guide-branches'], ['guideFoot', '.guide-foot'], ['sessCards', '.sess-grid'],
    ['sessAgents', '.sess-agent-list'], ['sessFoot', '.sess-foot']],
  '@workers': [['workerStats', '.stats'], ['wfilters', '.wfilters'], ['wgroup', '.wgroup .rgroup-head'], ['wrow', '.wrow-name'],
    ['wwhen', '.wrow-when'], ['wstrip', '.wrow-strip'], ['wstate', '.wrow-state']],
  '@agents': [['agentList', '.agents-list'], ['agentConvs', '.agent-convs'], ['agentProfile', '.agent-bar'],
    ['agentSkills', '.agent-skill-cards'], ['agentModes', '.agent-modes'], ['agentSend', '.chat-main .tabview-send']],
  '@check': [['reviewRun', '.col-page > .page-head .btn-primary'], ['reviewFlow', '.flow'], ['reviewFilter', '.review-bar'],
    ['reviewSort', '.review-top .seg'], ['reviewTable', '.tbl-review']],
  '@jev': [['jevRun', '.jev-actions'], ['jevStage', '.jev-stage'], ['jevPlan', '.jev-side']],
  '@settings': [['settingsNav', '.settings-nav'], ['settingsBody', '.settings-body'], ['setCard', '.set-card-head']],
  // Work through, a view of the work tab (its parts are explained there, hintsFor)
  '@flow': [['flowSide', '.flow-side'], ['flowOverview', '.flow-overview'], ['flowCard', '.flow-card'], ['flowVerbs', '.flow-card .verbbar'],
    ['flowDetails', '.flow-details'], ['flowWalk', '.flow-walk']],
}
// a page of the briefing profile is built from the same parts everywhere: each part it has is explained
const PAGE_HINTS = [['pageBadge', '.col-page > .page-head .pbadge'], ['oboard', '.oboard'], ['kinds', '.tri-kinds'],
  ['triage', '.tri-sort'], ['reviewStrip', '.review-strip'], ['jorder', '.jorder'], ['sectionHead', '.psec .psec-head'],
  ['table', '.psec .table-wrap'], ['quiet', '.psec-quiet'], ['ghFigures', '.ghb-figures'], ['ghBoards', '.ghb-boards'],
  ['ghPeople', '.ghb-people'], ['ghList', '.ghl-tools'], ['gauges', '.gtiles'], ['costBars', '.ubars'], ['costList', '.clist'],
  ['calFigures', '.calf'], ['calBar', '.calbar'], ['calDays', '.cal-day']]
// the as-of time is the reload button, the notes stand in the history, the look-up card under Settings, Appearance
const HEADER_HINTS = [['pages', '.pagebar'], ['asof', '.hdr-asof'], ['tabsButton', '.hdr-tabs'],
  ['ask', '.hdr-ask'], ['history', '.hdr-history'], ['relay', '.hdr-relay'], ['explain', '.hdr-explain']]

/** What the overlay explains on the page now: its own areas (group page), then the header (group head).
 *  The work tab showing a page instead of the day's columns (by area, by Jev) explains that page's parts */
export function hintsFor(s) {
  const page = s?.ui?.page
  const view = page === 'briefing' ? workViewIn(s) : null
  const dayColumns = page !== 'briefing' || view === 'due'
  const own = view === 'flow' ? [['workSwitch', '.work-switch'], ...HINTS['@flow']] : !dayColumns ? [['workSwitch', '.work-switch'], ...PAGE_HINTS, ['tabcol', '#tabs-column']]
    : HINTS[page] ?? [...PAGE_HINTS, ['tabcol', '#tabs-column']]
  return [...own.map(([id, target]) => ({ id, target, group: 'page' })),
    ...HEADER_HINTS.map(([id, target]) => ({ id, target, group: 'head' }))]
}

const HINT_MARGIN = 12    // the notes keep this far off the screen's edges
const HINT_GAP = 40       // and this far from their area, room for the arrow
const HINT_RING = 6       // the ring stands this far outside the area

const overlaps = (a, b, pad = 0) => a.left < b.left + b.width + pad && b.left < a.left + a.width + pad
  && a.top < b.top + b.height + pad && b.top < a.top + a.height + pad
const clampTo = (v, lo, hi) => Math.max(lo, Math.min(v, hi))

/** A small area (a button, a chip, a figure) is circled, a long or large one framed */
const ringShape = r => (r.width <= 320 && r.height <= 110 && r.width / r.height < 6 ? 'ellipse' : 'frame')

/** Where each hint's note, ring and arrow stand. `items` in order of importance, each {id, rect, note:
 *  {width, height}}; the rects as the screen shows them. A note goes below, above, right or left of its
 *  area, inside a large one; never over another note, never over a small area still to be explained, never
 *  off the screen. A hint without room, or whose area is off the screen, is dropped. A small area gets an
 *  ellipse, a long or large one a frame; the arrow runs from the note's edge to the ring's */
export function hintLayout(items, view) {
  const visible = items.filter(it => it.rect && it.rect.width > 0 && it.rect.height > 0
    && it.rect.top < view.height && it.rect.top + it.rect.height > 0 && it.rect.left < view.width && it.rect.left + it.rect.width > 0)
  const dropped = items.filter(it => !visible.includes(it)).map(it => it.id)
  const rings = new Map(visible.map(it => {
    const r = it.rect
    return [it.id, { top: r.top - HINT_RING, left: r.left - HINT_RING, width: r.width + HINT_RING * 2, height: r.height + HINT_RING * 2 }]
  }))
  const big = r => r.width * r.height > view.width * view.height * 0.12
  const placed = []
  for (const it of visible) {
    const ring = rings.get(it.id)
    const { width, height } = it.note
    const fit = (top, left) => ({ top: clampTo(top, HINT_MARGIN, view.height - height - HINT_MARGIN),
      left: clampTo(left, HINT_MARGIN, view.width - width - HINT_MARGIN), width, height })
    const cx = ring.left + ring.width / 2
    const cy = ring.top + ring.height / 2
    // a large area takes its note inside, near its top; beside it, the note would stand in the next column
    const within = big(ring) ? [fit(ring.top + HINT_GAP, ring.left + HINT_GAP), fit(ring.top + HINT_GAP, ring.left + ring.width - width - HINT_GAP),
      fit(cy - height / 2, ring.left + HINT_GAP)] : []
    // then fanned out below it, beside the place right under it and in the rows further down, so the
    // notes of areas that stand close together (the header's buttons) find room side by side
    // the nearest first, so the arrows stay short and cross as little as they can
    const step = width + 10
    const near = n => Math.hypot(n.left + n.width / 2 - cx, n.top + n.height / 2 - cy)
    const fan = [0, 1, 2, 3, 4].flatMap(k => [-2, -1, 0, 1, 2].filter(dx => k || dx)
      .map(dx => fit(ring.top + ring.height + HINT_GAP + k * (height + 10), cx - width / 2 + dx * step))).sort((a, b) => near(a) - near(b))
    const tries = [...within,
      fit(ring.top + ring.height + HINT_GAP, cx - width / 2),
      fit(ring.top - HINT_GAP - height, cx - width / 2),
      fit(cy - height / 2, ring.left + ring.width + HINT_GAP),
      fit(cy - height / 2, ring.left - HINT_GAP - width), ...fan]
    // the small areas the note must not cover, already drawn or still to come: first every one, then, where
    // that leaves no room (a header button above the tab bar), only those an ellipse circles
    const others = visible.filter(x => x !== it && !big(rings.get(x.id))).map(x => rings.get(x.id))
    const circled = others.filter(r => ringShape(r) === 'ellipse')
    // a note pushed back onto the screen may land on its own area: only the inside places may stand there
    const free = (n, clear) => (within.includes(n) || !overlaps(n, ring)) && placed.every(p => !overlaps(n, p.note, 8))
      && clear.every(r => !overlaps(n, r))
    const note = tries.find(n => free(n, others)) ?? tries.find(n => free(n, circled))
    if (!note) { dropped.push(it.id); continue }
    const inside = overlaps(note, ring)
    // the note's point nearest the area's middle, and the ring's point nearest that
    const x1 = clampTo(cx, note.left, note.left + note.width)
    const y1 = clampTo(cy, note.top, note.top + note.height)
    const arrow = inside ? null : (() => {
      let x2 = clampTo(x1, ring.left, ring.left + ring.width)
      let y2 = clampTo(y1, ring.top, ring.top + ring.height)
      // a point that fell inside the ring is pushed onto its nearest edge
      if (x2 > ring.left && x2 < ring.left + ring.width && y2 > ring.top && y2 < ring.top + ring.height) {
        const d = [y2 - ring.top, ring.top + ring.height - y2, x2 - ring.left, ring.left + ring.width - x2]
        const k = d.indexOf(Math.min(...d))
        if (k === 0) y2 = ring.top; else if (k === 1) y2 = ring.top + ring.height; else if (k === 2) x2 = ring.left; else x2 = ring.left + ring.width
      }
      return { x1, y1, x2, y2 }
    })()
    placed.push({ id: it.id, n: placed.length + 1, ring, shape: ringShape(ring), note, arrow })
  }
  return { placed, dropped }
}

/** The hints in rounds, so every note has room: the page's areas first, then the header's, each group in as
 *  many rounds as its notes need. `items` as for hintLayout plus their group. An area the page does not show
 *  (no rect) is not counted; one further down than the screen reaches is `away`, so the bar can say that
 *  scrolling brings more. Each round numbers its notes from 1 */
export function hintRounds(items, view) {
  const rounds = []
  const away = []
  for (const group of ['page', 'head']) {
    // the page in the order its areas matter, the header from left to right as it reads
    const mine = items.filter(it => (it.group ?? 'page') === group && it.rect && it.rect.width > 0 && it.rect.height > 0)
    if (group === 'head') mine.sort((a, b) => a.rect.left - b.rect.left)
    let rest = mine.filter(it => it.rect.top < view.height && it.rect.top + it.rect.height > 0
      && it.rect.left < view.width && it.rect.left + it.rect.width > 0)
    // further down is what scrolling brings; above or beside the view, or without room even alone, is left out
    away.push(...mine.filter(it => !rest.includes(it) && it.rect.top >= view.height).map(it => it.id))
    while (rest.length) {
      const { placed } = hintLayout(rest, view)
      if (!placed.length) break
      rounds.push({ group, placed })
      const done = new Set(placed.map(p => p.id))
      rest = rest.filter(it => !done.has(it.id))
    }
  }
  return { rounds, away }
}

/** Open the event stream; its first `state` event is the page's first state (the server sends one on every
 *  connect), so the page asks /api/state only when the stream fails before that first state came, once.
 *  The state used to be fetched and then sent again by the stream: twice the largest payload on every load */
export function openStream(api, handlers, onConn, { apply, fail }) {
  let first = false
  let fellBack = false
  const state = p => { first = true; handlers.state(p) }
  return api.events({ ...handlers, state }, conn => {
    onConn(conn)
    if (conn !== 'down' || first || fellBack) return
    fellBack = true
    api.state().then(st => (st.ok ? apply(st.data) : fail(st)))
  })
}

/** A view_pages event put into the model the page has: the pages it carries by id, every other page as it was,
 *  in the server's order. null when it cannot be applied (no model yet, an older seq, a page the page does not
 *  know): then the whole state is asked for */
export function mergePages(model, ev) {
  if (!model || !ev || !Array.isArray(ev.order) || (model.seq ?? 0) >= (ev.seq ?? 0)) return null
  const fresh = new Map((ev.pages ?? []).map(p => [p.id, p]))
  const had = new Map((model.pages ?? []).map(p => [p.id, p]))
  const pages = ev.order.map(id => fresh.get(id) ?? had.get(id))
  return pages.every(Boolean) ? { ...model, seq: ev.seq, pages } : null
}
