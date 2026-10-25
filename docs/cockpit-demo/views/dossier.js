// SPDX-License-Identifier: MIT
// The cockpit, the files view of the work tab (logic.js workViews 'dossier'): one task at a time, large, as a
// file. On top its cover (kind, status, priority, the situation in one sentence with where it comes from and
// its date), under it the next step in the hero of the start page focus with the four verbs, then the file's
// drawers, folded (inbox, history, sections, references, from /api/task), the bar every list walks with
// (back, "2 of 9", Next, keys n and p) and the next files after it, at most six.
// The queue is the one every walk takes (logic.js queueOf, scope 'dossier'): a tab that asks, a result that
// waits, an open inbox item, then the doing and review tasks of every priority. The next step is derived on
// every render and never stored.
// The rules every component keeps stand at the head of components.js.

import { html, useEffect } from '../vendor/htm-preact-3.1.1.module.js'
import {
  detailNeedsLoad, dossierStep, fileQueue, focusIndex, formatDay, prioToken, stepAge, tabOfTask,
} from '../logic.js'
import { T, language } from '../text.js'
import { WorkSwitch } from './day.js'
import { After, Calm, FocusWalk, Hero } from './focus.js'
import { Dot, PrioChip } from './parts.js'

/** The files the view walks: the one queue in its files scope, from the tabs, the model and the returns */
export const dossierQueue = s => fileQueue(s.tabs?.tabs ?? [], s.model, s.now || Date.now())

/** A queue entry as the hero of the focus reads it: always its task row, so a file keeps the verbs of every row;
 *  a tab that asks stands beside them as the row's tab (Hero tabOf) */
function heroEntry(x) {
  return { kind: 'row', id: x.row.key, row: x.row }
}

/** The tab of a file: the one that asks, where that put it in the queue, else the first tab of its task */
const fileTab = (x, s) => (x.reason === 'tab' ? x.tab : tabOfTask(s.tabs?.tabs, x.slug))

/** Where a step comes from and since when, in one line: "from the inbox, for 2 days" */
function stepLine(step, nowMs) {
  if (!step) return null
  const d = T().dossier
  const age = stepAge(step.since, nowMs)
  return [d.from[step.from] ?? step.from, age == null ? null : d.age(age)].filter(Boolean).join(', ')
}

/** The situation of a file in one sentence, always with where it comes from and its date: the headline of
 *  STATUS.md (dated by its last change), else what the triage made of it (dated by its run) */
function Situation({ x, s, data }) {
  const d = T().dossier
  const lang = language()
  const f = data?.front ?? {}
  const gist = s.triage?.items?.[x.row.key]?.gist
  const pick = f.headline ? { text: f.headline, from: d.situationFrom.status, at: f.last_updated }
    : gist ? { text: gist, from: d.situationFrom.triage, at: s.triage?.last?.at ?? null } : null
  if (!pick) return null
  const at = typeof pick.at === 'string' && /^\d{4}-\d{2}-\d{2}/.test(pick.at) ? formatDay(pick.at.slice(0, 10), lang) : null
  return html`<p class="dz-lead">"${pick.text}" <span class="muted small">(${[pick.from, at].filter(Boolean).join(', ')})</span></p>`
}

/** The cover: the slug, its kind, its status, its priority and area, then the situation */
function Cover({ x, s, data }) {
  const t = T()
  const r = x.row
  const kind = data?.front?.type ?? r.task_type
  return html`<header class="dz-cover panel panel-pad">
    <p class="dz-facts">
      <${Dot} token=${prioToken(r.priority)} />
      <span class="mono">${x.slug}</span>
      ${kind ? html`<span class="dz-fact">${kind}</span>` : null}
      ${r.priority ? html`<${PrioChip} priority=${r.priority} />` : null}
      ${r.status ? html`<span class="dz-fact">${t.taskState[r.status] ?? r.status}</span>` : null}
      ${r.area ? html`<span class="dz-fact muted">${r.area}</span>` : null}
    </p>
    <h2 class="dz-title">${r.title}</h2>
    <${Situation} x=${x} s=${s} data=${data} />
  </header>`
}

/** One drawer of the file, folded, its count in its head; none when it has nothing */
function Drawer({ title, n, children }) {
  if (!n) return null
  return html`<details class="dz-drawer"><summary>${title} <span class="sec-count mono">${n}</span></summary>${children}</details>`
}

/** The drawers of a file, from what /api/task holds: its inbox items, its history (log rows), the sections of
 *  STATUS.md and the paths it names as related */
function Drawers({ data }) {
  const d = T().dossier
  if (!data) return null
  const inbox = data.inbox ?? []
  const log = data.log ?? []
  const sections = data.sections ?? []
  const refs = data.related ?? []
  return html`<div class="dz-drawers">
    <${Drawer} title=${d.drawers.inbox} n=${inbox.length}>
      <ul class="entries">${inbox.map(e => html`<li key=${e.id} class="entry">${e.summary}</li>`)}</ul><//>
    <${Drawer} title=${d.drawers.history} n=${log.length}>
      <ol class="log-rows">${log.map((l, i) => html`<li key=${i}><span class="mono muted">${l.at}</span><span>${l.text}</span></li>`)}</ol><//>
    <${Drawer} title=${d.drawers.sections} n=${sections.length}>
      ${sections.map((x, i) => html`<details key=${i}><summary>${x.heading}</summary><p class="pre">${x.text}</p></details>`)}<//>
    <${Drawer} title=${d.drawers.refs} n=${refs.length}>
      <ul class="entries">${refs.map(p => html`<li key=${p} class="entry"><code>${p}</code></li>`)}</ul><//>
  </div>`
}

/** The kind word over a card of the strip after the file in front: why it stands in the queue */
const reasonWord = x => {
  const d = T().dossier
  return x.reason === 'task' ? (x.row.next ? d.from[x.row.next.from] : d.noNext) : d.from[x.reason]
}

export function DossierView({ s, c }) {
  const d = T().dossier
  const queue = dossierQueue(s)
  // held by its task key: once the file in front is settled, the next one moves up into its place
  const i = focusIndex(queue, s.ui.dossierAt)
  const x = queue[i] ?? null
  const entry = x ? s.details?.task?.[x.slug] : null
  const ver = s.model?.collected_ms ?? 0
  useEffect(() => { if (x && detailNeedsLoad(entry, ver)) c.loadTask(x.slug) }, [x?.slug, ver, entry?.stale])
  const data = entry?.data ?? null
  const nowMs = s.now || Date.now()
  const step = x ? dossierStep(x) : null
  const hero = x ? heroEntry(x) : null
  return html`<div class="col col-page dz">
    <header class="page-head"><${WorkSwitch} s=${s} c=${c} /></header>
    ${x ? html`
      <${Cover} key=${`c${x.id}`} x=${x} s=${s} data=${data} />
      <${Hero} key=${x.id} x=${hero} n=${queue.length} tabOf=${() => fileTab(x, s)} s=${s} c=${c}
        title=${step?.what ?? d.noNext} kindWord=${d.next} sub=${stepLine(step, nowMs)} />
      <${Drawers} data=${data} />
      <${FocusWalk} queue=${queue} i=${i} s=${s} c=${c} walk=${c.dossierWalk} />
      <${After} queue=${queue} i=${i} onPick=${k => c.dossierWalk(queue[k].id, k)} s=${s} title=${d.after} kindWord=${reasonWord} />`
    : html`<${Calm} s=${s} c=${c} title=${d.empty} sub=${d.emptySub} action=${false} />`}
  </div>`
}
