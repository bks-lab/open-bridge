// SPDX-License-Identifier: MIT
// The cockpit, the pages: which tab stands where, and the fixed page ids.
// The rules every component keeps stand at the head of components.js.

import { listedChats, reviewHome, walkRefs, workPageOf, workViewOf } from '../logic.js'
import { T } from '../text.js'

// the Jev page's id; components.js loads the page itself only when Jev is switched on
export const JEV_PAGE = '@jev'
export const ASK_MAX = 4000
export const TAB_MSG_MAX = 2000     // the 'text' check of SPECIAL_KINDS in actions.py (tab_send in actions_tabs.py)
export const CHECK_PAGE = '@check'      // the task check's own page; profile pages never start with @
export const SESSIONS_PAGE = '@sessions'
export const WORKERS_PAGE = '@workers'
export const CHAT_PAGE = '@chat'
export const AGENTS_PAGE = '@agents'
export const START_PAGE = '@start'     // the start screen: greeting, projects, cards that lead into the work
export const SETTINGS_PAGE = '@settings'   // the cockpit's own settings, always there, always behind More

/** Whether the Chat is laid out as cmux (cockpit.chat_layout: workspaces): the agents then live in it, not on a page */
export const chatAsWorkspaces = s => s?.rooms?.layout === 'workspaces'

/** The area the Chat as cmux shows: Work (the workspaces, tabs and chats) or A2A (the agents). A2A only where
 *  a peer exists; a stored choice without one, or in the classic layout, shows Work */
export function chatAreaOf(s) {
  return chatAsWorkspaces(s) && s.ui?.chatArea === 'a2a' && (s.agents?.peers ?? []).length ? 'a2a' : 'work'
}

/** The A2A area as a patch of ui where the Chat can show it (the workspaces layout, a peer), else none: a
 *  choice it cannot show is not kept, or a peer that turns up later would open the Chat on A2A unasked */
export function a2aArea(s) {
  return chatAsWorkspaces(s) && (s.agents?.peers ?? []).length ? { chatArea: 'a2a' } : {}
}

/** Where a way to an agent leads (a conversation, a card on the start page, the band, a stored page): the
 *  A2A area of the Chat in the workspaces layout, else the Agents page. The patch of ui it sets */
export function agentsLanding(s) {
  return chatAsWorkspaces(s) ? { page: CHAT_PAGE, ...a2aArea(s) } : { page: AGENTS_PAGE }
}

/** The controller's actions of the Chat's areas and of the ways to an agent, on a store: get() the state,
 *  setUi(patch), save(key, value) for this browser, now() the clock. app.js spreads them into ctl; they
 *  stand here so a test drives them on a small store of its own */
export function chatAreaActions({ get, setUi, save, now = () => Date.now() }) {
  // a patch that changes the area keeps it in this browser too
  const apply = patch => {
    if (patch.chatArea && patch.chatArea !== get().ui?.chatArea) save('bridge-cockpit.chatArea', patch.chatArea)
    setUi(patch)
  }
  // a room of the work (a tab, a workspace, a Bridge, a chat) shows on the Work area: an A2A area left
  // open in this browser would hide it
  const room = (r, more = {}) => apply({ room: r, ...more, chatArea: 'work' })
  return {
    // the area the Chat as cmux shows: its work or the A2A agents
    setChatArea: area => apply({ chatArea: area === 'a2a' && a2aArea(get()).chatArea ? 'a2a' : 'work' }),
    // the pick of an agent (a card, a row on the start page) opens its latest conversation; as cmux on the
    // Chat's A2A area, where its card stands
    pickAgent: peer => {
      const s = get()
      const latest = listedChats(s.agents?.convs, s.agents?.keep_hours, now()).filter(x => x.peer === peer)
        .sort((a, b) => (b.last_ms ?? 0) - (a.last_ms ?? 0))[0]
      apply({ agentPeer: peer, agentConv: latest?.id ?? null, ...a2aArea(s) })
    },
    // the Agents page, or as cmux the Chat on its A2A area (agentsLanding)
    openAgentConv: conv => {
      const s = get()
      const c = (s.agents?.convs ?? []).find(x => x.id === conv)
      const to = agentsLanding(s)
      save('bridge-cockpit.page', to.page)
      apply({ ...to, tabView: null, agentConv: conv, agentPeer: c?.peer ?? null })
    },
    // the page setPage opens for an id: as cmux the agents have no page, their way (the band, a card, a
    // stored page) opens the Chat on its A2A area
    pageFor: id => {
      const s = get()
      if (id !== AGENTS_PAGE || !chatAsWorkspaces(s)) return id
      const { page, ...area } = agentsLanding(s)
      if (area.chatArea) apply(area)
      return page
    },
    // the chat as cmux: what the right side shows ({ kind: 'ws' | 'tab' | 'chat' | 'bridge', id })
    pickRoom: r => room(r, r?.kind === 'tab' ? { tabWalk: walkRefs(get().tabs?.tabs) } : {}),
    // the walk through the tabs that want you, from the first of these refs (Work through, the waiting tabs)
    walkFrom: refs => { if (refs?.length) room({ kind: 'tab', id: refs[0] }, { tabWalk: refs }) },
    walkTab: (ref, { focus = false } = {}) => { if (ref) room({ kind: 'tab', id: ref }, { walkFocus: focus }) },
  }
}

/** The page the task check stands on, when inbox and tasks share one (then the check has no tab of its own) */
export function reviewHomeOf(s) {
  return reviewHome(s.model?.pages, T().workOrder.kinds)
}

/** Every page with whether it stands behind More: the fixed pages, then the profile's. The system
 *  views (Workers, Agents, Check, Jev) and profile pages with `group: more` go behind More */
function pageList(s) {
  // In front the few tabs of every day: Start, Today, Chat and the profile's main pages (Work, Operations).
  // Everything else stands behind them and folds behind More only when the bar has no room for it.
  // The Workers tab only where a worker view exists, Agents only where this Bridge knows an A2A peer and the
  // Chat is the classic one (as cmux the agents are a tab inside the Chat, chatAreaOf);
  // a page of group `day` has no tab, its sections stand under the day list of Today (DayColumn); Settings is the last of all
  return [{ id: START_PAGE }, { id: 'briefing' }, { id: CHAT_PAGE }, { id: SESSIONS_PAGE, more: true },
    ...(s.workers?.status === 'none' ? [] : [{ id: WORKERS_PAGE, more: true }]),
    ...((s.agents?.peers ?? []).length && !chatAsWorkspaces(s) ? [{ id: AGENTS_PAGE, more: true }] : []), ...(reviewHomeOf(s) ? [] : [{ id: CHECK_PAGE, more: true }]),
    ...(s.jev?.enabled && !workPageOf(s.model?.pages)?.jev ? [{ id: JEV_PAGE, more: true }] : []),
    ...(s.model?.pages ?? []).filter(p => p.group !== 'day' && p.group !== 'work').map(p => ({ id: p.id, more: p.group === 'more' })),
    { id: SETTINGS_PAGE, more: true }]
}

/** The name of the briefing's tab: the title of the work page where one folds into it, else Today */
export function briefingTitle(s) {
  return workPageOf(s.model?.pages)?.title || T().briefing
}

/** The view the briefing's tab shows: what is due, by source or by Jev (logic.js workViewOf); on any
 *  other tab what is due, so nothing there changes */
export function workViewNow(s) {
  return s.ui?.page === 'briefing' ? workViewOf(s.ui.workView, workPageOf(s.model?.pages), s.jev) : 'due'
}

/** Whether the main area shows a page rather than the day's three columns */
export const onPageOf = s => s.ui.page !== 'briefing' || workViewNow(s) !== 'due'

/** Every page in tab bar order: the tabs in front, then those behind More. Alt 1 to Alt 9 follow this order */
export function pageOrder(s) {
  const list = pageList(s)
  return [...list.filter(p => !p.more), ...list.filter(p => p.more)].map(p => p.id)
}

/** The pages behind the bar's More menu */
export function morePages(s) {
  return new Set(pageList(s).filter(p => p.more).map(p => p.id))
}
