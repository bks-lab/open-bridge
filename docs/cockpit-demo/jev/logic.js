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
