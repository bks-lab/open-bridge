// SPDX-License-Identifier: MIT
// Pure helpers of the Jev page (scripts/web/jev/page.js): which rows go to Jev, where a judged task
// stands in the matrix, which plan items still exist on the dashboard, and the invented answer of
// mock mode. No DOM and no Preact here; the node test imports this file.

import { clamp, rng } from './motion.js'

export const W = 1000, H = 600
export const X0 = 96, X1 = 960, Y0 = 540, Y1 = 56
export const CORE = { x: (X0 + X1) / 2, y: (Y0 + Y1) / 2 }

/** Every row of the model once, briefing sections first, then the task rows: the order the server
 *  sends them to Jev in (jev.py collect_tasks) */
export function modelRows(model, limit = 20) {
  const rows = [...(model?.sections ?? []).flatMap(sec => sec?.rows ?? []), ...(model?.task_rows ?? [])]
  const seen = new Set()
  const out = []
  for (const r of rows) {
    const key = r?.key || r?.title
    if (!r?.title || seen.has(key)) continue
    seen.add(key)
    out.push({ ...r, key })
    if (out.length >= limit) break
  }
  return out
}

/** The titles the page shows while Jev reads */
export const pendingTitles = (model, limit = 20) => modelRows(model, limit).map(r => r.title)

/** A small stable number from a string, the seed of a task's nudge in the matrix */
export function hashSeed(s) {
  let h = 2166136261
  for (const ch of String(s ?? '')) h = Math.imul(h ^ ch.codePointAt(0), 16777619) >>> 0
  return h
}

/** Where a task stands in the matrix: urgency right, impact up, a nudge seeded by its key so equal
 *  judgments do not hide each other and a task keeps its spot when others come or go */
export function place(item) {
  const r = rng(hashSeed(item.key ?? item.id))
  const jx = (r() - 0.5) * 22, jy = (r() - 0.5) * 22
  return {
    x: clamp(X0 + 14, X1 - 14, X0 + (item.urgency ?? 0.5) * (X1 - X0) + jx),
    y: clamp(Y1 + 14, Y0 - 14, Y0 - (item.impact ?? 0.5) * (Y0 - Y1) + jy),
    r: 6 + 17 * (item.priority ?? 0),
  }
}

/** Start time of each task's flight in the first play: by rank, the whole swarm leaves within 1.4 s */
export const launch = (i, n) => 0.75 + i * Math.min(0.08, 1.4 / Math.max(1, n))

/** The plan items that are still on the dashboard: a task closed or dropped since Jev judged it
 *  leaves the picture at once instead of waiting for the next (paid) rating. Without a model
 *  nothing is filtered. The first task falls to the best remaining one */
export function liveItems(plan, model, extra = null) {
  const items = plan?.items ?? []
  if (!model) return { items, first: items.find(it => it.id === plan?.first) ?? items[0] ?? null }
  // extra: the keys of rows only a work page holds (an idea, a debrief point), not the briefing
  const keys = new Set([...modelRows(model, Infinity).map(r => r.key), ...(extra ?? [])])
  const kept = items.filter(it => keys.has(it.key))
  return { items: kept, first: kept.find(it => it.id === plan.first) ?? kept[0] ?? null }
}

/** The order of a work page (jev.py rank) in the shape of a rating (jev.py run), so the Jev view of the
 *  work tab draws the same picture as the Jev tab: an item's key is its id, the first is a key */
export function orderPlan(order) {
  if (!order) return null
  const items = (order.items ?? []).map(it => ({ ...it, id: it.key }))
  if (!items.length) return { ok: true, cached: true, empty: true, plan: { items: [], first: null } }
  return { ok: true, empty: false, cached: true, digest: `order:${order.at_ms}`, at_ms: order.at_ms, took_ms: order.took_ms,
    questions: items.length * 4 + (order.calls ?? 1), usage: order.usage ?? null, price: null,
    plan: { items, first: order.first ?? items[0].key } }
}

/** What a plan row can jump to, the same choice the dashboard's own rows make: a live agent tab
 *  first (tab_jump), else "advise me" when the row offers it, else only its detail */
export function rowJump(row) {
  if (!row) return null
  if (row.tab?.live && row.tab.ref) return { verb: 'tab_jump', args: { tab_ref: row.tab.ref }, busy: row.tab.ref }
  if ((row.actions ?? []).some(a => a?.id === 'advise')) return { verb: 'advise', args: { keys: [row.key] }, busy: row.key }
  return null
}

/** What a click on a plan row or dot opens: a dashboard row its detail column ('peek'); an inbox item
 *  or task only the work page holds (a deferred item, a closed task) its own drawer ('item'), as the
 *  page's list view does; anything else nothing */
export function planOpen(it, byKey, extra) {
  if (byKey.has(it.key)) return { how: 'peek', key: it.key }
  const m = /^(inbox|task):(.+)$/.exec(it.key)
  if (!m || !(extra ?? []).includes(it.key)) return null
  return { how: 'item', key: it.key, it: { [m[1]]: m[2], title: it.title } }
}

const quadrant = (u, im) => (u >= 0.5 ? (im >= 0.5 ? 'now' : 'hand') : (im >= 0.5 ? 'plan' : 'drop'))

/** One invented rating in the server's shape (jev.py run): judgments seeded by the row keys, so
 *  the same rows give the same picture and a later round moves a few tasks. Token counts are
 *  invented too and the price stays null, as the real API reports tokens and no price */
export function mockRating(model, round = 0, at = 0) {
  const rows = modelRows(model)
  if (!rows.length) return { ok: true, cached: false, empty: true, plan: { items: [], first: null } }
  const digest = `mock-${(hashSeed(rows.map(r => r.key).join('|')) + round).toString(16)}`
  const items = rows.map((r, i) => {
    const g = rng(hashSeed(r.key) + round * 7)
    const u = g(), im = g(), ef = g(), me = g()
    const priority = 0.42 * u + 0.38 * im + 0.12 * (1 - ef)
    return { id: `t${i + 1}`, key: r.key, title: r.title, area: r.area ?? null, urgency: +u.toFixed(3), impact: +im.toFixed(3),
      effort: +ef.toFixed(3), only_me: +me.toFixed(3), first: 0, priority: +priority.toFixed(3),
      confidence: +(0.4 + 0.6 * g()).toFixed(3), quadrant: quadrant(u, im), who: me >= 0.5 ? 'me' : 'delegate' }
  }).sort((a, b) => b.priority - a.priority).map((it, i) => ({ ...it, rank: i + 1 }))
  items[0].first = 0.71
  const questions = items.length * 4 + 1
  return { ok: true, empty: false, digest, at_ms: at, took_ms: 412 + round * 37, questions,
    usage: { input_tokens: 240 + questions * 68, output_tokens: questions * 5 }, price: null,
    plan: { items, first: items[0].id, first_confidence: 0.64, model: 'jev-mock' } }
}

const dayOf = ms => { const d = new Date(ms); return `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}` }

/** Mock mode's POST /api/jev/run with the server's rules: by itself at most once per day (later
 *  requests get the kept rating, `changed` when the rows differ), force always rates, cache_only
 *  never does, and `today` sums the day's tokens */
export function createMockJev(clock = () => Date.now()) {
  let kept = null, day = null, round = 0
  let today = { day: null, ratings: 0, input_tokens: 0, output_tokens: 0, unknown: 0 }
  return function run(model, { force = false, cacheOnly = false } = {}) {
    const now = clock()
    const fresh = mockRating(model, round, now)
    if (fresh.empty) return { result: fresh, paid: false }
    if (!force && kept && day === dayOf(now)) {   // the real digest carries the date, so a new day never matches
      return { result: { ...kept, cached: true, changed: kept.digest !== fresh.digest, today: { ...today } }, paid: false }
    }
    if (cacheOnly && !force) return { result: { ok: true, stale: true, cached: false, empty: false, digest: fresh.digest }, paid: false }
    if (force) round += 1
    const rating = force ? mockRating(model, round, now) : fresh
    kept = rating
    day = dayOf(now)
    if (today.day !== day) today = { day, ratings: 0, input_tokens: 0, output_tokens: 0, unknown: 0 }
    today = { ...today, ratings: today.ratings + 1, input_tokens: today.input_tokens + rating.usage.input_tokens,
      output_tokens: today.output_tokens + rating.usage.output_tokens }
    return { result: { ...rating, cached: false, changed: false, today: { ...today } }, paid: true }
  }
}

/** Tokens in the page's language with grouping, tabular in the CSS */
export function tokenText(n, lang = 'de') {
  return Math.round(n).toLocaleString(lang === 'de' ? 'de-DE' : 'en-US')
}

/** What the cost line says: the tokens of this rating and of today, never a price the API did not
 *  name. Returns null when the answer carries no counts at all */
export function costLine(data) {
  const u = data?.usage
  if (!u || u.input_tokens == null || u.output_tokens == null) return null
  const t = data.today ?? {}
  return { tokens: u.input_tokens + u.output_tokens, today: (t.input_tokens ?? 0) + (t.output_tokens ?? 0),
    ratings: t.ratings ?? 1, unknown: t.unknown ?? 0, price: data.price ?? null }
}

// ---------------------------------------------------------------- calm play and a readable matrix

// what a cut may not end on before its ellipsis: a space, an opening quote or bracket, a comma and the like
const DANGLING = /[\s„“"'(\[{,;:.\-/]+$/

/** A text cut to at most n characters at a word end, with an ellipsis; a text that fits stays whole (its
 *  whitespace folded). One word longer than the room gets a hard cut, still with the ellipsis */
export function cutWords(s, n) {
  const t = String(s ?? '').replace(/\s+/g, ' ').trim()
  if (t.length <= n) return t
  const room = t.slice(0, n - 1)
  const sp = t[n - 1] === ' ' ? room.length : room.lastIndexOf(' ')
  const head = (sp >= n * 0.4 ? room.slice(0, sp) : room).replace(DANGLING, '')
  return (head || room) + '…'
}

/** A title the server cut at `limit` characters (it is that long and does not say so) loses its broken last
 *  word and says it was cut; any other title stays as it is */
export function trimCut(s, limit) {
  const t = String(s ?? '')
  if (t.length < limit || t.endsWith('…')) return t
  const sp = t.lastIndexOf(' ')
  const head = (sp > 0 ? t.slice(0, sp) : t.slice(0, limit - 1)).replace(DANGLING, '')
  return (head || t.slice(0, limit - 1)) + '…'
}

/** What a new answer plays: 'intro' for the first rating on the page (or a replay), 'update' when the rating
 *  changed (its digest or time), 'keep' when the kept rating came back (nothing moves), 'none' for no picture */
export function playFor(prev, next, { replay = false } = {}) {
  if (!next || next.empty || !next.plan?.items?.length) return 'none'
  if (replay || !prev?.plan?.items?.length) return 'intro'
  if (prev.digest === next.digest && prev.at_ms === next.at_ms) return 'keep'
  return 'update'
}

/** When a request shows Jev reading: a click at once; a background check never over a drawn picture (the
 *  picture stays as it is until a changed answer glides in), and only after a moment when nothing is drawn yet */
export function readingFor({ force = false, hasPlan = false } = {}) {
  return force ? 'now' : hasPlan ? 'never' : 'later'
}

/** Whether a new request may take over from the one in flight (`running`: 'force', 'check' or null): a
 *  background check never cancels a click's rating, it waits for its answer */
export const checkWins = ({ force = false, running = null } = {}) => force || running !== 'force'

/** The typing cursor shows only while the line types, and is gone once the line stands */
export const cursorShown = (T, t0, d) => T >= t0 - 0.1 && T < t0 + d + 0.05

/** The crown over the first task, as a circle: the page draws it 14 above the dot's edge */
export const crownAt = p => ({ x: p.x, y: p.y - p.r - 14, r: 13 })

/** Points pushed apart until no two overlap (a gap between their edges), seeded by their keys where two sit
 *  on the same spot, so the same judgments always give the same picture; kept inside `box`. `crownOf` names
 *  the point that carries the crown: other points keep off it. `ring` is what the radii add for the
 *  collision over the drawn dot (the crown sits on the drawn dot). `rects` (the quadrant words) keep points and
 *  the crown off them. Points that touch nothing stay put */
export function separate(pts, { gap = 4, box = null, crownOf = null, ring = 0, rects = [], iters = 240 } = {}) {
  const P = pts.map(p => ({ key: p.key, x: p.x, y: p.y, r: p.r }))
  const crownOfP = p => crownAt({ x: p.x, y: p.y, r: p.r - ring })
  const inside = p => {
    if (!box) return
    const top = p.key === crownOf ? p.r - ring + 27 : p.r
    p.x = clamp(box.x0 + p.r, box.x1 - p.r, p.x)
    p.y = clamp(box.y0 + top, box.y1 - p.r, p.y)
  }
  const away = (a, b) => {
    const g = rng(hashSeed(`${a}|${b}`))
    const ang = g() * Math.PI * 2
    return [Math.cos(ang), Math.sin(ang)]
  }
  const head = crownOf == null ? null : P.find(p => p.key === crownOf) ?? null
  for (let n = 0; n < iters; n++) {
    let moved = false
    for (let i = 0; i < P.length; i++) {
      for (let j = i + 1; j < P.length; j++) {
        const a = P[i], b = P[j]
        const dx = b.x - a.x, dy = b.y - a.y, d = Math.hypot(dx, dy), min = a.r + b.r + gap
        if (d >= min - 1e-6) continue
        const [ux, uy] = d > 1e-6 ? [dx / d, dy / d] : away(a.key, b.key)
        const push = (min - d) / 2 + 0.05
        a.x -= ux * push; a.y -= uy * push; b.x += ux * push; b.y += uy * push
        moved = true
      }
    }
    if (head) {
      const c = crownOfP(head)
      for (const p of P) {
        if (p === head) continue
        const dx = p.x - c.x, dy = p.y - c.y, d = Math.hypot(dx, dy), min = p.r + c.r + gap / 2
        if (d >= min - 1e-6) continue
        const [ux, uy] = d > 1e-6 ? [dx / d, dy / d] : away(head.key, p.key)
        p.x += ux * (min - d + 0.05); p.y += uy * (min - d + 0.05)
        moved = true
      }
    }
    for (const rect of rects) {
      for (const p of P) {
        const [mx, my] = outOf(p, rect)
        if (mx || my) { p.x += mx; p.y += my; moved = true }
        if (p === head) {
          const [cx, cy] = outOf(crownOfP(p), rect)
          if (cx || cy) { p.x += cx; p.y += cy; moved = true }
        }
      }
    }
    P.forEach(inside)
    if (!moved) break
  }
  return new Map(P.map(p => [p.key, p]))
}

/** How far a circle must move to leave a rect: [0, 0] when it does not touch it; out along the nearest point,
 *  or through the nearest side when its centre lies inside */
function outOf(c, r) {
  const nx = Math.max(r.x0, Math.min(c.x, r.x1)), ny = Math.max(r.y0, Math.min(c.y, r.y1))
  const dx = c.x - nx, dy = c.y - ny, d = Math.hypot(dx, dy)
  if (d >= c.r) return [0, 0]
  if (d > 1e-6) return [(dx / d) * (c.r - d + 0.05), (dy / d) * (c.r - d + 0.05)]
  const sides = [[r.x0 - c.r - 0.05 - c.x, 0], [r.x1 + c.r + 0.05 - c.x, 0], [0, r.y0 - c.r - 0.05 - c.y], [0, r.y1 + c.r + 0.05 - c.y]]
  return sides.reduce((a, b) => (Math.hypot(...b) < Math.hypot(...a) ? b : a))
}

const hitsRect = (c, r) => {
  const nx = Math.max(r.x0, Math.min(c.x, r.x1)), ny = Math.max(r.y0, Math.min(c.y, r.y1))
  return Math.hypot(c.x - nx, c.y - ny) < c.r
}
const meets = (a, b) => a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1

/** Where each label stands by its point, in the order given (the most important first): beside the point,
 *  above or below it, else a little further with a leader line, with the full text or a shorter cut; never
 *  over a point (with its ring), another placed label, a rect in `avoid` (the quadrant words, the crown) or
 *  outside `box`. A label with no free place is hidden (it shows on hover). Per key {dx, dy, anchor, text,
 *  rect, leader, hidden}: dx, dy and the leader relative to the point, rect in the matrix */
export function placeLabels(dots, labels, { avoid = [], box = null, charW = 7.2, short = 16 } = {}) {
  const taken = []
  const out = new Map()
  for (const { key, text } of labels) {
    const d = dots.get(key)
    if (!d) continue
    const texts = [text, cutWords(text, short)].filter((x, i, all) => all.indexOf(x) === i)
    const near = [[d.r + 8, 4, 'start'], [-(d.r + 8), 4, 'end'], [0, -(d.r + 9), 'middle'], [0, d.r + 18, 'middle']]
    const far = [[d.r + 20, -(d.r + 16), 'start'], [d.r + 20, d.r + 22, 'start'], [-(d.r + 20), -(d.r + 16), 'end'],
      [-(d.r + 20), d.r + 22, 'end'], [d.r + 36, 4, 'start'], [-(d.r + 36), 4, 'end']]
    const tries = [...texts.flatMap(t => near.map(c => [t, c, false])), ...texts.flatMap(t => far.map(c => [t, c, true]))]
    let found = null
    for (const [t, [dx, dy, anchor], lead] of tries) {
      const w = t.length * charW
      const x0 = d.x + (anchor === 'start' ? dx : anchor === 'end' ? dx - w : dx - w / 2)
      const rect = { x0, y0: d.y + dy - 11, x1: x0 + w, y1: d.y + dy + 4 }
      if (box && (rect.x0 < box.x0 || rect.x1 > box.x1 || rect.y0 < box.y0 || rect.y1 > box.y1)) continue
      if ([...dots.values()].some(o => hitsRect({ x: o.x, y: o.y, r: o.r + 4 }, rect))) continue
      if (taken.some(r => meets(r, rect)) || avoid.some(r => r && meets(r, rect))) continue
      let leader = null
      if (lead) {
        const ex = anchor === 'start' ? dx - 3 : anchor === 'end' ? dx + 3 : dx, ey = dy - 4
        const len = Math.hypot(ex, ey) || 1
        leader = { x1: (ex / len) * (d.r + 5), y1: (ey / len) * (d.r + 5), x2: ex, y2: ey }
      }
      found = { dx, dy, anchor, text: t, rect, leader, hidden: false }
      break
    }
    if (found) taken.push(found.rect)
    out.set(key, found ?? { dx: d.r + 8, dy: 4, anchor: 'start', text, rect: null, leader: null, hidden: true })
  }
  return out
}

/** The four squares of the matrix: where each lies, where its word stands and the corner it grows from */
export const QUADS = [
  { id: 'now', x: CORE.x, y: Y1, w: X1 - CORE.x, h: CORE.y - Y1, ax: X1 - 12, ay: Y1 + 22, anchor: 'end', ox: CORE.x, oy: CORE.y },
  { id: 'plan', x: X0, y: Y1, w: CORE.x - X0, h: CORE.y - Y1, ax: X0 + 12, ay: Y1 + 22, anchor: 'start', ox: CORE.x, oy: CORE.y },
  { id: 'hand', x: CORE.x, y: CORE.y, w: X1 - CORE.x, h: Y0 - CORE.y, ax: X1 - 12, ay: Y0 - 12, anchor: 'end', ox: CORE.x, oy: CORE.y },
  { id: 'drop', x: X0, y: CORE.y, w: CORE.x - X0, h: Y0 - CORE.y, ax: X0 + 12, ay: Y0 - 12, anchor: 'start', ox: CORE.x, oy: CORE.y },
]

/** Where the quadrant words stand, as rects the labels keep off (15px capitals with letter spacing) */
export const quadWordRects = (quads, charW = 11.2) => QUADS.map(q => {
  const w = String(quads?.[q.id] ?? '').length * charW
  const x0 = q.anchor === 'end' ? q.ax - w : q.ax
  return { x0: x0 - 4, y0: q.ay - 14, x1: x0 + w + 4, y1: q.ay + 5 }
})

/** The resting picture of the matrix: every task on its place (place) pushed apart so no two dots and no dot
 *  and the crown overlap (separate), and the labels of the first four placed clear of everything
 *  (placeLabels); the other tasks get a label place for hover only. Deterministic: same items, same picture */
export function layoutMatrix(items, { first = null, avoid = [], charW = 7.2 } = {}) {
  const box = { x0: X0, x1: X1, y0: Y1, y1: Y0 }
  const base = items.map(it => ({ key: it.key, ...place(it) }))
  const sep = separate(base.map(p => ({ key: p.key, x: p.x, y: p.y, r: p.r + 4 })), { gap: 3, box, crownOf: first?.key ?? null, ring: 4, rects: avoid })
  const spots = new Map(base.map(p => [p.key, { x: sep.get(p.key).x, y: sep.get(p.key).y, r: p.r }]))
  const fs = first ? spots.get(first.key) : null
  const c = fs ? crownAt(fs) : null
  const crownRect = c ? { x0: c.x - c.r, y0: c.y - c.r, x1: c.x + c.r, y1: c.y + c.r } : null
  const keep = [...avoid, crownRect].filter(Boolean)
  const ranked = [...items].sort((a, b) => (a.rank ?? 99) - (b.rank ?? 99))
  const shownItems = ranked.filter(it => (it.rank ?? 99) <= 4)
  const labels = new Map()
  const placed = placeLabels(spots, shownItems.map(it => ({ key: it.key, text: cutWords(it.title, 26) })), { avoid: keep, box, charW })
  for (const [key, l] of placed) labels.set(key, { ...l, shown: true })
  const rects = [...placed.values()].map(l => l.rect).filter(Boolean)
  for (const it of ranked) {
    if (labels.has(it.key)) continue
    const one = placeLabels(spots, [{ key: it.key, text: cutWords(it.title, 44) }], { avoid: [...keep, ...rects], box, charW })
    const l = one.get(it.key)
    labels.set(it.key, { ...l, hidden: false, shown: false })
  }
  return { spots, labels }
}

/** The words of the matrix: with the buckets on the squares say the profile's bucket words (buckets.js bucketWords:
 *  now Do, plan Plan, hand I'll do, drop Later) and the legend who moves (you, the Bridge), else the page's own */
export function matrixWords(words, t) {
  const q = words?.quadrant ?? {}
  const quads = Object.fromEntries(Object.entries(t.quads).map(([id, w]) => [id, q[id] || w]))
  return { quads, me: words?.who?.me || t.me, delegate: words?.who?.delegate || t.delegate }
}
