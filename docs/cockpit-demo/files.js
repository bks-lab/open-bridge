// SPDX-License-Identifier: MIT
// Pure helpers of the cockpit's files view: the queue of files, what a file's drawers hold, its next step,
// the search and what a question asked in a file carries along. No DOM, no network, no state. logic.js
// passes every name on, so a view may import it from either; the frontend test imports this file under node.
import { TABLES } from './text.js'
import { CONTEXT_MAX, indexRows, liveStage, queueOf } from './logic.js'
import { areaScope, inProject } from './areas.js'

/** The files the files view walks under the filters of Work (areaScope as on Work, whatever page is open):
 *  what Next and Previous, n and p and a found file see */
export function scopedFileQueue(s) {
  const v = areaScope({ ...s, ui: { ...s.ui, page: 'briefing' } })
  return fileQueue(v.tabs?.tabs ?? [], v.model, s.now || Date.now(), s.sessions?.runs)
}

/** Where a found file opens: at its place in the filtered queue, else beside the queue (a file of another area,
 *  a backlog task); a closed one always beside it, by its folder, since a slug can be open and closed at once */
export function fileOpen(s, slug, path) {
  const closed = typeof path === 'string' && path.startsWith('work/done/')
  const queue = closed ? [] : scopedFileQueue(s)
  const i = queue.findIndex(x => x.slug === slug)
  return i >= 0 ? { dossierAt: { id: queue[i].id, i }, dossierOpen: null } : { dossierOpen: closed ? path : slug }
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
 *  one put away until shown again), resting or dropped by its bucket, else waiting with nothing that asks about it
 *  (a row of a later section with no tab, result or open item). Read from the whole model, so the filter's own
 *  share shows; backlog tasks never reach the model and count nowhere. `s` the state the view sees (areaScope),
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
      : hidden.has(r.key) ? 'deferred' : r.bucket === 'resting' ? 'resting' : r.bucket === 'drop' ? 'drop' : 'waiting'
    by[why].push({ slug: r.task, row: r, until: why === 'deferred' ? r.hidden_until ?? null : null })
  }
  const groups = LEFT_OUT.filter(k => by[k].length).map(reason => ({ reason, rows: by[reason] }))
  return { total: groups.reduce((n, g) => n + g.rows.length, 0), groups }
}

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
