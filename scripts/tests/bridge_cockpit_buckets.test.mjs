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
  // the bucket picked holds nothing: it stays open with its empty state, a button leads to the next one that holds one
  assert.equal(el.$('.fb-head-title').text(), 'Tun (du, heute)')
  assert.ok(el.$$('.fb-empty button').some(b => /Parken oder streichen/.test(b.text())))
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

// ---------------------------------------------------------------- round 1 of the simulation

test('a point opened from any list lands on its own card in its own bucket, never on the first card', () => {
  const first = ask('20261009-0900-q1', { brief_nr: 1 })
  const quiet = task('resting-one', { bucket: 'drop', brief_nr: 12 })
  const s = state({ now: [first], work: [task('a'), quiet] })
  const patch = logic.pointOpen(s, quiet.key)
  assert.equal(patch.flowBucket, 'drop')
  assert.deepEqual(patch.flowBucketAt, { id: quiet.key, i: 0 })
  const el = mount(html`<${FlowPage} s=${{ ...s, ui: { ...s.ui, ...patch } }} c=${recorder()} />`)
  assert.equal(el.$('.fb-title').text(), quiet.title)
  // a row no bucket holds (a closed task, another area's) still opens as a point of its own
  assert.equal(logic.pointOpen(s, 'task:gone-long-ago').flowView, 'solo')
})

test('an empty bucket picked stays open with its empty state and the way on, it never jumps to the first bucket', () => {
  const s = state({ now: [ask('20261009-0900-q1')], work: [task('p')], ui: { flowBucket: 'waiting', flowView: 'buckets' } })
  const el = mount(html`<${FlowPage} s=${s} c=${recorder()} />`)
  assert.equal(el.$('.fb-bucket.is-open').getAttribute('data-bucket'), 'waiting')
  assert.ok(el.$('.fb-empty'), 'the empty state of the bucket picked')
  assert.match(el.$('.fb-empty').text(), /Tun \(du, heute\)/)
})

test('a point put off until a later day stands in no bucket until then, however it was put off', () => {
  const s = state({ now: [ask('20261009-0900-q1'), ask('20261009-0901-off', { inbox_state: 'deferred', until: TOMORROW, bucket: 'plan', brief_nr: 4 }),
    ask('20261009-0902-back', { inbox_state: 'deferred', until: '2026-10-09', bucket: 'plan' })], work: [task('a')] })
  // Later on a task hides it here until the day (hide_until): it moves on, its bucket counts one less
  s.model.hidden = [task('put-off', { bucket: 'do', hidden_until: TOMORROW, section: 'work' })]
  const { all } = logic.bucketPoints(s, 'de')
  const ids = all.map(x => x.id)
  assert.ok(!ids.includes('task:put-off'), 'a task hidden until tomorrow')
  assert.ok(!ids.includes('inbox:20261009-0901-off'), 'an item put off until tomorrow, by inbox.py or here alike')
  assert.ok(ids.includes('inbox:20261009-0902-back'), 'an item whose day came is a point again')
  assert.ok(ids.includes('task:a') && ids.includes('inbox:20261009-0900-q1'))
})

test('an answer moves on to the next point, also where the point answered stays in its bucket', async () => {
  const calls = []
  const c = new Proxy({}, { get: (_, p) => (p === 'then' || typeof p === 'symbol' ? undefined
    : (...a) => { calls.push([p, ...a]); return p === 'act' ? Promise.resolve({ ok: true }) : undefined }) })
  const one = task('w1', { bucket: 'waiting', blocked_by: 'Robin' })
  const two = task('w2', { bucket: 'waiting', blocked_by: 'Mika' })
  const s = state({ work: [one, two], ui: { flowBucket: 'waiting', flowView: 'buckets' } })
  const el = mount(html`<${FlowPage} s=${s} c=${c} />`)
  await rounds()
  assert.equal(el.$('.fb-title').text(), one.title)
  el.$$('.fb-answers button').find(b => b.text() === 'Warten').click()
  await rounds()
  el.$$('.fb-pick button')[0].click()
  await rounds()
  assert.equal(calls.find(x => x[0] === 'act')[1], 'runs_on')
  assert.deepEqual(calls.find(x => x[0] === 'flowBucketGo'), ['flowBucketGo', two.key, 0])
})

test('a blocked task or stream the briefing does not list waits on others, wherever the model keeps its blocker', () => {
  // the model's own rows of resting tasks carry the blocker only on the card (model.py with_tasks, card.state)
  const blocked = task('fabrikam-backup', { bucket: 'resting', card: { state: { blocked_by: 'waiting for Robin' } } })
  assert.equal(logic.rowBucket(blocked), 'waiting')
  const stream = task('rota', { bucket: 'resting', stream: true, card: { state: { blocked_by: 'waiting for Kai' } } })
  assert.equal(logic.rowBucket(stream), 'waiting')
  assert.equal(logic.rowBucket(task('quiet', { bucket: 'resting' })), 'drop')
})

test('a nudge on a blocked task names what it waits on, and Wait keeps that blocker', () => {
  const s = state()
  const t = task('logbook', { bucket: 'waiting', blocked_by: 'waiting for Robin to reply' })
  const [nudge, wait] = logic.bucketAnswers(row(t), 'waiting', s, 'de')
  assert.match(nudge.run.args.note, /waiting for Robin to reply/)
  assert.doesNotMatch(nudge.run.args.note, /andere Seite|jemandem/)
  // no "on": task.py wait keeps the blocker the task has
  assert.deepEqual(wait.run.then('2026-10-16'), { verb: 'runs_on', args: { keys: [t.key], until: '2026-10-16' } })
})

test('askQuestion never cuts a question at a dot inside a number, a version or a path', () => {
  assert.equal(logic.askQuestion('Shall I bump v2.3.1 to v2.4? It fixes the bug.'), 'Shall I bump v2.3.1 to v2.4?')
  assert.equal(logic.askQuestion('Für die Schätzung fehlt mir eine Zahl: Wie viele Datensätze laufen pro Nacht durch den Sync,\ngrob 10.000 oder eher 1 Million? Davon hängt ab, ob wir in Batches migrieren.'),
    'Für die Schätzung fehlt mir eine Zahl: Wie viele Datensätze laufen pro Nacht durch den Sync, grob 10.000 oder eher 1 Million?')
  assert.equal(logic.askQuestion('Run ./deploy.sh --env staging now. Do you want to proceed?'), 'Run ./deploy.sh --env staging now. Do you want to proceed?')
  // a question mid-text asks (asks.question_of `asks`), as one at the end does
  assert.equal(logic.asksSomething({ text: 'Done? Then fine.', asks: true }), true)
})

test('tabWords: what a tab asks or said last, never the driver\'s chrome line', () => {
  const chrome = { last: '⏵⏵ accept edits on (shift+tab to cycle)', ask: { text: 'Soll ich den Vertrag kündigen?' } }
  assert.equal(logic.tabWords(chrome), 'Soll ich den Vertrag kündigen?')
  assert.equal(logic.tabWords({ last: '⏵⏵ accept edits on (shift+tab to cycle)' }), '')
  assert.equal(logic.tabWords({ last: '? for shortcuts' }), '')
  assert.equal(logic.tabWords({ last: 'Tests are green.' }), 'Tests are green.')
})

test('a row shows one number, the printed briefing\'s, while the buckets are on', () => {
  const s = { ...state(), model: { ...state().model, numbers: { 'task:a': 4, 'task:b': 42 } } }
  assert.equal(logic.shownNumber({ key: 'task:a', brief_nr: null }, s), null)
  assert.equal(logic.shownNumber({ key: 'task:b', brief_nr: 4 }, s), 4)
  // with the switch off the cockpit's own number, as before
  assert.equal(logic.shownNumber({ key: 'task:b', brief_nr: 4 }, { ...s, work: { flow: { enabled: true, buckets: { enabled: false } } } }), 42)
})

test('a number typed with the buckets on names the printed briefing\'s row', () => {
  const a = task('a', { brief_nr: 4 })
  const b = task('b')
  const byKey = new Map([[a.key, a], [b.key, b]])
  const by = logic.rowByNumber({ numbers: { [b.key]: 4 } }, byKey, true)
  assert.equal(by.get(4), a)
  assert.equal(logic.rowByNumber({ numbers: { [b.key]: 4 } }, byKey).get(4), b)
})

test('Next is a sentence that fits the bucket, a stream is named a stream, Obsolete asks with its own words', () => {
  const s = state()
  // an inbox card's generic one-word step ("entscheiden", "dein Ja geben") gives way to the bucket's sentence
  const q = ask('20261009-0900-q1', { card: { next: { what: 'entscheiden' } } })
  assert.equal(logic.nextSentence(row(q), 'do', s, 'de'), text.TABLES.de.flow.buckets.next.do)
  const d = ask('20261009-0901-q2', { bucket: 'delegate', card: { next: { what: 'dein Ja geben' } } })
  assert.equal(logic.nextSentence(row(d), 'delegate', s, 'de'), text.TABLES.de.flow.buckets.next.delegate)
  // a task's own step stays, however short
  assert.equal(logic.nextSentence(row(task('t', { card: { next: { what: 'Merge it' } } })), 'plan', s, 'de'), 'Merge it')
  const river = task('river', { stream: true, work_kind: 'stream', bucket: 'drop' })
  assert.equal(logic.pointKindWord(row(river), 'de'), 'Stream')
  assert.doesNotMatch(logic.nextSentence(row(river), 'drop', s, 'de'), /Parken/)
  // the confirm of Obsolete never says a bare "Ja" beside the bucket's Ja
  assert.notEqual(text.TABLES.de.flow.buckets.obsoleteYes, 'Ja')
})

test('a German page says the German default words where the profile names none, though the server fills the English', () => {
  // the server sends its defaults (briefing_view DEFAULT_BUCKETS) for what the profile leaves out
  const served = [{ id: 'do', title: 'Tun (du, heute)', options: ['yes', 'later', 'drop'] }, { id: 'plan', title: 'Plan', options: ['schedule', 'later'] }]
  const defs = logic.bucketDefs(state({ buckets: served }), 'de')
  assert.deepEqual(defs[0], { id: 'do', title: 'Tun (du, heute)', options: ['ja', 'später', 'streichen'] })
  assert.deepEqual(defs[1], { id: 'plan', title: 'Planen', options: ['einplanen', 'später'] })
  // a profile's own words stay, also English ones on an English page
  assert.deepEqual(logic.bucketDefs(state({ buckets: served }), 'en')[0].options, ['yes', 'later', 'drop'])
  assert.deepEqual(logic.bucketDefs(state({ buckets: [{ id: 'do', title: 'Heute', options: ['klar', 'morgen', 'weg'] }] }), 'de')[0].options, ['klar', 'morgen', 'weg'])
})

test('a point whose inbox id the server refuses offers no answer it would refuse', () => {
  const bad = ask('20260929-1900-keep-or-cancel-the-power-contract-(deadl')
  assert.deepEqual(answersOf(row(bad), 'do', state()), [])
})

test('a task a question about it stands for is a point of its own too, as the briefing numbers both', () => {
  const t = task('power', { bucket: 'drop', brief_nr: 8 })
  const q = ask('20261009-0900-power', { task: 'power', brief_nr: 2 })
  const { all } = logic.bucketPoints(state({ now: [q], work: [t] }), 'de')
  assert.deepEqual(all.map(x => x.id).sort(), [q.key, t.key].sort())
  assert.equal(all.find(x => x.id === t.key).bucket, 'drop')
})

test('the taskboard says what a task waits on once, never "wartet auf waiting for"', () => {
  assert.equal(text.TABLES.de.taskboard.tag.waitingOn('waiting for Noa to reply'), 'waiting for Noa to reply')
  assert.equal(text.TABLES.de.taskboard.tag.waitingOn('Noa'), 'wartet auf Noa')
})

test('what runs stands quiet under the buckets, no decision and never lost from the page', async () => {
  const c = recorder()
  const working = { ref: 'surface:5', name: 'fabrikam-backup', state: 'working', slug: 'backup', since_ms: NOW - 5 * MIN, workspace: 'Home' }
  const s = state({ work: [task('backup'), task('other')], tabs: [working], driver: { caps: ['tabs', 'launch', 'focus', 'screen'] } })
  const el = mount(html`<${FlowPage} s=${s} c=${c} />`)
  await rounds()
  const run = el.$('.fb-running')
  assert.ok(run, 'a quiet list of what runs')
  assert.match(run.text(), /Task backup/)
  // it is no point of a bucket
  assert.ok(!logic.bucketPoints(s, 'de').all.some(x => x.id === 'task:backup'))
  run.$$('button')[0].click()
  assert.equal(c.calls.at(-1)[0], 'flowRun')
})

test('a tab whose question needs a number or a choice is answered in words first, never only with Go on', async () => {
  const q = { ref: 'surface:2', name: 'estimate-sync', state: 'waiting', since_ms: NOW - 5 * MIN, workspace: 'Home',
    ask: { text: 'Wie viele Datensätze, grob 10.000 oder eher 1 Million? Davon hängt es ab.', hash: 'h2', yes_no: false, asks: true, draft: false } }
  const s = state({ tabs: [q], driver: { caps: ['tabs', 'launch', 'focus', 'screen', 'send', 'key'] } })
  const x = { group: 'asks', id: 'tab:surface:2', kind: 'tab', tab: q, row: null }
  const a = logic.bucketAnswers(x, 'do', s, 'de')
  assert.equal(a[0].run.kind, 'say')
  assert.ok(a.some(b => b.run.verb === 'tab_go_on'))
  const calls = []
  const c = new Proxy({}, { get: (_, p) => (p === 'then' || typeof p === 'symbol' ? undefined
    : (...args) => { calls.push([p, ...args]); return p === 'reply' ? Promise.resolve({ ok: true }) : undefined }) })
  const el = mount(html`<${views.flowbuckets.BucketCard} x=${x} bucket="do" s=${s} c=${c} />`)
  el.$$('.fb-answers button')[0].click()
  await rounds()
  const box = el.$('.fb-say input')
  assert.ok(box, 'a line to answer in')
  box.value = 'eher 1 Million'
  box.dispatch('input')
  await rounds()
  el.$('.fb-say form').dispatch('submit')
  await rounds()
  assert.deepEqual(calls.find(x2 => x2[0] === 'reply').slice(1), ['tab_send', logic.replySend(q, 'eher 1 Million').args])
  assert.equal(logic.replySend(q, 'x').args.seen, 'h2')
})

test('the files page is named in words on the start page, never by its id', () => {
  assert.equal(views.home.pageTitleOf({ model: { pages: [] }, ui: {} }, '@files'), text.TABLES.en.filesTab)
})

test('a toast says a day the way the page says days, never as an ISO date', () => {
  assert.equal(logic.noteDays('Später, zurück am 2026-11-22', 'de'), `Später, zurück am ${logic.formatDay('2026-11-22', 'de')}`)
  // an inbox id with its digits stays as it is
  assert.equal(logic.noteDays('20261121-1443-check-the-release', 'de'), '20261121-1443-check-the-release')
})
