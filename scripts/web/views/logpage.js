// SPDX-License-Identifier: MIT
// The cockpit, a page's log layout (profile `view: log` on a section, `place: rail` on others): the search bar on top,
// below it the main column with the log by hour and a narrow rail beside it with the rail sections as tiles and the
// log's topics as chips that filter it. Where the log is the work log (`kind: activity`), a time range stands between
// the search and the columns (views/logrange.js): the log, its topics and the commits tiles follow it, by day over
// several days and by hour within one.
// The rules every component keeps stand at the head of components.js.

import { html, useEffect, useRef, useState } from '../vendor/htm-preact-3.1.1.module.js'
import { areaLog, shiftDays, dayStart, dayTime, filterRows, formatDay, isoDate, logDays, logHours, logTopics, rangeDay, rangeEdges, rangeOneDay,
  rangeStep, repoBusy, repoRange, skipText, sparkOf, weekdayNames } from '../logic.js'
import { T, language } from '../text.js'
import { Marked, PageSearch } from './timeline.js'
import { Btn, Icon, StateLine } from './parts.js'
import { RANGE_KINDS, RangePanel, eventTimes, rangeDays, rangeHeld, rangeSections, rangeView, useLogRange } from './logrange.js'

/** How many rows of a log stand at once; a button shows the next ones */
export const LOG_STEP = 100

/** A row's web page: its own web link, else its url where that is http(s) (a commits row names its repository so) */
const webOf = it => (it.link?.kind === 'web' ? it.link.href : /^https?:\/\//.test(it.url ?? '') ? it.url : null)

/** The log sections of a page's main column and the rows they hold, the rows loaded after the first ones among them */
function logRows(page, s) {
  return (page.sections ?? []).filter(sec => sec.view === 'log' && sec.place !== 'rail')
    .flatMap(sec => areaLog(s, s.more?.[`${page.id}/${sec.id}`]?.items ?? sec.items ?? []))
}

/** The rows of a log (PageSection with `view: log`) under sticky hour heads: time, glyph, context and the text
 *  clamped to two lines, a click opens it in full; the typed words marked; the first LOG_STEP rows, then a button.
 *  A row of a task (`task`) or about one, a stream or a closed one (`about_task`, its context) carries a file mark and,
 *  open, the way to its file. With `days` (a range over several days) the heads are the days, each with its count and,
 *  with `onDay`, a button that picks that day alone; `reset` starts from the first rows again when it changes */
export function LogRows({ items, page, section, c, words = '', days = false, onDay = null, reset = '', texts = null, need = null }) {
  const w = T().logPage
  const lang = language()
  // how many rows stand, counted for the words typed and the range: new words or a new range start from the first rows
  const key = `${words}|${reset}`
  const [step, setStep] = useState({ key, shown: LOG_STEP })
  const shown = step.key === key ? step.shown : LOG_STEP
  const [open, setOpen] = useState(() => new Set())
  const marks = words ? words.split(/\s+/) : []
  const toggle = i => setOpen(o => { const n = new Set(o); if (n.has(i)) n.delete(i); else n.add(i); return n })
  const rest = items.length - shown
  const perDay = new Map()
  if (days) for (const it of items) perDay.set(it.day, (perDay.get(it.day) ?? 0) + 1)
  const visible = items.slice(0, shown)
  const groups = days ? logDays(visible) : logHours(visible)
  // a row of the range comes without its text: the rows drawn ask for theirs (`need`), the text map holds what came
  const titleOf = it => it.title ?? texts?.[it.id] ?? null
  const missing = need ? visible.filter(it => it.id != null && titleOf(it) == null).map(it => it.id) : []
  useEffect(() => { if (missing.length) need(missing) }, [missing.join(',')])
  // the detail of a row of the range names its day with the time, and the work log as where it comes from
  const info = it => (it.id != null ? { ...it, title: titleOf(it) ?? '', when: `${rangeDay(dayTime(it.day, '12:00'), lang)}, ${it.when}`,
    origin: { ...(it.origin ?? {}), detail: w.origin } } : it)
  return html`<div class="logv">
    ${groups.map((h, hi) => html`<section class="logv-hour" key=${`${h.key}-${hi}`}>
      ${days ? html`<h3 class="logv-head logv-dayhead"><span class="logv-day">${rangeDay(dayTime(h.key, '12:00'), lang)}</span>
          <span class="logv-daycount muted small">${w.dayCount(perDay.get(h.key) ?? h.rows.length)}</span>
          ${onDay ? html`<button type="button" class="logv-onlyday" onClick=${() => onDay(h.key)}>${w.onlyDay}</button>` : null}</h3>`
        : html`<h3 class="logv-head mono">${h.key}</h3>`}
      <ul class="logv-rows">${h.rows.map(it => {
        const on = open.has(it.index)
        // the file of the task the row is, else of the one it is about (its context); a closed one by its folder
        const file = it.task ?? it.about_task ?? null
        return html`<li key=${it.index} class=${`logv-row${on ? ' is-open' : ''}${it.tone === 'dim' ? ' is-dim' : ''}`}>
          <button type="button" class="logv-btn" aria-expanded=${String(on)} onClick=${() => toggle(it.index)}>
            <span class="logv-time mono">${it.when}</span>
            <span class="logv-glyph" aria-hidden="true">${it.glyph ?? '·'}</span>
            <span class="logv-text">${file ? html`<span class="logv-file" title=${w.hasFile}><${Icon} name="file" size=${12} /><span class="sr-only">${w.hasFile}</span></span> ` : null}${it.group ? html`<span class="logv-ctx"><${Marked} text=${it.group} words=${marks} /></span> ` : null}${titleOf(it) == null ? html`<span class="logv-wait muted">${w.waiting}</span>` : html`<${Marked} text=${titleOf(it)} words=${marks} />`}</span>
          </button>
          ${on ? html`<span class="logv-acts">${file ? html`<${Btn} size="xs" variant="secondary" icon="file"
              onClick=${() => c.openFile(file, it.task ? null : it.about_path ?? null)}>${w.openFile}<//>` : null}
            <button type="button" class="btn-link small logv-open" onClick=${() => c.openInfo(info(it), page, section)}>${w.open}</button></span>` : null}
        </li>`
      })}</ul>
    </section>`)}
    ${rest > 0 ? html`<${Btn} size="xs" variant="ghost" icon="chevronDown" onClick=${() => setStep({ key, shown: shown + LOG_STEP })}>${w.more(Math.min(LOG_STEP, rest))}<//>` : null}
  </div>`
}

/** One row of a rail section as a tile: its name, its `when` with the leading number large (a commits row: "3 today"),
 *  the sparkline at the start of its detail as bars and the rest (the branch); the tile opens the row's web page */
function RailTile({ it, page, section, c }) {
  const href = webOf(it)
  const { bars, rest } = sparkOf(it.detail)
  const big = /^(\d+)\s+(.*)$/.exec(it.when ?? '')
  const inner = html`<span class="logp-name">${it.title}</span>
    ${it.when ? html`<span class="logp-big mono">${big ? html`${big[1]} <small>${big[2]}</small>` : it.when}</span>` : null}
    ${bars.length ? html`<span class="logp-spark" aria-hidden="true">${bars.map((b, i) => html`<i key=${i} style=${{ '--h': `${Math.round((b + 1) / 8 * 100)}%` }}></i>`)}</span>` : null}
    ${rest ? html`<span class="logp-branch">${rest}${href ? html` <${Icon} name="external" size=${11} />` : null}</span>` : null}`
  return href ? html`<a class="logp-tile" href=${href} target="_blank" rel="noopener noreferrer" title=${it.title}>${inner}</a>`
    : html`<button type="button" class="logp-tile" onClick=${() => c.openInfo(it, page, section)}>${inner}</button>`
}

/** A section with `place: rail`: a panel of tiles, two to a row, its quiet rows (dim: nothing today) in one line */
function RailSection({ page, section, c }) {
  const t = T(), w = t.logPage
  const rows = section.items ?? []
  const live = rows.filter(it => it.tone !== 'dim'), quiet = rows.filter(it => it.tone === 'dim')
  const id = `ps-${page.id}-${section.id}`
  return html`<section class="panel panel-pad logp-panel" aria-labelledby=${id}>
    <h2 class="sec-title" id=${id}>${section.title}
      ${section.status === 'ok' ? html` <span class="sec-count mono">${section.total ?? rows.length}</span>` : null}</h2>
    ${section.status === 'error' ? html`<${StateLine} token="danger" strong word=${t.unreadable(section.reason || '')} />`
      : section.status === 'skipped' ? html`<${StateLine} token="warning" word=${skipText(section, t)} />`
      : !rows.length ? html`<p class="muted small">${section.empty || t.empty}</p>`
      : html`${live.length ? html`<div class="logp-tiles">${live.map(it => html`<${RailTile} key=${it.index} it=${it} page=${page.id} section=${section.id} c=${c} />`)}</div>` : null}
        ${quiet.length ? html`<p class="muted small logp-quiet">${w.quiet} ${quiet.map((it, i) => {
          const href = webOf(it)
          return html`${i ? ', ' : ''}${href ? html`<a href=${href} target="_blank" rel="noopener noreferrer">${it.title}</a>` : it.title}`
        })}</p>` : null}`}
  </section>`
}

/** Most tiles the commits of a range stand in; the rest in one line */
const TILES_MAX = 6

/** The commits section of the rail over the range: own commits per repository in it, a sparkline over the range,
 *  at most TILES_MAX tiles and the rest in one line, and the repositories busy in the last seven days but quiet in it */
function RangeRepos({ page, section, repos, cur, now, slices }) {
  const w = T().logPage
  const rc = repoRange(repos, cur.from, cur.to, slices)
  const word = cur.preset === 'today' || cur.preset === 'yesterday' ? cur.preset : 'range'
  const on = new Set(rc.map(r => r.repo))
  const week = shiftDays(dayStart(now), -6)
  const quiet = repos.filter(r => !on.has(r.repo) && repoBusy(r, week, shiftDays(dayStart(now), 1)))
  const link = r => (/^https?:\/\//.test(r.url ?? '') ? html`<a href=${r.url} target="_blank" rel="noopener noreferrer">${r.repo}</a>` : r.repo)
  const id = `ps-${page.id}-${section.id}`
  return html`<section class="panel panel-pad logp-panel" aria-labelledby=${id}>
    <h2 class="sec-title" id=${id}>${w.repos} <span class="sec-count mono">${rc.length}</span></h2>
    ${rc.length ? html`<div class="logp-tiles">${rc.slice(0, TILES_MAX).map(r => {
      const top = Math.max(1, ...r.spark)
      const inner = html`<span class="logp-name">${r.repo}</span>
        <span class="logp-big mono">${r.n} <small>${w.unit[word]}</small></span>
        <span class="logp-spark" aria-hidden="true">${r.spark.map((n, i) => html`<i key=${i} class=${n ? '' : 'is-none'} style=${{ '--h': `${n ? Math.max(12, Math.round(n / top * 100)) : 6}%` }}></i>`)}</span>
        <span class="logp-branch">${r.branch}${r.url ? html` <${Icon} name="external" size=${11} />` : null}</span>`
      return r.url ? html`<a class="logp-tile" key=${r.repo} href=${r.url} target="_blank" rel="noopener noreferrer" title=${r.repo}>${inner}</a>`
        : html`<div class="logp-tile" key=${r.repo}>${inner}</div>`
    })}</div>` : html`<p class="muted small">${w.noCommits}</p>`}
    ${rc.length > TILES_MAX || quiet.length ? html`<p class="muted small logp-quiet">
      ${rc.length > TILES_MAX ? html`<span>${w.reposMore} ${rc.slice(TILES_MAX).map((r, i) => html`${i ? ', ' : ''}${link(r)} ${r.n}`)}</span>` : null}
      ${rc.length > TILES_MAX && quiet.length ? html`<br />` : null}
      ${quiet.length ? html`<span>${w.reposQuiet(word)} ${quiet.map((r, i) => html`${i ? ', ' : ''}${link(r)}`)}</span>` : null}</p>` : null}
  </section>`
}

/** The log's contexts as chips with their counts; a chip filters the log to its topic, again clears it */
function TopicsPanel({ page, topics, topic, setTopic, title = null }) {
  const w = T().logPage
  if (!topics.length) return null
  const id = `logp-topics-${page.id}`
  return html`<section class="panel panel-pad logp-panel" aria-labelledby=${id}>
    <h2 class="sec-title" id=${id}>${title ?? w.topics} <span class="sec-count mono">${topics.length}</span></h2>
    <div class="logp-chips" role="group" aria-label=${w.topicsLabel}>
      ${topics.map(([name, n]) => html`<button type="button" key=${name} class=${`fchip${topic === name ? ' is-on' : ''}`}
        aria-pressed=${String(topic === name)} onClick=${() => setTopic(topic === name ? null : name)}>${name} <span class="mono muted">${n}</span></button>`)}
    </div>
  </section>`
}

/** The head of a page with the log layout: the day, the title, how many log lines in how many topics (in the range,
 *  with the own commits in it, where the page has one) */
export function LogHead({ page, s }) {
  const w = T().logPage
  const lang = language()
  const now = new Date(s.now || Date.now())
  const day = `${weekdayNames(lang)[(now.getDay() + 6) % 7]} ${formatDay(isoDate(now.getTime()), lang, true)}`
  const logs = (page.sections ?? []).filter(sec => sec.view === 'log' && sec.place !== 'rail')
  const ranged = !!rangeSections(page).log
  const [state] = useLogRange(page.id)
  let sum = null
  if (ranged) {
    const v = rangeView(page, s, state)
    const rc = v.repos ? repoRange(v.repos, v.cur.from, v.cur.to) : null
    sum = rc ? w.summaryRange(v.rows.length, logTopics(v.rows).length, rc.reduce((n, r) => n + r.n, 0), rc.length)
      : w.summary(v.rows.length, logTopics(v.rows).length)
  } else if (logs.length) {
    sum = w.summary(logs.reduce((n, sec) => n + (sec.total ?? sec.count ?? 0), 0), logTopics(logRows(page, s)).length)
  }
  return html`<div class="logp-head">
    <span class="dz-eyebrow">${day}</span>
    <h2 class="detail-title">${page.title}</h2>
    ${sum ? html`<span class="muted small logp-sum">${sum}</span>` : null}
  </div>`
}

/** A page with the log layout: the search bar (with `search: true`) over two columns, the main sections on the left
 *  (the log; in Every day the timeline in its place, in Ask AI the answer above it), the rail beside them (stacked
 *  above them on a narrow screen). `draw(sections, q, topic)` draws the main sections with the typed words and topic.
 *  A page whose log is the work log takes the time range (RangedLogPage) */
export function LogPage({ page, s, c, draw }) {
  return rangeSections(page).log ? html`<${RangedLogPage} page=${page} s=${s} c=${c} draw=${draw} />`
    : html`<${PlainLogPage} page=${page} s=${s} c=${c} draw=${draw} />`
}

/** The log layout without a range: the log as the section drew it */
function PlainLogPage({ page, s, c, draw }) {
  const w = T().logPage
  const [topic, setTopic] = useState(null)
  const main = (page.sections ?? []).filter(sec => sec.place !== 'rail')
  const rail = (page.sections ?? []).filter(sec => sec.place === 'rail')
  const topics = logTopics(logRows(page, s))
  const on = topics.some(([name]) => name === topic) ? topic : null
  const grid = (q, parts = {}) => html`<div class="logp-grid">
    <div class="logp-main">${parts.answer ?? null}${parts.mode === 'all' && s.timeline ? parts.timeline : draw(main, q, on)}</div>
    <aside class="logp-rail" aria-label=${w.rail}>
      ${rail.map(sec => html`<${RailSection} key=${sec.id} page=${page} section=${sec} c=${c} />`)}
      <${TopicsPanel} page=${page} topics=${topics} topic=${on} setTopic=${setTopic} />
    </aside>
  </div>`
  return page.search ? html`<${PageSearch} page=${page} s=${s} c=${c} split render=${grid} />` : grid('')
}

/** The rows of a range that hold every typed word */
const holding = (rows, words) => (words ? words.split(/\s+/).reduce((list, x) => filterRows(list, { q: x }), rows) : rows)

/** The log page with the time range: the range is the page's (useLogRange, Today on every opening); the range's rows
 *  are loaded once a range needs days the page does not hold yet (c.loadLogRange), and again when the collector read
 *  the day anew; Every day loads the history beside the log (c.loadLogEvents) for its stacked chart */
function RangedLogPage({ page, s, c, draw }) {
  const [state, set] = useLogRange(page.id, true)
  const { log, commits } = rangeSections(page)
  const v = rangeView(page, s, state)
  const want = rangeDays(v.cur)
  const held = rangeHeld(s.logRange, want)
  // a range whose days are not loaded asks for them; a new pass of the collector asks again for the days held
  useEffect(() => { if (!held) c.loadLogRange({ ...want, commits: commits?.id ?? null }) }, [want.from, want.to, held])
  const seen = useRef(s.model?.collected_at ?? null)
  useEffect(() => {
    const at = s.model?.collected_at ?? null
    if (at !== seen.current && s.logRange?.status === 'ok') c.loadLogRange({ from: s.logRange.from, to: s.logRange.to, commits: commits?.id ?? null })
    seen.current = at
  }, [s.model?.collected_at])
  const body = (q, parts = {}) => html`<${RangeBody} page=${page} s=${s} c=${c} draw=${draw} v=${v} state=${state} set=${set}
    log=${log} commits=${commits} q=${q} parts=${parts} />`
  if (!page.search) return body('')
  const none = words => {
    if (!v.compact) return !holding(v.rows, words).length
    const h = s.logHits
    if (!h || h.q !== words || h.status !== 'ok' || h.rev !== s.logRange?.data?.rev) return false
    const ids = new Set(h.ids)
    return !v.rows.some(it => ids.has(it.id))
  }
  return html`<${PageSearch} page=${page} s=${s} c=${c} split render=${body} days=${want} none=${none} />`
}

/** The range panel and the two columns under it, for the words and the mode the search hands over */
function RangeBody({ page, s, c, draw, v, state, set, log, commits, q, parts }) {
  const t = T(), w = t.logPage, wr = t.logRange
  const [topic, setTopic] = useState(null)
  const mode = parts.mode ?? 'today'
  const typed = parts.words ?? ''
  // Every day reads every day: the range turns to All once, Back returns; its chart asks for the history beside the log
  const was = useRef(mode)
  useEffect(() => {
    if (mode === 'all' && was.current !== 'all' && v.cur.preset !== 'all') set(st => ({ ...st, back: [...st.back, st.range], range: { preset: 'all' } }))
    was.current = mode
  }, [mode])
  const asked = mode === 'all' ? (typed.length >= 2 ? typed : '') : null
  useEffect(() => {
    if (asked === null || (s.logEvents && s.logEvents.q === asked && s.logEvents.status !== 'error')) return undefined
    const wait = setTimeout(() => c.loadLogEvents(asked), asked ? 450 : 0)
    return () => clearTimeout(wait)
  }, [asked])
  const main = (page.sections ?? []).filter(sec => sec.place !== 'rail' && sec !== log)
  const rail = (page.sections ?? []).filter(sec => sec.place === 'rail' && sec !== commits)
  // rows of the range come without their text: the server finds the words (c.loadLogHits) and hands their ids back,
  // and sends the text of the rows the list draws (c.loadLogText); today's rows of the section filter here
  const rev = v.compact ? s.logRange?.data?.rev ?? null : null
  const hq = mode === 'all' ? (typed.length >= 2 ? typed : '') : q
  const hits = rev && hq && s.logHits?.q === hq && s.logHits.rev === rev && s.logHits.status === 'ok' ? new Set(s.logHits.ids) : null
  useEffect(() => {
    if (!rev || !hq || hits || (s.logHits?.q === hq && s.logHits.rev === rev && s.logHits.status === 'loading')) return undefined
    const wait = setTimeout(() => c.loadLogHits({ q: hq, rev, from: s.logRange.from, to: s.logRange.to }), 300)
    return () => clearTimeout(wait)
  }, [rev, hq, !!hits])
  const found = (rows, words) => (!words ? rows : !rev ? holding(rows, words) : hits ? rows.filter(it => hits.has(it.id)) : null)
  const texts = rev && s.logText?.rev === rev ? s.logText.texts : null
  const need = rev ? ids => c.loadLogText({ rev, ids }) : null
  const searching = found(v.rows, q) === null
  const byWords = found(v.rows, q) ?? v.rows
  const topics = logTopics(byWords)
  const on = topics.some(([name]) => name === topic) ? topic : null
  const shown = on ? byWords.filter(it => it.group === on) : byWords
  const filtering = !!q || !!on
  const oneDay = rangeOneDay(v.cur.from, v.cur.to)
  // what the bars count: the rows shown (the hits, while words or a topic filter), stacked with the history in Every day
  let series = [{ kind: 'did', items: filtering ? shown : v.rows }]
  if (mode === 'all') {
    const events = eventTimes(s.logEvents?.data?.events).filter(e => e.ts >= v.cur.from && e.ts < v.cur.to)
    series = RANGE_KINDS.map(([kind]) => ({ kind, items: kind === 'did' ? found(v.rows, hq) ?? v.rows : events.filter(e => e.kind === kind) }))
  }
  const count = searching ? wr.searching : filtering ? wr.hits(shown.length, v.rows.length) : wr.lines(v.rows.length)
  const keyText = filtering ? wr.keyHits(q, on) : wr.kinds.did
  const onDay = day => set(st => ({ ...st, back: [...st.back, st.range], range: { from: dayTime(day, '00:00'), to: shiftDays(dayTime(day, '00:00'), 1) } }))
  const title = v.cur.preset === 'today' ? log.title : w.inRange
  const reset = `${v.cur.from}-${v.cur.to}-${on ?? ''}`
  const logPanel = html`<section class="panel panel-pad psec" aria-labelledby=${`ps-${page.id}-${log.id}`}>
    <header class="psec-head"><h2 class="sec-title" id=${`ps-${page.id}-${log.id}`}>${title}
      <span class="sec-count mono">${shown.length}</span>${on ? html`<span class="muted"> · ${on}</span>` : null}</h2></header>
    ${s.logRange?.status === 'error' && !v.held ? html`<p class="muted small"><${StateLine} token="warning" word=${wr.error(s.logRange.error ?? '')} /></p>` : null}
    ${searching ? html`<p class="muted logr-empty">${wr.searching}</p>`
      : shown.length ? html`<${LogRows} items=${shown} page=${page.id} section=${log.id} c=${c} words=${q} days=${!oneDay} onDay=${onDay} reset=${reset}
        texts=${texts} need=${need} />`
      : html`<p class="muted logr-empty">${(q || on) && v.rows.length ? t.filterNone : v.cur.preset === 'today' && log.empty ? log.empty : wr.none}
        ${v.cur.preset !== 'all' ? html` <button type="button" class="btn-link" onClick=${() => set(st => ({ ...st, back: [...st.back, st.range], range: { preset: 'all' } }))}>${wr.preset.all}</button> ${wr.searchAll}` : null}</p>`}
  </section>`
  // the sparkline of a tile: as many parts as the chart has bars, fourteen at most
  const slices = Math.min(14, rangeEdges(v.cur.from, v.cur.to, rangeStep(v.cur.from, v.cur.to, state.step)).length - 1)
  return html`<${RangePanel} page=${page} cur=${v.cur} state=${state} set=${set} series=${series} count=${count} keyText=${keyText}
      stacked=${mode === 'all'} now=${v.now} />
    <div class="logp-grid">
      <div class="logp-main">${parts.answer ?? null}${mode === 'all' && s.timeline ? parts.timeline : logPanel}${draw(main, q, on)}</div>
      <aside class="logp-rail" aria-label=${w.rail}>
        ${commits ? (v.repos ? html`<${RangeRepos} page=${page} section=${commits} repos=${v.repos} cur=${v.cur} now=${v.now} slices=${slices} />`
          : html`<${RailSection} page=${page} section=${commits} c=${c} />`) : null}
        ${rail.map(sec => html`<${RailSection} key=${sec.id} page=${page} section=${sec} c=${c} />`)}
        <${TopicsPanel} page=${page} topics=${topics} topic=${on} setTopic=${setTopic} title=${w.topicsRange} />
      </aside>
    </div>`
}
