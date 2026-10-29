// SPDX-License-Identifier: MIT
// The cockpit, a page's log layout (profile `view: log` on a section, `place: rail` on others): the search bar on top,
// below it the main column with the log by hour and a narrow rail beside it with the rail sections as tiles and the
// log's topics as chips that filter it.
// The rules every component keeps stand at the head of components.js.

import { html, useState } from '../vendor/htm-preact-3.1.1.module.js'
import { formatDay, isoDate, logHours, logTopics, skipText, sparkOf, weekdayNames } from '../logic.js'
import { T, language } from '../text.js'
import { Marked, PageSearch } from './timeline.js'
import { Btn, Icon, StateLine } from './parts.js'

/** How many rows of a log stand at once; a button shows the next ones */
export const LOG_STEP = 100

/** A row's web page: its own web link, else its url where that is http(s) (a commits row names its repository so) */
const webOf = it => (it.link?.kind === 'web' ? it.link.href : /^https?:\/\//.test(it.url ?? '') ? it.url : null)

/** The log sections of a page's main column and the rows they hold, the rows loaded after the first ones among them */
function logRows(page, s) {
  return (page.sections ?? []).filter(sec => sec.view === 'log' && sec.place !== 'rail')
    .flatMap(sec => s.more?.[`${page.id}/${sec.id}`]?.items ?? sec.items ?? [])
}

/** The rows of a log (PageSection with `view: log`) under sticky hour heads: time, glyph, context and the text
 *  clamped to two lines, a click opens it in full; the typed words marked; the first LOG_STEP rows, then a button */
export function LogRows({ items, page, section, c, words = '' }) {
  const w = T().logPage
  // how many rows stand, counted for the words typed: new words start from the first rows again
  const [step, setStep] = useState({ words, shown: LOG_STEP })
  const shown = step.words === words ? step.shown : LOG_STEP
  const [open, setOpen] = useState(() => new Set())
  const marks = words ? words.split(/\s+/) : []
  const toggle = i => setOpen(o => { const n = new Set(o); if (n.has(i)) n.delete(i); else n.add(i); return n })
  const rest = items.length - shown
  return html`<div class="logv">
    ${logHours(items.slice(0, shown)).map((h, hi) => html`<section class="logv-hour" key=${`${h.key}-${hi}`}>
      <h3 class="logv-head mono">${h.key}</h3>
      <ul class="logv-rows">${h.rows.map(it => {
        const on = open.has(it.index)
        return html`<li key=${it.index} class=${`logv-row${on ? ' is-open' : ''}${it.tone === 'dim' ? ' is-dim' : ''}`}>
          <button type="button" class="logv-btn" aria-expanded=${String(on)} onClick=${() => toggle(it.index)}>
            <span class="logv-time mono">${it.when}</span>
            <span class="logv-glyph" aria-hidden="true">${it.glyph ?? '·'}</span>
            <span class="logv-text">${it.group ? html`<span class="logv-ctx"><${Marked} text=${it.group} words=${marks} /></span> ` : null}<${Marked} text=${it.title} words=${marks} /></span>
          </button>
          ${on ? html`<button type="button" class="btn-link small logv-open" onClick=${() => c.openInfo(it, page, section)}>${w.open}</button>` : null}
        </li>`
      })}</ul>
    </section>`)}
    ${rest > 0 ? html`<${Btn} size="xs" variant="ghost" icon="chevronDown" onClick=${() => setStep({ words, shown: shown + LOG_STEP })}>${w.more(Math.min(LOG_STEP, rest))}<//>` : null}
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

/** The log's contexts as chips with their counts; a chip filters the log to its topic, again clears it */
function TopicsPanel({ page, topics, topic, setTopic }) {
  const w = T().logPage
  if (!topics.length) return null
  const id = `logp-topics-${page.id}`
  return html`<section class="panel panel-pad logp-panel" aria-labelledby=${id}>
    <h2 class="sec-title" id=${id}>${w.topics} <span class="sec-count mono">${topics.length}</span></h2>
    <div class="logp-chips" role="group" aria-label=${w.topicsLabel}>
      ${topics.map(([name, n]) => html`<button type="button" key=${name} class=${`fchip${topic === name ? ' is-on' : ''}`}
        aria-pressed=${String(topic === name)} onClick=${() => setTopic(topic === name ? null : name)}>${name} <span class="mono muted">${n}</span></button>`)}
    </div>
  </section>`
}

/** The head of a page with the log layout: the day, the title, how many log lines in how many topics */
export function LogHead({ page, s }) {
  const w = T().logPage
  const lang = language()
  const now = new Date(s.now || Date.now())
  const day = `${weekdayNames(lang)[(now.getDay() + 6) % 7]} ${formatDay(isoDate(now.getTime()), lang, true)}`
  const logs = (page.sections ?? []).filter(sec => sec.view === 'log' && sec.place !== 'rail')
  const n = logs.reduce((sum, sec) => sum + (sec.total ?? sec.count ?? 0), 0)
  return html`<div class="logp-head">
    <span class="dz-eyebrow">${day}</span>
    <h2 class="detail-title">${page.title}</h2>
    ${logs.length ? html`<span class="muted small logp-sum">${w.summary(n, logTopics(logRows(page, s)).length)}</span>` : null}
  </div>`
}

/** A page with the log layout: the search bar (with `search: true`) over two columns, the main sections on the left
 *  (the log; in Every day the timeline in its place, in Ask AI the answer above it), the rail beside them (stacked
 *  above them on a narrow screen). `draw(sections, q, topic)` draws the main sections with the typed words and topic */
export function LogPage({ page, s, c, draw }) {
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
