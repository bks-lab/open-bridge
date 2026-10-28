// SPDX-License-Identifier: MIT
// The cockpit, the files tab (logic.js FILES_PAGE, a tab of its own beside Work since round 6c). It starts on its
// search (FilesStart): a large field that takes the focus, under it the chips Area, State (open, done, all) and Kind
// (task, stream, closed) and the records changed last (GET /api/records, logic.js recordList), narrowed live as one
// types by title, slug, area and theme and by what the server's search (/api/find) found in the STATUS.md text, each
// with its area, state, last change and the matching line; a click opens one. "Ask AI" beside the field (only with
// cockpit.files_search on) sends the question and the records listed to the model on a click, never by itself; the
// line under it says beforehand how many go and how many the block list keeps private (logic.js askPlan), and the
// answer links the records it names. Under the list the walk through the active files, one at a time.
// A record opened, or the walk, shows one task at a time as a file, on one framed surface, centred at a reading
// width. In the head the way back to the search and a small search field. On the surface: the eyebrow (File,
// "2 of 16", status, kind, priority, the slug on the right), the title as the one heading, the situation in one sentence with where it comes from and its date, then the next
// step in the hero of the start page focus, set as a tinted block with the four verbs, then the file's drawers
// as rows on hairlines, folded (result, inbox, history, files, references, sections), a question to the file,
// and at its foot the walk: Previous, where it stands (a click shows the whole queue to pick from), the title of
// the next file and Next. All of it for the mouse; the view names no key (n and p walk only with the shortcuts
// switched on, app.js).
// The Result drawer holds what came back for the task (logic.js fileResults): the starts of the return channel
// as the start page shows them (ReturnCard, with its ways on and its forget), and the workflow runs the server
// bound to the task (sessions state `runs`), each with why it belongs here; a finished run not yet checked
// waits as the file's result until Checked (verb run_seen), and the drawer stands open while anything waits.
// The Files drawer lists the folder besides STATUS.md (/api/task `files`) and reads a file in place on a click
// (/api/task?file=), Markdown as prose, anything else as it stands.
// The queue is the one every walk takes (logic.js queueOf, scope 'dossier'): a tab that asks, a result that
// waits, an open inbox item, then the doing and review tasks of every priority. The next step is derived on
// every render and never stored. Under the head of the file one calm line says how many active tasks and streams
// the queue leaves out and why (logic.js queueLeftOut: resting, dropped, waiting with nothing that asks, deferred,
// of another area, not pinned); a click lists them, each opens beside the queue, and the empty view names the same.
// With cockpit.files_scope all every task and stream is a file (model.files): behind the queue the chips Active,
// Waiting, Resting, Backlog and All with their counts list them (logic.js fileShelves), each opening as a file of the
// queue does. The shelves split by the queue (Active is the queue, Waiting and Resting what it leaves out, by the
// same rule as the line), and a file outside the queue that rests, is dropped, put off or waits names why as a chip
// on its cover. The line of what the queue leaves out leads to the chips, scrolled into view and focused, instead
// of saying the backlog is not shown.
// The search field in the head (/api/find) puts what it found above the file: by file, best first, a click
// opens a file, a closed one too, beside the queue (ui.dossierOpen) on the same surface with the way back at
// its foot, the results then folded to their head. A question asked in a file carries its folder and cover as
// data (logic.js fileContext) and names an open task, never a closed one; with no file open, a question about
// the results carries the result list (findContext). A file whose next step nobody names offers a suggestion:
// one read-only question, its answer shown, written to STATUS.md only when the
// person takes it over (verb task_set_next).
// The rules every component keeps stand at the head of components.js.

import { html, useEffect, useRef, useState } from '../vendor/htm-preact-3.1.1.module.js'
import {
  askPlan, detailNeedsLoad, dossierStep, duration, FILE_SHELVES, fileContext, fileFacts, fileFolder, fileOf, fileQueue, fileReason,
  fileResults, filesAll, fileShelves, findContext, focusIndex, formatDay, indexRows, placeKind, prioToken, projectTone,
  queueLeftOut, RECORD_KINDS, RECORD_STATES, recordList, rowProject, short, stepAge, suggestedStep, tabOfTask,
} from '../logic.js'
import { T, language } from '../text.js'
import { ItemCard, cardOf, describeOf } from './card.js'
import { KindTag, OriginTag } from './day.js'
import { Calm, Hero } from './focus.js'
import { ReturnCard } from './home.js'
import { Btn, Dot, Icon, StateLine } from './parts.js'
import { Prose } from './prose.js'

/** The files the view walks: the one queue in its files scope, from the tabs, the model and the returns */
export const dossierQueue = s => fileQueue(s.tabs?.tabs ?? [], s.model, s.now || Date.now(), s.sessions?.runs)

/** A queue entry as the hero of the focus reads it: always its task row, so a file keeps the verbs of every row;
 *  a tab that asks stands beside them as the row's tab (Hero tabOf). Without the row's reasons (who it waits
 *  on, since when, its task): the head of the file and the line under its step say that once */
function heroEntry(x) {
  return { kind: 'row', id: x.row.key, row: { ...x.row, why: [] } }
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
  return html`<p class="dz-lead">${pick.text} <span class="dz-src">${[pick.from, at].filter(Boolean).join(', ')}</span></p>`
}

/** A file's area as the areas table shows it (its dot, its name): a click shows that area only (ui.area),
 *  pressed while it is the filter, and a click then lets go. A file without an area says so, quietly */
function AreaChip({ name, s, c, cls = 'dz-area' }) {
  const h = T().home
  if (!name) return html`<span class=${`${cls === 'dz-area' ? 'dz-area-none' : 'dz-found-area-none'} muted`}>${h.noArea}</span>`
  const on = String(s.ui?.area ?? '').trim().toLowerCase() === name.trim().toLowerCase()
  return html`<button type="button" class=${`chip ${cls}`} aria-pressed=${String(on)} title=${on ? h.areaClear : h.areaFilter(name)}
    onClick=${() => c.setArea(on ? null : name)}>
    <span class=${`home-area-dot tk-${projectTone(name)}`} aria-hidden="true"></span>${name}</button>`
}

/** Why an active file stands beside the queue, as a chip (cockpit.files_scope all): resting (its title names what
 *  blocks it), dropped, waiting, or put off with the day it comes back; none for a file of the queue (`queued`)
 *  or of the backlog */
const REASON_CLASS = { resting: 'dz-reason-resting', drop: 'dz-reason-drop', deferred: 'dz-reason-deferred', waiting: 'dz-reason-waiting' }

function ReasonChip({ f, queued = false }) {
  const d = T().dossier
  const why = fileReason(f, queued)
  if (!why) return null
  const word = why === 'deferred' ? (f.deferred_until ? d.reasonUntil(formatDay(f.deferred_until, language())) : d.reason.deferred) : d.reason[why]
  const title = why === 'resting' && f.blocked_by ? d.reasonBlocked(f.blocked_by) : d.left.why[why] ?? ''
  return html`<span class=${`chip dz-reason ${REASON_CLASS[why]}`} title=${title}>${word}</span>`
}

/** The head of a file: an eyebrow (what it is, where it stands, its status, kind and priority, its area and its
 *  slug on the right), its title as the one heading of the view, and the situation. `where` names its place in the eyebrow:
 *  "2 of 16" in the queue, "Opened from the search" and "closed" for a file found beside it. `file` is the file
 *  the server lists for it (cockpit.files_scope all), whose reason chip it shows unless it is `queued` */
function Cover({ x, s, c, data, where = [], file = null, queued = false }) {
  const t = T()
  const r = x.row
  const kind = data?.front?.type ?? r.task_type
  const parts = [...where, r.status ? t.taskState[r.status] ?? r.status : null, kind, r.priority].filter(Boolean)
  // the card of the task (card.py): the same title as its row and drawer, its goal, story and criteria under the
  // situation; the next step stands in the hero below, the status, priority and area in the eyebrow
  const card = cardOf(r, data)
  return html`<header class="dz-cover">
    <p class="dz-eyebrow">
      <span class="dz-eyebrow-what"><${Dot} token=${prioToken(r.priority)} /><${KindTag} row=${{ key: `task:${x.slug}`, task: x.slug, stream: r.stream, work_kind: data?.work_kind ?? r.work_kind }} s=${s} />
        <${OriginTag} row=${r} origin=${data?.origin ?? r.origin ?? null} />${parts.map((w, k) => html`${k ? html`<span class="dz-sep" aria-hidden="true">·</span>` : null}<span key=${k}>${w}</span>`)}
        ${file ? html`<${ReasonChip} f=${file} queued=${queued} />` : null}</span>
      <span class="dz-eyebrow-end"><${AreaChip} name=${rowProject(r)} s=${s} c=${c} /><span class="dz-slug mono">${x.slug}</span></span>
    </p>
    <h2 id="dz-title" class="dz-title">${card?.title || r.title}</h2>
    <${Situation} x=${x} s=${s} data=${data} />
    <${ItemCard} card=${card} d=${describeOf(s, `task:${x.slug}`, r.describe, data?.describe)} dkey=${`task:${x.slug}`} s=${s} c=${c}
      skip=${['summary', 'next', 'state', 'priority', 'area', 'source']} cls="dz-card" />
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
    ${r.answer ? html`<div class="dz-run-answer"><p class="label-caps">${w.answer}</p><${Prose} cls="dz-run-text" text=${short(r.answer, 400)} /></div>` : null}
    ${waits ? html`<div class="btn-row"><${Btn} size="xs" variant="primary" busy=${!!s.ui.busy?.run_seen}
        onClick=${() => c.act('run_seen', { id: r.id })}>${w.check}<//></div>`
      : r.seen ? html`<p class="small"><${StateLine} token="success" word=${w.checked} /></p>` : null}
  </li>`
}

/** What came back for a task (logic.js fileResults): the starts of the return channel and the workflow runs; the
 *  Result drawer of a file and the Result block of Work through (views/flow.js) show it the same */
export function ResultList({ res, s, c }) {
  return html`${res.returns.length ? html`<div class="ai-cards">${res.returns.map(r => html`<${ReturnCard} key=${r.key} r=${r} s=${s} c=${c} />`)}</div>` : null}
    ${res.runs.length ? html`<ul class="entries dz-runs">${res.runs.map(r => html`<${RunCard} key=${r.id} r=${r} s=${s} c=${c} />`)}</ul>` : null}`
}

/** What came back for the file: the starts of the return channel and the workflow runs, open while one waits */
function ResultDrawer({ res, s, c }) {
  const d = T().dossier
  return html`<${Drawer} title=${d.drawers.result} n=${res.returns.length + res.runs.length} open=${res.waiting > 0}>
    <${ResultList} res=${res} s=${s} c=${c} />
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
    ${shown ? html`<section class="dz-file-view panel panel-pad" aria-live="polite">
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
export function Drawers({ data, res = null, folder = null, s, c }) {
  const d = T().dossier
  if (!data && !res) return null
  const inbox = data?.inbox ?? []
  const log = data?.log ?? []
  const sections = data?.sections ?? []
  const refs = data?.related ?? []
  return html`<div class="dz-drawers">
    ${res ? html`<${ResultDrawer} res=${res} s=${s} c=${c} />` : null}
    <${Drawer} title=${d.drawers.inbox} n=${inbox.length}>
      <ul class="entries">${inbox.map(e => html`<li key=${e.id} class="entry"><span>${e.summary}</span>
        <span class="entry-tags"><${KindTag} row=${{ key: `inbox:${e.id}`, inbox_id: e.id }} s=${null} /><${OriginTag} origin=${e.origin ?? null} /></span></li>`)}</ul><//>
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

/** The search field of the files view, small in the head of the view beside the view switch; what is typed is
 *  searched (c.findFiles) on Search or Enter, never run as a code */
function FindField({ s, c }) {
  const f = T().dossier.find
  const [text, setText] = useState(s.find?.q ?? '')
  // the words searched last, also when the command box searched them while this field was open; only a new
  // search sets it, never what is being typed
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
  return html`<form class="dz-find" role="search" title=${f.label} onSubmit=${submit}>
    <label class="sr-only" for="dossier-find">${f.label}</label>
    <${Icon} name="search" />
    <input id="dossier-find" class="dz-find-input" type="search" autocomplete="off" spellcheck="false" maxlength="200"
      placeholder=${f.placeholder} value=${text} onInput=${e => setText(e.currentTarget.value)} />
    <${Btn} variant="ghost" size="xs" busy=${s.find?.status === 'loading'} onClick=${submit}>${f.button}<//>
  </form>`
}

/** What the search found, under the head of the view: by file, best first, each with its kind, its count of
 *  hits and its first lines; a file opens with a click, a log or archive line has no file to open. With no
 *  file open beside the queue, a question about the results */
function FindResults({ s, c, open }) {
  const d = T().dossier
  const f = d.find
  const found = s.find ?? null
  // a file opened from the results folds them to their head, so the file stands right under it
  const [folded, setFolded] = useState(!!open)
  const was = useRef(open)
  if (was.current !== open) { was.current = open; if (folded !== !!open) setFolded(!!open) }
  // what the start of the files tab searched stands in its own list there, not above a file opened from it
  if (!found || found.from === 'start') return null
  const groups = found.status === 'ok' ? found.data?.groups ?? [] : []
  // the search is across every area on purpose: a hit names its area, looked up in the whole model
  const rows = indexRows(s.wholeModel ?? s.model)
  const areaOf = slug => (slug ? rowProject(rows.get(`task:${slug}`)) || null : null)
  const note = found.status === 'loading' ? f.loading : found.status === 'error' ? f.failed(found.error ?? '')
    : found.status === 'tooShort' ? f.tooShort : !groups.length ? f.none(found.q) : found.data.truncated ? f.shown(groups.length, found.data.total) : null
  return html`<section class="dz-results" aria-label=${f.label}>
    <header class="dz-results-head">
      <p class="dz-eyebrow">${f.title}${found.q ? html`<span class="dz-sep" aria-hidden="true">·</span><span class="dz-results-q">${found.q}</span>` : null}</p>
      <span class="dz-results-acts">
        ${open ? html`<${Btn} variant="ghost" size="xs" icon=${folded ? 'chevronDown' : 'chevronUp'} pressed=${!folded}
          onClick=${() => setFolded(!folded)}>${folded ? f.show : f.hide}<//>` : null}
        <${Btn} variant="ghost" size="xs" icon="close" onClick=${() => c.clearFind()}>${f.clear}<//>
      </span>
    </header>
    ${folded ? null : html`
    ${note ? html`<p class="dz-find-note muted small" role="status">${note}</p>` : null}
    ${s.ui.area ? html`<p class="dz-find-note muted small">${f.allAreas}</p>` : null}
    ${groups.length ? html`<ol class="dz-found">${groups.map(g => html`<li key=${g.path} class="dz-found-item">
      <p class="dz-found-head">
        ${g.slug ? html`<button type="button" class="dz-found-open btn-link" onClick=${() => c.openFile(g.slug, g.path)}>${g.slug}</button>`
          : html`<span class="mono">${g.path}</span>`}
        ${g.slug ? html`<${KindTag} row=${{ key: `task:${g.slug}`, task: g.slug, work_kind: g.work_kind ?? placeKind(g.path) }} s=${s} />` : null}
        <span class="dz-fact">${f.kind[g.kind] ?? g.kind}</span>
        ${g.slug ? html`<${AreaChip} name=${areaOf(g.slug)} s=${s} c=${c} cls="dz-found-area" />` : null}
        ${g.slug ? html`<span class="dz-found-title">${g.title}</span>` : null}
        <span class="muted small">${f.hits(g.count)}</span>
      </p>
      ${(g.hits ?? []).slice(0, 2).map(h => html`<p key=${`${h.path}:${h.line}`} class="dz-found-hit small"><span class="mono muted">${h.path.split('/').pop()}:${h.line}</span> ${h.text}</p>`)}
    </li>`)}</ol>` : null}
    ${groups.length && !open ? html`<${AskBox} cls="dz-ask-results" label=${d.ask.results} placeholder=${d.ask.resultsPlaceholder}
      context=${findContext(found.data, language())} task=${null} s=${s} c=${c} />` : null}`}
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

/** A file opened from the search, beside the queue: the same surface as a file of the queue, its head from
 *  /api/task, the next step its STATUS.md names (or the suggestion when it names none and the task is open), its
 *  drawers, a question to it, and the way back at its foot. `open` is its slug, or the folder of a closed copy
 *  (work/done/<month>/<slug>), which borrows nothing from a row of its slug. A closed file is never named as the
 *  task of a question (quick.py would archive the chat at once); none of the verbs, it is not in the queue */
function OpenFile({ open, s, c, queued = false }) {
  const d = T().dossier
  const slug = open.split('/').pop()
  const entry = s.details?.task?.[open]
  const ver = s.model?.collected_ms ?? 0
  useEffect(() => { if (detailNeedsLoad(entry, ver)) c.loadTask(open) }, [open, ver, entry?.stale])
  const data = entry?.data ?? null
  // a found file can belong to any area: it reads the whole model and every tab, not the filtered ones
  const whole = s.wholeModel ?? s.model
  const tabs = (s.wholeTabs ?? s.tabs)?.tabs
  const row = open.includes('/') ? null
    : (whole?.sections ?? []).flatMap(x => x.rows ?? []).find(r => r.key === `task:${slug}` && !r.inbox_id) ?? null
  const facts = fileFacts(slug, data, row)
  const x = { id: `task:${slug}`, slug, row: { key: `task:${slug}`, title: facts.title, priority: facts.priority,
    status: facts.status, task_type: facts.type, area: row?.area ?? null, area_names: row?.area_names ?? [], mark: row?.mark ?? null } }
  const context = fileContext(facts, language())
  // the suggestion writes through the task's row (verb task_set_next): only an open task the model lists
  const suggest = row && facts.kind !== 'done' && !facts.next
  // opened from far down the results: its head comes into view
  const top = useRef(null)
  useEffect(() => { top.current?.scrollIntoView?.({ block: 'nearest' }) }, [])
  // opened from the walk it goes back there, opened from the search start back to the search
  const back = html`<footer class="dz-foot"><div class="dz-walk">
    <${Btn} variant="secondary" size="sm" icon="back" cls="dz-walk-btn" onClick=${() => c.closeFile()}>${s.ui.filesWalk ? d.back : d.start.back}<//></div></footer>`
  return html`<article ref=${top} class="dz-file dz-open" aria-labelledby="dz-title">
    ${entry?.status === 'error' ? html`<p class="muted" role="status">${d.noFile}</p>` : html`
      <${Cover} x=${x} s=${s} c=${c} data=${data} where=${[d.opened, facts.kind === 'task' ? null : d.find.kind[facts.kind]]}
        file=${filesAll(s) && !open.includes('/') ? fileOf(s, slug) : null} queued=${queued} />
      ${facts.next ? html`<section class="dz-step"><p class="dz-step-kind">${d.next}</p><p class="dz-step-title">${facts.next}</p></section>` : null}
      ${suggest ? html`<${Suggest} x=${x} s=${s} c=${c} context=${context} />` : null}
      <${Drawers} data=${data} folder=${open.includes('/') ? open : null}
        res=${open.includes('/') ? null : fileResults(slug, whole, tabs, s.now || Date.now(), s.sessions?.runs)} s=${s} c=${c} />
      <${AskBox} cls="dz-ask" label=${d.ask.label} placeholder=${d.ask.placeholder} context=${context}
        task=${facts.kind === 'done' ? null : slug} s=${s} c=${c} />`}
    ${back}
  </article>`
}

/** The kind word of a file in the queue list: why it stands in the queue */
const reasonWord = x => {
  const d = T().dossier
  return x.reason === 'task' ? (x.row.next ? d.from[x.row.next.from] : d.noNext) : d.from[x.reason]
}

/** The foot of the file: Previous, where it stands, the title of the next file and Next, all buttons for the
 *  mouse. The position opens the whole queue as a list, a click on one walks to it. No key is named here:
 *  n and p walk too, only with the shortcuts switched on (app.js).
 *  Work through walks its points with the same bar (views/flow.js): `go` walks to an index there (else the files
 *  view's dossierWalk), `words` names the steps ({label, prev, next, queue}), `titleFor` and `tagsOf` draw an entry
 *  without a row, `whyOf` its word on the right, `done` the line past the last one, and `onwards` ({title, word,
 *  onGo}) what comes after the last one: Next then leads there (the next theme or area where something is open) */
export function Walk({ queue, i, s, c, go: walkTo = null, words = null, titleFor = null, tagsOf = null, whyOf = null, done = null,
  onwards = null, cls = '' }) {
  const t = T()
  const w = words ?? t.dossier.walk
  const [list, setList] = useState(false)
  if (queue.length < 2 && !onwards) return null
  const go = k => { setList(false); walkTo ? walkTo(k) : c.dossierWalk(queue[k].id, k) }
  const next = i + 1 < queue.length ? queue[i + 1] : null
  const title = x => (titleFor ? titleFor(x) : x.row.title)
  const ahead = next ? short(title(next), 80) : onwards ? onwards.title : done ?? t.nextDone
  return html`<footer class=${`dz-foot${cls ? ` ${cls}` : ''}`}>
    ${list ? html`<ol id="dz-queue" class="dz-queue">${queue.map((x, k) => html`<li key=${x.id}>
      <button type="button" class="dz-queue-item" aria-current=${k === i ? 'true' : undefined} onClick=${() => go(k)}>
        <span class="dz-queue-n mono">${k + 1}</span>
        <span class="entry-tags">${tagsOf ? tagsOf(x) : html`<${KindTag} row=${x.row} s=${s} /><${OriginTag} row=${x.row} />`}</span>
        <span class="dz-queue-title">${short(title(x), 90)}</span>
        <span class="dz-queue-why">${whyOf ? whyOf(x) : reasonWord(x)}</span>
      </button></li>`)}</ol>` : null}
    <nav class="dz-walk" aria-label=${w.label}>
      <${Btn} variant="secondary" size="sm" icon="back" cls="dz-walk-btn" disabled=${i === 0} onClick=${() => go(i - 1)}>${w.prev}<//>
      <button type="button" class="dz-pos" aria-expanded=${String(list)} aria-controls="dz-queue" title=${w.queue}
        onClick=${() => setList(!list)}><span class="mono">${t.nextPos(i + 1, queue.length)}</span><${Icon} name=${list ? 'chevronDown' : 'chevronUp'} /></button>
      <span class="dz-walk-next">${ahead}</span>
      <button type="button" class="btn btn-primary btn-sm dz-walk-btn dz-walk-go" disabled=${!next && !onwards}
        onClick=${() => (next ? go(i + 1) : onwards?.onGo())}>
        <span class="btn-label">${next || !onwards ? w.next : onwards.word}</span><${Icon} name="forward" /></button>
    </nav>
  </footer>`
}

/** The active tasks the queue leaves out, in one calm line: where the file stands (none in an empty queue) and
 *  how many more by why; a click lists them by why, each opening beside the queue (c.openFile), with the one
 *  sentence that backlog tasks never show here. Under an area that hides some, every area again with one click
 *  (`areaButton`, off where the view offers it already). None when nothing is left out */
// the chip of the shelves a reason of the line leads to (cockpit.files_scope all); area and unpinned have none
const LEFT_SHELF = { resting: 'resting', drop: 'resting', deferred: 'resting', waiting: 'waiting' }

function LeftOut({ gaps, s, c, pos = null, areaButton = true }) {
  const t = T()
  const d = t.dossier.left
  const shelves = filesAll(s)
  const [open, setOpen] = useState(false)
  if (!gaps.total) return null
  const lang = language()
  const parts = gaps.groups.map(g => d.reason[g.reason](g.rows.length)).join(', ')
  const why = g => (g.reason === 'area' ? d.why.area(s.ui.area) : d.why[g.reason])
  const detail = (g, x) => (g.reason === 'deferred' ? (x.until ? d.until(formatDay(x.until, lang)) : d.untilShown)
    : g.reason === 'area' ? rowProject(x.row) || t.home.noArea : null)
  const folder = x => `work/${x.row.stream || x.row.work_kind === 'stream' ? 'streams' : 'tasks'}/${x.slug}`
  const backlog = shelves ? fileShelves(s).lists.backlog.length : 0
  return html`<div class="dz-left">
    <p class="dz-left-head">
      <button type="button" class="dz-left-line" aria-expanded=${String(open)} aria-controls="dz-left-list"
        onClick=${() => setOpen(!open)}>${pos ? `${pos} · ` : ''}${d.line(gaps.total, parts)}<${Icon} name=${open ? 'chevronUp' : 'chevronDown'} /></button>
      ${areaButton && s.ui.area && gaps.groups.some(g => g.reason === 'area')
        ? html`<${Btn} variant="ghost" size="xs" onClick=${() => c.setArea(null)}>${t.home.areaClear}<//>` : null}
    </p>
    ${open ? html`<div id="dz-left-list" class="dz-left-list">
      ${gaps.groups.map(g => html`<section key=${g.reason} class="dz-left-group">
        <p class="dz-left-why muted small">${why(g)}${shelves && LEFT_SHELF[g.reason] ? html` <button type="button" class="btn-link dz-left-shelf"
          onClick=${() => c.setFileShelf(LEFT_SHELF[g.reason], true)}>${d.toShelf(t.dossier.shelf.chip[LEFT_SHELF[g.reason]])}</button>` : null}</p>
        <ul class="entries">${g.rows.map(x => html`<li key=${x.slug} class="entry">
          <button type="button" class="btn-link dz-left-open" onClick=${() => c.openFile(x.slug, folder(x))}>${x.row.title || x.slug}</button>
          <span class="entry-tags"><${KindTag} row=${x.row} s=${s} />${detail(g, x) ? html`<span class="muted small">${detail(g, x)}</span>` : null}</span>
        </li>`)}</ul>
      </section>`)}
      ${shelves ? (backlog ? html`<p class="dz-left-backlog muted small"><button type="button" class="btn-link dz-left-shelf"
          onClick=${() => c.setFileShelf('backlog', true)}>${d.toBacklog(backlog)}</button></p>` : null)
        : html`<p class="dz-left-backlog muted small">${d.backlog}</p>`}
    </div>` : null}
  </div>`
}

/** Every task and stream behind the queue (cockpit.files_scope all, model.files): the chips Active, Waiting,
 *  Resting, Backlog and All, each with its count; a click lists the files of one (ui.fileShelf), sorted by
 *  status, priority and last change, a second click folds it. A file opens as one of the queue does
 *  (c.openFile: at its place in the queue, else beside it). They split by the queue (`queue`, the files it walks):
 *  Active is the queue, the rest by why it is left out. Under an area filter it holds that area, and names how
 *  many stand in the others with the way back to every area. A chip picked from the line of what the queue leaves
 *  out (ui.fileShelfReveal) brings the shelves into view and takes the focus, once */
function Shelves({ s, c, queue = [] }) {
  const t = T()
  const d = t.dossier
  const sh = fileShelves(s, queue)
  const queued = new Set(queue.map(x => x.slug))
  const at = FILE_SHELVES.includes(s.ui.fileShelf) ? s.ui.fileShelf : null
  const files = at ? sh.lists[at] : []
  const lang = language()
  const box = useRef(null)
  const chips = useRef({})
  const reveal = Boolean(s.ui.fileShelfReveal && at)
  useEffect(() => {
    if (!reveal) return
    box.current?.scrollIntoView?.({ block: 'start' })
    chips.current[at]?.focus?.()
    c.fileShelfShown()
  }, [reveal, at])
  return html`<section ref=${box} class="dz-shelves" aria-label=${d.shelf.label}>
    <div class="dz-shelf-chips">
      ${FILE_SHELVES.map(k => html`<button key=${k} ref=${el => { chips.current[k] = el }} type="button" class="chip dz-shelf-chip"
        aria-pressed=${String(at === k)} aria-controls=${at === k ? 'dz-shelf-list' : undefined}
        onClick=${() => c.setFileShelf(at === k ? null : k)}>${`${d.shelf.chip[k]} (${sh.lists[k].length})`}</button>`)}
    </div>
    ${s.ui.area && sh.elsewhere ? html`<p class="dz-shelf-elsewhere muted small">${d.shelf.elsewhere(sh.elsewhere, s.ui.area)}
      <${Btn} variant="ghost" size="xs" onClick=${() => c.setArea(null)}>${t.home.areaClear}<//></p>` : null}
    ${at ? files.length ? html`<ul id="dz-shelf-list" class="entries dz-shelf-list">${files.map(f => html`<li key=${f.slug} class="entry">
        <button type="button" class="btn-link dz-shelf-open" onClick=${() => c.openFile(f.slug, fileFolder(f))}>${f.title || f.slug}</button>
        <span class="entry-tags"><${Dot} token=${prioToken(f.priority)} /><${KindTag} row=${{ key: `task:${f.slug}`, task: f.slug, work_kind: f.kind }} s=${s} />
          <span class="muted small">${[t.taskState[f.status] ?? f.status, f.priority].filter(Boolean).join(' · ')}</span>
          <${ReasonChip} f=${f} queued=${queued.has(f.slug)} />
          ${f.updated ? html`<span class="muted small">${d.shelf.updated(formatDay(String(f.updated).slice(0, 10), lang))}</span>` : null}</span>
      </li>`)}</ul>` : html`<p id="dz-shelf-list" class="muted small">${d.shelf.none}</p>` : null}
  </section>`
}

/** One chip of the start's filters: pressed while its value is the one set */
const StartChip = ({ on, onClick, children }) => html`<button type="button" class="chip fs-chip" aria-pressed=${String(!!on)}
  onClick=${onClick}>${children}</button>`

/** The answer of the AI to the records (s.filesAsk from c.askRecords): its text, how many records it read, and a
 *  link to each record it names */
function AskAnswer({ ask, s, c }) {
  const f = T().dossier.start
  if (!ask) return null
  const data = ask.data ?? null
  return html`<section class="fs-answer" aria-live="polite">
    <header class="fs-answer-head"><p class="dz-eyebrow">${f.answer}${data ? html`<span class="dz-sep" aria-hidden="true">·</span><span class="muted">${f.answerFrom(data.sent, data.model)}</span>` : null}</p>
      <${Btn} variant="ghost" size="xs" icon="close" onClick=${() => c.clearFilesAsk()}>${f.close}<//></header>
    ${ask.status === 'loading' ? html`<p class="muted small" role="status">${f.asking}</p>`
      : ask.status === 'error' ? html`<p class="muted small" role="status">${ask.error}</p>`
      : html`<p class="fs-answer-text">${data?.answer}</p>
        ${(data?.files ?? []).length ? html`<ul class="fs-answer-files">${data.files.map(x => html`<li key=${x.path}>
          <button type="button" class="btn-link fs-open" onClick=${() => c.openFile(x.slug, x.path)}>${x.title || x.slug}</button>
          ${x.why ? html` <span class="muted small">${x.why}</span>` : null}</li>`)}</ul>` : null}`}
  </section>`
}

/** The start of the files tab (module head): the search first, its chips, the records, the AI on a click, the walk */
function FilesStart({ s, c, queue }) {
  const t = T()
  const f = t.dossier.start
  const lang = language()
  const list = recordList(s)
  const fs = s.work?.files_search ?? null
  const q = s.ui.filesQ ?? ''
  const field = useRef(null)
  // the records come fresh on every visit (the controller keeps a read of the last minute); the field takes the focus
  useEffect(() => { c.loadRecords(); field.current?.focus?.() }, [])
  const plan = askPlan(list.rows, fs?.block ?? [])
  const state = RECORD_STATES.includes(s.ui.filesState) ? s.ui.filesState : 'open'
  const shown = list.rows.slice(0, 30)
  const ask = () => c.askRecords(q.replace(/\s+/g, ' ').trim() || f.askDefault, plan.paths)
  const note = plan.paths.length ? [f.sends(plan.paths.length), plan.held.n ? f.held(plan.held.n, plan.held.words) : null].filter(Boolean).join(' ')
    : f.nothingToSend
  return html`<div class="col col-page dz">
    <div class="dz-page fs-start">
      <form class="fs-find" role="search" onSubmit=${e => e.preventDefault()}>
        <label class="sr-only" for="files-start-find">${f.label}</label>
        <span class="fs-find-box"><${Icon} name="search" />
          <input id="files-start-find" ref=${field} class="fs-find-input" type="search" autocomplete="off" spellcheck="false"
            maxlength="200" autofocus placeholder=${f.placeholder} value=${q} onInput=${e => c.setFilesFilter({ filesQ: e.currentTarget.value })} /></span>
        ${fs?.enabled ? html`<span class="fs-ask"><${Btn} variant="secondary" size="sm" icon="spark" disabled=${!plan.paths.length}
          busy=${s.filesAsk?.status === 'loading'} onClick=${ask}>${f.ask}<//></span>` : null}
      </form>
      ${fs?.enabled ? html`<p class="fs-ask-note muted small">${note}</p>` : null}
      <div class="fs-chips">
        ${list.areas.length ? html`<span class="fs-chip-group" role="group" aria-label=${f.area}>
          <${StartChip} on=${!s.ui.area} onClick=${() => c.setArea(null)}>${f.allAreas}<//>
          ${list.areas.slice(0, 12).map(a => html`<${StartChip} key=${a} on=${String(s.ui.area ?? '').toLowerCase() === a.toLowerCase()}
            onClick=${() => c.setArea(a)}>${a}<//>`)}</span>` : null}
        <span class="fs-chip-group" role="group" aria-label=${f.stateLabel}>
          ${RECORD_STATES.map(k => html`<${StartChip} key=${k} on=${state === k} onClick=${() => c.setFilesFilter({ filesState: k })}>${f.state[k]}<//>`)}</span>
        <span class="fs-chip-group" role="group" aria-label=${f.kindLabel}>
          ${RECORD_KINDS.map(k => html`<${StartChip} key=${k} on=${s.ui.filesKind === k}
            onClick=${() => c.setFilesFilter(s.ui.filesKind === k ? { filesKind: null } : { filesKind: k, ...(k === 'done' ? { filesState: 'done' } : {}) })}>${f.kind[k]}<//>`)}</span>
      </div>
      <${AskAnswer} ask=${s.filesAsk} s=${s} c=${c} />
      <section class="fs-records" aria-label=${f.label}>
        <p class="dz-eyebrow">${q.trim() ? f.found(list.rows.length) : f.recent}${list.rows.length > shown.length
          ? html`<span class="dz-sep" aria-hidden="true">·</span><span class="muted">${f.shown(shown.length, list.rows.length)}</span>` : null}</p>
        ${shown.length ? html`<ol class="fs-list">${shown.map(r => html`<li key=${r.path} class="fs-item">
          <button type="button" class="btn-link fs-open" onClick=${() => c.openFile(r.slug, r.path)}>${r.title || r.slug}</button>
          <span class="fs-meta small">
            ${r.area ? html`<span class="fs-area"><span class=${`home-area-dot tk-${projectTone(r.area)}`} aria-hidden="true"></span>${r.area}</span>` : null}
            <span class="muted">${[t.taskState[r.status] ?? r.status, r.kind === 'done' ? null : f.kind[r.work_kind === 'stream' ? 'stream' : 'task']].filter(Boolean).join(' · ')}</span>
            ${r.updated ? html`<span class="muted">${f.changed(formatDay(String(r.updated).slice(0, 10), lang))}</span>` : null}
            ${r.theme ? html`<span class="muted">${r.theme}</span>` : null}</span>
          ${r.hit ? html`<p class="fs-hit small muted">${r.hit}</p>` : null}
        </li>`)}</ol>`
          : html`<p class="muted small" role="status">${list.status === 'loading' || !list.status ? f.loading
            : list.status === 'error' ? f.failed(list.error ?? '') : f.none}</p>`}
      </section>
      ${queue.length ? html`<p class="fs-walk"><${Btn} variant="ghost" size="sm" icon="forward"
        onClick=${() => c.dossierWalk(queue[0].id, 0)}>${f.walk(queue.length)}<//></p>` : null}
    </div>
  </div>`
}

export function DossierView({ s, c }) {
  const d = T().dossier
  const t = T()
  const queue = dossierQueue(s)
  // held by its task key: once the file in front is settled, the next one moves up into its place
  const i = focusIndex(queue, s.ui.dossierAt)
  const x = queue[i] ?? null
  const entry = x ? s.details?.task?.[x.slug] : null
  const ver = s.model?.collected_ms ?? 0
  const open = s.ui.dossierOpen ?? null
  // the files tab starts on its search: the walk only once asked for (ui.filesWalk), a record once opened
  const start = !open && !s.ui.filesWalk
  useEffect(() => { if (!start && x && detailNeedsLoad(entry, ver)) c.loadTask(x.slug) }, [start, x?.slug, ver, entry?.stale])
  if (start) return html`<${FilesStart} s=${s} c=${c} queue=${queue} />`
  const data = entry?.data ?? null
  const nowMs = s.now || Date.now()
  const step = x ? dossierStep(x) : null
  const context = x ? fileContext(fileFacts(x.slug, data, x.row), language()) : ''
  // the active tasks the queue leaves out, and in an empty queue the sentence that says why (the star keeps its
  // own sentence before the reasons; the backlog sentence stands in the list only)
  const gaps = queueLeftOut(s, queue)
  const reasons = () => d.left.emptySub(gaps.groups.map(g => d.left.reason[g.reason](g.rows.length)).join(', '))
  const why = (sub, keep = false) => (gaps.total ? (keep ? `${sub} ${reasons()}` : reasons()) : sub)
  return html`<div class="col col-page dz">
    <div class="dz-page">
      <header class="page-head dz-head"><${Btn} variant="ghost" size="sm" icon="back" cls="dz-home"
        onClick=${() => c.filesHome()}>${d.start.back}<//><${FindField} s=${s} c=${c} /></header>
      <${FindResults} s=${s} c=${c} open=${open} />
      ${open ? html`<${OpenFile} key=${open} open=${open} s=${s} c=${c} queued=${queue.some(q => q.slug === open)} />` : x ? html`<article class="dz-file" aria-labelledby="dz-title">
        <${Cover} key=${`c${x.id}`} x=${x} s=${s} c=${c} data=${data} where=${[d.label, t.nextPos(i + 1, queue.length)]} />
        <${LeftOut} gaps=${gaps} s=${s} c=${c} pos=${t.nextPos(i + 1, queue.length)} />
        <${Hero} key=${x.id} x=${heroEntry(x)} n=${1} tabOf=${() => fileTab(x, s)} s=${s} c=${c}
          title=${stepTitle(step)} kindWord=${d.next} sub=${stepLine(step, nowMs)} />
        ${step ? null : html`<${Suggest} key=${`s${x.id}`} x=${x} s=${s} c=${c} context=${context} />`}
        <${Drawers} key=${`d${x.id}`} data=${data} res=${fileResults(x.slug, s.model, s.tabs?.tabs, nowMs, s.sessions?.runs)} s=${s} c=${c} />
        <${AskBox} key=${`a${x.id}`} cls="dz-ask" label=${d.ask.label} placeholder=${d.ask.placeholder} context=${context}
          task=${x.slug} s=${s} c=${c} />
        <${Walk} queue=${queue} i=${i} s=${s} c=${c} />
      </article>`
      : s.ui.pinnedOnly ? html`<${Calm} s=${s} c=${c} title=${s.ui.area ? d.emptyAreaPinned(s.ui.area) : d.emptyPinned} sub=${why(d.emptyPinnedSub, true)} action=${false} />
          <div class="btn-row dz-empty-acts"><${Btn} variant="secondary" size="sm" onClick=${() => c.setPinnedOnly(false)}>${d.allFiles}<//></div>
          <${LeftOut} gaps=${gaps} s=${s} c=${c} />`
      : s.ui.area ? html`<${Calm} s=${s} c=${c} title=${d.emptyArea(s.ui.area)} sub=${why(d.emptyAreaSub)} action=${false} />
          <div class="btn-row dz-empty-acts"><${Btn} variant="secondary" size="sm" onClick=${() => c.setArea(null)}>${d.allAreas}<//></div>
          <${LeftOut} gaps=${gaps} s=${s} c=${c} areaButton=${false} />`
        : html`<${Calm} s=${s} c=${c} title=${d.empty} sub=${why(d.emptySub)} action=${false} /><${LeftOut} gaps=${gaps} s=${s} c=${c} />`}
      ${filesAll(s) ? html`<${Shelves} s=${s} c=${c} queue=${queue} />` : null}
    </div>
  </div>`
}
