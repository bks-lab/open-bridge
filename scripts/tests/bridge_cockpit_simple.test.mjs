// SPDX-License-Identifier: MIT
// Tests of stage 4 of the one point view, simpler (scripts/web/point.js, flow.js and the views of Work through), no npm
// dependencies.
//
//   node --test scripts/tests/bridge_cockpit_simple.test.mjs
//
// A point says three things: its name (a task's H1, an inbox item's brief name, the brief name where a title is a
// slug or too long), where it stands (the brief's stand, else the triage's gist) and its next step with who takes it.
// The overview bands by who takes the next step (Check-in, Needs you, the Bridge does it); the right column has one
// strong button, the four states and More; In progress hands a point to someone until a check-in day, Running
// elsewhere holds it until then, and on the day it comes back as a check-in with its answers on the card.
import test from 'node:test'
import assert from 'node:assert/strict'
import { cockpitState, loadCockpit, mount, recorder, settle as rounds } from './cockpit_render.mjs'

const { html, views, text, logic } = await loadCockpit()
const en = text.TABLES.en
const de = text.TABLES.de
const tick = () => rounds()
const until = async (ok, ms = 2000) => { for (const end = Date.now() + ms; !ok() && Date.now() < end;) await tick() }
const proto = Object.getPrototypeOf(document.createElement('div'))
if (!proto.querySelector) proto.querySelector = function querySelector(sel) { return this.$(sel) }
proto.focus ??= function focus() { document.activeElement = this }
globalThis.window ??= { addEventListener() {}, removeEventListener() {}, innerWidth: 1280 }
for (const k of ['offsetLeft', 'offsetWidth', 'scrollWidth', 'clientWidth']) Object.defineProperty(proto, k, { get: () => 0, configurable: true })

// a fixed local "now": Friday, 9 October 2026, noon (the moment the other suites use)
const NOW = new Date(2026, 9, 9, 12, 0, 0).getTime()
const MIN = 60000
const TODAY = '2026-10-09'

const card = (over = {}) => ({ title: null, name: null, stand: null, goal: null, next: null, ...over })
const task = (slug, over = {}) => ({ key: `task:${slug}`, task: slug, title: `Task ${slug}`, status: 'doing', bucket: 'tasks',
  priority: 'P2', settle: ['done', 'not_doing'], card: card(), ...over })
const ask = (id, over = {}) => ({ key: `inbox:${id}`, inbox_id: id, title: `Question ${id}`, art: 'ask', inbox_state: 'open',
  bucket: 'do', gate: 'only-you', settle: ['done', 'not_doing'], card: card(), ...over })
const ref = (repo, n, over = {}) => ({ key: `ref:${repo}#${n}`, ref: `${repo}#${n}`, title: `Issue ${n} of ${repo}`, bucket: 'plan',
  section: 'now', url: `https://github.com/${repo}/issues/${n}`, settle: ['done', 'not_doing'], card: card(), ...over })
const next = (what, who, extra = {}) => ({ what, who, due: null, from: 'status', since: null, check: null, ...extra })

function state({ now = [], work = [], later = [], hidden = [], tabs = [], pages = [], ui = {}, flow = true, ...rest } = {}) {
  return {
    now: NOW, model: { sections: [{ id: 'now', rows: now }, { id: 'give', rows: [] }, { id: 'work', rows: work },
      { id: 'track', rows: [] }, { id: 'later', rows: later }], hidden, returns: [], pages },
    tabs: { tabs }, driver: { caps: null }, triage: { items: {} }, jevOrder: {},
    work: { flow: { enabled: flow, drop_reasons: ['resolves_itself', 'not_needed'], return_after_s: 20 }, person: 'Mara' },
    themes: { enabled: false }, details: { inbox: {}, task: {}, activity: {} },
    ui: { page: 'briefing', workView: 'flow', busy: {}, flowAt: null, flowChip: 'all', flowJump: null, flowView: 'overview', ...ui }, ...rest,
  }
}
const flowState = (over = {}) => cockpitState(NOW, state(over))
const { FlowPage } = views.flow
const pointAt = (key, over = {}) => ({ flowView: 'point', flowAt: { id: key, i: 0 }, ...over })

// ---------------------------------------------------------------- A: a point says three things

test('A1 the name: an inbox item its brief name, a task its H1 unless a slug or over 60 characters, the original title kept', () => {
  assert.equal(logic.pointName(ask('20261009-0900-a-q', { title: 'Look at the backup log of the night', card: card({ name: 'Night backup' }) })), 'Night backup')
  assert.equal(logic.pointName(ask('20261009-0900-a-q', { title: 'Renew the domain' })), 'Renew the domain', 'no name: its title')
  assert.equal(logic.pointName(task('a', { title: 'Portal redesign', card: card({ name: 'Another name' }) })), 'Portal redesign', 'an H1 stands')
  assert.equal(logic.pointName(task('a', { title: 'portal-redesign-v2', card: card({ name: 'Portal redesign' }) })), 'Portal redesign', 'a slug gives way')
  const long = 'Portal redesign: everything the new portal should do one day, with every page and its owner'
  assert.equal(logic.pointName(task('a', { title: long, card: card({ name: 'Portal redesign' }) })), 'Portal redesign')
  assert.equal(logic.pointName(task('a', { title: long })), long, 'without a name the title stays whole')
  assert.equal(logic.pointOriginal(task('a', { title: long, card: card({ name: 'Portal redesign' }) })), long)
  assert.equal(logic.pointOriginal(task('a', { title: 'Portal redesign' })), null)
})

test('A2 the stand: the brief\'s sentence, else the triage\'s gist, else nothing', () => {
  const q = ask('20261009-0900-a-q', { card: card({ stand: 'The invoice is due since Monday, no payment found.' }) })
  const s = { triage: { items: { [q.key]: { gist: 'Pay the invoice' } } } }
  assert.equal(logic.pointStand(q, s), 'The invoice is due since Monday, no payment found.')
  assert.equal(logic.pointStand({ ...q, card: card() }, s), 'Pay the invoice')
  assert.equal(logic.pointStand({ ...q, card: card() }, { triage: { items: {} } }), null)
})

test('A3 the next step: its words, who as you, the Bridge or a person, its due or check-in day', () => {
  const s = { work: { person: 'Mara' } }
  assert.deepEqual(logic.pointStep(task('a', { card: card({ next: next('Send the draft', 'me', { due: '2026-10-12' }) }) }), s),
    { what: 'Send the draft', who: 'me', whoKind: 'me', due: '2026-10-12', check: null })
  assert.equal(logic.pointStep(task('a', { card: card({ next: next('Send it', 'bridge') }) }), s).whoKind, 'bridge')
  assert.equal(logic.pointStep(task('a', { card: card({ next: next('Send it', 'mara') }) }), s).whoKind, 'me', 'the owner by name')
  assert.equal(logic.pointStep(task('a', { card: card({ next: next('Send it', 'lena') }) }), s).whoKind, 'person')
  assert.equal(logic.pointStep(task('a', { checkin: { who: 'lena', until: '2026-10-12', since: '2026-10-05' }, card: card({ next: next('Send it', 'lena') }) }), s).check,
    '2026-10-12', 'a check-in day from the row')
  assert.equal(logic.pointStep(task('a'), s), null)
})

// ---------------------------------------------------------------- B4: bands by who takes the next step

test('B4 the overview bands by who takes the next step: check-in on top, needs you, the Bridge does it', () => {
  const mine = task('mine', { card: card({ next: next('Decide', 'me') }) })
  const bridge = task('bridge', { card: card({ next: next('Run the tests', 'bridge') }) })
  const due = task('due', { checkin: { who: 'lena', until: TODAY, since: '2026-10-02' }, card: card({ next: next('Sign it', 'lena') }) })
  const q = ask('20261009-0900-a-q', { card: card({ next: next('decide', 'me') }) })
  const s = state({ now: [q], work: [mine, bridge, due] })
  const parts = logic.flowParts(s)
  assert.deepEqual(parts.checkin.map(x => x.row.key), ['task:due'])
  const bands = views.flowlist.bandsOf(logic.flowQueue(parts, 'all'), null, s)
  assert.deepEqual(bands.map(b => b.band), ['checkin', 'you', 'bridge'])
  assert.deepEqual(bands.find(b => b.band === 'bridge').rows.map(r => r.id), ['task:bridge'])
  assert.ok(bands.find(b => b.band === 'you').rows.some(r => r.id === q.key) && bands.find(b => b.band === 'you').rows.some(r => r.id === 'task:mine'))
  assert.deepEqual(logic.FLOW_BANDS, ['checkin', 'you', 'bridge'])
  assert.deepEqual([en.flow.groups.checkin, de.flow.groups.checkin, de.flow.groups.you, de.flow.groups.bridge],
    ['Check-in', 'Nachfrage', 'Braucht dich', 'Bridge macht'])
})

// ---------------------------------------------------------------- C: In progress with a check-in

test('C1 to C3 the check-in: set, it waits under Running elsewhere, it comes back on its day as a check-in', () => {
  const later = '2026-10-16'
  const waiting = ask('20261009-0900-a-q', { inbox_state: 'deferred', until: later, checkin: { who: 'lena', until: later, since: TODAY } })
  const taskAway = task('away', { bucket: 'waiting', checkin: { who: 'lena', until: later, since: TODAY }, card: card({ next: next('Sign it', 'lena') }) })
  const back = task('back', { bucket: 'waiting', checkin: { who: 'lena', until: '2026-10-08', since: '2026-10-01' }, card: card({ next: next('Sign it', 'lena') }) })
  const s = state({ later: [waiting], work: [taskAway, back] })
  const parts = logic.flowParts(s)
  const running = parts.leftOut.groups.find(g => g.reason === 'running')
  assert.ok(running, 'a group Running elsewhere')
  assert.deepEqual(running.rows.map(e => e.row.key).sort(), [waiting.key, 'task:away'].sort())
  assert.ok(running.rows.every(e => e.kind === 'checkin' && e.who === 'lena' && e.until === later))
  assert.deepEqual(parts.checkin.map(x => x.row.key), ['task:back'], 'its day came: a check-in')
  assert.equal(parts.leftOut.groups[0].reason, 'running', 'Running elsewhere first among Not now')
  assert.deepEqual(logic.FLOW_LEFT_OUT, ['running', 'later', 'idea', 'stream', 'github'])
  // the days In progress offers, and who it can go to
  assert.deepEqual(logic.checkinDays(NOW), { 3: '2026-10-12', 7: '2026-10-16', 14: '2026-10-23' })
  const who = logic.workWho(state({ work: [taskAway, task('x', { card: card({ next: next('Go', 'jan') }) })] }))
  assert.deepEqual(who.slice(0, 2), ['me', 'bridge'])
  assert.ok(who.includes('lena') && who.includes('jan'))
  // Back on of a check-in: the inbox item opens again, the task's step comes back to its owner
  const plan = logic.leftPlan(running.rows, 'back', s)
  assert.deepEqual(plan.calls.map(c => c.verb).sort(), ['inbox_reopen', 'task_next'])
  assert.deepEqual(plan.calls.find(c => c.verb === 'task_next').args, { slug: 'away', who: 'me', clear_check: true })
  assert.deepEqual([en.flow.notnow.group.running, de.flow.notnow.group.running], ['Running elsewhere', 'Läuft'])
})

test('C3 the check-in card: since when with whom, its answers on the card, no 2x2 and no strong button beside it', async () => {
  const back = task('back', { bucket: 'waiting', checkin: { who: 'lena', until: '2026-10-08', since: '2026-10-01' },
    card: card({ next: next('Sign it', 'lena', { check: '2026-10-08' }) }) })
  // a suggestion stands for the row, yet the card answers: the right column keeps More only
  const themes = { enabled: true, assign: {}, themes: [], suggest: { 'task:back': { verb: 'later', reason: 'x', at_ms: NOW } } }
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${{ ...flowState({ work: [back], ui: pointAt('task:back') }), themes }} c=${c} />`)
  const head = el.$('.flow-card .fx-sub').text()
  assert.equal(head, en.flow.simple.since(logic.formatDay('2026-10-01', 'en'), 'Lena'))
  const answers = el.$$('.flow-checkin-acts button').map(b => b.text())
  assert.deepEqual(answers, [en.flow.verbs.done, `${en.flow.simple.still} ▾`, en.flow.simple.stuck, `${en.flow.verbs.drop} ▾`, en.flow.simple.chaseButton('Lena')])
  assert.equal(el.$('.flow-aside .verbbar-grid'), null, 'no 2x2')
  assert.equal(el.$('.flow-aside .verbbar-strong'), null, 'no strong button')
  assert.ok(el.$('.flow-aside .flow-more-toggle'), 'More stays')
  // Still running: a new day with the same person; Stuck: back to the owner with why; Follow up: a draft, never sent
  el.button(`${en.flow.simple.still} ▾`).click()
  await tick()
  el.button(en.flow.simple.inDays(7)).click()
  await until(() => c.calls.some(x => x[0] === 'act'))
  assert.deepEqual(c.calls.find(x => x[0] === 'act'), ['act', 'work_on', { key: 'task:back', who: 'lena', until: '2026-10-16' }])
  const c2 = recorder()
  const el2 = mount(html`<${FlowPage} s=${flowState({ work: [back], ui: pointAt('task:back') })} c=${c2} />`)
  el2.button(en.flow.simple.stuck).click()
  await tick()
  el2.button(en.flow.simple.stuckGo).click()
  await until(() => c2.calls.some(x => x[0] === 'act'))
  assert.deepEqual(c2.calls.find(x => x[0] === 'act'), ['act', 'checkin_stuck', { key: 'task:back' }])
  const c3 = recorder()
  const el3 = mount(html`<${FlowPage} s=${flowState({ work: [back], ui: pointAt('task:back') })} c=${c3} />`)
  el3.button(en.flow.simple.chaseButton('Lena')).click()
  await until(() => c3.calls.some(x => x[0] === 'act'))
  const [, verb, args] = c3.calls.find(x => x[0] === 'act')
  assert.equal(verb, 'do_it')
  assert.match(args.note, /never send it/)
  assert.match(de.flow.simple.chase('Lena', 'x'), /nichts senden/)
})

// ---------------------------------------------------------------- B1: one strong button, four states, More

test('B1 the strong button applies the AI\'s suggestion with its verb and step, else your yes, else the Bridge\'s step', () => {
  const s = state()
  const t = task('a', { card: card({ next: next('Switch the probe', 'bridge') }) })
  assert.deepEqual(logic.strongOf({ row: t }, s, { verb: 'do', reason: 'It can run alone' }), { verb: 'do', sug: true, step: 'Switch the probe' })
  assert.deepEqual(logic.strongOf({ row: t }, s, null), { verb: 'do', sug: false, step: 'Switch the probe' }, 'the Bridge\'s own step')
  const yes = ask('20261009-0900-a-q', { gate: 'your-yes', has_action: true })
  assert.deepEqual(logic.strongOf({ row: yes }, s, null), { verb: 'yes' })
  assert.equal(logic.strongOf({ row: task('b', { card: card({ next: next('Decide', 'me') }) }) }, s, null), null, 'your own step: no strong button')
  assert.deepEqual(logic.SIMPLE_STATES, ['done', 'work', 'later', 'drop'])
})

test('B1 the menu More holds every other verb that applies, per kind, none that cannot', () => {
  const s = state()
  assert.deepEqual(logic.moreOf({ kind: 'row', row: ask('20261009-0900-a-q') }, s), ['task', 'describe', 'advise'])
  assert.deepEqual(logic.moreOf({ kind: 'row', row: task('a') }, s), ['net', 'describe', 'advise'])
  assert.deepEqual(logic.moreOf({ kind: 'row', row: task('a', { adopt_candidates: [{ ref: 'surface:1', name: 'notes', workspace: 'Demo' }] }) }, s),
    ['net', 'describe', 'advise', 'adopt'])
  assert.deepEqual(logic.moreOf({ kind: 'row', row: ref('acme/app', 7) }, s), ['github', 'advise'])
  assert.deepEqual(logic.moreOf({ kind: 'row', row: ref('acme/app', 7) }, s, { board: true }), ['github', 'board', 'advise'])
  const hidden = task('h', { hidden_until: '2026-10-20' })
  assert.ok(logic.moreOf({ group: 'left', left: 'later', kind: 'row', row: hidden, entry: { row: hidden, why: 'hidden', kind: 'later' } }, s).includes('back'))
  assert.deepEqual(logic.moreOf({ kind: 'row', row: task('a') }, { ...s, boot: { config: { person: 'lena' } } }), [], 'a person: none of the owner\'s')
})

// ---------------------------------------------------------------- after the first review: every line a person reads

const LONG = 'config: docs/setup.md still names port 8790 after the switch to cockpit.port in scripts/web/config.yaml'
const withInstruct = st => ({ ...st, work: { ...st.work, flow: { ...st.work.flow, instruct: { enabled: true, budget_per_day: 30, model: null } } } })

test('A1 every line a person reads names the point by its name: the instruction line, Ask, a plan\'s points, Merge, Related', async () => {
  const q = ask('20261009-0900-a-q', { title: LONG, card: card({ name: 'Update the setup docs' }) })
  const st = withInstruct(flowState({ now: [q], ui: pointAt(q.key) }))
  const parts = logic.flowParts(st)
  const x = logic.flowQueue(parts, 'all').find(p => p.row?.key === q.key)
  assert.equal(logic.instructScope(x, [x], new Set(), 'Ops', st).title, 'Update the setup docs')
  const el = mount(html`<${FlowPage} s=${st} c=${recorder()} />`)
  assert.ok(el.$('.flow-instruct-scope').text().startsWith(en.flow.instruct.point('Update the setup docs')), el.$('.flow-instruct-scope').text())
  for (const part of ['.flow-card', '.flow-aside', '.flow-instruct', '.flow-walk']) {
    assert.ok(!(el.$(part)?.text() ?? '').includes(LONG), `${part}: the raw title stands only under Details and in the fold What else is stored`)
  }
  // Ask names it the same way
  const ak = mount(html`<${FlowPage} s=${{ ...st, ui: { ...st.ui, flowLine: 'ask' } }} c=${recorder()} />`)
  assert.equal(ak.$('.flow-instruct-scope').text(), en.flow.instruct.point('Update the setup docs'))
  // a plan the server words with the raw title: the page names its points by their name
  const plan = { id: 'p1', text: 'done', point: true, n: 1, steps: [{ n: 1, op: 'done', keys: [q.key], titles: [LONG], skipped: [] }], at_ms: NOW }
  const pl = mount(html`<${FlowPage} s=${{ ...st, ui: { ...st.ui, flowPlan: plan } }} c=${recorder()} />`)
  assert.match(pl.$('.flow-instruct-step').text(), /Update the setup docs/)
  assert.ok(!pl.$('.flow-instruct-step').text().includes('cockpit.port'))
  // Merge and Related name the tasks by their name
  const a = task('a', { title: 'setup-docs', card: card({ name: 'The setup docs' }) })
  const b = task('b', { title: 'Task b' })
  const two = flowState({ work: [a, b], ui: { flowView: 'overview', flowPicked: ['task:a', 'task:b'] } })
  const mg = mount(html`<${FlowPage} s=${two} c=${recorder()} />`)
  mg.button(`${en.flow.merge.button} ▾`).click()
  await tick()
  assert.ok(mg.$$('.flow-merge-title').map(t => t.text()).includes('The setup docs'))
  // the item's Related names the task it belongs to by the task's name, not its slug of an H1
  const rel = mount(html`<${FlowPage} s=${flowState({ work: [a, ask('20261009-0901-b-q', { task: 'a', title: LONG, card: card({ name: 'The port in the docs' }) })],
    ui: pointAt('inbox:20261009-0901-b-q', { flowTab: 'related' }) })} c=${recorder()} />`)
  const related = rel.$$('.flow-related-open').map(b => b.text())
  assert.ok(related.includes('The setup docs') && !related.includes('setup-docs'), related.join(' | '))
})

test('A2 a row whose only word is its tab\'s state says it is the tab\'s: Agent tab: finished, never a bare Finished', () => {
  // the demo's start that finished with a result, under Needs you
  const demo = mount(html`<${FlowPage} s=${cockpitState(NOW, { ui: { page: 'briefing', workView: 'flow', flowView: 'overview', flowPicked: [] } })} c=${recorder()} />`)
  const fin = demo.$$('.flow-ov-row').find(r => r.$('.flow-ov-open').text() === 'Settle the invoice format with the vendor')
  assert.equal(fin.$('.flow-ov-stand').text(), en.flow.simple.tabIs(en.flow.simple.tabState.result))
  assert.ok(!demo.$$('.flow-ov-stand').some(x => [en.flow.kind.result, en.flow.kind.idle, en.flow.kind.lost, en.flow.kind.asks].includes(x.text())),
    'no bare tab state under a name')
  // a tab that waits at its prompt: the card head says the same, the line says it is the tab's
  const st = flowState({ work: [task('wt'), task('rev', { status: 'review' })],
    tabs: [{ ref: 'surface:10', name: 'wt', slug: 'wt', state: 'waiting', since_ms: NOW - 25 * MIN }],
    returns: [{ key: 'task:wt', item: 'wt', title: 'Task wt', mode: 'go', at_ms: NOW - 30 * MIN, stage: 'result', in_briefing: true,
      tab: { ref: 'surface:10' }, result: { kind: 'note', text: 'Result: nothing to do', key: null, at_ms: null } }],
    ui: { flowView: 'overview', flowPicked: [] } })
  const el = mount(html`<${FlowPage} s=${st} c=${recorder()} />`)
  const stand = name => el.$$('.flow-ov-row').find(r => r.$('.flow-ov-open').text() === name).$('.flow-ov-stand').text()
  assert.equal(stand('Task wt'), en.flow.simple.tabIs(en.flow.simple.tabState.waits))
  assert.equal(en.flow.simple.tabIs(en.flow.simple.tabState.result), 'Agent tab: finished')
  assert.equal(de.flow.simple.tabIs(de.flow.simple.tabState.result), 'Agenten-Tab: fertig')
  for (const k of ['asks', 'waits', 'result', 'idle', 'done', 'lost']) for (const t of [en, de]) assert.ok(t.flow.simple.tabState[k], k)
  // a task's own state stays its own
  assert.equal(stand('Task rev'), en.flow.kind.task)
})

test('B2 the field Who says who and its state in a few words, the whole line on hover', () => {
  const live = { ref: 'surface:21', name: 'a research', slug: 'a', state: 'waiting', since_ms: NOW - 11 * MIN }
  const el = mount(html`<${FlowPage} s=${flowState({ work: [task('a')], tabs: [live], ui: pointAt('task:a') })} c=${recorder()} />`)
  const who = el.$('.flow-aside [data-field=who] dd span')
  assert.equal(who.text(), en.flow.simple.whoTab(en.flow.doing.stage.waiting))
  assert.equal(who.text(), 'Agent tab (waiting)')
  assert.match(who.getAttribute('title'), /a research/)
  assert.equal(de.flow.simple.whoTab(de.flow.doing.stage.waiting), 'Agenten-Tab (wartet)')
  assert.equal(en.flow.simple.whoBridge(en.flow.doing.stage.working), 'Bridge (at work)')
  assert.equal(de.flow.simple.whoBridge(de.flow.doing.stage.working), 'Bridge (arbeitet)')
  assert.equal(logic.whoBrief({ by: 'start', stage: 'working', since_ms: NOW - 6 * MIN }, 'en'), 'Bridge (at work)')
  assert.equal(logic.whoBrief({ by: 'none', days: 3 }, 'en'), null, 'nobody: the line says when it last moved')
})

test('C2 Running elsewhere says on whom a row waits by name, never a raw me', () => {
  const mine = ask('20261009-0900-a-w', { bucket: 'waiting', card: card({ next: next('read', 'me') }) })
  const lenas = ask('20261009-0901-b-w', { bucket: 'waiting', card: card({ next: next('answer', 'lena') }) })
  const el = mount(html`<${FlowPage} s=${flowState({ later: [mine, lenas], ui: { flowView: 'left', flowLeft: 'running', flowLeftPicked: [] } })} c=${recorder()} />`)
  const why = Object.fromEntries(el.$$('.flow-ov-row').map(tr => [tr.$('.flow-ov-open').text(), tr.$('.flow-ov-why').text()]))
  assert.equal(why[mine.title], en.flow.notnow.why.others)
  assert.equal(why[lenas.title], en.flow.notnow.why.waits('Lena'))
})

test('C1 the free date of In progress says it is optional, its parse unchanged', async () => {
  const el = mount(html`<${FlowPage} s=${flowState({ work: [task('a')], ui: pointAt('task:a') })} c=${recorder()} />`)
  el.button(`${en.flow.simple.work} ▾`).click()
  await tick()
  const date = el.$$('.flow-work input').find(i => i.getAttribute('aria-label') === en.flow.simple.dateLabel)
  assert.equal(date.getAttribute('placeholder'), en.flow.simple.dateHint)
  assert.deepEqual([en.flow.simple.dateHint, de.flow.simple.dateHint], ['or a date', 'oder ein Datum'])
})
