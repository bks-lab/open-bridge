// SPDX-License-Identifier: MIT
// The cockpit, the decision guide (guide.py): what Claude Haiku read of a waiting tab, drawn as a small
// tree. The root says where the session stands and what it waits for; each branch is one next step, and a
// click on it sends through the reply verbs that guard a tab (logic.js guideChoices: tab_send with the
// question's hash, tab_option for a dialog's number). A step that reaches beyond the session (push, merge,
// delete, deploy, send) takes a second click. The last branch always opens the tab to answer it yourself.
// GuideTree stands in the chat's tab pane and the tab window, GuideLine in the sidebar's "Waiting for you"
// and on a session card, GuideBoard on top of the Sessions page, GuideSettings on the settings page.
// The rules every component keeps stand at the head of components.js.

import { html, useState } from '../vendor/htm-preact-3.1.1.module.js'
import { answerMark, canTab, centsText, duration, errorText, guideChoices, guideOf, short, stateToken } from '../logic.js'
import { T, language } from '../text.js'
import { Thinking } from './chat.js'
import { Btn, Chip, Dot, Empty, Icon, StateLine } from './parts.js'
import { Card, Switch } from './settings.js'

const URGENCY = { 'needs-you': 0, waiting: 1 }

/** The reading of one waiting tab as a tree; nothing while the guide is off or the tab does not wait.
 *  `compact` (a narrow column) leaves out the words a step would send */
export function GuideTree({ tab, s, c, compact = false }) {
  const t = T()
  const g = t.guide
  const { status, entry } = guideOf(s, tab)
  const [armed, setArmed] = useState(null)
  const [note, setNote] = useState(null)
  if (status === 'off') return null
  const busy = !!s.ui?.busy?.[tab.ref]
  const read = html`<${Btn} size="xs" variant="ghost" icon="reload" busy=${busy} onClick=${() => c.guideRead(tab.ref)}>
    ${status === 'none' ? g.read : g.again}<//>`
  if (status === 'none') {
    return html`<div class="guide is-empty" role="group" aria-label=${g.title}>
      <p class="muted small guide-empty"><${Icon} name="spark" size=${12} /> ${g.noneYet}</p>${read}</div>`
  }
  if (status === 'running') {
    return html`<div class="guide is-running" role="group" aria-label=${g.title} aria-busy="true"><${Thinking} label=${g.reading} /></div>`
  }
  if (status === 'error') {
    return html`<div class="guide is-error" role="group" aria-label=${g.title}>
      <p class="small"><${StateLine} token="danger" word=${g.failed(entry.error)} /></p>${read}</div>`
  }
  const choices = status === 'fresh' ? guideChoices(tab, entry, s) : []
  const pick = async ch => {
    if (ch.risky && armed !== ch.id) { setArmed(ch.id); return }
    setArmed(null)
    setNote(null)
    const r = await c.reply(ch.verb, ch.args)
    if (r?.refused) { setNote(errorText(r.error, t)); return }
    if (!r?.ok) { if (r?.note) setNote(r.note); return }
    c.markAnswered?.(tab.ref, answerMark(tab, short(ch.label, 40), Date.now()))
  }
  const cost = entry.cost_usd == null ? null : centsText(entry.cost_usd * 100, language())
  const ago = duration((s.now || Date.now()) - (entry.at_ms ?? s.now ?? Date.now()))
  return html`<div class=${`guide${status === 'stale' ? ' is-stale' : ''}${compact ? ' is-compact' : ''}`} role="group" aria-label=${g.title}>
    <div class="guide-root">
      <span class="label-caps guide-cap"><${Icon} name="spark" size=${12} /> ${g.where}</span>
      <p class="guide-where">${entry.where}</p>
      ${entry.waits_for ? html`<p class="guide-waits small"><span class="muted">${g.waitsFor}</span> ${entry.waits_for}</p>` : null}
      ${status === 'stale' ? html`<p class="small"><${StateLine} token="warning" word=${g.stale} /></p>` : null}
    </div>
    <ul class="guide-branches">
      ${choices.map(ch => html`<li key=${ch.id} class=${`guide-branch${ch.picked ? ' is-picked' : ''}${ch.risky ? ' is-risky' : ''}`}>
        <button type="button" class=${`guide-opt${armed === ch.id ? ' is-armed' : ''}`} disabled=${busy}
          title=${ch.send ? g.sends(ch.send) : g.presses(ch.n)} onClick=${() => pick(ch)}>
          <span class="guide-opt-head">
            <span class="guide-opt-label">${armed === ch.id ? g.confirm(ch.label) : ch.label}</span>
            ${ch.picked ? html`<${Chip} token="info" cls="guide-chip">${g.picked}<//>` : null}
            ${ch.risky ? html`<${Chip} token="warning" cls="guide-chip">${g.risky}<//>` : null}
          </span>
          ${ch.why ? html`<span class="guide-why muted small">${ch.why}</span>` : null}
          ${ch.send && !compact ? html`<span class="guide-send mono small">${g.sends(short(ch.send, 120))}</span>` : null}
        </button>
      </li>`)}
      ${status === 'fresh' && !choices.length ? html`<li class="guide-branch is-none"><span class="muted small">${g.none}</span></li>` : null}
      <li class="guide-branch is-own">
        <button type="button" class="guide-opt is-own" onClick=${() => c.openTabView(tab.ref)}>
          <span class="guide-opt-label">${g.own}</span>
        </button>
      </li>
    </ul>
    <footer class="guide-foot muted small">
      <span>${g.meta(g.source[entry.source] ?? '', cost, ago)}</span>
      ${read}
    </footer>
    ${note ? html`<p class="reply-note small" role="status">${note}</p>` : null}
  </div>`
}

/** One line of the reading: where the tab stands, for the sidebar and a session card; nothing otherwise */
export function GuideLine({ tab, s }) {
  const t = T()
  const { status, entry } = guideOf(s, tab)
  if (status === 'running') return html`<p class="guide-line muted small"><${Icon} name="spark" size=${12} /> ${t.guide.reading}</p>`
  if (status !== 'fresh' || !entry?.where) return null
  return html`<p class="guide-line small clamp2" title=${entry.where}><${Icon} name="spark" size=${12} /> ${entry.where}</p>`
}

/** "Where you are needed" on top of the Sessions page: every tab that waits for you with its reading,
 *  the tabs that need you first; nothing while the guide is off or no tab waits. A tab whose result is
 *  filed stays out: it waits only to be checked, and "With AI" below offers that */
export function GuideBoard({ s, c }) {
  const t = T()
  if (!s.guide?.enabled) return null
  const tabs = (s.tabs?.tabs ?? []).filter(tab => !tab.filed_by && guideOf(s, tab).status !== 'off')
    .sort((a, b) => (URGENCY[a.state] ?? 2) - (URGENCY[b.state] ?? 2) || (a.since_ms ?? 0) - (b.since_ms ?? 0))
  if (!tabs.length) return null
  const jump = canTab(s, 'focus')
  return html`<section class="panel panel-pad psec guide-board" aria-labelledby="guide-board-title">
    <header class="psec-head">
      <h3 class="sec-title" id="guide-board-title">${t.guide.boardTitle} <span class="sec-count mono">${tabs.length}</span></h3>
      ${s.guide.auto ? null : html`<span class="muted small">${t.guide.manualHint}</span>`}
    </header>
    <p class="muted small guide-board-intro">${t.guide.boardIntro}</p>
    <div class="guide-board-list">${tabs.map(tab => html`<article key=${tab.ref} class="guide-card">
      <header class="guide-card-head">
        <${Dot} token=${stateToken(tab.state)} />
        ${jump ? html`<button type="button" class="btn-link guide-card-name" onClick=${() => c.act('tab_jump', { tab_ref: tab.ref })}>${short(tab.name, 60)}</button>`
          : html`<span class="guide-card-name">${short(tab.name, 60)}</span>`}
        <span class="muted small">${tab.workspace}</span>
        <span class="muted small">${t.state[tab.state] ?? tab.state}</span>
      </header>
      <${GuideTree} tab=${tab} s=${s} c=${c} />
    </article>`)}</div>
  </section>`
}

/** The settings page's area of the guide: the switch, reading by itself, what is read */
export function GuideSettings({ s, c }) {
  const w = T().settings
  const g = s.guide
  if (!g) return html`<${Card} title=${w.guideTitle}><${Empty}>${w.noServer}<//><//>`
  const busy = !!s.ui.busy?.guide_settings || !!s.ui.busy?.guide_settings_reset
  const toggle = (k, disabled = false) => html`<span class="set-head-switch"><${Switch} on=${!!g[k]} label=${w.guideLabel[k]}
    disabled=${busy || disabled} onChange=${v => c.saveGuide({ [k]: v })} /></span>`
  const changed = (g.overridden ?? []).length
  return html`
    ${changed ? html`<div class="set-banner" role="status">
      <span class="set-banner-text">${w.overridden(changed)}</span>
      <${Btn} size="xs" variant="secondary" busy=${busy} title=${w.resetTitle} onClick=${() => c.resetGuide()}>${w.reset}<//>
    </div>` : null}
    <${Card} title=${w.guideTitle} intro=${g.enabled ? w.guideIntro : w.guideOff} head=${toggle('enabled')}>
      ${g.available === false ? html`<p class="small"><${StateLine} token="warning" word=${w.guideNoClaude} /></p>` : null}
      <p class="muted small">${w.guidePrivacy}</p>
    <//>
    <${Card} title=${w.guideAutoTitle} intro=${w.guideAutoIntro(g.per_hour)} off=${!g.enabled} head=${toggle('auto', !g.enabled)} />`
}
