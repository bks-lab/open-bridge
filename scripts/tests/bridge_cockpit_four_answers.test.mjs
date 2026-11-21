// SPDX-License-Identifier: MIT
// Tests of the model of Work through by the briefing's buckets (cockpit.flow.buckets): every point answers who is on
// the move and when. Four buckets (Do, Plan, I'll do, Waiting on others), the same four answers on every point (Do it,
// Later ▾, Done, Obsolete), what is out of sight only counted. scripts/web/buckets.js and views/flowbuckets.js, no npm
// dependencies.
//
//   node --test scripts/tests/bridge_cockpit_four_answers.test.mjs
import test from 'node:test'
import assert from 'node:assert/strict'
import { loadCockpit, mount, recorder, settle as rounds } from './cockpit_render.mjs'

const { html, views, text, logic } = await loadCockpit()
const { FlowPage } = views.flow
const { BucketCard, BucketBar } = views.flowbuckets
const en = text.TABLES.en.flow.buckets
const de = text.TABLES.de.flow.buckets

// Friday, 9 October 2026, noon
const NOW = new Date(2026, 9, 9, 12, 0, 0).getTime()
const MIN = 60000
const TOMORROW = '2026-10-10'
const MONDAY = '2026-10-12'
const WEEK = '2026-10-16'
const LIST_DAY = '9999-12-31'

// what the server sends for a German profile (briefing_view bucket_defs): titles only
const SERVED = [{ id: 'do', title: 'Tun' }, { id: 'plan', title: 'Planen' }, { id: 'delegate', title: 'Mache ich' },
  { id: 'waiting', title: 'Wartet auf andere' }]

const task = (slug, over = {}) => ({ key: `task:${slug}`, task: slug, title: `Task ${slug}`, status: 'doing', bucket: 'plan',
  priority: 'P2', settle: ['done', 'not_doing'], ...over })
const ask = (id, over = {}) => ({ key: `inbox:${id}`, inbox_id: id, title: `Question ${id}`, art: 'ask', inbox_state: 'open',
  bucket: 'do', gate: 'your-yes', settle: ['done', 'not_doing'], ...over })
const issue = (n, over = {}) => ({ key: `ref:acme/app#${n}`, ref: `acme/app#${n}`, title: `Issue ${n}`, bucket: 'plan',
  url: `https://github.com/acme/app/issues/${n}`, settle: ['done', 'not_doing'], ...over })
const stream = (slug, over = {}) => task(slug, { stream: true, work_kind: 'stream', ...over })

function state({ now = [], work = [], tabs = [], buckets = SERVED, aside = { later: 2, list: 5, done_today: 1 }, ui = {}, ...rest } = {}) {
  return {
    now: NOW, model: { sections: [{ id: 'now', rows: now }, { id: 'give', rows: [] }, { id: 'work', rows: work },
      { id: 'track', rows: [] }, { id: 'later', rows: [] }], hidden: [], returns: [], buckets, aside },
    tabs: { tabs, at_ms: NOW }, driver: { caps: ['tabs', 'launch', 'focus', 'screen'] }, triage: { items: {} }, jevOrder: {}, details: {},
    work: { flow: { enabled: true, drop_reasons: ['resolves_itself', 'not_needed'], return_after_s: 20, buckets: { enabled: true } } },
    themes: { enabled: false }, quick: { convs: [] }, flow_ai: {},
    ui: { page: '@flow', busy: {}, flowAt: null, flowChip: 'all', flowJump: null, flowView: 'overview', ...ui }, ...rest,
  }
}

const row = r => ({ group: 'row', id: r.key, kind: 'row', row: r })
const answers = (r, bucket, s = state(), lang = 'en') => logic.bucketAnswers(row(r), bucket, s, lang)
const meanings = list => list.map(a => a.meaning)
const later = (list, choice, day = null) => list.find(a => a.meaning === 'later').run.then(choice, day)

// a fake controller whose acts go through
function ctl() {
  const calls = []
  const c = new Proxy({}, { get: (_, p) => (p === 'then' || typeof p === 'symbol' ? undefined
    : (...a) => { calls.push([p, ...a]); return p === 'act' || p === 'reply' ? Promise.resolve({ ok: true }) : undefined }) })
  return { c, calls }
}

// ---------------------------------------------------------------- the four buckets

test('four buckets in the briefing\'s order, no Park or drop left', () => {
  assert.deepEqual(logic.BUCKET_IDS, ['do', 'plan', 'delegate', 'waiting'])
  assert.deepEqual(logic.bucketDefs(state(), 'de').map(b => b.title), ['Tun', 'Planen', 'Mache ich', 'Wartet auf andere'])
  // an older server that still sends drop and options: drop is left out, options are no answers of a bucket
  const old = [{ id: 'do', title: 'Tun (du, heute)', options: ['ja'] }, { id: 'drop', title: 'Parken oder streichen' }]
  assert.deepEqual(logic.bucketDefs(state({ buckets: old }), 'de'), [{ id: 'do', title: 'Tun (du, heute)' }])
  // a German page says German words where the server sent its English defaults
  const english = [{ id: 'do', title: 'Do (you, today)' }, { id: 'plan', title: 'Plan' }]
  assert.deepEqual(logic.bucketDefs(state({ buckets: english }), 'de').map(b => b.title), ['Tun', 'Planen'])
  assert.deepEqual(logic.bucketDefs(state({ buckets: [] }), 'en').map(b => b.title), Object.values(en.defaults).map(d => d.title))
  for (const tb of [en, de]) assert.ok(!('drop' in tb.defaults) && !('drop' in tb.sub))
})

test('a long-resting point stays in its own bucket with a quiet mark, never in a bucket of its own', () => {
  assert.equal(logic.rowBucket(task('quiet', { bucket: 'resting' })), 'plan')
  assert.equal(logic.rowBucket(task('quiet', { bucket: 'resting', card: { next: { who: 'bridge' } } })), 'delegate')
  // an older briefing's drop bucket: the row by who has its next move
  assert.equal(logic.rowBucket(task('old', { bucket: 'drop' })), 'plan')
  assert.equal(logic.restingOf(task('a', { resting: 54 })), 54)
  assert.equal(logic.restingOf(task('b', { bucket: 'resting' })), true)
  assert.equal(logic.restingOf(task('c')), null)
  assert.equal(en.resting(54), 'resting for 54 days')
  assert.equal(de.resting(54), 'ruht seit 54 Tagen')
  assert.equal(de.resting(1), 'ruht seit 1 Tag')
})

test('a step with someone else waits on them; a backlog task stands in no bucket, it is on the watch list', () => {
  assert.equal(logic.rowBucket(task('t', { bucket: 'tasks', card: { next: { who: 'Robin' } } })), 'waiting')
  assert.equal(logic.rowBucket(task('t', { bucket: 'tasks', card: { next: { who: 'me' } } })), 'plan')
  assert.equal(logic.rowBucket(task('t', { bucket: 'tasks', status: 'backlog' })), null)
  // a list keeps it somewhere: Plan, you without a day
  assert.equal(logic.viewBucket(row(task('t', { bucket: 'tasks', status: 'backlog' }))), 'plan')
})

test('what is out of sight is counted: later, the watch list, done today', () => {
  assert.deepEqual(logic.asideCounts(state()), { later: 2, list: 5, done_today: 1 })
  assert.deepEqual(logic.asideCounts(state({ aside: null })), { later: 0, list: 0, done_today: 0 })
})

// ---------------------------------------------------------------- the four answers

test('every point takes the same four answers in the same order, Do it strong, Obsolete quiet and last', () => {
  const s = state()
  for (const [r, bucket] of [[ask('20261009-0900-q1'), 'do'], [task('p'), 'plan'], [task('d', { bucket: 'delegate' }), 'delegate'],
    [task('w', { bucket: 'waiting', blocked_by: 'Robin' }), 'waiting'], [issue(4), 'plan']]) {
    const a = answers(r, bucket, s, 'de')
    assert.deepEqual(meanings(a), ['do', 'later', 'done', 'obsolete'], `${bucket} ${r.key}`)
    assert.deepEqual(a.map(x => x.label), ['Mach das', 'Später ▾', 'Erledigt', 'Veraltet'], `${bucket} ${r.key}`)
    assert.ok(a[0].primary && !a.slice(1).some(x => x.primary))
    assert.ok(a[3].quiet && a[3].confirm)
  }
})

test('Do it: an inbox item gets its yes, a task an agent on its next step, a waiting point a nudge that is only a draft', () => {
  const s = state()
  const item = ask('20261009-0900-q1')
  assert.deepEqual(answers(item, 'do')[0].run, { kind: 'act', verb: 'do_it', args: { keys: [item.key], yes: true } })
  const t = task('t')
  assert.deepEqual(answers(t, 'plan')[0].run, { kind: 'act', verb: 'do_it', args: { keys: [t.key] } })
  const w = task('w', { bucket: 'waiting', blocked_by: 'waiting for Robin' })
  const nudge = answers(w, 'waiting', s)[0].run
  assert.equal(nudge.verb, 'do_it')
  assert.match(nudge.args.note, /draft/i)
  assert.match(nudge.args.note, /never send/i)
  // a point an agent tab works on is never started twice: no Do it, Later stands first and is not strong
  const busy = task('busy', { tab: { ref: 'surface:3', live: true } })
  const a = answers(busy, 'plan')
  assert.deepEqual(meanings(a), ['later', 'done', 'obsolete'])
  assert.ok(!a.some(x => x.primary))
})

test('Do it on an asking tab is the tab\'s own answers in first place', () => {
  const tab = { ref: 'surface:9', name: 'Contact import', state: 'waiting', since_ms: NOW - 5 * MIN, workspace: 'Home',
    ask: { text: 'Shall I try again?', hash: 'h1', draft: true, suggestion: 'yes, try again' } }
  const s = state({ tabs: [tab], driver: { caps: null } })
  const alone = logic.bucketAnswers({ group: 'asks', id: 'tab:surface:9', kind: 'tab', tab, row: null }, 'do', s, 'en')
  assert.equal(alone[0].run.verb, 'tab_accept')
  assert.ok(alone[0].primary)
  assert.ok(alone.every(a => a.meaning === 'do'), 'a tab alone has nothing to put off or close')
  // a tab that asks about an inbox item: its answers first, then Later, Done, Obsolete on the item
  const item = ask('20261009-0900-q1')
  const onItem = logic.bucketAnswers({ group: 'asks', id: item.key, kind: 'tab', tab, row: item }, 'do', s, 'en')
  assert.equal(onItem[0].run.verb, 'tab_accept')
  assert.deepEqual(meanings(onItem).slice(-3), ['later', 'done', 'obsolete'])
})

test('Later: tomorrow, Monday, in a week, a picked day, the watch list', () => {
  const s = state()
  const item = ask('20261009-0900-q1')
  const a = answers(item, 'do', s)
  assert.deepEqual(a[1].run.choices, ['tomorrow', 'monday', 'week', 'pick', 'list'])
  assert.deepEqual(logic.laterDays(NOW), { tomorrow: TOMORROW, monday: MONDAY, week: WEEK })
  assert.deepEqual(later(a, 'tomorrow', TOMORROW), { verb: 'later', args: { key: item.key, until: TOMORROW } })
  assert.deepEqual(later(a, 'pick', '2026-11-03'), { verb: 'later', args: { key: item.key, until: '2026-11-03' } })
  // the watch list: an inbox item or any row put off without a day, a task to the backlog
  assert.deepEqual(later(a, 'list'), { verb: 'later', args: { key: item.key, until: LIST_DAY } })
  const t = task('t')
  assert.deepEqual(later(answers(t, 'plan'), 'list'), { verb: 'task_park', args: { key: t.key, reason: en.parkText } })
  // Plan's day is a planned day, never "later"
  assert.deepEqual(later(answers(t, 'plan'), 'monday', MONDAY), { verb: 'later', args: { key: t.key, until: MONDAY, plan: true } })
  // a stream on the watch list is put off without a day, never parked as a task
  const river = stream('river')
  assert.deepEqual(later(answers(river, 'plan'), 'list'), { verb: 'later', args: { key: river.key, until: LIST_DAY } })
  // a backlog task is on the watch list already
  assert.ok(!answers(task('b', { status: 'backlog' }), 'plan').find(x => x.meaning === 'later').run.choices.includes('list'))
})

test('Later on a waiting point keeps it with the same person until the day', () => {
  const t = task('w', { bucket: 'waiting' })
  const x = { ...row(t), group: 'checkin', checkin: { who: 'Ada', until: '2026-10-09' } }
  const a = logic.bucketAnswers(x, 'waiting', state(), 'en')
  assert.deepEqual(a.find(z => z.meaning === 'later').run.then('week', WEEK), { verb: 'runs_on', args: { keys: [t.key], until: WEEK, on: 'Ada' } })
  // a blocked task keeps its blocker (task.py wait without on)
  const b = task('b', { bucket: 'waiting', blocked_by: 'waiting for Robin' })
  assert.deepEqual(later(answers(b, 'waiting'), 'tomorrow', TOMORROW), { verb: 'runs_on', args: { keys: [b.key], until: TOMORROW } })
})

test('Done settles as done; on a stream it is done for this time and the stream runs on', () => {
  const t = task('t')
  const done = answers(t, 'plan').find(a => a.meaning === 'done')
  assert.deepEqual(done.run, { kind: 'act', verb: 'settle', args: { keys: [t.key], outcome: 'done' } })
  const river = stream('river')
  const d = answers(river, 'plan', state(), 'de').find(a => a.meaning === 'done')
  assert.equal(d.label, 'für diesmal erledigt')
  assert.equal(d.run.verb, 'later')
  assert.equal(d.run.args.until, TOMORROW)
  assert.equal(d.run.args.text, de.doneStreamText)
  // a row that cannot be settled as done offers no Done
  assert.ok(!answers(task('x', { settle: ['not_doing'] }), 'plan').some(a => a.meaning === 'done'))
})

test('the old eleven answer words are gone from bucket mode', () => {
  const words = /^(ja|yes|los|go|nachfassen|nudge|einplanen|schedule|nicht jetzt|not now|warten|wait|parken|park|behalten|keep|streichen|drop)$/i
  const s = state()
  for (const lang of ['en', 'de']) {
    for (const [r, b] of [[ask('20261009-0900-q1'), 'do'], [task('p'), 'plan'], [task('d'), 'delegate'], [task('w', { blocked_by: 'x' }), 'waiting']]) {
      for (const a of answers(r, b, s, lang)) assert.doesNotMatch(a.label, words, `${lang} ${b} ${a.label}`)
    }
  }
  assert.equal(logic.BUCKET_MEANINGS, undefined)
})

// ---------------------------------------------------------------- More

test('More: with you, the Bridge or a name; a task\'s step is handed over, anything else goes to a person', () => {
  const t = task('t')
  const own = logic.ownerChoices(row(t), state())
  assert.deepEqual(own.choices.map(o => [o.who, o.run.verb]), [['me', 'task_owner'], ['bridge', 'task_owner']])
  assert.deepEqual(own.choices[1].run.args, { key: t.key, who: 'bridge' })
  assert.deepEqual(own.name('Robin'), { verb: 'work_on', args: { key: t.key, who: 'Robin', until: WEEK } })
  assert.equal(own.current, 'me')
  assert.equal(logic.ownerChoices(row(task('d', { card: { next: { who: 'bridge' } } })), state()).current, 'bridge')
  // an inbox item has no step to hand to the Bridge: Do it is that; a name puts it with someone
  const item = ask('20261009-0900-q1')
  const io = logic.ownerChoices(row(item), state())
  assert.deepEqual(io.choices, [])
  assert.equal(io.name('Ada').verb, 'work_on')
})

// ---------------------------------------------------------------- the page

test('the card: Next, the four answers, the briefing number with the answer words, the resting mark, More', async () => {
  const { c, calls } = ctl()
  const t = task('prompt', { title: 'Fetch the prompt', bucket: 'plan', brief_nr: 3, resting: 12, card: { next: { what: 'I draft a note that asks for the prompt.' } } })
  const s = state({ work: [t] })
  const el = mount(html`<${BucketCard} x=${row(t)} bucket="plan" s=${s} c=${c} />`)
  assert.equal(el.$('.fb-next p').text(), 'I draft a note that asks for the prompt.')
  assert.deepEqual(el.$$('.fb-answers .fb-answer').map(b => b.text()), ['Do it', 'Later ▾', 'Done', 'Obsolete'])
  assert.ok(el.$('.fb-answer-do').hasClass('btn-primary'))
  assert.match(el.$('.fb-nr').text(), /no\. 3/)
  assert.match(el.$('.fb-nr').text(), /"3 do"/)
  assert.match(el.$('.fb-nr').text(), /"3 later"/)
  assert.match(el.$('.fb-marks').text(), /resting for 12 days/)
  const more = el.$('.fb-more')
  assert.ok(more.$('.fb-owner'), 'With … under More')
  assert.ok(more.$('.fb-fields'), 'the fields under More')
  assert.ok(more.$('.fb-ask'), 'the free line under More')
  // Later opens its menu, a day goes out as the answer
  el.$('.fb-answer-later').click()
  await rounds()
  const menu = el.$('.fb-later-menu')
  assert.ok(menu)
  assert.deepEqual(menu.$$('button').map(b => b.getAttribute('data-choice')).filter(Boolean), ['tomorrow', 'monday', 'week', 'pick', 'list'])
  menu.$('[data-choice="monday"]').click()
  await rounds()
  assert.deepEqual(calls.find(x => x[0] === 'act'), ['act', 'later', { key: t.key, until: MONDAY, plan: true, was: 'doing' }])
})

test('the card: Obsolete asks in place with a note, and the note goes with it', async () => {
  const { c, calls } = ctl()
  const t = task('old', { title: 'Old thing' })
  const el = mount(html`<${BucketCard} x=${row(t)} bucket="plan" s=${state({ work: [t] })} c=${c} />`)
  el.$('.fb-answer-obsolete').click()
  await rounds()
  const box = el.$('.fb-confirm input')
  assert.ok(box, 'a note why, optional')
  box.value = 'the vendor left'
  box.dispatch('input')
  await rounds()
  el.$('.fb-confirm-yes').click()
  await rounds()
  const sent = calls.find(x => x[0] === 'act')
  assert.equal(sent[1], 'settle')
  assert.equal(sent[2].outcome, 'not_doing')
  assert.match(sent[2].text, /the vendor left/)
})

test('the card of a stream says End stream and done for this time', () => {
  const river = stream('river', { title: 'Weekly rota' })
  const el = mount(html`<${BucketCard} x=${row(river)} bucket="plan" s=${state({ work: [river] })} c=${recorder()} />`)
  assert.match(el.$('.fb-answer-done').text(), /done for this time/)
  assert.equal(el.$('.fb-answer-obsolete').text(), en.obsoleteStream)
})

test('the left column: who is on the move, the four buckets with what each means, the three counts out of sight', async () => {
  const s = state({ now: [ask('20261009-0900-q1')], work: [task('a'), task('b', { bucket: 'delegate' })] })
  const el = mount(html`<${FlowPage} s=${s} c=${recorder()} />`)
  await rounds()
  assert.equal(el.$('.fb-side h2').text(), en.label)
  assert.deepEqual(el.$$('.fb-bucket-sub').map(x => x.text()), ['you, today', 'you, no day yet', 'the Bridge', 'someone else'])
  const aside = el.$('.fb-aside')
  assert.ok(aside)
  assert.deepEqual(aside.$$('.fb-aside-n').map(n => n.text()), ['2', '5', '1'])
  assert.match(aside.text(), /watch list/i)
  assert.doesNotMatch(el.text(), /Park or drop|Parken oder streichen/)
})

test('a row of a list: the bucket chip, Do it strong, Later, Done and Obsolete under one More', async () => {
  const t = task('t')
  const el = mount(html`<${BucketBar} x=${row(t)} s=${state({ work: [t] })} c=${recorder()} />`)
  assert.equal(el.$$('.fb-bar > .fb-answer').map(b => b.text()).join(), 'Do it')
  el.$('.fb-bar-more').click()
  await rounds()
  assert.deepEqual(el.$$('.fb-bar-rest .fb-answer').map(b => b.text()), ['Later ▾', 'Done', 'Obsolete'])
})

test('Jev\'s squares and the task board say the four buckets, no drop word', () => {
  const w = logic.bucketWords(state(), 'de')
  assert.deepEqual(w.quadrant, { now: 'Tun', plan: 'Planen', hand: 'Mache ich', drop: 'Merkliste' })
  assert.deepEqual(w.columns, { bridge: 'Mache ich', waiting: 'Wartet auf andere' })
})
