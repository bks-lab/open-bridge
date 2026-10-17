// SPDX-License-Identifier: MIT
// The cockpit, the pages: which tab stands where, and the fixed page ids.
// The rules every component keeps stand at the head of components.js.

import { reviewHome, workPageOf, workViewOf } from '../logic.js'
import { T } from '../text.js'

// the Jev page's id; components.js loads the page itself only when Jev is switched on
export const JEV_PAGE = '@jev'
export const ASK_MAX = 4000
export const TAB_MSG_MAX = 2000     // actions.py tab_send: check_text(..., 2000)
export const CHECK_PAGE = '@check'      // the task check's own page; profile pages never start with @
export const SESSIONS_PAGE = '@sessions'
export const WORKERS_PAGE = '@workers'
export const CHAT_PAGE = '@chat'
export const AGENTS_PAGE = '@agents'
export const START_PAGE = '@start'     // the start screen: greeting, projects, cards that lead into the work
export const SETTINGS_PAGE = '@settings'   // the cockpit's own settings, always there, always behind More

/** The page the task check stands on, when inbox and tasks share one (then the check has no tab of its own) */
export function reviewHomeOf(s) {
  return reviewHome(s.model?.pages, T().workOrder.kinds)
}

/** Every page with whether it stands behind More: the fixed pages, then the profile's. The system
 *  views (Workers, Agents, Check, Jev) and profile pages with `group: more` go behind More */
function pageList(s) {
  // In front the few tabs of every day: Start, Today, Chat and the profile's main pages (Work, Operations).
  // Everything else stands behind them and folds behind More only when the bar has no room for it.
  // The Workers tab only where a worker view exists, Agents only where this Bridge knows an A2A peer;
  // a page of group `day` has no tab, its sections stand under the day list of Today (DayColumn); Settings is the last of all
  return [{ id: START_PAGE }, { id: 'briefing' }, { id: CHAT_PAGE }, { id: SESSIONS_PAGE, more: true },
    ...(s.workers?.status === 'none' ? [] : [{ id: WORKERS_PAGE, more: true }]),
    ...((s.agents?.peers ?? []).length ? [{ id: AGENTS_PAGE, more: true }] : []), ...(reviewHomeOf(s) ? [] : [{ id: CHECK_PAGE, more: true }]),
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
