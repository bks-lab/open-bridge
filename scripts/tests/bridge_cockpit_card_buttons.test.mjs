// SPDX-License-Identifier: MIT
// Tests of the buttons of a card (cockpit-card-buttons, step 2 of a card that is useful or out of the way), no npm
// dependencies.
//
//   node --test scripts/tests/bridge_cockpit_card_buttons.test.mjs
//
// Every point of Work through has Give it to the AI: three ways, each a verb the server knows (Let it do it do_it,
// Advise advise, Collect context collect_context), the one its sort fits picked first. A reminder (its asks are
// someone else's) has its own strong button, Draft the message to <who>, and I asked, which waits for the answer
// with that person. An inbox item's Drop is Out of date (an idea's Discard), with reasons of its own and the AI's
// why written in where the card found it out of date.

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

const card = (over = {}) => ({ title: null, name: null, stand: null, goal: null, next: null, ...over })
const task = (slug, over = {}) => ({ key: `task:${slug}`, task: slug, title: `Task ${slug}`, status: 'doing', bucket: 'tasks',
  priority: 'P2', settle: ['done', 'not_doing'], card: card(), ...over })
const item = (id, over = {}) => ({ key: `inbox:${id}`, inbox_id: id, inbox_kind: 'question', title: `Question ${id}`, art: 'ask', inbox_state: 'open',
  bucket: 'do', gate: 'only-you', settle: ['done', 'not_doing'], card: card(), ...over })
const ref = (repo, n, over = {}) => ({ key: `ref:${repo}#${n}`, ref: `${repo}#${n}`, title: `Issue ${n} of ${repo}`, bucket: 'plan',
  section: 'now', url: `https://github.com/${repo}/issues/${n}`, settle: ['done', 'not_doing'], card: card(), ...over })

function state({ now = [], work = [], later = [], ui = {}, ...rest } = {}) {
  return {
    now: NOW, model: { sections: [{ id: 'now', rows: now }, { id: 'give', rows: [] }, { id: 'work', rows: work },
      { id: 'track', rows: [] }, { id: 'later', rows: later }], hidden: [], returns: [], pages: [] },
    tabs: { tabs: [] }, driver: { caps: null }, triage: { items: {} }, jevOrder: {},
    work: { flow: { enabled: true, drop_reasons: ['resolves_itself', 'not_needed'], return_after_s: 20 }, person: 'Mara' },
    themes: { enabled: false }, details: { inbox: {}, task: {}, activity: {} },
    ui: { page: 'briefing', workView: 'flow', busy: {}, flowAt: null, flowChip: 'all', flowJump: null, flowView: 'overview', ...ui }, ...rest,
  }
}
const flowState = (over = {}) => cockpitState(NOW, state(over))
const { FlowPage } = views.flow
const pointAt = key => ({ flowView: 'point', flowAt: { id: key, i: 0 } })
const acts = c => c.calls.filter(x => x[0] === 'act')
// a field's value as the page set it (a property, else the attribute the test DOM keeps)
const valueOf = el => el.value ?? el.getAttribute('value')

const ASK_LENA = item('20261009-0900-ask-lena', { title: 'Ask Lena five open points',
  card: card({ to: 'Lena', ask: ['May we name you as the model?', 'Is the contract a frame or a draft?'] }) })

// ---------------------------------------------------------------- A: the sort of a card

test('A1 the sort: a reminder where its asks are someone else\'s, else the inbox kind, a task, an issue', () => {
  assert.equal(logic.cardSort(ASK_LENA), 'reminder')
  assert.equal(logic.cardSort(item('a', { card: card({ to: 'me' }) })), 'question', 'asks of you are a question')
  for (const kind of ['decision', 'question', 'finding', 'draft', 'result', 'idea']) assert.equal(logic.cardSort(item('a', { inbox_kind: kind })), kind)
  assert.equal(logic.cardSort(item('a', { inbox_kind: null })), 'question', 'an item without a kind asks')
  assert.equal(logic.cardSort(task('a')), 'task')
  assert.equal(logic.cardSort(ref('org/repo', 7)), 'issue')
  assert.equal(logic.cardSort({ key: 'due:x' }), 'other')
  assert.equal(logic.reminderTo(ASK_LENA), 'Lena')
  assert.equal(logic.reminderTo(item('a', { card: card({ to: 'ich' }) })), null)
})

// ---------------------------------------------------------------- B: Give it to the AI

test('B1 the ways to the AI: three, Collect context only where its verb works, the first one by sort', () => {
  assert.deepEqual(logic.AI_MODES, ['go', 'report', 'context'])
  const first = row => logic.aiOf(row).mode
  assert.equal(first(item('a', { inbox_kind: 'finding' })), 'go')
  assert.equal(first(item('a', { inbox_kind: 'decision' })), 'report')
  assert.equal(first(item('a', { inbox_kind: 'question' })), 'context')
  assert.equal(first(item('a', { inbox_kind: 'idea' })), 'context')
  assert.equal(first(ASK_LENA), 'go', 'a reminder: its go drafts the message')
  assert.equal(first(task('a')), 'go')
  assert.deepEqual(logic.aiOf(item('a')).modes, ['go', 'report', 'context'])
  assert.deepEqual(logic.aiOf(task('a')).modes, ['go', 'report', 'context'])
  assert.deepEqual(logic.aiOf(ref('org/repo', 7)).modes, ['go', 'report'], 'an issue cannot collect context')
  assert.equal(logic.aiOf(item('a'), { person: true }), null, 'a person hands nothing to a model')
  assert.equal(logic.aiOf(item('a'), { live: true }).off, 'working')
  assert.equal(logic.aiOf(item('a', { inbox_state: 'approved' })).off, 'approved')
  assert.equal(logic.aiOf(item('a')).off, null)
})

test('B2 what each way sends: go only with a sentence, Advise and Collect context with one where there is one', () => {
  const q = item('a')
  assert.equal(logic.aiAction('go', q, '  '), null, 'nothing starts unseen')
  assert.deepEqual(logic.aiAction('go', q, 'Fix it'), { verb: 'do_it', args: { keys: ['inbox:a'], note: 'Fix it' } })
  assert.deepEqual(logic.aiAction('report', q, ''), { verb: 'advise', args: { keys: ['inbox:a'] } })
  assert.deepEqual(logic.aiAction('report', q, 'Mind the cost'), { verb: 'advise', args: { keys: ['inbox:a'], note: 'Mind the cost' } })
  assert.deepEqual(logic.aiAction('context', q, ''), { verb: 'collect_context', args: { key: 'inbox:a' } })
  assert.deepEqual(logic.aiAction('context', q, 'the contract'), { verb: 'collect_context', args: { key: 'inbox:a', note: 'the contract' } })
  assert.equal(logic.aiAction('context', ref('org/repo', 7), 'x'), null, 'no context for an issue')
  assert.equal(logic.aiAction('other', q, 'x'), null)
})

test('B3 the sentence a way opens with: go the start sentence, a reminder\'s go its draft, the others none', () => {
  const q = item('a', { title: 'Renew the domain' })
  assert.equal(logic.aiNote('go', q, 'en'), logic.startNote(q, 'en'))
  assert.equal(logic.aiNote('report', q, 'en'), '')
  assert.equal(logic.aiNote('context', q, 'en'), '')
  const draft = logic.aiNote('go', ASK_LENA, 'en')
  assert.equal(draft, logic.aiDraft(ASK_LENA, 'en'))
  assert.match(draft, /to Lena/)
  assert.match(draft, /1\. May we name you as the model\? 2\. Is the contract a frame or a draft\?/)
  assert.match(draft, /never send it/)
  assert.doesNotMatch(draft, /\?\./, 'a question keeps its own mark')
  assert.match(logic.aiDraft(ASK_LENA, 'de'), /an Lena/)
  assert.match(logic.aiDraft(ASK_LENA, 'de'), /nichts senden/)
  const bare = item('b', { title: 'The slides', card: card({ to: 'Lena' }) })
  assert.match(logic.aiDraft(bare, 'en'), /to Lena about "The slides"/, 'no asks: the name')
})

test('B4 Give it to the AI on a point: the ways with what they do, the first one picked, Start sends its verb', async () => {
  const q = item('20261009-0901-q', { title: 'Which contract applies' })
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${flowState({ now: [q], ui: pointAt(q.key) })} c=${c} />`)
  el.button(`${en.flow.ai.button} ▾`).click()
  await tick()
  const ways = el.$$('.flow-ai-modes button')
  assert.deepEqual(ways.map(b => b.$('.flow-ai-mode-name').text()), [en.flow.ai.mode.go, en.flow.ai.mode.report, en.flow.ai.mode.context])
  assert.deepEqual(ways.map(b => b.$('.flow-ai-mode-note').text()), [en.flow.ai.modeNote.go, en.flow.ai.modeNote.report, en.flow.ai.modeNote.context])
  assert.deepEqual(ways.map(b => b.getAttribute('aria-pressed')), ['false', 'false', 'true'], 'a question collects context first')
  el.button(en.flow.ai.start).click()
  await until(() => acts(c).length)
  assert.deepEqual(acts(c)[0], ['act', 'collect_context', { key: q.key }])
  // Advise: its verb; Let it do it: the start sentence written in, its verb with it
  const c2 = recorder()
  const el2 = mount(html`<${FlowPage} s=${flowState({ now: [q], ui: pointAt(q.key) })} c=${c2} />`)
  el2.button(`${en.flow.ai.button} ▾`).click()
  await tick()
  el2.$$('.flow-ai-modes button')[1].click()
  await tick()
  el2.button(en.flow.ai.start).click()
  await until(() => acts(c2).length)
  assert.deepEqual(acts(c2)[0], ['act', 'advise', { keys: [q.key] }])
  const c3 = recorder()
  const el3 = mount(html`<${FlowPage} s=${flowState({ now: [q], ui: pointAt(q.key) })} c=${c3} />`)
  el3.button(`${en.flow.ai.button} ▾`).click()
  await tick()
  el3.$$('.flow-ai-modes button')[0].click()
  await tick()
  assert.equal(valueOf(el3.$('.flow-ai textarea')), logic.startNote(q, 'en'))
  el3.button(en.flow.ai.start).click()
  await until(() => acts(c3).length)
  assert.deepEqual(acts(c3)[0], ['act', 'do_it', { keys: [q.key], note: logic.startNote(q, 'en') }])
})

test('B5 no Give it to the AI for a person (while an agent works, aiOf says why: B1)', () => {
  const q = item('20261009-0901-q')
  const guest = mount(html`<${FlowPage} s=${{ ...flowState({ now: [q], ui: pointAt(q.key) }), boot: { config: { person: 'Lena' } } }} c=${recorder()} />`)
  assert.equal(guest.$$('button').some(b => b.text() === `${en.flow.ai.button} ▾`), false)
})

// ---------------------------------------------------------------- C: a reminder

test('C1 a reminder: Draft the message to <who> is the strong button, a draft only; I asked waits for the answer', async () => {
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${flowState({ now: [ASK_LENA], ui: pointAt(ASK_LENA.key) })} c=${c} />`)
  const strong = el.$('.flow-aside .verbbar-strong')
  assert.equal(strong.text(), en.flow.ai.draftTo('Lena'))
  strong.click()
  await until(() => acts(c).length)
  assert.deepEqual(acts(c)[0], ['act', 'do_it', { keys: [ASK_LENA.key], note: logic.aiDraft(ASK_LENA, 'en') }])
  const c2 = recorder()
  const el2 = mount(html`<${FlowPage} s=${flowState({ now: [ASK_LENA], ui: pointAt(ASK_LENA.key) })} c=${c2} />`)
  el2.button(en.flow.ai.asked).click()
  await until(() => acts(c2).length)
  assert.deepEqual(acts(c2)[0], ['act', 'work_on', { key: ASK_LENA.key, who: 'Lena', until: '2026-10-12', text: en.flow.ai.askedNote }])
  // the AI's go is the draft too, by its own name
  el2.button(`${en.flow.ai.button} ▾`).click()
  await tick()
  assert.equal(el2.$$('.flow-ai-modes button')[0].$('.flow-ai-mode-name').text(), en.flow.ai.draftMode)
  assert.equal(valueOf(el2.$('.flow-ai textarea')), logic.aiDraft(ASK_LENA, 'en'))
})

test('C2 the strong button of a reminder stands before the AI\'s suggestion; any other point keeps its suggestion', () => {
  const sug = { verb: 'later', reason: 'x' }
  assert.deepEqual(logic.strongOf({ row: ASK_LENA }, { triage: { items: {} } }, sug), { verb: 'draft', sug: false, to: 'Lena' })
  assert.equal(logic.strongOf({ row: item('a') }, { triage: { items: {} } }, sug).verb, 'later')
})

// ---------------------------------------------------------------- D: Out of date

test('D1 an inbox item\'s Drop is Out of date with its own reasons, an idea\'s Discard; a task keeps Drop and the configured ones', async () => {
  assert.deepEqual(logic.OBSOLETE_REASONS, ['already_done', 'not_relevant', 'not_like_this'])
  const s = flowState({})
  assert.deepEqual(logic.dropReasonsOf(item('a'), s), logic.OBSOLETE_REASONS)
  assert.deepEqual(logic.dropReasonsOf(task('a'), s), ['resolves_itself', 'not_needed'])
  assert.deepEqual(logic.OBSOLETE_REASONS.map(r => logic.dropReasonWord(r, 'de')), ['Schon erledigt', 'Nicht mehr relevant', 'Brauche ich so nicht'])
  const q = item('20261009-0901-q')
  const el = mount(html`<${FlowPage} s=${flowState({ now: [q], ui: pointAt(q.key) })} c=${recorder()} />`)
  const grid = el.$$('.flow-aside .verbbar-grid button').map(b => b.text())
  assert.ok(grid.includes(`${en.flow.ai.obsolete} ▾`), grid.join(' | '))
  el.button(`${en.flow.ai.obsolete} ▾`).click()
  await tick()
  const panel = el.$('.flow-aside .verbbar-panel')
  assert.deepEqual(panel.$$('.verbbar-acts button').map(b => b.text()), logic.OBSOLETE_REASONS.map(r => logic.dropReasonWord(r, 'en')))
  assert.equal(panel.getAttribute('aria-label'), en.flow.ai.obsoleteLabel)
  const t = mount(html`<${FlowPage} s=${flowState({ work: [task('a')], ui: pointAt('task:a') })} c=${recorder()} />`)
  assert.ok(t.$$('.flow-aside .verbbar-grid button').some(b => b.text() === `${en.flow.simple.drop} ▾`), 'a task drops')
  assert.equal(logic.dropWord(item('a', { inbox_kind: 'idea', art: 'idea' }), 'de'), 'Verwerfen')
  assert.equal(logic.dropWord(item('a'), 'de'), 'Überholt')
  assert.equal(logic.dropWord(task('a'), 'de'), null)
})

test('D2 a card the AI found out of date opens Out of date with its why written in, sent as the reason', async () => {
  const old = item('20261009-0902-old', { card: card({ verdict: { word: 'obsolete', why: 'The meeting was on Monday' } }) })
  assert.equal(logic.dropSeed(old), 'The meeting was on Monday')
  assert.equal(logic.dropSeed(item('a')), '')
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${flowState({ now: [old], ui: { flowView: 'left', flowLeft: 'obsolete', flowLeftAt: { id: old.key, i: 0 } } })} c=${c} />`)
  const btn = el.$$('button').find(b => b.text() === `${en.flow.ai.obsolete} ▾`)
  assert.ok(btn, 'the card stands with Out of date')
  btn.click()
  await tick()
  const field = el.$$('.flow-aside .verbbar-panel input').find(i => i.getAttribute('aria-label') === en.flow.drop.other)
  assert.equal(valueOf(field), 'The meeting was on Monday')
  el.button(en.flow.ai.obsoleteSend).click()
  await until(() => acts(c).length)
  assert.deepEqual(acts(c)[0], ['act', 'settle', { keys: [old.key], outcome: 'not_doing', text: 'The meeting was on Monday' }])
})

// ---------------------------------------------------------------- E: the words

test('E1 the German words are the ones of the mockup', () => {
  const a = de.flow.ai
  assert.deepEqual([a.button, a.mode.go, a.mode.report, a.mode.context, a.asked, a.obsolete, a.discard, a.draftTo('Lena')],
    ['An die AI geben', 'Machen lassen', 'Beraten', 'Infos sammeln', 'Hab ich gefragt', 'Überholt', 'Verwerfen', 'Nachricht an Lena entwerfen'])
  for (const words of [en.flow.ai, de.flow.ai]) {
    const all = JSON.stringify(words) + words.draft('X', ['a'], 'n') + words.draftTo('X')
    assert.doesNotMatch(all, /[–—]|--/, 'no dashes')
  }
})
