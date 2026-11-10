// SPDX-License-Identifier: MIT
// The cockpit, a tasks section drawn as a taskboard (profile `view: taskboard` on a `kind: tasks` section): the work
// seen from the tasks rather than the agent tabs. Four columns by who has the next move (Me, Bridge, Waiting on
// others, To review), the streams as a band under them, a box of tidy-up suggestions by fixed rules and a box of the
// agent tabs that carry no task. A card opens a side panel with its goal, its status and its next step and the
// existing verbs of a task: Done (task_close), Waiting until (runs_on), To the idea list (shelve), Hand to the AI
// (start_agent), Go to tab (tab_jump) or Open a tab (collect_context). The one area filter (ui.area) acts on all of
// it. For the mouse: big buttons, no text names a key. The pure part is taskboard.js.
// The rules every component keeps stand at the head of components.js.

import { html, useState } from '../vendor/htm-preact-3.1.1.module.js'
import { indexRows, personOf, TB_COLUMNS, tbBoard, tbCard, tbDecideSlugs, tbInArea, tbLooseTabs, tbTidy } from '../logic.js'
import { T } from '../text.js'
import { jumpToTab } from './home.js'
import { Btn, Empty } from './parts.js'

// the suggestions a person kept, per browser: a convenience, never state that must hold
const KEPT_KEY = 'cockpit.taskboard.kept'

function readKept() {
  try {
    const raw = JSON.parse(globalThis.localStorage?.getItem(KEPT_KEY) ?? '[]')
    return new Set(Array.isArray(raw) ? raw.filter(x => typeof x === 'string') : [])
  } catch {
    return new Set()
  }
}

function writeKept(set) {
  try {
    globalThis.localStorage?.setItem(KEPT_KEY, JSON.stringify([...set].slice(-500)))
  } catch { /* a private window: kept for this visit only */ }
}

/** The tags of a card in words */
function Tags({ card }) {
  const w = T().taskboard.tag
  return html`<span class="tb-tags">${card.tags.map(g => html`<span key=${g.kind}
    class=${`tb-tag tb-tag-${g.kind}${g.soon ? ' is-soon' : ''}`}>${typeof w[g.kind] === 'function' ? w[g.kind](g.value) : g.kind === 'area' ? g.value : w[g.kind]}</span>`)}</span>`
}

function Card({ card, picked, onPick }) {
  const t = T().taskboard
  return html`<button type="button" class=${`tb-card${picked ? ' is-picked' : ''}`} aria-pressed=${String(!!picked)}
    aria-haspopup="dialog" onClick=${() => onPick(card.slug)}>
    <span class="tb-card-title">${card.title}</span>
    <span class=${`tb-card-step${card.step ? '' : ' muted'}`}>${card.step || t.noStep}</span>
    <${Tags} card=${card} />
  </button>`
}

/** The panel of the open card: what it is, and the verbs a task already has; one that does not apply is left out */
function Side({ card, s, c, onClose }) {
  const t = T().taskboard
  const busy = s.ui?.busy ?? {}
  const person = !!personOf(s)
  const after = p => Promise.resolve(p).then(onClose)
  const acts = []
  if (!card.stream) acts.push(html`<${Btn} key="done" variant="primary" busy=${!!busy.task_close}
    onClick=${() => after(c.act('task_close', { keys: [card.key], reason: 'done' }))}>${t.act.done}<//>`)
  acts.push(html`<${Btn} key="wait" onClick=${() => c.askRunsOn([{ key: card.key, title: card.full }])}>${t.act.wait}<//>`)
  if (!card.stream) acts.push(html`<${Btn} key="shelve" busy=${!!busy.shelve} title=${t.actTitle.shelve}
    onClick=${() => after(c.act('shelve', { key: card.key, reason: t.shelveReason }))}>${t.act.shelve}<//>`)
  if (!person) acts.push(html`<${Btn} key="ai" busy=${!!busy.start_agent} title=${t.actTitle.ai}
    onClick=${() => c.act('start_agent', { keys: [card.key] })}>${t.act.ai}<//>`)
  if (card.tab) acts.push(html`<${Btn} key="tab" onClick=${() => jumpToTab(s, c, card.tab)}>${t.act.toTab}<//>`)
  else if (!person) acts.push(html`<${Btn} key="open" busy=${!!busy.collect_context} title=${t.actTitle.openTab}
    onClick=${() => c.act('collect_context', { key: card.key })}>${t.act.openTab}<//>`)
  const missing = html`<span class="muted">${t.side.missing}</span>`
  return html`<aside class="tb-side panel" role="dialog" aria-label=${card.title}>
    <div class="tb-side-head">
      <h3 class="tb-side-title">${card.title}</h3>
      <${Btn} size="sm" onClick=${onClose}>${t.side.close}<//>
    </div>
    ${card.headline || card.full !== card.title ? html`<p class="tb-side-headline muted">${card.headline || card.full}</p>` : null}
    <${Tags} card=${card} />
    <dl class="tb-side-facts">
      <dt class="label-caps">${t.side.goal}</dt><dd>${card.goal || missing}</dd>
      <dt class="label-caps">${t.side.stand}</dt><dd>${card.stand || missing}${card.updated
        ? html` <span class="muted small">(${t.side.updated(card.updated)})</span>` : null}</dd>
      <dt class="label-caps">${t.side.next}</dt><dd>${card.step || missing}</dd>
      ${card.column === 'waiting' && card.who ? html`<dt class="label-caps">${t.side.waitingOn}</dt><dd>${card.who}</dd>` : null}
    </dl>
    <div class="tb-side-acts">${acts}</div>
  </aside>`
}

/** The tidy-up suggestions: what each would do, Yes runs it, Keep hides it in this browser */
function Tidy({ rows, s, c, onKeep, anchor }) {
  const t = T().taskboard
  const busy = s.ui?.busy ?? {}
  const yes = x => (x.verb === 'close' ? c.act('task_close', { keys: [x.key], reason: 'done' })
    : c.act('shelve', { key: x.key, reason: t.shelveReason }))
  const why = x => x.why || (typeof t.tidyRule[x.rule] === 'function' ? t.tidyRule[x.rule](x.days) : t.tidyRule[x.rule] ?? t.tidyRule.extra)
  return html`<section class="tb-box panel panel-pad" id=${anchor} aria-labelledby=${`${anchor}-h`}>
    <h3 class="tb-box-title" id=${`${anchor}-h`}>${t.tidy} <span class="sec-count mono">${rows.length}</span></h3>
    <p class="muted small">${t.tidyHint}</p>
    ${rows.length ? html`<ul class="tb-list">${rows.map(x => html`<li key=${x.id} class="tb-list-row">
      <span class="tb-list-main"><span class="tb-list-verb">${t.tidyVerb[x.verb]}</span>
        <span class="tb-list-title">${x.title}</span><span class="muted small">${why(x)}</span></span>
      <span class="btn-row"><${Btn} variant="primary" busy=${!!busy[x.verb === 'close' ? 'task_close' : 'shelve']} onClick=${() => yes(x)}>${t.yes}<//>
        <${Btn} onClick=${() => onKeep(x.id)}>${t.keep}<//></span>
    </li>`)}</ul>` : html`<${Empty}>${t.tidyNone}<//>`}
  </section>`
}

/** The open agent tabs no task belongs to, each a click away */
function LooseTabs({ tabs, s, c }) {
  const t = T().taskboard
  return html`<section class="tb-box panel panel-pad" aria-label=${t.loose}>
    <h3 class="tb-box-title">${t.loose} <span class="sec-count mono">${tabs.length}</span></h3>
    <p class="muted small">${t.looseHint}</p>
    ${tabs.length ? html`<ul class="tb-list">${tabs.map(x => html`<li key=${x.ref} class="tb-list-row">
      <span class="tb-list-main"><span class="tb-list-verb">${x.workspace || ''}</span>
        <span class="tb-list-title">${x.name || x.ref}</span>${x.last ? html`<span class="muted small">${x.last}</span>` : null}</span>
      <span class="btn-row"><${Btn} onClick=${() => jumpToTab(s, c, x.ref)}>${t.toTab}<//></span>
    </li>`)}</ul>` : html`<${Empty}>${t.looseNone}<//>`}
  </section>`
}

/** A `kind: tasks` section as a taskboard (PageSection, `view: taskboard`). `tidy` on the section is the seam for
 *  suggestions a later check adds (taskboard.js tbTidy, `extra`) */
export function TaskBoard({ items, page, section, s, c }) {
  const t = T().taskboard
  const [pick, setPick] = useState(null)
  const [kept, setKept] = useState(readKept)
  const byKey = indexRows(s.model)
  const tabs = s.tabs?.tabs ?? []
  const area = s.ui?.area || null
  const ctx = { now: s.now || Date.now(), decide: tbDecideSlugs([...byKey.values()]), tabs, byKey }
  const cards = (items ?? []).map(it => tbCard(it, ctx)).filter(x => x.slug && tbInArea(x, area))
  const board = tbBoard(cards)
  const tidy = tbTidy(cards, kept, section?.tidy ?? [])
  const loose = tbLooseTabs(tabs, byKey).filter(x => tbInArea(x, area))
  const open = pick ? cards.find(x => x.slug === pick) : null
  const anchor = `tb-tidy-${page?.id ?? ''}-${section?.id ?? ''}`
  const keep = id => { const next = new Set(kept); next.add(id); writeKept(next); setKept(next) }
  const toggle = slug => setPick(p => (p === slug ? null : slug))
  const card = x => html`<${Card} key=${x.key} card=${x} picked=${pick === x.slug} onPick=${toggle} />`
  return html`<div class=${`tb${open ? ' has-side' : ''}`}>
    <div class="tb-top">
      <${Btn} onClick=${() => globalThis.document?.getElementById(anchor)?.scrollIntoView?.({ block: 'start' })}>${t.tidyBtn(tidy.length)}<//>
    </div>
    <div class="tb-board">${TB_COLUMNS.map(id => html`<section key=${id} class=${`tb-col tb-col-${id}`} aria-labelledby=${`tb-h-${id}`}>
      <h3 class="tb-col-title" id=${`tb-h-${id}`}>${t.columns[id]} <span class="sec-count mono">${board.columns[id].length}</span></h3>
      <p class="tb-col-sub muted small">${t.sub[id]}</p>
      ${board.columns[id].length ? board.columns[id].map(card) : html`<p class="muted small">${t.columnNone}</p>`}
    </section>`)}</div>
    <section class="tb-streams" aria-labelledby="tb-h-streams">
      <h3 class="tb-col-title" id="tb-h-streams">${t.streams} <span class="sec-count mono">${board.streams.length}</span></h3>
      ${board.streams.length ? html`<div class="tb-streams-row">${board.streams.map(card)}</div>` : html`<p class="muted small">${t.streamsNone}</p>`}
    </section>
    <div class="tb-boxes">
      <${Tidy} rows=${tidy} s=${s} c=${c} onKeep=${keep} anchor=${anchor} />
      <${LooseTabs} tabs=${loose} s=${s} c=${c} />
    </div>
    ${open ? html`<${Side} card=${open} s=${s} c=${c} onClose=${() => setPick(null)} />` : null}
  </div>`
}
