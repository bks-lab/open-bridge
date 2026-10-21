// SPDX-License-Identifier: MIT
// The explain overlay: one button lays notes over the page, each with a number, a ring around the area it
// means and an arrow to it, so a person sees what is what without leaving the page. Which areas a page has
// is logic.js hintsFor, where note, ring and arrow stand is logic.js hintLayout, and hintRounds splits them
// so every note has room: the page first, the header after it, Next and the arrow keys page on. An area
// the page does not show right now is left out. A click anywhere or Esc closes it; it changes nothing.

import { html, useEffect, useLayoutEffect, useRef, useState } from '../vendor/htm-preact-3.1.1.module.js'
import { hintRounds, hintsFor } from '../logic.js'
import { T } from '../text.js'
import { useFocusOnOpen } from './overlays.js'

const NOTE_WIDTH = 260
const LINE = 18          // a body line of a note, at the note's font
const CHARS = 31         // about this many characters fit on a line of it (German words run long)
const BAR_ROOM = 64      // the bar at the foot and its margin

/** A note's size before it is drawn: its width is fixed, its height follows the length of its words */
function noteSize(words) {
  return { width: NOTE_WIDTH, height: 46 + Math.ceil((words?.body ?? '').length / CHARS) * LINE }
}

function viewOf() {
  return typeof window === 'undefined' ? { width: 1200, height: 800 }
    : { width: window.innerWidth || 1200, height: window.innerHeight || 800 }
}

/** The first element of a target the screen shows, as a rect; null when there is none */
function rectOf(target) {
  if (typeof document === 'undefined' || !document.querySelectorAll) return null
  try {
    for (const el of document.querySelectorAll(target)) {
      const r = el.getBoundingClientRect?.()
      if (r && r.width > 0 && r.height > 0) return { top: r.top, left: r.left, width: r.width, height: r.height }
    }
  } catch { /* a selector the page does not know: nothing to point at */ }
  return null
}

export function HintsOverlay({ s, c }) {
  if (!s.ui?.hints) return null
  return html`<${HintsMeasured} s=${s} c=${c} />`
}

function HintsMeasured({ s, c }) {
  const words = T().hints.items
  const [layout, setLayout] = useState(null)
  const [at, setAt] = useState(0)
  const now = useRef(s)
  now.current = s
  useLayoutEffect(() => {
    const measure = () => {
      const items = hintsFor(now.current).map(h => ({ id: h.id, group: h.group, rect: rectOf(h.target), note: noteSize(words[h.id]) }))
      // the bar at the foot keeps its strip: no note is placed behind it
      const view = viewOf()
      setLayout({ ...hintRounds(items, { width: view.width, height: view.height - BAR_ROOM }), view })
    }
    measure()
    if (typeof window === 'undefined' || !window.addEventListener) return undefined
    window.addEventListener('resize', measure)
    window.addEventListener('scroll', measure, true)
    return () => {
      window.removeEventListener('resize', measure)
      window.removeEventListener('scroll', measure, true)
    }
  }, [s.ui.page, s.layout, s.model?.seq])   // new data can move or add an area: measure again
  // another page starts at its first round; new data or a resize keeps the round (HintsLayer clamps it)
  useLayoutEffect(() => setAt(0), [s.ui.page])
  return html`<${HintsLayer} layout=${layout} at=${at} go=${setAt} c=${c} />`
}

/** A gentle curve from the note to the ring: the middle pushed off to one side by a fifth of the length */
function curve({ x1, y1, x2, y2 }) {
  const mx = (x1 + x2) / 2
  const my = (y1 + y2) / 2
  const dx = x2 - x1
  const dy = y2 - y1
  const qx = mx - dy * 0.2
  const qy = my + dx * 0.2
  return `M${x1.toFixed(1)} ${y1.toFixed(1)} Q${qx.toFixed(1)} ${qy.toFixed(1)} ${x2.toFixed(1)} ${y2.toFixed(1)}`
}

/** The drawn overlay for a layout (hintRounds' rounds and the view they were placed in), its round `at`;
 *  `go(n)` shows another round */
export function HintsLayer({ layout, at = 0, go = () => {}, c }) {
  const t = T().hints
  const ref = useFocusOnOpen(true)
  const rounds = layout?.rounds ?? []
  const i = Math.max(0, Math.min(at, rounds.length - 1))
  const round = rounds[i]
  const placed = round?.placed ?? []
  const view = layout?.view ?? { width: 0, height: 0 }
  const below = (layout?.away ?? []).length
  const close = () => c.setHints(false)
  // the arrows page on wherever the focus stands; the round's main button takes the focus once it is drawn
  useEffect(() => {
    ref.current?.querySelector?.('[data-autofocus]')?.focus?.()
    if (typeof document === 'undefined' || !document.addEventListener) return undefined
    const onKey = e => {
      if (e.altKey || e.metaKey || e.ctrlKey) return
      if (e.key === 'ArrowRight' && i < rounds.length - 1) { e.preventDefault(); go(i + 1) }
      else if (e.key === 'ArrowLeft' && i > 0) { e.preventDefault(); go(i - 1) }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [i, rounds.length])
  const last = i >= rounds.length - 1
  return html`<div class="hints" ref=${ref} role="dialog" aria-modal="true" aria-label=${t.buttonTitle} onClick=${close}>
    <div class="hints-scrim" aria-hidden="true"></div>
    <svg class="hints-svg" width=${view.width} height=${view.height} viewBox=${`0 0 ${view.width} ${view.height}`} aria-hidden="true" focusable="false">
      <defs><marker id="hints-head" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
        <path class="hints-head" d="M0 0L10 5L0 10z" /></marker></defs>
      ${placed.map(p => p.shape === 'ellipse'
        ? html`<ellipse key=${`r${p.id}`} class="hints-ring" cx=${p.ring.left + p.ring.width / 2} cy=${p.ring.top + p.ring.height / 2}
            rx=${p.ring.width / 2 + 10} ry=${p.ring.height / 2 + 8} />`
        : html`<rect key=${`r${p.id}`} class="hints-ring" x=${p.ring.left} y=${p.ring.top} width=${p.ring.width} height=${p.ring.height} rx="12" />`)}
      ${placed.filter(p => p.arrow).map(p => html`<path key=${`a${p.id}`} class="hints-arrow" d=${curve(p.arrow)} marker-end="url(#hints-head)" />`)}
    </svg>
    ${placed.map(p => {
      const words = t.items[p.id]
      return html`<div key=${p.id} class="hints-note" data-hint=${p.id}
        style=${{ top: `${Math.round(p.note.top)}px`, left: `${Math.round(p.note.left)}px`, width: `${p.note.width}px` }}>
        <span class="hints-n mono" aria-hidden="true">${p.n}</span>
        <b class="hints-title">${words.title}</b>
        <p class="hints-body">${words.body}</p>
      </div>`
    })}
    <div class="hints-bar" role="status" onClick=${e => e.stopPropagation()}>
      ${round ? html`<span class="hints-where small"><b>${t.groups[round.group]}</b>${rounds.length > 1
        ? html` <span class="muted mono">${t.round(i + 1, rounds.length)}</span>` : null}</span>` : null}
      <span class="small muted hints-bar-text">${layout && !rounds.length ? t.none : below && round?.group === 'page' ? t.below(below) : rounds.length > 1 ? t.bar : t.barOne}</span>
      <button type="button" class="btn btn-ghost btn-xs" onClick=${() => c.tourStart()}><span class="btn-label">${t.tour}</span></button>
      ${i > 0 ? html`<button type="button" class="btn btn-secondary btn-xs" onClick=${() => go(i - 1)}><span class="btn-label">${t.back}</span></button>` : null}
      ${last ? html`<button type="button" class="btn btn-primary btn-xs" data-autofocus onClick=${close}><span class="btn-label">${t.close}</span></button>`
        : html`<button type="button" class="btn btn-secondary btn-xs" onClick=${close}><span class="btn-label">${t.close}</span></button>
          <button type="button" class="btn btn-primary btn-xs" data-autofocus onClick=${() => go(i + 1)}><span class="btn-label">${t.next}</span></button>`}
    </div>
  </div>`
}
