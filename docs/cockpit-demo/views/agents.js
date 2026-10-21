// SPDX-License-Identifier: MIT
// The cockpit, the A2A agents page.
// The rules every component keeps stand at the head of components.js.

import { html, useEffect, useState } from '../vendor/htm-preact-3.1.1.module.js'
import { short, chatStamp, listedChats, a2aTrouble, a2aHost } from '../logic.js'
import { T, language } from '../text.js'
import { SendBox, Thinking, useStickToEnd } from './chat.js'
import { Btn, Dot, Icon, StateLine, useRoving } from './parts.js'
import { Prose } from './prose.js'

// ---------------------------------------------------------------- A2A agents

const REACH_TONE = { ok: 'ok', refused: 'bad', failed: 'bad', unreachable: 'warn', unknown: 'dim' }

/** One agent as a card: who it is from its card, what it may do, whether the last call went through */
function AgentCard({ p, on, c, s, held = 0 }) {
  const t = T()
  const card = p.card ?? {}
  const tone = REACH_TONE[p.reach] ?? 'dim'
  return html`<button type="button" class=${`agent-card rt-${tone}${on ? ' is-on' : ''}`} onClick=${() => c.pickAgent(p.id)}
    aria-current=${on ? 'true' : undefined}>
    <span class="agent-head"><span class=${`rdot rdot-${tone}`} aria-hidden="true"></span>
      <span class="agent-name" title=${card.name || p.id}>${card.name || p.id}</span></span>
    <span class="agent-id mono small muted">${p.id}</span>
    <span class="agent-sum">${p.summary || card.description}</span>
    <span class="agent-meta small">
      ${p.reach !== 'ok' ? html`<span class=${`agent-reach is-${tone}`}>${t.agentReach[p.reach] ?? p.reach}</span>` : null}
      ${held ? html`<span class="agent-reach is-warn">${t.agentHeld(held)}</span>` : null}
      ${p.last_ms ? html`<span class="muted">${t.agentLast(chatStamp(p.last_ms, s.now, language()))}</span>` : null}
    </span>
  </button>`
}

/** The agent above its conversation: who it is, whether it is reachable, what failed, and the button that
 *  opens its card. It stays when the card is folded away, so a failure is seen without opening it */
function AgentBar({ p, open, onToggle, listToggle }) {
  const t = T()
  const tone = REACH_TONE[p.reach] ?? 'dim'
  const card = p.card ?? {}
  const troubles = [p.card_error && t.agentTroubleWhere.card, p.last_error && t.agentTroubleWhere.send].filter(Boolean)
  return html`<header class=${`agent-bar rt-${tone}`}>
    ${listToggle}
    <span class=${`rdot rdot-${tone}`} aria-hidden="true"></span>
    <span class="agent-bar-who">
      <strong class="agent-bar-name" title=${p.id}>${card.name || p.id}</strong>
      <span class="agent-bar-sub small muted">${p.id}${p.reach !== 'ok' && !troubles.length ? ` · ${t.agentReach[p.reach] ?? p.reach}` : ''}</span>
    </span>
    ${troubles.map(x => html`<span key=${x} class="agent-reach is-warn small">${x}</span>`)}
    <button type="button" class=${`btn btn-${open ? 'primary' : 'secondary'} btn-sm agent-bar-card`} aria-expanded=${String(open)}
      aria-controls="agent-profile" onClick=${onToggle}><${Icon} name=${open ? 'chevronUp' : 'chevronDown'} /><span class="btn-label">${open ? t.agentCardHide : t.agentCardShow}</span></button>
  </header>`
}

/** What went wrong reaching an agent, in plain words: which step (`where`: reading its card, delivering
 *  the last message), the reason (logic.js a2aTrouble), what to do about it, and the raw text folded away */
function AgentTrouble({ p, where, err }) {
  const t = T()
  const kind = a2aTrouble(err)
  const why = t.agentTrouble[kind] ?? t.agentTrouble.other
  const x = { id: p.id, host: a2aHost(p.card?.endpoint || p.card_url) || p.id, owner: p.owner || t.agentOwnerFallback, tailnet: p.network === 'tailnet' }
  return html`<div class=${`agent-trouble is-${where === 'send' ? 'danger' : 'warning'}`} role="status">
    <${StateLine} token=${where === 'send' ? 'danger' : 'warning'} strong word=${`${t.agentTroubleWhere[where]}: ${why.title}`} />
    <p class="agent-trouble-hint">${why.hint(x)}</p>
    <details class="agent-trouble-raw"><summary class="muted small">${t.agentTroubleDetail}</summary><code class="mono small">${err}</code></details>
  </div>`
}

/** The agent's card as a profile: who and which version, where and how it is reached, what it takes
 *  and gives, its skills with their whole description and examples; an example fills the message box.
 *  Without a readable card it still says what the peer file knows, why the card is missing, and offers
 *  to check again */
function AgentProfile({ p, onExample, c, s }) {
  const t = T()
  const card = p.card ?? {}
  const [skill, setSkill] = useState(null)
  const [checking, setChecking] = useState(false)
  const facts = [
    [t.agentFact.version, card.version], [t.agentFact.protocol, [card.binding, card.protocol && `A2A ${card.protocol}`].filter(Boolean).join(' · ')],
    [t.agentFact.provider, card.provider?.name], [t.agentFact.endpoint, card.endpoint],
    [t.agentFact.card, p.card ? null : p.card_url],
    [t.agentFact.access, [p.needs_token ? t.agentToken : t.agentOpen, p.network ? t.agentNet[p.network] ?? p.network : null].filter(Boolean).join(' · ')],
    [t.agentFact.modes, card.input?.length ? `${card.input.join(', ')} → ${(card.output ?? []).join(', ')}` : null],
    [t.agentFact.gate, p.usage?.human_gate], [t.agentFact.allowed, p.usage?.allowed?.length ? p.usage.allowed.map(x => t.agentModes[x] ?? x).join(', ') : null],
    [t.agentFact.owner, p.owner],
  ].filter(([, v]) => v)
  const mono = new Set([t.agentFact.endpoint, t.agentFact.card])
  const recheck = async () => {
    setChecking(true)
    try { await c.loadAgents(true) } finally { setTimeout(() => setChecking(false), 1500) }
  }
  return html`<div class="agent-profile row-in" id="agent-profile">
    <header class="agent-profile-head">
      <div><h3 class="agent-profile-name">${card.name || p.id}</h3>
        ${card.description || p.summary ? html`<p class="agent-profile-desc">${card.description || p.summary}</p>` : null}</div>
      <span class="btn-row">
        ${p.card_at_ms ? html`<span class="muted small">${t.agentChecked(chatStamp(p.card_at_ms, s.now, language()))}</span>` : null}
        <${Btn} size="xs" variant="secondary" icon="reload" busy=${checking} onClick=${recheck}>${t.agentRecheck}<//>
        ${card.streaming ? html`<span class="chip">${t.agentStreaming}</span>` : null}
        ${card.docs ? html`<a class="btn btn-ghost btn-xs" href=${card.docs} target="_blank" rel="noopener noreferrer"><${Icon} name="external" size=${13} /><span class="btn-label">${t.agentDocs}</span></a>` : null}
      </span>
    </header>
    ${p.card_error ? html`<${AgentTrouble} p=${p} where="card" err=${p.card_error} />` : null}
    ${p.last_error ? html`<${AgentTrouble} p=${p} where="send" err=${p.last_error} />` : null}
    ${!p.card && !p.card_error ? html`<p class="muted small">${t.agentNoCard}</p>` : null}
    <dl class="agent-facts">${facts.map(([k, v]) => html`<div key=${k}><dt>${k}</dt><dd class=${mono.has(k) ? 'mono' : ''}>${v}</dd></div>`)}</dl>
    ${card.skills?.length ? html`<h4 class="label-caps">${t.agentSkills(card.skills.length)}</h4>
      <ul class="agent-skill-cards">${card.skills.map((k, i) => {
        const open = skill === i
        return html`<li key=${k.id || k.name} class=${`agent-skill${open ? ' is-open' : ''}`}>
          <button type="button" class="agent-skill-head" aria-expanded=${String(open)} onClick=${() => setSkill(open ? null : i)}>
            <strong>${k.name}</strong>${k.tags?.length ? html`<span class="agent-tags">${k.tags.map(x => html`<span key=${x} class="chip">${x}</span>`)}</span>` : null}
            <span class="agent-skill-chev" aria-hidden="true">${open ? '▾' : '▸'}</span></button>
          <p class=${`agent-skill-desc${open ? '' : ' is-clamped'}`}>${k.description}</p>
          ${open && k.examples?.length ? html`<div class="agent-examples"><span class="muted small">${t.agentExamples}</span>
            ${k.examples.map(x => html`<button type="button" key=${x} class="fchip" onClick=${() => onExample(x)}>${x}</button>`)}</div>` : null}
        </li>`
      })}</ul>` : null}
  </div>`
}

/** A conversation with one agent: question or task, sent only on a click; a held answer waits for the
 *  agent's owner, is looked at again every minute by the server, and on a click */
function AgentThread({ conv, peer, c, s }) {
  const t = T()
  return conv.turns.map((x, i) => {
    const last = i === conv.turns.length - 1
    return html`<div class="qturn row-in" key=${i} style=${{ '--i': 0 }}>
      <div class="qq">${x.mode === 'task' ? html`<span class="chip agent-mode">${t.agentModes.task}</span> ` : null}${x.q}</div>
      ${x.a && !x.waiting ? html`<${Prose} cls="qa" text=${x.a} />` : null}
      ${x.error ? html`<p title=${x.error}><${StateLine} token="danger" word=${x.error === 'interrupted' ? t.quickInterrupted
        : t.agentFailed((t.agentTrouble[a2aTrouble(x.error)] ?? t.agentTrouble.other).title)} /></p>` : null}
      ${last && conv.running ? html`<div class="qdoing"><${Thinking} label=${x.waiting ? t.agentLooking : t.agentSent} /></div>` : null}
      ${last && !conv.running && x.waiting ? html`<div class="agent-held">
        <${StateLine} token="warning" strong word=${t.agentWaiting} />
        ${x.a ? html`<p class="muted small">${x.a}</p>` : null}
        ${peer?.usage?.human_gate ? html`<p class="small">${t.agentWhereGate(peer.usage.human_gate)}</p>` : null}
        <p class="btn-row">
          <${Btn} size="xs" variant="secondary" busy=${!!s.ui.busy[`quick:${conv.id}`]} onClick=${() => c.agentPoll(conv.id)}>${t.agentPoll}<//></p>
      </div>` : null}
    </div>`
  })
}

/** The page of the A2A agents; `embedded` (the chat as cmux) shows one agent without the page head and the list */
export function AgentsPage({ s, c, embedded = false }) {
  const t = T()
  const lang = language()
  const a = s.agents ?? {}
  const peers = a.peers ?? []
  // the conversations the lists show: none untouched past keep_hours, the way the chats leave (agents.py expire)
  const convs = listedChats(a.convs, a.keep_hours, s.now)
  const conv = (a.convs ?? []).find(x => x.id === s.ui.agentConv) ?? null
  const peerId = conv?.peer ?? s.ui.agentPeer ?? peers[0]?.id
  const peer = peers.find(p => p.id === peerId) ?? peers[0]
  const mine = convs.filter(x => x.peer === peer?.id)
  const [text, setText] = useState('')
  // the card: open by itself while no conversation is open, folded under one; the bar's button decides otherwise
  const [profile, setProfile] = useState(null)
  const [forgetArmed, setForgetArmed] = useState(null)
  const body = useStickToEnd(conv, null)
  const modeKeys = useRoving()
  useEffect(() => { c.loadAgents() }, [])
  // a draft belongs to the agent it was written for: switching agents never carries it over
  useEffect(() => { setProfile(null); setText('') }, [peer?.id])
  const mode = s.ui.agentMode
  const send = async () => {
    const v = text.trim()
    if (!v || !peer || conv?.running) return
    if (await c.agentSend(peer.id, v, mode, conv?.id)) setText('')
  }
  const example = v => { setText(v); document.getElementById('agent-input')?.focus() }
  const showProfile = profile ?? !conv
  const listHidden = embedded || !!s.ui.agentsListHidden
  return html`<div class=${embedded ? 'agentspage is-embedded' : 'col col-page agentspage'}>
    ${embedded ? null : html`<header class="page-head"><h2 class="detail-title">${t.agentsTab}</h2>
      <span class="muted small">${t.agentsIntro}</span></header>`}
    <div class=${`agents-grid${listHidden ? ' is-wide' : ''}`}>
      ${listHidden ? null : html`<nav class="agents-list" id="agents-list" aria-label=${t.agentsTab}>
        ${peers.map(p => html`<${AgentCard} key=${p.id} p=${p} on=${p.id === peer?.id} c=${c} s=${s}
          held=${convs.filter(x => x.peer === p.id && !x.running && x.turns.at(-1)?.waiting).length} />`)}
      </nav>`}
      <section class="panel chat-main" aria-label=${peer?.card?.name || peer?.id}>
        ${peer ? html`<${AgentBar} p=${peer} open=${showProfile} onToggle=${() => setProfile(!showProfile)}
          listToggle=${embedded ? null : html`<button type="button" class="btn btn-ghost btn-xs agents-list-toggle" aria-expanded=${String(!listHidden)} aria-controls="agents-list"
            title=${listHidden ? t.agentsListShow : t.agentsListHide} aria-label=${listHidden ? t.agentsListShow : t.agentsListHide}
            onClick=${c.toggleAgentsList}><${Icon} name=${listHidden ? 'chevronRight' : 'back'} /></button>`} />` : null}
        <header class="agent-convs">
          <button type="button" class=${`chip quick-conv${!conv ? ' is-on' : ''}`} onClick=${() => c.newAgentChat(peer.id)}>+ ${t.quickNew}</button>
          ${mine.slice(0, 8).map(x => html`<button type="button" key=${x.id} class=${`chip quick-conv${x.id === conv?.id ? ' is-on' : ''}`}
            onClick=${() => c.pickAgentConv(x.id)} title=${x.turns[0]?.q}>${x.running ? html`<${Dot} token="info" pulse /> `
              : x.turns.at(-1)?.waiting ? html`<${Dot} token="warning" /> ` : null}${short(x.turns[0]?.q ?? '', 36)}
            <span class="muted"> · ${chatStamp(x.last_ms ?? x.started_ms, s.now, lang)}</span></button>`)}
          ${conv && !conv.running ? html`<button type="button" class=${`chip quick-conv agent-forget${forgetArmed === conv.id ? ' is-armed' : ''}`}
            title=${t.agentForgetHint} onBlur=${() => setForgetArmed(null)}
            onClick=${() => forgetArmed === conv.id ? c.agentForget(conv.id) : setForgetArmed(conv.id)}>${forgetArmed === conv.id ? t.agentForgetSure : t.agentForget}</button>` : null}
        </header>
        <div class="tabview-body quick-body" ref=${body} tabindex="-1" role="log" aria-label=${t.quickHistory}>
          ${peer && showProfile ? html`<${AgentProfile} key=${peer.id} p=${peer} onExample=${example} c=${c} s=${s} />` : null}
          ${conv ? html`<${AgentThread} conv=${conv} peer=${peer} c=${c} s=${s} />` : null}
        </div>
        <footer class="tabview-foot">
          <div class="btn-row agent-modes" role="radiogroup" aria-label=${t.agentModeLabel} ref=${modeKeys.ref} onKeyDown=${modeKeys.onKeyDown}>
            ${['question', 'task'].map(m => html`<button type="button" role="radio" key=${m} aria-checked=${String(mode === m)}
              class=${`fchip${mode === m ? ' is-on' : ''}`} onClick=${() => c.setAgentMode(m)}>${t.agentModes[m]}</button>`)}
            <span class="muted small">${t.agentModeHint[mode]}</span>
          </div>
          <${SendBox} id="agent-input" label=${t.agentSendLabel} value=${text} setValue=${setText} onSend=${send} max=${4000}
            placeholder=${t.agentPlaceholder(peer?.card?.name || peer?.id || '')} busy=${!!s.ui.busy[conv ? `quick:${conv.id}` : 'a2a_ask']}
            disabled=${!!conv?.running || !peer} sendLabel=${t.agentSendBtn} autofocus=${false} />
        </footer>
      </section>
    </div>
  </div>`
}
