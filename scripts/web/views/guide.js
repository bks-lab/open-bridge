// SPDX-License-Identifier: MIT
// The cockpit, the decision guide (guide.py): what Claude Haiku read of a waiting tab, drawn as a small
// tree. The root says what the session is about (its folder and task beside it, its first ask on hover),
// where it stands and what it waits for; each branch is one next step. A click on a branch only puts its
// words in a box under the tree, to read and edit; Send types them into the tab (a dialog's step: Press
// presses its number), through the reply verbs that guard a tab (logic.js guideChoices: tab_send with the
// question's hash, tab_option for a dialog's number). A step that reaches beyond the session (push, merge,
// delete, deploy, send) says so in the box. The last branch opens an empty box to answer yourself. Beside
// the reading: To tab (the terminal jumps there), Watch (the tab's live screen here) and What was read (the
// asks and the agent's words Haiku read), for when the short reading is not enough.
// GuideTree stands in the chat's tab pane and on the tab cards, GuideLine in the sidebar's "Waiting for you"
// and on a session card, GuideBoard on top of the Sessions page, GuideSettings on the settings page.
// The rules every component keeps stand at the head of components.js.

import { html, useEffect, useRef, useState } from '../vendor/htm-preact-3.1.1.module.js'
import { answerMark, canTab, centsText, duration, errorText, guideChoices, guideOf, replySend, short, stateToken, tabStateKey } from '../logic.js'
import { T, language } from '../text.js'
import { Thinking } from './chat.js'
import { TAB_MSG_MAX } from './nav.js'
import { Btn, Chip, Dot, Empty, Icon, StateLine } from './parts.js'
import { Prose } from './prose.js'
import { Card, Switch } from './settings.js'

const URGENCY = { 'needs-you': 0, waiting: 1 }

/** What the session is about: Haiku's line (or its title, task or first ask while Haiku reads), its folder
 *  and its task beside it, the ask it was started with on hover; nothing before the session was read */
function About({ entry }) {
  const g = T().guide
  if (!entry?.about) return null
  const topic = entry.topic ?? {}
  const facts = [topic.project, topic.task_title ? g.task(topic.task_title) : null].filter(Boolean)
  return html`<div class="guide-head">
    <span class="label-caps guide-cap">${g.about}</span>
    <p class="guide-about">${entry.about}</p>
    ${facts.length || topic.first ? html`<p class="guide-topic muted small" title=${topic.first ? g.startedWith(topic.first) : undefined}>
      ${facts.length ? facts.map((f, i) => html`<span key=${i} class="guide-fact">${f}</span>`)
        : html`<span class="guide-fact">${g.startedWith(short(topic.first, 80))}</span>`}</p>` : null}
  </div>`
}

/** The ways into the session beside a reading: the terminal jumps to the tab, the tab's live screen opens
 *  here, and what Haiku read unfolds below. `bare`: the host shows its own ways to the tab, only what was read */
function Ways({ tab, s, c, entry, open, setOpen, bare = false }) {
  const g = T().guide
  return html`<span class="guide-ways">
    ${!bare && canTab(s, 'focus') ? html`<${Btn} size="xs" variant="ghost" icon="external" onClick=${() => c.act('tab_jump', { tab_ref: tab.ref })}>${g.toTab}<//>` : null}
    ${bare ? null : html`<${Btn} size="xs" variant="ghost" icon="tabs" onClick=${() => c.openTabView(tab.ref)}>${g.watch}<//>`}
    ${entry?.read ? html`<${Btn} size="xs" variant="ghost" pressed=${open} onClick=${() => setOpen(!open)}>${open ? g.hideRead : g.showRead}<//>` : null}
  </span>`
}

/** What Haiku read of the session: the ask it was started with, the asks before and last, and the agent's
 *  last words (Markdown, drawn as text) or the end of the screen */
function ReadBlock({ read }) {
  const g = T().guide
  if (!read) return null
  const asks = [['readFirst', read.first !== read.user && read.first !== read.prev ? read.first : null],
    ['readPrev', read.prev], ['readUser', read.user]].filter(([, v]) => v)
  return html`<div class="guide-read">
    ${asks.map(([k, v]) => html`<section key=${k}><h4 class="label-caps">${g[k]}</h4><p class="guide-read-text">${v}</p></section>`)}
    ${read.said ? html`<section><h4 class="label-caps">${read.source === 'screen' ? g.readScreen : g.readSaid}</h4>
      ${read.source === 'screen' ? html`<pre class="guide-read-text mono small">${read.said}</pre>` : html`<${Prose} text=${read.said} cls="guide-read-text" />`}
    </section>` : null}
  </div>`
}

/** The reading of one waiting tab as a tree; nothing while the guide is off or the tab does not wait.
 *  `compact` (a narrow column) leaves out the words a step would send; `bare` (a card of the Work through
 *  page, whose own To tab remembers the jump) leaves To tab and Watch to its host */
export function GuideTree({ tab, s, c, compact = false, bare = false }) {
  const t = T()
  const g = t.guide
  const { status, entry } = guideOf(s, tab)
  const [chosen, setChosen] = useState(null)        // the branch picked: its words wait in the box
  const [draft, setDraft] = useState('')
  const [open, setOpen] = useState(false)           // what was read, unfolded
  const [note, setNote] = useState(null)
  const box = useRef(null)
  const field = useRef(null)
  // a step just chosen: its box comes into view (in a scrolling pane it opens below the fold) and takes the cursor
  useEffect(() => {
    if (!chosen) return
    box.current?.scrollIntoView?.({ block: 'nearest' })
    field.current?.focus?.()
  }, [chosen])
  if (status === 'off') return null
  const busy = !!s.ui?.busy?.[tab.ref]
  const read = html`<${Btn} size="xs" variant="ghost" icon="reload" busy=${busy} onClick=${() => c.guideRead(tab.ref)}>
    ${status === 'none' ? g.read : g.again}<//>`
  const ways = html`<${Ways} tab=${tab} s=${s} c=${c} entry=${entry} open=${open} setOpen=${setOpen} bare=${bare} />`
  const readOut = open ? html`<${ReadBlock} read=${entry?.read} />` : null
  if (status === 'none') {
    return html`<div class="guide is-empty" role="group" aria-label=${g.title}>
      <p class="muted small guide-empty"><${Icon} name="spark" size=${12} /> ${g.noneYet}</p>${read}${ways}</div>`
  }
  if (status === 'running') {
    return html`<div class="guide is-running" role="group" aria-label=${g.title} aria-busy="true">
      <${About} entry=${entry} /><${Thinking} label=${g.reading} />${ways}${readOut}</div>`
  }
  if (status === 'error') {
    return html`<div class="guide is-error" role="group" aria-label=${g.title}>
      <${About} entry=${entry} />
      <p class="small"><${StateLine} token="danger" word=${g.failed(entry.error)} /></p>${read}${ways}${readOut}</div>`
  }
  const choices = status === 'fresh' ? guideChoices(tab, entry, s) : []
  // answering yourself: words into a waiting tab; a dialog takes no words, so there it opens the tab
  const ownBox = tab.state === 'waiting' && canTab(s, 'send')
  const current = chosen === 'own' ? { id: 'own', n: null, risky: false } : choices.find(x => x.id === chosen) ?? null
  const choose = ch => {
    setNote(null)
    if (chosen === ch.id) { setChosen(null); return }
    setChosen(ch.id)
    setDraft(ch.send ?? '')
  }
  const cancel = () => { setChosen(null); setDraft(''); setNote(null) }
  const send = async () => {
    if (!current) return
    let verb = current.verb
    let args = current.args
    if (current.n == null) {
      const v = draft.trim()
      if (!v) return
      ;({ verb, args } = replySend(tab, v))
    }
    setNote(null)
    const r = await c.reply(verb, args)
    if (r?.refused) { setNote(errorText(r.error, t)); return }
    if (!r?.ok) { if (r?.note) setNote(r.note); return }
    c.markAnswered?.(tab.ref, answerMark(tab, short(current.n == null ? draft.trim() : current.label, 40), Date.now()))
    cancel()
  }
  const boxId = `guide-box-${tab.ref}`
  const cost = entry.cost_usd == null ? null : centsText(entry.cost_usd * 100, language())
  const ago = duration((s.now || Date.now()) - (entry.at_ms ?? s.now ?? Date.now()))
  return html`<div class=${`guide${status === 'stale' ? ' is-stale' : ''}${compact ? ' is-compact' : ''}`} role="group" aria-label=${g.title}>
    <div class="guide-root">
      <${About} entry=${entry} />
      <span class="label-caps guide-cap"><${Icon} name="spark" size=${12} /> ${g.where}</span>
      <p class="guide-where">${entry.where}</p>
      ${entry.waits_for ? html`<p class="guide-waits small"><span class="muted">${g.waitsFor}</span> ${entry.waits_for}</p>` : null}
      ${status === 'stale' ? html`<p class="small"><${StateLine} token="warning" word=${g.stale} /></p>` : null}
    </div>
    <ul class="guide-branches">
      ${choices.map(ch => html`<li key=${ch.id} class=${`guide-branch${ch.picked ? ' is-picked' : ''}${ch.risky ? ' is-risky' : ''}${chosen === ch.id ? ' is-chosen' : ''}`}>
        <button type="button" class="guide-opt" disabled=${busy} aria-pressed=${String(chosen === ch.id)}
          title=${ch.send ? g.sends(ch.send) : g.presses(ch.n)} onClick=${() => choose(ch)}>
          <span class="guide-opt-head">
            <span class="guide-opt-label">${ch.label}</span>
            ${ch.picked ? html`<${Chip} token="info" cls="guide-chip">${g.picked}<//>` : null}
            ${ch.risky ? html`<${Chip} token="warning" cls="guide-chip">${g.risky}<//>` : null}
          </span>
          ${ch.why ? html`<span class="guide-why muted small">${ch.why}</span>` : null}
          ${ch.send && !compact ? html`<span class="guide-send mono small">${g.sends(short(ch.send, 120))}</span>` : null}
        </button>
      </li>`)}
      ${status === 'fresh' && !choices.length ? html`<li class="guide-branch is-none"><span class="muted small">${g.none}</span></li>` : null}
      <li class=${`guide-branch is-own${chosen === 'own' ? ' is-chosen' : ''}`}>
        <button type="button" class="guide-opt is-own" aria-pressed=${ownBox ? String(chosen === 'own') : undefined}
          onClick=${() => (ownBox ? choose({ id: 'own', send: '' }) : c.openTabView(tab.ref))}>
          <span class="guide-opt-label">${g.own}</span>
        </button>
      </li>
    </ul>
    ${current ? html`<div class="guide-compose" ref=${box}>
      ${current.risky ? html`<p class="small"><${StateLine} token="warning" word=${g.riskyNote} /></p>` : null}
      ${current.n != null ? html`<p class="small">${g.presses(current.n)}: <strong>${current.label}</strong></p>`
        : html`<label class="sr-only" for=${boxId}>${g.composeLabel}</label>
          <textarea id=${boxId} ref=${field} class="input guide-box" rows="3" maxlength=${TAB_MSG_MAX} value=${draft} placeholder=${g.composeLabel}
            onInput=${e => setDraft(e.currentTarget.value)}
            onKeyDown=${e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); send() } }}></textarea>`}
      ${tab.ask?.draft && current.n == null ? html`<p class="reply-draft muted small">${t.reply.draft}</p>` : null}
      <div class="btn-row">
        <${Btn} size="sm" variant="primary" icon="send" busy=${busy} disabled=${current.n == null && !draft.trim()} onClick=${send}>
          ${current.n != null ? g.press : g.send}<//>
        <${Btn} size="sm" variant="ghost" onClick=${cancel}>${g.cancel}<//>
      </div>
    </div>` : null}
    <footer class="guide-foot muted small">
      <span>${g.meta(g.source[entry.source] ?? '', cost, ago)}</span>
      <span class="guide-foot-tools">${ways}${read}</span>
    </footer>
    ${readOut}
    ${note ? html`<p class="reply-note small" role="status">${note}</p>` : null}
  </div>`
}

/** The reading in two lines, for the sidebar and a session card: what the session is about, then where
 *  it stands (or that Haiku reads); nothing otherwise */
export function GuideLine({ tab, s }) {
  const t = T()
  const { status, entry } = guideOf(s, tab)
  const about = entry?.about ? html`<span class="guide-line-about">${entry.about}</span>` : null
  if (status === 'running') {
    return html`<p class="guide-line small"><${Icon} name="spark" size=${12} /><span class="guide-line-text">${about}
      <span class="muted">${t.guide.reading}</span></span></p>`
  }
  if (status !== 'fresh' || !entry?.where) return null
  return html`<p class="guide-line small" title=${tab.ask?.text || entry.where}><${Icon} name="spark" size=${12} /><span class="guide-line-text">${about}
    <span class="guide-line-where clamp2">${entry.where}</span></span></p>`
}

/** The tabs the guide reads for you, the ones that need you first, the longest waiting first. A tab whose
 *  result is filed stays out: it waits only to be checked, and "With AI" offers that */
export function guideTabs(s) {
  if (!s.guide?.enabled) return []
  return (s.tabs?.tabs ?? []).filter(tab => !tab.filed_by && guideOf(s, tab).status !== 'off')
    .sort((a, b) => (URGENCY[a.state] ?? 2) - (URGENCY[b.state] ?? 2) || (a.since_ms ?? 0) - (b.since_ms ?? 0))
}

/** One tab with its reading: its state, name (a jump to it where the driver can), workspace, the tree */
export function GuideCard({ tab, s, c }) {
  const t = T()
  const jump = canTab(s, 'focus')
  return html`<article class="guide-card">
    <header class="guide-card-head">
      <${Dot} token=${stateToken(tabStateKey(tab))} />
      ${jump ? html`<button type="button" class="btn-link guide-card-name" onClick=${() => c.act('tab_jump', { tab_ref: tab.ref })}>${short(tab.name, 60)}</button>`
        : html`<span class="guide-card-name">${short(tab.name, 60)}</span>`}
      <span class="muted small">${tab.workspace}</span>
      <span class="muted small">${t.state[tabStateKey(tab)] ?? tab.state}</span>
    </header>
    <${GuideTree} tab=${tab} s=${s} c=${c} />
  </article>`
}

/** "Where you are needed" on top of the Sessions page: every tab that waits for you with its reading
 *  (guideTabs); nothing while the guide is off or no tab waits */
export function GuideBoard({ s, c }) {
  const t = T()
  const tabs = guideTabs(s)
  if (!tabs.length) return null
  return html`<section class="panel panel-pad psec guide-board" aria-labelledby="guide-board-title">
    <header class="psec-head">
      <h3 class="sec-title" id="guide-board-title">${t.guide.boardTitle} <span class="sec-count mono">${tabs.length}</span></h3>
      ${s.guide.auto ? null : html`<span class="muted small">${t.guide.manualHint}</span>`}
    </header>
    <p class="muted small guide-board-intro">${t.guide.boardIntro}</p>
    <div class="guide-board-list">${tabs.map(tab => html`<${GuideCard} key=${tab.ref} tab=${tab} s=${s} c=${c} />`)}</div>
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
