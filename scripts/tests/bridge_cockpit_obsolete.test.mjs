// SPDX-License-Identifier: MIT
// Tests of the fixed last answer Obsolete of Work through by the briefing's buckets (cockpit.flow.buckets) and of the
// instruction line under its card: scripts/web/buckets.js bucketAnswers, views/flowbuckets.js BucketCard and
// BucketBar, no npm dependencies.
//
//   node --test scripts/tests/bridge_cockpit_obsolete.test.mjs
//
// Every point in every bucket ends with one quiet answer Obsolete, always at the same place. Its act is the classic
// "Drop because out of date": a task settled not doing with the reason noted, an inbox item dropped with the note, an
// issue hidden here (never closed on GitHub), a stream ended. A tab's question is answered in the tab, so it is not
// offered there unless the tab asks about an inbox item. A click asks first, in place.
import test from 'node:test'
import assert from 'node:assert/strict'
import { loadCockpit, mount, recorder, settle as rounds, waitFor } from './cockpit_render.mjs'

const { html, views, text, logic } = await loadCockpit()
const { FlowPage } = views.flow
const { BucketBar } = views.flowbuckets
const en = text.TABLES.en.flow.buckets
const de = text.TABLES.de.flow.buckets

const NOW = new Date(2026, 9, 9, 12, 0, 0).getTime()
const MIN = 60000

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
const issue = (n, over = {}) => ({ key: `ref:acme/app#${n}`, ref: `acme/app#${n}`, title: `Issue ${n}`, bucket: 'plan',
  url: `https://github.com/acme/app/issues/${n}`, settle: ['done', 'not_doing'], ...over })
const stream = (slug, over = {}) => task(slug, { stream: true, work_kind: 'stream', ...over })

function state({ now = [], work = [], tabs = [], on = true, instruct = false, ui = {} } = {}) {
  return {
    now: NOW, model: { sections: [{ id: 'now', rows: now }, { id: 'give', rows: [] }, { id: 'work', rows: work },
      { id: 'track', rows: [] }, { id: 'later', rows: [] }], hidden: [], returns: [], buckets: PROFILE },
    tabs: { tabs, at_ms: NOW }, driver: { caps: null }, triage: { items: {} }, jevOrder: {}, details: {},
    work: { flow: { enabled: true, drop_reasons: ['resolves_itself', 'not_needed'], return_after_s: 20, buckets: { enabled: on },
      instruct: { enabled: instruct } } },
    themes: { enabled: false }, quick: { convs: [] }, flow_ai: {},
    ui: { page: '@flow', busy: {}, flowAt: null, flowChip: 'all', flowJump: null, flowView: 'overview', ...ui },
  }
}

const asking = {
  ref: 'surface:9', name: 'Contact import', state: 'waiting', since_ms: NOW - 5 * MIN, workspace: 'Home',
  ask: { text: 'Shall I try again?', hash: 'h1', draft: true, suggestion: 'yes, try again' },
}

const row = r => ({ group: 'question', id: r.key, kind: 'row', row: r })
const last = (x, bucket, s, lang = 'en') => logic.bucketAnswers(x, bucket, s, lang).at(-1)

// ---------------------------------------------------------------- the answer and its act

test('every point in every bucket ends with Obsolete, the same quiet answer at the same place', () => {
  const s = state()
  for (const bucket of logic.BUCKET_IDS) {
    for (const r of [task('t', { bucket }), ask('20261009-0900-q1', { bucket }), issue(7, { bucket })]) {
      const a = logic.bucketAnswers(row(r), bucket, s, 'en')
      assert.equal(a.at(-1).meaning, 'obsolete', `${bucket} ${r.key}`)
      assert.equal(a.at(-1).label, en.obsolete)
      assert.equal(a.at(-1).confirm, true, 'it asks first')
      assert.equal(a.filter(x => x.meaning === 'obsolete').length, 1)
      // never the strong one: something the bucket offers comes first
      assert.notEqual(a[0].meaning, 'obsolete', `${bucket} ${r.key}`)
    }
  }
  assert.equal(last(row(task('t')), 'plan', s, 'de').label, de.obsolete)
  assert.equal(de.obsolete, 'Veraltet')
  assert.equal(en.obsolete, 'Obsolete')
})

test('Obsolete is the classic drop because out of date: a task settled not doing with the reason noted', () => {
  const s = state()
  const t = task('old-plan', { bucket: 'drop' })
  const a = last(row(t), 'drop', s, 'de')
  assert.deepEqual(a.run, { kind: 'act', verb: 'settle', args: { keys: [t.key], outcome: 'not_doing', text: de.obsoleteText } })
  assert.equal(de.obsoleteText, 'veraltet')
})

test('Obsolete on an inbox item drops it with the note and counts it as out of date under its source', () => {
  const s = state()
  const item = ask('20261009-0900-q1')
  const a = last(row(item), 'do', s, 'de')
  assert.deepEqual(a.run, { kind: 'act', verb: 'settle',
    args: { keys: [item.key], outcome: 'not_doing', text: 'veraltet', reason: 'outdated' } })
})

test('Obsolete on an issue hides it here and never closes it on GitHub', () => {
  const s = state()
  const i = issue(42, { bucket: 'waiting' })
  const a = last(row(i), 'waiting', s, 'en')
  assert.equal(a.run.verb, 'settle')
  assert.equal(a.run.args.outcome, 'not_doing')
  assert.ok(!['issue_done', 'close', 'task_close'].includes(a.run.verb))
})

test('Obsolete on a stream ends it, with the same note', () => {
  const s = state()
  const st = stream('weekly-ops', { bucket: 'do' })
  const a = last(row(st), 'do', s, 'en')
  assert.deepEqual(a.run, { kind: 'act', verb: 'settle',
    args: { keys: [st.key], outcome: 'not_doing', text: en.obsoleteText, stream: true } })
})

test('a tab\'s question keeps its own answers first: Obsolete last where the tab asks about a point', () => {
  const s = state({ tabs: [asking] })
  const alone = logic.bucketAnswers({ group: 'asks', id: 'tab:surface:9', kind: 'tab', tab: asking, row: null }, 'do', s, 'en')
  assert.ok(alone.every(x => x.meaning !== 'obsolete'))
  // round 1 of the four answers: a tab about a task takes the four too, Obsolete closes that task as not done
  const onTask = logic.bucketAnswers({ group: 'asks', id: 'tab:surface:9', kind: 'tab', tab: asking, row: task('t') }, 'do', s, 'en')
  assert.equal(onTask.at(-1).meaning, 'obsolete')
  const item = ask('20261009-0900-q1')
  const onItem = logic.bucketAnswers({ group: 'asks', id: 'tab:surface:9', kind: 'tab', tab: asking, row: item }, 'do', s, 'en')
  assert.equal(onItem.at(-1).meaning, 'obsolete')
  assert.equal(onItem.at(-1).run.args.keys[0], item.key)
  assert.equal(onItem[0].run.kind, 'reply', 'the tab\'s own answer stays first')
})

test('a row that cannot be settled, or is read only, offers no Obsolete', () => {
  const s = state()
  assert.ok(logic.bucketAnswers(row(task('t', { settle: ['done'] })), 'plan', s, 'en').every(x => x.meaning !== 'obsolete'))
  assert.ok(logic.bucketAnswers({ ...row(task('t')), readOnly: true }, 'plan', s, 'en').every(x => x.meaning !== 'obsolete'))
})

// ---------------------------------------------------------------- the card and the bar

test('the card: Obsolete is the last, quiet button; a click asks in place, Yes sends the act, Cancel takes it back', async () => {
  const c = recorder()
  const t = task('old-plan', { bucket: 'plan' })
  const el = mount(html`<${FlowPage} s=${state({ work: [t] })} c=${c} />`)
  await rounds()
  const buttons = el.$$('.fb-answers button')
  const ob = buttons.at(-1)
  assert.equal(ob.text(), en.obsolete)
  assert.ok(ob.hasClass('fb-answer-obsolete'))
  assert.ok(!ob.hasClass('btn-primary'))
  ob.click()
  await rounds()
  assert.equal(c.calls.find(x => x[0] === 'act'), undefined, 'nothing goes before the yes')
  assert.equal(el.$('.fb-confirm-q').text(), en.obsoleteAsk)
  assert.equal(el.$('.fb-answers .fb-answer-obsolete'), null, 'the confirm stands in its place')
  el.$('.fb-confirm-no').click()
  await rounds()
  assert.equal(el.$('.fb-confirm'), null)
  el.$('.fb-answers .fb-answer-obsolete').click()
  await rounds()
  el.$('.fb-confirm-yes').click()
  await waitFor(() => c.calls.some(x => x[0] === 'act'), { what: 'the act after the yes' })
  assert.deepEqual(c.calls.find(x => x[0] === 'act'), ['act', 'settle', { keys: [t.key], outcome: 'not_doing', text: en.obsoleteText, was: 'doing' }])
  assert.doesNotMatch(el.text(), /\b(enter|esc|shortcut)\b/i)
})

test('the bar of a list row: Obsolete stands last, never the strong one', async () => {
  const c = recorder()
  const t = task('old-plan', { bucket: 'delegate' })
  const s = state({ work: [t] })
  const el = mount(html`<${BucketBar} x=${logic.rowPoint(t, s)} s=${s} c=${c} />`)
  await rounds()
  assert.ok(!el.$('.btn-primary').hasClass('fb-answer-obsolete'))
  const rest = el.$$('.fb-bar button')
  assert.ok(rest.at(-1).hasClass('fb-answer-obsolete'))
  rest.at(-1).click()
  await rounds()
  assert.equal(el.$('.fb-confirm-q').text(), en.obsoleteAsk)
  el.$('.fb-confirm-yes').click()
  await waitFor(() => c.calls.some(x => x[0] === 'act'), { what: 'the act after the yes' })
  assert.equal(c.calls.find(x => x[0] === 'act')[1], 'settle')
})

// ---------------------------------------------------------------- the instruction line under the card

test('the card in bucket mode has the free line again: Instruct and Ask, scoped to the point', async () => {
  const t = task('bridges', { bucket: 'plan' })
  const el = mount(html`<${FlowPage} s=${state({ work: [t], instruct: true })} c=${recorder()} />`)
  await rounds()
  const line = el.$('.fb-main .flow-instruct')
  assert.ok(line, 'the line under the card')
  assert.match(line.text(), new RegExp(text.TABLES.en.flow.ask.instruct))
  assert.match(line.text(), new RegExp(text.TABLES.en.flow.ask.ask))
  assert.match(el.$('.fb-main .flow-instruct-scope').text(), /Task bridges/)
})

test('without the instruction switch the line still asks about the point; a tab alone has none', async () => {
  const el = mount(html`<${FlowPage} s=${state({ work: [task('bridges')] })} c=${recorder()} />`)
  await rounds()
  assert.ok(el.$('.fb-main .flow-instruct textarea'), 'Ask about the point')
  const tabOnly = mount(html`<${FlowPage} s=${state({ tabs: [asking] })} c=${recorder()} />`)
  await rounds()
  assert.equal(tabOnly.$('.fb-main .flow-instruct'), null)
})
