// SPDX-License-Identifier: MIT
// Tests of the page loading new code (erledigtes-raeumt-sich-weg step 1), no npm dependencies.
//
//   node --test scripts/tests/bridge_cockpit_reload.test.mjs
//
// The server names the code of the page in every hello (server.py web_stamp). The page keeps the first one; a
// later hello with another stamp means the server runs newer code than the page: the page says so with a button
// and loads again by itself as soon as nobody types in it, or at once while it is hidden.

import test from 'node:test'
import assert from 'node:assert/strict'
import { cockpitState, loadCockpit, mount, recorder } from './cockpit_render.mjs'

const { html, views, text, logic } = await loadCockpit()
const en = text.TABLES.en
const de = text.TABLES.de

test('R1 a new stamp: the first hello sets it, the same keeps quiet, another one asks for a load', () => {
  assert.deepEqual(logic.codeSeen(null, 'abc'), { code: 'abc', newer: false })
  assert.deepEqual(logic.codeSeen('abc', 'abc'), { code: 'abc', newer: false })
  assert.deepEqual(logic.codeSeen('abc', 'def'), { code: 'abc', newer: true }, 'the page keeps the code it runs')
  assert.deepEqual(logic.codeSeen('abc', ''), { code: 'abc', newer: false }, 'a server that names none changes nothing')
  assert.deepEqual(logic.codeSeen(null, undefined), { code: null, newer: false })
})

test('R2 when the page may load again by itself: hidden at once, else only with nobody typing for half a minute', () => {
  assert.equal(logic.reloadSafe({ hidden: true, editing: true, idleMs: 0 }), true, 'nobody looks at it')
  assert.equal(logic.reloadSafe({ hidden: false, editing: false, idleMs: 30000 }), true)
  assert.equal(logic.reloadSafe({ hidden: false, editing: false, idleMs: 29999 }), false, 'someone just clicked')
  assert.equal(logic.reloadSafe({ hidden: false, editing: true, idleMs: 600000 }), false, 'a field holds text')
  assert.equal(logic.RELOAD_IDLE_MS, 30000)
})

test('R3 the header says newer code runs, with a button that loads the page', () => {
  const s = cockpitState(Date.now(), { ui: { page: 'briefing', newCode: true } })
  const c = recorder()
  const el = mount(html`<${views.header.NewCode} s=${s} c=${c} />`)
  assert.match(el.text(), new RegExp(en.newCode.line))
  el.button(en.newCode.button).click()
  assert.ok(c.calls.some(x => x[0] === 'reloadPage'))
  const none = mount(html`<${views.header.NewCode} s=${cockpitState(Date.now(), { ui: { page: 'briefing' } })} c=${recorder()} />`)
  assert.equal(none.text().trim(), '')
  assert.deepEqual([de.newCode.button, typeof de.newCode.line], ['Neu laden', 'string'])
})
