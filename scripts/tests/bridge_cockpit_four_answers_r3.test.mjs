// SPDX-License-Identifier: MIT
// Round 3 of the simulation of the four answers (cockpit.flow.buckets): what the testers reproduced on simulated
// Bridges, each a case of scripts/web/buckets.js and the views that show a point. No npm dependencies.
//
//   node --test scripts/tests/bridge_cockpit_four_answers_r3.test.mjs
import test from 'node:test'
import assert from 'node:assert/strict'
import { loadCockpit } from './cockpit_render.mjs'

const { logic, text } = await loadCockpit()

// Friday, 9 October 2026, noon
const NOW = new Date(2026, 9, 9, 12, 0, 0).getTime()
const MIN = 60000
const TOMORROW = '2026-10-10'

const task = (slug, over = {}) => ({ key: `task:${slug}`, task: slug, title: `Task ${slug}`, status: 'doing', bucket: 'plan',
  priority: 'P2', settle: ['done', 'not_doing'], ...over })
const ask = (id, over = {}) => ({ key: `inbox:${id}`, inbox_id: id, title: `Question ${id}`, art: 'ask', inbox_state: 'open',
  bucket: 'do', gate: 'your-yes', settle: ['done', 'not_doing'], ...over })

function state({ now = [], work = [], later = [], tabs = [], hidden = [], taskRows = [], away = [], ui = {}, ...rest } = {}) {
  return {
    now: NOW, model: { sections: [{ id: 'now', rows: now }, { id: 'give', rows: [] }, { id: 'work', rows: work },
      { id: 'track', rows: [] }, { id: 'later', rows: later }], hidden, returns: [], task_rows: taskRows, away,
    buckets: [], aside: { later: 0, list: 0, done_today: 0 } },
    tabs: { tabs, at_ms: NOW }, driver: { caps: ['tabs', 'launch', 'focus', 'screen', 'key', 'send'] }, triage: { items: {} }, jevOrder: {},
    details: {}, work: { flow: { enabled: true, drop_reasons: [], return_after_s: 20, buckets: { enabled: true } } },
    themes: { enabled: false }, quick: { convs: [] }, flow_ai: {},
    ui: { page: '@flow', busy: {}, flowAt: null, flowChip: 'all', flowJump: null, flowView: 'overview', answered: {}, ...ui }, ...rest,
  }
}

const where = (s, key) => logic.bucketPoints(s, 'en').all.filter(x => x.row?.key === key).map(x => x.bucket)

// ---------------------------------------------------------------- Later on a waiting point

test('a waiting task put off to a day is out of sight until it, whatever its blocker says', () => {
  // round 3: Later > Monday on a task waiting for Mika was counted as Later and still stood in Waiting on others
  const t = task('access-review', { bucket: 'waiting', blocked_by: 'waiting for Mika to reply' })
  const s = state({ work: [t], taskRows: [t], away: [{ key: t.key, until: TOMORROW }] })
  assert.deepEqual(where(s, t.key), [])
  // its day came: back where its blocker puts it
  const back = state({ work: [t], taskRows: [t], away: [{ key: t.key, until: '2026-10-09' }] })
  assert.deepEqual(where(back, t.key), ['waiting'])
})
