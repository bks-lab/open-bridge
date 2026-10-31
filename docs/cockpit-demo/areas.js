// SPDX-License-Identifier: MIT
// Pure helpers of the cockpit's areas: the start page's area lines, where a number of them leads, the one
// area filter (ui.area) and the state a page sees under it. No DOM, no network, no state. logic.js passes
// every name on, so a view may import it from either; the frontend test imports this file under node.
import { asksYou, dueWhen, homeChosen, homeView, indexRows, wantsYou, workViewIn } from './logic.js'
import { scopedFileQueue } from './files.js'

// the aliases of workplace.workspaces (bootstrap config.area_aliases), lower case alias -> area name; set once at boot
let ALIASES = new Map()

/** Takes the server's {alias: area} map; every name compare of this file folds an alias into its area */
export function setAreaAliases(map) {
  ALIASES = new Map(Object.entries(map && typeof map === 'object' ? map : {})
    .filter(([a, n]) => typeof a === 'string' && typeof n === 'string' && a.trim() && n.trim())
    .map(([a, n]) => [a.trim().toLowerCase(), n.trim()]))
}

/** A name as its area spells it: an alias becomes its area, any other name stays as it is (trimmed) */
export const areaName = name => { const n = String(name ?? '').trim(); return ALIASES.get(n.toLowerCase()) ?? n }
/** The key two names of one area share: lower case, the alias folded */
export const areaKey = name => areaName(name).toLowerCase()

/** The areas a row stands in as the filter matches it (inProject): every name it carries, aliases folded, each once;
 *  none at all is [''] */
export function rowAreas(row) {
  const names = [row?.area, ...(row?.area_names ?? []), row?.mark?.label].filter(n => n && String(n).trim())
  const out = [...new Map(names.map(n => [areaKey(n), areaName(n)])).values()]
  return out.length ? out : ['']
}

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
    const key = areaKey(name)
    if (!key) return
    const x = seen.get(key) ?? { name: areaName(name), n: 0 }
    x.n += 1
    seen.set(key, x)
  }
  // an empty shell makes no area: nothing is open there
  for (const t of tabs ?? []) if (!t.is_control && t.state !== 'shell') add(t.workspace)
  for (const r of rows ?? []) add(rowProject(r))
  return [...seen.values()].sort((a, b) => b.n - a.n || a.name.localeCompare(b.name)).map(x => x.name)
}

/** Does a tab or a row belong to the chosen project? No project chosen: everything does */
export function inProject(x, project) {
  if (!project) return true
  const want = areaKey(project)
  const names = [x?.workspace, x?.area, ...(x?.area_names ?? []), x?.mark?.label]
  return names.some(n => n && areaKey(n) === want)
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
export function rowOverdue(row, nowMs) {
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
  const zero = () => ({ waiting: 0, waitingTabs: 0, waitingRows: 0, running: 0, review: 0, overdue: 0, tasks: 0, resting: 0 })
  // what has no area counts under NONE, the line "No area" at the end
  const bump = (name, what) => {
    const key = areaKey(name) || NONE
    const x = counts.get(key) ?? zero()
    x[what] += 1
    counts.set(key, x)
  }
  // a row of "now" that asks you stands for the tab that waits on its work; an idea or a report there asks nothing
  const paired = new Set()
  // a row counts under every area its filter matches (rowAreas), as Work through counts it under each
  const bumpRow = (r, what) => { for (const a of rowAreas(r)) bump(a, what) }
  for (const r of section('now').filter(asksYou)) {
    bumpRow(r, 'waiting')
    bumpRow(r, 'waitingRows')
    for (const t of live) if ((r.task && t.slug === r.task) || (r.inbox_id && t.item === r.inbox_id)) paired.add(t.ref)
  }
  // an answered start stands for its tab gone idle
  const answered = new Set()
  for (const r of returns ?? []) {
    const row = byKey.get(r.key)
    if (!row || (r.live ?? r.stage) !== 'result') continue
    bumpRow(row, 'review')
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
    if (restingTab(t)) bump(t.workspace, 'resting')
  }
  for (const r of rows) if (rowOverdue(r, nowMs)) bumpRow(r, 'overdue')
  const slugs = new Set()
  for (const r of section('work')) {
    if (!r.task || slugs.has(r.task)) continue
    slugs.add(r.task)
    bumpRow(r, 'tasks')
  }
  const line = (name, x, extra = {}) => ({ name, tone: projectTone(name), ...x, total: x.waiting + x.running + x.review + x.overdue, ...extra })
  const out = homeProjects(tabs, rows).map(name => line(name, counts.get(areaKey(name)) ?? zero()))
  if (counts.has(NONE)) out.push(line('', counts.get(NONE), { none: true, tone: 'muted' }))
  return out.filter(a => a.total > 0 || a.tasks > 0 || a.resting > 0)
}

const NONE = '\u0000none'   // no area name can be this

/** An agent tab at rest: open, not at work and not asking (an empty shell is no agent tab) */
export const restingTab = t => !!t && !t.is_control && t.state !== 'shell' && t.state !== 'working' && !wantsYou(t)

/** The agent tabs at rest in one area, by their workspace (an alias folded); '' counts those without a workspace */
export function restingIn(tabs, name) {
  const want = areaKey(name)
  return (tabs ?? []).filter(t => restingTab(t) && areaKey(t.workspace) === want).length
}

// the order of the figures a pill of the area bar shows: the first one that is not 0
const BAR_FIGS = ['waiting', 'overdue', 'running', 'review', 'tasks', 'resting']

let TAGS = new Map()
/** The tags of workplace.workspaces (boot, config.area_tags): what a log row's tag may say for an area */
export function setAreaTags(map) {
  TAGS = new Map(Object.entries(map ?? {}).map(([name, tags]) => [areaKey(name), (tags ?? []).map(t => String(t).toLowerCase())]))
}

const globbed = (word, pattern) => new RegExp(`^${pattern.split('*').map(p => p.replace(/[.+?^${}()|[\]\\]/g, '\\$&')).join('.*')}$`).test(word)

/** Does a log tag stand in an area? */
export const tagInArea = (tag, area) => (TAGS.get(areaKey(area)) ?? []).some(p => globbed(String(tag ?? '').toLowerCase(), p))

/** A page under the area filter that is no page of AREA_PAGES: its log, its dates or its cost card follow the area */
export function pageFollowsArea(page) {
  return !!page && ((page.sections ?? []).some(x => x.view === 'log' || (x.view === 'agenda' && x.kind === 'calendar')) || (page.cards ?? []).includes?.('costs'))
}

/** The area a word of ?ws= means: its name, an alias, or the id of its workspace; none: null */
export function areaOfWord(s, word) {
  const want = areaKey(word)
  if (!want) return null
  const byId = (s?.workspaces?.items ?? []).find(i => i.area && (i.id ?? '').toLowerCase() === want)
  return byId?.area ?? (s?.boot?.config?.areas ?? []).find(a => areaKey(a) === want) ?? null
}

const itemOf = s => (s?.ui?.area ? (s.workspaces?.items ?? []).find(i => i.area && areaKey(i.area) === areaKey(s.ui.area)) : null)

/** The log rows of the area; an area with no tags keeps them all, nothing says which are its own */
export function areaLog(s, items) {
  const area = s?.ui?.area
  if (!area || !(TAGS.get(areaKey(area)) ?? []).length) return items
  return (items ?? []).filter(it => tagInArea(it.group, area))
}

/** The dates of the area by the calendars its workspace names. None named: no filter. An empty list: none, and `none` says so */
export function areaDates(s, items) {
  const names = itemOf(s)?.calendars
  if (!Array.isArray(names)) return { items, none: false }
  return { items: (items ?? []).filter(it => names.includes(it.cal?.calendar)), none: !names.length }
}

/** The project the cost card opens on under an area */
export const areaCostCenter = s => itemOf(s)?.cost_center ?? null

/** A page's badge under the area filter: the counting rows of that area, else the server's */
export function areaBadge(s, page) {
  const area = s?.ui?.area
  const counting = (page?.sections ?? []).filter(x => x.weight > 0 && Array.isArray(x.rows))
  if (!area || !counting.length || page?.badge?.kind !== 'count') return page?.badge
  const n = counting.reduce((sum, x) => sum + x.rows.filter(r => inProject(r, area)).length * x.weight, 0)
  return n ? { kind: 'count', n } : { kind: 'none' }
}

/** The areas switched off on the settings page, as keys; an area may stand under an alias */
export const areasOff = s => new Set((s?.workspaces?.off ?? []).map(areaKey))

/** Lines or names without the areas switched off; the line "No area" stays */
export function withoutOff(s, list) {
  const off = areasOff(s)
  if (!off.size) return list ?? []
  return (list ?? []).filter(a => (typeof a === 'string' ? !off.has(areaKey(a)) : a.none || !off.has(areaKey(a.name))))
}

/** The bar of areas on the stage: a pill per area line (homeAreas, flowAreas) with one figure, what waits on you,
 *  else what is at work, else the tasks, else the tabs at rest; what waits first, then what works, then the most
 *  open, the line "No area" last; a line with no figure above 0 makes no pill. `configured` (workplace.workspaces)
 *  gives the quiet areas: those without a pill */
export function areaBar(lines, configured = []) {
  const pills = (lines ?? []).flatMap(a => {
    const kind = BAR_FIGS.find(k => (a[k] ?? 0) > 0)
    return kind ? [{ ...a, fig: { kind, n: a[kind] } }] : []
  }).sort((x, y) => (x.none ? 1 : 0) - (y.none ? 1 : 0) || (y.waiting ?? 0) - (x.waiting ?? 0) || (y.running ?? 0) - (x.running ?? 0)
    || ((y.tasks ?? 0) + (y.resting ?? 0)) - ((x.tasks ?? 0) + (x.resting ?? 0)) || String(x.name).localeCompare(String(y.name)))
  const have = new Set(pills.filter(p => !p.none).map(p => areaKey(p.name)))
  const quiet = [...new Set((configured ?? []).filter(n => typeof n === 'string' && n.trim() && !have.has(areaKey(n))))]
  return { pills, quiet }
}

/** Every number of a pill in words, for its title */
export const areaBarTitle = (pill, h) => h.areaBarParts({ waiting: pill.waiting ?? 0, overdue: pill.overdue ?? 0,
  running: pill.running ?? 0, review: pill.review ?? 0, tasks: pill.tasks ?? 0, resting: pill.resting ?? 0 })

/** Where a number of the areas leads, the area as the filter there (ui.area): tabs alone that want you
 *  are answered in the chat, one after the other (its walk); rows, or rows and tabs, wait in Work, what is due first, as do
 *  overdue rows; what runs and what is to review are the sessions and the starts of the Sessions page;
 *  the tasks open Work in the view it was left in, the area's name the files tab */
export function areaJump(kind, area) {
  // with Work through on (flow.js flowAreas) what waits, what is to review and what is overdue are its points
  if (area?.flow && ['waiting', 'review', 'overdue'].includes(kind)) return { page: '@flow' }
  if (kind === 'waiting') return area?.waitingTabs && !area.waitingRows ? { page: '@chat', walk: true } : { page: 'briefing', view: 'due' }
  if (kind === 'running' || kind === 'review') return { page: '@sessions' }
  if (kind === 'overdue') return { page: 'briefing', view: 'due' }
  // the area's name opens its files (the files tab, logic.js FILES_PAGE, stands on every Bridge)
  if (kind === 'name') return { page: '@files' }
  return { page: 'briefing' }
}

// the pages the area filter (ui.area) acts on; '@flow' is the Work through page (flow.js FLOW_PAGE), '@files' the files
// tab (logic.js FILES_PAGE), named here as literals since this file is evaluated before them when logic.js loads
export const AREA_PAGES = new Set(['briefing', '@chat', '@sessions', '@flow', '@files'])

// the view areaScope asks for when Work through takes the rows as Due scopes them: no view of the work tab, so the
// work tab's fallback (a Due switched off falls back to Work through) never leads back into Work through
const DUE_ROWS = '@due'

/** The row behind a page item: by its key, its task or its inbox item */
function itemRow(it, byKey) {
  return byKey.get(it.key) ?? (it.task ? byKey.get(`task:${it.task}`) : null) ?? (it.inbox ? byKey.get(`inbox:${it.inbox}`) : null) ?? null
}

/** The state a page sees under the area filter (ui.area) and Work's star (ui.pinnedOnly): Work keeps the
 *  rows and page items of the area (or pinned) and the area's tabs beside them, Chat the tabs of the area, Sessions its sessions (by
 *  their tab, else their folder) and its starts. Work through sees what Work sees under the area, and the starts of
 *  the area beside it (the star stays Work's). Every other page, and the header with its badges, gets
 *  the state as it is; so does a page without a filter (the same object back) */
export function areaScope(s) {
  const page = s?.ui?.page
  const area = AREA_PAGES.has(page) ? s.ui.area || null : null
  // Work's star keeps only the pinned rows, in the files tab too (it was a view of Work before round 6c)
  const pins = (page === 'briefing' || page === '@files') && s.ui.pinnedOnly ? new Set(s.home?.pins ?? []) : null
  if (!area && !pins) return s
  const byKey = indexRows(s.model)
  const tabs = s.tabs?.tabs ?? []
  // a tab stays with the area by its workspace, or by the task or inbox item of a row of the area it works on
  // (a tab of an area's task may run in a workspace named otherwise)
  const areaRows = area ? (s.model?.sections ?? []).flatMap(sec => sec.rows ?? []).filter(r => inProject(r, area)) : []
  const slugs = new Set(areaRows.map(r => r.task).filter(Boolean))
  const items = new Set(areaRows.map(r => r.inbox_id).filter(Boolean))
  const keepTab = t => t.is_control || inProject(t, area) || (!!t.slug && slugs.has(t.slug)) || (!!t.item && items.has(t.item))
  const tabOf = new Map(tabs.map(t => [t.ref, t]))
  const keepReturn = r => inProject(byKey.get(r.key) ?? {}, area) || (!!r.tab?.ref && !!tabOf.get(r.tab.ref) && inProject(tabOf.get(r.tab.ref), area))
  // the view the work tab shows, its fallback too (logic.js workViewIn: a view switched off shows Work through)
  if (page === '@flow' || (page === 'briefing' && s.ui.workView !== DUE_ROWS && workViewIn(s) === 'flow')) {
    // the rows as Due scopes them (DUE_ROWS: the same call with the view Work through again never ended)
    const v = areaScope({ ...s, ui: { ...s.ui, page: 'briefing', workView: DUE_ROWS, pinnedOnly: false } })
    // the sessions too, by their tab or folder as on the Sessions page: a linked session drives its task (In progress)
    const keepSession = x => (x.tab?.ref && tabOf.get(x.tab.ref) ? inProject(tabOf.get(x.tab.ref), area) : inProject({ workspace: x.project }, area))
    // the files of the area too (round 4: a backlog task or a stream of model.files is an open row of the page); the
    // files view keeps reading every file through wholeModel
    const files = Array.isArray(v.model?.files) && area ? { files: v.model.files.filter(f => inProject({ area_names: f.area_names }, area)) } : {}
    // the open tasks a page names and the items put off past the window are rows of the page too (flow.js universeOf):
    // under an area only that area's (28.10.: another area's closable task stood in every area)
    const rest = area && v.model ? { task_rows: (v.model.task_rows ?? []).filter(r => inProject(r, area)),
      deferred: (v.model.deferred ?? []).filter(r => inProject(r, area)) } : {}
    return { ...v, ui: s.ui, model: v.model && { ...v.model, returns: (s.model?.returns ?? []).filter(keepReturn), ...files, ...rest },
      sessions: s.sessions && area ? { ...s.sessions, sessions: (s.sessions.sessions ?? []).filter(keepSession) } : s.sessions }
  }
  // the files tab takes the rows as Work does (it was Work's view until round 6c)
  if (page === 'briefing' || page === '@files') {
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
  const keepSession = x => {
    const tab = x.tab?.ref ? tabOf.get(x.tab.ref) : null
    return tab ? inProject(tab, area) : inProject({ workspace: x.project }, area)
  }
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
