// SPDX-License-Identifier: MIT
// Pure helpers of the cockpit's areas: the start page's area lines, where a number of them leads, the one
// area filter (ui.area) and the state a page sees under it. No DOM, no network, no state. logic.js passes
// every name on, so a view may import it from either; the frontend test imports this file under node.
import { asksYou, dueWhen, homeChosen, homeView, indexRows, wantsYou } from './logic.js'
import { scopedFileQueue } from './files.js'

/** The project a row belongs to: its area, else its first area name, else the label of its mark */
export function rowProject(row) {
  return row?.area || row?.area_names?.[0] || row?.mark?.label || ''
}

/** The project chips of the start page: the workspaces of the agent tabs and the projects of the rows,
 *  the most frequent first (ties by name), each name once whatever its case; the spelling seen first wins,
 *  tabs before rows. The control tab and nameless entries count for nothing */
export function homeProjects(tabs, rows) {
  const seen = new Map()
  const add = name => {
    const key = String(name ?? '').trim().toLowerCase()
    if (!key) return
    const x = seen.get(key) ?? { name: String(name).trim(), n: 0 }
    x.n += 1
    seen.set(key, x)
  }
  for (const t of tabs ?? []) if (!t.is_control) add(t.workspace)
  for (const r of rows ?? []) add(rowProject(r))
  return [...seen.values()].sort((a, b) => b.n - a.n || a.name.localeCompare(b.name)).map(x => x.name)
}

/** Does a tab or a row belong to the chosen project? No project chosen: everything does */
export function inProject(x, project) {
  if (!project) return true
  const want = String(project).trim().toLowerCase()
  const names = [x?.workspace, x?.area, ...(x?.area_names ?? []), x?.mark?.label]
  return names.some(n => n && String(n).trim().toLowerCase() === want)
}

const PROJECT_TONES = ['secondary', 'accent', 'success', 'warning', 'info']

/** A project's tone for its card band: the same name always the same DESIGN.md token, whatever its case */
export function projectTone(name) {
  let h = 0
  for (const ch of String(name ?? '').toLowerCase()) h = (h * 31 + ch.codePointAt(0)) >>> 0
  return PROJECT_TONES[h % PROJECT_TONES.length]
}

/** Is a row past its date? `due_at` or `due`, a day (YYYY-MM-DD, the server's form) or milliseconds;
 *  due today is not overdue */
function rowOverdue(row, nowMs) {
  const due = row?.due_at ?? row?.due
  if (typeof due === 'number') return due < nowMs
  return dueWhen(due, nowMs)?.kind === 'overdue'
}

/** The areas of the start page, each with what it holds for you: rows of "now" and tabs that wait on you,
 *  tabs at work, tabs that went idle and answered starts to review, rows past their date, and the open
 *  tasks (`tasks`, not in `total`: it keeps an area there to pick when nothing else is). Names and order as
 *  the project chips have them (homeProjects); an area with no number at all drops out. The control tab
 *  and bare shells count for nothing, and each thing counts once: a row in several sections, a row of
 *  "now" and the tab waiting on its work (as model.tab_for pairs them), an answered start and its idle tab */
export function homeAreas(tabs, sections, returns, nowMs) {
  const live = (tabs ?? []).filter(t => !t.is_control && t.state !== 'shell')
  const byKey = new Map()
  for (const sec of sections ?? []) for (const r of sec.rows ?? []) if (!byKey.has(r.key)) byKey.set(r.key, r)
  const rows = [...byKey.values()]
  const section = id => (sections ?? []).find(x => x.id === id)?.rows ?? []
  const counts = new Map()
  const zero = () => ({ waiting: 0, waitingTabs: 0, waitingRows: 0, running: 0, review: 0, overdue: 0, tasks: 0 })
  // what has no area counts under NONE, the line "No area" at the end
  const bump = (name, what) => {
    const key = String(name ?? '').trim().toLowerCase() || NONE
    const x = counts.get(key) ?? zero()
    x[what] += 1
    counts.set(key, x)
  }
  // a row of "now" that asks you stands for the tab that waits on its work; an idea or a report there asks nothing
  const paired = new Set()
  for (const r of section('now').filter(asksYou)) {
    bump(rowProject(r), 'waiting')
    bump(rowProject(r), 'waitingRows')
    for (const t of live) if ((r.task && t.slug === r.task) || (r.inbox_id && t.item === r.inbox_id)) paired.add(t.ref)
  }
  // an answered start stands for its tab gone idle
  const answered = new Set()
  for (const r of returns ?? []) {
    const row = byKey.get(r.key)
    if (!row || (r.live ?? r.stage) !== 'result') continue
    bump(rowProject(row), 'review')
    for (const t of live) if (t.ref === r.tab?.ref || (r.item && (t.slug === r.item || t.item === r.item))) answered.add(t.ref)
  }
  for (const t of live) {
    // one rule for the number and its jump: the tab wants you (wantsYou), and no row of "now" stands for it
    if (wantsYou(t) && !paired.has(t.ref)) {
      bump(t.workspace, 'waiting')
      bump(t.workspace, 'waitingTabs')
    }
    if (t.state === 'working') bump(t.workspace, 'running')
    if (t.idle === true && !answered.has(t.ref)) bump(t.workspace, 'review')
  }
  for (const r of rows) if (rowOverdue(r, nowMs)) bump(rowProject(r), 'overdue')
  const slugs = new Set()
  for (const r of section('work')) {
    if (!r.task || slugs.has(r.task)) continue
    slugs.add(r.task)
    bump(rowProject(r), 'tasks')
  }
  const line = (name, x, extra = {}) => ({ name, tone: projectTone(name), ...x, total: x.waiting + x.running + x.review + x.overdue, ...extra })
  const out = homeProjects(tabs, rows).map(name => line(name, counts.get(name.toLowerCase()) ?? zero()))
  if (counts.has(NONE)) out.push(line('', counts.get(NONE), { none: true, tone: 'muted' }))
  return out.filter(a => a.total > 0 || a.tasks > 0)
}

const NONE = '\u0000none'   // no area name can be this

/** Where a number of the areas leads, the area as the filter there (ui.area): tabs alone that want you
 *  are answered in the chat, one after the other (its walk); rows, or rows and tabs, wait in Work, what is due first, as do
 *  overdue rows; what runs and what is to review are the sessions and the starts of the Sessions page;
 *  the tasks open Work in the view it was left in, the area's name the files view */
export function areaJump(kind, area) {
  if (kind === 'waiting') return area?.waitingTabs && !area.waitingRows ? { page: '@chat', walk: true } : { page: 'briefing', view: 'due' }
  if (kind === 'running' || kind === 'review') return { page: '@sessions' }
  if (kind === 'overdue') return { page: 'briefing', view: 'due' }
  // the area's name opens its files (one task at a time; the files view stands on every Bridge)
  if (kind === 'name') return { page: 'briefing', view: 'dossier' }
  return { page: 'briefing' }
}

// the pages the area filter (ui.area) acts on
export const AREA_PAGES = new Set(['briefing', '@chat', '@sessions'])

/** The row behind a page item: by its key, its task or its inbox item */
function itemRow(it, byKey) {
  return byKey.get(it.key) ?? (it.task ? byKey.get(`task:${it.task}`) : null) ?? (it.inbox ? byKey.get(`inbox:${it.inbox}`) : null) ?? null
}

/** The state a page sees under the area filter (ui.area) and Work's star (ui.pinnedOnly): Work keeps the
 *  rows and page items of the area (or pinned) and the area's tabs beside them, Chat the tabs of the area, Sessions its sessions (by
 *  their tab, else their folder) and its starts. Every other page, and the header with its badges, gets
 *  the state as it is; so does a page without a filter (the same object back) */
export function areaScope(s) {
  const page = s?.ui?.page
  const area = AREA_PAGES.has(page) ? s.ui.area || null : null
  const pins = page === 'briefing' && s.ui.pinnedOnly ? new Set(s.home?.pins ?? []) : null
  if (!area && !pins) return s
  const byKey = indexRows(s.model)
  const tabs = s.tabs?.tabs ?? []
  // a tab stays with the area by its workspace, or by the task or inbox item of a row of the area it works on
  // (a tab of an area's task may run in a workspace named otherwise)
  const areaRows = area ? (s.model?.sections ?? []).flatMap(sec => sec.rows ?? []).filter(r => inProject(r, area)) : []
  const slugs = new Set(areaRows.map(r => r.task).filter(Boolean))
  const items = new Set(areaRows.map(r => r.inbox_id).filter(Boolean))
  const keepTab = t => t.is_control || inProject(t, area) || (!!t.slug && slugs.has(t.slug)) || (!!t.item && items.has(t.item))
  if (page === 'briefing') {
    const keepRow = r => !!r && inProject(r, area) && (!pins || pins.has(r.key))
    const keepItem = it => {
      const row = itemRow(it, byKey)
      return (inProject(it, area) || (!!row && inProject(row, area))) && (!pins || (!!row && pins.has(row.key)))
    }
    const model = s.model && {
      ...s.model,
      sections: (s.model.sections ?? []).map(sec => {
        const rows = (sec.rows ?? []).filter(keepRow)
        const shown = new Set(rows.map(r => r.key))
        return { ...sec, rows, total: rows.length, ...(sec.compact ? { compact: sec.compact.filter(k => shown.has(k)) } : {}) }
      }),
      hidden: (s.model.hidden ?? []).filter(keepRow),
      // a page section counts what it shows; `scoped` says the rows still to load are not filtered yet
      pages: (s.model.pages ?? []).map(p => ({ ...p, sections: (p.sections ?? []).map(sec => {
        if (!sec.items) return sec
        const items = sec.items.filter(keepItem)
        return { ...sec, items, total: items.length, count: items.length, scoped: true }
      }) })),
    }
    const more = Object.fromEntries(Object.entries(s.more ?? {}).map(([k, v]) => [k, v?.items ? { ...v, items: v.items.filter(keepItem) } : v]))
    // the tab column beside Work shows and counts the area's tabs too
    // wholeModel: what a search across every area looks its hits up in (the files view's search stays global)
    return { ...s, model, more, tabs: area ? { ...s.tabs, tabs: tabs.filter(keepTab) } : s.tabs, wholeModel: s.model, wholeTabs: s.tabs }
  }
  if (page === '@chat') {
    const kept = tabs.filter(keepTab)
    const listed = s.tabs?.workspaces
    // and only the workspaces that hold one of those tabs or carry the area's name: the others showed up
    // empty under the filter, a workspace nobody could enter (25.10.)
    const holds = w => kept.some(t => (t.ws_ref && w.ref ? t.ws_ref === w.ref : t.workspace === w.title))
    const keepWs = w => holds(w) || inProject({ workspace: w.title }, area)
    // the ones left out still tell the sidebar which Bridge a workspace lies in (roomsOf: other Bridges)
    const workspaces = listed ? { workspaces: listed.filter(keepWs), hidden_workspaces: listed.filter(w => !keepWs(w)) } : {}
    return { ...s, tabs: { ...s.tabs, tabs: kept, ...workspaces } }
  }
  // the Sessions page
  const tabOf = new Map(tabs.map(t => [t.ref, t]))
  const keepSession = x => {
    const tab = x.tab?.ref ? tabOf.get(x.tab.ref) : null
    return tab ? inProject(tab, area) : inProject({ workspace: x.project }, area)
  }
  const keepReturn = r => inProject(byKey.get(r.key) ?? {}, area) || (!!r.tab?.ref && !!tabOf.get(r.tab.ref) && inProject(tabOf.get(r.tab.ref), area))
  return {
    ...s,
    tabs: { ...s.tabs, tabs: tabs.filter(keepTab) },
    sessions: s.sessions && { ...s.sessions, sessions: (s.sessions.sessions ?? []).filter(keepSession) },
    model: s.model && { ...s.model, returns: (s.model.returns ?? []).filter(keepReturn) },
  }
}

/** The state the keys act on, or null where they act on no rows: Work under its filters, and the overview
 *  of the start page while its part "Waiting on you" is on (its rows only, of the area, folded as shown:
 *  `desk` marks it, a pick there would not show) */
export function keyScope(s) {
  const page = s?.ui?.page
  if (page === 'briefing') return areaScope(s)
  if (page !== '@start') return null
  const chosen = homeChosen(s.model, s.home)
  if (homeView(chosen) !== 'areas' || !chosen.includes('d:waiting')) return null
  const v = areaScope({ ...s, ui: { ...s.ui, page: 'briefing', pinnedOnly: false } })
  return { ...v, desk: true, ui: { ...s.ui, dayHeight: 0 },
    model: v.model && { ...v.model, sections: (v.model.sections ?? []).filter(x => x.id === 'now'), hidden: [] } }
}

/** A row as the page shows it under its filters (keyScope, else areaScope), or null when they hide it:
 *  what a key may act on */
export function scopeRow(s, key) {
  if (!key) return null
  const v = keyScope(s) ?? areaScope(s)
  return indexRows(v.model).get(key) ?? null
}

/** What leaves the ui once a filter hides it: picks, the focus and the selection on rows no longer shown,
 *  so nothing can act on a row unseen. A patch for setUi */
export function scopeKeep(s) {
  const shown = indexRows(areaScope(s).model)
  const keep = k => (k && shown.has(k) ? k : null)
  // the place in the files: kept where its file stands in the queue the filter leaves, else the walk starts over
  const at = s.ui?.dossierAt
  const files = at ? scopedFileQueue(s) : []
  const i = at ? files.findIndex(x => x.id === at.id) : -1
  return { picked: (s.ui?.picked ?? []).filter(k => shown.has(k)), focusKey: keep(s.ui?.focusKey), selectedKey: keep(s.ui?.selectedKey),
    dossierAt: i >= 0 ? { id: at.id, i } : null }
}

/** What Escape does on a page the area filter acts on: a selection (an open row or picks) closes first,
 *  then the filter goes; null when neither applies */
export function escapeStep(ui) {
  if (!ui?.area || !AREA_PAGES.has(ui.page)) return null
  return ui.selectedKey || ui.picked?.length ? 'selection' : 'area'
}

/** Whether the area lines can stand in for the project chips: every chip has a line, else a project
 *  without one could no longer be picked */
export function areasCoverProjects(projects, areas) {
  const have = new Set((areas ?? []).map(a => a.name.trim().toLowerCase()))
  return (projects ?? []).every(p => have.has(String(p).trim().toLowerCase()))
}
