// SPDX-License-Identifier: MIT
// The cockpit, the chat: the quick chat window and its page.
// The rules every component keeps stand at the head of components.js.

import { html, useEffect, useLayoutEffect, useRef, useState } from '../vendor/htm-preact-3.1.1.module.js'
import { short, canTab, centsText, chatStamp, handoffStatus, listedChats, routeOf } from '../logic.js'
import { T, language } from '../text.js'
import { Segmented } from './detail.js'
import { LaunchPick } from './launch.js'
import { ASK_MAX } from './nav.js'
import { useFocusOnOpen } from './overlays.js'
import { Btn, Dot, StateLine, useClock } from './parts.js'
import { Prose } from './prose.js'

// ---------------------------------------------------------------- the answer while it is written

/** The live text of every answer being written, kept apart from the page's store: a piece of an answer
 *  re-renders only the components that show it (useQuickLive), never the whole page. app.js feeds it
 *  from the `quick_live` events and the state a page connects with (logic.js applyQuickLive) */
export const quickLive = (() => {
  let map = {}
  const subs = new Set()
  return {
    get: () => map,
    set(next) {
      if (next === map) return
      map = next
      for (const fn of subs) fn(map)
    },
    subscribe(fn) {
      subs.add(fn)
      return () => subs.delete(fn)
    },
  }
})()

/** The live text and doing of the answer `id` is writing, or null; re-renders when that one changes */
export function useQuickLive(id) {
  const [, tick] = useState(0)
  const live = id ? quickLive.get()[id] ?? null : null
  useLayoutEffect(() => {
    let last = live
    const check = m => { const now = id ? m[id] ?? null : null; if (now !== last) { last = now; tick(n => n + 1) } }
    const off = quickLive.subscribe(check)
    check(quickLive.get())   // what came between the render and now
    return off
  }, [id])
  return live
}

// ---------------------------------------------------------------- the chat

/** Cost of a turn in cents, in the page language: 0.0021 $ -> "0,21 ct" */
function costText(usd, lang) {
  return usd == null ? '' : `${centsText(usd * 100, lang)} ct`
}

/** Three dots that rise in turn while Claude thinks (a spring per dot, offset by a third) */
export function Thinking({ label }) {
  const T0 = useClock(true)
  return html`<span class="thinking" aria-live="polite"><span class="thinking-dots" aria-hidden="true">${[0, 1, 2].map(i => {
    const k = (Math.sin((T0 * 2 * Math.PI) / 1.1 - i * 0.9) + 1) / 2
    return html`<span key=${i} style=${{ transform: `translateY(${(-4 * k).toFixed(2)}px)`, opacity: (0.35 + 0.65 * k).toFixed(3) }}></span>`
  })}</span><span class="muted small">${label}</span></span>`
}

/** The message box of a chat or a tab: Enter sends, Shift+Enter breaks the line */
/** A text box with its send button. `alt` adds a second way to send ({ label, title, onSend, ready, busy }):
 *  Enter takes the first, Cmd or Ctrl Enter the second */
export function SendBox({ id, label, value, setValue, onSend, max, placeholder, busy, disabled, sendLabel, autofocus = true, alt = null }) {
  const t = T()
  return html`<div class="field-row tabview-send">
    <label class="sr-only" for=${id}>${label}</label>
    <textarea id=${id} class="input" rows="2" maxlength=${max} placeholder=${placeholder} value=${value} data-autofocus=${autofocus ? '' : undefined}
      onInput=${e => setValue(e.currentTarget.value)}
      onKeyDown=${e => {
        if (e.key !== 'Enter' || e.shiftKey) return
        e.preventDefault()
        if (alt && (e.metaKey || e.ctrlKey)) { if (alt.ready) alt.onSend() } else onSend()
      }}></textarea>
    <span class="send-btns">
      <${Btn} size="sm" variant=${alt ? 'secondary' : 'primary'} icon="send" busy=${busy} disabled=${!value.trim() || disabled} onClick=${onSend}>${sendLabel ?? t.btnSend}<//>
      ${alt ? html`<${Btn} size="sm" variant="primary" icon="tabs" busy=${alt.busy} disabled=${!alt.ready} title=${alt.title} onClick=${alt.onSend}>${alt.label}<//>` : null}
    </span>
  </div>`
}

/** The turns of one chat; the turn being answered shows its text while it is written and what it reads */
export function ChatThread({ s, conv }) {
  const t = T()
  const lang = language()
  const live = useQuickLive(conv?.id)
  return conv.turns.map((x, i) => {
    const open = !x.a && !x.error && i === conv.turns.length - 1 && conv.running
    return html`<div class="qturn row-in" key=${i} style=${{ '--i': 0 }}>
      <div class="qq">${x.q}</div>
      ${x.a ? html`<${Prose} cls="qa" text=${x.a} />`
        : x.error ? html`<p><${StateLine} token="danger" word=${x.error === 'interrupted' ? t.quickInterrupted : t.quickFailed(x.error)} /></p>`
        : open && live?.text ? html`<${Prose} cls="qa is-live" text=${live.text}><span class="qcaret" aria-hidden="true"></span><//>` : null}
      ${open ? html`<${Thinking} label=${live?.doing ? t.quickReading(live.doing)
        : live?.text ? t.quickWriting : t.quickThinking(t.quickModel[x.model_asked] ?? x.model_asked)} />` : null}
      ${x.a ? html`<div class="qmeta mono small muted">${x.model ?? x.model_asked}${x.cost_usd != null ? ` · ${costText(x.cost_usd, lang)}` : ''}</div>` : null}
    </div>`
  })
}

/** The status line of a chat handed on (logic.js handoffStatus) with the one step it offers: try again, open
 *  the tab it arrived in, or type it into the waiting control tab */
function HandoffLine({ s, c, st, onRetry, relayId }) {
  const t = T()
  const word = st.word === 'inTab' ? t.handoff.inTab(st.tab) : t.handoff[st.word]
  const action = st.action === 'retry' && onRetry ? html`<button type="button" class="btn-link small" onClick=${onRetry}>${t.handoff.retry}</button>`
    : st.action === 'jump' && canTab(s, 'focus') ? html`<button type="button" class="btn-link small" onClick=${() => c.act('tab_jump', { tab_ref: st.ref })}>${t.handoff.jump}</button>`
    : st.action === 'ask_via_tab' && relayId ? html`<button type="button" class="btn-link small" onClick=${() => c.act('ask_via_tab', { relay_id: relayId })}>${t.handoff.askViaTab}</button>`
    : null
  return html`<p class="handoff-status small" role="status" data-status=${st.word}><${StateLine} token=${st.tone} word=${word} />${action ? ' ' : null}${action}</p>`
}

/** Hand on, the cost so far, and the box for the next question (a reply goes on in the open chat). One input:
 *  the chip under the field says where Enter goes (logic.js routeOf: a read-only answer here, or an agent tab),
 *  a click on it switches until the field is empty again. Cmd Enter starts a tab at once. Once handed on, the
 *  chip gives way to the status line: where it went and how that went. No countdown, no timer */
export function ChatFoot({ s, c, conv, autofocus }) {
  const t = T()
  const lang = language()
  const [text, setTextRaw] = useState('')
  // the route picked by hand on the chip ('quick' or 'tab'), held until the field is empty: never a flip of
  // the guess, which typing on may turn around (a trailing question mark) and so invert the choice
  const [pinned, setPinned] = useState(null)
  const setText = v => { setTextRaw(v); if (!v.trim()) setPinned(null) }
  const model = s.ui.quickModel ?? s.quick?.default ?? 'haiku'
  const last = conv?.turns?.[conv.turns.length - 1]
  const total = conv ? conv.turns.reduce((n, x) => n + (x.cost_usd ?? 0), 0) : 0
  const costKnown = !conv || conv.turns.every(x => !x.a || x.cost_usd != null)
  const asked = last?.model_asked
  const guess = routeOf(text)
  const route = pinned ? { ...guess, to: pinned, by: 'flipped' } : guess
  // where the last handoff went: the chat's own record, or for a new problem the page's record of its start
  const handed = conv ? conv.handed ?? null : (s.ui.sent ?? []).at(-1) ?? null
  const status = handoffStatus(handed, s.relay?.records, s.tabs?.tabs)
  const starting = status?.word === 'starting'
  const answered = !!(conv && last?.a && !conv.running)
  // the second way: a real Claude session in a cmux tab, which may act. A new problem opens one at once;
  // an open chat goes on there with what was said so far, and the text in the box as the order on top
  const toTab = async (v, routed) => {
    if (starting) return null
    if (conv) return answered ? c.act('quick_handoff', { conv: conv.id, to: 'tab', ...(v ? { text: v } : {}) }) : null
    if (!v) return null
    const r = await c.act('chat_tab', { text: v, routed })
    if (r) c.noteSent({ to: 'tab', status: r.launch ?? 'failed', inbox_id: r.inbox_id ?? null, at_ms: Date.now(), text: v, routed })
    return r
  }
  const send = async () => {
    if (!text.trim() || conv?.running) return
    const v = route.text
    const done = route.to === 'tab' ? await toTab(v, route.by) : v ? await c.ask('free', { text: v }) : false
    if (done) setText('')
  }
  const solve = async () => {
    if (await toTab(routeOf(text).text, 'forced')) setText('')
  }
  // only a tab start is tried again from here: a chat never goes to the control session with one click
  const retry = handed?.to === 'tab' ? () => conv ? c.act('quick_handoff', { conv: conv.id, to: 'tab' }) : toTab(handed.text, handed.routed ?? 'default') : null
  const solveBusy = conv ? !!s.ui.busy[`quick:${conv.id}`] : !!s.ui.busy.chat_tab
  // no "to the control session" button: one stray click put a whole chat into the session at the
  // terminal (14.10.); a chat that needs acting goes to its own tab with "Get it done"
  return html`<footer class="tabview-foot">
    ${answered ? html`<div class="btn-row quick-next">
      <span class="muted small quick-total">${costKnown ? t.quickTotal(costText(total, lang)) : t.quickCostUnknown}${asked && asked !== model ? ` · ${t.quickSwitch(t.quickModel[model])}` : ''}</span>
    </div>` : null}
    <${SendBox} id="quick-input" label=${t.askLabel} value=${text} setValue=${setText} onSend=${send} max=${ASK_MAX} autofocus=${autofocus}
      placeholder=${conv ? t.quickReply : t.route.placeholder} busy=${route.to === 'tab' ? solveBusy : !!s.ui.busy['ask:free']}
      disabled=${!!conv?.running || (route.to === 'tab' && starting)} sendLabel=${route.to === 'tab' ? t.chatSolve : t.chatAsk}
      alt=${{ label: t.chatSolve, title: t.chatSolveTitle, onSend: solve, busy: solveBusy, ready: (conv ? answered : !!text.trim()) && !starting }} />
    ${text.trim() ? html`<p class="route-line small"><button type="button" class=${`chip route-chip is-${route.to}`} title=${t.route.flip}
        aria-label=${`${route.to === 'tab' ? t.route.toTab : t.route.toQuick}. ${t.route.flip}`} data-route=${route.to}
        onClick=${() => setPinned(route.to === 'tab' ? 'quick' : 'tab')}>${route.to === 'tab' ? t.route.toTab : t.route.toQuick}</button></p>`
      : status ? html`<${HandoffLine} s=${s} c=${c} st=${status} onRetry=${retry} relayId=${handed?.relay_id} />` : null}
    <${LaunchPick} s=${s} c=${c} />
    <p class="muted small chat-hint">${t.chatSolveHint}</p>
  </footer>`
}

function ModelPick({ s, c }) {
  const t = T()
  const model = s.ui.quickModel ?? s.quick?.default ?? 'haiku'
  return html`<${Segmented} label=${t.quickModelLabel} current=${model} values=${(s.quick?.models ?? ['haiku', 'sonnet', 'opus']).map(m => [m, t.quickModel[m] ?? m])}
      onPick=${m => c.setQuickModel(m)} /><span class="muted small">${t.quickModelHint[model] ?? ''}</span>
      ${s.ui.quickModel != null ? html`<button type="button" class="btn-link small" onClick=${() => c.setQuickModel(null)}>${t.quickServiceDefault}</button>` : null}`
}

/** The end of the thread stays in view while an answer grows */
export function useStickToEnd(conv, live) {
  const body = useRef(null)
  const last = conv?.turns?.[conv.turns.length - 1]
  useLayoutEffect(() => { if (body.current) body.current.scrollTop = body.current.scrollHeight },
    [conv?.id, conv?.turns?.length, last?.a, conv?.running, live?.text?.length, live?.doing])
  return body
}

/** The chat window: ask straight away (the box has the cursor), the answer shows while it is written,
 *  a reply goes on in the same session (Haiku unless picked), recent chats one click away, and "As a tab"
 *  keeps it on the Chat tab. When it turns into work it goes to an agent tab (Sonnet or more) or to the
 *  control session. Nothing here changes a file */
export function QuickChat({ s, c }) {
  const t = T()
  const q = s.quick ?? {}
  const convs = listedChats(q.convs, q.keep_hours, s.now)
  const conv = (q.convs ?? []).find(x => x.id === s.ui.quickConv) ?? null
  const body = useStickToEnd(conv, useQuickLive(conv?.id))
  const dialog = useFocusOnOpen(true)
  return html`<div class="overlay overlay-center" onClick=${e => { if (e.target === e.currentTarget) c.closeTabView() }}>
    <div class="dialog tabview quickchat" role="dialog" aria-modal="true" aria-labelledby="quick-title" ref=${dialog}>
      <header class="tabview-head">
        <h2 class="sec-title tabview-title" id="quick-title">${t.askTitle}</h2>
        <${ModelPick} s=${s} c=${c} />
        <span class="tabview-live"></span>
        <button type="button" class="btn-link small" title=${t.quickAsTabTitle} onClick=${c.chatAsTab}>${t.quickAsTab}</button>
        ${s.tabs?.control?.ref ? html`<button type="button" class="btn-link small" onClick=${c.openClaude}>${t.quickToControl}</button>` : null}
        <${Btn} variant="ghost" size="xs" icon="close" label=${t.close} onClick=${c.closeTabView} />
      </header>
      ${convs.length ? html`<nav class="quick-convs" aria-label=${t.quickChats}>
        <button type="button" class=${`chip quick-conv${!conv ? ' is-on' : ''}`} onClick=${c.newQuick}>+ ${t.quickNew}</button>
        ${convs.slice(0, 8).map(x => html`<button type="button" key=${x.id} class=${`chip quick-conv${x.id === conv?.id ? ' is-on' : ''}`}
          title=${x.turns[0]?.q} onClick=${() => c.pickQuick(x.id)}>${x.running ? html`<${Dot} token="info" pulse /> ` : null}${short(x.turns[0]?.q ?? '', 34)}</button>`)}
      </nav>` : null}
      <div class="tabview-body quick-body" ref=${body} tabindex="-1" role="log" aria-label=${t.quickHistory}>
        ${q.config_error || !q.available ? html`<p><${StateLine} token="warning" word=${q.config_error ?? t.quickUnavailable} /></p>` : null}
        ${!conv ? html`<div class="quick-empty"><p class="muted">${t.quickIntro}</p></div>` : html`<${ChatThread} s=${s} conv=${conv} />`}
      </div>
      <${ChatFoot} key=${conv?.id ?? 'new'} s=${s} c=${c} conv=${conv} autofocus />
    </div>
  </div>`
}

/** The Chat tab: every kept chat on the left (first question, when, model, cost), the open one on the
 *  right with its box ready; a chat goes on where it stopped, also after a restart of the dashboard */
export function ChatPage({ s, c }) {
  const t = T()
  const lang = language()
  const q = s.quick ?? {}
  const convs = listedChats(q.convs, q.keep_hours, s.now)
  const conv = (q.convs ?? []).find(x => x.id === s.ui.quickConv) ?? null
  const body = useStickToEnd(conv, useQuickLive(conv?.id))
  const [forgetArmed, setForgetArmed] = useState(null)
  useEffect(() => { document.getElementById('quick-input')?.focus() }, [conv?.id])
  return html`<div class="col col-page chatpage">
    <header class="page-head"><h2 class="detail-title">${t.chatTab}</h2><${ModelPick} s=${s} c=${c} />
      ${conv && !conv.running ? html`<button type="button" class=${`chip quick-conv agent-forget${forgetArmed === conv.id ? ' is-armed' : ''}`}
        title=${t.quickForgetHint} onBlur=${() => setForgetArmed(null)}
        onClick=${() => forgetArmed === conv.id ? c.quickForget(conv.id) : setForgetArmed(conv.id)}>${forgetArmed === conv.id ? t.quickForgetSure : t.quickForget}</button>` : null}</header>
    <div class="chat-grid">
      <nav class="panel chat-list" aria-label=${t.quickChats}>
        <button type="button" class=${`chat-item chat-new${!conv ? ' is-on' : ''}`} onClick=${c.newQuick}>+ ${t.quickNew}</button>
        ${convs.length ? convs.map(x => {
          const costKnown = x.turns.every(y => !y.a || y.cost_usd != null)
          const cost = costKnown ? x.turns.reduce((n, y) => n + (y.cost_usd ?? 0), 0) : null
          const lastTurn = x.turns[x.turns.length - 1]
          return html`<button type="button" key=${x.id} class=${`chat-item${x.id === conv?.id ? ' is-on' : ''}`} onClick=${() => c.pickQuick(x.id)}
            aria-current=${x.id === conv?.id ? 'true' : undefined}>
            <span class="chat-item-q">${x.running ? html`<${Dot} token="info" pulse /> ` : null}${short(x.turns[0]?.q ?? '', 70)}</span>
            <span class="chat-item-meta mono small muted">${[chatStamp(x.last_ms ?? x.started_ms, s.now, lang), t.quickTurns(x.turns.length),
              t.quickModel[lastTurn?.model_asked] ?? lastTurn?.model_asked, !costKnown ? t.quickCostUnknown : cost ? costText(cost, lang) : null].filter(Boolean).join(' · ')}</span>
          </button>`
        }) : html`<p class="muted small chat-none">${t.quickNoChats}</p>`}
      </nav>
      <section class="panel chat-main" aria-label=${t.askTitle}>
        <div class="tabview-body quick-body" ref=${body} tabindex="-1" role="log" aria-label=${t.quickHistory}>
          ${q.config_error || !q.available ? html`<p><${StateLine} token="warning" word=${q.config_error ?? t.quickUnavailable} /></p>` : null}
          ${!conv ? html`<div class="quick-empty"><p class="muted">${t.quickIntro}</p></div>` : html`<${ChatThread} s=${s} conv=${conv} />`}
        </div>
        <${ChatFoot} key=${conv?.id ?? 'new'} s=${s} c=${c} conv=${conv} autofocus=${false} />
      </section>
    </div>
  </div>`
}
