// SPDX-License-Identifier: MIT
// Organize with AI: what one question to the model proposes for the workspaces and tabs of this Bridge
// (actions.py organize_propose), grouped by workspace, nothing ticked. Only the ticked items are applied
// (organize_apply); after that the applied, skipped and failed ones are listed. The scope, the checks and
// the safe order live on the server (organize.py); this view only shows and ticks.
// The rules every component keeps stand at the head of components.js.

import { html } from '../vendor/htm-preact-3.1.1.module.js'
import { organizeGroups, organizeTicks, roomsOf } from '../logic.js'
import { T } from '../text.js'
import { useFocusOnOpen } from './overlays.js'
import { Btn, Spinner } from './parts.js'

/** A value as the row shows it: a colour or description that is not set says so */
function shown(t, it, which) {
  const v = which === 'from' ? it.fromText : it.toText
  if (v) return v
  return it.kind === 'ws_color' ? t.organize.noColour : it.kind === 'ws_description' ? t.organize.noDescription : ''
}

function ItemRow({ it, on, c }) {
  const t = T()
  const kind = t.organize.kinds[it.kind] ?? it.kind
  const from = shown(t, it, 'from')
  return html`<li class="org-item">
    <label class="org-line">
      <input type="checkbox" checked=${on} aria-label=${t.organize.tickItem(kind, it.subject)}
        onChange=${() => c.organizeToggle(it.id)} />
      <span class="org-kind label-caps">${kind}</span>
      <span class="org-subject">${it.kind === 'tab_title' || it.kind === 'tab_move' ? it.subject : ''}</span>
      ${from ? html`<s class="org-from muted">${from}</s>` : null}
      <span class="org-arrow" aria-hidden="true">${' > '}</span>
      <span class="org-to">${shown(t, it, 'to')}</span>
    </label>
    ${it.why ? html`<p class="org-why muted small">${it.why}</p>` : null}
  </li>`
}

function Group({ g, ticks, c }) {
  const t = T()
  const state = organizeTicks.groupState(ticks, g)
  return html`<section class="org-group">
    <header class="org-group-head">
      <h3 class="sec-title org-group-title">${g.title}</h3>
      <label class="org-group-tick small">
        <input type="checkbox" checked=${state === 'all'} aria-checked=${state === 'some' ? 'mixed' : undefined}
          aria-label=${`${t.organize.tickGroup}: ${g.title}`} onChange=${() => c.organizeTickGroup(g.ref, state !== 'all')} />
        <span>${t.organize.tickGroup}</span>
      </label>
    </header>
    <ul class="org-items">${g.items.map(it => html`<${ItemRow} key=${it.id} it=${it} on=${!!ticks?.[it.id]} c=${c} />`)}</ul>
  </section>`
}

/** After apply: the counts, and per list what it was about */
function Result({ result, byId }) {
  const t = T()
  const what = id => { const it = byId.get(id); return it ? `${t.organize.kinds[it.kind] ?? it.kind}: ${it.subject}` : id }
  const why = x => t.organize.why[x.why] ?? x.why
  return html`<div class="org-result" role="status">
    <p class="small"><strong>${t.organize.applied(result.applied.length)}</strong></p>
    ${result.applied.length ? html`<ul class="org-list small">${result.applied.map(id => html`<li key=${id}>${what(id)}</li>`)}</ul>` : null}
    ${result.skipped.length ? html`<p class="small">${t.organize.skipped(result.skipped.length)}</p>
      <ul class="org-list small muted">${result.skipped.map(x => html`<li key=${x.id}>${what(x.id)} (${why(x)})</li>`)}</ul>` : null}
    ${result.failed.length ? html`<p class="small">${t.organize.failed(result.failed.length)}</p>
      <ul class="org-list small">${result.failed.map(x => html`<li key=${x.id}>${what(x.id)}: ${x.error}</li>`)}</ul>` : null}
  </div>`
}

export function OrganizeView({ s, c }) {
  const t = T()
  const o = s.ui?.organize
  const ref = useFocusOnOpen(!!o)
  if (!o) return null
  const proposal = o.proposal
  const groups = proposal ? organizeGroups(proposal, roomsOf(s)) : []
  const byId = new Map(groups.flatMap(g => g.items.map(it => [it.id, it])))
  const n = organizeTicks.ids(o.ticks, proposal).length
  return html`<div class="overlay overlay-center" onClick=${e => { if (e.target === e.currentTarget && !o.applying) c.organizeClose() }}>
    <div class="dialog dialog-wide org-dialog" role="dialog" aria-modal="true" aria-labelledby="organize-title" aria-busy=${o.busy || o.applying ? 'true' : undefined} ref=${ref}>
      <header class="drawer-head">
        <h2 class="sec-title" id="organize-title">${t.organize.title}</h2>
      </header>
      ${o.busy ? html`<p class="org-busy muted"><${Spinner} /> ${t.organize.thinking}</p>` : null}
      ${proposal ? html`<p class="org-scope small">${t.organize.scope(proposal.scope)}</p>
        <p class="muted small">${t.organize.hint}</p>` : null}
      ${proposal && !proposal.items.length ? html`<p class="org-none">${t.organize.none}</p>` : null}
      ${groups.length ? html`<div class="org-groups">${groups.map(g => html`<${Group} key=${g.ref} g=${g} ticks=${o.ticks} c=${c} />`)}</div>` : null}
      ${o.result ? html`<${Result} result=${o.result} byId=${byId} />` : null}
      <div class="btn-row dialog-acts">
        ${proposal?.items.length ? html`<${Btn} size="sm" variant="ghost" onClick=${() => c.organizeTickAll()}>${t.organize.tickAll}<//>` : null}
        <button type="button" class="btn btn-secondary btn-sm" data-autofocus disabled=${o.applying}
          onClick=${() => c.organizeClose()}><span class="btn-label">${t.organize.close}</span></button>
        <${Btn} size="sm" variant="primary" disabled=${n === 0 || o.busy} busy=${o.applying} onClick=${() => c.organizeApply()}>${t.organize.apply(n)}<//>
      </div>
    </div>
  </div>`
}
