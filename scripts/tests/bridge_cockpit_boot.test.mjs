// SPDX-License-Identifier: MIT
// Tests of the page's boot guard (scripts/web/boot.js), no npm dependencies.
//
//   node --test scripts/tests/bridge_cockpit_boot.test.mjs
//
// Right after a restart of the server every open page loads anew while the server is still starting. When app.js or
// a style sheet of that load fails (a connection reset), the page used to stay blank for good. boot.js, a classic
// script that runs before anything else, loads the page again by itself: at most three times in a row, a little
// later each time, and never once app.js runs (it calls window.cockpitBootDone, which also clears the count).
import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import assert from 'node:assert/strict'

const WEB = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'web')
const SOURCE = fs.readFileSync(path.join(WEB, 'boot.js'), 'utf8')

/** A page with boot.js run in it: its error listener, its timers and its reloads, sessionStorage as a Map (or one
 *  that throws, as a blocked one does) */
function page({ stored = null, blocked = false } = {}) {
  const store = new Map(stored == null ? [] : [['bridge-cockpit.boot-retries', String(stored)]])
  const listeners = []
  const timers = []
  const reloads = []
  const sessionStorage = blocked
    ? { getItem() { throw new Error('blocked') }, setItem() { throw new Error('blocked') }, removeItem() { throw new Error('blocked') } }
    : { getItem: k => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: k => store.delete(k) }
  const window = { sessionStorage, location: { reload: () => reloads.push(1) }, setTimeout: (fn, ms) => timers.push({ fn, ms }) }
  const document = { addEventListener: (type, fn, capture) => listeners.push({ type, fn, capture }) }
  vm.runInNewContext(SOURCE, { window, document })
  const fail = target => listeners.filter(l => l.type === 'error').forEach(l => l.fn({ target }))
  return { window, store, listeners, timers, reloads, fail }
}

const script = { tagName: 'SCRIPT' }
const sheet = { tagName: 'LINK', rel: 'stylesheet' }

test('B1 a failed app.js or style sheet loads the page again a second later, counting the try', () => {
  const p = page()
  assert.ok(p.listeners.some(l => l.type === 'error' && l.capture === true), 'listens in the capture phase: resource errors do not bubble')
  p.fail(script)
  assert.equal(p.timers.length, 1)
  assert.equal(p.timers[0].ms, 1000)
  assert.equal(p.store.get('bridge-cockpit.boot-retries'), '1')
  p.timers[0].fn()
  assert.equal(p.reloads.length, 1)
  const q = page()
  q.fail(sheet)
  assert.equal(q.timers.length, 1)
})

test('B2 one reload per load however many files fail, later each time, and never a fourth in a row', () => {
  const p = page()
  p.fail(script)
  p.fail(sheet)
  p.fail(script)
  assert.equal(p.timers.length, 1, 'one plan for the whole load')
  const second = page({ stored: 1 })
  second.fail(script)
  assert.equal(second.timers[0].ms, 2000)
  assert.equal(second.store.get('bridge-cockpit.boot-retries'), '2')
  const third = page({ stored: 3 })
  third.fail(script)
  assert.equal(third.timers.length, 0, 'three tries in a row are enough: a server that is down stays a page that says nothing')
})

test('B3 an image or anything else that fails is no reason, nor a storage the page may not use', () => {
  const p = page()
  p.fail({ tagName: 'IMG' })
  p.fail({ tagName: 'LINK', rel: 'icon' })
  p.fail(null)
  assert.equal(p.timers.length, 0)
  const blocked = page({ blocked: true })
  blocked.fail(script)
  assert.equal(blocked.timers.length, 0, 'without a count a reload could loop')
})

test('B4 once app.js runs, a later failure reloads nothing and the count is cleared', () => {
  const p = page({ stored: 2 })
  p.window.cockpitBootDone()
  assert.equal(p.store.has('bridge-cockpit.boot-retries'), false)
  p.fail(script)
  assert.equal(p.timers.length, 0)
  page({ blocked: true }).window.cockpitBootDone()   // a blocked storage throws nothing
})

test('B5 index.html runs boot.js first, before the style sheets and app.js, and app.js reports its start', () => {
  const index = fs.readFileSync(path.join(WEB, 'index.html'), 'utf8')
  const at = name => index.indexOf(name)
  assert.ok(at('<script src="boot.js"></script>') > 0)
  assert.ok(at('boot.js') < at('theme.js') && at('boot.js') < at('.css') && at('boot.js') < at('app.js'))
  const app = fs.readFileSync(path.join(WEB, 'app.js'), 'utf8')
  assert.match(app, /window\.cockpitBootDone\?\.\(\)/)
})

test('B6 a style sheet that keeps failing while app.js runs never makes the page loop', () => {
  const p = page()
  p.fail(sheet)                      // the sheet fails first, a reload is planned
  p.window.cockpitBootDone()         // app.js still runs afterwards
  assert.equal(p.store.get('bridge-cockpit.boot-retries'), '1', 'the count of a load that failed stays')
  const next = page({ stored: 3 })
  next.fail(sheet)
  assert.equal(next.timers.length, 0)
})
