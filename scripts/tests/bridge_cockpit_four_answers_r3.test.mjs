// SPDX-License-Identifier: MIT
// Round 3 of the simulation of the four answers (cockpit.flow.buckets): what the testers reproduced on simulated
// Bridges, each a case of scripts/web/buckets.js and the views that show a point. No npm dependencies.
//
//   node --test scripts/tests/bridge_cockpit_four_answers_r3.test.mjs
import test from 'node:test'
import assert from 'node:assert/strict'
import { loadCockpit, mount } from './cockpit_render.mjs'

const { html, views, logic, text } = await loadCockpit()

// Friday, 9 October 2026, noon
const NOW = new Date(2026, 9, 9, 12, 0, 0).getTime()
const MIN = 60000
const TOMORROW = '2026-10-10'

const task = (slug, over = {}) => ({ key: `task:${slug}`, task: slug, title: `Task ${slug}`, status: 'doing', bucket: 'plan',
  priority: 'P2', settle: ['done', 'not_doing'], ...over })
const ask = (id, over = {}) => ({ key: `inbox:${id}`, inbox_id: id, title: `Question ${id}`, art: 'ask', inbox_state: 'open',
  bucket: 'do', gate: 'your-yes', settle: ['done', 'not_doing'], ...over })

function state({ now = [], work = [], later = [], tabs = [], hidden = [], taskRows = [], away = [], ui = {}, ...rest } = {}) {
  return {
    now: NOW, model: { sections: [{ id: 'now', rows: now }, { id: 'give', rows: [] }, { id: 'work', rows: work },
      { id: 'track', rows: [] }, { id: 'later', rows: later }], hidden, returns: [], task_rows: taskRows, away,
    buckets: [], aside: { later: 0, list: 0, done_today: 0 } },
    tabs: { tabs, at_ms: NOW }, driver: { caps: ['tabs', 'launch', 'focus', 'screen', 'key', 'send'] }, triage: { items: {} }, jevOrder: {},
    details: {}, work: { flow: { enabled: true, drop_reasons: [], return_after_s: 20, buckets: { enabled: true } } },
    themes: { enabled: false }, quick: { convs: [] }, flow_ai: {},
    ui: { page: '@flow', busy: {}, flowAt: null, flowChip: 'all', flowJump: null, flowView: 'overview', answered: {}, ...ui }, ...rest,
  }
}

const where = (s, key) => logic.bucketPoints(s, 'en').all.filter(x => x.row?.key === key).map(x => x.bucket)

// ---------------------------------------------------------------- Later on a waiting point

test('a waiting task put off to a day is out of sight until it, whatever its blocker says', () => {
  // round 3: Later > Monday on a task waiting for Mika was counted as Later and still stood in Waiting on others
  const t = task('access-review', { bucket: 'waiting', blocked_by: 'waiting for Mika to reply' })
  const s = state({ work: [t], taskRows: [t], away: [{ key: t.key, until: TOMORROW }] })
  assert.deepEqual(where(s, t.key), [])
  // its day came: back where its blocker puts it
  const back = state({ work: [t], taskRows: [t], away: [{ key: t.key, until: '2026-10-09' }] })
  assert.deepEqual(where(back, t.key), ['waiting'])
})

// ---------------------------------------------------------------- a tab whose item is put off or settled

test('a tab whose item is put off or settled is no point anywhere: column, Start, By source', () => {
  // round 3: Later > tomorrow on a tab card's item took it out of Work through, the column card kept the Do chip
  // and the answers, Start led with it as "needs you, Now", By source listed it under Do
  const id = '20261121-2345-health-report-b34f'
  const item = ask(id)
  const tab = { ref: 'surface:9', name: 'Health report', item: id, state: 'needs-you', live: true, since_ms: NOW - 5 * MIN,
    ask: { text: 'Do you want to proceed?', hash: 'h9' } }
  const put = state({ now: [item], tabs: [tab], away: [{ key: item.key, until: TOMORROW }] })
  assert.equal(logic.tabPoint(tab, put), null)
  assert.equal(logic.focusPick([tab], put.model)?.tab?.ref, undefined)
  assert.ok(!logic.homeListParts([tab], put.model).asking.some(t => t.ref === tab.ref))
  assert.equal(logic.rowPoint(item, put).kind, 'row')
  // closed (Done) or dropped (Obsolete): the tab can go, it asks for no answer
  const done = state({ now: [], tabs: [{ ...tab, settled: 'dropped' }] })
  assert.equal(logic.tabPoint({ ...tab, settled: 'dropped' }, done), null)
  // an open one still stands as itself
  const open = state({ now: [item], tabs: [tab] })
  assert.ok(logic.tabPoint(tab, open))
  assert.equal(logic.focusPick([tab], open.model)?.tab?.ref, tab.ref)
})

test('the words of a tab whose item was closed as not done say Obsolete', () => {
  assert.match(text.TABLES.de.tabSettled.dropped, /^Veraltet/)
  assert.match(text.TABLES.en.tabSettled.dropped, /^Obsolete/)
})

test('By source counts a row put off to a later day in no bucket', () => {
  const item = ask('20261121-2345-health-report-b34f')
  const s = state({ now: [item], away: [{ key: item.key, until: TOMORROW }] })
  const byKey = new Map([[item.key, item]])
  assert.equal(logic.itemBucket({ key: item.key, inbox: item.inbox_id, title: item.title }, s, byKey), null)
  const open = state({ now: [item] })
  assert.equal(logic.itemBucket({ key: item.key, inbox: item.inbox_id, title: item.title }, open, byKey), 'do')
})

// ---------------------------------------------------------------- With …

test('With … on a waiting task names no current holder it does not have, and an inbox item with the Bridge says so', () => {
  // round 3: a task waiting on Jordan showed du as the current, greyed choice
  const t = task('health', { bucket: 'waiting', blocked_by: 'waiting for Jordan' })
  const own = logic.ownerChoices({ group: 'row', id: t.key, kind: 'row', row: t }, state({ work: [t] }))
  assert.notEqual(own.current, 'me')
  const withBridge = ask('20261009-0900-q2', { inbox_state: 'deferred', who: 'bridge' })
  assert.equal(logic.ownerChoices({ group: 'row', id: withBridge.key, kind: 'row', row: withBridge }, state()).current, 'bridge')
  const withJordan = ask('20261009-0900-q3', { inbox_state: 'deferred', who: 'Jordan' })
  assert.equal(logic.ownerChoices({ group: 'row', id: withJordan.key, kind: 'row', row: withJordan }, state()).current, 'Jordan')
})

// ---------------------------------------------------------------- Fields: Who follows the bucket

test('Fields > Who says who has the point by its bucket', () => {
  // round 3: Who said the Bridge on a card in Do, you on one in I'll do, nobody on a task waiting on Jordan
  const r = ask('20261009-0900-q4', { card: { next: { what: 'Plan it', who: 'bridge' } } })
  const who = (bucket, row) => logic.fieldsSplit([{ id: 'who', drive: { by: 'none' } }], { bucket, row }, state()).top[0].step?.who
  assert.equal(who('do', r), 'me')
  assert.equal(who('delegate', { ...r, card: { next: { what: 'x', who: 'me' } } }), 'bridge')
  assert.equal(who('waiting', task('h', { blocked_by: 'waiting for Jordan', card: { next: { what: 'Draft', who: 'Jordan' } } })), 'Jordan')
  assert.equal(who('waiting', task('h2', { blocked_by: 'waiting for Jordan' })), 'waiting for Jordan')
})

// ---------------------------------------------------------------- the card of a waiting point

test('a waiting card names what it waits on and how long', () => {
  // round 3: none of the 8 waiting cards named a person or carried a mark, the briefing said "waiting 56 days"
  const c = new Proxy({}, { get: (_, p) => (p === 'then' || typeof p === 'symbol' ? undefined : () => Promise.resolve({ ok: true })) })
  const t = task('logbook', { bucket: 'waiting', blocked_by: 'waiting for Mika to reply', waiting_days: 56 })
  const el = mount(html`<${views.flowbuckets.BucketCard} x=${{ group: 'row', id: t.key, kind: 'row', row: t, bucket: 'waiting' }}
    bucket="waiting" s=${state({ work: [t] })} c=${c} />`)
  assert.match(el.$('.fb-marks').text(), /waiting for Mika to reply/)
  assert.match(el.$('.fb-marks').text(), /waiting for 56 days/)
  const named = task('report', { bucket: 'waiting', card: { next: { what: 'Draft it', who: 'Jordan' } }, waiting_days: 3 })
  const el2 = mount(html`<${views.flowbuckets.BucketCard} x=${{ group: 'row', id: named.key, kind: 'row', row: named, bucket: 'waiting' }}
    bucket="waiting" s=${state({ work: [named] })} c=${c} />`)
  assert.match(el2.$('.fb-marks').text(), /waits on Jordan/)
})

// ---------------------------------------------------------------- Do it on an approved item

test('an item whose yes is given keeps Do it in I\'ll do: it starts now', () => {
  const item = ask('20261009-0900-q5', { inbox_state: 'approved', bucket: 'delegate', has_action: true })
  const got = logic.bucketAnswers({ group: 'row', id: item.key, kind: 'row', row: item }, 'delegate', state({ now: [item] }), 'en')
  assert.equal(got[0].meaning, 'do')
  assert.deepEqual(got[0].run.args, { keys: [item.key], yes: true })
})

// ---------------------------------------------------------------- go on

test('go on is offered only where the tab asks nothing', () => {
  // round 3: the briefing tab asking for an answer by number and a which-way question both got "Go on"
  const s = state()
  const base = { ref: 'surface:14', name: 'Briefing', state: 'waiting', live: true, since_ms: NOW - 5 * MIN }
  const by = tab => logic.replyOptions(tab, s, text.TABLES.en).buttons.map(b => b.verb)
  assert.ok(!by({ ...base, ask: { text: 'Antwort per Nummer, zum Beispiel "3 später montag" oder "1 mach".', hash: 'h1', asks: true } }).includes('tab_go_on'))
  assert.ok(!by({ ...base, ask: { text: 'Which way do you take, and should the answer go to Jordan after?', hash: 'h2', asks: true } }).includes('tab_go_on'))
  assert.ok(by({ ...base, ask: { text: 'Commit now?', hash: 'h3', yes_no: true, asks: true } }).includes('tab_go_on'))
  assert.ok(by({ ...base, ask: { text: 'Summary: the import ran.', hash: 'h4' } }).includes('tab_go_on'))
})
