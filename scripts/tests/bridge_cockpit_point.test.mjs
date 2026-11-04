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
import { cockpitState, loadCockpit, mount, recorder, settle as rounds } from './cockpit_render.mjs'

const { html, views, text, logic } = await loadCockpit()
const en = text.TABLES.en
const de = text.TABLES.de
const tick = () => rounds()
const until = async (ok, ms = 2000) => { for (const end = Date.now() + ms; !ok() && Date.now() < end;) await tick() }
/** Stage 4: the fold Details of the fields opened (every field but Theme, Area, Who and Due stands in it) */
async function openDetails(el) {
  const t = el.$('.flow-aside .flow-facts-toggle')
  if (t && t.getAttribute('aria-expanded') !== 'true') { t.click(); await tick() }
  return el
}
/** Stage 4: the item of the menu More whose words are `word` (or start with them), the menu opened first */
async function moreItem(el, word) {
  const t = el.$('.flow-aside .flow-more-toggle')
  if (t && t.getAttribute('aria-expanded') !== 'true') { t.click(); await tick() }
  return el.$$('.flow-aside .flow-more-item').find(b => b.text() === word || b.text().startsWith(word)) ?? null
}
const WEB = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'web')
const APP = fs.readFileSync(path.join(WEB, 'app.js'), 'utf8')
const method = head => {
  const at = APP.indexOf(`\n  ${head}`)
  assert.ok(at >= 0, `app.js has ${head}`)
  const end = APP.indexOf('\n  },', at)
  return APP.slice(at, end > 0 ? end : at + 2000)
}
const proto = Object.getPrototypeOf(document.createElement('div'))
if (!proto.querySelector) proto.querySelector = function querySelector(sel) { return this.$(sel) }
proto.focus ??= function focus() { document.activeElement = this }
globalThis.window ??= { addEventListener() {}, removeEventListener() {}, innerWidth: 1280 }
for (const k of ['offsetLeft', 'offsetWidth', 'scrollWidth', 'clientWidth']) Object.defineProperty(proto, k, { get: () => 0, configurable: true })

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
  const listed = { ...closed, records: { status: 'ok', data: { records: [{ path: folder, slug: 'old', kind: 'done', area: 'Docs' }] } } }
  assert.equal(logic.soloPoint(listed, { key: 'task:old', file: folder }).row.area, 'Docs', 'its area as the Files tab listed it')
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

test('pointFacts: an inbox item\'s kind, gate, who closes it, when it closes on its own, its key and id; a task\'s type, blocker and file', () => {
  const q = ask('20261001-1659-a-bin')
  const facts = logic.pointFacts({ kind: 'row', row: q }, ITEM)
  // the urgency is a field of its own to change (stage 3), not a fact under Details
  assert.deepEqual(facts.map(f => f.id), ['kind', 'gate', 'closer', 'closes', 'key', 'id'])
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
    why: 'Nothing says it is done', text: 'The scans of last week lie in the bin.', cut: false, reasons: [], lines: [] })
  assert.deepEqual(logic.pointAbout(q, { triage: { items: {} } }, { ...ITEM, detail_truncated: true }),
    { head: null, you: false, need: null, why: null, text: ITEM.detail, cut: true, reasons: [], lines: [] })
  assert.equal(logic.pointAbout(q, { triage: { items: {} } }, null), null)
  assert.equal(logic.pointAbout(null, s), null)
  // stage 3: why it is here (the briefing's reasons) and the lines its page writes of its task
  const lines = [{ kind: 'next', text: 'Ask the vendor' }]
  const pages = [{ id: 'p', sections: [{ id: 'x', items: [{ title: 'a', task: 'a', lines }] }] }]
  const about = logic.pointAbout(task('a', { why: ['due tomorrow', ' '] }), { triage: { items: {} }, model: { pages } })
  assert.deepEqual([about.reasons, about.lines], [['due tomorrow'], lines])
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
  const info = method('openInfo(it, page, section) {')
  assert.match(info, /pointViewOn\(/)
  assert.match(info, /infoPoint\(/, 'only a page item that stands on the page as a row opens as a point')
  const point = method('openPoint(key')
  assert.match(point, /pointOpen\(/)
  assert.match(point, /workViewGo\(/, 'the work tab goes to Work through the way every view switch goes')
  assert.match(method('select(key) {'), /openPoint\(/)
})

// ---------------------------------------------------------------- the one view, mounted

const { FlowPage } = views.flow
const { DossierView, dossierQueue } = views.dossier
const flowState = (over = {}) => cockpitState(NOW, state(over))

test('Not now: a title opens the row in the one point view in the middle, To the list leads back, the walk walks the group', () => {
  const rows = [task('b', { hidden_until: '2026-10-21', title: 'Second' }), task('a', { hidden_until: '2026-10-20', title: 'First' })]
  const c = recorder()
  const list = mount(html`<${FlowPage} s=${flowState({ hidden: rows, ui: { flowView: 'left', flowLeft: 'later', flowLeftPicked: [] } })} c=${c} />`)
  list.$$('.flow-ov-open')[1].click()
  assert.deepEqual(c.calls.at(-1), ['flowLeftOpen', 'task:b', 1])
  const el = mount(html`<${FlowPage} s=${flowState({ hidden: rows, ui: { flowView: 'left', flowLeft: 'later', flowLeftAt: { id: 'task:b', i: 1 } } })} c=${c} />`)
  assert.match(el.$('.flow-card .fx-title').text(), /Second/)
  assert.match(el.$('.flow-card .fx-kind').text(), new RegExp(en.flow.notnow.group.later), 'its group in the head')
  assert.ok(el.$('.flow-ptabs') && el.$('.flow-aside .verbbar-grid'), 'the same tabs and verbs as every point (stage 4: the four states)')
  assert.equal(el.$('.flow-leftlist'), null, 'the list gives way to the point')
  assert.match(el.$('.dz-walk').text(), /2 of 2/)
  el.button(en.flow.one.backList).click()
  assert.deepEqual(c.calls.at(-1), ['flowLeft', 'later'])
  el.$('.dz-walk').button(en.flow.walk2.prev).click()
  assert.deepEqual(c.calls.at(-1), ['flowLeftOpen', 'task:a', 0])
  // a row that left its group: the next of the group in its place, the list once the group is empty
  const moved = mount(html`<${FlowPage} s=${flowState({ hidden: [rows[1]], ui: { flowView: 'left', flowLeft: 'later', flowLeftAt: { id: 'task:b', i: 1 } } })} c=${c} />`)
  assert.match(moved.$('.flow-card .fx-title').text(), /First/)
  for (const lang of ['en', 'de']) assert.ok(text.TABLES[lang].flow.one.backList, lang)
  assert.equal(de.flow.one.backList, 'Zur Liste')
})

test('a point of its own: a closed task reads its file and offers nothing, Ask still asks; Back to the overview', async () => {
  const folder = 'work/done/2026-10/old'
  const details = { inbox: {}, activity: {}, task: { [folder]: { status: 'ok', ver: 0, data: { slug: 'old', kind: 'done', work_kind: 'done_task',
    path: `${folder}/STATUS.md`, front: { status: 'done', type: 'feature', headline: 'Shipped the export' }, card: { title: 'Old export', goal: 'Export works' },
    sections: [{ heading: 'Situation', text: 'Done in October.' }] } } } }
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${flowState({ details, ui: { flowView: 'solo', flowSolo: { key: 'task:old', file: folder } } })} c=${c} />`)
  assert.match(el.$('.flow-card .fx-title').text(), /Old export/)
  // stage 4: the headline is stored with the rest, folded in Description
  assert.ok(!el.$('.flow-card').text().includes('Shipped the export'), 'no headline under the title')
  assert.match(el.$('.flow-ptabs .flow-stored').text(), /Shipped the export/, 'the headline in the fold What else is stored')
  assert.match(el.$('.flow-aside .flow-readonly').text(), new RegExp(en.flow.one.readOnly))
  assert.equal(el.$('.flow-aside .verbbar'), null, 'no verb acts on a closed copy')
  assert.equal(el.button(en.flow.instruct.send), null, 'no instruction')
  assert.ok(el.button(en.flow.ask.send), 'a question still goes')
  el.button(en.flow.point.back).click()
  assert.deepEqual(c.calls.at(-1), ['flowOverview'])
  // not read yet: it is read, and the middle says so
  const lc = recorder()
  const wait = mount(html`<${FlowPage} s=${flowState({ ui: { flowView: 'solo', flowSolo: { key: 'task:old', file: folder } } })} c=${lc} />`)
  assert.match(wait.$('.flow-main').text(), new RegExp(en.flow.one.loading))
  await until(() => lc.calls.some(x => x[0] === 'loadTask'))
  assert.deepEqual(lc.calls.find(x => x[0] === 'loadTask'), ['loadTask', folder])
})

test('the card of a point: its kind and Pin in the head, the next step in one line under the title with who as a chip', () => {
  const t = task('a', { card: { title: 'Task a', next: { what: 'Send the draft', who: 'me' } } })
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${flowState({ work: [t], ui: { flowView: 'point', flowAt: { id: 'task:a', i: 0 } } })} c=${c} />`)
  const head = el.$('.flow-card .fx-hero-top')
  assert.ok(head.$('.kind-tag') || head.text().includes(en.kind.task), 'the kind of row in the head')
  const pin = el.$('.flow-card .flow-pin')
  assert.equal(pin.text().trim(), `☆ ${en.flow.one.pin}`)
  pin.click()
  assert.deepEqual(c.calls.at(-1), ['pin', 'task:a', true])
  const next = el.$('.flow-card .flow-step')
  assert.match(next.text(), /Send the draft/)
  assert.equal(next.$('.flow-who').text(), en.card.who.me)
  const pinned = mount(html`<${FlowPage} s=${{ ...flowState({ work: [t], ui: { flowView: 'point', flowAt: { id: 'task:a', i: 0 } } }), home: { pins: ['task:a'] } }} c=${recorder()} />`)
  assert.equal(pinned.$('.flow-card .flow-pin').text().trim(), `★ ${en.flow.one.pinned}`)
})

test('what the drawer held: the facts under Details, what it is about and the description in Description, the history in Activity, the parent in Related', async () => {
  const id = '20261001-1659-a-bin'
  const q = ask(id, { task: 'a', title: 'Delete the scans?' })
  const details = { task: {}, activity: { [q.key]: { status: 'ok', ver: 0, data: { rows: [], counts: { all: 0 }, can: { note: true } } } },
    inbox: { [id]: { status: 'ok', ver: 0, data: { id, item: ITEM, events: [{ verb: 'defer', by: 'web', at: '2026-10-03T09:00:00', until: '2026-10-05' }] } } } }
  const triage = { items: { [q.key]: { gist: 'Empty the bin after the check', doer: 'you', why: 'deleting is only yours', reason: 'Nothing says it is done' } } }
  const base = over => cockpitState(NOW, { ...state({ now: [q], work: [task('a')], ui: { flowView: 'point', flowAt: { id: q.key, i: 0 }, ...over } }), details, triage })
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${base({})} c=${c} />`)
  // the fold Details at the foot of the fields
  assert.equal(el.$('.flow-facts'), null, 'folded')
  el.$('.flow-facts-toggle').click()
  await tick()
  const facts = Object.fromEntries(el.$$('.flow-facts .meta-item').map(m => [m.getAttribute('data-fact'), m.$('dd').text()]))
  assert.equal(facts.kind, en.item.kindName.decision)
  assert.equal(facts.gate, en.gate['only-you'] ?? 'only-you')
  assert.equal(facts.closer, en.item.closerKind.person)
  assert.equal(facts.closes, en.item.noProbe)
  assert.equal(facts.id, id)
  // Description: what it is about, the description as filed
  const desc = el.$('.flow-desc')
  assert.match(desc.text(), new RegExp(en.flow.one.about))
  assert.match(desc.text(), /Empty the bin after the check/)
  assert.match(desc.text(), new RegExp(en.flow.one.needs('deleting is only yours')))
  assert.match(desc.text(), /The scans of last week lie in the bin\./)
  // Activity: History, a filter of its own
  const act = mount(html`<${FlowPage} s=${base({ flowTab: 'activity', flowFilter: 'history' })} c=${recorder()} />`)
  const hist = act.$$('.flow-act-row.is-history')
  assert.equal(hist.length, 1)
  assert.match(hist[0].text(), new RegExp(en.item.verb.defer))
  assert.ok(act.$$('.flow-act-filters button').some(b => b.text().startsWith(en.flow.activity.filter.history)))
  // Related: the task it belongs to, a click opens it in the same view
  const rc = recorder()
  const rel = mount(html`<${FlowPage} s=${base({ flowTab: 'related' })} c=${rc} />`)
  assert.match(rel.$('.flow-related').text(), new RegExp(en.flow.one.parent))
  rel.$('.flow-related-open').click()
  assert.deepEqual(rc.calls.at(-1), ['openItem', 'task:a'])
})

test('a task\'s Description folds its STATUS.md under From the file', () => {
  const details = { inbox: {}, activity: {}, task: { a: { status: 'ok', ver: 0, data: { slug: 'a', kind: 'task', path: 'work/tasks/a/STATUS.md', front: {},
    card: { title: 'Task a', goal: 'Ship it' }, sections: [{ heading: 'Situation', text: 'Half way.' }, { heading: 'Next Steps', text: '- [ ] ship' }], related: [] } } } }
  const el = mount(html`<${FlowPage} s=${cockpitState(NOW, { ...state({ work: [task('a')], ui: { flowView: 'point', flowAt: { id: 'task:a', i: 0 } } }), details })} c=${recorder()} />`)
  const fold = el.$('.flow-desc .flow-sections')
  assert.ok(fold)
  assert.match(fold.$('summary').text(), new RegExp(en.flow.one.sections(2)))
  assert.deepEqual(fold.$$('.flow-section summary').map(x => x.text()), ['Situation', 'Next Steps'])
})

test('Make it a task: every inbox item offers it through a panel that says what it does; an issue through its page\'s step', async () => {
  const q = ask('20261009-0900-a-q')
  const calls = []
  const c = new Proxy({}, { get: (_, p) => (p === 'calls' ? calls : p === 'then' || typeof p === 'symbol' ? undefined
    : (...a) => { calls.push([p, ...a]); return p === 'act' ? Promise.resolve({ ok: true, task: 'new-one' }) : undefined }) })
  const el = mount(html`<${FlowPage} s=${flowState({ now: [q], ui: { flowView: 'point', flowAt: { id: q.key, i: 0 } } })} c=${c} />`)
  ;(await moreItem(el, en.flow.basic.task)).click()
  await tick()
  assert.match(el.$('.verbbar-panel').text(), new RegExp(en.flow.basic.taskInbox))
  el.button(en.flow.basic.taskGo).click()
  await until(() => calls.some(x => x[0] === 'openItem'))
  assert.deepEqual(calls.find(x => x[0] === 'act'), ['act', 'to_task', { key: q.key }])
  assert.deepEqual(calls.find(x => x[0] === 'openItem'), ['openItem', 'task:new-one'], 'the new task opens in the same view')
  // an issue with the GitHub page's step
  const issue = ref('acme/app', 7, { bucket: 'do' })
  const pages = [{ id: 'gh', title: 'GitHub', sections: [{ id: 'mine', kind: 'tracker', items: [{ index: 3, row_id: 'acme/app#7', actions: [{ id: 'adopt', label: 'x' }] }] }] }]
  const ic = recorder()
  const iel = mount(html`<${FlowPage} s=${flowState({ now: [issue], pages, ui: { flowView: 'point', flowAt: { id: issue.key, i: 0 } } })} c=${ic} />`)
  ;(await moreItem(iel, en.flow.basic.task)).click()
  await tick()
  assert.match(iel.$('.verbbar-panel').text(), new RegExp(en.flow.basic.taskIssue.slice(0, 20)))
  iel.button(en.flow.basic.taskGo).click()
  await tick()
  assert.deepEqual(ic.calls.find(x => x[0] === 'act'), ['act', 'row_action', { page: 'gh', section: 'mine', index: 3, action: 'adopt' }])
  // a task is one already, a pull request has no step
  const tel = mount(html`<${FlowPage} s=${flowState({ work: [task('a')], ui: { flowView: 'point', flowAt: { id: 'task:a', i: 0 } } })} c=${recorder()} />`)
  assert.equal(await moreItem(tel, en.flow.basic.task), null)
  assert.equal(de.flow.basic.task, 'Zur Aufgabe machen')
})

test('Instruct or Ask: a switch over the line on a point; Ask sends a question about the point the files view\'s way, its answer under the line', async () => {
  const q = ask('20261009-0900-a-q', { title: 'Delete the scans?' })
  const st = over => cockpitState(NOW, { ...state({ now: [q], ui: { flowView: 'point', flowAt: { id: q.key, i: 0 }, ...over } }),
    work: { flow: { enabled: true, drop_reasons: [], return_after_s: 20, instruct: { enabled: true, budget_per_day: 30, model: null } } } })
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${st({})} c=${c} />`)
  const mode = el.$('.flow-line-mode')
  assert.deepEqual(mode.$$('button').map(b => b.text()), [en.flow.ask.instruct, en.flow.ask.ask])
  mode.button(en.flow.ask.ask).click()
  assert.deepEqual(c.calls.at(-1), ['flowLine', 'ask'])
  const ac = recorder()
  const asking = mount(html`<${FlowPage} s=${st({ flowLine: 'ask' })} c=${ac} />`)
  assert.equal(asking.button(en.flow.instruct.send), null)
  const box = asking.$('#flow-ask-text')
  box.value = 'what happened since Monday?'
  box.dispatch('input')
  await tick()
  asking.$('.flow-instruct-row').button(en.flow.ask.send).click()
  await until(() => ac.calls.some(x => x[0] === 'flowAsk'))
  const call = ac.calls.find(x => x[0] === 'flowAsk')
  assert.equal(call[1], 'what happened since Monday?')
  assert.match(call[2], /Delete the scans\?/, 'the point goes along as data')
  assert.equal(call[3], null, 'an inbox item names no task')
  assert.equal(call[4], q.key)
  // the answer under the line
  const quick = { available: true, convs: [{ id: 'q0000000001', running: false, turns: [{ q: 'x', a: 'Nothing moved since Monday.' }] }] }
  const ans = mount(html`<${FlowPage} s=${{ ...st({ flowLine: 'ask', flowAsk: { key: q.key, conv: 'q0000000001' } }), quick }} c=${recorder()} />`)
  assert.match(ans.$('.flow-ask-answer').text(), /Nothing moved since Monday\./)
  // the controller asks the files view's way: a free quick question with the point as data
  const ask_ = method('flowAsk: (text, context, task, key)')
  assert.match(ask_, /api\.ask\('free'/)
  assert.match(ask_, /via: 'quick'/)
  assert.deepEqual([de.flow.ask.instruct, de.flow.ask.ask], ['Anweisen', 'Fragen'])
})

test('the Files tab with Work through on: a record opens in the one point view, its walk over the list, Close the record; off, the file card stays', async () => {
  const s = cockpitState(NOW, { ui: { page: '@files' } })
  const queue = dossierQueue(s)
  const x = queue.find(q => q.reason === 'task') ?? queue[0]
  const c = recorder()
  const el = mount(html`<${DossierView} s=${{ ...s, ui: { ...s.ui, filesWalk: true, dossierAt: { id: x.id, i: queue.indexOf(x) } } }} c=${c} />`)
  assert.ok(el.$('.flow-main .flow-card') && el.$('.flow-main .flow-ptabs'), 'the card and the tabs of a point')
  assert.equal(el.$('.dz-cover'), null, 'no file card')
  assert.ok(el.$('.flow-aside .verbbar-grid'), 'the right column of Work through')
  assert.equal(el.$('.flow-aside .flow-details'), null, 'no Details link')
  assert.ok(el.$('.flow-main .dz-walk'), 'the walk')
  el.button(en.dossier.start.back).click()
  assert.deepEqual(c.calls.at(-1), ['filesHome'])
  // Work through off: the file card and the Details link, as before
  const off = { ...s, work: { ...s.work, flow: { ...s.work.flow, enabled: false } }, ui: { ...s.ui, filesWalk: true, dossierAt: { id: x.id, i: queue.indexOf(x) } } }
  const card = mount(html`<${DossierView} s=${off} c=${recorder()} />`)
  assert.ok(card.$('.dz-cover'))
  assert.equal(card.$('.flow-main .flow-ptabs'), null)
})

test('a tab that asks about a row: the card is titled by the point opened, the tab named in the line under it', () => {
  const t = task('guide', { title: 'Write the setup guide' })
  const tab = { ref: 'surface:9', name: 'guide research', slug: 'guide', state: 'needs-you', since_ms: NOW - MIN, ask: { text: 'Shall I go on?' } }
  const el = mount(html`<${FlowPage} s=${flowState({ work: [t], tabs: [tab], ui: { flowView: 'point', flowAt: { id: 'tab:surface:9', i: 0 } } })} c=${recorder()} />`)
  assert.equal(el.$('.flow-card .fx-title').text().trim(), 'Write the setup guide')
  assert.equal(el.$('.flow-card .fx-sub').text(), en.flow.one.tabAsks('guide research'))
  assert.match(el.$('.flow-card').text(), /Shall I go on\?/)
  assert.match(el.$('.dz-walk')?.text() ?? 'Write the setup guide', /Write the setup guide|1 of/)
  // the Files tab opens the same point under the same title
  const s = flowState({ work: [t], tabs: [tab], ui: { page: '@files', dossierOpen: 'guide' } })
  const files = mount(html`<${DossierView} s=${s} c=${recorder()} />`)
  assert.equal(files.$('.flow-card .fx-title').text().trim(), 'Write the setup guide')
  // a tab with no row behind it is the point: its name is the title
  const alone = { ...tab, slug: null, ref: 'surface:8', name: 'loose' }
  const el2 = mount(html`<${FlowPage} s=${flowState({ tabs: [alone], ui: { flowView: 'point', flowAt: { id: 'tab:surface:8', i: 0 } } })} c=${recorder()} />`)
  assert.equal(el2.$('.flow-card .fx-title').text().trim(), 'loose')
  assert.equal(de.flow.one.tabAsks('x'), 'Tab x fragt')
})

// ---------------------------------------------------------------- stage 3: every way the same view, nothing the drawer did lost

const answering = (answer = { ok: true }) => {
  const calls = []
  return new Proxy({}, { get: (_, p) => (p === 'calls' ? calls : p === 'then' || typeof p === 'symbol' ? undefined
    : (...a) => { calls.push([p, ...a]); return p === 'act' ? Promise.resolve(answer) : undefined }) })
}
const pick = (el, value) => { el.value = value; el.dispatch('change') }
const BOOT = { status: 'ok', config: { areas: ['Ops', 'Docs'] } }
const pointAt = (key, over = {}) => ({ flowView: 'point', flowAt: { id: key, i: 0 }, ...over })

test('pointList, pointListAt and pointBack: the list a way came from, walked in Work through, and where it leads back', () => {
  const back = logic.pointBack(state({ ui: { page: '@check', flowView: 'check', flowLeft: 'later' } }))
  assert.equal(back.page, '@check')
  assert.equal(back.ui.flowView, 'check')
  assert.equal(back.ui.flowLeft, 'later')
  const list = logic.pointList([{ key: 'task:a', title: 'A' }, { key: 'task:b', title: 'B' }, { key: 'task:a', title: 'again' }, { title: 'no key' }], 'task:b', back)
  assert.deepEqual(list.items, [{ key: 'task:a', title: 'A' }, { key: 'task:b', title: 'B' }], 'each key once, in the list\'s order')
  assert.equal(list.i, 1)
  assert.equal(list.back, back)
  assert.equal(logic.pointList([{ key: 'task:a' }], 'task:z', back), null, 'a key the list does not hold')
  assert.equal(logic.pointList(null, 'task:a', back), null)
  // the point in front: the list holds while that row stands there, by its key or the key it covers
  assert.equal(logic.pointListAt(list, { group: 'solo', id: 'task:b', kind: 'row', row: task('b') }), list)
  assert.equal(logic.pointListAt(list, { group: 'doing', id: 'task:b', kind: 'row', row: task('b') }), list)
  assert.equal(logic.pointListAt(list, { group: 'doing', id: 'task:a', kind: 'row', row: task('a') }), null, 'another point: the list lets go')
  assert.equal(logic.pointListAt(null, { id: 'task:b', row: task('b') }), null)
})

test('the controller: peek, openItem and select open the one point view with the list they came from; off, the detail and the drawer stay', () => {
  const peek = method('peek(key, from')
  assert.match(peek, /pointViewOn\(/, 'peek asks the rule first')
  assert.match(peek, /openPoint\(key, null, pointList\(queue, key, pointBack\(/)
  assert.match(peek, /pageDetail: true/, 'and keeps the detail beside the page where Work through is off')
  assert.match(method('openItem(key'), /pointList\(queue, key, pointBack\(/)
  const sel = method('select(key) {')
  assert.match(sel, /pointViewOn\(/)
  assert.match(sel, /dayQueue\(/, 'a row of Due walks the Due list')
  assert.match(method('openPoint(key'), /flowList: list/)
  assert.match(method('flowListBack()'), /setPage\(/)
  assert.match(method('flowListGo(k)'), /openPoint\(/)
  // every other way inside Work through lets the list go
  for (const head of ['flowGo:', 'flowOverview:', 'flowLeft:', 'flowLeftOpen:', 'flowRead:', 'flowReadOpen:', 'flowRun:', 'flowRunning:', 'flowSolo:',
    'flowCheck:', 'flowSide:', 'flowMode:']) {
    const at = APP.indexOf(`\n  ${head}`)
    assert.ok(at >= 0, head)
    const rest = APP.slice(at + 3)
    const end = rest.search(/\n {2}[a-zA-Z/]/)
    assert.match(rest.slice(0, end), /flowList: null/, head)
  }
})

test('a row opened from a list: To the list leads back where the list stood, the walk walks that list', () => {
  const rows = [task('a', { title: 'First' }), task('b', { title: 'Second' })]
  const flowList = logic.pointList(rows.map(r => ({ key: r.key, title: r.title })), 'task:b', { page: '@check', ui: {} })
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${flowState({ work: rows, ui: pointAt('task:b', { flowList }) })} c=${c} />`)
  assert.match(el.$('.flow-card .fx-title').text(), /Second/)
  assert.match(el.$('.dz-walk').text(), /2 of 2/)
  el.$('.dz-walk').button(en.flow.walk2.prev).click()
  assert.deepEqual(c.calls.at(-1), ['flowListGo', 0])
  el.button(en.flow.one.backList).click()
  assert.deepEqual(c.calls.at(-1), ['flowListBack'])
  // a point of its own opened from a list: the same, even while its detail is read
  const solo = logic.pointList([{ key: 'task:gone', title: 'Gone' }, { key: 'task:a', title: 'First' }], 'task:gone', { page: 'start', ui: {} })
  const sc = recorder()
  const wait = mount(html`<${FlowPage} s=${flowState({ work: rows, ui: { flowView: 'solo', flowSolo: { key: 'task:gone', file: null }, flowList: solo } })} c=${sc} />`)
  wait.button(en.flow.one.backList).click()
  assert.deepEqual(sc.calls.at(-1), ['flowListBack'])
  // the list let go (another point in front): Back to the overview and the queue's walk again
  const other = mount(html`<${FlowPage} s=${flowState({ work: rows, ui: pointAt('task:a', { flowList }) })} c=${recorder()} />`)
  assert.ok(other.button(en.flow.point.back))
  assert.equal(other.button(en.flow.one.backList), null)
})

test('the task check in Work through opens a task through peek, the walk over its rows', () => {
  const t = task('a', { title: 'First', review: { verdict: 'close', reason: 'All steps are done.', confidence: 'high' } })
  const u = task('b', { title: 'Second', review: { verdict: 'stale', reason: 'Nothing moved.', confidence: 'high' } })
  const base = flowState({ work: [t, u], ui: { flowView: 'check', rvPicked: [], rvFilter: 'all', rvSort: null } })
  const s = { ...base, model: { ...base.model, review: { keys: ['task:a', 'task:b'], last: { reviewed_at: '2026-10-09T08:00:00' } } } }
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${s} c=${c} />`)
  const open = el.$$('.c-task .info-open')
  assert.equal(open.length, 2, 'the check lists the tasks')
  open[1].click()
  const call = c.calls.at(-1)
  assert.deepEqual(call.slice(0, 2), ['peek', 'task:b'], 'peek, which opens the one view where Work through is on')
  assert.deepEqual(call[3].map(e => e.key), ['task:a', 'task:b'], 'with the rows of the check as its list')
})

test('the fields change in place what the detail column changed: Area and Urgency of an inbox item, Prio of a task', async () => {
  const q = ask('20261009-0900-a-q', { urgency: 'today', area: 'Ops' })
  const c = recorder()
  // stage 4: Area on top, Urgency and Prio in Details
  const el = await openDetails(mount(html`<${FlowPage} s=${{ ...flowState({ now: [q], ui: pointAt(q.key) }), boot: BOOT }} c=${c} />`))
  const area = el.$('[data-field=area] select')
  assert.ok(area, 'Area is a select on an inbox item without a task')
  assert.deepEqual(area.$$('option').map(o => o.text()), [en.areaNone, 'Ops', 'Docs'])
  pick(area, 'Docs')
  assert.deepEqual(c.calls.at(-1), ['act', 'area', { key: q.key, value: 'Docs' }])
  pick(area, '')
  assert.deepEqual(c.calls.at(-1), ['act', 'area', { key: q.key }], 'no area takes it back')
  const when = el.$('[data-field=when] select')
  assert.ok(when, 'Urgency is a select on an inbox item')
  assert.equal(el.$('[data-field=when] dt').text(), en.flow.fields.when)
  pick(when, 'now')
  assert.deepEqual(c.calls.at(-1), ['act', 'urgency', { key: q.key, value: 'now' }])
  assert.equal(el.$('[data-field=prio] select'), null, 'an inbox item has no priority of its own')
  // a task: its priority, beside what Jev or the triage said
  const tc = recorder()
  const tel = await openDetails(mount(html`<${FlowPage} s=${{ ...flowState({ work: [task('a', { priority: 'P2' })], ui: pointAt('task:a') }), boot: BOOT }} c=${tc} />`))
  const prio = tel.$('[data-field=prio] select')
  assert.ok(prio)
  pick(prio, 'P0')
  assert.deepEqual(tc.calls.at(-1), ['act', 'priority', { key: 'task:a', value: 'P0' }])
  assert.equal(tel.$('[data-field=when]'), null, 'a task has no inbox urgency')
  assert.equal(tel.$('[data-field=area] select'), null, 'a task shows its area, as the detail column did')
  // an item with a task shows the task's area; a person's page gives no area; a closed point changes nothing
  const withTask = mount(html`<${FlowPage} s=${{ ...flowState({ now: [ask('20261009-0901-b-q', { task: 'a' })], work: [task('a')], ui: pointAt('inbox:20261009-0901-b-q') }), boot: BOOT }} c=${recorder()} />`)
  assert.equal(withTask.$('[data-field=area] select'), null)
  const person = await openDetails(mount(html`<${FlowPage} s=${{ ...flowState({ now: [q], ui: pointAt(q.key) }), boot: { status: 'ok', config: { areas: ['Ops'], person: 'lena' } } }} c=${recorder()} />`))
  assert.equal(person.$('[data-field=area] select'), null, 'an area is the owner\'s to give')
  assert.ok(person.$('[data-field=when] select'), 'urgency and priority are a person\'s verbs too (access.py)')
  const details = { inbox: { x1: { status: 'ok', ver: 0, data: { id: 'x1', item: { ...ITEM, state: 'done', urgency: 'now' }, events: [] } } }, task: {}, activity: {} }
  const closed = await openDetails(mount(html`<${FlowPage} s=${{ ...flowState({ details, ui: { flowView: 'solo', flowSolo: { key: 'inbox:x1', file: null } } }), boot: BOOT }} c=${recorder()} />`))
  assert.equal(closed.$('[data-field=when] select'), null)
  assert.equal(closed.$('[data-field=when] dd').text(), en.urgency.now, 'read only, in words')
  assert.deepEqual([en.flow.fields.when, de.flow.fields.when], ['Urgency', 'Dringlichkeit'])
})

test('a task\'s team and its task check are fields: how far the team is, the next role to start, the verdict with Check again and Keep open', async () => {
  const teams = [{ id: 'build', label: 'Build', roles: [{ id: 'impl', name: 'Implement', mode: 'go' }, { id: 'review', name: 'Review', mode: 'go' }] },
    { id: 'research', label: 'Research', roles: [{ id: 'look', name: 'Look', mode: 'report' }] }]
  const t = task('a', { team: { team_id: 'build', started: 1, next_role: { id: 'review', name: 'Review' }, ready: true }, team_suggestions: ['build', 'research'],
    review: { verdict: 'stale', reason: 'Nothing moved for 30 days.', confidence: 'high', kept: false } })
  const base = flowState({ work: [t], ui: pointAt('task:a') })
  const s = { ...base, model: { ...base.model, teams } }
  const c = recorder()
  const el = await openDetails(mount(html`<${FlowPage} s=${s} c=${c} />`))
  const team = el.$('[data-field=team]')
  assert.ok(team)
  assert.match(team.text(), new RegExp(en.teamProgress('Build', 1, 2)))
  team.button(en.teamNext('Review')).click()
  assert.deepEqual(c.calls.at(-1), ['act', 'team_role', { key: 'task:a', team: 'build' }])
  team.button(en.teamStart('Research')).click()
  assert.deepEqual(c.calls.at(-1), ['act', 'team_role', { key: 'task:a', team: 'research' }])
  const check = el.$('[data-field=check]')
  assert.match(check.text(), /Nothing moved for 30 days\./)
  check.button(en.btnKeep).click()
  assert.deepEqual(c.calls.at(-1), ['keep', ['task:a']])
  check.button(en.btnCheckAgain).click()
  assert.deepEqual(c.calls.at(-1), ['review', ['task:a'], false, true])
  // an inbox item has neither; a person's page has neither (a check asks a model, a team starts agents)
  const q = await openDetails(mount(html`<${FlowPage} s=${flowState({ now: [ask('20261009-0900-a-q')], ui: pointAt('inbox:20261009-0900-a-q') })} c=${recorder()} />`))
  assert.equal(q.$('[data-field=team]'), null)
  assert.equal(q.$('[data-field=check]'), null)
  const person = await openDetails(mount(html`<${FlowPage} s=${{ ...s, boot: { status: 'ok', config: { person: 'lena' } } }} c=${recorder()} />`))
  assert.equal(person.$('[data-field=team]'), null)
  assert.equal(person.$('[data-field=check]'), null)
  assert.deepEqual([en.flow.fields.team, en.flow.fields.check], ['Team', en.reviewTitle])
})

test('what else the detail column did stands in the view: the sessions and the asks folded in under Related, Take over a tab, Back on, why it is here', async () => {
  const t = task('a', { also_inbox: [{ id: '20261009-1100-ask-c1', title: 'Is the report ready?' }], why: ['due tomorrow', 'only you'],
    adopt_candidates: [{ ref: 'surface:9', name: 'notes', workspace: 'Demo' }] })
  const sessions = { links: [{ sid: 'aa11', task: 'a', name: 'a research' }, { sid: 'bb22', task: 'a', name: 'a draft' }],
    sessions: [{ sid: 'aa11', tab: { ref: 'surface:3', name: 'a research' } }] }
  const c = recorder()
  const st = over => ({ ...flowState({ work: [t], ui: pointAt('task:a', over) }), sessions })
  const rel = mount(html`<${FlowPage} s=${st({ flowTab: 'related' })} c=${c} />`)
  const pane = rel.$('.flow-related')
  assert.match(pane.text(), new RegExp(en.taskSessions(2).replace(/[()]/g, '.')))
  pane.button(en.btnToTab).click()
  assert.deepEqual(c.calls.at(-1), ['act', 'tab_jump', { tab_ref: 'surface:3' }])
  pane.button(en.sessionResume).click()
  assert.deepEqual(c.calls.at(-1), ['act', 'session_resume', { session: 'bb22' }])
  assert.match(pane.text(), new RegExp(en.flow.one.asked))
  pane.button('Is the report ready?').click()
  assert.deepEqual(c.calls.at(-1), ['openItem', 'inbox:20261009-1100-ask-c1'])
  // a row of any kind with an ask folded in has Related
  assert.deepEqual(logic.pointTabs({ kind: 'row', row: ref('acme/app', 7, { also_inbox: [{ id: 'x', title: 'y' }] }) }, {}), ['desc', 'activity', 'related'])
  // Take over a tab: the tab already running on it, named
  const ac = recorder()
  const el = mount(html`<${FlowPage} s=${st({})} c=${ac} />`)
  ;(await moreItem(el, en.flow.one.adopt('Demo / notes'))).click()
  assert.deepEqual(ac.calls.at(-1), ['act', 'adopt', { key: 'task:a', tab_ref: 'surface:9' }])
  // why it is here, on top of Description
  assert.match(el.$('.flow-desc').text(), new RegExp(en.whyTitle))
  assert.match(el.$('.flow-desc').text(), /due tomorrow/)
  // a row of Later comes back on from its point, as from its list
  const hidden = task('h', { hidden_until: '2026-10-20', title: 'Hidden one' })
  const bc = recorder()
  const later = mount(html`<${FlowPage} s=${flowState({ hidden: [hidden], ui: { flowView: 'left', flowLeft: 'later', flowLeftAt: { id: 'task:h', i: 0 } } })} c=${bc} />`)
  ;(await moreItem(later, en.flow.notnow.back)).click()
  await tick()
  assert.deepEqual(bc.calls.at(-1), ['flowBatch', [{ verb: 'unhide', args: { key: 'task:h' } }], 'left'])
  assert.equal(de.flow.one.adopt('Demo / notes'), 'Tab Demo / notes zuordnen')
})

test('Steps: the steps a row has on its page stand in its Steps tab, two clicks as on the page, no drawer', async () => {
  const app = ref('jobs/board', 4, { title: 'Application at Example', sources: ['apps'] })
  const pages = [{ id: 'work', title: 'Work', sections: [{ id: 'apps', kind: 'list', steps: 'buttons', items: [{ index: 2, title: 'Application at Example',
    row_id: 'jobs/board#4', actions: [{ id: 'followup', label: 'Followed up' }, { id: 'declined', label: 'Turned down' }] }] }] }]
  const s = flowState({ now: [app], pages, ui: pointAt(app.key, { flowTab: 'steps' }) })
  assert.deepEqual(logic.pointTabs({ kind: 'row', row: app }, s), ['desc', 'steps', 'activity'])
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${s} c=${c} />`)
  const pane = el.$('.flow-ptabs-pane')
  assert.match(pane.text(), /Followed up/)
  pane.button('Followed up').click()
  await tick()
  pane.$$('button').find(b => b.text().includes('Followed up')).click()
  assert.deepEqual(c.calls.at(-1), ['act', 'row_action', { page: 'work', section: 'apps', index: 2, action: 'followup' }])
  // the verbs lead to the tab, never to a drawer (stage 4: Steps in More)
  ;(await moreItem(el, en.rowSteps)).click()
  assert.deepEqual(c.calls.at(-1), ['flowTab', 'steps'])
  assert.ok(!c.calls.some(x => x[0] === 'openInfo'))
})

test('nextWho: who takes a next step in words: you and the Bridge by the card\'s words, the owner by the name the config gives, anyone else capitalised', () => {
  const s = { work: { person: 'Mara' } }
  assert.equal(logic.nextWho('me', s, 'en'), en.card.who.me)
  assert.equal(logic.nextWho('bridge', s, 'de'), de.card.who.bridge)
  assert.equal(logic.nextWho('mara', s, 'en'), 'Mara', 'the owner, as cockpit.person_name spells her')
  assert.equal(logic.nextWho('lena', s, 'en'), 'Lena')
  assert.equal(logic.nextWho('Jan de Vries', s, 'en'), 'Jan de Vries')
  assert.equal(logic.nextWho('', s, 'en'), null)
  assert.equal(logic.nextWho('mara', { server: { person: 'Mara Lind' } }, 'en'), 'Mara Lind', 'by the first name of the configured one')
  // the next step box of a point says it so
  const t = task('a', { card: { title: 'Task a', next: { what: 'Send the draft', who: 'lena' } } })
  const el = mount(html`<${FlowPage} s=${flowState({ work: [t], ui: pointAt('task:a') })} c=${recorder()} />`)
  assert.match(el.$('.flow-card .flow-step').text(), /Lena/)
  assert.doesNotMatch(el.$('.flow-card .flow-step').text(), /lena/)
})

test('a GitHub issue says what it says on GitHub under Description, read only once its fold is opened', async () => {
  const issue = ref('acme/app', 7, { origin: { category: 'github', detail: 'acme/app', raw: null, ref: 'acme/app#7' } })
  const calls = []
  const c = new Proxy({}, { get: (_, p) => (p === 'then' || typeof p === 'symbol' ? undefined
    : (...a) => { calls.push([p, ...a]); return p === 'github' ? Promise.resolve({ ok: false, error: { message: 'offline' } }) : undefined }) })
  const el = mount(html`<${FlowPage} s=${flowState({ now: [issue], ui: pointAt(issue.key) })} c=${c} />`)
  const fold = el.$('.flow-desc .flow-gh-toggle')
  assert.equal(fold.text().trim(), `${en.flow.one.onGitHub} ▾`)
  assert.ok(!calls.some(x => x[0] === 'github'), 'nothing is read on the way')
  fold.click()
  await until(() => calls.some(x => x[0] === 'github'))
  assert.deepEqual(calls.find(x => x[0] === 'github'), ['github', 'acme/app#7', false])
  // a task or an inbox item has none
  const t = mount(html`<${FlowPage} s=${flowState({ work: [task('a')], ui: pointAt('task:a') })} c=${recorder()} />`)
  assert.equal(t.$('.flow-gh-toggle'), null)
  assert.equal(de.flow.one.onGitHub, 'Was auf GitHub steht')
})
