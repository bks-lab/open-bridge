// SPDX-License-Identifier: MIT
// Tests of the colour mode button in the header (scripts/web/views/header.js, logic.nextTheme), no npm dependencies.
//
//   node --test scripts/tests/bridge_cockpit_theme_button.test.mjs
//
// One click goes auto, light, dark and round again; the icon and the label say the mode it stands on. The owner's
// choice stays in this browser (setTheme); a person's is also kept on the server, as on their Settings page.
import test from 'node:test'
import assert from 'node:assert/strict'
import { cockpitState, loadCockpit, mount, recorder } from './cockpit_render.mjs'

const NOW = Date.parse('2026-10-09T12:00:00Z')
const { html, views, logic, text } = await loadCockpit()
const { Header } = views.header
const en = text.TABLES.en

const person = { name: 'pat', pages: ['@start', 'briefing', '@files', '@chat'], verbs: ['done', 'note'] }

function header(theme, asPerson = false) {
  const s = cockpitState(NOW, { ui: { theme } })
  const state = asPerson ? { ...s, boot: { ...s.boot, config: { ...s.boot?.config, person } } } : s
  const c = recorder()
  return { el: mount(html`<${Header} s=${state} c=${c} />`), c }
}

test('the modes go round: auto, light, dark, auto; anything else starts at light', () => {
  assert.equal(logic.nextTheme('auto'), 'light')
  assert.equal(logic.nextTheme('light'), 'dark')
  assert.equal(logic.nextTheme('dark'), 'auto')
  assert.equal(logic.nextTheme(undefined), 'light')
  assert.equal(logic.nextTheme('neon'), 'light')
})

test('the header carries the button, named after the mode it stands on', () => {
  for (const mode of ['auto', 'light', 'dark']) {
    const { el } = header(mode)
    const btn = el.$('.hdr-theme')
    assert.ok(btn, `no theme button for ${mode}`)
    const label = btn.getAttribute('aria-label') ?? btn.getAttribute('title') ?? ''
    assert.ok(label.includes(en.theme[mode]), `${mode}: ${label}`)
  }
})

test('a click on the owner page sets the next mode and nothing else', () => {
  const { el, c } = header('light')
  el.$('.hdr-theme').click()
  assert.deepEqual(c.calls.filter(x => x[0] === 'setTheme'), [['setTheme', 'dark']])
  assert.equal(c.calls.filter(x => x[0] === 'act').length, 0)
})

test('on a person page the choice is also kept on the server', () => {
  const { el, c } = header('dark', true)
  el.$('.hdr-theme').click()
  assert.deepEqual(c.calls.filter(x => x[0] === 'setTheme'), [['setTheme', 'auto']])
  assert.deepEqual(c.calls.find(x => x[0] === 'act')?.slice(1), ['person_settings', { theme: 'auto' }])
})
