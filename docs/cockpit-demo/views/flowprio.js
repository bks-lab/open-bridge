// SPDX-License-Identifier: MIT
// The cockpit, Prio of Work through (views/flow.js, round 4): the third order of the left column beside Themes and
// Areas, offered while Jev orders the work page (logic.js prioOn). Jev's daily order of the work page puts each point
// into a square: urgent and important (only you, today), important and not urgent (plan it), urgent and not important
// (the Bridge can do it), neither (drop it); a point Jev did not rate (a tab alone, an issue: Jev rates no refs) stands
// under Not rated yet. At the level of all squares the middle shows PrioSource (when Jev ordered how many points, or
// that it orders now, failed, has no order yet) and PrioGrid: the 2x2 grid with urgent left and important on top, each
// square a button with its name, its count, what it means, its first four titles and what Jev suggests there; a click
// enters the square, whose points then stand in Jev's order (the walk goes the same way).
// For the mouse: no text names a key.
// The rules every component keeps stand at the head of components.js.

import { html } from '../vendor/htm-preact-3.1.1.module.js'
import { formatDay, isoDate, pointsIn, short } from '../logic.js'
import { T, language } from '../text.js'
import { SideDot, sideName } from './flowside.js'

// the titles a square names before it says how many more it holds
const SQUARE_TITLES = 4

/** A point's title in a square: its row's, else its tab's */
const titleOf = x => (x.kind === 'reports' ? x.rows[0]?.title : x.row?.title ?? x.title ?? x.tab?.name) ?? ''

/** Where Jev's order stands, in one line: when it ordered how many points, or that it orders, failed, has none */
export function PrioSource({ order, n }) {
  const f = T().flow.prio
  const lang = language()
  if (order?.running) return html`<p class="flow-prio-from muted small" role="status">${f.running}</p>`
  if (order?.error && !order?.order) return html`<p class="flow-prio-from muted small" role="status">${f.failed}</p>`
  const at = order?.order?.at_ms
  if (!Number.isFinite(at)) return html`<p class="flow-prio-from muted small">${f.empty}</p>`
  const d = new Date(at)
  const two = n => String(n).padStart(2, '0')
  const time = `${formatDay(isoDate(at), lang)} ${two(d.getHours())}:${two(d.getMinutes())}`
  return html`<p class="flow-prio-from muted small">${f.from(time, n)}</p>`
}

/** One square: a button with its name, count, meaning, first titles and the suggestion of the square */
function Square({ side, points, s, c }) {
  const t = T()
  const f = t.flow.prio
  const q = side.quadrant
  const mine = pointsIn(points, side.id, s, 'prio')
  const more = mine.length - SQUARE_TITLES
  return html`<button type="button" class=${`flow-prio-sq tk-${side.tone ?? 'muted'}`} data-quadrant=${q ?? 'none'} onClick=${() => c.flowSide(side.id)}>
    <span class="flow-prio-head"><${SideDot} side=${side} /><span class="flow-prio-name">${sideName(side, 'prio')}</span>
      <span class="flow-prio-n mono">${side.open}</span></span>
    ${q ? html`<span class="flow-prio-sub muted small">${f.sub[q]}</span>` : null}
    ${mine.length ? html`<ul class="flow-prio-titles">${mine.slice(0, SQUARE_TITLES).map(x => html`<li key=${x.id}>${short(titleOf(x), 70)}</li>`)}</ul>` : null}
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
