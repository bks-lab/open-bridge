// SPDX-License-Identifier: MIT
// Tests of every task and stream as a file (cockpit.files_scope all; scripts/web/files.js fileReason and
// views/dossier.js), no npm dependencies.
//
//   node --test scripts/tests/bridge_cockpit_files_all.test.mjs
//
// The queue stays the ordering of the walk. Every record stands in the one list on the left; the middle holds the
// open record or the hint, never a second list (round 6d: the chips Active, Waiting, Resting, Backlog and All are
// gone). A file that rests, is dropped, put off or waits says so on its cover.
import test from 'node:test'
import assert from 'node:assert/strict'
import { cockpitState, loadCockpit, mount, recorder } from './cockpit_render.mjs'

const { html, views, text, logic } = await loadCockpit()
const en = text.TABLES.en
const de = text.TABLES.de

// a fixed local "now": Friday, 9 October 2026, noon (the same moment the other suites use)
const NOW = new Date(2026, 9, 9, 12, 0, 0).getTime()

const row = (task, extra = {}) => ({ key: `task:${task}`, task, status: 'doing', bucket: 'tasks', title: `Task ${task}`,
  area: 'ACME', area_names: ['ACME'], ...extra })

// the keys the server sends for a file (collector.files_of), nothing the page does not read
const FILE_KEYS = ['area_names', 'blocked_by', 'bucket', 'deferred', 'deferred_until', 'kind', 'priority', 'slug', 'status', 'title', 'updated']

const file = (slug, extra = {}) => ({ slug, kind: 'task', status: 'doing', area_names: ['ACME'], priority: 'P2',
  title: `Task ${slug}`, updated: '2026-10-01', blocked_by: null, bucket: 'tasks', deferred: false, deferred_until: null, ...extra })

/** A model with two tasks in the queue, the active ones it leaves out, and every file the server lists */
function model() {
  return {
    sections: [
      { id: 'work', rows: [row('a', { priority: 'P1' }), row('b', { status: 'review' })] },
      { id: 'later', rows: [row('r', { bucket: 'resting' }), row('d', { bucket: 'drop' }), row('w', { bucket: 'waiting' })] },
    ],
    hidden: [row('h', { hidden_until: '2026-11-02' })],
    returns: [],
    files: [
      file('a', { priority: 'P1' }), file('b', { status: 'review' }),
      file('r', { bucket: 'resting', blocked_by: 'the vendor' }), file('d', { bucket: 'drop' }), file('w', { bucket: 'waiting' }),
      file('h', { deferred: true, deferred_until: '2026-11-02' }),
      file('old', { status: 'backlog', bucket: null, priority: 'P3', updated: '2026-08-01' }),
      file('new', { status: 'backlog', bucket: null, priority: 'P3', updated: '2026-10-05' }),
      file('top', { status: 'backlog', bucket: null, priority: 'P0', updated: '2026-07-01' }),
      file('orbit', { status: 'backlog', bucket: null, area_names: ['ORBIT'], kind: 'stream' }),
    ],
  }
}

/** The state as the files view sees it, under the filters of Work (components.js hands it areaScope) */
function seen(ui = {}, over = {}) {
  const s = cockpitState(NOW, { model: model(), tabs: { tabs: [] }, sessions: { runs: [] }, work: { view: 'files', focus_to_files: false, files_scope: 'all' },
    ...over, ui: { page: '@files', filesWalk: true, ...ui } })
  return logic.areaScope(s)
}

const slugs = list => list.map(f => f.slug)

test('each file outside the queue names why it rests', () => {
  const by = Object.fromEntries(model().files.map(f => [f.slug, f]))
  assert.deepEqual(['r', 'd', 'w', 'h', 'old'].map(k => logic.fileReason(by[k])), ['resting', 'drop', 'waiting', 'deferred', null])
  // blocked without a resting row still rests
  assert.equal(logic.fileReason(file('x', { bucket: null, blocked_by: 'someone' })), 'resting')
  // active outside the queue with nothing that asks about it: waiting, as the line of what the queue leaves out says
  assert.equal(logic.fileReason(file('y', { bucket: 'tasks' })), 'waiting')
  // a file of the queue names none, whatever its bucket or block: a tab, a result or an item asks about it
  for (const k of ['r', 'd', 'w', 'h']) assert.equal(logic.fileReason(by[k], true), null, k)
})

test('the server sends only the keys the page reads', () => {
  for (const f of model().files) assert.deepEqual(Object.keys(f).sort(), FILE_KEYS)
  // the demo sends the same
  const demo = cockpitState(NOW).model.files
  assert.ok(demo.length > 0)
  for (const f of demo) assert.deepEqual(Object.keys(f).sort(), FILE_KEYS, f.slug)
})

const queueOf = s => views.dossier.dossierQueue(s)

test('the middle holds no second list: no shelves in any state, the list on the left is the one list', () => {
  // review 28.10.: the old chips "Active (4) Waiting (1) ..." opened a second list in the middle, counted apart from
  // the list on the left (22 against 23)
  const { DossierView } = views.dossier
  const m = { ...model(), sections: [{ id: 'later', rows: [row('r', { bucket: 'resting' })] }], hidden: [] }
  for (const [what, st] of [['the walk', seen()], ['nothing picked', seen({ filesWalk: false })], ['an area', seen({ area: 'ACME' })],
    ['an empty queue', seen({}, { model: m })], ['a record open', seen({ filesWalk: false, dossierOpen: 'top' })]]) {
    const el = mount(html`<${DossierView} s=${st} c=${recorder()} />`)
    assert.ok(!el.$('.dz-shelves') && !el.$('.dz-shelf-chip'), what)
    assert.ok(!el.button(en.dossier.shelf?.chip?.active ?? 'Active (2)'), what)
  }
  assert.equal(logic.fileShelves, undefined)
})

test('the queue of the walk names no reason on the cover of its own file', () => {
  const m = model()
  m.sections[0].rows = [row('a', { priority: 'P1', blocked_by: 'the vendor' }), row('b', { status: 'review', bucket: 'waiting' })]
  m.files[0] = file('a', { priority: 'P1', blocked_by: 'the vendor' })
  m.files[1] = file('b', { status: 'review', bucket: 'waiting' })
  const s = seen({}, { model: m })
  assert.deepEqual(queueOf(s).map(x => x.slug).sort(), ['a', 'b'])
  const el = mount(html`<${views.dossier.DossierView} s=${s} c=${recorder()} />`)
  assert.equal(el.$('.dz-cover .dz-reason'), null)
})

test('a file that rests, is dropped, put off or waits shows why as a chip on its cover', () => {
  const { DossierView } = views.dossier
  const cover = (slug, over) => mount(html`<${DossierView} s=${seen({ dossierOpen: slug }, over)} c=${recorder()} />`).$('.dz-cover .dz-reason')
  assert.equal(cover('r').text(), en.dossier.reason.resting)
  assert.equal(cover('r').getAttribute('title'), en.dossier.reasonBlocked('the vendor'))
  assert.equal(cover('d').text(), en.dossier.reason.drop)
  assert.equal(cover('w').text(), en.dossier.reason.waiting)
  assert.equal(cover('h').text(), en.dossier.reasonUntil(logic.formatDay('2026-11-02', 'en')))
  assert.equal(cover('top'), null, 'a backlog file says backlog as its status, no reason chip')
  // a closed copy of a slug borrows nothing from the open file of that slug
  assert.equal(cover('work/done/2026-10/r'), null)
  // a file of the queue that waits on nothing has none either
  assert.equal(mount(html`<${DossierView} s=${seen()} c=${recorder()} />`).$('.dz-cover .dz-reason'), null)
  // with files_scope active no cover names a reason
  const active = { work: { view: 'files', focus_to_files: false, files_scope: 'active' } }
  for (const k of ['r', 'd', 'w', 'h']) assert.equal(cover(k, active), null, k)
})

test('the line of what the queue leaves out opens its files beside the queue, with no way to chips that are gone', async () => {
  const { DossierView } = views.dossier
  const c = recorder()
  const el = mount(html`<${DossierView} s=${seen()} c=${c} />`)
  el.$('.dz-left-line').click()
  await new Promise(resolve => setTimeout(resolve, 20))
  const list = el.$('.dz-left-list')
  assert.equal(list.$$('.dz-left-shelf').length, 0)
  // every record, the backlog too, stands in the list on the left: no sentence that it does not
  assert.ok(!list.text().includes(en.dossier.left.backlog))
  list.$('.dz-left-open').click()
  assert.equal(c.calls.filter(x => x[0] === 'openFile').length, 1)
})

test('the texts stand in both languages under the same keys, German with the words of the view', () => {
  const keys = t => Object.keys(t).sort()
  assert.deepEqual(keys(en.dossier.reason), keys(de.dossier.reason))
  assert.equal(de.dossier.reason.deferred, 'zurückgestellt')
  assert.equal(en.dossier.shelf, undefined)
  const said = JSON.stringify([en.dossier.reason, de.dossier.reason, en.dossier.reasonUntil, de.dossier.reasonUntil,
    en.dossier.reasonBlocked, de.dossier.reasonBlocked], (k, v) => (typeof v === 'function' ? v(2, 'x') : v))
  assert.doesNotMatch(said, /[–—]|\bkeys?\b|Taste/i)
})

test('the demo with ?files_scope=all opens a backlog file beside the queue', () => {
  const s0 = cockpitState(NOW, { ui: { page: '@files', filesWalk: true } })
  const s = logic.areaScope({ ...s0, work: { ...s0.work, files_scope: 'all' } })
  const slug = s.model.files.find(f => f.status === 'backlog' && !queueOf(s).some(q => q.slug === f.slug)).slug
  assert.deepEqual(logic.fileOpen(s, slug, `work/tasks/${slug}`), { dossierOpen: slug })
})
