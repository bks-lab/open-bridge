// SPDX-License-Identifier: MIT
// The cockpit's four answers send the act lib/answers.py effect() names for the same row (round 4 of the four
// answers: the two tables were written twice and disagreed). The cases are shared with test_answers.py:
// scripts/tests/fixtures/answers/effects.json. No npm dependencies.
//
//   node --test scripts/tests/bridge_cockpit_answer_contract.test.mjs
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { loadCockpit } from './cockpit_render.mjs'

const { logic } = await loadCockpit()
const contract = JSON.parse(readFileSync(new URL('./fixtures/answers/effects.json', import.meta.url), 'utf8'))
const [y, mo, d] = contract.today.split('-').map(Number)
const NOW = new Date(y, mo - 1, d, 12, 0, 0).getTime()

// an act without the page's words (a note's, a text's, a park's reason), as test_answers.py compares it
function comparable(act) {
  const args = Object.fromEntries(Object.entries(act?.args ?? {}).filter(([k]) => k !== 'text' && k !== 'note'))
  if (act?.verb === 'task_park') delete args.reason
  return { verb: act?.verb ?? null, args }
}

function sent(c) {
  const x = { group: 'row', id: c.row.key, kind: 'row', row: c.row }
  const s = { now: NOW, model: {}, ui: {} }
  const answer = logic.bucketAnswers(x, c.row.bucket, s, 'en').find(a => a.meaning === c.answer)
  assert.ok(answer, `${c.name}: no ${c.answer} offered`)
  if (answer.run.kind === 'later') {
    const choice = c.until === logic.LIST_DAY ? 'list' : 'pick'
    return answer.run.then(choice, choice === 'list' ? null : c.until)
  }
  return { verb: answer.run.verb, args: answer.run.args }
}

for (const c of contract.cases) {
  test(`the cockpit sends what the table names: ${c.name}`, () => {
    assert.deepEqual(comparable(sent(c)), comparable(c.act))
  })
}

// ---------------------------------------------------------------- an agent tab that asks has the briefing's number

test('an agent tab that asks without a row of its own says the number the briefing gave it', () => {
  const tab = { ref: 'surface:9', name: 'Contact import', state: 'needs-you', live: true, ask: { text: 'Proceed?', yes_no: true } }
  const s = { now: NOW, model: { tab_nrs: { 'surface:9': 21 } }, ui: {} }
  assert.equal(logic.pointNr({ kind: 'tab', id: 'tab:surface:9', tab, row: null }, s), 21)
  // a tab of a row says the row's number
  assert.equal(logic.pointNr({ kind: 'tab', id: 'tab:surface:9', tab, row: { key: 'task:a', brief_nr: 4 } }, s), 4)
  assert.equal(logic.pointNr({ kind: 'tab', id: 'tab:surface:8', tab: { ...tab, ref: 'surface:8' }, row: null }, s), null)
})

// ---------------------------------------------------------------- no terminal

test('without a terminal Do it is offered only where a yes needs none, and Next says why', () => {
  const s = { now: NOW, model: {}, ui: {}, driver: { caps: ['tabs'] } }
  const t = { key: 'task:a', task: 'a', status: 'doing', bucket: 'plan', title: 'Task a' }
  const point = row => ({ group: 'row', id: row.key, kind: 'row', row })
  const meanings = (row, bucket = row.bucket) => logic.bucketAnswers(point(row), bucket, s, 'en').map(a => a.meaning)
  // round 4: the card said "I start an agent", the click failed with a long red toast
  assert.deepEqual(meanings(t), ['later', 'done', 'obsolete'])
  assert.match(logic.nextSentence(point(t), 'plan', s, 'en'), /No terminal is connected/)
  assert.deepEqual(meanings({ ...t, bucket: 'waiting', who: 'Ada' }), ['later', 'done', 'obsolete'])
  // an inbox item's yes runs without a terminal
  const yes = { key: 'inbox:20261121-0900-check-x', inbox_id: '20261121-0900-check-x', inbox_state: 'open', bucket: 'do', gate: 'your-yes', title: 'Check' }
  assert.equal(meanings(yes)[0], 'do')
  assert.equal(meanings({ ...yes, gate: 'only-you' })[0], 'later')
  // with a terminal, or while the page does not know yet (no caps), Do it stands
  assert.equal(logic.bucketAnswers(point(t), 'plan', { ...s, driver: { caps: ['tabs', 'launch'] } }, 'en')[0].meaning, 'do')
  assert.equal(logic.bucketAnswers(point(t), 'plan', { ...s, driver: { caps: null } }, 'en')[0].meaning, 'do')
})

// ---------------------------------------------------------------- one count of Do

test('with the buckets on the lead line says the count of Do, the badge\'s, in the page\'s words', async () => {
  const { views } = await loadCockpit()
  const { leadOf } = views.stage
  const row = { key: 'inbox:20261121-0900-check-x', inbox_id: '20261121-0900-check-x', inbox_state: 'open', bucket: 'do', gate: 'your-yes', title: 'Check', art: 'ask' }
  const s = { now: NOW, model: { headline: '11 asks for you today · 4 reports · free for the rest of the day', headline_rest: 'free for the rest of the day',
    sections: [{ id: 'now', rows: [row] }, { id: 'give', rows: [] }, { id: 'work', rows: [] }, { id: 'track', rows: [] }, { id: 'later', rows: [] }],
    hidden: [], returns: [], buckets: [] },
    tabs: { tabs: [], at_ms: NOW }, driver: { caps: null }, triage: { items: {} }, jevOrder: {},
    work: { flow: { enabled: true, buckets: { enabled: true } } }, themes: { enabled: false }, ui: { page: 'home', busy: {} } }
  const lead = leadOf(s.model, s)
  assert.doesNotMatch(lead, /11|reports/)
  assert.match(lead, /^1 waits for you · free for the rest of the day$/)
})

// ---------------------------------------------------------------- one kind word

test('an inbox item is named by its art on the card as on every list', async () => {
  const { html, mount, views } = await import('./cockpit_render.mjs').then(async r => ({ ...(await r.loadCockpit()), mount: r.mount }))
  const idea = { key: 'inbox:20261121-0900-x', inbox_id: '20261121-0900-x', art: 'idea', inbox_kind: 'idea', title: 'Backup check' }
  assert.equal(logic.pointKindWord({ kind: 'row', row: idea }, 'en'), 'Idea')
  assert.equal(logic.pointKindWord({ kind: 'row', row: { ...idea, art: 'ask' } }, 'de'), 'Frage')
  const el = mount(html`<${views.day.KindTag} row=${idea} s=${{ model: {} }} />`)
  assert.match(el.text(), /Idea/)
})

test('a waiting point an agent tab works on gets no nudge, so no second agent (round 4)', () => {
  const row = { key: 'task:a', task: 'a', status: 'doing', bucket: 'waiting', who: 'Ada', card: { next: { who: 'Ada' } }, tab: { live: true } }
  const s = { now: NOW, model: {}, ui: {} }
  const got = logic.bucketAnswers({ group: 'row', id: row.key, kind: 'row', row }, 'waiting', s, 'en').map(a => a.meaning)
  assert.deepEqual(got, ['later', 'done', 'obsolete'])
})

test('a point Do it started here stands in I\'ll do as running until the model catches up (round 4)', () => {
  const t = { key: 'task:a', task: 'a', status: 'doing', bucket: 'plan', title: 'Task a' }
  const s = { now: NOW, model: { collected_ms: NOW - 1000, sections: [{ id: 'now', rows: [] }, { id: 'give', rows: [] }, { id: 'work', rows: [t] },
    { id: 'track', rows: [] }, { id: 'later', rows: [] }], hidden: [], returns: [], buckets: [], task_rows: [t] },
  tabs: { tabs: [], at_ms: NOW }, driver: { caps: null }, triage: { items: {} }, jevOrder: {},
  work: { flow: { enabled: true, buckets: { enabled: true } } }, themes: { enabled: false },
  ui: { page: '@flow', busy: {}, flowAnswered: { 'task:a': { ms: NOW - 500, bucket: 'plan', then: 'running' } } } }
  const where = logic.bucketPoints(s, 'en').all.filter(x => x.row?.key === 'task:a').map(x => [x.bucket, !!x.running])
  assert.deepEqual(where, [['delegate', true]])
  // any other answer takes it out of every bucket meanwhile
  const done = { ...s, ui: { ...s.ui, flowAnswered: { 'task:a': { ms: NOW - 500, bucket: 'plan' } } } }
  assert.deepEqual(logic.bucketPoints(done, 'en').all.filter(x => x.row?.key === 'task:a'), [])
})
