// SPDX-License-Identifier: MIT
// Tests of the work views by the briefing's buckets (cockpit.flow.buckets): Due, By source, By Jev and the agent
// tabs column say the same bucket words and offer the same answers as the card of Work through
// (views/flowbuckets.js BucketCard), they differ only in order and grouping. No npm dependencies.
//
//   node --test scripts/tests/bridge_cockpit_unify.test.mjs
import test from 'node:test'
import assert from 'node:assert/strict'
import { loadCockpit, mount, recorder, settle as rounds } from './cockpit_render.mjs'

const { html, views, text, logic, jev, components } = await loadCockpit()
const en = text.TABLES.en
const de = text.TABLES.de

const NOW = new Date(2026, 9, 9, 12, 0, 0).getTime()
const MIN = 60000
const TOMORROW = '2026-10-10'

const PROFILE = [
  { id: 'do', title: 'Tun (du, heute)', options: ['ja', 'später', 'streichen'] },
  { id: 'plan', title: 'Planen', options: ['einplanen', 'später'] },
  { id: 'delegate', title: 'Mache ich', options: ['los', 'nicht jetzt'] },
  { id: 'waiting', title: 'Wartet auf andere', options: ['nachfassen', 'warten'] },
  { id: 'drop', title: 'Parken oder streichen', options: ['parken', 'behalten'] },
]

const task = (slug, over = {}) => ({ key: `task:${slug}`, task: slug, title: `Task ${slug}`, status: 'doing', bucket: 'plan',
  priority: 'P2', settle: ['done', 'not_doing'], ...over })
const ask = (id, over = {}) => ({ key: `inbox:${id}`, inbox_id: id, title: `Question ${id}`, art: 'ask', inbox_state: 'open',
  bucket: 'do', gate: 'your-yes', settle: ['done', 'not_doing'], ...over })

function state({ now = [], give = [], work = [], track = [], later = [], tabs = [], buckets = PROFILE, on = true, ui = {}, pages = [], ...rest } = {}) {
  return {
    now: NOW, layout: 'wide', model: { sections: [['now', now], ['give', give], ['work', work], ['track', track], ['later', later]]
      .map(([id, rows]) => ({ id, rows, total: rows.length, compact: rows.map(r => r.key) })), hidden: [], returns: [], buckets, pages },
    tabs: { tabs, at_ms: NOW }, driver: { caps: { key: true, send: true, focus: true, screen: true } }, triage: { items: {} }, jevOrder: {},
    work: { flow: { enabled: true, drop_reasons: ['resolves_itself', 'not_needed'], return_after_s: 20, buckets: { enabled: on } } },
    themes: { enabled: false }, more: {}, details: { inbox: {}, task: {} }, sessions: { sessions: [] },
    ui: { page: 'briefing', busy: {}, picked: [], expanded: { now: true, give: true, work: true, track: true, later: true }, dayHeight: 2000, ...ui },
    ...rest,
  }
}

const dialog = { ref: 'surface:3', name: 'Deploy', state: 'needs-you', since_ms: NOW - 2 * MIN, workspace: 'Home', slug: 'deploy',
  ask: { text: 'Do you want to proceed?\n1. Yes\n2. Yes, and do not ask again\n3. No', hash: 'd1',
    options: [{ n: 1, label: 'Yes' }, { n: 2, label: 'Yes, and do not ask again' }, { n: 3, label: 'No' }] } }
const ready = { ref: 'surface:9', name: 'Contact import', state: 'waiting', since_ms: NOW - 5 * MIN, workspace: 'Home',
  ask: { text: 'Ada Smith is not in Contacts yet.\nShall I try again?', hash: 'h1', draft: true, suggestion: 'yes, try the contact again' } }
const working = { ref: 'surface:5', name: 'Build', state: 'working', since_ms: NOW - 9 * MIN, workspace: 'Home', live: true }

const buttonsOf = el => el.$$('button').map(b => b.text().trim())
const KEYS = /\b(enter|esc|shortcut|taste|kürzel)\b/i

// ---------------------------------------------------------------- the pure part

test('rowPoint: a row whose tab asks stands as that tab, answered in it; any other row as itself', () => {
  const r = task('deploy', { tab: { ref: 'surface:3', live: true, state: 'needs-you' } })
  const s = state({ tabs: [dialog] })
  const p = logic.rowPoint(r, s)
  assert.equal(p.kind, 'tab')
  assert.equal(p.tab.ref, 'surface:3')
  assert.equal(logic.viewBucket(p), 'do')
  const plain = logic.rowPoint(task('x'), s)
  assert.deepEqual([plain.kind, plain.id, logic.viewBucket(plain)], ['row', 'task:x', 'plan'])
  // a backlog task no bucket of the briefing holds stands under drop in a list, never in none
  assert.equal(logic.viewBucket(logic.rowPoint(task('b', { status: 'backlog', bucket: 'tasks' }), s)), 'drop')
})

test('bucketAnswers: a row an agent tab already works on is never started a second time', () => {
  const s = state({ tabs: [working] })
  const r = task('build', { bucket: 'delegate', tab: { ref: 'surface:5', live: true, state: 'working' } })
  const a = logic.bucketAnswers(logic.rowPoint(r, s), 'delegate', s, 'en')
  assert.ok(a.every(x => x.run.verb !== 'do_it'), 'no do_it on a live tab')
  assert.deepEqual(a.map(x => x.meaning), ['later', 'obsolete'])
})

test('workShows: the bucket filter of By source keeps the rows of that bucket, a stale filter of the other mode keeps all', () => {
  const s = state({ work: [task('a', { bucket: 'delegate' }), task('b', { bucket: 'plan' })] })
  const byKey = logic.indexRows(s.model)
  const a = { task: 'a', title: 'A' }
  const b = { task: 'b', title: 'B' }
  assert.deepEqual([a, b].filter(it => logic.workShows(it, s, byKey, 'b:delegate')).map(x => x.task), ['a'])
  assert.equal(logic.workShows(a, s, byKey, 'close'), true, 'a triage filter means nothing in bucket mode')
  const off = state({ on: false, work: s.model.sections[2].rows })
  assert.equal(logic.workShows(a, off, byKey, 'b:plan'), true, 'a bucket filter means nothing with the switch off')
  const counts = logic.bucketCounts([a, b, { title: 'no row' }], s, byKey, 'en')
  assert.equal(counts.all, 3)
  assert.equal(counts.delegate, 1)
  assert.equal(counts.plan, 1)
})

test('one act, one label: Let the AI do it says the delegate answer in bucket mode, Open a tab is no new start, an issue is hidden', () => {
  assert.equal(logic.doWord(state(), 'de'), 'Los')
  assert.equal(logic.doWord(state({ on: false }), 'de'), de.action.do)
  // collect_context starts a tab that reads up: its word is the panel's, never "open a tab"
  assert.equal(de.taskboard.act.openTab, de.btnCollect)
  assert.equal(en.taskboard.act.openTab, en.btnCollect)
  assert.notEqual(de.taskboard.act.openTab, 'Tab öffnen')
})

// ---------------------------------------------------------------- Due

test('Due by buckets: every row its bucket word, the bucket\'s answers, the first strong, the rest under one More', async () => {
  const c = recorder()
  const item = ask('20261009-0900-q1', { brief_nr: 4 })
  const s = state({ now: [item], work: [task('bridges', { bucket: 'delegate' })] })
  const el = mount(html`<${views.day.DayColumn} s=${s} c=${c} byKey=${logic.indexRows(s.model)} />`)
  await rounds()
  const rows = el.$$('li.row')
  assert.equal(rows.length, 2)
  const first = rows[0]
  assert.equal(first.$('.fb-chip').text(), 'Tun (du, heute)')
  // its one number is the printed briefing's, at the row's start; the bar names no second one
  assert.match(first.$('.row-num').text(), /4$/)
  assert.equal(first.$('.fb-chip-nr'), null)
  assert.equal(rows[1].$('.row-num').text(), '')
  const acts = first.$('.row-acts')
  const bs = acts.$$('.fb-bar button')
  assert.equal(bs[0].text().trim(), 'Ja')
  assert.ok(bs[0].hasClass('btn-primary'))
  assert.deepEqual(buttonsOf(acts).filter(x => x !== '☆' && x !== '★'), ['Ja', en.flow.buckets.more])
  // none of the old doors and their words
  assert.doesNotMatch(el.text(), /Let AI do it|Close ▾|AI machen lassen|Abhaken/)
  assert.doesNotMatch(el.$$('.sec-title').map(x => x.text()).join(' '), new RegExp(en.section.now))
  bs[0].click()
  await rounds()
  assert.deepEqual(c.calls.find(x => x[0] === 'act'), ['act', 'do_it', { keys: [item.key], yes: true }])
  // More holds the rest of the bucket's answers, the same acts as the card's
  acts.button(en.flow.buckets.more).click()
  await rounds()
  assert.deepEqual(buttonsOf(acts).filter(x => !['☆', '★', en.flow.buckets.more].includes(x)), ['Ja', 'Später', 'Streichen', en.flow.buckets.obsolete])
  acts.button('Später').click()
  await rounds()
  assert.deepEqual(c.calls.filter(x => x[0] === 'act').at(-1), ['act', 'later', { key: item.key, until: TOMORROW }])
  assert.equal(rows[1].$('.fb-chip').text(), 'Mache ich')
  assert.equal(rows[1].$('.row-acts .btn-primary').text().trim(), 'Los')
  assert.doesNotMatch(el.text(), KEYS)
})

test('Due by buckets: a day first where the answer needs one, the same day picker as the card', async () => {
  const c = recorder()
  const s = state({ work: [task('plan-me')] })
  const el = mount(html`<${views.day.DayColumn} s=${s} c=${c} byKey=${logic.indexRows(s.model)} />`)
  await rounds()
  el.$('.row-acts .btn-primary').click()
  await rounds()
  assert.ok(el.$('.fb-pick'), 'the day picker opens')
  el.$('.fb-pick').button(en.flow.buckets.pick.tomorrow).click()
  await rounds()
  assert.deepEqual(c.calls.find(x => x[0] === 'act'), ['act', 'later', { key: 'task:plan-me', until: TOMORROW, plan: true }])
})

test('Due by buckets: a row whose tab asks offers the tab\'s own answers, never a bare yes for a choice', async () => {
  const c = recorder()
  const s = state({ now: [task('deploy', { bucket: 'do', tab: { ref: 'surface:3', live: true, state: 'needs-you' } })], tabs: [dialog] })
  const el = mount(html`<${views.day.DayColumn} s=${s} c=${c} byKey=${logic.indexRows(s.model)} />`)
  await rounds()
  const acts = el.$('.row-acts')
  assert.equal(acts.$('.btn-primary').text().trim(), 'Yes')
  acts.$('.btn-primary').click()
  await rounds()
  assert.deepEqual(c.calls.find(x => x[0] === 'reply'), ['reply', 'tab_option', { tab_ref: 'surface:3', n: 1, seen: 'd1', name: 'Deploy' }])
})

test('Due by buckets: the selection offers the delegate bucket\'s answers for every picked row', async () => {
  const c = recorder()
  const s = state({ work: [task('a'), task('b')], ui: { picked: ['task:a', 'task:b'] } })
  const el = mount(html`<${views.day.DayColumn} s=${s} c=${c} byKey=${logic.indexRows(s.model)} />`)
  await rounds()
  const bar = el.$('.selbar') ?? el.$('.selection-bar')
  assert.ok(bar, 'the selection bar')
  assert.doesNotMatch(bar.text(), /Let AI do it|Close/)
  bar.button('Los (2)').click()
  await rounds()
  assert.deepEqual(c.calls.find(x => x[0] === 'act'), ['act', 'do_it', { keys: ['task:a', 'task:b'] }])
})

test('Due with the switch off: the old doors stay', async () => {
  const s = state({ on: false, now: [ask('20261009-0900-q1')] })
  const el = mount(html`<${views.day.DayColumn} s=${s} c=${recorder()} byKey=${logic.indexRows(s.model)} />`)
  await rounds()
  assert.equal(el.$('.fb-bar'), null)
  assert.match(el.text(), new RegExp(en.section.now))
  assert.ok(el.$$('button').some(b => b.text().includes(en.settle)))
})

// ---------------------------------------------------------------- By source

function workPage(items) {
  return [{ id: 'work', group: 'work', title: 'Work', sections: [{ id: 'inbox', kind: 'inbox', title: 'Inbox', items, total: items.length }] }]
}

test('By source by buckets: the strip filters by the bucket words, no separate triage words, each row its bucket bar', async () => {
  const c = recorder()
  const q = ask('20261009-0900-q1')
  const t = task('bridges', { bucket: 'delegate' })
  const items = [{ index: 0, title: q.title, inbox: q.inbox_id, key: 'i0' }, { index: 1, title: t.title, task: 'bridges', key: 'i1' }]
  const s = state({ now: [q], work: [t], pages: workPage(items), ui: { workView: 'area' },
    triage: { items: { [q.key]: { gist: 'about the prompt', verdict: 'close', doer: 'ai' } } } })
  const el = mount(html`<${components.PageView} s=${s} c=${c} />`)
  await rounds()
  const strip = el.$('.tri-sort')
  assert.ok(strip)
  const chips = strip.$$('.fchip').map(b => b.text().replace(/\s+\d+$/, '').trim())
  assert.deepEqual(chips, [en.triage.filter.all, ...PROFILE.map(b => b.title)])
  assert.doesNotMatch(el.text(), new RegExp([en.triage.close, en.triage.ai, en.triage.filter.you, en.triage.filter.unclear].join('|')))
  assert.match(el.text(), /about the prompt/, 'the gist stays')
  assert.deepEqual(el.$$('.fb-chip').map(x => x.text()), ['Tun (du, heute)', 'Mache ich'])
  strip.$$('.fchip')[3].click()
  assert.deepEqual(c.calls.at(-1), ['setTriageFilter', 'b:delegate'])
})

test('By source with a bucket picked shows only that bucket\'s rows', async () => {
  const q = ask('20261009-0900-q1')
  const t = task('bridges', { bucket: 'delegate' })
  const items = [{ index: 0, title: q.title, inbox: q.inbox_id, key: 'i0' }, { index: 1, title: t.title, task: 'bridges', key: 'i1' }]
  const s = state({ now: [q], work: [t], pages: workPage(items), ui: { workView: 'area', triageFilter: 'b:delegate' } })
  const el = mount(html`<${components.PageView} s=${s} c=${recorder()} />`)
  await rounds()
  assert.deepEqual(el.$$('.fb-chip').map(x => x.text()), ['Mache ich'])
})

// ---------------------------------------------------------------- the agent tabs

test('the tabs column by buckets: a dialog offers its options, no Yes and No beside them', async () => {
  const c = recorder()
  const s = state({ tabs: [dialog] })
  const el = mount(html`<${views.tabs.TabCard} tab=${dialog} s=${s} c=${c} byKey=${new Map()} slim />`)
  await rounds()
  assert.equal(el.$('.fb-chip').text(), 'Tun (du, heute)')
  const words = buttonsOf(el)
  assert.ok(!words.includes(en.btnYes) || words.filter(w => w === 'Yes').length === 1, 'one Yes, the option, not tab_yes beside it')
  el.$('.fb-bar .btn-primary').click()
  await rounds()
  assert.equal(c.calls.find(x => x[0] === 'reply')?.[1], 'tab_option')
  assert.ok(!c.calls.some(x => x[0] === 'act' && x[1] === 'tab_yes'))
})

test('the tabs column by buckets: a ready answer goes with tab_accept, never Keep going while the line holds text', async () => {
  const c = recorder()
  const s = state({ tabs: [ready] })
  const el = mount(html`<${views.tabs.TabCard} tab=${ready} s=${s} c=${c} byKey=${new Map()} />`)
  await rounds()
  assert.doesNotMatch(el.text(), new RegExp(en.btnGoOn.replace(/"/g, '.')))
  el.$('.fb-bar .btn-primary').click()
  await rounds()
  assert.equal(c.calls.find(x => x[0] === 'reply')?.[1], 'tab_accept')
})

test('the tabs column with the switch off: Yes and No as before', async () => {
  const s = state({ on: false, tabs: [dialog] })
  const el = mount(html`<${views.tabs.TabCard} tab=${dialog} s=${s} c=${recorder()} byKey=${new Map()} slim />`)
  await rounds()
  assert.equal(el.$('.fb-bar'), null)
  assert.ok(buttonsOf(el).includes(en.btnYes))
})

// ---------------------------------------------------------------- By Jev

test('By Jev by buckets: each row of the plan its bucket bar, no second set of words for who and square', async () => {
  const c = recorder()
  const t = task('bridges', { bucket: 'delegate' })
  const s = state({ work: [t] })
  const byKey = logic.indexRows(s.model)
  const items = [{ key: t.key, title: t.title, rank: 1, who: 'me', quadrant: 'now', effort: 0.2, impact: 0.8, priority: 0.9, confidence: 0.7 }]
  const el = mount(html`<${jev.PlanList} items=${items} byKey=${byKey} s=${s} c=${c} emph=${() => false} setHover=${() => {}}
    listRef=${null} extra=${[]} pageItems=${null} onOpen=${() => {}} words=${{ me: 'Tun (du, heute)', delegate: 'Mache ich', quads: { now: 'Tun (du, heute)' } }} />`)
  await rounds()
  assert.equal(el.$('.fb-chip').text(), 'Mache ich')
  assert.equal(el.$$('.jev-pill').filter(p => /Tun|Mache/.test(p.text())).length, 0)
  el.$('.fb-bar .btn-primary').click()
  await rounds()
  assert.deepEqual(c.calls.find(x => x[0] === 'act'), ['act', 'do_it', { keys: [t.key] }])
})
