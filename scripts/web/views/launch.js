// SPDX-License-Identifier: MIT
// The cockpit, the model an agent tab starts with: the one picker every start block shows.
// The rules every component keeps stand at the head of components.js.

import { html, useEffect } from '../vendor/htm-preact-3.1.1.module.js'
import { launchChoice, launchOptions, routeText } from '../logic.js'
import { T, language } from '../text.js'
import { Segmented } from './detail.js'
import { Chip } from './parts.js'

/** Model and effort for the next start, beside the start buttons. One choice for every block (ui.launchModel,
 *  ui.launchEffort); app.js act() sends it along with every start verb. `items` are the rows the block starts
 *  ({ key, title }): with Auto chosen and one row in view, its recommendation is fetched once and shown.
 *  Nothing at all while launch is off or the server does not know it */
export function LaunchPick({ s, c, items = [] }) {
  const opts = launchOptions(s.launch)
  const choice = launchChoice(s.launch, s.ui)
  const one = items.length === 1 ? items[0] : null
  const wantsRoute = !!opts && choice.model === 'auto' && !!one
  useEffect(() => {
    if (wantsRoute) c.launchRoute([one])
  }, [wantsRoute, one?.key, one?.title])
  if (!opts) return null
  if (!opts.models.length && !opts.efforts.length) return null
  const t = T()
  const w = t.launch
  const hit = wantsRoute ? s.launchRoutes?.[one.key] : null
  const note = choice.model !== 'auto' ? null
    : items.length > 1 ? html`<span class="muted small">${w.autoEach}</span>`
    : hit?.status === 'loading' ? html`<span class="muted small launch-wait">${w.routing}</span>`
    : hit?.status === 'ok' ? html`<span class="muted small launch-rec" title=${hit.route.why || undefined}>${routeText(hit.route, t, language())}</span>`
    : null
  return html`<div class="launch-pick">
    ${opts.models.length === 0 ? null : opts.readOnly
      ? html`<${Chip} title=${w.readOnlyTitle}>${w.label}: ${w.model.auto}<//>`
      : html`<span class="muted small">${w.label}</span><${Segmented} label=${w.label} current=${choice.model} values=${opts.models.map(m => [m, w.model[m] ?? m])}
          onPick=${m => c.setLaunchModel(m)} />`}
    ${opts.efforts.length ? html`<span class="muted small">${w.effortLabel}</span><${Segmented} label=${w.effortLabel} current=${choice.effort}
      values=${opts.efforts.map(e => [e, w.effort[e] ?? e])} onPick=${e => c.setLaunchEffort(e)} />` : null}
    ${note}
  </div>`
}
