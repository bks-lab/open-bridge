// SPDX-License-Identifier: MIT
// Render tests of the cockpit views (scripts/web/views/), no npm dependencies.
//
//   node scripts/tests/bridge_cockpit_render.test.mjs
//
// Each test mounts a component with the vendored Preact into the small DOM of cockpit_render.mjs,
// against the invented state of scripts/web/mock.js, and asserts on what a person sees and can press:
// the visible text, the buttons, the data and aria attributes, and the action a click sends. Nothing
// here reads a view's source, so renaming a variable or moving a call into a helper keeps them green
// as long as the page shows the same thing.
import test from 'node:test'
import assert from 'node:assert/strict'
import { cockpitState, loadCockpit, mount, recorder } from './cockpit_render.mjs'

const { html, views, text } = await loadCockpit()
const { ReturnCard, returnsOf } = views.home
const { TabControls } = views.detail
const { SessionCard } = views.sessions
const { Header } = views.header
const en = text.TABLES.en

// a fixed local "now": Friday, 9 October 2026, noon (the same moment the frontend suite uses)
const NOW = new Date(2026, 9, 9, 12, 0, 0).getTime()
const MIN = 60000

const tabOf = (s, ref) => s.tabs.tabs.find(t => t.ref === ref)
const labels = el => el.$$('button').map(b => b.text())

/** One start in the return channel, in the shape the server sends (model.returns) */
function start(over = {}) {
  return { key: 'inbox:20261009-0910-tidy-labels-c3d4', item: '20261009-0910-tidy-labels-c3d4', mode: 'go',
    title: 'Tidy the issue labels on the demo board', at_ms: NOW - 12 * MIN, stage: 'working', tab: { ref: 'surface:10' }, ...over }
}

/** The state with these starts, each card's `r` as the start page hands it over (returnsOf adds the live stage) */
function withReturns(returns, over = {}) {
  const s = cockpitState(NOW, over)
  s.model = { ...s.model, returns }
  return s
}

function renderReturn(r, over = {}) {
  const s = withReturns([r], over)
  const c = recorder()
  const [live] = returnsOf(s)
  return { el: mount(html`<${ReturnCard} r=${live} s=${s} c=${c} />`), c, s }
}

// ---------------------------------------------------------------- ReturnCard

test('return card: a settled start whose tab only waits offers to close the tab, first', () => {
  const { el, c } = renderReturn(start({ stage: 'done' }))
  const card = el.$('article.rcard')
  assert.ok(card.hasClass('tk-success'), card.getAttribute('class'))
  assert.equal(el.$('.rcard-title').text(), 'Tidy the issue labels on the demo board')
  assert.equal(el.$('.rcard-mode').text(), en.home.returnMode.go)
  // the steps light the one it stands on
  assert.equal(el.$('.rsteps li.is-now').text(), en.home.returnStage.done)
  assert.match(el.text(), new RegExp(en.home.returnSettled.replace(/[.]/g, '\\.')))
  const close = el.button(en.btnCloseTab)
  assert.ok(close.hasClass('btn-primary'))
  assert.equal(labels(el).indexOf(en.btnCloseTab), 2, labels(el).join(' | '))   // after the title and the forget cross
  close.click()
  assert.deepEqual(c.calls.at(-1), ['act', 'tab_close', { tab_ref: 'surface:10' }])
})

test('return card: without the close right of the terminal driver the tab stays and the card says nothing of closing', () => {
  const { el } = renderReturn(start({ stage: 'done' }), { driver: { caps: ['focus', 'screen', 'key'] } })
  assert.equal(el.button(en.btnCloseTab), null)
  assert.doesNotMatch(el.text(), new RegExp(en.home.returnSettled.slice(0, 12)))
  // going to the tab is the first way on now
  assert.ok(el.button(en.home.toTab).hasClass('btn-primary'))
})

test('return card: an answer shows its text and opens as the first way on, the tab second', () => {
  const answer = { text: 'Three labels renamed, two merged.', key: 'inbox:20261009-1130-result-0f0f' }
  const { el, c } = renderReturn(start({ stage: 'result', result: answer }))
  assert.equal(el.$('.rcard-answer').text(), `${en.home.returnAnswer} ${answer.text}`)
  assert.equal(el.button(en.btnCloseTab), null)
  const open = el.button(en.home.returnOpenAnswer)
  assert.ok(open.hasClass('btn-primary'))
  assert.ok(el.button(en.home.toTab).hasClass('btn-secondary'))
  open.click()
  assert.deepEqual(c.calls.at(-1), ['openItem', answer.key, null])
})

test('return card: a working start shows the tab last line, the way to the tab and its screen', () => {
  const { el, c } = renderReturn(start({ tab: { ref: 'surface:8' }, item: 'docs-refresh', key: 'task:docs-refresh', title: 'Refresh the docs' }))
  assert.equal(el.$('.rsteps li.is-now').text(), en.home.returnStage.working)
  assert.equal(el.$('.rcard-last').text(), 'Running the link check (12 of 40 pages)')
  el.button(en.home.view).click()
  assert.deepEqual(c.calls.at(-1), ['openTabView', 'surface:8'])
})

test('return card: a start without a word for minutes is lost, says so and keeps the row actions', () => {
  const { el } = renderReturn(start({ stage: 'started', tab: null, at_ms: NOW - 20 * MIN }))
  assert.ok(el.$('ol.rsteps').hasClass('is-lost'))
  assert.match(el.text(), new RegExp(en.home.returnLostHint.slice(0, 20)))
  assert.equal(el.button(en.home.toTab), null)
  // the row's own actions stand in for the missing tab
  assert.ok(el.$('.hcard-acts').$$('button').length > 0)
})

test('return card: the cross takes the start off the list', () => {
  const { el, c } = renderReturn(start())
  el.$(`button[aria-label="${en.home.returnForget}"]`).click()
  assert.deepEqual(c.calls.at(-1), ['act', 'return_forget', { key: 'inbox:20261009-0910-tidy-labels-c3d4' }])
})

// ---------------------------------------------------------------- TabControls

function renderControls(ref, { slim = true, tab: patch = {}, returns = [], ...over } = {}) {
  const s = withReturns(returns, over)
  const tab = { ...tabOf(s, ref), ...patch }
  const c = recorder()
  return { el: mount(html`<div class="host"><${TabControls} tab=${tab} s=${s} c=${c} slim=${slim} /></div>`), c }
}

test('tab controls, slim: a tab that asks offers yes and no, and yes reaches the tab', () => {
  const { el, c } = renderControls('surface:7')
  assert.deepEqual(labels(el), [en.btnYes, en.btnNo])
  el.button(en.btnYes).click()
  assert.deepEqual(c.calls.at(-1), ['act', 'tab_yes', { tab_ref: 'surface:7' }])
})

test('tab controls, slim: a waiting tab goes on; once its start settled, or it settled on its own, it closes', () => {
  assert.deepEqual(labels(renderControls('surface:12').el), [en.btnGoOn])
  const settledByStart = renderControls('surface:12', { returns: [start({ stage: 'done', tab: { ref: 'surface:12' } })] })
  assert.deepEqual(labels(settledByStart.el), [en.btnCloseTab])
  settledByStart.el.button(en.btnCloseTab).click()
  assert.deepEqual(settledByStart.c.calls.at(-1), ['act', 'tab_close', { tab_ref: 'surface:12' }])
  assert.deepEqual(labels(renderControls('surface:12', { tab: { settled: 'task' } }).el), [en.btnCloseTab])
  // a filed result closes as well; the control tab never offers to close
  assert.deepEqual(labels(renderControls('surface:10').el), [en.btnCloseTab])
  assert.deepEqual(labels(renderControls('surface:3', { tab: { settled: 'item' } }).el), [en.btnToTab])
})

test('tab controls, slim: without the driver rights the card falls back to the screen, and with none to nothing', () => {
  const screen = renderControls('surface:7', { driver: { caps: ['screen'] } })
  assert.deepEqual(labels(screen.el), [en.btnTabView])
  screen.el.button(en.btnTabView).click()
  assert.deepEqual(screen.c.calls.at(-1), ['openTabView', 'surface:7'])
  assert.deepEqual(labels(renderControls('surface:8', { driver: { caps: [] } }).el), [])
})

test('tab controls, full: every control of the tab, and the message field when it is open', () => {
  const closed = renderControls('surface:7', { slim: false })
  assert.deepEqual(labels(closed.el), [en.btnYes, en.btnNo, en.btnToTab, en.btnTabView, en.btnMessage])
  assert.equal(closed.el.button(en.btnMessage).getAttribute('aria-pressed'), 'false')
  closed.el.button(en.btnMessage).click()
  assert.deepEqual(closed.c.calls.at(-1), ['setOpenMsg', 'surface:7'])
  const open = renderControls('surface:7', { slim: false, ui: { openMsg: 'surface:7' } })
  const input = open.el.$('input#msg-surface\\:7')
  assert.ok(input, 'message input')
  assert.equal(input.getAttribute('placeholder'), en.msgPlaceholder)
  assert.equal(open.el.$(`label[for="msg-surface:7"]`).text(), en.msgPlaceholder)
  // nothing typed yet: send waits
  assert.equal(open.el.button(en.btnSend).hasAttribute('disabled'), true)
})

test('tab controls: a busy tab disables its buttons and says it is busy', () => {
  const { el } = renderControls('surface:7', { slim: false, ui: { busy: { 'surface:7': true } } })
  const yes = el.button(en.btnYes)
  assert.equal(yes.hasAttribute('disabled'), true)
  assert.equal(yes.getAttribute('aria-busy'), 'true')
  // viewing the screen does not wait on the tab
  assert.equal(el.button(en.btnTabView).hasAttribute('disabled'), false)
})

// ---------------------------------------------------------------- SessionCard

function renderSession(id, over = {}, patchTab = null) {
  const s = cockpitState(NOW, over)
  if (patchTab) s.tabs = { ...s.tabs, tabs: s.tabs.tabs.map(t => (t.ref === patchTab.ref ? { ...t, ...patchTab } : t)) }
  const x = s.sessions.sessions.find(y => y.id === id)
  const c = recorder()
  return { el: mount(html`<ul><${SessionCard} x=${x} s=${s} c=${c} /></ul>`), c }
}

test('session card: a session whose tab asks is loud, reads the full tab and answers it in the card', () => {
  const { el, c } = renderSession('d8db96ad')
  const li = el.$('li.sess')
  assert.ok(li.hasClass('is-alert'))
  assert.equal(el.$('.sess-head .state-line').text(), en.sessionStatus['needs-you'])
  assert.ok(el.$('.sess-head .state-line').hasClass('is-strong'))
  // the session list names its tab slim; the last line comes from the tab list
  assert.equal(el.$('.tab-last').text(), 'Allow edit of RELEASE_NOTES.md?')
  assert.equal(el.$('.sess-title').text(), 'alpha-release')
  assert.deepEqual(el.$('.sess-foot').$$('button').map(b => b.text()), [en.btnYes, en.btnNo])
  el.$('button.sess-title').click()
  assert.deepEqual(c.calls.at(-1), ['act', 'tab_jump', { tab_ref: 'surface:7' }])
})

test('session card: a tab settled on its own says so and offers to close', () => {
  const { el } = renderSession('d8db96ad', {}, { ref: 'surface:7', state: 'waiting', settled: 'item' })
  assert.match(el.text(), new RegExp(en.tabSettled.item.slice(0, 20)))
  assert.deepEqual(el.$('.sess-foot').$$('button').map(b => b.text()), [en.btnCloseTab])
})

test('session card: the control session shows its chips, its running agents and its workflow', () => {
  const { el } = renderSession('7a16c7b2')
  assert.ok(el.$('li.sess').hasClass('is-busy'))
  const chips = el.$('.sess-head').$$('.chip').map(x => x.text())
  assert.ok(chips.includes(en.sessionControl), chips.join(' | '))
  assert.ok(chips.includes('claude.ai'), chips.join(' | '))
  assert.equal(el.$$('.sess-agent-list > li').length, 2)
  assert.match(el.$('.sess-agents').text(), new RegExp(`^2 ${en.agentsWord(2)}`))
  assert.match(el.text(), /demo-build/)
})

test('session card: a session outside cmux has no tab controls and says where it is not', () => {
  const { el } = renderSession('3c9a1e44')
  assert.match(el.$('.sess-where').text(), new RegExp(en.sessionNoTab))
  assert.equal(el.$('button.sess-title'), null)
  assert.deepEqual(el.$('.sess-foot').$$('button').map(b => b.text()), [])
})

// ---------------------------------------------------------------- Header: the scratch hint

function renderHeader(scratch, over = {}) {
  const s = cockpitState(NOW, { boot: { status: 'ok', error: null, version: '0.1.0', config: {}, scratch }, ...over })
  return mount(html`<${Header} s=${s} c=${recorder()} />`)
}

test('header: a cockpit on a copy of the Bridge says so on every page, with the copy in its tooltip', () => {
  const el = renderHeader({ kind: 'copy', root: '/tmp/demo-copy' })
  const note = el.$('.hdr-scratch')
  assert.equal(note.getAttribute('role'), 'note')
  assert.equal(note.getAttribute('title'), en.scratchCopy('/tmp/demo-copy'))
  assert.equal(note.$('.hdr-demo-long').text(), en.scratchBadge)
  assert.equal(note.$('.hdr-demo-short').text(), en.scratchBadgeShort)
})

test('header: a cockpit with only its own state names that, and a normal one shows no hint', () => {
  const own = renderHeader({ kind: 'state', state_dir: '/tmp/demo-state' }).$('.hdr-scratch')
  assert.equal(own.getAttribute('title'), en.scratchState('/tmp/demo-state'))
  assert.equal(own.$('.hdr-demo-long').text(), en.stateBadge)
  assert.equal(renderHeader(null).$('.hdr-scratch'), null)
  // the demo badge is a different hint and stands apart from it
  const demo = renderHeader(null, { mock: true })
  assert.equal(demo.$('.hdr-scratch'), null)
  assert.equal(demo.$('.hdr-demo .hdr-demo-long').text(), en.demoBadge)
})

// ---------------------------------------------------------------- the agent tab column folds away

const { TabsColumn } = views.tabs

test('tab column: beside the work it offers to hide itself, in the drawer to pin it back', () => {
  const s = cockpitState(NOW)
  const c = recorder()
  const col = mount(html`<${TabsColumn} s=${s} c=${c} byKey=${new Map()} />`)
  assert.equal(col.button(en.tabsPin), null)
  col.button(en.tabsHide).click()
  assert.deepEqual(c.calls, [['toggleRail']])
  // hidden, the drawer behind the header button brings it back beside the page
  const hidden = cockpitState(NOW, { ui: { railHidden: true, drawer: 'tabs' } })
  const d = recorder()
  const drawer = mount(html`<${TabsColumn} s=${hidden} c=${d} byKey=${new Map()} inDrawer />`)
  assert.equal(drawer.button(en.tabsHide), null)
  drawer.button(en.tabsPin).click()
  assert.deepEqual(d.calls, [['toggleRail']])
  // a page that never has the column (Status, Sessions) offers no pin in its drawer
  const other = cockpitState(NOW, { ui: { railHidden: true, page: '@sessions' } })
  assert.equal(mount(html`<${TabsColumn} s=${other} c=${recorder()} byKey=${new Map()} inDrawer />`).button(en.tabsPin), null)
})

test('header: with the tab column hidden the work tab shows the Tabs button, else not', () => {
  const tabsBtn = el => el.$$('button').find(b => b.text().startsWith('Tabs')) ?? null
  assert.equal(tabsBtn(renderHeader(null)), null)
  assert.ok(tabsBtn(renderHeader(null, { ui: { page: 'briefing', railHidden: true } })))
})
