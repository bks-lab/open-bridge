// SPDX-License-Identifier: MIT
// The cockpit, profile pages: sections, tiles, mosaic, the overview board, a folder's machines, a sub page's head
// card, the Jev order.
// The rules every component keeps stand at the head of components.js.

import { html, useEffect, useState } from '../vendor/htm-preact-3.1.1.module.js'
import {
  indexRows, stateToken, toneToken, gaugeArc, gaugeBands, gaugePoint, gaugeSection, meterScale, meterText,
  meterView, TONE_FILTERS, FILTER_TONE, actionRow, filterRows, groupRows, tagFacets, toneFilter, detailText,
  sectionStamp, triageKey, triageShows, sectionTile, jobCounts, machineLines, pageSummary, short, tokenText, usageToday, tabStateKey,
  jevList, TASK_LANES, taskLane, noiseRows, rowActionKey,
  skipFixable, skipText,
  cardPlan, moneyText, costBoard, itemRow, ghFiltered, ghMyLogin,
} from '../logic.js'
import { reducedMotion } from '../motion.js'
import { T, language } from '../text.js'
import { TriageGist } from '../triage.js'
import { KindTag, OriginTag, PageItemActions, RowBar } from './day.js'
import { Lines } from './detail.js'
import { ReturnChip } from './home.js'
import { rowClickOpens, useFocusOnOpen } from './overlays.js'
import { Btn, SkipFix, Chip, Dot, Empty, Icon, MarkChip, PrioChip, StateLine, VerdictChip, usePopover, useRoving, useTween } from './parts.js'
import { GitHubBoard, GitHubList, ghShows } from './github.js'
import { WORKERS_PAGE, folderOf, subPagesOf } from './nav.js'
import { DatesAgenda } from './dates.js'
import { CostCard, UsageCard } from './costs.js'

// ---------------------------------------------------------------- pages

/** A row's gauge: the fill grows to its value, a thin mark shows how much of the time window has passed,
 *  and when the value runs ahead of the time it says so in words */
export function MeterBar({ meter, scale, tone }) {
  const t = T()
  const lang = language()
  const v = meterView(meter, scale)
  const frac = useTween(v.frac, { start: 0 })
  const shown = useTween(meter.value, { start: 0 })
  const fill = tone === 'bad' ? 'danger' : tone === 'warn' ? 'warning' : v.relative ? 'secondary' : 'info'
  return html`<div class="meter">
    <span class="meter-track" aria-hidden="true">
      <span class=${`meter-fill tk-${fill}`} style=${{ transform: `scaleX(${Math.max(0, frac).toFixed(4)})` }}></span>
      ${v.pace != null ? html`<span class="meter-pace" style=${{ '--p': v.pace.toFixed(4) }}></span>` : null}
    </span>
    <span class="meter-text num">${meterText(meter, shown, lang)}</span>
    ${v.pace != null ? html`<span class="muted small">${t.meterPace(Math.round(v.pace * 100))}</span>` : null}
    ${v.ahead ? html`<${StateLine} token="warning" word=${t.meterAhead} />` : null}
  </div>`
}

/** A half-circle gauge (DESIGN.md tokens): the source's ranges as an outer ring, the value as the inner
 *  arc, a needle where the time window stands. The number and the words below carry the state, the color
 *  only repeats it */
function Gauge({ meter, label }) {
  const lang = language()
  const f = useTween(Math.min(1, meter.value / meter.max), { start: 0 })
  const shown = useTween(meter.value, { start: 0 })
  const bands = gaugeBands(meter)
  const token = meter.bad != null && meter.value >= meter.bad ? 'danger'
    : meter.warn != null && meter.value >= meter.warn ? 'warning' : 'secondary'
  const mark = (x, r0, r1) => { const [a, b] = gaugePoint(x, r0); const [c2, d] = gaugePoint(x, r1); return { x1: a, y1: b, x2: c2, y2: d } }
  const tick = (x, text) => {
    const [tx, ty] = gaugePoint(x, 104)
    const end = x <= 0.001 || x >= 0.999
    return html`<text x=${(end ? (x < 0.5 ? 10 : 190) : tx).toFixed(1)} y=${(end ? 116 : Math.min(108, ty + 3)).toFixed(1)} class="g-label"
      text-anchor=${end ? 'middle' : x < 0.4 ? 'end' : x > 0.6 ? 'start' : 'middle'}>${text}</text>`
  }
  const unit = meter.unit === '%' ? ' %' : ''
  return html`<svg class="gauge" viewBox="-26 0 252 120" role="img" aria-label=${label}>
    ${bands.length ? bands.map(b => html`<path key=${b.token} d=${gaugeArc(b.from, b.to, 90)} class=${`g-band tk-${b.token}`} />`)
      : html`<path d=${gaugeArc(0, 1, 90)} class="g-band g-band-none" />`}
    <path d=${gaugeArc(0, 1, 72)} class="g-track" />
    ${f > 0.002 ? html`<path d=${gaugeArc(0, f, 72)} class=${`g-value tk-${token}`} />` : null}
    ${meter.elapsed != null ? html`<line ...${mark(meter.elapsed, 56, 96)} class="g-pace" />` : null}
    ${tick(0, `0${unit}`)}
    ${meter.warn != null ? tick(meter.warn / meter.max, `${Math.round(meter.warn)}${unit}`) : null}
    ${meter.bad != null ? tick(meter.bad / meter.max, `${Math.round(meter.bad)}${unit}`) : null}
    ${tick(1, `${Math.round(meter.max)}${unit}`)}
    <text x="100" y="96" text-anchor="middle" class="g-num">${meter.unit
      ? meterText(meter, shown, lang).replace(' %', '\u202f%') : String(Math.round(shown))}</text>
  </svg>`
}

/** A section of gauges as tiles: title, the gauge, when it resets, how much time has passed */
function GaugeTile({ it, page, section, c }) {
  const t = T()
  const v = meterView(it.meter, 0)
  const title = it.title.replace(/:\s*[\d.,]+\s*%?\s*$/, '')
  return html`<li class="gtile card-opens" tabindex="0" onClick=${e => { if (rowClickOpens(e)) c.openInfo(it, page, section) }}
    onKeyDown=${e => { if (e.key === 'Enter' && e.target === e.currentTarget) { e.preventDefault(); c.openInfo(it, page, section) } }}>
    <h3 class="gtile-title">${it.tone ? html`<${StateLine} token=${toneToken(it.tone)} strong=${it.tone === 'bad'} word=${title} />` : title}</h3>
    <${Gauge} meter=${it.meter} label=${it.title} />
    <div class="gtile-foot small">
      ${it.when ? html`<span class="muted">${t.gaugeResets(it.when)}</span>` : null}
      ${v.pace != null ? html`<span class="muted">${t.meterPace(Math.round(v.pace * 100))}</span>` : null}
      ${v.pace != null ? html`<${StateLine} token=${v.ahead ? 'warning' : 'success'} word=${v.ahead ? t.meterAhead : t.meterOnPace} />` : null}
    </div>
    ${it.ask ? html`<div class="btn-row"><${Btn} size="xs" variant="ghost" onClick=${() => c.ask('info', { page, section, index: it.index })}>${t.btnAsk}<//></div>` : null}
  </li>`
}

/** A command row's own steps (an application: followed up, turned down, ...) in two clicks; each is
 *  run by its section's command and can be taken back from the toast or the history. `as="buttons"`
 *  (a section's `steps: buttons`) sets every step out as a button of its own: the first click arms it,
 *  the second runs it, and an armed button falls back after a few seconds. `head` (a GitHub row's lead
 *  step or To tab, views/github.js) makes it one split button: the head left, ▾ with these steps */
export function RowSteps({ it, page, section, s, c, as = 'menu', head = null }) {
  const t = T()
  const [open, setOpen] = useState(false)
  const [armed, setArmed] = useState(null)
  const box = usePopover(open, setOpen)
  const busy = !!s.ui.busy[rowActionKey({ page, section, index: it.index })]
  const pick = action => { setOpen(false); setArmed(null); c.act('row_action', { page, section, index: it.index, action }) }
  useEffect(() => {
    if (!armed) return undefined
    const id = setTimeout(() => setArmed(null), 4000)
    return () => clearTimeout(id)
  }, [armed])
  if (as === 'buttons') {
    return html`<span class="btn-row row-step-buttons">${it.actions.map(a => html`<${Btn} key=${a.id} size="xs"
      variant=${armed === a.id ? 'primary' : 'secondary'} busy=${busy} pressed=${armed === a.id}
      title=${armed === a.id ? t.stepConfirmTitle : undefined}
      onClick=${() => (armed === a.id ? pick(a.id) : setArmed(a.id))}>${armed === a.id ? t.stepConfirm(a.label) : a.label}<//>`)}</span>`
  }
  return html`<span class="settle" ref=${box}>
    ${head ? html`<span class="btn-split">${head}<${Btn} size="xs" variant="primary" busy=${busy} pressed=${open} title=${t.rowStepsTitle}
        label=${t.rowStepsMore} onClick=${() => setOpen(!open)}>▾<//></span>`
      : html`<${Btn} size="xs" variant="ghost" busy=${busy} pressed=${open} title=${t.rowStepsTitle} onClick=${() => setOpen(!open)}>${t.rowSteps} ▾<//>`}
    ${open ? html`<span class="settle-menu" role="menu">${it.actions.map(a => html`<button type="button" role="menuitem" key=${a.id}
      class="settle-item" onClick=${() => pick(a.id)}><span>${a.label}</span></button>`)}</span>` : null}
  </span>`
}

/** What a row opens, as an entry of the list a detail walks through (ui.queue): an inbox item or task
 *  its drawer, a row of a known task that task's detail beside the page, anything else nothing */
export function rowEntry(it, page, section, byKey) {
  const itemKey = (section === 'tasks' || section === 'inbox' || it.inbox) ? triageKey(it) : null
  if (itemKey) return { how: 'item', key: itemKey, title: it.title, it, where: { page, section } }
  if (it.task && byKey.has(`task:${it.task}`)) return { how: 'peek', key: `task:${it.task}`, title: it.title }
  return null
}

/** The rows of a list in the order it shows them, as the queue its details walk through */
export const rowQueue = (rows, byKey) => rows.map(r => rowEntry(r.it, r.page, r.section, byKey)).filter(Boolean)

function InfoRow({ it, page, section, s, c, byKey, scale = 0, lead = null, queue = null, steps = 'menu', timed = true }) {
  const t = T()
  const tri = s.triage?.items?.[triageKey(it)] ?? null
  const [open, setOpen] = useState(false)
  const tone = it.tone ?? null
  // an inbox item or task opens its drawer: a click anywhere on the row but its controls, or Enter on the row
  const itemKey = (section === 'tasks' || section === 'inbox' || it.inbox) ? triageKey(it) : null
  // an inbox item or task opens its own drawer, every other row the general detail
  const openIt = () => (itemKey ? c.openItem(itemKey, it, { page, section }, null, queue) : c.openInfo(it, page, section))
  // the detail line in words, without the priority the chip beside the title already shows
  const detail = detailText(it.detail, t).split(' · ').filter(p => p !== it.priority).join(' · ')
  return html`<tr class=${`${tone ? `tone-${tone}` : ''} row-opens`} tabindex="0"
    onClick=${e => { if (rowClickOpens(e)) openIt() }}
    onKeyDown=${e => { if (e.key === 'Enter' && e.target === e.currentTarget) { e.preventDefault(); openIt() } }}>
    ${timed ? html`<td class="c-when mono">${it.when}</td>` : null}
    <td class=${`c-item${tri ? ' has-gist' : ''}`}>
      ${tri ? html`<${TriageGist} tri=${tri} keyRow=${actionRow(it, byKey)} c=${c} s=${s} />` : null}
      <div class="info-title">
        ${lead ? html`${lead.rank ? html`<span class="jrank mono" title=${lead.judge ? t.workOrder.judge(lead.judge) : undefined}>${lead.rank}</span>` : null}<span class="chip jlabel">${lead.label}</span>` : null}
        ${itemKey ? html`<button type="button" class="btn-link info-open" title=${t.item.open}
            aria-haspopup="dialog" onClick=${openIt}>
            ${tone ? html`<${StateLine} token=${toneToken(tone)} strong=${tone === 'bad'} word=${it.title} />` : it.title}</button>`
          : it.task && byKey.has(`task:${it.task}`) ? html`<button type="button" class="btn-link info-open" title=${t.openDetail}
            aria-haspopup="true" onClick=${e => c.peek(`task:${it.task}`, e.currentTarget, queue)}>
            ${tone ? html`<${StateLine} token=${toneToken(tone)} strong=${tone === 'bad'} word=${it.title} />` : it.title}</button>`
          : tone ? html`<${StateLine} token=${toneToken(tone)} strong=${tone === 'bad'} word=${it.title} />` : html`<span>${it.title}</span>`}
        <span class="info-kinds"><${KindTag} row=${itemRow(it)} s=${s} /><${OriginTag} row=${itemRow(it)} /></span>
        <${MarkChip} mark=${it.mark} /><${PrioChip} priority=${it.priority} />
        ${it.task ? html`<${VerdictChip} review=${byKey.get(`task:${it.task}`)?.review} />` : null}
        ${it.state ? html`<span class="chip">${t.taskState[it.state] ?? it.state}</span>` : null}
        ${it.tab ? html`<${Chip} token=${stateToken(tabStateKey(it.tab))}>${t.state[tabStateKey(it.tab)] ?? it.tab.state}<//>` : null}
        ${it.starting ? html`<${Chip} token="info">${t.startingTab}<//>` : null}
        <${ReturnChip} s=${s} rowKey=${[itemKey, it.task ? `task:${it.task}` : null]} />
      </div>
      ${detail ? html`<div class="info-detail muted">${detail}</div>` : null}
      ${it.meter ? html`<${MeterBar} meter=${it.meter} scale=${scale} tone=${tone} />` : null}
      ${open && (it.lines ?? []).length ? html`<${Lines} lines=${it.lines} />` : null}
    </td>
    <td class="c-acts"><span class="btn-row">
      ${it.link?.kind === 'web' ? html`<a class="btn btn-ghost btn-xs" href=${it.link.href} target="_blank" rel="noopener noreferrer">
        <${Icon} name="external" size=${14} /><span class="btn-label">${t.openLink}</span></a>` : null}
      ${it.link?.kind === 'file' ? html`<${Btn} size="xs" variant="ghost" icon="copy" cls="act-quiet" title=${it.link.path} onClick=${() => c.copy(it.link.path)}>${t.copyPath}<//>` : null}
      <${PageItemActions} it=${it} s=${s} c=${c} />
      ${it.ask ? html`<${Btn} size="xs" variant="ghost" cls="act-quiet" onClick=${() => c.ask('info', { page, section, index: it.index })}>${t.btnAsk}<//>` : null}
      ${(it.lines ?? []).length ? html`<${Btn} size="xs" variant="ghost" cls=${open ? '' : 'act-quiet'} pressed=${open} onClick=${() => setOpen(!open)}>${t.btnLines}<//>` : null}
      ${it.actions?.length && it.row_id ? html`<${RowSteps} it=${it} page=${page} section=${section} s=${s} c=${c} as=${steps} />` : null}
      ${actionRow(it, byKey) && (it.inbox || it.task) ? html`<${RowBar} row=${actionRow(it, byKey)} s=${s} c=${c} tab=${it.tab} pin=${false} />` : null}
    </span></td>
  </tr>`
}

// ---------------------------------------------------------------- drawn sections: tiles and mosaic

/** Symbols for drawn rows: a source names a family (a device type, a cloud service, a provider), the
 *  page draws a plain line icon; anything unknown is a box */
const RES_ICONS = {
  laptop: 'M4 6h16v10H4zM2 19h20',
  monitor: 'M3 4h18v12H3zM8 20h8M12 16v4',
  server: 'M4 4h16v6H4zM4 14h16v6H4zM8 7h.01M8 17h.01',
  router: 'M3 14h18v6H3zM7 17h.01M11 17h.01M8 14 5 8M16 14l3-6',
  phone: 'M7 2h10v20H7zM11 18h2',
  robot: 'M6 8h12v10H6zM12 4v4M9 12h.01M15 12h.01M9 15h6',
  printer: 'M6 3h12v6H6zM4 9h16v8H4zM8 14h8v7H8z',
  usb: 'M9 2h6v8H9zM7 10h10v12H7z',
  gear: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1-1.9 1.9-.1-.1a1.6 1.6 0 0 0-2.7 1.1V20h-2.6v-.2a1.6 1.6 0 0 0-2.7-1.1l-.1.1-1.9-1.9.1-.1A1.6 1.6 0 0 0 4.6 15H4v-2.6h.2a1.6 1.6 0 0 0 1.1-2.7l-.1-.1 1.9-1.9.1.1a1.6 1.6 0 0 0 2.7-1.1V4h2.6v.2a1.6 1.6 0 0 0 2.7 1.1l.1-.1 1.9 1.9-.1.1a1.6 1.6 0 0 0 1.1 2.7h.2V15z',
  bolt: 'M13 2 4 14h7l-1 8 9-12h-7l1-8z',
  globe: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18',
  page: 'M6 2h9l5 5v15H6zM14 2v6h6',
  tunnel: 'M3 20v-8a9 9 0 0 1 18 0v8M7 20v-8a5 5 0 0 1 10 0v8',
  cloud: 'M7 18h10a4 4 0 0 0 .5-8A6 6 0 0 0 6 9a4.5 4.5 0 0 0 1 9z',
  mail: 'M3 5h18v14H3zM3 6l9 7 9-7',
  box: 'M4 7l8-4 8 4v10l-8 4-8-4zM4 7l8 4 8-4M12 11v10',
}

const ICON_OF = {
  macos: 'laptop', windows: 'monitor', linux: 'server', saas: 'cloud', router: 'router', 'kvm-over-ip': 'monitor',
  'smart-device': 'phone', robot: 'robot', '3d-printer': 'printer', 'usb-toolkit': 'usb', worker: 'gear',
  'function app': 'bolt', 'web app': 'globe', zone: 'globe', pages: 'page', tunnel: 'tunnel', account: 'cloud',
  azure: 'cloud', cloudflare: 'cloud', aws: 'cloud', gcp: 'cloud', m365: 'cloud', tailscale: 'cloud', ionos: 'globe',
  google: 'mail', icloud: 'mail', microsoft365: 'mail', exchange: 'mail', imap: 'mail',
}

function ResIcon({ name, size = 18 }) {
  const d = RES_ICONS[ICON_OF[name] ?? name] ?? RES_ICONS.box
  return html`<svg class="res-icon" width=${size} height=${size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
    stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d=${d} /></svg>`
}

export { usePopover }   // the menus of day.js and header.js take it from here

/** Search, state, group and tags: what a drawn section shows; the counts say what each choice holds */
function useRowFilter(items, initTags = {}) {
  const [q, setQ] = useState('')
  const [tone, setTone] = useState('all')
  const [group, setGroup] = useState(null)
  const [tags, setTags] = useState(initTags)
  const filter = { q, tone, group, tags }
  const counts = Object.fromEntries(TONE_FILTERS.map(([k]) => [k, filterRows(items, { ...filter, tone: k }).length]))
  return {
    q, setQ, tone, setTone, group, setGroup, tags, counts,
    shown: filterRows(items, filter),
    groups: [...new Set(items.map(it => it.group).filter(Boolean))],
    facets: tagFacets(items, filter),
    setTag: (k, v) => setTags(x => ({ ...x, [k]: x[k] === v ? null : v })),
    active: !!(q.trim() || tone !== 'all' || group || Object.values(tags).some(Boolean)),
    reset: () => { setQ(''); setTone('all'); setGroup(null); setTags({}) },
  }
}

function FilterBar({ f, label, groups = true }) {
  const t = T()
  return html`<div class="fbar" role="search" aria-label=${label}>
    <input class="input fbar-q" type="search" placeholder=${t.filterSearch} value=${f.q} onInput=${e => f.setQ(e.currentTarget.value)}
      aria-label=${t.filterSearch} />
    <span class="fbar-chips" role="group" aria-label=${t.filterState}>${TONE_FILTERS.map(([k]) => html`<button type="button" key=${k}
      class=${`fchip${f.tone === k ? ' is-on' : ''}`} aria-pressed=${String(f.tone === k)} disabled=${k !== 'all' && !f.counts[k]}
      onClick=${() => f.setTone(k)}>${k !== 'all' ? html`<span class=${`fdot fdot-${FILTER_TONE[k]}`} aria-hidden="true"></span>` : null}${t.filterTone[k]} <span class="mono">${f.counts[k]}</span></button>`)}</span>
    ${groups && f.groups.length > 1 && f.groups.length <= 14 ? html`<span class="fbar-chips" role="group" aria-label=${t.filterGroup}>
      ${f.groups.map(g => html`<button type="button" key=${g} class=${`fchip fchip-g${f.group === g ? ' is-on' : ''}`} aria-pressed=${String(f.group === g)}
        onClick=${() => f.setGroup(f.group === g ? null : g)}>${g}</button>`)}</span>` : null}
    ${f.facets.map(x => html`<span class="fbar-chips fbar-facet" role="group" aria-label=${x.key} key=${x.key}>
      <span class="fbar-key">${x.key}</span>
      ${x.values.map(([v, n]) => html`<button type="button" key=${v} class=${`fchip fchip-g${f.tags[x.key] === v ? ' is-on' : ''}`}
        aria-pressed=${String(f.tags[x.key] === v)} disabled=${!n && f.tags[x.key] !== v} onClick=${() => f.setTag(x.key, v)}>${v} <span class="mono">${n}</span></button>`)}
    </span>`)}
    ${f.active ? html`<${Btn} size="xs" variant="ghost" icon="close" onClick=${f.reset}>${t.filterReset}<//>` : null}
  </div>`
}

const ACCOUNT_STATUSES = [['active', 'success'], ['paused', 'warning'], ['disabled', 'on-surface-muted']]

/** An account's state in two clicks: active, paused or switched off, written into its file */
export function StatusMenu({ it, page, section, c }) {
  const t = T()
  const [open, setOpen] = useState(false)
  const box = usePopover(open, setOpen)
  const now = it.account.status
  const pick = status => { setOpen(false); if (status !== now) c.act('account_status', { page, section, index: it.index, status }) }
  return html`<span class="settle" ref=${box}>
    <${Btn} size="xs" variant="ghost" pressed=${open} onClick=${() => setOpen(!open)}>${t.acctStatus[now] ?? now} ▾<//>
    ${open ? html`<span class="settle-menu is-left" role="menu">
      ${ACCOUNT_STATUSES.map(([k, token]) => html`<button type="button" role="menuitemradio" aria-checked=${String(k === now)} key=${k}
        class="settle-item" onClick=${() => pick(k)}><${Dot} token=${token} /><span>${t.acctStatus[k]}</span>
        ${k === now ? html`<span class="muted small">${t.acctNow}</span>` : null}</button>`)}
      <span class="settle-hint muted small">${t.acctHint}</span>
    </span>` : null}
  </span>`
}

/** One drawn row: symbol, name, state as dot and word, what it is, the way to it */
function ResTile({ it, page, section, c, i, services, s = null, steps = 'menu' }) {
  const t = T()
  const tone = it.tone ?? 'ok'
  return html`<article class=${`rtile rt-${tone} row-in card-opens`} style=${{ '--i': Math.min(i, 14) }} tabindex="0"
    onClick=${e => { if (rowClickOpens(e)) c.openInfo(it, page, section) }}
    onKeyDown=${e => { if (e.key === 'Enter' && e.target === e.currentTarget) { e.preventDefault(); c.openInfo(it, page, section) } }}>
    <header class="rtile-head">
      <span class="rtile-icon"><${ResIcon} name=${it.icon} /></span>
      <h4 class="rtile-title" title=${it.title}>${it.title}</h4>
      <span class=${`rdot rdot-${tone}`} aria-hidden="true"></span>
    </header>
    ${it.detail ? html`<p class="rtile-detail">${it.detail}</p>` : null}
    ${it.meter ? html`<${MeterBar} meter=${it.meter} scale=${0} tone=${it.tone} />` : null}
    <footer class="rtile-foot">
      ${services ? html`<${Btn} size="xs" variant="secondary" onClick=${services.open}>${t.resServices(services.n)}<//>` : null}
      ${it.account?.status ? html`<${StatusMenu} it=${it} page=${page} section=${section} c=${c} />` : null}
      ${it.link?.kind === 'web' ? html`<a class="btn btn-ghost btn-xs" href=${it.link.href} target="_blank" rel="noopener noreferrer">
        <${Icon} name="external" size=${13} /><span class="btn-label">${t.openLink}</span></a>` : null}
      ${it.ask ? html`<${Btn} size="xs" variant="ghost" onClick=${() => c.ask('info', { page, section, index: it.index })}>${t.btnAsk}<//>` : null}
      ${steps === 'buttons' && s && it.actions?.length && it.row_id
        ? html`<${RowSteps} it=${it} page=${page} section=${section} s=${s} c=${c} as="buttons" />` : null}
    </footer>
  </article>`
}

/** Everything one account runs, as a filterable list: by kind, state, group, region, and by name */
function ResDrawer({ d, page, c, onClose }) {
  const t = T()
  const f = useRowFilter(d.rows, d.tags ?? {})
  const dialog = useFocusOnOpen(true)
  useEffect(() => {
    const esc = e => { if (e.key === 'Escape') { e.stopPropagation(); onClose() } }
    document.addEventListener('keydown', esc, true)
    return () => document.removeEventListener('keydown', esc, true)
  }, [])
  const keys = [...new Set(d.rows.flatMap(it => Object.keys(it.tags ?? {})))]
  const head = d.head
  return html`<div class="overlay overlay-center" onClick=${e => { if (e.target === e.currentTarget) onClose() }}>
    <div class="dialog rdrawer" role="dialog" aria-modal="true" aria-labelledby="rdrawer-title" ref=${dialog}>
      <header class=${`rdrawer-head rt-${head?.tone ?? 'ok'}`}>
        <span class="rtile-icon"><${ResIcon} name=${head?.icon ?? 'account'} size=${22} /></span>
        <div class="rgroup-main"><h2 class="sec-title rdrawer-title" id="rdrawer-title">${d.title}</h2>
          ${head?.detail ? html`<p class="rtile-detail">${head.detail}</p>` : null}</div>
        <div class="btn-row">
          ${head?.link?.kind === 'web' ? html`<a class="btn btn-ghost btn-xs" href=${head.link.href} target="_blank" rel="noopener noreferrer">
            <${Icon} name="external" size=${13} /><span class="btn-label">${t.openLink}</span></a>` : null}
          ${head ? html`<${Btn} size="xs" variant="ghost" onClick=${() => c.ask('info', { page, section: d.section, index: head.index })}>${t.btnAsk}<//>` : null}
          <${Btn} variant="ghost" size="xs" icon="close" label=${t.close} onClick=${onClose} />
        </div>
      </header>
      <div class="rdrawer-filter"><${FilterBar} f=${f} label=${t.filterLabel} groups=${false} /></div>
      <div class="rdrawer-body" tabindex="0" role="region" aria-label=${d.title}>
        ${f.shown.length ? html`<table class="tbl rdrawer-tbl">
          <thead><tr><th scope="col">${t.resName}</th>${keys.map(k => html`<th scope="col" key=${k}>${k}</th>`)}<th scope="col" class="c-acts"></th></tr></thead>
          <tbody>${f.shown.map(it => html`<tr key=${it.index}>
            <td><span class="rdrawer-name"><span class=${`rdot rdot-${it.tone ?? 'ok'}`} aria-hidden="true"></span>
              <${ResIcon} name=${it.icon} size=${14} /><span>${it.title}</span></span></td>
            ${keys.map(k => html`<td key=${k} class=${it.tags?.[k] && f.tags[k] !== it.tags[k] ? 'rdrawer-tag' : 'muted'}>
              ${it.tags?.[k] ? html`<button type="button" class="linkish" onClick=${() => f.setTag(k, it.tags[k])}>${it.tags[k]}</button>` : ''}</td>`)}
            <td class="c-acts"><span class="btn-row">
              ${it.link?.kind === 'web' ? html`<a class="btn btn-ghost btn-xs" href=${it.link.href} target="_blank" rel="noopener noreferrer"
                aria-label=${`${t.openLink}: ${it.title}`}><${Icon} name="external" size=${13} /></a>` : null}
              <${Btn} size="xs" variant="ghost" onClick=${() => c.ask('info', { page, section: d.section, index: it.index })}>${t.btnAsk}<//>
            </span></td></tr>`)}</tbody></table>` : html`<${Empty}>${t.filterNone}<//>`}
      </div>
      <footer class="rdrawer-foot muted small">${t.resShown(f.shown.length, d.rows.length)}</footer>
    </div>
  </div>`
}

/** The rows of the account a head row stands for, in any section of the page */
function accountRows(sections, id) {
  for (const sec of sections ?? []) {
    const items = sec.items ?? []
    const head = items.find(x => x.icon === 'account' && x.account?.id === id)
    if (head) return { title: head.title, head, section: sec.id, rows: items.filter(x => x !== head && x.group === head.group) }
  }
  return null
}

const MANY = 6     // a group with more rows than this shows its head, its problems, and the rest in the list

/** Cards in groups: a group's own head row (an account with its counts) leads it, the rest are tiles;
 *  a large group shows only what needs a look, the whole of it opens as a list */
function TilesView({ items, page, section, sections, c, s = null, steps = 'menu' }) {
  const t = T()
  const f = useRowFilter(items)
  const [drawer, setDrawer] = useState(null)
  const groups = []
  for (const it of f.shown) {
    const key = it.group ?? ''
    let g = groups.find(x => x.key === key)
    if (!g) groups.push(g = { key, head: null, rows: [] })
    if (it.icon === 'account' && !g.head) g.head = it
    else g.rows.push(it)
  }
  const servicesOf = it => {
    if (!it.account?.id || it.icon === 'account') return null
    const d = accountRows(sections, it.account.id)
    return d && d.rows.length ? { n: d.rows.length, open: () => setDrawer(d) } : null
  }
  return html`<div class="rview">
    <${FilterBar} f=${f} label=${t.filterLabel} />
    ${!f.shown.length ? html`<${Empty}>${t.filterNone}<//>` : groups.map(g => {
      const all = items.filter(it => (it.group ?? '') === g.key && it !== g.head)
      const n = k => all.filter(toneFilter(k)).length
      const big = g.head && all.length > MANY && !f.active
      const tiles = big ? g.rows.filter(toneFilter('problems')) : g.rows
      const open = tags => setDrawer({ title: g.head.title, head: g.head, section, rows: all, tags })
      const kindKey = Object.keys(all[0]?.tags ?? {})[0]
      const kinds = kindKey ? Object.entries(all.reduce((m, it) => ({ ...m, [it.tags?.[kindKey]]: (m[it.tags?.[kindKey]] ?? 0) + 1 }), {}))
        .filter(([k]) => k !== 'undefined').sort((a, b) => b[1] - a[1]) : []
      return html`<section class="rgroup" key=${g.key}>
        ${g.head ? html`<header class=${`rgroup-head is-card rt-${g.head.tone ?? 'ok'}`}>
            <span class="rtile-icon"><${ResIcon} name=${g.head.icon} size=${22} /></span>
            <div class="rgroup-main"><h3 class="rgroup-title">${g.head.title}</h3>
              ${g.head.detail ? html`<p class="rtile-detail">${g.head.detail}</p>` : null}
              ${g.head.meter ? html`<${MeterBar} meter=${g.head.meter} scale=${0} tone=${g.head.tone} />` : null}
              ${all.length ? html`<div class="rgroup-kinds">${kinds.map(([k, m]) => html`<button type="button" key=${k} class="fchip fchip-g"
                onClick=${() => open({ [kindKey]: k })}>${k} <span class="mono">${m}</span></button>`)}</div>` : null}</div>
            <div class="btn-row rgroup-acts">
              ${all.length ? html`<${Btn} size="xs" variant="primary" onClick=${() => open({})}>${t.resServices(all.length)}<//>` : null}
              ${g.head.link?.kind === 'web' ? html`<a class="btn btn-secondary btn-xs" href=${g.head.link.href} target="_blank" rel="noopener noreferrer">
                <${Icon} name="external" size=${13} /><span class="btn-label">${t.openLink}</span></a>` : null}
              <${Btn} size="xs" variant="ghost" onClick=${() => c.ask('info', { page, section, index: g.head.index })}>${t.btnAsk}<//>
            </div>
          </header>`
          : g.key ? html`<header class="rgroup-head"><h3 class="rgroup-title">${g.key}</h3>
            <span class="rgroup-count">${['ok', 'problems', 'off'].filter(k => n(k)).map(k => html`<span key=${k} class="rgroup-n">
              <span class=${`fdot fdot-${FILTER_TONE[k]}`} aria-hidden="true"></span>${t.filterTone[k]} <span class="mono">${n(k)}</span></span>`)}</span></header>` : null}
        ${big && tiles.length ? html`<h4 class="label-caps mosaic-sub">${t.mosaicProblems(tiles.length)}</h4>` : null}
        ${tiles.length ? html`<div class="rtiles">${tiles.map((it, i) => html`<${ResTile} key=${it.index} it=${it} i=${i} page=${page}
          section=${section} c=${c} services=${servicesOf(it)} s=${s} steps=${steps} />`)}</div>` : null}
      </section>`
    })}
    ${drawer ? html`<${ResDrawer} d=${drawer} page=${page} c=${c} onClose=${() => setDrawer(null)} />` : null}
  </div>`
}

/** Every row as one small square, coloured and patterned by its state; a click shows it, the rows that
 *  need a look follow as tiles. Rows with a gauge (a summary) stand on top */
function MosaicView({ items, page, section, c }) {
  const t = T()
  const heads = items.filter(it => it.meter)
  const cells = items.filter(it => !it.meter)
  const f = useRowFilter(cells)
  const [pick, setPick] = useState(null)
  const picked = cells.find(it => it.index === pick) ?? null
  const legend = [...new Set(cells.map(it => it.group).filter(Boolean))].map(g => ({ g, n: cells.filter(it => it.group === g).length,
    tone: cells.find(it => it.group === g)?.tone ?? 'ok' }))
  const [allProblems, setAllProblems] = useState(false)
  const problemsAll = f.shown.filter(it => it.tone === 'bad' || it.tone === 'warn')
  // red always shows; of the rest the first six, the others one click away
  const problems = allProblems ? problemsAll : problemsAll.filter((it, i) => it.tone === 'bad' || i < 6)
  return html`<div class="rview">
    ${heads.map(h => html`<div class=${`mosaic-head rt-${h.tone ?? 'ok'}`} key=${h.index}>
      <div><h3 class="rgroup-title">${h.title}</h3>${h.detail ? html`<p class="rtile-detail">${h.detail}</p>` : null}</div>
      <${MeterBar} meter=${h.meter} scale=${0} tone=${h.tone} /></div>`)}
    <${FilterBar} f=${f} label=${t.filterLabel} groups=${false} />
    <div class="mosaic" role="list" aria-label=${section}>${f.shown.map((it, i) => html`<button type="button" role="listitem" key=${it.index}
      class=${`mcell mc-${it.tone ?? 'ok'}${pick === it.index ? ' is-picked' : ''}`} style=${{ '--i': Math.min(i, 60) }}
      title=${`${it.title}: ${it.group ?? ''}`} aria-label=${`${it.title}, ${it.group ?? ''}`}
      onClick=${() => setPick(pick === it.index ? null : it.index)}></button>`)}</div>
    <div class="mosaic-legend">${legend.map(l => html`<button type="button" key=${l.g} class=${`fchip fchip-g${f.group === l.g ? ' is-on' : ''}`}
      onClick=${() => f.setGroup(f.group === l.g ? null : l.g)}><span class=${`mcell mcell-sm mc-${l.tone}`} aria-hidden="true"></span>${l.g} <span class="mono">${l.n}</span></button>`)}</div>
    ${picked ? html`<div class="rtiles"><${ResTile} it=${picked} i=${0} page=${page} section=${section} c=${c} /></div>` : null}
    ${problemsAll.length && !picked ? html`<h4 class="label-caps mosaic-sub">${t.mosaicProblems(problemsAll.length)}</h4>
      <div class="rtiles">${problems.map((it, i) => html`<${ResTile} key=${it.index} it=${it} i=${i} page=${page} section=${section} c=${c} />`)}</div>
      ${problemsAll.length > problems.length || allProblems ? html`<${Btn} size="xs" variant="ghost" icon="chevronDown"
        onClick=${() => setAllProblems(!allProblems)}>${allProblems ? t.mosaicFewer : t.mosaicAll(problemsAll.length)}<//>` : null}` : null}
  </div>`
}

/** Rows under their group (a log under its task), the busiest first; each group shows its newest
 *  rows, the rest one click away */
function GroupsView({ items, page, section, c }) {
  const t = T()
  const [open, setOpen] = useState({})
  const groups = groupRows(items).sort((a, b) => b.rows.length - a.rows.length)
  return html`<div class="gview">${groups.map((g, gi) => {
    const all = !!open[g.key]
    const rows = all ? g.rows : g.rows.slice(0, 3)
    return html`<section class="gview-group row-in" key=${g.key} style=${{ '--i': Math.min(gi, 14) }}>
      <header class="gview-head">
        <h3 class="gview-title">${g.key || t.groupOther}</h3>
        <span class="gview-count mono">${g.rows.length}</span>
        ${g.rows[0]?.when ? html`<span class="muted small">${t.groupLast(g.rows[0].when)}</span>` : null}
      </header>
      <ul class="gview-rows">${rows.map(it => html`<li key=${it.index} class=${`gview-row card-opens${it.tone === 'dim' ? ' is-dim' : ''}`} tabindex="0"
        onClick=${e => { if (rowClickOpens(e)) c.openInfo(it, page, section) }}
        onKeyDown=${e => { if (e.key === 'Enter' && e.target === e.currentTarget) { e.preventDefault(); c.openInfo(it, page, section) } }}>
        <span class="gview-when mono">${it.when}</span><span class="gview-text">${it.title}</span>
        ${it.ask ? html`<${Btn} size="xs" variant="ghost" onClick=${() => c.ask('info', { page, section, index: it.index })}>${t.btnAsk}<//>` : null}
      </li>`)}</ul>
      ${g.rows.length > 3 ? html`<${Btn} size="xs" variant="ghost" icon="chevronDown"
        onClick=${() => setOpen({ ...open, [g.key]: !all })}>${all ? t.mosaicFewer : t.mosaicAll(g.rows.length)}<//>` : null}
    </section>`
  })}</div>`
}

export function PageSection({ page, section, s, c }) {
  const byKey = indexRows(s.model)
  const t = T()
  // a GitHub section's figures and filter bar filter its rows: kept per section in this browser (round 6c)
  const ghKey = `${page.id}/${section.id}`, ghFilter = s.ui.ghFilter?.[ghKey] ?? null
  const setGhFilter = f => c.setGhFilter(ghKey, f)
  const gh = !!(section.metrics?.length || section.boards?.length)
  const stamp = sectionStamp(section.as_of, s.model?.collected_at)
  const more = section.whole ? null : s.more[`${page.id}/${section.id}`]   // whole: the caller already took every row
  // a task or inbox section follows the triage filter on top of its page
  const all = more ? more.items : (section.items ?? [])
  const items = section.kind === 'tasks' || section.kind === 'inbox'
    ? all.filter(it => triageShows(it, s.triage?.items, s.ui.triageFilter)) : gh ? all.filter(it => ghShows(it, ghFilter, ghMyLogin(all))) : all
  const left = more ? 0 : section.more ?? 0
  const scale = meterScale(items)
  // nothing found: a section that says so in one quiet line, or none at all when the profile asks
  const quiet = !items.length && section.status !== 'error' && section.status !== 'skipped' && !(gh && ghFiltered(ghFilter))
  if (quiet && section.hide_empty) return null
  // kept on the page for what reads it there (an account's services, the badge, the alarm): drawn only with a finding
  if (section.hide_ok && !section.bad && section.status !== 'error') return null
  if (quiet) {
    return html`<section class="panel psec psec-quiet" aria-labelledby=${`ps-${page.id}-${section.id}`}>
      <h2 class="sec-title" id=${`ps-${page.id}-${section.id}`}>${section.title}</h2>
      <${StateLine} token=${section.alarm ? 'success' : 'info'} word=${section.empty || t.empty} />
      ${stamp ? html`<span class="muted small" title=${t.measuredTitle}>${t.measuredAt(stamp)}</span>` : null}
    </section>`
  }
  let body
  if (section.status === 'skipped') body = html`<p class=${section.left_out ? 'muted' : ''}><${StateLine} token=${section.left_out ? 'info' : 'warning'} word=${skipText(section, t)} />
    ${skipFixable(section) ? html` <${SkipFix} s=${s} c=${c} title=${section.title} reason=${section.reason} />` : null}</p>`
  else if (section.status === 'error') body = html`<p><${StateLine} token="danger" strong word=${t.unreadable(section.reason || '')} /></p>`
  else if (section.view === 'tiles') body = html`<${TilesView} items=${items} page=${page.id} section=${section.id} sections=${page.sections} c=${c} s=${s} steps=${section.steps ?? 'menu'} />`
  else if (section.view === 'agenda' && section.kind === 'calendar') body = html`<${DatesAgenda} items=${items} page=${page} section=${section} s=${s} c=${c} />`
  else if (section.view === 'groups') body = html`<${GroupsView} items=${items} page=${page.id} section=${section.id} c=${c} />`
  // a github-work section on its board view: the GitHub list (views/github.js), not the general table
  else if (section.view === 'board' && gh) body = html`<${GitHubList} items=${items} page=${page.id} section=${section} s=${s} c=${c} byKey=${byKey} />`
  else if (section.view === 'mosaic') body = html`<${MosaicView} items=${items} page=${page.id} section=${section.id} c=${c} />`
  else if (gaugeSection(items)) {
    body = html`<ul class="gtiles">${items.map(it => html`<${GaugeTile} key=${it.index} it=${it} page=${page.id} section=${section.id} c=${c} />`)}</ul>`
  } else {
    // a task list in lanes: being worked on, runs on (quiet until a day), waits for your yes; one lane, no heads
    // board: the rows under their group (a GitHub row's board), the groups in the order the rows first name them
    const lanes = section.kind === 'tasks' ? TASK_LANES.map(id => [id, items.filter(it => taskLane(it) === id)]).filter(([, l]) => l.length)
      : section.view === 'board' ? [...new Set(items.map(it => it.group ?? ''))].map(g => [g, items.filter(it => (it.group ?? '') === g)]) : []
    // the shown order is the one a detail walks on; When only where a row has a time; the actions head for a reader only
    const shown = lanes.length > 1 ? lanes.flatMap(([, l]) => l) : items
    const queue = rowQueue(shown.map(it => ({ it, page: page.id, section: section.id })), byKey), timed = items.some(it => it.when)
    const row = it => html`<${InfoRow} key=${it.index} it=${it} page=${page.id} section=${section.id} s=${s} c=${c} byKey=${byKey} scale=${scale} queue=${queue} steps=${section.steps ?? 'menu'} timed=${timed} />`
    body = html`<div class="table-wrap" tabindex="0" role="region" aria-label=${section.title}>
      <table class="tbl">
        <thead><tr>${timed ? html`<th scope="col" class="c-when">${t.col.when}</th>` : null}<th scope="col">${t.col.item}</th><th scope="col" class="c-acts"><span class="sr-only">${t.col.actions}</span></th></tr></thead>
        ${lanes.length > 1 ? lanes.map(([id, list]) => html`<tbody key=${id} class=${section.view === 'board' ? 'lane-group' : `lane-${id}`}>
          <tr class="lane-head"><th scope="rowgroup" colspan=${timed ? 3 : 2}><span class="label-caps">${section.view === 'board' ? (id || t.groupOther) : t.lane[id]}</span> <span class="sec-count mono">${list.length}</span></th></tr>
          ${list.map(row)}</tbody>`)
          : html`<tbody>${items.map(row)}</tbody>`}
      </table>
    </div>`
  }
  return html`<section class="panel panel-pad psec" aria-labelledby=${`ps-${page.id}-${section.id}`}>
    <header class="psec-head">
      <h2 class="sec-title" id=${`ps-${page.id}-${section.id}`}>${section.title}
        ${section.status !== 'skipped' && section.status !== 'error' ? html`<span class="sec-count mono">${section.total ?? section.count}</span>` : null}</h2>
      ${section.bad ? html`<${StateLine} token="danger" strong word=${t.badgeFindings(section.bad)} />` : null}
      ${stamp ? html`<span class="muted small" title=${t.measuredTitle}>${t.measuredAt(stamp)}</span>` : null}
    </header>
    ${section.stale ? html`<p class="muted small"><${StateLine} token="warning" word=${section.stale} /></p>` : null}
    ${gh ? html`<${GitHubBoard} section=${section} items=${all} filter=${ghFilter} setFilter=${setGhFilter} s=${s} c=${c} />` : null}
    ${gh && ghFiltered(ghFilter) && !items.length ? html`<${Empty}>${t.filterNone}<//>` : body}
    ${left > 0 ? html`<${Btn} size="xs" variant="ghost" icon="chevronDown" onClick=${() => c.loadMore(page.id, section.id)}>${section.scoped ? t.btnMoreScoped(left) : t.btnMore(left)}<//>` : null}
  </section>`
}

// ---------------------------------------------------------------- the overview page: tiles, tokens of the week

/** Scroll to a section of the open page (the overview tiles jump there) */
function jumpTo(id) {
  const el = document.getElementById(id)
  if (el) el.scrollIntoView({ behavior: reducedMotion() ? 'auto' : 'smooth', block: 'start' })
}

function BoardTile({ title, tone, big, sub, note, onClick, label, bars = null }) {
  return html`<li><button type="button" class=${`otile tk-${tone}`} onClick=${onClick} aria-label=${label}>
    <span class="otile-head"><${Dot} token=${tone === 'neutral' ? 'on-surface-muted' : tone} /><span class="otile-title">${title}</span></span>
    <span class="otile-big num">${big}</span>
    ${sub ? html`<span class="otile-sub">${sub}</span>` : null}
    ${bars ? html`<span class="otile-bars" aria-hidden="true">${bars.map(b => html`<span key=${b.day}
      class=${`otile-bar${b.provisional ? ' is-provisional' : ''}`} style=${{ height: `${Math.max(4, b.frac * 100).toFixed(1)}%` }}></span>`)}</span>` : null}
    ${note ? html`<span class="otile-note">${note}</span>` : null}
  </button></li>`
}

/** The board on top of a page with `overview: true`: a tile per section and per live source (workers, tokens, costs
 *  when the page places the cost card), each a click away from its details. Its sub pages (`under:`) stand in the
 *  folder bar above it, Background jobs among them; Background jobs with a tab of their own keep a tile here, red
 *  only for an outage, and it opens on every job. The running sessions stand in the tab column beside it */
export function OverviewBoard({ page, s, c }) {
  const t = T()
  const lang = language()
  const tiles = []
  const stats = s.workers?.data?.stats
  if (stats && !subPagesOf(s, page.id).includes(WORKERS_PAGE)) {
    const j = jobCounts(s.workers.data)
    tiles.push(html`<${BoardTile} key="@w" title=${t.workersTab} tone=${j.failing ? 'danger' : j.upkeep ? 'neutral' : 'success'} big=${j.failing || j.all}
      sub=${t.overviewWorkers(j.ok, j.all, j.failing, j.upkeep)} label=${t.overviewJump(t.workersTab)} onClick=${() => c.openWorkers({})} />`)
  }
  const plan = cardPlan(page)
  const placed = [...Object.values(plan.after).flat(), ...plan.end]
  const k = s.costs?.data
  if (k && placed.includes('costs')) {
    const b = costBoard(k)
    const cur = k.currency ?? 'EUR'
    tiles.push(html`<${BoardTile} key="@k" title=${t.costsTile} tone=${b.tone} big=${moneyText(b.yesterday, lang, cur)}
      sub=${t.costsTileSub(moneyText(b.month, lang, cur))} bars=${b.week} note=${k.stale ? t.costsStale : null}
      label=${t.overviewJump(t.costsTitle)} onClick=${() => jumpTo(`costs-${page.id}`)} />`)
  }
  const u = s.usage?.data
  if (u) {
    const day = usageToday(u)
    tiles.push(html`<${BoardTile} key="@u" title=${t.usageTitle} tone=${u.outliers?.length ? 'warning' : 'neutral'} big=${tokenText(day.today, lang)}
      sub=${day.usual == null ? null : t.usageUsual(tokenText(day.usual, lang))}
      note=${u.outliers?.length ? t.usageOutlier(t.usageSource[u.outliers[0].source], u.outliers[0].factor) : null}
      label=${t.overviewJump(t.usageTitle)} onClick=${() => jumpTo(`usage-${page.id}`)} />`)
  }
  for (const sec of page.sections ?? []) {
    const x = sectionTile(sec)
    if (sec.hide_empty && !x.count && x.state === 'ok') continue
    if (sec.hide_ok && !sec.bad && x.state !== 'error') continue
    const sub = x.state === 'error' ? t.unreadable(x.note || '') : x.state === 'skipped' ? skipText(sec, t)
      : x.peak ? t.overviewPeak(x.peak.title, x.peak.percent)
      : x.counts ? x.counts.map(g => `${g.title} ${Math.round(g.value)}/${Math.round(g.max)}`).join(', ')
      : x.loud ? null : (x.count ? null : sec.empty)
    tiles.push(html`<${BoardTile} key=${sec.id} title=${sec.title} tone=${x.tone} big=${x.peak ? `${x.peak.percent} %` : x.loud || x.count}
      sub=${sub} note=${x.state === 'ok' ? x.note : null} label=${t.overviewJump(sec.title)} onClick=${() => jumpTo(`ps-${page.id}-${sec.id}`)} />`)
  }
  return html`<ul class="oboard" aria-label=${page.title}>${tiles}</ul>`
}

/** The machines on top of a folder page, one line each (logic.js machineLines): its background jobs and outages,
 *  whether it is always on, and where a sub page names it (a lab: its state there). The line opens the machine's
 *  jobs, or the page that names it when no job runs there; a place opens its page. None outside a folder page */
export function MachineLines({ page, s, c }) {
  const t = T()
  if (folderOf(s, page?.id) !== page?.id) return null
  const pages = s.model?.pages ?? []
  const folder = [page, ...subPagesOf(s, page.id).map(id => pages.find(p => p.id === id)).filter(Boolean)]
  const view = s.workers?.data
  const lines = machineLines({ runs: view?.runs ?? [], hosts: view?.hosts ?? (view?.host ? [view.host] : []), pages: folder })
    .map(x => ({ ...x, places: x.places.filter(p => p.page !== page.id) })).filter(x => x.jobs || x.places.length)
  if (!lines.length) return null
  return html`<section class="panel panel-pad mlines" aria-labelledby=${`ml-${page.id}`}>
    <h2 class="sec-title mlines-title" id=${`ml-${page.id}`}>${t.machinesTitle}</h2>
    <ul class="mlines-list">${lines.map(x => {
      const open = () => (x.jobs ? c.openWorkers({ host: x.name }) : c.setPage(x.places[0].page))
      const tone = x.tone === 'bad' ? 'danger' : x.tone === 'dim' ? 'on-surface-muted' : x.jobs ? 'success' : 'on-surface-muted'
      return html`<li key=${x.name} class="mline">
        <button type="button" class="mline-main" aria-label=${x.jobs ? t.machineOpen(x.name) : t.overviewJump(x.places[0].title)} onClick=${open}>
          <${Dot} token=${tone} /><strong class="mline-name">${x.name}</strong>
          ${x.always ? html`<span class="chip">${t.machineAlways}</span>` : x.state ? html`<span class="muted small" title=${x.state}>${short(x.state, 56)}</span>` : null}
          <span class="small">${x.jobs ? t.machineJobs(x.jobs) : t.machineNoJobs}</span>
          ${x.failing ? html`<span class="small mline-bad">${t.folderOutages(x.failing)}</span>` : null}
          ${x.upkeep ? html`<span class="muted small">${t.machineUpkeep(x.upkeep)}</span>` : null}
        </button>
        ${x.places.map(p => html`<button key=${p.page} type="button" class="fchip mline-place" aria-label=${t.machinePlace(p.title, p.state)}
          onClick=${() => c.setPage(p.page)}><${Dot} token=${p.tone ? toneToken(p.tone) : 'success'} /><span>${t.machinePlace(p.title, p.state)}</span></button>`)}
      </li>`
    })}</ul>
  </section>`
}

/** The head card of a sub page with `overview: true` (a lab): one line per part, folded where they say the same
 *  (logic.js pageSummary), each a jump to its part. Only the page's own parts: the jobs, tokens and costs stand on
 *  the folder's overview and its bar */
export function PageSummary({ page, s, c }) {
  const t = T()
  const lines = pageSummary(page)
  if (!lines.length) return null
  const say = x => {
    if (x.kind === 'error') return t.unreadable(x.note || '')
    if (x.kind === 'skipped') return skipText(x.section, t)
    if (x.kind === 'loud') return [x.tone === 'danger' ? t.folderFindings(x.n) : t.folderWarnings(x.n), x.note].filter(Boolean).join(': ')
    if (x.kind === 'peak') return t.overviewPeak(x.peak.title, x.peak.percent)
    if (x.kind === 'gauges') return x.gauges.map(g => `${g.title} ${Math.round(g.value)}/${Math.round(g.max)}`).join(', ')
    if (x.kind === 'one') return [x.text, x.detail].filter(Boolean).join(' · ')
    if (x.kind === 'rows') return t.summaryRows(x.counts.ok, x.counts.off)
    return x.text
  }
  return html`<section class="panel panel-pad psum" aria-label=${t.summaryLabel(page.title)}>
    <ul class="psum-list">${lines.map(x => html`<li key=${x.ids[0]}>
      <button type="button" class="psum-line" onClick=${() => jumpTo(`ps-${page.id}-${x.ids[0]}`)} aria-label=${t.overviewJump(x.titles[0])}>
        <${Dot} token=${x.tone === 'neutral' ? 'on-surface-muted' : x.tone} /><span class="psum-title" title=${x.titles.join(', ')}>${t.summaryParts(x.titles)}</span>
        <span class="psum-text">${say(x)}</span>
      </button></li>`)}</ul>
  </section>`
}

/** A page's live card by its id (`cards:` in the profile places them, cardPlan says where) */
export function PageCard({ id, page, s, c }) {
  if (id === 'costs') return html`<${CostCard} page=${page} s=${s} c=${c} />`
  if (id === 'usage') return html`<${UsageCard} page=${page} s=${s} c=${c} />`
  if (id === 'noise') return html`<${NoiseCard} page=${page} s=${s} c=${c} />`
  return null
}

/** The inbox sources a person had to drop from, most clicks first, and the mute rules in force with a
 *  button to lift each. Read when the page opens and with every new briefing, never on a timer */
export function NoiseCard({ page, s, c }) {
  const t = T()
  useEffect(() => { c.loadNoise() }, [s.model?.seq ?? 0])
  const n = s.noise ?? {}
  const data = n.data
  const rows = noiseRows(data)
  const mutes = data?.mutes ?? []
  const why = r => Object.entries(r.reasons ?? {}).map(([k, v]) => `${t.dropReasonShort[k] ?? k} ${v}`).join(', ')
  return html`<section class="panel panel-pad psec noise" id=${`noise-${page.id}`} aria-labelledby=${`noise-${page.id}-t`}>
    <header class="psec-head">
      <h2 class="sec-title" id=${`noise-${page.id}-t`}>${t.noiseTitle}</h2>
      <span class="muted small">${t.noiseWhere(data?.days ?? 30)}</span>
    </header>
    ${!data ? html`<p class="muted">${n.status === 'error' ? t.unreadable(n.error || '') : t.noiseLoading}</p>` : html`
      ${rows.length ? html`<div class="table-wrap" tabindex="0" role="region" aria-label=${t.noiseTitle}>
        <table class="tbl"><thead><tr><th scope="col">${t.noiseCol.source}</th><th scope="col" class="num">${t.noiseCol.dropped}</th>
          <th scope="col" class="num">${t.noiseCol.share}</th><th scope="col">${t.noiseCol.why}</th></tr></thead>
          <tbody>${rows.map(r => html`<tr key=${r.source}><td class="mono">${r.source}</td>
            <td class="num">${t.noiseOf(r.dropped, r.filed)}</td><td class="num">${r.percent} %</td>
            <td class="small">${why(r)}${r.muted ? html` <span class="muted">· ${t.noiseMuted(r.muted)}</span>` : null}</td></tr>`)}</tbody>
        </table></div>` : html`<${Empty}>${t.noiseNone}<//>`}
      ${mutes.length ? html`<h3 class="label-caps noise-sub">${t.noiseMutes}</h3>
        <ul class="ulist">${mutes.map(m => html`<li key=${m.id}>
          <span><span class="mono">${m.source}</span> ${t.noiseMuteWhat(m.key_prefix || m.kind || t.noiseMuteAll, m.until)}</span>
          <${Btn} size="xs" variant="ghost" busy=${!!s.ui.busy.inbox_unmute} label=${t.noiseUnmuteLabel(m.source)}
            onClick=${() => c.unmute(m.id)}>${t.noiseUnmute}<//></li>`)}</ul>` : null}`}
  </section>`
}

// ---------------------------------------------------------------- a work page in the order of Jev

/** Which kind of row a page with inbox and task rows shows: all, or one label (inbox, task, ...) */
export function KindBar({ kinds, active, c }) {
  const t = T()
  const total = kinds.reduce((a, k) => a + k.n, 0)
  const keys = useRoving()
  const chip = (label, n, on) => html`<button type="button" role="radio" key=${label ?? '@all'} aria-checked=${String(on)}
    class=${`fchip${on ? ' is-on' : ''}`} onClick=${() => c.setWorkKind(label)}>${label ?? t.workOrder.kindAll} <span class="mono">${n}</span></button>`
  return html`<div class="panel panel-pad tri-bar tri-kinds" role="group" aria-label=${t.workOrder.kindFilter}>
    <span class="fbar-chips" role="radiogroup" aria-label=${t.workOrder.kindFilter} ref=${keys.ref} onKeyDown=${keys.onKeyDown}>
      ${chip(null, total, !active)}${kinds.map(k => chip(k.label, k.n, active?.label === k.label))}
    </span></div>`
}

/** The strip on a page with `jev:`: by area or by Jev, and the click that orders it. Nothing goes to Jev
 *  by itself: on open the page only asks the server for the last order */
export function WorkOrder({ page, s, c }) {
  const t = T()
  const lang = language()
  const st = s.jevOrder[page.id]
  useEffect(() => { if (st === undefined) c.jevRank(page.id, false) }, [page.id])
  const order = st?.order ?? null
  const view = order && s.ui.workView === 'jev' ? 'jev' : 'area'
  const keys = useRoving()
  const tokens = order?.usage && order.usage.input_tokens != null ? tokenText((order.usage.input_tokens ?? 0) + (order.usage.output_tokens ?? 0), lang) : null
  return html`<div class="panel panel-pad tri-bar jorder" role="group" aria-label=${t.workOrder.label}>
    <span class="fbar-chips" role="radiogroup" aria-label=${t.workOrder.label} ref=${keys.ref} onKeyDown=${keys.onKeyDown}>
      ${['area', 'jev'].map(v => html`<button type="button" role="radio" key=${v} aria-checked=${String(view === v)}
        class=${`fchip${view === v ? ' is-on' : ''}`} disabled=${v === 'jev' && !order} onClick=${() => c.setWorkView(v)}>
        ${v === 'area' ? t.workOrder.byArea : t.workOrder.byJev}</button>`)}
    </span>
    <span class="tri-run">
      <span class="muted small">${st?.running ? t.workOrder.running : order ? html`${t.workOrder.last(order, lang, tokens)}<span class="jleft"><span class="jsep"> · </span>${t.workOrder.left(order.skipped)}</span>` : t.workOrder.never}</span>
      <button type="button" class=${`btn ${order ? 'btn-ghost' : 'btn-secondary'} btn-xs`} disabled=${!!st?.running} aria-busy=${st?.running ? 'true' : undefined}
        title=${t.workOrder.what} onClick=${() => c.jevRank(page.id, true)}><span class="btn-label">${order ? t.workOrder.rerun : t.workOrder.run}</span></button>
    </span>
    ${st?.error ? html`<p class="jerr"><${StateLine} token="danger" word=${t.workOrder.failed(st.error)} /></p>` : null}
  </div>`
}

/** Every row of the page in one list: Jev's order first, each row with its rank and its label, then the
 *  rows Jev did not see. A section with more rows than shown loads them, so the list is whole */
export function JevList({ page, s, c }) {
  const t = T()
  const byKey = indexRows(s.model)
  useEffect(() => {
    for (const sec of page.sections ?? []) if ((sec.more ?? 0) > 0 && !s.more[`${page.id}/${sec.id}`]) c.loadMore(page.id, sec.id)
  }, [page.id])
  const sections = (page.sections ?? []).map(sec => {
    const all = s.more[`${page.id}/${sec.id}`]?.items ?? sec.items ?? []
    return { ...sec, items: all.filter(it => triageShows(it, s.triage?.items, s.ui.triageFilter)) }
  })
  const list = jevList(sections, s.jevOrder[page.id]?.order, t.workOrder.kinds)
  // one queue over both parts: after Jev's last row the detail walks on into the rest
  const queue = rowQueue([...list.ranked, ...list.rest].map(r => ({ it: r.it, page: page.id, section: r.section })), byKey)
  const rows = entries => html`<div class="table-wrap" tabindex="0" role="region" aria-label=${page.title}>
    <table class="tbl"><thead><tr><th scope="col" class="c-when">${t.col.when}</th><th scope="col">${t.col.item}</th><th scope="col" class="c-acts">${t.col.actions}</th></tr></thead>
      <tbody>${entries.map(r => html`<${InfoRow} key=${`${r.section}/${r.it.index}`} it=${r.it} page=${page.id} section=${r.section} s=${s} c=${c}
        byKey=${byKey} lead=${{ rank: r.rank, label: r.label, judge: r.judge }} queue=${queue} />`)}</tbody></table></div>`
  return html`
    <section class="panel panel-pad psec" aria-labelledby=${`ps-${page.id}-jev`}>
      <header class="psec-head"><h2 class="sec-title" id=${`ps-${page.id}-jev`}>${t.workOrder.byJev}
        <span class="sec-count mono">${list.ranked.length}</span></h2></header>
      ${list.ranked.length ? rows(list.ranked) : html`<${Empty}>${t.filterNone}<//>`}
    </section>
    ${list.rest.length ? html`<section class="panel panel-pad psec" aria-labelledby=${`ps-${page.id}-jrest`}>
      <header class="psec-head"><h2 class="sec-title" id=${`ps-${page.id}-jrest`}>${t.workOrder.rest(list.rest.length)}</h2></header>
      ${rows(list.rest)}
    </section>` : null}`
}
