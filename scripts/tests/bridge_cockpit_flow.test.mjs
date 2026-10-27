// SPDX-License-Identifier: MIT
// Tests of the cockpit's Work through page (scripts/web/flow.js, views/flow.js and views/verbbar.js), no npm
// dependencies.
//
//   node --test scripts/tests/bridge_cockpit_flow.test.mjs
//
// The one queue of the page in its fixed groups, each row once, what it leaves out and why, the return card after a
// jump to a tab, the five verbs and what each sends, and the page without a terminal driver. The pure helpers are
// imported as the frontend suite imports them, the views are mounted as the render suite mounts them.
import test from 'node:test'
import assert from 'node:assert/strict'
import { cockpitState, loadCockpit, mount, recorder } from './cockpit_render.mjs'

const { html, views, text, logic } = await loadCockpit()
const { FlowPage } = views.flow
const { VerbBar } = views.verbbar
const en = text.TABLES.en
const tick = () => new Promise(resolve => setTimeout(resolve, 20))
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
    ui: { page: '@flow', busy: {}, flowAt: null, flowChip: 'all', flowJump: null, ...ui }, ...rest,
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
  assert.deepEqual(logic.FLOW_GROUPS, ['back', 'asks', 'result', 'lost', 'question', 'doing', 'task', 'reports'])
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
  const s = state({ now: [ask('20261009-0900-a-new'), ask('20261001-0900-a-old'), ask('20261009-0800-a-due', { due: '2026-10-12' })] })
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
  assert.deepEqual(why, { later: ['task:put-off'], waiting: ['task:waits'], resting: ['task:blocked'], stream: ['task:stream-one'],
    idea: ['inbox:20261009-0900-a-idea', 'task:backlog-one'] })
  assert.equal(parts.leftOut.groups[0].rows[0].until, '2026-10-20')
  assert.equal(parts.leftOut.total, 6)
  assert.deepEqual(parts.leftOut.groups.map(g => g.reason), logic.FLOW_LEFT_OUT)
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
  // in progress: the start first, its task not a second time
  assert.deepEqual(queueOf(s).map(x => x.id), ['start:task:run', 'task:other'])
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

test('the return card: every answer forgets the jump, Not yet too', async () => {
  const jump = { key: 'task:a', ref: 'surface:9', title: 'a', at: NOW - 30 * MIN, armed: true }
  const s = cockpitState(NOW, { ...state({ work: [task('a')], tabs: [{ ref: 'surface:9', name: 'a', slug: 'a', state: 'waiting' }] }),
    ui: { ...state().ui, flowJump: jump } })
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${s} c=${c} />`)
  assert.match(el.$('.flow-card').text(), new RegExp(en.flow.backAsk))
  el.button(en.flow.notYet).click()
  assert.deepEqual(c.calls.at(-1), ['flowBack'])
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
  assert.ok(el.button(en.flow.notYet))
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
  assert.deepEqual(c.calls.at(-1).slice(0, 1), ['laterMonday'])
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
  assert.deepEqual(logic.workViews(null, null, true), ['due', 'dossier', 'flow'])
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

test('the page on the demo data: the left column, the tabs, the card, the details and the files view\'s walk bar', () => {
  const s = cockpitState(NOW, { ui: { page: 'briefing', workView: 'flow' } })
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${s} c=${c} />`)
  assert.ok(el.$('.flow-side') && el.$('.flow-tabs') && el.$('.flow-card') && el.$('.flow-details'), 'three columns and the tabs')
  // no chips and no lane any more: the left column and the tabs stand for them
  assert.equal(el.$('.flow-chips'), null)
  assert.equal(el.$('.flow-lane'), null)
  // the walk is the files view's bar with the words of a point
  const walk = el.$('.flow-walk .dz-walk')
  assert.ok(walk, 'the big bar')
  assert.ok(el.button(en.flow.walk2.prev) && el.button(en.flow.walk2.next))
  // the head says how much is in progress and how much is open, and holds the view switch
  assert.match(el.$('.flow-head').text(), /in progress/)
  assert.ok(el.$('.flow-head .work-switch'))
  // the title of the card opens nothing: no drawer, no walk of its own
  assert.equal(el.$('.flow-card .fx-title button'), null)
  // a tab brings its point to the front, an entry of the left column picks it
  el.$$('.flow-tab')[1].click()
  assert.equal(c.calls.at(-1)[0], 'flowGo')
  el.$$('.flow-side-item')[1].click()
  assert.equal(c.calls.at(-1)[0], 'flowSide')
  // the details come as headings, the goal open; a click pulls another in
  const heads = el.$$('.flow-block-head button')
  assert.ok(heads.length >= 4)
  assert.equal(heads[0].getAttribute('aria-expanded'), 'true')
  heads[1].click()
  assert.deepEqual(c.calls.at(-1), ['flowBlock', 'criteria'])
  // narrow: the same choice as a select over the tabs
  assert.ok(el.$('.flow-side-select select'))
})

test('the left column marks what needs you, the walk leads on to the next area after the last point', () => {
  const s = cockpitState(NOW, { ...state({ now: [ask('20261009-0900-a-q', { area: 'Ops' })], work: [task('a', { area: 'Ops' }), task('b', { area: 'Docs' })] }),
    ui: { ...state().ui, page: 'briefing', workView: 'flow', flowSide: { areas: 'a:ops' }, flowAt: { id: 'task:a', i: 1 } } })
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${s} c=${c} />`)
  const items = el.$$('.flow-side-item')
  assert.deepEqual(items.map(b => [b.$('.flow-side-name').text(), b.$('.flow-side-you')?.text() ?? null, b.$('.flow-side-counts > .mono.muted').text()]),
    [[en.flow.side.allAreas, '1', '3'], ['Ops', '1', '2'], ['Docs', null, '1']])
  assert.ok(items[1].getAttribute('class').includes('is-you') && items[1].getAttribute('aria-current') === 'true')
  // two points in Ops, the second in front: Next leads to Docs
  assert.deepEqual(el.$$('.flow-tab').map(b => b.getAttribute('aria-selected')), ['false', 'true'])
  assert.match(el.$('.dz-walk-next').text(), new RegExp(en.flow.walk2.nextSide('Docs')))
  el.button(en.flow.walk2.toSide).click()
  assert.deepEqual(c.calls.at(-1), ['flowSide', 'a:docs'])
})

test('In progress on the card: who works on it, the last lines, To tab, and Let AI go on only without a tab at work', () => {
  const busy = { ref: 'surface:21', name: 'busy', slug: 'busy', state: 'working', since_ms: NOW - 18 * MIN, last: 'Running the tests' }
  let c = recorder()
  let el = mount(html`<${FlowPage} s=${cockpitState(NOW, { ...state({ work: [task('busy')], tabs: [busy] }), ui: { ...state().ui, page: 'briefing', workView: 'flow' } })} c=${c} />`)
  const card = el.$('.flow-card')
  assert.match(card.text(), new RegExp(en.flow.kind.doing))
  assert.match(card.$('.flow-who').text(), /Agent tab busy: at work, for 18 min/)
  assert.match(card.$('.fx-screen').text(), /Running the tests/)
  assert.ok(el.button(en.flow.toTab) && el.button(en.flow.verbs.done))
  assert.equal(el.button(`${en.flow.doing.goOn} ▾`), null)
  // no tab open: when it last moved, and Let AI go on with it
  c = recorder()
  el = mount(html`<${FlowPage} s=${cockpitState(NOW, { ...state({ work: [task('quiet', { updated: '2026-10-06' })] }), ui: { ...state().ui, page: 'briefing', workView: 'flow' } })} c=${c} />`)
  assert.match(el.$('.flow-who').text(), /No tab open, last moved 3 days ago/)
  assert.ok(el.button(`${en.flow.doing.goOn} ▾`))
  assert.equal(el.button(en.flow.toTab), null)
})

test('the List: suggestions with where they come from, Take the suggestions, one line to confirm, then the batch and its undo', async () => {
  const rows = [task('d1'), task('drop'), task('agent'), task('mine')]
  const triage = { last: { at: '2026-10-09T07:00:00' }, items: { 'task:d1': { verdict: 'close', reason: 'The guide is merged' },
    'task:agent': { doer: 'ai', reason: 'A small change' } } }
  const themes = themesState({ assign: {}, suggest: { 'task:drop': { verb: 'drop', reason: 'Nobody needs it', drop: 'not_needed', at_ms: NOW } } })
  const base = { ...state({ work: rows }), triage, themes, ui: { ...state().ui, page: 'briefing', workView: 'flow', flowShow: 'list' } }
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${cockpitState(NOW, base)} c=${c} />`)
  assert.equal(el.$('.flow-details'), null)
  assert.equal(el.$$('.flow-row').length, 4)
  const from = el.$('.flow-list-from').text()
  assert.match(from, /from the triage of/)
  assert.match(from, new RegExp(en.flow.list.from.themes))
  assert.match(from, new RegExp(en.flow.list.honest))
  assert.match(el.$$('.flow-row')[0].text(), /The guide is merged/)
  // nothing goes out before Confirm
  el.button(en.flow.list.take).click()
  await tick()
  assert.equal(c.calls.filter(x => x[0] === 'act' || x[0] === 'flowBatch').length, 0)
  // Take ticks done and drop, never Let AI do it
  const picked = el.$$('.flow-row').map(li => li.getAttribute('class').includes('is-picked'))
  assert.deepEqual(picked, [true, true, false, false])
  assert.match(el.$('.flow-list-confirm').text(), /1 done, 1 drop: No longer needed/)
  el.button(en.flow.list.confirm).click()
  await tick()
  assert.deepEqual(c.calls.find(x => x[0] === 'flowBatch'), ['flowBatch', [{ verb: 'settle', args: { keys: ['task:d1'], outcome: 'done' } },
    { verb: 'shelve', args: { key: 'task:drop', reason: 'No longer needed' } }]])
  // after the batch: one undo for all of it
  const after = mount(html`<${FlowPage} s=${cockpitState(NOW, { ...base, ui: { ...base.ui, flowBatch: { running: false, n: 2, undo: [{ undo: {} }] } } })} c=${c} />`)
  after.button(en.flow.list.undo).click()
  assert.deepEqual(c.calls.at(-1), ['flowBatchUndo'])
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
  assert.deepEqual(queueOf(s).map(x => x.id), ['session:surface:12', 'task:other'])
  // a session tab that stopped working is no longer in the lane, and its task is back in the band
  const quiet = state({ work: [task('mine')], tabs: [{ ...tabs[0], state: 'waiting' }], sessions })
  assert.deepEqual(logic.flowParts(quiet).lane, [])
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

test('a finished start: its result line and the criteria of its brief as a plain list, nothing ticked', () => {
  const row = task('fin', { card: { acceptance: ['The machine boots Linux', 'The backup runs'] } })
  const s = cockpitState(NOW, state({ work: [row], tabs: [{ ref: 'surface:10', name: 'fin', slug: 'fin', state: 'waiting', since_ms: NOW - 25 * MIN }],
    returns: [startOf('fin', 'result', { tab: { ref: 'surface:10' }, result: { kind: 'note', text: 'Result: driver installed, a restart is open', key: null, at_ms: null } })] }))
  const el = mount(html`<${FlowPage} s=${s} c=${recorder()} />`)
  const card = el.$('.flow-card')
  assert.match(card.text(), new RegExp(`${en.flow.result}.*driver installed`))
  const items = card.$$('.flow-criteria li').map(li => li.text())
  assert.deepEqual(items, ['The machine boots Linux', 'The backup runs'])
  assert.doesNotMatch(card.$('.flow-criteria').text(), /[✓✔☑]/)
  assert.equal(card.$$('input').filter(i => i.getAttribute('type') === 'checkbox').length, 0)
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
  assert.deepEqual(logic.FLOW_GROUPS, ['back', 'asks', 'result', 'lost', 'question', 'doing', 'task', 'reports'])
  // the doing ones: a start of the cockpit, a session typed by hand, the task with its working tab, the quiet one
  const by = Object.fromEntries(parts.doing.map(x => [x.row?.task ?? x.start?.item, logic.flowDrive(x, s)]))
  assert.equal(by.busy.by, 'tab')
  assert.equal(by.busy.tab.ref, 'surface:21')
  assert.equal(by.typed.by, 'session')
  assert.equal(by.started.by, 'start')
  assert.deepEqual([by.quiet.by, by.quiet.days], ['none', 3])
  // the one whose tab asks stands with the tabs that ask, a review task with the tasks
  assert.deepEqual(parts.asks.map(x => x.row?.task), ['asking'])
  assert.deepEqual(parts.task.map(x => x.row.task), ['checked'])
  // what runs counts for max_running as before: the starts and the session tabs at work
  assert.equal(logic.flowRunning(s), 2)
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
  assert.deepEqual(plan.calls, [
    { verb: 'settle', args: { keys: ['task:d1', 'task:d2'], outcome: 'done' } },
    { verb: 'later', args: { key: 'task:later', until: '2026-10-12' } },
    { verb: 'shelve', args: { key: 'task:drop', reason: en.flow.drop.reason.not_needed } },
    { verb: 'do_it', args: { keys: ['task:agent'], note: en.flow.start.note('Task agent') } }])
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
  assert.deepEqual(plan.calls, [{ verb: 'settle', args: { keys: ['task:d1'], outcome: 'done' } }])
  assert.deepEqual(plan.skipped.map(x => x.why), ['not_offered'])
  plan = logic.batchPlan([task('d1'), ask('20261009-0900-a-q')], 'drop', s, 'Nobody needs it')
  assert.deepEqual(plan.calls, [{ verb: 'shelve', args: { key: 'task:d1', reason: 'Nobody needs it' } },
    { verb: 'settle', args: { keys: ['inbox:20261009-0900-a-q'], outcome: 'not_doing', text: 'Nobody needs it' } }])
  assert.equal(logic.batchPlan([task('d1')], 'drop', s, '').calls.length, 0)
  plan = logic.batchPlan([task('d1'), task('d2')], 'later', s, '2026-10-12')
  assert.deepEqual(plan.calls.map(x => x.args), [{ key: 'task:d1', until: '2026-10-12' }, { key: 'task:d2', until: '2026-10-12' }])
})
