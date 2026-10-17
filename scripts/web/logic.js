// SPDX-License-Identifier: MIT
// Pure helpers of the cockpit: dates, durations, shortcut codes, mark
// colors and small read-only views over the server model. No DOM, no network, no
// state; the frontend test imports this file directly under node.
//
// The server decides everything about the domain (which section a row is in, which
// actions apply, whether a tab waits). These helpers only format and look things up.
import { TABLES } from './text.js'

/** The words of one language (text.js, rules/language-policy.md section 3); English for any other */
const tableOf = lang => (TABLES[lang] ?? TABLES.en).logic

export const DAY = 86400000

export function pad(n) {
  return String(n).padStart(2, '0')
}

/** Local calendar date of an epoch millisecond value, as YYYY-MM-DD */
export function isoDate(ms) {
  const d = new Date(ms)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** Local HH:MM of an epoch millisecond value */
export function clockTime(ms) {
  const d = new Date(ms)
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** The next Monday after `ms` (a Monday gives the Monday a week later), as epoch ms.
 * Port of nextMonday in mods/briefing-ui/hooks/logic.ts. */
export function nextMonday(ms) {
  const day = new Date(ms).getDay()
  return ms + ((8 - day) % 7 || 7) * DAY
}

/** "2026-10-14", "14.10." or "14.10.2026" as YYYY-MM-DD, else null.
 * A date without a year that already passed this year means next year.
 * Port of parseDate in mods/briefing-ui/hooks/logic.ts. */
export function parseDate(text, now) {
  const t = String(text ?? '').trim()
  if (/^\d{4}-\d{2}-\d{2}$/.test(t)) return isoDate(new Date(`${t}T12:00:00`).getTime()) === t ? t : null
  const m = /^(\d{1,2})\.(\d{1,2})\.?(\d{4})?$/.exec(t)
  if (!m) return null
  const year = m[3] ? Number(m[3]) : new Date(now).getFullYear()
  const probe = new Date(year, Number(m[2]) - 1, Number(m[1]))
  if (probe.getMonth() !== Number(m[2]) - 1 || probe.getDate() !== Number(m[1])) return null
  const date = `${year}-${pad(Number(m[2]))}-${pad(Number(m[1]))}`
  return !m[3] && date < isoDate(now) ? `${year + 1}-${pad(Number(m[2]))}-${pad(Number(m[1]))}` : date
}

/** "7 min", "1:05 h". Port of duration in mods/briefing-ui/hooks/logic.ts; negative is 0. */
export function duration(ms) {
  const min = Math.max(0, Math.floor(ms / 60000))
  return min < 60 ? `${min} min` : `${Math.floor(min / 60)}:${pad(min % 60)} h`
}

/** Collapse whitespace and cut to `max` characters with an ellipsis */
/** One line of at most `max`, cut at a word when one ends in the last third, never mid word otherwise */
export function short(text, max) {
  const line = String(text ?? '').replace(/\s+/g, ' ').trim()
  if (line.length <= max) return line
  let cut = line.slice(0, Math.max(1, max - 1))
  const space = cut.lastIndexOf(' ')
  if (space >= Math.floor(max * 2 / 3)) cut = cut.slice(0, space).replace(/[ ,;:·-]+$/, '')
  return cut + '…'
}

/** The mod's shortcut codes: "1a", "3b 4v". Letters: a do it, b later tomorrow, c drop,
 * v advise me, w do it in its own workspace. */
export const SHORTCUT = /^\d+[abcvw](\s+\d+[abcvw])*$/

/** Parsed codes as [{n, letter}], or null when the text is not a code line */
export function parseShortcut(text) {
  const t = String(text ?? '').trim().toLowerCase()
  if (!SHORTCUT.test(t)) return null
  return t.split(/\s+/).map(code => ({ n: Number(code.slice(0, -1)), letter: code.slice(-1) }))
}

/** Why a/w (start) is refused on a row, as in the mod's shortcut hook and card buttons:
 * 'approved', 'waiting', 'only_you', or null when starting is fine. */
export function startRefusal(row) {
  if (!row) return null
  if (row.inbox_state === 'approved') return 'approved'
  if (row.bucket === 'waiting') return 'waiting'
  if (row.inbox_id && row.gate === 'only-you') return 'only_you'
  return null
}

/**
 * Turn parsed codes into a plan, the way the mod's shortcut hook does (register.tsx):
 * rows with a live tab jump instead of a/v/w; a/w refused for only-you, waiting and
 * approved rows; all a rows together, all w rows together, all v rows together; b and c
 * per row. `rowFor(n)` returns the row numbered n or undefined.
 */
export function planShortcut(codes, rowFor) {
  const plan = { missing: [], jump: [], refused: [], do: [], ws: [], advise: [], later: [], drop: [] }
  for (const { n, letter } of codes) {
    const row = rowFor(n)
    if (!row) {
      plan.missing.push(n)
      continue
    }
    if (row.tab && row.tab.live && 'avw'.includes(letter)) plan.jump.push({ n, row })
    else if ('aw'.includes(letter) && startRefusal(row)) plan.refused.push({ n, row, reason: startRefusal(row) })
    else if (letter === 'b') plan.later.push({ n, row })
    else if (letter === 'c') plan.drop.push({ n, row })
    else if (letter === 'v') plan.advise.push({ n, row })
    else if (letter === 'w') plan.ws.push({ n, row })
    else plan.do.push({ n, row })
  }
  return plan
}

/** Design token for a profile mark color name. Never put a profile value into CSS. */
export function markToken(color) {
  const c = typeof color === 'string' ? color.trim().toLowerCase() : ''
  if (c === 'red') return 'danger'
  if (c === 'yellow' || c === 'orange') return 'warning'
  if (c === 'green') return 'success'
  if (c === 'blue' || c === 'cyan') return 'info'
  if (c === 'magenta' || c === 'purple') return 'secondary'
  return 'on-surface-muted'
}

/** Design token for a priority: P0 danger, P1 warning, P2 info, else muted */
export function prioToken(priority) {
  return { P0: 'danger', P1: 'warning', P2: 'info' }[priority] ?? 'on-surface-muted'
}

/** Design token for an item tone */
export function toneToken(tone) {
  return { bad: 'danger', warn: 'warning', dim: 'on-surface-muted' }[tone] ?? 'info'
}

/** Design token for a drawn state (ok, warn, bad, dim): a resource, a worker, a run */
export function runToken(tone) {
  return { ok: 'success', warn: 'warning', bad: 'danger' }[tone] ?? 'on-surface-muted'
}

/** A finding that asks for a look: high or medium */
export const serious = f => f?.severity === 'high' || f?.severity === 'medium'

/** Design token for a note tone (ok, info, warn, bad) */
export function noteToken(tone) {
  return { ok: 'success', warn: 'warning', bad: 'danger' }[tone] ?? 'info'
}

/** Design token for a tab state */
export function stateToken(state) {
  return { 'needs-you': 'danger', waiting: 'warning', working: 'success' }[state] ?? 'on-surface-muted'
}

export const SECTION_ORDER = ['now', 'give', 'work', 'later']

/** Every row of the model by key: the rows of all sections plus the hidden rows */
export function indexRows(model) {
  const byKey = new Map()
  if (!model) return byKey
  for (const s of model.sections ?? []) for (const r of s.rows ?? []) byKey.set(r.key, r)
  for (const r of model.hidden ?? []) if (!byKey.has(r.key)) byKey.set(r.key, r)
  for (const r of model.task_rows ?? []) if (!byKey.has(r.key)) byKey.set(r.key, r)
  return byKey
}

/** The rows a section shows: every row when expanded, else the compact keys */
export function sectionRows(section, expanded, byKey) {
  if (!section) return []
  if (expanded) return section.rows ?? []
  return (section.compact ?? []).map(k => byKey.get(k)).filter(Boolean)
}

/** All displayed rows in card order (now, give, work, later), for j/k navigation */
export function displayedRows(model, expanded, byKey) {
  if (!model) return []
  const out = []
  for (const id of SECTION_ORDER) {
    const s = (model.sections ?? []).find(x => x.id === id)
    out.push(...sectionRows(s, !!expanded[id], byKey))
  }
  return out
}

/** Number to row, from model.numbers */
export function rowByNumber(model, byKey) {
  const out = new Map()
  for (const [key, n] of Object.entries(model?.numbers ?? {})) {
    const r = byKey.get(key)
    if (r) out.set(n, r)
  }
  return out
}

const STATE_ORDER = { 'needs-you': 0, waiting: 1, working: 2, shell: 3 }

/** Tabs grouped by workspace, each group sorted needs-you, waiting, working, shell;
 * groups ordered by their most urgent tab, then by name. The control tab is left out. */
export function groupTabs(tabs) {
  const groups = new Map()
  for (const t of tabs ?? []) {
    if (t.is_control) continue
    const ws = t.workspace || ''
    if (!groups.has(ws)) groups.set(ws, [])
    groups.get(ws).push(t)
  }
  const rank = t => STATE_ORDER[t.state] ?? 4
  const out = [...groups.entries()].map(([workspace, list]) => ({
    workspace, tabs: list.slice().sort((a, b) => rank(a) - rank(b) || String(a.name).localeCompare(String(b.name))),
  }))
  out.sort((a, b) => rank(a.tabs[0]) - rank(b.tabs[0]) || a.workspace.localeCompare(b.workspace))
  return out
}

/** Tabs that want attention (waiting or long), most urgent first, without the control tab */
export function attentionTabs(tabs) {
  return (tabs ?? []).filter(t => !t.is_control && (t.waiting || t.long))
    .sort((a, b) => (STATE_ORDER[a.state] ?? 4) - (STATE_ORDER[b.state] ?? 4) || (a.since_ms ?? 0) - (b.since_ms ?? 0))
}

/** The two numbers of the running Claude sessions, one source for the Sessions tab and the start station:
 *  how many sessions there are, and how many subagents and workflows run in them */
export function sessionCounts(sessions) {
  const list = sessions ?? []
  return { sessions: list.length, agents: list.reduce((n, x) => n + (x.agents?.running_count ?? 0) + (x.workflows?.length ?? 0), 0) }
}

/** Seconds left of a running pass, from its remembered duration; null when unknown */
export function etaSeconds(loading, now) {
  if (!loading?.pass || !loading.eta_ms) return null
  const left = loading.eta_ms - (now - (loading.started_ms || now))
  return Math.max(1, Math.round(left / 1000))
}

/** Is the keyboard focus in a text field (then the single-key shortcuts stay off) */
export function isTypingTarget(el) {
  if (!el) return false
  const tag = (el.tagName || '').toLowerCase()
  if (tag === 'textarea' || tag === 'select') return true
  if (tag === 'input') {
    const type = (el.type || 'text').toLowerCase()
    return !['checkbox', 'radio', 'button', 'submit', 'reset'].includes(type)
  }
  return el.isContentEditable === true
}

/** Display a YYYY-MM-DD date with Intl in the page language; the raw text if unparsable */
export function formatDay(iso, lang, withYear = false) {
  if (typeof iso !== 'string' || !/^\d{4}-\d{2}-\d{2}/.test(iso)) return iso ?? ''
  const d = new Date(`${iso.slice(0, 10)}T12:00:00`)
  if (Number.isNaN(d.getTime())) return iso
  try {
    const opts = withYear ? { day: 'numeric', month: 'short', year: 'numeric' } : { weekday: 'short', day: 'numeric', month: 'short' }
    return new Intl.DateTimeFormat(lang, opts).format(d)
  } catch {
    return iso
  }
}

/** Local HH:MM:SS of an epoch ms value, via Intl */
/** When a chat was last used, short: the time today, else day and time ("14:05", "9.10. 14:05") */
export function chatStamp(ms, nowMs, lang) {
  if (typeof ms !== 'number' || !Number.isFinite(ms)) return ''
  const d = new Date(ms)
  const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`
  if (isoDate(ms) === isoDate(nowMs)) return hm
  return String(lang).startsWith('de') ? `${d.getDate()}.${d.getMonth() + 1}. ${hm}` : `${d.getMonth() + 1}/${d.getDate()} ${hm}`
}

export function formatClock(ms, lang) {
  try {
    return new Intl.DateTimeFormat(lang, { hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' }).format(new Date(ms))
  } catch {
    return clockTime(ms)
  }
}

/** Notes keep the newest `max` entries; an entry equal in text and tone to one of the last
 * few seconds is dropped (the server broadcasts action notes that the POST also returns). */
export function addNote(notes, note, now, max = 20, windowMs = 10000) {
  const dup = notes.some(n => n.text === note.text && n.tone === note.tone && now - (n.ms ?? 0) < windowMs)
  if (dup) return notes
  return [...notes, { ...note, ms: now }].slice(-max)
}

/** Insert or replace a relay record by id; newest first */
export function upsertRecord(records, record) {
  const rest = (records ?? []).filter(r => r.id !== record.id)
  return [record, ...rest].sort((a, b) => (b.created_ms ?? 0) - (a.created_ms ?? 0)).slice(0, 20)
}

/** Text of an API error in the page language; `table` is T() */
export function errorText(error, table) {
  if (!error) return table.errors.unknown
  const base = table.errors[error.code] ?? error.message ?? table.errors.unknown
  return error.field ? `${base} (${table.errorField(error.field)})` : base
}

// ---------------------------------------------------------------- connection, warnings, details, focus

/** Not open for this long: the page says the connection is lost (ms) */
export const CONN_GRACE_MS = 3000

/** The live stream is lost: refused ('down') at once, any other state than open after CONN_GRACE_MS */
export function connLost(conn, sinceMs, now) {
  if (conn === 'open') return false
  if (conn === 'down') return true
  return now - (sinceMs ?? now) >= CONN_GRACE_MS
}

/**
 * The states the page must never hide, at any width: a lost connection (the data shown no longer
 * updates), a model from the last run, a pass that failed. Each is a dot plus a written word.
 */
export function pageWarnings(s, t) {
  const out = []
  if (connLost(s.conn, s.connMs, s.now)) out.push({ token: 'warning', word: t.connLost })
  if (s.model?.stale) out.push({ token: 'warning', word: t.staleModel })
  const ld = s.loading ?? {}
  if (ld.last_error && !ld.pass) out.push({ token: 'danger', word: t.loadFailed(short(ld.last_error.message ?? '', 48)) })
  return out
}

/**
 * A single-key shortcut acts on the list behind the overlay, so none runs while a confirmation or a
 * drawer is open; `g` then `t` (focus the tabs) still does. Escape is handled before this check.
 */
export function modalKeyAllowed(ui, key, gPending) {
  if (ui?.confirm) return false
  if (!ui?.drawer) return true
  return key === 'g' || (gPending && key === 't')
}

/**
 * A detail (task or inbox entry) is fetched again when there is none, when an action touched it
 * (`stale`) or when a newer collect run came in (`ver`, the model's collected_ms). A failed load
 * waits for the retry button instead of trying on every render.
 */
export function detailNeedsLoad(entry, ver) {
  if (!entry) return true
  if (entry.status !== 'ok') return false
  return !!entry.stale || entry.ver !== ver
}

/** Marks the details of a row's inbox entry and task as stale (after an action on that row) */
export function invalidateDetails(details, row) {
  if (!row || (!row.inbox_id && !row.task)) return details
  const mark = (table, id) => (id && table[id] ? { ...table, [id]: { ...table[id], stale: true } } : table)
  return { ...details, inbox: mark(details.inbox, row.inbox_id), task: mark(details.task, row.task) }
}

/** The "more" lists fetched for the run the model shows; one from an older run would freeze the section */
export function freshMore(more, model) {
  const ver = model?.collected_ms
  const keep = Object.entries(more ?? {}).filter(([, v]) => model && v && v.ver === ver)
  return keep.length === Object.keys(more ?? {}).length ? more : Object.fromEntries(keep)
}

/** Where Tab moves inside a dialog of `count` focusable elements: around the ends, -1 when there is none */
export function nextFocusIndex(count, at, shift) {
  if (count <= 0) return -1
  if (at < 0) return shift ? count - 1 : 0
  return shift ? (at - 1 + count) % count : (at + 1) % count
}

// ---------------------------------------------------------------- task check (task.py review)

export const VERDICT_ORDER = ['close', 'stale', 'unclear', 'waiting', 'continue']

/** Design token for a check verdict: close and stale want a decision, waiting is information */
export function verdictToken(verdict) {
  return { close: 'danger', stale: 'warning', unclear: 'warning', waiting: 'info', continue: 'success' }[verdict] ?? 'on-surface-muted'
}

/** Filled and empty dots for a confidence, ●●○ */
export function confidenceDots(confidence) {
  const n = { high: 3, medium: 2, low: 1 }[confidence] ?? 0
  return '●'.repeat(n) + '○'.repeat(3 - n)
}

/** Rows that carry a verdict, filtered ('all', a verdict, 'changed') and sorted ('verdict', 'priority', 'activity') */
export function reviewRows(rows, filter = 'all', sort = 'verdict') {
  const rank = { P0: 0, P1: 1, P2: 2, P3: 3 }
  const vi = r => { const i = VERDICT_ORDER.indexOf(r.review.verdict); return i < 0 ? 9 : i }
  const quiet = r => (r.review.days_since_activity ?? -1)
  const keep = rows.filter(r => r?.review && (filter === 'all' || (filter === 'changed' ? r.review.changed : r.review.verdict === filter)))
  const by = {
    verdict: (a, b) => vi(a) - vi(b) || (rank[a.priority] ?? 4) - (rank[b.priority] ?? 4) || quiet(b) - quiet(a),
    priority: (a, b) => (rank[a.priority] ?? 4) - (rank[b.priority] ?? 4) || vi(a) - vi(b),
    activity: (a, b) => quiet(b) - quiet(a) || vi(a) - vi(b),
  }[sort] ?? (() => 0)
  return keep.slice().sort((a, b) => by(a, b) || String(a.title).localeCompare(String(b.title)))
}

/** Count per verdict, plus 'all' and 'changed' */
export function verdictCounts(rows) {
  const out = { all: 0, changed: 0 }
  for (const v of VERDICT_ORDER) out[v] = 0
  for (const r of rows) {
    if (!r?.review) continue
    out.all += 1
    out[r.review.verdict] = (out[r.review.verdict] ?? 0) + 1
    if (r.review.changed) out.changed += 1
  }
  return out
}

/** Cents as text in the page language, 0.42 -> "0,42" (de) */
export function centsText(ct, lang) {
  const n = Number(ct ?? 0)
  const text = n < 0.1 && n > 0 ? '<0.1' : n.toFixed(n < 10 ? 2 : 1)
  return lang === 'de' ? text.replace('.', ',') : text
}

// ---------------------------------------------------------------- drawings (check flow, verdict bar, agent lanes)

/** The drawn check: who answered how many. A tier draws from the one before it when that one was asked
 *  too (it cost something), since only its unclear answers go on; otherwise straight from the tasks */
export function checkFlow(last) {
  if (!last) return null
  const tiers = (last.tiers ?? []).map((x, i, all) => ({
    ...x, fromPrev: i > 0 && all[i - 1].cost_ct != null && x.answered > 0 && all[i - 1].cost_ct > 0,
  }))
  return { total: last.reviewed ?? 0, cached: last.cached ?? 0, tiers }
}

/** Segments of the verdict bar in VERDICT_ORDER: start and width as fractions of all counted rows */
export function verdictSegments(counts) {
  const total = VERDICT_ORDER.reduce((n, v) => n + (counts?.[v] ?? 0), 0)
  if (!total) return []
  let x = 0
  return VERDICT_ORDER.filter(v => (counts[v] ?? 0) > 0).map(v => {
    const seg = { verdict: v, n: counts[v], x, w: counts[v] / total }
    x += seg.w
    return seg
  })
}

/** The lane's width: the oldest running agent plus a quarter, in whole 5 minutes, 10 to 60 minutes */
export function laneWindow(agents, now) {
  const oldest = Math.max(0, ...(agents ?? []).map(a => now - (a.since_ms ?? now)))
  const five = 300000
  return Math.min(12 * five, Math.max(2 * five, Math.ceil(oldest * 1.25 / five) * five))
}

/** Where the running subagents of a session sit in a lane of the last windowMs: the start as a fraction
 *  (each runs on to the right edge), an agent older than the window starts at its left edge and says so */
export function agentLane(agents, now, windowMs = 1800000) {
  const from = now - windowMs
  return (agents ?? []).map(a => {
    const start = Math.max(from, Math.min(now, a.since_ms ?? now))
    return { id: a.id, x0: (start - from) / windowMs, older: (a.since_ms ?? now) < from }
  })
}

/** A running check against the last one: elapsed seconds and a fraction that stays below 1 until it ends */
export function runProgress(running, now, lastSec) {
  if (!running) return null
  const sec = Math.max(0, (now - running.started_ms) / 1000)
  const expected = lastSec > 0 ? lastSec : 60
  return { sec, expected, frac: Math.min(0.97, sec / expected), over: sec > expected }
}

/** The largest value among a section's gauges that have no max of their own: they compare to each other */
export function meterScale(items) {
  return Math.max(0, ...(items ?? []).map(it => (it?.meter && !it.meter.max ? it.meter.value : 0)))
}

/** A gauge as the page draws it: the fill as a fraction, the time already passed, and whether the value
 *  runs ahead of the time (more than 5 points), which is the reason to look at a quota at all */
export function meterView(meter, scale) {
  if (!meter) return null
  const top = meter.max ?? scale
  const frac = top > 0 ? Math.min(1, meter.value / top) : 0
  const pace = typeof meter.elapsed === 'number' ? meter.elapsed : null
  return { frac, pace, ahead: pace != null && frac > pace + 0.05, relative: !meter.max }
}

/** The gauge's value as text: 74 %, $12.50, 10 / 1000 EUR */
export function meterText(meter, value, lang) {
  const n = (x, d) => { const s = x.toFixed(d); return lang === 'de' ? s.replace('.', ',') : s }
  if (meter.unit === '%') return `${n(value, 0)} %`
  if (meter.unit === '$') return `$${value.toFixed(2)}`      // as the sources write dollars, with a point
  const d = Number.isInteger(meter.value) ? 0 : 2
  const max = meter.max != null && meter.unit !== '%' ? ` / ${n(meter.max, Number.isInteger(meter.max) ? 0 : 2)}` : ''
  return `${n(value, d)}${max}${meter.unit ? ` ${meter.unit}` : ''}`
}

/** A point on the gauge's half circle (center 100,100 in a 200 by 112 box): f 0 is the left end, 1 the right */
export function gaugePoint(f, r) {
  const a = Math.PI * (1 - Math.min(1, Math.max(0, f)))
  return [100 + r * Math.cos(a), 100 - r * Math.sin(a)]
}

/** The SVG path of the half circle's arc from f0 to f1 at radius r; empty when there is nothing to draw */
export function gaugeArc(f0, f1, r) {
  if (!(f1 > f0)) return ''
  const [x0, y0] = gaugePoint(f0, r)
  const [x1, y1] = gaugePoint(f1, r)
  return `M ${x0.toFixed(2)} ${y0.toFixed(2)} A ${r} ${r} 0 0 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`
}

/** The colored ranges of a gauge, only where the source named warn or bad: good, warning, bad */
export function gaugeBands(meter) {
  if (!meter?.max || (meter.warn == null && meter.bad == null)) return []
  const f = x => x / meter.max
  const cuts = [['success', 0], ...(meter.warn != null ? [['warning', f(meter.warn)]] : []),
    ...(meter.bad != null ? [['danger', f(meter.bad)]] : [])]
  return cuts.map(([token, from], i) => ({ token, from, to: i + 1 < cuts.length ? cuts[i + 1][1] : 1 }))
}

/** A section turns into gauge tiles when every row carries a gauge with its own max */
export function gaugeSection(items) {
  return (items ?? []).length > 0 && items.every(it => it?.meter?.max)
}

/** A Claude Code terminal as chat lines: what you typed (❯ or >), what Claude says (⏺), tool output (⎿),
 *  the rest as it stands. Blank runs collapse to one, so the stream reads like a chat */
export function screenLines(text) {
  const out = []
  let kind = 'plain'
  for (const raw of String(text ?? '').split('\n')) {
    const line = raw.replace(/\s+$/, '')
    const lead = line.trimStart()
    if (!line) {
      if (out.length && out[out.length - 1].text !== '') out.push({ kind: 'gap', text: '' })
      continue
    }
    if (/^[❯>]\s/.test(lead)) kind = 'user'
    else if (lead.startsWith('⏺')) kind = 'claude'
    else if (lead.startsWith('⎿')) kind = 'tool'
    else if (/^[─━═╭╰│]/.test(lead)) kind = 'frame'
    else if (kind === 'frame' || kind === 'tool') kind = 'plain'
    out.push({ kind, text: line })
  }
  while (out.length && out[out.length - 1].kind === 'gap') out.pop()
  return out
}

// ---------------------------------------------------------------- workers tab (workload view --json)

const WORKER_TONE = { in_sync: 'ok', observed: 'ok', intentionally_absent: 'dim', 'not reported': 'dim', not_provisioned: 'dim', absent: 'bad', disabled: 'bad',
  drifted: 'warn', inventory_missing: 'warn', source_drift: 'warn', inventory_stale: 'warn' }

/** A run's state as a tone: ok, warn, bad, dim; anything unknown is warn, never silently ok */
export function workerTone(run) {
  if (run?.retired) return 'dim'
  return WORKER_TONE[run?.state] ?? (run?.state ? 'warn' : 'ok')
}

/** How a recorded run is drawn: a shape and a tone, never colour alone */
export function stripMark(entry) {
  return { ok: ['●', 'ok'], failed: ['✗', 'bad'], expired: ['◑', 'warn'], skipped: ['○', 'dim'] }[entry?.verdict] ?? ['?', 'warn']
}

/** Counts per facet value over the runs a filter leaves when that facet itself is not applied */
export function workerFacets(runs, filter = {}) {
  const out = {}
  for (const facet of ['kind', 'sphere', 'state', 'host']) {
    const rest = filterWorkers(runs, { ...filter, [facet]: null })
    out[facet] = {}
    for (const r of rest) {
      const v = r[facet] || '?'
      out[facet][v] = (out[facet][v] ?? 0) + 1
    }
  }
  return out
}

/** Search, facets and "only with a finding" */
export function filterWorkers(runs, { q = '', kind = null, sphere = null, state = null, host = null, attention = false } = {}) {
  const needle = q.trim().toLowerCase()
  return (runs ?? []).filter(r => (!kind || r.kind === kind) && (!sphere || r.sphere === sphere)
    && (!state || r.state === state) && (!host || r.host === host)
    && (!attention || (r.findings ?? []).some(serious))
    && (!needle || `${r.id} ${r.title ?? ''} ${r.purpose ?? ''} ${r.system ?? ''}`.toLowerCase().includes(needle)))
}

/** Runs grouped by system in the order the view lists its systems, the rest after them */
export function groupBySystem(runs, systems = []) {
  const order = new Map((systems ?? []).map((s, i) => [s.id, i]))
  const groups = new Map()
  for (const r of runs) {
    const key = r.system || ''
    if (!groups.has(key)) groups.set(key, { id: key, title: (systems ?? []).find(s => s.id === key)?.title ?? key, runs: [] })
    groups.get(key).runs.push(r)
  }
  return [...groups.values()].sort((a, b) => (order.get(a.id) ?? 999) - (order.get(b.id) ?? 999) || a.id.localeCompare(b.id))
}

// ---------------------------------------------------------------- drawn sections: search, state, group, tags

/** State filters of a drawn section, by the row's tone */
export const TONE_FILTERS = [['all', () => true], ['problems', it => it.tone === 'bad' || it.tone === 'warn'],
  ['ok', it => !it.tone], ['off', it => it.tone === 'dim']]
/** The tone a state filter stands for, for its dot */
export const FILTER_TONE = { ok: 'ok', problems: 'warn', off: 'dim' }
export const toneFilter = key => (TONE_FILTERS.find(([k]) => k === key) ?? TONE_FILTERS[0])[1]

/** Rows that pass the search, the state, the group and every chosen tag ({label: value}) */
export function filterRows(items, { q = '', tone = 'all', group = null, tags = {} } = {}) {
  const needle = q.trim().toLowerCase()
  const keep = toneFilter(tone)
  return (items ?? []).filter(it => keep(it) && (!group || it.group === group)
    && Object.entries(tags).every(([k, v]) => !v || it.tags?.[k] === v)
    && (!needle || `${it.title} ${it.detail ?? ''} ${it.group ?? ''} ${Object.values(it.tags ?? {}).join(' ')}`
      .toLowerCase().includes(needle)))
}

/** The tag labels worth a row of chips: each with its values and how many rows each would leave,
 *  counted with that label's own choice off. A label with one value, or more than max, is left out */
export function tagFacets(items, filter = {}, max = 16) {
  const keys = [...new Set((items ?? []).flatMap(it => Object.keys(it.tags ?? {})))]
  const out = []
  for (const key of keys) {
    const all = new Set((items ?? []).map(it => it.tags?.[key]).filter(Boolean))
    if (all.size < 2 || all.size > max) continue
    const rest = filterRows(items, { ...filter, tags: { ...(filter.tags ?? {}), [key]: null } })
    const n = {}
    for (const it of rest) if (it.tags?.[key]) n[it.tags[key]] = (n[it.tags[key]] ?? 0) + 1
    out.push({ key, values: [...all].sort((a, b) => (n[b] ?? 0) - (n[a] ?? 0) || a.localeCompare(b)).map(v => [v, n[v] ?? 0]) })
  }
  return out
}

/** Rows under their group, groups in the order their first row comes (newest first for a log);
 *  rows without a group gather under '' at the end */
export function groupRows(items) {
  const groups = new Map()
  for (const it of items ?? []) {
    const key = it.group ?? ''
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key).push(it)
  }
  const out = [...groups].map(([key, rows]) => ({ key, rows }))
  return [...out.filter(g => g.key), ...out.filter(g => !g.key)]
}

/** Short weekday names Monday first, from the platform for the page's language ("Mo", "Di" / "Mon", "Tue") */
export function weekdayNames(lang) {
  const f = new Intl.DateTimeFormat(lang, { weekday: 'short' })
  return Array.from({ length: 7 }, (_, k) => f.format(new Date(2024, 0, 1 + k)).replace(/\.$/, ''))
}

// ---------------------------------------------------------------- triage: what a row is, whether it can go, who does it

export const TRIAGE_FILTERS = ['all', 'close', 'ai', 'you', 'unclear']

/** The key a task or inbox row is sorted under (scripts/triage.py), or null for any other row */
export function triageKey(it) {
  // an inbox row names its task too: the row is the item
  return it?.inbox ? `inbox:${it.inbox}` : it?.task ? `task:${it.task}` : null
}

function triageMatch(tri, f) {
  if (f === 'close') return tri?.verdict === 'close'
  if (f === 'ai') return tri?.doer === 'ai'
  if (f === 'you') return tri?.doer === 'you'
  if (f === 'unclear') return !tri || tri.verdict === 'unclear'
  return true
}

/** Whether a row stays under a filter; a row that is neither task nor inbox item always stays */
export function triageShows(it, map, f) {
  const key = triageKey(it)
  return !key || f === 'all' || !f || triageMatch((map ?? {})[key], f)
}

/** How many sorted rows each filter would show; `all` counts every row */
export function triageCounts(items, map) {
  const out = { all: (items ?? []).length, close: 0, ai: 0, you: 0, unclear: 0 }
  for (const it of items ?? []) {
    const key = triageKey(it)
    if (!key) continue
    for (const f of TRIAGE_FILTERS.slice(1)) if (triageMatch((map ?? {})[key], f)) out[f] += 1
  }
  return out
}

/** The AI's effort as 0 to 3 dots */
export const effortDots = e => ({ small: 1, medium: 2, large: 3 })[e] ?? 0

/** Whether a row of the Status, Dates, Trackers or More page offers Do it, Advise and Settle: the page says so
 *  (`actionable`), and a row with an inbox item or a task of its own keeps that path */
export function pageItemActs(it) {
  return !!(it?.actionable && it.key && !it.inbox && !it.task)
}

/** The row a page item acts through: the briefing's own row when it has one, else one made from the
 *  item (an inbox item or a task the page lists but the briefing does not); the server checks it again */
export function actionRow(it, byKey) {
  const key = triageKey(it)
  if (!key) return pageItemActs(it) ? { key: it.key, title: it.title, settle: ['done', 'not_doing'] } : null
  const own = byKey?.get(key)
  if (own) return own
  // an inbox item that runs on (put off with what it waits on) is no row of the day: it can open again
  return it.inbox ? { key, title: it.title, inbox_id: it.inbox, settle: ['done', 'not_doing'],
    runs: (it.lines ?? []).some(l => l.kind === 'look') }
    : { key, title: it.title, task: it.task, settle: ['done', 'not_doing'], closable: true }
}

// ---------------------------------------------------------------- item drawer

const URL_RE = /\bhttps?:\/\/[^\s<>"'`]+/g

/** A text in pieces: plain runs and http(s) links, a trailing period or bracket left outside the link */
export function linkParts(value) {
  const text = typeof value === 'string' ? value : ''
  const out = []
  let at = 0
  for (const m of text.matchAll(URL_RE)) {
    let href = m[0]
    while (/[.,;:!?)\]}]$/.test(href)) href = href.slice(0, -1)
    if (m.index > at) out.push({ text: text.slice(at, m.index) })
    out.push({ href, text: href })
    at = m.index + href.length
  }
  if (at < text.length) out.push({ text: text.slice(at) })
  return out
}

function probeDate(value) {
  const m = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}:\d{2}))?/.exec(String(value ?? ''))
  return m ? `${m[3]}.${m[2]}.${m[1]}${m[4] ? ` ${m[4]}` : ''}` : String(value ?? '')
}

/** How an inbox item closes on its own (its closes_when probe), in the page's words; null without one */
export function probeText(spec, t) {
  if (!spec || typeof spec !== 'object' || Array.isArray(spec)) return null
  const p = t.probe
  for (const combine of ['all', 'any']) {
    if (Array.isArray(spec[combine])) {
      return spec[combine].map(x => probeText(x, t) ?? p.unknown).join(combine === 'all' ? ` ${p.and} ` : ` ${p.or} `)
    }
  }
  if ('gh_pr' in spec) return p.ghPr(String(spec.gh_pr), String(spec.state ?? 'merged'))
  if ('gh_issue' in spec) return p.ghIssue(String(spec.gh_issue), String(spec.state ?? 'closed'))
  if ('task_status' in spec) return p.taskStatus(String(spec.task_status), String(spec.status ?? 'done'))
  if ('path_exists' in spec) return p.pathExists(String(spec.path_exists))
  if ('after' in spec) return p.after(probeDate(spec.after))
  if ('unseen_for' in spec) return p.unseenFor(String(spec.unseen_for?.hours ?? '?'))
  if ('command' in spec) return p.command(Array.isArray(spec.command) ? spec.command.join(' ') : String(spec.command))
  return p.unknown
}

/** Events newest first; one without a time goes last. The input is left as it is */
export function newestFirst(events) {
  return [...(events ?? [])].sort((a, b) => String(b?.at ?? '').localeCompare(String(a?.at ?? '')))
}

/** The overview's status rows, each with the tone it is drawn in: a source that failed (danger, with
 *  its reason), a probe with findings (warning), any other count (info) in view, in that order; the
 *  quiet ones (nothing to count, or a source that comes with the full pass) folded away */
export function statusSplit(rows) {
  const toned = (rows ?? []).map(x => ({
    ...x,
    tone: x.state === 'error' ? 'danger' : x.state === 'skipped' ? 'neutral'
      : !(Number(x.count) > 0) ? 'success' : x.probe ? 'warning' : 'info',
  }))
  const rank = ['danger', 'warning', 'info']
  const loud = rank.flatMap(tone => toned.filter(x => x.tone === tone))
  return { loud, quiet: toned.filter(x => !rank.includes(x.tone)) }
}

const WEEK = ['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU']

function weekdays(list, lang) {
  const idx = list.map(d => WEEK.indexOf(d))
  if (idx.some(i => i < 0)) return null
  const names = tableOf(lang).days
  const run = idx.length > 2 && idx.every((v, k) => k === 0 || v === idx[k - 1] + 1)
  return run ? `${names[list[0]]} ${tableOf(lang).sched.to} ${names[list[list.length - 1]]}` : list.map(d => names[d]).join(', ')
}

/** A run's schedule as `workload view` writes it (every 300s, FREQ=...;BYDAY=... at HH:MM, continuous,
 *  N path(s) watched) in words; anything else stays as it came */
export function scheduleText(when, lang = 'en') {
  const L = tableOf(lang).sched
  const w = String(when ?? '').trim()
  let m = w.match(/^every (\d+)s$/)
  if (m) {
    const sec = Number(m[1])
    const amount = sec < 60 || sec % 60 ? `${sec} s` : sec % 3600 ? `${sec / 60} min` : `${sec / 3600} h`
    return `${L.every} ${amount}`
  }
  if (w === 'continuous') return L.continuous
  m = w.match(/^(\d+) path\(s\) watched$/)
  if (m) return L.watched(Number(m[1]))
  const parts = w.split(/;\s*(?=FREQ=)/)
  const rules = parts.map(p => p.match(/^FREQ=(DAILY|WEEKLY)(?:;BYDAY=([A-Z,]+))? at (\d\d:\d\d)$/))
  if (!w || rules.some(r => !r)) return w
  const out = []
  for (const [, freq, days, at] of rules) {
    const head = freq === 'DAILY' ? L.daily : weekdays((days ?? '').split(','), lang === 'de' ? 'de' : 'en')
    if (!head) return w
    const same = out.find(o => o.head === head)
    if (same) same.times.push(at)
    else out.push({ head, times: [at] })
  }
  return out.map(o => `${o.head} ${o.times.join(', ')}`).join('; ')
}


/** The note under a run's day axis (`workload view`) in words, the last run in local time */
export function dayNoteText(note, lang = 'en') {
  const L = tableOf(lang).notes
  return String(note ?? '').split(/;\s*/).filter(Boolean).map(part => {
    if (part === 'nothing says this schedule is behind') return L.behind
    if (part === 'nothing here can judge this schedule') return L.judge
    if (part.startsWith('fires when a path changes')) return L.path
    let m = part.match(/^last run (\d\d:\d\d) local\b/)
    if (m) return L.last(m[1])
    m = part.match(/^last run (\d{4}-\d\d-\d\dT[\d:.]+Z)/)
    if (m) {
      const d = new Date(m[1])
      if (!Number.isNaN(d.getTime())) return L.last(d.toLocaleTimeString(lang, { hour: '2-digit', minute: '2-digit' }))
    }
    return part
  }).join(' · ')
}

/** A row's detail line (`a · b`) with the inbox kind and gate the server writes as machine words in the
 *  page's language; every other part stays */
export function detailText(detail, t) {
  return String(detail ?? '').split(' · ').map(p => t.item?.kindName?.[p] ?? t.gate?.[p] ?? p).join(' · ')
}

// The pages where work is handed to the AI and comes back: only there the agent tab column stands beside
// the page; everywhere else it folds to its header button and the page keeps the full width
const RAIL = new Set(['briefing', '@chat'])
export function railShown(page) {
  return RAIL.has(page)
}

/** The one next step a slim tab card offers, as action keys: answer a question, go on, close a tab
 *  that filed its result or whose start is settled, else go to the tab; `can(right)` says what this cockpit
 *  may do with a tab (canTab) */
export function tabNextStep(tab, can, settled = false) {
  const own = !tab.is_control
  const finished = !!tab.filed_by || settled
  if (tab.state === 'needs-you' && can('key')) return ['yes', 'no']
  if (tab.state === 'waiting' && own && finished && can('close')) return ['close']
  if (tab.state === 'waiting' && own && !tab.filed_by) return ['go_on']
  if (can('focus')) return ['jump']
  return can('screen') ? ['view'] : []
}

/** The time a page section names beside its title: only when its source measured at another time than
 *  the pass the header names, so one screen shows one as-of time unless a source really is older */
export function sectionStamp(asOf, collectedAt) {
  return asOf && asOf !== collectedAt ? asOf : null
}

/** A tab's screen text as one plain line: no code fences, prompt marks, box rules or runs of blanks */
export function previewText(text) {
  return String(text ?? '').replace(/```/g, ' ').replace(/[\u2500-\u257f\u276f\u203a]+/g, ' ').replace(/\s+/g, ' ').trim()
}

// ---------------------------------------------------------------- the Betrieb page: overview tiles, tokens of the week

/** A token count short in the words of text.js: 950, 340k, 1.2M, 1.6B (en), the decimal comma for de */
export function tokenText(n, lang) {
  const v = Math.max(0, Number(n) || 0)
  const U = tableOf(lang).tokens
  if (v < 1000) return String(Math.round(v))
  if (v < 1e6) return `${Math.round(v / 1000)}${U.k}`
  const [d, unit] = v < 1e9 ? [1e6, U.m] : [1e9, U.b]
  const m = (v / d).toFixed(v / d < 10 ? 1 : 0)
  return `${lang === 'de' ? m.replace('.', ',') : m}${unit}`
}

/** One tile of a page overview: how many rows its section has, how many are loud (bad or warn) and the first of
 *  them, the fullest gauge when the section is gauges, and one tone for the tile */
export function sectionTile(section) {
  const items = section?.items ?? []
  const count = section?.total ?? section?.count ?? items.length
  if (section?.status === 'error') return { count, loud: 0, tone: 'danger', note: section.reason || null, peak: null, counts: null, state: 'error' }
  if (section?.status === 'skipped') return { count, loud: 0, tone: 'neutral', note: null, peak: null, counts: null, state: 'skipped' }
  const loud = items.filter(it => it.tone === 'bad' || it.tone === 'warn')
  let peak = null
  let tone = loud.some(it => it.tone === 'bad') ? 'danger' : loud.length ? 'warning' : 'neutral'
  // a gauge with limits is a quota (higher is worse): the tile shows the fullest; one without is a count
  if (gaugeSection(items) && items.some(it => it.meter.warn != null || it.meter.bad != null)) {
    const top = items.reduce((a, it) => (it.meter.value / it.meter.max > a.meter.value / a.meter.max ? it : a))
    peak = { title: String(top.title ?? '').replace(/:\s*[\d.,]+\s*%?$/, ''), percent: Math.round((top.meter.value / top.meter.max) * 100) }
    const m = top.meter
    if (tone === 'neutral') tone = m.bad != null && m.value >= m.bad ? 'danger' : m.warn != null && m.value >= m.warn ? 'warning' : 'success'
  } else if (tone === 'neutral' && section?.alarm && count === 0) tone = 'success'
  const counts = gaugeSection(items) && !peak ? items.map(it => ({ title: it.title, value: it.meter.value, max: it.meter.max })) : null
  return { count, loud: loud.length, tone, note: loud[0]?.title ?? null, peak, counts, state: 'ok' }
}

export const USAGE_SOURCES = ['session', 'subagent', 'worker']

/** The week of tokens as stacked bars: per day the written tokens of each source, as a share of the largest day */
export function usageBars(usage) {
  const days = usage?.days ?? []
  const max = Math.max(0, ...days.map(d => d.output ?? 0))
  return {
    max,
    days: days.map(d => ({
      day: d.day, total: d.output ?? 0,
      parts: USAGE_SOURCES.map(s => ({ source: s, value: d.sources?.[s]?.output ?? 0 }))
        .filter(p => p.value > 0).map(p => ({ ...p, frac: max ? p.value / max : 0 })),
    })),
  }
}

/** Today's written tokens and the usual day (the mean of the earlier days with any use; null without one) */
export function usageToday(usage) {
  const days = usage?.days ?? []
  if (!days.length) return { today: 0, usual: null }
  const earlier = days.slice(0, -1).map(d => d.output ?? 0).filter(n => n > 0)
  return { today: days[days.length - 1].output ?? 0, usual: earlier.length ? Math.round(earlier.reduce((a, b) => a + b, 0) / earlier.length) : null }
}

// ---------------------------------------------------------------- a work page in the order of Jev

/** The label a row of a work page carries: its kind's word for a section named after its kind
 *  (inbox, tasks, workplace), else the section title up to its bracket */
export function workLabel(section, kinds) {
  if (section?.id && section.id === section.kind && kinds?.[section.kind]) return kinds[section.kind]
  return String(section?.title ?? section?.id ?? '').split(' (')[0].trim()
}

const level = v => (typeof v === 'number' ? Math.round(Math.max(0, Math.min(1, v)) * 3) : null)

/** The page of group `work`: it has no tab of its own, it is the "by source" view of the work tab */
export function workPageOf(pages) {
  return (pages ?? []).find(p => p?.group === 'work') ?? null
}

/** The views of the work tab: what is due (the four blocks) always, by source where a work page exists,
 *  by Jev where that page asks for an order and Jev is switched on and has its key */
export function workViews(page, jev) {
  return ['due', ...(page ? ['area'] : []), ...(page?.jev && jev?.enabled && jev?.ready ? ['jev'] : [])]
}

/** The view the work tab shows: the remembered one where it can, else what is due */
export function workViewOf(view, page, jev) {
  return workViews(page, jev).includes(view) ? view : 'due'
}

/** The rows of a work page for the order of Jev: `ranked` in Jev's order, `rest` (not sent, or new since)
 *  in page order. A row standing in two sections shows once, in the first. Each entry: {it, section, label,
 *  rank, judge}, judge being Jev's levels 0 to 3 and whether only the person can do it */
export function jevList(sections, order, kinds) {
  const byKey = new Map((order?.items ?? []).map(x => [x.key, x]))
  const seen = new Set()
  const ranked = []
  const rest = []
  for (const sec of sections ?? []) {
    for (const it of sec.items ?? []) {
      const key = triageKey(it)
      const mark = key ?? `${sec.id}:${it.index}`
      if (seen.has(mark)) continue
      seen.add(mark)
      const o = key ? byKey.get(key) : null
      const row = { it, section: sec.id, label: workLabel(sec, kinds), rank: o?.rank ?? null, judge: null }
      if (o) {
        row.judge = { urgency: level(o.urgency), impact: level(o.impact), effort: level(o.effort),
          onlyMe: typeof o.only_me === 'number' ? o.only_me >= 0.5 : null }
        ranked.push(row)
      } else rest.push(row)
    }
  }
  ranked.sort((a, b) => a.rank - b.rank)
  return { ranked: order ? ranked : [], rest: order ? rest : [...ranked, ...rest] }
}

/** The kinds of rows a page holds, for its filter: one entry per label (a section's kind word or its short
 *  title) with its count and sections, empty sections left out. Only for a page holding inbox and task rows
 *  together, else none */
export function workKinds(sections, kinds) {
  const list = sections ?? []
  if (!list.some(s => s.kind === 'inbox') || !list.some(s => s.kind === 'tasks')) return []
  const out = []
  for (const sec of list) {
    const n = sec.total ?? (sec.items ?? []).length
    if (!n) continue
    const label = workLabel(sec, kinds)
    const k = out.find(x => x.label === label)
    if (k) { k.n += n; k.sections.push(sec.id) } else out.push({ label, n, sections: [sec.id] })
  }
  return out
}

/** Where the task check stands when inbox and tasks share a page: that page and the label of its tasks
 *  section ({page, label}), else null and the check keeps a tab of its own */
export function reviewHome(pages, kinds) {
  for (const p of pages ?? []) {
    const tasks = (p.sections ?? []).find(sec => sec.kind === 'tasks')
    if (tasks && workKinds(p.sections, kinds).length) return { page: p.id, label: workLabel(tasks, kinds) }
  }
  return null
}

/** Whether the terminal driver can do this to a tab (focus, key, screen, close); not known yet counts as yes */
export function canTab(s, verb) {
  const caps = s?.driver?.caps
  return !Array.isArray(caps) || caps.includes(verb)
}

// ---------------------------------------------------------------- the start page

/** The part of the day a greeting names: night before 5 and from 22, early to 11, day to 17, evening after */
export function greetingPart(hour) {
  if (hour < 5 || hour >= 22) return 'night'
  if (hour < 11) return 'early'
  if (hour < 17) return 'day'
  return 'evening'
}

/** The project a row belongs to: its area, else its first area name, else the label of its mark */
function rowProject(row) {
  return row?.area || row?.area_names?.[0] || row?.mark?.label || ''
}

/** The project chips of the start page: the workspaces of the agent tabs and the projects of the rows,
 *  the most frequent first (ties by name), each name once whatever its case; the spelling seen first wins,
 *  tabs before rows. The control tab and nameless entries count for nothing */
export function homeProjects(tabs, rows) {
  const seen = new Map()
  const add = name => {
    const key = String(name ?? '').trim().toLowerCase()
    if (!key) return
    const x = seen.get(key) ?? { name: String(name).trim(), n: 0 }
    x.n += 1
    seen.set(key, x)
  }
  for (const t of tabs ?? []) if (!t.is_control) add(t.workspace)
  for (const r of rows ?? []) add(rowProject(r))
  return [...seen.values()].sort((a, b) => b.n - a.n || a.name.localeCompare(b.name)).map(x => x.name)
}

/** Does a tab or a row belong to the chosen project? No project chosen: everything does */
export function inProject(x, project) {
  if (!project) return true
  const want = String(project).toLowerCase()
  const names = [x?.workspace, x?.area, ...(x?.area_names ?? []), x?.mark?.label]
  return names.some(n => n && String(n).toLowerCase() === want)
}

/** The cards of "continue": the agent tabs of the project without the control tab and bare shells,
 *  the ones that need you first, then waiting, then working; within a state the longest first */
export function homeContinue(tabs, project) {
  const rank = t => STATE_ORDER[t.state] ?? 4
  return (tabs ?? []).filter(t => !t.is_control && t.state !== 'shell' && inProject(t, project))
    .sort((a, b) => rank(a) - rank(b) || (a.since_ms ?? 0) - (b.since_ms ?? 0))
}

const PROJECT_TONES = ['secondary', 'accent', 'success', 'warning', 'info']

/** A project's tone for its card band: the same name always the same DESIGN.md token, whatever its case */
export function projectTone(name) {
  let h = 0
  for (const ch of String(name ?? '').toLowerCase()) h = (h * 31 + ch.codePointAt(0)) >>> 0
  return PROJECT_TONES[h % PROJECT_TONES.length]
}

/** The agent tab that works on a task, by the task's slug */
export function tabOfTask(tabs, slug) {
  if (!slug) return null
  return (tabs ?? []).find(t => t.slug === slug) ?? null
}

/** What a gauge's pace means: its share per day against the even share of its window (the budget),
 *  and where it ends at the reset if it goes on like this. Too early in the window (under 2 %) or
 *  without a window there is nothing to reckon; a window under a day has no share per day */
export function meterPace(meter) {
  const e = meter?.elapsed
  if (!meter?.max || e == null || e < 0.02) return null
  const projected = meter.value / e
  const days = meter.window_h >= 24 ? meter.window_h / 24 : null
  const perDay = days ? meter.value / (e * days) : null
  const budget = days ? meter.max / days : null
  return { perDay, budget, projected, over: projected > meter.max }
}

/** A label as part of a tile id: lower case, no accents, words joined by hyphens */
export function tileSlug(text) {
  return String(text ?? '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase()
    .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 60)
}

const HOME_SHELVES = ['focus', 'returns', 'pinned', 'continue', 'waiting', 'tasks', 'starts']
const HOME_OPTIONS = ['today', 'preview', 'trend', 'title', 'project', 'pulse', 'classic']
const HOME_CORE = ['scan', 'brief']   // what a click on the bridge's core does; several combine
const OFF_BY_DEFAULT = new Set(['o:classic', 'k:brief'])   // the bridge stage is the start page; the tiles of before are a choice

/** Everything the start page can show, in the order it offers it: each gauge in percent of a page (a quota),
 *  the counts of the day, every page of the profile, the shelves, and the options that change how things
 *  show. Ids are stable across loads */
export function homeCatalog(model, { workers = true } = {}) {
  const out = []
  for (const p of model?.pages ?? []) {
    for (const sec of p.sections ?? []) {
      for (const it of sec.items ?? []) {
        if (it.meter?.unit !== '%' || !it.meter.max) continue
        const label = String(it.title ?? '').replace(/:\s*[\d.,]+\s*%\s*$/, '')
        out.push({ id: `q:${sec.id}:${tileSlug(label)}`, kind: 'quota', label, it, page: p.id, section: sec.id })
      }
    }
  }
  for (const id of ['c:waiting', 'c:returns', 'c:tabs', 'c:agents', 'c:workers', 'c:next', 'c:done']) {
    if (id !== 'c:workers' || workers) out.push({ id, kind: 'count' })
  }
  for (const p of model?.pages ?? []) out.push({ id: `p:${p.id}`, kind: 'page', label: p.title, page: p })
  for (const x of HOME_SHELVES) out.push({ id: `s:${x}`, kind: 'shelf' })
  for (const x of HOME_OPTIONS) out.push({ id: `o:${x}`, kind: 'option' })
  for (const x of HOME_CORE) out.push({ id: `k:${x}`, kind: 'core' })
  return out
}

/** What a page shows before anyone chose: the first quota of a window of a day or more, what waits on you,
 *  the next date, the page with the tasks, every shelf and every option */
function homeDefaults(model, all) {
  const quota = all.find(x => x.kind === 'quota' && x.it.meter.window_h >= 24) ?? all.find(x => x.kind === 'quota')
  const work = (model?.pages ?? []).find(p => (p.sections ?? []).some(sec => sec.kind === 'tasks'))
  return new Set([quota?.id, 'c:waiting', 'c:returns', 'c:agents', 'c:workers', 'c:next', work ? `p:${work.id}` : null,
    ...HOME_SHELVES.map(x => `s:${x}`), ...HOME_OPTIONS.map(x => `o:${x}`), ...HOME_CORE.map(x => `k:${x}`)]
    .filter(x => x && !OFF_BY_DEFAULT.has(x)))
}

/** What the start page shows, in its order: the choice made ({tiles, seen} from the server), else the
 *  defaults. A choice keeps its order; an entry the chooser had not offered yet when it was made comes with
 *  its default, at the end; an id that no longer exists drops out */
export function homeChosen(model, saved) {
  const all = homeCatalog(model)
  const known = new Set(all.map(x => x.id))
  const defaults = homeDefaults(model, all)
  if (!Array.isArray(saved?.tiles)) return all.map(x => x.id).filter(id => defaults.has(id))
  const seen = new Set(saved.seen ?? [])
  const kept = saved.tiles.filter(id => known.has(id))
  const added = all.map(x => x.id).filter(id => !seen.has(id) && !kept.includes(id) && defaults.has(id))
  return [...kept, ...added]
}

/** An id moved one place earlier (-1) or later (+1) in a list; at an end it stays */
export function moveId(list, id, step) {
  const i = list.indexOf(id)
  const j = i + step
  if (i < 0 || j < 0 || j >= list.length) return list
  const out = list.slice()
  out[i] = list[j]
  out[j] = id
  return out
}

/** The one next step of the start page: a tab that asks you, else the first row waiting on you, else the
 *  first P0 or P1 task of the backlog; nothing when there is none */
export function focusPick(tabs, model) {
  const asking = (tabs ?? []).find(t => !t.is_control && t.state === 'needs-you')
  if (asking) return { kind: 'tab', tab: asking }
  const rows = id => (model?.sections ?? []).find(x => x.id === id)?.rows ?? []
  const first = rows('now')[0]
  if (first) return { kind: 'row', row: first }
  const task = rows('work').find(r => r.task && /^P[01]$/.test(r.priority ?? ''))
  return task ? { kind: 'row', row: task } : null
}

/** The next date that has not begun, from every calendar section of the pages (rows with `at`) */
export function nextEvent(model, nowMs) {
  return upcomingEvents(model, nowMs, 1)[0] ?? null
}

/** Every coming event of the calendar sections, soonest first, at most `limit`: the list beside an opened one */
export function upcomingEvents(model, nowMs, limit = Infinity) {
  const out = []
  for (const p of model?.pages ?? []) {
    for (const sec of p.sections ?? []) {
      if (sec.kind !== 'calendar') continue
      for (const it of sec.items ?? []) {
        const ms = it.at ? Date.parse(it.at) : NaN
        if (Number.isFinite(ms) && ms > nowMs) out.push({ it, ms, page: p.id, section: sec.id })
      }
    }
  }
  return out.sort((a, b) => a.ms - b.ms).slice(0, limit)
}

/** How long until a moment, in words a countdown reads: minutes, then hours and minutes, then days and hours */
export function untilText(ms) {
  const min = Math.floor(Math.max(0, ms) / 60000)
  const h = Math.floor(min / 60)
  if (h >= 24) return `${Math.floor(h / 24)} d ${h % 24} h`
  return h ? `${h} h ${min % 60} min` : `${min} min`
}

/** How many of a page's items belong to a project (by mark or area) */
export function countInProject(items, project) {
  return (items ?? []).filter(it => inProject(it, project)).length
}

/** The bridge of the start page (the explainer films' picture): a viewBox of 680 by 520 with the core in
 *  the middle, its rings squashed a little as seen from above */
export const STAGE = { w: 680, h: 520, cx: 340, cy: 255, rx: 250, ry: 192, squash: 0.92, rim: 128 }
export const MAX_STATIONS = 14   // beyond ten the ring widens and the stations draw compact

/** Where up to fourteen stations stand around the core: spread over an ellipse, clockwise, each with the
 *  curved link from the core's rim to it (an SVG path); more than ten widen the ellipse */
export function stageSpots(n) {
  const k = Math.min(n, MAX_STATIONS)
  const rx = k > 10 ? 292 : STAGE.rx
  const ry = k > 10 ? 210 : STAGE.ry
  const out = []
  // the stations stand between the angles, so none sits straight above or below the core
  for (let i = 0; i < k; i++) {
    const a = -Math.PI / 2 + ((i + 0.5) / k) * Math.PI * 2
    const x = STAGE.cx + rx * Math.cos(a)
    const y = STAGE.cy + ry * Math.sin(a)
    const from = { x: STAGE.cx + STAGE.rim * Math.cos(a), y: STAGE.cy + STAGE.rim * STAGE.squash * Math.sin(a) }
    // the bend: halfway, pushed sideways a little, always to the same side
    const mx = (from.x + x) / 2 - Math.sin(a) * 28
    const my = (from.y + y) / 2 + Math.cos(a) * 28
    const f = v => v.toFixed(1)
    out.push({ x, y, from, path: `M${f(from.x)} ${f(from.y)} Q${f(mx)} ${f(my)} ${f(x)} ${f(y)}` })
  }
  return out
}

/** The dust of the stage: n points from a fixed seed, so every render draws the same sky */
export function stageDust(n, seed = 1) {
  let v = seed >>> 0 || 1
  const rnd = () => ((v = (v * 1664525 + 1013904223) >>> 0) / 4294967296)
  return Array.from({ length: n }, () => ({ x: rnd() * STAGE.w, y: rnd() * STAGE.h, r: 0.6 + rnd() * 0.9, o: 0.25 + rnd() * 0.5 }))
}

/** The beat of a station's heart line, in seconds: fast and uneven when red, calmer the better it goes;
 *  a station with nothing to say has no beat */
export function pulseSpeed(tone) {
  return { danger: 0.75, warning: 1.4, info: 2.6, success: 3.6 }[tone] ?? null
}

/** What a speech recognition error says to the person: the microphone was refused, nothing was heard, the
 *  service could not be reached, or something else. Stopped by hand says nothing */
export function speechError(code) {
  if (code === 'aborted') return null
  if (['not-allowed', 'service-not-allowed', 'audio-capture'].includes(code)) return 'denied'
  if (code === 'no-speech') return 'nothing'
  if (code === 'network') return 'network'
  return 'other'
}

export const RETURN_STAGES = ['started', 'working', 'asks', 'result', 'done']

/** Where a start stands now: the server knows the answer and the close; the tab's state the page sees itself,
 *  so a tab that just began to wait shows at once, not with the next collection */
export function liveStage(r, tabs, nowMs) {
  if (r.stage === 'result' || r.stage === 'done') return r.stage
  const mine = (tabs ?? []).filter(t => !t.is_control && (t.ref === r.tab?.ref || t.slug === r.item || t.item === r.item))
  if (mine.some(t => t.state !== 'working')) return 'asks'
  if (mine.length) return 'working'
  return nowMs - r.at_ms < 180000 ? 'started' : 'lost'
}

/** The starts handed to the AI by what they want of you: done or answered and to check, a question, at
 *  work, or gone without a word. Newest first within a group, as the server sends them */
export function aiGroups(returns, tabs, nowMs) {
  const g = { check: [], asks: [], working: [], lost: [] }
  for (const r of returns ?? []) {
    const live = liveStage(r, tabs, nowMs)
    const to = live === 'done' || live === 'result' ? 'check' : live === 'asks' ? 'asks' : live === 'lost' ? 'lost' : 'working'
    g[to].push({ ...r, live })
  }
  return g
}

/** The tabs whose start is settled (its inbox item closed, its task done): nothing is left for them to do */
export function settledRefs(returns, tabs, nowMs) {
  const open = new Set((tabs ?? []).map(t => t.ref))
  return new Set((returns ?? []).filter(r => r.tab?.ref && open.has(r.tab.ref) && liveStage(r, tabs, nowMs) === 'done').map(r => r.tab.ref))
}

/** What the AI left for you: checks whose tab is still open, tabs settled on their own, and the questions */
export function aiWaiting(returns, tabs, nowMs) {
  const g = aiGroups(returns, tabs, nowMs)
  const open = new Set((tabs ?? []).map(t => t.ref))
  const done = new Set(g.check.filter(r => r.tab?.ref && open.has(r.tab.ref)).map(r => r.tab.ref))
  for (const t of tabs ?? []) if (t.settled && t.state === 'waiting' && !t.is_control) done.add(t.ref)
  return done.size + g.asks.length
}

/** The tone of a stage: an answer is good news, a question waits on you, work runs, a lost start is red */
export function stageTone(stage) {
  return { started: 'info', working: 'info', asks: 'warning', result: 'success', done: 'success', lost: 'danger' }[stage] ?? 'muted'
}

/** What happened between two states of the page, for the live feed: rows that came and went, a row turned
 *  urgent, a tab that now asks you, an answer in the return channel, a new finding. The first state has no
 *  before, so nothing happened yet */
export function feedEvents(prev, next, prevTabs, nextTabs, at) {
  if (!prev || !next) return []
  const out = []
  const rows = m => new Map((m.sections ?? []).filter(x => x.id === 'now').flatMap(x => x.rows ?? []).map(r => [r.key, r]))
  const a = rows(prev)
  const b = rows(next)
  for (const [key, r] of b) {
    const was = a.get(key)
    if (!was) out.push({ kind: 'new', key, title: r.title, at })
    else if (r.urgency === 'now' && was.urgency !== 'now') out.push({ kind: 'urgent', key, title: r.title, at })
  }
  for (const [key, r] of a) if (!b.has(key)) out.push({ kind: 'gone', key, title: r.title, at })
  const tabs = new Map((prevTabs ?? []).map(t => [t.ref, t]))
  for (const t of nextTabs ?? []) {
    const was = tabs.get(t.ref)
    if (was && !t.is_control && t.state === 'needs-you' && was.state !== 'needs-you') out.push({ kind: 'tabAsks', ref: t.ref, title: t.name, at })
  }
  const stage = new Map((prev.returns ?? []).map(r => [r.key, r.stage]))
  for (const r of next.returns ?? []) {
    const was = stage.get(r.key)
    if (was && was !== r.stage && (r.stage === 'result' || r.stage === 'done')) out.push({ kind: 'answer', key: r.key, title: r.title, at })
    if (was && was !== r.stage && r.stage === 'lost') out.push({ kind: 'lost', key: r.key, title: r.title, at })
  }
  const alarms = new Set((prev.alarms ?? []).map(x => `${x.page_id}/${x.section_title}`))
  for (const x of next.alarms ?? []) {
    if (!alarms.has(`${x.page_id}/${x.section_title}`)) out.push({ kind: 'alarm', page: x.page_id, title: x.section_title, at })
  }
  return out
}

/** The feed with new events in front, at most `cap`; an event that repeats the newest of its kind and row
 *  is dropped */
export function addFeed(feed, events, cap = 50) {
  const out = [...feed]
  for (const e of events) {
    if (out.some(x => x.kind === e.kind && (x.key ?? x.ref ?? x.title) === (e.key ?? e.ref ?? e.title))) continue
    out.unshift(e)
  }
  return out.sort((x, y) => y.at - x.at).slice(0, cap)
}

// ---------------------------------------------------------------- the inner room: the knowledge graph in 3D

/** The regions of the net, in the order of their anchors (graph.py `group`) */
export const GRAPH_GROUPS = ['core', 'identity', 'infra', 'workflow', 'work', 'docs', 'other']

/** A small seeded random, so one tree always grows into the same net */
export function seeded(seed = 7) {
  let x = seed >>> 0 || 1
  return () => { x ^= x << 13; x >>>= 0; x ^= x >>> 17; x ^= x << 5; x >>>= 0; return x / 4294967296 }
}

/**
 * The net to lay out: each region gets an anchor on a sphere (the core in the middle), each node starts near its
 * region's anchor. pos and vel are flat [x, y, z, ...]; adj lists each node's neighbours both ways.
 */
export function seedGraph(nodes, edges, { radius = 260, seed = 7 } = {}) {
  const rnd = seeded(seed)
  const index = new Map(nodes.map((n, i) => [n.id, i]))
  const outer = GRAPH_GROUPS.filter(g => g !== 'core')
  const anchors = { core: [0, 0, 0] }
  outer.forEach((g, i) => {
    // a Fibonacci sphere: the regions spread evenly around the core
    const y = 1 - (i + 0.5) / outer.length * 2
    const r = Math.sqrt(1 - y * y)
    const a = i * Math.PI * (3 - Math.sqrt(5))
    anchors[g] = [Math.cos(a) * r * radius, y * radius, Math.sin(a) * r * radius]
  })
  const pos = new Float32Array(nodes.length * 3)
  nodes.forEach((n, i) => {
    const [ax, ay, az] = anchors[n.group] ?? anchors.other
    pos[i * 3] = ax + (rnd() - 0.5) * 120
    pos[i * 3 + 1] = ay + (rnd() - 0.5) * 120
    pos[i * 3 + 2] = az + (rnd() - 0.5) * 120
  })
  const adj = nodes.map(() => [])
  const links = []
  for (const e of edges) {
    const a = index.get(e.s), b = index.get(e.t)
    if (a === undefined || b === undefined || a === b) continue
    links.push([a, b])
    adj[a].push(b)
    adj[b].push(a)
  }
  return { nodes, index, anchors, pos, vel: new Float32Array(nodes.length * 3), adj, links }
}

/** One step of the forces: nodes push apart, links pull, each node is drawn a little to its region. The motion left */
export function stepGraph(g, { repel = 1800, spring = 0.02, length = 46, pull = 0.004, damp = 0.82 } = {}) {
  const { pos, vel, nodes, links, anchors } = g
  const n = nodes.length
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      const dx = pos[i * 3] - pos[j * 3], dy = pos[i * 3 + 1] - pos[j * 3 + 1], dz = pos[i * 3 + 2] - pos[j * 3 + 2]
      const d2 = dx * dx + dy * dy + dz * dz + 25
      if (d2 > 90000) continue
      const f = repel / (d2 * Math.sqrt(d2))
      vel[i * 3] += dx * f; vel[i * 3 + 1] += dy * f; vel[i * 3 + 2] += dz * f
      vel[j * 3] -= dx * f; vel[j * 3 + 1] -= dy * f; vel[j * 3 + 2] -= dz * f
    }
  }
  for (const [a, b] of links) {
    const dx = pos[b * 3] - pos[a * 3], dy = pos[b * 3 + 1] - pos[a * 3 + 1], dz = pos[b * 3 + 2] - pos[a * 3 + 2]
    const d = Math.sqrt(dx * dx + dy * dy + dz * dz) || 1
    const f = (d - length) * spring / d
    vel[a * 3] += dx * f; vel[a * 3 + 1] += dy * f; vel[a * 3 + 2] += dz * f
    vel[b * 3] -= dx * f; vel[b * 3 + 1] -= dy * f; vel[b * 3 + 2] -= dz * f
  }
  let moved = 0
  for (let i = 0; i < n; i++) {
    const [ax, ay, az] = anchors[nodes[i].group] ?? anchors.other
    for (let k = 0; k < 3; k++) {
      vel[i * 3 + k] = (vel[i * 3 + k] + ([ax, ay, az][k] - pos[i * 3 + k]) * pull) * damp
      pos[i * 3 + k] += vel[i * 3 + k]
      moved += Math.abs(vel[i * 3 + k])
    }
  }
  return n ? moved / n : 0
}

/** Where a point of the net stands on the screen: x, y, its depth, and how large things near it draw (0 behind) */
export function projectPoint(x, y, z, cam, w, h) {
  const px = x - cam.target[0], py = y - cam.target[1], pz = z - cam.target[2]
  const cy = Math.cos(cam.yaw), sy = Math.sin(cam.yaw), cp = Math.cos(cam.pitch), sp = Math.sin(cam.pitch)
  const x1 = px * cy - pz * sy
  const z1 = px * sy + pz * cy
  const y2 = py * cp - z1 * sp
  const z2 = py * sp + z1 * cp
  const depth = z2 + cam.dist
  if (depth < 8) return { x: 0, y: 0, depth, scale: 0 }
  const f = (Math.min(w, h) * 0.9) / Math.tan((cam.fov ?? 1) / 2) / 2
  const scale = f / depth
  return { x: w / 2 + x1 * scale, y: h / 2 + y2 * scale, depth, scale }
}

/** The next stop of a journey: a neighbour not yet visited, the best connected first; else a jump to an unseen node */
export function nextHop(g, cur, visited, rnd = Math.random) {
  const fresh = (g.adj[cur] ?? []).filter(j => !visited.has(j))
  if (fresh.length) {
    fresh.sort((a, b) => g.adj[b].length - g.adj[a].length)
    return fresh[Math.floor(rnd() * Math.min(3, fresh.length))]
  }
  const rest = g.nodes.map((_, i) => i).filter(i => !visited.has(i) && g.adj[i].length)
  if (rest.length) return rest[Math.floor(rnd() * rest.length)]
  const any = g.adj[cur] ?? []
  return any.length ? any[Math.floor(rnd() * any.length)] : cur
}

/** The nodes a search finds, best first: the id itself, then the start of a name, then anywhere in name, title or path */
export function graphFind(nodes, q, max = 8) {
  const s = String(q ?? '').trim().toLowerCase()
  if (!s) return []
  const rank = n => {
    const label = n.label.toLowerCase()
    if (label === s) return 0
    if (label.startsWith(s)) return 1
    if (label.includes(s)) return 2
    if ((n.title ?? '').toLowerCase().includes(s)) return 3
    if (n.id.toLowerCase().includes(s)) return 4
    return 9
  }
  return nodes.map((n, i) => ({ i, r: rank(n), d: n.degree ?? 0 })).filter(x => x.r < 9)
    .sort((a, b) => a.r - b.r || b.d - a.d).slice(0, max).map(x => x.i)
}

// ---------------------------------------------------------------- the picture of the day (Lagebild): data first, then a verdict

/**
 * The picture of the day as data, from what the page already holds: what to start with, who waits for you, what runs,
 * which starts answered or went quiet, the next date, the tightest quota, the findings, and what can wait.
 */
export function situation(model, tabs, nowMs) {
  const rows = id => (model?.sections ?? []).find(x => x.id === id)?.rows ?? []
  const live = (tabs ?? []).filter(t => !t.is_control && t.state !== 'shell')
  const returns = model?.returns ?? []
  let quota = null
  for (const p of model?.pages ?? []) {
    for (const sec of p.sections ?? []) {
      for (const it of sec.items ?? []) {
        const m = it.meter
        if (m?.unit !== '%' || !m.max) continue
        const pace = meterPace(m)
        const share = m.value / m.max
        const label = String(it.title ?? '').replace(/:\s*[\d.,]+\s*%\s*$/, '')
        const q = { label, value: m.value, max: m.max, perDay: pace?.perDay ?? null, over: !!pace?.over,
          bad: m.bad != null && m.value >= m.bad, warn: m.warn != null && m.value >= m.warn, it, page: p.id, section: sec.id }
        if (!quota || (q.over || q.bad) > (quota.over || quota.bad) || ((q.over || q.bad) === (quota.over || quota.bad) && share > quota.value / quota.max)) quota = q
      }
    }
  }
  return {
    first: focusPick(tabs, model),
    now: rows('now'),
    give: rows('give'),
    work: rows('work'),
    later: rows('later'),
    asking: live.filter(t => t.state === 'needs-you'),
    waiting: live.filter(t => t.state === 'waiting'),
    working: live.filter(t => t.state === 'working'),
    answers: returns.filter(r => r.stage === 'result'),
    lost: returns.filter(r => r.stage === 'lost'),
    next: nextEvent(model, nowMs),
    alarms: model?.alarms ?? [],
    quota,
  }
}

/** The picture as plain lines for Claude: only what is there, each list cut short, so the verdict rests on the page's data */
export function situationText(sit, nowMs, lang = 'de') {
  const names = (list, f, n = 4) => list.slice(0, n).map(f).join('; ') + (list.length > n ? tableOf(lang).situation.more(list.length - n) : '')
  const title = r => String(r.title ?? r.name ?? r.key ?? '').replace(/\s+/g, ' ').slice(0, 90)
  const row = r => `${r.priority ? `${r.priority} ` : ''}${title(r)}`
  const L = tableOf(lang).situation
  const out = []
  if (sit.now.length) out.push(`${L.now}: ${names(sit.now, row)}`)
  if (sit.asking.length) out.push(`${L.asking}: ${names(sit.asking, title)}`)
  if (sit.give.length) out.push(`${L.give}: ${names(sit.give, row)}`)
  if (sit.work.length) out.push(`${L.work}: ${names(sit.work, row, 5)}`)
  if (sit.working.length) out.push(`${L.working}: ${names(sit.working, title)}`)
  if (sit.answers.length) out.push(`${L.answers}: ${names(sit.answers, title)}`)
  if (sit.lost.length) out.push(`${L.lost}: ${names(sit.lost, title)}`)
  if (sit.next) out.push(`${L.next}: ${title(sit.next.it)} ${L.inT} ${untilText(sit.next.ms - nowMs)}`)
  if (sit.quota) out.push(`${L.quota}: ${sit.quota.label} ${Math.round(sit.quota.value)} %${sit.quota.perDay != null ? `, ${Math.round(sit.quota.perDay)} % ${L.per}` : ''}${sit.quota.over ? `, ${L.over}` : ''}`)
  if (sit.alarms.length) out.push(`${L.alarms}: ${names(sit.alarms, a => `${a.section_title} (${a.count})`)}`)
  if (sit.later.length) out.push(`${L.later}: ${sit.later.length}`)
  return out.join('\n')
}

const VERDICT_KEYS = { first: ['zuerst', 'first'], then: ['dann', 'then'], later: ['kann warten', 'can wait'] }

/** Claude's verdict in its three fixed lines (first, then, can wait), or null when the answer has another shape */
export function parseVerdict(text) {
  const out = {}
  for (const line of String(text ?? '').split('\n')) {
    const clean = line.replace(/^[\s*#>-]+/, '').replace(/\*\*/g, '').trim()
    for (const [k, words] of Object.entries(VERDICT_KEYS)) {
      const w = words.find(x => clean.toLowerCase().startsWith(`${x}:`))
      if (w && !out[k]) out[k] = clean.slice(w.length + 1).trim()
    }
  }
  return out.first && out.then && out.later ? out : null
}

const LIVE_RANK = { asks: 0, alarm: 1, answer: 2, working: 3, lost: 4, warn: 5 }

/**
 * What is alive in the net right now, by node: a task whose agent tab works or waits, a start handed to a tab that
 * answered or went quiet, a worker whose declared run has a finding. One state per node, the most pressing.
 */
export function graphLive(g, tabs, returns, runs) {
  const out = new Map()
  const put = (i, v) => {
    if (i === undefined) return
    const was = out.get(i)
    if (!was || LIVE_RANK[v.tone] < LIVE_RANK[was.tone]) out.set(i, v)
  }
  const task = slug => slug ? g.index.get(`work/tasks/${slug}/STATUS.md`) ?? g.index.get(`work/streams/${slug}/STATUS.md`) : undefined
  for (const t of tabs ?? []) {
    if (t.is_control || !t.slug) continue
    if (t.state === 'needs-you' || t.state === 'waiting') put(task(t.slug), { tone: 'asks', text: t.name, ref: t.ref })
    else if (t.state === 'working') put(task(t.slug), { tone: 'working', text: t.name, ref: t.ref })
  }
  for (const r of returns ?? []) {
    if (r.stage === 'result') put(task(r.item), { tone: 'answer', text: r.title, key: r.key })
    else if (r.stage === 'lost') put(task(r.item), { tone: 'lost', text: r.title, key: r.key })
  }
  for (const run of runs ?? []) {
    if (run.retired) continue
    const i = g.index.get(`workflow/workloads/${run.id}.yaml`)
    if (run.severity === 'high') put(i, { tone: 'alarm', text: run.title ?? run.id })
    else if (run.severity === 'medium') put(i, { tone: 'warn', text: run.title ?? run.id })
  }
  return out
}

/** The lane of a task row on a work page: review (waits for your yes), runs (waits on someone or something,
 *  task.py wait or a blocked_by), next (backlog), now (being worked on). In the order a page shows them */
export const TASK_LANES = ['now', 'runs', 'review', 'next']
export function taskLane(it) {
  if (it?.state === 'review') return 'review'
  if ((it?.lines ?? []).some(l => l.kind === 'blocked' || l.kind === 'look')) return 'runs'
  if (it?.state === 'backlog') return 'next'
  return 'now'
}

/** The theme a page address forces for this one load: `?theme=light` or `?theme=dark`, else null.
 *  The static demo on the website uses it; the choice is never saved. theme.js repeats this rule,
 *  because a classic script in <head> cannot import a module. */
export function themeOverride(search) {
  if (typeof search !== 'string') return null
  const mode = new URLSearchParams(search).get('theme')
  return mode === 'light' || mode === 'dark' ? mode : null
}

// ---------------------------------------------------------------- the model an agent tab starts with (launch)

/** The verbs that start an agent: only these carry a model and an effort, and only while launch is on */
export const START_VERBS = ['do_it', 'advise', 'start_agent', 'collect_context', 'team_role', 'session_resume', 'chat_tab', 'quick_handoff']
export const LAUNCH_MODELS = ['haiku', 'sonnet', 'opus']
export const LAUNCH_EFFORTS = ['low', 'medium', 'high', 'xhigh']

/** What the start picker offers under the server's switches (state.launch), or null while launch is off or
 *  the server does not know it yet. Auto comes first where it is on; without manual choice it stands alone,
 *  read only. 'standard' is no effort flag at all: the CLI's own default */
export function launchOptions(launch) {
  if (!launch?.enabled) return null
  const models = launch.models?.length ? launch.models : LAUNCH_MODELS
  const efforts = launch.efforts?.length ? launch.efforts : LAUNCH_EFFORTS
  return {
    models: [...(launch.auto ? ['auto'] : []), ...(launch.manual ? models : [])],
    efforts: launch.effort ? [...(launch.auto ? ['auto'] : []), 'standard', ...efforts] : [],
    readOnly: !launch.manual,
  }
}

/** The model and effort chosen now: the stored pick where the switches still offer it, else Auto while Auto
 *  is on, else the configured defaults */
export function launchChoice(launch, ui) {
  const opts = launchOptions(launch) ?? { models: [], efforts: [] }
  const model = !opts.readOnly && opts.models.includes(ui?.launchModel) ? ui.launchModel
    : launch?.auto ? 'auto' : launch?.default_model ?? 'sonnet'
  const effort = opts.efforts.includes(ui?.launchEffort) ? ui.launchEffort
    : launch?.auto ? 'auto' : launch?.default_effort ?? 'standard'
  return { model, effort }
}

/** The args a start sends: the very same object while launch is off or for any other verb, so nothing
 *  changes for a server without it. On, the choice goes along; Auto with a recommendation cached for the
 *  one row started sends its concrete model and effort, so the server need not route again. An effort
 *  goes along only while the effort switch is on, Standard as 'standard' */
export function withLaunch(verb, args, launch, ui, routes) {
  if (!launch?.enabled || !START_VERBS.includes(verb)) return args
  const { model, effort } = launchChoice(launch, ui)
  const keys = args?.keys ?? (args?.key ? [args.key] : [])
  const hit = keys.length === 1 ? routes?.[keys[0]] : null
  const rec = model === 'auto' && hit?.status === 'ok' ? hit.route : null
  const out = { ...args, model: rec ? rec.model : model }
  if (launch.effort) {
    const e = effort === 'auto' && rec ? rec.effort : effort
    if (e) out.effort = e   // 'standard' goes out as such: the server then passes no effort flag
  }
  return out
}

/** The rows whose recommendation is still to fetch: none yet, or one for an older title. A failed one stays
 *  quiet (no retry loop); the server takes at most 20 keys */
export function routesToFetch(items, cache) {
  return (items ?? []).filter(x => x?.key && (!cache?.[x.key] || cache[x.key].title !== x.title)).map(x => x.key).slice(0, 20)
}

/** "Auto: Sonnet · high (Jev, level 1.2)": a recommendation in the page language, null without one */
export function routeText(route, t, lang) {
  if (!route) return null
  const w = t.launch
  const level = route.level == null ? '' : Number(route.level).toLocaleString(lang === 'de' ? 'de-DE' : 'en-US', { maximumFractionDigits: 2 })
  const by = route.routed_by === 'jev' ? (level ? w.byJevLevel(level) : 'Jev') : route.routed_by === 'haiku' ? 'Haiku' : w.byDefault
  return `Auto: ${w.model[route.model] ?? route.model}${route.effort ? ` · ${w.effort[route.effort] ?? route.effort}` : ''} (${by})`
}

/** One setting as the partial the server saves: 'standard' is no effort (null), a name without its blanks */
export function launchPatch(key, value) {
  if (key === 'default_effort') return { [key]: value === 'standard' ? null : value }
  if (typeof value === 'string') return { [key]: value.trim() }
  return { [key]: value }
}

/** A Jev model name the server accepts: jev-1.14.0 or jev-2.0 */
export function jevModelValid(v) {
  return /^jev-\d+\.\d+(\.\d+)?$/.test(String(v ?? '').trim())
}

/** What is wrong with the Jev bands, or null: every bound 0 to 3 and rising, the last one open ("else") */
export function bandsProblem(bands) {
  const list = bands ?? []
  if (!list.length || list[list.length - 1].below != null) return 'last'
  const bounds = list.slice(0, -1).map(b => b.below)
  if (bounds.some(b => typeof b !== 'number' || !Number.isFinite(b) || b < 0 || b > 3)) return 'range'
  if (bounds.some((b, i) => i > 0 && b <= bounds[i - 1])) return 'order'
  return null
}
