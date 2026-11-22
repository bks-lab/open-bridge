// SPDX-License-Identifier: MIT
// What the operator's own cockpit still showed right after the four buckets and four answers (#704): Jev's matrix in
// its own words, and agent tabs offering "Keep going" and "Answer…" and a Do chip where they asked nothing. A tab's own
// answers replace Do it only where it asks (a dialog, a ready answer, yes or no, a question in words); a tab that asks
// nothing offers the way to it and its close, and on its point the answers that make sense there. No npm dependencies.
//
//   node --test scripts/tests/bridge_cockpit_704_followup.test.mjs
import test from 'node:test'
import assert from 'node:assert/strict'
import { loadCockpit, mount, recorder, settle as rounds } from './cockpit_render.mjs'

const { html, views, text, logic, jev } = await loadCockpit()
const en = text.TABLES.en
const de = text.TABLES.de

// Friday, 9 October 2026, noon
const NOW = new Date(2026, 9, 9, 12, 0, 0).getTime()
const MIN = 60000

const SERVED = [{ id: 'do', title: 'Tun' }, { id: 'plan', title: 'Planen' }, { id: 'delegate', title: 'Mache ich' },
  { id: 'waiting', title: 'Wartet auf andere' }]

const ask = (id, over = {}) => ({ key: `inbox:${id}`, inbox_id: id, title: `Question ${id}`, art: 'ask', inbox_state: 'open',
  bucket: 'do', gate: 'your-yes', settle: ['done', 'not_doing'], ...over })

function state({ now = [], work = [], tabs = [], on = true, ui = {}, ...rest } = {}) {
  return {
    now: NOW, layout: 'wide', model: { sections: [['now', now], ['give', []], ['work', work], ['track', []], ['later', []]]
      .map(([id, rows]) => ({ id, rows, total: rows.length, compact: rows.map(r => r.key) })), hidden: [], returns: [], buckets: SERVED,
    aside: { later: 0, list: 0, done_today: 0 } },
    tabs: { tabs, at_ms: NOW }, driver: { caps: ['tabs', 'launch', 'focus', 'screen', 'key', 'send', 'close'] }, triage: { items: {} }, jevOrder: {},
    work: { flow: { enabled: true, drop_reasons: [], return_after_s: 20, buckets: { enabled: on } } },
    themes: { enabled: false }, more: {}, details: { inbox: {}, task: {} }, sessions: { sessions: [] }, quick: { convs: [] }, flow_ai: {},
    ui: { page: 'briefing', busy: {}, picked: [], expanded: { now: true, give: true, work: true, track: true, later: true }, dayHeight: 2000, ...ui },
    ...rest,
  }
}

const buttonsOf = el => el.$$('button').map(b => b.text().trim()).filter(Boolean)

// a finished tab: it waits at its prompt and went quiet, its last words are no question (the operator's "Erzeuge ein Bild")
const finished = { ref: 'surface:21', name: 'Make a picture', state: 'waiting', idle: true, live: true, since_ms: NOW - 40 * MIN,
  workspace: 'Home', last: 'The picture is in ~/Pictures/out.png.', ask: { text: 'The picture is in ~/Pictures/out.png.', hash: 'f1' } }
// one that waits at its prompt, not quiet yet, and asks nothing
const told = { ...finished, ref: 'surface:22', name: 'Import', idle: false, since_ms: NOW - 2 * MIN,
  ask: { text: 'Summary: the import ran.', hash: 'f2' } }
const yesNo = { ...told, ref: 'surface:23', name: 'Commit', ask: { text: 'Commit now?', hash: 'y1', yes_no: true, asks: true } }
const question = { ...told, ref: 'surface:24', name: 'Estimate', ask: { text: 'How many records, roughly?', hash: 'q1', asks: true } }
const ready = { ...told, ref: 'surface:25', name: 'Contact import', ask: { text: 'Shall I try again?', hash: 'r1', draft: true, suggestion: 'yes, try again' } }
const dialog = { ref: 'surface:26', name: 'Deploy', state: 'needs-you', since_ms: NOW - 2 * MIN, workspace: 'Home', live: true,
  ask: { text: 'Do you want to proceed?', hash: 'd1', options: [{ n: 1, label: 'Yes' }, { n: 2, label: 'No' }] } }

const GO_ON = [en.btnGoOn, de.btnGoOn, en.reply.goOn, de.reply.goOn].map(w => w.replace(/["„“]/g, ''))
const noGoOn = (words, what) => {
  for (const w of words) assert.ok(!GO_ON.some(g => w.replace(/["„“]/g, '') === g), `${what}: ${w}`)
}

// ---------------------------------------------------------------- which tab asks

test('tabAsksYou: a dialog, a ready answer, yes or no and a question in words ask; a finished or told tab asks nothing', () => {
  assert.equal(logic.tabAsksYou(dialog), true)
  assert.equal(logic.tabAsksYou(ready), true)
  assert.equal(logic.tabAsksYou(yesNo), true)
  assert.equal(logic.tabAsksYou(question), true)
  assert.equal(logic.tabAsksYou(told), false)
  assert.equal(logic.tabAsksYou(finished), false)
  assert.equal(logic.tabAsksYou({ ...told, state: 'working' }), false)
  assert.equal(logic.tabAsksYou({ ...dialog, is_control: true }), false)
})

// ---------------------------------------------------------------- the answers of a tab with the buckets on

test('with the buckets on no tab is offered Keep going, whatever it says', () => {
  const s = state({ tabs: [finished, told, yesNo, question, ready, dialog] })
  for (const tab of [finished, told, yesNo, question, ready, dialog]) {
    const verbs = logic.replyOptions(tab, s, en).buttons.map(b => b.verb)
    assert.ok(!verbs.includes('tab_go_on'), `${tab.name}: ${verbs}`)
    const p = { group: 'asks', id: `tab:${tab.ref}`, kind: 'tab', tab, row: null }
    assert.ok(!logic.bucketAnswers(p, 'do', s, 'de').some(a => a.run?.verb === 'tab_go_on' || a.label === de.reply.goOn), tab.name)
  }
  // the switch off: Work through as it was, go on where the tab asks nothing
  const off = state({ on: false, tabs: [told] })
  assert.ok(logic.replyOptions(told, off, en).buttons.some(b => b.verb === 'tab_go_on'))
})

test('a tab that asks keeps its own answers first; a yes or no keeps an answer in words after them', () => {
  const s = state({ tabs: [yesNo, question, ready, dialog] })
  const first = tab => logic.bucketAnswers({ group: 'asks', id: `tab:${tab.ref}`, kind: 'tab', tab, row: null }, 'do', s, 'de')
  assert.deepEqual(first(yesNo).map(a => a.label), [de.reply.yes, de.reply.no, de.flow.buckets.sayAnswer])
  assert.equal(first(question)[0].run.kind, 'say')
  assert.equal(first(ready)[0].run.verb, 'tab_accept')
  assert.equal(first(dialog)[0].run.verb, 'tab_option')
})

test('a tab that asks nothing offers no answer in words: the way to it first, and on its item Later, Done and Obsolete', () => {
  const item = ask('20261009-0900-pic1', { title: 'Make a picture' })
  const tab = { ...told, item: item.inbox_id }
  const s = state({ now: [item], tabs: [tab] })
  const p = logic.tabPoint(tab, s)
  const got = logic.bucketAnswers(p, 'do', s, 'de')
  assert.equal(got[0].run.verb, 'tab_jump')
  assert.equal(got[0].label, de.btnToTab)
  assert.ok(!got.some(a => a.label === de.flow.buckets.sayAnswer))
  assert.deepEqual(got.slice(1).map(a => a.meaning), ['later', 'done', 'obsolete'])
  // Next says the tab asks nothing, never that its input line holds text
  assert.equal(logic.nextSentence(p, 'do', s, 'de'), de.flow.buckets.nextTabQuiet)
})

test('a finished tab is no point of Do: no chip, no answers of its own, only the way to it and its close', async () => {
  const s = state({ tabs: [finished] })
  assert.equal(logic.tabPoint(finished, s), null)
  for (const slim of [true, false]) {
    const el = mount(html`<${views.tabs.TabCard} tab=${finished} s=${s} c=${recorder()} byKey=${new Map()} slim=${slim} />`)
    await rounds()
    assert.equal(el.$('.fb-chip'), null, `slim ${slim}`)
    const words = buttonsOf(el)
    noGoOn(words, `slim ${slim}`)
    assert.ok(!words.includes(en.flow.buckets.sayAnswer) && !words.includes(de.flow.buckets.sayAnswer), words.join())
    assert.ok(words.includes(en.btnToTab), words.join())
    assert.ok(words.some(w => w === en.btnCloseTab || w === en.btnCloseTabOnly), words.join())
  }
})

test('the tabs column with the buckets on: a tab that asks nothing shows no Keep going and no Answer…, also while it is not quiet yet', async () => {
  const item = ask('20261009-0900-imp1', { title: 'Import' })
  const tab = { ...told, item: item.inbox_id }
  const s = state({ now: [item], tabs: [tab] })
  const el = mount(html`<${views.tabs.TabCard} tab=${tab} s=${s} c=${recorder()} byKey=${new Map()} slim />`)
  await rounds()
  const words = buttonsOf(el)
  noGoOn(words, 'told')
  assert.ok(!words.includes(en.flow.buckets.sayAnswer), words.join())
  // Go to tab once, as the first answer, not a second time beside it
  assert.equal(words.filter(w => w === en.reply.openTab || w === en.btnToTab).length, 1, words.join())
})

// ---------------------------------------------------------------- Jev in the bucket words

test('Jev\'s squares say the bucket words of the profile; the low corner says Later; the legend says you and Bridge', () => {
  const w = logic.bucketWords(state(), 'de')
  assert.deepEqual(w.quadrant, { now: 'Tun', plan: 'Planen', hand: 'Mache ich', drop: 'Später' })
  assert.deepEqual(w.who, { me: 'du', delegate: 'Bridge' })
  const t = { quads: { now: 'Jetzt selbst', plan: 'Einplanen', hand: 'Abgeben', drop: 'Loslassen' }, me: 'du', delegate: 'abgeben' }
  const m = jev.matrixWords(w, t)
  assert.deepEqual(m, { quads: { now: 'Tun', plan: 'Planen', hand: 'Mache ich', drop: 'Später' }, me: 'du', delegate: 'Bridge' })
  // English titles of an English profile, the English word for Later
  const enW = logic.bucketWords({ ...state(), model: { ...state().model, buckets: [] } }, 'en')
  assert.deepEqual(enW.quadrant, { now: 'Do', plan: 'Plan', hand: 'I\'ll do', drop: 'Later' })
  assert.deepEqual(enW.who, { me: 'you', delegate: 'Bridge' })
  // the switch off: Jev's own words
  assert.deepEqual(logic.bucketWords(state({ on: false }), 'de'), { columns: {}, quadrant: {}, who: {} })
})

test('the Jev page source names the matrix by the bucket words while the buckets are on', async () => {
  const fs = await import('node:fs')
  const src = fs.readFileSync(new URL('../web/jev/page.js', import.meta.url), 'utf8')
  assert.doesNotMatch(src, /matrixWords\(null,/)
})
