// SPDX-License-Identifier: MIT
// The fields of the Chat (logic.js): what stands where, as pure functions on the plain value the page keeps.
import test from 'node:test'
import assert from 'node:assert/strict'
import { fieldsBeside, fieldsClose, fieldsDrop, fieldsHold, fieldsLayout, fieldsOf, fieldsPick, fieldsSwap, fieldsTopic, termStatus } from '../web/logic.js'

const topic = { topic: true, follow: true, tab: null }

test('fieldsOf: anything else than a known shape is one empty field', () => {
  assert.deepEqual(fieldsOf(null), { layout: '1', panes: [null], active: 0, split: 58 })
  assert.deepEqual(fieldsOf({ layout: 'x', panes: 'y', active: 9, split: 1 }), { layout: '1', panes: [null], active: 0, split: 25 })
})

test('fieldsOf: the panes fit the layout, and a room no field holds takes the active one', () => {
  assert.deepEqual(fieldsOf({ layout: '2h', panes: ['a', 'b', 'c'] }).panes, ['a', 'b'])
  assert.deepEqual(fieldsOf({ layout: '3', panes: ['a'] }).panes, ['a', null, null])
  assert.deepEqual(fieldsOf({ layout: '2h', panes: ['a', 'b'], active: 1 }, 'c').panes, ['a', 'c'])
  const kept = fieldsOf({ layout: '2h', panes: ['a', topic], active: 1 }, 'a')
  assert.equal(kept.active, 1, 'the field beside stays active while its chat stands in a field')
})

test('fieldsPick: a tab goes to the active field, never over Zum Thema, and a tab in a field is only found', () => {
  const two = fieldsOf({ layout: '2h', panes: ['a', 'b'] })
  assert.deepEqual(fieldsPick(two, 'c').panes, ['c', 'b'])
  assert.equal(fieldsPick(two, 'b').active, 1)
  const side = fieldsOf({ layout: '2h', panes: ['a', topic], active: 1 })
  const r = fieldsPick(side, 'c')
  assert.deepEqual(r.panes, ['c', topic])
  assert.equal(r.active, 0)
})

test('fieldsBeside: fills a free field, else grows the layout up to four', () => {
  const r = fieldsBeside(fieldsOf({ panes: ['a'] }), 'b')
  assert.equal(r.layout, '2h')
  assert.deepEqual(r.panes, ['a', 'b'])
  assert.equal(r.active, 1)
  assert.deepEqual(fieldsBeside(fieldsOf({ layout: '4', panes: ['a', null, 'c', 'd'] }), 'b').panes, ['a', 'b', 'c', 'd'])
  assert.equal(fieldsBeside(r, 'a'), r, 'one that stands in a field stays')
})

test('fieldsLayout: keeps what is open, fills from the list, and leaves the rest free', () => {
  assert.deepEqual(fieldsLayout(fieldsOf({ panes: ['a'] }), '3', ['a', 'x']).panes, ['a', 'x', null])
  const less = fieldsLayout(fieldsOf({ layout: '4', panes: ['a', 'b', 'c', 'd'], active: 3 }), '2v')
  assert.deepEqual(less.panes, ['a', 'b'])
  assert.equal(less.active, 1)
})

test('fieldsSwap: the two change places and the active field goes along', () => {
  const r = fieldsSwap(fieldsOf({ layout: '2h', panes: ['a', topic] }), 0, 1)
  assert.deepEqual(r.panes, [topic, 'a'])
  assert.equal(r.active, 1)
})

test('fieldsClose: the layout shrinks with the fields, the last one stays', () => {
  const r = fieldsClose(fieldsOf({ layout: '4', panes: ['a', 'b', null, 'd'] }), 1)
  assert.equal(r.layout, '2h')
  assert.deepEqual(r.panes, ['a', 'd'])
  assert.deepEqual(fieldsClose(fieldsOf({ layout: '2h', panes: ['a', 'b'] }), 1).panes, ['a'])
  assert.equal(fieldsClose(fieldsOf({ panes: ['a'] }), 0).layout, '1')
})

test('fieldsTopic: opens once beside the chat, in a free field when there is one', () => {
  const r = fieldsTopic(fieldsOf({ panes: ['a'] }))
  assert.equal(r.layout, '2h')
  assert.deepEqual(r.panes, ['a', topic])
  assert.equal(r.active, 0)
  assert.equal(fieldsTopic(r), r)
  assert.deepEqual(fieldsTopic(fieldsOf({ layout: '3', panes: ['a', null, 'c'] })).panes, ['a', topic, 'c'])
  assert.deepEqual(fieldsTopic(fieldsOf({ layout: '4', panes: ['a', 'b', 'c', 'd'] })).panes.at(-1), topic)
})

test('fieldsHold: holds the topic at a tab and lets it follow again', () => {
  const held = fieldsHold(fieldsOf({ layout: '2h', panes: ['a', topic] }), 1, 'a')
  assert.deepEqual(held.panes[1], { topic: true, follow: false, tab: 'a' })
  assert.deepEqual(fieldsHold(held, 1, 'b').panes[1], topic)
})

test('fieldsDrop: a tab dropped on a field opens there, one in a field swaps', () => {
  const f = fieldsOf({ layout: '2h', panes: ['a', 'b'] })
  assert.deepEqual(fieldsDrop(f, 1, 'c').panes, ['a', 'c'])
  assert.deepEqual(fieldsDrop(f, 1, 'a').panes, ['b', 'a'])
})

test('termStatus: reads what a status line names and nothing else', () => {
  assert.deepEqual(termStatus('x\n  ➜ repo git:(main) [Opus 5.5 · medium] 16%/1M · $1.58'), { model: 'Opus 5.5 · medium', context: 16, cost: '$1.58' })
  assert.equal(termStatus('nothing here'), null)
  assert.equal(termStatus(null), null)
})
