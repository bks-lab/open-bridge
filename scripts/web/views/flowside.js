// SPDX-License-Identifier: MIT
// The cockpit, the columns around the card of Work through (views/flow.js), laid out as cmux lays out a workspace:
// on the left the themes (or the areas) like its workspace sidebar, over the card its open points like its tab bar,
// on the right the details of the point in front to pull in by click.
// FlowSide: Themes or Areas on top while the themes are on (logic.js flowMode), then All, one entry per theme or area
// that holds a point (its colour, its name, how many need you in the warning tone, how many are open), and No theme
// yet or No area last; a theme or area where something needs you carries the warning dot. Under the list Order themes
// again (a regroup within the day's budget) and what the themes run is doing; a theme picked can be renamed. On a
// narrow screen the list is a select over the tabs. FlowTabs: the points of the group picked in the queue's fixed
// order, each with a dot for its kind and stage; the row wraps, so none is ever cut off. FlowDetails: the blocks of the
// task and around it (goal and story, criteria, steps, source, notes and log, result, the tab's screen, related),
// only their headings at first, the goal open; a click pulls one in and the choice stays from point to point
// (ui.flowBlocks). It reuses what the files view and the item card already draw (views/card.js ItemCard,
// views/dossier.js ResultList). With the themes on, it also moves the point to another theme or a new one.
// For the mouse: no text names a key.
// The rules every component keeps stand at the head of components.js.

import { html, useEffect, useState } from '../vendor/htm-preact-3.1.1.module.js'
import { detailNeedsLoad, duration, fileResults, flowDrive, FLOW_YOU, indexRows, previewText, short, stageTone } from '../logic.js'
import { T } from '../text.js'
import { describeOf, ItemCard } from './card.js'
import { OriginTag } from './day.js'
import { Segmented } from './detail.js'
import { ResultList } from './dossier.js'
import { Btn, Dot, Icon, useRoving } from './parts.js'

/** The words of a side: its theme or area name, else All or None in the words of the mode */
export function sideName(side, mode) {
  const f = T().flow.side
  if (side.id === 'all') return mode === 'themes' ? f.allThemes : f.allAreas
  if (side.id === 'none') return mode === 'themes' ? f.noTheme : f.noArea
  return side.name
}

/** Rename a theme a person picked: a field with Save; the name is a person's from then on (themes.py rename) */
function Rename({ theme, c, onDone }) {
  const f = T().flow.side
  const [name, setName] = useState(theme.name)
  const v = name.trim()
  const save = () => { if (v && v !== theme.name) c.flowThemeRename(theme.id, v); onDone() }
  return html`<form class="flow-side-rename" onSubmit=${e => { e.preventDefault(); save() }}>
    <label class="label-caps" for="flow-rename">${f.renameLabel}</label>
    <input id="flow-rename" class="input" type="text" maxlength="40" value=${name} onInput=${e => setName(e.currentTarget.value)} />
    <span class="verbbar-acts"><${Btn} size="xs" variant="primary" disabled=${!v} onClick=${save}>${f.save}<//>
      <${Btn} size="xs" variant="ghost" onClick=${onDone}>${f.cancel}<//></span>
  </form>`
}

/** The left column: the themes or areas with their counts, a click picks one (logic.js flowSides) */
export function FlowSide({ sides, side, mode, points, s, c }) {
  const t = T()
  const f = t.flow.side
  const th = s.themes
  const [renaming, setRenaming] = useState(false)
  const picked = sides.find(x => x.id === side) ?? sides[0]
  const keys = points.flatMap(x => (x.kind === 'reports' ? x.rows.map(r => r.key) : x.row?.key ? [x.row.key] : []))
  const busy = !!s.ui.flowThemesBusy || !!th?.running || !!s.ui.busy?.['flow:themes']
  const status = mode !== 'themes' ? null : busy ? f.ordering : th?.budget_left === 0 ? f.budget : th?.last_error ? f.failed : null
  return html`<aside class="flow-side" aria-label=${f.label}>
    ${th?.enabled === true ? html`<${Segmented} label=${f.label} values=${[['themes', f.themes], ['areas', f.areas]]} current=${mode}
      onPick=${v => c.flowMode(v)} />` : null}
    <label class="flow-side-select"><span class="sr-only">${f.pick}</span>
      <select class="input" value=${picked.id} onChange=${e => c.flowSide(e.currentTarget.value)}>
        ${sides.map(x => html`<option key=${x.id} value=${x.id}>${sideName(x, mode)} (${x.open})</option>`)}
      </select></label>
    <ul class="flow-side-list">${sides.map(x => {
      const on = x.id === picked.id
      return html`<li key=${x.id}><button type="button" class=${`flow-side-item${on ? ' is-on' : ''}${x.you ? ' is-you' : ''}`}
        aria-current=${on ? 'true' : undefined} title=${x.you ? f.asks : undefined} onClick=${() => c.flowSide(x.id)}>
        ${x.id === 'all' ? html`<${Icon} name="tabs" size=${14} />`
          : html`<span class=${`flow-side-dot tk-${x.tone ?? 'muted'}`} style=${x.color ? { '--ws-color': x.color } : undefined} aria-hidden="true"></span>`}
        <span class="flow-side-name">${sideName(x, mode)}</span>
        <span class="flow-side-counts">
          ${x.you ? html`<span class="flow-side-you" title=${f.you(x.you)}><${Dot} token="warning" /><span class="mono">${x.you}</span></span>` : null}
          <span class="mono muted" title=${f.open(x.open)}>${x.open}</span>
        </span>
      </button></li>`
    })}</ul>
    ${mode === 'themes' ? html`<div class="flow-side-foot">
      ${picked.theme && !renaming ? html`<${Btn} size="xs" variant="ghost" onClick=${() => setRenaming(true)}>${f.rename}<//>` : null}
      ${picked.theme && renaming ? html`<${Rename} key=${picked.theme.id} theme=${picked.theme} c=${c} onDone=${() => setRenaming(false)} />` : null}
      <${Btn} size="xs" variant="secondary" icon="spark" busy=${busy} disabled=${!keys.length || th?.budget_left === 0}
        onClick=${() => c.flowThemes('regroup', keys.slice(0, 50))}>${f.regroup}<//>
      ${status ? html`<p class="muted small" role="status">${status}</p>` : null}
    </div>` : null}
  </aside>`
}

/** A point's dot: what it is and where it stands, as the agent tabs show theirs */
function pointTone(x, s) {
  if (x.group === 'doing') {
    const d = flowDrive(x, s)
    return { token: d.by === 'none' ? 'muted' : stageTone(d.stage === 'needs-you' ? 'asks' : d.stage ?? 'working'), pulse: d.stage === 'working' }
  }
  if (FLOW_YOU.includes(x.group)) return { token: x.group === 'result' ? 'success' : x.group === 'lost' ? 'danger' : 'warning', pulse: x.group === 'asks' }
  return { token: x.group === 'reports' ? 'muted' : 'info', pulse: false }
}

/** Over the card: the points of the group picked as tabs, in the queue's order, a thin line between its groups */
export function FlowTabs({ points, i, titleFor, kindFor, go, s }) {
  const f = T().flow
  const keys = useRoving()
  return html`<div class="flow-tabs" role="tablist" aria-label=${f.tabs.label} ref=${keys.ref} onKeyDown=${keys.onKeyDown}>
    ${points.map((x, k) => {
      const tone = pointTone(x, s)
      const sep = k > 0 && points[k - 1].group !== x.group && (FLOW_YOU.includes(points[k - 1].group) !== FLOW_YOU.includes(x.group) || x.group !== 'doing')
      return html`${sep ? html`<span key=${`sep-${x.id}`} class="flow-tabs-sep" aria-hidden="true"></span>` : null}
        <button key=${x.id} type="button" role="tab" aria-selected=${String(k === i)} class=${`flow-tab${k === i ? ' is-on' : ''}`}
          title=${`${kindFor(x)}: ${titleFor(x)}`} onClick=${() => go(k)}>
          <${Dot} token=${tone.token} pulse=${tone.pulse} /><span class="flow-tab-title">${short(titleFor(x), 34)}</span>
        </button>`
    })}
  </div>`
}

// the blocks of the right column, in the order they stand; the first one stands open at first (app.js flowBlocks)
export const DETAIL_BLOCKS = ['goal', 'criteria', 'steps', 'source', 'notes', 'result', 'screen', 'related']
const STEP_RE = /^\s*[-*] \[( |x|X)\] (.+)$/

/** The steps of a task: the checklist lines of its STATUS.md, as they stand (read only: they are ticked there) */
function stepsOf(data) {
  return (data?.sections ?? []).flatMap(sec => String(sec.text ?? '').split('\n').map(l => STEP_RE.exec(l)).filter(Boolean)
    .map(m => ({ done: m[1] !== ' ', text: m[2].trim() })))
}

/** The blocks a point has: a task all of them, an inbox item its card, its source and notes, a tab alone its screen */
function blocksOf(x, tab) {
  if (x.kind === 'reports') return ['source', 'notes']
  const row = x.row
  if (!row) return tab ? ['screen'] : []
  const task = !!row.task && !row.inbox_id
  return DETAIL_BLOCKS.filter(b => (b === 'screen' ? !!tab : ['steps', 'result', 'related'].includes(b) ? task || !!row.task : true))
}

/** The theme of the point, by hand: another theme of the list, or a new one with a name of the person's */
function ThemePick({ row, s, c }) {
  const f = T().flow.side
  const th = s.themes
  const [making, setMaking] = useState(false)
  const [name, setName] = useState('')
  const now = th?.assign?.[row.key] ?? ''
  const id = `flow-theme-${row.key}`
  if (making) {
    const v = name.trim()
    const save = () => { if (v) c.flowThemeNew(row.key, v); setMaking(false); setName('') }
    return html`<form class="flow-theme-pick" onSubmit=${e => { e.preventDefault(); save() }}>
      <label class="label-caps" for=${id}>${f.newName}</label>
      <input id=${id} class="input" type="text" maxlength="40" value=${name} onInput=${e => setName(e.currentTarget.value)} />
      <span class="verbbar-acts"><${Btn} size="xs" variant="primary" disabled=${!v} onClick=${save}>${f.save}<//>
        <${Btn} size="xs" variant="ghost" onClick=${() => setMaking(false)}>${f.cancel}<//></span>
    </form>`
  }
  return html`<div class="flow-theme-pick">
    <label class="label-caps" for=${id}>${f.moveLabel}</label>
    <span class="field-row"><select id=${id} class="input" value=${now} onChange=${e => {
      const v = e.currentTarget.value
      if (v === '+') setMaking(true)
      else if (v && v !== now) c.flowThemeMove(row.key, v)
    }}>
      ${now ? null : html`<option value="">${f.noTheme}</option>`}
      ${(th?.themes ?? []).map(x => html`<option key=${x.id} value=${x.id}>${x.name}</option>`)}
      <option value="+">${f.newTheme}</option>
    </select></span>
  </div>`
}

/** One block: its heading a button that pulls it in or folds it, its body only while it is open */
function Block({ id, open, c, children }) {
  const f = T().flow.details
  return html`<section class=${`flow-block${open ? ' is-open' : ''}`}>
    <h3 class="flow-block-head"><button type="button" aria-expanded=${String(open)} onClick=${() => c.flowBlock(id)}>
      <span>${f.blocks[id]}</span><${Icon} name=${open ? 'chevronUp' : 'chevronDown'} size=${14} /></button></h3>
    ${open ? html`<div class="flow-block-body">${children}</div>` : null}
  </section>`
}

const SKIP_BUT = keep => ['summary', 'goal', 'story', 'acceptance', 'next', 'state', 'owner', 'priority', 'due', 'area', 'source',
  'progress', 'gaps', 'describe'].filter(k => !keep.includes(k))

/** The right column: the details of the point in front, block by block (DETAIL_BLOCKS) */
export function FlowDetails({ x, s, c }) {
  const t = T()
  const f = t.flow.details
  const row = x?.row ?? null
  const slug = row?.task ?? null
  const entry = slug ? s.details?.task?.[slug] : null
  const ver = s.model?.collected_ms ?? 0
  const open = s.ui.flowBlocks ?? ['goal']
  const tab = x ? x.tab ?? (x.group === 'doing' ? flowDrive(x, s).tab : null) : null
  const blocks = x ? blocksOf(x, tab) : []
  const wantsTask = !!slug && blocks.some(b => open.includes(b) && b !== 'screen')
  useEffect(() => { if (wantsTask && detailNeedsLoad(entry, ver)) c.loadTask(slug) }, [slug, wantsTask, ver, entry?.stale])
  if (!x) return html`<aside class="flow-details" aria-label=${f.label}></aside>`
  const data = entry?.data ?? null
  const card = data?.card ?? row?.card ?? null
  const key = row?.key ?? null
  const d = key ? describeOf(s, key, data?.describe, row?.describe) : null
  const loading = slug && !data && entry?.status !== 'error'
  const none = id => html`<p class="muted small">${loading ? f.loading : f.none[id]}</p>`
  const nowMs = s.now || Date.now()
  const body = id => {
    if (id === 'goal' || id === 'criteria') {
      const keep = id === 'goal' ? ['goal', 'story', 'describe'] : ['acceptance']
      const has = id === 'goal' ? card?.goal || card?.story : (card?.acceptance ?? []).length
      return html`${card ? html`<${ItemCard} card=${card} d=${d} dkey=${key} s=${s} c=${c} skip=${SKIP_BUT(keep)} cls="flow-card-brief" />` : null}
        ${has ? null : none(id)}`
    }
    if (id === 'steps') {
      const steps = stepsOf(data)
      return steps.length ? html`<ul class="flow-steps">${steps.map((st, k) => html`<li key=${k} class=${st.done ? 'is-done' : ''}>
        <span class="flow-step-mark mono">${st.done ? f.done : f.todo}</span> <span>${st.text}</span></li>`)}</ul>` : none(id)
    }
    if (id === 'source') {
      const related = data?.related ?? []
      const url = row?.url ?? row?.link ?? null
      const rows = x.kind === 'reports' ? x.rows : row ? [row] : []
      return html`<div class="flow-source">
        ${rows.map(r => html`<p key=${r.key} class="small"><${OriginTag} row=${r} /> ${x.kind === 'reports' ? short(r.title, 60) : null}</p>`)}
        ${url ? html`<p class="small"><a href=${url} target="_blank" rel="noopener noreferrer">${f.open}</a> <span class="muted">${short(url, 60)}</span></p>` : null}
        ${related.length ? html`<ul class="entries">${related.map(p => html`<li key=${p} class="entry"><code>${p}</code></li>`)}</ul>` : null}
        ${!rows.length && !url && !related.length ? none(id) : null}
      </div>`
    }
    if (id === 'notes') {
      const log = (data?.log ?? []).slice(-6)
      const inbox = data?.inbox ?? []
      const why = x.kind === 'reports' ? x.rows.flatMap(r => r.why ?? []) : row?.why ?? []
      if (!log.length && !inbox.length && !why.length) return none(id)
      return html`${why.length ? html`<ul class="fx-why">${why.slice(0, 4).map(w => html`<li key=${w}>${w}</li>`)}</ul>` : null}
        ${inbox.length ? html`<ul class="entries">${inbox.map(e => html`<li key=${e.id} class="entry"><span>${e.summary}</span></li>`)}</ul>` : null}
        ${log.length ? html`<ol class="log-rows">${log.map((l, k) => html`<li key=${k}><span class="mono muted">${l.at}</span><span>${l.text}</span></li>`)}</ol>` : null}`
    }
    if (id === 'result') {
      const res = slug ? fileResults(slug, s.model, s.tabs?.tabs, nowMs, s.sessions?.runs) : null
      const said = x.start?.result?.text ?? null
      if (!said && !(res && (res.returns.length || res.runs.length))) return none(id)
      return html`${said ? html`<p class="flow-answer small">${short(said, 400)}</p>` : null}${res ? html`<${ResultList} res=${res} s=${s} c=${c} />` : null}`
    }
    if (id === 'screen') {
      const lines = String(tab?.last ?? '').split('\n').map(previewText).filter(Boolean).slice(-12)
      return html`${lines.length ? html`<pre class="fx-screen mono">${lines.join('\n')}</pre>` : html`<p class="muted small">${f.none.screen}</p>`}
        ${tab ? html`<p class="muted small">${tab.name} · ${duration(nowMs - (tab.since_ms || nowMs))}</p>
          <${Btn} size="xs" variant="secondary" onClick=${() => c.openTabView(tab.ref)}>${f.view}<//>` : null}`
    }
    // related: the other rows of the same task (its inbox items, a page item), as they stand in the model
    const others = slug ? [...indexRows(s.model).values()].filter(r => r.task === slug && r.key !== key) : []
    return others.length ? html`<ul class="entries">${others.map(r => html`<li key=${r.key} class="entry"><span>${short(r.title, 80)}</span>
      <span class="entry-tags"><${OriginTag} row=${r} /></span></li>`)}</ul>` : none(id)
  }
  return html`<aside class="flow-details" aria-label=${f.label}>
    <header class="flow-details-head"><p class="label-caps">${f.label}</p><p class="muted small">${f.hint}</p></header>
    ${s.themes?.enabled === true && key && x.kind !== 'reports' ? html`<${ThemePick} key=${key} row=${row} s=${s} c=${c} />` : null}
    ${blocks.map(id => html`<${Block} key=${id} id=${id} open=${open.includes(id)} c=${c}>${open.includes(id) ? body(id) : null}<//>`)}
  </aside>`
}
