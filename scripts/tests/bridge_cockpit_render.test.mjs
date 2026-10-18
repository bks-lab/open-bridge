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
