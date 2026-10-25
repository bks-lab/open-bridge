// SPDX-License-Identifier: MIT
// Tests of the cockpit's areas (scripts/web/areas.js and what the start page draws of them), no npm dependencies.
//
//   node --test scripts/tests/bridge_cockpit_areas.test.mjs
//
// The area lines of the start page and their numbers, where a number leads, the one area filter (ui.area)
// and what Work, Chat and Sessions show under it, tabs gone idle, the parts of the overview. The pure helpers
// are imported as the frontend suite imports them, the views are mounted as the render suite mounts them.
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import test from 'node:test'
import assert from 'node:assert/strict'
import { cockpitState, loadCockpit, mount, recorder } from './cockpit_render.mjs'

const here = path.dirname(fileURLToPath(import.meta.url))
const WEB = path.join(here, '..', 'web')
const { html, views, text, logic } = await loadCockpit()
const loadedRooms = await loadCockpit()
const en = text.TABLES.en

// a fixed local "now": Friday, 9 October 2026, noon (the same moment the other suites use)
const NOW = new Date(2026, 9, 9, 12, 0, 0).getTime()
const MIN = 60000

/** One start in the return channel, in the shape the server sends (model.returns) */
function start(over = {}) {
  return { key: 'inbox:20261009-0910-tidy-labels-c3d4', item: '20261009-0910-tidy-labels-c3d4', mode: 'go',
    title: 'Tidy the issue labels on the demo board', at_ms: NOW - 12 * MIN, stage: 'working', tab: { ref: 'surface:10' }, ...over }
}

// ---------------------------------------------------------------- areas: the pure helpers (from the frontend suite)

test('the start page: greeting by hour, project chips from tabs and rows, cards filtered by project', async () => {
  const logic = await import(pathToFileURL(path.join(WEB, 'logic.js')).href)
  assert.deepEqual([3, 7, 13, 19, 23].map(logic.greetingPart), ['night', 'early', 'day', 'evening', 'night'])
  const tabs = [
    { ref: 'c', name: 'Bridge', workspace: 'Bridge', state: 'waiting', is_control: true },
    { ref: 'a', name: 'Metrics', workspace: 'ACME', state: 'working', since_ms: 5 },
    { ref: 'b', name: 'Log', workspace: 'ACME', state: 'needs-you', since_ms: 9 },
    { ref: 'd', name: 'orbit', workspace: 'ORBIT', state: 'waiting', since_ms: 1 },
    { ref: 'e', name: 'zsh', workspace: '', state: 'shell' },
  ]
  const rows = [
    { key: 'r1', area: 'Bridge', area_names: ['Bridge', 'open-bridge'] },
    { key: 'r2', area: null, area_names: [], mark: { label: 'acme' } },
    { key: 'r3', area: 'Privat', area_names: ['Privat'] },
  ]
  // most frequent first, names merged without regard to case, the control tab and empty names left out
  assert.deepEqual(logic.homeProjects(tabs, rows), ['ACME', 'Bridge', 'ORBIT', 'Privat'])
  assert.equal(logic.inProject(rows[1], 'ACME'), true)
  assert.equal(logic.inProject(rows[0], 'open-bridge'), true)
  assert.equal(logic.inProject(rows[0], 'ACME'), false)
  assert.equal(logic.inProject(rows[0], null), true)          // no chip chosen: everything
  // continue: no control tab, no bare shell; needs-you before waiting before working
  assert.deepEqual(logic.homeContinue(tabs, null).map(t => t.ref), ['b', 'd', 'a'])
  assert.deepEqual(logic.homeContinue(tabs, 'acme').map(t => t.ref), ['b', 'a'])
  // a project name always gets the same tone, and only tokens DESIGN.md has
  assert.equal(logic.projectTone('ACME'), logic.projectTone('acme'))
  assert.ok(['secondary', 'accent', 'success', 'warning', 'info'].includes(logic.projectTone('ORBIT')))
  // the tab of a task row, by its slug
  assert.equal(logic.tabOfTask([{ ref: 'x', slug: 'foo' }], 'foo').ref, 'x')
  assert.equal(logic.tabOfTask([{ ref: 'x', slug: 'foo' }], null), null)
})

test('the start page counts per area what waits, runs, is to review, is overdue and its tasks, each thing once', async () => {
  const logic = await import(pathToFileURL(path.join(WEB, 'logic.js')).href)
  const now = new Date(2026, 9, 13, 12, 0).getTime()
  const tabs = [
    { ref: 'c', workspace: 'ACME', state: 'working', waiting: true, idle: true, is_control: true },   // the control tab: never
    { ref: 's', workspace: 'ACME', state: 'shell', waiting: true },                                  // a bare shell: never
    { ref: 'a', workspace: 'acme', state: 'working' },
    { ref: 'b', workspace: 'ACME', state: 'needs-you', waiting: true },
    { ref: 'i', workspace: ' ACME ', state: 'waiting', waiting: true, item: 'inbox-1' },            // the tab of the row inbox:1
    { ref: 'd', workspace: 'ORBIT', state: 'waiting', idle: true },
    { ref: 'g', workspace: 'ORBIT', state: 'waiting', idle: true, slug: 'a' },                       // its start answered: counted there
    { ref: 'e', workspace: 'ORBIT', state: 'waiting' },                                              // no idle field: waiting, not to review
    { ref: 'f', workspace: 'Quiet', state: 'shell' },                                                // counts for nothing
  ]
  const sections = [
    { id: 'now', rows: [{ key: 'inbox:1', inbox_id: 'inbox-1', area: 'Acme' }, { key: 'inbox:2', area: 'Privat', due: '2026-10-12' }] },
    { id: 'work', rows: [
      { key: 'task:a', task: 'a', area: 'ORBIT', due: '2026-10-01' },
      { key: 'task:b', task: 'b', area: 'ORBIT', due: '2026-10-13' },      // due today: not overdue
      { key: 'task:b2', task: 'b', area: 'ORBIT' },                        // the same task again: one task
      { key: 'task:c', task: 'c', area: 'ACME', due_at: '2026-10-10' },
      { key: 'task:d', task: 'd', area: 'Still', due: '2026-12-01' },      // only a task: the area stays, damped
      { key: 'gh:1', area: 'Board' }] },                                   // no task, no number: no line
  ]
  const returns = [
    { key: 'task:a', item: 'a', stage: 'result', live: 'result', tab: { ref: 'g' } },
    { key: 'task:c', stage: 'working', live: 'working' },                 // still at work: not to review
    { key: 'inbox:gone', stage: 'result', live: 'result' },               // its row is gone: no area
  ]
  const areas = logic.homeAreas(tabs, sections, returns, now)
  const rows = sections.flatMap(x => x.rows)
  // the order of the project chips, names merged without regard to case or spaces, an area without a number left out
  assert.deepEqual(areas.map(a => a.name), logic.homeProjects(tabs, rows).filter(n => !['Quiet', 'Board'].includes(n)))
  const by = Object.fromEntries(areas.map(a => [a.name.toLowerCase(), a]))
  assert.deepEqual(Object.keys(by).sort(), ['acme', 'orbit', 'privat', 'still'])
  const figs = a => [a.waiting, a.running, a.review, a.overdue, a.tasks, a.total]
  // the row inbox:1 and its waiting tab are one thing: 2 waiting (that one and tab b), not 3
  assert.equal(by.acme.tone, logic.projectTone('ACME'))
  assert.deepEqual(figs(by.acme), [2, 1, 0, 1, 1, 4])
  // the idle tab g is the start whose answer came: to review once, with d beside it; e waits
  assert.deepEqual(figs(by.orbit), [1, 0, 2, 1, 2, 4])
  assert.deepEqual(figs(by.privat), [1, 0, 0, 1, 0, 2])
  // tasks only: total 0, but the line stays so the area can still be picked
  assert.deepEqual(figs(by.still), [0, 0, 0, 0, 1, 0])
  assert.deepEqual(logic.homeAreas([], [], [], now), [])
  assert.deepEqual(logic.homeAreas(null, null, null, now), [])
  // the lines stand in for the chips only when every chip has a line
  assert.equal(logic.areasCoverProjects(['ACME', 'ORBIT'], areas), true)
  assert.equal(logic.areasCoverProjects(['ACME', 'Board'], areas), false)
  assert.equal(logic.areasCoverProjects(['acme '], areas), true)
  // inProject compares as the chips do: no case, no surrounding spaces
  assert.equal(logic.inProject({ workspace: ' ACME ' }, 'acme'), true)
  assert.equal(logic.inProject({ area: 'Acme' }, ' ACME'), true)
})

test('a tab that went idle is done, not waiting on you: walks, groups, counts and the picture leave it out', async () => {
  const logic = await import(pathToFileURL(path.join(WEB, 'logic.js')).href)
  const tab = (ref, state, over = {}) => ({ ref, state, name: ref, workspace: 'W', since_ms: 1, ...over })
  const tabs = [tab('n', 'needs-you'), tab('w', 'waiting', { waiting: true }), tab('i', 'waiting', { idle: true, waiting: false }),
    tab('k', 'working'), { ...tab('c', 'waiting'), is_control: true }]
  assert.equal(logic.wantsYou(tabs[0]), true)
  assert.equal(logic.wantsYou(tabs[1]), true)
  assert.equal(logic.wantsYou(tabs[2]), false)
  assert.equal(logic.wantsYou(tabs[3]), false)
  assert.equal(logic.wantsYou(tabs[4]), false)
  assert.equal(logic.tabWaits(tabs[2]), false)
  assert.deepEqual(logic.walkRefs(tabs), ['n', 'w'])
  // an idle tab stands in a group of its own, after the ones at work
  const q = logic.statusQueue(tabs)
  assert.deepEqual(q.map(g => g.state), ['needs-you', 'waiting', 'working', 'idle'])
  assert.deepEqual(q.find(g => g.state === 'idle').tabs.map(t => t.ref), ['i'])
  assert.deepEqual(logic.situation({ sections: [], returns: [] }, tabs, 0).waiting.map(t => t.ref), ['w'])
  assert.deepEqual(logic.situation({ sections: [], returns: [] }, tabs, 0).idle.map(t => t.ref), ['i'])
  // the graph: an idle tab reads as an answer to check, not as a question
  const g = { index: new Map([['work/tasks/x/STATUS.md', 0], ['work/tasks/y/STATUS.md', 1]]) }
  const live = logic.graphLive(g, [tab('i', 'waiting', { idle: true, slug: 'x' }), tab('w', 'waiting', { slug: 'y' })], [], [])
  assert.equal(live.get(0).tone, 'answer')
  assert.equal(live.get(1).tone, 'asks')
})

test('the control view: the default, also for a choice made before it existed; a chosen view stays', async () => {
  const logic = await import(pathToFileURL(path.join(WEB, 'logic.js')).href)
  const model = { pages: [{ id: 'ops', title: 'Ops', sections: [{ id: 'quota', kind: 'command', items: [
    { title: 'Session (5 h): 3 %', meter: { value: 3, max: 100, unit: '%', window_h: 5 } },
    { title: 'Week: 19 %', meter: { value: 19, max: 100, unit: '%', window_h: 168 } }] }] }] }
  const all = logic.homeCatalog(model).map(x => x.id)
  const old = all.filter(x => x !== 'o:stage')        // what the chooser offered before the control view
  assert.equal(logic.homeView(logic.homeChosen(model, null)), 'areas')
  // chosen before, no view option set (it was the bridge then): now the control view, the bridge is not added
  assert.equal(logic.homeView(logic.homeChosen(model, { tiles: ['c:waiting', 's:tasks'], seen: old })), 'areas')
  // a view chosen before stays
  assert.equal(logic.homeView(logic.homeChosen(model, { tiles: ['c:waiting', 'o:focusview'], seen: old })), 'focus')
  assert.equal(logic.homeView(logic.homeChosen(model, { tiles: ['o:classic'], seen: old })), 'tiles')
  assert.equal(logic.homeView(logic.homeChosen(model, { tiles: ['o:list'], seen: old })), 'list')
  // pinned is no longer a default shelf, but a choice that had it keeps it
  assert.equal(logic.homeChosen(model, null).includes('s:pinned'), false)
  assert.equal(logic.homeChosen(model, { tiles: ['s:pinned'], seen: old }).includes('s:pinned'), true)
  // "next up" takes the quota the defaults take: the first with a window of a day or more
  assert.equal(logic.homeQuota(model).label, 'Week')
  assert.equal(logic.homeQuota({ pages: [] }), null)
})

test('a number of the areas jumps to the page that holds those things, the area as its filter', async () => {
  const logic = await import(pathToFileURL(path.join(WEB, 'logic.js')).href)
  const a = { name: 'ACME', waiting: 2, waitingTabs: 1, running: 1, review: 1, overdue: 1, tasks: 3 }
  // tabs that want you are answered in the chat, walked one by one; rows alone wait in Work, what is due first
  assert.deepEqual(logic.areaJump('waiting', a), { page: '@chat', walk: true })
  assert.deepEqual(logic.areaJump('waiting', { ...a, waitingTabs: 0 }), { page: 'briefing', view: 'due' })
  assert.deepEqual(logic.areaJump('running', a), { page: '@sessions' })
  assert.deepEqual(logic.areaJump('review', a), { page: '@sessions' })
  assert.deepEqual(logic.areaJump('overdue', a), { page: 'briefing', view: 'due' })
  assert.deepEqual(logic.areaJump('tasks', a), { page: 'briefing' })
  // the name of an area opens its files (the files view stands on every Bridge)
  assert.deepEqual(logic.areaJump('name', a), { page: 'briefing', view: 'dossier' })
  // homeAreas says how many of the waiting are tabs
  const areas = logic.homeAreas([{ ref: 't', workspace: 'ACME', state: 'needs-you', waiting: true }],
    [{ id: 'now', rows: [{ key: 'inbox:1', area: 'ACME' }] }], [], 0)
  assert.equal(areas[0].waiting, 2)
  assert.equal(areas[0].waitingTabs, 1)
})

test('the area filter: Work, Chat and Sessions show the area only, the other pages and the badges everything', async () => {
  const logic = await import(pathToFileURL(path.join(WEB, 'logic.js')).href)
  const tabs = [{ ref: 'c', is_control: true, workspace: 'Bridge', state: 'waiting' }, { ref: 'a', workspace: 'ACME', state: 'working' },
    { ref: 'o', workspace: 'ORBIT', state: 'needs-you' }]
  const model = {
    sections: [{ id: 'now', total: 2, rows: [{ key: 'inbox:1', area: 'ACME' }, { key: 'inbox:2', area: 'ORBIT' }] },
      { id: 'work', total: 2, rows: [{ key: 'task:a', task: 'a', area: 'acme' }, { key: 'task:b', task: 'b', area: 'ORBIT' }] }],
    pages: [{ id: 'work', group: 'work', sections: [{ id: 'tasks', kind: 'tasks', items: [
      { key: 'item:work/tasks/a', task: 'a', title: 'A' }, { key: 'item:work/tasks/b', task: 'b', title: 'B' },
      { key: 'item:work/tasks/x', title: 'X', mark: { label: 'ACME' } }] }] }],
    returns: [{ key: 'task:a', stage: 'result' }, { key: 'task:b', stage: 'result' }],
  }
  const sessions = { sessions: [{ sid: '1', project: 'acme', tab: null }, { sid: '2', project: 'x', tab: { ref: 'o' } }, { sid: '3', project: 'y', tab: { ref: 'a' } }] }
  const more = { 'work/tasks': { items: model.pages[0].sections[0].items } }
  const base = { model, tabs: { tabs }, sessions, more, home: { pins: ['task:b'] } }
  const at = (page, ui = {}) => logic.areaScope({ ...base, ui: { page, area: 'ACME', ...ui } })
  const keys = v => v.model.sections.flatMap(x => x.rows.map(r => r.key))
  // Work: the rows and the page items of the area, a section's total follows; the tab column beside it too
  const work = at('briefing')
  assert.deepEqual(work.tabs.tabs.map(t => t.ref), ['c', 'a'])
  assert.deepEqual(keys(work), ['inbox:1', 'task:a'])
  assert.deepEqual(work.model.sections.map(x => x.total), [1, 1])
  assert.deepEqual(work.model.pages[0].sections[0].items.map(x => x.title), ['A', 'X'])
  assert.deepEqual(work.more['work/tasks'].items.map(x => x.title), ['A', 'X'])
  // Chat: the tabs of the area, the control tab stays
  assert.deepEqual(at('@chat').tabs.tabs.map(t => t.ref), ['c', 'a'])
  // and only the workspaces that hold one of them or carry the area's name: an empty one cannot be entered
  const listed = [{ ref: 'w1', title: 'Bridge' }, { ref: 'w2', title: 'ORBIT' }, { ref: 'w3', title: 'acme' }, { ref: 'w4', title: 'Scratch' }]
  const chat = logic.areaScope({ ...base, tabs: { tabs, workspaces: listed }, ui: { page: '@chat', area: 'ACME' } })
  assert.deepEqual(chat.tabs.workspaces.map(w => w.title), ['Bridge', 'acme'])
  assert.deepEqual(chat.tabs.hidden_workspaces.map(w => w.title), ['ORBIT', 'Scratch'])
  // a Bridge whose workspace the filter left out does not come back as an "other" Bridge
  const bridges = [{ id: 'b2', name: 'Two', path: '/repo/two' }]
  const rooms = logic.roomsOf({ ...chat, tabs: { ...chat.tabs, hidden_workspaces: [{ ref: 'w2', title: 'ORBIT', cwd: '/repo/two/x' }] },
    rooms: { bridges }, ui: chat.ui })
  assert.deepEqual(rooms.bridges, [])
  assert.equal(logic.areaScope({ ...base, tabs: { tabs }, ui: { page: '@chat', area: 'ACME' } }).tabs.workspaces, undefined)
  // Sessions: by the session's tab, else its folder; the starts by their row
  const sess = at('@sessions')
  assert.deepEqual(sess.sessions.sessions.map(x => x.sid), ['1', '3'])
  assert.deepEqual(sess.model.returns.map(r => r.key), ['task:a'])
  // any other page, or no area: the state as it is
  const start = { ...base, ui: { page: '@start', area: 'ACME' } }
  assert.equal(logic.areaScope(start), start)
  const plain = { ...base, ui: { page: 'briefing', area: null } }
  assert.equal(logic.areaScope(plain), plain)
  // only pinned (the star on Work): the rows and items whose row is pinned, with or without an area
  const pinned = logic.areaScope({ ...base, ui: { page: 'briefing', area: null, pinnedOnly: true } })
  assert.deepEqual(keys(pinned), ['task:b'])
  assert.deepEqual(pinned.model.pages[0].sections[0].items.map(x => x.title), ['B'])
  assert.deepEqual(keys(at('briefing', { pinnedOnly: true })), [])
  // the pin filter is Work's own
  assert.deepEqual(logic.areaScope({ ...base, ui: { page: '@chat', area: null, pinnedOnly: true } }).tabs.tabs.length, 3)
})

test('the tabs button counts the tabs that want you; a finished tab reads done', async () => {
  const logic = await import(pathToFileURL(path.join(WEB, 'logic.js')).href)
  const tabs = [{ ref: 'n', state: 'needs-you' }, { ref: 'w', state: 'waiting', waiting: true }, { ref: 'i', state: 'waiting', idle: true, long: null },
    { ref: 'c', state: 'needs-you', is_control: true }, { ref: 'k', state: 'working', long: 'working' }]
  assert.equal(logic.tabsButtonCount(tabs), 2)
  assert.equal(logic.tabStateKey(tabs[2]), 'idle')
  assert.equal(logic.tabStateKey(tabs[1]), 'waiting')
  assert.equal(logic.tabStateKey({ state: 'working', idle: true }), 'working')
  assert.equal(text.TABLES.en.state.idle, 'done')
  assert.equal(text.TABLES.de.state.idle, 'fertig')
})

test('the areas count waiting with one rule, split into tabs and rows; what has no area gets a line of its own', async () => {
  const logic = await import(pathToFileURL(path.join(WEB, 'logic.js')).href)
  const tabs = [
    { ref: 'a', workspace: 'ACME', state: 'needs-you' },                    // wants you, no server waiting flag: counts
    { ref: 'b', workspace: 'ACME', state: 'waiting', waiting: true, idle: true },   // idle: not waiting, whatever the flag says
    { ref: 'o', workspace: 'ORBIT', state: 'waiting', waiting: true },
    { ref: 'n', workspace: '', state: 'needs-you' },                         // no area
  ]
  const sections = [{ id: 'now', rows: [{ key: 'inbox:1', area: 'ORBIT' }, { key: 'inbox:2' }, { key: 'inbox:3' }] }]
  const areas = logic.homeAreas(tabs, sections, [], 0)
  const by = Object.fromEntries(areas.map(a => [a.none ? '-' : a.name, a]))
  assert.deepEqual([by.ACME.waiting, by.ACME.waitingTabs, by.ACME.waitingRows], [1, 1, 0])
  assert.deepEqual([by.ORBIT.waiting, by.ORBIT.waitingTabs, by.ORBIT.waitingRows], [2, 1, 1])
  // what has no area: one line at the end, named by the page
  assert.equal(areas.at(-1).none, true)
  assert.equal(areas.at(-1).name, '')
  assert.deepEqual([by['-'].waiting, by['-'].waitingTabs, by['-'].waitingRows], [3, 1, 2])
  // the jump follows what waits: tabs alone are walked in the chat, rows or a mix open Work on what is due
  assert.deepEqual(logic.areaJump('waiting', by.ACME), { page: '@chat', walk: true })
  assert.deepEqual(logic.areaJump('waiting', by.ORBIT), { page: 'briefing', view: 'due' })
  // the lines cover the chips without the no-area line
  assert.equal(logic.areasCoverProjects(['ACME', 'ORBIT'], areas), true)
  assert.deepEqual(logic.homeAreas([], [{ id: 'now', rows: [{ key: 'x', area: 'A' }] }], [], 0).map(a => a.none ?? false), [false])
})

test('under the area filter the compact rows, the hidden rows and the page counts follow; picks and focus that left go', async () => {
  const logic = await import(pathToFileURL(path.join(WEB, 'logic.js')).href)
  const model = {
    sections: [{ id: 'now', total: 3, compact: ['inbox:1', 'inbox:2'], rows: [{ key: 'inbox:1', area: 'ACME' }, { key: 'inbox:2', area: 'ORBIT' }, { key: 'inbox:3', area: 'ACME' }] }],
    hidden: [{ key: 'inbox:9', area: 'ORBIT' }, { key: 'inbox:8', area: 'ACME' }],
    pages: [{ id: 'work', group: 'work', sections: [{ id: 'inbox', kind: 'inbox', total: 3, count: 3, more: 4, items: [
      { key: 'item:1', inbox: '1' }, { key: 'item:2', inbox: '2' }, { key: 'item:3', inbox: '3' }] }] }],
  }
  const s = { model, more: {}, tabs: { tabs: [] }, home: { pins: ['inbox:2'] },
    ui: { page: 'briefing', area: 'ACME', expanded: {}, picked: ['inbox:1', 'inbox:2'], focusKey: 'inbox:2', selectedKey: 'inbox:2' } }
  const v = logic.areaScope(s)
  assert.deepEqual(v.model.sections[0].compact, ['inbox:1'])
  assert.deepEqual(v.model.hidden.map(r => r.key), ['inbox:8'])
  // the day list shows the area's rows only, also folded
  assert.deepEqual(logic.displayedRows(v.model, {}, logic.indexRows(v.model)).map(r => r.key), ['inbox:1'])
  // a page section counts what it shows and says that more are filtered
  const sec = v.model.pages[0].sections[0]
  assert.deepEqual([sec.total, sec.count, sec.scoped], [2, 2, true])
  // the star filter folds the compact rows too
  const p = logic.areaScope({ ...s, ui: { ...s.ui, area: null, pinnedOnly: true } })
  assert.deepEqual(p.model.sections[0].compact, ['inbox:2'])
  // what the filter hid leaves the picks, the focus and the selection; nothing can act on it unseen
  assert.deepEqual(logic.scopeKeep(s), { picked: ['inbox:1'], focusKey: null, selectedKey: null, dossierAt: null })
  assert.deepEqual(logic.scopeKeep({ ...s, ui: { ...s.ui, focusKey: 'inbox:1', selectedKey: null } }), { picked: ['inbox:1'], focusKey: 'inbox:1', selectedKey: null, dossierAt: null })
  assert.equal(logic.scopeRow(s, 'inbox:2'), null)
  assert.equal(logic.scopeRow(s, 'inbox:1').key, 'inbox:1')
  // the walk in the chat goes through the area's tabs only
  const tabs = [{ ref: 'a', workspace: 'ACME', state: 'needs-you' }, { ref: 'o', workspace: 'ORBIT', state: 'needs-you' }]
  assert.deepEqual(logic.walkRefs(logic.areaScope({ tabs: { tabs }, ui: { page: '@chat', area: 'ACME' } }).tabs.tabs), ['a'])
  // Escape: an open selection first, then the filter, and only on the pages it filters
  assert.equal(logic.escapeStep({ page: 'briefing', area: 'ACME', selectedKey: 'k', picked: [] }), 'selection')
  assert.equal(logic.escapeStep({ page: 'briefing', area: 'ACME', selectedKey: null, picked: ['k'] }), 'selection')
  assert.equal(logic.escapeStep({ page: 'briefing', area: 'ACME', selectedKey: null, picked: [] }), 'area')
  assert.equal(logic.escapeStep({ page: '@start', area: 'ACME', selectedKey: null, picked: [] }), null)
  assert.equal(logic.escapeStep({ page: 'briefing', area: null, selectedKey: 'k', picked: [] }), null)
})

test('the overview parts: off by default, a choice made before them does not get them, the keys reach only shown rows', async () => {
  const logic = await import(pathToFileURL(path.join(WEB, 'logic.js')).href)
  const model = { pages: [], sections: [
    { id: 'now', total: 2, compact: ['inbox:1', 'inbox:2'], rows: [{ key: 'inbox:1', area: 'ACME' }, { key: 'inbox:2', area: 'ORBIT' }] },
    { id: 'work', total: 1, compact: ['task:a'], rows: [{ key: 'task:a', task: 'a', area: 'ACME' }] }] }
  const all = logic.homeCatalog(model)
  const desk = all.filter(x => x.kind === 'desk').map(x => x.id)
  assert.deepEqual(desk, ['d:waiting', 'd:guide', 'd:tabs', 'd:day'])
  assert.equal(logic.homeChosen(model, null).some(x => x.startsWith('d:')), false)
  const old = all.map(x => x.id).filter(x => !x.startsWith('d:'))
  assert.equal(logic.homeChosen(model, { tiles: ['s:areas'], seen: old }).some(x => x.startsWith('d:')), false)
  // the keys on the overview: the rows of "Waiting on you" when that part is on, the area's only
  const ui = { page: '@start', area: null, expanded: {}, picked: [], dayHeight: 900 }
  const base = { model, tabs: { tabs: [] }, more: {}, home: { tiles: ['s:areas'], seen: all.map(x => x.id) }, ui }
  assert.equal(logic.keyScope(base), null)
  const on = { ...base, home: { ...base.home, tiles: ['s:areas', 'd:waiting'] } }
  const rows = v => logic.displayedRows(v.model, v.ui.expanded, logic.indexRows(v.model), v.ui.dayHeight).map(r => r.key)
  assert.deepEqual(rows(logic.keyScope(on)), ['inbox:1', 'inbox:2'])
  assert.equal(logic.keyScope(on).desk, true)
  const acme = { ...on, ui: { ...ui, area: 'ACME' } }
  assert.deepEqual(rows(logic.keyScope(acme)), ['inbox:1'])
  assert.equal(logic.scopeRow(acme, 'inbox:2'), null)
  assert.equal(logic.scopeRow(acme, 'task:a'), null)            // a task row is not on the overview
  assert.equal(logic.scopeRow(acme, 'inbox:1').key, 'inbox:1')
  // another view of the start page: no keys there, as before
  assert.equal(logic.keyScope({ ...on, home: { ...on.home, tiles: ['d:waiting', 'o:classic'] } }), null)
  // Work: the rows its filters show
  assert.deepEqual(rows(logic.keyScope({ ...base, ui: { ...ui, page: 'briefing', area: 'ACME', dayHeight: 0 } })), ['inbox:1', 'task:a'])
})

// ---------------------------------------------------------------- areas: what the views show (from the render suite)

// ---------------------------------------------------------------- the areas on the start page

const { HomeAreas, HomePage } = views.home

const AREAS = [
  { name: 'ACME', tone: 'accent', waiting: 2, waitingTabs: 1, running: 1, review: 0, overdue: 1, tasks: 3, total: 4 },
  { name: 'ORBIT', tone: 'info', waiting: 0, waitingTabs: 0, running: 0, review: 2, overdue: 0, tasks: 0, total: 2 },
  { name: 'Still', tone: 'success', waiting: 0, waitingTabs: 0, running: 0, review: 0, overdue: 0, tasks: 1, total: 0 },
]

test('areas: a table, the column heads once, a line per area; the name filters the start page, a number jumps', () => {
  const c = recorder()
  const el = mount(html`<${HomeAreas} areas=${AREAS} project="ACME" c=${c} />`)
  assert.equal(el.$('h2').text(), en.home.areasTitle)
  assert.deepEqual(el.$$('thead th').map(x => x.text()).slice(1),
    [en.home.areaWaiting, en.home.areaRunning, en.home.areaReview, en.home.areaOverdue, en.home.areaTasks])
  const lines = el.$$('tbody tr')
  // "All" first, then the areas in their order
  assert.equal(lines.length, 4)
  const picks = el.$$('button.home-area-pick')
  assert.match(picks[0].text(), new RegExp(en.home.all))
  assert.equal(picks[0].getAttribute('aria-pressed'), 'false')
  assert.equal(picks[1].getAttribute('aria-pressed'), 'true')
  assert.ok(picks[1].$('.home-area-dot').hasClass('tk-accent'))
  // a line with nothing but tasks is damped
  assert.ok(lines[3].hasClass('is-quiet'))
  assert.ok(!lines[1].hasClass('is-quiet'))
  // the numbers, each with its label for the narrow screen; a zero is damped and no button
  const cells = lines[1].$$('td')
  assert.deepEqual(cells.map(x => x.text()), ['2', '1', '0', '1', '3'])
  assert.deepEqual(cells.map(x => x.getAttribute('data-label')),
    [en.home.areaWaiting, en.home.areaRunning, en.home.areaReview, en.home.areaOverdue, en.home.areaTasks])
  assert.ok(cells[2].hasClass('is-zero'))
  assert.equal(cells[2].$('button'), null)
  // "All" sums them up
  assert.deepEqual(lines[0].$$('td').map(x => x.text()), ['2', '1', '2', '1', '4'])
  picks[1].click()
  picks[2].click()
  picks[0].click()
  cells[0].$('button').click()
  cells[3].$('button').click()
  assert.deepEqual(c.calls, [['setArea', null], ['setArea', 'ORBIT'], ['setArea', null],
    ['goArea', 'ACME', { page: '@chat', walk: true }], ['goArea', 'ACME', { page: 'briefing', view: 'due' }]])
})

test('areas in the control view: the name opens Work for that area instead of filtering the start page', () => {
  const c = recorder()
  const el = mount(html`<${HomeAreas} areas=${AREAS} project=${null} c=${c} desk />`)
  const picks = el.$$('button.home-area-pick')
  assert.equal(picks[1].getAttribute('aria-pressed'), null)
  picks[1].click()
  picks[0].click()
  assert.deepEqual(c.calls, [['goArea', 'ACME', { page: 'briefing', view: 'dossier' }], ['goArea', null, { page: 'briefing', view: 'dossier' }]])
})

test('areas: with nothing in any area a short line says so', () => {
  const el = mount(html`<${HomeAreas} areas=${[]} project=${null} c=${recorder()} />`)
  assert.equal(el.$$('button.home-area-pick').length, 0)
  assert.match(el.text(), new RegExp(en.home.areasEmpty.slice(0, 20)))
})

test('the control view is the start page: one head line, the areas, next up, and nothing else', () => {
  const s = cockpitState(NOW, { ui: { page: '@start' } })
  const el = mount(html`<${HomePage} s=${s} c=${recorder()} />`)
  const desk = el.$('.desk')
  assert.ok(desk, 'the control view')
  assert.deepEqual(desk.childNodes.filter(x => x.nodeType === 1).map(x => x.getAttribute('class').split(' ')[0]), ['desk-head', 'home-shelf', 'desk-next'])
  assert.ok(desk.$('.home-areas'))
  // no greeting, no ask box, no news band, no other shelf
  for (const sel of ['.home-hero', '.home-ask', '.ticker', '.home-chips', '.home-grid', '.bridge-stage']) assert.equal(el.$(sel), null, sel)
  // the head counts what waits on you as the column does
  const sum = el.$$('tbody tr').slice(1).reduce((n, tr) => n + Number(tr.$$('td')[0].text()), 0)
  assert.match(el.$('.desk-head').text(), new RegExp(en.home.deskWaiting(sum)))
  // next up names the next date and the quota, each a link
  assert.ok(el.$$('.desk-next button').length >= 1)
})

test('the area bar: over Work it names the area and offers the star filter; nothing on a page it does not filter', () => {
  const { AreaBar } = views.home
  const c = recorder()
  const s = cockpitState(NOW, { ui: { page: 'briefing', area: 'ACME' } })
  s.home = { ...s.home, pins: ['task:a'] }
  const el = mount(html`<${AreaBar} s=${s} c=${c} />`)
  assert.match(el.text(), new RegExp(en.home.areaFilter('ACME')))
  el.button(en.home.areaClear).click()
  const star = el.$$('button').find(b => b.getAttribute('aria-pressed') === 'false')
  star.click()
  assert.deepEqual(c.calls, [['setArea', null], ['setPinnedOnly', true]])
  // Chat with an area: the area, no star
  const withTab = cockpitState(NOW, { ui: { page: '@chat', area: 'ACME' } })
  withTab.tabs = { ...withTab.tabs, tabs: [{ ref: 'a', workspace: 'ACME', state: 'working' }] }
  const chat = mount(html`<${AreaBar} s=${withTab} c=${recorder()} />`)
  assert.equal(chat.$$('button').length, 1)
  assert.equal(chat.$('.area-bar-empty'), null)
  // an area without an agent tab says so on Chat and offers every area, the control tab and shells count for nothing
  const none = cockpitState(NOW, { ui: { page: '@chat', area: 'ACME' } })
  none.tabs = { ...none.tabs, at_ms: NOW, error: null, tabs: [{ ref: 'c', is_control: true, workspace: 'ACME', state: 'waiting' },
    { ref: 's', workspace: 'ACME', state: 'shell' }, { ref: 'o', workspace: 'ORBIT', state: 'working' }] }
  const cc = recorder()
  const empty = mount(html`<${AreaBar} s=${none} c=${cc} />`)
  assert.equal(empty.$('.area-bar-empty').text(), en.home.areaNoTabs('ACME'))
  empty.$('.area-bar-all').click()
  assert.deepEqual(cc.calls, [['setArea', null]])
  // before the first answer of the terminal, or over its error, no hint
  assert.equal(mount(html`<${AreaBar} s=${{ ...none, tabs: { ...none.tabs, at_ms: 0 } }} c=${recorder()} />`).$('.area-bar-empty'), null)
  assert.equal(mount(html`<${AreaBar} s=${{ ...none, tabs: { ...none.tabs, error: 'no driver' } }} c=${recorder()} />`).$('.area-bar-empty'), null)
  // the start page and a page without a filter: no bar
  assert.equal(mount(html`<${AreaBar} s=${cockpitState(NOW, { ui: { page: '@start', area: 'ACME' } })} c=${recorder()} />`).$('.area-bar'), null)
  assert.equal(mount(html`<${AreaBar} s=${cockpitState(NOW, { ui: { page: '@chat', area: null } })} c=${recorder()} />`).$('.area-bar'), null)
})

test('areas: what has no area stands last as "No area", its numbers jump without a filter', () => {
  const c = recorder()
  const none = { name: '', none: true, tone: 'muted', waiting: 2, waitingTabs: 1, waitingRows: 1, running: 0, review: 0, overdue: 0, tasks: 0, total: 2 }
  const el = mount(html`<${HomeAreas} areas=${[AREAS[0], none]} project=${null} c=${c} desk />`)
  const lines = el.$$('tbody tr')
  assert.match(lines.at(-1).text(), new RegExp(en.home.noArea))
  lines.at(-1).$('td button').click()
  lines.at(-1).$('button.home-area-pick').click()
  assert.deepEqual(c.calls, [['goArea', null, { page: 'briefing', view: 'due' }], ['goArea', null, { page: 'briefing', view: 'dossier' }]])
  // a table also for screen readers when the narrow layout draws it as blocks
  assert.equal(el.$('table').getAttribute('role'), 'table')
  assert.equal(lines[0].getAttribute('role'), 'row')
  assert.equal(lines[0].$('td').getAttribute('role'), 'cell')
  assert.equal(el.$('thead th').getAttribute('role'), 'columnheader')
})

test('the overview: the head counts what waits as the line All does, split into tabs and entries', () => {
  const s = cockpitState(NOW, { ui: { page: '@start' } })
  const el = mount(html`<${HomePage} s=${s} c=${recorder()} />`)
  const all = el.$$('tbody tr')[0]
  const n = Number(all.$$('td')[0].text())
  assert.ok(n > 0)
  assert.match(el.$('.desk-head').text(), new RegExp(en.home.deskWaiting(n).replace(/[()]/g, '.')))
})

test('the overview with the areas switched off says where they went', () => {
  const s = cockpitState(NOW, { ui: { page: '@start' } })
  const { logic } = loadedRooms
  s.home = { tiles: logic.homeChosen(s.model, null).filter(x => x !== 's:areas'), seen: logic.homeCatalog(s.model).map(x => x.id), pins: [] }
  const el = mount(html`<${HomePage} s=${s} c=${recorder()} />`)
  assert.equal(el.$('table'), null)
  assert.match(el.$('.desk').text(), new RegExp(en.home.areasOff.slice(0, 20)))
})

test('start page views: the news band only when switched on for the start page; the day, the areas, then the chips', () => {
  const { logic } = loadedRooms
  const walk = root => { const out = []; const go = n => { for (const x of n.childNodes) if (x.nodeType === 1) { out.push(x); go(x) } }; go(root); return out }
  for (const view of ['tiles', 'stage']) {
    const base = cockpitState(NOW, { ui: { page: '@start' } })
    const tiles = logic.homeViewSet(logic.homeChosen(base.model, null), view)
    const home = { tiles, seen: logic.homeCatalog(base.model).map(x => x.id), pins: [] }
    const off = mount(html`<${HomePage} s=${{ ...base, home }} c=${recorder()} />`)
    assert.equal(off.$('.ticker'), null, view)
    const on = mount(html`<${HomePage} s=${{ ...base, home, ui: { ...base.ui, tickerOnStart: true } }} c=${recorder()} />`)
    assert.ok(on.$('.ticker'), view)
    // in page order: the day shelf before the areas, the areas before any chip row
    const els = walk(off)
    const areas = els.findIndex(x => x.hasClass('home-areas'))
    const chips = els.findIndex(x => x.hasClass('home-chips'))
    const day = els.findIndex(x => x.getAttribute('aria-labelledby') === 'home-day')
    assert.ok(areas >= 0, view)
    if (day >= 0) assert.ok(day < areas, view)
    if (chips >= 0) assert.ok(areas < chips, view)
  }
})

test('one area filter: on the other start views the bar names it, the overview shows none', () => {
  const { AreaBar } = views.home
  const { logic } = loadedRooms
  const base = cockpitState(NOW, { ui: { page: '@start', area: 'ACME' } })
  const tiles = { tiles: logic.homeViewSet(logic.homeChosen(base.model, null), 'tiles'), seen: logic.homeCatalog(base.model).map(x => x.id), pins: [] }
  assert.match(mount(html`<${AreaBar} s=${{ ...base, home: tiles }} c=${recorder()} />`).text(), new RegExp(en.home.areaFilter('ACME')))
  assert.equal(mount(html`<${AreaBar} s=${base} c=${recorder()} />`).$('.area-bar'), null)
})

test('the middle of Due shows the day, with a work page too, under the same area filter; the overview does not', () => {
  const { DetailColumn } = views.detail
  const { logic } = loadedRooms
  const base = cockpitState(NOW, { ui: { page: 'briefing', selectedKey: null } })
  const day = { id: 'today', title: 'What happened today', group: 'day', sections: [{ id: 'log', title: 'Log', kind: 'list', items: [
    { key: 'item:today/log/a', title: 'ACME deploy', detail: '', when: '', tone: 'ok', mark: { label: 'ACME' } },
    { key: 'item:today/log/b', title: 'ORBIT backup', detail: '', when: '', tone: 'ok', mark: { label: 'ORBIT' } }] }] }
  const work = { id: 'work', title: 'Work', group: 'work', sections: [{ id: 'tasks', title: 'Tasks', kind: 'tasks', items: [] }] }
  const s = { ...base, model: { ...base.model, pages: [...(base.model.pages ?? []), work, day] } }
  const el = mount(html`<${DetailColumn} s=${s} c=${recorder()} byKey=${logic.indexRows(s.model)} />`)
  assert.ok(el.$('.day-view'), 'the day in the middle')
  assert.match(el.text(), new RegExp(en.agendaTitle))
  assert.match(el.text(), /ACME deploy/)
  assert.match(el.text(), /ORBIT backup/)
  // under the area filter the day keeps to the area as the rows do
  const scoped = { ...s, ui: { ...s.ui, area: 'ACME' } }
  const fel = mount(html`<${DetailColumn} s=${scoped} c=${recorder()} byKey=${logic.indexRows(s.model)} />`)
  assert.match(fel.text(), /ACME deploy/)
  assert.doesNotMatch(fel.text(), /ORBIT backup/)
  // the overview on Start shows no day
  const start = mount(html`<${HomePage} s=${{ ...s, ui: { ...s.ui, page: '@start' } }} c=${recorder()} />`)
  assert.equal(start.$('.day-view'), null)
  assert.equal(start.$('.day-card'), null)
  assert.doesNotMatch(start.text(), /ACME deploy/)
})

test('Work under an area filter: the tab column shows and counts that area, the middle counts what waits there', () => {
  const { TabsColumn } = views.tabs
  const { DetailColumn } = views.detail
  const { logic } = loadedRooms
  const base = cockpitState(NOW, { ui: { page: 'briefing', selectedKey: null, area: 'ACME' } })
  const tabs = [{ ref: 'c', name: 'control', is_control: true, workspace: 'Bridge', state: 'waiting' },
    { ref: 'a1', name: 'acme-one', workspace: 'ACME', state: 'needs-you', waiting: true },
    { ref: 'a2', name: 'acme-two', workspace: 'ACME', state: 'working' },
    { ref: 'o1', name: 'orbit-one', workspace: 'ORBIT', state: 'needs-you', waiting: true },
    { ref: 'o2', name: 'orbit-two', workspace: 'ORBIT', state: 'working' }]
  const model = { ...base.model, briefing_badge: 11, headline_rest: 'free for the rest of the day',
    sections: [{ id: 'now', total: 3, rows: [{ key: 'inbox:1', title: 'A', area: 'ACME' }, { key: 'inbox:2', title: 'B', area: 'ORBIT' }, { key: 'inbox:3', title: 'C', area: 'ORBIT' }] }] }
  const s = { ...base, model, tabs: { ...base.tabs, tabs } }
  const v = logic.areaScope(s)
  const col = mount(html`<${TabsColumn} s=${v} c=${recorder()} byKey=${logic.indexRows(v.model)} />`)
  assert.match(col.text(), /acme-one/)
  assert.doesNotMatch(col.text(), /orbit-one|orbit-two/)
  assert.match(col.$('#tabs-title').text(), /2/)
  // the middle: what waits in the area (its row and its tab), as the area's line on the overview counts it
  const mid = mount(html`<${DetailColumn} s=${s} c=${recorder()} byKey=${logic.indexRows(s.model)} />`)
  assert.match(mid.$('.detail-title').text(), new RegExp(en.forYouNow(2)))
  assert.doesNotMatch(mid.$('.detail-title').text(), /11/)
  assert.match(mid.$('.detail-title').text(), /free for the rest of the day/)
  // what stays global says so
  assert.match(mid.text(), new RegExp(en.allAreas))
  // without a filter the server's number stands
  const whole = mount(html`<${DetailColumn} s=${{ ...s, ui: { ...s.ui, area: null } }} c=${recorder()} byKey=${logic.indexRows(s.model)} />`)
  assert.match(whole.$('.detail-title').text(), new RegExp(en.forYouNow(11)))
  assert.doesNotMatch(whole.text(), new RegExp(en.allAreas))
})

// ---------------------------------------------------------------- the parts of the overview

function deskState(parts, over = {}) {
  const { logic } = loadedRooms
  const base = cockpitState(NOW, { ui: { page: '@start', ...(over.ui ?? {}) } })
  const tiles = [...logic.homeChosen(base.model, null), ...parts]
  return { ...base, home: { tiles, seen: logic.homeCatalog(base.model).map(x => x.id), pins: [] } }
}

test('overview parts: none by default; each one shows only when chosen, in the chosen order, under the table', () => {
  const off = mount(html`<${HomePage} s=${deskState([])} c=${recorder()} />`)
  for (const id of ['desk-waiting', 'desk-guide', 'desk-tabs', 'desk-day']) assert.equal(off.$(`#${id}`), null, id)
  const s = deskState(['d:waiting', 'd:tabs', 'd:day'])
  const el = mount(html`<${HomePage} s=${s} c=${recorder()} />`)
  const desk = el.$('.desk')
  const kids = desk.childNodes.filter(x => x.nodeType === 1).map(x => x.getAttribute('class').split(' ')[0])
  // the head, the table, the parts, then next up
  assert.equal(kids[0], 'desk-head')
  assert.equal(kids.at(-1), 'desk-next')
  assert.ok(el.$('.desk-parts'))
  // waiting on you: the rows of the Work section, the same component (its rows, their actions)
  const waiting = el.$('#desk-waiting')
  assert.ok(waiting, 'waiting on you')
  assert.ok(waiting.$$('li.row').length > 0)
  assert.ok(waiting.$('.row-acts'))
  // the agent tabs: the same cards as beside Work
  assert.ok(el.$('#desk-tabs .tabcard'))
  // the day: the blocks of the middle of Work
  assert.ok(el.$('#desk-day .day-view'))
  // the guide was not chosen
  assert.equal(el.$('#desk-guide'), null)
  // the order of the choice is the order on the page
  const s2 = deskState(['d:day', 'd:waiting'])
  const el2 = mount(html`<${HomePage} s=${s2} c=${recorder()} />`)
  const ids = el2.$('.desk-parts').childNodes.filter(x => x.nodeType === 1).map(x => x.getAttribute('id'))
  assert.deepEqual(ids, ['desk-day', 'desk-waiting'])
})

test('overview parts follow the area filter, and with one on the bar names the filter', () => {
  const { AreaBar } = views.home
  const s = deskState(['d:waiting', 'd:tabs'], { ui: { area: 'zzz-no-such-area' } })
  const el = mount(html`<${HomePage} s=${s} c=${recorder()} />`)
  // nothing of the area: the parts stay small or away, no big empty cards
  assert.equal(el.$$('#desk-waiting li.row').length, 0)
  assert.equal(el.$('#desk-tabs .tabcard'), null)
  assert.match(mount(html`<${AreaBar} s=${s} c=${recorder()} />`).text(), /zzz-no-such-area/)
  // without a part the overview has no filter, so no bar
  assert.equal(mount(html`<${AreaBar} s=${deskState([], { ui: { area: 'ACME' } })} c=${recorder()} />`).$('.area-bar'), null)
})

test('overview: the decision guide shows the next tab that wants you, with next and previous when there are more', async () => {
  const s = deskState(['d:guide'])
  const tabs = [{ ref: 'g1', name: 'first', workspace: 'W', state: 'needs-you', since_ms: NOW - 9000 },
    { ref: 'g2', name: 'second', workspace: 'W', state: 'waiting', since_ms: NOW - 5000 }]
  const st = { ...s, tabs: { ...s.tabs, tabs }, guide: { enabled: true, auto: true, entries: {} } }
  const c = recorder()
  const el = mount(html`<${HomePage} s=${st} c=${c} />`)
  const box = el.$('#desk-guide')
  assert.ok(box)
  assert.match(box.text(), /first/)
  assert.doesNotMatch(box.text(), /second/)
  box.button(en.home.deskNext).click()
  await new Promise(r => setTimeout(r, 0))     // Preact draws a state change on the next tick
  assert.match(el.$('#desk-guide').text(), /second/)
  // the guide off: the part says nothing
  const none = mount(html`<${HomePage} s=${{ ...st, guide: { enabled: false } }} c=${recorder()} />`)
  assert.equal(none.$('#desk-guide'), null)
})

test('no Customise and no settings link on the start page: the page bar has Settings', () => {
  const { logic } = loadedRooms
  for (const view of ['areas', 'tiles', 'stage', 'list']) {
    const base = cockpitState(NOW, { ui: { page: '@start' } })
    const tiles = logic.homeViewSet(logic.homeChosen(base.model, null), view)
    const c = recorder()
    const el = mount(html`<${HomePage} s=${{ ...base, home: { tiles, seen: logic.homeCatalog(base.model).map(x => x.id), pins: [] } }} c=${c} />`)
    // the small links only: reading the text of every button of the bridge (its stations draw SVG) takes minutes
    assert.equal(el.$$('button.btn-link').some(b => b.text() === en.home.choose), false, view)
    assert.equal(el.$('.stage-tools') ?? el.$('.desk-tools'), null, view)
    assert.equal(c.calls.some(x => x[0] === 'setDrawer' && x[1] === 'customize'), false, view)
  }
})

test('the overview\'s day holds dates, status and tidying; commits and the log of today stay on Work', () => {
  const day = { id: 'today', title: 'What happened today', group: 'day', sections: [{ id: 'log', title: 'Log', kind: 'list', items: [
    { key: 'item:today/log/a', title: 'a long log line', detail: '', when: '', tone: 'ok' }] }] }
  const base = deskState(['d:day'])
  const s = { ...base, model: { ...base.model, pages: [...(base.model.pages ?? []), day] } }
  const el = mount(html`<${HomePage} s=${s} c=${recorder()} />`)
  assert.ok(el.$('#desk-day .day-view'))
  assert.equal(el.$('#desk-day .day-more'), null)
  assert.doesNotMatch(el.$('#desk-day').text(), /a long log line/)
})

// ---------------------------------------------------------------- the area of an inbox item (detail page)

test('area: an inbox item without a task picks one of the configured areas in its detail, or none', () => {
  const { DetailColumn } = views.detail
  const s = cockpitState(NOW)
  s.boot = { ...s.boot, config: { areas: ['Bridge', 'Home'] } }
  const item = { ...s.model.sections.flatMap(sec => sec.rows ?? []).find(r => r.inbox_id), task: null, area: 'Home' }
  s.ui = { ...s.ui, selectedKey: item.key }
  const c = recorder()
  const el = mount(html`<${DetailColumn} s=${s} c=${c} byKey=${new Map([[item.key, item]])} />`)
  const pick = el.$('select.area-pick')
  assert.ok(pick, 'the detail has an area picker')
  assert.deepEqual(pick.$$('option').map(o => o.text()), [en.areaNone, 'Bridge', 'Home'])
  assert.equal(pick.value ?? pick.getAttribute('value'), 'Home')
  pick.value = 'Bridge'
  pick.dispatch('change')
  assert.deepEqual(c.calls.at(-1), ['act', 'area', { key: item.key, value: 'Bridge' }])
  pick.value = ''
  pick.dispatch('change')
  assert.deepEqual(c.calls.at(-1), ['act', 'area', { key: item.key }])
  // an item with a task shows its task's area and has no picker; without configured areas there is none either
  const linked = { ...item, task: 'alpha' }
  s.ui = { ...s.ui, selectedKey: linked.key }
  assert.equal(mount(html`<${DetailColumn} s=${s} c=${c} byKey=${new Map([[linked.key, linked]])} />`).$('select.area-pick'), null)
  s.boot = { ...s.boot, config: {} }
  s.ui = { ...s.ui, selectedKey: item.key }
  assert.equal(mount(html`<${DetailColumn} s=${s} c=${c} byKey=${new Map([[item.key, item]])} />`).$('select.area-pick'), null)
})
