// SPDX-License-Identifier: MIT
// Render tests of the item card (scripts/web/views/card.js), no npm dependencies.
//
//   node --test scripts/tests/bridge_cockpit_card.test.mjs
//
// Every item reaches the page with one `card` (card.py) and, for a task, stream or inbox item, the describe view
// beside it (describe.py state_for). ItemCard draws it in a detail head, ItemCardLine as the sub line of a list
// row: the goal first, the story as one sentence, the acceptance criteria as a list to read (never to tick), the
// next step, chips, progress and the gaps as quiet hints. Text a model wrote and nobody edited carries "AI". The
// describe button asks for a brief; a proposal is applied, edited or discarded right there.
import test from 'node:test'
import assert from 'node:assert/strict'
import { cockpitState, loadCockpit, mount, recorder } from './cockpit_render.mjs'

const { html, views, text, logic } = await loadCockpit()
const en = text.TABLES.en
const de = text.TABLES.de
const { ItemCard, ItemCardLine } = views.card

const NOW = new Date(2026, 9, 9, 12, 0, 0).getTime()
const tick = () => new Promise(r => setTimeout(r, 10))

const proto = Object.getPrototypeOf(document.body)
proto.focus ??= function focus() { document.activeElement = this }
proto.getBoundingClientRect ??= () => ({ left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0 })
proto.scrollTo ??= () => {}
// a drawer moves the focus into itself after it mounts, which this small DOM has no selector engine for
proto.querySelector ??= () => null
globalThis.window ??= { innerWidth: 1280, innerHeight: 800, addEventListener() {}, removeEventListener() {} }

const STORY = { as: 'a new team member', want: 'a guide for the demo setup', so_that: 'I am ready in an hour' }
const TASK = {
  kind: 'task', subkind: null, title: 'Write the onboarding guide', summary: 'As a new team member, I want a guide for the demo setup, so that I am ready in an hour.',
  goal: 'A new member sets up the demo project in under an hour', story: STORY,
  acceptance: ['Every step is written down', 'Two colleagues tried it'],
  next: { what: 'Draft the first two chapters', who: 'me', due: '2026-10-12', from: 'status', since: '2026-10-08' },
  state: { word: 'doing', blocked_by: null, since: null }, owner: 'me', priority: 'P1', due: '2026-10-12', area: 'Demo',
  updated: '2026-10-08', source: null, links: [{ kind: 'task', key: 'demo-task', label: 'Write the onboarding guide', closed: false }],
  progress: { done: 2, total: 5 }, written: 'ai', gaps: [],
}
const AI = { written: 'ai', stale: false, running: false, last_error: null, warnings: [], model_mismatch: false, proposal: null,
  by: 'claude-haiku-5-5', at: '2026-10-08' }
const s0 = (over = {}) => cockpitState(NOW, over)

/** A controller that records like recorder() and answers act() the way the server would */
function answering(answer = { ok: true }) {
  const calls = []
  return new Proxy({}, { get: (_, p) => (p === 'calls' ? calls : p === 'then' || typeof p === 'symbol' ? undefined
    : (...a) => { calls.push([p, ...a]); return Promise.resolve(answer) }) })
}
const acts = c => c.calls.filter(x => x[0] === 'act').map(x => [x[1], x[2]])

// ---------------------------------------------------------------- what a card shows, per kind

test('card: a task shows its goal first, the story as one sentence, the criteria as a list and the next step', () => {
  const el = mount(html`<${ItemCard} card=${TASK} d=${AI} dkey="task:demo-task" s=${s0()} c=${recorder()} />`)
  assert.equal(el.$('.card-goal-text').text(), TASK.goal)
  assert.equal(el.$('.card-story').text(), en.card.storyLine(STORY.as, STORY.want, STORY.so_that))
  assert.deepEqual(el.$$('.card-criteria li').map(li => li.text()), TASK.acceptance)
  assert.ok(el.$('.card-next').text().includes('Draft the first two chapters'))
  assert.ok(el.$('.card-next').text().includes(en.card.who.me), 'who takes the step')
  assert.ok(el.$('.card-progress').text().includes(en.card.steps(2, 5)))
  const chips = el.$('.card-chips').text()
  assert.ok(chips.includes(en.taskState.doing) && chips.includes('P1') && chips.includes('Demo') && chips.includes(en.card.owner.me))
  // the summary is the story here: it is said once
  assert.equal(el.$('.card-summary'), null)
})

test('card: the acceptance criteria are read, never ticked: the steps checklist stays the only thing to tick', () => {
  const el = mount(html`<${ItemCard} card=${TASK} d=${AI} dkey="task:demo-task" s=${s0()} c=${recorder()} />`)
  assert.equal(el.$$('.card input').length, 0, 'no input in the card')
  assert.equal(el.$$('.card-criteria [type="checkbox"]').length, 0)
  assert.equal(el.$$('.card-criteria li').length, 2)
})

test('card: an inbox item shows its summary and next step; a check stays compact, empty parts draw nothing', () => {
  const inbox = { ...TASK, kind: 'inbox', subkind: 'decision', title: 'Review the demo report', goal: null, story: null,
    acceptance: null, summary: 'The report of the demo check is ready to read.', progress: null,
    next: { what: 'decide', who: 'me', due: null, from: 'item', since: null }, state: { word: 'open', blocked_by: null, since: null },
    owner: 'me', priority: null, area: null, due: null, gaps: [], written: 'item' }
  const el = mount(html`<${ItemCard} card=${inbox} dkey="inbox:x" s=${s0()} c=${recorder()} />`)
  assert.equal(el.$('.card-summary').text(), inbox.summary)
  assert.ok(el.$('.card-chips').text().includes(en.item.stateName.open))
  assert.equal(el.$('.card-goal'), null)
  assert.equal(el.$('.card-criteria'), null)
  const check = { kind: 'check', subkind: null, title: 'Disk space', summary: null, goal: null, story: null, acceptance: null,
    next: null, state: { word: 'ok', blocked_by: null, since: null }, owner: null, priority: null, due: null, area: null,
    updated: null, source: null, links: [], progress: null, written: 'title', gaps: [] }
  const small = mount(html`<${ItemCard} card=${check} s=${s0()} c=${recorder()} />`)
  for (const sel of ['.card-summary', '.card-goal', '.card-story', '.card-criteria', '.card-next', '.card-progress', '.card-gaps', '.card-describe']) {
    assert.equal(small.$(sel), null, sel)
  }
  assert.equal(mount(html`<${ItemCard} card=${null} s=${s0()} c=${recorder()} />`).text(), '')
})

test('card: the title shows only where asked, and parts the head already shows can be left out', () => {
  const el = mount(html`<${ItemCard} card=${TASK} d=${AI} dkey="task:demo-task" s=${s0()} c=${recorder()} title skip=${['priority', 'next']} />`)
  assert.equal(el.$('.card-title').text(), TASK.title)
  assert.ok(!el.$('.card-chips').text().includes('P1'))
  assert.equal(el.$('.card-next'), null)
  assert.equal(mount(html`<${ItemCard} card=${TASK} s=${s0()} c=${recorder()} />`).$('.card-title'), null)
})

// ---------------------------------------------------------------- who wrote it

test('card: text a model wrote and nobody edited carries "AI" with the model and the day on hover', () => {
  const el = mount(html`<${ItemCard} card=${TASK} d=${AI} dkey="task:demo-task" s=${s0()} c=${recorder()} />`)
  const mark = el.$('.ai-mark')
  assert.equal(mark.text(), en.card.ai)
  assert.equal(mark.getAttribute('title'), en.card.aiBy('claude-haiku-5-5', logic.formatDay('2026-10-08', 'en', true)))
  const human = mount(html`<${ItemCard} card=${{ ...TASK, written: 'human' }} d=${{ ...AI, written: 'human' }} dkey="task:demo-task" s=${s0()} c=${recorder()} />`)
  assert.equal(human.$('.ai-mark'), null, 'a person edited it: no mark')
})

test('card: a brief the item has changed past says "outdated"', () => {
  const el = mount(html`<${ItemCard} card=${TASK} d=${{ ...AI, stale: true }} dkey="task:demo-task" s=${s0()} c=${recorder()} />`)
  assert.equal(el.$('.card-stale').text(), en.card.stale)
  assert.equal(el.$('.card-stale').getAttribute('title'), en.card.staleHint)
  assert.equal(mount(html`<${ItemCard} card=${TASK} d=${AI} dkey="task:demo-task" s=${s0()} c=${recorder()} />`).$('.card-stale'), null)
})

// ---------------------------------------------------------------- gaps

test('card: gaps are quiet hints; an entry about a closed task offers to close it', async () => {
  const card = { ...TASK, kind: 'inbox', subkind: 'result', goal: null, story: null, acceptance: null,
    gaps: ['no_goal', 'placeholder_next', 'task_closed'] }
  const c = answering()
  const el = mount(html`<${ItemCard} card=${card} dkey="inbox:20261009-0940-filed-board-c2d3" s=${s0()} c=${c} />`)
  const hints = el.$('.card-gaps').text()
  for (const g of ['no_goal', 'placeholder_next', 'task_closed']) assert.ok(hints.includes(en.card.gap[g]), g)
  el.$('.card-gaps').button(en.card.closeEntry).click()
  await tick()
  assert.deepEqual(acts(c), [['settle', { keys: ['inbox:20261009-0940-filed-board-c2d3'], outcome: 'done' }]])
  // a task has no such entry to close
  const own = mount(html`<${ItemCard} card=${{ ...TASK, gaps: ['no_goal'] }} dkey="task:demo-task" s=${s0()} c=${recorder()} />`)
  assert.equal(own.$('.card-gaps').button(en.card.closeEntry), null)
})

// ---------------------------------------------------------------- describe with AI

test('card: "Describe with AI" asks for a brief of the item and is busy while it runs', async () => {
  const c = answering({ ok: true, describe: AI })
  const el = mount(html`<${ItemCard} card=${{ ...TASK, goal: null, story: null, acceptance: null, gaps: ['no_goal'] }} dkey="task:demo-task" s=${s0()} c=${c} />`)
  el.$('.card-describe').button(en.card.describe).click()
  await tick()
  assert.deepEqual(acts(c), [['describe_run', { key: 'task:demo-task' }]])
  const busy = mount(html`<${ItemCard} card=${TASK} d=${AI} dkey="task:demo-task" s=${s0({ ui: { busy: { 'task:demo-task': 'describe_run' } } })} c=${recorder()} />`)
  assert.ok(busy.$('.card-describe button').hasAttribute('disabled'))
  const running = mount(html`<${ItemCard} card=${TASK} d=${{ ...AI, running: true }} dkey="task:demo-task" s=${s0()} c=${recorder()} />`)
  assert.ok(running.$('.card-describe button').hasAttribute('disabled'))
  assert.ok(running.$('.card-describe').text().includes(en.card.running))
  // only a task, stream or inbox item can be described
  const gh = mount(html`<${ItemCard} card=${{ ...TASK, kind: 'github' }} dkey="ref:x" s=${s0()} c=${recorder()} />`)
  assert.equal(gh.$('.card-describe'), null)
  assert.equal(mount(html`<${ItemCard} card=${TASK} s=${s0()} c=${recorder()} />`).$('.card-describe'), null, 'no key, no button')
})

const PROPOSAL = { id: 'd0123456789', by: 'claude-haiku-5-5', at_ms: NOW,
  brief: { goal: 'A proposed goal for the guide', story: { as: 'a lead', want: 'one page to send', so_that: 'nobody asks twice' },
    acceptance: ['The page is linked from the README'] } }
const HUMAN = { ...AI, written: 'human', proposal: PROPOSAL }

test('card: a proposal shows beside the text a person wrote, with Apply and Discard', async () => {
  const c = answering()
  const el = mount(html`<${ItemCard} card=${{ ...TASK, written: 'human' }} d=${HUMAN} dkey="task:demo-task" s=${s0()} c=${c} />`)
  const box = el.$('.card-proposal')
  assert.ok(box.text().includes(PROPOSAL.brief.goal) && box.text().includes(en.card.proposal))
  assert.equal(el.$('.card-goal-text').text(), TASK.goal, 'the stored brief stays what the card says')
  box.button(en.card.apply).click()
  await tick()
  box.button(en.card.discard).click()
  await tick()
  assert.deepEqual(acts(c), [['describe_apply', { key: 'task:demo-task', proposal: PROPOSAL.id }],
    ['describe_discard', { key: 'task:demo-task', proposal: PROPOSAL.id }]])
})

test('card: Edit opens a small form of the proposal; Save applies it as the person changed it', async () => {
  const c = answering()
  const el = mount(html`<${ItemCard} card=${{ ...TASK, written: 'human' }} d=${HUMAN} dkey="task:demo-task" s=${s0()} c=${c} />`)
  el.$('.card-proposal').button(en.card.edit).click()
  await tick()
  const form = el.$('form.card-edit')
  assert.ok(form, 'the form')
  const field = name => form.$(`[name="${name}"]`)
  assert.equal(form.$$('.card-edit-crit').length, 5, 'up to five criteria')
  field('goal').value = 'My own goal for the guide'
  field('goal').dispatch('input')
  field('acceptance1').value = 'A second criterion'
  field('acceptance1').dispatch('input')
  await tick()
  form.dispatch('submit')
  await tick()
  assert.deepEqual(acts(c), [['describe_apply', { key: 'task:demo-task', proposal: PROPOSAL.id, brief: {
    goal: 'My own goal for the guide', story: PROPOSAL.brief.story,
    acceptance: ['The page is linked from the README', 'A second criterion'] } }]])
})

test('card: a story with a part left empty is sent as no story; a stream keeps no criteria', async () => {
  const c = answering()
  const el = mount(html`<${ItemCard} card=${{ ...TASK, kind: 'stream', written: 'human' }} d=${HUMAN} dkey="task:team-onboarding" s=${s0()} c=${c} />`)
  el.$('.card-proposal').button(en.card.edit).click()
  await tick()
  const form = el.$('form.card-edit')
  assert.equal(form.$$('.card-edit-crit').length, 0, 'a stream has no criteria')
  form.$('[name="so_that"]').value = ''
  form.$('[name="so_that"]').dispatch('input')
  await tick()
  form.dispatch('submit')
  await tick()
  assert.deepEqual(acts(c), [['describe_apply', { key: 'task:team-onboarding', proposal: PROPOSAL.id,
    brief: { goal: PROPOSAL.brief.goal, acceptance: [] } }]])
})

test('card: German words come from the text module, with native umlauts', () => {
  assert.equal(de.card.describe, 'AI beschreiben')
  assert.equal(de.card.apply, 'Übernehmen')
  assert.equal(de.card.gap.task_closed, 'Aufgabe schon geschlossen')
  assert.equal(de.card.storyLine('Kundin', 'eine Rechnung', 'ich zahlen kann'), 'Als Kundin möchte ich eine Rechnung, damit ich zahlen kann.')
  assert.deepEqual(Object.keys(de.card).sort(), Object.keys(en.card).sort())
})

// ---------------------------------------------------------------- the list line

test('card line: a list row says its goal under the title when it has one, else nothing', () => {
  assert.equal(mount(html`<${ItemCardLine} card=${TASK} />`).$('.card-line').text(), TASK.goal)
  assert.equal(mount(html`<${ItemCardLine} card=${{ ...TASK, goal: null }} />`).text(), '')
  assert.equal(mount(html`<${ItemCardLine} card=${null} />`).text(), '')
})

// ---------------------------------------------------------------- the same item everywhere

test('card: the demo task has the same title in the list, the drawer and the files view, with its goal', async () => {
  const s = s0({ ui: { page: 'briefing', workView: 'dossier', selectedKey: 'task:demo-task', queue: null } })
  const row = logic.indexRows(s.model).get('task:demo-task')
  assert.ok(row.card?.goal, 'the demo gives the task a brief')
  const title = row.card.title
  // the list
  const list = mount(html`<${views.day.Section} section=${s.model.sections.find(x => x.id === 'work')} s=${s} c=${recorder()} byKey=${logic.indexRows(s.model)} />`)
  const line = list.$$('li.row').find(li => li.getAttribute('data-key') === 'task:demo-task')
  assert.equal(line.$('.row-title').text(), title)
  // the detail column
  const detail = mount(html`<${views.detail.DetailColumn} s=${s} c=${recorder()} byKey=${logic.indexRows(s.model)} />`)
  assert.equal(detail.$('.detail-title').text(), title)
  assert.equal(detail.$('.card-goal-text').text(), row.card.goal)
  // the drawer, its detail loaded with a headline that differs from the title
  const loaded = { ...s, details: { inbox: {}, task: { 'demo-task': { status: 'ok', at: s.model.collected_ms, data: {
    ok: true, slug: 'demo-task', front: { headline: 'Some other headline' }, sections: [], card: row.card } } } },
    ui: { ...s.ui, item: { key: 'task:demo-task', it: { task: 'demo-task', title: 'demo-task' } } } }
  const drawer = mount(html`<${views.overlays.ItemDrawer} s=${loaded} c=${recorder()} byKey=${logic.indexRows(s.model)} />`)
  await tick()
  assert.equal(drawer.$('.idrawer-title').text(), title)
  assert.ok(drawer.$('.card-goal-text'), 'the card in the drawer')
  // the files view, opened on the demo task
  const queue = views.dossier.dossierQueue(s)
  const k = queue.findIndex(x => x.slug === 'demo-task')
  assert.ok(k >= 0, 'the demo task is a file')
  const file = mount(html`<${views.dossier.DossierView} s=${{ ...s, ui: { ...s.ui, dossierAt: { id: queue[k].id, i: k } } }} c=${recorder()} />`)
  assert.equal(file.$('.dz-title').text(), title)
  assert.equal(file.$('.card-goal-text').text(), row.card.goal)
})

test('card: the demo shows the four ways a brief stands: AI written, edited with a proposal, outdated, with gaps', () => {
  const s = s0()
  const byKey = logic.indexRows(s.model)
  const rows = [...byKey.values()]
  assert.ok(rows.some(r => r.describe?.written === 'ai' && !r.describe.stale), 'one written by AI')
  assert.ok(rows.some(r => r.describe?.written === 'human' && r.describe.proposal), 'one edited, with a proposal')
  assert.ok(rows.some(r => r.describe?.stale), 'one outdated')
  assert.ok(rows.some(r => (r.card?.gaps ?? []).length >= 2), 'one with gaps')
  assert.ok(rows.every(r => r.card && typeof r.card === 'object'), 'every row carries a card')
})

test('card line: a list row without a triage gist shows its goal under the title, on Today and on the start page', () => {
  const s = s0({ triage: { items: {}, last: null, running: null } })
  const byKey = logic.indexRows(s.model)
  const row = byKey.get('task:docs-refresh')
  const list = mount(html`<${views.day.Section} section=${{ ...s.model.sections.find(x => x.id === 'work'), compact: ['task:docs-refresh'] }} s=${s} c=${recorder()} byKey=${byKey} />`)
  const line = list.$$('li.row').find(li => li.getAttribute('data-key') === 'task:docs-refresh')
  assert.equal(line.$('.card-line').text(), row.card.goal)
  // a row without a goal gets no line
  const quiet = list.$$('li.row').find(li => li.getAttribute('data-key') === 'task:old-cleanup')
  if (quiet) assert.equal(quiet.$('.card-line'), null)
})

// ---------------------------------------------------------------- the demo answers the describe verbs

test('demo: describe writes a brief for an item nobody wrote, proposes for an edited one, applies and discards', async () => {
  const { mock } = await loadCockpit()
  const tr = mock.createMockTransport({ lang: 'en', latency: 0 })
  const events = []
  tr.events(new Proxy({}, { get: (_, name) => p => events.push([name, p]) }), () => {})
  const act = (verb, args) => tr.post('/api/action', { verb, args })
  const rowOf = async key => logic.indexRows((await tr.get('/api/state')).data.model).get(key)
  const written = (await act('describe_run', { key: 'task:old-cleanup' })).data
  assert.equal(written.outcome, 'written')
  assert.equal(written.describe.written, 'ai')
  const after = await rowOf('task:old-cleanup')
  assert.ok(after.card.goal && !after.card.gaps.includes('no_goal'), 'the card has its goal now')
  const proposed = (await act('describe_run', { key: 'task:docs-refresh' })).data
  assert.equal(proposed.outcome, 'proposal')
  const id = proposed.describe.proposal.id
  assert.equal((await rowOf('task:docs-refresh')).card.goal, 'Readers find every docs page from one index', 'the person\'s text stays')
  const applied = (await act('describe_apply', { key: 'task:docs-refresh', proposal: id, brief: { goal: 'My own goal', acceptance: ['One'] } })).data
  assert.equal(applied.describe.written, 'human')
  assert.equal(applied.describe.proposal, null)
  assert.equal((await rowOf('task:docs-refresh')).card.goal, 'My own goal')
  assert.equal((await act('describe_discard', { key: 'task:docs-refresh', proposal: id })).error.code, 'stale_proposal')
  await new Promise(r => setTimeout(r, 120))
  assert.ok(events.some(([name, p]) => name === 'describe' && p.key === 'task:docs-refresh'), 'the page hears it')
  // the details carry the card and describe view of their row
  const detail = (await tr.get('/api/task?slug=docs-refresh')).data
  assert.equal(detail.card.goal, 'My own goal')
  assert.equal(detail.describe.written, 'human')
})

// ---------------------------------------------------------------- review fixes

const { render } = await loadCockpit()
const count = (hay, needle) => hay.split(needle).length - 1

test('card: a proposal that fills a card without a valid brief stands once, in the proposal with Apply', () => {
  // the stored brief failed the gate (or there is none): card.py fills the card from the proposal as "ai"
  const filled = { ...TASK, written: 'ai', goal: PROPOSAL.brief.goal, story: PROPOSAL.brief.story, acceptance: PROPOSAL.brief.acceptance }
  for (const written of ['human', null]) {
    const el = mount(html`<${ItemCard} card=${filled} d=${{ ...AI, written, proposal: PROPOSAL }} dkey="task:demo-task" s=${s0()} c=${recorder()} />`)
    assert.equal(count(el.text(), PROPOSAL.brief.goal), 1, `the goal once (${written})`)
    assert.ok(el.$('.card-goal-text') === null, 'the card does not pass the proposal off as its brief')
    assert.ok(el.$('.card-proposal').button(en.card.apply), 'the proposal keeps Apply')
  }
})

test('card: a new proposal while the form is open starts the form afresh, never with the old text', async () => {
  const root = document.createElement('div')
  const draw = prop => render(html`<${ItemCard} card=${{ ...TASK, written: 'human' }} d=${{ ...HUMAN, proposal: prop }}
    dkey="task:demo-task" s=${s0()} c=${answering()} />`, root)
  draw(PROPOSAL)
  root.$('.card-proposal').button(en.card.edit).click()
  await tick()
  assert.ok(root.$('form.card-edit'))
  const next = { ...PROPOSAL, id: 'd9876543210', brief: { ...PROPOSAL.brief, goal: 'A newer proposed goal' } }
  draw(next)
  await tick()
  assert.ok(root.$('form.card-edit') === null, 'the form of the old proposal is gone')
  assert.ok(root.$('.card-proposal').text().includes('A newer proposed goal'))
  render(null, root)
})

test('card: the AI mark says its model and day to a screen reader too, not only on hover', () => {
  const el = mount(html`<${ItemCard} card=${{ ...TASK, written: 'human' }} d=${{ ...AI, proposal: PROPOSAL }} dkey="task:demo-task" s=${s0()} c=${recorder()} />`)
  for (const mark of el.$$('.ai-mark')) {
    assert.equal(mark.getAttribute('role'), 'img')
    assert.equal(mark.getAttribute('aria-label'), mark.getAttribute('title'))
  }
  assert.equal(el.$$('.ai-mark').length, 2, 'the brief and the proposal')
})

test('card: the focus goes to the form on Edit and back to the describe button after Apply; the state is announced', async () => {
  const c = answering()
  const el = mount(html`<${ItemCard} card=${{ ...TASK, written: 'human' }} d=${HUMAN} dkey="task:demo-task" s=${s0()} c=${c} />`)
  el.$('.card-proposal').button(en.card.edit).click()
  await tick()
  assert.ok(document.activeElement === el.$('form.card-edit').$('[name="goal"]'), 'the first field of the form')
  el.$('form.card-edit').dispatch('submit')
  await tick()
  assert.ok(document.activeElement === el.$('.card-describe button'), 'the describe button')
  const discard = mount(html`<${ItemCard} card=${{ ...TASK, written: 'human' }} d=${HUMAN} dkey="task:demo-task" s=${s0()} c=${answering()} />`)
  discard.$('.card-proposal').button(en.card.discard).click()
  await tick()
  assert.ok(document.activeElement === discard.$('.card-describe button'), 'the describe button after Discard')
  const running = mount(html`<${ItemCard} card=${TASK} d=${{ ...AI, running: true }} dkey="task:demo-task" s=${s0()} c=${recorder()} />`)
  assert.equal(running.$('.card-describe [role="status"]').text(), en.card.running)
  const failed = mount(html`<${ItemCard} card=${TASK} d=${{ ...AI, last_error: 'no answer' }} dkey="task:demo-task" s=${s0()} c=${recorder()} />`)
  assert.equal(failed.$('.card-describe [role="alert"]').text(), en.card.lastError('no answer'))
})

test('card: the describe button waits while any describe runs, since the server runs one at a time', () => {
  const card = html`<${ItemCard} card=${TASK} d=${AI} dkey="task:demo-task" s=${null} c=${recorder()} />`
  const of = s => mount({ ...card, props: { ...card.props, s } }).$('.card-describe button').hasAttribute('disabled')
  assert.equal(of(s0()), false)
  assert.equal(of(s0({ describe: { 'inbox:x': { key: 'inbox:x', running: true } } })), true, 'a live run of another item')
  assert.equal(of(s0({ ui: { busy: { 'inbox:x': 'describe_run' } } })), true, 'an action of another card')
  assert.equal(of(s0({ ui: { busy: { 'inbox:x': 'settle' } } })), false, 'another verb does not count')
  const base = s0()
  const model = { ...base.model, sections: base.model.sections.map((sec, i) => (i ? sec : { ...sec,
    rows: sec.rows.map((r, j) => (j ? r : { ...r, describe: { ...AI, running: true } })) })) }
  assert.equal(of({ ...base, model }), true, 'a run the model carries on another row')
})

test('logic: a new model keeps the live describe views of keys it carries no row of', () => {
  const s = s0()
  const live = { 'task:demo-task': { running: true }, 'inbox:not-in-the-model': { running: true } }
  assert.deepEqual(Object.keys(logic.liveDescribeAfter(live, s.model)), ['inbox:not-in-the-model'])
  assert.deepEqual(logic.liveDescribeAfter(undefined, s.model), {})
})

test('card: a list row shows the card title, the one the drawer and the files view show', () => {
  const base = s0()
  const model = { ...base.model, sections: base.model.sections.map(sec => ({ ...sec,
    rows: sec.rows.map(r => (r.key === 'task:demo-task' ? { ...r, title: 'demo-task' } : r)) })) }
  const s = { ...base, model }
  const byKey = logic.indexRows(model)
  const list = mount(html`<${views.day.Section} section=${model.sections.find(x => x.id === 'work')} s=${s} c=${recorder()} byKey=${byKey} />`)
  const line = list.$$('li.row').find(li => li.getAttribute('data-key') === 'task:demo-task')
  assert.equal(line.$('.row-title').text(), byKey.get('task:demo-task').card.title)
  assert.notEqual(byKey.get('task:demo-task').card.title, 'demo-task')
})

test('card: a detail head leaves out the chips the facts below it already say', async () => {
  const s = s0({ ui: { page: 'briefing', selectedKey: 'task:demo-task' } })
  const byKey = logic.indexRows(s.model)
  const row = byKey.get('task:demo-task')
  const detail = mount(html`<${views.detail.DetailColumn} s=${s} c=${recorder()} byKey=${byKey} />`)
  const chips = detail.$('.detail-card .card-chips')?.text() ?? ''
  assert.ok(!chips.includes(row.area), 'the area stands in the facts')
  assert.ok(!chips.includes(en.taskState.doing), 'the state stands in the task facts')
  // the drawer of a task: its facts list says the state and the priority
  const loaded = { ...s, details: { inbox: {}, task: { 'demo-task': { status: 'ok', at: s.model.collected_ms, data: {
    ok: true, slug: 'demo-task', front: { status: 'doing', priority: 'P1' }, sections: [], card: row.card } } } },
    ui: { ...s.ui, item: { key: 'task:demo-task', it: { task: 'demo-task', title: 'demo-task' } } } }
  const drawer = mount(html`<${views.overlays.ItemDrawer} s=${loaded} c=${recorder()} byKey=${byKey} />`)
  await tick()
  const dchips = drawer.$('.idrawer-card .card-chips')?.text() ?? ''
  assert.ok(!dchips.includes(en.taskState.doing) && !dchips.includes('P1'))
  assert.ok(drawer.$('.idrawer-facts').text().includes(en.taskState.doing))
})

// ---------------------------------------------------------------- references in the brief (brief_refs.py, card.py brief_refs)

const GH = 'https://github.com/acme/app/issues/95'
const REFS_TASK = {
  ...TASK, goal: 'Every gap of work/tasks/demo-task/gaps.md is closed',
  acceptance: ['All gaps of acme/app#95 are closed', 'Bericht §6 is answered', 'spec-gap stays closed', 'Nothing to point at'],
  brief_refs: {
    goal: [{ text: 'Every gap of ' }, { text: 'work/tasks/demo-task/gaps.md', ref: { kind: 'file', path: 'work/tasks/demo-task/gaps.md' } },
      { text: ' is closed' }],
    story: null,
    acceptance: [
      [{ text: 'All gaps of ' }, { text: 'acme/app#95', ref: { kind: 'web', href: GH } }, { text: ' are closed' }],
      [{ text: 'Bericht ' }, { text: '§6', unresolved: true }, { text: ' is answered' }],
      [{ text: 'spec-gap', ref: { kind: 'task', key: 'spec-gap', folder: null } }, { text: ' stays closed' }],
      null,
    ],
  },
  gaps: ['unresolved_ref'],
}

test('card: a reference on GitHub is a link that opens in a new tab, never a link back into the page', () => {
  const el = mount(html`<${ItemCard} card=${REFS_TASK} d=${AI} dkey="task:demo-task" s=${s0()} c=${recorder()} />`)
  const [first] = el.$$('.card-criteria li')
  assert.equal(first.text(), 'All gaps of acme/app#95 are closed')
  const a = first.$('a')
  assert.equal(a.getAttribute('href'), GH)
  assert.equal(a.getAttribute('target'), '_blank')
  assert.ok(a.getAttribute('rel').split(' ').includes('noopener'))
  assert.equal(el.$$('.card-criteria li')[3].text(), 'Nothing to point at', 'a criterion without a reference stays text')
})

test('card: a reference a reader cannot reach stands as text with a quiet hint, and the gap says so', () => {
  const el = mount(html`<${ItemCard} card=${REFS_TASK} d=${AI} dkey="task:demo-task" s=${s0()} c=${recorder()} />`)
  const item = el.$$('.card-criteria li')[1]
  const missing = item.$('.card-ref-missing')
  assert.ok(missing.text().startsWith('§6'))
  assert.equal(missing.getAttribute('title'), en.card.refMissing)
  assert.ok(item.text().includes(en.card.refMissing), 'said to a screen reader too')
  assert.equal(item.$$('a').length + item.$$('button').length, 0)
  assert.ok(el.$('.card-gaps').text().includes(en.card.gap.unresolved_ref))
})

test('card: a task slug opens the task and a file of a task folder is read in place, through the files view openers', async () => {
  const c = answering({ ok: true, data: { text: '# Gaps\n\nNone left.', cut: false } })
  const el = mount(html`<${ItemCard} card=${REFS_TASK} d=${AI} dkey="task:demo-task" s=${s0()} c=${c} />`)
  el.$$('.card-criteria li')[2].$('button').click()
  assert.deepEqual(c.calls.find(x => x[0] === 'openFile'), ['openFile', 'spec-gap', null])
  el.$('.card-goal-text').$('button').click()
  assert.deepEqual(c.calls.find(x => x[0] === 'taskFile'), ['taskFile', 'demo-task', 'gaps.md', null])
  await tick()
  assert.ok(el.$('.card-ref-file').text().includes('None left.'))
  el.$('.card-goal-text').$('button').click()
  await tick()
  assert.equal(el.$('.card-ref-file'), null, 'a second click closes it')
})

test('card: a path outside a task folder is shown with a copy button; German hints come from the text module', () => {
  const card = { ...REFS_TASK, brief_refs: { goal: [{ text: 'docs/mapping.md', ref: { kind: 'file', path: 'docs/mapping.md' } },
    { text: ' lists every field' }], story: null, acceptance: [] } }
  const c = recorder()
  const el = mount(html`<${ItemCard} card=${card} d=${AI} dkey="task:demo-task" s=${s0()} c=${c} />`)
  assert.equal(el.$('.card-goal-text code').text(), 'docs/mapping.md')
  el.$('.card-goal-text').button(en.copyPath).click()
  assert.deepEqual(c.calls.find(x => x[0] === 'copy'), ['copy', 'docs/mapping.md'])
  assert.equal(de.card.refMissing, 'nicht auffindbar')
  assert.ok(de.card.gap.unresolved_ref.length > 0 && Object.keys(de.card.staleWhy).join() === Object.keys(en.card.staleWhy).join())
})

test('card: "outdated" says why: the text moved on, an older prompt, a reference to try again', () => {
  for (const why of ['basis', 'prompt', 'refs']) {
    const el = mount(html`<${ItemCard} card=${TASK} d=${{ ...AI, stale: true, stale_why: why }} dkey="task:demo-task" s=${s0()} c=${recorder()} />`)
    assert.equal(el.$('.card-stale').getAttribute('title'), en.card.staleWhy[why])
  }
})

test('card: the demo has a criterion with a link and one with a reference nobody can reach', () => {
  const rows = [...logic.indexRows(s0().model).values()]
  const parts = rows.flatMap(r => r.card?.brief_refs?.acceptance ?? []).filter(Boolean).flat()
  assert.ok(parts.some(p => p.ref?.kind === 'web'), 'a linked criterion')
  assert.ok(parts.some(p => p.unresolved), 'an unresolved one')
  assert.ok(rows.some(r => (r.card?.gaps ?? []).includes('unresolved_ref')))
})
