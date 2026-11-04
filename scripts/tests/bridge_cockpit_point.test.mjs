// SPDX-License-Identifier: MIT
// Tests of the one point view (stage 1, scripts/web/point.js, views/flowpoint.js and the controller's ways that open
// a row), no npm dependencies.
//
//   node --test scripts/tests/bridge_cockpit_point.test.mjs
//
// Where Work through is on every way to an item or a task opens the point view of Work through: which open lands
// where (pointOpen), the point of a row of Not now and its walk, a point of its own for a row that stands nowhere,
// what the item drawer held and where it stands now (the fold Details, What it is about, History, the parent task),
// the basic verbs in their one order, Make it a task, and Instruct or Ask under the card. Where Work through is off
// the item drawer and the file card stay. The pure helpers are imported as the frontend suite imports them, the views
// are mounted as the render suite mounts them, the controller is read off its source.
import fs from 'node:fs'
import path from 'node:path'
import test from 'node:test'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import { loadCockpit } from './cockpit_render.mjs'

const { text, logic } = await loadCockpit()
const WEB = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'web')
const APP = fs.readFileSync(path.join(WEB, 'app.js'), 'utf8')
const method = head => {
  const at = APP.indexOf(`\n  ${head}`)
  assert.ok(at >= 0, `app.js has ${head}`)
  const end = APP.indexOf('\n  },', at)
  return APP.slice(at, end > 0 ? end : at + 2000)
}

// a fixed local "now": Friday, 9 October 2026, noon (the moment the other suites use)
const NOW = new Date(2026, 9, 9, 12, 0, 0).getTime()
const MIN = 60000

const task = (slug, over = {}) => ({ key: `task:${slug}`, task: slug, title: `Task ${slug}`, status: 'doing', bucket: 'tasks',
  priority: 'P2', settle: ['done', 'not_doing'], ...over })
const ask = (id, over = {}) => ({ key: `inbox:${id}`, inbox_id: id, title: `Question ${id}`, art: 'ask', inbox_state: 'open',
  bucket: 'do', gate: 'only-you', settle: ['done', 'not_doing'], ...over })
const ref = (repo, n, over = {}) => ({ key: `ref:${repo}#${n}`, ref: `${repo}#${n}`, title: `Issue ${n} of ${repo}`, bucket: 'plan',
  url: `https://example.org/${repo}/issues/${n}`, settle: ['done', 'not_doing'], ...over })

/** A state of Work through: the rows by section, the tabs, the ui and the rest (as the flow suite builds it) */
function state({ now = [], work = [], later = [], hidden = [], tabs = [], pages = [], ui = {}, flow = true, ...rest } = {}) {
  return {
    now: NOW, model: { sections: [{ id: 'now', rows: now }, { id: 'give', rows: [] }, { id: 'work', rows: work },
      { id: 'track', rows: [] }, { id: 'later', rows: later }], hidden, returns: [], pages },
    tabs: { tabs }, driver: { caps: null }, triage: { items: {} }, jevOrder: {},
    work: { flow: { enabled: flow, drop_reasons: ['resolves_itself', 'not_needed'], return_after_s: 20 } },
    themes: { enabled: false }, details: { inbox: {}, task: {}, activity: {} },
    ui: { page: 'briefing', workView: 'flow', busy: {}, flowAt: null, flowChip: 'all', flowJump: null, flowView: 'overview', ...ui }, ...rest,
  }
}

// ---------------------------------------------------------------- the rule and where a way lands

test('pointViewOn: the one point view holds exactly where the work tab offers Work through', () => {
  assert.equal(logic.pointViewOn(state()), true)
  assert.equal(logic.pointViewOn(state({ flow: false })), false, 'the OSS default keeps the drawer and the file card')
  assert.equal(logic.pointViewOn({ ...state(), work: { flow: { enabled: true }, views: ['due', 'files'] } }), false, 'work_views without flow')
  assert.equal(logic.pointViewOn(null), false)
})

test('pointOpen: a point opens in the queue at the level of all, an entry in Running now, a row of Not now in its group, the rest alone', () => {
  const s = state({ now: [ask('20261009-0900-a-q')], work: [task('run'), task('free')],
    hidden: [task('put-off', { hidden_until: '2026-10-20' })],
    tabs: [{ ref: 'surface:5', name: 'run', slug: 'run', state: 'working', since_ms: NOW - MIN }],
    ui: { flowSide: { themes: 'x', areas: 'Ops' }, flowMode: 'areas', flowPicked: ['task:free'], flowPlan: { steps: [] } } })
  const point = logic.pointOpen(s, 'task:free')
  assert.equal(point.flowView, 'point')
  assert.deepEqual(point.flowAt, { id: 'task:free', i: 0 })
  assert.equal(point.flowSide.areas, null, 'the side of the mode goes back to all, so the queue holds the point')
  assert.equal(point.flowSide.themes, 'x', 'the other mode keeps its side')
  assert.deepEqual(point.flowPicked, [])
  assert.equal(point.flowPlan, null)
  assert.deepEqual(logic.pointOpen(s, 'task:run'), { flowPicked: [], flowPlan: null, flowView: 'run', flowRunId: 'tab:surface:5', flowRunFrom: 'overview' })
  const left = logic.pointOpen(s, 'task:put-off')
  assert.equal(left.flowView, 'left')
  assert.equal(left.flowLeft, 'later')
  assert.deepEqual(left.flowLeftAt, { id: 'task:put-off', i: 0 }, 'the row opens in the middle, not the list alone, held as the queue holds a point')
  assert.deepEqual(logic.pointOpen(s, 'task:closed', 'work/done/2026-10/closed'),
    { flowPicked: [], flowPlan: null, flowView: 'solo', flowSolo: { key: 'task:closed', file: 'work/done/2026-10/closed' } })
  assert.deepEqual(logic.pointOpen(s, 'inbox:20261001-0900-a-gone').flowSolo, { key: 'inbox:20261001-0900-a-gone', file: null })
  assert.equal(logic.pointOpen(s, null), null)
  // the ticks of the group a row opens in stay where the group was open already
  const same = logic.pointOpen({ ...s, ui: { ...s.ui, flowLeft: 'later', flowLeftPicked: ['task:put-off'] } }, 'task:put-off')
  assert.deepEqual(same.flowLeftPicked, ['task:put-off'])
})

test('leftWalk and leftPoint: the rows of a group of Not now as points, in the list\'s order, the walk of a row opened there', () => {
  const s = state({ hidden: [task('b', { hidden_until: '2026-10-21', title: 'B' }), task('a', { hidden_until: '2026-10-20', title: 'A' })] })
  const parts = logic.flowParts(s)
  const walk = logic.leftWalk(parts, 'later')
  assert.deepEqual(walk.map(x => x.id), ['task:a', 'task:b'], 'the order of the list: the soonest day first')
  assert.deepEqual(walk.map(x => [x.group, x.left, x.kind]), [['left', 'later', 'row'], ['left', 'later', 'row']])
  assert.equal(logic.leftPoint(parts, 'later', 'task:b').row.title, 'B')
  assert.equal(logic.leftPoint(parts, 'later', 'task:gone'), null)
  assert.deepEqual(logic.leftWalk(parts, 'idea'), [])
})

test('soloPoint: another area\'s open row as it is, a closed task and a settled item read only from their detail', () => {
  const other = task('elsewhere', { area: 'Docs' })
  const s = state({ work: [other] })
  const open = logic.soloPoint(s, { key: 'task:elsewhere', file: null })
  assert.equal(open.readOnly, false, 'an open row keeps its verbs')
  assert.equal(open.row, other)
  // a closed copy: from the task detail of its folder
  const folder = 'work/done/2026-10/old'
  const closed = { ...s, details: { task: { [folder]: { status: 'ok', data: { slug: 'old', kind: 'done', work_kind: 'done_task', path: `${folder}/STATUS.md`,
    front: { status: 'done', type: 'feature', headline: 'Shipped the export' }, card: { title: 'Old export', goal: 'Export works' } } } }, inbox: {} } }
  const point = logic.soloPoint(closed, { key: 'task:old', file: folder })
  assert.equal(point.readOnly, true)
  assert.equal(point.file, folder)
  assert.equal(point.row.title, 'Old export')
  assert.equal(point.row.task, 'old')
  assert.deepEqual(point.row.settle, [], 'nothing settles a closed copy')
  const ids = logic.flowFields(point, { ...closed, themes: { enabled: true, assign: {} } }).map(f => f.id)
  assert.ok(!ids.includes('theme') && !ids.includes('who'), 'no theme to move and nobody at work on a closed point')
  assert.deepEqual(logic.soloSource({ key: 'task:old', file: folder }), { kind: 'task', id: folder })
  assert.deepEqual(logic.soloSource({ key: 'inbox:20261001-0900-a-x', file: null }), { kind: 'inbox', id: '20261001-0900-a-x' })
  assert.equal(logic.soloSource({ key: 'ref:acme/app#7' }), null)
  // a settled inbox item: from its detail
  const id = '20261001-0900-a-x'
  const item = { ...s, details: { task: {}, inbox: { [id]: { status: 'ok', data: { id, item: { summary: 'Was asked', state: 'done', kind: 'question', task: null } } } } } }
  const done = logic.soloPoint(item, { key: `inbox:${id}`, file: null })
  assert.equal(done.readOnly, true)
  assert.equal(done.row.title, 'Was asked')
  assert.equal(done.row.inbox_state, 'done')
  // a task no section lists (a new backlog task): open, so its verbs go, a task settles; a stream never does
  const fresh = { ...s, details: { task: { 'new-one': { status: 'ok', data: { slug: 'new-one', kind: 'task', work_kind: 'task', path: 'work/tasks/new-one/STATUS.md',
    front: { status: 'backlog' }, card: { title: 'A new one' } } } }, inbox: {} } }
  const made = logic.soloPoint(fresh, { key: 'task:new-one', file: null })
  assert.equal(made.readOnly, false)
  assert.deepEqual(made.row.settle, ['done', 'not_doing'])
  // nothing known yet: null, the view reads the detail first
  assert.equal(logic.soloPoint(s, { key: 'task:unknown', file: null }), null)
  assert.equal(logic.soloPoint(s, null), null)
})

// ---------------------------------------------------------------- what the drawer held, in the one view

const ITEM = { summary: 'Delete the scans?', detail: 'The scans of last week lie in the bin.', kind: 'decision', gate: 'only-you', urgency: 'later',
  state: 'open', task: null, key: 'bin-scans', closer: 'person', closes_when: null, action_display: null, created: '2026-10-01T16:59:00' }

test('pointFacts: an inbox item\'s kind, urgency, gate, who closes it, when it closes on its own, its key and id; a task\'s type, blocker and file', () => {
  const q = ask('20261001-1659-a-bin')
  const facts = logic.pointFacts({ kind: 'row', row: q }, ITEM)
  assert.deepEqual(facts.map(f => f.id), ['kind', 'urgency', 'gate', 'closer', 'closes', 'key', 'id'])
  assert.deepEqual(facts.find(f => f.id === 'closer'), { id: 'closer', value: 'person', probe: false })
  assert.equal(facts.find(f => f.id === 'id').value, '20261001-1659-a-bin')
  // before its detail came: what the row says, never a guess for the rest
  assert.deepEqual(logic.pointFacts({ kind: 'row', row: q }).map(f => f.id), ['gate', 'id'])
  // with a check that closes it and an action that runs on the yes
  const probe = logic.pointFacts({ kind: 'row', row: q }, { ...ITEM, closer: null, closes_when: { file_exists: 'x' }, action_display: 'make deploy' })
  assert.deepEqual(probe.find(f => f.id === 'closer'), { id: 'closer', value: null, probe: true })
  assert.equal(probe.find(f => f.id === 'runs').value, 'make deploy')
  const t = task('export', { task_type: 'feature' })
  assert.deepEqual(logic.pointFacts({ kind: 'row', row: t }, null, { path: 'work/tasks/export/STATUS.md', front: { type: 'bug', blocked_by: 'the vendor' } }),
    [{ id: 'kind', value: 'bug' }, { id: 'blocked', value: 'the vendor' }, { id: 'file', value: 'work/tasks/export/STATUS.md' }])
  assert.deepEqual(logic.pointFacts({ kind: 'row', row: task('s', { stream: true }) }), [{ id: 'file', value: 'work/streams/s/STATUS.md' }])
  assert.deepEqual(logic.pointFacts({ kind: 'row', row: ref('acme/app', 7) }), [{ id: 'ref', value: 'acme/app#7' }, { id: 'id', value: 'ref:acme/app#7' }])
  assert.deepEqual(logic.pointFacts({ kind: 'reports', rows: [] }), [])
})

test('pointAbout: the triage\'s gist, why only you can do it and its reason, and the raw description, on top of Description', () => {
  const q = ask('20261001-1659-a-bin')
  const s = { triage: { items: { [q.key]: { gist: 'Empty the bin after the check', doer: 'you', why: 'deleting is only yours', reason: 'Nothing says it is done' } } } }
  assert.deepEqual(logic.pointAbout(q, s, ITEM), { head: 'Empty the bin after the check', you: true, need: 'deleting is only yours',
    why: 'Nothing says it is done', text: 'The scans of last week lie in the bin.', cut: false })
  assert.deepEqual(logic.pointAbout(q, { triage: { items: {} } }, { ...ITEM, detail_truncated: true }),
    { head: null, you: false, need: null, why: null, text: ITEM.detail, cut: true })
  assert.equal(logic.pointAbout(q, { triage: { items: {} } }, null), null)
  assert.equal(logic.pointAbout(null, s), null)
})

test('historyRows and activityFilters: the item\'s events newest first, a filter History of their own only where there are some', () => {
  const rows = logic.historyRows([{ verb: 'created', by: 'web', at: '2026-10-01T16:59:00' }, { verb: 'defer', by: 'web', at: '2026-10-03T09:00:00', until: '2026-10-10' },
    { verb: 'note', by: 'bridge', at: '2026-10-02T10:00:00', text: 'Checked the folder' }, { at: '2026-10-04T10:00:00' }])
  assert.deepEqual(rows.map(r => r.verb), ['defer', 'note', 'created'], 'newest first, an event without a verb left out')
  assert.equal(rows[1].note, 'Checked the folder', 'what a tab noted reads as its note')
  assert.ok(rows.every(r => r.kind === 'history'))
  assert.deepEqual(logic.activityFilters(rows), [...logic.ACTIVITY_FILTERS, 'history'])
  assert.deepEqual(logic.activityFilters([]), logic.ACTIVITY_FILTERS)
  assert.deepEqual(logic.historyRows(null), [])
})

test('relatedOf: an item that names a task has that task as its parent, apart from the other items of it', () => {
  const t = task('a')
  const q1 = ask('20261009-0900-a-q', { task: 'a' })
  const q2 = ask('20261009-0901-a-r', { task: 'a' })
  const s = state({ now: [q1, q2], work: [t] })
  const rel = logic.relatedOf({ kind: 'row', row: q1 }, s, { related: ['docs/guide.md'] })
  assert.equal(rel.parent.key, 'task:a')
  assert.deepEqual(rel.rows.map(r => r.key), [q2.key])
  assert.deepEqual(rel.paths, ['docs/guide.md'])
  // the task itself has no parent; its items are its related rows
  const own = logic.relatedOf({ kind: 'row', row: t }, s, null)
  assert.equal(own.parent, null)
  assert.deepEqual(own.rows.map(r => r.key), [q1.key, q2.key])
  // a parent the sections do not list (a backlog task) stands with what its file says
  const lone = logic.relatedOf({ kind: 'row', row: ask('20261009-0902-a-z', { task: 'shelf' }) }, state(), { card: { title: 'The shelf' } })
  assert.deepEqual(lone.parent, { key: 'task:shelf', task: 'shelf', title: 'The shelf' })
})

// ---------------------------------------------------------------- the basic verbs in their one order

test('basicVerbs: every point offers Let AI do it, Done, Later and Drop in that order, Make it a task where it can become one', () => {
  const ids = list => list.map(v => (v.off ? `${v.id}:${v.off}` : v.id))
  assert.deepEqual(ids(logic.basicVerbs(ask('20261009-0900-a-q'))), ['do', 'done', 'later', 'drop', 'task'])
  assert.deepEqual(ids(logic.basicVerbs(task('a'))), ['do', 'done', 'later', 'drop'], 'a task is one already')
  assert.deepEqual(ids(logic.basicVerbs(task('s', { stream: true, settle: [] }))), ['do', 'done:stream', 'later', 'drop:stream'])
  assert.deepEqual(ids(logic.basicVerbs(ask('20261009-0900-a-y', { inbox_state: 'approved' }))), ['do:approved', 'done', 'later', 'drop', 'task'])
  assert.deepEqual(ids(logic.basicVerbs(task('a'), { live: true })), ['do:working', 'done', 'later', 'drop'], 'no second agent beside a live tab')
  assert.deepEqual(ids(logic.basicVerbs(task('a'), { live: true, asks: true })), ['do:working', 'done:asks', 'later', 'drop:asks'],
    'nothing closes what waits for an answer')
  assert.deepEqual(ids(logic.basicVerbs(task('a', { settle: [] }))), ['do', 'done:unsettled', 'later', 'drop'])
  assert.deepEqual(ids(logic.basicVerbs(ask('20261009-0900-a-q'), { person: true })), ['done', 'later', 'drop'], 'a person starts nothing')
  // an issue: a task only through its page's step, never a pull request or an issue with a task
  assert.deepEqual(ids(logic.basicVerbs(ref('acme/app', 7))), ['do', 'done', 'later', 'drop'])
  assert.deepEqual(ids(logic.basicVerbs(ref('acme/app', 7), { adopt: { page: 'gh', section: 'mine', index: 0 } })), ['do', 'done', 'later', 'drop', 'task'])
  assert.deepEqual(logic.BASIC_VERBS, ['do', 'done', 'later', 'drop', 'task'])
})

test('adoptStepOf: the GitHub page row of an issue whose step makes it a task, none for a pull request or an issue with a task', () => {
  const pages = [{ id: 'gh', sections: [{ id: 'mine', kind: 'tracker', items: [
    { index: 0, row_id: 'acme/app#7', actions: [{ id: 'analyze' }, { id: 'adopt' }] },
    { index: 1, row_id: 'acme/app#8', actions: [{ id: 'review' }] }] }] }]
  const s = { model: { pages } }
  assert.deepEqual(logic.adoptStepOf(ref('acme/app', 7), s), { page: 'gh', section: 'mine', index: 0 })
  assert.equal(logic.adoptStepOf(ref('acme/app', 8), s), null, 'a pull request has no such step')
  assert.equal(logic.adoptStepOf(ref('acme/app', 7, { task: 'app-7' }), s), null)
  assert.equal(logic.adoptStepOf(ask('20261009-0900-a-q'), s), null)
})

test('pointContext: a task carries its file as the files view words it, any other row its facts, never more than fits', () => {
  const t = task('export')
  assert.equal(logic.pointContext({ kind: 'row', row: t }, state(), null, null, 'en'),
    logic.fileContext(logic.fileFacts('export', null, t), 'en'))
  const q = ask('20261001-1659-a-bin', { card: { goal: 'The bin is empty', acceptance: ['No scan is left'] } })
  const s = { triage: { items: { [q.key]: { gist: 'Empty the bin' } } } }
  const ctx = logic.pointContext({ kind: 'row', row: q }, s, null, ITEM, 'en')
  for (const part of [q.title, q.key, 'The bin is empty', '- No scan is left', 'Empty the bin', ITEM.detail]) assert.ok(ctx.includes(part), part)
  const long = logic.pointContext({ kind: 'row', row: q }, s, null, { ...ITEM, detail: 'x'.repeat(9000) }, 'de')
  assert.equal(long.length, logic.CONTEXT_MAX)
  assert.equal(logic.pointContext({ kind: 'reports', rows: [] }, s), '')
})

test('infoPoint: a page item opens as its point where its row stands on the page, by its key or its own id; else it keeps its drawer', () => {
  const app = { key: 'item:apps:app-7', ref: 'app-7', title: 'Application seven', bucket: 'do', urgency: 'today', sources: ['apps'] }
  const s = state({ now: [app, ask('20261009-0900-a-q')], work: [task('a')] })
  assert.equal(logic.infoPoint(s, { row_id: 'app-7', title: 'Application seven' }), 'item:apps:app-7')
  assert.equal(logic.infoPoint(s, { task: 'a' }), 'task:a')
  assert.equal(logic.infoPoint(s, { inbox: '20261009-0900-a-q', task: 'a' }), 'inbox:20261009-0900-a-q', 'an item is the row, not its task')
  assert.equal(logic.infoPoint(s, { row_id: 'cpu-load', title: 'CPU' }), null, 'a gauge is no row')
  assert.equal(logic.infoPoint(s, { task: 'gone' }), null, 'a task that stands nowhere keeps the drawer of its page item')
  assert.equal(logic.infoPoint(s, null), null)
})

// ---------------------------------------------------------------- the controller: every way lands in the one view

test('the controller: openItem, openFile, openInfo and select open the one point view where it holds, the drawer and the file card where not', () => {
  const open = method('openItem(key')
  assert.match(open, /pointViewOn\(/, 'openItem asks the rule first')
  assert.match(open, /openPoint\(/)
  assert.match(open, /drawer: 'item'/, 'and keeps the drawer where Work through is off')
  const file = method('openFile(slug, path) {')
  assert.match(file, /pointViewOn\(/)
  assert.match(file, /openPoint\(/)
  assert.match(file, /fileClick\(/, 'the Files tab and the fallback keep their way')
  const info = method('openInfo(it, page, section, drawer = false) {')
  assert.match(info, /pointViewOn\(/)
  assert.match(info, /infoPoint\(/, 'only a page item that stands on the page as a row opens as a point')
  assert.match(info, /!drawer/, 'the steps of a point keep their drawer')
  const point = method('openPoint(key')
  assert.match(point, /pointOpen\(/)
  assert.match(point, /workViewGo\(/, 'the work tab goes to Work through the way every view switch goes')
  assert.match(method('select(key) {'), /openPoint\(/)
})
