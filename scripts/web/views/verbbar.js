// SPDX-License-Identifier: MIT
// The cockpit, the five verbs of the Work through page as one part (views/flow.js): Let AI do it, Advise, Done,
// Later until, Drop because. The suggested verb is the primary button (logic.js suggestedVerb). Let AI do it opens
// the start sentence, filled with the row's title and the request for a result line, and starts only with text in
// it, the model and its effort under it (views/launch.js LaunchPick: with Auto, the router's recommendation for this
// row, fetched once and kept for the page's life), and asks first once cockpit.flow.max_running agents run (logic.js
// flowRunning); Later until offers the days of the close door (tomorrow, Monday, next week, a date); Drop because offers the
// configured reasons and a field, and sends nothing without a reason. Advise asks a read-only quick question and
// shows the answer in the card, with a way to start from it. What each verb sends is logic.js flowAction. On the right
// column of Work through the verbs stand under each other (`stack`), the strong one first, a panel under them; a verb
// whose strong button the AI suggested (`suggested`) says so to the server (by suggestion), any other click sends none.
// Stage 1 of the one point view (`fixed`): the basic verbs stand in their one order whatever is strong (logic.js
// BASIC_VERBS), one that cannot go now off (`off`, {verb: why}) with why in one line under them, Make it a task opens
// a panel that says what it does before it goes (`toTask` {what, run}: verb to_task for an inbox item, the GitHub page's
// step for an issue), and what the kind adds (Advise, Give your yes, `lead`, `extra`) in a row of its own under them.
// Stage 4, simpler (`simple`): the four states in a quiet 2x2 (logic.js SIMPLE_STATES: Done, In progress ▾, Later ▾,
// Drop ▾; an inbox item's Drop is Out of date ▾, an idea's Discard ▾, with the reasons of Out of date and the why of a
// card the AI found out of date written in: logic.js dropWord, dropReasonsOf, dropSeed), one that cannot go now off
// with why under them; In progress opens who has it (you, the Bridge, the people
// the Bridge names, someone else) and when to ask again (in 3 days, a week, two weeks, a date) with an optional
// sentence (verb work_on); the Bridge is Let AI do it, its start sentence and model. The strong button and More stand
// apart (views/flowside.js SimpleActs); `apply` asks the bar to open one of its panels from outside (the strong
// button's start when the cap of what runs is reached).
// For the mouse: no text names a key.
// The rules every component keeps stand at the head of components.js.

import { html, useState } from '../vendor/htm-preact-3.1.1.module.js'
import { personOf, BASIC_VERBS, checkinDays, DAY, dropReasonWord, flowAction, flowRunning, flowSettings, isoDate, nextMonday, nextWho, parseDate, short,
  SIMPLE_STATES, startNote, suggestedVerb, verbsFor, workWho, pointName, seenOn, dropWhat, dropReasonsOf, dropSeed, dropWord } from '../logic.js'
import { T, language } from '../text.js'
import { LaunchPick } from './launch.js'
import { Btn } from './parts.js'
import { Prose } from './prose.js'

// the verbs that open a small panel under the bar instead of sending at once
const PANELS = new Set(['do', 'later', 'drop', 'task', 'work'])
const BASIC = new Set(BASIC_VERBS)

/** A list of verbs in words, the last joined by and: "Done and Drop", "Erledigt und Weg" */
const joined = (list, and) => (list.length > 1 ? `${list.slice(0, -1).join(', ')} ${and} ${list.at(-1)}` : list[0] ?? '')

/** The answer of Advise for this row (ui.flowAdvice, a quick chat of its own), with a way to start from it */
function Advice({ row, s, c, onStart }) {
  const f = T().flow.advice
  const mine = s.ui?.flowAdvice?.key === row.key ? s.ui.flowAdvice : null
  if (!mine) return null
  const conv = (s.quick?.convs ?? []).find(q => q.id === mine.conv)
  const last = conv?.turns?.[conv.turns.length - 1]
  const close = html`<${Btn} size="xs" variant="ghost" onClick=${() => c.flowAdviseClose()}>${f.close}<//>`
  if (!conv || conv.running || (!last?.a && !last?.error)) {
    return html`<div class="verbbar-advice" role="status"><p class="muted small">${f.running}</p><div class="verbbar-acts">${close}</div></div>`
  }
  return html`<div class="verbbar-advice" role="status">
    <p class="label-caps">${f.title}</p>
    ${last?.a ? html`<${Prose} text=${last.a} cls="verbbar-answer" />` : html`<p class="muted small">${f.failed}</p>`}
    <p class="muted small">${f.note}</p>
    <div class="verbbar-acts">
      ${last?.a ? html`<${Btn} size="xs" variant="secondary" onClick=${() => onStart(last.a)}>${f.start}<//>` : null}
      ${close}
    </div>
  </div>`
}

/** The five verbs of one row. `verbs` narrows them (a card that offers fewer), `primary` names the strong one where
 *  the card knows better than the triage (false: none, a way to the tab is the strong one), `suggested` says the AI
 *  suggested that one, `words` gives a verb other words (Start again on a lost start), `handlers` a verb its own
 *  action (Done that closes the tab too: called with the verb's by, answers what the server answered), `yes` false
 *  leaves out Give your yes (an agent works on the point already), `onDone` runs after a verb went out, whatever it
 *  answered (the return card forgets its jump), `extra` stands after them, `stack` puts them under each other with the
 *  strong one first, every other one in the same style. `first` stands before all of them (Open on GitHub), `lead`
 *  right after the strong one (View and Improve on a finished start), `tail` apart under the bar (a tab's close, so it
 *  is no click by mistake); `yesFirst` makes Give your yes the strong one, first, where it is offered. `fixed`, `off`
 *  and `toTask`: the basic verbs of the one point view (module head) */
export function VerbBar({ row, s, c, verbs = null, primary = null, suggested = false, words = {}, handlers = {}, yes: offerYes = true, onDone = null,
  extra = null, stack = false, first = null, lead = null, tail = null, yesFirst = false, fixed = false, off = {}, toTask = null, simple = false,
  opened = null }) {
  const t = T()
  const f = t.flow
  const lang = language()
  // a person gets the verbs of the row, none that hands it to a model or a tab (access.py)
  const offered = verbsFor(row).filter(v => !personOf(s) || ['done', 'later', 'drop'].includes(v))
  const yes = offerYes && row.inbox_id && row.gate === 'your-yes' && row.has_action && row.inbox_state !== 'approved'
  const yesStrong = yesFirst && yes
  // fixed: the basic verbs as given (logic.js basicVerbs says which are off), Make it a task with its way, the rest as
  // the row offers them
  const given = fixed ? (verbs ?? []).filter(v => (v === 'task' ? !!toTask : BASIC.has(v) || offered.includes(v)))
    : (verbs ?? offered).filter(v => offered.includes(v))
  const strong0 = primary === false || yesStrong ? null : primary ?? suggestedVerb(row, s.triage?.items?.[row.key] ?? null)
  // a verb that cannot go now is never the strong one
  const strong = strong0 && !off[strong0] && given.includes(strong0) ? strong0 : null
  const list = fixed ? given : stack && given.includes(strong) ? [strong, ...given.filter(v => v !== strong)] : given
  // the strong verb the AI suggested goes out as such; the person's own pick of any other says nothing
  const by = v => (suggested && v === strong ? 'suggestion' : null)
  const [open, setOpen] = useState(opened)
  const [note, setNote] = useState(() => startNote(row, lang))
  // In progress (stage 4): who has it, when to ask again (a week by default), what runs
  const [who, setWho] = useState(null)
  const [otherWho, setOtherWho] = useState('')
  const [askDay, setAskDay] = useState(() => checkinDays(s.now || Date.now())[7])
  const [askOwn, setAskOwn] = useState('')
  const [runs, setRuns] = useState('')
  const [reason, setReason] = useState(null)
  // the four states (`simple`): an inbox item's Drop is Out of date (an idea's Discard), with its own reasons and the
  // why of a card the AI found out of date written in (logic.js dropWord, dropReasonsOf, dropSeed)
  const [other, setOther] = useState(() => (simple ? dropSeed(row) : ''))
  const outWord = simple ? dropWord(row, lang) : null
  const outdated = !!outWord && outWord === f.ai.obsolete
  const [day, setDay] = useState('')
  const [dayErr, setDayErr] = useState('')
  const [manual, setManual] = useState(null)
  const [crowd, setCrowd] = useState(0)    // how many ran when Start asked first; 0: not asked
  // the read marks on (cockpit.flow.seen): Later of the four states is Revisit ▾, read now and back unread on its day; the
  // sentence, when there is one, is the only thing written into the task
  const revisit = simple && seenOn(s)
  // and In progress is Hand over: for someone else only (the person's own later is Revisit, keeping it active is Keep
  // in focus), the same verb work_on and its check-in
  const hand = revisit
  const [sentence, setSentence] = useState('')
  const busy = !!s.ui?.busy?.[row.key]
  const finish = r => {
    if (r?.ok) c.flowDecided()
    onDone?.(r)
  }
  const send = async a => {
    if (!a) return
    const r = await c.act(a.verb, a.args)
    // no terminal driver: the server hands out the commands to start it by hand
    if (Array.isArray(r?.manual) && r.manual.length) { setManual(r.manual); return }
    setOpen(null)
    finish(r)
  }
  const toggle = v => { setOpen(open === v ? null : v); setManual(null); setCrowd(0) }
  // In progress goes out to the person picked, or as Let AI do it where the Bridge has it (its start panel)
  const workTo = who === 'other' ? otherWho.trim() : who
  const workGo = () => {
    if (workTo === 'bridge') { setOpen('do'); return }
    const day = askOwn.trim() ? parseDate(askOwn, s.now) : askDay
    if (!workTo || !day) return
    send({ verb: 'work_on', args: { key: row.key, who: workTo, until: day, ...(runs.trim() ? { text: runs.trim() } : {}) } })
  }
  // Start: at once below the cap of what runs, else after Start anyway (the count read at the click, no timer)
  const start = force => {
    const a = flowAction('do', row, note, by('do'))
    if (!a) return
    const running = force ? 0 : flowRunning(s)
    if (running >= flowSettings(s).max_running) { setCrowd(running); return }
    setCrowd(0)
    send(a)
  }
  const own = async v => finish(await handlers[v](by(v)))
  const click = v => (off[v] ? null : handlers[v] ? own(v) : PANELS.has(v) ? toggle(v) : v === 'advise' ? c.flowAdvise(row.key) : send(flowAction(v, row, '', by(v))))
  const makeTask = async () => {
    const r = await toTask?.run?.()
    if (r?.ok) setOpen(null)
    finish(r)
  }
  const nowMs = s.now || Date.now()
  const putOff = iso => send(flowAction('later', row, iso, by('later'), revisit ? { revisit: true, ...(sentence.trim() ? { text: sentence.trim() } : {}) } : null))
  const word = v => words[v] ?? (v === 'drop' && outWord ? outWord : v === 'task' ? f.basic.task : revisit && v === 'later' ? f.marks.revisit : hand && v === 'work' ? f.marks.handOver
    : simple && f.simple[v] ? f.simple[v] : f.verbs[v])
  const pickDay = () => {
    const iso = parseDate(day, s.now)
    if (!iso) return setDayErr(t.noDate(day || ' '))
    if (iso <= isoDate(s.now || Date.now())) return setDayErr(t.pastDate)
    putOff(iso)
  }
  const why = (other.trim() || (reason ? dropReasonWord(reason, lang) : '')).trim()
  const reasons = simple ? dropReasonsOf(row, s) : flowSettings(s).drop_reasons
  const btn = v => html`<${Btn} key=${v} size="sm" variant=${v === strong ? 'primary' : 'secondary'} busy=${busy && v !== 'advise' && !off[v]}
    disabled=${!!off[v]} pressed=${PANELS.has(v) && !off[v] ? open === v : undefined} onClick=${() => click(v)}>${PANELS.has(v) ? `${word(v)} ▾` : word(v)}<//>`
  const btns = list.map(btn)
  // what `lead` follows: the strong verb where it stands first, else nothing
  const head = strong && list[0] === strong ? 1 : 0
  const yesBtn = variant => html`<${Btn} size="sm" variant=${variant} busy=${busy} onClick=${() => send({ verb: 'do_it', args: { keys: [row.key] } })}>${f.approve}<//>`
  // fixed: why the verbs that are off cannot go now, one line per reason
  const offWhy = fixed ? [...new Set(list.filter(v => off[v]).map(v => off[v]))] : []
  const offLine = offWhy.length ? html`<div class="verbbar-off">${offWhy.map(why => html`<p key=${why} class="muted small">${f.basic.offLine(
    joined(list.filter(v => off[v] === why).map(v => f.basic.short[v] ?? word(v)), f.basic.and), f.basic.off[why] ?? why)}</p>`)}</div>` : null
  const kind = fixed ? html`${yesStrong ? yesBtn('primary') : null}${first}${lead}${list.filter(v => !BASIC.has(v)).map(btn)}
    ${yes && !yesStrong ? yesBtn('secondary') : null}${extra}` : null
  const days = checkinDays(nowMs)
  const people = simple && open === 'work' ? workWho(s).filter(p => !hand || p !== 'me') : []
  const simpleBtn = v => html`<${Btn} key=${v} size="xs" variant="secondary" cls="verbbar-state" busy=${busy && !off[v]} disabled=${!!off[v]}
    title=${off[v] ? f.basic.off[off[v]] ?? off[v] : undefined} pressed=${PANELS.has(v) && !off[v] ? open === v : undefined}
    onClick=${() => click(v)}>${PANELS.has(v) ? `${word(v)} ▾` : word(v)}<//>`
  const simpleOff = simple ? [...new Set(SIMPLE_STATES.filter(v => off[v]).map(v => off[v]))] : []
  return html`<div class=${`verbbar${stack ? ' is-stack' : ''}${fixed ? ' is-fixed' : ''}${simple ? ' is-simple' : ''}`} role="group" aria-label=${f.title}>
    <${Advice} row=${row} s=${s} c=${c} onStart=${answer => { setNote(startNote({ title: `${row.title}. ${f.advice.title}: ${short(answer, 500)}` }, lang)); setOpen('do') }} />
    ${simple ? html`${first}<div class="verbbar-grid">${SIMPLE_STATES.map(simpleBtn)}</div>
      ${simpleOff.length ? html`<div class="verbbar-off">${simpleOff.map(why => html`<p key=${why} class="muted small">${f.basic.offLine(
        joined(SIMPLE_STATES.filter(v => off[v] === why).map(v => f.basic.short[v] ?? word(v)), f.basic.and), f.basic.off[why] ?? why)}</p>`)}</div>` : null}
      ${extra}`
    : fixed ? html`<div class="verbbar-row verbbar-basic">${list.filter(v => BASIC.has(v)).map(btn)}</div>
      ${offLine}
      ${kind ? html`<div class="verbbar-row verbbar-kind">${kind}</div>` : null}`
      : html`<div class="verbbar-row">
      ${first}
      ${yesStrong ? yesBtn('primary') : null}
      ${btns.slice(0, head)}${lead}${btns.slice(head)}
      ${yes && !yesStrong ? yesBtn(stack ? 'secondary' : 'ghost') : null}
      ${extra}
    </div>`}
    ${tail ? html`<div class="verbbar-row verbbar-tail">${tail}</div>` : null}
    ${open === 'work' ? html`<div class="verbbar-panel flow-work" role="group" aria-label=${f.simple.work}>
      <p class="label-caps">${hand ? f.marks.handTo : f.simple.whoLabel}</p>
      <div class="flow-work-chips">${people.map(p => html`<${Btn} key=${p} size="xs" variant="secondary" pressed=${who === p}
        onClick=${() => setWho(p)}>${p === 'me' ? f.simple.me : p === 'bridge' ? f.simple.bridge : nextWho(p, s, lang)}<//>`)}
        <${Btn} size="xs" variant="secondary" pressed=${who === 'other'} onClick=${() => setWho('other')}>${f.simple.other}<//></div>
      ${who === 'other' ? html`<input class="input" type="text" maxlength="60" aria-label=${f.simple.otherLabel} placeholder=${f.simple.otherLabel} value=${otherWho}
        onInput=${e => setOtherWho(e.currentTarget.value)} />` : null}
      ${workTo === 'bridge' ? html`<p class="muted small">${f.simple.bridgeNote}</p>` : html`<p class="label-caps">${f.simple.whenLabel}</p>
      <div class="flow-work-chips">${[3, 7, 14].map(d => html`<${Btn} key=${d} size="xs" variant="secondary"
        pressed=${!askOwn.trim() && askDay === days[d]} onClick=${() => { setAskDay(days[d]); setAskOwn('') }}>${f.simple.inDays(d)}<//>`)}</div>
      <input class="input input-date mono" type="text" inputmode="numeric" aria-label=${f.simple.dateLabel} placeholder=${f.simple.dateHint} value=${askOwn}
        onInput=${e => setAskOwn(e.currentTarget.value)} />
      <input class="input" type="text" maxlength="300" aria-label=${f.simple.runsLabel} placeholder=${f.simple.runsLabel} value=${runs}
        onInput=${e => setRuns(e.currentTarget.value)} />`}
      <div class="verbbar-acts">
        <${Btn} size="sm" variant="primary" busy=${busy} disabled=${!workTo} onClick=${workGo}>${workTo === 'bridge' ? f.simple.toBridge : f.simple.take}<//>
        <${Btn} size="sm" variant="ghost" onClick=${() => setOpen(null)}>${f.simple.cancel}<//>
      </div>
    </div>` : null}
    ${open === 'task' && toTask ? html`<div class="verbbar-panel" role="group" aria-label=${f.basic.task}>
      <p class="small">${toTask.what}</p>
      <div class="verbbar-acts"><${Btn} size="sm" variant="primary" busy=${busy} onClick=${makeTask}>${f.basic.taskGo}<//></div>
    </div>` : null}
    ${open === 'do' ? html`<div class="verbbar-panel">
      <label class="label-caps" for=${`vb-note-${row.key}`}>${f.start.label}</label>
      <textarea id=${`vb-note-${row.key}`} class="input textarea" rows="3" maxlength="2000" value=${note}
        onInput=${e => setNote(e.currentTarget.value)}></textarea>
      <${LaunchPick} s=${s} c=${c} items=${[{ key: row.key, title: pointName(row) }]} />
      <div class="verbbar-acts">
        <${Btn} size="sm" variant="primary" busy=${busy} disabled=${!note.trim()} onClick=${() => start(false)}>${f.start.button}<//>
        ${note.trim() ? null : html`<span class="muted small">${f.start.empty}</span>`}
      </div>
      ${crowd ? html`<div class="verbbar-acts" role="alert"><span class="small">${f.start.busy(crowd)}</span>
        <${Btn} size="sm" variant="secondary" busy=${busy} onClick=${() => start(true)}>${f.start.anyway}<//></div>` : null}
      ${manual ? html`<div class="verbbar-manual"><p class="small">${f.start.manual}</p><pre class="mono small">${manual.join('\n')}</pre>
        <${Btn} size="xs" variant="secondary" icon="copy" onClick=${() => c.copy(manual.join('\n'))}>${f.start.copy}<//></div>` : null}
    </div>` : null}
    ${open === 'later' && revisit ? html`<div class="verbbar-panel flow-revisit" role="group" aria-label=${f.marks.revisitLabel}>
      <p class="label-caps">${f.marks.revisitLabel}</p>
      <div class="verbbar-acts">
        <${Btn} size="sm" variant="secondary" onClick=${() => putOff(isoDate(nowMs + DAY))}>${f.marks.tomorrow}<//>
        <${Btn} size="sm" variant="secondary" onClick=${() => putOff(isoDate(nextMonday(nowMs)))}>${f.marks.monday}<//>
        <${Btn} size="sm" variant="secondary" onClick=${() => putOff(isoDate(nowMs + 7 * DAY))}>${f.marks.week}<//>
        <${Btn} size="sm" variant="secondary" onClick=${() => putOff(isoDate(nowMs + 14 * DAY))}>${f.marks.twoWeeks}<//>
      </div>
      <span class="field-row">
        <input class="input input-date mono" type="text" inputmode="numeric" aria-label=${f.marks.date} placeholder=${t.datePlaceholder}
          value=${day} aria-invalid=${dayErr ? 'true' : undefined} onInput=${e => { setDay(e.currentTarget.value); setDayErr('') }} />
        <${Btn} size="sm" variant="secondary" disabled=${!day.trim()} onClick=${pickDay}>${f.marks.go}<//>
        ${dayErr ? html`<span class="small verbbar-err" role="alert">${dayErr}</span>` : null}
      </span>
      <input class="input" type="text" maxlength="300" aria-label=${f.marks.text} placeholder=${f.marks.text} value=${sentence}
        onInput=${e => setSentence(e.currentTarget.value)} />
    </div>` : null}
    ${open === 'later' && !revisit ? html`<div class="verbbar-panel" role="group" aria-label=${f.later.label}>
      <div class="verbbar-acts">
        <${Btn} size="sm" variant="secondary" onClick=${() => putOff(isoDate(nowMs + DAY))}>${f.later.tomorrow}<//>
        <${Btn} size="sm" variant="secondary" onClick=${() => putOff(isoDate(nextMonday(nowMs)))}>${f.later.monday}<//>
        <${Btn} size="sm" variant="secondary" onClick=${() => putOff(isoDate(nowMs + 7 * DAY))}>${f.later.week}<//>
      </div>
      <span class="field-row">
        <input class="input input-date mono" type="text" inputmode="numeric" aria-label=${f.later.date} placeholder=${t.datePlaceholder}
          value=${day} aria-invalid=${dayErr ? 'true' : undefined} onInput=${e => { setDay(e.currentTarget.value); setDayErr('') }} />
        <${Btn} size="sm" variant="secondary" disabled=${!day.trim()} onClick=${pickDay}>${f.later.go}<//>
        ${dayErr ? html`<span class="small verbbar-err" role="alert">${dayErr}</span>` : null}
      </span>
    </div>` : null}
    ${open === 'drop' ? html`<div class="verbbar-panel" role="group" aria-label=${outdated ? f.ai.obsoleteLabel : f.drop.label}>
      <div class="verbbar-acts">
        ${reasons.map(x => html`<${Btn} key=${x} size="sm" variant="secondary" pressed=${reason === x}
          onClick=${() => { setReason(reason === x ? null : x); setOther('') }}>${dropReasonWord(x, lang)}<//>`)}
      </div>
      <span class="field-row">
        <input class="input" type="text" maxlength="200" aria-label=${f.drop.other} placeholder=${f.drop.other} value=${other}
          onInput=${e => { setOther(e.currentTarget.value); setReason(null) }} />
        <${Btn} size="sm" variant="primary" busy=${busy} disabled=${!why} onClick=${() => send(flowAction('drop', row, why, by('drop')))}>${outdated ? f.ai.obsoleteSend : f.drop.send}<//>
      </span>
      <p class="muted small flow-drop-what">${dropWhat(row, s, lang)}</p>
    </div>` : null}
  </div>`
}
