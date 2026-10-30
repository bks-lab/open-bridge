// SPDX-License-Identifier: MIT
// The cockpit, the fields of the Chat (logic.js fieldsOf): one to four side by side, each holding a tab or Zum Thema.
// They live on this page only, so tabs of any workspace stand together and the terminal stays as it is. FieldBar on
// top: the tabs of the open chat's workspace, Chat + Thema, the layouts, swapping and the view without the page around
// it. A click in the list goes to the active field, a field's head dragged onto another swaps the two, a tab dragged
// from the list opens where it lands. The bar between two fields swaps them and sets their width. Zum Thema (TopicPane)
// is the reading of the chat and its file, the same two the files tab and the guide draw; AnswerBar is what a waiting
// tab asks, at the edge of the terminal, which stays in view. Its words go out through the guarded reply verbs.
// The rules every component keeps stand at the head of components.js.

import { html, useState } from '../vendor/htm-preact-3.1.1.module.js'
import { FIELD_COUNT, answerMark, canTab, errorText, guideChoices, guideOf, indexRows, isTopic, previewText, replySend, short, stateToken, tabStateKey, taskOfTab } from '../logic.js'
import { T } from '../text.js'
import { OpenFile } from './dossier.js'
import { GuideTree } from './guide.js'
import { TAB_MSG_MAX } from './nav.js'
import { Btn, Dot, Icon, StateLine } from './parts.js'
import { TabReply } from './reply.js'
import { Pop, usePop } from './termtools.js'

const LAYOUTS = [['1', 1, 1], ['2h', 2, 1], ['2v', 1, 2], ['3', 3, 1], ['m2', 2, 2], ['4', 2, 2]]
const DRAG = 'text/x-cockpit-field'

/** What a drag carries: a field by its index or a tab of the list by its ref */
export const dragField = i => e => { e.dataTransfer.setData(DRAG, `f${i}`); e.dataTransfer.effectAllowed = 'move' }
export const dragTab = ref => e => { e.dataTransfer.setData(DRAG, `t${ref}`); e.dataTransfer.effectAllowed = 'move' }

/** Where a drag may land: over a field, which shows it. On the drop a field swaps, a tab opens there */
const dropOn = (i, c) => ({
  onDragOver: e => { if (e.dataTransfer.types.includes(DRAG)) { e.preventDefault(); e.currentTarget.classList.add('is-over') } },
  onDragLeave: e => e.currentTarget.classList.remove('is-over'),
  onDrop: e => {
    const v = e.dataTransfer.getData(DRAG)
    e.currentTarget.classList.remove('is-over')
    if (!v) return
    e.preventDefault()
    if (v[0] === 'f') c.fieldSwap(Number(v.slice(1)), i)
    else c.fieldDrop(i, v.slice(1))
  },
})

function LayoutMark({ cols, rows, cells, big }) {
  return html`<i class="lay-mark" style=${{ gridTemplateColumns: `repeat(${cols}, 1fr)`, gridTemplateRows: `repeat(${rows}, 1fr)` }} aria-hidden="true">
    ${Array.from({ length: cells }, (_, k) => html`<b key=${k} class=${big && !k ? 'is-big' : undefined}></b>`)}</i>`
}

/** How the page and the terminal go together: each way is a switch, off until set, kept in this browser */
function LinkButton({ s, c }) {
  const t = T().fields
  const { pop, close, open } = usePop()
  const link = s.ui.link ?? {}
  const row = (k, word, why) => html`<button type="button" class="pop-item" aria-pressed=${String(!!link[k])} onClick=${() => c.setLink(k, !link[k])}>
    <span class="pop-check" aria-hidden="true">${link[k] ? '✓' : ''}</span><span>${word}<span class="muted small pop-why">${why}</span></span></button>`
  return html`<button type="button" class="field-link" title=${t.link} onClick=${open('link')}><i class=${link.follow || link.jump ? 'is-on' : ''} aria-hidden="true"></i>${t.linkWord}</button>
    ${pop ? html`<${Pop} at=${pop.at} onClose=${close}><h4 class="label-caps">${t.link}</h4>
      ${row('follow', t.follow2, t.followWhy)}${row('jump', t.jump, t.jumpWhy)}<//>` : null}`
}

/** The bar over the fields: the tabs of the open chat's workspace, as a terminal shows them, each with its state */
export function FieldBar({ s, c, f, tab }) {
  const t = T().fields
  const w = (s.tabs?.tabs ?? []).filter(x => x.workspace === tab?.workspace)
  const hasTopic = f.panes.some(isTopic)
  return html`<div class="field-bar" role="group" aria-label=${t.bar}>
    ${tab ? html`<span class="field-ws">${tab.workspace}</span>` : null}
    <div class="field-tabs">${w.map(x => html`<button type="button" key=${x.ref} class=${`field-tab${x.ref === tab?.ref ? ' is-on' : ''}`} title=${x.name}
      aria-current=${x.ref === tab?.ref ? 'true' : undefined} onClick=${() => c.pickRoom({ kind: 'tab', id: x.ref })}>
      <${Dot} token=${stateToken(tabStateKey(x))} pulse=${x.state === 'working'} /><span>${x.name}</span></button>`)}
      ${tab?.ws_ref && canTab(s, 'new_tab') ? html`<button type="button" class="field-plus" title=${T().tools.newChatIn(tab.workspace)} aria-label=${T().tools.newChatIn(tab.workspace)}
        onClick=${() => c.newChat({ ws: { ref: tab.ws_ref, title: tab.workspace } })}>+</button>` : null}</div>
    <span class="field-layouts">
      <${Btn} size="xs" variant="secondary" pressed=${hasTopic} title=${t.chatTopicTitle} onClick=${() => c.fieldTopic()}>${t.chatTopic}<//>
      ${LAYOUTS.map(([id, cols, rows]) => html`<button type="button" key=${id} class=${`field-lay${f.layout === id ? ' is-on' : ''}`} title=${t.layout[id]} aria-label=${t.layout[id]}
        aria-pressed=${String(f.layout === id)} onClick=${() => c.fieldLayout(id)}><${LayoutMark} cols=${cols} rows=${rows} cells=${FIELD_COUNT[id]} big=${id === 'm2'} /></button>`)}
      <button type="button" class="field-lay" title=${t.swap} aria-label=${t.swap} disabled=${f.panes.length < 2}
        onClick=${() => c.fieldSwap(f.active, (f.active + 1) % f.panes.length)}><span aria-hidden="true">⇄</span></button>
      <button type="button" class=${`field-lay${s.ui.fieldsFull ? ' is-on' : ''}`} title=${t.full} aria-label=${t.full} aria-pressed=${String(!!s.ui.fieldsFull)}
        onClick=${() => c.fieldsFull()}><span aria-hidden="true">⛶</span></button>
      ${canTab(s, 'focus') ? html`<${LinkButton} s=${s} c=${c} />` : null}
    </span>
  </div>`
}

/** A bar between two fields: its button swaps them; where `drag` is set it also sets their width */
function Gutter({ a, b, c, at, row = false, box = null }) {
  const t = T().fields
  const down = box ? e => {
    if (e.target.closest('button')) return
    e.preventDefault()
    const grid = e.currentTarget.parentElement
    const r = grid.getBoundingClientRect()
    let last = null
    const move = ev => { last = ((ev.clientX - r.left) / r.width) * 100; grid.style.setProperty('--split', `${Math.min(75, Math.max(25, last))}%`) }
    const up = () => { removeEventListener('pointermove', move); removeEventListener('pointerup', up); if (last != null) c.fieldSplit(last) }
    addEventListener('pointermove', move)
    addEventListener('pointerup', up)
  } : undefined
  return html`<div class=${`field-gutter${box ? ' can-drag' : ''}${row ? ' is-row' : ''}`} style=${row ? { top: at } : { left: at }} onPointerDown=${down}>
    <button type="button" class="field-swap" title=${t.swapTwo} aria-label=${t.swapTwo} onClick=${() => c.fieldSwap(a, b)}><span aria-hidden="true">⇄</span></button></div>`
}

/** The fields in their layout: `render(pane, i)` draws each, wrapped so a drag can land on it */
export function FieldGrid({ f, c, render }) {
  const wide = f.layout === '2h' || f.layout === 'm2'
  return html`<div class="fields" data-layout=${f.layout} style=${{ '--split': `${f.split}%` }}>
    ${f.panes.map((p, i) => html`<div class=${`field${i === f.active && f.panes.length > 1 ? ' is-active' : ''}`} key=${typeof p === 'string' ? p : `f${i}`}
      onMouseDownCapture=${() => c.fieldFocus(i)} ...${f.panes.length > 1 ? dropOn(i, c) : {}}>${render(p, i)}</div>`)}
    ${wide ? html`<${Gutter} a=${0} b=${1} c=${c} at="var(--split)" box />` : null}
    ${f.layout === '3' ? html`<${Gutter} a=${0} b=${1} c=${c} at="33.33%" /><${Gutter} a=${1} b=${2} c=${c} at="66.66%" />` : null}
    ${f.layout === '2v' ? html`<${Gutter} a=${0} b=${1} c=${c} at="50%" row />` : null}
  </div>`
}

/** The head's own marks of a field in a split: the grip to drag it and × to close it, the tab runs on */
export const FieldGrip = ({ i, on }) => (on ? html`<span class="field-grip" draggable="true" title=${T().fields.grip} onDragStart=${dragField(i)} aria-hidden="true">⠿</span>` : null)
export const FieldClose = ({ i, c, on }) => (on ? html`<${Btn} size="xs" variant="ghost" icon="close" label=${T().fields.closeField} title=${T().fields.closeField} onClick=${() => c.fieldClose(i)} />` : null)

/** A free field: what could stand here */
export function EmptyField({ i, c }) {
  const t = T().fields
  return html`<section class="panel chat-main rooms-main field-empty"><p class="muted">${t.free}</p>
    <div class="btn-row"><${Btn} size="xs" variant="secondary" onClick=${() => c.fieldTopic(i)}>${t.topic}<//></div></section>`
}

/** Links a chat to a file, by the session that runs in the tab (the same verb the Sessions page uses) */
function LinkFile({ s, c, tab }) {
  const t = T().fields
  const sess = (s.sessions?.sessions ?? []).filter(x => x.tab?.ref === tab.ref).sort((a, b) => (b.started_ms ?? 0) - (a.started_ms ?? 0))[0]
  const tasks = [...indexRows(s.model).values()].filter(r => String(r.key).startsWith('task:') && !r.inbox_id)
  return html`<section class="topic-none"><p class="muted">${t.noFile}</p>
    ${sess ? html`<select class="input input-sm" aria-label=${t.pickFile} onChange=${e => { const slug = e.currentTarget.value; if (slug) c.act('session_link', { session: sess.sid, slug }) }}>
      <option value="">${t.pickFile}</option>
      ${tasks.map(k => html`<option key=${k.key} value=${k.key.slice(5)}>${short(k.title, 48)}</option>`)}</select>` : null}</section>`
}

/** Zum Thema: the reading of the open chat and its file. It follows the chat, or holds on to one */
export function TopicPane({ p, i, s, c, tab, split }) {
  const t = T().fields
  const slug = tab ? taskOfTab(s, tab) : null
  const reads = tab && guideOf(s, tab).status !== 'off'
  const give = next => c.termKeys(tab.ref, [{ text: next }])
  return html`<section class="panel chat-main rooms-main field-topic" aria-label=${t.topic}>
    <header class="tabview-head"><${FieldGrip} i=${i} on=${split} /><strong class="field-topic-title">${t.topic}</strong>
      <span class="muted small field-of">${tab?.name ?? ''}</span>
      <button type="button" class=${`field-follow${p.follow ? ' is-on' : ''}`} title=${p.follow ? t.followTitle : t.heldTitle}
        onClick=${() => c.fieldHold(i, tab?.ref ?? null)}>${p.follow ? t.follow : t.held}</button>
      <${FieldClose} i=${i} c=${c} on=${split} /></header>
    <div class="topic-body">
      ${!tab ? html`<p class="muted">${t.noChat}</p>` : null}
      ${reads ? html`<h3 class="label-caps topic-cap"><${Icon} name="spark" size=${12} /> ${t.reading}</h3><${GuideTree} tab=${tab} s=${s} c=${c} bare />` : null}
      ${tab ? html`<h3 class="label-caps topic-cap">${t.file}</h3>` : null}
      ${slug ? html`<${OpenFile} key=${slug} open=${slug} s=${s} c=${c} stepActs=${next => html`<${Btn} size="xs" variant="secondary" onClick=${() => give(next)}>${t.toChat}<//>`} />` : tab ? html`<${LinkFile} s=${s} c=${c} tab=${tab} />` : null}
    </div>
  </section>`
}

/** What a tab waiting for you asks, at the edge of its terminal: the question in a line and the answers as buttons.
 *  A step that sends words shows them first, to read and edit; a dialog's number presses at once, one that reaches
 *  beyond the session asks first. Selbst antworten hands the keyboard to the terminal, Ganze Lage opens Zum Thema */
export function AnswerBar({ tab, s, c, onOwn, onTopic }) {
  const t = T()
  const g = t.guide
  const { status, entry } = guideOf(s, tab)
  const [chosen, setChosen] = useState(null)
  const [draft, setDraft] = useState('')
  const [note, setNote] = useState(null)
  const choices = status === 'fresh' ? guideChoices(tab, entry, s) : []
  const busy = !!s.ui?.busy?.[tab.ref]
  const question = (status === 'fresh' && entry.waits_for) || tab.ask?.text || previewText(tab.last) || t.reply.unreadable
  const go = async (ch, words) => {
    setNote(null)
    const { verb, args } = ch.n == null ? replySend(tab, words) : ch
    const r = await c.reply(verb, args)
    if (r?.refused) { setNote(errorText(r.error, t)); return }
    if (!r?.ok) { if (r?.note) setNote(r.note); return }
    c.markAnswered?.(tab.ref, answerMark(tab, short(ch.n == null ? words : ch.label, 40), Date.now()))
    setChosen(null)
  }
  const pick = ch => {
    if (ch.n != null && !ch.risky) { go(ch); return }
    setChosen(chosen?.id === ch.id ? null : ch)
    setDraft(ch.send ?? '')
  }
  return html`<div class=${`answer${tab.state === 'needs-you' ? ' is-asking' : ''}`} role="group" aria-label=${t.reply.asks}>
    <p class="answer-q" title=${entry?.where || question}><${Icon} name="spark" size=${12} />
      <strong>${tab.state === 'needs-you' ? t.fields.asks : t.fields.waitsFor}</strong> <span>${question}</span>
      ${status !== 'off' ? html`<button type="button" class="btn-link small" onClick=${onTopic}>${t.fields.wholeReading}</button>` : null}</p>
    ${choices.length && tab.ask?.draft ? html`<p class="reply-draft muted small">${t.reply.draft}</p>` : null}
    <div class="answer-opts">
      ${choices.length ? choices.map(ch => html`<button type="button" key=${ch.id} class=${`answer-opt${ch.picked ? ' is-picked' : ''}${chosen?.id === ch.id ? ' is-on' : ''}`}
        disabled=${busy} title=${ch.why || ch.label} aria-pressed=${String(chosen?.id === ch.id)} onClick=${() => pick(ch)}>${ch.label}</button>`)
        : html`<${TabReply} tab=${tab} s=${s} c=${c} bare />`}
      <button type="button" class="answer-opt is-quiet" onClick=${onOwn}>${g.own}</button>
    </div>
    ${chosen ? html`<div class="answer-compose">
      ${chosen.risky ? html`<p class="small"><${StateLine} token="warning" word=${g.riskyNote} /></p>` : null}
      ${chosen.n != null ? html`<p class="small">${g.presses(chosen.n)}: <strong>${chosen.label}</strong></p>`
        : html`<textarea class="input" rows="2" maxlength=${TAB_MSG_MAX} aria-label=${g.composeLabel} value=${draft} onInput=${e => setDraft(e.currentTarget.value)}></textarea>`}
      <span class="btn-row"><${Btn} size="xs" variant="primary" icon="send" busy=${busy} disabled=${chosen.n == null && !draft.trim()} onClick=${() => go(chosen, draft.trim())}>${chosen.n != null ? g.press : g.send}<//>
        <${Btn} size="xs" variant="ghost" onClick=${() => setChosen(null)}>${g.cancel}<//></span>
    </div>` : null}
    ${note ? html`<p class="reply-note small" role="status">${note}</p>` : null}
  </div>`
}
