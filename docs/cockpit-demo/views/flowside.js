// SPDX-License-Identifier: MIT
// The cockpit, the columns around the middle of Work through (views/flow.js), laid out as cmux lays out a workspace.
// FlowSide, the left column in two levels, like a workspace sidebar that opens a workspace. Level one: Themes or Areas
// on top while the themes are on (logic.js flowMode), then one entry per theme or area that holds a point (its colour,
// its name, how many need you in the warning tone, how many are open), No theme yet or No area last; a click enters
// it. Under the list Order themes again (a regroup within the day's budget) and what the themes run is doing. Level two:
// All themes on top to go back, the name of the theme or area as the way to its overview (marked while the overview
// shows), All and Tick the AI suggestions, then its points grouped Needs you, In progress, Tasks, Reports (logic.js
// pointBand), each with a box, its title (a click opens the point), a dot and a word for its stage, its area and the
// suggestion as a small chip. The boxes are the same selection as the overview's (ui.flowPicked). A theme entered can
// be renamed. On a narrow screen both levels are one select over the middle.
// FlowDetails: the blocks of the task and around it (goal and story, criteria, steps, source, notes and log, result,
// the tab's screen, related), only their headings at first, the goal open; a click pulls one in and the choice stays
// from point to point (ui.flowBlocks); in the overview a line says how they come. It reuses what the files view and
// the item card already draw (views/card.js ItemCard, views/dossier.js ResultList). With the themes on, it also moves
// the point to another theme or a new one.
// For the mouse: no text names a key.
// The rules every component keeps stand at the head of components.js.

import { html, useEffect, useState } from '../vendor/htm-preact-3.1.1.module.js'
import { batchPreselect, detailNeedsLoad, duration, fileResults, flowDrive, flowSuggestion, indexRows, previewText, short } from '../logic.js'
import { T } from '../text.js'
import { describeOf, ItemCard } from './card.js'
import { OriginTag } from './day.js'
import { Segmented } from './detail.js'
import { ResultList } from './dossier.js'
import { bandsOf, pointTone, rowArea } from './flowlist.js'
import { Btn, Dot, Icon } from './parts.js'

/** The words of a side: its theme or area name, else All or None in the words of the mode */
export function sideName(side, mode) {
  const f = T().flow.side
  if (!side || side.id === 'all') return mode === 'themes' ? f.allThemes : f.allAreas
  if (side.id === 'none') return mode === 'themes' ? f.noTheme : f.noArea
  return side.name
}

/** The colour mark of a side: its terminal workspace's colour where it has one, else the tone of its name */
export const SideDot = ({ side }) => html`<span class=${`flow-side-dot tk-${side?.tone ?? 'muted'}`}
  style=${side?.color ? { '--ws-color': side.color } : undefined} aria-hidden="true"></span>`

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

/** Level one: the themes or areas with their counts, a click enters one */
function Level1({ sides, mode, points, s, c }) {
  const f = T().flow.side
  const th = s.themes
  const keys = points.flatMap(x => (x.kind === 'reports' ? x.rows.map(r => r.key) : x.row?.key ? [x.row.key] : []))
  const busy = !!s.ui.flowThemesBusy || !!th?.running || !!s.ui.busy?.['flow:themes']
  const status = mode !== 'themes' ? null : busy ? f.ordering : th?.budget_left === 0 ? f.budget : th?.last_error ? f.failed : null
  return html`${th?.enabled === true ? html`<${Segmented} label=${f.label} values=${[['themes', f.themes], ['areas', f.areas]]} current=${mode}
      onPick=${v => c.flowMode(v)} />` : null}
    <ul class="flow-side-list flow-side-body">${sides.filter(x => x.id !== 'all').map(x => html`<li key=${x.id}>
      <button type="button" class=${`flow-side-item${x.you ? ' is-you' : ''}`} title=${x.you ? f.asks : undefined} onClick=${() => c.flowSide(x.id)}>
        <${SideDot} side=${x} />
        <span class="flow-side-name"><span class="flow-side-label">${sideName(x, mode)}</span>
          ${x.you ? html`<span class="flow-side-you">${f.you(x.you)}</span>` : null}</span>
        <span class="flow-side-open mono muted" title=${f.open(x.open)}>${x.open}</span>
        <${Icon} name="chevronRight" size=${14} />
      </button></li>`)}</ul>
    ${mode === 'themes' ? html`<div class="flow-side-foot flow-side-body">
      <${Btn} size="xs" variant="secondary" icon="spark" busy=${busy} disabled=${!keys.length || th?.budget_left === 0}
        onClick=${() => c.flowThemes('regroup', keys.slice(0, 50))}>${f.regroup}<//>
      ${status ? html`<p class="muted small" role="status">${status}</p>` : null}
    </div>` : null}`
}

/** Level two: back to all, the name as the way to the overview, All and Tick, the points grouped with their boxes */
function Level2({ entered, mode, points, at, view, picked, titleFor, kindFor, s, c }) {
  const t = T()
  const f = t.flow.side
  const [renaming, setRenaming] = useState(false)
  const bands = bandsOf(points)
  const pickable = bands.flatMap(b => b.rows).filter(r => r.row)
  const all = pickable.length > 0 && pickable.every(r => picked.has(r.id))
  const pre = batchPreselect(pickable.map(r => r.row), s)
  const open = view === 'point' ? points[at]?.id : null
  return html`<div class="flow-side-body flow-side-drill">
    <button type="button" class="btn-link flow-side-back" onClick=${() => c.flowSide(null)}>‹ ${sideName(null, mode)}</button>
    <button type="button" class=${`flow-side-title${view === 'overview' ? ' is-on' : ''}`} aria-current=${view === 'overview' ? 'true' : undefined}
      onClick=${() => c.flowOverview()}>
      <${SideDot} side=${entered} /><span class="flow-side-name">${sideName(entered, mode)}</span>
      <span class="flow-side-badge muted">${f.overview}</span>
    </button>
    <div class="flow-side-tools">
      <label class="flow-check"><input type="checkbox" class="flow-side-all" checked=${all} disabled=${!pickable.length}
        onClick=${() => c.flowPick(pickable.map(r => r.id), !all)} /><span>${t.flow.list.pickAll}</span></label>
      <button type="button" class="btn-link flow-side-tick" disabled=${!pre.length} onClick=${() => c.flowPick(pre, true)}>${f.tickAi(pre.length)}</button>
    </div>
    ${bands.map(b => html`<section key=${b.band} class="flow-side-band" aria-label=${t.flow.groups[b.band]}>
      <h3 class="flow-side-group label-caps">${t.flow.groups[b.band]}</h3>
      <ul class="flow-pts">${b.rows.map(r => {
        const sug = r.row ? flowSuggestion(r.row, s) : null
        const tone = pointTone(r.x, s)
        const title = r.row?.title ?? titleFor(r.x)
        const area = rowArea(r)
        const on = open != null && r.x.id === open
        return html`<li key=${r.id} class=${`flow-pt${on ? ' is-on' : ''}${picked.has(r.id) ? ' is-picked' : ''}`}>
          ${r.row ? html`<input type="checkbox" class="flow-pt-pick" aria-label=${t.flow.list.pick(short(title, 60))} checked=${picked.has(r.id)}
            onClick=${() => c.flowPick([r.id], !picked.has(r.id))} />` : html`<span class="flow-pt-pick" aria-hidden="true"></span>`}
          <button type="button" class="flow-pt-open" aria-current=${on ? 'true' : undefined} onClick=${() => c.flowGo(r.x.id, points.indexOf(r.x))}>
            <span class="flow-pt-title">${short(title, 90)}</span>
            <span class="flow-pt-meta"><${Dot} token=${tone.token} pulse=${tone.pulse} /><span>${kindFor(r.x)}${area ? ` · ${area}` : ''}</span>
              ${sug ? html`<span class=${`flow-pt-chip flow-sug-${sug.verb}`}>${f.chip(t.flow.list.verb[sug.verb])}</span>` : null}</span>
          </button>
        </li>`
      })}</ul>
    </section>`)}
    ${mode === 'themes' && entered.theme ? html`<div class="flow-side-foot">
      ${renaming ? html`<${Rename} key=${entered.theme.id} theme=${entered.theme} c=${c} onDone=${() => setRenaming(false)} />`
        : html`<${Btn} size="xs" variant="ghost" onClick=${() => setRenaming(true)}>${f.rename}<//>`}
    </div>` : null}
  </div>`
}

/** The left column: level one the themes or areas, level two the points of the one entered (logic.js flowSides) */
export function FlowSide({ sides, entered, mode, points, all, at, view, picked, titleFor, kindFor, s, c }) {
  const f = T().flow.side
  return html`<aside class="flow-side" aria-label=${f.label}>
    <label class="flow-side-select"><span class="sr-only">${f.pick}</span>
      <select class="input" value=${entered?.id ?? ''} onChange=${e => c.flowSide(e.currentTarget.value || null)}>
        <option value="">${sideName(null, mode)} (${sides[0]?.open ?? 0})</option>
        ${sides.filter(x => x.id !== 'all').map(x => html`<option key=${x.id} value=${x.id}>${sideName(x, mode)} (${x.open})</option>`)}
      </select></label>
    ${entered ? html`<${Level2} entered=${entered} mode=${mode} points=${points} at=${at} view=${view} picked=${picked}
        titleFor=${titleFor} kindFor=${kindFor} s=${s} c=${c} />`
      : html`<${Level1} sides=${sides} mode=${mode} points=${all} s=${s} c=${c} />`}
  </aside>`
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
  if (!x) return html`<aside class="flow-details" aria-label=${f.label}>
    <header class="flow-details-head"><p class="label-caps">${f.label}</p><p class="muted small flow-details-hint">${f.overview}</p></header>
  </aside>`
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
