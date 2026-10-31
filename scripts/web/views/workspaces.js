// SPDX-License-Identifier: MIT
// The cockpit, the settings: the area Workspaces. Every area of this Bridge with a switch, its rules in one line, and
// for one with a file under workflow/workspaces/ Archive and Delete; a child stands under its parent.
// The rules every component keeps stand at the head of components.js.
//
// Off takes an area out of the bar, the chips and the shelf (areas.js areasOff). Nothing is deleted, nothing stops,
// and the line All still counts it. Delete asks a second click, and the server's refusal says what stops it.

import { html, useState } from '../vendor/htm-preact-3.1.1.module.js'
import { T } from '../text.js'
import { Btn, Chip } from './parts.js'
// a cycle (settings.js draws WorkspaceSettings): these parts are used only inside render functions
import { Card, Row, Switch } from './settings.js'

/** The rules of a workspace in one line; without a file it is a filter and nothing else */
export function ruleLine(it, t) {
  if (!it.id) return t.noFile
  return [t.level[it.level ?? 'view'], it.style, it.mail && t.mailProfile(it.mail), it.persona && t.persona(it.persona)]
    .filter(Boolean).join(', ')
}

/** Parents in the config's order, each followed by its children */
export function workspaceTree(items) {
  const live = (items ?? []).filter(i => !i.archived)
  const ids = new Set(live.map(i => i.id).filter(Boolean))
  return live.filter(i => !i.parent || !ids.has(i.parent)).flatMap(p => [p, ...live.filter(i => p.id && i.parent === p.id)])
}

function Item({ it, c, armed, arm }) {
  const t = T().workspaces
  const name = it.area ?? it.title
  const shut = () => { if (armed) { arm(null); c.workspaceDelete(it.id) } else arm(it.id) }
  return html`<div class=${`ws-item${it.parent ? ' is-child' : ''}`}>
    <${Row} label=${name} explain=${it.held_by ? t.heldBy(it.held_by) : ruleLine(it, t)}>
      <div class="btn-row">
        ${it.id ? html`<${Btn} variant="ghost" size="xs" onClick=${() => c.workspaceArchive(it.id)}>${t.archive}<//>
          <${Btn} variant=${armed ? 'danger' : 'ghost'} size="xs" onClick=${shut}>${armed ? t.deleteAgain : t.delete}<//>` : null}
        ${it.area ? html`<${Switch} on=${it.on && !it.held_by} disabled=${!!it.held_by} label=${t.switchLabel(name)}
          onChange=${on => c.workspaceSwitch(it.area, on)} />` : null}
      </div>
    <//>
  </div>`
}

/** The area Workspaces of the settings page */
export function WorkspaceSettings({ s, c }) {
  const t = T().workspaces
  const [armed, arm] = useState(null)
  const items = s.workspaces?.items ?? []
  const gone = items.filter(i => i.archived)
  return html`<${Card} title=${t.title} intro=${t.intro}>
    ${workspaceTree(items).map(it => html`<${Item} key=${it.id ?? it.area} it=${it} c=${c} armed=${!!it.id && armed === it.id} arm=${arm} />`)}
  <//>
  ${gone.length ? html`<${Card} title=${t.archived} intro=${t.archivedIntro}>
    ${gone.map(it => html`<${Row} key=${it.id} label=${it.area ?? it.title} explain=${ruleLine(it, t)} mark=${html` <${Chip}>${t.archivedMark}<//>`}>
      <${Btn} variant="secondary" size="xs" onClick=${() => c.workspaceRestore(it.id)}>${t.restore}<//>
    <//>`)}
  <//>` : null}`
}
