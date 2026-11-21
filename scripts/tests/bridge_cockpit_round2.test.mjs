// SPDX-License-Identifier: MIT
// Tests of round 2 of the cockpit simulation (21.11.2026): Work through by the briefing's buckets and the views beside
// it act as the printed briefing acts, show what it shows, and never answer one thing for another. No npm dependencies.
//
//   node --test scripts/tests/bridge_cockpit_round2.test.mjs
import test from 'node:test'
import assert from 'node:assert/strict'
import { loadCockpit, mount, recorder, settle as rounds } from './cockpit_render.mjs'

const { html, views, text, logic, triage } = await loadCockpit()
const de = text.TABLES.de.flow.buckets

const NOW = new Date(2026, 9, 9, 12, 0, 0).getTime()
const MIN = 60000
const TOMORROW = '2026-10-10'

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

function state({ now = [], work = [], later = [], tabs = [], buckets = PROFILE, ui = {}, ...rest } = {}) {
  return {
    now: NOW, model: { sections: [{ id: 'now', rows: now }, { id: 'give', rows: [] }, { id: 'work', rows: work },
      { id: 'track', rows: [] }, { id: 'later', rows: later }], hidden: [], returns: [], buckets },
    tabs: { tabs, at_ms: NOW }, driver: { caps: { key: true, send: true, focus: true, screen: true } }, triage: { items: {} }, jevOrder: {},
    work: { flow: { enabled: true, drop_reasons: ['resolves_itself', 'not_needed'], return_after_s: 20, buckets: { enabled: true } } },
    themes: { enabled: false }, details: { inbox: {}, task: {} }, sessions: { sessions: [] },
    ui: { page: '@flow', busy: {}, flowAt: null, flowChip: 'all', flowJump: null, flowView: 'overview', ...ui }, ...rest,
  }
}
const row = r => ({ group: 'question', id: r.key, kind: 'row', row: r })
const answers = (x, bucket, s, lang = 'de') => logic.bucketAnswers(x, bucket, s, lang)

// the deploy dialog of a task's tab, and an inbox item about that task (a reply draft to Jordan)
const deploy = { ref: '%3', name: 'fix-route-planner-eta', state: 'needs-you', since_ms: NOW - MIN, workspace: 'Home', slug: 'fix-route-planner-eta',
  item: null, live: true, ask: { text: './deploy.sh --env staging route-planner\nDo you want to proceed?\n❯ 1. Yes\n2. Yes, and don\'t ask again\n3. No',
    hash: 'd1', options: [{ n: 1, label: 'Yes' }, { n: 2, label: 'Yes, and don\'t ask again' }, { n: 3, label: 'No' }] } }

test('Do\'s Yes is the briefing\'s yes: the item approved, and Go of I\'ll do it stays a start', () => {
  const s = state()
  const item = ask('20261009-0900-q1')
  const [yes] = answers(row(item), 'do', s)
  assert.deepEqual(yes.run, { kind: 'act', verb: 'do_it', args: { keys: [item.key], yes: true } })
  const [go] = answers(row({ ...item, bucket: 'delegate' }), 'delegate', s)
  assert.deepEqual(go.run, { kind: 'act', verb: 'do_it', args: { keys: [item.key] } })
  // an inbox item a tab works on still takes the yes (the tab is not started twice: the server only approves)
  const worked = ask('20261009-0901-q2', { tab: { ref: '%9', live: true } })
  assert.equal(answers(row(worked), 'do', s)[0].run.args.yes, true)
})

test('Not now of I\'ll do it leaves the point as it is: nothing is written, the walk moves on', async () => {
  const s = state()
  const t = task('t', { bucket: 'delegate' })
  const notNow = answers(row(t), 'delegate', s)[1]
  assert.equal(notNow.meaning, 'later')
  assert.deepEqual(notNow.run, { kind: 'skip' })
  const calls = []
  const c = new Proxy({}, { get: (_, p) => (p === 'then' || typeof p === 'symbol' ? undefined : (...a) => { calls.push([p, ...a]) }) })
  const el = mount(html`<${views.flowbuckets.BucketCard} x=${row(t)} bucket="delegate" s=${s} c=${c} onDone=${() => calls.push(['done'])} />`)
  el.$$('.fb-answers button').find(b => b.text() === 'Nicht jetzt').click()
  await rounds()
  assert.ok(!calls.some(x => x[0] === 'act'), 'no act')
  assert.ok(calls.some(x => x[0] === 'done'), 'the walk moves on')
})

test('an inbox item put off to a day the briefing still shows stands in the briefing\'s bucket, back on that day', () => {
  const later = ask('20261009-0901-off', { inbox_state: 'deferred', until: TOMORROW, bucket: 'plan', brief_nr: 4 })
  const s = state({ now: [ask('20261009-0900-q1')], later: [later] })
  const { buckets } = logic.bucketPoints(s, 'de')
  assert.ok(buckets.find(b => b.id === 'plan').points.some(p => p.id === later.key))
})

test('an inbox row about a task whose tab asks keeps its own answers; only the tab\'s own item stands as the tab', () => {
  const s = state({ tabs: [deploy] })
  const reply = ask('20260930-1100-reply-to-jordan-about-the-route-planner', { task: 'fix-route-planner-eta', tab: { ref: '%3', live: true, state: 'needs-you' } })
  const p = logic.rowPoint(reply, s)
  assert.equal(p.kind, 'row', 'the deploy dialog is no answer to the reply draft')
  assert.ok(!answers(p, logic.viewBucket(p), s).some(a => a.run.kind === 'reply'))
  // the task row of that tab still stands as the tab
  assert.equal(logic.rowPoint(task('fix-route-planner-eta', { tab: { ref: '%3', live: true } }), s).kind, 'tab')
  // and an inbox item the tab itself works on
  const own = ask('20260930-1101-own', { tab: { ref: '%4' } })
  assert.equal(logic.rowPoint(own, state({ tabs: [{ ...deploy, ref: '%4', slug: null, item: '20260930-1101-own' }] })).kind, 'tab')
})

test('Next never promises a Yes the card does not offer', () => {
  const s = state()
  // a yes already given: the Bridge runs it
  const yes = ask('20261009-0900-q1', { inbox_state: 'approved', bucket: 'delegate' })
  assert.equal(logic.nextSentence(row(yes), 'delegate', s, 'de'), de.nextApproved)
  // an id the server refuses: nothing to answer here
  const bad = ask('20260930-1530-robin:-new-storage-key-reference-for-the')
  assert.equal(answers(row(bad), 'do', s).length, 0)
  assert.equal(logic.nextSentence(row(bad), 'do', s, 'de'), de.nextNone)
  // a task an agent tab works on: no second start
  const busy = task('busy', { bucket: 'do', tab: { ref: '%7', live: true } })
  assert.ok(!answers(row(busy), 'do', s).some(a => a.meaning === 'yes'))
  assert.equal(logic.nextSentence(row(busy), 'do', s, 'de'), de.nextWorking)
})

test('a card quotes the briefing\'s own answer of the bucket the briefing has the point in', async () => {
  // a start got lost: the cockpit asks in Do, the briefing still has no. 8 under Waiting on others
  const t = task('price-list', { bucket: 'waiting', brief_nr: 8 })
  const el = mount(html`<${views.flowbuckets.BucketCard} x=${{ ...row(t), group: 'lost' }} bucket="do" s=${state()} c=${recorder()} />`)
  assert.match(el.$('.fb-nr').text(), /„8 nachfassen“|"8 nachfassen"|8 nachfassen/)
  assert.doesNotMatch(el.$('.fb-nr').text(), /8 ja/)
  await rounds()
})

// ---------------------------------------------------------------- words to a tab

const drafted = { ref: '%6', name: 'update-the-data-import', state: 'waiting', since_ms: NOW - 3 * MIN, workspace: 'Home', live: true,
  ask: { text: 'Soll ich den Haken in der Aufgabe setzen?\n❯ #', hash: 'h6', draft: true, suggestion: null, yes_no: true } }

test('Message is never offered where words cannot go: a dialog takes its options, a draft is in the way', async () => {
  const s = state({ tabs: [deploy, drafted] })
  for (const tab of [deploy, drafted]) {
    const el = mount(html`<${views.detail.TabControls} tab=${tab} s=${s} c=${recorder()} />`)
    assert.ok(!el.$$('button').some(b => /^(message|Nachricht)$/.test(b.text().trim())), `no Message on ${tab.name}`)
  }
  assert.equal(logic.canMessage(deploy), false)
  assert.equal(logic.canMessage(drafted), false)
  assert.equal(logic.canMessage({ ...drafted, ask: { text: 'Done.', hash: 'x', draft: false } }), true)
  await rounds()
})

test('the tab overlay offers no line to type into a dialog or onto a draft, and says why', () => {
  // views/tabs.js TabView shows its sentence in place of the line where tabNoSend names a reason
  assert.equal(logic.tabNoSend(deploy, false), 'dialog')
  assert.equal(logic.tabNoSend(drafted, false), 'draft')
  assert.equal(logic.tabNoSend({ ...drafted, ask: { text: 'Done.', draft: false } }, false), null)
  // the control session takes words through the relay, whatever its screen shows
  assert.equal(logic.tabNoSend(deploy, true), null)
  assert.ok(text.TABLES.de.tabNoSendDialog && text.TABLES.de.tabNoSendDraft)
})

test('a tab whose prompt holds a draft offers the way to the tab and says what is in the way', async () => {
  const s = state({ tabs: [drafted] })
  const x = { group: 'asks', id: 'tab:%6', kind: 'tab', tab: drafted, row: null }
  const a = answers(x, 'do', s)
  assert.equal(a[0]?.run?.verb, 'tab_jump')
  const el = mount(html`<${views.flowbuckets.BucketCard} x=${x} bucket="do" s=${s} c=${recorder()} />`)
  assert.ok(el.$('.fb-answers button'), 'one answer at least')
  assert.match(el.text(), /Entwurf|typed|draft/i)
  const reply = mount(html`<${views.reply.TabReply} tab=${drafted} s=${s} c=${recorder()} noJump />`)
  assert.ok(reply.$('.reply-draft'), 'the reply says a draft is in the way, also without a button')
  await rounds()
})

// ---------------------------------------------------------------- two browsers

test('an answer names the state the page saw the point in, so the server refuses one that moved on meanwhile', async () => {
  const item = ask('20261009-0900-q1')
  assert.deepEqual(logic.withWas({ verb: 'later', args: { key: item.key, until: TOMORROW } }, item),
    { verb: 'later', args: { key: item.key, until: TOMORROW, was: 'open' } })
  const t = task('t', { bucket: 'drop', status: 'doing' })
  assert.equal(logic.withWas({ verb: 'task_park', args: { key: t.key } }, t).args.was, 'doing')
  // a verb that does not take it, or a row without a state, goes as it was
  assert.deepEqual(logic.withWas({ verb: 'tab_jump', args: { tab_ref: '%1' } }, item), { verb: 'tab_jump', args: { tab_ref: '%1' } })
  assert.equal(logic.withWas({ verb: 'settle', args: { keys: ['issue:x'] } }, { key: 'issue:x' }).args.was, undefined)
  const calls = []
  const c = new Proxy({}, { get: (_, p) => (p === 'then' || typeof p === 'symbol' ? undefined
    : (...a) => { calls.push([p, ...a]); return p === 'act' ? Promise.resolve({ ok: true }) : undefined }) })
  const el = mount(html`<${views.flowbuckets.BucketCard} x=${row(item)} bucket="do" s=${state()} c=${c} />`)
  el.$$('.fb-answers button').find(b => b.text() === 'Später').click()
  await rounds()
  assert.equal(calls.find(x => x[0] === 'act')[2].was, 'open')
  assert.ok(text.TABLES.de.errors.point_moved && text.TABLES.en.errors.point_moved)
})

test('a point answered here leaves its bucket at once and comes back only if the next collection still holds it', () => {
  const a = ask('20261009-0900-a')
  const b = ask('20261009-0901-b')
  const s = state({ now: [a, b] })
  s.model.collected_ms = NOW - 1000
  const answered = { flowAnswered: { [a.key]: { ms: NOW - 500, bucket: 'do' } } }
  const ids = st => logic.bucketPoints(st, 'de').all.map(x => x.id)
  assert.deepEqual(ids({ ...s, ui: { ...s.ui, ...answered } }), [b.key], 'gone at once, not after the next collection')
  assert.deepEqual(ids({ ...s, model: { ...s.model, collected_ms: NOW }, ui: { ...s.ui, ...answered } }).sort(), [a.key, b.key].sort(),
    'a point the next collection still holds (Wait on a task that waits) is back')
  assert.deepEqual(ids({ ...s, now: NOW + 61000, ui: { ...s.ui, ...answered } }).sort(), [a.key, b.key].sort(), 'never hidden for long')
})

test('a card another browser answered stays in place with a word and the way on, it never swaps under the pointer', async () => {
  const b = ask('20261009-0901-b')
  const c = recorder()
  const s = state({ now: [b], ui: { flowView: 'buckets', flowBucket: 'do', flowBucketAt: { id: 'inbox:20261009-0900-gone', i: 0 } } })
  const el = mount(html`<${views.flow.FlowPage} s=${s} c=${c} />`)
  await rounds()
  assert.ok(el.$('.fb-moved'), 'a word that the point was answered elsewhere')
  assert.equal(el.$('.fb-answers'), null, 'no answers under the pointer')
  el.$('.fb-moved button').click()
  assert.deepEqual(c.calls.at(-1), ['flowBucketGo', b.key, 0])
  // the point answered here: the next card stands at once
  const own = mount(html`<${views.flow.FlowPage} s=${{ ...s, ui: { ...s.ui, flowAnswered: { 'inbox:20261009-0900-gone': { ms: NOW, bucket: 'do' } } } }} c=${recorder()} />`)
  await rounds()
  assert.equal(own.$('.fb-moved'), null)
})

test('a bucket says it is done only after something was answered in it, else that it holds nothing today', async () => {
  const s = state({ work: [task('quiet', { bucket: 'drop' })], ui: { flowView: 'buckets', flowBucket: 'delegate' } })
  const el = mount(html`<${views.flow.FlowPage} s=${s} c=${recorder()} />`)
  await rounds()
  assert.match(el.$('.fb-empty').text(), new RegExp(text.TABLES.en.flow.buckets.empty))
  const done = mount(html`<${views.flow.FlowPage} s=${{ ...s, ui: { ...s.ui, flowAnswered: { 'task:x': { ms: NOW, bucket: 'delegate' } } } }} c=${recorder()} />`)
  await rounds()
  assert.match(done.$('.fb-empty').text(), new RegExp(text.TABLES.en.flow.buckets.cleared))
})

test('the walk stands right under the card, above the free line, never sticky under it', async () => {
  const s = state({ now: [ask('20261009-0900-a'), ask('20261009-0901-b')], ui: { flowView: 'buckets' } })
  const el = mount(html`<${views.flow.FlowPage} s=${s} c=${recorder()} />`)
  await rounds()
  const kids = el.$('.fb-main').childNodes.map(k => k.getAttribute?.('class') ?? '')
  assert.ok(kids.findIndex(k => /fb-walk/.test(k)) < kids.findIndex(k => /fb-dock/.test(k)), kids.join(' | '))
  const { readFileSync } = await import('node:fs')
  const css = readFileSync(new URL('../web/flow.css', import.meta.url), 'utf8')
  assert.doesNotMatch(css.match(/\.fb-walk \{[^}]*\}/)[0], /sticky/)
})

// ---------------------------------------------------------------- what a tab says, on every view

test('a tab\'s lines are its own words: no tool output, no tool call, no mode line', () => {
  const screen = '⏺ Ich prüfe die Backup-Logs von Fabrikam.\n⏺ Bash(grep -c FAILED backup.log)\n  ⎿  3\n✶ Investigating… (esc to interrupt)\n⏵⏵ accept edits on (shift+tab to cycle)'
  assert.deepEqual(logic.tabLines(screen), ['Ich prüfe die Backup-Logs von Fabrikam.'])
  assert.equal(logic.tabWords({ last: '  ⎿  3' }), '')
  assert.equal(logic.tabWords({ last: '▸▸ accept edits on (shift+tab to cycle)' }), '')
  assert.deepEqual(logic.tabLines('▸▸ accept edits on (shift+tab to cycle)'), [])
})

test('an entry of what runs opens beside the buckets, never in the classic layout, and a session is named', async () => {
  const working = { ref: 'surface:5', name: 'fabrikam-backup', state: 'working', slug: 'backup', since_ms: NOW - 5 * MIN, workspace: 'Home', live: true,
    last: '▸▸ accept edits on (shift+tab to cycle)' }
  const s = state({ work: [task('backup'), task('other')], tabs: [working], driver: { caps: ['tabs', 'launch', 'focus', 'screen'] } })
  const runs = logic.runningOf(logic.flowParts(s))
  const id = runs.loose[0]?.id ?? runs.sessions[0]?.entry?.id
  assert.ok(id, 'the backup runs')
  const el = mount(html`<${views.flow.FlowPage} s=${{ ...s, ui: { ...s.ui, flowView: 'run', flowRunId: id } }} c=${recorder()} />`)
  await rounds()
  assert.ok(el.$('.fb-grid'), 'the buckets stay on the left')
  assert.ok(el.$('.fb-main .fx-hero'), 'the running card in the middle')
  assert.doesNotMatch(el.$('.fb-main').text(), /accept edits/)
  // a busy session without a tab is named by its own name
  assert.equal(views.flowbuckets.runTitle({ session: { name: 'ops review', id: 's1' } }), 'ops review')
})

test('a tab card in the column shows what it asks before its answer, and one More only', async () => {
  const s = state({ tabs: [deploy] })
  const el = mount(html`<${views.tabs.TabCard} tab=${deploy} s=${s} c=${recorder()} byKey=${new Map()} slim />`)
  assert.match(el.text(), /Do you want to proceed\?/, 'the question stands with its answer')
  const words = el.$$('button').map(b => b.text().trim().toLowerCase())
  assert.ok(words.filter(w => w === 'more' || w === 'mehr').length <= 1, words.join(' | '))
  await rounds()
})

test('a row of By source names its number in the briefing on its bar, and offers what every other view offers', async () => {
  const item = ask('20261009-0900-q1', { brief_nr: 3 })
  const s = state({ now: [item] })
  const el = mount(html`<${views.day.RowBar} row=${item} s=${s} c=${recorder()} pin=${false} nr />`)
  assert.ok(el.$('.fb-chip-nr'), 'the number on the bar')
  const due = mount(html`<${views.day.RowBar} row=${item} s=${s} c=${recorder()} pin=${false} />`)
  assert.equal(due.$('.fb-chip-nr'), null, 'Due names it at the row start')
  await rounds()
})

test('the bucket strip of By source counts every row of the page: the rows not shown yet are loaded', async () => {
  const { TriageBar } = triage
  const c = recorder()
  const s = state()
  mount(html`<${TriageBar} s=${s} c=${c} items=${[]} byKey=${new Map()} more=${['work/inbox']} />`)
  await rounds()
  assert.deepEqual(c.calls.find(x => x[0] === 'loadMore'), ['loadMore', 'work', 'inbox'])
})

// ---------------------------------------------------------------- Jev

test('Jev after a failed daily order says so on every visit that day, in plain words, never "nothing to rate"', async () => {
  const { jevAnswer, jevErrorText } = (await loadCockpit()).jev
  const failed = jevAnswer({ ok: true, data: { order: null, failed_today: true, today: null } })
  assert.equal(failed.ok, false)
  assert.equal(failed.failedToday, true)
  assert.equal(jevAnswer({ ok: true, data: { order: null, today: null } }).data.empty, true, 'no order and no failure: empty')
  // a refusal names its status in words, never the API's JSON
  const raw = 'Jev refused the request (401): {"detail":{"error_type":"authentication_error","message":"Cannot authenticate"}}'
  for (const lang of ['de', 'en']) {
    const said = jevErrorText(raw, lang)
    assert.doesNotMatch(said, /[{}]|error_type|authentication_error/)
    assert.match(said, /401/)
  }
})

test('"waiting on you" is one count everywhere while the buckets are on: the points of Do (you, today)', () => {
  const a = ask('20261009-0900-a')
  const b = ask('20261009-0901-b', { area: 'Ops' })
  const later = ask('20261009-0902-c', { bucket: 'plan' })
  const s = state({ now: [a, b, later], work: [task('t', { bucket: 'do' })] })
  const rows = logic.waitingRows(s)
  assert.deepEqual(rows.map(r => r.key).sort(), [a.key, b.key, 'task:t'].sort())
  assert.equal(logic.startWaiting(s), 3)
  assert.equal(logic.flowWaiting(s), 3)
  assert.equal(logic.startWaiting(s, 'Ops'), 1)
})

test('once the server answers again its "does not answer" toast goes, and the header says the loss in a few words', () => {
  const de2 = text.TABLES.de
  const toasts = [{ id: 1, text: de2.errors.network, tone: 'bad' }, { id: 2, text: 'Verworfen', tone: 'ok' }]
  assert.deepEqual(logic.backOnline(toasts, de2).map(x => x.id), [2])
  assert.ok(de2.connLost.length <= 16 && !/,/.test(de2.connLost), de2.connLost)
})

test('the task board says its own words for its columns, and Hide is no Keep: one word, one act', () => {
  // its columns sort by who has the next move, not by the briefing's buckets: they never carry a bucket's name
  assert.deepEqual(logic.bucketWords(state(), 'de').columns, {})
  const tb = text.TABLES.de.taskboard
  assert.notEqual(tb.keep, 'Behalten', 'the tidy button only hides here; Behalten is the briefing\'s keep')
  assert.doesNotMatch(tb.tidyHint, /Behalten/)
})
