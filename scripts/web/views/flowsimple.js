// SPDX-License-Identifier: MIT
// The cockpit, the verbs of a point in the one point view, simpler (stage 4, the user's "it has to get simpler": too
// many buttons on a point). SimpleActs, the right column's What you can do of Work through (views/flowside.js
// PointActs hands every point with a row to it while Work through is on): ONE strong button that applies the AI's
// suggestion with its verb and the step (logic.js strongOf), else Give your yes, else the Bridge's own step, and To tab
// while an agent tab is on the point; Give it to the AI ▾ on every card (AiGive: Let it do it, Advise, Collect context,
// the way its sort fits picked first; cockpit-card-buttons), a reminder's I asked beside it; the four states in a quiet
// 2x2 (views/verbbar.js `simple`: Done, In progress ▾, Later ▾, Drop ▾, an inbox item's Out of date ▾); More ▾, a menu
// of every other verb that applies (logic.js moreOf) and the ways of a tab. A reminder (its asks are someone else's)
// has Draft the message to <who> as its strong button, a draft only. OrderMenu,
// Order ▾ under the left column's list: what orders the list (Order themes again, Sort again, Read in with Jev or
// Haiku, Rename the theme entered), the lines of a run that runs under it. Both menus are popovers (parts.js
// usePopover). Where Work through is off none of this stands: views/flowside.js BasicActs and its foot stay as they were.
// For the mouse: no text names a key.
// The rules every component keeps stand at the head of components.js.

import { html, useState } from '../vendor/htm-preact-3.1.1.module.js'
import {
  adoptStepOf, aiAction, aiDraft, aiNote, aiOf, basicVerbs, checkinDays, reminderTo, canTab, DAY, dropReasonWord, flowAction, flowDriver, flowLive, flowRunning, flowSettings, flowTabOf, formatDay, haikuReady, isoDate,
  jevReady, leftPlan, moreOf, personOf, pointName, replyOptions, short, strongOf, tabCloseOffer, triageRunning, workPageOf,
  pointKeys, readMark, seenOn, seenSettings,
} from '../logic.js'
import { T, language } from '../text.js'
import { TabClose } from './detail.js'
import { sugFrom, sugWhy } from './flowlist.js'
import { GITHUB_ISSUE, Improve, IssueWays, Resort, Rename } from './flowside.js'
import { PrioFoot } from './flowprio.js'
import { LaunchPick } from './launch.js'
import { Btn, usePopover } from './parts.js'
import { VerbBar } from './verbbar.js'

/** The verbs of a point, simpler (stage 4 of the one point view), top to bottom: ONE strong button, a reminder's
 *  Draft the message to <who>, else the AI's suggestion with its verb and step (logic.js strongOf: Let the Bridge:
 *  <step>, Done, Later, Drop), else Give your yes, else the Bridge's own step, and To tab while an agent tab is on the
 *  point; then Give it to the AI ▾ (AiGive, gone while an agent works on it) with a reminder's I asked; then the four states in a quiet
 *  2x2 (Done, In progress ▾, Later ▾, Drop ▾; one that cannot go says why; a tab that asks what its card answers
 *  keeps To tab in More); then More ▾, the menu of every other verb
 *  that applies (logic.js moreOf: Make it a task, Open on GitHub, the board's moves, Show in the net, Describe again,
 *  Advise, Assign tab, Back on, Steps, Runs on, Not this task) and the ways of a tab (View, its close). A check-in
 *  answers on its card: no states then, only More */
export function SimpleActs({ x, row, s, c, sug }) {
  const t = T()
  const f = t.flow
  const w = f.simple
  const lang = language()
  const [more, setMore] = useState(false)
  const box = usePopover(more, setMore)
  const [panel, setPanel] = useState(null)
  const [crowd, setCrowd] = useState(false)
  const back = x.kind === 'back'
  const live = back ? null : flowLive(x, s)
  const tab = back ? null : flowTabOf(x, s)
  const near = live || tab
  const asks = live?.state === 'needs-you'
  const title = pointName(row)
  const running = x.group === 'doing' && (!!live || (x.kind === 'start' && ['started', 'working'].includes(x.stage)))
  const adopt = adoptStepOf(row, s)
  const person = !!personOf(s)
  const basic = basicVerbs(row, { live: !!live, asks, running, person, adopt })
  const off = Object.fromEntries(basic.filter(v => v.off).map(v => [v.id, v.off]))
  const issue = !!row.ref && !row.task && !row.inbox_id
  const board = issue && !live && GITHUB_ISSUE(row)
  const review = !live && !!row.task && row.status === 'review' && x.group !== 'doing'
  const offer = near && !asks ? tabCloseOffer(near, s) : null
  // where the close of the tab behind it ends this very point, Done in its place closes the tab too (stage 1's rule)
  const ends = !!offer?.done && offer.keys.includes(row.key)
  const busy = !!s.ui?.busy?.[row.key]
  // a check-in answers on its card (views/flowpoint.js CheckinCard): no strong button beside it
  const strong = live || x.group === 'checkin' ? null : strongOf(x, s, sug)
  const by = strong?.sug ? 'suggestion' : null
  const send = async a => { if (!a) return; const r = await c.act(a.verb, a.args); if (r?.ok) c.flowDecided() }
  // the read marks (cockpit.flow.seen): Later is Revisit, read now and back unread on its day; with open_reads click a
  // point stays unread until Read; a doing task that rests offers to go on with it in focus
  const seen = seenOn(s)
  const mark = seen && !person && !x.readOnly && x.group !== 'read' ? readMark(x, s) : null
  const focusable = !!mark?.active
  const inFocus = (s.seen?.focus ?? []).includes(row.key)
  const revisitArgs = seen && !person ? { revisit: true } : null
  // the strong button applies what it says at once; a start past the cap of what runs opens its panel instead
  // an issue on a board closes by the board's rules (review first): the suggestion's Done opens its moves, where the
  // move that fits is the strong one with the reason in its field
  const viaBoard = !!board && strong?.verb === 'done'
  // what the strong start sends: a reminder's draft of its message (a draft only), else the Bridge's step
  const strongStart = () => (strong?.verb === 'draft' ? aiAction('go', row, aiDraft(row, lang))
    : flowAction('do', row, w.startStep(strong?.step ?? title), by))
  const applyStrong = () => {
    if (!strong) return
    if (viaBoard) return setPanel(panel === 'board' ? null : 'board')
    if (strong.verb === 'yes') return send({ verb: 'do_it', args: { keys: [row.key] } })
    if (strong.verb === 'do' || strong.verb === 'draft') {
      if (flowRunning(s) >= flowSettings(s).max_running) { setCrowd(true); return }
      return send(strongStart())
    }
    if (strong.verb === 'later') return send(flowAction('later', row, laterDay, by, revisitArgs))
    if (strong.verb === 'drop') return send(flowAction('drop', row, sug?.drop ? dropReasonWord(sug.drop, lang) : sug?.reason || w.dropSug, by))
    return send(flowAction('done', row, '', by))
  }
  // the words say what the click does: the Bridge's start with its step, Later with its day, Done or Drop alone (the
  // step is no part of what they do)
  const laterDay = sug?.until ?? isoDate((s.now || Date.now()) + 7 * DAY)
  const strongWord = !strong ? null : viaBoard ? `${w.boardDone} ${panel === 'board' ? '▴' : '▾'}` : strong.verb === 'yes' ? f.approve
    : strong.verb === 'draft' ? f.ai.draftTo(strong.to)
    : strong.verb === 'do' ? w.strongDo(strong.step ?? title)
      : strong.verb === 'later' ? (revisitArgs ? f.marks.strong(formatDay(laterDay, lang)) : f.list.laterUntil(formatDay(laterDay, lang)))
        : w[strong.verb] ?? f.verbs[strong.verb]
  // a suggestion says it is one: nothing is set until the click (a Revisit day read as a date already set)
  const said = strong?.sug && !viaBoard && strongWord ? w.suggested(strongWord) : strongWord
  // the suggestion's why and where it comes from stand on the strong button, on hover (stage 4: no line of its own)
  const sugTitle = strong?.sug && sug ? [sugWhy(sug, lang), sugFrom(sug, lang)].filter(Boolean).join(' · ') : null
  // a tab that asks what its card answers (its options, yes and no: logic.js replyOptions) needs no jump: To tab is
  // strong only where the card cannot answer it, else it waits in More; a tab at work or at its prompt keeps it strong
  const reply = x.kind === 'tab' && asks ? replyOptions(live, s, t) : null
  const cardAnswers = !!reply && (reply.textBox || reply.buttons.some(b => b.id !== 'open'))
  const strongBtn = live && flowDriver(s) && !cardAnswers
    ? html`<${Btn} size="sm" variant="primary" cls="verbbar-strong" onClick=${() => c.flowJump({ key: row.key, ref: live.ref, title })}>${f.toTab}<//>`
    : strong ? html`<${Btn} size="sm" variant=${viaBoard && panel === 'board' ? 'secondary' : 'primary'} cls="verbbar-strong" busy=${busy}
      pressed=${viaBoard ? panel === 'board' : undefined} title=${sugTitle || undefined} onClick=${applyStrong}>${short(said, 80)}<//>` : null
  const items = moreOf(x, s, { board, adopt })
  const slug = row.task && !person ? row.task : null
  const backOn = items.includes('back') ? leftPlan([x.entry], 'back', s, '', lang) : null
  const run = fn => () => { setMore(false); fn() }
  const item = (id, word, onClick) => html`<button key=${id} type="button" class="flow-more-item" role="menuitem" onClick=${onClick}>${word}</button>`
  const menu = html`${items.map(id => {
    if (id === 'task') return item(id, f.basic.task, () => { setPanel('task'); setMore(false) })
    if (id === 'github') return html`<a key=${id} class="flow-more-item" role="menuitem" href=${row.url} target="_blank" rel="noopener noreferrer">${f.onWeb(row.url)}</a>`
    if (id === 'board') return item(id, w.board, () => { setPanel('board'); setMore(false) })
    if (id === 'net') return item(id, f.one.net, run(() => c.openInner(`task:${slug}`)))
    if (id === 'describe') return item(id, w.describe, run(() => c.act('describe_run', { key: row.key })))
    if (id === 'advise') return item(id, w.advise, run(() => c.flowAdvise(row.key)))
    if (id === 'adopt') return html`${(row.adopt_candidates ?? []).map(a => item(`adopt-${a.ref}`, f.one.adopt(`${a.workspace} / ${a.name}`),
      run(() => c.act('adopt', { key: row.key, tab_ref: a.ref }))))}`
    if (id === 'back') return item(id, f.notnow.back, run(async () => {
      if (backOn.early.length) c.flowEarly({ [row.key]: x.entry.until })
      if (backOn.calls.length) await c.flowBatch(backOn.calls, 'left')
    }))
    if (id === 'steps') return item(id, t.rowSteps, run(() => c.flowTab('steps')))
    if (id === 'runsOn') return item(id, f.runsOn, run(() => c.flowBack()))
    if (id === 'unlink') return item(id, f.run.unlink, run(() => c.act('session_unlink', { session: x.session.sid })))
    return null
  })}
    ${mark && !mark.live && !(mark.unread && mark.why?.kind === 'forced') ? item('unread', f.marks.markUnread, run(() => c.flowUnread(row.key))) : null}
    ${focusable ? item('focus', inFocus ? f.marks.unfocus : f.marks.focus, run(() => c.flowFocus(row.key, !inFocus))) : null}
    ${review ? item('improve', f.improve.button, () => { setPanel('improve'); setMore(false) }) : null}
    ${near && flowDriver(s) ? item('view', f.view, run(() => c.openTabView(near.ref))) : null}
    ${(!live || cardAnswers) && near && flowDriver(s) ? item('totab', f.toTab, run(() => c.flowJump({ key: row.key, ref: near.ref, title }))) : null}
    ${offer ? html`<div class="flow-more-close"><${TabClose} tab=${near} s=${s} c=${c} size="sm" only=${ends} /></div>` : null}`
  const toTask = basic.some(v => v.id === 'task') ? (row.inbox_id
    ? { what: f.basic.taskInbox, run: async () => { const r = await c.act('to_task', { key: row.key }); if (r?.ok && r.task) c.openItem(`task:${r.task}`); return r } }
    : { what: f.basic.taskIssue, run: () => c.act('row_action', { ...adopt, action: 'adopt' }) }) : null
  // Give it to the AI (cockpit-card-buttons): on every card, gone while an agent works on the point or its yes runs
  const ai = aiOf(row, { live: !!live, running, person })
  const hasMore = !!menu && (items.length || review || near || offer || (mark && !mark.live) || focusable)
  // Read (open_reads click) while the point is unread; Go on, keep in focus where a doing task rests and nothing else is strong
  const readBtn = mark?.unread && !mark.live && seenSettings(s).open_reads === 'click'
    ? html`<${Btn} size="sm" variant="primary" cls="verbbar-strong flow-read-btn" onClick=${() => c.flowSeen(pointKeys(x))}>${f.marks.read}<//>` : null
  const goOn = !strongBtn && focusable && !mark.active.active && !inFocus
    ? html`<${Btn} size="sm" variant="primary" cls="verbbar-strong" onClick=${() => c.flowFocus(row.key, true)}>${f.marks.goOn}<//>` : null
  return html`<div class="flow-simple">
    ${readBtn}
    ${strongBtn ?? goOn}
    ${crowd ? html`<div class="verbbar-acts" role="alert"><span class="small">${f.start.busy(flowRunning(s))}</span>
      <${Btn} size="sm" variant="secondary" onClick=${() => { setCrowd(false); send(strongStart()) }}>${f.start.anyway}<//></div>` : null}
    ${ai && !ai.off && x.group !== 'checkin' ? html`<${AiGive} key=${row.key} row=${row} ai=${ai} s=${s} c=${c} onSent=${() => c.flowDecided()} />` : null}
    ${x.group === 'checkin' ? null : html`<${VerbBar} row=${row} s=${s} c=${c} simple stack off=${{ ...off, work: off.work ?? null }}
      words=${ends ? { done: t.btnDoneCloseTab } : {}} handlers=${ends ? { done: b => c.act('tab_done', { tab_ref: near.ref, ...(b ? { by: b } : {}) }) } : {}} />`}
    ${hasMore ? html`<div class="flow-more" ref=${box}>
      <button type="button" class="btn-link flow-more-toggle" aria-expanded=${String(more)} aria-haspopup="menu" onClick=${() => setMore(!more)}>${w.more} ${more ? '▴' : '▾'}</button>
      ${more ? html`<div class="flow-more-menu" role="menu">${menu}</div>` : null}
    </div>` : null}
    ${panel === 'task' && toTask ? html`<div class="verbbar-panel" role="group" aria-label=${f.basic.task}>
      <p class="small">${toTask.what}</p>
      <div class="verbbar-acts"><${Btn} size="sm" variant="primary" busy=${busy} onClick=${async () => { const r = await toTask.run(); if (r?.ok) setPanel(null) }}>${f.basic.taskGo}<//>
        <${Btn} size="sm" variant="ghost" onClick=${() => setPanel(null)}>${w.cancel}<//></div>
    </div>` : null}
    ${panel === 'board' ? html`<div class="flow-more-board"><${IssueWays} key=${row.key} row=${row} s=${s} c=${c} sug=${sug} /></div>` : null}
    ${panel === 'improve' ? html`<${Improve} row=${row} tab=${tab && tab.state === 'waiting' && canTab(s, 'send') ? tab : null} s=${s} c=${c} onDone=${() => setPanel(null)} />` : null}

  </div>`
}

/** Give it to the AI (cockpit-card-buttons), the same button on every card: its panel the three ways with what each
 *  does (logic.js aiOf: the one the card's sort fits picked first), the sentence the agent starts with (aiNote: the
 *  way's own until the person writes one, then theirs whatever way), the model under it; Start sends the way's verb
 *  (aiAction) and asks first once cockpit.flow.max_running agents run. A reminder adds I asked: In progress with that
 *  person for three days (verb work_on), back on that day as a check-in that asks how it stands */
function AiGive({ row, ai, s, c, onSent }) {
  const t = T()
  const f = t.flow
  const a = f.ai
  const lang = language()
  const [open, setOpen] = useState(false)
  const [mode, setMode] = useState(ai.mode)
  const [note, setNote] = useState(() => aiNote(ai.mode, row, lang))
  const [own, setOwn] = useState(false)
  const [crowd, setCrowd] = useState(0)
  const [manual, setManual] = useState(null)
  const busy = !!s.ui?.busy?.[row.key]
  const to = ai.sort === 'reminder' ? reminderTo(row) : null
  const pick = m => { setMode(m); if (!own) setNote(aiNote(m, row, lang)); setCrowd(0) }
  const go = async force => {
    const act = aiAction(mode, row, note)
    if (!act) return
    const n = force ? 0 : flowRunning(s)
    if (n >= flowSettings(s).max_running) { setCrowd(n); return }
    setCrowd(0)
    const r = await c.act(act.verb, act.args)
    // no terminal driver: the server hands out the commands to start it by hand
    if (Array.isArray(r?.manual) && r.manual.length) { setManual(r.manual); return }
    if (r?.ok) { setOpen(false); onSent?.() }
  }
  const asked = async () => {
    const r = await c.act('work_on', { key: row.key, who: to, until: checkinDays(s.now || Date.now())[3], text: a.askedNote })
    if (r?.ok) onSent?.()
  }
  const empty = mode === 'go' && !note.trim()
  const id = `ai-${row.key}`
  return html`<div class="flow-ai">
    <div class="verbbar-acts">
      <${Btn} size="sm" variant="secondary" pressed=${open} onClick=${() => { setOpen(!open); setCrowd(0) }}>${`${a.button} ${open ? '▴' : '▾'}`}<//>
      ${to ? html`<${Btn} size="sm" variant="secondary" busy=${busy} onClick=${asked}>${a.asked}<//>` : null}
    </div>
    ${open ? html`<div class="verbbar-panel" role="group" aria-label=${a.button}>
      <p class="small">${a.label}</p>
      <div class="flow-ai-modes">${ai.modes.map(m => html`<${Btn} key=${m} size="sm" variant="secondary" cls="flow-ai-mode" pressed=${mode === m}
        onClick=${() => pick(m)}><span class="flow-ai-mode-name">${m === 'go' && to ? a.draftMode : a.mode[m]}</span>
        <small class="flow-ai-mode-note">${a.modeNote[m]}</small><//>`)}</div>
      <label class="label-caps" for=${`${id}-note`}>${mode === 'go' ? a.note : a.noteOptional}</label>
      <textarea id=${`${id}-note`} class="input textarea" rows="3" maxlength="2000" value=${note}
        onInput=${e => { setNote(e.currentTarget.value); setOwn(true) }}></textarea>
      <${LaunchPick} s=${s} c=${c} items=${[{ key: row.key, title: pointName(row) }]} />
      <div class="verbbar-acts">
        <${Btn} size="sm" variant="primary" busy=${busy} disabled=${empty} onClick=${() => go(false)}>${a.start}<//>
        <${Btn} size="sm" variant="ghost" onClick=${() => setOpen(false)}>${a.cancel}<//>
        ${empty ? html`<span class="muted small">${a.empty}</span>` : null}
      </div>
      ${crowd ? html`<div class="verbbar-acts" role="alert"><span class="small">${f.start.busy(crowd)}</span>
        <${Btn} size="sm" variant="secondary" busy=${busy} onClick=${() => go(true)}>${f.start.anyway}<//></div>` : null}
      ${manual ? html`<div class="verbbar-manual"><p class="small">${f.start.manual}</p><pre class="mono small">${manual.join('\n')}</pre>
        <${Btn} size="xs" variant="secondary" icon="copy" onClick=${() => c.copy(manual.join('\n'))}>${f.start.copy}<//></div>` : null}
    </div>` : null}
  </div>`
}

/** Order ▾ under the list (stage 4): one menu for what orders the list, each only where it applies: Order themes
 *  again (themes), Sort again (the daily triage, where By source is off), Read in with Jev and with Haiku (where Jev
 *  orders the work page), Rename the theme entered; one that runs already stands off and busy, and the lines of what
 *  runs (the themes run, Prio's order) stay under it */
export function OrderMenu({ mode, keys, busy, entered, naming, setNaming, status, s, c }) {
  const t = T()
  const f = t.flow.side
  const p = t.flow.prio
  const th = s.themes
  const [open, setOpen] = useState(false)
  const box = usePopover(open, setOpen)
  const page = workPageOf(s.model?.pages)
  const order = page ? s.jevOrder?.[page.id] : null
  // each item {id, word, run, busy, off, title}: one that runs already stands off and busy, Haiku's runs used up off
  // with why
  const reading = !!order?.running
  const spent = !(s.prio?.haiku?.budget_left > 0)
  const items = [
    mode === 'themes' && keys.length && th?.budget_left !== 0 ? { id: 'regroup', word: f.regroup, run: () => c.flowThemes('regroup', keys.slice(0, 50)), busy } : null,
    Resort({ s, c }) ? { id: 'resort', word: f.resort, run: () => c.triageRun(false), busy: triageRunning(s), title: t.triage.rerunTitle } : null,
    page && jevReady(s) ? { id: 'jev', word: p.readJev, run: () => c.flowPrioRead(page.id, 'jev'), busy: reading } : null,
    page && haikuReady(s) ? { id: 'haiku', word: p.readHaiku, run: () => c.flowPrioRead(page.id, 'haiku'), busy: reading, off: spent,
      title: spent ? p.budget : undefined } : null,
    entered?.theme && !naming ? { id: 'rename', word: f.rename, run: () => setNaming(true) } : null,
  ].filter(Boolean)
  return html`<div class="flow-side-foot flow-side-body flow-order" ref=${box}>
    ${items.length ? html`<button type="button" class="btn-link flow-order-toggle" aria-expanded=${String(open)} aria-haspopup="menu"
      onClick=${() => setOpen(!open)}>${t.flow.simple.order} ${open ? '▴' : '▾'}</button>` : null}
    ${open ? html`<div class="flow-more-menu" role="menu">${items.map(it => html`<button key=${it.id} type="button"
      class="flow-more-item" role="menuitem" disabled=${!!(it.busy || it.off)} aria-busy=${it.busy ? 'true' : undefined} title=${it.title}
      onClick=${() => { setOpen(false); it.run() }}>${it.word}</button>`)}</div>` : null}
    ${busy || status ? html`<p class="muted small" role="status">${status ?? f.ordering}</p>` : null}
    ${mode === 'prio' ? html`<${PrioFoot} s=${s} c=${c} reads=${false} />` : null}
    ${entered?.theme && naming ? html`<${Rename} key=${entered.theme.id} theme=${entered.theme} c=${c} onDone=${() => setNaming(false)} />` : null}
  </div>`
}
