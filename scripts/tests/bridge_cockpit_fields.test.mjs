// SPDX-License-Identifier: MIT
// The fields of the Chat (logic.js): what stands where, as pure functions on the plain value the page keeps.
import test from 'node:test'
import assert from 'node:assert/strict'
import { fieldsBeside, fieldsClose, fieldsDrop, fieldsHold, fieldsLayout, fieldsOf, fieldsPick, fieldsSwap, fieldsTopic, fieldsWall, pastCut, pastMerge, pastShown, pastText, screenLines, termStatus } from '../web/logic.js'

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

test('fieldsWall: the tabs of a workspace side by side, at most four', () => {
  const r = fieldsWall(fieldsOf({ panes: ['z'] }), ['a', 'b', 'c', 'd', 'e'])
  assert.equal(r.layout, '4')
  assert.deepEqual(r.panes, ['a', 'b', 'c', 'd'])
  assert.equal(fieldsWall(fieldsOf({ layout: '3', panes: ['a', 'b'] }), ['a', 'b']).layout, '2h')
})

// what went before the screen of an agent tab
const turn = (i, role, text) => ({ i, role, text, at_ms: 0 })

test('pastCut: the turns that stand on the screen are not told twice, as drawn: wrapped and without markdown', () => {
  const turns = [turn(0, 'user', 'What does the broker do at night?'), turn(1, 'agent', 'It sleeps until a job comes in.'),
    turn(2, 'user', 'Please fix the **header height** on the page'), turn(3, 'tool', 'Bash: git status'), turn(4, 'agent', 'The header is back at its normal height.\n\nNothing else changed.')]
  const screen = '❯ Please fix the header height\n  on the page\n\n⏺ Bash(git status)\n  ⎿  clean\n\n⏺ The header is back at its\n  normal height.\n\n  Nothing else changed.\n\n❯'
  assert.equal(pastCut(turns, screen), 2)
})

test('pastCut: a turn the screen no longer holds stays, an empty or foreign screen takes none', () => {
  const turns = [turn(0, 'user', 'What does the broker do at night?'), turn(1, 'agent', 'It sleeps until a job comes in.')]
  assert.equal(pastCut(turns, ''), 2)
  assert.equal(pastCut(turns, '? for shortcuts'), 2)
  assert.equal(pastCut([], 'anything'), 0)
})

test('pastCut: folded tools are not looked for, and a look ends after two turns off the screen', () => {
  const folded = [turn(0, 'agent', 'Reading the three files now.'), turn(1, 'tool', 'Read: a.md'), turn(2, 'tool', 'Read: b.md'), turn(3, 'agent', 'All three say the same thing.')]
  assert.equal(pastCut(folded, '⏺ Reading the three files now.\n  Read 2 files (ctrl+o to expand)\n⏺ All three say the same thing.'), 0)
  const again = [turn(0, 'agent', 'I will look at the log first.'), turn(1, 'user', 'Something else entirely today'), turn(2, 'agent', 'An answer long gone by now'),
    turn(3, 'agent', 'I will look at the log first.')]
  assert.equal(pastCut(again, '⏺ I will look at the log first.'), 3, 'the same words further back are another turn')
})

test('pastShown: a long answer that runs on to the screen ends where the screen starts', () => {
  const long = 'First paragraph of a long answer.\n\nSecond paragraph goes on\nand on for a while.\n\nThird paragraph ends it.'
  const screen = '  Second paragraph goes on and on\n  for a while.\n\n  Third paragraph ends it.\n\n❯'
  assert.deepEqual(pastShown([turn(0, 'user', 'Tell me all of it please'), turn(1, 'agent', long)], screen),
    [turn(0, 'user', 'Tell me all of it please'), turn(1, 'agent', 'First paragraph of a long answer.')])
})

test('pastShown: looks past what the terminal adds on top, and past the tools the answer ended with', () => {
  const long = 'A first part that scrolled away by now.\n\nThe end of the same long answer stands below.'
  const turns = [turn(0, 'agent', long), turn(1, 'tool', 'Read: a.md'), turn(2, 'agent', 'And a new turn on the screen.')]
  const screen = '✻ Worked for 1m 28s\n  The end of the same long answer stands below.\n⏺ Read(a.md)\n⏺ And a new turn on the screen.'
  assert.deepEqual(pastShown(turns, screen), [turn(0, 'agent', 'A first part that scrolled away by now.')])
})

test('pastShown: a screen that has no line of the turn leaves it whole, and a turn that starts on the screen goes', () => {
  const turns = [turn(0, 'user', 'Tell me all of it please'), turn(1, 'agent', 'An answer the screen does not hold.'), turn(2, 'tool', 'Read: a.md')]
  assert.deepEqual(pastShown(turns, '❯ something else entirely'), turns)
  assert.deepEqual(pastShown([turn(0, 'agent', 'Short')], 'Short'), [turn(0, 'agent', 'Short')], 'too short to find')
  assert.deepEqual(pastShown([], 'anything at all here'), [])
})

test('pastMerge: a new read replaces the end, older pages go before it, another session starts anew', () => {
  const first = pastMerge(null, { source: 'session', sid: 'a', turns: [turn(5, 'user', 'x'), turn(6, 'agent', 'y')], truncated: true })
  assert.deepEqual(first, { sid: 'a', turns: [turn(5, 'user', 'x'), turn(6, 'agent', 'y')], more: true })
  const older = pastMerge(first, { source: 'session', sid: 'a', turns: [turn(3, 'user', 'v'), turn(4, 'agent', 'w')], truncated: true }, true)
  assert.deepEqual(older.turns.map(x => x.i), [3, 4, 5, 6])
  assert.equal(older.more, true)
  const newer = pastMerge(older, { source: 'session', sid: 'a', turns: [turn(6, 'agent', 'y'), turn(7, 'tool', 'z')], truncated: true })
  assert.deepEqual(newer.turns.map(x => x.i), [3, 4, 5, 6, 7], 'what paged back stays')
  assert.equal(pastMerge(older, { source: 'session', sid: 'a', turns: [], truncated: true }, true).more, false, 'an empty page ends it')
  assert.deepEqual(pastMerge(newer, { source: 'session', sid: 'b', turns: [turn(0, 'user', 'new')], truncated: false }), { sid: 'b', turns: [turn(0, 'user', 'new')], more: false })
})

test('pastMerge: only a session file is a past, a page that comes late to another session changes nothing', () => {
  const held = { sid: 'a', turns: [turn(5, 'user', 'x')], more: true }
  assert.equal(pastMerge(held, { source: 'terminal', turns: [turn(0, 'terminal', '$ ls')], truncated: false }), null)
  assert.equal(pastMerge(held, { source: 'session', sid: 'b', turns: [turn(1, 'user', 'y')], truncated: false }, true), held)
  assert.equal(pastMerge(held, { source: 'terminal', turns: [], truncated: false }, true), held)
})

test('pastText: reads as the terminal does: the marks screenLines knows, a turn per block, no bold markers', () => {
  const text = pastText([turn(0, 'user', 'first line\nsecond line'), turn(1, 'agent', 'It is **done** now\n\nand checked'), turn(2, 'tool', 'Bash: git status')])
  assert.equal(text, '❯ first line\n  second line\n\n⏺ It is done now\n\n  and checked\n\n⎿  Bash: git status')
  assert.deepEqual(screenLines(text).filter(l => l.kind !== 'gap').map(l => l.kind), ['user', 'user', 'claude', 'claude', 'tool'])
  assert.equal(pastText([]), '')
})
