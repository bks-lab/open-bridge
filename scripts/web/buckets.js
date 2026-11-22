// SPDX-License-Identifier: MIT
// Pure helpers of Work through by the briefing's buckets (cockpit.flow.buckets, views/flowbuckets.js). Every point
// answers two questions, who is on the move and when. Who: its bucket, one of the briefing's four (briefing_view.py
// BUCKETS, the row's `bucket`): Do (you, today), Plan (you, no day yet), I'll do (the Bridge), Waiting on others
// (anyone else). A point nobody touched for a while stays in its bucket and carries a quiet mark, resting for N days.
// When: what is put off to a day, on the watch list or done today is out of sight and only counted under the buckets
// (the model's `aside`). Every point takes the same four answers (lib/answers.py ANSWERS), in this order on every card,
// every view and in the printed briefing: Do it (the Bridge takes the next step; an agent tab that asks puts its own
// answers in this place), Later ▾ (tomorrow, Monday, in a week, a picked day, the watch list), Done, Obsolete (quiet,
// last, asked first). Each goes out as a verb of the server the rest of the page already uses (do_it, later, runs_on,
// task_park, settle, the tab's own answers); With … under More hands a task's step over (task_owner, work_on). No DOM,
// no network. logic.js passes every name on.
import { TABLES } from './text.js'
import { DAY, canTab, tabAsksYou, tabHeld, wantsYou, actionRow, flowAction, inProject, flowParts, flowOn, flowQueue, isoDate, nextMonday, personOf, pointName, pointStep, previewText, replyOptions,
  replySend, short, triageShows } from './logic.js'

// the briefing's buckets, in its order (briefing_view BUCKETS)
export const BUCKET_IDS = ['do', 'plan', 'delegate', 'waiting']

// the four answers every point takes, in their order (lib/answers.py ANSWERS); Do it is the strong one
export const ANSWER_IDS = ['do', 'later', 'done', 'obsolete']

// what Later offers, in its order (lib/answers.py LATER_CHOICES)
export const LATER_CHOICES = ['tomorrow', 'monday', 'week', 'pick', 'list']

// the day a point on the watch list is put off to: nobody reaches it, so it never comes back by itself (lib/answers.py)
export const LIST_DAY = '9999-12-31'

// the farthest day a Later puts a point off to, in days from today (lib/answers.py LATER_MAX_DAYS, the server's 366)
export const LATER_MAX_DAYS = 366

// the groups of the queue that are agent tabs (a tab that asks, the return card, a finished or lost start): they ask
// the person, so they stand in Do
const TAB_GROUPS = ['asks', 'back', 'result', 'lost']

// the inbox ids the server takes (actions_base.py INBOX_ID_RE)
const INBOX_ID = /^[0-9]{8}-[0-9]{4}-[a-z0-9][a-z0-9-]{0,119}$/

// who is you on a step (task_who): any other name is someone else's move
const YOU = new Set(['', 'me', 'you', 'self', 'ich', 'du'])
const BRIDGE = new Set(['bridge', 'bridge_then_me'])

// the English titles the server fills in where a profile names none (briefing_view BUCKET_TITLES, also the titles of
// an older server): no words of the profile, the page says its own language's in their place
const SERVER_TITLES = new Set(['Do (you, today)', 'Plan', 'I\'ll do', 'Waiting on others'])

/** Whether Work through shows the briefing's buckets: the page on, its switch cockpit.flow.buckets on, and the
 *  owner's page (a person's page keeps Work through as it is) */
export const flowBucketsOn = s => flowOn(s) && s?.work?.flow?.buckets?.enabled === true && !personOf(s)

/** The buckets in the profile's order, each {id, title}: the server's (model.buckets, the profile's view.buckets),
 *  else the defaults in the page's language. An older server's `drop` is left out, and a bucket has no answers of its
 *  own: every point takes the four (bucketAnswers) */
export function bucketDefs(s, lang = 'en') {
  const d = (TABLES[lang] ?? TABLES.en).flow.buckets.defaults
  const given = (s?.model?.buckets ?? []).filter(b => BUCKET_IDS.includes(b?.id))
  const list = given.length ? given : BUCKET_IDS.map(id => ({ id }))
  return list.map(b => ({ id: b.id, title: b.title && !SERVER_TITLES.has(b.title) ? b.title : d[b.id].title }))
}

/** The bucket of a row: the one the briefing put it in; a task the briefing does not list (it has no next step, or
 *  the page reads it beside the briefing) by who has its next move: blocked or someone else's step Waiting, the
 *  Bridge's I'll do, else Plan. A backlog task none (null): it is on the watch list, out of sight as in the briefing */
export function rowBucket(row) {
  if (BUCKET_IDS.includes(row?.bucket)) return row.bucket
  if (row?.status === 'backlog') return null
  // the model's own rows of resting tasks keep the blocker on the card (model.py with_tasks)
  if (row?.blocked_by || row?.card?.state?.blocked_by) return 'waiting'
  const who = String(row?.card?.next?.who ?? '').trim().toLowerCase()
  if (BRIDGE.has(who)) return 'delegate'
  if (!YOU.has(who)) return 'waiting'
  return 'plan'
}

/** How long a point rests (the briefing's advice quiet, `resting`): its days, true where none are named (the model's
 *  own resting rows, an older briefing's drop), else null. A mark on the card, never a bucket of its own */
export function restingOf(row) {
  const r = row?.resting
  if (Number.isInteger(r) && r > 0) return r
  if (r === true) return true
  if ((row?.bucket === 'resting' || row?.bucket === 'drop') && !(row?.blocked_by || row?.card?.state?.blocked_by)) return true
  return null
}

/** What is out of sight of the buckets, only counted under them (the model's `aside`, briefing.py aside_counts): put
 *  off to a day, on the watch list, done or obsolete today; zeros where the briefing counted nothing */
export function asideCounts(s) {
  const a = s?.model?.aside ?? {}
  const n = v => (Number.isInteger(v) && v > 0 ? v : 0)
  return { later: n(a.later), list: n(a.list), done_today: n(a.done_today) }
}

/** The bucket of a point: an agent tab that asks (or finished, or got lost) Do, a check-in whose day came Waiting
 *  on others (its answers are nudge and wait), any other by its row */
export function pointBucket(x) {
  if (x?.running) return 'delegate'
  if (TAB_GROUPS.includes(x?.group) || (x?.kind === 'tab' && x?.group !== 'doing')) return 'do'
  if (x?.group === 'checkin') return 'waiting'
  return rowBucket(x?.row)
}

/** Every point of the page once, each in its bucket, in the profile's order: {buckets: [{id, title, options,
 *  points}], all}. A point is a card of the queue (the reports card stands as one point per report) or a row of Not
 *  now; what runs (Running now) and what an agent finished to read are no decision and stand apart. Within a bucket
 *  a tab that asks comes first, then the rows the printed briefing numbers, in its order, then the rest in the
 *  queue's */
export function bucketPoints(s, lang = 'en', parts = flowParts(s)) {
  const seen = new Set()
  const all = []
  const gone = answeredHere(s)
  const startedHere = new Set([...gone].filter(k => s?.ui?.flowAnswered?.[k]?.then === 'running'))
  // put off to a day and out of sight until it (the briefing's `away`): a tab that asks about such an item waits with
  // it (round 1 of the four answers: Later on a tab card put the item off, the tab's point stayed in Do)
  const away = new Set((s?.model?.away ?? []).map(a => a?.key))
  // what is hidden here until a day, or settled: a tab that asks about it waits with it too (round 2: after Later on
  // the item, or done for this time on the stream, its tab stood on in Do and was counted out of sight as well)
  const today0 = isoDate(s?.now || Date.now())
  for (const r of s?.model?.hidden ?? []) {
    if (r?.key && (r.settled_as != null || String(r.hidden_until ?? '').slice(0, 10) > today0)) away.add(r.key)
  }
  const tabRowGone = tab => (tab?.item && away.has(`inbox:${tab.item}`)) || (tab?.slug && away.has(`task:${tab.slug}`))
  // a row the briefing holds away until a later day is no point until then, also one whose blocker would put it in
  // Waiting on others (round 3: Later > Monday on a waiting task was counted as later and stood on in Waiting)
  const awayNow = new Set((s?.model?.away ?? []).filter(a => a?.key && String(a.until ?? '').slice(0, 10) > today0).map(a => a.key))
  const push = x => {
    const id = x.id
    if (!id || seen.has(id)) return
    // Do it went out here and an agent starts: the point runs in I'll do until the model catches up (round 4)
    if (gone.has(id) && !x.running && startedHere.has(id)) return push({ ...x, running: true })
    if (gone.has(id) && !(x.running && startedHere.has(id))) return
    if (x.tab && tabRowGone(x.tab)) return
    if (!x.running && x.row?.key && awayNow.has(x.row.key)) return
    // a task the briefing does not list (no next step: its housekeeping counts it; the model's own rows beside the
    // briefing) is no point either: the briefing numbers every point the page shows (round 4: such tasks stood in
    // Plan without a number, as the unlisted streams did in round 2). One an agent runs on stays the Bridge's
    if (!x.running && x.kind === 'row' && isTask(x.row) && !BUCKET_IDS.includes(x.row.bucket)) return
    const bucket = pointBucket(x)
    if (!bucket) return
    seen.add(id)
    all.push({ ...x, bucket })
  }
  for (const x of flowQueue(parts, 'all')) {
    if (x.kind === 'reports') for (const r of x.rows) push({ group: 'reports', id: r.key, kind: 'row', row: r })
    else push(x)
  }
  // what an agent works on since Do it (a start of the return channel, at work or starting) is the Bridge's: it
  // stands in I'll do, marked as running (round 1 of the four answers: it stood only under Running now and left
  // every bucket); a finished one asks you to read it and stands in Do (TAB_GROUPS)
  // the same for a task's own tab at work and a session on a task (round 2: after Yes in an asking tab its task went
  // back to Plan while the agent ran)
  for (const e of parts?.lane ?? []) {
    if (e?.kind === 'start' && e.row?.key) push({ group: 'running', id: e.row.key, kind: 'row', row: e.row, running: true, start: e.start })
    else if ((e?.kind === 'tab' || e?.kind === 'session') && e.row?.key) push({ group: 'running', id: e.row.key, kind: 'row', row: e.row, running: true, tab: e.tab })
  }
  // a question about a task stands for that task on the classic page (flow.js R8); the briefing numbers both, so
  // here the task is a point of its own too, in its own bucket
  for (const x of flowQueue(parts, 'all')) if (x.covers && x.task?.key) push({ group: 'row', id: x.task.key, kind: 'row', row: x.task })
  // a row put off until a later day (hidden here, ahead of its lead time, put off to tomorrow too) is no point until
  // that day, out of sight and counted as later, as in the printed briefing (briefing_view away): an answer that puts
  // it off moves on. One with someone until a check-in day (With … > a name) waits on them: it stands in Waiting on
  // others, where the briefing has it (round 1 of the four answers: a hand-over left every bucket)
  const today = isoDate(s?.now || Date.now())
  const off = e => !!e?.until && String(e.until).slice(0, 10) > today && e.kind !== 'checkin'
  // a stream the briefing does not list (its profile reads no streams) is no point either: the briefing numbers every
  // point the page shows, so the two never disagree (round 2: seven resting streams stood in Plan without a number)
  const unlisted = (g, e) => g.reason === 'stream' && !BUCKET_IDS.includes(e?.row?.bucket)
  for (const g of parts?.leftOut?.groups ?? []) {
    for (const e of g.rows ?? []) if (e?.row?.key && !off(e) && !unlisted(g, e)) push({ group: 'left', left: g.reason, id: e.row.key, kind: 'row', row: e.row, entry: e })
  }
  const order = new Map(all.map((x, i) => [x.id, i]))
  const nr = x => pointNr(x, s) ?? Infinity
  // a tab that asks holds an agent until it is answered: it comes first, whatever kind of card shows it
  const tabFirst = x => (x.kind === 'tab' || (x.tab && ASKING.has(x.tab.state)) ? 0 : 1)
  const buckets = bucketDefs(s, lang).map(b => ({ ...b,
    points: all.filter(x => x.bucket === b.id).sort((a, z) => tabFirst(a) - tabFirst(z) || nr(a) - nr(z) || order.get(a.id) - order.get(z.id)) }))
  // a bucket the profile hides (left out of view.buckets) hides nothing here: its points join the first bucket
  const shown = new Set(buckets.map(b => b.id))
  const strays = all.filter(x => !shown.has(x.bucket))
  if (strays.length && buckets.length) buckets[0].points.push(...strays)
  return { buckets, all }
}

// how long a point answered here stays out of its bucket while no newer collection says where it stands now
const ANSWERED_HOLD_MS = 60000

/** The points answered on this page that the model has not caught up with (ui.flowAnswered: {key: {ms, bucket}}):
 *  out of their bucket at once, so a point just parked is never answered twice in the seconds before the next
 *  collection (round 2); one the next collection still holds (Wait on a task that waits) is back, never after a
 *  minute */
export function answeredHere(s) {
  const at = s?.model?.collected_ms ?? 0
  const now = s?.now || Date.now()
  return new Set(Object.entries(s?.ui?.flowAnswered ?? {}).filter(([, a]) => a && a.ms > at && now - a.ms < ANSWERED_HOLD_MS).map(([k]) => k))
}

/** What waits on you while the buckets are on: the rows of the points of Do (you, today), under an area its own;
 *  the start page's tile, its shelf, the work tab's badge and the head of Due all count these, so one label carries one
 *  count (round 2: "warten auf dich" was 45 on the tile and 22 in the list it opened) */
export function waitingRows(s, area = null) {
  const base = { ...s, ui: { ...(s?.ui ?? {}), page: '@flow', area: null } }
  const doBucket = bucketPoints(base, 'en').buckets.find(b => b.id === 'do')
  const seen = new Set()
  const rows = []
  for (const x of doBucket?.points ?? []) {
    if (!x.row?.key || seen.has(x.row.key)) continue
    seen.add(x.row.key)
    rows.push(x.row)
  }
  return area ? rows.filter(r => inProject(r, area)) : rows
}

/** How many points wait on you while the buckets are on: the points of Do, an agent tab that asks without a row
 *  included (round 1: the badge and the tile counted rows only, 41 against Do's 43); under an area only the points
 *  of its rows. The start page's tile, the work tab's badge and the head of Due say this one count */
export function waitingCount(s, area = null) {
  const base = { ...s, ui: { ...(s?.ui ?? {}), page: '@flow', area: null } }
  const points = bucketPoints(base, 'en').buckets.find(b => b.id === 'do')?.points ?? []
  return area ? points.filter(x => x.row?.key && inProject(x.row, area)).length : points.length
}

/** Due by the four buckets (round 1 of the four answers: Due was grouped by its own sections, words outside the four,
 *  and its numbers ran out of order): one section per shown bucket that holds a row, in the profile's order, its rows
 *  in the order Work through shows them (the briefing's numbers first), each row once. {id, title, rows, total,
 *  compact} as a section of the model, so Due draws them as it draws its own */
export function bucketSections(s, lang = 'en') {
  const base = { ...s, ui: { ...(s?.ui ?? {}), page: '@flow', area: null } }
  return bucketPoints(base, lang).buckets.map(b => {
    const seen = new Set()
    const rows = b.points.map(x => x.row).filter(r => r?.key && !seen.has(r.key) && seen.add(r.key))
    return { id: b.id, title: b.title, rows, total: rows.length, compact: rows.slice(0, 8).map(r => r.key) }
  }).filter(sec => sec.total)
}

/** The bucket open: the one picked (ui.flowBucket), also while it is empty (its empty state offers the next bucket
 *  that holds a point), else the first one that holds one, else the first */
export function openBucket(buckets, picked) {
  return buckets.find(b => b.id === picked) ?? buckets.find(b => b.points.length) ?? buckets[0] ?? null
}

/** The question of a tab's screen: the last sentence that asks (it ends with a "?"), with the sentence before it
 *  where the question alone is short ("Shall I try again?" says little without why); else its last line; '' without
 *  text. A terminal wraps a sentence over lines, so the lines are read as one text, a list mark ("- ") or a blank line
 *  starting a new one. The first line of a long screen is mostly what the tab did, not what it asks (#702's
 *  follow-up) */
export function askQuestion(text) {
  const lines = String(text ?? '').split('\n').map(l => previewText(l))
  const last = lines.filter(Boolean).at(-1) ?? ''
  // paragraphs: a blank line or a list mark starts one
  const paras = []
  for (const l of lines) {
    if (!l) { paras.push(''); continue }
    if (/^([-*•]|\d+[.)])\s/.test(l) || !paras.length) paras.push(l.replace(/^([-*•]|\d+[.)])\s+/, ''))
    else paras[paras.length - 1] = paras[paras.length - 1] ? `${paras[paras.length - 1]} ${l}` : l
  }
  for (const p of paras.filter(Boolean).reverse()) {
    // a sentence ends at a mark followed by a space: a dot inside a number (10.000), a version (v2.3.1) or a path
    // (./deploy.sh) ends none
    const sentences = p.split(/(?<=[.!?])\s+/).map(x => x.trim()).filter(Boolean)
    for (let i = sentences.length - 1; i >= 0; i--) {
      if (!sentences[i].endsWith('?')) continue
      const q = sentences[i]
      return q.length < 60 && i > 0 ? `${sentences[i - 1]} ${q}` : q
    }
  }
  return last
}

// Claude Code's own lines a driver may report as a tab's last line (asks.py STATUS, HINT): its mode, its hints,
// its turn status; never the tab's words
// its tool calls ("⏺ Bash(…)") and their output ("⎿ 3") are what it ran, not what it says (round 2: "⎿ 3" stood as a
// tab's line on the start page)
const TAB_CHROME = /^[\u23f5\u23f8\u23f9\u23bf✻✶✳✢✽✦※·*]|^\u23fa\s*[A-Z][\w-]*\(|\?\s+for shortcuts|esc to interrupt|shift\+tab to cycle|auto-compact|accept edits|bypass permissions|plan mode|\/clear to save|update installed/i

/** The last lines of a tab's screen in its own words (every view that shows a few: Start, the running card), without
 *  Claude Code's own lines (TAB_CHROME) and without the mark it puts before what the agent says */
export function tabLines(text, n = 3) {
  return String(text ?? '').split('\n').filter(l => l.trim() && !TAB_CHROME.test(l.trim()))
    .map(l => previewText(l.trim().replace(/^\u23fa\s*/, ''))).filter(Boolean).slice(-n)
}

/** Whether words may go to a tab as a message: an agent at work in it, no dialog (a dialog takes its options; the
 *  driver types the words and presses Enter, which picks the highlighted one) and no draft in its input line (the
 *  words would be appended to it; the server refuses them, tab_draft) */
export const canMessage = tab => !!tab?.live && tab.state !== 'needs-you' && !tab.ask?.draft

/** Why no line to type into stands under a tab (the tab overlay): 'dialog' where it shows one, 'draft' where its input
 *  line holds text, null where words may go, the control session always (it takes them through the relay) */
export const tabNoSend = (tab, isControl) => (isControl || !tab ? null : tab.state === 'needs-you' ? 'dialog' : tab.ask?.draft ? 'draft' : null)

/** A tab's words in one line, for every view that names them (Start, the tabs column, the drawer, the card): its
 *  question (askQuestion of what the server read off its screen), else its last line where that is no line of
 *  Claude Code's own, else '' */
export function tabWords(tab) {
  const q = askQuestion(tab?.ask?.text)
  if (q) return q
  const last = previewText(tab?.last)
  return last && !TAB_CHROME.test(String(tab?.last ?? '').trim()) ? last : ''
}

/** A point's next sentence, one line, what Do it does: the step of its card (who does what next), a check-in's
 *  nudge, else the bucket's fixed sentence; an asking tab gets its answer. No model call */
export function nextSentence(x, bucket, s, lang = 'en') {
  const f = (TABLES[lang] ?? TABLES.en).flow.buckets
  const tab = x?.tab ?? null
  if (tab && (x.kind === 'tab' || x.kind === 'start' || x.kind === 'back')) {
    // where nothing can be sent from here (a "#" in its input line, a dialog without keys) the first answer is the way
    // to the tab, and Next says so (round 2: it promised to send an answer)
    // a tab that asks nothing says so; one with words in its input line that nobody can send from here says that
    if (!tabAsksYou(tab) && !tab.ask?.draft) return f.nextTabQuiet
    const first = bucketAnswers(x, bucket, s, lang)[0]
    return first?.run?.verb === 'tab_jump' ? f.nextOpenTab : f.nextTab
  }
  const who = waitsOn(x)
  if (x?.group === 'checkin') return f.checkin(who ?? f.someone)
  // an inbox card's generic step is a verb or two ("decide", "give your yes"), no sentence: the bucket's own sentence
  // says it whole. A task's step is the person's own words and stays, however short
  const own = s2 => typeof s2 === 'string' && s2.trim() && !(x?.row?.inbox_id && s2.trim().split(/\s+/).length < 4) ? s2.trim() : null
  // a yes given runs on the Bridge's next pass
  if (x?.row?.inbox_id && x.row.inbox_state === 'approved') return f.nextApproved
  const a = bucketAnswers(x, bucket, s, lang)
  if (!a.length) return f.nextNone
  if (!a.some(z => z.meaning === 'do')) {
    if (x?.row?.tab?.live || x?.running) return f.nextWorking
    // no terminal to start an agent in: Do it is not offered, and Next says why instead of promising an agent (round 4)
    return needsAgent(x?.row) && !canTab(s, 'launch') ? f.nextNoTerminal : f.nextNone
  }
  if (bucket === 'waiting') return f.nextWaiting(who ?? f.someone)
  // what Do it does to this point, said concretely (round 1 of the four answers: 101 of 121 cards said only "the
  // Bridge takes the next step"): an inbox item gets its yes, a task an agent on its step, or on the task as a whole
  const step = x?.row ? pointStep(x.row, s) : null
  const said = own(step?.what) ?? own(x?.row?.next?.what)
  // only you can act on it (gate only-you): Do it prepares it and you take the last step, it never gives a yes (round
  // 2: Next promised a yes and a run, the server started an agent)
  if (x?.row?.inbox_id && x.row.gate === 'only-you') return f.nextPrepare(short(pointName(x.row), 120))
  if (x?.row?.inbox_id) return said ? short(said, 240) : f.nextYes(short(pointName(x.row), 120))
  if (said) return f.nextStep(short(said.replace(/[.!]+$/, ''), 200))
  if (x?.row?.task) return f.nextNoStep
  return f.next[bucket] ?? ''
}

/** The days Later names, as YYYY-MM-DD: tomorrow, next Monday, in a week (lib/answers.py later_until) */
export function laterDays(nowMs) {
  return { tomorrow: isoDate(nowMs + DAY), monday: isoDate(nextMonday(nowMs)), week: isoDate(nowMs + 7 * DAY) }
}

/** The day "later" puts a point off to on a list without a menu (Due's Later for many): tomorrow */
export const nextBriefingDay = nowMs => isoDate(nowMs + DAY)

const isTask = row => !!row?.task && !row.inbox_id && row.key === `task:${row.task}`

/** Whether Do it on a row starts an agent (actions_work.py v_do_it): any row but an inbox item whose yes runs on its
 *  own, i.e. a task, an issue, an only-you item, an approved item without an action of its own */
const needsAgent = row => !!row?.key && (!row.inbox_id || row.gate === 'only-you' || (row.inbox_state === 'approved' && !row.has_action))
const isStream = row => !row?.inbox_id && !!(row?.stream || row?.work_kind === 'stream')

/** Who a waiting point waits on, for a nudge: the check-in's, else the task's step's or the row's while nothing
 *  blocks it (a blocker is a sentence, never a name: blockerOf), else nobody named (null) */
function waitsOn(x) {
  const named = x?.checkin?.who ?? x?.row?.checkin?.who
  if (named) return named
  if (blockerOf(x?.row)) return null
  const who = x?.row?.card?.next?.who ?? x?.row?.who
  return who && !YOU.has(String(who).toLowerCase()) && !BRIDGE.has(String(who).toLowerCase()) ? who : null
}

/** What a blocked row waits on, as its task says it (blocked_by, kept on the card for the model's own rows) */
const blockerOf = row => row?.blocked_by || row?.card?.state?.blocked_by || null

/** The four answers of a point, in their order: each {id, meaning, label, run, primary?, quiet?, confirm?}. `run` is
 *  what it sends: {kind: 'act', verb, args} a verb of the server (c.act), {kind: 'reply', verb, args} a tab's own
 *  answer (c.reply), {kind: 'say', tab} words to a tab, {kind: 'later', choices, then(choice, day)} Later's menu,
 *  then(choice, day) the act of a choice (LATER_CHOICES; `day` the day of a day choice). Do it (meaning do, primary)
 *  is the Bridge taking the next step: an inbox item's yes, an agent on a task's next step, a nudge on a waiting point
 *  written as a draft and never sent; a tab that asks puts its own answers in its place (a dialog's options, Yes and
 *  No, the ready answer of #702's tab_accept). Later puts it off to a day (on a waiting point with the same person,
 *  runs_on) or onto the watch list (a task to the backlog, task_park; anything else without a day, LIST_DAY). Done
 *  settles it (a stream: done for this time, it runs on). Obsolete, quiet and last, asks first and closes it as not
 *  done with a note. An answer that cannot go for this point is left out (a tab without a row has only its own) */
export function bucketAnswers(x, bucket, s, lang = 'en') {
  const t = TABLES[lang] ?? TABLES.en
  const f = t.flow.buckets
  // an inbox id the server refuses (actions_base.py INBOX_ID_RE) takes no answer: none is offered
  const row = x?.row?.key && !x.readOnly && (!x.row.inbox_id || INBOX_ID.test(x.row.inbox_id)) ? x.row : null
  const key = row?.key
  const now = s?.now || Date.now()
  const out = []
  const add = (meaning, run, label, more = {}) => {
    if (run) out.push({ id: `${meaning}${out.length}`, meaning, label, run, ...more })
  }
  const act = a => (a ? { kind: 'act', verb: a.verb, args: a.args } : null)
  const stream = isStream(row)
  const tab = x?.tab ?? null
  const isTabPoint = !!tab && (x.kind === 'tab' || x.kind === 'start' || x.kind === 'back')
  // a tab that asks takes the four like every card (round 1 of the four answers): its own answers in the place of Do
  // it, Later, Done and Obsolete on the point it asks about (its inbox item, or its task); a tab without a row has
  // only its own
  // round 2: on a tab of a task or a stream they closed or put off the whole task, never the question; there the tab's
  // own answers stand alone, as in the tabs column (docs/bridge-cockpit.md, Buckets)
  const own = !isTabPoint || (!!row?.inbox_id && (!tab.item || tab.item === row.inbox_id))
  // ---- Do it
  if (isTabPoint) {
    // the tab's own answers win: what it asks is answered in the tab, never by a new start. Where it takes words
    // (textBox), an answer in words stands among them: first where the question is no yes or no
    // only a tab that asks (tabAsksYou) has answers of its own; one that asks nothing offers the way to it in their place,
    // never "Keep going" or an answer in words (after #704 a finished tab offered both, beside a Do chip)
    const opts = tabAsksYou(tab) ? replyOptions(tab, s, t) : { buttons: [], textBox: false }
    const mine = opts.buttons.filter(b => b.verb !== 'tab_jump' && b.verb !== 'tab_go_on')
    const jump = opts.buttons.find(b => b.verb === 'tab_jump')
      ?? (canTab(s, 'focus') ? { verb: 'tab_jump', args: { tab_ref: tab.ref }, label: t.btnToTab } : null)
    const say = opts.textBox ? { kind: 'say', tab } : null
    if (say && !tab.ask?.yes_no) add('do', say, f.sayAnswer)
    for (const b of mine) add('do', { kind: 'reply', verb: b.verb, args: b.args }, b.label)
    if (say && tab.ask?.yes_no) add('do', say, f.sayAnswer)
    if (!out.length && jump) add('do', { kind: 'reply', verb: jump.verb, args: jump.args }, jump.label)
  } else if (key && (row.inbox_state !== 'approved' || (!row.tab?.live && !x.running)) &&
    (canTab(s, 'launch') || (!needsAgent(row) && bucket !== 'waiting'))) {
    // an item whose yes is given takes Do it too in I'll do: it starts now instead of on the next pass (round 3)
    // without a terminal (the driver lists no launch) only a yes goes: what would start an agent is not offered, so a
    // click never fails after the card promised an agent (round 4)
    if (bucket === 'waiting' && (row.tab?.live || x.running)) {
      // a row an agent tab already works on gets no second start, a nudge neither (round 4)
    } else if (bucket === 'waiting') {
      const who = waitsOn(x)
      const blocker = blockerOf(row)
      const ask = who ? t.flow.simple.chase(who, pointName(row)) : blocker ? t.flow.simple.chaseBlocked(short(blocker, 120), pointName(row))
        : t.flow.simple.chase(f.someone, pointName(row))
      add('do', act(flowAction('do', row, ask)), f.answers.do)
    } else if (row.inbox_id) {
      // the briefing's yes (control.md: inbox.py approve, then run): the server starts on it only where no action of
      // its own runs and no tab works on it
      add('do', act({ verb: 'do_it', args: { keys: [key], yes: true } }), f.answers.do)
    } else if (!row.tab?.live && !x.running) {
      // a row an agent tab already works on is never started a second time (do_it would launch another)
      add('do', act({ verb: 'do_it', args: { keys: [key] } }), f.answers.do)
    }
  }
  if (out.length) out[0].primary = true
  if (!key || !own) return out
  // ---- Later ▾
  const who = bucket === 'waiting' ? waitsOn(x) : null
  const backlog = isTask(row) && row.status === 'backlog'
  const then = (choice, day = null) => {
    if (choice === 'list') {
      if (backlog) return null
      return isTask(row) && !stream ? { verb: 'task_park', args: { key, reason: f.parkText } } : { verb: 'later', args: { key, until: LIST_DAY } }
    }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(String(day ?? ''))) return null
    // on a waiting point Later keeps it with the same person (task.py wait keeps the blocker where nobody is named)
    if (bucket === 'waiting') return { verb: 'runs_on', args: { keys: [key], until: day, ...(who ? { on: String(who) } : {}) } }
    return { verb: 'later', args: { key, until: day, ...(bucket === 'plan' ? { plan: true } : {}) } }
  }
  add('later', { kind: 'later', choices: LATER_CHOICES.filter(c => c !== 'list' || !backlog), then }, f.answers.later)
  // ---- Done
  // a stream done for this time: out of sight until tomorrow and counted as done today, the stream runs on
  if (stream) add('done', act({ verb: 'later', args: { key, until: isoDate(now + DAY), done: true } }), f.answers.doneStream)
  else if (!Array.isArray(row.settle) || row.settle.includes('done')) add('done', act({ verb: 'settle', args: { keys: [key], outcome: 'done' } }), f.answers.done)
  // ---- Obsolete
  const gone = obsoleteRun(row, f)
  if (gone) add('obsolete', gone, f.obsolete, { confirm: true, quiet: true, ...(stream ? { stream: true } : {}) })
  return out
}

/** Who can take a point's next step under More (With …): {current, choices, name}. `choices` are you and the Bridge
 *  for a task's step (task_owner, task.py next --who); `name(who)` puts any point with a person until a check-in in a
 *  week (work_on), so it waits on them; `current` who has it now (me, bridge or the name) */
export function ownerChoices(x, s) {
  const row = x?.row?.key && !x.readOnly ? x.row : null
  if (!row) return { current: null, choices: [], name: () => null }
  const key = row.key
  // an inbox item put off with someone says who (row.who); a task its step's who; a point that waits on a blocker
  // without a name has no holder to mark (round 3: a task waiting on Jordan marked du as the current one)
  const held = row.inbox_id ? (row.inbox_state === 'deferred' ? row.who ?? x.checkin?.who : null) : row.card?.next?.who
  const step = String(held ?? row.checkin?.who ?? x.checkin?.who ?? '').trim()
  const low = step.toLowerCase()
  const blocked = !step && (blockerOf(row) || x?.bucket === 'waiting')
  const current = blocked ? null : BRIDGE.has(low) ? 'bridge' : YOU.has(low) ? 'me' : step
  // you and the Bridge on every point that has an owner, an inbox item too (round 3: it offered only a name)
  const choices = isTask(row) || row.inbox_id ? ['me', 'bridge'].map(who => ({ who, run: { verb: 'task_owner', args: { key, who } } })) : []
  const week = laterDays(s?.now || Date.now()).week
  const name = who => {
    const w = String(who ?? '').replace(/\s+/g, ' ').trim()
    return w ? { verb: 'work_on', args: { key, who: w.slice(0, 60), until: week } } : null
  }
  return { current, choices, name }
}

// the answers that name the state the page saw (actions_base.py WAS_VERBS, POINT_STATES)
const WAS_VERBS = new Set(['do_it', 'later', 'settle', 'shelve', 'task_park', 'task_keep', 'runs_on'])
const POINT_STATES = new Set(['open', 'approved', 'waiting', 'deferred', 'doing', 'review', 'backlog'])

/** An answer as it goes out: with the state the page saw its point in (`was`: an inbox item's state, a task's
 *  status), so the server refuses it once another browser answered the point meanwhile (409 point_moved, round 2);
 *  a verb that takes none, or a row without a state, goes as it is */
export function withWas(go, row) {
  if (!go || !WAS_VERBS.has(go.verb)) return go
  const was = row?.inbox_id ? row.inbox_state : row?.task ? row.status : null
  return POINT_STATES.has(was) ? { ...go, args: { ...go.args, was } } : go
}

/** What Obsolete sends, the fixed last answer of every point: one settle as not done (actions_work.py v_settle) with
 *  the note as its text, so the history keeps it. A task is closed as not done, an inbox item dropped with the note
 *  and counted as out of date under its source (inbox.py drop --reason outdated), an issue or any other row hidden
 *  here (its source, GitHub too, stays as it is), a stream ended (the page asked: the confirm). Null where it cannot
 *  go: no row, or one the server does not settle as not done */
function obsoleteRun(row, f) {
  if (!row?.key) return null
  if (Array.isArray(row.settle) && !row.settle.includes('not_doing')) return null
  return { kind: 'act', verb: 'settle', args: { keys: [row.key], outcome: 'not_doing', text: f.obsoleteText,
    ...(row.inbox_id ? { reason: 'outdated' } : {}), ...(isStream(row) ? { stream: true } : {}) } }
}

/** Obsolete with the person's note: the note after the fixed word, so the history says both */
export function withNote(go, note, f) {
  const n = String(note ?? '').replace(/\s+/g, ' ').trim()
  return n && go?.verb === 'settle' ? { ...go, args: { ...go.args, text: `${f.obsoleteText}: ${n}`.slice(0, 2000) } } : go
}

/** The kind of a point in a word (Agent tab, Inbox, Stream, Task, Issue or PR, Point) */
export function pointKindWord(x, lang = 'en') {
  const k = (TABLES[lang] ?? TABLES.en).flow.buckets.kind
  if (x?.tab && (x.kind === 'tab' || x.kind === 'start' || x.kind === 'back')) return k.tab
  const row = x?.row
  // an inbox item by its art, as every list's kind tag says it (round 4: the card said Inbox, the lists Report)
  if (row?.inbox_id) return (TABLES[lang] ?? TABLES.en).kindArt?.[row.art ?? 'ask'] ?? k.inbox
  if (isStream(row)) return k.stream
  if (row?.task) return k.task
  if (row?.ref) return k.issue
  return k.other
}

/** The words of the buckets by the ids other parts of the page use, {} where the buckets are off: the task board's
 *  columns of the Bridge's moves and of what waits on others (its own words for yours and for review: it splits by who
 *  moves, not by day), Jev's squares (`quadrant`) and the colours of its legend (`who`: you or the Bridge) */
export function bucketWords(s, lang = 'en') {
  if (!flowBucketsOn(s)) return { columns: {}, quadrant: {}, who: {} }
  const f = (TABLES[lang] ?? TABLES.en).flow.buckets
  const by = Object.fromEntries(bucketDefs(s, lang).map(b => [b.id, b.title]))
  // Jev's squares in the bucket words (Michael, 22.11.2026): urgent and weighty is Do, weighty without hurry Plan,
  // urgent and light the Bridge's (I'll do). Light and not urgent has no bucket: it is what Later takes out of sight,
  // so that square says the word of that answer rather than nothing, and no word of Jev's own stands beside the four
  return { columns: { bridge: by.delegate, waiting: by.waiting },
    quadrant: { now: by.do, plan: by.plan, hand: by.delegate, drop: f.answers.laterPlain },
    who: { me: f.owner.me, delegate: f.owner.bridge } }
}

// ---------------------------------------------------------------- the other views of the work tab

// the states of an agent tab that ask the person: a dialog, or a prompt waiting for an answer
const ASKING = new Set(['needs-you', 'waiting'])

/** A row of any view (Due, By source, By Jev, the detail) as a point of the buckets: a row whose agent tab asks
 *  stands as that tab, answered in the tab as on the card of Work through; any other row as itself */
export function rowPoint(row, s) {
  const ref = row?.tab?.ref ?? null
  const all = s?.tabs?.tabs ?? []
  // an inbox item's own tab (its item) before the tab its task has (round 2: a stream's tab stood for an item whose
  // own tab asked yes or no, and Do it reached nothing)
  const own = row?.inbox_id ? all.find(x => x.item === row.inbox_id && wantsYou(x)) ?? null : null
  const tab = own ?? (ref ? all.find(x => x.ref === ref) ?? null : null)
  // only the row the tab works on: an inbox item about its task is no answer to its dialog (round 2: "Reply to
  // Jordan" offered the deploy dialog's Yes and approved the deploy)
  const about = row?.inbox_id ? tab?.item === row.inbox_id : !!row?.task && (tab?.slug == null || tab.slug === row.task)
  if (tab && wantsYou(tab) && about && !tabHeld(tab, s?.model)) return { group: 'asks', id: row.key, kind: 'tab', tab, row }
  return { group: 'row', id: row?.key ?? null, kind: 'row', row }
}

/** An agent tab of the tabs column as a point: one that asks stands in Do with its own answers, with the row of the
 *  inbox item it asks about (Later, Done and Obsolete act on that item, as on its card in Work through: round 1 of
 *  the four answers had only the tab's own answer in the column and in Chat); one that works or is the control
 *  session is no decision (null) */
export function tabPoint(tab, s = null) {
  // a tab that finished (waits at its prompt and went quiet) is no point, as in Work through (flow.js, wantsYou): its
  // card in the column wears no Do chip (after #704 a finished tab did)
  if (!wantsYou(tab) || tabHeld(tab, s?.model)) return null
  // its item's row wherever the model holds it (a section, the rows put off, the ones past the briefing's window): a
  // column card has Later, Done and Obsolete as the card in Work through has (round 2: one with a ready answer had none)
  const m = s?.model ?? {}
  const row = tab.item ? [...(m.sections ?? []).flatMap(x => x.rows ?? []), ...(m.hidden ?? []), ...(m.deferred ?? [])]
    .find(r => r?.inbox_id === tab.item) ?? null : null
  return { group: 'asks', id: `tab:${tab.ref}`, kind: 'tab', tab, row }
}

/** The bucket a point stands in on a list: its bucket (pointBucket), a backlog task the briefing holds in none (it
 *  is on the watch list) under Plan, you without a day, so no row of a list stands in none */
export const viewBucket = x => pointBucket(x) ?? 'plan'

/** The bucket of a page item (By source): the bucket of its row, null for an item no answer reaches */
export function itemBucket(it, s, byKey) {
  const row = actionRow(it, byKey)
  return row && !noPoint(row, s) ? viewBucket(rowPoint(row, s)) : null
}

/** Whether a row is no point of the buckets, the same rule as Work through's (bucketPoints): a task the briefing folded
 *  into an inbox line (that line is its point), a stream the briefing does not list. By source keeps it among its
 *  source's rows but counts it in no bucket (round 2: its chips counted Plan 62 where Work through had 55) */
function noPoint(row, s) {
  // put off to a later day: out of sight until it, as in Work through (round 3: By source listed such an item under Do)
  const today = isoDate(s?.now || Date.now())
  if (row?.key && (s?.model?.away ?? []).some(a => a?.key === row.key && String(a.until ?? '').slice(0, 10) > today)) return true
  if (!row?.inbox_id && row?.task && (s?.model?.sections ?? []).some(x => (x.rows ?? []).some(r => (r?.folded_tasks ?? []).includes(row.task)))) return true
  return !row?.inbox_id && !!(row?.stream || row?.work_kind === 'stream') && !BUCKET_IDS.includes(row?.bucket)
}

/** Whether a page item is an advice about a task that is a point of its own (an advise section's "resting for 55
 *  days" on a task the page lists): with the buckets on that advice is a mark on the point, never a row beside it
 *  (round 3: By source counted 195 rows where every other view had 113 points) */
export function adviceFolded(it, sec, s, byKey) {
  if (!flowBucketsOn(s) || sec?.kind === 'tasks' || sec?.kind === 'inbox') return false
  return !!it?.task && (sec?.kind === 'advise' || /advi[cs]e/.test(String(sec?.id ?? ''))) && !!byKey?.get(`task:${it.task}`)
}

/** A page's sections as By source counts them while the buckets are on: an advice folded into its point is no row
 *  (adviceFolded), so the strip's "All" and each source say the points shown */
export function sourceSections(sections, s, byKey) {
  if (!flowBucketsOn(s)) return sections
  return (sections ?? []).map(sec => {
    const items = sec.items ?? []
    const gone = items.filter(it => adviceFolded(it, sec, s, byKey)).length
    return gone ? { ...sec, items: items.filter(it => !adviceFolded(it, sec, s, byKey)), total: Math.max(0, (sec.total ?? items.length) - gone) } : sec
  })
}

/** Whether a page item stays under the strip's filter: with the buckets on a filter `b:<bucket>` keeps that
 *  bucket's items, without them the triage's; a filter of the other mode (left from before the switch moved) keeps
 *  all */
export function workShows(it, s, byKey, f) {
  const bucket = typeof f === 'string' && f.startsWith('b:') ? f.slice(2) : null
  if (flowBucketsOn(s)) {
    // a task the briefing folded into its inbox line is that line, one matter one row (round 3: By source listed it
    // beside its line, unnumbered, in another bucket); one put off to a later day is out of sight here too
    const row = actionRow(it, byKey)
    if (row && noPoint(row, s) && !(row.stream || row.work_kind === 'stream')) return false
    return !bucket || itemBucket(it, s, byKey) === bucket
  }
  return bucket ? true : triageShows(it, s?.triage?.items, f)
}

/** How many page items each bucket holds, `all` every item */
export function bucketCounts(items, s, byKey, lang = 'en') {
  const out = { all: (items ?? []).length, ...Object.fromEntries(bucketDefs(s, lang).map(b => [b.id, 0])) }
  for (const it of items ?? []) {
    const b = itemBucket(it, s, byKey)
    if (b && b in out) out[b] += 1
  }
  return out
}

/** The word of "let the AI do it" (do_it): Do it, the first of the four answers, while the buckets are on, so one
 *  act has one label on every view; else the page's own */
export function doWord(s, lang = 'en') {
  const t = TABLES[lang] ?? TABLES.en
  return flowBucketsOn(s) ? t.flow.buckets.answers.do : t.action.do
}

/** The number a point has in the printed briefing: its row's (brief_nr), else, for an agent tab that asks without a
 *  row of its own, the number the briefing gave that tab (model.tab_nrs by its ref, briefing_view tab_asks); null
 *  where the briefing numbers none */
export function pointNr(x, s) {
  if (Number.isInteger(x?.row?.brief_nr)) return x.row.brief_nr
  const n = x?.tab?.ref && !x?.row ? s?.model?.tab_nrs?.[x.tab.ref] : null
  return Number.isInteger(n) ? n : null
}

/** The number a row shows on a list (Due, By source, the start page): while the buckets are on only its number in the
 *  printed briefing (brief_nr, "4 yes" in the chat acts on it), null for a row the briefing does not number, so no
 *  second number of the cockpit's own stands beside it; else the cockpit's own (model.numbers) */
export function shownNumber(row, s) {
  if (flowBucketsOn(s)) return Number.isInteger(row?.brief_nr) ? row.brief_nr : null
  return s?.model?.numbers?.[row?.key] ?? row?.number ?? null
}
