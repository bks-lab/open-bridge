// SPDX-License-Identifier: MIT
// The cockpit, what a waiting tab asks and the answers to it from the page: the question as the tab
// poll read it off the tab's screen (asks.py), and one button per option of a dialog, yes and no for a
// yes or no question, go on and a text field. Every answer names the question it answers, the tab's name
// and its state, and the server sends nothing once the tab moved on (actions.py guard_fresh).
// The rules every component keeps stand at the head of components.js.

import { html, useEffect, useRef, useState } from '../vendor/htm-preact-3.1.1.module.js'
import { errorText, previewText, replyOptions, replySend, short } from '../logic.js'
import { T } from '../text.js'
import { TAB_MSG_MAX } from './nav.js'
import { Btn } from './parts.js'

/** The question of a tab in at most three lines; the tab's last line when none was read, and a word
 *  saying so when there is neither and the tab waits (one that runs for an hour asks nothing) */
export function AskLine({ tab }) {
  const t = T()
  const text = tab?.ask?.text || previewText(tab?.last)
  if (!text && tab?.state !== 'needs-you' && tab?.state !== 'waiting') return null
  return html`<p class=${`reply-ask clamp3${text ? '' : ' muted'}`} title=${text || undefined}>${text || t.reply.unreadable}</p>`
}

/** The answers the page offers `tab` (logic.js replyOptions). `compact` (the sidebar) keeps the text field
 *  behind a button; `bare` (the tab's own view, which has its message box and its way to the tab) leaves
 *  out the field and the open-tab button. An answer that went out is kept in ui.answered; a refusal
 *  (the tab moved on, a draft in it) shows its note here and keeps what was typed */
export function TabReply({ tab, s, c, compact = false, bare = false }) {
  const t = T()
  const [open, setOpen] = useState(!compact)
  const [text, setText] = useState('')
  const [note, setNote] = useState(null)
  const field = useRef(null)
  const focus = useRef(false)
  useEffect(() => {
    if (focus.current && field.current) { focus.current = false; field.current.focus?.() }
  })
  if (!tab) return null
  const { buttons, textBox } = replyOptions(tab, s, t)
  const shown = bare ? buttons.filter(b => b.verb !== 'tab_jump') : buttons
  const withText = textBox && !bare
  if (!shown.length && !withText) return null
  const busy = !!s.ui?.busy?.[tab.ref]
  const id = `reply-${tab.ref}`
  const answer = async (verb, args, q) => {
    setNote(null)
    const r = await c.reply(verb, args)
    if (r?.refused) { setNote(errorText(r.error, t)); return false }
    if (r && verb !== 'tab_jump') c.markAnswered?.(tab.ref, { hash: tab.ask?.hash ?? null, q })
    return !!r
  }
  const send = async () => {
    const v = text.trim()
    if (!v) return
    const { verb, args } = replySend(tab, v)
    if (await answer(verb, args, short(v, 40))) setText('')
  }
  const opener = withText && !open ? html`<button type="button" class="btn btn-ghost btn-xs" aria-expanded="false" aria-controls=${id}
    onClick=${() => { focus.current = true; setOpen(true) }}><span class="btn-label">${t.reply.placeholder}</span></button>` : null
  return html`<div class="reply">
    ${tab.ask?.draft ? html`<p class="reply-draft muted small">${t.reply.draft}</p>` : null}
    ${shown.length || opener ? html`<div class="btn-row reply-btns">
      ${shown.map((b, i) => html`<${Btn} key=${b.id} size="xs" variant=${b.verb === 'tab_jump' ? 'ghost' : i === 0 ? 'primary' : 'secondary'}
        busy=${busy} title=${b.label} onClick=${() => answer(b.verb, b.args, b.label)}>${b.label}<//>`)}
      ${opener}
    </div>` : null}
    ${withText && open ? html`<div class="field-row reply-field">
      <label class="sr-only" for=${id}>${t.reply.placeholder}</label>
      <textarea id=${id} class="input" rows="1" maxlength=${TAB_MSG_MAX} placeholder=${t.reply.placeholder} value=${text} ref=${field}
        onInput=${e => setText(e.currentTarget.value)}
        onKeyDown=${e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }}></textarea>
      <${Btn} size="xs" variant="primary" icon="send" busy=${busy} disabled=${!text.trim()} onClick=${send}>${t.reply.send}<//>
    </div>` : null}
    ${note ? html`<p class="reply-note small" role="status">${note}</p>` : null}
  </div>`
}
