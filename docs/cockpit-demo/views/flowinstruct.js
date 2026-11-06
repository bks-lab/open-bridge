// SPDX-License-Identifier: MIT
// The cockpit, the instruction line of Work through (views/flow.js), at the foot of the middle above the walk bar:
// one sentence to the Bridge in place of a few clicks (cockpit.flow.instruct, off by default). One row while it is
// empty, it grows while typed. Above it what it speaks for (logic.js instructScope): the open point, and that a reply
// goes to its live tab where it has one; in the overview the points ticked there, or every point of the theme or area
// (at most 50 go, and the label says so); on the reports card its reports. Where no key stands behind the point (a tab
// alone, a start whose item is not in the list) there is no line. Send asks the server: a small model turns the
// sentence into steps of the verbs there are (Done, Later until, Drop because, Let AI do it with a sentence, a reply to
// the live tab; a mail draft is a start whose sentence says draft only, never send; on a finished AI run Read, Make it
// a task with its title and Analyse further with its sentence, stage 2). Then "This is how I understood
// it": the steps in words, each point that drops out of a step struck through in it with why, what was unclear; Run
// (off without a step to run), Change (the sentence back in the field) and Discard. Nothing runs without Run: Run sends
// the steps through the verbs and their undo (logic.js instructCalls, app.js flowBatch: quiet, one toast), its undo
// under the line.
// Stage 1 of the one point view: on an open point the line instructs or asks, a switch Instruct | Ask over it where
// both go (ui.flowLine). Ask sends the sentence as a question about this point the way the files view asks a file
// (c.flowAsk: a free quick question, read only, with the point as data, logic.js pointContext, and the task where the
// point is an open task) and shows the answer under the line, with Close; it needs no cockpit.flow.instruct, so on a
// point of its own that is closed, or with the instruction line off, the line asks only. A person's page asks nothing
// here (access.py).
// For the mouse: no text names a key.
// The rules every component keeps stand at the head of components.js.

import { html, useRef, useState } from '../vendor/htm-preact-3.1.1.module.js'
import { dropReasonWord, errorText, flowSettings, formatDay, INSTRUCT_MAX, instructCalls, instructWhy, personOf, pointContext, pointName, rowName, seenOn, short } from '../logic.js'
import { T, language } from '../text.js'
import { Segmented } from './detail.js'
import { Btn } from './parts.js'
import { Prose } from './prose.js'

/** What a step does, in words: its verb (a start for a mail says it drafts only), its day or reason; a later is a
 *  Revisit while the read marks are on (it goes out as one, logic.js instructCalls) */
export function stepWord(st, f, lang, s = null) {
  if (st.op === 'do' || st.op === 'mail') return st.mail || st.op === 'mail' ? f.op.mail : f.op.do
  if (st.op === 'later') return (s && seenOn(s) ? f.op.revisit : f.op.later)(formatDay(String(st.until ?? ''), lang))
  if (st.op === 'drop') return f.op.drop(dropReasonWord(st.reason ?? '', lang))
  return f.op[st.op] ?? String(st.op)
}

/** The points of a step: the ones it runs, then the ones that drop out, struck through with why (the page's own checks,
 *  logic.js instructCalls, and the server's); a point not among them says only why */
function StepPoints({ st, k, skipped, s, f }) {
  const mine = skipped.filter(x => x.step === k)
  // the server words a point by its raw title: the page names it as every view does (logic.js rowName)
  const name = (key, title) => (key ? rowName(s, key) : null) ?? title
  const points = [...(st.keys ?? []).map((key, i) => ({ key, title: name(key, st.titles?.[i] ?? mine.find(x => x.key === key)?.title ?? key),
    why: mine.find(x => x.key === key)?.why ?? null })), ...(st.skipped ?? []).map(x => ({ key: x.key, title: name(x.key, x.title), why: instructWhy(st, x, s) }))]
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
        <span class="flow-instruct-op">${stepWord(st, f, lang, s)}</span><${StepPoints} st=${st} k=${k} skipped=${skipped} s=${s} f=${f} />
        ${st.op === 'reply' && st.text ? html` <q class="flow-instruct-said">${st.text}</q>` : null}
        ${st.op === 'task' && st.title ? html` <q class="flow-instruct-said">${st.title}</q>` : null}
        ${['do', 'mail', 'analyse'].includes(st.op) && st.note && runs ? html`<span class="flow-instruct-note muted small">${st.note}</span>` : null}
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

/** The answer to a question about the point (ui.flowAsk, a quick chat of its own), under the line, with Close */
function AskAnswer({ x, s, c }) {
  const f = T().flow.ask
  const mine = s.ui?.flowAsk?.key === x.row.key ? s.ui.flowAsk : null
  if (!mine) return null
  const conv = (s.quick?.convs ?? []).find(q => q.id === mine.conv)
  const last = conv?.turns?.[conv.turns.length - 1]
  const close = html`<${Btn} size="xs" variant="ghost" onClick=${() => c.flowAskClose()}>${f.close}<//>`
  if (!conv || conv.running || (!last?.a && !last?.error)) {
    return html`<div class="flow-ask-answer" role="status"><p class="muted small">${f.running}</p><div class="verbbar-acts">${close}</div></div>`
  }
  return html`<div class="flow-ask-answer" role="status">
    <p class="label-caps">${f.answer}</p>
    ${last?.a ? html`<${Prose} text=${last.a} cls="verbbar-answer" />` : html`<p class="muted small">${f.failed}</p>`}
    <p class="muted small">${f.note}</p>
    <div class="verbbar-acts">${close}</div>
  </div>`
}

/** Ask on an open point: the sentence as a question about it, the files view's way (module head) */
function AskLine({ x, s, c }) {
  const t = T()
  const f = t.flow.ask
  const [text, setText] = useState('')
  const [err, setErr] = useState(null)
  const box = useRef(null)
  const row = x.row
  const own = !!row.task && row.key === `task:${row.task}`
  const detail = row.task ? s.details?.task?.[x.file ?? row.task]?.data ?? null : null
  const item = row.inbox_id ? s.details?.inbox?.[row.inbox_id]?.data?.item ?? null : null
  // the task it names only where the point is that task and open (a closed one would end the chat at once)
  const task = own && !x.readOnly && !x.file ? row.task : null
  const busy = !!s.ui.busy?.['ask:point']
  const v = text.replace(/\s+/g, ' ').trim()
  const grow = el => { if (!el?.style) return; el.style.height = 'auto'; if (el.value && el.scrollHeight) el.style.height = `${el.scrollHeight}px` }
  const send = async () => {
    if (!v) return
    setErr(null)
    const r = await c.flowAsk(v, pointContext(x, s, own ? detail : null, item, language()), task, row.key)
    if (r?.ok) { setText(''); if (box.current) box.current.style.height = 'auto' } else if (r?.error) setErr(errorText(r.error, t))
  }
  return html`<p class="flow-instruct-scope muted small">${t.flow.instruct.point(short(pointName(row) || row.key, 80))}</p>
    <form class="flow-instruct-row" onSubmit=${e => { e.preventDefault(); send() }}>
      <label class="sr-only" for="flow-ask-text">${f.label}</label>
      <textarea id="flow-ask-text" ref=${box} class="input textarea flow-instruct-text" rows="1" maxlength="4000" placeholder=${f.placeholder}
        value=${text} onInput=${e => { setText(e.currentTarget.value); grow(e.currentTarget) }}></textarea>
      <${Btn} size="sm" variant="primary" icon="spark" busy=${busy} disabled=${!v} onClick=${send}>${f.send}<//>
    </form>
    ${err ? html`<p class="small verbbar-err" role="status">${err}</p>` : null}
    <${AskAnswer} x=${x} s=${s} c=${c} />`
}

/** The line under an open point or the overview: Instruct (the sentence to the Bridge) and, on a point, Ask (a
 *  question about it), a switch over them where both go */
export function InstructLine({ scope, x = null, s, c }) {
  const f = T().flow.ask
  const instruct = flowSettings(s).instruct.enabled
  const askable = !!x && x.kind !== 'reports' && !!x.row?.key && !personOf(s)
  const both = instruct && !!scope && askable
  const mode = both ? s.ui.flowLine ?? 'instruct' : askable && !(instruct && scope) ? 'ask' : 'instruct'
  if (mode === 'instruct' && !instruct) return null
  const line = mode === 'ask' ? html`<${AskLine} x=${x} s=${s} c=${c} />` : html`<${Instruct} scope=${scope} bare=${both} s=${s} c=${c} />`
  if (!both) return mode === 'ask' ? html`<section class="flow-instruct" aria-label=${f.label}>${line}</section>` : line
  return html`<section class="flow-instruct is-switch" aria-label=${f.mode}>
    <div class="flow-line-mode"><${Segmented} label=${f.mode} values=${[['instruct', f.instruct], ['ask', f.ask]]} current=${mode}
      onPick=${v => c.flowLine(v)} /></div>
    ${line}
  </section>`
}

/** Instruct: what it speaks for, the sentence, Send; the plan over it once the server read the sentence. `bare`
 *  inside the switch, which is its section */
function Instruct({ scope, bare = false, s, c }) {
  const t = T()
  const f = t.flow.instruct
  const [text, setText] = useState('')
  const [err, setErr] = useState(null)
  const box = useRef(null)
  const plan = s.ui.flowPlan ?? null
  const done = s.ui.flowBatch?.from === 'instruct' ? s.ui.flowBatch : null
  const ran = done && !done.running && done.n ? html`<div class="flow-list-done flow-instruct-done" role="status"><span>${f.ran(done.n)}</span>
    ${(done.undo ?? []).length ? html`<${Btn} size="sm" variant="secondary" onClick=${() => c.flowBatchUndo()}>${f.undo}<//>` : null}</div>` : null
  // a point no sentence can act on: no field that could never send, only the undo of an instruction that just ran
  const wrap = body => (bare ? body : html`<section class="flow-instruct" aria-label=${f.label}>${body}</section>`)
  if (!scope) return ran ? wrap(ran) : null
  const busy = !!s.ui.busy?.['flow:instruct'] || !!s.flow_ai?.instruct_running
  const left = s.flow_ai?.instruct_left
  const v = text.replace(/\s+/g, ' ').trim()
  const label = scope.point ? [f.point(short(scope.title, 80)), scope.tab ? f.reply : null].filter(Boolean).join(' · ')
    : [scope.picked ? f.picked(scope.n) : scope.reports ? f.reports(scope.n) : scope.name ? f.side(scope.n, scope.name, scope.total)
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
  return wrap(html`
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
    ${err ? html`<p class="small verbbar-err" role="status">${err}</p>` : null}`)
}
