// SPDX-License-Identifier: MIT
// Tests of Hand over and a Drop that says what it does (Work through: scripts/web/flow.js dropWhat, views/verbbar.js,
// views/flowlist.js BatchBar, views/flowpoint.js CheckinCard), no npm dependencies.
//
//   node --test scripts/tests/bridge_cockpit_hand_over.test.mjs
//
// With the read marks on (cockpit.flow.seen) In progress ▾ is Hand over ▾: only someone else takes it (the Bridge, a
// person the instance names, someone else), never Me, since the person's own later is Revisit. The verb stays work_on.
// Drop says before the click what it will do, from the real setting: a task shelved as an idea that comes back on a day
// (cockpit.flow.drop_idea true, the default) or closed for good (false), an inbox item dropped, an issue only hidden.
import test from 'node:test'
import assert from 'node:assert/strict'
import { cockpitState, loadCockpit, mount, recorder, settle as rounds } from './cockpit_render.mjs'

const { html, views, text, logic } = await loadCockpit()
const en = text.TABLES.en
const de = text.TABLES.de
const tick = () => rounds()
const proto = Object.getPrototypeOf(document.createElement('div'))
if (!proto.querySelector) proto.querySelector = function querySelector(sel) { return this.$(sel) }
proto.focus ??= function focus() { document.activeElement = this }
globalThis.window ??= { addEventListener() {}, removeEventListener() {}, innerWidth: 1280 }

const NOW = new Date(2026, 9, 9, 12, 0, 0).getTime()
const task = (slug, over = {}) => ({ key: `task:${slug}`, task: slug, title: `Task ${slug}`, status: 'doing', bucket: 'tasks',
  priority: 'P2', settle: ['done', 'not_doing'], updated: '2026-10-09', card: { next: { what: 'Go on', who: 'Robin' } }, ...over })
const ask = (id, over = {}) => ({ key: `inbox:${id}`, inbox_id: id, title: `Question ${id.slice(-2)}`, art: 'ask', gate: 'your-call',
  inbox_state: 'open', bucket: 'now', settle: ['done', 'not_doing'], ...over })
const issue = { key: 'ref:acme/app#7', ref: 'acme/app#7', title: 'Fix the export', url: 'https://github.com/acme/app/issues/7', bucket: 'do',
  settle: ['done', 'not_doing'], sources: ['github'] }

function state({ work = [], now = [], seen = { enabled: true }, flow = {}, ui = {}, ...rest } = {}) {
  return {
    now: NOW, model: { sections: [{ id: 'now', rows: now }, { id: 'give', rows: [] }, { id: 'work', rows: work }, { id: 'track', rows: [] },
      { id: 'later', rows: [] }], hidden: [], returns: [], pages: [] },
    tabs: { tabs: [] }, driver: { caps: null }, triage: { items: {} }, jevOrder: {}, home: { tiles: null, seen: null, pins: [] },
    work: { flow: { enabled: true, drop_reasons: ['not_needed'], return_after_s: 20, seen, ...flow } },
    seen: { marks: {}, focus: [] }, themes: { enabled: false }, details: { inbox: {}, task: {}, activity: {} },
    ui: { page: 'briefing', workView: 'flow', busy: {}, flowAt: null, flowChip: 'all', flowJump: null, flowView: 'overview', ...ui }, ...rest,
  }
}
const page = over => cockpitState(NOW, state(over))
const { FlowPage } = views.flow

test('drop_idea: on unless the server says off', () => {
  assert.equal(logic.flowSettings(state()).drop_idea, true)
  assert.equal(logic.flowSettings(state({ flow: { drop_idea: false } })).drop_idea, false)
})

test('dropWhat: what Drop does, by kind and by the setting, in both languages', () => {
  const day = logic.formatDay('2027-01-07', 'en')
  assert.equal(logic.dropWhat(task('a'), state(), 'en'), en.flow.drop.what.idea(day), 'a task comes back as an idea after 90 days')
  assert.equal(logic.dropWhat(task('a'), state({ flow: { drop_idea: false } }), 'en'), en.flow.drop.what.task)
  assert.equal(logic.dropWhat(ask('20261009-0900-q-a1'), state(), 'en'), en.flow.drop.what.inbox)
  assert.equal(logic.dropWhat(issue, state(), 'en'), en.flow.drop.what.issue)
  assert.equal(logic.dropWhat({ key: 'title:x', title: 'A date' }, state(), 'en'), en.flow.drop.what.other)
  assert.equal(de.flow.drop.what.task, 'Schließt die Aufgabe endgültig')
  assert.equal(de.flow.drop.what.idea('7.1.'), 'Schließt die Aufgabe; sie kommt als Idee am 7.1. wieder')
  const words = o => Object.values(o).map(v => (typeof v === 'function' ? v('7.1.') : v))
  for (const w of [...words(de.flow.drop.what), de.flow.marks.handOver, de.flow.marks.handTo, de.flow.marks.handedSince('1.10.', 'Robin')]) {
    assert.ok(!/[–—]|\s-\s/.test(w), w)
  }
})

test('the point: Hand over ▾ in place of In progress, without Me; its Drop says what it does', async () => {
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${page({ work: [task('a')], ui: { flowView: 'point', flowAt: { id: 'task:a', i: 0 } } })} c=${c} />`)
  const hand = el.button(`${en.flow.marks.handOver} ▾`)
  assert.ok(hand, 'Hand over')
  assert.equal(el.button(`${en.flow.simple.work} ▾`), null)
  hand.click()
  await tick()
  const chips = el.$$('.flow-work-chips button').map(b => b.text())
  assert.ok(!chips.includes(en.flow.simple.me), chips.join())
  assert.ok(chips.includes(en.flow.simple.bridge) && chips.includes('Robin'))
  assert.ok(el.text().includes(en.flow.marks.handTo))
  el.button(`${en.flow.verbs.drop} ▾`)?.click() ?? el.button(`${en.flow.simple.drop} ▾`).click()
  await tick()
  assert.equal(el.$('.flow-drop-what').text(), logic.dropWhat(task('a'), state(), 'en'))
})

test('off: In progress keeps Me and its words', async () => {
  const el = mount(html`<${FlowPage} s=${page({ work: [task('a')], seen: { enabled: false }, ui: { flowView: 'point', flowAt: { id: 'task:a', i: 0 } } })}
    c=${recorder()} />`)
  el.button(`${en.flow.simple.work} ▾`).click()
  await tick()
  assert.ok(el.$$('.flow-work-chips button').some(b => b.text() === en.flow.simple.me))
})

test('the batch: Hand over without Me, a drop line per kind ticked, the summary says handed over', async () => {
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${page({ work: [task('a')], now: [ask('20261009-0900-q-a1')], ui: { flowPicked: ['task:a', 'inbox:20261009-0900-q-a1'] } })} c=${c} />`)
  const bar = el.$('.flow-ov-bar')
  bar.$$('button').find(b => b.text() === `${en.flow.marks.handOver} ▾`).click()
  await tick()
  assert.ok(!el.$$('.flow-work .flow-work-chips button').some(b => b.text() === en.flow.simple.me))
  bar.$$('button').find(b => b.text() === `${en.flow.verbs.drop} ▾`).click()
  await tick()
  assert.deepEqual(el.$$('.flow-drop-what').map(p => p.text()).sort(),
    [logic.dropWhat(task('a'), state(), 'en'), en.flow.drop.what.inbox].sort())
  const plan = logic.batchPlan([task('a')], 'work', state(), { who: 'Robin', until: '2026-10-16' })
  assert.match(en.flow.batch.summary(plan), /handed over to Robin/)
  assert.match(en.flow.batch.summary(logic.batchPlan([task('a')], 'work', state({ seen: { enabled: false } }), { who: 'Robin', until: '2026-10-16' })),
    /in progress with Robin/)
})

test('the check-in card says handed over while the marks are on, and its Drop says what it does', async () => {
  const row = task('a', { checkin: { who: 'Robin', until: '2026-10-09', since: '2026-10-02' } })
  const el = mount(html`<${FlowPage} s=${page({ work: [row], ui: { flowView: 'point', flowAt: { id: 'task:a', i: 0 } } })} c=${recorder()} />`)
  assert.equal(el.$('.flow-checkin .fx-sub').text(), en.flow.marks.handedSince(logic.formatDay('2026-10-02', 'en'), 'Robin'))
  el.$('.flow-checkin').$$('button').find(b => b.text() === `${en.flow.verbs.drop} ▾`).click()
  await tick()
  assert.ok(el.$('.flow-checkin .flow-drop-what'))
  const off = mount(html`<${FlowPage} s=${page({ work: [row], seen: { enabled: false }, ui: { flowView: 'point', flowAt: { id: 'task:a', i: 0 } } })} c=${recorder()} />`)
  assert.equal(off.$('.flow-checkin .fx-sub').text(), en.flow.simple.since(logic.formatDay('2026-10-02', 'en'), 'Robin'))
})
