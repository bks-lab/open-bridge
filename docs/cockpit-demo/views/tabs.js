// SPDX-License-Identifier: MIT
// The cockpit, the agent tabs: the column, its cards, one tab large.
// The rules every component keeps stand at the head of components.js.

import { html, useEffect, useLayoutEffect, useRef, useState } from '../vendor/htm-preact-3.1.1.module.js'
import { duration, groupTabs, stateToken, canTab, screenLines, previewText } from '../logic.js'
import { T } from '../text.js'
import { SendBox } from './chat.js'
import { TabControls } from './detail.js'
import { StartControl } from './header.js'
import { ASK_MAX, TAB_MSG_MAX } from './nav.js'
import { useFocusOnOpen } from './overlays.js'
import { Btn, Chip, Empty, StateLine } from './parts.js'

// ---------------------------------------------------------------- agent tabs

/** One agent tab large in the middle, like the Claude Code CLI: its terminal read every 1.5 s while
 *  the page is visible, the end in view unless you scrolled up, and below it the message box and the
 *  buttons the tab's state allows. Read only through the terminal driver (screen); sending goes through tab_send */
export function TabView({ s, c }) {
  const t = T()
  const claude = s.ui.tabView === '@control'
  const ref = claude ? s.tabs?.control?.ref ?? null : s.ui.tabView
  const tab = (s.tabs?.tabs ?? []).find(x => x.ref === ref) ?? null
  const isControl = claude || !!tab?.is_control
  const relay = s.relay ?? {}
  const fb = s.ui.askFallback
  const [screen, setScreen] = useState(null)
  const [err, setErr] = useState(null)
  const [text, setText] = useState('')
  const body = useRef(null)
  const stick = useRef(true)
  const dialog = useFocusOnOpen(true)
  useEffect(() => {
    let alive = true
    let timer = null
    if (!ref) return undefined
    const pull = async () => {
      if (document.visibilityState === 'visible') {
        const res = await c.tabScreen(ref)
        if (!alive) return
        if (res.ok) { setScreen(res.data); setErr(null) } else setErr(res.error?.message || res.error?.code || '?')
      }
      if (alive) timer = setTimeout(pull, 1500)
    }
    pull()
    return () => { alive = false; clearTimeout(timer) }
  }, [ref])
  useLayoutEffect(() => {
    const el = body.current
    if (el && stick.current) el.scrollTop = el.scrollHeight
  }, [screen?.text])
  const onScroll = e => { const el = e.currentTarget; stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40 }
  const busy = !!s.ui.busy[ref]
  const state = tab?.state ?? screen?.state
  const send = async () => {
    const v = text.trim()
    if (!v) return
    // to the control session through the relay when it is on (it waits for the end of a turn), else typed in
    const r = isControl && relay.online ? await c.askControl('free', { text: v }, v)
      : ref ? await c.act('tab_send', { tab_ref: ref, text: v }) : false
    if (r) { setText(''); stick.current = true }
  }
  const lines = screenLines(screen?.text)
  return html`<div class="overlay overlay-center" onClick=${e => { if (e.target === e.currentTarget) c.closeTabView() }}>
    <div class="dialog tabview" role="dialog" aria-modal="true" aria-labelledby="tabview-title" ref=${dialog}>
      <header class="tabview-head">
        ${state ? html`<${StateLine} token=${stateToken(state)} strong=${state === 'needs-you'} word=${t.state[state] ?? state} />` : null}
        <h2 class="sec-title tabview-title" id="tabview-title">${isControl ? t.controlSession : tab?.name ?? screen?.name ?? ref}</h2>
        <span class="muted small">${tab?.workspace ?? screen?.workspace ?? ''}</span>
        <span class="tabview-live muted small" aria-live="off">${err ? html`<${StateLine} token="danger" word=${t.tabViewFailed(err)} />`
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
      ${!claude || ref ? html`<div class="tabview-body" ref=${body} onScroll=${onScroll} tabindex="0" role="log" aria-label=${t.tabViewLog}>
        ${lines.length ? lines.map((l, i) => html`<div key=${i} class=${`tl tl-${l.kind}`}>${l.text || ' '}</div>`)
          : html`<p class="muted">${screen ? t.tabViewEmpty : t.loading}</p>`}
      </div>` : html`<div></div>`}
      <footer class="tabview-foot">
        ${state === 'needs-you' && canTab(s, 'key') ? html`<div class="btn-row">
          <${Btn} size="xs" variant="primary" busy=${busy} onClick=${() => c.act('tab_yes', { tab_ref: ref })}>${t.btnYes}<//>
          <${Btn} size="xs" variant="secondary" busy=${busy} onClick=${() => c.act('tab_no', { tab_ref: ref })}>${t.btnNo}<//>
        </div>` : null}
        ${state === 'waiting' && tab && !tab.filed_by && !tab.is_control ? html`<div class="btn-row">
          <${Btn} size="xs" variant="secondary" busy=${busy} onClick=${() => c.act('tab_go_on', { tab_ref: ref })}>${t.btnGoOn}<//></div>` : null}
        <${SendBox} id="tabview-input" label=${t.msgPlaceholder} value=${text} setValue=${setText} onSend=${send} busy=${busy}
          max=${isControl ? ASK_MAX : TAB_MSG_MAX} placeholder=${isControl ? t.askPlaceholder : t.tabViewPlaceholder} />
      </footer>
    </div>
  </div>`
}

/** A session tab as a card. In the agent tab column it is slim: state, name and its one next step; a
 *  click on more opens the preview and every control */
function TabCard({ tab, s, c, byKey, slim = false }) {
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
        : html`<${StateLine} token=${stateToken(tab.state)} strong=${tab.state === 'needs-you'} word=${t.state[tab.state] ?? tab.state} />`}
      <span class="tabcard-age mono">${ageText}</span>
      ${tab.long ? html`<span class="chip chip-warn-outline">${t.tabLong}</span>` : null}
    </header>
    <h3 class="tabcard-name">${hasRow
      ? html`<button type="button" class="btn-link" title=${t.showTab(tab.name)} onClick=${() => c.select(rowKey)}>${tab.name}</button>`
      : html`<button type="button" class="btn-link" title=${t.btnTabView} onClick=${() => c.openTabView(tab.ref)}>${tab.name}</button>`}</h3>
    ${full && previewText(tab.last) ? html`<p class="tab-last clamp2" title=${tab.last}>${previewText(tab.last)}</p>` : null}
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
        ${inDrawer ? html`<${Btn} variant="ghost" size="xs" icon="close" label=${t.close} onClick=${() => c.setDrawer(null)} />` : null}
      </header>
      ${!s.cmux?.ok ? html`<p class="banner"><${StateLine} token="warning" word=${t.cmuxMissing(s.cmux?.error ?? '')} /></p>` : null}
      ${s.tabs?.error ? html`<p class="banner"><${StateLine} token="danger" strong word=${t.tabsStale(s.tabs.error.since, s.tabs.error.message)} /></p>` : null}
      ${control ? html`<${TabCard} tab=${control} s=${s} c=${c} byKey=${byKey} slim />` : null}
      ${groups.length ? groups.map(g => html`<section class="tabgroup" key=${g.workspace}>
        <h3 class="mono-label">${g.workspace || '·'}</h3>
        <div class="tabgrid">${g.tabs.map(tab => html`<${TabCard} key=${tab.ref} tab=${tab} s=${s} c=${c} byKey=${byKey} slim />`)}</div>
      </section>`) : html`<${Empty}>${t.tabsEmpty}<//>`}
      <${SnapshotPanel} s=${s} c=${c} />
    </div>
  </div>`
}
