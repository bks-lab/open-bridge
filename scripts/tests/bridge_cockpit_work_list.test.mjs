// SPDX-License-Identifier: MIT
// Render tests of Work through as a list: the left column lists every open point under its theme (or area, or
// square), in the order its overview walks them; a click opens the point in the middle and the list stays, the point
// open marked; with no point open the middle shows the overview as before, the start view of the page.
//
//   node --test scripts/tests/bridge_cockpit_work_list.test.mjs
import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { cockpitState, loadCockpit, mount, recorder, waitFor } from './cockpit_render.mjs'

const { html, views, logic } = await loadCockpit()
const { FlowPage } = views.flow
const { walkOrder } = views.flowlist
const { pointTitle } = views.flowpoint
const NOW = new Date(2026, 9, 9, 12, 0, 0).getTime()
const WEB = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'web')
const APP = fs.readFileSync(path.join(WEB, 'app.js'), 'utf8')

const task = (slug, over = {}) => ({ key: `task:${slug}`, task: slug, title: `Task ${slug}`, status: 'doing', bucket: 'tasks',
  priority: 'P2', settle: ['done', 'not_doing'], ...over })
const ask = (id, over = {}) => ({ key: `inbox:${id}`, inbox_id: id, title: `Question ${id}`, art: 'ask', inbox_state: 'open',
  bucket: 'do', gate: 'only-you', settle: ['done', 'not_doing'], ...over })

/** Two areas: Ops holds a question and a task, Docs a task (the themes off, so the left column groups by area) */
function state(ui = {}) {
  const now = [ask('20261009-0900-a-q', { area: 'Ops' })]
  const work = [task('a', { area: 'Ops' }), task('b', { area: 'Docs' })]
  return cockpitState(NOW, {
    now: NOW, model: { sections: [{ id: 'now', rows: now }, { id: 'give', rows: [] }, { id: 'work', rows: work },
      { id: 'track', rows: [] }, { id: 'later', rows: [] }], hidden: [], returns: [], briefing_badge: 1 },
    tabs: { tabs: [] }, driver: { caps: null }, triage: { items: {} }, jevOrder: {},
    work: { flow: { enabled: true, drop_reasons: ['resolves_itself', 'not_needed'], return_after_s: 20 } },
    themes: { enabled: false },
    ui: { page: 'briefing', workView: 'flow', busy: {}, flowAt: null, flowChip: 'all', flowJump: null, flowView: 'overview', flowPicked: [], ...ui },
  })
}
/** The sides of the left column with their points in the order the overview walks them */
function sidesOf(s) {
  const all = logic.flowQueue(logic.flowParts(s), 'all')
  const mode = logic.flowMode(s)
  return logic.flowSides(s, all, mode).filter(x => x.id !== 'all')
    .map(x => ({ id: x.id, points: walkOrder(logic.pointsIn(all, x.id, s, mode), null) }))
}

test('the left column lists every point under its area, in the overview\'s order; the middle keeps the overview', () => {
  const s = state()
  const el = mount(html`<${FlowPage} s=${s} c=${recorder()} />`)
  const side = el.$('.flow-side')
  const want = sidesOf(s)
  assert.deepEqual(want.map(x => x.points.length).sort(), [1, 2], 'Ops two points, Docs one')
  const lists = side.$$('.flow-side-pts')
  assert.equal(lists.length, want.length, 'one list per area')
  lists.forEach((ul, i) => assert.deepEqual(ul.$$('.flow-side-pt-name').map(n => n.text()), want[i].points.map(p => pointTitle(p))))
  assert.equal(side.$$('.flow-side-pt').length, 3, 'every open point once')
  assert.equal(side.$('.flow-side-pt.is-current'), null, 'nothing open, nothing marked')
  assert.ok(el.$('.flow-overview'), 'the overview stands in the middle, the start view')
  assert.ok(!side.$('input[type=checkbox]'), 'no boxes on the left: the overview has them')
})

test('a point of the list opens in the middle, its area entered, at its place in that area\'s walk', () => {
  const s = state()
  const c = recorder()
  const el = mount(html`<${FlowPage} s=${s} c=${c} />`)
  const want = sidesOf(s)
  const ops = want.findIndex(x => x.points.length === 2)
  const btn = el.$$('.flow-side-pts')[ops].$$('.flow-side-pt')[1]
  btn.click()
  assert.deepEqual(c.calls.at(-1), ['flowSidePoint', want[ops].id, want[ops].points[1].id, 1])
})

test('with a point open the list stays, every area\'s points in it, the one open marked', () => {
  const base = state()
  const want = sidesOf(base)
  const ops = want.find(x => x.points.length === 2)
  const open = ops.points[1]
  const s = state({ flowView: 'point', flowSide: { areas: ops.id }, flowAt: { id: open.id, i: 1 } })
  const el = mount(html`<${FlowPage} s=${s} c=${recorder()} />`)
  const side = el.$('.flow-side')
  assert.equal(side.$$('.flow-side-pt').length, 3, 'the other area keeps its points in the list')
  const marked = side.$$('.flow-side-pt.is-current')
  assert.equal(marked.length, 1)
  assert.equal(marked[0].$('.flow-side-pt-name').text(), pointTitle(open))
  assert.equal(marked[0].getAttribute('aria-current'), 'true')
  assert.ok(el.$('.flow-main.is-point'), 'the point in the middle')
})

test('walking on in the middle brings the point open into view in the list', async () => {
  const base = state()
  const ops = sidesOf(base).find(x => x.points.length === 2)
  const seen = []
  const proto = Object.getPrototypeOf(document.createElement('div'))
  const had = proto.scrollIntoView
  proto.scrollIntoView = function scrollIntoView(o) { seen.push([this.getAttribute('class'), o]) }
  try {
    mount(html`<${FlowPage} s=${state({ flowView: 'point', flowSide: { areas: ops.id }, flowAt: { id: ops.points[1].id, i: 1 } })} c=${recorder()} />`)
    await waitFor(() => seen.length, { what: 'a row scrolled into view' }).catch(() => {})
  } finally { if (had) proto.scrollIntoView = had; else delete proto.scrollIntoView }
  assert.ok(seen.some(([cls, o]) => /flow-side-pt is-current/.test(cls) && o?.block === 'nearest'), 'the marked row, not the page, scrolled')
})

test('the controller: flowSidePoint enters the side and opens that point there', () => {
  const at = APP.indexOf('\n  flowSidePoint')
  assert.ok(at >= 0, 'app.js has flowSidePoint')
  const body = APP.slice(at, APP.indexOf('\n  flow', at + 10))
  assert.match(body, /flowSide: \{/)
  assert.match(body, /flowAt: \{ id, i \}/)
  assert.match(body, /flowView: 'point'/)
})
