// SPDX-License-Identifier: MIT
// The first-run tour: a welcome, then one step per area of the page with that area lit up, Next, Back and
// Skip, the way other tools introduce themselves. The steps are logic.js tourSteps, where the box stands is
// logic.js tourPlace; the controller opens the step's page and keeps on the server how the tour ended
// (tour_done), so a second browser does not offer it again. Help and Settings start it again.

import { html, useLayoutEffect, useRef, useState } from '../vendor/htm-preact-3.1.1.module.js'
import { tourIndex, tourPlace, tourSteps } from '../logic.js'
import { T } from '../text.js'
import { useFocusOnOpen } from './overlays.js'

const PAD = 6   // the light reaches this far past the area

/** The area a step lights, as the screen shows it now; null when the page has none (the box then stands in the middle) */
function rectOf(target) {
  if (!target || typeof document === 'undefined' || !document.querySelector) return null
  try {
    const el = document.querySelector(target)
    const r = el?.getBoundingClientRect?.()
    if (!r || (!r.width && !r.height)) return null
    return { top: r.top - PAD, left: r.left - PAD, width: r.width + PAD * 2, height: r.height + PAD * 2 }
  } catch {
    return null
  }
}

function viewOf() {
  return typeof window === 'undefined' ? { width: 1200, height: 800 }
    : { width: window.innerWidth || 1200, height: window.innerHeight || 800 }
}

export function Tour({ s, c }) {
  const at = s.ui?.tour
  if (!at) return null
  const t = T().tour
  const steps = tourSteps(s)
  const i = tourIndex(s)
  // one component for the whole tour, so the light moves from area to area instead of starting again
  return html`<${TourStep} step=${steps[i]} i=${i} n=${steps.length} t=${t} c=${c} page=${s.ui.page} />`
}

function TourStep({ step, i, n, t, c, page }) {
  const box = useRef(null)
  const ref = useFocusOnOpen(true)
  const [spot, setSpot] = useState(null)
  const [place, setPlace] = useState(null)
  // measure after the step's page has drawn, again on every resize and scroll
  useLayoutEffect(() => {
    let frame = 0
    const measure = () => {
      const rect = rectOf(step.target)
      const b = box.current?.getBoundingClientRect?.()
      setSpot(rect)
      setPlace(tourPlace(rect, { width: b?.width || 360, height: b?.height || 200 }, viewOf()))
    }
    const later = () => { if (typeof requestAnimationFrame === 'function') { cancelAnimationFrame(frame); frame = requestAnimationFrame(measure) } else measure() }
    measure()
    later()
    if (typeof window === 'undefined' || !window.addEventListener) return undefined
    window.addEventListener('resize', later)
    window.addEventListener('scroll', later, true)
    return () => {
      if (typeof cancelAnimationFrame === 'function') cancelAnimationFrame(frame)
      window.removeEventListener('resize', later)
      window.removeEventListener('scroll', later, true)
    }
  }, [step.id, page])
  const words = t.steps[step.id]
  const first = i === 0
  const last = i === n - 1
  const style = place && place.side !== 'center' ? { top: `${Math.round(place.top)}px`, left: `${Math.round(place.left)}px` } : undefined
  return html`<div class=${`tour${spot ? ' has-spot' : ''}`} ref=${ref}>
    ${spot ? html`<div class="tour-spot" aria-hidden="true" style=${{ top: `${spot.top}px`, left: `${spot.left}px`,
      width: `${spot.width}px`, height: `${spot.height}px` }}></div>` : html`<div class="tour-scrim" aria-hidden="true"></div>`}
    <div class=${`tour-box${!place || place.side === 'center' ? ' tour-center' : ''}`} data-side=${place?.side ?? 'center'} ref=${box} style=${style}
      role="dialog" aria-modal="true" aria-labelledby="tour-title" aria-describedby="tour-body">
      <p class="tour-count label-caps" aria-label=${t.label}>${first || last ? t.label : t.count(i, n - 2)}</p>
      <h2 class="tour-title" id="tour-title">${words.title}</h2>
      <p class="tour-body" id="tour-body">${words.body}</p>
      <div class="tour-dots" aria-hidden="true">${Array.from({ length: n }, (_, k) => html`<span key=${k} class=${`tour-dot${k === i ? ' is-on' : ''}`}></span>`)}</div>
      <div class="btn-row tour-acts">
        ${last ? null : html`<button type="button" class="btn btn-ghost btn-sm tour-skip" onClick=${() => c.tourEnd('skipped')}><span class="btn-label">${t.skip}</span></button>`}
        <span class="tour-gap"></span>
        ${first || last ? null : html`<button type="button" class="btn btn-secondary btn-sm" onClick=${() => c.tourGo(i - 1)}><span class="btn-label">${t.back}</span></button>`}
        ${last ? html`<button type="button" class="btn btn-primary btn-sm" data-autofocus onClick=${() => c.tourEnd('finished')}><span class="btn-label">${t.finish}</span></button>`
          : html`<button type="button" class="btn btn-primary btn-sm" data-autofocus onClick=${() => c.tourGo(i + 1)}><span class="btn-label">${first ? t.start : t.next}</span></button>`}
      </div>
    </div>
  </div>`
}
