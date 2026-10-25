// SPDX-License-Identifier: MIT
// Tests of every task and stream as a file (cockpit.files_scope all; scripts/web/files.js fileShelves and
// views/dossier.js), no npm dependencies.
//
//   node --test scripts/tests/bridge_cockpit_files_all.test.mjs
//
// The queue stays the ordering at the top. Behind it the chips Active, Waiting, Resting, Backlog and All, each
// with its count, list the files the server sends (model.files) sorted by status, priority and last change, and
// each opens like a file of the queue does. A file that rests, is dropped, put off or waits says so on its cover.
// The line of what the queue leaves out leads to the chips, and the area filter keeps its way back to every area.
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
    ...over, ui: { page: 'briefing', workView: 'dossier', ...ui } })
  return logic.areaScope(s)
}

const slugs = list => list.map(f => f.slug)

test('each file outside the queue stands on one shelf by its status and bucket, and names why it rests', () => {
  const by = Object.fromEntries(model().files.map(f => [f.slug, f]))
  assert.deepEqual(['r', 'd', 'w', 'h', 'old'].map(k => logic.fileShelf(by[k])), ['resting', 'resting', 'waiting', 'resting', 'backlog'])
  assert.deepEqual(['r', 'd', 'w', 'h', 'old'].map(k => logic.fileReason(by[k])), ['resting', 'drop', 'waiting', 'deferred', null])
  // blocked without a resting row still rests
  assert.equal(logic.fileReason(file('x', { bucket: null, blocked_by: 'someone' })), 'resting')
  // active outside the queue with nothing that asks about it: waiting, as the line of what the queue leaves out says
  assert.equal(logic.fileReason(file('y', { bucket: 'tasks' })), 'waiting')
  // a file of the queue is active, whatever its bucket or block: a tab, a result or an item asks about it
  for (const k of ['r', 'd', 'w', 'h']) {
    assert.equal(logic.fileShelf(by[k], true), 'active', k)
    assert.equal(logic.fileReason(by[k], true), null, k)
  }
  assert.equal(logic.fileShelf(by.old, true), 'backlog')
})

test('the server sends only the keys the page reads', () => {
  for (const f of model().files) assert.deepEqual(Object.keys(f).sort(), FILE_KEYS)
  // the demo sends the same
  const demo = cockpitState(NOW).model.files
  assert.ok(demo.length > 0)
  for (const f of demo) assert.deepEqual(Object.keys(f).sort(), FILE_KEYS, f.slug)
})

const queueOf = s => views.dossier.dossierQueue(s)

test('the shelves count what they hold, sorted by status, priority and last change', () => {
  const s = seen()
  const sh = logic.fileShelves(s, queueOf(s))
  assert.deepEqual(Object.keys(sh.lists), ['active', 'waiting', 'resting', 'backlog', 'all'])
  assert.deepEqual(slugs(sh.lists.active), ['a', 'b'])
  assert.deepEqual(slugs(sh.lists.waiting), ['w'])
  // the same status, priority and day of change: by slug
  assert.deepEqual(slugs(sh.lists.resting), ['d', 'h', 'r'])
  // P0 first, then P2, then the newer of two P3
  assert.deepEqual(slugs(sh.lists.backlog), ['top', 'orbit', 'new', 'old'])
  // doing before review before backlog
  assert.deepEqual(slugs(sh.lists.all), ['a', 'd', 'h', 'r', 'w', 'b', 'top', 'orbit', 'new', 'old'])
  assert.equal(sh.lists.all.length, 10)
  assert.equal(sh.elsewhere, 0)
})

test('the shelves split by the queue: Active is the queue, Waiting and Resting count what the line names', () => {
  // a file of the queue waits on someone else, another is blocked: both stay Active, the queue asks about them
  const m = model()
  m.sections[0].rows = [row('a', { priority: 'P1', blocked_by: 'the vendor' }), row('b', { status: 'review', bucket: 'waiting' })]
  m.files[0] = file('a', { priority: 'P1', blocked_by: 'the vendor' })
  m.files[1] = file('b', { status: 'review', bucket: 'waiting' })
  const s = seen({}, { model: m })
  const queue = queueOf(s)
  assert.deepEqual(queue.map(x => x.slug).sort(), ['a', 'b'])
  const sh = logic.fileShelves(s, queue)
  assert.deepEqual(slugs(sh.lists.active), ['a', 'b'])
  assert.deepEqual(slugs(sh.lists.waiting), ['w'])
  // the same numbers as the line of what the queue leaves out
  const gaps = Object.fromEntries(logic.queueLeftOut(s, queue).groups.map(g => [g.reason, g.rows.length]))
  assert.equal(sh.lists.waiting.length, gaps.waiting ?? 0)
  assert.equal(sh.lists.resting.length, (gaps.resting ?? 0) + (gaps.drop ?? 0) + (gaps.deferred ?? 0))
  // and the cover of the queue's file names no reason against its place in the queue
  const el = mount(html`<${views.dossier.DossierView} s=${s} c=${recorder()} />`)
  assert.equal(el.$('.dz-cover .dz-reason'), null)
})

test('under an area the shelves hold that area only and count the rest as elsewhere', () => {
  const s = seen({ area: 'ACME' })
  const sh = logic.fileShelves(s, queueOf(s))
  assert.equal(sh.lists.all.length, 9)
  assert.ok(!slugs(sh.lists.backlog).includes('orbit'))
  assert.equal(sh.elsewhere, 1)
})

test('with files_scope active, or a server that sends no list, the view shows no shelves', () => {
  const { DossierView } = views.dossier
  const off = seen({}, { work: { view: 'files', focus_to_files: false, files_scope: 'active' } })
  assert.equal(logic.filesAll(off), false)
  assert.equal(mount(html`<${DossierView} s=${off} c=${recorder()} />`).$('.dz-shelves'), null)
  const m = model()
  delete m.files
  const old = seen({}, { model: m })
  assert.equal(logic.filesAll(old), false)
  assert.equal(mount(html`<${DossierView} s=${old} c=${recorder()} />`).$('.dz-shelves'), null)
})

test('behind the queue the chips name their counts, a click picks one, and a file opens like the queue opens it', () => {
  const { DossierView } = views.dossier
  const c = recorder()
  const el = mount(html`<${DossierView} s=${seen()} c=${c} />`)
  // the queue stays on top: the file of the queue first, the shelves after it
  const kids = [...el.$('.dz-page').childNodes].filter(k => k.nodeType === 1).map(k => k.getAttribute('class') ?? '')
  assert.ok(kids.findIndex(k => k.includes('dz-file')) < kids.findIndex(k => k.includes('dz-shelves')), 'queue first')
  const chips = el.$$('.dz-shelf-chip')
  const sh = en.dossier.shelf
  assert.deepEqual(chips.map(b => b.text()), [`${sh.chip.active} (2)`, `${sh.chip.waiting} (1)`, `${sh.chip.resting} (3)`,
    `${sh.chip.backlog} (4)`, `${sh.chip.all} (10)`])
  assert.ok(chips.every(b => b.getAttribute('aria-pressed') === 'false'), 'none picked yet')
  assert.equal(el.$('.dz-shelf-list'), null, 'no list until a chip is picked')
  chips[3].click()
  assert.deepEqual(c.calls.filter(x => x[0] === 'setFileShelf'), [['setFileShelf', 'backlog']])

  const c2 = recorder()
  const picked = mount(html`<${DossierView} s=${seen({ fileShelf: 'backlog' })} c=${c2} />`)
  assert.equal(picked.$$('.dz-shelf-chip')[3].getAttribute('aria-pressed'), 'true')
  const opens = picked.$$('.dz-shelf-open')
  assert.deepEqual(opens.map(b => b.text()), slugs(logic.fileShelves(seen(), queueOf(seen())).lists.backlog).map(x => `Task ${x}`))
  opens[0].click()
  assert.deepEqual(c2.calls.filter(x => x[0] === 'openFile'), [['openFile', 'top', 'work/tasks/top']])
  // a picked chip folds again with a second click
  picked.$$('.dz-shelf-chip')[3].click()
  assert.deepEqual(c2.calls.filter(x => x[0] === 'setFileShelf'), [['setFileShelf', null]])
  // a stream opens by its own folder
  const all = mount(html`<${DossierView} s=${seen({ fileShelf: 'all' })} c=${c2} />`)
  all.$$('.dz-shelf-open').find(b => b.text() === 'Task orbit').click()
  assert.deepEqual(c2.calls.filter(x => x[0] === 'openFile').at(-1), ['openFile', 'orbit', 'work/streams/orbit'])
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

test('the line of what the queue leaves out leads to the chips and drops its backlog sentence', async () => {
  const { DossierView } = views.dossier
  const c = recorder()
  const el = mount(html`<${DossierView} s=${seen()} c=${c} />`)
  el.$('.dz-left-line').click()
  await new Promise(resolve => setTimeout(resolve, 20))
  const list = el.$('.dz-left-list')
  assert.ok(!list.text().includes(en.dossier.left.backlog), 'the backlog has its chip now')
  const links = list.$$('.dz-left-shelf')
  assert.ok(links.length >= 3)
  for (const b of links) b.click()
  const calls = c.calls.filter(x => x[0] === 'setFileShelf')
  const to = calls.map(x => x[1])
  assert.ok(to.includes('resting') && to.includes('waiting') && to.includes('backlog'), String(to))
  // from the line the chips come into view: the call asks for that
  assert.ok(calls.every(x => x[2] === true), JSON.stringify(calls))
  assert.ok(list.text().includes(en.dossier.left.toBacklog(4)))
})

test('under an area the shelves keep the way back to every area', () => {
  const { DossierView } = views.dossier
  const c = recorder()
  const el = mount(html`<${DossierView} s=${seen({ area: 'ACME' })} c=${c} />`)
  const shelves = el.$('.dz-shelves')
  assert.ok(shelves.text().includes(en.dossier.shelf.elsewhere(1, 'ACME')))
  shelves.$$('button').find(b => b.text() === en.home.areaClear).click()
  assert.deepEqual(c.calls.filter(x => x[0] === 'setArea'), [['setArea', null]])
})

test('the empty queue still shows the shelves', () => {
  const { DossierView } = views.dossier
  const m = { ...model(), sections: [{ id: 'later', rows: [row('r', { bucket: 'resting' })] }], hidden: [] }
  const el = mount(html`<${DossierView} s=${seen({}, { model: m })} c=${recorder()} />`)
  assert.equal(el.$('.fx-calm .fx-title').text(), en.dossier.empty)
  assert.ok(el.$('.dz-shelves'))
})

test('a chip picked from the line comes into view and takes the focus', async () => {
  const { DossierView } = views.dossier
  const proto = Object.getPrototypeOf(globalThis.document.createElement('section'))
  const seenBy = { scroll: [], focus: [] }
  const had = { scroll: proto.scrollIntoView, focus: proto.focus }
  proto.scrollIntoView = function () { seenBy.scroll.push(this) }
  proto.focus = function () { seenBy.focus.push(this) }
  try {
    const el = mount(html`<${DossierView} s=${seen({ fileShelf: 'resting', fileShelfReveal: 1 })} c=${recorder()} />`)
    await new Promise(resolve => setTimeout(resolve, 20))
    assert.ok(seenBy.scroll.includes(el.$('.dz-shelves')), 'the shelves scroll into view')
    assert.deepEqual(seenBy.focus, [el.$$('.dz-shelf-chip')[2]])
    // a chip picked on the shelves themselves moves nothing
    seenBy.scroll.length = 0
    seenBy.focus.length = 0
    const quiet = mount(html`<${DossierView} s=${seen({ fileShelf: 'resting' })} c=${recorder()} />`)
    await new Promise(resolve => setTimeout(resolve, 20))
    assert.ok(!seenBy.scroll.includes(quiet.$('.dz-shelves')))
    assert.equal(seenBy.focus.length, 0)
  } finally {
    proto.scrollIntoView = had.scroll
    proto.focus = had.focus
  }
})

test('only the pressed chip points at the list it opens, and the shelves are named once', () => {
  const { DossierView } = views.dossier
  const none = mount(html`<${DossierView} s=${seen()} c=${recorder()} />`)
  assert.ok(none.$$('.dz-shelf-chip').every(b => b.getAttribute('aria-controls') == null))
  assert.equal(none.$$('.dz-shelves [role]').length, 0)
  assert.equal(none.$$('[aria-label]').filter(n => n.getAttribute('aria-label') === en.dossier.shelf.label).length, 1)
  const picked = mount(html`<${DossierView} s=${seen({ fileShelf: 'waiting' })} c=${recorder()} />`)
  const chips = picked.$$('.dz-shelf-chip')
  assert.deepEqual(chips.map(b => b.getAttribute('aria-controls') ?? null), [null, 'dz-shelf-list', null, null, null])
  assert.ok(picked.$('#dz-shelf-list'))
})

test('the texts stand in both languages under the same keys, German with the words of the view', () => {
  const keys = t => Object.keys(t).sort()
  assert.deepEqual(keys(en.dossier.shelf), keys(de.dossier.shelf))
  assert.deepEqual(keys(en.dossier.shelf.chip), keys(de.dossier.shelf.chip))
  assert.deepEqual(keys(en.dossier.reason), keys(de.dossier.reason))
  assert.deepEqual(Object.values(de.dossier.shelf.chip), ['Aktiv', 'Wartet', 'Ruhend', 'Backlog', 'Alle'])
  assert.equal(de.dossier.reason.deferred, 'zurückgestellt')
  const said = JSON.stringify([en.dossier.shelf, de.dossier.shelf, en.dossier.reason, de.dossier.reason,
    en.dossier.reasonUntil, de.dossier.reasonUntil, en.dossier.reasonBlocked, de.dossier.reasonBlocked,
    en.dossier.left.toShelf, de.dossier.left.toShelf],
  (k, v) => (typeof v === 'function' ? v(2, 'x') : v))
  assert.doesNotMatch(said, /[–—]|\bkeys?\b|Taste/i)
})

test('the demo with ?files_scope=all shows the shelves with its backlog, and a backlog file opens beside the queue', () => {
  const { DossierView } = views.dossier
  const s0 = cockpitState(NOW, { ui: { page: 'briefing', workView: 'dossier', fileShelf: 'backlog' } })
  const s = logic.areaScope({ ...s0, work: { ...s0.work, files_scope: 'all' } })
  const el = mount(html`<${DossierView} s=${s} c=${recorder()} />`)
  const backlog = el.$$('.dz-shelf-chip')[3].text()
  assert.match(backlog, /^Backlog \([1-9]\d*\)$/)
  assert.ok(el.$$('.dz-shelf-open').length > 0)
  // the backlog file is in no queue: it opens beside it, by its slug
  const slug = logic.fileShelves(s, queueOf(s)).lists.backlog[0].slug
  assert.deepEqual(logic.fileOpen(s, slug, `work/tasks/${slug}`), { dossierOpen: slug })
})
