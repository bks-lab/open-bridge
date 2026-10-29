// SPDX-License-Identifier: MIT
// The cockpit, the live cards of the overview page: cloud costs per account and tokens per Bridge, both as stacked
// bars over days (at most four series), read from their endpoints when they show. The rules every component keeps
// stand at the head of components.js.

import { html, useEffect, useState } from '../vendor/htm-preact-3.1.1.module.js'
import {
  formatDay, weekdayNames, tokenText, USAGE_SOURCES, stackBars, shownLabels, sparkPoints, moneyText, budgetBar, costBars,
  costDay, costTotals, costYesterday, costTone, costSources, costCenterChoices, costPersonaChoices, costCenterBudget, costScope, costMonths, clockTime, SERIES_REST, USAGE_RANGES, USAGE_DIMS, NO_BRIDGE, usageParts,
} from '../logic.js'
import { T, language } from '../text.js'
import { Btn, Chip, Empty, StateLine } from './parts.js'
import { Prose } from './prose.js'

/** A row of chips that picks one value (a range, a dimension); `shown` writes its label in front of it */
function ChipPick({ label, values, value, textOf, onPick, shown = false }) {
  return html`<div class="chip-pick" role="group" aria-label=${label}>${shown ? html`<span class="chip-pick-label label-caps">${label}</span>` : null}${values.map(v => html`<button type="button" key=${v}
    class=${`fchip${v === value ? ' is-on' : ''}`} aria-pressed=${String(v === value)} onClick=${() => onPick(v)}>${textOf(v)}</button>`)}</div>`
}

/** Stacked bars over days, at most four series (sr-0 to sr-3, the last the rest); 30 and 90 columns get narrow bars
 *  and every k-th day label. A provisional day is drawn lighter with a dashed top. A click picks the day */
function StackChart({ bars, label, nameOf, valueText, pick, onPick }) {
  const lang = language()
  const t = T()
  const n = bars.days.length
  const dense = n > 14
  const shown = shownLabels(n, dense ? 10 : n)
  const names = weekdayNames(lang)
  const dayText = iso => (dense ? String(Number(iso.slice(8, 10))) : names[(new Date(`${iso}T12:00:00`).getDay() + 6) % 7])
  const series = key => `sr-${bars.keys.indexOf(key)}`
  return html`<div class=${`ubars${dense ? ' is-dense' : ''}`} style=${{ '--n': n }} role="group" aria-label=${label}>
    ${bars.days.map((d, i) => html`<button type="button" key=${d.day} class=${`ubar${pick === d.day ? ' is-on' : ''}${d.provisional ? ' is-provisional' : ''}`}
        aria-pressed=${pick === d.day} aria-label=${`${t.usageDayOf(formatDay(d.day, lang))}: ${valueText(d.total)}`} onClick=${() => onPick(d.day)}>
      ${dense ? null : html`<span class="ubar-n mono">${valueText(d.total)}</span>`}
      <span class="ubar-col">${d.parts.map(p => html`<span key=${p.key} class=${`ubar-part ${series(p.key)}`}
        style=${{ height: `${(p.frac * 100).toFixed(2)}%` }} title=${`${nameOf(p.key)}: ${valueText(p.value)}`}></span>`)}</span>
      <span class="ubar-day">${shown[i] ? dayText(d.day) : ' '}</span>
    </button>`)}
  </div>`
}

/** The legend of a StackChart: each series with its sum over the shown days */
function StackLegend({ bars, nameOf, valueText, extra = null }) {
  const sum = key => bars.days.reduce((a, d) => a + (d.parts.find(p => p.key === key)?.value ?? 0), 0)
  return html`<ul class="ulegend">${bars.keys.map((k, i) => html`<li key=${k}><span class=${`ukey sr-${i}`} aria-hidden="true"></span>
    ${nameOf(k)} <span class="mono">${valueText(sum(k))}</span></li>`)}${extra}</ul>`
}

/** An account's budget: the month so far filled, the forecast as a marker, the budget the full width until the
 *  month runs past it (then a mark where it ends) */
function BudgetBar({ acc, label }) {
  const b = budgetBar(acc)
  if (!b) return null
  const pct = x => `${(Math.min(1, Math.max(0, x)) * 100).toFixed(2)}%`
  const fill = b.tone === 'danger' ? 'danger' : b.tone === 'warning' ? 'warning' : 'secondary'
  return html`<span class="cbudget" role="img" aria-label=${label}>
    <span class=${`cbudget-fill tk-${fill}`} style=${{ width: pct(b.fill) }}></span>
    ${b.forecast != null ? html`<span class=${`cbudget-fc tk-${fill}`} style=${{ left: pct(b.forecast) }}></span>` : null}
    ${b.budget < 1 ? html`<span class="cbudget-cap" style=${{ left: pct(b.budget) }}></span>` : null}
  </span>`
}

const KEY_PROVIDERS = ['openai', 'anthropic', 'elastic']

/** One account of the cost card: name, provider, yesterday, the month against its budget; a failed one says why,
 *  and one that needs a login carries the command to run, ready to copy */
function CostRow({ acc, data, c }) {
  const t = T()
  const lang = language()
  const cur = acc.currency || data.currency || 'EUR'
  const money = n => moneyText(n, lang, cur)
  const head = html`<span class="crow-name"><span class="crow-title">${acc.display_name || acc.id}</span>
    <${Chip}>${acc.provider}<//>${acc.kind === 'fixed' ? html`<${Chip}>${t.costsFixed}<//>` : null}</span>`
  if (!acc.ok) {
    return html`<li class="crow is-failed">${head}
      <div class="crow-why">
        ${acc.login_command ? html`<p><${StateLine} token="warning" strong word=${t.costsLogin} /> <span class="small">${acc.login?.hint || acc.error || ''}</span></p>
          <p class="crow-cmd"><code class="mono">${acc.login_command}</code>
            <${Btn} size="xs" variant="secondary" onClick=${() => c.copy(acc.login_command)}>${t.copyCommand}<//></p>
          ${KEY_PROVIDERS.includes(acc.provider) ? html`<p class="muted small">${t.costsKeyHint}</p>` : null}`
        : html`<p class="muted small">${acc.error || ''}</p>`}
      </div></li>`
  }
  const y = costYesterday(acc, data.today)
  const mtd = money(acc.month_to_date ?? 0)
  const tone = costTone(acc)
  const word = acc.budget_month ? t.costsOf(mtd, money(acc.budget_month)) : mtd
  return html`<li class=${`crow tk-${tone}`}>${head}
    <span class="crow-fig"><span class="label-caps">${t.costsYesterday}</span><span class="num">${y == null ? '' : money(y)}</span></span>
    <span class="crow-fig"><span class="label-caps">${t.costsMonth}</span><span class="num">${word}</span></span>
    <span class="crow-budget">
      ${acc.budget_month ? html`<${BudgetBar} acc=${acc} label=${`${word}, ${t.costsForecast(money(acc.forecast_month ?? 0))}`} />` : html`<span class="muted small">${t.costsNoBudget}</span>`}
      ${acc.forecast_month != null ? html`<span class="muted small">${t.costsForecast(money(acc.forecast_month))}</span>` : null}
      ${acc.fx_missing && acc.original_currency ? html`<span class="muted small">${t.costsNoFx(acc.original_currency)}</span>` : null}
      ${acc.credits_month ? html`<span class="muted small">${t.costsCredits(money(acc.used_month ?? 0), money(acc.credits_month))}</span>` : null}
    </span></li>`
}

/** A text handed to the browser as a file to save */
function saveText(text, name, type) {
  const url = URL.createObjectURL(new Blob([text], { type: `${type};charset=utf-8` }))
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** The cost statement of the picked month, persona and project (scripts/cost-ledger.py statement): made on the
 *  button, from the closed month or the kept view (then marked provisional), to read, copy or save */
function CostStatement({ data, center, persona, c }) {
  const t = T()
  const lang = language()
  const months = costMonths(data)
  const [month, setMonth] = useState(null)
  const [made, setMade] = useState(null)
  const [busy, setBusy] = useState(false)
  const pick = months.includes(month) ? month : months[0]
  const key = `${pick}|${persona}|${center}`
  if (!months.length) return null
  const monthText = m => new Intl.DateTimeFormat(lang, { month: 'long', year: 'numeric' }).format(new Date(`${m}-15T12:00:00`))
  const make = async () => {
    setBusy(true)
    setMade({ key, ...(await c.costStatement({ month: pick, center, persona })) })
    setBusy(false)
  }
  const st = made?.key === key && made.ok ? made.statement : null
  const file = ext => `${t.costsStatementFile}-${pick}-${center === 'all' ? persona : center}.${ext}`
  return html`<div class="costs-make">
    <${ChipPick} shown label=${t.costsMonthLabel} values=${months} value=${pick} textOf=${monthText} onPick=${setMonth} />
    <${Btn} size="xs" variant="secondary" busy=${busy} onClick=${make}>${t.costsMake}<//>
    ${made?.key === key && !made.ok ? html`<p class="muted small">${made.error}</p>` : null}
    ${st ? html`<div class="costs-stmt">
      <${Prose} text=${st.markdown} />
      <p class="costs-stmt-actions">
        <${Btn} size="xs" variant="secondary" onClick=${() => c.copy(st.markdown)}>${t.costsCopy}<//>
        <${Btn} size="xs" variant="secondary" onClick=${() => saveText(st.markdown, file('md'), 'text/markdown')}>${t.costsSaveMd}<//>
        <${Btn} size="xs" variant="secondary" onClick=${() => saveText(st.csv, file('csv'), 'text/csv')}>${t.costsSaveCsv}<//>
        <${Btn} size="xs" variant="ghost" onClick=${() => setMade(null)}>${t.costsStatementClose}<//>
      </p></div>` : null}
  </div>`
}

/** Cloud costs per day and account against a budget (scripts/cloud-costs.py, read by bridge-resources.py costs).
 *  Read when the card shows, with every new briefing and on its reload button, never on a timer */
export function CostCard({ page, s, c }) {
  const t = T()
  const lang = language()
  useEffect(() => { c.loadCosts() }, [s.model?.seq ?? 0])
  const k = s.costs ?? {}
  const data = k.data
  const [range, setRange] = useState('7')
  const [pick, setPick] = useState(null)
  const [center, setCenter] = useState('all')
  const [persona, setPersona] = useState('all')
  const cur = data?.currency ?? 'EUR'
  const money = n => moneyText(n, lang, cur)
  // a persona and a project (workflow/cost-centers/) narrow the bars, the day, the rows and the totals alike
  const personas = data ? costPersonaChoices(data) : []
  const who = personas.includes(persona) ? persona : 'all'
  const choices = data ? costCenterChoices(data, who) : []
  const what = choices.includes(center) ? center : 'all'
  const shown = data ? costScope(data, what, who) : data
  const budget = data ? costCenterBudget(data, what) : null
  const centerText = v => (v === 'all' ? t.costsCenterAll : v === 'none' ? t.costsCenterNone
    : data?.cost_centers?.find(x => x.id === v)?.title ?? v)
  const personaText = v => (v === 'all' ? t.costsCenterAll
    : data?.cost_centers?.find(x => x.persona_ref === v)?.persona_title ?? v)
  const accounts = shown?.accounts ?? []
  const bars = shown ? costBars(shown, range) : null
  const nameOf = key => (key === SERIES_REST ? t.costsRest : accounts.find(a => a.id === key)?.display_name || key)
  const sel = bars?.days.some(d => d.day === pick) ? pick : null
  const day = sel ? costDay(shown, sel) : []
  const tot = shown ? costTotals(shown, range) : null
  const at = data?.at ? Date.parse(data.at) : NaN
  return html`<section class="panel panel-pad psec costs" id=${`costs-${page.id}`} aria-labelledby=${`costs-${page.id}-t`}>
    <header class="psec-head">
      <h2 class="sec-title" id=${`costs-${page.id}-t`}>${t.costsTitle}</h2>
      ${data ? html`<${ChipPick} label=${t.costsRangeLabel} values=${['7', '30', 'month']} value=${range} textOf=${v => t.costsRanges[v]}
        onPick=${v => { setRange(v); setPick(null) }} />` : null}
      ${data && !Number.isNaN(at) ? html`<span class="muted small">${t.costsMeasured(clockTime(at), costSources(data))}</span>` : null}
      <${Btn} size="xs" variant="ghost" icon="reload" label=${t.costsReload} busy=${k.status === 'loading'} onClick=${() => c.loadCosts()} />
    </header>
    ${data?.stale ? html`<p><${StateLine} token="warning" strong word=${t.costsStale} /></p>` : null}
    ${personas.length || choices.length ? html`<div class="costs-filters">
      ${personas.length ? html`<${ChipPick} shown label=${t.costsPersonaLabel} values=${personas} value=${who}
        textOf=${personaText} onPick=${v => { setPersona(v); setCenter('all'); setPick(null) }} />` : null}
      ${choices.length ? html`<${ChipPick} shown label=${t.costsCenterLabel} values=${choices} value=${what}
        textOf=${centerText} onPick=${v => { setCenter(v); setPick(null) }} />` : null}
    </div>` : null}
    ${budget ? html`<p class="costs-budget"><span class="label-caps">${t.costsCenterBudget}</span>
      <${BudgetBar} acc=${budget} label=${t.costsOf(money(budget.month_to_date), money(budget.budget_month))} />
      <span class="muted small">${t.costsOf(money(budget.month_to_date), money(budget.budget_month))} · ${t.costsForecast(money(budget.forecast_month))}</span></p>` : null}
    ${!data ? html`<p class="muted">${k.status === 'error' ? t.unreadable(k.error || '') : k.status === 'none' ? t.costsEmpty : t.costsLoading}</p>` : html`
      ${bars.max ? html`<${StackChart} bars=${bars} label=${t.costsTitle} nameOf=${nameOf} valueText=${money} pick=${sel}
          onPick=${d => setPick(p => (p === d ? null : d))} />
        <${StackLegend} bars=${bars} nameOf=${nameOf} valueText=${money}
          extra=${bars.days.some(d => d.provisional) ? html`<li class="muted"><span class="ukey ukey-provisional" aria-hidden="true"></span>${t.costsProvisional}</li>` : null} />` : null}
      ${sel ? html`<div class="uday">
        <h3 class="uday-title">${formatDay(sel, lang)}</h3>
        <ul class="ulist">${day.map(a => html`<li key=${a.id}><span>${a.name}${a.groups.length ? html` <span class="muted small">· ${a.groups.map(([g, v]) => `${g} ${money(v)}`).join(', ')}</span>` : null}</span>
          <span class="num">${money(a.amount)}</span></li>`)}</ul>
      </div>` : null}
      <h3 class="label-caps costs-sub">${t.costsAccounts}</h3>
      <ul class="clist">${accounts.map(a => html`<${CostRow} key=${a.id} acc=${a} data=${shown} c=${c} />`)}</ul>
      <p class="costs-total"><span class="num">${t.costsTotal(money(tot.range), money(tot.month))}</span></p>
      <${CostStatement} data=${data} center=${what} persona=${who} c=${c} />`}
  </section>`
}

/** A bridge's tokens per day as a tiny line */
function Spark({ values, label }) {
  const pts = sparkPoints(values, 60, 16)
  return pts ? html`<svg class="spark" viewBox="0 -1 60 18" width="60" height="18" role="img" aria-label=${label}>
    <polyline points=${pts} /></svg>` : null
}

/** The written tokens over 7, 30 or 90 days, a bar per day split by Bridge, model, source or project; a click on a
 *  day shows its models and projects; below, each Bridge with its machine. Read when the page opens, with every
 *  new briefing and on its reload button, never on a timer */
export function UsageCard({ page, s, c }) {
  const t = T()
  const lang = language()
  useEffect(() => { c.loadUsage() }, [s.model?.seq ?? 0])
  const u = s.usage ?? {}
  const data = u.data
  const [pick, setPick] = useState(null)
  const [dimPick, setDim] = useState(null)
  const hasBridges = (data?.bridges ?? []).length > 0
  const dim = dimPick ?? (hasBridges ? 'bridge' : 'source')
  const days = data?.days ?? []
  const bars = stackBars(days, d => usageParts(d, dim), dim === 'source' ? { order: USAGE_SOURCES } : {})
  const sel = days.find(d => d.day === pick) ?? days[days.length - 1]
  const tok = n => tokenText(n, lang)
  const nameOf = key => (key === SERIES_REST ? t.usageRest : dim === 'source' ? t.usageSource[key] ?? key
    : dim === 'bridge' ? (key === NO_BRIDGE ? t.usageNoBridge : key) : dim === 'model' ? String(key).replace(/^claude-/, '') : key)
  const sum = f => USAGE_SOURCES.reduce((a, k) => a + (sel?.sources?.[k]?.[f] ?? 0), 0)
  const at = data?.at ? Date.parse(data.at) : NaN
  const range = u.days ?? data?.range ?? 7
  const down = (data?.hosts ?? []).filter(h => !h.ok)     // pending: its first read still runs, not a failure
  return html`<section class="panel panel-pad psec usage" id=${`usage-${page.id}`} aria-labelledby=${`usage-${page.id}-t`}>
    <header class="psec-head">
      <h2 class="sec-title" id=${`usage-${page.id}-t`}>${t.usageTitle}</h2>
      <${ChipPick} label=${t.usageRangeLabel} values=${USAGE_RANGES} value=${range} textOf=${t.usageRanges}
        onPick=${n => { setPick(null); c.loadUsage(n) }} />
      ${!Number.isNaN(at) ? html`<span class="muted small">${t.usageMeasured(clockTime(at))}</span>` : null}
      <${Btn} size="xs" variant="ghost" icon="reload" label=${t.usageReload} busy=${u.status === 'loading'} onClick=${() => c.loadUsage(range)} />
    </header>
    <p class="muted small">${t.usageWhere}</p>
    ${!data ? html`<p class="muted">${u.status === 'error' ? t.unreadable(u.error || '') : t.usageLoading}</p>`
      : !bars.max ? html`<${Empty}>${t.usageNone}<//>` : html`
      ${(data.outliers ?? []).map(o => html`<p key=${o.source}><${StateLine} token="warning" strong word=${t.usageOutlier(t.usageSource[o.source], o.factor)} /></p>`)}
      <${ChipPick} label=${t.usageDimLabel} values=${USAGE_DIMS} value=${dim} textOf=${v => t.usageDims[v]} onPick=${setDim} />
      <${StackChart} bars=${bars} label=${t.usageTitle} nameOf=${nameOf} valueText=${tok} pick=${sel?.day}
        onPick=${setPick} />
      <${StackLegend} bars=${bars} nameOf=${nameOf} valueText=${tok} />
      ${sel ? html`<div class="uday">
        <h3 class="uday-title">${formatDay(sel.day, lang)}</h3>
        <div class="uday-cols">
          <div><span class="label-caps">${t.usageModels}</span>
            <ul class="ulist">${(sel.models ?? []).map(m => html`<li key=${m.model}><span>${m.model.replace(/^claude-/, '')}</span><span class="num">${tok(m.output)}</span></li>`)}</ul></div>
          <div><span class="label-caps">${t.usageProjects}</span>
            <ul class="ulist">${(sel.projects ?? []).map(p => html`<li key=${p.project}><span>${p.project}</span><span class="num">${tok(p.output)}</span></li>`)}</ul></div>
        </div>
        <p class="muted small">${t.usageInput(tok(sum('input')), tok(sum('cache_read')), tok(sum('cache_write')))}</p>
      </div>` : null}`}
    ${data && (hasBridges || down.length) ? html`<h3 class="label-caps costs-sub">${t.usagePerBridge}</h3>
      <ul class="blist">
        ${(data.bridges ?? []).map(b => html`<li key=${`${b.bridge}@${b.host}`} class="brow">
          <span class="crow-name"><span class="crow-title">${b.bridge ?? t.usageNoBridge}</span><${Chip}>${b.host}<//></span>
          <span class="num">${tok(b.output)}</span>
          <span class="muted small brow-models">${(b.models ?? []).slice(0, 3).map(m => String(m.model).replace(/^claude-/, '')).join(', ')}</span>
          <${Spark} values=${b.days ?? []} label=${`${b.bridge ?? t.usageNoBridge}: ${tok(b.output)}`} />
        </li>`)}
        ${down.map(h => html`<li key=${`@${h.host}`} class=${h.pending ? 'brow is-pending' : 'brow is-failed'}><span class="muted small">${h.pending ? t.usagePending(h.host) : t.usageUnreachable(h.host, h.error || '')}</span></li>`)}
      </ul>` : null}
  </section>`
}
