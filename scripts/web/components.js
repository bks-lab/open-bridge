// SPDX-License-Identifier: MIT
// Preact + htm components of the cockpit (contract section 7).
// Rendering goes only through htm templates, so every text is escaped; nothing here
// sets raw HTML. Components read the store snapshot `s` and call the controller `c`;
// they never decide which action applies to a row, the server's model says so.
// This file holds the root (App) and the page router (PageView); every area has its own file under
// views/, which imports what it uses from the others. app.js imports from here only.

import { html, useEffect, useLayoutEffect, useState } from './vendor/htm-preact-3.1.1.module.js'
import { cardPlan, indexRows, railShown, triageKey, workKinds, workPageOf } from './logic.js'
import { T } from './text.js'
import { TriageBar } from './triage.js'
import { InnerRoom } from './inner.js'
import { AgentsPage } from './views/agents.js'
import { ChatPage, QuickChat } from './views/chat.js'
import { RoomsPage } from './views/rooms.js'
import { OrganizeView } from './views/organize.js'
import { ReviewBody, ReviewPage, ReviewStrip } from './views/check.js'
import { DayColumn, WorkSwitch } from './views/day.js'
import { DetailColumn } from './views/detail.js'
import { DossierView } from './views/dossier.js'
import { Header, PageBadge, PageBar } from './views/header.js'
import { HomePage, jumpToTab, useHomeTitle } from './views/home.js'
import {
  AGENTS_PAGE, CHAT_PAGE, CHECK_PAGE, JEV_PAGE, SESSIONS_PAGE, SETTINGS_PAGE, START_PAGE, WORKERS_PAGE, onPageOf, reviewHomeOf,
  workViewNow,
} from './views/nav.js'
import {
  AuthPanel, BootPanel, ConfirmDialog, HelpDialog, HistoryDrawer, InfoDrawer, ItemDrawer, MobileSwitch, NotesDrawer,
  TabsDrawer, Toasts,
} from './views/overlays.js'
import { JevList, KindBar, OverviewBoard, PageCard, PageSection, WorkOrder } from './views/pages.js'
import { Empty, StateLine } from './views/parts.js'
import { SessionsPage, WorkersPage } from './views/sessions.js'
import { CustomizeDrawer, SettingsPage } from './views/settings.js'
import { TabView, TabsColumn } from './views/tabs.js'
import { Tour } from './views/tour.js'
import { HintsOverlay } from './views/hints.js'
export { useHomeTitle } from './views/home.js'
export { quickLive } from './views/chat.js'
export {
  AGENTS_PAGE, CHAT_PAGE, CHECK_PAGE, JEV_PAGE, SESSIONS_PAGE, SETTINGS_PAGE, START_PAGE, WORKERS_PAGE, morePages, pageOrder,
  workViewNow,
} from './views/nav.js'

// Jev is an optional integration (integrations.typesafe): its page and stylesheet load only once it is
// switched on and has its key, so a Bridge without it never fetches them
let jevPage = null      // the loaded module, or { failed: true }

function useJevPage(enabled) {
  const [, tick] = useState(0)
  useEffect(() => {
    if (!enabled || jevPage) return
    const css = document.createElement('link')
    css.rel = 'stylesheet'
    css.href = 'jev/jev.css'
    document.head.appendChild(css)
    import('./jev/page.js').then(m => { jevPage = m }, () => { jevPage = { failed: true } }).then(() => tick(n => n + 1))
  }, [enabled])
  return jevPage
}

function PageView({ s, c }) {
  const t = T()
  const jev = useJevPage(!!(s.jev?.enabled && s.jev?.ready))
  if (s.ui.page === START_PAGE) return html`<${HomePage} s=${s} c=${c} />`
  if (s.ui.page === CHECK_PAGE) return html`<${ReviewPage} s=${s} c=${c} />`
  if (s.ui.page === SESSIONS_PAGE) return html`<${SessionsPage} s=${s} c=${c} />`
  if (s.ui.page === WORKERS_PAGE) return html`<${WorkersPage} s=${s} c=${c} />`
  if (s.ui.page === CHAT_PAGE) return s.rooms?.layout === 'workspaces' ? html`<${RoomsPage} s=${s} c=${c} />` : html`<${ChatPage} s=${s} c=${c} />`
  if (s.ui.page === SETTINGS_PAGE) return html`<${SettingsPage} s=${s} c=${c} />`
  if (s.ui.page === AGENTS_PAGE && (s.agents?.peers ?? []).length) return html`<${AgentsPage} s=${s} c=${c} />`
  const view = workViewNow(s)
  // the files view (one task at a time) needs no work page: it walks the tasks of the model
  if (view === 'dossier') return html`<${DossierView} s=${s} c=${c} />`
  const work = view === 'due' ? null : workPageOf(s.model?.pages)
  if (view === 'jev') {
    const JevWork = jev?.JevWork
    // rows only the work page holds (an idea, a debrief point) stay in the picture by their key
    const extra = (work.sections ?? []).flatMap(sec => (s.more[`${work.id}/${sec.id}`]?.items ?? sec.items ?? []).map(triageKey)).filter(Boolean)
    return JevWork ? html`<${JevWork} s=${s} c=${c} page=${work} extra=${extra} top=${html`<${WorkSwitch} s=${s} c=${c} />`} />`
      : html`<div class="col col-page"><${WorkSwitch} s=${s} c=${c} /><div class="panel panel-pad"><p class="muted">${jev?.failed ? t.jevNotReady.load_failed : t.loading}</p></div></div>`
  }
  if (s.ui.page === JEV_PAGE && s.jev?.enabled) {
    const JevPage = jev?.JevPage
    return s.jev.ready && JevPage ? html`<${JevPage} s=${s} c=${c} />` : s.jev.ready ? html`<div class="col col-page"><div class="panel panel-pad"><p class="muted">${jev?.failed ? t.jevNotReady.load_failed : t.loading}</p></div></div>` : html`<div class="col col-page">
      <header class="page-head"><h2 class="detail-title">Jev</h2></header>
      <div class="panel panel-pad"><p><${StateLine} token="warning" strong word=${t.jevNotReady[s.jev.reason] ?? s.jev.reason} /></p>
        <p class="muted small">${t.jevHowTo}</p></div></div>`
  }
  const whole = work ?? (s.model?.pages ?? []).find(p => p.id === s.ui.page)
  if (!whole) return html`<div class="col col-page"><div class="panel panel-pad"><${Empty}>${t.pageEmpty}<//></div></div>`
  // a page with inbox and task rows filters by kind; everything below sees only the chosen sections
  const kinds = workKinds(whole.sections, t.workOrder.kinds)
  const kind = kinds.find(k => k.label === s.ui.workKind) ?? null
  // the task check stands under the tasks label of the page where inbox and tasks stand together; once it
  // has run, its table takes the place of the plain task list
  const home = reviewHomeOf(s)
  const checkHere = !!kind && home?.page === whole.id && home.label === kind.label && s.ui.workView !== 'jev'
  const checked = checkHere && !!s.model?.review?.last
  const seen = new Set(checked ? s.model.review.keys ?? [] : [])
  // a task the check has seen stands in its table; the plain list keeps only the ones it has not seen yet
  const unseen = sec => {
    const items = (s.more[`${whole.id}/${sec.id}`]?.items ?? sec.items ?? []).filter(it => !it.task || !seen.has(`task:${it.task}`))
    return { ...sec, items, total: items.length, more: 0, whole: true }
  }
  const page = kind ? { ...whole, sections: whole.sections.filter(sec => kind.sections.includes(sec.id))
    .map(sec => (checked && sec.kind === 'tasks' ? unseen(sec) : sec)) } : whole
  // the live cards (costs, tokens, noise): after the section the profile names, or at the end of the page
  const cards = cardPlan(page)
  // the order by Jev stands in place of the sections, so a card placed after one moves to the end
  const jevList = !!(page.jev && !work && s.jev?.enabled && s.jev?.ready && s.ui.workView === 'jev' && s.jevOrder[page.id]?.order)
  const card = id => html`<${PageCard} key=${`@${id}`} id=${id} page=${page} s=${s} c=${c} />`
  return html`<div class="col col-page">
    <header class="page-head">
      ${work ? html`<${WorkSwitch} s=${s} c=${c} />` : html`<h2 class="detail-title">${page.title}</h2>`}
      <${PageBadge} badge=${page.badge} />
    </header>
    ${page.overview ? html`<${OverviewBoard} page=${page} s=${s} c=${c} />` : null}
    ${kinds.length > 1 ? html`<${KindBar} kinds=${kinds} active=${kind} c=${c} />` : null}
    ${page.sections?.some(sec => sec.kind === 'tasks' || sec.kind === 'inbox') ? html`<${TriageBar} s=${s} c=${c} byKey=${indexRows(s.model)}
      items=${(kind ? whole.sections.filter(sec => kind.sections.includes(sec.id)) : whole.sections)
        .filter(sec => sec.kind === 'tasks' || sec.kind === 'inbox').flatMap(sec => s.more[`${whole.id}/${sec.id}`]?.items ?? sec.items ?? [])} />` : null}
    ${checkHere ? html`<${ReviewBody} s=${s} c=${c} inline />`
      : page.sections?.some(sec => sec.kind === 'tasks' && (sec.items ?? []).some(it => it.task)) ? html`<${ReviewStrip} s=${s} c=${c} />` : null}
    ${page.jev && !work && s.jev?.enabled && s.jev?.ready ? html`<${WorkOrder} page=${page} s=${s} c=${c} />` : null}
    ${jevList ? html`<${JevList} page=${page} s=${s} c=${c} />`
      : (page.sections ?? []).length ? page.sections.flatMap(sec => [html`<${PageSection} key=${sec.id} page=${page} section=${sec} s=${s} c=${c} />`,
        ...(cards.after[sec.id] ?? []).map(card)])
      : html`<div class="panel panel-pad"><${Empty}>${t.pageEmpty}<//></div>`}
    ${(jevList ? [...Object.values(cards.after).flat(), ...cards.end] : cards.end).map(card)}
  </div>`
}

// ---------------------------------------------------------------- root

export function App({ store, ctl }) {
  const [s, setS] = useState(store.get())
  useLayoutEffect(() => {
    // subscribe, then catch up with whatever changed between the first render and now
    const off = store.subscribe(setS)
    setS(store.get())
    return off
  }, [])
  ctl.setAskFallback = v => store.set(x => ({ ...x, ui: { ...x.ui, askFallback: v } }))
  useHomeTitle(s)
  if (s.boot.status === 'unauthorized') return html`<${AuthPanel} />`
  if (s.boot.status !== 'ok') return html`<${BootPanel} s=${s} c=${ctl} />`
  const byKey = indexRows(s.model)
  const onPage = onPageOf(s)
  const layout = s.layout
  const peek = onPage && s.ui.pageDetail && !!s.ui.selectedKey
  const pane = onPage && !peek && s.ui.pane === 'detail' ? 'day' : s.ui.pane
  // a wide page that shows sessions itself or needs the width folds the tab column to its header button
  const rail = layout === 'wide' && railShown(s.ui.page, s.rooms?.layout, s.ui.railHidden)
  const tabsDrawer = layout === 'medium' || (layout === 'wide' && !rail)
  const showTabsCol = rail || (layout === 'narrow' && pane === 'tabs')
  const main = onPage
    ? html`<${PageView} s=${s} c=${ctl} />${peek ? html`<${DetailColumn} s=${s} c=${ctl} byKey=${byKey} />` : null}`
    : html`<${DayColumn} s=${s} c=${ctl} byKey=${byKey} /><${DetailColumn} s=${s} c=${ctl} byKey=${byKey} />`
  // the page tabs keep their own row on every width: in the header of a wide screen they shared the room
  // with the tools, and the widest screen showed the fewest tabs
  return html`<div class="shell">
    <a class="skip" href="#main">${T().skip}</a>
    <${Header} s=${s} c=${ctl} />
    <${PageBar} s=${s} c=${ctl} />
    ${layout === 'narrow' ? html`<${MobileSwitch} s=${s} c=${ctl} />` : null}
    <main id="main" class=${`main layout-${layout}${onPage ? ' on-page' : ''}${peek ? ' with-detail' : ''}${layout === 'wide' && !rail ? ' no-rail' : ''}${s.ui.selectedKey ? '' : ' no-pick'}`} data-pane=${pane}>
      ${main}
      ${showTabsCol ? html`<${TabsColumn} s=${s} c=${ctl} byKey=${byKey} />` : null}
    </main>
    ${tabsDrawer && s.ui.drawer === 'tabs' ? html`<${TabsDrawer} s=${s} c=${ctl} byKey=${byKey} />` : null}
    ${s.ui.drawer === 'notes' ? html`<${NotesDrawer} s=${s} c=${ctl} />` : null}
    ${s.ui.drawer === 'customize' ? html`<${CustomizeDrawer} s=${s} c=${ctl} />` : null}
    ${s.ui.drawer === 'history' ? html`<${HistoryDrawer} s=${s} c=${ctl} />` : null}
    ${s.ui.drawer === 'help' ? html`<${HelpDialog} s=${s} c=${ctl} />` : null}
    ${s.ui.drawer === 'item' && s.ui.item ? html`<${ItemDrawer} s=${s} c=${ctl} byKey=${byKey} />` : null}
    ${s.ui.drawer === 'info' && s.ui.info ? html`<${InfoDrawer} s=${s} c=${ctl} />` : null}
    ${s.ui.tabView === '@ask' ? html`<${QuickChat} s=${s} c=${ctl} />` : s.ui.tabView ? html`<${TabView} s=${s} c=${ctl} />` : null}
    ${s.ui.inner ? html`<${InnerRoom} s=${s} c=${ctl} focus=${s.ui.innerFocus} onClose=${ctl.closeInner}
      onTab=${ref => { ctl.closeInner(); jumpToTab(s, ctl, ref) }} />` : null}
    ${s.ui.organize ? html`<${OrganizeView} s=${s} c=${ctl} />` : null}
    <${ConfirmDialog} s=${s} c=${ctl} />
    <${Toasts} s=${s} c=${ctl} />
    <${HintsOverlay} s=${s} c=${ctl} />
    <${Tour} s=${s} c=${ctl} />
  </div>`
}
