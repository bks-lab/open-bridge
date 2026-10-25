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

const { html, views, text, logic } = await loadCockpit()
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

test('chatArea: kept in this browser like the agents list, read with a fallback and saved on a switch', () => {
  const app = read('app.js')
  assert.match(app, /chatArea: load\('bridge-cockpit\.chatArea', 'work'\) === 'a2a' \? 'a2a' : 'work'/)
  const set = app.match(/setChatArea: area => \{[\s\S]*?\n  \},/)?.[0]
  assert.ok(set, 'a setChatArea action')
  assert.match(set, /save\('bridge-cockpit\.chatArea', /)
  // load and save keep to try/catch: storage may be blocked
  assert.match(app.match(/function load\(key, fallback\) \{[\s\S]*?\n\}/)[0], /try \{/)
  assert.match(app.match(/function save\(key, value\) \{[\s\S]*?\n\}/)[0], /try \{/)
})

test('agentsLanding: an agent opens on the Chat in its A2A area, or on the Agents page in the classic layout', () => {
  assert.deepEqual(nav.agentsLanding(state()), { page: nav.CHAT_PAGE, chatArea: 'a2a' })
  assert.deepEqual(nav.agentsLanding(cockpitState(NOW)), { page: nav.AGENTS_PAGE })
  // every jump goes through it: openAgentConv, the agents of the stage, the ticker target, a stored page
  const app = read('app.js')
  const open = app.match(/openAgentConv: conv => \{[\s\S]*?\n  \},/)?.[0]
  assert.ok(open && /agentsLanding\(/.test(open), 'openAgentConv lands where agentsLanding says')
  const pick = app.match(/pickAgent: peer => \{[\s\S]*?\n  \},/)?.[0]
  assert.match(pick, /chatArea: 'a2a'/)
  assert.match(app.match(/setPage\(id\) \{[\s\S]*?\n  \},/)[0], /id === AGENTS_PAGE/)
  assert.match(app.match(/function fixPage\(\) \{[\s\S]*?\n\}/)[0], /AGENTS_PAGE/)
  assert.doesNotMatch(read('views/stage.js'), /setPage\(AGENTS_PAGE\)/)
  // the ticker's page target @agents is a known page wherever a peer exists
  assert.equal(logic.tickerPage(state(), '@agents', nav.pageOrder(state())), '@agents')
  assert.equal(logic.tickerPage(noPeers(), '@agents', nav.pageOrder(noPeers())), 'briefing')
})

test('the switch above the sidebar: Work and A2A with the number of agents, only where a peer exists', () => {
  const s = state()
  const c = recorder()
  const el = mount(html`<${RoomsPage} s=${s} c=${c} />`)
  const sw = el.$('.rooms-area')
  assert.ok(sw, 'a switch above the sidebar')
  assert.deepEqual(sw.$$('button').map(b => b.text()), [en.chatArea.work, en.chatArea.a2a(s.agents.peers.length)])
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
  // the page bar measures itself and cannot mount in the small DOM: the Chat tab is read from its source.
  // In the workspaces layout it shows the agents' badge beside the quick chat's spinner, through agentBadge
  const header = read('views/header.js')
  const chatTab = header.match(/\$\{tab\(CHAT_PAGE, [^\n]*/)?.[0]
  assert.ok(chatTab && /chatBadge/.test(chatTab), 'the Chat tab takes its badge from chatBadge')
  assert.match(header, /const chatBadge = [^\n]*agentBadge\(s\)/)
  assert.equal((header.match(/x\.turns\?\.\[x\.turns\.length - 1\]\?\.waiting/g) ?? []).length, 0, 'no copy of the badge rule left')
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
