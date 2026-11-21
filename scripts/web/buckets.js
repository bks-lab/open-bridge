// SPDX-License-Identifier: MIT
// Pure helpers of Work through by the briefing's buckets (cockpit.flow.buckets, views/flowbuckets.js). Every point
// of the page (a task, a stream, an inbox item, an agent tab that asks, a check-in, a report, an issue) stands in
// exactly one bucket of the briefing profile's `view.buckets`, by the server's bucket rule (briefing_view.py, the
// row's `bucket`); the names, the order and the answer words are the profile's (model.buckets), the defaults of
// docs/briefings.md where it names none. Each card says one next sentence and offers its bucket's answers, the first
// one "the Bridge does the next step". An answer is the act the briefing's answer is (skills/briefing/references/
// control.md): the meaning of an answer is its place in the bucket's options, whatever the profile calls it, and it
// goes out as a verb of the server the rest of the page already uses (do_it, later, settle, task_park, task_keep,
// runs_on, the tab's own answers). No DOM, no network. logic.js passes every name on.
import { TABLES } from './text.js'
import { DAY, actionRow, flowAction, flowParts, flowOn, flowQueue, isoDate, nextMonday, personOf, pointName, pointStep, previewText, replyOptions,
  replySend, short, triageShows } from './logic.js'

// the briefing's buckets, in its default order (briefing_view BUCKETS)
export const BUCKET_IDS = ['do', 'plan', 'delegate', 'waiting', 'drop']

// what each answer of a bucket means, by its place (control.md: a profile may rename the options, their order keeps
// these meanings). The first one is always the Bridge taking the next step
export const BUCKET_MEANINGS = {
  do: ['yes', 'later', 'drop'], plan: ['schedule', 'later'], delegate: ['go', 'later'], waiting: ['nudge', 'wait'], drop: ['park', 'keep'],
}

// the groups of the queue that are agent tabs (a tab that asks, the return card, a finished or lost start): they ask
// the person, so they stand in Do
const TAB_GROUPS = ['asks', 'back', 'result', 'lost']

// the inbox ids the server takes (actions_base.py INBOX_ID_RE)
const INBOX_ID = /^[0-9]{8}-[0-9]{4}-[a-z0-9][a-z0-9-]{0,119}$/

// how long a park keeps a point that is no task out of sight (a task goes to the backlog instead)
const PARK_DAYS = 30

/** Whether Work through shows the briefing's buckets: the page on, its switch cockpit.flow.buckets on, and the
 *  owner's page (a person's page keeps Work through as it is) */
export const flowBucketsOn = s => flowOn(s) && s?.work?.flow?.buckets?.enabled === true && !personOf(s)

/** The buckets in the profile's order, each {id, title, options}: the server's (model.buckets, the profile's
 *  view.buckets), else the defaults in the page's language; a bucket without answers takes the defaults' */
export function bucketDefs(s, lang = 'en') {
  const d = (TABLES[lang] ?? TABLES.en).flow.buckets.defaults
  const en = TABLES.en.flow.buckets.defaults
  const given = (s?.model?.buckets ?? []).filter(b => BUCKET_IDS.includes(b?.id))
  const list = given.length ? given : BUCKET_IDS.map(id => ({ id }))
  // the server fills what a profile leaves out with its English defaults (briefing_view DEFAULT_BUCKETS): those are
  // no words of the profile, the page says its own language's defaults in their place
  const same = (a, b) => Array.isArray(a) && a.length === b.length && a.every((w, i) => String(w).toLowerCase() === b[i])
  return list.map(b => ({ id: b.id, title: b.title && b.title !== en[b.id].title ? b.title : d[b.id].title,
    options: b.options?.length && !same(b.options, en[b.id].options) ? b.options : d[b.id].options }))
}

/** The bucket of a row: the one the briefing put it in; a task the briefing does not list (it has no next step, or
 *  the page reads it beside the briefing) by who has its next move: the Bridge delegate, blocked waiting, resting
 *  drop, else plan; a backlog task none (null), it stands in no bucket as in the briefing */
export function rowBucket(row) {
  if (BUCKET_IDS.includes(row?.bucket)) return row.bucket
  // a backlog task no bucket of the briefing holds is parked already (the briefing's Merkliste shows it in none)
  if (row?.status === 'backlog') return null
  // the model's own rows of resting tasks keep the blocker on the card (model.py with_tasks)
  if (row?.blocked_by || row?.card?.state?.blocked_by) return 'waiting'
  if (row?.bucket === 'resting') return 'drop'
  const who = String(row?.card?.next?.who ?? '').toLowerCase()
  if (who === 'bridge' || who === 'bridge_then_me') return 'delegate'
  return 'plan'
}

/** The bucket of a point: an agent tab that asks (or finished, or got lost) Do, a check-in whose day came Waiting
 *  on others (its answers are nudge and wait), any other by its row */
export function pointBucket(x) {
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
  const push = x => {
    const id = x.id
    if (!id || seen.has(id)) return
    const bucket = pointBucket(x)
    if (!bucket) return
    seen.add(id)
    all.push({ ...x, bucket })
  }
  for (const x of flowQueue(parts, 'all')) {
    if (x.kind === 'reports') for (const r of x.rows) push({ group: 'reports', id: r.key, kind: 'row', row: r })
    else push(x)
  }
  // a question about a task stands for that task on the classic page (flow.js R8); the briefing numbers both, so
  // here the task is a point of its own too, in its own bucket
  for (const x of flowQueue(parts, 'all')) if (x.covers && x.task?.key) push({ group: 'row', id: x.task.key, kind: 'row', row: x.task })
  // a row put off until a later day (hidden here, deferred by inbox.py or here, ahead of its lead time, with someone
  // until a check-in day) is no point until that day, however it was put off: an answer that puts it off moves on
  const today = isoDate(s?.now || Date.now())
  const off = e => !!e?.until && String(e.until).slice(0, 10) > today
  for (const g of parts?.leftOut?.groups ?? []) {
    for (const e of g.rows ?? []) if (e?.row?.key && !off(e)) push({ group: 'left', left: g.reason, id: e.row.key, kind: 'row', row: e.row, entry: e })
  }
  const order = new Map(all.map((x, i) => [x.id, i]))
  const nr = x => (Number.isInteger(x.row?.brief_nr) ? x.row.brief_nr : Infinity)
  // a tab that asks holds an agent until it is answered: it comes first
  const tabFirst = x => (x.kind === 'tab' ? 0 : 1)
  const buckets = bucketDefs(s, lang).map(b => ({ ...b,
    points: all.filter(x => x.bucket === b.id).sort((a, z) => tabFirst(a) - tabFirst(z) || nr(a) - nr(z) || order.get(a.id) - order.get(z.id)) }))
  // a bucket the profile hides (left out of view.buckets) hides nothing here: its points join the first bucket
  const shown = new Set(buckets.map(b => b.id))
  const strays = all.filter(x => !shown.has(x.bucket))
  if (strays.length && buckets.length) buckets[0].points.push(...strays)
  return { buckets, all }
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
const TAB_CHROME = /^[\u23f5\u23f8\u23f9✻✶✳✢✽✦※·*]|\?\s+for shortcuts|esc to interrupt|shift\+tab to cycle|auto-compact|accept edits|bypass permissions|plan mode|\/clear to save|update installed/i

/** A tab's words in one line, for every view that names them (Start, the tabs column, the drawer, the card): its
 *  question (askQuestion of what the server read off its screen), else its last line where that is no line of
 *  Claude Code's own, else '' */
export function tabWords(tab) {
  const q = askQuestion(tab?.ask?.text)
  if (q) return q
  const last = previewText(tab?.last)
  return last && !TAB_CHROME.test(String(tab?.last ?? '').trim()) ? last : ''
}

/** A point's next sentence, one line: what the tab asks, the step of its card (who does what next), a check-in's
 *  question, else the bucket's fixed sentence. No model call */
export function nextSentence(x, bucket, s, lang = 'en') {
  const f = (TABLES[lang] ?? TABLES.en).flow.buckets
  const tab = x?.tab ?? null
  if (tab && (x.kind === 'tab' || x.kind === 'start' || x.kind === 'back')) {
    const q = tabWords(tab)
    if (q) return short(q, 240)
  }
  if (x?.group === 'checkin') return f.checkin(x.checkin?.who ?? x.row?.checkin?.who ?? f.someone)
  // an inbox card's generic step is a verb or two ("decide", "give your yes"), no sentence, and in Plan or I'll do it
  // even names an answer the bucket does not offer: the bucket's own sentence says it whole. A task's step is the
  // person's own words and stays, however short
  const own = s2 => typeof s2 === 'string' && s2.trim() && !(x?.row?.inbox_id && s2.trim().split(/\s+/).length < 4) ? s2.trim() : null
  const step = x?.row ? pointStep(x.row, s) : null
  if (own(step?.what)) return short(own(step.what), 240)
  if (own(x?.row?.next?.what)) return short(own(x.row.next.what), 240)
  if (bucket === 'drop' && isStream(x?.row)) return f.nextStream
  return f.next[bucket] ?? ''
}

/** The day "later" puts a point off to: the next briefing day, tomorrow */
export const nextBriefingDay = nowMs => isoDate(nowMs + DAY)

/** The days the day picker offers (plan's schedule, waiting's wait), as [word key, YYYY-MM-DD] */
export function pickDays(nowMs) {
  return [['tomorrow', isoDate(nowMs + DAY)], ['monday', isoDate(nextMonday(nowMs))], ['week', isoDate(nowMs + 7 * DAY)],
    ['month', isoDate(nowMs + PARK_DAYS * DAY)]]
}

const upFirst = w => (w ? w.charAt(0).toUpperCase() + w.slice(1) : w)
const isTask = row => !!row?.task && !row.inbox_id && row.key === `task:${row.task}`
const isStream = row => !row?.inbox_id && !!(row?.stream || row?.work_kind === 'stream')

/** Who a waiting point waits on, for a nudge: the check-in's, else the task's step's or the row's while nothing
 *  blocks it (a blocker is a sentence, never a name: blockerOf), else nobody named (null) */
function waitsOn(x) {
  const named = x?.checkin?.who ?? x?.row?.checkin?.who
  if (named) return named
  if (blockerOf(x?.row)) return null
  const who = x?.row?.card?.next?.who ?? x?.row?.who
  return who && !['me', 'you', 'self', 'bridge', 'bridge_then_me'].includes(String(who).toLowerCase()) ? who : null
}

/** What a blocked row waits on, as its task says it (blocked_by, kept on the card for the model's own rows) */
const blockerOf = row => row?.blocked_by || row?.card?.state?.blocked_by || null

/** The answers of a point in its bucket, the first the strong one: each {id, meaning, label, run}, `run` what it
 *  sends: {kind: 'reply', verb, args} a tab's own answer (c.reply), {kind: 'act', verb, args} a verb of the server
 *  (c.act), {kind: 'pick', then} a day picked first, then `then(day)` gives the act. An answer that cannot go for this
 *  point (a stream is never dropped, a tab without a row is not put off) is left out; a tab's own answers (a dialog's
 *  options, yes and no, the ready answer of #702's tab_accept) stand for yes and come first. Last, fixed and quiet, stands
 *  Obsolete (meaning `obsolete`, `confirm` and `quiet` true: the page asks first and never shows it strong), the
 *  same on every point in every bucket (obsoleteRun) */
export function bucketAnswers(x, bucket, s, lang = 'en') {
  const t = TABLES[lang] ?? TABLES.en
  const f = t.flow.buckets
  const def = bucketDefs(s, lang).find(b => b.id === bucket) ?? { options: [] }
  const words = def.options
  const meanings = BUCKET_MEANINGS[bucket] ?? []
  // an inbox id the server refuses (actions_base.py INBOX_ID_RE) takes no answer: none is offered
  const row = x?.row?.key && !x.readOnly && (!x.row.inbox_id || INBOX_ID.test(x.row.inbox_id)) ? x.row : null
  const key = row?.key
  const now = s?.now || Date.now()
  const out = []
  const add = (meaning, run, label = null) => {
    if (!run) return
    const i = meanings.indexOf(meaning)
    out.push({ id: `${meaning}${out.length}`, meaning, label: label ?? upFirst(words[i] ?? meaning), run })
  }
  const act = a => (a ? { kind: 'act', verb: a.verb, args: a.args } : null)
  const later = key ? act({ verb: 'later', args: { key, until: nextBriefingDay(now) } }) : null
  // a row an agent tab already works on is never started a second time (do_it would launch another)
  const doIt = key && row.inbox_state !== 'approved' && !row.tab?.live ? act({ verb: 'do_it', args: { keys: [key] } }) : null
  const tab = x?.tab ?? null
  if (bucket === 'do' && tab && (x.kind === 'tab' || x.kind === 'start' || x.kind === 'back')) {
    // the tab's own answers win: what it asks is answered in the tab, never by a new start. Where it takes words
    // (textBox), an answer in words stands among them: first where the question is no yes or no (a number, a
    // choice, "reply by number"), so Go on is never the only way to answer it
    const opts = replyOptions(tab, s, t)
    const own = opts.buttons.filter(b => b.verb !== 'tab_jump')
    const say = opts.textBox ? { kind: 'say', tab } : null
    if (say && !tab.ask?.yes_no) add('yes', say, f.say)
    for (const b of own) {
      if (say && tab.ask?.yes_no && b.verb === 'tab_go_on') add('yes', say, f.say)
      add('yes', { kind: 'reply', verb: b.verb, args: b.args }, b.label)
    }
    if (!own.length && !say) add('yes', doIt)
  } else if (bucket === 'do') add('yes', doIt)
  if (bucket === 'delegate') add('go', doIt)
  if (bucket === 'plan') add('schedule', key ? { kind: 'pick', then: day => ({ verb: 'later', args: { key, until: day } }) } : null)
  if (bucket === 'waiting') {
    const who = waitsOn(x)
    const blocker = blockerOf(row)
    const ask = who ? t.flow.simple.chase(who, pointName(row ?? {})) : blocker ? t.flow.simple.chaseBlocked(short(blocker, 120), pointName(row ?? {}))
      : t.flow.simple.chase(f.someone, pointName(row ?? {}))
    add('nudge', key && row.inbox_state !== 'approved' ? act(flowAction('do', row, ask)) : null)
    // a named person goes with the wait; without one task.py wait keeps the blocker the task has
    add('wait', key ? { kind: 'pick', then: day => ({ verb: 'runs_on', args: { keys: [key], until: day, ...(who ? { on: String(who) } : {}) } }) } : null)
  }
  // on a tab, later and drop act only on the inbox item it asks about: on a task or a stream behind it they would put
  // off the whole task, not the question
  const own = !(tab && (x.kind === 'tab' || x.kind === 'start' || x.kind === 'back')) || !!row?.inbox_id
  if ((bucket === 'do' || bucket === 'plan' || bucket === 'delegate') && own) add('later', later)
  if (bucket === 'do' && own) add('drop', key && !isStream(row) ? act(flowAction('drop', row, f.dropText)) : null)
  if (bucket === 'drop') {
    // park is the briefing's park (control.md: status backlog, the task stays open); a backlog task is parked already
    add('park', !key || isStream(row) || row.status === 'backlog' ? null
      : isTask(row) ? act({ verb: 'task_park', args: { key, reason: f.parkText } })
      : act({ verb: 'later', args: { key, until: isoDate(now + PARK_DAYS * DAY) } }))
    add('keep', isTask(row) ? act({ verb: 'task_keep', args: { keys: [key] } }) : null)
  }
  const gone = obsoleteRun(row, own, f)
  if (gone) out.push({ id: `obsolete${out.length}`, meaning: 'obsolete', label: f.obsolete, run: gone, confirm: true, quiet: true })
  return out
}

/** What Obsolete sends, the fixed last answer of every point: the classic "Drop because out of date" as one settle
 *  (actions_work.py v_settle) with the reason as its text, so the history keeps it. A task is closed as not done, an
 *  inbox item dropped with the note and counted as out of date under its source (inbox.py drop --reason outdated), an
 *  issue or any other row hidden here (its source, GitHub too, stays as it is), a stream ended (the page asked: the
 *  confirm). Null where it cannot go: no row, a read-only one, one the server does not settle as not done, or a tab's
 *  question about anything but an inbox item (`own` false: the tab's own answers win) */
function obsoleteRun(row, own, f) {
  if (!row?.key || !own) return null
  if (Array.isArray(row.settle) && !row.settle.includes('not_doing')) return null
  return { kind: 'act', verb: 'settle', args: { keys: [row.key], outcome: 'not_doing', text: f.obsoleteText,
    ...(row.inbox_id ? { reason: 'outdated' } : {}), ...(isStream(row) ? { stream: true } : {}) } }
}

/** The kind of a point in a word (Agent tab, Inbox, Stream, Task, Issue or PR, Point) */
export function pointKindWord(x, lang = 'en') {
  const k = (TABLES[lang] ?? TABLES.en).flow.buckets.kind
  if (x?.tab && (x.kind === 'tab' || x.kind === 'start' || x.kind === 'back')) return k.tab
  const row = x?.row
  if (row?.inbox_id) return k.inbox
  if (isStream(row)) return k.stream
  if (row?.task) return k.task
  if (row?.ref) return k.issue
  return k.other
}

/** The words of the buckets by the ids other parts of the page use: the taskboard's columns (me, bridge, waiting;
 *  review stays its own) and Jev's squares (now, plan, hand, drop), {} where the buckets are off */
export function bucketWords(s, lang = 'en') {
  if (!flowBucketsOn(s)) return { columns: {}, quadrant: {} }
  const by = Object.fromEntries(bucketDefs(s, lang).map(b => [b.id, b.title]))
  return { columns: { me: by.do, bridge: by.delegate, waiting: by.waiting }, quadrant: { now: by.do, plan: by.plan, hand: by.delegate, drop: by.drop } }
}

// ---------------------------------------------------------------- the other views of the work tab

// the states of an agent tab that ask the person: a dialog, or a prompt waiting for an answer
const ASKING = new Set(['needs-you', 'waiting'])

/** A row of any view (Due, By source, By Jev, the detail) as a point of the buckets: a row whose agent tab asks
 *  stands as that tab, answered in the tab as on the card of Work through; any other row as itself */
export function rowPoint(row, s) {
  const ref = row?.tab?.ref ?? null
  const tab = ref ? (s?.tabs?.tabs ?? []).find(x => x.ref === ref) ?? null : null
  if (tab && !tab.is_control && ASKING.has(tab.state)) return { group: 'asks', id: row.key, kind: 'tab', tab, row }
  return { group: 'row', id: row?.key ?? null, kind: 'row', row }
}

/** An agent tab of the tabs column as a point: one that asks stands in Do with its own answers; one that works or
 *  is the control session is no decision (null) */
export function tabPoint(tab) {
  return tab && !tab.is_control && ASKING.has(tab.state) ? { group: 'asks', id: `tab:${tab.ref}`, kind: 'tab', tab, row: null } : null
}

/** The bucket a point stands in on a list: its bucket (pointBucket), a backlog task the briefing holds in none
 *  under drop, where its answers park or keep it, so no row of a list stands in none */
export const viewBucket = x => pointBucket(x) ?? 'drop'

/** The bucket of a page item (By source): the bucket of its row, null for an item no answer reaches */
export function itemBucket(it, s, byKey) {
  const row = actionRow(it, byKey)
  return row ? viewBucket(rowPoint(row, s)) : null
}

/** Whether a page item stays under the strip's filter: with the buckets on a filter `b:<bucket>` keeps that
 *  bucket's items, without them the triage's; a filter of the other mode (left from before the switch moved) keeps
 *  all */
export function workShows(it, s, byKey, f) {
  const bucket = typeof f === 'string' && f.startsWith('b:') ? f.slice(2) : null
  if (flowBucketsOn(s)) return !bucket || itemBucket(it, s, byKey) === bucket
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

/** The word of "let the AI do it" (do_it): the delegate bucket's first answer while the buckets are on, so one act
 *  has one label on every view; else the page's own */
export function doWord(s, lang = 'en') {
  if (!flowBucketsOn(s)) return (TABLES[lang] ?? TABLES.en).action.do
  return upFirst(bucketDefs(s, lang).find(b => b.id === 'delegate')?.options?.[0] ?? (TABLES[lang] ?? TABLES.en).action.do)
}

/** The number a row shows on a list (Due, By source, the start page): while the buckets are on only its number in the
 *  printed briefing (brief_nr, "4 yes" in the chat acts on it), null for a row the briefing does not number, so no
 *  second number of the cockpit's own stands beside it; else the cockpit's own (model.numbers) */
export function shownNumber(row, s) {
  if (flowBucketsOn(s)) return Number.isInteger(row?.brief_nr) ? row.brief_nr : null
  return s?.model?.numbers?.[row?.key] ?? row?.number ?? null
}
