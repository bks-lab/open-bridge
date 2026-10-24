// SPDX-License-Identifier: MIT
// Keyboard tests of the cockpit's ARIA widgets (#401), no npm dependencies.
//
//   node scripts/tests/bridge_cockpit_aria.test.mjs
//
// A radio group and a tab list are one tab stop whose arrow keys, Home and End move the choice; a menu
// takes the focus when it opens, its arrow keys move between the items, and Escape gives the focus
// back to the button that opened it. The real components render into the DOM of cockpit_render.mjs,
// which knows no focus: the test adds the little it needs (focus() sets document.activeElement). DOM nodes
// are compared with ===, never assert.equal: a failing diff of a node walks the whole tree.
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import test from 'node:test'
import assert from 'node:assert/strict'
import { cockpitState, loadCockpit, recorder } from './cockpit_render.mjs'

await loadCockpit()   // installs the DOM; the components below come from a copy of their own, with its own Preact
const here = path.dirname(fileURLToPath(import.meta.url))
const WEB = path.resolve(here, '..', 'web')
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'bridge-cockpit-aria-'))
process.on('exit', () => fs.rmSync(tmp, { recursive: true, force: true }))
fs.cpSync(WEB, path.join(tmp, 'web'), { recursive: true })
fs.writeFileSync(path.join(tmp, 'web', 'package.json'), '{ "type": "module" }\n')
const load = rel => import(pathToFileURL(path.join(tmp, 'web', rel)).href)
const vendor = await load('vendor/htm-preact-3.1.1.module.js')
const pages = await load('views/pages.js')
const header = await load('views/header.js')
const { html, render } = vendor

const Element = Object.getPrototypeOf(document.body).constructor
Element.prototype.focus = function focus() { document.activeElement = this }
Element.prototype.querySelector = function querySelector(sel) { return this.$(sel) }
globalThis.window ??= { addEventListener() {}, removeEventListener() {}, innerWidth: 1280 }   // the page bar listens for resize
// and measures its tabs: a DOM without layout says 0, so it neither folds nor moves its marker
for (const k of ['offsetLeft', 'offsetWidth', 'scrollWidth', 'clientWidth']) Object.defineProperty(Element.prototype, k, { get: () => 0, configurable: true })
const settle = () => new Promise(r => setTimeout(r, 30))
const NOW = new Date(2026, 9, 9, 12, 0, 0).getTime()

function mountOwn(vnode) {
  const root = document.createElement('div')
  document.body.appendChild(root)
  render(vnode, root)
  return root
}
/** A key pressed on `el`: bubbles like a browser keydown */
const press = (el, key) => el.dispatch('keydown', { key })
/** A key the document's capturing listeners see first (the popover's Escape) */
function pressDoc(key) {
  const ev = { type: 'keydown', key, target: document.activeElement, defaultPrevented: false, preventDefault() { ev.defaultPrevented = true }, stopPropagation() {} }
  for (const fn of document.listeners.get('keydown:true') ?? []) fn(ev)
  return ev
}

test('radio group: the chosen chip is the one tab stop, arrows move the choice, End and Home jump', async () => {
  const c = recorder()
  const kinds = [{ label: 'inbox', n: 2 }, { label: 'task', n: 3 }, { label: 'stream', n: 1 }]
  const el = mountOwn(html`<${pages.KindBar} kinds=${kinds} active=${kinds[0]} c=${c} />`)
  await settle()
  const radios = el.$$('[role="radio"]')
  assert.deepEqual(radios.map(r => r.getAttribute('tabindex')), ['-1', '0', '-1', '-1'])
  radios[1].focus()
  const ev = press(radios[1], 'ArrowRight')
  assert.equal(ev.defaultPrevented, true)
  assert.deepEqual(c.calls.at(-1), ['setWorkKind', 'task'])
  assert.ok(document.activeElement === radios[2])
  press(radios[2], 'End')
  assert.deepEqual(c.calls.at(-1), ['setWorkKind', 'stream'])
  press(radios[3], 'ArrowRight')
  assert.deepEqual(c.calls.at(-1), ['setWorkKind', null], 'the last steps around to the first')
  const n = c.calls.length
  press(radios[0], 'a')
  assert.equal(c.calls.length, n, 'another key chooses nothing')
})

test('tab list: arrows switch the page, every tab but the active one is out of the tab order', async () => {
  const c = recorder()
  const s = cockpitState(NOW)
  const el = mountOwn(html`<${header.PageBar} s=${s} c=${c} />`)
  await settle()
  const tabs = el.$$('[role="tab"]')
  assert.ok(tabs.length > 2)
  const on = tabs.findIndex(x => x.getAttribute('aria-selected') === 'true')
  assert.ok(on >= 0)
  assert.deepEqual(tabs.map(x => x.getAttribute('tabindex')), tabs.map((_, i) => (i === on ? '0' : '-1')))
  tabs[on].focus()
  press(tabs[on], 'ArrowRight')
  assert.equal(c.calls.at(-1)[0], 'setPage')
  assert.ok(document.activeElement === tabs[(on + 1) % tabs.length])
})

test('menu: opening focuses the first item, arrows move between items, Escape closes and gives the focus back', async () => {
  const c = recorder()
  const it = { index: 0, actions: [{ id: 'follow', label: 'Followed up' }, { id: 'reject', label: 'Turned down' }] }
  const s = cockpitState(NOW)
  const el = mountOwn(html`<${pages.RowSteps} it=${it} page="p" section="x" s=${s} c=${c} />`)
  const trigger = el.$('button')
  trigger.focus()
  trigger.click()
  await settle()
  const items = el.$$('[role="menuitem"]')
  assert.equal(items.length, 2)
  assert.ok(document.activeElement === items[0], 'the menu takes the focus')
  pressDoc('ArrowDown')
  assert.ok(document.activeElement === items[1])
  pressDoc('ArrowDown')
  assert.ok(document.activeElement === items[0], 'around the end')
  pressDoc('End')
  assert.ok(document.activeElement === items[1])
  pressDoc('Escape')
  await settle()
  assert.ok(el.$('[role="menu"]') === null, 'Escape closes the menu')
  assert.ok(document.activeElement === el.$('button'), 'and the focus is back on the button that opened it')
})

test('menu: a pick closes it and the focus returns to its button instead of falling to the page', async () => {
  const c = recorder()
  const it = { index: 0, actions: [{ id: 'follow', label: 'Followed up' }] }
  const el = mountOwn(html`<${pages.RowSteps} it=${it} page="p" section="x" s=${cockpitState(NOW)} c=${c} />`)
  el.$('button').click()
  await settle()
  el.$('[role="menuitem"]').click()
  document.activeElement = document.body   // the item is gone, a browser drops the focus to the body
  await settle()
  assert.deepEqual(c.calls.at(-1), ['act', 'row_action', { page: 'p', section: 'x', index: 0, action: 'follow' }])
  assert.ok(document.activeElement === el.$('button'))
})

test('reply buttons and the text field have accessible names', async () => {
  const reply = await load('views/reply.js')
  const s = cockpitState(NOW)
  const named = b => (b.textContent.trim() || b.getAttribute('aria-label') || '').length > 0
  for (const ref of ['surface:7', 'surface:12', 'surface:10']) {
    const tab = s.tabs.tabs.find(t => t.ref === ref)
    for (const compact of [false, true]) {
      const el = mountOwn(html`<${reply.TabReply} tab=${tab} s=${s} c=${recorder()} compact=${compact} />`)
      await settle()
      const buttons = el.$$('button')
      assert.ok(buttons.length > 0, ref)
      assert.ok(buttons.every(named), `${ref}: a button without a name`)
      for (const box of el.$$('textarea')) {
        const id = box.getAttribute('id')
        assert.ok(id && el.$$('label').some(l => l.getAttribute('for') === id && l.textContent.trim()), `${ref}: the field has no label`)
      }
      // the folded field opens on a button that says it opens something
      const opener = el.$$('button').find(b => b.getAttribute('aria-expanded') !== null)
      if (compact && ref !== 'surface:7') {
        assert.ok(opener, `${ref}: no opener`)
        assert.equal(opener.getAttribute('aria-expanded'), 'false')
        opener.click()
        await settle()
        assert.equal(el.$$('textarea').length, 1)
        assert.ok(document.activeElement === el.$('textarea'), 'the opened field takes the focus')
      }
      render(null, el)
    }
  }
})

test('organize checkboxes have labels', async () => {
  const organize = await load('views/organize.js')
  const items = [
    { id: 'ws_color:workspace:2', kind: 'ws_color', ref: 'workspace:2', from: null, to: 'Teal', why: 'x', cap: 'set_color' },
    { id: 'tab_title:surface:9', kind: 'tab_title', ref: 'surface:9', from: 'release', to: 'Release notes', why: 'y', cap: 'rename' }]
  const s = cockpitState(NOW, { ui: { organize: { busy: false, proposal: { id: 'o0123456789', at_ms: NOW, scope: 2, items }, ticks: {} } } })
  const el = mountOwn(html`<${organize.OrganizeView} s=${s} c=${recorder()} />`)
  await settle()
  const boxes = el.$$('input[type="checkbox"]')
  assert.ok(boxes.length >= 3, 'one per item and one per workspace')
  for (const box of boxes) {
    const label = box.getAttribute('aria-label') || (box.parentNode?.localName === 'label' ? box.parentNode.textContent.trim() : '')
    assert.ok(label, 'a checkbox without a name')
  }
  const dialog = el.$('[role="dialog"]')
  assert.ok(dialog && dialog.getAttribute('aria-modal') === 'true' && dialog.getAttribute('aria-labelledby'))
  assert.ok(el.$$('button').every(b => (b.textContent.trim() || b.getAttribute('aria-label') || '').length > 0))
  render(null, el)
})

test('no aria-label on an element without a role: a screen reader skips it on a span, a div or a pre', () => {
  // review C27: the name goes in a .sr-only span beside what is seen, or the element gets the role it plays
  const files = [...fs.readdirSync(WEB).filter(f => f.endsWith('.js')).map(f => path.join(WEB, f)),
    ...fs.readdirSync(path.join(WEB, 'views')).filter(f => f.endsWith('.js')).map(f => path.join(WEB, 'views', f))]
  const bad = []
  for (const file of files) {
    const src = fs.readFileSync(file, 'utf8')
    for (const m of src.matchAll(/<(span|pre|div|i|p|li|small|b)\b[^>]*\baria-label=[^>]*>/g)) {
      if (!/\brole=/.test(m[0])) bad.push(`${path.basename(file)}: ${m[0].slice(0, 80)}`)
    }
  }
  assert.deepEqual(bad, [])
})
