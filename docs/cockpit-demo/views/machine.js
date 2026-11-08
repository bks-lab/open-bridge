// SPDX-License-Identifier: MIT
// The cockpit, the area On this machine of the settings: every page of the briefing profile, a sub page under its
// folder, and under each page its sections, each with a switch. Kept on this machine only (views.py, views.json).
// The rules every component keeps stand at the head of components.js.
//
// A section switched off is not collected at all and stands nowhere; a page switched off has no tab and no place in
// its folder; a page whose sections are all off goes the same way. The list is the catalog the last collect sent, so
// what is off still stands here to come back on.

import { html } from '../vendor/htm-preact-3.1.1.module.js'
import { machineTree } from '../logic.js'
import { T } from '../text.js'
import { Empty } from './parts.js'
// a cycle (settings.js draws MachineSettings): these parts are used only inside render functions
import { Card, Row, Switch } from './settings.js'

// the kinds the briefing page shows itself: off here, the briefing loses them too (briefing_view.BRIEFING_KINDS)
const BRIEFING_KINDS = ['inbox', 'advise', 'tasks']

function PageItem({ p, v, c }) {
  const t = T().machine
  const pagesOff = new Set(v.pages_off ?? [])
  const sectionsOff = new Set(v.sections_off ?? [])
  const heldBy = p.under && pagesOff.has(p.under) ? p.under : null
  const on = !pagesOff.has(p.id) && !heldBy
  const allOff = (p.sections ?? []).length > 0 && p.sections.every(x => sectionsOff.has(x.id))
  const explain = heldBy ? t.heldBy(p.parentTitle ?? heldBy) : !on ? t.pageOff : allOff ? t.allOff : p.under ? t.inFolder(p.parentTitle ?? p.under) : null
  return html`<div class=${`mc-page${p.under ? ' is-child' : ''}`}>
    <${Row} label=${p.title} explain=${explain}>
      <${Switch} on=${on} disabled=${!!heldBy} label=${t.pageLabel(p.title)} onChange=${x => c.viewSwitch('page', p.id, x)} />
    <//>
    ${on ? html`<div class="mc-sections">${(p.sections ?? []).map(x => html`<${Row} key=${x.id} label=${x.title}
        explain=${BRIEFING_KINDS.includes(x.kind) ? t.briefingToo : null}>
      <${Switch} on=${!sectionsOff.has(x.id)} label=${t.sectionLabel(x.title)} onChange=${y => c.viewSwitch('section', x.id, y)} />
    <//>`)}</div>` : null}
  </div>`
}

/** The area On this machine of the settings page */
export function MachineSettings({ s, c }) {
  const t = T().machine
  const v = s.views
  const pages = machineTree(v?.catalog)
  return html`<${Card} title=${t.title} intro=${t.intro} head=${html`<span class="muted small">${t.here}</span>`}>
    ${!v ? html`<${Empty}>${t.older}<//>` : !pages.length ? html`<${Empty}>${t.none}<//>`
      : pages.map(p => html`<${PageItem} key=${p.id} p=${p} v=${v} c=${c} />`)}
  <//>`
}
