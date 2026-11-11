// SPDX-License-Identifier: MIT
// Pure helpers of the taskboard (a `kind: tasks` section with `view: taskboard`, views/taskboard.js): the column of a
// task, its card with its tags, the tidy-up suggestions by fixed rules, and the agent tabs that carry no task. No DOM,
// no network, no state; logic.js passes every name on, the frontend test imports it from there.
//
// Who has a task's next move is the server's (briefing_view.task_who, the rule Work's buckets keep too): each row
// carries it as `board.lane`. This file only places the row: a stream in the band, a task in review under To review,
// any other by its lane.
import { inProject } from './areas.js'

const DAY = 86400000

// the four columns, in their order; a stream stands in the band under them
export const TB_COLUMNS = ['me', 'bridge', 'waiting', 'review']
// a step older than this many days says so on its card (not on a waiting one: it waits on purpose)
export const TB_STEP_OLD = 7
// the longest name a waiting tag shows
export const TB_WHO_MAX = 40
// a due day closer than this many days is red
export const TB_DUE_SOON = 30
// the fixed tidy-up rules: a backlog task this many days without movement, a step this many days old
export const TB_TIDY = { backlogQuiet: 30, stepOld: 14 }
// fewer letters before a colon are a tag ("Bug:"), not a topic (briefing_view TOPIC_MIN)
const TOPIC_MIN = 4

/** Midnight of an ISO day (YYYY-MM-DD) in local time, or null */
function dayOf(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso ?? ''))
  return m ? new Date(+m[1], +m[2] - 1, +m[3]).getTime() : null
}

/** Whole days from an ISO day to now (positive in the past), or null */
export function tbDaysSince(iso, nowMs) {
  const d = dayOf(iso)
  if (d == null) return null
  const now = new Date(nowMs)
  return Math.round((new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime() - d) / DAY)
}

/** A task's short title: its H1 up to the first colon (the topic), the whole H1 when the part before is a tag */
export function tbTopic(title) {
  const text = String(title ?? '').trim()
  const at = text.indexOf(':')
  return at >= TOPIC_MIN ? text.slice(0, at).trim() : text
}

/** The column of a task row: stream (the band), review, else by who has its next move (board.lane); a task
 *  without a step stands with you */
export function tbColumn(it) {
  const b = it?.board ?? {}
  if (b.stream) return 'stream'
  if (it?.state === 'review') return 'review'
  if (b.lane === 'bridge') return 'bridge'
  if (b.lane === 'waiting') return 'waiting'
  return 'me'
}

/** The tasks an open inbox decision is tied to (an item's `task`, kind decision): their cards say Decide, first. Only
 *  one that asks now: not put off (deferred), not filed ahead and waiting for its probe (waiting, `waits_for`), not
 *  approved already */
export function tbDecideSlugs(rows) {
  const out = new Set()
  for (const r of rows ?? []) {
    if (r?.inbox_id && r.task && r.inbox_kind === 'decision' && (r.inbox_state ?? 'open') === 'open') out.add(r.task)
  }
  return out
}

/** The tab that carries a task: the row's own (the server found it), else an open tab with the task's slug */
function tabOf(it, slug, tabs) {
  if (it?.tab?.ref) return it.tab.ref
  const t = (tabs ?? []).find(x => !x.is_control && x.slug === slug)
  return t?.ref ?? null
}

/** One card of a task row: what the board, its tags and the side panel show. `ctx`: {now, decide (tbDecideSlugs),
 *  tabs, byKey (logic.js indexRows: the area of a task Work shows)} */
export function tbCard(it, ctx = {}) {
  const b = it?.board ?? {}
  const slug = it?.task || it?.id || ''
  const row = ctx.byKey?.get?.(`task:${slug}`) ?? null
  const area = b.area || row?.area || ''
  // a wait whose look-again day has come (or passed) is back with you: the column's promise is "until that day"
  const lookDue = b.lane === 'waiting' && !!b.until && (tbDaysSince(b.until, ctx.now ?? Date.now()) ?? -1) >= 0
  const column = lookDue && tbColumn(it) === 'waiting' ? 'me' : tbColumn(it)
  const stepDays = tbDaysSince(b.updated, ctx.now ?? Date.now())
  const dueDays = b.due ? -tbDaysSince(b.due, ctx.now ?? Date.now()) : null
  const card = {
    key: `task:${slug}`, slug, column, state: it?.state ?? null, title: tbTopic(it?.title) || slug,
    full: String(it?.title ?? slug), headline: b.headline ?? null, step: b.step ?? null, goal: b.goal ?? null,
    stand: b.stand ?? null, updated: b.updated ?? null, lane: b.lane ?? 'none', who: b.who ?? null, until: b.until ?? null,
    due: b.due ?? null, stream: !!b.stream, area, area_names: [area, ...(row?.area_names ?? [])].filter(Boolean),
    decide: column === 'me' && !!ctx.decide?.has?.(slug), tab: tabOf(it, slug, ctx.tabs), stepDays, dueDays,
    priority: it?.priority ?? null, lookDue: lookDue && column === 'me',
  }
  card.tags = tbTags(card)
  return card
}

/** The tags of a card, as data (the view words them): decide, area, backlog, tab open, waiting on, look again, due
 *  (soon: within TB_DUE_SOON days), the step's age past TB_STEP_OLD days (not on a waiting card). A card back from
 *  waiting (lookDue) keeps who it waited on and says since when it is due to look again */
export function tbTags(card) {
  const tags = []
  if (card.decide) tags.push({ kind: 'decide' })
  if (card.area) tags.push({ kind: 'area', value: card.area })
  if (card.state === 'backlog') tags.push({ kind: 'backlog' })
  if (card.tab) tags.push({ kind: 'tab' })
  // a blocked_by says why in a sentence: the tag keeps its start, the panel's step says the rest
  const waited = card.column === 'waiting' || card.lookDue
  // a step that is yours with others (briefing_view task_who: lane me, `who` the others) says with whom
  if (!waited && card.lane === 'me' && card.who) tags.push({ kind: 'with', value: card.who.length > TB_WHO_MAX ? `${card.who.slice(0, TB_WHO_MAX - 1).trimEnd()}…` : card.who })
  if (waited && card.who) tags.push({ kind: 'waitingOn', value: card.who.length > TB_WHO_MAX ? `${card.who.slice(0, TB_WHO_MAX - 1).trimEnd()}…` : card.who })
  if (card.until) tags.push({ kind: card.lookDue ? 'lookDue' : 'lookAgain', value: card.until })
  if (card.due) tags.push({ kind: 'due', value: card.due, soon: card.dueDays != null && card.dueDays <= TB_DUE_SOON })
  if (!waited && card.stepDays != null && card.stepDays > TB_STEP_OLD) tags.push({ kind: 'stepOld', value: card.stepDays })
  return tags
}

/** Does a card (or a tab) stand in the area of the one area filter (ui.area)? No area chosen: every one */
export const tbInArea = (x, area) => inProject(x, area)

/** A backlog task that asks nothing of you now: no decision tied to it, no look-again day come, no due day within
 *  TB_DUE_SOON days. It waits in the band of what is not started instead of filling Me */
export const tbIsLater = c => c.column === 'me' && c.state === 'backlog' && !c.stream && !c.decide && !c.lookDue
  && !(c.dueDays != null && c.dueDays <= TB_DUE_SOON)

/** The board: the cards in their columns, the streams in their band and the backlog that asks nothing now in its own
 *  (`later`, tbIsLater). You: a decision first, then what is under way before the backlog, then by due day; waiting:
 *  by the day to look again, none last; the rest as they came */
export function tbBoard(cards) {
  const columns = Object.fromEntries(TB_COLUMNS.map(id => [id, []]))
  const streams = []
  const later = []
  for (const c of cards ?? []) (c.column === 'stream' ? streams : tbIsLater(c) ? later : columns[c.column] ?? columns.me).push(c)
  const at = new Map((cards ?? []).map((c, i) => [c.key, i]))
  const by = (...keys) => (a, b) => {
    for (const k of keys) { const d = k(a) - k(b) || 0; if (d) return d }
    return at.get(a.key) - at.get(b.key)
  }
  const dayKey = iso => dayOf(iso) ?? Infinity
  columns.me.sort(by(c => (c.decide ? 0 : 1), c => (c.state === 'backlog' ? 1 : 0), c => dayKey(c.due)))
  columns.waiting.sort((a, b) => (a.until || '9').localeCompare(b.until || '9') || at.get(a.key) - at.get(b.key))
  later.sort(by(c => dayKey(c.due)))
  return { columns, streams, later }
}

/** The tidy-up suggestions by fixed rules, one per task, each with the verb its Yes runs (`shelve`: to the idea list,
 *  task.py shelve): a task without a next step, a backlog task without movement for TB_TIDY.backlogQuiet days, a
 *  step of a task under way older than TB_TIDY.stepOld days. Streams and waiting tasks are left alone. `kept`: the
 *  ids a person kept in this browser (tbTidyId). `extra`: the seam for a later check (an AI's "probably done"): rows
 *  {slug, rule, verb, why?} in the same shape, `verb` shelve or close, taken for tasks no fixed rule names */
export function tbTidy(cards, kept = new Set(), extra = []) {
  const out = []
  const named = new Set()
  for (const c of cards ?? []) {
    if (c.stream || c.column === 'waiting' || c.lookDue) continue
    let rule = null
    if (c.lane === 'none') rule = 'noNext'
    else if (c.state === 'backlog' && c.stepDays != null && c.stepDays >= TB_TIDY.backlogQuiet) rule = 'backlogQuiet'
    else if (c.state === 'doing' && c.column !== 'review' && c.stepDays != null && c.stepDays >= TB_TIDY.stepOld) rule = 'stepOld'
    if (!rule) continue
    named.add(c.slug)
    out.push({ id: tbTidyId(rule, c.slug), slug: c.slug, key: c.key, title: c.title, rule, verb: 'shelve', days: c.stepDays, source: 'rule' })
  }
  const bySlug = new Map((cards ?? []).map(c => [c.slug, c]))
  for (const x of extra ?? []) {
    const c = bySlug.get(x?.slug)
    if (!c || c.stream || named.has(c.slug) || !['shelve', 'close'].includes(x.verb)) continue
    named.add(c.slug)
    out.push({ id: tbTidyId(x.rule || 'extra', c.slug), slug: c.slug, key: c.key, title: c.title, rule: x.rule || 'extra',
      verb: x.verb, why: typeof x.why === 'string' ? x.why : null, days: c.stepDays, source: x.source || 'extra' })
  }
  return out.filter(x => !kept.has(x.id))
}

/** The id a kept suggestion is remembered by: its rule and its task, so a new reason asks again */
export const tbTidyId = (rule, slug) => `${rule}:${slug}`

/** The open agent tabs that carry no task: no slug, and no inbox item tied to a task (the control tab and bare
 *  shells are no work) */
export function tbLooseTabs(tabs, byKey = new Map()) {
  return (tabs ?? []).filter(t => t && !t.is_control && t.state !== 'shell' && !t.slug
    && !(t.item && byKey.get?.(`inbox:${t.item}`)?.task))
}
