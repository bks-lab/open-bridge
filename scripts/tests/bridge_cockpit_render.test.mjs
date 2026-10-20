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

// ---------------------------------------------------------------- what works where: header chip and sidebar counts

test('the header shows the working total from the mock sessions', () => {
  const s = cockpitState(NOW)
  const c = recorder()
  const chip = mount(html`<${Header} s=${s} c=${c} />`).$('.hdr-agents')
  // this Bridge's tabs: three busy sessions, five subagents, two workflows (the paused one does not count);
  // the session of another folder stands only in the tooltip
  assert.equal(chip.text(), en.header.working(3, 5, 2))
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

test('the sidebar order toggle flips between the terminal order and the most urgent first', () => {
  const c = recorder()
  const s = cockpitState(NOW)
  const el = mount(html`<${Sidebar} s=${s} c=${c} rooms=${roomsOf(s)} here=${{ kind: 'chat' }} />`)
  const toggle = el.button(en.rooms.sortUrgency)
  assert.equal(toggle.getAttribute('aria-pressed'), 'false')
  toggle.click()
  assert.deepEqual(c.calls, [['toggleRoomsSort']])
  const on = cockpitState(NOW, { ui: { roomsSort: 'urgency' } })
  assert.equal(renderSide(on).button(en.rooms.sortUrgency).getAttribute('aria-pressed'), 'true')
})

// ---------------------------------------------------------------- what a tab waits for, answered from the page

const { TabReply } = views.reply
const replyRows = el => el.$$('.reply-group .reply-row')
const replyRow = (el, name) => replyRows(el).find(r => r.$('.reply-name').text() === name) ?? null
const tick = () => new Promise(resolve => setTimeout(resolve, 20))

test('the sidebar shows Waiting for you with the question and option buttons', () => {
  const s = cockpitState(NOW)
  const c = recorder()
  const el = mount(html`<${Sidebar} s=${s} c=${c} rooms=${roomsOf(s)} here=${{ kind: 'chat' }} />`)
  const group = el.$('.reply-group')
  assert.equal(group.$('h3').text(), en.reply.asks)
  // the most urgent first, the control tab never; the group stands above the workspaces
  assert.deepEqual(replyRows(el).map(r => r.$('.reply-name').text()), ['alpha-release', 'report-draft', 'demo-task research', 'changelog'])
  const side = el.$('nav')
  assert.ok(side.childNodes.indexOf(group) < side.childNodes.indexOf(el.$('section.room-ws')))
  const alpha = replyRow(el, 'alpha-release')
  const ask = tabOf(s, 'surface:7').ask
  assert.match(alpha.$('.reply-ask').text(), /Do you want to make this edit\?/)
  assert.match(alpha.text(), /Ops/)
  // one button per option the dialog shows, labelled with it, and the tab one click away; no free text into a dialog
  for (const o of ask.options) assert.ok(alpha.button(o.label), o.label)
  assert.ok(alpha.button(en.reply.openTab))
  assert.equal(alpha.$('textarea'), null)
  alpha.button(ask.options[1].label).click()
  assert.deepEqual(c.calls.at(-1).slice(0, 3), ['reply', 'tab_option', { tab_ref: 'surface:7', n: 2, seen: ask.hash, name: 'alpha-release' }])
  // a yes or no question: yes and no as words, go on, and the answer field behind one click
  const research = replyRow(el, 'demo-task research')
  assert.ok(research.button(en.reply.yes) && research.button(en.reply.no) && research.button(en.reply.goOn))
  assert.equal(research.$('textarea'), null)
  research.button(en.reply.yes).click()
  assert.deepEqual(c.calls.at(-1).slice(0, 3), ['reply', 'tab_send', { tab_ref: 'surface:12', text: en.reply.yesText, expect: 'waiting',
    seen: tabOf(s, 'surface:12').ask.hash, name: 'demo-task research' }])
  assert.ok(research.button(en.reply.placeholder))
  // the name opens the tab on the right; the tab's own row in its workspace reads the question as its title
  research.$('.reply-head').click()
  assert.deepEqual(c.calls.at(-1), ['pickRoom', { kind: 'tab', id: 'surface:12' }])
  assert.equal(tabRow(el, 'demo-task research').getAttribute('title'), tabOf(s, 'surface:12').ask.text)
  // a filed result offers no go on and carries no question (the poll reads none for a filed tab)
  const report = replyRow(el, 'report-draft')
  assert.equal(report.button(en.reply.goOn), null)
  assert.doesNotMatch(report.text(), new RegExp(en.reply.draft))
  // a typed draft in a tab that waits is named
  assert.match(replyRow(el, 'changelog').text(), new RegExp(en.reply.draft))
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
  // still where it stood, greyed, with nothing left to press on it
  assert.deepEqual(replyRows(el).map(r => r.$('.reply-name').text()), ['alpha-release', 'report-draft', 'demo-task research', 'changelog'])
  const row = replyRow(el, 'demo-task research')
  assert.ok(row.hasClass('is-left'))
  assert.match(row.text(), new RegExp(en.reply.movedOn))
  assert.equal(row.button(en.reply.yes), null)
  // answered from here, it says what the answer was
  renderSide({ ...moved, ui: { ...moved.ui, answered: { 'surface:12': { hash: tabOf(s, 'surface:12').ask.hash, q: 'Yes' } } } }, el)
  assert.match(replyRow(el, 'demo-task research').text(), new RegExp(en.reply.answered('Yes')))
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
  assert.doesNotMatch(row.text(), new RegExp(en.reply.unreadable))
  assert.equal(row.$('.reply-ask'), null)
  // a tab that waits and whose question cannot be read says so
  const blind = { ...s, tabs: { ...s.tabs, tabs: s.tabs.tabs.map(t => t.ref === 'surface:12' ? { ...t, ask: null, last: '' } : t) } }
  assert.match(replyRow(renderSide(blind), 'demo-task research').$('.reply-ask').text(), new RegExp(en.reply.unreadable))
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
  assert.equal(docs.$$('.room-tab').length, 2)                                     // its tabs stay
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
  const tr = mock.createMockTransport({ lang: 'en' })
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
  const tr = mock.createMockTransport({ lang: 'en' })
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

// ---------------------------------------------------------------- the chat: one input with a visible route (package 5)

const { ChatFoot } = views.chat
const ANSWERED = { id: 'q0123456789', kind: 'free', started_ms: NOW, session: null, total_usd: 0, running: false, last_ms: NOW,
  turns: [{ q: 'what next?', a: 'Commit the yaml change.', model_asked: 'haiku', model: 'haiku-5-5', cost_usd: 0.001, at_ms: NOW, error: null }] }

function renderFoot({ conv = null, over = {} } = {}) {
  const s = cockpitState(NOW, over)
  const c = recorder()
  const el = mount(html`<${ChatFoot} s=${s} c=${c} conv=${conv} autofocus=${false} />`)
  return { el, c, s }
}
const acts = c => c.calls.filter(x => x[0] === 'act' || x[0] === 'ask')

test('the route chip shows the guess and a click flips it', async () => {
  const { el } = renderFoot()
  assert.equal(el.$('.route-chip'), null, 'no chip while the field is empty')
  typeInto(el.$('#quick-input'), 'Fix the flaky test')
  await settle()
  assert.equal(el.$('.route-chip').text(), en.route.toTab)
  assert.equal(el.$('.route-chip').getAttribute('title'), en.route.flip)
  el.$('.route-chip').click()
  await settle()
  assert.equal(el.$('.route-chip').text(), en.route.toQuick)
  // the flip holds while typing goes on, and ends when the field is cleared
  typeInto(el.$('#quick-input'), 'Fix the flaky test now')
  await settle()
  assert.equal(el.$('.route-chip').text(), en.route.toQuick)
  typeInto(el.$('#quick-input'), '')
  await settle()
  typeInto(el.$('#quick-input'), 'Fix it')
  await settle()
  assert.equal(el.$('.route-chip').text(), en.route.toTab)
  typeInto(el.$('#quick-input'), 'what is open?')
  await settle()
  assert.equal(el.$('.route-chip').text(), en.route.toQuick)
})

test('Enter on a tab route without a conversation calls chat_tab, inside a conversation quick_handoff', async () => {
  const fresh = renderFoot()
  typeInto(fresh.el.$('#quick-input'), 'Fix the flaky test')
  await settle()
  keydown(fresh.el.$('#quick-input'), 'Enter')
  await settle()
  assert.deepEqual(acts(fresh.c), [['act', 'chat_tab', { text: 'Fix the flaky test', routed: 'words' }]])
  // a question asks here; a ! prefix is stripped and starts a tab
  const ask = renderFoot()
  typeInto(ask.el.$('#quick-input'), 'what waits for me?')
  await settle()
  keydown(ask.el.$('#quick-input'), 'Enter')
  typeInto(ask.el.$('#quick-input'), '!tidy the labels')
  await settle()
  keydown(ask.el.$('#quick-input'), 'Enter')
  await settle()
  assert.deepEqual(acts(ask.c), [['ask', 'free', { text: 'what waits for me?' }],
    ['act', 'chat_tab', { text: 'tidy the labels', routed: 'prefix' }]])
  // a flipped chip says so
  const flipped = renderFoot()
  typeInto(flipped.el.$('#quick-input'), 'the release notes')
  await settle()
  flipped.el.$('.route-chip').click()
  await settle()
  keydown(flipped.el.$('#quick-input'), 'Enter')
  await settle()
  assert.deepEqual(acts(flipped.c), [['act', 'chat_tab', { text: 'the release notes', routed: 'flipped' }]])
  // inside an answered conversation the tab route hands the chat on, with the text as the order
  const inConv = renderFoot({ conv: ANSWERED })
  typeInto(inConv.el.$('#quick-input'), 'Update the docs too')
  await settle()
  keydown(inConv.el.$('#quick-input'), 'Enter')
  await settle()
  assert.deepEqual(acts(inConv.c), [['act', 'quick_handoff', { conv: ANSWERED.id, to: 'tab', text: 'Update the docs too' }]])
})

test('Cmd+Enter starts a tab at once', async () => {
  const { el, c } = renderFoot()
  typeInto(el.$('#quick-input'), 'what waits for me?')
  await settle()
  el.$('#quick-input').dispatch('keydown', { key: 'Enter', metaKey: true })
  await settle()
  assert.deepEqual(acts(c), [['act', 'chat_tab', { text: 'what waits for me?', routed: 'forced' }]])
})

test('a handed chat shows its status and disables the handoff buttons only while starting', async () => {
  const solve = el => el.button(en.chatSolve)
  const starting = renderFoot({ conv: { ...ANSWERED, handed: { to: 'tab', at_ms: NOW, status: 'starting' } } })
  assert.match(starting.el.$('.handoff-status').text(), new RegExp(en.handoff.starting))
  assert.equal(solve(starting.el).hasAttribute('disabled'), true)
  // arrived: the tab that carries the item, one click away
  const s0 = cockpitState(NOW)
  const tab = s0.tabs.tabs.find(t => !t.is_control && t.state !== 'shell')
  const tabs = { ...s0.tabs, tabs: s0.tabs.tabs.map(t => t.ref === tab.ref ? { ...t, item: '20261009-1200-what-next-a1b2' } : t) }
  const arrived = renderFoot({ conv: { ...ANSWERED, handed: { to: 'tab', at_ms: NOW, status: 'started', inbox_id: '20261009-1200-what-next-a1b2' } },
    over: { tabs } })
  assert.match(arrived.el.$('.handoff-status').text(), new RegExp(en.handoff.inTab(tab.name)))
  assert.equal(solve(arrived.el).hasAttribute('disabled'), false)
  arrived.el.button(en.handoff.jump).click()
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
  // while typing, the chip stands where the status was
  typeInto(arrived.el.$('#quick-input'), 'and the docs?')
  await settle()
  assert.equal(arrived.el.$('.handoff-status'), null)
  assert.ok(arrived.el.$('.route-chip'))
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
  for (const word of ['starting', 'started', 'running', 'failed', 'manual', 'nothing', 'waiting', 'arrived', 'offline']) assert.ok(seen.has(word), word)
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
  const names = () => replyRows(el).map(r => r.$('.reply-name').text())
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
  assert.ok(row.hasClass('is-left') && row.button(en.reply.yes) === null)
  assert.match(row.text(), new RegExp(en.reply.answered('Yes')))
  // the agent worked and asks the identical question again: a new state since, the same hash
  const again = { ...s, tabs: { ...s.tabs, at_ms: s.tabs.at_ms + 3000, tabs: s.tabs.tabs.map(t => t.ref === 'surface:12'
    ? { ...t, since_ms: NOW - 1000 } : t) }, ui: { ...s.ui, answered: { 'surface:12': mark } } }
  const back = replyRow(renderSide(again), 'demo-task research')
  assert.ok(!back.hasClass('is-left'))
  assert.ok(back.button(en.reply.yes))
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

test('the route chip keeps the route picked by hand while the guess changes under typing', async () => {
  const { el, c } = renderFoot()
  typeInto(el.$('#quick-input'), 'Schreib mir')
  await settle()
  const guess = el.$('.route-chip').text()
  el.$('.route-chip').click()
  await settle()
  const picked = el.$('.route-chip').text()
  assert.notEqual(picked, guess)
  // typing on turns the guess around (a trailing question mark): the picked route stays
  typeInto(el.$('#quick-input'), 'Schreib mir eine kurze Zusammenfassung, geht das?')
  await settle()
  assert.equal(el.$('.route-chip').text(), picked)
  keydown(el.$('#quick-input'), 'Enter')
  await settle()
  const sent = acts(c)
  assert.equal(sent.length, 1)
  assert.equal(picked === en.route.toQuick ? sent[0][0] : sent[0][1], picked === en.route.toQuick ? 'ask' : 'chat_tab')
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

test('guide: a waiting tab shows where it stands and one branch per step, the recommended one marked', async () => {
  const s = cockpitState(NOW)
  const tab = tabOf(s, 'surface:12')
  const c = guideCtl()
  const el = mount(html`<${GuideTree} tab=${tab} s=${s} c=${c} />`)
  assert.equal(el.$('.guide-where').text(), 'Three sources found and read; nothing is written to team.md yet.')
  assert.match(el.$('.guide-waits').text(), /Whether to summarise the sources in team\.md\./)
  assert.deepEqual(optLabels(el), ['Summarise', 'List them first', 'Summarise and push', en.guide.own])
  assert.ok(el.$('.guide-branch.is-picked'), 'the recommended step is marked')
  assert.match(el.$('.guide-branch.is-picked').text(), new RegExp(en.guide.picked))
  assert.match(el.$$('.guide-branch')[2].text(), new RegExp(en.guide.risky))
  el.$$('.guide-opt')[0].click()
  await tick()
  assert.deepEqual(c.calls.find(x => x[0] === 'reply').slice(1), ['tab_send', { tab_ref: 'surface:12', text: 'Yes, summarise them in team.md.',
    expect: 'waiting', seen: tab.ask.hash, name: 'demo-task research' }])
  assert.ok(c.calls.some(x => x[0] === 'markAnswered' && x[1] === 'surface:12'))
})

test('guide: a step that reaches beyond the session sends only on the second click', async () => {
  const s = cockpitState(NOW)
  const c = guideCtl()
  const el = mount(html`<${GuideTree} tab=${tabOf(s, 'surface:12')} s=${s} c=${c} />`)
  el.$$('.guide-opt')[2].click()
  await tick()
  assert.equal(c.calls.filter(x => x[0] === 'reply').length, 0)
  assert.equal(optLabels(el)[2], en.guide.confirm('Summarise and push'))
  el.$$('.guide-opt')[2].click()
  await tick()
  assert.deepEqual(c.calls.filter(x => x[0] === 'reply').map(x => x[2].text), ['Summarise them in team.md, commit and push.'])
})

test('guide: a dialog step presses its own number with the question it was read for', async () => {
  const s = cockpitState(NOW)
  const tab = tabOf(s, 'surface:7')
  const c = guideCtl()
  const el = mount(html`<${GuideTree} tab=${tab} s=${s} c=${c} />`)
  assert.deepEqual(optLabels(el), ['Yes', 'No, and tell Claude what to do differently', en.guide.own])
  el.$$('.guide-opt')[1].click()
  await tick()
  assert.deepEqual(c.calls.find(x => x[0] === 'reply').slice(1), ['tab_option', { tab_ref: 'surface:7', n: 3, seen: tab.ask.hash, name: 'alpha-release' }])
})

test('guide: a tab not read yet offers the reading, and answering yourself opens the tab', () => {
  const s = cockpitState(NOW)
  const c = recorder()
  const el = mount(html`<${GuideTree} tab=${tabOf(s, 'surface:13')} s=${s} c=${c} />`)
  assert.match(el.text(), new RegExp(en.guide.noneYet.slice(0, 20)))
  el.button(en.guide.read).click()
  assert.deepEqual(c.calls.at(-1), ['guideRead', 'surface:13'])
  const read = mount(html`<${GuideTree} tab=${tabOf(s, 'surface:12')} s=${s} c=${c} />`)
  read.$$('.guide-opt').at(-1).click()
  assert.deepEqual(c.calls.at(-1), ['openTabView', 'surface:12'])
})

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
