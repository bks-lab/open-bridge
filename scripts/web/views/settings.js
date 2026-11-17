// SPDX-License-Identifier: MIT
// The cockpit, the settings: one page with an area per subject (the start page, how it looks, the model an
// agent tab starts with). Everything the start page can show is chosen here, in its area Start page; the colours
// and the look-up card of what the help said (the signs of a row, acting, the keys, costs) stand under Appearance.
// The rules every component keeps stand at the head of components.js.

import { html, useEffect, useState } from '../vendor/htm-preact-3.1.1.module.js'
import {
  DESK_PARTS, LAUNCH_EFFORTS, LAUNCH_MODELS, MAX_STATIONS, bandsProblem, dropAmong, featureDisabled, featureGroups, flowModeOf, flowModePatch,
  featuresLocked, homeCatalog, homeChosen, homeView, homeViewSet, jevModelValid, launchPatch, moveAmong, personOf, presetBoard, presetChanges, presetOn,
  restartNotice, restartedLately,
} from '../logic.js'
import { T, language } from '../text.js'
import { Segmented } from './detail.js'
import { catalogLabel } from './home.js'
import { Btn, Chip, Empty, Icon, StateLine, useRoving } from './parts.js'
import { GuideSettings } from './guide.js'
import { TickerSettings } from './ticker.js'
import { WorkspaceSettings } from './workspaces.js'
import { MachineSettings } from './machine.js'
import { BoardSettings } from './github.js'
import { PageSection } from './pages.js'

const SECTIONS = ['setup', 'features', 'start', 'look', 'workspaces', 'machine', 'launch', 'ticker', 'guide', 'boards']
const STATION_KINDS = ['quota', 'count', 'page']

// ---------------------------------------------------------------- the parts every area uses

/** An on/off switch: a button with role switch, the state in its track */
export function Switch({ on, onChange, label, disabled }) {
  return html`<button type="button" role="switch" class="switch" aria-checked=${String(!!on)} aria-label=${label}
    disabled=${disabled} onClick=${() => onChange(!on)}><span class="switch-thumb" aria-hidden="true"></span></button>`
}

/** A card of one subject: its title, a line on what it is for, an optional control in its head; `cls` a class more */
export function Card({ title, intro, head, children, off, cls = '' }) {
  return html`<section class=${`panel set-card${off ? ' is-off' : ''}${cls ? ` ${cls}` : ''}`}>
    <header class="set-card-head">
      <div class="set-card-title"><h3 class="set-card-name">${title}</h3>${intro ? html`<p class="muted small">${intro}</p>` : null}</div>
      ${head ? html`<div class="set-card-tool">${head}</div>` : null}
    </header>
    ${children ? html`<div class="set-card-body">${children}</div>` : null}
  </section>`
}

/** One setting: its name and what it does on the left, its control on the right (below it when `wide`); `note` a
 *  line under the explanation */
export function Row({ label, explain, mark, wide, note, children }) {
  return html`<div class=${`set-row${wide ? ' is-wide' : ''}`}>
    <div class="set-text">
      <span class="set-label">${label}${mark ?? null}</span>
      ${explain ? html`<span class="muted small set-explain">${explain}</span>` : null}
      ${note ?? null}
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
  return { catalog, chosen, on: new Set(chosen), save, flip, view: homeView(chosen), pick: v => save(homeViewSet(chosen, v)) }
}

/** The start page's view, bridge, tiles or list, as the first choice of the area */
function ViewCard({ home }) {
  const w = T().settings
  const view = home.view
  const keys = useRoving()
  return html`<${Card} title=${w.viewTitle} intro=${w.viewIntro}>
    <div class="view-pick" role="radiogroup" aria-label=${w.viewTitle} ref=${keys.ref} onKeyDown=${keys.onKeyDown}>
      ${['areas', 'stage', 'tiles', 'list', 'focus'].map(v => html`<button type="button" key=${v} role="radio" aria-checked=${String(view === v)}
        class=${`view-opt${view === v ? ' is-on' : ''}`} onClick=${() => view !== v && home.pick(v)}>
        <span class=${`view-thumb view-thumb-${v}`} aria-hidden="true">${v === 'areas' ? html`<u></u><i></i><i></i><i></i><u></u>` : v === 'stage'
          ? html`<b></b><i></i><i></i><i></i><i></i><i></i><i></i>`
          : v === 'tiles' ? html`<em></em><i></i><i></i><i></i><i></i>`
          : v === 'list' ? html`<em></em><u></u><i></i><i></i><i></i><i></i>` : html`<em></em><b></b><u></u><i></i><i></i><i></i>`}</span>
        <span class="view-name">${w.view[v]}</span>
        <span class="muted small">${w.viewExplain[v]}</span>
      </button>`)}
    </div>
    ${view === 'focus' ? html`<p class="muted small view-note">${w.focusNote}</p>` : null}
  <//>`
}

/** The stations of the bridge (the tiles of the tiles view): the ones shown in their order, each with a
 *  switch, two arrows and a grip to drag it; below them the ones not shown. The bridge has a place for
 *  MAX_STATIONS - 1 of them, Today takes the last */
function StationsCard({ home }) {
  const w = T().settings
  // the bridge has room for a few; the tiles and the list take as many as are chosen
  const tiles = home.view !== 'stage'
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
  const title = { stage: w.stationsTitle, tiles: w.stationsTitleTiles, list: w.stationsTitleList }[home.view] ?? w.stationsTitleTiles
  return html`<${Card} title=${title} intro=${home.view === 'list' ? w.stationsIntroList : w.stationsIntro} head=${count}>
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
  const list = home.view === 'list'
  // the overview shows the areas and nothing else of the shelves
  const note = id => (home.view === 'areas' ? (id === 's:areas' ? null : w.notDesk)
    : id === 's:focus' && home.view === 'stage' ? w.onlyTiles : id === 's:starts' && list ? w.notList : null)
  return html`<${Card} title=${w.shelvesTitle} intro=${list ? w.shelvesIntroList : w.shelvesIntro}>
    <${SwitchRows} home=${home} ids=${home.catalog.filter(x => x.kind === 'shelf').map(x => x.id)} note=${note} />
  <//>`
}

/** What a click on the bridge's core does besides the picture of the day; the tiles view has no core */
function CoreCard({ home }) {
  const w = T().settings
  if (home.view !== 'stage') return null
  return html`<${Card} title=${w.coreTitle} intro=${w.coreIntro}>
    <${SwitchRows} home=${home} ids=${home.catalog.filter(x => x.kind === 'core').map(x => x.id)} />
  <//>`
}

/** The parts the overview shows under its table: a switch each, off until chosen, saved with the rest of
 *  the start page (home_tiles); the chosen ones in their order, with arrows to move one */
function DeskCard({ home }) {
  const w = T().settings
  const h = T().home
  const isPart = id => id.startsWith('d:')
  const shown = home.chosen.filter(isPart)
  const rest = DESK_PARTS.map(x => `d:${x}`).filter(id => !shown.includes(id))
  const name = id => h.deskPart[id.slice(2)]
  const row = (id, i, on) => html`<${Row} key=${id} label=${name(id)} explain=${w.explainOption[id]}>
    ${on ? html`<span class="st-move">
      <button type="button" class="icon-btn" disabled=${i === 0} aria-label=${w.up(name(id))} title=${w.up(name(id))}
        onClick=${() => home.save(moveAmong(home.chosen, isPart, id, -1))}><${Icon} name="chevronUp" size=${14} /></button>
      <button type="button" class="icon-btn" disabled=${i === shown.length - 1} aria-label=${w.down(name(id))} title=${w.down(name(id))}
        onClick=${() => home.save(moveAmong(home.chosen, isPart, id, 1))}><${Icon} name="chevronDown" size=${14} /></button>
    </span>` : null}
    <${Switch} on=${on} label=${name(id)} onChange=${v => home.flip(id, v)} />
  <//>`
  return html`<${Card} title=${w.deskTitle} intro=${home.view === 'areas' ? w.deskIntro : `${w.deskIntro} ${w.deskOnly}`}>
    ${shown.map((id, i) => row(id, i, true))}${rest.map((id, i) => row(id, i, false))}
  <//>`
}

/** The start page in one place: the view, the overview's parts, the tiles and shelves of the other views,
 *  what a click on the bridge's core does, and the options that change how things show */
function StartArea({ s, c }) {
  const w = T().settings
  const home = useHome(s, c)
  // the focus view shows what needs you and nothing to choose: no stations, no sections
  const others = home.view !== 'focus'
  return html`<${ViewCard} home=${home} />
    <${DeskCard} home=${home} />
    ${others ? html`<h3 class="label-caps set-group">${w.otherViews}</h3>
      <${StationsCard} home=${home} />
      <${ShelvesCard} home=${home} />
      <${CoreCard} home=${home} />` : null}
    <${DetailsCard} s=${s} c=${c} />`
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

/** Keyboard shortcuts: off unless switched on, kept in this browser only like the colours */
function KeysCard({ s, c }) {
  const w = T().settings
  return html`<${Card} title=${w.keysTitle} intro=${w.keysIntro} head=${html`<span class="muted small">${w.thisBrowser}</span>`}>
    <${Segmented} label=${w.keysTitle} current=${s.ui.shortcuts ? 'on' : 'off'} values=${[['off', w.keysOffWord], ['on', w.keysOnWord]]}
      onPick=${v => c.setShortcuts(v === 'on')} />
  <//>`
}

function DetailsCard({ s, c }) {
  const w = T().settings
  const home = useHome(s, c)
  return html`<${Card} title=${w.detailsTitle} intro=${w.detailsIntro} head=${html`<span class="muted small">${w.everywhere}</span>`}>
    <${SwitchRows} home=${home} ids=${['o:pulse', 'o:today', 'o:trend', 'o:preview', 'o:project', 'o:title']} />
  <//>`
}

const LOOKUP_TOPICS = ['rows', 'act', 'keys', 'trust']

/** To look up, one topic at a time: what the marks of a row say, how acting works, the keys (only while they are on:
 *  mouse first, so off the card says only that they are off, the card above switches them on), what costs tokens and
 *  what stays local. Help in the header opens it on a topic. What each part of a page is for is Explain's, in Help */
function LookupCard({ s }) {
  const t = T()
  const w = t.settings
  // the topic the header's Help picked (app.js openLookup), each pick anew; a click on the card's own switch after it
  const [topic, setTopic] = useState(s.ui.lookupTopic ?? 'rows')
  useEffect(() => { if (s.ui.lookupTopic) setTopic(s.ui.lookupTopic) }, [s.ui.lookupTopic, s.ui.lookupAt])
  const body = topic === 'keys'
    ? s.ui.shortcuts ? html`<p class="muted small">${t.commandHint}</p>
      <dl class="keys">${t.keys.map(([k, v], i) => html`<div key=${i}><dt><kbd>${k}</kbd></dt><dd>${v}</dd></div>`)}</dl>`
      : html`<p class="muted small">${t.keysOff}</p>`
    : html`<dl class="help-text">${t.helpTopics[topic].map(([k, v]) => html`<div key=${k}><dt>${k}</dt><dd>${Array.isArray(v)
      ? html`<ul class="plain help-list">${v.map(x => html`<li key=${x}>${x}</li>`)}</ul>` : v}</dd></div>`)}</dl>`
  return html`<${Card} title=${w.lookupTitle} intro=${w.lookupIntro}>
    <${Segmented} label=${t.help.tabsLabel} current=${topic} values=${LOOKUP_TOPICS.map(id => [id, t.help.tabs[id]])} onPick=${setTopic} />
    <div class="lookup-pane">${body}</div>
  <//>`
}

function LookArea({ s, c }) {
  return html`<${ThemeCard} s=${s} c=${c} /><${KeysCard} s=${s} c=${c} /><${LookupCard} s=${s} /><${TourCard} s=${s} c=${c} />`
}

/** The first-run tour: start it now, and offer it again on the next visit once it ended */
function TourCard({ s, c }) {
  const w = T().tour
  const tr = s.tour
  const busy = !!s.ui.busy?.tour_reset
  return html`<${Card} title=${w.settingsTitle} intro=${tr?.enabled === false ? w.settingsOff : w.settingsIntro}
    head=${html`<${Btn} size="sm" variant="secondary" onClick=${c.tourStart}>${w.again}<//>`}>
    ${tr?.done ? html`<p class="small tour-done"><span class="muted">${w.settingsDone(tr.done.how, tr.done.at)}</span>
      <${Btn} size="xs" variant="ghost" busy=${busy} onClick=${() => c.tourReset()}>${w.reset}<//></p>` : null}
  <//>`
}

// ---------------------------------------------------------------- the features beside the config

/** A value of a feature in words, for its choice and the "changed" tooltip: on or off, a choice by its word */
function featureWord(x, v) {
  const w = T().features
  if (typeof v === 'boolean') return v ? w.on : w.off
  if (v == null) return w.none
  return w.choice[x.id]?.[v] ?? String(v)
}

/** The title and the line of a preset: a built-in one from the text table, one from a file as it names itself */
function presetText(p) {
  const w = T().features
  if (p.builtin) return { title: w.preset[p.id]?.title ?? p.id, description: w.preset[p.id]?.description ?? null }
  return { title: p.title || p.id, description: p.description || null }
}

// The sketches of the Features area, drawn as the start page's views are (style.css .view-thumb-<name>): the
// shapes each picture is made of, in order. A choice draws `<feature>-<value>`, a helper its own id; a name
// without a sketch draws none
const SKETCHES = {
  'flow-off': 'em i i i i', 'flow-beside': 'i i i b', 'flow-only': 'u b i i i',
  'describe-off': 'i i i', 'describe-missing': 'i i i em em', 'describe-stale': 'i i i em em em',
  'chat_layout-classic': 'u i i i b', 'chat_layout-workspaces': 'em em em i i i',
  'files_scope-active': 'em i i', 'files_scope-all': 'em i i i i i',
  launch_model: 'i i i b em', ticker: 'em i i i u', session_guide: 'b i i i',
}

/** One sketch: `family` (a feature id, or flow for the Work through picker) and the value it shows */
function Sketch({ family, value = null, small = false }) {
  const name = value == null ? family : `${family}-${value}`
  const spec = SKETCHES[name]
  if (!spec) return null
  return html`<span class=${`view-thumb view-thumb-${family}${value == null ? '' : ` view-thumb-${name}`}${small ? ' view-thumb-sm' : ''}`} aria-hidden="true">
    ${spec.split(' ').map((tag, k) => html`<${tag} key=${k} />`)}</span>`
}

/** A choice as picker cards, as the view of the start page: per option its sketch, its name and one line; the
 *  option in use marked, a click on another picks it at once */
function PickCards({ label, family, options, current, busy, onPick }) {
  const keys = useRoving()
  return html`<div class=${`view-pick feat-pick is-${options.length}`} role="radiogroup" aria-label=${label} ref=${keys.ref} onKeyDown=${keys.onKeyDown}>
    ${options.map(o => html`<button type="button" key=${o.value} role="radio" aria-checked=${String(current === o.value)} disabled=${busy}
      class=${`view-opt${current === o.value ? ' is-on' : ''}`} onClick=${() => current !== o.value && onPick(o.value)}>
      <${Sketch} family=${family} value=${o.value} />
      <span class="view-name">${o.title}</span>
      ${o.line ? html`<span class="muted small">${o.line}</span>` : null}
    </button>`)}
  </div>`
}

/** The marks beside a feature's name: "set here" where the page's value differs from bridge-config.yaml (the tooltip
 *  says what the config says, in `word`), "AI" where it calls a model */
function featureMarks(x, word = featureWord(x, x.config)) {
  const w = T().features
  return html`${x.overridden ? html`<${Chip} token="info" title=${w.configWas(word)}>${w.changed}<//>` : null}${x.ai
    ? html`<${Chip} cls="feat-ai" title=${w.aiTitle}>${w.ai}<//>` : null}`
}

/** The presets as picker cards: each with a sketch of what it sets (logic.js presetBoard), the one matching now
 *  marked; a click on another asks in the card how many switches it sets, and Apply applies it (features_preset);
 *  never a browser dialog */
function PresetsCard({ f, busy, c }) {
  const w = T().features
  const [asking, setAsking] = useState(null)
  const keys = useRoving()
  const presets = f.presets ?? []
  const on = presetOn(presets, f.items)
  const ask = presets.find(p => p.id === asking) ?? null
  return html`<${Card} title=${w.presetsTitle} intro=${w.presetsIntro}>
    <div class="view-pick" role="radiogroup" aria-label=${w.presetsTitle} ref=${keys.ref} onKeyDown=${keys.onKeyDown}>
      ${presets.map(p => {
        const tx = presetText(p)
        return html`<button type="button" key=${p.id} role="radio" aria-checked=${String(on === p.id)} disabled=${busy}
          class=${`view-opt${on === p.id ? ' is-on' : ''}${asking === p.id ? ' is-asked' : ''}`} onClick=${() => setAsking(on === p.id ? null : p.id)}>
          <span class="view-thumb view-thumb-board" aria-hidden="true">${presetBoard(p, f.items).map(d => html`<i key=${d.id} class=${`is-${d.state}`} />`)}</span>
          <span class="view-name">${tx.title}</span>
          ${tx.description ? html`<span class="muted small">${tx.description}</span>` : null}
          ${!p.builtin && p.scope ? html`<span class="muted small">${w.scope[p.scope] ?? p.scope}</span>` : null}
        </button>`
      })}
    </div>
    ${ask ? html`<div class="feat-ask" role="status">
      <span>${w.ask(presetText(ask).title, presetChanges(ask, f.items).length)}</span>
      <span class="feat-ask-acts">
        <${Btn} size="xs" variant="primary" busy=${busy} onClick=${() => { setAsking(null); c.applyFeaturePreset(ask.id) }}>${w.apply}<//>
        <${Btn} size="xs" variant="secondary" onClick=${() => setAsking(null)}>${w.cancel}<//>
      </span>
    </div>` : null}
  <//>`
}

/** What Ask AI in Files keeps from the model (cockpit.files_search.block), or the warning that nothing is kept */
function BlockLine({ words }) {
  const w = T().features
  return words?.length ? html`<span class="muted small feat-note">${w.blockWords(words.join(', '))}</span>`
    : html`<span class="small feat-note"><${StateLine} token="warning" word=${w.blockNone} /></span>`
}

/** One switch as a row: its name, what it does, its marks, and its control, greyed while the feature it requires is
 *  off, saved at once (features_save). A sub switch of Work through says nothing of its own then, its card says once
 *  that they wait; a requirement elsewhere is named beside the control */
function FeatureRow({ x, items, busy, block, c }) {
  const w = T().features
  const name = w.label[x.id] ?? x.id
  const off = featureDisabled(x, items)
  const na = x.available === false
  const parent = off && !x.sub && !na ? items.find(y => y.id === x.requires) : null
  return html`<div class=${`feat-row${x.sub ? ' feat-sub' : ''}${(x.sub && off) || na ? ' is-off' : ''}`} data-feature=${x.id}>
    <${Row} label=${name} explain=${w.explain[x.id]} mark=${featureMarks(x)} note=${x.id === 'files_search' ? html`<${BlockLine} words=${block} />` : null}>
      ${na ? html`<span class="muted small set-aside">${w.unavailable}</span>` : null}
      ${parent ? html`<span class="muted small set-aside">${w.needs(w.label[parent.id] ?? parent.id)}</span>` : null}
      <${Switch} on=${x.value === true} label=${name} disabled=${busy || off || na} onChange=${v => c.saveFeatures({ [x.id]: v })} />
    <//>
  </div>`
}

/** One choice as a row with its picker cards below its name, never a dropdown */
function ChoiceRow({ x, items, busy, c }) {
  const w = T().features
  const name = w.label[x.id] ?? x.id
  const na = x.available === false
  return html`<div class=${`feat-row${na ? ' is-off' : ''}`} data-feature=${x.id}>
    <${Row} label=${name} explain=${w.explain[x.id]} mark=${featureMarks(x)} wide note=${na ? html`<span class="muted small feat-note">${w.unavailable}</span>` : null}>
      <${PickCards} label=${name} family=${x.id} current=${x.value} busy=${busy || na || featureDisabled(x, items)} onPick=${v => c.saveFeatures({ [x.id]: v })}
        options=${(x.values ?? []).map(v => ({ value: v, title: featureWord(x, v), line: w.choiceLine[x.id]?.[v] }))} />
    <//>
  </div>`
}

/** A helper as a tile, as a station of the start page: its sketch, lit while on, its name and line, the way to its own
 *  area and its switch. Helpers act at once, without a restart */
function HelperTile({ x, items, busy, c }) {
  const t = T()
  const w = t.features
  const name = w.label[x.id] ?? x.id
  const on = x.value === true
  const na = x.available === false
  const area = x.area && AREAS[x.area] ? x.area : null
  return html`<div class=${`view-opt feat-tile${on ? ' is-on' : ''}`} data-feature=${x.id}>
    <${Sketch} family=${x.id} small />
    <span class="set-label">${name}${featureMarks(x)}</span>
    <span class="muted small">${na ? w.unavailable : w.explain[x.id]}</span>
    <span class="feat-tile-foot">
      ${area ? html`<${Btn} size="xs" variant="ghost" title=${w.detailsTitle(t.settings.section[area]?.title ?? area)}
        onClick=${() => c.setSettingsSection(area)}>${w.details}<//>` : null}
      <${Switch} on=${on} label=${name} disabled=${busy || na || featureDisabled(x, items)} onChange=${v => c.saveFeatures({ [x.id]: v })} />
    </span>
  </div>`
}

/** Work through as the headline of the area: the modern way to work, as three picker cards (Lists, Work through,
 *  Only Work through; logic.js flowModeOf), and what it can do as switches under it, waiting while Lists is picked */
function FlowCard({ f, subs, busy, c }) {
  const w = T().features
  const flow = f.items.find(x => x.id === 'flow')
  const only = f.items.find(x => x.id === 'flow_only')
  const mode = flowModeOf(f.items)
  const modes = only ? ['off', 'beside', 'only'] : ['off', 'beside']
  const word = flowModeOf(f.items, 'config')
  const mark = featureMarks({ ...flow, overridden: flow.overridden || !!only?.overridden }, w.flowMode[word]?.title ?? word)
  return html`<${Card} cls="feat-hero" title=${w.flowTitle} intro=${w.flowIntro} head=${mark}>
    <div class="feat-row" data-feature="flow">
      <${PickCards} label=${w.flowModeLabel} family="flow" current=${mode} busy=${busy}
        options=${modes.map(m => ({ value: m, title: w.flowMode[m].title, line: w.flowMode[m].line }))}
        onPick=${m => { const patch = flowModePatch(m, f.items); if (Object.keys(patch).length) c.saveFeatures(patch) }} />
    </div>
    ${subs.length ? html`<h4 class="label-caps set-group feat-subs-title">${w.subsTitle}</h4>
      ${mode === 'off' ? html`<p class="muted small feat-note">${w.subsWait}</p>` : null}
      ${subs.map(x => html`<${FeatureRow} key=${x.id} x=${x} items=${f.items} busy=${busy} c=${c} />`)}` : null}
  <//>`
}

// the line about a restart, by the phase logic.js restartNotice gives
const RESTART_WORDS = { restarting: 'restarting', slow: 'restartSlow', needed: 'restartNeeded', waiting: 'restartWaiting', code: 'restartCode' }

/** What the switches set here amount to, as done and not as a fault: the count in the info tone, and Back to
 *  bridge-config.yaml, which asks in the banner first (features_reset) */
function OverrideBanner({ n, busy, c }) {
  const w = T().features
  const [asking, setAsking] = useState(false)
  return html`<div class="set-banner is-info" role="status">
    <span class="set-banner-text">${asking ? w.resetAsk(n) : w.overridden(n)}</span>
    ${asking ? html`<span class="feat-ask-acts">
        <${Btn} size="xs" variant="primary" busy=${busy} onClick=${() => { setAsking(false); c.resetFeatures() }}>${w.resetApply}<//>
        <${Btn} size="xs" variant="secondary" onClick=${() => setAsking(false)}>${w.cancel}<//>
      </span>`
      : html`<${Btn} size="xs" variant="ghost" busy=${busy} title=${w.resetTitle} onClick=${() => setAsking(true)}>${w.reset}<//>`}
  </div>`
}

/** Features: the switches beside bridge-config.yaml (state.features, features.py), built as the start page's area is:
 *  Work through first as the headline, the presets as picker cards, then one card per group, every choice as picker
 *  cards and the helpers as tiles. A change of a config key acts after a restart, which the server makes itself where
 *  it can (app.js featuresAnswer) */
function FeaturesArea({ s, c }) {
  const t = T()
  const w = t.features
  const f = s.features
  // no state yet says it loads; a state without the block comes from a server older than this area
  if (!f?.items) return html`<${Card} title=${t.settings.section.features.title}><${Empty}>${s.server ? w.noServer : w.loading}<//><//>`
  const notice = restartNotice(s.ui.featuresRestart, f.restart)
  // a features verb in flight, or a restart under way (logic.js featuresLocked): every control waits. A change that
  // only waits for a restart locks nothing
  const verbs = ['features_save', 'features_preset', 'features_reset', 'features_restart']
  const busy = verbs.some(v => s.ui.busy?.[v]) || featuresLocked(s.ui.featuresRestart, f.restart)
  const groups = featureGroups(f.items)
  // Work through and what requires it in its group make the headline card; Only Work through is one of its cards
  const flow = f.items.find(x => x.id === 'flow')
  const subs = flow ? (groups.find(g => g.id === flow.group)?.items ?? []).filter(x => x.sub && x.requires === 'flow' && x.id !== 'flow_only') : []
  const inHero = new Set(flow ? ['flow', 'flow_only', ...subs.map(x => x.id)] : [])
  const rest = groups.map(g => ({ ...g, items: g.items.filter(x => !inHero.has(x.id)) })).filter(g => g.items.length)
  const body = g => {
    const tiles = g.items.filter(x => x.group === 'helpers' && x.kind === 'switch')
    const rows = g.items.filter(x => !tiles.includes(x))
    return html`${tiles.length ? html`<div class=${`view-pick feat-tiles is-${Math.min(tiles.length, 4)}`}>
        ${tiles.map(x => html`<${HelperTile} key=${x.id} x=${x} items=${f.items} busy=${busy} c=${c} />`)}</div>` : null}
      ${rows.map(x => (x.kind === 'choice' ? html`<${ChoiceRow} key=${x.id} x=${x} items=${f.items} busy=${busy} c=${c} />`
        : html`<${FeatureRow} key=${x.id} x=${x} items=${f.items} busy=${busy} block=${f.files_block} c=${c} />`))}`
  }
  return html`
    ${f.overridden > 0 ? html`<${OverrideBanner} n=${f.overridden} busy=${busy} c=${c} />` : null}
    ${notice ? html`<div class=${`banner feat-restart${notice === 'restarting' || notice === 'code' ? ' is-info' : ''}`} role="status">
      <${StateLine} token=${notice === 'restarting' || notice === 'code' ? 'info' : 'warning'} strong word=${w[RESTART_WORDS[notice]]} />
      ${notice === 'waiting' || (notice === 'code' && f.restart?.can) ? html`<${Btn} size="xs" variant="primary" busy=${busy} title=${w.restartNowTitle}
        onClick=${() => c.restartFeatures()}>${w.restartNow}<//>` : null}
    </div>` : restartedLately(f.restart, Date.now()) ? html`<div class="banner feat-restart feat-done is-success" role="status">
      <${StateLine} token="success" strong word=${w.restarted} />
    </div>` : null}
    ${f.warnings?.length ? html`<div class="banner set-warnings" role="status">
      <${StateLine} token="warning" strong word=${w.warnings} />
      <ul class="set-warnings-list">${f.warnings.map((line, i) => html`<li key=${i} class="mono small">${line}</li>`)}</ul>
    </div>` : null}
    ${flow ? html`<${FlowCard} f=${f} subs=${subs} busy=${busy} c=${c} />` : null}
    <${PresetsCard} f=${f} busy=${busy} c=${c} />
    ${rest.map(g => html`<${Card} key=${g.id} title=${w.group[g.id]?.title ?? g.id} intro=${w.group[g.id]?.intro}>${body(g)}<//>`)}`
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

// ---------------------------------------------------------------- the page

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

// ---------------------------------------------------------------- setup

/** The Setup page's sections (briefing.py collect --setup, docs/bridge-cockpit.md, The Setup page): what still keeps
 *  the cockpit from working well, what can be switched on, what is on. Drawn as every page draws a section, so a row
 *  keeps its steps (Let AI do it, Advise, Close, Later, its own steps and their undo) and its key */
function SetupArea({ s, c }) {
  const pages = (s.model?.pages ?? []).filter(p => p.group === 'settings')
  return html`<div class="set-setup">${pages.flatMap(p => (p.sections ?? []).map(sec =>
    html`<${PageSection} key=${`${p.id}/${sec.id}`} page=${p} section=${sec} s=${s} c=${c} />`))}</div>`
}

/** The areas this Bridge offers: Setup only while the view carries its page (cockpit.setup) */
function sectionsOf(s) {
  return (s.model?.pages ?? []).some(p => p.group === 'settings') ? SECTIONS : SECTIONS.filter(id => id !== 'setup')
}

// the news ticker on the start page: its own group from views/ticker.js
const AREAS = { setup: SetupArea, features: FeaturesArea, start: StartArea, look: LookArea, workspaces: WorkspaceSettings, machine: MachineSettings, launch: LaunchArea, ticker: TickerSettings, guide: GuideSettings, boards: BoardSettings }
const AREA_ICONS = { setup: 'bulb', features: 'sliders', start: 'home', look: 'sun', workspaces: 'sliders', machine: 'tabs', launch: 'spark', ticker: 'bell', guide: 'chat', boards: 'sliders' }

/** The page: the areas as a list on the left (a row of buttons on a narrow screen), the one chosen beside it */
/** What a person sets for themselves (access.py): the colours and the language, kept on the server for them, whatever
 *  device they come from. No setting of the Bridge stands here */
function PersonSettings({ s, c }) {
  const t = T()
  const kept = personOf(s).settings ?? {}
  return html`<div class="col col-page settings-page">
    <header class="page-head settings-head"><h2 class="detail-title">${t.settings.title}</h2></header>
    <${Card} title=${t.settings.themeTitle}>
      <${Segmented} label=${t.settings.themeTitle} current=${s.ui.theme} values=${['auto', 'light', 'dark'].map(v => [v, t.theme[v]])}
        onPick=${v => { c.setTheme(v); c.act('person_settings', { theme: v }) }} />
    <//>
    <${Card} title=${t.person.language}>
      <${Segmented} label=${t.person.language} current=${kept.language ?? language()} values=${[['de', 'Deutsch'], ['en', 'English']]}
        onPick=${v => Promise.resolve(c.act('person_settings', { language: v })).then(() => window.location.reload())} />
    <//>
    ${s.personAsk?.manage?.length ? html`<${Card} title=${t.person.chatTitle}>
      ${s.personAsk.manage.map(row => html`<div class="person-engine" key=${row.person}>
        <strong>${row.person}</strong>
        <${Segmented} label=${`${t.person.chatTitle}: ${row.person}`} current=${row.engine}
          values=${[...row.options, 'off'].map(v => [v, t.person.engine[v]])}
          onPick=${v => c.act('ask_engine', { person: row.person, engine: v })} />
        ${row.engine === 'codex' && !row.signed_in ? html`<span class="muted small">${t.person.chatLogin}</span>` : null}
      </div>`)}
    <//>` : null}
  </div>`
}

export function SettingsPage({ s, c }) {
  if (personOf(s)) return html`<${PersonSettings} s=${s} c=${c} />`
  const w = T().settings
  const sections = sectionsOf(s)
  // a stored choice the Bridge no longer offers (Setup without its page) falls back to the start page's area
  const at = sections.includes(s.ui.settingsSection) ? s.ui.settingsSection : 'start'
  const Area = AREAS[at]
  return html`<div class="col col-page settings-page">
    <header class="page-head settings-head">
      <h2 class="detail-title">${w.title}</h2>
      <p class="muted">${w.lead}</p>
    </header>
    <${ConfigWarnings} s=${s} />
    <div class="settings-layout">
      <nav class="settings-nav" aria-label=${w.sectionsLabel}>
        ${sections.map(id => html`<button type="button" key=${id} class=${`settings-nav-item${at === id ? ' is-on' : ''}`}
          aria-current=${at === id ? 'page' : undefined} onClick=${() => c.setSettingsSection(id)}>
          <${Icon} name=${AREA_ICONS[id]} size=${18} />
          <span class="settings-nav-text"><b>${w.section[id].title}</b><small>${w.section[id].sub}</small></span>
        </button>`)}
      </nav>
      <div class="settings-body" key=${at}><${Area} s=${s} c=${c} /></div>
    </div>
  </div>`
}

