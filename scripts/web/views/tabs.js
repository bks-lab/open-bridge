// SPDX-License-Identifier: MIT
// The cockpit, the agent tabs: the column, its cards, one tab large.
// The rules every component keeps stand at the head of components.js.

import { html, useEffect, useLayoutEffect, useMemo, useRef, useState } from '../vendor/htm-preact-3.1.1.module.js'
import { duration, groupTabs, stateToken, canTab, noTabDriver, screenLines, screenPoll, previewText, railOn, SCREEN_FAST_MS, SCREEN_FAST_FOR_MS, SCREEN_POLL_MS, tabStateKey, termEcho, termKey, termParts, termPaste, termQueue } from '../logic.js'
import { T } from '../text.js'
import { SendBox } from './chat.js'
import { TabControls } from './detail.js'
import { StartControl } from './header.js'
import { ASK_MAX, TAB_MSG_MAX } from './nav.js'
import { useFocusOnOpen } from './overlays.js'
import { Btn, Chip, Empty, StateLine } from './parts.js'
import { GuideLine, GuideTree } from './guide.js'
import { TabReply } from './reply.js'

const TERM_BATCH = 64            // the steps of one call (actions_base.py TERM_STEPS_MAX)
const TERM_PASTE_MAX = 32000

// ---------------------------------------------------------------- agent tabs

/** One agent tab large in the middle, like the Claude Code CLI: its terminal read while the page is
 *  visible (useTabScreen), the end in view unless you scrolled up, and below it the message box and the
 *  buttons the tab's state allows. Read through the terminal driver (screen); sending goes through tab_send, and the
 *  keyboard of the screen through tab_keys (TermScreen) */
/** The terminal of one tab, read while the page is visible: every 1.5 s right after a change, slower up
 *  to every 5 s while it stays the same. The server answers unchanged to the hash held, and only a
 *  changed screen is stored, so an idle tab neither moves its text nor renders the view again: { screen, err } */
export function useTabScreen(c, ref) {
  const [screen, setScreen] = useState(null)
  const [err, setErr] = useState(null)
  const poke = useRef(() => {})
  useEffect(() => {
    let alive = true
    let timer = null
    let held = null
    let delay = SCREEN_POLL_MS
    let fastUntil = 0
    let reading = false
    setScreen(null)
    setErr(null)
    if (!ref) return undefined
    const pull = async () => {
      const fast = Date.now() < fastUntil
      if (document.visibilityState === 'visible') {
        reading = true
        const res = await c.tabScreen(ref, held?.hash, fast)
        reading = false
        if (!alive) return
        if (res.ok) {
          const next = screenPoll(held, res.data, delay)
          delay = next.delay
          if (next.screen !== held) { held = next.screen; setScreen(held) }
          setErr(null)
        } else setErr(res.error?.message || res.error?.code || '?')
      }
      if (alive) timer = setTimeout(pull, Date.now() < fastUntil ? SCREEN_FAST_MS : delay)
    }
    // a key went in: read now and quickly for a moment, one read at a time
    poke.current = () => {
      fastUntil = Date.now() + SCREEN_FAST_FOR_MS
      if (!reading) { clearTimeout(timer); pull() }
    }
    pull()
    return () => { alive = false; clearTimeout(timer) }
  }, [ref])
  return { screen, err, poke: () => poke.current() }
}

/** A tab's terminal as lines, coloured by kind and tone (logic.js screenLines, termParts). While it is live the cursor
 *  stands in the prompt when one is near the end, else behind the last line; solid and blinking while you type, an
 *  outline otherwise, as in a terminal without focus. `echo` is what you typed and the screen does not show yet */
export function TermLines({ text, live = false, typing = false, echo = '', empty }) {
  const lines = useMemo(() => screenLines(text), [text])
  if (!lines.length) return html`<p class="muted">${empty}</p>`
  const prompt = lines.findLastIndex(l => l.kind === 'user')
  const cursor = !live ? -1 : prompt >= 0 && prompt >= lines.length - 5 ? prompt : lines.length - 1
  const atCursor = html`${echo ? html`<span class="term-echo">${echo}</span>` : null}<span class=${`term-cursor${typing ? ' is-on' : ''}`} aria-hidden="true"></span>`
  return lines.map((l, i) => html`<div key=${i} class=${`term-line term-${l.kind}${l.tone ? ` term-${l.tone}` : ''}`}>${l.text ? termParts(l.text).map((p, k) => p.c ? html`<span key=${k} class=${`term-${p.c}`}>${p.t}</span>` : p.t) : ' '}${i === cursor ? atCursor : null}</div>`)
}

/** The screen of a tab as a terminal: read as useTabScreen reads it, the end in view unless you scrolled up. With
 *  `canType` it takes the keyboard: a click on it (no selection made) puts the focus in a hidden box, and from there
 *  a key goes straight to the tab, in order, one batch at a time, what piles up meanwhile in the next (tab_keys).
 *  The box, and not the screen itself, so a dead key, an Option character and a paste arrive as what they make. Cmd
 *  stays the Mac's, a click beside it or Ctrl+] gives the keyboard back to the page */
export function TermScreen({ tabRef, screen, live = false, empty, canType = false, c, poke, focusRef = null }) {
  const t = T()
  const body = useRef(null)
  const stick = useRef(true)
  const field = useRef(null)
  const queue = useRef({ steps: [], busy: false, composing: false })
  const [echo, setEcho] = useState('')
  const [typing, setTyping] = useState(false)
  useLayoutEffect(() => {
    const el = body.current
    if (el && stick.current) el.scrollTop = el.scrollHeight
  }, [screen?.text, echo])
  // the screen has what was typed: the echo goes, unless more is on its way
  useEffect(() => {
    const q = queue.current
    if (!q.busy && !q.steps.length) setEcho('')
  }, [screen?.hash])
  const flush = async () => {
    const q = queue.current
    if (q.busy || !q.steps.length) return
    q.busy = true
    const steps = q.steps.slice(0, TERM_BATCH)
    q.steps = q.steps.slice(TERM_BATCH)
    const sent = await c.termKeys(tabRef, steps)
    q.busy = false
    poke?.()
    if (sent === false) {
      q.steps = []
      setEcho('')
    } else flush()
  }
  const press = step => {
    const q = queue.current
    q.steps = termQueue(q.steps, step)
    stick.current = true
    setEcho(e => termEcho(e, step))
    flush()
  }
  const take = el => {
    const text = el.value.replace(/[\x00-\x1f\x7f]/g, '')
    el.value = ''
    if (text) press({ text })
  }
  const onKey = e => {
    if (e.ctrlKey && e.key === ']') {
      e.preventDefault()
      body.current?.focus()
      return
    }
    const step = termKey(e)
    if (!step) return
    e.preventDefault()
    e.stopPropagation()
    press(step)
  }
  const onPaste = e => {
    e.preventDefault()
    const text = termPaste(e.clipboardData?.getData('text'))
    if (text) press({ paste: text.slice(0, TERM_PASTE_MAX) })
  }
  const toField = () => field.current?.focus({ preventScroll: true })
  if (focusRef) focusRef.current = toField
  // a drag selects, to copy: only a plain click starts typing
  const onMouseUp = () => { if (window.getSelection?.()?.isCollapsed !== false) toField() }
  // the focus on the screen itself (after a selection, after Ctrl+]): a letter starts typing, the arrows still scroll
  const onBodyKey = e => { if (e.target === e.currentTarget && e.key.length === 1 && !e.metaKey && !e.ctrlKey) toField() }
  return html`<div class=${`tabview-body${typing ? ' is-typing' : ''}`} ref=${body} tabindex="0" role="log" aria-label=${t.tabViewLog}
    onMouseUp=${canType ? onMouseUp : undefined} onKeyDown=${canType ? onBodyKey : undefined}
    onScroll=${e => { const el = e.currentTarget; stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40 }}>
    <${TermLines} text=${screen?.text} live=${live} typing=${typing} echo=${echo} empty=${empty} />
    ${canType ? html`<textarea class="term-input" ref=${field} rows="1" aria-label=${t.termInput} autocomplete="off" autocapitalize="off" spellcheck="false"
      onKeyDown=${onKey} onInput=${e => { if (!e.isComposing && !queue.current.composing) take(e.currentTarget) }} onPaste=${onPaste}
      onCompositionStart=${() => { queue.current.composing = true }}
      onCompositionEnd=${e => { queue.current.composing = false; take(e.currentTarget) }}
      onFocus=${() => setTyping(true)} onBlur=${() => setTyping(false)}></textarea>
    <p class="term-status small muted">${typing ? t.termTyping : t.termClick}</p>` : null}
  </div>`
}

export function TabView({ s, c }) {
  const t = T()
  const claude = s.ui.tabView === '@control'
  const ref = claude ? s.tabs?.control?.ref ?? null : s.ui.tabView
  const tab = (s.tabs?.tabs ?? []).find(x => x.ref === ref) ?? null
  const isControl = claude || !!tab?.is_control
  const relay = s.relay ?? {}
  const fb = s.ui.askFallback
  const { screen, err, poke } = useTabScreen(c, ref)
  const [text, setText] = useState('')
  const dialog = useFocusOnOpen(true)
  const busy = !!s.ui.busy[ref]
  const state = tab?.state ?? screen?.state
  const send = async () => {
    const v = text.trim()
    if (!v) return
    // to the control session through the relay when it is on (it waits for the end of a turn), else typed in
    const r = isControl && relay.online ? await c.askControl('free', { text: v }, v)
      : ref ? await c.act('tab_send', { tab_ref: ref, text: v }) : false
    if (r) setText('')
  }
  return html`<div class="overlay overlay-center" onClick=${e => { if (e.target === e.currentTarget) c.closeTabView() }}>
    <div class="dialog tabview term" role="dialog" aria-modal="true" aria-labelledby="tabview-title" ref=${dialog}>
      <header class="tabview-head">
        ${state ? html`<${StateLine} token=${stateToken(state)} strong=${state === 'needs-you'} word=${t.state[state] ?? state} />` : null}
        <h2 class="sec-title tabview-title" id="tabview-title">${isControl ? t.controlSession : tab?.name ?? screen?.name ?? ref}</h2>
        <span class="muted small">${tab?.workspace ?? screen?.workspace ?? ''}</span>
        <span class=${`tabview-live muted small${screen && !err ? ' is-live' : ''}`} aria-live="off">${err ? html`<${StateLine} token="danger" word=${t.tabViewFailed(err)} />`
          : screen ? t.tabViewLive : t.loading}</span>
        ${ref && canTab(s, 'focus') ? html`<${Btn} size="xs" variant="ghost" busy=${busy} onClick=${() => c.act('tab_jump', { tab_ref: ref })}>${t.btnToTab}<//>` : null}
        <${Btn} variant="ghost" size="xs" icon="close" label=${t.close} onClick=${c.closeTabView} />
      </header>
      ${claude && !ref ? html`<div class="tabview-off">
        <${StateLine} token="warning" strong word=${t.relayReason[relay.reason] ?? t.relay.offline} />
        <p class="muted small">${t.claudeNoSession}</p>
        <div class="btn-row"><${StartControl} s=${s} c=${c} size="sm" /></div>
      </div>` : null}
      ${fb ? html`<div class="callout ask-fallback" role="region" aria-label=${t.askOfflineTitle}>
        <strong>${t.askOfflineTitle}</strong>
        <div class="btn-row">
          <${Btn} size="xs" icon="copy" onClick=${() => c.copy(fb.text || fb.record?.preview || '')}>${t.askCopy}<//>
          ${fb.fallback?.available && fb.record ? html`<${Btn} size="xs" variant="primary"
            onClick=${() => c.act('ask_via_tab', { relay_id: fb.record.id })}>${t.askViaTab}<//>` : null}
          <${Btn} size="xs" variant="ghost" icon="close" label=${t.close} onClick=${() => c.setAskFallback(null)} />
        </div>
      </div>` : null}
      ${!claude || ref ? html`<${TermScreen} tabRef=${ref} screen=${screen} live=${!!screen && !err} empty=${screen ? t.tabViewEmpty : t.loading}
        canType=${canTab(s, 'keys')} c=${c} poke=${poke} />` : html`<div></div>`}
      <footer class="tabview-foot">
        ${tab ? html`<${TabReply} tab=${tab} s=${s} c=${c} bare />` : null}
        <${SendBox} id="tabview-input" label=${t.msgPlaceholder} value=${text} setValue=${setText} onSend=${send} busy=${busy}
          max=${isControl ? ASK_MAX : TAB_MSG_MAX} placeholder=${isControl ? t.askPlaceholder : t.tabViewPlaceholder} />
      </footer>
    </div>
  </div>`
}

/** A session tab as a card. In the agent tab column it is slim: state, name and its one next step; a
 *  click on more opens the preview and every control */
export function TabCard({ tab, s, c, byKey, slim = false }) {
  const t = T()
  const [open, setOpen] = useState(false)
  const full = !slim || open
  const rowKey = tab.slug ? `task:${tab.slug}` : null
  const hasRow = rowKey && byKey.has(rowKey)
  const age = duration(s.now - (tab.since_ms || s.now))
  const ageText = tab.long === 'waiting' ? t.waitingFor(age) : tab.long === 'running' ? t.runningFor(age) : t.sinceFor(age)
  const shell = tab.state === 'shell'
  return html`<article class=${`tabcard st-${tab.state}${shell ? ' is-shell' : ''}${tab.is_control ? ' is-control' : ''}${full ? '' : ' is-slim'}`}>
    <header class="tabcard-head">
      ${tab.is_control
        ? html`<button type="button" class="btn-link" onClick=${c.openClaude}><${StateLine} token="on-surface-muted" word=${t.controlSession} /></button>`
        : html`<${StateLine} token=${stateToken(tabStateKey(tab))} strong=${tab.state === 'needs-you'} word=${t.state[tabStateKey(tab)] ?? tab.state} />`}
      <span class="tabcard-age mono">${ageText}</span>
      ${tab.long ? html`<span class="chip chip-warn-outline">${t.tabLong}</span>` : null}
    </header>
    <h3 class="tabcard-name">${hasRow
      ? html`<button type="button" class="btn-link" title=${t.showTab(tab.name)} onClick=${() => c.select(rowKey)}>${tab.name}</button>`
      : html`<button type="button" class="btn-link" title=${t.btnTabView} onClick=${() => c.openTabView(tab.ref)}>${tab.name}</button>`}</h3>
    ${full && previewText(tab.last) ? html`<p class="tab-last clamp2" title=${tab.last}>${previewText(tab.last)}</p>` : null}
    ${full ? html`<${GuideTree} tab=${tab} s=${s} c=${c} compact />` : html`<${GuideLine} tab=${tab} s=${s} />`}
    ${tab.settled ? html`<p class="small"><${StateLine} token="success" word=${t.tabSettled[tab.settled] ?? tab.settled} /></p>` : null}
    ${full && (tab.slug || tab.team || tab.role || tab.filed_by) ? html`<div class="chips">
      ${tab.slug ? html`<span class="chip"><span class="muted">${t.tabChips.task}</span> ${tab.slug}</span>` : null}
      ${tab.team ? html`<span class="chip"><span class="muted">${t.tabChips.team}</span> ${tab.team}</span>` : null}
      ${tab.role ? html`<span class="chip"><span class="muted">${t.tabChips.role}</span> ${tab.role}</span>` : null}
      ${tab.filed_by ? html`<${Chip} token="success">${t.resultFiled}<//>` : null}
    </div>` : null}
    ${full ? html`<${TabControls} tab=${tab} s=${s} c=${c} />` : html`<div class="btn-row"><${TabControls} tab=${tab} s=${s} c=${c} slim /></div>`}
    ${slim ? html`<button type="button" class="btn-link tabcard-more" aria-expanded=${String(open)}
      onClick=${() => setOpen(!open)}>${open ? t.cardLess : t.cardMore}</button>` : null}
  </article>`
}

function SnapshotPanel({ s, c }) {
  const t = T()
  if (!s.cmux?.ok) return null
  return html`<section class="snap" aria-labelledby="snap-title">
    <h3 class="label-caps" id="snap-title">${t.snapshotTitle}</h3>
    <div class="btn-row">
      <${Btn} size="xs" busy=${!!s.ui.busy.snapshot} onClick=${() => c.snapshot(false)}>${t.btnSave}<//>
      <${Btn} size="xs" variant="ghost" busy=${!!s.ui.busy.snapshot_list} onClick=${() => c.snapshot(true)}>${t.btnList}<//>
    </div>
    ${s.ui.snapshotText ? html`<p class="pre small">${s.ui.snapshotText}</p>` : null}
  </section>`
}

/** Why the tabs may be missing or stale: no terminal driver lists them, or the last read of their list failed
 *  (since when, why). The tab column and the head of the Chat show it (round 6) */
export function TabWarnings({ s }) {
  const t = T()
  return html`${noTabDriver(s) ? html`<p class="banner"><${StateLine} token="warning" word=${t.noDriver} /></p>` : null}
    ${s.tabs?.error ? html`<p class="banner"><${StateLine} token="danger" strong word=${t.tabsStale(s.tabs.error.since, s.tabs.error.message)} /></p>` : null}`
}

export function TabsColumn({ s, c, byKey, inDrawer }) {
  const t = T()
  const tabs = s.tabs?.tabs ?? []
  const control = tabs.find(x => x.is_control)
  const groups = groupTabs(tabs)
  const waiting = tabs.filter(x => x.waiting && !x.is_control).length
  const working = tabs.filter(x => x.state === 'working' && !x.is_control).length
  return html`<div class=${`col col-tabs${inDrawer ? ' in-drawer' : ''}`} id="tabs-column" tabindex="-1" aria-labelledby="tabs-title">
    <div class="panel panel-pad tabs-panel">
      <header class="tabs-head">
        <h2 class="sec-title" id="tabs-title">${t.tabsTitle} <span class="sec-count mono">${tabs.filter(x => !x.is_control).length}</span></h2>
        <span class="muted small">${waiting ? t.waitCount(waiting) : ''}${waiting && working ? ' · ' : ''}${working ? t.workingCount(working) : ''}</span>
        <span class="tabs-head-acts">
          ${inDrawer && s.ui.railHidden && s.layout === 'wide' && railOn(s, false)
            ? html`<${Btn} variant="ghost" size="xs" title=${t.tabsPinTitle} onClick=${() => c.toggleRail()}>${t.tabsPin}<//>` : null}
          ${inDrawer ? html`<${Btn} variant="ghost" size="xs" icon="close" label=${t.close} onClick=${() => c.setDrawer(null)} />`
            : s.layout === 'wide' ? html`<${Btn} variant="ghost" size="xs" title=${t.tabsHideTitle} onClick=${() => c.toggleRail()}>${t.tabsHide}<//>` : null}
        </span>
      </header>
      <${TabWarnings} s=${s} />
      ${control ? html`<${TabCard} tab=${control} s=${s} c=${c} byKey=${byKey} slim />` : null}
      ${groups.length ? groups.map(g => html`<section class="tabgroup" key=${g.workspace}>
        <h3 class="mono-label">${g.workspace || '·'}</h3>
        <div class="tabgrid">${g.tabs.map(tab => html`<${TabCard} key=${tab.ref} tab=${tab} s=${s} c=${c} byKey=${byKey} slim />`)}</div>
      </section>`) : html`<${Empty}>${t.tabsEmpty}<//>`}
      <${SnapshotPanel} s=${s} c=${c} />
    </div>
  </div>`
}
