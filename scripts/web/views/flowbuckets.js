// SPDX-License-Identifier: MIT
// The cockpit, Work through by the briefing's buckets (cockpit.flow.buckets, on by default; docs/bridge-cockpit.md,
// Buckets): the page's behaviour once its switch is on, in place of the overview and the right column. Every point
// answers who is on the move and when. Left, under "Who is on the move", the four buckets in the profile's order, each
// with who it means and its count, the open one with its points under it, then what is out of sight, only counted
// (later, the watch list, done today), then what runs. The middle shows the open bucket's head (its title and what Do
// it does there) and one card at a time: its kind and facts as small marks (a resting point says so, quietly), its
// title, what a tab asks, one sentence Next (logic.js nextSentence: what Do it does), the four answers every point
// takes (logic.js bucketAnswers: Do it strong, a tab's own answers in its place; Later ▾ with tomorrow, Monday, in a
// week, a picked day and the watch list; Done; Obsolete quiet and last, asked first in place with a note), its number
// in the printed briefing with the words the chat takes, and under More only: With … (you, the Bridge, a name), To
// the tab, Ask (views/flowinstruct.js InstructLine) and the fields (views/flowside.js Fields, views/flowtabs.js
// PointTabs). An answer moves on to the next point by itself (the card is held by its id, logic.js focusIndex); the
// walk bar under it only goes back and forth, it never decides. After the last point of a bucket the page offers the
// next bucket that holds one. Every answer goes out through c.act or c.reply, so the toast offers its undo.
// For the mouse: no text names a key.
// The rules every component keeps stand at the head of components.js.

import { html, useEffect, useState } from '../vendor/htm-preact-3.1.1.module.js'
import {
  answerMark, askQuestion, asideCounts, bucketAnswers, bucketDefs, bucketPoints, detailNeedsLoad, errorText, flowParts, focusIndex, formatDay, instructScope,
  isoDate, laterDays, nextSentence, openBucket, ownerChoices, parseDate, pointArea, pointKindWord, pointName, replySend, restingOf, runningOf, short, viewBucket,
  withNote, withWas,
} from '../logic.js'
import { T, language } from '../text.js'
import { WorkSwitch } from './day.js'
import { Fields } from './flowside.js'
import { InstructLine } from './flowinstruct.js'
import { PointTabs } from './flowtabs.js'
import { PointCard } from './flowpoint.js'
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

/** Later's menu: tomorrow, Monday, in a week (each with its day), a picked day, the watch list. `onChoose(choice,
 *  day)` sends the answer; a picked day must lie after today */
function LaterMenu({ a, s, busy, onChoose, uid = 'fb-later-day' }) {
  const f = T().flow.buckets
  const lang = language()
  const now = s.now || Date.now()
  const days = laterDays(now)
  const today = isoDate(now)
  const [picking, setPicking] = useState(false)
  const [own, setOwn] = useState('')
  const picked = parseDate(own, now)
  const day = picked && picked > today ? picked : null
  const has = k => a.run.choices.includes(k)
  return html`<div class="fb-later-menu" role="group" aria-label=${f.later.label}>
    ${['tomorrow', 'monday', 'week'].filter(has).map(k => html`<button type="button" key=${k} class="fb-later-item" data-choice=${k} disabled=${busy}
      onClick=${() => onChoose(k, days[k])}><span>${f.later[k]}</span><span class="fb-later-sub muted small">${formatDay(days[k], lang)}</span></button>`)}
    ${has('pick') ? html`<button type="button" class="fb-later-item" data-choice="pick" aria-expanded=${String(picking)} disabled=${busy}
      onClick=${() => setPicking(!picking)}><span>${f.later.pick}</span><span class="fb-later-sub muted small">${f.later.pickSub}</span></button>` : null}
    ${picking ? html`<div class="fb-later-pick field-row">
      <label class="sr-only" for=${uid}>${f.later.pick}</label>
      <input id=${uid} class="input" type="date" min=${days.tomorrow} value=${own} onInput=${e => setOwn(e.currentTarget.value)} />
      <${Btn} size="sm" variant="primary" busy=${busy} disabled=${!day} onClick=${() => day && onChoose('pick', day)}>${f.later.set}<//>
    </div>` : null}
    ${has('list') ? html`<hr class="fb-later-sep" /><button type="button" class="fb-later-item" data-choice="list" disabled=${busy}
      onClick=${() => onChoose('list', null)}><span>${f.later.list}</span><span class="fb-later-sub muted small">${f.later.listSub}</span></button>` : null}
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

/** The four answers of a point and what a click on one does, the one place every view sends an answer from (the
 *  card here, the bar of a row on Due, By source, By Jev and the tabs column): a tab's own answer goes to the tab
 *  (c.reply) and is marked answered, a verb of the server goes out as c.act, Later opens its menu first (`menu`, sent
 *  by `run(a, {choice, day})`), Obsolete its confirm in place (`confirm`, sent by `run(a, note, true)`). `onDone`
 *  runs once an answer went through (the card moves on) */
export function useBucketAnswer(x, bucket, s, c, onDone = null) {
  const lang = language()
  const t = T()
  const f = t.flow.buckets
  const [menu, setMenu] = useState(null)
  const [confirm, setConfirm] = useState(null)
  const [note, setNote] = useState(null)
  const [say, setSay] = useState(null)
  const row = x?.row ?? null
  const tab = x?.tab ?? null
  const answers = x ? bucketAnswers(x, bucket, s, lang) : []
  const busy = !!(s.ui?.busy?.[row?.key] || (tab && s.ui?.busy?.[tab.ref]))
  const closeAll = () => { setMenu(null); setSay(null); setConfirm(null) }
  const send = async (go, a) => {
    const r = await c.act(go.verb, go.args)
    closeAll()
    if (Array.isArray(r?.manual) && r.manual.length) { setNote(r.manual.join('\n')); return }
    if (r?.ok) onDone?.(a)
    else if (r?.note) setNote(r.note)
  }
  const run = async (a, arg = null, sure = false) => {
    setNote(null)
    if (a.confirm && !sure) { setMenu(null); setSay(null); setConfirm(a); return }
    if (a.run.kind === 'later' && !arg) { setSay(null); setConfirm(null); setMenu(menu?.id === a.id ? null : a); return }
    // an answer in words: the line opens first, `arg` carries the words once they are sent (SayLine)
    if (a.run.kind === 'say' && !arg) { setMenu(null); setConfirm(null); setSay(a); return }
    if (a.run.kind === 'reply' || a.run.kind === 'say') {
      const go = a.run.kind === 'say' ? replySend(a.run.tab, arg) : a.run
      const r = await c.reply(go.verb, go.args)
      if (r?.refused) { setNote(errorText(r.error, t)); return }
      if (!r?.ok) { if (r?.note) setNote(r.note); return }
      closeAll()
      c.markAnswered?.(tab.ref, answerMark(tab, a.run.kind === 'say' ? arg : a.label, Date.now()))
      onDone?.(a)
      return
    }
    const raw = a.run.kind === 'later' ? a.run.then(arg.choice, arg.day) : a.meaning === 'obsolete' ? withNote(a.run, arg, f) : a.run
    if (!raw) return
    await send(withWas(raw, row), a)
  }
  // With … under More: the step to you or the Bridge, or the point to a person (logic.js ownerChoices)
  const give = async go => { if (go) await send(go, { meaning: 'owner' }) }
  return { answers, run, menu, setMenu, confirm, setConfirm, note, busy, say, setSay, give }
}

/** Obsolete's question in place: a note why, optional, then Yes or Cancel */
function ObsoleteConfirm({ a, size, busy, run, onCancel }) {
  const f = T().flow.buckets
  const [why, setWhy] = useState('')
  const ask = a.label === f.obsoleteStream ? f.obsoleteAskStream : f.obsoleteAsk
  return html`<span class="fb-confirm" role="group" aria-label=${ask}>
    <span class="fb-confirm-q small">${ask}</span>
    <input class="input fb-confirm-note" type="text" value=${why} placeholder=${f.obsoleteNote} aria-label=${f.obsoleteNote}
      onInput=${e => setWhy(e.currentTarget.value)} />
    <${Btn} size=${size} variant="secondary" busy=${busy} cls="fb-confirm-yes" onClick=${() => run(a, why, true)}>${f.obsoleteYes}<//>
    <${Btn} size=${size} variant="ghost" cls="fb-confirm-no" onClick=${onCancel}>${f.obsoleteNo}<//>
  </span>`
}

/** The answers as buttons, in their order: the strong one (`primary`), Later with its menu under it, Done (on a
 *  stream with the word that it runs on), Obsolete a quiet ghost whose click opens its question in place */
function AnswerButtons({ list, size, busy, menu, confirm, run, setConfirm, max, s, uid }) {
  const f = T().flow.buckets
  return list.map(a => {
    const cls = `fb-answer fb-answer-${a.meaning}${a.quiet ? ' fb-quiet' : ''}`
    if (confirm?.id === a.id) return html`<${ObsoleteConfirm} key=${a.id} a=${a} size=${size} busy=${busy} run=${run} onCancel=${() => setConfirm(null)} />`
    const btn = html`<${Btn} key=${a.id} size=${size} variant=${a.primary ? 'primary' : a.quiet ? 'ghost' : 'secondary'} busy=${busy}
      pressed=${a.run.kind === 'later' ? menu?.id === a.id : undefined} title=${a.quiet ? f.obsoleteTip : a.label} cls=${cls}
      onClick=${() => run(a)}>${short(a.label, max)}<//>`
    if (a.run.kind === 'later') {
      return html`<span key=${a.id} class="fb-later">${btn}${menu?.id === a.id
        ? html`<${LaterMenu} a=${a} s=${s} busy=${busy} uid=${`${uid}-day`} onChoose=${(choice, day) => run(a, { choice, day })} />` : null}</span>`
    }
    if (a.meaning === 'done' && a.label === f.answers.doneStream) {
      return html`<span key=${a.id} class="fb-done-col">${btn}<small class="muted">${f.doneStreamSub}</small></span>`
    }
    return btn
  })
}

/** A point's bucket as one small chip, the bucket's title, with its number in the printed briefing beside it */
export function BucketChip({ x, bucket, s, nr: withNr = true }) {
  const lang = language()
  const f = T().flow.buckets
  const def = bucketDefs(s, lang).find(b => b.id === bucket)
  if (!def) return null
  const nr = withNr ? x?.row?.brief_nr : null
  return html`<span class="fb-chips"><span class=${`chip fb-chip fb-chip-${bucket}`} title=${f.sub[bucket]}>${def.title}</span>${Number.isInteger(nr)
    ? html`<span class="chip fb-chip-nr mono" title=${f.inBriefing(nr, f.say)}>${f.nr(nr)}</span>` : null}</span>`
}

/** The answers of a point on a row of a list: its bucket chip, the strong one, the rest under one More, the same
 *  answers and acts as the card (BucketCard). `chip` false leaves the chip out where the row shows it */
export function BucketBar({ x, s, c, size = 'xs', bucket = null, chip = true, nr = true }) {
  const f = T().flow.buckets
  const b = bucket ?? viewBucket(x)
  const { answers, run, menu, confirm, setConfirm, note, busy, say, setSay } = useBucketAnswer(x, b, s, c)
  const [more, setMore] = useState(false)
  const first = answers.find(a => a.primary) ?? null
  const rest = answers.filter(a => a !== first)
  const uid = `fb-bar-${String(x?.id ?? 'x').replace(/[^\w-]/g, '-')}`
  const btns = list => html`<${AnswerButtons} list=${list} size=${size} busy=${busy} menu=${menu} confirm=${confirm} run=${run}
    setConfirm=${setConfirm} max=${40} s=${s} uid=${uid} />`
  return html`<span class="fb-bar">
    ${chip ? html`<${BucketChip} x=${x} bucket=${b} s=${s} nr=${nr} />` : null}
    ${first ? btns([first]) : null}
    ${rest.length ? html`<${Btn} size=${size} variant="ghost" pressed=${more} cls="fb-bar-more" onClick=${() => setMore(!more)}>${f.more}<//>` : null}
    ${more ? html`<span class="fb-bar-rest">${btns(rest)}</span>` : null}
    ${say ? html`<${SayLine} busy=${busy} uid=${`${uid}-say`} onSend=${words => run(say, words)} onCancel=${() => setSay(null)} />` : null}
    ${note ? html`<span class="fb-note small" role="status">${note}</span>` : null}
  </span>`
}

/** With … under More: you and the Bridge for a task's step, a name for anyone; the one who has it now marked */
function OwnerPick({ x, s, give, busy }) {
  const f = T().flow.buckets
  const own = ownerChoices(x, s)
  const [name, setName] = useState('')
  const go = own.name(name)
  const words = { me: f.owner.me, bridge: f.owner.bridge }
  return html`<section class="fb-owner fb-more-part">
    <h3 class="label-caps">${f.owner.head}</h3>
    <div class="btn-row">
      ${own.choices.map(o => html`<${Btn} key=${o.who} size="sm" variant="secondary" busy=${busy} pressed=${own.current === o.who}
        disabled=${own.current === o.who} cls=${`fb-owner-${o.who}`} onClick=${() => give(o.run)}>${words[o.who]}<//>`)}
      <form class="field-row fb-owner-name" onSubmit=${e => { e.preventDefault?.(); give(go) }}>
        <label class="sr-only" for="fb-owner-name">${f.owner.name}</label>
        <input id="fb-owner-name" class="input" type="text" maxlength="60" value=${name} placeholder=${f.owner.name}
          onInput=${e => setName(e.currentTarget.value)} />
        <${Btn} size="sm" variant="secondary" busy=${busy} disabled=${!go} onClick=${() => give(go)}>${f.owner.give}<//>
      </form>
    </div>
  </section>`
}

/** One point as a card: its marks, its title, what a tab asks, Next, the four answers, its number in the briefing,
 *  and under More: With …, To the tab, Ask, the fields */
export function BucketCard({ x, bucket, s, c, onDone = null }) {
  const lang = language()
  const t = T()
  const f = t.flow.buckets
  useItemDetail(x, s, c)
  const row = x.row ?? null
  const tab = x.tab ?? null
  // an answer that went out takes its point out of the bucket at once (answeredHere)
  const { answers, run, menu, confirm, setConfirm, note, busy, say, setSay, give } = useBucketAnswer(x, bucket, s, c, () => {
    c.flowDecided?.()
    c.flowAnswered?.(x.id, bucket)
    onDone?.()
  })
  const rest = row ? restingOf(row) : null
  const who = bucket === 'waiting' ? x.checkin?.who ?? row?.checkin?.who ?? null : null
  const marks = [[pointKindWord(x, lang)], [pointArea(x)], [row?.due ? f.due(formatDay(String(row.due).slice(0, 10), lang)) : null],
    [row?.gate === 'only-you' ? f.onlyYou : null], [who ? f.with(who) : null], [rest ? f.resting(rest) : null, 'fb-mark-quiet', f.restingTip]]
    .filter(m => m[0])
  // a tab that asks is named by its tab (the way it reads in the terminal), the task it works on under it
  const title = pointTitleOf(x)
  const sub = row && isTab(x) ? t.flow.forTask(pointName(row)) : null
  const question = isTab(x) && tab.ask?.text ? short(askQuestion(tab.ask.text), 400) : null
  const tabRef = tab?.ref ?? row?.tab?.ref ?? null
  // the free line for what the buttons do not cover, scoped to the point (views/flowinstruct.js), under More
  const scope = !x.readOnly ? instructScope(x, [], new Set(), null, s) : null
  return html`<article class="fb-card" aria-labelledby="fb-title">
    <div class="fb-marks">${marks.map(([m, cls, tip]) => html`<span class=${`fb-mark${cls ? ` ${cls}` : ''}`} title=${tip}>${m}</span>`)}</div>
    <h2 id="fb-title" class="fb-title">${title}</h2>
    ${sub ? html`<p class="fb-sub muted">${sub}</p>` : null}
    ${question ? html`<div class="fb-question"><span class="label-caps">${f.asks}</span><p>${question}</p></div>` : null}
    <div class="fb-next"><span class="label-caps">${f.nextLabel}</span><p>${nextSentence(x, bucket, s, lang)}</p></div>
    ${answers.length ? html`<div class="fb-answers" role="group" aria-label=${f.nextLabel}>
      <${AnswerButtons} list=${answers} size="sm" busy=${busy} menu=${menu} confirm=${confirm} run=${run} setConfirm=${setConfirm}
        max=${60} s=${s} uid="fb-card" />
    </div>` : null}
    ${say ? html`<${SayLine} busy=${busy} onSend=${words => run(say, words)} onCancel=${() => setSay(null)} />` : null}
    ${note ? html`<p class="fb-note small" role="status">${note}</p>` : null}
    ${isTab(x) && tab.ask?.draft ? html`<p class="fb-note fb-draft muted small">${tab.ask.suggestion ? t.reply.draft : t.reply.typed}</p>` : null}
    ${Number.isInteger(row?.brief_nr) ? html`<p class="fb-nr muted small">${f.inBriefing(row.brief_nr, f.say)}</p>` : null}
    <details class="fb-more">
      <summary>${f.more}</summary>
      <div class="fb-more-body">
        ${row && !x.readOnly ? html`<${OwnerPick} key=${x.id} x=${x} s=${s} give=${give} busy=${busy} />` : null}
        ${tabRef ? html`<section class="fb-tab fb-more-part"><h3 class="label-caps">${f.tabHead}</h3>
          <${Btn} size="sm" variant="secondary" cls="fb-to-tab" onClick=${() => c.act('tab_jump', { tab_ref: tabRef })}>${f.toTab}<//></section>` : null}
        ${row?.key ? html`<section class="fb-ask fb-more-part"><h3 class="label-caps">${f.askHead}</h3>
          <${InstructLine} key=${x.id} scope=${scope} x=${x} s=${s} c=${c} /></section>` : null}
        <section class="fb-fields fb-more-part"><h3 class="label-caps">${f.fieldsHead}</h3>
          ${tab?.ask?.text ? html`<pre class="fb-screen mono">${tab.ask.text}</pre>` : null}
          ${x.kind !== 'reports' && row ? html`<${Fields} x=${x} s=${s} c=${c} />` : null}
          ${row ? html`<${PointTabs} x=${x} s=${s} c=${c} />` : null}
        </section>
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

/** The name of an entry of what runs: its entry's title, its tab's name, a session's own name (sessions carry a name,
 *  never a title: an empty button stood under Running for a busy session without a tab, round 2) */
export const runTitle = v => v?.entry?.title ?? v?.tab?.name ?? v?.session?.tab?.name ?? v?.session?.name ?? v?.session?.title ?? v?.session?.id ?? v?.id ?? ''

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
  const running = [...runs.sessions.map(v => ({ id: v.entry?.id ?? v.id, title: runTitle(v), open: v.entry ? () => c.flowRun(v.entry.id) : () => c.flowRunning() })),
    ...runs.loose.map(e => ({ id: e.id, title: e.title ?? e.tab?.name ?? '', open: () => c.flowRun(e.id) }))]
  const reads = (parts.read ?? []).map((r, k) => ({ id: r.id, title: r.title ?? r.row?.title ?? '', open: () => c.flowReadOpen(r.id, k) }))
  // an entry of what runs, opened from the list under the buckets: its card in the middle, the buckets stay
  const runEntry = s.ui?.flowView === 'run' ? (parts.lane ?? []).find(e => e.id === s.ui.flowRunId) ?? null : null
  const open = openBucket(buckets, s.ui?.flowBucket)
  const points = open?.points ?? []
  const at = s.ui?.flowBucketAt ?? null
  const i = focusIndex(points, at)
  // the point of the card left its bucket without an answer here (another browser, the chat, a script): the card
  // stays with a word and the way on, so a click meant for it never lands on the next point (round 2)
  const answered = s.ui?.flowAnswered ?? {}
  const movedAway = !!at?.id && !points.some(p => p.id === at.id) && !answered[at.id]
  const x = movedAway ? null : points[i] ?? null
  const onwards = open ? buckets.find(b => b.id !== open.id && b.points.length) ?? null : null
  // an answer moves on to the next point, also where the point stays in its bucket (Wait on a task that waits, a
  // tab's own answer): the next one is held by its id, at the place the answered one leaves free
  const onwardsAfter = () => c.flowBucketGo(points[i + 1]?.id ?? null, i)
  // what is out of sight, only counted (the model's aside): later, the watch list, done today
  const aside = asideCounts(s)
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
        <div class="fb-aside">
          <p class="label-caps">${f.aside.head}</p>
          ${[['later', aside.later, f.aside.laterTip], ['list', aside.list, f.aside.listTip], ['done', aside.done_today, f.aside.doneTip]].map(([k, n, tip]) => html`
            <div key=${k} class=${`fb-aside-row fb-aside-${k}`} title=${tip}><span>${f.aside[k]}</span><b class="fb-aside-n mono">${n}</b></div>`)}
        </div>
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
          <p class="fb-legend muted small">${f.rule[open.id] ?? ''}</p>
        </header>` : null}
        ${runEntry ? html`<div class="fb-run"><${Btn} size="sm" variant="secondary" icon="back" onClick=${() => c.flowBucket(open?.id ?? null)}>${f.back(open?.title ?? f.label)}<//>
            <${PointCard} x=${runEntry} s=${s} c=${c} /></div>`
          : movedAway ? html`<div class="fb-moved" role="status"><p>${f.moved}</p>
            ${points.length ? html`<${Btn} size="sm" variant="primary" onClick=${() => c.flowBucketGo(points[i].id, i)}>${f.movedOn}<//>` : null}</div>`
          : x ? html`<${BucketCard} key=${x.id} x=${x} bucket=${open.id} s=${s} c=${c} onDone=${onwardsAfter} />`
          : html`<div class="fb-empty"><p>${Object.values(answered).some(v => v?.bucket === open?.id) ? f.cleared : f.empty}</p>
            ${onwards ? html`<${Btn} size="sm" variant="primary" onClick=${() => c.flowBucket(onwards.id)}>${f.onwards(onwards.title)}<//>`
              : html`<p class="muted">${f.allDone}</p>`}</div>`}
        ${x && !runEntry ? html`<div class="fb-walk">
          <${Btn} size="sm" variant="secondary" icon="back" disabled=${i === 0} onClick=${() => c.flowBucketGo(points[i - 1].id, i - 1)}>${f.prev}<//>
          <span class="fb-pos muted small">${f.pos(i + 1, points.length)}</span>
          <${Btn} size="sm" variant="secondary" disabled=${i >= points.length - 1} onClick=${() => c.flowBucketGo(points[i + 1].id, i + 1)}>${f.next2}<//>
        </div>` : null}
      </section>
    </div>
  </div>`
}
