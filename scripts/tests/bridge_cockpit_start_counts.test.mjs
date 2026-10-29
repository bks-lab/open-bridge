// SPDX-License-Identifier: MIT
// Tests of the start page's numbers against Work through (scripts/web/flow.js flowAreas, flowWaiting), no npm
// dependencies.
//
//   node --test scripts/tests/bridge_cockpit_start_counts.test.mjs
//
// With Work through on, every number of the start page (the head line, a line of the areas, the page bar's count of
// the work tab) is what Work through shows under the same area filter: one count, read from flowParts, never a
// second rule beside it. Without Work through the start page keeps its own count (homeAreas).
import fs from 'node:fs'
import test from 'node:test'
import assert from 'node:assert/strict'
import { loadCockpit } from './cockpit_render.mjs'

const { logic } = await loadCockpit()

// a fixed local "now": Friday, 9 October 2026, noon (the same moment the other suites use)
const NOW = new Date(2026, 9, 9, 12, 0, 0).getTime()
const MIN = 60000

const task = (slug, over = {}) => ({ key: `task:${slug}`, task: slug, title: `Task ${slug}`, status: 'doing', bucket: 'tasks',
  priority: 'P2', settle: ['done', 'not_doing'], ...over })
const ask = (id, over = {}) => ({ key: `inbox:${id}`, inbox_id: id, title: `Question ${id}`, art: 'ask', inbox_state: 'open',
  bucket: 'do', gate: 'only-you', settle: ['done', 'not_doing'], ...over })

function state({ now = [], work = [], tabs = [], returns = [], sessions, ui = {}, flow = true } = {}) {
  return {
    now: NOW, model: { sections: [{ id: 'now', rows: now }, { id: 'give', rows: [] }, { id: 'work', rows: work },
      { id: 'track', rows: [] }, { id: 'later', rows: [] }], hidden: [], returns, briefing_badge: now.filter(logic.asksYou).length },
    tabs: { tabs }, driver: { caps: null }, triage: { items: {} }, jevOrder: {}, ...(sessions ? { sessions } : {}),
    work: { flow: { enabled: flow, drop_reasons: ['resolves_itself', 'not_needed'], return_after_s: 20 } },
    themes: { enabled: false },
    ui: { page: '@home', busy: {}, flowAt: null, flowChip: 'all', flowJump: null, flowView: 'overview', ...ui },
  }
}

// what Work through counts under an area (null: all), read the way the page reads it
function workSees(s, area) {
  const parts = logic.flowParts(logic.areaScope({ ...s, ui: { ...s.ui, page: '@flow', area } }))
  const you = parts.asks.length + parts.lost.length + parts.question.length + (parts.back ? 1 : 0)
  return { waiting: you, review: parts.result.length, running: logic.runningOf(parts).n,
    tasks: parts.task.length + parts.doing.length + parts.issue.length }
}
const figs = a => ({ waiting: a.waiting, review: a.review, running: a.running, tasks: a.tasks })

test('flowAreas: a row Work through holds under Not now does not wait on you on the start page', () => {
  const s = state({
    now: [
      task('blocked', { area_names: ['ACME'], urgency: 'today', blocked_by: 'waits for the customer' }),
      ask('20261009-0900-a-rest', { area_names: ['ACME'], bucket: 'resting' }),
      ask('20261009-0901-a-yes', { area_names: ['ACME'], inbox_state: 'approved' }),
      ask('20261009-0902-a-open', { area_names: ['ACME'] }),
    ],
  })
  // the old count took every ask of Now
  assert.equal(logic.homeAreas([], s.model.sections, [], NOW).find(a => a.name === 'ACME').waiting, 4)
  const { areas, all } = logic.flowAreas(s)
  assert.equal(areas.find(a => a.name === 'ACME').waiting, 1)
  assert.equal(all.waiting, 1)
  assert.equal(all.waitingRows, 1)
  assert.equal(logic.flowWaiting(s), 1)
})

test('flowAreas: every line is what Work through shows under that area, All what it shows unfiltered', () => {
  const s = state({
    now: [ask('20261009-0900-a-q', { area_names: ['ACME'] }), ask('20261009-0901-b-q', { area_names: ['Beta'] }),
      ask('20261009-0902-n-q')],
    work: [task('a1', { area_names: ['ACME'] }), task('b1', { area_names: ['Beta'] }), task('both', { area_names: ['ACME', 'Beta'] })],
    tabs: [{ ref: 'surface:1', name: 'acme', workspace: 'ACME', state: 'needs-you', since_ms: NOW - 5 * MIN },
      { ref: 'surface:2', name: 'beta', workspace: 'Beta', state: 'working', slug: 'b1', since_ms: NOW - 9 * MIN }],
    returns: [{ key: 'task:a1', item: 'a1', title: 'Task a1', mode: 'go', at_ms: NOW - 60 * MIN, stage: 'started', tab: { ref: 'surface:9' } }],
  })
  const { areas, all } = logic.flowAreas(s)
  for (const name of ['ACME', 'Beta']) assert.deepEqual(figs(areas.find(a => a.name === name)), workSees(s, name), name)
  assert.deepEqual(figs(all), workSees(s, null))
  // a row of two areas stands under both filters, so it counts in both lines (All counts it once)
  assert.equal(areas.find(a => a.name === 'ACME').tasks, 1)
  assert.equal(areas.find(a => a.name === 'Beta').tasks, 1)
  // what has no area stands in its own line
  assert.equal(areas.find(a => a.none).waiting, 1)
})

test('flowAreas: a tab answered here and a start that was lost count as Work through counts them', () => {
  const tab = { ref: 'surface:5', name: 'x', workspace: 'ACME', state: 'needs-you', since_ms: NOW - 3 * MIN, ask: { hash: 'h1' } }
  const lost = { key: 'task:gone', item: 'gone', title: 'Task gone', mode: 'go', at_ms: NOW - 60 * MIN, stage: 'started', tab: { ref: 'surface:9' } }
  const s = state({ work: [task('gone', { area_names: ['ACME'] })], tabs: [tab], returns: [lost] })
  const before = logic.flowAreas(s).areas.find(a => a.name === 'ACME')
  assert.equal(before.waiting, 2)
  assert.equal(before.waitingTabs, 1)
  const answered = { [tab.ref]: logic.answerMark(tab, 'Redirect', NOW) }
  const after = logic.flowAreas({ ...s, ui: { ...s.ui, answered } }).areas.find(a => a.name === 'ACME')
  assert.equal(after.waiting, 1)
  assert.equal(after.waitingTabs, 0)
})

test('flowAreas: running is the count of Running now, a finished (quiet) session not', () => {
  const tabs = [{ ref: 'surface:3', name: 'quiet', workspace: 'ACME', state: 'waiting', idle: true, since_ms: NOW - 30 * MIN },
    { ref: 'surface:4', name: 'busy', workspace: 'ACME', state: 'working', since_ms: NOW - 5 * MIN }]
  const sessions = { sessions: [{ id: 's1', sid: 's1', tab: { ref: 'surface:3' }, status: 'idle', started_ms: NOW - 40 * MIN },
    { id: 's2', sid: 's2', tab: { ref: 'surface:4' }, status: 'busy', started_ms: NOW - 6 * MIN }] }
  const s = state({ work: [task('a1', { area_names: ['ACME'] })], tabs, sessions })
  const acme = logic.flowAreas(s).areas.find(a => a.name === 'ACME')
  assert.equal(acme.running, logic.runningOf(logic.flowParts({ ...s, ui: { ...s.ui, page: '@flow' } })).n)
  assert.equal(acme.running, 1)
})

test('areaJump: with Work through on the numbers lead into it, without it as before', () => {
  const flow = { flow: true, waitingTabs: 1, waitingRows: 0 }
  assert.deepEqual(logic.areaJump('waiting', flow), { page: '@flow' })
  assert.deepEqual(logic.areaJump('waiting', { ...flow, waitingRows: 2 }), { page: '@flow' })
  assert.deepEqual(logic.areaJump('review', flow), { page: '@flow' })
  assert.deepEqual(logic.areaJump('overdue', flow), { page: '@flow' })
  assert.deepEqual(logic.areaJump('running', flow), { page: '@sessions' })
  assert.deepEqual(logic.areaJump('waiting', { waitingTabs: 1, waitingRows: 0 }), { page: '@chat', walk: true })
  assert.deepEqual(logic.areaJump('overdue', {}), { page: 'briefing', view: 'due' })
})

test('without Work through the start page keeps its own count', () => {
  const s = state({ flow: false, now: [ask('20261009-0900-a-q', { bucket: 'resting' })] })
  assert.equal(logic.flowWaiting(s), null)
})

test('the start page, its tiles and the page bar read the one count', () => {
  const home = fs.readFileSync(new URL('../web/views/home.js', import.meta.url), 'utf8')
  const header = fs.readFileSync(new URL('../web/views/header.js', import.meta.url), 'utf8')
  const stage = fs.readFileSync(new URL('../web/views/stage.js', import.meta.url), 'utf8')
  assert.ok(/flowAreas\(/.test(home))
  assert.ok(/flowWaiting\(s\)/.test(header))
  assert.ok(/startWaiting\(/.test(stage))
  assert.ok(/startWaiting\(/.test(home))
})

test('areaScope: Work through under an area holds no other area\'s task_rows or deferred items', () => {
  const s = state({ work: [task('a1', { area_names: ['ACME'] })] })
  s.model.task_rows = [task('b-closable', { area_names: ['Beta'], closable: true })]
  s.model.deferred = [ask('20261009-0905-b-later', { area_names: ['Beta'], inbox_state: 'deferred', until: '2026-11-01' })]
  const scoped = logic.areaScope({ ...s, ui: { ...s.ui, page: '@flow', area: 'ACME' } })
  assert.deepEqual(scoped.model.task_rows, [])
  assert.deepEqual(scoped.model.deferred, [])
  const acme = logic.flowAreas(s).areas.find(a => a.name === 'ACME')
  assert.equal(acme.tasks, 1)
  assert.ok(logic.flowAreas(s).areas.find(a => a.name === 'Beta'))
})

test('flowAreas: a question without an area that covers a task of an area is not counted under No area', () => {
  const s = state({ now: [ask('20261009-0900-x-q', { task: 'a1' })], work: [task('a1', { area_names: ['ACME'] })] })
  const { areas } = logic.flowAreas(s)
  assert.equal(areas.find(a => a.none), undefined)
})

test('flowAreas: the counts follow a tab within seconds, not a minute', () => {
  const tab = { ref: 'surface:5', name: 'x', workspace: 'ACME', state: 'needs-you', since_ms: NOW - 3 * MIN }
  const s = state({ tabs: [tab] })
  assert.equal(logic.flowAreas(s).all.waiting, 1)
  const later = { ...s, now: NOW + 10000, tabs: s.tabs }
  // same tabs object, ten seconds on: computed anew (the memo keys on a few seconds)
  assert.notEqual(logic.flowAreas(later), logic.flowAreas(s))
})

test('the overview of Work reads the start page\'s count', () => {
  const detail = fs.readFileSync(new URL('../web/views/detail.js', import.meta.url), 'utf8')
  assert.ok(/startWaiting\(s, s\.ui\.area\)/.test(detail))
})
