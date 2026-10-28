// SPDX-License-Identifier: MIT
// The cockpit, small parts every view uses: icons, buttons, chips, the motion hooks.
// The rules every component keeps stand at the head of components.js.

import { html, useEffect, useRef, useState } from '../vendor/htm-preact-3.1.1.module.js'
import { markToken, prioToken, rovingIndex, short, verdictToken } from '../logic.js'
import { nowSec, reducedMotion, settled, springTo } from '../motion.js'
import { T } from '../text.js'

// ---------------------------------------------------------------- motion (motion.js, from the explainer films)

/** A number that follows its target with the film spring; a new target in mid move bends the path.
 *  `start` makes the first render run up from there. Under reduced motion the target stands at once */
export function useTween(target, { start, w = 9, zeta = 0.95 } = {}) {
  const o = { w, zeta }
  const st = useRef(null)
  const [, tick] = useState(0)
  const still = reducedMotion()
  if (st.current === null) {
    const from = start ?? target
    st.current = { from, to: target, moves: from !== target && !still ? [[nowSec(), target]] : [] }
    if (still) st.current.from = target
  }
  const m = st.current
  if (target !== m.to) {
    if (still) { m.from = target; m.moves = [] } else m.moves = [...m.moves, [nowSec(), target]]
    m.to = target
  }
  useEffect(() => {
    if (!m.moves.length) return undefined
    let id = requestAnimationFrame(function step() {
      if (settled(nowSec(), m.moves, o)) { m.from = m.to; m.moves = []; tick(n => n + 1); return }
      tick(n => n + 1)
      id = requestAnimationFrame(step)
    })
    return () => cancelAnimationFrame(id)
  }, [m.moves])
  return m.moves.length ? springTo(nowSec(), m.from, m.moves, o) : m.to
}

/** Seconds on the page clock, a new render every frame while `active`; reduced motion never ticks */
export function useClock(active) {
  const [T, setT] = useState(nowSec)
  useEffect(() => {
    if (!active || reducedMotion()) return undefined
    let id = requestAnimationFrame(function step() { setT(nowSec()); id = requestAnimationFrame(step) })
    return () => cancelAnimationFrame(id)
  }, [active])
  return T
}

/** A counter for each time `value` changes and `counts(before, value)` says it counts; keyed elements replay their hit once */
export function useHits(value, counts = () => true) {
  const last = useRef(value)
  const n = useRef(0)
  if (value !== last.current) {
    if (last.current !== undefined && counts(last.current, value)) n.current += 1
    last.current = value
  }
  return n.current
}

/** A number counting to its value in tabular figures, so nothing beside it moves */
export function CountNum({ value, start = 0, cls = '' }) {
  const v = useTween(Number(value) || 0, { start })
  return html`<span class=${`num ${cls}`}>${v.toFixed(0)}</span>`
}

// ---------------------------------------------------------------- keyboard (the ARIA roles keep their promise, #401)

const ROVING = { radiogroup: ['radio', 'aria-checked'], tablist: ['tab', 'aria-selected'] }
const MENU_ITEMS = ['menuitem', 'menuitemradio', 'menuitemcheckbox']

/** The elements under `root` with one of `roles`, in page order, the disabled ones left out */
function withRole(root, roles) {
  const out = []
  const walk = n => {
    for (const k of n.childNodes ?? []) {
      if (k.nodeType !== 1) continue
      if (roles.includes(k.getAttribute('role')) && !k.hasAttribute('disabled')) out.push(k)
      walk(k)
    }
  }
  if (root) walk(root)
  return out
}

/** The button that opens a popover: the first one in its box outside the menu */
function opener(root) {
  for (const k of root?.childNodes ?? []) {
    if (k.nodeType !== 1 || k.getAttribute('role') === 'menu') continue
    if (k.localName === 'button') return k
    const inner = opener(k)
    if (inner) return inner
  }
  return null
}

/** A radio group or a tab list as one tab stop: the chosen option takes the Tab key, the arrows, Home
 *  and End move the focus and the choice with it. A tab that opens a menu (More) only takes the focus.
 *  Put `ref` and `onKeyDown` on the element with role radiogroup or tablist; `given` reuses a ref it has */
export function useRoving(given) {
  const own = useRef(null)
  const ref = given ?? own
  useEffect(() => {
    const root = ref.current
    const [role, attr] = ROVING[root?.getAttribute('role')] ?? []
    if (!role) return
    const items = withRole(root, [role])
    const on = Math.max(0, items.findIndex(el => el.getAttribute(attr) === 'true'))
    items.forEach((el, i) => el.setAttribute('tabindex', i === on ? '0' : '-1'))
  })
  const onKeyDown = e => {
    if (e.altKey || e.ctrlKey || e.metaKey) return
    const root = ref.current
    const [role] = ROVING[root?.getAttribute('role')] ?? []
    const items = role ? withRole(root, [role]) : []
    const at = items.indexOf(e.target)
    const next = at < 0 ? -1 : rovingIndex(items.length, at, e.key)
    if (next < 0) return
    e.preventDefault()
    const el = items[next]
    el.focus()
    if (next !== at && !el.hasAttribute('aria-haspopup')) el.click()
  }
  return { ref, onKeyDown }
}

/** A small menu that closes on Escape or a click outside it; returns the ref for its box. On open the
 *  focus moves to its first item, the arrows, Home and End move it between the items. Closed by Escape
 *  or a pick, the focus goes back to the button that opened it; a click outside leaves it where it went */
export function usePopover(open, setOpen) {
  const box = useRef(null)
  useEffect(() => {
    const root = box.current
    if (!open || !root) return undefined
    const trigger = opener(root)
    let giveBack = true
    withRole(root, MENU_ITEMS)[0]?.focus()
    const away = e => { if (!root.contains(e.target)) { giveBack = false; setOpen(false) } }
    const keys = e => {
      if (e.key === 'Escape') { e.stopPropagation(); setOpen(false); return }
      const items = withRole(root, MENU_ITEMS)
      const at = items.indexOf(document.activeElement)
      if (at < 0 && document.activeElement !== trigger) return
      const next = rovingIndex(items.length, at, e.key)
      if (next < 0) return
      e.preventDefault()
      items[next].focus()
    }
    document.addEventListener('pointerdown', away)
    document.addEventListener('keydown', keys, true)
    return () => {
      document.removeEventListener('pointerdown', away)
      document.removeEventListener('keydown', keys, true)
      const now = document.activeElement
      const elsewhere = now && now !== document.body && document.contains(now) && !root.contains(now)
      if (giveBack && !elsewhere && trigger && document.contains(trigger)) trigger.focus()
    }
  }, [open])
  return box
}

// ---------------------------------------------------------------- small parts

const ICONS = {
  history: 'M3 12a9 9 0 1 0 2.6-6.4L3 8M3 3v5h5M12 7v5l3 2',
  reload: 'M20 11a8 8 0 1 0-2.34 5.66M20 4v7h-7',
  bulb: 'M9 18h6M10 21h4M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2.1h5c0-.9.4-1.6 1-2.1A6 6 0 0 0 12 3z',
  help: 'M9.1 9a3 3 0 0 1 5.8 1c0 2-3 2.5-3 4.5M12 18h.01M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z',
  sun: 'M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4',
  moon: 'M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z',
  auto: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 3v18',
  bell: 'M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9M10.3 21a1.94 1.94 0 0 0 3.4 0',
  close: 'M18 6 6 18M6 6l12 12',
  external: 'M15 3h6v6M10 14 21 3M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6',
  copy: 'M9 9h11v11H9zM5 15H4V4h11v1',
  chevronDown: 'M6 9l6 6 6-6',
  chevronUp: 'M6 15l6-6 6 6',
  home: 'M3 11l9-7 9 7M5 10v10h14V10M10 20v-6h4v6',
  sliders: 'M4 6h9M17 6h3M15 4v4M4 12h3M11 12h9M9 10v4M4 18h11M19 18h1M17 16v4',
  chevronRight: 'M9 6l6 6-6 6',
  back: 'M15 18l-6-6 6-6',
  forward: 'M9 18l6-6-6-6',
  tabs: 'M3 5h18v14H3zM15 5v14',
  send: 'M22 2 11 13M22 2l-7 20-4-9-9-4 20-7z',
  spark: 'M12 3v4M12 17v4M3 12h4M17 12h4',
  mic: 'M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3zM5 11a7 7 0 0 0 14 0M12 18v3',
  pause: 'M9 5v14M15 5v14',
  play: 'M7 5l12 7-12 7z',
  chat: 'M21 12a8 8 0 0 1-11.6 7.1L3 21l1.9-6.4A8 8 0 1 1 21 12z',
  subagent: 'M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM5 21a7 7 0 0 1 14 0',
  workflow: 'M6 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM18 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM6 9v3a6 6 0 0 0 6 6h3',
  sort: 'M4 6h16M7 12h10M10 18h4',
  pencil: 'M17 3a2.85 2.85 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5zM15 5l4 4',
  search: 'M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM20 20l-4-4',
}

export function Icon({ name, size = 16 }) {
  return html`<svg class="icon" width=${size} height=${size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
    stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
    <path d=${ICONS[name]} /></svg>`
}

/** Status dot; the written word always sits beside it (state never by color alone) */
export function Dot({ token, pulse }) {
  return html`<span class=${`dot tk-${token}${pulse ? ' dot-pulse' : ''}`} aria-hidden="true"></span>`
}

/** A button; `u` names it for the click log (logic.js usageControl) where its classes cannot */
export function Btn({ variant = 'secondary', size = 'sm', onClick, disabled, busy, title, pressed, children, label, icon, cls = '', u }) {
  return html`<button type="button" class=${`btn btn-${variant} btn-${size} ${cls}`} data-u=${u} onClick=${onClick}
    disabled=${disabled || busy} aria-busy=${busy ? 'true' : undefined} title=${title} aria-label=${label}
    aria-pressed=${pressed === undefined ? undefined : String(!!pressed)}>
    ${icon ? html`<${Icon} name=${icon} />` : null}${children ? html`<span class="btn-label">${children}</span>` : null}
  </button>`
}

/** "Seen" on a finding (a job, worker:<host>:<id>, or a page row): grey until it changes; on a seen one its
 *  "Show again". A button like the ones beside it (Analyse in a tab, Ask), never a bare word. Nothing where there
 *  is no finding to mark (`loud` false and not seen) */
export function SeenBtn({ k, acked, loud, c }) {
  const t = T().findingSeen
  if (!acked && !loud) return null
  return acked ? html`<${Btn} size="xs" variant="secondary" u="seen-undo" onClick=${() => c.ackFinding(k, false)}>${t.undo}<//>`
    : html`<${Btn} size="xs" variant="secondary" u="seen" title=${t.title} onClick=${() => c.ackFinding(k, true)}>${t.btn}<//>`
}

/** "Let AI do it" for a briefing section that cannot run on this machine: files the reason as a decision and
 *  starts an agent tab on it (verb chat_tab), the way the chat hands on a problem */
export function SkipFix({ s, c, title, reason }) {
  const t = T()
  return html`<${Btn} size="xs" variant="secondary" busy=${!!s?.ui?.busy?.chat_tab}
    onClick=${() => c.act('chat_tab', { text: t.skippedFixOrder(title, reason || '') })}>${t.action.do}<//>`
}

export function Chip({ token, children, title, cls = '' }) {
  return html`<span class=${`chip ${token ? `chip-tk tk-${token}` : ''} ${cls}`} title=${title}>
    ${token ? html`<${Dot} token=${token} />` : null}<span>${children}</span></span>`
}

export function StateLine({ token, word, strong }) {
  return html`<span class=${`state-line${strong ? ' is-strong' : ''}`}><${Dot} token=${token} /><span>${word}</span></span>`
}

export function MarkChip({ mark }) {
  if (!mark) return null
  return html`<${Chip} token=${markToken(mark.color)} cls="chip-mark">${mark.label}<//>`
}

export function PrioChip({ priority }) {
  if (!priority) return null
  return html`<span class=${`prio tk-${prioToken(priority)}`} title=${`${T().meta.priority} ${priority}`}>${priority}</span>`
}

/** The check's verdict on a task row; nothing for "continue" or a recommendation kept open */
export function VerdictChip({ review }) {
  if (!review || review.kept || review.verdict === 'continue') return null
  return html`<${Chip} token=${verdictToken(review.verdict)} title=${review.reason ?? undefined}>${T().verdictTag[review.verdict] ?? review.verdict}<//>`
}

export function Empty({ children }) {
  return html`<p class="empty">${children}</p>`
}

export function Spinner() {
  return html`<span class="spinner" aria-hidden="true"></span>`
}

export function LinkView({ link, c, onOpenTask }) {
  const t = T()
  if (!link) return null
  if (link.kind === 'web') {
    return html`<a class="link-out" href=${link.href} target="_blank" rel="noopener noreferrer">
      <span class="link-text">${short(link.href, 64)}</span><${Icon} name="external" size=${14} /></a>`
  }
  const m = /^work\/(?:tasks|streams)\/([a-z0-9][a-z0-9-]*)\/STATUS\.md$/.exec(link.path ?? '')
  return html`<span class="link-file">
    ${m && onOpenTask
      ? html`<button type="button" class="btn-link mono" onClick=${() => onOpenTask(m[1])}>${link.path}</button>`
      : html`<code>${link.path}</code>`}
    <${Btn} variant="ghost" size="xs" icon="copy" label=${t.copyPath} title=${t.copyPath} onClick=${() => c.copy(link.path)} />
  </span>`
}

// ---------------------------------------------------------------- the walk bar

/** The one bar every walk through a list ends in: under a detail opened from a list (detail.js NextUp),
 *  under an open tab (rooms.js TabWalk) and under the focus of the start page (focus.js). Back, where
 *  you stand, the next entry with Next (key n), the two after it as links; at the end `done` stands
 *  where Next was. Without `pos` back and the place are left out (a tab outside the walk). `next` and
 *  each of `later` are { key, title, sub?, look?, onOpen }; `goRef` holds the span around Next, for
 *  the walks that keep the focus on it */
export function WalkBar({ label, shortcuts = false, pos = null, onPrev = null, next = null, later = [], done, goRef = null }) {
  const t = T()
  const key = k => (shortcuts ? ` (${k})` : '')
  return html`<nav class="next-up" aria-label=${label}>
    <div class="next-up-bar">
      ${pos ? html`<${Btn} size="xs" variant="ghost" icon="back" label=${t.nextPrev} title=${t.nextPrev + key('p')} disabled=${!onPrev} onClick=${onPrev ?? undefined} />
        <span class="next-up-pos mono" aria-live="polite">${t.nextPos(pos[0], pos[1])}</span>` : null}
      ${next ? html`<span class="next-up-text" title=${next.look}><span class="label-caps">${t.nextUp}</span>
          <span class="next-up-title">${next.title}</span>${next.sub ? html`<span class="muted small">${next.sub}</span>` : null}</span>
        <span ref=${goRef} class="next-up-go"><${Btn} size="xs" variant="primary" icon="forward" title=${t.nextOpen + key('n')} onClick=${next.onOpen}>${t.nextOpen}<//></span>`
        : html`<span class="next-up-text muted small">${done}</span>`}
    </div>
    ${later.length ? html`<ol class="next-up-later" start=${(pos?.[0] ?? 0) + 2}>${later.map(e => html`<li key=${e.key}>
      <button type="button" class="btn-link" title=${e.look} onClick=${e.onOpen}>${e.title}</button>${e.sub ? html` <span class="muted small next-up-sub">${e.sub}</span>` : null}</li>`)}</ol>` : null}
  </nav>`
}
