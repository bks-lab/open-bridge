// SPDX-License-Identifier: MIT
// Pure helpers of the cockpit's files view: the queue of files, what a file's drawers hold, its next step,
// the search and what a question asked in a file carries along, and the start of the files tab (its records, their
// filters, what its question to the AI sends and holds back, the point of Work through its right column shows). No DOM, no network, no state. logic.js
// passes every name on, so a view may import it from either; the frontend test imports this file under node.
import { TABLES } from './text.js'
import { CONTEXT_MAX, FILES_PAGE, filesOn, flowParts, flowQueue, flowUniverse, indexRows, liveStage, queueOf } from './logic.js'
import { areaScope, inProject, rowProject } from './areas.js'

/** The files the files view walks under the filters of the files tab (areaScope as there, whatever page is open):
 *  what Next and Previous, n and p and a found file see */
export function scopedFileQueue(s) {
  const v = areaScope({ ...s, ui: { ...s.ui, page: FILES_PAGE } })
  return fileQueue(v.tabs?.tabs ?? [], v.model, s.now || Date.now(), s.sessions?.runs)
}

// ---------------------------------------------------------------- the start of the files tab

export const RECORD_STATES = ['open', 'done', 'all']
// what a record is: a closed one is its kind too (work_kind done_task, done_stream), closed is a state
export const RECORD_KINDS = ['task', 'stream']
// the records a question to the AI takes at most (work_find.py ASK_FILES_MAX, the server checks it again)
export const ASK_FILES_MAX = 12

const fold = x => String(x ?? '').toLowerCase()

/** A record's area, from one place for the list and the opened record: the area the cockpit names (its row, its
 *  file of model.files), else the one the server read from its front matter (`fallback`: the record's area, its
 *  context) */
export function recordArea(row, file, fallback = null) {
  return rowProject(row) || file?.area_names?.[0] || fallback || null
}

/** A matching line as text to read: no Markdown marks (bold, italic, code, a heading or list mark), a table row's
 *  cells joined by a dot (also a row the snippet cut short, its … kept), a front matter line by its value; a `slug:`
 *  line is no match to show (null) */
export function hitText(line) {
  const raw = String(line ?? '').trim()
  if (!raw || /^slug\s*:/i.test(raw)) return null
  const cut = /^…/.test(raw) ? '…' : ''
  const body = raw.replace(/^…\s*/, '')
  const row = /^\|/.test(body) || /\|$/.test(body) || /\|.*\|/.test(body) || (!!cut && body.includes(' | '))
  const cells = row ? body.replace(/^\|/, '').replace(/\|$/, '').split('|').map(x => x.trim()).filter(Boolean).join(' · ') : body
  const front = cells.match(/^[a-z][a-z_]*:\s+["']?(.*?)["']?$/)
  return (cut + (front && !row ? front[1] : cells)).replace(/^#{1,6}\s+/, '').replace(/^[-*+]\s+/, '').replace(/\*\*|__|`/g, '')
    .replace(/(^|[\s(])[*_]([^*_\s][^*_]*?)[*_](?=[\s).,:;!?]|$)/g, '$1$2').replace(/\s+/g, ' ').trim() || null
}

/** The records of the files tab's start (GET /api/records, `s.records`) as it lists them under its filters: the
 *  words of ui.filesQ, every one in the title, slug, area or theme, or in what the server's search found for those
 *  words (s.find, with its first line as `hit`); ui.area as everywhere; ui.filesState open (default), done or all;
 *  ui.filesKind task or stream (a closed one by what it was). A record's area is recordArea's; its theme the one
 *  Work through placed its point in; its `hit` the first matching line that reads as text (hitText). Newest change first, the ones whose title
 *  or slug holds the words before the rest. {rows, areas, status, error}: `areas` every area named, for the chips */
export function recordList(s) {
  const records = s?.records?.data?.records ?? []
  const model = s?.wholeModel ?? s?.model
  const rows = indexRows(model)
  const files = new Map((model?.files ?? []).map(f => [f.slug, f]))
  const themes = new Map((s?.themes?.themes ?? []).map(t => [t.id, t.name]))
  const ui = s?.ui ?? {}
  const q = String(ui.filesQ ?? '').replace(/\s+/g, ' ').trim()
  const words = q ? [...new Set(fold(q).split(' '))] : []
  const found = s?.find?.status === 'ok' && s.find.q === q ? new Map((s.find.data?.groups ?? []).map(g => [g.path, g])) : new Map()
  const state = RECORD_STATES.includes(ui.filesState) ? ui.filesState : 'open'
  const kind = RECORD_KINDS.includes(ui.filesKind) ? ui.filesKind : null
  const out = []
  const areas = new Map()
  for (const r of records) {
    const open = r.kind !== 'done'
    const row = open ? rows.get(`task:${r.slug}`) : null
    const area = recordArea(row, files.get(r.slug), r.area)
    if (area && !areas.has(fold(area))) areas.set(fold(area), area)
    const theme = open ? themes.get(s?.themes?.assign?.[`task:${r.slug}`]) ?? null : null
    if (state === 'open' ? !open : state === 'done' ? open : false) continue
    if (kind && String(r.work_kind ?? '').replace(/^done_/, '') !== kind) continue
    if (ui.area && !inProject({ area, area_names: [r.area] }, ui.area)) continue
    const g = found.get(r.path)
    const named = words.every(w => fold(`${r.title} ${r.slug}`).includes(w))
    if (words.length && !g && !words.every(w => fold(`${r.title} ${r.slug} ${area ?? ''} ${theme ?? ''}`).includes(w))) continue
    // the first line that reads as text and says more than the title
    const hit = (g?.hits ?? []).map(h => hitText(h.text)).find(x => x && fold(x) !== fold(r.title)) ?? null
    out.push({ ...r, area, theme, hit, named: !words.length || named })
  }
  out.sort((a, b) => (b.named - a.named) || String(b.updated ?? '').localeCompare(String(a.updated ?? '')))
  return { rows: out, areas: [...areas.values()], status: s?.records?.status ?? null, error: s?.records?.error ?? null }
}

/** What the files tab's question to the AI sends: the folders of the first ASK_FILES_MAX records listed, each once,
 *  but every one the block list (cockpit.files_search.block) holds back; those are counted with the words that held
 *  them. A record the server checked names those words (`held`, GET /api/records: it reads the text that would go
 *  too, actions_work.record_check), so the count is the server's; one without (an older server) is checked here by
 *  its area, theme, path and title, case folded. The server holds them back again. {paths, held: {n, words}} */
export function askPlan(rows, words) {
  const block = (words ?? []).filter(w => typeof w === 'string' && w)
  const seen = new Set()
  const paths = []
  const hit = new Set()
  let held = 0
  for (const r of rows ?? []) {
    if (paths.length + held >= ASK_FILES_MAX) break
    if (!r?.path || seen.has(r.path)) continue
    seen.add(r.path)
    const hay = [r.area, r.theme, r.path, r.title].filter(Boolean).map(fold)
    const by = Array.isArray(r.held) ? block.filter(w => r.held.some(x => fold(x) === fold(w)) || hay.some(h => h.includes(fold(w))))
      : block.filter(w => hay.some(h => h.includes(fold(w))))
    if (by.length) { held += 1; by.forEach(w => hit.add(w)) } else paths.push(r.path)
  }
  return { paths, held: { n: held, words: block.filter(w => hit.has(w)) } }
}

/** The point a record open in the files tab stands for in its right column (views/flowside.js FlowAside, round 6d):
 *  the open task's row (flowUniverse, across every area), as Work through shows it where it holds that row (a point
 *  or an entry of Running now, flowParts), else as a task point of its own. `open` is a slug, or the folder of a
 *  closed copy, which has none, as a task no row names has none: its verbs would act on nothing */
export function recordPoint(s, open) {
  if (!open || String(open).includes('/')) return null
  const key = `task:${open}`
  const row = flowUniverse({ ...s, model: s?.wholeModel ?? s?.model }).get(key)
  if (!row) return null
  const parts = flowParts(s)
  return [...flowQueue(parts, 'all'), ...parts.lane].find(x => x.kind !== 'reports' && x.row?.key === key)
    ?? { group: 'task', id: key, kind: 'row', row }
}

/** Where a found file opens: at its place in the filtered queue, the walk on (ui.filesWalk), else beside the queue
 *  (a file of another area, a backlog task); a closed one always beside it, by its folder, since a slug can be open
 *  and closed at once */
export function fileOpen(s, slug, path) {
  const closed = typeof path === 'string' && path.startsWith('work/done/')
  const queue = closed ? [] : scopedFileQueue(s)
  const i = queue.findIndex(x => x.slug === slug)
  return i >= 0 ? { dossierAt: { id: queue[i].id, i }, dossierOpen: null, filesWalk: true } : { dossierOpen: closed ? path : slug }
}

/** Where a click on a task's file shows it (c.openFile from a card, Work through, the start page, a drawer or the
 *  files tab): the files tab with that record open, at its place in the walk where the filtered queue holds it
 *  (fileOpen); in the files tab with nothing over it the page stays. Only where cockpit.work_views keeps no files
 *  view the item drawer takes it over the page, which stays as it was. {item} or {ui, page} */
export function fileClick(s, slug, path) {
  if (s.ui?.page === FILES_PAGE && !s.ui.drawer && !s.ui.tabView) return { ui: fileOpen(s, slug, path) }
  if (!filesOn(s)) return { item: `task:${slug}` }
  return { ui: { drawer: null, item: null, ...fileOpen(s, slug, path) }, page: FILES_PAGE }
}

const FILE_STATES = ['doing', 'review']

// a workflow run whose result is there to check: finished, or failed (a killed one was stopped on purpose)
const RUN_RESULTS = ['completed', 'failed']

/** The task a start of the return channel belongs to: the task of its row, else its own task key */
const returnSlug = (r, taskOf) => taskOf.get(r.key) ?? (String(r.key ?? '').startsWith('task:') ? r.key.slice(5) : null)

/** The workflow runs whose result waits on you (sessions state `runs`, bound to a task by the server and not
 *  marked checked), as results of the files queue: {key: wf:<id>, kind: 'run', slug, title, at_ms, result, run} */
export function runResults(runs) {
  return (runs ?? []).filter(r => r?.task && !r.seen && RUN_RESULTS.includes(r.status))
    .map(r => ({ key: `wf:${r.id}`, kind: 'run', slug: r.task, title: r.name, at_ms: r.ended_ms ?? r.at_ms ?? null,
      result: { text: r.summary || r.answer || null }, run: r }))
}

/** The parts of the files view (queueOf scope 'dossier'): the tabs that ask about a task, the results that wait
 *  (the starts of model.returns where they stand now, then the finished workflow runs not yet checked), the open
 *  inbox items that name a task, and the task rows. A file opens only for a task doing or in review (a row
 *  without a status, of a backlog section or a task closed since, opens none). `files` are those rows in every
 *  section but the blocked, quiet or dropped ones (bucket resting, drop): a tab, a result or an item opens them
 *  wherever they stand, a task waiting on someone else too. `tasks` are those of what waits on you and of the
 *  work: they stand in the queue on their own. An item put off counts as not open */
export function dossierParts(tabs, model, nowMs, runs = []) {
  const sec = id => (model?.sections ?? []).find(x => x.id === id)?.rows ?? []
  const all = ['now', 'give', 'work', 'track', 'later'].flatMap(sec)
  const isFile = r => r.task && !r.inbox_id && FILE_STATES.includes(r.status) && !['resting', 'drop'].includes(r.bucket)
  const files = all.filter(isFile)
  const tasks = [...sec('now'), ...sec('work')].filter(isFile)
  const waiting = all.filter(r => r.inbox_id && r.task && r.inbox_state !== 'deferred')
  const taskOf = new Map(all.filter(r => r.task).map(r => [r.key, r.task]))
  const results = [...(model?.returns ?? []).filter(r => liveStage(r, tabs, nowMs) === 'result')
    .map(r => ({ ...r, slug: returnSlug(r, taskOf) })), ...runResults(runs)]
  const asking = (tabs ?? []).filter(t => !t.is_control && t.state === 'needs-you' && t.slug)
  return { asking, results, waiting, files, tasks }
}

/** The files the files view walks, and its keys n and p: the one queue in its files scope */
export function fileQueue(tabs, model, nowMs, runs = []) {
  return queueOf(dossierParts(tabs, model, nowMs, runs), { scope: 'dossier' })
}

// why an active task stands outside the queue, in the order the files view names them
export const LEFT_OUT = ['resting', 'drop', 'waiting', 'deferred', 'area', 'unpinned']

/** The active tasks and streams (doing or review) the files queue leaves out, by why: under the filters of Work
 *  of another area (area) or not pinned (unpinned), put off (deferred, the day it comes back as `until`, null for
 *  one put away until shown again), dropped by its bucket, resting by its bucket or a block, else waiting with nothing that asks about it
 *  (a row of a later section with no tab, result or open item). Read from the whole model, so the filter's own
 *  share shows; backlog tasks stand in no section and count nowhere here (with cockpit.files_scope all they stand on
 *  their chip behind the queue, fileShelves). `s` the state the view sees (areaScope),
 *  `queue` its files. {total, groups: [{reason, rows: [{slug, row, until}]}]}, in LEFT_OUT order, none empty */
export function queueLeftOut(s, queue) {
  const whole = s?.wholeModel ?? s?.model
  const inQueue = new Set((queue ?? []).map(x => x.slug))
  const area = s?.ui?.area || null
  const pins = s?.ui?.pinnedOnly ? new Set(s.home?.pins ?? []) : null
  const hidden = new Set((whole?.hidden ?? []).map(r => r.key))
  const by = Object.fromEntries(LEFT_OUT.map(k => [k, []]))
  const seen = new Set()
  for (const r of [...(whole?.sections ?? []).flatMap(x => x.rows ?? []), ...(whole?.hidden ?? [])]) {
    if (!r?.task || r.inbox_id || !FILE_STATES.includes(r.status) || seen.has(r.task)) continue
    seen.add(r.task)
    if (inQueue.has(r.task)) continue
    const why = area && !inProject(r, area) ? 'area' : pins && !pins.has(r.key) ? 'unpinned'
      : hidden.has(r.key) ? 'deferred' : r.bucket === 'drop' ? 'drop' : r.bucket === 'resting' || r.blocked_by ? 'resting' : 'waiting'
    by[why].push({ slug: r.task, row: r, until: why === 'deferred' ? r.hidden_until ?? null : null })
  }
  const groups = LEFT_OUT.filter(k => by[k].length).map(reason => ({ reason, rows: by[reason] }))
  return { total: groups.reduce((n, g) => n + g.rows.length, 0), groups }
}

// the chips of every file behind the queue (cockpit.files_scope all), in the order the view shows them
export const FILE_SHELVES = ['active', 'waiting', 'resting', 'backlog', 'all']

// how the shelves sort: by status, then priority, then the latest change first
const STATUS_RANK = { doing: 0, review: 1, backlog: 2 }
const PRIO_RANK = { P0: 0, P1: 1, P2: 2, P3: 3 }

/** Does the files view show every task and stream behind its queue? cockpit.files_scope all, and a server that
 *  sends the list (model.files); an older server or the default `active` keeps the view as it was */
export function filesAll(s) {
  return s?.work?.files_scope === 'all' && Array.isArray((s?.wholeModel ?? s?.model)?.files)
}

/** The file the server lists for a slug (model.files, across every area), or null */
export function fileOf(s, slug) {
  return ((s?.wholeModel ?? s?.model)?.files ?? []).find(f => f.slug === slug) ?? null
}

/** Why an active file stands beside the queue, as the chip on its cover, by the same rule as the line of what the
 *  queue leaves out (queueLeftOut): put off (deferred), dropped by its bucket, resting (its bucket, or blocked),
 *  else waiting with nothing that asks about it. Null for a file of the queue (`queued`: a tab, a result or an item
 *  asks about it, so no reason contradicts its place) and for a backlog file, whose status says it */
export function fileReason(f, queued = false) {
  if (!f || queued || f.status === 'backlog') return null
  if (f.deferred) return 'deferred'
  if (f.bucket === 'drop') return 'drop'
  if (f.bucket === 'resting' || f.blocked_by) return 'resting'
  return 'waiting'
}

/** The shelf a file stands on: backlog by its status, active for a file of the queue (`queued`), else waiting or
 *  resting (resting, dropped or put off) by its reason */
export function fileShelf(f, queued = false) {
  if (f?.status === 'backlog') return 'backlog'
  if (queued) return 'active'
  return fileReason(f) === 'waiting' ? 'waiting' : 'resting'
}

const byFile = (a, b) => (STATUS_RANK[a.status] ?? 3) - (STATUS_RANK[b.status] ?? 3)
  || (PRIO_RANK[a.priority] ?? 4) - (PRIO_RANK[b.priority] ?? 4)
  || String(b.updated ?? '').localeCompare(String(a.updated ?? '')) || a.slug.localeCompare(b.slug)

/** Every file behind the queue (model.files) under the area filter of Work, by shelf, each sorted by status,
 *  priority and last change. The shelves split by the queue the view walks (`queue`, its files): Active holds the
 *  files of the queue, Waiting and Resting the active ones it leaves out, so they count what the line of what the
 *  queue leaves out names. `elsewhere` how many the area filter leaves out. {lists: {shelf: [file]}, elsewhere} */
export function fileShelves(s, queue = []) {
  const every = (s?.wholeModel ?? s?.model)?.files ?? []
  const area = s?.ui?.area || null
  const queued = new Set((queue ?? []).map(x => x.slug))
  const files = every.filter(f => inProject(f, area)).sort(byFile)
  const lists = Object.fromEntries(FILE_SHELVES.map(k => [k, k === 'all' ? files
    : files.filter(f => fileShelf(f, queued.has(f.slug)) === k)]))
  return { lists, elsewhere: every.length - files.length }
}

/** The folder a file opens by: its stream or task folder */
export const fileFolder = f => `work/${f.kind === 'stream' ? 'streams' : 'tasks'}/${f.slug}`

/** What a file's Result drawer holds: the starts of the return channel for its task or its inbox items (each
 *  with where it stands now, `live`), the workflow runs bound to it, and how many of them wait on you (a start
 *  with its result, a finished run not yet checked) */
export function fileResults(slug, model, tabs, nowMs, runs = []) {
  const taskOf = new Map([...indexRows(model).values()].filter(r => r.task).map(r => [r.key, r.task]))
  const returns = (model?.returns ?? []).filter(r => returnSlug(r, taskOf) === slug).map(r => ({ ...r, live: liveStage(r, tabs, nowMs) }))
  const mine = (runs ?? []).filter(r => r?.task === slug)
  const waiting = returns.filter(r => r.live === 'result').length + runResults(mine).length
  return { returns, runs: mine, waiting }
}

/** The next step of a file, derived and never stored: the tab's question, the result to check, the oldest open
 *  inbox item of the task (the server's, with its date; the item that put the file in the queue where the server
 *  names none), else what STATUS.md names as next (model.py task_next); {what, from, since} or null when nothing
 *  names one. `since` is ms or an ISO date */
export function dossierStep(x) {
  if (x?.reason === 'tab') return { what: x.tab.name, from: 'tab', since: x.tab.since_ms ?? null }
  // a workflow run: its name, the view words it as a check of its result
  if (x?.reason === 'result' && x.result.kind === 'run') return { what: x.result.title, from: 'run', since: x.result.at_ms ?? null }
  if (x?.reason === 'result') return { what: x.result.result?.text || x.result.title, from: 'result', since: x.result.at_ms ?? null }
  const next = x?.row?.next
  // the queue meets a task's items in the order of the page, not by age: the server's oldest one names the step
  if (x?.reason === 'inbox' && (!next || next.from !== 'inbox')) {
    return { what: x.item.title, from: 'inbox', since: null }
  }
  return next?.what ? { what: next.what, from: next.from, since: next.since ?? null } : null
}

/** How many whole days lie between `since` (ms, an ISO date or date and time, read as local) and now; null
 *  for no date or one that does not read */
export function stepAge(since, nowMs) {
  if (since == null || since === '') return null
  const ms = typeof since === 'number' ? since : new Date(/^\d{4}-\d{2}-\d{2}$/.test(since) ? `${since}T00:00` : since).getTime()
  if (!Number.isFinite(ms)) return null
  const day = d => { const x = new Date(d); x.setHours(0, 0, 0, 0); return x.getTime() }
  return Math.max(0, Math.round((day(nowMs) - day(ms)) / 86400000))
}

/** "?words" in the command box is a search of the files (/api/find), never a code: the words ('' for a bare ?),
 *  null for anything else, so every code parses as it always has */
export function commandSearch(raw) {
  const text = String(raw ?? '').trim()
  return text.startsWith('?') ? text.slice(1).trim() : null
}

/** The facts of one file for its cover and its questions: what /api/task holds, the row (when the model has one)
 *  filling what the detail lacks. `path` is the file's folder, `kind` task, stream or done */
export function fileFacts(slug, data, row) {
  const f = data?.front ?? {}
  const kind = data?.kind ?? 'task'
  const path = typeof data?.path === 'string' ? data.path.replace(/\/STATUS\.md$/, '')
    : `work/${kind === 'stream' ? 'streams' : 'tasks'}/${slug}`
  return { slug, kind, path, title: row?.title ?? f.headline ?? slug, status: f.status ?? row?.status ?? null,
    priority: f.priority ?? row?.priority ?? null, type: f.type ?? row?.task_type ?? null, headline: f.headline ?? null,
    next: f.next ?? row?.next?.what ?? null }
}

const filesWords = lang => (TABLES[lang] ?? TABLES.en).dossier

/** What a question asked in a file carries along as data (actions.py ask `context`): where the file lies and its
 *  cover, and that the answer comes from that folder. Cut to CONTEXT_MAX, never refused */
export function fileContext(file, lang = 'en') {
  const d = filesWords(lang)
  const w = d.ctx
  const lines = [`${w.file}: ${file.slug} (${d.find.kind[file.kind] ?? file.kind})`, `${w.folder}: ${file.path}/`,
    file.title ? `${w.title}: ${file.title}` : null, file.status ? `${w.status}: ${file.status}` : null,
    file.priority ? `${w.priority}: ${file.priority}` : null,
    file.headline && file.headline !== file.title ? `${w.situation}: ${file.headline}` : null,
    file.next ? `${w.next}: ${file.next}` : null, w.read(file.path)].filter(Boolean)
  const out = lines.join('\n')
  return out.length <= CONTEXT_MAX ? out : out.slice(0, CONTEXT_MAX)
}

/** What a question about the search results carries along, with no file open: the found files best first, each
 *  with its first hits, as many as fit in CONTEXT_MAX and the count of those that did not; '' without results */
export function findContext(result, lang = 'en') {
  const groups = result?.groups ?? []
  if (!groups.length) return ''
  const d = filesWords(lang)
  let out = d.ctx.results(result.query ?? '')
  for (let i = 0; i < groups.length; i++) {
    const g = groups[i]
    const block = [`- ${g.slug ?? g.path} (${d.find.kind[g.kind] ?? g.kind}): ${g.title} [${g.path}]`,
      ...(g.hits ?? []).slice(0, 2).map(h => `  ${h.path}:${h.line}: ${h.text}`)].join('\n')
    const rest = Math.max(result.total ?? groups.length, groups.length) - i
    const tail = `\n${d.ctx.more(rest)}`
    if (out.length + 1 + block.length + tail.length > CONTEXT_MAX) return out + tail
    out += `\n${block}`
  }
  const left = (result.total ?? groups.length) - groups.length
  const tail = left > 0 ? `\n${d.ctx.more(left)}` : ''
  return out.length + tail.length <= CONTEXT_MAX ? out + tail : out
}

/** The step a suggestion names: the first line of the answer, without list marks, emphasis, quotes or a leading
 *  "Next step:" in either language; one line of at most 300 characters (actions.py STEP_MAX), null for none */
export function suggestedStep(answer) {
  const first = String(answer ?? '').split('\n').map(x => x.trim()).find(Boolean)
  if (!first) return null
  const labels = Object.values(TABLES).map(t => t.dossier.next.toLowerCase())
  let text = first.replace(/^(?:[-*>#•]+|\d+[.)])\s*/, '').replace(/\*\*|__|`/g, '').trim()
  const label = labels.find(l => text.toLowerCase().startsWith(`${l}:`))
  if (label) text = text.slice(label.length + 1).trim()
  text = text.replace(/^["'“„«]+|["'”“»]+$/g, '').replace(/\s+/g, ' ').trim()
  return text ? text.slice(0, 300) : null
}
