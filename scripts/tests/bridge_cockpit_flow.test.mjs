// SPDX-License-Identifier: MIT
// Tests of the cockpit's Work through page (scripts/web/flow.js, views/flow.js and views/verbbar.js), no npm
// dependencies.
//
//   node --test scripts/tests/bridge_cockpit_flow.test.mjs
//
// The one queue of the page in its fixed groups, each row once, what it leaves out and why, the return card after a
// jump to a tab, the five verbs and what each sends, and the page without a terminal driver. The pure helpers are
// imported as the frontend suite imports them, the views are mounted as the render suite mounts them; what the
// controller does with a way (app.js) is read off its source, as the frontend suite reads it.
import fs from 'node:fs'
import test from 'node:test'
import assert from 'node:assert/strict'
import { cockpitState, loadCockpit, mount, recorder } from './cockpit_render.mjs'

const { html, views, text, logic, mock } = await loadCockpit()
const { FlowPage } = views.flow
const { VerbBar } = views.verbbar
const en = text.TABLES.en
const tick = () => new Promise(resolve => setTimeout(resolve, 20))
// effects run after the render; under a loaded runner 20 ms may not be enough, so wait for what the test expects
const until = async (ok, ms = 2000) => { for (const end = Date.now() + ms; !ok() && Date.now() < end;) await tick() }
// the page bar reads its active tab back with querySelector, listens for resize and measures its tabs (as in the
// aria suite): a DOM without layout says 0, so it neither folds nor moves its marker
const proto = Object.getPrototypeOf(document.createElement('div'))
if (!proto.querySelector) proto.querySelector = function querySelector(sel) { return this.$(sel) }
globalThis.window ??= { addEventListener() {}, removeEventListener() {}, innerWidth: 1280 }
for (const k of ['offsetLeft', 'offsetWidth', 'scrollWidth', 'clientWidth']) Object.defineProperty(proto, k, { get: () => 0, configurable: true })

// a fixed local "now": Friday, 9 October 2026, noon (the same moment the other suites use)
const NOW = new Date(2026, 9, 9, 12, 0, 0).getTime()
const MIN = 60000

const task = (slug, over = {}) => ({ key: `task:${slug}`, task: slug, title: `Task ${slug}`, status: 'doing', bucket: 'tasks',
  priority: 'P2', settle: ['done', 'not_doing'], ...over })
const ask = (id, over = {}) => ({ key: `inbox:${id}`, inbox_id: id, title: `Question ${id}`, art: 'ask', inbox_state: 'open',
  bucket: 'do', gate: 'only-you', settle: ['done', 'not_doing'], ...over })
const report = (id, over = {}) => ({ ...ask(id), title: `Report ${id}`, art: 'report', gate: 'free', ...over })

/** A state of the page: the rows by section, the tabs, the starts of the return channel, the ui and the rest */
function state({ now = [], work = [], later = [], hidden = [], tabs = [], returns = [], ui = {}, ...rest } = {}) {
  return {
    now: NOW, model: { sections: [{ id: 'now', rows: now }, { id: 'give', rows: [] }, { id: 'work', rows: work },
      { id: 'track', rows: [] }, { id: 'later', rows: later }], hidden, returns, briefing_badge: now.filter(logic.asksYou).length },
    tabs: { tabs }, driver: { caps: null }, triage: { items: {} }, jevOrder: {},
    work: { flow: { enabled: true, drop_reasons: ['resolves_itself', 'not_needed'], return_after_s: 20 } },
    // the themes off unless a test switches them on: the left column groups by area
    themes: { enabled: false },
    ui: { page: '@flow', busy: {}, flowAt: null, flowChip: 'all', flowJump: null, flowView: 'point', ...ui }, ...rest,
  }
}

const queueOf = (s, chip = 'all') => logic.flowQueue(logic.flowParts(s), chip)

// ---------------------------------------------------------------- the queue: groups, each row once, what it leaves out

test('flowQueue: the groups stand in a fixed order, a Jev rank only orders inside its group', () => {
  const s = state({
    now: [ask('20261009-0900-a-q1')],
    work: [task('ranked', { priority: 'P0' }), task('plain')],
    tabs: [{ ref: 'surface:5', name: 'other', state: 'needs-you', since_ms: NOW - 3 * MIN }],
    jevOrder: { work: { order: { items: [{ key: 'task:plain', rank: 1 }, { key: 'task:ranked', rank: 2 }] } } },
  })
  const q = queueOf(s)
  // doing tasks are in progress: after what needs you, before the tasks in review
  assert.deepEqual(q.map(x => x.group), ['asks', 'question', 'doing', 'doing'])
  // the rank of a task never lifts it over a question; inside its group it outweighs the priority
  assert.deepEqual(q.filter(x => x.group === 'doing').map(x => x.row.task), ['plain', 'ranked'])
  // without a rank the priority orders the tasks
  const plain = queueOf({ ...s, jevOrder: {} }).filter(x => x.group === 'doing').map(x => x.row.task)
  assert.deepEqual(plain, ['ranked', 'plain'])
  assert.deepEqual(logic.FLOW_GROUPS, ['back', 'asks', 'result', 'lost', 'question', 'doing', 'task', 'issue', 'reports'])
})

test('flowQueue: a question without a task and a task on P3 both stand in it, reports as one card at the end', () => {
  const s = state({ now: [ask('20261009-0900-a-lone'), report('20261009-0901-a-r1'), report('20261009-0902-a-r2')],
    work: [task('low', { priority: 'P3' }), task('review-one', { status: 'review', priority: null })] })
  const q = queueOf(s)
  // a task without a priority stands after the one on P3, every priority is in it
  assert.deepEqual(q.map(x => x.id), ['inbox:20261009-0900-a-lone', 'task:low', 'task:review-one', 'reports'])
  assert.equal(q[0].row.title, 'Question 20261009-0900-a-lone')
  const reports = q.at(-1)
  assert.equal(reports.kind, 'reports')
  assert.deepEqual(reports.rows.map(r => r.inbox_id), ['20261009-0901-a-r1', '20261009-0902-a-r2'])
  // the chips: what asks you, what the agents left, the tasks, the reports by their rows
  const counts = logic.flowCounts(logic.flowParts(s))
  assert.deepEqual(counts, { all: 5, you: 1, running: 1, tasks: 1, reports: 2 })
  assert.deepEqual(queueOf(s, 'tasks').map(x => x.group), ['task'])
  assert.deepEqual(queueOf(s, 'running').map(x => x.row.task), ['low'])
})

test('flowQueue: an inbox item with a task stands once, on its question card, and the task does not come again', () => {
  const s = state({ now: [ask('20261009-0900-a-q', { task: 'demo' })], work: [task('demo'), task('other')] })
  const q = queueOf(s)
  assert.deepEqual(q.map(x => x.id), ['inbox:20261009-0900-a-q', 'task:other'])
  assert.equal(q[0].task.key, 'task:demo')
  // a question asked twice in the model (two sections) stands once too
  const twice = state({ now: [ask('20261009-0900-a-q')], later: [ask('20261009-0900-a-q')] })
  assert.equal(queueOf(twice).length, 1)
})

test('flowQueue: the questions with a due day come first, then the oldest', () => {
  const s = state({ now: [ask('20261009-0900-a-new'), ask('20261001-0900-a-old'), ask('20261009-0800-a-due', { due: '2026-10-11' })] })
  assert.deepEqual(queueOf(s).map(x => x.row.inbox_id), ['20261009-0800-a-due', '20261001-0900-a-old', '20261009-0900-a-new'])
})

test('flowParts: what is put off, waits, rests, is a stream or an idea stands in leftOut with why', () => {
  const s = state({
    work: [task('stream-one', { stream: true }), task('blocked', { blocked_by: 'the vendor' }), task('kept')],
    later: [task('waits', { bucket: 'waiting' }), ask('20261009-0900-a-idea', { art: 'idea' }), task('backlog-one', { status: 'backlog', bucket: 'resting' })],
    hidden: [task('put-off', { hidden_until: '2026-10-20' })],
  })
  const parts = logic.flowParts(s)
  assert.deepEqual(queueOf(s).map(x => x.id), ['task:kept'])
  const why = Object.fromEntries(parts.leftOut.groups.map(g => [g.reason, g.rows.map(x => x.row.key)]))
  // round 4: inside a group by priority, then age; round 6 B: Later holds what is put off, waits and rests, in order
  assert.deepEqual(why, { later: ['task:put-off', 'task:waits', 'task:blocked'], stream: ['task:stream-one'],
    idea: ['task:backlog-one', 'inbox:20261009-0900-a-idea'] })
  assert.deepEqual(parts.leftOut.groups[0].rows.map(e => e.kind), ['later', 'waiting', 'resting'])
  assert.equal(parts.leftOut.groups[0].rows[0].until, '2026-10-20')
  assert.equal(parts.leftOut.total, 6)
  assert.deepEqual(parts.leftOut.groups.map(g => g.reason), logic.FLOW_LEFT_OUT.filter(k => !['watch', 'github'].includes(k)))
  // the ideas and the backlog come back only on the calm card, at most three: by rank, else the priority first
  assert.deepEqual(logic.restSuggestions(s, 3).map(r => r.key), ['task:backlog-one', 'inbox:20261009-0900-a-idea'])
  assert.deepEqual(logic.restSuggestions(s, 1).map(r => r.key), ['task:backlog-one'])
})

test('flowQueue: after a settle the next card moves up into the place by its id', () => {
  const s = state({ work: [task('a', { priority: 'P0' }), task('b', { priority: 'P1' }), task('c', { priority: 'P2' })] })
  const q = queueOf(s)
  const at = { id: q[1].id, i: 1 }
  assert.equal(q[logic.focusIndex(q, at)].row.task, 'b')
  // b is settled: the card that stood after it comes to the front of the page
  const after = queueOf(state({ work: [task('a', { priority: 'P0' }), task('c', { priority: 'P2' })] }))
  assert.equal(after[logic.focusIndex(after, at)].row.task, 'c')
  // a card that starts to ask moves into the queue without moving the one in front
  const more = queueOf(state({ now: [ask('20261009-0900-a-new')], work: [task('a', { priority: 'P0' }), task('b', { priority: 'P1' })] }))
  assert.equal(more[logic.focusIndex(more, at)].row.task, 'b')
})

test('flowParts: a running start stands only in the lane, until it asks, finishes or is lost', () => {
  const start = (stage, over = {}) => ({ key: 'task:run', item: 'run', title: 'Task run', mode: 'go', at_ms: NOW - 18 * MIN, stage,
    tab: { ref: 'surface:9' }, ...over })
  const tab = state => ({ ref: 'surface:9', name: 'run', slug: 'run', state, since_ms: NOW - 18 * MIN })
  const s = state({ work: [task('run'), task('other')], tabs: [tab('working')], returns: [start('working')] })
  let parts = logic.flowParts(s)
  assert.deepEqual(parts.lane.map(x => x.row.key), ['task:run'])
  // round 4: what runs is no point, its task not a second time
  assert.deepEqual(queueOf(s).map(x => x.id), ['task:other'])
  // the tab stops working: the start asks, as a card of the group of tabs that ask, and its tab is not listed twice
  const asks = state({ work: [task('run')], tabs: [tab('needs-you')], returns: [start('working')] })
  assert.deepEqual(queueOf(asks).map(x => [x.group, x.kind]), [['asks', 'start']])
  // an answer is a result, a start without a tab and without a word a while ago is lost (the newest first)
  parts = logic.flowParts(state({ work: [task('run'), task('gone')], returns: [start('result', { result: { text: 'Done' } }),
    start('started', { key: 'task:gone', item: 'gone', at_ms: NOW - 60 * MIN })] }))
  assert.deepEqual(parts.result.map(x => x.start.key), ['task:run'])
  assert.deepEqual(parts.lost.map(x => x.start.key), ['task:gone'])
  // a stage the page does not know yet: a quiet tab (idle) counts as finished, anything else as a tab that asks
  parts = logic.flowParts(state({ work: [task('run')], tabs: [tab('waiting')], returns: [start('idle')] }))
  assert.deepEqual(parts.result.map(x => x.stage), ['idle'])
  parts = logic.flowParts(state({ work: [task('run')], tabs: [tab('waiting')], returns: [start('pondering')] }))
  assert.deepEqual(parts.asks.map(x => x.start.key), ['task:run'])
})

test('flowParts: without a terminal driver no lane and no cards of the agents, the band is questions, tasks, reports', () => {
  const s = state({ now: [ask('20261009-0900-a-q'), report('20261009-0901-a-r')], work: [task('run'), task('other')],
    tabs: [{ ref: 'surface:5', name: 'x', state: 'needs-you' }],
    returns: [{ key: 'task:run', item: 'run', title: 'Task run', mode: 'go', at_ms: NOW - 60 * MIN, stage: 'started' }],
    driver: { caps: [] }, ui: { flowJump: { key: 'task:other', ref: 'surface:5', title: 'x', at: NOW - MIN, armed: true } } })
  const parts = logic.flowParts(s)
  assert.equal(logic.flowDriver(s), false)
  assert.deepEqual([parts.lane, parts.asks, parts.result, parts.lost], [[], [], [], []])
  assert.equal(parts.back, null)
  assert.deepEqual(queueOf(s).map(x => x.group), ['question', 'doing', 'doing', 'reports'])
})

// ---------------------------------------------------------------- the return card

test('flowArm: the return card comes only after a jump to a tab, once return_after_s went by, never on being shown alone', () => {
  const jump = { key: 'task:a', ref: 'surface:9', title: 'a', at: NOW, armed: false }
  assert.equal(logic.flowArm(null, NOW + 60000, 20), null)                         // no jump: being shown asks nothing
  assert.equal(logic.flowArm(jump, NOW + 5000, 20), jump)                          // too soon: the jump waits
  assert.deepEqual(logic.flowArm(jump, NOW + 21000, 20), { ...jump, armed: true })
  assert.equal(logic.flowArm(jump, NOW + 4 * 3600000 + 1, 20), null)              // four hours on it is forgotten
  const armed = logic.flowArm(jump, NOW + 21000, 20)
  assert.equal(logic.flowArm(armed, NOW + 30000, 20), armed)                       // armed stays armed
  // only an armed jump stands as the first card
  const s = state({ work: [task('a')], tabs: [{ ref: 'surface:9', name: 'a', slug: 'a', state: 'waiting' }] })
  assert.equal(logic.flowParts({ ...s, ui: { ...s.ui, flowJump: jump } }).back, null)
  const q = queueOf({ ...s, ui: { ...s.ui, flowJump: armed } })
  assert.deepEqual(q.map(x => [x.group, x.id]), [['back', 'back']])                // its row is not listed again
})

test('the return card: every answer forgets the jump', async () => {
  const jump = { key: 'task:a', ref: 'surface:9', title: 'a', at: NOW - 30 * MIN, armed: true }
  const s = cockpitState(NOW, { ...state({ work: [task('a')], tabs: [{ ref: 'surface:9', name: 'a', slug: 'a', state: 'waiting' }] }),
    ui: { ...state().ui, flowJump: jump } })
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${s} c=${c} />`)
  assert.match(el.$('.flow-card').text(), new RegExp(en.flow.backAsk))
  // one way back (29.10.2026: Not yet did what Runs on does, so it went)
  assert.equal(el.button(en.flow.notYet), null)
  el.button(en.flow.runsOn).click()
  assert.deepEqual(c.calls.at(-1), ['flowBack'])
  el.button(en.flow.verbs.done).click()
  await tick()
  assert.deepEqual(c.calls.find(x => x[0] === 'act'), ['act', 'settle', { keys: ['task:a'], outcome: 'done' }])
  assert.ok(c.calls.some(x => x[0] === 'flowBack'))
})

// ---------------------------------------------------------------- the verbs

test('verbsFor: a stream gets neither Done nor Drop, an approved item no start', () => {
  assert.deepEqual(logic.verbsFor(task('a')), ['do', 'advise', 'done', 'later', 'drop'])
  assert.deepEqual(logic.verbsFor(task('s', { stream: true })), ['do', 'advise', 'later'])
  assert.deepEqual(logic.verbsFor(ask('20261009-0900-a-ok', { inbox_state: 'approved' })), ['advise', 'done', 'later', 'drop'])
  assert.deepEqual(logic.verbsFor(task('n', { settle: [] })), ['do', 'advise', 'later', 'drop'])
})

test('verbsFor: an inbox item about a stream is the way a stream comes in, so it keeps Done and Drop', () => {
  const q = ask('20261009-0900-a-onb', { work_kind: 'stream', about_task: 'onb', about_kind: 'stream' })
  assert.deepEqual(logic.verbsFor(q), ['do', 'advise', 'done', 'later', 'drop'])
  assert.deepEqual(logic.flowAction('drop', q, 'Resolves itself'),
    { verb: 'settle', args: { keys: [q.key], outcome: 'not_doing', text: 'Resolves itself' } })
  // the stream's own row stays without them, and out of the queue
  assert.deepEqual(logic.verbsFor(task('onb', { stream: true, work_kind: 'stream' })), ['do', 'advise', 'later'])
})

test('the return card after a jump from a tab without an item claims nothing was settled', () => {
  const jump = { key: null, ref: 'surface:5', title: 'other', at: NOW - 30 * MIN, armed: true }
  const s = cockpitState(NOW, { ...state({ tabs: [{ ref: 'surface:5', name: 'other', state: 'waiting' }] }), ui: { ...state().ui, flowJump: jump } })
  const el = mount(html`<${FlowPage} s=${s} c=${recorder()} />`)
  assert.match(el.$('.flow-card').text(), new RegExp(en.flow.backAsk))
  assert.doesNotMatch(el.$('.flow-card').text(), new RegExp(en.flow.backGone))
  assert.ok(el.button(en.flow.runsOn))
})

test('suggestedVerb: the triage verdict, else Advise on a question and Let AI do it on a task the AI may do', () => {
  const tri = verdict => ({ verdict, doer: 'ai' })
  assert.equal(logic.suggestedVerb(task('a'), tri('close')), 'done')
  assert.equal(logic.suggestedVerb(task('a'), tri('stale')), 'drop')
  assert.equal(logic.suggestedVerb(task('a'), tri('waiting')), 'later')
  assert.equal(logic.suggestedVerb(task('a'), { verdict: 'continue', doer: 'either' }), 'do')
  assert.equal(logic.suggestedVerb(task('a'), { verdict: 'continue', doer: 'you' }), 'advise')
  assert.equal(logic.suggestedVerb(ask('20261009-0900-a-q'), null), 'advise')
  // a suggestion the row does not offer gives way: a stream is never dropped
  assert.equal(logic.suggestedVerb(task('s', { stream: true }), tri('stale')), 'advise')
})

test('flowAction: what each verb sends; Let AI do it never without a sentence, Drop never without a reason', () => {
  const t = task('a')
  const q = ask('20261009-0900-a-q')
  const other = { key: 'ref:example/repo#12', ref: 'example/repo#12', title: 'Issue', settle: ['done', 'not_doing'] }
  assert.equal(logic.flowAction('do', t, '   '), null)
  assert.deepEqual(logic.flowAction('do', t, ' Go on. '), { verb: 'do_it', args: { keys: ['task:a'], note: 'Go on.' } })
  assert.deepEqual(logic.flowAction('done', q), { verb: 'settle', args: { keys: [q.key], outcome: 'done' } })
  assert.deepEqual(logic.flowAction('later', t, '2026-10-12'), { verb: 'later', args: { key: 'task:a', until: '2026-10-12' } })
  assert.equal(logic.flowAction('drop', t, ''), null)
  assert.deepEqual(logic.flowAction('drop', t, 'No longer needed'), { verb: 'shelve', args: { key: 'task:a', reason: 'No longer needed' } })
  assert.deepEqual(logic.flowAction('drop', q, 'Resolves itself'),
    { verb: 'settle', args: { keys: [q.key], outcome: 'not_doing', text: 'Resolves itself' } })
  assert.deepEqual(logic.flowAction('drop', other, 'elsewhere'), { verb: 'settle', args: { keys: [other.key], outcome: 'not_doing', text: 'elsewhere' } })
  assert.equal(logic.flowAction('drop', task('s', { stream: true }), 'x'), null)
  // the start sentence always ends with the request for a result line
  for (const lang of ['en', 'de']) assert.match(text.TABLES[lang].flow.start.note('Write the guide'), /^Write the guide\. .*(Result|Ergebnis): /)
})

test('Drop because: without a reason nothing is sent; a picked reason or one typed goes with the verb', async () => {
  const c = recorder()
  const s = cockpitState(NOW, state())
  const el = mount(html`<${VerbBar} row=${task('a')} s=${s} c=${c} />`)
  el.button(`${en.flow.verbs.drop} ▾`).click()
  await tick()
  const send = el.button(en.flow.drop.send)
  assert.ok(send.hasAttribute('disabled'))
  send.click()
  assert.equal(c.calls.filter(x => x[0] === 'act').length, 0)
  el.button(en.flow.drop.reason.not_needed).click()
  await tick()
  el.button(en.flow.drop.send).click()
  await tick()
  assert.deepEqual(c.calls.find(x => x[0] === 'act'), ['act', 'shelve', { key: 'task:a', reason: en.flow.drop.reason.not_needed }])
})

test('Let AI do it: the field holds the start sentence, an empty field starts nothing, Start sends do_it with it', async () => {
  const c = recorder()
  const s = cockpitState(NOW, state())
  const el = mount(html`<${VerbBar} row=${task('a')} s=${s} c=${c} />`)
  el.button(`${en.flow.verbs.do} ▾`).click()
  await tick()
  const box = el.$('textarea')
  assert.equal(box.value ?? box.getAttribute('value'), en.flow.start.note('Task a'))
  box.value = ''
  box.dispatch('input')
  await tick()
  assert.ok(el.button(en.flow.start.button).hasAttribute('disabled'))
  el.button(en.flow.start.button).click()
  assert.equal(c.calls.filter(x => x[0] === 'act').length, 0)
  box.value = 'Only the tests'
  box.dispatch('input')
  await tick()
  el.button(en.flow.start.button).click()
  await tick()
  assert.deepEqual(c.calls.find(x => x[0] === 'act'), ['act', 'do_it', { keys: ['task:a'], note: 'Only the tests' }])
})

test('the verb bar: the suggested verb is the primary button, Later offers the days, Advise asks in the card', async () => {
  const c = recorder()
  const s = cockpitState(NOW, state({ triage: { items: { 'task:a': { verdict: 'close', doer: 'ai' } } } }))
  const el = mount(html`<${VerbBar} row=${task('a')} s=${s} c=${c} />`)
  assert.ok(el.button(en.flow.verbs.done).hasClass('btn-primary'))
  el.button(`${en.flow.verbs.later} ▾`).click()
  await tick()
  el.button(en.flow.later.monday).click()
  await tick()
  assert.deepEqual(c.calls.filter(x => x[0] === 'act').at(-1), ['act', 'later', { key: 'task:a', until: logic.isoDate(logic.nextMonday(NOW)) }])
  el.button(en.flow.verbs.advise).click()
  assert.deepEqual(c.calls.at(-1), ['flowAdvise', 'task:a'])
  // a stream shows neither Done nor Drop
  const stream = mount(html`<${VerbBar} row=${task('s', { stream: true })} s=${s} c=${recorder()} />`)
  assert.equal(stream.button(en.flow.verbs.done), null)
  assert.equal(stream.button(`${en.flow.verbs.drop} ▾`), null)
})

test('a card whose tab asks offers no start: the tab takes no sentence while it asks', () => {
  const s = cockpitState(NOW, state({ work: [task('run')], tabs: [{ ref: 'surface:9', name: 'run', slug: 'run', state: 'needs-you', since_ms: NOW - MIN }] }))
  const el = mount(html`<${FlowPage} s=${s} c=${recorder()} />`)
  assert.equal(el.button(`${en.flow.verbs.do} ▾`), null)
  assert.ok(el.button(en.flow.verbs.advise) && el.button(en.flow.toTab))
})

// ---------------------------------------------------------------- the page

test('the page: Work through is a view of the work tab with cockpit.flow.enabled, no tab of its own', () => {
  const { pageOrder, workViewNow } = views.nav
  // no top tab, with the switch on or off
  for (const enabled of [false, true]) assert.ok(!pageOrder({ work: { flow: { enabled } } }).includes('@flow'))
  // a view of the work tab: last in its switch, only while the page is switched on
  assert.ok(!logic.workViews(null, null, false).includes('flow'))
  assert.deepEqual(logic.workViews(null, null, true), ['due', 'flow'])
  assert.equal(logic.workViewOf('flow', null, null, false), 'due')
  assert.equal(logic.workViewOf('flow', null, null, true), 'flow')
  // cockpit.work_view may name it
  assert.equal(logic.workViewId('flow'), 'flow')
  const flow = enabled => ({ ...cockpitState(NOW).work, flow: { enabled, drop_reasons: [], return_after_s: 20 } })
  const on = cockpitState(NOW, { work: flow(true), ui: { page: 'briefing', workView: 'flow' } })
  assert.equal(workViewNow(on), 'flow')
  assert.equal(workViewNow({ ...on, work: flow(false) }), 'due')
  // the view switch names it beside the others, a click picks it
  const c = recorder()
  const sw = mount(html`<${views.day.WorkSwitch} s=${on} c=${c} />`)
  const radio = sw.$$('[role=radio]').find(b => b.text() === en.workOrder.views.flow)
  assert.ok(radio, 'the view is in the switch')
  assert.equal(radio.getAttribute('aria-checked'), 'true')
  const off = mount(html`<${views.day.WorkSwitch} s=${{ ...on, work: flow(false) }} c=${recorder()} />`)
  assert.ok(!off.$$('[role=radio]').some(b => b.text() === en.workOrder.views.flow))
  // the page bar has no tab of the page any more
  const bar = mount(html`<${views.header.PageBar} s=${on} c=${recorder()} />`)
  assert.ok(!bar.$$('[role=tab]').some(b => b.text().startsWith(en.flow.title)))
  // a stored page or a link @flow is the work tab in this view (logic.js flowPageFor)
  assert.deepEqual(logic.flowPageFor('@flow'), { page: 'briefing', view: 'flow' })
  assert.equal(logic.flowPageFor('briefing'), null)
})

test('the page on the demo data: the themes or areas on the left, the overview of all in the middle, no right column yet', () => {
  const s = cockpitState(NOW, { ui: { page: 'briefing', workView: 'flow' } })
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${s} c=${c} />`)
  // round 6 B: the right column comes with a point; the overview takes its width
  assert.ok(el.$('.flow-side') && el.$('.flow-overview') && !el.$('.flow-aside'), 'two columns')
  // no tabs over the card and no Focus or List any more, no chips and no lane
  for (const gone of ['.flow-tabs', '.flow-main-top', '.flow-chips', '.flow-lane', '.flow-card', '.flow-walk']) assert.equal(el.$(gone), null, gone)
  // level one, a table of contents: All first, marked at the level of all, then an entry per theme or area
  const mode = logic.flowMode(s)
  const every = logic.flowSides(s, logic.flowQueue(logic.flowParts(s)), mode)
  const sides = every.filter(x => x.id !== 'all')
  const items = el.$$('.flow-side-item')
  assert.equal(items.length, sides.length + 1)
  assert.match(items[0].text(), new RegExp(`${mode === 'themes' ? en.flow.side.allThemes : en.flow.side.allAreas}\\s*${every[0].open}`))
  assert.ok(items[0].hasClass('is-on'))
  assert.equal(items[0].getAttribute('aria-current'), 'true')
  assert.ok(items.slice(1).every(b => !b.hasClass('is-on') && b.getAttribute('aria-current') == null))
  items[1].click()
  assert.deepEqual(c.calls.at(-1), ['flowSide', sides[0].id])
  items[0].click()
  assert.deepEqual(c.calls.at(-1), ['flowSide', null])
  // the middle names the level and shows every point grouped
  assert.match(el.$('.flow-main-head').text(), new RegExp(mode === 'themes' ? en.flow.side.allThemes : en.flow.side.allAreas))
  assert.ok(el.$$('.flow-ov-row').length >= sides.length)
  // the overview has no tabs under a card and no instruction scope of a point
  assert.equal(el.$('.flow-ptabs'), null)
  // the head says how many points, how many run and how many are not now (round 4), and holds the view switch
  const counts = logic.flowParts(s).counts
  assert.match(el.$('.flow-head').text(), new RegExp(en.flow.count(counts.points, logic.runningOf(logic.flowParts(s)).n, counts.left)))
  assert.ok(el.$('.flow-head .work-switch'))
  // narrow: the same choice as a select, its first option the level of all
  const opts = el.$$('.flow-side-select option')
  assert.ok(!opts[0].getAttribute('value'), 'the first option has no side')
  assert.equal(opts.length, sides.length + 1)
})

const opsState = (ui = {}) => cockpitState(NOW, { ...state({ now: [ask('20261009-0900-a-q', { area: 'Ops' })], work: [task('a', { area: 'Ops' }), task('b', { area: 'Docs' })] }),
  ui: { ...state().ui, page: 'briefing', workView: 'flow', flowSide: { areas: 'a:ops' }, flowView: 'overview', flowPicked: [], ...ui } })

test('a theme entered: the left column keeps the same list, the one entered marked, All first leads back, no points on it', () => {
  const c = recorder()
  const st = opsState()
  const el = mount(html`<${FlowPage} s=${st} c=${c} />`)
  const side = el.$('.flow-side')
  const sides = logic.flowSides(st, logic.flowQueue(logic.flowParts(st)), 'areas').filter(x => x.id !== 'all')
  const items = side.$$('.flow-side-item')
  assert.equal(items.length, sides.length + 1, 'All and every area, as on level one')
  assert.match(items[0].text(), new RegExp(en.flow.side.allAreas))
  assert.ok(!items[0].hasClass('is-on'))
  items[0].click()
  assert.deepEqual(c.calls.at(-1), ['flowSide', null])
  // the area entered is marked, the others are not
  const ops = items.find(b => /Ops/.test(b.text()))
  assert.ok(ops.hasClass('is-on'))
  assert.equal(ops.getAttribute('aria-current'), 'true')
  assert.deepEqual(items.filter(b => b.hasClass('is-on')).length, 1)
  items.find(b => /Docs/.test(b.text())).click()
  assert.deepEqual(c.calls.at(-1), ['flowSide', 'a:docs'])
  // no points, no boxes, no All box and no Tick on the left: the middle has them
  for (const gone of ['.flow-pt', '.flow-pt-pick', '.flow-pt-chip', '.flow-side-back', '.flow-side-title', '.flow-side-tick', 'input[type=checkbox]']) {
    assert.ok(!side.$(gone), gone)
  }
  // the middle: the theme's name, the groups as a table with a box, a stage and an area; a title opens the point
  assert.match(el.$('.flow-main-head').text(), /Ops/)
  assert.deepEqual(el.$$('.flow-ov-group').map(h => h.text()), [en.flow.groups.you, en.flow.groups.doing])
  const rows = el.$$('.flow-ov-row')
  assert.equal(rows.length, 2)
  assert.match(rows[1].text(), /Ops/)
  rows[0].$('.flow-ov-open').click()
  assert.deepEqual(c.calls.at(-1), ['flowGo', 'inbox:20261009-0900-a-q', 0])
  rows[1].$('.flow-ov-pick').click()
  assert.deepEqual(c.calls.at(-1), ['flowPick', ['task:a'], true])
  // the stage keeps its words whole: no ellipsis in its cell
  assert.ok(!rows[1].$('.flow-ov-stage').getAttribute('class').includes('ellipsis'))
  const picked = mount(html`<${FlowPage} s=${opsState({ flowPicked: ['task:a'] })} c=${recorder()} />`)
  assert.deepEqual(picked.$$('.flow-ov-pick').map(b => b.hasAttribute('checked')), [false, true])
  assert.match(picked.$('.flow-ov-bar').text(), new RegExp(en.flow.list.ticked(1, '')))
})

test('the overview: a group has its own box, it ticks that group and no other, and goes off again', () => {
  const reps = ['20261009-1000-r1', '20261009-1000-r2'].map(id => report(id, { area: 'Ops' }))
  const groupState = ui => cockpitState(NOW, { ...state({ now: [ask('20261009-0900-a-q', { area: 'Ops' }), ...reps] }),
    ui: { ...state().ui, page: 'briefing', workView: 'flow', flowSide: { areas: 'a:ops' }, flowView: 'overview', flowPicked: [], ...ui } })
  const keys = reps.map(r => r.key)
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${groupState()} c=${c} />`)
  const reports = el.$$('.flow-ov-group').find(h => h.text() === en.flow.groups.reports)
  const box = reports.$('.flow-ov-grouppick')
  assert.equal(box.getAttribute('aria-label'), en.flow.list.pickGroup(en.flow.groups.reports))
  assert.ok(!box.hasAttribute('checked'))
  box.click()
  assert.deepEqual(c.calls.at(-1), ['flowPick', keys, true])
  // ticked, it shows it, a click takes the group out again; one row of the group ticked is not the group ticked
  const c2 = recorder()
  const on = mount(html`<${FlowPage} s=${groupState({ flowPicked: keys })} c=${c2} />`)
  const again = on.$$('.flow-ov-group').find(h => h.text() === en.flow.groups.reports).$('.flow-ov-grouppick')
  assert.ok(again.hasAttribute('checked'))
  again.click()
  assert.deepEqual(c2.calls.at(-1), ['flowPick', keys, false])
  const half = mount(html`<${FlowPage} s=${groupState({ flowPicked: [keys[0]] })} c=${recorder()} />`)
  assert.ok(!half.$$('.flow-ov-group').find(h => h.text() === en.flow.groups.reports).$('.flow-ov-grouppick').hasAttribute('checked'))
})

test('the open point: Back to overview, what is ticked, the card with its verbs, the walk on to the next theme', () => {
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${opsState({ flowView: 'point', flowAt: { id: 'task:a', i: 1 }, flowPicked: ['task:a'] })} c=${c} />`)
  assert.ok(!el.$('.flow-overview'), '.flow-overview')
  const back = el.$('.flow-back')
  assert.match(back.text(), new RegExp(en.flow.point.back))
  back.click()
  assert.deepEqual(c.calls.at(-1), ['flowOverview'])
  assert.match(el.$('.flow-main-theme').text(), /Ops/)
  // one point ticked: the line says so and leads to the overview
  assert.match(el.$('.flow-picked-line').text(), new RegExp(en.flow.point.ticked(1)))
  el.button(en.flow.point.see).click()
  assert.deepEqual(c.calls.at(-1), ['flowOverview'])
  // the card, the point marked on the left, the title of the card opens nothing
  assert.ok(el.$('.flow-card .fx-hero'))
  assert.equal(el.$('.flow-card .fx-title button'), null)
  // the left column names where the point stands: its area stays marked, no point listed there
  assert.ok(!el.$('aside .flow-pt'), 'aside .flow-pt')
  assert.equal(el.$$('.flow-side-item').find(b => /Ops/.test(b.text())).getAttribute('aria-current'), 'true')
  // the files view's walk bar: after the last point of Ops, the next area
  assert.ok(el.$('.flow-walk .dz-walk'))
  assert.match(el.$('.dz-walk-next').text(), new RegExp(en.flow.walk2.nextSide('Docs')))
  el.button(en.flow.walk2.toSide).click()
  assert.deepEqual(c.calls.at(-1), ['flowSide', 'a:docs', 'point'])
  // under the card the tabs of the point, Description chosen first; a click picks another, no detail blocks any more
  const tabs = el.$$('.flow-ptabs [role=tab]')
  assert.deepEqual(tabs.map(b => b.getAttribute('data-tab')), ['desc', 'steps', 'activity', 'related'])
  assert.equal(tabs[0].getAttribute('aria-selected'), 'true')
  tabs[2].click()
  assert.deepEqual(c.calls.at(-1), ['flowTab', 'activity'])
  assert.equal(el.$('.flow-block-head'), null)
  // nothing ticked: no line
  const none = mount(html`<${FlowPage} s=${opsState({ flowView: 'point', flowAt: { id: 'task:a', i: 1 } })} c=${recorder()} />`)
  assert.equal(none.$('.flow-picked-line'), null)
})

test('the open point carries the suggestion the overview shows: its words on the right above the buttons, its verb the strong one', () => {
  const q = 'inbox:20261009-0900-a-q'
  const themes = themesState({ suggest: { [q]: { verb: 'done', reason: 'Answered in the thread', at_ms: NOW - MIN } } })
  const s = opsState({ flowView: 'point', flowAt: { id: q, i: 0 }, flowMode: 'areas' })
  const el = mount(html`<${FlowPage} s=${{ ...s, themes }} c=${recorder()} />`)
  // the same suggestion as in the overview's table, with its half sentence of why, on the right over the buttons
  const advice = el.$('.flow-aside .flow-can-sug')
  assert.ok(advice, 'the suggestion stands on the right')
  assert.match(advice.text(), new RegExp(en.flow.list.cols.suggestion))
  assert.match(advice.text(), new RegExp(en.flow.list.verb.done))
  assert.match(advice.text(), /Answered in the thread/)
  assert.ok(!el.$('.flow-card .flow-sug'), 'not on the card')
  // the strong button is the suggested verb, not Advise, and the first of the stack
  const strong = el.$$('.flow-aside .flow-can button').filter(b => b.getAttribute('class').includes('primary')).map(b => b.text().trim())
  assert.deepEqual(strong, [en.flow.verbs.done])
  assert.equal(el.$('.flow-aside .flow-can button').text().trim(), en.flow.verbs.done)
  // without a suggestion: no line
  const plain = mount(html`<${FlowPage} s=${s} c=${recorder()} />`)
  assert.equal(plain.$('.flow-can-sug'), null)
})

test('In progress: the card shows the last lines, the field says who works on it, To tab, and Let AI go on only without a tab at work', () => {
  const busy = { ref: 'surface:21', name: 'busy', slug: 'busy', state: 'working', since_ms: NOW - 18 * MIN, last: 'Running the tests' }
  let c = recorder()
  // round 4: a task a live tab works on runs, so it opens from Running now (view run)
  let el = mount(html`<${FlowPage} s=${cockpitState(NOW, { ...state({ work: [task('busy')], tabs: [busy] }),
    ui: { ...state().ui, page: 'briefing', workView: 'flow', flowView: 'run', flowRunId: 'tab:surface:21' } })} c=${c} />`)
  const card = el.$('.flow-card')
  assert.match(card.text(), new RegExp(`${en.flow.run.label} · ${en.flow.doing.stage.working}`))
  assert.equal(card.$('.flow-who'), null, 'no box who works on it in the card')
  assert.match(el.$('.flow-aside [data-field=who]').text(), /Agent tab busy: at work, for 18 min/)
  assert.match(card.$('.fx-screen').text(), /Running the tests/)
  assert.ok(!el.$('.flow-aside .fx-screen'), 'the screen only in the card')
  // a tab at work: To tab is the strong button, View beside it, no Let AI do it
  assert.ok(el.button(en.flow.toTab).hasClass('btn-primary') && el.button(en.flow.view) && el.button(en.flow.verbs.done))
  assert.equal(el.button(`${en.flow.doing.goOn} ▾`), null)
  assert.equal(el.button(`${en.flow.verbs.do} ▾`), null)
  // no tab open: when it last moved, and Let AI go on with it
  c = recorder()
  el = mount(html`<${FlowPage} s=${cockpitState(NOW, { ...state({ work: [task('quiet', { updated: '2026-10-06' })] }), ui: { ...state().ui, page: 'briefing', workView: 'flow' } })} c=${c} />`)
  assert.match(el.$('.flow-aside [data-field=who]').text(), /Nobody works on it right now, last moved 3 days ago/)
  assert.ok(el.button(`${en.flow.doing.goOn} ▾`).hasClass('btn-primary'))
  assert.equal(el.button(en.flow.toTab), null)
})

test('Details beside the page: with the detail column open the right column of Work through moves under the middle', () => {
  // the detail column halves the page column (style.css .with-detail): three columns of Work through do not fit there
  const css = fs.readFileSync(new URL('../web/flow.css', import.meta.url), 'utf8')
  assert.match(css, /\.main\.with-detail:not\(\.layout-narrow\) \.flow-grid \{ grid-template-columns: minmax\(200px, 240px\) minmax\(0, 1fr\); \}/)
  assert.match(css, /\.main\.with-detail:not\(\.layout-narrow\) \.flow-grid > \.flow-aside \{ grid-column: 2; position: static;/)
  // and the walk bar in a middle that narrow wraps its Next onto a line of its own instead of cutting it off
  assert.match(css, /@container \(max-width: 480px\) \{ \.flow-dock \.dz-walk \{ flex-wrap: wrap;/)
})

test('Sort again at the foot of the left column where By source, which carries the triage rerun, is off (round 6 B)', () => {
  const at = (views, themes, busy = {}) => {
    const s = { ...state({ work: [task('a'), task('b')] }), themes, ui: { ...state().ui, page: 'briefing', workView: 'flow', flowView: 'overview', busy } }
    s.model.pages = [{ id: 'arbeit', title: 'Work', group: 'work', sections: [] }]
    s.work = { ...s.work, views }
    return s
  }
  for (const themes of [themesState(), { enabled: false }]) {
    const c = recorder()
    const el = mount(html`<${FlowPage} s=${cockpitState(NOW, at(['files', 'flow'], themes))} c=${c} />`)
    const b = el.$$('.flow-side .flow-side-foot button').find(x => x.text() === en.flow.side.resort)
    assert.ok(b, `Sort again with the themes ${themes.enabled ? 'on' : 'off'}`)
    assert.ok(b.hasClass('btn-ghost'))
    assert.equal(b.getAttribute('title'), en.triage.rerunTitle)
    b.click()
    assert.deepEqual(c.calls.find(x => x[0] === 'triageRun'), ['triageRun', false])
    if (themes.enabled) assert.ok(el.$('.flow-side-foot').$$('button').some(x => x.text() === en.flow.side.regroup), 'beside Order themes again')
  }
  // busy while the triage runs, and not there while By source offers its own
  const busy = mount(html`<${FlowPage} s=${cockpitState(NOW, at(['files', 'flow'], themesState(), { [logic.TRIAGE_BUSY]: true }))} c=${recorder()} />`)
  const b = busy.$$('.flow-side-foot button').find(x => x.text() === en.flow.side.resort)
  assert.ok(b.getAttribute('disabled') != null && b.getAttribute('aria-busy') === 'true')
  const all = mount(html`<${FlowPage} s=${cockpitState(NOW, at(null, themesState()))} c=${recorder()} />`)
  assert.ok(!all.$$('.flow-side button').some(x => x.text() === en.flow.side.resort), 'By source carries it')
  for (const lang of ['en', 'de']) assert.ok(text.TABLES[lang].flow.side.resort, lang)
  assert.equal(text.TABLES.de.flow.side.resort, 'Neu einordnen')
})

test('the themes: the view asks for the points without one, never twice in a render, not with the day spent or the themes off', async () => {
  const th = themesState({ assign: { 'task:a': 't000001' } })
  const base = { ...state({ work: [task('a'), task('b')] }), ui: { ...state().ui, page: 'briefing', workView: 'flow' } }
  let c = recorder()
  const el = mount(html`<${FlowPage} s=${cockpitState(NOW, { ...base, themes: th })} c=${c} />`)
  await tick()
  assert.deepEqual(c.calls.filter(x => x[0] === 'flowThemesAuto'), [['flowThemesAuto', ['task:b']]])
  // Themes beside Areas on top, the theme of the point, Order themes again
  assert.ok(el.$('.flow-side .seg'))
  assert.ok(el.$('.flow-theme-pick select'))
  assert.ok(el.button(en.flow.side.regroup))
  for (const themes of [themesState({ budget_left: 0 }), { enabled: false }]) {
    c = recorder()
    const quiet = mount(html`<${FlowPage} s=${cockpitState(NOW, { ...base, themes })} c=${c} />`)
    await tick()
    assert.equal(c.calls.filter(x => x[0] === 'flowThemesAuto').length, 0)
    if (themes.enabled === false) assert.equal(quiet.$('.flow-side .seg'), null)
  }
})

test('the page without a terminal driver: no lane and no To tab, the start hands out the commands to copy', () => {
  const base = cockpitState(NOW, { ui: { page: '@flow', flowChip: 'all' } })
  const s = { ...base, driver: { caps: [] } }
  const el = mount(html`<${FlowPage} s=${s} c=${recorder()} />`)
  assert.equal(el.$('.flow-lane'), null)
  assert.equal(el.button(en.flow.toTab), null)
  assert.match(el.text(), new RegExp(en.flow.noDriver.slice(0, 20)))
})

test('the page with nothing open: the calm card and up to three ideas to start, each with Let AI do it', () => {
  const s = cockpitState(NOW, { ...state({ later: [ask('20261009-0900-a-idea', { art: 'idea' })] }) })
  const el = mount(html`<${FlowPage} s=${s} c=${recorder()} />`)
  assert.match(el.text(), new RegExp(en.flow.rest.title))
  assert.ok(el.$('.flow-rest .verbbar'))
})

// ---------------------------------------------------------------- the words

test('the texts of the page: both languages alike, mouse first, no keyboard shortcut named anywhere', () => {
  const leaves = (v, at = '') => (typeof v === 'string' ? [[at, v]] : typeof v === 'function' ? [[at, String(v(2, 2))]]
    : Object.entries(v).flatMap(([k, x]) => leaves(x, `${at}.${k}`)))
  for (const lang of ['en', 'de']) {
    for (const [at, value] of leaves(text.TABLES[lang].flow)) {
      assert.doesNotMatch(value, /\b(alt|ctrl|cmd|shift|esc|escape|enter|shortcut|hotkey|taste|tasten|kürzel|tastatur)\b|\([a-z]\)/i, `${lang}${at}`)
    }
    for (const id of ['all', 'you', 'running', 'tasks', 'reports']) assert.ok(text.TABLES[lang].flow.chips[id], `${lang} chip ${id}`)
  }
  const de = text.TABLES.de.flow
  assert.deepEqual([de.verbs.do, de.verbs.advise, de.verbs.done, de.verbs.later, de.verbs.drop], ['Bridge macht', 'Beraten', 'Erledigt', 'Später bis', 'Weg, weil'])
  assert.equal(text.TABLES.de.workOrder.views.flow, 'Abarbeiten')
  assert.equal(de.chips.running, 'Läuft')
})

// ---------------------------------------------------------------- the agents: quiet tabs, the order, the briefs ahead

const startOf = (slug, stage, over = {}) => ({ key: `task:${slug}`, item: slug, title: `Task ${slug}`, mode: 'go', at_ms: NOW - 30 * MIN,
  stage, in_briefing: true, tab: null, result: null, ...over })

test('flowParts: a quiet start (idle) is finished, on a shell tab too; once its tab asks it asks again', () => {
  const shell = { ref: 'surface:11', name: 'zsh', state: 'shell', since_ms: NOW - 20 * MIN }
  let parts = logic.flowParts(state({ work: [task('quiet')], tabs: [shell], returns: [startOf('quiet', 'idle', { tab: { ref: 'surface:11' } })] }))
  assert.deepEqual(parts.result.map(x => [x.start.key, x.stage]), [['task:quiet', 'idle']])
  assert.deepEqual(parts.lost, [])
  // the tab asks a question now: needs-you outweighs what the server last called quiet
  const asking = { ref: 'surface:11', name: 'quiet', slug: 'quiet', state: 'needs-you', since_ms: NOW - MIN }
  parts = logic.flowParts(state({ work: [task('quiet')], tabs: [asking], returns: [startOf('quiet', 'idle', { tab: { ref: 'surface:11' } })] }))
  assert.deepEqual(parts.asks.map(x => x.start.key), ['task:quiet'])
  assert.deepEqual(parts.result, [])
})

test('flowQueue: the tasks follow the triage rank (next_rank), before a Jev view of a page and before the priority', () => {
  const s = state({
    work: [task('high', { priority: 'P0' }), task('first', { priority: 'P3' }), task('second', { priority: 'P2' })],
    triage: { items: { 'task:first': { next_rank: 1 }, 'task:second': { next_rank: 2 } } },
    jevOrder: { work: { order: { items: [{ key: 'task:second', rank: 1 }, { key: 'task:first', rank: 2 }] } } },
  })
  assert.deepEqual(queueOf(s).map(x => x.row.task), ['first', 'second', 'high'])
})

test('the lane: a tab of a session linked to a task, typed by hand, runs there and keeps its task out of the band', () => {
  const tabs = [{ ref: 'surface:12', name: 'mine', state: 'working', since_ms: NOW - 9 * MIN, last: 'Reading the tests' }]
  const sessions = { sessions: [{ id: 'aa11', task: 'mine', status: 'busy', started_ms: NOW - 12 * MIN, tab: { ref: 'surface:12', name: 'mine' } },
    { id: 'bb22', task: null, status: 'busy', tab: { ref: 'surface:13', name: 'free' } }] }
  const s = state({ work: [task('mine'), task('other')], tabs, sessions })
  const parts = logic.flowParts(s)
  assert.deepEqual(parts.lane.map(x => [x.kind, x.tab.ref, x.row?.key]), [['session', 'surface:12', 'task:mine']])
  assert.deepEqual(queueOf(s).map(x => x.id), ['task:other'])
  // a session tab that went quiet at its prompt is finished and runs no more: its task is a point again (not quiet
  // yet it asks as a point with its task); back at its shell it no longer runs either, its task is a point
  const waiting = state({ work: [task('mine')], tabs: [{ ...tabs[0], state: 'waiting', idle: true }], sessions })
  assert.deepEqual(logic.flowParts(waiting).lane, [])
  assert.deepEqual(queueOf(waiting).map(x => x.id), ['task:mine'])
  const asking = state({ work: [task('mine')], tabs: [{ ...tabs[0], state: 'waiting' }], sessions })
  assert.deepEqual([logic.flowParts(asking).lane, queueOf(asking).map(x => [x.group, x.row?.key])], [[], [['asks', 'task:mine']]])
  const quiet = state({ work: [task('mine')], tabs: [{ ...tabs[0], state: 'shell' }], sessions })
  assert.deepEqual(logic.flowParts(quiet).lane, [])
  assert.deepEqual(queueOf(quiet).map(x => x.id), ['task:mine'])
})

test('round 6: Running now holds every live session as a card, with or without a task, each once', () => {
  const tabs = [{ ref: 'surface:12', name: 'mine', state: 'working', since_ms: NOW - 9 * MIN },
    { ref: 'surface:13', name: 'free', state: 'working', since_ms: NOW - 4 * MIN },
    { ref: 'surface:14', name: 'asking', state: 'needs-you', since_ms: NOW - 2 * MIN },
    { ref: 'surface:15', name: 'ended', state: 'shell' },
    { ref: 'surface:16', name: 'own tab', slug: 'tabbed', state: 'working', since_ms: NOW - 3 * MIN },
    // quiet: still for 30 minutes with nothing asked, so the server marks it idle and it is no point (round 6 b)
    { ref: 'surface:17', name: 'quiet', state: 'waiting', idle: true, since_ms: NOW - 30 * MIN }]
  const sessions = { sessions: [
    { id: 'aa11', sid: 'aa11-full', task: 'mine', task_how: 'hand', status: 'busy', started_ms: NOW - 12 * MIN, tab: { ref: 'surface:12', name: 'mine' } },
    { id: 'bb22', sid: 'bb22-full', task: null, status: 'busy', started_ms: NOW - 5 * MIN, tab: { ref: 'surface:13', name: 'free' } },
    { id: 'cc33', sid: 'cc33-full', task: null, status: 'idle', started_ms: NOW - 6 * MIN, tab: { ref: 'surface:14', name: 'asking' } },
    { id: 'dd44', sid: 'dd44-full', task: null, status: 'idle', started_ms: NOW - 60 * MIN, tab: { ref: 'surface:15', name: 'ended' } },
    { id: 'ee55', sid: 'ee55-full', task: null, status: 'busy', started_ms: NOW - 3 * MIN, tab: { ref: 'surface:16', name: 'own tab' } },
    { id: 'ff66', sid: 'ff66-full', task: null, status: 'idle', started_ms: NOW - 40 * MIN, tab: { ref: 'surface:17', name: 'quiet' } },
    { id: 'gg77', sid: 'gg77-full', task: null, status: 'busy', started_ms: NOW - 8 * MIN, remote: true, tab: null },
    { id: 'hh88', sid: 'hh88-full', task: null, status: 'idle', started_ms: NOW - 99 * MIN, tab: { ref: 'surface:3', name: 'Control', is_control: true } }] }
  const s = state({ work: [task('mine'), task('tabbed'), task('other')], tabs, sessions })
  const parts = logic.flowParts(s)
  // the lane keeps its entries and its keys: the counts and the universe do not move
  assert.deepEqual(parts.lane.map(x => x.id).sort(), ['session:surface:12', 'tab:surface:16'])
  checkInvariant(s, 'sessions')
  // one card per live session at work: the one asking stands as its point, the ended tab, the quiet one (finished)
  // and the control session stay out; the newest first
  assert.deepEqual(parts.sessions.map(v => v.session.id), ['ee55', 'bb22', 'gg77', 'aa11'])
  const by = Object.fromEntries(parts.sessions.map(v => [v.session.id, v]))
  // a lane entry of a session's tab is that session's card, with its row for the box: never a row of its own besides
  assert.equal(by.aa11.entry.id, 'session:surface:12')
  assert.equal(by.ee55.entry.id, 'tab:surface:16')
  assert.equal(by.bb22.entry, null)
  assert.equal(by.gg77.tab, null)
  assert.deepEqual(logic.runningOf(parts).loose, [])
  assert.equal(logic.runningOf(parts).n, 4)
  assert.equal(parts.counts.sessions, 4)
  assert.ok(parts.asks.some(x => x.tab.ref === 'surface:14'))
  // a start at work in a tab without a session stays a row of its own
  const start = { key: 'task:other', item: 'other', title: 'Task other', mode: 'go', at_ms: NOW - 2 * MIN, stage: 'started', tab: { ref: 'surface:20' } }
  const s2 = state({ work: [task('other')], tabs: [{ ref: 'surface:20', name: 'run', state: 'working' }], returns: [start], sessions: { sessions: [] } })
  const p2 = logic.flowParts(s2)
  assert.deepEqual(logic.runningOf(p2).loose.map(x => x.id), ['start:task:other'])
  assert.equal(logic.runningOf(p2).n, 1)
})

test('round 6: one card per tab, the newest session of it, with the task of an older one where it has none', () => {
  const tabs = [{ ref: 'surface:30', name: 'ui tab', state: 'working', since_ms: NOW - 2 * MIN }]
  const older = { id: 'old1', sid: 'old1-full', task: 'board-ui', task_how: 'hand', task_since_ms: NOW - 600 * MIN, status: 'idle',
    started_ms: NOW - 600 * MIN, tab: { ref: 'surface:30', name: 'ui tab' }, agents: { running_count: 1, done_recent: 0, running: [] } }
  const newer = { id: 'new1', sid: 'new1-full', task: null, status: 'busy', started_ms: NOW - 2 * MIN, tab: { ref: 'surface:30', name: 'ui tab' } }
  for (const list of [[older, newer], [newer, older]]) {
    const s = state({ work: [task('board-ui')], tabs, sessions: { sessions: list } })
    const parts = logic.flowParts(s)
    assert.equal(parts.sessions.length, 1, 'one card for the tab')
    const [card] = parts.sessions
    assert.equal(card.session.id, 'new1')
    assert.deepEqual([card.session.task, card.session.task_how, card.session.sid], ['board-ui', 'hand', 'old1-full'])
    assert.equal(card.entry?.id, 'session:surface:30')
    assert.equal(logic.runningOf(parts).n, 1)
    const el = mount(html`<${FlowPage} s=${{ ...s, ui: { ...s.ui, flowView: 'running', flowPicked: [] } }} c=${recorder()} />`)
    assert.equal(el.$$('.flow-main .sess').length, 1)
  }
  // the newer one linked itself: its own task stands
  const s2 = state({ work: [task('board-ui'), task('other')], tabs, sessions: { sessions: [older, { ...newer, task: 'other', task_how: 'seen' }] } })
  const p2 = logic.flowParts(s2)
  assert.deepEqual(p2.sessions.map(v => [v.session.id, v.session.task, v.entry?.row?.key]), [['new1', 'other', 'task:other']])
})

test('round 6: without a terminal driver Running now still lists the live sessions, without their tabs', () => {
  const sessions = { sessions: [{ id: 'aa11', sid: 'aa11-full', task: 'mine', status: 'busy', started_ms: NOW - 12 * MIN, tab: { ref: 'surface:12', name: 'mine' } },
    { id: 'bb22', sid: 'bb22-full', status: 'busy', started_ms: NOW - 50 * MIN, tab: null },
    { id: 'cc33', sid: 'cc33-full', status: 'idle', started_ms: NOW - 60 * MIN, tab: null }] }
  const s = state({ work: [task('mine')], tabs: [{ ref: 'surface:12', name: 'mine', state: 'working' }], sessions, driver: { caps: [] } })
  const parts = logic.flowParts(s)
  assert.deepEqual(parts.lane, [])
  // the idle one is finished: no card of Running now
  assert.deepEqual(parts.sessions.map(v => [v.session.id, v.tab, v.entry]), [['aa11', null, null], ['bb22', null, null]])
  checkInvariant(s, 'no driver')
  const el = mount(html`<${FlowPage} s=${{ ...s, ui: { ...s.ui, flowView: 'running', flowPicked: [] } }} c=${recorder()} />`)
  assert.match(el.$('aside .flow-run-cat').text(), new RegExp(`${en.flow.run.label}\\s*2`))
  assert.equal(el.$$('.flow-main .sess').length, 2)
  assert.ok(!el.button(en.flow.toTab), 'no To tab without a driver')
  assert.ok(!el.button(en.btnToTab), 'no To tab without a driver')
  assert.match(el.$('.flow-main').text(), new RegExp(en.flow.run.noTask))
})

test('round 6: the running view shows the sessions as compact cards, a box for a task, View opens the tab in the Chat', () => {
  const tabs = [{ ref: 'surface:1', name: 'board tab', state: 'working', since_ms: NOW - 40 * MIN, last: 'Reading the board' },
    { ref: 'surface:2', name: 'loose tab', state: 'working', since_ms: NOW - 5 * MIN, last: 'Writing tests' }]
  const sessions = { sessions: [
    { id: 'a', sid: 'a-full', task: 'board-ui', task_how: 'seen', task_since_ms: NOW - 30 * MIN, status: 'busy', started_ms: NOW - 40 * MIN, tab: { ref: 'surface:1', name: 'board tab', workspace: 'Work' },
      agents: { running_count: 1, done_recent: 0, running: [{ id: 'x1', type: 'Explore', description: 'Find it', since_ms: NOW - MIN }] } },
    { id: 'b', sid: 'b-full', task: null, status: 'busy', started_ms: NOW - 5 * MIN, tab: { ref: 'surface:2', name: 'loose tab', workspace: 'Work' } }] }
  const s = state({ work: [task('board-ui', { title: 'Board UI' }), task('other')], tabs, sessions, rooms: { layout: 'workspaces' },
    ui: { flowView: 'running', flowPicked: ['task:board-ui'] } })
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${s} c=${c} />`)
  const main = el.$('.flow-main')
  assert.match(main.$('h2').text(), new RegExp(`${en.flow.run.label}\\s*2`))
  const cards = main.$$('.sess')
  assert.equal(cards.length, 2, 'one card per session')
  assert.ok(!main.$('.flow-runstrip-row'), 'the session of a lane entry is its card, not a row besides')
  const board = cards.find(x => x.text().includes('board tab'))
  const loose = cards.find(x => x.text().includes('loose tab'))
  // the task's card keeps its box for a merge, ticked; the card without a task has none and offers to link one
  const box = board.$('input[type=checkbox]')
  assert.ok(box && box.hasAttribute('checked'), 'the box of the task, ticked')
  assert.ok(!loose.$('input[type=checkbox]'), 'no box without a task')
  assert.ok(loose.$('select.sess-task-pick'), 'a task picker')
  assert.match(loose.text(), new RegExp(en.flow.run.noTask))
  assert.match(board.text(), /Writing tests|Reading the board/)
  assert.ok(!board.$('.sess-agent-list'), 'compact: the agents as a count and a lane, not a list')
  // the title jumps to the tab, View in chat opens the tab's room in the Chat, the task opens the entry in the middle
  board.$('.sess-title').click()
  assert.deepEqual(c.calls.at(-1), ['act', 'tab_jump', { tab_ref: 'surface:1' }])
  board.$$('button').find(b => b.text() === en.flow.run.inChat).click()
  assert.deepEqual(c.calls.slice(-2), [['setPage', '@chat'], ['pickRoom', { kind: 'tab', id: 'surface:1' }]])
  board.$('.flow-run-open').click()
  assert.deepEqual(c.calls.at(-1), ['flowRun', 'session:surface:1'])
  // the classic Chat has no rooms: no View in chat, View stays the overlay
  const classic = mount(html`<${FlowPage} s=${{ ...s, rooms: { layout: 'classic' } }} c=${recorder()} />`)
  assert.ok(!classic.$$('.sess button').some(b => b.text() === en.flow.run.inChat), 'no View in chat in the classic layout')
})

test('prepTargets: the next cards whose brief is missing or stale, at most n, never one the page prepared already', () => {
  const fresh = { written: 'ai', stale: false }
  const s = state({ work: [task('a', { priority: 'P0' }), task('b', { priority: 'P1', describe: fresh }), task('c', { priority: 'P2' }),
    task('d', { priority: 'P3', describe: { written: 'human', stale: true } })], describe: {} })
  const q = queueOf(s)
  // the cards right after the one in front: b has its brief, so only c is left of the two
  assert.deepEqual(logic.prepTargets(q, 0, 2, s), ['task:c'])
  assert.deepEqual(logic.prepTargets(q, 1, 2, s), ['task:c', 'task:d'])
  assert.deepEqual(logic.prepTargets(q, 0, 0, s), [])
  // a live describe view outweighs the row's: a brief written meanwhile, or one being written now
  assert.deepEqual(logic.prepTargets(q, 1, 2, { ...s, describe: { 'task:c': { key: 'task:c', ...fresh } } }), ['task:d'])
  assert.deepEqual(logic.prepTargets(q, 1, 2, { ...s, describe: { 'task:c': { key: 'task:c', running: true } } }), ['task:d'])
  // the reports card and a tab without an item have no brief to prepare
  const r = state({ now: [report('20261009-0901-a-r')], tabs: [{ ref: 'surface:5', name: 'x', state: 'needs-you' }], work: [task('z')] })
  assert.deepEqual(logic.prepTargets(queueOf(r), 0, 2, r), ['task:z'])
})

test('prepRunner: one brief at a time, each key once, a refusal ends the round and keeps the keys not sent for later', async () => {
  const sent = []
  const answers = []
  const ask = logic.prepRunner(key => new Promise(resolve => { sent.push(key); answers.push(resolve) }))
  ask(['task:b', 'task:c'])
  // the next card came up while b is written: its keys wait their turn, c only once
  ask(['task:c', 'task:d'])
  await tick()
  assert.deepEqual(sent, ['task:b'])
  answers.shift()(true)
  await tick()
  assert.deepEqual(sent, ['task:b', 'task:c'])
  answers.shift()(true)
  await tick()
  answers.shift()(true)
  await tick()
  assert.deepEqual(sent, ['task:b', 'task:c', 'task:d'])
  // once per key: what went out once never goes again on this page view
  ask(['task:b', 'task:d'])
  await tick()
  assert.equal(sent.length, 3)
  // a refusal (the hour's budget spent, a brief written meanwhile) ends the round: f is not sent now
  ask(['task:e', 'task:f'])
  await tick()
  answers.shift()(false)
  await tick()
  assert.deepEqual(sent.slice(3), ['task:e'])
  // a later card asks again: e went out once and stays out, f was never sent and goes now
  ask(['task:e', 'task:f'])
  await tick()
  assert.deepEqual(sent.slice(3), ['task:e', 'task:f'])
  answers.shift()(true)
  // a send that throws counts as a refusal and leaves the runner ready
  const thrown = []
  const loud = logic.prepRunner(async key => { thrown.push(key); throw new Error('offline') })
  loud(['task:g', 'task:h'])
  await tick()
  loud(['task:h'])
  await tick()
  assert.deepEqual(thrown, ['task:g', 'task:h'])
})

test('the page prepares the next briefs on its own when a card comes to the front, none with prep_ahead 0', async () => {
  const s = state({ work: [task('a', { priority: 'P0' }), task('b', { priority: 'P1' }), task('c', { priority: 'P2' }), task('d', { priority: 'P3' })] })
  const c = recorder()
  mount(html`<${FlowPage} s=${cockpitState(NOW, s)} c=${c} />`)
  await tick()
  const preps = c.calls.filter(x => x[0] === 'flowPrep')
  assert.deepEqual(preps, [['flowPrep', ['task:b', 'task:c']]])
  assert.equal(c.calls.filter(x => x[0] === 'act').length, 0)
  const off = recorder()
  mount(html`<${FlowPage} s=${cockpitState(NOW, { ...s, work: { flow: { ...s.work.flow, prep_ahead: 0 } } })} c=${off} />`)
  await tick()
  assert.equal(off.calls.filter(x => x[0] === 'flowPrep').length, 0)
  assert.equal(logic.flowSettings({ work: { flow: { enabled: true } } }).prep_ahead, 2)
  assert.equal(logic.flowSettings({ work: { flow: { enabled: true } } }).max_running, 4)
})

// ---------------------------------------------------------------- a tab asks: its answers on the card

const dialog = (over = {}) => ({ ref: 'surface:7', name: 'docs-merge', state: 'needs-you', since_ms: NOW - 12 * MIN,
  ask: { text: 'Delete the old page or redirect it?', hash: 'h1', options: [{ n: 1, label: 'Delete' }, { n: 2, label: 'Redirect' }] }, ...over })

test('a tab that asks: its options as buttons, a click answers the tab with the question it read, no jump', async () => {
  const c = recorder()
  const s = cockpitState(NOW, state({ tabs: [dialog()] }))
  const el = mount(html`<${FlowPage} s=${s} c=${c} />`)
  assert.match(el.$('.flow-card').text(), /Delete the old page or redirect it\?/)
  el.button('Redirect').click()
  await tick()
  assert.deepEqual(c.calls.find(x => x[0] === 'reply'), ['reply', 'tab_option', { tab_ref: 'surface:7', n: 2, seen: 'h1', name: 'docs-merge' }])
  // the card's own To tab remembers the jump; the bare jump of the answers is not there twice
  assert.equal(el.$$('button').filter(b => b.text() === en.reply.openTab).length, 0)
  el.button(en.flow.toTab).click()
  assert.equal(c.calls.at(-1)[0], 'flowJump')
})

test('a tab that was answered leaves the queue at once, the next card moves up', () => {
  const tab = dialog()
  const s = state({ tabs: [tab], work: [task('next')] })
  assert.deepEqual(queueOf(s).map(x => x.group), ['asks', 'doing'])
  const answered = { [tab.ref]: logic.answerMark(tab, 'Redirect', NOW) }
  assert.deepEqual(queueOf({ ...s, ui: { ...s.ui, answered } }).map(x => x.id), ['task:next'])
  // asked anew (another question), it is back
  const again = { ...tab, ask: { ...tab.ask, hash: 'h2' } }
  assert.deepEqual(queueOf({ ...s, tabs: { tabs: [again] }, ui: { ...s.ui, answered } }).map(x => x.group), ['asks', 'doing'])
})

test('a tab that asks: the decision guide on the card, a branch pressed through tab_option with the hash, To tab remembered', async () => {
  const tab = dialog()
  const guide = { enabled: true, entries: { [tab.ref]: { key: 'h1', state: 'needs-you', about: 'Merging the docs', where: 'Two pages say the same',
    options: [{ n: 2, label: 'Redirect it', why: 'Links stay alive' }], pick: 0, source: 'haiku', at_ms: NOW - MIN } } }
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${cockpitState(NOW, { ...state({ tabs: [tab] }), guide })} c=${c} />`)
  // folded under one button on the card, so its answers come once
  el.$$('.flow-card button').find(b => b.text() === en.flow.guide.show).click()
  await tick()
  assert.match(el.$('.flow-card').text(), /Two pages say the same/)
  el.$$('.guide-opt').find(b => b.text().includes('Redirect it')).click()
  await tick()
  el.button(text.TABLES.en.guide.press).click()
  await tick()
  assert.deepEqual(c.calls.filter(x => x[0] === 'reply').at(-1), ['reply', 'tab_option', { tab_ref: 'surface:7', n: 2, seen: 'h1', name: 'docs-merge' }])
  // one To tab on the card, the page's own that remembers the jump, so the return card asks after it
  const jumps = el.$$('button').filter(b => b.text() === en.flow.toTab || b.text() === text.TABLES.en.guide.toTab)
  assert.equal(jumps.length, 1)
  jumps[0].click()
  assert.equal(c.calls.at(-1)[0], 'flowJump')
  assert.equal(c.calls.filter(x => x[0] === 'act' && x[1] === 'tab_jump').length, 0)
})

// ---------------------------------------------------------------- finished or quiet: the result, the criteria, improve

test('a finished start: its result line once under Result, the criteria of its brief in Description, nothing ticked', () => {
  const row = task('fin', { card: { acceptance: ['The machine boots Linux', 'The backup runs'] } })
  const s = cockpitState(NOW, state({ work: [row], tabs: [{ ref: 'surface:10', name: 'fin', slug: 'fin', state: 'waiting', since_ms: NOW - 25 * MIN }],
    returns: [startOf('fin', 'result', { tab: { ref: 'surface:10' }, result: { kind: 'note', text: 'Result: driver installed, a restart is open', key: null, at_ms: null } })] }))
  const el = mount(html`<${FlowPage} s=${s} c=${recorder()} />`)
  const card = el.$('.flow-card')
  assert.equal(card.$('.flow-answer').text(), `${en.flow.result} driver installed, a restart is open`, 'the head word once')
  assert.match(el.$('.flow-ptabs [role=tabpanel]').text(), /The machine boots Linux.*The backup runs/)
  assert.doesNotMatch(el.$('.flow-ptabs [role=tabpanel]').text(), /[✓✔☑]/)
  assert.equal(el.$('.flow-ptabs').$$('input').filter(i => i.getAttribute('type') === 'checkbox').length, 0)
  assert.ok(el.button(en.flow.doneClose) && el.button(en.flow.runsOn) && el.button(`${en.flow.improve.button} ▾`))
})

test('a finished or quiet start whose item is not in the list (put off, resting) still offers a way off the queue', () => {
  const home = text.TABLES.en.home
  for (const [stage, tabs] of [['result', []], ['idle', [{ ref: 'surface:11', name: 'zsh', state: 'shell', since_ms: NOW - 20 * MIN }]]]) {
    const c = recorder()
    const s = cockpitState(NOW, state({ tabs, returns: [startOf('gone', stage, { tab: tabs.length ? { ref: 'surface:11' } : null,
      result: stage === 'result' ? { kind: 'note', text: 'Result: nothing to change', key: null, at_ms: null } : null })] }))
    const el = mount(html`<${FlowPage} s=${s} c=${c} />`)
    assert.match(el.$('.flow-card').text(), new RegExp(stage === 'result' ? 'nothing to change' : en.flow.idleSub))
    el.button(home.returnForget).click()
    assert.deepEqual(c.calls.at(-1), ['act', 'return_forget', { key: 'task:gone' }])
  }
})

test('a start that ended with a note stays a card to look at, with its note and the way back to its question', () => {
  // 28.10.: the tab closed the item with its note, and Running now showed nothing at all
  const ID = '20261028-0736-chat-bot-a1b2'
  const done = (over = {}) => ({ key: `inbox:${ID}`, item: ID, title: 'Chat bot job', mode: 'go', at_ms: NOW - 30 * MIN, stage: 'done',
    in_briefing: false, tab: null, conv: 'q0123456789', result: { kind: 'close', text: 'Result: the bot runs, nothing to change', key: null, at_ms: NOW - MIN }, ...over })
  let parts = logic.flowParts(state({ returns: [done()] }))
  assert.deepEqual(parts.result.map(x => [x.start.key, x.stage]), [[`inbox:${ID}`, 'done']])
  // ended without a word it is settled, as before
  parts = logic.flowParts(state({ returns: [done({ result: { kind: 'close', text: '', key: null, at_ms: NOW - MIN } })] }))
  assert.deepEqual(parts.result, [])
  const c = recorder()
  const s = cockpitState(NOW, state({ returns: [done()], quick: { convs: [{ id: 'q0123456789', turns: [{ q: 'what is with the bot?', a: 'x' }] }] } }))
  const el = mount(html`<${FlowPage} s=${s} c=${c} />`)
  const card = el.$('.flow-card')
  assert.match(card.text(), new RegExp(en.flow.kind.done))
  assert.match(card.$('.flow-answer').text(), /the bot runs, nothing to change/)
  el.button(en.flow.toQuestion).click()
  assert.deepEqual(c.calls.find(x => x[0] === 'openAsk'), ['openAsk', 'q0123456789'])
  // seen: taken off the list
  el.button(text.TABLES.en.home.returnForget).click()
  assert.deepEqual(c.calls.at(-1), ['act', 'return_forget', { key: `inbox:${ID}` }])
  // its question is gone from the chats (archived): no way back offered
  const gone = mount(html`<${FlowPage} s=${cockpitState(NOW, state({ returns: [done()], quick: { convs: [] } }))} c=${recorder()} />`)
  assert.ok(!gone.button(en.flow.toQuestion), 'no link to an archived question')
  // a note that asks: the card asks under the question's own head
  const asks = mount(html`<${FlowPage} s=${cockpitState(NOW, state({ returns: [done({ stage: 'asks',
    result: { kind: 'note', text: 'Question: close it?', asks: true, key: null, at_ms: NOW - MIN } })] }))} c=${recorder()} />`)
  assert.equal(asks.$('.flow-card .flow-answer').text(), `${en.flow.question} close it?`)
  for (const lang of ['en', 'de']) assert.ok(text.TABLES[lang].flow.kind.done && text.TABLES[lang].flow.toQuestion && text.TABLES[lang].flow.question)
  assert.equal(text.TABLES.de.flow.kind.done, 'Zum Ansehen')
})

// ---------------------------------------------------------------- round 6d: Close tab on every point with a tab

test('28.10.: a finished start whose item already left the list still closes its tab', () => {
  // the tab closed its item itself; under Work only To tab, View and Forget stood there (flowside.js FinishedActs)
  const ID = '20261028-0736-chat-bot-a1b2'
  const done = { key: `inbox:${ID}`, item: ID, title: 'Chat bot job', mode: 'go', at_ms: NOW - 30 * MIN, stage: 'done', in_briefing: false,
    tab: { ref: 'surface:21' }, result: { kind: 'close', text: 'Result: the bot runs, nothing to change', key: null, at_ms: NOW - MIN } }
  const tab = { ref: 'surface:21', name: 'inbox-chat-bot', item: ID, state: 'waiting', settled: 'item', behind: null, since_ms: NOW - 20 * MIN }
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${cockpitState(NOW, state({ tabs: [tab], returns: [done] }))} c=${c} />`)
  const can = el.$('.flow-aside .flow-can')
  assert.ok(can.$('.tab-close'), 'the one close of a tab')
  assert.deepEqual(can.$('.tab-close').$$('button').map(b => b.text()), [en.btnCloseTab], 'nothing open behind it: the tab alone')
  can.$('.tab-close').$$('button')[0].click()
  assert.deepEqual(c.calls.at(-1), ['act', 'tab_close', { tab_ref: 'surface:21' }])
})

test('a finished start with its task behind the tab: Done and close the tab ends both on the server, Close tab only beside it', () => {
  const row = task('fin')
  const live = { ref: 'surface:10', name: 'fin', slug: 'fin', state: 'waiting', behind: { task: 'fin', item: null }, since_ms: NOW - 25 * MIN }
  const c = recorder()
  const s = cockpitState(NOW, state({ work: [row], tabs: [live],
    returns: [startOf('fin', 'result', { tab: { ref: 'surface:10' }, result: { kind: 'note', text: 'Result: nothing to do', key: null, at_ms: null } })] }))
  const el = mount(html`<${FlowPage} s=${s} c=${c} />`)
  const can = el.$$('.flow-aside .flow-can button')
  assert.equal(can.filter(b => b.text() === en.flow.doneClose).length, 1, 'one Done')
  assert.ok(can.some(b => b.text() === en.btnCloseTabOnly))
  assert.ok(!can.some(b => b.text() === en.btnDoneCloseTab), 'the bar holds the Done')
  can.find(b => b.text() === en.flow.doneClose).click()
  assert.deepEqual(c.calls.filter(x => x[0] === 'act').at(-1), ['act', 'tab_done', { tab_ref: 'surface:10' }])
})

test('a tab card says the tab waits where it asks nothing, and asks only where it asks: never "asks" beside its close', () => {
  // 28.10.: the card head read "A tab asks" while the aside offered Close tab (wantsYou against asksSomething)
  const said = { ref: 'surface:12', name: 'Claude Code', state: 'waiting', since_ms: NOW - 14 * MIN, ask: { text: 'Done, the report is filed.', options: [] } }
  const el = mount(html`<${FlowPage} s=${cockpitState(NOW, state({ tabs: [said] }))} c=${recorder()} />`)
  assert.equal(el.$('.flow-card .fx-kind').text(), en.flow.kind.waits)
  assert.ok(el.$('.flow-aside .tab-close'), 'it closes')
  const asking = { ...said, ask: { text: 'Shall I go on?', yes_no: true, options: [] } }
  const ask = mount(html`<${FlowPage} s=${cockpitState(NOW, state({ tabs: [asking] }))} c=${recorder()} />`)
  assert.equal(ask.$('.flow-card .fx-kind').text(), en.flow.kind.asks)
  assert.ok(!ask.$('.flow-aside .tab-close'), 'no close while it asks')
  assert.equal(text.TABLES.de.flow.kind.waits, 'Tab wartet')
})

test('a point whose tab waits at its prompt: its close stands with the tab ways, and Done once where the close ends the point', () => {
  const tab = { ref: 'surface:12', name: 'a research', slug: 'a', state: 'waiting', behind: { task: 'a', item: null }, since_ms: NOW - 14 * MIN }
  const s = pointState({ rows: [task('a', { area: 'Ops' })], tabs: [tab] })
  const el = mount(html`<${FlowPage} s=${s} c=${recorder()} />`)
  const can = el.$$('.flow-aside .flow-can button').map(b => b.text())
  assert.ok(can.includes(en.btnDoneCloseTab) && can.includes(en.btnCloseTabOnly), can.join(' | '))
  assert.ok(!can.includes(en.flow.verbs.done), can.join(' | '))
  // at work it neither closes nor loses its Done
  const busy = mount(html`<${FlowPage} s=${pointState({ rows: [task('a', { area: 'Ops' })], tabs: [{ ...tab, state: 'working' }] })} c=${recorder()} />`)
  assert.ok(!busy.$('.flow-aside .tab-close'))
  assert.ok(busy.$$('.flow-aside .flow-can button').some(b => b.text() === en.flow.verbs.done))
})

test('Running now: an entry of the strip holds the same close (a session card holds it through its tab controls)', () => {
  const tab = { ref: 'surface:12', name: 'a research', slug: 'a', state: 'waiting', idle: true, since_ms: NOW - 14 * MIN }
  const lane = [{ group: 'doing', lane: true, id: 'tab:surface:12', kind: 'tab', row: task('a'), tab, stage: 'idle', how: 'tab', title: 'a', at: NOW - MIN }]
  const s = cockpitState(NOW, state({ work: [task('a')], tabs: [tab] }))
  const el = mount(html`<${views.flowrun.RunningStrip} lane=${lane} s=${s} c=${recorder()} />`)
  assert.ok(el.$('.flow-runstrip-acts .tab-close'))
})

test('Improve: words to the tab while it lives (tab_send through the reply guard), else a new start with them', async () => {
  const row = task('fin')
  const live = { ref: 'surface:10', name: 'fin', slug: 'fin', state: 'waiting', since_ms: NOW - 25 * MIN }
  const base = { work: [row], returns: [startOf('fin', 'idle', { tab: { ref: 'surface:10' } })] }
  let c = recorder()
  let el = mount(html`<${FlowPage} s=${cockpitState(NOW, state({ ...base, tabs: [live] }))} c=${c} />`)
  el.button(`${en.flow.improve.button} ▾`).click()
  await tick()
  let box = el.$('.flow-improve textarea')
  assert.ok(el.button(en.flow.improve.send).hasAttribute('disabled'))
  box.value = 'Add the test for the empty list'
  box.dispatch('input')
  await tick()
  el.button(en.flow.improve.send).click()
  await tick()
  assert.deepEqual(c.calls.find(x => x[0] === 'reply'), ['reply', 'tab_send', { tab_ref: 'surface:10', text: 'Add the test for the empty list', expect: 'waiting', name: 'fin' }])
  // the tab is gone: Improve starts anew with the words, as every start, with a sentence
  c = recorder()
  el = mount(html`<${FlowPage} s=${cockpitState(NOW, state({ ...base, returns: [startOf('fin', 'result', { result: { kind: 'note', text: 'Result: half done' } })] }))} c=${c} />`)
  el.button(`${en.flow.improve.button} ▾`).click()
  await tick()
  box = el.$('.flow-improve textarea')
  box.value = 'Finish the other half'
  box.dispatch('input')
  await tick()
  el.button(en.flow.improve.restart).click()
  await tick()
  assert.deepEqual(c.calls.find(x => x[0] === 'act'), ['act', 'do_it', { keys: ['task:fin'], note: 'Finish the other half' }])
})

// ---------------------------------------------------------------- Let AI do it: the model and the cap on what runs

test('Let AI do it: the model picker under it fetches the recommendation of this card once', async () => {
  const launch = { enabled: true, auto: true, manual: true, effort: false, models: ['haiku', 'sonnet', 'opus'], default_model: 'sonnet' }
  const c = recorder()
  const s = cockpitState(NOW, { ...state(), launch, launchRoutes: {} })
  const el = mount(html`<${VerbBar} row=${task('a')} s=${s} c=${c} />`)
  assert.equal(el.$('.launch-pick'), null)
  el.button(`${en.flow.verbs.do} ▾`).click()
  await tick()
  assert.ok(el.$('.verbbar-panel .launch-pick'), 'model and target under the start sentence')
  assert.deepEqual(c.calls.filter(x => x[0] === 'launchRoute'), [['launchRoute', [{ key: 'task:a', title: 'Task a' }]]])
})

test('Let AI do it: with max_running starts at work it asks first, Start anyway starts', async () => {
  const running = ['r1', 'r2'].map(slug => startOf(slug, 'working', { tab: { ref: `surface:${slug}` } }))
  const tabs = ['r1', 'r2'].map(slug => ({ ref: `surface:${slug}`, name: slug, slug, state: 'working', since_ms: NOW - 5 * MIN }))
  const flow = n => ({ enabled: true, drop_reasons: [], return_after_s: 20, prep_ahead: 2, max_running: n })
  const c = recorder()
  const s = cockpitState(NOW, { ...state({ work: [task('a'), task('r1'), task('r2')], tabs, returns: running }), work: { flow: flow(2) } })
  const el = mount(html`<${VerbBar} row=${task('a')} s=${s} c=${c} />`)
  el.button(`${en.flow.verbs.do} ▾`).click()
  await tick()
  el.button(en.flow.start.button).click()
  await tick()
  assert.equal(c.calls.filter(x => x[0] === 'act').length, 0)
  assert.match(el.$('.verbbar-panel').text(), new RegExp(en.flow.start.busy(2).replace(/[.?]/g, '\\$&')))
  el.button(en.flow.start.anyway).click()
  await tick()
  assert.deepEqual(c.calls.find(x => x[0] === 'act'), ['act', 'do_it', { keys: ['task:a'], note: en.flow.start.note('Task a') }])
  // below the cap it starts at once
  const one = recorder()
  const free = mount(html`<${VerbBar} row=${task('a')} s=${cockpitState(NOW, { ...s, work: { flow: flow(3) } })} c=${one} />`)
  free.button(`${en.flow.verbs.do} ▾`).click()
  await tick()
  free.button(en.flow.start.button).click()
  await tick()
  assert.equal(one.calls.filter(x => x[0] === 'act' && x[1] === 'do_it').length, 1)
})

// ---------------------------------------------------------------- round 2: in progress, themes and areas, the list

const DAYMS = 24 * 60 * MIN

test('In progress: every doing task with what drives it, a review task stays a task, a doing task asks only through its tab', () => {
  const tabs = [{ ref: 'surface:21', name: 'busy', slug: 'busy', state: 'working', since_ms: NOW - 18 * MIN, last: 'Running the tests' },
    { ref: 'surface:22', name: 'asking', slug: 'asking', state: 'needs-you', since_ms: NOW - 2 * MIN }]
  const sessions = { sessions: [{ id: 'cc33', task: 'typed', status: 'busy', started_ms: NOW - 9 * MIN, tab: { ref: 'surface:23', name: 'typed' } }] }
  const s = state({ work: [task('busy'), task('asking'), task('quiet', { updated: '2026-10-06' }), task('typed'), task('checked', { status: 'review' })],
    tabs: [...tabs, { ref: 'surface:23', name: 'typed', state: 'working', since_ms: NOW - 9 * MIN },
      { ref: 'surface:24', name: 'started', state: 'working', since_ms: NOW - 4 * MIN }], sessions,
    returns: [startOf('started', 'working', { tab: { ref: 'surface:24' }, at_ms: NOW - 4 * MIN })] })
  const parts = logic.flowParts(s)
  assert.deepEqual(logic.FLOW_GROUPS, ['back', 'asks', 'result', 'lost', 'question', 'doing', 'task', 'issue', 'reports'])
  // the doing ones: a start of the cockpit, a session typed by hand, the task with its working tab (these three run, round 4:
  // in Running now), the quiet one (a point)
  assert.deepEqual(parts.doing.map(x => x.row.task), ['quiet'])
  const by = Object.fromEntries([...parts.lane, ...parts.doing].map(x => [x.row?.task ?? x.start?.item, logic.flowDrive(x, s)]))
  assert.equal(by.busy.by, 'tab')
  assert.equal(by.busy.tab.ref, 'surface:21')
  assert.equal(by.typed.by, 'session')
  assert.equal(by.started.by, 'start')
  assert.deepEqual([by.quiet.by, by.quiet.days], ['none', 3])
  // the one whose tab asks stands with the tabs that ask, a review task with the tasks
  assert.deepEqual(parts.asks.map(x => x.row?.task), ['asking'])
  assert.deepEqual(parts.task.map(x => x.row.task), ['checked'])
  // what runs counts for max_running: the starts, the session tabs and the task tabs at work (round 4: the task tab too)
  assert.equal(logic.flowRunning(s), 3)
  const q = queueOf(s)
  assert.ok(q.findIndex(x => x.group === 'doing') > q.findIndex(x => x.group === 'asks'))
  assert.ok(q.findIndex(x => x.group === 'doing') < q.findIndex(x => x.group === 'task'))
})

const themesState = (over = {}) => ({ enabled: true, max_themes: 8, budget_left: 3, running: false, last_error: null,
  themes: [{ id: 't000001', name: 'Release work', by: 'ai' }, { id: 't000002', name: 'Empty one', by: 'ai' }],
  assign: { 'task:a': 't000001', 'inbox:20261009-0900-a-q': 't000001' }, by_person: [], suggest: {}, at_ms: NOW - MIN, ...over })

test('the left column by areas: All on top, one entry per area with what needs you and what is open, No area last', () => {
  const s = state({ now: [ask('20261009-0900-a-q', { area: 'Ops' })], work: [task('a', { area: 'Ops' }), task('b', { area: 'Docs' }), task('c')],
    tabs: { tabs: [] } })
  s.tabs = { tabs: [], workspaces: [{ ref: 'workspace:2', title: 'Ops', color: '#196F3D' }] }
  const points = queueOf(s)
  const sides = logic.flowSides(s, points, 'areas')
  assert.deepEqual(sides.map(x => [x.id, x.open, x.you]), [['all', 4, 1], ['a:ops', 2, 1], ['a:docs', 1, 0], ['none', 1, 0]])
  assert.equal(sides[1].color, '#196F3D')
  assert.deepEqual(logic.pointsIn(points, 'a:ops', s, 'areas').map(x => x.id), ['inbox:20261009-0900-a-q', 'task:a'])
  assert.deepEqual(logic.pointsIn(points, 'none', s, 'areas').map(x => x.id), ['task:c'])
  assert.equal(logic.pointsIn(points, 'all', s, 'areas').length, 4)
})

test('the left column by themes: the themes that hold a point, No theme yet for the rest, areas while themes are off', () => {
  const s = { ...state({ now: [ask('20261009-0900-a-q'), report('20261009-0901-a-r1'), report('20261009-0902-a-r2')],
    work: [task('a'), task('b')] }), themes: themesState({ assign: { 'task:a': 't000001', 'inbox:20261009-0900-a-q': 't000001', 'inbox:20261009-0901-a-r1': 't000001' } }) }
  const points = queueOf(s)
  assert.equal(logic.flowMode(s), 'themes')
  const sides = logic.flowSides(s, points, 'themes')
  assert.deepEqual(sides.map(x => [x.id, x.name ?? null, x.open]), [['all', null, 5], ['t:t000001', 'Release work', 3], ['none', null, 2]])
  // the reports card splits by side: each side holds its own reports as one tab
  const mine = logic.pointsIn(points, 't:t000001', s, 'themes')
  assert.deepEqual(mine.map(x => x.id), ['inbox:20261009-0900-a-q', 'task:a', 'reports'])
  assert.deepEqual(mine.at(-1).rows.map(r => r.inbox_id), ['20261009-0901-a-r1'])
  assert.deepEqual(logic.pointsIn(points, 'none', s, 'themes').map(x => x.id), ['task:b', 'reports'])
  // what to send for a run: the points without a theme (reports by their rows), none twice, none while one runs
  assert.deepEqual(logic.themesToAsk(points, s), ['task:b', 'inbox:20261009-0902-a-r2'])
  assert.deepEqual(logic.themesToAsk(points, { ...s, themes: themesState({ running: true }) }), [])
  assert.deepEqual(logic.themesToAsk(points, { ...s, themes: themesState({ budget_left: 0 }) }), [])
  // switched off, or an older server: the areas
  assert.equal(logic.flowMode({ ...s, themes: { enabled: false } }), 'areas')
  assert.equal(logic.flowMode({ ...s, themes: undefined }), 'areas')
  assert.equal(logic.flowMode({ ...s, ui: { ...s.ui, flowMode: 'areas' } }), 'areas')
})

test('flowSuggestion: the triage of the day first, else what the themes run said, each with where it comes from', () => {
  const today = '2026-10-09T07:00:00'
  const rows = [task('closing'), task('stale'), task('waits'), task('agent'), task('mine'), task('nothing')]
  const triage = { last: { at: today }, items: { 'task:closing': { verdict: 'close', reason: 'The guide is merged' },
    'task:stale': { verdict: 'stale', reason: 'Nobody needs it' }, 'task:waits': { verdict: 'waiting', reason: 'Waits on the vendor' },
    'task:agent': { doer: 'ai', reason: 'A small change' } } }
  const themes = themesState({ suggest: { 'task:mine': { verb: 'you', reason: 'Only you can sign it', at_ms: NOW - MIN },
    'task:closing': { verb: 'drop', reason: 'ignored, the triage is fresh', at_ms: NOW - MIN } } })
  const s = { ...state({ work: rows }), triage, themes }
  const got = Object.fromEntries(rows.map(r => [r.task, logic.flowSuggestion(r, s)]))
  assert.deepEqual([got.closing.verb, got.closing.from, got.closing.reason], ['done', 'triage', 'The guide is merged'])
  assert.equal(got.stale.verb, 'drop')
  assert.deepEqual([got.waits.verb, got.waits.until], ['later', '2026-10-12'])
  assert.equal(got.agent.verb, 'do')
  assert.deepEqual([got.mine.verb, got.mine.from], ['you', 'themes'])
  assert.equal(got.nothing, null)
  // a triage of three days ago is stale: the themes run speaks instead
  const old = { ...s, triage: { ...triage, last: { at: '2026-10-06T07:00:00' } } }
  assert.deepEqual([logic.flowSuggestion(task('closing'), old).verb, logic.flowSuggestion(task('closing'), old).from], ['drop', 'themes'])
  // a verb the row does not offer is no suggestion: a stream is never done
  assert.equal(logic.flowSuggestion(task('closing', { stream: true, settle: [] }), s), null)
})

test('a point an agent already works on: no Let AI do it as its suggestion, and a batch never starts a second agent on it', () => {
  const rows = [task('run'), task('tabbed'), task('free')]
  const sug = { 'task:run': { verb: 'do', reason: 'r' }, 'task:tabbed': { verb: 'do', reason: 'r' }, 'task:free': { verb: 'do', reason: 'r' } }
  // the start's tab names no task (slug), so only the start itself says an agent is on it
  const s = { ...state({ work: rows, tabs: [{ ref: 'surface:7', name: 'tabbed', slug: 'tabbed', state: 'working', since_ms: NOW - MIN },
    { ref: 'surface:9', name: 'agent', state: 'working', since_ms: NOW - 5 * MIN }],
    returns: [{ key: 'task:run', item: 'run', title: 'Task run', mode: 'go', at_ms: NOW - 5 * MIN, stage: 'working', tab: { ref: 'surface:9' } }] }),
  themes: themesState({ suggest: sug }) }
  // the start from the cockpit and the tab of the task work on it already: nothing to hand to an agent there
  assert.equal(logic.flowSuggestion(task('run'), s), null)
  assert.equal(logic.flowSuggestion(task('tabbed'), s), null)
  assert.equal(logic.flowSuggestion(task('free'), s).verb, 'do')
  const plan = logic.batchPlan(rows, 'suggested', s)
  assert.deepEqual(plan.calls.map(x => x.args.keys), [['task:free']])
  // both run (Running now): a batch takes what runs only into Done or a merge
  assert.deepEqual(plan.skipped.map(x => [x.row.key, x.why]), [['task:run', 'working'], ['task:tabbed', 'working']])
  // the same for a start picked by hand with one verb for all
  assert.deepEqual(logic.batchPlan([task('run')], 'do', s).skipped.map(x => x.why), ['working'])
})

test('batchPlan: the suggestions take done, drop and later, never Let AI do it unless picked and under max_running', () => {
  const rows = [task('d1'), task('d2'), task('drop'), task('later'), task('agent'), task('mine')]
  const sug = { 'task:d1': { verb: 'done', reason: 'r' }, 'task:d2': { verb: 'done', reason: 'r' },
    'task:drop': { verb: 'drop', reason: 'r', drop: 'not_needed' }, 'task:later': { verb: 'later', reason: 'r', until: '2026-10-12' },
    'task:agent': { verb: 'do', reason: 'r' }, 'task:mine': { verb: 'you', reason: 'r' } }
  const s = { ...state({ work: rows }), themes: themesState({ suggest: sug }) }
  // what Take the suggestions ticks: done, drop and later, never Let AI do it, never needs you
  assert.deepEqual(logic.batchPreselect(rows, s), ['task:d1', 'task:d2', 'task:drop', 'task:later'])
  let plan = logic.batchPlan(rows.filter(r => r.task !== 'mine'), 'suggested', s)
  // Done for several goes out as one settle; drop shelves with its reason; later with its day; the start with its own sentence
  // each with by: suggestion, which the server keeps in the history and the launches
  assert.deepEqual(plan.calls, [
    { verb: 'settle', args: { keys: ['task:d1', 'task:d2'], outcome: 'done', by: 'suggestion' } },
    { verb: 'later', args: { key: 'task:later', until: '2026-10-12', by: 'suggestion' } },
    { verb: 'shelve', args: { key: 'task:drop', reason: en.flow.drop.reason.not_needed, by: 'suggestion' } },
    { verb: 'do_it', args: { keys: ['task:agent'], note: en.flow.start.note('Task agent'), by: 'suggestion' } }])
  assert.deepEqual(plan.counts, { done: 2, later: 1, drop: 1, do: 1 })
  assert.equal(logic.batchSummary(plan, 'en'), en.flow.batch.summary(plan))
  // at max_running the start stays out, and the plan says why
  const tabs = ['r1', 'r2', 'r3', 'r4'].map(x => ({ ref: `surface:${x}`, name: x, slug: x, state: 'working' }))
  const busy = { ...s, returns: [], model: s.model, sessions: { sessions: tabs.map((t, i) => ({ id: `s${i}`, task: t.slug, tab: { ref: t.ref } })) },
    tabs: { tabs } }
  busy.model = { ...s.model, sections: s.model.sections.map(x => (x.id === 'work' ? { ...x, rows: [...x.rows, ...tabs.map(t => task(t.slug))] } : x)) }
  plan = logic.batchPlan([task('agent')], 'suggested', busy)
  assert.deepEqual(plan.calls, [])
  assert.deepEqual(plan.skipped.map(x => [x.row.key, x.why]), [['task:agent', 'running']])
  // one verb for all: Done where a row offers it, Drop with one reason for all, Later with one day
  plan = logic.batchPlan([task('d1'), task('x', { stream: true, settle: [] })], 'done', s)
  assert.deepEqual(plan.calls, [{ verb: 'settle', args: { keys: ['task:d1'], outcome: 'done', by: 'batch' } }])
  assert.deepEqual(plan.skipped.map(x => x.why), ['not_offered'])
  plan = logic.batchPlan([task('d1'), ask('20261009-0900-a-q')], 'drop', s, 'Nobody needs it')
  assert.deepEqual(plan.calls, [{ verb: 'shelve', args: { key: 'task:d1', reason: 'Nobody needs it', by: 'batch' } },
    { verb: 'settle', args: { keys: ['inbox:20261009-0900-a-q'], outcome: 'not_doing', text: 'Nobody needs it', by: 'batch' } }])
  assert.equal(logic.batchPlan([task('d1')], 'drop', s, '').calls.length, 0)
  plan = logic.batchPlan([task('d1'), task('d2')], 'later', s, '2026-10-12')
  assert.deepEqual(plan.calls.map(x => x.args), [{ key: 'task:d1', until: '2026-10-12', by: 'batch' }, { key: 'task:d2', until: '2026-10-12', by: 'batch' }])
})

test('the overview: suggestions with where they come from, Tick, the ticked line, Run with one line to confirm, then one undo', async () => {
  const rows = [task('d1'), task('drop'), task('agent'), task('mine')]
  const triage = { last: { at: '2026-10-09T07:00:00' }, items: { 'task:d1': { verdict: 'close', reason: 'The guide is merged' },
    'task:agent': { doer: 'ai', reason: 'A small change' } } }
  const assign = Object.fromEntries(rows.map(r => [r.key, 't000001']))
  const themes = themesState({ assign, suggest: { 'task:drop': { verb: 'drop', reason: 'Nobody needs it', drop: 'not_needed', at_ms: NOW } } })
  const base = { ...state({ work: rows }), triage, themes,
    ui: { ...state().ui, page: 'briefing', workView: 'flow', flowView: 'overview', flowSide: { themes: 't:t000001' }, flowPicked: [] } }
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${cockpitState(NOW, base)} c=${c} />`)
  assert.equal(el.$$('.flow-ov-row').length, 4)
  const from = el.$('.flow-list-from').text()
  assert.match(from, /from the triage of/)
  assert.match(from, new RegExp(en.flow.list.from.themes))
  assert.match(from, new RegExp(en.flow.list.honest))
  assert.match(el.$$('.flow-ov-row')[0].$('.flow-ov-sug').text(), /The guide is merged/)
  // the suggestion stands once, in the middle: no chip and no Tick in the left column
  assert.match(el.$$('.flow-ov-row')[0].$('.flow-ov-sug').text(), new RegExp(en.flow.list.verb.done))
  assert.ok(!el.$('aside .flow-pt-chip'), 'aside .flow-pt-chip')
  // Tick in the bar: done and drop, never Let AI do it; nothing goes out
  el.button(en.flow.list.tick(2)).click()
  assert.deepEqual(c.calls.at(-1), ['flowPick', ['task:d1', 'task:drop'], true])
  assert.equal(c.calls.filter(x => x[0] === 'act' || x[0] === 'flowBatch').length, 0)
  assert.ok(el.button(en.flow.list.run).hasAttribute('disabled'))
  // two ticked: the bar counts them by their suggestion, Run plans, Confirm sends and clears the boxes
  const s2 = cockpitState(NOW, { ...base, ui: { ...base.ui, flowPicked: ['task:d1', 'task:drop'] } })
  const c2 = recorder()
  const el2 = mount(html`<${FlowPage} s=${s2} c=${c2} />`)
  assert.match(el2.$('.flow-ov-bar').text(), new RegExp(en.flow.list.ticked(2, '1 done, 1 drop')))
  assert.deepEqual(el2.$$('.flow-ov-row').map(tr => tr.getAttribute('class').includes('is-picked')), [true, true, false, false])
  el2.button(en.flow.list.run).click()
  await tick()
  assert.match(el2.$('.flow-list-confirm').text(), /1 done, 1 drop: No longer needed/)
  assert.equal(c2.calls.filter(x => x[0] === 'flowBatch').length, 0)
  el2.button(en.flow.list.confirm).click()
  await tick()
  assert.deepEqual(c2.calls.find(x => x[0] === 'flowBatch'), ['flowBatch', [{ verb: 'settle', args: { keys: ['task:d1'], outcome: 'done', by: 'suggestion' } },
    { verb: 'shelve', args: { key: 'task:drop', reason: 'No longer needed', by: 'suggestion' } }]])
  assert.ok(c2.calls.some(x => x[0] === 'flowPick' && x[2] === false))
  // the same for all: Done with the two ticked plans a settle of both
  const el3 = mount(html`<${FlowPage} s=${s2} c=${recorder()} />`)
  el3.button(en.flow.verbs.done).click()
  await tick()
  assert.match(el3.$('.flow-list-confirm').text(), /2 done/)
  // after the batch: one undo for all of it, once on the page
  const after = mount(html`<${FlowPage} s=${cockpitState(NOW, { ...base, ui: { ...base.ui, flowBatch: { running: false, n: 2, undo: [{ undo: {} }] } } })} c=${c} />`)
  assert.equal(after.$$('button').filter(b => b.text().includes(en.flow.list.undo)).length, 1)
  after.button(en.flow.list.undo).click()
  assert.deepEqual(c.calls.at(-1), ['flowBatchUndo'])
})

test('pointBand: the left column and the overview group the points as Needs you, In progress, Tasks, Reports', () => {
  assert.deepEqual(logic.FLOW_BANDS, ['you', 'doing', 'task', 'issue', 'reports'])
  for (const g of logic.FLOW_YOU) assert.equal(logic.pointBand({ group: g }), 'you')
  assert.equal(logic.pointBand({ group: 'doing' }), 'doing')
  assert.equal(logic.pointBand({ group: 'task' }), 'task')
  assert.equal(logic.pointBand({ group: 'reports' }), 'reports')
})

test('themesAsker: each key once, but a run that failed leaves its keys free for the next ask', async () => {
  const sent = []
  let answer = false
  const ask = logic.themesAsker(async keys => { sent.push(keys); return answer })
  await ask(['a', 'b'])
  await ask(['a', 'b'])
  assert.deepEqual(sent, [['a', 'b'], ['a', 'b']])
  answer = true
  await ask(['a', 'c'])
  await ask(['a', 'c'])
  assert.deepEqual(sent.at(-1), ['a', 'c'])
  assert.equal(sent.length, 3)
  // one at a time: an ask while one runs is left out (the next render asks again)
  let release
  const slow = logic.themesAsker(keys => new Promise(r => { sent.push(keys); release = r }))
  const first = slow(['x'])
  await slow(['y'])
  release(true)
  await first
  assert.deepEqual(sent.slice(-1), [['x']])
})

// ---------------------------------------------------------------- round 3: tabs under the card, one Activity, fields
// right, the instruction line, nothing twice

/** The element right after `el` among its parent's elements (the render DOM has no sibling selector) */
const nextEl = el => { const sibs = el.parentNode.childNodes.filter(n => n.nodeType === 1); return sibs[sibs.indexOf(el) + 1] ?? null }

/** A row of the activity feed as /api/flow/activity sends it */
const arow = (over = {}) => ({ id: 'note:1', at: '2026-10-09T09:00', at_ms: NOW - 3 * 60 * MIN, kind: 'note', filters: ['notes'], text: '',
  change: null, undone_ms: null, by: null, links: [], doc: null, agent: null, ...over })

/** The feed of task:a: one row of each source, the counts before a cut, the facts and what the page may do */
const feedOf = (key = 'task:a', over = {}) => ({ ok: true, key, at_ms: NOW, more: false,
  rows: [
    arow({ id: 'theme:1', at: '2026-10-09T09:40', kind: 'theme', filters: ['state'], change: { field: 'theme', old: null, new: 'Release work' },
      by: { kind: 'themes', name: null } }),
    arow({ id: 'doc:1', at: '2026-10-09T09:12', kind: 'doc', filters: ['docs'], text: 'The first draft', by: { kind: 'you', name: null },
      doc: { path: 'deliverables/draft.md', state: 'new', changes: 1, attached: false, bytes: 1200 },
      links: [{ kind: 'doc', slug: 'a', path: 'deliverables/draft.md' }] }),
    arow({ id: 'agent:1', at: '2026-10-09T08:12', kind: 'agent', filters: ['agents', 'state'], text: 'Started: write the draft',
      change: { field: 'driver', old: null, new: 'draft-tab' }, by: { kind: 'suggestion', name: null }, links: [{ kind: 'tab', ref: 'surface:5' }],
      agent: { mode: 'go', stage: 'working', result: null } }),
    arow({ id: 'decision:1', at: '2026-10-08T17:20', kind: 'decision', filters: ['state'],
      change: { field: 'decision', old: null, new: 'later', until: '2026-10-12' }, undone_ms: NOW - 60 * MIN, by: { kind: 'batch', name: null } }),
    arow({ id: 'code:1', at: '2026-10-08', kind: 'code', filters: ['code'], text: 'example/repo#18 The setup guide', by: { kind: 'git', name: null },
      links: [{ kind: 'web', href: 'https://github.com/example/repo/pull/18' }] }),
    arow({ id: 'note:1', at: '2026-10-07', kind: 'note', filters: ['notes'], text: 'Outline agreed' }),
    arow({ id: 'status:1', at: '2026-10-06T10:00', kind: 'status', filters: ['state'], change: { field: 'status', old: 'backlog', new: 'doing' },
      by: { kind: 'git', name: null } }),
  ],
  counts: { all: 7, notes: 1, docs: 1, state: 4, agents: 1, code: 1 },
  facts: { created: '2026-10-05', moved: '2026-10-09T09:40',
    jev: { quadrant: 'plan', rank: 4, urgency: 0.67, impact: 1.0, effort: 0.33, only_me: 0.8, at_ms: NOW } },
  summary: null, can: { note: true, attach: true, summary: true }, ...over })

/** The task detail of /api/task for task:a: its card, two steps of three done, two related paths */
const detailOf = (over = {}) => ({ ok: true, slug: 'a', kind: 'task', path: 'work/tasks/a/STATUS.md',
  front: { status: 'doing', created: '2026-10-05', origin: 'https://example.org/tickets/7' },
  sections: [{ heading: 'Steps', text: '- [x] Outline\n- [X] Examples\n- [ ] Screenshots', truncated: false }],
  log: [], inbox: [], related: ['docs/guide.md', 'work/tasks/b/STATUS.md'],
  card: { kind: 'task', goal: 'A new member sets up the project in an hour', story: null, acceptance: ['Every step is written down'] }, ...over })

/** The page on one point open: the flow blocks on as the demo has them, the detail and the feed loaded for task:a */
function pointState({ rows = [task('a', { area: 'Ops' })], feed = feedOf(), detail = detailOf(), flow = {}, ui = {}, ...rest } = {}) {
  const base = state({ work: rows, ...rest })
  const st = cockpitState(NOW, { ...base,
    work: { flow: { enabled: true, drop_reasons: ['resolves_itself', 'not_needed'], return_after_s: 20,
      summary: { enabled: true, budget_per_day: 10, model: null }, instruct: { enabled: true, budget_per_day: 30, model: null },
      attach: { enabled: true, max_mb: 10 }, ...flow } },
    flow_ai: { summary_left: 9, instruct_left: 29, instruct_running: false },
    details: { inbox: {}, task: detail ? { a: { status: 'ok', ver: 0, data: detail } } : {},
      activity: feed ? { [feed.key]: { status: 'ok', ver: 0, data: feed } } : {} },
    ui: { ...base.ui, page: 'briefing', workView: 'flow', flowView: 'point', flowAt: { id: rows[0].key, i: 0 }, flowTab: 'desc', flowFilter: 'all', ...ui } })
  // round 4: a task a live tab works on runs (Running now), so it opens as an entry of it in the middle (view run)
  const run = ui.flowView ? null : logic.flowParts(st).lane.find(x => x.row?.key === rows[0].key)
  return run ? { ...st, ui: { ...st.ui, flowView: 'run', flowRunId: run.id } } : st
}

/** The point or the entry of Running now that stands for a key */
const pointOf = (s, key) => [...logic.flowParts(s).lane, ...queueOf(s)].find(x => x.row?.key === key)

test('pointTabs: Description and Activity on every point with a row, Steps and Related with a task, none for a tab alone or the reports', () => {
  assert.deepEqual(logic.FLOW_TABS, ['desc', 'steps', 'activity', 'related'])
  assert.deepEqual(logic.pointTabs({ kind: 'row', row: task('a') }), ['desc', 'steps', 'activity', 'related'])
  assert.deepEqual(logic.pointTabs({ kind: 'row', row: ask('20261009-0900-a-q') }), ['desc', 'activity'])
  assert.deepEqual(logic.pointTabs({ kind: 'row', row: ask('20261009-0900-a-q', { task: 'a' }) }), ['desc', 'steps', 'activity', 'related'])
  assert.deepEqual(logic.pointTabs({ kind: 'tab', tab: { ref: 'surface:1' }, row: null }), [])
  assert.deepEqual(logic.pointTabs({ kind: 'reports', rows: [report('20261009-0901-a-r')] }), [])
  // the tab chosen stays from point to point; one the point lacks falls back to Description
  assert.equal(logic.pointTab(['desc', 'activity'], 'activity'), 'activity')
  assert.equal(logic.pointTab(['desc', 'activity'], 'steps'), 'desc')
  assert.equal(logic.pointTab(['desc', 'activity'], null), 'desc')
})

test('stepsOf: the checklist lines of STATUS.md as they stand, done or open', () => {
  assert.deepEqual(logic.stepsOf(detailOf()), [{ done: true, text: 'Outline' }, { done: true, text: 'Examples' }, { done: false, text: 'Screenshots' }])
  assert.deepEqual(logic.stepsOf(null), [])
  assert.deepEqual(logic.stepsOf({ sections: [{ text: 'no list here\n- a plain bullet' }] }), [])
})

test('activityRows and activityCounts: a filter keeps the rows that carry it, the counts are the server\'s, before its cut', () => {
  const feed = feedOf()
  assert.deepEqual(logic.ACTIVITY_FILTERS, ['all', 'notes', 'docs', 'state', 'agents', 'code'])
  assert.equal(logic.activityRows(feed, 'all').length, 7)
  assert.deepEqual(logic.activityRows(feed, 'state').map(r => r.id), ['theme:1', 'agent:1', 'decision:1', 'status:1'])
  assert.deepEqual(logic.activityRows(feed, 'agents').map(r => r.id), ['agent:1'])
  assert.deepEqual(logic.activityRows(null, 'all'), [])
  // the server counts before it cuts at 200 rows: its counts stand, even where the rows shown are fewer
  assert.deepEqual(logic.activityCounts({ ...feed, counts: { ...feed.counts, all: 260 }, more: true }).all, 260)
  // a feed without counts is counted from its rows
  assert.deepEqual(logic.activityCounts({ rows: feed.rows }), { all: 7, notes: 1, docs: 1, state: 4, agents: 1, code: 1 })
})

test('activityWhen: a day and a time in the page\'s language, a day alone for a source with only the day', () => {
  assert.equal(logic.activityWhen('2026-10-27T09:40', 'de'), '27.10. 09:40')
  assert.equal(logic.activityWhen('2026-10-27', 'de'), '27.10.')
  assert.match(logic.activityWhen('2026-10-27T09:40', 'en'), /^Oct 27 09:40$/)
  assert.equal(logic.activityWhen('', 'en'), '')
})

test('flowFields: the fields of a point in their order, never a status; Prio from Jev, else the triage rank, else the priority', () => {
  const s = pointState()
  const x = queueOf(s)[0]
  const fields = logic.flowFields(x, s, feedOf(), detailOf())
  assert.deepEqual(fields.map(f => f.id), ['area', 'who', 'prio', 'urgency', 'impact', 'effort', 'due', 'source', 'created', 'moved'])
  assert.ok(!fields.some(f => ['status', 'state'].includes(f.id)), 'no Status field: the card head says it')
  const by = Object.fromEntries(fields.map(f => [f.id, f]))
  assert.deepEqual(by.prio.jev, { quadrant: 'plan', rank: 4, who: null, ranker: null })
  assert.deepEqual([by.urgency.value, by.impact.value, by.effort.value], [0.67, 1.0, 0.33])
  assert.equal(by.area.value, 'Ops')
  assert.equal(by.who.drive.by, 'none')
  assert.equal(by.source.url, 'https://example.org/tickets/7', 'STATUS.md origin when it is a link')
  assert.equal(by.created.value, '2026-10-05')
  assert.equal(by.moved.value, '2026-10-09T09:40')
  // the theme comes first while the themes are on
  const th = { ...s, themes: themesState() }
  assert.equal(logic.flowFields(x, th, feedOf(), detailOf())[0].id, 'theme')
  // without Jev: the triage's rank, else the priority; no bars then
  const noJev = feedOf('task:a', { facts: { created: null, moved: null, jev: null } })
  const ranked = { ...s, triage: { items: { 'task:a': { next_rank: 3 } } } }
  const r = Object.fromEntries(logic.flowFields(x, ranked, noJev, null).map(f => [f.id, f]))
  assert.equal(r.prio.rank, 3)
  assert.equal(r.urgency, undefined)
  assert.equal(Object.fromEntries(logic.flowFields(x, s, noJev, null).map(f => [f.id, f])).prio.priority, 'P2')
  // a tab that asks: who works on it is its tab
  const ts = state({ tabs: [dialog()] })
  const tx = queueOf(ts)[0]
  assert.equal(Object.fromEntries(logic.flowFields(tx, ts, null, null).map(f => [f.id, f])).who.drive.by, 'tab')
})

test('flowAction and the verb bar carry by: a suggestion taken, a batch, an instruction; a click of your own sends none', async () => {
  assert.deepEqual(logic.flowAction('done', task('a'), '', 'suggestion'), { verb: 'settle', args: { keys: ['task:a'], outcome: 'done', by: 'suggestion' } })
  assert.deepEqual(logic.flowAction('later', task('a'), '2026-10-12', 'instruction'), { verb: 'later', args: { key: 'task:a', until: '2026-10-12', by: 'instruction' } })
  assert.deepEqual(logic.flowAction('drop', task('a'), 'x', 'batch'), { verb: 'shelve', args: { key: 'task:a', reason: 'x', by: 'batch' } })
  assert.deepEqual(logic.flowAction('do', task('a'), 'Go', 'instruction'), { verb: 'do_it', args: { keys: ['task:a'], note: 'Go', by: 'instruction' } })
  // the primary that came from the suggestion sends by suggestion; another verb of the same bar sends none
  const themes = themesState({ suggest: { 'task:a': { verb: 'done', reason: 'Merged', at_ms: NOW } } })
  const s = { ...pointState(), themes }
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${s} c=${c} />`)
  el.button(en.flow.verbs.done).click()
  await tick()
  assert.deepEqual(c.calls.find(x => x[0] === 'act'), ['act', 'settle', { keys: ['task:a'], outcome: 'done', by: 'suggestion' }])
  const c2 = recorder()
  const el2 = mount(html`<${FlowPage} s=${s} c=${c2} />`)
  el2.button(`${en.flow.verbs.later} ▾`).click()
  await tick()
  el2.button(en.flow.later.tomorrow).click()
  await tick()
  assert.deepEqual(c2.calls.find(x => x[0] === 'act'), ['act', 'later', { key: 'task:a', until: '2026-10-10' }])
})

test('the card carries content only: no verbs, no source, no area, no who; the state in its head; the tabs under it', () => {
  const busy = { ref: 'surface:21', name: 'busy', slug: 'a', state: 'working', since_ms: NOW - 18 * MIN, last: 'one\ntwo\nthree\nfour\nfive\nRunning the tests' }
  const s = pointState({ tabs: [busy] })
  const el = mount(html`<${FlowPage} s=${s} c=${recorder()} />`)
  const card = el.$('.flow-card')
  assert.equal(card.$('.fx-acts'), null, 'no foot on the card')
  assert.equal(card.$$('button').length, 0, 'no button on a card of a task at work')
  assert.equal(card.$('.origin'), null, 'the source stands in the fields only')
  assert.equal(card.$('.fx-proj'), null, 'the area stands in the fields only')
  assert.equal(card.$('.flow-who'), null)
  // the screen up to twelve lines, in the card only
  assert.match(card.$('.fx-screen').text(), /one two three four five Running the tests/)
  // the tabs stand under the card, and no tab of the screen of its own
  assert.ok(nextEl(card).hasClass('flow-ptabs'), 'the tab bar right under the card')
  assert.ok(!el.$$('.flow-ptabs [role=tab]').some(b => /screen|tab/i.test(b.getAttribute('data-tab'))))
  // a question card: its title and the state, the source out of it, the verbs on the right
  const q = pointState({ rows: [ask('20261009-0900-a-q', { area: 'Ops', origin: { category: 'bot', detail: 'issue-radar' } })], feed: feedOf('inbox:20261009-0900-a-q'), detail: null })
  const qel = mount(html`<${FlowPage} s=${q} c=${recorder()} />`)
  assert.equal(qel.$('.flow-card .origin'), null)
  assert.ok(qel.$('.flow-aside [data-field=source] .origin'))
  assert.deepEqual(qel.$$('.flow-ptabs [role=tab]').map(b => b.getAttribute('data-tab')), ['desc', 'activity'])
})

test('the tab bar: one tablist under the card, counts in it, the chosen tab kept from point to point, a missing one falls back', () => {
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${pointState({ ui: { flowTab: 'activity' } })} c=${c} />`)
  const bar = el.$('.flow-ptabs [role=tablist]')
  assert.ok(bar)
  const tabs = bar.$$('[role=tab]')
  assert.deepEqual(tabs.map(b => b.text()), [en.flow.ptabs.desc, `${en.flow.ptabs.steps} 2/3`, `${en.flow.ptabs.activity} 7`, `${en.flow.ptabs.related} 2`])
  assert.deepEqual(tabs.map(b => b.getAttribute('aria-selected')), ['false', 'false', 'true', 'false'])
  assert.ok(el.$('.flow-ptabs [role=tabpanel] .flow-act'))
  tabs[1].click()
  assert.deepEqual(c.calls.at(-1), ['flowTab', 'steps'])
  // a question without a task has no Steps: the tab chosen falls back to Description
  const q = pointState({ rows: [ask('20261009-0900-a-q')], feed: feedOf('inbox:20261009-0900-a-q'), detail: null, ui: { flowTab: 'steps' } })
  const qel = mount(html`<${FlowPage} s=${q} c=${recorder()} />`)
  assert.equal(qel.$('.flow-ptabs [aria-selected=true]').getAttribute('data-tab'), 'desc')
  // the reports card has no bar
  const r = cockpitState(NOW, { ...state({ now: [report('20261009-0901-a-r')] }), ui: { ...state().ui, flowAt: { id: 'reports', i: 0 } } })
  assert.equal(mount(html`<${FlowPage} s=${r} c=${recorder()} />`).$('.flow-ptabs'), null)
})

test('Description: goal, story and criteria without the source; Steps n of m; Related: the other rows and the paths STATUS.md names', () => {
  const desc = mount(html`<${FlowPage} s=${pointState()} c=${recorder()} />`)
  const pane = desc.$('.flow-ptabs [role=tabpanel]')
  assert.match(pane.text(), /A new member sets up the project in an hour/)
  assert.match(pane.text(), /Every step is written down/)
  assert.equal(pane.$('.origin'), null, 'no source in the description')
  const steps = mount(html`<${FlowPage} s=${pointState({ ui: { flowTab: 'steps' } })} c=${recorder()} />`)
  assert.deepEqual(steps.$$('.flow-steps li').map(li => li.getAttribute('class')), ['is-done', 'is-done', ''])
  const rel = mount(html`<${FlowPage} s=${pointState({ rows: [task('a'), ask('20261009-0900-a-q', { task: 'a', title: 'The vendor asks' })], ui: { flowTab: 'related' } })} c=${recorder()} />`)
  const related = rel.$('.flow-related').text()
  assert.match(related, /docs\/guide\.md/)
  assert.match(related, /work\/tasks\/b\/STATUS\.md/)
})

test('Activity: the filters with their counts, each row with time, kind, old struck through then new, who; links open what they name', () => {
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${pointState({ ui: { flowTab: 'activity' } })} c=${c} />`)
  const pane = el.$('.flow-act')
  const filters = pane.$$('.flow-act-filters button')
  assert.deepEqual(filters.map(b => b.text()), ['All 7', 'Notes 1', 'Documents 1', 'State 4', 'Agents 1', 'Code 1'])
  filters[3].click()
  assert.deepEqual(c.calls.at(-1), ['flowFilter', 'state'])
  const rows = pane.$$('.flow-act-row')
  assert.equal(rows.length, 7)
  // a state row: the old value struck through, then the new one, and who did it
  const status = rows[6]
  assert.equal(status.$('.flow-chg-old').localName, 'del')
  assert.equal(status.$('.flow-chg-old').text(), en.flow.activity.state.backlog)
  assert.equal(status.$('.flow-chg-new').text(), en.flow.activity.state.doing)
  assert.match(status.$('.flow-act-who').text(), new RegExp(en.flow.activity.by.git))
  assert.match(status.$('.flow-act-kind').text(), new RegExp(en.flow.activity.kind.status))
  // a decision taken back says so, a theme without an old one struck as No theme yet, as the mockup has it
  assert.ok(rows[3].$('.flow-act-undone'))
  assert.match(rows[3].text(), new RegExp(en.flow.activity.undone))
  assert.equal(rows[0].$('.flow-chg-old').text(), en.flow.side.noTheme)
  assert.equal(rows[2].$('.flow-chg-old').text(), en.flow.activity.nobody, 'who drives it: nobody before the start')
  assert.match(rows[0].$('.flow-act-who').text(), new RegExp(en.flow.activity.by.themes))
  // a document opens in a new tab through the doc route, a web link too, a tab link in the page's view of the tab
  const doc = rows[1].$('a')
  assert.equal(doc.getAttribute('target'), '_blank')
  assert.ok(c.calls.some(x => x[0] === 'docHref' && x[1] === 'a' && x[2] === 'deliverables/draft.md'))
  assert.match(rows[1].$('.flow-act-kind').text(), new RegExp(en.flow.activity.doc.new))
  assert.equal(rows[4].$('a').getAttribute('href'), 'https://github.com/example/repo/pull/18')
  assert.equal(rows[4].$('a').getAttribute('rel'), 'noopener noreferrer')
  rows[2].$('.flow-act-links button').click()
  assert.deepEqual(c.calls.at(-1), ['openTabView', 'surface:5'])
  // a filter shows its rows only
  const st = mount(html`<${FlowPage} s=${pointState({ ui: { flowTab: 'activity', flowFilter: 'state' } })} c=${recorder()} />`)
  assert.equal(st.$$('.flow-act-row').length, 4)
})

test('Activity as the server words it: a state row says itself in its change, a document in its link, a start without a tab names nobody', () => {
  // activity.py gives a state row a short phrase as its text (a fallback for a reader without the change), a document
  // row its path inside deliverables/, and a start of the return channel a driver of null when no tab is known
  const rows = [
    arow({ id: 'status:1', at: '2026-10-08T15:00', kind: 'status', filters: ['state'], text: 'Status changed', change: { field: 'status', old: 'doing', new: 'review' } }),
    arow({ id: 'decision:1', at: '2026-10-08T14:00', kind: 'decision', filters: ['state'], text: 'Later until 2026-10-12',
      change: { field: 'decision', old: null, new: 'later', until: '2026-10-12' }, by: { kind: 'instruction', name: null } }),
    arow({ id: 'theme:1', at: '2026-10-08T13:00', kind: 'theme', filters: ['state'], text: 'Theme changed', change: { field: 'theme', old: 'Docs', new: 'Release work' } }),
    arow({ id: 'doc:1', at: '2026-10-08T12:00', kind: 'doc', filters: ['docs'], text: 'sub/plan.md',
      doc: { path: 'deliverables/sub/plan.md', state: 'new', changes: 1, attached: false, bytes: 10 }, links: [{ kind: 'doc', slug: 'a', path: 'deliverables/sub/plan.md' }] }),
    arow({ id: 'agent:1', at: '2026-10-08T11:00', kind: 'agent', filters: ['agents', 'state'], text: 'the draft is in deliverables/plan.md',
      change: { field: 'driver', old: null, new: null }, agent: { mode: 'go', stage: 'result', result: 'the draft is in deliverables/plan.md' } }),
    arow({ id: 'created:1', at: '2026-10-01', kind: 'created', filters: ['state'], text: 'Created', change: { field: 'status', old: null, new: 'backlog' } }),
  ]
  const feed = feedOf('task:a', { rows, counts: { all: 6, notes: 0, docs: 1, state: 5, agents: 1, code: 0 } })
  const el = mount(html`<${FlowPage} s=${pointState({ feed, ui: { flowTab: 'activity' } })} c=${recorder()} />`)
  const r = el.$$('.flow-act-row')
  assert.equal(r.length, 6)
  for (const k of [0, 1, 2, 5]) {
    assert.ok(!r[k].$('.flow-act-text'), `${rows[k].kind}: the change says it, the phrase is not said twice`)
    assert.ok(r[k].$('.flow-chg-new'))
  }
  assert.match(r[1].$('.flow-chg-new').text(), new RegExp(en.flow.activity.decision.later))
  assert.ok(!r[3].$('.flow-act-text'), 'the path stands once, as the link')
  assert.equal(r[3].$('a').text(), 'deliverables/sub/plan.md')
  assert.ok(!r[4].$('.flow-chg'), 'no driver known: no change shown')
  assert.match(r[4].$('.flow-act-text').text(), /the draft is in deliverables\/plan\.md/)
})

test('Activity: a note through the server, a document attached where the point has a task, the summary on a click', async () => {
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${pointState({ ui: { flowTab: 'activity' } })} c=${c} />`)
  const add = el.button(en.flow.activity.note.add)
  assert.ok(add.hasAttribute('disabled'), 'nothing to add yet')
  const field = el.$('.flow-act-note')
  field.value = 'Called the vendor, prices next week'
  field.dispatch('input')
  await tick()
  el.button(en.flow.activity.note.add).click()
  await tick()
  assert.deepEqual(c.calls.find(x => x[0] === 'flowNote'), ['flowNote', 'task:a', 'Called the vendor, prices next week'])
  // the file picker is hidden behind its button; a picked file goes to the controller as it is
  assert.ok(el.button(en.flow.activity.attach.button))
  const input = el.$('input[type=file]')
  assert.ok(input && input.hasAttribute('hidden'))
  const file = { name: 'Offer v2.pdf', size: 4000 }
  input.files = [file]
  input.dispatch('change')
  await tick()
  assert.deepEqual(c.calls.find(x => x[0] === 'flowAttach'), ['flowAttach', 'task:a', file])
  // too big for max_mb: refused on the page, nothing goes out
  const c2 = recorder()
  const small = mount(html`<${FlowPage} s=${pointState({ ui: { flowTab: 'activity' }, flow: { attach: { enabled: true, max_mb: 1 } } })} c=${c2} />`)
  const big = small.$('input[type=file]')
  big.files = [{ name: 'huge.zip', size: 2 * 1048576 }]
  big.dispatch('change')
  await tick()
  assert.equal(c2.calls.filter(x => x[0] === 'flowAttach').length, 0)
  assert.match(small.$('.flow-act-foot').text(), new RegExp(en.flow.activity.attach.tooBig(1)))
  // no attach for a point the server says takes none
  const none = mount(html`<${FlowPage} s=${pointState({ ui: { flowTab: 'activity' }, feed: feedOf('task:a', { can: { note: true, attach: false, summary: true } }) })} c=${recorder()} />`)
  assert.equal(none.button(en.flow.activity.attach.button), null)
  // the summary: a click asks, a kept one shows with its model and time, outdated when rows came since
  el.button(en.flow.activity.summary.button).click()
  assert.deepEqual(c.calls.at(-1), ['flowSummary', 'task:a'])
  const kept = feedOf('task:a', { summary: { text: 'Drafted and reviewed.', since: '2026-10-02', at_ms: NOW - 30 * MIN, model: 'haiku', stale: true } })
  const sum = mount(html`<${FlowPage} s=${pointState({ ui: { flowTab: 'activity' }, feed: kept })} c=${recorder()} />`)
  assert.match(sum.$('.flow-act-sum').text(), /Drafted and reviewed\./)
  assert.match(sum.$('.flow-act-sum').text(), /Haiku/)
  assert.match(sum.$('.flow-act-sum').text(), new RegExp(en.flow.activity.summary.stale))
  // the summary off: no button
  const off = mount(html`<${FlowPage} s=${pointState({ ui: { flowTab: 'activity' }, flow: { summary: { enabled: false } } })} c=${recorder()} />`)
  assert.equal(off.button(en.flow.activity.summary.button), null)
})

test('the feed is read when a point opens, again when it is stale, never for the overview', async () => {
  const c = recorder()
  mount(html`<${FlowPage} s=${pointState({ feed: null })} c=${c} />`)
  await tick()
  assert.deepEqual(c.calls.filter(x => x[0] === 'loadActivity'), [['loadActivity', 'task:a']])
  const c2 = recorder()
  mount(html`<${FlowPage} s=${pointState()} c=${c2} />`)
  await tick()
  assert.equal(c2.calls.filter(x => x[0] === 'loadActivity').length, 0)
  const c3 = recorder()
  mount(html`<${FlowPage} s=${pointState({ feed: null, ui: { flowView: 'overview' } })} c=${c3} />`)
  await tick()
  assert.equal(c3.calls.filter(x => x[0] === 'loadActivity').length, 0)
  // invalidateDetails marks the feed of the row stale too, after a verb on it
  const d = logic.invalidateDetails({ inbox: {}, task: {}, activity: { 'task:a': { status: 'ok', ver: 0, data: {} } } }, task('a'))
  assert.equal(d.activity['task:a'].stale, true)
  assert.deepEqual(logic.invalidateDetails({ inbox: {}, task: {} }, task('a')).activity, {})
})

test('the right column: What you can do with the suggestion and the verbs stacked, then the fields; Status is no field', () => {
  const themes = themesState({ assign: { 'task:a': 't000001' }, suggest: { 'task:a': { verb: 'later', reason: 'Waits for the vendor', until: '2026-10-12', at_ms: NOW } } })
  const el = mount(html`<${FlowPage} s=${{ ...pointState(), themes }} c=${recorder()} />`)
  const aside = el.$('.flow-aside')
  assert.match(aside.$('.flow-can').text(), new RegExp(en.flow.fields.can))
  assert.match(aside.$('.flow-can-sug').text(), /Waits for the vendor/)
  assert.ok(aside.$('.flow-can .verbbar.is-stack'), 'the verbs stand under each other')
  // the suggested verb first and strong
  const first = aside.$('.flow-can .verbbar-row button')
  assert.ok(first.hasClass('btn-primary'))
  assert.equal(first.text(), `${en.flow.verbs.later} ▾`)
  const fields = aside.$$('.flow-fields dt').map(d => d.text())
  assert.deepEqual(fields, [en.flow.fields.theme, en.flow.fields.area, en.flow.fields.who, en.flow.fields.prio, en.flow.fields.urgency,
    en.flow.fields.impact, en.flow.fields.effort, en.flow.fields.due, en.flow.fields.source, en.flow.fields.created, en.flow.fields.moved])
  assert.ok(aside.$('[data-field=theme] select'), 'the theme can be changed there')
  assert.match(aside.$('[data-field=prio]').text(), new RegExp(`${en.flow.fields.quadrant.plan}.*Jev #4`))
  assert.ok(aside.$('[data-field=urgency] .meter-fill'))
  assert.match(aside.$('[data-field=source] a').getAttribute('href'), /example\.org\/tickets\/7/)
})

test('the right column by card: a live tab gives To tab and View, a finished start Done and close, the reports All seen', () => {
  // a tab that asks: To tab strong, View, no Let AI do it
  const asks = mount(html`<${FlowPage} s=${cockpitState(NOW, state({ work: [task('run')], tabs: [{ ref: 'surface:9', name: 'run', slug: 'run', state: 'needs-you', since_ms: NOW - MIN }] }))} c=${recorder()} />`)
  const can = asks.$('.flow-aside .flow-can')
  assert.equal(can.$$('button')[0].text(), en.flow.toTab)
  assert.ok(can.$$('button')[0].hasClass('btn-primary'))
  assert.equal(can.$$('button')[1].text(), en.flow.view)
  assert.equal(asks.button(`${en.flow.verbs.do} ▾`), null)
  // the reports: Seen for the ticked ones on the right, Seen on each report in the card
  const r = mount(html`<${FlowPage} s=${cockpitState(NOW, state({ now: [report('20261009-0901-a-r')] }))} c=${recorder()} />`)
  assert.ok(r.$('.flow-aside').$$('button').some(b => b.text() === en.flow.seenTicked(0)))
  assert.ok(!r.$('.flow-card').$$('button').some(b => b.text() === en.flow.allSeen))
})

test('the reports: Seen on the right settles only the ticked reports, All seen only when every one is ticked', () => {
  // 29.10.2026: one report open in the card, All seen on the right closed all five, read as the Seen of the open one
  const reps = [report('20261009-0901-a-r1'), report('20261009-0902-a-r2'), report('20261009-0903-a-r3')]
  const keys = reps.map(r => r.key)
  const right = el => el.$('.flow-aside .fx-do button')
  const settles = c => c.calls.filter(x => x[0] === 'act' && x[1] === 'settle')
  // nothing ticked: the button sends nothing and says what to do, a report opened in the card is not ticked by that
  const c0 = recorder()
  const none = mount(html`<${FlowPage} s=${cockpitState(NOW, state({ now: reps }))} c=${c0} />`)
  assert.equal(right(none).text(), en.flow.seenTicked(0))
  assert.ok(right(none).getAttribute('disabled') != null, 'disabled while nothing is ticked')
  right(none).click()
  assert.deepEqual(settles(c0), [])
  assert.equal(none.$('.flow-aside .flow-reports-hint').text(), en.flow.tickReports)
  // one ticked: only that one goes
  const c1 = recorder()
  const one = mount(html`<${FlowPage} s=${cockpitState(NOW, state({ now: reps, ui: { flowPicked: [keys[1]] } }))} c=${c1} />`)
  assert.equal(right(one).text(), en.flow.seenTicked(1))
  right(one).click()
  assert.deepEqual(settles(c1), [['act', 'settle', { keys: [keys[1]], outcome: 'done' }]])
  // every one ticked: All seen, for all of them
  const c2 = recorder()
  const every = mount(html`<${FlowPage} s=${cockpitState(NOW, state({ now: reps, ui: { flowPicked: keys } }))} c=${c2} />`)
  assert.equal(right(every).text(), en.flow.allSeen)
  right(every).click()
  assert.deepEqual(settles(c2), [['act', 'settle', { keys, outcome: 'done' }]])
  // the boxes in the card: one per report and All, one selection with the overview's (ui.flowPicked)
  const boxes = one.$$('.flow-reports > li input[type="checkbox"]')
  assert.deepEqual(boxes.map(b => b.getAttribute('aria-label')), reps.map(r => en.flow.list.pick(r.title)))
  boxes[0].click()
  assert.deepEqual(c1.calls.find(x => x[0] === 'flowPick'), ['flowPick', [keys[0]], true])
  one.$('.flow-reports-all input').click()
  assert.deepEqual(c1.calls.filter(x => x[0] === 'flowPick').at(-1), ['flowPick', keys, true])
  every.$('.flow-reports-all input').click()
  assert.deepEqual(c2.calls.find(x => x[0] === 'flowPick'), ['flowPick', keys, false])
  // the Seen of a report in the card stays its own
  one.$$('.flow-reports > li')[2].$$('button').find(b => b.text() === en.flow.seen).click()
  assert.deepEqual(settles(c1).at(-1), ['act', 'settle', { keys: [keys[2]], outcome: 'done' }])
  for (const lang of ['en', 'de']) {
    const f = text.TABLES[lang].flow
    assert.ok(f.tickReports && f.seenTicked(2) !== f.seenTicked(1), `${lang} words`)
  }
})

// ---------------------------------------------------------------- the buttons on the right by kind (29.10.2026)

/** The ways on the right of a point in their order, the strong one in brackets: every button and every link styled as
 *  one, Details and the STATUS.md link left out; `tail` only those set apart under the verbs (.verbbar-tail) */
function acts(el, tail = false) {
  const out = []
  const walk = (n, apart) => {
    if (n.nodeType !== 1) return
    const there = apart || n.hasClass('verbbar-tail')
    if (n.localName === 'button' || (n.localName === 'a' && n.hasClass('btn'))) {
      const w = n.text().trim()
      if ((!tail || there) && w && w !== en.flow.details && !/STATUS\.md$/.test(w)) out.push(n.hasClass('btn-primary') ? `[${w}]` : w)
      return
    }
    for (const k of n.childNodes) walk(k, there)
  }
  walk(el.$('.flow-aside'), false)
  return out
}
const panel = w => `${w} ▾`
const onTab = (st, over = {}) => ({ ref: 'surface:9', name: 'run', slug: 'run', state: st, since_ms: NOW - 18 * MIN, ...over })
const right = (st, c = recorder()) => mount(html`<${FlowPage} s=${cockpitState(NOW, st)} c=${c} />`)

test('the right column: no strong button without a suggestion, Advise is one verb among the others (B)', () => {
  const v = en.flow.verbs
  assert.deepEqual(acts(right(state({ now: [ask('20261009-0900-a-q')] }))), [panel(v.do), v.advise, v.done, panel(v.later), panel(v.drop)])
  // a suggestion still makes its verb the strong one, first
  const s = state({ now: [ask('20261009-0900-a-q')], themes: { enabled: true, assign: {}, themes: [], suggest: { 'inbox:20261009-0900-a-q': { verb: 'later', reason: 'x', at_ms: NOW } } } })
  assert.equal(acts(right(s))[0], `[${panel(v.later)}]`)
})

test('the right column: a finding with an action ready gives its yes first and strong (D)', () => {
  const v = en.flow.verbs
  const y = ask('20261009-0900-a-y', { gate: 'your-yes', has_action: true, art: 'finding' })
  assert.deepEqual(acts(right(state({ now: [y] }))), [`[${en.flow.approve}]`, panel(v.do), v.advise, v.done, panel(v.later), panel(v.drop)])
})

test('the right column: a task in review offers Done strong, then Improve, Later, Drop and Advise, no Let AI do it (C)', async () => {
  const v = en.flow.verbs
  const c = recorder()
  const el = right(state({ work: [task('r', { status: 'review' })] }), c)
  assert.deepEqual(acts(el), [`[${v.done}]`, panel(en.flow.improve.button), panel(v.later), panel(v.drop), v.advise])
  // Improve opens the sentence for a new start, which goes out only with words in it
  el.$$('.flow-aside button').find(b => b.text() === panel(en.flow.improve.button)).click()
  await until(() => el.$('.flow-aside .flow-improve textarea'))
  assert.ok(el.$('.flow-aside .flow-improve textarea'), 'the field for what is still to do')
})

test('the right column: an issue says Hide for what only leaves this list, Open on GitHub first (A)', () => {
  const v = en.flow.verbs
  const issue = ref('acme/app', 7, { bucket: 'do' })
  const el = right(state({ now: [issue] }))
  assert.deepEqual(acts(el), [en.flow.onWeb(issue.url), panel(v.do), v.advise, en.flow.hide, panel(v.later), panel(v.drop)])
  assert.equal(en.flow.onWeb('https://github.com/acme/app/issues/7'), 'Open on GitHub')
  const a = el.$('.flow-aside a.btn')
  assert.equal(a.getAttribute('href'), issue.url)
  assert.equal(a.getAttribute('target'), '_blank')
  for (const lang of ['en', 'de']) assert.ok(text.TABLES[lang].flow.hide && text.TABLES[lang].flow.onWeb, lang)
})

// ---------------------------------------------------------------- an issue on a board: review and done (29.10.2026)

const PLAN = (over = {}) => ({ ok: true, ref: 'acme/app#7', type: 'issue', state: 'OPEN', url: 'https://github.com/acme/app/issues/7', unmatched: [],
  boards: [{ slug: 'ops', title: 'Ops', owner: 'acme', number: 7, status: 'In Progress', review_state: 'In Review', done_state: 'Done',
    in_review: false, in_done: false, rules: ['done_requires_review', 'done_only_by_user'] }], ...over })
/** A recorder whose issuePlan answers with `plan` (GET /api/issue) */
const withPlan = plan => {
  const c = recorder()
  return new Proxy(c, { get: (t, p) => (p === 'issuePlan' ? (ref => { t.calls.push(['issuePlan', ref]); return Promise.resolve(plan) }) : t[p]) })
}
const gitIssue = (over = {}) => ref('acme/app', 7, { bucket: 'do', url: 'https://github.com/acme/app/issues/7', ...over })
const iw = en.flow.issue
/** Until the card read its board: the line no longer says it is reading */
const read = el => until(() => el.$('.flow-issue-on') && el.$('.flow-issue-on').text() !== iw.loading)

test('an issue on a board: Set to review and Done after Open on GitHub, the board and its status above them', async () => {
  const v = en.flow.verbs
  const c = withPlan({ ok: true, data: PLAN() })
  const el = right(state({ now: [gitIssue()] }), c)
  await read(el)
  assert.deepEqual(c.calls.find(x => x[0] === 'issuePlan'), ['issuePlan', 'acme/app#7'])
  assert.match(el.$('.flow-issue-on').text(), /Ops: In Progress/)
  assert.deepEqual(acts(el), [en.flow.onWeb('https://github.com/acme/app/issues/7'), panel(iw.review), panel(iw.done), iw.check, panel(v.do), v.advise,
    en.flow.hide, panel(v.later), panel(v.drop)])
})

test('Set to review asks what is done first, then sends issue_review with it', async () => {
  const c = withPlan({ ok: true, data: PLAN() })
  const el = right(state({ now: [gitIssue()] }), c)
  await read(el)
  el.$$('.flow-aside button').find(b => b.text() === panel(iw.review)).click()
  await until(() => el.$('.flow-issue-panel textarea'))
  const send = () => el.$$('.flow-issue-panel button').find(b => b.text() === iw.sendReview)
  assert.ok(send().getAttribute('disabled') != null, 'no review comment without a reason')
  const box = el.$('.flow-issue-panel textarea')
  box.value = 'Deployed and verified'
  box.dispatch('input')
  await until(() => send().getAttribute('disabled') == null)
  send().click()
  await until(() => c.calls.some(x => x[0] === 'act'))
  assert.deepEqual(c.calls.find(x => x[0] === 'act'), ['act', 'issue_review', { key: 'ref:acme/app#7', text: 'Deployed and verified' }])
})

test('Done says what the click will do and the board rules before it sends issue_done', async () => {
  const c = withPlan({ ok: true, data: PLAN() })
  const el = right(state({ now: [gitIssue()] }), c)
  await read(el)
  el.$$('.flow-aside button').find(b => b.text() === panel(iw.done)).click()
  await until(() => el.$('.flow-issue-panel'))
  const p = el.$('.flow-issue-panel').text()
  assert.ok(p.includes(iw.steps([iw.comment, 'In Review', 'Done', iw.close].join(', '))), p)
  assert.ok(p.includes(iw.rules('done_requires_review, done_only_by_user')), p)
  el.$$('.flow-issue-panel button').find(b => b.text() === iw.confirmDone).click()
  await until(() => c.calls.some(x => x[0] === 'act'))
  assert.deepEqual(c.calls.find(x => x[0] === 'act'), ['act', 'issue_done', { key: 'ref:acme/app#7' }])
})

test('the AI suggests closing: the button that fits is the strong one, its reason already in the field, Hide stays plain', async () => {
  const s = state({ now: [gitIssue()], themes: { enabled: true, assign: {}, themes: [], suggest: { 'ref:acme/app#7': { verb: 'done', reason: 'PR #9 is merged', at_ms: NOW } } } })
  const c = withPlan({ ok: true, data: PLAN() })
  const el = right(s, c)
  await read(el)
  const all = acts(el)
  assert.equal(all[1], `[${panel(iw.review)}]`, all.join(' | '))
  assert.ok(all.includes(en.flow.hide), 'Hide is no longer strong')
  el.$$('.flow-aside button').find(b => b.text() === panel(iw.review)).click()
  await until(() => el.$('.flow-issue-panel textarea'))
  const box = el.$('.flow-issue-panel textarea')
  assert.equal(box.value ?? box.getAttribute('value'), 'PR #9 is merged')
  // in review already: Done is the one that fits
  const inReview = PLAN({ boards: [{ ...PLAN().boards[0], status: 'In Review', in_review: true }] })
  const el2 = right(s, withPlan({ ok: true, data: inReview }))
  await read(el2)
  assert.ok(!acts(el2).includes(panel(iw.review)))
  assert.ok(acts(el2).includes(`[${panel(iw.done)}]`), acts(el2).join(' | '))
})

test('a board of the issue that workflow/projects/ does not know is named, and Done passes through review on any board with review states', async () => {
  const plan = PLAN({ unmatched: [{ owner: 'acme', number: 3, title: 'Roadmap' }],
    boards: [{ ...PLAN().boards[0], rules: [] }] })
  const el = right(state({ now: [gitIssue()] }), withPlan({ ok: true, data: plan }))
  await read(el)
  assert.equal(el.$('.flow-issue-other').text(), iw.other('Roadmap'))
  el.$$('.flow-aside button').find(b => b.text() === panel(iw.done)).click()
  await until(() => el.$('.flow-issue-panel'))
  assert.ok(el.$('.flow-issue-panel').text().includes(iw.steps([iw.comment, 'In Review', 'Done', iw.close].join(', '))))
})

test('Check with AI: the click sends issue_check, its done makes the fitting button strong with its comment in the field', async () => {
  const done = { verdict: 'done', reason: 'Both boxes ticked, #13 merged', evidence: ['#13 merged'], missing: [],
    comment: 'Parser fixed in #13, test added.', model: 'claude-haiku-5-5', at: '2026-10-29T18:30:00' }
  const base = withPlan({ ok: true, data: PLAN() })
  const c = new Proxy(base, { get: (t, p) => (p === 'act' ? ((verb, args) => { t.calls.push(['act', verb, args]); return Promise.resolve({ ok: true, issue_check: done }) }) : t[p]) })
  const el = right(state({ now: [gitIssue()] }), c)
  await read(el)
  assert.ok(!el.$('.flow-issue-check'), 'no verdict before a check')
  assert.ok(!acts(el).some(w => w.startsWith('[')), 'nothing strong without a suggestion')
  el.$$('.flow-aside button').find(b => b.text() === iw.check).click()
  await until(() => el.$('.flow-issue-check'))
  assert.deepEqual(c.calls.find(x => x[0] === 'act'), ['act', 'issue_check', { key: 'ref:acme/app#7' }])
  assert.match(el.$('.flow-issue-check').text(), new RegExp(`${iw.verdict.done}.*Both boxes ticked`))
  assert.ok(el.$('.flow-issue-check').text().includes('#13 merged'))
  assert.equal(acts(el)[1], `[${panel(iw.review)}]`)
  el.$$('.flow-aside button').find(b => b.text() === panel(iw.review)).click()
  await until(() => el.$('.flow-issue-panel textarea'))
  const box = el.$('.flow-issue-panel textarea')
  assert.equal(box.value ?? box.getAttribute('value'), 'Parser fixed in #13, test added.')
})

test('a kept check comes back with the plan, and its not done outweighs the triage', async () => {
  const kept = { verdict: 'not_done', reason: 'The test box is open', evidence: [], missing: ['a test'], comment: '', model: 'claude-sonnet-5-5', at: '2026-10-29T18:00:00' }
  const s = state({ now: [gitIssue()], themes: { enabled: true, assign: {}, themes: [], suggest: { 'ref:acme/app#7': { verb: 'done', reason: 'x', at_ms: NOW } } } })
  const el = right(s, withPlan({ ok: true, data: PLAN({ check: kept }) }))
  await read(el)
  assert.match(el.$('.flow-issue-check').text(), new RegExp(iw.verdict.not_done))
  assert.ok(el.$('.flow-issue-check').text().includes('a test'))
  assert.ok(!acts(el).some(w => w.startsWith('[')), acts(el).join(' | '))
  for (const lang of ['en', 'de']) assert.ok(text.TABLES[lang].flow.issue.verdict.unclear && text.TABLES[lang].flow.issue.check, lang)
})

test('an issue on no board of workflow/projects/ and a pull request keep Hide only', async () => {
  const none = right(state({ now: [gitIssue()] }), withPlan({ ok: true, data: PLAN({ boards: [] }) }))
  await read(none)
  assert.equal(none.$('.flow-issue-on').text(), iw.none)
  assert.ok(!acts(none).some(w => w.includes(iw.review) || w.includes(iw.done)))
  const c = withPlan({ ok: true, data: PLAN() })
  const pr = right(state({ now: [gitIssue({ url: 'https://github.com/acme/app/pull/7' })] }), c)
  assert.ok(!pr.$('.flow-issue-on'))
  assert.ok(!c.calls.some(x => x[0] === 'issuePlan'), 'a pull request reads no board plan')
  for (const lang of ['en', 'de']) assert.ok(text.TABLES[lang].flow.issue.confirmDone, lang)
})

test('the right column: the return card has one way back, Runs on (E)', () => {
  const v = en.flow.verbs
  const el = right(state({ work: [task('other')], tabs: [onTab('waiting', { ref: 'surface:5', slug: 'other' })],
    ui: { flowJump: { key: 'task:other', ref: 'surface:5', title: 'x', at: NOW - MIN, armed: true } } }))
  assert.deepEqual(acts(el), [`[${v.done}]`, panel(v.later), panel(v.drop), en.flow.runsOn])
})

test('the right column: a tab waiting at its prompt puts its close last and apart (F)', () => {
  const v = en.flow.verbs
  const el = right(state({ work: [task('run')], tabs: [onTab('waiting')] }))
  const all = acts(el)
  assert.deepEqual(all.slice(0, 6), [`[${en.flow.toTab}]`, en.flow.view, v.advise, v.done, panel(v.later), panel(v.drop)])
  assert.deepEqual(acts(el, true), all.slice(6))
  assert.ok(acts(el, true).includes(en.btnCloseTab), 'the close stands apart')
})

test('the right column: while a tab asks, only To tab, View, Advise and Later; nothing closes what waits for you (H)', () => {
  const v = en.flow.verbs
  assert.deepEqual(acts(right(state({ work: [task('run')], tabs: [onTab('needs-you')] }))),
    [`[${en.flow.toTab}]`, en.flow.view, v.advise, panel(v.later)])
})

test('the right column: a finished start, View and Improve right after Done, the tab ways apart at the end (G)', () => {
  const v = en.flow.verbs
  const el = right(state({ work: [task('fin')], tabs: [onTab('waiting', { ref: 'surface:10', slug: 'fin' })],
    returns: [startOf('fin', 'result', { tab: { ref: 'surface:10' }, result: { kind: 'note', text: 'Result: done', key: null, at_ms: null } })] }))
  const all = acts(el)
  assert.deepEqual(all.slice(0, 6), [`[${en.flow.doneClose}]`, en.flow.view, panel(en.flow.improve.button), en.flow.runsOn, panel(v.later), panel(v.drop)])
  assert.deepEqual(acts(el, true)[0], en.flow.toTab)
  assert.deepEqual(acts(el, true), all.slice(6))
})

test('the right column: where the close of the tab behind it ends the point, Done and close tab stands with the verbs', () => {
  // a tab waiting at its prompt with the task behind it: its close offers Done for it (besideClose takes Done out of
  // the verbs), so that Done stands right after the tab's ways, not apart at the end (review 29.10.2026)
  const wait = { ref: 'surface:12', name: 'a', slug: 'a', state: 'waiting', behind: { task: 'a', item: null }, since_ms: NOW - 14 * MIN }
  const v = en.flow.verbs
  const all = acts(right(state({ work: [task('a')], tabs: [wait] })))
  assert.deepEqual(all, [`[${en.flow.toTab}]`, en.flow.view, en.btnDoneCloseTab, en.btnCloseTabOnly, v.advise, panel(v.later), panel(v.drop)])
  // a driver that closes tabs but starts none still shows that Done
  const noLaunch = acts(right({ ...state({ work: [task('a')], tabs: [wait] }), driver: { caps: ['close'] } }))
  assert.ok(noLaunch.includes(en.btnDoneCloseTab), noLaunch.join(' | '))
})

test('the reports say Done like every other card (I)', () => {
  assert.equal(en.flow.seen, 'Done')
  assert.equal(en.flow.allSeen, 'All done')
  assert.equal(text.TABLES.de.flow.seen, 'Erledigt')
  assert.equal(text.TABLES.de.flow.allSeen, 'Alle erledigt')
  assert.equal(text.TABLES.de.flow.seenTicked(2), 'Erledigt (2 angehakt)')
})

test('Details at the point (round 6 B): an inbox item or a task opens its drawer, any other row its detail column, a report its own', () => {
  const details = el => el.$$('.flow-aside .flow-can button').filter(b => b.text() === en.flow.details)
  const q = ask('20261009-0900-a-q1')
  const t = task('a')
  const issue = ref('acme/app', 7, { bucket: 'do' })
  for (const [s, call] of [[state({ now: [q] }), ['openItem', q.key]], [state({ work: [t] }), ['openItem', t.key]],
    [state({ now: [issue] }), ['peek', issue.key, null]]]) {
    const c = recorder()
    const el = mount(html`<${FlowPage} s=${cockpitState(NOW, s)} c=${c} />`)
    const links = details(el)
    assert.equal(links.length, 1, `one Details at ${call[1]}`)
    assert.ok(links[0].hasClass('btn-link'), 'a link in the style of the column, below the verbs')
    links[0].click()
    const got = c.calls.find(x => x[0] === call[0])
    assert.ok(got, `${call[0]} for ${call[1]}`)
    assert.deepEqual(got.slice(0, call.length), call)
    if (call[0] === 'openItem') assert.equal(got[2]?.key, call[1], 'the drawer gets the row')
  }
  // the reports: one point of many rows, so Details stands on each report in the card, beside its Seen
  const reps = [report('20261009-0901-a-r'), report('20261009-0902-a-r')]
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${cockpitState(NOW, state({ now: reps }))} c=${c} />`)
  assert.equal(details(el).length, 0)
  const each = el.$$('.flow-reports > li').map(li => li.$$('button').find(b => b.text() === en.flow.details))
  assert.equal(each.filter(Boolean).length, 2)
  each[1].click()
  assert.deepEqual(c.calls.find(x => x[0] === 'openItem').slice(0, 2), ['openItem', reps[1].key])
  for (const lang of ['en', 'de']) assert.equal(text.TABLES[lang].flow.details, 'Details')
})

test('nothing twice: state in the card head, who and source in the fields, the screen in the card, the suggestion on the right', () => {
  const busy = { ref: 'surface:21', name: 'busy', slug: 'a', state: 'working', since_ms: NOW - 18 * MIN, last: 'Running the tests' }
  const themes = themesState({ assign: { 'task:a': 't000001' }, suggest: { 'task:a': { verb: 'done', reason: 'Merged', at_ms: NOW } } })
  const el = mount(html`<${FlowPage} s=${{ ...pointState({ tabs: [busy] }), themes }} c=${recorder()} />`)
  const card = el.$('.flow-card')
  const aside = el.$('.flow-aside')
  const tabs = el.$('.flow-ptabs')
  const where = (sel) => [card, aside, tabs].map(x => x.$$(sel).length)
  assert.deepEqual(where('.fx-kind'), [1, 0, 0], 'the state once, in the card head')
  assert.deepEqual(where('.state-line'), [0, 0, 0], 'who drives it is the field, no state line of its tab')
  assert.deepEqual(where('.fx-screen'), [1, 0, 0], 'the screen once, in the card')
  assert.deepEqual(where('.origin'), [0, 1, 0], 'the source once, in the fields')
  assert.deepEqual(where('.flow-sug'), [0, 1, 0], 'the suggestion once, on the right')
  assert.deepEqual(where('[data-field=who]'), [0, 1, 0], 'who works on it once, in the fields')
  assert.equal(aside.$$('dt').filter(d => /status|state/i.test(d.text())).length, 0)
})

test('instructScope: the open point, with its tab where it takes typed words; in the overview the ticked points, else every point of the side, at most 50', () => {
  const busy = { ref: 'surface:21', name: 'busy', slug: 'a', state: 'working', since_ms: NOW - MIN }
  const s = pointState({ tabs: [busy] })
  const q = queueOf(s)
  const one = logic.instructScope(pointOf(s, 'task:a'), q, new Set(), 'Ops', s)
  assert.deepEqual([one.point, one.keys, one.title, one.tab?.ref], [true, ['task:a'], 'Task a', undefined])
  // a reply goes only to a tab that waits at its prompt (replyOptions: a text box), not to one at work or asking a choice
  for (const [state, ref] of [['waiting', 'surface:21'], ['needs-you', undefined]]) {
    const w = pointState({ tabs: [{ ...busy, state }] })
    const wq = queueOf(w)
    assert.equal(logic.instructScope(pointOf(w, 'task:a'), wq, new Set(), 'Ops', w).tab?.ref, ref, state)
  }
  const many = state({ work: Array.from({ length: 60 }, (_, i) => task(`t${i}`)) })
  const all = queueOf(many)
  const side = logic.instructScope(null, all, new Set(), 'Ops', many)
  assert.deepEqual([side.point, side.picked, side.n, side.keys.length, side.cut], [false, false, 60, 50, true])
  const picked = logic.instructScope(null, all, new Set(['task:t3', 'task:t5']), 'Ops', many)
  assert.deepEqual([picked.picked, picked.keys], [true, ['task:t3', 'task:t5']])
  // the reports card: every report, or the ticked ones where some are ticked
  const reps = state({ now: [report('20261009-0901-a-r1'), report('20261009-0902-a-r2')] })
  const card = queueOf(reps).find(x => x.kind === 'reports')
  const cardAll = logic.instructScope(card, queueOf(reps), new Set(), null, reps)
  assert.deepEqual([cardAll.reports, cardAll.picked, cardAll.keys], [true, false, card.rows.map(r => r.key)])
  const cardOne = logic.instructScope(card, queueOf(reps), new Set([card.rows[1].key, 'task:elsewhere']), null, reps)
  assert.deepEqual([cardOne.reports, cardOne.picked, cardOne.keys], [true, true, [card.rows[1].key]])
  // the words of the label
  assert.equal(en.flow.instruct.point('Task a'), 'For: Task a')
  assert.match(en.flow.instruct.side(60, 'Ops'), /60 points in Ops/)
})

test('instructCalls: each step through its verb with by instruction, done for several as one settle, a reply to its tab', () => {
  // the tab a reply goes to (the plan names it), no tab of the task: Let AI do it may start on task a
  const live = { ref: 'surface:3', name: 'helper', state: 'waiting', since_ms: NOW - MIN }
  const asks = { ref: 'surface:5', name: 'asker', state: 'needs-you', since_ms: NOW - MIN, ask: { options: [{ n: 1, label: 'Yes' }] } }
  const s = state({ work: [task('a'), task('b'), task('busy')], tabs: [live, asks, { ref: 'surface:4', name: 'busy', slug: 'busy', state: 'working' }] })
  const plan = { id: 'p1', text: 'x', point: false, steps: [
    { n: 1, op: 'done', keys: ['task:a', 'task:b'], titles: ['Task a', 'Task b'], skipped: [] },
    { n: 2, op: 'later', keys: ['task:b'], until: '2026-10-12', skipped: [] },
    { n: 3, op: 'drop', keys: ['task:a'], reason: 'not_needed', skipped: [] },
    { n: 4, op: 'do', mail: true, keys: ['task:a', 'task:busy'], note: 'Write a mail draft, a draft only, never send it: ask about the prices', skipped: [] },
    { n: 5, op: 'reply', keys: ['task:a'], tab_ref: 'surface:3', text: 'yes, go on', skipped: [] },
    { n: 6, op: 'done', keys: ['task:gone'], skipped: [] },
    // a tab that asks a choice takes its options on the card, never typed words (actions_tabs.py tab_send)
    { n: 7, op: 'reply', keys: ['task:b'], tab_ref: 'surface:5', text: 'yes', skipped: [] },
  ], unclear: null }
  const { calls, skipped } = logic.instructCalls(plan, s, 'en')
  assert.deepEqual(calls, [
    { verb: 'settle', args: { keys: ['task:a', 'task:b'], outcome: 'done', by: 'instruction' } },
    { verb: 'later', args: { key: 'task:b', until: '2026-10-12', by: 'instruction' } },
    { verb: 'shelve', args: { key: 'task:a', reason: en.flow.drop.reason.not_needed, by: 'instruction' } },
    { verb: 'do_it', args: { keys: ['task:a'], note: 'Write a mail draft, a draft only, never send it: ask about the prices', by: 'instruction' } },
    { verb: 'tab_send', args: { tab_ref: 'surface:3', text: 'yes, go on', expect: 'waiting', name: 'helper' } },
  ])
  assert.deepEqual(skipped.map(x => [x.key, x.why]), [['task:busy', 'working'], ['task:gone', 'gone'], ['task:b', 'asks']])
  for (const lang of ['en', 'de']) assert.ok(text.TABLES[lang].flow.instruct.skipped.asks, 'the why is worded')
  // a reply whose tab is gone runs nothing
  assert.deepEqual(logic.instructCalls({ steps: [{ op: 'reply', keys: ['task:a'], tab_ref: 'surface:99', text: 'y', skipped: [] }] }, s, 'en').calls, [])
  assert.deepEqual(logic.instructCalls(null, s, 'en'), { calls: [], skipped: [] })
})

test('the instruction line: one row while empty, its scope above it, Send asks the server, the plan with Run, Change and Discard', async () => {
  const live = { ref: 'surface:21', name: 'busy', slug: 'a', state: 'waiting', since_ms: NOW - MIN }
  const c = recorder()
  // two points, so the walk bar stands under the line; a question about the task whose tab waits (round 4: the task's own
  // row would run, in Running now, where no walk bar stands)
  const q = ask('20261009-0900-a-q', { task: 'a', title: 'Task a', area: 'Ops' })
  const el = mount(html`<${FlowPage} s=${pointState({ rows: [q, task('b', { area: 'Ops' })], feed: feedOf(q.key), tabs: [live] })} c=${c} />`)
  const line = el.$('.flow-instruct')
  assert.ok(line, 'the line stands on a point')
  assert.ok(nextEl(line).hasClass('flow-walk'), 'right above the walk bar')
  assert.match(line.$('.flow-instruct-scope').text(), new RegExp(`${en.flow.instruct.point('Task a')}.*${en.flow.instruct.reply}`))
  const box = line.$('textarea')
  assert.equal(box.getAttribute('rows'), '1')
  assert.ok(el.button(en.flow.instruct.send).hasAttribute('disabled'))
  box.value = 'done, and ask the vendor about the prices'
  box.dispatch('input')
  await tick()
  el.button(en.flow.instruct.send).click()
  await tick()
  assert.deepEqual(c.calls.find(x => x[0] === 'flowInstruct'), ['flowInstruct', 'done, and ask the vendor about the prices', [q.key], true])
  // a plan came: this is how I understood it, the steps in words, what stays out muted with why, Run, Change, Discard
  const plan = { id: 'p1', text: 'done, and ask the vendor about the prices', point: true, n: 1, steps: [
    { n: 1, op: 'done', keys: ['task:a'], titles: ['Task a'], skipped: [] },
    { n: 2, op: 'do', mail: true, keys: ['task:a'], titles: ['Task a'], note: 'Write a mail draft, a draft only, never send it: ask the vendor', skipped: [] },
    { n: 3, op: 'later', keys: [], titles: [], until: '2026-10-09', skipped: [{ key: 'task:a', title: 'Task a', why: 'bad_day' }] }],
    unclear: 'Which vendor?', model: 'haiku', at_ms: NOW }
  // (no tab of the task here: Let AI do it starts only where no agent works on it yet, as in a batch)
  const c2 = recorder()
  const p = mount(html`<${FlowPage} s=${pointState({ ui: { flowPlan: plan } })} c=${c2} />`)
  const panel = p.$('.flow-instruct-plan')
  assert.match(panel.text(), new RegExp(en.flow.instruct.understood))
  assert.equal(panel.$$('.flow-instruct-step').length, 3)
  assert.match(panel.text(), new RegExp(en.flow.instruct.op.mail))
  assert.match(panel.$('.flow-instruct-skip').text(), new RegExp(en.flow.instruct.skipped.bad_day))
  assert.match(panel.text(), /Which vendor\?/)
  p.button(en.flow.instruct.run).click()
  await tick()
  const batch = c2.calls.find(x => x[0] === 'flowBatch')
  assert.deepEqual(batch[1].map(x => x.verb), ['settle', 'do_it'])
  assert.equal(batch[2], 'instruct')
  p.button(en.flow.instruct.discard).click()
  assert.deepEqual(c2.calls.at(-1), ['flowPlan', null])
  // Change: the sentence back in the field, the plan gone
  const c3 = recorder()
  const ch = mount(html`<${FlowPage} s=${pointState({ tabs: [live], ui: { flowPlan: plan } })} c=${c3} />`)
  ch.button(en.flow.instruct.change).click()
  await tick()
  const ta = ch.$('.flow-instruct textarea')
  assert.equal(ta.value ?? ta.getAttribute('value'), plan.text)
  assert.deepEqual(c3.calls.at(-1), ['flowPlan', null])
  // nothing runnable: Run is off
  const empty = { ...plan, steps: [plan.steps[2]] }
  const off = mount(html`<${FlowPage} s=${pointState({ ui: { flowPlan: empty } })} c=${recorder()} />`)
  assert.ok(off.button(en.flow.instruct.run).hasAttribute('disabled'))
  // in the overview: the ticked points or the whole side, and the line stays without a walk bar
  const ov = mount(html`<${FlowPage} s=${pointState({ ui: { flowView: 'overview', flowSide: { areas: 'a:ops' } } })} c=${recorder()} />`)
  assert.match(ov.$('.flow-instruct-scope').text(), new RegExp(en.flow.instruct.side(1, 'Ops')))
  // off by default: no line
  const no = mount(html`<${FlowPage} s=${pointState({ flow: { instruct: { enabled: false } } })} c=${recorder()} />`)
  assert.equal(no.$('.flow-instruct'), null)
})

test('the texts of round 3: both languages, the sixteen refusals worded, no key named, no dash', () => {
  for (const lang of ['en', 'de']) {
    const t = text.TABLES[lang]
    for (const code of ['flow_off', 'summary_off', 'summary_budget', 'summary_running', 'summary_empty', 'summary_unavailable', 'summary_failed',
      'instruct_off', 'instruct_budget', 'instruct_running', 'instruct_unavailable', 'instruct_failed', 'attach_off', 'attach_no_task',
      'attach_too_big', 'attach_exists']) assert.ok(t.errors[code], `${lang} ${code}`)
    for (const id of logic.ACTIVITY_FILTERS) assert.ok(t.flow.activity.filter[id], `${lang} filter ${id}`)
    for (const id of logic.FLOW_TABS) assert.ok(t.flow.ptabs[id], `${lang} tab ${id}`)
  }
  const de = text.TABLES.de.flow
  assert.deepEqual([de.ptabs.desc, de.ptabs.steps, de.ptabs.activity, de.ptabs.related], ['Beschreibung', 'Schritte', 'Aktivität', 'Verwandt'])
  assert.deepEqual(logic.ACTIVITY_FILTERS.map(id => de.activity.filter[id]), ['Alles', 'Notizen', 'Dokumente', 'Zustand', 'Agenten', 'Code'])
  assert.equal(de.fields.can, 'Was du tun kannst')
  assert.equal(de.instruct.understood, 'So habe ich es verstanden')
  assert.deepEqual([de.instruct.run, de.instruct.change, de.instruct.discard], ['Ausführen', 'Ändern', 'Verwerfen'])
})

// ---------------------------------------------------------------- round 3: the demo fakes every new route

test('the demo: the activity of the demo task carries every kind and every filter, an inbox key a short one, any other key its creation', async () => {
  const tr = mock.createMockTransport({ lang: 'en', latency: 0 })
  const st = (await tr.get('/api/state')).data
  assert.deepEqual(Object.keys(st.flow_ai).sort(), ['instruct_left', 'instruct_running', 'summary_left'])
  for (const k of ['summary', 'instruct', 'attach']) assert.equal(st.work.flow[k].enabled, true, k)
  const r = await tr.get('/api/flow/activity?key=task:demo-task')
  assert.equal(r.ok, true)
  const feed = r.data
  const kinds = new Set(feed.rows.map(x => x.kind))
  for (const k of ['note', 'log', 'doc', 'status', 'theme', 'decision', 'created', 'agent', 'session', 'code']) assert.ok(kinds.has(k), k)
  for (const f of logic.ACTIVITY_FILTERS.slice(1)) assert.ok(feed.counts[f] > 0, f)
  assert.equal(feed.counts.all, feed.rows.length)
  assert.deepEqual(logic.activityCounts({ rows: feed.rows }), feed.counts)
  assert.ok(feed.facts.jev && feed.facts.jev.rank > 0)
  // newest first, each row with an id unique in the answer
  const ms = feed.rows.map(x => x.at_ms ?? Date.parse(x.at))
  assert.deepEqual(ms, [...ms].sort((a, b) => b - a))
  assert.equal(new Set(feed.rows.map(x => x.id)).size, feed.rows.length)
  // an inbox item that names the demo task reads its feed; another item has a short one of its own
  const review = st.model.sections.flatMap(x => x.rows).find(x => x.inbox_id && x.task === 'demo-task')
  assert.equal((await tr.get(`/api/flow/activity?key=${encodeURIComponent(review.key)}`)).data.counts.all, feed.counts.all)
  const inbox = st.model.sections.flatMap(x => x.rows).find(x => x.inbox_id === '20261009-0915-update-docs-e5f6')
  const short = (await tr.get(`/api/flow/activity?key=${encodeURIComponent(inbox.key)}`)).data
  assert.ok(short.rows.length >= 2 && short.rows.length < feed.rows.length)
  const started = new Set((st.model.returns ?? []).map(r => r.key))
  const other = st.model.sections.flatMap(x => x.rows).find(x => x.task && x.key !== 'task:demo-task' && !x.inbox_id && !started.has(x.key))
  const one = (await tr.get(`/api/flow/activity?key=${encodeURIComponent(other.key)}`)).data
  assert.deepEqual(one.rows.map(x => x.kind), ['created'])
  assert.equal(one.facts.jev, null)
  // a row started from the cockpit lists that start among its agents, as activity.py does
  const run = st.model.sections.flatMap(x => x.rows).find(x => started.has(x.key) && x.task !== 'demo-task' && !x.inbox_id)
  const ran = (await tr.get(`/api/flow/activity?key=${encodeURIComponent(run.key)}`)).data
  assert.ok(ran.counts.agents >= 1, run.key)
  assert.equal((await tr.get('/api/flow/activity?key=task:nowhere')).error.code, 'stale_row')
  // a document opens from a Blob of invented text
  const href = tr.href('/api/flow/doc?slug=demo-task&path=deliverables%2Fguide-draft.md')
  assert.match(href, /^blob:/)
  assert.equal(tr.href('/api/state'), '/api/state')
  // off with ?flow=0
  const off = mock.createMockTransport({ lang: 'en', latency: 0, flow: false })
  assert.equal((await off.get('/api/flow/activity?key=task:demo-task')).error.code, 'flow_off')
})

test('the demo: a note and an attachment come into the feed, an attachment refused by the rules', async () => {
  const tr = mock.createMockTransport({ lang: 'en', latency: 0 })
  const before = (await tr.get('/api/flow/activity?key=task:demo-task')).data.counts
  let r = await tr.post('/api/action', { verb: 'note', args: { key: 'task:demo-task', text: 'Asked the team for screenshots' } })
  assert.equal(r.ok, true)
  r = await tr.post('/api/flow/attach', { key: 'task:demo-task', name: 'notes.txt', data: 'aGk=' })
  assert.equal(r.ok, true)
  assert.equal(r.data.attach.path, 'deliverables/notes.txt')
  assert.equal(r.data.attach.bytes, 2)
  const after = (await tr.get('/api/flow/activity?key=task:demo-task&fresh=1')).data
  assert.equal(after.counts.notes, before.notes + 1)
  assert.equal(after.counts.docs, before.docs + 1)
  assert.equal(after.rows[0].kind, 'doc')
  assert.equal(after.rows[0].doc.attached, true)
  // the same name again gets -2; a bad name, bad data, too big, a point without a task are refused
  assert.equal((await tr.post('/api/flow/attach', { key: 'task:demo-task', name: 'notes.txt', data: 'aGk=' })).data.attach.name, 'notes-2.txt')
  assert.equal((await tr.post('/api/flow/attach', { key: 'task:demo-task', name: '../../etc/passwd', data: 'aGk=' })).data.attach.path, 'deliverables/passwd')
  assert.equal((await tr.post('/api/flow/attach', { key: 'task:demo-task', name: '...', data: 'aGk=' })).error.code, 'invalid_argument')
  assert.equal((await tr.post('/api/flow/attach', { key: 'task:demo-task', name: 'a.txt', data: '%%%' })).error.code, 'invalid_argument')
  assert.equal((await tr.post('/api/flow/attach', { key: 'task:demo-task', name: 'a.bin', data: 'A'.repeat(15 * 1048576) })).error.code, 'attach_too_big')
  const st = (await tr.get('/api/state')).data
  const lone = st.model.sections.flatMap(x => x.rows).find(x => x.inbox_id && !x.task)
  assert.equal((await tr.post('/api/flow/attach', { key: lone.key, name: 'a.txt', data: 'aGk=' })).error.code, 'attach_no_task')
  // the verb takes the same way
  r = await tr.post('/api/action', { verb: 'flow_attach', args: { key: 'task:demo-task', name: 'b.txt', data: 'aGk=' } })
  assert.equal(r.data.attach.name, 'b.txt')
})

test('the demo: the summary within its budget and kept while nothing changed, the instruction by a fixed word match', async () => {
  const tr = mock.createMockTransport({ lang: 'de', latency: 0 })
  let r = await tr.post('/api/action', { verb: 'flow_activity_summary', args: { key: 'task:demo-task' } })
  assert.equal(r.ok, true)
  assert.ok(r.data.summary.text.length > 20)
  assert.doesNotMatch(r.data.summary.text, /[\u2014\u2013]| - /)
  assert.equal(r.data.summary.cached, false)
  assert.equal(r.data.flow_ai.summary_left, 9)
  r = await tr.post('/api/action', { verb: 'flow_activity_summary', args: { key: 'task:demo-task' } })
  assert.equal(r.data.summary.cached, true)
  assert.equal(r.data.flow_ai.summary_left, 9, 'a kept summary costs nothing')
  // the instruction: done and a mail, the mail becomes a start that drafts only
  r = await tr.post('/api/action', { verb: 'flow_instruct', args: { text: 'erledigt, und schreib eine Mail an den Anbieter', keys: ['task:demo-task'], point: true } })
  assert.equal(r.ok, true)
  const ops = r.data.plan.steps.map(x => [x.op, x.mail ?? false])
  assert.deepEqual(ops, [['done', false], ['do', true]])
  assert.match(r.data.plan.steps[1].note, /mail-draft/)
  assert.equal(r.data.flow_ai.instruct_left, 29)
  // a reply only with the point open and a live tab; in the overview it stays out with no_tab
  r = await tr.post('/api/action', { verb: 'flow_instruct', args: { text: 'antworte: ja, weiter', keys: ['task:demo-task'], point: false } })
  assert.deepEqual(r.data.plan.steps[0].skipped.map(x => x.why), ['no_tab'])
  r = await tr.post('/api/action', { verb: 'flow_instruct', args: { text: 'antworte: ja, weiter', keys: ['task:demo-task'], point: true } })
  assert.equal(r.data.plan.steps[0].op, 'reply')
  assert.ok(r.data.plan.steps[0].tab_ref)
  r = await tr.post('/api/action', { verb: 'flow_instruct', args: { text: 'hmm', keys: ['task:demo-task'], point: true } })
  assert.deepEqual(r.data.plan.steps, [])
  assert.ok(r.data.plan.unclear)
  // by is taken on the verbs it belongs to
  r = await tr.post('/api/action', { verb: 'later', args: { key: 'task:demo-task', until: '2026-12-01', by: 'instruction' } })
  assert.equal(r.ok, true)
})

// ---------------------------------------------------------------- round 3, after review: nothing twice, one answer set,
// the live tab leads, the suggested verb strong, every state worded, the source as links, each skip in its step

test('the card never says who works on it: no tab state, no started ago; the field on the right says it', () => {
  // a question about a task whose tab waits at its prompt, a task whose tab works, a start whose tab asks, a tab alone
  const waits = { ref: 'surface:12', name: 'a research', slug: 'a', state: 'waiting', since_ms: NOW - 14 * MIN, last: 'Shall I merge the sources?' }
  const q = pointState({ rows: [ask('20261009-0900-a-q', { task: 'a', area: 'Ops' })], feed: feedOf('inbox:20261009-0900-a-q'), tabs: [waits] })
  let el = mount(html`<${FlowPage} s=${q} c=${recorder()} />`)
  assert.ok(!el.$('.flow-card .state-line'), 'no tab state in the card')
  assert.doesNotMatch(el.$('.flow-card').text(), /a research/)
  assert.match(el.$('.flow-aside [data-field=who]').text(), /Agent tab a research: waiting, for 14 min/)
  const busy = { ref: 'surface:21', name: 'notes', slug: 'a', state: 'working', since_ms: NOW - 10 * MIN, last: 'Reading the notes' }
  el = mount(html`<${FlowPage} s=${pointState({ tabs: [busy] })} c=${recorder()} />`)
  assert.ok(!el.$('.flow-card .fx-meta'), 'no line who drives it in the card')
  assert.doesNotMatch(el.$('.flow-card').text(), /notes: at work/)
  assert.match(el.$('.flow-card .fx-screen').text(), /Reading the notes/, 'the screen stays in the card')
  const asks = { ref: 'surface:10', name: 'fin', slug: 'fin', state: 'needs-you', since_ms: NOW - 5 * MIN, ask: { text: 'Edit the file?', hash: 'h9', options: [{ n: 1, label: 'Yes' }] } }
  const st = cockpitState(NOW, state({ work: [task('fin')], tabs: [asks], returns: [startOf('fin', 'asks', { tab: { ref: 'surface:10' } })] }))
  el = mount(html`<${FlowPage} s=${st} c=${recorder()} />`)
  assert.doesNotMatch(el.$('.flow-card').text(), new RegExp(en.flow.started('30 min')))
  assert.match(el.$('.flow-aside [data-field=who]').text(), /Started from the cockpit 30 min ago/)
  el = mount(html`<${FlowPage} s=${cockpitState(NOW, state({ tabs: [dialog()] }))} c=${recorder()} />`)
  assert.ok(!el.$('.flow-card .state-line'), 'a tab alone: its kind says it asks, no state line')
})

test('a tab that asks: one set of answers on the card, the guide folded behind one button and without a second title', async () => {
  const tab = dialog()
  const guide = { enabled: true, entries: { [tab.ref]: { key: 'h1', state: 'needs-you', about: 'Merging the docs', where: 'Two pages say the same',
    options: [{ n: 2, label: 'Redirect it', why: 'Links stay alive' }], pick: 0, source: 'haiku', at_ms: NOW - MIN } } }
  const el = mount(html`<${FlowPage} s=${cockpitState(NOW, { ...state({ tabs: [tab] }), guide })} c=${recorder()} />`)
  const card = el.$('.flow-card')
  assert.deepEqual(card.$$('.reply-btns button').map(b => b.text()), ['Delete', 'Redirect'])
  assert.ok(!card.$('.guide'), 'the guide is folded')
  const open = card.$$('button').find(b => b.text() === en.flow.guide.show)
  assert.ok(open, 'one button unfolds it')
  open.click()
  await tick()
  assert.ok(el.$('.flow-card .guide'))
  assert.ok(!el.$('.flow-card .guide-head'), 'what it is about is the card\'s title already')
  assert.ok(el.$$('.flow-card button').some(b => b.text() === en.flow.guide.hide))
})

test('a finished start: the criteria stand in Description, not in the card as well', () => {
  const row = task('fin', { card: { acceptance: ['The machine boots Linux', 'The backup runs'] } })
  const s = pointState({ rows: [row], feed: feedOf('task:fin'), detail: null,
    tabs: [{ ref: 'surface:10', name: 'fin', slug: 'fin', state: 'waiting', since_ms: NOW - 25 * MIN }],
    returns: [startOf('fin', 'result', { tab: { ref: 'surface:10' }, result: { kind: 'note', text: 'Result: driver installed', key: null, at_ms: null } })],
    ui: { flowAt: { id: 'start:task:fin', i: 0 } } })
  const el = mount(html`<${FlowPage} s=${s} c=${recorder()} />`)
  assert.ok(!el.$('.flow-card .flow-criteria'))
  assert.doesNotMatch(el.$('.flow-card').text(), /The machine boots Linux/)
  assert.match(el.$('.flow-ptabs [role=tabpanel]').text(), /The machine boots Linux.*The backup runs/)
})

test('the instruction line names what it speaks for: the reports by their count, no line where nothing takes a sentence', () => {
  const s = cockpitState(NOW, { ...state({ now: [report('20261009-0901-a-r'), report('20261009-0902-b-r')] }), work: pointState().work,
    flow_ai: { instruct_left: 9 }, ui: { ...state().ui, page: 'briefing', workView: 'flow', flowAt: { id: 'reports', i: 0 } } })
  const q = queueOf(s)
  const scope = logic.instructScope(q[0], q, new Set(), 'Ops', s)
  assert.deepEqual([scope.point, scope.keys, scope.n], [false, ['inbox:20261009-0901-a-r', 'inbox:20261009-0902-b-r'], 2])
  const el = mount(html`<${FlowPage} s=${s} c=${recorder()} />`)
  assert.match(el.$('.flow-instruct-scope').text(), new RegExp(en.flow.instruct.reports(2)))
  // a start whose item is not in the list: nothing the sentence could act on, so no line that never sends
  const gone = cockpitState(NOW, { ...state({ returns: [startOf('gone', 'result', { result: { kind: 'note', text: 'Result: done', key: null, at_ms: null } })] }),
    work: pointState().work })
  const gq = queueOf(gone)
  assert.equal(logic.instructScope(gq[0], gq, new Set(), 'Ops', gone), null)
  assert.ok(!mount(html`<${FlowPage} s=${gone} c=${recorder()} />`).$('.flow-instruct'))
  // an instruction that ran keeps its undo there, though the point now in front takes no sentence
  const ran = { ...gone, ui: { ...gone.ui, flowBatch: { running: false, n: 1, from: 'instruct', undo: [{ undo: { verb: 'task_reopen', args: { slug: 'a' } } }] } } }
  const c = recorder()
  const kept = mount(html`<${FlowPage} s=${ran} c=${c} />`)
  assert.ok(kept.$('.flow-instruct-done'), 'the undo stays')
  assert.ok(!kept.$('.flow-instruct textarea'), 'no field that could not send')
  kept.button(en.flow.instruct.undo).click()
  assert.deepEqual(c.calls.at(-1), ['flowBatchUndo'])
  for (const lang of ['en', 'de']) assert.ok(text.TABLES[lang].flow.instruct.reports(2))
  // the overview of all: how many of the rows it shows the sentence reaches (a tab alone has no item), no side named
  const mixed = cockpitState(NOW, { ...state({ work: [task('a'), task('b')], tabs: [dialog()] }), work: pointState().work,
    ui: { ...state().ui, page: 'briefing', workView: 'flow', flowView: 'overview' } })
  const ov = mount(html`<${FlowPage} s=${mixed} c=${recorder()} />`)
  assert.equal(ov.$('.flow-instruct-scope').text().split(' · ')[0], en.flow.instruct.every(2, 3))
  assert.equal(en.flow.instruct.every(2, 3), 'For 2 of the 3 points')
  assert.equal(text.TABLES.de.flow.instruct.every(9, 11), 'Gilt für 9 von 11 Punkten')
})

test('a tab that waits at its prompt is live too: To tab and View lead in one style, no Let AI do it, no Give your yes', () => {
  const waits = { ref: 'surface:12', name: 'a research', slug: 'a', state: 'waiting', since_ms: NOW - 14 * MIN }
  const yes = { gate: 'your-yes', has_action: true }
  for (const tab of [waits, { ...waits, state: 'working' }]) {
    const s = pointState({ rows: [ask('20261009-0900-a-q', { task: 'a', ...yes })], feed: feedOf('inbox:20261009-0900-a-q'), tabs: [tab] })
    assert.equal(logic.flowLive(queueOf(s)[0], s)?.ref, 'surface:12', tab.state)
    const el = mount(html`<${FlowPage} s=${s} c=${recorder()} />`)
    const can = el.$$('.flow-aside .flow-can button')
    assert.deepEqual(can.slice(0, 2).map(b => b.text()), [en.flow.toTab, en.flow.view], tab.state)
    assert.ok(can[0].hasClass('btn-primary') && can[1].hasClass('btn-secondary'), tab.state)
    assert.equal(can.filter(b => b.hasClass('btn-ghost')).length, 0, 'one style in the stack')
    assert.ok(!can.some(b => b.text() === `${en.flow.verbs.do} ▾` || b.text() === en.flow.approve), tab.state)
  }
})

test('a finished start: the verb the AI suggests is the strong one, Done and close the tab one of the others, one style', () => {
  const row = task('fin')
  const live = { ref: 'surface:10', name: 'fin', slug: 'fin', state: 'waiting', since_ms: NOW - 25 * MIN }
  const themes = themesState({ assign: {}, suggest: { 'task:fin': { verb: 'drop', reason: 'No longer needed', drop: 'not_needed', at_ms: NOW } } })
  const s = { ...cockpitState(NOW, state({ work: [row], tabs: [live],
    returns: [startOf('fin', 'result', { tab: { ref: 'surface:10' }, result: { kind: 'note', text: 'Result: nothing to do', key: 'inbox:x', at_ms: null } })] })), themes }
  const el = mount(html`<${FlowPage} s=${s} c=${recorder()} />`)
  const can = el.$$('.flow-aside .flow-can button')
  assert.equal(can[0].text(), `${en.flow.verbs.drop} ▾`)
  assert.ok(can[0].hasClass('btn-primary'))
  const close = can.find(b => b.text() === en.flow.doneClose)
  assert.ok(close && close.hasClass('btn-secondary'))
  assert.equal(can.filter(b => b.hasClass('btn-primary')).length, 1)
  assert.equal(can.filter(b => b.hasClass('btn-ghost')).length, 0, 'one style in the stack')
  assert.ok(!can.some(b => b.text() === en.flow.approve))
  // without a suggestion Done and close the tab is the strong one
  const plain = mount(html`<${FlowPage} s=${{ ...s, themes: { enabled: false } }} c=${recorder()} />`)
  assert.equal(plain.$('.flow-aside .flow-can button').text(), en.flow.doneClose)
})

test('Activity words every state as the page does: an inbox item open, a task in review as the card head says it', () => {
  const rows = [arow({ id: 'created:1', kind: 'created', filters: ['state'], change: { field: 'status', old: null, new: 'open' } }),
    arow({ id: 'status:2', kind: 'status', filters: ['state'], change: { field: 'status', old: 'doing', new: 'review' } }),
    arow({ id: 'status:3', kind: 'status', filters: ['state'], change: { field: 'status', old: 'open', new: 'approved' } })]
  const feed = feedOf('task:a', { rows, counts: { all: 3, notes: 0, docs: 0, state: 3, agents: 0, code: 0 } })
  try {
    for (const lang of ['en', 'de']) {
      text.setLanguage(lang)
      const t = text.TABLES[lang].flow
      const el = mount(html`<${FlowPage} s=${pointState({ feed, ui: { flowTab: 'activity' } })} c=${recorder()} />`)
      const said = el.$$('.flow-act-row .flow-chg').map(x => x.text())
      assert.deepEqual(said, [t.activity.state.open, `${t.activity.state.doing} → ${t.activity.state.review}`,
        `${t.activity.state.open} → ${t.activity.state.approved}`], lang)
      assert.equal(t.activity.state.review, t.kind.task, `${lang}: review as the card head says it`)
      assert.equal(t.activity.state.doing, t.kind.doing, `${lang}: doing as the card head says it`)
      for (const k of ['open', 'approved', 'deferred', 'done', 'dropped', 'backlog']) assert.ok(t.activity.state[k], `${lang} ${k}`)
    }
  } finally {
    text.setLanguage('en')
  }
})

test('the source in the fields: the chip stays in the column, STATUS.md opens the files view, an issue opens on the web by its ref', () => {
  const c = recorder()
  const row = task('a', { area: 'Ops', url: 'https://example.org/repo/issues/12', origin: { category: 'bot', word_key: null, detail: 'issue-radar', raw: null, ref: 'example/repo#3' } })
  const el = mount(html`<${FlowPage} s=${pointState({ rows: [row], detail: detailOf({ front: { status: 'doing' } }) })} c=${c} />`)
  const src = el.$('.flow-aside [data-field=source]')
  assert.ok(src.$('.origin'), 'the chip stays')
  const status = src.$$('button').find(b => b.text() === 'STATUS.md')
  assert.ok(status, 'STATUS.md as a link')
  status.click()
  assert.deepEqual(c.calls.at(-1), ['openFile', 'a', null])
  const link = src.$$('a').find(a => a.getAttribute('href') === 'https://example.org/repo/issues/12')
  assert.equal(link?.text(), 'repo#12', 'the issue by its ref')
  assert.equal(logic.refOfUrl('https://github.com/owner/repo/pull/7'), 'owner/repo#7')
  assert.equal(logic.refOfUrl('https://example.org/grp/app/-/issues/3'), 'grp/app#3')
  assert.equal(logic.refOfUrl('https://example.org/docs/page'), null)
})

test('the plan says each skip inside its step, the point struck through; a reply to a tab that asks says to answer on the card', () => {
  const busy = { ref: 'surface:21', name: 'busy', slug: 'a', state: 'working', since_ms: NOW - MIN }
  const plan = { id: 'p1', text: 'x', point: true, n: 1, steps: [
    { n: 1, op: 'do', mail: true, keys: ['task:a'], titles: ['Task a'], note: 'A mail draft, a draft only', skipped: [] },
    { n: 2, op: 'reply', keys: [], titles: [], tab_ref: null, text: 'yes', skipped: [{ key: 'task:a', title: 'Task a', why: 'not_offered' }] },
  ], unclear: null, model: 'haiku', at_ms: NOW }
  let el = mount(html`<${FlowPage} s=${pointState({ tabs: [busy], ui: { flowPlan: plan } })} c=${recorder()} />`)
  const steps = el.$$('.flow-instruct-plan .flow-instruct-step')
  assert.equal(steps.length, 2)
  assert.equal(steps[0].$('del')?.text(), 'Task a', 'the point that drops out is struck through in its step')
  assert.match(steps[0].text(), new RegExp(en.flow.instruct.skipped.working))
  assert.equal(el.$$('.flow-instruct-plan > .flow-instruct-skip').length, 0, 'no loose line under the steps')
  // the server says not offered for a reply; with the point's tab asking a choice the page says why
  const asks = { ...busy, state: 'needs-you', ask: { text: 'Pick one', hash: 'h1', options: [{ n: 1, label: 'One' }] } }
  el = mount(html`<${FlowPage} s=${pointState({ tabs: [asks], ui: { flowPlan: plan } })} c=${recorder()} />`)
  const reply = el.$$('.flow-instruct-plan .flow-instruct-step')[1]
  assert.match(reply.text(), new RegExp(en.flow.instruct.skipped.asks.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')))
  assert.equal(reply.$('del')?.text(), 'Task a')
})

test('the demo plans the placeholder in full, a mail as a draft only; a part it cannot read stays unclear', async () => {
  for (const lang of ['en', 'de']) {
    const tr = mock.createMockTransport({ lang, latency: 0 })
    const example = text.TABLES[lang].flow.instruct.placeholder.split(': ').slice(1).join(': ')
    const r = await tr.post('/api/action', { verb: 'flow_instruct', args: { text: example, keys: ['task:demo-task'], point: true } })
    assert.deepEqual(r.data.plan.steps.map(x => [x.op, x.mail ?? false]), [['done', false], ['do', true]], lang)
    assert.equal(r.data.plan.unclear, null, lang)
    assert.match(r.data.plan.steps[1].note, /mail-draft/)
  }
  const tr = mock.createMockTransport({ lang: 'de', latency: 0 })
  const r = await tr.post('/api/action', { verb: 'flow_instruct', args: { text: 'erledigt, und kauf Brot', keys: ['task:demo-task'], point: true } })
  assert.deepEqual(r.data.plan.steps.map(x => x.op), ['done'])
  assert.match(r.data.plan.unclear, /kauf Brot/)
  // a reply to a tab that asks a choice: the why says so
  const st = (await tr.get('/api/state')).data
  const asking = st.tabs.tabs.find(t => t.state === 'needs-you' && t.slug)
  const key = `task:${asking.slug}`
  if (st.model.sections.some(x => x.rows.some(y => y.key === key))) {
    const p = await tr.post('/api/action', { verb: 'flow_instruct', args: { text: 'antworte: ja', keys: [key], point: true } })
    assert.deepEqual(p.data.plan.steps[0].skipped.map(x => x.why), ['asks'])
  }
})

test('the demo takes a decision back: the point is in the list again, the note in the page\'s language', async () => {
  const tr = mock.createMockTransport({ lang: 'de', latency: 0 })
  const rowsOf = async () => (await tr.get('/api/state')).data.model.sections.flatMap(x => x.rows).map(r => r.key)
  const before = await rowsOf()
  const key = before.find(k => k.startsWith('inbox:'))
  const task1 = before.find(k => k.startsWith('task:'))
  let r = await tr.post('/api/action', { verb: 'settle', args: { keys: [key, task1], outcome: 'done' } })
  assert.equal(r.ok, true)
  assert.doesNotMatch(r.data.note, /settle|inbox:|task:/)
  assert.ok(!(await rowsOf()).includes(key))
  for (const u of r.data.undo) {
    const back = await tr.post('/api/action', { verb: u.undo.verb, args: u.undo.args })
    assert.equal(back.ok, true)
    assert.doesNotMatch(back.data.note, /reopen|inbox:|task:/)
  }
  const after = await rowsOf()
  assert.ok(after.includes(key) && after.includes(task1), 'both are back')
  assert.equal(after.length, before.length)
})

test('the German demo speaks German: the note of a note, the steps and criteria of a task; one attachment says itself once', async () => {
  const tr = mock.createMockTransport({ lang: 'de', latency: 0 })
  const heard = []
  tr.events({ note: x => heard.push(x.text) }, () => {})
  await new Promise(r => setTimeout(r, 40))
  const n = await tr.post('/api/action', { verb: 'note', args: { key: 'task:demo-task', text: 'Notiz' } })
  assert.doesNotMatch(n.data.note, /^Mock: note\b|task:demo-task/)
  await new Promise(r => setTimeout(r, 40))
  assert.deepEqual(heard, [n.data.note], 'the note of a note, once')
  heard.length = 0
  const a = await tr.post('/api/flow/attach', { key: 'task:demo-task', name: 'x.txt', data: 'aGk=' })
  assert.equal(a.ok, true)
  await new Promise(r => setTimeout(r, 40))
  assert.deepEqual(heard, [], 'the page says the attachment itself, the demo adds no second note')
  const st = (await tr.get('/api/state')).data
  const slugs = [...new Set(st.model.sections.flatMap(x => x.rows).filter(x => x.task && !x.inbox_id).map(x => x.task))]
  const steps = []
  for (const slug of slugs.slice(0, 3)) {
    const d = (await tr.get(`/api/task?slug=${slug}`)).data
    const text = d.sections.find(x => x.heading === 'Steps').text
    assert.doesNotMatch(text, /Outline the chapters|Collect examples|Review with/, slug)
    steps.push(text)
    for (const p of d.related) assert.doesNotMatch(p, /\s/)
  }
  assert.ok(new Set(steps).size > 1, 'the steps differ from task to task')
  const d = (await tr.get('/api/task?slug=demo-task')).data
  assert.doesNotMatch(JSON.stringify(d.sections), /done and checked|team member/)
})

test('the demo names an attachment as the server does: letters of any script kept, one blank or underscore of a run', async () => {
  const tr = mock.createMockTransport({ lang: 'en', latency: 0 })
  // what activity.py safe_name makes of each (computed with the server's function)
  const want = { 'Mein Bericht (Entwurf) ä.txt': 'Mein Bericht (Entwurf) ä.txt', 'Grüße_aus  Köln.md': 'Grüße_aus Köln.md', 'a​b.txt': 'ab.txt',
    'x  y__z.txt': 'x y_z.txt', 'Отчёт №5.txt': 'Отчёт _5.txt', '日本語.txt': '日本語.txt', '..hidden .txt': 'hidden .txt',
    'emoji\u{1F600}.txt': 'emoji_.txt', 'Zahl ²³ ½.txt': 'Zahl ²³ ½.txt', 'a _b.txt': 'a _b.txt' }
  for (const [name, safe] of Object.entries(want)) {
    const r = await tr.post('/api/flow/attach', { key: 'task:demo-task', name, data: 'aGk=' })
    assert.equal(r.data?.attach?.name, safe, name)
  }
})

// ---------------------------------------------------------------- round 4: every open row once, Running now, Not now,
// not too early, merge, Prio, the work views

// a fixed Tuesday, 27 October 2026, 14:40: the moment of the spec's findings
const TUE = new Date(2026, 9, 27, 14, 40, 0).getTime()
const ref = (repo, n, over = {}) => ({ key: `ref:${repo}#${n}`, ref: `${repo}#${n}`, title: `Issue ${n} of ${repo}`, bucket: 'plan',
  url: `https://example.org/${repo}/issues/${n}`, settle: ['done', 'not_doing'], ...over })
const fileOf = (slug, over = {}) => ({ slug, kind: 'task', status: 'backlog', area_names: ['Ops'], priority: 'P2', title: `File ${slug}`,
  updated: '2026-10-20', blocked_by: null, bucket: null, deferred: false, deferred_until: null, ...over })

/** A state shaped like the real dump (invented names, the same kinds and counts): a report put off and a ref in Now,
 *  three questions in Give (one due on Sunday evening, urgency later), two doing tasks in Work (one a live tab works
 *  on, recognised from its session), 87 refs in Track from two repos, nine resting, waiting or parked tasks in Later,
 *  five hidden rows (one settled here), the backlog and a stream only in model.files */
function dumpState(over = {}) {
  const sections = {
    now: [report('20261026-0900-tunnel-report', { inbox_state: 'deferred', until: '2026-10-29', bucket: 'do' }),
      ref('acme/wiki', 222, { bucket: 'do', urgency: 'today' })],
    give: [ask('20261025-1800-sunday-tunnels', { bucket: 'plan', urgency: 'later', due: '2026-11-01T19:00' }),
      ask('20261026-1000-vendor-question', { bucket: 'plan' }), ask('20261026-1100-access-question', { bucket: 'plan' })],
    work: [task('board-ui', { bucket: 'plan', updated: '2026-10-27' }), task('points-walk', { updated: '2026-10-21' })],
    track: [...Array.from({ length: 60 }, (_, i) => ref('acme/app', 100 + i)), ...Array.from({ length: 27 }, (_, i) => ref('acme/docs', 10 + i))],
    later: [...['r1', 'r2', 'r3', 'r4'].map(x => task(`rest-${x}`, { bucket: 'resting' })), ...['w1', 'w2', 'w3'].map(x => task(`wait-${x}`, { bucket: 'waiting' })),
      task('park-1', { bucket: 'drop', status: 'review' }), task('park-2', { bucket: 'drop', status: 'review' })],
  }
  const hidden = [ref('acme/app', 900, { bucket: 'do', hidden_until: '2026-10-30' }), ref('acme/app', 901, { bucket: 'do', hidden_until: '2026-11-02' }),
    ref('acme/docs', 902, { hidden_until: '2026-10-31' }), task('hidden-1', { hidden_until: '2026-11-03' }),
    task('settled-1', { hidden_until: null, settled_as: 'done' })]
  const files = [fileOf('board-ui', { status: 'doing', bucket: 'plan' }), fileOf('points-walk', { status: 'doing', bucket: 'tasks' }),
    ...['b1', 'b2', 'b3', 'b4', 'b5', 'b6'].map(x => fileOf(`backlog-${x}`)), fileOf('applications', { kind: 'stream', status: 'doing' })]
  const tabs = [{ ref: 'surface:1', name: 'cockpit board ui', state: 'working', since_ms: TUE - 70 * MIN, slug: null, item: null, last: 'Editing flow.js' },
    // still for 30 minutes with nothing to decide: idle, as the server marks it, so no point (round 6 b)
    { ref: 'surface:2', name: 'notes', state: 'waiting', idle: true, since_ms: TUE - 30 * MIN, slug: null, item: null },
    { ref: 'surface:3', name: 'Control', state: 'waiting', is_control: true }]
  const sessions = { sessions: [{ id: 's1', sid: 's1-full', task: 'board-ui', task_how: 'seen', task_since_ms: TUE - 50 * MIN, started_ms: TUE - 90 * MIN,
    tab: { ref: 'surface:1', name: 'cockpit board ui' } }, { id: 's2', sid: 's2-full', task: null, tab: { ref: 'surface:2', name: 'notes' } }] }
  const base = state({ now: sections.now, work: sections.work, later: sections.later, hidden, tabs, sessions, ...over })
  base.now = TUE
  base.model.sections.find(x => x.id === 'give').rows = sections.give
  base.model.sections.find(x => x.id === 'track').rows = sections.track
  base.model.files = files
  base.work = { ...base.work, files_scope: 'all', flow: { ...base.work.flow, ahead_days: 2 } }
  return base
}

/** Every key the parts place, by where: throws on a key placed twice (logic.flowKeys) */
function checkInvariant(s, label) {
  const parts = logic.flowParts(s)
  const keys = logic.flowKeys(parts)
  const uni = logic.flowUniverse(s)
  for (const k of uni.keys()) assert.ok(keys.has(k), `${label}: ${k} stands nowhere`)
  for (const [k, at] of keys) if (!uni.has(k)) assert.ok(['point', 'lane'].includes(at.at), `${label}: ${k} outside the open rows sits in ${at.at}`)
  const c = parts.counts
  assert.equal(c.points + c.running + c.left, uni.size + c.extra, `${label}: the counts add up`)
  assert.equal(c.total, c.points + c.running + c.left, label)
  return { parts, keys, uni }
}

test('I1: every open row of the dump stands exactly once, as a point, in Running now or in a Not now group', () => {
  const { parts, keys, uni } = checkInvariant(dumpState(), 'dump')
  // the 87 refs of Track are watched by repo, the settled hidden row is not open, the backlog and the stream come from model.files
  assert.equal(uni.size, 2 + 3 + 2 + 87 + 9 + 4 + 7)
  assert.ok(!uni.has('task:settled-1'), 'a row settled here is not open')
  const by = Object.fromEntries(parts.leftOut.groups.map(g => [g.reason, g.rows.length]))
  assert.equal(by.watch, 87)
  assert.deepEqual([...new Set(parts.leftOut.groups.find(g => g.reason === 'watch').rows.map(e => e.repo))], ['acme/app', 'acme/docs'])
  assert.equal(by.stream, 1)
  assert.equal(by.idea, 6)
  // the ref in Now with bucket do is a point of its own group, Issues and PRs
  assert.deepEqual(parts.issue.map(x => x.row.key), ['ref:acme/wiki#222'])
  assert.equal(keys.get('ref:acme/wiki#222').at, 'point')
  // the session the cockpit recognised runs: Running now, not a point to decide
  assert.deepEqual(parts.lane.map(x => [x.kind, x.row?.key, x.how, x.stage]), [['session', 'task:board-ui', 'seen', 'working']])
  assert.equal(parts.lane[0].at, TUE - 50 * MIN)
  assert.ok(!logic.flowQueue(parts).some(x => x.row?.key === 'task:board-ui'))
  // the Sunday question waits under Later until Friday; the report put off waits for its day
  const later = parts.leftOut.groups.find(g => g.reason === 'later').rows
  const sunday = later.find(e => e.row.inbox_id === '20261025-1800-sunday-tunnels')
  assert.deepEqual([sunday.why, sunday.until, sunday.due], ['ahead', '2026-10-30', '2026-11-01T19:00'])
  assert.deepEqual(later.find(e => e.row.inbox_id === '20261026-0900-tunnel-report').why, 'deferred')
  assert.equal(parts.counts.extra, 0)
  assert.equal(parts.counts.points + parts.counts.running + parts.counts.left, uni.size)
})

test('I1: the demo state, with files_scope all, with and without a driver, and a state of every kind', () => {
  const NOWD = new Date(2026, 9, 9, 12, 0, 0).getTime()
  const demo = mock.buildState(NOWD, { filesScope: 'all' })
  checkInvariant({ ...demo, now: NOWD, ui: { busy: {} } }, 'demo')
  checkInvariant({ ...demo, now: NOWD, driver: { caps: [] }, ui: { busy: {} } }, 'demo without a driver')
  // I2: the demo counts the open rows by its own loop, the page by its universe: the same number
  assert.equal(logic.flowUniverse(demo).size, demo.model.counts.flow_open)
  const every = state({
    now: [ask('20261009-0900-a-q', { task: 'covered' }), ask('20261009-0901-a-q2', { task: 'covered' }), report('20261009-0902-a-r'),
      ref('acme/app', 1, { bucket: 'do' }), ask('20261009-0903-a-far', { due: '2026-10-20' })],
    work: [task('covered'), task('review-one', { status: 'review' }), task('doing-one'), task('odd', { status: null }), task('blocked', { blocked_by: 'x' })],
    later: [task('waits', { bucket: 'waiting' }), ask('20261009-0904-a-idea', { art: 'idea' }), ask('20261009-0905-a-ok', { inbox_state: 'approved' }),
      ask('20261009-0906-a-w', { bucket: 'waiting' }), ask('20261009-0907-a-r', { bucket: 'resting', art: 'report' }),
      ask('20261009-0908-a-d', { inbox_state: 'deferred', until: '2026-10-12' }), ref('acme/app', 2, { bucket: 'waiting' }), { key: 'title:A date', title: 'A date', bucket: 'plan' }],
    hidden: [task('put-off', { hidden_until: '2026-10-20' }), task('gone', { settled_as: 'not_doing' })],
    tabs: [{ ref: 'surface:5', name: 'alone', state: 'needs-you', since_ms: NOW - MIN }, { ref: 'surface:6', name: 'doing-one', slug: 'doing-one', state: 'working', since_ms: NOW - 5 * MIN },
      { ref: 'surface:7', name: 'typed', state: 'working', since_ms: NOW - 9 * MIN }],
    sessions: { sessions: [{ id: 'x1', sid: 'x1-full', task: 'closed-one', task_how: 'hand', tab: { ref: 'surface:7' } }] },
    returns: [startOf('started-one', 'working', { tab: { ref: 'surface:8' }, at_ms: NOW - MIN })],
  })
  every.model.files = [fileOf('backlog-1'), fileOf('stream-1', { kind: 'stream', status: 'doing' }), fileOf('covered', { status: 'doing' })]
  every.model.task_rows = [task('closed-one', { title: 'A closed task' })]
  const { parts } = checkInvariant(every, 'every kind')
  // a question that names a task stands for it, the second question naming it does not stand for it twice
  assert.deepEqual(parts.question.filter(x => x.covers).map(x => x.task.key), ['task:covered'])
  // a session linked to a task not open takes its title from task_rows, but stands for no open row
  const typed = parts.lane.find(x => x.kind === 'session')
  assert.deepEqual([typed.row, typed.title, typed.stage, typed.how], [null, 'A closed task', 'working', 'hand'])
  // flowKeys refuses a key placed twice
  const twice = { ...parts, lane: [...parts.lane, { ...parts.lane.find(x => x.row), id: 'again' }] }
  assert.throws(() => logic.flowKeys(twice), /twice/)
})

test('flowParts rules: hidden, put off, approved, idea, waiting and resting, reports, questions, streams, backlog, tasks, issues, watched', () => {
  const s = state({
    now: [ask('20261009-0900-a-q'), report('20261009-0901-a-r'), ref('acme/app', 1, { bucket: 'do' }), ref('acme/app', 9, { urgency: 'now' })],
    work: [task('review-one', { status: 'review' }), task('doing-one'), task('no-state', { status: null }), task('stream-one', { stream: true }),
      task('drop-one', { bucket: 'drop' }), task('blocked', { blocked_by: 'the vendor' })],
    later: [task('waits', { bucket: 'waiting' }), ask('20261009-0902-a-idea', { art: 'idea' }), ask('20261009-0903-a-ok', { inbox_state: 'approved' }),
      ask('20261009-0904-a-w', { bucket: 'waiting' }), ask('20261009-0905-a-rest', { bucket: 'resting' }), ask('20261009-0906-a-d', { inbox_state: 'deferred', until: '2026-10-12' }),
      ref('acme/app', 2, { bucket: 'waiting' }), ref('acme/docs', 3), { key: 'title:A date', title: 'A date', bucket: 'plan' },
      { key: 'item:grp/app#4', title: 'GitLab', bucket: 'plan', url: 'https://example.org/grp/app/-/issues/4' }],
    hidden: [ref('acme/app', 5, { hidden_until: '2026-10-11' })],
  })
  s.model.files = [fileOf('backlog-one'), fileOf('doing-one', { status: 'doing' })]
  const parts = logic.flowParts(s)
  const left = Object.fromEntries(parts.leftOut.groups.map(g => [g.reason, g.rows.map(e => e.row.key)]))
  // round 6 B: Later holds three kinds, each row with its own
  const kind = k => parts.leftOut.groups.flatMap(g => g.rows).filter(e => e.kind === k)
  assert.deepEqual(kind('later').map(e => e.row.key), ['ref:acme/app#5', 'inbox:20261009-0906-a-d'])
  assert.deepEqual(kind('later').map(e => [e.why, e.until]), [['hidden', '2026-10-11'], ['deferred', '2026-10-12']])
  assert.deepEqual(kind('waiting').map(e => e.row.key).sort(), ['inbox:20261009-0903-a-ok', 'inbox:20261009-0904-a-w', 'ref:acme/app#2', 'task:waits'].sort())
  assert.deepEqual(kind('resting').map(e => e.row.key).sort(), ['inbox:20261009-0905-a-rest', 'task:blocked', 'task:drop-one', 'task:no-state'].sort())
  assert.deepEqual(left.later, [...kind('later'), ...kind('waiting'), ...kind('resting')].map(e => e.row.key))
  assert.deepEqual(left.idea.sort(), ['inbox:20261009-0902-a-idea', 'task:backlog-one'].sort())
  assert.deepEqual(left.stream, ['task:stream-one'])
  assert.deepEqual(left.watch, ['ref:acme/docs#3', 'item:grp/app#4', 'title:A date'])
  assert.deepEqual(parts.leftOut.groups.find(g => g.reason === 'watch').rows.map(e => e.repo), ['acme/docs', 'grp/app', null])
  assert.deepEqual(parts.question.map(x => x.id), ['inbox:20261009-0900-a-q'])
  assert.deepEqual(parts.reports[0].rows.map(r => r.key), ['inbox:20261009-0901-a-r'])
  assert.deepEqual(parts.task.map(x => x.id), ['task:review-one'])
  assert.deepEqual(parts.doing.map(x => x.id), ['task:doing-one'])
  // an issue or PR in Now, by bucket do or urgency now, is a point of Issues and PRs, the soonest due first
  assert.deepEqual(parts.issue.map(x => x.row.key), ['ref:acme/app#1', 'ref:acme/app#9'])
  assert.deepEqual(logic.FLOW_LEFT_OUT, ['later', 'idea', 'stream', 'watch', 'github'])
  assert.deepEqual(logic.FLOW_GROUPS, ['back', 'asks', 'result', 'lost', 'question', 'doing', 'task', 'issue', 'reports'])
  assert.deepEqual(logic.FLOW_BANDS, ['you', 'doing', 'task', 'issue', 'reports'])
  assert.deepEqual(logic.FLOW_CHIPS.tasks, ['task', 'issue'])
  // fileRow: a file of model.files as a row the verbs work on
  assert.deepEqual(logic.fileRow(fileOf('x', { kind: 'stream', area_names: ['Docs'], deferred_until: '2026-10-30' })), { key: 'task:x', task: 'x', title: 'File x',
    status: 'backlog', stream: true, work_kind: 'stream', priority: 'P2', updated: '2026-10-20', blocked_by: null, bucket: null, area_names: ['Docs'],
    area: 'Docs', settle: [], hidden_until: '2026-10-30', from_files: true })
})

test('C, not too early: a point due later than ahead_days waits under Later until that lead time, by the day of its due', () => {
  const at = (due, over = {}) => ask('20261025-1800-x', { due, ...over })
  const parts = (row, flow = {}, ui = {}) => {
    const s = state({ now: [row], ui })
    s.now = TUE
    s.work.flow = { ...s.work.flow, ...flow }
    return logic.flowParts(s)
  }
  const later = p => p.leftOut.groups.find(g => g.reason === 'later')?.rows ?? []
  // Tuesday, due Sunday 19:00, ahead_days 2 (the default): it waits until Friday, the time does not shift the day
  let p = parts(at('2026-11-01T19:00'))
  assert.deepEqual(later(p).map(e => [e.why, e.until, e.due]), [['ahead', '2026-10-30', '2026-11-01T19:00']])
  assert.equal(p.question.length, 0)
  // on Friday it is two days ahead, not more: a point again; the same with a lead time of 5
  const fri = state({ now: [at('2026-11-01T19:00')] })
  fri.now = new Date(2026, 9, 30, 8, 0).getTime()
  assert.equal(logic.flowParts(fri).question.length, 1)
  assert.equal(parts(at('2026-11-01T19:00'), { ahead_days: 5 }).question.length, 1)
  // urgency now never waits; ahead_days 0: everything due after today waits for its day
  assert.equal(parts(at('2026-11-01', { urgency: 'now' })).question.length, 1)
  assert.deepEqual(later(parts(at('2026-10-28'), { ahead_days: 0 })).map(e => e.until), ['2026-10-28'])
  assert.equal(parts(at('2026-10-27T23:00'), { ahead_days: 0 }).question.length, 1)
  // a task, a report and an issue wait the same way; a waiting row is no point, so it keeps its own group
  for (const row of [task('t', { due: '2026-11-05' }), report('20261025-1800-r', { due: '2026-11-05' }), ref('acme/app', 1, { bucket: 'do', due: '2026-11-05' })]) {
    assert.deepEqual(later(parts(row)).map(e => [e.row.key, e.why]), [[row.key, 'ahead']], row.key)
  }
  // Back on: the viewer's override holds while its day still equals the computed one
  assert.equal(parts(at('2026-11-01T19:00'), {}, { flowEarly: { 'inbox:20261025-1800-x': '2026-10-30' } }).question.length, 1)
  assert.equal(later(parts(at('2026-11-02T19:00'), {}, { flowEarly: { 'inbox:20261025-1800-x': '2026-10-30' } })).length, 1)
  assert.equal(logic.flowSettings({ work: { flow: {} } }).ahead_days, 2)
  assert.equal(logic.flowSettings({ work: { flow: { ahead_days: -1 } } }).ahead_days, 2)
  assert.equal(logic.flowSettings({ work: { flow: { ahead_days: 0 } } }).ahead_days, 0)
})

test('A, Running now: a start at work, a linked or recognised session, a task tab at work; a finished one is a point again, a tab that asks stays a point', () => {
  // a tab waiting at its prompt that went quiet (idle) is finished and runs no more: its task stands as a point; not
  // quiet yet it needs you
  const tabs = [{ ref: 'surface:1', name: 'seen tab', state: 'working', since_ms: NOW - 40 * MIN },
    { ref: 'surface:2', name: 'quiet tab', state: 'waiting', idle: true, since_ms: NOW - 20 * MIN },
    { ref: 'surface:3', name: 'own', slug: 'own', state: 'waiting', idle: true, since_ms: NOW - 10 * MIN },
    { ref: 'surface:4', name: 'asks', slug: 'asks', state: 'needs-you', since_ms: NOW - 5 * MIN },
    { ref: 'surface:9', name: 'run', slug: 'run', state: 'working', since_ms: NOW - 3 * MIN }]
  const sessions = { sessions: [
    { id: 'a', sid: 'a-full', task: 'seen', task_how: 'seen', task_since_ms: NOW - 30 * MIN, started_ms: NOW - 60 * MIN, tab: { ref: 'surface:1' } },
    { id: 'b', sid: 'b-full', task: 'quiet', task_how: 'hand', task_since_ms: null, started_ms: NOW - 25 * MIN, tab: { ref: 'surface:2' } },
    { id: 'c', sid: 'c-full', task: 'asks', task_how: 'tab', tab: { ref: 'surface:4' } }] }
  const s = state({ work: ['seen', 'quiet', 'own', 'asks', 'run', 'free'].map(x => task(x)), tabs, sessions,
    returns: [startOf('run', 'working', { tab: { ref: 'surface:9' }, at_ms: NOW - 3 * MIN })] })
  const parts = logic.flowParts(s)
  assert.deepEqual(parts.lane.map(x => [x.id, x.kind, x.how, x.stage]), [['start:task:run', 'start', 'start', 'working'],
    ['session:surface:1', 'session', 'seen', 'working']])
  assert.ok(parts.lane.every(x => x.lane === true && x.group === 'doing'))
  assert.deepEqual(parts.asks.map(x => x.row?.key), ['task:asks'])
  // not quiet yet, both need you: points that ask, with their task
  const fresh = { ...s, tabs: { tabs: tabs.map(t => ({ ...t, idle: false })) } }
  assert.deepEqual(logic.flowParts(fresh).asks.map(x => x.row?.key), ['task:quiet', 'task:own', 'task:asks'])
  assert.deepEqual(parts.doing.map(x => x.id).sort(), ['task:free', 'task:own', 'task:quiet'])
  // max_running counts what runs: the start and the session at work, never a waiting or finished one
  assert.equal(logic.flowRunning(s), 2)
  // who drives the finished one's point: its tab, finished
  assert.equal(logic.flowDrive(parts.doing.find(x => x.id === 'task:quiet'), s).stage, 'idle')
  // no lane entry is a point: the walk, the overview and the batch never hold one
  assert.ok(!logic.flowQueue(parts).some(x => x.lane))
  // a doing task nobody works on says so, with the day it last moved
  assert.equal(en.flow.doing.none(4), 'Nobody works on it right now, last moved 4 days ago.')
  assert.equal(text.TABLES.de.flow.doing.none(4), 'Gerade arbeitet niemand daran, zuletzt bewegt vor 4 Tagen.')
})

test('leftPlan: Back on per entry, the other verbs as a batch plans them', () => {
  const s = state({ work: [task('blocked', { blocked_by: 'x' }), task('quiet', { bucket: 'resting' }), task('waits', { bucket: 'waiting' })] })
  const e = (row, over = {}) => ({ row, until: null, why: null, due: null, repo: null, ...over })
  const entries = [e(ref('acme/app', 1), { why: 'hidden', until: '2026-10-11' }), e(ask('20261009-0900-a-d', { inbox_state: 'deferred' }), { why: 'deferred' }),
    e(ask('20261009-0901-a-far'), { why: 'ahead', until: '2026-10-12' }), e(task('blocked', { blocked_by: 'x' })), e(task('waits', { bucket: 'waiting' })),
    e(task('quiet', { bucket: 'resting' })), e(ask('20261009-0902-a-w', { bucket: 'waiting' })), e(task('st', { stream: true }))]
  const plan = logic.leftPlan(entries, 'back', s)
  // a wait that comes from someone else's next step has no blocker to clear: it stays out (UX-4)
  assert.deepEqual(plan.calls, [{ verb: 'unhide', args: { key: 'ref:acme/app#1' } }, { verb: 'inbox_reopen', args: { id: '20261009-0900-a-d' } },
    { verb: 'task_running', args: { slug: 'blocked' } }, { verb: 'task_keep', args: { keys: ['task:quiet'] } }])
  assert.deepEqual(plan.early, ['inbox:20261009-0901-a-far'])
  assert.deepEqual(plan.skipped.map(x => [x.row.key, x.why]), [['task:waits', 'not_offered'], ['inbox:20261009-0902-a-w', 'not_offered'], ['task:st', 'not_offered']])
  assert.equal(plan.counts.back, 5)
  assert.match(en.flow.batch.summary(plan), /5 back on; 3 stay out/)
  assert.match(text.TABLES.de.flow.batch.summary({ counts: { back: 1 }, skipped: [{}] }), /1 wieder dran; 1 bleibt draußen/)
  // done, later, drop, do: exactly as batchPlan
  const rows = [e(ref('acme/app', 1)), e(task('st', { stream: true }))]
  assert.deepEqual(logic.leftPlan(rows, 'done', s).calls, logic.batchPlan(rows.map(x => x.row), 'done', s).calls)
  assert.deepEqual(logic.LEFT_VERBS, { later: ['back', 'later', 'done', 'drop'], idea: ['do', 'later', 'done', 'drop'], stream: ['later'],
    watch: ['later', 'done', 'drop'] })
})

test('B, merge: only open finite tasks, the one with more activity stays, then the newest move, then the state', () => {
  const a = task('a', { status: 'review' })
  const b = task('b')
  const rows = [a, b, ask('20261009-0900-a-q', { task: 'a' }), task('st', { stream: true }), { ...task('c'), key: 'ref:acme/app#1' }]
  assert.deepEqual(logic.mergeable(rows).map(r => r.key), ['task:a', 'task:b'])
  const feed = (all, moved) => ({ counts: { all }, facts: { moved } })
  assert.equal(logic.mergeKeep([a, b], { 'task:a': feed(3, '2026-10-01'), 'task:b': feed(9, '2026-10-01') }), 'task:b')
  assert.equal(logic.mergeKeep([a, b], { 'task:a': feed(3, '2026-10-08T10:00'), 'task:b': feed(3, '2026-10-02') }), 'task:a')
  assert.equal(logic.mergeKeep([a, b], {}), 'task:b', 'a tie: doing before review')
  assert.equal(logic.mergeKeep([task('x'), task('y')], {}), 'task:x', 'a tie all through: the first')
})

test('E, Prio: offered while Jev orders the work page; four squares in Jev order, the unrated last; Jev feeds the suggestions', () => {
  const page = { id: 'work', group: 'work', jev: true, sections: [] }
  const order = { at_ms: NOW - 60 * MIN, items: [{ key: 'task:b', rank: 1, quadrant: 'now', who: 'me' }, { key: 'task:a', rank: 2, quadrant: 'now', who: 'me' },
    { key: 'task:c', rank: 3, quadrant: 'hand', who: 'delegate' }, { key: 'task:d', rank: 4, quadrant: 'drop', who: 'delegate' }] }
  const s = state({ work: ['a', 'b', 'c', 'd', 'e'].map(x => task(x)), ui: { flowMode: 'prio' } })
  s.model.pages = [page]
  s.jev = { enabled: true, ready: true }
  s.jevOrder = { work: { order } }
  s.work.flow.drop_reasons = ['not_worth_it']
  assert.equal(logic.prioOn(s), true)
  assert.equal(logic.flowMode(s), 'prio')
  assert.equal(logic.flowMode({ ...s, jev: { enabled: false } }), 'areas')
  assert.equal(logic.flowMode({ ...s, themes: { enabled: true }, jev: { enabled: false } }), 'themes')
  assert.deepEqual([...logic.jevQuadrants(s).entries()].map(([k, v]) => [k, v.quadrant, v.rank]), [['task:b', 'now', 1], ['task:a', 'now', 2], ['task:c', 'hand', 3], ['task:d', 'drop', 4]])
  // an order older than rank_max_age_days counts no more
  assert.equal(logic.jevQuadrants({ ...s, now: NOW + 8 * 86400000 }).size, 0)
  const all = logic.flowQueue(logic.flowParts(s))
  const sides = logic.flowSides(s, all, 'prio')
  assert.deepEqual(sides.map(x => [x.id, x.open]), [['all', 5], ['q:now', 2], ['q:plan', 0], ['q:hand', 1], ['q:drop', 1], ['none', 1]])
  assert.deepEqual(logic.pointsIn(all, 'q:now', s, 'prio').map(x => x.row.key), ['task:b', 'task:a'])
  // Jev suggests Drop for its drop square (a task that did not move lately), Let AI do it for hand; nothing for now and
  // plan; Tick the suggestions never ticks a ranker's Drop
  const quiet = task('d', { updated: '2026-09-01' })
  assert.deepEqual(logic.flowSuggestion(quiet, s), { verb: 'drop', drop: 'not_worth_it', reason: '', until: null, from: 'jev', ranker: 'jev', at: NOW - 60 * MIN, quadrant: 'drop' })
  assert.equal(logic.flowSuggestion(task('d'), s), null, 'in progress, when it moved unknown')
  assert.equal(logic.flowSuggestion(task('c'), s).verb, 'do')
  assert.equal(logic.flowSuggestion(task('b'), s), null)
  assert.deepEqual(logic.batchPreselect([quiet, task('c')], s), [])
  // no work page with Jev: no Prio
  assert.equal(logic.prioOn({ ...s, model: { ...s.model, pages: [] } }), false)
})

test('F, the work views: cockpit.work_views keeps the views it names, an older server keeps them all', () => {
  const page = { id: 'work', group: 'work', jev: true }
  const jev = { enabled: true, ready: true }
  // the files are a tab of their own since round 6c, never a view of the switch
  assert.deepEqual(logic.workViews(page, jev, true), ['due', 'area', 'jev', 'flow'])
  assert.deepEqual(logic.workViews(page, jev, true, ['files', 'flow']), ['flow'])
  assert.deepEqual(logic.workViews(page, jev, true, ['source']), ['area'])
  assert.deepEqual(logic.workViews(page, jev, true, []), ['due', 'area', 'jev', 'flow'], 'nothing left: unfiltered')
  assert.deepEqual(logic.workViews(page, jev, true, ['files']), ['due'], 'only the files: what is due')
  // round 6 B: a view switched off falls back to Work through where it is kept, the first view kept only without it
  assert.equal(logic.workViewOf('due', page, jev, true, ['files', 'flow']), 'flow', 'Work through kept')
  assert.equal(logic.workViewOf('due', page, jev, true, ['files', 'source']), 'area', 'the first view kept')
  const s = { model: { pages: [page] }, jev, work: { flow: { enabled: true }, views: ['files', 'flow'] }, ui: { workView: 'jev' } }
  assert.equal(logic.workViewIn(s), 'flow')
})

// ---------------------------------------------------------------- round 4: the views and the demo

const demoFlow = (ui = {}, over = {}) => cockpitState(NOW, { ...over, ui: { page: 'briefing', workView: 'flow', flowView: 'overview', flowPicked: [], ...ui } })

test('Running now: one row on top of the left column, never a strip over the overview', () => {
  const s = demoFlow()
  const parts = logic.flowParts(s)
  assert.ok(parts.lane.length >= 3, 'the demo runs a start, a recognised session and a task tab')
  assert.ok(parts.lane.some(x => x.how === 'seen' && x.stage === 'working'))
  // round 6 B: its session waiting at a question, not quiet yet, asks as a point with its task, not in Running now
  assert.ok(parts.asks.some(x => x.tab?.ref === 'surface:12' && x.row?.key === 'task:demo-task'))
  assert.ok(!parts.lane.some(x => x.tab?.ref === 'surface:12'))
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${s} c=${c} />`)
  // the left column holds one row: its name and its count, the dot pulsing while an entry works, no entry listed
  const cats = el.$$('aside .flow-run-cat')
  assert.equal(cats.length, 1)
  assert.ok(cats[0].hasClass('flow-notnow-item'), 'styled as a group of Not now')
  assert.match(cats[0].text(), new RegExp(`${en.flow.run.label}\\s*${logic.runningOf(parts).n}`))
  assert.ok(cats[0].$('.dot').hasClass('dot-pulse'))
  assert.ok(!cats[0].hasClass('is-on'))
  assert.ok(!el.$('aside .flow-side-body .flow-run-item'), 'no entry listed in the wide column (the narrow fold keeps its lines)')
  assert.ok(!el.$('aside .flow-side-body .flow-run-open'), 'no entry listed in the wide column (the narrow fold keeps its lines)')
  cats[0].click()
  assert.deepEqual(c.calls.at(-1), ['flowRunning'])
  // Running now is only that row: no strip of its entries over the overview (the view `running` lists them, below)
  assert.equal(el.$('.flow-main .flow-runstrip'), null)
  const seen = parts.lane.find(x => x.how === 'seen')
  // no entry of Running now in the overview's table or the batch
  assert.ok(!el.$$('.flow-ov-row').some(tr => tr.text().includes(seen.title)))
  // nothing runs: no row
  const calm = mount(html`<${FlowPage} s=${state({ work: [task('a')], ui: { flowView: 'overview', flowPicked: [] } })} c=${recorder()} />`)
  assert.ok(!calm.$('aside .flow-run-cat'), 'aside .flow-run-cat')
})

test('the running view: back to overview, Running now with its count, every entry with To tab and View and its box, the row marked', () => {
  const s = demoFlow({ flowView: 'running' })
  const run = logic.runningOf(logic.flowParts(s))
  const lane = run.loose
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${s} c=${c} />`)
  assert.ok(!el.$('.flow-overview'), '.flow-overview')
  const main = el.$('.flow-main')
  assert.match(main.$('h2').text(), new RegExp(`${en.flow.run.label}\\s*${run.n}`))
  // round 6: the entries no session card holds as rows, every live session as a card
  const rows = main.$$('.flow-runstrip-row')
  assert.ok(lane.length >= 1, 'the demo runs a start without a session')
  assert.equal(rows.length, lane.length, 'every entry no card holds, at the level of all')
  assert.equal(main.$$('.sess').length, run.sessions.length)
  assert.ok(rows.every(r => r.$$('button').some(b => b.text() === en.flow.toTab)))
  assert.ok(rows.some(r => r.$$('button').some(b => b.text() === en.flow.view)))
  assert.ok(main.$('.flow-runstrip-pick'), 'the boxes for a merge stay')
  rows[0].$('.flow-run-open').click()
  assert.deepEqual(c.calls.at(-1), ['flowRun', lane[0].id])
  main.$('.flow-back').click()
  assert.deepEqual(c.calls.at(-1), ['flowOverview'])
  const cat = el.$('aside .flow-run-cat')
  assert.ok(cat.hasClass('is-on'))
  assert.equal(cat.getAttribute('aria-current'), 'true')
  // nothing marked among the sides while Running now is open in the middle
  assert.ok(el.$$('.flow-side-item').every(b => !b.hasClass('is-on')))
  // the running view with nothing running falls back to the overview
  const calm = mount(html`<${FlowPage} s=${state({ work: [task('a')], ui: { flowView: 'running', flowPicked: [] } })} c=${recorder()} />`)
  assert.ok(calm.$('.flow-overview'))
})

test('an entry opened from the running view goes back to it, one opened from the overview back to the overview', () => {
  const s = demoFlow()
  const seen = logic.flowParts(s).lane.find(x => x.how === 'seen')
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${demoFlow({ flowView: 'run', flowRunId: seen.id, flowRunFrom: 'running' })} c=${c} />`)
  assert.match(el.$('.flow-back').text(), new RegExp(en.flow.run.back))
  el.$('.flow-back').click()
  assert.deepEqual(c.calls.at(-1), ['flowRunning'])
  const c2 = recorder()
  const el2 = mount(html`<${FlowPage} s=${demoFlow({ flowView: 'run', flowRunId: seen.id })} c=${c2} />`)
  assert.match(el2.$('.flow-back').text(), new RegExp(en.flow.point.back))
  el2.$('.flow-back').click()
  assert.deepEqual(c2.calls.at(-1), ['flowOverview'])
})

test('what opens in the middle comes into view: the top of the middle scrolled up out of sight is brought back', async () => {
  const seen = []
  const had = { rect: proto.getBoundingClientRect, into: proto.scrollIntoView }
  proto.getBoundingClientRect = function rect() { return { top: String(this.getAttribute?.('class') ?? '').includes('flow-main') ? -400 : 0 } }
  proto.scrollIntoView = function into(opts) { seen.push([this.getAttribute('class'), opts]) }
  try {
    const left = logic.flowParts(demoFlow()).leftOut.groups[0].reason
    mount(html`<${FlowPage} s=${demoFlow({ flowView: 'left', flowLeft: left })} c=${recorder()} />`)
    await tick()
    assert.ok(seen.some(([cls, opts]) => cls.includes('flow-main') && opts?.block === 'start'), 'the middle scrolled into view')
  } finally {
    proto.getBoundingClientRect = had.rect
    proto.scrollIntoView = had.into
  }
})

test('the run view: the card, its tabs and the instruction line, no walk bar; Not this task unlinks a recognised session', () => {
  const s = demoFlow()
  const seen = logic.flowParts(s).lane.find(x => x.how === 'seen')
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${demoFlow({ flowView: 'run', flowRunId: seen.id })} c=${c} />`)
  assert.match(el.$('.flow-card').text(), new RegExp(seen.title))
  assert.equal(el.$('.flow-walk'), null)
  assert.ok(el.$('.flow-ptabs'))
  assert.ok(el.$('aside .flow-run-cat.is-on'), 'Running now is marked on the left while one of its entries is open')
  const can = el.$$('.flow-aside .flow-can button')
  assert.equal(can[0].text(), en.flow.toTab)
  assert.ok(can[0].hasClass('btn-primary'))
  el.button(en.flow.run.unlink).click()
  assert.deepEqual(c.calls.at(-1), ['act', 'session_unlink', { session: seen.session.sid }])
  assert.match(el.$('.flow-aside [data-field=who]').text(), /docs search/)
  // an entry gone (finished, unlinked): the overview again
  const gone = mount(html`<${FlowPage} s=${demoFlow({ flowView: 'run', flowRunId: 'session:surface:99' })} c=${recorder()} />`)
  assert.ok(gone.$('.flow-overview') || gone.$('.flow-prio'))
})

test('Not now: a button per group at the foot of the left column, a click shows the group as a list with its batch', async () => {
  const s = demoFlow()
  const left = logic.flowParts(s).leftOut
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${s} c=${c} />`)
  const block = el.$('aside .flow-notnow')
  assert.match(block.$('h3').text(), new RegExp(`${en.flow.notnow.label}\\s*${left.total}`))
  // a button per group; the rows the demo's GitHub list holds stand in one line of their own (G3)
  assert.deepEqual(block.$$('.flow-notnow-item').map(b => b.$('.flow-side-label').text()), left.groups.filter(g => !g.at).map(g => en.flow.notnow.group[g.reason]))
  assert.equal(block.$('.flow-notnow-line').text().trim(), en.flow.notnow.onPage(2, 'Trackers'))
  block.$$('.flow-notnow-item')[0].click()
  assert.deepEqual(c.calls.at(-1), ['flowLeft', left.groups[0].reason])
  // the Sunday question waits under Later, from two days before; Back on takes it back in this browser
  const later = left.groups.find(g => g.reason === 'later')
  const sunday = later.rows.find(e => e.why === 'ahead')
  assert.ok(sunday, 'the question due in five days waits')
  const c2 = recorder()
  const list = mount(html`<${FlowPage} s=${demoFlow({ flowView: 'left', flowLeft: 'later', flowLeftPicked: [sunday.row.key] })} c=${c2} />`)
  assert.match(list.$('.flow-leftlist h2').text(), new RegExp(en.flow.notnow.group.later))
  assert.match(list.$('.flow-left-sub').text(), new RegExp(en.flow.notnow.sub.later))
  assert.equal(list.$('.flow-instruct'), null, 'no instruction line in a list of Not now')
  // round 6 B: no right column on a list, its hint under it; the column Why says when it is due and when it comes up
  assert.ok(!list.$('.flow-aside'))
  assert.match(list.$('.flow-main').text(), new RegExp(en.flow.notnow.hint.slice(0, 30)))
  const tr = list.$$('.flow-ov-row').find(r => r.text().includes(sunday.row.title))
  assert.match(tr.$('.flow-ov-why').text(), new RegExp(en.flow.notnow.why.ahead('.+', '.+')))
  assert.deepEqual(list.$$('.flow-ov-verbs button').map(b => b.text()), [en.flow.notnow.back, `${en.flow.verbs.later} ▾`, en.flow.verbs.done, `${en.flow.verbs.drop} ▾`])
  list.button(en.flow.notnow.back).click()
  await tick()
  assert.match(list.$('.flow-list-confirm').text(), /1 back on/)
  list.button(en.flow.list.confirm).click()
  await tick()
  assert.deepEqual(c2.calls.find(x => x[0] === 'flowEarly'), ['flowEarly', { [sunday.row.key]: sunday.until }])
  // the watched issues and pull requests no GitHub list holds under a head per repository
  const watch = mount(html`<${FlowPage} s=${demoFlow({ flowView: 'left', flowLeft: 'watch' })} c=${recorder()} />`)
  const heads = watch.$$('.flow-ov-group').map(h => h.text())
  assert.ok(heads.includes('example/repo') && heads.includes('grp/app') && !heads.includes('example/tools'), heads.join(', '))
  assert.ok(watch.$$('.flow-ov-open').some(a => a.getAttribute('href')?.startsWith('https://example.org/')), 'an issue opens on the web')
})

test('Not now: the rows a GitHub list holds fold into one line that leads there, the rest stay watched, the counts hold (G3)', () => {
  const gh = { page: 'github', section: 'boards' }
  const s = state({ later: [ref('acme/app', 3, { on_board: gh }), ref('acme/app', 2, { on_board: gh }), ref('acme/docs', 4),
    { key: 'ref:checks/disk-low', ref: 'checks/disk-low', title: 'Disk almost full', bucket: 'plan' },
    ref('acme/app', 7, { on_board: gh, bucket: 'do' })],
    hidden: [ref('acme/app', 9, { on_board: gh, hidden_until: '2026-10-20' })] })
  s.model.pages = [{ id: 'github', title: 'GitHub', sections: [] }]
  const { parts } = checkInvariant(s, 'a GitHub list')
  const by = Object.fromEntries(parts.leftOut.groups.map(g => [g.reason, g]))
  // only the watched rows of a board fold: one that needs you stays a point, one put off stays under Later
  assert.deepEqual(by.github.rows.map(e => e.row.key), ['ref:acme/app#2', 'ref:acme/app#3'])
  assert.deepEqual(by.github.at, { ...gh, title: 'GitHub' })
  assert.deepEqual(by.watch.rows.map(e => e.row.key), ['ref:acme/docs#4', 'ref:checks/disk-low'])
  assert.deepEqual(parts.issue.map(x => x.row.key), ['ref:acme/app#7'])
  assert.deepEqual(by.later.rows.map(e => e.row.key), ['ref:acme/app#9'])
  // the line counts its rows: Not now holds them, so points, Running now and Not now still add up to every open row
  assert.equal(parts.counts.left, 5)
  assert.equal(parts.leftOut.total, 5)
  // the left column: Watching and Later as group buttons, the GitHub rows as one quiet line that opens the list
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${{ ...s, ui: { ...s.ui, flowView: 'overview' } }} c=${c} />`)
  const block = el.$('aside .flow-notnow')
  assert.deepEqual(block.$$('.flow-notnow-item').map(b => b.$('.flow-side-label').text()), [en.flow.notnow.group.later, en.flow.notnow.group.watch])
  const line = block.$('.flow-notnow-line')
  assert.equal(line.text().trim(), en.flow.notnow.onPage(2, 'GitHub'))
  assert.equal(line.getAttribute('title'), en.flow.notnow.onPageTitle('GitHub'))
  line.click()
  // round 6c G4: the line opens the list with every row, so a filter kept there does not hide what it counted
  assert.deepEqual(c.calls.at(-1), ['openSection', 'github', 'boards', null])
  // a list on a page the model does not name keeps its id as the word
  const lone = state({ later: [ref('acme/app', 2, { on_board: { page: 'boards', section: 'work' } })] })
  assert.deepEqual(logic.flowParts(lone).leftOut.groups[0].at, { page: 'boards', section: 'work', title: 'boards' })
})

test('Merge in the batch: two open tasks ticked offer it, a stream or an item ticked with them turns it off with why', async () => {
  const s = demoFlow({ flowPicked: ['task:release-polish', 'task:release-wording'] })
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${s} c=${c} />`)
  const merge = el.button(`${en.flow.merge.button} ▾`)
  assert.ok(merge && !merge.hasAttribute('disabled'))
  merge.click()
  await tick()
  const panel = el.$('.flow-merge')
  assert.match(panel.text(), new RegExp(en.flow.merge.title))
  assert.equal(panel.$$('input[type=radio]').length, 2)
  assert.ok(c.calls.filter(x => x[0] === 'loadActivity').length >= 2, 'the feeds load for the counts')
  assert.match(panel.text(), /Polish the wording of the release checklist stays/)
  el.button(en.flow.merge.run).click()
  await tick()
  assert.deepEqual(c.calls.find(x => x[0] === 'flowMerge'), ['flowMerge', 'task:release-polish', ['task:release-wording'], 'overview'])
  // as Confirm does, the merge unticks the rows it took: an undo brings them back unticked
  const untick = c.calls.findIndex(x => x[0] === 'flowPick' && x[2] === false)
  assert.ok(untick >= 0, 'the merged rows are unticked')
  assert.deepEqual([...c.calls[untick][1]].sort(), ['task:release-polish', 'task:release-wording'])
  assert.ok(untick < c.calls.findIndex(x => x[0] === 'flowMerge'), 'unticked before the merge goes out')
  // with an inbox item ticked too: disabled, and the line says why
  const mixed = mount(html`<${FlowPage} s=${demoFlow({ flowPicked: ['task:release-polish', 'task:release-wording', 'inbox:20261009-0900-review-demo-a1b2'] })} c=${recorder()} />`)
  assert.ok(mixed.button(`${en.flow.merge.button} ▾`).hasAttribute('disabled'))
  assert.match(mixed.$('.flow-merge-only').text(), new RegExp(en.flow.merge.only.slice(0, 20)))
  // the panel's keep goes to the one with more activity once the feeds came
  const feeds = { 'task:release-polish': { counts: { all: 2 }, facts: { moved: '2026-10-05' } }, 'task:release-wording': { counts: { all: 7 }, facts: { moved: '2026-10-07' } } }
  const withFeeds = demoFlow({ flowPicked: ['task:release-polish', 'task:release-wording'] }, { details: { inbox: {}, task: {},
    activity: Object.fromEntries(Object.entries(feeds).map(([k, v]) => [k, { status: 'ok', ver: 0, data: v }])) } })
  const p = mount(html`<${views.flowlist.MergePanel} rows=${logic.flowParts(withFeeds).task.map(x => x.row).concat(logic.flowParts(withFeeds).doing.map(x => x.row))
    .filter(r => r.key.startsWith('task:release-'))} s=${withFeeds} c=${recorder()} onClose=${() => {}} />`)
  assert.match(p.text(), /Reword the release checklist stays/)
  assert.match(p.text(), new RegExp(en.flow.merge.activity(7)))
})

test('Prio: the switch offers it with a work page Jev orders, the grid of four squares, a click enters a square', async () => {
  const base = mock.buildState(NOW, { workPage: true })
  const st = cockpitState(NOW, { model: base.model, ui: { page: 'briefing', workView: 'flow', flowView: 'overview', flowMode: 'prio', flowPicked: [] } })
  const all = logic.flowQueue(logic.flowParts(st))
  const keys = all.filter(x => x.row).map(x => x.row.key)
  const order = { at_ms: NOW - 30 * MIN, items: keys.slice(0, 4).map((key, i) => ({ key, rank: i + 1, quadrant: logic.FLOW_QUADRANTS[i], who: 'me' })) }
  const s = { ...st, jevOrder: { work: { order, running: false, error: null } } }
  assert.equal(logic.flowMode(s), 'prio')
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${s} c=${c} />`)
  assert.deepEqual(el.$$('aside .seg-btn').map(b => b.text()), [en.flow.side.themes, en.flow.side.areas, en.flow.side.prio])
  const squares = el.$$('.flow-prio-grid .flow-prio-sq')
  assert.deepEqual(squares.map(b => b.getAttribute('data-quadrant')), ['now', 'plan', 'hand', 'drop'])
  assert.match(squares[0].text(), new RegExp(en.flow.fields.quadrant.now))
  assert.match(squares[0].text(), new RegExp(en.flow.prio.sub.now))
  assert.ok(el.$('.flow-prio-none .flow-prio-sq'), 'the points Jev did not rate')
  assert.match(el.$('.flow-prio-from').text(), /Jev ordered/)
  assert.match(el.$('.flow-main .flow-main-hint').text(), new RegExp(en.flow.prio.hint.slice(0, 30)))
  squares[1].click()
  assert.deepEqual(c.calls.at(-1), ['flowSide', 'q:plan'])
  // no order yet: the page asks for the day's order once
  const none = { ...st, jevOrder: {} }
  const c2 = recorder()
  mount(html`<${FlowPage} s=${none} c=${c2} />`)
  await tick()
  assert.deepEqual(c2.calls.find(x => x[0] === 'flowPrioOrder'), ['flowPrioOrder', 'work'])
  // a square entered: All squares first, the squares as on level one with it marked, its points one band in Jev's order
  const inside = mount(html`<${FlowPage} s=${{ ...s, ui: { ...s.ui, flowSide: { prio: 'q:now' } } }} c=${recorder()} />`)
  const sq = inside.$$('aside .flow-side-item')
  assert.match(sq[0].text(), new RegExp(en.flow.side.allQuads))
  assert.ok(sq.find(b => b.text().includes(en.flow.fields.quadrant.now)).hasClass('is-on'))
  assert.ok(inside.$('aside .flow-prio-foot'), 'Ask Jev again stays at the foot')
  assert.deepEqual(inside.$$('.flow-ov-group').map(h => h.text()), [en.flow.groups.rank])
})

test('the head counts points, what runs and what is not now; the sum is every open row', () => {
  const s = demoFlow()
  const p = logic.flowParts(s)
  const el = mount(html`<${FlowPage} s=${s} c=${recorder()} />`)
  // what runs: the session cards and the entries no card holds, as the left column's row counts them (round 6)
  assert.match(el.$('.flow-head').text(), new RegExp(en.flow.count(p.counts.points, logic.runningOf(p).n, p.counts.left)))
  assert.equal(p.counts.total - p.counts.extra, logic.flowUniverse(s).size)
  assert.equal(en.flow.count(1, 0, 2), '1 point · 2 not now')
  assert.equal(text.TABLES.de.flow.count(3, 1, 2), '3 Punkte · 1 läuft · 2 nicht dran')
  // the left-out drawer is gone
  assert.equal(el.$('.flow-left'), null)
})

test('the Sessions page names a task recognised from the session and offers Not this task', () => {
  const s = cockpitState(NOW, { ui: { page: '@sessions' } })
  const c = recorder()
  const el = mount(html`<${views.sessions.SessionsPage} s=${s} c=${c} />`)
  const seen = el.$$('.sess-seen')
  assert.equal(seen.length, 1)
  assert.equal(seen[0].text(), en.sessionSeen)
  assert.equal(seen[0].getAttribute('title'), en.sessionSeenTitle)
  el.button(en.sessionNotThis).click()
  assert.deepEqual(c.calls.at(-1), ['act', 'session_unlink', { session: '6b1d9e20-0000-4000-8000-000000000004' }])
})

test('F: the work tab shows only the views cockpit.work_views keeps; one left, no switch at all', () => {
  const page = { id: 'work', group: 'work', jev: true, sections: [] }
  const at = views_ => {
    const s = cockpitState(NOW, { work: { ...cockpitState(NOW).work, views: views_ }, jev: { enabled: true, ready: true },
      ui: { page: 'briefing', workView: 'flow' } })
    s.model = { ...s.model, pages: [...s.model.pages, page] }
    return mount(html`<${views.day.WorkSwitch} s=${s} c=${recorder()} />`)
  }
  assert.deepEqual(at(['files', 'due', 'flow']).$$('[role=radio]').map(b => b.text()), [en.workOrder.views.due, en.workOrder.views.flow])
  assert.ok(!at(['files', 'flow']).$('.work-switch'), 'the files and Work through: Work through alone, no switch')
})

test('the demo merges two tasks and takes it back; the refusals as the server words them', async () => {
  const tr = mock.createMockTransport({ latency: 0 })
  const act = (verb, args) => tr.post('/api/action', { verb, args })
  assert.equal((await act('flow_merge', { keep: 'task:release-polish', keys: ['task:release-polish'] })).error.code, 'invalid_argument')
  assert.equal((await act('flow_merge', { keep: 'task:release-polish', keys: ['task:nowhere'] })).error.code, 'stale_row')
  assert.equal((await act('flow_merge', { keep: 'task:release-polish', keys: ['task:team-onboarding'] })).error.code, 'merge_not_task')
  assert.equal((await act('flow_merge', { keep: 'task:release-polish', keys: ['inbox:20261009-0915-update-docs-e5f6'] })).error.code, 'merge_not_task')
  const off = mock.createMockTransport({ latency: 0, flow: false })
  assert.equal((await off.post('/api/action', { verb: 'flow_merge', args: { keep: 'task:release-polish', keys: ['task:release-wording'] } })).error.code, 'flow_off')
  // a backlog task of the files list merges as well
  const r = await act('flow_merge', { keep: 'task:release-polish', keys: ['task:release-wording', 'task:docs-search'] })
  assert.equal(r.ok, true)
  assert.deepEqual(r.data.merge, { keep: 'release-polish', merged: ['release-wording', 'docs-search'], failed: [] })
  assert.deepEqual(r.data.settled, ['task:release-wording', 'task:docs-search'])
  assert.deepEqual(r.data.undo.map(u => u.undo), [{ verb: 'task_unmerge', args: { keep: 'release-polish', slug: 'release-wording', as: 'review' } },
    { verb: 'task_unmerge', args: { keep: 'release-polish', slug: 'docs-search', as: 'backlog' } }])
  let st = (await tr.get('/api/state')).data
  const keys = new Set([...st.model.sections.flatMap(x => x.rows).map(x => x.key), ...st.model.files.map(f => `task:${f.slug}`)])
  assert.ok(!keys.has('task:release-wording') && !keys.has('task:docs-search') && keys.has('task:release-polish'))
  const top = (await tr.get('/api/history')).data.entries[0]
  assert.equal(top.verb, 'flow_merge')
  assert.deepEqual(top.items.map(x => [x.did, x.ident]), [['merged', 'release-wording'], ['merged_in', 'release-polish'], ['merged', 'docs-search'], ['merged_in', 'release-polish']])
  const feed = (await tr.get('/api/flow/activity?key=task:release-polish&fresh=1')).data
  assert.ok(feed.rows.some(x => x.change?.new === 'merged_in' && x.change.from === 'release-wording'))
  // the undo: the merged task is back, a second undo of the same is not applicable
  const u = await act('task_unmerge', { keep: 'release-polish', slug: 'release-wording', as: 'review' })
  assert.equal(u.ok, true)
  assert.deepEqual(u.data.unmerge, { keep: 'release-polish', slug: 'release-wording' })
  st = (await tr.get('/api/state')).data
  assert.ok(st.model.sections.flatMap(x => x.rows).some(x => x.key === 'task:release-wording'))
  assert.ok(st.model.files.some(f => f.slug === 'release-wording'))
  assert.equal((await act('task_unmerge', { keep: 'release-polish', slug: 'release-wording' })).error.code, 'not_applicable')
  assert.ok(await act('task_unmerge', { keep: 'release-polish', slug: 'docs-search', as: 'backlog' }))
  assert.ok((await tr.get('/api/state')).data.model.files.some(f => f.slug === 'docs-search'))
})

test('the demo takes Back on and a recognised session back: unhide, reopen, running, keep, Not this task', async () => {
  const tr = mock.createMockTransport({ latency: 0 })
  const act = (verb, args) => tr.post('/api/action', { verb, args })
  let st = (await tr.get('/api/state')).data
  const hiddenKey = 'title:Renew the test certificate'
  assert.ok(st.model.hidden.some(r => r.key === hiddenKey))
  await act('unhide', { key: hiddenKey })
  st = (await tr.get('/api/state')).data
  assert.ok(!st.model.hidden.some(r => r.key === hiddenKey) && st.model.sections.flatMap(x => x.rows).some(r => r.key === hiddenKey))
  await act('inbox_reopen', { id: '20261008-1600-quote-check-3e4f' })
  st = (await tr.get('/api/state')).data
  assert.equal(st.model.sections.flatMap(x => x.rows).find(r => r.inbox_id === '20261008-1600-quote-check-3e4f').inbox_state, 'open')
  await act('task_keep', { keys: ['task:report-dark-mode'] })
  st = (await tr.get('/api/state')).data
  assert.equal(st.model.sections.flatMap(x => x.rows).find(r => r.key === 'task:report-dark-mode').bucket, 'tasks')
  // a session recognised at work on a task: Not this task takes the task off, and says so
  const sid = st.sessions.sessions.find(x => x.task_how === 'seen').sid
  const r = await act('session_unlink', { session: sid })
  assert.deepEqual(r.data.session, { sid, refused: 'search-index' })
  assert.match(r.data.note, /no longer counts as work on search-index/)
  st = (await tr.get('/api/state')).data
  assert.equal(st.sessions.sessions.find(x => x.sid === sid).task, null)
  assert.equal((await act('session_unlink', { session: sid })).error.code, 'stale_row')
  await act('session_link', { session: sid, slug: 'search-index' })
  st = (await tr.get('/api/state')).data
  assert.deepEqual([st.sessions.sessions.find(x => x.sid === sid).task, st.sessions.sessions.find(x => x.sid === sid).task_how], ['search-index', 'hand'])
})

test('under an area filter Work through holds the files of that area only: a backlog task of another area is not in Not now', () => {
  const s = cockpitState(NOW, { ui: { page: 'briefing', workView: 'flow', area: 'Docs', flowView: 'overview', flowPicked: [] } })
  const scoped = logic.areaScope(s)
  assert.ok(scoped.model.files.length > 0)
  assert.ok(scoped.model.files.every(f => (f.area_names ?? []).includes('Docs')), 'only the files of the area')
  const idea = logic.flowParts(scoped).leftOut.groups.find(g => g.reason === 'idea')?.rows.map(e => e.row.key) ?? []
  assert.ok(!idea.includes('task:metrics-export'), 'a backlog task of Ops stays out')
  assert.ok(idea.includes('task:docs-search'))
  // the files view's own list stays whole (wholeModel)
  assert.equal(scoped.wholeModel.files.length, s.model.files.length)
})

// ---------------------------------------------------------------- round 4 review: what the walk on the real data found

/** Two tasks about the same thing: one a session runs (Running now), one a point; a third point besides */
function twinState(ui = {}) {
  const tabs = [{ ref: 'surface:1', name: 'board tab', state: 'working', since_ms: NOW - 40 * MIN }]
  const sessions = { sessions: [{ id: 'a', sid: 'a-full', task: 'board-ui', task_how: 'seen', task_since_ms: NOW - 30 * MIN, tab: { ref: 'surface:1' } }] }
  return state({ work: [task('board-ui', { title: 'Board UI' }), task('points-walk', { title: 'Points walk' }), task('other', { title: 'Other' })],
    tabs, sessions, ui: { flowView: 'overview', flowPicked: [], ...ui } })
}

test('UX-1: a task in Running now has a box only for merging; with a point ticked beside it Merge is offered', async () => {
  const s = twinState({ flowPicked: ['task:board-ui', 'task:points-walk'] })
  const parts = logic.flowParts(s)
  assert.deepEqual(parts.lane.map(x => x.row?.key), ['task:board-ui'])
  assert.deepEqual(logic.laneRows(parts.lane).map(r => r.id), ['task:board-ui'])
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${s} c=${c} />`)
  // the box stands in Running now (the view `running`), never on a strip over the overview
  assert.equal(el.$('.flow-runstrip'), null)
  const run = mount(html`<${FlowPage} s=${{ ...s, ui: { ...s.ui, flowView: 'running' } }} c=${c} />`)
  const box = run.$('.flow-main input[type=checkbox]')
  assert.ok(box, 'the entry of Running now has a box')
  assert.ok(box.checked || box.hasAttribute('checked'), 'ticked')
  box.click()
  assert.deepEqual(c.calls.at(-1), ['flowPick', ['task:board-ui'], false])
  const merge = el.button(`${en.flow.merge.button} ▾`)
  assert.ok(merge && !merge.hasAttribute('disabled'), 'a lane task and a point task can be merged')
  merge.click()
  await tick()
  // the one a session runs on is the one that stays: its folder never moves from under the agent
  assert.match(el.$('.flow-merge').text(), /Board UI stays/)
  assert.match(el.$('.flow-merge').text(), new RegExp(en.flow.merge.proposalRunning.slice(0, 25)))
  // a batch never starts, puts off or drops what runs; Done stays a choice
  const lane = s.model.sections[2].rows[0]
  const point = s.model.sections[2].rows[1]
  const sug = logic.batchPlan([lane, point], 'suggested', { ...s, triage: { last: { at: '2026-10-09T08:00' }, items: { 'task:board-ui': { verdict: 'close' }, 'task:points-walk': { verdict: 'close' } } } })
  assert.deepEqual(sug.skipped.map(x => [x.row.key, x.why]), [['task:board-ui', 'working']])
  for (const how of ['later', 'drop', 'do']) {
    assert.deepEqual(logic.batchPlan([lane], how, s, how === 'later' ? '2026-10-12' : 'x').skipped.map(x => x.why), ['working'], how)
  }
  assert.deepEqual(logic.batchPlan([lane, point], 'done', s).calls, [{ verb: 'settle', args: { keys: ['task:board-ui', 'task:points-walk'], outcome: 'done', by: 'batch' } }])
  // All ticks the points, not what runs
  const c2 = recorder()
  const el2 = mount(html`<${FlowPage} s=${twinState()} c=${c2} />`)
  el2.$('.flow-ov-all').click()
  assert.deepEqual(c2.calls.at(-1)[1].sort(), ['task:other', 'task:points-walk'])
  assert.equal(logic.mergeKeep([point, lane], {}, new Set(['task:board-ui'])), 'task:board-ui')
})

test('UX-2: a recognised session whose tab asks stands once, as the card that asks, with its task', () => {
  const sessions = { sessions: [{ id: 'a', sid: 'a-full', task: 'board-ui', task_how: 'seen', task_since_ms: NOW - 30 * MIN, tab: { ref: 'surface:1' } }] }
  // round 6 B: a tab waiting at its prompt and not quiet yet asks as a dialog does; a quiet one is finished and its task
  // a point again; only one at work runs
  for (const [st, idle] of [['working', false], ['waiting', true], ['waiting', false], ['needs-you', false]]) {
    const s = state({ work: [task('board-ui')], tabs: [{ ref: 'surface:1', name: 'board tab', state: st, idle, since_ms: NOW - 5 * MIN }], sessions })
    const parts = logic.flowParts(s)
    const keys = logic.flowKeys(parts)
    if (st === 'needs-you' || (st === 'waiting' && !idle)) {
      assert.deepEqual(parts.lane, [])
      assert.deepEqual(parts.asks.map(x => [x.id, x.row?.key]), [['tab:surface:1', 'task:board-ui']])
      assert.deepEqual(parts.doing, [])
      assert.deepEqual([parts.counts.points, parts.counts.extra], [1, 0])
    } else if (idle) {
      assert.deepEqual(parts.lane, [], 'finished')
      assert.deepEqual(parts.doing.map(x => x.id), ['task:board-ui'])
    } else {
      assert.deepEqual(parts.lane.map(x => x.id), ['session:surface:1'], st)
      assert.equal(parts.counts.points, 0)
    }
    assert.equal(keys.size, 1, st)
  }
})

test('UX-3: the open tasks a page names and the items put off past the window stand in Work through', () => {
  const s = state({ work: [task('a')] })
  s.model.task_rows = [task('job-hunt', { status: null, stream: true, closable: false, bucket: 'do', title: 'Job hunt' }),
    task('parked', { status: 'backlog', closable: true, bucket: 'do' }), task('closed-one', { status: null, closable: false, stream: false })]
  s.model.deferred = [ask('20261020-0800-a-shelved-idea', { art: 'idea', inbox_state: 'deferred', until: '2027-01-25', bucket: 'plan' }),
    ask('20261020-0820-runs-on', { inbox_state: 'deferred', until: '2026-12-01', bucket: 'plan' })]
  s.model.pages = [{ id: 'work', group: 'work', sections: [
    { id: 'ideas', kind: 'inbox', items: [{ inbox: '20261020-0800-a-shelved-idea' }, { inbox: '20261020-0820-runs-on' }] },
    { id: 'tasks', kind: 'tasks', items: [{ task: 'a' }, { task: 'job-hunt' }, { task: 'parked' }, { task: 'closed-one' }] }] }]
  const uni = logic.flowUniverse(s)
  assert.deepEqual([...uni.keys()].sort(), ['inbox:20261020-0800-a-shelved-idea', 'inbox:20261020-0820-runs-on', 'task:a', 'task:job-hunt', 'task:parked'])
  checkInvariant(s, 'pages')
  const parts = logic.flowParts(s)
  const left = Object.fromEntries(parts.leftOut.groups.map(g => [g.reason, g.rows]))
  assert.deepEqual(left.stream.map(e => e.row.key), ['task:job-hunt'])
  // an idea put off for months stands with the ideas and says its day, any other item put off under Later
  assert.deepEqual(left.idea.map(e => [e.row.key, e.until]).sort(), [['inbox:20261020-0800-a-shelved-idea', '2027-01-25'], ['task:parked', null]])
  assert.deepEqual(left.later.map(e => [e.row.key, e.why, e.until]), [['inbox:20261020-0820-runs-on', 'deferred', '2026-12-01']])
  // every inbox item and task the work page shows is in the universe, or closed
  for (const sec of s.model.pages[0].sections) {
    for (const it of sec.items) {
      const ok = it.inbox ? [...uni.values()].some(r => r.inbox_id === it.inbox) : uni.has(`task:${it.task}`) || it.task === 'closed-one'
      assert.ok(ok, JSON.stringify(it))
    }
  }
  // the list says the day an idea put off comes back
  const el = mount(html`<${FlowPage} s=${{ ...s, ui: { ...s.ui, flowView: 'left', flowLeft: 'idea' } }} c=${recorder()} />`)
  const tr = el.$$('.flow-ov-row').find(r => r.text().includes('20261020-0800-a-shelved-idea'))
  assert.match(tr.text(), new RegExp(en.flow.notnow.from('').trim()))
})

test('UX-3: the demo counts the open rows by its own loop, the page by its universe, with task_rows and deferred', () => {
  const NOWD = new Date(2026, 9, 9, 12, 0, 0).getTime()
  for (const opts of [{}, { filesScope: 'all' }]) {
    const demo = mock.buildState(NOWD, opts)
    assert.ok((demo.model.deferred ?? []).length >= 1, 'the demo puts an idea off past the window')
    assert.equal(logic.flowUniverse(demo).size, demo.model.counts.flow_open, JSON.stringify(opts))
    checkInvariant({ ...demo, now: NOWD, ui: { busy: {} } }, `demo ${JSON.stringify(opts)}`)
  }
})

test('UX-4: Back on clears only a real wait; a task whose next step is the person\'s own waits on nobody else', () => {
  const me = { key: 'task:mine', status: 'doing', bucket: 'waiting', card: { next: { what: 'build the next one', who: 'Ada' }, state: { blocked_by: null } } }
  const blocked = { ...task('blocked'), bucket: 'waiting', card: { state: { blocked_by: 'the vendor' } } }
  const other = { ...task('other'), bucket: 'waiting', card: { next: { what: 'answer', who: 'Bob' }, state: { blocked_by: null } } }
  const s = state({ later: [{ ...task('mine'), ...me }, blocked, other] })
  s.work = { ...s.work, person: 'Ada' }
  const parts = logic.flowParts(s)
  const waits = parts.leftOut.groups.flatMap(g => g.rows).filter(e => e.kind === 'waiting').map(e => e.row.key)
  assert.deepEqual(waits.sort(), ['task:blocked', 'task:other'])
  assert.deepEqual(parts.doing.map(x => x.row.key), ['task:mine'], 'its own next step: a point')
  const e = row => ({ row, until: null, why: null, due: null, repo: null })
  const plan = logic.leftPlan([e(blocked), e(other), e(task('fb', { blocked_by: 'x', bucket: 'waiting' }))], 'back', s)
  assert.deepEqual(plan.calls, [{ verb: 'task_running', args: { slug: 'blocked' } }, { verb: 'task_running', args: { slug: 'fb' } }])
  assert.deepEqual(plan.skipped.map(x => [x.row.key, x.why]), [['task:other', 'not_offered']])
  // without a person named, nothing changes: who is someone else
  const s2 = state({ later: [{ ...task('mine'), ...me }] })
  assert.deepEqual(logic.flowParts(s2).leftOut.groups.map(g => [g.reason, g.rows.map(e => e.kind)]), [['later', ['waiting']]])
})

test('UX-6 and UX-7: Prio reads in again at the foot of its left column; a square names every point it counts', async () => {
  const base = mock.buildState(NOW, { workPage: true })
  const st = cockpitState(NOW, { model: base.model, ui: { page: 'briefing', workView: 'flow', flowView: 'overview', flowMode: 'prio', flowPicked: [] } })
  const order = { at_ms: NOW - 30 * MIN, items: [] }
  const s = { ...st, jevOrder: { work: { order, running: false, error: null } } }
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${s} c=${c} />`)
  const foot = el.$('aside .flow-prio-foot')
  assert.ok(foot, 'the foot of Prio level one')
  assert.match(foot.text(), new RegExp(en.flow.prio.foot('Jev', views.flowprio.orderTime(order.at_ms), 0)))
  foot.$('button').click()
  assert.deepEqual(c.calls.at(-1), ['flowPrioRead', 'work', 'jev'])
  const busy = mount(html`<${FlowPage} s=${{ ...s, jevOrder: { work: { order, running: true, ranker: 'jev', error: null } } }} c=${recorder()} />`)
  assert.ok(busy.$$('aside .flow-prio-foot button').every(b => b.hasAttribute('disabled')), 'both wait while one reads in')
  // every point stands unrated: the square lists four, the line says how many more, the reports by their rows
  const none = el.$('.flow-prio-none .flow-prio-sq')
  const n = Number(none.$('.flow-prio-n').text())
  const listed = none.$$('.flow-prio-titles li').length
  assert.equal(listed, Math.min(4, n))
  if (n > 4) assert.match(none.text(), new RegExp(en.flow.prio.more(n - 4)))
})

test('the overview says of a task nobody works on when it last moved; Watching sorts issue numbers as numbers', () => {
  const s = state({ work: [task('idle', { updated: '2026-10-05', created: '2026-10-08' })], ui: { flowView: 'overview', flowPicked: [] } })
  const el = mount(html`<${FlowPage} s=${s} c=${recorder()} />`)
  const tr = el.$$('.flow-ov-row').find(r => r.text().includes('Task idle'))
  assert.match(tr.text(), new RegExp(en.flow.doing.none(4)))
  const w = state({ later: [ref('acme/app', 18), ref('acme/app', 2), ref('acme/app', 101)] })
  const watch = logic.flowParts(w).leftOut.groups.find(g => g.reason === 'watch').rows.map(e => e.row.key)
  assert.deepEqual(watch, ['ref:acme/app#2', 'ref:acme/app#18', 'ref:acme/app#101'])
})

test('an entry of Running now opened in the middle says so in its head, and why it is no point', () => {
  const s = twinState()
  const lane = logic.flowParts(s).lane[0]
  const el = mount(html`<${FlowPage} s=${{ ...s, ui: { ...s.ui, flowView: 'run', flowRunId: lane.id } }} c=${recorder()} />`)
  const head = el.$('.flow-card .fx-kind').text()
  assert.match(head, new RegExp(en.flow.run.label))
  assert.match(head, new RegExp(en.flow.doing.stage.working))
  assert.match(el.$('.flow-card').text(), new RegExp(en.flow.run.cardWhy.slice(0, 30)))
})

// ---------------------------------------------------------------- round 6 B: Work shows Work through only

// the controller's source (app.js mounts no view a test could click), and the body of one of its methods
const APP = fs.readFileSync(new URL('../web/app.js', import.meta.url), 'utf8')
const method = head => {
  const at = APP.indexOf(`\n  ${head}`)
  assert.ok(at >= 0, `app.js has ${head}`)
  return APP.slice(at, APP.indexOf('\n  },', at) > 0 ? APP.indexOf('\n  },', at) : at + 2000)
}

test('R6B 1a: a view not on offer falls back to Work through where it is on, and a way to it never stores it', () => {
  const page = { id: 'work', group: 'work', jev: true }
  const jev = { enabled: true, ready: true }
  assert.equal(logic.workViewOf('due', page, jev, true, ['files', 'flow']), 'flow', 'Due switched off: Work through, not the files')
  assert.equal(logic.workViewOf('area', page, jev, true, ['files', 'flow']), 'flow')
  assert.equal(logic.workViewOf('jev', page, { enabled: false }, true), 'flow', 'Jev gone with every view on: Work through')
  assert.equal(logic.workViewOf('due', page, jev, false, ['files', 'source']), 'area', 'without Work through: the first view kept')
  assert.equal(logic.workViewOf('due', page, jev, true), 'due', 'a view on offer stays')
  const s = { model: { pages: [page] }, jev, work: { flow: { enabled: true }, views: ['files', 'flow'] }, ui: { workView: 'due' } }
  assert.deepEqual(logic.workViewsIn(s), ['flow'])
  assert.equal(logic.workViewIn(s), 'flow')
  // a way names the view it wants: one on offer is taken and kept, one switched off lands on Work through, unkept
  assert.deepEqual(logic.workViewGo(s, 'area'), { view: 'flow', save: false })
  assert.deepEqual(logic.workViewGo(s, 'jev'), { view: 'flow', save: false })
  assert.deepEqual(logic.workViewGo(s, 'dossier'), { view: 'flow', save: false }, 'the files are a tab, never a view kept')
  assert.deepEqual(logic.workViewGo({ ...s, work: { flow: { enabled: true } } }, 'area'), { view: 'area', save: true })
  // the task check keeps a tab of its own once By source is off: its place on the work page is gone with that view
  const pages = [{ id: 'work', group: 'work', sections: [{ id: 'inbox', kind: 'inbox', total: 1 }, { id: 'tasks', kind: 'tasks', total: 1 }] }]
  const kinds = en.workOrder.kinds
  assert.equal(logic.reviewHome(pages, kinds)?.page, 'work')
  assert.equal(logic.reviewHome(pages, kinds, ['due', 'area', 'dossier'])?.page, 'work')
  assert.equal(logic.reviewHome(pages, kinds, ['dossier']), null)
  // round 6 c P2: where Work through is on the check stands there, never on the work page (and no tab either)
  assert.equal(logic.reviewHome(pages, kinds, ['due', 'area', 'dossier', 'flow']), null)
  const off = { model: { pages }, work: { flow: { enabled: false }, views: ['files'] }, ui: { page: 'briefing', workView: 'dossier' } }
  assert.equal(views.nav.reviewHomeOf(off), null)
  assert.ok(views.nav.pageOrder(off).includes('@check'), 'the check tab is back')
  assert.equal(views.nav.reviewHomeOf({ ...off, work: { flow: { enabled: false } } })?.page, 'work')
  // every way of the controller that names a view goes through workViewGo, so none stores a view switched off
  for (const head of ['setPage(id) {', 'setWorkView:', 'openReview() {']) assert.match(method(head), /workViewGo\(/, head)
  assert.match(method('openReview() {'), /reviewHome\(.*workViewsIn\(s\)\)/)
  // a way to Jev's view lands in Work through with Prio on the left where Jev orders the work page
  assert.match(method('setPage(id) {'), /prioOn\(/)
})

test('R6B 1b: flowWhere finds a row on the page by its key, and select opens it there when the work tab shows no Due', () => {
  const s = state({ now: [ask('20261009-0900-a-q')], work: [task('run'), task('free')], hidden: [task('put-off', { hidden_until: '2026-10-20' })],
    tabs: [{ ref: 'surface:5', name: 'run', slug: 'run', state: 'working', since_ms: NOW - MIN }] })
  assert.deepEqual(logic.flowWhere(s, 'inbox:20261009-0900-a-q'), { view: 'point', id: 'inbox:20261009-0900-a-q' })
  assert.deepEqual(logic.flowWhere(s, 'task:free'), { view: 'point', id: 'task:free' })
  assert.deepEqual(logic.flowWhere(s, 'task:run'), { view: 'run', id: 'tab:surface:5' })
  assert.deepEqual(logic.flowWhere(s, 'task:put-off'), { view: 'left', id: 'later' })
  assert.equal(logic.flowWhere(s, 'task:nowhere'), null)
  assert.equal(logic.flowWhere(s, null), null)
  // a question that stands for its task: the task's key finds that question
  const covered = state({ now: [ask('20261009-0901-a-t', { task: 'cov' })], work: [task('cov')] })
  assert.deepEqual(logic.flowWhere(covered, 'task:cov'), { view: 'point', id: 'inbox:20261009-0901-a-t' })
  // a click on a tab's name (views/tabs.js TabCard) selects its row: without Due it opens where the view holds it,
  // in Work through its point, entry or group, elsewhere the detail beside the page
  const select = method('select(key) {')
  assert.match(select, /workViewIn\(/)
  assert.match(select, /flowWhere\(/)
  assert.match(select, /peek\(/)
})

test('R6B 1c: Work through before the first state says it loads or why it cannot, never that everything is decided', () => {
  const s = { ...state(), model: null }
  const el = mount(html`<${FlowPage} s=${s} c=${recorder()} />`)
  assert.ok(!el.text().includes(en.flow.rest.title), 'no calm card before a state')
  assert.ok(el.$('.skeleton'), 'the skeleton of a page that loads')
  assert.ok(!el.$('.flow-grid'), 'no columns without a state')
  const lost = mount(html`<${FlowPage} s=${{ ...s, conn: 'down' }} c=${recorder()} />`)
  assert.match(lost.text(), new RegExp(en.connLost))
  assert.ok(!lost.text().includes(en.flow.rest.title))
  // Due says the same with the same part
  const day = mount(html`<${views.day.DayColumn} s=${{ ...s, conn: 'down' }} c=${recorder()} byKey=${new Map()} />`)
  assert.match(day.text(), new RegExp(en.connLost))
})

test('R6B 1d: a row with steps of its own (an application) opens them in the info drawer from Work through', () => {
  const app = { key: 'item:apps:app-7', ref: 'app-7', title: 'Application seven', bucket: 'do', urgency: 'today', sources: ['apps'] }
  const item = { index: 0, key: 'item:work/apps/app-7', title: 'Application seven', row_id: 'app-7', actions: [{ id: 'followed_up', label: 'Followed up' }] }
  const pages = [{ id: 'work', title: 'Work', group: 'work', sections: [{ id: 'apps', items: [item] }] }]
  const s = state({ now: [app] })
  s.model.pages = pages
  assert.deepEqual(logic.pageStepsOf(app, s), { it: item, page: 'work', section: 'apps' })
  assert.equal(logic.pageStepsOf({ ...app, ref: 'app-8' }, s), null)
  assert.equal(logic.pageStepsOf({ ...app, sources: ['other'] }, s), null)
  assert.equal(logic.pageStepsOf(app, { ...s, model: { ...s.model, pages: [{ ...pages[0], sections: [{ id: 'apps', items: [{ ...item, actions: null }] }] }] } }), null)
  // the open point: its steps beside its verbs
  const c = recorder()
  const point = mount(html`<${FlowPage} s=${{ ...s, ui: { ...s.ui, flowView: 'point', flowAt: { id: app.key, i: 0 } } }} c=${c} />`)
  const btn = point.$$('.flow-aside .flow-can button').find(b => b.text().startsWith(en.rowSteps))
  assert.ok(btn, 'the steps on the point')
  btn.click()
  assert.deepEqual(c.calls.at(-1), ['openInfo', item, 'work', 'apps'])
  // in a list of Not now its title opens the drawer too
  const watched = state({ later: [{ ...app, bucket: 'plan', urgency: null }] })
  watched.model.pages = pages
  const lc = recorder()
  const list = mount(html`<${FlowPage} s=${{ ...watched, ui: { ...watched.ui, flowView: 'left', flowLeft: 'watch', flowLeftPicked: [] } }} c=${lc} />`)
  const title = list.$$('.flow-ov-open').find(b => b.text().includes('Application seven'))
  assert.equal(title.localName, 'button')
  title.click()
  assert.deepEqual(lc.calls.at(-1), ['openInfo', item, 'work', 'apps'])
})

test('R6B 1e: the task check speaks on the point: close, stale and waiting suggest Done, Drop and Later, the newer of check and triage first', () => {
  const rows = [task('closing', { review: { verdict: 'close', reason: 'The guide is merged' } }), task('stale', { review: { verdict: 'stale', reason: 'Nobody asked since' } }),
    task('waits', { review: { verdict: 'waiting', reason: 'Waits on the vendor' } }), task('goes', { review: { verdict: 'continue', reason: 'Work goes on' } }),
    task('kept', { review: { verdict: 'close', reason: 'r', kept: true } })]
  const s = state({ work: rows })
  s.model.review = { last: { reviewed_at: '2026-10-09T08:00:00' } }
  const got = Object.fromEntries(rows.map(r => [r.task, logic.flowSuggestion(r, s)]))
  assert.deepEqual([got.closing.verb, got.closing.from, got.closing.reason, got.closing.at], ['done', 'check', 'The guide is merged', '2026-10-09T08:00:00'])
  assert.equal(got.stale.verb, 'drop')
  assert.deepEqual([got.waits.verb, got.waits.until], ['later', '2026-10-12'])
  assert.equal(got.goes, null, 'go on is no verb')
  assert.equal(got.kept, null, 'a verdict the person kept the task against says nothing')
  // the triage of the day and the check on one row: the newer one speaks
  const tri = at => ({ last: { at }, items: { 'task:closing': { verdict: 'stale', reason: 'From the triage' } } })
  assert.equal(logic.flowSuggestion(rows[0], { ...s, triage: tri('2026-10-09T07:00:00') }).from, 'check')
  assert.equal(logic.flowSuggestion(rows[0], { ...s, triage: tri('2026-10-09T09:00:00') }).from, 'triage')
  // Tick the suggestions takes them, the overview and the point say where they come from
  assert.deepEqual(logic.batchPreselect(rows, s), ['task:closing', 'task:stale', 'task:waits'])
  const el = mount(html`<${FlowPage} s=${{ ...s, ui: { ...s.ui, flowView: 'overview', flowPicked: [] } }} c=${recorder()} />`)
  const day = logic.formatDay('2026-10-09', 'en')
  assert.match(el.$('.flow-list-from').text(), new RegExp(en.flow.list.from.check(day)))
  const sug = el.$$('.flow-ov-row').find(r => r.text().includes('Task closing')).$('.flow-sug')
  assert.equal(sug.getAttribute('title'), en.flow.list.from.check(day))
  const point = mount(html`<${FlowPage} s=${{ ...s, ui: { ...s.ui, flowView: 'point', flowAt: { id: 'task:closing', i: 0 } } }} c=${recorder()} />`)
  assert.match(point.$('.flow-aside .flow-can-sug').text(), /The guide is merged/)
})

test('R6B 1f, 2c and 2d: Jev\'s daily order and the themes are asked in every order of the left column, Jev never anew by itself', async () => {
  const base = mock.buildState(NOW, { workPage: true })
  const themes = themesState({ assign: {} })
  for (const flowMode of ['themes', 'areas', 'prio']) {
    const st = cockpitState(NOW, { model: base.model, ui: { page: 'briefing', workView: 'flow', flowView: 'overview', flowMode, flowPicked: [] } })
    const c = recorder()
    mount(html`<${FlowPage} s=${{ ...st, themes, jevOrder: {} }} c=${c} />`)
    await until(() => c.calls.some(x => x[0] === 'flowThemesAuto') && c.calls.some(x => x[0] === 'flowPrioOrder'))
    assert.deepEqual(c.calls.filter(x => x[0] === 'flowPrioOrder'), [['flowPrioOrder', 'work']], flowMode)
    assert.ok(c.calls.some(x => x[0] === 'flowThemesAuto'), `${flowMode}: the points without a theme ask for theirs`)
    assert.ok(!c.calls.some(x => ['flowPrioRead', 'jevRun', 'jevRank', 'jevWork'].includes(x[0])), `${flowMode}: no read-in of its own`)
    // with the order there, nothing is asked
    const held = recorder()
    mount(html`<${FlowPage} s=${{ ...st, themes, jevOrder: { work: { order: { at_ms: NOW - MIN, items: [] } } } }} c=${held} />`)
    await tick()
    assert.ok(!held.calls.some(x => x[0] === 'flowPrioOrder'), flowMode)
  }
  // the controller's daily order asks without force (the server: the day's first ask orders, every later one reads)
  assert.match(method('async flowPrioOrder(page) {'), /const daily = jevReady\(s\) && prioLoaded\(s\)/)
  assert.match(method('async flowPrioOrder(page) {'), /daily \? \{ page, daily, rows: prioRows\(s\) \} : \{ page \}/)
  assert.ok(!/force: true/.test(method('async flowPrioOrder(page) {')))
})

test('R6B 1g: the star Only pinned stands over Due, not over Work through, where it acts on nothing', () => {
  const { AreaBar } = views.home
  assert.equal(typeof en.home.pinnedOnly, 'string')
  const s = cockpitState(NOW, { home: { tiles: null, seen: null, pins: ['task:a'] }, ui: { page: 'briefing', workView: 'due' } })
  const pill = el => el.$$('button').some(b => b.text().includes(en.home.pinnedOnly))
  assert.ok(pill(mount(html`<${AreaBar} s=${s} c=${recorder()} />`)), 'Due keeps the star')
  assert.ok(!pill(mount(html`<${AreaBar} s=${{ ...s, ui: { ...s.ui, workView: 'flow' } }} c=${recorder()} />`)))
  // the area chip stays there
  const area = mount(html`<${AreaBar} s=${{ ...s, ui: { ...s.ui, workView: 'flow', area: 'Ops' } }} c=${recorder()} />`)
  assert.ok(area.$('.area-bar-chip') && !pill(area))
})

test('R6B 2a: a tab that waits and has not gone quiet needs you, a quiet one is finished, as everywhere in the cockpit', () => {
  const tabs = [{ ref: 'surface:21', name: 'own', slug: 'own', state: 'waiting', since_ms: NOW - 3 * MIN, last: 'Shall I go on?' },
    { ref: 'surface:22', name: 'own quiet', slug: 'quiet', state: 'waiting', idle: true, since_ms: NOW - 25 * MIN },
    { ref: 'surface:23', name: 'linked', state: 'waiting', since_ms: NOW - 2 * MIN },
    { ref: 'surface:24', name: 'alone', state: 'waiting', since_ms: NOW - 4 * MIN },
    { ref: 'surface:25', name: 'alone quiet', state: 'waiting', idle: true, since_ms: NOW - 40 * MIN }]
  const sessions = { sessions: [
    { id: 'aa', sid: 'aa-full', task: 'link', task_how: 'hand', status: 'idle', started_ms: NOW - 20 * MIN, tab: { ref: 'surface:23', name: 'linked' } },
    { id: 'bb', sid: 'bb-full', task: null, status: 'idle', started_ms: NOW - 50 * MIN, tab: { ref: 'surface:25', name: 'alone quiet' } }] }
  const s = state({ work: [task('own'), task('quiet'), task('link')], tabs, sessions })
  const parts = logic.flowParts(s)
  // the ones not quiet need you: points that ask, with their task where they have one, the oldest first
  assert.deepEqual(parts.asks.map(x => [x.tab.ref, x.row?.key ?? null]), [['surface:24', null], ['surface:21', 'task:own'], ['surface:23', 'task:link']])
  // the quiet one is finished: it runs no more, its task is a point again, and its point says it finished
  assert.deepEqual(parts.lane, [])
  const quiet = parts.doing.find(x => x.id === 'task:quiet')
  assert.equal(logic.flowDrive(quiet, s).stage, 'idle')
  // no session card for a quiet tab either; the tabs that need you keep their session on their point
  assert.deepEqual(parts.sessions, [])
  checkInvariant(s, '2a')
  // in the words of the rest of the cockpit: finished
  assert.equal(text.TABLES.de.flow.doing.stage.idle, text.TABLES.de.state.idle)
  // answered from here, a waiting tab works again as far as the page knows: no point any more
  const mark = t => ({ hash: 'h1', state: t.state, since: t.since_ms })
  const asked = tabs.map(t => (t.ref === 'surface:24' ? { ...t, ask: { hash: 'h1' } } : t))
  const answered = { ...state({ work: [task('own'), task('quiet'), task('link')], tabs: asked, sessions }), ui: { ...state().ui, answered: { 'surface:24': mark(asked[3]) } } }
  assert.ok(!logic.flowParts(answered).asks.some(x => x.tab.ref === 'surface:24'))
})

test('R6B 2b: Next walks the points in the order the overview lists them', async () => {
  const s = state({ now: [ask('20261009-0905-a-q2'), ask('20261009-0900-a-q1')], work: [task('rev', { status: 'review' }), task('doing'), task('first', { priority: 'P0' })],
    tabs: [{ ref: 'surface:5', name: 'a tab asks', state: 'needs-you', since_ms: NOW - 3 * MIN }] })
  const over = mount(html`<${FlowPage} s=${{ ...s, ui: { ...s.ui, flowView: 'overview', flowPicked: [] } }} c=${recorder()} />`)
  const listed = over.$$('.flow-ov-open').map(b => b.text())
  assert.equal(listed.length, 6)
  const pt = mount(html`<${FlowPage} s=${{ ...s, ui: { ...s.ui, flowView: 'point', flowAt: null } }} c=${recorder()} />`)
  pt.$('.flow-walk .dz-pos').click()
  await tick()
  assert.deepEqual(pt.$$('.dz-queue-title').map(b => b.text()), listed)
  // the walk and the overview take one order (views/flowlist.js walkOrder): a square of Prio by Jev's rank too
  const points = logic.flowQueue(logic.flowParts(s))
  assert.deepEqual(views.flowlist.walkOrder(points).map(x => x.id), views.flowlist.listRows(points).map(r => r.x.id).filter((id, i, a) => a.indexOf(id) === i))
  assert.deepEqual(views.flowlist.walkOrder([...points].reverse(), 'rank').map(x => x.id), [...points].reverse().map(x => x.id))
})

test('R6B 2e: a sentence to all or to the ticked ones leaves a row an agent works on alone; on the open point it acts', () => {
  const s = state({ work: [task('run'), task('free')], tabs: [{ ref: 'surface:9', name: 'run', slug: 'run', state: 'needs-you', since_ms: NOW - MIN }] })
  const plan = point => ({ point, steps: [{ op: 'later', keys: ['task:run', 'task:free'], until: '2026-10-12' },
    { op: 'drop', keys: ['task:run'], reason: 'not_needed' }, { op: 'done', keys: ['task:run'] }] })
  const all = logic.instructCalls(plan(false), s)
  assert.deepEqual(all.skipped.map(x => [x.step, x.key, x.why]), [[0, 'task:run', 'working'], [1, 'task:run', 'working']])
  assert.deepEqual(all.calls.map(x => [x.verb, x.args.key ?? x.args.keys]), [['later', 'task:free'], ['settle', ['task:run']]])
  const one = logic.instructCalls(plan(true), s)
  assert.deepEqual(one.skipped, [])
  assert.deepEqual(one.calls.map(x => x.verb), ['later', 'later', 'shelve', 'settle'])
})

test('R6B 2f: one group Later holds what is put off, what waits on others and what rests, each row saying why, its verbs its own', () => {
  const s = state({ work: [task('blocked', { blocked_by: 'the vendor' }), task('quiet', { bucket: 'resting', updated: '2026-10-01' }),
    task('waits', { bucket: 'waiting', card: { next: { what: 'answer', who: 'Bob' } } })],
  later: [ask('20261009-0904-a-w', { bucket: 'waiting' }), ask('20261009-0903-a-ok', { inbox_state: 'approved' })],
  hidden: [task('put-off', { hidden_until: '2026-10-20' })] })
  const parts = logic.flowParts(s)
  assert.deepEqual(logic.FLOW_LEFT_OUT, ['later', 'idea', 'stream', 'watch', 'github'])
  assert.deepEqual(parts.leftOut.groups.map(g => g.reason), ['later'])
  const later = parts.leftOut.groups[0].rows
  assert.deepEqual(later.map(e => [e.row.key, e.kind]), [['task:put-off', 'later'], ['task:waits', 'waiting'], ['inbox:20261009-0903-a-ok', 'waiting'],
    ['inbox:20261009-0904-a-w', 'waiting'], ['task:blocked', 'resting'], ['task:quiet', 'resting']])
  checkInvariant(s, '2f')
  // the column Why: until when, on whom, since when
  const lang = 'en'
  const el = mount(html`<${FlowPage} s=${{ ...s, ui: { ...s.ui, flowView: 'left', flowLeft: 'later', flowLeftPicked: [] } }} c=${recorder()} />`)
  assert.ok(el.$$('th').some(th => th.text() === en.flow.notnow.cols.why))
  const why = Object.fromEntries(el.$$('.flow-ov-row').map(tr => [tr.$('.flow-ov-open').text(), tr.$('.flow-ov-why').text()]))
  const w = en.flow.notnow.why
  assert.equal(why['Task put-off'], w.hidden(logic.formatDay('2026-10-20', lang)))
  assert.equal(why['Task waits'], w.waits('Bob'))
  assert.equal(why['Question 20261009-0904-a-w'], w.others)
  assert.equal(why['Question 20261009-0903-a-ok'], w.approved)
  assert.equal(why['Task blocked'], w.blocked('the vendor'))
  assert.equal(why['Task quiet'], w.resting(logic.formatDay('2026-10-01', lang)))
  // each row keeps its own verbs: Back on unhides, runs a blocked task again, keeps a resting one
  const plan = logic.leftPlan(later, 'back', s)
  assert.deepEqual(plan.calls.map(x => [x.verb, x.args.key ?? x.args.slug ?? x.args.keys?.[0]]),
    [['unhide', 'task:put-off'], ['task_running', 'blocked'], ['task_keep', 'task:quiet']])
  assert.deepEqual(logic.LEFT_VERBS.later, ['back', 'later', 'done', 'drop'])
})

test('Later: Back on in one click on each row that can come back, beside the batch (as the hidden list of Due had it)', () => {
  const s = state({ work: [task('blocked', { blocked_by: 'the vendor' })], later: [ask('20261009-0904-a-w', { bucket: 'waiting' })],
    hidden: [task('put-off', { hidden_until: '2026-10-20' })] })
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${{ ...s, ui: { ...s.ui, flowView: 'left', flowLeft: 'later', flowLeftPicked: [] } }} c=${c} />`)
  const rowOf = title => el.$$('.flow-ov-row').find(tr => tr.$('.flow-ov-open').text() === title)
  const back = tr => tr.$$('button').find(b => b.text() === en.flow.notnow.back)
  assert.ok(back(rowOf('Task put-off')) && back(rowOf('Task blocked')), 'a row put off and a blocked task')
  assert.ok(!back(rowOf('Question 20261009-0904-a-w')), 'nothing to take back on: no button')
  back(rowOf('Task put-off')).click()
  assert.deepEqual(c.calls.find(x => x[0] === 'flowBatch'), ['flowBatch', [{ verb: 'unhide', args: { key: 'task:put-off' } }], 'left'])
  // the column Why still says only why, and wraps so the button beside it keeps its room
  assert.equal(rowOf('Task put-off').$('.flow-ov-why').text(), en.flow.notnow.why.hidden(logic.formatDay('2026-10-20', 'en')))
  const css = fs.readFileSync(new URL('../web/flow.css', import.meta.url), 'utf8')
  assert.match(css, /\.flow-ov-stage\.flow-ov-why \{ white-space: normal;/)
  assert.match(css, /\.flow-ov-act \{ width: 1%; white-space: nowrap; \}/)
})

test('R6B 2g: the right column stands only while a point or an entry is open; a list of Not now and Prio say how they work in the middle', () => {
  const s = state({ work: [task('a')], later: [ask('20261009-0904-a-w', { bucket: 'waiting' })] })
  const el = mount(html`<${FlowPage} s=${{ ...s, ui: { ...s.ui, flowView: 'overview', flowPicked: [] } }} c=${recorder()} />`)
  assert.ok(!el.$('.flow-aside'), 'no empty Fields card on the overview')
  assert.ok(el.$('.flow-grid').hasClass('no-aside'))
  const pt = mount(html`<${FlowPage} s=${{ ...s, ui: { ...s.ui, flowView: 'point', flowAt: { id: 'task:a', i: 0 } } }} c=${recorder()} />`)
  assert.ok(pt.$('.flow-aside .flow-can') && !pt.$('.flow-grid').hasClass('no-aside'))
  const left = mount(html`<${FlowPage} s=${{ ...s, ui: { ...s.ui, flowView: 'left', flowLeft: 'later', flowLeftPicked: [] } }} c=${recorder()} />`)
  assert.ok(!left.$('.flow-aside'))
  assert.match(left.$('.flow-main').text(), new RegExp(en.flow.notnow.hint.slice(0, 30)))
})

// ---------------------------------------------------------------- round 6 b: the Sessions tab goes, Running now holds the sessions

test('round 6 b S5: a waiting tab that wants you is a point that asks; a quiet one is finished and has no card of Running now', () => {
  const tabs = [{ ref: 'surface:21', name: 'asks at its prompt', state: 'waiting', since_ms: NOW - 4 * MIN },
    { ref: 'surface:22', name: 'went quiet', state: 'waiting', idle: true, since_ms: NOW - 30 * MIN },
    { ref: 'surface:23', name: 'needs you', state: 'needs-you', since_ms: NOW - 2 * MIN }]
  const sessions = { sessions: [
    { id: 'w1', sid: 'w1-full', task: null, status: 'idle', started_ms: NOW - 9 * MIN, tab: { ref: 'surface:21', name: 'asks at its prompt' } },
    { id: 'w2', sid: 'w2-full', task: null, status: 'idle', started_ms: NOW - 40 * MIN, tab: { ref: 'surface:22', name: 'went quiet' } }] }
  const s = state({ work: [task('other')], tabs, sessions })
  const parts = logic.flowParts(s)
  // the oldest question first, a waiting tab beside one that needs you (logic.js wantsYou)
  assert.deepEqual(parts.asks.map(x => x.id), ['tab:surface:21', 'tab:surface:23'])
  assert.deepEqual(queueOf(s).map(x => x.group), ['asks', 'asks', 'doing'])
  // its session stands with the point, not a second time as a card; the quiet one is no point and runs no more
  assert.deepEqual(parts.sessions, [])
  checkInvariant(s, 'waiting tabs')
  // without a terminal driver nothing asks from a tab
  assert.deepEqual(logic.flowParts({ ...s, driver: { caps: [] } }).asks, [])
})

test('round 6 b S1: where Work through lists the sessions, every way to the Sessions tab leads to its Running now', () => {
  const on = state()
  const off = { ...on, work: { flow: { enabled: false } } }
  const kept = { ...on, work: { ...on.work, views: ['files'] } }
  assert.equal(logic.sessionsInFlow(on), true)
  assert.equal(logic.sessionsInFlow(off), false)
  assert.equal(logic.sessionsInFlow(kept), false, 'cockpit.work_views without flow keeps the tab')
  assert.equal(logic.sessionsInFlow(null), false)
  assert.deepEqual(logic.flowPageFor('@sessions', on), { page: 'briefing', view: 'flow', flowView: 'running' })
  assert.equal(logic.flowPageFor('@sessions', off), null)
  assert.equal(logic.flowPageFor('@sessions'), null)
  assert.deepEqual(logic.flowPageFor('@flow', on), { page: 'briefing', view: 'flow' })
  // a note or a status item of the band that names the tab keeps the name, so setPage leads it there
  assert.equal(logic.tickerPage(on, '@sessions', views.nav.pageOrder(on)), '@sessions')
  assert.equal(logic.tickerPage(off, '@sessions', views.nav.pageOrder(off)), '@sessions')
  // the area jumps and the tour name the tab as before: the controller leads them (app.js setPage)
  assert.deepEqual(logic.areaJump('running', {}), { page: '@sessions' })
  assert.ok(logic.tourSteps({ ...on, layout: 'wide' }).some(x => x.page === '@sessions'))
  // the way's name says where it lands
  assert.equal(views.nav.sessionsName(on), en.flow.run.label)
  assert.equal(views.nav.sessionsName(off), en.sessionsTab)
})

test('round 6 b S2 S6: no Sessions tab and no AI badge where Running now lists the sessions; without Work through both stay', () => {
  const on = cockpitState(NOW, { ui: { page: 'briefing' } })
  const off = cockpitState(NOW, { work: { ...on.work, flow: { enabled: false } }, ui: { page: 'briefing' } })
  assert.ok(!views.nav.pageOrder(on).includes('@sessions'))
  assert.ok(views.nav.pageOrder(off).includes('@sessions'))
  assert.ok(views.nav.morePages(off).has('@sessions'))
  // the demo leaves the AI something to look at, so the badge would show on the tab
  assert.ok(logic.aiWaiting(on.model.returns, on.tabs.tabs, NOW) > 0)
  const tabsOf = s => mount(html`<${views.header.PageBar} s=${s} c=${recorder()} />`).$$('[role=tab]')
  const named = (list, word) => list.find(b => b.text().startsWith(word)) ?? null
  assert.ok(!named(tabsOf(on), en.sessionsTab), 'no Sessions tab')
  assert.ok(!tabsOf(on).some(b => b.$$('.pbadge').some(x => x.text().startsWith(en.aiBadge))), 'no AI badge anywhere')
  const kept = named(tabsOf(off), en.sessionsTab)
  assert.ok(!!kept, 'the Sessions tab stays without Work through')
  assert.match(kept.text(), new RegExp(`${en.aiBadge}`))
})

test('round 6 b: the tour shows Running now where it lists the sessions, the Sessions tab elsewhere, in both languages', () => {
  const on = { ...state(), layout: 'wide' }
  const off = { ...on, work: { flow: { enabled: false } } }
  const step = s => logic.tourSteps(s).find(x => x.page === '@sessions')
  assert.equal(step(on).id, 'running')
  assert.equal(step(off).id, 'sessions')
  for (const lang of ['en', 'de']) assert.ok(text.TABLES[lang].tour.steps.running?.body, lang)
  // the explain overlay names the session cards where they stand now
  const hints = logic.hintsFor({ ...on, ui: { page: 'briefing', workView: 'flow' } }).map(h => [h.id, h.target])
  assert.ok(hints.some(([id, target]) => id === 'sessCards' && target === '.flow-sessions'))
})

// ---------------------------------------------------------------- round 6 c: the task check in Work through

const checkUi = (ui = {}) => demoFlow({ rvFilter: 'all', rvSort: 'verdict', rvPicked: [], ...ui })

test('round 6 c P1: Check tasks stands under Not now with its open verdicts, a click shows the check in the middle', () => {
  const s = checkUi()
  // the demo's check judged three tasks: close, stale and waiting, none kept; close and stale want a decision,
  // waiting only says so
  assert.equal(logic.checkOpen(s.model), 2)
  const judged = (slug, review) => task(slug, { review: { verdict: 'close', kept: false, ...review } })
  const kept = { sections: [{ id: 'work', rows: [judged('a'), judged('b', { kept: true }), judged('c', { verdict: 'continue' }),
    judged('d', { verdict: 'waiting' }), judged('e', { verdict: 'unclear' }), judged('f', { verdict: 'stale' })] }],
    review: { keys: ['task:a', 'task:b', 'task:c', 'task:d', 'task:e', 'task:f', 'task:gone'] } }
  assert.equal(logic.checkOpen(kept), 2, 'a kept verdict, a continue, waiting, unclear and a task closed since are nothing to decide')
  assert.equal(logic.checkOpen({ review: { keys: [] } }), 0)
  assert.equal(logic.checkOpen(null), 0)
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${s} c=${c} />`)
  const row = el.$('aside .flow-check .flow-check-row')
  assert.ok(row, 'a row Check tasks in the left column')
  assert.equal(row.$('.flow-side-label').text(), en.reviewTab)
  assert.equal(row.$('.flow-side-open').text().trim(), en.flow.check.count(2))
  // its own block above Not now, not one of its groups
  const aside = el.$('aside')
  assert.ok(!aside.$('.flow-notnow .flow-check-row'), 'not under the head Not now')
  const kids = aside.childNodes.filter(n => n.nodeType === 1)
  assert.ok(kids.findIndex(n => n.hasClass('flow-check')) < kids.findIndex(n => n.hasClass('flow-notnow')), 'above Not now')
  assert.equal(row.getAttribute('title'), en.flow.check.intro)
  assert.ok(!row.hasClass('is-on'))
  row.click()
  assert.deepEqual(c.calls.at(-1), ['flowCheck'])
  // no run yet: the row stands all the same, the way to the first run
  const none = mount(html`<${FlowPage} s=${{ ...s, model: { ...s.model, review: { running: null, error: null, last: null, keys: [] } } }} c=${recorder()} />`)
  assert.equal(none.$('aside .flow-check-row .flow-side-open').text().trim(), en.flow.check.none)
  // the middle: Back, the name, the run button, the plain line on top, then the check itself
  const c2 = recorder()
  const mid = mount(html`<${FlowPage} s=${checkUi({ flowView: 'check' })} c=${c2} />`)
  assert.ok(mid.$('aside .flow-check-row').hasClass('is-on'), 'the row is marked while the check is open')
  const main = mid.$('.flow-main')
  assert.equal(main.$('.flow-main-title').text().trim(), en.reviewTab)
  assert.equal(main.$('.flow-check-intro').text(), en.flow.check.intro)
  assert.ok(main.$('.review-bar'), 'the verdict filter')
  assert.ok(main.$('.review-top .seg'), 'the sort')
  assert.ok(main.$('.tbl-review'), 'the table with its boxes')
  // the verdicts come first; how the check ran is one folded line under them, its stations inside
  const how = main.$('details.review-how')
  assert.ok(how && !how.getAttribute('open'), 'the run folded')
  assert.ok(how.$('summary').text().length > 0)
  assert.ok(!main.$('.review-top .flow-wrap'), 'no drawn check above the verdicts')
  const parts = main.$('.flow-checklist').childNodes.filter(n => n.nodeType === 1)
  assert.ok(parts.findIndex(n => n.hasClass('psec')) < parts.findIndex(n => n.hasClass('review-how')), 'the table above the run')
  assert.ok(!main.$('.flow-overview'), 'not the overview')
  assert.ok(!mid.$('.flow-aside'), 'no right column')
  assert.ok(!main.$('.flow-dock'), 'no instruction line under the check')
  main.button(en.flow.point.back).click()
  assert.deepEqual(c2.calls.at(-1), ['flowOverview'])
  // the run button says it checks again and what the last check cost, never the heading's words
  const last = checkUi().model.review.last
  const again = en.flow.check.again(en.reviewCost(logic.centsText(last.cost_ct, 'en'), last.cost_known))
  assert.notEqual(again, en.reviewTab)
  main.button(again).click()
  assert.deepEqual(c2.calls.at(-1), ['review'])
  assert.match(en.flow.check.first, /AI/, 'the first run says that it asks the AI')
  // the German line says what the check does, in plain words
  assert.equal(text.TABLES.de.flow.check.intro,
    'Die KI schaut deine Aufgabenordner durch und schlägt vor, was erledigt, liegen geblieben oder wartend aussieht. Nichts passiert ohne deinen Klick.')
  assert.equal(text.TABLES.de.flow.check.count(5), '5 zum Entscheiden')
  assert.equal(text.TABLES.de.flow.check.count(0), 'nichts zu entscheiden')
  assert.equal(text.TABLES.de.flow.check.again('0,33 ct'), 'Neu prüfen lassen (ca. 0,33 ct)')
})

test('round 6 c P2: where Work through is on, the check has no tab and every way to it lands there; without it the tab stays', () => {
  const on = state()
  const off = { ...on, work: { flow: { enabled: false } } }
  const kept = { ...on, work: { ...on.work, views: ['files'] } }
  assert.equal(logic.checkInFlow(on), true)
  assert.equal(logic.checkInFlow(off), false)
  assert.equal(logic.checkInFlow(kept), false, 'cockpit.work_views without flow keeps the tab')
  assert.equal(logic.checkInFlow(null), false)
  // a stored page, a deep link, a note: the page id leads to Work through with the check in the middle
  assert.deepEqual(logic.flowPageFor('@check', on), { page: 'briefing', view: 'flow', flowView: 'check' })
  assert.equal(logic.flowPageFor('@check', off), null)
  assert.equal(logic.flowPageFor('@check'), null)
  assert.equal(logic.tickerPage(on, '@check', views.nav.pageOrder(on)), '@check')
  assert.ok(!views.nav.pageOrder(on).includes('@check'), 'no tab of its own')
  assert.ok(views.nav.pageOrder(off).includes('@check'), 'without Work through the tab stays')
  const tabsOf = s => mount(html`<${views.header.PageBar} s=${s} c=${recorder()} />`).$$('[role=tab]')
  assert.ok(!tabsOf(cockpitState(NOW, { ui: { page: 'briefing' } })).some(b => b.text().startsWith(en.reviewTab)))
  const demoOff = cockpitState(NOW, { work: { flow: { enabled: false }, views: ['files'] }, ui: { page: 'briefing' } })
  assert.ok(tabsOf(demoOff).some(b => b.text().startsWith(en.reviewTab)), 'the tab, named Check tasks')
  // the ticker and the start page go through openReview, which falls to setPage(CHECK_PAGE) where no page holds the
  // check, and setPage leads the id through flowPageFor; a stored @check without its tab goes the same way (fixPage)
  assert.match(method('openReview() {'), /if \(!home\) return ctl\.setPage\(CHECK_PAGE\)/)
  assert.match(method('setPage(id) {'), /flowPageFor\(id, s\)/)
  assert.match(APP, /CHECK_PAGE && !pageOrder\(s\)\.includes\(CHECK_PAGE\)\) ctl\.openReview\(\)/)
  assert.match(APP, /flowCheck: \(\) => setUi\(\{ flowView: 'check'/)
  // the explain overlay names the row in Work through, in both languages
  const hints = logic.hintsFor({ ...on, ui: { page: 'briefing', workView: 'flow' } }).map(h => [h.id, h.target])
  assert.ok(hints.some(([id, target]) => id === 'flowCheck' && target === '.flow-check-row'))
  for (const lang of ['en', 'de']) assert.ok(text.TABLES[lang].hints.items.flowCheck?.body, lang)
})

test('6d: a record open in the files tab carries the right column of Work through for its point, the same verbs', () => {
  const s = cockpitState(NOW, { ui: { page: '@files' } })
  const parts = logic.flowParts(s)
  const point = logic.flowQueue(parts, 'all').find(x => x.kind === 'row' && x.row?.task)
  assert.ok(point, 'the demo has a task point')
  const words = el => el.$$('.flow-aside .flow-can button').map(b => b.text().trim())
  const flow = mount(html`<${views.flowside.FlowAside} x=${point} s=${s} c=${recorder()} />`)
  const files = mount(html`<${views.dossier.DossierView} s=${{ ...s, ui: { ...s.ui, dossierOpen: point.row.task } }} c=${recorder()} />`)
  assert.ok(words(flow).length > 2)
  assert.deepEqual(words(files), words(flow))
  // the list opens a record beside it, the walk off (app.js)
  assert.match(APP, /openRecord: \(slug, path\) => setUi\(\{ dossierOpen: String\(path \?\? ''\)\.startsWith\('work\/done\/'\) \? path : slug, filesWalk: false \}\)/)
})
