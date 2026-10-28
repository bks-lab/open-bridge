// SPDX-License-Identifier: MIT
// The A2A area of the chat as cmux (cockpit.chat_layout: workspaces), no npm dependencies.
//
//   node --test scripts/tests/bridge_cockpit_chat_a2a.test.mjs
//
// With the workspaces layout the agents have no page of their own: the Chat carries a switch above its
// sidebar, Work and A2A, and every way to an agent lands there. The classic layout keeps its Agents tab.
import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { cockpitState, loadCockpit, mount, recorder } from './cockpit_render.mjs'

const { html, views, text, logic, render } = await loadCockpit()
const { RoomsPage } = views.rooms
const { agentBadge } = views.agents
const nav = views.nav
const en = text.TABLES.en
const de = text.TABLES.de
const WEB = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'web')
const read = rel => fs.readFileSync(path.join(WEB, rel), 'utf8')

const NOW = new Date(2026, 9, 9, 12, 0, 0).getTime()
const WS = { layout: 'workspaces' }
const state = (over = {}) => cockpitState(NOW, { rooms: WS, ...over })
const noPeers = over => state({ agents: { peers: [], convs: [] }, ...over })
const conv = (over = {}) => ({ id: 'g0000000001', peer: 'team-bridge', started_ms: NOW - 60000, last_ms: NOW - 60000, context_id: null,
  running: false, turns: [{ q: 'Hello?', mode: 'question', a: null, waiting: false, at_ms: NOW, error: null }], ...over })
const withConvs = (convs, over = {}) => { const s0 = state(); return state({ agents: { ...s0.agents, convs }, ...over }) }

test('pages: the workspaces layout has no Agents tab, the classic one keeps it behind More', () => {
  const peers = { agents: { peers: [{ id: 'a' }] } }
  assert.ok(!nav.pageOrder({ ...peers, rooms: WS }).includes(nav.AGENTS_PAGE))
  assert.ok(!nav.morePages({ ...peers, rooms: WS }).has(nav.AGENTS_PAGE))
  assert.ok(nav.pageOrder({ ...peers, rooms: { layout: 'classic' } }).includes(nav.AGENTS_PAGE))
  assert.ok(nav.pageOrder(peers).includes(nav.AGENTS_PAGE))
})

test('chatArea: Work by default, A2A only where the layout is workspaces and a peer exists', () => {
  assert.equal(nav.chatAreaOf(state()), 'work')
  assert.equal(nav.chatAreaOf(state({ ui: { chatArea: 'a2a' } })), 'a2a')
  assert.equal(nav.chatAreaOf(state({ ui: { chatArea: 'nonsense' } })), 'work')
  assert.equal(nav.chatAreaOf(noPeers({ ui: { chatArea: 'a2a' } })), 'work')
  assert.equal(nav.chatAreaOf(cockpitState(NOW, { ui: { chatArea: 'a2a' } })), 'work', 'the classic layout has no A2A area')
})

// a small store for the controller's actions of the Chat's areas (views/nav.js chatAreaActions, which app.js
// spreads into ctl): the test drives the actions themselves, not their source
function harness(s0) {
  let s = s0
  const saved = {}
  const acts = nav.chatAreaActions({
    get: () => s,
    setUi: p => { s = { ...s, ui: { ...s.ui, ...(typeof p === 'function' ? p(s.ui) : p) } } },
    save: (k, v) => { saved[k] = v },
    now: () => NOW,
  })
  return { acts, get: () => s, saved }
}

test('chatArea: kept in this browser like the agents list, read with a fallback and saved on a switch', () => {
  const app = read('app.js')
  assert.match(app, /chatArea: load\('bridge-cockpit\.chatArea', 'work'\) === 'a2a' \? 'a2a' : 'work'/)
  // load and save keep to try/catch: storage may be blocked
  assert.match(app.match(/function load\(key, fallback\) \{[\s\S]*?\n\}/)[0], /try \{/)
  assert.match(app.match(/function save\(key, value\) \{[\s\S]*?\n\}/)[0], /try \{/)
  const h = harness(state())
  h.acts.setChatArea('a2a')
  assert.equal(h.get().ui.chatArea, 'a2a')
  assert.equal(h.saved['bridge-cockpit.chatArea'], 'a2a')
  assert.equal(nav.chatAreaOf(h.get()), 'a2a')
  h.acts.setChatArea('work')
  assert.equal(h.saved['bridge-cockpit.chatArea'], 'work')
  assert.equal(nav.chatAreaOf(h.get()), 'work')
  // an area the Chat cannot show (no peer) is not kept: a peer that turns up later would open A2A unasked
  const none = harness(noPeers())
  none.acts.setChatArea('a2a')
  assert.equal(none.get().ui.chatArea, 'work')
  assert.notEqual(none.saved['bridge-cockpit.chatArea'], 'a2a')
})

test('pickAgent: as cmux it opens the A2A area on the agent\'s latest conversation; classic keeps the area', () => {
  const convs = [conv({ id: 'g1', peer: 'docs-agent', last_ms: NOW - 9000 }), conv({ id: 'g2', peer: 'docs-agent', last_ms: NOW - 1000 })]
  const h = harness(withConvs(convs))
  h.acts.pickAgent('docs-agent')
  assert.equal(h.get().ui.agentPeer, 'docs-agent')
  assert.equal(h.get().ui.agentConv, 'g2')
  assert.equal(nav.chatAreaOf(h.get()), 'a2a')
  assert.equal(h.saved['bridge-cockpit.chatArea'], 'a2a')
  // never one the list no longer shows (past keep_hours): then a new conversation
  const old = harness(withConvs([conv({ id: 'g9', peer: 'docs-agent', last_ms: NOW - 30 * 3600000 })]))
  old.get().agents.keep_hours = 24
  old.acts.pickAgent('docs-agent')
  assert.equal(old.get().ui.agentConv, null)
  const classic = harness(cockpitState(NOW))
  classic.acts.pickAgent('docs-agent')
  assert.equal(classic.get().ui.agentPeer, 'docs-agent')
  assert.equal(classic.get().ui.chatArea, undefined)
  assert.deepEqual(classic.saved, {})
  const none = harness(noPeers())
  none.acts.pickAgent('docs-agent')
  assert.notEqual(none.get().ui.chatArea, 'a2a')
  assert.equal(none.saved['bridge-cockpit.chatArea'], undefined)
})

test('openAgentConv: lands on the Chat in its A2A area with the conversation picked, the Agents page when classic', () => {
  const h = harness(withConvs([conv({ id: 'g7', peer: 'team-bridge' })], { ui: { page: 'briefing', tabView: 'x' } }))
  h.acts.openAgentConv('g7')
  const ui = h.get().ui
  assert.equal(ui.page, nav.CHAT_PAGE)
  assert.equal(nav.chatAreaOf(h.get()), 'a2a')
  assert.equal(ui.agentConv, 'g7')
  assert.equal(ui.agentPeer, 'team-bridge')
  assert.equal(ui.tabView, null)
  assert.equal(h.saved['bridge-cockpit.page'], nav.CHAT_PAGE)
  assert.equal(h.saved['bridge-cockpit.chatArea'], 'a2a')
  // what then shows: the A2A area with the conversation on the right
  const el = mount(html`<${RoomsPage} s=${h.get()} c=${recorder()} />`)
  assert.ok(el.$('.rooms-agents'), 'the agent cards')
  assert.equal(el.$('.rooms-side'), null)
  render(null, el)
  const classic = harness(cockpitState(NOW))
  classic.acts.openAgentConv('g7')
  assert.equal(classic.get().ui.page, nav.AGENTS_PAGE)
  assert.equal(classic.saved['bridge-cockpit.page'], nav.AGENTS_PAGE)
})

test('pageFor: @agents (the band, a stored page, the start page) becomes the Chat on its A2A area as cmux', () => {
  assert.deepEqual(nav.agentsLanding(state()), { page: nav.CHAT_PAGE, chatArea: 'a2a' })
  assert.deepEqual(nav.agentsLanding(noPeers()), { page: nav.CHAT_PAGE })
  assert.deepEqual(nav.agentsLanding(cockpitState(NOW)), { page: nav.AGENTS_PAGE })
  const h = harness(state())
  assert.equal(h.acts.pageFor(nav.AGENTS_PAGE), nav.CHAT_PAGE)
  assert.equal(nav.chatAreaOf(h.get()), 'a2a')
  assert.equal(h.saved['bridge-cockpit.chatArea'], 'a2a')
  assert.equal(h.acts.pageFor('briefing'), 'briefing')
  // without a peer the Chat opens on Work, and no A2A choice is kept for later
  const none = harness(noPeers())
  assert.equal(none.acts.pageFor(nav.AGENTS_PAGE), nav.CHAT_PAGE)
  assert.equal(none.saved['bridge-cockpit.chatArea'], undefined)
  assert.notEqual(none.get().ui.chatArea, 'a2a')
  const classic = harness(cockpitState(NOW))
  assert.equal(classic.acts.pageFor(nav.AGENTS_PAGE), nav.AGENTS_PAGE)
  assert.deepEqual(classic.saved, {})
  // the controller takes these actions and its setPage asks pageFor; nothing sets a room past them
  const app = read('app.js')
  assert.match(app, /\.\.\.chatAreaActions\(\{/)
  assert.match(app.match(/setPage\(id\) \{[\s\S]*?\n  \},/)[0], /id = ctl\.pageFor\(id\)/)
  assert.doesNotMatch(app, /setUi\(\{ room: /)
  assert.doesNotMatch(app, /save\('bridge-cockpit\.chatArea'/)
  assert.doesNotMatch(read('views/stage.js'), /setPage\(AGENTS_PAGE\)/)
  // the ticker's page target @agents is a known page wherever a peer exists
  assert.equal(logic.tickerPage(state(), '@agents', nav.pageOrder(state())), '@agents')
  assert.equal(logic.tickerPage(noPeers(), '@agents', nav.pageOrder(noPeers())), 'briefing')
})

test('a room of the work shows on Work even when the Chat was left on A2A: pick, walk, the waiting tabs', () => {
  const left = over => state({ ui: { page: nav.CHAT_PAGE, chatArea: 'a2a', ...over } })
  const tab = left().tabs.tabs[0]
  assert.ok(tab, 'a tab in the state')
  const paths = {
    pickTab: a => a.pickRoom({ kind: 'tab', id: tab.ref }),
    pickWs: a => a.pickRoom({ kind: 'ws', id: 'x' }),
    pickBridge: a => a.pickRoom({ kind: 'bridge', id: 'x' }),
    pickChat: a => a.pickRoom({ kind: 'chat' }),
    walkFrom: a => a.walkFrom([tab.ref]),    // Work through, the n shortcut, the start page's waiting tabs (goArea)
    walkTab: a => a.walkTab(tab.ref, { focus: true }),
  }
  for (const [name, go] of Object.entries(paths)) {
    const h = harness(left())
    assert.equal(nav.chatAreaOf(h.get()), 'a2a', name)
    go(h.acts)
    assert.equal(nav.chatAreaOf(h.get()), 'work', name)
    assert.equal(h.saved['bridge-cockpit.chatArea'], 'work', name)
    const el = mount(html`<${RoomsPage} s=${h.get()} c=${recorder()} />`)
    assert.ok(el.$('.rooms-side'), `${name}: the work sidebar`)
    assert.equal(el.$('.rooms-agents'), null, name)
    render(null, el)   // a tab's pane keeps a timer: unmounted, the test run can end
  }
  const h = harness(left())
  h.acts.walkFrom([tab.ref, 'other'])
  assert.deepEqual(h.get().ui.room, { kind: 'tab', id: tab.ref })
  assert.deepEqual(h.get().ui.tabWalk, [tab.ref, 'other'])
  h.acts.walkFrom([])
  assert.deepEqual(h.get().ui.room, { kind: 'tab', id: tab.ref }, 'an empty walk changes nothing')
  // the area stays as it was where nothing changes: a pick on Work does not write the area again (only the room it
  // picked, which the Chat opens on next time, round 6d C3)
  const w = harness(state({ ui: { chatArea: 'work' } }))
  w.acts.pickRoom({ kind: 'chat' })
  assert.deepEqual(w.saved, { 'bridge-cockpit.chatRoom': '{"kind":"chat"}' })
})

test('the switch above the sidebar: Work and A2A with the number of agents, only where a peer exists', () => {
  const s = state()
  const c = recorder()
  const el = mount(html`<${RoomsPage} s=${s} c=${c} />`)
  const sw = el.$('.rooms-area')
  assert.ok(sw, 'a switch above the sidebar')
  assert.deepEqual(sw.$$('button').map(b => b.text()), [en.chatArea.work, en.chatArea.a2a(s.agents.peers.length)])
  // the click log tells the two apart by name (round 6d), the words never leave the page
  assert.deepEqual(sw.$$('button').map(b => b.getAttribute('data-u')), ['chat-work', 'chat-a2a'])
  assert.equal(sw.button(en.chatArea.work).getAttribute('aria-pressed'), 'true')
  sw.button(en.chatArea.a2a(s.agents.peers.length)).click()
  assert.deepEqual(c.calls.filter(x => x[0] === 'setChatArea'), [['setChatArea', 'a2a']])
  // the agents left the work sidebar; the Bridges on this machine stay there
  assert.equal(el.$$('.rooms-side .agent-card').length, 0)
  assert.doesNotMatch(el.$('.rooms-side').text(), new RegExp(en.chatArea.agents.replace(/[()]/g, '\\$&')))
  // no peer, no switch
  assert.equal(mount(html`<${RoomsPage} s=${noPeers()} c=${recorder()} />`).$('.rooms-area'), null)
})

test('the A2A area: the agent cards on the left, the conversation of the picked one on the right', () => {
  const s = state({ ui: { chatArea: 'a2a', agentPeer: 'docs-agent' } })
  const c = recorder()
  const el = mount(html`<${RoomsPage} s=${s} c=${c} />`)
  const cards = el.$$('.rooms-agents .agent-card')
  assert.equal(cards.length, s.agents.peers.length)
  // each card keeps its reach dot
  assert.ok(cards.every(x => x.$('.rdot')), 'a reach dot on every card')
  assert.ok(el.$('.rooms-agents .agent-card.is-on').text().includes('docs-agent'))
  // no work sidebar in this area, the conversation embedded on the right
  assert.equal(el.$('.rooms-side'), null)
  assert.ok(el.$('.agentspage.is-embedded'), 'the conversation')
  assert.equal(el.$$('.agentspage .agents-list').length, 0)
  assert.equal(el.$('.rooms-area').button(en.chatArea.work).getAttribute('aria-pressed'), 'false')
  cards[0].$('.agent-pick').click()
  assert.deepEqual(c.calls.filter(x => x[0] === 'pickAgent'), [['pickAgent', s.agents.peers[0].id]])
})

test('agentBadge: running before waiting, nothing when no conversation does either', () => {
  assert.equal(agentBadge(state({ agents: { peers: [], convs: [] } })), null)
  assert.equal(agentBadge({}), null)
  assert.equal(agentBadge(withConvs([conv({ running: true })])), 'running')
  assert.equal(agentBadge(withConvs([conv({ turns: [{ q: 'x', waiting: true }] })])), 'waiting')
  assert.equal(agentBadge(withConvs([conv({ turns: [{ q: 'x', waiting: true }] }), conv({ id: 'g2', running: true })])), 'running')
})

test('the signal stays visible: the Chat tab and the A2A switch carry the agents\' badge', () => {
  const { chatTabSignal } = views.header
  const quick = { quick: { convs: [{ id: 'q', running: true }] } }
  assert.equal(chatTabSignal(state()), null)
  assert.equal(chatTabSignal(state(quick)), 'quick')
  assert.equal(chatTabSignal(withConvs([conv({ running: true })])), 'running')
  assert.equal(chatTabSignal(withConvs([conv({ turns: [{ q: 'x', waiting: true }] })])), 'waiting')
  assert.equal(chatTabSignal(withConvs([conv({ running: true })], quick)), 'quick', 'the quick chat\'s spinner first')
  // classic: the Agents tab wears the agents' signal, the Chat tab only its own
  const s0 = cockpitState(NOW)
  assert.equal(chatTabSignal(cockpitState(NOW, { agents: { ...s0.agents, convs: [conv({ running: true })] } })), null)
  assert.equal(chatTabSignal(cockpitState(NOW, quick)), 'quick')
  // the page bar measures itself and cannot mount in the small DOM: its Chat tab wears chatTabSignal through ChatTabMark
  const header = read('views/header.js')
  assert.match(header, /tab\(CHAT_PAGE, t\.chatTab, html`<\$\{ChatTabMark\} kind=\$\{chatTabSignal\(s\)\} \/>`\)/)
  const { ChatTabMark } = views.header
  assert.ok(mount(html`<${ChatTabMark} kind="quick" />`).$('.spinner'))
  assert.ok(mount(html`<${ChatTabMark} kind="running" />`).$('.agent-mark .spinner'))
  assert.ok(mount(html`<${ChatTabMark} kind="waiting" />`).$('.agent-mark .dot.tk-warning'))
  assert.equal(mount(html`<${ChatTabMark} kind=${null} />`).text(), '')
  const s = withConvs([conv({ running: true })])
  const sw = mount(html`<${RoomsPage} s=${s} c=${recorder()} />`).$('.rooms-area')
  assert.ok(sw.$$('button')[1].$('.spinner'), 'the A2A switch spins while an agent answers')
  const held = withConvs([conv({ turns: [{ q: 'x', waiting: true }] })])
  const sw2 = mount(html`<${RoomsPage} s=${held} c=${recorder()} />`).$('.rooms-area')
  assert.ok(sw2.$$('button')[1].$('.dot.tk-warning'), 'a dot while an answer is held')
})

test('the words of the switch stand in both languages', () => {
  for (const t of [en, de]) {
    assert.ok(t.chatArea.label && t.chatArea.work && t.chatArea.a2a(2))
    assert.match(t.chatArea.a2a(2), /A2A/)
  }
  assert.equal(de.chatArea.work, 'Arbeit')
  assert.equal(de.chatArea.a2a(3), 'A2A (3)')
})

test('the heights: the switch takes its room only where it stands, and the A2A list keeps its own', () => {
  // no layout in the small DOM: the rules are read from the stylesheet
  const css = read('style.css')
  const rule = sel => css.match(new RegExp(`(?:^|\\n)\\s*${sel.replace(/[.()>:]/g, '\\$&')} \\{([^}]*)\\}`))?.[1]
  // the work sidebar without a switch (no peer) keeps its height as before
  assert.match(rule('.rooms-side'), /max-height: calc\(100dvh - 180px\)/)
  // with the switch above it, it gives up the switch's room; on a wide page only (narrow keeps 260px)
  const wide = css.match(/@media \(min-width: 900px\) \{([\s\S]*?)\n\}/g)?.find(b => b.includes('.rooms-area'))
  assert.ok(wide, 'a wide-page block for the switch')
  assert.match(wide, /\.rooms-left:has\(> \.rooms-area\) > \.rooms-side,\s*\.rooms-agents\.agents-list \{ max-height: calc\(100dvh - 220px\); \}/)
  // .agents-list comes later and would win at the same weight: the A2A list names both classes, and no dead rule is left
  assert.doesNotMatch(rule('.rooms-agents') ?? '', /max-height/)
})
