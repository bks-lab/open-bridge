// SPDX-License-Identifier: MIT
// Round 2 of the simulation of the four answers (cockpit.flow.buckets): what the testers reproduced on simulated
// Bridges, each a case of scripts/web/buckets.js and scripts/web/flow.js. No npm dependencies.
//
//   node --test scripts/tests/bridge_cockpit_four_answers_r2.test.mjs
import test from 'node:test'
import assert from 'node:assert/strict'
import { loadCockpit } from './cockpit_render.mjs'

const { logic, text } = await loadCockpit()
const en = text.TABLES.en.flow.buckets
const de = text.TABLES.de.flow.buckets

// Friday, 9 October 2026, noon
const NOW = new Date(2026, 9, 9, 12, 0, 0).getTime()
const MIN = 60000
const TOMORROW = '2026-10-10'

const task = (slug, over = {}) => ({ key: `task:${slug}`, task: slug, title: `Task ${slug}`, status: 'doing', bucket: 'plan',
  priority: 'P2', settle: ['done', 'not_doing'], ...over })
const ask = (id, over = {}) => ({ key: `inbox:${id}`, inbox_id: id, title: `Question ${id}`, art: 'ask', inbox_state: 'open',
  bucket: 'do', gate: 'your-yes', settle: ['done', 'not_doing'], ...over })

function state({ now = [], work = [], later = [], tabs = [], hidden = [], taskRows = [], ui = {}, ...rest } = {}) {
  return {
    now: NOW, model: { sections: [{ id: 'now', rows: now }, { id: 'give', rows: [] }, { id: 'work', rows: work },
      { id: 'track', rows: [] }, { id: 'later', rows: later }], hidden, returns: [], task_rows: taskRows,
    buckets: [], aside: { later: 0, list: 0, done_today: 0 } },
    tabs: { tabs, at_ms: NOW }, driver: { caps: ['tabs', 'launch', 'focus', 'screen', 'key', 'send'] }, triage: { items: {} }, jevOrder: {},
    details: {}, work: { flow: { enabled: true, drop_reasons: [], return_after_s: 20, buckets: { enabled: true } } },
    themes: { enabled: false }, quick: { convs: [] }, flow_ai: {},
    ui: { page: '@flow', busy: {}, flowAt: null, flowChip: 'all', flowJump: null, flowView: 'overview', answered: {}, ...ui }, ...rest,
  }
}

const pointsOf = (s, bucket) => logic.bucketPoints(s, 'en').buckets.find(b => b.id === bucket).points
const where = (s, key) => logic.bucketPoints(s, 'en').all.filter(x => x.row?.key === key).map(x => x.bucket)

// ---------------------------------------------------------------- one matter, one point

test('a task the briefing folded into its inbox line is no second point, from the task list or the files', () => {
  const line = ask('20261009-0900-keep-or-cancel', { folded_tasks: ['power'] })
  const power = task('power', { title: 'Decide on the power contract', closable: true, bucket: 'tasks' })
  const s = state({ now: [line], taskRows: [power] })
  s.model.files = [{ slug: 'power', title: 'Decide on the power contract', status: 'doing', kind: 'tasks' }]
  assert.deepEqual(where(s, line.key), ['do'])
  assert.deepEqual(where(s, power.key), [], 'the task stands as its line')
})

// ---------------------------------------------------------------- a tab that was answered

test('a task tab answered from here works for the Bridge: its task stands in I\'ll do, marked as running', () => {
  const t = task('route', { bucket: 'plan' })
  const tab = { ref: 'surface:5', name: 'route', slug: 'route', state: 'needs-you', live: true, since_ms: NOW - 5 * MIN,
    ask: { text: 'Should I commit this change now? (y/n)', hash: 'h1' } }
  const asked = state({ work: [t], tabs: [tab] })
  assert.deepEqual(where(asked, t.key), ['do'])
  // answered here: the tab is still read as asking until the next poll, the page knows better
  const after = state({ work: [t], tabs: [tab], ui: { answered: { 'surface:5': { hash: 'h1', state: 'needs-you', since: NOW - 5 * MIN } } } })
  const p = logic.bucketPoints(after, 'en').all.filter(x => x.row?.key === t.key)
  assert.deepEqual(p.map(x => x.bucket), ['delegate'])
  assert.equal(p[0].running, true)
  // and one whose tab works by itself does too
  const working = state({ work: [t], tabs: [{ ...tab, state: 'working', ask: null }] })
  assert.deepEqual(where(working, t.key), ['delegate'])
})

// ---------------------------------------------------------------- a tab of a task or stream

test('on a tab that asks about a task or a stream only the tab\'s own answers stand: Later, Done and Obsolete would close the whole task', () => {
  const t = task('fix-eta')
  const tab = { ref: 'surface:12', name: 'fix-eta', slug: 'fix-eta', state: 'waiting', live: true, since_ms: NOW - 5 * MIN,
    ask: { text: 'Release today or tomorrow?', hash: 'h2' } }
  const s = state({ work: [t], tabs: [tab] })
  const p = logic.bucketPoints(s, 'en').all.find(x => x.tab?.ref === 'surface:12')
  assert.ok(p && p.row?.key === t.key)
  const got = logic.bucketAnswers(p, 'do', s, 'en').map(a => a.meaning)
  assert.ok(got.length && got.every(m => m === 'do'), got.join())
  // a tab that asks about an inbox item keeps Later, Done and Obsolete on that item
  const item = ask('20261009-0900-d779')
  const tab2 = { ...tab, ref: 'surface:17', slug: null, item: item.inbox_id }
  const s2 = state({ now: [item], tabs: [tab2] })
  const p2 = logic.bucketPoints(s2, 'en').all.find(x => x.tab?.ref === 'surface:17')
  assert.deepEqual(logic.bucketAnswers(p2, 'do', s2, 'en').map(a => a.meaning).slice(-3), ['later', 'done', 'obsolete'])
})

test('a tab whose item or stream is put off or done for this time leaves Do with it', () => {
  const item = ask('20261009-0900-d779', { inbox_state: 'deferred', hidden_until: '2026-10-12' })
  const tab = { ref: 'surface:17', name: 'Support rota · d779', item: item.inbox_id, state: 'waiting', live: true, since_ms: NOW - MIN,
    ask: { text: 'Swap Taylor and Casey?', yes_no: true, hash: 'h3' } }
  const s = state({ hidden: [item], tabs: [tab] })
  assert.ok(!logic.bucketPoints(s, 'en').all.some(x => x.tab?.ref === 'surface:17'))
  const river = task('rota', { stream: true, work_kind: 'stream', hidden_until: TOMORROW })
  const st = { ref: 'surface:13', name: 'rota', slug: 'rota', state: 'needs-you', live: true, since_ms: NOW - MIN, ask: { text: '1. Yes 2. No' } }
  const s2 = state({ hidden: [river], tabs: [st] })
  assert.ok(!logic.bucketPoints(s2, 'en').all.some(x => x.tab?.ref === 'surface:13'))
})

test('a row of a list whose own tab asks stands as that tab, even where its task has another tab', () => {
  const item = ask('20261009-0900-d779', { task: 'rota', tab: { ref: 'surface:13', state: 'needs-you', live: true } })
  const stream = { ref: 'surface:13', name: 'rota', slug: 'rota', state: 'needs-you', live: true, ask: { text: '1. Yes 2. No' } }
  const own = { ref: 'surface:17', name: 'Support rota · d779', item: item.inbox_id, state: 'waiting', live: true,
    ask: { text: 'Swap Taylor and Casey?', yes_no: true, hash: 'h3' } }
  const s = state({ now: [item], tabs: [stream, own] })
  const p = logic.rowPoint(item, s)
  assert.equal(p.kind, 'tab')
  assert.equal(p.tab.ref, 'surface:17')
  assert.notEqual(logic.bucketAnswers(p, 'do', s, 'en')[0].run.verb, 'do_it')
})

// ---------------------------------------------------------------- Next says what the first button does

test('Next says what the first button does: the way to the tab where nothing can be sent, a preparation where only you can act', () => {
  const tab = { ref: 'surface:20', name: 'close-out', item: '20261009-0900-close', state: 'waiting', live: true,
    ask: { text: '#', draft: true, hash: 'h4' } }
  const item = ask('20261009-0900-close')
  const s = state({ now: [item], tabs: [tab] })
  const p = logic.tabPoint(tab, s)
  assert.equal(logic.bucketAnswers(p, 'do', s, 'en')[0].run.verb, 'tab_jump')
  assert.equal(logic.nextSentence(p, 'do', s, 'en'), en.nextOpenTab)
  assert.equal(logic.nextSentence(p, 'do', s, 'de'), de.nextOpenTab)
  // only you can act on it: Do it prepares it, it never gives a yes
  const mine = ask('20261009-0900-invoice', { gate: 'only-you', title: 'Prepare the invoice export' })
  const s2 = state({ now: [mine] })
  const said = logic.nextSentence({ group: 'row', id: mine.key, kind: 'row', row: mine }, 'do', s2, 'en')
  assert.equal(said, en.nextPrepare('Prepare the invoice export'))
  assert.doesNotMatch(said, /yes/)
})

test('a stream the briefing does not list is no point; one it lists stands in its bucket with its number', () => {
  const quiet = task('rota', { stream: true, work_kind: 'stream', bucket: 'resting', resting: 52 })
  const listed = task('river', { stream: true, work_kind: 'stream', bucket: 'plan', brief_nr: 4 })
  const s = state({ later: [quiet], work: [listed] })
  assert.deepEqual(where(s, quiet.key), [])
  assert.deepEqual(where(s, listed.key), ['plan'])
})

test('By source counts in each bucket what Work through holds: no folded task, no stream the briefing does not list', () => {
  const line = ask('20261009-0900-keep', { folded_tasks: ['power'] })
  const power = task('power', { bucket: 'tasks', closable: true })
  const quiet = task('rota', { stream: true, work_kind: 'stream', bucket: 'resting' })
  const plain = task('plain', { bucket: 'plan' })
  const s = state({ now: [line], work: [plain], later: [quiet], taskRows: [power] })
  const byKey = logic.indexRows(s.model)
  const items = [power, quiet, plain, line].map(r => (r.inbox_id ? { inbox: r.inbox_id, title: r.title } : { task: r.task, title: r.title }))
  const counts = logic.bucketCounts(items, s, byKey, 'en')
  const work = logic.bucketPoints(s, 'en').buckets
  for (const b of work) assert.equal(counts[b.id], b.points.length, b.id)
})

test('Look up names the four buckets and the four answers while the buckets are on', async () => {
  const { views } = await loadCockpit()
  const s = state()
  for (const lang of ['en', 'de']) {
    const t = text.TABLES[lang]
    const got = views.settings.helpOf(s, t)
    const all = JSON.stringify([got.rows, got.act, got.trust])
    assert.doesNotMatch(all, /Hand on|Let AI do it|Advise|Follow up|Weitergeben|AI machen lassen|Beraten|Nachfassen|Abhaken|Waiting for you|AI can take over/, lang)
    assert.match(all, lang === 'de' ? /Mach das.*Später.*Erledigt.*Veraltet/ : /Do it.*Later.*Done.*Obsolete/)
    // with the switch off it is as it was
    const off = { ...s, work: { flow: { enabled: true, buckets: { enabled: false } } } }
    assert.equal(views.settings.helpOf(off, t), t.helpTopics)
  }
})

test('a row of Settings, Setup wears no bucket and no answers, only Seen and its steps', async () => {
  // round 2 (words): "No machine is named to run inbox approvals" wore Plan, the four answers and a fifth, Seen
  const { html, views } = await loadCockpit()
  const { mount, recorder } = await import('./cockpit_render.mjs')
  const it = { index: 0, key: 'setup:runner', title: 'No machine is named to run inbox approvals', actionable: true, when: '',
    row_id: 'runner', actions: [{ id: 'fix', label: 'Name this machine' }] }
  const section = { id: 'gaps', title: 'Gaps', items: [it], view: 'list' }
  const page = { id: 'setup', group: 'settings', title: 'Setup', sections: [section] }
  const s = state()
  s.model.pages = [page]
  s.more = {}
  const el = mount(html`<${views.pages.PageSection} page=${page} section=${section} s=${s} c=${recorder()} />`)
  assert.equal(el.$$('.fb-answer').length, 0, 'no answers')
  assert.equal(el.$$('.fb-chip').length, 0, 'no bucket chip')
})

test('a column card of a tab with a ready answer keeps Later, Done and Obsolete on its item, wherever the model holds it', () => {
  const item = ask('20261009-0900-d779', { inbox_state: 'deferred' })
  const tab = { ref: 'surface:17', name: 'Support rota · d779', item: item.inbox_id, state: 'waiting', live: true,
    ask: { text: 'Swap Taylor and Casey?', hash: 'h3', draft: true, suggestion: 'ja, tauschen' } }
  const s = state({ tabs: [tab] })
  s.model.deferred = [item]
  const p = logic.tabPoint(tab, s)
  const got = logic.bucketAnswers(p, 'do', s, 'de')
  assert.equal(got[0].run.verb, 'tab_accept')
  assert.deepEqual(got.map(a => a.meaning).slice(-3), ['later', 'done', 'obsolete'])
})
