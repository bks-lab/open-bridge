// SPDX-License-Identifier: MIT
// The cockpit, the instruction line of Work through (views/flow.js), at the foot of the middle above the walk bar:
// one sentence to the Bridge in place of a few clicks (cockpit.flow.instruct, off by default). One row while it is
// empty, it grows while typed. Above it what it speaks for (logic.js instructScope): the open point, and that a reply
// goes to its live tab where it has one; in the overview the points ticked there, or every point of the theme or area
// (at most 50 go, and the label says so); on the reports card its reports. Where no key stands behind the point (a tab
// alone, a start whose item is not in the list) there is no line. Send asks the server: a small model turns the
// sentence into steps of the verbs there are (Done, Later until, Drop because, Let AI do it with a sentence, a reply to
// the live tab; a mail draft is a start whose sentence says draft only, never send). Then "This is how I understood
// it": the steps in words, each point that drops out of a step struck through in it with why, what was unclear; Run
// (off without a step to run), Change (the sentence back in the field) and Discard. Nothing runs without Run: Run sends
// the steps through the verbs and their undo (logic.js instructCalls, app.js flowBatch: quiet, one toast), its undo
// under the line.
// For the mouse: no text names a key.
// The rules every component keeps stand at the head of components.js.

import { html, useRef, useState } from '../vendor/htm-preact-3.1.1.module.js'
import { dropReasonWord, errorText, flowSettings, formatDay, INSTRUCT_MAX, instructCalls, instructWhy, short } from '../logic.js'
import { T, language } from '../text.js'
import { Btn } from './parts.js'

/** What a step does, in words: its verb (a start for a mail says it drafts only), its day or reason */
function stepWord(st, f, lang) {
  if (st.op === 'do' || st.op === 'mail') return st.mail || st.op === 'mail' ? f.op.mail : f.op.do
  if (st.op === 'later') return f.op.later(formatDay(String(st.until ?? ''), lang))
  if (st.op === 'drop') return f.op.drop(dropReasonWord(st.reason ?? '', lang))
  return f.op[st.op] ?? String(st.op)
}

/** The points of a step: the ones it runs, then the ones that drop out, struck through with why (the page's own checks,
 *  logic.js instructCalls, and the server's); a point not among them says only why */
function StepPoints({ st, k, skipped, s, f }) {
  const mine = skipped.filter(x => x.step === k)
  const points = [...(st.keys ?? []).map((key, i) => ({ key, title: st.titles?.[i] ?? mine.find(x => x.key === key)?.title ?? key,
    why: mine.find(x => x.key === key)?.why ?? null })), ...(st.skipped ?? []).map(x => ({ key: x.key, title: x.title, why: instructWhy(st, x, s) }))]
  if (!points.length) return null
  return html`: ${points.map((p, i) => html`<span key=${`${p.key}${i}`} class="flow-instruct-pt">${i ? ', ' : ''}${!p.why ? short(p.title || p.key, 70)
    : html`${p.title || p.key ? html`<del>${short(p.title || p.key, 70)}</del> ` : null}<span class="flow-instruct-skip muted small">(${f.skipped[p.why] ?? p.why})</span>`}</span>`)}`
}

/** The plan of the sentence, before anything runs: its steps, what drops out of each and why, Run, Change and Discard */
function Plan({ plan, s, c, onChange }) {
  const t = T()
  const f = t.flow.instruct
  const lang = language()
  const { calls, skipped } = instructCalls(plan, s, lang)
  const run = async () => {
    c.flowPlan(null)
    await c.flowBatch(calls, 'instruct')
  }
  const model = plan.model ? String(plan.model).charAt(0).toUpperCase() + String(plan.model).slice(1) : null
  return html`<div class="flow-instruct-plan" role="group" aria-labelledby="flow-instruct-understood">
    <p class="flow-instruct-head"><b id="flow-instruct-understood">${f.understood}</b>${model ? html` <span class="muted small">(${model})</span>` : null}</p>
    ${(plan.steps ?? []).length ? html`<ol class="flow-instruct-steps">${plan.steps.map((st, k) => {
      const runs = (st.keys ?? []).some(key => !skipped.some(x => x.step === k && x.key === key))
      return html`<li key=${k} class=${`flow-instruct-step${runs ? '' : ' is-out'}`}>
        <span class="flow-instruct-op">${stepWord(st, f, lang)}</span><${StepPoints} st=${st} k=${k} skipped=${skipped} s=${s} f=${f} />
        ${st.op === 'reply' && st.text ? html` <q class="flow-instruct-said">${short(st.text, 200)}</q>` : null}
        ${(st.op === 'do' || st.op === 'mail') && st.note && runs ? html`<span class="flow-instruct-note muted small">${short(st.note, 240)}</span>` : null}
      </li>`
    })}</ol>` : null}
    ${plan.unclear ? html`<p class="small flow-instruct-unclear"><span class="label-caps">${f.unclear}</span> ${plan.unclear}</p>` : null}
    <div class="verbbar-acts">
      <${Btn} size="sm" variant="primary" disabled=${!calls.length} onClick=${run}>${f.run}<//>
      <${Btn} size="sm" variant="secondary" onClick=${() => onChange(plan.text ?? '')}>${f.change}<//>
      <${Btn} size="sm" variant="ghost" onClick=${() => c.flowPlan(null)}>${f.discard}<//>
      <span class="muted small">${f.honest}</span>
    </div>
  </div>`
}

/** The line: what it speaks for, the sentence, Send; the plan over it once the server read the sentence */
export function InstructLine({ scope, s, c }) {
  const t = T()
  const f = t.flow.instruct
  const [text, setText] = useState('')
  const [err, setErr] = useState(null)
  const box = useRef(null)
  if (!flowSettings(s).instruct.enabled) return null
  const plan = s.ui.flowPlan ?? null
  const done = s.ui.flowBatch?.from === 'instruct' ? s.ui.flowBatch : null
  const ran = done && !done.running && done.n ? html`<div class="flow-list-done flow-instruct-done" role="status"><span>${f.ran(done.n)}</span>
    ${(done.undo ?? []).length ? html`<${Btn} size="sm" variant="secondary" onClick=${() => c.flowBatchUndo()}>${f.undo}<//>` : null}</div>` : null
  // a point no sentence can act on: no field that could never send, only the undo of an instruction that just ran
  if (!scope) return ran ? html`<section class="flow-instruct" aria-label=${f.label}>${ran}</section>` : null
  const busy = !!s.ui.busy?.['flow:instruct'] || !!s.flow_ai?.instruct_running
  const left = s.flow_ai?.instruct_left
  const v = text.replace(/\s+/g, ' ').trim()
  const label = scope.point ? [f.point(short(scope.title, 80)), scope.tab ? f.reply : null].filter(Boolean).join(' · ')
    : [scope.reports ? f.reports(scope.n) : scope.picked ? f.picked(scope.n) : scope.name ? f.side(scope.n, scope.name, scope.total)
      : f.every(scope.n, scope.total), scope.cut ? f.cut(INSTRUCT_MAX) : null]
      .filter(Boolean).join(' · ')
  // the field grows with what is typed and is one row again once empty
  const grow = el => { if (!el?.style) return; el.style.height = 'auto'; if (el.value && el.scrollHeight) el.style.height = `${el.scrollHeight}px` }
  const send = async () => {
    if (!v || !scope.keys.length) return
    setErr(null)
    const r = await c.flowInstruct(v, scope.keys, scope.point)
    if (r?.ok) { setText(''); if (box.current) box.current.style.height = 'auto' } else if (r?.error) setErr(errorText(r.error, t))
  }
  const change = words => {
    setText(words)
    c.flowPlan(null)
    setTimeout(() => { grow(box.current); box.current?.focus?.() }, 0)
  }
  return html`<section class="flow-instruct" aria-label=${f.label}>
    ${plan ? html`<${Plan} plan=${plan} s=${s} c=${c} onChange=${change} />` : null}
    ${ran}
    <p class="flow-instruct-scope muted small">${label}${Number.isInteger(left) ? html` <span class="flow-instruct-left">· ${f.left(left)}</span>` : null}</p>
    <form class="flow-instruct-row" onSubmit=${e => { e.preventDefault(); send() }}>
      <label class="sr-only" for="flow-instruct-text">${f.label}</label>
      <textarea id="flow-instruct-text" ref=${box} class="input textarea flow-instruct-text" rows="1" maxlength="600" placeholder=${f.placeholder}
        value=${text} onInput=${e => { setText(e.currentTarget.value); grow(e.currentTarget) }}></textarea>
      <${Btn} size="sm" variant="primary" icon="send" busy=${busy} disabled=${!v || !scope.keys.length} onClick=${send}>${f.send}<//>
    </form>
    ${busy ? html`<p class="muted small" role="status">${f.running}</p>` : null}
    ${err ? html`<p class="small verbbar-err" role="status">${err}</p>` : null}
  </section>`
}
