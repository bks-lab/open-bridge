// SPDX-License-Identifier: MIT
// Render test of the config warnings on the settings page (#402), no npm dependencies.
//
//   node --test scripts/tests/bridge_cockpit_config.test.mjs
//
// The server checks the cockpit: block and sends what it found as config_warnings in /api/bootstrap; the
// settings page shows them in a box above its areas, one line each, and nothing when the list is empty.
// The settings view is not among the views cockpit_render.mjs loads, so this file loads its own copy of
// scripts/web (the small DOM comes from cockpit_render.mjs) and renders with that copy's Preact.
import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { cockpitState, loadCockpit } from './cockpit_render.mjs'

await loadCockpit()                                    // the DOM and the invented state of mock.js
const WEB = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'web')
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'bridge-cockpit-config-'))
process.on('exit', () => fs.rmSync(tmp, { recursive: true, force: true }))
fs.cpSync(WEB, path.join(tmp, 'web'), { recursive: true })
fs.writeFileSync(path.join(tmp, 'web', 'package.json'), '{ "type": "module" }\n')
const load = rel => import(pathToFileURL(path.join(tmp, 'web', rel)).href)
const { html, render } = await load('vendor/htm-preact-3.1.1.module.js')
const { ConfigWarnings, SettingsPage } = await load('views/settings.js')
const en = (await load('text.js')).TABLES.en

const NOW = new Date(2026, 9, 9, 12, 0, 0).getTime()
const LINES = ['cockpit.open_in: "browser" is not one of auto, cmux, system, none; using "auto"',
  'cockpit.tab_seconds: unknown key, ignored']

function mount(vnode) {
  const root = document.createElement('div')
  render(vnode, root)
  return root
}

function withWarnings(warnings) {
  const s = cockpitState(NOW, { ui: { page: 'settings', settingsSection: 'look' } })
  return { ...s, boot: { ...s.boot, warnings } }
}

test('config warnings: one line per warning under a title that says what it is', () => {
  const el = mount(html`<${ConfigWarnings} s=${withWarnings(LINES)} />`)
  const box = el.$('.set-warnings')
  assert.ok(box, 'the box shows')
  assert.equal(box.getAttribute('role'), 'status')
  assert.match(box.text(), new RegExp(en.settings.configWarnings))
  assert.deepEqual(el.$$('.set-warnings-list li').map(li => li.text()), LINES)
})

test('config warnings: nothing at all for a clean block or a boot without the list', () => {
  assert.equal(mount(html`<${ConfigWarnings} s=${withWarnings([])} />`).$('.set-warnings'), null)
  const old = cockpitState(NOW)                        // a server from before #402 sends no list
  assert.equal(mount(html`<${ConfigWarnings} s=${old} />`).$('.set-warnings'), null)
})

test('config warnings: the settings page shows the box above its areas', () => {
  const el = mount(html`<${SettingsPage} s=${withWarnings(LINES)} c=${{}} />`)
  assert.equal(el.$$('.set-warnings-list li').length, 2)
  assert.ok(el.$('.settings-layout'), 'the areas still render')
})
