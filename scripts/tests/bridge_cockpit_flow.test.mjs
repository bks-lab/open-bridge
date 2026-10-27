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

const { html, views, text, logic, mock } = await loadCockpit()
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

test('the page on the demo data: the themes or areas on the left, the overview of all in the middle, a hint on the right', () => {
  const s = cockpitState(NOW, { ui: { page: 'briefing', workView: 'flow' } })
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${s} c=${c} />`)
  assert.ok(el.$('.flow-side') && el.$('.flow-overview') && el.$('.flow-aside'), 'three columns')
  // no tabs over the card and no Focus or List any more, no chips and no lane
  for (const gone of ['.flow-tabs', '.flow-main-top', '.flow-chips', '.flow-lane', '.flow-card', '.flow-walk']) assert.equal(el.$(gone), null, gone)
  // level one: an entry per theme or area, no All entry (the overview of all stands in the middle)
  const mode = logic.flowMode(s)
  const sides = logic.flowSides(s, logic.flowQueue(logic.flowParts(s)), mode).filter(x => x.id !== 'all')
  assert.equal(el.$$('.flow-side-item').length, sides.length)
  el.$$('.flow-side-item')[0].click()
  assert.deepEqual(c.calls.at(-1), ['flowSide', sides[0].id])
  // the middle names the level and shows every point grouped, the right says how details come
  assert.match(el.$('.flow-main-head').text(), new RegExp(mode === 'themes' ? en.flow.side.allThemes : en.flow.side.allAreas))
  assert.ok(el.$$('.flow-ov-row').length >= sides.length)
  assert.match(el.$('.flow-aside').text(), new RegExp(en.flow.fields.overview.slice(0, 30)))
  // the overview has no tabs under a card and no instruction scope of a point
  assert.equal(el.$('.flow-ptabs'), null)
  // the head says how much is in progress and how much is open, and holds the view switch
  assert.match(el.$('.flow-head').text(), /in progress/)
  assert.ok(el.$('.flow-head .work-switch'))
  // narrow: the same choice as a select, its first option the level of all
  const opts = el.$$('.flow-side-select option')
  assert.ok(!opts[0].getAttribute('value'), 'the first option has no side')
  assert.equal(opts.length, sides.length + 1)
})

const opsState = (ui = {}) => cockpitState(NOW, { ...state({ now: [ask('20261009-0900-a-q', { area: 'Ops' })], work: [task('a', { area: 'Ops' }), task('b', { area: 'Docs' })] }),
  ui: { ...state().ui, page: 'briefing', workView: 'flow', flowSide: { areas: 'a:ops' }, flowView: 'overview', flowPicked: [], ...ui } })

test('a theme entered: back to all, its name as the overview, its points grouped with a box, a stage and a chip', () => {
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${opsState()} c=${c} />`)
  const side = el.$('.flow-side')
  // on top the way back, then the name marked as the overview it shows
  el.$('.flow-side-back').click()
  assert.deepEqual(c.calls.at(-1), ['flowSide', null])
  assert.match(el.$('.flow-side-back').text(), new RegExp(en.flow.side.allAreas))
  const title = el.$('.flow-side-title')
  assert.match(title.text(), /Ops/)
  assert.match(title.text(), new RegExp(en.flow.side.overview))
  assert.equal(title.getAttribute('aria-current'), 'true')
  title.click()
  assert.deepEqual(c.calls.at(-1), ['flowOverview'])
  // the groups in the queue's order, a row per point: its box, title, stage and area
  assert.deepEqual(side.$$('.flow-side-group').map(h => h.text()), [en.flow.groups.you, en.flow.groups.doing])
  const items = side.$$('.flow-pt')
  assert.equal(items.length, 2)
  assert.match(items[1].$('.flow-pt-meta').text(), new RegExp(`${en.flow.kind.doing}.*Ops`))
  items[1].$('.flow-pt-open').click()
  assert.deepEqual(c.calls.at(-1), ['flowGo', 'task:a', 1])
  items[1].$('.flow-pt-pick').click()
  assert.deepEqual(c.calls.at(-1), ['flowPick', ['task:a'], true])
  // the middle: the theme's name, the same groups as a table, a title opens the point
  assert.match(el.$('.flow-main-head').text(), /Ops/)
  assert.deepEqual(el.$$('.flow-ov-group').map(h => h.text()), [en.flow.groups.you, en.flow.groups.doing])
  const rows = el.$$('.flow-ov-row')
  assert.equal(rows.length, 2)
  rows[0].$('.flow-ov-open').click()
  assert.deepEqual(c.calls.at(-1), ['flowGo', 'inbox:20261009-0900-a-q', 0])
  // the stage keeps its words whole: no ellipsis in its cell
  assert.ok(!rows[1].$('.flow-ov-stage').getAttribute('class').includes('ellipsis'))
  // the boxes left and in the table are one selection
  const picked = mount(html`<${FlowPage} s=${opsState({ flowPicked: ['task:a'] })} c=${recorder()} />`)
  assert.deepEqual(picked.$$('.flow-pt-pick').map(b => b.hasAttribute('checked')), [false, true])
  assert.deepEqual(picked.$$('.flow-ov-pick').map(b => b.hasAttribute('checked')), [false, true])
  assert.match(picked.$('.flow-ov-bar').text(), new RegExp(en.flow.list.ticked(1, '')))
})

test('the open point: Back to overview, what is ticked, the card with its verbs, the walk on to the next theme', () => {
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${opsState({ flowView: 'point', flowAt: { id: 'task:a', i: 1 }, flowPicked: ['task:a'] })} c=${c} />`)
  assert.equal(el.$('.flow-overview'), null)
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
  assert.deepEqual(el.$$('.flow-pt').map(li => li.getAttribute('class').includes('is-on')), [false, true])
  assert.equal(el.$('.flow-side-title').getAttribute('aria-current'), null)
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
  assert.equal(el.$('.flow-card .flow-sug'), null, 'not on the card')
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
  let el = mount(html`<${FlowPage} s=${cockpitState(NOW, { ...state({ work: [task('busy')], tabs: [busy] }), ui: { ...state().ui, page: 'briefing', workView: 'flow' } })} c=${c} />`)
  const card = el.$('.flow-card')
  assert.match(card.text(), new RegExp(en.flow.kind.doing))
  assert.equal(card.$('.flow-who'), null, 'no box who works on it in the card')
  assert.match(el.$('.flow-aside [data-field=who]').text(), /Agent tab busy: at work, for 18 min/)
  assert.match(card.$('.fx-screen').text(), /Running the tests/)
  assert.equal(el.$('.flow-aside .fx-screen'), null, 'the screen only in the card')
  // a tab at work: To tab is the strong button, View beside it, no Let AI do it
  assert.ok(el.button(en.flow.toTab).hasClass('btn-primary') && el.button(en.flow.view) && el.button(en.flow.verbs.done))
  assert.equal(el.button(`${en.flow.doing.goOn} ▾`), null)
  assert.equal(el.button(`${en.flow.verbs.do} ▾`), null)
  // no tab open: when it last moved, and Let AI go on with it
  c = recorder()
  el = mount(html`<${FlowPage} s=${cockpitState(NOW, { ...state({ work: [task('quiet', { updated: '2026-10-06' })] }), ui: { ...state().ui, page: 'briefing', workView: 'flow' } })} c=${c} />`)
  assert.match(el.$('.flow-aside [data-field=who]').text(), /No tab open, last moved 3 days ago/)
  assert.ok(el.button(`${en.flow.doing.goOn} ▾`).hasClass('btn-primary'))
  assert.equal(el.button(en.flow.toTab), null)
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
  assert.deepEqual(plan.skipped.map(x => [x.row.key, x.why]), [['task:run', 'no_suggestion'], ['task:tabbed', 'no_suggestion']])
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
  // the chip on the left names the suggestion
  assert.match(el.$$('.flow-pt')[0].$('.flow-pt-chip').text(), new RegExp(en.flow.list.verb.done))
  // Tick, left and in the bar: done and drop, never Let AI do it; nothing goes out
  el.button(en.flow.side.tickAi(2)).click()
  assert.deepEqual(c.calls.at(-1), ['flowPick', ['task:d1', 'task:drop'], true])
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
  assert.deepEqual(logic.FLOW_BANDS, ['you', 'doing', 'task', 'reports'])
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
  return cockpitState(NOW, { ...base,
    work: { flow: { enabled: true, drop_reasons: ['resolves_itself', 'not_needed'], return_after_s: 20,
      summary: { enabled: true, budget_per_day: 10, model: null }, instruct: { enabled: true, budget_per_day: 30, model: null },
      attach: { enabled: true, max_mb: 10 }, ...flow } },
    flow_ai: { summary_left: 9, instruct_left: 29, instruct_running: false },
    details: { inbox: {}, task: detail ? { a: { status: 'ok', ver: 0, data: detail } } : {},
      activity: feed ? { [feed.key]: { status: 'ok', ver: 0, data: feed } } : {} },
    ui: { ...base.ui, page: 'briefing', workView: 'flow', flowView: 'point', flowAt: { id: rows[0].key, i: 0 }, flowTab: 'desc', flowFilter: 'all', ...ui } })
}

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
  assert.deepEqual(by.prio.jev, { quadrant: 'plan', rank: 4 })
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
  assert.match(status.$('.flow-chg-old').text(), new RegExp(text.TABLES.en.taskState.backlog))
  assert.match(status.$('.flow-chg-new').text(), new RegExp(text.TABLES.en.taskState.doing))
  assert.match(status.$('.flow-act-who').text(), new RegExp(en.flow.activity.by.git))
  assert.match(status.$('.flow-act-kind').text(), new RegExp(en.flow.activity.kind.status))
  // a decision taken back says so, a theme without an old one shows the new alone
  assert.ok(rows[3].$('.flow-act-undone'))
  assert.match(rows[3].text(), new RegExp(en.flow.activity.undone))
  assert.equal(rows[0].$('.flow-chg-old'), null)
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
  // the reports: All seen on the right, Seen on each report in the card
  const r = mount(html`<${FlowPage} s=${cockpitState(NOW, state({ now: [report('20261009-0901-a-r')] }))} c=${recorder()} />`)
  assert.ok(r.$('.flow-aside').$$('button').some(b => b.text() === en.flow.allSeen))
  assert.ok(!r.$('.flow-card').$$('button').some(b => b.text() === en.flow.allSeen))
})

test('nothing twice: state in the card head, who and source in the fields, the screen in the card, the suggestion on the right', () => {
  const busy = { ref: 'surface:21', name: 'busy', slug: 'a', state: 'working', since_ms: NOW - 18 * MIN, last: 'Running the tests' }
  const themes = themesState({ assign: { 'task:a': 't000001' }, suggest: { 'task:a': { verb: 'done', reason: 'Merged', at_ms: NOW } } })
  const el = mount(html`<${FlowPage} s=${{ ...pointState({ tabs: [busy] }), themes }} c=${recorder()} />`)
  const card = el.$('.flow-card')
  const aside = el.$('.flow-aside')
  const tabs = el.$('.flow-ptabs')
  const where = (sel) => [card, aside, tabs].map(x => x.$$(sel).length)
  assert.deepEqual(where('.state-line'), [1, 0, 0], 'the state once, in the card head')
  assert.deepEqual(where('.fx-screen'), [1, 0, 0], 'the screen once, in the card')
  assert.deepEqual(where('.origin'), [0, 1, 0], 'the source once, in the fields')
  assert.deepEqual(where('.flow-sug'), [0, 1, 0], 'the suggestion once, on the right')
  assert.deepEqual(where('[data-field=who]'), [0, 1, 0], 'who works on it once, in the fields')
  assert.equal(aside.$$('dt').filter(d => /status|state/i.test(d.text())).length, 0)
})

test('instructScope: the open point, with its live tab; in the overview the ticked points, else every point of the side, at most 50', () => {
  const busy = { ref: 'surface:21', name: 'busy', slug: 'a', state: 'working', since_ms: NOW - MIN }
  const s = pointState({ tabs: [busy] })
  const q = queueOf(s)
  const one = logic.instructScope(q[0], q, new Set(), 'Ops', s)
  assert.deepEqual([one.point, one.keys, one.title, one.tab?.ref], [true, ['task:a'], 'Task a', 'surface:21'])
  const many = state({ work: Array.from({ length: 60 }, (_, i) => task(`t${i}`)) })
  const all = queueOf(many)
  const side = logic.instructScope(null, all, new Set(), 'Ops', many)
  assert.deepEqual([side.point, side.picked, side.n, side.keys.length, side.cut], [false, false, 60, 50, true])
  const picked = logic.instructScope(null, all, new Set(['task:t3', 'task:t5']), 'Ops', many)
  assert.deepEqual([picked.picked, picked.keys], [true, ['task:t3', 'task:t5']])
  // the words of the label
  assert.equal(en.flow.instruct.point('Task a'), 'For: Task a')
  assert.match(en.flow.instruct.side(60, 'Ops'), /60 points in Ops/)
})

test('instructCalls: each step through its verb with by instruction, done for several as one settle, a reply to its tab', () => {
  // the tab a reply goes to (the plan names it), no tab of the task: Let AI do it may start on task a
  const live = { ref: 'surface:3', name: 'helper', state: 'waiting', since_ms: NOW - MIN }
  const s = state({ work: [task('a'), task('b'), task('busy')], tabs: [live, { ref: 'surface:4', name: 'busy', slug: 'busy', state: 'working' }] })
  const plan = { id: 'p1', text: 'x', point: false, steps: [
    { n: 1, op: 'done', keys: ['task:a', 'task:b'], titles: ['Task a', 'Task b'], skipped: [] },
    { n: 2, op: 'later', keys: ['task:b'], until: '2026-10-12', skipped: [] },
    { n: 3, op: 'drop', keys: ['task:a'], reason: 'not_needed', skipped: [] },
    { n: 4, op: 'do', mail: true, keys: ['task:a', 'task:busy'], note: 'Write a mail draft, a draft only, never send it: ask about the prices', skipped: [] },
    { n: 5, op: 'reply', keys: ['task:a'], tab_ref: 'surface:3', text: 'yes, go on', skipped: [] },
    { n: 6, op: 'done', keys: ['task:gone'], skipped: [] },
  ], unclear: null }
  const { calls, skipped } = logic.instructCalls(plan, s, 'en')
  assert.deepEqual(calls, [
    { verb: 'settle', args: { keys: ['task:a', 'task:b'], outcome: 'done', by: 'instruction' } },
    { verb: 'later', args: { key: 'task:b', until: '2026-10-12', by: 'instruction' } },
    { verb: 'shelve', args: { key: 'task:a', reason: en.flow.drop.reason.not_needed, by: 'instruction' } },
    { verb: 'do_it', args: { keys: ['task:a'], note: 'Write a mail draft, a draft only, never send it: ask about the prices', by: 'instruction' } },
    { verb: 'tab_send', args: { tab_ref: 'surface:3', text: 'yes, go on', expect: 'waiting', name: 'helper' } },
  ])
  assert.deepEqual(skipped.map(x => [x.key, x.why]), [['task:busy', 'working'], ['task:gone', 'gone']])
  // a reply whose tab is gone runs nothing
  assert.deepEqual(logic.instructCalls({ steps: [{ op: 'reply', keys: ['task:a'], tab_ref: 'surface:99', text: 'y', skipped: [] }] }, s, 'en').calls, [])
  assert.deepEqual(logic.instructCalls(null, s, 'en'), { calls: [], skipped: [] })
})

test('the instruction line: one row while empty, its scope above it, Send asks the server, the plan with Run, Change and Discard', async () => {
  const live = { ref: 'surface:21', name: 'busy', slug: 'a', state: 'waiting', since_ms: NOW - MIN }
  const c = recorder()
  // two points, so the walk bar stands under the line
  const el = mount(html`<${FlowPage} s=${pointState({ rows: [task('a', { area: 'Ops' }), task('b', { area: 'Ops' })], tabs: [live] })} c=${c} />`)
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
  assert.deepEqual(c.calls.find(x => x[0] === 'flowInstruct'), ['flowInstruct', 'done, and ask the vendor about the prices', ['task:a'], true])
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
  const other = st.model.sections.flatMap(x => x.rows).find(x => x.task && x.key !== 'task:demo-task' && !x.inbox_id)
  const one = (await tr.get(`/api/flow/activity?key=${encodeURIComponent(other.key)}`)).data
  assert.deepEqual(one.rows.map(x => x.kind), ['created'])
  assert.equal(one.facts.jev, null)
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
