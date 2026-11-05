// SPDX-License-Identifier: MIT
// The cockpit, the workspaces: the picker in the header, and the area Workspaces of the settings: every area with
// two switches and Delete, a child under its parent.
// The rules every component keeps stand at the head of components.js.
//
// Active is the stronger switch: a resting workspace's rules no longer hold. Shown says whether it stands in the picker
// (areas.js areasOff). Neither deletes anything, nothing stops, and All still counts it. Delete says what it touches first (verb workspace_plan), and the default area has none.

import { html, useState } from '../vendor/htm-preact-3.1.1.module.js'
import { areaKey, areasOff, projectTone, workspacesOn } from '../logic.js'
import { T } from '../text.js'
import { Btn } from './parts.js'
// a cycle (settings.js draws WorkspaceSettings): these parts are used only inside render functions
import { Card, Row, Switch } from './settings.js'
import { Pop, usePop } from './termtools.js'

/** The rules of a workspace in one line; without a file it is a filter and nothing else */
export function ruleLine(it, t) {
  if (!it.id) return t.noFile
  return [t.level[it.level ?? 'view'], it.style, it.mail && t.mailProfile(it.mail), it.persona && t.persona(it.persona)]
    .filter(Boolean).join(', ')
}

/** Parents in the config's order, each followed by its children */
export function workspaceTree(items) {
  const all = items ?? []
  const ids = new Set(all.map(i => i.id).filter(Boolean))
  return all.filter(i => !i.parent || !ids.has(i.parent)).flatMap(p => [p, ...all.filter(i => p.id && i.parent === p.id)])
}

/** What the picker offers: the active and shown workspaces with an area of their own */
export function pickable(s) {
  const away = areasOff(s)
  return workspaceTree(s.workspaces?.items).filter(i => i.area && !away.has(areaKey(i.area)))
}

/** The picker in the header: the area the whole cockpit shows, on every page */
export function WorkspacePicker({ s, c }) {
  const t = T().workspaces
  const { pop, open, close } = usePop()
  const items = pickable(s)
  if (!items.length || !workspacesOn(s)) return null
  const pick = area => { close(); c.setArea(area) }
  const dot = name => html`<span class=${`home-area-dot tk-${projectTone(name)}`} aria-hidden="true"></span>`
  return html`<div class="hdr-pick">
    <button type="button" class="btn btn-secondary btn-sm" aria-haspopup="menu" aria-expanded=${String(!!pop)} onClick=${open('ws')}>
      ${s.ui.area ? dot(s.ui.area) : null}<span>${s.ui.area ?? t.all}</span> <span aria-hidden="true">▾</span></button>
    ${pop ? html`<${Pop} at=${pop.at} onClose=${close}>
      <button type="button" class="pop-item" onClick=${() => pick(null)}>${t.all}</button>
      ${items.map(it => html`<button type="button" key=${it.key} class=${`pop-item${it.parent ? ' is-child' : ''}`} onClick=${() => pick(it.area)}>
        ${dot(it.area)}<span>${it.area}</span></button>`)}
    <//>` : null}
  </div>`
}

/** What a delete touches, in words, with the last button; what stops it instead of that button */
function DeleteAsk({ plan, it, c, done }) {
  const t = T().workspaces
  const stop = plan.fixed ? t.stopFixed : plan.tabs ? t.stopTabs(plan.tabs) : plan.children.length ? t.stopChildren(plan.children.join(', ')) : null
  return html`<div class="ws-ask" role="group" aria-label=${t.delete}>
    <p class="small">${stop ?? t.touches(plan.tasks, plan.records)}</p>
    <div class="btn-row">
      ${stop ? null : html`<${Btn} variant="danger" size="xs" onClick=${() => { done(); c.workspaceDelete(it.key) }}>${t.deleteForGood}<//>`}
      <${Btn} variant="ghost" size="xs" onClick=${done}>${t.cancel}<//>
    </div>
  </div>`
}

function Item({ it, s, c, ask, setAsk }) {
  const t = T().workspaces
  const name = it.area ?? it.title
  const asleep = (s.workspaces?.inactive ?? []).includes(it.key)
  const held = it.active_held_by ?? null
  const shown = held ? t.heldBy(held) : it.held_by ? t.heldBy(it.held_by) : asleep ? t.resting : ruleLine(it, t)
  const plan = async () => { const r = await c.workspacePlan(it.key); if (r?.plan) setAsk(r.plan) }
  return html`<div class=${`ws-item${it.parent ? ' is-child' : ''}`}>
    <${Row} label=${name} explain=${shown}>
      <div class="btn-row ws-tools">
        <label class="ws-switch"><span class="muted small">${t.active}</span>
          <${Switch} on=${!asleep} disabled=${!!held} label=${t.activeLabel(name)} onChange=${on => c.workspaceActive(it.key, on)} /></label>
        ${it.area ? html`<label class="ws-switch"><span class="muted small">${t.shown}</span>
          <${Switch} on=${it.on && !it.held_by && !asleep} disabled=${!!it.held_by || asleep} label=${t.shownLabel(name)}
            onChange=${on => c.workspaceSwitch(it.area, on)} /></label>` : null}
        ${it.fixed ? html`<span class="muted small">${t.fixed}</span>`
          : html`<${Btn} variant="ghost" size="xs" onClick=${plan}>${t.delete}<//>`}
      </div>
    <//>
    ${ask ? html`<${DeleteAsk} plan=${ask} it=${it} c=${c} done=${() => setAsk(null)} />` : null}
  </div>`
}

/** The area Workspaces of the settings page */
export function WorkspaceSettings({ s, c }) {
  const t = T().workspaces
  const [ask, setAsk] = useState(null)
  const on = workspacesOn(s)
  const head = html`<${Switch} on=${on} label=${t.mainLabel} onChange=${c.workspacesEnabled} />`
  if (!on) return html`<${Card} title=${t.title} intro=${t.mainOff} head=${head} off />`
  return html`<${Card} title=${t.title} intro=${t.intro} head=${head}>
    ${workspaceTree(s.workspaces?.items).map(it => html`<${Item} key=${it.key} it=${it} s=${s} c=${c}
      ask=${ask?.key === it.key ? ask : null} setAsk=${setAsk} />`)}
  <//>`
}
