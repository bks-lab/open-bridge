// SPDX-License-Identifier: MIT
// The cockpit, the chat as cmux shows it (cockpit.chat_layout: workspaces): a switch on top of the left
// side picks the area, Work or A2A. Work lists the workspaces in the terminal's order with their tabs and
// the other Bridges on this machine, A2A the agents as cards (views/agents.js); on the right whatever is
// picked. Reading only: a tab is written to in its window ("Write"), the quick chat and the agents keep their
// own boxes. A tab or a workspace of its own may get a name
// here (RenameField); task tabs and the control session keep theirs (logic.js canRename). "Organize with AI"
// in the sidebar's head asks the model for a tidier order of this Bridge's workspaces (views/organize.js).
// Round 6, from the Sessions page: on top of Work why the relay has nobody to ask with the button that starts a
// control session (views/header.js ControlNotice), and why the tabs may be missing or stale (views/tabs.js
// TabWarnings); a tab's pane names the task it works on, which opens in the drawer over the Chat.
// Round 6d: the questions stand under the tabs waiting for you, by title, open and handed ones first with their markers,
// and "all" reaches the ones archived in the last days (read only: an archived one opens without its box). A waiting
// tab is a short line there, answered only on the right (C2); the Chat opens where this browser was last (C3); a tab
// says what it came from, a link to it (C5).
// The open tab's head closes a tab that neither works nor asks through the one close of every place (views/detail.js
// TabClose: Done and close tab where a task or an item stands behind it) and walks on; a line of Waiting for you
// stays one line (C2), so its close is that head's.
// The rules every component keeps stand at the head of components.js.

import { html, useEffect, useRef, useState } from '../vendor/htm-preact-3.1.1.module.js'
import { ASK_ARCHIVE_DAYS, askList, attentionTabs, canRename, canRenameWorkspace, canTab, chatLanding, chatStamp, duration, fieldsOf, indexRows, isAnswered, isTopic, listedChats, roomShown, roomsOf, shellQuote, short, stateToken, statusQueue, tabOrigin, tabWalkView, taskOfTab, waitLage, walkRefs, tabStateKey, wantsYou } from '../logic.js'
import { T, language } from '../text.js'
import { AgentList, AgentMark, AgentsPage, agentBadge } from './agents.js'
import { AskMark, ChatFoot, ChatIntro, ChatThread, useQuickLive, useStickToEnd } from './chat.js'
import { Segmented, TabClose } from './detail.js'
import { AnswerBar, EmptyField, FieldBar, FieldClose, FieldGrid, FieldGrip, TopicPane, dragTab } from './fields.js'
import { Btn, Dot, Empty, Icon, StateLine, WalkBar } from './parts.js'
import { ControlNotice } from './header.js'
import { chatAreaOf, openOrigin } from './nav.js'
import { TabWarnings, TermScreen, useTabScreen } from './tabs.js'

const CHATS_SHOWN = 6

/** The room picked, else the chat (the open quick chat is ui.quickConv); one kept from before a reload that is
 *  gone shows the chat (logic.js roomShown). Never picked on its own from the tabs once the Chat is open: a tab
 *  that starts waiting would take the pane away while you type */
const pickedRoom = roomShown

function Item({ on, onClick, onDblClick, children, title, cls = '', drag = null }) {
  return html`<button type="button" class=${`room-item ${cls}${on ? ' is-on' : ''}`} aria-current=${on ? 'true' : undefined}
    title=${title} onClick=${onClick} onDblClick=${onDblClick} draggable=${drag ? 'true' : undefined} onDragStart=${drag ? dragTab(drag) : undefined}>${children}</button>`
}

/** A click that picks a room; the second click of a double click picks nothing again (it opens the rename) */
const firstClick = fn => e => { if ((e?.detail ?? 1) <= 1) fn() }

/** What a tab came from (logic.js tabOrigin), left out where it is the task `slug` the tab already names */
function shownOrigin(s, tab, slug) {
  const from = tabOrigin(s, tab, language())
  return from && !(slug && from.key === `task:${slug}`) ? from : null
}

/** Whether the workplace knows this tab by its name (a task, an inbox item, a team role): it keeps that name */
const taskTab = tab => !!(tab.slug || tab.item || tab.team)

/** The new name of a tab or a workspace, in place of its row: Enter or Save takes it (trimmed, never
 *  empty), Esc or Cancel leaves the old one. The field stands instead of the row's button, never inside it */
function RenameField({ value, label, onSave, onCancel }) {
  const t = T()
  const [text, setText] = useState(value ?? '')
  const [bad, setBad] = useState(false)
  const input = useRef(null)
  useEffect(() => { input.current?.focus?.(); input.current?.select?.() }, [])
  const save = raw => {
    const v = String(raw ?? '').trim()
    if (!v) { setBad(true); return }
    onSave(v)
  }
  const onKey = e => {
    if (e.key === 'Enter') { e.preventDefault(); save(e.currentTarget.value) }
    else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); onCancel() }
  }
  return html`<div class="room-rename">
    <input type="text" class="input room-rename-input" ref=${input} value=${text} maxlength="80" aria-label=${label}
      aria-invalid=${bad ? 'true' : undefined} onInput=${e => { setText(e.currentTarget.value); setBad(false) }} onKeyDown=${onKey} />
    <${Btn} size="xs" variant="primary" onClick=${() => save(input.current?.value ?? text)}>${t.rooms.save}<//>
    <${Btn} size="xs" variant="ghost" onClick=${() => onCancel()}>${t.rooms.cancel}<//>
  </div>`
}

/** Sends the new name; the field closes once the terminal took it, and stays with what was typed otherwise */
async function saveName(c, verb, args) {
  const r = await c.act(verb, args)
  if (r?.ok) c.stopRename()
}

function renaming(s, kind, id) {
  const r = s.ui?.renaming
  return !!r && r.kind === kind && r.id === id
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

/** A tab's row in its workspace: its dot, name and state, and under it what it came from (logic.js tabOrigin; the
 *  link to it stands in the tab's head), unless that is its own task, whose name it carries already. `dim`: it stands in Waiting for you above, so here it is a grey line that
 *  only says it waits (round 6d C2) */
function TabItem({ tab, on, s, c, where = false, dim = false }) {
  const t = T()
  if (renaming(s, 'tab', tab.ref)) {
    return html`<${RenameField} value=${tab.name} label=${t.rooms.renameTab}
      onSave=${title => saveName(c, 'tab_rename', { tab_ref: tab.ref, title })} onCancel=${() => c.stopRename()} />`
  }
  const from = shownOrigin(s, tab, tab.slug)
  return html`<${Item} on=${on} cls=${`room-tab${dim ? ' is-dim' : ''}${from ? ' has-from' : ''}`} title=${tab.ask?.text || tab.last || tab.name} drag=${tab.ref} onClick=${firstClick(() => c.pickRoom({ kind: 'tab', id: tab.ref }))}
    onDblClick=${canRename(s, tab) ? () => c.startRename('tab', tab.ref) : undefined}>
    <${Dot} token=${dim ? 'muted' : stateToken(tabStateKey(tab))} pulse=${tab.state === 'working'} />
    <span class="room-name">${tab.is_control ? t.controlSession : tab.name}</span>
    <${LoadChip} load=${tab.load} />
    <span class="room-meta muted small">${where ? tab.workspace : dim ? t.state.waiting : t.state[tabStateKey(tab)] ?? tab.state}</span>
    ${from ? html`<span class="room-from muted small">${t.rooms.from(from.title)}</span>` : null}
  <//>`
}

/** The questions (logic.js askList): open and handed ones first, each by its title on a line of its own (what tells
 *  questions apart: the job, the machine, the state), its marker and time under it; "all"
 *  shows every one of the last days, the archived ones too (s.chatArchive, read once), greyed and without ×, or
 *  says that the archive holds none */
function Chats({ convs, s, c, here }) {
  const t = T()
  const all = !!s.ui.asksAll
  const live = askList(convs, s, language())
  const ids = new Set(live.map(x => x.conv.id))
  const old = all ? askList((s.chatArchive?.convs ?? []).filter(x => !ids.has(x.id)), s, language()).map(x => ({ ...x, archived: true })) : []
  const shown = all ? [...live, ...old] : live.slice(0, CHATS_SHOWN)
  return html`<div class="room-chats">
    ${shown.map(({ conv: x, title, mark, archived }) => html`<div class=${`room-chat-row${archived ? ' is-archived' : ''}`} key=${x.id}>
      <${Item} on=${here.kind === 'chat' && s.ui.quickConv === x.id} cls="room-chat" title=${x.turns[0]?.q}
        onClick=${() => { c.pickQuick(x.id); c.pickRoom({ kind: 'chat' }) }}>
        ${x.running ? html`<${Dot} token="info" pulse />` : html`<span class="room-glyph"><${Icon} name="chat" size=${12} /></span>`}
        <span class="room-name">${title}</span>
        <span class="room-sub"><${AskMark} mark=${mark} archived=${archived} />
          <span class="room-meta muted small">${chatStamp(x.last_ms ?? x.started_ms, s.now, language())}</span></span>
      <//>
      ${x.running || archived ? null : html`<button type="button" class="room-x" title=${t.quickForgetHint} aria-label=${t.quickForget} onClick=${() => c.quickForget(x.id)}>×</button>`}
    </div>`)}
    ${all && s.chatArchive?.status === 'loading' ? html`<p class="muted small room-more">${t.asks.loading}</p>` : null}
    ${all && s.chatArchive?.status === 'error' ? html`<p class="muted small room-more">${t.asks.failed}</p>` : null}
    ${all && s.chatArchive?.status === 'ok' && !old.length ? html`<p class="muted small room-more">${t.asks.noneArchived(ASK_ARCHIVE_DAYS)}</p>` : null}
    <button type="button" class="btn-link small room-more" onClick=${() => c.showAllAsks(!all)}>${all ? t.cardLess : t.rooms.allAsks}</button>
  </div>`
}

function WorkspaceGroup({ w, s, c, here, waits }) {
  const t = T()
  const on = here.kind === 'ws' && here.id === w.key
  const head = renaming(s, 'ws', w.ref) && w.ref
    ? html`<${RenameField} value=${w.title} label=${t.rooms.renameWs}
        onSave=${title => saveName(c, 'workspace_rename', { ws_ref: w.ref, title })} onCancel=${() => c.stopRename()} />`
    : null
  return html`<section class="room-ws" style=${w.color ? { '--ws-color': w.color } : undefined}>
    ${head ?? html`<${Item} on=${on} cls="room-ws-head" title=${w.description || w.title} onClick=${firstClick(() => c.pickRoom({ kind: 'ws', id: w.key }))}
      onDblClick=${canRenameWorkspace(s, w) ? () => c.startRename('ws', w.ref) : undefined}>
      <span class="room-ws-title">${w.pinned ? html`<span class="room-pin"><span class="sr-only">${t.rooms.pinned}</span><span aria-hidden="true">${t.rooms.pinMark}</span></span>` : null}${w.title}</span>
      <${LoadChip} load=${w.load} />
      ${w.state ? html`<span class="room-meta"><${StateLine} token=${stateToken(w.state)} word=${t.state[w.state] ?? w.state} /></span>` : null}
      ${w.unread ? html`<span class="room-badge mono"><span class="sr-only">${t.rooms.unread(w.unread)}</span><span aria-hidden="true">${w.unread}</span></span>` : null}
      ${w.bridge ? html`<span class="chip room-bridge">${w.bridge.name}</span>` : null}
    <//>`}
    ${w.tabs.map(tab => html`<${TabItem} key=${tab.ref} tab=${tab} on=${here.kind === 'tab' && here.id === tab.ref} s=${s} c=${c} dim=${waits.has(tab.ref)} />`)}
  </section>`
}

/** The tabs waiting for you, and those that left the list at the last poll: such a row stays one poll
 *  longer where it stood, greyed, so a click never lands on the row that slid up into its place.
 *  A poll is a new tabs.at_ms; renders in between change nothing of it. [{ tab, left }] */
function useLeaving(list, atMs) {
  const mem = useRef({ at: atMs, list, left: [] })
  const m = mem.current
  if (atMs !== m.at) {
    const now = new Set(list.map(x => x.ref))
    m.left = m.list.map((tab, i) => ({ tab, i })).filter(x => !now.has(x.tab.ref))
    m.at = atMs
    m.list = list
  }
  const out = list.map(tab => ({ tab, left: false }))
  for (const { tab, i } of m.left) out.splice(Math.min(i, out.length), 0, { tab, left: true })
  return out
}

/** One tab that waits for you, as a short entry (round 6d C2): its dot, name and how long, and one line of where it
 *  stands (logic.js waitLage: its workspace, what it asks or its last words); a state other than waiting says its
 *  word, "waits" being the group's heading. A click opens it on the right, where its question and the answers stand
 *  (they are never repeated here). A row that left, or was answered here and still shows that very question (the
 *  same words in the same stretch of its state, logic.js isAnswered), stays one poll longer, greyed with what happened */
function WaitLine({ tab, left, s, c, here }) {
  const t = T()
  const answered = s.ui?.answered?.[tab.ref] ?? null
  const done = left || isAnswered(answered, tab)
  const key = tabStateKey(tab)
  const word = done ? (answered ? t.reply.answeredWord : t.reply.movedOn) : key === 'waiting' ? null : t.state[key] ?? tab.state
  const lage = waitLage(tab)
  return html`<${Item} on=${here.kind === 'tab' && here.id === tab.ref} cls=${`room-wait${done ? ' is-left' : ''}`}
    title=${done && answered ? t.reply.answered(answered.q) : tab.ask?.text || tab.last || tab.name} onClick=${() => c.pickRoom({ kind: 'tab', id: tab.ref })}>
    <${Dot} token=${stateToken(key)} pulse=${tab.state === 'working'} />
    <span class="room-name">${tab.name}</span>
    ${word ? html`<span class="room-meta muted small" data-word=${done ? 'done' : key}>${word}</span>` : null}
    <span class="room-meta muted small mono">${duration(s.now - (tab.since_ms || s.now))}</span>
    ${lage ? html`<span class="room-lage muted small">${lage}</span>` : null}
  <//>`
}

/** "Waiting for you" near the top of the sidebar, over the questions: the tabs that want attention (logic.js attentionTabs). While
 *  the pointer or the focus is in it, its rows keep the order last shown and a tab that starts asking goes
 *  last: sorted, a new tab would push every row down, and a click meant for one row would land on another
 *  tab. The sorted order comes back when the pointer leaves */
function WaitingGroup({ s, c, here }) {
  const t = T()
  const order = useHeldOrder(attentionTabs(s.tabs?.tabs), 'urgency', tab => tab.ref)
  const rows = useLeaving(order.list, s.tabs?.at_ms ?? 0)
  if (!rows.length) return null
  return html`<section class="reply-group" aria-label=${t.reply.asks}
    onPointerEnter=${order.hold} onPointerLeave=${order.release} onFocusIn=${order.hold}
    onFocusOut=${e => { if (!e.currentTarget.contains(e.relatedTarget)) order.release() }}>
    <h3 class="label-caps room-group">${t.reply.asks}</h3>
    ${rows.map(({ tab, left }) => html`<${WaitLine} key=${tab.ref} tab=${tab} left=${left} s=${s} c=${c} here=${here} />`)}
  </section>`
}

/** The rooms in the order last shown while the pointer or the focus is in the sidebar: a row never moves
 *  away under the hand. Only the order holds; counts and states follow at once. A new room goes last.
 *  A change of the sort mode is the one reorder the hand asked for (its toggle sits in the sidebar), so it
 *  applies at once and the new order holds from there */
function useHeldOrder(list, mode, keyOf = w => w.key) {
  const held = useRef(false)
  const shown = useRef(null)
  const lastMode = useRef(mode)
  const [, redraw] = useState(0)
  const asked = lastMode.current !== mode
  lastMode.current = mode
  let out = list
  if (held.current && shown.current && !asked) {
    const at = new Map(shown.current.map((k, i) => [k, i]))
    out = list.slice().sort((a, b) => (at.get(keyOf(a)) ?? Infinity) - (at.get(keyOf(b)) ?? Infinity))
  }
  shown.current = out.map(keyOf)
  const hold = () => { held.current = true }
  const release = () => { if (held.current) { held.current = false; redraw(n => n + 1) } }
  return { list: out, hold, release }
}

/** The tabs by status (logic.js statusQueue), each row with its workspace, so you walk them top to bottom:
 *  answer or close what needs you or waits, then the rest (Work through and the tab's bar walk them). Below stands the control
 *  session, which has no status of that kind (the questions stand on top of the sidebar). A tab that changes its status starts its time again, so it goes last in its new group and
 *  the rows above it stay where they were */
function StatusGroups({ s, c, here }) {
  const t = T()
  const groups = statusQueue(s.tabs?.tabs)
  const control = (s.tabs?.tabs ?? []).find(x => x.is_control)
  return html`<div class="room-status-list">
    ${groups.map(g => html`<section class="room-status" key=${g.state}>
      <h3 class="label-caps room-group"><${StateLine} token=${stateToken(g.state)} word=${t.rooms.status[g.state]} /> <span class="mono muted">${g.tabs.length}</span></h3>
      ${g.tabs.map(tab => html`<${TabItem} key=${tab.ref} tab=${tab} on=${here.kind === 'tab' && here.id === tab.ref} s=${s} c=${c} where />`)}
    </section>`)}
    ${!groups.length ? html`<${Empty}>${t.tabsEmpty}<//>` : null}
    ${control ? html`<section class="room-ws">
      <${TabItem} tab=${control} on=${here.kind === 'tab' && here.id === control.ref} s=${s} c=${c} />
    </section>` : null}
  </div>`
}

/** Work through: opens the first tab that wants you, in the order By status lists them, and starts the
 *  walk the open tab's bar goes on with (TabWalk); nothing when no tab wants you */
function WalkStart({ s, c }) {
  const t = T()
  const n = walkRefs(s.tabs?.tabs).length
  return n ? html`<${Btn} size="xs" variant="primary" icon="forward" title=${t.rooms.walkTitle} onClick=${() => c.startWalk()}>${t.rooms.walk(n)}<//>` : null
}

/** The foot of an open tab: the same bar the lists have under a detail (detail.js NextUp), over the tabs
 *  that want you (logic.js tabWalkView): back, where you stand, the next tab with Next (key n), the two
 *  after it as links. A tab outside the walk (one that works) shows only the first that wants you */
function TabWalk({ s, c, tab }) {
  const t = T()
  const tabs = s.tabs?.tabs
  const v = tabWalkView(tabs, s.ui.tabWalk, tab.ref)
  const first = v ? null : walkRefs(tabs).find(r => r !== tab.ref)
  const ahead = v ? v.next : first ? [{ key: first, ...tabFacts(tabs, first) }] : []
  const [next, ...later] = ahead
  const go = useRef(null)
  // Next keeps the focus on Next, so Enter goes on to the one after (as in the lists)
  useEffect(() => { if (s.ui.walkFocus) { go.current?.querySelector?.('button')?.focus?.(); c.walkFocused() } }, [tab.ref])
  if (!v && !next) return null
  const open = e => () => c.walkTab(e.key, { focus: true })
  return html`<${WalkBar} label=${t.rooms.walkLabel} shortcuts=${s.ui.shortcuts} pos=${v ? [v.pos, v.total] : null}
    onPrev=${v?.prev ? open(v.prev) : null} goRef=${go} done=${t.rooms.walkDone}
    next=${next ? { key: next.key, title: next.title ?? next.key, sub: next.workspace, onOpen: open(next) } : null}
    later=${later.map(e => ({ key: e.key, title: `${e.title ?? e.key}${e.workspace ? ` · ${e.workspace}` : ''}`, onOpen: open(e) }))} />`
}

const tabFacts = (tabs, ref) => {
  const tab = (tabs ?? []).find(x => x.ref === ref)
  return { title: tab?.name ?? null, workspace: tab?.workspace ?? null }
}

/** The sidebar of the Work area: the order of the tabs on top, where it is reached without scrolling past
 *  the tabs; then Waiting for you as short lines (left out by status, whose first groups hold the same tabs), the
 *  questions as a group of their own right under it in every order (round 6d C1, with the way to a new one in its
 *  head), the workspaces or the status groups, and the Bridges on this machine. The A2A agents have an area of
 *  their own */
export function Sidebar({ s, c, rooms, here }) {
  const t = T()
  const sort = ['urgency', 'status'].includes(s.ui?.roomsSort) ? s.ui.roomsSort : 'terminal'
  const order = useHeldOrder(rooms.workspaces, sort === 'urgency' ? 'urgency' : 'terminal')
  // the tabs Waiting for you lists: in their workspace a grey line only
  const waits = new Set(sort === 'status' ? [] : attentionTabs(s.tabs?.tabs).filter(wantsYou).map(x => x.ref))
  return html`<nav class="panel rooms-side" aria-label=${t.rooms.side}
    onPointerEnter=${order.hold} onPointerLeave=${order.release} onFocusIn=${order.hold}
    onFocusOut=${e => { if (!e.currentTarget.contains(e.relatedTarget)) order.release() }}>
    <div class="room-order">
      <${Segmented} label=${t.rooms.sortLabel} current=${sort} onPick=${v => c.setRoomsSort(v)}
        values=${[['terminal', t.rooms.sortTerminal], ['urgency', t.rooms.sortUrgency], ['status', t.rooms.sortStatus]]} />
      <${WalkStart} s=${s} c=${c} />
    </div>
    ${sort === 'status' ? null : html`<${WaitingGroup} s=${s} c=${c} here=${here} />`}
    <section class="room-ws room-asks"><div class="room-group-head"><h3 class="label-caps room-group">${t.rooms.chats}</h3>
        <button type="button" class="btn-link small room-new" aria-current=${here.kind === 'chat' && !s.ui.quickConv ? 'true' : undefined}
          onClick=${() => { c.newQuick(); c.pickRoom({ kind: 'chat' }) }}>+ ${t.rooms.newAsk}</button></div>
      <${Chats} convs=${listedChats(s.quick?.convs, s.quick?.keep_hours, s.now)} s=${s} c=${c} here=${here} /></section>
    <div class="room-group-head">
      <h3 class="label-caps room-group">${t.rooms.workspaces}</h3>
      ${canTab(s, 'rename') ? html`<${Btn} size="xs" variant="ghost" title=${t.organize.buttonTitle} busy=${!!s.ui?.organize?.busy}
        onClick=${() => c.organizePropose()}>${t.organize.button}<//>` : null}
    </div>
    ${s.tabs?.workspaces == null ? html`<p class="muted small">${t.rooms.noList}</p>` : null}
    ${sort === 'status' ? html`<${StatusGroups} s=${s} c=${c} here=${here} />`
      : order.list.length ? order.list.map(w => html`<${WorkspaceGroup} key=${w.key} w=${w} s=${s} c=${c} here=${here} waits=${waits} />`)
      : html`<${Empty}>${t.tabsEmpty}<//>`}
    ${rooms.bridges.length ? html`<h3 class="label-caps room-group">${t.rooms.bridges}</h3>
      ${rooms.bridges.map(b => html`<${Item} key=${b.id} on=${here.kind === 'bridge' && here.id === b.id} title=${b.purpose}
        onClick=${() => c.pickRoom({ kind: 'bridge', id: b.id })}><span class="room-name">${b.name}</span>
        <span class="room-meta muted small mono">${b.branch ?? ''}</span><//>`)}` : null}
  </nav>`
}

/** One tab in a field: its terminal, live, always in view, the keyboard goes to it (TermScreen); what it asks stands
 *  at the terminal's edge (AnswerBar); "Write" opens the tab window with its box. `i` is its field, `split` says
 *  there are others */
function TabPane({ s, c, tab, i = 0, split = false }) {
  const t = T()
  // while the tab's window is open it reads the terminal itself: one reader at a time
  const { screen, err, poke } = useTabScreen(c, s.ui.tabView ? null : tab.ref)
  const typeHere = useRef(null)
  // by state on purpose: a tab gone idle (finished) can still be answered
  const replying = (tab.state === 'needs-you' || tab.state === 'waiting') && !tab.is_control
  // alone in the page an answer that reached the tab, or its close, ends this tab's turn: the walk goes on to the
  // next, as settling an entry does in the lists. A jump to the terminal is no answer. Beside others it stays
  const onward = () => { if (split) return; const n = tabWalkView(s.tabs?.tabs, s.ui.tabWalk, tab.ref, 0)?.next[0]?.key ?? walkRefs(s.tabs?.tabs).find(r => r !== tab.ref); if (n) c.walkTab(n) }
  const cc = { ...c, reply: async (verb, args) => {
    const r = await c.reply(verb, args)
    if (r?.ok && verb !== 'tab_jump') onward()
    return r
  } }
  // the task it works on, opened in the drawer over the Chat (round 6), and what it came from when that is anything
  // else (round 6d C5): a question, a job, an inbox item, another task
  const slug = taskOfTab(s, tab)
  const from = shownOrigin(s, tab, slug)
  const taskTitle = slug ? indexRows(s.model).get(`task:${slug}`)?.title ?? slug : null
  return html`<section class="panel chat-main rooms-main" aria-labelledby=${i ? `room-title-${i}` : 'room-title'}>
    <header class="tabview-head">
      <${FieldGrip} i=${i} on=${split} />
      <${StateLine} token=${stateToken(tabStateKey(tab))} strong=${tab.state === 'needs-you'} word=${t.state[tabStateKey(tab)] ?? tab.state} />
      <h2 class="sec-title tabview-title" id=${i ? `room-title-${i}` : 'room-title'} title=${taskTab(tab) && !tab.is_control ? t.rooms.taskName : tab.is_control ? undefined : tab.name}>
        ${tab.is_control ? t.controlSession : tab.name}</h2>
      ${canRename(s, tab) ? html`<${Btn} size="xs" variant="ghost" icon="pencil" label=${t.rooms.rename} title=${t.rooms.rename}
        onClick=${() => c.startRename('tab', tab.ref)} />` : null}
      <span class="muted small field-wsname">${tab.workspace}</span>
      ${slug ? html`<button type="button" class="btn-link small room-task" title=${t.infoOpenTask}
        onClick=${() => c.openItem(`task:${slug}`, { task: slug, title: taskTitle })}>${t.sessionTask(short(taskTitle, 60))}</button>` : null}
      ${from ? html`<button type="button" class="btn-link small room-from-link" data-from=${from.kind} title=${t.rooms.fromTitle}
        onClick=${() => openOrigin(s, c, from)}>${t.rooms.from(short(from.title, 60))}</button>` : null}
      <span class=${`tabview-live muted small${screen && !err ? ' is-live' : ''}`} aria-live="off">${err ? html`<${StateLine} token="danger" word=${t.tabViewFailed(err)} />`
        : screen ? t.tabViewLive : t.loading}</span>
      <span class="room-head-acts">
        <${Btn} size="xs" variant="secondary" pressed=${(s.ui.fields?.panes ?? []).some(isTopic)} title=${t.fields.chatTopicTitle} onClick=${() => c.fieldTopic()}>${t.fields.topic}<//>
        <${Btn} size="xs" variant="primary" icon="send" title=${t.rooms.writeTitle} onClick=${() => c.openTabView(tab.ref)}>${t.rooms.write}<//>
        <${TabClose} tab=${tab} s=${s} c=${c} looking onClosed=${onward} />
        <${FieldClose} i=${i} c=${c} on=${split} />
      </span>
    </header>
    <${TermScreen} tabRef=${tab.ref} screen=${screen} live=${!!screen && !err} empty=${screen ? t.tabViewEmpty : t.loading}
      canType=${canTab(s, 'keys')} c=${c} poke=${poke} focusRef=${typeHere} />
    ${replying ? html`<${AnswerBar} key=${tab.ask?.hash ?? tab.ref} tab=${tab} s=${s} c=${cc} onOwn=${() => typeHere.current?.()} onTopic=${() => c.fieldTopic()} />` : null}
  </section>`
}

function ChatPane({ s, c }) {
  const t = T()
  const q = s.quick ?? {}
  const live = (q.convs ?? []).find(x => x.id === s.ui.quickConv) ?? null
  // one picked from the archive under "all" reads as it was, without a box to go on in
  const archived = live ? null : (s.chatArchive?.convs ?? []).find(x => x.id === s.ui.quickConv) ?? null
  const conv = live ?? archived
  const body = useStickToEnd(conv, useQuickLive(conv?.id))
  return html`<section class="panel chat-main rooms-main" aria-label=${t.askTitle}>
    <header class="tabview-head"><h2 class="sec-title tabview-title">${conv ? askList([conv], s, language())[0].title : t.rooms.newAsk}</h2>
      ${archived ? html`<${AskMark} archived />` : null}
      <span class="muted small">${t.rooms.chatHint}</span></header>
    <div class="tabview-body quick-body" ref=${body} tabindex="-1" role="log" aria-label=${t.quickHistory}>
      ${q.config_error || !q.available ? html`<p><${StateLine} token="warning" word=${q.config_error ?? t.quickUnavailable} /></p>` : null}
      ${!conv ? html`<${ChatIntro} q=${q} />` : html`<${ChatThread} s=${s} c=${c} conv=${conv} />`}
    </div>
    ${archived ? null : html`<${ChatFoot} key=${conv?.id ?? 'new'} s=${s} c=${c} conv=${conv} autofocus=${false} />`}
  </section>`
}

function WorkspacePane({ s, c, w }) {
  const t = T()
  const facts = [[t.rooms.fact.folder, w.cwd], [t.rooms.fact.branch, w.branch ? `${w.branch}${w.dirty ? ' *' : ''}` : null],
    [t.rooms.fact.pr, w.pr], [t.rooms.fact.bridge, w.bridge?.name], [t.rooms.fact.last, w.latest?.text]].filter(([, v]) => v)
  return html`<section class="panel chat-main rooms-main room-ws-pane" style=${w.color ? { '--ws-color': w.color } : undefined} aria-labelledby="room-title">
    <header class="tabview-head"><h2 class="sec-title tabview-title" id="room-title">${w.title}</h2>
      ${canRenameWorkspace(s, w) ? html`<${Btn} size="xs" variant="ghost" icon="pencil" label=${t.rooms.rename} title=${t.rooms.rename}
        onClick=${() => c.startRename('ws', w.ref)} />` : null}
      ${w.description ? html`<span class="muted small">${w.description}</span>` : null}</header>
    <div class="tabview-body">
      ${facts.length ? html`<dl class="agent-facts">${facts.map(([k, v]) => html`<div key=${k}><dt>${k}</dt><dd class="mono">${v}</dd></div>`)}</dl>` : null}
      ${(w.statuses ?? []).length ? html`<p class="small">${w.statuses.map(x => html`<span key=${x.name} class="chip">${x.text}</span> `)}</p>` : null}
      ${w.tabs.length ? html`<ul class="room-list">${w.tabs.map(tab => html`<li key=${tab.ref}><button type="button" class="btn-link"
        onClick=${() => c.pickRoom({ kind: 'tab', id: tab.ref })}>${tab.name}</button>
        <span class="muted small"> ${t.state[tabStateKey(tab)] ?? tab.state}</span></li>`)}</ul>` : html`<${Empty}>${t.rooms.noTabs}<//>`}
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

/** Above the sidebar: Work (the workspaces, tabs and chats) or A2A (the agents, with how many and what
 *  they signal, agents.js agentBadge). Only where this Bridge knows a peer */
function AreaSwitch({ s, c, area }) {
  const t = T()
  const peers = s.agents?.peers ?? []
  if (!peers.length) return null
  return html`<div class="rooms-area">
    <${Segmented} label=${t.chatArea.label} u="chat" current=${area} onPick=${v => c.setChatArea(v)}
      values=${[['work', t.chatArea.work], ['a2a', html`${t.chatArea.a2a(peers.length)}<${AgentMark} kind=${agentBadge(s)} />`]]} />
  </div>`
}

export function RoomsPage({ s, c }) {
  const t = T()
  const rooms = roomsOf(s)
  const here = pickedRoom(s)
  const area = chatAreaOf(s)
  useEffect(() => { c.loadAgents() }, [])
  // nothing kept and nothing picked: the Chat picks once, as soon as the questions and the tabs are read (round 6d
  // C3, logic.js chatLanding); after that it never switches on its own
  const landed = useRef(false)
  const ready = !!s.quick && Array.isArray(s.tabs?.tabs)
  useEffect(() => {
    if (landed.current || !ready) return
    landed.current = true
    const go = chatLanding(s, language())
    if (!go) return
    if (go.conv) c.pickQuick(go.conv)
    c.pickRoom(go.room)
  }, [ready])
  if (area === 'a2a') {
    return html`<div class="col col-page roomspage term">
      <div class="rooms-grid">
        <div class="rooms-left"><${AreaSwitch} s=${s} c=${c} area=${area} /><${AgentList} s=${s} c=${c} /></div>
        <section class="panel chat-main rooms-main rooms-agent"><${AgentsPage} s=${s} c=${c} embedded /></section>
      </div>
    </div>`
  }
  let pane = null
  if (here.kind === 'tab') {
    const tabs = s.tabs?.tabs ?? []
    const tab = tabs.find(x => x.ref === here.id)
    const f = fieldsOf(s.ui.fields, here.id)
    const split = f.panes.length > 1
    const field = (p, i) => {
      if (isTopic(p)) return html`<${TopicPane} p=${p} i=${i} s=${s} c=${c} split=${split} tab=${tabs.find(x => x.ref === (p.follow ? here.id : p.tab)) ?? null} />`
      if (!p) return html`<${EmptyField} i=${i} c=${c} />`
      const open = tabs.find(x => x.ref === p)
      return open ? html`<${TabPane} s=${s} c=${c} tab=${open} i=${i} split=${split} />`
        : html`<section class="panel chat-main rooms-main"><${Empty}>${t.rooms.gone}<//><${FieldClose} i=${i} c=${c} on=${split} /></section>`
    }
    pane = html`<section class="fields-wrap">
      <${FieldBar} s=${s} c=${c} f=${f} tab=${tab} />
      <${FieldGrid} f=${f} c=${c} render=${field} />
      ${tab ? html`<div class="fields-walk"><${TabWalk} s=${s} c=${c} tab=${tab} /></div>` : null}
    </section>`
  } else if (here.kind === 'ws') {
    const w = rooms.workspaces.find(x => x.key === here.id)
    pane = w ? html`<${WorkspacePane} s=${s} c=${c} w=${w} />` : null
  } else if (here.kind === 'bridge') {
    const b = (s.rooms?.bridges ?? []).find(x => x.id === here.id)
    pane = b ? html`<${BridgePane} c=${c} b=${b} />` : null
  }
  pane = pane ?? html`<${ChatPane} s=${s} c=${c} />`
  return html`<div class=${`col col-page roomspage term${s.ui.fieldsFull && here.kind === 'tab' ? ' is-full' : ''}`}>
    <${ControlNotice} s=${s} c=${c} />
    <${TabWarnings} s=${s} />
    <div class="rooms-grid">
      <div class="rooms-left"><${AreaSwitch} s=${s} c=${c} area=${area} /><${Sidebar} s=${s} c=${c} rooms=${rooms} here=${here} /></div>
      ${pane}
    </div>
  </div>`
}
