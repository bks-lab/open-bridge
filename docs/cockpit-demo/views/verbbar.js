// SPDX-License-Identifier: MIT
// The cockpit, the five verbs of the Work through page as one part (views/flow.js): Let AI do it, Advise, Done,
// Later until, Drop because. The suggested verb is the primary button (logic.js suggestedVerb). Let AI do it opens
// the start sentence, filled with the row's title and the request for a result line, and starts only with text in
// it; Later until offers the days of the close door (tomorrow, Monday, next week, a date); Drop because offers the
// configured reasons and a field, and sends nothing without a reason. Advise asks a read-only quick question and
// shows the answer in the card, with a way to start from it. What each verb sends is logic.js flowAction.
// For the mouse: no text names a key.
// The rules every component keeps stand at the head of components.js.

import { html, useState } from '../vendor/htm-preact-3.1.1.module.js'
import { dropReasonWord, flowAction, flowSettings, isoDate, parseDate, short, startNote, suggestedVerb, verbsFor } from '../logic.js'
import { T, language } from '../text.js'
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
 *  the card knows better than the triage, `words` gives a verb other words (Start again on a lost start), `onDone`
 *  runs after a verb went out, whatever it answered (the return card forgets its jump), `extra` stands after them */
export function VerbBar({ row, s, c, verbs = null, primary = null, words = {}, onDone = null, extra = null }) {
  const t = T()
  const f = t.flow
  const lang = language()
  const offered = verbsFor(row)
  const list = (verbs ?? offered).filter(v => offered.includes(v))
  const strong = primary ?? suggestedVerb(row, s.triage?.items?.[row.key] ?? null)
  const [open, setOpen] = useState(null)
  const [note, setNote] = useState(() => startNote(row, lang))
  const [reason, setReason] = useState(null)
  const [other, setOther] = useState('')
  const [day, setDay] = useState('')
  const [dayErr, setDayErr] = useState('')
  const [manual, setManual] = useState(null)
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
  const later = async fn => { setOpen(null); finish(await fn()) }
  const toggle = v => { setOpen(open === v ? null : v); setManual(null) }
  const click = v => (PANELS.has(v) ? toggle(v) : v === 'advise' ? c.flowAdvise(row.key) : send(flowAction(v, row)))
  const word = v => words[v] ?? f.verbs[v]
  const yes = row.inbox_id && row.gate === 'your-yes' && row.has_action && row.inbox_state !== 'approved'
  const pickDay = () => {
    const iso = parseDate(day, s.now)
    if (!iso) return setDayErr(t.noDate(day || ' '))
    if (iso <= isoDate(s.now || Date.now())) return setDayErr(t.pastDate)
    send(flowAction('later', row, iso))
  }
  const why = (other.trim() || (reason ? dropReasonWord(reason, lang) : '')).trim()
  const reasons = flowSettings(s).drop_reasons
  return html`<div class="verbbar" role="group" aria-label=${f.title}>
    <${Advice} row=${row} s=${s} c=${c} onStart=${answer => { setNote(startNote({ title: `${row.title}. ${f.advice.title}: ${short(answer, 500)}` }, lang)); setOpen('do') }} />
    <div class="verbbar-row">
      ${list.map(v => html`<${Btn} key=${v} size="sm" variant=${v === strong ? 'primary' : 'secondary'} busy=${busy && v !== 'advise'}
        pressed=${PANELS.has(v) ? open === v : undefined} onClick=${() => click(v)}>${PANELS.has(v) ? `${word(v)} ▾` : word(v)}<//>`)}
      ${yes ? html`<${Btn} size="sm" variant="ghost" busy=${busy} onClick=${() => send({ verb: 'do_it', args: { keys: [row.key] } })}>${f.approve}<//>` : null}
      ${extra}
    </div>
    ${open === 'do' ? html`<div class="verbbar-panel">
      <label class="label-caps" for=${`vb-note-${row.key}`}>${f.start.label}</label>
      <textarea id=${`vb-note-${row.key}`} class="input textarea" rows="3" maxlength="2000" value=${note}
        onInput=${e => setNote(e.currentTarget.value)}></textarea>
      <div class="verbbar-acts">
        <${Btn} size="sm" variant="primary" busy=${busy} disabled=${!note.trim()} onClick=${() => send(flowAction('do', row, note))}>${f.start.button}<//>
        ${note.trim() ? null : html`<span class="muted small">${f.start.empty}</span>`}
      </div>
      ${manual ? html`<div class="verbbar-manual"><p class="small">${f.start.manual}</p><pre class="mono small">${manual.join('\n')}</pre>
        <${Btn} size="xs" variant="secondary" icon="copy" onClick=${() => c.copy(manual.join('\n'))}>${f.start.copy}<//></div>` : null}
    </div>` : null}
    ${open === 'later' ? html`<div class="verbbar-panel" role="group" aria-label=${f.later.label}>
      <div class="verbbar-acts">
        <${Btn} size="sm" variant="secondary" onClick=${() => later(() => c.laterDays(row, 1))}>${f.later.tomorrow}<//>
        <${Btn} size="sm" variant="secondary" onClick=${() => later(() => c.laterMonday(row))}>${f.later.monday}<//>
        <${Btn} size="sm" variant="secondary" onClick=${() => later(() => c.laterDays(row, 7))}>${f.later.week}<//>
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
        <${Btn} size="sm" variant="primary" busy=${busy} disabled=${!why} onClick=${() => send(flowAction('drop', row, why))}>${f.drop.send}<//>
      </span>
    </div>` : null}
  </div>`
}
