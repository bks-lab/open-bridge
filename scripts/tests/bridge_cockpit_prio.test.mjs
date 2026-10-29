// SPDX-License-Identifier: MIT
// Tests of Prio on Work through, reading in (scripts/web/flow.js prioRows, views/flowprio.js, app.js), no npm
// dependencies.
//
//   node --test scripts/tests/bridge_cockpit_prio.test.mjs
//
// The read-in takes every point the work view shows, each with the fields the server passes on; two rankers, Jev and
// Haiku, are always on offer at Prio's foot, and the source line names which one made the order. A ranker's Drop is
// never ticked ahead and never offered for a row an agent works on or a task in progress that moved lately; "only
// you" stands only where the ranker said so. Running now is one entry of the left column, never a strip over an
// overview, and a finished tab no longer runs.
import fs from 'node:fs'
import test from 'node:test'
import assert from 'node:assert/strict'
import { cockpitState, loadCockpit, mount, recorder } from './cockpit_render.mjs'

const { html, views, text, logic, mock } = await loadCockpit()
const { FlowPage } = views.flow
const en = text.TABLES.en
const de = text.TABLES.de
const tick = () => new Promise(resolve => setTimeout(resolve, 20))
const proto = Object.getPrototypeOf(document.createElement('div'))
if (!proto.querySelector) proto.querySelector = function querySelector(sel) { return this.$(sel) }
globalThis.window ??= { addEventListener() {}, removeEventListener() {}, innerWidth: 1280 }
for (const k of ['offsetLeft', 'offsetWidth', 'scrollWidth', 'clientWidth']) Object.defineProperty(proto, k, { get: () => 0, configurable: true })

// Friday, 9 October 2026, noon
const NOW = new Date(2026, 9, 9, 12, 0, 0).getTime()
const MIN = 60000
const DAY = 86400000

const task = (slug, over = {}) => ({ key: `task:${slug}`, task: slug, title: `Task ${slug}`, status: 'doing', bucket: 'tasks',
  priority: 'P2', settle: ['done', 'not_doing'], updated: '2026-10-01', ...over })
const ask = (id, over = {}) => ({ key: `inbox:${id}`, inbox_id: id, title: `Question ${id}`, art: 'ask', inbox_state: 'open',
  bucket: 'do', gate: 'only-you', settle: ['done', 'not_doing'], ...over })
const WORK_PAGE = { id: 'work', group: 'work', jev: true, sections: [] }

function state({ now = [], work = [], tabs = [], returns = [], ui = {}, ...rest } = {}) {
  return {
    now: NOW, model: { sections: [{ id: 'now', rows: now }, { id: 'give', rows: [] }, { id: 'work', rows: work },
      { id: 'track', rows: [] }, { id: 'later', rows: [] }], hidden: [], returns, pages: [WORK_PAGE] },
    tabs: { tabs }, driver: { caps: null }, triage: { items: {} }, jevOrder: {},
    work: { flow: { enabled: true, drop_reasons: ['not_worth_it'], return_after_s: 20 } },
    themes: { enabled: false }, jev: { enabled: true, ready: true }, prio: { haiku: { ready: true, budget_left: 4 }, fallback: 'none' },
    ui: { page: '@flow', busy: {}, flowAt: null, flowChip: 'all', flowJump: null, flowView: 'overview', flowPicked: [], ...ui }, ...rest,
  }
}

// ---------------------------------------------------------------- what a read-in sends

test('prioRows: every point the view shows goes, a tab alone and what runs too, each with its fields and no more', () => {
  const s = state({
    now: [ask('20261007-0900-a-q1', { due: '2026-10-10' }), { key: 'ref:acme/web#12', ref: 'acme/web#12', title: 'Fix the login', urgency: 'now', sources: ['github'] }],
    work: [task('review-one', { status: 'review' }), task('busy')],
    tabs: [{ ref: 'surface:5', name: 'research', state: 'needs-you', since_ms: NOW - 3 * MIN },
      { ref: 'surface:9', name: 'busy tab', slug: 'busy', state: 'working', since_ms: NOW - 9 * MIN }],
  })
  const rows = logic.prioRows(s)
  const by = Object.fromEntries(rows.map(r => [r.key, r]))
  assert.deepEqual(Object.keys(by).sort(), ['inbox:20261007-0900-a-q1', 'ref:acme/web#12', 'tab:surface:5', 'task:busy', 'task:review-one'])
  assert.deepEqual(by['inbox:20261007-0900-a-q1'], { key: 'inbox:20261007-0900-a-q1', title: 'Question 20261007-0900-a-q1', kind: 'inbox',
    status: 'open', due: '2026-10-10', since: '2026-10-07', running: false })
  assert.equal(by['ref:acme/web#12'].kind, 'issue')
  assert.equal(by['tab:surface:5'].kind, 'tab')
  assert.equal(by['tab:surface:5'].title, 'research')
  // the task its tab works on stands under Running now: it goes, marked as running
  assert.equal(by['task:busy'].running, true)
  assert.equal(by['task:review-one'].status, 'review')
  assert.equal(by['task:review-one'].since, undefined)
  for (const r of rows) for (const k of Object.keys(r)) assert.ok(['key', 'title', 'kind', 'status', 'due', 'since', 'running'].includes(k), k)
})

test('prioOn: Prio is on offer with Jev or with Haiku, also with Jev switched off', () => {
  const s = state()
  assert.equal(logic.prioOn(s), true)
  assert.equal(logic.prioOn({ ...s, jev: { enabled: false } }), true, 'Haiku alone')
  assert.equal(logic.prioOn({ ...s, prio: { haiku: { ready: false } } }), true, 'Jev alone')
  assert.equal(logic.prioOn({ ...s, jev: { enabled: false }, prio: { haiku: { ready: false } } }), false)
  assert.equal(logic.prioOn({ ...s, prio: undefined, jev: { enabled: false } }), false, 'an older server: no Haiku')
})

test('a tab alone gets its square from the order by its tab key', () => {
  const s = state({ ui: { flowMode: 'prio' }, tabs: [{ ref: 'surface:5', name: 'research', state: 'needs-you', since_ms: NOW - MIN }] })
  s.jevOrder = { work: { order: { at_ms: NOW - MIN, ranker: 'haiku', items: [{ key: 'tab:surface:5', rank: 1, quadrant: 'plan', who: 'delegate' }] } } }
  const all = logic.flowQueue(logic.flowParts(s))
  assert.deepEqual(logic.pointsIn(all, 'q:plan', s, 'prio').map(x => x.id), ['tab:surface:5'])
})

// ---------------------------------------------------------------- the safeguards of a ranker's Drop

test('a ranker never pre-ticks a Drop, and never suggests one where an agent works or a task in progress moved lately', () => {
  const rows = [task('quiet', { updated: '2026-09-01' }), task('fresh', { status: 'review', updated: '2026-10-08' }),
    task('worked'), task('review-unknown', { status: 'review', updated: null })]
  const s = state({ work: rows, tabs: [{ ref: 'surface:4', name: 'w', slug: 'worked', state: 'waiting', since_ms: NOW - MIN }] })
  s.jevOrder = { work: { order: { at_ms: NOW - MIN, ranker: 'jev', items: rows.map((r, i) => ({ key: r.key, rank: i + 1, quadrant: 'drop', who: 'delegate' })) } } }
  assert.equal(logic.flowSuggestion(rows[0], s)?.verb, 'drop', 'a doing task that did not move for weeks')
  assert.equal(logic.flowSuggestion(rows[1], s), null, 'in review and moved yesterday')
  assert.equal(logic.flowSuggestion(rows[2], s), null, 'an agent tab of its task')
  assert.equal(logic.flowSuggestion(rows[3], s), null, 'in review, when it moved unknown')
  assert.deepEqual(logic.batchPreselect(rows, s), [], 'Tick the suggestions leaves a ranker\'s Drop alone')
  // a Drop of the triage is still ticked ahead
  const tri = { ...s, triage: { last: { at: '2026-10-09T08:00:00' }, items: { 'task:quiet': { verdict: 'stale', reason: 'old' } } } }
  assert.deepEqual(logic.batchPreselect(rows, tri), ['task:quiet'])
})

// ---------------------------------------------------------------- the squares, the foot and the source line

function prioState(order, over = {}) {
  const base = mock.buildState(NOW, { workPage: true })
  const st = cockpitState(NOW, { model: base.model, ui: { page: 'briefing', workView: 'flow', flowView: 'overview', flowMode: 'prio', flowPicked: [] } })
  return { ...st, prio: { haiku: { ready: true, budget_left: 3 }, fallback: 'none' }, jevOrder: { work: { order, running: false, error: null } }, ...over }
}

test('the square of now says urgent and important, and "only you" only for what the ranker gave to you', () => {
  const st = prioState(null)
  const keys = logic.flowQueue(logic.flowParts(st)).filter(x => x.row).map(x => x.row.key)
  const order = { at_ms: NOW - 30 * MIN, ranker: 'jev', sent: 3, skipped: { private: 0 },
    items: [{ key: keys[0], rank: 1, quadrant: 'now', who: 'me' }, { key: keys[1], rank: 2, quadrant: 'now', who: 'delegate' },
      { key: keys[2], rank: 3, quadrant: 'now', who: 'delegate' }] }
  const el = mount(html`<${FlowPage} s=${prioState(order)} c=${recorder()} />`)
  const now = el.$$('.flow-prio-grid .flow-prio-sq').find(b => b.getAttribute('data-quadrant') === 'now')
  assert.ok(!/only you/.test(en.flow.prio.sub.now) && !/nur du/.test(de.flow.prio.sub.now), 'the square names no doer')
  assert.match(now.text(), new RegExp(en.flow.prio.onlyYou(1)))
  const none = { ...order, items: order.items.map(x => ({ ...x, who: 'delegate' })) }
  const el2 = mount(html`<${FlowPage} s=${prioState(none)} c=${recorder()} />`)
  const now2 = el2.$$('.flow-prio-grid .flow-prio-sq').find(b => b.getAttribute('data-quadrant') === 'now')
  assert.ok(!now2.text().includes(en.flow.prio.onlyYou(1)) && !/only you/.test(now2.text()))
})

test('the foot offers both rankers at all times; each reads in the points of the view; the line names ranker, time and count', () => {
  const order = { at_ms: NOW - 30 * MIN, ranker: 'haiku', sent: 18, skipped: { private: 2, same: 1 }, items: [] }
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${prioState(order)} c=${c} />`)
  const foot = el.$('aside .flow-prio-foot')
  const buttons = foot.$$('button')
  assert.deepEqual(buttons.map(b => b.text()), [en.flow.prio.readJev, en.flow.prio.readHaiku])
  buttons[0].click()
  assert.deepEqual(c.calls.at(-1), ['flowPrioRead', 'work', 'jev'])
  buttons[1].click()
  assert.deepEqual(c.calls.at(-1), ['flowPrioRead', 'work', 'haiku'])
  const time = views.flowprio.orderTime(order.at_ms)
  assert.match(foot.text(), new RegExp(en.flow.prio.foot('Haiku', time, 18)))
  assert.equal(en.flow.prio.foot('Haiku', '29 Oct 14:10', 18), 'Haiku, 29 Oct 14:10, 18 points')
  assert.equal(de.flow.prio.foot('Haiku', '29. Okt. 14:10', 1), 'Haiku, 29. Okt. 14:10, 1 Punkt')
  assert.match(foot.text(), new RegExp(en.flow.prio.held(2)))
  assert.match(el.$('.flow-prio-from').text(), /Haiku/)
  // Jev switched off: only Haiku; Haiku's runs used up: its button is there and grey
  const off = mount(html`<${FlowPage} s=${{ ...prioState(order), jev: { enabled: false } }} c=${recorder()} />`)
  assert.deepEqual(off.$$('aside .flow-prio-foot button').map(b => b.text()), [en.flow.prio.readHaiku])
  const spent = mount(html`<${FlowPage} s=${prioState(order, { prio: { haiku: { ready: true, budget_left: 0 } } })} c=${recorder()} />`)
  const hb = spent.$$('aside .flow-prio-foot button').find(b => b.text() === en.flow.prio.readHaiku)
  assert.ok(hb.hasAttribute('disabled'))
  // a Jev read-in that fell back says so
  const fell = mount(html`<${FlowPage} s=${prioState({ ...order, fallback: { from: 'jev', code: 'jev_upstream' } })} c=${recorder()} />`)
  assert.match(fell.$('aside .flow-prio-foot').text(), new RegExp(en.flow.prio.fellBack))
})

test('the controller reads in with the rows of the view and the ranker chosen, and keeps the daily order Jev\'s', () => {
  const src = fs.readFileSync(new URL('../web/app.js', import.meta.url), 'utf8')
  const read = src.slice(src.indexOf('async flowPrioRead('), src.indexOf('async flowPrioRead(') + 900)
  assert.match(read, /api\.post\('\/api\/jev\/rank', \{ page, force: true, ranker, rows: prioRows\(store\.get\(\)\) \}\)/)
  const daily = src.slice(src.indexOf('async flowPrioOrder('), src.indexOf('async flowPrioOrder(') + 900)
  assert.match(daily, /daily: jevReady\(s\)/)
  assert.ok(!/ranker: 'haiku'/.test(daily), 'Haiku never orders by itself')
})

test('the point\'s Prio field says only you only where the ranker said so', () => {
  const x = { kind: 'row', group: 'doing', id: 'task:a', row: task('a') }
  const s = state({ work: [task('a')] })
  const feed = who => ({ facts: { jev: { quadrant: 'now', rank: 1, who, urgency: 1, impact: 1, effort: 0 } } })
  const by = who => Object.fromEntries(logic.flowFields(x, s, feed(who), null).map(f => [f.id, f]))
  assert.equal(by('me').prio.jev.who, 'me')
  assert.equal(by('delegate').prio.jev.who, 'delegate')
  assert.ok(!/selbst/.test(de.flow.fields.quadrant.now), 'the square\'s name names no doer')
})

// ---------------------------------------------------------------- Running now: one entry, one count, finished is not running

test('Running now stands only in the left column, never as a strip over an overview; one count for head and column', () => {
  const s = cockpitState(NOW, { ui: { page: 'briefing', workView: 'flow', flowView: 'overview', flowPicked: [] } })
  const parts = logic.flowParts(s)
  const n = logic.runningOf(parts).n
  assert.ok(n >= 1, 'the demo runs something')
  for (const ui of [{}, { flowMode: 'areas', flowSide: { areas: logic.flowSides(s, logic.flowQueue(parts), 'areas')[1]?.id } }]) {
    const el = mount(html`<${FlowPage} s=${{ ...s, ui: { ...s.ui, ...ui } }} c=${recorder()} />`)
    assert.equal(el.$('.flow-main .flow-runstrip'), null, 'no strip over the overview')
    assert.match(el.$('aside .flow-run-cat').text(), new RegExp(`${en.flow.run.label}\\s*${n}`))
    assert.match(el.$('.flow-head').text(), new RegExp(en.flow.count(parts.counts.points, n, parts.counts.left)))
  }
  // the running view still lists them
  const run = mount(html`<${FlowPage} s=${{ ...s, ui: { ...s.ui, flowView: 'running' } }} c=${recorder()} />`)
  assert.ok(run.$('.flow-main .flow-runstrip') || run.$('.flow-main .sess'))
})

test('a finished tab (quiet at its prompt) no longer runs: its task is a point again, its session card leaves Running now', () => {
  const tabs = [{ ref: 'surface:12', name: 'done tab', slug: 'tabbed', state: 'waiting', idle: true, since_ms: NOW - 30 * MIN },
    { ref: 'surface:13', name: 'busy', state: 'working', since_ms: NOW - 2 * MIN }]
  const sessions = { sessions: [
    { id: 'aa11', sid: 'aa11-full', task: 'linked', task_how: 'hand', status: 'idle', started_ms: NOW - 40 * MIN, tab: { ref: 'surface:12', name: 'done tab' } },
    { id: 'bb22', sid: 'bb22-full', task: null, status: 'busy', started_ms: NOW - 5 * MIN, tab: { ref: 'surface:13', name: 'busy' } },
    { id: 'cc33', sid: 'cc33-full', task: null, status: 'idle', started_ms: NOW - 50 * MIN, tab: null }] }
  const s = state({ work: [task('tabbed'), task('linked')], tabs, sessions })
  const parts = logic.flowParts(s)
  assert.deepEqual(parts.lane, [])
  assert.deepEqual(logic.flowQueue(parts).filter(x => x.row).map(x => x.row.key).sort(), ['task:linked', 'task:tabbed'])
  assert.deepEqual(parts.sessions.map(v => v.session.id), ['bb22'])
  assert.equal(logic.runningOf(parts).n, 1)
  // a row of a point an agent works on keeps a small marker in the list
  const at = state({ work: [task('w')], returns: [], tabs: [] })
  assert.equal(logic.rowRunning(task('w'), at), false)
})
