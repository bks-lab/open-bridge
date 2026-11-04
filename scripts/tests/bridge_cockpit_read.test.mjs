// SPDX-License-Identifier: MIT
// Tests of the finished AI runs in the one point view (stage 2: scripts/web/flow.js, point.js, views/flowleft.js
// ReadRow and ReadList, views/flowpoint.js and views/flowside.js ReadActs), no npm dependencies.
//
//   node --test scripts/tests/bridge_cockpit_read.test.mjs
//
// A start whose item ended after it (stage done) with something to read stands in a group of its own, Finished, to
// read, never in the queue nor among what needs you; it leaves the group once read, or read_days after it ended. Its
// card says in plain words what became of it, the run's own words folded; its verbs are Read, Analyse further and
// Make it a task; the instruction line plans them; Who works on it names the run's day. The pure helpers are imported
// as the frontend suite imports them, the views mounted as the render suite mounts them.
import test from 'node:test'
import assert from 'node:assert/strict'
import { cockpitState, loadCockpit, mount, recorder, settle as rounds } from './cockpit_render.mjs'

const { html, views, text, logic } = await loadCockpit()
const en = text.TABLES.en
const de = text.TABLES.de
const tick = () => rounds()
const until = async (ok, ms = 2000) => { for (const end = Date.now() + ms; !ok() && Date.now() < end;) await tick() }
const proto = Object.getPrototypeOf(document.createElement('div'))
if (!proto.querySelector) proto.querySelector = function querySelector(sel) { return this.$(sel) }
proto.focus ??= function focus() { document.activeElement = this }
globalThis.window ??= { addEventListener() {}, removeEventListener() {}, innerWidth: 1280 }
for (const k of ['offsetLeft', 'offsetWidth', 'scrollWidth', 'clientWidth']) Object.defineProperty(proto, k, { get: () => 0, configurable: true })

const NOW = new Date(2026, 9, 9, 12, 0, 0).getTime()
const MIN = 60000
const HOUR = 60 * MIN
const DAY = 24 * HOUR
const ID = '20261008-0900-check-the-export-a1b2'
const CHECK = en.flow.one ? 'Its check found the problem gone, and the item closed itself. Nothing to do.' : ''

const task = (slug, over = {}) => ({ key: `task:${slug}`, task: slug, title: `Task ${slug}`, status: 'doing', bucket: 'tasks',
  priority: 'P2', settle: ['done', 'not_doing'], ...over })
/** A start of the return channel (returns.py build) */
const start = (key, stage, over = {}) => ({ key, item: key.split(':')[1], title: `Run on ${key}`, mode: 'go', at_ms: NOW - 2 * DAY, stage,
  in_briefing: false, tab: null, conv: null, result: null, ...over })
const doneRun = (over = {}) => start(`inbox:${ID}`, 'done', { title: 'Check the export', ended_ms: NOW - DAY, read_ms: null,
  result: { kind: 'close', text: 'closes_when holds', key: null, at_ms: NOW - DAY, by: 'check' }, plain: CHECK, ...over })

function state({ work = [], returns = [], ui = {}, flow = {}, ...rest } = {}) {
  return {
    now: NOW, model: { sections: [{ id: 'now', rows: [] }, { id: 'give', rows: [] }, { id: 'work', rows: work }, { id: 'track', rows: [] },
      { id: 'later', rows: [] }], hidden: [], returns, pages: [] },
    tabs: { tabs: [] }, driver: { caps: null }, triage: { items: {} }, jevOrder: {},
    work: { flow: { enabled: true, drop_reasons: [], return_after_s: 20, read_days: 3, ...flow } },
    themes: { enabled: false }, details: { inbox: {}, task: {}, activity: {} },
    ui: { page: 'briefing', workView: 'flow', busy: {}, flowAt: null, flowChip: 'all', flowJump: null, flowView: 'overview', ...ui }, ...rest,
  }
}

// ---------------------------------------------------------------- the group: what stands there and what does not

test('a done start with something to read stands under Finished, to read, never in the queue nor among what needs you', () => {
  const s = state({ work: [task('a')], returns: [doneRun(), start('task:fin', 'result', { result: { kind: 'note', text: 'Result: ok' } })] })
  const parts = logic.flowParts(s)
  assert.deepEqual(parts.read.map(x => [x.id, x.group, x.kind, x.stage]), [[`start:inbox:${ID}`, 'read', 'start', 'done']])
  assert.equal(parts.read[0].row.key, `inbox:${ID}`, 'a row of its own, so its tabs, fields and the line have its key')
  assert.equal(parts.read[0].row.inbox_id, ID)
  const queue = logic.flowQueue(parts, 'all')
  assert.ok(!queue.some(x => x.id === `start:inbox:${ID}`), 'not a point of the queue')
  assert.deepEqual(parts.result.map(x => x.id), ['start:task:fin'], 'an answered one still wants a decision')
  assert.equal(parts.counts.read, 1)
  assert.ok(!logic.FLOW_YOU.includes('read'))
})

test('readFresh: a run leaves the group once read, or read_days after it ended (its start where the end is unknown)', () => {
  assert.equal(logic.readFresh(doneRun(), NOW, 3), true)
  assert.equal(logic.readFresh(doneRun({ read_ms: NOW - HOUR }), NOW, 3), false)
  assert.equal(logic.readFresh(doneRun({ ended_ms: NOW - 3 * DAY - MIN }), NOW, 3), false)
  assert.equal(logic.readFresh(doneRun({ ended_ms: null, at_ms: NOW - 2 * DAY }), NOW, 3), true)
  assert.equal(logic.readFresh(doneRun({ ended_ms: null, at_ms: NOW - 4 * DAY }), NOW, 3), false)
  const parts = logic.flowParts(state({ returns: [doneRun({ read_ms: NOW - HOUR })] }))
  assert.deepEqual(parts.read, [])
  assert.deepEqual(parts.result, [], 'a read one stands nowhere')
  assert.equal(logic.flowSettings(state({ flow: { read_days: 0 } })).read_days, 3, 'below 1 keeps the default')
  assert.equal(logic.flowSettings(state({ flow: { read_days: 7 } })).read_days, 7)
  // a done start without anything to read stays out, as before
  assert.deepEqual(logic.flowParts(state({ returns: [doneRun({ result: null, plain: 'The item was dropped.' })] })).read, [])
})

test('where a key opens: a finished run in its group, as the point view of it', () => {
  const s = state({ returns: [doneRun()] })
  assert.deepEqual(logic.flowWhere(s, `inbox:${ID}`), { view: 'read', id: `start:inbox:${ID}` })
  const patch = logic.pointOpen(s, `inbox:${ID}`)
  assert.equal(patch.flowView, 'read')
  assert.deepEqual(patch.flowReadAt, { id: `start:inbox:${ID}`, i: 0 })
  assert.deepEqual(logic.pointTabs(logic.flowParts(s).read[0]), ['desc', 'activity', 'related'])
})

test('sinceText: minutes and hours within a day, days after it, never hours above 24', () => {
  assert.equal(logic.sinceText(5 * MIN, 'en'), '5 min')
  assert.equal(logic.sinceText(3 * HOUR + 4 * MIN, 'en'), '3:04 h')
  assert.equal(logic.sinceText(143 * HOUR, 'en'), en.flow.one.days(5))
  assert.equal(logic.sinceText(30 * HOUR, 'de'), de.flow.one.days(1))
  assert.equal(de.flow.one.days(5), '5 Tagen')
})

test('the instruction line on a finished run: its key, and Run sends read, a task and analyse further through their verbs', () => {
  const s = state({ returns: [doneRun()] })
  const x = logic.flowParts(s).read[0]
  const scope = logic.instructScope(x, [], new Set(), null, s)
  assert.deepEqual([scope.point, scope.keys], [true, [`inbox:${ID}`]])
  const key = `inbox:${ID}`
  const plan = { point: true, steps: [{ op: 'read', keys: [key] }, { op: 'task', keys: [key], title: 'Watch the export' },
    { op: 'analyse', keys: [key], note: 'Look further (never send)' }, { op: 'done', keys: [key] }] }
  const { calls, skipped } = logic.instructCalls(plan, s)
  assert.deepEqual(calls, [{ verb: 'return_read', args: { key } },
    { verb: 'return_task', args: { key, title: 'Watch the export', describe: true, close: true } },
    { verb: 'return_analyse', args: { key, note: 'Look further (never send)' } }])
  assert.deepEqual(skipped, [{ step: 3, key, title: 'Check the export', why: 'not_offered' }])
  // analyse further keeps to max_running as a start does
  const full = state({ returns: [doneRun()], flow: { max_running: 1 },
    tabs: { tabs: [{ ref: 'surface:1', name: 'busy', slug: 'b', state: 'working' }] }, work: [task('b')] })
  full.tabs = { tabs: [{ ref: 'surface:1', name: 'busy', slug: 'b', state: 'working' }] }
  const capped = logic.instructCalls({ point: true, steps: [{ op: 'analyse', keys: [key], note: 'x' }] }, full)
  assert.deepEqual(capped.skipped.map(x => x.why), ['running'])
})

// ---------------------------------------------------------------- the views

const { FlowPage } = views.flow
const flowState = (over = {}) => cockpitState(NOW, state(over))
const answering = (answer = { ok: true }) => {
  const calls = []
  return new Proxy({}, { get: (_, p) => (p === 'calls' ? calls : p === 'then' || typeof p === 'symbol' ? undefined
    : (...a) => { calls.push([p, ...a]); return p === 'act' ? Promise.resolve(answer) : undefined }) })
}

test('the left column: Finished, to read under Running now with its count, a click lists the runs, a title opens one', () => {
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${flowState({ returns: [doneRun()] })} c=${c} />`)
  const row = el.$('.flow-read-row')
  assert.ok(row.text().includes(en.flow.read.label) && row.$('.flow-side-open').text() === '1')
  row.click()
  assert.deepEqual(c.calls.at(-1), ['flowRead'])
  assert.ok(!el.$$('.flow-ov-open').some(b => b.text().includes('Check the export')), 'not in the overview')
  const list = mount(html`<${FlowPage} s=${flowState({ returns: [doneRun()], ui: { flowView: 'read' } })} c=${c} />`)
  assert.ok(list.$('.flow-readlist h2').text().includes(en.flow.read.label))
  assert.ok(list.$('.flow-readlist').text().includes(CHECK.slice(0, 20)))
  // an ended item without an area: no empty column Area
  assert.ok(!list.$$('.flow-readlist th').some(th => th.text() === en.flow.list.cols.area))
  list.$('.flow-readlist .flow-ov-open').click()
  assert.deepEqual(c.calls.at(-1), ['flowReadOpen', `start:inbox:${ID}`, 0])
  // nothing to read: no row
  assert.equal(mount(html`<${FlowPage} s=${flowState()} c=${recorder()} />`).$('.flow-read-row'), null)
  assert.equal(de.flow.read.label, 'Fertig, zum Lesen')
})

test('a finished run in the one view: the plain sentence, the run\'s words folded, its day as who works on it, its tabs', () => {
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${flowState({ returns: [doneRun()], ui: { flowView: 'read', flowReadAt: { id: `start:inbox:${ID}`, i: 0 } } })} c=${c} />`)
  const card = el.$('.flow-card')
  assert.ok(card.$('.fx-kind').text().includes(en.flow.read.kind))
  assert.equal(card.$('.fx-title').text().trim(), 'Check the export')
  assert.ok(card.$('.flow-answer').text().includes(CHECK.slice(0, 30)))
  assert.ok(!card.$('.flow-answer').text().includes('closes_when'))
  assert.equal(card.$('.flow-raw summary').text(), en.flow.read.raw)
  assert.ok(card.$('.flow-raw').text().includes('closes_when holds'))
  const who = el.$('.flow-aside [data-field=who] dd').text()
  assert.ok(who.startsWith('AI run of '), who)
  assert.ok(!/\d+:\d\d h/.test(who) && !/\bdone\b/.test(who), 'never a raw stage, never hours above a day')
  assert.deepEqual(el.$$('.flow-ptabs [role=tab]').map(b => b.getAttribute('data-tab')), ['desc', 'activity', 'related'])
  // what it was asked stands on Description, no line that nothing is written
  const desc = el.$('.flow-desc')
  assert.ok(desc && desc.text().includes(en.flow.read.asked) && !desc.text().includes(en.flow.desc.none))
  el.button(en.flow.one.backList).click()
  assert.deepEqual(c.calls.at(-1), ['flowRead'])
  assert.ok(el.$('.flow-instruct'), 'the line works on it')
})

test('a finished run\'s verbs: Read strong, Analyse further and Make it a task in panels, no Later and no Drop', async () => {
  const c = answering({ ok: true, task: 'watch-the-export' })
  const s = { ...flowState({ returns: [doneRun()], ui: { flowView: 'read', flowReadAt: { id: `start:inbox:${ID}`, i: 0 } } }),
    boot: { status: 'ok', config: { areas: ['Ops', 'Docs'] } } }
  const el = mount(html`<${FlowPage} s=${s} c=${c} />`)
  const basic = el.$$('.flow-aside .verbbar-basic button')
  assert.deepEqual(basic.map(b => b.text()), [en.flow.read.read, `${en.flow.read.analyse} ▾`, `${en.flow.basic.task} ▾`])
  assert.ok(basic[0].hasClass('btn-primary'))
  assert.ok(!el.$$('.flow-aside button').some(b => b.text().startsWith(en.flow.verbs.later) || b.text().startsWith(en.flow.verbs.drop)))
  basic[0].click()
  assert.deepEqual(c.calls.find(x => x[0] === 'act'), ['act', 'return_read', { key: `inbox:${ID}` }])
  // Analyse further: a sentence of the person's, then return_analyse
  el.button(`${en.flow.read.analyse} ▾`).click()
  await tick()
  const box = el.$('.flow-aside .verbbar-panel textarea')
  assert.equal(box.value ?? box.getAttribute('value') ?? '', '', 'prefilled with nothing')
  box.value = 'Which exports came back?'
  box.dispatch('input')
  await tick()
  el.button(en.flow.read.analyseGo).click()
  await until(() => c.calls.some(x => x[1] === 'return_analyse'))
  assert.deepEqual(c.calls.find(x => x[1] === 'return_analyse'), ['act', 'return_analyse', { key: `inbox:${ID}`, note: 'Which exports came back?' }])
  // Make it a task: its title from the run, both boxes ticked, then the new task opens in the same view
  const tc = answering({ ok: true, task: 'watch-the-export' })
  const el2 = mount(html`<${FlowPage} s=${s} c=${tc} />`)
  el2.button(`${en.flow.basic.task} ▾`).click()
  await tick()
  const title = el2.$('.flow-aside .verbbar-panel input[type="text"]')
  assert.equal(title.value ?? title.getAttribute('value'), 'Check the export')
  assert.equal(el2.$$('.flow-aside .verbbar-panel input[type="checkbox"]').length, 2)
  el2.button(en.flow.read.taskGo).click()
  await until(() => tc.calls.some(x => x[0] === 'openItem'))
  assert.deepEqual(tc.calls.find(x => x[1] === 'return_task'), ['act', 'return_task', { key: `inbox:${ID}`, title: 'Check the export', describe: true, close: true }])
  assert.deepEqual(tc.calls.find(x => x[0] === 'openItem'), ['openItem', 'task:watch-the-export'])
  // without a terminal driver no run starts from here
  const nod = mount(html`<${FlowPage} s=${{ ...s, driver: { caps: ['close'] } }} c=${recorder()} />`)
  assert.ok(nod.button(`${en.flow.read.analyse} ▾`).hasAttribute('disabled'))
  assert.ok(nod.$('.flow-aside').text().includes(en.flow.read.noDriver.slice(0, 20)))
  assert.deepEqual([de.flow.read.read, de.flow.read.analyse], ['Gelesen', 'Weiter analysieren'])
})

test('Who works on it for a start that still runs reads its stage in words and days past a day', () => {
  const run = start('task:long', 'working', { at_ms: NOW - 143 * HOUR, tab: null })
  const lane = { group: 'doing', lane: true, id: 'start:task:long', kind: 'start', row: task('long'), tab: null, start: run, stage: 'working', how: 'start', title: 'x', at: run.at_ms }
  const s = flowState({ work: [task('long')], returns: [run] })
  const el = mount(html`<${views.flowside.FlowAside} x=${lane} s=${s} c=${recorder()} />`)
  const who = el.$('[data-field=who]').text()
  assert.ok(who.includes(en.flow.one.days(5)), who)
  assert.ok(!who.includes('143:'), who)
})
