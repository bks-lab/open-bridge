// SPDX-License-Identifier: MIT
// Tests of Settings, On this machine (scripts/web/views/machine.js, logic.js machineModel and machineTree), no npm
// dependencies.
//
//   node --test scripts/tests/bridge_cockpit_machine.test.mjs
//
// A page or a section of the briefing profile switched off on one machine: the page loses it at once (the collect
// leaves it out from the next pass on), the settings list every page with its sections, a sub page under its folder.
import test from 'node:test'
import assert from 'node:assert/strict'
import { cockpitState, loadCockpit, mount, recorder } from './cockpit_render.mjs'

const { html, views, text, logic } = await loadCockpit()
const en = text.TABLES.en
const NOW = new Date(2026, 9, 9, 12, 0, 0).getTime()

const sec = (id, title = id) => ({ id, title, kind: 'command', items: [] })
const model = () => ({
  seq: 3,
  pages: [
    { id: 'ops', title: 'Ops', sections: [sec('probes')], subs: ['@workers', 'lab', 'ci-monitor'] },
    { id: 'lab', title: 'Lab', under: 'ops', sections: [sec('lab-probe'), sec('lab-gpu')] },
    { id: 'ci-monitor', title: 'CI', under: 'ops', sections: [sec('ci')] },
    { id: 'jobs', title: 'Jobs', sections: [sec('applications')] },
  ],
  alarms: [{ page_id: 'jobs', page_title: 'Jobs', section_title: 'applications', count: 1 }],
})
const CATALOG = [
  { id: 'ops', title: 'Ops', group: 'main', under: null, sections: [{ id: 'probes', title: 'Probes', kind: 'command' }] },
  { id: 'jobs', title: 'Jobs', group: 'main', under: null, sections: [{ id: 'applications', title: 'Applications', kind: 'tracker' }] },
  { id: 'lab', title: 'Lab', group: 'main', under: 'ops', sections: [{ id: 'lab-probe', title: 'Lab probe', kind: 'command' }] },
  { id: 'work', title: 'Work', group: 'work', under: null, sections: [{ id: 'inbox', title: 'Inbox', kind: 'inbox' }] },
]

test('machineModel: nothing off keeps the very same model', () => {
  const m = model()
  assert.equal(logic.machineModel(m, { pages_off: [], sections_off: [] }), m)
  assert.equal(logic.machineModel(m, null), m)
  assert.equal(logic.machineModel(null, { pages_off: ['ops'] }), null)
})

test('machineModel: a page off has no tab, leaves its folder, and its alarm goes with it', () => {
  const m = logic.machineModel(model(), { pages_off: ['jobs', 'lab'], sections_off: [] })
  assert.deepEqual(m.pages.map(p => p.id), ['ops', 'ci-monitor'])
  assert.deepEqual(m.pages[0].subs, ['@workers', 'ci-monitor'])      // the cockpit's own page is no profile page
  assert.deepEqual(m.alarms, [])
  // a folder off takes its sub pages with it
  assert.deepEqual(logic.machineModel(model(), { pages_off: ['ops'] }).pages.map(p => p.id), ['jobs'])
})

test('machineModel: a section off stands nowhere, a page with every section off goes like a page off', () => {
  const m = logic.machineModel(model(), { pages_off: [], sections_off: ['lab-gpu', 'ci'] })
  assert.deepEqual(m.pages.map(p => p.id), ['ops', 'lab', 'jobs'])
  assert.deepEqual(m.pages[1].sections.map(x => x.id), ['lab-probe'])
  assert.deepEqual(m.pages[0].subs, ['@workers', 'lab'])
  // ids the profile no longer has change nothing
  const same = model()
  assert.equal(logic.machineModel(same, { pages_off: ['gone'], sections_off: ['nope'] }), same)
})

test('machineTree: each folder followed by its sub pages, the folder named on them', () => {
  assert.deepEqual(logic.machineTree(CATALOG).map(p => [p.id, p.parentTitle ?? null]),
    [['ops', null], ['lab', 'Ops'], ['jobs', null], ['work', null]])
  assert.deepEqual(logic.machineTree(null), [])
})

test('settings: On this machine lists every page and its sections with a switch, and switches through the server', () => {
  const { SettingsPage } = views.settings
  const s = cockpitState(NOW, { ui: { page: '@settings', settingsSection: 'machine' },
    views: { rev: 1, pages_off: ['jobs'], sections_off: ['lab-probe'], catalog: CATALOG } })
  const c = recorder()
  const el = mount(html`<${SettingsPage} s=${s} c=${c} />`)
  assert.ok(el.$$('.settings-nav-item').some(b => b.text().includes(en.settings.section.machine.title)))
  const body = el.$('.settings-body')
  assert.equal(body.$('.set-card-name').text(), en.machine.title)
  // pages in the tree's order, the sub page a step in
  assert.deepEqual(body.$$('.mc-page > .set-row .set-label').map(x => x.text()), ['Ops', 'Lab', 'Jobs', 'Work'])
  assert.ok(body.$$('.mc-page')[1].getAttribute('class').includes('is-child'))
  // a page off shows no sections and says so; a page whose sections are all off says that
  const jobs = body.$$('.mc-page')[2]
  assert.ok(!jobs.$('.mc-sections') && jobs.text().includes(en.machine.pageOff))
  assert.ok(body.$$('.mc-page')[1].text().includes(en.machine.allOff))
  // a section the briefing page shows itself says it goes there too
  assert.ok(body.$$('.mc-page')[3].text().includes(en.machine.briefingToo))
  el.$$('button[role="switch"]').find(b => b.getAttribute('aria-label') === en.machine.pageLabel('Jobs')).click()
  assert.deepEqual(c.calls.at(-1), ['viewSwitch', 'page', 'jobs', true])
  el.$$('button[role="switch"]').find(b => b.getAttribute('aria-label') === en.machine.sectionLabel('Probes')).click()
  assert.deepEqual(c.calls.at(-1), ['viewSwitch', 'section', 'probes', false])
})

test('settings: On this machine without the server block or without pages says why', () => {
  const { SettingsPage } = views.settings
  const old = mount(html`<${SettingsPage} s=${cockpitState(NOW, { ui: { page: '@settings', settingsSection: 'machine' }, views: null })} c=${recorder()} />`)
  assert.match(old.$('.settings-body').text(), new RegExp(en.machine.older.slice(0, 20)))
  const none = mount(html`<${SettingsPage} s=${cockpitState(NOW, { ui: { page: '@settings', settingsSection: 'machine' },
    views: { rev: 0, pages_off: [], sections_off: [], catalog: [] } })} c=${recorder()} />`)
  assert.match(none.$('.settings-body').text(), new RegExp(en.machine.none.slice(0, 20)))
})

test('text: every word of the area in both languages', () => {
  const de = text.TABLES.de
  assert.deepEqual(Object.keys(de.machine).sort(), Object.keys(en.machine).sort())
  assert.ok(de.settings.section.machine.title === 'Auf diesem Rechner' && en.settings.section.machine.title === 'On this machine')
  for (const v of Object.values(de.machine)) {
    const words = typeof v === 'function' ? v('X') : v
    assert.doesNotMatch(words, /[\u2013\u2014]| - /, words)
  }
})
