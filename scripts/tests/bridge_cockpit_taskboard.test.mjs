// SPDX-License-Identifier: MIT
// Tests of the taskboard (scripts/web/taskboard.js and views/taskboard.js), no npm dependencies.
//
//   node --test scripts/tests/bridge_cockpit_taskboard.test.mjs
//
// A `kind: tasks` section with `view: taskboard`: the column of each task by who has its next move, the tags of a
// card, the tidy-up rules and their seam, the tabs without a task, the one area filter, and the side panel with the
// verbs a task already has. The pure helpers come through logic.js, the view is mounted as the render suite mounts it.
import test from 'node:test'
import assert from 'node:assert/strict'
import { cockpitState, loadCockpit, mount, recorder, waitFor } from './cockpit_render.mjs'

const { html, views, text, logic } = await loadCockpit()
const en = text.TABLES.en
const de = text.TABLES.de

// a fixed local "now": Tuesday, 10 November 2026, noon
const NOW = new Date(2026, 10, 10, 12, 0, 0).getTime()

/** A task row of a page section as the server sends it (briefing_view.task_board under `board`) */
function task(slug, board = {}, over = {}) {
  return { index: 0, key: `item:tasks/board/${slug}`, title: `${slug}: the whole headline`, task: slug, state: 'doing', tone: null,
    detail: '', when: '', lines: [], tab: null,
    board: { lane: 'me', who: null, until: null, due: null, step: `step of ${slug}`, goal: null, stand: null, headline: null,
      area: 'Ops', stream: false, updated: '2026-11-09', ...board }, ...over }
}

const cardOf = (it, ctx = {}) => logic.tbCard(it, { now: NOW, ...ctx })

test('a task stands in the column of who has its next move; review and streams go apart', () => {
  assert.equal(logic.tbColumn(task('a')), 'me')
  assert.equal(logic.tbColumn(task('b', { lane: 'bridge' })), 'bridge')
  assert.equal(logic.tbColumn(task('c', { lane: 'waiting', who: 'Lior' })), 'waiting')
  assert.equal(logic.tbColumn(task('d', { lane: 'none', step: null })), 'me', 'no step: with you')
  assert.equal(logic.tbColumn(task('e', { lane: 'bridge' }, { state: 'review' })), 'review', 'review wins over the lane')
  assert.equal(logic.tbColumn(task('f', { stream: true }, { state: 'review' })), 'stream', 'a stream is in the band')
})

test('the board: a decision first in Me, waiting by its look-again day, streams in their band', () => {
  const decide = new Set(['late'])
  const items = [task('early'), task('backlog', {}, { state: 'backlog' }), task('late'),
    task('w2', { lane: 'waiting', who: 'Ana', until: '2026-11-20' }), task('w1', { lane: 'waiting', who: 'Ben', until: '2026-11-13' }),
    task('w0', { lane: 'waiting', who: 'Cy' }), task('s', { stream: true })]
  const board = logic.tbBoard(items.map(it => cardOf(it, { decide })))
  assert.deepEqual(board.columns.me.map(c => c.slug), ['late', 'early', 'backlog'])
  assert.deepEqual(board.columns.waiting.map(c => c.slug), ['w1', 'w2', 'w0'])
  assert.deepEqual(board.streams.map(c => c.slug), ['s'])
  assert.equal(board.columns.me[0].decide, true)
})

test('an open inbox decision tied to a task marks it; a put-off one or another kind does not', () => {
  const rows = [{ inbox_id: 'i1', task: 'a', inbox_kind: 'decision' }, { inbox_id: 'i2', task: 'b', inbox_kind: 'finding' },
    { inbox_id: 'i3', task: 'c', inbox_kind: 'decision', inbox_state: 'deferred' }, { task: 'd', inbox_kind: 'decision' }]
  assert.deepEqual([...logic.tbDecideSlugs(rows)], ['a'])
})

test('the tags of a card: area, tab, waiting on, look again, due (red within 30 days), an old step but not on a waiting card', () => {
  const kinds = c => c.tags.map(g => g.kind)
  const mine = cardOf(task('a', { due: '2026-11-30', updated: '2026-10-31' }), { decide: new Set(['a']) })
  assert.deepEqual(kinds(mine), ['decide', 'area', 'due', 'stepOld'])
  assert.equal(mine.tags.find(g => g.kind === 'due').soon, true)
  assert.equal(mine.tags.find(g => g.kind === 'stepOld').value, 10)
  const far = cardOf(task('b', { due: '2027-04-08' }))
  assert.equal(far.tags.find(g => g.kind === 'due').soon, false)
  const waiting = cardOf(task('c', { lane: 'waiting', who: 'Lior', until: '2026-11-17', updated: '2026-10-01' }))
  assert.deepEqual(kinds(waiting), ['area', 'waitingOn', 'lookAgain'])
  // a tab the server found on the row, else an open tab with the task's slug
  assert.equal(cardOf(task('d', {}, { tab: { ref: 'surface:4' } })).tab, 'surface:4')
  assert.equal(cardOf(task('e'), { tabs: [{ ref: 'surface:5', slug: 'e' }] }).tab, 'surface:5')
  assert.ok(kinds(cardOf(task('e'), { tabs: [{ ref: 'surface:5', slug: 'e' }] })).includes('tab'))
  // the short title is the topic before the colon; a short tag before a colon stays
  assert.equal(cardOf(task('f')).title, 'f: the whole headline')
  assert.equal(logic.tbTopic('Cockpit page: four columns'), 'Cockpit page')
  assert.equal(logic.tbTopic('Bug: it fails'), 'Bug: it fails')
  assert.equal(en.taskboard.tag.stepOld(10), 'Step 10 days old')
  assert.equal(de.taskboard.tag.lookAgain('2026-11-17'), 'nachsehen 17.11.')
})

test('tidy-up: no next step, a quiet backlog, an old step; streams and waiting tasks left alone; Keep hides one', () => {
  const cards = [
    task('none', { lane: 'none', step: null }), task('quiet', { updated: '2026-10-01' }, { state: 'backlog' }),
    task('fresh-backlog', { updated: '2026-11-01' }, { state: 'backlog' }), task('old', { updated: '2026-10-20' }),
    task('new', { updated: '2026-11-05' }), task('waits', { lane: 'waiting', who: 'Ana', updated: '2026-09-01' }),
    task('stream', { stream: true, lane: 'none', step: null }), task('judge', { updated: '2026-09-01' }, { state: 'review' }),
  ].map(it => cardOf(it))
  const rows = logic.tbTidy(cards)
  assert.deepEqual(rows.map(x => [x.slug, x.rule, x.verb]), [['none', 'noNext', 'shelve'], ['quiet', 'backlogQuiet', 'shelve'], ['old', 'stepOld', 'shelve']])
  assert.equal(rows[1].days, 40)
  const kept = new Set([logic.tbTidyId('stepOld', 'old')])
  assert.deepEqual(logic.tbTidy(cards, kept).map(x => x.slug), ['none', 'quiet'])
  // the seam for a later check: its rows for tasks no rule names, with their own verb; never a stream or an unknown verb
  const extra = [{ slug: 'new', rule: 'probablyDone', verb: 'close', why: 'PR merged', source: 'ai' }, { slug: 'none', verb: 'close' },
    { slug: 'stream', verb: 'close' }, { slug: 'judge', verb: 'delete' }]
  const more = logic.tbTidy(cards, new Set(), extra)
  assert.deepEqual(more.map(x => [x.slug, x.verb]), [['none', 'shelve'], ['quiet', 'shelve'], ['old', 'shelve'], ['new', 'close']])
  assert.equal(more.at(-1).why, 'PR merged')
})

test('tabs without a task: no slug, no item tied to a task, never the control tab or a bare shell', () => {
  const byKey = new Map([['inbox:i1', { task: 'a' }], ['inbox:i2', { task: null }]])
  const tabs = [{ ref: 's1', slug: 'a' }, { ref: 's2', slug: null, item: 'i1' }, { ref: 's3', slug: null, item: 'i2' },
    { ref: 's4', slug: null }, { ref: 's5', is_control: true }, { ref: 's6', state: 'shell' }]
  assert.deepEqual(logic.tbLooseTabs(tabs, byKey).map(t => t.ref), ['s3', 's4'])
})

// ---------------------------------------------------------------- the view

const section = items => ({ id: 'board', kind: 'tasks', view: 'taskboard', title: 'Tasks', status: 'ok', items, count: items.length, total: items.length })
const page = sec => ({ id: 'tasks', title: 'Tasks', sections: [sec] })
const state = (over = {}) => {
  const base = cockpitState(NOW)
  return { ...base, tabs: { ...base.tabs, tabs: over.tabs ?? [] }, ui: { ...base.ui, page: 'tasks', ...(over.ui ?? {}) } }
}

test('the page draws four columns, the band, both boxes; the area filter keeps one area, its tabs too', () => {
  const items = [task('ops-one'), task('home-one', { area: 'Home' }), task('ops-bridge', { lane: 'bridge' }),
    task('ops-stream', { stream: true }), task('home-review', { area: 'Home' }, { state: 'review' })]
  const sec = section(items)
  const tabs = [{ ref: 'surface:21', name: 'loose ops', workspace: 'Ops', state: 'waiting', slug: null }, { ref: 'surface:22', name: 'loose home', workspace: 'Home', state: 'waiting', slug: null }]
  const all = mount(html`<${views.pages.PageSection} page=${page(sec)} section=${sec} s=${state({ tabs })} c=${recorder()} />`)
  assert.deepEqual(all.$$('.tb-col-title').map(h => h.text().replace(/ \d+$/, '')), [en.taskboard.columns.me, en.taskboard.columns.bridge,
    en.taskboard.columns.waiting, en.taskboard.columns.review, en.taskboard.streams])
  assert.equal(all.$$('.tb-card').length, 5)
  assert.match(all.text(), new RegExp(en.taskboard.tidy))
  assert.equal(all.$$('.tb-list-row').filter(r => /loose/.test(r.text())).length, 2)
  const ops = mount(html`<${views.pages.PageSection} page=${page(sec)} section=${sec} s=${state({ tabs, ui: { area: 'Ops' } })} c=${recorder()} />`)
  assert.deepEqual(ops.$$('.tb-card-title').map(x => x.text()), ['ops-one', 'ops-bridge', 'ops-stream'])
  assert.deepEqual(ops.$$('.tb-list-row').filter(r => /loose/.test(r.text())).map(r => r.$('.tb-list-title').text()), ['loose ops'])
  assert.ok(logic.pageFollowsArea(page(sec)), 'the area bar stands over the page')
})

test('a card opens the side panel with goal, status and step, and its buttons send the existing verbs', async () => {
  const it = task('alpha', { goal: 'Ship it', stand: 'Half done', headline: 'Alpha: ship the release' })
  const sec = section([it])
  const c = recorder()
  const el = mount(html`<${views.pages.PageSection} page=${page(sec)} section=${sec} s=${state()} c=${c} />`)
  el.$('.tb-card').click()
  await waitFor(() => el.$('.tb-side'), { what: 'the panel opens' })
  const side = el.$('.tb-side')
  assert.match(side.text(), /Ship it/)
  assert.match(side.text(), /Half done/)
  assert.match(side.text(), /step of alpha/)
  side.button(en.taskboard.act.done).click()
  assert.deepEqual(c.calls.at(-1), ['act', 'task_close', { keys: ['task:alpha'], reason: 'done' }])
  await waitFor(() => !el.$('.tb-side'), { what: 'Done closes the panel' })
  el.$('.tb-card').click()
  await waitFor(() => el.$('.tb-side'), { what: 'the panel opens again' })
  el.$('.tb-side').button(en.taskboard.act.wait).click()
  assert.deepEqual(c.calls.at(-1), ['askRunsOn', [{ key: 'task:alpha', title: 'alpha: the whole headline' }]])
  el.$('.tb-side').button(en.taskboard.act.ai).click()
  assert.deepEqual(c.calls.at(-1), ['act', 'start_agent', { keys: ['task:alpha'] }])
  el.$('.tb-side').button(en.taskboard.act.openTab).click()
  assert.deepEqual(c.calls.at(-1), ['act', 'collect_context', { key: 'task:alpha' }])
  el.$('.tb-side').button(en.taskboard.act.shelve).click()
  assert.deepEqual(c.calls.at(-1), ['act', 'shelve', { key: 'task:alpha', reason: en.taskboard.shelveReason }])
})

test('a stream offers neither Done nor the idea list; a task with a tab offers Go to tab instead of Open a tab', async () => {
  const sec = section([task('weekly', { stream: true }), task('beta', {}, { tab: { ref: 'surface:7', state: 'working' } })])
  const el = mount(html`<${views.pages.PageSection} page=${page(sec)} section=${sec} s=${state()} c=${recorder()} />`)
  el.$$('.tb-card')[1].click()     // the band stands after the columns: beta first, weekly second
  await waitFor(() => el.$('.tb-side'), { what: 'the panel opens' })
  let side = el.$('.tb-side')
  assert.ok(!side.button(en.taskboard.act.done) && !side.button(en.taskboard.act.shelve))
  el.$$('.tb-card')[0].click()
  await waitFor(() => el.$('.tb-side .tb-side-title')?.text() === 'beta', { what: 'the panel shows beta' })
  side = el.$('.tb-side')
  assert.ok(side.button(en.taskboard.act.toTab) && !side.button(en.taskboard.act.openTab))
})

test('a tidy-up Yes runs its verb, Keep hides the row', async () => {
  const sec = section([task('quiet', { updated: '2026-09-01' }, { state: 'backlog' })])
  const c = recorder()
  const el = mount(html`<${views.pages.PageSection} page=${page(sec)} section=${sec} s=${state()} c=${c} />`)
  const row = el.$$('.tb-list-row').find(r => /quiet/.test(r.text()))
  assert.match(row.text(), new RegExp(en.taskboard.tidyVerb.shelve))
  row.button(en.taskboard.yes).click()
  assert.deepEqual(c.calls.at(-1), ['act', 'shelve', { key: 'task:quiet', reason: en.taskboard.shelveReason }])
  row.button(en.taskboard.keep).click()
  await waitFor(() => !el.$$('.tb-list-row').some(r => /quiet/.test(r.text())), { what: 'kept: gone from the box' })
})

test('a waiting tag keeps the start of a long reason', () => {
  const long = 'the appointment on 09.11. happened, the agent still sends a mail'
  const tag = cardOf(task('x', { lane: 'waiting', who: long })).tags.find(g => g.kind === 'waitingOn')
  assert.ok(tag.value.length <= logic.TB_WHO_MAX && tag.value.endsWith('…') && long.startsWith(tag.value.slice(0, -1)))
})

test('a waiting task whose look-again day has come stands with you again, says since when and who it waited on', () => {
  const kinds = c => c.tags.map(g => g.kind)
  const past = cardOf(task('p', { lane: 'waiting', who: 'Lior', until: '2026-10-26', updated: '2026-10-01' }))
  assert.equal(past.column, 'me')
  assert.equal(past.lookDue, true)
  assert.deepEqual(kinds(past), ['area', 'waitingOn', 'lookDue'], 'no old-step tag: it waited on purpose')
  assert.equal(past.tags.find(g => g.kind === 'lookDue').value, '2026-10-26')
  const today = cardOf(task('t', { lane: 'waiting', who: 'Ana', until: '2026-11-10' }))
  assert.equal(today.column, 'me', 'the look-again day itself counts')
  const ahead = cardOf(task('a', { lane: 'waiting', who: 'Ben', until: '2026-11-11' }))
  assert.equal(ahead.column, 'waiting')
  assert.equal(ahead.lookDue, false)
  const open = cardOf(task('o', { lane: 'waiting', who: 'Cy' }))
  assert.equal(open.column, 'waiting', 'no day: it keeps waiting')
  assert.equal(logic.tbTidy([past]).length, 0, 'a task back from waiting is no tidy-up case')
  assert.equal(de.taskboard.tag.lookDue('2026-10-26'), 'nachsehen fällig seit 26.10.')
})
