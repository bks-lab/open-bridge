// SPDX-License-Identifier: MIT
// The cockpit, the files view of the work tab (logic.js workViews 'dossier'): one task at a time, large, as a
// file. On top its cover (kind, status, priority, the situation in one sentence with where it comes from and
// its date), under it the next step in the hero of the start page focus with the four verbs, then the file's
// drawers, folded (result, inbox, history, files, references, sections), the bar every list walks with
// (back, "2 of 9", Next, keys n and p) and the next files after it, at most six.
// The Result drawer holds what came back for the task (logic.js fileResults): the starts of the return channel
// as the start page shows them (ReturnCard, with its ways on and its forget), and the workflow runs the server
// bound to the task (sessions state `runs`), each with why it belongs here; a finished run not yet checked
// waits as the file's result until Checked (verb run_seen), and the drawer stands open while anything waits.
// The Files drawer lists the folder besides STATUS.md (/api/task `files`) and reads a file in place on a click
// (/api/task?file=), Markdown as prose, anything else as it stands.
// The queue is the one every walk takes (logic.js queueOf, scope 'dossier'): a tab that asks, a result that
// waits, an open inbox item, then the doing and review tasks of every priority. The next step is derived on
// every render and never stored.
// On top a search field of its own (/api/find): the results by file, best first, a click opens a file, a
// closed one too, beside the queue (ui.dossierOpen) with the way back. A question asked in a file carries its
// folder and cover as data (logic.js fileContext) and names an open task, never a closed one; with no file
// open, a question about the results carries the result list (findContext). A file whose next step nobody
// names offers a suggestion: one read-only question, its answer shown, written to STATUS.md only when the
// person takes it over (verb task_set_next).
// The rules every component keeps stand at the head of components.js.

import { html, useEffect, useRef, useState } from '../vendor/htm-preact-3.1.1.module.js'
import {
  detailNeedsLoad, dossierStep, duration, fileContext, fileFacts, fileQueue, fileResults, findContext, focusIndex, formatDay,
  prioToken, short, stepAge, suggestedStep, tabOfTask,
} from '../logic.js'
import { T, language } from '../text.js'
import { WorkSwitch } from './day.js'
import { After, Calm, FocusWalk, Hero } from './focus.js'
import { ReturnCard } from './home.js'
import { Btn, Dot, PrioChip, StateLine } from './parts.js'
import { Prose } from './prose.js'

/** The files the view walks: the one queue in its files scope, from the tabs, the model and the returns */
export const dossierQueue = s => fileQueue(s.tabs?.tabs ?? [], s.model, s.now || Date.now(), s.sessions?.runs)

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

/** The words of a step: a workflow run's is a check of its result, any other its own words */
function stepTitle(step) {
  const d = T().dossier
  if (!step) return d.noNext
  return step.from === 'run' ? d.runStep(step.what) : step.what
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

/** One drawer of the file, folded unless `open`, its count in its head; none when it has nothing */
function Drawer({ title, n, open = false, children }) {
  if (!n) return null
  return html`<details class="dz-drawer" open=${open || undefined}><summary>${title} <span class="sec-count mono">${n}</span></summary>${children}</details>`
}

const RUN_TOKEN = { completed: 'success', failed: 'danger', running: 'info', killed: 'on-surface-muted' }

/** One workflow run bound to the file: its name, how it stands and since when, why it belongs here, what it
 *  left, and Checked while its result waits */
function RunCard({ r, s, c }) {
  const d = T().dossier
  const w = d.run
  const now = s.now || Date.now()
  const at = r.ended_ms ?? r.since_ms ?? r.at_ms
  const waits = !r.seen && (r.status === 'completed' || r.status === 'failed')
  return html`<li class="dz-run">
    <p class="dz-run-head">
      <${StateLine} token=${RUN_TOKEN[r.status] ?? 'on-surface-muted'} word=${w.status[r.status] ?? r.status} />
      <span class="mono">${r.name}</span>
      ${at ? html`<span class="muted small">${T().home.returnAgo(duration(now - at))}</span>` : null}
      ${r.agents ? html`<span class="muted small">${w.agents(r.agents)}</span>` : null}
      <span class="muted small">${(r.how ?? []).map(h => w.how[h] ?? h).join(', ')}</span>
    </p>
    ${r.summary ? html`<p class="dz-run-summary">${r.summary}</p>` : null}
    ${r.answer ? html`<p class="rcard-answer"><span class="label-caps">${w.answer}</span> ${short(r.answer, 400)}</p>` : null}
    ${waits ? html`<div class="btn-row"><${Btn} size="xs" variant="primary" busy=${!!s.ui.busy?.run_seen}
        onClick=${() => c.act('run_seen', { id: r.id })}>${w.check}<//></div>`
      : r.seen ? html`<p class="small"><${StateLine} token="success" word=${w.checked} /></p>` : null}
  </li>`
}

/** What came back for the file: the starts of the return channel and the workflow runs, open while one waits */
function ResultDrawer({ res, s, c }) {
  const d = T().dossier
  return html`<${Drawer} title=${d.drawers.result} n=${res.returns.length + res.runs.length} open=${res.waiting > 0}>
    ${res.returns.length ? html`<div class="ai-cards">${res.returns.map(r => html`<${ReturnCard} key=${r.key} r=${r} s=${s} c=${c} />`)}</div>` : null}
    ${res.runs.length ? html`<ul class="entries dz-runs">${res.runs.map(r => html`<${RunCard} key=${r.id} r=${r} s=${s} c=${c} />`)}</ul>` : null}
  <//>`
}

/** The folder's files besides STATUS.md; a click reads one in place (/api/task?file=), again closes it */
function FilesDrawer({ data, folder, c }) {
  const d = T().dossier
  const files = data?.files ?? []
  const [shown, setShown] = useState(null)
  const base = String(data?.path ?? '').replace(/\/STATUS\.md$/, '')
  const pick = async rel => {
    if (shown?.file === rel) return setShown(null)
    setShown({ file: rel, status: 'loading' })
    const res = await c.taskFile(data.slug, rel, folder)
    setShown(cur => (cur?.file !== rel ? cur : res?.ok ? { file: rel, status: 'ok', ...res.data } : { file: rel, status: 'error' }))
  }
  return html`<${Drawer} title=${d.drawers.files} n=${files.length}>
    <ul class="entries dz-files">${files.map(f => html`<li key=${f.path} class="entry">
      <button type="button" class="btn-link dz-file-open mono" aria-expanded=${shown?.file === f.path} onClick=${() => pick(f.path)}>${f.path}</button>
    </li>`)}</ul>
    ${shown ? html`<section class="dz-file panel panel-pad" aria-live="polite">
      <p class="dz-file-path muted small"><code>${base}/${shown.file}</code>
        <${Btn} variant="ghost" size="xs" onClick=${() => setShown(null)}>${d.file.close}<//></p>
      ${shown.status === 'loading' ? html`<p class="muted small" role="status">${d.file.loading}</p>`
        : shown.status === 'error' ? html`<p class="muted small" role="status">${d.file.failed}</p>`
        : /\.md$/i.test(shown.file) ? html`<${Prose} cls="dz-file-text" text=${shown.text ?? ''} />`
        : html`<pre class="pre dz-file-text">${shown.text ?? ''}</pre>`}
      ${shown.cut ? html`<p class="muted small">${d.file.cut}</p>` : null}
    </section>` : null}
  <//>`
}

/** The drawers of a file: what came back for it (when `res` is given), and from what /api/task holds its inbox
 *  items, its history (log rows), the files of its folder, the paths it names as related and the sections of
 *  STATUS.md. `folder` the folder of a closed copy, or null */
function Drawers({ data, res = null, folder = null, s, c }) {
  const d = T().dossier
  if (!data && !res) return null
  const inbox = data?.inbox ?? []
  const log = data?.log ?? []
  const sections = data?.sections ?? []
  const refs = data?.related ?? []
  return html`<div class="dz-drawers">
    ${res ? html`<${ResultDrawer} res=${res} s=${s} c=${c} />` : null}
    <${Drawer} title=${d.drawers.inbox} n=${inbox.length}>
      <ul class="entries">${inbox.map(e => html`<li key=${e.id} class="entry">${e.summary}</li>`)}</ul><//>
    <${Drawer} title=${d.drawers.history} n=${log.length}>
      <ol class="log-rows">${log.map((l, i) => html`<li key=${i}><span class="mono muted">${l.at}</span><span>${l.text}</span></li>`)}</ol><//>
    ${data ? html`<${FilesDrawer} key=${data.path} data=${data} folder=${folder} c=${c} />` : null}
    <${Drawer} title=${d.drawers.refs} n=${refs.length}>
      <ul class="entries">${refs.map(p => html`<li key=${p} class="entry"><code>${p}</code></li>`)}</ul><//>
    <${Drawer} title=${d.drawers.sections} n=${sections.length}>
      ${sections.map((x, i) => html`<details key=${i}><summary>${x.heading}</summary><p class="pre">${x.text}</p></details>`)}<//>
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
  // the words searched last, also when the command box searched them (?words) while this field was open; only
  // a new search sets it, never what is being typed
  const searched = useRef(s.find?.q ?? '')
  useEffect(() => {
    const q = s.find?.q ?? ''
    if (q !== searched.current) { searched.current = q; setText(q) }
  }, [s.find?.q])
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
    ${groups.length ? html`<ol class="dz-found">${groups.map(g => html`<li key=${g.path} class="dz-found-item">
      <p class="dz-found-head">
        ${g.slug ? html`<button type="button" class="dz-found-open btn-link" onClick=${() => c.openFile(g.slug, g.path)}>${g.slug}</button>`
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
 *  to STATUS.md only on Take over (c.takeNext, verb task_set_next) */
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
  const dismiss = html`<${Btn} variant="ghost" size="sm" onClick=${() => c.dismissSuggest()}>${d.dismiss}<//>`
  // still asked; a chat gone from the list (archived, replaced) falls through to "no suggestion"
  if (conv && (conv.running || (!last?.a && !last?.error))) {
    return html`<div class="dz-suggest" role="status"><p class="muted small">${d.running}</p>
      <div class="dz-suggest-acts">${dismiss}</div></div>`
  }
  return html`<div class="dz-suggest panel panel-pad" role="status">
    ${step ? html`<p class="eyebrow">${d.title}</p><p class="dz-suggest-step">${step}</p><p class="muted small">${d.note}</p>`
      : html`<p class="muted small">${d.failed}</p>`}
    <div class="dz-suggest-acts">
      ${step ? html`<${Btn} variant="primary" size="sm" onClick=${() => c.takeNext(x.row.key, step)}>${d.take}<//>` : null}
      ${dismiss}
    </div>
  </div>`
}

/** A file opened from the search, beside the queue: its cover from /api/task, the next step its STATUS.md
 *  names (or the suggestion when it names none and the task is open), its drawers, a question to it, and the
 *  way back. `open` is its slug, or the folder of a closed copy (work/done/<month>/<slug>), which borrows
 *  nothing from a row of its slug. A closed file is never named as the task of a question (quick.py would
 *  archive the chat at once); none of the verbs, it is not in the queue */
function OpenFile({ open, s, c }) {
  const d = T().dossier
  const slug = open.split('/').pop()
  const entry = s.details?.task?.[open]
  const ver = s.model?.collected_ms ?? 0
  useEffect(() => { if (detailNeedsLoad(entry, ver)) c.loadTask(open) }, [open, ver, entry?.stale])
  const data = entry?.data ?? null
  const row = open.includes('/') ? null
    : (s.model?.sections ?? []).flatMap(x => x.rows ?? []).find(r => r.key === `task:${slug}` && !r.inbox_id) ?? null
  const facts = fileFacts(slug, data, row)
  const x = { id: `task:${slug}`, slug, row: { key: `task:${slug}`, title: facts.title, priority: facts.priority,
    status: facts.status, task_type: facts.type, area: row?.area ?? null } }
  const context = fileContext(facts, language())
  // the suggestion writes through the task's row (verb task_set_next): only an open task the model lists
  const suggest = row && facts.kind !== 'done' && !facts.next
  return html`<div class="dz-open">
    <p class="dz-opened muted small">${d.opened} <${Btn} variant="ghost" size="sm" icon="back" onClick=${() => c.closeFile()}>${d.back}<//></p>
    ${entry?.status === 'error' ? html`<p class="muted" role="status">${d.noFile}</p>` : html`
      <${Cover} x=${x} s=${s} data=${data} place=${facts.kind === 'task' ? null : d.find.kind[facts.kind]} />
      ${facts.next ? html`<p class="dz-next"><span class="eyebrow">${d.next}</span> ${facts.next}</p>` : null}
      ${suggest ? html`<${Suggest} x=${x} s=${s} c=${c} context=${context} />` : null}
      <${Drawers} data=${data} folder=${open.includes('/') ? open : null}
        res=${open.includes('/') ? null : fileResults(slug, s.model, s.tabs?.tabs, s.now || Date.now(), s.sessions?.runs)} s=${s} c=${c} />
      <${AskBox} cls="dz-ask" label=${d.ask.label} placeholder=${d.ask.placeholder} context=${context}
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
    ${open ? html`<${OpenFile} key=${open} open=${open} s=${s} c=${c} />` : x ? html`
      <${Cover} key=${`c${x.id}`} x=${x} s=${s} data=${data} />
      <${Hero} key=${x.id} x=${hero} n=${queue.length} tabOf=${() => fileTab(x, s)} s=${s} c=${c}
        title=${stepTitle(step)} kindWord=${d.next} sub=${stepLine(step, nowMs)} />
      ${step ? null : html`<${Suggest} key=${`s${x.id}`} x=${x} s=${s} c=${c} context=${context} />`}
      <${Drawers} key=${`d${x.id}`} data=${data} res=${fileResults(x.slug, s.model, s.tabs?.tabs, nowMs, s.sessions?.runs)} s=${s} c=${c} />
      <${AskBox} key=${`a${x.id}`} cls="dz-ask" label=${d.ask.label} placeholder=${d.ask.placeholder} context=${context}
        task=${x.slug} s=${s} c=${c} />
      <${FocusWalk} queue=${queue} i=${i} s=${s} c=${c} walk=${c.dossierWalk} />
      <${After} queue=${queue} i=${i} onPick=${k => c.dossierWalk(queue[k].id, k)} s=${s} title=${d.after} kindWord=${reasonWord} />`
    : html`<${Calm} s=${s} c=${c} title=${d.empty} sub=${d.emptySub} action=${false} />`}
  </div>`
}
