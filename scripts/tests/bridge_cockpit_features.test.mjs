// SPDX-License-Identifier: MIT
// Tests of the Features area of the settings (views/settings.js FeaturesArea; logic.js featureGroups, featureDisabled,
// presetChanges, presetOn, restartStep, restartNotice), no npm dependencies.
//
//   node --test scripts/tests/bridge_cockpit_features.test.mjs
//
// The server sends the catalogue with each feature's value, what bridge-config.yaml alone says and whether the two
// differ (state.features, features.py). The page groups the rows in a fixed order, indents the sub switches of Work
// through under it and greys them while it is off, marks a changed value and a row that calls a model, opens the own
// settings of a helper, and applies a preset only after a confirm line in its card. A save that changes a config
// feature restarts the server; the page says so and reloads once the server says hello again.
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import test from 'node:test'
import assert from 'node:assert/strict'
import { cockpitState, loadCockpit, mount, recorder, settle } from './cockpit_render.mjs'

const { html, views, text, logic, mock } = await loadCockpit()
const en = text.TABLES.en
const de = text.TABLES.de
const { SettingsPage } = views.settings

const NOW = new Date(2026, 9, 9, 12, 0, 0).getTime()

/** One catalogue row in the shape of contract section 4 */
const item = (id, over = {}) => ({ id, group: 'work', kind: 'switch', value: false, config: false, overridden: false,
  requires: null, ai: false, store: null, area: null, ...over })

/** The page state with the Features area open; `features` patched over the mock's block */
function featuresPage(patch = {}, ui = {}) {
  const base = cockpitState(NOW, { ui: { page: '@settings', settingsSection: 'features', ...ui } })
  return { ...base, features: { ...base.features, ...patch } }
}

/** The mock's items with some of them changed: `{ id: { value, overridden, ... } }` */
function itemsWith(s, changes) {
  return s.features.items.map(x => (changes[x.id] ? { ...x, ...changes[x.id] } : x))
}

const rowOf = (el, id) => el.$(`[data-feature="${id}"]`)
const switchOf = (el, id) => rowOf(el, id)?.$('[role="switch"]')

// ---------------------------------------------------------------- logic: grouping

test('featureGroups: the groups in their fixed order whatever order the server sends, empty ones left out', () => {
  const items = [item('voice', { group: 'page' }), item('ticker', { group: 'helpers', store: 'ticker' }), item('chat_layout', { group: 'chat', kind: 'choice' }),
    item('describe', { kind: 'choice' }), item('flow')]
  assert.deepEqual(logic.featureGroups(items).map(g => g.id), ['work', 'chat', 'helpers', 'page'])
  assert.deepEqual(logic.FEATURE_GROUPS, ['work', 'chat', 'files', 'helpers', 'page'])
})

test('featureGroups: Work through first, its sub switches right after it and marked sub, the rest after them', () => {
  const items = [item('describe', { kind: 'choice' }), item('flow_themes', { requires: 'flow', ai: true }), item('triage_daily'),
    item('flow'), item('flow_seen', { requires: 'flow' })]
  const [work] = logic.featureGroups(items)
  assert.deepEqual(work.items.map(x => x.id), ['flow', 'flow_themes', 'flow_seen', 'describe', 'triage_daily'])
  assert.deepEqual(work.items.map(x => x.sub), [false, true, true, false, false])
  // a feature from a newer server in a group the page does not know yet still shows, after the known ones
  const later = logic.featureGroups([item('x', { group: 'later' }), item('voice', { group: 'page' })])
  assert.deepEqual(later.map(g => g.id), ['page', 'later'])
  assert.deepEqual(logic.featureGroups(null), [])
})

test('featureDisabled: a row is greyed while the feature it requires is off, never otherwise', () => {
  const off = [item('flow', { value: false }), item('flow_themes', { requires: 'flow' }), item('describe', { kind: 'choice', value: 'off' })]
  assert.equal(logic.featureDisabled(off[1], off), true)
  assert.equal(logic.featureDisabled(off[0], off), false)
  assert.equal(logic.featureDisabled(off[2], off), false)
  const on = off.map(x => (x.id === 'flow' ? { ...x, value: true } : x))
  assert.equal(logic.featureDisabled(on[1], on), false)
  // a requirement the list does not hold greys nothing: the server decides
  assert.equal(logic.featureDisabled(item('y', { requires: 'gone' }), off), false)
})

// ---------------------------------------------------------------- logic: presets

test('presetChanges: the features a preset names whose value differs now, unknown ids left out', () => {
  const items = [item('flow', { value: true }), item('flow_seen', { value: false }), item('describe', { kind: 'choice', value: 'off' })]
  assert.deepEqual(logic.presetChanges({ features: { flow: true, flow_seen: true, describe: 'stale', gone: true } }, items), ['flow_seen', 'describe'])
  assert.deepEqual(logic.presetChanges({ features: { flow: true } }, items), [])
  assert.deepEqual(logic.presetChanges({}, items), [])
  // a feature this cockpit does not offer (available false) changes nothing when a preset names it
  const served = [...items, item('triage_daily', { value: false, available: false })]
  assert.deepEqual(logic.presetChanges({ features: { triage_daily: true, flow_seen: true } }, served), ['flow_seen'])
})

test('presetOn: of the presets that match, the one naming most features; none matching, none', () => {
  const presets = [
    { id: 'basic', builtin: true, features: { a: false, b: false, c: false }, matches: false },
    { id: 'team', builtin: false, features: { a: true }, matches: true },
    { id: 'wide', builtin: false, features: { a: true, b: false }, matches: true },
  ]
  assert.equal(logic.presetOn(presets), 'wide')
  assert.equal(logic.presetOn(presets.map(p => ({ ...p, matches: false }))), null)
  // a tie keeps the order the server sends
  assert.equal(logic.presetOn([{ id: 'x', features: { a: 1 }, matches: true }, { id: 'y', features: { b: 1 }, matches: true }]), 'x')
  assert.equal(logic.presetOn(undefined), null)
})

test('presetOn with the items: a feature this cockpit does not offer neither breaks a match nor counts toward one', () => {
  const items = [item('flow', { value: true }), item('voice', { group: 'page', value: false }), item('triage_daily', { value: false, available: false })]
  // full names the daily sort, which this cockpit never switches on: the rest matches, so full is marked
  const full = { id: 'full', features: { flow: true, triage_daily: true }, matches: false }
  assert.equal(logic.presetOn([full], items), 'full')
  // a preset that names only what this cockpit does not offer matches nothing
  assert.equal(logic.presetOn([{ id: 'sort', features: { triage_daily: true }, matches: false }], items), null)
  // of two that match, the one naming more of what this cockpit offers
  const wide = { id: 'wide', features: { flow: true, voice: false }, matches: false }
  assert.equal(logic.presetOn([full, wide], items), 'wide')
  // what the server says still counts
  assert.equal(logic.presetOn([{ id: 'srv', features: { voice: true }, matches: true }], items), 'srv')
})

test('savableSettings: a save never carries a feature this cockpit does not offer', () => {
  const items = [item('flow', { value: true }), item('triage_daily', { value: false, available: false })]
  assert.deepEqual(logic.savableSettings({ flow: false, triage_daily: true }, items), { flow: false })
  assert.deepEqual(logic.savableSettings({ triage_daily: true }, items), {})
  // an id the page does not know goes as it is: the server answers for it
  assert.deepEqual(logic.savableSettings({ later: true }, items), { later: true })
  assert.deepEqual(logic.savableSettings({ flow: false }, null), { flow: false })
})

test('flowModeOf: Work through and Only Work through read as one choice of three, from the values or the config', () => {
  const items = (flow, only, cfg = {}) => [item('flow', { value: flow, config: cfg.flow ?? false }),
    item('flow_only', { requires: 'flow', value: only, config: cfg.only ?? false })]
  assert.equal(logic.flowModeOf(items(false, false)), 'off')
  assert.equal(logic.flowModeOf(items(false, true)), 'off')
  assert.equal(logic.flowModeOf(items(true, false)), 'beside')
  assert.equal(logic.flowModeOf(items(true, true)), 'only')
  assert.equal(logic.flowModeOf(items(true, true), 'config'), 'off')
  assert.equal(logic.flowModeOf(items(false, false, { flow: true, only: true }), 'config'), 'only')
  assert.equal(logic.flowModeOf([]), null)
})

test('flowModePatch: a pick of the Work through picker saves only what changes', () => {
  const items = (flow, only) => [item('flow', { value: flow }), item('flow_only', { requires: 'flow', value: only })]
  assert.deepEqual(logic.flowModePatch('only', items(false, false)), { flow: true, flow_only: true })
  assert.deepEqual(logic.flowModePatch('only', items(true, false)), { flow_only: true })
  assert.deepEqual(logic.flowModePatch('beside', items(true, true)), { flow_only: false })
  assert.deepEqual(logic.flowModePatch('beside', items(false, false)), { flow: true })
  // Lists switches both off, so the work tab never offers a view that is gone
  assert.deepEqual(logic.flowModePatch('off', items(true, true)), { flow: false, flow_only: false })
  assert.deepEqual(logic.flowModePatch('off', items(true, false)), { flow: false })
  assert.deepEqual(logic.flowModePatch('beside', items(true, false)), {})
  // a server without Only Work through: the patch never names it
  assert.deepEqual(logic.flowModePatch('beside', [item('flow')]), { flow: true })
  assert.deepEqual(logic.flowModePatch('only', [item('flow')]), { flow: true })
  // nor one this cockpit does not offer
  assert.deepEqual(logic.flowModePatch('only', [item('flow'), item('flow_only', { requires: 'flow', available: false })]), { flow: true })
})

test('presetBoard: one mark per feature in the order of the cards: switched on, at its default, or left as it is', () => {
  const items = [item('voice', { group: 'page' }), item('flow'), item('describe', { kind: 'choice', values: ['off', 'missing', 'stale'] }),
    item('flow_seen', { requires: 'flow' })]
  assert.deepEqual(logic.presetBoard({ features: { flow: true, describe: 'off', voice: false } }, items),
    [{ id: 'flow', state: 'on' }, { id: 'flow_seen', state: 'free' }, { id: 'describe', state: 'off' }, { id: 'voice', state: 'off' }])
  assert.equal(logic.presetBoard({ features: { describe: 'stale' } }, items).find(d => d.id === 'describe').state, 'on')
  assert.deepEqual(logic.presetBoard(null, []), [])
})

// ---------------------------------------------------------------- logic: the restart

test('restartStep: now waits for the server to come back and reloads on its next hello', () => {
  let st = logic.restartStep(null, { kind: 'answer', restart: 'now' })
  assert.deepEqual(st, { phase: 'restarting', reload: false })
  assert.deepEqual(logic.restartStep(st.phase, { kind: 'timeout' }), { phase: 'slow', reload: false })
  st = logic.restartStep('restarting', { kind: 'hello' })
  assert.deepEqual(st, { phase: null, reload: true })
  assert.deepEqual(logic.restartStep('slow', { kind: 'hello' }), { phase: null, reload: true })
})

test('restartStep: needed says so until the server is back, none changes nothing, only a restart it made reloads', () => {
  assert.deepEqual(logic.restartStep(null, { kind: 'answer', restart: 'needed' }), { phase: 'needed', reload: false })
  assert.deepEqual(logic.restartStep('needed', { kind: 'answer', restart: 'none' }), { phase: 'needed', reload: false })
  assert.deepEqual(logic.restartStep(null, { kind: 'answer', restart: 'none' }), { phase: null, reload: false })
  assert.deepEqual(logic.restartStep(null, { kind: 'hello' }), { phase: null, reload: false })
  // a hello after a restart by hand: the server's own pending flag says from then on whether one still waits
  assert.deepEqual(logic.restartStep('needed', { kind: 'hello' }), { phase: null, reload: false })
  assert.deepEqual(logic.restartStep(null, { kind: 'timeout' }), { phase: null, reload: false })
  // an answer from an older server without the field counts as none
  assert.deepEqual(logic.restartStep(null, { kind: 'answer' }), { phase: null, reload: false })
})

test('restartNotice: the restart of this page first, then what the server says: under way, waiting, or by hand', () => {
  assert.equal(logic.restartNotice('restarting', { pending: false, requested: false, can: true }), 'restarting')
  assert.equal(logic.restartNotice('slow', { pending: true, requested: true, can: true }), 'slow')
  // the server was asked to restart, from this page or another
  assert.equal(logic.restartNotice(null, { pending: true, requested: true, can: true }), 'restarting')
  // a change waits and nobody asked yet: the area offers Restart now where the server can, the commands where not
  assert.equal(logic.restartNotice(null, { pending: true, requested: false, can: true }), 'waiting')
  assert.equal(logic.restartNotice(null, { pending: true, requested: false, can: false }), 'needed')
  assert.equal(logic.restartNotice('needed', { pending: false, requested: false, can: false }), 'needed')
  assert.equal(logic.restartNotice(null, { pending: false, requested: false, can: true }), null)
  assert.equal(logic.restartNotice(null, undefined), null)
})

test('featuresLocked: only a restart under way locks the area, never a change that only waits', () => {
  assert.equal(logic.featuresLocked('restarting', { pending: false, requested: false }), true)
  assert.equal(logic.featuresLocked(null, { pending: true, requested: true }), true)
  assert.equal(logic.featuresLocked(null, { pending: true, requested: false, can: true }), false)
  assert.equal(logic.featuresLocked(null, { pending: true, requested: false, can: false }), false)
  // past the fallback the page says how to restart by hand, and the switches are free again
  assert.equal(logic.featuresLocked('slow', { pending: true, requested: false }), false)
  assert.equal(logic.featuresLocked('needed', undefined), false)
  assert.equal(logic.featuresLocked(null, undefined), false)
})

test('lostRestart: a save whose answer was lost restarts the server when it changed a config feature', () => {
  const f = { restart: { pending: false, requested: false, can: true }, items: [
    item('flow', { value: false }), item('voice', { group: 'page', value: false }),
    item('ticker', { group: 'helpers', store: 'ticker', value: false }),
    item('describe', { kind: 'choice', values: ['off', 'missing', 'stale'], value: 'off', overridden: false })],
    presets: [{ id: 'team', features: { flow: true } }, { id: 'news', features: { ticker: true } }, { id: 'same', features: { flow: false } }] }
  assert.equal(logic.lostRestart('features_save', { settings: { flow: true } }, f), 'now')
  assert.equal(logic.lostRestart('features_save', { settings: { ticker: true } }, f), 'none')     // a store acts at once
  assert.equal(logic.lostRestart('features_save', { settings: { voice: false } }, f), 'none')    // nothing changed
  assert.equal(logic.lostRestart('features_preset', { preset: 'team' }, f), 'now')
  assert.equal(logic.lostRestart('features_preset', { preset: 'news' }, f), 'none')
  assert.equal(logic.lostRestart('features_preset', { preset: 'same' }, f), 'none')
  assert.equal(logic.lostRestart('features_reset', {}, f), 'none')
  const changed = { ...f, items: f.items.map(x => (x.id === 'describe' ? { ...x, value: 'stale', overridden: true } : x)) }
  assert.equal(logic.lostRestart('features_reset', {}, changed), 'now')
  assert.equal(logic.lostRestart('features_restart', {}, f), 'now')
  // a server that cannot restart itself: the commands by hand
  const cannot = { ...f, restart: { ...f.restart, can: false } }
  assert.equal(logic.lostRestart('features_save', { settings: { flow: true } }, cannot), 'needed')
  assert.equal(logic.lostRestart('features_save', { settings: { flow: true } }, null), 'none')
  // saving a feature this cockpit does not offer is a no-op on the server, never a restart
  const served = { ...f, items: [...f.items, item('triage_daily', { value: false, available: false })] }
  assert.equal(logic.lostRestart('features_save', { settings: { triage_daily: true } }, served), 'none')
})

test('helloReload: another tab loads anew when the server started again while a restart waited or was asked for', () => {
  const waits = { pending: true, requested: false, can: true }
  assert.equal(logic.helloReload(null, 1000, waits), false)              // the first hello of this page
  assert.equal(logic.helloReload(1000, 1000, waits), false)              // the stream only reconnected
  assert.equal(logic.helloReload(1000, 2000, waits), true)
  assert.equal(logic.helloReload(1000, 2000, { pending: false, requested: true, can: true }), true)
  assert.equal(logic.helloReload(1000, 2000, { pending: false, requested: false, can: true }), false)
  assert.equal(logic.helloReload(1000, 2000, undefined), false)
  assert.equal(logic.helloReload(1000, undefined, waits), false)
})

// ---------------------------------------------------------------- the mock state

test('mock: ?served=1 shows a served cockpit, where the daily sort is not available', () => {
  const plain = mock.buildState(NOW).features.items
  assert.ok(plain.every(x => x.available === true))
  const served = mock.buildState(NOW, { served: true }).features.items
  assert.deepEqual(served.filter(x => x.available === false).map(x => x.id), ['triage_daily'])
})

test('mock: the demo carries the whole catalogue, two built-in presets and one from a file, nothing changed', () => {
  const f = mock.buildState(NOW).features
  const ids = f.items.map(x => x.id)
  for (const id of ['flow', 'flow_only', 'flow_themes', 'flow_summary', 'flow_instruct', 'flow_checkin', 'flow_prio_haiku', 'flow_seen', 'flow_attach',
    'describe', 'triage_daily', 'chat_layout', 'files_scope', 'files_search', 'launch_model', 'ticker', 'session_guide', 'voice']) assert.ok(ids.includes(id), id)
  assert.equal(f.overridden, 0)
  assert.deepEqual(f.presets.filter(p => p.builtin).map(p => p.id), ['basic', 'full'])
  assert.ok(f.presets.some(p => !p.builtin && p.title))
  assert.ok(Array.isArray(f.files_block) && Array.isArray(f.warnings))
  // the text table carries a label and a line for every feature of the catalogue, and the words of every choice
  for (const x of f.items) {
    for (const t of [en, de]) {
      assert.ok(t.features.label[x.id], `label ${x.id}`)
      assert.ok(t.features.explain[x.id], `explain ${x.id}`)
      for (const v of x.values ?? []) assert.ok(t.features.choice[x.id]?.[v], `choice ${x.id}.${v}`)
    }
  }
})

// ---------------------------------------------------------------- the stream

test('api: the stream hands the features event to its handler, as it does launch and the others', async () => {
  // api.js as an .mjs copy, so every supported Node version loads it (as bridge_cockpit_frontend.test.mjs does)
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'bridge-cockpit-features-'))
  const saved = globalThis.EventSource
  try {
    const web = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'web')
    fs.copyFileSync(path.join(web, 'api.js'), path.join(dir, 'api.mjs'))
    const api = await import(pathToFileURL(path.join(dir, 'api.mjs')).href)
    let es = null
    globalThis.EventSource = class { static CLOSED = 2; constructor() { this.listeners = {}; es = this } addEventListener(n, fn) { this.listeners[n] = fn } close() {} }
    const got = []
    const stream = api.createApi().events({ features: f => got.push(f) }, () => {})
    assert.equal(typeof es.listeners.features, 'function', 'the page listens to the features event')
    es.listeners.features({ data: JSON.stringify({ overridden: 1 }) })
    assert.deepEqual(got, [{ overridden: 1 }])
    stream.close()
  } finally {
    globalThis.EventSource = saved
    fs.rmSync(dir, { recursive: true, force: true })
  }
})

// ---------------------------------------------------------------- the area

test('features area: in the settings right after Setup, before the start page, with its own icon', () => {
  const s = featuresPage()
  const el = mount(html`<${SettingsPage} s=${s} c=${recorder()} />`)
  const names = el.$$('.settings-nav-item b').map(b => b.text())
  assert.equal(names[0], en.settings.section.features.title)
  assert.equal(names[1], en.settings.section.start.title)
  assert.equal(en.settings.section.features.title, 'Features')
  assert.equal(de.settings.section.features.title, 'Funktionen')
  assert.ok(el.$('.settings-nav-item.is-on').text().includes(en.settings.section.features.title))
})

test('features area: no banner while nothing differs; with a change the banner counts it and Reset resets', async () => {
  const plain = mount(html`<${SettingsPage} s=${featuresPage()} c=${recorder()} />`)
  assert.equal(plain.$('.set-banner'), null)
  const s0 = featuresPage()
  const s = featuresPage({ overridden: 2, items: itemsWith(s0, { flow: { value: false, overridden: true }, voice: { value: true, overridden: true } }) })
  const c = recorder()
  const el = mount(html`<${SettingsPage} s=${s} c=${c} />`)
  const banner = el.$('.set-banner')
  assert.ok(banner)
  assert.match(banner.text(), new RegExp(en.features.overridden(2)))
  banner.button(en.features.reset).click()
  await settle()
  assert.equal(c.calls.length, 0, 'the first click only asks')
  el.$('.set-banner').button(en.features.resetApply).click()
  assert.deepEqual(c.calls.at(-1), ['resetFeatures'])
})

test('features area: Work through heads the area as its own card, then the presets, then one card per group in order', () => {
  const el = mount(html`<${SettingsPage} s=${featuresPage()} c=${recorder()} />`)
  const titles = el.$$('.settings-body .set-card-name').map(x => x.text())
  assert.deepEqual(titles, [en.features.flowTitle, en.features.presetsTitle, ...['work', 'chat', 'files', 'helpers', 'page'].map(g => en.features.group[g].title)])
  const hero = el.$$('.settings-body .set-card')[0]
  assert.ok(hero.hasClass('feat-hero'), 'the headline card stands out')
  assert.match(hero.text(), new RegExp(en.features.flowIntro.slice(0, 20)))
  // nothing in the area is a bare dropdown
  assert.equal(el.$$('select').length, 0)
})

const SUBS = ['flow_themes', 'flow_summary', 'flow_instruct', 'flow_checkin', 'flow_prio_haiku', 'flow_seen', 'flow_attach']
const heroOf = el => el.$$('.set-card').find(x => x.hasClass('feat-hero'))

test('features area: the sub switches of Work through stand indented in its card and grey while it is off', () => {
  const s0 = featuresPage()
  const on = mount(html`<${SettingsPage} s=${featuresPage({ items: itemsWith(s0, { flow: { value: true } }) })} c=${recorder()} />`)
  const ids = heroOf(on).$$('[data-feature]').map(x => x.getAttribute('data-feature'))
  assert.deepEqual(ids, ['flow', ...SUBS])
  for (const id of SUBS) {
    assert.ok(rowOf(on, id).hasClass('feat-sub'), id)
    assert.ok(!switchOf(on, id).hasAttribute('disabled'), `${id} free while Work through is on`)
  }
  // the rest of the group stays in its own card
  assert.ok(!heroOf(on).$('[data-feature="describe"]'))
  const off = mount(html`<${SettingsPage} s=${featuresPage({ items: itemsWith(s0, { flow: { value: false } }) })} c=${recorder()} />`)
  for (const id of ['flow_themes', 'flow_seen']) {
    assert.ok(switchOf(off, id).hasAttribute('disabled'), `${id} greyed while Work through is off`)
    assert.ok(rowOf(off, id).hasClass('is-off'), id)
  }
  // one line in the card says why, not one per sub switch
  assert.ok(heroOf(off).text().includes(en.features.subsWait))
  assert.ok(!heroOf(on).text().includes(en.features.subsWait))
  assert.ok(!rowOf(off, 'flow_themes').text().includes(en.features.needs(en.features.label.flow)))
  assert.ok(!switchOf(off, 'voice').hasAttribute('disabled'))
})

test('features area: Work through is a picker of three cards with sketches, the one in use marked, a pick saves what changes', () => {
  const s0 = featuresPage()
  const c = recorder()
  const el = mount(html`<${SettingsPage} s=${featuresPage({ items: itemsWith(s0, { flow: { value: true }, flow_only: { value: false } }) })} c=${c} />`)
  const radios = rowOf(el, 'flow').$$('[role="radio"]')
  assert.deepEqual(radios.map(r => r.$('.view-name').text()), ['off', 'beside', 'only'].map(m => en.features.flowMode[m].title))
  assert.ok(radios.every(r => r.$('.view-thumb')), 'each card carries its sketch')
  assert.deepEqual(radios.map(r => r.getAttribute('aria-checked')), ['false', 'true', 'false'])
  assert.ok(radios[1].hasClass('is-on'))
  radios[2].click()
  assert.deepEqual(c.calls.at(-1), ['saveFeatures', { flow_only: true }])
  radios[0].click()
  assert.deepEqual(c.calls.at(-1), ['saveFeatures', { flow: false }])
  // the one in use asks for nothing
  const n = c.calls.length
  radios[1].click()
  assert.equal(c.calls.length, n)
  // changed against the config: the chip names what the config says, in the picker's words
  const changed = mount(html`<${SettingsPage} s=${featuresPage({ overridden: 1, items: itemsWith(s0, { flow: { value: true, config: false, overridden: true } }) })} c=${recorder()} />`)
  const chip = heroOf(changed).$$('.chip').find(ch => ch.text() === en.features.changed)
  assert.equal(chip?.getAttribute('title'), en.features.configWas(en.features.flowMode.off.title))
})

test('features area: a feature this cockpit does not offer stands greyed with a line why, its control dead', () => {
  const s0 = featuresPage()
  const el = mount(html`<${SettingsPage} s=${featuresPage({ items: itemsWith(s0, { triage_daily: { available: false } }) })} c=${recorder()} />`)
  assert.ok(switchOf(el, 'triage_daily').hasAttribute('disabled'))
  assert.ok(rowOf(el, 'triage_daily').text().includes(en.features.unavailable))
  assert.ok(!switchOf(el, 'voice').hasAttribute('disabled'))
  assert.ok(!rowOf(el, 'voice').text().includes(en.features.unavailable))
  // a choice the same way: its cards wait
  const choice = mount(html`<${SettingsPage} s=${featuresPage({ items: itemsWith(s0, { chat_layout: { available: false } }) })} c=${recorder()} />`)
  assert.ok(rowOf(choice, 'chat_layout').$$('[role="radio"]').every(r => r.hasAttribute('disabled')))
  assert.ok(rowOf(choice, 'chat_layout').text().includes(en.features.unavailable))
})

test('features area: a feature that requires one of another group says what it needs beside its greyed control', () => {
  const s0 = featuresPage()
  const items = [...itemsWith(s0, { flow: { value: false } }), item('voice_more', { group: 'page', requires: 'flow' })]
  const el = mount(html`<${SettingsPage} s=${featuresPage({ items })} c=${recorder()} />`)
  assert.ok(switchOf(el, 'voice_more').hasAttribute('disabled'))
  assert.ok(rowOf(el, 'voice_more').text().includes(en.features.needs(en.features.label.flow)))
  assert.ok(!rowOf(el, 'voice_more').hasClass('feat-sub'))
})

test('features area: while the server restarts every control waits', () => {
  const el = mount(html`<${SettingsPage} s=${featuresPage({}, { featuresRestart: 'restarting' })} c=${recorder()} />`)
  assert.ok(switchOf(el, 'voice').hasAttribute('disabled'))
  assert.ok(el.$$('[role="radio"]').every(r => r.hasAttribute('disabled')))
})

test('features area: a switch and a choice save at once, only what changed', () => {
  const s0 = featuresPage()
  const s = featuresPage({ items: itemsWith(s0, { flow: { value: true }, flow_seen: { value: false }, describe: { value: 'off' } }) })
  const c = recorder()
  const el = mount(html`<${SettingsPage} s=${s} c=${c} />`)
  switchOf(el, 'flow_seen').click()
  assert.deepEqual(c.calls.at(-1), ['saveFeatures', { flow_seen: true }])
  const stale = rowOf(el, 'describe').$$('[role="radio"]').find(r => r.$('.view-name').text() === en.features.choice.describe.stale)
  stale.click()
  assert.deepEqual(c.calls.at(-1), ['saveFeatures', { describe: 'stale' }])
  // while a save runs every control waits
  const busy = mount(html`<${SettingsPage} s=${{ ...s, ui: { ...s.ui, busy: { features_save: 'features_save' } } }} c=${recorder()} />`)
  assert.ok(switchOf(busy, 'voice').hasAttribute('disabled'))
})

test('features area: the AI chip on the rows that call a model, the changed chip with what the config says', () => {
  const s0 = featuresPage()
  const s = featuresPage({ overridden: 1, items: itemsWith(s0, { describe: { value: 'stale', config: 'off', overridden: true } }) })
  const el = mount(html`<${SettingsPage} s=${s} c=${recorder()} />`)
  // Only Work through is a card of the Work through picker, not a row of its own
  for (const x of s.features.items.filter(y => y.id !== 'flow_only')) {
    const chip = rowOf(el, x.id).$$('.chip').find(ch => ch.text() === en.features.ai)
    assert.equal(!!chip, !!x.ai, x.id)
    if (chip) assert.equal(chip.getAttribute('title'), en.features.aiTitle)
  }
  const changed = rowOf(el, 'describe').$$('.chip').find(ch => ch.text() === en.features.changed)
  assert.ok(changed)
  assert.equal(changed.getAttribute('title'), en.features.configWas(en.features.choice.describe.off))
  assert.ok(!rowOf(el, 'voice').$$('.chip').some(ch => ch.text() === en.features.changed))
})

test('features area: every choice is a picker of cards with a sketch, never a dropdown, and a pick saves at once', () => {
  const s0 = featuresPage()
  const s = featuresPage({ items: itemsWith(s0, { chat_layout: { value: 'classic' }, files_scope: { value: 'active' }, describe: { value: 'missing' } }) })
  const c = recorder()
  const el = mount(html`<${SettingsPage} s=${s} c=${c} />`)
  for (const [id, values, now, other] of [['chat_layout', ['classic', 'workspaces'], 'classic', 'workspaces'],
    ['files_scope', ['active', 'all'], 'active', 'all'], ['describe', ['off', 'missing', 'stale'], 'missing', 'off']]) {
    const group = rowOf(el, id).$('[role="radiogroup"]')
    assert.ok(group, id)
    const radios = group.$$('[role="radio"]')
    assert.deepEqual(radios.map(r => r.$('.view-name').text()), values.map(v => en.features.choice[id][v]), id)
    for (const [i, r] of radios.entries()) {
      assert.ok(r.$(`.view-thumb.view-thumb-${id}-${values[i]}`), `${id}.${values[i]} has its sketch`)
      assert.ok(r.text().includes(en.features.choiceLine[id][values[i]]), `${id}.${values[i]} says what it does`)
      assert.equal(r.getAttribute('aria-checked'), String(values[i] === now))
    }
    radios[values.indexOf(other)].click()
    assert.deepEqual(c.calls.at(-1), ['saveFeatures', { [id]: other }], id)
  }
})

test('features area: the helpers are tiles with a sketch, lit while on, with their switch and Details', () => {
  const s0 = featuresPage()
  const s = featuresPage({ items: itemsWith(s0, { ticker: { value: true }, session_guide: { value: false } }) })
  const c = recorder()
  const el = mount(html`<${SettingsPage} s=${s} c=${c} />`)
  for (const id of ['launch_model', 'ticker', 'session_guide']) {
    const tile = rowOf(el, id)
    assert.ok(tile.hasClass('feat-tile'), id)
    assert.ok(tile.$(`.view-thumb.view-thumb-${id}`), `${id} has its sketch`)
    assert.ok(tile.$('[role="switch"]'), `${id} has its switch`)
  }
  assert.ok(rowOf(el, 'ticker').hasClass('is-on'))
  assert.ok(!rowOf(el, 'session_guide').hasClass('is-on'))
  switchOf(el, 'session_guide').click()
  assert.deepEqual(c.calls.at(-1), ['saveFeatures', { session_guide: true }])
})

test('features area: each preset card sketches what it sets, one mark per feature, lit where it switches one on', () => {
  const s = featuresPage()
  const el = mount(html`<${SettingsPage} s=${s} c=${recorder()} />`)
  const radios = el.$$('[role="radio"]').filter(r => r.$('.view-thumb-board'))
  assert.equal(radios.length, s.features.presets.length)
  for (const [i, r] of radios.entries()) {
    const board = logic.presetBoard(s.features.presets[i], s.features.items)
    const marks = r.$$('.view-thumb-board i')
    assert.equal(marks.length, s.features.items.length, s.features.presets[i].id)
    assert.deepEqual(marks.map(m => m.getAttribute('class')), board.map(d => `is-${d.state}`), s.features.presets[i].id)
  }
  // basic lights nothing, full lights all it names
  assert.equal(radios[0].$$('.view-thumb-board i.is-on').length, 0)
  assert.ok(radios[1].$$('.view-thumb-board i.is-on').length > 10)
})

test('features area: each helper row has a Details button that opens its own settings area', () => {
  const c = recorder()
  const el = mount(html`<${SettingsPage} s=${featuresPage()} c=${c} />`)
  const areas = { launch_model: 'launch', ticker: 'ticker', session_guide: 'guide' }
  for (const [id, area] of Object.entries(areas)) {
    rowOf(el, id).button(en.features.details).click()
    assert.deepEqual(c.calls.at(-1), ['setSettingsSection', area], id)
  }
  assert.equal(rowOf(el, 'flow').button(en.features.details), null)
})

test('features area: Ask AI in Files names its block words, or warns when there are none', () => {
  const withWords = mount(html`<${SettingsPage} s=${featuresPage({ files_block: ['Health', 'Family'] })} c=${recorder()} />`)
  assert.match(rowOf(withWords, 'files_search').text(), new RegExp(en.features.blockWords('Health, Family')))
  const none = mount(html`<${SettingsPage} s=${featuresPage({ files_block: [] })} c=${recorder()} />`)
  const row = rowOf(none, 'files_search')
  assert.ok(row.text().includes(en.features.blockNone))
  assert.ok(row.$('.tk-warning'), 'the warning line in the warning tone')
})

test('features area: a preset is a picker card, the matching one marked, built-ins titled from the text table', async () => {
  const s = featuresPage()
  const el = mount(html`<${SettingsPage} s=${s} c=${recorder()} />`)
  const radios = el.$$('[role="radio"]').filter(r => r.$('.view-thumb-board'))
  const names = radios.map(r => r.$('.view-name').text())
  assert.equal(names[0], en.features.preset.basic.title)
  assert.equal(names[1], en.features.preset.full.title)
  assert.ok(names.includes(s.features.presets.find(p => !p.builtin).title))
  assert.equal(de.features.preset.basic.title, 'Grundausstattung')
  assert.equal(de.features.preset.full.title, 'Alles an')
  const on = logic.presetOn(s.features.presets)
  radios.forEach((r, i) => assert.equal(r.getAttribute('aria-checked'), String(s.features.presets[i].id === on), s.features.presets[i].id))
  // the preset the server says matches now is the one marked, and a click on it asks nothing
  const matching = featuresPage({ presets: s.features.presets.map(p => ({ ...p, matches: p.id === 'team' })) })
  const marked = mount(html`<${SettingsPage} s=${matching} c=${recorder()} />`)
  const checked = marked.$$('[role="radio"]').filter(r => r.$('.view-thumb-board') && r.getAttribute('aria-checked') === 'true')
  assert.deepEqual(checked.map(r => r.$('.view-name').text()), ['Team'])
  assert.ok(checked[0].hasClass('is-on'))
  checked[0].click()
  await settle()
  assert.equal(marked.$('.feat-ask'), null)
})

test('features area: a click on a preset asks in its card first; Cancel leaves it, Apply applies it', async () => {
  const s0 = featuresPage()
  const team = { id: 'team', builtin: false, title: 'Team', description: 'What the team works with', scope: 'org',
    features: { flow: true, flow_seen: true, voice: true }, matches: false }
  const s = featuresPage({ presets: [...s0.features.presets.filter(p => p.builtin), team],
    items: itemsWith(s0, { flow: { value: true }, flow_seen: { value: false }, voice: { value: false } }) })
  const c = recorder()
  const el = mount(html`<${SettingsPage} s=${s} c=${c} />`)
  const radio = () => el.$$('[role="radio"]').find(r => r.$('.view-name').text() === 'Team')
  assert.equal(el.$('.feat-ask'), null)
  radio().click()
  await settle()
  const ask = el.$('.feat-ask')
  assert.ok(ask, 'the confirm line stands in the card')
  assert.match(ask.text(), new RegExp(en.features.ask('Team', 2).replace('?', '\\?')))
  assert.equal(c.calls.length, 0, 'nothing applied before Apply')
  ask.button(en.features.cancel).click()
  await settle()
  assert.equal(el.$('.feat-ask'), null)
  assert.equal(c.calls.length, 0)
  radio().click()
  await settle()
  el.$('.feat-ask').button(en.features.apply).click()
  assert.deepEqual(c.calls.at(-1), ['applyFeaturePreset', 'team'])
})

test('features area: a change that waits offers Restart now, locks nothing, and Reset stays free', async () => {
  const s0 = featuresPage()
  const s = featuresPage({ overridden: 1, restart: { pending: true, requested: false, can: true },
    items: itemsWith(s0, { flow: { value: false, config: true, overridden: true } }) })
  const c = recorder()
  const el = mount(html`<${SettingsPage} s=${s} c=${c} />`)
  const notice = el.$('.feat-restart')
  assert.ok(notice.text().includes(en.features.restartWaiting))
  notice.button(en.features.restartNow).click()
  assert.deepEqual(c.calls.at(-1), ['restartFeatures'])
  assert.ok(!switchOf(el, 'voice').hasAttribute('disabled'), 'a waiting change locks no switch')
  assert.ok(el.$$('[role="radio"]').every(r => !r.hasAttribute('disabled')), 'nor a picker card')
  el.$('.set-banner').button(en.features.reset).click()
  await settle()
  el.$('.set-banner').button(en.features.resetApply).click()
  assert.deepEqual(c.calls.at(-1), ['resetFeatures'])
  // a server that cannot restart itself: the commands by hand instead of the button
  const cannot = mount(html`<${SettingsPage} s=${featuresPage({ restart: { pending: true, requested: false, can: false } })} c=${recorder()} />`)
  assert.ok(cannot.text().includes(en.features.restartNeeded))
  assert.equal(cannot.button(en.features.restartNow), null)
  assert.ok(!switchOf(cannot, 'voice').hasAttribute('disabled'))
  // asked for, here or in another browser: it restarts, and the area waits for it
  const asked = mount(html`<${SettingsPage} s=${featuresPage({ restart: { pending: true, requested: true, can: true } })} c=${recorder()} />`)
  assert.ok(asked.text().includes(en.features.restarting))
  assert.equal(asked.button(en.features.restartNow), null)
  assert.ok(switchOf(asked, 'voice').hasAttribute('disabled'))
})

test('features area: the restart line while the server restarts, and the hint when a restart is needed', () => {
  const restarting = mount(html`<${SettingsPage} s=${featuresPage({}, { featuresRestart: 'restarting' })} c=${recorder()} />`)
  assert.ok(restarting.text().includes(en.features.restarting))
  const needed = mount(html`<${SettingsPage} s=${featuresPage({ restart: { pending: true, requested: false, can: false } })} c=${recorder()} />`)
  assert.ok(needed.text().includes(en.features.restartNeeded))
  const slow = mount(html`<${SettingsPage} s=${featuresPage({}, { featuresRestart: 'slow' })} c=${recorder()} />`)
  assert.ok(slow.text().includes(en.features.restartSlow))
  const quiet = mount(html`<${SettingsPage} s=${featuresPage()} c=${recorder()} />`)
  assert.ok(!quiet.text().includes(en.features.restarting) && !quiet.text().includes(en.features.restartNeeded))
})

test('features area: the warnings of the presets show as lines; an older server without the block says so', () => {
  const el = mount(html`<${SettingsPage} s=${featuresPage({ warnings: ['workflow/cockpit-presets/x.yaml: unknown feature foo, left out'] })} c=${recorder()} />`)
  assert.ok(el.text().includes('workflow/cockpit-presets/x.yaml: unknown feature foo, left out'))
  const base = cockpitState(NOW, { ui: { page: '@settings', settingsSection: 'features' } })
  const old = mount(html`<${SettingsPage} s=${{ ...base, features: null }} c=${recorder()} />`)
  assert.ok(old.text().includes(en.features.noServer))
})

test('features area: German words stay short and natural', () => {
  text.setLanguage('de')
  try {
    const el = mount(html`<${SettingsPage} s=${featuresPage()} c=${recorder()} />`)
    assert.ok(el.$$('.settings-nav-item b').some(b => b.text() === 'Funktionen'))
    const names = el.$$('[role="radio"] .view-name').map(x => x.text())
    assert.ok(names.includes('Abarbeiten') && names.includes('Nur Abarbeiten'))
    assert.ok(names.includes('Grundausstattung') && names.includes('Alles an'))
    assert.equal(de.features.label.flow, 'Abarbeiten')
  } finally {
    text.setLanguage('en')
  }
})

// ---------------------------------------------------------------- what a switch did, said plainly (Axel's cockpit)

const DASHES = /[–—]/

test('features area: a switch set here reads as done, not as a fault: an info banner, Back to the config asks first', async () => {
  const s0 = featuresPage()
  const s = featuresPage({ overridden: 1, items: itemsWith(s0, { chat_layout: { value: 'workspaces', config: 'classic', overridden: true } }) })
  const c = recorder()
  const el = mount(html`<${SettingsPage} s=${s} c=${c} />`)
  const banner = el.$('.set-banner')
  assert.ok(banner.getAttribute('class').includes('is-info'), 'the info tone, not the warning one')
  assert.equal(en.features.overridden(1), '1 switch set here, bridge-config.yaml stays as it is')
  assert.equal(en.features.overridden(3), '3 switches set here, bridge-config.yaml stays as it is')
  assert.equal(de.features.overridden(1), '1 Schalter hier eingestellt, bridge-config.yaml bleibt, wie sie ist')
  assert.equal(de.features.overridden(2), '2 Schalter hier eingestellt, bridge-config.yaml bleibt, wie sie ist')
  banner.button(en.features.reset).click()
  await settle()
  const asking = el.$('.set-banner')
  assert.ok(asking.text().includes(en.features.resetAsk(1)))
  asking.button(en.features.cancel).click()
  await settle()
  assert.equal(c.calls.length, 0)
  assert.ok(!el.$('.set-banner').text().includes(en.features.resetAsk(1)))
  assert.equal(de.features.reset, 'Zurück auf bridge-config.yaml')
})

test('features area: the mark beside a switch set here says so in the info tone, with what the config says', () => {
  const s0 = featuresPage()
  const s = featuresPage({ overridden: 1, items: itemsWith(s0, { describe: { value: 'stale', config: 'off', overridden: true } }) })
  const el = mount(html`<${SettingsPage} s=${s} c=${recorder()} />`)
  const mark = rowOf(el, 'describe').$$('.chip').find(ch => ch.text() === en.features.changed)
  assert.ok(mark.getAttribute('class').includes('tk-info') && !mark.getAttribute('class').includes('tk-warning'))
  assert.deepEqual([en.features.changed, de.features.changed], ['set here', 'hier eingestellt'])
})

test('restartedLately: the server came back from its own restart within the last two minutes', () => {
  const now = 1_800_000_000_000
  assert.equal(logic.restartedLately({ done_ms: now - 5000 }, now), true)
  assert.equal(logic.restartedLately({ done_ms: now - logic.RESTARTED_SHOW_MS - 1 }, now), false)
  assert.equal(logic.restartedLately({ done_ms: null }, now), false)
  assert.equal(logic.restartedLately(null, now), false)
  assert.equal(logic.restartedLately({ done_ms: now + 60000 }, now), false, 'a time from the future says nothing')
  assert.equal(logic.RESTARTED_SHOW_MS, 120000)
})

test('features area: after its own restart the area says the change is saved and acts now', () => {
  const back = mount(html`<${SettingsPage} s=${featuresPage({ restart: { pending: false, requested: false, can: true, code: false, done_ms: Date.now() - 4000 } })} c=${recorder()} />`)
  assert.ok(back.text().includes(en.features.restarted))
  assert.ok(back.$('.feat-done').getAttribute('class').includes('is-success'), 'good news, never the warning frame')
  const long = mount(html`<${SettingsPage} s=${featuresPage({ restart: { pending: false, requested: false, can: true, code: false, done_ms: Date.now() - 600000 } })} c=${recorder()} />`)
  assert.ok(!long.text().includes(en.features.restarted))
  const again = mount(html`<${SettingsPage} s=${featuresPage({ restart: { pending: true, requested: false, can: true, code: false, done_ms: Date.now() - 4000 } })} c=${recorder()} />`)
  assert.ok(!again.text().includes(en.features.restarted), 'a change that waits again says that instead')
})

test('restartNotice: newer code on disk offers a restart too, a waiting change first', () => {
  assert.equal(logic.restartNotice(null, { pending: false, requested: false, can: true, code: true }), 'code')
  assert.equal(logic.restartNotice(null, { pending: true, requested: false, can: true, code: true }), 'waiting')
  assert.equal(logic.restartNotice(null, { pending: false, requested: true, can: true, code: true }), 'restarting')
  assert.equal(logic.restartNotice(null, { pending: false, requested: false, can: true, code: false }), null)
})

test('features area: newer code on disk: the area says so and Restart now restarts', () => {
  const c = recorder()
  const el = mount(html`<${SettingsPage} s=${featuresPage({ restart: { pending: false, requested: false, can: true, code: true, done_ms: null } })} c=${c} />`)
  const notice = el.$('.feat-restart')
  assert.ok(notice.text().includes(en.features.restartCode))
  assert.ok(notice.getAttribute('class').includes('is-info'))
  notice.button(en.features.restartNow).click()
  assert.deepEqual(c.calls.at(-1), ['restartFeatures'])
})

test('serverCodeNotice: the header offers the restart to the owner while newer code waits', () => {
  const base = cockpitState(NOW, { ui: { page: 'briefing' } })
  const withRestart = (restart, ui = {}) => ({ ...base, ui: { ...base.ui, ...ui }, features: { ...base.features, restart } })
  assert.equal(logic.serverCodeNotice(withRestart({ pending: false, requested: false, can: true, code: false })), null)
  assert.equal(logic.serverCodeNotice(withRestart({ pending: false, requested: false, can: true, code: true })), 'ready')
  assert.equal(logic.serverCodeNotice(withRestart({ pending: false, requested: false, can: false, code: true })), null, 'nothing to press without a hook')
  assert.equal(logic.serverCodeNotice(withRestart({ pending: false, requested: true, can: true, code: true })), 'restarting')
  assert.equal(logic.serverCodeNotice(withRestart({ pending: false, requested: false, can: true, code: true }, { featuresRestart: 'restarting' })), 'restarting')
  assert.equal(logic.serverCodeNotice({ ...withRestart({ pending: false, requested: false, can: true, code: true }), boot: { ...base.boot, config: { ...base.boot?.config, person: { name: 'Sam' } } } }), null, 'never a served person')
  assert.equal(logic.serverCodeNotice({ ...base, features: null }), null)
})

test('header: a newer cockpit version waits: one line and Restart, which restarts it', () => {
  const base = cockpitState(NOW, { ui: { page: 'briefing' } })
  const s = { ...base, features: { ...base.features, restart: { pending: false, requested: false, can: true, code: true, done_ms: null } } }
  const c = recorder()
  const el = mount(html`<${views.header.ServerCode} s=${s} c=${c} />`)
  assert.ok(el.text().includes(en.serverCode.line))
  el.button(en.serverCode.button).click()
  assert.deepEqual(c.calls.at(-1), ['restartFeatures'])
  const busy = mount(html`<${views.header.ServerCode} s=${{ ...s, ui: { ...s.ui, featuresRestart: 'restarting' } }} c=${recorder()} />`)
  assert.ok(busy.text().includes(en.serverCode.restarting))
  const none = mount(html`<${views.header.ServerCode} s=${base} c=${recorder()} />`)
  assert.equal(none.text().trim(), '')
  assert.deepEqual([de.serverCode.button, de.serverCode.line], ['Neu starten', 'Neuer Stand des Cockpits bereit'])
})

test('features area: an older server says it runs the code from before the update, and how to restart it', () => {
  for (const t of [en, de]) assert.match(t.features.noServer, /bridge-cockpit\.py stop/)
  assert.match(en.features.noServer, /before the update/)
  assert.match(de.features.noServer, /vor dem Update/)
})

test('features area: the new words carry no dashes and the commands work without Claude', () => {
  const words = t => [t.features.overridden(2), t.features.reset, t.features.resetTitle, t.features.resetAsk(2), t.features.resetApply,
    t.features.changed, t.features.restarted, t.features.restartCode, t.features.noServer, t.features.restartSlow, t.features.restartNeeded,
    t.serverCode.line, t.serverCode.button, t.serverCode.title, t.serverCode.restarting]
  for (const t of [en, de]) {
    for (const w of words(t)) assert.ok(typeof w === 'string' && w && !DASHES.test(w), w)
    for (const w of [t.features.noServer, t.features.restartSlow, t.features.restartNeeded]) assert.match(w, /bridge-cockpit\.py open/)
  }
})

test('features area: before the first state it says it loads, not that the server is old', () => {
  const base = cockpitState(NOW, { ui: { page: '@settings', settingsSection: 'features' } })
  const loading = mount(html`<${SettingsPage} s=${{ ...base, server: null, features: null }} c=${recorder()} />`)
  assert.ok(!loading.text().includes(en.features.noServer))
  assert.ok(loading.text().includes(en.features.loading))
  const old = mount(html`<${SettingsPage} s=${{ ...base, features: null }} c=${recorder()} />`)
  assert.ok(base.server, 'the mock state has arrived')
  assert.ok(old.text().includes(en.features.noServer))
})

test('features area: the line after a restart fits a restart for newer code too, nothing claims a save', () => {
  for (const t of [en, de]) assert.ok(!/Saved|Gespeichert/.test(t.features.restarted), t.features.restarted)
})
