// SPDX-License-Identifier: MIT
// Render tests of a board's draft card on the GitHub page (#407): a project item without an issue
// behind it has no number and no link, and the page says so instead of drawing it like an issue.
//
//   node --test scripts/tests/bridge_cockpit_draft_cards.test.mjs
import test from 'node:test'
import assert from 'node:assert/strict'
import { cockpitState, loadCockpit, mount, recorder } from './cockpit_render.mjs'

const { html, views, text } = await loadCockpit()
const { GitHubList } = views.github
const en = text.TABLES.en
const NOW = new Date(2026, 9, 9, 12, 0, 0).getTime()

const draft = {
  index: 0, title: 'Private finding', group: 'Tool board', row_id: 'draft:tool:PVTI_d1', flags: ['mine'],
  actions: [{ id: 'analyze', label: 'Analyse' }, { id: 'adopt', label: 'Make it a task' }],
  gh: { title: 'Private finding', repo: null, number: null, type: 'draft', state: 'ready', status: 'Todo', priority: null,
    labels: [], people: ['demo-user'], prs: [], task: null, stream: false, untasked: false, changed: null, quiet: null, note: null },
}

test('draft card: marked as a draft, without a number or a link, offering only its steps', () => {
  const s = cockpitState(NOW)
  const c = recorder()
  const el = mount(html`<${GitHubList} items=${[draft]} page="work" section=${{ id: 'work', boards: [] }} s=${s} c=${c} byKey=${new Map()} />`)
  const row = el.$('.ghl-row')
  assert.ok(row, 'the draft is drawn as a row')
  assert.equal(row.$('.ghl-chip-draft')?.text(), en.gh.draftCard)
  assert.equal(row.$('.ghl-chip-draft').getAttribute('title'), en.gh.draftCardTitle)
  assert.doesNotMatch(row.text(), /#\d/)                       // no number to show
  assert.equal(row.$$('a').length, 0)                           // no link to open
  assert.ok(row.button('Analyse'), 'Analyse leads')
  row.button('Analyse').click()
  assert.deepEqual(c.calls.at(-1), ['act', 'row_action', { page: 'work', section: 'work', index: 0, action: 'analyze' }])
})
