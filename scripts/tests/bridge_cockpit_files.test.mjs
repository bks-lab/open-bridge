// SPDX-License-Identifier: MIT
// Tests of the cockpit's files view (scripts/web/files.js and views/dossier.js), no npm dependencies.
//
//   node --test scripts/tests/bridge_cockpit_files.test.mjs
//
// The one queue of files, a file's next step and its drawers, the search, a question asked in a file and the
// suggestion, the workflow runs as results, and the files under the area filter. The pure helpers are imported
// as the frontend suite imports them, the views are mounted as the render suite mounts them.
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import test from 'node:test'
import assert from 'node:assert/strict'
import { cockpitState, loadCockpit, mount, recorder } from './cockpit_render.mjs'

const here = path.dirname(fileURLToPath(import.meta.url))
const WEB = path.join(here, '..', 'web')
const { html, views, text, logic } = await loadCockpit()
const loadedRooms = await loadCockpit()
const { logic: loadedLogic } = await loadCockpit()
const api = await import(pathToFileURL(path.join(WEB, 'api.js')).href)
const en = text.TABLES.en
const { Header } = views.header

const read = rel => fs.readFileSync(path.join(WEB, rel), 'utf8')
const boxValue = box => box.value ?? box.getAttribute('value') ?? ''
const tick = () => new Promise(resolve => setTimeout(resolve, 20))

// a fixed local "now": Friday, 9 October 2026, noon (the same moment the other suites use)
const NOW = new Date(2026, 9, 9, 12, 0, 0).getTime()
const MIN = 60000

/** One start in the return channel, in the shape the server sends (model.returns) */
function start(over = {}) {
  return { key: 'inbox:20261009-0910-tidy-labels-c3d4', item: '20261009-0910-tidy-labels-c3d4', mode: 'go',
    title: 'Tidy the issue labels on the demo board', at_ms: NOW - 12 * MIN, stage: 'working', tab: { ref: 'surface:10' }, ...over }
}

function renderHeader(scratch, over = {}) {
  const s = cockpitState(NOW, { boot: { status: 'ok', error: null, version: '0.1.0', config: {}, scratch }, ...over })
  return mount(html`<${Header} s=${s} c=${recorder()} />`)
}

// ---------------------------------------------------------------- files: the pure helpers (from the frontend suite)

test('files and the area filter: a found file opens where the filtered queue holds it, else beside it; the place survives a filter only when it fits', async () => {
  const logic = await import(pathToFileURL(path.join(WEB, 'logic.js')).href)
  const row = (task, area, extra = {}) => ({ key: `task:${task}`, task, status: 'doing', bucket: 'act', area, area_names: [area], title: task, ...extra })
  const model = { sections: [{ id: 'now', rows: [] }, { id: 'work', rows: [row('a', 'ACME'), row('b', 'ORBIT'), row('c', 'ACME')] }] }
  // a tab that asks about an ACME task from a workspace named otherwise stays with the area's files
  const tabs = [{ ref: 't', workspace: 'scratch', state: 'needs-you', slug: 'c' }, { ref: 'u', workspace: 'ORBIT', state: 'needs-you', slug: 'b' }]
  const s = { model, tabs: { tabs }, now: 0, more: {}, home: { pins: [] }, ui: { page: 'briefing', area: 'ACME', picked: [], dossierAt: null } }
  assert.deepEqual(logic.areaScope(s).tabs.tabs.map(t => t.ref), ['t'])
  assert.deepEqual(logic.areaScope({ ...s, ui: { ...s.ui, page: '@chat' } }).tabs.tabs.map(t => t.ref), ['t'])
  const queue = logic.scopedFileQueue(s)
  assert.deepEqual(queue.map(x => x.slug), ['c', 'a'])
  // a hit of the area opens in the queue at its place there; one of another area beside the queue
  assert.deepEqual(logic.fileOpen(s, 'a', 'work/tasks/a'), { dossierAt: { id: queue[1].id, i: 1 }, dossierOpen: null })
  assert.deepEqual(logic.fileOpen(s, 'b', 'work/tasks/b'), { dossierOpen: 'b' })
  assert.deepEqual(logic.fileOpen(s, 'x', 'work/done/2026-10/x'), { dossierOpen: 'work/done/2026-10/x' })
  // a new filter keeps the place of a file that stands in it, else the walk starts at its first file
  const at = { id: queue[1].id, i: 1 }
  assert.deepEqual(logic.scopeKeep({ ...s, ui: { ...s.ui, dossierAt: at } }).dossierAt, at)
  assert.equal(logic.scopeKeep({ ...s, ui: { ...s.ui, area: 'ORBIT', dossierAt: at } }).dossierAt, null)
  assert.equal(logic.scopeKeep({ ...s, ui: { ...s.ui, dossierAt: null } }).dossierAt, null)
})

test('a click on a task outside the files view shows it: an open one in the item drawer, a closed one in the files view', async () => {
  const logic = await import(pathToFileURL(path.join(WEB, 'logic.js')).href)
  const row = task => ({ key: `task:${task}`, task, status: 'doing', bucket: 'act', title: task })
  const model = { sections: [{ id: 'now', rows: [] }, { id: 'work', rows: [row('a'), row('b')] }] }
  const work = { flow: { enabled: true }, views: null }
  const at = ui => ({ model, tabs: { tabs: [] }, now: 0, more: {}, home: { pins: [] }, work,
    ui: { area: null, picked: [], dossierAt: null, drawer: null, ...ui } })
  // Work through, the start page, a card in the item drawer over the files: the drawer opens over the page, which stays
  for (const ui of [{ page: 'briefing', workView: 'flow' }, { page: '@start' }, { page: 'briefing', workView: 'dossier', drawer: 'item' }]) {
    assert.deepEqual(logic.fileClick(at(ui), 'a', null), { item: 'task:a' }, JSON.stringify(ui))
  }
  // in the files view with nothing over it the file opens there, at its place in the queue (fileOpen)
  const files = at({ page: 'briefing', workView: 'dossier' })
  assert.deepEqual(logic.fileClick(files, 'b', null), { ui: logic.fileOpen(files, 'b', null) })
  // a closed copy: the files view reads it by its folder, so the click opens Work there, for this visit
  const closed = 'work/done/2026-10/x'
  assert.deepEqual(logic.fileClick(at({ page: 'briefing', workView: 'flow' }), 'x', closed),
    { ui: { workView: 'dossier', drawer: null, item: null, dossierOpen: closed }, page: 'briefing' })
  // where cockpit.work_views keeps no files view, the drawer takes the closed one too
  assert.deepEqual(logic.fileClick({ ...at({ page: '@start' }), work: { ...work, views: ['flow'] } }, 'x', closed), { item: 'task:x' })
  // the controller goes that way: the drawer through openItem, else the files view and its page
  const open = read('app.js').match(/\n {2}openFile\(slug, path\) \{[\s\S]*?\n {2}\},/)[0]
  assert.match(open, /fileClick\(/)
  assert.match(open, /ctl\.openItem\(/)
  assert.match(open, /ctl\.setPage\(/)
})

// ---------------------------------------------------------------- the files view: one queue for every walk

test('one queue function: the focus scope keeps the start page queue as it was, P0 and P1 tasks only', () => {
  const tabs = [{ ref: 'ask', name: 'ask', state: 'needs-you' }, { ref: 'run', name: 'run', state: 'working' }]
  const model = { sections: [
    { id: 'now', rows: [{ key: 'n1', title: 'Answer' }] },
    { id: 'work', rows: [{ key: 't0', title: 'Urgent', task: 'u', priority: 'P0', status: 'doing' },
      { key: 't1', title: 'Later', task: 'l', priority: 'P2', status: 'doing' }] },
  ] }
  const parts = logic.homeListParts(tabs, model, {})
  assert.deepEqual(logic.queueOf(parts, { scope: 'focus' }), logic.homeQueue(parts))
  assert.deepEqual(logic.queueOf(parts).map(x => x.id), ['ask', 'n1', 't0'], 'focus is the default scope')
})

const fileTask = (slug, priority, extra = {}) => ({ key: `task:${slug}`, title: `Task ${slug}`, task: slug, priority, status: 'doing', ...extra })

test('the files queue: a tab that asks, a result that waits, an inbox item, then doing and review tasks of every priority', () => {
  const model = {
    sections: [
      { id: 'now', rows: [{ key: 'inbox:1', title: 'Answer the vendor', inbox_id: '1', task: 'gamma' }, { key: 'inbox:9', title: 'Loose', inbox_id: '9' }] },
      { id: 'give', rows: [] },
      { id: 'work', rows: [fileTask('alpha', 'P0'), fileTask('beta', 'P2'), fileTask('gamma', 'P3', { status: 'review' }),
        fileTask('delta', 'P1'), fileTask('parked', 'P1', { status: 'backlog' })] },
      { id: 'later', rows: [fileTask('resting', 'P0', { bucket: 'resting' }), { key: 'inbox:2', title: 'x', inbox_id: '2', task: 'resting' }] },
    ],
    returns: [{ key: 'task:beta', item: 'beta', stage: 'result', at_ms: 1 }, { key: 'task:alpha', item: 'alpha', stage: 'working', at_ms: 1 }],
  }
  const tabs = [{ ref: 's:1', state: 'needs-you', slug: 'delta' }, { ref: 's:2', state: 'needs-you' },
    { ref: 's:3', state: 'needs-you', slug: 'resting' }, { ref: 's:4', state: 'needs-you', slug: 'alpha', is_control: true }]
  const q = logic.queueOf(logic.dossierParts(tabs, model, 10), { scope: 'dossier' })
  assert.deepEqual(q.map(x => [x.slug, x.reason]), [['delta', 'tab'], ['beta', 'result'], ['gamma', 'inbox'], ['alpha', 'task']])
  assert.deepEqual(q.map(x => x.id), ['task:delta', 'task:beta', 'task:gamma', 'task:alpha'], 'one entry per file, by its task key')
  assert.equal(q[0].tab.ref, 's:1')
  assert.equal(q[1].result.key, 'task:beta')
  assert.equal(q[2].item.key, 'inbox:1')
  assert.equal(q[3].row.key, 'task:alpha')
  // backlog, blocked and resting files stay out, and so does what has no file (a loose inbox item, a tab without a task)
  assert.ok(!q.some(x => ['parked', 'resting'].includes(x.slug)))
  assert.deepEqual(logic.queueOf(logic.dossierParts([], {}, 10), { scope: 'dossier' }), [])
})

test('acceptance: a P2 task in status doing stands in the files queue, the focus keeps leaving it out', () => {
  const model = { sections: [{ id: 'now', rows: [] }, { id: 'work', rows: [fileTask('invoice-onboarding', 'P2')] }] }
  const files = logic.queueOf(logic.dossierParts([], model, 0), { scope: 'dossier' })
  assert.deepEqual(files.map(x => x.slug), ['invoice-onboarding'])
  assert.deepEqual(logic.queueOf(logic.homeListParts([], model, {}), { scope: 'focus' }), [])
})

test('the files queue opens a file only for a task doing or in review: a row without a status opens none', () => {
  // a profile section of backlog tasks, or a briefing that names a task closed since: the row has no status
  const model = { sections: [
    { id: 'now', rows: [fileTask('unknown', 'P1', { status: null }), { key: 'inbox:1', title: 'x', inbox_id: '1', task: 'unknown' }] },
    { id: 'work', rows: [fileTask('closed', 'P0', { status: undefined }), fileTask('open', 'P3')] },
  ] }
  const tabs = [{ ref: 's:1', state: 'needs-you', slug: 'closed' }]
  assert.deepEqual(logic.queueOf(logic.dossierParts(tabs, model, 0), { scope: 'dossier' }).map(x => x.slug), ['open'])
})

test('a tab, a result or an inbox item opens the file of a doing task wherever its row stands, never a resting one', () => {
  // a doing task that waits on someone else stands in later; a tab that asks about it still leads the queue
  const model = { sections: [
    { id: 'now', rows: [{ key: 'inbox:1', title: 'Answer', inbox_id: '1', task: 'hidden' }] },
    { id: 'work', rows: [fileTask('own', 'P2')] },
    { id: 'later', rows: [fileTask('other', 'P2', { bucket: 'waiting' }), fileTask('stuck', 'P1', { bucket: 'resting' }),
      fileTask('hidden', 'P2', { bucket: 'waiting' }), fileTask('quiet', 'P2', { bucket: 'waiting' })] },
  ] }
  const tabs = [{ ref: 's:1', state: 'needs-you', slug: 'other' }, { ref: 's:2', state: 'needs-you', slug: 'stuck' }]
  const q = logic.queueOf(logic.dossierParts(tabs, model, 0), { scope: 'dossier' })
  assert.deepEqual(q.map(x => [x.slug, x.reason]), [['other', 'tab'], ['hidden', 'inbox'], ['own', 'task']])
  assert.equal(q[0].row.key, 'task:other')
})

test('a file is its task row, not a board item that names the same task', () => {
  const board = { key: 'gh:1', title: 'Board item of x', task: 'x', status: 'doing', priority: 'P1' }
  const model = { sections: [{ id: 'work', rows: [fileTask('x', 'P1'), board] }] }
  const q = logic.queueOf(logic.dossierParts([], model, 0), { scope: 'dossier' })
  assert.deepEqual(q.map(x => [x.slug, x.id, x.row.title]), [['x', 'task:x', 'Task x']])
  // the board item alone still opens the file of its task
  const only = logic.queueOf(logic.dossierParts([], { sections: [{ id: 'work', rows: [board] }] }, 0), { scope: 'dossier' })
  assert.deepEqual(only.map(x => [x.slug, x.id]), [['x', 'gh:1']])
})

test('n and p walk the files view the way its bar does, the one files queue', () => {
  const app = read('app.js')
  const body = app.match(/\/\/ n \/ p in the files view[\s\S]*?\n  \}/)[0]
  assert.match(body, /workViewIn\(s\) === 'dossier'/)
  assert.match(body, /scopedFileQueue\(s\)/)
  assert.match(body, /focusIndex\(queue, s\.ui\.dossierAt\) \+ \(key === 'n' \? 1 : -1\)/)
  assert.match(body, /ctl\.dossierWalk\(queue\[to\]\.id, to\)/)
})

test('the next step of a file says where it comes from and since when', () => {
  const row = fileTask('alpha', 'P2', { next: { what: 'Merge it', from: 'status', since: '2026-10-07', key: null } })
  assert.deepEqual(logic.dossierStep({ reason: 'task', row }), { what: 'Merge it', from: 'status', since: '2026-10-07' })
  assert.deepEqual(logic.dossierStep({ reason: 'tab', row, tab: { name: 'alpha tab', since_ms: 5 } }), { what: 'alpha tab', from: 'tab', since: 5 })
  assert.deepEqual(logic.dossierStep({ reason: 'result', row, result: { title: 'Run', at_ms: 7, result: { text: 'All green' } } }),
    { what: 'All green', from: 'result', since: 7 })
  // an inbox item: the server's oldest item with its date where it names one, else the item itself
  const inboxNext = { what: 'Answer', from: 'inbox', since: '2026-10-08T09:00', key: 'inbox:1' }
  assert.deepEqual(logic.dossierStep({ reason: 'inbox', row: { ...row, next: inboxNext }, item: { key: 'inbox:1', title: 'Answer' } }),
    { what: 'Answer', from: 'inbox', since: '2026-10-08T09:00' })
  assert.deepEqual(logic.dossierStep({ reason: 'inbox', row, item: { key: 'inbox:3', title: 'Other' } }), { what: 'Other', from: 'inbox', since: null })
  // the queue met a younger item of the task first: the step is still the oldest one, with its date
  assert.deepEqual(logic.dossierStep({ reason: 'inbox', row: { ...row, next: inboxNext }, item: { key: 'inbox:3', title: 'Younger' } }),
    { what: 'Answer', from: 'inbox', since: '2026-10-08T09:00' })
  // nothing names a next step: none is made up
  assert.equal(logic.dossierStep({ reason: 'task', row: fileTask('beta', 'P3') }), null)
})

test('the age of a step in whole days, from a date, a date and time, or milliseconds', () => {
  const now = new Date(2026, 9, 9, 12, 0, 0).getTime()
  assert.equal(logic.stepAge('2026-10-07', now), 2)
  assert.equal(logic.stepAge('2026-10-09T09:00', now), 0)
  assert.equal(logic.stepAge(now - 3 * 86400000, now), 3)
  assert.equal(logic.stepAge(null, now), null)
  assert.equal(logic.stepAge('not a date', now), null)
})

test('the work tab offers the files view beside the others, never as its default', () => {
  const work = { id: 'work', group: 'work', jev: true }
  const ready = { enabled: true, ready: true }
  assert.deepEqual(logic.workViews(work, ready), ['due', 'area', 'jev', 'dossier'])
  assert.deepEqual(logic.workViews(null, ready), ['due', 'dossier'])
  assert.equal(logic.workViewOf('dossier', null, ready), 'dossier')
  assert.equal(logic.workViewOf(undefined, work, ready), 'due')
})

// ---------------------------------------------------------------- the files view: find, ask a file, next step (E2)

test('files: ?words in the command box is a search, everything else stays a code', () => {
  assert.equal(logic.commandSearch('?gateway september'), 'gateway september')
  assert.equal(logic.commandSearch('  ?  invoice  '), 'invoice')
  assert.equal(logic.commandSearch('?'), '')
  for (const code of ['1a 3b', '2a', 'gateway', '', null]) assert.equal(logic.commandSearch(code), null)
  // a code still parses as before
  assert.ok(logic.parseShortcut('1a 3b'))
})

test('files: the api searches with the words in the query string, encoded', async () => {
  const got = []
  const a = api.createApi({ get: async p => { got.push(p); return { ok: true } }, post: async () => ({ ok: true }), events: () => ({}) })
  await a.find('a&b=c ?x')
  // a closed copy of a slug by its folder
  await a.task('weekly-report', 'work/done/2026-09/weekly-report')
  await a.task('weekly-report')
  assert.deepEqual(got, ['/api/find?q=a%26b%3Dc%20%3Fx', '/api/task?slug=weekly-report&path=work%2Fdone%2F2026-09%2Fweekly-report',
    '/api/task?slug=weekly-report'])
})

test('files: the facts of a file come from its task detail, the row filling what the detail lacks', () => {
  const data = { kind: 'done', path: 'work/done/2026-09/invoice-onboarding/STATUS.md',
    front: { status: 'done', priority: 'P2', type: 'admin', headline: 'Onboard the invoice vendor', next: null } }
  const f = logic.fileFacts('invoice-onboarding', data, null)
  assert.deepEqual(f, { slug: 'invoice-onboarding', kind: 'done', path: 'work/done/2026-09/invoice-onboarding', title: 'Onboard the invoice vendor',
    status: 'done', priority: 'P2', type: 'admin', headline: 'Onboard the invoice vendor', next: null })
  const row = { title: 'Row title', status: 'doing', priority: 'P1', task_type: 'feature', next: { what: 'Call the vendor' } }
  const g = logic.fileFacts('x', null, row)
  assert.equal(g.title, 'Row title')
  assert.equal(g.next, 'Call the vendor')
  assert.equal(g.kind, 'task')
  assert.equal(g.path, 'work/tasks/x')
})

test('files: a question in a file carries where it lies and its cover as data, in the page language', () => {
  const f = { slug: 'invoice-onboarding', kind: 'task', path: 'work/tasks/invoice-onboarding', title: 'Onboard the invoice vendor',
    status: 'doing', priority: 'P2', type: 'admin', headline: 'Onboard the invoice vendor', next: 'Call the vendor' }
  const en = logic.fileContext(f, 'en')
  for (const part of ['invoice-onboarding', 'work/tasks/invoice-onboarding/', 'doing', 'P2', 'Call the vendor']) assert.ok(en.includes(part), part)
  assert.ok(en.includes(text.TABLES.en.dossier.ctx.read('work/tasks/invoice-onboarding')))
  assert.ok(logic.fileContext(f, 'de').includes(text.TABLES.de.dossier.ctx.next))
  assert.ok(en.length <= logic.CONTEXT_MAX)
  // a very long cover is cut to what the server takes, never refused
  assert.ok(logic.fileContext({ ...f, headline: 'x'.repeat(9000) }, 'en').length <= logic.CONTEXT_MAX)
})

test('files: a question about the results carries the list of found files, best first, within the limit', () => {
  const hit = (path, line) => ({ path, line, text: `gateway at ${line}` })
  const res = { query: 'gateway', total: 3, groups: [
    { slug: 'invoice-onboarding', kind: 'task', path: 'work/tasks/invoice-onboarding', title: 'Onboard', rank: 1, count: 2,
      hits: [hit('work/tasks/invoice-onboarding/STATUS.md', 3), hit('work/tasks/invoice-onboarding/notes.md', 1)] },
    { slug: null, kind: 'log', path: 'work/log.md', title: 'work/log.md', rank: 2, count: 1, hits: [hit('work/log.md', 9)] }] }
  const ctx = logic.findContext(res, 'en')
  assert.ok(ctx.startsWith(text.TABLES.en.dossier.ctx.results('gateway')))
  assert.ok(ctx.indexOf('invoice-onboarding') < ctx.indexOf('work/log.md'))
  assert.ok(ctx.includes('work/tasks/invoice-onboarding/STATUS.md:3: gateway at 3'))
  const many = { ...res, total: 400, groups: Array.from({ length: 400 }, (_, i) => ({ ...res.groups[0], slug: `file-${i}` })) }
  const cut = logic.findContext(many, 'en')
  assert.ok(cut.length <= logic.CONTEXT_MAX && cut.includes(text.TABLES.en.dossier.ctx.more(1).split('1')[0].trim()))
  assert.equal(logic.findContext(null, 'en'), '')
})

test('files: a suggested step is the first line of the answer, plain, one line, at most 300 characters', () => {
  assert.equal(logic.suggestedStep('\n\n- **Call the vendor** about the 422\nBecause ...'), 'Call the vendor about the 422')
  assert.equal(logic.suggestedStep('1. "Write the summary"'), 'Write the summary')
  assert.equal(logic.suggestedStep('Next step: Send the draft'), 'Send the draft')
  assert.equal(logic.suggestedStep('   '), null)
  assert.equal(logic.suggestedStep(null), null)
  assert.equal(logic.suggestedStep('y'.repeat(400)).length, 300)
})

test('files: the command box searches before it parses codes, and a suggestion stays out of the chat lists', () => {
  const app = read('app.js')
  const run = app.slice(app.indexOf('async runCommand(text)'))
  assert.ok(run.indexOf('commandSearch(text)') >= 0 && run.indexOf('commandSearch(text)') < run.indexOf('parseShortcut(text)'))
  // the search opens the files view for this visit only: the saved work view stays what it was
  const search = run.slice(0, run.indexOf('parseShortcut(text)'))
  assert.doesNotMatch(search, /setWorkView|save\(/)
  assert.match(search, /ctl\.openFiles\(\)/)   // which sets workView 'dossier' and saves nothing (test below)
  // an answer for words no longer asked is dropped; a suggestion asks in its own place; only a click writes it
  assert.match(app, /if \(store\.get\(\)\.find\?\.q !== words\) return/)
  assert.match(app, /place: 'suggest'/)
  assert.match(app, /act\('task_set_next', \{ key, text \}\)/)
  const convs = [{ id: 'a', place: 'core', running: true }, { id: 'b', place: 'suggest', running: true }, { id: 'c', running: true }]
  assert.deepEqual(logic.listedChats(convs, 24, Date.now()).map(x => x.id), ['c'])
  // nor does it make the chat tab spin or the ask button light up
  const header = read('views/header.js')
  assert.equal((header.match(/\(s\.quick\?\.convs \?\? \[\]\)\.some\(chatRunning\)/g) ?? []).length, 2)
  assert.doesNotMatch(header, /\(s\.quick\?\.convs \?\? \[\]\)\.some\(x => x\.running\)/)
})

// ---------------------------------------------------------------- the files view: workflow runs and results (E3)

test('a workflow run bound to a task: a finished one not yet checked waits as its result, a running or checked one does not', () => {
  const model = { sections: [{ id: 'work', rows: [fileTask('alpha', 'P2'), fileTask('beta', 'P3'), fileTask('gamma', 'P1'),
    fileTask('parked', 'P1', { status: 'backlog' })] }], returns: [] }
  const runs = [
    { id: 'wf_a', task: 'beta', name: 'plan-beta', status: 'completed', seen: false, ended_ms: 5, summary: 'Plan it' },
    { id: 'wf_b', task: 'gamma', name: 'g', status: 'running', seen: false, ended_ms: null },
    { id: 'wf_c', task: 'alpha', name: 'a', status: 'completed', seen: true, ended_ms: 4 },
    { id: 'wf_d', task: 'parked', name: 'p', status: 'completed', seen: false, ended_ms: 3 },
    { id: 'wf_e', task: 'alpha', name: 'k', status: 'killed', seen: false, ended_ms: 3 },
  ]
  const q = logic.fileQueue([], model, 10, runs)
  assert.deepEqual(q.map(x => [x.slug, x.reason]), [['beta', 'result'], ['alpha', 'task'], ['gamma', 'task']])
  assert.equal(q[0].result.key, 'wf:wf_a')
  assert.equal(q[0].result.kind, 'run')
  assert.deepEqual(logic.dossierStep(q[0]), { what: 'plan-beta', from: 'run', since: 5 })
  // a start's result still comes first: it is the person's own hand-over
  const both = logic.fileQueue([], { ...model, returns: [{ key: 'task:alpha', item: 'alpha', stage: 'result', at_ms: 1 }] }, 10, runs)
  assert.deepEqual(both.map(x => [x.slug, x.reason]).slice(0, 2), [['alpha', 'result'], ['beta', 'result']])
  // without runs the queue is as before
  assert.deepEqual(logic.fileQueue([], model, 10).map(x => x.reason), ['task', 'task', 'task'])
})

test('the results of a file: the starts of its task and of its inbox items, and its workflow runs', () => {
  const model = {
    sections: [{ id: 'now', rows: [{ key: 'inbox:1', inbox_id: '1', task: 'alpha', title: 'x' }] }, { id: 'work', rows: [fileTask('alpha', 'P2')] }],
    returns: [{ key: 'task:alpha', item: 'alpha', stage: 'result', at_ms: 1, title: 'A' }, { key: 'inbox:1', item: '1', stage: 'done', at_ms: 2 },
      { key: 'task:beta', item: 'beta', stage: 'result', at_ms: 1 }],
  }
  const runs = [{ id: 'wf_a', task: 'alpha', status: 'completed', seen: false }, { id: 'wf_b', task: 'beta', status: 'completed', seen: false },
    { id: 'wf_c', task: 'alpha', status: 'running', seen: false }]
  const r = logic.fileResults('alpha', model, [], 10, runs)
  assert.deepEqual(r.returns.map(x => [x.key, x.live]), [['task:alpha', 'result'], ['inbox:1', 'done']])
  assert.deepEqual(r.runs.map(x => x.id), ['wf_a', 'wf_c'])
  assert.equal(r.waiting, 2, 'a result and a finished run not yet checked')
  assert.deepEqual(logic.fileResults('none', model, [], 10, runs), { returns: [], runs: [], waiting: 0 })
})

test('every walk of the files view reads the workflow runs of the sessions state', () => {
  // the walk of the keys and a found file read the queue the view shows (scopedFileQueue): a finished run
  // not yet checked lifts its file up there as in the view
  const row = task => ({ key: `task:${task}`, task, status: 'doing', bucket: 'act', title: task })
  const st = { model: { sections: [{ id: 'work', rows: [row('a'), row('b')] }] }, tabs: { tabs: [] }, now: 0, ui: { page: 'briefing' } }
  assert.deepEqual(logic.scopedFileQueue(st).map(x => x.slug), ['a', 'b'])
  const runs = [{ id: 'r', name: 'check', task: 'b', status: 'completed', seen: false, ended_ms: 1 }]
  assert.deepEqual(logic.scopedFileQueue({ ...st, sessions: { runs } }).map(x => x.slug), ['b', 'a'])
  assert.match(read('views/dossier.js'), /fileQueue\(s\.tabs\?\.tabs \?\? \[\], s\.model, s\.now \|\| Date\.now\(\), s\.sessions\?\.runs\)/)
  assert.match(read('api.js'), /file=\$\{encodeURIComponent\(file\)\}/)
})

// ---------------------------------------------------------------- files: what the views show (from the render suite)

// ---------------------------------------------------------------- the files view: one file large, the next ones after it

const filesOn = (over = {}) => cockpitState(NOW, { ...over, ui: { page: 'briefing', workView: 'dossier', ...(over.ui ?? {}) } })

test('the files view shows one file as one surface: its head, its next step with the four verbs, its walk at its foot', async () => {
  const { DossierView, dossierQueue } = views.dossier
  const s = filesOn()
  const queue = dossierQueue(s)
  assert.ok(queue.length > 2, 'the demo has files in the queue')
  // a P2 task in status doing stands in it (the focus on the start page leaves it out)
  assert.ok(queue.some(x => x.row.priority === 'P2' && x.row.status === 'doing'))
  const c = recorder()
  const el = mount(html`<${DossierView} s=${s} c=${c} />`)
  const cover = el.$('.dz-cover')
  assert.ok(cover, 'a cover')
  assert.match(cover.text(), new RegExp(queue[0].slug))
  assert.ok(cover.text().includes(en.taskState[queue[0].row.status]), 'the status in words')
  assert.ok(el.$('.fx-hero'), 'the next step in the hero of the start page focus')
  // one surface: the head, the step, the drawers and the walk all stand in the file, nothing walks over it
  const file = el.$('article.dz-file')
  assert.ok(file.$('.dz-cover') && file.$('.fx-hero') && file.$('.dz-foot .dz-walk'), 'all inside the one surface')
  assert.ok(file.$('.dz-eyebrow').text().includes(en.nextPos(1, queue.length)), 'where it stands, in the eyebrow')
  assert.equal(el.$$('.dz-title').length, 1, 'one title')
  assert.equal(el.$('.next-up'), null, 'not the floating bar of the lists')
  assert.equal(el.$('.fx-after'), null, 'no strip of cards after it')
  assert.doesNotMatch(file.$('.fx-hero').getAttribute('class'), /has-more/, 'no stacked edges under the step')
  // Previous and Next as buttons with words; the first file has no previous one
  const walk = el.$('.dz-walk')
  assert.ok(walk.button(en.dossier.walk.prev).hasAttribute('disabled'))
  walk.button(en.dossier.walk.next).click()
  assert.deepEqual(c.calls.filter(x => x[0] === 'dossierWalk'), [['dossierWalk', queue[1].id, 1]])
  // the position opens the whole queue, a click walks to one
  assert.equal(el.$('.dz-queue'), null, 'folded until asked')
  el.$('.dz-pos').click()
  await tick()
  const items = el.$$('.dz-queue-item')
  assert.equal(items.length, queue.length)
  assert.equal(items[0].getAttribute('aria-current'), 'true')
  items[3].click()
  assert.deepEqual(c.calls.filter(x => x[0] === 'dossierWalk').at(-1), ['dossierWalk', queue[3].id, 3])
  // the view switch stands on top, the files view on
  const on = el.$$('.work-switch button').find(b => b.getAttribute('aria-checked') === 'true')
  assert.equal(on.text(), en.workOrder.views.dossier)
})

test('a file whose next step comes from STATUS.md says so, with its age, and the verbs act on the task', () => {
  const { DossierView, dossierQueue } = views.dossier
  const base = filesOn()
  const queue = dossierQueue(base)
  const k = queue.findIndex(x => x.reason === 'task' && x.row.next?.from === 'status')
  assert.ok(k >= 0, 'the demo has a task with a next step in its STATUS.md')
  const x = queue[k]
  const el = mount(html`<${DossierView} s=${filesOn({ ui: { dossierAt: { id: x.id, i: k } } })} c=${recorder()} />`)
  const hero = el.$('.fx-hero')
  assert.equal(hero.$('.fx-title').text().trim(), x.row.next.what)
  assert.ok(hero.text().includes(en.dossier.from.status), 'where the step comes from')
  assert.ok(el.$('.fx-hero .fx-do'), 'the verbs of the row')
})

test('a file a tab asks about keeps the verbs of its task, the tab named beside them', () => {
  const { DossierView, dossierQueue } = views.dossier
  const s = filesOn()
  const queue = dossierQueue(s)
  assert.equal(queue[0].reason, 'tab', 'the demo has a tab that asks about a task')
  const el = mount(html`<${DossierView} s=${s} c=${recorder()} />`)
  const acts = el.$('.fx-hero .fx-do')
  assert.ok(acts.text().includes(en.settle), 'the close door of the row')
  assert.ok(!acts.text().includes(en.home.view), 'not the bare tab buttons')
  assert.ok(el.$('.fx-hero .fx-meta').text().includes(queue[0].tab.name), 'the tab that asks, named')
})

test('a file without a known next step says so instead of making one up', () => {
  const { DossierView, dossierQueue } = views.dossier
  const queue = dossierQueue(filesOn())
  const k = queue.findIndex(x => x.reason === 'task' && !x.row.next)
  assert.ok(k >= 0, 'the demo has a task without a next step')
  const el = mount(html`<${DossierView} s=${filesOn({ ui: { dossierAt: { id: queue[k].id, i: k } } })} c=${recorder()} />`)
  assert.equal(el.$('.fx-hero .fx-title').text().trim(), en.dossier.noNext)
})

test('the drawers of a file come folded, each with its count, from what the task detail holds', () => {
  const { DossierView, dossierQueue } = views.dossier
  const queue = dossierQueue(filesOn())
  const slug = queue[0].slug
  const data = { ok: true, slug, kind: 'task', path: `work/tasks/${slug}/STATUS.md`, front: { headline: 'Ship the release notes', last_updated: '2026-10-07' },
    sections: [{ heading: 'Goal', text: 'x', truncated: false }, { heading: 'Notes', text: 'y', truncated: false }],
    log: [{ at: '2026-10-08 09:00', glyph: 'x', context: slug, text: 'started' }],
    inbox: [{ id: '20261009-0900-x', summary: 'One item', state: 'open' }], related: ['docs/example.md'] }
  // nothing came back for it (no start, no workflow run): no Result drawer (E3 opens that one while it waits)
  const s = filesOn({ details: { inbox: {}, task: { [slug]: { status: 'ok', data, ver: 0 } } },
    model: { ...filesOn().model, returns: [] }, sessions: { ...filesOn().sessions, runs: [] } })
  const el = mount(html`<${DossierView} s=${s} c=${recorder()} />`)
  const drawers = el.$$('details.dz-drawer')
  assert.equal(drawers.length, 4)
  assert.ok(drawers.every(d => d.getAttribute('open') == null), 'folded')
  const heads = drawers.map(d => d.$('summary').text())
  assert.ok(heads[0].includes(en.dossier.drawers.inbox) && heads[0].includes('1'))
  assert.ok(heads.some(h => h.includes(en.dossier.drawers.sections) && h.includes('2')))
  assert.ok(heads.some(h => h.includes(en.dossier.drawers.refs)))
  // the situation in one sentence, with where it comes from and its date
  const sit = el.$('.dz-lead').text()
  assert.ok(sit.includes('Ship the release notes') && sit.includes(en.dossier.situationFrom.status))
})

test('with no file in the queue the files view rests calmly', () => {
  const { DossierView } = views.dossier
  const s = { ...filesOn(), ...cockpitState(NOW, { model: loadedRooms.mock.buildState(NOW, { empty: true }).model, ui: { page: 'briefing', workView: 'dossier' } }) }
  const el = mount(html`<${DossierView} s=${s} c=${recorder()} />`)
  assert.ok(el.$('.fx-calm'))
  assert.equal(el.$('.fx-calm .fx-title').text(), en.dossier.empty)
})

test('the files view names no key, also with the shortcuts switched on: the mouse walks it', () => {
  const { DossierView } = views.dossier
  const el = mount(html`<${DossierView} s=${filesOn({ ui: { shortcuts: true } })} c=${recorder()} />`)
  const said = [el.text(), ...el.$$('[title]').map(x => x.getAttribute('title')), ...el.$$('[aria-label]').map(x => x.getAttribute('aria-label'))].join(' ')
  assert.doesNotMatch(said, /\((n|p)\)|\bkeys?\b/i)
  assert.equal(el.$$('kbd').length, 0)
})

// ---------------------------------------------------------------- the files view: find, ask a file, next step (E2)

const FOUND = { ok: true, query: 'vendor export', words: ['vendor', 'export'], engine: 'rg', total: 3, truncated: false, groups: [
  { slug: 'demo-task', kind: 'task', path: 'work/tasks/demo-task', title: 'Demo task', rank: 0, count: 1,
    hits: [{ path: 'work/tasks/demo-task/STATUS.md', line: 4, text: 'the vendor export' }] },
  { slug: 'release-notes-2026-09', kind: 'done', path: 'work/done/2026-09/release-notes-2026-09', title: 'Release notes for September',
    rank: 2, count: 2, hits: [{ path: 'work/done/2026-09/release-notes-2026-09/notes.md', line: 1, text: 'vendor export timed out' }] },
  { slug: null, kind: 'log', path: 'work/log.md', title: 'work/log.md', rank: 2, count: 1,
    hits: [{ path: 'work/log.md', line: 9, text: 'vendor export again' }] }] }

/** A controller that records like recorder() and answers the methods a form awaits */
function answering() {
  const calls = []
  return new Proxy({}, { get: (_, p) => (p === 'calls' ? calls : p === 'then' || typeof p === 'symbol' ? undefined
    : (...a) => { calls.push([p, ...a]); return Promise.resolve(true) }) })
}

async function typeAndSend(el, selector, value) {
  const input = el.$(`${selector} input`)
  input.value = value
  input.dispatch('input')
  await tick()
  el.$(`form${selector}`).dispatch('submit')
  await tick()
}

test('the files view has a search field of its own; what is typed there is searched, never run as a code', async () => {
  const { DossierView } = views.dossier
  const c = answering()
  const el = mount(html`<${DossierView} s=${filesOn()} c=${c} />`)
  const form = el.$('form.dz-find')
  assert.ok(form && form.getAttribute('role') === 'search')
  assert.equal(el.$('form.dz-find input').getAttribute('placeholder'), en.dossier.find.placeholder)
  await typeAndSend(el, '.dz-find', '  2a vendor  ')
  assert.deepEqual(c.calls.filter(x => x[0] === 'findFiles'), [['findFiles', '2a vendor']])
  assert.equal(c.calls.filter(x => x[0] === 'act' || x[0] === 'runCommand').length, 0)
})

test('the results come by file, best first; a click opens a file, a closed one too; a log line has none to open', () => {
  const { DossierView } = views.dossier
  const c = recorder()
  const el = mount(html`<${DossierView} s=${filesOn({ find: { q: 'vendor export', status: 'ok', data: FOUND } })} c=${c} />`)
  const items = el.$$('.dz-found > li')
  assert.equal(items.length, 3)
  assert.ok(items[0].text().includes('demo-task') && items[0].text().includes(en.dossier.find.kind.task))
  assert.ok(items[1].text().includes(en.dossier.find.kind.done) && items[1].text().includes(en.dossier.find.hits(2)))
  assert.ok(items[1].text().includes('vendor export timed out'))
  items[1].$('button.dz-found-open').click()
  assert.deepEqual(c.calls.filter(x => x[0] === 'openFile'), [['openFile', 'release-notes-2026-09', 'work/done/2026-09/release-notes-2026-09']])
  assert.equal(items[2].$('button.dz-found-open'), null)
  assert.ok(items[2].text().includes('work/log.md'))
  el.button(en.dossier.find.clear).click()
  assert.ok(c.calls.some(x => x[0] === 'clearFind'))
})

test('a search that finds nothing or fails says so in words', () => {
  const { DossierView } = views.dossier
  const none = mount(html`<${DossierView} s=${filesOn({ find: { q: 'zzz', status: 'ok', data: { ...FOUND, query: 'zzz', total: 0, groups: [] } } })} c=${recorder()} />`)
  assert.ok(none.$('.dz-find-note').text().includes(en.dossier.find.none('zzz')))
  const bad = mount(html`<${DossierView} s=${filesOn({ find: { q: 'zzz', status: 'error', error: 'boom' } })} c=${recorder()} />`)
  assert.ok(bad.$('.dz-find-note').text().includes(en.dossier.find.failed('boom')))
})

test('without an open file a question about the results carries the result list, never a task', async () => {
  const { DossierView } = views.dossier
  const c = answering()
  const s = filesOn({ find: { q: 'vendor export', status: 'ok', data: FOUND } })
  const el = mount(html`<${DossierView} s=${s} c=${c} />`)
  await typeAndSend(el, '.dz-ask-results', 'which one failed?')
  const [call] = c.calls.filter(x => x[0] === 'askFile')
  assert.equal(call[1], 'which one failed?')
  assert.equal(call[2], logic_findContext(FOUND))
  assert.equal(call[3], null)
})

const logic_findContext = res => loadedRooms.logic.findContext(res, 'en')

test('a file opened from the search shows its cover from the task detail and leads back to the queue', async () => {
  const { DossierView } = views.dossier
  const slug = 'release-notes-2026-09'
  const data = { ok: true, slug, kind: 'done', path: `work/done/2026-09/${slug}/STATUS.md`,
    front: { status: 'done', priority: 'P2', type: 'admin', headline: 'Release notes for September', last_updated: '2026-09-30' },
    sections: [{ heading: 'Notes', text: 'x', truncated: false }], log: [], inbox: [], related: [] }
  const c = answering()
  const s = filesOn({ details: { inbox: {}, task: { [slug]: { status: 'ok', data, ver: 0 } } }, ui: { dossierOpen: slug } })
  const el = mount(html`<${DossierView} s=${s} c=${c} />`)
  assert.ok(el.$('.dz-eyebrow').text().includes(en.dossier.opened))
  assert.ok(el.$('.dz-cover').text().includes(slug) && el.$('.dz-cover').text().includes(en.dossier.find.kind.done))
  assert.equal(el.$('.fx-hero'), null, 'no verbs for a file outside the queue')
  // a closed file is asked about without naming its task: the chat would otherwise be archived at once
  await typeAndSend(el, '.dz-ask', 'what was the cause?')
  const [call] = c.calls.filter(x => x[0] === 'askFile')
  assert.equal(call[1], 'what was the cause?')
  assert.ok(call[2].includes(`work/done/2026-09/${slug}/`) && call[2].includes('Release notes for September'))
  assert.equal(call[3], null)
  el.button(en.dossier.back).click()
  assert.ok(c.calls.some(x => x[0] === 'closeFile'))
})

test('asking a file in the queue sends its folder and cover and names its task', async () => {
  const { DossierView, dossierQueue } = views.dossier
  const s = filesOn()
  const x = dossierQueue(s)[0]
  const c = answering()
  const el = mount(html`<${DossierView} s=${s} c=${c} />`)
  assert.equal(el.$('.dz-ask input').getAttribute('placeholder'), en.dossier.ask.placeholder)
  await typeAndSend(el, '.dz-ask', 'what blocks it?')
  const [call] = c.calls.filter(y => y[0] === 'askFile')
  assert.ok(call[2].includes(`work/tasks/${x.slug}/`) && call[2].includes(x.slug))
  assert.equal(call[3], x.slug)
})

test('a file without a next step offers a suggestion; the answer shows read only until it is taken over', () => {
  const { DossierView, dossierQueue } = views.dossier
  const queue = dossierQueue(filesOn())
  const k = queue.findIndex(y => y.reason === 'task' && !y.row.next)
  const x = queue[k]
  const at = { dossierAt: { id: x.id, i: k } }
  const c = recorder()
  let el = mount(html`<${DossierView} s=${filesOn({ ui: at })} c=${c} />`)
  el.button(en.dossier.suggest.button).click()
  const [call] = c.calls.filter(y => y[0] === 'suggestNext')
  assert.equal(call[1], x.slug)
  assert.ok(call[2].includes(`work/tasks/${x.slug}/`))
  // a file whose step is known offers none
  const known = queue.findIndex(y => y.reason === 'task' && y.row.next)
  const other = mount(html`<${DossierView} s=${filesOn({ ui: { dossierAt: { id: queue[known].id, i: known } } })} c=${recorder()} />`)
  assert.equal(other.button(en.dossier.suggest.button), null)
  // while it is asked
  const running = { quick: { convs: [{ id: 'q0000000001', running: true, turns: [{ q: 'x', a: null }] }] } }
  el = mount(html`<${DossierView} s=${filesOn({ ...running, ui: { ...at, suggest: { slug: x.slug, conv: 'q0000000001' } } })} c=${c} />`)
  assert.ok(el.$('.dz-suggest').text().includes(en.dossier.suggest.running))
  // the answer: its first line, with the way to take it over or let it go
  const answered = { quick: { convs: [{ id: 'q0000000001', running: false, turns: [{ q: 'x', a: '- **Call the vendor** today\nbecause it waits' }] }] } }
  const c2 = recorder()
  el = mount(html`<${DossierView} s=${filesOn({ ...answered, ui: { ...at, suggest: { slug: x.slug, conv: 'q0000000001' } } })} c=${c2} />`)
  const box = el.$('.dz-suggest')
  assert.ok(box.text().includes('Call the vendor today') && box.text().includes(en.dossier.suggest.note))
  assert.ok(!box.text().includes('because'))
  box.button(en.dossier.suggest.take).click()
  assert.deepEqual(c2.calls.filter(y => y[0] === 'takeNext'), [['takeNext', x.row.key, 'Call the vendor today']])
  box.button(en.dossier.suggest.dismiss).click()
  assert.ok(c2.calls.some(y => y[0] === 'dismissSuggest'))
})

// ---------------------------------------------------------------- the files view: review fixes of E2

test('files: the search field shows the words searched last, also when they came from the command box', async () => {
  const { DossierView } = views.dossier
  const field = el => boxValue(el.$('form.dz-find input'))
  const el = mount(html`<${DossierView} s=${filesOn({ find: { q: 'vendor export', status: 'ok', data: FOUND } })} c=${recorder()} />`)
  await tick()
  assert.equal(field(el), 'vendor export')
  // ?invoice in the command box while the view is open: the field follows
  loadedRooms.render(html`<${DossierView} s=${filesOn({ find: { q: 'invoice', status: 'loading', data: null } })} c=${recorder()} />`, el)
  await tick()
  assert.equal(field(el), 'invoice')
  // what is typed stays while the search stays the same
  const input = el.$('form.dz-find input')
  input.value = 'invoice vendor'
  input.dispatch('input')
  await tick()
  loadedRooms.render(html`<${DossierView} s=${filesOn({ find: { q: 'invoice', status: 'ok', data: FOUND } })} c=${recorder()} />`, el)
  await tick()
  assert.equal(field(el), 'invoice vendor')
})

test('files: a found closed file opens by its folder, so a slug open and closed are two files', () => {
  const { DossierView } = views.dossier
  const c = recorder()
  const el = mount(html`<${DossierView} s=${filesOn({ find: { q: 'vendor export', status: 'ok', data: FOUND } })} c=${c} />`)
  el.$$('.dz-found > li')[1].$('button.dz-found-open').click()
  el.$$('.dz-found > li')[0].$('button.dz-found-open').click()
  assert.deepEqual(c.calls.filter(x => x[0] === 'openFile'), [
    ['openFile', 'release-notes-2026-09', 'work/done/2026-09/release-notes-2026-09'],
    ['openFile', 'demo-task', FOUND.groups[0].path]])
})

test('files: with a file opened from the results they fold to their head and unfold on a click', async () => {
  const { DossierView } = views.dossier
  const slug = views.dossier.dossierQueue(filesOn()).find(x => x.reason === 'task').slug
  const el = mount(html`<${DossierView} s=${filesOn({ find: { q: 'vendor export', status: 'ok', data: FOUND }, ui: { dossierOpen: slug } })} c=${recorder()} />`)
  assert.ok(el.$('.dz-results-head').text().includes('vendor export'), 'the words stay named')
  assert.equal(el.$$('.dz-found > li').length, 0, 'folded')
  el.button(en.dossier.find.show).click()
  await tick()
  assert.equal(el.$$('.dz-found > li').length, 3)
  // with no file open they stand unfolded, with nothing to fold
  const plain = mount(html`<${DossierView} s=${filesOn({ find: { q: 'vendor export', status: 'ok', data: FOUND } })} c=${recorder()} />`)
  assert.equal(plain.$$('.dz-found > li').length, 3)
  assert.equal(plain.button(en.dossier.find.hide), null)
})

test('files: a closed copy opened by its folder reads that copy and borrows nothing from an open row of its slug', async () => {
  const { DossierView } = views.dossier
  const queue = views.dossier.dossierQueue(filesOn())
  const slug = queue.find(x => x.reason === 'task').slug
  const folder = `work/done/2026-08/${slug}`
  const data = { ok: true, slug, kind: 'done', path: `${folder}/STATUS.md`,
    front: { status: 'done', priority: 'P3', type: 'admin', headline: 'The August copy', last_updated: '2026-08-30' },
    sections: [], log: [], inbox: [], related: [] }
  const c = answering()
  const el = mount(html`<${DossierView} s=${filesOn({ details: { inbox: {}, task: { [folder]: { status: 'ok', data, ver: 0 } } }, ui: { dossierOpen: folder } })} c=${c} />`)
  const cover = el.$('.dz-cover').text()
  assert.ok(cover.includes(slug) && cover.includes('The August copy') && cover.includes(en.dossier.find.kind.done))
  assert.equal(el.button(en.dossier.suggest.button), null, 'no suggestion for a closed file')
  // not loaded yet: it asks for that folder
  const c2 = recorder()
  mount(html`<${DossierView} s=${filesOn({ ui: { dossierOpen: folder } })} c=${c2} />`)
  await tick()
  assert.ok(c2.calls.some(x => x[0] === 'loadTask' && x[1] === folder))
  assert.ok(!c2.calls.some(x => x[0] === 'loadTask' && x[1] === slug), 'never the open file of its slug in its place')
})

test('files: an open task found outside the queue without a next step offers the suggestion too', () => {
  const { DossierView, dossierQueue } = views.dossier
  const base = filesOn()
  const inQueue = new Set(dossierQueue(base).map(x => x.slug))
  const row = base.model.sections.flatMap(x => x.rows ?? []).find(r => r.key?.startsWith('task:') && !r.inbox_id && !r.next
    && !inQueue.has(r.key.slice(5)))
  assert.ok(row, 'the demo has an open task outside the queue without a next step')
  const slug = row.key.slice(5)
  const data = { ok: true, slug, kind: 'task', path: `work/tasks/${slug}/STATUS.md`, front: { status: 'backlog', headline: 'h' },
    sections: [], log: [], inbox: [], related: [] }
  const c = recorder()
  const el = mount(html`<${DossierView} s=${filesOn({ details: { inbox: {}, task: { [slug]: { status: 'ok', data, ver: 0 } } }, ui: { dossierOpen: slug } })} c=${c} />`)
  el.button(en.dossier.suggest.button).click()
  const [call] = c.calls.filter(x => x[0] === 'suggestNext')
  assert.equal(call[1], slug)
  assert.ok(call[2].includes(`work/tasks/${slug}/`))
})

test('files: a suggestion whose chat is gone or still running can always be let go', () => {
  const { DossierView, dossierQueue } = views.dossier
  const queue = dossierQueue(filesOn())
  const k = queue.findIndex(y => y.reason === 'task' && !y.row.next)
  const x = queue[k]
  const at = { dossierAt: { id: x.id, i: k }, suggest: { slug: x.slug, conv: 'q0000000009' } }
  // its chat left the list (archived, replaced): no endless "running"
  const c = recorder()
  let el = mount(html`<${DossierView} s=${filesOn({ quick: { convs: [] }, ui: at })} c=${c} />`)
  assert.ok(!el.$('.dz-suggest').text().includes(en.dossier.suggest.running))
  assert.ok(el.$('.dz-suggest').text().includes(en.dossier.suggest.failed))
  el.$('.dz-suggest').button(en.dossier.suggest.dismiss).click()
  assert.ok(c.calls.some(y => y[0] === 'dismissSuggest'))
  // while it runs
  const c2 = recorder()
  el = mount(html`<${DossierView} s=${filesOn({ quick: { convs: [{ id: 'q0000000009', running: true, turns: [{ q: 'x', a: null }] }] }, ui: at })} c=${c2} />`)
  assert.ok(el.$('.dz-suggest').text().includes(en.dossier.suggest.running))
  el.$('.dz-suggest').button(en.dossier.suggest.dismiss).click()
  assert.ok(c2.calls.some(y => y[0] === 'dismissSuggest'))
})

test('header: a running suggestion is no running chat, the start page core still is', () => {
  // the chat tab's spinner and the ask button read the same test (the page bar measures the window, so its own test)
  const { chatRunning } = views.header
  const convs = list => ({ quick: { convs: list } })
  assert.equal(chatRunning({ place: 'suggest', running: true }), false)
  assert.equal(chatRunning({ place: 'core', running: true }), true)
  assert.equal(chatRunning({ running: true }), true)
  assert.equal(chatRunning({ running: false }), false)
  assert.ok(!renderHeader(null, convs([{ id: 'a', place: 'suggest', running: true, turns: [] }])).$('.hdr-ask').hasClass('btn-primary'))
  assert.ok(renderHeader(null, convs([{ id: 'b', place: 'core', running: true, turns: [] }])).$('.hdr-ask').hasClass('btn-primary'))
})

// ---------------------------------------------------------------- the files view: results and the folder's files (E3)

/** A controller that records every call and answers the reading of a task's file */
function reading(text) {
  const calls = []
  return new Proxy({}, { get: (_, p) => (p === 'calls' ? calls : p === 'then' || typeof p === 'symbol' ? undefined
    : (...a) => { calls.push([p, ...a]); return p === 'taskFile' ? Promise.resolve({ ok: true, data: { ok: true, file: a[1], text, cut: false } }) : undefined }) })
}

function fileWithResult() {
  const base = filesOn()
  const slug = views.dossier.dossierQueue(base).find(x => x.reason === 'task').slug
  const runs = [{ id: 'wf_plan', task: slug, name: 'plan-run', status: 'completed', seen: false, since_ms: NOW - 600000,
    ended_ms: NOW - 60000, at_ms: NOW - 60000, agents: 4, summary: 'Plan the change', answer: 'Done: see notes.md', how: ['named'], sid: 'x' },
  { id: 'wf_old', task: slug, name: 'old-run', status: 'completed', seen: true, since_ms: NOW - 9e6, ended_ms: NOW - 8e6, at_ms: NOW - 8e6,
    agents: 2, summary: 'An earlier look', answer: null, how: ['session'], sid: 'y' }]
  const sessions = { ...(base.sessions ?? {}), runs }
  const queue = views.dossier.dossierQueue(filesOn({ sessions }))
  const k = queue.findIndex(x => x.slug === slug)
  const data = { ok: true, slug, kind: 'task', path: `work/tasks/${slug}/STATUS.md`, front: {}, sections: [], log: [], inbox: [], related: [],
    files: [{ path: 'notes.md', size: 10 }, { path: 'research/a.yaml', size: 5 }] }
  return { slug, queue, k, s: filesOn({ sessions, details: { inbox: {}, task: { [slug]: { status: 'ok', data, ver: 0 } } },
    ui: { dossierAt: { id: queue[k].id, i: k } } }) }
}

test('a file whose workflow result waits: its step says so, the Result drawer stands open with the run and Checked', () => {
  const { DossierView } = views.dossier
  const { queue, k, s } = fileWithResult()
  assert.equal(queue[k].reason, 'result', 'a finished run not yet checked puts its file in the result stage')
  const c = recorder()
  const el = mount(html`<${DossierView} s=${s} c=${c} />`)
  assert.equal(el.$('.fx-hero .fx-title').text().trim(), en.dossier.runStep('plan-run'))
  assert.ok(el.$('.fx-hero').text().includes(en.dossier.from.run))
  const result = el.$$('details.dz-drawer').find(d => d.$('summary').text().includes(en.dossier.drawers.result))
  assert.ok(result, 'a Result drawer')
  assert.ok(result.getAttribute('open') != null, 'open while a result waits')
  assert.ok(result.$('summary').text().includes('2'))
  const cards = result.$$('.dz-run')
  assert.equal(cards.length, 2)
  assert.ok(cards[0].text().includes('Plan the change') && cards[0].text().includes('Done: see notes.md'))
  assert.ok(cards[0].text().includes(en.dossier.run.how.named), 'why the run belongs to this file')
  assert.ok(cards[1].text().includes(en.dossier.run.checked), 'a checked run says so and offers nothing')
  assert.ok(!cards[1].$('button'))
  cards[0].button(en.dossier.run.check).click()
  assert.deepEqual(c.calls.filter(x => x[0] === 'act'), [['act', 'run_seen', { id: 'wf_plan' }]])
})

test('a failed workflow run waits as a result with a red mark; a running or stopped one waits for nothing', () => {
  const { DossierView } = views.dossier
  const { s, slug } = fileWithResult()
  const runs = [{ ...s.sessions.runs[0], id: 'wf_fail', status: 'failed', answer: null },
    { ...s.sessions.runs[0], id: 'wf_live', status: 'running', ended_ms: null },
    { ...s.sessions.runs[0], id: 'wf_stop', status: 'killed' }]
  assert.deepEqual(loadedLogic.runResults(runs).map(r => r.key), ['wf:wf_fail'])
  const failed = { ...s, sessions: { ...s.sessions, runs } }
  const queue = views.dossier.dossierQueue(failed)
  const k = queue.findIndex(x => x.slug === slug)
  assert.equal(queue[k].reason, 'result')
  const el = mount(html`<${DossierView} s=${{ ...failed, ui: { ...failed.ui, dossierAt: { id: queue[k].id, i: k } } }} c=${recorder()} />`)
  const cards = el.$$('.dz-run')
  const card = id => cards.find(x => x.text().includes(en.dossier.run.status[runs.find(r => r.id === id).status]))
  assert.ok(card('wf_fail').$('.dot.tk-danger'), 'a failed run is marked as a danger, a token the stylesheet knows')
  assert.ok(card('wf_fail').button(en.dossier.run.check), 'its result waits to be checked')
  assert.ok(card('wf_live').$('.dot.tk-info') && !card('wf_live').$('button'))
  assert.ok(!card('wf_stop').$('button'))
})

test('a file without a waiting result keeps its Result drawer folded; a file of only STATUS.md has no Files drawer', () => {
  const { DossierView } = views.dossier
  const { s, slug } = fileWithResult()
  const seen = { ...s, sessions: { ...s.sessions, runs: s.sessions.runs.map(r => ({ ...r, seen: true })) } }
  const queue = views.dossier.dossierQueue(seen)
  const k = queue.findIndex(x => x.slug === slug)
  const el = mount(html`<${DossierView} s=${{ ...seen, ui: { ...seen.ui, dossierAt: { id: queue[k].id, i: k } } }} c=${recorder()} />`)
  const result = el.$$('details.dz-drawer').find(d => d.$('summary').text().includes(en.dossier.drawers.result))
  assert.ok(result && result.getAttribute('open') == null)
  const bare = { ...seen, details: { inbox: {}, task: { [slug]: { ...seen.details.task[slug], data: { ...seen.details.task[slug].data, files: [] } } } },
    ui: { ...seen.ui, dossierAt: { id: queue[k].id, i: k } } }
  const none = mount(html`<${DossierView} s=${bare} c=${recorder()} />`)
  assert.ok(!none.$$('details.dz-drawer').some(d => d.$('summary').text().includes(en.dossier.drawers.files)))
})

test('the Files drawer lists the folder, a click reads the file in place as Markdown or as it stands', async () => {
  const { DossierView } = views.dossier
  const { s, slug } = fileWithResult()
  const c = reading('# Notes\n\nThe **vendor** answered.')
  const el = mount(html`<${DossierView} s=${s} c=${c} />`)
  const files = el.$$('details.dz-drawer').find(d => d.$('summary').text().includes(en.dossier.drawers.files))
  assert.ok(files && files.$('summary').text().includes('2'))
  assert.deepEqual(files.$$('.dz-file-open').map(b => b.text().trim()), ['notes.md', 'research/a.yaml'])
  files.button('notes.md').click()
  await tick()
  assert.deepEqual(c.calls.find(x => x[0] === 'taskFile'), ['taskFile', slug, 'notes.md', null])
  const shown = el.$('.dz-file-text')
  assert.ok(shown, 'the file is shown')
  assert.ok(shown.$('strong') && shown.text().includes('vendor'), 'Markdown drawn as prose')
  assert.ok(el.$('.dz-file-path').text().includes(`work/tasks/${slug}/notes.md`), 'with its path')
})

// ---------------------------------------------------------------- files and areas

test('files under an area filter: the queue, its count and its walk keep to the area', () => {
  const { DossierView, dossierQueue } = views.dossier
  const { logic } = loadedRooms
  const s = filesOn({ ui: { area: 'Ops' } })
  const all = dossierQueue(filesOn())
  const v = logic.areaScope(s)
  const queue = dossierQueue(v)
  assert.ok(all.length > queue.length && queue.length > 0)
  assert.ok(queue.every(x => logic.rowProject(x.row) === 'Ops'), queue.map(x => x.slug).join())
  const el = mount(html`<${DossierView} s=${v} c=${recorder()} />`)
  assert.ok(el.$('.dz-eyebrow').text().includes(en.nextPos(1, queue.length)))
})

test('files: a result and a workflow run of a task of another area put no file in the filtered queue', () => {
  const { dossierQueue } = views.dossier
  const { logic } = loadedRooms
  const base = filesOn()
  const docs = dossierQueue(base).find(x => logic.rowProject(x.row) === 'Docs')
  const ret = { key: docs.row.key, item: docs.slug, mode: 'go', title: 'answered', at_ms: NOW - 60000, stage: 'result', tab: null }
  const run = { id: 'run-1', name: 'check', task: docs.slug, status: 'completed', seen: false, ended_ms: NOW - 30000 }
  const s = { ...base, model: { ...base.model, returns: [...(base.model.returns ?? []), ret] }, sessions: { ...base.sessions, runs: [run] } }
  // without a filter they lift the Docs file up as a result that waits
  const whole = dossierQueue(s)
  assert.equal(whole.find(x => x.slug === docs.slug).reason, 'result')
  // under Ops neither brings it in
  const ops = dossierQueue(logic.areaScope({ ...s, ui: { ...s.ui, area: 'Ops' } }))
  assert.equal(ops.some(x => x.slug === docs.slug), false)
  assert.ok(ops.length > 0)
})

test('files: a file of another area opened from the search keeps its area chip, its results and its suggestion', () => {
  const { DossierView, dossierQueue } = views.dossier
  const { logic } = loadedRooms
  const base = filesOn()
  const docs = dossierQueue(base).find(x => logic.rowProject(x.row) === 'Docs')
  const ret = { key: docs.row.key, item: docs.slug, mode: 'go', title: 'answered here', at_ms: NOW - 60000, stage: 'result', tab: null }
  const s = { ...base, model: { ...base.model, returns: [...(base.model.returns ?? []), ret] },
    details: { ...base.details, task: { [docs.slug]: { status: 'ok', ver: base.model?.collected_ms ?? 0, data: { slug: docs.slug, front: { title: docs.row.title, status: 'doing' }, path: `work/tasks/${docs.slug}/STATUS.md` } } } },
    ui: { ...base.ui, area: 'Ops', dossierOpen: docs.slug } }
  const row = (s.model.sections ?? []).flatMap(x => x.rows ?? []).find(r => r.key === docs.row.key)
  const noNext = { ...s, model: { ...s.model, sections: s.model.sections.map(x => ({ ...x, rows: (x.rows ?? []).map(r => (r === row ? { ...r, next: null } : r)) })) } }
  const el = mount(html`<${DossierView} s=${logic.areaScope(noNext)} c=${recorder()} />`)
  const open = el.$('.dz-open')
  assert.ok(open, 'the file opened beside the queue')
  assert.match(open.$('.dz-area').text(), /Docs/)
  assert.ok(open.$('.rcard'), 'its result')
  assert.ok(open.button(en.dossier.suggest.button), 'the suggestion')
})

test('files: the area chip reads pressed while its area is the filter, a click lets go; no area reads so, quietly', () => {
  const { DossierView, dossierQueue } = views.dossier
  const { logic } = loadedRooms
  const s = filesOn({ ui: { area: 'Ops' } })
  const c = recorder()
  const el = mount(html`<${DossierView} s=${logic.areaScope(s)} c=${c} />`)
  const chip = el.$('.dz-area')
  assert.equal(chip.getAttribute('aria-pressed'), 'true')
  chip.click()
  assert.deepEqual(c.calls.at(-1), ['setArea', null])
  // a file without an area: a quiet word, no button
  const base = filesOn()
  const first = dossierQueue(base)[0]
  const bare = { ...base, model: { ...base.model, sections: base.model.sections.map(x => ({ ...x, rows: (x.rows ?? []).map(r => (r.key === first.row.key ? { ...r, area: null, area_names: [], mark: null } : r)) })) } }
  const el2 = mount(html`<${DossierView} s=${bare} c=${recorder()} />`)
  assert.equal(el2.$('.dz-area'), null)
  assert.match(el2.$('.dz-area-none').text(), new RegExp(en.home.noArea))
  assert.equal(el2.$('.dz-area-none').tagName === 'BUTTON', false)
})

test('files: the star and an area with nothing pinned say both, the button lets the star go', () => {
  const { DossierView } = views.dossier
  const { logic } = loadedRooms
  const c = recorder()
  const s = filesOn({ ui: { area: 'Ops', pinnedOnly: true } })
  const el = mount(html`<${DossierView} s=${logic.areaScope({ ...s, home: { ...s.home, pins: [] } })} c=${c} />`)
  assert.match(el.text(), new RegExp(en.dossier.emptyAreaPinned('Ops')))
  el.button(en.dossier.allFiles).click()
  assert.deepEqual(c.calls.at(-1), ['setPinnedOnly', false])
})

test('a file names its area on its cover; a click sets the area filter', () => {
  const { DossierView, dossierQueue } = views.dossier
  const s = filesOn()
  const first = dossierQueue(s)[0]
  const c = recorder()
  const el = mount(html`<${DossierView} s=${s} c=${c} />`)
  const chip = el.$('.dz-area')
  assert.ok(chip, 'the area on the cover')
  assert.match(chip.text(), new RegExp(loadedRooms.logic.rowProject(first.row)))
  assert.ok(chip.$('.home-area-dot'))
  chip.click()
  assert.deepEqual(c.calls.at(-1), ['setArea', loadedRooms.logic.rowProject(first.row)])
})

test('files: an area with nothing open says so and offers every area', () => {
  const { DossierView } = views.dossier
  const { logic } = loadedRooms
  const c = recorder()
  const v = logic.areaScope(filesOn({ ui: { area: 'Nowhere' } }))
  const el = mount(html`<${DossierView} s=${v} c=${c} />`)
  assert.match(el.text(), new RegExp(en.dossier.emptyArea('Nowhere')))
  el.button(en.dossier.allAreas).click()
  assert.deepEqual(c.calls.at(-1), ['setArea', null])
  // without a filter the plain words, no button
  const plain = mount(html`<${DossierView} s=${{ ...filesOn(), model: { ...filesOn().model, sections: [] }, tabs: { tabs: [] } }} c=${recorder()} />`)
  assert.equal(plain.button(en.dossier.allAreas), null)
})

test('the search stays across all areas: each hit names its area, under a filter a line says so', () => {
  const { DossierView, dossierQueue } = views.dossier
  const { logic } = loadedRooms
  const base = filesOn({ ui: { area: 'Ops' } })
  const other = dossierQueue(filesOn()).find(x => logic.rowProject(x.row) !== 'Ops')
  const find = { q: 'x', status: 'ok', data: { total: 1, truncated: false, groups: [
    { slug: other.slug, path: `work/tasks/${other.slug}`, title: other.row.title, kind: 'task', count: 1, hits: [] }] } }
  const el = mount(html`<${DossierView} s=${logic.areaScope({ ...base, find })} c=${recorder()} />`)
  const hit = el.$('.dz-found-item')
  assert.ok(hit, 'the hit of another area is found')
  assert.match(hit.$('.dz-found-area').text(), new RegExp(logic.rowProject(other.row)))
  assert.match(el.$('.dz-results').text(), new RegExp(en.dossier.find.allAreas))
  const plain = mount(html`<${DossierView} s=${{ ...filesOn(), find }} c=${recorder()} />`)
  assert.doesNotMatch(plain.$('.dz-results').text(), new RegExp(en.dossier.find.allAreas))
  assert.ok(plain.$('.dz-found-area'))
})

// ---------------------------------------------------------------- what a file is and where it comes from

test('the cover of a file names Task or Stream first, then where it comes from, and keeps its .dz parts', () => {
  const { DossierView, dossierQueue } = views.dossier
  const base = filesOn()
  const queue = dossierQueue(base)
  const stream = queue.find(x => x.slug === 'team-onboarding')
  assert.ok(stream, 'the demo stream is in the queue')
  for (const [x, word] of [[queue.find(y => y.slug !== 'team-onboarding'), en.kind.task], [stream, en.kind.stream]]) {
    const s = filesOn({ ui: { dossierAt: { id: x.id, i: queue.indexOf(x) } } })
    const el = mount(html`<${DossierView} s=${s} c=${recorder()} />`)
    const what = el.$('.dz-cover .dz-eyebrow-what')
    assert.ok(what && el.$('.dz-cover .dz-eyebrow-end') && el.$('.dz-cover .dz-title'), 'the .dz parts stand')
    assert.match(what.$('.kind').text(), new RegExp(`${word}$`))
    assert.ok(what.$('.origin'), 'the origin beside it')
  }
  // a closed task and an ended stream, as the file's own detail says
  for (const [kind, word] of [['done_task', en.kind.done_task], ['done_stream', en.kind.done_stream]]) {
    const x = queue[0]
    const s = filesOn()
    s.details = { inbox: {}, task: { [x.slug]: { status: 'ok', ver: s.model.collected_ms, data: { ok: true, slug: x.slug, kind: 'done', work_kind: kind,
      origin: { category: 'skill', word_key: null, detail: 'debrief', raw: 'debrief', ref: null, via_cockpit: false },
      front: {}, sections: [], log: [], inbox: [], files: [], related: [], path: `work/done/2026-10/${x.slug}/STATUS.md` } } } }
    const el = mount(html`<${DossierView} s=${s} c=${recorder()} />`)
    assert.match(el.$('.dz-eyebrow-what .kind').text(), new RegExp(`${word}$`))
    assert.equal(el.$('.dz-eyebrow-what .origin-word').text(), en.origin.skill)
  }
})
