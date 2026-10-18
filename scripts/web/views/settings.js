// SPDX-License-Identifier: MIT
// The cockpit, the settings: one page with an area per subject (the start page, how it looks, the model an
// agent tab starts with), and the drawer "Customise" opens beside the start page with the same editors.
// The rules every component keeps stand at the head of components.js.

import { html, useEffect, useState } from '../vendor/htm-preact-3.1.1.module.js'
import {
  LAUNCH_EFFORTS, LAUNCH_MODELS, MAX_STATIONS, bandsProblem, dropAmong, homeCatalog, homeChosen, jevModelValid,
  launchPatch, moveAmong,
} from '../logic.js'
import { T } from '../text.js'
import { Segmented } from './detail.js'
import { catalogLabel } from './home.js'
import { Drawer } from './overlays.js'
import { Btn, Chip, Empty, Icon, StateLine, useRoving } from './parts.js'
import { TickerSettings } from './ticker.js'

const SECTIONS = ['start', 'look', 'launch', 'ticker']
const STATION_KINDS = ['quota', 'count', 'page']

// ---------------------------------------------------------------- the parts every area uses

/** An on/off switch: a button with role switch, the state in its track */
export function Switch({ on, onChange, label, disabled }) {
  return html`<button type="button" role="switch" class="switch" aria-checked=${String(!!on)} aria-label=${label}
    disabled=${disabled} onClick=${() => onChange(!on)}><span class="switch-thumb" aria-hidden="true"></span></button>`
}

/** A card of one subject: its title, a line on what it is for, an optional control in its head */
export function Card({ title, intro, head, children, off }) {
  return html`<section class=${`panel set-card${off ? ' is-off' : ''}`}>
    <header class="set-card-head">
      <div class="set-card-title"><h3 class="set-card-name">${title}</h3>${intro ? html`<p class="muted small">${intro}</p>` : null}</div>
      ${head ? html`<div class="set-card-tool">${head}</div>` : null}
    </header>
    ${children ? html`<div class="set-card-body">${children}</div>` : null}
  </section>`
}

/** One setting: its name and what it does on the left, its control on the right (below it when `wide`) */
export function Row({ label, explain, mark, wide, children }) {
  return html`<div class=${`set-row${wide ? ' is-wide' : ''}`}>
    <div class="set-text">
      <span class="set-label">${label}${mark ?? null}</span>
      ${explain ? html`<span class="muted small set-explain">${explain}</span>` : null}
    </div>
    <div class="set-control">${children}</div>
  </div>`
}

// ---------------------------------------------------------------- the start page

/** What the start page offers and shows, and a save that keeps what it offered (homeChosen reads both) */
function useHome(s, c) {
  const catalog = homeCatalog(s.model, { workers: s.workers?.status !== 'none' })
  const chosen = homeChosen(s.model, s.home)
  const save = list => c.setHomeTiles(list, catalog.map(x => x.id))
  const flip = (id, on) => save(on ? (chosen.includes(id) ? chosen : [...chosen, id]) : chosen.filter(x => x !== id))
  return { catalog, chosen, on: new Set(chosen), save, flip }
}

/** The start page's view, bridge or tiles, as the first choice of the area */
function ViewCard({ home }) {
  const w = T().settings
  const view = home.on.has('o:classic') ? 'tiles' : 'stage'
  const keys = useRoving()
  return html`<${Card} title=${w.viewTitle} intro=${w.viewIntro}>
    <div class="view-pick" role="radiogroup" aria-label=${w.viewTitle} ref=${keys.ref} onKeyDown=${keys.onKeyDown}>
      ${['stage', 'tiles'].map(v => html`<button type="button" key=${v} role="radio" aria-checked=${String(view === v)}
        class=${`view-opt${view === v ? ' is-on' : ''}`} onClick=${() => view !== v && home.flip('o:classic', v === 'tiles')}>
        <span class=${`view-thumb view-thumb-${v}`} aria-hidden="true">${v === 'stage'
          ? html`<b></b><i></i><i></i><i></i><i></i><i></i><i></i>` : html`<em></em><i></i><i></i><i></i><i></i>`}</span>
        <span class="view-name">${w.view[v]}</span>
        <span class="muted small">${w.viewExplain[v]}</span>
      </button>`)}
    </div>
  <//>`
}

/** The stations of the bridge (the tiles of the tiles view): the ones shown in their order, each with a
 *  switch, two arrows and a grip to drag it; below them the ones not shown. The bridge has a place for
 *  MAX_STATIONS - 1 of them, Today takes the last */
function StationsCard({ home }) {
  const w = T().settings
  const tiles = home.on.has('o:classic')
  const byId = new Map(home.catalog.map(x => [x.id, x]))
  const isStation = id => STATION_KINDS.includes(byId.get(id)?.kind)
  const shown = home.chosen.filter(isStation)
  const hidden = home.catalog.filter(x => STATION_KINDS.includes(x.kind) && !home.on.has(x.id))
  const room = MAX_STATIONS - 1
  const [drag, setDrag] = useState(null)
  const [over, setOver] = useState(null)
  const drop = target => {
    if (drag && target && drag !== target) home.save(dropAmong(home.chosen, isStation, drag, target))
    setDrag(null)
    setOver(null)
  }
  const row = (id, i) => {
    const x = byId.get(id)
    const name = catalogLabel(x)
    const full = !tiles && i >= room
    return html`<li key=${id} class=${`st-row${drag === id ? ' is-drag' : ''}${over === id && drag !== id ? ' is-over' : ''}${full ? ' is-full' : ''}`}
      draggable="true" onDragStart=${e => { setDrag(id); e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', id) }}
      onDragOver=${e => { e.preventDefault(); if (over !== id) setOver(id) }}
      onDrop=${e => { e.preventDefault(); drop(id) }} onDragEnd=${() => { setDrag(null); setOver(null) }}>
      <span class="st-grip" title=${w.drag(name)} aria-hidden="true"></span>
      <span class="st-pos num" aria-hidden="true">${i + 1}</span>
      <span class="st-name">${name}${full ? html`<small class="st-full">${w.stationsFull}</small>` : null}</span>
      <span class="st-kind">${w.kind[x.kind]}</span>
      <span class="st-move">
        <button type="button" class="icon-btn" disabled=${i === 0} aria-label=${w.up(name)} title=${w.up(name)}
          onClick=${() => home.save(moveAmong(home.chosen, isStation, id, -1))}><${Icon} name="chevronUp" size=${14} /></button>
        <button type="button" class="icon-btn" disabled=${i === shown.length - 1} aria-label=${w.down(name)} title=${w.down(name)}
          onClick=${() => home.save(moveAmong(home.chosen, isStation, id, 1))}><${Icon} name="chevronDown" size=${14} /></button>
      </span>
      <${Switch} on=${true} label=${name} onChange=${() => home.flip(id, false)} />
    </li>`
  }
  const count = tiles ? null : html`<span class=${`set-count num${shown.length > room ? ' is-over' : ''}`}>${w.stationsCount(Math.min(shown.length, room), room)}</span>`
  return html`<${Card} title=${tiles ? w.stationsTitleTiles : w.stationsTitle} intro=${w.stationsIntro} head=${count}>
    <h4 class="label-caps st-group">${w.stationsShown}</h4>
    ${shown.length ? html`<ol class="st-list">${shown.map(row)}</ol>` : html`<${Empty}>${w.stationsNone}<//>`}
    <h4 class="label-caps st-group">${w.stationsHidden}</h4>
    ${hidden.length ? html`<ul class="st-list is-hidden">${hidden.map(x => html`<li key=${x.id} class="st-row">
      <span class="st-name">${catalogLabel(x)}</span>
      <span class="st-kind">${w.kind[x.kind]}</span>
      <${Switch} on=${false} label=${catalogLabel(x)} onChange=${() => home.flip(x.id, true)} />
    </li>`)}</ul>` : html`<${Empty}>${w.stationsAllShown}<//>`}
  <//>`
}

/** Switches for a list of catalog ids, each with its explanation; `note(id)` adds a remark beside the name */
function SwitchRows({ home, ids, note }) {
  const w = T().settings
  const known = new Map(home.catalog.map(x => [x.id, x]))
  return ids.filter(id => known.has(id)).map(id => {
    const name = catalogLabel(known.get(id))
    const extra = note?.(id)
    return html`<${Row} key=${id} label=${name} explain=${w.explainOption[id]} mark=${extra ? html`<${Chip}>${extra}<//>` : null}>
      <${Switch} on=${home.on.has(id)} label=${name} onChange=${v => home.flip(id, v)} />
    <//>`
  })
}

function ShelvesCard({ home }) {
  const w = T().settings
  const tiles = home.on.has('o:classic')
  return html`<${Card} title=${w.shelvesTitle} intro=${w.shelvesIntro}>
    <${SwitchRows} home=${home} ids=${home.catalog.filter(x => x.kind === 'shelf').map(x => x.id)}
      note=${id => (id === 's:focus' && !tiles ? w.onlyTiles : null)} />
  <//>`
}

/** What a click on the bridge's core does besides the picture of the day; the tiles view has no core */
function CoreCard({ home }) {
  const w = T().settings
  if (home.on.has('o:classic')) return null
  return html`<${Card} title=${w.coreTitle} intro=${w.coreIntro}>
    <${SwitchRows} home=${home} ids=${home.catalog.filter(x => x.kind === 'core').map(x => x.id)} />
  <//>`
}

function StartArea({ s, c }) {
  const home = useHome(s, c)
  return html`<${ViewCard} home=${home} />
    <${StationsCard} home=${home} />
    <${ShelvesCard} home=${home} />
    <${CoreCard} home=${home} />`
}

// ---------------------------------------------------------------- how it looks

/** Light, dark or the system's: kept in this browser only, unlike everything else here */
function ThemeCard({ s, c }) {
  const t = T()
  const w = t.settings
  return html`<${Card} title=${w.themeTitle} intro=${w.themeIntro} head=${html`<span class="muted small">${w.thisBrowser}</span>`}>
    <${Segmented} label=${w.themeTitle} current=${s.ui.theme} values=${['auto', 'light', 'dark'].map(v => [v, t.theme[v]])}
      onPick=${v => c.setTheme(v)} />
  <//>`
}

function DetailsCard({ s, c }) {
  const w = T().settings
  const home = useHome(s, c)
  return html`<${Card} title=${w.detailsTitle} intro=${w.detailsIntro} head=${html`<span class="muted small">${w.everywhere}</span>`}>
    <${SwitchRows} home=${home} ids=${['o:pulse', 'o:today', 'o:trend', 'o:preview', 'o:project', 'o:title']} />
  <//>`
}

function LookArea({ s, c }) {
  return html`<${ThemeCard} s=${s} c=${c} /><${DetailsCard} s=${s} c=${c} />`
}

// ---------------------------------------------------------------- the model an agent tab starts with

/** A mark where the page changed a value against bridge-config.yaml, the config's value in the tooltip */
function changedMark(k, l) {
  const w = T().settings
  return (l?.overridden ?? []).includes(k)
    ? html`<${Chip} token="warning" title=${w.configWas(valueWord(k, l?.defaults?.[k]))}>${w.changed}<//>` : null
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

/** A launch setting as a row: label, explanation and changed mark from its key */
function LRow({ k, l, wide, children }) {
  const w = T().settings
  return html`<${Row} label=${w.label[k]} explain=${w.explain[k]} mark=${changedMark(k, l)} wide=${wide}>${children}<//>`
}

/** The model an agent tab starts with: the main switch, the choice by hand, and Auto, whose details show
 *  only while it is on (the Jev rows only when Jev may decide, the Haiku table only when Haiku may) */
function LaunchArea({ s, c }) {
  const t = T()
  const w = t.settings
  const l = s.launch
  if (!l?.settings) return html`<${Card} title=${w.launchTitle}><${Empty}>${w.noServer}<//><//>`
  const st = l.settings
  const on = !!st.enabled
  const busy = !!s.ui.busy.launch_settings || !!s.ui.busy.launch_settings_reset
  const save = (k, v) => c.saveLaunch(launchPatch(k, v))
  const models = l.models?.length ? l.models : LAUNCH_MODELS
  const efforts = l.efforts?.length ? l.efforts : LAUNCH_EFFORTS
  const modelValues = models.map(m => [m, t.launch.model[m] ?? m])
  const toggle = k => html`<${Switch} on=${!!st[k]} label=${w.label[k]} disabled=${busy || (k !== 'enabled' && !on) || (k === 'triage_jev' && !st.auto)}
    onChange=${v => save(k, v)} />`
  const changed = (l.overridden ?? []).length
  return html`
    ${changed ? html`<div class="set-banner" role="status">
      <span class="set-banner-text">${w.overridden(changed)}</span>
      <${Btn} size="xs" variant="secondary" busy=${busy} title=${w.resetTitle} onClick=${() => c.resetLaunch()}>${w.reset}<//>
    </div>` : null}
    <${Card} title=${w.launchTitle} intro=${on ? w.launchIntro : w.mainOff} head=${html`<span class="set-head-switch">${changedMark('enabled', l)}${toggle('enabled')}</span>`} />
    <${Card} title=${w.manualTitle} intro=${w.manualIntro} off=${!on}>
      <${LRow} k="manual" l=${l}>${toggle('manual')}<//>
      <${LRow} k="effort" l=${l}>${toggle('effort')}<//>
      <${LRow} k="default_model" l=${l}>
        <${Segmented} label=${w.label.default_model} busy=${busy || !on} current=${st.default_model} values=${modelValues}
          onPick=${v => save('default_model', v)} /><//>
      <${LRow} k="default_effort" l=${l} wide>
        <${Segmented} label=${w.label.default_effort} busy=${busy || !on} current=${st.default_effort ?? 'standard'}
          values=${['standard', ...efforts].map(e => [e, t.launch.effort[e] ?? e])} onPick=${v => save('default_effort', v)} /><//>
    <//>
    <${Card} title=${w.autoTitle} intro=${st.auto ? w.autoIntro : w.autoOff} off=${!on}
      head=${html`<span class="set-head-switch">${changedMark('auto', l)}${toggle('auto')}</span>`}>
      ${st.auto ? html`
        <${LRow} k="max_model" l=${l}>
          <${Segmented} label=${w.label.max_model} busy=${busy || !on} current=${st.max_model} values=${modelValues}
            onPick=${v => save('max_model', v)} /><//>
        <${LRow} k="router" l=${l} wide>
          <${Segmented} label=${w.label.router} busy=${busy || !on} current=${st.router}
            values=${['chain', 'jev', 'haiku'].map(r => [r, w.router[r]])} onPick=${v => save('router', v)} />
          <span class="muted small">${w.routerNow(w.routerWord[l.router] ?? l.router ?? w.routerWord.off)}</span><//>
        <${LRow} k="triage_jev" l=${l}>
          ${s.jev?.ready ? null : html`<span class="muted small set-aside">${w.triageJevNeedsJev}</span>`}${toggle('triage_jev')}<//>
        ${st.router !== 'haiku' ? html`
          <${LRow} k="jev_model" l=${l}><${JevModelField} value=${st.jev_model ?? ''} busy=${busy} save=${save} /><//>
          <${LRow} k="jev_bands" l=${l} wide><${BandsTable} bands=${st.jev_bands ?? []} models=${models} efforts=${efforts} busy=${busy} save=${save} /><//>` : null}
        ${st.router !== 'jev' ? html`
          <${LRow} k="haiku_map" l=${l} wide><${HaikuTable} map=${st.haiku_map ?? []} models=${models} efforts=${efforts} busy=${busy} save=${save} /><//>` : null}
      ` : null}
    <//>`
}

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

/** The scale 0 to 3 as one bar: each band a stretch in its model's tone, model and effort written in it */
function Scale({ spans }) {
  const t = T()
  const tone = { haiku: 'success', sonnet: 'info', opus: 'warning' }   // the dearer the model, the warmer
  return html`<div class="scale" role="img" aria-label=${t.settings.scaleLabel}>
    <div class="scale-bar">
      ${spans.map((x, i) => {
        const width = Math.max(0, Math.min(3, x.to) - Math.max(0, x.from)) / 3 * 100
        return width > 0 ? html`<span key=${i} class=${`scale-band tk-${tone[x.model] ?? 'secondary'}`} style=${{ width: `${width}%` }}>
          <b>${t.launch.model[x.model] ?? x.model}</b><small>${x.effort ? t.launch.effort[x.effort] ?? x.effort : t.launch.effort.standard}</small>
        </span>` : null
      })}
    </div>
    <div class="scale-ticks num" aria-hidden="true"><span>0</span><span>1</span><span>2</span><span>3</span></div>
  </div>`
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
 *  Edited here (the scale follows the draft), checked (0 to 3, rising), saved as one with the button */
function BandsTable({ bands, models, efforts, busy, save }) {
  const w = T().settings
  const [draft, setDraft] = useState(bands)
  const was = JSON.stringify(bands)
  useEffect(() => setDraft(bands), [was])
  const problem = bandsProblem(draft)
  const set = (i, patch) => setDraft(draft.map((b, j) => (j === i ? { ...b, ...patch } : b)))
  const spans = problem ? [] : draft.map((b, i) => ({ from: i ? draft[i - 1].below : 0, to: b.below ?? 3, model: b.model, effort: b.effort }))
  return html`<div class="set-table-wrap">
    ${spans.length ? html`<${Scale} spans=${spans} />` : null}
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
  const step = draft.length ? 3 / draft.length : 3
  return html`<div class="set-table-wrap">
    ${draft.length ? html`<${Scale} spans=${draft.map((x, i) => ({ from: i * step, to: (i + 1) * step, model: x.model, effort: x.effort }))} />` : null}
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

// ---------------------------------------------------------------- the page and the drawer

/** What the server's check of the cockpit: block found (/api/bootstrap config_warnings): one line per key it
 *  does not know or could not use, each with the value used instead; nothing when the block is clean */
export function ConfigWarnings({ s }) {
  const lines = s.boot?.warnings ?? []
  if (!lines.length) return null
  const w = T().settings
  return html`<div class="banner set-warnings" role="status">
    <${StateLine} token="warning" strong word=${w.configWarnings} />
    <p class="muted small">${w.configWarningsExplain}</p>
    <ul class="set-warnings-list">${lines.map((line, i) => html`<li key=${i} class="mono small">${line}</li>`)}</ul>
  </div>`
}

// the news ticker on the start page: its own group from views/ticker.js
const AREAS = { start: StartArea, look: LookArea, launch: LaunchArea, ticker: TickerSettings }
const AREA_ICONS = { start: 'home', look: 'sun', launch: 'spark', ticker: 'bell' }

/** The page: the areas as a list on the left (a row of buttons on a narrow screen), the one chosen beside it */
export function SettingsPage({ s, c }) {
  const w = T().settings
  const at = SECTIONS.includes(s.ui.settingsSection) ? s.ui.settingsSection : SECTIONS[0]
  const Area = AREAS[at]
  return html`<div class="col col-page settings-page">
    <header class="page-head settings-head">
      <h2 class="detail-title">${w.title}</h2>
      <p class="muted">${w.lead}</p>
    </header>
    <${ConfigWarnings} s=${s} />
    <div class="settings-layout">
      <nav class="settings-nav" aria-label=${w.sectionsLabel}>
        ${SECTIONS.map(id => html`<button type="button" key=${id} class=${`settings-nav-item${at === id ? ' is-on' : ''}`}
          aria-current=${at === id ? 'page' : undefined} onClick=${() => c.setSettingsSection(id)}>
          <${Icon} name=${AREA_ICONS[id]} size=${18} />
          <span class="settings-nav-text"><b>${w.section[id].title}</b><small>${w.section[id].sub}</small></span>
        </button>`)}
      </nav>
      <div class="settings-body" key=${at}><${Area} s=${s} c=${c} /></div>
    </div>
  </div>`
}

/** "Customise" beside the start page: the same editors in a drawer that leaves the page in view, so every
 *  change shows on it at once */
export function CustomizeDrawer({ s, c }) {
  const w = T().settings
  return html`<${Drawer} id="customize" title=${w.customizeTitle} onClose=${() => c.setDrawer(null)} cls="drawer-wide" clear>
    <p class="muted small customize-lead">${w.customizeLead}</p>
    <div class="customize-body">
      <${StartArea} s=${s} c=${c} />
      <${DetailsCard} s=${s} c=${c} />
    </div>
    <footer class="customize-foot">
      <${Btn} variant="ghost" size="sm" onClick=${() => c.openSettings('start')}>${w.allSettings}<//>
    </footer>
  <//>`
}
