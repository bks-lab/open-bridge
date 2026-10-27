// SPDX-License-Identifier: MIT
// Pure helpers of the cockpit's Work through page (views/flow.js): the one queue in its fixed groups, what it
// leaves out and why, the cards of the calm card, the return card after a jump to a tab, the five verbs (which a
// row offers, which one is suggested, what each sends), the briefs to prepare for the cards that come next and how
// many agents run; since round 3 also the tabs under the card of an open point (Description, Steps, Activity, Related),
// the rows and counts of its Activity, the fields on the right, and the scope and the calls of the instruction line.
// No DOM, no network, no state of its own (prepRunner holds the line app.js keeps). logic.js
// passes every name on, so a view may import it from either; the flow test imports it under node.
//
// The queue reads the rows of /api/state as they are: no store of its own. Its groups stand in an order fixed here,
// and nothing (no Jev rank, no triage) moves a card across a group: a tab that asks always stands before a task.
import { TABLES } from './text.js'
import { canTab, DAY, homeProjects, indexRows, isAnswered, isoDate, liveStage, nextMonday, projectTone, replyOptions, replySend, rowProject, tabOfTask, workPageOf } from './logic.js'

// the page's id; areas.js names it as a literal beside it (its own imports would reach this file too late)
export const FLOW_PAGE = '@flow'

// the groups of the queue, in the order the page walks them: the return card after a jump, a tab that asks, what an
// agent finished, a start that got lost, a question for you (these five need you), a task in progress nobody works on
// right now, the tasks in review, the issues and pull requests of Now, the reports as one card. What runs stands in
// Running now (parts.lane and the live sessions, parts.sessions), never in the queue
export const FLOW_GROUPS = ['back', 'asks', 'result', 'lost', 'question', 'doing', 'task', 'issue', 'reports']

// the groups that need you: the left column counts them in the warning tone
export const FLOW_YOU = ['back', 'asks', 'result', 'lost', 'question']

// the bands the left column and the overview of a theme group the points in, in the queue's order: what needs you,
// what is in progress, the tasks in review, the issues and pull requests, the reports (pointBand)
export const FLOW_BANDS = ['you', 'doing', 'task', 'issue', 'reports']

/** The band of a point: a group that needs you is `you`, any other its own group */
export const pointBand = x => (FLOW_YOU.includes(x?.group) ? 'you' : x?.group)

// the groups a filter of the queue shows; `all` shows every group (the page shows all, by theme or area)
export const FLOW_CHIPS = { all: FLOW_GROUPS, you: FLOW_YOU, running: ['doing'], tasks: ['task', 'issue'], reports: ['reports'] }

// the groups of Not now, the open rows that are no point now, in the order the left column lists them: put off or due
// later than the lead time, waiting on others, resting, ideas and the backlog, the streams, the issues and pull
// requests watched, and those of them a GitHub list holds (`github`, the row's on_board: they stand on that page, so
// Not now names them in one line that leads there, views/flowleft.js)
export const FLOW_LEFT_OUT = ['later', 'waiting', 'resting', 'idea', 'stream', 'watch', 'github']

// the verbs each group of Not now offers in its batch bar (a row a verb does not fit stays out, not_offered)
export const LEFT_VERBS = { later: ['back', 'later', 'done', 'drop'], waiting: ['back', 'later', 'done', 'drop'], resting: ['back', 'later', 'done', 'drop'],
  idea: ['do', 'later', 'done', 'drop'], stream: ['later'], watch: ['later', 'done', 'drop'] }

// the five verbs, in the order the verb bar shows them
export const FLOW_VERBS = ['do', 'advise', 'done', 'later', 'drop']

// a jump to a tab older than this asks nothing any more when the page comes back into view
export const FLOW_RETURN_MAX_MS = 4 * 3600000

// the squares of Jev, in the order of the grid: urgent and important, important, urgent, neither
export const FLOW_QUADRANTS = ['now', 'plan', 'hand', 'drop']

// the group a start of the return channel stands in by where it stands now: started and working run (Running now), a
// done one is settled. `idle` (a quiet tab with no question, returns.py) counts as finished; a stage the page does
// not know falls to the tabs that ask, since its tab no longer works
const STAGE_GROUP = { started: 'lane', working: 'lane', asks: 'asks', idle: 'result', result: 'result', lost: 'lost', done: null }

const SECTIONS = ['now', 'give', 'work', 'track', 'later']
const TASK_STATES = ['doing', 'review']
// a triage older than this many days suggests nothing in the list: the themes run speaks instead (flowSuggestion)
const TRIAGE_FRESH_DAYS = 2
const PRIO_RANK = { P0: 0, P1: 1, P2: 2, P3: 3 }
const DAY_RE = /^\d{4}-\d{2}-\d{2}/
// an issue, a pull request or a merge request by its short name: owner/repo#7
const REF_RE = /^([\w.-]+\/[\w.-]+)#\d+$/

/** Whether the page and its tab exist: cockpit.flow.enabled, off on an older server */
export const flowOn = s => s?.work?.flow?.enabled === true

/** The page's settings as the server sends them (cockpit.flow), with the defaults of config.py for what is missing */
export function flowSettings(s) {
  const f = s?.work?.flow ?? {}
  const int = (k, d, low) => (Number.isInteger(f[k]) && f[k] >= low ? f[k] : d)
  const mb = f.attach?.max_mb
  return { enabled: f.enabled === true, drop_reasons: Array.isArray(f.drop_reasons) ? f.drop_reasons : [],
    return_after_s: Number.isFinite(f.return_after_s) ? f.return_after_s : 20, prep_ahead: int('prep_ahead', 2, 0),
    max_running: int('max_running', 4, 1), rank_max_age_days: int('rank_max_age_days', 7, 1),
    // round 4: how many days before its due a point comes up (C)
    ahead_days: int('ahead_days', 2, 0),
    // round 3, each off unless the server says on (an older server sends none of them)
    summary: { enabled: f.summary?.enabled === true }, instruct: { enabled: f.instruct?.enabled === true },
    attach: { enabled: f.attach?.enabled === true, max_mb: Number.isFinite(mb) && mb >= 1 ? mb : 10 } }
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
// an issue's number as a number: owner/repo#2 before #18
const byKey = (a, b) => String(a.key).localeCompare(String(b.key), undefined, { numeric: true })
const byTitle = (a, b) => String(a.title ?? '').localeCompare(String(b.title ?? ''))

// ---------------------------------------------------------------- round 4: every open row once

/** A task or stream of model.files (cockpit.files_scope all) as a row of the page: a backlog task or a stream no
 *  section carries. The server resolves every open task:<slug> (actions.page_entry), so the verbs work on it */
export function fileRow(f) {
  const kind = f?.kind === 'stream' ? 'stream' : 'task'
  const areas = Array.isArray(f?.area_names) ? f.area_names.filter(Boolean) : []
  return { key: `task:${f.slug}`, task: f.slug, title: f.title ?? f.slug, status: f.status ?? null, stream: kind === 'stream', work_kind: kind,
    priority: f.priority ?? null, updated: f.updated ?? null, blocked_by: f.blocked_by ?? null, bucket: f.bucket ?? null, area_names: areas,
    area: areas[0] ?? null, settle: kind === 'task' ? ['done', 'not_doing'] : [], hidden_until: f.deferred_until ?? null, from_files: true }
}

/** The open rows and where each came from first: the sections in their order, the hidden rows not settled here,
 *  every file of model.files, every open task a page names (model.task_rows: a task or a stream whose folder is
 *  open, closable or stream), every item put off past the briefing's window (model.deferred) */
function universeOf(s) {
  const model = s?.model ?? {}
  const rows = new Map()
  const from = new Map()
  const put = (r, src) => { if (r?.key && !rows.has(r.key)) { rows.set(r.key, r); from.set(r.key, src) } }
  for (const id of SECTIONS) for (const r of (model.sections ?? []).find(x => x.id === id)?.rows ?? []) put(r, id)
  for (const r of model.hidden ?? []) if (r && r.settled_as == null) put(r, 'hidden')
  for (const f of Array.isArray(model.files) ? model.files : []) if (f?.slug) put(fileRow(f), 'files')
  for (const r of model.task_rows ?? []) if (r && (r.closable || r.stream)) put(r, 'task_rows')
  for (const r of model.deferred ?? []) put(r, 'deferred')
  return { rows, from }
}

/** The open rows of the page by key, the first source winning: every row of the sections (now, give, work, track,
 *  later), every hidden row not settled here, every file of model.files, every open task of model.task_rows (a
 *  closed one a page still names is not open), every item of model.deferred */
export const flowUniverse = s => universeOf(s).rows

/** The row keys a point stands for: pointKeys, and the task a question card stands for beside its item */
export const coveredKeys = x => [...pointKeys(x), ...(x?.covers && x.task?.key ? [x.task.key] : [])]

/** Where each key stands: Map key -> {at: point, lane or left, id}; throws on a key placed twice */
export function flowKeys(parts) {
  const out = new Map()
  const put = (key, at, id) => {
    if (!key) return
    if (out.has(key)) throw new Error(`flowKeys: ${key} stands twice (${out.get(key).id}, ${id})`)
    out.set(key, { at, id })
  }
  for (const x of flowQueue(parts, 'all')) for (const k of coveredKeys(x)) put(k, 'point', x.id)
  for (const x of parts?.lane ?? []) put(x.row?.key, 'lane', x.id)
  for (const g of parts?.leftOut?.groups ?? []) for (const e of g.rows) put(e.row?.key, 'left', g.reason)
  return out
}

// a calendar day as a count of days, so no clock change bends the count between two days
const dayNumber = iso => Date.UTC(Number(iso.slice(0, 4)), Number(iso.slice(5, 7)) - 1, Number(iso.slice(8, 10))) / DAY
const dayOf = n => new Date(n * DAY).toISOString().slice(0, 10)

/** When a point due later than the lead time comes up: {until, due} while its due day is more than `days` ahead of
 *  `today` and it is not urgent now, else null. A due with a time counts by its day */
export function aheadOf(row, today, days) {
  if (!row?.due || row.urgency === 'now' || !DAY_RE.test(String(row.due)) || !DAY_RE.test(String(today))) return null
  const due = dayNumber(String(row.due).slice(0, 10))
  if (due - dayNumber(today) <= days) return null
  return { until: dayOf(due - days), due: row.due }
}

/** The repository a watched row belongs to: owner/repo of its ref, else of its address, else its first source */
export function repoOf(row) {
  const m = REF_RE.exec(String(row?.ref ?? ''))
  if (m) return m[1]
  const url = refOfUrl(row?.url)
  if (url) return url.replace(/#\d+$/, '')
  return row?.sources?.[0] ?? null
}

const isTaskRow = r => !r.inbox_id && !!r.task && r.key === `task:${r.task}`
const isStreamRow = r => !!(r.stream || r.work_kind === 'stream')
// what a task waits on: its blocker (task.py wait sets it with quiet_until), from the row or its card
const rowBlocked = r => !!(r?.blocked_by || r?.card?.state?.blocked_by)
// the words a next step names the person by: the briefing's own (briefing_view WHO_YOU) and cockpit.person_name
const MINE = ['me', 'you', 'self']

/** Whether a waiting row waits on someone else: it is blocked by something, or its next step names another person.
 *  A next step that names the person (cockpit.person_name, s.work.person) is their own: no wait on others */
export function waitsOnOthers(r, s) {
  if (rowBlocked(r)) return true
  const who = String(r?.card?.next?.who ?? '').trim().toLowerCase()
  const me = String(s?.work?.person ?? '').trim().toLowerCase()
  return !(who && (MINE.includes(who) || who === me))
}
// a row of Now: its section, or what puts a row there (urgency now or today, bucket do)
const inNow = (r, src) => src === 'now' || r.section === 'now' || r.urgency === 'now' || r.urgency === 'today' || r.bucket === 'do'

/** The parts of the page from the state it sees (areaScope). Every open row (flowUniverse) stands exactly once: on a
 *  point (the groups of FLOW_GROUPS), in Running now (`lane`: a start at work, a session linked to a task or
 *  recognised from what it did, a task's own tab at work or waiting) or in a group of Not now (`leftOut`, by why). A
 *  point or an entry of the lane may stand for no open row (a tab alone, a start whose item left the list), a row of
 *  Not now always stands for one. Live first (only with a terminal driver): the return card, the starts by stage, the
 *  sessions, the task tabs, the tabs that ask; then each open row by the first rule that fits. A point due later than
 *  cockpit.flow.ahead_days waits under Later until then (aheadOf), unless the viewer took it back on (ui.flowEarly).
 *  A card is {group, id, kind, row?, start?, tab?, task?, covers?, rows?, stage?}; an entry of the lane {group doing,
 *  lane, id, kind start, session or tab, row, tab, stage, how, title, at}; one of Not now {row, until, why, due, repo}.
 *  A watched row a GitHub list holds (on_board) stands in the group `github`, which names that list as `at`.
 *  Besides, every live session as a card of Running now (`sessions`, round 6: {id, kind live, session, tab, entry,
 *  stage}, entry the lane's entry in its tab), with or without a driver; it stands for no row, so no key or count moves.
 *  counts: points (the reports by their rows), running, left, extra (cards and entries that stand for no open row,
 *  less the tasks a question stands for beside its item), their total, and the session cards */
export function flowParts(s) {
  const nowMs = s?.now || Date.now()
  const model = s?.model ?? {}
  const driver = flowDriver(s)
  const { rows: uni, from } = universeOf(s)
  const named = new Map((model.task_rows ?? []).map(r => [r.key, r]))
  // every tab tells where a start stands (a quiet one is back at its shell), a shell asks nothing
  const allTabs = (s?.tabs?.tabs ?? []).filter(t => !t.is_control)
  const tabs = allTabs.filter(t => t.state !== 'shell')
  const answered = s?.ui?.answered ?? {}
  const asking = t => !isAnswered(answered[t.ref], t)
  const runs = t => !!t && (t.state === 'working' || t.state === 'waiting')
  const rowOfTask = slug => (slug ? uni.get(`task:${slug}`) ?? null : null)
  const used = new Set()      // row keys a card, an entry of the lane or a group already stands for
  const usedTabs = new Set()
  const take = row => { if (row?.key) used.add(row.key) }
  const out = { back: null, asks: [], result: [], lost: [], question: [], doing: [], task: [], issue: [], reports: [], lane: [], sessions: [] }
  const tabOf = ref => allTabs.find(t => t.ref === ref) ?? null
  if (driver) {
    // L1 the return card, only once the jump is armed (flowArm); its row and its tab stand nowhere else
    const jump = s?.ui?.flowJump
    if (jump?.armed) {
      const row = uni.get(jump.key) ?? null
      out.back = { group: 'back', id: 'back', kind: 'back', jump, row, tab: tabOf(jump.ref) }
      take(row)
      usedTabs.add(jump.ref)
    }
    // L2 the starts of the return channel by where they stand now: at work in Running now, else a card
    for (const r of model.returns ?? []) {
      const mine = allTabs.filter(t => t.ref === r.tab?.ref || (r.item && (t.slug === r.item || t.item === r.item)))
      let stage = flowStage(r, allTabs, nowMs)
      // answered from here: it works again, as far as the page knows, until the next read of its tab
      if (stage === 'asks' && mine.length && !mine.some(asking)) stage = 'working'
      const group = Object.hasOwn(STAGE_GROUP, stage) ? STAGE_GROUP[stage] : 'asks'
      if (!group || used.has(r.key)) continue
      const row = uni.get(r.key) ?? null
      const tab = tabOf(r.tab?.ref) ?? mine[0] ?? null
      if (group === 'lane') {
        out.lane.push({ group: 'doing', lane: true, id: `start:${r.key}`, kind: 'start', row, tab, start: r, stage, how: 'start',
          title: row?.title ?? r.title, at: r.at_ms ?? null })
      } else out[group].push({ group, id: `start:${r.key}`, kind: 'start', start: r, row, stage, tab, title: r.title, at: r.at_ms })
      used.add(r.key)
      for (const t of mine) usedTabs.add(t.ref)
    }
    // L3 a live session linked to a task (by hand, by its task tab, or recognised from what it did) while its tab works
    // or waits at its prompt; a second session on the same task stands without the row. The newest session of a tab
    // first, so the entry of a tab is the task its card shows (S)
    for (const x of [...(s?.sessions?.sessions ?? [])].sort((a, b) => (b?.started_ms ?? 0) - (a?.started_ms ?? 0))) {
      const tab = x?.task && x.tab?.ref && !usedTabs.has(x.tab.ref) ? tabOf(x.tab.ref) : null
      if (!runs(tab)) continue
      const key = `task:${x.task}`
      const row = used.has(key) ? null : rowOfTask(x.task)
      out.lane.push({ group: 'doing', lane: true, id: `session:${tab.ref}`, kind: 'session', row, tab, session: x, stage: tab.state,
        how: x.task_how ?? 'hand', title: (row ?? uni.get(key) ?? named.get(key))?.title ?? tab.name,
        at: x.task_since_ms ?? x.started_ms ?? tab.since_ms ?? null })
      used.add(key)
      usedTabs.add(tab.ref)
    }
    // L4 a task's own tab (its slug) at work or waiting at its prompt
    for (const t of allTabs) {
      const row = runs(t) && t.slug && !usedTabs.has(t.ref) ? rowOfTask(t.slug) : null
      if (!row || used.has(row.key)) continue
      out.lane.push({ group: 'doing', lane: true, id: `tab:${t.ref}`, kind: 'tab', row, tab: t, stage: t.state, how: 'tab', title: row.title ?? t.name,
        at: t.since_ms ?? null })
      take(row)
      usedTabs.add(t.ref)
    }
    // L5 the tabs that ask you, with or without a row, the oldest question first: they need you, so they are points
    // a session linked to that tab (by hand, by its task tab, or recognised) brings its task: it stands once, as the
    // card that asks, and goes back to Running now once its tab works again
    for (const t of tabs.filter(x => x.state === 'needs-you' && !usedTabs.has(x.ref) && asking(x)).sort((a, b) => (a.since_ms ?? 0) - (b.since_ms ?? 0))) {
      const linked = (s?.sessions?.sessions ?? []).find(v => v.task && v.tab?.ref === t.ref)
      const found = (t.slug ? rowOfTask(t.slug) : null) ?? (t.item ? uni.get(`inbox:${t.item}`) ?? null : null) ?? (linked ? rowOfTask(linked.task) : null)
      const row = found && !used.has(found.key) ? found : null
      out.asks.push({ group: 'asks', id: `tab:${t.ref}`, kind: 'tab', tab: t, row })
      take(row)
      usedTabs.add(t.ref)
    }
    out.asks.sort((a, b) => (a.tab?.since_ms ?? a.start?.at_ms ?? 0) - (b.tab?.since_ms ?? b.start?.at_ms ?? 0))
    out.result.sort((a, b) => (a.start.at_ms ?? 0) - (b.start.at_ms ?? 0))
    out.lost.sort((a, b) => (b.start.at_ms ?? 0) - (a.start.at_ms ?? 0))
  }
  // S every live session of this machine as one card of Running now (round 6), with a task or without one and with a
  // driver or without one (then without its tab): a lane entry in its tab is that card's (`entry`, its box), a tab that
  // stands as a point (the return card, one that asks, a finished start) keeps its session there, a tab back at its
  // shell and the control session (the Chat's) stand nowhere. One card per tab: of several sessions in one tab (one
  // went on after a compaction) the newest, with the task of the newest one that has one where it has none (its sid
  // too, so Not this task undoes that link). Rows of no row key: the keys and counts stay the lane's
  const laneOfTab = new Map(out.lane.filter(e => e.tab?.ref).map(e => [e.tab.ref, e]))
  const byTab = new Map()
  for (const x of s?.sessions?.sessions ?? []) {
    if (!x || x.tab?.is_control) continue
    const tab = driver && x.tab?.ref ? tabOf(x.tab.ref) : null
    if (tab?.state === 'shell' || (tab && !laneOfTab.has(tab.ref) && usedTabs.has(tab.ref))) continue
    const card = { id: `live:${x.id ?? x.sid}`, kind: 'live', session: x, tab, entry: tab ? laneOfTab.get(tab.ref) ?? null : null,
      stage: tab?.state ?? (x.status === 'busy' ? 'working' : 'idle') }
    if (!tab) { out.sessions.push(card); continue }
    const all = [...(byTab.get(tab.ref) ?? []), card]
    byTab.set(tab.ref, all)
  }
  for (const all of byTab.values()) {
    all.sort((a, b) => (b.session.started_ms ?? 0) - (a.session.started_ms ?? 0))
    const [card] = all
    const holder = card.session.task ? null : all.find(v => v.session.task)
    out.sessions.push(holder ? { ...card, session: { ...card.session, task: holder.session.task, task_how: holder.session.task_how,
      task_since_ms: holder.session.task_since_ms, sid: holder.session.sid } } : card)
  }
  out.sessions.sort((a, b) => (SESSION_RANK[a.stage] ?? 3) - (SESSION_RANK[b.stage] ?? 3) || (b.session.started_ms ?? 0) - (a.session.started_ms ?? 0))
  const left = Object.fromEntries(FLOW_LEFT_OUT.map(k => [k, []]))
  const leave = (why, row, extra = {}) => {
    left[why].push({ row, until: null, why: null, due: row.due ?? null, repo: null, ...extra })
    used.add(row.key)
  }
  // C: a point due later than the lead time waits under Later until then, unless the viewer took it back on
  const lead = flowSettings(s).ahead_days
  const today = isoDate(nowMs)
  const early = s?.ui?.flowEarly ?? {}
  const waits = row => {
    const a = aheadOf(row, today, lead)
    if (!a || early[row.key] === a.until) return false
    leave('later', row, { why: 'ahead', until: a.until, due: row.due })
    return true
  }
  // R1 what is hidden until a day
  for (const [key, r] of uni) if (from.get(key) === 'hidden' && !used.has(key)) leave('later', r, { why: 'hidden', until: r.hidden_until ?? null })
  const open = () => [...uni.values()].filter(r => !used.has(r.key))
  // R2 to R7 the inbox items: put off, given your yes, ideas, waiting or resting, the reports, the questions
  const questions = []
  const reports = []
  for (const r of open()) {
    if (r.inbox_state === 'deferred' && r.art === 'idea') leave('idea', r, { until: r.until ?? null })
    else if (r.inbox_state === 'deferred') leave('later', r, { why: 'deferred', until: r.until ?? null })
    else if (!r.inbox_id) continue
    else if (r.inbox_state === 'approved') leave('waiting', r)
    else if (r.art === 'idea') leave('idea', r)
    else if (r.bucket === 'waiting') leave('waiting', r)
    else if (r.bucket === 'resting') leave('resting', r)
    else if (r.art === 'report') reports.push(r)
    else questions.push(r)
  }
  // a question about a task stands for that task too (R8), the first one that names it
  for (const r of questions.sort(byDue)) {
    if (waits(r)) continue
    const task = rowOfTask(r.task)
    const covers = !!task && !used.has(task.key)
    out.question.push({ group: 'question', id: r.key, kind: 'row', row: r, task, covers })
    used.add(r.key)
    take(covers ? task : null)
  }
  const shown = reports.sort(byAge).filter(r => !waits(r))
  for (const r of shown) used.add(r.key)
  out.reports = shown.length ? [{ group: 'reports', id: 'reports', kind: 'reports', rows: shown }] : []
  // R9 to R15 the tasks and streams; R16 to R18 every other row (an issue, a pull request, a date)
  const tasks = []
  const issues = []
  for (const r of open()) {
    if (isTaskRow(r)) {
      if (isStreamRow(r)) leave('stream', r)
      else if (r.status === 'backlog') leave('idea', r)
      else if (!TASK_STATES.includes(r.status)) leave('resting', r)
      else if (r.bucket === 'waiting' && waitsOnOthers(r, s)) leave('waiting', r)
      else if (r.bucket === 'resting' || r.bucket === 'drop' || r.blocked_by) leave('resting', r)
      else if (!waits(r)) tasks.push(r)
    } else if (r.bucket === 'waiting') leave('waiting', r)
    else if (inNow(r, from.get(r.key))) { if (!waits(r)) issues.push(r) }
    else leave(r.on_board?.page ? 'github' : 'watch', r, { repo: repoOf(r) })
  }
  const ranks = rankMap(s)
  const order = (a, b) => byRank(ranks)(a, b) || byPrio(a, b) || byAge(a, b)
  for (const r of [...tasks, ...issues]) used.add(r.key)
  out.task = tasks.filter(r => r.status !== 'doing').sort(order).map(r => ({ group: 'task', id: r.key, kind: 'row', row: r }))
  out.doing = tasks.filter(r => r.status === 'doing').sort(order).map(r => ({ group: 'doing', id: r.key, kind: 'row', row: r }))
  out.issue = issues.sort((a, b) => (a.due && b.due ? a.due.localeCompare(b.due) : a.due ? -1 : b.due ? 1 : 0) || byPrio(a, b) || byKey(a, b))
    .map(r => ({ group: 'issue', id: r.key, kind: 'row', row: r }))
  // Running now, the newest first
  out.lane.sort((a, b) => (b.at ?? 0) - (a.at ?? 0))
  left.later.sort((a, b) => (a.until && b.until ? a.until.localeCompare(b.until) : a.until ? -1 : b.until ? 1 : 0) || byTitle(a.row, b.row))
  for (const k of ['watch', 'github']) left[k].sort((a, b) => (a.repo && b.repo ? a.repo.localeCompare(b.repo) : a.repo ? -1 : b.repo ? 1 : 0) || byKey(a.row, b.row))
  for (const k of ['waiting', 'resting', 'idea', 'stream']) left[k].sort((a, b) => byPrio(a.row, b.row) || byAge(a.row, b.row))
  const groups = FLOW_LEFT_OUT.filter(k => left[k].length)
    .map(reason => ({ reason, rows: left[reason], ...(reason === 'github' ? { at: boardOf(left.github, model.pages) } : {}) }))
  const leftN = groups.reduce((n, g) => n + g.rows.length, 0)
  out.leftOut = { total: leftN, groups }
  const queue = flowQueue(out, 'all')
  const points = queue.reduce((n, x) => n + (x.kind === 'reports' ? x.rows.length : 1), 0)
  const open1 = x => !!x.row?.key && uni.has(x.row.key)
  const extra = queue.filter(x => x.kind !== 'reports' && !open1(x)).length + out.lane.filter(x => !open1(x)).length - queue.filter(x => x.covers).length
  out.counts = { points, running: out.lane.length, left: leftN, extra, total: points + out.lane.length + leftN, sessions: out.sessions.length }
  return out
}

/** Where the rows of Not now a GitHub list holds stand: the list most of them name ({page, section}, the server's
 *  on_board) with its page's title, else the page's id */
function boardOf(entries, pages) {
  const n = new Map()
  for (const { row: { on_board: at } } of entries) {
    const k = `${at.page}/${at.section}`
    n.set(k, { at, count: (n.get(k)?.count ?? 0) + 1 })
  }
  const { page, section } = [...n.values()].sort((a, b) => b.count - a.count)[0].at
  return { page, section, title: (pages ?? []).find(p => p.id === page)?.title || page }
}

// the order of the session cards: a tab that asks (answered here, so no point), at work, waiting at its prompt, quiet
const SESSION_RANK = { 'needs-you': 0, working: 1, waiting: 2 }

/** What Running now lists (round 6): the cards of the live sessions, then the entries of the lane no session card
 *  holds (`loose`: a start at work or a task's own tab without a live session), their number `n` (the left column's
 *  count) and whether one of them works. A busy session works; one waiting at its prompt or quiet does not */
export function runningOf(parts) {
  const sessions = parts?.sessions ?? []
  const held = new Set(sessions.map(v => v.entry?.id).filter(Boolean))
  const loose = (parts?.lane ?? []).filter(e => !held.has(e.id))
  const working = loose.some(x => x.stage === 'working' || x.stage === 'started') || sessions.some(v => v.stage === 'working')
  return { sessions, loose, n: sessions.length + loose.length, working }
}

/** How many agents run now: the entries of Running now that are at work or starting (a start, a session or a task
 *  tab; one waiting at its prompt runs nothing). Let AI do it asks first once cockpit.flow.max_running of them run */
export const flowRunning = (s, parts = flowParts(s)) => parts.lane.filter(x => x.stage === 'started' || x.stage === 'working').length

/** The rows of Running now a box may tick: an entry's own open task (no stream). Ticked, such a row goes only into a
 *  merge or Done of a batch, never into a start, Later or Drop (batchPlan): an agent works on it. Each {id, row, x} */
export const laneRows = lane => (lane ?? []).filter(x => x.row && isTaskRow(x.row) && !isStreamRow(x.row)).map(x => ({ id: x.row.key, row: x.row, x }))

/** What drives a point in progress now: a start of the cockpit (`start`, its stage and since when), the agent tab of
 *  its task (`tab`, the tab's state), a session in a linked tab (`session`, by hand, by its task tab or recognised,
 *  its tab's state now), else nothing (`none`, with how many days ago its task last moved, from its updated day).
 *  {by, tab, since_ms, days, stage} */
export function flowDrive(x, s) {
  const nowMs = s?.now || Date.now()
  const tabs = (s?.tabs?.tabs ?? []).filter(t => !t.is_control)
  if (x.kind === 'start') return { by: 'start', tab: x.tab ?? null, since_ms: x.start.at_ms ?? null, days: null, stage: x.stage }
  if (x.kind === 'session') {
    const tab = tabs.find(t => t.ref === x.tab?.ref) ?? x.tab ?? null
    return { by: 'session', tab, since_ms: x.at ?? null, days: null, stage: tab?.state ?? 'working' }
  }
  // a card of a tab (one that asks, the return card while its tab is there, a task tab of Running now): that tab
  if ((x.kind === 'tab' || x.kind === 'back') && x.tab) return { by: 'tab', tab: x.tab, since_ms: x.tab.since_ms ?? null, days: null, stage: x.tab.state }
  const slug = x.row?.task
  const tab = slug ? tabOfTask(tabs, slug) : null
  if (tab && tab.state !== 'shell') return { by: 'tab', tab, since_ms: tab.since_ms ?? null, days: null, stage: tab.state }
  const linked = slug ? (s?.sessions?.sessions ?? []).find(v => v.task === slug && v.tab?.ref) : null
  const ltab = linked ? tabs.find(t => t.ref === linked.tab.ref) ?? null : null
  if (ltab) return { by: 'session', tab: ltab, since_ms: linked.task_since_ms ?? linked.started_ms ?? ltab.since_ms ?? null, days: null, stage: ltab.state }
  const day = DAY_RE.test(String(x.row?.updated ?? '')) ? new Date(`${String(x.row.updated).slice(0, 10)}T00:00:00`).getTime() : null
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

/** Whether Prio can order the left column: Jev orders the work page (its `jev:`), Jev is on and has its key */
export const prioOn = s => !!(workPageOf(s?.model?.pages)?.jev && s?.jev?.enabled && s?.jev?.ready)

/** The orders of the left column on offer, in the order of the switch: Themes while the themes are on, Areas,
 *  Prio while Jev orders the work page (prioOn) */
export const flowModes = s => [...(s?.themes?.enabled === true ? ['themes'] : []), 'areas', ...(prioOn(s) ? ['prio'] : [])]

/** How the left column groups: by Jev's squares when the person picked Prio and Jev orders the work page; by the
 *  themes the server keeps (cockpit.flow.themes on), unless the person picked the areas (ui.flowMode); by the areas
 *  while the themes are off or the server is older */
export function flowMode(s) {
  const want = s?.ui?.flowMode
  if (want === 'prio' && prioOn(s)) return 'prio'
  if (s?.themes?.enabled !== true) return 'areas'
  return want === 'areas' ? 'areas' : 'themes'
}

// the squares of a Jev order by the order object they were read from (one read per order, not per row)
const QUADS_SEEN = new WeakMap()

/** Jev's squares of the open points: Map key -> {quadrant, rank, who, at_ms} from the daily order of the work page
 *  (s.jevOrder, the round 2 Jev view), only while that order is at most cockpit.flow.rank_max_age_days old */
export function jevQuadrants(s) {
  const page = workPageOf(s?.model?.pages)
  const order = page ? s?.jevOrder?.[page.id]?.order : null
  if (!order || !Array.isArray(order.items)) return new Map()
  const nowMs = s?.now || Date.now()
  if (Number.isFinite(order.at_ms) && nowMs - order.at_ms > flowSettings(s).rank_max_age_days * DAY) return new Map()
  if (QUADS_SEEN.has(order)) return QUADS_SEEN.get(order)
  const out = new Map()
  for (const it of order.items) {
    if (it?.key && FLOW_QUADRANTS.includes(it.quadrant) && !out.has(it.key)) out.set(it.key, { quadrant: it.quadrant, rank: it.rank ?? null, who: it.who ?? null, at_ms: order.at_ms ?? null })
  }
  QUADS_SEEN.set(order, out)
  return out
}

const areaId = name => `a:${String(name).trim().toLowerCase()}`

/** The side a row stands on: its theme (t:<id>), its area (a:<name>) or its square of Jev (q:<quadrant>), else none */
function rowSide(row, s, mode, tab = null) {
  if (mode === 'prio') {
    const q = row ? jevQuadrants(s).get(row.key) : null
    return q ? `q:${q.quadrant}` : NO_SIDE
  }
  if (mode === 'themes') {
    const id = row ? s?.themes?.assign?.[row.key] : null
    return id && (s.themes.themes ?? []).some(t => t.id === id) ? `t:${id}` : NO_SIDE
  }
  const name = row ? rowProject(row) : tab?.workspace
  return name ? areaId(name) : NO_SIDE
}

/** The points of one side (`all` every one): a reports card splits, each side holds its own reports as one card. In
 *  Prio a square holds its points in Jev's order, the unrated ones by due, then the triage's rank, then priority and
 *  age; the walk goes the same way */
export function pointsIn(points, side, s, mode) {
  if (!side || side === 'all') return points ?? []
  const out = []
  for (const x of points ?? []) {
    if (x.kind === 'reports') {
      const rows = x.rows.filter(r => rowSide(r, s, mode) === side)
      if (rows.length) out.push({ ...x, rows })
    } else if (rowSide(x.row, s, mode, x.tab) === side) out.push(x)
  }
  if (mode !== 'prio') return out
  const quads = jevQuadrants(s)
  const rankIn = x => quads.get(x.kind === 'reports' ? x.rows[0]?.key : x.row?.key)?.rank ?? Infinity
  if (side.startsWith('q:')) return out.sort((a, b) => rankIn(a) - rankIn(b))
  const next = x => s?.triage?.items?.[x.row?.key]?.next_rank ?? Infinity
  const rowOf = x => x.row ?? x.rows?.[0] ?? {}
  return out.sort((a, b) => byDue(rowOf(a), rowOf(b)) || next(a) - next(b) || byPrio(rowOf(a), rowOf(b)) || byAge(rowOf(a), rowOf(b)))
}

/** The count of a side: its open points (reports by their rows) and how many of them need you */
function countOf(points) {
  const open = points.reduce((n, x) => n + (x.kind === 'reports' ? x.rows.length : 1), 0)
  return { open, you: points.filter(x => FLOW_YOU.includes(x.group)).length }
}

/** The entries of the left column: All on top, then each theme or area that holds a point, No theme yet or No area
 *  last when points stand outside them. A theme by its name (the server's order), an area by the order the start page
 *  gives the areas (the most frequent first), its colour the terminal workspace's of that name where one has one. In
 *  Prio the four squares always (an empty one too), then Not rated yet while it holds points. Each {id, name, tone,
 *  color, open, you, quadrant?} */
export function flowSides(s, points, mode = flowMode(s)) {
  const sides = []
  if (mode === 'prio') {
    for (const q of FLOW_QUADRANTS) sides.push({ id: `q:${q}`, quadrant: q, name: null, tone: QUAD_TONE[q], color: null, ...countOf(pointsIn(points, `q:${q}`, s, mode)) })
  } else if (mode === 'themes') {
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

// the tone of each square of Jev in the left column and the grid
const QUAD_TONE = { now: 'danger', plan: 'info', hand: 'warning', drop: 'muted' }

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
  // Jev last: its square drop says Drop (too big for what it brings, where the instance offers that reason), hand says
  // Let AI do it; now and plan say nothing a verb could take
  const q = jevQuadrants(s).get(row.key)
  if (q?.quadrant === 'drop' && ok('drop')) {
    return { verb: 'drop', drop: flowSettings(s).drop_reasons.includes('not_worth_it') ? 'not_worth_it' : null, reason: '', until: null, from: 'jev',
      at: q.at_ms, quadrant: 'drop' }
  }
  if (q?.quadrant === 'hand' && ok('do')) return { verb: 'do', reason: '', until: null, drop: null, from: 'jev', at: q.at_ms, quadrant: 'hand' }
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
  const by = how === 'suggested' ? 'suggestion' : 'batch'
  const done = []
  const later = []
  const drop = []
  const starts = []
  const skipped = []
  const parts = flowParts(s)
  let running = flowRunning(s, parts)
  const cap = flowSettings(s).max_running
  // what runs (Running now) goes into Done of a batch or a merge, never into a suggestion, a start, Later or Drop
  const lanes = new Set(parts.lane.map(x => x.row?.key).filter(Boolean))
  for (const row of rows ?? []) {
    if (lanes.has(row?.key) && how !== 'done') { skipped.push({ row, why: 'working' }); continue }
    const sug = how === 'suggested' ? flowSuggestion(row, s) : null
    const verb = how === 'suggested' ? sug?.verb : how
    if (!verb) { skipped.push({ row, why: 'no_suggestion' }); continue }
    if (verb === 'you') { skipped.push({ row, why: 'you' }); continue }
    if (!verbsFor(row).includes(verb)) { skipped.push({ row, why: 'not_offered' }); continue }
    if (verb === 'done') done.push(row)
    else if (verb === 'later') {
      const day = how === 'suggested' ? sug.until : value
      const a = flowAction('later', row, day, by)
      if (a) later.push(a)
      else skipped.push({ row, why: 'not_offered' })
    } else if (verb === 'drop') {
      const why = how === 'suggested' ? (sug.drop ? dropReasonWord(sug.drop, lang) : sug.reason || jevWhy(sug, lang)) : value
      const a = flowAction('drop', row, why, by)
      if (a) drop.push(a)
      else skipped.push({ row, why: 'not_offered' })
    } else if (verb === 'do') {
      if (atWork(row, s)) { skipped.push({ row, why: 'working' }); continue }
      if (running >= cap) { skipped.push({ row, why: 'running' }); continue }
      running += 1
      starts.push(flowAction('do', row, startNote(row, lang), by))
    } else skipped.push({ row, why: 'not_offered' })
  }
  // the drops that settle (not a shelve) go out together where they share a reason
  const settles = new Map()
  const shelves = []
  for (const a of drop) {
    if (a.verb !== 'settle') { shelves.push(a); continue }
    const k = a.args.text
    if (settles.has(k)) settles.get(k).args.keys.push(...a.args.keys)
    else settles.set(k, { verb: 'settle', args: { keys: [...a.args.keys], outcome: 'not_doing', text: k, by } })
  }
  const calls = [...(done.length ? [{ verb: 'settle', args: { keys: done.map(r => r.key), outcome: 'done', by } }] : []),
    ...later, ...shelves, ...settles.values(), ...starts]
  return { calls, skipped, counts: { done: done.length, later: later.length, drop: drop.length, do: starts.length },
    how, value, days: [...new Set(later.map(a => a.args.until))], reasons: [...new Set(drop.map(a => a.args.reason ?? a.args.text))] }
}

/** The half sentence of why Jev suggests a verb, by its square, in the page's language; '' for any other source */
export const jevWhy = (sug, lang = 'en') => (sug?.from === 'jev' ? (TABLES[lang] ?? TABLES.en).flow.list.jevWhy[sug.quadrant] ?? '' : '')

/** What a verb of a Not now list sends for its entries, before it is confirmed: Back on (`back`) per entry by why it
 *  waits (unhide what is hidden, reopen an item put off, take a point due later back on in this browser only, a task
 *  blocked or waiting running again, a task resting kept), every other verb exactly as a batch plans it (batchPlan).
 *  Back on carries no undo: put it off again instead. {calls, early: [key], skipped: [{row, why}], counts} */
export function leftPlan(entries, verb, s, value = '', lang = 'en') {
  if (verb !== 'back') {
    const plan = batchPlan((entries ?? []).map(e => e.row), verb, s, value, lang)
    return { ...plan, early: [], counts: { back: 0, ...plan.counts } }
  }
  const calls = []
  const early = []
  const skipped = []
  for (const e of entries ?? []) {
    const row = e.row
    if (e.why === 'hidden') calls.push({ verb: 'unhide', args: { key: row.key } })
    else if (e.why === 'deferred' && row.inbox_id) calls.push({ verb: 'inbox_reopen', args: { id: row.inbox_id } })
    else if (e.why === 'ahead') early.push(row.key)
    // running again clears a blocker (task.py wait --clear); a wait that comes from a next step of someone else has
    // nothing to clear, so it stays out and the line says so
    else if (isTaskRow(row) && !isStreamRow(row) && rowBlocked(row)) calls.push({ verb: 'task_running', args: { slug: row.task } })
    else if (isTaskRow(row) && !isStreamRow(row) && row.bucket !== 'waiting' && TASK_STATES.includes(row.status)) calls.push({ verb: 'task_keep', args: { keys: [row.key] } })
    else skipped.push({ row, why: 'not_offered' })
  }
  return { calls, early, skipped, counts: { back: calls.length + early.length, done: 0, later: 0, drop: 0, do: 0 }, how: 'back', value, days: [], reasons: [] }
}

/** The ticked rows that can be merged: open finite tasks, no stream and no inbox item */
export const mergeable = rows => (rows ?? []).filter(r => !!r && isTaskRow(r) && !isStreamRow(r))

const STATE_RANK = { doing: 0, review: 1, backlog: 2 }

/** The task a merge keeps, suggested: one an agent works on (`working`, its keys: its folder never moves from under
 *  the agent), then the one with the most activity (its feed's count of all rows), then the one moved last, then
 *  doing before review before backlog, then the first in the list. `feeds` key -> feed */
export function mergeKeep(rows, feeds = {}, working = new Set()) {
  const list = mergeable(rows)
  if (!list.length) return null
  const all = r => Number(feeds?.[r.key]?.counts?.all) || 0
  const moved = r => String(feeds?.[r.key]?.facts?.moved ?? '')
  const busy = r => (working.has(r.key) ? 1 : 0)
  return list.map((r, i) => ({ r, i })).sort((a, b) => busy(b.r) - busy(a.r) || all(b.r) - all(a.r) || moved(b.r).localeCompare(moved(a.r))
    || (STATE_RANK[a.r.status] ?? 3) - (STATE_RANK[b.r.status] ?? 3) || a.i - b.i)[0].r.key
}

/** The points due later taken back on before their day ({key: until}), without the ones whose day came */
export function flowEarlyKept(map, today) {
  if (!map || typeof map !== 'object') return {}
  return Object.fromEntries(Object.entries(map).filter(([k, v]) => typeof k === 'string' && typeof v === 'string' && DAY_RE.test(v) && v > today))
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
 *  task declined) and settles anything else as not doing, the reason with it. Advise is a question (c.flowAdvise).
 *  `by` says where the decision came from (suggestion, batch, instruction); a click of the person's own sends none */
export function flowAction(verb, row, value = '', by = null) {
  const text = String(value ?? '').replace(/\s+/g, ' ').trim()
  const key = row?.key
  if (!key) return null
  const tag = by ? { by } : {}
  if (verb === 'do') return text ? { verb: 'do_it', args: { keys: [key], note: text, ...tag } } : null
  if (verb === 'done') return { verb: 'settle', args: { keys: [key], outcome: 'done', ...tag } }
  if (verb === 'later') return /^\d{4}-\d{2}-\d{2}$/.test(text) ? { verb: 'later', args: { key, until: text, ...tag } } : null
  if (verb === 'drop') {
    if (!text || isStream(row)) return null
    return row.task && !row.inbox_id ? { verb: 'shelve', args: { key, reason: text.slice(0, 200), ...tag } }
      : { verb: 'settle', args: { keys: [key], outcome: 'not_doing', text, ...tag } }
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

// ---------------------------------------------------------------- round 3: the open point's tabs, its activity, its
// fields, the instruction line

// the tabs under the card of an open point, in the order of their bar
export const FLOW_TABS = ['desc', 'steps', 'activity', 'related']

// the filters of the Activity tab, in the order of their bar; a row of the feed names the ones it counts in
export const ACTIVITY_FILTERS = ['all', 'notes', 'docs', 'state', 'agents', 'code']

// at most this many keys go with one instruction (actions.py keys)
export const INSTRUCT_MAX = 50

/** The tabs a point has under its card: Description and Activity on every point with a row, Steps and Related where
 *  the row has a task (an inbox item that names one reads that task); a tab alone and the reports card have none */
export function pointTabs(x) {
  const row = x && x.kind !== 'reports' ? x.row : null
  if (!row?.key) return []
  return FLOW_TABS.filter(id => id === 'desc' || id === 'activity' || !!row.task)
}

/** The tab shown: the one chosen (ui.flowTab, kept from point to point) where the point has it, else Description */
export const pointTab = (tabs, want) => (tabs.includes(want) ? want : 'desc')

const STEP_RE = /^\s*[-*] \[( |x|X)\] (.+)$/

/** The steps of a task: the checklist lines of its STATUS.md, as they stand (read only: they are ticked there) */
export function stepsOf(detail) {
  return (detail?.sections ?? []).flatMap(sec => String(sec.text ?? '').split('\n').map(l => STEP_RE.exec(l)).filter(Boolean)
    .map(m => ({ done: m[1] !== ' ', text: m[2].trim() })))
}

/** What is related to a point: the other rows of its task as they stand in the model (its inbox items, the task's own
 *  row for an item that names it) and the paths its STATUS.md names under related. {rows, paths} */
export function relatedOf(x, s, detail) {
  const row = x && x.kind !== 'reports' ? x.row : null
  if (!row?.task) return { rows: [], paths: [] }
  const rows = [...indexRows(s?.model).values()].filter(r => r.task === row.task && r.key !== row.key)
  return { rows, paths: (detail?.related ?? []).map(String).filter(Boolean) }
}

/** The rows of the activity under a filter, in the server's order (the newest first) */
export const activityRows = (feed, filter = 'all') => (feed?.rows ?? []).filter(r => filter === 'all' || (r.filters ?? []).includes(filter))

/** The count of each filter: the server's, counted before it cut the rows at 200, else counted from the rows */
export function activityCounts(feed) {
  const given = feed?.counts && typeof feed.counts === 'object' ? feed.counts : null
  return Object.fromEntries(ACTIVITY_FILTERS.map(f => [f, given ? Math.max(0, Number(given[f]) || 0) : activityRows(feed, f).length]))
}

/** When a row of the activity happened, short: the day and the time ("27.10. 09:40", "Oct 27 09:40"), the day alone
 *  for a source that has only the day */
export function activityWhen(at, lang = 'en') {
  const m = /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?/.exec(String(at ?? ''))
  if (!m) return ''
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]), 12)
  let day
  try {
    day = new Intl.DateTimeFormat(lang, lang === 'de' ? { day: 'numeric', month: 'numeric' } : { month: 'short', day: 'numeric' }).format(d)
  } catch {
    day = `${Number(m[3])}.${Number(m[2])}.`
  }
  return m[4] ? `${day} ${m[4]}:${m[5]}` : day
}

/** The agent tab of a point that takes words: the tab that drives it (flowDrive), unless it is back at its shell */
export function flowTabOf(x, s) {
  if (!x || x.kind === 'reports') return null
  const tab = flowDrive(x, s).tab
  return tab && tab.state !== 'shell' ? tab : null
}

/** The tab of a point while it is live: at work, asking, or waiting at its prompt (the agent is there, it takes words).
 *  Then To tab is the strong way and no second agent starts, the same rule as atWork, so the verbs on the right and
 *  the instruction line agree on whether an agent works on the point */
export function flowLive(x, s) {
  const tab = flowTabOf(x, s)
  return tab && ['working', 'needs-you', 'waiting'].includes(tab.state) ? tab : null
}

/** A start's result line without its own head word ("Result: ..." or "Ergebnis: ...", returns.py RESULT_HEADS): the
 *  card says Result above it already */
export const resultText = text => String(text ?? '').replace(/^\s*(?:Result|Ergebnis)\s*:\s*/i, '')

/** The short name of an issue, a pull request or a merge request by its address ("owner/repo#7"; one path segment
 *  before it gives "repo#7"); null for any other link */
export function refOfUrl(href) {
  const m = /^https?:\/\/[^/]+\/(.+?)\/(?:-\/)?(?:issues|pull|pulls|merge_requests)\/(\d+)(?:[/?#]|$)/.exec(String(href ?? ''))
  return m ? `${m[1].split('/').slice(-2).join('/')}#${m[2]}` : null
}

/** The fields of the right column, in their order, each {id, ...} for the view to word: the theme (themes on), the
 *  area, who works on it (flowDrive), the prio (Jev's quadrant and rank from the feed, else the triage's rank, else the
 *  priority), the three bars of Jev, due, the source (its row, row.url, else STATUS.md's origin when it is a link),
 *  created and moved. Never the status: the card's head says it */
export function flowFields(x, s, feed = null, detail = null) {
  if (!x) return []
  const reports = x.kind === 'reports'
  const row = reports ? null : x.row ?? null
  const facts = feed?.facts ?? {}
  const jev = facts.jev && typeof facts.jev === 'object' ? facts.jev : null
  const out = []
  if (s?.themes?.enabled === true && row?.key) out.push({ id: 'theme', value: s.themes.assign?.[row.key] ?? null })
  out.push({ id: 'area', value: pointArea(x) })
  if (!reports) out.push({ id: 'who', drive: flowDrive(x, s) })
  if (!reports) {
    const rank = row ? s?.triage?.items?.[row.key]?.next_rank : null
    out.push({ id: 'prio', jev: jev ? { quadrant: jev.quadrant ?? null, rank: jev.rank ?? null } : null,
      rank: !jev && Number.isFinite(rank) ? rank : null, priority: row?.priority ?? null })
    if (jev) for (const id of ['urgency', 'impact', 'effort']) if (Number.isFinite(jev[id])) out.push({ id, value: jev[id] })
    out.push({ id: 'due', value: row?.due ?? null })
  }
  const origin = typeof detail?.front?.origin === 'string' ? detail.front.origin.trim() : ''
  const link = /^https?:\/\/\S+$/.test(origin) ? origin : null
  const url = row?.url ?? link
  out.push({ id: 'source', row, rows: reports ? x.rows : null, url: url ?? null, link: link && link !== url ? link : null })
  // a start whose item is not in the list: it was made and last moved when it started
  const started = x.kind === 'start' && Number.isFinite(x.start?.at_ms) ? localStamp(x.start.at_ms) : null
  if (!reports) {
    out.push({ id: 'created', value: facts.created ?? detail?.front?.created ?? row?.created ?? (row ? null : started) })
    out.push({ id: 'moved', value: facts.moved ?? detail?.front?.last_updated ?? started })
  }
  return out
}

/** A local moment as activity.py words it: "YYYY-MM-DDTHH:MM" */
function localStamp(ms) {
  const d = new Date(ms)
  return `${isoDate(ms)}T${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

/** A level of Jev's bars in a word: high from two thirds, low under one third */
export const meterLevel = v => (v >= 0.67 ? 'high' : v >= 0.34 ? 'mid' : 'low')

/** Whether a file is too large to attach (cockpit.flow.attach.max_mb): the page says so before it reads it */
export const attachTooBig = (bytes, s) => Number(bytes) > flowSettings(s).attach.max_mb * 1048576

/** What the instruction line speaks for: the open point (and its tab, where a reply can go), the reports card for its
 *  reports (as in the overview: no reply), else in the overview the points ticked there or every point of the side
 *  entered (`name` null: all of them); at most INSTRUCT_MAX keys go. {point, picked, reports, keys, n, cut, total (the
 *  rows of the overview), title, tab, name}, or null where no key stands behind it (a tab alone, a start whose item is
 *  not in the list): there a sentence could act on nothing */
export function instructScope(x, queue, picked, name, s) {
  const cut = keys => ({ keys: keys.slice(0, INSTRUCT_MAX), n: keys.length, cut: keys.length > INSTRUCT_MAX })
  if (x?.kind === 'reports') {
    const keys = pointKeys(x)
    return keys.length ? { point: false, picked: false, reports: true, ...cut(keys), title: null, tab: null, name } : null
  }
  if (x) {
    const row = x.row ?? null
    if (!row?.key) return null
    const tab = flowTabOf(x, s)
    return { point: true, picked: false, reports: false, keys: [row.key], n: 1, cut: false, title: row.title ?? '', tab: takesWords(tab, s) ? tab : null, name }
  }
  const all = (queue ?? []).flatMap(pointKeys)
  const ticked = picked?.size ? all.filter(k => picked.has(k)) : []
  const mine = ticked.length ? ticked : all
  if (!mine.length) return null
  // the rows the overview shows, a point without an item too: the label says how many of them the sentence reaches
  const total = (queue ?? []).reduce((n, q) => n + (q.kind === 'reports' ? q.rows.length : 1), 0)
  return { point: false, picked: ticked.length > 0, reports: false, ...cut(mine), total, title: null, tab: null, name }
}

/** Why a step of the plan leaves a point out, in the page's terms: a reply the server calls not offered while the
 *  point's tab asks a choice is that (asks: answered on the card); anything else as the server says it */
export function instructWhy(step, skip, s) {
  if (step?.op !== 'reply' || skip?.why !== 'not_offered' || !skip.key) return skip?.why ?? null
  const row = indexRows(s?.model).get(skip.key)
  return row && flowDrive({ kind: 'row', row }, s).tab?.state === 'needs-you' ? 'asks' : skip.why
}

/** Whether typed words may go to `tab`: it waits at its prompt, as the reply box has it (replyOptions). A tab that asks
 *  a choice takes its options on the card, one at work takes nothing (actions_tabs.py tab_send) */
const takesWords = (tab, s) => !!tab && replyOptions(tab, s).textBox

/** What Run sends for the plan the server made of a sentence (flow_instruct): every step through the verb it names,
 *  each with by instruction. Done for several goes out as one settle; Later with its day, Drop with its reason in the
 *  page's words; Let AI do it with its sentence (a mail is such a start, its sentence asks for a draft only) and, as in
 *  a batch, never where an agent works already nor past max_running; a reply goes to the tab its step names, through
 *  the reply guard, only while it waits at its prompt. A key no longer in the list stays out. {calls, skipped: [{step,
 *  key, title, why}]}, `step` the index of the step in plan.steps, so the page says each skip inside its step */
export function instructCalls(plan, s, lang = 'en') {
  const calls = []
  const skipped = []
  if (!plan || !Array.isArray(plan.steps)) return { calls, skipped }
  const rows = indexRows(s?.model)
  let running = flowRunning(s)
  const cap = flowSettings(s).max_running
  for (const [at, step] of plan.steps.entries()) {
    const out = (k, why) => skipped.push({ step: at, key: k, title: rows.get(k)?.title ?? null, why })
    const keys = (step.keys ?? []).filter(k => rows.has(k) || (out(k, 'gone'), false))
    if (!keys.length) continue
    const op = step.op === 'mail' ? 'do' : step.op
    if (op === 'reply') {
      const tab = (s?.tabs?.tabs ?? []).find(t => t.ref === step.tab_ref)
      const words = String(step.text ?? '').trim()
      if (tab && words && takesWords(tab, s)) calls.push(replySend(tab, words))
      else for (const k of keys) out(k, tab?.state === 'needs-you' ? 'asks' : 'no_tab')
      continue
    }
    if (op === 'done') {
      const ok = keys.filter(k => verbsFor(rows.get(k)).includes('done') || (out(k, 'not_offered'), false))
      if (ok.length) calls.push({ verb: 'settle', args: { keys: ok, outcome: 'done', by: 'instruction' } })
      continue
    }
    for (const k of keys) {
      const row = rows.get(k)
      if (!['later', 'drop', 'do'].includes(op) || !verbsFor(row).includes(op)) { out(k, 'not_offered'); continue }
      if (op === 'do') {
        if (atWork(row, s)) { out(k, 'working'); continue }
        if (running >= cap) { out(k, 'running'); continue }
      }
      const value = op === 'later' ? step.until : op === 'drop' ? dropReasonWord(step.reason ?? '', lang) : step.note
      const a = flowAction(op, row, value, 'instruction')
      if (!a) { out(k, op === 'later' ? 'bad_day' : 'not_offered'); continue }
      if (op === 'do') running += 1
      calls.push(a)
    }
  }
  return { calls, skipped }
}
