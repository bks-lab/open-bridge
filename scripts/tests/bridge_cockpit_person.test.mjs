// SPDX-License-Identifier: MIT
// Tests of a person's page (access.py): what the server names in bootstrap is all the page offers and all it sends.
//
//   node --test scripts/tests/bridge_cockpit_person.test.mjs
import test from 'node:test'
import assert from 'node:assert/strict'
import { cockpitState, loadCockpit, mount, recorder } from './cockpit_render.mjs'

const NOW = Date.parse('2026-10-09T12:00:00Z')
const { html, views, logic, text } = await loadCockpit()
const api = await import(new URL('../web/api.js', import.meta.url).href)
const T = text.T
const nav = views.nav
const person = { name: 'pat', pages: ['@start', 'briefing', '@files', '@chat'], verbs: ['done', 'note'],
  routes: ['/api/bootstrap', '/api/state', '/api/events', '/api/records', '/api/action', '/api/presence'] }
const asPerson = patch => {
  const s = cockpitState(NOW, patch)
  return { ...s, boot: { ...s.boot, config: { ...s.boot?.config, person } } }
}
const spy = () => {
  const sent = []
  return { sent, get: async p => { sent.push(p); return { ok: true, data: {} } }, post: async p => { sent.push(p); return { ok: true, data: {} } } }
}

test('a closed route never leaves the page and reads as a route that is not there', async () => {
  const t = spy()
  const a = api.createApi(t)
  a.setAccess(person)
  for (const res of [await a.get('/api/workers'), await a.seen('page'), await a.reload(true), await a.ask('free', { text: 'x' }, {})]) {
    assert.equal(res.ok, false)
    assert.equal(res.status, 404)
  }
  assert.deepEqual(t.sent, [])
})

test('an open route goes out, a query string does not change what it is', async () => {
  const t = spy()
  const a = api.createApi(t)
  a.setAccess(person)
  await a.records()
  await a.state()
  assert.deepEqual(t.sent, ['/api/records', '/api/state'])
})

test('a verb that is not theirs is not sent', async () => {
  const t = spy()
  const a = api.createApi(t)
  a.setAccess(person)
  assert.equal((await a.action('tab_new', {})).status, 404)
  assert.equal((await a.action('done', { key: 'x' })).ok, true)
  assert.deepEqual(t.sent, ['/api/action'])
})

test('the owner page sends everything as before', async () => {
  const t = spy()
  const a = api.createApi(t)
  await a.get('/api/workers')
  await a.seen('page')
  await a.action('tab_new', {})
  assert.equal(t.sent.length, 3)
  a.setAccess(null)
  await a.get('/api/usage')
  assert.equal(t.sent.length, 4)
})

test('the tabs of a person are the ones the server names, in their order', () => {
  assert.deepEqual(nav.pageOrder(asPerson()), person.pages)
})

test('the owner keeps the tabs of the bar', () => {
  const order = nav.pageOrder(cockpitState(NOW))
  assert.ok(order.includes(nav.SETTINGS_PAGE))
})

test('a person is told of no terminal driver', () => {
  const t = T()
  const owner = cockpitState(NOW, { driver: { caps: [] } })
  assert.ok(logic.pageWarnings(owner, t).some(w => w.kind === 'driver'))
  assert.ok(!logic.pageWarnings(asPerson({ driver: { caps: [] } }), t).some(w => w.kind === 'driver'))
})

test('the header of a person holds no Tabs, Ask or History and no reload', () => {
  const box = mount(html`<${views.header.Header} s=${asPerson({ layout: 'medium' })} c=${recorder()} />`)
  for (const cls of ['.hdr-tabs', '.hdr-ask', '.hdr-history', '.asof-btn']) assert.equal(box.$(cls), null, cls)
  assert.ok(box.$('.hdr-notes'))
})

test('the header of the owner keeps them', () => {
  const box = mount(html`<${views.header.Header} s=${cockpitState(NOW, { layout: 'medium' })} c=${recorder()} />`)
  for (const cls of ['.hdr-tabs', '.hdr-ask', '.hdr-history', '.asof-btn']) assert.ok(box.$(cls), cls)
})

test('a person has no column of agent tabs and no way to it', () => {
  const on = { ui: { page: 'briefing', railHidden: false } }
  assert.equal(logic.railOn(cockpitState(NOW, on)), true)
  assert.equal(logic.railOn(asPerson(on)), false)
})

test('a row offers a person neither a start nor a star', () => {
  const s = asPerson()
  const row = s.model.sections.flatMap(x => x.rows ?? []).find(r => r.key)
  assert.equal(mount(html`<${views.day.StartMenu} row=${row} s=${s} c=${recorder()} />`).$('button'), null)
  assert.equal(mount(html`<${views.home.PinStar} rowKey="task:x" s=${s} c=${recorder()} />`).$('button'), null)
  const owner = cockpitState(NOW)
  assert.ok(mount(html`<${views.day.StartMenu} row=${row} s=${owner} c=${recorder()} />`).$('button'))
})

test('an empty section stands out of a person\'s day, a full one stays', () => {
  const section = { id: 'delegate', total: 0, rows: [] }
  const c = recorder()
  assert.equal(mount(html`<${views.day.Section} section=${section} s=${asPerson()} c=${c} byKey=${new Map()} />`).$('section'), null)
  assert.ok(mount(html`<${views.day.Section} section=${section} s=${cockpitState(NOW)} c=${c} byKey=${new Map()} />`).$('section'))
})

test('a check of a row and a question in a file are not offered to a person', () => {
  const s = asPerson()
  const row = s.model.sections.flatMap(x => x.rows ?? []).find(r => r.key)
  assert.equal(mount(html`<${views.check.ReviewBlock} row=${row} s=${s} c=${recorder()} />`).$('.review-block'), null)
  assert.ok(mount(html`<${views.check.ReviewBlock} row=${row} s=${cockpitState(NOW)} c=${recorder()} />`).$('.review-block'))
})

test('a phone shows a person no switch with a single place', () => {
  const box = mount(html`<${views.overlays.MobileSwitch} s=${asPerson({ layout: 'narrow', ui: { page: '@start', pane: 'day' } })} c=${recorder()} />`)
  assert.equal(box.$('button'), null)
})

test('the Chat of a person says that questions are off and offers none', () => {
  const box = mount(html`<${views.chat.ChatPage} s=${asPerson()} c=${recorder()} />`)
  assert.ok(box.text().includes(T().chatArea.personOff))
  assert.equal(box.$('#quick-input'), null)
})
