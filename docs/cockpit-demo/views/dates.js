// SPDX-License-Identifier: MIT
// The cockpit's dates as an agenda (`view: agenda` on a calendar section): two figures on top, the overlaps
// (a filter) and the longest free block left today, then the events as an agenda by day, a week grid or a month
// overview. The page shows time only: the next date stands on Start, due rows in Work, and the month is offered
// once the loaded dates span four weeks (a month kept in the browser shows the agenda till then). Everything
// here reads; an event's steps start an agent tab (row_action), a click opens the event's detail.
import { html, useEffect, useMemo, useState } from '../vendor/htm-preact-3.1.1.module.js'
import { T, language } from '../text.js'
import { Btn, Chip, Icon, MarkChip, StateLine } from './parts.js'
import { areaDates, rowActionKey } from '../logic.js'

const MODES = ['agenda', 'week', 'month']
const MODE_KEY = 'cockpit.dates.mode'
const HOUR_PX = 40
// the days the loaded dates must span, today included, before the month is offered: fewer leave most cells empty
const MONTH_DAYS = 28
const NARROW = '(max-width: 760px)'

const two = n => String(n).padStart(2, '0')
const dayKey = d => `${d.getFullYear()}-${two(d.getMonth() + 1)}-${two(d.getDate())}`
const parseDay = key => { const [y, m, d] = key.split('-').map(Number); return new Date(y, m - 1, d) }
const addDays = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n)
const mondayOf = d => addDays(d, -((d.getDay() + 6) % 7))
const minutesOf = iso => { const d = new Date(iso); return d.getHours() * 60 + d.getMinutes() }
const hhmm = iso => { const d = new Date(iso); return `${two(d.getHours())}:${two(d.getMinutes())}` }

function readMode() {
  try { const m = localStorage.getItem(MODE_KEY); return MODES.includes(m) ? m : 'agenda' } catch { return 'agenda' }
}
function keepMode(m) {
  try { localStorage.setItem(MODE_KEY, m) } catch { /* private window: the mode lasts for this page only */ }
}

function useNarrow() {
  const query = typeof window !== 'undefined' && window.matchMedia ? window.matchMedia(NARROW) : null
  const [narrow, setNarrow] = useState(!!query?.matches)
  useEffect(() => {
    if (!query) return undefined
    const on = e => setNarrow(e.matches)
    query.addEventListener?.('change', on)
    return () => query.removeEventListener?.('change', on)
  }, [])
  return narrow
}

/** How long, in words: "45 min", "1 h", "1 h 15" */
export function duration(minutes) {
  const t = T()
  if (!minutes) return ''
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return h ? (m ? t.cal.hm(h, m) : t.cal.h(h)) : t.cal.min(m)
}

function dayLabel(key, todayKey) {
  const t = T()
  const d = parseDay(key)
  const date = new Intl.DateTimeFormat(language(), { weekday: 'long', day: '2-digit', month: '2-digit' }).format(d)
  if (key === todayKey) return `${t.cal.today}, ${date}`
  if (key === dayKey(addDays(parseDay(todayKey), 1))) return `${t.cal.tomorrow}, ${date}`
  return date
}

/** A row passes the filters: a calendar, only events that count, a text, the overlaps figure */
function shows(it, f) {
  const cal = it.cal
  if (!cal) return true
  if (f.mine && cal.info) return false
  if (f.calendar && cal.calendar !== f.calendar) return false
  if (f.q) {
    const hay = `${it.title} ${cal.where ?? ''} ${(cal.people ?? []).join(' ')} ${cal.calendar ?? ''}`.toLowerCase()
    if (!hay.includes(f.q.toLowerCase())) return false
  }
  if (f.range === 'overlaps') return (cal.overlaps ?? []).length > 0
  return true
}

/** Two figures at most: the overlaps, a filter, and the longest free block left today. Today, tomorrow and the week
 *  stand as the agenda's day heads, the next date on Start, due rows in Work, where a row put off stays put off */
function Figures({ figures, filter, setFilter }) {
  const t = T()
  if (!figures) return null
  const on = filter.range === 'overlaps'
  return html`<ul class="calf" aria-label=${t.cal.figuresLabel}>
    <li><button type="button" class=${`calf-tile${on ? ' is-on' : ''}${figures.overlaps ? ' tk-warning is-loud' : ''}`}
      aria-pressed=${String(on)} onClick=${() => setFilter({ ...filter, range: on ? null : 'overlaps' })}>
      <span class="calf-n mono">${figures.overlaps}</span><span class="calf-label">${t.cal.fig.overlaps}</span></button></li>
    ${figures.free_today ? html`<li><div class="calf-tile is-static">
      <span class="calf-n mono">${duration(figures.free_today.minutes) || '0'}</span>
      <span class="calf-label">${t.cal.fig.free}</span>
      <span class="calf-sub muted">${t.cal.fig.freeFrom(hhmm(figures.free_today.from))}</span></div></li>` : null}
  </ul>`
}

function Filters({ items, filter, setFilter }) {
  const t = T()
  const cals = Object.entries(items.reduce((n, it) => (it.cal?.calendar ? { ...n, [it.cal.calendar]: (n[it.cal.calendar] ?? 0) + 1 } : n), {}))
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, 14)
  const hasInfo = items.some(it => it.cal?.info)
  return html`<div class="calbar">
    <input class="cal-search" type="search" value=${filter.q} placeholder=${t.cal.search} aria-label=${t.cal.search}
      onInput=${e => setFilter({ ...filter, q: e.currentTarget.value })} />
    ${hasInfo ? html`<button type="button" class=${`fchip${filter.mine ? ' is-on' : ''}`} aria-pressed=${String(filter.mine)}
      onClick=${() => setFilter({ ...filter, mine: !filter.mine })}>${t.cal.mineOnly}</button>` : null}
    ${cals.length > 1 ? cals.map(([name, n]) => {
      const on = filter.calendar === name
      return html`<button type="button" key=${name} class=${`fchip${on ? ' is-on' : ''}`} aria-pressed=${String(on)}
        onClick=${() => setFilter({ ...filter, calendar: on ? null : name })}>${name} <span class="mono muted">${n}</span></button>`
    }) : null}
    ${filter.range || filter.calendar || filter.q || filter.mine ? html`<${Btn} size="xs" variant="ghost" icon="close"
      onClick=${() => setFilter({ q: '', mine: false, calendar: null, range: null })}>${t.cal.clear}<//>` : null}
  </div>`
}

/** One day's busy blocks on a bar from the working day's start to its end; today with a now mark */
function DayBar({ events, figures, now, isToday }) {
  const ds = (figures?.day_start ?? 8) * 60
  const span = ((figures?.day_end ?? 20) * 60) - ds
  const pos = m => Math.min(100, Math.max(0, ((m - ds) / span) * 100))
  const timed = events.filter(it => it.cal?.start && !it.cal.all_day)
  const nowMin = new Date(now).getHours() * 60 + new Date(now).getMinutes()
  return html`<span class="cal-daybar" aria-hidden="true">
    ${timed.map(it => {
      const a = pos(minutesOf(it.cal.start))
      const b = pos(minutesOf(it.cal.start) + (it.cal.minutes || 15))
      return html`<span key=${it.index} class=${`cal-block${it.cal.info ? ' is-info' : ''}${(it.cal.overlaps ?? []).length ? ' tk-warning is-clash' : ''}`}
        style=${{ left: `${a}%`, width: `${Math.max(1.5, b - a)}%` }}></span>`
    })}
    ${isToday && nowMin >= ds && nowMin <= ds + span ? html`<span class="cal-now" style=${{ left: `${pos(nowMin)}%` }}></span>` : null}
  </span>`
}

function EventRow({ it, page, section, s, c }) {
  const t = T()
  const cal = it.cal
  const busy = !!s.ui.busy[rowActionKey({ page: page.id, section: section.id, index: it.index })]
  const open = () => c.openInfo(it, page.id, section.id)
  const cls = `cal-row card-opens${cal.info ? ' is-info' : ''}${cal.past ? ' is-past' : ''}${cal.running ? ' is-running' : ''}`
  return html`<li class=${cls} tabindex="0"
    onClick=${e => { if (!e.target.closest('button, a, input')) open() }}
    onKeyDown=${e => { if (e.key === 'Enter' && e.target === e.currentTarget) { e.preventDefault(); open() } }}>
    <span class="cal-time mono">${cal.all_day ? t.cal.allDay : hhmm(cal.start)}
      ${!cal.all_day && cal.minutes ? html`<span class="cal-dur muted">${duration(cal.minutes)}</span>` : null}</span>
    <span class="cal-main">
      <span class="cal-title">${it.title}
        ${cal.running ? html` <${Chip} token="success">${t.cal.running}<//>` : null}
        <${MarkChip} mark=${it.mark} /></span>
      <span class="cal-meta small">
        ${cal.calendar ? html`<span class="cal-cal">${cal.calendar}${cal.info ? ` · ${t.cal.infoCal}` : ''}</span>` : null}
        ${cal.where ? html`<span>${cal.where}</span>` : cal.online ? html`<span>${t.cal.online}</span>` : null}
        ${cal.people?.length ? html`<span title=${cal.people.join(', ')}>${t.cal.people(cal.people.length)}</span>` : null}
        ${(cal.overlaps ?? []).length ? html`<${StateLine} token="warning" word=${t.cal.overlapWith(cal.overlaps.join(', '))} />` : null}
      </span>
    </span>
    <span class="cal-acts btn-row">
      ${cal.online && it.link?.kind === 'web' && !cal.past ? html`<a class="btn btn-secondary btn-xs" href=${it.link.href} target="_blank" rel="noopener noreferrer">
        <${Icon} name="external" size=${14} /><span class="btn-label">${t.cal.join}</span></a>` : null}
      ${(it.actions ?? []).map(a => html`<${Btn} key=${a.id} size="xs" variant="primary" busy=${busy}
        onClick=${() => c.act('row_action', { page: page.id, section: section.id, index: it.index, action: a.id })}>${a.label}<//>`)}
    </span>
  </li>`
}

function Agenda({ days, todayKey, figures, now, page, section, s, c }) {
  const t = T()
  if (!days.length) return html`<p class="muted">${t.cal.none}</p>`
  return html`<div class="cal-agenda">${days.map(([key, events]) => {
    const counting = events.filter(it => !it.cal.info)
    const busy = counting.filter(it => !it.cal.all_day).reduce((n, it) => n + (it.cal.minutes || 0), 0)
    return html`<section key=${key} class=${`cal-day${key === todayKey ? ' is-today' : ''}`} id=${`calday-${section.id}-${key}`}>
      <header class="cal-dayhead">
        <h3 class="cal-dayname">${dayLabel(key, todayKey)}</h3>
        <span class="muted small">${t.cal.dayCount(counting.length, events.length - counting.length)}${busy ? ` · ${duration(busy)}` : ''}</span>
        <${DayBar} events=${events} figures=${figures} now=${now} isToday=${key === todayKey} />
      </header>
      <ul class="cal-rows">${events.map(it => html`<${EventRow} key=${it.index} it=${it} page=${page} section=${section} s=${s} c=${c} />`)}</ul>
    </section>`
  })}</div>`
}

/** Events of one day side by side where they overlap: each gets a column and the width of its cluster */
function lanes(events) {
  const timed = events.filter(it => !it.cal.all_day && it.cal.start)
    .map(it => ({ it, a: minutesOf(it.cal.start), b: minutesOf(it.cal.start) + Math.max(15, it.cal.minutes || 15) }))
    .sort((x, y) => x.a - y.a || y.b - x.b)
  const out = []
  let cluster = []
  let end = -1
  const flush = () => {
    const cols = []
    for (const e of cluster) {
      let k = cols.findIndex(last => last <= e.a)
      if (k < 0) { k = cols.length; cols.push(0) }
      cols[k] = e.b
      e.col = k
    }
    for (const e of cluster) out.push({ ...e, cols: cols.length })
    cluster = []
  }
  for (const e of timed) {
    if (cluster.length && e.a >= end) flush()
    cluster.push(e)
    end = Math.max(end, e.b)
  }
  if (cluster.length) flush()
  return out
}

function Week({ byDay, start, todayKey, figures, now, page, section, c }) {
  const t = T()
  const ds = figures?.day_start ?? 7
  const de = figures?.day_end ?? 21
  const from = Math.min(ds, 7)
  const to = Math.max(de, 21)
  const hours = Array.from({ length: to - from }, (_, i) => from + i)
  const days = Array.from({ length: 7 }, (_, i) => dayKey(addDays(start, i)))
  // a weekday's first two letters (Mo, Di): the long name cut, the same in every language this page speaks
  const wkd = new Intl.DateTimeFormat(language(), { weekday: 'long' })
  const dm = new Intl.DateTimeFormat(language(), { day: '2-digit', month: '2-digit' })
  const fmt = { format: d => `${wkd.format(d).slice(0, 2)} ${dm.format(d)}` }
  const nowD = new Date(now)
  const nowTop = ((nowD.getHours() * 60 + nowD.getMinutes()) - from * 60) / 60 * HOUR_PX
  const open = it => c.openInfo(it, page.id, section.id)
  return html`<div class="cal-week" role="grid" aria-label=${t.cal.views.week}>
    <div class="cal-wk-head"><span></span>${days.map(k => html`<span key=${k} class=${`cal-wk-day${k === todayKey ? ' is-today' : ''}`}>${fmt.format(parseDay(k))}</span>`)}</div>
    <div class="cal-wk-allday"><span class="muted small">${t.cal.allDay}</span>${days.map(k => html`<span key=${k} class="cal-wk-cell">
      ${(byDay.get(k) ?? []).filter(it => it.cal.all_day).map(it => html`<button type="button" key=${it.index}
        class=${`cal-wk-chip${it.cal.info ? ' is-info' : ''}`} onClick=${() => open(it)}>${it.title}</button>`)}</span>`)}</div>
    <div class="cal-wk-body" style=${{ height: `${hours.length * HOUR_PX}px` }}>
      <div class="cal-wk-hours">${hours.map(h => html`<span key=${h} class="mono muted small" style=${{ height: `${HOUR_PX}px` }}>${two(h)}</span>`)}</div>
      ${days.map(k => html`<div key=${k} class=${`cal-wk-col${k === todayKey ? ' is-today' : ''}`}>
        ${lanes(byDay.get(k) ?? []).map(e => {
          const top = Math.max(0, (e.a - from * 60) / 60 * HOUR_PX)
          const height = Math.max(18, Math.min((e.b - e.a) / 60 * HOUR_PX, hours.length * HOUR_PX - top))
          return html`<button type="button" key=${e.it.index}
            class=${`cal-ev${e.it.cal.info ? ' is-info' : ''}${e.it.cal.past ? ' is-past' : ''}${(e.it.cal.overlaps ?? []).length ? ' is-clash' : ''}`}
            style=${{ top: `${top}px`, height: `${height}px`, left: `${(e.col / e.cols) * 100}%`, width: `calc(${100 / e.cols}% - 2px)` }}
            title=${`${hhmm(e.it.cal.start)} ${e.it.title}`} onClick=${() => open(e.it)}>
            <span class="mono">${hhmm(e.it.cal.start)}</span> ${e.it.title}</button>`
        })}
        ${k === todayKey && nowTop >= 0 && nowTop <= hours.length * HOUR_PX ? html`<span class="cal-wk-now" style=${{ top: `${nowTop}px` }}></span>` : null}
      </div>`)}
    </div>
  </div>`
}

function Month({ byDay, anchor, todayKey, onDay }) {
  const t = T()
  const first = new Date(anchor.getFullYear(), anchor.getMonth(), 1)
  const start = mondayOf(first)
  const cells = Array.from({ length: 42 }, (_, i) => addDays(start, i))
  const weeks = cells.length / 7
  const used = Array.from({ length: weeks }, (_, w) => cells.slice(w * 7, w * 7 + 7))
    .filter((wk, i) => i < 4 || wk.some(d => d.getMonth() === anchor.getMonth()))
  const wd = { format: d => new Intl.DateTimeFormat(language(), { weekday: 'long' }).format(d).slice(0, 2) }
  return html`<div class="cal-month" role="grid" aria-label=${t.cal.views.month}>
    <div class="cal-mo-head">${used[0].map(d => html`<span key=${dayKey(d)} class="muted small">${wd.format(d)}</span>`)}</div>
    ${used.map((wk, i) => html`<div key=${i} class="cal-mo-week">${wk.map(d => {
      const k = dayKey(d)
      const events = byDay.get(k) ?? []
      const counting = events.filter(it => !it.cal.info)
      const cls = `cal-mo-day${k === todayKey ? ' is-today' : ''}${d.getMonth() !== anchor.getMonth() ? ' is-out' : ''}${events.length ? ' has-events' : ''}`
      return html`<button type="button" key=${k} class=${cls} disabled=${!events.length} onClick=${() => onDay(k)}
        aria-label=${`${k}: ${t.cal.dayCount(counting.length, events.length - counting.length)}`}>
        <span class="cal-mo-num mono">${d.getDate()}</span>
        ${events.length ? html`<span class="cal-mo-count mono">${counting.length || events.length}</span>` : null}
        ${events.slice(0, 3).map(it => html`<span key=${it.index} class=${`cal-mo-title${it.cal.info ? ' is-info' : ''}`}>${it.title}</span>`)}
        ${events.length > 3 ? html`<span class="muted small">${t.cal.moreN(events.length - 3)}</span>` : null}
      </button>`
    })}</div>`)}
  </div>`
}

/** The agenda view of a calendar section: figures, filters, and the events by day, as a week or a month */
export function DatesAgenda({ items: every, page, section, s, c }) {
  const t = T()
  const { items, none } = areaDates(s, every)
  const now = s.now || Date.now()
  const todayKey = dayKey(new Date(now))
  const [mode, setModeRaw] = useState(readMode)
  const [filter, setFilter] = useState({ q: '', mine: false, calendar: null, range: null })
  const narrow = useNarrow()
  const shown = useMemo(() => items.filter(it => it.cal && shows(it, filter)), [items, filter])
  const byDay = useMemo(() => {
    const m = new Map()
    // by day, a day's all-day events first, then by start
    const order = (a, b) => String(a.cal.day).localeCompare(String(b.cal.day))
      || (a.cal.all_day === b.cal.all_day ? 0 : a.cal.all_day ? -1 : 1) || String(a.cal.start).localeCompare(String(b.cal.start))
    for (const it of [...shown].sort(order)) {
      if (!m.has(it.cal.day)) m.set(it.cal.day, [])
      m.get(it.cal.day).push(it)
    }
    return m
  }, [shown])
  // the loaded window: prev and next never leave the days the section brought, and the month needs four weeks of it
  const loaded = items.map(it => it.cal?.day).filter(Boolean).sort()
  const firstDay = loaded[0] ?? todayKey
  const lastDay = loaded[loaded.length - 1] ?? todayKey
  const monthOn = Math.round((parseDay(lastDay) - parseDay(firstDay)) / 86400000) + 1 >= MONTH_DAYS
  const modes = monthOn ? MODES : MODES.filter(m => m !== 'month')
  // on a Saturday or Sunday the week to look at is the coming one: the section brings the days ahead
  const home = [0, 6].includes(parseDay(todayKey).getDay()) ? dayKey(mondayOf(addDays(parseDay(todayKey), 7))) : todayKey
  const [anchor, setAnchor] = useState(home)
  // a week on a narrow screen or a month that is not offered shows the agenda; the kept choice stays for later
  const view = (mode === 'week' && narrow) || (mode === 'month' && !monthOn) ? 'agenda' : mode
  const setMode = m => { setModeRaw(m); keepMode(m) }
  const weekStart = mondayOf(parseDay(anchor))
  // the month starts from today until the person moves it: the weekend's next Monday may lie in the next month
  const monthAnchor = anchor === home ? todayKey : anchor
  const canPrev = view === 'week' ? dayKey(addDays(weekStart, -1)) >= firstDay
    : view === 'month' ? dayKey(new Date(parseDay(monthAnchor).getFullYear(), parseDay(monthAnchor).getMonth(), 0)) >= firstDay : false
  const canNext = view === 'week' ? dayKey(addDays(weekStart, 7)) <= lastDay
    : view === 'month' ? dayKey(new Date(parseDay(monthAnchor).getFullYear(), parseDay(monthAnchor).getMonth() + 1, 1)) <= lastDay : false
  const step = dir => {
    const a = parseDay(view === 'month' ? monthAnchor : anchor)
    setAnchor(dayKey(view === 'week' ? addDays(a, 7 * dir) : new Date(a.getFullYear(), a.getMonth() + dir, 1)))
  }
  const onDay = k => {
    setAnchor(k)
    setMode(narrow ? 'agenda' : 'week')
    if (narrow) requestAnimationFrame(() => document.getElementById(`calday-${section.id}-${k}`)?.scrollIntoView({ block: 'start' }))
  }
  const rangeLabel = view === 'week'
    ? `${new Intl.DateTimeFormat(language(), { day: '2-digit', month: '2-digit' }).format(weekStart)} ${t.cal.to} ${new Intl.DateTimeFormat(language(), { day: '2-digit', month: '2-digit' }).format(addDays(weekStart, 6))}`
    : new Intl.DateTimeFormat(language(), { month: 'long', year: 'numeric' }).format(parseDay(monthAnchor))
  return html`<div class="cal">
    ${none ? html`<p class="muted small">${t.cal.noneOfArea(s.ui.area)}</p>` : null}
    <${Figures} figures=${section.cal_figures} filter=${filter} setFilter=${setFilter} />
    <div class="cal-tools">
      <div class="ghb-mode" role="group" aria-label=${t.cal.viewLabel}>${modes.map(m => html`<button type="button" key=${m}
        class=${`ghb-mode-btn${view === m ? ' is-on' : ''}`} aria-pressed=${String(view === m)} disabled=${m === 'week' && narrow}
        title=${m === 'week' && narrow ? t.cal.weekNarrow : undefined} onClick=${() => setMode(m)}>${t.cal.views[m]}</button>`)}</div>
      ${view !== 'agenda' ? html`<span class="cal-nav">
        <${Btn} size="xs" variant="ghost" disabled=${!canPrev} onClick=${() => step(-1)}>${t.cal.prev}<//>
        <span class="small">${rangeLabel}</span>
        <${Btn} size="xs" variant="ghost" disabled=${!canNext} onClick=${() => step(1)}>${t.cal.next}<//>
        ${anchor !== home ? html`<${Btn} size="xs" variant="ghost" onClick=${() => setAnchor(home)}>${t.cal.back}<//>` : null}
      </span>` : null}
    </div>
    <${Filters} items=${items} filter=${filter} setFilter=${setFilter} />
    ${view === 'week' ? html`<${Week} byDay=${byDay} start=${weekStart} todayKey=${todayKey} figures=${section.cal_figures} now=${now} page=${page} section=${section} c=${c} />`
      : view === 'month' ? html`<${Month} byDay=${byDay} anchor=${parseDay(monthAnchor)} todayKey=${todayKey} onDay=${onDay} />`
      : html`<${Agenda} days=${[...byDay.entries()]} todayKey=${todayKey} figures=${section.cal_figures} now=${now} page=${page} section=${section} s=${s} c=${c} />`}
  </div>`
}

/** An opened event's facts in the info drawer: when and how long, its calendar, where, the link, the people */
export function CalendarFacts({ it }) {
  const t = T()
  const cal = it.cal
  if (!cal) return null
  const when = cal.start ? new Intl.DateTimeFormat(language(), { weekday: 'long', day: '2-digit', month: 'long' }).format(new Date(cal.start)) : ''
  const time = cal.all_day ? t.cal.allDay : cal.start ? `${hhmm(cal.start)} ${t.cal.to} ${hhmm(cal.end)}` : ''
  return html`<section class="idrawer-sec cal-facts">
    <dl class="meta">
      <div class="meta-item"><dt>${t.cal.facts.when}</dt><dd>${when}<br /><span class="mono">${time}</span></dd></div>
      ${cal.minutes && !cal.all_day ? html`<div class="meta-item"><dt>${t.cal.facts.duration}</dt><dd>${duration(cal.minutes)}</dd></div>` : null}
      ${cal.calendar ? html`<div class="meta-item"><dt>${t.cal.facts.calendar}</dt><dd>${cal.calendar}${cal.info ? ` · ${t.cal.infoCal}` : ''}</dd></div>` : null}
      ${cal.where ? html`<div class="meta-item"><dt>${t.cal.facts.where}</dt><dd>${cal.where}</dd></div>` : null}
      ${cal.online ? html`<div class="meta-item"><dt>${t.cal.facts.link}</dt><dd>${t.cal.online}</dd></div>` : null}
    </dl>
    ${(cal.overlaps ?? []).length ? html`<p class="small"><${StateLine} token="warning" word=${t.cal.overlapWith(cal.overlaps.join(', '))} /></p>` : null}
    ${cal.people?.length ? html`<div><h3 class="label-caps">${t.cal.facts.people(cal.people.length)}</h3>
      <ul class="cal-people">${cal.people.map(p => html`<li key=${p}>${p}</li>`)}</ul></div>` : null}
  </section>`
}
