// SPDX-License-Identifier: MIT
// The cockpit, the settings page: one group per subject, the first is the model an agent tab starts with.
// The rules every component keeps stand at the head of components.js.

import { html, useEffect, useState } from '../vendor/htm-preact-3.1.1.module.js'
import { LAUNCH_EFFORTS, LAUNCH_MODELS, bandsProblem, jevModelValid, launchPatch } from '../logic.js'
import { T } from '../text.js'
import { Segmented } from './detail.js'
import { Btn, Chip, Empty } from './parts.js'

/** The page: a header and the groups, each a panel of its own. A later group joins the list */
export function SettingsPage({ s, c }) {
  const t = T()
  return html`<div class="col col-page settings-page">
    <header class="page-head"><h2 class="detail-title">${t.settings.title}</h2></header>
    ${GROUPS.map(Group => html`<${Group} key=${Group.name} s=${s} c=${c} />`)}
  </div>`
}

/** One setting: its name, what it does in one line, its control, and a mark where the page changed it
 *  against bridge-config.yaml (the config's value in the tooltip) */
function SetRow({ k, s, children }) {
  const t = T()
  const l = s.launch
  const changed = (l?.overridden ?? []).includes(k)
  return html`<div class="set-row">
    <div class="set-head">
      <span class="set-label">${t.settings.label[k]}</span>
      ${changed ? html`<${Chip} token="warning" title=${t.settings.configWas(valueWord(k, l?.defaults?.[k]))}>${t.settings.changed}<//>` : null}
    </div>
    <p class="muted small set-explain">${t.settings.explain[k]}</p>
    <div class="set-control">${children}</div>
  </div>`
}

/** A value of the config in words, for the "changed" tooltip */
function valueWord(k, v) {
  const t = T()
  if (typeof v === 'boolean') return v ? t.settings.on : t.settings.off
  if (v == null) return k === 'default_effort' ? t.launch.effort.standard : t.settings.none
  if (k === 'router') return t.settings.router[v] ?? v
  if (Array.isArray(v)) return v.map(x => `${t.launch.model[x.model] ?? x.model} ${x.effort ? t.launch.effort[x.effort] ?? x.effort : ''}`.trim()).join(', ')
  return t.launch.model[v] ?? t.launch.effort[v] ?? String(v)
}

/** A switch that saves at once */
function Toggle({ k, s, save, disabled }) {
  const on = !!s.launch?.settings?.[k]
  return html`<label class="set-toggle">
    <input type="checkbox" role="switch" checked=${on} disabled=${disabled} aria-label=${T().settings.label[k]}
      onChange=${e => save(k, e.currentTarget.checked)} />
    <span>${on ? T().settings.on : T().settings.off}</span>
  </label>`
}

/** The model an agent tab starts with: master switch, the three sub switches (grey while it is off), the
 *  defaults, how Auto decides, and the two tables that turn a rating into model and effort */
function LaunchSettings({ s, c }) {
  const t = T()
  const w = t.settings
  const l = s.launch
  if (!l?.settings) {
    return html`<section class="panel panel-pad set-group"><h3 class="label-caps">${w.launchTitle}</h3><${Empty}>${w.noServer}<//></section>`
  }
  const st = l.settings
  const on = !!st.enabled
  const busy = !!s.ui.busy.launch_settings || !!s.ui.busy.launch_settings_reset
  const save = (k, v) => c.saveLaunch(launchPatch(k, v))
  const models = l.models?.length ? l.models : LAUNCH_MODELS
  const efforts = l.efforts?.length ? l.efforts : LAUNCH_EFFORTS
  const modelValues = models.map(m => [m, t.launch.model[m] ?? m])
  return html`<section class="panel panel-pad set-group">
    <header class="set-group-head">
      <h3 class="label-caps">${w.launchTitle}</h3>
      <${Btn} size="xs" variant="ghost" busy=${busy} disabled=${!(l.overridden ?? []).length} title=${w.resetTitle}
        onClick=${() => c.resetLaunch()}>${w.reset}<//>
    </header>
    <p class="muted small">${w.launchIntro}</p>
    <${SetRow} k="enabled" s=${s}><${Toggle} k="enabled" s=${s} save=${save} disabled=${busy} /><//>
    <fieldset class=${`set-sub${on ? '' : ' is-off'}`} disabled=${!on}>
      <${SetRow} k="manual" s=${s}><${Toggle} k="manual" s=${s} save=${save} disabled=${busy} /><//>
      <${SetRow} k="auto" s=${s}><${Toggle} k="auto" s=${s} save=${save} disabled=${busy} /><//>
      <${SetRow} k="effort" s=${s}><${Toggle} k="effort" s=${s} save=${save} disabled=${busy} /><//>
      <${SetRow} k="default_model" s=${s}>
        <${Segmented} label=${w.label.default_model} busy=${busy || !on} current=${st.default_model} values=${modelValues}
          onPick=${v => save('default_model', v)} /><//>
      <${SetRow} k="default_effort" s=${s}>
        <${Segmented} label=${w.label.default_effort} busy=${busy || !on} current=${st.default_effort ?? 'standard'}
          values=${['standard', ...efforts].map(e => [e, t.launch.effort[e] ?? e])} onPick=${v => save('default_effort', v)} /><//>
      <${SetRow} k="max_model" s=${s}>
        <${Segmented} label=${w.label.max_model} busy=${busy || !on} current=${st.max_model} values=${modelValues}
          onPick=${v => save('max_model', v)} /><//>
      <${SetRow} k="router" s=${s}>
        <${Segmented} label=${w.label.router} busy=${busy || !on} current=${st.router}
          values=${['chain', 'jev', 'haiku'].map(r => [r, w.router[r]])} onPick=${v => save('router', v)} />
        <span class="muted small">${w.routerNow(w.routerWord[l.router] ?? l.router ?? w.routerWord.off)}</span><//>
      <${SetRow} k="jev_model" s=${s}><${JevModelField} value=${st.jev_model ?? ''} busy=${busy} save=${save} /><//>
      <${SetRow} k="jev_bands" s=${s}><${BandsTable} bands=${st.jev_bands ?? []} models=${models} efforts=${efforts} busy=${busy} save=${save} /><//>
      <${SetRow} k="haiku_map" s=${s}><${HaikuTable} map=${st.haiku_map ?? []} models=${models} efforts=${efforts} busy=${busy} save=${save} /><//>
    </fieldset>
  </section>`
}

// the groups of the page in their order; a new subject adds its component here
const GROUPS = [LaunchSettings]

/** The Jev model by name, saved with the button once it reads like jev-1.14.0 */
function JevModelField({ value, busy, save }) {
  const w = T().settings
  const [draft, setDraft] = useState(value)
  useEffect(() => setDraft(value), [value])
  const ok = jevModelValid(draft)
  const go = () => { if (ok && draft.trim() !== value) save('jev_model', draft) }
  return html`<span class="field-row set-field">
    <input class="input input-sm mono" type="text" value=${draft} aria-label=${w.label.jev_model} aria-invalid=${String(!ok)}
      onInput=${e => setDraft(e.currentTarget.value)} onKeyDown=${e => { if (e.key === 'Enter') go() }} />
    <${Btn} size="xs" variant="secondary" busy=${busy} disabled=${!ok || draft.trim() === value} onClick=${go}>${w.save}<//>
    ${ok ? null : html`<span class="small set-bad">${w.jevModelBad}</span>`}
  </span>`
}

/** A model and an effort per row, as two selects; an effort of null is the CLI's own default */
function PickCells({ x, models, efforts, set }) {
  const t = T()
  return html`<td><select class="input input-sm" aria-label=${t.settings.model} value=${x.model}
      onChange=${e => set({ model: e.currentTarget.value })}>
      ${models.map(m => html`<option key=${m} value=${m}>${t.launch.model[m] ?? m}</option>`)}</select></td>
    <td><select class="input input-sm" aria-label=${t.settings.effort} value=${x.effort ?? 'standard'}
      onChange=${e => set({ effort: e.currentTarget.value === 'standard' ? null : e.currentTarget.value })}>
      ${['standard', ...efforts].map(v => html`<option key=${v} value=${v}>${t.launch.effort[v] ?? v}</option>`)}</select></td>`
}

/** The Jev bands: a rating below a row's bound gets that row's model and effort, the last row the rest.
 *  Edited here, checked (0 to 3, rising), saved as one with the button */
function BandsTable({ bands, models, efforts, busy, save }) {
  const w = T().settings
  const [draft, setDraft] = useState(bands)
  const was = JSON.stringify(bands)
  useEffect(() => setDraft(bands), [was])
  const problem = bandsProblem(draft)
  const set = (i, patch) => setDraft(draft.map((b, j) => (j === i ? { ...b, ...patch } : b)))
  return html`<div class="set-table-wrap">
    <table class="tbl set-table">
      <thead><tr><th scope="col">${w.below}</th><th scope="col">${w.model}</th><th scope="col">${w.effort}</th></tr></thead>
      <tbody>${draft.map((b, i) => html`<tr key=${i}>
        <td>${b.below == null ? html`<span class="muted">${w.else}</span>`
          : html`<input class="input input-sm mono set-num" type="number" min="0" max="3" step="0.05" value=${b.below}
              aria-label=${`${w.below} ${i + 1}`} onInput=${e => set(i, { below: e.currentTarget.value === '' ? Number.NaN : Number(e.currentTarget.value) })} />`}</td>
        <${PickCells} x=${b} models=${models} efforts=${efforts} set=${p => set(i, p)} />
      </tr>`)}</tbody>
    </table>
    <span class="field-row">
      <${Btn} size="xs" variant="secondary" busy=${busy} disabled=${!!problem || JSON.stringify(draft) === was}
        onClick=${() => save('jev_bands', draft)}>${w.save}<//>
      ${problem ? html`<span class="small set-bad">${w.bandsBad[problem]}</span>` : null}
    </span>
  </div>`
}

/** The Haiku levels 0 to 3, each with its model and effort, saved as one with the button */
function HaikuTable({ map, models, efforts, busy, save }) {
  const w = T().settings
  const [draft, setDraft] = useState(map)
  const was = JSON.stringify(map)
  useEffect(() => setDraft(map), [was])
  const set = (i, patch) => setDraft(draft.map((b, j) => (j === i ? { ...b, ...patch } : b)))
  return html`<div class="set-table-wrap">
    <table class="tbl set-table">
      <thead><tr><th scope="col"></th><th scope="col">${w.model}</th><th scope="col">${w.effort}</th></tr></thead>
      <tbody>${draft.map((x, i) => html`<tr key=${i}>
        <th scope="row">${w.level(i)}</th>
        <${PickCells} x=${x} models=${models} efforts=${efforts} set=${p => set(i, p)} />
      </tr>`)}</tbody>
    </table>
    <span class="field-row">
      <${Btn} size="xs" variant="secondary" busy=${busy} disabled=${JSON.stringify(draft) === was}
        onClick=${() => save('haiku_map', draft)}>${w.save}<//>
    </span>
  </div>`
}
