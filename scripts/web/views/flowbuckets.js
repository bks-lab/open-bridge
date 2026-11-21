// SPDX-License-Identifier: MIT
// The cockpit, Work through by the briefing's buckets (cockpit.flow.buckets, on by default; docs/bridge-cockpit.md,
// Buckets): the page's behaviour once its switch is on, in place of the overview and the right column. Left the
// briefing's buckets in the profile's order, each with its count, the open one with its points under it. The middle
// shows the open bucket's head (its title, what it means, what its answers do) and one card at a time: its kind and
// facts as small marks, its title, one sentence Next (logic.js nextSentence: what the tab asks, the card's step, a
// fixed sentence per bucket), the bucket's answers as big buttons with the first one strong (logic.js bucketAnswers:
// the same acts as the briefing's answers, a tab's own answers first), its number in the printed briefing, and under
// More everything else the page offers on a point (views/flowside.js FlowAside: the states, Hand over, the fields;
// views/flowtabs.js PointTabs: Description, Steps, Activity). An answer moves on to the next point by itself (the card
// is held by its id, logic.js focusIndex); the walk bar under it only goes back and forth, it never decides. After the
// last point of a bucket the page offers the next bucket that holds one.
// Every point ends with the fixed, quiet answer Obsolete (buckets.js bucketAnswers), which asks first in place; under
// the card stands the free line (views/flowinstruct.js InstructLine: Instruct and Ask) for what the buttons do not cover.
// For the mouse: no text names a key.
// The rules every component keeps stand at the head of components.js.

import { html, useEffect, useState } from '../vendor/htm-preact-3.1.1.module.js'
import {
  answerMark, bucketAnswers, bucketDefs, bucketPoints, detailNeedsLoad, errorText, flowParts, focusIndex, formatDay, instructScope, nextSentence, openBucket, parseDate,
  pickDays, pointArea, pointKindWord, pointName, replySend, runningOf, short, viewBucket,
} from '../logic.js'
import { T, language } from '../text.js'
import { WorkSwitch } from './day.js'
import { FlowAside } from './flowside.js'
import { InstructLine } from './flowinstruct.js'
import { PointTabs } from './flowtabs.js'
import { Btn } from './parts.js'

const isTab = x => !!x?.tab && (x.kind === 'tab' || x.kind === 'start' || x.kind === 'back')

/** A point's title: a tab's name for a tab, else its row's name */
const pointTitleOf = x => (isTab(x) ? x.tab.name : x?.row ? pointName(x.row) : x?.title ?? x?.id ?? '')

/** An inbox item's detail, read when its card is in front and once stale (as views/flowpoint.js reads it) */
function useItemDetail(x, s, c) {
  const id = x?.row?.inbox_id ?? null
  const entry = id ? s.details?.inbox?.[id] ?? null : null
  const ver = s.model?.collected_ms ?? 0
  useEffect(() => { if (id && detailNeedsLoad(entry, ver)) c.loadInbox(id) }, [id, ver, entry?.stale])
}

/** The day picker of an answer that needs a day first (plan's schedule, waiting's wait): a few days, another one */
function DayPick({ s, onPick, onCancel, busy, uid = 'fb-pick-day' }) {
  const f = T().flow.buckets.pick
  const [own, setOwn] = useState('')
  const now = s.now || Date.now()
  const day = parseDate(own, now)
  return html`<div class="fb-pick" role="group" aria-label=${f.title}>
    <p class="label-caps">${f.title}</p>
    <div class="btn-row">
      ${pickDays(now).map(([k, iso]) => html`<${Btn} key=${k} size="sm" variant="secondary" busy=${busy} title=${iso}
        onClick=${() => onPick(iso)}>${f[k]}<//>`)}
    </div>
    <div class="field-row fb-pick-own">
      <label class="sr-only" for=${uid}>${f.own}</label>
      <input id=${uid} class="input" type="date" value=${own} placeholder=${f.own} onInput=${e => setOwn(e.currentTarget.value)} />
      <${Btn} size="sm" variant="primary" busy=${busy} disabled=${!day} onClick=${() => day && onPick(day)}>${f.set}<//>
      <${Btn} size="sm" variant="ghost" onClick=${onCancel}>${f.cancel}<//>
    </div>
  </div>`
}

/** The line an answer in words opens (a tab that asks for a number or a choice): the words go to the tab as the
 *  tab's own answer (tab_send, guarded by the question it answers), Cancel closes it */
function SayLine({ onSend, onCancel, busy, uid = 'fb-say-text' }) {
  const f = T().flow.buckets
  const [text, setText] = useState('')
  const words = text.trim()
  return html`<div class="fb-say" role="group" aria-label=${f.sayLabel}>
    <form class="field-row" onSubmit=${e => { e.preventDefault?.(); if (words) onSend(words) }}>
      <label class="sr-only" for=${uid}>${f.sayLabel}</label>
      <input id=${uid} class="input" type="text" value=${text} placeholder=${f.sayLabel} onInput=${e => setText(e.currentTarget.value)} />
      <${Btn} size="sm" variant="primary" busy=${busy} disabled=${!words} onClick=${() => words && onSend(words)}>${f.saySend}<//>
      <${Btn} size="sm" variant="ghost" onClick=${onCancel}>${f.sayCancel}<//>
    </form>
  </div>`
}

/** The answers of a point in its bucket and what a click on one does, the one place every view sends an answer
 *  from (the card here, the bar of a row on Due, By source, By Jev and the tabs column): a tab's own answer goes
 *  to the tab (c.reply) and is marked answered, a verb of the server goes out as c.act, an answer that needs a
 *  day opens the day picker first, one that asks first (Obsolete) its confirm in place (`confirm`, sent by `run(a,
 *  null, true)`). `onDone` runs once an answer went through (the card moves on) */
export function useBucketAnswer(x, bucket, s, c, onDone = null) {
  const lang = language()
  const t = T()
  const [pick, setPick] = useState(null)
  const [confirm, setConfirm] = useState(null)
  const [note, setNote] = useState(null)
  const [say, setSay] = useState(null)
  const row = x?.row ?? null
  const tab = x?.tab ?? null
  const answers = x ? bucketAnswers(x, bucket, s, lang) : []
  const busy = !!(s.ui?.busy?.[row?.key] || (tab && s.ui?.busy?.[tab.ref]))
  const run = async (a, day = null, sure = false) => {
    setNote(null)
    if (a.confirm && !sure) { setPick(null); setSay(null); setConfirm(a); return }
    setConfirm(null)
    if (a.run.kind === 'pick' && !day) { setSay(null); setPick(a); return }
    // an answer in words: the line opens first, `day` carries the words once they are sent (SayLine)
    if (a.run.kind === 'say' && !day) { setPick(null); setSay(a); return }
    if (a.run.kind === 'reply' || a.run.kind === 'say') {
      const go = a.run.kind === 'say' ? replySend(a.run.tab, day) : a.run
      const r = await c.reply(go.verb, go.args)
      if (r?.refused) { setNote(errorText(r.error, t)); return }
      if (!r?.ok) { if (r?.note) setNote(r.note); return }
      setSay(null)
      c.markAnswered?.(tab.ref, answerMark(tab, a.run.kind === 'say' ? day : a.label, Date.now()))
      onDone?.()
      return
    }
    const go = a.run.kind === 'pick' ? a.run.then(day) : a.run
    const r = await c.act(go.verb, go.args)
    setPick(null)
    if (Array.isArray(r?.manual) && r.manual.length) { setNote(r.manual.join('\n')); return }
    if (r?.ok) onDone?.()
    else if (r?.note) setNote(r.note)
  }
  return { answers, run, pick, setPick, confirm, setConfirm, note, busy, say, setSay }
}

/** The answers as buttons, in their order: the strong one where `strong` says so, a quiet one (Obsolete) a ghost,
 *  one whose confirm is open its question in place, Yes and Cancel */
function AnswerButtons({ list, strong, size, busy, pick, confirm, run, setConfirm, max }) {
  const f = T().flow.buckets
  return list.map(a => (confirm?.id === a.id
    ? html`<span key=${a.id} class="fb-confirm" role="group" aria-label=${f.obsoleteAsk}>
        <span class="fb-confirm-q small">${f.obsoleteAsk}</span>
        <${Btn} size=${size} variant="secondary" busy=${busy} cls="fb-confirm-yes" onClick=${() => run(a, null, true)}>${f.obsoleteYes}<//>
        <${Btn} size=${size} variant="ghost" cls="fb-confirm-no" onClick=${() => setConfirm(null)}>${f.obsoleteNo}<//>
      </span>`
    : html`<${Btn} key=${a.id} size=${size} variant=${strong(a) ? 'primary' : a.quiet ? 'ghost' : 'secondary'} busy=${busy}
        pressed=${pick?.id === a.id ? true : undefined} title=${a.quiet ? f.obsoleteTip : a.label} cls=${`fb-answer fb-answer-${a.meaning}${a.quiet ? ' fb-quiet' : ''}`}
        onClick=${() => run(a)}>${short(a.label, max)}<//>`))
}

/** A point's bucket as one small chip, the bucket's title, with its number in the printed briefing beside it */
export function BucketChip({ x, bucket, s, nr: withNr = true }) {
  const lang = language()
  const f = T().flow.buckets
  const def = bucketDefs(s, lang).find(b => b.id === bucket)
  if (!def) return null
  const nr = withNr ? x?.row?.brief_nr : null
  return html`<span class="fb-chips"><span class=${`chip fb-chip fb-chip-${bucket}`} title=${f.sub[bucket]}>${def.title}</span>${Number.isInteger(nr)
    ? html`<span class="chip fb-chip-nr mono" title=${f.inBriefing(nr, null)}>${f.nr(nr)}</span>` : null}</span>`
}

/** The answers of a point on a row of a list: its bucket chip, the first answer strong, the rest under one More,
 *  the same answers and acts as the card (BucketCard). `chip` false leaves the chip out where the row shows it */
export function BucketBar({ x, s, c, size = 'xs', bucket = null, chip = true, nr = true }) {
  const f = T().flow.buckets
  const b = bucket ?? viewBucket(x)
  const { answers, run, pick, setPick, confirm, setConfirm, note, busy, say, setSay } = useBucketAnswer(x, b, s, c)
  const [more, setMore] = useState(false)
  // the strong one is the first the bucket offers, never the quiet Obsolete, which stands last under More
  const first = answers[0] && !answers[0].quiet ? answers[0] : null
  const rest = first ? answers.slice(1) : answers
  const btns = (list, strong) => html`<${AnswerButtons} list=${list} strong=${() => strong} size=${size} busy=${busy} pick=${pick}
    confirm=${confirm} run=${run} setConfirm=${setConfirm} max=${40} />`
  const uid = `fb-pick-${String(x?.id ?? 'x').replace(/[^\w-]/g, '-')}`
  return html`<span class="fb-bar">
    ${chip ? html`<${BucketChip} x=${x} bucket=${b} s=${s} nr=${nr} />` : null}
    ${first ? btns([first], true) : null}
    ${rest.length ? html`<${Btn} size=${size} variant="ghost" pressed=${more} cls="fb-bar-more" onClick=${() => setMore(!more)}>${f.more}<//>` : null}
    ${more ? html`<span class="fb-bar-rest">${btns(rest, false)}</span>` : null}
    ${pick ? html`<${DayPick} s=${s} busy=${busy} uid=${uid} onPick=${day => run(pick, day)} onCancel=${() => setPick(null)} />` : null}
    ${say ? html`<${SayLine} busy=${busy} uid=${`${uid}-say`} onSend=${words => run(say, words)} onCancel=${() => setSay(null)} />` : null}
    ${note ? html`<span class="fb-note small" role="status">${note}</span>` : null}
  </span>`
}

/** One point as a card: its marks, its title, Next, the bucket's answers, its number in the briefing, More */
export function BucketCard({ x, bucket, s, c, onDone = null }) {
  const lang = language()
  const t = T()
  const f = t.flow.buckets
  useItemDetail(x, s, c)
  const row = x.row ?? null
  const tab = x.tab ?? null
  const { answers, run, pick, setPick, confirm, setConfirm, note, busy, say, setSay } = useBucketAnswer(x, bucket, s, c, () => { c.flowDecided?.(); onDone?.() })
  const marks = [pointKindWord(x, lang), pointArea(x), row?.due ? f.due(formatDay(String(row.due).slice(0, 10), lang)) : null,
    row?.gate === 'only-you' ? f.onlyYou : null, bucket === 'waiting' && (x.checkin?.who ?? row?.checkin?.who) ? f.with(x.checkin?.who ?? row.checkin.who) : null]
    .filter(Boolean)
  // a tab that asks is named by its tab (the way it reads in the terminal), the task it works on under it
  const title = pointTitleOf(x)
  const sub = row && isTab(x) ? t.flow.forTask(pointName(row)) : null
  const first = answers[0]?.label ?? null
  return html`<article class="fb-card" aria-labelledby="fb-title">
    <div class="fb-marks">${marks.map(m => html`<span class="fb-mark">${m}</span>`)}</div>
    <h2 id="fb-title" class="fb-title">${title}</h2>
    ${sub ? html`<p class="fb-sub muted">${sub}</p>` : null}
    <div class="fb-next"><span class="label-caps">${f.nextLabel}</span><p>${nextSentence(x, bucket, s, lang)}</p></div>
    ${answers.length ? html`<div class="fb-answers" role="group" aria-label=${f.nextLabel}>
      <${AnswerButtons} list=${answers} strong=${a => a === answers[0] && !a.quiet} size="sm" busy=${busy} pick=${pick} confirm=${confirm}
        run=${run} setConfirm=${setConfirm} max=${60} />
    </div>` : null}
    ${pick ? html`<${DayPick} s=${s} busy=${busy} onPick=${day => run(pick, day)} onCancel=${() => setPick(null)} />` : null}
    ${say ? html`<${SayLine} busy=${busy} onSend=${words => run(say, words)} onCancel=${() => setSay(null)} />` : null}
    ${note ? html`<p class="fb-note small" role="status">${note}</p>` : null}
    ${Number.isInteger(row?.brief_nr) ? html`<p class="fb-nr muted small">${f.inBriefing(row.brief_nr, first && !tab ? first.toLowerCase() : null)}</p>` : null}
    <details class="fb-more">
      <summary>${f.more}</summary>
      <div class="fb-more-body">
        ${tab?.ask?.text ? html`<pre class="fb-screen mono">${tab.ask.text}</pre>` : null}
        <${FlowAside} x=${x} s=${s} c=${c} />
        ${row ? html`<${PointTabs} x=${x} s=${s} c=${c} />` : null}
      </div>
    </details>
  </article>`
}

/** On a narrow screen the card stands under the list: a point picked there brings its card into view */
function cardIntoView() {
  if (typeof window === 'undefined' || !window.matchMedia?.('(max-width: 960px)')?.matches) return
  const calm = window.matchMedia('(prefers-reduced-motion: reduce)')?.matches
  window.requestAnimationFrame?.(() => document.querySelector?.('.fb-main')?.scrollIntoView?.({ block: 'start', behavior: calm ? 'auto' : 'smooth' }))
}

/** The page by buckets: the buckets on the left, the open one's head, one card, the walk under it */
export function BucketBody({ s, c }) {
  const lang = language()
  const t = T()
  const f = t.flow.buckets
  const parts = flowParts(s)
  const { buckets, all } = bucketPoints(s, lang, parts)
  // what runs (an agent at work) and what an agent finished to read are no decision: they stand quiet under the
  // buckets, each a way to its entry, so nothing that runs is lost from the page
  const runs = runningOf(parts)
  const running = [...runs.sessions.map(v => ({ id: v.entry?.id ?? v.id, title: v.entry?.title ?? v.tab?.name ?? v.session?.title ?? '', open: v.entry ? () => c.flowRun(v.entry.id) : () => c.flowRunning() })),
    ...runs.loose.map(e => ({ id: e.id, title: e.title ?? e.tab?.name ?? '', open: () => c.flowRun(e.id) }))]
  const reads = (parts.read ?? []).map((r, k) => ({ id: r.id, title: r.title ?? r.row?.title ?? '', open: () => c.flowReadOpen(r.id, k) }))
  const open = openBucket(buckets, s.ui?.flowBucket)
  const points = open?.points ?? []
  const i = focusIndex(points, s.ui?.flowBucketAt)
  const x = points[i] ?? null
  const onwards = open ? buckets.find(b => b.id !== open.id && b.points.length) ?? null : null
  // an answer moves on to the next point, also where the point stays in its bucket (Wait on a task that waits, a
  // tab's own answer): the next one is held by its id, at the place the answered one leaves free
  const onwardsAfter = () => c.flowBucketGo(points[i + 1]?.id ?? null, i)
  // what each answer of the open bucket does, and the fixed last one every point has
  const legend = open ? [f.legend[open.id]?.(...open.options.map(o => o.charAt(0).toUpperCase() + o.slice(1))), f.obsoleteLegend(f.obsolete)]
    .filter(Boolean).join(' ') : ''
  // the free line under the card for what the buttons do not cover, scoped to the point (views/flowinstruct.js)
  const scope = x && !x.readOnly ? instructScope(x, [], new Set(), null, s) : null
  return html`<div class="col col-page flow flow-buckets">
    <header class="page-head flow-head">
      <${WorkSwitch} s=${s} c=${c} />
      <p class="muted small">${t.flow.count(all.length, 0, 0).split(' · ')[0]}</p>
    </header>
    <div class="fb-grid">
      <nav class="fb-side" aria-label=${f.label}>
        <h2 class="label-caps">${f.label}</h2>
        <ul class="fb-buckets">${buckets.map(b => html`<li key=${b.id}>
          <button type="button" class=${`fb-bucket${b.id === open?.id ? ' is-open' : ''}${b.points.length ? '' : ' is-empty'}`} data-bucket=${b.id}
            aria-current=${b.id === open?.id ? 'true' : undefined} onClick=${() => c.flowBucket(b.id)}>
            <span class="fb-bucket-name">${b.title}<span class="fb-bucket-sub muted small">${f.sub[b.id]}</span></span>
            <span class="fb-bucket-n mono">${f.count(b.points.length)}</span>
          </button>
          ${b.id === open?.id && b.points.length ? html`<ul class="fb-points">${b.points.map((p, k) => html`<li key=${p.id}>
            <button type="button" class=${`fb-point${p.id === x?.id ? ' is-current' : ''}`} aria-current=${p.id === x?.id ? 'true' : undefined}
              title=${pointTitleOf(p)} onClick=${() => { c.flowBucketGo(p.id, k); cardIntoView() }}>${short(pointTitleOf(p), 70)}</button>
          </li>`)}</ul>` : null}
        </li>`)}</ul>
        ${running.length || reads.length ? html`<div class="fb-running">
          ${running.length ? html`<h3 class="label-caps">${t.flow.lane.label}</h3>
            <ul class="fb-points">${running.map(e => html`<li key=${e.id}><button type="button" class="fb-point" title=${e.title} onClick=${e.open}>${short(e.title, 70)}</button></li>`)}</ul>` : null}
          ${reads.length ? html`<h3 class="label-caps">${t.flow.kind.done}</h3>
            <ul class="fb-points">${reads.map(e => html`<li key=${e.id}><button type="button" class="fb-point" title=${e.title} onClick=${e.open}>${short(e.title, 70)}</button></li>`)}</ul>` : null}
        </div>` : null}
      </nav>
      <section class="fb-main" aria-label=${open?.title ?? f.label}>
        ${open ? html`<header class="fb-head">
          <h2 class="fb-head-title">${open.title}</h2><span class="fb-head-sub muted">${f.sub[open.id]}</span>
          ${legend ? html`<p class="fb-legend muted small">${legend}</p>` : null}
        </header>` : null}
        ${x ? html`<${BucketCard} key=${x.id} x=${x} bucket=${open.id} s=${s} c=${c} onDone=${onwardsAfter} />`
          : html`<div class="fb-empty"><p>${all.length ? f.cleared : f.empty}</p>
            ${onwards ? html`<${Btn} size="sm" variant="primary" onClick=${() => c.flowBucket(onwards.id)}>${f.onwards(onwards.title)}<//>`
              : html`<p class="muted">${f.allDone}</p>`}</div>`}
        ${x ? html`<div class="fb-dock flow-dock"><${InstructLine} key=${x.id} scope=${scope} x=${x} s=${s} c=${c} /></div>` : null}
        ${x ? html`<div class="fb-walk">
          <${Btn} size="sm" variant="secondary" icon="back" disabled=${i === 0} onClick=${() => c.flowBucketGo(points[i - 1].id, i - 1)}>${f.prev}<//>
          <span class="fb-pos muted small">${f.pos(i + 1, points.length)}</span>
          <${Btn} size="sm" variant="secondary" disabled=${i >= points.length - 1} onClick=${() => c.flowBucketGo(points[i + 1].id, i + 1)}>${f.next2}<//>
        </div>` : null}
      </section>
    </div>
  </div>`
}
