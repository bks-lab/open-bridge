// SPDX-License-Identifier: MIT
// Frontend tests of the Betrieb page's cost and token cards (scripts/web/logic.js), no npm dependencies.
//
//   node --test scripts/tests/bridge_cockpit_costs.test.mjs
//
// The pure helpers behind the cards: where a page's live cards stand, the stacked bars (top three and the
// rest), the budget bar, money in German and English, the thinned day labels and the sparkline.
// The page's .js files are ES modules without a package.json "type"; like the other frontend tests they are
// copied to a temp directory as .mjs and imported there.
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import test from 'node:test'
import assert from 'node:assert/strict'

const here = path.dirname(fileURLToPath(import.meta.url))
const WEB = path.join(here, '..', 'web')
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'bridge-cockpit-costs-'))
for (const name of ['logic', 'text']) {
  const src = fs.readFileSync(path.join(WEB, `${name}.js`), 'utf8').replace(/(from\s+'\.\/[^']+)\.js'/g, "$1.mjs'")
  fs.writeFileSync(path.join(tmp, `${name}.mjs`), src)
}
const logic = await import(pathToFileURL(path.join(tmp, 'logic.mjs')).href)
const text = await import(pathToFileURL(path.join(tmp, 'text.mjs')).href)
process.on('exit', () => fs.rmSync(tmp, { recursive: true, force: true }))

// ---------------------------------------------------------------- where a page's cards stand

test('a page without cards keeps what overview alone drew: usage and noise at its end', () => {
  const plan = logic.cardPlan({ overview: true, sections: [{ id: 'a' }], cards: null })
  assert.deepEqual(plan, { after: {}, end: ['usage', 'noise'] })
  assert.deepEqual(logic.cardPlan({ sections: [{ id: 'a' }] }), { after: {}, end: [] })
})

test('cards stand after their section in the listed order, each once; an unknown section sends a card to the end', () => {
  const page = { overview: true, sections: [{ id: 'systeme' }, { id: 'x' }],
    cards: [{ id: 'costs', after: 'systeme' }, { id: 'usage', after: 'systeme' }, { id: 'noise', after: null }, { id: 'usage', after: 'gone' }] }
  assert.deepEqual(logic.cardPlan(page), { after: { systeme: ['costs', 'usage'] }, end: ['noise'] })
  // an empty list is a choice too: no card at all
  assert.deepEqual(logic.cardPlan({ overview: true, sections: [], cards: [] }), { after: {}, end: [] })
  assert.equal(logic.cardPlan({ cards: [{ id: 'costs', after: null }], sections: [] }).end[0], 'costs')
})

// ---------------------------------------------------------------- stacked bars: top three and the rest

test('stacked bars keep the three largest series over the range and sum the rest', () => {
  const days = [
    { day: '2026-10-01', v: { a: 5, b: 1, c: 2, d: 1, e: 1 } },
    { day: '2026-10-02', v: { a: 1, b: 4, c: 0, d: 0, e: 0 }, provisional: true },
  ]
  const bars = logic.stackBars(days, d => d.v)
  assert.deepEqual(bars.keys, ['a', 'b', 'c', logic.SERIES_REST])
  assert.equal(bars.max, 10)
  assert.equal(bars.total, 15)
  assert.deepEqual(bars.days[0].parts, [
    { key: 'a', value: 5, frac: 0.5 }, { key: 'b', value: 1, frac: 0.1 }, { key: 'c', value: 2, frac: 0.2 }, { key: logic.SERIES_REST, value: 2, frac: 0.2 }])
  assert.equal(bars.days[1].provisional, true)
  assert.deepEqual(bars.days[1].parts.map(p => p.key), ['a', 'b'])   // zero parts are left out
  // with no more than three series there is no rest
  assert.deepEqual(logic.stackBars(days.slice(1), d => d.v).keys, ['b', 'a'])
  // a fixed order keeps its keys and colours, whatever is largest
  assert.deepEqual(logic.stackBars(days, d => d.v, { order: ['e', 'd'] }).keys, ['e', 'd'])
  assert.deepEqual(logic.stackBars([], d => d.v), { keys: [], max: 0, total: 0, days: [] })
})

test('day labels thin out on 30 and 90 columns, anchored on the newest day', () => {
  assert.deepEqual(logic.shownLabels(5, 10), [true, true, true, true, true])
  const thirty = logic.shownLabels(30, 10)
  assert.equal(thirty.length, 30)
  assert.equal(thirty[29], true)
  assert.ok(thirty.filter(Boolean).length <= 10)
  assert.equal(logic.shownLabels(90, 10).filter(Boolean).length, 10)
  assert.deepEqual(logic.shownLabels(0), [])
})

test('a sparkline is an inline SVG polyline over the width, the largest value at the top', () => {
  assert.equal(logic.sparkPoints([0, 5, 10], 60, 20), '0,20 30,10 60,0')
  assert.equal(logic.sparkPoints([0, 0], 60, 20), '0,20 60,20')
  assert.equal(logic.sparkPoints([4], 60, 20), '0,0 60,0')
  assert.equal(logic.sparkPoints([], 60, 20), '')
})

// ---------------------------------------------------------------- money and the budget bar

test('money reads in the words of each language: decimal comma and euro after the number in German', () => {
  assert.equal(logic.moneyText(1.234, 'de'), '1,23 €')
  assert.equal(logic.moneyText(1.234, 'en'), '€1.23')
  assert.equal(logic.moneyText(50, 'de'), '50 €')
  assert.equal(logic.moneyText(1234.5, 'de'), '1.234,50 €')
  assert.equal(logic.moneyText(1234.5, 'en'), '€1,234.50')
  assert.equal(logic.moneyText(12.3, 'en', 'USD'), '$12.30')
  assert.equal(logic.moneyText(12.3, 'de', 'GBP'), '12,30 GBP')
  assert.equal(logic.moneyText(-2, 'en'), '-€2')
  assert.equal(logic.moneyText(null, 'de'), '0 €')
})

test('the budget bar: the budget is the full width until the month runs past it', () => {
  assert.deepEqual(logic.budgetBar({ budget_month: 50, month_to_date: 10, forecast_month: 40 }),
    { fill: 0.2, forecast: 0.8, budget: 1, tone: 'success' })
  const warn = logic.budgetBar({ budget_month: 50, month_to_date: 25, forecast_month: 100 })
  assert.deepEqual(warn, { fill: 0.25, forecast: 1, budget: 0.5, tone: 'warning' })
  assert.equal(logic.budgetBar({ budget_month: 50, month_to_date: 60, forecast_month: 80 }).tone, 'danger')
  assert.equal(logic.budgetBar({ budget_month: 50, month_to_date: 5, forecast_month: null }).forecast, null)
  assert.equal(logic.budgetBar({ budget_month: null, month_to_date: 5 }), null)
  assert.equal(logic.budgetBar({ budget_month: 0, month_to_date: 5 }), null)
})

// ---------------------------------------------------------------- the cost view

const acc = (id, amounts, extra = {}) => ({
  id, display_name: id.toUpperCase(), provider: 'azure', kind: 'usage', ok: true, error: null, currency: 'EUR',
  days: amounts.map((a, i) => ({ day: `2026-10-${String(i + 1).padStart(2, '0')}`, amount: a, provisional: i >= amounts.length - 2,
    groups: a ? { Functions: a * 0.75, Storage: a * 0.25 } : {} })),
  month_to_date: amounts.reduce((x, y) => x + y, 0), forecast_month: 40, budget_month: 50, ...extra,
})
const costs = {
  schema: 1, kind: 'cloud-costs', host: 'my-server', at: '2026-10-10T06:15:00+02:00', currency: 'EUR', today: '2026-10-10',
  accounts: [
    acc('a', [1, 1, 1, 1, 1, 1, 1, 1, 2, 3]),
    acc('b', [2, 2, 2, 2, 2, 2, 2, 2, 2, 2], { kind: 'fixed', provider: 'contract' }),
    acc('c', [0, 0, 0, 0, 0, 0, 0, 0, 0.5, 0]),
    acc('d', [0, 0, 0, 0, 0, 0, 0, 0, 0.2, 0.1]),
    { id: 'broken', display_name: 'Broken', provider: 'aws', ok: false, error: 'needs ce:GetCostAndUsage', days: [], month_to_date: null, forecast_month: null },
  ],
}

test('the cost window: seven days, thirty days or the calendar month, ending today', () => {
  assert.deepEqual(logic.costWindow(costs, '7'), ['2026-10-04', '2026-10-05', '2026-10-06', '2026-10-07', '2026-10-08', '2026-10-09', '2026-10-10'])
  assert.equal(logic.costWindow(costs, '30').length, 30)
  assert.equal(logic.costWindow(costs, '30')[0], '2026-09-11')
  assert.equal(logic.costWindow(costs, 'month').length, 10)
  assert.equal(logic.costWindow(costs, 'month')[0], '2026-10-01')
  assert.deepEqual(logic.costWindow(null, '7'), [])
})

test('cost bars: a bar per day of the window, the three dearest accounts and the rest, provisional days marked', () => {
  const bars = logic.costBars(costs, '7')
  assert.equal(bars.days.length, 7)
  assert.deepEqual(bars.keys, ['b', 'a', 'c', logic.SERIES_REST])
  const last = bars.days[bars.days.length - 1]
  assert.equal(last.day, '2026-10-10')
  assert.equal(last.provisional, true)
  assert.equal(Math.round(last.total * 100), 510)
  assert.equal(bars.days[0].provisional, false)
  // a day the file does not have (before the window it measured) is an empty day, not a gap
  assert.equal(logic.costBars(costs, '30').days[0].total, 0)
})

test('a picked day lists its accounts, dearest first, each with its largest groups', () => {
  const day = logic.costDay(costs, '2026-10-09')
  assert.deepEqual(day.map(x => x.id), ['a', 'b', 'c', 'd'])
  assert.deepEqual(day[0].groups, [['Functions', 1.5], ['Storage', 0.5]])
  assert.equal(day[0].name, 'A')
})

test('totals of the range and of the month, a yesterday per account, one tone per account', () => {
  const tot = logic.costTotals(costs, '7')
  assert.equal(Math.round(tot.range * 100), Math.round((1 * 5 + 2 + 3 + 14 + 0.5 + 0.3) * 100))
  assert.equal(Math.round(tot.month * 100), Math.round((13 + 20 + 0.5 + 0.3) * 100))
  assert.equal(logic.costYesterday(costs.accounts[0], costs.today), 2)
  assert.equal(logic.costYesterday(costs.accounts[4], costs.today), null)
  assert.equal(logic.costTone(costs.accounts[0]), 'success')
  assert.equal(logic.costTone(costs.accounts[4]), 'warning')
  assert.equal(logic.costTone({ ...costs.accounts[0], month_to_date: 60 }), 'danger')
  assert.equal(logic.costTone({ ...costs.accounts[0], budget_month: null }), 'neutral')
})

test('the overview tile: yesterday, the month so far, seven little bars and the worst tone', () => {
  const b = logic.costBoard(costs)
  assert.equal(Math.round(b.yesterday * 100), 470)
  assert.equal(b.week.length, 7)
  assert.equal(b.week[6].frac, 1)
  assert.equal(b.tone, 'warning')   // the failed account
  assert.equal(logic.costBoard({ ...costs, accounts: costs.accounts.slice(0, 2) }).tone, 'success')
  assert.equal(logic.costBoard({ ...costs, stale: true, accounts: costs.accounts.slice(0, 2) }).tone, 'warning')
})

// ---------------------------------------------------------------- tokens by dimension

test('tokens split by Bridge, model, source or project for the stacked bars', () => {
  const d = {
    sources: { session: { output: 30 }, subagent: { output: 10 }, worker: { output: 0 } },
    models: [{ model: 'claude-x', output: 25 }, { model: 'claude-y', output: 15 }],
    projects: [{ project: 'demo', output: 40 }],
    bridges: [{ bridge: 'main', host: 'my-laptop', output: 30 }, { bridge: null, host: 'my-laptop', output: 6 }, { bridge: 'main', host: 'my-server', output: 4 }],
  }
  assert.deepEqual(logic.usageParts(d, 'source'), { session: 30, subagent: 10, worker: 0 })
  assert.deepEqual(logic.usageParts(d, 'model'), { 'claude-x': 25, 'claude-y': 15 })
  assert.deepEqual(logic.usageParts(d, 'project'), { demo: 40 })
  assert.deepEqual(logic.usageParts(d, 'bridge'), { main: 34, [logic.NO_BRIDGE]: 6 })
  assert.deepEqual(logic.usageParts({}, 'bridge'), {})
  // usage.py lists at most eight per day: what the list leaves out goes to the rest, so every split sums to the day
  const many = { output: 12000, sources: { session: { output: 12000 } },
    projects: Array.from({ length: 8 }, (_, i) => ({ project: `p${i}`, output: 1000 })) }
  const parts = logic.usageParts(many, 'project')
  assert.equal(parts[logic.SERIES_REST], 4000)
  assert.equal(Object.values(parts).reduce((a, x) => a + x, 0), 12000)
  for (const dim of logic.USAGE_DIMS) assert.equal(logic.stackBars([many], x => logic.usageParts(x, dim)).total, 12000, dim)
  const bars = logic.stackBars([many], x => logic.usageParts(x, 'project'))
  assert.deepEqual(bars.keys, ['p0', 'p1', 'p2', logic.SERIES_REST])      // the remainder is never a named series
  assert.equal(bars.days[0].parts.find(p => p.key === logic.SERIES_REST).value, 9000)
  assert.deepEqual(logic.USAGE_RANGES, [7, 30, 90])
  assert.deepEqual(logic.USAGE_DIMS, ['bridge', 'model', 'source', 'project'])
})

// ---------------------------------------------------------------- words

test('the cost and token words exist in both languages, German without dashes', () => {
  for (const lang of ['de', 'en']) {
    const t = text.TABLES[lang]
    for (const k of ['costsTitle', 'costsRanges', 'costsMeasured', 'costsStale', 'costsProvisional', 'costsLogin', 'costsKeyHint',
      'costsEmpty', 'costsTotal', 'costsYesterday', 'costsMonth', 'costsOf', 'costsRest', 'costsReload', 'costsTile',
      'usageRanges', 'usageDims', 'usagePerBridge', 'usageNoBridge', 'usageUnreachable', 'usagePending', 'usageMeasured', 'usageReload', 'usageRest']) {
      assert.ok(t[k], `${lang}.${k}`)
    }
  }
  const de = JSON.stringify(Object.fromEntries(Object.entries(text.TABLES.de).filter(([k]) => /^costs|^usage/.test(k))
    .map(([k, v]) => [k, typeof v === 'function' ? v(2, 2, 2) : v])))
  assert.ok(!/[–—]|--/.test(de), de)
})

// ---------------------------------------------------------------- the cards as rendered, against mock.js

test('the cost card draws a bar per day, a row per account, and offers the login command of the one that needs it', async () => {
  const { loadCockpit, mount, cockpitState, recorder } = await import('./cockpit_render.mjs')
  const { html, views, mock, text: tx } = await loadCockpit()
  tx.setLanguage('de')
  const tr = mock.createMockTransport({ lang: 'de', latency: 0 })
  const view = (await tr.get('/api/costs')).data.view
  const c = recorder()
  const s = cockpitState(Date.now(), { costs: { status: 'ok', data: view, error: null } })
  const el = mount(html`<${views.costs.CostCard} page=${{ id: 'ops' }} s=${s} c=${c} />`)
  assert.equal(el.$('.sec-title').text(), 'Cloud-Kosten')
  assert.equal(el.$$('.ubar').length, 7)
  assert.equal(el.$$('.crow').length, view.accounts.length)
  assert.ok(el.$$('.ubar.is-provisional').length >= 1)
  assert.ok(el.$$('.ukey').length <= 5)   // at most four series and the provisional note
  const failed = el.$('.crow.is-failed')
  assert.match(failed.text(), /Anmeldung nötig/)
  assert.match(failed.$('code').text(), /secrets\.sh store/)
  failed.button('Befehl kopieren').click()
  assert.deepEqual(c.calls.find(x => x[0] === 'copy'), ['copy', view.accounts.find(a => a.login_command).login_command])
  // 30 days and the month are counted on the page from the same file
  el.button('30 Tage').click()
  await new Promise(r => setTimeout(r, 0))
  assert.equal(el.$$('.ubar').length, 30)
  assert.ok(el.$('.ubars.is-dense'))
  // a click on a day lists its accounts
  el.$$('.ubar')[29].click()
  await new Promise(r => setTimeout(r, 0))
  assert.ok(el.$('.uday .ulist li'))
  tx.setLanguage('en')
})

test('without a cost file the card says what to declare', async () => {
  const { loadCockpit, mount, cockpitState, recorder } = await import('./cockpit_render.mjs')
  const { html, views } = await loadCockpit()
  const s = cockpitState(Date.now(), { costs: { status: 'none', data: null, error: null } })
  const el = mount(html`<${views.costs.CostCard} page=${{ id: 'ops' }} s=${s} c=${recorder()} />`)
  assert.match(el.text(), /docs\/cloud-costs\.md/)
})

test('the token card splits by Bridge, lists each Bridge with its machine and names a machine that does not answer', async () => {
  const { loadCockpit, mount, cockpitState, recorder } = await import('./cockpit_render.mjs')
  const { html, views, mock } = await loadCockpit()
  const tr = mock.createMockTransport({ lang: 'en', latency: 0 })
  const usage = (await tr.get('/api/usage?days=30')).data.usage
  assert.equal(usage.days.length, 30)
  const c = recorder()
  const s = cockpitState(Date.now(), { usage: { status: 'ok', data: usage, error: null, days: 30 } })
  const el = mount(html`<${views.costs.UsageCard} page=${{ id: 'ops' }} s=${s} c=${c} />`)
  assert.equal(el.$$('.ubar').length, 30)
  assert.equal(el.$$('.brow').length, usage.bridges.length + usage.hosts.filter(h => !h.ok).length)
  assert.match(el.$('.brow.is-failed').text(), /my-workstation: not reachable/)
  // a machine whose first read is still running is being read, not unreachable
  const pending = { ...usage, hosts: [...usage.hosts, { host: 'my-nas', ok: false, pending: true, error: null, at: null, local: false }] }
  const el2 = mount(html`<${views.costs.UsageCard} page=${{ id: 'ops' }} s=${cockpitState(Date.now(), { usage: { status: 'ok', data: pending, error: null, days: 30 } })} c=${recorder()} />`)
  const rows = el2.$$('.brow').map(r => r.text())
  assert.ok(rows.some(r => /my-nas: being read/.test(r)), rows)
  assert.ok(!rows.some(r => /my-nas: not reachable/.test(r)), rows)
  assert.ok(el.$('.spark polyline'))
  assert.match(el.$('.ulegend').text(), /demo-bridge/)
  el.button('Model').click()
  await new Promise(r => setTimeout(r, 0))
  assert.match(el.$('.ulegend').text(), /opus-5-5/)
  el.button('90 days').click()
  assert.ok(c.calls.some(x => x[0] === 'loadUsage' && x[1] === 90))
})

test('the overview board shows a cost tile when the page places the cost card', async () => {
  const { loadCockpit, mount, cockpitState, recorder } = await import('./cockpit_render.mjs')
  const { html, views, mock } = await loadCockpit()
  const view = (await mock.createMockTransport({ lang: 'en', latency: 0 }).get('/api/costs')).data.view
  const s = cockpitState(Date.now(), { costs: { status: 'ok', data: view, error: null } })
  const page = { id: 'ops', title: 'Ops', overview: true, sections: [], cards: [{ id: 'costs', after: null }] }
  const el = mount(html`<${views.pages.OverviewBoard} page=${page} s=${s} c=${recorder()} />`)
  assert.equal(el.$$('.otile-bar').length, 7)
  const none = mount(html`<${views.pages.OverviewBoard} page=${{ ...page, cards: null }} s=${s} c=${recorder()} />`)
  assert.equal(none.$$('.otile-bar').length, 0)
})

test('the cost card names every machine whose report it merges', () => {
  assert.equal(logic.costSources({ sources: [{ host: 'my-server' }, { host: 'my-laptop' }, { host: 'my-server' }] }), 'my-server, my-laptop')
  assert.equal(logic.costSources({ host: 'my-server', source: 'ssh:my-server:/x' }), 'my-server')
  assert.equal(logic.costSources({ sources: [{ source: '/tmp/costs.json' }] }), '/tmp/costs.json')
  assert.equal(logic.costSources(null), '')
})
