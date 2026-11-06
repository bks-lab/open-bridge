// SPDX-License-Identifier: MIT
// The cockpit, the read marks of Work through in words (cockpit.flow.seen, logic.js readMark and rowMark; the server's
// seen.py): the count of an entry of the left column (the unread ones bold, every open one faint beside them, as a mail
// app counts its folders), why a point of the overview is unread, and the fields Read mark and Active of an open point.
// The views that show them: views/flowside.js (the left column and the fields), views/flowlist.js (the overview).
// For the mouse: no text names a key.
// The rules every component keeps stand at the head of components.js.

import { html } from '../vendor/htm-preact-3.1.1.module.js'
import { formatDay, isoDate } from '../logic.js'
import { T } from '../text.js'

/** The count of an entry: with the read marks on the unread ones bold and every open one faint beside them (a mail
 *  app's folder), else how many are open */
export function SideCount({ side }) {
  const f = T().flow
  if (side?.unread == null) return html`<span class="flow-side-open mono muted" title=${f.side.open(side?.open ?? 0)}>${side?.open ?? 0}</span>`
  return html`<span class="flow-side-counts" title=${f.marks.sideTitle(side.unread, side.open)}>
    ${side.unread ? html`<b class="flow-side-unread mono">${side.unread}</b>` : null}<span class="flow-side-open mono muted">${side.open}</span></span>`
}

/** The field Read mark in words (the read marks, logic.js rowMark): never opened, marked unread, read on a day and when
 *  it comes back, or that something new came since */
export function markWords(m, lang) {
  const f = T().flow.marks.mark
  const day = d => formatDay(d, lang)
  if (!m || m.why?.kind === 'never') return f.never
  if (m.why?.kind === 'forced') return f.forced
  if (!m.read) return f.never
  if (m.why?.kind === 'new') return `${f.read(day(m.read))}, ${f.news}`
  return m.back ? f.back(day(m.read), day(m.back)) : f.read(day(m.read))
}

/** The field Active of a doing task: kept in focus, pinned, an agent at work, active with the day it last moved, or
 *  resting for how many days */
export function activeWords(a, lang) {
  const f = T().flow.marks.act
  if (!a) return ''
  if (a.by) return f[a.by]
  if (!a.active) return f.resting(a.days)
  return Number.isFinite(a.last) ? f.moved(formatDay(isoDate(a.last), lang)) : f.unknown
}

/** Why a point is unread, in a few words (the read marks, logic.js readMark): never opened, marked unread, what came
 *  new and when, its revisit day, or how long a doing task rests; '' for one that asks for you now or is read */
export function unreadWhy(mark, lang) {
  const f = T().flow.marks
  const w = mark?.why
  if (!mark?.unread || !w || w.kind === 'live') return ''
  const day = d => formatDay(d, lang)
  return w.kind === 'never' ? f.why.never : w.kind === 'forced' ? f.why.forced : w.kind === 'new' ? f.why.new(f.what[w.what] ?? w.what, day(w.day))
    : w.kind === 'revisit' ? f.why.revisit(day(w.day)) : w.kind === 'resting' ? f.why.resting(w.days) : ''
}
