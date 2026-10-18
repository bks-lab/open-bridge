// SPDX-License-Identifier: MIT
// The cockpit, the chat as cmux shows it (cockpit.chat_layout: workspaces): on the left the
// workspaces in the terminal's order with their tabs, the other Bridges on this machine and the A2A
// agents; on the right whatever is picked. Reading only: a tab is written to in its window ("Write"),
// the quick chat and the agents keep their own boxes.
// The rules every component keeps stand at the head of components.js.

import { html, useEffect, useLayoutEffect, useRef, useState } from '../vendor/htm-preact-3.1.1.module.js'
import { chatStamp, roomsOf, screenLines, shellQuote, short, stateToken } from '../logic.js'
import { T, language } from '../text.js'
import { AgentsPage } from './agents.js'
import { ChatFoot, ChatThread, useQuickLive, useStickToEnd } from './chat.js'
import { Btn, Dot, Empty, Icon, StateLine } from './parts.js'
import { useTabScreen } from './tabs.js'

const CHATS_SHOWN = 6

/** The room picked, else the chat (the open quick chat is ui.quickConv). Never picked on its own from
 *  the tabs: a tab that starts waiting would take the pane away while you type */
function pickedRoom(s) {
  return s.ui.room ?? { kind: 'chat' }
}

function Item({ on, onClick, children, title, cls = '' }) {
  return html`<button type="button" class=${`room-item ${cls}${on ? ' is-on' : ''}`} aria-current=${on ? 'true' : undefined}
    title=${title} onClick=${onClick}>${children}</button>`
}

/** What runs in a tab or a workspace (logic.js agentLoad): its subagents and workflows, each with its icon;
 *  nothing when neither runs */
function LoadChip({ load }) {
  const t = T()
  if (!load || load.subagents + load.workflows <= 0) return null
  const part = (n, icon, word) => n > 0 ? html`<span class="room-load-n"><${Icon} name=${icon} size=${12} />
    <span class="mono" aria-hidden="true">${n}</span><span class="sr-only">${word(n)}</span></span>` : null
  return html`<span class="room-load" title=${t.rooms.loadTitle(load.busy, load.subagents, load.workflows)}>
    ${part(load.subagents, 'subagent', t.rooms.subagents)}${part(load.workflows, 'workflow', t.rooms.workflows)}</span>`
}

function TabItem({ tab, on, c }) {
  const t = T()
  return html`<${Item} on=${on} cls="room-tab" title=${tab.last || tab.name} onClick=${() => c.pickRoom({ kind: 'tab', id: tab.ref })}>
    <${Dot} token=${stateToken(tab.state)} pulse=${tab.state === 'working'} />
    <span class="room-name">${tab.is_control ? t.controlSession : tab.name}</span>
    <${LoadChip} load=${tab.load} />
    <span class="room-meta muted small">${t.state[tab.state] ?? tab.state}</span>
  <//>`
}

function Chats({ convs, s, c, here }) {
  const t = T()
  const [all, setAll] = useState(false)
  const shown = all ? convs : convs.slice(0, CHATS_SHOWN)
  return html`<div class="room-chats">
    <${Item} on=${here.kind === 'chat' && !s.ui.quickConv} cls="room-chat" onClick=${() => { c.newQuick(); c.pickRoom({ kind: 'chat' }) }}>
      <span class="room-name">+ ${t.quickNew}</span><//>
    ${shown.map(x => html`<div class="room-chat-row" key=${x.id}>
      <${Item} on=${here.kind === 'chat' && s.ui.quickConv === x.id} cls="room-chat" title=${x.turns[0]?.q}
        onClick=${() => { c.pickQuick(x.id); c.pickRoom({ kind: 'chat' }) }}>
        ${x.running ? html`<${Dot} token="info" pulse />` : html`<span class="room-glyph"><${Icon} name="chat" size=${12} /></span>`}
        <span class="room-name">${short(x.turns[0]?.q ?? '', 40)}</span>
        <span class="room-meta muted small">${chatStamp(x.last_ms ?? x.started_ms, s.now, language())}</span>
      <//>
      ${x.running ? null : html`<button type="button" class="room-x" title=${t.quickForgetHint} aria-label=${t.quickForget} onClick=${() => c.quickForget(x.id)}>×</button>`}
    </div>`)}
    ${convs.length > CHATS_SHOWN ? html`<button type="button" class="btn-link small room-more" onClick=${() => setAll(!all)}>
      ${all ? t.cardLess : t.rooms.allChats(convs.length)}</button>` : null}
  </div>`
}

function WorkspaceGroup({ w, s, c, here }) {
  const t = T()
  const on = here.kind === 'ws' && here.id === w.key
  return html`<section class="room-ws" style=${w.color ? { '--ws-color': w.color } : undefined}>
    <${Item} on=${on} cls="room-ws-head" title=${w.description || w.title} onClick=${() => c.pickRoom({ kind: 'ws', id: w.key })}>
      <span class="room-ws-title">${w.pinned ? html`<span class="room-pin" aria-label=${t.rooms.pinned}>${t.rooms.pinMark}</span>` : null}${w.title}</span>
      <${LoadChip} load=${w.load} />
      ${w.state ? html`<span class="room-meta"><${StateLine} token=${stateToken(w.state)} word=${t.state[w.state] ?? w.state} /></span>` : null}
      ${w.unread ? html`<span class="room-badge mono" aria-label=${t.rooms.unread(w.unread)}>${w.unread}</span>` : null}
      ${w.bridge ? html`<span class="chip room-bridge">${w.bridge.name}</span>` : null}
    <//>
    ${w.tabs.map(tab => html`<${TabItem} key=${tab.ref} tab=${tab} on=${here.kind === 'tab' && here.id === tab.ref} c=${c} />`)}
    ${w.chats.length || (s.rooms?.control && w.title === s.rooms.control) ? html`<${Chats} convs=${w.chats} s=${s} c=${c} here=${here} />` : null}
  </section>`
}

/** The rooms in the order last shown while the pointer or the focus is in the sidebar: a row never moves
 *  away under the hand. Only the order holds; counts and states follow at once. A new room goes last.
 *  A change of the sort mode is the one reorder the hand asked for (its toggle sits in the sidebar), so it
 *  applies at once and the new order holds from there */
function useHeldOrder(list, mode) {
  const held = useRef(false)
  const shown = useRef(null)
  const lastMode = useRef(mode)
  const [, redraw] = useState(0)
  const asked = lastMode.current !== mode
  lastMode.current = mode
  let out = list
  if (held.current && shown.current && !asked) {
    const at = new Map(shown.current.map((k, i) => [k, i]))
    out = list.slice().sort((a, b) => (at.get(a.key) ?? Infinity) - (at.get(b.key) ?? Infinity))
  }
  shown.current = out.map(w => w.key)
  const hold = () => { held.current = true }
  const release = () => { if (held.current) { held.current = false; redraw(n => n + 1) } }
  return { list: out, hold, release }
}

export function Sidebar({ s, c, rooms, here }) {
  const t = T()
  const urgency = s.ui?.roomsSort === 'urgency'
  const order = useHeldOrder(rooms.workspaces, urgency ? 'urgency' : 'terminal')
  return html`<nav class="panel rooms-side" aria-label=${t.rooms.side}
    onPointerEnter=${order.hold} onPointerLeave=${order.release} onFocusIn=${order.hold}
    onFocusOut=${e => { if (!e.currentTarget.contains(e.relatedTarget)) order.release() }}>
    ${rooms.chats.length ? html`<section class="room-ws"><h3 class="label-caps">${t.rooms.chats}</h3>
      <${Chats} convs=${rooms.chats} s=${s} c=${c} here=${here} /></section>` : null}
    <div class="room-group-head">
      <h3 class="label-caps room-group">${t.rooms.workspaces}</h3>
      <${Btn} size="xs" variant="ghost" icon="sort" pressed=${urgency} title=${urgency ? t.rooms.sortUrgency : t.rooms.sortTerminal}
        onClick=${() => c.toggleRoomsSort()}>${t.rooms.sortUrgency}<//>
    </div>
    ${s.tabs?.workspaces == null ? html`<p class="muted small">${t.rooms.noList}</p>` : null}
    ${order.list.length ? order.list.map(w => html`<${WorkspaceGroup} key=${w.key} w=${w} s=${s} c=${c} here=${here} />`)
      : html`<${Empty}>${t.tabsEmpty}<//>`}
    ${rooms.bridges.length ? html`<h3 class="label-caps room-group">${t.rooms.bridges}</h3>
      ${rooms.bridges.map(b => html`<${Item} key=${b.id} on=${here.kind === 'bridge' && here.id === b.id} title=${b.purpose}
        onClick=${() => c.pickRoom({ kind: 'bridge', id: b.id })}><span class="room-name">${b.name}</span>
        <span class="room-meta muted small mono">${b.branch ?? ''}</span><//>`)}` : null}
    ${rooms.agents.length ? html`<h3 class="label-caps room-group">${t.rooms.agents}</h3>
      ${rooms.agents.map(p => html`<${Item} key=${p.id} on=${here.kind === 'agent' && here.id === p.id} title=${p.card?.description}
        onClick=${() => { c.pickAgent(p.id); c.pickRoom({ kind: 'agent', id: p.id }) }}>
        <span class="room-name">${p.card?.name || p.id}</span><span class="room-meta muted small mono">${p.id}</span><//>`)}` : null}
  </nav>`
}

/** One tab on the right: its terminal, read only; "Write" opens the tab window with its box and keys */
function TabPane({ s, c, tab }) {
  const t = T()
  // while the tab's window is open it reads the terminal itself: one reader at a time
  const { screen, err } = useTabScreen(c, s.ui.tabView ? null : tab.ref)
  const body = useRef(null)
  const stick = useRef(true)
  useLayoutEffect(() => { const el = body.current; if (el && stick.current) el.scrollTop = el.scrollHeight }, [screen?.text])
  useEffect(() => { stick.current = true }, [tab.ref])
  const lines = screenLines(screen?.text)
  return html`<section class="panel chat-main rooms-main" aria-labelledby="room-title">
    <header class="tabview-head">
      <${StateLine} token=${stateToken(tab.state)} strong=${tab.state === 'needs-you'} word=${t.state[tab.state] ?? tab.state} />
      <h2 class="sec-title tabview-title" id="room-title">${tab.is_control ? t.controlSession : tab.name}</h2>
      <span class="muted small">${tab.workspace}</span>
      <span class="tabview-live muted small" aria-live="off">${err ? html`<${StateLine} token="danger" word=${t.tabViewFailed(err)} />`
        : screen ? t.tabViewLive : t.loading}</span>
      <${Btn} size="xs" variant="primary" icon="send" title=${t.rooms.writeTitle} onClick=${() => c.openTabView(tab.ref)}>${t.rooms.write}<//>
    </header>
    <div class="tabview-body" ref=${body} tabindex="0" role="log" aria-label=${t.tabViewLog}
      onScroll=${e => { const el = e.currentTarget; stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40 }}>
      ${lines.length ? lines.map((l, i) => html`<div key=${i} class=${`tl tl-${l.kind}`}>${l.text || ' '}</div>`)
        : html`<p class="muted">${screen ? t.tabViewEmpty : t.loading}</p>`}
    </div>
  </section>`
}

function ChatPane({ s, c }) {
  const t = T()
  const q = s.quick ?? {}
  const conv = (q.convs ?? []).find(x => x.id === s.ui.quickConv) ?? null
  const body = useStickToEnd(conv, useQuickLive(conv?.id))
  return html`<section class="panel chat-main rooms-main" aria-label=${t.askTitle}>
    <header class="tabview-head"><h2 class="sec-title tabview-title">${conv ? short(conv.turns[0]?.q ?? '', 80) : t.quickNew}</h2>
      <span class="muted small">${t.rooms.chatHint}</span></header>
    <div class="tabview-body quick-body" ref=${body} tabindex="-1" role="log" aria-label=${t.quickHistory}>
      ${q.config_error || !q.available ? html`<p><${StateLine} token="warning" word=${q.config_error ?? t.quickUnavailable} /></p>` : null}
      ${!conv ? html`<div class="quick-empty"><p class="muted">${t.quickIntro}</p></div>` : html`<${ChatThread} s=${s} conv=${conv} />`}
    </div>
    <${ChatFoot} key=${conv?.id ?? 'new'} s=${s} c=${c} conv=${conv} autofocus=${false} />
  </section>`
}

function WorkspacePane({ s, c, w }) {
  const t = T()
  const facts = [[t.rooms.fact.folder, w.cwd], [t.rooms.fact.branch, w.branch ? `${w.branch}${w.dirty ? ' *' : ''}` : null],
    [t.rooms.fact.pr, w.pr], [t.rooms.fact.bridge, w.bridge?.name], [t.rooms.fact.last, w.latest?.text]].filter(([, v]) => v)
  return html`<section class="panel chat-main rooms-main room-ws-pane" style=${w.color ? { '--ws-color': w.color } : undefined} aria-labelledby="room-title">
    <header class="tabview-head"><h2 class="sec-title tabview-title" id="room-title">${w.title}</h2>
      ${w.description ? html`<span class="muted small">${w.description}</span>` : null}</header>
    <div class="tabview-body">
      ${facts.length ? html`<dl class="agent-facts">${facts.map(([k, v]) => html`<div key=${k}><dt>${k}</dt><dd class="mono">${v}</dd></div>`)}</dl>` : null}
      ${(w.statuses ?? []).length ? html`<p class="small">${w.statuses.map(x => html`<span key=${x.name} class="chip">${x.text}</span> `)}</p>` : null}
      ${w.tabs.length ? html`<ul class="room-list">${w.tabs.map(tab => html`<li key=${tab.ref}><button type="button" class="btn-link"
        onClick=${() => c.pickRoom({ kind: 'tab', id: tab.ref })}>${tab.name}</button>
        <span class="muted small"> ${t.state[tab.state] ?? tab.state}</span></li>`)}</ul>` : html`<${Empty}>${t.rooms.noTabs}<//>`}
    </div>
  </section>`
}

/** Another Bridge: where it is and how to work in it. Nothing of it is read here (its own session works there) */
function BridgePane({ c, b }) {
  const t = T()
  const command = `cd ${shellQuote(b.path)} && claude`
  return html`<section class="panel chat-main rooms-main" aria-labelledby="room-title">
    <header class="tabview-head"><h2 class="sec-title tabview-title" id="room-title">${b.name}</h2>
      ${b.purpose ? html`<span class="muted small">${b.purpose}</span>` : null}</header>
    <div class="tabview-body">
      <dl class="agent-facts"><div><dt>${t.rooms.fact.folder}</dt><dd class="mono">${b.path}</dd></div>
        ${b.branch ? html`<div><dt>${t.rooms.fact.branch}</dt><dd class="mono">${b.branch}</dd></div>` : null}</dl>
      <p class="small">${t.rooms.bridgeHint}</p>
      <p class="btn-row"><code class="mono small">${command}</code>
        <${Btn} size="xs" icon="copy" onClick=${() => c.copy(command)}>${t.askCopy}<//></p>
    </div>
  </section>`
}

export function RoomsPage({ s, c }) {
  const t = T()
  const rooms = roomsOf(s)
  const here = pickedRoom(s)
  useEffect(() => { c.loadAgents() }, [])
  let pane = null
  if (here.kind === 'tab') {
    const tab = (s.tabs?.tabs ?? []).find(x => x.ref === here.id)
    pane = tab ? html`<${TabPane} key=${tab.ref} s=${s} c=${c} tab=${tab} />` : html`<section class="panel chat-main rooms-main"><${Empty}>${t.rooms.gone}<//></section>`
  } else if (here.kind === 'ws') {
    const w = rooms.workspaces.find(x => x.key === here.id)
    pane = w ? html`<${WorkspacePane} s=${s} c=${c} w=${w} />` : null
  } else if (here.kind === 'bridge') {
    const b = (s.rooms?.bridges ?? []).find(x => x.id === here.id)
    pane = b ? html`<${BridgePane} c=${c} b=${b} />` : null
  } else if (here.kind === 'agent') {
    pane = html`<section class="panel chat-main rooms-main rooms-agent"><${AgentsPage} s=${s} c=${c} embedded /></section>`
  }
  pane = pane ?? html`<${ChatPane} s=${s} c=${c} />`
  return html`<div class="col col-page roomspage">
    <div class="rooms-grid">
      <${Sidebar} s=${s} c=${c} rooms=${rooms} here=${here} />
      ${pane}
    </div>
  </div>`
}
