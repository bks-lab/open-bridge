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
// For the mouse: no text names a key.
// The rules every component keeps stand at the head of components.js.

import { html, useEffect, useState } from '../vendor/htm-preact-3.1.1.module.js'
import {
  answerMark, bucketAnswers, bucketDefs, bucketPoints, detailNeedsLoad, errorText, focusIndex, formatDay, nextSentence, openBucket, parseDate, pickDays,
  pointArea, pointKindWord, pointName, short, viewBucket,
} from '../logic.js'
import { T, language } from '../text.js'
import { WorkSwitch } from './day.js'
import { FlowAside } from './flowside.js'
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

/** The answers of a point in its bucket and what a click on one does, the one place every view sends an answer
 *  from (the card here, the bar of a row on Due, By source, By Jev and the tabs column): a tab's own answer goes
 *  to the tab (c.reply) and is marked answered, a verb of the server goes out as c.act, an answer that needs a
 *  day opens the day picker first. `onDone` runs once an answer went through (the card moves on) */
export function useBucketAnswer(x, bucket, s, c, onDone = null) {
  const lang = language()
  const t = T()
  const [pick, setPick] = useState(null)
  const [note, setNote] = useState(null)
  const row = x?.row ?? null
  const tab = x?.tab ?? null
  const answers = x ? bucketAnswers(x, bucket, s, lang) : []
  const busy = !!(s.ui?.busy?.[row?.key] || (tab && s.ui?.busy?.[tab.ref]))
  const run = async (a, day = null) => {
    setNote(null)
    if (a.run.kind === 'pick' && !day) { setPick(a); return }
    if (a.run.kind === 'reply') {
      const r = await c.reply(a.run.verb, a.run.args)
      if (r?.refused) { setNote(errorText(r.error, t)); return }
      if (!r?.ok) { if (r?.note) setNote(r.note); return }
      c.markAnswered?.(tab.ref, answerMark(tab, a.label, Date.now()))
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
  return { answers, run, pick, setPick, note, busy }
}

/** A point's bucket as one small chip, the bucket's title, with its number in the printed briefing beside it */
export function BucketChip({ x, bucket, s }) {
  const lang = language()
  const f = T().flow.buckets
  const def = bucketDefs(s, lang).find(b => b.id === bucket)
  if (!def) return null
  const nr = x?.row?.brief_nr
  return html`<span class="fb-chips"><span class=${`chip fb-chip fb-chip-${bucket}`} title=${f.sub[bucket]}>${def.title}</span>${Number.isInteger(nr)
    ? html`<span class="chip fb-chip-nr mono" title=${f.inBriefing(nr, null)}>${f.nr(nr)}</span>` : null}</span>`
}

/** The answers of a point on a row of a list: its bucket chip, the first answer strong, the rest under one More,
 *  the same answers and acts as the card (BucketCard). `chip` false leaves the chip out where the row shows it */
export function BucketBar({ x, s, c, size = 'xs', bucket = null, chip = true }) {
  const f = T().flow.buckets
  const b = bucket ?? viewBucket(x)
  const { answers, run, pick, setPick, note, busy } = useBucketAnswer(x, b, s, c)
  const [more, setMore] = useState(false)
  const [first, ...rest] = answers
  const btn = (a, strong) => html`<${Btn} key=${a.id} size=${size} variant=${strong ? 'primary' : 'secondary'} busy=${busy}
    pressed=${pick?.id === a.id ? true : undefined} title=${a.label} cls=${`fb-answer fb-answer-${a.meaning}`} onClick=${() => run(a)}>${short(a.label, 40)}<//>`
  const uid = `fb-pick-${String(x?.id ?? 'x').replace(/[^\w-]/g, '-')}`
  return html`<span class="fb-bar">
    ${chip ? html`<${BucketChip} x=${x} bucket=${b} s=${s} />` : null}
    ${first ? btn(first, true) : null}
    ${rest.length ? html`<${Btn} size=${size} variant="ghost" pressed=${more} cls="fb-bar-more" onClick=${() => setMore(!more)}>${f.more}<//>` : null}
    ${more ? html`<span class="fb-bar-rest">${rest.map(a => btn(a, false))}</span>` : null}
    ${pick ? html`<${DayPick} s=${s} busy=${busy} uid=${uid} onPick=${day => run(pick, day)} onCancel=${() => setPick(null)} />` : null}
    ${note ? html`<span class="fb-note small" role="status">${note}</span>` : null}
  </span>`
}

/** One point as a card: its marks, its title, Next, the bucket's answers, its number in the briefing, More */
export function BucketCard({ x, bucket, s, c }) {
  const lang = language()
  const t = T()
  const f = t.flow.buckets
  useItemDetail(x, s, c)
  const row = x.row ?? null
  const tab = x.tab ?? null
  const { answers, run, pick, setPick, note, busy } = useBucketAnswer(x, bucket, s, c, () => c.flowDecided?.())
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
      ${answers.map((a, i) => html`<${Btn} key=${a.id} size="sm" variant=${i === 0 ? 'primary' : 'secondary'} busy=${busy}
        pressed=${pick?.id === a.id ? true : undefined} title=${a.label} cls=${`fb-answer fb-answer-${a.meaning}`} onClick=${() => run(a)}>${short(a.label, 60)}<//>`)}
    </div>` : null}
    ${pick ? html`<${DayPick} s=${s} busy=${busy} onPick=${day => run(pick, day)} onCancel=${() => setPick(null)} />` : null}
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

/** The page by buckets: the buckets on the left, the open one's head, one card, the walk under it */
export function BucketBody({ s, c }) {
  const lang = language()
  const t = T()
  const f = t.flow.buckets
  const { buckets, all } = bucketPoints(s, lang)
  const open = openBucket(buckets, s.ui?.flowBucket)
  const points = open?.points ?? []
  const i = focusIndex(points, s.ui?.flowBucketAt)
  const x = points[i] ?? null
  const onwards = open ? buckets.find(b => b.id !== open.id && b.points.length) ?? null : null
  const legend = open ? f.legend[open.id]?.(...open.options.map(o => o.charAt(0).toUpperCase() + o.slice(1))) ?? '' : ''
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
              title=${pointTitleOf(p)} onClick=${() => c.flowBucketGo(p.id, k)}>${short(pointTitleOf(p), 70)}</button>
          </li>`)}</ul>` : null}
        </li>`)}</ul>
      </nav>
      <section class="fb-main" aria-label=${open?.title ?? f.label}>
        ${open ? html`<header class="fb-head">
          <h2 class="fb-head-title">${open.title}</h2><span class="fb-head-sub muted">${f.sub[open.id]}</span>
          ${legend ? html`<p class="fb-legend muted small">${legend}</p>` : null}
        </header>` : null}
        ${x ? html`<${BucketCard} key=${x.id} x=${x} bucket=${open.id} s=${s} c=${c} />`
          : html`<div class="fb-empty"><p>${all.length ? f.cleared : f.empty}</p>
            ${onwards ? html`<${Btn} size="sm" variant="primary" onClick=${() => c.flowBucket(onwards.id)}>${f.onwards(onwards.title)}<//>`
              : html`<p class="muted">${f.allDone}</p>`}</div>`}
        ${x ? html`<div class="fb-walk">
          <${Btn} size="sm" variant="secondary" icon="back" disabled=${i === 0} onClick=${() => c.flowBucketGo(points[i - 1].id, i - 1)}>${f.prev}<//>
          <span class="fb-pos muted small">${f.pos(i + 1, points.length)}</span>
          <${Btn} size="sm" variant="secondary" disabled=${i >= points.length - 1} onClick=${() => c.flowBucketGo(points[i + 1].id, i + 1)}>${f.next2}<//>
        </div>` : null}
      </section>
    </div>
  </div>`
}
