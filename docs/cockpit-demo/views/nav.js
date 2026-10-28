// SPDX-License-Identifier: MIT
// The cockpit, the pages: which tab stands where, which page stands under another (a folder and its places), and the
// fixed page ids.
// The rules every component keeps stand at the head of components.js.

import { FILES_PAGE, FLOW_PAGE, checkInFlow, filesOn, jobCounts, listedChats, reviewHome, sessionsInFlow, subPageTile, walkRefs, workPageOf, workViewIn, workViewsIn } from '../logic.js'
import { T } from '../text.js'

// the Jev page's id; components.js loads the page itself only when Jev is switched on
export const JEV_PAGE = '@jev'
export const ASK_MAX = 4000
export const TAB_MSG_MAX = 2000     // the 'text' check of SPECIAL_KINDS in actions.py (tab_send in actions_tabs.py)
export const CHECK_PAGE = '@check'      // the task check's own page; profile pages never start with @
// the live sessions; where Work through lists them in Running now (logic.js sessionsInFlow) the page has no tab and
// every way to it leads there (app.js setPage)
export const SESSIONS_PAGE = '@sessions'
export const WORKERS_PAGE = '@workers'
export const CHAT_PAGE = '@chat'
export const AGENTS_PAGE = '@agents'
export const START_PAGE = '@start'     // the start screen: greeting, projects, cards that lead into the work
export const SETTINGS_PAGE = '@settings'   // the cockpit's own settings, always there, always behind More
// the id the Work through page had before it became a view of the work tab (flow.js); app.js leads it there
export { FLOW_PAGE }
// the files tab beside Work (views/dossier.js), where every link that opens a task's file leads (round 6c)
export { FILES_PAGE }

/** Whether the Chat is laid out as cmux (cockpit.chat_layout: workspaces): the agents then live in it, not on a page */
export const chatAsWorkspaces = s => s?.rooms?.layout === 'workspaces'

/** The name of the way to the live sessions, as the place it opens: Running now where Work through lists them
 *  (logic.js sessionsInFlow), else the Sessions tab */
export const sessionsName = s => (sessionsInFlow(s) ? T().flow.run.label : T().sessionsTab)

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

/** The page the task check stands on, when inbox and tasks share one (then the check has no tab of its own); the
 *  work page only while the work tab offers By source and not Work through (there the check stands, checkInFlow),
 *  else the check is a tab again */
export function reviewHomeOf(s) {
  return reviewHome(s.model?.pages, T().workOrder.kinds, workViewsIn(s))
}

/** The sub pages a page names (`under:` in the profile, `subs` from briefing_view.pages), in their order: the
 *  pages the model carries, and the Workers page where a worker view exists. A page without a tab names none */
export function subPagesOf(s, id) {
  const pages = s?.model?.pages ?? []
  const page = pages.find(p => p.id === id)
  if (!page || page.under || page.group === 'day' || page.group === 'work') return []
  return (page.subs ?? []).filter(x => (x === WORKERS_PAGE ? s.workers?.status !== 'none' : x !== id && pages.some(p => p.id === x)))
}

/** The page a sub page stands under, or null: the sub page has no tab of its own, the parent's tab stays lit while
 *  it is open, and the bar of the folder stands on both (views/header.js FolderBar). A parent the model does not
 *  carry leaves the page its own tab */
export function parentOf(s, id) {
  return (s?.model?.pages ?? []).find(p => p.id !== id && subPagesOf(s, p.id).includes(id))?.id ?? null
}

/** The folder a page belongs to: the page itself where it names sub pages, else the page it stands under, else null */
export function folderOf(s, id = s?.ui?.page) {
  return subPagesOf(s, id).length ? id : parentOf(s, id)
}

/** The places of a folder for its bar and its tab's menu: the folder page first (its overview), then its sub pages,
 *  each with a mark: `tone` for its dot and a short `note` ("3 down", "4 warnings") only where something stands out.
 *  Red with an outage or a finding, orange with warnings (logic.js subPageTile), green on a live all clear */
export function folderPlaces(s, id) {
  const t = T()
  const pages = s?.model?.pages ?? []
  const page = pages.find(p => p.id === id)
  const subs = subPagesOf(s, id)
  if (!page || !subs.length) return []
  const own = page.badge?.kind === 'bad' ? { tone: 'danger', note: t.folderFindings(page.badge.n) }
    : { tone: page.badge?.kind === 'ok' ? 'success' : 'on-surface-muted', note: null }
  return [{ id, label: t.folderOverview, ...own }, ...subs.map(x => {
    if (x === WORKERS_PAGE) {
      const j = jobCounts(s.workers?.data)
      return { id: x, label: t.workersTab, tone: j.failing ? 'danger' : j.upkeep ? 'on-surface-muted' : 'success',
        note: j.failing ? t.folderOutages(j.failing) : null, title: t.overviewWorkers(j.ok, j.all, j.failing, j.upkeep) }
    }
    const sub = pages.find(p => p.id === x)
    const tile = subPageTile(sub)
    const note = tile.error ? t.folderUnreadable : tile.tone === 'danger' ? t.folderFindings(tile.big)
      : tile.tone === 'warning' ? t.folderWarnings(tile.big) : null
    return { id: x, label: sub.title, tone: tile.tone === 'neutral' ? 'on-surface-muted' : tile.tone, note,
      title: tile.warnIn ? t.subPageWarn(tile.big, tile.warnIn) : tile.error ? t.unreadable(tile.note) : tile.note ?? undefined }
  })]
}

/** A page's badge in the bar: its own, or red with every finding of its sub pages and the outages of the Workers
 *  page under it, so their alarm still shows on the one tab left. Upkeep of the workers never colours it */
export function tabBadgeOf(s, page) {
  const subs = subPagesOf(s, page?.id)
  if (!subs.length) return page?.badge
  const pages = s.model?.pages ?? []
  const badOf = p => (p?.badge?.kind === 'bad' ? p.badge.n : 0)
  const bad = badOf(page) + subs.reduce((n, id) => n + (id === WORKERS_PAGE ? jobCounts(s.workers?.data).failing
    : badOf(pages.find(p => p.id === id))), 0)
  return bad > 0 ? { kind: 'bad', n: bad } : page.badge
}

/** The badge beside a page's title: its tab's, but a sub page's plain "ok" only on a live all clear (an alarm
 *  section that reports nothing, logic.js subPageTile): rows nothing measures live never make a page look in order */
export function headBadgeOf(s, page) {
  const badge = tabBadgeOf(s, page)
  return badge?.kind === 'ok' && parentOf(s, page?.id) && subPageTile(page).tone !== 'success' ? { kind: 'none' } : badge
}

/** Every page with whether it stands behind More: the fixed pages, then the profile's. The system
 *  views (Workers, Agents, Check, Jev) and profile pages with `group: more` go behind More */
function pageList(s) {
  // In front the few tabs of every day: Start, Today, the files right after it (filesOn: a tab of their own since
  // round 6c), Chat and the profile's main pages (Work, Operations).
  // Work through (cockpit.flow.enabled) is a view of the work tab, no tab of its own.
  // Everything else stands behind them and folds behind More only when the bar has no room for it.
  // The Workers tab only where a worker view exists, Agents only where this Bridge knows an A2A peer and the
  // Chat is the classic one (as cmux the agents are a tab inside the Chat, chatAreaOf), Sessions only where Work through
  // does not list the live sessions in its Running now (round 6, sessionsInFlow), the task check only where no page holds
  // it and Work through does not (round 6 c, checkInFlow: its row stands under Not now);
  // a page of group `day` has no tab, its sections stand under the day list of Today (DayColumn); a sub page
  // (parentOf: a profile page with `under:`, or the Workers page placed under one) has none either, the bar of
  // its folder and the menu at its parent's tab open it; Settings is the last of all
  return [{ id: START_PAGE }, { id: 'briefing' }, ...(filesOn(s) ? [{ id: FILES_PAGE }] : []), { id: CHAT_PAGE }, ...(sessionsInFlow(s) ? [] : [{ id: SESSIONS_PAGE, more: true }]),
    ...(s.workers?.status === 'none' || parentOf(s, WORKERS_PAGE) ? [] : [{ id: WORKERS_PAGE, more: true }]),
    ...((s.agents?.peers ?? []).length && !chatAsWorkspaces(s) ? [{ id: AGENTS_PAGE, more: true }] : []), ...(reviewHomeOf(s) || checkInFlow(s) ? [] : [{ id: CHECK_PAGE, more: true }]),
    ...(s.jev?.enabled && !workPageOf(s.model?.pages)?.jev ? [{ id: JEV_PAGE, more: true }] : []),
    ...(s.model?.pages ?? []).filter(p => p.group !== 'day' && p.group !== 'work' && !parentOf(s, p.id)).map(p => ({ id: p.id, more: p.group === 'more' })),
    { id: SETTINGS_PAGE, more: true }]
}

/** The name of the briefing's tab: the title of the work page where one folds into it, else Today */
export function briefingTitle(s) {
  return workPageOf(s.model?.pages)?.title || T().briefing
}

/** The view the briefing's tab shows: what is due, by source, by Jev or Work through (logic.js workViewIn; the
 *  files are a tab of their own, FILES_PAGE); on any other tab what is due, so nothing there changes */
export function workViewNow(s) {
  return s.ui?.page === 'briefing' ? workViewIn(s) : 'due'
}

/** Whether the main area shows a page rather than the day's three columns */
export const onPageOf = s => s.ui.page !== 'briefing' || workViewNow(s) !== 'due'

/** Every page in tab bar order: the tabs in front, then those behind More. Alt 1 to Alt 9 follow this order */
export function pageOrder(s) {
  const list = pageList(s)
  return [...list.filter(p => !p.more), ...list.filter(p => p.more)].map(p => p.id)
}

/** The tab that is lit while a page is open: its parent's for a sub page, else its own */
export function litTab(s) {
  return parentOf(s, s.ui?.page) ?? s.ui?.page
}

/** The pages behind the bar's More menu */
export function morePages(s) {
  return new Set(pageList(s).filter(p => p.more).map(p => p.id))
}
