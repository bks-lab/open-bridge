// SPDX-License-Identifier: MIT
// Render tests of a GitHub row opened beside its list: a click on a row of the GitHub list opens what GitHub says
// about it in a column beside the list, never in Work through and never over the list, so the next row is one click
// away on the left; the column walks the list in the order it is shown (back, next, n and p).
//
//   node --test scripts/tests/bridge_cockpit_gh_beside.test.mjs
import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { cockpitState, loadCockpit, mount, recorder, settle } from './cockpit_render.mjs'

const { html, views, text, logic, components } = await loadCockpit()
const { GitHubList } = views.github
const { InfoDrawer } = views.overlays
const en = text.TABLES.en
const NOW = new Date(2026, 9, 9, 12, 0, 0).getTime()
const WEB = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'web')
const APP = fs.readFileSync(path.join(WEB, 'app.js'), 'utf8')
const method = head => {
  const at = APP.indexOf(`\n  ${head}`)
  assert.ok(at >= 0, `app.js has ${head}`)
  const end = APP.indexOf('\n  },', at)
  return APP.slice(at, end > 0 ? end : at + 2000)
}

/** The GitHub section of the invented data (mock.js): page trackers, section mine */
function ghPage(s) {
  const page = s.model.pages.find(p => p.id === 'trackers')
  const section = page.sections.find(x => x.id === 'mine')
  return { page, section, rows: section.items.filter(it => /#\d+$/.test(it.row_id ?? '')) }
}
const enter = row => row.dispatch('keydown', { key: 'Enter' })
// the page shell asks a few DOM methods the small DOM of cockpit_render.mjs leaves out (as bridge_cockpit_point does)
const proto = Object.getPrototypeOf(document.createElement('div'))
if (!proto.querySelector) proto.querySelector = function querySelector(sel) { return this.$(sel) }
proto.focus ??= function focus() { document.activeElement = this }
globalThis.window ??= { addEventListener() {}, removeEventListener() {}, innerWidth: 1280 }
for (const k of ['offsetLeft', 'offsetWidth', 'scrollWidth', 'clientWidth']) Object.defineProperty(proto, k, { get: () => 0, configurable: true })

test('ghWalkAt: where a row stands in the walk of its list, by its index and title', () => {
  const walk = [{ index: 4, title: 'd' }, { index: 1, title: 'a' }, { index: 7, title: 'g' }]
  assert.deepEqual(logic.ghWalkAt(walk, { index: 1, title: 'a' }), { pos: 2, total: 3, prev: walk[0], next: [walk[2]] })
  assert.deepEqual(logic.ghWalkAt(walk, { index: 4, title: 'd' }), { pos: 1, total: 3, prev: null, next: [walk[1], walk[2]] })
  assert.equal(logic.ghWalkAt(walk, { index: 1, title: 'other' }), null, 'a row that changed is not taken for another')
  assert.equal(logic.ghWalkAt(null, { index: 1, title: 'a' }), null)
  assert.equal(logic.ghWalkAt(walk, null), null)
})

test('a row of the GitHub list opens beside the list with the rows as the list shows them, never as a point', () => {
  const s = cockpitState(NOW)
  const { section, rows } = ghPage(s)
  const c = recorder()
  const el = mount(html`<${GitHubList} items=${rows} page="trackers" section=${section} s=${{ ...s, ui: { ...s.ui, ghGroup: false } }} c=${c} byKey=${new Map()} />`)
  const shown = el.$$('.ghl-row')
  assert.ok(shown.length >= 2)
  enter(shown[1])
  const call = c.calls.at(-1)
  assert.equal(call[0], 'openInfo')
  assert.deepEqual(call.slice(2, 4), ['trackers', 'mine'])
  assert.equal(call[4].beside, true, 'beside the list')
  assert.deepEqual(call[4].walk.map(it => it.gh.title), shown.map(r => r.$('.ghl-title').text()), 'the walk is the list as it is shown')
  assert.equal(call[1], call[4].walk[1], 'the row clicked')
  assert.ok(!c.calls.some(x => x[0] === 'openPoint' || x[0] === 'peek'))
})

test('the row open beside the list is marked in the list', () => {
  const s = cockpitState(NOW)
  const { section, rows } = ghPage(s)
  const info = { it: rows[1], page: 'trackers', section: 'mine', beside: true, on: 'trackers', walk: rows }
  const el = mount(html`<${GitHubList} items=${rows} page="trackers" section=${section} s=${{ ...s, ui: { ...s.ui, ghGroup: false, info } }} c=${recorder()} byKey=${new Map()} />`)
  const marked = el.$$('.ghl-row').filter(r => r.hasClass('is-current'))
  assert.equal(marked.length, 1)
  assert.equal(marked[0].$('.ghl-title').text(), rows[1].gh.title)
  assert.equal(marked[0].getAttribute('aria-current'), 'true')
})

test('beside the list: a column, no overlay over the list; GitHub is read at once; back and next walk the list', async () => {
  const base = cockpitState(NOW)
  const { rows } = ghPage(base)
  assert.ok(rows.length >= 3, 'the invented page has three GitHub rows')
  const info = { it: rows[1], page: 'trackers', section: 'mine', beside: true, on: 'trackers', walk: rows }
  const s = { ...base, ui: { ...base.ui, page: 'trackers', info } }
  const c = recorder()
  const el = mount(html`<${InfoDrawer} s=${s} c=${c} beside />`)
  assert.equal(el.$('.overlay'), null, 'nothing lies over the list')
  assert.equal(el.$('[aria-modal]'), null)
  assert.ok(el.$('.col-detail .idrawer-beside'), 'a column beside the page')
  assert.match(el.$('.idrawer-title').text(), new RegExp(rows[1].gh.title))
  await settle()
  assert.deepEqual(c.calls.find(x => x[0] === 'github'), ['github', rows[1].row_id, false], 'what GitHub says, read on opening')
  assert.equal(el.$('.next-up-pos').text(), en.nextPos(2, rows.length))
  assert.equal(el.$('.next-up-title').text(), logic.short(rows[2].gh.title, 90), 'the next one by its GitHub title')
  el.button(en.nextOpen).click()
  assert.deepEqual(c.calls.at(-1), ['openInfo', rows[2], 'trackers', 'mine', { beside: true, walk: rows }])
  el.button(en.nextPrev).click()
  assert.deepEqual(c.calls.at(-1), ['openInfo', rows[0], 'trackers', 'mine', { beside: true, walk: rows }])
  el.button(en.item.close).click()
  assert.deepEqual(c.calls.at(-1), ['closeInfo'])
})

test('the page shell: the GitHub list on the left and the row beside it, on the page it was opened on only', () => {
  const base = cockpitState(NOW)
  const { rows } = ghPage(base)
  const info = { it: rows[0], page: 'trackers', section: 'mine', beside: true, on: 'trackers', walk: rows }
  const shell = ui => {
    // Jev's work order stays out (its own state); the page and its GitHub list are what counts here
    const st = { ...base, jev: { enabled: false }, jevOrder: {}, toasts: [], ui: { ...base.ui, ...ui } }
    return mount(html`<${components.App} store=${{ get: () => st, subscribe: () => () => {}, set() {} }} ctl=${recorder()} />`)
  }
  const el = shell({ page: 'trackers', info })
  assert.ok(el.$('main').hasClass('with-detail'), 'the page makes room for the column')
  assert.ok(el.$('main .col-detail .idrawer-beside'), 'the column stands in the page, beside the list')
  assert.ok(el.$$('main .ghl-row').length >= 2, 'the list stays to click the next row')
  assert.equal(el.$('.overlay'), null)
  const away = shell({ page: 'systems', info })
  assert.equal(away.$('.idrawer-beside'), null, 'another page shows no GitHub column')
  assert.ok(!away.$('main').hasClass('with-detail'))
})

test('the controller: a row beside the list opens there before any way to Work through; Escape, n and p and a page switch know it', () => {
  const info = method('openInfo(it, page, section')
  assert.ok(info.indexOf('beside') >= 0 && info.indexOf('beside') < info.indexOf('infoPoint('), 'beside the list comes first, never a point')
  assert.match(method('closeInfo() {'), /beside/)
  assert.match(APP, /s\.ui\.info\?\.beside && s\.ui\.info\.on === s\.ui\.page && !isTypingTarget\(e\.target\)\) return ctl\.closeInfo\(\)/, 'Escape closes the column')
  assert.match(APP, /ghWalkAt\(s\.ui\.info\.walk/, 'n and p walk the list')
  assert.match(method('setPage('), /info:/, 'another page lets the column go')
})

test('the keys act on the column only on its own page, and every way to another page lets it go', () => {
  // Escape and n / p check the page the column was opened on: left behind elsewhere, it must not take their keys
  assert.match(APP, /s\.ui\.info\?\.beside && s\.ui\.info\.on === s\.ui\.page && !isTypingTarget\(e\.target\)\) return ctl\.closeInfo\(\)/)
  assert.match(APP, /\(key === 'n' \|\| key === 'p'\) && s\.ui\.info\?\.beside && s\.ui\.info\.on === s\.ui\.page/)
  // the ways that set the page without setPage: Chat as a tab, a row's select onto the work tab
  assert.match(method('chatAsTab:'), /info: /)
  assert.match(method('select(key) {'), /page: 'briefing', info: /)
})
