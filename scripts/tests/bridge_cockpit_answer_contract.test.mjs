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
