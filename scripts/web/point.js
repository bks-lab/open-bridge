// SPDX-License-Identifier: MIT
// Pure helpers of the one point view (stage 1, 04.11.2026). Where Work through is on (pointViewOn: the work tab offers
// it) every way to an item or a task opens the point view of Work through (views/flowpoint.js PointView): a title on
// any page, a link in a drawer or a card, a row of a list of Not now, a record of the Files tab. Here: whether that
// rule holds, where a key opens (pointOpen: the ui of Work through that shows it in the middle), the point of a row of
// Not now with its group as the walk (leftWalk, leftPoint), the row a page item stands for (infoPoint), a point of its own for a row that stands nowhere on the
// page (soloPoint: another area's open row as it is; a closed task, a settled item, read only, from its detail), what
// the item drawer held beside the fields (pointFacts: the fold Details at the foot of the right column; pointAbout:
// what it is about and the raw description, on top of Description; historyRows and activityFilters: the item's history
// as a filter of Activity), the basic verbs in their one order (BASIC_VERBS, basicVerbs: every point offers them, a
// verb that cannot go now stands off with why), the page row whose step makes an issue a task (adoptStepOf) and what a
// question about a point carries along (pointContext, the question path of the files view). Stage 2: a finished AI
// run opens in its group Finished, to read (pointOpen `flowReadAt`), and how long ago reads in days past a day (sinceText).
// Stage 3: a way that comes from a list (the task check, a page's rows, the start page, the Due list) brings the list
// along (pointList: what the walk walks; pointBack: where To the list leads; pointListAt: whether the point in front is
// still the one it opened), and who takes a next step reads in words (nextWho).
// Where Work through is off (cockpit.flow.enabled false, the default of open-bridge) none of it applies: the item
// drawer (views/overlays.js ItemDrawer) and the file card of the Files tab (views/dossier.js OpenFile) stay as they
// were. No DOM, no network, no state; logic.js passes every name on, the point test imports it under node.
import { TABLES } from './text.js'
import { ACTIVITY_FILTERS, areaScope, CONTEXT_MAX, coveredKeys, duration, fileContext, fileFacts, flowMode, flowParts, flowUniverse, flowWhere,
  rowProject, sessionsInFlow, triageKey } from './logic.js'

/** Whether every way to an item or a task opens the one point view: the work tab offers Work through
 *  (cockpit.flow.enabled, kept by cockpit.work_views), the rule the sessions and the task check follow too
 *  (logic.js sessionsInFlow). Off, the item drawer and the file card stay */
export const pointViewOn = s => sessionsInFlow(s)

/** Where a way that names a row opens it in Work through: the patch of the ui that shows it in the middle, by where
 *  the row stands on the page as the work tab sees it (flowWhere over areaScope): its point at the level of all (the
 *  walk walks the queue, Back leads to the overview), its entry of Running now, its row in its group of Not now
 *  (`flowLeftAt` {id, i}, held as the queue holds a point: the walk walks the group, Back leads to its list), else a
 *  point of its own (`flowSolo`: another area's row, a closed task, a settled item; `file` the folder of a closed copy,
 *  which no open row of the slug stands for). The ticks and a plan of the
 *  instruction line belong to what was open before, so they go. Null without a key */
export function pointOpen(s, key, file = null) {
  if (!key) return null
  const ui = s?.ui ?? {}
  const work = areaScope({ ...s, ui: { ...ui, page: 'briefing' } })
  const to = file ? null : flowWhere(work, key)
  const base = { flowPicked: [], flowPlan: null }
  if (to?.view === 'point') return { ...base, flowView: 'point', flowAt: { id: to.id, i: 0 }, flowSide: { ...(ui.flowSide ?? {}), [flowMode(s)]: null } }
  if (to?.view === 'run') return { ...base, flowView: 'run', flowRunId: to.id, flowRunFrom: 'overview' }
  // a finished AI run (stage 2): in its group Finished, to read, held as the queue holds a point
  if (to?.view === 'read') return { ...base, flowView: 'read', flowReadAt: { id: to.id, i: Math.max(0, (flowParts(work).read ?? []).findIndex(x => x.id === to.id)) } }
  if (to?.view === 'left') {
    const i = Math.max(0, leftWalk(flowParts(work), to.id).findIndex(x => x.id === key))
    return { ...base, flowView: 'left', flowLeft: to.id, flowLeftAt: { id: key, i }, flowLeftPicked: ui.flowLeft === to.id ? ui.flowLeftPicked ?? [] : [] }
  }
  return { ...base, flowView: 'solo', flowSolo: { key, file: file ?? null } }
}

/** Where the page stands when a way opens a row from a list: its page and, on the work tab, the view and the place of
 *  Work through (the view, the group of Not now, the row of a group, the finished run, the entry of Running now, the
 *  point of its own, the point of the queue), so To the list leads back to that very place */
export function pointBack(s) {
  const ui = s?.ui ?? {}
  const keep = ['workView', 'flowView', 'flowLeft', 'flowLeftAt', 'flowReadAt', 'flowRunId', 'flowRunFrom', 'flowSolo', 'flowAt']
  return { page: ui.page ?? null, ui: Object.fromEntries(keep.filter(k => ui[k] !== undefined).map(k => [k, ui[k]])) }
}

/** The list a way to a row came from (the queue of peek or openItem: [{key, title}], the check's rows, a page's rows,
 *  the start page's, the Due list), as Work through walks it with the row in front (ui.flowList): {items: [{key,
 *  title}], i, back}, each key once in the list's order; null without a list or where the list does not hold the key */
export function pointList(queue, key, back) {
  const seen = new Set()
  const items = []
  for (const e of queue ?? []) {
    if (!e?.key || seen.has(e.key)) continue
    seen.add(e.key)
    items.push({ key: String(e.key), title: e.title ?? null })
  }
  const i = items.findIndex(e => e.key === key)
  return i < 0 ? null : { items, i, back: back ?? null }
}

/** The list the point in front was opened from: while that row stands there (its point, its entry, its row of a
 *  group, a point of its own, a finished run by its key, or a point that covers it), else null and the point walks
 *  and goes back as its place does */
export function pointListAt(list, x) {
  const key = list?.items?.[list.i]?.key
  if (!key || !x) return null
  return x.id === key || x.start?.key === key || coveredKeys(x).includes(key) ? list : null
}

/** Who takes a next step in words (card.py next.who, from STATUS.md): me and the Bridge by the card's word table, the
 *  owner by the name the config gives (cockpit.person_name: the whole name, or its first word as STATUS.md writes it,
 *  any case), anyone else by the name as written with its first letter capital; null without one */
export function nextWho(who, s, lang = 'en') {
  const raw = String(who ?? '').trim()
  if (!raw) return null
  const words = (TABLES[lang] ?? TABLES.en).card.who
  const low = raw.toLowerCase()
  if (Object.hasOwn(words, low)) return words[low]
  const owner = String(s?.work?.person ?? s?.server?.person ?? '').trim()
  if (owner && (low === owner.toLowerCase() || low === owner.split(/\s+/)[0].toLowerCase())) return owner
  return raw.charAt(0).toUpperCase() + raw.slice(1)
}

/** The row a page item stands for on the page of Work through, by its key (an inbox item or a task, logic.js triageKey)
 *  or its own id (the ref of a row such as an application or an issue, row_id): the key where that row stands there
 *  (a point, an entry, a row of Not now), else null, and the item keeps its info drawer (a gauge, a date, a machine) */
export function infoPoint(s, it) {
  if (!it) return null
  const work = areaScope({ ...s, ui: { ...(s?.ui ?? {}), page: 'briefing' } })
  const rows = [...flowUniverse(work).values()]
  const key = triageKey(it) ?? (typeof it.row_id === 'string' && it.row_id ? rows.find(r => r.ref === it.row_id)?.key ?? null : null)
  return key && flowWhere(work, key) ? key : null
}

/** How long ago, in words that never say hours above a day: minutes and hours within a day (logic.js duration), days
 *  after it (text-flow.js one.days, the case the sentences of Who works on it take) */
export function sinceText(ms, lang = 'en') {
  const min = Math.max(0, Math.floor(Number(ms) / 60000) || 0)
  if (min < 24 * 60) return duration(min * 60000)
  return (TABLES[lang] ?? TABLES.en).flow.one.days(Math.floor(min / (24 * 60)))
}

/** The rows of a group of Not now as points, in the order its list shows them: the walk of a row opened from that
 *  list. Each {group 'left', left (the group), id (the row's key), kind 'row', row, entry (the group's entry)} */
export function leftWalk(parts, reason) {
  const g = (parts?.leftOut?.groups ?? []).find(x => x.reason === reason)
  return (g?.rows ?? []).filter(e => e?.row?.key).map(e => ({ group: 'left', left: reason, id: e.row.key, kind: 'row', row: e.row, entry: e }))
}

/** The point of one row of a group of Not now, null once the row left the group (decided, back on) */
export const leftPoint = (parts, reason, key) => leftWalk(parts, reason).find(x => x.id === key) ?? null

const isTaskKey = key => /^task:/.test(String(key ?? ''))

/** Where the detail of a point of its own is read (c.loadTask, c.loadInbox): a task by its slug or the folder of its
 *  closed copy, an inbox item by its id; null for any other key */
export function soloSource(solo) {
  const key = String(solo?.key ?? '')
  if (isTaskKey(key)) return { kind: 'task', id: solo.file ?? key.slice(5) }
  if (key.startsWith('inbox:')) return { kind: 'inbox', id: key.slice(6) }
  return null
}

/** A point of its own for a row that stands nowhere on the page (pointOpen `flowSolo`): another area's open row as
 *  it is (the whole model's, its verbs act on it), else what its detail says: a task the model lists in no section
 *  from its STATUS.md (a new backlog task: open, the server resolves every open task:<slug>, so its verbs go; a
 *  closed one, or `file` the folder of a closed copy, read only), a settled inbox item from its item.yaml, read only.
 *  {group 'solo', id, kind 'row', row, readOnly, file}; null while its detail is still read, and for a key with
 *  nothing known of it */
export function soloPoint(s, solo) {
  const key = solo?.key
  if (!key) return null
  const open = solo.file ? null : flowUniverse({ ...s, model: s?.wholeModel ?? s?.model }).get(key)
  if (open) return { group: 'solo', id: key, kind: 'row', row: open, readOnly: false, file: null }
  const src = soloSource(solo)
  if (src?.kind === 'task') {
    const data = s?.details?.task?.[src.id]?.data
    if (!data) return null
    const f = data.front ?? {}
    const slug = key.slice(5)
    const stream = data.kind === 'stream' || data.work_kind === 'stream' || data.work_kind === 'done_stream'
    const closed = !!solo.file || !['task', 'stream'].includes(data.kind)
    // its area: the card's (card.py reads the front matter), else the one the Files tab's list named for the record
    const rec = (s?.records?.data?.records ?? []).find(r => (solo.file ? r.path === solo.file : r.slug === slug && r.kind !== 'done'))
    return { group: 'solo', id: key, kind: 'row', readOnly: closed, file: solo.file ?? null,
      row: { key, task: slug, title: data.card?.title || f.headline || slug, status: f.status ?? null, priority: f.priority ?? null,
        task_type: f.type ?? null, area: data.card?.area || rec?.area || null, blocked_by: f.blocked_by ?? null, card: data.card ?? null, stream,
        work_kind: data.work_kind ?? null, origin: data.origin ?? null, settle: closed || stream ? [] : ['done', 'not_doing'] } }
  }
  if (src?.kind === 'inbox') {
    const data = s?.details?.inbox?.[src.id]?.data
    const it = data?.item
    if (!it) return null
    return { group: 'solo', id: key, kind: 'row', readOnly: true, file: null,
      row: { key, inbox_id: src.id, title: it.summary || src.id, inbox_state: it.state ?? null, inbox_kind: it.kind ?? null, task: it.task ?? null,
        urgency: it.urgency ?? null, gate: it.gate ?? null, due: it.due ?? null, card: data.card ?? null, origin: data.origin ?? null, settle: [] } }
  }
  return null
}

/** The facts the item drawer held beside the fields, for the fold Details at the foot of the right column, in this
 *  order, each {id, value, ...} for the view to word, only those with a value: an inbox item its kind and approval
 *  gate (its urgency is a field to change since stage 3, flow.js flowFields `when`), who closes it (`probe`: a check closes it) and when it closes on its own, what runs on its yes, its
 *  key and its id (from its detail, /api/inbox); a task its type, what blocks it and the path of its STATUS.md; any
 *  other row its ref and its key. Created and the source stay fields of their own */
export function pointFacts(x, item = null, detail = null) {
  const row = x && x.kind !== 'reports' ? x.row : null
  if (!row?.key) return []
  const out = []
  const put = (id, value, extra = {}) => { if (value != null && String(value).trim() !== '') out.push({ id, value, ...extra }) }
  if (row.inbox_id) {
    put('kind', item?.kind ?? row.inbox_kind)
    put('gate', item?.gate ?? row.gate)
    if (item) {
      out.push({ id: 'closer', value: item.closer ?? null, probe: !!item.closes_when })
      out.push({ id: 'closes', value: item.closes_when ?? null })
      put('runs', item.action_display)
      put('key', item.key)
    }
    put('id', row.inbox_id)
    return out
  }
  if (row.task && row.key === `task:${row.task}`) {
    put('kind', detail?.front?.type ?? row.task_type)
    put('blocked', detail?.front?.blocked_by ?? row.blocked_by)
    put('file', detail?.path ?? `work/${row.stream || row.work_kind === 'stream' ? 'streams' : 'tasks'}/${row.task}/STATUS.md`)
    return out
  }
  put('ref', row.ref)
  put('id', row.key)
  return out
}

/** What a point is about, on top of its Description (the item drawer's What it is about and its Detail): the day's
 *  triage of the row (its gist as the head, why it needs you where only you can do it, its reason), the raw
 *  description of an inbox item (its detail, `cut` where the server shortened it) and, since stage 3, why it is here
 *  (the briefing's reasons, row.why, the detail column's Why it is here) and the lines its page writes of its task
 *  (`lines`, pageLinesOf). Null with none of them */
export function pointAbout(row, s, item = null) {
  if (!row?.key) return null
  const tri = s?.triage?.items?.[row.key] ?? null
  const word = v => String(v ?? '').trim() || null
  const head = word(tri?.gist)
  const you = tri?.doer === 'you'
  const why = word(tri?.reason)
  const text = word(item?.detail)
  const reasons = (Array.isArray(row.why) ? row.why : []).map(word).filter(Boolean)
  const lines = pageLinesOf(row, s)
  if (!head && !you && !why && !text && !reasons.length && !lines.length) return null
  return { head, you, need: you ? word(tri?.why) : null, why, text, cut: !!item?.detail_truncated, reasons, lines }
}

/** The lines a page writes of a task (a page item that names the task and carries lines: next, blocked, a kind of its
 *  own), the first such item's; none for a row without a task (the detail column's lines of a task) */
export function pageLinesOf(row, s) {
  const slug = row?.task
  if (!slug) return []
  for (const p of s?.model?.pages ?? []) for (const sec of p.sections ?? []) for (const it of sec.items ?? []) {
    if (it?.task === slug && (it.lines ?? []).length) return it.lines
  }
  return []
}

/** The history of an inbox item (its events, /api/inbox), newest first, as rows of the filter History of Activity:
 *  {id, at, kind 'history', verb, by, until, note} */
export function historyRows(events) {
  return (Array.isArray(events) ? events : []).filter(e => e && e.verb)
    .map((e, i) => ({ id: `history:${i}`, at: String(e.at ?? ''), kind: 'history', verb: String(e.verb), by: e.by ?? null, until: e.until ?? null,
      note: e.note ?? e.text ?? null }))
    .sort((a, b) => b.at.localeCompare(a.at))
}

/** The filters of Activity for a point: those of the feed, and History last where the point has a history of its own
 *  (an inbox item's events, historyRows): a filter of its own, never counted in All, since the feed replays the
 *  state changes among them already */
export const activityFilters = history => ((history ?? []).length ? [...ACTIVITY_FILTERS, 'history'] : ACTIVITY_FILTERS)

// the basic verbs of every point, in the one order the right column shows them: Let AI do it, Done, Later until,
// Drop because, then Make it a task where the point can become one
export const BASIC_VERBS = ['do', 'done', 'later', 'drop', 'task']

/** The basic verbs of a point's row in their one order (BASIC_VERBS), each {id, off}: `off` names why it cannot go
 *  now, null when it can. Let AI do it is off while an agent works on the point (`live`, `running`: no second agent
 *  beside it) and on an item whose yes is given (it runs on its own); Done and Drop are off while its tab asks (nothing
 *  closes what waits for an answer) and on a stream (it runs on, it never ends this way), Done too where the row
 *  cannot be settled; Later always goes. Make it a task stands on every inbox item (verb to_task) and on an issue
 *  without a task whose page row offers the step that makes one (`adopt`, adoptStepOf), never on a task. A person
 *  (access.py) gets neither a start nor a new task */
export function basicVerbs(row, { live = false, asks = false, running = false, person = false, adopt = null } = {}) {
  if (!row?.key) return []
  const stream = !!(row.stream || row.work_kind === 'stream')
  const out = []
  if (!person) out.push({ id: 'do', off: live || running ? 'working' : row.inbox_state === 'approved' ? 'approved' : null })
  out.push({ id: 'done', off: asks ? 'asks' : stream ? 'stream' : (row.settle ?? []).includes('done') ? null : 'unsettled' })
  out.push({ id: 'later', off: null })
  out.push({ id: 'drop', off: asks ? 'asks' : stream ? 'stream' : null })
  if (!person && (row.inbox_id || (adopt && !row.task))) out.push({ id: 'task', off: null })
  return out
}

/** The page row whose step makes an issue a task of this Bridge (the GitHub page's step adopt, briefing.py
 *  BUILTIN_ROW_STEPS, sent as row_action): {page, section, index} of the item whose row_id is the row's ref, null for a
 *  row that is no issue, has a task or whose page offers no such step (a pull request never does) */
export function adoptStepOf(row, s) {
  if (!row?.ref || row.task || row.inbox_id) return null
  for (const p of s?.model?.pages ?? []) {
    for (const sec of p.sections ?? []) {
      const it = (sec.items ?? []).find(x => x?.row_id === row.ref && (x.actions ?? []).some(a => a?.id === 'adopt'))
      if (it) return { page: p.id, section: sec.id, index: it.index }
    }
  }
  return null
}

/** What a question about a point carries along as data (the files view's question path, actions.py ask `context`):
 *  a task its file as the files view words it (fileContext), any other row its title, key, state, area, brief, next
 *  step, what the triage made of it, its raw description and its link. Cut to CONTEXT_MAX, never refused */
export function pointContext(x, s, detail = null, item = null, lang = 'en') {
  const row = x && x.kind !== 'reports' ? x.row : null
  if (!row?.key) return ''
  if (row.task && row.key === `task:${row.task}`) return fileContext(fileFacts(row.task, detail, row), lang)
  const w = (TABLES[lang] ?? TABLES.en).flow.ask.ctx
  const card = row.card ?? null
  const tri = s?.triage?.items?.[row.key] ?? null
  const state = row.inbox_state ?? row.status ?? null
  const lines = [`${w.point}: ${row.title ?? row.key}`, `${w.key}: ${row.key}`, state ? `${w.state}: ${state}` : null,
    rowProject(row) ? `${w.area}: ${rowProject(row)}` : null, row.task ? `${w.task}: ${row.task}` : null,
    card?.goal ? `${w.goal}: ${card.goal}` : null, ...(card?.acceptance ?? []).slice(0, 5).map(a => `- ${a}`),
    card?.next?.what ? `${w.next}: ${card.next.what}` : null, tri?.gist ? `${w.about}: ${tri.gist}` : null,
    item?.detail ? `${w.detail}: ${item.detail}` : null, row.url ? `${w.link}: ${row.url}` : null, w.read].filter(Boolean)
  const out = lines.join('\n')
  return out.length <= CONTEXT_MAX ? out : out.slice(0, CONTEXT_MAX)
}
