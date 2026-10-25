// SPDX-License-Identifier: MIT
// The cockpit, the news ticker: the news of the feeds the server reads (state.ticker) run in one slim band
// beside the greeting, and what runs, waits, is slow or failing (read from the page's own store, logic.js
// tickerStatus) stands still as a list in the live section of the start page. Its group on the settings
// page stands here too.
// The rules every component keeps stand at the head of components.js.
//
// Claude Haiku edits the news only from the Editor button: no effect, timer or render ever asks it.

import { html, useEffect, useRef, useState } from '../vendor/htm-preact-3.1.1.module.js'
import {
  TICKER_KINDS, indexRows, tickerDuration, tickerResume, tickerFeedItems, tickerFeedValid, tickerIsNew, tickerItems,
  tickerMuteTerms, tickerPage, tickerPatch, tickerSourceToken, tickerStatusItems, tickerText,
} from '../logic.js'
import { reducedMotion } from '../motion.js'
import { T } from '../text.js'
import { Segmented } from './detail.js'
import { jumpToTab, openWhole } from './home.js'
import { pageOrder } from './nav.js'
import { Btn, Chip, Empty } from './parts.js'
// a cycle (settings.js draws TickerSettings): these parts are used only inside render functions
import { Card, Row, Switch } from './settings.js'

// a status tone as the design token the band colours it with
const TONE_TOKEN = { bad: 'danger', warn: 'warning', info: 'accent', ok: 'success' }
// how many status rows the live section shows before "more"
const STATUS_MAX = 6

/** Where a click on a status item leads: only to names the controller has, a page that exists nowhere opens Today */
function goTo(s, c, target, el) {
  switch (target?.kind) {
    case 'page': return c.setPage(tickerPage(s, target.id, pageOrder(s)))
    case 'item': return c.openItem(target.key, null)
    case 'tab': return jumpToTab(s, c, target.ref)
    case 'drawer': return c.setDrawer(target.id)
    case 'info': return c.openInfo(target.it, target.page, target.section)
    case 'row': {
      const row = indexRows(s.model).get(target.key)
      return row ? openWhole(c, row, el) : c.setPage('briefing')
    }
    case 'review': return c.openReview()
    case 'workers': return c.openWorkers(null)
    case 'conv': return c.openAgentConv(target.id)
    case 'claude': return c.openClaude()
    default: return null
  }
}

/** A status item: a button that leads to where it stands, or plain text where it leads nowhere; the same
 *  in the band and in the list of the live section */
function StatusItem({ it, s, c }) {
  const cls = `ticker-item ticker-status tk-${TONE_TOKEN[it.tone] ?? 'accent'}`
  const words = tickerText(it, T())
  if (!it.target) return html`<span class=${cls}><span class="ticker-dot" aria-hidden="true"></span><span>${words}</span></span>`
  return html`<button type="button" class=${cls} onClick=${e => goTo(s, c, it.target, e.currentTarget)}>
    <span class="ticker-dot" aria-hidden="true"></span><span>${words}</span></button>`
}

/** One entry of the band: a news item as a link that opens in a new tab, its source in a colour of its
 *  own (the same for the same feed on every load), or a status item. A news item marks itself new (after
 *  the viewer's last visit, or after the editor's pick), names how many other feeds tell the same story,
 *  and dims once opened in this browser */
function TickerEntry({ it, s, c, order, smart }) {
  const t = T()
  if (it.kind === 'feed') {
    const fresh = it.fresh || (smart?.mark_new !== false && tickerIsNew(it, s.ui.tickerSince))
    const read = (s.ui.tickerRead ?? []).includes(it.id)
    const also = (it.sources ?? []).map(x => x.source).filter(Boolean)
    const title = [it.title, also.length ? t.ticker.alsoAt(also) : ''].filter(Boolean).join('\n')
    return html`<li><a class=${`ticker-item ticker-feed${fresh ? ' ticker-fresh' : ''}${read ? ' ticker-read' : ''}`} href=${it.url}
      target="_blank" rel="noopener noreferrer" title=${title} onClick=${() => c.tickerOpened?.(it.id)}>
      <span class=${`ticker-src tk-${tickerSourceToken(it.feed ?? it.source, order)}`}>${it.source}</span>
      ${fresh ? html`<span class="ticker-new">${t.ticker.fresh}</span>` : null}
      <span class="ticker-title">${it.short ?? it.title}</span>
      ${also.length ? html`<span class="ticker-also"><span class="sr-only">${t.ticker.alsoAt(also)}</span><span aria-hidden="true">+${also.length}</span></span>` : null}</a></li>`
  }
  return html`<li><${StatusItem} it=${it} s=${s} c=${c} /></li>`
}

/** The status, standing still: loudest first like the band sorted it, at most six rows, the rest behind a
 *  toggle that opens them in place. Nothing while the ticker or its status is off, or nothing is to say */
export function TickerStatusList({ s, c }) {
  const t = T()
  const [open, setOpen] = useState(false)
  const items = tickerStatusItems(s, s.now || Date.now())
  if (!items.length) return null
  const rest = items.length - STATUS_MAX
  const shown = open || rest <= 0 ? items : items.slice(0, STATUS_MAX)
  return html`<div class="ticker-status-box">
    <ul class="ticker-status-list" aria-label=${t.ticker.statusLabel}>
      ${shown.map(it => html`<li key=${it.id}><${StatusItem} it=${it} s=${s} c=${c} /></li>`)}
    </ul>
    ${rest > 0 ? html`<button type="button" class="btn-link ticker-status-more" aria-expanded=${String(open)}
      onClick=${() => setOpen(!open)}>${open ? t.ticker.less : t.ticker.more(rest)}</button>` : null}
  </div>`
}

/** The band: a small head (its name, how many are new, Pause, Editor, Refresh, how it stands) over one
 *  line whose entries run from right to left in two equal tracks, the second only a copy for the seamless
 *  loop (hidden from screen readers and the keyboard). The line has no box: a hairline under it like the
 *  greeting's, its ends fade. Hover, focus and the Pause button stop it (WCAG 2.2.2: the button is the way
 *  for touch and keyboard, kept per browser); with reduced motion it stands still and scrolls by hand.
 *  With only="news" it carries the feed items alone, the status stands in TickerStatusList */
export function TickerBand({ s, c, only }) {
  const t = T()
  const tk = s.ticker
  const news = only === 'news'
  const items = news ? tickerFeedItems(s) : tickerItems(s, s.now || Date.now())
  const speed = tk?.settings?.speed ?? 'normal'
  const trackRef = useRef(null)
  const copyRef = useRef(null)
  const still = reducedMotion()
  const sig = items.map(x => x.id).join('|')
  // one pass takes the track's width at the chosen speed; set through the CSSOM, never a style attribute
  useEffect(() => {
    const el = trackRef.current
    if (!el) return
    const sec = tickerDuration(el.scrollWidth, speed)
    for (const x of [el, copyRef.current]) {
      if (!x) continue
      // keep the place in the pass: a bare new duration would move the band by the change in share
      const a = x.getAnimations?.()[0]
      const was = a ? Number(a.currentTime) : null
      const old = parseFloat(x.style.animationDuration)
      x.style.animationDuration = `${sec}s`
      const b = x.getAnimations?.()[0]
      if (b && Number.isFinite(was) && old > 0) b.currentTime = tickerResume(was, old, sec)
    }
  }, [sig, speed])
  if (!tk?.enabled || !items.length) return null
  const ed = tk.editor ?? {}
  const editing = !!ed.running || !!s.ui.busy.ticker_edit
  const refreshing = !!tk.refreshing || !!s.ui.busy.ticker_refresh
  const failed = (tk.feeds ?? []).filter(f => f.ok === false || f.error).length
  const smart = tk.settings?.smart
  const paused = !!s.ui.tickerPaused
  const fresh = items.filter(it => it.kind === 'feed' && (it.fresh || (smart?.mark_new !== false && tickerIsNew(it, s.ui.tickerSince)))).length
  // each track gets its own entries: one vnode is never mounted twice
  // the configured feeds in order, disabled ones included, so switching one off moves no colour
  const order = (tk?.settings?.feeds ?? []).map(f => f.id)
  const entries = () => items.map(it => html`<${TickerEntry} key=${it.id} it=${it} s=${s} c=${c} order=${order} smart=${smart} />`)
  return html`<section class=${`ticker${news ? ' ticker-news' : ''}${paused ? ' is-paused' : ''}`} role="region" aria-label=${news ? t.ticker.newsLabel : t.ticker.label}>
    <div class="ticker-head">
      <span class="ticker-eyebrow">${news ? t.ticker.newsName : t.ticker.label}</span>
      ${fresh ? html`<span class="ticker-count">${t.ticker.freshCount(fresh)}</span>` : null}
      <span class="ticker-tools">
        ${still ? null : html`<${Btn} size="xs" variant="ghost" icon=${paused ? 'play' : 'pause'} pressed=${paused}
          label=${paused ? t.ticker.play : t.ticker.pause} title=${paused ? t.ticker.play : t.ticker.pause} onClick=${() => c.setTickerPaused(!paused)} />`}
        ${ed.available ? html`<${Btn} size="xs" variant="ghost" icon="spark" busy=${editing} label=${t.ticker.edit} title=${t.ticker.editTitle}
          onClick=${() => c.tickerEdit()}>${editing ? t.ticker.editing : null}<//>` : null}
        <${Btn} size="xs" variant="ghost" icon="reload" busy=${refreshing} label=${t.ticker.refresh} title=${t.ticker.refresh}
          onClick=${() => c.tickerRefresh()}>${refreshing ? t.ticker.refreshing : null}<//>
      </span>
      <span class="ticker-meta">
        ${ed.last ? html`<span>${t.ticker.edited(ed.last.picked, ed.last.of)}</span>` : null}
        ${failed ? html`<span>${t.ticker.feedError(failed)}</span>` : null}
        ${ed.error ? html`<span class="set-bad">${t.ticker.editFailed(ed.error)}</span>` : null}
      </span>
    </div>
    <div class="ticker-viewport">
      <ul class=${`ticker-track ticker-${speed}`} ref=${trackRef}>${entries()}</ul>
      ${still ? null : html`<ul class=${`ticker-track ticker-copy ticker-${speed}`} ref=${copyRef} aria-hidden="true" inert>${entries()}</ul>`}
    </div>
  </section>`
}

// ---------------------------------------------------------------- the settings group

/** The interests as free text, saved with the button or Enter (Shift Enter for a new line) */
function InterestsField({ value, busy, save }) {
  const w = T().ticker.settings
  const [draft, setDraft] = useState(value)
  useEffect(() => setDraft(value), [value])
  const same = draft.trim() === value.trim()
  const go = () => { if (!same && draft.length <= 500) save(draft) }
  return html`<span class="field-row set-field ticker-interests">
    <textarea class="input input-sm" rows="2" maxlength="500" value=${draft} aria-label=${w.label.interests}
      onInput=${e => setDraft(e.currentTarget.value)}
      onKeyDown=${e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); go() } }}></textarea>
    <${Btn} size="xs" variant="secondary" busy=${busy} disabled=${same} onClick=${go}>${w.save}<//>
  </span>`
}

/** The muted terms as one line of text, comma separated, saved with the button or Enter */
function MuteField({ value, busy, save }) {
  const w = T().ticker.settings
  const joined = (value ?? []).join(', ')
  const [draft, setDraft] = useState(joined)
  useEffect(() => setDraft(joined), [joined])
  const terms = tickerMuteTerms(draft)
  const same = terms.join('\n') === (value ?? []).join('\n')
  const go = () => { if (!same) save(terms) }
  return html`<span class="field-row set-field ticker-interests">
    <input class="input input-sm" type="text" value=${draft} aria-label=${w.label.mute} placeholder=${w.mutePlaceholder}
      onInput=${e => setDraft(e.currentTarget.value)} onKeyDown=${e => { if (e.key === 'Enter') { e.preventDefault(); go() } }} />
    <${Btn} size="xs" variant="secondary" busy=${busy} disabled=${same} onClick=${go}>${w.save}<//>
  </span>`
}

/** The interest profile proposed from the open tasks: as keywords (no model) or written by Haiku, each only
 *  on its button. The proposal stands below until it is taken into the interests or a new one comes */
function ProfileBox({ tk, s, c, busy, save }) {
  const w = T().ticker.settings
  const p = tk.profile ?? {}
  const last = p.last
  const llmOn = !!tk.editor?.available
  const running = !!p.running || !!s.ui.busy.ticker_profile
  const none = !(p.tasks > 0)
  return html`<div class="ticker-profile">
    <span class="field-row">
      <${Btn} size="xs" variant="ghost" busy=${running} disabled=${busy || none} onClick=${() => c.tickerProfile(false)}>${w.profileWords}<//>
      ${llmOn ? html`<${Btn} size="xs" variant="ghost" icon="spark" busy=${running} disabled=${busy || none}
        onClick=${() => c.tickerProfile(true)}>${running ? w.profileRunning : w.profileLlm}<//>` : null}
      <span class="muted small">${none ? w.profileNoTasks : w.profileFrom(p.tasks)}</span>
    </span>
    ${last?.error ? html`<span class="small set-bad">${w.profileFailed(last.error)}</span>` : null}
    ${last?.text ? html`<div class="ticker-proposal">
      <span class="small muted">${last.llm ? w.proposalLlm : w.proposalWords}</span>
      <p>${last.text}</p>
      <${Btn} size="xs" variant="secondary" disabled=${busy} onClick=${() => save(last.text)}>${w.takeProposal}<//>
    </div>` : null}
  </div>`
}

/** The feeds: edited here row by row, each checked like the server checks it, saved as one list */
function FeedsTable({ feeds, status, busy, save }) {
  const w = T().ticker.settings
  const [draft, setDraft] = useState(feeds)
  const was = JSON.stringify(feeds)
  useEffect(() => setDraft(feeds), [was])
  const set = (i, patch) => setDraft(draft.map((f, j) => (j === i ? { ...f, ...patch } : f)))
  const bad = draft.some(f => !tickerFeedValid(f)) || new Set(draft.map(f => f.id.trim())).size !== draft.length
  const field = (f, i, key, label, cls) => html`<input class=${`input input-sm ${cls}`} type="text" value=${f[key]}
    aria-label=${`${label} ${i + 1}`} aria-invalid=${String(!tickerFeedValid(f))} onInput=${e => set(i, { [key]: e.currentTarget.value })} />`
  return html`<div class="set-table-wrap">
    <table class="tbl set-table ticker-feeds">
      <thead><tr><th scope="col">${w.feedOn}</th><th scope="col">${w.feedId}</th><th scope="col">${w.feedName}</th>
        <th scope="col">${w.feedUrl}</th><th scope="col"></th></tr></thead>
      <tbody>${draft.map((f, i) => {
        const err = (status ?? []).find(x => x.id === f.id)?.error
        return html`<tr key=${i}>
          <td><input type="checkbox" checked=${f.enabled !== false} aria-label=${`${w.feedOn} ${i + 1}`}
            onChange=${e => set(i, { enabled: e.currentTarget.checked })} /></td>
          <td>${field(f, i, 'id', w.feedId, 'mono ticker-feed-id')}</td>
          <td>${field(f, i, 'name', w.feedName, '')}</td>
          <td>${field(f, i, 'url', w.feedUrl, 'mono ticker-feed-url')}
            ${err ? html`<span class="small set-bad">${w.feedFailed(err)}</span>` : null}</td>
          <td><${Btn} size="xs" variant="ghost" onClick=${() => setDraft(draft.filter((_, j) => j !== i))}>${w.removeFeed}<//></td>
        </tr>`
      })}</tbody>
    </table>
    <span class="field-row">
      <${Btn} size="xs" variant="ghost" disabled=${draft.length >= 20}
        onClick=${() => setDraft([...draft, { id: '', name: '', url: '', enabled: true }])}>${w.addFeed}<//>
      <${Btn} size="xs" variant="secondary" busy=${busy} disabled=${bad || !draft.length || JSON.stringify(draft) === was}
        onClick=${() => save(draft)}>${w.save}<//>
      ${bad ? html`<span class="small set-bad">${w.feedBad}</span>` : null}
    </span>
  </div>`
}

/** The ticker's area on the settings page: the band, its feeds, which status it mixes in, and the editor's
 *  wishes, a card each. Every change saves at once into .bridge/cockpit/ticker.json, never the config */
export function TickerSettings({ s, c }) {
  const w = T().ticker.settings
  const tk = s.ticker
  if (!tk?.settings) {
    return html`<${Card} title=${w.title}><${Empty}>${w.noServer}<//><//>`
  }
  const st = tk.settings
  const on = !!st.enabled
  const busy = !!s.ui.busy.ticker_settings || !!s.ui.busy.ticker_settings_reset
  const save = (k, v) => c.saveTicker(tickerPatch(k, v, st))
  const num = (k, choices, word = String) => html`<${Segmented} label=${w.label[k]} busy=${busy || !on} current=${st[k]}
    values=${choices.map(v => [v, word(v)])} onPick=${v => save(k, v)} />`
  const kinds = st.status?.kinds ?? TICKER_KINDS
  const statusOn = st.status?.enabled !== false
  const ed = st.editor ?? {}
  const sm = st.smart ?? {}
  const edOn = ed.enabled !== false
  const changed = (tk.overridden ?? []).length
  // one setting in the page's row, marked where the page changed its block against bridge-config.yaml
  const row = (k, children, { field, wide } = {}) => html`<${Row} label=${w.label[k]} explain=${w.explain[k]} wide=${wide}
    mark=${(tk.overridden ?? []).includes(field ?? k) ? html`<${Chip} token="warning">${w.changed}<//>` : null}>${children}<//>`
  return html`
    ${changed ? html`<div class="set-banner" role="status">
      <span class="set-banner-text">${w.resetTitle}</span>
      <${Btn} size="xs" variant="ghost" busy=${busy} onClick=${() => c.resetTicker()}>${w.reset}<//>
    </div>` : null}
    <${Card} title=${w.title} intro=${w.intro}
      head=${html`<span class="set-head-switch"><${Switch} label=${w.label.enabled} on=${on} disabled=${busy} onChange=${v => save('enabled', v)} /></span>`}>
      ${row('speed', html`<${Segmented} label=${w.label.speed} busy=${busy || !on} current=${st.speed}
        values=${['slow', 'normal', 'fast'].map(v => [v, w.speed[v]])} onPick=${v => save('speed', v)} />`)}
      ${row('max_items', num('max_items', [10, 20, 30, 50]))}
      ${row('per_feed', num('per_feed', [3, 5, 8, 12]))}
      ${row('refresh_minutes', num('refresh_minutes', [15, 30, 60, 180], w.minutes))}
    <//>
    <${Card} title=${w.label.onStart} intro=${w.explain.onStart} off=${!on}
      head=${html`<span class="set-head-switch"><${Switch} label=${w.label.onStart} on=${!!s.ui.tickerOnStart} disabled=${!on} onChange=${v => c.setTickerOnStart(v)} /></span>`} />
    <${Card} title=${w.label.feeds} intro=${w.explain.feeds} off=${!on}>
      <${FeedsTable} feeds=${st.feeds ?? []} status=${tk.feeds} busy=${busy || !on} save=${v => save('feeds', v)} />
    <//>
    <${Card} title=${w.label.status} intro=${w.explain.status} off=${!on || !statusOn}
      head=${html`<span class="set-head-switch"><${Switch} label=${w.label.status} on=${statusOn} disabled=${busy || !on} onChange=${v => save('status.enabled', v)} /></span>`}>
      ${row('kinds', html`<div class="chooser-chips" role="group" aria-label=${w.label.kinds}>
          ${TICKER_KINDS.map(k => html`<button type="button" key=${k} class=${`home-chip${kinds.includes(k) ? ' is-on' : ''}`}
            aria-pressed=${String(kinds.includes(k))} disabled=${busy || !on || !statusOn}
            onClick=${() => save('status.kinds', TICKER_KINDS.filter(x => (x === k ? !kinds.includes(k) : kinds.includes(x))))}>${w.kind[k]}</button>`)}
        </div>`, { field: 'status', wide: true })}
    <//>
    <${Card} title=${w.smartTitle} intro=${w.smartIntro} off=${!on}>
      ${row('cluster', html`<${Switch} label=${w.label.cluster} on=${sm.cluster !== false} disabled=${busy || !on}
        onChange=${v => save('smart.cluster', v)} />`, { field: 'smart' })}
      ${row('max_age_hours', html`<${Segmented} label=${w.label.max_age_hours} busy=${busy || !on} current=${sm.max_age_hours ?? 0}
        values=${[0, 24, 72, 168].map(v => [v, w.age(v)])} onPick=${v => save('smart.max_age_hours', v)} />`, { field: 'smart' })}
      ${row('mark_new', html`<${Switch} label=${w.label.mark_new} on=${sm.mark_new !== false} disabled=${busy || !on}
        onChange=${v => save('smart.mark_new', v)} />`, { field: 'smart' })}
      ${row('mute', html`<${MuteField} value=${sm.mute ?? []} busy=${busy || !on} save=${v => save('smart.mute', v)} />`,
        { field: 'smart', wide: true })}
    <//>
    <${Card} title=${w.interestsTitle} intro=${w.interestsIntro} off=${!on}>
      <div class="ticker-interests-box">
        <${InterestsField} value=${ed.interests ?? ''} busy=${busy} save=${v => save('editor.interests', v)} />
        <${ProfileBox} tk=${tk} s=${s} c=${c} busy=${busy || !on} save=${v => save('editor.interests', v)} />
      </div>
    <//>
    <${Card} title=${w.editorTitle} intro=${w.editorIntro} off=${!on || !edOn}
      head=${html`<span class="set-head-switch"><${Switch} label=${w.label.editorOn} on=${edOn} disabled=${busy || !on} onChange=${v => save('editor.enabled', v)} /></span>`}>
      ${row('max_picks', html`<${Segmented} label=${w.label.max_picks} busy=${busy || !on || !edOn} current=${ed.max_picks}
        values=${[5, 8, 12, 20].map(v => [v, String(v)])} onPick=${v => save('editor.max_picks', v)} />`, { field: 'editor' })}
      ${row('shorten', html`<${Switch} label=${w.label.shorten} on=${ed.shorten !== false} disabled=${busy || !on || !edOn}
        onChange=${v => save('editor.shorten', v)} />`, { field: 'editor' })}
    <//>`
}
