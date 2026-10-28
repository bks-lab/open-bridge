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
const loadedRooms = await loadCockpit()
const en = text.TABLES.en

// a fixed local "now": Friday, 9 October 2026, noon (the same moment the frontend suite uses)
const NOW = new Date(2026, 9, 9, 12, 0, 0).getTime()
const MIN = 60000

const tabOf = (s, ref) => s.tabs.tabs.find(t => t.ref === ref)
const labels = el => el.$$('button').map(b => b.text())
const tick = () => new Promise(resolve => setTimeout(resolve, 20))
/** Waits for an effect with a bounded loop of ticks (slow runners take more than one) */
async function until(done, n = 100) {
  for (let i = 0; i < n && !done(); i++) await tick()
}

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
  // round 6d: its tab only waits, so it can close too, less loudly than the answer
  assert.ok(el.button(en.btnCloseTab)?.hasClass('btn-secondary'), labels(el).join(' | '))
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

test('the sessions page: a settled start is done, never to check; it stands there only while its tab is open to be closed', () => {
  const old = n => start({ key: `inbox:20261001-0900-old-${n}`, item: `20261001-0900-old-${n}`, title: `Old start ${n}`,
    stage: 'done', tab: null, at_ms: NOW - 3 * 24 * 60 * MIN })
  const s = withReturns([old(1), old(2), start({ stage: 'done' })], { ui: { page: '@sessions' } })
  const box = mount(html`<${views.sessions.SessionsPage} s=${s} c=${recorder()} />`).$('.ai-returns')
  assert.ok(box !== null, 'the section of the starts stands')
  const heads = box.$$('.ai-group h4').map(h => h.text())
  assert.ok(!heads.some(h => h.startsWith(en.aiGroup.check)), heads.join(' | '))
  assert.deepEqual(heads, [`${en.aiGroup.done} 1`])
  assert.deepEqual(box.$$('.rcard-title').map(b => b.text()), ['Tidy the issue labels on the demo board'])
  assert.ok(box.button(en.btnCloseTab) !== null, 'its tab can go')
  // with nothing but old settled starts nothing is left for you: no section at all
  const quiet = withReturns([old(1), old(2)], { ui: { page: '@sessions' } })
  assert.ok(!mount(html`<${views.sessions.SessionsPage} s=${quiet} c=${recorder()} />`).$('.ai-returns'), 'the old starts stand there')
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
  // it asks a question: it goes on, its close waits until it settled
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
  const { el } = renderSession('d8db96ad', {}, { ref: 'surface:7', state: 'waiting', settled: 'item', ask: null })
  assert.match(el.text(), new RegExp(en.tabSettled.item.slice(0, 20)))
  assert.deepEqual(el.$('.sess-foot').$$('button').map(b => b.text()), [en.btnCloseTab])
})

// ---------------------------------------------------------------- TabClose (round 6d): one close of a tab in every place

test('tab close: a tab with a task and an item behind it offers Done and close tab first, Close tab only beside it', () => {
  const { el, c } = renderControls('surface:13', { tab: { ask: null, behind: { task: 'demo-task', item: '20261009-0910-tidy-labels-c3d4' } } })
  assert.deepEqual(labels(el), [en.btnGoOn, en.btnDoneCloseTab, en.btnCloseTabOnly])
  assert.ok(el.button(en.btnDoneCloseTab).hasClass('btn-primary'))
  assert.ok(el.button(en.btnCloseTabOnly).hasClass('btn-secondary'))
  el.button(en.btnDoneCloseTab).click()
  assert.deepEqual(c.calls.at(-1), ['act', 'tab_done', { tab_ref: 'surface:13' }])
})

test('tab close: unseen answers ask first, a second click closes, a settled tab closes at once', async () => {
  const { el, c } = renderControls('surface:13', { tab: { ask: null, filed_by: 'ref:issue-1' } })
  const close = () => el.$('.tab-close').$$('button')[0]
  assert.equal(close().text(), en.btnCloseTab)
  close().click()
  await until(() => close().text() === en.closeTabSure(en.btnCloseTab))
  assert.equal(close().text(), en.closeTabSure(en.btnCloseTab))
  assert.equal(close().getAttribute('title'), en.closeTabUnseen)
  assert.equal(c.calls.filter(x => x[0] === 'act').length, 0)
  close().click()
  assert.deepEqual(c.calls.at(-1), ['act', 'tab_close', { tab_ref: 'surface:13' }])
  const settled = renderControls('surface:13', { tab: { ask: null, settled: 'item', filed_by: 'ref:issue-1' } })
  settled.el.button(en.btnCloseTab).click()
  assert.deepEqual(settled.c.calls.at(-1), ['act', 'tab_close', { tab_ref: 'surface:13' }])
  // a tab from which nothing came back closes at the first click
  const plain = renderControls('surface:13', { tab: { ask: null } })
  plain.el.$('.tab-close').$$('button')[0].click()
  assert.deepEqual(plain.c.calls.at(-1), ['act', 'tab_close', { tab_ref: 'surface:13' }])
})

test('tab close: a tab at work, one that asks and the control tab offer no close', () => {
  for (const [ref, patch] of [['surface:8', {}], ['surface:12', {}], ['surface:7', {}], ['surface:3', { settled: 'item' }]]) {
    assert.ok(!renderControls(ref, { tab: patch }).el.$('.tab-close'), ref)
    assert.ok(!renderControls(ref, { slim: false, tab: patch }).el.$('.tab-close'), ref)
  }
})

test('tab close: the full controls, the return card and a session card hold the same one close', () => {
  assert.ok(renderControls('surface:13', { slim: false, tab: { ask: null } }).el.$('.tab-close'), 'full controls')
  const card = renderReturn(start({ stage: 'result', tab: { ref: 'surface:10' }, result: { text: 'Done.', key: null } }))
  assert.ok(card.el.$('.tab-close'), 'a return card whose answer came back')
  const sess = renderSession('d8db96ad', {}, { ref: 'surface:7', state: 'waiting', ask: null })
  assert.ok(sess.el.$('.sess-foot .tab-close'), 'a session card')
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

// ---------------------------------------------------------------- the page bar: More and the keys in the tooltips

/** The page bar as on a screen too narrow for its tabs, handed to `check`: the DOM has no layout, so the bar is told
 *  that it overflows (scrollWidth past clientWidth) and folds every tab of the more group behind More, one a render.
 *  It reads its active tab back and listens for resize (as in the aria suite); the stubs stand for this mount only,
 *  and the bar is unmounted before they go */
async function foldedBar(s, check) {
  const { render } = await loadCockpit()
  const proto = Object.getPrototypeOf(document.body)
  const saved = ['querySelector', 'offsetLeft', 'offsetWidth', 'scrollWidth', 'clientWidth'].map(k => [k, Object.getOwnPropertyDescriptor(proto, k)])
  const hadWindow = 'window' in globalThis
  if (!hadWindow) globalThis.window = { addEventListener() {}, removeEventListener() {}, innerWidth: 1280 }
  Object.defineProperty(proto, 'querySelector', { value(sel) { return this.$(sel) }, configurable: true, writable: true })
  for (const k of ['offsetLeft', 'offsetWidth', 'clientWidth']) Object.defineProperty(proto, k, { get: () => 0, configurable: true })
  Object.defineProperty(proto, 'scrollWidth', { get() { return this.hasClass('pagebar') ? 2000 : 0 }, configurable: true })
  const root = document.createElement('div')
  try {
    render(html`<${views.header.PageBar} s=${s} c=${recorder()} />`, root)
    await new Promise(resolve => setTimeout(resolve, 30))
    check(root)
  } finally {
    render(null, root)
    for (const [k, d] of saved) { if (d) Object.defineProperty(proto, k, d); else delete proto[k] }
    if (!hadWindow) delete globalThis.window
  }
}

test('page bar: More wears a dot only for a reason behind it; a grey count, an idle agent or a green ok is none', async () => {
  const base = cockpitState(NOW)
  const calm = cockpitState(NOW, { agents: { ...base.agents, convs: [] }, ui: { page: '@start' } })
  await foldedBar(calm, el => {
    const more = el.$('.ptab-more button')
    assert.ok(more !== null, 'the tabs of the more group fold behind More')
    assert.equal(more.text().startsWith(en.morePages), true)
    assert.ok(!more.$('.dot'), 'a dot on More with nothing behind it')
  })
  // a page behind More with a finding: its colour on More
  const page = { id: 'llm', title: 'Models', group: 'more', badge: { kind: 'bad', n: 2 }, sections: [] }
  const bad = { ...calm, model: { ...calm.model, pages: [...calm.model.pages, page] } }
  await foldedBar(bad, el => assert.ok(!!el.$('.ptab-more button .dot.tk-danger'), 'no red dot for a finding behind More'))
  const ok = { ...calm, model: { ...calm.model, pages: [...calm.model.pages, { ...page, badge: { kind: 'ok' } }] } }
  await foldedBar(ok, el => assert.ok(!el.$('.ptab-more button .dot'), 'a dot on More for a green ok'))
  // background jobs: an outage is red on More, upkeep alone no reason (proposal 5, jobCounts)
  const runs = [{ id: 'a', state: 'last_run_failed', severity: 'high' }, { id: 'b', state: 'drifted', severity: 'medium' }]
  const down = { ...calm, workers: { status: 'ok', data: { stats: { with_findings: 2, in_service: 2 }, runs } } }
  await foldedBar(down, el => assert.ok(!!el.$('.ptab-more button .dot.tk-danger'), 'no red dot for an outage of the jobs'))
  const upkeep = { ...calm, workers: { status: 'ok', data: { stats: { with_findings: 1, in_service: 1 }, runs: [runs[1]] } } }
  await foldedBar(upkeep, el => assert.ok(!el.$('.ptab-more button .dot'), 'a dot on More for upkeep of the jobs'))
})

test('page bar and header: a tooltip names a key only while the shortcuts are on', async () => {
  const proto = Object.getPrototypeOf(document.body)
  proto.focus ??= function focus() { document.activeElement = this }
  const off = cockpitState(NOW, { ui: { page: '@start' } })
  const on = cockpitState(NOW, { ui: { page: '@start', shortcuts: true } })
  await foldedBar(off, el => {
    const titles = el.$$('[title]').map(x => x.getAttribute('title'))
    assert.ok(!titles.some(x => /\(Alt \d\)/.test(x)), titles.join(' | '))
  })
  await foldedBar(on, el => assert.equal(el.$$('[role=tab]')[0].getAttribute('title'), `${en.startTab} (Alt 1)`))
  const header = s => mount(html`<${Header} s=${s} c=${recorder()} />`)
  const titles = el => el.$$('button').map(b => b.getAttribute('title')).filter(Boolean)
  // the as-of time is the reload (r); Explain, first in Help, answers to ? (decision 6, menue.md)
  const quiet = header(off)
  quiet.$('.hdr-help > button').click()
  await tick()
  assert.ok(!titles(quiet).some(x => /\((\?|r)\)$/.test(x)), titles(quiet).join(' | '))
  assert.ok(titles(quiet).includes(en.hints.buttonTitle) && titles(quiet).some(x => x.endsWith(` · ${en.reloadTitle}`)), titles(quiet).join(' | '))
  const keyed = header(on)
  keyed.$('.hdr-help > button').click()
  await tick()
  assert.ok(titles(keyed).includes(`${en.hints.buttonTitle} (?)`) && titles(keyed).some(x => x.endsWith(`${en.reloadTitle} (r)`)), titles(keyed).join(' | '))
})

// ---------------------------------------------------------------- Header: four parts and the as-of time (K1 to K5)

test('header: the as-of time is the reload button with its mark; no colours, reload or Explain button beside it', () => {
  const s = cockpitState(NOW)
  const c = recorder()
  const el = mount(html`<${Header} s=${s} c=${c} />`)
  const asof = el.$('.hdr-asof button')
  assert.ok(asof, 'the time is a button')
  assert.equal(asof.$('.asof-text').text(), en.sourceAsOf(s.model.collected_at))
  assert.ok(asof.$('svg'), 'with the reload mark on it')
  assert.match(asof.getAttribute('title'), new RegExp(en.reloadTitle.replace(/[()]/g, '\\$&')))
  asof.click()
  assert.deepEqual(c.calls, [['reload']])
  for (const gone of ['.hdr-reload', '.hdr-theme', '.hdr-explain']) assert.ok(!el.$(gone), `${gone} left the header`)
  assert.ok(!el.$$('button').some(b => /^Theme\b/.test(b.getAttribute('aria-label') ?? '')), 'no colours button')
  for (const kept of ['.hdr-ask', '.hdr-history', '.hdr-notes', '.hdr-help']) assert.ok(el.$(kept), `${kept} stays`)
})

test('header as the menu has it (decision 6): Notes is the bell, Help ? holds Explain first, the look-up topics and the tour', async () => {
  // the menu moves the focus in on open: the small DOM answers with what it supports
  const proto = Object.getPrototypeOf(document.body)
  proto.focus ??= function focus() { document.activeElement = this }
  const s = cockpitState(NOW)
  const c = recorder()
  const el = mount(html`<${Header} s=${s} c=${c} />`)
  // left to right: History, Notes, then Help at the end
  const parts = el.$('.hdr-right').childNodes.map(n => (n.nodeType === 1 ? n.getAttribute('class') ?? '' : ''))
  const at = name => parts.findIndex(x => x.split(' ').includes(`hdr-${name}`))
  assert.ok(at('history') >= 0 && at('history') < at('notes') && at('notes') < at('help') && at('help') === parts.length - 1, parts.join(' | '))
  const bell = el.$('.hdr-notes')
  assert.equal(bell.getAttribute('aria-label'), en.notesTitle)
  assert.ok(bell.$('svg'), 'the bell')
  bell.click()
  assert.deepEqual(c.calls.at(-1), ['setDrawer', 'notes'])
  const help = el.$('.hdr-help > button')
  assert.equal(help.getAttribute('aria-haspopup'), 'menu')
  assert.equal(help.getAttribute('aria-label'), en.helpTitle)
  assert.ok(!el.$('.help-menu'), 'closed until clicked')
  const items = () => el.$$('.help-menu [role=menuitem]')
  help.click()
  await tick()
  // the topic Keyboard only while the shortcuts are on: off (the default), no key does anything
  const topics = ['rows', 'act', 'trust']
  assert.deepEqual(items().map(b => b.text()), [en.hints.button, ...topics.map(id => en.help.tabs[id]), en.tour.again])
  const keyed = mount(html`<${Header} s=${{ ...s, ui: { ...s.ui, shortcuts: true } }} c=${recorder()} />`)
  keyed.$('.hdr-help > button').click()
  await tick()
  assert.ok(keyed.$$('.help-menu [role=menuitem]').some(b => b.text() === en.help.tabs.keys), 'with the shortcuts on')
  assert.match(el.$('.help-menu').text(), new RegExp(en.settings.lookupTitle))
  const want = [['setHints', true], ...topics.map(id => ['openLookup', id]), ['tourStart']]
  for (let k = 0; k < want.length; k++) {
    if (!el.$('.help-menu')) { help.click(); await tick() }
    items()[k].click()
    await tick()
    assert.deepEqual(c.calls.at(-1), want[k], `item ${k}`)
    assert.ok(!el.$('.help-menu'), 'a pick closes the menu')
  }
})

test('notes drawer: the bell lists what the cockpit reported, newest first; an entry with a target goes there', async () => {
  const proto = Object.getPrototypeOf(document.body)
  proto.focus ??= function focus() { document.activeElement = this }
  proto.querySelector ??= function querySelector(sel) { try { return this.$(sel) } catch { return null } }
  const { NotesDrawer } = views.overlays
  const s = cockpitState(NOW, { ui: { drawer: 'notes' }, notes: [
    { at: '11:58', text: 'Plain note', tone: 'info', ms: 1 },
    { at: '11:59', text: 'Sent to demo-task', tone: 'ok', ms: 2, go: { kind: 'item', key: 'task:demo-task' } },
  ] })
  const c = recorder()
  const el = mount(html`<${NotesDrawer} s=${s} c=${c} />`)
  assert.deepEqual(el.$$('.note').map(n => n.text().includes('Sent to demo-task')), [true, false], 'newest first')
  el.$('button.note-go').click()
  assert.deepEqual(c.calls, [['setDrawer', null], ['openItem', 'task:demo-task', null]])
  const none = mount(html`<${NotesDrawer} s=${{ ...s, notes: [] }} c=${recorder()} />`)
  assert.match(none.text(), new RegExp(en.notesEmpty))
  for (const lang of ['en', 'de']) assert.ok(text.TABLES[lang].notesTitle && text.TABLES[lang].notesEmpty && text.TABLES[lang].helpTitle, lang)
  await tick()
})

test('header: while a fresh pass runs the as-of button waits; narrow, the header keeps the mark, the line below the time', () => {
  const busy = cockpitState(NOW, { loading: { pass: 'full', fresh: true, started_ms: NOW, eta_ms: 0, queued: null, last_error: null } })
  const b = mount(html`<${Header} s=${busy} c=${recorder()} />`).$('.hdr-asof button')
  assert.equal(b.getAttribute('aria-busy'), 'true')
  assert.ok(b.hasAttribute('disabled'), 'a second click starts no second pass')
  const narrow = cockpitState(NOW, { layout: 'narrow' })
  const c = recorder()
  const head = mount(html`<${Header} s=${narrow} c=${c} />`)
  const mark = head.$('.hdr-asof button')
  assert.ok(mark && mark.$('svg'), 'the mark stays in a narrow header')
  assert.equal(mark.$('.asof-text'), null)
  mark.click()
  assert.deepEqual(c.calls, [['reload']])
  const line = mount(html`<${views.overlays.MobileSwitch} s=${narrow} c=${c} />`).$('.mobile-status .hdr-asof button')
  assert.equal(line.$('.asof-text').text(), en.sourceAsOf(narrow.model.collected_at))
  line.click()
  assert.deepEqual(c.calls.at(-1), ['reload'])
})

// ---------------------------------------------------------------- what works where: header chip and sidebar counts

test('the header shows the working total from the mock sessions', () => {
  const s = cockpitState(NOW)
  const c = recorder()
  const chip = mount(html`<${Header} s=${s} c=${c} />`).$('.hdr-agents')
  // this Bridge's tabs: four busy sessions (round 4: one of them on a task it was recognised working on), five
  // subagents, two workflows (the paused one does not count); the session of another folder stands only in the tooltip
  assert.equal(chip.text(), en.header.working(4, 5, 2))
  assert.equal(chip.getAttribute('title'), en.header.workingTitle(4, 2))
  chip.click()
  assert.deepEqual(c.calls, [['setPage', '@sessions']])
  // nothing at work: no chip
  const idle = cockpitState(NOW, { sessions: { at_ms: NOW, sessions: [] } })
  assert.equal(mount(html`<${Header} s=${idle} c=${recorder()} />`).$('.hdr-agents'), null)
})

const { Sidebar } = views.rooms
const { roomsOf } = loadedRooms.logic
function renderSide(s, root = null) {
  const vnode = html`<${Sidebar} s=${s} c=${recorder()} rooms=${roomsOf(s)} here=${{ kind: 'chat' }} />`
  if (!root) return mount(vnode)
  loadedRooms.render(vnode, root)
  return root
}
const groupOf = (el, title) => el.$$('section.room-ws').find(g => g.$('.room-ws-title')?.text() === title) ?? null
const tabRow = (el, name) => el.$$('.room-tab').find(b => b.$('.room-name').text() === name) ?? null

test('a workspace group shows the sum of its tabs and a tab its own count', () => {
  const s = cockpitState(NOW)
  s.sessions = { at_ms: NOW, sessions: [
    { id: 'x1', status: 'busy', agents: { running_count: 2 }, workflows: [], tab: { ref: 'surface:9', ws_ref: 'workspace:3', workspace: 'Demo' } },
    { id: 'x2', status: 'idle', agents: { running_count: 1 }, workflows: [{ status: 'running', agents: 3 }, { status: 'paused' }],
      tab: { ref: 'surface:12', ws_ref: 'workspace:3', workspace: 'Demo' } },
    { id: 'x3', status: 'busy', agents: { running_count: 5 }, workflows: [], tab: null }] }
  const el = renderSide(s)
  const demo = groupOf(el, 'Demo')
  const head = demo.$('.room-ws-head .room-load')
  assert.equal(head.getAttribute('title'), en.rooms.loadTitle(1, 3, 1))
  assert.match(head.text(), new RegExp(`${en.rooms.subagents(3)}.*${en.rooms.workflows(1)}`))
  assert.equal(tabRow(el, 'notes').$('.room-load').getAttribute('title'), en.rooms.loadTitle(1, 2, 0))
  assert.equal(tabRow(el, 'demo-task research').$('.room-load').getAttribute('title'), en.rooms.loadTitle(0, 1, 1))
  assert.equal(tabRow(el, 'report-draft').$('.room-load'), null)                // nothing runs in it: no chip
  // the second workspace with the same title shares nothing of it, the session elsewhere stands nowhere
  const twins = el.$$('section.room-ws').filter(g => g.$('.room-ws-title')?.text() === 'Demo')
  assert.equal(twins.length, 2)
  assert.equal(twins[1].$('.room-load'), null)
  assert.equal(el.$$('.room-load').length, 3)
})

test('the sidebar keeps its order while the pointer is inside', async () => {
  const titles = el => el.$$('section.room-ws .room-ws-title').map(x => x.text())
  const s = cockpitState(NOW, { ui: { roomsSort: 'urgency' } })
  const el = renderSide(s)
  const before = titles(el)
  assert.equal(before[0], 'Ops')                                               // the tab that needs you leads
  el.$('nav').dispatch('pointerenter')
  // the Ops tab is answered and a Docs tab now asks: the order would change, the state words follow at once
  const next = { ...s, tabs: { ...s.tabs, tabs: s.tabs.tabs.map(t => t.ref === 'surface:7' ? { ...t, state: 'working' }
    : t.ref === 'surface:8' ? { ...t, state: 'needs-you' } : t) } }
  renderSide(next, el)
  assert.deepEqual(titles(el), before)
  assert.equal(tabRow(el, 'docs-refresh').$('.room-meta').text(), en.state['needs-you'])
  el.$('nav').dispatch('pointerleave')
  await new Promise(resolve => setTimeout(resolve, 0))
  assert.equal(titles(el)[0], 'Docs')
})

test('a click on the order toggle reorders at once, though the pointer is inside', () => {
  const titles = el => el.$$('section.room-ws .room-ws-title').map(x => x.text())
  const s = cockpitState(NOW)
  const el = renderSide(s)
  assert.match(titles(el)[0], /Control$/)                                       // the terminal's order: pinned first
  el.$('nav').dispatch('pointerenter')
  // the toggle sits inside the sidebar: its own click is the one change of order the hand asked for
  renderSide({ ...s, ui: { ...s.ui, roomsSort: 'urgency' } }, el)
  assert.equal(titles(el)[0], 'Ops')
  // and the new order holds again while the pointer stays
  const next = { ...s, ui: { ...s.ui, roomsSort: 'urgency' }, tabs: { ...s.tabs, tabs: s.tabs.tabs.map(t =>
    t.ref === 'surface:7' ? { ...t, state: 'working' } : t.ref === 'surface:8' ? { ...t, state: 'needs-you' } : t) } }
  renderSide(next, el)
  assert.equal(titles(el)[0], 'Ops')
})

test('the sidebar order picks the terminal order, the most urgent first or by status', () => {
  const c = recorder()
  const s = cockpitState(NOW)
  const el = mount(html`<${Sidebar} s=${s} c=${c} rooms=${roomsOf(s)} here=${{ kind: 'chat' }} />`)
  assert.equal(el.button(en.rooms.sortTerminal).getAttribute('aria-pressed'), 'true')
  assert.equal(el.button(en.rooms.sortUrgency).getAttribute('aria-pressed'), 'false')
  el.button(en.rooms.sortUrgency).click()
  el.button(en.rooms.sortStatus).click()
  assert.deepEqual(c.calls, [['setRoomsSort', 'urgency'], ['setRoomsSort', 'status']])
  const on = cockpitState(NOW, { ui: { roomsSort: 'status' } })
  assert.equal(renderSide(on).button(en.rooms.sortStatus).getAttribute('aria-pressed'), 'true')
})

test('by status the sidebar lists every tab under its status, the longest waiting first, with its workspace', () => {
  const s = cockpitState(NOW, { ui: { roomsSort: 'status' } })
  const el = renderSide(s)
  const groups = el.$$('section.room-status')
  // each heading: the status word and how many tabs stand under it
  assert.deepEqual(groups.map(g => g.$('h3').text()), [`${en.rooms.status['needs-you']} 1`, `${en.rooms.status.waiting} 3`,
    `${en.rooms.status.working} 3`, `${en.rooms.status.shell} 1`])
  assert.deepEqual(groups.map(g => g.$$('.room-tab .room-name').map(x => x.text())),
    [['alpha-release'], ['report-draft', 'demo-task research', 'changelog'], ['docs-refresh', 'docs search', 'notes'], ['zsh']])
  assert.equal(groups[1].$('.room-tab .room-meta').text(), 'Demo')          // the workspace in place of the state word
  assert.equal(el.$$('section.room-ws .room-ws-title').length, 0)           // no workspace groups in this order
  // the control session and the quick chats stay reachable below
  assert.ok(el.$$('.room-tab .room-name').some(x => / session$/.test(x.text())))
})

test('the order choice stands on top of the sidebar, and by status Waiting for you gives way to the groups', () => {
  const s = cockpitState(NOW, { guide: null })
  const el = renderSide(s)
  const side = el.$('nav')
  const at = node => side.childNodes.indexOf(node)
  assert.ok(at(el.$('.room-order')) < at(el.$('.reply-group')))               // reachable without scrolling past the asks
  const byStatus = renderSide(cockpitState(NOW, { guide: null, ui: { roomsSort: 'status' } }))
  assert.equal(byStatus.$('.reply-group'), null)                               // the same tabs stand under Needs you and Done
  assert.ok(byStatus.$('section.room-status'))
})

test('Work through on top of the sidebar opens the first tab that wants you, in every order', () => {
  for (const roomsSort of ['terminal', 'urgency', 'status']) {
    const s = cockpitState(NOW, { ui: { roomsSort } })
    const c = recorder()
    const el = mount(html`<${Sidebar} s=${s} c=${c} rooms=${roomsOf(s)} here=${{ kind: 'chat' }} />`)
    el.$('.room-order').$$('button').find(b => b.text() === en.rooms.walk(4)).click()
    assert.deepEqual(c.calls, [['startWalk']], roomsSort)
  }
  // nothing waits: no button
  const s = cockpitState(NOW)
  const calm = cockpitState(NOW, { tabs: { ...s.tabs, tabs: s.tabs.tabs.map(t => ({ ...t, state: 'working' })) } })
  assert.equal(renderSide(calm).$('.room-order').$$('button').some(b => b.text().startsWith(en.rooms.walk(0).split(' (')[0])), false)
})

const WALK = ['surface:7', 'surface:10', 'surface:12', 'surface:13']
const tabPane = (ref, c, over = {}) => mount(html`<${RoomsPage} s=${cockpitState(NOW, { ...over, ui: { room: { kind: 'tab', id: ref }, tabWalk: WALK, tabView: 'surface:99', ...(over.ui ?? {}) } })} c=${c} />`)

test('the open tab ends in the same bar the lists have: back, where you stand, what comes next and Next', () => {
  const c = recorder()
  const bar = tabPane('surface:10', c).$('.rooms-main .next-up')
  assert.equal(bar.$('.next-up-pos').text(), en.nextPos(2, 4))
  assert.equal(bar.$('.next-up-title').text(), 'demo-task research')
  assert.deepEqual(bar.$$('.next-up-later li').map(li => li.text()), ['changelog · Ops'])
  bar.button(en.nextOpen).click()
  bar.button(en.nextPrev).click()
  bar.$('.next-up-later button').click()
  assert.deepEqual(c.calls.filter(x => x[0] === 'walkTab'), [['walkTab', 'surface:12', { focus: true }], ['walkTab', 'surface:7', { focus: true }],
    ['walkTab', 'surface:13', { focus: true }]])
})

test('a tab outside the walk still shows the first that wants you as next', () => {
  const c = recorder()
  const bar = tabPane('surface:8', c).$('.rooms-main .next-up')                 // docs-refresh works: not in the walk
  assert.equal(bar.$('.next-up-pos'), null)
  assert.equal(bar.$('.next-up-title').text(), 'alpha-release')
})

test('an answer sent from the open tab goes on to the next one, a jump to the terminal does not', async () => {
  const c = recorder()
  const cc = new Proxy(c, { get: (o, p) => (p === 'reply' ? async (...a) => { o.calls.push(['reply', ...a]); return { ok: true } } : o[p]) })
  const el = tabPane('surface:12', cc, { guide: null })
  el.$('.reply-pane').button(en.reply.goOn).click()
  await tick()
  assert.deepEqual(c.calls.filter(x => x[0] === 'walkTab'), [['walkTab', 'surface:13']])
})

test('the open tab can be closed from its head, and the walk goes on', async () => {
  const c = recorder()
  const cc = new Proxy(c, { get: (o, p) => (p === 'act' ? async (...a) => { o.calls.push(['act', ...a]); return { ok: true } } : o[p]) })
  // round 6d: the one close of every place (TabClose); a tab with a draft in its prompt asks and keeps it
  assert.ok(!tabPane('surface:13', cc).$('.rooms-main .tabview-head .tab-close'))
  const el = tabPane('surface:10', cc)
  const close = () => el.$('.rooms-main .tabview-head .tab-close').$$('button')[0]
  assert.equal(close().text(), en.btnCloseTab)
  // its filed result stands on the screen beside the close: one click closes (round 6d fix, no second click here)
  close().click()
  await until(() => c.calls.some(x => x[0] === 'walkTab'))
  assert.deepEqual(c.calls.filter(x => x[0] === 'act' || x[0] === 'walkTab'), [['act', 'tab_close', { tab_ref: 'surface:10' }], ['walkTab', 'surface:12']])
})

test('the answer that tells a session to keep going says so, it is never read as the way to the next tab', () => {
  assert.equal(en.reply.goOn, '"Keep going"')
  assert.equal(text.TABLES.de.reply.goOn, '„Mach weiter“')
  assert.notEqual(text.TABLES.de.reply.goOn, text.TABLES.de.nextOpen)
})

test('6d C2: a waiting tab is a short entry, its dot, name and how long, and one line of where it stands; a click opens it, its answers stand only on the right', () => {
  const s = cockpitState(NOW, { guide: null })
  const c = recorder()
  const el = mount(html`<${Sidebar} s=${s} c=${c} rooms=${roomsOf(s)} here=${{ kind: 'chat' }} />`)
  const row = replyRow(el, 'demo-task research')
  // "waits" is the group's own heading, so the line does not say it again (walk of 28.10.)
  assert.deepEqual(row.$$('.room-meta').map(x => x.text()), ['11 min'])
  const tab = tabOf(s, 'surface:12')
  assert.equal(row.$('.room-lage').text(), loadedRooms.logic.waitLage(tab))
  assert.ok(loadedRooms.logic.waitLage(tab).includes(tab.ask.text.split('\n').find(Boolean).trim().slice(0, 20)), loadedRooms.logic.waitLage(tab))
  assert.equal(row.getAttribute('title'), tab.ask.text)
  // two tabs of the same name tell apart by their workspace and their last words
  const twin = { ref: 'surface:90', name: 'Claude Code', workspace: 'Home', state: 'waiting', last: 'Tests pass, ready to commit', ask: null }
  assert.notEqual(loadedRooms.logic.waitLage(twin), loadedRooms.logic.waitLage({ ...twin, workspace: 'Work', last: 'Which board?' }))
  assert.equal(loadedRooms.logic.waitLage(twin), 'Home · Tests pass, ready to commit')
  // nothing to answer in the list: no option, no yes, no field, no reading of the guide
  const group = el.$('.reply-group')
  // one button per row, the row itself; a quiet tab's close stands under its line (round 6d item 9), never an answer
  assert.equal(group.$$('button').length, replyRows(el).length, 'one button per row, the row itself')
  assert.equal(group.$('textarea'), null)
  assert.equal(group.$('.reply-ask'), null)
  assert.equal(group.$('.guide-line-about'), null)
  row.click()
  assert.deepEqual(c.calls.filter(x => x[0] === 'pickRoom'), [['pickRoom', { kind: 'tab', id: 'surface:12' }]])
  // in its workspace below it is a grey line that only says it waits; the others keep their state
  const own = tabRow(el, 'demo-task research')
  assert.ok(own.hasClass('is-dim'))
  assert.equal(own.$('.room-meta').text(), en.state.waiting)
  assert.ok(tabRow(el, 'alpha-release').hasClass('is-dim'))
  assert.equal(tabRow(el, 'alpha-release').$('.room-meta').text(), en.state.waiting)
  assert.ok(!tabRow(el, 'notes').hasClass('is-dim'))
  // by status there is no Waiting for you above, so nothing is greyed
  const byStatus = mount(html`<${Sidebar} s=${cockpitState(NOW, { ui: { roomsSort: 'status' } })} c=${recorder()} rooms=${roomsOf(s)} here=${{ kind: 'chat' }} />`)
  assert.equal(byStatus.$$('.room-tab.is-dim').length, 0)
})

// ---------------------------------------------------------------- what a tab waits for, answered from the page

const { TabReply } = views.reply
const replyRows = el => el.$$('.reply-group .room-wait')
const replyRow = (el, name) => replyRows(el).find(r => r.$('.room-name').text() === name) ?? null

test('the sidebar: a line of Waiting for you stays one line, its tab closes from the head on the right and the walk goes on', () => {
  // round 6d: C2 keeps each waiting tab to one line; a close under every line doubled the list (walk of 28.10.), so
  // the one close of every place stands in the open tab's head, which walks on to the next tab after it
  const s = cockpitState(NOW, { guide: null })
  s.tabs = { ...s.tabs, tabs: s.tabs.tabs.map(t => (t.ref === 'surface:12' ? { ...t, ask: null } : t)) }
  const el = mount(html`<${Sidebar} s=${s} c=${recorder()} rooms=${roomsOf(s)} here=${{ kind: 'chat' }} />`)
  assert.ok(replyRow(el, 'demo-task research'), 'the quiet tab is listed')
  assert.equal(el.$('.reply-group .tab-close'), null)
  const pane = mount(html`<${RoomsPage} s=${{ ...s, ui: { ...s.ui, room: { kind: 'tab', id: 'surface:12' }, tabView: 'surface:99' } }} c=${recorder()} />`)
  assert.ok(pane.$('.rooms-main .tabview-head .tab-close'))
})

test('the sidebar shows Waiting for you, the most urgent first, above the workspaces', () => {
  const s = cockpitState(NOW, { guide: null })
  const c = recorder()
  const el = mount(html`<${Sidebar} s=${s} c=${c} rooms=${roomsOf(s)} here=${{ kind: 'chat' }} />`)
  const group = el.$('.reply-group')
  assert.equal(group.$('h3').text(), en.reply.asks)
  // the most urgent first, the control tab never; the group stands above the workspaces
  assert.deepEqual(replyRows(el).map(r => r.$('.room-name').text()), ['alpha-release', 'report-draft', 'demo-task research', 'changelog'])
  const side = el.$('nav')
  const firstWs = el.$$('section.room-ws').find(x => !(x.getAttribute('class') ?? '').includes('room-asks'))
  assert.ok(side.childNodes.indexOf(group) < side.childNodes.indexOf(firstWs))
  assert.equal(replyRow(el, 'alpha-release').$('.room-meta').text(), en.state['needs-you'])
  // the tab's own row in its workspace reads the question as its title
  assert.equal(tabRow(el, 'demo-task research').getAttribute('title'), tabOf(s, 'surface:12').ask.text)
})

test('a tab_moved answer keeps the draft and shows the note', async () => {
  const s = cockpitState(NOW)
  const tab = tabOf(s, 'surface:12')
  const sent = []
  let answer = { refused: true, error: { code: 'tab_moved', message: 'moved', field: null } }
  const c = new Proxy({}, { get: (_, p) => p === 'reply' ? (...a) => { sent.push(a); return Promise.resolve(answer) }
    : p === 'then' ? undefined : () => undefined })
  const el = mount(html`<${TabReply} tab=${tab} s=${s} c=${c} />`)
  const box = el.$('textarea')
  box.value = 'yes, all three'
  box.dispatch('input')
  await tick()
  el.button(en.reply.send).click()
  await tick()
  assert.deepEqual(sent[0].slice(0, 2), ['tab_send', { tab_ref: 'surface:12', text: 'yes, all three', expect: 'waiting', seen: tab.ask.hash,
    name: 'demo-task research' }])
  assert.equal(el.$('.reply-note').text(), en.errors.tab_moved)
  assert.equal(el.$('textarea').value, 'yes, all three')
  // a draft in the tab: the same, in its own words
  answer = { refused: true, error: { code: 'tab_draft', message: 'draft', field: null } }
  el.button(en.reply.send).click()
  await tick()
  assert.equal(el.$('.reply-note').text(), en.errors.tab_draft)
  assert.equal(el.$('textarea').value, 'yes, all three')
})

test('a row that left stays greyed for one poll', () => {
  const s = cockpitState(NOW)
  const el = renderSide(s)
  const moved = { ...s, tabs: { ...s.tabs, at_ms: s.tabs.at_ms + 3000,
    tabs: s.tabs.tabs.map(t => t.ref === 'surface:12' ? { ...t, state: 'working', waiting: false, ask: null } : t) } }
  renderSide(moved, el)
  // still where it stood, greyed, saying it moved on
  assert.deepEqual(replyRows(el).map(r => r.$('.room-name').text()), ['alpha-release', 'report-draft', 'demo-task research', 'changelog'])
  const row = replyRow(el, 'demo-task research')
  assert.ok(row.hasClass('is-left'))
  assert.equal(row.$('.room-meta').text(), en.reply.movedOn)
  // answered from here, it says so, and what the answer was on its title
  renderSide({ ...moved, ui: { ...moved.ui, answered: { 'surface:12': { hash: tabOf(s, 'surface:12').ask.hash, q: 'Yes' } } } }, el)
  assert.equal(replyRow(el, 'demo-task research').$('.room-meta').text(), en.reply.answeredWord)
  assert.equal(replyRow(el, 'demo-task research').getAttribute('title'), en.reply.answered('Yes'))
  // the next poll: gone
  renderSide({ ...moved, tabs: { ...moved.tabs, at_ms: moved.tabs.at_ms + 3000 } }, el)
  assert.equal(replyRow(el, 'demo-task research'), null)
  assert.equal(replyRows(el).length, 3)
})

test('TabView renders the shared TabReply', async () => {
  const proto = Object.getPrototypeOf(document.body)
  proto.focus ??= function focus() { document.activeElement = this }
  proto.querySelector ??= function querySelector(sel) { return this.$(sel) }
  const s = cockpitState(NOW, { ui: { tabView: 'surface:7' } })
  const c = recorder()
  const root = mount(html`<${views.tabs.TabView} s=${s} c=${c} />`)
  try {
    const ask = tabOf(s, 'surface:7').ask
    for (const o of ask.options) assert.ok(root.button(o.label), o.label)
    // the dialog's own words, never a bare yes and no beside them
    assert.equal(root.$$('button').filter(b => b.text() === en.btnNo).length, 0)
    root.button(ask.options[2].label).click()
    assert.deepEqual(c.calls.at(-1).slice(0, 3), ['reply', 'tab_option', { tab_ref: 'surface:7', n: 3, seen: ask.hash, name: 'alpha-release' }])
    // a waiting tab: yes, no and go on above the view's own message box, which stays the one box
    const research = mount(html`<${views.tabs.TabView} s=${cockpitState(NOW, { ui: { tabView: 'surface:12' } })} c=${recorder()} />`)
    try {
      assert.ok(research.button(en.reply.yes) && research.button(en.reply.goOn))
      assert.equal(research.$$('textarea').length, 1)
    } finally {
      loadedRooms.render(null, research)
    }
  } finally {
    loadedRooms.render(null, root)
  }
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

// ---------------------------------------------------------------- the work tab's day list

const { DayColumn } = views.day
const dayOf = (over = {}) => {
  const s = cockpitState(NOW, over)
  return { el: mount(html`<${DayColumn} s=${s} c=${recorder()} byKey=${logicIndex(s)} />`), s }
}
const logicIndex = s => loadedLogic.indexRows(s.model)
const { logic: loadedLogic } = await loadCockpit()
const rowOf = (el, key) => el.$$('li.row').find(li => li.getAttribute('data-key') === key)

test('day list: Haiku says what a row is about under its title and labels the kind of work', () => {
  const { el } = dayOf()
  const demo = rowOf(el, 'task:demo-task')
  assert.equal(demo.$('.row-gist').text(), 'A setup guide for new team members')
  assert.equal(demo.$('.chip-topic').text(), en.topic.docs)
  // a gist that only repeats the title adds nothing and stays away
  assert.equal(rowOf(el, 'inbox:20261009-0915-update-docs-e5f6')?.$('.row-gist') ?? null, null)
})

test('day list: a due date stands once and relative, an overdue one in red', () => {
  const { el } = dayOf({ ui: { expanded: { give: true } } })
  const docs = rowOf(el, 'inbox:20261009-0915-update-docs-e5f6')
  const due = docs.$('.meta-due')
  assert.equal(due.text(), en.dueOverdue(3))
  assert.ok(due.hasClass('tk-danger'), due.getAttribute('class'))
  assert.doesNotMatch(docs.$('.meta-why').text(), /\bdue\b/)            // the why no longer repeats it
  assert.match(docs.$('.meta-why').text(), /changed since 08:40/)
  assert.equal(rowOf(el, 'inbox:20261009-0900-review-demo-a1b2').$('.meta-due').text(), en.dueTomorrow)
})

test('day list: board and tracker rows stand in their own folded section after the tasks', () => {
  const { el } = dayOf()
  const titles = el.$$('h2.sec-title').map(h => h.text().replace(/\d+$/, '').trim())
  assert.deepEqual(titles, [en.section.now, en.section.give, en.section.work, en.section.track, en.section.later])
  assert.equal(rowOf(el, 'ref:example/repo#12'), undefined)
  const shown = dayOf({ ui: { expanded: { track: true } } }).el
  assert.ok(rowOf(shown, 'ref:example/repo#12'))
})

test('day list: a section fills up to the rows the column has room for, never past what it holds', () => {
  const s = cockpitState(NOW)
  const byKey = loadedLogic.indexRows(s.model)
  const work = s.model.sections.find(x => x.id === 'work')
  assert.deepEqual(loadedLogic.sectionRows(work, false, byKey).map(r => r.key), work.compact)
  assert.deepEqual(loadedLogic.sectionRows(work, false, byKey, 10).map(r => r.key), work.rows.map(r => r.key))
  assert.deepEqual(loadedLogic.sectionRows(work, false, byKey, 1).map(r => r.key), work.compact)   // the compact rows always stand
})

// ---------------------------------------------------------------- Toasts and row steps (#391)

// the overlays and the row steps from a copy of scripts/web of their own, rendered with that copy's Preact
const extra = await (async () => {
  const fs = await import('node:fs')
  const os = await import('node:os')
  const path = await import('node:path')
  const { fileURLToPath, pathToFileURL } = await import('node:url')
  const web = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'bridge-cockpit-render-391-')), 'web')
  process.on('exit', () => fs.rmSync(path.dirname(web), { recursive: true, force: true }))
  fs.cpSync(path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'web'), web, { recursive: true })
  fs.writeFileSync(path.join(web, 'package.json'), '{ "type": "module" }\n')
  const load = rel => import(pathToFileURL(path.join(web, rel)).href)
  return { ...(await load('vendor/htm-preact-3.1.1.module.js')), overlays: await load('views/overlays.js'),
    pages: await load('views/pages.js'), logic: await load('logic.js') }
})()

function mountExtra(vnode) {
  const root = document.createElement('div')
  extra.render(vnode, root)
  return root
}

test('toasts: hover and focus inside a toast hold its timer, leaving lets it run again', () => {
  const s = cockpitState(NOW, { toasts: [
    { id: 7, text: 'Closed the task', tone: 'ok', at: '12:00', action: 'undo', undo: [{ undo: { verb: 'task_reopen' } }] },
  ] })
  const c = recorder()
  const el = mountExtra(extra.html`<${extra.overlays.Toasts} s=${s} c=${c} />`)
  const toast = el.$('.toast')
  toast.dispatch('mouseenter')
  toast.dispatch('mouseleave')
  el.button(en.undoToast).dispatch('focusin')
  el.button(en.undoToast).dispatch('focusout')
  assert.deepEqual(c.calls, [['pauseToast', 7, 'hover'], ['resumeToast', 7, 'hover'], ['pauseToast', 7, 'focus'], ['resumeToast', 7, 'focus']])
})

test('row steps: a busy row action disables only its own row', () => {
  const s = cockpitState(NOW, { ui: { busy: { [extra.logic.rowActionKey({ page: 'p', section: 'sec', index: 1 })]: 'row_action' } } })
  const row = index => ({ index, row_id: `r${index}`, actions: [{ id: 'follow', label: 'Followed up' }] })
  const steps = index => mountExtra(extra.html`<${extra.pages.RowSteps} it=${row(index)} page="p" section="sec" s=${s} c=${recorder()} />`)
  assert.equal(steps(1).$('button').hasAttribute('disabled'), true, 'the row in flight waits')
  assert.equal(steps(2).$('button').hasAttribute('disabled'), false, 'another row stays free')
})

test('row steps as buttons: every step stands as its own button and runs on the second click', async () => {
  const redraw = () => new Promise(r => setTimeout(r, 20))   // a click's state lands on the next render
  const s = cockpitState(NOW)
  const c = recorder()
  const it = { index: 3, row_id: 'pc:lab', actions: [{ id: 'wake', label: 'Switch on' }, { id: 'shutdown', label: 'Switch off' }] }
  const el = mountExtra(extra.html`<${extra.pages.RowSteps} it=${it} page="p" section="sec" s=${s} c=${c} as="buttons" />`)
  assert.deepEqual(el.$$('button').map(b => b.text()), ['Switch on', 'Switch off'], 'no menu in front of the steps')
  el.button('Switch off').dispatch('click')
  await redraw()
  assert.deepEqual(c.calls, [], 'the first click only asks')
  assert.ok(el.$$('button').some(b => b.text() === en.stepConfirm('Switch off')), 'the armed button says what a second click does')
  el.button(en.stepConfirm('Switch off')).dispatch('click')
  assert.deepEqual(c.calls, [['act', 'row_action', { page: 'p', section: 'sec', index: 3, action: 'shutdown' }]])
})

test('row steps as buttons: a busy row disables its buttons', () => {
  const s = cockpitState(NOW, { ui: { busy: { [extra.logic.rowActionKey({ page: 'p', section: 'sec', index: 1 })]: 'row_action' } } })
  const it = { index: 1, row_id: 'r1', actions: [{ id: 'wake', label: 'Switch on' }] }
  const el = mountExtra(extra.html`<${extra.pages.RowSteps} it=${it} page="p" section="sec" s=${s} c=${recorder()} as="buttons" />`)
  assert.equal(el.$('button').hasAttribute('disabled'), true)
})

// ---------------------------------------------------------------- the dates page shows time only (views/dates.js)

// a day n days after NOW as the server writes it, and one event on it at `hour`
const calDay = n => { const d = new Date(2026, 9, 9 + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}` }
const calEvent = (index, n, hour, more = {}) => ({ index, title: `Date ${index}`, cal: { start: `${calDay(n)}T${hour}:00`, end: `${calDay(n)}T${hour}:30`,
  day: calDay(n), minutes: 30, all_day: false, calendar: 'Work', info: false, where: null, online: false, people: [], past: false, running: false,
  overlaps: [], ...more } })

/** A dates page with these events and, beside the calendar, a section of due rows (overdue and due this week) */
function renderDates(events) {
  const cal = { id: 'calendar', kind: 'calendar', view: 'agenda', title: 'Calendar', status: 'ok', items: events, count: events.length, total: events.length,
    cal_figures: { today: 2, busy_today: 60, tomorrow: 1, week: 3, overlaps: 1, info_week: 0, day_start: 8, day_end: 20,
      next: { start: `${calDay(0)}T14:00`, title: 'Date 1' }, free_today: { minutes: 90, from: `${calDay(0)}T15:00` } } }
  const due = { id: 'deadlines', kind: 'command', title: 'Deadlines', status: 'ok', count: 2, total: 2,
    items: [{ index: 0, title: 'Slides', due_at: calDay(-2) }, { index: 1, title: 'Offer', due_at: calDay(3) }] }
  const page = { id: 'dates', title: 'Dates', sections: [cal, due] }
  const c = recorder()
  return { el: mount(html`<${views.pages.PageSection} page=${page} section=${cal} s=${cockpitState(NOW)} c=${c} />`), c }
}

test('dates: two figures at most, the overlaps and the free block today; no day counts, no next date, no due rows of the page', () => {
  const { el } = renderDates([calEvent(0, 0, 14, { overlaps: ['Date 1'] }), calEvent(1, 0, 14, { overlaps: ['Date 0'] }), calEvent(2, 1, 9)])
  assert.deepEqual(el.$$('.calf-label').map(x => x.text()), [en.cal.fig.overlaps, en.cal.fig.free])
  assert.ok(!el.$('.calf-title'), 'no tile names the next date')
})

test('dates: the overlaps figure still filters the agenda', async () => {
  const { el } = renderDates([calEvent(0, 0, 14, { overlaps: ['Date 1'] }), calEvent(1, 0, 14, { overlaps: ['Date 0'] }), calEvent(2, 1, 9)])
  assert.equal(el.$$('.cal-row').length, 3)
  el.$$('.calf-tile')[0].click()
  await new Promise(r => setTimeout(r, 20))
  assert.deepEqual(el.$$('.cal-row .cal-title').map(x => x.text().trim()), ['Date 0', 'Date 1'])
})

test('dates: the month view stands once the loaded dates span four weeks; a month kept in the browser shows the agenda till then', () => {
  const modes = el => el.$$('.ghb-mode-btn').map(b => b.text())
  const short = [calEvent(0, 0, 9), calEvent(1, 26, 9)]   // 27 days, today included
  const long = [calEvent(0, 0, 9), calEvent(1, 27, 9)]    // 28 days
  assert.deepEqual(modes(renderDates(short).el), [en.cal.views.agenda, en.cal.views.week])
  assert.deepEqual(modes(renderDates(long).el), [en.cal.views.agenda, en.cal.views.week, en.cal.views.month])
  const had = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
  const kept = []
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, writable: true,
    value: { getItem: () => 'month', setItem: (k, v) => kept.push([k, v]) } })
  try {
    const hidden = renderDates(short).el
    assert.ok(!!hidden.$('.cal-agenda') && !hidden.$('.cal-month'), 'the agenda while the month is hidden')
    assert.ok(!!renderDates(long).el.$('.cal-month'), 'the month once four weeks are loaded')
    assert.deepEqual(kept, [], 'hiding the month does not overwrite the kept choice')
  } finally {
    if (had) Object.defineProperty(globalThis, 'localStorage', had)
    else delete globalThis.localStorage
  }
})

// ---------------------------------------------------------------- quick_live: only the chat re-renders (#400)

/** views/chat.js and the vendored Preact from a copy of their own (cockpit_render.mjs loads other views) */
async function loadChat() {
  const fs = await import('node:fs')
  const os = await import('node:os')
  const path = await import('node:path')
  const { fileURLToPath, pathToFileURL } = await import('node:url')
  const web = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'bridge-cockpit-chat-')), 'web')
  process.on('exit', () => fs.rmSync(path.dirname(web), { recursive: true, force: true }))
  fs.cpSync(path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'web'), web, { recursive: true })
  fs.writeFileSync(path.join(web, 'package.json'), '{ "type": "module" }\n')
  const load = rel => import(pathToFileURL(path.join(web, rel)).href)
  return { vendor: await load('vendor/htm-preact-3.1.1.module.js'), chat: await load('views/chat.js'), logic: await load('logic.js') }
}

const settle = () => new Promise(r => setTimeout(r, 20))

test('quick_live: a piece of an answer re-renders the chat thread, never the page around it', async () => {
  const { vendor, chat, logic } = await loadChat()
  const { html: h, useLayoutEffect: layout, useState: state } = vendor
  const conv = { id: 'q0123456789', kind: 'free', started_ms: NOW, session: null, total_usd: 0, running: true, last_ms: NOW,
    turns: [{ q: 'how far?', a: null, model_asked: 'haiku', model: null, cost_usd: null, at_ms: NOW, error: null }] }
  // the page's root as components.js App holds it: the store's state, a new render on every store change
  let s0 = cockpitState(NOW)
  const subs = new Set()
  const store = { get: () => s0, set(fn) { s0 = fn(s0); for (const f of subs) f(s0) } }
  let pageRenders = 0
  function Page() { pageRenders += 1; return h`<p class="page">page</p>` }
  function Root() {
    const [s, setS] = state(store.get())
    layout(() => { subs.add(setS); return () => subs.delete(setS) }, [])
    return h`<div><${Page} s=${s} /><div class="thread"><${chat.ChatThread} s=${s} conv=${conv} /></div></div>`
  }
  const el = document.createElement('div')
  vendor.render(h`<${Root} />`, el)          // with the copy's own Preact, whose hooks the chat uses
  await settle()
  const before = pageRenders
  const { quickLive } = chat
  quickLive.set(logic.applyQuickLive(quickLive.get(), { conv: conv.id, seq: 1, at: 0, text: 'Seven ', doing: null }))
  await settle()
  quickLive.set(logic.applyQuickLive(quickLive.get(), { conv: conv.id, seq: 2, at: 6, text: 'of eleven.', doing: null }))
  await settle()
  assert.equal(el.$('.thread .qa').text(), 'Seven of eleven.')
  assert.equal(pageRenders, before, 'the page did not render again')
  // and the counter would see it: a change in the store renders the page
  store.set(s => ({ ...s, now: NOW + 1 }))
  await settle()
  assert.equal(pageRenders, before + 1)
  quickLive.set(logic.applyQuickLive(quickLive.get(), { conv: conv.id, text: null, doing: null }))
  await settle()
  assert.equal(el.$('.thread .qa'), null)
  vendor.render(null, el)
})

// ---------------------------------------------------------------- the tab view's screen poll (#387)

const { render } = await loadCockpit()

test('tab view poll: an unchanged screen is not stored again and the next read comes later', async t => {
  const { useTabScreen } = views.tabs
  await new Promise(done => setTimeout(done, 150))   // effects the tests before left queued run on real timers first
  t.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: NOW })
  const saved = document.visibilityState
  document.visibilityState = 'visible'
  t.after(() => { document.visibilityState = saved })
  const first = { ok: true, ref: 'surface:7', text: '> hi', hash: 'aa11' }
  const idle = { ok: true, ref: 'surface:7', unchanged: true, hash: 'aa11' }
  const answers = [first, idle, idle, idle, { ok: true, ref: 'surface:7', text: '> hi\n⏺ ok', hash: 'bb22' }, idle]
  const asked = []
  const c = { tabScreen: (ref, since) => { asked.push({ at: Date.now(), since }); return Promise.resolve({ ok: true, data: answers.shift() }) } }
  const held = []
  function Probe() { const { screen } = useTabScreen(c, 'surface:7'); held.push(screen); return null }
  const flush = async () => { for (let i = 0; i < 5; i++) await Promise.resolve() }
  const root = mount(html`<${Probe} />`)
  t.after(() => render(null, root))
  // in steps of 50 ms, the answers settling in between, until the six reads went out
  for (let ms = 0; asked.length < 6 && ms < 60000; ms += 50) { t.mock.timers.tick(50); await flush() }
  await flush()
  assert.deepEqual(asked.map(a => a.since), [undefined, 'aa11', 'aa11', 'aa11', 'aa11', 'bb22'])
  const gaps = asked.slice(1).map((a, i) => a.at - asked[i].at)
  assert.ok(gaps[1] > gaps[0] && gaps[2] > gaps[1], `the poll slows while idle: ${gaps}`)
  assert.ok(gaps[4] < gaps[3], `a change brings the fast pace back: ${gaps}`)
  // the screen objects the hook handed out: null, the first screen, then the change, nothing in between
  const distinct = held.filter((x, i) => i === 0 || x !== held[i - 1])
  assert.deepEqual(distinct.map(x => x?.hash ?? null), [null, 'aa11', 'bb22'])
})

test('a tab that runs for an hour stands in Waiting for you without claiming it waits', () => {
  const s = cockpitState(NOW)
  const long = { ...s, tabs: { ...s.tabs, tabs: s.tabs.tabs.map(t => t.ref === 'surface:8'
    ? { ...t, state: 'working', waiting: false, long: 'working', last: '', ask: null } : t) } }
  const el = renderSide(long)
  const name = tabOf(long, 'surface:8').name
  const row = replyRow(el, name)
  assert.ok(row, 'the long runner is listed')
  assert.equal(row.$('.room-meta').text(), en.state.working)
  assert.ok(!tabRow(el, name).hasClass('is-dim'), 'it works, so its own row keeps saying so')
  // a tab that waits and whose question cannot be read says so where it is answered, on the right
  const blind = { ...s, tabs: { ...s.tabs, tabs: s.tabs.tabs.map(t => t.ref === 'surface:12' ? { ...t, ask: null, last: '' } : t) }, guide: null,
    ui: { ...s.ui, room: { kind: 'tab', id: 'surface:12' }, tabView: 'surface:99' } }
  assert.match(mount(html`<${RoomsPage} s=${blind} c=${recorder()} />`).$('.reply-pane .reply-ask').text(), new RegExp(en.reply.unreadable))
})

const { RoomsPage } = views.rooms
const keydown = (el, key) => el.dispatch('keydown', { key })
function typeInto(input, value) {
  input.value = value
  input.dispatch('input')
}

test('the rename field replaces the item, saves through tab_rename and workspace_rename and Esc cancels', () => {
  // a tab: its row in the sidebar is the field while it is renamed, not a field inside a button
  const s = cockpitState(NOW, { ui: { renaming: { kind: 'tab', id: 'surface:11' } } })
  const c = recorder()
  const el = mount(html`<${Sidebar} s=${s} c=${c} rooms=${roomsOf(s)} here=${{ kind: 'chat' }} />`)
  assert.ok(tabRow(el, 'zsh') === null, 'the tab row is replaced by the field')
  const input = el.$('.room-rename input')
  assert.ok(input, 'the field stands where the tab was')
  assert.equal(input.getAttribute('aria-label'), en.rooms.renameTab)
  assert.equal(el.$$('button .room-rename').length + el.$$('button input').length, 0)
  typeInto(input, '   ')
  keydown(input, 'Enter')
  assert.deepEqual(c.calls.filter(x => x[0] === 'act'), [])                       // empty is refused, nothing sent
  typeInto(input, '  Scratch pad ')
  keydown(input, 'Enter')
  assert.deepEqual(c.calls.filter(x => x[0] === 'act'), [['act', 'tab_rename', { tab_ref: 'surface:11', title: 'Scratch pad' }]])
  keydown(input, 'Escape')
  assert.deepEqual(c.calls.at(-1), ['stopRename'])
  // the Save and Cancel buttons do the same
  el.button(en.rooms.cancel).click()
  assert.deepEqual(c.calls.at(-1), ['stopRename'])

  // a workspace: its head is the field
  const w = cockpitState(NOW, { ui: { renaming: { kind: 'ws', id: 'workspace:4' } } })
  const cw = recorder()
  const side = mount(html`<${Sidebar} s=${w} c=${cw} rooms=${roomsOf(w)} here=${{ kind: 'chat' }} />`)
  const docs = side.$$('section.room-ws').find(g => g.$('.room-rename'))
  assert.ok(docs && docs.$('.room-ws-head') === null, 'the head is replaced by the field')
  assert.equal(docs.$$('.room-tab').length, 3)                                     // its tabs stay
  const wsInput = docs.$('.room-rename input')
  assert.equal(wsInput.getAttribute('aria-label'), en.rooms.renameWs)
  typeInto(wsInput, 'Writing')
  side.button(en.rooms.save).click()
  assert.deepEqual(cw.calls.filter(x => x[0] === 'act'), [['act', 'workspace_rename', { ws_ref: 'workspace:4', title: 'Writing' }]])
})

test('a double click on a title opens the rename field once, and only where a rename is allowed', () => {
  const s = cockpitState(NOW)
  const c = recorder()
  const el = mount(html`<${Sidebar} s=${s} c=${c} rooms=${roomsOf(s)} here=${{ kind: 'chat' }} />`)
  const zsh = tabRow(el, 'zsh')
  zsh.dispatch('click', { detail: 1 })
  zsh.dispatch('click', { detail: 2 })
  zsh.dispatch('dblclick')
  assert.deepEqual(c.calls, [['pickRoom', { kind: 'tab', id: 'surface:11' }], ['startRename', 'tab', 'surface:11']])
  // a task tab keeps its name: a double click opens nothing (its pane says why)
  const task = tabRow(el, 'alpha-release')
  c.calls.length = 0
  task.dispatch('dblclick')
  assert.deepEqual(c.calls, [])
  groupOf(el, 'Docs').$('.room-ws-head').dispatch('dblclick')
  assert.deepEqual(c.calls, [['startRename', 'ws', 'workspace:4']])
})

test('the tab and the workspace pane carry a pencil that opens the rename', () => {
  const pane = (room, over = {}) => {
    const s = cockpitState(NOW, { ui: { room, tabView: 'surface:99', ...over } })
    const c = recorder()
    return { el: mount(html`<${RoomsPage} s=${s} c=${c} />`), c }
  }
  const tab = pane({ kind: 'tab', id: 'surface:11' })
  tab.el.$('.tabview-head').button(en.rooms.rename).click()
  assert.deepEqual(tab.c.calls.filter(x => x[0] === 'startRename'), [['startRename', 'tab', 'surface:11']])
  const task = pane({ kind: 'tab', id: 'surface:7' })
  assert.ok(task.el.$('.tabview-head').button(en.rooms.rename) === null, 'no pencil on a task tab')
  assert.equal(task.el.$('#room-title').getAttribute('title'), en.rooms.taskName)
  const ws = pane({ kind: 'ws', id: 'workspace:4' })
  ws.el.$('.tabview-head').button(en.rooms.rename).click()
  assert.deepEqual(ws.c.calls.filter(x => x[0] === 'startRename'), [['startRename', 'ws', 'workspace:4']])
  // without the driver's verb, no pencil
  const none = pane({ kind: 'ws', id: 'workspace:4' })
  assert.ok(none.el)
  const s = cockpitState(NOW, { ui: { room: { kind: 'ws', id: 'workspace:4' } }, driver: { caps: ['tabs', 'rename'] } })
  const el = mount(html`<${RoomsPage} s=${s} c=${recorder()} />`)
  assert.ok(el.$('.tabview-head').button(en.rooms.rename) === null, 'no pencil without the cap')
})

test('the demo renames a free tab and a workspace and refuses what the server refuses', async () => {
  const { mock } = loadedRooms
  const tr = mock.createMockTransport({ lang: 'en', latency: 0 })
  const events = []
  tr.events(new Proxy({}, { get: (_, name) => p => events.push([name, p]) }), () => {})
  const act = (verb, args) => tr.post('/api/action', { verb, args })
  assert.equal((await act('tab_rename', { tab_ref: 'surface:7', title: 'Mine' })).error.code, 'task_tab_name')
  assert.equal((await act('tab_rename', { tab_ref: 'surface:9', title: 'Mine' })).error.code, 'rename_loses_state')
  assert.equal((await act('tab_rename', { tab_ref: 'surface:11', title: 'notes' })).error.code, 'name_in_use')
  assert.equal((await act('workspace_rename', { ws_ref: 'workspace:1', title: 'Mine' })).error.code, 'control_tab')
  assert.equal((await act('tab_rename', { tab_ref: 'surface:11', title: 'Scratch' })).ok, true)
  assert.equal((await act('workspace_rename', { ws_ref: 'workspace:4', title: 'Writing' })).ok, true)
  const st = (await tr.get('/api/state')).data
  assert.equal(st.tabs.tabs.find(t => t.ref === 'surface:11').name, 'Scratch')
  assert.equal(st.tabs.workspaces.find(w => w.ref === 'workspace:4').title, 'Writing')
  assert.ok(st.tabs.tabs.filter(t => t.ws_ref === 'workspace:4').every(t => t.workspace === 'Writing'))
  assert.ok(st.driver.caps.includes('rename_workspace'))
  assert.ok(events.some(([name]) => name === 'tabs'))
})

// ---------------------------------------------------------------- organize with AI

const { OrganizeView } = views.organize
const ORG_ITEMS = [
  { id: 'ws_color:workspace:2', kind: 'ws_color', ref: 'workspace:2', from: null, to: 'Teal', why: 'One colour for the releases', cap: 'set_color' },
  { id: 'tab_title:surface:9', kind: 'tab_title', ref: 'surface:9', from: 'release', to: 'Release notes', why: 'Says what it holds', cap: 'rename' },
  { id: 'ws_title:workspace:4', kind: 'ws_title', ref: 'workspace:4', from: 'Docs', to: 'Writing', why: 'Clearer', cap: 'rename_workspace' },
]
const orgState = organize => cockpitState(NOW, { ui: { organize } })

test('the organize view shows the scope, from and to with a checkbox per item and the result counts', () => {
  const busy = mount(html`<${OrganizeView} s=${orgState({ busy: true, proposal: null, ticks: {} })} c=${recorder()} />`)
  assert.ok(busy.text().includes(en.organize.thinking))
  const proposal = { id: 'o0123456789', at_ms: NOW, scope: 3, items: ORG_ITEMS }
  const c = recorder()
  const el = mount(html`<${OrganizeView} s=${orgState({ busy: false, proposal, ticks: {} })} c=${c} />`)
  assert.ok(el.text().includes(en.organize.scope(3)))
  assert.ok(el.text().includes(en.organize.hint))
  const rows = el.$$('.org-item')
  assert.equal(rows.length, 3)
  assert.ok(rows.every(r => r.$('input[type="checkbox"]') && !r.$('input[type="checkbox"]').hasAttribute('checked')))
  const title = rows.find(r => r.text().includes('Release notes'))
  assert.equal(title.$('s').text(), 'release')
  assert.ok(title.text().includes(en.organize.kinds.tab_title) && title.text().includes('Says what it holds'))
  // nothing ticked: apply is off; a tick, a group tick and tick all go to the controller
  assert.ok(el.button(en.organize.apply(0)).hasAttribute('disabled'))
  title.$('input[type="checkbox"]').dispatch('change')
  el.button(en.organize.tickAll).click()
  el.$$('.org-group-tick input')[0].dispatch('change')
  assert.deepEqual(c.calls.map(x => x[0]), ['organizeToggle', 'organizeTickAll', 'organizeTickGroup'])
  // ticked items: apply sends them
  const ticked = mount(html`<${OrganizeView} s=${orgState({ busy: false, proposal, ticks: { 'ws_title:workspace:4': true } })} c=${c} />`)
  ticked.button(en.organize.apply(1)).click()
  assert.deepEqual(c.calls.at(-1), ['organizeApply'])
  ticked.button(en.organize.close).click()
  assert.deepEqual(c.calls.at(-1), ['organizeClose'])
  // nothing to improve
  const none = mount(html`<${OrganizeView} s=${orgState({ busy: false, proposal: { ...proposal, items: [] }, ticks: {} })} c=${recorder()} />`)
  assert.ok(none.text().includes(en.organize.none))
  // after apply: the counts and the lists
  const result = { applied: ['ws_title:workspace:4'], skipped: [{ id: 'tab_title:surface:9', why: 'changed' }],
    failed: [{ id: 'ws_color:workspace:2', error: 'driver_failed', detail: 'cmux refused' }] }
  const done = mount(html`<${OrganizeView} s=${orgState({ busy: false, proposal, ticks: {}, result })} c=${recorder()} />`)
  for (const line of [en.organize.applied(1), en.organize.skipped(1), en.organize.failed(1)]) assert.ok(done.text().includes(line), line)
  // what the terminal said stays out of the text, at most in a tooltip
  assert.ok(done.text().includes(en.organize.errors.driver_failed))
  assert.ok(!done.text().includes('cmux refused'))
})

test('the organize result says in words why an item failed or was skipped, never a code', () => {
  const proposal = { id: 'o0123456789', at_ms: NOW, scope: 3, items: ORG_ITEMS }
  const result = { applied: [], skipped: [{ id: 'tab_title:surface:9', why: 'last_tab' }],
    failed: [{ id: 'ws_color:workspace:2', error: 'timeout' }, { id: 'ws_title:workspace:4', error: 'driver_cannot' }] }
  const el = mount(html`<${OrganizeView} s=${orgState({ busy: false, proposal, ticks: {}, result })} c=${recorder()} />`)
  const text = el.text()
  for (const words of [en.organize.errors.timeout, en.organize.errors.driver_cannot, en.organize.why.last_tab]) assert.ok(text.includes(words), words)
  assert.ok(!/: (timeout|driver_cannot)\b/.test(text))
  assert.ok(text.includes(en.organize.skippedAny(1)))
})

test('the sidebar offers Organize with AI with the rename cap and keeps it off while it runs', () => {
  const c = recorder()
  const s = cockpitState(NOW)
  const el = mount(html`<${Sidebar} s=${s} c=${c} rooms=${roomsOf(s)} here=${{ kind: 'chat' }} />`)
  el.button(en.organize.button).click()
  assert.deepEqual(c.calls, [['organizePropose']])
  const running = cockpitState(NOW, { ui: { organize: { busy: true, proposal: null, ticks: {} } } })
  const busy = mount(html`<${Sidebar} s=${running} c=${recorder()} rooms=${roomsOf(running)} here=${{ kind: 'chat' }} />`)
  assert.ok(busy.button(en.organize.button).hasAttribute('disabled'))
  const without = cockpitState(NOW, { driver: { caps: ['tabs'] } })
  const none = mount(html`<${Sidebar} s=${without} c=${recorder()} rooms=${roomsOf(without)} here=${{ kind: 'chat' }} />`)
  assert.equal(none.button(en.organize.button), null)
})

test('the demo proposes every kind and applies the ticked ones', async () => {
  const { mock } = loadedRooms
  const tr = mock.createMockTransport({ lang: 'en', latency: 0 })
  tr.events(new Proxy({}, { get: () => () => {} }), () => {})
  const act = (verb, args) => tr.post('/api/action', { verb, args })
  const prop = (await act('organize_propose', {})).data.proposal
  assert.equal(prop.items.length, 5)
  assert.deepEqual(new Set(prop.items.map(i => i.kind)), new Set(['ws_title', 'ws_color', 'ws_description', 'tab_title', 'tab_move']))
  const st0 = (await tr.get('/api/state')).data
  assert.ok(st0.tabs.workspaces.every(w => 'color_name' in w))
  const res = (await act('organize_apply', { proposal: prop.id, items: prop.items.map(i => i.id) })).data
  assert.equal(res.applied.length, 5)
  const st = (await tr.get('/api/state')).data
  for (const it of prop.items) {
    if (it.kind === 'ws_title') assert.equal(st.tabs.workspaces.find(w => w.ref === it.ref).title, it.to)
    if (it.kind === 'ws_color') assert.equal(st.tabs.workspaces.find(w => w.ref === it.ref).color_name, it.to)
    if (it.kind === 'tab_title') assert.equal(st.tabs.tabs.find(t => t.ref === it.ref).name, it.to)
    if (it.kind === 'tab_move') assert.equal(st.tabs.tabs.find(t => t.ref === it.ref).ws_ref, it.to)
  }
  assert.equal((await act('organize_apply', { proposal: 'o9999999999', items: [prop.items[0].id] })).error.code, 'stale_proposal')
})

// ---------------------------------------------------------------- the chat: one field, two fixed buttons (package 5, round 6d C4)

const { ChatFoot, ChatThread, QuickChat } = views.chat
const ANSWERED = { id: 'q0123456789', kind: 'free', started_ms: NOW, session: null, total_usd: 0, running: false, last_ms: NOW,
  turns: [{ q: 'what next?', a: 'Commit the yaml change.', model_asked: 'haiku', model: 'haiku-5-5', cost_usd: 0.001, at_ms: NOW, error: null }] }

function renderFoot({ conv = null, over = {} } = {}) {
  const s = cockpitState(NOW, over)
  const c = recorder()
  const el = mount(html`<${ChatFoot} s=${s} c=${c} conv=${conv} autofocus=${false} />`)
  return { el, c, s }
}
const acts = c => c.calls.filter(x => x[0] === 'act' || x[0] === 'ask')

test('6d C4: one field with two fixed buttons, Ask and Let AI do it, whatever is typed; no route chip, no hint under it', async () => {
  const { el } = renderFoot()
  const names = () => el.$('.send-btns').$$('button').map(b => b.text())
  assert.deepEqual(names(), [en.chatAsk, en.chatSolve])
  assert.equal(el.$('#quick-input').getAttribute('placeholder'), en.chatPlaceholder)
  for (const typed of ['Fix the flaky test', 'what is open?', '!tidy the labels', 'the release notes']) {
    typeInto(el.$('#quick-input'), typed)
    await settle()
    assert.deepEqual(names(), [en.chatAsk, en.chatSolve], typed)
    assert.equal(el.$('.route-chip'), null, typed)
  }
  assert.equal(el.$('.chat-hint'), null)
  assert.doesNotMatch(el.$('.tabview-foot').text(), /Cmd|Ctrl|Enter/)
})

test('6d C4: Ask and Enter answer here, read only, as typed; Let AI do it starts a tab, inside a conversation it hands it on', async () => {
  const ask = renderFoot()
  typeInto(ask.el.$('#quick-input'), 'Fix the flaky test')
  await settle()
  keydown(ask.el.$('#quick-input'), 'Enter')
  await settle()
  typeInto(ask.el.$('#quick-input'), '!tidy the labels')
  await settle()
  ask.el.button(en.chatAsk).click()
  await settle()
  assert.deepEqual(acts(ask.c), [['ask', 'free', { text: 'Fix the flaky test' }], ['ask', 'free', { text: '!tidy the labels' }]])
  const solve = renderFoot()
  typeInto(solve.el.$('#quick-input'), 'what waits for me?')
  await settle()
  solve.el.button(en.chatSolve).click()
  await settle()
  assert.deepEqual(acts(solve.c), [['act', 'chat_tab', { text: 'what waits for me?', routed: 'forced' }]])
  // inside an answered conversation it hands the chat on, with the text as the order
  const inConv = renderFoot({ conv: ANSWERED })
  typeInto(inConv.el.$('#quick-input'), 'Update the docs too')
  await settle()
  inConv.el.button(en.chatSolve).click()
  await settle()
  assert.deepEqual(acts(inConv.c), [['act', 'quick_handoff', { conv: ANSWERED.id, to: 'tab', text: 'Update the docs too' }]])
})

test('a handed chat shows its status and disables the handoff buttons only while starting', async () => {
  const solve = el => el.button(en.chatSolve)
  const starting = renderFoot({ conv: { ...ANSWERED, handed: { to: 'tab', at_ms: NOW, status: 'starting' } } })
  assert.match(starting.el.$('.handoff-status').text(), new RegExp(en.handoff.starting))
  assert.equal(solve(starting.el).hasAttribute('disabled'), true)
  // arrived: the tab that carries the item, one click away (one that asks you says so instead, round 6d)
  const s0 = cockpitState(NOW)
  const tab = s0.tabs.tabs.find(t => !t.is_control && t.state !== 'shell' && t.state !== 'needs-you')
  const tabs = { ...s0.tabs, tabs: s0.tabs.tabs.map(t => t.ref === tab.ref ? { ...t, item: '20261009-1200-what-next-a1b2' } : t) }
  const arrived = renderFoot({ conv: { ...ANSWERED, handed: { to: 'tab', at_ms: NOW, status: 'started', inbox_id: '20261009-1200-what-next-a1b2' } },
    over: { tabs } })
  assert.match(arrived.el.$('.handoff-status').text(), new RegExp(en.handoff.inTab(tab.name)))
  assert.equal(solve(arrived.el).hasAttribute('disabled'), false)
  // Open the tab opens it in the cockpit (round 6d), the terminal is the second way
  arrived.el.button(en.handoff.jump).click()
  assert.deepEqual(arrived.c.calls.filter(x => x[0] === 'openTabView'), [['openTabView', tab.ref]])
  arrived.el.button(en.handoff.inTerminal).click()
  assert.deepEqual(acts(arrived.c), [['act', 'tab_jump', { tab_ref: tab.ref }]])
  // a failed start is tried again on the same route
  const failed = renderFoot({ conv: { ...ANSWERED, handed: { to: 'tab', at_ms: NOW, status: 'failed', inbox_id: 'x' } } })
  assert.match(failed.el.$('.handoff-status').text(), new RegExp(en.handoff.failed))
  failed.el.button(en.handoff.retry).click()
  assert.deepEqual(acts(failed.c), [['act', 'quick_handoff', { conv: ANSWERED.id, to: 'tab' }]])
  // a control handoff shows the relay's word, and offers no one click control handoff of its own
  const control = renderFoot({ conv: { ...ANSWERED, handed: { to: 'control', at_ms: NOW, status: 'queued', relay_id: 'r9' } },
    over: { relay: { ...s0.relay, records: [{ id: 'r9', status: 'submitted' }] } } })
  assert.match(control.el.$('.handoff-status').text(), new RegExp(en.handoff.arrived))
  // typing on keeps the status where it is: there is no chip to give way to
  typeInto(arrived.el.$('#quick-input'), 'and the docs?')
  await settle()
  assert.ok(arrived.el.$('.handoff-status'))
})

test('a handed chat says what came back from its item: the result, or the question it asks', () => {
  const handed = outcome => ({ ...ANSWERED, handed: { to: 'tab', at_ms: NOW, status: 'started', inbox_id: '20261009-1200-what-next-a1b2', outcome } })
  const done = renderFoot({ conv: handed({ text: 'Result: the bot runs', closed: true, at_ms: NOW, asks: false }) })
  assert.equal(done.el.$('.handoff-status').getAttribute('data-status'), 'result')
  assert.match(done.el.$('.handoff-status').text(), new RegExp(en.handoff.result('the bot runs')))
  const asks = renderFoot({ conv: handed({ text: 'Question: close it?', closed: false, at_ms: NOW, asks: true }) })
  assert.match(asks.el.$('.handoff-status').text(), /Asks you: close it\?/)
  assert.doesNotMatch(asks.el.$('.handoff-status').text(), /Question:/)
})

test('every handed chat of the demo shows a worded status line', () => {
  const s = cockpitState(NOW)
  const handed = s.quick.convs.filter(x => x.handed)
  assert.ok(handed.length >= 11, 'one chat per status')
  const seen = new Set()
  for (const conv of handed) {
    const el = mount(html`<${ChatFoot} s=${s} c=${recorder()} conv=${conv} autofocus=${false} />`)
    const line = el.$('.handoff-status')
    assert.ok(line && line.text(), conv.handed.status)
    assert.doesNotMatch(line.text(), /undefined/)
    seen.add(line.getAttribute('data-status'))
  }
  for (const word of ['starting', 'started', 'running', 'failed', 'manual', 'nothing', 'gone', 'waiting', 'arrived', 'offline']) assert.ok(seen.has(word), word)
})

// ---------------------------------------------------------------- round 6d: finding questions again

const asked = (id, q, ms, over = {}) => ({ id, kind: 'free', started_ms: ms, session: null, total_usd: 0, running: false, last_ms: ms,
  turns: [{ q, a: 'An answer.', model_asked: 'haiku', model: 'haiku', cost_usd: 0, at_ms: ms, error: null }], ...over })
const JOB_Q = 'Background job chat-bot on mini: last run failed. It ended with 75. What now?'
function asksState(over = {}) {
  const s0 = cockpitState(NOW)
  const tab = s0.tabs.tabs.find(t => !t.is_control && t.state !== 'shell')
  const tabs = { ...s0.tabs, tabs: s0.tabs.tabs.map(t => t.ref === tab.ref ? { ...t, item: 'i-job', state: 'working' } : t) }
  const convs = [asked('q0000000001', JOB_Q, NOW - 30 * MIN), asked('q0000000002', JOB_Q, NOW - 29 * MIN),
    asked('q0000000003', JOB_Q, NOW - 28 * MIN, { handed: { to: 'tab', at_ms: NOW - 27 * MIN, status: 'started', inbox_id: 'i-job' } }),
    asked('q0000000004', 'What is new?', NOW - 5 * MIN),
    asked('q0000000005', 'Close the old label task', NOW - 50 * MIN, { handed: { to: 'tab', at_ms: NOW - 49 * MIN, status: 'started', inbox_id: 'i-gone',
      outcome: { text: 'Result: Nothing to do, the labels were merged already', closed: true, at_ms: NOW - 40 * MIN, asks: false } } })]
  return { s: cockpitState(NOW, { tabs, quick: { ...s0.quick, keep_hours: 24, convs }, ...over }), tab }
}

test('a question in the Chat list keeps its title on a line of its own, its marker and time under it', async () => {
  // 28.10. at 1280: "Tab ended" and the time took the row and cut the titles to "Backgrou…"
  const { s } = asksState()
  const el = mount(html`<${Sidebar} s=${s} c=${recorder()} rooms=${roomsOf(s)} here=${{ kind: 'chat' }} />`)
  const row = el.$$('.room-asks .room-chat').find(r => r.$('.ask-mark'))
  assert.ok(row, 'a handed question is listed')
  const sub = row.$('.room-sub')
  assert.ok(sub && sub.$('.ask-mark') && sub.$('.room-meta'), 'marker and time stand under the title')
  assert.equal(sub.$('.room-name'), null)
  const fs = await import('node:fs')
  assert.match(fs.readFileSync(new URL('../web/style.css', import.meta.url), 'utf8'), /\.room-sub \{[^}]*flex: 1 0 100%/)
})

test('the question window lists recent questions by title, with time stamps for equal ones and their markers', () => {
  const { s } = asksState({ ui: { tabView: '@ask' } })
  const el = mount(html`<${QuickChat} s=${s} c=${recorder()} />`)
  const chips = el.$$('.quick-conv').map(b => b.text())
  // open and handed first, the new chat button before them
  assert.match(chips[1], /^chat-bot · mini · last run failed/)          // by job, machine and state, never the prompt
  assert.match(chips[1], new RegExp(en.asks.mark.inTab))
  assert.match(chips[2], new RegExp(en.asks.mark.done))
  assert.ok(chips.some(x => x.includes('What is new?')), chips.join(' | '))
  const stamped = chips.filter(x => x.includes('chat-bot'))
  assert.equal(stamped.length, 3)
  assert.equal(new Set(stamped).size, 3, 'three equal questions read apart by their time')
  assert.ok(stamped.every(x => x.includes(en.asks.today)), stamped.join(' | '))
})

test('a question chip clips only its title, so its marker stays in view however long the title', async () => {
  // walk 28.10.: the chip cut at its width took the marker with it
  const { s } = asksState({ ui: { tabView: '@ask' } })
  const el = mount(html`<${QuickChat} s=${s} c=${recorder()} />`)
  const chip = el.$$('.quick-conv').find(b => b.$('.ask-mark'))
  assert.ok(chip, 'a chip with a marker')
  assert.ok(chip.$('.quick-conv-title'), 'the title has a part of its own')
  assert.ok(!chip.$('.quick-conv-title .ask-mark'), 'the marker is not part of the clipped title')
  const fs = await import('node:fs')
  const css = fs.readFileSync(new URL('../web/style.css', import.meta.url), 'utf8')
  assert.match(css, /\.quick-conv-title \{[^}]*text-overflow: ellipsis/)
})

test('a handed question that came back shows its outcome under the question and in its status line', () => {
  const { s } = asksState()
  const conv = s.quick.convs.find(x => x.id === 'q0000000005')
  const el = mount(html`<${ChatFoot} s=${s} c=${recorder()} conv=${conv} autofocus=${false} />`)
  const line = el.$('.handoff-status')
  assert.equal(line.getAttribute('data-status'), 'result')
  assert.match(line.text(), new RegExp(en.handoff.result('Nothing to do, the labels were merged already')))
  const thread = mount(html`<${ChatThread} s=${s} c=${recorder()} conv=${conv} />`)
  assert.match(thread.$('.qoutcome').text(), /Nothing to do, the labels were merged already/)
})

test('as cmux, Open the tab picks the tab room in the cockpit and the terminal is the second way', () => {
  const { s, tab } = asksState({ rooms: { ...cockpitState(NOW).rooms, layout: 'workspaces' } })
  const conv = s.quick.convs.find(x => x.id === 'q0000000003')
  const c = recorder()
  const el = mount(html`<${ChatFoot} s=${s} c=${c} conv=${conv} autofocus=${false} />`)
  el.button(en.handoff.jump).click()
  assert.deepEqual(c.calls.filter(x => ['setPage', 'pickRoom'].includes(x[0])), [['setPage', '@chat'], ['pickRoom', { kind: 'tab', id: tab.ref }]])
  el.button(en.handoff.inTerminal).click()
  assert.deepEqual(acts(c), [['act', 'tab_jump', { tab_ref: tab.ref }]])
})

test('in the Chat as cmux the questions stand on top, open and handed first, and all of them reaches the archive', async () => {
  const { s } = asksState({ rooms: { ...cockpitState(NOW).rooms, layout: 'workspaces' } })
  const c = recorder()
  const el = mount(html`<${Sidebar} s=${s} c=${c} rooms=${roomsOf(s)} here=${{ kind: 'chat' }} />`)
  const group = el.$('.room-asks')
  assert.ok(group, 'the questions have a group of their own')
  const heads = el.$$('h3').map(h => h.text())
  assert.ok(heads.findIndex(h => h.includes(en.rooms.chats)) < heads.findIndex(h => h.includes(en.rooms.workspaces)), heads.join(' | '))
  const rows = group.$$('.room-chat-row').map(r => r.text())
  assert.match(rows[0], new RegExp(en.asks.mark.inTab))
  assert.match(rows[1], new RegExp(en.asks.mark.done))
  assert.ok(rows.findIndex(x => x.includes('What is new?')) > 1, rows.join(' | '))
  // all: every question of the last days, the archived ones too, read once from the server
  group.button(en.rooms.allAsks).click()
  await settle()
  assert.deepEqual(c.calls.filter(x => x[0] === 'showAllAsks'), [['showAllAsks', true]])
  const archived = cockpitState(NOW, { ...s, chatArchive: { status: 'ok', convs: [asked('q00000000a1', 'An old question from Monday', NOW - 3 * 24 * 60 * MIN, { why: 'expired' })] } })
  const all = mount(html`<${Sidebar} s=${{ ...archived, ui: { ...archived.ui, asksAll: true } }} c=${recorder()} rooms=${roomsOf(archived)} here=${{ kind: 'chat' }} />`)
  const old = all.$$('.room-asks .room-chat-row').find(r => r.text().includes('An old question from Monday'))
  assert.ok(old, 'the archived question is listed')
  assert.match(old.text(), new RegExp(en.asks.mark.archived))
})

// ---------------------------------------------------------------- the A2A agents page

test('the agents section no longer lists an expired conversation', () => {
  const { AgentsPage } = views.agents
  const s0 = cockpitState(NOW)
  const peer = s0.agents.peers[0].id
  const conv = (id, q, ago, extra = {}) => ({ id, peer, started_ms: NOW - ago, last_ms: NOW - ago, context_id: null, running: false,
    turns: [{ q, mode: 'question', a: 'An answer.', state: 'completed', task_id: null, waiting: false, at_ms: NOW - ago, answered_ms: NOW - ago, error: null, ...extra }] })
  const agents = { ...s0.agents, keep_hours: 24, convs: [conv('g0000000001', 'A fresh question', 2 * 3600000),
    conv('g0000000002', 'A question from last week', 7 * 24 * 3600000),
    conv('g0000000003', 'A task the owner still holds', 7 * 24 * 3600000, { waiting: true, state: 'input-required' })] }
  const s = cockpitState(NOW, { agents, ui: { agentPeer: peer } })
  const el = mount(html`<${AgentsPage} s=${s} c=${recorder()} />`)
  const listed = el.$$('.agent-convs .quick-conv').map(b => b.text())
  assert.ok(listed.some(x => x.includes('A fresh question')), listed.join(' | '))
  assert.ok(listed.some(x => x.includes('A task the owner still holds')), listed.join(' | '))
  assert.ok(!listed.some(x => x.includes('A question from last week')), listed.join(' | '))
  // 0 keeps every one
  const all = mount(html`<${AgentsPage} s=${{ ...s, agents: { ...agents, keep_hours: 0 } }} c=${recorder()} />`)
  assert.ok(all.$$('.agent-convs .quick-conv').some(b => b.text().includes('A question from last week')))
})

test('an agent whose card cannot be read says why in plain words, what to do, and offers to check again', () => {
  const { AgentsPage } = views.agents
  const s0 = cockpitState(NOW)
  const p = s0.agents.peers.find(x => x.id === 'partner-bridge')
  assert.ok(p, 'the demo state has a peer with an unreadable card')
  const c = recorder()
  const s = cockpitState(NOW, { ui: { agentPeer: p.id } })
  const el = mount(html`<${AgentsPage} s=${s} c=${c} />`)
  const trouble = el.$$('.agent-trouble').map(x => x.text())
  assert.equal(trouble.length, 2, trouble.join(' | '))
  // the card: the name does not resolve, and the hint names the tailnet, the host and its owner
  assert.match(trouble[0], /address not found/)
  assert.match(trouble[0], /tailnet of partner/)
  assert.match(trouble[0], /example\.org/)
  // the last message: refused, with the token advice
  assert.match(trouble[1], /refused/)
  assert.match(trouble[1], /token/)
  // the raw text is kept, folded away, never the headline
  assert.ok(el.$$('.agent-trouble-raw code').some(x => x.text().includes('nodename')))
  assert.doesNotMatch(el.$('.agent-trouble-hint').text(), /Errno/)
  // without a card the profile still shows the card address from the peer file and the summary
  assert.match(el.$('.agent-facts').text(), /example\.org\/partner\//)
  assert.match(el.$('.agent-profile-desc').text(), /partner team/)
  // check again asks the server for fresh cards
  el.$('.agent-profile-head').$$('button').find(b => /check again/.test(b.text())).click()
  assert.ok(c.calls.some(([name, fresh]) => name === 'loadAgents' && fresh === true), JSON.stringify(c.calls))
})

test('the agent stands in a bar above the conversation: name, state and a real button for its card', () => {
  const { AgentsPage } = views.agents
  const s0 = cockpitState(NOW)
  const p = s0.agents.peers.find(x => x.id === 'partner-bridge')
  const conv = { id: 'g0000000009', peer: p.id, started_ms: NOW - 60000, last_ms: NOW - 60000, context_id: null, running: false,
    turns: [{ q: 'Hello?', mode: 'question', a: 'Hi.', state: 'completed', task_id: null, waiting: false, at_ms: NOW, answered_ms: NOW, error: null }] }
  const s = cockpitState(NOW, { agents: { ...s0.agents, convs: [conv] }, ui: { agentPeer: p.id, agentConv: conv.id } })
  const el = mount(html`<${AgentsPage} s=${s} c=${recorder()} />`)
  const bar = el.$('.agent-bar')
  assert.ok(bar, 'a bar above the conversation')
  assert.match(bar.text(), /partner-bridge/)
  // the trouble shows in the bar too, so it is seen with the card folded away
  assert.match(bar.text(), /card not readable/i)
  // the card is no chip among the conversations any more
  assert.equal(el.$$('.agent-convs .agent-profile-toggle').length, 0)
  // with a conversation open the card is folded; the bar's button opens it
  assert.equal(el.$('.agent-profile'), null)
  const btn = bar.$$('button').find(b => /card/i.test(b.text()))
  assert.ok(btn, 'a button named for the card in the bar')
  assert.equal(btn.getAttribute('aria-expanded'), 'false')
})

test('every agent card in the list carries its own card button, which picks the agent and opens the card', () => {
  const { AgentsPage } = views.agents
  const s0 = cockpitState(NOW)
  const c = recorder()
  const el = mount(html`<${AgentsPage} s=${s0} c=${c} />`)
  const cards = el.$$('.agents-list .agent-card')
  assert.equal(cards.length, s0.agents.peers.length)
  for (const card of cards) assert.ok(card.$$('button').some(b => /card/i.test(b.text())), card.text())
  // no button inside a button: the pick and the card button are siblings
  assert.equal(el.$$('.agents-list button button').length, 0)
  const last = cards.at(-1)
  last.$$('button').find(b => /card/i.test(b.text())).click()
  assert.ok(c.calls.some(([name, id]) => name === 'pickAgent' && id === s0.agents.peers.at(-1).id), JSON.stringify(c.calls))
})

// ---------------------------------------------------------------- review findings

test('the demo state carries only question states the server emits and ids it accepts', () => {
  const s = cockpitState(NOW)
  for (const t of s.tabs.tabs) {
    if (t.filed_by || t.is_control || !['waiting', 'needs-you'].includes(t.state)) assert.equal(t.ask, null, t.ref)
  }
  assert.ok(s.tabs.tabs.some(t => t.ask?.draft && !t.filed_by && t.waiting), 'a draft on a tab the poll reads')
  for (const conv of s.quick.convs) assert.match(conv.id, /^q[0-9a-f]{10}$/, conv.id)
})

test('the organize result words every failure code, the terminal\'s own text only as a tooltip', () => {
  const proposal = { id: 'o0123456789', at_ms: NOW, scope: 3, items: ORG_ITEMS }
  for (const code of ['name_in_use', 'managed', 'gone', 'last_tab', 'changed', 'driver_failed']) {
    for (const t of Object.values(text.TABLES)) assert.equal(typeof t.organize.errors[code], 'string', code)
    const result = { applied: [], skipped: [], failed: [{ id: 'ws_color:workspace:2', error: code, detail: "no open tab with the ref 'surface:7'" }] }
    const el = mount(html`<${OrganizeView} s=${orgState({ busy: false, proposal, ticks: {}, result })} c=${recorder()} />`)
    const li = el.$$('.org-list li').at(-1)
    assert.ok(li.text().endsWith(`: ${en.organize.errors[code]}`), code)
    assert.ok(!el.text().includes('surface:7'), code)
    assert.equal(li.getAttribute('title'), "no open tab with the ref 'surface:7'")
  }
  // an unknown code still reads as words
  const odd = { applied: [], skipped: [{ id: 'tab_title:surface:9', why: 'task_tab' }], failed: [{ id: 'ws_color:workspace:2', error: 'exit 1' }] }
  const el = mount(html`<${OrganizeView} s=${orgState({ busy: false, proposal, ticks: {}, result: odd })} c=${recorder()} />`)
  assert.ok(el.text().includes(en.organize.errors.driver_failed) && !el.text().includes('exit 1'))
  assert.ok(el.text().includes(en.organize.why.task_tab))
})

test('an organize item checkbox is named by its row: the kind, what it was and what it becomes', () => {
  const proposal = { id: 'o0123456789', at_ms: NOW, scope: 3, items: ORG_ITEMS }
  const el = mount(html`<${OrganizeView} s=${orgState({ busy: false, proposal, ticks: {} })} c=${recorder()} />`)
  const row = el.$$('.org-item').find(r => r.text().includes('Release notes'))
  const box = row.$('input[type="checkbox"]')
  assert.equal(box.getAttribute('aria-label'), null, 'an aria-label would hide the from and to')
  const name = box.parentNode.textContent
  for (const part of [en.organize.kinds.tab_title, 'release', 'Release notes']) assert.ok(name.includes(part), part)
})

test('Waiting for you holds its order while the pointer is in it; a new row goes last until it leaves', async () => {
  const s = cockpitState(NOW)
  const el = renderSide(s)
  const names = () => replyRows(el).map(r => r.$('.room-name').text())
  const before = names()
  el.$('.reply-group').dispatch('pointerenter')
  // docs-refresh starts asking: sorted, it would stand on top, right where the pointer is
  const asks = { text: 'Run the link check again?', hash: 'a'.repeat(16), yes_no: true, draft: false,
    options: [{ n: 1, label: 'Yes' }, { n: 2, label: 'No' }] }
  const next = { ...s, tabs: { ...s.tabs, at_ms: s.tabs.at_ms + 3000, tabs: s.tabs.tabs.map(t => t.ref === 'surface:8'
    ? { ...t, state: 'needs-you', waiting: true, ask: asks, since_ms: NOW } : t) } }
  renderSide(next, el)
  assert.deepEqual(names(), [...before, 'docs-refresh'])
  el.$('.reply-group').dispatch('pointerleave')
  await new Promise(resolve => setTimeout(resolve, 0))
  assert.equal(names()[0], 'alpha-release')
  assert.equal(names()[1], 'docs-refresh')
})

test('an answered row comes back with its buttons when the same question is asked again', () => {
  const s = cockpitState(NOW)
  const tab = tabOf(s, 'surface:12')
  const mark = loadedRooms.logic.answerMark(tab, 'Yes', NOW)
  const el = renderSide({ ...s, ui: { ...s.ui, answered: { 'surface:12': mark } } })
  const row = replyRow(el, 'demo-task research')
  assert.ok(row.hasClass('is-left'))
  assert.equal(row.$('.room-meta').text(), en.reply.answeredWord)
  // the agent worked and asks the identical question again: a new state since, the same hash
  const again = { ...s, tabs: { ...s.tabs, at_ms: s.tabs.at_ms + 3000, tabs: s.tabs.tabs.map(t => t.ref === 'surface:12'
    ? { ...t, since_ms: NOW - 1000 } : t) }, ui: { ...s.ui, answered: { 'surface:12': mark } } }
  const back = replyRow(renderSide(again), 'demo-task research')
  assert.ok(!back.hasClass('is-left'))
  assert.ok(!back.$$('.room-meta').some(x => x.text() === en.reply.answeredWord), 'no longer marked answered')
})

test('an answer the tab did not take is not marked answered and keeps what was typed', async () => {
  const s = cockpitState(NOW)
  const tab = tabOf(s, 'surface:12')
  const calls = []
  const c = new Proxy({}, { get: (_, p) => p === 'reply' ? (...a) => { calls.push(['reply', ...a]); return Promise.resolve({ ok: false, note: 'send failed' }) }
    : p === 'then' ? undefined : (...a) => { calls.push([p, ...a]) } })
  const el = mount(html`<${TabReply} tab=${tab} s=${s} c=${c} />`)
  el.button(en.reply.yes).click()
  await tick()
  const box = el.$('textarea')
  box.value = 'all three please'
  box.dispatch('input')
  await tick()
  el.button(en.reply.send).click()
  await tick()
  assert.ok(!calls.some(x => x[0] === 'markAnswered'), 'nothing went out, nothing is marked')
  assert.equal(el.$('textarea').value, 'all three please')
})

// ---------------------------------------------------------------- the decision guide (views/guide.js)

const { GuideTree, GuideBoard, GuideLine, GuideSettings } = views.guide
/** A controller whose reply answers ok and records what it sent; every other call is recorded too */
function guideCtl() {
  const calls = []
  const c = new Proxy({}, { get: (_, p) => p === 'calls' ? calls : p === 'then' ? undefined
    : (...a) => { calls.push([p, ...a]); return p === 'reply' ? Promise.resolve({ ok: true }) : undefined } })
  return c
}
const optLabels = el => el.$$('.guide-opt-label').map(x => x.text())
// a textarea's words: Preact writes `value` as an attribute into the small DOM until something sets the property
const boxValue = box => box.value ?? box.getAttribute('value') ?? ''

test('guide: a reading made for another question shows as stale without steps', () => {
  const s = cockpitState(NOW)
  const tab = { ...tabOf(s, 'surface:12'), ask: { ...tabOf(s, 'surface:12').ask, hash: 'ffffffffffffffff' } }
  const el = mount(html`<${GuideTree} tab=${tab} s=${s} c=${recorder()} />`)
  assert.ok(el.$('.guide.is-stale'))
  assert.match(el.text(), new RegExp(en.guide.stale))
  assert.deepEqual(optLabels(el), [en.guide.own])
})

test('guide: off, the tree, the line and the board draw nothing', () => {
  const s = cockpitState(NOW, { guide: { enabled: false, auto: true, per_hour: 30, entries: {}, rev: 1, overridden: [] } })
  const tab = tabOf(s, 'surface:12')
  assert.equal(mount(html`<${GuideTree} tab=${tab} s=${s} c=${recorder()} />`).text(), '')
  assert.equal(mount(html`<${GuideLine} tab=${tab} s=${s} />`).text(), '')
  assert.equal(mount(html`<${GuideBoard} s=${s} c=${recorder()} />`).text(), '')
  // the control tab and a working tab never get a reading
  const on = cockpitState(NOW)
  assert.equal(mount(html`<${GuideTree} tab=${tabOf(on, 'surface:3')} s=${on} c=${recorder()} />`).text(), '')
  assert.equal(mount(html`<${GuideTree} tab=${tabOf(on, 'surface:8')} s=${on} c=${recorder()} />`).text(), '')
})

test('guide: the board lists every waiting tab, the one that needs you first, each with its tree', () => {
  const s = cockpitState(NOW)
  const el = mount(html`<${GuideBoard} s=${s} c=${recorder()} />`)
  assert.match(el.$('.sec-title').text(), new RegExp(en.guide.boardTitle))
  assert.deepEqual(el.$$('.guide-card-name').map(x => x.text()), ['alpha-release', 'demo-task research', 'changelog'])
  assert.equal(el.$$('.guide').length, 3)
})

test('guide: the settings switch the guide and reading by itself, beside the config', () => {
  const s = cockpitState(NOW)
  const c = recorder()
  const el = mount(html`<${GuideSettings} s=${s} c=${c} />`)
  const switches = el.$$('[role="switch"]')
  assert.deepEqual(switches.map(x => x.getAttribute('aria-label')), [en.settings.guideLabel.enabled, en.settings.guideLabel.auto])
  switches[0].click()
  assert.deepEqual(c.calls.at(-1), ['saveGuide', { enabled: false }])
  switches[1].click()
  assert.deepEqual(c.calls.at(-1), ['saveGuide', { auto: false }])
})

test('guide: the tree opens with what the session is about, its folder and its task', () => {
  const s = cockpitState(NOW)
  const el = mount(html`<${GuideTree} tab=${tabOf(s, 'surface:12')} s=${s} c=${recorder()} />`)
  assert.equal(el.$('.guide-about').text(), 'Sources for the team page of the demo project')
  assert.match(el.$('.guide-root').text(), new RegExp(en.guide.about))
  const topic = el.$('.guide-topic')
  assert.match(topic.text(), /demo/)
  assert.match(topic.text(), new RegExp(en.guide.task('Write the onboarding guide for the demo project')))
  assert.equal(topic.getAttribute('title'), en.guide.startedWith('Find three good sources for the team page and summarise them'))
})

test('guide: the line names what the session is about first, then where it stands', () => {
  const s = cockpitState(NOW)
  const el = mount(html`<${GuideLine} tab=${tabOf(s, 'surface:12')} s=${s} />`)
  assert.equal(el.$('.guide-line-about').text(), 'Sources for the team page of the demo project')
  assert.match(el.text(), /Three sources found and read/)
})

test('guide: while Haiku reads, what the session is about already shows', () => {
  const s = cockpitState(NOW)
  const entry = { ...s.guide.entries['surface:12'], running: true, where: '', options: [], about: 'Sources for the team page' }
  const st = { ...s, guide: { ...s.guide, entries: { ...s.guide.entries, 'surface:12': entry } } }
  const tree = mount(html`<${GuideTree} tab=${tabOf(st, 'surface:12')} s=${st} c=${recorder()} />`)
  assert.equal(tree.$('.guide-about').text(), 'Sources for the team page')
  assert.match(tree.text(), new RegExp(en.guide.reading))
  assert.equal(mount(html`<${GuideLine} tab=${tabOf(st, 'surface:12')} s=${st} />`).$('.guide-line-about').text(), 'Sources for the team page')
})

test('guide: a row of Waiting for you stays one short line, the reading of the guide stands on the right', () => {
  const s = cockpitState(NOW)
  const el = mount(html`<${Sidebar} s=${s} c=${recorder()} rooms=${roomsOf(s)} here=${{ kind: 'chat' }} />`)
  const research = replyRow(el, 'demo-task research')
  assert.equal(research.$('.guide-line-about'), null)
  assert.equal(research.$('.reply-ask'), null)
  const pane = mount(html`<${RoomsPage} s=${cockpitState(NOW, { ui: { room: { kind: 'tab', id: 'surface:12' }, tabView: 'surface:99' } })} c=${recorder()} />`)
  assert.ok(pane.$('.rooms-main .guide'), 'the reading of the guide stands with the tab')
})

test('guide: a waiting tab shows where it stands and one branch per step, the recommended one marked', () => {
  const s = cockpitState(NOW)
  const el = mount(html`<${GuideTree} tab=${tabOf(s, 'surface:12')} s=${s} c=${guideCtl()} />`)
  assert.equal(el.$('.guide-where').text(), 'Three sources found and read; nothing is written to team.md yet.')
  assert.match(el.$('.guide-waits').text(), /Whether to summarise the sources in team\.md\./)
  assert.deepEqual(optLabels(el), ['Summarise', 'List them first', 'Summarise and push', en.guide.own])
  assert.match(el.$('.guide-branch.is-picked').text(), new RegExp(en.guide.picked))
  assert.match(el.$$('.guide-branch')[2].text(), new RegExp(en.guide.risky))
})

test('guide: a click only puts the words in the box, Send sends them, edited if you edited them', async () => {
  const s = cockpitState(NOW)
  const tab = tabOf(s, 'surface:12')
  const c = guideCtl()
  const el = mount(html`<${GuideTree} tab=${tab} s=${s} c=${c} />`)
  assert.equal(el.$('.guide-compose'), null)
  el.$$('.guide-opt')[0].click()
  await tick()
  assert.equal(c.calls.filter(x => x[0] === 'reply').length, 0, 'a click sends nothing')
  assert.ok(el.$('.guide-branch.is-chosen'))
  const box = el.$('.guide-compose textarea')
  assert.equal(boxValue(box), 'Yes, summarise them in team.md.')
  box.value = 'Yes, but only the first two.'
  box.dispatch('input')
  await tick()
  el.$('.guide-compose').button(en.guide.send).click()
  await tick()
  assert.deepEqual(c.calls.find(x => x[0] === 'reply').slice(1), ['tab_send', { tab_ref: 'surface:12', text: 'Yes, but only the first two.',
    expect: 'waiting', seen: tab.ask.hash, name: 'demo-task research' }])
  assert.ok(c.calls.some(x => x[0] === 'markAnswered' && x[1] === 'surface:12'))
})

test('guide: a step that reaches beyond the session says so in the box before it is sent; Cancel leaves it', async () => {
  const s = cockpitState(NOW)
  const c = guideCtl()
  const el = mount(html`<${GuideTree} tab=${tabOf(s, 'surface:12')} s=${s} c=${c} />`)
  el.$$('.guide-opt')[2].click()
  await tick()
  assert.match(el.$('.guide-compose').text(), new RegExp(en.guide.riskyNote))
  el.$('.guide-compose').button(en.guide.cancel).click()
  await tick()
  assert.equal(el.$('.guide-compose'), null)
  assert.equal(c.calls.filter(x => x[0] === 'reply').length, 0)
})

test('guide: a dialog step is chosen first and pressed with its own number on Press', async () => {
  const s = cockpitState(NOW)
  const tab = tabOf(s, 'surface:7')
  const c = guideCtl()
  const el = mount(html`<${GuideTree} tab=${tab} s=${s} c=${c} />`)
  assert.deepEqual(optLabels(el), ['Yes', 'No, and tell Claude what to do differently', en.guide.own])
  el.$$('.guide-opt')[1].click()
  await tick()
  assert.equal(c.calls.filter(x => x[0] === 'reply').length, 0)
  assert.equal(el.$('.guide-compose textarea'), null, 'a dialog takes no typed words')
  el.$('.guide-compose').button(en.guide.press).click()
  await tick()
  assert.deepEqual(c.calls.find(x => x[0] === 'reply').slice(1), ['tab_option', { tab_ref: 'surface:7', n: 3, seen: tab.ask.hash, name: 'alpha-release' }])
})

test('guide: Answer yourself opens an empty box; the tab is one click away, its screen another', async () => {
  const s = cockpitState(NOW)
  const c = guideCtl()
  const el = mount(html`<${GuideTree} tab=${tabOf(s, 'surface:12')} s=${s} c=${c} />`)
  el.$$('.guide-opt').at(-1).click()
  await tick()
  assert.equal(boxValue(el.$('.guide-compose textarea')), '')
  el.button(en.guide.toTab).click()
  assert.deepEqual(c.calls.at(-1), ['act', 'tab_jump', { tab_ref: 'surface:12' }])
  el.button(en.guide.watch).click()
  assert.deepEqual(c.calls.at(-1), ['openTabView', 'surface:12'])
  // a tab not read yet offers the reading
  const fresh = mount(html`<${GuideTree} tab=${tabOf(s, 'surface:13')} s=${s} c=${c} />`)
  fresh.button(en.guide.read).click()
  assert.deepEqual(c.calls.at(-1), ['guideRead', 'surface:13'])
})

test('guide: What was read shows the asks and the agent words Haiku read', async () => {
  const s = cockpitState(NOW)
  const el = mount(html`<${GuideTree} tab=${tabOf(s, 'surface:12')} s=${s} c=${guideCtl()} />`)
  assert.equal(el.$('.guide-read'), null)
  el.button(en.guide.showRead).click()
  await tick()
  const read = el.$('.guide-read')
  assert.match(read.text(), /Find three good sources for the team page/)
  assert.match(read.text(), /I found three sources/)
  el.button(en.guide.hideRead).click()
  await tick()
  assert.equal(el.$('.guide-read'), null)
})

test('guide: in the chat the view switches between reading, both and terminal', () => {
  const pane = guideView => mount(html`<${RoomsPage} s=${cockpitState(NOW, { ui: { room: { kind: 'tab', id: 'surface:12' }, tabView: 'surface:99',
    ...(guideView ? { guideView } : {}) } })} c=${recorder()} />`)
  const both = pane(null)
  assert.ok(both.$('.rooms-main .guide') && both.$('.rooms-main .tabview-body'), 'both by default')
  assert.ok(both.$('.rooms-main.has-reply'), 'the reading gets a row of its own')
  const only = pane('guide')
  assert.ok(only.$('.rooms-main .guide') && !only.$('.rooms-main .tabview-body'))
  const screen = pane('screen')
  assert.ok(!screen.$('.rooms-main .guide') && screen.$('.rooms-main .tabview-body'))
  assert.match(screen.$('.reply-pane').text(), /Should I summarise them/)
  // the switch itself, and the sidebar following it
  const c = recorder()
  const el = mount(html`<${RoomsPage} s=${cockpitState(NOW, { ui: { room: { kind: 'tab', id: 'surface:12' }, tabView: 'surface:99' } })} c=${c} />`)
  el.$('.guide-view').button(en.guide.view.screen).click()
  assert.deepEqual(c.calls.at(-1), ['setGuideView', 'screen'])
})

test('guide: a chosen step brings its box into view and puts the cursor in it, Send in reach', async () => {
  const s = cockpitState(NOW)
  const el = mount(html`<${GuideTree} tab=${tabOf(s, 'surface:12')} s=${s} c=${guideCtl()} />`)
  // the small DOM has no layout and no focus: count the calls instead
  const proto = Object.getPrototypeOf(el)
  const seen = []
  const had = { scroll: proto.scrollIntoView, focus: proto.focus }
  proto.scrollIntoView = function (o) { seen.push(['scroll', this.getAttribute('class'), o?.block]) }
  proto.focus = function () { seen.push(['focus', this.tagName?.toLowerCase?.() ?? this.nodeName]) }
  try {
    el.$$('.guide-opt')[0].click()
    // the effect runs after paint: a busy runner needs more than one tick
    for (let i = 0; i < 50 && !seen.some(x => x[0] === 'scroll'); i++) await tick()
    assert.deepEqual(seen.find(x => x[0] === 'scroll'), ['scroll', 'guide-compose', 'nearest'])
    assert.ok(seen.some(x => x[0] === 'focus' && /textarea/i.test(x[1])), JSON.stringify(seen))
    assert.ok(el.$('.guide-compose').button(en.guide.send))
  } finally {
    proto.scrollIntoView = had.scroll
    proto.focus = had.focus
  }
})

// ---------------------------------------------------------------- the first-run tour (views/tour.js)

const { Tour } = views.tour
const { tourSteps } = (await loadCockpit()).logic

test('tour: the welcome offers the tour and a skip, the skip ends it as skipped', () => {
  const s = cockpitState(NOW, { tour: { enabled: true, done: null }, ui: { tour: { id: 'welcome' } } })
  const c = recorder()
  const el = mount(html`<${Tour} s=${s} c=${c} />`)
  assert.match(el.text(), new RegExp(en.tour.steps.welcome.title))
  assert.ok(labels(el).includes(en.tour.start))
  el.button(en.tour.skip).click()
  assert.deepEqual(c.calls.at(-1), ['tourEnd', 'skipped'])
})

test('tour: a middle step counts, goes back and on, the last one ends it as finished', () => {
  const steps = text.TABLES.en.tour.steps
  const s = cockpitState(NOW, { tour: { enabled: true, done: null }, ui: { tour: { id: 'start' } } })
  const c = recorder()
  const el = mount(html`<${Tour} s=${s} c=${c} />`)
  const list = tourSteps(s)
  assert.match(el.text(), new RegExp(steps[list[2].id].title))
  assert.match(el.$('.tour-count').text(), new RegExp(`2.*${list.length - 2}`))
  el.button(en.tour.next).click()
  assert.deepEqual(c.calls.at(-1), ['tourGo', 3])
  el.button(en.tour.back).click()
  assert.deepEqual(c.calls.at(-1), ['tourGo', 1])
  const last = mount(html`<${Tour} s=${{ ...s, ui: { ...s.ui, tour: { id: list.at(-1).id } } }} c=${c} />`)
  last.button(en.tour.finish).click()
  assert.deepEqual(c.calls.at(-1), ['tourEnd', 'finished'])
})

// the Setup page (docs/bridge-cockpit.md, The Setup page): a welcome with something to set up offers it first
const SETUP_MODEL = model => ({ ...model, pages: [...(model?.pages ?? []), { id: 'setup', title: 'Setup', group: 'settings', sections: [
  { id: 'setup-checks', items: [{ index: 0, title: 'Task management is off', tone: 'warn' }] },
  { id: 'setup-available', items: [{ index: 1, title: 'GitHub', tone: null }] }] }] })

test('tour: with a finding on the Setup page the welcome offers Set up first, which opens that page', () => {
  const base = cockpitState(NOW, { tour: { enabled: true, done: null }, ui: { tour: { id: 'welcome' } } })
  const s = { ...base, model: SETUP_MODEL(base.model) }
  const c = recorder()
  const el = mount(html`<${Tour} s=${s} c=${c} />`)
  assert.ok(labels(el).includes(en.tour.setupFirst))
  assert.ok(labels(el).includes(en.tour.start) && labels(el).includes(en.tour.skip))
  assert.match(el.text(), new RegExp(en.tour.setupHint))
  el.button(en.tour.setupFirst).click()
  assert.deepEqual(c.calls.at(-1), ['tourSetup', 'setup'])
  // nothing to set up: the welcome as before
  const plain = mount(html`<${Tour} s=${base} c=${recorder()} />`)
  assert.ok(!labels(plain).includes(en.tour.setupFirst))
  // a later step never offers it
  const later = mount(html`<${Tour} s=${{ ...s, ui: { ...s.ui, tour: { id: 'start' } } }} c=${recorder()} />`)
  assert.ok(!labels(later).includes(en.tour.setupFirst))
})

test('settings: the Setup area shows the setup sections with their rows, the area only where the page exists', () => {
  const { SettingsPage } = views.settings
  const base = cockpitState(NOW, { ui: { page: '@settings', settingsSection: 'setup' } })
  const model = { ...base.model, pages: [...(base.model?.pages ?? []), { id: 'setup', title: 'Setup', group: 'settings', badge: { kind: 'count', n: 1, warn: true },
    sections: [{ id: 'setup-checks', title: 'What keeps the cockpit from working well', kind: 'command', status: 'ok', total: 1, items: [
      { index: 0, key: 'item:setup/setup-checks/work-off', id: 'work-off', title: 'Task management is off', detail: 'Set work.enabled: true', tone: 'warn', actionable: true }] }] }] }
  const el = mount(html`<${SettingsPage} s=${{ ...base, model }} c=${recorder()} />`)
  assert.ok(el.$$('.settings-nav-item').some(b => b.text().includes(en.settings.section.setup.title)))
  assert.match(el.$('.settings-body').text(), /Task management is off/)
  assert.ok(el.$('.settings-body .psec'), 'drawn as a page section, with the rows and steps every page has')
  // the page has no tab and no place behind More; the Settings tab carries its count
  assert.ok(!views.nav.pageOrder({ ...base, model }).includes('setup'))
  assert.ok(views.nav.pageOrder({ ...base, model }).includes('@settings'))
  // a Bridge without the page (cockpit.setup false): no such area, and a stored choice of it falls back
  const none = mount(html`<${SettingsPage} s=${base} c=${recorder()} />`)
  assert.ok(!none.$$('.settings-nav-item').some(b => b.text().includes(en.settings.section.setup.title)))
})

test('tour: closed, it draws nothing', () => {
  const s = cockpitState(NOW, { tour: { enabled: true, done: null }, ui: { tour: null } })
  assert.equal(mount(html`<${Tour} s=${s} c=${recorder()} />`).text(), '')
})

// ---------------------------------------------------------------- the explain overlay (views/hints.js)

const { HintsLayer, HintsOverlay } = views.hints

test('hints: closed, the overlay draws nothing', () => {
  const s = cockpitState(NOW, { ui: { hints: false } })
  assert.equal(mount(html`<${HintsOverlay} s=${s} c=${recorder()} />`).text(), '')
})

test('hints: every placed hint has its numbered note, its ring and its arrow; Close and the tour act', () => {
  const layout = { view: { width: 1400, height: 900 }, away: [], rounds: [{ group: 'page', placed: [
    { id: 'ask', n: 1, shape: 'ellipse', ring: { top: 6, left: 700, width: 100, height: 44 },
      note: { top: 90, left: 640, width: 260, height: 80 }, arrow: { x1: 750, y1: 90, x2: 750, y2: 50 } },
    { id: 'detail', n: 2, shape: 'frame', ring: { top: 110, left: 10, width: 620, height: 770 },
      note: { top: 150, left: 50, width: 260, height: 80 }, arrow: null },
  ] }] }
  const c = recorder()
  const el = mount(html`<${HintsLayer} layout=${layout} c=${c} />`)
  assert.deepEqual(el.$$('.hints-note').map(n => n.getAttribute('data-hint')), ['ask', 'detail'])
  assert.deepEqual(el.$$('.hints-n').map(n => n.text()), ['1', '2'])
  assert.match(el.$('.hints-note').text(), new RegExp(en.hints.items.ask.title))
  assert.equal(el.$$('ellipse').length, 1)
  assert.equal(el.$$('rect').length, 1)
  assert.equal(el.$$('.hints-arrow').length, 1)
  assert.match(el.$('.hints-bar').text(), new RegExp(en.hints.groups.page))
  assert.equal(el.$$('.hints-bar button').filter(b => b.text() === en.hints.next).length, 0)   // one round: no Next
  assert.match(el.$('.hints-bar').text(), new RegExp(en.hints.barOne))                      // and no arrow keys promised
  el.button(en.hints.close).click()
  assert.deepEqual(c.calls.at(-1), ['setHints', false])
  el.button(en.hints.tour).click()
  assert.deepEqual(c.calls.at(-1), ['tourStart'])
})

test('hints: more than one round pages on with Next, Back and the arrow keys, the header last', async () => {
  const one = id => ({ id, n: 1, shape: 'ellipse', ring: { top: 6, left: 700, width: 100, height: 44 },
    note: { top: 90, left: 640, width: 260, height: 80 }, arrow: null })
  const layout = { view: { width: 1400, height: 900 }, away: ['table'],
    rounds: [{ group: 'page', placed: [one('rowMain')] }, { group: 'page', placed: [one('rowActs')] }, { group: 'head', placed: [one('ask')] }] }
  const went = []
  const first = mount(html`<${HintsLayer} layout=${layout} at=${0} go=${n => went.push(n)} c=${recorder()} />`)
  assert.deepEqual(first.$$('.hints-note').map(n => n.getAttribute('data-hint')), ['rowMain'])
  assert.match(first.$('.hints-bar').text(), new RegExp(en.hints.round(1, 3)))
  assert.match(first.$('.hints-bar').text(), new RegExp(en.hints.below(1).slice(0, 12)))   // one more further down
  first.button(en.hints.next).click()
  await tick()
  document.dispatch('keydown', { key: 'ArrowRight' })
  document.dispatch('keydown', { key: 'ArrowLeft' })          // nothing before the first round
  assert.deepEqual(went, [1, 1])
  const lastRound = mount(html`<${HintsLayer} layout=${layout} at=${2} go=${n => went.push(n)} c=${recorder()} />`)
  assert.deepEqual(lastRound.$$('.hints-note').map(n => n.getAttribute('data-hint')), ['ask'])
  assert.match(lastRound.$('.hints-bar').text(), new RegExp(en.hints.groups.head))
  assert.equal(lastRound.$$('.hints-bar button').filter(b => b.text() === en.hints.next).length, 0)
  lastRound.button(en.hints.back).click()
  assert.deepEqual(went.at(-1), 1)
})

test('hints: "What bothers you here?" keeps a sentence with the page and the area of a note clicked, calmly', async () => {
  const layout = { view: { width: 1400, height: 900 }, away: [], rounds: [{ group: 'page', placed: [
    { id: 'chatList', n: 1, shape: 'frame', ring: { top: 110, left: 10, width: 620, height: 500 },
      note: { top: 150, left: 50, width: 260, height: 80 }, arrow: null }] }] }
  const sent = []
  const c = { setHints: on => sent.push(['setHints', on]), tourStart() {}, explainNote: async args => { sent.push(['note', args]); return { ok: true } } }
  // without a place (an older caller) there is no field
  assert.equal(mount(html`<${HintsLayer} layout=${layout} c=${c} />`).$$('.hints-bar button').filter(b => b.text() === en.hints.noteOpen).length, 0)
  const el = mount(html`<${HintsLayer} layout=${layout} c=${c} place=${{ page: '@chat', view: '-' }} />`)
  el.button(en.hints.noteOpen).click()
  await tick()
  assert.ok(el.$('.hints-say'), 'the field opens above the bar')
  assert.match(el.$('.hints-say').text(), new RegExp(en.hints.notePick))
  // a click on a note picks its area and does not close the overlay
  el.$('.hints-note').click()
  await tick()
  assert.deepEqual(sent, [])
  assert.match(el.$('.hints-say').text(), new RegExp(en.hints.noteArea(en.hints.items.chatList.title)))
  typeInto(el.$('.hints-say input'), '  The question is gone after a reload  ')
  await tick()
  el.button(en.hints.noteSave).click()
  for (let i = 0; i < 20 && !el.$('.hints-noted'); i++) await tick()
  assert.deepEqual(sent, [['note', { text: 'The question is gone after a reload', page: '@chat', area: 'chatList' }]])
  assert.equal(el.$('.hints-say'), null, 'the field closes once noted')
  assert.equal(el.$('.hints-noted').text(), en.hints.noteSaved)
  assert.equal(text.TABLES.de.hints.noteOpen, 'Was stört hier?')
})

test('hints: while "What bothers you here?" is open a click beside a note keeps the field and its words', async () => {
  // 28.10.: a slight miss while picking a note closed the whole layer, and the sentence was gone without a word
  const layout = { view: { width: 1400, height: 900 }, away: [], rounds: [{ group: 'page', placed: [
    { id: 'chatList', n: 1, shape: 'frame', ring: { top: 110, left: 10, width: 620, height: 500 },
      note: { top: 150, left: 50, width: 260, height: 80 }, arrow: null }] }] }
  const sent = []
  const c = { setHints: on => sent.push(['setHints', on]), tourStart() {}, explainNote: async () => ({ ok: true }) }
  const el = mount(html`<${HintsLayer} layout=${layout} c=${c} place=${{ page: '@chat', view: '-' }} />`)
  el.button(en.hints.noteOpen).click()
  await tick()
  typeInto(el.$('.hints-say input'), 'The list jumps')
  await tick()
  assert.doesNotMatch(el.$('.hints-bar').text(), new RegExp(en.hints.barOne), 'the bar no longer says a click beside closes')
  el.$('.hints').click()
  await tick()
  assert.deepEqual(sent, [], 'nothing closed')
  assert.equal(el.$('.hints-say input').value, 'The list jumps')
  // Cancel closes the field, then a click beside closes the layer as before
  el.button(en.hints.noteCancel).click()
  await tick()
  el.$('.hints').click()
  assert.deepEqual(sent, [['setHints', false]])
})

test('hints: nothing in view says so instead of an empty overlay', () => {
  const el = mount(html`<${HintsLayer} layout=${{ view: { width: 800, height: 600 }, rounds: [], away: ['ask'] }} c=${recorder()} />`)
  assert.match(el.$('.hints-bar').text(), new RegExp(en.hints.none.slice(0, 20)))
})

// ---------------------------------------------------------------- look up (views/settings.js, under Appearance; K3)

test('look up: Appearance holds the signs, acting, the keys and costs, one topic at a time; the page notes are Explain\'s', async () => {
  const { SettingsPage } = views.settings
  const s = cockpitState(NOW, { ui: { page: '@settings', settingsSection: 'look', shortcuts: false } })
  const el = mount(html`<${SettingsPage} s=${s} c=${recorder()} />`)
  const card = el.$$('.set-card').find(x => x.$('.set-card-name')?.text() === en.settings.lookupTitle)
  assert.ok(card, 'the card stands under Appearance')
  assert.deepEqual(card.$$('.seg-btn').map(b => b.text()), ['rows', 'act', 'keys', 'trust'].map(id => en.help.tabs[id]))
  assert.match(card.text(), new RegExp(en.kindHelp))
  card.button(en.help.tabs.keys).click()
  await tick()
  assert.match(card.text(), new RegExp(en.keysOff.slice(0, 20)))
  // mouse first: while the keys are off the card names none, the card above switches them on
  assert.ok(!card.$('kbd'), 'no key while they are off')
  assert.ok(!card.$('dl.keys'), 'no key table while they are off')
  const on = mount(html`<${SettingsPage} s=${{ ...s, ui: { ...s.ui, shortcuts: true } }} c=${recorder()} />`)
  const onCard = on.$$('.set-card').find(x => x.$('.set-card-name')?.text() === en.settings.lookupTitle)
  onCard.button(en.help.tabs.keys).click()
  await tick()
  assert.ok(onCard.$('dl.keys kbd'), 'the keys stand there once they are on')
  card.button(en.help.tabs.trust).click()
  await tick()
  assert.match(card.text(), new RegExp(en.helpTopics.trust[0][0]))
  assert.doesNotMatch(card.text(), new RegExp(en.kindHelp))
  // the colours stand on the same page, the header has no button for them
  assert.ok(el.$$('.set-card-name').some(x => x.text() === en.settings.themeTitle))
})

// ---------------------------------------------------------------- NextUp

test('next up: a small bar under a detail opened from a list: back, where you stand, the next with "next", two more as links', () => {
  const { NextUp } = views.detail
  const s = cockpitState(NOW)
  const rows = [...(s.model.sections ?? []).flatMap(sec => sec.rows ?? [])].slice(0, 5)
  assert.equal(rows.length, 5)
  const byKey = new Map(rows.map(r => [r.key, r]))
  const entry = r => ({ how: 'peek', key: r.key, title: r.title })
  s.ui = { ...s.ui, pageDetail: true, selectedKey: rows[1].key, queue: rows.map(entry) }
  const c = recorder()
  const el = mount(html`<${NextUp} s=${s} c=${c} byKey=${byKey} current=${rows[1].key} />`)
  assert.ok(el.$('nav.next-up'))
  assert.equal(el.$('.next-up-pos').text(), en.nextPos(2, 5))
  assert.equal(el.$('.next-up-title').text(), rows[2].title)
  // the two after the next one stand open below it, each a click away
  assert.deepEqual(el.$$('.next-up-later button').map(b => b.text()), [rows[3].title, rows[4].title])
  el.button(en.nextOpen).click()
  assert.deepEqual(c.calls.at(-1), ['openNext', entry(rows[2])])
  el.$$('.next-up-later button')[1].click()
  assert.deepEqual(c.calls.at(-1), ['openNext', entry(rows[4])])
  el.button(en.nextPrev).click()
  assert.deepEqual(c.calls.at(-1), ['openNext', entry(rows[0])])
  // the next one was settled: it no longer counts, the one after moves up
  s.model = { ...s.model, sections: s.model.sections.map(sec => ({ ...sec, rows: (sec.rows ?? []).filter(r => r.key !== rows[2].key) })) }
  const el2 = mount(html`<${NextUp} s=${s} c=${recorder()} byKey=${byKey} current=${rows[1].key} />`)
  assert.equal(el2.$('.next-up-pos').text(), en.nextPos(2, 4))
  assert.equal(el2.$('.next-up-title').text(), rows[3].title)
  // the last one says so, and back still works
  const el3 = mount(html`<${NextUp} s=${s} c=${recorder()} byKey=${byKey} current=${rows[4].key} />`)
  assert.equal(el3.$('.next-up-title'), null)
  assert.match(el3.text(), new RegExp(en.nextDone.replace(/[.]/g, '\\.')))
  // a detail not opened from a list has no bar
  s.ui = { ...s.ui, queue: null }
  assert.equal(mount(html`<${NextUp} s=${s} c=${recorder()} byKey=${byKey} current=${rows[1].key} />`).$('nav.next-up'), null)
})

// ---------------------------------------------------------------- the start page walks like the lists

const { HomeList } = views.list
const { HomeFocusView } = views.focus
const homeOn = over => cockpitState(NOW, { ...over, home: { tiles: null, seen: null, pins: [] } })

test('the list on the start page opens a row with the rows it shows as the queue, so the bar under it walks on', () => {
  const c = recorder()
  const el = mount(html`<${HomeList} s=${homeOn()} c=${c} />`)
  const btn = el.$$('li.hl-line').find(li => li.$('.hl-num'))?.$('.hl-line-main')
  assert.ok(btn, 'the list shows an inbox row')
  const li = el.$$('li.hl-line').find(x => x.$('.hl-num'))
  assert.match(li.$('.hl-num').text(), /#\d+/, 'the number stands as a reference')
  assert.ok(Object.values(en.kind).some(k => li.$('.kind').text().includes(k)), 'what it is, in the words of Today')
  btn.click()
  const call = c.calls.find(x => x[0] === 'openItem' || x[0] === 'peek')
  assert.ok(call, 'a click opens the row')
  const queue = call[0] === 'openItem' ? call[5] : call[3]
  assert.ok(Array.isArray(queue) && queue.length > 1, 'it hands the queue over')
  assert.ok(queue.some(e => e.key === call[1]), 'the opened row stands in it')
})

test('the focus ends in the same bar the lists have: where you stand, Next, and at the end no circle', () => {
  const s = homeOn()
  const queue = views.focus.focusQueue(s)
  assert.ok(queue.length > 2, 'the demo has a queue')
  const c = recorder()
  const bar = mount(html`<${HomeFocusView} s=${s} c=${c} />`).$('.fx-work .next-up')
  assert.ok(bar, 'the bar stands under the step')
  assert.equal(bar.$('.next-up-pos').text(), en.nextPos(1, queue.length))
  bar.button(en.nextOpen).click()
  assert.deepEqual(c.calls.filter(x => x[0] === 'focusWalk'), [['focusWalk', queue[1].id, 1]])
  const last = queue.length - 1
  const end = mount(html`<${HomeFocusView} s=${homeOn({ ui: { focusAt: { id: queue[last].id, i: last } } })} c=${recorder()} />`).$('.fx-work .next-up')
  assert.equal(end.$('.next-up-pos').text(), en.nextPos(queue.length, queue.length))
  assert.equal(end.$$('button').some(b => b.text() === en.nextOpen), false, 'no Next at the end')
  assert.equal(end.$('.next-up-text').text(), en.nextDone)
  assert.equal(mount(html`<${HomeFocusView} s=${s} c=${recorder()} />`).$('.fx-nav'), null, 'no buttons of its own beside the bar')
})

// ---------------------------------------------------------------- GitHub boards: hidden on the page, chosen in the settings

const { GitHubBoard, BoardSettings } = views.github

function ghSection(s) {
  return s.model.pages.flatMap(p => p.sections ?? []).find(x => x.boards?.length)
}

test('github boards: a board switched off leaves the page, one line names it and opens the settings', () => {
  const s = cockpitState(NOW)
  const c = recorder()
  const section = ghSection(s)
  const el = mount(html`<${GitHubBoard} section=${section} filter=${null} setFilter=${() => {}} c=${c} s=${s} />`)
  const line = el.$('.ghb-hidden')
  assert.match(line.text(), /Old roadmap/)
  line.$('button').click()
  assert.deepEqual(c.calls.at(-1), ['openSettings', 'boards'])
})

test('github page (G4): only the figures with a cause stand above the list, no tile per board and no switch on the page', () => {
  const s = cockpitState(NOW)
  const c = recorder()
  const section = ghSection(s)
  const el = mount(html`<${GitHubBoard} section=${section} filter=${null} setFilter=${() => {}} c=${c} s=${s} />`)
  // the demo counts open, yours, your PRs, in progress, in review, closed and merged (no cause to look) and blocked 0
  assert.deepEqual(el.$$('.ghb-figure .ghb-label').map(x => x.text()), [en.gh.figure.ask_review, en.gh.figure.quiet, en.gh.figure.untasked])
  assert.ok(!el.$('.ghb-boards'), 'no tile per board: its facts stand in the head of its list')
  assert.ok(!el.$('.ghb-mode'), 'Off, Mine and All are chosen in the settings only')
  el.$$('.ghb-figure')[1].click()
  assert.deepEqual(c.calls, [])
  const picked = []
  const f = mount(html`<${GitHubBoard} section=${section} filter=${null} setFilter=${x => picked.push(x)} c=${c} s=${s} />`)
  f.$$('.ghb-figure')[1].click()
  assert.deepEqual(picked, [{ flag: 'quiet' }])
})

test('github list (G4): the head of a board names its facts, the cards it shows, how many are open by state, a cut', () => {
  const { GitHubList } = views.github
  const s = cockpitState(NOW)
  const base = ghSection(s)
  const section = { ...base, boards: base.boards.map(b => (b.name === 'Demo board' ? { ...b, capped: 200 } : b)) }
  const el = mount(html`<${GitHubList} items=${section.items} page="trackers" section=${section} s=${s} c=${recorder()} byKey=${new Map()} />`)
  const group = name => el.$$('.ghl-group').find(g => g.$('.ghl-head-name').text() === name)
  const facts = group('Demo board').$('.ghl-facts').text()
  for (const part of [en.gh.boardMode.mine, en.gh.boardOpen(9), `3 ${en.gh.state.new}`, `2 ${en.gh.state.in_progress}`, `1 ${en.gh.state.blocked}`, en.gh.capped(200)]) {
    assert.ok(facts.includes(part), `${part} in ${facts}`)
  }
  // rows the search adds without a board stand under their repository, with no board facts
  assert.ok(group('example/tools') && !group('example/tools').$('.ghl-facts'))
})

test('github rows (G4): one split start, the lead step left and the other steps under ▾, Close beside; a live tab leads with To tab', async () => {
  const { GitHubList } = views.github
  const s = cockpitState(NOW)
  const c = recorder()
  const it = { index: 0, key: 'item:github/boards/example/repo#5', title: 'example/repo#5 Fix it', actionable: true, row_id: 'example/repo#5',
    group: 'Demo board', flags: ['mine'], gh: { title: 'Fix it', repo: 'example/repo', number: 5, type: 'issue', state: 'ready' },
    actions: [{ id: 'analyze', label: 'Analyse' }, { id: 'implement', label: 'Implement' }, { id: 'sync', label: 'Sync status' }],
    link: { kind: 'web', href: 'https://example.org/repo/issues/5' } }
  const list = row => mount(html`<${GitHubList} items=${[row]} page="github" section=${{ id: 'boards', boards: [] }} s=${s} c=${c} byKey=${new Map()} />`)
  const el = list(it)
  const acts = el.$('.ghl-acts')
  const [lead, more] = acts.$('.btn-split').$$('button')
  assert.equal(lead.text(), 'Implement', 'yours to implement: the lead')
  assert.equal(more.text(), '▾')
  assert.ok(!acts.$('.start'), 'no second start beside the lead step')
  assert.ok(labels(acts).includes(`${en.settle} ▾`), 'Close beside it')
  lead.click()
  assert.deepEqual(c.calls.at(-1), ['act', 'row_action', { page: 'github', section: 'boards', index: 0, action: 'implement' }])
  more.click()
  await tick()
  assert.deepEqual(acts.$$('[role="menuitem"]').map(b => b.text()), ['Analyse', 'Sync status'])
  acts.$$('[role="menuitem"]')[0].click()
  assert.deepEqual(c.calls.at(-1), ['act', 'row_action', { page: 'github', section: 'boards', index: 0, action: 'analyze' }])
  // an agent works on the row: To tab leads, every step under ▾
  const live = list({ ...it, tab: { ref: 'surface:9', state: 'working', live: true, waiting: false } }).$('.ghl-acts')
  const [toTab, all] = live.$('.btn-split').$$('button')
  assert.equal(toTab.text(), en.btnToTab)
  toTab.click()
  assert.deepEqual(c.calls.at(-1), ['act', 'tab_jump', { tab_ref: 'surface:9' }])
  all.click()
  await tick()
  assert.deepEqual(live.$$('[role="menuitem"]').map(b => b.text()), ['Analyse', 'Implement', 'Sync status'])
  // a row with no step of its own: the general start is its one start
  const bare = list({ ...it, actions: null }).$('.ghl-acts')
  assert.ok(bare.$('.start') && !bare.$('.btn-split'))
})

// round 6c: a filter bar over the GitHub rows (Board, Person, Repository, Kind, Board status) and more on each row
function ghBarRows() {
  const row = (index, gh, over = {}) => ({ index, key: `item:github/boards/${index}`, title: gh.title, flags: [], actionable: true,
    gh: { type: 'issue', state: 'ready', people: [], labels: [], also_on: [], prs: [], ...gh }, ...over })
  return [
    row(1, { title: 'Fix the parser', repo: 'example/app', number: 1, board: 'Demo board', status: 'In Progress', people: ['demo-user'],
      labels: ['bug', 'ci', 'parser', 'p1', 'flaky'], author: 'teammate' }, { flags: ['mine'], group: 'Demo board' }),
    row(2, { title: 'Write the docs', repo: 'example/app', number: 2, board: 'Demo board', status: 'Todo',
      people: ['teammate', 'second-dev', 'third-dev', 'fourth-dev'], author: 'demo-user', by_me: true }, { group: 'Demo board' }),
    row(3, { title: 'Bump the schema', repo: 'example/tools', number: 3, board: null, status: 'open', type: 'pr', author: 'other-dev',
      people: ['other-dev'], pr: { draft: true, review: 'changes_requested', checks: 'failure' } }, { flags: ['ask_review'], group: 'example/tools' }),
  ]
}

function ghBar(filter = null, items = ghBarRows()) {
  const picked = []
  const section = { id: 'boards', items, boards: [{ name: 'Demo board', slug: 'demo', mode: 'mine', counts: {} }], metrics: [{ id: 'open', n: 3 }] }
  const el = mount(html`<${GitHubBoard} section=${section} items=${items} filter=${filter} setFilter=${f => picked.push(f)} c=${recorder()} s=${cockpitState(NOW)} />`)
  return { el, picked }
}

test('github filter bar (6c G1, 6d): Board, Assigned to, Opened by, Repository, Kind and Board status with counts, combined', () => {
  const { el, picked } = ghBar()
  const field = d => el.$(`.ghf-field[data-dim="${d}"] select`)
  for (const d of ['board', 'assignee', 'author', 'repo', 'type', 'status']) assert.ok(field(d), `a select for ${d}`)
  assert.ok(!field('person'), 'Person is split in two')
  assert.equal(el.$('.ghf-field[data-dim="assignee"] .ghf-label').text(), en.gh.bar.dim.assignee)
  assert.equal(el.$('.ghf-field[data-dim="author"] .ghf-label').text(), en.gh.bar.dim.author)
  const opts = d => field(d).$$('option').map(o => o.text())
  assert.deepEqual(opts('board'), [en.gh.bar.all(3), 'Demo board (2)', `${en.gh.bar.noBoard} (1)`])
  // Me first, then the most rows, your own login only as Me
  assert.deepEqual(opts('assignee'), [en.gh.bar.all(3), `${en.gh.bar.me} (1)`, '@fourth-dev (1)', '@other-dev (1)',
    '@second-dev (1)', '@teammate (1)', '@third-dev (1)'])
  assert.deepEqual(opts('author'), [en.gh.bar.all(3), `${en.gh.bar.me} (1)`, '@other-dev (1)', '@teammate (1)'])
  const nobody = ghBar(null, [...ghBarRows(), { ...ghBarRows()[0], index: 4, flags: [], gh: { ...ghBarRows()[0].gh, people: [] } }])
  assert.equal(nobody.el.$('.ghf-field[data-dim="assignee"] select').$$('option').at(-1).text(), `${en.gh.bar.nobody} (1)`, 'nobody last')
  assert.deepEqual(opts('type'), [en.gh.bar.all(3), `${en.gh.bar.kind.issue} (2)`, `${en.gh.bar.kind.pr} (1)`])
  assert.deepEqual(opts('status'), [en.gh.bar.all(3), 'In Progress (1)', 'Todo (1)'], 'only rows on a board have a column')
  assert.ok(!el.$('.ghf-reset'), 'nothing chosen: no reset')
  const sel = field('board')
  sel.value = 'Demo board'
  sel.dispatch('change')
  assert.deepEqual(picked.at(-1), { board: 'Demo board' })
  // a choice keeps the others: Person on top of Board; under that board every row is an issue, and Kind stays in its
  // place with that one value, so the bar does not jump (walk of 28.10.)
  const two = ghBar({ board: 'Demo board' })
  assert.deepEqual(two.el.$('.ghf-field[data-dim="type"] select').$$('option').map(o => o.text()), [en.gh.bar.all(2), `${en.gh.bar.kind.issue} (2)`])
  const person = two.el.$('.ghf-field[data-dim="assignee"] select')
  person.value = 'teammate'
  person.dispatch('change')
  assert.deepEqual(two.picked.at(-1), { board: 'Demo board', assignee: 'teammate' })
  // back to all in one dimension leaves the rest
  const all = two.el.$('.ghf-field[data-dim="board"] select')
  all.value = ''
  all.dispatch('change')
  assert.deepEqual(two.picked.at(-1), { board: null })
})

test('github filter bar (6c G1): with a choice it says how many rows it shows and resets every filter in one click', () => {
  const { el, picked } = ghBar({ assignee: '@me', flag: 'mine' })
  assert.equal(el.$('.ghf-count').text(), en.gh.bar.count(1, 3), 'Me and the figure yours: the one row assigned to you')
  const reset = el.$('.ghf-reset')
  assert.equal(reset.text(), en.gh.bar.reset)
  reset.click()
  assert.deepEqual(picked.at(-1), null)
  // a dimension with one value only and nothing chosen stays out of the way
  const lone = ghBar(null, ghBarRows().filter(r => r.gh.repo === 'example/app'))
  assert.ok(!lone.el.$('.ghf-field[data-dim="repo"]'), 'one repository: no select')
  assert.ok(lone.el.$('.ghf-field[data-dim="assignee"]') && lone.el.$('.ghf-field[data-dim="author"]'))
})

test('github rows (6c G2): repository and number, board and column, people, labels three and +n, who opened it, a PR\'s state', () => {
  const { GitHubList } = views.github
  const s = cockpitState(NOW)
  const rows = ghBarRows()
  const el = mount(html`<${GitHubList} items=${rows} page="github" section=${{ id: 'boards', boards: [{ name: 'Demo board', mode: 'mine' }] }}
    s=${{ ...s, ui: { ...s.ui, ghGroup: false } }} c=${recorder()} byKey=${new Map()} />`)
  assert.ok(!el.$('.ghl-head'), 'not grouped: one list without board heads')
  const row = n => el.$$('.ghl-row').find(r => r.$('.ghl-title').text() === n)
  const first = row('Fix the parser')
  assert.equal(first.$('.ghl-ref').text(), 'app#1')
  assert.equal(first.$('.ghl-chip-board').text(), 'Demo board', 'not grouped: the row names its board')
  assert.equal(first.$('.ghl-state').text(), 'In Progress')
  assert.deepEqual(first.$$('.ghl-meta .gh-label').map(x => x.text()), ['bug', 'ci', 'parser'])
  assert.equal(first.$('.ghl-more').text(), '+2')
  assert.equal(first.$('.ghl-more').getAttribute('title'), 'p1, flaky')
  // round 6d: who it is assigned to and who opened it, both on every row; you as you
  assert.equal(first.$('.ghl-author').text(), en.gh.by('teammate'))
  assert.equal(first.$('.ghl-people').text(), `${en.gh.assigned} ${en.gh.you}`)
  const docs = row('Write the docs')
  assert.equal(docs.$('.ghl-people-label').text(), en.gh.assigned)
  assert.deepEqual(docs.$$('.ghl-people .gh-person').map(x => x.text()), ['@teammate', '@second-dev', '@third-dev', '+1'])
  assert.equal(docs.$('.ghl-author').text(), en.gh.byYou, 'opened by you')
  const pr = row('Bump the schema')
  assert.ok(!pr.$('.ghl-chip-board'), 'on no board')
  assert.deepEqual(pr.$$('.ghl-pr').map(x => x.text()), [en.gh.draft, en.gh.reviewState.changes_requested, en.gh.checksShort.failure])
  assert.equal(pr.$('.ghl-author').text(), en.gh.by('other-dev'), 'opened by the one assigned: both still said')
  assert.deepEqual(pr.$$('.ghl-people .gh-person').map(x => x.text()), ['@other-dev'])
  // nobody assigned says so; a row whose author is unknown names none
  const bare = mount(html`<${GitHubList} items=${[{ ...rows[0], flags: [], gh: { ...rows[0].gh, people: [], author: null } }]} page="github"
    section=${{ id: 'boards', boards: [] }} s=${s} c=${recorder()} byKey=${new Map()} />`)
  assert.equal(bare.$('.ghl-nobody').text(), en.gh.nobodyAssigned)
  assert.ok(!bare.$('.ghl-author') && !bare.$('.ghl-people .gh-person'))
  // grouped (the default): the heads stand, the rows leave the board out
  const grouped = mount(html`<${GitHubList} items=${rows} page="github" section=${{ id: 'boards', boards: [] }} s=${s} c=${recorder()} byKey=${new Map()} />`)
  assert.ok(grouped.$('.ghl-head'))
  assert.ok(!grouped.$('.ghl-chip-board'))
})

test('github rows (6d): a click on a name sets that filter, beside the choices made; the search finds a person by @login', async () => {
  const { GitHubList } = views.github
  const s = cockpitState(NOW)
  const picked = []
  const el = mount(html`<${GitHubList} items=${ghBarRows()} page="github" section=${{ id: 'boards', boards: [] }} s=${s} c=${recorder()}
    byKey=${new Map()} filter=${{ board: 'Demo board' }} setFilter=${f => picked.push(f)} />`)
  const row = n => el.$$('.ghl-row').find(r => r.$('.ghl-title').text() === n)
  row('Write the docs').$$('.ghl-people .gh-person').find(x => x.text() === '@second-dev').click()
  assert.deepEqual(picked.at(-1), { board: 'Demo board', assignee: 'second-dev' })
  row('Fix the parser').$('.ghl-people .gh-person').click()
  assert.deepEqual(picked.at(-1), { board: 'Demo board', assignee: '@me' }, 'you are Me')
  row('Fix the parser').$('.ghl-author .gh-person').click()
  assert.deepEqual(picked.at(-1), { board: 'Demo board', author: 'teammate' })
  row('Write the docs').$('.ghl-author .gh-person').click()
  assert.deepEqual(picked.at(-1), { board: 'Demo board', author: '@me' })
  // without a filter to set (an older caller) the names are plain text
  const plain = mount(html`<${GitHubList} items=${ghBarRows()} page="github" section=${{ id: 'boards', boards: [] }} s=${s} c=${recorder()} byKey=${new Map()} />`)
  assert.ok(!plain.$('button.gh-person'))
  const box = el.$('.ghl-search')
  box.value = '@second-dev'
  box.dispatch('input')
  for (let i = 0; i < 20 && el.$$('.ghl-row').length !== 1; i++) await tick()
  assert.deepEqual(el.$$('.ghl-title').map(x => x.text()), ['Write the docs'])
})

test('github list (6c G2): "Group by board" switches the heads off and on, kept for the viewer', () => {
  const { GitHubList } = views.github
  const s = cockpitState(NOW)
  const c = recorder()
  const el = mount(html`<${GitHubList} items=${ghBarRows()} page="github" section=${{ id: 'boards', boards: [] }} s=${s} c=${c} byKey=${new Map()} />`)
  const toggle = el.$('.ghl-group-toggle')
  assert.equal(toggle.text(), en.gh.groupByBoard)
  assert.equal(toggle.getAttribute('aria-pressed'), 'true')
  toggle.click()
  assert.deepEqual(c.calls.at(-1), ['setGhGroup', false])
})

test('github page (6c G1): the section reads its kept filter, a new choice goes to the controller under page and section', () => {
  const { PageSection } = views.pages
  const base = cockpitState(NOW)
  const page = base.model.pages.find(p => p.id === 'trackers')
  const section = ghSection(base)
  const c = recorder()
  const s = cockpitState(NOW, { ui: { ghFilter: { 'trackers/mine': { type: 'pr' } } } })
  const el = mount(html`<${PageSection} page=${page} section=${section} s=${s} c=${c} />`)
  assert.deepEqual(el.$$('.ghl-title').map(x => x.text()), ['Release checklist'], 'only the pull request')
  assert.ok(el.$('.ghf-reset'))
  const board = el.$('.ghf-field[data-dim="type"] select')
  board.value = ''
  board.dispatch('change')
  assert.deepEqual(c.calls.at(-1), ['setGhFilter', 'trackers/mine', { type: null }])
  // a kept choice no row matches: the bar stays, so it can be taken back, and the list says nothing matches
  const none = mount(html`<${PageSection} page=${page} section=${section} c=${recorder()}
    s=${cockpitState(NOW, { ui: { ghFilter: { 'trackers/mine': { repo: 'example/gone' } } } })} />`)
  assert.ok(none.$('.ghf-reset') && !none.$('.ghl-row'))
  assert.match(none.text(), new RegExp(en.filterNone))
})

test('github boards: the settings list every board, the hidden ones too, and the default for new boards', () => {
  const s = cockpitState(NOW)
  const c = recorder()
  const section = ghSection(s)
  const el = mount(html`<${BoardSettings} s=${s} c=${c} />`)
  assert.deepEqual(el.$$('.board-set-name').map(x => x.text()), ['Demo board', 'Docs board', 'Old roadmap'])
  const rows = el.$$('.board-set-row')
  rows[2].$$('button').find(b => b.text() === en.gh.mode.mine).click()
  assert.deepEqual(c.calls.at(-1), ['act', 'github_board', { section: section.id, slug: 'old-roadmap', mode: 'mine' }])
  const fresh = el.$('.board-set-default')
  assert.deepEqual(labels(fresh), [en.gh.defaultMode.profile, en.gh.mode.off, en.gh.mode.mine, en.gh.mode.all])
  fresh.$$('button').find(b => b.text() === en.gh.mode.off).click()
  assert.deepEqual(c.calls.at(-1), ['act', 'github_board_default', { mode: 'off' }])
})

test('github boards: without a GitHub section the settings say where boards come from', () => {
  const s = cockpitState(NOW)
  s.model = { ...s.model, pages: [] }
  const el = mount(html`<${BoardSettings} s=${s} c=${recorder()} />`)
  assert.match(el.text(), new RegExp(en.gh.noBoards.slice(0, 20)))
})

// ---------------------------------------------------------------- cockpit.focus_to_files: the focus leads on into the files

test('the calm card of the focus opens the tasks, or with cockpit.focus_to_files the files view', () => {
  const { Calm } = views.focus
  const c = recorder()
  const el = mount(html`<${Calm} s=${homeOn()} c=${c} />`)
  assert.equal(el.$('.fx-calm .fx-acts button').text(), en.home.focus.toWork)
  assert.equal(el.$('.fx-calm p').text(), en.home.focus.nothingSub)
  const on = recorder()
  const files = mount(html`<${Calm} s=${homeOn({ work: { view: 'due', focus_to_files: true } })} c=${on} />`)
  assert.equal(files.$('.fx-calm p').text(), en.home.focus.nothingSubFiles)
  files.button(en.home.focus.toFiles).click()
  assert.deepEqual(on.calls, [['openFiles']])
})

test('with cockpit.focus_to_files the last step of the focus offers the files view in place of the end line', () => {
  const s = homeOn({ work: { view: 'due', focus_to_files: true } })
  const queue = views.focus.focusQueue(s)
  const last = queue.length - 1
  const c = recorder()
  const end = mount(html`<${HomeFocusView} s=${{ ...s, ui: { ...s.ui, focusAt: { id: queue[last].id, i: last } } }} c=${c} />`).$('.fx-work .next-up')
  end.button(en.home.focus.toFiles).click()
  assert.deepEqual(c.calls.filter(x => x[0] === 'openFiles'), [['openFiles']])
  // before the end the bar walks on as always
  const mid = mount(html`<${HomeFocusView} s=${s} c=${recorder()} />`).$('.fx-work .next-up')
  assert.equal(mid.$$('button').some(b => b.text() === en.home.focus.toFiles), false)
})

test('with cockpit.focus_to_files a focus of one step still offers the files view, where no bar stands', () => {
  const s = homeOn({ work: { view: 'due', focus_to_files: true } })
  const one = views.focus.focusQueue(s).slice(0, 1)
  assert.equal(one.length, 1, 'the demo state has a step')
  const c = recorder()
  const done = html`<button type="button" class="btn-link" onClick=${() => c.openFiles()}>${en.home.focus.toFiles}</button>`
  const el = mount(html`<div><${views.focus.FocusWalk} queue=${one} i=${0} s=${s} c=${c} done=${done} /></div>`)
  assert.equal(el.$('.next-up'), null, 'no bar for one step')
  el.button(en.home.focus.toFiles).click()
  assert.deepEqual(c.calls, [['openFiles']])
  // without the switch one step stands alone, as before
  const plain = mount(html`<div><${views.focus.FocusWalk} queue=${one} i=${0} s=${s} c=${recorder()} /></div>`)
  assert.equal(plain.$$('button').length, 0)
})

test('the demo shows the work tab as the default config does, and ?work=files&focus_to_files=1&files_scope=all as the switches do', () => {
  const { mock } = loadedRooms
  const work = st => { const { flow, views, files_search: _fs, ...rest } = st.work; return rest }
  // the files tab's question to its records is on in the demo, the Health area kept private (round 6c)
  assert.deepEqual(mock.buildState(NOW).work.files_search, { enabled: true, block: ['Health'], left: 20 })
  // every view of the work tab (cockpit.work_views), ?views=files,flow narrows it
  assert.deepEqual(mock.buildState(NOW).work.views, ['due', 'source', 'jev', 'files', 'flow'])
  assert.deepEqual(mock.buildState(NOW, { views: ['files', 'flow'] }).work.views, ['files', 'flow'])
  assert.deepEqual(work(mock.buildState(NOW)), { view: 'due', focus_to_files: false, files_scope: 'active' })
  assert.deepEqual(work(mock.buildState(NOW, { work: 'files', focusToFiles: true, filesScope: 'all' })), { view: 'files', focus_to_files: true, files_scope: 'all' })
  assert.deepEqual(work(mock.buildState(NOW, { work: 'tiles', filesScope: 'some' })), { view: 'due', focus_to_files: false, files_scope: 'active' })
  // the Work through page is on in the demo, ?flow=0 shows the cockpit without it
  assert.equal(mock.buildState(NOW).work.flow.enabled, true)
  assert.equal(mock.buildState(NOW, { flow: false }).work.flow.enabled, false)
  // the demo lists every file, the backlog too, so ?files_scope=all has something to show
  assert.ok(mock.buildState(NOW).model.files.some(f => f.status === 'backlog'))
})

// ---------------------------------------------------------------- where a row comes from, task or stream

const workRows = s => [...(s.model.sections ?? []).flatMap(x => x.rows), ...(s.model.hidden ?? []), ...(s.model.task_rows ?? [])]
const workRow = (s, key) => workRows(s).find(r => r.key === key)
const wordOf = (o, t) => (o.category === 'work' ? t.origin.work[o.word_key] : o.category === 'tracker' ? o.word_key : t.origin[o.category])

test('origin: every row of the demo shows the kind first, then its source as a word, a detail and the raw text in the tooltip', () => {
  const { RowMeta } = views.day
  const s = cockpitState(NOW)
  const seen = new Set()
  for (const row of workRows(s)) {
    const el = mount(html`<${RowMeta} row=${row} s=${s} />`)
    const meta = el.$('.row-meta')
    const first = meta.childNodes.find(n => n.localName)
    assert.ok(first?.hasClass('kind'), `${row.key}: the kind stands first`)
    // then the origin, with only the kind's own "about" part between them
    const els = meta.childNodes.filter(n => n.localName)
    const at = els.findIndex(n => n.hasClass('origin'))
    if (at >= 0) assert.ok(els.slice(1, at).every(n => n.hasClass('kind-about')), `${row.key}: then the origin`)
    const o = row.origin
    if (!o || (o.category === 'other' && !o.detail)) {
      // no source written down: still a tag, a neutral "Other source · unknown"
      assert.equal(el.$('.origin .origin-word').text(), en.origin.other, row.key)
      assert.equal(el.$('.origin .origin-detail').text(), en.originUnknown, row.key)
      continue
    }
    seen.add(o.category)
    const chip = el.$('.origin')
    assert.ok(chip, `${row.key}: an origin chip`)
    assert.equal(chip.$('.origin-word').text(), wordOf(o, en), row.key)
    if (o.detail) assert.equal(chip.$('.origin-detail').text(), o.detail, row.key)
    assert.ok(chip.getAttribute('title').startsWith(o.raw || en.originTitle[o.category]), `${row.key}: ${chip.getAttribute('title')}`)
    assert.equal(chip.$('.sr-only').text(), en.originSpoken, 'a spoken prefix')
  }
  for (const c of ['github', 'tracker', 'calendar', 'bot', 'session', 'skill', 'work', 'person', 'bridge', 'other']) {
    assert.ok(seen.has(c), `the demo shows a ${c} row`)
  }
})

test('origin: a stream says Stream, a report from its tab says about Stream, in both languages', () => {
  const { RowMeta, KindTag } = views.day
  const s = cockpitState(NOW)
  const stream = mount(html`<${RowMeta} row=${workRow(s, 'task:team-onboarding')} s=${s} />`)
  assert.ok(stream.$('.kind').hasClass('kind-stream'))
  assert.equal(stream.$('.kind').text(), `↻${en.kind.stream}`)
  const note = workRow(s, 'inbox:20261009-0930-onboarding-note-b1c2')
  const el = mount(html`<${KindTag} row=${note} s=${s} />`)
  assert.match(el.text(), new RegExp(`${en.kindAbout} ↻ ${en.kind.stream}: Onboard the new team members`))
  text.setLanguage('de')
  try {
    const de = text.TABLES.de
    const el2 = mount(html`<${RowMeta} row=${note} s=${s} />`)
    assert.match(el2.text(), new RegExp(`zu ↻ Stream:`))
    assert.equal(el2.$('.origin .sr-only').text(), 'Quelle:')
    assert.equal(el2.$('.origin-word').text(), de.origin.session)
  } finally {
    text.setLanguage('en')
  }
})

test('origin: a GitLab row names its board, a row the cockpit filed names the board row it came from', () => {
  const { RowMeta } = views.day
  const s = cockpitState(NOW)
  const gl = mount(html`<${RowMeta} row=${workRow(s, 'item:grp/app#3')} s=${s} />`)
  assert.equal(gl.$('.origin-word').text(), 'GitLab')
  assert.doesNotMatch(gl.text(), /GitHub/)
  const filed = mount(html`<${RowMeta} row=${workRow(s, 'inbox:20261009-0940-filed-board-c2d3')} s=${s} />`)
  assert.equal(filed.$('.origin-word').text(), en.origin.github)
  assert.match(filed.$('.origin').getAttribute('title'), new RegExp(en.originViaCockpit))
  assert.equal(filed.$('.origin-ref').text(), 'example/repo#15', 'the board row it came from')
})

test('origin: no origin still draws a neutral Other source, unknown, and breaks nothing', () => {
  const { OriginTag, KindTag, RowMeta } = views.day
  for (const vnode of [html`<${OriginTag} origin=${null} />`, html`<${OriginTag} row=${{ origin: { category: 'other', detail: null } }} />`,
    html`<${OriginTag} row=${{}} />`]) {
    const el = mount(vnode)
    assert.equal(el.$('.origin-word').text(), en.origin.other)
    assert.equal(el.$('.origin-detail').text(), en.originUnknown)
    assert.equal(el.$('.origin').getAttribute('title'), en.originNone)
    assert.equal(el.$('.sr-only').text(), en.originSpoken)
  }
  const s = cockpitState(NOW)
  assert.equal(mount(html`<${KindTag} row=${{}} s=${s} />`).$('.kind').text(), `•${en.kind.other}`)
  assert.ok(mount(html`<${RowMeta} row=${{ key: 'x', title: 'x', origin: null }} s=${s} />`).$('.kind'))
})

test('origin: By source and the detail show both tags, the board list its ref for a GitHub row, the detail the raw text in full beside the sources', () => {
  const { PageSection } = views.pages
  const s = cockpitState(NOW)
  const page = s.model.pages.find(p => p.id === 'trackers')
  const tasks = page.sections.find(x => x.id === 'tasks')
  const el = mount(html`<${PageSection} page=${page} section=${tasks} s=${s} c=${recorder()} />`)
  const tags = el.$('.info-kinds')
  assert.ok(tags, 'kind and origin on a By source row')
  assert.match(tags.text(), new RegExp(en.kind.task))
  assert.equal(tags.$('.origin-word').text(), en.origin.bridge)
  const { GitHubList } = views.github
  const mine = page.sections.find(x => x.id === 'mine')
  const gh = mount(html`<${GitHubList} items=${mine.items} page=${page.id} section=${mine.id} s=${s} c=${recorder()} byKey=${new Map()} />`)
  // a GitHub row says where it comes from by its repo#n; the chip GitHub beside it would say it twice (6c fix)
  assert.ok(gh.$('.ghl-ref'))
  assert.ok(!gh.$$('.ghl-row').some(r => r.$('.origin-word')?.text() === en.origin.github))
  // the detail: the kind and the origin in its head, the raw text in the facts, the sources row kept
  const { DetailColumn } = views.detail
  const { indexRows } = loadedRooms.logic
  const key = 'inbox:20261009-0910-tidy-labels-c3d4'
  const ds = cockpitState(NOW, { ui: { selectedKey: key, queue: null } })
  const d = mount(html`<${DetailColumn} s=${ds} c=${recorder()} byKey=${indexRows(ds.model)} />`)
  assert.ok(d.$('.detail-kind .kind') && d.$('.detail-kind .origin'))
  assert.equal(d.$('.meta-from-raw').text(), 'homebox/issue-radar')
  const dts = d.$$('dt').map(x => x.text())
  assert.ok(dts.includes(en.meta.from) && dts.includes(en.meta.sources), dts.join(', '))
})

test('origin: the drawer opened by a stream key alone says Stream, the focus card and the return card show the tags', async () => {
  const { ItemDrawer } = views.overlays
  // the drawer moves the focus into itself after it mounts; this small DOM has no selector engine for that
  const Element = Object.getPrototypeOf(document.body).constructor
  const had = Object.getOwnPropertyDescriptor(Element.prototype, 'querySelector')
  Element.prototype.querySelector = () => null
  const { indexRows } = loadedRooms.logic
  const s = cockpitState(NOW, { ui: { item: { key: 'task:pilot-plan', it: { title: 'Pilot plan' } } } })
  s.details = { inbox: {}, task: { 'pilot-plan': { status: 'ok', ver: s.model.collected_ms, data: { ok: true, slug: 'pilot-plan', kind: 'stream', work_kind: 'stream',
    origin: { category: 'bridge', word_key: null, detail: null, raw: null, ref: null, via_cockpit: false }, front: {}, sections: [], log: [], inbox: [], path: 'work/streams/pilot-plan/STATUS.md' } } } }
  const d = mount(html`<${ItemDrawer} s=${s} c=${recorder()} byKey=${indexRows(s.model)} />`)
  assert.equal(d.$('.idrawer-head .kind').text(), `↻${en.kind.stream}`)
  await new Promise(r => setTimeout(r, 40))
  if (had) Object.defineProperty(Element.prototype, 'querySelector', had)
  else delete Element.prototype.querySelector
  const { Hero, After } = views.focus
  const fs = cockpitState(NOW)
  const x = { kind: 'row', id: 'task:team-onboarding', row: workRow(fs, 'task:team-onboarding') }
  const hero = mount(html`<${Hero} x=${x} n=${2} tabOf=${() => null} s=${fs} c=${recorder()} />`)
  assert.ok(hero.$('.fx-meta .kind-stream') && hero.$('.fx-meta .origin'))
  const after = mount(html`<${After} queue=${[x, { kind: 'row', id: 'ref:example/repo#12', row: workRow(fs, 'ref:example/repo#12') }]} i=${0} onPick=${() => {}} s=${fs} />`)
  assert.equal(after.$('.fx-card .origin-word').text(), en.origin.github)
  const { el } = renderReturn(start({ key: 'inbox:20261009-0915-update-docs-e5f6' }))
  assert.equal(el.$('.rcard-tags .origin-word').text(), en.origin.session)
})

test('origin: the check table names task or stream, the week names a closed task and an ended stream', () => {
  const { ReviewBody } = views.check
  const s = cockpitState(NOW, { ui: { rvFilter: 'all', rvSort: null, rvPicked: [] } })
  const el = mount(html`<${ReviewBody} s=${s} c=${recorder()} inline />`)
  assert.ok(el.$$('.c-task .kind').length >= 1)
  assert.equal(el.$$('.c-task .origin').length, el.$$('.c-task .kind').length, 'the check table names the source too')
  assert.deepEqual(s.model.week.items.map(x => x.work_kind), ['done_task', 'done_stream'])
})

// ---------------------------------------------------------------- task or stream, and the source, in every place

/** Mounts a view that moves the focus into itself after it mounts (a drawer, a dialog in the detail), which this
 *  small DOM has no selector engine for */
async function settled(vnode) {
  const Element = Object.getPrototypeOf(document.body).constructor
  const had = Object.getOwnPropertyDescriptor(Element.prototype, 'querySelector')
  Element.prototype.querySelector = () => null
  try {
    const d = mount(vnode)
    await new Promise(r => setTimeout(r, 200))
    return d
  } finally {
    if (had) Object.defineProperty(Element.prototype, 'querySelector', had)
    else delete Element.prototype.querySelector
  }
}

function drawer(s) {
  const { ItemDrawer } = views.overlays
  const { indexRows } = loadedRooms.logic
  return settled(html`<${ItemDrawer} s=${s} c=${recorder()} byKey=${indexRows(s.model)} />`)
}

const SESSION = { category: 'session', word_key: null, detail: 'claude', raw: 'claude', ref: null, via_cockpit: false }
const streamDetail = (s, over = {}) => ({ status: 'ok', ver: s.model.collected_ms, data: { ok: true, slug: 'team-onboarding', kind: 'stream',
  work_kind: 'stream', origin: { category: 'bridge', word_key: null, detail: null, raw: null, ref: null, via_cockpit: false },
  front: { headline: 'Onboard the new team members', status: 'doing' }, sections: [], log: [], path: 'work/streams/team-onboarding/STATUS.md',
  inbox: [{ id: '20261009-0930-onboarding-note-b1c2', summary: 'Accounts are ready', origin: SESSION }], ...over } })

test('kind: the drawer of a report about a stream names the stream as a stream, its button too', async () => {
  const id = '20261009-0930-onboarding-note-b1c2'
  const s = cockpitState(NOW, { ui: { item: { key: `inbox:${id}`, it: { title: 'Note' } } } })
  s.details = { inbox: { [id]: { status: 'ok', ver: s.model.collected_ms, data: { ok: true, id, events: [], origin: SESSION,
    item: { summary: 'Accounts are ready', task: 'team-onboarding', from: 'claude' } } } }, task: { 'team-onboarding': streamDetail(s) } }
  const d = await drawer(s)
  const card = d.$('.idrawer-task')
  assert.equal(card.$('.kind').text(), `↻${en.kind.stream}`)
  assert.doesNotMatch(card.text(), new RegExp(`^${en.item.task}`))
  assert.ok(card.$$('button').some(b => b.text() === en.item.openKind.stream), card.text())
})

test('kind and origin: the drawer of a stream heads its inbox list with "this stream" and names who filed each', async () => {
  const s = cockpitState(NOW, { ui: { item: { key: 'task:team-onboarding', it: { title: 'Onboard' } } } })
  s.details = { inbox: {}, task: { 'team-onboarding': streamDetail(s) } }
  const d = await drawer(s)
  assert.ok(d.$$('h3').some(h => h.text() === en.item.related('stream')), d.$$('h3').map(h => h.text()).join(' | '))
  assert.equal(d.$('.entries .origin-word').text(), en.origin.session)
})

test('kind and origin: the detail of a stream says Stream in its head and tags every inbox entry of it', async () => {
  const { DetailColumn } = views.detail
  const { indexRows } = loadedRooms.logic
  const s = cockpitState(NOW, { ui: { selectedKey: 'task:team-onboarding', queue: null } })
  s.details = { inbox: {}, task: { 'team-onboarding': streamDetail(s) } }
  const d = await settled(html`<${DetailColumn} s=${s} c=${recorder()} byKey=${indexRows(s.model)} />`)
  const head = d.$('.task-detail h3').text()
  assert.ok(head.startsWith(`${en.kind.stream}:`), head)
  assert.ok(d.$$('.task-detail h4').some(h => h.text() === en.taskEntries('stream')))
  const entry = d.$('.task-detail .entries .entry')
  assert.ok(entry.$('.kind') && entry.$('.origin'), entry.text())
  assert.equal(entry.$('.origin-word').text(), en.origin.session)
})

test('kind: the history says Stream for an ended stream, Task for a task', async () => {
  const { HistoryDrawer } = views.overlays
  const s = cockpitState(NOW)
  s.history = [{ id: 'h1', at_ms: NOW, verb: 'task_close', items: [
    { key: 'task:team-onboarding', title: 'Onboard', kind: 'task', work_kind: 'stream', did: 'done', ident: 'team-onboarding', undo: null },
    { key: 'task:x', title: 'X', kind: 'task', work_kind: 'task', did: 'done', ident: 'x', undo: null }] }]
  const el = await settled(html`<${HistoryDrawer} s=${s} c=${recorder()} />`)
  assert.deepEqual(el.$$('.hist-what .chip').map(x => x.text()), [en.histKind.stream, en.histKind.task])
})

test('history: undo brings a task back with the status it had before the close, never forced to doing (K2)', async () => {
  const { HistoryDrawer } = views.overlays
  const s = cockpitState(NOW)
  const back = (slug, as) => ({ verb: 'task_reopen', args: { slug, ...(as ? { as } : {}) } })
  s.history = [{ id: 'h2', at_ms: NOW, verb: 'task_close', items: [
    { key: 'task:in-review', title: 'In review', kind: 'task', did: 'done', ident: 'in-review', undo: back('in-review', 'review') },
    { key: 'task:in-backlog', title: 'In backlog', kind: 'task', did: 'done', ident: 'in-backlog', undo: back('in-backlog', 'backlog') },
    { key: 'task:older', title: 'Older', kind: 'task', did: 'done', ident: 'older', undo: back('older') }] }]
  const c = recorder()
  const el = await settled(html`<${HistoryDrawer} s=${s} c=${c} />`)
  const rows = el.$$('.hist-item')
  const review = rows[0].$$('button')
  assert.deepEqual(review.map(b => b.text()), [en.undoReview, en.undoBacklog])
  review[0].click()
  assert.deepEqual(c.calls.at(-1), ['undo', s.history[0].items[0].undo])
  review[1].click()
  assert.deepEqual(c.calls.at(-1), ['undo', s.history[0].items[0].undo, 'backlog'])
  // closed out of the backlog: the one way back is the backlog
  const backlog = rows[1].$$('button')
  assert.deepEqual(backlog.map(b => b.text()), [en.undoBacklog])
  backlog[0].click()
  assert.deepEqual(c.calls.at(-1), ['undo', s.history[0].items[1].undo])
  // an older entry without the status: open again as before, or still to be done
  assert.deepEqual(rows[2].$$('button').map(b => b.text()), [en.undoReopen, en.undoBacklog])
})

test('origin: the files view lists the inbox entries of a file with who filed them', () => {
  const { Drawers } = views.dossier
  const s = cockpitState(NOW)
  const el = mount(html`<${Drawers} data=${streamDetail(s).data} s=${s} c=${recorder()} />`)
  const entry = el.$('.entries .entry')
  assert.equal(entry.$('.kind').text(), `◆${en.kind.inbox}`)
  assert.equal(entry.$('.origin-word').text(), en.origin.session)
})

test('kind: a search hit in work/done says closed task or ended stream by the server, never guesses task', () => {
  const { placeKind, rowKind } = loadedRooms.logic
  assert.equal(placeKind('work/done/2026-09/x'), 'done')
  assert.equal(rowKind({ task: 'x', work_kind: 'done' }).kind, 'done')
  const { KindTag } = views.day
  assert.equal(mount(html`<${KindTag} row=${{ key: 'task:x', task: 'x', work_kind: 'done' }} s=${null} />`).$('.kind').text(), `✓${en.kind.done}`)
  assert.equal(mount(html`<${KindTag} row=${{ key: 'task:x', task: 'x', work_kind: 'done_stream' }} s=${null} />`).$('.kind').text(), `↻✓${en.kind.done_stream}`)
})

test('kind: a board row names the closed task or the ended stream it syncs with', () => {
  const { ghPlaceChip } = views.github
  assert.equal(ghPlaceChip({ work_kind: 'done_stream' }, { task: 'x', stream: true }, en), `${en.kind.done_stream} x`)
  assert.equal(ghPlaceChip({ work_kind: 'done_task' }, { task: 'x' }, en), `${en.kind.done_task} x`)
  assert.equal(ghPlaceChip({ work_kind: 'stream' }, { task: 'x' }, en), en.gh.streamChip('x'))
  assert.equal(ghPlaceChip({}, { task: 'x', stream: true }, en), en.gh.streamChip('x'))
})

test('walk: the entries after the next one carry their tags too', () => {
  const { WalkBar } = views.parts
  const el = mount(html`<${WalkBar} label="walk" next=${{ key: 'a', title: 'A', sub: html`<span class="tag-a">A</span>`, onOpen: () => {} }}
    later=${[{ key: 'b', title: 'B', sub: html`<span class="tag-b">B</span>`, onOpen: () => {} }]} done="done" />`)
  assert.ok(el.$('.next-up-later .tag-b'), 'a later entry shows its sub')
})

test('origin: the live feed names the kind and the source of a work row it reports on', () => {
  const { FeedLine } = views.stage
  const s = cockpitState(NOW)
  const el = mount(html`<${FeedLine} e=${{ kind: 'new', key: 'task:team-onboarding', title: 'Onboard', at: NOW }} s=${s} c=${recorder()} />`)
  assert.ok(el.$('.kind-stream') && el.$('.origin'), el.text())
})

test('jev: a plan entry the model holds no row for reads its kind and source from the work page item', () => {
  const { planRow } = loadedRooms.jev
  const item = { key: 'inbox:20261001-0900-x-ab12', inbox: '20261001-0900-x-ab12', title: 'X', work_kind: null,
    origin: { category: 'bot', word_key: null, detail: 'radar', raw: 'radar', ref: null, via_cockpit: false } }
  const pageItems = new Map([[item.key, item]])
  const row = planRow({ key: item.key }, null, pageItems)
  assert.equal(row.origin.category, 'bot')
  assert.equal(row.inbox_id, '20261001-0900-x-ab12')
  assert.equal(planRow({ key: 'task:y' }, null, null).task, 'y')
})

// ---------------------------------------------------------------- Operations and its sub pages (under:, @workers)

const opsSec = (id, title, items, extra = {}) => ({ id, kind: 'command', title, status: 'ok', reason: '', alarm: false, empty: 'nothing',
  count: items.length, total: items.length, weight: 0, bad: items.filter(x => x.tone === 'bad').length, as_of: null, more: 0, items, ...extra })
const opsRow = (i, title, tone = null) => ({ index: i, title, tone, detail: '', when: '', actionable: false })
const opsRun = (id, severity) => ({ id, title: id, state: severity === 'high' ? 'stopped' : severity === 'medium' ? 'drifted' : 'in_sync',
  severity: severity ?? 'none', findings: severity ? [{ state: 'x', severity, detail: 'd' }] : [], strip: [], retired: false })

/** The cockpit with three pages of an invented Bridge: Operations names Background jobs, Inventory and Lab as its sub pages */
function opsState({ runs = [opsRun('mail', null), opsRun('pilot', 'medium')], ui = {}, pages = null } = {}) {
  const base = cockpitState(NOW, { ui })
  const page = (id, title, sections, extra = {}) => ({ id, title, group: 'main', badge: { kind: 'ok' }, overview: false, cards: null,
    jev: false, under: null, subs: [], sections, ...extra })
  const all = pages ?? [
    page('ops', 'Operations', [opsSec('checks', 'Checks', [], { alarm: true, empty: 'all green' })],
      { overview: true, cards: [], subs: ['@workers', 'inv', 'lab'] }),
    page('inv', 'Inventory', [opsSec('machines', 'Machines', [opsRow(0, 'box'), opsRow(1, 'printer', 'dim'), opsRow(2, 'watch', 'dim')], { view: 'tiles' }),
      opsSec('cloud', 'Cloud live', [opsRow(0, 'fn-a')], { view: 'tiles', hide_ok: true })], { under: 'ops' }),
    page('lab', 'Lab', [opsSec('remotes', 'Remotes', [opsRow(0, 'gpu-box', 'dim')]), opsSec('findings', 'Findings', [], { alarm: true })], { under: 'ops' }),
  ]
  const live = runs.filter(r => !r.retired)
  return { ...base, model: { ...base.model, pages: all }, usage: { status: 'idle', data: null }, costs: { status: 'idle', data: null },
    workers: { status: 'ok', error: null, data: { host: 'homebox', generated_at: '', systems: [], runs,
      stats: { in_service: live.length, with_findings: live.filter(r => r.findings.length).length, not_reported: 0, retired: 0 } } } }
}

const tabTexts = bar => bar.$$('[role=tab]').map(b => b.text())

/** The page bar reads its active tab back with querySelector, listens for resize and measures its tabs (as in the
 *  flow suite): a DOM without layout says 0, so it neither folds nor moves its marker. Installed by the first test
 *  that mounts the bar, so the tests above this section run on the DOM as it was */
function pageBar(s, c = recorder()) {
  const proto = Object.getPrototypeOf(document.createElement('div'))
  if (!proto.querySelector) proto.querySelector = function querySelector(sel) { return this.$(sel) }
  globalThis.window ??= { addEventListener() {}, removeEventListener() {}, innerWidth: 1280 }
  for (const k of ['offsetLeft', 'offsetWidth', 'scrollWidth', 'clientWidth']) {
    if (!Object.getOwnPropertyDescriptor(proto, k)) Object.defineProperty(proto, k, { get: () => 0, configurable: true })
  }
  return mount(html`<${views.header.PageBar} s=${s} c=${c} />`)
}

test('operations: a page names its sub pages and each knows its parent; Background jobs only where a worker view exists', () => {
  const { parentOf, subPagesOf, pageOrder } = views.nav
  const s = opsState()
  assert.deepEqual(subPagesOf(s, 'ops'), ['@workers', 'inv', 'lab'])
  assert.deepEqual([parentOf(s, 'inv'), parentOf(s, '@workers'), parentOf(s, 'ops')], ['ops', 'ops', null])
  assert.ok(!pageOrder(s).some(id => ['inv', 'lab', '@workers'].includes(id)), pageOrder(s).join(' '))
  assert.deepEqual(subPagesOf({ ...s, workers: { status: 'none', data: null } }, 'ops'), ['inv', 'lab'])
  // a parent the model does not carry leaves its sub pages a tab of their own
  const orphan = { ...s, model: { ...s.model, pages: s.model.pages.filter(p => p.id !== 'ops') } }
  assert.equal(parentOf(orphan, 'inv'), null)
  assert.ok(pageOrder(orphan).includes('inv') && pageOrder(orphan).includes('@workers'))
  // beside a sub page's title a plain ok only on a live all clear: devices nothing measures live are not in order
  const { headBadgeOf } = views.nav
  const page = id => s.model.pages.find(p => p.id === id)
  assert.deepEqual([headBadgeOf(s, page('inv')).kind, headBadgeOf(s, page('lab')).kind, headBadgeOf(s, page('ops')).kind], ['none', 'ok', 'ok'])
})

test('operations: a sub page has no tab, the tab of the page it stands under stays lit while it is open', () => {
  for (const page of ['inv', '@workers']) {
    const bar = pageBar(opsState({ ui: { page } }))
    const tabs = tabTexts(bar)
    assert.ok(tabs.some(x => x.startsWith('Operations')), tabs.join(' | '))
    assert.ok(!tabs.some(x => x.startsWith('Inventory') || x.startsWith('Lab') || x.startsWith(en.workersTab)), tabs.join(' | '))
    const lit = bar.$$('[role=tab]').filter(b => b.getAttribute('aria-selected') === 'true').map(b => b.text())
    assert.equal(lit.length, 1, page)
    assert.match(lit[0], /^Operations/, page)
  }
})

test('operations: an outage turns the parent tab red with its count, upkeep alone leaves it calm', () => {
  const opsTab = s => pageBar(s).$$('[role=tab]').find(b => b.text().startsWith('Operations'))
  const calm = opsTab(opsState())
  assert.ok(!calm.$('.tk-danger') && !calm.$('.tk-warning'), calm.text())
  const down = opsTab(opsState({ runs: [opsRun('mail', null), opsRun('pilot', 'medium'), opsRun('backup', 'high')] }))
  assert.ok(down.$('.pbadge .tk-danger'), down.text())
  assert.equal(down.$('.pbadge .mono').text(), '1')
  // a finding on a sub page counts there too
  const s = opsState()
  const inv = s.model.pages.find(p => p.id === 'inv')
  const red = { ...s, model: { ...s.model, pages: s.model.pages.map(p => (p === inv ? { ...inv, badge: { kind: 'bad', n: 2 } } : p)) } }
  assert.equal(opsTab(red).$('.pbadge .mono').text(), '2')
})

test('operations: Background jobs keep their own tab red only for an outage, never orange for upkeep', () => {
  const alone = runs => {
    const s = opsState({ runs })
    return { ...s, model: { ...s.model, pages: s.model.pages.map(p => ({ ...p, subs: [], under: null })) } }
  }
  const jobsTab = s => pageBar(s).$$('[role=tab]').find(b => b.text().startsWith(en.workersTab))
  const upkeep = jobsTab(alone([opsRun('pilot', 'medium'), opsRun('report', 'medium')]))
  assert.ok(upkeep, 'the tab is there')
  assert.ok(!upkeep.$('.pbadge'), upkeep.text())
  const down = jobsTab(alone([opsRun('pilot', 'medium'), opsRun('backup', 'high')]))
  assert.ok(down.$('.pbadge .tk-danger'), down.text())
  assert.equal(down.$('.pbadge .mono').text(), '1')
})

test('operations: the tiles on top show the parent\'s own parts, its sub pages stand in the folder bar instead', () => {
  const { OverviewBoard } = views.pages
  const s = opsState({ runs: [opsRun('mail', null), opsRun('pilot', 'medium'), opsRun('backup', 'high')] })
  const el = mount(html`<${OverviewBoard} page=${s.model.pages[0]} s=${s} c=${recorder()} />`)
  assert.deepEqual(el.$$('.otile').map(x => x.$('.otile-title').text()), ['Checks'])
  // Background jobs with a tab of their own keep their tile on an overview, and it opens on every job
  const free = { ...s, model: { ...s.model, pages: s.model.pages.map(p => ({ ...p, subs: [], under: null })) } }
  const c = recorder()
  const jobs = mount(html`<${OverviewBoard} page=${free.model.pages[0]} s=${free} c=${c} />`).$$('.otile')
    .find(x => x.$('.otile-title').text() === en.workersTab)
  assert.ok(jobs.hasClass('tk-danger'), jobs.getAttribute('class'))
  assert.equal(jobs.$('.otile-big').text(), '1')
  jobs.click()
  assert.deepEqual(c.calls.at(-1), ['openWorkers', {}])
})

test('Background jobs opened on their outages: only those, the chip says so and takes it back', () => {
  const runs = [opsRun('mail', null), opsRun('pilot', 'medium'), opsRun('backup', 'high')]
  const el = mount(html`<${views.sessions.WorkersPage} s=${opsState({ runs, ui: { page: '@workers', workersFilter: { outage: true } } })} c=${recorder()} />`)
  const chip = el.$$('.wfilters .fchip').find(b => b.text().includes(en.workerOutage))
  assert.ok(chip, 'the outage chip')
  assert.equal(chip.getAttribute('aria-pressed'), 'true')
  assert.match(el.$('.wfilters').text(), new RegExp(en.workersShown(1, 3).replace(/[()]/g, '\\$&')))
  // without an outage the chip stands only while it is on
  const calm = mount(html`<${views.sessions.WorkersPage} s=${opsState({ runs: runs.slice(0, 2), ui: { page: '@workers' } })} c=${recorder()} />`)
  assert.ok(!calm.$$('.wfilters .fchip').some(b => b.text().includes(en.workerOutage)))
})

test('a job finding marked seen: "Seen" on the open row, then grey with its note and "show again"', async () => {
  const opened = async el => {
    el.$('.wrow-main').click()
    for (let i = 0; i < 20 && !el.$('.wrow-detail'); i++) await new Promise(r => setTimeout(r, 0))
  }
  const failed = { ...opsRun('chat-bot', 'high'), host: 'mini' }
  const c = recorder()
  const el = mount(html`<${views.sessions.WorkersPage} s=${opsState({ runs: [failed], ui: { page: '@workers' } })} c=${c} />`)
  await opened(el)
  const seen = el.$$('.wrow-detail button').find(b => b.text() === en.findingSeen.btn)
  assert.ok(seen, 'the Seen button')
  assert.equal(seen.getAttribute('title'), en.findingSeen.title)
  seen.click()
  assert.deepEqual(c.calls.at(-1), ['ackFinding', 'worker:mini:chat-bot', true])
  const acked = { ...failed, acked: { day: '2026-10-28', note: 'a planned restart' } }
  const c2 = recorder()
  const calm = mount(html`<${views.sessions.WorkersPage} s=${opsState({ runs: [acked], ui: { page: '@workers' } })} c=${c2} />`)
  assert.ok(!calm.$('.wrow').hasClass('rt-bad'), calm.$('.wrow').getAttribute('class'))
  await opened(calm)
  assert.match(calm.$('.wrow-detail').text(), /a planned restart/)
  calm.$$('.wrow-detail button').find(b => b.text() === en.findingSeen.undo).click()
  assert.deepEqual(c2.calls.at(-1), ['ackFinding', 'worker:mini:chat-bot', false])
})

test('operations: the folder bar names the overview and every sub page with its mark, on each of them', () => {
  const { FolderBar } = views.header
  const runs = [opsRun('mail', null), opsRun('pilot', 'medium'), opsRun('backup', 'high')]
  const warnLab = s => ({ ...s, model: { ...s.model, pages: s.model.pages.map(p => (p.id === 'lab'
    ? { ...p, sections: [...p.sections, opsSec('logs', 'Logs', [opsRow(0, 'journal', 'warn'), opsRow(1, 'tasks', 'warn')])] } : p)) } })
  for (const page of ['ops', 'inv', 'lab']) {
    const c = recorder()
    const bar = mount(html`<${FolderBar} s=${warnLab(opsState({ runs, ui: { page } }))} c=${c} />`).$('.folderbar')
    assert.ok(bar, page)
    const items = bar.$$('button')
    assert.deepEqual(items.map(b => b.$('.folder-name').text()), [en.folderOverview, en.workersTab, 'Inventory', 'Lab'], page)
    const current = items.filter(b => b.getAttribute('aria-current') === 'page').map(b => b.$('.folder-name').text())
    assert.deepEqual(current, [page === 'ops' ? en.folderOverview : page === 'inv' ? 'Inventory' : 'Lab'])
    const [, jobs, inv, lab] = items
    assert.ok(jobs.$('.tk-danger'), jobs.text())
    assert.equal(jobs.$('.folder-note').text(), en.folderOutages(1))
    assert.equal(lab.$('.folder-note').text(), en.folderWarnings(2))
    assert.ok(!inv.$('.folder-note'), inv.text())
    items[3].click()
    assert.deepEqual(c.calls.at(-1), ['setPage', 'lab'])
    items[0].click()
    assert.deepEqual(c.calls.at(-1), ['setPage', 'ops'])
  }
  assert.ok(mount(html`<${views.sessions.WorkersPage} s=${opsState({ ui: { page: '@workers' } })} c=${recorder()} />`).$('.folderbar'),
    'on Background jobs too')
  assert.ok(!mount(html`<${FolderBar} s=${opsState({ ui: { page: 'briefing' } })} c=${recorder()} />`).$('.folderbar'), 'none outside a folder')
  // no way back of its own: the bar is the way
  assert.ok(!mount(html`<${views.sessions.WorkersPage} s=${opsState({ ui: { page: '@workers' } })} c=${recorder()} />`).button('‹ Operations'))
})

test('operations: the parent tab opens its overview, its ▾ opens a menu of the same pages with their marks', async () => {
  const proto = Object.getPrototypeOf(document.body)
  proto.focus ??= function focus() { document.activeElement = this }
  const c = recorder()
  const bar = pageBar(opsState({ runs: [opsRun('mail', null), opsRun('backup', 'high')], ui: { page: 'inv' } }), c)
  bar.$$('[role=tab]').find(b => b.text().startsWith('Operations')).click()
  assert.deepEqual(c.calls.at(-1), ['setPage', 'ops'])
  const caret = bar.button(en.folderMenu('Operations'))
  assert.ok(caret, 'the ▾ beside the tab')
  assert.equal(caret.getAttribute('aria-haspopup'), 'menu')
  assert.ok(!bar.$('.folder-menu'), 'closed until clicked')
  caret.click()
  await tick()
  const items = bar.$$('.folder-menu [role=menuitem]')
  assert.deepEqual(items.map(b => b.$('.folder-name').text()), [en.folderOverview, en.workersTab, 'Inventory', 'Lab'])
  assert.equal(items[1].$('.folder-note').text(), en.folderOutages(1))
  items[3].click()
  await tick()
  assert.deepEqual(c.calls.at(-1), ['setPage', 'lab'])
  assert.ok(!bar.$('.folder-menu'), 'a pick closes it')
})

test('operations: the tab order follows the listing, and a page without under is a tab of its own again', () => {
  const { pageOrder, subPagesOf } = views.nav
  const s = opsState()
  const gh = { id: 'gh', title: 'GitHub', group: 'main', badge: { kind: 'ok' }, overview: false, cards: null, jev: false, under: null, subs: [], sections: [] }
  const order = pages => pageOrder({ ...s, model: { ...s.model, pages } }).filter(id => ['ops', 'gh'].includes(id))
  assert.deepEqual(order([...s.model.pages, gh]), ['ops', 'gh'])
  assert.deepEqual(order([gh, ...s.model.pages]), ['gh', 'ops'])
  const free = { ...s, model: { ...s.model, pages: s.model.pages.map(p => (p.id === 'lab' ? { ...p, under: null }
    : p.id === 'ops' ? { ...p, subs: ['@workers', 'inv'] } : p)) } }
  assert.ok(pageOrder(free).includes('lab'))
  assert.deepEqual(subPagesOf(free, 'ops'), ['@workers', 'inv'])
  assert.ok(!mount(html`<${views.header.FolderBar} s=${{ ...free, ui: { ...free.ui, page: 'lab' } }} c=${recorder()} />`).$('.folderbar'))
})

/** Runs on machines: the always-on box with an outage and a job in order, the laptop with one */
const hostRun = (id, host, severity = null, extra = {}) => ({ ...opsRun(id, severity), host, system: '', kind: 'interval', ...extra })
const machinePages = () => {
  const s = opsState()
  const inv = s.model.pages.find(p => p.id === 'inv')
  const lab = s.model.pages.find(p => p.id === 'lab')
  const mrow = (i, name, tone, detail) => ({ ...opsRow(i, name, tone), id: `machine:${name}`, detail })
  return s.model.pages.map(p => (p === inv ? { ...inv, sections: [opsSec('machines', 'Machines',
    [mrow(0, 'homebox', null, 'always on'), mrow(1, 'laptop', null, 'online'), mrow(2, 'gpu-box', 'dim', 'offline'), mrow(3, 'printer', 'dim', 'outside')])] }
    : p === lab ? { ...lab, sections: [opsSec('remotes', 'Remotes', [{ ...opsRow(0, 'gpu-box', 'dim'), detail: 'off' }, { ...opsRow(1, 'homebox'), detail: 'on' }])] } : p))
}

test('machines: one line per machine a job runs on or a sub page names, the always-on first; a printer is not one', () => {
  const runs = [hostRun('mail', 'homebox'), hostRun('backup', 'homebox', 'high'), hostRun('sync', 'laptop', 'medium')]
  const lines = loadedLogic.machineLines({ runs, hosts: ['homebox'], pages: machinePages() })
  assert.deepEqual(lines.map(x => x.name), ['homebox', 'laptop', 'gpu-box'])
  const [box, laptop, gpu] = lines
  assert.deepEqual([box.always, box.jobs, box.failing, box.upkeep, box.tone], [true, 2, 1, 0, 'bad'])
  assert.deepEqual(box.places.map(p => [p.page, p.title, p.state]), [['lab', 'Lab', 'on']])
  assert.deepEqual([laptop.always, laptop.jobs, laptop.upkeep, laptop.state, laptop.places.length], [false, 1, 1, 'online', 0])
  assert.deepEqual([gpu.jobs, gpu.state, gpu.tone, gpu.places.map(p => p.state)], [0, 'offline', 'dim', ['off']])
})

test('machines: the rows as the server sends them (collector.info_out: a key, no id) still give a machine its state and its lab place', () => {
  // info_out carries `key` (item:<page>/<section>/<source id>) and `row_id`, never `id`; a lab row names its machine
  // in tags.Remote or its id pc:<name>, whatever its title says
  const served = (page, sec, id, title, tone, detail, extra = {}) => ({ ...opsRow(0, title, tone), key: `item:${page}/${sec}/${id}`,
    row_id: null, detail, ...extra })
  const s = opsState()
  const pages = s.model.pages.map(p => (p.id === 'inv' ? { ...p, sections: [opsSec('machines', 'Machines', [
    served('inv', 'machines', 'machine:homebox', 'homebox', null, 'macos · macOS 27.0 · online · always on', { tags: { Device: 'macos' } }),
    served('inv', 'machines', 'machine:gpu-box', 'gpu-box', 'dim', 'windows · Windows 11 · offline', { tags: { Device: 'windows' } })])] }
    : p.id === 'lab' ? { ...p, sections: [opsSec('remotes', 'Remotes', [
      served('lab', 'remotes', 'pc:gpu-box', 'GPU box (lab)', 'dim', 'off', { row_id: 'pc:gpu-box', tags: { Remote: 'gpu-box' } })])] } : p))
  const lines = loadedLogic.machineLines({ runs: [hostRun('mail', 'homebox')], hosts: ['homebox'], pages })
  assert.deepEqual(lines.map(x => x.name), ['homebox', 'gpu-box'], 'a machine with no job still has its line through its lab row')
  const [box, gpu] = lines
  assert.deepEqual(box.places, [], 'the inventory row is the state, never a place of its own')
  // the state without its device word, which the tags already say
  assert.equal(gpu.state, 'Windows 11 · offline')
  assert.equal(gpu.tone, 'dim')
  assert.deepEqual(gpu.places.map(p => [p.page, p.state]), [['lab', 'off']])
})

test('machines: the block on the overview opens the jobs of a machine, a lab state opens the lab', () => {
  const { MachineLines } = views.pages
  const runs = [hostRun('mail', 'homebox'), hostRun('backup', 'homebox', 'high'), hostRun('sync', 'laptop', 'medium')]
  const base = opsState({ runs, ui: { page: 'ops' } })
  const s = { ...base, model: { ...base.model, pages: machinePages() }, workers: { ...base.workers, data: { ...base.workers.data, hosts: ['homebox'] } } }
  const c = recorder()
  const el = mount(html`<${MachineLines} page=${s.model.pages[0]} s=${s} c=${c} />`)
  assert.equal(el.$('.mlines-title').text(), en.machinesTitle)
  const rows = el.$$('.mline')
  assert.deepEqual(rows.map(r => r.$('.mline-name').text()), ['homebox', 'laptop', 'gpu-box'])
  assert.match(rows[0].text(), new RegExp(en.machineAlways))
  assert.match(rows[0].text(), new RegExp(en.machineJobs(2)))
  assert.ok(rows[0].$('.mline-main .tk-danger'), 'an outage is red')
  rows[0].$('.mline-main').click()
  assert.deepEqual(c.calls.at(-1), ['openWorkers', { host: 'homebox' }])
  rows[0].button(en.machinePlace('Lab', 'on')).click()
  assert.deepEqual(c.calls.at(-1), ['setPage', 'lab'])
  rows[2].$('.mline-main').click()
  assert.deepEqual(c.calls.at(-1), ['setPage', 'lab'])
  // a page outside a folder draws none
  assert.ok(!mount(html`<${MachineLines} page=${s.model.pages[1]} s=${s} c=${recorder()} />`).$('.mlines'))
})

test('background jobs: by machine, the always-on first, the systems with an outage first, every job in view', () => {
  const runs = [hostRun('sync', 'laptop', null, { system: 'notes' }), hostRun('mail', 'homebox', null, { system: 'mail' }),
    hostRun('backup', 'homebox', 'high', { system: 'store' }), hostRun('pilot', 'homebox', 'medium', { system: 'mail' })]
  const groups = loadedLogic.groupByHost(runs, { hosts: ['homebox'], systems: [{ id: 'mail', title: 'Mail' }, { id: 'store', title: 'Store' }] })
  assert.deepEqual(groups.map(g => [g.host, g.always, g.runs.length, g.failing, g.upkeep]), [['homebox', true, 3, 1, 1], ['laptop', false, 1, 0, 0]])
  assert.deepEqual(groups[0].groups.map(g => [g.id, g.runs.map(r => r.id)]), [['store', ['backup']], ['mail', ['pilot', 'mail']]])
  const base = opsState({ runs, ui: { page: '@workers' } })
  const s = { ...base, workers: { ...base.workers, data: { ...base.workers.data, hosts: ['homebox'], systems: [{ id: 'mail', title: 'Mail' }] } } }
  const el = mount(html`<${views.sessions.WorkersPage} s=${s} c=${recorder()} />`)
  const heads = el.$$('.wmachine > .wmachine-head')
  assert.deepEqual(heads.map(h => h.$('.rgroup-title').text()), ['homebox', 'laptop'])
  assert.match(heads[0].text(), new RegExp(en.machineAlways))
  assert.equal(el.$$('.wrow').length, 4, 'every job, not only those with a finding')
  // the machine is the first filter, as chips
  const first = el.$('.wfilters .wfacet')
  assert.equal(first.$('.label-caps').text(), en.workerFacet.host)
  assert.deepEqual(first.$$('.fchip').map(b => b.text().split(' ')[0]), ['homebox', 'laptop'])
})

test('background jobs: a row names its kind, when it ran last and when it runs next', () => {
  const now = new Date(2026, 9, 9, 12, 0).getTime()
  const at = (h, m) => new Date(2026, 9, 9, h, m).toISOString()
  const daily = { when: 'FREQ=DAILY at 06:05; FREQ=DAILY at 18:05', day: { marks: [{ at_pct: 25, today: true }] }, strip: [{ at: at(6, 6), verdict: 'ok' }] }
  assert.deepEqual(loadedLogic.runTimes(daily, now), { last: Date.parse(at(6, 6)), next: new Date(2026, 9, 9, 18, 5).getTime() })
  const every = { when: 'every 900s', day: { marks: [] }, strip: [{ at: at(11, 50), verdict: 'ok' }] }
  assert.deepEqual(loadedLogic.runTimes(every, now), { last: Date.parse(at(11, 50)), next: Date.parse(at(12, 5)) })
  assert.deepEqual(loadedLogic.runTimes({ when: 'continuous', strip: [] }, now), { last: null, next: null })
  // a weekly run not due today names no time today
  assert.equal(loadedLogic.runTimes({ when: 'FREQ=WEEKLY;BYDAY=SU at 10:30', day: { marks: [] }, strip: [] }, now).next, null)
  const run = hostRun('mail', 'homebox', null, { kind: 'recurring', ...daily, title: 'Mail digest', purpose: 'sends the digest' })
  const s = opsState({ runs: [run], ui: { page: '@workers' } })
  const row = mount(html`<${views.sessions.WorkersPage} s=${{ ...s, now }} c=${recorder()} />`).$('.wrow')
  assert.match(row.$('.wrow-name').text(), new RegExp(en.workerKind.recurring))
  assert.match(row.$('.wrow-times').text(), /06:06/)
  assert.match(row.$('.wrow-times').text(), /18:05/)
})

// a question a row was asked (quick.py `about`), as the server sends the conversations
const rowChat = (id, key, running, last_ms = NOW) => ({ id, about: { kind: 'worker', key }, running, last_ms, started_ms: last_ms - 1000, turns: [] })
// a job row opened: its detail lands on a later render, waited for in bounded ticks
async function openRow(row) {
  row.$('.wrow-main').click()
  for (let k = 0; k < 100 && !row.$('.wrow-detail'); k++) await new Promise(r => setTimeout(r, 10))
  return row
}

test('background jobs: a row asks about its job and analyses it in a tab, both by machine and job only', async () => {
  const s = opsState({ runs: [hostRun('bot', 'homebox', 'high')], ui: { page: '@workers' } })
  const c = recorder()
  const row = mount(html`<${views.sessions.WorkersPage} s=${s} c=${c} />`).$('.wrow')
  await openRow(row)
  row.button(en.btnWorkerAdvise).click()
  assert.deepEqual(c.calls.at(-1), ['act', 'worker_advise', { host: 'homebox', id: 'bot' }])
  row.button(en.btnAsk).click()
  assert.deepEqual(c.calls.at(-1), ['ask', 'worker', { host: 'homebox', id: 'bot' }])
})

test('background jobs: a row asked before shows that question and opens it, a new one only on ask again', async () => {
  assert.equal(loadedLogic.rowConv([rowChat('g0000000001', 'worker:homebox:bot', false, NOW - 5000), rowChat('g0000000002', 'worker:homebox:bot', true),
    rowChat('g0000000003', 'worker:homebox:mail', false, NOW + 1)], 'worker:homebox:bot').id, 'g0000000002', 'the newest of that row')
  assert.equal(loadedLogic.rowConv([rowChat('g0000000001', 'worker:homebox:bot', false)], 'worker:laptop:bot'), null)
  const base = opsState({ runs: [hostRun('bot', 'homebox', 'high')], ui: { page: '@workers' } })
  for (const [running, word] of [[true, en.askRunning], [false, en.askAnswered]]) {
    const s = { ...base, quick: { ...(base.quick ?? {}), convs: [rowChat('g0000000002', 'worker:homebox:bot', running)] } }
    const c = recorder()
    const row = mount(html`<${views.sessions.WorkersPage} s=${s} c=${c} />`).$('.wrow')
    await openRow(row)
    assert.match(row.$('.wrow-detail').text(), new RegExp(word))
    assert.ok(!row.button(en.btnAsk), 'no second question beside the open one')
    row.button(en.askOpenConv).click()
    assert.deepEqual(c.calls.at(-1), ['openAsk', 'g0000000002'])
    row.button(en.btnAskAgain).click()
    assert.deepEqual(c.calls.at(-1), ['ask', 'worker', { host: 'homebox', id: 'bot' }])
  }
})

test('background jobs: a row whose question went on to a tab carries the marker every question list shows', async () => {
  // the row and the question window agree (logic.js askMark): in its tab, then done once its item came back
  const base = opsState({ runs: [hostRun('bot', 'homebox', 'high')], ui: { page: '@workers' } })
  const handed = outcome => ({ ...rowChat('g0000000004', 'worker:homebox:bot', false), turns: [{ q: 'x', a: 'y' }],
    handed: { to: 'tab', at_ms: NOW, status: 'started', inbox_id: 'i-bot', ...(outcome ? { outcome } : {}) } })
  for (const [conv, word] of [[handed(null), en.asks.mark.inTab],
    [handed({ text: 'Result: the bot runs', closed: true, at_ms: NOW, asks: false }), en.asks.mark.done],
    [handed({ text: 'Question: restart it?', closed: false, at_ms: NOW, asks: true }), en.asks.mark.asksYou]]) {
    const s = { ...base, quick: { ...(base.quick ?? {}), convs: [conv] } }
    const row = mount(html`<${views.sessions.WorkersPage} s=${s} c=${recorder()} />`).$('.wrow')
    await openRow(row)
    assert.match(row.$('.wrow-detail').text(), new RegExp(word))
    assert.ok(row.button(en.askOpenConv), 'the question stays one click away')
  }
})

test('background jobs: a job filed for a tab shows that tab while its item is open, and its result once it ended', async () => {
  const id = '20261028-0736-background-job-bot-a1b2'
  const base = opsState({ runs: [{ ...hostRun('bot', 'homebox', 'high'), advise: { inbox: id, state: 'open' } }], ui: { page: '@workers' } })
  const ret = (stage, result, tab) => ({ key: `inbox:${id}`, item: id, title: 'bot', mode: 'report', at_ms: NOW - 60000, stage, in_briefing: false, tab, result })
  const s = { ...base, model: { ...base.model, returns: [ret('working', null, { ref: 'surface:9', state: 'working', since_ms: NOW, last: '' })] } }
  const c = recorder()
  const row = mount(html`<${views.sessions.WorkersPage} s=${s} c=${c} />`).$('.wrow')
  await openRow(row)
  assert.match(row.$('.wrow-detail').text(), new RegExp(en.workerInTab))
  assert.ok(!row.button(en.btnWorkerAdvise), 'no second start while the item is open')
  row.button(en.workerToTab).click()
  assert.deepEqual(c.calls.at(-1), ['openTabView', 'surface:9'])
  // where the Chat lays out its tabs, the way goes to that tab's room there
  const rooms = { ...s, rooms: { ...(s.rooms ?? {}), layout: 'workspaces' } }
  const c2 = recorder()
  const row2 = mount(html`<${views.sessions.WorkersPage} s=${rooms} c=${c2} />`).$('.wrow')
  await openRow(row2)
  row2.button(en.workerToTab).click()
  assert.deepEqual(c2.calls.slice(-2), [['setPage', '@chat'], ['pickRoom', { kind: 'tab', id: 'surface:9' }]])
  const ended = { ...base, workers: { ...base.workers, data: { ...base.workers.data, runs: [{ ...hostRun('bot', 'homebox', 'high'), advise: { inbox: id, state: 'done' } }] } },
    model: { ...base.model, returns: [ret('done', { kind: 'close', text: 'the finding is old, the bot runs', key: null, at_ms: NOW }, null)] } }
  const done = mount(html`<${views.sessions.WorkersPage} s=${ended} c=${recorder()} />`).$('.wrow')
  await openRow(done)
  assert.match(done.$('.wrow-detail').text(), /the finding is old, the bot runs/)
  assert.ok(done.button(en.btnWorkerAdvise), 'an ended analysis may run again')
})

test('background jobs: Seen stands last beside the analysis, and a seen row offers no new analysis until its item is open', async () => {
  const words = row => row.$$('.wrow-detail .btn-row button').map(b => b.text())
  const red = mount(html`<${views.sessions.WorkersPage} s=${opsState({ runs: [hostRun('bot', 'homebox', 'high')], ui: { page: '@workers' } })} c=${recorder()} />`).$('.wrow')
  await openRow(red)
  assert.deepEqual(words(red), [en.btnWorkerAdvise, en.btnAsk, en.findingSeen.btn])
  // a button like its neighbours, never a bare word (walk of 28.10.)
  const seen = red.$$('.wrow-detail .btn-row button').find(b => b.text() === en.findingSeen.btn)
  assert.ok(seen.hasClass('btn-secondary') && !seen.hasClass('act-quiet'), seen.getAttribute('class'))
  assert.equal(text.TABLES.de.findingSeen.undo, 'Wieder anzeigen')
  // seen: grey, "show again" only, the job needs nothing more until it fails anew
  const acked = { ...hostRun('bot', 'homebox', 'high'), acked: { day: '2026-10-28', note: 'the bot runs' } }
  const calm = mount(html`<${views.sessions.WorkersPage} s=${opsState({ runs: [acked], ui: { page: '@workers' } })} c=${recorder()} />`).$('.wrow')
  await openRow(calm)
  assert.deepEqual(words(calm), [en.btnAsk, en.findingSeen.undo])
  // seen while its analysis still works in a tab: the way to that tab stays
  const id = '20261028-0736-background-job-bot-a1b2'
  const base = opsState({ runs: [{ ...acked, advise: { inbox: id, state: 'open' } }], ui: { page: '@workers' } })
  const s = { ...base, model: { ...base.model, returns: [{ key: `inbox:${id}`, item: id, title: 'bot', mode: 'report', at_ms: NOW - 60000,
    stage: 'working', in_briefing: false, tab: { ref: 'surface:9', state: 'working', since_ms: NOW, last: '' }, result: null }] } }
  const busy = mount(html`<${views.sessions.WorkersPage} s=${s} c=${recorder()} />`).$('.wrow')
  await openRow(busy)
  assert.deepEqual(words(busy), [en.workerToTab, en.btnAsk, en.findingSeen.undo])
})

test('a page row asked before shows that question and opens it instead of asking again', () => {
  const sec = opsSec('checks', 'Checks', [{ ...opsRow(0, 'Backup', 'bad'), key: 'item:ops/checks/backup', ask: true }])
  const page = { id: 'ops', title: 'Operations', sections: [sec] }
  const base = cockpitState(NOW)
  const c = recorder()
  const fresh = mount(html`<${views.pages.PageSection} page=${page} section=${sec} s=${base} c=${c} />`)
  fresh.button(en.btnAsk).click()
  assert.deepEqual(c.calls.at(-1), ['ask', 'info', { page: 'ops', section: 'checks', index: 0 }])
  const s = { ...base, quick: { ...(base.quick ?? {}), convs: [{ ...rowChat('g0000000005', 'item:ops/checks/backup', false), about: { kind: 'info', key: 'item:ops/checks/backup' } }] } }
  const el = mount(html`<${views.pages.PageSection} page=${page} section=${sec} s=${s} c=${c} />`)
  assert.match(el.text(), new RegExp(en.askAnswered))
  assert.ok(!el.button(en.btnAsk), 'no second question')
  el.button(en.askOpenConv).click()
  assert.deepEqual(c.calls.at(-1), ['openAsk', 'g0000000005'])
})

test('lab: a sub page with overview shows a head card of its own parts, folded where they say the same, no jobs and no tokens', () => {
  const rest = { ...opsRow(0, 'Lab not running', 'dim'), detail: 'the box is off' }
  const lab = { id: 'lab', title: 'Lab', overview: true, under: 'ops', sections: [
    opsSec('remotes', 'Remotes', [opsRow(0, 'gpu-box', 'dim'), opsRow(1, 'homebox')]),
    opsSec('findings', 'Findings', [], { alarm: true, empty: 'Lab quiet' }),
    opsSec('gpu', 'GPU', [rest]), opsSec('llm', 'Model', [rest]),
    opsSec('logs', 'Logs', [opsRow(0, 'journal', 'warn'), opsRow(1, 'tasks', 'warn')])] }
  const lines = loadedLogic.pageSummary(lab)
  assert.deepEqual(lines.map(x => [x.titles.join('+'), x.kind, x.tone]), [['Remotes', 'rows', 'neutral'], ['Findings', 'empty', 'success'],
    ['GPU+Model', 'one', 'neutral'], ['Logs', 'loud', 'warning']])
  const base = opsState({ ui: { page: 'lab' } })
  const s = { ...base, usage: { status: 'ok', data: { days: [], outliers: [] } }, model: { ...base.model, pages: base.model.pages.map(p => (p.id === 'lab' ? { ...p, ...lab } : p)) } }
  const c = recorder()
  const el = mount(html`<${views.pages.PageSummary} page=${s.model.pages.find(p => p.id === 'lab')} s=${s} c=${c} />`)
  const rows = el.$$('.psum-line')
  assert.equal(rows.length, 4)
  assert.match(rows[0].text(), new RegExp(`Remotes.*${en.summaryRows(1, 1)}`))
  assert.match(rows[2].text(), /GPU, Model.*Lab not running/)
  assert.match(rows[3].text(), new RegExp(`Logs.*${en.folderWarnings(2)}`))
  assert.ok(!el.text().includes(en.workersTab) && !el.text().includes(en.usageTitle), el.text())
})

test('operations: a section with hide_ok is drawn only while one of its rows is a finding', () => {
  const { PageSection } = views.pages
  const s = opsState({ ui: { page: 'inv' } })
  const page = s.model.pages.find(p => p.id === 'inv')
  const cloud = page.sections.find(x => x.id === 'cloud')
  assert.ok(!mount(html`<${PageSection} page=${page} section=${cloud} s=${s} c=${recorder()} />`).$('section'), 'hidden while quiet')
  const down = { ...cloud, bad: 1, items: [opsRow(0, 'fn-a', 'bad')] }
  assert.ok(mount(html`<${PageSection} page=${page} section=${down} s=${s} c=${recorder()} />`).$('section'), 'shown with a finding')
})

// ---------------------------------------------------------------- the runaway guard of cockpit_render.mjs
// A view that renders itself without end must fail its test within a second or two, with a message naming it,
// instead of growing the process until the machine runs out of memory. Each case runs in a child process with
// its own heap cap and a hard kill, so a guard that does not trip costs this suite seconds, never the machine.

const HELPER = new URL('./cockpit_render.mjs', import.meta.url).href
// the child is a test run of its own, not a file of this one: without this its report goes out in the runner's
// binary protocol instead of text
const { NODE_TEST_CONTEXT: _, ...CHILD_ENV } = process.env

/** Runs the module `src` in a child with a 256 MB heap and a hard kill after `kill` ms; `asTest` runs it as a
 *  file under `node --test`, the way the suites run */
async function capped(src, { asTest = false, env = {}, kill = 20000 } = {}) {
  const { spawnSync } = await import('node:child_process')
  const fs = await import('node:fs')
  const os = await import('node:os')
  const path = await import('node:path')
  let args = ['--input-type=module', '-e', src]
  let dir = null
  if (asTest) {
    dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cockpit-guard-'))
    fs.writeFileSync(path.join(dir, 'case.test.mjs'), src)
    args = ['--test', '--test-timeout=60000', path.join(dir, 'case.test.mjs')]
  }
  const started = Date.now()
  try {
    const r = spawnSync(process.execPath, ['--max-old-space-size=256', ...args],
      { encoding: 'utf8', timeout: kill, killSignal: 'SIGKILL', env: { ...CHILD_ENV, ...env } })
    return { ...r, wall: Date.now() - started, out: (r.stdout ?? '') + (r.stderr ?? '') }
  } finally {
    if (dir) fs.rmSync(dir, { recursive: true, force: true })
  }
}

/** Runs `body` in a capped child after loading the cockpit; reports how long the trip took */
async function runaway(body, opts = {}) {
  const src = `
    import test from 'node:test'
    import { loadCockpit, mount } from ${JSON.stringify(HELPER)}
    const { html, useState, useEffect, useLayoutEffect } = await loadCockpit()
    let t0 = 0
    process.prependListener('uncaughtException', e => { console.log('TRIP ' + (Date.now() - t0) + ' ' + e.message); process.exit(3) })
    ${body}`
  const r = await capped(src, opts)
  const m = /TRIP (\d+) (.*)/.exec(r.stdout)
  return { ...r, ms: m ? Number(m[1]) : null, message: m ? m[2] : null }
}

test('guard: a layout effect that sets state on every render trips the render budget, naming the component', async () => {
  const r = await runaway(`
    function LayoutSpinner() { const [n, set] = useState(0); useLayoutEffect(() => set(n + 1)); return html\`<b>\${n}</b>\` }
    t0 = Date.now(); mount(html\`<\${LayoutSpinner} />\`); await new Promise(r => setTimeout(r, 30000))`)
  assert.equal(r.status, 3, r.out)
  assert.match(r.message, /render loop: LayoutSpinner/)
  assert.match(r.message, /Mounted at .*\[eval1\]:\d+/)
  assert.ok(r.ms < 2000, `tripped after ${r.ms} ms`)
})

test('guard: a state update in the render body trips the render budget', async () => {
  const r = await runaway(`
    function RenderSetter() { const [n, set] = useState(0); set(n + 1); return html\`<b>\${n}</b>\` }
    t0 = Date.now(); mount(html\`<\${RenderSetter} />\`); await new Promise(r => setTimeout(r, 30000))`)
  assert.equal(r.status, 3, r.out)
  assert.match(r.message, /render loop: RenderSetter/)
  assert.ok(r.ms < 2000, `tripped after ${r.ms} ms`)
})

test('guard: an effect that sets state on every render trips the render budget within a second or two', async () => {
  const r = await runaway(`
    function EffectSpinner() { const [xs, set] = useState([]); useEffect(() => set(xs.concat([xs.length]))); return html\`<ul>\${xs.map(x => html\`<li>\${x}</li>\`)}</ul>\` }
    t0 = Date.now(); mount(html\`<\${EffectSpinner} />\`); await new Promise(r => setTimeout(r, 30000))`)
  assert.equal(r.status, 3, r.out)
  assert.match(r.message, /render loop: EffectSpinner/)
  assert.ok(r.ms < 2500, `tripped after ${r.ms} ms`)
})

test('guard: an unbounded list trips the heap ceiling before the heap cap', async () => {
  const r = await runaway(`
    function Endless() { return html\`<ul>\${Array.from({ length: 400000 }, (_, i) => html\`<li class="row">\${i}</li>\`)}</ul>\` }
    t0 = Date.now(); try { mount(html\`<\${Endless} />\`) } catch (e) { console.log('TRIP ' + (Date.now() - t0) + ' ' + e.message); process.exit(3) }`,
  { env: { COCKPIT_RENDER_HEAP_MB: '96' } })
  assert.equal(r.status, 3, r.out)
  assert.match(r.message, /heap ceiling: .* MB used, more than 96 MB/)
})

test('guard: a slow effect loop under the budget ends with its file instead of keeping the process alive', async () => {
  const r = await runaway(`
    function Ticker() { const [n, set] = useState(0); useEffect(() => { const t = setTimeout(() => set(n + 1), 20); return () => clearTimeout(t) }); return html\`<b>\${n}</b>\` }
    test('ticks', async () => { mount(html\`<\${Ticker} />\`); await new Promise(r => setTimeout(r, 200)) })`, { asTest: true })
  assert.equal(r.signal, null, `killed after ${r.wall} ms: the process outlived its tests\n${r.out}`)
  assert.equal(r.status, 0, r.out)
  assert.ok(r.wall < 10000, `ended after ${r.wall} ms`)
})

// A failing assertion prints its `actual`. An element of the small DOM hangs off its parent, Preact's root vnode
// and through it the whole page state, and node's assert prints with depth 1000 and without custom inspectors,
// so printing one element used to grow the process by gigabytes a second (outside the heap, so a heap cap did
// not stop it) and the test timeout never fired. The element now prints as its tag, classes and a little text.

/** Runs `body` in a capped child after mounting a return card as `el` */
function printing(body, opts = {}) {
  const src = `
    import test from 'node:test'
    import assert from 'node:assert/strict'
    import util from 'node:util'
    import { cockpitState, loadCockpit, mount, recorder } from ${JSON.stringify(HELPER)}
    const { html, views } = await loadCockpit()
    const NOW = ${NOW}
    const el = mount(html\`<\${views.home.ReturnCard} r=\${${JSON.stringify(start())}} s=\${cockpitState(NOW)} c=\${recorder()} />\`)
    ${body}`
  return capped(src, opts)
}

test('print: a failing assert.equal on an element builds a short message at once', async () => {
  const r = await printing(`
    const t0 = Date.now()
    try { assert.equal(el.firstChild, null) } catch (e) { console.log(JSON.stringify({ ms: Date.now() - t0, len: e.message.length, msg: e.message })) }`)
  assert.equal(r.signal, null, `killed after ${r.wall} ms while printing an element`)
  const got = JSON.parse(r.stdout.split('\n').find(l => l.startsWith('{"ms"')) ?? 'null')
  assert.ok(got.ms < 1000, `the message took ${got.ms} ms`)
  assert.ok(got.len < 2000, `the message is ${got.len} characters long`)
  assert.match(got.msg, /article/)
})

test('print: util.inspect of an element, a text node and the document reads as a tag, not as the page', async () => {
  const r = await printing(`
    console.log(util.inspect(el.firstChild)); console.log(util.inspect(el.firstChild.firstChild)); console.log(util.inspect(document))`)
  assert.equal(r.status, 0, r.out)
  const [element, , doc] = r.stdout.trim().split('\n')
  assert.match(element, /^<article class="rcard[^"]*">.{0,90}<\/article>$/)
  assert.ok(r.stdout.length < 1000, r.stdout)
  assert.equal(doc, '#document')
})

test('print: a failing test on an element ends in seconds through the test reporter', async () => {
  const r = await printing(`
    test('an element where none belongs', () => { assert.equal(el, null) })`, { asTest: true })
  assert.equal(r.signal, null, `killed after ${r.wall} ms while reporting the failure`)
  assert.equal(r.status, 1, r.out)
  assert.match(r.out, /an element where none belongs/)
  assert.ok(r.out.length < 20000, `the report is ${r.out.length} characters long`)
})

// ---------------------------------------------------------------- round 6 b: what the Sessions page held, in the Chat

const OFFLINE = { enabled: true, online: false, reason: 'no_heartbeat', session: null, records: [] }
const chatOn = (over = {}) => cockpitState(NOW, { ...over, ui: { room: { kind: 'chat' }, tabView: 'surface:99', ...(over.ui ?? {}) } })

test('round 6 b S3: the Chat says on its head why the relay has nobody to ask, with the button that starts a control session', () => {
  const t = text.T()
  const c = recorder()
  const el = mount(html`<${RoomsPage} s=${chatOn({ relay: OFFLINE })} c=${c} />`)
  const note = el.$('.chat-control')
  assert.ok(!!note, 'the notice on top of the Chat')
  assert.ok(note.text().includes(t.relayReason.no_heartbeat), note.text())
  note.button(t.btnStartControl).click()
  assert.deepEqual(c.calls.at(-1), ['act', 'start_control', {}])
  // the same notice stands on top of the classic Chat (views/chat.js ChatPage)
  const own = mount(html`<${views.header.ControlNotice} s=${chatOn({ relay: OFFLINE })} c=${recorder()} />`)
  assert.ok(own.$$('.chat-control').some(x => x.text().includes(t.relayReason.no_heartbeat)), 'the notice on its own')
  // the relay ready: nothing
  assert.ok(!mount(html`<${RoomsPage} s=${chatOn()} c=${recorder()} />`).$('.chat-control'), 'nothing while the relay is ready')
  // a control session that runs but does not listen: the Chat says so, and the header's badge leads there where
  // Running now lists the sessions (the Sessions page without Work through)
  const deaf = { ...OFFLINE, reason: 'ambiguous' }
  const words = mount(html`<${RoomsPage} s=${chatOn({ relay: deaf })} c=${recorder()} />`).$$('.chat-control').map(x => x.text())
  assert.ok(words.some(w => w.includes(t.sessionControlNoRelay)), words.join(' | '))
  const badge = s => { const c2 = recorder(); mount(html`<${views.header.RelayBadge} s=${s} c=${c2} />`).$('button.hdr-relay').click(); return c2.calls }
  assert.deepEqual(badge(chatOn({ relay: deaf })), [['setPage', '@chat']])
  const classicFlow = chatOn({ relay: deaf })
  assert.deepEqual(badge({ ...classicFlow, work: { ...classicFlow.work, flow: { enabled: false } } }), [['setPage', '@sessions']])
})

test('round 6 b S4: the Chat warns when the tab list is broken or no driver lists the tabs, and a tab links to its task', () => {
  const t = text.T()
  const banners = s => mount(html`<${RoomsPage} s=${s} c=${recorder()} />`).$$('.banner').map(x => x.text())
  const base = chatOn()
  const broken = banners(chatOn({ tabs: { ...base.tabs, error: { since: '11:58', message: 'the terminal did not answer' } } }))
  assert.ok(broken.some(w => w.includes(t.tabsStale('11:58', 'the terminal did not answer'))), broken.join(' | '))
  const none = banners(chatOn({ cmux: { ok: false, error: null }, driver: { caps: [] } }))
  assert.ok(none.some(w => w.includes(t.noDriver)), none.join(' | '))
  assert.deepEqual(banners(base), [])
  // a task tab names its task, a click opens it in the drawer over the Chat
  const open = ref => {
    const c = recorder()
    const el = mount(html`<${RoomsPage} s=${chatOn({ ui: { room: { kind: 'tab', id: ref } } })} c=${c} />`)
    const link = el.$('.tabview-head .room-task')
    if (!link) return null
    link.click()
    const call = c.calls.find(x => x[0] === 'openItem')
    return call ? [call[1], link.getAttribute('title')] : []
  }
  assert.deepEqual(open('surface:12'), ['task:demo-task', t.infoOpenTask])
  // a tab typed into by hand whose session works on a task (recognised): that task
  assert.deepEqual(open('surface:14'), ['task:search-index', t.infoOpenTask])
  // a tab of no task: no link
  assert.equal(open('surface:11'), null)
})

// ---------------------------------------------------------------- round 6 c fix: the small fixes block on the day

test('the day names its housekeeping block in plain words and says per line what to do, the text where it has no kind', () => {
  const { DayView } = views.detail
  const base = cockpitState(NOW)
  const tend = [
    { kind: 'no_next', text: '2 tasks without a next step: a, b', n: 2, names: ['alpha', 'beta'] },
    { kind: 'untasked', text: 'GitHub: assigned to you without a task: 12', n: 12, names: [], title: 'GitHub' },
    { kind: 'muted', text: '2 muted', n: 2, names: [] },
    { kind: 'note', text: '9 tasks active, 5 is the cap', n: null, names: [] },
  ]
  const s = { ...base, model: { ...base.model, extras: { ...base.model.extras, hygiene: tend.map(x => x.text), tend } } }
  const el = mount(html`<${DayView} s=${s} c=${recorder()} />`)
  const block = el.$$('.ov-block').find(b => b.$('h3')?.text() === en.hygieneTitle)
  assert.ok(block, 'the block under its title')
  const lines = block.$$('li').map(li => li.text().trim())
  assert.deepEqual(lines, [en.tend.no_next(tend[0]), en.tend.untasked(tend[1]), en.tend.muted(tend[2]), tend[3].text])
  // without facts (an older server) the lines stand as they came
  const old = { ...base, model: { ...base.model, extras: { ...base.model.extras, hygiene: ['x line'], tend: undefined } } }
  assert.ok(mount(html`<${DayView} s=${old} c=${recorder()} />`).text().includes('x line'))
  // the word nobody understood is gone from every German text that names this block
  const de = text.TABLES.de
  assert.doesNotMatch(`${de.hygieneTitle} ${de.allAreas} ${de.settings.explainOption['d:day']}`, /Aufräumen/)
  for (const k of ['no_next', 'untasked', 'muted', 'error', 'repos_skipped', 'owed', 'hidden']) {
    assert.equal(typeof de.tend[k], 'function', k)
    assert.match(de.tend[k]({ n: 2, names: ['a', 'b'], title: 'X', reason: 'r' }), /\.$/, `${k} is a sentence`)
  }
})

test('background jobs answer to the words Worker and Workflow, name every machine they list, and the header says AI runs', () => {
  const run = (id, host, kind, extra = {}) => ({ ...opsRun(id, null), host, kind, system: '', ...extra })
  const runs = [run('mail', 'homebox', 'daemon'), run('nightly', 'homebox', 'recurring'), run('poll', 'laptop', 'interval'), run('eye', 'homebox', 'watch')]
  const ids = q => loadedLogic.filterWorkers(runs, { q }).map(r => r.id)
  assert.deepEqual(ids('workflow'), ['nightly', 'poll'], 'scheduled and interval runs are the workflows')
  assert.deepEqual(ids('Worker'), ['mail', 'nightly', 'poll', 'eye'], 'every background job is a worker')
  assert.deepEqual(ids('termin'), ['nightly'], 'the German kind word too')
  assert.deepEqual(ids('dienst'), ['mail'])
  const s = opsState({ runs, ui: { page: '@workers' } })
  const el = mount(html`<${views.sessions.WorkersPage} s=${s} c=${recorder()} />`)
  assert.match(el.$('.page-head').text(), /homebox, laptop/, 'the head names both machines')
  assert.equal(el.$('.workers-intro').text(), en.workersIntro)
  // the retired label Worker stays retired in the texts (one word per thing); the search answers to it all the same
  assert.match(text.TABLES.de.workersIntro, /Workflows/)
  // a search that finds nothing does not add the count of units the machine runs without a declaration
  const none = mount(html`<${views.sessions.WorkersPage} s=${{ ...s, ui: { ...s.ui, workersFilter: { q: 'zzz' } },
    workers: { ...s.workers, data: { ...s.workers.data, elsewhere: { undeclared: { counted: 9 } } } } }} c=${recorder()} />`)
  assert.ok(!none.text().includes(en.workersElsewhere(9)))
  // the header's count of Claude workflows no longer says Workflows, which are the jobs of the machines to the person
  for (const lang of ['en', 'de']) assert.doesNotMatch(text.TABLES[lang].header.working(1, 0, 2), /[Ww]orkflow/, lang)
})

test('lab: a head line that folds more than two parts names the first and counts the rest, the whole list as its tooltip', () => {
  const rest = { ...opsRow(0, 'Lab not running', 'dim'), detail: 'the box is off' }
  const lab = { id: 'lab', title: 'Lab', overview: true, under: 'ops', sections: [
    opsSec('gpu', 'GPU', [rest]), opsSec('llm', 'Model', [rest]), opsSec('guests', 'Guests', [rest]), opsSec('disk', 'Storage', [rest])] }
  const base = opsState({ ui: { page: 'lab' } })
  const s = { ...base, model: { ...base.model, pages: base.model.pages.map(p => (p.id === 'lab' ? { ...p, ...lab } : p)) } }
  const line = mount(html`<${views.pages.PageSummary} page=${s.model.pages.find(p => p.id === 'lab')} s=${s} c=${recorder()} />`).$('.psum-line')
  assert.equal(line.$('.psum-title').text(), en.summaryParts(['GPU', 'Model', 'Guests', 'Storage']))
  assert.equal(line.$('.psum-title').getAttribute('title'), 'GPU, Model, Guests, Storage')
  assert.equal(en.summaryParts(['GPU', 'Model']), 'GPU, Model')
})

test('a drawn list shows the When column only where a row has a time, and names its actions column for a screen reader only', () => {
  const { PageSection } = views.pages
  const s = opsState({ ui: { page: 'inv' } })
  const page = s.model.pages.find(p => p.id === 'inv')
  const plain = opsSec('gpu', 'GPU', [{ ...opsRow(0, 'card 0'), detail: '40 %' }])
  const el = mount(html`<${PageSection} page=${page} section=${plain} s=${s} c=${recorder()} />`)
  assert.ok(!el.$('th.c-when') && !el.$('td.c-when'), 'no empty When column')
  assert.ok(el.$('th.c-acts .sr-only'), 'the actions head is not drawn as a word')
  const timed = opsSec('gpu', 'GPU', [{ ...opsRow(0, 'card 0'), when: '09:12' }])
  assert.ok(mount(html`<${PageSection} page=${page} section=${timed} s=${s} c=${recorder()} />`).$('td.c-when'))
})

test('github (6c fix): a board column spelled two ways is one option, the rows drop the GitHub tag their ref already says', () => {
  const rows = ghBarRows().map(r => (r.index === 2 ? { ...r, gh: { ...r.gh, status: 'In progress' } }
    : r.index === 3 ? { ...r, gh: { ...r.gh, board: 'Demo board', status: 'Todo' } } : r))
  const { el, picked } = ghBar(null, rows)
  const status = el.$('.ghf-field[data-dim="status"] select')
  assert.deepEqual(status.$$('option').map(o => o.text()), [en.gh.bar.all(3), 'In Progress (2)', 'Todo (1)'])
  status.value = 'in progress'
  status.dispatch('change')
  const f = picked.at(-1)
  assert.equal(rows.filter(it => loadedLogic.ghPasses(it, f)).length, 2, 'the pick holds both spellings')
  // the settings link says what it does: which boards are fetched, not a second board filter
  assert.notEqual(en.gh.boardsSettings, en.gh.bar.dim.board)
  assert.match(text.TABLES.de.gh.boardsSettings, /laden/)
  const { GitHubList } = views.github
  const s = cockpitState(NOW)
  const list = mount(html`<${GitHubList} items=${ghBarRows()} page="github" section=${{ id: 'boards', boards: [] }} s=${s} c=${recorder()} byKey=${new Map()} />`)
  assert.ok(list.$('.ghl-ref') && !list.$('.ghl-row .origin'), 'repo#n, no GitHub chip')
})

test('6d: the files tab stands on the grid of Work through, so it stacks where Work through stacks', async () => {
  const fs = await import('node:fs')
  const s = cockpitState(NOW, { ui: { page: '@files', filesWalk: true } })
  const el = mount(html`<${views.dossier.DossierView} s=${s} c=${recorder()} />`)
  const grid = el.$('.flow-grid')
  assert.ok(grid && grid.$('.flow-side.dz-side') && grid.$('.flow-main.dz-main'), 'the columns of Work through')
  assert.ok(el.$('.col.flow'), 'inside the page of Work through, whose column height the side columns keep')
  const css = fs.readFileSync(new URL('../web/flow.css', import.meta.url), 'utf8')
  assert.match(css, /@media \(max-width: 960px\) \{\n {2}\.flow-grid, \.flow-grid\.no-aside \{ grid-template-columns: minmax\(0, 1fr\); \}/)
})

test('6d: in the narrow left column of the files tab the AI question field stands over its button, never squeezed beside it', async () => {
  // walk 28.10.: with a record open the field shrank to a sliver beside "Ask the AI about these n records"
  const fs = await import('node:fs')
  const css = fs.readFileSync(new URL('../web/files.css', import.meta.url), 'utf8')
  assert.match(css, /\.dz-side \.fs-askq \{ flex-direction: column; align-items: stretch; \}/)
})

// ---------------------------------------------------------------- round 6d review fixes

test('6d fix: a handed question whose tab is gone says so under the chat and offers to start again or open its item', () => {
  // live 28.10.: "Started, the tab is opening" an hour after the start, while Work said "Tab gone"
  const s0 = cockpitState(NOW)
  const conv = asked('q0000000007', JOB_Q, NOW - 70 * MIN, { handed: { to: 'tab', at_ms: NOW - 69 * MIN, status: 'started', inbox_id: 'i-lost' } })
  const s = cockpitState(NOW, { quick: { ...s0.quick, keep_hours: 24, convs: [conv] } })
  const c = recorder()
  const el = mount(html`<${ChatFoot} s=${s} c=${c} conv=${conv} autofocus=${false} />`)
  const line = el.$('.handoff-status')
  assert.equal(line.getAttribute('data-status'), 'gone')
  assert.match(line.text(), new RegExp(en.handoff.gone))
  el.button(en.handoff.restart).click()
  assert.deepEqual(c.calls.filter(x => x[0] === 'act').at(-1), ['act', 'quick_handoff', { conv: 'q0000000007', to: 'tab' }])
  el.button(en.handoff.openItem).click()
  assert.deepEqual(c.calls.filter(x => x[0] === 'openItem').at(-1), ['openItem', 'inbox:i-lost', null])
  // the question lists say the same, never "in its tab"
  const chips = mount(html`<${QuickChat} s=${{ ...s, ui: { ...s.ui, tabView: '@ask' } }} c=${recorder()} />`).$$('.quick-conv').map(b => b.text())
  assert.ok(chips.some(x => x.includes(en.asks.mark.gone)) && !chips.some(x => x.includes(en.asks.mark.inTab)), chips.join(' | '))
})

test('6d fix: a job row whose analysis has no tab says the tab ended and offers a new start, never "in a tab" beside it', async () => {
  const id = '20261028-0736-background-job-bot-a1b2'
  const base = opsState({ runs: [{ ...hostRun('bot', 'homebox', 'high'), advise: { inbox: id, state: 'open' } }], ui: { page: '@workers' } })
  const ret = (stage, at, result = null) => ({ key: `inbox:${id}`, item: id, title: 'bot', mode: 'report', at_ms: at, stage, in_briefing: false, tab: null, result })
  const row = async st => {
    const s = { ...base, model: { ...base.model, returns: [st] } }
    const c = recorder()
    return [await openRow(mount(html`<${views.sessions.WorkersPage} s=${s} c=${c} />`).$('.wrow')), c]
  }
  const [lost, c] = await row(ret('lost', NOW - 60 * MIN))
  assert.doesNotMatch(lost.$('.wrow-detail').text(), new RegExp(`\\b${en.workerInTab}\\b`))
  assert.match(lost.$('.wrow-detail').text(), new RegExp(en.workerTabGone))
  assert.ok(!lost.button(en.workerToTab))
  lost.button(en.btnWorkerAdvise).click()
  assert.deepEqual(c.calls.at(-1), ['act', 'worker_advise', { host: 'homebox', id: 'bot' }])
  // just started: it is starting, and there is no second start yet
  const [fresh] = await row(ret('started', NOW - 30_000))
  assert.match(fresh.$('.wrow-detail').text(), new RegExp(en.workerStarting))
  assert.ok(!fresh.button(en.btnWorkerAdvise))
})

test('6d fix: a collapsed job row shows that an analysis came back', () => {
  const id = '20261028-0736-background-job-bot-a1b2'
  const base = opsState({ runs: [{ ...hostRun('bot', 'homebox', 'high'), advise: { inbox: id, state: 'done' } }, hostRun('mail', 'homebox', 'high')], ui: { page: '@workers' } })
  const s = { ...base, model: { ...base.model, returns: [{ key: `inbox:${id}`, item: id, title: 'bot', mode: 'report', at_ms: NOW - MIN, stage: 'done',
    in_briefing: false, tab: null, result: { kind: 'close', text: 'the finding is old', key: null, at_ms: NOW } }] } }
  const rows = mount(html`<${views.sessions.WorkersPage} s=${s} c=${recorder()} />`).$$('.wrow')
  const bot = rows.find(r => r.text().includes('bot') && !r.text().includes('mail'))
  assert.ok(bot.$('.wrow-main').text().includes(en.workerResultIn), 'the closed row says a result is there')
  assert.ok(rows.filter(r => r !== bot).every(r => !r.$('.wrow-main').text().includes(en.workerResultIn)))
})

test('6d fix: a row question that failed or is still unanswered never reads as answered', async () => {
  const base = opsState({ runs: [hostRun('bot', 'homebox', 'high')], ui: { page: '@workers' } })
  const conv = turn => ({ ...rowChat('g0000000005', 'worker:homebox:bot', false), turns: [{ q: 'x', ...turn }] })
  for (const [turn, word] of [[{ a: null, error: 'timeout' }, en.askFailed], [{ a: null, error: null }, en.askRunning], [{ a: 'yes', error: null }, en.askAnswered]]) {
    const s = { ...base, quick: { ...(base.quick ?? {}), convs: [conv(turn)] } }
    const row = await openRow(mount(html`<${views.sessions.WorkersPage} s=${s} c=${recorder()} />`).$('.wrow'))
    const chip = row.$$('.wrow-detail .chip').map(x => x.text()).join(' | ')
    assert.ok(chip.includes(word), `${JSON.stringify(turn)}: ${chip}`)
    if (word !== en.askAnswered) assert.ok(!chip.includes(en.askAnswered), chip)
  }
})

test('6d fix: the buttons of a job row are written alike', () => {
  for (const lang of ['en', 'de']) {
    const t = text.TABLES[lang]
    const words = [t.btnWorkerAdvise, t.btnAsk, t.btnAskAgain, t.askOpenConv, t.workerToTab]
    assert.ok(words.every(w => w[0] === w[0].toUpperCase()), `${lang}: ${words.join(' | ')}`)
  }
})

test('6d C1: in the Chat the questions stand right under the tabs waiting for you, in every order, and an empty archive says so', async () => {
  const { s } = asksState({ rooms: { ...cockpitState(NOW).rooms, layout: 'workspaces' } })
  for (const roomsSort of ['terminal', 'urgency', 'status']) {
    const sorted = { ...s, ui: { ...s.ui, roomsSort } }
    const el = mount(html`<${Sidebar} s=${sorted} c=${recorder()} rooms=${roomsOf(sorted)} here=${{ kind: 'chat' }} />`)
    const heads = el.$$('h3').map(h => h.text())
    const waits = heads.findIndex(h => h.includes(en.reply.asks))
    const asks = heads.findIndex(h => h.includes(en.rooms.chats))
    // by status Waiting for you gives way to the groups, and the questions come first after the order
    assert.equal(asks, roomsSort === 'status' ? 0 : waits + 1, `${roomsSort}: ${heads.join(' | ')}`)
  }
  const el = mount(html`<${Sidebar} s=${s} c=${recorder()} rooms=${roomsOf(s)} here=${{ kind: 'chat' }} />`)
  const empty = { ...s, chatArchive: { status: 'ok', convs: [] }, ui: { ...s.ui, asksAll: true } }
  const all = mount(html`<${Sidebar} s=${empty} c=${recorder()} rooms=${roomsOf(empty)} here=${{ kind: 'chat' }} />`)
  assert.match(all.$('.room-asks').text(), new RegExp(en.asks.noneArchived(7)))
  const none = mount(html`<${Sidebar} s=${{ ...empty, ui: { ...empty.ui, asksAll: false } }} c=${recorder()} rooms=${roomsOf(empty)} here=${{ kind: 'chat' }} />`)
  assert.doesNotMatch(none.$('.room-asks').text(), new RegExp(en.asks.noneArchived(7)))
})

test('6d fix: a finding on a job row quotes the job\'s own words after the state in the page\'s language', async () => {
  // the view writes its findings in English: in German they read as a quote, never as part of the German sentence
  const run = { ...hostRun('bot', 'homebox', 'high'), findings: [{ state: 'last_run_failed', severity: 'high', detail: 'the last run ended with 75', hint: '' }] }
  const s = opsState({ runs: [run], ui: { page: '@workers' } })
  const row = await openRow(mount(html`<${views.sessions.WorkersPage} s=${s} c=${recorder()} />`).$('.wrow'))
  assert.match(row.$('.wfind').text(), new RegExp(`${en.workerState.last_run_failed}: ${en.workerQuote('the last run ended with 75')}`))
  assert.equal(text.TABLES.de.workerQuote('x'), '„x“')
})

test('6d fix: in the Chat\'s questions the marker stands beside the clipped title, never inside it', () => {
  // walk 28.10.: "Hintergrundjob telegr…" hid its "Tab beendet" with the rest of the title
  const { s } = asksState({ rooms: { ...cockpitState(NOW).rooms, layout: 'workspaces' } })
  const el = mount(html`<${Sidebar} s=${s} c=${recorder()} rooms=${roomsOf(s)} here=${{ kind: 'chat' }} />`)
  const marked = el.$$('.room-asks .room-chat').filter(b => b.$('.ask-mark'))
  assert.ok(marked.length >= 2)
  for (const b of marked) assert.ok(!b.$('.room-name .ask-mark'), b.text())
})

// ---------------------------------------------------------------- round 6d, the Chat (chat.md C1 to C5)

test('6d C1: the questions group carries the way to a new question in its head, and an empty chat says how long questions stay', () => {
  const { s } = asksState({ rooms: { ...cockpitState(NOW).rooms, layout: 'workspaces' } })
  const c = recorder()
  const el = mount(html`<${Sidebar} s=${s} c=${c} rooms=${roomsOf(s)} here=${{ kind: 'chat' }} />`)
  const head = el.$('.room-asks .room-group-head')
  assert.equal(head.$('h3').text(), en.rooms.chats)
  head.button(`+ ${en.rooms.newAsk}`).click()
  assert.deepEqual(c.calls.filter(x => ['newQuick', 'pickRoom'].includes(x[0])), [['newQuick'], ['pickRoom', { kind: 'chat' }]])
  // no row of its own for it among the questions
  assert.ok(!el.$$('.room-asks .room-chats button').some(b => b.text().includes(en.rooms.newAsk)))
  const week = cockpitState(NOW, { quick: { ...s.quick, keep_hours: 168 }, ui: { room: { kind: 'chat' }, quickConv: null } })
  const page = mount(html`<${RoomsPage} s=${week} c=${recorder()} />`)
  assert.equal(page.$('.rooms-main .quick-kept').text(), en.asks.kept(168))
  assert.match(page.$('.rooms-main .quick-kept').text(), /7 days/)
  const win = mount(html`<${QuickChat} s=${{ ...week, ui: { ...week.ui, tabView: '@ask' } }} c=${recorder()} />`)
  assert.equal(win.$('.quick-kept').text(), en.asks.kept(168))
})

test('6d C3: a kept tab that is gone opens the chat; one closed under the hand still says so', () => {
  const kept = cockpitState(NOW, { ui: { room: { kind: 'tab', id: 'surface:77', kept: true }, quickConv: null, tabView: 'surface:99' } })
  const el = mount(html`<${RoomsPage} s=${kept} c=${recorder()} />`)
  assert.ok(el.$('.rooms-main #quick-input'), 'the chat with its field')
  assert.doesNotMatch(el.text(), new RegExp(en.rooms.gone))
  const picked = cockpitState(NOW, { ui: { room: { kind: 'tab', id: 'surface:77' }, quickConv: null, tabView: 'surface:99' } })
  assert.match(mount(html`<${RoomsPage} s=${picked} c=${recorder()} />`).text(), new RegExp(en.rooms.gone))
  // a kept tab that is there opens as it was left
  const there = cockpitState(NOW, { ui: { room: { kind: 'tab', id: 'surface:12', kept: true }, tabView: 'surface:99' } })
  assert.equal(mount(html`<${RoomsPage} s=${there} c=${recorder()} />`).$('#room-title').text(), 'demo-task research')
})

test('6d C3: with nothing kept the Chat picks once on entering, and never again on its own', async () => {
  const { s } = asksState({ ui: { room: null, quickConv: null } })
  const c = recorder()
  const root = mount(html`<${RoomsPage} s=${s} c=${c} />`)
  for (let i = 0; i < 10 && !c.calls.some(x => x[0] === 'pickRoom'); i++) await settle()
  const first = c.calls.filter(x => ['pickQuick', 'pickRoom'].includes(x[0]))
  assert.equal(first.length, 2, JSON.stringify(first))
  assert.equal(first[0][0], 'pickQuick')
  assert.deepEqual(first[1], ['pickRoom', { kind: 'chat' }])
  // a new poll, a tab that starts asking: no second pick
  const later = { ...s, tabs: { ...s.tabs, at_ms: s.tabs.at_ms + 3000 } }
  loadedRooms.render(html`<${RoomsPage} s=${later} c=${c} />`, root)
  for (let i = 0; i < 5; i++) await settle()
  assert.equal(c.calls.filter(x => x[0] === 'pickRoom').length, 1)
})

test('6d C3: every room picked is kept in this browser, the chat, a tab and a workspace alike', () => {
  const saved = []
  let s = cockpitState(NOW)
  const acts = views.nav.chatAreaActions({ get: () => s, setUi: p => { s = { ...s, ui: { ...s.ui, ...p } } }, save: (k, v) => saved.push([k, v]), now: () => NOW })
  acts.pickRoom({ kind: 'tab', id: 'surface:12' })
  acts.pickRoom({ kind: 'chat' })
  acts.walkTab('surface:7')
  assert.deepEqual(saved.filter(x => x[0] === 'bridge-cockpit.chatRoom'), [['bridge-cockpit.chatRoom', '{"kind":"tab","id":"surface:12"}'],
    ['bridge-cockpit.chatRoom', '{"kind":"chat"}'], ['bridge-cockpit.chatRoom', '{"kind":"tab","id":"surface:7"}']])
})

test('6d C4: on the Chat the header\'s Ask puts the cursor into the page\'s field, elsewhere it opens the window', () => {
  const c = recorder()
  mount(html`<${Header} s=${cockpitState(NOW, { ui: { page: '@chat', tabView: null } })} c=${c} />`).$('.hdr-ask').click()
  const other = recorder()
  mount(html`<${Header} s=${cockpitState(NOW, { ui: { page: 'briefing' } })} c=${other} />`).$('.hdr-ask').click()
  assert.deepEqual([c.calls.map(x => x[0]), other.calls.map(x => x[0])], [['askHere'], ['openAsk']])
})

/** A tab handed on from a question, one from a job and one from an inbox item, each with the start that opened it */
function originState(over = {}) {
  const s0 = cockpitState(NOW)
  const conv = { ...ANSWERED, id: 'q00000000c5', turns: [{ ...ANSWERED.turns[0], q: 'Why did the chat bot fail this morning?' }],
    handed: { to: 'tab', at_ms: NOW - 5 * MIN, status: 'started', inbox_id: '20261009-1150-why-did-the-chat-c5c5' } }
  const tabs = { ...s0.tabs, tabs: [...s0.tabs.tabs,
    { ref: 'surface:31', ws_ref: 'workspace:3', name: 'Inbox why-did-the-chat-c5c5', workspace: 'Demo', state: 'working', last: 'Reading the log',
      slug: null, item: '20261009-1150-why-did-the-chat-c5c5', team: null, role: null, live: true, waiting: false, is_control: false,
      filed_by: null, since_ms: NOW - 4 * MIN, long: null, ask: null },
  ] }
  return cockpitState(NOW, { tabs, quick: { ...s0.quick, convs: [conv, ...(s0.quick?.convs ?? [])] }, ...over })
}

test('6d C5: a tab handed on from a question says so in its head and its row, and the title opens that question', () => {
  const s = originState({ ui: { room: { kind: 'tab', id: 'surface:31' }, tabView: 'surface:99' } })
  const c = recorder()
  const el = mount(html`<${RoomsPage} s=${s} c=${c} />`)
  const link = el.$('.tabview-head .room-from-link')
  assert.equal(link.text(), en.rooms.from('Why did the chat bot fail this morning?'))
  assert.equal(link.getAttribute('data-from'), 'ask')
  link.click()
  assert.deepEqual(c.calls.filter(x => ['pickQuick', 'pickRoom'].includes(x[0])), [['pickQuick', 'q00000000c5'], ['pickRoom', { kind: 'chat' }]])
  const row = tabRow(el, 'Inbox why-did-the-chat-c5c5')
  assert.equal(row.$('.room-from').text(), en.rooms.from('Why did the chat bot fail this morning?'))
  // its own task is no origin to name: a task tab keeps its task link alone
  const task = mount(html`<${RoomsPage} s=${cockpitState(NOW, { ui: { room: { kind: 'tab', id: 'surface:12' }, tabView: 'surface:99' } })} c=${recorder()} />`)
  assert.equal(task.$('.tabview-head .room-from-link'), null)
  assert.ok(task.$('.tabview-head .room-task'))
  assert.equal(tabRow(task, 'demo-task research').$('.room-from'), null)
})

test('6d: the open tab\'s head names its origin and carries the one close of every place, side by side', () => {
  const el = mount(html`<${RoomsPage} s=${cockpitState(NOW, { ui: { room: { kind: 'tab', id: 'surface:10' }, tabView: 'surface:99' } })} c=${recorder()} />`)
  const head = el.$('.rooms-main .tabview-head')
  assert.ok(head.$('.room-from-link'), 'C5: aus: <Titel>')
  assert.ok(head.$('.tab-close'), 'item 9: Close tab')
})

test('6d C5: a tab from an inbox item or a job opens that item in the drawer or the job on its page', () => {
  const s0 = cockpitState(NOW)
  const row = { key: 'inbox:20261009-1150-job-b6b6', title: 'Background job chat-bot on homebox: last run failed', inbox_key: 'worker:homebox:chat-bot' }
  const model = { ...s0.model, task_rows: [...(s0.model.task_rows ?? []), row] }
  const tab = { ref: 'surface:32', ws_ref: 'workspace:3', name: 'Inbox job-b6b6', workspace: 'Demo', state: 'working', last: '', slug: null,
    item: '20261009-1150-job-b6b6', team: null, role: null, live: true, waiting: false, is_control: false, filed_by: null, since_ms: NOW, long: null, ask: null }
  const s = cockpitState(NOW, { model, tabs: { ...s0.tabs, tabs: [...s0.tabs.tabs, tab] }, ui: { room: { kind: 'tab', id: 'surface:32' }, tabView: 'surface:99' } })
  const c = recorder()
  const link = mount(html`<${RoomsPage} s=${s} c=${c} />`).$('.tabview-head .room-from-link')
  assert.equal(link.getAttribute('data-from'), 'job')
  assert.equal(link.text(), en.rooms.from('chat-bot · homebox'))
  link.click()
  assert.deepEqual(c.calls.filter(x => x[0] === 'setPage'), [['setPage', '@workers']])
  // the demo's report tab came from an inbox item: it opens in the drawer
  const report = mount(html`<${RoomsPage} s=${cockpitState(NOW, { ui: { room: { kind: 'tab', id: 'surface:10' }, tabView: 'surface:99' } })} c=${c} />`)
  const item = report.$('.tabview-head .room-from-link')
  assert.equal(item.getAttribute('data-from'), 'item')
  item.click()
  assert.equal(c.calls.at(-1)[0], 'openItem')
  assert.match(c.calls.at(-1)[1], /^inbox:/)
})

// ---------------------------------------------------------------- 6d: the click log tells the new buttons apart

test('6d: the click log names each new button of this round on its own, never by its words', async () => {
  const name = b => loadedLogic.usageControl(b)
  const { el } = renderControls('surface:13', { tab: { ask: null, behind: { task: 'demo-task', item: '20261009-0910-tidy-labels-c3d4' } } })
  assert.deepEqual([name(el.button(en.btnDoneCloseTab)), name(el.button(en.btnCloseTabOnly))], ['tab-done', 'tab-close'])
  const { el: foot } = renderFoot()
  assert.deepEqual([name(foot.button(en.chatAsk)), name(foot.button(en.chatSolve))], ['chat-ask', 'chat-ai'])
  const head = mount(html`<${RoomsPage} s=${cockpitState(NOW, { ui: { room: { kind: 'tab', id: 'surface:10' }, tabView: 'surface:99' } })} c=${recorder()} />`)
  assert.equal(name(head.$('.room-from-link')), 'room-from-link')
  const base = opsState({ runs: [hostRun('bot', 'homebox', 'high')], ui: { page: '@workers' } })
  const row = await openRow(mount(html`<${views.sessions.WorkersPage} s=${base} c=${recorder()} />`).$('.wrow'))
  assert.equal(name(row.button(en.btnWorkerAdvise)), 'worker-advise')
  assert.equal(name(row.button(en.findingSeen.btn)), 'seen')
  // the explain window's own field: opening it and noting are told apart from the bar's other buttons
  const layout = { view: { width: 1400, height: 900 }, away: [], rounds: [{ group: 'page', placed: [] }] }
  const hints = mount(html`<${HintsLayer} layout=${layout} c=${{ setHints() {}, tourStart() {}, explainNote: async () => ({ ok: true }) }} place=${{ page: '@chat', view: '-' }} />`)
  assert.equal(name(hints.button(en.hints.noteOpen)), 'explain-note')
  hints.button(en.hints.noteOpen).click()
  for (let i = 0; i < 20 && !hints.$('.hints-say'); i++) await tick()
  assert.deepEqual([name(hints.button(en.hints.noteSave)), name(hints.button(en.hints.noteCancel))], ['explain-note-save', 'explain-note-cancel'])
})
