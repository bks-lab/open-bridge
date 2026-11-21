// SPDX-License-Identifier: MIT
// Tests of Work through by the briefing's buckets (cockpit.flow.buckets): scripts/web/buckets.js and
// views/flowbuckets.js, no npm dependencies.
//
//   node --test scripts/tests/bridge_cockpit_buckets.test.mjs
//
// Every point stands in one bucket of the briefing profile, named and ordered as the profile says; a card says one
// next sentence and offers its bucket's answers, the first one the Bridge taking the next step, each the same act as
// the briefing's answer; everything else stands under More; the card names its number in the printed briefing.
import test from 'node:test'
import assert from 'node:assert/strict'
import { loadCockpit, mount, recorder, settle as rounds } from './cockpit_render.mjs'

const { html, views, text, logic } = await loadCockpit()
const { FlowPage } = views.flow
const { PointCard } = views.flowpoint
const en = text.TABLES.en.flow.buckets

// a fixed local "now": Friday, 9 October 2026, noon (as the other suites)
const NOW = new Date(2026, 9, 9, 12, 0, 0).getTime()
const MIN = 60000
const TOMORROW = '2026-10-10'

// a German profile's words (view.buckets), in its order
const PROFILE = [
  { id: 'do', title: 'Tun (du, heute)', options: ['ja', 'später', 'streichen'] },
  { id: 'plan', title: 'Planen', options: ['einplanen', 'später'] },
  { id: 'delegate', title: 'Mache ich', options: ['los', 'nicht jetzt'] },
  { id: 'waiting', title: 'Wartet auf andere', options: ['nachfassen', 'warten'] },
  { id: 'drop', title: 'Parken oder streichen', options: ['parken', 'behalten'] },
]

const task = (slug, over = {}) => ({ key: `task:${slug}`, task: slug, title: `Task ${slug}`, status: 'doing', bucket: 'plan',
  priority: 'P2', settle: ['done', 'not_doing'], ...over })
const ask = (id, over = {}) => ({ key: `inbox:${id}`, inbox_id: id, title: `Question ${id}`, art: 'ask', inbox_state: 'open',
  bucket: 'do', gate: 'your-yes', settle: ['done', 'not_doing'], ...over })

function state({ now = [], work = [], later = [], tabs = [], buckets = PROFILE, on = true, ui = {}, ...rest } = {}) {
  return {
    now: NOW, model: { sections: [{ id: 'now', rows: now }, { id: 'give', rows: [] }, { id: 'work', rows: work },
      { id: 'track', rows: [] }, { id: 'later', rows: later }], hidden: [], returns: [], buckets },
    tabs: { tabs, at_ms: NOW }, driver: { caps: null }, triage: { items: {} }, jevOrder: {},
    work: { flow: { enabled: true, drop_reasons: ['resolves_itself', 'not_needed'], return_after_s: 20, buckets: { enabled: on } } },
    themes: { enabled: false },
    ui: { page: '@flow', busy: {}, flowAt: null, flowChip: 'all', flowJump: null, flowView: 'overview', ...ui }, ...rest,
  }
}

// a tab that asks, its input line holds the answer ready (#702, tab_accept)
const asking = {
  ref: 'surface:9', name: 'Contact import', state: 'waiting', since_ms: NOW - 5 * MIN, workspace: 'Home',
  ask: { text: 'I noted the new address for the next mails.\nAda Smith is not in Contacts yet.\nShall I try again?',
    hash: 'h1', draft: true, suggestion: 'yes, try the contact again' },
}

const answersOf = (x, bucket, s) => logic.bucketAnswers(x, bucket, s, 'en')
const row = r => ({ group: 'question', id: r.key, kind: 'row', row: r })

// ---------------------------------------------------------------- the question of a tab (#702's follow-up)

test('askQuestion: the last sentence that asks, with the one before it where it is short, else the last line', () => {
  assert.equal(logic.askQuestion(asking.ask.text), 'Ada Smith is not in Contacts yet. Shall I try again?')
  assert.equal(logic.askQuestion('Done the build.\nTests are green. Shall I open the PR? Or wait'), 'Tests are green. Shall I open the PR?')
  // a terminal wraps a sentence over lines: the question is read whole, a list mark starts a new one
  assert.equal(logic.askQuestion('- Contacts did not answer in time, so Ada Smith is not saved yet. Shall I\ntry again?'),
    'Contacts did not answer in time, so Ada Smith is not saved yet. Shall I try again?')
  assert.equal(logic.askQuestion('Is this long enough to stand alone without the line before it, I wonder?'),
    'Is this long enough to stand alone without the line before it, I wonder?')
  assert.equal(logic.askQuestion('first line\nsecond line'), 'second line')
  assert.equal(logic.askQuestion(''), '')
})

test('the card of a tab that asks shows the question itself, not the first line of its screen', () => {
  const s = state({ tabs: [asking] })
  const el = mount(html`<${PointCard} x=${{ group: 'asks', id: 'tab:surface:9', kind: 'tab', tab: asking, row: null }} s=${s} c=${recorder()} />`)
  assert.match(el.text(), /Shall I try again\?/)
  assert.doesNotMatch(el.$('.fx-sub')?.text() ?? '', /new address/)
})

// ---------------------------------------------------------------- every point in one bucket

test('bucketPoints: every point once, in the bucket the briefing put it, the profile naming and ordering them', () => {
  const s = state({
    now: [ask('20261009-0900-q1', { brief_nr: 2 }), ask('20261009-0901-q2', { brief_nr: 1 })],
    work: [task('mine', { status: 'review' }), task('bridges', { status: 'review', bucket: 'delegate' }),
      task('blocked', { status: 'review', bucket: 'tasks', blocked_by: 'Ada' }), task('quiet', { status: 'review', bucket: 'drop' })],
    tabs: [asking],
  })
  const { buckets, all } = logic.bucketPoints(s, 'en')
  assert.deepEqual(buckets.map(b => b.title), PROFILE.map(b => b.title))
  const where = Object.fromEntries(buckets.flatMap(b => b.points.map(p => [p.id, b.id])))
  assert.equal(where['tab:surface:9'], 'do', 'a tab that asks is yours')
  assert.equal(where['task:bridges'], 'delegate')
  assert.equal(where['task:blocked'], 'waiting')
  assert.equal(where['task:quiet'], 'drop')
  assert.equal(where['task:mine'], 'plan')
  assert.equal(new Set(all.map(x => x.id)).size, all.length, 'each point once')
  // a tab that asks first, then the rows the printed briefing numbers, in its order
  const doIds = buckets[0].points.map(p => p.id)
  assert.deepEqual(doIds.slice(0, 3), ['tab:surface:9', 'inbox:20261009-0901-q2', 'inbox:20261009-0900-q1'])
})

test('bucketDefs: without the server\'s buckets the defaults of the page\'s language stand', () => {
  const s = state({ buckets: [] })
  assert.deepEqual(logic.bucketDefs(s, 'de').map(b => b.title), ['Tun (du, heute)', 'Planen', 'Mache ich', 'Wartet auf andere', 'Parken oder streichen'])
  assert.deepEqual(logic.bucketDefs(s, 'en')[0], { id: 'do', title: en.defaults.do.title, options: ['yes', 'later', 'drop'] })
})

// ---------------------------------------------------------------- the answers, the briefing's acts

test('do: yes lets the Bridge take the next step, later puts it off to the next briefing day, drop settles it', () => {
  const s = state()
  const item = ask('20261009-0900-q1')
  const a = answersOf(row(item), 'do', s)
  assert.deepEqual(a.map(x => x.label), ['Ja', 'Später', 'Streichen', en.obsolete])
  assert.deepEqual(a[0].run, { kind: 'act', verb: 'do_it', args: { keys: [item.key] } })
  assert.deepEqual(a[1].run, { kind: 'act', verb: 'later', args: { key: item.key, until: TOMORROW } })
  assert.equal(a[2].run.verb, 'settle')
  assert.equal(a[2].run.args.outcome, 'not_doing')
  // a task is shelved, never settled
  assert.equal(answersOf(row(task('t', { bucket: 'do' })), 'do', s)[2].run.verb, 'shelve')
})

test('do: a tab\'s own answers win, its ready answer first and strong (tab_accept)', () => {
  const s = state({ tabs: [asking] })
  const a = answersOf({ group: 'asks', id: 'tab:surface:9', kind: 'tab', tab: asking, row: null }, 'do', s)
  assert.equal(a[0].run.kind, 'reply')
  assert.equal(a[0].run.verb, 'tab_accept')
  assert.match(a[0].label, /yes, try the contact again/)
  // a tab without a row has nothing to put off or drop
  assert.ok(a.every(x => x.meaning === 'yes'))
  // nor one that works on a task: later would put off the whole task, not the question
  const onTask = answersOf({ group: 'asks', id: 'tab:surface:9', kind: 'tab', tab: asking, row: task('applications') }, 'do', s)
  assert.ok(onTask.every(x => x.meaning === 'yes'))
})

test('delegate, plan, waiting, drop: go, a day picked, a nudge that only drafts, park and keep', () => {
  const s = state()
  const t = task('t', { bucket: 'delegate' })
  const go = answersOf(row(t), 'delegate', s)
  assert.deepEqual(go.map(x => x.label), ['Los', 'Nicht jetzt', en.obsolete])
  assert.deepEqual(go[0].run, { kind: 'act', verb: 'do_it', args: { keys: [t.key] } })
  const plan = answersOf(row(t), 'plan', s)
  assert.equal(plan[0].run.kind, 'pick')
  assert.deepEqual(plan[0].run.then('2026-10-20'), { verb: 'later', args: { key: t.key, until: '2026-10-20' } })
  const w = answersOf({ ...row(t), checkin: { who: 'Ada', until: '2026-10-09' }, group: 'checkin' }, 'waiting', s)
  assert.equal(w[0].run.verb, 'do_it')
  assert.match(w[0].run.args.note, /draft/i)
  assert.match(w[0].run.args.note, /never send/i)
  assert.deepEqual(w[1].run.then('2026-10-16'), { verb: 'runs_on', args: { keys: [t.key], until: '2026-10-16', on: 'Ada' } })
  const d = answersOf(row(t), 'drop', s)
  assert.deepEqual(d.map(x => [x.label, x.run.verb]), [['Parken', 'task_park'], ['Behalten', 'task_keep'], [en.obsolete, 'settle']])
  // park is the briefing's park: status backlog, never a close as declined (control.md)
  assert.equal(d[0].run.args.key, t.key)
  // a backlog task is parked already: only keep and Obsolete are left
  const parked = answersOf(row(task('b', { status: 'backlog' })), 'drop', s)
  assert.deepEqual(parked.map(x => x.run.verb), ['task_keep', 'settle'])
})

// ---------------------------------------------------------------- the page

test('the page by buckets: the buckets left with their counts, one card with Next, its answers and its number', async () => {
  const c = recorder()
  const item = ask('20261009-0900-q1', { title: 'Fetch the prompt', brief_nr: 3, card: { next: { what: 'I draft a note that asks for the prompt.', who: 'bridge' } } })
  const s = state({ now: [item], work: [task('bridges', { status: 'review', bucket: 'delegate' })] })
  const el = mount(html`<${FlowPage} s=${s} c=${c} />`)
  await rounds()
  assert.deepEqual(el.$$('.fb-bucket .fb-bucket-name').map(b => b.childNodes[0].data ?? b.text()).map(x => String(x).trim()),
    PROFILE.map(b => b.title))
  assert.deepEqual(el.$$('.fb-bucket-n').map(n => n.text()), ['1', 'empty', '1', 'empty', 'empty'])
  assert.equal(el.$('.fb-title').text(), 'Fetch the prompt')
  assert.equal(el.$('.fb-next p').text(), 'I draft a note that asks for the prompt.')
  const buttons = el.$$('.fb-answers button')
  assert.deepEqual(buttons.map(b => b.text()), ['Ja', 'Später', 'Streichen', en.obsolete])
  assert.ok(buttons[0].hasClass('btn-primary'))
  assert.match(el.$('.fb-nr').text(), /no\. 3/)
  // no right column: what else the page offers stands under More
  assert.ok(el.$('.fb-more .flow-aside'), 'the verbs and fields under More')
  assert.equal(el.$$('.flow-aside').length, el.$$('.fb-more .flow-aside').length)
  buttons[0].click()
  await rounds()
  assert.deepEqual(c.calls.find(x => x[0] === 'act'), ['act', 'do_it', { keys: [item.key] }])
  el.$$('.fb-bucket')[2].click()
  assert.deepEqual(c.calls.at(-1), ['flowBucket', 'delegate'])
})

test('the page by buckets: an empty bucket offers the next one that holds a point; the mouse is enough', async () => {
  const s = state({ work: [task('quiet', { status: 'review', bucket: 'drop' })], ui: { flowBucket: 'do' } })
  const el = mount(html`<${FlowPage} s=${s} c=${recorder()} />`)
  await rounds()
  // the bucket picked holds nothing: the first one that holds a point is open
  assert.equal(el.$('.fb-head-title').text(), 'Parken oder streichen')
  assert.doesNotMatch(el.text(), /\b(enter|esc|shortcut|taste)\b/i)
})

test('the switch off: Work through as it was', async () => {
  const s = state({ on: false, now: [ask('20261009-0900-q1')] })
  const el = mount(html`<${FlowPage} s=${s} c=${recorder()} />`)
  await rounds()
  assert.equal(el.$('.fb-grid'), null)
  assert.ok(el.$('.flow-grid'))
})

test('bucketWords: the taskboard columns and Jev\'s squares say the buckets\' names while the switch is on', () => {
  const on = logic.bucketWords(state(), 'de')
  assert.deepEqual(on.columns, { me: 'Tun (du, heute)', bridge: 'Mache ich', waiting: 'Wartet auf andere' })
  assert.deepEqual(on.quadrant, { now: 'Tun (du, heute)', plan: 'Planen', hand: 'Mache ich', drop: 'Parken oder streichen' })
  assert.deepEqual(logic.bucketWords(state({ on: false }), 'de'), { columns: {}, quadrant: {} })
})
