// SPDX-License-Identifier: MIT
// The cockpit, Prio of Work through (views/flow.js, round 4): the third order of the left column beside Themes and
// Areas, offered while a work page asks for an order and Jev or Haiku can read in (logic.js prioOn). The newest order of
// the work page, by Jev or by Haiku, puts each point into a square: urgent and important (today), important and not
// urgent (plan it), urgent and not important (the Bridge can do it), neither (drop it); a point not rated (new since the
// read-in) stands under Not rated yet. "Only you" is never the square's word: a square says how many of its points the
// ranker gave to you alone (who: me). At the level of all squares the middle shows PrioSource (which ranker ordered how
// many points when, or that it reads in now, failed, has no order yet) and PrioGrid: the 2x2 grid with urgent left and
// important on top, each square a button with its name, its count, what it means, its first four titles (the reports by
// each of their rows, as the count counts them) and how many more, and what the ranker suggests there; a click enters the
// square, whose points then stand in the ranker's order (the walk goes the same way). PrioFoot stands at the foot of the
// left column's level one: ranker, time and count of the order, how many points the page's private words held back,
// that Haiku read in for a Jev that failed, and the two buttons Read in with Jev and Read in with Haiku, each there while
// its ranker can read in, both at all times (c.flowPrioRead: every point the view shows, logic.js prioRows).
// For the mouse: no text names a key.
// The rules every component keeps stand at the head of components.js.

import { html } from '../vendor/htm-preact-3.1.1.module.js'
import { formatDay, haikuReady, isoDate, jevQuadrants, jevReady, pointKeys, pointsIn, rankerName, short, workPageOf } from '../logic.js'
import { T, language } from '../text.js'
import { listRows } from './flowlist.js'
import { SideDot, sideName } from './flowside.js'
import { Btn } from './parts.js'

// the titles a square names before it says how many more it holds
const SQUARE_TITLES = 4

/** A row's title in a square (logic listRows): its row's, else its card's, else its tab's */
const titleOf = r => (r.row?.title ?? r.x?.title ?? r.x?.tab?.name) ?? ''

/** When Jev's order was made: its day in the page's words and the time */
export function orderTime(at, lang = language()) {
  const d = new Date(at)
  const two = n => String(n).padStart(2, '0')
  return `${formatDay(isoDate(at), lang)} ${two(d.getHours())}:${two(d.getMinutes())}`
}

/** Where the order stands, in one line: which ranker ordered how many points when, or that it reads in, failed, has
 *  none. `n` counts the points when the order names no count (an older server) */
export function PrioSource({ order, n }) {
  const f = T().flow.prio
  const lang = language()
  const o = order?.order
  if (order?.running) return html`<p class="flow-prio-from muted small" role="status">${f.running}</p>`
  if (order?.error && !o) return html`<p class="flow-prio-from muted small" role="status">${f.failed(rankerName(order.ranker))}</p>`
  if (!Number.isFinite(o?.at_ms)) return html`<p class="flow-prio-from muted small">${f.empty}</p>`
  return html`<p class="flow-prio-from muted small">${f.from(rankerName(o.ranker), orderTime(o.at_ms, lang), Number.isInteger(o.sent) ? o.sent : n)}</p>`
}

/** The foot of Prio's level one: ranker, time and count of the order (or that it reads in, failed, has none), what
 *  the private words held back, a fallback that ran, and Read in with Jev and Read in with Haiku (each while its ranker
 *  can read in, Haiku grey once its runs of the day are spent; both busy while one reads in) */
export function PrioFoot({ s, c }) {
  const f = T().flow.prio
  const page = workPageOf(s.model?.pages)
  if (!page) return null
  const order = s.jevOrder?.[page.id]
  const o = order?.order
  const at = o?.at_ms
  const line = order?.running ? f.running : order?.error && !o ? f.failed(rankerName(order.ranker))
    : Number.isFinite(at) ? f.foot(rankerName(o.ranker), orderTime(at), Number.isInteger(o.sent) ? o.sent : (o.items ?? []).length) : f.empty
  const held = order?.running ? 0 : o?.skipped?.private ?? 0
  const spent = !(s.prio?.haiku?.budget_left > 0)
  const busy = !!order?.running
  return html`<div class="flow-side-foot flow-side-body flow-prio-foot">
    <p class="muted small" role="status">${line}</p>
    ${held ? html`<p class="muted small">${f.held(held)}</p>` : null}
    ${!busy && o?.fallback ? html`<p class="muted small">${f.fellBack}</p>` : null}
    ${!busy && order?.error ? html`<p class="muted small" role="alert">${o ? `${f.failed(rankerName(order.ranker))}: ` : ''}${short(String(order.error), 160)}</p>` : null}
    <div class="flow-prio-reads">
      ${jevReady(s) ? html`<${Btn} size="xs" variant="secondary" icon="spark" busy=${busy && order?.ranker === 'jev'} disabled=${busy}
        onClick=${() => c.flowPrioRead(page.id, 'jev')}>${f.readJev}<//>` : null}
      ${haikuReady(s) ? html`<${Btn} size="xs" variant="secondary" icon="spark" busy=${busy && order?.ranker === 'haiku'} disabled=${busy || spent}
        title=${spent ? f.budget : undefined} onClick=${() => c.flowPrioRead(page.id, 'haiku')}>${f.readHaiku}<//>` : null}
    </div>
  </div>`
}

/** One square: a button with its name, count, meaning, how many of its points only you can do (the ranker's who),
 *  first titles and the suggestion of the square */
function Square({ side, points, s, c }) {
  const t = T()
  const f = t.flow.prio
  const q = side.quadrant
  const mine = pointsIn(points, side.id, s, 'prio')
  // every row the count counts: a reports card by each of its reports
  const rows = listRows(mine)
  const quads = jevQuadrants(s)
  const onlyMe = q ? mine.flatMap(x => (pointKeys(x).length ? pointKeys(x) : x.tab?.ref ? [`tab:${x.tab.ref}`] : [])).filter(k => quads.get(k)?.who === 'me').length : 0
  const shown = rows.slice(0, SQUARE_TITLES)
  const more = side.open - shown.length
  return html`<button type="button" class=${`flow-prio-sq tk-${side.tone ?? 'muted'}`} data-quadrant=${q ?? 'none'} onClick=${() => c.flowSide(side.id)}>
    <span class="flow-prio-head"><${SideDot} side=${side} /><span class="flow-prio-name">${sideName(side, 'prio')}</span>
      <span class="flow-prio-n mono">${side.open}</span></span>
    ${q ? html`<span class="flow-prio-sub muted small">${f.sub[q]}</span>` : null}
    ${onlyMe ? html`<span class="flow-prio-me small">${f.onlyYou(onlyMe)}</span>` : null}
    ${shown.length ? html`<ul class="flow-prio-titles">${shown.map(r => html`<li key=${r.id}>${short(titleOf(r), 70)}</li>`)}</ul>` : null}
    ${more > 0 ? html`<span class="muted small">${f.more(more)}</span>` : null}
    ${q ? html`<span class="flow-prio-hint small">${f.hints[q]}</span>` : null}
  </button>`
}

/** The 2x2 grid of Jev's squares: columns urgent and not urgent, rows important and not important; under it the
 *  points not rated yet, where there are any */
export function PrioGrid({ sides, points, s, c }) {
  const f = T().flow.prio
  const by = id => sides.find(x => x.id === id)
  const none = by('none')
  return html`<section class="flow-prio" aria-label=${f.title}>
    <div class="flow-prio-grid" role="group" aria-label=${f.title}>
      <span class="flow-prio-axis flow-prio-axis-x" aria-hidden="true"></span>
      <span class="flow-prio-axis muted small" aria-hidden="true">${f.axis.urgent}</span>
      <span class="flow-prio-axis muted small" aria-hidden="true">${f.axis.notUrgent}</span>
      <span class="flow-prio-axis flow-prio-axis-y muted small" aria-hidden="true">${f.axis.important}</span>
      <${Square} side=${by('q:now')} points=${points} s=${s} c=${c} />
      <${Square} side=${by('q:plan')} points=${points} s=${s} c=${c} />
      <span class="flow-prio-axis flow-prio-axis-y muted small" aria-hidden="true">${f.axis.notImportant}</span>
      <${Square} side=${by('q:hand')} points=${points} s=${s} c=${c} />
      <${Square} side=${by('q:drop')} points=${points} s=${s} c=${c} />
    </div>
    ${none ? html`<div class="flow-prio-none"><${Square} side=${none} points=${points} s=${s} c=${c} /></div>` : null}
  </section>`
}
