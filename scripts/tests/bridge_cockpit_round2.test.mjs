// SPDX-License-Identifier: MIT
// Tests of round 2 of the cockpit simulation (21.11.2026): Work through by the briefing's buckets and the views beside
// it act as the printed briefing acts, show what it shows, and never answer one thing for another. No npm dependencies.
//
//   node --test scripts/tests/bridge_cockpit_round2.test.mjs
import test from 'node:test'
import assert from 'node:assert/strict'
import { loadCockpit, mount, recorder, settle as rounds } from './cockpit_render.mjs'

const { html, views, text, logic } = await loadCockpit()
const de = text.TABLES.de.flow.buckets

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

function state({ now = [], work = [], later = [], tabs = [], buckets = PROFILE, ui = {}, ...rest } = {}) {
  return {
    now: NOW, model: { sections: [{ id: 'now', rows: now }, { id: 'give', rows: [] }, { id: 'work', rows: work },
      { id: 'track', rows: [] }, { id: 'later', rows: later }], hidden: [], returns: [], buckets },
    tabs: { tabs, at_ms: NOW }, driver: { caps: { key: true, send: true, focus: true, screen: true } }, triage: { items: {} }, jevOrder: {},
    work: { flow: { enabled: true, drop_reasons: ['resolves_itself', 'not_needed'], return_after_s: 20, buckets: { enabled: true } } },
    themes: { enabled: false }, details: { inbox: {}, task: {} }, sessions: { sessions: [] },
    ui: { page: '@flow', busy: {}, flowAt: null, flowChip: 'all', flowJump: null, flowView: 'overview', ...ui }, ...rest,
  }
}
const row = r => ({ group: 'question', id: r.key, kind: 'row', row: r })
const answers = (x, bucket, s, lang = 'de') => logic.bucketAnswers(x, bucket, s, lang)

// the deploy dialog of a task's tab, and an inbox item about that task (a reply draft to Jordan)
const deploy = { ref: '%3', name: 'fix-route-planner-eta', state: 'needs-you', since_ms: NOW - MIN, workspace: 'Home', slug: 'fix-route-planner-eta',
  item: null, live: true, ask: { text: './deploy.sh --env staging route-planner\nDo you want to proceed?\n❯ 1. Yes\n2. Yes, and don\'t ask again\n3. No',
    hash: 'd1', options: [{ n: 1, label: 'Yes' }, { n: 2, label: 'Yes, and don\'t ask again' }, { n: 3, label: 'No' }] } }

test('Do\'s Yes is the briefing\'s yes: the item approved, and Go of I\'ll do it stays a start', () => {
  const s = state()
  const item = ask('20261009-0900-q1')
  const [yes] = answers(row(item), 'do', s)
  assert.deepEqual(yes.run, { kind: 'act', verb: 'do_it', args: { keys: [item.key], yes: true } })
  const [go] = answers(row({ ...item, bucket: 'delegate' }), 'delegate', s)
  assert.deepEqual(go.run, { kind: 'act', verb: 'do_it', args: { keys: [item.key] } })
  // an inbox item a tab works on still takes the yes (the tab is not started twice: the server only approves)
  const worked = ask('20261009-0901-q2', { tab: { ref: '%9', live: true } })
  assert.equal(answers(row(worked), 'do', s)[0].run.args.yes, true)
})

test('Not now of I\'ll do it leaves the point as it is: nothing is written, the walk moves on', async () => {
  const s = state()
  const t = task('t', { bucket: 'delegate' })
  const notNow = answers(row(t), 'delegate', s)[1]
  assert.equal(notNow.meaning, 'later')
  assert.deepEqual(notNow.run, { kind: 'skip' })
  const calls = []
  const c = new Proxy({}, { get: (_, p) => (p === 'then' || typeof p === 'symbol' ? undefined : (...a) => { calls.push([p, ...a]) }) })
  const el = mount(html`<${views.flowbuckets.BucketCard} x=${row(t)} bucket="delegate" s=${s} c=${c} onDone=${() => calls.push(['done'])} />`)
  el.$$('.fb-answers button').find(b => b.text() === 'Nicht jetzt').click()
  await rounds()
  assert.ok(!calls.some(x => x[0] === 'act'), 'no act')
  assert.ok(calls.some(x => x[0] === 'done'), 'the walk moves on')
})

test('an inbox item put off to a day the briefing still shows stands in the briefing\'s bucket, back on that day', () => {
  const later = ask('20261009-0901-off', { inbox_state: 'deferred', until: TOMORROW, bucket: 'plan', brief_nr: 4 })
  const s = state({ now: [ask('20261009-0900-q1')], later: [later] })
  const { buckets } = logic.bucketPoints(s, 'de')
  assert.ok(buckets.find(b => b.id === 'plan').points.some(p => p.id === later.key))
})

test('an inbox row about a task whose tab asks keeps its own answers; only the tab\'s own item stands as the tab', () => {
  const s = state({ tabs: [deploy] })
  const reply = ask('20260930-1100-reply-to-jordan-about-the-route-planner', { task: 'fix-route-planner-eta', tab: { ref: '%3', live: true, state: 'needs-you' } })
  const p = logic.rowPoint(reply, s)
  assert.equal(p.kind, 'row', 'the deploy dialog is no answer to the reply draft')
  assert.ok(!answers(p, logic.viewBucket(p), s).some(a => a.run.kind === 'reply'))
  // the task row of that tab still stands as the tab
  assert.equal(logic.rowPoint(task('fix-route-planner-eta', { tab: { ref: '%3', live: true } }), s).kind, 'tab')
  // and an inbox item the tab itself works on
  const own = ask('20260930-1101-own', { tab: { ref: '%4' } })
  assert.equal(logic.rowPoint(own, state({ tabs: [{ ...deploy, ref: '%4', slug: null, item: '20260930-1101-own' }] })).kind, 'tab')
})

test('Next never promises a Yes the card does not offer', () => {
  const s = state()
  // a yes already given: the Bridge runs it
  const yes = ask('20261009-0900-q1', { inbox_state: 'approved', bucket: 'delegate' })
  assert.equal(logic.nextSentence(row(yes), 'delegate', s, 'de'), de.nextApproved)
  // an id the server refuses: nothing to answer here
  const bad = ask('20260930-1530-robin:-new-storage-key-reference-for-the')
  assert.equal(answers(row(bad), 'do', s).length, 0)
  assert.equal(logic.nextSentence(row(bad), 'do', s, 'de'), de.nextNone)
  // a task an agent tab works on: no second start
  const busy = task('busy', { bucket: 'do', tab: { ref: '%7', live: true } })
  assert.ok(!answers(row(busy), 'do', s).some(a => a.meaning === 'yes'))
  assert.equal(logic.nextSentence(row(busy), 'do', s, 'de'), de.nextWorking)
})

test('a card quotes the briefing\'s own answer of the bucket the briefing has the point in', () => {
  // a start got lost: the cockpit asks in Do, the briefing still has no. 8 under Waiting on others
  const t = task('price-list', { bucket: 'waiting', brief_nr: 8 })
  const el = mount(html`<${views.flowbuckets.BucketCard} x=${{ ...row(t), group: 'lost' }} bucket="do" s=${state()} c=${recorder()} />`)
  assert.match(el.$('.fb-nr').text(), /„8 nachfassen“|"8 nachfassen"|8 nachfassen/)
  assert.doesNotMatch(el.$('.fb-nr').text(), /8 ja/)
})
