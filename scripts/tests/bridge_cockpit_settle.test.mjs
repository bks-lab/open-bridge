// SPDX-License-Identifier: MIT
// Render tests of the close door in an item's detail, no npm dependencies.
//
//   node --test scripts/tests/bridge_cockpit_settle.test.mjs
//
// A task's detail offers "Close ▾" once, in its actions bar. The check's recommendation below it carries no door
// of its own: a close the check recommends still arrives with its reason as the prefilled sentence.
import test from 'node:test'
import assert from 'node:assert/strict'
import { cockpitState, loadCockpit, mount, recorder } from './cockpit_render.mjs'

const { html, views, text, logic } = await loadCockpit()
const en = text.TABLES.en
const { DetailColumn } = views.detail
const { SettleMenu } = views.day

// a fixed local "now": Friday, 9 October 2026, noon (the same moment the other render suites use)
const NOW = new Date(2026, 9, 9, 12, 0, 0).getTime()

// the open panel places itself under its door and moves the focus into itself; this small DOM has neither
const proto = Object.getPrototypeOf(document.body)
proto.focus ??= function focus() { document.activeElement = this }
proto.getBoundingClientRect ??= () => ({ left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0 })
globalThis.window ??= { innerWidth: 1280, innerHeight: 800, addEventListener() {}, removeEventListener() {} }

/** Mounts a view that moves the focus into itself after it mounts, which this small DOM has no selector engine for */
async function settled(vnode) {
  const Element = Object.getPrototypeOf(document.body).constructor
  const had = Object.getOwnPropertyDescriptor(Element.prototype, 'querySelector')
  Element.prototype.querySelector = () => null
  try {
    const d = mount(vnode)
    await new Promise(r => setTimeout(r, 50))
    return d
  } finally {
    if (had) Object.defineProperty(Element.prototype, 'querySelector', had)
    else delete Element.prototype.querySelector
  }
}

const detail = key => {
  const s = cockpitState(NOW, { ui: { selectedKey: key, queue: null } })
  return { s, d: settled(html`<${DetailColumn} s=${s} c=${recorder()} byKey=${logic.indexRows(s.model)} />`) }
}
/** The close doors of a view (the start door shares the class `settle`) */
const doors = el => el.$$('.settle').filter(x => !x.getAttribute('class').split(' ').includes('start'))
/** The item's own actions: the task's inbox entries further down carry their own doors */
const actions = d => d.$('.block-actions')
/** What a textarea shows: Preact writes `value` as an attribute in this small DOM, a test may set the property */
const shown = el => el.value ?? el.getAttribute('value')
const tick = () => new Promise(r => setTimeout(r, 10))

test('settle: a task detail with a check recommendation offers the close door once', async () => {
  const d = await detail('task:demo-task').d
  assert.ok(d.$('.review-block'), 'the recommendation is shown')
  assert.equal(doors(actions(d)).length, 1, 'one close door in the task detail')
  assert.equal(d.$('.review-block').$$('.settle').length, 0, 'the recommendation carries no door of its own')
})

test('settle: the close door of a task the check would close opens with its reason as the sentence', async () => {
  const { s, d: pending } = detail('task:demo-task')
  const d = await pending
  const row = logic.indexRows(s.model).get('task:demo-task')
  assert.equal(row.review.verdict, 'close')
  const door = doors(actions(d))[0]
  door.$('button').click()
  await tick()
  assert.equal(shown(door.$('textarea')), row.review.reason.slice(0, 400))
})

/** Opens the close door of a view and returns the sentence its panel shows */
const sentence = async vnode => {
  const el = await settled(vnode)
  doors(el)[0].$('button').click()
  await tick()
  return shown(el.$('textarea'))
}
/** A row of the demo with the check's recommendation replaced */
const reviewed = (s, review) => {
  const row = logic.indexRows(s.model).get('task:quiet-docs')
  return { ...row, review: { ...row.review, ...review } }
}

test('settle: a passed seed wins, a stale recommendation leaves the sentence empty', async () => {
  const s = cockpitState(NOW)
  const row = logic.indexRows(s.model).get('task:quiet-docs')
  assert.equal(row.review.verdict, 'stale')
  assert.equal(await sentence(html`<${SettleMenu} rows=${[row]} s=${s} c=${recorder()} />`), '')
  assert.equal(await sentence(html`<${SettleMenu} rows=${[row]} s=${s} c=${recorder()} seed="mine" />`), 'mine')
  assert.equal(await sentence(html`<${SettleMenu} rows=${[reviewed(s, { verdict: 'close' })]} s=${s} c=${recorder()} seed="" />`), '',
    'an empty seed keeps the sentence empty')
})

test('settle: a recommendation to continue leaves the sentence empty', async () => {
  const s = cockpitState(NOW)
  const row = reviewed(s, { verdict: 'continue', resolved: false, reason: 'Still moving.' })
  assert.equal(await sentence(html`<${SettleMenu} rows=${[row]} s=${s} c=${recorder()} />`), '')
})

test('settle: a check that found the work resolved brings its reason, whatever the verdict', async () => {
  const s = cockpitState(NOW)
  const row = reviewed(s, { verdict: 'continue', resolved: true, reason: 'The fix has landed.' })
  assert.equal(await sentence(html`<${SettleMenu} rows=${[row]} s=${s} c=${recorder()} />`), 'The fix has landed.')
})

test('settle: a list row the check would close opens its close door with the reason as well', async () => {
  const s = cockpitState(NOW)
  const row = reviewed(s, { verdict: 'close', reason: 'Nothing left to do.' })
  assert.equal(await sentence(html`<${views.day.RowBar} row=${row} s=${s} c=${recorder()} />`), 'Nothing left to do.')
})

test('settle: a selection of several rows brings no reason', async () => {
  const s = cockpitState(NOW)
  const a = reviewed(s, { verdict: 'close', reason: 'Nothing left to do.' })
  const b = { ...a, key: 'task:other', task: 'other' }
  assert.equal(await sentence(html`<${SettleMenu} rows=${[a, b]} s=${s} c=${recorder()} />`), '')
})

test('settle: an inbox item detail still offers the close door once', async () => {
  const d = await detail('inbox:20261009-0910-tidy-labels-c3d4').d
  assert.equal(doors(actions(d)).length, 1, 'one close door in the inbox detail')
  assert.ok(doors(actions(d))[0].text().includes(en.settle))
})
