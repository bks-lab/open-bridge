// SPDX-License-Identifier: MIT
// Tests of the log page's time range (scripts/web/views/logrange.js, the helpers in logic.js), no npm dependencies.
//
//   node --max-old-space-size=1024 --test --test-timeout=60000 scripts/tests/bridge_cockpit_logrange.test.mjs
//
// The presets and the bar widths, buckets on the local calendar across a clock change, the rows of a range, the
// commits per repository; then the page as the router mounts it: the range panel between the search and the two
// columns, the chart, a click and a drag that zoom, Back, the log by day, the topics and the tiles that follow the
// range, and the three search modes.
import test from 'node:test'
import assert from 'node:assert/strict'
import { cockpitState, loadCockpit } from './cockpit_render.mjs'

const { logic } = await loadCockpit()

// a fixed local "now": Thursday, 29 October 2026, 14:30 (the Sunday before was the clock change in Europe)
const NOW = new Date(2026, 9, 29, 14, 30).getTime()
const at = (d, h = 0, m = 0, mo = 9) => new Date(2026, mo, d, h, m).getTime()

// ---------------------------------------------------------------- the pure helpers

test('the presets are calendar days of the local clock, All from the first day of the log', () => {
  const r = p => logic.rangeOf({ preset: p }, NOW, at(1, 9, 0, 2))
  assert.deepEqual(r('today'), { from: at(29), to: at(30), preset: 'today' })
  assert.deepEqual(r('yesterday'), { from: at(28), to: at(29), preset: 'yesterday' })
  assert.deepEqual(r('7d'), { from: at(23), to: at(30), preset: '7d' })
  assert.deepEqual(r('30d'), { from: at(30, 0, 0, 8), to: at(30), preset: '30d' })
  assert.deepEqual(r('all'), { from: at(1, 0, 0, 2), to: at(30), preset: 'all' })
  // without a first day All is today; a range of its own stays as it is
  assert.equal(logic.rangeOf({ preset: 'all' }, NOW).from, at(29))
  assert.deepEqual(logic.rangeOf({ from: at(29, 9), to: at(29, 12) }, NOW), { from: at(29, 9), to: at(29, 12), preset: null })
  assert.deepEqual(logic.RANGE_PRESETS, ['today', 'yesterday', '7d', '30d', 'all'])
})

test('the bar width a range takes on its own and the ones a person may choose', () => {
  const key = (f, t) => logic.rangeStepAuto(f, t).key
  assert.equal(key(at(29), at(30)), '30m')                 // 48 bars
  assert.equal(key(at(29, 9), at(29, 12)), '15m')          // 12 bars
  assert.equal(key(at(23), at(30)), '3h')                  // 56 bars
  assert.equal(key(at(30, 0, 0, 8), at(30)), '1d')         // 30 bars
  assert.equal(key(at(1, 0, 0, 0), at(30)), '1w')          // 302 days: more than the 240 day bars, so weeks
  assert.deepEqual(logic.rangeSteps(at(29), at(30)).map(s => s.key), ['15m', '30m', '1h', '3h', '6h', '12h', '1d'])
  assert.equal(logic.rangeStep(at(29), at(30), '1h').key, '1h')
  assert.equal(logic.rangeStep(at(29), at(30), '1w').key, '30m', 'a width wider than the range falls back to auto')
  assert.equal(logic.rangeStep(at(29), at(30), 'auto').key, '30m')
})

test('the bars stand on the local calendar: a day is a day across the clock change, a week starts on Monday', () => {
  const day = logic.RANGE_STEPS.find(s => s.key === '1d'), week = logic.RANGE_STEPS.find(s => s.key === '1w')
  const hour = logic.RANGE_STEPS.find(s => s.key === '1h')
  const edges = logic.rangeEdges(at(23), at(30), day)
  assert.deepEqual(edges, [23, 24, 25, 26, 27, 28, 29, 30].map(d => at(d)))
  // 25 October 2026 has 25 hours in Europe; here the bar still ends at the next midnight
  assert.equal(logic.stepNext(at(25), day), at(26))
  assert.equal(logic.stepFloor(at(29, 14, 30), week), at(26))
  assert.equal(logic.stepFloor(at(29, 14, 31), hour), at(29, 14))
  assert.equal(logic.stepFloor(at(29, 14, 31), logic.RANGE_STEPS[0]), at(29, 14, 30))
  assert.equal(logic.barOf(edges, at(29, 23, 59)), 6)
  assert.equal(logic.barOf(edges, at(30)), -1)
  assert.equal(logic.barOf(edges, at(22, 23)), -1)
})

test('rows count per bar, and per kind for the stacked chart', () => {
  const day = logic.RANGE_STEPS.find(s => s.key === '1d')
  const edges = logic.rangeEdges(at(27), at(30), day)
  const items = [{ ts: at(27, 9), kind: 'did' }, { ts: at(27, 10), kind: 'closed' }, { ts: at(29, 8), kind: 'did' }, { ts: at(30, 1), kind: 'did' }]
  assert.deepEqual(logic.rangeCounts(items, edges), [2, 0, 1])
  assert.deepEqual(logic.rangeCounts(items, edges, it => it.kind), { did: [1, 0, 1], closed: [1, 0, 0] })
})

test('the rows of a range newest first, from the compact answer of /api/logrange or from the section of today', () => {
  // the answer comes newest first, each row [day, time, group, glyph] by index, its id its offset plus its place
  const data = { offset: 40, rev: 'abcdef012345', days: ['2026-10-29', '2026-10-27'], glyphs: ['🔧', '📝'],
    groups: [{ name: 'billing', task: null, about_task: 'billing', about_path: null, kind: 'stream' },
      { name: 'docs', task: 'docs', about_task: null, about_path: null, kind: 'task' }],
    rows: [[0, '09:15', 0, 0], [1, '17:00', 1, 1]] }
  const rows = logic.logRangeRows(data)
  assert.deepEqual(rows.map(r => [r.day, r.when, r.id, r.index]), [['2026-10-27', '17:00', 41, 100041], ['2026-10-29', '09:15', 40, 100040]])
  assert.deepEqual({ ...rows[1], ts: 0, origin: null }, { index: 100040, id: 40, title: null, when: '09:15', glyph: '🔧', group: 'billing', detail: 'billing',
    tone: null, task: null, about_task: 'billing', about_path: null, work_kind: 'stream', day: '2026-10-29', ts: 0, origin: null })
  assert.equal(rows[1].origin.category, 'bridge')
  assert.deepEqual(logic.rangeSlice(rows, at(29), at(30)).map(r => r.id), [40])
  assert.deepEqual(logic.rangeSlice(rows, at(27), at(30)).map(r => r.id), [40, 41])
  // the section's rows of today: `at` where they carry it, else their time today; a row of another day stays out
  const today = logic.logTodayRows([{ index: 0, title: 'b', when: '13:42' }, { index: 1, title: 'a', when: '09:00', at: '2026-10-29T09:00' },
    { index: 2, title: 'old', when: 'Tue' }, { index: 3, title: 'yesterday', when: '23:00', at: '2026-10-28T23:00' }], NOW)
  assert.deepEqual(today.map(r => [r.title, r.ts]), [['a', at(29, 9)], ['b', at(29, 13, 42)]])
  assert.deepEqual(logic.logDays([...rows].reverse()).map(d => [d.key, d.rows.length]), [['2026-10-29', 1], ['2026-10-27', 1]])
  assert.equal(logic.rangeOneDay(at(29), at(30)), true)
  assert.equal(logic.rangeOneDay(at(28), at(30)), false)
})

test('the chart geometry: where a moment stands and which bar is under the pointer', () => {
  const edges = [at(29), at(29, 12), at(30)]
  const g = logic.chartGeometry(edges, 248)
  assert.equal(g.x(at(29)), 38)
  assert.equal(g.x(at(30)), 238)
  assert.equal(g.barAt(10), 0)
  assert.equal(g.barAt(139), 1)
  assert.equal(g.barAt(400), 1)
  assert.deepEqual([1, 4, 5, 7, 12, 30, 240].map(logic.niceMax), [1, 4, 5, 10, 20, 50, 250])
})

test('the axis labels: hours on a day, midnight named, days on a week, dates on a month', () => {
  const day = logic.rangeTicks([at(29), at(30)], 900, 'de')
  assert.ok(day.some(t => t.label === '12:00'))
  assert.deepEqual(day.filter(t => t.mid).map(t => t.label), ['Do 29.10.', 'Fr 30.10.'])
  const week = logic.rangeTicks([at(23), at(30)], 900, 'de')
  assert.deepEqual(week.slice(0, 2).map(t => t.label), ['Fr 23.', 'Sa 24.'])
  const month = logic.rangeTicks([at(30, 0, 0, 8), at(30)], 900, 'de')
  assert.ok(month.every(t => /^\d{2}\.\d{2}\.$/.test(t.label)))
  assert.equal(logic.rangeDay(at(29), 'de'), 'Do 29.10.2026')
  assert.equal(logic.rangeDay(at(29), 'en', false), 'Thu 29 Oct')
  assert.equal(logic.shortDay(at(29), 'de'), '29.10.')
})

test('the own commits of a range per repository, the busiest first, a sparkline over the range', () => {
  const s = ms => Math.floor(ms / 1000)
  const repos = [{ repo: 'example/tools', branch: 'dev', url: 'https://example.org/tools', ts: [s(at(29, 9))] },
    { repo: 'example/app', branch: 'main', url: 'javascript:x', ts: [s(at(23, 9)), s(at(29, 10)), s(at(29, 11))] },
    { repo: 'example/quiet', branch: 'main', url: null, ts: [s(at(20, 9))] }]
  const got = logic.repoRange(repos, at(29), at(30), 4)
  assert.deepEqual(got, [{ repo: 'example/app', branch: 'main', url: null, n: 2, spark: [0, 2, 0, 0] },
    { repo: 'example/tools', branch: 'dev', url: 'https://example.org/tools', n: 1, spark: [0, 1, 0, 0] }])
  assert.equal(logic.repoBusy(repos[2], at(23), at(30)), false)
  assert.equal(logic.repoBusy(repos[1], at(23), at(30)), true)
})

// ---------------------------------------------------------------- the page, mounted through the router

const { html, components, text } = await loadCockpit()
const { mount, recorder } = await import('./cockpit_render.mjs')
const en = text.TABLES.en, de = text.TABLES.de
const tick = () => new Promise(resolve => setTimeout(resolve, 20))
const sec = ms => Math.floor(ms / 1000)

const TODAY_ROWS = [
  { index: 0, title: 'Gateway retry moved to the night run', when: '13:42', at: '2026-10-29T13:42', glyph: '🔧', group: 'billing', tone: null, detail: 'billing' },
  { index: 1, title: 'Docs index checked and the links repaired', when: '13:05', at: '2026-10-29T13:05', glyph: '📝', group: 'docs', tone: null, detail: 'docs' },
  { index: 2, title: 'Invoice export renamed', when: '09:15', at: '2026-10-29T09:15', glyph: '✅', group: 'billing', tone: null, detail: 'billing' }]
const REPOS = [
  { index: 0, title: 'example/app', when: '3 today', detail: '▁▂▂▅▂▁█ main', tone: null, link: { kind: 'web', href: 'https://github.com/example/app/commits' } }]
const PAGE = { id: 'day', title: 'Daily log', search: true, sections: [
  { id: 'activity', kind: 'activity', view: 'log', title: 'Log today', status: 'ok', alarm: false, empty: 'no line yet', count: 3, total: 3, items: TODAY_ROWS },
  { id: 'commits', kind: 'commits', place: 'rail', title: 'Repos, 7 days', status: 'ok', alarm: false, empty: 'none', count: 1, total: 1, items: REPOS }] }

// what /api/logrange answered for the last 30 days: today's three rows, and some on the days before, as the server packs
// them (rows without their text, the text by id from logText)
const row = (date, time, group, title, glyph = 'x') => ({ date, time, glyph, group, title })
const ROWS = [row('2026-10-29', '13:42', 'billing', 'Gateway retry moved to the night run', '🔧'), row('2026-10-29', '13:05', 'docs', 'Docs index checked and the links repaired', '📝'),
  row('2026-10-29', '09:15', 'billing', 'Invoice export renamed', '✅'), row('2026-10-28', '16:00', 'release', 'Release notes drafted'),
  row('2026-10-27', '10:30', 'billing', 'Gateway retry planned'), row('2026-10-27', '08:00', 'ops', 'Disk cleaned'), row('2026-10-20', '11:00', 'docs', 'Guide outlined')]
const REV = '0123456789ab'
function pack(rows, tasks = {}) {
  const days = [], groups = [], glyphs = [], at = (list, v, entry = v) => { let i = list.findIndex(x => (x.name ?? x) === v); if (i < 0) { i = list.length; list.push(entry) } return i }
  const packed = rows.map(r => [at(days, r.date), r.time, at(groups, r.group, { name: r.group, task: tasks[r.group] ?? null, about_task: null, about_path: null,
    kind: tasks[r.group] ? 'task' : null }), at(glyphs, r.glyph)])
  return { rev: REV, offset: 0, total: rows.length, days, groups, glyphs, rows: packed }
}
const TEXTS = { rev: REV, texts: Object.fromEntries(ROWS.map((r, i) => [String(i), r.title])) }
const RANGE = { ok: true, from: '2026-09-30', to: '2026-10-29', first: '2026-03-17', today: '2026-10-29', repos_from: '2026-09-30', skipped: [], ...pack(ROWS),
  repos: [
    { repo: 'example/app', branch: 'main', url: 'https://github.com/example/app/commits/main', ts: [sec(at(29, 9)), sec(at(29, 10)), sec(at(27, 9))] },
    { repo: 'example/tools', branch: 'dev', url: null, ts: [sec(at(28, 15))] },
    ...['a', 'b', 'c', 'd', 'e', 'f'].map((x, i) => ({ repo: `example/${x}`, branch: 'main', url: null, ts: [sec(at(29, 8 + i))] }))] }
/** The ids the server would find for some words: every word in the text or the context */
const hitsOf = q => ({ q, rev: REV, status: 'ok', ids: ROWS.flatMap((r, i) => (q.toLowerCase().split(/\s+/).every(w => `${r.title} ${r.group}`.toLowerCase().includes(w)) ? [i] : [])) })

function state(over = {}) {
  const s = cockpitState(NOW)
  s.model = { ...s.model, pages: [PAGE] }
  s.ui = { ...s.ui, page: PAGE.id }
  s.jev = { ...s.jev, enabled: false }
  return { ...s, ...over }
}
const loaded = (over = {}) => state({ logRange: { from: '2026-09-30', to: '2026-10-29', status: 'ok', data: RANGE, error: null }, logText: TEXTS, ...over })
const page = (s, c = recorder()) => mount(html`<${components.PageView} s=${s} c=${c} />`)
const preset = (el, label) => el.$$('.logr-presets button').find(b => b.text() === label)
const radio = (el, label) => el.$$('.psearch-seg button').find(b => b.text() === label)
async function type(el, value) {
  const box = el.$('.psearch input')
  box.value = value
  box.dispatch('input')
  await tick()
}
/** A pointer at the middle of bar i of the chart as it is drawn (the test DOM has no layout: 720 px wide) */
function barX(el, i) {
  const bars = el.$$('.logr-chart rect.logr-bar')
  const b = bars.find(r => r.getAttribute('data-i') === String(i))
  return Number(b.getAttribute('x')) + Number(b.getAttribute('width')) / 2
}
function point(el, type, x) { el.$('.logr-chart').dispatch(type, { clientX: x, button: 0, pointerId: 1 }) }

test('the range panel stands between the search and the two columns, Today by default, from the section before the range answers', async () => {
  const c = recorder()
  const el = page(state(), c)
  const all = n => n.childNodes.filter(x => x.nodeType === 1).flatMap(x => [x, ...all(x)])
  const order = ['psearch-bar', 'logr', 'logp-grid'].map(cls => all(el).findIndex(n => n.hasClass(cls)))
  assert.ok(order.every(i => i >= 0) && order[0] < order[1] && order[1] < order[2], String(order))
  assert.deepEqual(el.$$('.logr-presets button').map(b => b.text()), ['Today', 'Yesterday', '7 days', '30 days', 'All'])
  assert.equal(preset(el, 'Today').getAttribute('aria-pressed'), 'true')
  assert.equal(el.$('.logr-label').text(), 'Thu 29 Oct 2026, whole day')
  assert.equal(el.$('.logr-count').text(), en.logRange.lines(3))
  assert.ok(!el.$('.logr-back'), 'no Back before a second range')
  // 30 minute bars on a day, the three rows in three bars; the hatched rest of the day and the line of now
  assert.equal(el.$$('.logr-chart rect.logr-bar').length, 3)
  assert.ok(el.$('.logr-chart .logr-now'))
  assert.ok(el.$('.logr-chart .logr-future'))
  // the range of today is asked for once the page stands, with the rail's commits section
  await tick()
  assert.deepEqual(c.calls.filter(x => x[0] === 'loadLogRange'), [['loadLogRange', { from: '2026-10-29', to: '2026-10-29', commits: 'commits' }]])
  // mouse first: no key named anywhere on the panel
  assert.doesNotMatch(el.$('.logr').text(), /\b(Shift|Ctrl|Alt|Enter|key|Taste)\b/i)
})

test('a preset picks its range, Back returns to the one before; the list stands under its days with an only-this-day button', async () => {
  const c = recorder()
  const el = page(loaded(), c)
  preset(el, '7 days').click()
  await tick()
  assert.equal(el.$('.logr-label').text(), 'Fri 23 Oct to Thu 29 Oct 2026')
  assert.equal(el.$('.logr-count').text(), en.logRange.lines(6))
  assert.equal(c.calls.filter(x => x[0] === 'loadLogRange').length, 0, 'the 30 days answered already hold 7 days')
  const heads = el.$$('.logp-main .logv-dayhead')
  assert.deepEqual(heads.map(h => h.$('.logv-day').text()), ['Thu 29 Oct 2026', 'Wed 28 Oct 2026', 'Tue 27 Oct 2026'])
  assert.equal(heads[0].$('.logv-daycount').text(), en.logPage.dayCount(3))
  assert.match(el.$('.logp-main .sec-title').text(), new RegExp(en.logPage.inRange))
  // only this day: that day by the hour
  heads[2].button(en.logPage.onlyDay).click()
  await tick()
  assert.equal(el.$('.logr-label').text(), 'Tue 27 Oct 2026, whole day')
  assert.deepEqual(el.$$('.logp-main .logv-head').map(h => h.text()), ['10:00', '08:00'])
  el.$('.logr-back').click()
  await tick()
  assert.equal(el.$('.logr-label').text(), 'Fri 23 Oct to Thu 29 Oct 2026')
  el.$('.logr-back').click()
  await tick()
  assert.equal(preset(el, 'Today').getAttribute('aria-pressed'), 'true')
  assert.ok(!el.$('.logr-back'))
  // a range the answer does not hold is asked for
  preset(el, 'All').click()
  await tick()
  assert.deepEqual(c.calls.filter(x => x[0] === 'loadLogRange').at(-1), ['loadLogRange', { from: null, to: '2026-10-29', commits: 'commits' }])
})

test('a click on a bar zooms into it, a drag zooms into the bars it covers, hovering names the bar, its count and its contexts', async () => {
  const el = page(loaded())
  preset(el, '7 days').click()
  await tick()
  // 3 hour bars over seven days: the bar of 29 October 12:00 to 15:00 holds two rows
  const i = barOf(el, at(29, 12))
  point(el, 'pointermove', barX(el, i))
  await tick()
  const tip = el.$('.logr-tip').text()
  assert.match(tip, /Thu 29 Oct, 12:00 to 15:00/)
  assert.match(tip, /2 lines/)
  assert.match(tip, /billing 1 · docs 1|docs 1 · billing 1/)
  point(el, 'pointerdown', barX(el, i))
  point(el, 'pointerup', barX(el, i))
  await tick()
  assert.equal(el.$('.logr-label').text(), 'Thu 29 Oct 2026, 12:00 to 15:00')
  assert.equal(el.$$('.logp-main .logv-row').length, 2)
  // back to the week, then a drag from 27 October 06:00 over to 28 October 18:00
  el.$('.logr-back').click()
  await tick()
  point(el, 'pointerdown', barX(el, barOf(el, at(27, 6))) - 1)
  point(el, 'pointermove', barX(el, barOf(el, at(28, 15))) + 1)
  await tick()
  assert.ok(el.$('.logr-chart .logr-sel'), 'the selection stands while dragging')
  point(el, 'pointerup', barX(el, barOf(el, at(28, 15))) + 1)
  await tick()
  assert.equal(el.$('.logr-label').text(), 'Tue 27 Oct 06:00 to Wed 28 Oct 18:00')
  assert.deepEqual(el.$$('.logp-main .logv-row').map(r => r.$('.logv-time').text()), ['16:00', '10:30', '08:00'])
})

/** The bar a moment falls in, by the data-i the chart writes and the edges it names */
function barOf(el, ms) {
  const edges = el.$('.logr-chart').getAttribute('data-edges').split(',').map(Number)
  return logic.barOf(edges, ms)
}

test('a row of an earlier day opens as a row of today does: its day in the detail, the log as its origin, the file of its task', async () => {
  const c = recorder()
  const rows = { ...RANGE, ...pack(ROWS, { release: 'release-notes' }) }
  const el = page(loaded({ logRange: { from: '2026-09-30', to: '2026-10-29', status: 'ok', data: rows, error: null } }), c)
  preset(el, 'Yesterday').click()
  await tick()
  const row = el.$('.logp-main .logv-row')
  assert.ok(row.$('.logv-file'), 'a row of a task carries the file mark')
  row.$('.logv-btn').click()
  await tick()
  el.$('.logp-main .logv-row').button(en.logPage.openFile).click()
  el.$('.logp-main .logv-row').button(en.logPage.open).click()
  assert.deepEqual(c.calls.find(x => x[0] === 'openFile'), ['openFile', 'release-notes', null])
  const [, it, pageId, sectionId] = c.calls.find(x => x[0] === 'openInfo')
  // the detail names the day and the time, and where the row comes from: the work log of this Bridge
  assert.deepEqual([it.title, it.when, pageId, sectionId], ['Release notes drafted', 'Wed 28 Oct 2026, 16:00', 'day', 'activity'])
  const { OriginTag } = (await loadCockpit()).views.day
  const tag = mount(html`<${OriginTag} row=${logic.itemRow(it)} />`)
  assert.match(tag.text(), new RegExp(`${en.origin.bridge}.*${en.logPage.origin}`))
  assert.doesNotMatch(tag.text(), new RegExp(en.originUnknown))
})

test('the list asks for the text of the rows it draws only, and draws them once they come', async () => {
  const c = recorder()
  const el = page(loaded({ logText: null }), c)
  preset(el, '7 days').click()
  await tick()
  assert.equal(el.$$('.logp-main .logv-row').length, 6)
  assert.ok(el.$('.logp-main .logv-row .logv-wait'), 'a row without its text yet says so')
  await tick()
  assert.deepEqual(c.calls.filter(x => x[0] === 'loadLogText').at(-1), ['loadLogText', { rev: REV, ids: [0, 1, 2, 3, 4, 5] }])
})

test('the bar width: automatic by default, any width that fits to choose', async () => {
  const el = page(loaded())
  const select = el.$('.logr-step select')
  assert.deepEqual(select.$$('option').map(o => o.value ?? o.getAttribute('value')), ['auto', '15m', '30m', '1h', '3h', '6h', '12h', '1d'])
  assert.equal(select.$$('option')[0].text(), en.logRange.auto(en.logRange.step['30m']))
  select.value = '1h'
  select.dispatch('change')
  await tick()
  assert.equal(el.$('.logr-chart').getAttribute('data-edges').split(',').length, 25)
})

test('In range filters the rows of the range as one types, the chart then shows only the hits; the topics and the tiles follow the range', async () => {
  const c = recorder()
  let el = page(loaded(), c)
  assert.equal(radio(el, en.pageSearch.mode.range).getAttribute('aria-checked'), 'true')
  preset(el, '7 days').click()
  await tick()
  // topics: the contexts of the range
  assert.deepEqual(el.$$('.logp-rail .fchip').map(b => b.text()), ['billing 3', 'docs 1', 'ops 1', 'release 1'])
  // tiles: own commits in the range, at most six, the rest in one line
  const tiles = el.$$('.logp-rail .logp-tile')
  assert.equal(tiles.length, 6)
  assert.equal(tiles[0].$('.logp-name').text(), 'example/app')
  assert.equal(tiles[0].$('.logp-big').text(), '3 commits')
  assert.match(el.$('.logp-rail .logp-quiet').text(), /example\/f 1/)
  // the words are found on the server (the rows came without their text); its hits filter the rows, the chart and the topics
  await type(el, 'gateway')
  assert.equal(el.$('.logr-count').text(), en.logRange.searching)
  await new Promise(r => setTimeout(r, 400))
  assert.deepEqual(c.calls.filter(x => x[0] === 'loadLogHits').at(-1), ['loadLogHits', { q: 'gateway', rev: REV, from: '2026-09-30', to: '2026-10-29' }])
  el = page(loaded({ logHits: hitsOf('gateway') }), c)
  preset(el, '7 days').click()
  await tick()
  await type(el, 'gateway')
  assert.equal(el.$('.logr-count').text(), en.logRange.hits(2, 6))
  assert.equal(el.$$('.logp-main .logv-row').length, 2)
  assert.equal(el.$$('.logr-chart rect.logr-bar').length, 2)
  assert.deepEqual(el.$$('.logp-rail .fchip').map(b => b.text()), ['billing 2'])
  // Today: the tiles count today, the repositories busy in the week but quiet today in one line
  preset(el, 'Today').click()
  await tick()
  assert.equal(el.$$('.logp-rail .logp-tile')[0].$('.logp-big').text(), '2 today')
  assert.match(el.$('.logp-rail .logp-quiet').text(), /example\/tools/)
})

test('Every day switches to All, its chart stacks the log rows with the meetings, closed tasks and transcripts, a legend names them', async () => {
  const c = recorder()
  const events = { q: '', status: 'ok', error: null, data: { ok: true, from: null, to: '2026-10-29', transcripts: true, events: [
    { date: '2026-10-28', time: '10:00', kind: 'discussed', source: 'Weekly round', path: 'x', folder: null },
    { date: '2026-10-26', time: null, kind: 'closed', source: 'old-export', path: 'y', folder: 'work/done/2026-10/old-export' },
    { date: '2026-10-21', time: '16:49', kind: 'transcript', source: 'vendor-call', path: 'z', folder: null }] } }
  const all = { ...RANGE, from: '2026-03-17' }
  const el = page(loaded({ logRange: { from: null, to: '2026-10-29', status: 'ok', data: all, error: null }, logEvents: events }), c)
  radio(el, en.pageSearch.mode.all).click()
  await tick()
  assert.equal(preset(el, 'All').getAttribute('aria-pressed'), 'true')
  const kinds = new Set(el.$$('.logr-chart rect.logr-bar').map(r => r.getAttribute('data-kind')))
  assert.deepEqual([...kinds].sort(), ['closed', 'did', 'discussed', 'transcript'])
  assert.deepEqual(el.$$('.logr-key').map(k => k.text()), ['did', 'discussed', 'closed', 'transcript'].map(k => en.logRange.kinds[k]))
  // the history follows the range: a search asks with the days of the range
  await type(el, 'gateway retry')
  await new Promise(r => setTimeout(r, 500))
  assert.deepEqual(c.calls.filter(x => x[0] === 'searchTimeline').at(-1), ['searchTimeline', 'gateway retry', { from: null, to: '2026-10-29' }])
  // the chart counts the entries that hold the words: asked for once the typing pauses; all of them stood loaded before
  assert.deepEqual(c.calls.filter(x => x[0] === 'loadLogEvents'), [['loadLogEvents', 'gateway retry']])
  assert.deepEqual(c.calls.filter(x => x[0] === 'loadLogHits').at(-1), ['loadLogHits', { q: 'gateway retry', rev: REV, from: null, to: '2026-10-29' }])
})

test('Ask AI asks within the range', async () => {
  const c = recorder()
  const s = loaded()
  s.work = { ...s.work, files_search: { enabled: true, block: [], left: 5 } }
  const el = page(s, c)
  preset(el, '7 days').click()
  await tick()
  radio(el, en.pageSearch.mode.ai).click()
  await type(el, 'when did the retry move')
  el.$('form.psearch-bar').dispatch('submit')
  assert.deepEqual(c.calls.find(x => x[0] === 'askTimeline'), ['askTimeline', 'when did the retry move', { from: '2026-10-23', to: '2026-10-29' }])
})

test('the head of the page sums up the range', async () => {
  const el = page(loaded())
  preset(el, '7 days').click()
  await tick()
  assert.equal(el.$('.logp-sum').text(), en.logPage.summaryRange(6, 4, 10, 8))
})

test('the time range speaks every language; German with umlauts and without dashes', () => {
  for (const [lang, table] of Object.entries(text.TABLES)) {
    const w = table.logRange
    assert.ok(w && w.back && w.barsPer && w.hint && w.now, lang)
    assert.deepEqual(Object.keys(w.preset), logic.RANGE_PRESETS, lang)
    assert.deepEqual(Object.keys(w.step), logic.RANGE_STEPS.map(st => st.key), lang)
    assert.deepEqual(Object.keys(w.kinds), ['did', 'discussed', 'closed', 'transcript'], lang)
    assert.ok(table.pageSearch.mode.range && table.pageSearch.placeholder.range && table.logPage.inRange && table.logPage.onlyDay, lang)
  }
  assert.equal(de.pageSearch.mode.range, 'Im Zeitraum')
  assert.equal(de.pageSearch.mode.all, 'Alle Tage')
  const said = JSON.stringify(de.logRange) + de.logRange.lines(2) + de.logRange.hits(1, 3) + de.logPage.summaryRange(1, 1, 1, 1)
  assert.doesNotMatch(said, /[—–]/)
})
