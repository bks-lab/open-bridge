// SPDX-License-Identifier: MIT
// Pure helpers of the Jev page (scripts/web/jev/logic.js, jev/motion.js): node --test scripts/tests/bridge_cockpit_jev.test.mjs
import { test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import os from 'node:os'
import { fileURLToPath, pathToFileURL } from 'node:url'

const WEB = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'web')

// The page's modules are ES modules in .js files; outside the repo (a worktree under /tmp) node
// would read them as CommonJS. So, as bridge_cockpit_frontend.test.mjs does, copy them into a temp
// dir as .mjs, in the same layout, with their relative imports pointing at the copies
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'bridge-cockpit-jev-'))
for (const rel of ['motion.js', 'jev/motion.js', 'jev/logic.js']) {
  const src = fs.readFileSync(path.join(WEB, rel), 'utf8').replace(/(from\s+'\.{1,2}\/[^']+)\.js'/g, "$1.mjs'")
  fs.mkdirSync(path.dirname(path.join(tmp, rel)), { recursive: true })
  fs.writeFileSync(path.join(tmp, rel.replace(/\.js$/, '.mjs')), src)
}
process.on('exit', () => fs.rmSync(tmp, { recursive: true, force: true }))
const logic = await import(pathToFileURL(path.join(tmp, 'jev', 'logic.mjs')).href)
const motion = await import(pathToFileURL(path.join(tmp, 'jev', 'motion.mjs')).href)
const shared = await import(pathToFileURL(path.join(tmp, 'motion.mjs')).href)

const MODEL = {
  seq: 3,
  sections: [{ rows: [
    { key: 'inbox:a', title: 'Customer waits', tab: { ref: 'surface:7', live: true }, actions: [{ id: 'advise' }] },
    { key: 'task:b', title: 'Tidy the labels', actions: [{ id: 'advise' }] },
    { key: 'inbox:a', title: 'Customer waits' },
  ] }],
  task_rows: [{ key: 'task:c', title: 'Sign the offer' }, { key: 'task:d', title: '' }],
}

test('the springs come from the dashboard motion.js, not from a copy', () => {
  for (const name of ['spring', 'springTo', 'settled', 'clamp', 'ramp', 'o3', 'flowAlpha', 'reducedMotion', 'nowSec']) {
    assert.equal(motion[name], shared[name], name)
  }
  const src = fs.readFileSync(path.join(WEB, 'jev', 'motion.js'), 'utf8')
  assert.doesNotMatch(src, /export function spring\(/)
})

test('modelRows and pendingTitles follow the server order, each row once', () => {
  assert.deepEqual(logic.modelRows(MODEL).map(r => r.key), ['inbox:a', 'task:b', 'task:c'])
  assert.deepEqual(logic.pendingTitles(MODEL, 2), ['Customer waits', 'Tidy the labels'])
  assert.deepEqual(logic.pendingTitles(null), [])
})

test('place keeps a task on its spot when other tasks come or go', () => {
  const a = { key: 'task:x', urgency: 0.8, impact: 0.2, priority: 0.5 }
  assert.deepEqual(logic.place(a), logic.place({ ...a }))
  const p = logic.place(a)
  assert.ok(p.x > logic.CORE.x && p.y > logic.CORE.y, 'urgent, low impact: lower right')
  assert.ok(p.x <= logic.X1 - 14 && p.y <= logic.Y0 - 14)
  assert.equal(p.r, 6 + 17 * 0.5)
  assert.notDeepEqual(logic.place({ ...a, key: 'task:y' }), p)
})

test('liveItems drops tasks that left the dashboard and moves the first on', () => {
  const plan = { first: 't2', items: [
    { id: 't2', key: 'gone', rank: 1 }, { id: 't1', key: 'task:b', rank: 2 }, { id: 't3', key: 'inbox:a', rank: 3 }] }
  const live = logic.liveItems(plan, MODEL)
  assert.deepEqual(live.items.map(it => it.key), ['task:b', 'inbox:a'])
  assert.equal(live.first.key, 'task:b')
  assert.equal(logic.liveItems(plan, null).items.length, 3)
  assert.equal(logic.liveItems(null, MODEL).first, null)
})

test('orderPlan turns a work page order into the plan the matrix draws', () => {
  const order = { at_ms: 5, first: 'task:b', usage: { input_tokens: 3, output_tokens: 4 }, sent: 2, calls: 1,
    items: [{ key: 'task:b', rank: 1, title: 'Tidy', urgency: 1, impact: 1, priority: 0.9, confidence: 0.8, quadrant: 'now', who: 'me' },
      { key: 'inbox:z', rank: 2, title: 'Only on the page', urgency: 0, impact: 0, priority: 0.1, quadrant: 'drop', who: 'delegate' }] }
  const data = logic.orderPlan(order)
  assert.equal(data.plan.first, 'task:b')
  assert.deepEqual(data.plan.items.map(it => it.id), ['task:b', 'inbox:z'])
  assert.equal(data.at_ms, 5)
  assert.equal(data.digest, 'order:5')
  assert.deepEqual(data.usage, { input_tokens: 3, output_tokens: 4 })
  assert.equal(logic.orderPlan(null), null)
  assert.ok(logic.orderPlan({ items: [] }).empty)
  // a row only the work page holds (not in the briefing) stays in the picture when its key is known
  const live = logic.liveItems(data.plan, MODEL, new Set(['inbox:z']))
  assert.deepEqual(live.items.map(it => it.key), ['task:b', 'inbox:z'])
  assert.equal(live.first.key, 'task:b')
  assert.deepEqual(logic.liveItems(data.plan, MODEL).items.map(it => it.key), ['task:b'])
})

test('rowJump: a live tab first, else advise, else nothing', () => {
  const [a, b, c] = logic.modelRows(MODEL)
  assert.deepEqual(logic.rowJump(a), { verb: 'tab_jump', args: { tab_ref: 'surface:7' }, busy: 'surface:7' })
  assert.deepEqual(logic.rowJump(b), { verb: 'advise', args: { keys: ['task:b'] }, busy: 'task:b' })
  assert.equal(logic.rowJump(c), null)
  assert.equal(logic.rowJump({ ...a, tab: { ref: 'surface:7', live: false }, actions: [] }), null)
  assert.equal(logic.rowJump(undefined), null)
})

test('planOpen: a dashboard row peeks, a row only the work page holds opens its drawer', () => {
  const byKey = new Map(logic.modelRows(MODEL).map(r => [r.key, r]))
  assert.deepEqual(logic.planOpen({ key: 'task:b', title: 'Tidy the labels' }, byKey, null), { how: 'peek', key: 'task:b' })
  // a deferred inbox item stands only on the work page: not in the model, but in extra
  const extra = ['inbox:20261008-1535-x', 'task:closed-one', 'idea:7']
  assert.deepEqual(logic.planOpen({ key: 'inbox:20261008-1535-x', title: 'Evaluate' }, byKey, extra),
    { how: 'item', key: 'inbox:20261008-1535-x', it: { inbox: '20261008-1535-x', title: 'Evaluate' } })
  assert.deepEqual(logic.planOpen({ key: 'task:closed-one', title: 'Old' }, byKey, extra),
    { how: 'item', key: 'task:closed-one', it: { task: 'closed-one', title: 'Old' } })
  // another kind of page row has no drawer of its own; a key nowhere opens nothing
  assert.equal(logic.planOpen({ key: 'idea:7', title: 'Idea' }, byKey, extra), null)
  assert.equal(logic.planOpen({ key: 'inbox:gone', title: 'Gone' }, byKey, extra), null)
  assert.equal(logic.planOpen({ key: 'inbox:gone', title: 'Gone' }, byKey, null), null)
})

test('mockRating answers in the server shape with the real row keys, tokens and no price', () => {
  const r = logic.mockRating(MODEL)
  assert.equal(r.ok, true)
  assert.deepEqual(r.plan.items.map(it => it.key).sort(), ['inbox:a', 'task:b', 'task:c'])
  assert.deepEqual(r.plan.items.map(it => it.rank), [1, 2, 3])
  assert.equal(r.plan.first, r.plan.items[0].id)
  assert.equal(r.questions, 13)
  assert.equal(r.price, null)
  assert.ok(r.usage.input_tokens > 0 && r.usage.output_tokens > 0)
  assert.deepEqual(logic.mockRating(MODEL), r, 'same rows, same answer')
  assert.notEqual(logic.mockRating(MODEL, 1).digest, r.digest)
  assert.equal(logic.mockRating({ sections: [] }).empty, true)
})

test('the mock server rates by itself once a day, the button always, and sums the day', () => {
  let now = new Date(2026, 9, 10, 9, 0).getTime()
  const run = logic.createMockJev(() => now)
  const a = run(MODEL)
  assert.equal(a.paid, true)
  assert.equal(a.result.today.ratings, 1)
  const b = run(MODEL)
  assert.equal(b.paid, false)
  assert.equal(b.result.cached, true)
  assert.equal(b.result.changed, false)
  const other = { sections: [{ rows: [{ key: 'task:z', title: 'Neu' }] }] }
  now += 3600e3
  const c = run(other)
  assert.equal(c.paid, false, 'later the same day: no second automatic rating')
  assert.equal(c.result.changed, true)
  assert.equal(c.result.at_ms, a.result.at_ms)
  assert.equal(run(other, { cacheOnly: true }).paid, false)
  const f = run(other, { force: true })
  assert.equal(f.paid, true)
  assert.equal(f.result.today.ratings, 2)
  assert.equal(f.result.today.input_tokens, a.result.usage.input_tokens + f.result.usage.input_tokens)
  now += 86400e3
  const d = run(other)
  assert.equal(d.paid, true, 'the first request of a new day rates')
  assert.equal(d.result.today.ratings, 1)
})

test('costLine shows tokens and never a price the API did not name', () => {
  const line = logic.costLine({ usage: { input_tokens: 900, output_tokens: 60 }, today: { input_tokens: 1800, output_tokens: 120, ratings: 2, unknown: 0 }, price: null })
  assert.deepEqual(line, { tokens: 960, today: 1920, ratings: 2, unknown: 0, price: null })
  assert.equal(logic.costLine({ usage: { input_tokens: null, output_tokens: 3 } }), null)
  assert.equal(logic.costLine({}), null)
  assert.equal(logic.tokenText(12345.4, 'de'), '12.345')
  assert.equal(logic.tokenText(12345.4, 'en'), '12,345')
})

test('track follows a target with the dashboard spring and bends on a new one', () => {
  let st = motion.track(null, 0, 0)
  assert.equal(motion.trackAt(st, 0), 0)
  assert.equal(motion.track(st, 0, 1), st, 'same target, same state')
  st = motion.track(st, 1, 10)
  assert.equal(motion.tracking(st), true)
  const mid = motion.trackAt(st, 10.05)
  assert.ok(mid > 0 && mid < 1)
  st = motion.track(st, 0, 10.05)
  assert.ok(Math.abs(motion.trackAt(st, 10.05) - mid) < 1e-9, 'a retarget does not jump')
  assert.equal(motion.trackAt(st, 20), 0)
  assert.equal(motion.tracking(st), false, 'settled collapses to the target')
  const calm = motion.track(motion.track(null, 0, 0), 1, 5, true)
  assert.equal(motion.trackAt(calm, 5), 1, 'reduced motion stands at the target at once')
})

test('cursor blinks a few times and then rests, nothing moves for ever', () => {
  assert.equal(motion.cursorOn(1, 2, 1), true)
  assert.equal(motion.cursorOn(100, 2, 1), false)
  assert.equal(motion.countTo(10, 50, 0, 1, 20), 50)
  assert.equal(motion.countTo(0, 50, 0, 1, 20), 20)
})

test('the Jev page goes through the controller and keeps its own motion copy out', () => {
  const page = fs.readFileSync(path.join(WEB, 'jev', 'page.js'), 'utf8')
  assert.match(page, /c\.peek\(/)
  assert.match(page, /c\.act\(jump\.verb, jump\.args\)/)
  assert.match(page, /c\.jevRun\(/)
  assert.doesNotMatch(page, /mockRun|location\.search\)\.has\('mock'\)/, 'mock mode answers in mock.js, not in the page')
  assert.doesNotMatch(page, /innerHTML/)
  const css = fs.readFileSync(path.join(WEB, 'jev', 'jev.css'), 'utf8')
  assert.doesNotMatch(css, /transition\s*:|@keyframes/)
  assert.doesNotMatch(css, /#[0-9a-fA-F]{3,8}\b|rgb\(/, 'colours only from tokens')
  for (const src of [page, fs.readFileSync(path.join(WEB, 'jev', 'logic.js'), 'utf8')]) assert.doesNotMatch(src, /[–—]/)
})
