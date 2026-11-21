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

// ---------------------------------------------------------------- calm animation and a readable matrix

test('cutWords cuts at a word end with an ellipsis, a short text stays whole', () => {
  assert.equal(logic.cutWords('Den Demo-Bericht prüfen', 40), 'Den Demo-Bericht prüfen')
  const long = '„Demo Mi 25.11. 17:30: Produktvision lesen“ am Wed 25.11 17:30 überschneidet sich mit „Produktplanung“'
  const cut = logic.cutWords(long, 80)
  assert.ok(cut.endsWith('…'), cut)
  assert.ok(cut.length <= 80)
  assert.ok(long.startsWith(cut.slice(0, -1).trimEnd()), 'a prefix of the text')
  assert.doesNotMatch(cut, /„Produ…$/, 'never mid-word')
  assert.match(cut, /\S…$/, 'no space before the ellipsis')
  assert.doesNotMatch(cut, /[„(,:;-]…$/, 'no dangling quote or punctuation before the ellipsis')
  // one long word gets a hard cut, still with the ellipsis
  assert.equal(logic.cutWords('abcdefghijklmnopqrstuvwxyz', 10), 'abcdefghi…')
  assert.equal(logic.cutWords('', 10), '')
  assert.equal(logic.cutWords(null, 10), '')
  assert.equal(logic.cutWords('a  b\n c', 10), 'a b c', 'whitespace folds')
})

test('cutWords of a title the server cut mid-word drops the broken word', () => {
  // a title that arrives cut (it is as long as the server's limit) ends with a broken word: drop it, add the ellipsis
  assert.equal(logic.trimCut('am Mi überschneidet sich mit „Produ', 35), 'am Mi überschneidet sich mit…')
  assert.equal(logic.trimCut('Kurz und ganz', 160), 'Kurz und ganz')
  assert.equal(logic.trimCut('Schon mit Ellipse…', 18), 'Schon mit Ellipse…', 'a cut that says so stays')
})

test('playFor: the intro only for a first rating or a replay, an update only for a changed digest', () => {
  const a = { digest: 'd1', at_ms: 1, plan: { items: [{ key: 'k' }] } }
  assert.equal(logic.playFor(null, a), 'intro')
  assert.equal(logic.playFor({ plan: { items: [] } }, a), 'intro')
  assert.equal(logic.playFor(a, { ...a, changed: true, today: {} }), 'keep', 'the kept rating answered again: nothing plays')
  assert.equal(logic.playFor(a, { ...a, digest: 'd2', at_ms: 2 }), 'update')
  assert.equal(logic.playFor(a, { ok: true, empty: true, plan: { items: [] } }), 'none')
  assert.equal(logic.playFor(a, a, { replay: true }), 'intro')
})

test('readingFor: a background check never shows the reading scene over a drawn picture', () => {
  assert.equal(logic.readingFor({ force: true, hasPlan: true }), 'now')
  assert.equal(logic.readingFor({ force: true, hasPlan: false }), 'now')
  assert.equal(logic.readingFor({ force: false, hasPlan: true }), 'never')
  assert.equal(logic.readingFor({ force: false, hasPlan: false }), 'later')
  // a background check while a click's rating runs waits for it instead of cancelling it
  assert.equal(logic.checkWins({ force: false, running: 'force' }), false)
  assert.equal(logic.checkWins({ force: true, running: 'force' }), true)
  assert.equal(logic.checkWins({ force: false, running: 'check' }), true)
  assert.equal(logic.checkWins({ force: false, running: null }), true)
})

test('cursorShown: the typing cursor shows only while the line types', () => {
  assert.equal(logic.cursorShown(2.0, 2.7, 1.1), false, 'not before')
  assert.equal(logic.cursorShown(3.0, 2.7, 1.1), true, 'while typing')
  assert.equal(logic.cursorShown(3.9, 2.7, 1.1), false, 'gone once the line stands')
  assert.equal(logic.cursorShown(100, 2.7, 1.1), false)
})

const overlap = (a, b) => a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1
const circleHitsRect = (c, r) => {
  const nx = Math.max(r.x0, Math.min(c.x, r.x1)), ny = Math.max(r.y0, Math.min(c.y, r.y1))
  return Math.hypot(c.x - nx, c.y - ny) < c.r
}

test('separate pushes overlapping points apart, deterministic and inside the matrix', () => {
  const pts = ['a', 'b', 'c', 'd', 'e'].map((key, i) => ({ key, x: 500, y: 300, r: 10 + i }))
  const box = { x0: logic.X0, x1: logic.X1, y0: logic.Y1, y1: logic.Y0 }
  const out = logic.separate(pts, { gap: 4, box })
  assert.deepEqual(logic.separate(pts, { gap: 4, box }), out, 'same input, same picture')
  const list = pts.map(p => out.get(p.key))
  for (let i = 0; i < list.length; i++) {
    for (let j = i + 1; j < list.length; j++) {
      const d = Math.hypot(list[i].x - list[j].x, list[i].y - list[j].y)
      assert.ok(d >= list[i].r + list[j].r + 4 - 0.5, `${pts[i].key}/${pts[j].key} ${d.toFixed(1)}`)
    }
    assert.ok(list[i].x - list[i].r >= box.x0 && list[i].x + list[i].r <= box.x1)
    assert.ok(list[i].y - list[i].r >= box.y0 && list[i].y + list[i].r <= box.y1)
  }
  // points that do not touch stay where they are
  const apart = [{ key: 'p', x: 300, y: 200, r: 8 }, { key: 'q', x: 700, y: 400, r: 8 }]
  const kept = logic.separate(apart, { box })
  assert.deepEqual(kept.get('p'), apart[0])
  // a fixed obstacle (the crown above the first point) pushes the others away, never the first point sideways
  const crowd = [{ key: 'f', x: 500, y: 300, r: 12 }, { key: 'g', x: 500, y: 270, r: 8 }]
  const c2 = logic.separate(crowd, { box, crownOf: 'f' })
  const f = c2.get('f'), g = c2.get('g'), crown = logic.crownAt(f)
  assert.ok(Math.hypot(g.x - crown.x, g.y - crown.y) >= g.r + crown.r - 0.5, 'nothing sits on the crown')
})

test('separate keeps points and the crown off the quadrant words', () => {
  const box = { x0: logic.X0, x1: logic.X1, y0: logic.Y1, y1: logic.Y0 }
  const word = { x0: 820, y0: 60, x1: 950, y1: 84 }
  const out = logic.separate([{ key: 'a', x: 900, y: 75, r: 10 }], { box, rects: [word] })
  assert.ok(!circleHitsRect(out.get('a'), word), 'a dot leaves the word')
  const head = logic.separate([{ key: 'f', x: 900, y: 120, r: 12 }], { box, rects: [word], crownOf: 'f' })
  assert.ok(!circleHitsRect(logic.crownAt(head.get('f')), word), 'the crown leaves the word')
  assert.deepEqual(logic.separate([{ key: 'b', x: 300, y: 300, r: 10 }], { box, rects: [word] }).get('b'), { key: 'b', x: 300, y: 300, r: 10 })
})

test('placeLabels: no label covers a point, another label or a quadrant word; what cannot be placed hides', () => {
  const dots = new Map([['a', { x: 400, y: 300, r: 12 }], ['b', { x: 445, y: 300, r: 10 }], ['c', { x: 400, y: 340, r: 10 }],
    ['d', { x: 400, y: 262, r: 10 }]])
  const avoid = [{ x0: 360, y0: 200, x1: 600, y1: 230 }]
  const labels = [{ key: 'a', text: 'Den Demo-Bericht prüfen' }, { key: 'b', text: 'Die Issue-Labels aufräumen' },
    { key: 'c', text: 'Am Sonntag die Tunnel' }, { key: 'd', text: 'Idee: Abzeichen' }]
  const box = { x0: logic.X0, x1: logic.X1, y0: logic.Y1, y1: logic.Y0 }
  const out = logic.placeLabels(dots, labels, { avoid, box })
  assert.deepEqual(logic.placeLabels(dots, labels, { avoid, box }), out)
  const shown = [...out.entries()].filter(([, l]) => !l.hidden)
  assert.ok(shown.length >= 3, `placed ${shown.length}`)
  for (const [key, l] of shown) {
    for (const [k2, d] of dots) assert.ok(!circleHitsRect({ x: d.x, y: d.y, r: d.r + 4 }, l.rect), `${key} on point ${k2}`)
    for (const a of avoid) assert.ok(!overlap(l.rect, a), `${key} on a quadrant word`)
    for (const [k2, m] of shown) if (k2 !== key) assert.ok(!overlap(l.rect, m.rect), `${key} on ${k2}`)
    assert.ok(l.rect.x0 >= box.x0 && l.rect.x1 <= box.x1)
    // the label sits by its point: next to it, or with a leader line when it had to go further
    const d = dots.get(key)
    if (l.leader) assert.ok(Math.hypot(l.leader.x2, l.leader.y2) > d.r)
  }
  // a point walled in on every side gets no label (it shows on hover)
  const wall = new Map([['z', { x: 500, y: 300, r: 10 }]])
  const tight = logic.placeLabels(wall, [{ key: 'z', text: 'Wall' }], { avoid: [{ x0: 0, y0: 0, x1: 1000, y1: 296 }, { x0: 0, y0: 304, x1: 1000, y1: 600 }], box })
  assert.equal(tight.get('z').hidden, true)
})

test('layoutMatrix: ten tasks judged alike stand apart, labels clear, crown free', () => {
  const items = Array.from({ length: 10 }, (_, i) => ({ key: `task:${i}`, title: `Aufgabe Nummer ${i} mit einem längeren Titel`,
    urgency: 0.8, impact: 0.8, priority: 0.6 - i * 0.03, rank: i + 1 }))
  const lay = logic.layoutMatrix(items, { first: items[0], avoid: [] })
  assert.deepEqual(logic.layoutMatrix(items, { first: items[0], avoid: [] }), lay)
  const pts = items.map(it => lay.spots.get(it.key))
  for (let i = 0; i < pts.length; i++) for (let j = i + 1; j < pts.length; j++) {
    assert.ok(Math.hypot(pts[i].x - pts[j].x, pts[i].y - pts[j].y) >= pts[i].r + pts[j].r + 2, `${i}/${j}`)
  }
  const crown = logic.crownAt(pts[0])
  const words = logic.quadWordRects({ now: 'Jetzt selbst', plan: 'Einplanen', hand: 'Abgeben', drop: 'Loslassen' })
  const lay2 = logic.layoutMatrix(items, { first: items[0], avoid: words })
  for (const it of items) for (const w of words) assert.ok(!circleHitsRect({ ...lay2.spots.get(it.key), r: lay2.spots.get(it.key).r + 4 }, w), 'no dot on a quadrant word')
  for (const w of words) assert.ok(!circleHitsRect(logic.crownAt(lay2.spots.get(items[0].key)), w), 'no crown on a quadrant word')
  for (const p of pts.slice(1)) assert.ok(Math.hypot(p.x - crown.x, p.y - crown.y) >= p.r + crown.r - 0.5)
  const shown = [...lay.labels.values()].filter(l => !l.hidden && l.shown)
  for (const l of shown) {
    for (const p of pts) assert.ok(!circleHitsRect({ ...p, r: p.r + 4 }, l.rect))
    assert.ok(!circleHitsRect({ ...crown }, l.rect), 'no label over the crown')
  }
  // labels of the first four only; the rest name themselves on hover
  assert.ok([...lay.labels.entries()].every(([key, l]) => l.shown === (items.find(it => it.key === key).rank <= 4)))
  assert.ok(shown.every(l => !/\S…\S/.test(l.text) && l.text.length <= 27))
})

test('matrixWords: the squares and the legend say the profile\'s bucket words where they map', () => {
  const t = { quads: { now: 'Jetzt selbst', plan: 'Einplanen', hand: 'Abgeben', drop: 'Loslassen' }, me: 'du', delegate: 'abgeben' }
  assert.deepEqual(logic.matrixWords({ columns: {}, quadrant: {} }, t), { quads: t.quads, me: 'du', delegate: 'abgeben' })
  const words = { quadrant: { now: 'Tun (du, heute)', plan: 'Planen', hand: 'Mache ich', drop: 'Parken oder streichen' } }
  assert.deepEqual(logic.matrixWords(words, t), { quads: words.quadrant, me: 'Tun (du, heute)', delegate: 'Mache ich' })
  assert.deepEqual(logic.matrixWords(null, t).quads, t.quads)
})

test('the Jev page uses the calm helpers: bucket words, no reading flash, word cuts', () => {
  const page = fs.readFileSync(path.join(WEB, 'jev', 'page.js'), 'utf8')
  assert.match(page, /bucketWords\(/)
  assert.match(page, /readingFor\(/)
  assert.match(page, /playFor\(/)
  assert.match(page, /layoutMatrix\(/)
  assert.doesNotMatch(page, /const short = /, 'no cut of its own mid-word')
  assert.doesNotMatch(page, /cursorOn\(/)
})
