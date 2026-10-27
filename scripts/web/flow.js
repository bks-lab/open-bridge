// SPDX-License-Identifier: MIT
// Pure helpers of the cockpit's Work through page (views/flow.js): the one queue in its fixed groups, what it
// leaves out and why, the cards of the calm card, the return card after a jump to a tab, the five verbs (which a
// row offers, which one is suggested, what each sends), the briefs to prepare for the cards that come next and how
// many agents run. No DOM, no network, no state of its own (prepRunner holds the line app.js keeps). logic.js
// passes every name on, so a view may import it from either; the flow test imports it under node.
//
// The queue reads the rows of /api/state as they are: no store of its own. Its groups stand in an order fixed here,
// and nothing (no Jev rank, no triage) moves a card across a group: a tab that asks always stands before a task.
import { TABLES } from './text.js'
import { asksYou, canTab, DAY, homeProjects, isAnswered, isoDate, liveStage, nextMonday, projectTone, rowProject, tabOfTask } from './logic.js'

// the page's id; areas.js names it as a literal beside it (its own imports would reach this file too late)
export const FLOW_PAGE = '@flow'

// the groups of the queue, in the order the page walks them: the return card after a jump, a tab that asks, what an
// agent finished, a start that got lost, a question for you (these five need you), what is in progress (a start that
// runs, a session typed by hand, every doing task), the tasks in review, the reports as one card
export const FLOW_GROUPS = ['back', 'asks', 'result', 'lost', 'question', 'doing', 'task', 'reports']

// the groups that need you: the left column counts them in the warning tone
export const FLOW_YOU = ['back', 'asks', 'result', 'lost', 'question']

// the bands the left column and the overview of a theme group the points in, in the queue's order: what needs you,
// what is in progress, the tasks in review, the reports (pointBand)
export const FLOW_BANDS = ['you', 'doing', 'task', 'reports']

/** The band of a point: a group that needs you is `you`, any other its own group */
export const pointBand = x => (FLOW_YOU.includes(x?.group) ? 'you' : x?.group)

// the groups a filter of the queue shows; `all` shows every group (the page shows all, by theme or area)
export const FLOW_CHIPS = { all: FLOW_GROUPS, you: FLOW_YOU, running: ['doing'], tasks: ['task'], reports: ['reports'] }

// why an open row stands outside the queue, in the order the drawer names them
export const FLOW_LEFT_OUT = ['later', 'waiting', 'resting', 'stream', 'idea']

// the five verbs, in the order the verb bar shows them
export const FLOW_VERBS = ['do', 'advise', 'done', 'later', 'drop']

// a jump to a tab older than this asks nothing any more when the page comes back into view
export const FLOW_RETURN_MAX_MS = 4 * 3600000

// the group a start of the return channel stands in by where it stands now: started and working run in the lane, a
// done one is settled. `idle` (a quiet tab with no question, returns.py) counts as finished; a stage the page does
// not know falls to the tabs that ask, since its tab no longer works
const STAGE_GROUP = { started: 'doing', working: 'doing', asks: 'asks', idle: 'result', result: 'result', lost: 'lost', done: null }

const SECTIONS = ['now', 'give', 'work', 'track', 'later']
const TASK_STATES = ['doing', 'review']
// a triage older than this many days suggests nothing in the list: the themes run speaks instead (flowSuggestion)
const TRIAGE_FRESH_DAYS = 2
const PRIO_RANK = { P0: 0, P1: 1, P2: 2, P3: 3 }

/** Whether the page and its tab exist: cockpit.flow.enabled, off on an older server */
export const flowOn = s => s?.work?.flow?.enabled === true

/** The page's settings as the server sends them (cockpit.flow), with the defaults of config.py for what is missing */
export function flowSettings(s) {
  const f = s?.work?.flow ?? {}
  const int = (k, d, low) => (Number.isInteger(f[k]) && f[k] >= low ? f[k] : d)
  return { enabled: f.enabled === true, drop_reasons: Array.isArray(f.drop_reasons) ? f.drop_reasons : [],
    return_after_s: Number.isFinite(f.return_after_s) ? f.return_after_s : 20, prep_ahead: int('prep_ahead', 2, 0),
    max_running: int('max_running', 4, 1) }
}

/** Whether a terminal driver starts tabs here: without one nothing runs from the page, so the lane, the cards of
 *  the agents and every way to a tab stay out (a driver not read yet counts as there, as everywhere) */
export const flowDriver = s => canTab(s, 'launch')

/** Where a start stands now: the server's stage read against the tabs as they are (liveStage), a quiet one (idle)
 *  kept until its tab asks you */
export const flowStage = (r, tabs, nowMs) => liveStage(r, tabs, nowMs)

/** A jump to a tab after the page came back into view: armed once return_after_s went by since the jump, gone
 *  after FLOW_RETURN_MAX_MS, waiting before. Without a jump nothing: being shown alone never asks */
export function flowArm(jump, nowMs, afterS) {
  if (!jump) return null
  const gone = nowMs - jump.at
  if (gone > FLOW_RETURN_MAX_MS) return null
  if (jump.armed || gone < Math.max(0, afterS) * 1000) return jump
  return { ...jump, armed: true }
}

// how a row's age reads: an inbox id starts with its day and time, so the oldest sorts first; anything else by the
// day it names, else last
const ageOf = r => String(r.inbox_id ?? r.created ?? r.next?.since ?? '~')

/** The Jev rank of a row: the triage's next_rank (Jev's fresh rank, triage.py, within cockpit.flow.rank_max_age_days),
 *  else the order of a Jev view of a work page this page fetched (s.jevOrder) */
function rankMap(s) {
  const out = new Map()
  for (const [key, it] of Object.entries(s?.triage?.items ?? {})) if (Number.isFinite(it?.next_rank)) out.set(key, it.next_rank)
  for (const v of Object.values(s?.jevOrder ?? {})) for (const it of v?.order?.items ?? []) if (!out.has(it.key)) out.set(it.key, it.rank)
  return out
}

const rankOf = (r, ranks) => ranks.get(r.key) ?? null
const byRank = ranks => (a, b) => {
  const x = rankOf(a, ranks)
  const y = rankOf(b, ranks)
  if (x != null || y != null) return x == null ? 1 : y == null ? -1 : x - y
  return 0
}
const byPrio = (a, b) => (PRIO_RANK[a.priority] ?? 4) - (PRIO_RANK[b.priority] ?? 4)
const byAge = (a, b) => ageOf(a).localeCompare(ageOf(b))
// a due day first, the soonest first; then the oldest
const byDue = (a, b) => (a.due && b.due ? a.due.localeCompare(b.due) : a.due ? -1 : b.due ? 1 : 0) || byAge(a, b)

/** The parts of the page from the state it sees (areaScope): the cards of each group, the starts that run (the
 *  lane), what the queue leaves out and why. Every row stands once: a start, a tab that asks or a question about a
 *  task takes that task out of the tasks, a running start keeps its row out until it asks, finishes or is lost, and
 *  so does a tab of a session linked to a task while it works (one typed by hand). A tab answered from the page
 *  (ui.answered) asks no more until it asks anew. A card is {group, id, kind, row?, start?, tab?, task?, rows?,
 *  stage?}, kind back, start, tab, row or reports; an entry of the lane {id, kind start or session, title, at, ...} */
export function flowParts(s) {
  const nowMs = s?.now || Date.now()
  const model = s?.model ?? {}
  const driver = flowDriver(s)
  // every tab tells where a start stands (a quiet one is back at its shell), a shell asks nothing
  const allTabs = (s?.tabs?.tabs ?? []).filter(t => !t.is_control)
  const tabs = allTabs.filter(t => t.state !== 'shell')
  const answered = s?.ui?.answered ?? {}
  const asking = t => !isAnswered(answered[t.ref], t)
  const byKey = new Map()
  for (const id of SECTIONS) for (const r of (model.sections ?? []).find(x => x.id === id)?.rows ?? []) if (!byKey.has(r.key)) byKey.set(r.key, r)
  const rowOfTask = slug => byKey.get(`task:${slug}`) ?? null
  const used = new Set()      // row keys a card already stands for
  const usedTasks = new Set() // task slugs a card already stands for
  const usedTabs = new Set()
  const take = row => {
    if (!row) return
    used.add(row.key)
    if (row.task && !row.inbox_id) usedTasks.add(row.task)
  }
  const out = { back: null, asks: [], result: [], lost: [], question: [], doing: [], task: [], reports: [], lane: [] }
  const tabOf = ref => allTabs.find(t => t.ref === ref) ?? null
  if (driver) {
    // 1 the return card, only once the jump is armed (flowArm); its row and its tab stand nowhere else
    const jump = s?.ui?.flowJump
    if (jump?.armed) {
      const row = byKey.get(jump.key) ?? null
      out.back = { group: 'back', id: 'back', kind: 'back', jump, row, tab: tabOf(jump.ref) }
      take(row)
      usedTabs.add(jump.ref)
    }
    // 2 to 4 and the lane: the starts of the return channel by where they stand now
    for (const r of model.returns ?? []) {
      const mine = allTabs.filter(t => t.ref === r.tab?.ref || (r.item && (t.slug === r.item || t.item === r.item)))
      let stage = flowStage(r, allTabs, nowMs)
      // answered from here: it works again, as far as the page knows, until the next read of its tab
      if (stage === 'asks' && mine.length && !mine.some(asking)) stage = 'working'
      const group = Object.hasOwn(STAGE_GROUP, stage) ? STAGE_GROUP[stage] : 'asks'
      const row = byKey.get(r.key) ?? null
      if (!group || used.has(r.key)) continue
      const card = { group, id: `start:${r.key}`, kind: 'start', start: r, row, stage, tab: tabOf(r.tab?.ref) ?? mine[0] ?? null,
        title: r.title, at: r.at_ms }
      take(row ?? { key: r.key, task: String(r.key).startsWith('task:') ? r.key.slice(5) : null })
      for (const t of mine) usedTabs.add(t.ref)
      out[group].push(card)
    }
    // the lane, too: a tab of a session linked to an open task (typed by hand, session_links) while it works
    for (const x of s?.sessions?.sessions ?? []) {
      const tab = x.task && x.tab?.ref && !usedTabs.has(x.tab.ref) ? tabOf(x.tab.ref) : null
      if (!tab || tab.state !== 'working') continue
      const row = rowOfTask(x.task)
      out.doing.push({ group: 'doing', id: `session:${tab.ref}`, kind: 'session', session: x, row, tab, stage: 'working',
        title: row?.title ?? tab.name, at: x.started_ms ?? tab.since_ms ?? nowMs })
      take(row ?? { key: `task:${x.task}`, task: x.task })
      usedTabs.add(tab.ref)
    }
    // 2 the tabs that ask you, with or without a task, the oldest question first
    for (const t of tabs.filter(x => x.state === 'needs-you' && !usedTabs.has(x.ref) && asking(x)).sort((a, b) => (a.since_ms ?? 0) - (b.since_ms ?? 0))) {
      const row = (t.slug ? rowOfTask(t.slug) : null) ?? (t.item ? byKey.get(`inbox:${t.item}`) ?? null : null)
      if (row && used.has(row.key)) continue
      out.asks.push({ group: 'asks', id: `tab:${t.ref}`, kind: 'tab', tab: t, row })
      take(row)
      usedTabs.add(t.ref)
    }
    out.asks.sort((a, b) => (a.tab?.since_ms ?? a.start?.at_ms ?? 0) - (b.tab?.since_ms ?? b.start?.at_ms ?? 0))
    out.result.sort((a, b) => (a.start.at_ms ?? 0) - (b.start.at_ms ?? 0))
    out.lost.sort((a, b) => (b.start.at_ms ?? 0) - (a.start.at_ms ?? 0))
  }
  const left = Object.fromEntries(FLOW_LEFT_OUT.map(k => [k, []]))
  const leave = (why, row, until = null) => { if (!used.has(row.key)) { left[why].push({ row, until }); used.add(row.key) } }
  // what is put off (hidden until a day, an inbox item deferred) waits for its day
  for (const r of model.hidden ?? []) leave('later', r, r.hidden_until ?? null)
  const rows = [...byKey.values()]
  for (const r of rows.filter(x => x.inbox_state === 'deferred')) leave('later', r, r.until ?? null)
  const ranks = rankMap(s)
  // 5 the questions for you, with or without a task: a question about a task takes the task out of the tasks
  for (const r of rows.filter(x => x.inbox_id && asksYou(x) && !used.has(x.key) && x.inbox_state !== 'approved').sort(byDue)) {
    if (r.bucket === 'waiting') { leave('waiting', r); continue }
    if (r.bucket === 'resting') { leave('resting', r); continue }
    const task = r.task ? rowOfTask(r.task) : null
    out.question.push({ group: 'question', id: r.key, kind: 'row', row: r, task })
    used.add(r.key)
    if (r.task) usedTasks.add(r.task)
  }
  // 7 the reports, one card; ideas wait on the calm card
  const reports = rows.filter(x => x.inbox_id && x.art === 'report' && !used.has(x.key) && x.inbox_state !== 'approved').sort(byAge)
  for (const r of rows.filter(x => x.inbox_id && x.art === 'idea')) leave('idea', r)
  // 6 the tasks doing (in progress, with what drives them) or in review, every priority: by rank, else priority, then age
  const tasks = []
  for (const r of rows.filter(x => x.task && !x.inbox_id && !used.has(x.key))) {
    if (usedTasks.has(r.task)) continue
    if (r.stream || r.work_kind === 'stream') leave('stream', r)
    else if (r.status === 'backlog') leave('idea', r)
    else if (!TASK_STATES.includes(r.status)) { if (r.bucket === 'resting' || r.blocked_by) leave('resting', r) }
    else if (r.bucket === 'waiting') leave('waiting', r)
    else if (r.bucket === 'resting' || r.bucket === 'drop' || r.blocked_by) leave('resting', r)
    else tasks.push(r)
  }
  const order = (a, b) => byRank(ranks)(a, b) || byPrio(a, b) || byAge(a, b)
  out.task = tasks.filter(r => r.status !== 'doing').sort(order).map(r => ({ group: 'task', id: r.key, kind: 'row', row: r }))
  // what runs first (the starts and the session tabs, the newest first), then the doing tasks in their order
  out.lane = out.doing.slice()
  out.doing = [...out.doing.sort((a, b) => (b.at ?? 0) - (a.at ?? 0)),
    ...tasks.filter(r => r.status === 'doing').sort(order).map(r => ({ group: 'doing', id: r.key, kind: 'row', row: r }))]
  for (const r of reports) used.add(r.key)
  out.reports = reports.length ? [{ group: 'reports', id: 'reports', kind: 'reports', rows: reports }] : []
  // the lane: what runs (a start at work, a session tab at work), the newest first: what max_running counts
  out.lane = out.lane.sort((a, b) => (b.at ?? 0) - (a.at ?? 0))
  const groups = FLOW_LEFT_OUT.filter(k => left[k].length).map(reason => ({ reason, rows: left[reason] }))
  out.leftOut = { total: groups.reduce((n, g) => n + g.rows.length, 0), groups }
  return out
}

/** How many agents run now: the entries of the lane (starts at work, linked session tabs at work). Let AI do it asks
 *  first once cockpit.flow.max_running of them run */
export const flowRunning = s => flowParts(s).lane.length

/** What drives a point in progress now: a start of the cockpit (`start`, its stage and since when), the agent tab of
 *  its task (`tab`, the tab's state), a session typed by hand in a linked tab (`session`), else nothing (`none`, with
 *  how many days ago its task last moved, from its updated day). {by, tab, since_ms, days, stage} */
export function flowDrive(x, s) {
  const nowMs = s?.now || Date.now()
  const tabs = (s?.tabs?.tabs ?? []).filter(t => !t.is_control)
  if (x.kind === 'start') return { by: 'start', tab: x.tab ?? null, since_ms: x.start.at_ms ?? null, days: null, stage: x.stage }
  if (x.kind === 'session') return { by: 'session', tab: x.tab, since_ms: x.at ?? null, days: null, stage: 'working' }
  const slug = x.row?.task
  const tab = slug ? tabOfTask(tabs, slug) : null
  if (tab && tab.state !== 'shell') return { by: 'tab', tab, since_ms: tab.since_ms ?? null, days: null, stage: tab.state }
  const linked = slug ? (s?.sessions?.sessions ?? []).find(v => v.task === slug && v.tab?.ref) : null
  const ltab = linked ? tabs.find(t => t.ref === linked.tab.ref) ?? null : null
  if (ltab) return { by: 'session', tab: ltab, since_ms: linked.started_ms ?? ltab.since_ms ?? null, days: null, stage: ltab.state }
  const day = /^\d{4}-\d{2}-\d{2}/.test(String(x.row?.updated ?? '')) ? new Date(`${String(x.row.updated).slice(0, 10)}T00:00:00`).getTime() : null
  const today = new Date(isoDate(nowMs) + 'T00:00:00').getTime()
  return { by: 'none', tab: null, since_ms: null, days: day == null ? null : Math.max(0, Math.round((today - day) / DAY)), stage: null }
}

// ---------------------------------------------------------------- themes and areas: the left column

const NO_SIDE = 'none'

/** The area of a point: its row's project, else the workspace of its tab; '' without one */
export const pointArea = x => (x?.row ? rowProject(x.row) : x?.kind === 'reports' ? rowProject(x.rows?.[0]) : x?.tab?.workspace) || ''

/** The row keys a point stands for: the reports card for each of its rows, any other card for its row; a tab alone
 *  has none */
export const pointKeys = x => (x?.kind === 'reports' ? x.rows.map(r => r.key) : x?.row?.key ? [x.row.key] : [])

/** How the left column groups: by the themes the server keeps (cockpit.flow.themes on), unless the person picked the
 *  areas (ui.flowMode); by the areas while the themes are off or the server is older */
export function flowMode(s) {
  if (s?.themes?.enabled !== true) return 'areas'
  return s?.ui?.flowMode === 'areas' ? 'areas' : 'themes'
}

const areaId = name => `a:${String(name).trim().toLowerCase()}`

/** The side a row stands on: its theme (t:<id>) or its area (a:<name>), else none */
function rowSide(row, s, mode, tab = null) {
  if (mode === 'themes') {
    const id = row ? s?.themes?.assign?.[row.key] : null
    return id && (s.themes.themes ?? []).some(t => t.id === id) ? `t:${id}` : NO_SIDE
  }
  const name = row ? rowProject(row) : tab?.workspace
  return name ? areaId(name) : NO_SIDE
}

/** The points of one side (`all` every one): a reports card splits, each side holds its own reports as one card */
export function pointsIn(points, side, s, mode) {
  if (!side || side === 'all') return points ?? []
  const out = []
  for (const x of points ?? []) {
    if (x.kind === 'reports') {
      const rows = x.rows.filter(r => rowSide(r, s, mode) === side)
      if (rows.length) out.push({ ...x, rows })
    } else if (rowSide(x.row, s, mode, x.tab) === side) out.push(x)
  }
  return out
}

/** The count of a side: its open points (reports by their rows) and how many of them need you */
function countOf(points) {
  const open = points.reduce((n, x) => n + (x.kind === 'reports' ? x.rows.length : 1), 0)
  return { open, you: points.filter(x => FLOW_YOU.includes(x.group)).length }
}

/** The entries of the left column: All on top, then each theme or area that holds a point, No theme yet or No area
 *  last when points stand outside them. A theme by its name (the server's order), an area by the order the start page
 *  gives the areas (the most frequent first), its colour the terminal workspace's of that name where one has one.
 *  Each {id, name, tone, color, open, you} */
export function flowSides(s, points, mode = flowMode(s)) {
  const sides = []
  if (mode === 'themes') {
    for (const t of s?.themes?.themes ?? []) {
      const mine = pointsIn(points, `t:${t.id}`, s, mode)
      if (mine.length) sides.push({ id: `t:${t.id}`, theme: t, name: t.name, tone: projectTone(t.name), color: null, ...countOf(mine) })
    }
  } else {
    const rows = (points ?? []).flatMap(x => (x.kind === 'reports' ? x.rows : x.row ? [x.row] : []))
    const tabs = (points ?? []).filter(x => !x.row && x.tab).map(x => x.tab)
    const spaces = s?.tabs?.workspaces ?? []
    for (const name of homeProjects(tabs, rows)) {
      const mine = pointsIn(points, areaId(name), s, mode)
      if (!mine.length) continue
      const ws = spaces.find(w => String(w.title ?? '').trim().toLowerCase() === name.trim().toLowerCase() && w.color)
      sides.push({ id: areaId(name), name, tone: projectTone(name), color: ws?.color ?? null, ...countOf(mine) })
    }
  }
  const rest = pointsIn(points, NO_SIDE, s, mode)
  return [{ id: 'all', name: null, tone: null, color: null, ...countOf(points ?? []) }, ...sides,
    ...(rest.length ? [{ id: NO_SIDE, name: null, tone: 'muted', color: null, ...countOf(rest) }] : [])]
}

/** The keys a themes run should take now: the points without a theme, while themes are on, the day's budget has a
 *  run left and none runs; at most 50 (actions.py keys). Empty otherwise: nothing asks */
export function themesToAsk(points, s) {
  const th = s?.themes
  if (th?.enabled !== true || th.running || !(th.budget_left > 0)) return []
  const known = new Set((th.themes ?? []).map(t => t.id))
  return (points ?? []).flatMap(pointKeys).filter(k => !known.has(th.assign?.[k])).slice(0, 50)
}

/** The one asker of the themes for the points without one (app.js keeps one per page load): `send(keys)` runs the
 *  themes over them and resolves true when it went through. One run at a time (an ask while one runs is left out; the
 *  next render asks again), each key once per page load; a run that failed leaves its keys free, so only a key that
 *  was ordered counts as asked */
export function themesAsker(send) {
  const asked = new Set()
  let running = false
  return async function ask(keys) {
    const fresh = [...new Set(keys ?? [])].filter(k => !asked.has(k))
    if (!fresh.length || running) return
    running = true
    for (const k of fresh) asked.add(k)
    let ok = false
    try { ok = await send(fresh) } catch { ok = false } finally { running = false }
    if (!ok) for (const k of fresh) asked.delete(k)
  }
}

// ---------------------------------------------------------------- the list: suggestions and the batch

const TRIAGE_VERB = { close: 'done', stale: 'drop', waiting: 'later' }

/** Whether the day's triage still speaks: its run at most TRIAGE_FRESH_DAYS ago */
function triageFresh(s) {
  const at = Date.parse(String(s?.triage?.last?.at ?? ''))
  return Number.isFinite(at) && (s?.now || Date.now()) - at <= TRIAGE_FRESH_DAYS * DAY
}

/** Whether an agent works on a row already: a start of the cockpit for it that is not over, or a tab of its task
 *  (its own or a linked session's, flowDrive). Let AI do it there would start a second agent on the same work */
export function atWork(row, s) {
  if (!row?.key) return false
  const tabs = (s?.tabs?.tabs ?? []).filter(t => !t.is_control)
  const nowMs = s?.now || Date.now()
  if ((s?.model?.returns ?? []).some(r => r.key === row.key && !['done', 'lost'].includes(flowStage(r, tabs, nowMs)))) return true
  return flowDrive({ kind: 'row', row }, s).by !== 'none'
}

/** The suggestion for a row in the list, with half a sentence of why and where it comes from: the triage of the day
 *  first (verdict close, stale or waiting, else doer ai or either), while it is fresh; else what the themes run said
 *  for it. Only a verb the row offers (verbsFor), or `you` (only the person can); never Let AI do it where an agent
 *  works on it already (atWork). {verb, reason, until, drop, from, at} or null */
export function flowSuggestion(row, s) {
  if (!row?.key) return null
  const offered = verbsFor(row)
  const ok = v => v === 'you' || (offered.includes(v) && !(v === 'do' && atWork(row, s)))
  const tr = s?.triage?.items?.[row.key]
  if (tr && triageFresh(s)) {
    const verb = TRIAGE_VERB[tr.verdict] ?? (['ai', 'either'].includes(tr.doer) ? 'do' : tr.doer === 'you' ? 'you' : null)
    if (verb && ok(verb)) {
      return { verb, reason: tr.reason || tr.gist || '', until: verb === 'later' ? isoDate(nextMonday(s?.now || Date.now())) : null,
        drop: null, from: 'triage', at: s.triage.last.at }
    }
  }
  const th = s?.themes?.suggest?.[row.key]
  if (th && ok(th.verb)) return { verb: th.verb, reason: th.reason ?? '', until: th.until ?? null, drop: th.drop ?? null, from: 'themes', at: th.at_ms ?? null }
  return null
}

/** The rows Take the suggestions ticks: those whose suggestion is done, drop or later; never Let AI do it, never one
 *  that needs you */
export function batchPreselect(rows, s) {
  return (rows ?? []).filter(r => ['done', 'drop', 'later'].includes(flowSuggestion(r, s)?.verb)).map(r => r.key)
}

/** What a batch sends, before it is confirmed: `how` 'suggested' (each row its own suggestion), or one verb for all
 *  ('done', 'later' with the day as `value`, 'drop' with one reason as `value`). Done for several goes out as one
 *  settle; a task dropped is shelved, anything else settled as not doing with the reason; Let AI do it starts a row
 *  only with its own sentence and only while fewer than max_running run, else it stays out. {calls, skipped, counts}:
 *  calls in the order done, later, drop, do; skipped [{row, why}], why not_offered, no_suggestion, you, working (an
 *  agent is on it already, atWork) or running */
export function batchPlan(rows, how, s, value = '', lang = 'en') {
  const done = []
  const later = []
  const drop = []
  const starts = []
  const skipped = []
  let running = flowRunning(s)
  const cap = flowSettings(s).max_running
  for (const row of rows ?? []) {
    const sug = how === 'suggested' ? flowSuggestion(row, s) : null
    const verb = how === 'suggested' ? sug?.verb : how
    if (!verb) { skipped.push({ row, why: 'no_suggestion' }); continue }
    if (verb === 'you') { skipped.push({ row, why: 'you' }); continue }
    if (!verbsFor(row).includes(verb)) { skipped.push({ row, why: 'not_offered' }); continue }
    if (verb === 'done') done.push(row)
    else if (verb === 'later') {
      const day = how === 'suggested' ? sug.until : value
      const a = flowAction('later', row, day)
      if (a) later.push(a)
      else skipped.push({ row, why: 'not_offered' })
    } else if (verb === 'drop') {
      const why = how === 'suggested' ? (sug.drop ? dropReasonWord(sug.drop, lang) : sug.reason) : value
      const a = flowAction('drop', row, why)
      if (a) drop.push(a)
      else skipped.push({ row, why: 'not_offered' })
    } else if (verb === 'do') {
      if (atWork(row, s)) { skipped.push({ row, why: 'working' }); continue }
      if (running >= cap) { skipped.push({ row, why: 'running' }); continue }
      running += 1
      starts.push(flowAction('do', row, startNote(row, lang)))
    } else skipped.push({ row, why: 'not_offered' })
  }
  // the drops that settle (not a shelve) go out together where they share a reason
  const settles = new Map()
  const shelves = []
  for (const a of drop) {
    if (a.verb !== 'settle') { shelves.push(a); continue }
    const k = a.args.text
    if (settles.has(k)) settles.get(k).args.keys.push(...a.args.keys)
    else settles.set(k, { verb: 'settle', args: { keys: [...a.args.keys], outcome: 'not_doing', text: k } })
  }
  const calls = [...(done.length ? [{ verb: 'settle', args: { keys: done.map(r => r.key), outcome: 'done' } }] : []),
    ...later, ...shelves, ...settles.values(), ...starts]
  return { calls, skipped, counts: { done: done.length, later: later.length, drop: drop.length, do: starts.length },
    how, value, days: [...new Set(later.map(a => a.args.until))], reasons: [...new Set(drop.map(a => a.args.reason ?? a.args.text))] }
}

/** The one line a batch shows before it runs: what goes how, with the reason and the day (text-flow.js batch) */
export const batchSummary = (plan, lang = 'en') => (TABLES[lang] ?? TABLES.en).flow.batch.summary(plan)

// the kinds of row describe writes a brief for (describe.py KINDS): a task or stream, an inbox item
const describable = row => !!row && (!!row.inbox_id || (!!row.task && String(row.key).startsWith('task:')))

/** Whether a row's brief is there and current, or on its way: the live describe view (an event, an answer) before
 *  the row's own. Written and not stale, a proposal waiting, or a run now: nothing to prepare */
function briefReady(s, row) {
  const d = s?.describe?.[row.key] ?? row.describe ?? null
  return !!d && (d.running || !!d.proposal || (!!d.written && !d.stale))
}

/** The keys of the n cards after the one at `at` whose brief is missing or stale (cockpit.flow.prep_ahead): the
 *  page has them written before they stand in front. A card without an item (a tab alone, the reports) has none */
export function prepTargets(queue, at, n, s) {
  return (queue ?? []).slice(Math.max(0, at) + 1, Math.max(0, at) + 1 + Math.max(0, n))
    .map(x => x.row).filter(row => describable(row) && !briefReady(s, row)).map(row => row.key)
}

/** The one runner of the briefs written ahead (app.js keeps one per page load): `send(key)` asks for one brief and
 *  resolves true when it was written. The keys wait in line and go one at a time (describe writes one at a time), so
 *  a card that comes up while a brief is written only adds its keys; a key goes out once. A refusal (the hour's budget
 *  spent, a brief being written already) or a failure ends the round: the keys not sent stay for a later card */
export function prepRunner(send) {
  const sent = new Set()
  let line = []
  let running = false
  return async function ask(keys) {
    line = [...line, ...(keys ?? []).filter(k => !sent.has(k) && !line.includes(k))]
    if (running) return
    running = true
    try {
      while (line.length) {
        const key = line.shift()
        if (sent.has(key)) continue
        sent.add(key)
        let ok = false
        try { ok = await send(key) } catch { ok = false }
        if (!ok) { line = []; break }
      }
    } finally {
      running = false
    }
  }
}

/** The cards in the page's order, under a chip (FLOW_CHIPS): the return card first, the reports last */
export function flowQueue(parts, chip = 'all') {
  const groups = FLOW_CHIPS[chip] ?? FLOW_CHIPS.all
  return FLOW_GROUPS.filter(g => groups.includes(g)).flatMap(g => (g === 'back' ? (parts?.back ? [parts.back] : []) : parts?.[g] ?? []))
}

/** What each chip counts: its cards, the reports by their rows */
export function flowCounts(parts) {
  const n = g => (g === 'reports' ? (parts?.reports?.[0]?.rows.length ?? 0) : g === 'back' ? (parts?.back ? 1 : 0) : parts?.[g]?.length ?? 0)
  return Object.fromEntries(Object.entries(FLOW_CHIPS).map(([k, gs]) => [k, gs.reduce((sum, g) => sum + n(g), 0)]))
}

/** The ideas and backlog tasks the calm card offers to start, at most n: by Jev rank, then priority, then age */
export function restSuggestions(s, n = 3) {
  const parts = flowParts(s)
  const ranks = rankMap(s)
  const ideas = (parts.leftOut.groups.find(g => g.reason === 'idea')?.rows ?? []).map(x => x.row)
  return ideas.sort((a, b) => byRank(ranks)(a, b) || byPrio(a, b) || byAge(a, b)).slice(0, n)
}

// a stream's own row; an inbox item about a stream (work_kind stream too) is the way a stream comes in and is
// decided like any other item
const isStream = row => !row?.inbox_id && !!(row?.stream || row?.work_kind === 'stream')

/** The verbs a row offers, in FLOW_VERBS order: a start but on an item whose yes is given (it runs on its own),
 *  Done where the row can be settled, Drop on anything but a stream (a stream runs on, it never ends this way) */
export function verbsFor(row) {
  const stream = isStream(row)
  return FLOW_VERBS.filter(v => (v === 'do' ? row?.inbox_state !== 'approved'
    : v === 'done' ? !stream && (row?.settle ?? []).includes('done') : v === 'drop' ? !stream : true))
}

/** The verb the primary button carries: the triage's verdict (close, stale, waiting), else Advise on a question and
 *  Let AI do it on a task the AI may do (doer ai or either), else Advise; always one the row offers */
export function suggestedVerb(row, triage = null) {
  const offered = verbsFor(row)
  const byVerdict = { close: 'done', stale: 'drop', waiting: 'later' }[triage?.verdict]
  const pick = byVerdict ?? (row?.inbox_id ? 'advise' : row?.task && ['ai', 'either'].includes(triage?.doer) ? 'do' : 'advise')
  return offered.includes(pick) ? pick : 'advise'
}

/** What a verb sends for a row: {verb, args}, or null when it may not go (a start without a sentence, a drop
 *  without a reason or of a stream). Let AI do it always carries a sentence, so it starts an agent and never
 *  approves an item's own action unseen (actions_work.py do_it); Drop shelves a task (an idea in the inbox, the
 *  task declined) and settles anything else as not doing, the reason with it. Advise is a question (c.flowAdvise) */
export function flowAction(verb, row, value = '') {
  const text = String(value ?? '').replace(/\s+/g, ' ').trim()
  const key = row?.key
  if (!key) return null
  if (verb === 'do') return text ? { verb: 'do_it', args: { keys: [key], note: text } } : null
  if (verb === 'done') return { verb: 'settle', args: { keys: [key], outcome: 'done' } }
  if (verb === 'later') return /^\d{4}-\d{2}-\d{2}$/.test(text) ? { verb: 'later', args: { key, until: text } } : null
  if (verb === 'drop') {
    if (!text || isStream(row)) return null
    return row.task && !row.inbox_id ? { verb: 'shelve', args: { key, reason: text.slice(0, 200) } }
      : { verb: 'settle', args: { keys: [key], outcome: 'not_doing', text } }
  }
  return null
}

/** The start sentence a start opens with: the row's title and the request for a result line (text-flow.js) */
export function startNote(row, lang = 'en') {
  return (TABLES[lang] ?? TABLES.en).flow.start.note(String(row?.title ?? row?.key ?? '').trim())
}

/** The words of a reason to drop: a key of the defaults in the page's language, a reason of the instance as written */
export function dropReasonWord(reason, lang = 'en') {
  return (TABLES[lang] ?? TABLES.en).flow.drop.reason[reason] ?? String(reason)
}
