// SPDX-License-Identifier: MIT
// The cockpit, the item card: one way to show what an item is for, the same for a task, a stream, an inbox item and
// any row the server sends a `card` with (card.py, the shape card_fields.CARD_FIELDS names). ItemCard draws it in a
// detail head (the middle column, the drawers, the files view), ItemCardLine as the sub line of a list row.
//
// In this order, each only when it has something: the summary (left out when the story says it), the goal first and
// strongest, the user story as one sentence, the acceptance criteria as a short list to read (never to tick: the
// steps checklist of STATUS.md stays the only thing to tick), the next step with who takes it and by when, the chips
// (state, owner, priority, due, area, source), the progress of the steps and the gaps as quiet hints. A brief a
// model wrote and nobody edited carries a small "AI" with its model and day on hover, and "outdated" once the
// item changed past it (the describe view, describe.py state_for, the row's `describe` or the live `describe`
// event), with why on hover (stale_why: the text moved on, an older prompt, a reference to try once more). Where the
// brief names a reference (card.py brief_refs), the goal and each criterion are drawn in parts: an issue or URL as a
// link that opens in a new tab, a task slug through the files view (c.openFile), a file of a task folder read in
// place (c.taskFile, as the files view reads it), any other path as code with a copy button, and a reference nobody
// can reach as text with a quiet "not found". "Describe with AI" (verb describe_run) asks for a brief of a task, stream or inbox item; when a person
// wrote the brief, the model only proposes, and the proposal waits in the card with Apply, Edit and Discard
// (describe_apply, with the person's own text after Edit, and describe_discard). An error reaches the error toast
// like any other action. All of it for the mouse; no key is named.
// The rules every component keeps stand at the head of components.js.

import { html, useEffect, useRef, useState } from '../vendor/htm-preact-3.1.1.module.js'
import { formatDay, indexRows, personOf } from '../logic.js'
import { T, language } from '../text.js'
import { OriginTag } from './day.js'
import { Btn, Chip } from './parts.js'
import { Prose } from './prose.js'

/** The kinds of card describe takes (describe.py KINDS) */
export const DESCRIBABLE = new Set(['task', 'stream', 'inbox'])
/** The card chips a detail head leaves out where the facts below it say them already (and the origin tag of the
 *  head): a task's status and priority (TaskDetail, the drawer's TaskBody), an inbox item's state and due day
 *  (the drawer's InboxBody) */
export const TASK_FACTS_SKIP = ['source', 'state', 'priority']
export const INBOX_FACTS_SKIP = ['source', 'state', 'due']
const CRITERIA_MAX = 5
const STORY_PARTS = ['as', 'want', 'so_that']

/** The describe view of a key: the live one (the `describe` event, an action's answer) before what the row or
 *  detail carries; null without any */
export function describeOf(s, key, ...carried) {
  return (key && s?.describe?.[key]) || carried.find(x => x && typeof x === 'object') || null
}

/** The title of a list row: its card's, the one its detail, drawer and file show, else the row's own */
export const titleOf = row => row?.card?.title || row?.title || ''

/** Whether any describe runs now: the server runs one at a time (describe_running), so every card waits. A live
 *  view (the `describe` event, an action's answer), a describe action of any card, or a run a row of the model
 *  carries */
export function describeBusy(s) {
  if (Object.values(s?.describe ?? {}).some(v => v?.running)) return true
  if (Object.values(s?.ui?.busy ?? {}).includes('describe_run')) return true
  for (const r of indexRows(s?.model).values()) if (r.describe?.running) return true
  return false
}

/** Whether the card's brief is the waiting proposal (card.py fills a card without a valid stored brief from it,
 *  as "ai"): then the proposal, with Apply, says it once and the card does not pass it off as a brief */
export function briefFromProposal(card, d) {
  return !!(d?.proposal?.id && card?.goal && card.written === 'ai' && d.written !== 'ai')
}

/** The first button inside an element, walked by hand (no selector engine needed) */
function firstButton(el) {
  for (const n of el?.childNodes ?? []) {
    if (n.tagName === 'BUTTON') return n
    const deeper = firstButton(n)
    if (deeper) return deeper
  }
  return null
}

/** The card of an item: the model's row before the detail payload, null without either */
export const cardOf = (...from) => from.find(x => x?.card)?.card ?? null

/** The describe key of a row or page item: its own when it is a task or inbox key, else its task's or item's */
export function describeKey(x) {
  if (!x) return null
  if (typeof x.key === 'string' && /^(task|inbox):/.test(x.key)) return x.key
  if (x.inbox_id || x.inbox) return `inbox:${x.inbox_id || x.inbox}`
  if (x.task) return `task:${x.task}`
  return null
}

const dayOf = d => (typeof d === 'string' && /^\d{4}-\d{2}-\d{2}/.test(d) ? formatDay(d.slice(0, 10), language(), true) : d || null)

/** The story as one sentence, null unless all three parts are there */
function storyText(story) {
  if (!story || !STORY_PARTS.every(k => String(story[k] ?? '').trim())) return null
  return T().card.storyLine(story.as, story.want, story.so_that)
}

/** The small "AI": its model and day on hover and, as its label, for a screen reader */
function AiMark({ by, day }) {
  const w = T().card
  const says = w.aiBy(by || w.aiUnknown, day)
  return html`<span class="ai-mark" role="img" title=${says} aria-label=${says}>${w.ai}</span>`
}

/** "AI" for a brief a model wrote and nobody edited, with its model and day on hover; "outdated" once the item
 *  changed past it */
function WrittenMarks({ card, d }) {
  const w = T().card
  // the view's word on a stored brief; without one (no brief stored, a proposal fills the card) the card's own
  const ai = d?.written ? d.written === 'ai' : card.written === 'ai' && !!card.goal
  return html`${ai ? html`<${AiMark} by=${d?.by} day=${dayOf(d?.at)} />` : null}
    ${d?.stale ? html`<span class="card-stale" title=${w.staleWhy[d.stale_why] ?? w.staleHint}>${w.stale}</span>` : null}`
}

function stateWord(card, t) {
  const word = card.state?.word
  if (!word) return null
  if (card.kind === 'inbox') return t.item.stateName[word] ?? word
  if (['task', 'stream', 'done_task', 'done_stream'].includes(card.kind)) return t.taskState[word] ?? word
  return word
}

function Chips({ card, has }) {
  const t = T()
  const w = t.card
  const items = [
    has('state') && stateWord(card, t) ? html`<${Chip} key="state">${stateWord(card, t)}<//>` : null,
    has('owner') && card.owner ? html`<${Chip} key="owner">${w.owner[card.owner] ?? card.owner}<//>` : null,
    has('priority') && card.priority ? html`<${Chip} key="priority">${card.priority}<//>` : null,
    has('due') && card.due ? html`<${Chip} key="due">${w.due(dayOf(card.due))}<//>` : null,
    has('area') && card.area ? html`<${Chip} key="area">${card.area}<//>` : null,
    has('source') && card.source ? html`<${OriginTag} key="source" origin=${card.source} />` : null,
  ].filter(Boolean)
  return items.length ? html`<p class="card-chips">${items}</p>` : null
}

function NextLine({ next }) {
  const w = T().card
  if (!next?.what) return null
  const who = next.who ? w.who[next.who] ?? next.who : null
  return html`<p class="card-next"><span class="label-caps">${w.next}</span> <span class="card-next-what">${next.what}</span>
    ${who ? html`<span class="muted"> · ${who}</span>` : null}${next.due ? html`<span class="muted"> · ${w.due(dayOf(next.due))}</span>` : null}</p>`
}

function Progress({ p }) {
  const w = T().card
  if (!p?.total) return null
  const frac = Math.max(0, Math.min(1, p.done / p.total))
  return html`<p class="card-progress"><span class="card-meter" aria-hidden="true"><span class="card-meter-fill"
    style=${{ transform: `scaleX(${frac.toFixed(4)})` }}></span></span>
    <span class="muted small">${w.steps(p.done, p.total)}</span></p>`
}

/** The gaps as quiet hints; an entry about a task already closed offers to close the entry (settle, done) */
function Gaps({ card, dkey, s, c }) {
  const w = T().card
  const gaps = (card.gaps ?? []).filter(g => w.gap[g])
  if (!gaps.length) return null
  const closable = card.kind === 'inbox' && gaps.includes('task_closed') && dkey && c
  return html`<p class="card-gaps muted small">${gaps.map((g, i) => html`<span key=${g} class="card-gap">${i ? ' · ' : ''}${w.gap[g]}</span>`)}
    ${closable ? html` <${Btn} size="xs" variant="ghost" busy=${!!s?.ui?.busy?.[dkey]}
      onClick=${() => c.act('settle', { keys: [dkey], outcome: 'done' })}>${w.closeEntry}<//>` : null}</p>`
}

const TASK_FILE_RE = /^(work\/(?:tasks|streams)\/([a-z0-9][a-z0-9-]*)|work\/done\/[^/]+\/([a-z0-9][a-z0-9-]*))\/(.+)$/

/** A file reference as the files view opens it: {slug, file, folder} inside a task folder (folder: a closed copy's,
 *  else null), null for any other path */
function taskFileOf(path) {
  const m = TASK_FILE_RE.exec(path ?? '')
  if (!m) return null
  return { slug: m[2] ?? m[3], file: m[4], folder: m[3] ? m[1] : null }
}

/** One reference of a brief: a link, a button that opens it in the cockpit, or text with a quiet "not found" */
function RefPart({ p, c, shown, onFile }) {
  const w = T().card
  const ref = p.ref
  if (p.unresolved) {
    return html`<span class="card-ref-missing" title=${w.refMissing}>${p.text}<span class="sr-only"> (${w.refMissing})</span></span>`
  }
  if (!ref) return p.text
  if (ref.kind === 'web' && /^https?:\/\//.test(ref.href ?? '')) {
    return html`<a class="card-ref" href=${ref.href} target="_blank" rel="noopener noreferrer">${p.text}</a>`
  }
  if (ref.kind === 'task' && ref.key && c) {
    return html`<button type="button" class="btn-link card-ref" onClick=${() => c.openFile(ref.key, ref.folder ?? null)}>${p.text}</button>`
  }
  if (ref.kind === 'file' && ref.path) {
    const f = taskFileOf(ref.path)
    if (f && f.file === 'STATUS.md' && c) {
      return html`<button type="button" class="btn-link card-ref mono" onClick=${() => c.openFile(f.slug, f.folder)}>${p.text}</button>`
    }
    if (f && c) {
      return html`<button type="button" class="btn-link card-ref mono" aria-expanded=${shown === ref.path}
        onClick=${() => onFile(ref.path, f)}>${p.text}</button>`
    }
    return html`<span class="card-ref-path"><code>${p.text}</code>${c ? html`<${Btn} variant="ghost" size="xs" icon="copy"
      label=${T().copyPath} title=${T().copyPath} onClick=${() => c.copy(ref.path)} />` : null}</span>`
  }
  return p.text
}

/** A text of the brief: in parts with its references when card.py found any (brief_refs), else as it is */
function RefText({ text, parts, c, shown, onFile }) {
  if (!Array.isArray(parts) || !parts.length) return text
  return parts.map((p, i) => html`<${RefPart} key=${i} p=${p} c=${c} shown=${shown} onFile=${onFile} />`)
}

/** A file of a task folder a reference of the brief opened, read in place as the files view reads it */
function RefFile({ shown, onClose }) {
  const w = T().card
  return html`<section class="card-ref-file" aria-live="polite">
    <p class="muted small"><code>${shown.path}</code> <${Btn} variant="ghost" size="xs" onClick=${onClose}>${w.refClose}<//></p>
    ${shown.status === 'loading' ? html`<p class="muted small" role="status">${w.refFileLoading}</p>`
      : shown.status === 'error' ? html`<p class="muted small" role="status">${w.refFileFailed}</p>`
      : /\.md$/i.test(shown.path) ? html`<${Prose} cls="card-ref-text" text=${shown.text ?? ''} />`
      : html`<pre class="pre card-ref-text">${shown.text ?? ''}</pre>`}
    ${shown.cut ? html`<p class="muted small">${w.refFileCut}</p>` : null}
  </section>`
}

/** The brief: goal, story and criteria, with who wrote it; its references as links (RefText) */
function Brief({ card, d, has, c }) {
  const w = T().card
  const [shown, setShown] = useState(null)
  const story = has('story') ? storyText(card.story) : null
  const all = has('acceptance') ? card.acceptance ?? [] : []
  const criteria = all.map((x, i) => [x, card.brief_refs?.acceptance?.[i] ?? null]).filter(([x]) => x)
  const goal = has('goal') ? card.goal : null
  if (!goal && !story && !criteria.length) return null
  const onFile = async (path, f) => {
    if (shown?.path === path) return setShown(null)
    setShown({ path, status: 'loading' })
    const res = await c.taskFile(f.slug, f.file, f.folder)
    setShown(cur => (cur?.path !== path ? cur : res?.ok ? { path, status: 'ok', ...res.data } : { path, status: 'error' }))
  }
  const ref = { c, shown: shown?.path ?? null, onFile }
  return html`<div class="card-brief">
    ${goal ? html`<p class="card-goal"><span class="label-caps">${w.goal}</span> <${WrittenMarks} card=${card} d=${d} />
      <span class="card-goal-text"><${RefText} text=${goal} parts=${card.brief_refs?.goal} ...${ref} /></span></p>` : null}
    ${story ? html`<p class="card-story-line"><span class="label-caps">${w.story}</span> ${goal ? null : html`<${WrittenMarks} card=${card} d=${d} />`}
      <span class="card-story">${story}</span></p>` : null}
    ${criteria.length ? html`<div class="card-criteria-box"><span class="label-caps">${w.criteria}</span>
      <ul class="card-criteria">${criteria.map(([x, parts], i) => html`<li key=${i}><${RefText} text=${x} parts=${parts} ...${ref} /></li>`)}</ul></div>` : null}
    ${shown ? html`<${RefFile} shown=${shown} onClose=${() => setShown(null)} />` : null}
  </div>`
}

/** The small form of a proposal: goal, the three story parts and up to five criteria (none for a stream) */
function EditForm({ brief, stream, busy, onSave, onCancel }) {
  const w = T().card
  const f = w.form
  const [v, setV] = useState(() => ({
    goal: brief?.goal ?? '', ...Object.fromEntries(STORY_PARTS.map(k => [k, brief?.story?.[k] ?? ''])),
    acceptance: Array.from({ length: CRITERIA_MAX }, (_, i) => brief?.acceptance?.[i] ?? ''),
  }))
  const first = useRef(null)
  useEffect(() => { first.current?.focus() }, [])
  const set = (k, val) => setV(x => ({ ...x, [k]: val }))
  const setCrit = (i, val) => setV(x => ({ ...x, acceptance: x.acceptance.map((a, j) => (j === i ? val : a)) }))
  const submit = e => {
    e.preventDefault()
    const story = Object.fromEntries(STORY_PARTS.map(k => [k, v[k].trim()]))
    const out = { goal: v.goal.trim() }
    if (STORY_PARTS.every(k => story[k])) out.story = story
    out.acceptance = stream ? [] : v.acceptance.map(a => a.trim()).filter(Boolean)
    onSave(out)
  }
  const field = (name, label, value, onInput, extra = '', ref = null) => html`<label class="card-edit-field"><span class="small muted">${label}</span>
    <input class=${`input input-sm${extra}`} name=${name} type="text" value=${value} ref=${ref} onInput=${e => onInput(e.currentTarget.value)} /></label>`
  return html`<form class="card-edit" onSubmit=${submit}>
    ${field('goal', f.goal, v.goal, x => set('goal', x), '', first)}
    <div class="card-edit-story">${STORY_PARTS.map(k => field(k, f[k === 'so_that' ? 'soThat' : k], v[k], x => set(k, x)))}</div>
    <p class="small muted">${f.storyHint}</p>
    ${stream ? null : v.acceptance.map((a, i) => field(`acceptance${i}`, f.criterion(i + 1), a, x => setCrit(i, x), ' card-edit-crit'))}
    <div class="btn-row">
      <button type="submit" class="btn btn-primary btn-xs" disabled=${busy || !v.goal.trim()}><span class="btn-label">${w.save}</span></button>
      <${Btn} size="xs" variant="ghost" onClick=${onCancel}>${w.cancel}<//>
    </div>
  </form>`
}

/** A proposal of the model beside a brief a person wrote: what it says, Apply, Edit, Discard. Drawn with the
 *  proposal's id as its key, so a newer proposal starts afresh (never the form of the old one); `onDone` hands the
 *  focus on once the proposal is applied or discarded and leaves */
function Proposal({ prop, card, dkey, s, c, onDone }) {
  const w = T().card
  const [editing, setEditing] = useState(false)
  const busy = !!s?.ui?.busy?.[dkey]
  const b = prop.brief ?? {}
  const stream = card.kind === 'stream'
  const story = storyText(b.story)
  const criteria = stream ? [] : (b.acceptance ?? []).filter(Boolean)
  const apply = async brief => {
    const r = await c.act('describe_apply', brief ? { key: dkey, proposal: prop.id, brief } : { key: dkey, proposal: prop.id })
    if (r) {
      setEditing(false)
      onDone?.()
    }
  }
  const discard = async () => { if (await c.act('describe_discard', { key: dkey, proposal: prop.id })) onDone?.() }
  return html`<div class="card-proposal">
    <p class="card-proposal-head"><span class="label-caps">${w.proposal}</span>
      <${AiMark} by=${prop.by} day=${prop.at_ms ? dayOf(new Date(prop.at_ms).toISOString()) : null} /></p>
    <p class="muted small">${w.proposalHint}</p>
    ${editing ? html`<${EditForm} key=${prop.id} brief=${b} stream=${stream} busy=${busy} onSave=${apply} onCancel=${() => setEditing(false)} />`
      : html`${b.goal ? html`<p class="card-goal"><span class="label-caps">${w.goal}</span> <span>${b.goal}</span></p>` : null}
        ${story ? html`<p class="card-story-line"><span class="label-caps">${w.story}</span> <span>${story}</span></p>` : null}
        ${criteria.length ? html`<ul class="card-criteria">${criteria.map((x, i) => html`<li key=${i}>${x}</li>`)}</ul>` : null}
        <div class="btn-row">
          <${Btn} size="xs" variant="primary" busy=${busy} onClick=${() => apply(null)}>${w.apply}<//>
          <${Btn} size="xs" variant="secondary" disabled=${busy} onClick=${() => setEditing(true)}>${w.edit}<//>
          <${Btn} size="xs" variant="ghost" busy=${busy} onClick=${discard}>${w.discard}<//>
        </div>`}
  </div>`
}

/** "Describe with AI": busy while any describe runs (the server runs one at a time: this card's action, another
 *  card's, a run of the server's own pass); this item's run and its last error said in a live region */
function Describe({ card, d, dkey, s, c, box }) {
  if (personOf(s)) return null      // no model on a person's page (access.py)
  const w = T().card
  const running = !!d?.running
  const busy = running || !!s?.ui?.busy?.[dkey] || describeBusy(s)
  return html`<div class="card-describe" ref=${box}>
    <${Btn} size="xs" variant="secondary" icon="spark" busy=${busy} title=${w.describeHint}
      onClick=${() => c.act('describe_run', { key: dkey })}>${card.goal ? w.describeAgain : w.describe}<//>
    ${running ? html`<span class="muted small" role="status">${w.running}</span>` : null}
    ${d?.last_error && !running ? html`<span class="muted small card-error" role="alert">${w.lastError(d.last_error)}</span>` : null}
  </div>`
}

const has_ = (skip, k) => !skip.includes(k)

/** The card of an item in a detail head. `d` is its describe view, `dkey` the key describe takes (task:, inbox:);
 *  `title` draws the title too (where the head has none of its own), `skip` leaves out parts the head shows
 *  already: summary, goal, story, acceptance, next, state, owner, priority, due, area, source, progress, gaps,
 *  describe */
export function ItemCard({ card, d = null, dkey = null, s, c, title = false, skip = [], cls = '' }) {
  const box = useRef(null)
  if (!card) return null
  const describable = has_(skip, 'describe') && dkey && c && DESCRIBABLE.has(card.kind)
  const prop = describable && d?.proposal?.id ? d.proposal : null
  // a card filled from the waiting proposal leaves its brief to the proposal, which says it once with Apply
  const lent = prop && briefFromProposal(card, d)
  const has = k => has_(skip, k) && !(lent && ['goal', 'story', 'acceptance'].includes(k))
  const story = storyText(card.story)
  const summary = has('summary') && card.summary && !(story && (has_(skip, 'story') || lent)) ? card.summary : null
  const focusDescribe = () => setTimeout(() => firstButton(box.current)?.focus(), 0)
  return html`<section class=${`card card-${card.kind ?? 'item'} ${cls}`}>
    ${title && card.title ? html`<p class="card-title">${card.title}</p>` : null}
    ${summary ? html`<p class="card-summary">${summary}</p>` : null}
    <${Brief} card=${card} d=${d} has=${has} c=${c} />
    ${has('next') ? html`<${NextLine} next=${card.next} />` : null}
    <${Chips} card=${card} has=${has} />
    ${has('progress') ? html`<${Progress} p=${card.progress} />` : null}
    ${has('gaps') ? html`<${Gaps} card=${card} dkey=${dkey} s=${s} c=${c} />` : null}
    ${prop ? html`<${Proposal} key=${prop.id} prop=${prop} card=${card} dkey=${dkey} s=${s} c=${c} onDone=${focusDescribe} />` : null}
    ${describable ? html`<${Describe} card=${card} d=${d} dkey=${dkey} s=${s} c=${c} box=${box} />` : null}
  </section>`
}

/** The card as the sub line of a list row: its goal, when it has one; nothing otherwise */
export function ItemCardLine({ card, cls = '' }) {
  if (!card?.goal) return null
  return html`<span class=${`card-line ${cls}`} title=${T().card.goal}>${card.goal}</span>`
}
