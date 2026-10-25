// SPDX-License-Identifier: MIT
// Tests of what the files view says about the tasks its queue leaves out (scripts/web/files.js queueLeftOut and
// views/dossier.js), no npm dependencies.
//
//   node --test scripts/tests/bridge_cockpit_files_count.test.mjs
//
// The active tasks and streams (doing or review) that stand outside the queue, by why: resting, dropped, waiting
// with nothing that asks about them, deferred, of another area, not pinned. One line under where the file stands,
// a list to open each, every area again with one click, and the empty view naming the same reasons.
import test from 'node:test'
import assert from 'node:assert/strict'
import { cockpitState, loadCockpit, mount, recorder } from './cockpit_render.mjs'

const { html, views, text, logic } = await loadCockpit()
const en = text.TABLES.en
const de = text.TABLES.de
const tick = () => new Promise(resolve => setTimeout(resolve, 20))

// a fixed local "now": Friday, 9 October 2026, noon (the same moment the other suites use)
const NOW = new Date(2026, 9, 9, 12, 0, 0).getTime()

const row = (task, extra = {}) => ({ key: `task:${task}`, task, status: 'doing', bucket: 'tasks', title: `Task ${task}`,
  area: 'ACME', area_names: ['ACME'], ...extra })

/** A model with two tasks in the queue on their own, one asked about by a tab, and the ones it leaves out */
function model() {
  return {
    sections: [
      { id: 'now', rows: [row('a', { bucket: 'do' })] },
      { id: 'work', rows: [row('b', { status: 'review' }), row('o', { area: 'ORBIT', area_names: ['ORBIT'] })] },
      { id: 'later', rows: [
        row('r', { bucket: 'resting' }), row('r2', { bucket: 'resting', status: 'review' }),
        row('d', { bucket: 'drop' }),
        row('w', { bucket: 'waiting' }), row('q', { bucket: 'waiting' }),
        // an item put off names w: it puts nothing in the queue
        { key: 'inbox:1', inbox_id: '1', task: 'w', title: 'Put off', bucket: 'waiting', inbox_state: 'deferred' },
        // backlog and a task without a status never count
        row('bl', { status: 'backlog' }), row('ns', { status: null }),
      ] },
    ],
    hidden: [row('h', { hidden_until: '2026-11-02' }), row('h2', { hidden_until: null, area: 'ORBIT', area_names: ['ORBIT'] }),
      row('hb', { status: 'backlog', hidden_until: '2026-11-02' })],
    returns: [],
  }
}

const tabs = [{ ref: 't', workspace: 'ACME', state: 'needs-you', slug: 'q', name: 'asks about q' }]

/** The state as the files view sees it, under the filters of Work (components.js hands it areaScope) */
function seen(ui = {}, over = {}) {
  const s = cockpitState(NOW, { model: model(), tabs: { tabs }, sessions: { runs: [] }, ...over, ui: { page: 'briefing', workView: 'dossier', ...ui } })
  return logic.areaScope(s)
}

const counts = gaps => Object.fromEntries(gaps.groups.map(g => [g.reason, g.rows.map(x => x.slug)]))

test('the queue leaves out the resting, the dropped, the waiting and the deferred tasks, each by its reason', () => {
  const s = seen()
  const queue = views.dossier.dossierQueue(s)
  assert.deepEqual(queue.map(x => x.slug).sort(), ['a', 'b', 'o', 'q'])
  const gaps = logic.queueLeftOut(s, queue)
  assert.equal(gaps.total, 6)
  assert.deepEqual(counts(gaps), { resting: ['r', 'r2'], drop: ['d'], waiting: ['w'], deferred: ['h', 'h2'] })
  // in the order the line names them, and each deferred one with the day it comes back (null: until shown again)
  assert.deepEqual(gaps.groups.map(g => g.reason), ['resting', 'drop', 'waiting', 'deferred'])
  assert.deepEqual(gaps.groups.at(-1).rows.map(x => x.until), ['2026-11-02', null])
})

test('under the area filter the tasks of other areas count apart, so do the ones the star leaves out', () => {
  const s = seen({ area: 'ACME' })
  const gaps = logic.queueLeftOut(s, views.dossier.dossierQueue(s))
  assert.deepEqual(counts(gaps), { resting: ['r', 'r2'], drop: ['d'], waiting: ['w'], deferred: ['h'], area: ['o', 'h2'] })
  const pinned = seen({ pinnedOnly: true }, { home: { tiles: null, seen: null, pins: ['task:a'] } })
  const left = logic.queueLeftOut(pinned, views.dossier.dossierQueue(pinned))
  // the star keeps only pinned rows, so the tab asking about q no longer has a file to stand for: q counts too
  assert.deepEqual(counts(left).unpinned, ['b', 'o', 'r', 'r2', 'd', 'w', 'q', 'h', 'h2'])
  assert.equal(left.total, 9)
})

test('a queue that holds every active task leaves nothing out', () => {
  const s = seen({}, { model: { sections: [{ id: 'work', rows: [row('a'), row('bl', { status: 'backlog' })] }], hidden: [], returns: [] } })
  assert.deepEqual(logic.queueLeftOut(s, views.dossier.dossierQueue(s)), { total: 0, groups: [] })
})

test('one calm line under where the file stands names what is left out; a click lists them and each opens', async () => {
  const { DossierView, dossierQueue } = views.dossier
  const s = seen()
  const c = recorder()
  const el = mount(html`<${DossierView} s=${s} c=${c} />`)
  const line = el.$('.dz-left-line')
  assert.ok(line, 'the line')
  const n = dossierQueue(s).length
  const parts = [en.dossier.left.reason.resting(2), en.dossier.left.reason.drop(1), en.dossier.left.reason.waiting(1), en.dossier.left.reason.deferred(2)].join(', ')
  assert.equal(line.text(), `${en.nextPos(1, n)} · ${en.dossier.left.line(6, parts)}`)
  // it stands under the head of the file, before the step
  const kids = [...el.$('article.dz-file').childNodes].filter(k => k.nodeType === 1).map(k => k.getAttribute('class') ?? '')
  assert.ok(kids.findIndex(k => k.includes('dz-left')) === kids.findIndex(k => k.includes('dz-cover')) + 1, 'right under the head')
  assert.equal(line.getAttribute('aria-expanded'), 'false')
  assert.equal(el.$('.dz-left-list'), null, 'folded until asked')
  line.click()
  await tick()
  const list = el.$('.dz-left-list')
  assert.ok(list, 'the list')
  assert.equal(el.$('.dz-left-line').getAttribute('aria-expanded'), 'true')
  const opens = list.$$('.dz-left-open')
  assert.deepEqual(opens.map(b => b.text()), ['Task r', 'Task r2', 'Task d', 'Task w', 'Task h', 'Task h2'])
  assert.ok(list.text().includes(en.dossier.left.why.resting), 'why they rest')
  assert.ok(list.text().includes(en.dossier.left.until(logic.formatDay('2026-11-02', 'en'))), 'the day a deferred one comes back')
  assert.ok(list.text().includes(en.dossier.left.untilShown), 'one put away until shown again')
  // backlog: one sentence, no count
  assert.ok(list.text().includes(en.dossier.left.backlog))
  opens[3].click()
  assert.deepEqual(c.calls.filter(x => x[0] === 'openFile'), [['openFile', 'w', 'work/tasks/w']])
  // no button for every area while no area filter is on
  assert.equal(el.button(en.home.areaClear), null)
})

test('under an area the line counts the other areas and offers every area again', async () => {
  const { DossierView } = views.dossier
  const c = recorder()
  const el = mount(html`<${DossierView} s=${seen({ area: 'ACME' })} c=${c} />`)
  assert.ok(el.$('.dz-left-line').text().includes(en.dossier.left.reason.area(2)))
  el.button(en.home.areaClear).click()
  assert.deepEqual(c.calls.filter(x => x[0] === 'setArea'), [['setArea', null]])
  el.$('.dz-left-line').click()
  await tick()
  // a task of another area names its area
  assert.ok(el.$('.dz-left-list').text().includes('ORBIT'))
})

test('the empty files view names the same reasons and lists the tasks left out', async () => {
  const { DossierView } = views.dossier
  const m = { sections: [{ id: 'later', rows: [row('r', { bucket: 'resting' }), row('d', { bucket: 'drop' })] }], hidden: [], returns: [] }
  const c = recorder()
  const el = mount(html`<${DossierView} s=${seen({}, { model: m, tabs: { tabs: [] } })} c=${c} />`)
  assert.equal(el.$('.fx-calm .fx-title').text(), en.dossier.empty)
  const parts = [en.dossier.left.reason.resting(1), en.dossier.left.reason.drop(1)].join(', ')
  const sub = el.$('.fx-calm p.muted').text()
  assert.ok(sub.includes(en.dossier.left.emptySub(parts)), 'the reasons')
  assert.ok(!sub.includes(en.dossier.left.backlog), 'the backlog sentence waits for the list')
  assert.equal(el.$('.dz-left-line').text(), en.dossier.left.line(2, parts), 'no place in an empty queue')
  el.$('.dz-left-line').click()
  await tick()
  // the backlog sentence stands once on the page, in the list
  assert.equal(el.text().split(en.dossier.left.backlog).length, 2)
  el.$$('.dz-left-open')[0].click()
  assert.deepEqual(c.calls.filter(x => x[0] === 'openFile'), [['openFile', 'r', 'work/tasks/r']])
})

test('the empty view under the star keeps its own sentence and names the reasons after it', () => {
  const { DossierView } = views.dossier
  const m = { sections: [{ id: 'work', rows: [row('a')] }], hidden: [], returns: [] }
  const s = seen({ pinnedOnly: true }, { model: m, tabs: { tabs: [] }, home: { tiles: null, seen: null, pins: [] } })
  const el = mount(html`<${DossierView} s=${s} c=${recorder()} />`)
  assert.equal(el.$('.fx-calm .fx-title').text(), en.dossier.emptyPinned)
  assert.equal(el.$('.fx-calm p.muted').text(), `${en.dossier.emptyPinnedSub} ${en.dossier.left.emptySub(en.dossier.left.reason.unpinned(1))}`)
})

test('with nothing left out the view says nothing more, and the empty view keeps its sentence', () => {
  const { DossierView } = views.dossier
  const one = mount(html`<${DossierView} s=${seen({}, { model: { sections: [{ id: 'work', rows: [row('a')] }], hidden: [], returns: [] } })} c=${recorder()} />`)
  assert.equal(one.$('.dz-left'), null)
  const none = mount(html`<${DossierView} s=${seen({}, { model: { sections: [], hidden: [], returns: [] }, tabs: { tabs: [] } })} c=${recorder()} />`)
  assert.equal(none.$('.fx-calm p.muted').text(), en.dossier.emptySub)
  assert.equal(none.$('.dz-left'), null)
})

test('a stream opens by its own folder', async () => {
  const { DossierView } = views.dossier
  const m = { sections: [{ id: 'later', rows: [row('s', { bucket: 'resting', stream: true, work_kind: 'stream' })] }], hidden: [], returns: [] }
  const c = recorder()
  const el = mount(html`<${DossierView} s=${seen({}, { model: m, tabs: { tabs: [] } })} c=${c} />`)
  el.$('.dz-left-line').click()
  await tick()
  el.$('.dz-left-open').click()
  assert.deepEqual(c.calls.filter(x => x[0] === 'openFile'), [['openFile', 's', 'work/streams/s']])
})

test('the texts of the line stand in both languages under the same keys, the German one in the words of the view', () => {
  const keys = t => Object.keys(t.dossier.left).sort()
  assert.deepEqual(keys(en), keys(de))
  assert.deepEqual(Object.keys(en.dossier.left.reason).sort(), Object.keys(de.dossier.left.reason).sort())
  assert.deepEqual(Object.keys(en.dossier.left.why).sort(), Object.keys(de.dossier.left.why).sort())
  assert.equal(de.dossier.left.line(13, '3 ruhend'), '13 weitere nicht in der Schlange: 3 ruhend')
  assert.equal(de.dossier.left.reason.drop(3), '3 verworfen')
  assert.equal(de.dossier.left.reason.deferred(4), '4 zurückgestellt')
  // no dash as punctuation, no key named: the files view is walked with the mouse
  const said = JSON.stringify([en.dossier.left, de.dossier.left], (k, v) => (typeof v === 'function' ? v(2, 'x') : v))
  assert.doesNotMatch(said, /[\u2013\u2014]|\bkeys?\b|Taste/i)
})
