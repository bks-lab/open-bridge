// SPDX-License-Identifier: MIT
// The cockpit, the one point view (stage 1, 04.11.2026): the middle of an open point, one component wherever a point
// opens. Work through (views/flow.js) shows it for a point of the queue, an entry of Running now, a row of a list of
// Not now (Back leads to that list, the walk walks it) and a point of its own (a row that stands nowhere on the page:
// another area's, a closed task, a settled item, read only without an open row behind it, logic.js soloPoint); the
// Files tab (views/dossier.js) shows it for a record, opened from its list or walked, where Work through is on (the
// rule is logic.js pointViewOn; without Work through the Files tab keeps its file card). On top the way back (Back to
// overview, To the list, Close the record) with where it was opened from, then the card, held by its id: its kind in
// its head (the state, the only place it stands) with the kind of row and Pin at the end of the head (the start page's
// pins, c.pin), its title (always the title of the point opened: a tab that asks about a row names itself in the line
// under it, Tab x asks), what its tab asks with one set of answers, a start's result, the live tab's screen. Stage 4,
// simpler: a point says three things, its name (logic.js pointName: an inbox item's brief name, a task's H1 unless a
// slug or too long), where it stands in one sentence under it (pointStand: the brief's stand, else the triage's gist)
// and its next step in one line (StepLine: the step, who as a chip, its due or check-in day); the headline, the
// original title and the rest of what is stored stand folded in Description. A check-in whose day came has a card of
// its own (CheckinCard: since when with whom, How does it stand?, its answers on the card). Under it the tabs of the point (views/flowtabs.js PointTabs), at the foot the instruction line
// with Instruct or Ask (views/flowinstruct.js) over the walk bar (views/dossier.js Walk). The right column beside it is
// views/flowside.js FlowAside, which the page places. The cards of a start, of a tab that asks, of the return card and
// of the reports stand here as they did in views/flow.js (stage 2 does the finished starts). A point's detail is read
// when it opens (an inbox item's here, a task's and its Activity in PointTabs), a point of its own's before it can
// stand (useSoloLoad).
// For the mouse: no text names a key.
// The rules every component keeps stand at the head of components.js.

import { html, useEffect, useState } from '../vendor/htm-preact-3.1.1.module.js'
import {
  asksSomething, checkinDays, detailNeedsLoad, dropReasonWord, duration, flowAction, flowDrive, flowSettings, formatDay, guideOf, nextWho, personOf,
  pointName, pointStand, pointStep, previewText, reportsTicked, resultText, short, soloSource, stageTone, tabOfTask,
} from '../logic.js'
import { T, language } from '../text.js'
import { KindTag } from './day.js'
import { Walk } from './dossier.js'
import { InstructLine } from './flowinstruct.js'
import { PointTabs } from './flowtabs.js'
import { Hero } from './focus.js'
import { GuideTree } from './guide.js'
import { Btn, Dot, WhoChip } from './parts.js'
import { AskLine, TabReply } from './reply.js'

// the lines of a live tab's screen a card shows
const SCREEN_LINES = 12

/** The last lines of a tab's screen, the way they stood */
const tailLines = (text, n = SCREEN_LINES) => String(text ?? '').split('\n').map(previewText).filter(Boolean).slice(-n)

/** A card's title in the walk bar and the strip under it: the title of the point opened, a tab's name only for a tab
 *  with no row behind it */
function cardTitle(x) {
  const f = T().flow
  if (x.kind === 'back') return f.back(x.jump.title)
  if (x.kind === 'start') return x.start.title
  if (x.kind === 'tab') return x.row ? pointName(x.row) : x.tab.name
  if (x.kind === 'reports') return f.reports(x.rows.length)
  return pointName(x.row)
}

/** A card's kind in a word: its group, a quiet start and one ended with a note (to look at) by its stage; a tab that
 *  waits at its prompt with nothing asked on its screen (logic.js asksSomething, the rule its close follows) waits
 *  rather than asks, so the head never says it asks beside its close. A row of Not now says its group, a point of its
 *  own its state where it is closed, else that it was opened on its own */
function cardKind(x) {
  const t = T()
  const f = t.flow
  if (x.group === 'left') return f.notnow.group[x.left] ?? f.notnow.label
  if (x.group === 'read') return f.read.kind
  if (x.group === 'solo') {
    const r = x.row ?? {}
    return x.readOnly ? t.item.stateName[r.inbox_state] ?? t.taskState[r.status] ?? r.inbox_state ?? r.status ?? f.one.solo : f.one.solo
  }
  return f.kind[kindKey(x)]
}

/** The key of a card's kind (cardKind): a quiet start and one ended with a note by its stage, a tab that waits at its
 *  prompt with nothing asked as waits, else its group */
const kindKey = x => (x.stage === 'idle' || x.stage === 'done' ? x.stage
  : x.kind === 'tab' && x.tab?.state === 'waiting' && !asksSomething(x.tab.ask) ? 'waits' : x.group)

// the kinds that are a tab's or a start's state, not the point's own (stage 4: said as the tab's)
const TAB_KINDS = new Set(['asks', 'waits', 'result', 'idle', 'done', 'lost'])

/** What the overview says under a name that has no stand (stage 4): where the only word is its tab's or its start's
 *  state, it says it is the tab's ("Agent tab: finished", never a bare Finished that reads as if the point were done),
 *  any other point its kind (In review, In progress, A question for you) */
export function pointStandWord(x) {
  const f = T().flow
  const key = ['left', 'read', 'solo', 'doing'].includes(x.group) ? null : kindKey(x)
  return key && TAB_KINDS.has(key) ? f.simple.tabIs(f.simple.tabState[key]) : pointKind(x)
}

/** A point's title and its kind in a word, for the tabs, the walk and the list */
export const pointTitle = x => (x.group === 'doing' ? (x.row ? pointName(x.row) : x.title ?? x.start?.title ?? x.tab?.name ?? '') : cardTitle(x))
export const pointKind = x => (x.group === 'doing' ? T().flow.kind.doing : cardKind(x))

/** Pin at the end of a card's head (the star of the start page, c.pin; the item drawer had it): pressed while the
 *  row is pinned there; none on a person's page, whose start page is the owner's */
function PinButton({ rowKey, s, c }) {
  if (!rowKey || personOf(s)) return null
  const t = T()
  const on = (s.home?.pins ?? []).includes(rowKey)
  return html`<${Btn} size="xs" variant="ghost" cls="flow-pin" pressed=${on} title=${on ? t.home.unpin : t.home.pin}
    onClick=${() => c.pin(rowKey, !on)}>${on ? `★ ${t.flow.one.pinned}` : `☆ ${t.flow.one.pin}`}<//>`
}

/** The end of a card's head: what kind of row it is (an item, a task, an issue) and Pin */
function HeadEnd({ row, s, c }) {
  if (!row?.key) return null
  return html`<span class="flow-card-head"><${KindTag} row=${row} s=${s} bare /><${PinButton} rowKey=${row.key} s=${s} c=${c} /></span>`
}

/** The next step of a point: its card's (card.py, with who takes it and by when), else what its STATUS.md names */
function nextOf(row, detail) {
  const card = row?.card?.next ?? detail?.card?.next ?? null
  if (card?.what) return card
  const what = detail?.front?.next
  return what ? { what: String(what), who: null, due: null } : null
}

/** The next step in one line under the stand (stage 4): Next step, its words, who as a chip (logic.js nextWho: you,
 *  the Bridge, a person) and its due day or, while it is with someone, the day it asks again; none without a step.
 *  `next` the step as card.py or STATUS.md give it, where the row's card has none */
export function StepLine({ row, next = null, s }) {
  const f = T().flow.simple
  const lang = language()
  const step = pointStep(row, s) ?? (next?.what ? { what: String(next.what), who: next.who ?? null, due: next.due ?? null, check: row?.checkin?.until ?? null } : null)
  if (!step) return null
  const day = v => formatDay(String(v).slice(0, 10), lang)
  const when = step.check ? f.asksOn(day(step.check)) : step.due ? f.dueOn(day(step.due)) : null
  return html`<p class="flow-step"><span class="label-caps">${f.step}</span> <span class="flow-step-what">${step.what}</span>
    <${WhoChip} who=${step.who} s=${s} />${when ? html` <span class="muted small">${when}</span>` : null}</p>`
}

/** What a card says of its row's file: the task's detail (its own, or the folder of a closed copy), its headline as
 *  the line under the title and its next step; an inbox item reads only its own card */
function fileOf(x, s) {
  const row = x.row
  const own = !!row?.task && row.key === `task:${row.task}`
  const detail = own ? s.details?.task?.[x.file ?? row.task]?.data ?? null : null
  return { detail, headline: detail?.front?.headline ?? null, next: nextOf(row, detail) }
}

/** A check-in whose day came (stage 4, logic.js flowParts `checkin`): since when it is with whom and How does it stand?,
 *  what the Bridge found when it looked (a note of the check-in run, where one is), then the answers on the card: Done,
 *  Still running ▾ (a new check-in day), Stuck (back to you, with why as a note), Drop ▾ and Follow up with <who> (a
 *  start that drafts a follow-up to that person, never sends it). The right column then has no states, only More */
function CheckinCard({ x, n = 1, s, c }) {
  const t = T()
  const f = t.flow.simple
  const lang = language()
  const row = x.row
  const ck = x.checkin ?? row.checkin ?? {}
  const who = nextWho(ck.who, s, lang) || f.someone
  const [open, setOpen] = useState(null)
  const [why, setWhy] = useState('')
  const busy = !!s.ui?.busy?.[row.key]
  const days = checkinDays(s.now || Date.now())
  const send = async a => { if (!a) return; const r = await c.act(a.verb, a.args); if (r?.ok) { setOpen(null); c.flowDecided() } }
  const since = ck.since ? formatDay(String(ck.since).slice(0, 10), lang) : null
  const name = pointName(row)
  const reasons = flowSettings(s).drop_reasons
  return html`<article class="fx-hero tk-warning flow-checkin" aria-labelledby="flow-title">
    <header class="fx-hero-top"><span class="fx-kind"><${Dot} token="warning" />${f.checkinKind}</span><${HeadEnd} row=${row} s=${s} c=${c} /></header>
    <h2 id="flow-title" class="fx-title">${name}</h2>
    <p class="fx-sub">${f.since(since, who)}</p>
    ${ck.found ? html`<div class="flow-looked"><p class="label-caps">${f.looked}</p><p>${ck.found}</p></div>` : null}
    <div class="verbbar-acts flow-checkin-acts" role="group" aria-label=${f.answers}>
      <${Btn} size="sm" variant="secondary" busy=${busy} onClick=${() => send(flowAction('done', row, ''))}>${t.flow.verbs.done}<//>
      <${Btn} size="sm" variant="secondary" pressed=${open === 'still'} onClick=${() => setOpen(open === 'still' ? null : 'still')}>${f.still} ▾<//>
      <${Btn} size="sm" variant="secondary" pressed=${open === 'stuck'} onClick=${() => setOpen(open === 'stuck' ? null : 'stuck')}>${f.stuck}<//>
      <${Btn} size="sm" variant="secondary" pressed=${open === 'drop'} onClick=${() => setOpen(open === 'drop' ? null : 'drop')}>${t.flow.verbs.drop} ▾<//>
      ${personOf(s) ? null : html`<${Btn} size="sm" variant="primary" busy=${busy}
        onClick=${() => send(flowAction('do', row, f.chase(who, name)))}>${f.chaseButton(who)}<//>`}
    </div>
    ${open === 'still' ? html`<div class="verbbar-panel verbbar-acts" role="group" aria-label=${f.still}>
      ${[3, 7, 14].map(d => html`<${Btn} key=${d} size="sm" variant="secondary" busy=${busy}
        onClick=${() => send({ verb: 'work_on', args: { key: row.key, who: ck.who || 'me', until: days[d] } })}>${f.inDays(d)}<//>`)}
    </div>` : null}
    ${open === 'stuck' ? html`<div class="verbbar-panel" role="group" aria-label=${f.stuck}>
      <label class="label-caps" for=${`ck-why-${row.key}`}>${f.stuckWhy}</label>
      <span class="field-row"><input id=${`ck-why-${row.key}`} class="input" type="text" maxlength="300" value=${why} onInput=${e => setWhy(e.currentTarget.value)} />
        <${Btn} size="sm" variant="primary" busy=${busy} onClick=${() => send({ verb: 'checkin_stuck', args: { key: row.key, ...(why.trim() ? { text: why.trim() } : {}) } })}>${f.stuckGo}<//></span>
    </div>` : null}
    ${open === 'drop' ? html`<div class="verbbar-panel verbbar-acts" role="group" aria-label=${t.flow.drop.label}>
      ${reasons.map(r => html`<${Btn} key=${r} size="sm" variant="secondary" busy=${busy} onClick=${() => send(flowAction('drop', row, dropReasonWord(r, lang)))}>${dropReasonWord(r, lang)}<//>`)}
    </div>` : null}
  </article>`
}

/** What a tab asks, answered on the card: the answers to its question as one row of buttons (a dialog's options, yes
 *  and no, go on, a field), and the decision guide's steps folded under one button, without the guide's own line what
 *  it is about (the card's title says it). The way to the tab stands on the right (views/flowside.js TabWays, which
 *  remembers the jump), so neither repeats it */
function AskBlock({ tab, s, c }) {
  const f = T().flow.guide
  const [open, setOpen] = useState(false)
  if (!tab) return null
  const guide = guideOf(s, tab).status !== 'off'
  return html`<div class="flow-askblock">
    <${TabReply} tab=${tab} s=${s} c=${c} compact noJump />
    ${guide ? html`<button type="button" class="btn-link flow-guide-toggle" aria-expanded=${String(open)} onClick=${() => setOpen(!open)}>${open ? f.hide : f.show}</button>` : null}
    ${guide && open ? html`<${GuideTree} tab=${tab} s=${s} c=${c} bare about=${false} />` : null}
  </div>`
}

/** The return card: back from a tab the page jumped to, how did it go. Its answers stand on the right; every one
 *  forgets the jump */
function BackCard({ x, s }) {
  const f = T().flow
  const ago = duration((s.now || Date.now()) - x.jump.at)
  return html`<article class="fx-hero tk-info" aria-labelledby="flow-title">
    <header class="fx-hero-top"><span class="fx-kind"><${Dot} token="info" />${f.kind.back}</span><span class="mono muted small">${ago}</span></header>
    <h2 id="flow-title" class="fx-title">${f.back(x.jump.title)}</h2>
    <p class="flow-ask">${f.backAsk}</p>
    ${!x.row && x.jump.key ? html`<p class="muted small">${f.backGone}</p>` : null}
  </article>`
}

/** A start of the return channel that wants you: its tab asks, it finished (or went quiet, or ended with a note), or
 *  it got lost; or a finished AI run to read (stage 2: what became of it in plain words, the run's words folded under
 *  The run's words). The card says what came back (the result line or the question noted on its item, without its own head
 *  word) and what its tab asks, and leads back to the chat it was handed on from while that chat is kept; since when it
 *  runs is the field Who works on it, the criteria of its brief stand in Description, what to do with it on the right */
function StartCard({ x, s, c }) {
  const t = T()
  const f = t.flow
  const r = x.start
  const tab = x.tab
  const lines = r.result?.text ? [] : tailLines(tab?.last ?? r.tab?.last)
  const head = r.result?.asks ? f.question : r.result?.kind === 'note' || x.stage === 'done' ? f.result : t.home.returnAnswer
  const chat = r.conv && (s.quick?.convs ?? []).some(v => v.id === r.conv)
  // a finished AI run (stage 2): what became of it in plain words (returns.py plain_line), the run's own words folded
  const raw = String(r.result?.text ?? '').trim()
  const said = x.group === 'read' && r.plain ? r.plain : null
  return html`<article class=${`fx-hero tk-${stageTone(x.stage === 'idle' ? 'result' : x.stage)}`} aria-labelledby="flow-title">
    <header class="fx-hero-top"><span class="fx-kind"><${Dot} token=${stageTone(x.stage === 'idle' ? 'result' : x.stage)} />${cardKind(x)}</span></header>
    <h2 id="flow-title" class="fx-title">${(x.row?.key ? pointName(x.row) : null) || r.title}</h2>
    ${said ? html`<p class="flow-answer"><span class="label-caps">${head}</span> ${said}</p>
      ${raw && resultText(raw) !== said ? html`<details class="flow-raw"><summary class="small muted">${f.read.raw}</summary>
        <p class="mono small">${short(raw, 600)}</p></details>` : null}`
      : r.result?.text ? html`<p class="flow-answer"><span class="label-caps">${head}</span> ${short(resultText(r.result.text), 400)}</p>` : null}
    ${chat ? html`<p><button type="button" class="btn-link small" onClick=${() => c.openAsk(r.conv)}>${f.toQuestion}</button></p>` : null}
    ${x.stage === 'idle' && !r.result?.text ? html`<p class="muted">${f.idleSub}</p>` : null}
    ${x.group === 'lost' ? html`<p class="muted">${f.lostSub}</p>` : null}
    ${x.group === 'asks' ? html`<${AskLine} tab=${tab} />` : null}
    ${lines.length && x.group !== 'asks' ? html`<pre class="fx-screen mono">${lines.join('\n')}</pre>` : null}
    ${x.group === 'asks' ? html`<${AskBlock} tab=${tab} s=${s} c=${c} />` : null}
  </article>`
}

/** The reports as one card: each with its box and folding open with its reasons, Seen and Open (the report alone in
 *  the one view, c.flowSolo, Back leads to this card); All above them ticks every one. The boxes are the overview's
 *  (ui.flowPicked); Seen for the ticked ones stands on the right */
function ReportsCard({ x, s, c }) {
  const f = T().flow
  const keys = x.rows.map(r => r.key)
  const on = new Set(reportsTicked(x, s.ui.flowPicked))
  const all = on.size === keys.length
  return html`<article class="fx-hero tk-muted" aria-labelledby="flow-title">
    <header class="fx-hero-top"><span class="fx-kind"><${Dot} token="muted" />${f.kind.reports}</span></header>
    <h2 id="flow-title" class="fx-title">${f.reports(x.rows.length)}</h2>
    <label class="flow-check flow-reports-all"><input type="checkbox" checked=${all} onClick=${() => c.flowPick(keys, !all)} /><span>${f.list.pickAll}</span></label>
    <ul class="flow-reports">${x.rows.map(r => html`<li key=${r.key} class=${on.has(r.key) ? 'is-picked' : undefined}>
      <input type="checkbox" class="flow-ov-pick" aria-label=${f.list.pick(short(pointName(r), 60))} checked=${on.has(r.key)}
        onClick=${() => c.flowPick([r.key], !on.has(r.key))} /><details>
      <summary>${pointName(r)}</summary>
      ${(r.why ?? []).length ? html`<ul class="fx-why">${r.why.slice(0, 4).map(w => html`<li key=${w}>${w}</li>`)}</ul>` : null}
      <div class="fx-do"><${Btn} size="xs" variant="secondary" busy=${!!s.ui.busy?.[r.key]}
        onClick=${() => c.act('settle', { keys: [r.key], outcome: 'done' })}>${f.seen}<//>
        <button type="button" class="btn-link flow-report-open" onClick=${() => c.flowSolo(r.key, x.id)}>${f.one.open}</button></div>
    </details></li>`)}</ul>
  </article>`
}

// a word of a list as the start of a sentence
const upFirst = t => (t ? t[0].toUpperCase() + t.slice(1) : t)

/** A point in progress, or an entry of Running now: its state in its head (its dot pulses while an agent works on it,
 *  logic.js flowDrive) with the kind and Pin at the end, its title, its headline and next step, and the last lines of
 *  that tab's screen. Who works on it and since when is a field on the right, where its verbs stand too */
function DoingCard({ x, s, c }) {
  const f = T().flow
  const d = flowDrive(x, s)
  const row = x.row
  const lines = tailLines(d.tab?.last ?? x.start?.tab?.last)
  const live = d.by !== 'none' && (d.stage === 'working' || d.stage === 'started')
  const title = row ? pointName(row) : x.title ?? x.start?.title ?? ''
  const token = d.by === 'none' ? 'muted' : stageTone(d.stage === 'needs-you' ? 'asks' : d.stage ?? 'working')
  // an entry of Running now says so in its head with its stage, and why it stands there and not as a point
  const kind = x.lane ? [f.run.label, f.doing.stage[d.stage] ?? d.stage].filter(Boolean).join(' · ') : f.kind.doing
  const file = row ? fileOf(x, s) : null
  return html`<article class=${`fx-hero tk-${token === 'muted' ? 'muted' : 'info'}`} aria-labelledby="flow-title">
    <header class="fx-hero-top"><span class="fx-kind"><${Dot} token=${token} pulse=${live} />${kind}</span><${HeadEnd} row=${row} s=${s} c=${c} /></header>
    <h2 id="flow-title" class="fx-title">${title}</h2>
    ${row && pointStand(row, s) ? html`<p class="fx-sub">${pointStand(row, s)}</p>` : null}
    ${row ? html`<${StepLine} row=${row} next=${file?.next} s=${s} />` : null}
    ${x.lane ? html`<p class="muted small">${[upFirst(f.run.how[x.how]), f.run.cardWhy].filter(Boolean).join('. ')}</p>` : null}
    ${lines.length ? html`<pre class="fx-screen mono">${lines.join('\n')}</pre>` : null}
  </article>`
}

/** The card in front, by its kind, content only: a question or a task in the hero of the start page focus without its
 *  foot and without the facts the fields say, its kind and Pin at the end of its head, its task or headline under the
 *  title, its next step; a tab that asks with its answers, a start, the return card, the reports, a point in progress */
export function PointCard({ x, n = 1, s, c }) {
  const f = T().flow
  const tabs = s.tabs?.tabs ?? []
  if (x.group === 'checkin') return html`<${CheckinCard} x=${x} n=${n} s=${s} c=${c} />`
  if (x.group === 'doing') return html`<${DoingCard} x=${x} s=${s} c=${c} />`
  if (x.kind === 'back') return html`<${BackCard} x=${x} s=${s} />`
  if (x.kind === 'start') return html`<${StartCard} x=${x} s=${s} c=${c} />`
  if (x.kind === 'reports') return html`<${ReportsCard} x=${x} s=${s} c=${c} />`
  if (x.kind === 'tab') {
    // the card says the point that was opened: the title of its row, the tab's name as a line under it (Tab x asks)
    // with its question; a tab with no row behind it is the point, so its name is the title
    const question = x.tab.ask?.text ? short(x.tab.ask.text.split('\n').find(Boolean), 200) : null
    const asking = !(x.tab.state === 'waiting' && !asksSomething(x.tab.ask))
    return html`<${Hero} x=${{ kind: 'tab', id: x.tab.ref, tab: x.tab }} n=${n} tabOf=${() => null} s=${s} c=${c} kindWord=${cardKind(x)} openable=${false}
      foot=${false} facts=${false} screen=${SCREEN_LINES} headEnd=${x.row ? html`<${HeadEnd} row=${x.row} s=${s} c=${c} />` : null}
      title=${x.row ? pointName(x.row) : null} sub=${x.row ? (asking ? f.one.tabAsks(x.tab.name) : f.one.tabWaits(x.tab.name)) : question}
      lead=${x.row && question ? html`<p class="flow-ask">${question}</p>` : null}>
      <${AskBlock} tab=${x.tab} s=${s} c=${c} />
    <//>`
  }
  const row = x.row
  const tab = row.task ? tabOfTask(tabs, row.task) : null
  const file = fileOf(x, s)
  // stage 4: the name, where it stands, its next step; a question about a task names that task where it says no more
  const sub = pointStand(row, s) ?? (x.task ? f.forTask(pointName(x.task)) : null)
  return html`<${Hero} x=${{ kind: 'row', id: row.key, row }} n=${n} tabOf=${() => tab} s=${s} c=${c} kindWord=${cardKind(x)} title=${pointName(row)}
    sub=${sub} openable=${false} foot=${false} facts=${false} screen=${SCREEN_LINES} headEnd=${html`<${HeadEnd} row=${row} s=${s} c=${c} />`}
    lead=${html`<${StepLine} row=${row} next=${file.next} s=${s} />`} />`
}

/** The detail a point of its own is read from (logic.js soloSource: a task's STATUS.md, a closed copy by its folder,
 *  an inbox item's item.yaml), read when it opens and again once stale; its entry ({status, data, error}) for the view
 *  to say it loads or is gone. `solo` null reads nothing */
export function useSoloLoad(solo, s, c) {
  const src = solo ? soloSource(solo) : null
  const entry = src ? s.details?.[src.kind]?.[src.id] ?? null : null
  const ver = s.model?.collected_ms ?? 0
  useEffect(() => { if (src && detailNeedsLoad(entry, ver)) (src.kind === 'task' ? c.loadTask : c.loadInbox)(src.id) }, [src?.kind, src?.id, ver, entry?.stale])
  return entry
}

/** An inbox item's detail (its raw description, its facts, its history): read when its point opens and once stale */
function useItemDetail(x, s, c) {
  const id = x?.kind !== 'reports' ? x?.row?.inbox_id ?? null : null
  const entry = id ? s.details?.inbox?.[id] ?? null : null
  const ver = s.model?.collected_ms ?? 0
  useEffect(() => { if (id && detailNeedsLoad(entry, ver)) c.loadInbox(id) }, [id, ver, entry?.stale])
}

/** The middle of an open point, the one view of it wherever it opens: the way back in its head (`back` {word,
 *  onClick, icon}) with where it was opened from (`theme`), what stands `above` it (the ticked line of the overview),
 *  the card, its tabs, and at the foot the instruction line with Instruct or Ask (`scope`, logic.js instructScope)
 *  over the walk bar (`walk`: the props of views/dossier.js Walk, null for none) */
export function PointView({ x, back, theme = null, above = null, walk = null, scope = null, n = 1, s, c }) {
  useItemDetail(x, s, c)
  return html`<header class="flow-main-head">
      <${Btn} size="sm" variant="secondary" icon=${back.icon ?? 'back'} cls="flow-back" onClick=${back.onClick}>${back.word}<//>
      ${theme ? html`<span class="flow-main-theme muted">${theme}</span>` : null}
    </header>
    ${above}
    <div class="flow-point">
      <div class="flow-card" key=${x.id}><${PointCard} x=${x} n=${n} s=${s} c=${c} /></div>
      <${PointTabs} x=${x} s=${s} c=${c} />
    </div>
    <div class="flow-dock">
      <${InstructLine} key=${x.id} scope=${scope} x=${x} s=${s} c=${c} />
      ${walk ? html`<${Walk} ...${walk} s=${s} c=${c} />` : null}
    </div>`
}
