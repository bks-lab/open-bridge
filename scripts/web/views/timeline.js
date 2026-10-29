// SPDX-License-Identifier: MIT
// The cockpit, a page's search (profile `search: true`): one field over the page's own rows, every day before as a
// timeline (/api/timeline) and the question to the AI (verb timeline_ask) with the same words.
// The rules every component keeps stand at the head of components.js.

import { html, useEffect, useRef, useState } from '../vendor/htm-preact-3.1.1.module.js'
import { filterRows, formatDay, timelineDays } from '../logic.js'
import { T, language } from '../text.js'
import { Btn, Empty, useRoving } from './parts.js'

/** One line of the history: its time, what kind it is, where it stands, the line, how many more its file holds, and for
 *  a closed task the way to open it; `why` the half sentence the AI gave for naming it */
/** A text with every word it holds marked, case folded, the words as plain text, never a pattern */
export function Marked({ text, words }) {
  const low = String(text ?? '').toLowerCase()
  const ws = (words ?? []).map(x => String(x).toLowerCase()).filter(x => x.length >= 2)
  const out = []
  let at = 0
  while (at < low.length) {
    let hit = null
    for (const x of ws) {
      const i = low.indexOf(x, at)
      if (i >= 0 && (!hit || i < hit[0] || (i === hit[0] && x.length > hit[1]))) hit = [i, x.length]
    }
    if (!hit) break
    if (hit[0] > at) out.push(text.slice(at, hit[0]))
    out.push(html`<mark key=${hit[0]}>${text.slice(hit[0], hit[0] + hit[1])}</mark>`)
    at = hit[0] + hit[1]
  }
  out.push(String(text ?? '').slice(at))
  return out
}

function TimelineRow({ e, c, why = null, words = [] }) {
  const w = T().pageSearch
  return html`<li class="tl-row">
    <span class="tl-time mono">${e.time ?? ''}</span>
    <span class=${`tl-kind tl-${e.kind}`}>${w.kind[e.kind] ?? e.kind}</span>
    <span class="tl-main"><span class="tl-src">${e.source}</span> <span class="tl-text"><${Marked} text=${e.text} words=${words} /></span>
      ${e.more ? html` <span class="muted small">${w.more(e.more)}</span>` : null}
      ${why ? html` <span class="muted small">${why}</span>` : null}</span>
    ${e.folder ? html`<button type="button" class="btn-link small" onClick=${() => c.openFile(e.folder.split('/').pop(), e.folder)}>${w.open}</button>` : null}
  </li>`
}

/** Lines of the history by day, newest first */
function TimelineDays({ entries, c, cited = false, words = [] }) {
  const lang = language()
  return html`<ol class="tl-days">${timelineDays(entries).map(d => html`<li class="tl-day" key=${d.date}>
    <h4 class="label-caps tl-date">${formatDay(d.date, lang, true)}</h4>
    <ul class="tl-rows">${d.rows.map(e => html`<${TimelineRow} key=${`${e.path}:${e.line}`} e=${e} c=${c} why=${cited ? e.why : null} words=${words} />`)}</ul>
  </li>`)}</ol>`
}

/** Every day before (s.timeline from c.searchTimeline): the lines that hold every word, by day */
function Timeline({ find, c }) {
  const w = T().pageSearch
  if (!find) return null
  const data = find.data
  return html`<section class="tl" aria-live="polite">
    <header class="tl-head"><p class="dz-eyebrow">${w.timelineTitle(find.q)}${data ? html` <span class="sec-count mono">${data.total}</span>` : null}</p>
      <${Btn} variant="ghost" size="xs" icon="close" onClick=${() => c.clearTimeline()}>${w.close}<//></header>
    ${find.status === 'loading' ? html`<p class="muted small" role="status">${w.searching}</p>`
      : find.status === 'error' ? html`<p class="muted small" role="status">${find.error}</p>`
      : !data.entries.length ? html`<${Empty}>${w.nothing}<//>`
      : html`<${TimelineDays} entries=${data.entries} c=${c} words=${data.words ?? find.q.split(' ')} />
        ${data.truncated ? html`<p class="muted small">${w.truncated(data.entries.length, data.total)}</p>` : null}`}
  </section>`
}

/** The AI's answer to the history (s.timelineAsk from c.askTimeline): its text, what it read, the lines it names */
function TimelineAnswer({ ask, c }) {
  const w = T().pageSearch
  if (!ask) return null
  const data = ask.data ?? null
  return html`<section class="tl tl-answer" aria-live="polite">
    <header class="tl-head"><p class="dz-eyebrow">${w.answer}${data ? html` <span class="muted">${w.answerFrom(data.sent, data.model)}</span>` : null}</p>
      <${Btn} variant="ghost" size="xs" icon="close" onClick=${() => c.clearTimelineAsk()}>${w.close}<//></header>
    ${ask.status === 'loading' ? html`<p class="muted small" role="status">${w.asking}</p>`
      : ask.status === 'error' ? html`<p class="muted small" role="status">${ask.error}</p>`
      : html`<p class="tl-answer-text">${data?.answer ?? w.noAnswer}</p>
        ${(data?.entries ?? []).length ? html`<${TimelineDays} entries=${data.entries} c=${c} words=${data.terms ?? []} cited />` : null}`}
  </section>`
}

/** Whether a word list leaves a row on the page: every word in one of its sections' rows, the rows loaded after the
 *  first ones (s.more) among them */
function pageHolds(page, s, words) {
  const all = (page.sections ?? []).flatMap(sec => s.more?.[`${page.id}/${sec.id}`]?.items ?? sec.items ?? [])
  return words.split(/\s+/).reduce((rows, x) => filterRows(rows, { q: x }), all).length > 0
}

/** The sections of a page that hold more rows than it drew and have not loaded them yet */
function sectionsShort(page, s) {
  return (page.sections ?? []).filter(sec => (sec.more ?? 0) > 0 && !s.more?.[`${page.id}/${sec.id}`])
}

/** The search of a page with `search: true` (profile): one field and three modes beside it. Today filters the page's
 *  own rows as one types; Every day (Enter, or the switch to it) lists the history's lines by day (/api/timeline: the
 *  log and its archive, the meetings, the closed tasks, the raw transcripts); Ask AI (only with cockpit.files_search
 *  on, Enter or its button) asks when it was done or discussed. Switching keeps the text; only Today filters the rows.
 *  `render(q)` draws the sections with the words typed, '' when nothing filters */
export function PageSearch({ page, s, c, render }) {
  const w = T().pageSearch
  const [q, setQ] = useState('')
  const [mode, setMode] = useState('today')
  const keys = useRoving()
  const words = q.replace(/\s+/g, ' ').trim()
  const fs = s.work?.files_search ?? null
  const left = s.timelineAsk?.data?.left ?? fs?.left ?? null
  const spent = left === 0
  const modes = ['today', 'all', ...(fs?.enabled ? ['ai'] : [])]
  const now = modes.includes(mode) ? mode : 'today'
  const sent = useRef('')
  const go = (m = now) => {
    if (words.length < 2) return
    if (m === 'all') { sent.current = words; c.searchTimeline(words) }
    if (m === 'ai' && !spent) c.askTimeline(words)
  }
  const pick = m => { setMode(m); if (m === 'all') go('all') }
  const id = `psearch-${page.id}`
  const filtering = now === 'today' && words.length >= 2
  // Today searches every row of the page, not only the first ones drawn: a section that holds more loads the rest once
  const short = filtering ? sectionsShort(page, s) : []
  useEffect(() => { for (const sec of short) c.loadMore(page.id, sec.id) }, [short.map(sec => sec.id).join(' ')])
  // Every day searches as one types, once the typing pauses; Enter still searches at once
  useEffect(() => {
    if (now !== 'all' || words.length < 2 || words === sent.current) return
    const wait = setTimeout(() => go('all'), 450)
    return () => clearTimeout(wait)
  }, [now, words])
  return html`<div class="psearch">
    <form class="psearch-bar" role="search" aria-label=${w.label} onSubmit=${e => { e.preventDefault(); go() }}>
      <label class="sr-only" for=${id}>${w.label}</label>
      <input id=${id} class="input psearch-q" type="search" autocomplete="off" maxlength="200" placeholder=${w.placeholder[now]}
        value=${q} onInput=${e => setQ(e.currentTarget.value)} />
      <div class="psearch-seg" role="radiogroup" aria-label=${w.modeLabel} ref=${keys.ref} onKeyDown=${keys.onKeyDown}>
        ${modes.map(m => html`<button type="button" key=${m} role="radio" aria-checked=${String(now === m)}
          class=${now === m ? 'is-on' : ''} onClick=${() => pick(m)}>${w.mode[m]}</button>`)}
      </div>
      ${now === 'ai' ? html`<${Btn} size="sm" variant="secondary" icon="spark" disabled=${words.length < 2 || spent}
        busy=${s.timelineAsk?.status === 'loading'} onClick=${() => go('ai')}>${w.send}<//>` : null}
      ${fs?.enabled ? html`<span class="psearch-left muted small">${spent ? w.noneLeft : left != null ? w.left(left) : ''}</span>` : null}
    </form>
    ${now === 'ai' && fs?.block?.length ? html`<p class="psearch-note muted small">${w.private(fs.block)}</p>` : null}
    ${filtering && !short.length && !pageHolds(page, s, words) ? html`<p class="psearch-none muted small">${w.todayNone}
      <button type="button" class="btn-link small" onClick=${() => pick('all')}>${w.mode.all}</button></p>` : null}
    ${now === 'ai' ? html`<${TimelineAnswer} ask=${s.timelineAsk} c=${c} />` : null}
    ${now === 'all' ? html`<${Timeline} find=${s.timeline} c=${c} />` : null}
  </div>
  ${render(filtering ? words : '')}`
}
