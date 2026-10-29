// SPDX-License-Identifier: MIT
// The cockpit, a page's search (profile `search: true`): one field over the page's own rows, every day before as a
// timeline (/api/timeline) and the question to the AI (verb timeline_ask) with the same words.
// The rules every component keeps stand at the head of components.js.

import { html, useState } from '../vendor/htm-preact-3.1.1.module.js'
import { formatDay, timelineDays } from '../logic.js'
import { T, language } from '../text.js'
import { Btn, Empty } from './parts.js'

/** One line of the history: its time, what kind it is, where it stands, the line, how many more its file holds, and for
 *  a closed task the way to open it; `why` the half sentence the AI gave for naming it */
function TimelineRow({ e, c, why = null }) {
  const w = T().pageSearch
  return html`<li class="tl-row">
    <span class="tl-time mono">${e.time ?? ''}</span>
    <span class=${`tl-kind tl-${e.kind}`}>${w.kind[e.kind] ?? e.kind}</span>
    <span class="tl-main"><span class="tl-src">${e.source}</span> <span class="tl-text">${e.text}</span>
      ${e.more ? html` <span class="muted small">${w.more(e.more)}</span>` : null}
      ${why ? html` <span class="muted small">${why}</span>` : null}</span>
    ${e.folder ? html`<button type="button" class="btn-link small" onClick=${() => c.openFile(e.folder.split('/').pop(), e.folder)}>${w.open}</button>` : null}
  </li>`
}

/** Lines of the history by day, newest first */
function TimelineDays({ entries, c, cited = false }) {
  const lang = language()
  return html`<ol class="tl-days">${timelineDays(entries).map(d => html`<li class="tl-day" key=${d.date}>
    <h4 class="label-caps tl-date">${formatDay(d.date, lang, true)}</h4>
    <ul class="tl-rows">${d.rows.map(e => html`<${TimelineRow} key=${`${e.path}:${e.line}`} e=${e} c=${c} why=${cited ? e.why : null} />`)}</ul>
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
      : html`<${TimelineDays} entries=${data.entries} c=${c} />
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
        ${(data?.entries ?? []).length ? html`<${TimelineDays} entries=${data.entries} c=${c} cited />` : null}`}
  </section>`
}

/** The search of a page with `search: true` (profile): one field over the page's own rows as one types; Search all days
 *  (or Enter) asks the history every day before (/api/timeline: the log and its archive, the meetings, the closed tasks,
 *  the raw transcripts), Ask AI (cockpit.files_search on) asks when it was done or discussed with the same words.
 *  `render(q)` draws the sections with the words typed, '' while fewer than two characters stand there */
export function PageSearch({ page, s, c, render }) {
  const w = T().pageSearch
  const [q, setQ] = useState('')
  const words = q.replace(/\s+/g, ' ').trim()
  const fs = s.work?.files_search ?? null
  const left = s.timelineAsk?.data?.left ?? fs?.left ?? null
  const spent = left === 0
  const all = () => { if (words.length >= 2) c.searchTimeline(words) }
  const ask = () => { if (words.length >= 2 && !spent) c.askTimeline(words) }
  const id = `psearch-${page.id}`
  return html`<div class="psearch">
    <form class="psearch-bar" role="search" aria-label=${w.label} onSubmit=${e => { e.preventDefault(); all() }}>
      <label class="sr-only" for=${id}>${w.label}</label>
      <input id=${id} class="input psearch-q" type="search" autocomplete="off" maxlength="200" placeholder=${w.placeholder}
        value=${q} onInput=${e => setQ(e.currentTarget.value)} />
      <${Btn} size="sm" variant="secondary" icon="search" disabled=${words.length < 2} busy=${s.timeline?.status === 'loading'}
        onClick=${all}>${w.allDays}<//>
      ${fs?.enabled ? html`<${Btn} size="sm" variant="ghost" icon="spark" disabled=${words.length < 2 || spent}
        busy=${s.timelineAsk?.status === 'loading'} onClick=${ask}>${w.ask}<//>` : null}
    </form>
    ${fs?.enabled ? html`<p class="psearch-note muted small">${[w.askNote, fs.block?.length ? w.private(fs.block) : null,
      spent ? w.noneLeft : left != null ? w.left(left) : null].filter(Boolean).join(' ')}</p>` : null}
    <${TimelineAnswer} ask=${s.timelineAsk} c=${c} />
    <${Timeline} find=${s.timeline} c=${c} />
  </div>
  ${render(words.length >= 2 ? words : '')}`
}
