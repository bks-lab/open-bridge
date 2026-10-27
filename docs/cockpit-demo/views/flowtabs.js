// SPDX-License-Identifier: MIT
// The cockpit, the tabs under the card of an open point in Work through (views/flow.js), as an issue tracker keeps
// them: Description (goal, story and criteria; the source stands in the fields on the right), Steps (n/m, the
// checklist of its STATUS.md), Activity (count: everything that happened to the point, one list) and Related (n). The
// tab chosen stays from point to point (ui.flowTab, kept in this browser); one the point lacks falls back to
// Description (logic.js pointTabs, pointTab). A tab alone and the reports card have no bar. Card and panes read at most
// 820 px wide.
// Activity (ActivityPane): on top the summary of the last week on a click (cockpit.flow.summary, within the day's
// budget), the filters with their counts (All, Notes, Documents, State, Agents, Code: logic.js ACTIVITY_FILTERS), then
// one row per thing that happened, newest first: when, its kind, what (a change as the old value struck through, then
// the new one; a decision taken back says so), who or what did it. A document opens in a new tab through the doc route
// (c.docHref), a link on the web too, a tab in the page's view of it, a task in the files view. At the foot a note (the
// verb note through the server) and, where the point has an open task, a document attached to its deliverables (size
// checked here first, cockpit.flow.attach). The feed is read when the point opens (app.js loadActivity), again after a
// note, an attachment or a verb on the row.
// For the mouse: no text names a key.
// The rules every component keeps stand at the head of components.js.

import { html, useEffect, useRef, useState } from '../vendor/htm-preact-3.1.1.module.js'
import {
  ACTIVITY_FILTERS, activityCounts, activityRows, activityWhen, attachTooBig, detailNeedsLoad, errorText, flowSettings, formatDay, pointTab,
  pointTabs, relatedOf, short, stepsOf,
} from '../logic.js'
import { T, language } from '../text.js'
import { describeOf, ItemCard } from './card.js'
import { OriginTag } from './day.js'
import { Segmented } from './detail.js'
import { Btn, useRoving } from './parts.js'

// what Description leaves out: the source, the state, who, the prio and the dates stand in the fields and the card's
// head, the next step's who and day too; the progress is the count of Steps; a missing part says itself once
const DESC_SKIP = ['source', 'state', 'owner', 'priority', 'due', 'area', 'next', 'progress', 'gaps']

/** Description: the goal, the story and the criteria of the point's card, written by the task or the item */
function DescPane({ row, detail, entry, s, c }) {
  const f = T().flow.desc
  const card = (row.inbox_id ? row.card ?? detail?.card : detail?.card ?? row.card) ?? null
  const d = describeOf(s, row.key, detail?.describe, row.describe)
  const loading = !!row.task && !detail && entry?.status !== 'error'
  return html`<div class="flow-desc">
    ${card ? html`<${ItemCard} card=${card} d=${d} dkey=${row.key} s=${s} c=${c} skip=${DESC_SKIP} cls="flow-card-brief" />` : null}
    ${card?.goal || card?.story || (card?.acceptance ?? []).length ? null : html`<p class="muted small">${loading ? f.loading : f.none}</p>`}
  </div>`
}

/** Steps: the checklist of STATUS.md as it stands, done or open (ticked there, not here) */
function StepsPane({ steps }) {
  const f = T().flow.steps
  if (!steps.length) return html`<p class="muted small">${f.none}</p>`
  return html`<ul class="flow-steps">${steps.map((st, k) => html`<li key=${k} class=${st.done ? 'is-done' : ''}>
    <span class="flow-step-mark mono">${st.done ? f.done : f.todo}</span> <span>${st.text}</span></li>`)}</ul>`
}

/** Related: the other items of the same task as they stand in the model, the paths STATUS.md names */
function RelatedPane({ rel }) {
  const f = T().flow.related
  if (!rel.rows.length && !rel.paths.length) return html`<p class="muted small">${f.none}</p>`
  return html`<div class="flow-related">
    ${rel.rows.length ? html`<section><h3 class="label-caps">${f.rows}</h3>
      <ul class="entries">${rel.rows.map(r => html`<li key=${r.key} class="entry"><span>${short(r.title, 90)}</span>
        <span class="entry-tags"><${OriginTag} row=${r} /></span></li>`)}</ul></section>` : null}
    ${rel.paths.length ? html`<section><h3 class="label-caps">${f.paths}</h3>
      <ul class="entries">${rel.paths.map(p => html`<li key=${p} class="entry"><code>${p}</code></li>`)}</ul></section>` : null}
  </div>`
}

/** A changed value in words: a status as the card head words it (an inbox item's too), a theme's name, who drives it
 *  (nobody), a decision with its day or reason */
function changeWord(ch, v, t, lang) {
  const f = t.flow.activity
  if (ch.field === 'status') return f.state[v] ?? t.taskState[v] ?? String(v)
  if (ch.field === 'theme') return v ?? t.flow.side.noTheme
  if (ch.field === 'driver') return v ?? f.nobody
  if (ch.field === 'decision') {
    return [f.decision[v] ?? String(v), ch.until ? f.until(formatDay(ch.until, lang)) : null, ch.reason ? f.because(ch.reason) : null].filter(Boolean).join(' ')
  }
  return String(v ?? '')
}

// the fields whose empty side is a value of its own: no theme yet, nobody drives it
const NAMED_EMPTY = new Set(['theme', 'driver'])

/** A change: the old value struck through, then the new one; without an old value the new one alone, but a theme or a
 *  driver before was No theme yet or nobody, struck as such */
function Change({ ch }) {
  const t = T()
  const lang = language()
  const old = ch.old != null || NAMED_EMPTY.has(ch.field)
  return html`<span class="flow-chg">${old ? html`<del class="flow-chg-old">${changeWord(ch, ch.old, t, lang)}</del> → ` : null}<span
    class="flow-chg-new">${changeWord(ch, ch.new, t, lang)}</span></span>`
}

// the ref a code row starts with ("owner/repo#18", "repo#18", a commit's hash): the link of the row is that ref
const CODE_REF_RE = /^((?:[\w.-]+\/)?[\w.-]+#\d+|[0-9a-f]{7,40})(?=\s|$)\s*/

/** A code row's text with its ref as the link to the web (the mockup's "open-bridge #530"); null when it starts with none */
function codeRef(r) {
  const web = (r.links ?? []).find(l => l.kind === 'web')
  const m = r.kind === 'code' && web ? CODE_REF_RE.exec(String(r.text ?? '')) : null
  return m ? { href: web.href, ref: m[1], rest: String(r.text).slice(m[0].length), links: r.links.filter(l => l !== web) } : null
}

/** The links of a row: a document in a new tab through the doc route, a page on the web, a tab, a task */
function Links({ links, c }) {
  const f = T().flow.activity
  if (!(links ?? []).length) return null
  return html`<span class="flow-act-links">${links.map((l, k) => {
    if (l.kind === 'doc') return html`<a key=${k} href=${c.docHref(l.slug, l.path)} target="_blank" rel="noopener noreferrer">${l.path}</a>`
    if (l.kind === 'web') return html`<a key=${k} href=${l.href} target="_blank" rel="noopener noreferrer">${short(String(l.href).replace(/^https?:\/\//, ''), 60)}</a>`
    if (l.kind === 'tab') return html`<button key=${k} type="button" class="btn-link" onClick=${() => c.openTabView(l.ref)}>${f.toTab}</button>`
    if (l.kind === 'task') return html`<button key=${k} type="button" class="btn-link" onClick=${() => c.openFile(String(l.key ?? '').replace(/^task:/, ''), l.folder ?? null)}>${f.open}</button>`
    return null
  })}</span>`
}

// the kinds whose change says what happened: the server's text of such a row is a phrase for a reader without it
const SAID_BY_CHANGE = new Set(['status', 'theme', 'decision', 'created'])

/** What a row says besides its change and its links, said once (nothing twice): a state row says itself in its change,
 *  a document in its link (the server's text is its path inside deliverables/), a start without a known tab names
 *  nobody (a driver of null on both sides is no change) */
function rowSays(r) {
  const ch = r.change && !(r.change.field === 'driver' && r.change.old == null && r.change.new == null) ? r.change : null
  const path = r.kind === 'doc' ? String(r.doc?.path ?? '') : ''
  const text = !r.text || (ch && SAID_BY_CHANGE.has(r.kind)) || r.text === ch?.new || (path && (r.text === path || `deliverables/${r.text}` === path)) ? null : r.text
  return { ch, text }
}

/** One row of the activity: when, what kind, what happened, who or what did it */
function ActRow({ r, c }) {
  const t = T()
  const f = t.flow.activity
  const lang = language()
  const kind = r.kind === 'doc' && r.doc ? f.doc[r.doc.attached ? 'attached' : r.doc.state === 'changed' ? 'changed' : 'new'] : f.kind[r.kind] ?? r.kind
  const who = r.by ? [f.by[r.by.kind] ?? r.by.kind, r.by.name].filter(Boolean).join(' · ') : null
  const changes = r.kind === 'doc' && r.doc?.state === 'changed' && r.doc.changes > 1 ? f.doc.changes(r.doc.changes) : null
  const { ch, text } = rowSays(r)
  const code = codeRef(r)
  return html`<li class=${`flow-act-row is-${r.kind}${r.undone_ms ? ' is-undone' : ''}`}>
    <time class="flow-act-time mono" datetime=${r.at}>${activityWhen(r.at, lang)}</time>
    <div class="flow-act-body">
      <span class="flow-act-kind">${kind}${changes ? ` · ${changes}` : ''}</span>
      <span class="flow-act-what">
        ${ch ? html`<${Change} ch=${ch} />` : null}
        ${code ? html`<span class="flow-act-text"><a class="flow-act-ref mono" href=${code.href} target="_blank" rel="noopener noreferrer"
          title=${code.href}>${code.ref}</a>${code.rest ? ` ${code.rest}` : ''}</span>` : text ? html`<span class="flow-act-text">${text}</span>` : null}
        <${Links} links=${code ? code.links : r.links} c=${c} />
        ${r.undone_ms ? html`<span class="flow-act-undone">${f.undone}</span>` : null}
      </span>
      ${who ? html`<span class="flow-act-who">${who}</span>` : null}
    </div>
  </li>`
}

/** The summary of the last week, on a click (cockpit.flow.summary): the kept one with its model and time, outdated
 *  once rows came since; a refusal says itself here, no toast */
function Summary({ row, feed, s, c }) {
  const t = T()
  const f = t.flow.activity.summary
  const lang = language()
  const [err, setErr] = useState(null)
  const on = flowSettings(s).summary.enabled
  const kept = feed?.summary ?? null
  if (!on && !kept) return null
  const can = on && !!feed?.can?.summary && (!kept || kept.stale)
  const busy = !!s.ui.busy?.[`summary:${row.key}`]
  const left = s.flow_ai?.summary_left
  const clock = ms => (Number.isFinite(ms) ? new Date(ms).toLocaleTimeString(lang === 'de' ? 'de-DE' : 'en-GB', { hour: '2-digit', minute: '2-digit' }) : '')
  const model = m => (m ? String(m).charAt(0).toUpperCase() + String(m).slice(1) : '')
  const ask = async () => {
    setErr(null)
    const r = await c.flowSummary(row.key)
    if (r?.error) setErr(errorText(r.error, t))
  }
  if (!kept && !can) return null
  return html`<div class="flow-act-sum">
    ${kept ? html`<p class="flow-act-sum-text"><b>${f.title}</b> <span class="muted small">(${f.meta(model(kept.model), clock(kept.at_ms))})</span>
      ${kept.stale ? html` <span class="flow-act-stale">${f.stale}</span>` : null}<br />${kept.text}</p>` : null}
    ${can ? html`<span class="flow-act-sum-acts"><${Btn} size="xs" variant="secondary" icon="spark" busy=${busy} onClick=${ask}>${kept ? f.again : f.button}<//>
      ${busy ? html`<span class="muted small" role="status">${f.running}</span>` : Number.isInteger(left) ? html`<span class="muted small">${f.left(left)}</span>` : null}</span>` : null}
    ${err ? html`<p class="small verbbar-err" role="status">${err}</p>` : null}
  </div>`
}

/** The foot of Activity: a note in one line, and a document attached where the point has an open task */
function ActFoot({ row, feed, s, c }) {
  const f = T().flow.activity
  const [text, setText] = useState('')
  const [msg, setMsg] = useState(null)
  const file = useRef(null)
  const set = flowSettings(s)
  const v = text.replace(/\s+/g, ' ').trim()
  const busy = !!s.ui.busy?.[row.key]
  const attaching = !!s.ui.busy?.[`attach:${row.key}`]
  const add = async () => {
    if (!v) return
    const r = await c.flowNote(row.key, v)
    if (!r?.ok) return
    setText('')
    // written while a filter hides the notes: back to All, where it shows
    if (!['all', 'notes'].includes(s.ui.flowFilter ?? 'all')) c.flowFilter('all')
  }
  const pick = e => {
    const el = e.currentTarget
    const it = el.files?.[0] ?? null
    el.value = ''
    if (!it) return
    if (attachTooBig(it.size, s)) { setMsg(f.attach.tooBig(set.attach.max_mb)); return }
    setMsg(null)
    c.flowAttach(row.key, it)
  }
  const id = `flow-note-${row.key}`
  return html`<div class="flow-act-foot">
    ${feed?.can?.note !== false ? html`<form class="flow-act-noteform" onSubmit=${e => { e.preventDefault(); add() }}>
      <label class="sr-only" for=${id}>${f.note.label}</label>
      <input id=${id} class="input flow-act-note" type="text" maxlength="2000" placeholder=${f.note.label} value=${text}
        onInput=${e => setText(e.currentTarget.value)} />
      <${Btn} size="sm" variant="secondary" busy=${busy} disabled=${!v} onClick=${add}>${f.note.add}<//>
    </form>` : null}
    ${set.attach.enabled && feed?.can?.attach ? html`<span class="flow-act-attach">
      <input ref=${file} type="file" class="flow-act-file" hidden onChange=${pick} />
      <${Btn} size="sm" variant="ghost" busy=${attaching} onClick=${() => file.current?.click()}>${attaching ? f.attach.running : f.attach.button}<//>
    </span>` : null}
    ${msg ? html`<p class="small verbbar-err" role="status">${msg}</p>` : null}
  </div>`
}

/** Activity: the summary, the filters with their counts, the rows of the filter, the note and the attachment */
function ActivityPane({ row, entry, s, c }) {
  const f = T().flow.activity
  const feed = entry?.data ?? null
  if (!feed) return html`<p class="muted small" role="status">${entry?.status === 'error' ? entry.error ?? f.loading : f.loading}</p>`
  const filter = ACTIVITY_FILTERS.includes(s.ui.flowFilter) ? s.ui.flowFilter : 'all'
  const counts = activityCounts(feed)
  const rows = activityRows(feed, filter)
  return html`<div class="flow-act">
    <${Summary} row=${row} feed=${feed} s=${s} c=${c} />
    <div class="flow-act-filters"><${Segmented} label=${f.filters} values=${ACTIVITY_FILTERS.map(id => [id, `${f.filter[id]} ${counts[id]}`])}
      current=${filter} onPick=${v => c.flowFilter(v)} /></div>
    ${rows.length ? html`<ol class="flow-act-rows">${rows.map(r => html`<${ActRow} key=${r.id} r=${r} c=${c} />`)}</ol>`
      : html`<p class="muted small">${(feed.rows ?? []).length ? f.noneHere : f.none}</p>`}
    ${feed.more ? html`<p class="muted small">${f.more}</p>` : null}
    <${ActFoot} row=${row} feed=${feed} s=${s} c=${c} />
  </div>`
}

/** The tab bar under the card and the pane of the tab chosen; the task's file and the feed are read here when the
 *  point opens, and again when they went stale */
export function PointTabs({ x, s, c }) {
  const f = T().flow
  const keys = useRoving()
  const tabs = pointTabs(x)
  const row = tabs.length ? x.row : null
  const slug = row?.task ?? null
  const entry = slug ? s.details?.task?.[slug] : null
  const act = row ? s.details?.activity?.[row.key] : null
  const ver = s.model?.collected_ms ?? 0
  useEffect(() => { if (slug && detailNeedsLoad(entry, ver)) c.loadTask(slug) }, [slug, ver, entry?.stale])
  useEffect(() => { if (row && detailNeedsLoad(act, ver)) c.loadActivity(row.key) }, [row?.key, ver, act?.stale])
  if (!row) return null
  const detail = entry?.data ?? null
  const feed = act?.data ?? null
  const tab = pointTab(tabs, s.ui.flowTab)
  const steps = stepsOf(detail)
  const rel = relatedOf(x, s, detail)
  const n = { steps: steps.length ? `${steps.filter(st => st.done).length}/${steps.length}` : null, activity: feed ? String(activityCounts(feed).all) : null,
    related: rel.rows.length + rel.paths.length ? String(rel.rows.length + rel.paths.length) : null }
  const pane = tab === 'steps' ? html`<${StepsPane} steps=${steps} />`
    : tab === 'activity' ? html`<${ActivityPane} row=${row} entry=${act} s=${s} c=${c} />`
      : tab === 'related' ? html`<${RelatedPane} rel=${rel} />`
        : html`<${DescPane} row=${row} detail=${detail} entry=${entry} s=${s} c=${c} />`
  return html`<section class="flow-ptabs" aria-label=${f.ptabs.label}>
    <div class="flow-ptabs-bar" role="tablist" aria-label=${f.ptabs.label} ref=${keys.ref} onKeyDown=${keys.onKeyDown}>
      ${tabs.map(id => html`<button type="button" key=${id} role="tab" id=${`flow-ptab-${id}`} data-tab=${id} aria-selected=${String(tab === id)}
        aria-controls="flow-ptab-pane" class=${`flow-ptab${tab === id ? ' is-on' : ''}`} onClick=${() => tab !== id && c.flowTab(id)}>${f.ptabs[id]}${n[id]
          ? html` <span class="flow-ptab-n">${n[id]}</span>` : null}</button>`)}
    </div>
    <div class="flow-ptabs-pane" id="flow-ptab-pane" role="tabpanel" aria-labelledby=${`flow-ptab-${tab}`}>${pane}</div>
  </section>`
}
