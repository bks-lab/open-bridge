// SPDX-License-Identifier: MIT
// The cockpit, the files view of the work tab (logic.js workViews 'dossier'): one task at a time, large, as a
// file. On top its cover (kind, status, priority, the situation in one sentence with where it comes from and
// its date), under it the next step in the hero of the start page focus with the four verbs, then the file's
// drawers, folded (inbox, history, sections, references, from /api/task), the bar every list walks with
// (back, "2 of 9", Next, keys n and p) and the next files after it, at most six.
// The queue is the one every walk takes (logic.js queueOf, scope 'dossier'): a tab that asks, a result that
// waits, an open inbox item, then the doing and review tasks of every priority. The next step is derived on
// every render and never stored.
// On top a search field of its own (/api/find): the results by file, best first, a click opens a file, a
// closed one too, beside the queue (ui.dossierOpen) with the way back. A question asked in a file carries its
// folder and cover as data (logic.js fileContext) and names an open task, never a closed one; with no file
// open, a question about the results carries the result list (findContext). A file whose next step nobody
// names offers a suggestion: one read-only question, its answer shown, written to STATUS.md only when the
// person takes it over (verb task_next).
// The rules every component keeps stand at the head of components.js.

import { html, useEffect, useState } from '../vendor/htm-preact-3.1.1.module.js'
import {
  detailNeedsLoad, dossierStep, fileContext, fileFacts, fileQueue, findContext, focusIndex, formatDay, prioToken,
  stepAge, suggestedStep, tabOfTask,
} from '../logic.js'
import { T, language } from '../text.js'
import { WorkSwitch } from './day.js'
import { After, Calm, FocusWalk, Hero } from './focus.js'
import { Btn, Dot, PrioChip } from './parts.js'

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

/** The cover: the slug, where it lies when that is not the queue (a closed file), its kind, its status, its
 *  priority and area, then the situation */
function Cover({ x, s, data, place = null }) {
  const t = T()
  const r = x.row
  const kind = data?.front?.type ?? r.task_type
  return html`<header class="dz-cover panel panel-pad">
    <p class="dz-facts">
      <${Dot} token=${prioToken(r.priority)} />
      <span class="mono">${x.slug}</span>
      ${place ? html`<span class="dz-fact">${place}</span>` : null}
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

/** One line to ask in: the words go to c.askFile with the context as data and the task it names (or none) */
function AskBox({ cls, label, placeholder, context, task, s, c }) {
  const d = T().dossier
  const [text, setText] = useState('')
  const submit = async e => {
    e.preventDefault()
    const q = text.trim()
    if (q && await c.askFile(q, context, task)) setText('')
  }
  return html`<form class=${`dz-askbox ${cls}`} onSubmit=${submit}>
    <label class="sr-only" for=${`${cls}-input`}>${label}</label>
    <input id=${`${cls}-input`} class="input" type="text" maxlength="4000" autocomplete="off" placeholder=${placeholder}
      value=${text} onInput=${e => setText(e.currentTarget.value)} />
    <${Btn} variant="secondary" size="sm" busy=${!!s.ui.busy?.['ask:free']} onClick=${submit}>${d.ask.button}<//>
  </form>`
}

/** The search field of the files view, and what it found: by file, best first, each with its kind, its count of
 *  hits and its first lines; a file opens with a click, a log or archive line has no file to open */
function Find({ s, c, open }) {
  const d = T().dossier
  const f = d.find
  const [text, setText] = useState(s.find?.q ?? '')
  const submit = e => {
    e.preventDefault()
    const q = text.replace(/\s+/g, ' ').trim()
    if (q) c.findFiles(q)
  }
  const found = s.find ?? null
  const groups = found?.status === 'ok' ? found.data?.groups ?? [] : []
  const note = !found ? null : found.status === 'loading' ? f.loading : found.status === 'error' ? f.failed(found.error ?? '')
    : found.status === 'tooShort' ? f.tooShort : !groups.length ? f.none(found.q) : found.data.truncated ? f.shown(groups.length, found.data.total) : null
  return html`<section class="dz-search">
    <form class="dz-find" role="search" onSubmit=${submit}>
      <label class="sr-only" for="dossier-find">${f.label}</label>
      <input id="dossier-find" class="input" type="search" autocomplete="off" spellcheck="false" maxlength="200"
        placeholder=${f.placeholder} value=${text} onInput=${e => setText(e.currentTarget.value)} />
      <${Btn} variant="secondary" size="sm" busy=${found?.status === 'loading'} onClick=${submit}>${f.button}<//>
      ${found ? html`<${Btn} variant="ghost" size="sm" onClick=${() => { setText(''); c.clearFind() }}>${f.clear}<//>` : null}
    </form>
    ${note ? html`<p class="dz-find-note muted small" role="status">${note}</p>` : null}
    ${groups.length ? html`<ol class="dz-found">${groups.map(g => html`<li key=${g.slug ?? g.path} class="dz-found-item">
      <p class="dz-found-head">
        ${g.slug ? html`<button type="button" class="dz-found-open btn-link" onClick=${() => c.openFile(g.slug)}>${g.slug}</button>`
          : html`<span class="mono">${g.path}</span>`}
        <span class="dz-fact">${f.kind[g.kind] ?? g.kind}</span>
        ${g.slug ? html`<span class="dz-found-title">${g.title}</span>` : null}
        <span class="muted small">${f.hits(g.count)}</span>
      </p>
      ${(g.hits ?? []).slice(0, 2).map(h => html`<p key=${`${h.path}:${h.line}`} class="dz-found-hit small"><span class="mono muted">${h.path.split('/').pop()}:${h.line}</span> ${h.text}</p>`)}
    </li>`)}</ol>` : null}
    ${groups.length && !open ? html`<${AskBox} cls="dz-ask-results" label=${d.ask.results} placeholder=${d.ask.resultsPlaceholder}
      context=${findContext(found.data, language())} task=${null} s=${s} c=${c} />` : null}
  </section>`
}

/** No step known: a suggestion on request. One read-only question (c.suggestNext), its answer shown, written
 *  to STATUS.md only on Take over (c.takeNext, verb task_next) */
function Suggest({ x, s, c, context }) {
  const d = T().dossier.suggest
  const mine = s.ui.suggest?.slug === x.slug ? s.ui.suggest : null
  if (!mine) {
    return html`<div class="dz-suggest"><${Btn} variant="secondary" size="sm" icon="spark"
      busy=${!!s.ui.busy?.['ask:suggest']} onClick=${() => c.suggestNext(x.slug, context)}>${d.button}<//></div>`
  }
  const conv = (s.quick?.convs ?? []).find(q => q.id === mine.conv)
  const last = conv?.turns?.[conv.turns.length - 1]
  const step = last?.a ? suggestedStep(last.a) : null
  if (!conv || conv.running || (!last?.a && !last?.error)) {
    return html`<div class="dz-suggest" role="status"><p class="muted small">${d.running}</p></div>`
  }
  return html`<div class="dz-suggest panel panel-pad" role="status">
    ${step ? html`<p class="eyebrow">${d.title}</p><p class="dz-suggest-step">${step}</p><p class="muted small">${d.note}</p>`
      : html`<p class="muted small">${d.failed}</p>`}
    <div class="dz-suggest-acts">
      ${step ? html`<${Btn} variant="primary" size="sm" onClick=${() => c.takeNext(x.row.key, step)}>${d.take}<//>` : null}
      <${Btn} variant="ghost" size="sm" onClick=${() => c.dismissSuggest()}>${d.dismiss}<//>
    </div>
  </div>`
}

/** A file opened from the search, beside the queue: its cover from /api/task, the next step its STATUS.md
 *  names, its drawers, a question to it, and the way back. A closed file is never named as the task of a
 *  question (quick.py would archive the chat at once); none of the verbs, it is not in the queue */
function OpenFile({ slug, s, c }) {
  const d = T().dossier
  const entry = s.details?.task?.[slug]
  const ver = s.model?.collected_ms ?? 0
  useEffect(() => { if (detailNeedsLoad(entry, ver)) c.loadTask(slug) }, [slug, ver, entry?.stale])
  const data = entry?.data ?? null
  const row = (s.model?.sections ?? []).flatMap(x => x.rows ?? []).find(r => r.key === `task:${slug}`) ?? null
  const facts = fileFacts(slug, data, row)
  const x = { id: `task:${slug}`, slug, row: { key: `task:${slug}`, title: facts.title, priority: facts.priority,
    status: facts.status, task_type: facts.type, area: row?.area ?? null } }
  return html`<div class="dz-open">
    <p class="dz-opened muted small">${d.opened} <${Btn} variant="ghost" size="sm" icon="back" onClick=${() => c.closeFile()}>${d.back}<//></p>
    ${entry?.status === 'error' ? html`<p class="muted" role="status">${d.noFile}</p>` : html`
      <${Cover} x=${x} s=${s} data=${data} place=${facts.kind === 'task' ? null : d.find.kind[facts.kind]} />
      ${facts.next ? html`<p class="dz-next"><span class="eyebrow">${d.next}</span> ${facts.next}</p>` : null}
      <${Drawers} data=${data} />
      <${AskBox} cls="dz-ask" label=${d.ask.label} placeholder=${d.ask.placeholder} context=${fileContext(facts, language())}
        task=${facts.kind === 'done' ? null : slug} s=${s} c=${c} />`}
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
  const open = s.ui.dossierOpen ?? null
  const context = x ? fileContext(fileFacts(x.slug, data, x.row), language()) : ''
  return html`<div class="col col-page dz">
    <header class="page-head"><${WorkSwitch} s=${s} c=${c} /></header>
    <${Find} s=${s} c=${c} open=${open} />
    ${open ? html`<${OpenFile} key=${open} slug=${open} s=${s} c=${c} />` : x ? html`
      <${Cover} key=${`c${x.id}`} x=${x} s=${s} data=${data} />
      <${Hero} key=${x.id} x=${hero} n=${queue.length} tabOf=${() => fileTab(x, s)} s=${s} c=${c}
        title=${step?.what ?? d.noNext} kindWord=${d.next} sub=${stepLine(step, nowMs)} />
      ${step ? null : html`<${Suggest} key=${`s${x.id}`} x=${x} s=${s} c=${c} context=${context} />`}
      <${Drawers} data=${data} />
      <${AskBox} key=${`a${x.id}`} cls="dz-ask" label=${d.ask.label} placeholder=${d.ask.placeholder} context=${context}
        task=${x.slug} s=${s} c=${c} />
      <${FocusWalk} queue=${queue} i=${i} s=${s} c=${c} walk=${c.dossierWalk} />
      <${After} queue=${queue} i=${i} onPick=${k => c.dossierWalk(queue[k].id, k)} s=${s} title=${d.after} kindWord=${reasonWord} />`
    : html`<${Calm} s=${s} c=${c} title=${d.empty} sub=${d.emptySub} action=${false} />`}
  </div>`
}
