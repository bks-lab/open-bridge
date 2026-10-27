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
// For the mouse: no text names a key.
// The rules every component keeps stand at the head of components.js.

import { html, useState } from '../vendor/htm-preact-3.1.1.module.js'
import { DAY, dropReasonWord, flowAction, flowRunning, flowSettings, isoDate, nextMonday, parseDate, short, startNote, suggestedVerb, verbsFor } from '../logic.js'
import { T, language } from '../text.js'
import { LaunchPick } from './launch.js'
import { Btn } from './parts.js'
import { Prose } from './prose.js'

// the verbs that open a small panel under the bar instead of sending at once
const PANELS = new Set(['do', 'later', 'drop'])

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
 *  strong one first, every other one in the same style */
export function VerbBar({ row, s, c, verbs = null, primary = null, suggested = false, words = {}, handlers = {}, yes: offerYes = true, onDone = null,
  extra = null, stack = false }) {
  const t = T()
  const f = t.flow
  const lang = language()
  const offered = verbsFor(row)
  const strong = primary === false ? null : primary ?? suggestedVerb(row, s.triage?.items?.[row.key] ?? null)
  const given = (verbs ?? offered).filter(v => offered.includes(v))
  const list = stack && given.includes(strong) ? [strong, ...given.filter(v => v !== strong)] : given
  // the strong verb the AI suggested goes out as such; the person's own pick of any other says nothing
  const by = v => (suggested && v === strong ? 'suggestion' : null)
  const [open, setOpen] = useState(null)
  const [note, setNote] = useState(() => startNote(row, lang))
  const [reason, setReason] = useState(null)
  const [other, setOther] = useState('')
  const [day, setDay] = useState('')
  const [dayErr, setDayErr] = useState('')
  const [manual, setManual] = useState(null)
  const [crowd, setCrowd] = useState(0)    // how many ran when Start asked first; 0: not asked
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
  const click = v => (handlers[v] ? own(v) : PANELS.has(v) ? toggle(v) : v === 'advise' ? c.flowAdvise(row.key) : send(flowAction(v, row, '', by(v))))
  const nowMs = s.now || Date.now()
  const putOff = iso => send(flowAction('later', row, iso, by('later')))
  const word = v => words[v] ?? f.verbs[v]
  const yes = offerYes && row.inbox_id && row.gate === 'your-yes' && row.has_action && row.inbox_state !== 'approved'
  const pickDay = () => {
    const iso = parseDate(day, s.now)
    if (!iso) return setDayErr(t.noDate(day || ' '))
    if (iso <= isoDate(s.now || Date.now())) return setDayErr(t.pastDate)
    putOff(iso)
  }
  const why = (other.trim() || (reason ? dropReasonWord(reason, lang) : '')).trim()
  const reasons = flowSettings(s).drop_reasons
  return html`<div class=${`verbbar${stack ? ' is-stack' : ''}`} role="group" aria-label=${f.title}>
    <${Advice} row=${row} s=${s} c=${c} onStart=${answer => { setNote(startNote({ title: `${row.title}. ${f.advice.title}: ${short(answer, 500)}` }, lang)); setOpen('do') }} />
    <div class="verbbar-row">
      ${list.map(v => html`<${Btn} key=${v} size="sm" variant=${v === strong ? 'primary' : 'secondary'} busy=${busy && v !== 'advise'}
        pressed=${PANELS.has(v) ? open === v : undefined} onClick=${() => click(v)}>${PANELS.has(v) ? `${word(v)} ▾` : word(v)}<//>`)}
      ${yes ? html`<${Btn} size="sm" variant=${stack ? 'secondary' : 'ghost'} busy=${busy} onClick=${() => send({ verb: 'do_it', args: { keys: [row.key] } })}>${f.approve}<//>` : null}
      ${extra}
    </div>
    ${open === 'do' ? html`<div class="verbbar-panel">
      <label class="label-caps" for=${`vb-note-${row.key}`}>${f.start.label}</label>
      <textarea id=${`vb-note-${row.key}`} class="input textarea" rows="3" maxlength="2000" value=${note}
        onInput=${e => setNote(e.currentTarget.value)}></textarea>
      <${LaunchPick} s=${s} c=${c} items=${[{ key: row.key, title: row.title }]} />
      <div class="verbbar-acts">
        <${Btn} size="sm" variant="primary" busy=${busy} disabled=${!note.trim()} onClick=${() => start(false)}>${f.start.button}<//>
        ${note.trim() ? null : html`<span class="muted small">${f.start.empty}</span>`}
      </div>
      ${crowd ? html`<div class="verbbar-acts" role="alert"><span class="small">${f.start.busy(crowd)}</span>
        <${Btn} size="sm" variant="secondary" busy=${busy} onClick=${() => start(true)}>${f.start.anyway}<//></div>` : null}
      ${manual ? html`<div class="verbbar-manual"><p class="small">${f.start.manual}</p><pre class="mono small">${manual.join('\n')}</pre>
        <${Btn} size="xs" variant="secondary" icon="copy" onClick=${() => c.copy(manual.join('\n'))}>${f.start.copy}<//></div>` : null}
    </div>` : null}
    ${open === 'later' ? html`<div class="verbbar-panel" role="group" aria-label=${f.later.label}>
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
    ${open === 'drop' ? html`<div class="verbbar-panel" role="group" aria-label=${f.drop.label}>
      <div class="verbbar-acts">
        ${reasons.map(x => html`<${Btn} key=${x} size="sm" variant="secondary" pressed=${reason === x}
          onClick=${() => { setReason(reason === x ? null : x); setOther('') }}>${dropReasonWord(x, lang)}<//>`)}
      </div>
      <span class="field-row">
        <input class="input" type="text" maxlength="200" aria-label=${f.drop.other} placeholder=${f.drop.other} value=${other}
          onInput=${e => { setOther(e.currentTarget.value); setReason(null) }} />
        <${Btn} size="sm" variant="primary" busy=${busy} disabled=${!why} onClick=${() => send(flowAction('drop', row, why, by('drop')))}>${f.drop.send}<//>
      </span>
    </div>` : null}
  </div>`
}
