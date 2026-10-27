// SPDX-License-Identifier: MIT
// A toast that names its place leads there (the `go` of a note), and toasts past four are not lost.
//
//   node --test scripts/tests/bridge_cockpit_toast_go.test.mjs
//
// The pure part (logic.js noteGo, pushNoteState, alertToasts) is tested on its own; the toasts and the notes in
// the history are mounted with the render harness (cockpit_render.mjs) and clicked as a person clicks them, so
// the assertions are on where a click leads: the controller calls it makes, in order.
import test from 'node:test'
import assert from 'node:assert/strict'
import { cockpitState, loadCockpit, mount, recorder } from './cockpit_render.mjs'

const { html, views, text, logic } = await loadCockpit()
const { Toasts, HistoryDrawer } = views.overlays
const en = text.TABLES.en
const de = text.TABLES.de

const NOW = new Date(2026, 9, 9, 12, 0, 0).getTime()
const MIN = 60000

const toast = (id, over = {}) => ({ id, text: `Note ${id}`, tone: 'ok', at: '12:00', action: null, conv: null, undo: null,
  copy: null, go: null, ...over })

function renderToasts(toasts, over = {}) {
  const s = cockpitState(NOW, { toasts, ...over })
  const c = recorder()
  return { el: mount(html`<${Toasts} s=${s} c=${c} />`), c, s }
}

// ---------------------------------------------------------------- the union (logic.js noteGo)

test('noteGo: a known target passes with the fields of its kind only', () => {
  assert.deepEqual(logic.noteGo({ kind: 'tab', ref: 'surface:7' }), { kind: 'tab', ref: 'surface:7' })
  assert.deepEqual(logic.noteGo({ kind: 'row', key: 'ref:example/repo#12', path: '/etc' }), { kind: 'row', key: 'ref:example/repo#12' })
  assert.deepEqual(logic.noteGo({ kind: 'item', key: 'task:demo-task' }), { kind: 'item', key: 'task:demo-task' })
  assert.deepEqual(logic.noteGo({ kind: 'page', id: '@sessions' }), { kind: 'page', id: '@sessions' })
  assert.deepEqual(logic.noteGo({ kind: 'conv', id: 'g0123456789' }), { kind: 'conv', id: 'g0123456789' })
  assert.deepEqual(logic.noteGo({ kind: 'ask', id: 'q0123456789' }), { kind: 'ask', id: 'q0123456789' })
  assert.deepEqual(logic.noteGo({ kind: 'claude', id: 'x' }), { kind: 'claude' })
})

test('noteGo: an unknown or broken target becomes null', () => {
  for (const go of [undefined, null, 'surface:7', [], {}, { kind: 'file', path: 'x' }, { kind: 'tab' }, { kind: 'tab', ref: 7 },
    { kind: 'tab', ref: 'x'.repeat(300) }, { kind: 'item', key: 'ref:example/repo#12' }, { kind: 'row', key: 'nokind' },
    { kind: 'conv', id: '' }, { kind: 'drawer', id: 'notes' }, { kind: 'info', it: {} }, { kind: ['tab'], ref: 'surface:7' }]) {
    assert.equal(logic.noteGo(go), null, JSON.stringify(go))
  }
})

test('pushNoteState: the toast and the note keep a valid target and drop a broken one', () => {
  const s = logic.pushNoteState({ notes: [], toasts: [] }, { text: 'a', tone: 'ok', at: '12:00', go: { kind: 'tab', ref: 'surface:7' } }, 0, 1)
  assert.deepEqual(s.toasts[0].go, { kind: 'tab', ref: 'surface:7' })
  assert.deepEqual(s.notes[0].go, { kind: 'tab', ref: 'surface:7' })
  const bad = logic.pushNoteState({ notes: [], toasts: [] }, { text: 'a', tone: 'ok', at: '12:00', go: { kind: 'file', path: '/' } }, 0, 1)
  assert.equal(bad.toasts[0].go, null)
  assert.equal(bad.notes[0].go, null)
})

test('pushNoteState: a fifth toast does not vanish silently, it is counted as more', () => {
  let s = { notes: [], toasts: [], toastsMore: 0 }
  for (let i = 0; i < 4; i++) s = { ...s, ...logic.pushNoteState(s, { text: `n${i}`, tone: 'info', at: '12:00' }, i, i + 1) }
  assert.equal(s.toastsMore, 0)
  s = { ...s, ...logic.pushNoteState(s, { text: 'n4', tone: 'info', at: '12:00' }, 4, 5) }
  assert.deepEqual(s.toasts.map(t => t.id), [2, 3, 4, 5])
  assert.equal(s.toastsMore, 1)
  s = { ...s, ...logic.pushNoteState(s, { text: 'n5', tone: 'info', at: '12:00' }, 5, 6) }
  assert.equal(s.toastsMore, 2)
  assert.equal(s.notes.length, 6, 'the drawer still has every one')
})

// ---------------------------------------------------------------- a toast with a target

test('toast: without a target the text is plain, as before', () => {
  const { el } = renderToasts([toast(1)])
  assert.equal(el.$('.toast-go'), null)
  assert.equal(el.$('.toast-text').tagName.toLowerCase(), 'span')
})

test('toast: an unknown target is dropped, the text stays plain', () => {
  const { el } = renderToasts([toast(1, { go: { kind: 'file', path: '/etc/passwd' } })])
  assert.equal(el.$('.toast-go'), null)
})

test('toast: a click on the text of a tab toast dismisses it, then goes to the tab', () => {
  const { el, c } = renderToasts([toast(3, { go: { kind: 'tab', ref: 'surface:7' } })], { driver: { caps: ['tabs'] } })
  const go = el.$('button.toast-go')
  assert.ok(go, 'the message is a button')
  assert.equal(go.text().includes('Note 3'), true)
  go.click()
  assert.deepEqual(c.calls, [['dismissToast', 3], ['openTabView', 'surface:7']])
})

test('toast: a tab toast brings the tab to the front where the driver can', () => {
  const { el, c } = renderToasts([toast(3, { go: { kind: 'tab', ref: 'surface:7' } })], { driver: { caps: ['tabs', 'focus'] } })
  el.$('button.toast-go').click()
  assert.deepEqual(c.calls, [['dismissToast', 3], ['act', 'tab_jump', { tab_ref: 'surface:7' }]])
})

test('toast: a row, an item, a page and a conversation each lead to their own place', () => {
  const cases = [
    [{ kind: 'item', key: 'task:alpha-release' }, ['openItem', 'task:alpha-release', null]],
    [{ kind: 'page', id: '@sessions' }, ['setPage', '@sessions']],
    [{ kind: 'conv', id: 'g0123456789' }, ['openAgentConv', 'g0123456789']],
    [{ kind: 'ask', id: 'q0123456789' }, ['openAsk', 'q0123456789']],
    [{ kind: 'claude' }, ['openClaude']],
  ]
  for (const [go, want] of cases) {
    const { el, c } = renderToasts([toast(1, { go })])
    el.$('button.toast-go').click()
    assert.deepEqual(c.calls, [['dismissToast', 1], want], JSON.stringify(go))
  }
  // a row of the model opens whole as the start page opens it; a row that is gone leads to the work list
  const row = renderToasts([toast(1, { go: { kind: 'row', key: 'task:alpha-release' } })])
  row.el.$('button.toast-go').click()
  assert.equal(row.c.calls[1][0], 'openItem')
  assert.equal(row.c.calls[1][1], 'task:alpha-release')
  const gone = renderToasts([toast(1, { go: { kind: 'row', key: 'ref:no/such#1' } })])
  gone.el.$('button.toast-go').click()
  assert.deepEqual(gone.c.calls, [['dismissToast', 1], ['setPage', 'briefing']])
})

test('toast: the close X and Undo never navigate', () => {
  const undo = [{ undo: { verb: 'task_reopen', args: { slug: 'demo-task' } } }]
  const { el, c } = renderToasts([toast(5, { go: { kind: 'item', key: 'task:demo-task' }, action: 'undo', undo })])
  el.button(en.close).click()
  assert.deepEqual(c.calls, [['dismissToast', 5]])
  c.calls.length = 0
  el.button(en.undoToast).click()
  assert.deepEqual(c.calls, [['dismissToast', 5], ['undo', undo[0].undo]])
})

// ---------------------------------------------------------------- more than four

test('overflow: at five a compact last toast says how many more and opens the notes (in the history)', () => {
  const four = [1, 2, 3, 4].map(i => toast(i))
  assert.equal(renderToasts(four, { toastsMore: 0 }).el.$('.toast-more'), null)
  const { el, c } = renderToasts([2, 3, 4, 5].map(i => toast(i)), { toastsMore: 1 })
  const more = el.$('button.toast-more')
  assert.ok(more, 'the overflow toast is a button')
  assert.equal(more.text(), en.toastsMore(1))
  assert.equal(el.$('.toasts').childNodes.at(-1), more, 'it stands last')
  more.click()
  assert.deepEqual(c.calls, [['openNotes']])
})

test('overflow: the words are English and German', () => {
  assert.equal(en.toastsMore(3), '+3 more')
  assert.equal(de.toastsMore(3), '+3 weitere')
})

// ---------------------------------------------------------------- the notes in the history (K2)

/** The history drawer mounted with these notes and no closed items; the focus effect finds what the small DOM has */
function renderNotes(notes) {
  const proto = Object.getPrototypeOf(document.body)
  proto.focus ??= function focus() { document.activeElement = this }
  proto.querySelector ??= function querySelector(sel) { try { return this.$(sel) } catch { return null } }
  const s = cockpitState(NOW, { ui: { drawer: 'history' }, history: [], notes })
  const c = recorder()
  return { el: mount(html`<${HistoryDrawer} s=${s} c=${c} />`), c }
}

const dayWord = ms => logic.formatDay(logic.isoDate(ms), 'en')

test('history: the notes stand under Today, newest first; one with a target closes the drawer and goes there', async () => {
  const { el, c } = renderNotes([
    { at: '11:58', text: 'Plain note', tone: 'info', ms: NOW - 2 * MIN },
    { at: '11:59', text: 'Sent to demo-task', tone: 'ok', ms: NOW - MIN, go: { kind: 'item', key: 'task:demo-task' } },
    { at: '11:59', text: 'Broken target', tone: 'ok', ms: NOW - MIN, go: { kind: 'evil' } },
  ])
  const days = el.$$('.hist-day')
  assert.equal(days.length, 1)
  assert.equal(days[0].$('h3').text(), en.historyToday(dayWord(NOW)))
  assert.match(days[0].$('.hist-notes summary').text(), new RegExp(en.histNotes(3).replace(/[()]/g, '\\$&')))
  assert.deepEqual(days[0].$$('.note').map(n => n.text().replace(/^\d\d:\d\d\s*/, '')), ['Broken target', 'Sent to demo-task', 'Plain note'])
  const gos = el.$$('button.note-go')
  assert.equal(gos.length, 1)
  assert.match(gos[0].text(), /Sent to demo-task/)
  gos[0].click()
  assert.deepEqual(c.calls, [['setDrawer', null], ['openItem', 'task:demo-task', null]])
  await new Promise(resolve => setTimeout(resolve, 20))   // the focus effect runs inside the test
})

test('history: a note keeps its day, one from yesterday stands under yesterday, one without a date under today', async () => {
  const { el } = renderNotes([
    { at: '23:50', text: 'Late yesterday', tone: 'info', ms: NOW - 13 * 60 * MIN },
    { at: '11:00', text: 'Undated', tone: 'info', ms: 0 },
  ])
  const days = el.$$('.hist-day')
  assert.deepEqual(days.map(d => d.$('h3').text()), [en.historyToday(dayWord(NOW)), dayWord(NOW - 13 * 60 * MIN)])
  assert.match(days[0].text(), /Undated/)
  assert.match(days[1].text(), /Late yesterday/)
  assert.doesNotMatch(days[0].text(), /Late yesterday/)
  await new Promise(resolve => setTimeout(resolve, 20))
})

test('history: neither a closed item nor a note says the history is empty', async () => {
  const { el } = renderNotes([])
  assert.match(el.text(), new RegExp(en.historyEmpty))
  assert.equal(el.$('.hist-day'), null)
  await new Promise(resolve => setTimeout(resolve, 20))
})

test('the words of the notes in the history are English and German', () => {
  assert.equal(en.histNotes(2), 'Notes (2)')
  assert.equal(de.histNotes(2), 'Meldungen (2)')
  assert.equal(de.historyToday('Fr., 9. Okt.'), 'Heute, Fr., 9. Okt.')
})

// ---------------------------------------------------------------- which tab alert toasts (K2)

test('alertToasts: a tab that starts waiting toasts only while it is out of sight, one past the hour always', () => {
  const waits = { kind: 'tab_waiting', ref: 'surface:7' }
  const long = { kind: 'tab_long', ref: 'surface:7' }
  const start = { ui: { page: '@start', tabView: null, room: null } }
  assert.equal(logic.alertToasts(start, waits), true)
  // its tab view is open, or the Chat shows it in its work area: the note goes to the history only
  const viewed = { ui: { ...start.ui, tabView: 'surface:7' } }
  assert.equal(logic.alertToasts(viewed, waits), false)
  const room = { ui: { page: '@chat', chatArea: 'work', tabView: null, room: { kind: 'tab', id: 'surface:7' } } }
  assert.equal(logic.alertToasts(room, waits), false)
  // another tab in view, the Chat on its A2A area, a tab view over the room: it is not in sight
  assert.equal(logic.alertToasts({ ui: { ...start.ui, tabView: 'surface:8' } }, waits), true)
  assert.equal(logic.alertToasts({ ui: { ...room.ui, chatArea: 'a2a' } }, waits), true)
  assert.equal(logic.alertToasts({ ui: { ...room.ui, tabView: 'surface:9' } }, waits), true)
  assert.equal(logic.alertToasts({ ui: { ...room.ui, page: '@start' } }, waits), true)
  // past the hour it toasts in sight too
  assert.equal(logic.alertToasts(viewed, long), true)
  assert.equal(logic.alertToasts(room, long), true)
})

// ---------------------------------------------------------------- the store's toast steps (review fixes)

test('noteGo and its kind: only a string kind counts, never one that only coerces to a name', () => {
  assert.equal(logic.noteGo({ kind: ['claude'] }), null)
  assert.equal(logic.noteGo({ kind: ['tab'], ref: 'surface:7' }), null)
})

test('noteGo: a row or item key with a ".." segment is dropped, as the server drops it', () => {
  assert.equal(logic.noteGo({ kind: 'row', key: 'task:../../etc' }), null)
  assert.equal(logic.noteGo({ kind: 'item', key: 'task:a/../b' }), null)
  assert.equal(logic.noteGo({ kind: 'row', key: 'item:..' }), null)
  assert.deepEqual(logic.noteGo({ kind: 'row', key: 'item:systems/checks/x' }), { kind: 'row', key: 'item:systems/checks/x' })
  assert.deepEqual(logic.noteGo({ kind: 'row', key: 'title:Fix the..thing' }), { kind: 'row', key: 'title:Fix the..thing' })
})

test('pushNoteState: a toast pushed out is named in `out`, so its timer stops', () => {
  let s = { notes: [], toasts: [], toastsMore: 0 }
  for (let i = 0; i < 4; i++) s = { ...s, ...logic.pushNoteState(s, { text: `n${i}`, tone: 'info', at: '12:00' }, i, i + 1) }
  assert.deepEqual(s.out, [])
  const next = logic.pushNoteState(s, { text: 'n4', tone: 'info', at: '12:00' }, 4, 5)
  assert.deepEqual(next.out, [1])
})

test('pushNoteState: an Undo toast is kept over a plain one when one must go', () => {
  const undo = [{ undo: { verb: 'task_reopen' } }]
  let s = { notes: [], toasts: [], toastsMore: 0 }
  s = { ...s, ...logic.pushNoteState(s, { text: 'closed', tone: 'ok', at: '12:00', action: 'undo', undo }, 0, 1) }
  for (let i = 1; i < 5; i++) s = { ...s, ...logic.pushNoteState(s, { text: `n${i}`, tone: 'info', at: '12:00' }, i, i + 1) }
  assert.deepEqual(s.toasts.map(t => t.id), [1, 3, 4, 5], 'the oldest plain one went, the undo stays')
  assert.deepEqual(s.out, [2])
  assert.equal(s.toastsMore, 1)
  // every one with an action: then the oldest goes after all
  let a = { notes: [], toasts: [], toastsMore: 0 }
  for (let i = 0; i < 5; i++) a = { ...a, ...logic.pushNoteState(a, { text: `u${i}`, tone: 'ok', at: '12:00', action: 'undo', undo }, i, i + 1) }
  assert.deepEqual(a.toasts.map(t => t.id), [2, 3, 4, 5])
  assert.deepEqual(a.out, [1])
})

test('giveTwin: the twin of a toast still up hands over its action and its place, never takes one away', () => {
  const up = [toast(1, { text: 'Closed', go: null }), toast(2, { text: 'Other' })]
  const undo = [{ undo: { verb: 'task_reopen' } }]
  const got = logic.giveTwin(up, { text: 'Closed', action: 'undo', undo, go: { kind: 'item', key: 'task:demo-task' } })
  assert.equal(got.id, 1)
  assert.equal(got.toasts[0].action, 'undo')
  assert.deepEqual(got.toasts[0].undo, undo)
  assert.deepEqual(got.toasts[0].go, { kind: 'item', key: 'task:demo-task' })
  assert.equal(got.toasts[1], up[1])
  // only a place: the action of the toast stays
  const withUndo = [toast(1, { text: 'Closed', action: 'undo', undo })]
  const placed = logic.giveTwin(withUndo, { text: 'Closed', go: { kind: 'tab', ref: 'surface:7' } })
  assert.equal(placed.toasts[0].action, 'undo')
  assert.deepEqual(placed.toasts[0].go, { kind: 'tab', ref: 'surface:7' })
  // nothing to give, or a broken place: no twin
  assert.equal(logic.giveTwin(withUndo, { text: 'Closed' }), null)
  assert.equal(logic.giveTwin(up, { text: 'Closed', go: { kind: 'evil' } }), null)
  assert.equal(logic.giveTwin(up, { text: 'Nobody', action: 'undo', undo }), null)
})

test('dismissState: the "+N more" count stays while others are up and goes with the last', () => {
  const s = { toasts: [toast(1), toast(2)], toastsMore: 3 }
  assert.deepEqual(logic.dismissState(s, 1), { toasts: [s.toasts[1]], toastsMore: 3 })
  assert.deepEqual(logic.dismissState({ toasts: [toast(2)], toastsMore: 3 }, 2), { toasts: [], toastsMore: 0 })
  assert.deepEqual(logic.notesOpenedState({ toasts: [toast(2)], toastsMore: 3 }), { toastsMore: 0 })
})

// ---------------------------------------------------------------- an agent toast in the Chat as cmux (#509)

test('as cmux an agent toast and an @agents page target land on the Chat in its A2A area', () => {
  const nav = views.nav
  const base = cockpitState(NOW, { rooms: { layout: 'workspaces' } })
  const convs = [{ id: 'g0123456789', peer: 'team-bridge', started_ms: NOW - 60000, last_ms: NOW - 60000, context_id: null,
    running: false, turns: [{ q: 'Hello?', mode: 'question', a: null, waiting: false, at_ms: NOW, error: null }] }]
  /** The controller's way to an agent as app.js wires it: chatAreaActions, and setPage asking pageFor */
  const controller = s0 => {
    let s = s0
    const setUi = p => { s = { ...s, ui: { ...s.ui, ...(typeof p === 'function' ? p(s.ui) : p) } } }
    const acts = nav.chatAreaActions({ get: () => s, setUi, save: () => {}, now: () => NOW })
    return { get: () => s, c: { ...acts, dismissToast: () => {}, setPage: id => setUi({ page: acts.pageFor(id) }) } }
  }
  for (const go of [{ kind: 'conv', id: 'g0123456789' }, { kind: 'page', id: nav.AGENTS_PAGE }]) {
    const h = controller({ ...base, agents: { ...base.agents, convs }, toasts: [toast(1, { go })], ui: { ...base.ui, page: 'briefing' } })
    const el = mount(html`<${Toasts} s=${h.get()} c=${h.c} />`)
    el.$('button.toast-go').click()
    assert.equal(h.get().ui.page, nav.CHAT_PAGE, JSON.stringify(go))
    assert.equal(nav.chatAreaOf(h.get()), 'a2a', JSON.stringify(go))
  }
})
