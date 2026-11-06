// SPDX-License-Identifier: MIT
// Tests of the read marks of Work through (cockpit.flow.seen: scripts/web/flow.js seenSettings, rowMark, readMark,
// unreadWalk, seenFigures; views/flowmarks.js, flowlist.js, flowside.js, flowsimple.js, verbbar.js), no npm
// dependencies.
//
//   node --test scripts/tests/bridge_cockpit_seen.test.mjs
//
// Read means out of sight until something new happens to the point or its revisit day comes. Opening a point reads it
// (open_reads auto) or Read does (click); a marker the server read (model.moved) that moved past the one the mark kept
// makes it new again; a read point comes back on its revisit day (the day the person set, else its kind's interval). The
// left column counts the unread points bold, the overview folds the read ones under Read (n) and the resting doing
// tasks under Resting (n), Next walks the unread ones only, and Later of the four states is Revisit ▾.
import test from 'node:test'
import assert from 'node:assert/strict'
import { cockpitState, loadCockpit, mount, recorder, settle as rounds } from './cockpit_render.mjs'

const { html, views, text, logic } = await loadCockpit()
const en = text.TABLES.en
const de = text.TABLES.de
const tick = () => rounds()
const until = async (ok, ms = 2000) => { for (const end = Date.now() + ms; !ok() && Date.now() < end;) await tick() }
const proto = Object.getPrototypeOf(document.createElement('div'))
if (!proto.querySelector) proto.querySelector = function querySelector(sel) { return this.$(sel) }
proto.focus ??= function focus() { document.activeElement = this }
globalThis.window ??= { addEventListener() {}, removeEventListener() {}, innerWidth: 1280 }

const NOW = new Date(2026, 9, 9, 12, 0, 0).getTime()
const HOUR = 3600000
const DAY = 24 * HOUR
const TODAY = '2026-10-09'

const task = (slug, over = {}) => ({ key: `task:${slug}`, task: slug, title: `Task ${slug}`, status: 'doing', bucket: 'tasks',
  priority: 'P2', settle: ['done', 'not_doing'], updated: TODAY, ...over })
const ask = (id, over = {}) => ({ key: `inbox:${id}`, inbox_id: id, title: `Question ${id.slice(-2)}`, art: 'ask', gate: 'your-call',
  inbox_state: 'open', bucket: 'now', settle: ['done', 'not_doing'], ...over })
/** A read mark as the server keeps it (seen.py): read `daysAgo` days before NOW with the markers `m` */
const read = (daysAgo, m = {}, over = {}) => ({ at: NOW - daysAgo * DAY, m, until: null, unread: false, ...over })

function state({ work = [], now = [], moved = {}, marks = {}, focus = [], seen = { enabled: true }, ui = {}, flow = {}, ...rest } = {}) {
  return {
    now: NOW, model: { sections: [{ id: 'now', rows: now }, { id: 'give', rows: [] }, { id: 'work', rows: work }, { id: 'track', rows: [] },
      { id: 'later', rows: [] }], hidden: [], returns: [], pages: [], moved },
    tabs: { tabs: [] }, driver: { caps: null }, triage: { items: {} }, jevOrder: {}, home: { tiles: null, seen: null, pins: [] },
    work: { flow: { enabled: true, drop_reasons: ['not_needed'], return_after_s: 20, seen, ...flow } },
    seen: { marks, focus }, themes: { enabled: false }, details: { inbox: {}, task: {}, activity: {} },
    ui: { page: 'briefing', workView: 'flow', busy: {}, flowAt: null, flowChip: 'all', flowJump: null, flowView: 'overview', ...ui }, ...rest,
  }
}
const pointOf = (s, key) => logic.flowQueue(logic.flowParts(s), 'all').find(x => x.row?.key === key)

// ---------------------------------------------------------------- the settings

test('seenSettings: off unless the server says on, the intervals and counts of seen.py, no marks on a person\'s page', () => {
  const off = logic.seenSettings({})
  assert.deepEqual(off, { enabled: false, open_reads: 'auto', active_days: 7, revisit_days: { active: 7, resting: 14, backlog: 30, question: 2, issue: 7 },
    counts: { note: true, status: true, doc: true, run: true, code: true, log: true, inbox: true } })
  const s = state({ seen: { enabled: true, open_reads: 'click', active_days: 3, revisit_days: { question: 1, resting: 0 }, counts: { log: false } } })
  const on = logic.seenSettings(s)
  assert.equal(on.open_reads, 'click')
  assert.equal(on.active_days, 3)
  assert.deepEqual(on.revisit_days, { active: 7, resting: 14, backlog: 30, question: 1, issue: 7 }, 'below 1 keeps the default')
  assert.equal(on.counts.log, false)
  assert.equal(logic.seenOn(s), true)
  assert.equal(logic.seenOn(state({ seen: { enabled: false } })), false)
  assert.equal(logic.seenOn(state({ flow: { enabled: false } })), false, 'no Work through, no marks')
  assert.equal(logic.seenOn({ ...s, boot: { config: { person: 'anna' } } }), false, 'a person keeps no marks')
  assert.equal(logic.flowSettings(s).seen.enabled, true)
})

// ---------------------------------------------------------------- one mark

test('rowMark: never opened, read with its revisit day, new on a counted marker, marked unread, its revisit day come', () => {
  const t = task('a')
  const F = NOW - 2 * DAY        // the task moved two days ago: active
  const at = (over = {}) => logic.rowMark(t, state({ work: [t], moved: { 'task:a': { file: F } }, ...over }))
  assert.deepEqual([at().unread, at().why], [true, { kind: 'never' }])
  const quiet = at({ marks: { 'task:a': read(1, { file: F }) } })
  assert.equal(quiet.unread, false)
  assert.equal(quiet.read, '2026-10-08')
  assert.equal(quiet.back, '2026-10-15', 'an active doing task comes back after 7 days')
  assert.equal(quiet.kind, 'active')
  const fresh = at({ moved: { 'task:a': { file: F, doc: NOW - HOUR } }, marks: { 'task:a': read(1, { file: F }) } })
  assert.deepEqual([fresh.unread, fresh.why], [true, { kind: 'new', what: 'doc', day: TODAY }])
  // a kind the counts leave out moves nothing: note and status both off leave the file alone
  const notCounted = at({ moved: { 'task:a': { file: F + HOUR } }, marks: { 'task:a': read(1, { file: F }) },
    seen: { enabled: true, counts: { note: false, status: false } } })
  assert.equal(notCounted.unread, false)
  assert.equal(at({ moved: { 'task:a': { file: F + HOUR } }, marks: { 'task:a': read(1, { file: F }) }, seen: { enabled: true, counts: { note: false } } }).unread,
    true, 'note and status share the file: one of them on is enough')
  assert.deepEqual(at({ marks: { 'task:a': read(1, { file: F }, { unread: true }) } }).why, { kind: 'forced' })
  const back = at({ marks: { 'task:a': read(8, { file: F }) } })
  assert.deepEqual([back.unread, back.why], [true, { kind: 'revisit', day: '2026-10-08' }])
  // a day the person set wins over the interval
  const set = at({ marks: { 'task:a': read(1, { file: F }, { until: '2026-10-20' }) } })
  assert.deepEqual([set.unread, set.back], [false, '2026-10-20'])
  assert.equal(at({ marks: { 'task:a': read(1, { file: F }, { until: TODAY }) } }).why.kind, 'revisit')
})

test('rowMark: a doing task rests without movement, comes back after the resting interval and asks go on, park or close', () => {
  const old = NOW - 20 * DAY
  const t = task('r', { updated: '2026-09-19' })
  const base = { work: [t], moved: { 'task:r': { file: old } } }
  const act = logic.activeOf(t, state(base))
  assert.deepEqual([act.active, act.days, act.by], [false, 20, null])
  const resting = logic.rowMark(t, state({ ...base, marks: { 'task:r': read(5, { file: old }) } }))
  assert.equal(resting.resting, true)
  assert.equal(resting.kind, 'resting')
  assert.equal(resting.unread, false, 'read 5 days ago, back after 14')
  const due = logic.rowMark(t, state({ ...base, marks: { 'task:r': read(15, { file: old }) } }))
  assert.deepEqual([due.unread, due.why], [true, { kind: 'resting', days: 20 }])
  // in focus, pinned or with an agent on it, it is active
  assert.equal(logic.activeOf(t, state({ ...base, focus: ['task:r'] })).by, 'focus')
  assert.equal(logic.activeOf(t, state({ ...base, home: { pins: ['task:r'] } })).by, 'pin')
  assert.equal(logic.activeOf(t, state({ ...base, seen: { enabled: true, active_days: 30 } })).active, true)
  // not a doing task: no Active
  assert.equal(logic.activeOf(task('b', { status: 'backlog' }), state()), null)
})

test('the intervals by kind: a question after 2 days, an idea after 30, an issue after 7', () => {
  const q = ask('20261001-0900-q-a1')
  assert.equal(logic.rowMark(q, state({ now: [q], marks: { [q.key]: read(2) } })).why.kind, 'revisit')
  assert.equal(logic.rowMark(q, state({ now: [q], marks: { [q.key]: read(1) } })).unread, false)
  assert.equal(logic.revisitKind({ ...q, art: 'idea' }, state()), 'backlog')
  assert.equal(logic.revisitKind({ key: 'ref:o/r#1', ref: 'o/r#1' }, state()), 'issue')
  assert.equal(logic.revisitKind(task('b', { status: 'backlog' }), state()), 'backlog')
})

test('readMark: what asks for you now is unread while it stands, whatever its mark', () => {
  assert.deepEqual(logic.readMark({ group: 'asks', kind: 'tab', tab: { ref: 's:1' } }, state()).why, { kind: 'live' })
  assert.equal(logic.readMark({ group: 'checkin', kind: 'row', row: task('a') }, state({ marks: { 'task:a': read(0) } })).unread, true)
})

// ---------------------------------------------------------------- the lists

test('the left column counts the unread points beside every open one, and only while the marks are on', () => {
  const s = state({ work: [task('a'), task('b'), task('c')], marks: { 'task:a': read(1), 'task:b': read(1) } })
  const sides = logic.flowSides(s, logic.flowQueue(logic.flowParts(s), 'all'), 'areas')
  assert.deepEqual([sides[0].open, sides[0].unread], [3, 1])
  const off = state({ work: [task('a')], seen: { enabled: false } })
  assert.ok(!('unread' in logic.flowSides(off, logic.flowQueue(logic.flowParts(off), 'all'), 'areas')[0]), 'off: the count as before')
})

test('unreadWalk keeps the unread points and the one open; seenFigures counts new and revisits and names the next day', () => {
  const s = state({ work: [task('a'), task('b'), task('c')], marks: { 'task:a': read(1), 'task:b': read(8) } })
  const queue = logic.flowQueue(logic.flowParts(s), 'all')
  assert.deepEqual(logic.unreadWalk(queue, s).map(x => x.id), ['task:b', 'task:c'])
  assert.deepEqual(logic.unreadWalk(queue, s, { id: 'task:a', i: 0 }).map(x => x.id), ['task:a', 'task:b', 'task:c'])
  assert.deepEqual(logic.seenFigures(queue, s), { fresh: 1, revisit: 1, unread: 2, next: { day: '2026-10-15', n: 1 } })
  assert.deepEqual(logic.readKeys(queue, s), ['task:b', 'task:c'])
  assert.equal(en.flow.marks.head(1, 1), '1 new · 1 revisit today')
  assert.equal(de.flow.marks.head(2, 3), '2 neu · 3 Wiedervorlagen heute')
  const off = state({ work: [task('a')], seen: { enabled: false } })
  assert.equal(logic.unreadWalk(logic.flowQueue(logic.flowParts(off), 'all'), off).length, 1)
})

test('Revisit goes out as later with revisit: from the overview\'s batch and the instruction line, never from a Not now list', () => {
  const s = state({ work: [task('a')] })
  assert.deepEqual(logic.flowAction('later', task('a'), '2026-10-12', null, { revisit: true, text: 'ask again' }),
    { verb: 'later', args: { key: 'task:a', until: '2026-10-12', revisit: true, text: 'ask again' } })
  const plan = logic.batchPlan([task('a')], 'later', s, '2026-10-12')
  assert.deepEqual(plan.calls, [{ verb: 'later', args: { key: 'task:a', until: '2026-10-12', by: 'batch', revisit: true } }])
  assert.equal(plan.revisit, true)
  assert.match(en.flow.batch.summary(plan), /1 revisit on Oct 12/)
  assert.deepEqual(logic.batchPlan([task('a')], 'later', state({ work: [task('a')], seen: { enabled: false } }), '2026-10-12').calls[0].args,
    { key: 'task:a', until: '2026-10-12', by: 'batch' }, 'off: as before')
  const left = logic.leftPlan([{ row: task('a'), kind: 'later' }], 'later', s, '2026-10-12')
  assert.equal(left.calls[0].args.revisit, undefined, 'a row of Not now is put off as before')
  const ins = logic.instructCalls({ point: true, steps: [{ op: 'later', keys: ['task:a'], until: '2026-10-12' }] }, s)
  assert.deepEqual(ins.calls, [{ verb: 'later', args: { key: 'task:a', until: '2026-10-12', by: 'instruction', revisit: true } }])
})

test('the fields of an open point: Read mark and Active stand on top while the marks are on', () => {
  const s = state({ work: [task('a')], marks: { 'task:a': read(1) } })
  const x = pointOf(s, 'task:a')
  const { top } = logic.fieldsSplit(logic.flowFields(x, s), x, s)
  assert.deepEqual(top.map(f => f.id), ['area', 'who', 'due', 'readmark', 'active'])
  const off = state({ work: [task('a')], seen: { enabled: false } })
  assert.ok(!logic.flowFields(pointOf(off, 'task:a'), off).some(f => f.id === 'readmark'))
})

test('flowOpenKey: the key U marks the point open unread, only in Work through with the marks on', () => {
  const s = state({ work: [task('a')], ui: { flowView: 'point', flowAt: { id: 'task:a', i: 0 } } })
  assert.equal(logic.flowOpenKey(s), 'task:a')
  assert.equal(logic.flowOpenKey({ ...s, ui: { ...s.ui, flowView: 'overview' } }), null)
  assert.equal(logic.flowOpenKey(state({ work: [task('a')], seen: { enabled: false }, ui: s.ui })), null)
})

// ---------------------------------------------------------------- the views

const { FlowPage } = views.flow
const page = over => cockpitState(NOW, state(over))

test('the overview: unread rows first with a dot and why, the read ones under Read (n), the resting ones under Resting (n)', () => {
  const old = NOW - 20 * DAY
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${page({ work: [task('a'), task('b'), task('c'), task('r', { updated: '2026-09-19' })],
    moved: { 'task:c': { doc: NOW - HOUR }, 'task:r': { file: old } },
    marks: { 'task:a': read(1), 'task:c': read(1), 'task:r': read(2, { file: old }) } })} c=${c} />`)
  const unread = el.$$('.flow-ov-row.is-unread')
  assert.deepEqual(unread.map(r => r.$('.flow-ov-open').text()), ['Task b', 'Task c'])
  assert.equal(unread[0].$('.flow-ov-why').text(), en.flow.marks.why.never)
  assert.match(unread[1].$('.flow-ov-why').text(), /^New: a document \(/)
  const folds = el.$$('.flow-ov-fold')
  assert.deepEqual(folds.map(d => d.$('summary').text()), [en.flow.marks.readFold(1), en.flow.marks.restingFold(1)])
  assert.ok(folds[0].text().includes('Task a') && folds[1].text().includes('Task r'))
  el.button(en.flow.marks.allRead).click()
  assert.deepEqual(c.calls.at(-1), ['flowSeen', ['task:b', 'task:c']])
  assert.ok(el.$('.flow-head').text().includes(en.flow.marks.head(2, 0)))
  // the left column: the unread bold, every open one beside it
  assert.equal(el.$('.flow-side-item.is-all .flow-side-unread').text(), '2')
  assert.equal(el.$('.flow-side-item.is-all .flow-side-open').text(), '4')
})

test('all read: the overview says so and names the next revisit', () => {
  const el = mount(html`<${FlowPage} s=${page({ work: [task('a')], marks: { 'task:a': read(1) } })} c=${recorder()} />`)
  assert.equal(el.$('.flow-ov-allread').text(), en.flow.marks.allDone({ day: '2026-10-15', n: 1 }))
  assert.equal(el.$('.flow-side-item.is-all .flow-side-unread'), null, 'no bold number when nothing is unread')
})

test('opening a point reads it (auto); with click it stays unread and Read stands strong on the right', async () => {
  const c = recorder()
  mount(html`<${FlowPage} s=${page({ work: [task('a'), task('b')], ui: { flowView: 'point', flowAt: { id: 'task:a', i: 0 } } })} c=${c} />`)
  await until(() => c.calls.some(x => x[0] === 'flowSeen'))
  assert.deepEqual(c.calls.find(x => x[0] === 'flowSeen'), ['flowSeen', ['task:a']])
  const k = recorder()
  const el = mount(html`<${FlowPage} s=${page({ work: [task('a')], seen: { enabled: true, open_reads: 'click' },
    ui: { flowView: 'point', flowAt: { id: 'task:a', i: 0 } } })} c=${k} />`)
  await tick()
  assert.ok(!k.calls.some(x => x[0] === 'flowSeen'), 'click: an open reads nothing')
  const btn = el.button(en.flow.marks.read)
  assert.ok(btn.hasClass('btn-primary'))
  btn.click()
  assert.deepEqual(k.calls.at(-1), ['flowSeen', ['task:a']])
})

test('Next walks the unread points; past the last one the bar says All read and when the next comes back', () => {
  const el = mount(html`<${FlowPage} s=${page({ work: [task('a'), task('b')], marks: { 'task:a': read(0), 'task:b': read(1) },
    ui: { flowView: 'point', flowAt: { id: 'task:a', i: 0 } } })} c=${recorder()} />`)
  assert.equal(el.$('.dz-walk-next').text(), en.flow.marks.allDone({ day: '2026-10-15', n: 1 }))
  const two = mount(html`<${FlowPage} s=${page({ work: [task('a'), task('b'), task('c')], marks: { 'task:b': read(1) },
    ui: { flowView: 'point', flowAt: { id: 'task:a', i: 0 } } })} c=${recorder()} />`)
  assert.ok(two.$('.dz-walk-next').text().includes('Task c'), 'the read one in between is skipped')
})

test('the right column: Revisit ▾ in place of Later, its days and a sentence; More: Mark unread and Keep in focus', async () => {
  const c = new Proxy({}, { get: (_, p) => (p === 'calls' ? calls : p === 'then' || typeof p === 'symbol' ? undefined
    : (...a) => { calls.push([p, ...a]); return p === 'act' ? Promise.resolve({ ok: true }) : undefined }) })
  const calls = []
  const el = mount(html`<${FlowPage} s=${page({ work: [task('a')], marks: { 'task:a': read(0) },
    ui: { flowView: 'point', flowAt: { id: 'task:a', i: 0 } } })} c=${c} />`)
  const later = el.button(`${en.flow.marks.revisit} ▾`)
  assert.ok(later, 'Later is Revisit')
  later.click()
  await tick()
  const box = el.$$('.flow-revisit input').find(i => i.getAttribute('placeholder') === en.flow.marks.text)
  box.value = 'ask the vendor'
  box.dispatch('input')
  await tick()
  el.button(en.flow.marks.twoWeeks).click()
  await until(() => calls.some(x => x[0] === 'act'))
  assert.deepEqual(calls.find(x => x[0] === 'act'), ['act', 'later', { key: 'task:a', until: '2026-10-23', revisit: true, text: 'ask the vendor' }])
  el.$('.flow-more-toggle').click()
  await tick()
  el.button(en.flow.marks.markUnread).click()
  await tick()
  assert.ok(calls.some(x => x[0] === 'flowUnread' && x[1] === 'task:a'))
  el.$('.flow-more-toggle').click()
  await tick()
  el.button(en.flow.marks.focus).click()
  assert.ok(calls.some(x => x[0] === 'flowFocus' && x[1] === 'task:a' && x[2] === true))
  // the fields
  assert.match(el.$('.flow-aside [data-field=readmark] dd').text(), /^read /)
  assert.match(el.$('.flow-aside [data-field=active] dd').text(), /^active, last moved /)
})

test('off: nothing of it shows, Later stays Later', () => {
  const el = mount(html`<${FlowPage} s=${page({ work: [task('a')], seen: { enabled: false }, ui: { flowView: 'point', flowAt: { id: 'task:a', i: 0 } } })}
    c=${recorder()} />`)
  assert.equal(el.$('.flow-ov-fold'), null)
  assert.ok(el.button(`${en.flow.simple.later} ▾`))
  assert.equal(el.$('[data-field=readmark]'), null)
})

// ---------------------------------------------------------------- the words

test('the words: both languages under the same keys, German without a dash as punctuation', () => {
  const keys = o => Object.entries(o).flatMap(([k, v]) => (v && typeof v === 'object' ? keys(v).map(x => `${k}.${x}`) : [k])).sort()
  assert.deepEqual(keys(de.flow.marks), keys(en.flow.marks))
  const words = o => Object.values(o).flatMap(v => (typeof v === 'function' ? [v(2, 3), v({ day: '2026-10-15', n: 2 })] : v && typeof v === 'object' ? words(v) : [v]))
  for (const w of words(de.flow.marks)) assert.ok(!/[–—]|\s-\s/.test(String(w)), w)
  assert.equal(de.flow.marks.markUnread, 'Als ungelesen markieren')
  assert.equal(de.flow.marks.allRead, 'Alles als gelesen markieren')
  assert.equal(de.flow.marks.revisit, 'Wiedervorlage')
  assert.equal(de.flow.marks.focus, 'Im Fokus halten')
  assert.equal(de.flow.marks.read, 'Gelesen')
  assert.equal(de.flow.marks.unread, 'Ungelesen')
  assert.match(de.flow.marks.allDone(null), /^Alles gelesen/)
})

// ---------------------------------------------------------------- follow-up: the start page, the instruction line

test('the start page counts new and revisits from the same computation as the Work through head line', () => {
  const s = state({ work: [task('a'), task('b'), task('c')], marks: { 'task:a': read(1), 'task:b': read(8) } })
  const queue = logic.flowQueue(logic.flowParts(s), 'all')
  assert.deepEqual(logic.flowAreas(s).seen, logic.seenFigures(queue, s))
  assert.equal(logic.flowAreas(state({ work: [task('a')], seen: { enabled: false } })).seen, null, 'off: nothing')
})

test('the start page shows the line and leads into Work through; off it stays as it was', () => {
  const { HomePage } = views.home
  const c = recorder()
  const el = mount(html`<${HomePage} s=${cockpitState(NOW, state({ work: [task('a'), task('b')], marks: { 'task:a': read(8) }, ui: { page: '@start' } }))} c=${c} />`)
  const line = el.$('.home-seen')
  assert.ok(line, 'the line stands in the head')
  assert.equal(line.text().trim(), en.flow.marks.head(1, 1))
  line.click()
  assert.deepEqual(c.calls.at(-1), ['goArea', null, { page: '@flow' }])
  const off = mount(html`<${HomePage} s=${cockpitState(NOW, state({ work: [task('a')], seen: { enabled: false }, ui: { page: '@start' } }))} c=${recorder()} />`)
  assert.equal(off.$('.home-seen'), null)
  assert.equal(de.flow.marks.head(1, 1), '1 neu · 1 Wiedervorlage heute')
})

test('the instruction line words a later step as a revisit while the marks are on', () => {
  const { stepWord } = views.flowinstruct
  const st = { op: 'later', until: '2026-10-12' }
  const day = logic.formatDay('2026-10-12', 'en')
  assert.equal(stepWord(st, en.flow.instruct, 'en', state()), en.flow.instruct.op.revisit(day))
  assert.equal(stepWord(st, en.flow.instruct, 'en', state({ seen: { enabled: false } })), en.flow.instruct.op.later(day))
  assert.match(de.flow.instruct.op.revisit('12.10.'), /^Wiedervorlage 12\.10\./)
  assert.equal(en.histDid('revisit on 2026-10-20'), 'revisit on 2026-10-20')
  assert.equal(de.histDid('revisit on 2026-10-20'), 'Wiedervorlage am 2026-10-20')
  assert.equal(en.flow.activity.decision.revisit, 'Revisit')
  assert.equal(de.flow.activity.decision.revisit, 'Wiedervorlage')
})

test('the demo shows the marks with ?seen=1: one read, one new since, the rest never opened; its verbs keep them', async () => {
  const { mock } = await loadCockpit()
  const tr = mock.createMockTransport({ lang: 'en', latency: 0, seen: true })
  const events = []
  tr.events(new Proxy({}, { get: (_, name) => p => events.push([name, p]) }), () => {})
  const st = (await tr.get('/api/state')).data
  assert.equal(st.work.flow.seen.enabled, true)
  const s = { ...st, now: Date.now(), ui: { page: 'briefing', workView: 'flow' } }
  const index = logic.rowMark({ key: 'task:docs-refresh', task: 'docs-refresh', status: 'doing' }, s)
  assert.equal(index.unread, false)
  assert.equal(logic.rowMark({ key: 'task:release-polish', task: 'release-polish', status: 'doing' }, s).why.kind, 'new')
  const act = (verb, args) => tr.post('/api/action', { verb, args })
  await act('seen_read', { keys: ['task:release-polish'] })
  await act('later', { key: 'task:docs-refresh', until: '2099-01-02', revisit: true })
  const after = (await tr.get('/api/state')).data.seen.marks
  assert.equal(after['task:release-polish'].unread, false)
  assert.equal(after['task:docs-refresh'].until, '2099-01-02')
  await new Promise(r => setTimeout(r, 50))
  assert.ok(events.some(([name]) => name === 'seen'), 'the page hears it')
  assert.equal(mock.buildState(Date.now(), {}).work.flow.seen.enabled, false, 'without ?seen=1 the demo is as before')
})
