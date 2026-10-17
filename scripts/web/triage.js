// SPDX-License-Identifier: MIT
// Triage on the task and inbox pages: one glance per row says what it is about (gist), whether it can
// go (closable), and who does it (the AI, with its effort as dots, or you, with why). On top of the
// page a strip filters by that, counts each choice, closes everything closable in two clicks and sorts
// again on a click (scripts/triage.py, cached per item, so a run costs cents). The dashboard's own
// pieces stay in views/; this file only draws what the triage adds, from s.triage.

import { html, useEffect, useRef, useState } from './vendor/htm-preact-3.1.1.module.js'
import { TRIAGE_FILTERS, actionRow, centsText, checkPick, checkPickText, effortDots, triageCounts, triageKey } from './logic.js'
import { T, language } from './text.js'

const TONE = { close: 'success', ai: 'info', you: 'warning', either: 'on-surface-muted', unclear: 'on-surface-muted' }

/** What a row is about, in one line, and the three marks: can go, the AI can do it, it needs you */
export function TriageGist({ tri, keyRow, c, s }) {
  const t = T()
  if (!tri) return null
  const dots = effortDots(tri.effort)
  const busy = keyRow && !!s.ui.busy[keyRow.key]
  // the model the check implies for an item the AI may do, while Auto is on (logic.js checkPick)
  const pick = checkPick(tri, s.launch)
  return html`<div class="tri">
    <span class="tri-gist">${tri.gist}</span>
    <span class="tri-marks">
      ${tri.verdict === 'close' ? html`<span class="tri-mark tri-close" title=${tri.reason || undefined}>${t.triage.close}</span>` : null}
      ${tri.verdict === 'unclear' ? html`<span class="tri-mark tri-unclear" title=${tri.reason || undefined}>${t.triage.unclear}</span>` : null}
      ${tri.doer === 'ai' || tri.doer === 'either' ? html`<span class=${`tri-mark tri-${tri.doer}`} title=${tri.why || undefined}>
        ${tri.doer === 'ai' ? t.triage.ai : t.triage.either}
        ${dots ? html`<span class="tri-dots" aria-label=${t.triage.effort[tri.effort]}>${[1, 2, 3].map(i => html`<i key=${i} class=${i <= dots ? 'on' : ''}></i>`)}</span>` : null}</span>` : null}
      ${pick ? html`<span class="tri-mark tri-model" title=${t.launch.checkPickTitle}>${checkPickText(pick, t)}</span>` : null}
      ${tri.doer === 'you' ? html`<span class="tri-mark tri-you" title=${tri.why || undefined}>${tri.why ? `${t.triage.you}: ${tri.why}` : t.triage.you}</span>` : null}
      ${tri.doer === 'ai' && keyRow ? html`<button type="button" class="btn btn-secondary btn-xs tri-do" disabled=${busy}
        title=${t.triage.doTitle} onClick=${() => c.act('do_it', { keys: [keyRow.key] })}><span class="btn-label">${t.triage.doIt}</span></button>` : null}
    </span>
  </div>`
}

/** The strip over a task or inbox page: filters with counts, close what can go, sort again */
export function TriageBar({ s, c, items, byKey }) {
  const t = T()
  const tr = s.triage ?? {}
  const map = tr.items ?? {}
  const f = s.ui.triageFilter ?? 'all'
  const counts = triageCounts(items, map)
  const closable = items.filter(it => map[triageKey(it)]?.verdict === 'close')
    .map(it => actionRow(it, byKey)).filter(r => r && (r.settle ?? []).length)
  const running = !!tr.running
  const last = tr.last
  return html`<div class="panel panel-pad tri-bar" role="group" aria-label=${t.triage.label}>
    <span class="fbar-chips" role="radiogroup" aria-label=${t.triage.label}>
      ${TRIAGE_FILTERS.map(k => html`<button type="button" role="radio" key=${k} aria-checked=${String(f === k)}
        class=${`fchip${f === k ? ' is-on' : ''}`} disabled=${k !== 'all' && !counts[k]} onClick=${() => c.setTriageFilter(k)}>
        ${k !== 'all' ? html`<span class=${`dot tk-${TONE[k]}`} aria-hidden="true"></span>` : null}${t.triage.filter[k]}${k !== 'all' ? html` <span class="mono">${counts[k]}</span>` : null}</button>`)}
    </span>
    ${closable.length ? html`<${CloseAll} rows=${closable} c=${c} s=${s} />` : null}
    <span class="tri-run">
      <span class="muted small">${running ? t.triage.running : last ? t.triage.last({ ...last, cost: centsText(last.cost_ct, language()) }, language()) : t.triage.never}</span>
      <button type="button" class="btn btn-ghost btn-xs" disabled=${running} aria-busy=${running ? 'true' : undefined}
        onClick=${() => c.triageRun(false)} title=${t.triage.rerunTitle}><span class="btn-label">${t.triage.rerun}</span></button>
    </span>
  </div>`
}

/** Close everything closable in two clicks: the menu names what goes, then done or not doing */
function CloseAll({ rows, c, s }) {
  const t = T()
  const [open, setOpen] = useState(false)
  const box = useRef(null)
  useEffect(() => {
    if (!open) return undefined
    const away = e => { if (box.current && !box.current.contains(e.target)) setOpen(false) }
    const esc = e => { if (e.key === 'Escape') { e.stopPropagation(); setOpen(false) } }
    document.addEventListener('pointerdown', away)
    document.addEventListener('keydown', esc, true)
    return () => { document.removeEventListener('pointerdown', away); document.removeEventListener('keydown', esc, true) }
  }, [open])
  const keys = rows.map(r => r.key)
  const pick = outcome => { setOpen(false); c.act('settle', { keys, outcome }) }
  return html`<span class="settle" ref=${box}>
    <button type="button" class="btn btn-primary btn-xs" aria-pressed=${String(open)} disabled=${!!s.ui.busy[keys.join(',')]}
      onClick=${() => setOpen(!open)}><span class="btn-label">${t.triage.closeAll(rows.length)} ▾</span></button>
    ${open ? html`<span class="settle-menu tri-menu" role="menu">
      <ul class="tri-list">${rows.map(r => html`<li key=${r.key}>${r.title}</li>`)}</ul>
      <button type="button" role="menuitem" class="settle-item" onClick=${() => pick('done')}>
        <span class="dot tk-success" aria-hidden="true"></span><span>${t.settleDone}</span></button>
      <button type="button" role="menuitem" class="settle-item" onClick=${() => pick('not_doing')}>
        <span class="dot tk-on-surface-muted" aria-hidden="true"></span><span>${t.settleNot}</span></button>
    </span>` : null}
  </span>`
}
