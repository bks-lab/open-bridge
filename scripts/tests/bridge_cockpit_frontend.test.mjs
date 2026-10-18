// SPDX-License-Identifier: MIT
// Frontend tests of the cockpit (scripts/web/), no npm dependencies.
//
//   node scripts/tests/bridge_cockpit_frontend.test.mjs
//
// CONTRACT (work/tasks/tab-leitstand-verbessern/web-dashboard-contract.md, section 9.2):
// - text.js: de and en have the same keys, no empty value, no em or en dash, no emoji
// - logic.js: parseDate, nextMonday, duration, parseShortcut, markToken (plus the
//   shortcut plan the command box runs)
// - the vendored Preact+htm bundle is byte for byte the pinned file
// - index.html has no inline script body and no style attribute
// - no http:// or https:// URL in a served file except the vendor bundle
// - no innerHTML in authored JS
// - tokens.css and style.css hold no colour: the server renders colors.css from DESIGN.md
//
// Those are invariants of the source and stay patterns on it. What a view shows is better asserted by
// rendering it: bridge_cockpit_render.test.mjs does that for the return card, the tab controls, the
// session card and the header, against the states of mock.js.
//
// The page's .js files are ES modules without a package.json "type"; to run on every
// supported Node version they are copied to a temp directory as .mjs and imported there.
import { createHash } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import test from 'node:test'
import assert from 'node:assert/strict'

const here = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(here, '..', '..')
const WEB = path.join(ROOT, 'scripts', 'web')
const VENDOR = path.join(WEB, 'vendor', 'htm-preact-3.1.1.module.js')
const VENDOR_SHA256 = '72284e8e9079c87817145df1110f74e8a2aa040b2fc384922e18dfcb46fc1fd7'
const VENDOR_BYTES = 13194
// the components: components.js holds the root and the page router, views/ the rest, one file per area
const VIEW_FILES = fs.existsSync(path.join(WEB, 'views'))
  ? fs.readdirSync(path.join(WEB, 'views')).filter(f => f.endsWith('.js')).sort().map(f => `views/${f}`) : []
const COMPONENT_FILES = ['components.js', ...VIEW_FILES]
const AUTHORED_JS = ['app.js', 'api.js', 'components.js', 'inner.js', 'logic.js', 'motion.js', 'text.js', 'theme.js', 'mock.js', ...VIEW_FILES]
const SERVED_EXT = new Set(['.html', '.js', '.css', '.svg', '.woff2'])

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'bridge-cockpit-frontend-'))
for (const name of ['logic', 'text', 'api', 'motion']) {   // relative imports point at the copies (logic.js reads text.js)
  const src = fs.readFileSync(path.join(WEB, `${name}.js`), 'utf8').replace(/(from\s+'\.\/[^']+)\.js'/g, "$1.mjs'")
  fs.writeFileSync(path.join(tmp, `${name}.mjs`), src)
}
const logic = await import(pathToFileURL(path.join(tmp, 'logic.mjs')).href)
const text = await import(pathToFileURL(path.join(tmp, 'text.mjs')).href)
const api = await import(pathToFileURL(path.join(tmp, 'api.mjs')).href)
const motion = await import(pathToFileURL(path.join(tmp, 'motion.mjs')).href)
process.on('exit', () => fs.rmSync(tmp, { recursive: true, force: true }))

const read = rel => fs.readFileSync(path.join(WEB, rel), 'utf8')
/** The source of every component file as one text, for the tests that look for a pattern wherever it stands */
const readComponents = () => COMPONENT_FILES.map(read).join('\n')

function servedFiles(dir = WEB, rel = '') {
  const out = []
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const r = rel ? `${rel}/${entry.name}` : entry.name
    if (entry.isDirectory()) out.push(...servedFiles(path.join(dir, entry.name), r))
    else if (SERVED_EXT.has(path.extname(entry.name))) out.push(r)
  }
  return out
}

/** All texts of a table as [path, text]; functions get one sample value per parameter */
function leaves(value, at = '') {
  if (typeof value === 'string') return [[at, value]]
  if (typeof value === 'function') return [[`${at}()`, value(...new Array(Math.max(1, value.length)).fill(2))]]
  if (Array.isArray(value)) return value.flatMap((v, i) => leaves(v, `${at}[${i}]`))
  return Object.entries(value).flatMap(([k, v]) => leaves(v, at ? `${at}.${k}` : k))
}

function shape(value) {
  if (typeof value === 'string' || typeof value === 'function') return typeof value
  if (Array.isArray(value)) return value.map(shape)
  return Object.fromEntries(Object.keys(value).sort().map(k => [k, shape(value[k])]))
}

// a fixed local "now": Friday, 9 October 2026, noon
const NOW = new Date(2026, 9, 9, 12, 0, 0).getTime()

// ---------------------------------------------------------------- text.js

test('text tables: de and en have the same keys and nothing is empty', () => {
  const { de, en } = text.TABLES
  assert.deepEqual(shape(de), shape(en))
  for (const [where, value] of [...leaves(de), ...leaves(en)]) {
    assert.equal(typeof value, 'string', where)
    assert.ok(value.trim().length > 0, `empty: ${where}`)
  }
})

test('text tables: no em or en dash, no dash as punctuation, no emoji, no umlaut in English', () => {
  for (const [where, value] of [...leaves(text.TABLES.de), ...leaves(text.TABLES.en)]) {
    assert.doesNotMatch(value, /[\u2014\u2013]| - |--/, where)
    assert.doesNotMatch(value, /\p{Extended_Pictographic}/u, where)
  }
  for (const [where, value] of leaves(text.TABLES.en)) assert.doesNotMatch(value, /[äöüÄÖÜß]/, where)
})

test('text tables: every row action id of the server has a label', () => {
  for (const id of ['restart', 'to_tab', 'approved', 'drop', 'follow_up', 'done', 'advise', 'do', 'ask']) {
    for (const t of Object.values(text.TABLES)) assert.ok(t.action[id], id)
  }
  // one verb for handing work to an agent, the same on every button (14.10.), naming the AI, not a model (17.10.)
  assert.equal(text.TABLES.en.action.do, 'Let AI do it')
  assert.equal(text.TABLES.de.action.do, 'AI machen lassen')
  assert.equal(text.TABLES.en.action.follow_up, 'Follow up')
  assert.equal(text.TABLES.de.action.to_tab, 'Zum Tab')
})

// One word per thing (17.10.): closing is "Close"/"Abhaken" everywhere, a section has one name wherever it
// stands, and the core, the return channel, the scan and the workers speak plain words. The old words are gone.
test('text tables: one word per thing, the retired words appear nowhere', () => {
  const { de, en } = text.TABLES
  assert.equal(de.action.done, 'Abhaken'); assert.equal(en.action.done, 'Close')
  assert.equal(de.settleDone, 'Abhaken'); assert.equal(en.settleDone, 'Close')
  assert.deepEqual(de.section, { now: 'Wartet auf dich', give: 'Kann die AI übernehmen', work: 'Aufgaben', track: 'Aus Boards und Trackern', later: 'Später' })
  assert.deepEqual(en.section, { now: 'Waiting for you', give: 'AI can take over', work: 'Tasks', track: 'From boards and trackers', later: 'Later' })
  // the same sections on the start board (home.sit) and in the assessment Claude reads (logic.situation)
  for (const id of ['now', 'give', 'work', 'later']) {
    assert.equal(de.logic.situation[id], de.section[id], id); assert.equal(en.logic.situation[id], en.section[id], id)
  }
  for (const id of ['now', 'give', 'later']) { assert.equal(de.home.sit[id], de.section[id], id); assert.equal(en.home.sit[id], en.section[id], id) }
  assert.equal(de.home.returnsTitle, 'Bei der AI'); assert.equal(en.home.returnsTitle, 'With AI')
  assert.equal(de.settings.coreTitle, 'Beim Klick auf Bridge'); assert.equal(en.settings.coreTitle, 'On a click on Bridge')
  assert.equal(de.home.coreScan, 'Neu laden'); assert.equal(en.home.coreScan, 'Reload')
  assert.equal(de.home.briefTitle, 'Einschätzung'); assert.equal(en.home.briefTitle, 'Assessment')
  assert.equal(de.home.startTitle, 'Schnellzugriff'); assert.equal(en.home.startTitle, 'Quick access')
  assert.equal(de.workersTab, 'Hintergrundjobs'); assert.equal(en.workersTab, 'Background jobs')
  assert.equal(de.reviewTab, 'Aufräumen'); assert.equal(en.reviewTab, 'Tidy up')
  const flat = t => leaves(t).map(([, v]) => v).join('\n')
  for (const old of ['Erledigen lassen', 'Rückkanal', 'Kern-Klick', 'den Kern', 'Lagebild', 'Startpunkte', 'Arbeitsvorrat',
    'Kann ich abgeben', 'Wartet auf deine Freigabe', 'zum Tab', 'Worker']) assert.ok(!flat(de).includes(old), old)
  for (const old of ['Get it done', 'get it done', 'Return channel', 'Core click', 'the core', 'Picture of the day',
    'Starting points', 'To hand off', 'to hand off', 'Waits for your yes', 'To the tab', 'Workers', 'worker']) assert.ok(!flat(en).includes(old), old)
})

test('text tables: an error text for every error code of the API', () => {
  const codes = ['unauthorized', 'forbidden_origin', 'bad_host', 'bad_fetch_site', 'not_found', 'method_not_allowed',
    'unsupported_media_type', 'payload_too_large', 'unknown_verb', 'invalid_argument', 'invalid_json', 'stale_row',
    'stale_tab', 'not_applicable', 'relay_offline', 'cmux_unavailable', 'cli_unavailable', 'internal']
  for (const t of Object.values(text.TABLES)) for (const c of codes) assert.ok(t.errors[c], c)
})

test('setControl: the control workspace name from the config fills every text, nothing hard-coded', () => {
  const all = () => [...leaves(text.T())].map(([, v]) => v).join('\n')
  for (const lang of ['de', 'en']) {
    text.setLanguage(lang)
    text.setControl(null)
    assert.doesNotMatch(all(), /\{ws\}|Leitstand/)
    text.setControl('Bridge')
    assert.match(text.T().askPlaceholder, /Bridge/)
    assert.match(text.T().relayReason.no_control, /Bridge/)
    assert.doesNotMatch(all(), /\{ws\}|Leitstand/)
  }
  text.setControl(null)
  text.setLanguage('en')
})

test('setLanguage: de... means German, everything else English', () => {
  text.setLanguage('de')
  assert.equal(text.T().action.do, text.TABLES.de.action.do)
  assert.equal(text.language(), 'de')
  text.setLanguage('fr')
  assert.equal(text.T().action.do, text.TABLES.en.action.do)
  text.setLanguage('DE-at')
  assert.equal(text.T().action.do, text.TABLES.de.action.do)
  text.setLanguage(undefined)
  assert.equal(text.T().action.do, text.TABLES.en.action.do)
})

// ---------------------------------------------------------------- logic.js

test('parseDate: ISO, day.month., day.month.year, invalid dates, rollover without a year', () => {
  assert.equal(logic.parseDate('2026-10-14', NOW), '2026-10-14')
  assert.equal(logic.parseDate(' 2026-10-14 ', NOW), '2026-10-14')
  assert.equal(logic.parseDate('2026-02-30', NOW), null)
  assert.equal(logic.parseDate('14.10.', NOW), '2026-10-14')
  assert.equal(logic.parseDate('14.10', NOW), '2026-10-14')
  assert.equal(logic.parseDate('14.10.2026', NOW), '2026-10-14')
  assert.equal(logic.parseDate('1.3.2027', NOW), '2027-03-01')
  assert.equal(logic.parseDate('31.02.', NOW), null)
  assert.equal(logic.parseDate('99.99.', NOW), null)
  // a date without a year that already passed this year means next year
  assert.equal(logic.parseDate('01.03.', NOW), '2027-03-01')
  // today itself is not in the past
  assert.equal(logic.parseDate('09.10.', NOW), '2026-10-09')
  // with an explicit year, the past stays the past
  assert.equal(logic.parseDate('01.03.2026', NOW), '2026-03-01')
  assert.equal(logic.parseDate('tomorrow', NOW), null)
  assert.equal(logic.parseDate('', NOW), null)
})

test('nextMonday: always the coming Monday, a week later on a Monday', () => {
  const day = (y, m, d) => new Date(y, m - 1, d, 12).getTime()
  assert.equal(logic.isoDate(logic.nextMonday(day(2026, 10, 9))), '2026-10-12')    // Friday
  assert.equal(logic.isoDate(logic.nextMonday(day(2026, 10, 11))), '2026-10-12')   // Sunday
  assert.equal(logic.isoDate(logic.nextMonday(day(2026, 10, 12))), '2026-10-19')   // Monday
  assert.equal(logic.isoDate(logic.nextMonday(day(2026, 10, 13))), '2026-10-19')   // Tuesday
})

test('isoDate and clockTime are local', () => {
  assert.equal(logic.isoDate(NOW), '2026-10-09')
  assert.equal(logic.clockTime(NOW), '12:00')
})

test('duration: minutes below an hour, h:mm from an hour on, never negative', () => {
  assert.equal(logic.duration(0), '0 min')
  assert.equal(logic.duration(59 * 60000 + 59000), '59 min')
  assert.equal(logic.duration(60 * 60000), '1:00 h')
  assert.equal(logic.duration(65 * 60000), '1:05 h')
  assert.equal(logic.duration(25 * 3600000 + 7 * 60000), '25:07 h')
  assert.equal(logic.duration(-5000), '0 min')
})

test('parseShortcut: the mod codes, nothing else', () => {
  assert.deepEqual(logic.parseShortcut('1a 3b'), [{ n: 1, letter: 'a' }, { n: 3, letter: 'b' }])
  assert.deepEqual(logic.parseShortcut('  12V  '), [{ n: 12, letter: 'v' }])
  assert.deepEqual(logic.parseShortcut('2c   4w'), [{ n: 2, letter: 'c' }, { n: 4, letter: 'w' }])
  for (const bad of ['', '1', 'a1', '1x', '1a,2b', '1a 2', 'hello', '1aa', '-1a']) {
    assert.equal(logic.parseShortcut(bad), null, bad)
  }
})

test('planShortcut: tab rows jump, a/w refused like the mod, letters grouped', () => {
  const r = (key, extra = {}) => ({ key, title: key, bucket: 'do', inbox_id: null, gate: null, inbox_state: null, tab: null, ...extra })
  const rows = new Map([
    [1, r('task:a')],
    [2, r('task:b', { tab: { ref: 'surface:1', state: 'working', live: true, waiting: false } })],
    [3, r('inbox:x', { inbox_id: 'x', gate: 'only-you' })],
    [4, r('inbox:y', { inbox_id: 'y', inbox_state: 'approved' })],
    [5, r('ref:o/r#1', { bucket: 'waiting' })],
    [6, r('task:c')],
    [7, r('task:d', { tab: { ref: 'surface:2', state: 'shell', live: false, waiting: false } })],
  ])
  const plan = logic.planShortcut(logic.parseShortcut('1a 2a 3a 4w 5a 6w 9a 3v 1b 6c 7a 2b'), n => rows.get(n))
  assert.deepEqual(plan.missing, [9])
  assert.deepEqual(plan.jump.map(x => x.n), [2])                    // 2b is not a start: later, below
  assert.deepEqual(plan.refused.map(x => [x.n, x.reason]), [[3, 'only_you'], [4, 'approved'], [5, 'waiting']])
  assert.deepEqual(plan.do.map(x => x.n), [1, 7])                    // a dead shell tab does not jump
  assert.deepEqual(plan.ws.map(x => x.n), [6])
  assert.deepEqual(plan.advise.map(x => x.n), [3])                   // v is fine for only-you
  assert.deepEqual(plan.later.map(x => x.n), [1, 2])
  assert.deepEqual(plan.drop.map(x => x.n), [6])
})

test('letterShortcut: a v c b w act once per press, an auto-repeat keydown acts not at all', () => {
  for (const key of ['a', 'v', 'c', 'b', 'w']) assert.equal(logic.letterShortcut({ key, repeat: false }), key)
  assert.equal(logic.letterShortcut({ key: 'a' }), 'a')
  assert.equal(logic.letterShortcut({ key: 'a', repeat: true }), null)   // a held key sends no second action
  for (const key of ['x', 'j', 'Enter', 'ab', '']) assert.equal(logic.letterShortcut({ key }), null, key)
  // the keyboard handler goes through it, so the repeat check cannot be bypassed
  assert.match(read('app.js'), /letterShortcut\(e\)/)
})

test('createWithBusy: a row action already busy runs fn once, clears however fn ends, rows of a bulk count', async () => {
  let busy = {}
  const refused = []
  const withBusy = logic.createWithBusy(() => busy, f => { busy = f(busy) }, keys => refused.push(keys))
  const row = { refuse: true }
  let runs = 0
  let release
  const first = withBusy('task:a', 'do_it', () => { runs += 1; return new Promise(res => { release = res }) }, row)
  assert.deepEqual(busy, { 'task:a': 'do_it' })
  assert.equal(await withBusy('task:a', 'do_it', () => { runs += 1; return 'second' }, row), null)
  assert.equal(runs, 1)
  assert.deepEqual(refused, [['task:a']])   // the refusal is told, never silent
  release('first')
  assert.equal(await first, 'first')
  assert.deepEqual(busy, {})
  assert.equal(await withBusy('task:a', 'do_it', () => { runs += 1; return 'again' }, row), 'again')
  assert.equal(runs, 2)
  await assert.rejects(withBusy('task:a', 'do_it', () => { throw new Error('boom') }, row), /boom/)
  assert.deepEqual(busy, {})
  // a bulk marks each of its rows, so a single action on one of them waits its turn
  let releaseBulk
  const bulk = withBusy('task:a,task:b', 'do_it', () => new Promise(res => { releaseBulk = res }), { rows: ['task:a', 'task:b'], refuse: true })
  assert.deepEqual(busy, { 'task:a,task:b': 'do_it', 'task:a': 'do_it', 'task:b': 'do_it' })
  assert.equal(await withBusy('task:b', 'drop', () => 'ran', row), null)
  releaseBulk(true)
  await bulk
  assert.deepEqual(busy, {})
})

test('createWithBusy: a key that is not a row (a setting, a question) is never refused', async () => {
  let busy = {}
  const refused = []
  const withBusy = logic.createWithBusy(() => busy, f => { busy = f(busy) }, keys => refused.push(keys))
  let release
  const first = withBusy('home_tiles', 'home_tiles', () => new Promise(res => { release = res }))
  // a second tile flip or a question about another row while the first is pending still runs
  assert.equal(await withBusy('home_tiles', 'home_tiles', () => 'second'), 'second')
  assert.equal(await withBusy('ask:row', 'row', () => 'other row'), 'other row')
  assert.deepEqual(refused, [])
  release('first')
  assert.equal(await first, 'first')
  assert.deepEqual(busy, {})
})

test('planBusy: row actions refuse when busy, a bulk keeps its own key and names what it left out', () => {
  // settings and questions are no row: never refused
  assert.equal(logic.planBusy('home_tiles', { ids: ['a'] }, {}).refuse, false)
  assert.equal(logic.planBusy('home_tiles', { ids: ['a'] }, {}).key, 'home_tiles')
  assert.equal(logic.planBusy('launch_settings', { settings: {} }, {}).refuse, false)
  assert.equal(logic.planBusy('a2a_poll', { conv: 'c1' }, {}).key, 'quick:c1')
  // a pin is a toggle on the start page, not an action on the row: a quick second flip still goes
  assert.equal(logic.planBusy('pin', { key: 'task:a', on: true }, { 'task:a': 'pin' }).refuse, false)
  // one row
  const one = logic.planBusy('drop', { key: 'task:a' }, {})
  assert.deepEqual([one.key, one.refuse, one.refused, one.rows, one.skipped], ['task:a', true, false, [], []])
  assert.equal(logic.planBusy('tab_jump', { tab_ref: 't1' }, {}).refuse, true)
  // a bulk with one row in flight: that row left out, the key stays the whole list the buttons check
  const busy = { 'task:a': 'do_it' }
  const bulk = logic.planBusy('do_it', { keys: ['task:a', 'task:b', 'task:c'], target: 'workspace' }, busy)
  assert.equal(bulk.key, 'task:a,task:b,task:c')
  assert.deepEqual(bulk.rows, ['task:b', 'task:c'])
  assert.deepEqual(bulk.args, { keys: ['task:b', 'task:c'], target: 'workspace' })
  assert.deepEqual(bulk.skipped, ['task:a'])
  assert.equal(bulk.refused, false)
  assert.equal(bulk.refuse, true)
  // every row in flight: nothing is sent, and it says so
  const all = logic.planBusy('advise', { keys: ['task:a'] }, busy)
  assert.equal(all.refused, true)
  assert.deepEqual(all.skipped, ['task:a'])
})

test('act() wires planBusy into withBusy and tells what it left out', () => {
  const app = read('app.js')
  const body = app.match(/async function act\(verb, args = \{\}\) \{[\s\S]*?\n\}/)[0]
  assert.match(body, /planBusy\(verb, args, store\.get\(\)\.ui\.busy\)/)
  assert.match(body, /\.skipped\.length[\s\S]{0,120}busySkipped/)
  assert.match(body, /\.refused\)[\s\S]{0,80}return null/)
  assert.match(body, /withBusy\(p\.key, verb,/)
  assert.match(body, /withLaunch\(verb, p\.args,/)
  assert.match(body, /\{ rows: p\.rows, refuse: p\.refuse \}\)/)
  // a refusal inside withBusy shows a note too
  assert.match(app, /createWithBusy\([^\n]*busyAlready/)
})

test('planShortcut: c on an inbox row asks why like the Drop button, c on a task drops', () => {
  const rows = new Map([
    [1, { key: 'task:a', title: 'a', bucket: 'do', inbox_id: null, tab: null }],
    [2, { key: 'inbox:x', title: 'x', bucket: 'do', inbox_id: 'x', tab: null }],
    [3, { key: 'inbox:y', title: 'y', bucket: 'do', inbox_id: 'y', tab: null }],
  ])
  const plan = logic.planShortcut(logic.parseShortcut('1c 2c 3c'), n => rows.get(n))
  assert.deepEqual(plan.drop.map(x => x.n), [1])
  assert.deepEqual(plan.askDrop.map(x => x.n), [2, 3])
  // the command box and the c key run the plan, and its inbox drops open the drop dialog
  assert.match(read('app.js'), /plan\.askDrop[\s\S]{0,200}ctl\.askDrop\(/)
})

test('markToken: profile color names map to design tokens, unknown to muted', () => {
  assert.equal(logic.markToken('red'), 'danger')
  assert.equal(logic.markToken('Yellow'), 'warning')
  assert.equal(logic.markToken('orange'), 'warning')
  assert.equal(logic.markToken('green'), 'success')
  assert.equal(logic.markToken('blue'), 'info')
  assert.equal(logic.markToken('cyan'), 'info')
  assert.equal(logic.markToken('magenta'), 'secondary')
  assert.equal(logic.markToken('purple'), 'secondary')
  assert.equal(logic.markToken('#ff0000'), 'on-surface-muted')
  assert.equal(logic.markToken('url(x)'), 'on-surface-muted')
  assert.equal(logic.markToken(null), 'on-surface-muted')
})

test('model views: rows by key, compact or all per section, numbers, tab groups', () => {
  const row = key => ({ key })
  const model = {
    sections: [
      { id: 'now', total: 2, rows: [row('a'), row('b')], compact: ['a'] },
      { id: 'later', total: 1, rows: [row('c')], compact: [] },
    ],
    hidden: [row('h')],
    task_rows: [row('task:p'), row('a')],
    numbers: { a: 1, b: 2, c: 3 },
  }
  const byKey = logic.indexRows(model)
  // a task only a page shows (task_rows) resolves too; a card row keeps its own entry
  assert.deepEqual([...byKey.keys()], ['a', 'b', 'c', 'h', 'task:p'])
  assert.deepEqual(logic.displayedRows(model, {}, byKey).map(r => r.key), ['a'])
  assert.deepEqual(logic.displayedRows(model, { now: true, later: true }, byKey).map(r => r.key), ['a', 'b', 'c'])
  assert.equal(logic.rowByNumber(model, byKey).get(3).key, 'c')
  const tab = (ref, state, workspace, extra = {}) => ({ ref, name: ref, state, workspace, ...extra })
  const groups = logic.groupTabs([tab('s1', 'shell', 'B'), tab('s2', 'working', 'A'), tab('s3', 'needs-you', 'B'),
    tab('s4', 'waiting', 'C', { is_control: true })])
  assert.deepEqual(groups.map(g => [g.workspace, g.tabs.map(t => t.ref)]), [['B', ['s3', 's1']], ['A', ['s2']]])
  assert.deepEqual(logic.attentionTabs([tab('x', 'waiting', 'A', { waiting: true, is_control: true }),
    tab('y', 'working', 'A', { long: 'running' }), tab('z', 'needs-you', 'A', { waiting: true })]).map(t => t.ref), ['z', 'y'])
})

test('notes are deduplicated while their toast is up and capped', () => {
  let notes = []
  const up = [{ id: 1, text: 'x', tone: 'ok' }]
  notes = logic.addNote(notes, { text: 'x', tone: 'ok' }, 1000)
  notes = logic.addNote(notes, { text: 'x', tone: 'ok' }, 2000, up)
  assert.equal(notes.length, 1)
  notes = logic.addNote(notes, { text: 'x', tone: 'ok' }, 3000)
  assert.equal(notes.length, 2)
  for (let i = 0; i < 30; i++) notes = logic.addNote(notes, { text: `n${i}`, tone: 'info' }, 30000 + i)
  assert.equal(notes.length, 20)
})

test('startRefusal and errorText', () => {
  assert.equal(logic.startRefusal({ inbox_id: 'x', gate: 'only-you' }), 'only_you')
  assert.equal(logic.startRefusal({ inbox_id: 'x', gate: 'your-yes' }), null)
  assert.equal(logic.startRefusal({ bucket: 'waiting' }), 'waiting')
  text.setLanguage('en')
  const t = text.T()
  assert.equal(logic.errorText({ code: 'stale_row', message: 'x' }, t), t.errors.stale_row)
  assert.match(logic.errorText({ code: 'invalid_argument', message: 'x', field: 'until' }, t), /until/)
  assert.equal(logic.errorText({ code: 'something_new', message: 'raw' }, t), 'raw')
})

// ---------------------------------------------------------------- files

test('vendor bundle: pinned size and sha256, exports what the page imports', () => {
  const bytes = fs.readFileSync(VENDOR)
  assert.equal(bytes.length, VENDOR_BYTES)
  assert.equal(createHash('sha256').update(bytes).digest('hex'), VENDOR_SHA256)
  const exported = /export\{([^}]*)\}/.exec(bytes.toString('utf8'))[1].split(',').map(x => x.trim().split(/\s+as\s+/).pop())
  for (const file of ['app.js', ...COMPONENT_FILES]) {
    const m = /import \{([^}]*)\} from '(?:\.\.?\/)+vendor\/htm-preact-3\.1\.1\.module\.js'/.exec(read(file))
    if (file === 'app.js') assert.ok(m, file)
    if (!m) continue
    for (const name of m[1].split(',').map(x => x.trim()).filter(Boolean)) assert.ok(exported.includes(name), `${file}: ${name}`)
  }
})

test('every relative import names an export that exists', () => {
  const exportsOf = file => {
    const src = read(file)
    return new Set([...[...src.matchAll(/export (?:async )?(?:function|const|let|class) ([A-Za-z_$][\w$]*)/g)].map(m => m[1]),
      ...[...src.matchAll(/^export \{([^}]*)\}/gm)].flatMap(m => m[1].split(',').map(x => x.trim().split(/\s+as\s+/).pop()).filter(Boolean))])
  }
  for (const file of AUTHORED_JS) {
    for (const m of read(file).matchAll(/(?:import|export) \{([^}]*)\} from '(\.\.?\/[\w./-]+\.js)'/g)) {
      const target = path.posix.join(path.posix.dirname(file), m[2])
      if (target.startsWith('vendor/')) continue
      const names = m[1].split(',').map(x => x.trim().split(/\s+as\s+/)[0]).filter(Boolean)
      const have = exportsOf(target)
      for (const name of names) assert.ok(have.has(name), `${file} imports ${name} from ${target}`)
    }
  }
})

test('index.html: no inline script body, no style attribute or element, module entry and theme script', () => {
  const page = read('index.html')
  for (const m of page.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)) {
    assert.match(m[1], /\bsrc=/, 'every script has a src')
    assert.equal(m[2].trim(), '', 'no inline script body')
  }
  assert.doesNotMatch(page, /\sstyle\s*=/i)
  assert.doesNotMatch(page, /<style\b/i)
  assert.doesNotMatch(page, /\son[a-z]+\s*=/i, 'no inline event handler')
  assert.match(page, /<script src="theme\.js"><\/script>/)
  assert.match(page, /<script type="module" src="app\.js"><\/script>/)
  assert.match(page, /<meta charset="utf-8">/)
})

test('no http:// or https:// URL in a served file except the vendor bundle', () => {
  const files = servedFiles()
  assert.ok(files.includes('index.html') && files.includes('app.js'))
  for (const rel of files) {
    if (rel === 'vendor/htm-preact-3.1.1.module.js') continue
    const src = read(rel)
    if (rel === 'mock.js') {
      // The mock holds invented example links as row data (never loaded): only the reserved
      // example.org domain (RFC 2606) is allowed there.
      for (const m of src.matchAll(/https?:\/\/[^\s'"`)]+/g)) assert.match(m[0], /^https:\/\/example\.org\//, m[0])
      continue
    }
    assert.doesNotMatch(src, /https?:\/\//, rel)
  }
})

test('no innerHTML and no dangerouslySetInnerHTML in authored JS', () => {
  for (const file of AUTHORED_JS) {
    assert.doesNotMatch(read(file), /innerHTML|outerHTML|insertAdjacentHTML|document\.write|eval\(|new Function/, file)
  }
})

test('authored files carry the SPDX header and no em or en dash', () => {
  const header = {
    '.js': '// SPDX-License-Identifier: MIT', '.css': '/* SPDX-License-Identifier: MIT */',
    '.html': '<!-- SPDX-License-Identifier: MIT -->', '.md': '',
  }
  for (const rel of [...AUTHORED_JS, 'tokens.css', 'style.css', 'index.html', 'vendor/README.md']) {
    const src = read(rel)
    const h = header[path.extname(rel)]
    if (h) assert.ok(src.split('\n').slice(0, 3).includes(h), `${rel}: SPDX header`)
    assert.doesNotMatch(src, /[\u2014\u2013]/, `${rel}: dash`)
  }
  assert.match(read('vendor/README.md'), /72284e8e9079c87817145df1110f74e8a2aa040b2fc384922e18dfcb46fc1fd7/)
})

test('tokens.css and style.css carry no colour of their own: colors.css comes from DESIGN.md (design.py)', () => {
  assert.doesNotMatch(read('tokens.css'), /#[0-9A-Fa-f]{3,8}\b/)
  assert.doesNotMatch(read('style.css'), /#[0-9A-Fa-f]{3,8}\b/)
  assert.match(read('index.html'), /<link rel="stylesheet" href="colors.css">/)
})

// ---------------------------------------------------------------- review findings

/** A stand-in EventSource: the test fires open and error with the readyState a browser would have */
class FakeEventSource {
  static CONNECTING = 0
  static OPEN = 1
  static CLOSED = 2
  static last = null
  constructor(url) {
    this.url = url
    this.readyState = FakeEventSource.CONNECTING
    this.listeners = {}
    FakeEventSource.last = this
  }
  addEventListener(name, fn) { this.listeners[name] = fn }
  close() { this.readyState = FakeEventSource.CLOSED }
}

test('FE-1: a refused connection (EventSource stays CONNECTING) reports the connection as down', () => {
  const saved = globalThis.EventSource
  globalThis.EventSource = FakeEventSource
  try {
    const seen = []
    const stream = api.createApi().events({}, conn => seen.push(conn))
    const es = FakeEventSource.last
    es.readyState = FakeEventSource.OPEN
    es.onopen()
    es.readyState = FakeEventSource.CONNECTING   // the server went away; the browser retries by itself
    es.onerror()
    assert.equal(seen.at(-1), 'down')
    es.readyState = FakeEventSource.OPEN
    es.onopen()
    assert.equal(seen.at(-1), 'open')
    stream.close()
  } finally {
    globalThis.EventSource = saved
  }
})

test('FE-1: the page shows the connection as lost once it is not open for 3 s, at once when down', () => {
  assert.equal(logic.connLost('open', 0, 10000), false)
  assert.equal(logic.connLost('down', 9999, 10000), true)
  assert.equal(logic.connLost('connecting', 8000, 10000), false)
  assert.equal(logic.connLost('connecting', 6000, 10000), true)
})

test('FE-1 / FE-3: warnings name a lost connection, a stale model and a failed pass, at every width', () => {
  const t = text.TABLES.en
  const base = { conn: 'open', connMs: 0, now: 10000, model: { stale: false }, loading: { pass: null, last_error: null } }
  assert.deepEqual(logic.pageWarnings(base, t), [])
  const words = st => logic.pageWarnings({ ...base, ...st }, t).map(w => w.word)
  assert.deepEqual(words({ conn: 'down' }), [t.connLost])
  assert.deepEqual(words({ conn: 'connecting', connMs: 0 }), [t.connLost])
  assert.deepEqual(words({ model: { stale: true } }), [t.staleModel])
  assert.deepEqual(words({ loading: { pass: null, last_error: { message: 'timeout' } } }), [t.loadFailed('timeout')])
  assert.deepEqual(words({ loading: { pass: 'full', last_error: { message: 'timeout' } } }), [])
  const css = read('style.css')
  const narrow = css.slice(css.indexOf('@media (max-width: 899px)'), css.indexOf('@media (max-width: 640px)'))
  for (const cls of ['hdr-asof', 'hdr-warn', 'mobile-status', 'hdr-relay']) {
    assert.doesNotMatch(narrow, new RegExp(`\\.${cls}[^{]*\\{[^}]*display:\\s*none`), `${cls} hidden below 900 px`)
  }
  const src = readComponents()
  assert.match(src, /pageWarnings\(/)
  // below 900 px the warnings and the relay state have their own line under the header
  const sw = src.match(/function MobileSwitch\([\s\S]*?\n\}/)[0]
  assert.match(sw, /<\$\{AsOf\}/)
  assert.match(sw, /<\$\{RelayBadge\}/)
})

test('FE-2: single-key shortcuts do nothing while a drawer or a confirmation is open; Escape and g t still work', () => {
  const open = { confirm: null, drawer: 'notes' }
  for (const key of ['c', 'a', 'w', 'v', 'b', 'x', 'j', 'k', 'Enter', 'r', '/', '?']) {
    assert.equal(logic.modalKeyAllowed(open, key, false), false, key)
    assert.equal(logic.modalKeyAllowed({ confirm: { kind: 'approve_all' }, drawer: null }, key, false), false, key)
  }
  assert.equal(logic.modalKeyAllowed({ confirm: null, drawer: 'tabs' }, 'g', false), true)
  assert.equal(logic.modalKeyAllowed({ confirm: null, drawer: 'tabs' }, 't', true), true)
  assert.equal(logic.modalKeyAllowed({ confirm: null, drawer: null }, 'c', false), true)
  assert.match(read('app.js'), /modalKeyAllowed\(/)
})

test('FE-4: details reload after the model moved on or an action touched them; an error waits for a retry', () => {
  assert.equal(logic.detailNeedsLoad(undefined, 5), true)
  assert.equal(logic.detailNeedsLoad({ status: 'ok', ver: 5 }, 5), false)
  assert.equal(logic.detailNeedsLoad({ status: 'ok', ver: 4 }, 5), true)
  assert.equal(logic.detailNeedsLoad({ status: 'ok', ver: 5, stale: true }, 5), true)
  assert.equal(logic.detailNeedsLoad({ status: 'loading', ver: 4 }, 5), false)
  assert.equal(logic.detailNeedsLoad({ status: 'error', ver: 4 }, 5), false)
  const details = { inbox: { 'a-1': { status: 'ok', ver: 5 }, 'b-2': { status: 'ok', ver: 5 } }, task: { 'demo-task': { status: 'ok', ver: 5 } } }
  const out = logic.invalidateDetails(details, { inbox_id: 'a-1', task: 'demo-task' })
  assert.equal(out.inbox['a-1'].stale, true)
  assert.equal(out.task['demo-task'].stale, true)
  assert.equal(out.inbox['b-2'].stale, undefined)
  assert.equal(logic.invalidateDetails(details, null), details)
  assert.match(readComponents(), /t\.retry/)
})

test('FE-5: fetched "more" items count only for the run they came from', () => {
  const more = { 'today/activity': { items: [1, 2], total: 2, ver: 100 }, 'x/y': { items: [], total: 0, ver: 90 } }
  assert.deepEqual(Object.keys(logic.freshMore(more, { collected_ms: 100 })), ['today/activity'])
  assert.deepEqual(logic.freshMore(more, null), {})
  const same = { a: { ver: 7 } }
  assert.equal(logic.freshMore(same, { collected_ms: 7 }), same)
})

test('FE-6: Tab cycles inside an open dialog, both ways', () => {
  assert.equal(logic.nextFocusIndex(3, 2, false), 0)
  assert.equal(logic.nextFocusIndex(3, 0, true), 2)
  assert.equal(logic.nextFocusIndex(3, -1, false), 0)
  assert.equal(logic.nextFocusIndex(3, -1, true), 2)
  assert.equal(logic.nextFocusIndex(0, -1, false), -1)
  const src = readComponents()
  assert.match(src, /nextFocusIndex\(/)
  assert.match(src, /opener/)
})

test('FE-7: below 900 px the relay state keeps a written word next to its dot', () => {
  const css = read('style.css')
  const narrow = css.slice(css.indexOf('@media (max-width: 899px)'), css.indexOf('@media (max-width: 640px)'))
  assert.doesNotMatch(narrow, /\.hdr-relay[^{]*\{[^}]*clip/)
  assert.doesNotMatch(narrow, /state-line[^{]*\{[^}]*(clip|position:\s*absolute)/)
})

test('FE-8: at phone width page tables stack, so the actions stay in view', () => {
  const css = read('style.css')
  const phone = css.slice(css.indexOf('@media (max-width: 640px)'))
  assert.doesNotMatch(phone.slice(0, phone.indexOf('\n}\n')), /min-width:\s*34rem/)
  assert.match(phone, /\.tbl tr\b[^{]*\{[^}]*display:\s*(block|grid|flex)/)
})

test('task check: rows filter per verdict or changed, sort by verdict, priority or quiet, count per verdict', () => {
  const r = (key, verdict, priority, days, extra = {}) => ({ key, title: key, priority, review: { verdict, days_since_activity: days, ...extra } })
  const rows = [r('a', 'continue', 'P0', 1), r('b', 'close', 'P2', 4), r('c', 'stale', 'P1', 40, { changed: true }),
    r('d', 'close', 'P1', 2), { key: 'e', title: 'e', review: null }]
  assert.deepEqual(logic.reviewRows(rows).map(x => x.key), ['d', 'b', 'c', 'a'])
  assert.deepEqual(logic.reviewRows(rows, 'close').map(x => x.key), ['d', 'b'])
  assert.deepEqual(logic.reviewRows(rows, 'changed').map(x => x.key), ['c'])
  assert.deepEqual(logic.reviewRows(rows, 'all', 'priority').map(x => x.key), ['a', 'd', 'c', 'b'])
  assert.deepEqual(logic.reviewRows(rows, 'all', 'activity').map(x => x.key), ['c', 'b', 'd', 'a'])
  const n = logic.verdictCounts(rows)
  assert.equal(n.all, 4)
  assert.equal(n.close, 2)
  assert.equal(n.changed, 1)
  assert.equal(n.waiting, 0)
  assert.equal(logic.confidenceDots('medium'), '●●○')
  assert.equal(logic.confidenceDots(undefined), '○○○')
  assert.equal(logic.centsText(0.42, 'de'), '0,42')
  assert.equal(logic.centsText(2.1, 'en'), '2.10')
  assert.equal(logic.verdictToken('close'), 'danger')
})

test('task check: every verdict and close reason has a word in both languages', () => {
  for (const lang of ['en', 'de']) {
    text.setLanguage(lang)
    const t = text.T()
    for (const v of logic.VERDICT_ORDER) {
      assert.ok(t.verdictName[v] && t.verdictTag[v], `${lang} ${v}`)
    }
    for (const r of ['done', 'not_doing', 'superseded', 'elsewhere', 'auto']) assert.ok(t.closeReason[r], `${lang} ${r}`)
  }
})

test('the check page survives a model update: fixPage keeps every page of the tab order, Alt follows it', () => {
  const body = read('app.js').match(/function fixPage\(\) \{[\s\S]*?\n\}/)[0]
  assert.match(body, /pageOrder\(s\)/)
  const order = readComponents().match(/function pageList\(s\) \{[\s\S]*?\n\}/)[0]
  for (const page of ["'briefing'", 'SESSIONS_PAGE', 'WORKERS_PAGE', 'CHAT_PAGE', 'CHECK_PAGE']) assert.ok(order.includes(page), page)
  assert.match(readComponents(), /export const CHECK_PAGE = '@check'/)
  assert.match(read('app.js'), /const ids = pageOrder\(s\)/)
})

// ---------------------------------------------------------------- motion.js and the drawings

test('motion: a spring starts at 0, arrives at 1 and never overshoots at zeta 0.95', () => {
  assert.equal(motion.spring(0, 0), 0)
  assert.equal(motion.spring(-1, 0), 0)
  let prev = 0
  for (let T = 0.01; T < 2; T += 0.01) {
    const k = motion.spring(T, 0)
    assert.ok(k <= 1.0001, `overshoot at ${T}`)
    prev = k
  }
  assert.ok(prev > 0.999)
})

test('motion: a new target in mid move bends the value, it never jumps', () => {
  const moves = [[0, 100], [0.15, 20]]
  let prev = motion.springTo(0, 0, moves)
  for (let T = 0.005; T < 1.5; T += 0.005) {
    const v = motion.springTo(T, 0, moves)
    assert.ok(Math.abs(v - prev) < 8, `jump of ${v - prev} at ${T}`)
    prev = v
  }
  assert.ok(Math.abs(prev - 20) < 0.5)
  assert.equal(motion.settled(0.1, moves), false)
  assert.equal(motion.settled(3, moves), true)
})

test('motion: a hit rises in 80 ms and decays; points on a rail stay inside it', () => {
  assert.equal(motion.flash(0, [1]), 0)
  assert.ok(Math.abs(motion.flash(1.08, [1]) - 1) < 1e-9)
  assert.ok(motion.flash(2, [1]) < 0.1)
  for (const u of motion.flowPoints(7.3, 4)) assert.ok(u >= 0 && u < 1)
  assert.equal(motion.flowAlpha(0), 0)
  assert.equal(motion.flowAlpha(0.5, 0.2), 0)
  assert.equal(motion.flowAlpha(0.5), 1)
})

test('drawings: the check flow names its tiers, the cheaper one feeds the next', () => {
  const flow = logic.checkFlow({ reviewed: 13, cached: 2, tiers: [
    { model: 'haiku-5-5', answered: 10, cost_ct: 0.47 }, { model: 'sonnet-5-5', answered: 1, cost_ct: 2 }] })
  assert.equal(flow.total, 13)
  assert.equal(flow.cached, 2)
  assert.deepEqual(flow.tiers.map(x => x.fromPrev), [false, true])
  // a direct closer look (escalate) asks only the strong model: it draws from the tasks
  assert.deepEqual(logic.checkFlow({ reviewed: 1, tiers: [{ model: 'sonnet-5-5', answered: 1, cost_ct: 2 }] }).tiers[0].fromPrev, false)
  assert.equal(logic.checkFlow(null), null)
})

test('drawings: verdict segments follow the verdict order and fill the bar', () => {
  const seg = logic.verdictSegments({ continue: 6, close: 1, waiting: 2, stale: 1, unclear: 0 })
  assert.deepEqual(seg.map(x => x.verdict), ['close', 'stale', 'waiting', 'continue'])
  assert.ok(Math.abs(seg.reduce((n, x) => n + x.w, 0) - 1) < 1e-9)
  assert.equal(seg[1].x, 0.1)
  assert.deepEqual(logic.verdictSegments({}), [])
})

test('drawings: agent lanes sit inside the window, an old agent starts at the left edge', () => {
  const lane = logic.agentLane([{ id: 'a', since_ms: NOW - 600000 }, { id: 'b', since_ms: NOW - 7200000 }], NOW, 1800000)
  assert.ok(Math.abs(lane[0].x0 - 2 / 3) < 1e-9)
  assert.equal(lane[1].x0, 0)
  assert.equal(lane[1].older, true)
  assert.equal(logic.laneWindow([{ since_ms: NOW - 60000 }], NOW), 600000)
  assert.equal(logic.laneWindow([{ since_ms: NOW - 1200000 }], NOW), 1500000)
  assert.equal(logic.laneWindow([{ since_ms: NOW - 9e6 }], NOW), 3600000)
  const p = logic.runProgress({ started_ms: NOW - 40000 }, NOW, 28)
  assert.equal(p.over, true)
  assert.equal(p.frac, 0.97)
  assert.equal(logic.runProgress(null, NOW, 28), null)
})

test('drawings: a gauge fills against its max or the section, marks the time and says when it runs ahead', () => {
  const items = [{ meter: { value: 120, unit: '$' } }, { meter: { value: 30, unit: '$' } }, { meter: { value: 74, max: 100, unit: '%' } }, {}]
  assert.equal(logic.meterScale(items), 120)
  assert.deepEqual(logic.meterView(items[1].meter, 120), { frac: 0.25, pace: null, ahead: false, relative: true })
  const quota = logic.meterView({ value: 74, max: 100, unit: '%', elapsed: 0.5 }, 0)
  assert.equal(quota.ahead, true)
  assert.equal(logic.meterView({ value: 40, max: 100, unit: '%', elapsed: 0.5 }, 0).ahead, false)
  assert.equal(logic.meterView(null, 0), null)
  assert.equal(logic.meterText({ value: 74, max: 100, unit: '%' }, 74, 'de'), '74 %')
  assert.equal(logic.meterText({ value: 12.5, unit: '$' }, 12.5, 'de'), '$12.50')
  assert.equal(logic.meterText({ value: 10, max: 1000, unit: 'EUR' }, 10, 'en'), '10 / 1000 EUR')
})

test('drawings: a gauge is a half circle from the left, bands only where the source names them', () => {
  const at = (f, r) => logic.gaugePoint(f, r)
  assert.deepEqual(at(0, 80).map(Math.round), [20, 100])
  assert.deepEqual(at(1, 80).map(Math.round), [180, 100])
  assert.deepEqual(at(0.5, 80).map(Math.round), [100, 20])
  assert.ok(logic.gaugeArc(0, 1, 80).startsWith('M 20.00 100.00 A 80 80'))
  assert.equal(logic.gaugeArc(0.3, 0.3, 80), '')
  assert.deepEqual(logic.gaugeBands({ value: 74, max: 100, warn: 80, bad: 95 }).map(b => [b.token, b.from, b.to]),
    [['success', 0, 0.8], ['warning', 0.8, 0.95], ['danger', 0.95, 1]])
  assert.deepEqual(logic.gaugeBands({ value: 74, max: 100 }), [])
  assert.equal(logic.gaugeSection([{ meter: { value: 1, max: 100 } }, { meter: { value: 2, max: 10 } }]), true)
  assert.equal(logic.gaugeSection([{ meter: { value: 1, max: 100 } }, { title: 'x' }]), false)
  assert.equal(logic.gaugeSection([]), false)
})

test('tab view: a terminal reads as chat lines, blank runs collapse', () => {
  const lines = logic.screenLines('❯ fix the readme\n\n\n⏺ Reading README.md\n  ⎿  42 lines\nmore output\n\n> next\n\n')
  assert.deepEqual(lines.map(l => l.kind), ['user', 'gap', 'claude', 'tool', 'plain', 'gap', 'user'])
  assert.equal(lines[2].text, '⏺ Reading README.md')
  assert.deepEqual(logic.screenLines(''), [])
})

test('workers: tones, strip marks, facets that count without themselves, groups in view order', () => {
  const runs = [
    { id: 'a', title: 'Mail', kind: 'interval', sphere: 'work', state: 'in_sync', host: 'm', system: 'mail', findings: [] },
    { id: 'b', title: 'Pilot', kind: 'daemon', sphere: 'work', state: 'absent', host: 'm', system: 'board', findings: [{ severity: 'high' }] },
    { id: 'c', title: 'Old', kind: 'interval', sphere: 'privat', state: 'drifted', host: 'm', system: 'mail', findings: [{ severity: 'info' }] },
  ]
  assert.equal(logic.workerTone(runs[0]), 'ok')
  assert.equal(logic.workerTone(runs[1]), 'bad')
  assert.equal(logic.workerTone({ state: 'brand_new' }), 'warn')
  assert.deepEqual(logic.stripMark({ verdict: 'failed' }), ['✗', 'bad'])
  assert.deepEqual(logic.stripMark({ verdict: 'odd' }), ['?', 'warn'])
  assert.deepEqual(logic.filterWorkers(runs, { attention: true }).map(r => r.id), ['b'])
  assert.deepEqual(logic.filterWorkers(runs, { q: 'pil' }).map(r => r.id), ['b'])
  const f = logic.workerFacets(runs, { kind: 'interval' })
  assert.deepEqual(f.kind, { interval: 2, daemon: 1 })      // the facet itself is not applied to its own counts
  assert.deepEqual(f.sphere, { work: 1, privat: 1 })
  assert.deepEqual(logic.groupBySystem(runs, [{ id: 'board', title: 'Board' }, { id: 'mail', title: 'Mail' }]).map(g => [g.title, g.runs.length]),
    [['Board', 1], ['Mail', 2]])
})

test('logic: drawn sections filter by search, state, group and tags; a tag facet counts without its own choice', () => {
  const rows = [
    { title: 'fn-a', tone: null, group: 'Azure', tags: { Kind: 'Function App', State: 'running' } },
    { title: 'fn-b', tone: 'dim', group: 'Azure', tags: { Kind: 'Function App', State: 'stopped' } },
    { title: 'kv', tone: null, group: 'Azure', tags: { Kind: 'Key Vault', State: 'present', Region: 'westeurope' } },
    { title: 'other', tone: 'bad', group: 'CF' },
  ]
  assert.deepEqual(logic.filterRows(rows, { tags: { Kind: 'Function App' } }).map(r => r.title), ['fn-a', 'fn-b'])
  assert.deepEqual(logic.filterRows(rows, { tone: 'off' }).map(r => r.title), ['fn-b'])
  assert.deepEqual(logic.filterRows(rows, { q: 'stopped' }).map(r => r.title), ['fn-b'])     // tag values are searched
  assert.deepEqual(logic.filterRows(rows, { group: 'CF', tags: { Kind: null } }).map(r => r.title), ['other'])
  const f = logic.tagFacets(rows, { tags: { Kind: 'Key Vault' } })
  assert.deepEqual(f.map(x => x.key), ['Kind', 'State'])                    // Region has one value: no chips
  assert.deepEqual(f[0].values, [['Function App', 2], ['Key Vault', 1]])     // Kind counted without its own choice
  assert.deepEqual(f[1].values, [['present', 1], ['running', 0], ['stopped', 0]])
})

test('chat: a chat of today shows its time, an older one day and time', () => {
  const now = new Date(2026, 9, 10, 16, 0).getTime()
  assert.equal(logic.chatStamp(new Date(2026, 9, 10, 9, 5).getTime(), now, 'de'), '09:05')
  assert.equal(logic.chatStamp(new Date(2026, 9, 9, 14, 30).getTime(), now, 'de'), '9.10. 14:30')
  assert.equal(logic.chatStamp(new Date(2026, 9, 9, 14, 30).getTime(), now, 'en'), '10/9 14:30')
  assert.equal(logic.chatStamp(undefined, now, 'de'), '')
})

test('chat: no canned prompt buttons, the answer streams in, the chat is a page of its own', () => {
  const comp = readComponents()
  const de = text.TABLES.de
  for (const k of ['btnSort', 'btnPlan', 'btnEvening']) assert.equal(de[k], undefined)
  assert.ok(!/c\.ask\('(overview|plan_day|evening)'/.test(comp))
  assert.match(comp, /export const CHAT_PAGE = '@chat'/)
  assert.match(fs.readFileSync(path.join(WEB, 'api.js'), 'utf8'), /'quick_live'/)
  assert.equal(de.claudeAnswered('x'), 'Claude hat geantwortet auf «x»')
})

test('logic: groupRows keeps the order of first appearance, ungrouped rows last', () => {
  const g = logic.groupRows([{ title: 'a', group: 'x' }, { title: 'b' }, { title: 'c', group: 'y' }, { title: 'd', group: 'x' }])
  assert.deepEqual(g.map(x => [x.key, x.rows.map(r => r.title)]), [['x', ['a', 'd']], ['y', ['c']], ['', ['b']]])
})

test('logic: weekdayNames comes from the platform, Monday first, without a trailing dot', () => {
  assert.equal(logic.weekdayNames('de')[0], 'Mo')
  assert.equal(logic.weekdayNames('de')[6], 'So')
  assert.equal(logic.weekdayNames('en')[0], 'Mon')
})

test('no component file calls a logic.js export it forgot to import', () => {
  for (const file of COMPONENT_FILES) {
    const src = read(file)
    const imported = (src.match(/import \{([^}]*)\} from '(?:\.\.?\/)+logic\.js'/)?.[1] ?? '').split(',').map(x => x.trim()).filter(Boolean)
    const own = new Set([...src.matchAll(/function (\w+)/g)].map(m => m[1]))
    const missing = Object.keys(logic).filter(n => typeof logic[n] === 'function' && !imported.includes(n) && !own.has(n)
      && new RegExp(`[^.\\w]${n}\\(`).test(src))
    assert.deepEqual(missing, [], file)
  }
})

test('the components stand in files of a readable size: a small root, one file per area', () => {
  assert.ok(VIEW_FILES.length >= 8, `views/: ${VIEW_FILES.length} files`)
  assert.ok(read(COMPONENT_FILES[0]).split('\n').length <= 300, 'components.js holds only the root and the page router')
  for (const file of VIEW_FILES) assert.ok(read(file).split('\n').length <= 800, `${file}: ${read(file).split('\n').length} lines`)
})

test('every component file imports what it uses from the other files: no name only one file knows', () => {
  // the names every component file can reach: the top level of each, and what each imports from elsewhere
  const DECL = /^(?:export )?(?:async )?(?:function\*? |const |let |class )([A-Za-z_$][\w$]*)/gm
  const importsOf = src => new Set([...src.matchAll(/^import \{([\s\S]*?)\} from/gm)]
    .flatMap(m => m[1].split(',').map(x => x.trim().split(/\s+as\s+/).pop()).filter(Boolean)))
  const known = new Set()
  for (const f of COMPONENT_FILES) {
    const src = read(f)
    for (const m of src.matchAll(DECL)) known.add(m[1])
    for (const n of importsOf(src)) known.add(n)
  }
  for (const f of COMPONENT_FILES) {
    const src = read(f)
    // comments and re-exports name what they do not use
    const code = src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '').replace(/ \/\/ .*$/gm, '')
      .replace(/^export \{[^}]*\} from '[^']+'/gm, '')
    const own = new Set([...src.matchAll(DECL)].map(m => m[1]))
    const reach = importsOf(src)
    // a name the file declares itself further in (a parameter, a local const) is its own, not the other file's
    const local = n => new RegExp(`(?:const|let|var|function)\\s+${n}\\b|(?:const|let|var)\\s*[{[][^=]*\\b${n}\\b`).test(code)
    const missing = [...known].filter(n => !own.has(n) && !reach.has(n) && !local(n)
      && new RegExp(`(?<![\\w$.])${n.replace(/\$/g, '\\$')}(?![\\w$])`).test(code))
    assert.deepEqual(missing, [], f)
  }
})

test('jev is optional: the page loads without scripts/web/jev/, no tab, no call, no import while off', async () => {
  // a copy of the page without the Jev folder, imported as ES modules under node
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'bridge-cockpit-nojev-'))
  try {
    fs.cpSync(WEB, path.join(dir, 'web'), { recursive: true, filter: src => !src.startsWith(path.join(WEB, 'jev')) })
    fs.writeFileSync(path.join(dir, 'web', 'package.json'), '{"type":"module"}')
    const comp = await import(pathToFileURL(path.join(dir, 'web', 'components.js')).href)
    const pages = { model: { pages: [{ id: 'x' }] } }
    // the daily tabs first, then what stands behind More (Sessions, Workers, Agents, Check, Jev, pages with group more)
    assert.deepEqual(comp.pageOrder({ ...pages, jev: { enabled: false } }), ['@start', 'briefing', '@chat', 'x', '@sessions', '@workers', '@check', '@settings'])
    assert.ok(!comp.pageOrder({ ...pages }).includes('@jev'))                       // no jev state at all: off
    assert.ok(comp.pageOrder({ ...pages, jev: { enabled: true, ready: false } }).includes('@jev'))
    // the demo mode runs without the Jev files too, and shows Jev as off
    const mock = await import(pathToFileURL(path.join(dir, 'web', 'mock.js')).href)
    assert.deepEqual(mock.buildState().jev, { enabled: false, ready: false, reason: 'off' })
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
  const comp = readComponents()
  assert.doesNotMatch(comp, /^import[^\n]*jev\//m)                                  // never a static import
  assert.match(comp, /useJevPage\(!!\(s\.jev\?\.enabled && s\.jev\?\.ready\)\)/)    // loaded only when on and ready
  assert.match(comp, /\$\{s\.jev\?\.enabled && !workPageOf\(s\.model\?\.pages\)\?\.jev \? tab\(JEV_PAGE/)   // the tab only when on, and not folded into the work tab
  assert.doesNotMatch(read('index.html'), /jev/)
  // the page asks /api/jev only through jevRun (the Jev page), jevRank (the order of a work page) and jevWork
  // (the Jev view of the work tab, the order of its work page)
  const app = read('app.js')
  assert.equal((app.match(/\/api\/jev/g) ?? []).length, 3)
  assert.match(app, /jevWork: async[^\n]*\n\s*const res = await api\.post\('\/api\/jev\/rank', \{ page, force: !!force, daily: !force \}\)/)
  assert.match(app, /jevRun: \([^)]*\) => api\.post\('\/api\/jev\/run'/)
  assert.match(app, /const res = await api\.post\('\/api\/jev\/rank'/)
  // the order strip stands only where Jev is on and ready, and only it calls jevRank
  assert.match(comp, /page\.jev && !work && s\.jev\?\.enabled && s\.jev\?\.ready \? html`<\$\{WorkOrder\}/)
  assert.equal((comp.match(/\.jevRank\(/g) ?? []).length, 2)
  for (const name of ['app.js', 'components.js', 'api.js', 'logic.js', 'mock.js']) {
    assert.doesNotMatch(read(name).replace(/jevRun: \([^)]*\) => api\.post/, ''), /\.jevRun\(/, name)
  }
})

test('agents: the Agents tab only where the Bridge knows a peer, and a message only through agentSend', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'bridge-cockpit-agents-'))
  try {
    fs.cpSync(WEB, path.join(dir, 'web'), { recursive: true })
    fs.writeFileSync(path.join(dir, 'web', 'package.json'), '{"type":"module"}')
    const comp = await import(pathToFileURL(path.join(dir, 'web', 'components.js')).href)
    assert.ok(!comp.pageOrder({ agents: { peers: [] } }).includes('@agents'))
    assert.ok(!comp.pageOrder({}).includes('@agents'))
    assert.deepEqual(comp.pageOrder({ agents: { peers: [{ id: 'a' }] } }).slice(3, 6), ['@sessions', '@workers', '@agents'])
    assert.ok(comp.morePages({ agents: { peers: [{ id: 'a' }] } }).has('@agents'))
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
  // nothing sends on its own: a2a_ask appears once in app.js, inside agentSend, called only from the send box
  const app = read('app.js')
  assert.equal((app.match(/'a2a_ask'/g) ?? []).length, 1)
  assert.match(app, /agentSend: async \(peer, text, mode, conv\) => \{\n\s+const r = await act\('a2a_ask'/)
  assert.equal((readComponents().match(/c\.agentSend\(/g) ?? []).length, 1)
})

test('agents: a conversation is removed only on a second click and the page goes back to a new chat', () => {
  const app = read('app.js')
  assert.match(app, /agentForget: async conv => \{\n\s+const r = await act\('a2a_forget', \{ conv \}\)/)
  assert.match(app, /agentForget[\s\S]{0,200}agentConv: ui\.agentConv === conv \? null/)
  const page = readComponents().match(/function AgentsPage\(\{ s, c(?:, embedded = false)? \}\) \{[\s\S]*?\n\}/)[0]
  // the first click only arms the button, the second removes
  assert.match(page, /forgetArmed === conv\.id \? c\.agentForget\(conv\.id\) : setForgetArmed\(conv\.id\)/)
  assert.equal((read('text.js').match(/agentForgetSure:/g) ?? []).length, 2)
})

test('agents: a draft never travels to another agent, held answers show on the card', () => {
  const src = readComponents()
  const page = src.match(/function AgentsPage\(\{ s, c(?:, embedded = false)? \}\) \{[\s\S]*?\n\}/)[0]
  assert.match(page, /useEffect\(\(\) => \{[^}]*setText\(''\)[^}]*\}, \[peer\?\.id\]\)/)
  assert.match(page, /held=\$\{convs\.filter\(x => x\.peer === p\.id && !x\.running && x\.turns\.at\(-1\)\?\.waiting\)\.length\}/)
})

test('history: a close offers undo at once and later; a task comes back open or as still to be done', () => {
  const app = read('app.js')
  const comp = readComponents()
  assert.match(app, /if \(r\.undo\?\.length && r\.ok\) \{\s*pushNote\(\{[^}]*action: 'undo', undo: r\.undo \}/)
  // the toast restores the status the task had before the close (#384); older entries fall back to doing
  assert.match(app, /undo: async \(u, as = u\.args\?\.as \?\? 'doing'\) =>/)
  // the server's own note of the same text is often first: the undo must still reach the toast
  assert.match(app, /const twin = note\.action && s\.toasts\.find\(t => t\.text === note\.text && !t\.action\)/)
  const buttons = comp.match(/function UndoButtons\([\s\S]*?\n\}/)[0]
  assert.match(buttons, /c\.undo\(u, 'doing'\)/)
  assert.match(buttons, /c\.undo\(u, 'backlog'\)/)
  assert.match(comp, /s\.ui\.drawer === 'history' \? html`<\$\{HistoryDrawer\}/)
})

test('triage: a row finds its sorting by task or inbox id, filters count what each would show', () => {
  const map = { 'task:a': { verdict: 'close', doer: 'ai', effort: 'small' }, 'task:b': { verdict: 'continue', doer: 'you' },
    'inbox:x': { verdict: 'unclear', doer: 'either', effort: 'large' } }
  const rows = [{ task: 'a' }, { task: 'b' }, { inbox: 'x' }, { task: 'unsorted' }, { title: 'no key' }]
  assert.equal(logic.triageKey(rows[2]), 'inbox:x')
  assert.equal(logic.triageKey(rows[4]), null)
  // an inbox item that belongs to a task is sorted as the item, not as its task
  assert.equal(logic.triageKey({ inbox: 'x', task: 'a' }), 'inbox:x')
  assert.deepEqual(logic.triageCounts(rows, map), { all: 5, close: 1, ai: 1, you: 1, unclear: 2 })
  // a row that is neither task nor inbox item is never filtered away
  assert.deepEqual(rows.filter(r => logic.triageShows(r, map, 'unclear')).map(r => r.task ?? r.inbox ?? r.title),
    ['x', 'unsorted', 'no key'])
  assert.deepEqual(rows.filter(r => logic.triageShows(r, map, 'ai')).map(r => r.task ?? r.inbox ?? r.title), ['a', 'no key'])
  assert.equal(rows.every(r => logic.triageShows(r, map, 'all')), true)
  assert.deepEqual([logic.effortDots('small'), logic.effortDots('large'), logic.effortDots(null)], [1, 3, 0])
})

test('logic: a page item acts through the briefing row, else through one made from the item', () => {
  const own = { key: 'inbox:a', settle: ['done'] }
  const byKey = new Map([['inbox:a', own]])
  assert.equal(logic.actionRow({ inbox: 'a', title: 'x' }, byKey), own)
  assert.deepEqual(logic.actionRow({ inbox: 'b', title: 'y' }, byKey), { key: 'inbox:b', title: 'y', inbox_id: 'b', settle: ['done', 'not_doing'], runs: false })
  // an item that runs on (its lines name the day to look again) can open again
  assert.equal(logic.actionRow({ inbox: 'c', title: 'w', lines: [{ kind: 'look', text: '2026-10-19' }] }, byKey).runs, true)
  assert.equal(logic.taskLane({ state: 'review' }), 'review')
  assert.equal(logic.taskLane({ state: 'doing', lines: [{ kind: 'blocked', text: 'Ada' }] }), 'runs')
  assert.equal(logic.taskLane({ state: 'backlog' }), 'next')
  assert.equal(logic.taskLane({ state: 'doing' }), 'now')
  assert.equal(logic.actionRow({ task: 't', title: 'z' }, byKey).key, 'task:t')
  assert.equal(logic.actionRow({ title: 'none' }, byKey), null)
})

test('a command row with its own steps shows them as a two-click menu that acts through row_action', () => {
  const src = readComponents()
  const steps = src.match(/function RowSteps\(\{[\s\S]*?\n\}/)[0]
  assert.match(steps, /c\.act\('row_action', \{ page, section, index: it\.index, action \}\)/)
  assert.match(src, /it\.actions\?\.length && it\.row_id \? html`<\$\{RowSteps\}/)
})

test('GitHub work: an issue of yours no task tracks carries a chip and a figure that filters, in both languages', () => {
  for (const t of Object.values(text.TABLES)) {
    assert.ok(t.gh.figure.untasked && t.gh.figureTitle.untasked({ n: 2 }), 'figure label and title')
    assert.ok(t.gh.untaskedChip && t.gh.untaskedChipTitle, 'chip text and title')
  }
  const gh = read('views/github.js')
  assert.match(gh, /const LOUD = \{[^}]*\buntasked: '[a-z-]+'/)          // a reason to look: loud when not zero
  assert.match(gh, /g\.untasked \? html`<span class="ghl-chip ghl-chip-untasked" title=\$\{t\.gh\.untaskedChipTitle\}>\$\{t\.gh\.untaskedChip\}/)
  assert.match(read('style.css'), /\.ghl-chip-untasked \{[^}]*var\(--/)
  // the demo shows one: a row flagged untasked and a figure that counts it
  const mock = read('mock.js')
  assert.match(mock, /\{ id: 'untasked', n: 1 \}/)
  assert.match(mock, /flags: \[[^\]]*'untasked'[^\]]*\][\s\S]*?gh: \{[^\n]*untasked: true/)
  // and offers Make it a task there, as the server does; a row whose issue a task syncs does not
  assert.match(mock, /untasked: true[^\n]*\n\s*row_id: [^\n]*\{ id: 'adopt'/)
  assert.doesNotMatch(mock, /task: 'demo-task'[^\n]*\n\s*row_id: [^\n]*\{ id: 'adopt'/)
})

test('logic: the item drawer turns URLs in a detail into links, http and https only', () => {
  const parts = logic.linkParts('see https://example.org/a?b=1, then javascript:alert(1) and http://example.org/c.')
  assert.deepEqual(parts, [{ text: 'see ' }, { href: 'https://example.org/a?b=1', text: 'https://example.org/a?b=1' },
    { text: ', then javascript:alert(1) and ' }, { href: 'http://example.org/c', text: 'http://example.org/c' }, { text: '.' }])
  assert.deepEqual(logic.linkParts(''), [])
  assert.deepEqual(logic.linkParts(null), [])
})

test('logic: how an inbox item closes, in words, and its events newest first', () => {
  for (const t of Object.values(text.TABLES)) {
    const said = logic.probeText({ any: [{ gh_pr: 'org/repo#7', state: 'merged' }, { after: '2026-10-20' }] }, t)
    assert.match(said, /org\/repo#7/)
    assert.match(said, /20\.10\.2026|2026-10-20/)
    assert.ok(said.includes(t.probe.or), said)
    assert.match(logic.probeText({ all: [{ path_exists: 'a.md' }, { task_status: 'x', status: 'done' }] }, t), /a\.md[\s\S]*x/)
    assert.match(logic.probeText({ command: ['make', 'check'] }, t), /make check/)
    assert.match(logic.probeText({ gh_issue: 'o/r#3' }, t), /o\/r#3/)
    assert.match(logic.probeText({ unseen_for: { hours: 24 } }, t), /24/)
    assert.equal(logic.probeText(null, t), null)
    assert.equal(typeof logic.probeText({ weird: 1 }, t), 'string')
  }
  const ev = [{ at: '2026-10-09T09:11', verb: 'seen' }, { at: '2026-10-10T08:00', verb: 'note' }, { at: null, verb: 'x' }]
  assert.deepEqual(logic.newestFirst(ev).map(e => e.verb), ['note', 'seen', 'x'])
  assert.equal(ev[0].verb, 'seen')                                     // the input stays as it was
})

test('inbox and task rows open the item drawer on a click or Enter, never from a button inside the row', () => {
  const src = readComponents()
  const row = src.match(/function InfoRow\(\{[\s\S]*?\n\}/)[0]
  assert.match(row, /c\.openItem\(/)
  assert.match(row, /rowClickOpens\(e\)/)
  assert.match(row, /e\.key === 'Enter'/)
  assert.match(src, /function rowClickOpens\(e\) \{[\s\S]*?closest\('button, a, input, select, textarea, summary, label, \[role=menu\], \[role=menuitem\]'\)/)
  // the drawer reads only, through the two detail endpoints, and nothing in it starts a timer
  const drawer = src.match(/function ItemDrawer\(\{[\s\S]*?\n\}/)[0]
  assert.doesNotMatch(drawer, /setInterval|setTimeout/)
  assert.match(src, /s\.ui\.drawer === 'item' && s\.ui\.item \? html`<\$\{ItemDrawer\}/)
  const app = read('app.js')
  assert.match(app, /openItem\(/)
  assert.match(app, /closeItem\(/)
})

test('the page bar keeps the daily tabs in front and the rest behind More, in the order Alt counts', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'bridge-cockpit-more-'))
  try {
    fs.cpSync(WEB, path.join(dir, 'web'), { recursive: true })
    fs.writeFileSync(path.join(dir, 'web', 'package.json'), '{"type":"module"}')
    const comp = await import(pathToFileURL(path.join(dir, 'web', 'components.js')).href)
    const s = { model: { pages: [{ id: 'inbox' }, { id: 'llm', group: 'more' }, { id: 'tasks', group: 'main' }, { id: 'today', group: 'day' }] } }
    assert.deepEqual(comp.pageOrder(s), ['@start', 'briefing', '@chat', 'inbox', 'tasks', '@sessions', '@workers', '@check', 'llm', '@settings'])
    assert.deepEqual([...comp.morePages(s)], ['@sessions', '@workers', '@check', 'llm', '@settings'])
    // a page of group day has no tab: its sections stand under the day list of Today
    assert.ok(!comp.pageOrder(s).includes('today'))
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
  const comp = readComponents()
  // a tab's tooltip names the tab and its key, never the key alone
  assert.doesNotMatch(comp, /title=\$\{i >= 0 && i < 9 \? `Alt \$\{i \+ 1\}`/)
})

test('the day column: waiting tabs stand in the left column only where no tab column stands beside it', () => {
  const day = readComponents().match(/function DayColumn\([\s\S]*?\n\}/)[0]
  assert.match(day, /s\.layout === 'wide' \? null : html`<\$\{WaitingTabs\}/)
})

test('the chat decides per message: ask (read only) or solve it in a real Claude tab in cmux', () => {
  const foot = readComponents().match(/function ChatFoot\([\s\S]*?\n\}/)[0]
  assert.match(foot, /c\.act\('chat_tab', \{ text: v \}\)/)                         // a new problem opens a tab at once
  // a chat goes on in a tab; an empty box adds no order (the server refused an empty text, the click came to nothing)
  assert.match(foot, /c\.act\('quick_handoff', \{ conv: conv\.id, to: 'tab', \.\.\.\(v \? \{ text: v \} : \{\}\) \}\)/)
  const box = readComponents().match(/function SendBox\([\s\S]*?\n\}/)[0]
  assert.match(box, /e\.metaKey \|\| e\.ctrlKey/)                                   // Cmd or Ctrl Enter takes the second way
  for (const lang of ['en', 'de']) {
    const t = text.TABLES[lang]
    for (const k of ['chatAsk', 'chatSolve', 'chatSolveTitle', 'chatSolveHint']) assert.ok(t[k], `${lang} ${k}`)
  }
})

test('every card and row of a page opens its details: tables, resource tiles, gauges, grouped rows', () => {
  const comp = readComponents()
  const app = read('app.js')
  assert.match(app, /openInfo\(it, page, section\) \{/)
  assert.match(comp, /s\.ui\.drawer === 'info' && s\.ui\.info \? html`<\$\{InfoDrawer\}/)
  for (const name of ['InfoRow', 'ResTile', 'GaugeTile', 'GroupsView']) {
    const body = comp.match(new RegExp(`function ${name}\\([\\s\\S]*?\\n\\}`))[0]
    assert.match(body, /c\.openInfo\(/, name)
  }
  const drawer = comp.match(/function InfoDrawer\([\s\S]*?\n\}/)[0]
  for (const part of ['RowSteps', 'StatusMenu', "c.ask('info'", 'Lines', 'MeterBar']) assert.ok(drawer.includes(part), part)
})

test('a worker schedule reads as words, not as RRULE or seconds', async () => {
  const logic = await import(pathToFileURL(path.join(WEB, 'logic.js')).href)
  const de = s => logic.scheduleText(s, 'de')
  assert.equal(de('every 300s'), 'alle 5 min')
  assert.equal(de('every 45s'), 'alle 45 s')
  assert.equal(de('every 7200s'), 'alle 2 h')
  assert.equal(de('continuous'), 'läuft dauernd')
  assert.equal(de('FREQ=DAILY at 07:00; FREQ=DAILY at 12:30'), 'täglich 07:00, 12:30')
  assert.equal(de('FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR at 08:00'), 'Mo bis Fr 08:00')
  assert.equal(de('FREQ=WEEKLY;BYDAY=SU at 10:00'), 'So 10:00')
  assert.equal(de('FREQ=WEEKLY;BYDAY=MO,WE at 09:00'), 'Mo, Mi 09:00')
  assert.equal(de('2 path(s) watched'), 'beobachtet 2 Pfade')
  assert.equal(de('something new'), 'something new')
  assert.equal(logic.scheduleText('every 300s', 'en'), 'every 5 min')
  assert.equal(logic.scheduleText('FREQ=DAILY at 07:00', 'en'), 'daily 07:00')
})

test('a worker day note reads as words, the last run in local time', async () => {
  const logic = await import(pathToFileURL(path.join(WEB, 'logic.js')).href)
  const de = s => logic.dayNoteText(s, 'de')
  assert.equal(de('nothing says this schedule is behind'), 'im Takt')
  assert.equal(de('nothing says this schedule is behind; last run 08:00 local (2026-10-12T06:00:04Z)'), 'im Takt · zuletzt 08:00')
  const iso = '2026-10-13T04:34:59Z'
  const local = new Date(iso).toLocaleTimeString('de', { hour: '2-digit', minute: '2-digit' })
  assert.equal(de(`last run ${iso}, not placed on the axis: the declaration states no time zone, and the stamp is UTC`), `zuletzt ${local}`)
  assert.equal(de('nothing here can judge this schedule'), 'Takt nicht prüfbar')
  assert.equal(de('fires when a path changes, so it has no place on a clock'), 'reagiert auf Dateiänderungen')
  assert.equal(de(''), '')
})

test('a row detail line names kind and gate in words, never the machine value', async () => {
  const logic = await import(pathToFileURL(path.join(WEB, 'logic.js')).href)
  const t = text.TABLES.de
  assert.equal(logic.detailText('finding · your-yes', t), 'Befund · braucht dein Ja')
  assert.equal(logic.detailText('question · free', t), 'Frage · darf allein')
  assert.equal(logic.detailText('P1 · Bridge', t), 'P1 · Bridge')
  assert.equal(logic.detailText('', t), '')
})

test('the status list: a failed source is loud with its reason, a skipped one waits for the full pass, a count is no alarm', async () => {
  const logic = await import(pathToFileURL(path.join(WEB, 'logic.js')).href)
  const rows = [
    { title: 'quiet', count: 0, probe: false, state: 'ok' },
    { title: 'broken', count: 0, probe: false, state: 'error', reason: 'boom' },
    { title: 'later', count: 0, probe: false, state: 'skipped' },
    { title: 'probe', count: 2, probe: true, state: 'ok' },
    { title: 'counted', count: 5, probe: false, state: 'ok' },
  ]
  const { loud, quiet } = logic.statusSplit(rows)
  assert.deepEqual(loud.map(x => [x.title, x.tone]), [['broken', 'danger'], ['probe', 'warning'], ['counted', 'info']])
  assert.deepEqual(quiet.map(x => [x.title, x.tone]), [['quiet', 'success'], ['later', 'neutral']])
})

test('the briefing headline counts what the Briefing tab counts, the header does not repeat it', () => {
  const comp = readComponents()
  const header = comp.match(/function Header\([\s\S]*?\n\}/)[0]
  assert.doesNotMatch(header, /m\?\.headline/)
  const ov = comp.match(/function Overview\([\s\S]*?\n\}/)[0]
  assert.match(ov, /t\.forYouNow\(m\.briefing_badge/)
  assert.match(ov, /m\.headline_rest/)
})

test('the agent tab column stands only where work is handed to the AI: the work tab and the chat', async () => {
  const logic = await import(pathToFileURL(path.join(WEB, 'logic.js')).href)
  for (const p of ['@start', '@sessions', '@workers', '@check', '@agents', 'calendar', 'github', 'ops', undefined])
    assert.equal(logic.railShown(p), false, String(p))
  for (const p of ['briefing', '@chat']) assert.equal(logic.railShown(p), true, p)
  assert.equal(logic.railShown('@chat', 'workspaces'), false)          // the chat as cmux holds the tabs itself
  assert.equal(logic.railShown('briefing', 'workspaces'), true)
  // hidden by the person it stands nowhere, the header's Tabs button takes over
  for (const p of ['briefing', '@chat']) assert.equal(logic.railShown(p, 'classic', true), false, p)
})

test('a slim tab card offers one next step: answer, go on, close, else go to the tab', async () => {
  const logic = await import(pathToFileURL(path.join(WEB, 'logic.js')).href)
  const all = () => true
  assert.deepEqual(logic.tabNextStep({ state: 'needs-you' }, all), ['yes', 'no'])
  assert.deepEqual(logic.tabNextStep({ state: 'waiting' }, all), ['go_on'])
  assert.deepEqual(logic.tabNextStep({ state: 'waiting', filed_by: 'x' }, all), ['close'])
  assert.deepEqual(logic.tabNextStep({ state: 'working' }, all), ['jump'])
  assert.deepEqual(logic.tabNextStep({ state: 'waiting', is_control: true }, all), ['jump'])
  // without the rights for a step the card falls back to viewing the screen, and with none to nothing
  assert.deepEqual(logic.tabNextStep({ state: 'needs-you' }, k => k === 'screen'), ['view'])
  assert.deepEqual(logic.tabNextStep({ state: 'working' }, () => false), [])
})

test('the agent tab column shows slim cards that open to every control', () => {
  const comp = readComponents()
  assert.match(comp.match(/function TabCard\([\s\S]*?\n\}/)[0], /tab\.settled/)
  const col = comp.match(/function TabsColumn\([\s\S]*?\n\}/)[0]
  assert.match(col, /<\$\{TabCard\}[^>]*slim/)
  const card = comp.match(/function TabCard\([\s\S]*?\n\}/)[0]
  assert.match(card, /aria-expanded/)
  // the buttons of the slim TabControls are rendered in bridge_cockpit_render.test.mjs
})

test('a tab preview is plain text: no code fences, no runs of blanks', async () => {
  const logic = await import(pathToFileURL(path.join(WEB, 'logic.js')).href)
  assert.equal(logic.previewText('``` 2 for you today\n\n  free'), '2 for you today free')
  assert.equal(logic.previewText('❯ ─── ok'), 'ok')
})

test('small words: today instead of 0 days, one step in the singular', () => {
  const de = text.TABLES.de
  assert.equal(de.rvDays(0), 'heute')
  assert.equal(de.rvDays(1), '1 Tag')
  assert.equal(de.rvDays(4), '4 Tage')
  assert.equal(de.chip({ kind: 'steps', count: 1 }), '1 Schritt offen')
  assert.equal(de.chip({ kind: 'steps', count: 3 }), '3 Schritte offen')
})

test('token counts read short: thousands and millions in the page language', async () => {
  const logic = await import(pathToFileURL(path.join(WEB, 'logic.js')).href)
  assert.equal(logic.tokenText(0, 'de'), '0')
  assert.equal(logic.tokenText(950, 'de'), '950')
  assert.equal(logic.tokenText(340_400, 'de'), '340 Tsd.')
  assert.equal(logic.tokenText(1_234_567, 'de'), '1,2 Mio.')
  assert.equal(logic.tokenText(1_234_567, 'en'), '1.2M')
  assert.equal(logic.tokenText(12_000, 'en'), '12k')
  assert.equal(logic.tokenText(1_564_000_000, 'de'), '1,6 Mrd.')
  assert.equal(logic.tokenText(1_564_000_000, 'en'), '1.6B')
  assert.equal(logic.tokenText(51_200_000, 'de'), '51 Mio.')
})

test('an overview tile sums up its section: count, the loudest tone, the first loud row, a peak gauge', async () => {
  const logic = await import(pathToFileURL(path.join(WEB, 'logic.js')).href)
  const quiet = logic.sectionTile({ id: 'm', title: 'Maschinen', count: 3, total: 22, items: [{ title: 'a' }, { title: 'b', tone: 'dim' }] })
  assert.deepEqual(quiet, { count: 22, loud: 0, tone: 'neutral', note: null, peak: null, counts: null, state: 'ok' })
  const probes = logic.sectionTile({ id: 'p', alarm: true, count: 2, items: [{ title: 'Karte weg', tone: 'bad' }, { title: 'x', tone: 'warn' }] })
  assert.equal(probes.tone, 'danger')
  assert.equal(probes.loud, 2)
  assert.equal(probes.note, 'Karte weg')
  assert.equal(logic.sectionTile({ id: 'p', alarm: true, count: 0, items: [] }).tone, 'success')
  // a gauge row carries its value in the title too ("Woche: 17 %"); the tile names the gauge once
  const gauges = logic.sectionTile({ id: 'g', count: 2, items: [{ title: 'Woche: 17 %', meter: { value: 17, max: 100, warn: 80, bad: 95 } },
    { title: 'Sitzung', meter: { value: 3, max: 100, warn: 80, bad: 95 } }] })
  assert.deepEqual(gauges.peak, { title: 'Woche', percent: 17 })
  assert.equal(gauges.tone, 'success')
  const high = logic.sectionTile({ id: 'g', count: 1, items: [{ title: 'Woche', meter: { value: 85, max: 100, warn: 80, bad: 95 } }] })
  assert.equal(high.tone, 'warning')
  // a gauge without limits is a count (workers fine, machines online): no peak, higher is not worse
  const plain = logic.sectionTile({ id: 'o', count: 2, items: [{ title: 'Worker', meter: { value: 63, max: 90 } }, { title: 'Online', meter: { value: 1, max: 1 } }] })
  assert.equal(plain.peak, null)
  assert.deepEqual(plain.counts, [{ title: 'Worker', value: 63, max: 90 }, { title: 'Online', value: 1, max: 1 }])
  assert.equal(plain.tone, 'neutral')
  assert.equal(logic.sectionTile({ id: 'e', status: 'error', reason: 'x', items: [] }).state, 'error')
  assert.equal(logic.sectionTile({ id: 'e', status: 'error', reason: 'x', items: [] }).tone, 'danger')
  assert.equal(logic.sectionTile({ id: 's', status: 'skipped', items: [] }).state, 'skipped')
})

test('the week of tokens as bars: each day split by source, scaled to the largest day', async () => {
  const logic = await import(pathToFileURL(path.join(WEB, 'logic.js')).href)
  const src = (session, subagent, worker) => ({ session: { output: session }, subagent: { output: subagent }, worker: { output: worker } })
  const usage = { days: [{ day: '2026-10-12', output: 300, sources: src(200, 100, 0) }, { day: '2026-10-13', output: 150, sources: src(0, 0, 150) }] }
  const bars = logic.usageBars(usage)
  assert.equal(bars.max, 300)
  assert.deepEqual(bars.days[0].parts, [{ source: 'session', value: 200, frac: 200 / 300 }, { source: 'subagent', value: 100, frac: 100 / 300 }])
  assert.deepEqual(bars.days[1].parts, [{ source: 'worker', value: 150, frac: 0.5 }])
  // today against the usual day: the mean of the earlier days that had any use
  assert.deepEqual(logic.usageToday(usage), { today: 150, usual: 300 })
  assert.deepEqual(logic.usageToday({ days: [] }), { today: 0, usual: null })
})

test('the Betrieb words exist in both languages', () => {
  for (const lang of ['de', 'en']) {
    const t = text.TABLES[lang]
    for (const k of ['usageTitle', 'usageWhere', 'usageSource', 'usageOutlier', 'usageUsual', 'usageLoading', 'usageNone',
      'usageModels', 'usageProjects', 'usageInput', 'overviewWorkers', 'workersOnHost', 'workersOpen']) {
      assert.ok(t[k], `${lang}.${k}`)
    }
  }
})

test('a work page in the order of Jev: ranked rows first, each with its label, the rest after it', async () => {
  const logic = await import(pathToFileURL(path.join(WEB, 'logic.js')).href)
  const kinds = { inbox: 'Posteingang', tasks: 'Aufgabe', workplace: 'Arbeitsplatz' }
  const sections = [
    { id: 'inbox', kind: 'inbox', title: 'Wartet auf dich', items: [{ index: 0, title: 'A', inbox: 'a' }, { index: 1, title: 'B', inbox: 'b' }] },
    { id: 'ideen', kind: 'inbox', title: 'Ideen (Telegram fragt)', items: [{ index: 0, title: 'I', inbox: 'i' }] },
    { id: 'tasks', kind: 'tasks', title: 'Aufgaben', items: [{ index: 0, title: 'T', task: 't' }] },
    { id: 'bewerbungen', kind: 'command', title: 'Bewerbungen', items: [{ index: 0, title: 'Firma' }] },
    { id: 'workplace', kind: 'workplace', title: 'Arbeitsplatz heute', items: [{ index: 0, title: 'T', task: 't' }] },
  ]
  assert.equal(logic.workLabel(sections[0], kinds), 'Posteingang')
  assert.equal(logic.workLabel(sections[1], kinds), 'Ideen')
  assert.equal(logic.workLabel(sections[3], kinds), 'Bewerbungen')
  const order = { items: [{ key: 'task:t', rank: 1, urgency: 1, impact: 0.667, effort: 0.333, only_me: 0.9 }, { key: 'inbox:b', rank: 2 }] }
  const list = logic.jevList(sections, order, kinds)
  assert.deepEqual(list.ranked.map(r => [r.it.title, r.section, r.label, r.rank]), [['T', 'tasks', 'Aufgabe', 1], ['B', 'inbox', 'Posteingang', 2]])
  assert.deepEqual(list.ranked[0].judge, { urgency: 3, impact: 2, effort: 1, onlyMe: true })
  // the rest keeps the page order; a row standing in two sections (workplace and tasks) shows once
  assert.deepEqual(list.rest.map(r => [r.it.title, r.label]), [['A', 'Posteingang'], ['I', 'Ideen'], ['Firma', 'Bewerbungen']])
  assert.deepEqual(logic.jevList(sections, null, kinds).ranked, [])
})

test('a page of group work folds into the work tab, and with it the Jev tab', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'bridge-cockpit-work-'))
  try {
    fs.cpSync(WEB, path.join(dir, 'web'), { recursive: true })
    fs.writeFileSync(path.join(dir, 'web', 'package.json'), '{"type":"module"}')
    const comp = await import(pathToFileURL(path.join(dir, 'web', 'components.js')).href)
    const pages = [{ id: 'work', title: 'Work', group: 'work', jev: true }, { id: 'ops' }]
    const s = { model: { pages }, jev: { enabled: true, ready: true } }
    // no tab for the work page and none for Jev: both are views of the one work tab
    assert.deepEqual(comp.pageOrder(s), ['@start', 'briefing', '@chat', 'ops', '@sessions', '@workers', '@check', '@settings'])
    // without a work page the Jev tab stays where it was
    assert.ok(comp.pageOrder({ model: { pages: [{ id: 'ops' }] }, jev: { enabled: true } }).includes('@jev'))
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
})

test('the work tab opens on what is due and switches to by source and by Jev', () => {
  const work = { id: 'work', group: 'work', jev: true }
  assert.equal(logic.workPageOf([{ id: 'ops' }, work]), work)
  assert.equal(logic.workPageOf([{ id: 'ops' }]), null)
  const ready = { enabled: true, ready: true }
  assert.deepEqual(logic.workViews(work, ready), ['due', 'area', 'jev'])
  assert.deepEqual(logic.workViews(work, { enabled: false }), ['due', 'area'])
  assert.deepEqual(logic.workViews({ ...work, jev: false }, ready), ['due', 'area'])
  assert.deepEqual(logic.workViews(null, ready), ['due'])
  // a remembered view the tab cannot show falls back to what is due, the default
  assert.equal(logic.workViewOf('jev', work, ready), 'jev')
  assert.equal(logic.workViewOf('jev', work, { enabled: false }), 'due')
  assert.equal(logic.workViewOf('area', null, ready), 'due')
  assert.equal(logic.workViewOf(undefined, work, ready), 'due')
})

test('with a work tab the day view stands on Start, the middle of Due only points there', () => {
  const comp = readComponents()
  // one component holds the day: dates, status, clear and hygiene, the workplace, the pages of group day
  const day = comp.slice(comp.indexOf('function DayView('), comp.indexOf('function StatusList('))
  assert.match(day, /m\.agenda/)
  assert.match(day, /<\$\{StatusList\} rows=\$\{m\.status\}/)
  assert.match(day, /p\.group === 'day'/)
  // Start shows it where a work page exists, as a shelf of its own, in both start page styles
  const home = comp.slice(comp.indexOf('function HomePage('), comp.indexOf('function HomePage(') + 9000)
  assert.equal((home.match(/\$\{daily\}/g) ?? []).length, 2)
  assert.match(home, /const daily = workPageOf\(s\.model\?\.pages\) \? html`<\$\{HomeShelf\} id="home-day" title=\$\{h\.dayTitle\}/)
  // there it looks like the other shelves: one card per block; on the stage above the project chips, which do not filter it
  const cards = day.slice(day.indexOf('if (cards)'), day.indexOf('const [agenda, status'))
  assert.match(cards, /class=\$\{`hcard day-card day-\$\{b\.id\}`\}/)
  assert.match(home, /\$\{daily\}\s*\$\{chips\}/)
  // what happened today is long and read last: on Start a shelf of its own at the end, not one of the day cards
  assert.doesNotMatch(cards, /DayPages/)
  assert.match(day.slice(day.indexOf('const [agenda, status')), /<\$\{DayPages\} s=\$\{s\} c=\$\{c\} \/>/)
  assert.equal((home.match(/\$\{shelves\}\s*\$\{diary\}/g) ?? []).length, 2)
  // the shelf does not repeat the title of the card on the stage
  assert.notEqual(text.TABLES.de.home.dayTitle, text.TABLES.de.overviewTitle)
  assert.ok(text.TABLES.en.home.dayTitle)
  // the middle of Due keeps only the headline and a way to Start there; without a work page it stays whole
  const ov = comp.slice(comp.indexOf('function Overview('), comp.indexOf('function DayView('))
  assert.match(ov, /if \(workPageOf\(m\.pages\)\)/)
  assert.match(ov, /c\.setPage\(START_PAGE\)/)
  assert.match(ov, /<\$\{DayView\} s=\$\{s\} c=\$\{c\} \/>/)
  // its words exist in both languages
  assert.equal((read('text.js').match(/^  dayOnStart(Open)?: '/gm) ?? []).length, 4)
})

test('the words of the Jev order exist in both languages', () => {
  for (const lang of ['de', 'en']) {
    const t = text.TABLES[lang]
    assert.ok(t.workOrder, `${lang}.workOrder`)
    for (const k of ['label', 'byArea', 'byJev', 'run', 'rerun', 'running', 'never', 'last', 'left', 'rest', 'what', 'judge', 'kinds', 'failed']) {
      assert.ok(t.workOrder[k], `${lang}.workOrder.${k}`)
    }
  }
})

test('a page with inbox and task rows filters by kind: one chip per label with its count, empty ones left out', async () => {
  const logic = await import(pathToFileURL(path.join(WEB, 'logic.js')).href)
  const kinds = { inbox: 'Posteingang', tasks: 'Aufgabe', workplace: 'Arbeitsplatz' }
  const sections = [
    { id: 'inbox', kind: 'inbox', title: 'Wartet auf dich', total: 37, items: [{ inbox: 'a' }] },
    { id: 'ideen', kind: 'inbox', title: 'Ideen (Telegram)', total: 1, items: [{ inbox: 'i' }] },
    { id: 'debrief', kind: 'command', title: 'Offene Debrief-Punkte', total: 0, items: [] },
    { id: 'tasks', kind: 'tasks', title: 'Aufgaben', total: 9, items: [{ task: 't' }] },
  ]
  assert.deepEqual(logic.workKinds(sections, kinds), [
    { label: 'Posteingang', n: 37, sections: ['inbox'] }, { label: 'Ideen', n: 1, sections: ['ideen'] },
    { label: 'Aufgabe', n: 9, sections: ['tasks'] }])
  // only where inbox and task rows stand together
  assert.deepEqual(logic.workKinds(sections.slice(0, 2), kinds), [])
})

test('the task check lives on the page where inbox and tasks stand together, under the tasks label', async () => {
  const logic = await import(pathToFileURL(path.join(WEB, 'logic.js')).href)
  const kinds = { inbox: 'Posteingang', tasks: 'Aufgabe' }
  const work = { id: 'arbeit', sections: [{ id: 'inbox', kind: 'inbox', total: 3 }, { id: 'tasks', kind: 'tasks', total: 2 }] }
  const apart = [{ id: 'inbox', sections: [{ id: 'inbox', kind: 'inbox', total: 3 }] }, { id: 'tasks', sections: [{ id: 'tasks', kind: 'tasks', total: 2 }] }]
  assert.deepEqual(logic.reviewHome([{ id: 'x', sections: [] }, work], kinds), { page: 'arbeit', label: 'Aufgabe' })
  assert.equal(logic.reviewHome(apart, kinds), null)      // apart, the check keeps its own tab
  assert.equal(logic.reviewHome(undefined, kinds), null)
})

test('a tab offers only what the terminal driver serves; before the driver answered, everything shows', async () => {
  const logic = await import(pathToFileURL(path.join(WEB, 'logic.js')).href)
  assert.equal(logic.canTab({ driver: { caps: null } }, 'key'), true)
  assert.equal(logic.canTab({}, 'focus'), true)
  assert.equal(logic.canTab({ driver: { caps: ['tabs', 'send', 'focus'] } }, 'focus'), true)
  assert.equal(logic.canTab({ driver: { caps: ['tabs', 'send', 'focus'] } }, 'screen'), false)
  assert.equal(logic.canTab({ driver: { caps: [] } }, 'key'), false)
})

test('the tmux driver counts as a driver: no cmux banner, Start control offered, no text names cmux', async () => {
  const logic = await import(pathToFileURL(path.join(WEB, 'logic.js')).href)
  const TMUX = ['tabs', 'sessions', 'open', 'launch', 'send', 'rename', 'control', 'caps', 'focus', 'key', 'screen', 'close']
  // the banner says no driver lists the tabs: not with tmux, not while the driver has not answered yet
  assert.equal(logic.noTabDriver({ cmux: { ok: false, error: 'cmux CLI not found' }, driver: { caps: TMUX } }), false)
  assert.equal(logic.noTabDriver({ cmux: { ok: true }, driver: { caps: [] } }), false)
  assert.equal(logic.noTabDriver({ cmux: { ok: false }, driver: { caps: null } }), false)
  assert.equal(logic.noTabDriver({ cmux: { ok: false }, driver: { caps: [] } }), true)
  const tabs = read('views/tabs.js')
  assert.match(tabs, /\$\{noTabDriver\(s\) \? html`<p class="banner">/)
  assert.doesNotMatch(tabs, /\$\{!s\.cmux\?\.ok \? html`<p class="banner">/)
  // Start control asks the driver for a control tab: tmux can, without cmux
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'bridge-cockpit-control-'))
  try {
    fs.cpSync(WEB, path.join(dir, 'web'), { recursive: true })
    fs.writeFileSync(path.join(dir, 'web', 'package.json'), '{"type":"module"}')
    const header = await import(pathToFileURL(path.join(dir, 'web', 'views', 'header.js')).href)
    const relay = { enabled: true, online: false, reason: 'no_control' }
    assert.equal(header.canStartControl({ relay, cmux: { ok: false }, driver: { caps: TMUX } }), true)
    assert.equal(header.canStartControl({ relay: { ...relay, reason: 'no_heartbeat' }, cmux: { ok: false }, driver: { caps: TMUX } }), true)
    assert.equal(header.canStartControl({ relay, cmux: { ok: true }, driver: { caps: [] } }), false)    // no driver: nothing to start in
    assert.equal(header.canStartControl({ relay: { ...relay, online: true }, cmux: { ok: false }, driver: { caps: TMUX } }), false)
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
  // the texts of tabs and sessions name no driver; cmux stays in the texts of its own features
  const CMUX_ONLY = new Set(['errors.cmux_unavailable'])
  for (const lang of [text.TABLES.en, text.TABLES.de]) {
    for (const [at, value] of leaves(lang)) {
      if (CMUX_ONLY.has(at)) continue
      assert.doesNotMatch(String(value), /cmux/i, at)
    }
  }
})

test('the start page: greeting by hour, project chips from tabs and rows, cards filtered by project', async () => {
  const logic = await import(pathToFileURL(path.join(WEB, 'logic.js')).href)
  assert.deepEqual([3, 7, 13, 19, 23].map(logic.greetingPart), ['night', 'early', 'day', 'evening', 'night'])
  const tabs = [
    { ref: 'c', name: 'Bridge', workspace: 'Bridge', state: 'waiting', is_control: true },
    { ref: 'a', name: 'Metrics', workspace: 'ACME', state: 'working', since_ms: 5 },
    { ref: 'b', name: 'Log', workspace: 'ACME', state: 'needs-you', since_ms: 9 },
    { ref: 'd', name: 'orbit', workspace: 'ORBIT', state: 'waiting', since_ms: 1 },
    { ref: 'e', name: 'zsh', workspace: '', state: 'shell' },
  ]
  const rows = [
    { key: 'r1', area: 'Bridge', area_names: ['Bridge', 'open-bridge'] },
    { key: 'r2', area: null, area_names: [], mark: { label: 'acme' } },
    { key: 'r3', area: 'Privat', area_names: ['Privat'] },
  ]
  // most frequent first, names merged without regard to case, the control tab and empty names left out
  assert.deepEqual(logic.homeProjects(tabs, rows), ['ACME', 'Bridge', 'ORBIT', 'Privat'])
  assert.equal(logic.inProject(rows[1], 'ACME'), true)
  assert.equal(logic.inProject(rows[0], 'open-bridge'), true)
  assert.equal(logic.inProject(rows[0], 'ACME'), false)
  assert.equal(logic.inProject(rows[0], null), true)          // no chip chosen: everything
  // continue: no control tab, no bare shell; needs-you before waiting before working
  assert.deepEqual(logic.homeContinue(tabs, null).map(t => t.ref), ['b', 'd', 'a'])
  assert.deepEqual(logic.homeContinue(tabs, 'acme').map(t => t.ref), ['b', 'a'])
  // a project name always gets the same tone, and only tokens DESIGN.md has
  assert.equal(logic.projectTone('ACME'), logic.projectTone('acme'))
  assert.ok(['secondary', 'accent', 'success', 'warning', 'info'].includes(logic.projectTone('ORBIT')))
  // the tab of a task row, by its slug
  assert.equal(logic.tabOfTask([{ ref: 'x', slug: 'foo' }], 'foo').ref, 'x')
  assert.equal(logic.tabOfTask([{ ref: 'x', slug: 'foo' }], null), null)
})

test('the start page reckons a quota per day and where it ends at the reset', async () => {
  const logic = await import(pathToFileURL(path.join(WEB, 'logic.js')).href)
  // a week with 19 % used after 24.5 % of it: 11.1 a day against a budget of 14.3, 77.6 at the reset
  const week = logic.meterPace({ value: 19, max: 100, elapsed: 0.245, window_h: 168 })
  assert.equal(week.perDay.toFixed(1), '11.1')
  assert.equal(week.budget.toFixed(1), '14.3')
  assert.equal(week.projected.toFixed(1), '77.6')
  assert.equal(week.over, false)
  assert.equal(logic.meterPace({ value: 40, max: 100, elapsed: 0.25, window_h: 168 }).over, true)
  // a window shorter than a day has no share per day, only the projection
  const session = logic.meterPace({ value: 30, max: 100, elapsed: 0.5, window_h: 5 })
  assert.equal(session.perDay, null)
  assert.equal(session.projected, 60)
  // too early in the window, or no window at all: nothing to reckon
  assert.equal(logic.meterPace({ value: 1, max: 100, elapsed: 0.01, window_h: 168 }), null)
  assert.equal(logic.meterPace({ value: 5, max: 100, elapsed: null }), null)
})

test('the start page offers every tile to choose, and without a choice only a lean default', async () => {
  const logic = await import(pathToFileURL(path.join(WEB, 'logic.js')).href)
  const model = { pages: [
    { id: 'dates', title: 'Dates', badge: { kind: 'count', n: 4 }, sections: [{ id: 'cal', kind: 'calendar', items: [] }] },
    { id: 'work', title: 'Work', badge: { kind: 'count', n: 9 }, sections: [{ id: 'tasks', kind: 'tasks', items: [] }] },
    { id: 'ops', title: 'Ops', sections: [{ id: 'quota', kind: 'command', items: [
      { title: 'Session (5 h): 3 %', meter: { value: 3, max: 100, unit: '%', window_h: 5 } },
      { title: 'Week, all models: 19 %', meter: { value: 19, max: 100, unit: '%', window_h: 168 } },
      { title: 'Cost', meter: { value: 4, unit: '$' } }] }] }] }
  assert.equal(logic.tileSlug('Week, all Modelle: Ä'), 'week-all-modelle-a')
  const ids = logic.homeCatalog(model).map(x => x.id)
  assert.deepEqual(ids, ['q:quota:session-5-h', 'q:quota:week-all-models', 'c:waiting', 'c:returns', 'c:tabs', 'c:agents', 'c:workers', 'c:next', 'c:done',
    'p:dates', 'p:work', 'p:ops', 's:focus', 's:returns', 's:pinned', 's:continue', 's:waiting', 's:tasks', 's:starts',
    'o:today', 'o:preview', 'o:trend', 'o:title', 'o:project', 'o:pulse', 'o:classic', 'k:scan', 'k:brief'])
  // a Bridge without a worker view offers no Workers station: it would lead to a tab that is not there
  assert.equal(logic.homeCatalog(model, { workers: false }).some(x => x.id === 'c:workers'), false)
  // no choice yet: the weekly quota, what waits on you, the next date, the work page, every shelf and option
  assert.deepEqual(logic.homeChosen(model, null),
    ['q:quota:week-all-models', 'c:waiting', 'c:returns', 'c:agents', 'c:workers', 'c:next', 'p:work', 's:focus', 's:returns', 's:pinned', 's:continue',
      's:waiting', 's:tasks', 's:starts', 'o:today', 'o:preview', 'o:trend', 'o:title', 'o:project', 'o:pulse', 'k:scan'])
  // a choice keeps its order, an empty one too; what the chooser had offered is never added back
  const all = ids
  assert.deepEqual(logic.homeChosen(model, { tiles: ['p:work', 'p:dates'], seen: all }), ['p:work', 'p:dates'])
  assert.deepEqual(logic.homeChosen(model, { tiles: [], seen: all }), [])
  // a tile the chooser did not offer yet comes with its default, at the end
  assert.deepEqual(logic.homeChosen(model, { tiles: ['p:dates'], seen: all.filter(x => x !== 'c:next') }), ['p:dates', 'c:next'])
  // ids of tiles that no longer exist are dropped
  assert.deepEqual(logic.homeChosen(model, { tiles: ['p:gone', 'p:dates'], seen: all }), ['p:dates'])
  // a station moves past the next station, whatever stands between them in the list
  const list = ['c:a', 's:x', 'c:b', 'o:y', 'c:c']
  const among = id => id.startsWith('c:')
  assert.deepEqual(logic.moveAmong(list, among, 'c:b', -1), ['c:b', 's:x', 'c:a', 'o:y', 'c:c'])
  assert.deepEqual(logic.moveAmong(list, among, 'c:b', 1), ['c:a', 's:x', 'c:c', 'o:y', 'c:b'])
  assert.deepEqual(logic.moveAmong(list, among, 'c:a', -1), list)
  assert.deepEqual(logic.moveAmong(list, among, 's:x', 1), list)
  // dropped on another station it takes that one's place, the ones between move by one
  assert.deepEqual(logic.dropAmong(list, among, 'c:c', 'c:a'), ['c:c', 's:x', 'c:a', 'o:y', 'c:b'])
  assert.deepEqual(logic.dropAmong(list, among, 'c:a', 'c:c'), ['c:b', 's:x', 'c:c', 'o:y', 'c:a'])
  assert.deepEqual(logic.dropAmong(list, among, 'c:a', 'c:a'), list)
  assert.deepEqual(logic.dropAmong(list, among, 'c:a', 'c:gone'), list)
})

test('the start page picks one next step, the next date, and counts by project', async () => {
  const logic = await import(pathToFileURL(path.join(WEB, 'logic.js')).href)
  const rowNow = { key: 'inbox:1', title: 'Answer' }
  const task = { key: 'task:a', task: 'a', priority: 'P1', title: 'A' }
  const model = { sections: [{ id: 'now', rows: [rowNow] }, { id: 'work', rows: [{ key: 'task:b', task: 'b', priority: 'P3' }, task] }] }
  const tabs = [{ ref: 'c', state: 'needs-you', is_control: true }, { ref: 't', state: 'waiting' }]
  assert.equal(logic.focusPick(tabs, model).row, rowNow)                       // what waits on you first
  const asking = [...tabs, { ref: 'n', state: 'needs-you', name: 'x' }]
  assert.equal(logic.focusPick(asking, model).tab.ref, 'n')                     // a tab that asks you beats it
  assert.equal(logic.focusPick([], { sections: [{ id: 'now', rows: [] }, model.sections[1]] }).row, task)   // else the first P0/P1 task
  assert.equal(logic.focusPick([], { sections: [] }), null)
  const now = Date.parse('2026-10-13T20:00')
  const pages = [{ id: 'dates', sections: [{ id: 'cal', kind: 'calendar', items: [
    { title: 'Past', at: '2026-10-13T09:00' }, { title: 'Weekly', at: '2026-10-14T18:00' }, { title: 'Soon', at: '2026-10-13T21:30' },
    { title: 'No time' }] }] }]
  const next = logic.nextEvent({ pages }, now)
  assert.equal(next.it.title, 'Soon')
  assert.equal(next.ms - now, 90 * 60000)
  assert.equal(logic.nextEvent({ pages: [] }, now), null)
  // every coming event in time order, for the list beside an opened one
  assert.deepEqual(logic.upcomingEvents({ pages }, now).map(x => x.it.title), ['Soon', 'Weekly'])
  assert.deepEqual(logic.upcomingEvents({ pages }, now, 1).map(x => x.it.title), ['Soon'])
  assert.equal(logic.untilText(90 * 60000), '1 h 30 min')
  assert.equal(logic.untilText(25 * 60000), '25 min')
  assert.equal(logic.untilText(26 * 3600000), '1 d 2 h')
  // a page's items in a project, by mark or area
  assert.equal(logic.countInProject([{ mark: { label: 'ACME' } }, { area: 'acme' }, { mark: null }], 'ACME'), 2)
})

test('the bridge stage lays its stations around the core and draws the same dust every time', async () => {
  const logic = await import(pathToFileURL(path.join(WEB, 'logic.js')).href)
  const spots = logic.stageSpots(6)
  assert.equal(spots.length, 6)
  for (const p of spots) {
    assert.ok(p.x > 40 && p.x < logic.STAGE.w - 40 && p.y > 40 && p.y < logic.STAGE.h - 40, `inside the stage: ${p.x},${p.y}`)
    // every link leaves the core at its rim and bends
    assert.ok(Math.hypot(p.from.x - logic.STAGE.cx, (p.from.y - logic.STAGE.cy) / logic.STAGE.squash) > 100)
    assert.match(p.path, /^M[\d.]+ [\d.]+ Q[\d.]+ [\d.]+ [\d.]+ [\d.]+$/)
  }
  // no two stations on top of each other
  for (let i = 0; i < spots.length; i++) for (let j = i + 1; j < spots.length; j++) {
    assert.ok(Math.hypot(spots[i].x - spots[j].x, spots[i].y - spots[j].y) > 110)
  }
  assert.equal(logic.stageSpots(0).length, 0)
  assert.equal(logic.stageSpots(20).length, 14)              // at most fourteen stations
  const many = logic.stageSpots(14)
  for (let i = 0; i < many.length; i++) for (let j = i + 1; j < many.length; j++) {
    assert.ok(Math.hypot(many[i].x - many[j].x, many[i].y - many[j].y) > 95, 'fourteen still apart')
  }
  for (const p of many) assert.ok(p.x > 30 && p.x < logic.STAGE.w - 30 && p.y > 30 && p.y < logic.STAGE.h - 30)
  assert.deepEqual(logic.stageDust(40, 7), logic.stageDust(40, 7))
  assert.equal(logic.stageDust(40, 7).length, 40)
})

test('a station beats faster the worse it stands', async () => {
  const logic = await import(pathToFileURL(path.join(WEB, 'logic.js')).href)
  const beats = ['danger', 'warning', 'info', 'success'].map(logic.pulseSpeed)
  assert.deepEqual([...beats].sort((a, b) => a - b), beats)          // red fastest, green calmest
  assert.equal(logic.pulseSpeed('muted'), null)
})

test('the return channel takes the tab state live and keeps what the server knows of answers', async () => {
  const logic = await import(pathToFileURL(path.join(WEB, 'logic.js')).href)
  const r = { key: 'task:a', item: 'a', at_ms: 1000, stage: 'working', tab: { ref: 'surface:1' } }
  assert.equal(logic.liveStage(r, [{ ref: 'surface:1', state: 'needs-you' }], 2000), 'asks')
  assert.equal(logic.liveStage(r, [{ ref: 'surface:9', slug: 'a', state: 'working' }], 2000), 'working')
  assert.equal(logic.liveStage(r, [], 2000), 'started')
  assert.equal(logic.liveStage(r, [], 1000 + 4 * 60000), 'lost')
  assert.equal(logic.liveStage({ ...r, stage: 'result' }, [], 9e9), 'result')
  assert.equal(logic.liveStage(r, [{ ref: 'surface:1', state: 'working', is_control: true }], 2000), 'started')
  assert.equal(logic.stageTone('asks'), 'warning')
  assert.equal(logic.stageTone('lost'), 'danger')
})

test('the live feed reads what happened between two states of the page', async () => {
  const logic = await import(pathToFileURL(path.join(WEB, 'logic.js')).href)
  const row = (key, title, extra = {}) => ({ key, title, ...extra })
  const before = { sections: [{ id: 'now', rows: [row('inbox:a', 'A'), row('inbox:b', 'B', { urgency: 'later' })] }],
    pages: [{ id: 'ops', title: 'Ops', badge: { kind: 'count', n: 2 } }], alarms: [], returns: [{ key: 'task:x', title: 'X', stage: 'working' }] }
  const after = { sections: [{ id: 'now', rows: [row('inbox:b', 'B', { urgency: 'now' }), row('inbox:c', 'C')] }],
    pages: [{ id: 'ops', title: 'Ops', badge: { kind: 'bad', n: 1 } }],
    alarms: [{ page_id: 'ops', page_title: 'Ops', section_title: 'Probes', count: 1 }],
    returns: [{ key: 'task:x', title: 'X', stage: 'result' }] }
  const tabsBefore = [{ ref: 's1', name: 'ORBIT', state: 'working' }]
  const tabsAfter = [{ ref: 's1', name: 'ORBIT', state: 'needs-you' }, { ref: 's2', name: 'New', state: 'working' }]
  const ev = logic.feedEvents(before, after, tabsBefore, tabsAfter, 1000)
  const kinds = ev.map(e => `${e.kind}:${e.title}`)
  assert.deepEqual(kinds.sort(), ['alarm:Probes', 'answer:X', 'gone:A', 'new:C', 'tabAsks:ORBIT', 'urgent:B'].sort())
  assert.ok(ev.every(e => e.at === 1000))
  assert.equal(ev.find(e => e.kind === 'new').key, 'inbox:c')
  // the first state has no before: nothing happened yet
  assert.deepEqual(logic.feedEvents(null, after, null, tabsAfter, 1000), [])
  // a feed keeps the newest first and no more than its cap; the same event twice in a row counts once
  let feed = []
  feed = logic.addFeed(feed, ev, 50)
  feed = logic.addFeed(feed, [{ kind: 'new', key: 'inbox:c', title: 'C', at: 2000 }], 50)
  assert.equal(feed.filter(e => e.kind === 'new' && e.key === 'inbox:c').length, 1)
  assert.equal(logic.addFeed([], Array.from({ length: 80 }, (_, i) => ({ kind: 'new', key: `k${i}`, title: 't', at: i })), 50).length, 50)
})

test('the inner room lays the net out, projects it and wanders through it', async () => {
  const logic = await import(pathToFileURL(path.join(WEB, 'logic.js')).href)
  const nodes = [
    { id: 'bridge-config.yaml', group: 'core', label: 'bridge-config', degree: 2 },
    { id: 'identity/personas/me.yaml', group: 'identity', label: 'me', title: 'The persona', degree: 2 },
    { id: 'infra/remotes/box.yaml', group: 'infra', label: 'box', degree: 3 },
    { id: 'workflow/workloads/job.yaml', group: 'workflow', label: 'job', degree: 1 },
    { id: 'docs/alone.md', group: 'docs', label: 'alone', degree: 0 },
  ]
  const edges = [{ s: nodes[0].id, t: nodes[1].id }, { s: nodes[0].id, t: nodes[2].id }, { s: nodes[3].id, t: nodes[2].id },
    { s: nodes[1].id, t: nodes[2].id }, { s: nodes[1].id, t: 'gone.yaml' }]
  const g = logic.seedGraph(nodes, edges)
  // an edge to a node that is not in the net is dropped; adjacency runs both ways
  assert.equal(g.links.length, 4)
  assert.deepEqual([...g.adj[2]].sort(), [0, 1, 3])
  // the same tree grows into the same net
  assert.deepEqual([...logic.seedGraph(nodes, edges).pos], [...g.pos])
  let moved = Infinity
  for (let k = 0; k < 300; k++) moved = logic.stepGraph(g)
  assert.ok(moved < 0.5, `the net settles (${moved})`)
  assert.ok([...g.pos].every(Number.isFinite))
  // the camera's target sits in the middle of the screen; behind the camera nothing is drawn
  const cam = { yaw: 0, pitch: 0, dist: 500, target: [10, 20, 30], fov: 1 }
  const mid = logic.projectPoint(10, 20, 30, cam, 800, 600)
  assert.equal(mid.x, 400)
  assert.equal(mid.y, 300)
  assert.ok(logic.projectPoint(10, 20, -600, cam, 800, 600).scale === 0)
  assert.ok(logic.projectPoint(10, 20, 200, cam, 800, 600).scale < mid.scale)
  // a journey goes to a neighbour not seen yet, then jumps to an unseen connected node
  const visited = new Set([0])
  const hop = logic.nextHop(g, 0, visited, () => 0)
  assert.ok([1, 2].includes(hop))
  assert.equal(logic.nextHop(g, 3, new Set([0, 1, 2, 3]), () => 0), 2)
  // the search: the name first, then its start, then the title
  assert.deepEqual(logic.graphFind(nodes, 'box'), [2])
  assert.deepEqual(logic.graphFind(nodes, 'persona'), [1])
  assert.deepEqual(logic.graphFind(nodes, ''), [])
})

test('the picture of the day is read from the page data and the verdict keeps to its three lines', async () => {
  const logic = await import(pathToFileURL(path.join(WEB, 'logic.js')).href)
  const now = Date.parse('2026-10-13T10:00:00Z')
  const model = {
    sections: [
      { id: 'now', rows: [{ key: 'inbox:a', title: 'Answer the vendor', priority: 'P1' }] },
      { id: 'give', rows: [{ key: 'inbox:g', title: 'Approve the plan' }] },
      { id: 'work', rows: [{ key: 'task:t', title: 'Ship it', task: 't', priority: 'P2' }] },
      { id: 'later', rows: [{ key: 'inbox:l1', title: 'Someday' }, { key: 'inbox:l2', title: 'Maybe' }] },
    ],
    pages: [{ id: 'llm', sections: [
      { id: 'usage', items: [
        { title: 'Weekly: 40 %', meter: { unit: '%', value: 40, max: 100, elapsed: 0.2, window_h: 168 } },
        { title: 'Session: 70 %', meter: { unit: '%', value: 70, max: 100, elapsed: 0.9, window_h: 5, warn: 80 } },
      ] },
      { id: 'cal', kind: 'calendar', items: [{ title: 'Standup', at: '2026-10-13T11:30:00Z' }] },
    ] }],
    alarms: [{ page_id: 'ops', page_title: 'Ops', section_title: 'Probes', count: 2 }],
    returns: [{ key: 'task:x', title: 'X', stage: 'result' }, { key: 'task:y', title: 'Y', stage: 'lost' }],
  }
  const tabs = [{ ref: 's1', name: 'ORBIT', state: 'needs-you' }, { ref: 's2', name: 'Docs', state: 'working' }, { ref: 'c', name: 'ctl', state: 'working', is_control: true }]
  const sit = logic.situation(model, tabs, now)
  assert.equal(sit.first.kind, 'tab')
  assert.equal(sit.asking.length, 1)
  assert.deepEqual(sit.working.map(t => t.name), ['Docs'])
  assert.equal(sit.answers[0].key, 'task:x')
  assert.equal(sit.lost[0].key, 'task:y')
  assert.equal(sit.next.it.title, 'Standup')
  // the weekly quota runs over its pace (40 % after a fifth), so it is the tightest, not the higher session gauge
  assert.equal(sit.quota.label, 'Weekly')
  assert.ok(sit.quota.over)
  const text = logic.situationText(sit, now, 'de')
  assert.match(text, /^Wartet auf dich: P1 Answer the vendor$/m)
  assert.match(text, /^Tabs, die dich fragen: ORBIT$/m)
  assert.match(text, /^Nächster Termin: Standup in 1 h 30 min$/m)
  assert.match(text, /^Engstes Kontingent: Weekly 40 %, \d+ % pro Tag, reicht nicht/m)
  assert.match(text, /^Später: 2$/m)
  assert.doesNotMatch(text, /ctl/)
  // the verdict: three labelled lines, in either language, markdown around them ignored
  assert.deepEqual(logic.parseVerdict('**Zuerst:** ORBIT antworten.\nDann: Ship it.\n- Kann warten: Someday.'),
    { first: 'ORBIT antworten.', then: 'Ship it.', later: 'Someday.' })
  assert.deepEqual(logic.parseVerdict('First: a\nThen: b\nCan wait: c'), { first: 'a', then: 'b', later: 'c' })
  assert.equal(logic.parseVerdict('Just some prose.'), null)
})

test('the net knows what is alive: tabs on tasks, answers, quiet starts, workers with findings', async () => {
  const logic = await import(pathToFileURL(path.join(WEB, 'logic.js')).href)
  const nodes = ['work/tasks/alpha/STATUS.md', 'work/streams/beta/STATUS.md', 'workflow/workloads/job.yaml', 'workflow/workloads/ok.yaml', 'work/tasks/gamma/STATUS.md']
    .map(id => ({ id, group: 'work', label: id }))
  const g = logic.seedGraph(nodes, [])
  const live = logic.graphLive(g,
    [{ ref: 's1', name: 'Alpha tab', slug: 'alpha', state: 'working' }, { ref: 's2', name: 'Beta tab', slug: 'beta', state: 'needs-you' },
      { ref: 'c', slug: 'alpha', state: 'needs-you', is_control: true }],
    [{ key: 'task:alpha', item: 'alpha', title: 'Alpha', stage: 'result' }, { key: 'task:gamma', item: 'gamma', title: 'Gamma', stage: 'lost' }],
    [{ id: 'job', title: 'Nightly', severity: 'high' }, { id: 'ok', severity: 'info' }])
  // a tab waiting beats an answer, an answer beats a tab at work; the control tab counts for nothing
  assert.deepEqual(live.get(0), { tone: 'answer', text: 'Alpha', key: 'task:alpha' })
  assert.deepEqual(live.get(1), { tone: 'asks', text: 'Beta tab', ref: 's2' })
  assert.equal(live.get(2).tone, 'alarm')
  assert.equal(live.has(3), false)
  assert.equal(live.get(4).tone, 'lost')
})

test('short cuts a title at a word, not in the middle of one', () => {
  assert.equal(logic.short('An application open for 16 days without an answer', 26), 'An application open for…')
  assert.equal(logic.short('kurz', 10), 'kurz')
  assert.equal(logic.short('Donaudampfschifffahrtsgesellschaft', 10), 'Donaudamp…')   // one long word: cut it
})

// ---------------------------------------------------------------- ?theme= and the demo badge

test('themeOverride: ?theme=light|dark forces the mode, anything else is no override', () => {
  assert.equal(logic.themeOverride('?theme=dark'), 'dark')
  assert.equal(logic.themeOverride('?mock=1&theme=light&lang=de'), 'light')
  for (const search of ['', '?', '?theme=', '?theme=auto', '?theme=DARK', '?theme=blue', '?mock=1', undefined, null]) {
    assert.equal(logic.themeOverride(search), null, String(search))
  }
})

/** Runs theme.js (a classic script) against a fake page: the URL, the stored choice and the system mode */
async function runThemeScript({ search = '', stored = null, systemDark = false }) {
  const vm = await import('node:vm')
  const classes = new Set()
  const attrs = {}
  const writes = []
  const window = {
    location: { search },
    localStorage: {
      getItem: key => (key === 'bridge-cockpit.theme' ? stored : null),
      setItem: (key, value) => writes.push([key, value]),
      removeItem: key => writes.push([key, null]),
    },
    matchMedia: () => ({ matches: systemDark }),
  }
  const document = {
    documentElement: {
      classList: { toggle: (name, on) => (on ? classes.add(name) : classes.delete(name)) },
      setAttribute: (name, value) => { attrs[name] = value },
    },
  }
  vm.runInNewContext(read('theme.js'), { window, document, URLSearchParams })
  return { dark: classes.has('dark'), light: classes.has('light'), mode: attrs['data-theme-mode'], writes }
}

test('theme.js: ?theme= forces the mode for this load and never writes the stored choice', async () => {
  const forced = await runThemeScript({ search: '?mock=1&theme=dark', stored: 'light' })
  assert.deepEqual([forced.dark, forced.light, forced.mode, forced.writes], [true, false, 'dark', []])
  const light = await runThemeScript({ search: '?theme=light', systemDark: true })
  assert.deepEqual([light.dark, light.light, light.mode, light.writes], [false, true, 'light', []])
})

test('theme.js: without a valid ?theme= the stored choice or the system decides, as before', async () => {
  assert.equal((await runThemeScript({ search: '?theme=bogus', stored: 'light', systemDark: true })).dark, false)
  assert.equal((await runThemeScript({ stored: 'dark' })).dark, true)
  const auto = await runThemeScript({ systemDark: true })
  assert.deepEqual([auto.dark, auto.mode, auto.writes], [true, 'auto', []])
  assert.equal((await runThemeScript({ search: '?theme=auto', systemDark: false })).dark, false)
})

test('app.js: the initial theme takes ?theme= first and does not save it', () => {
  const src = read('app.js')
  assert.match(src, /themeOverride\(window\.location\.search\)/)
  assert.match(src, /theme: THEME_OVERRIDE \?\? load\('bridge-cockpit\.theme', 'auto'\)/)
})

test('demo badge: a short text in both tables, shown in the header in mock mode only', () => {
  for (const lang of ['en', 'de']) {
    const v = text.TABLES[lang].demoBadge
    assert.equal(typeof v, 'string', lang)
    assert.ok(v.length > 0 && v.length <= 32, `${lang}: short`)
    assert.ok(text.TABLES[lang].demoBadgeShort.length <= 6, `${lang}: fits a phone header`)
  }
  assert.notEqual(text.TABLES.en.demoBadge, text.TABLES.de.demoBadge)
  const header = readComponents().match(/function Header\(\{[\s\S]*?\n\}/)[0]
  assert.match(header, /s\.mock \? html`<span class="hdr-demo" title=\$\{t\.mockNote\}>[^`]*\$\{t\.demoBadge\}[^`]*\$\{t\.demoBadgeShort\}/)
  assert.match(read('style.css'), /\.hdr-demo \{/)
})

test('a page item a person can act on gets the same row as an inbox item: Do it, Advise, Settle', () => {
  const it = { title: 'Backup stale', key: 'item:systems/checks/backup', actionable: true }
  assert.deepEqual(logic.actionRow(it, new Map()), { key: 'item:systems/checks/backup', title: 'Backup stale', settle: ['done', 'not_doing'] })
  assert.equal(logic.pageItemActs(it), true)
  // nothing to do on it, or it has an inbox item or a task of its own (their path stays): no buttons
  assert.equal(logic.pageItemActs({ ...it, actionable: false }), false)
  assert.equal(logic.pageItemActs({ ...it, inbox: 'x' }), false)
  assert.equal(logic.pageItemActs({ ...it, task: 't' }), false)
  assert.equal(logic.actionRow({ title: 'plain', key: 'item:a/b/c', actionable: false }, new Map()), null)
})

// One count per word (16.10.): a number that stands on a tab, a station of the start page and a page
// headline is the same number everywhere, from one helper, so the page never contradicts itself.
test('sessionCounts: sessions are the sessions, agents are the running subagents and workflows', () => {
  assert.deepEqual(logic.sessionCounts(undefined), { sessions: 0, agents: 0 })
  assert.deepEqual(logic.sessionCounts([]), { sessions: 0, agents: 0 })
  assert.deepEqual(logic.sessionCounts([
    { agents: { running_count: 2 }, workflows: [{ name: 'w' }] },
    { agents: { running_count: 0 }, workflows: [] },
    { agents: { running_count: 1 } },
    {},
  ]), { sessions: 4, agents: 4 })
})

test('the Sessions tab and the Sessions station show the same number from sessionCounts', () => {
  const src = readComponents()
  assert.doesNotMatch(src, /agentsActive/)
  const uses = src.match(/sessionCounts\(s\.sessions\?\.sessions\)/g) ?? []
  assert.ok(uses.length >= 2, `sessionCounts used ${uses.length} times, expected tab and station`)
})

test('the Workers tab marks findings like a page with findings, never as a bare number beside the station count', () => {
  const src = readComponents()
  // the bare grey number of findings beside "Workers" read as the count of workers (5 on Start, 2 on the tab)
  assert.doesNotMatch(src, /pbadge is-quiet"><span class="mono">\$\{s\.workers\.data\.stats\.with_findings\}/)
  assert.match(src, /tab\(WORKERS_PAGE[^\n]*\n[^\n]*workersFindings/)
})

test('demo: the coloured Today number, the waits-for-you count and the Now section agree', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'bridge-cockpit-count-'))
  try {
    fs.cpSync(WEB, path.join(dir, 'web'), { recursive: true })
    fs.writeFileSync(path.join(dir, 'web', 'package.json'), '{"type":"module"}')
    const mock = await import(pathToFileURL(path.join(dir, 'web', 'mock.js')).href)
    const m = mock.buildState().model
    const now = m.sections.find(x => x.id === 'now')
    assert.equal(m.briefing_badge, m.counts.now)
    assert.equal(m.counts.now, now.total)
    for (const id of ['give', 'work', 'later']) assert.equal(m.counts[id], m.sections.find(x => x.id === id).total, id)
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
})

// The page tabs keep their own row on every width (16.10.): folded into the header of a wide screen,
// the tabs shared the room with the tools, so at 1600 px Sessions, Workers, Check and Jev stood behind
// More, the command box shrank to a symbol and Ask lost its word, while 1100 px showed all of it.
test('the page bar has its own row on a wide screen too, never inside the header', () => {
  const src = readComponents()
  assert.doesNotMatch(src, /merged/)
  assert.match(src, /\n    <\$\{Header\} s=\$\{s\} c=\$\{ctl\} \/>\n    <\$\{PageBar\} s=\$\{s\} c=\$\{ctl\} \/>\n/)
  const css = read('style.css')
  assert.doesNotMatch(css, /is-merged/)
})

// Start keeps one block beside the bridge (17.10.): a click on a station showed its inspector and, on a wide
// screen, Today as a second block beside it. Now the block shows one thing: Today, or the station looked at.
// Today is a station of the ring itself, its click brings Today back.
test('start: one block beside the bridge, Today is a station of the ring that brings it back', () => {
  const src = readComponents()
  assert.doesNotMatch(src, /stage-today|has-today/)
  assert.match(src, /const tiles = shownTiles\(catalog, chosen\)\.slice\(0, MAX_STATIONS - 1\)/)
  assert.match(src, /id: '@today', label: h\.cardTitle/)
  assert.match(src, /const ring = \[today, \.\.\.stations\]/)
  assert.match(src, /const spots = stageSpots\(ring\.length\)/)
  // the station Today clears the selection, the block shows Today when nothing is looked at
  assert.match(src, /st\.id === '@today' \? setSel\(null\)/)
  assert.match(src, /: html`<\$\{StageCard\} s=\$\{s\} c=\$\{c\} tabs=\$\{tabs\} onWeigh=\$\{\(\) => runMode\('k:brief'\)\} \/>`\}\n      <\/div>\n    <\/div>/)
  assert.doesNotMatch(read('style.css'), /stage-today|has-today/)
})

test('one as-of time per screen: the header says it, a section only when it was measured at another time', async () => {
  const logic = await import(pathToFileURL(path.join(WEB, 'logic.js')).href)
  assert.equal(logic.sectionStamp('10:58', '11:10'), '10:58')
  assert.equal(logic.sectionStamp('11:10', '11:10'), null)
  assert.equal(logic.sectionStamp(null, '11:10'), null)
  const comp = readComponents()
  assert.doesNotMatch(comp.match(/function TabsColumn\([\s\S]*?\n\}/)[0], /formatClock/)
  const sec = comp.match(/function PageSection\([\s\S]*?\n\}/)[0]
  assert.doesNotMatch(sec, /sourceAsOf/)
  assert.match(sec, /measuredAt/)
  assert.equal(read('text.js').match(/^  measuredAt: time =>/gm)?.length, 2)
})

// The row under the bridge (17.10.): its heading said "on a click on Bridge" while a click on a name ran it
// at once; the pin beside each name was the only thing the heading described. Now the row runs now and says
// so, what joins a click on Bridge is chosen in the chooser. The focus span is gone (it only counted down),
// speech moved into the question line at the top and fills the field instead of asking on its own.
test('start: the row under the bridge runs now, no focus span, speech sits in the question line', () => {
  const src = readComponents()
  const css = read('style.css')
  const stage = src.match(/function BridgeStage\([\s\S]*?\n\}/)[0]
  // no row under the bridge any more: Reload is in the header, the assessment sits in the card Today it replaces
  assert.doesNotMatch(stage, /core-modes|core-mode-pin|k:voice|k:focus|useVoice/)
  assert.doesNotMatch(css, /\.core-mode/)
  const card = src.match(/function StageCard\([\s\S]*?\n\}/)[0]
  assert.match(card, /onWeigh/)
  assert.match(card, /h\.weighDay/)
  assert.match(stage, /<\$\{StageCard\} s=\$\{s\} c=\$\{c\} tabs=\$\{tabs\} onWeigh=/)
  assert.doesNotMatch(src + css + read('app.js'), /focusUntil|clockLeft|c\.setFocus\(|setFocus\(until|in-focus|is-clock|core-mode-pin/)
  assert.equal(logic.clockLeft, undefined)
  const prompt = src.match(/function StagePrompt\([\s\S]*?\n\}/)[0]
  assert.match(prompt, /useVoice\(/)
  assert.match(prompt, /setText\(/)
  assert.doesNotMatch(src.match(/function CoreInspector\([\s\S]*?\n\}/)[0], /voice/)
  for (const lang of ['de', 'en']) {
    const h = text.TABLES[lang].home
    for (const k of ['coreFocus', 'coreVoice', 'focusRunning', 'focusHint', 'focusEnd', 'runNow', 'modeRun']) assert.equal(h[k], undefined, `${lang}.${k}`)
    assert.ok(h.weighDay, `${lang}.weighDay`)
    for (const k of ['denied', 'nothing', 'network', 'other']) assert.ok(h.voiceError[k], `${lang}.voiceError.${k}`)
  }
})

test('a speech recognition error names its cause instead of going quiet', () => {
  assert.equal(logic.speechError('not-allowed'), 'denied')
  assert.equal(logic.speechError('service-not-allowed'), 'denied')
  assert.equal(logic.speechError('audio-capture'), 'denied')
  assert.equal(logic.speechError('no-speech'), 'nothing')
  assert.equal(logic.speechError('network'), 'network')
  assert.equal(logic.speechError('aborted'), null)     // stopped by hand: no message
  assert.equal(logic.speechError('bad-grammar'), 'other')
  assert.equal(logic.speechError(undefined), 'other')
})

test('the assessment recommends to the reader, it does not claim to start anything itself', () => {
  const de = text.TABLES.de.home.briefAsk('X')
  const en = text.TABLES.en.home.briefAsk('X')
  assert.match(de, /womit du jetzt anfängst/)
  assert.doesNotMatch(de, /womit ich/)
  assert.match(en, /what you start with now/)
  assert.doesNotMatch(en, /what I start with/)
  // the three line labels the verdict parser reads stay as they were
  assert.match(de, /Zuerst:[\s\S]*Dann:[\s\S]*Kann warten:/)
  assert.match(en, /First:[\s\S]*Then:[\s\S]*Can wait:/)
})

test('a tab whose start is settled (its item closed, its task done) offers to close, like a filed result', async () => {
  const logic = await import(pathToFileURL(path.join(WEB, 'logic.js')).href)
  const all = () => true
  assert.deepEqual(logic.tabNextStep({ state: 'waiting' }, all, true), ['close'])
  // settled but still working or asking: the tab is not done with you yet
  assert.deepEqual(logic.tabNextStep({ state: 'working' }, all, true), ['jump'])
  assert.deepEqual(logic.tabNextStep({ state: 'needs-you' }, all, true), ['yes', 'no'])
  // without the close right it stays at going to the tab
  assert.deepEqual(logic.tabNextStep({ state: 'waiting' }, k => k !== 'close', true), ['go_on'])
})

test('the starts handed to the AI fall into: done and to check, needs you, working, no word', async () => {
  const logic = await import(pathToFileURL(path.join(WEB, 'logic.js')).href)
  const now = 10 * 60000
  const returns = [
    { key: 'inbox:a', item: 'a', at_ms: 0, stage: 'done', tab: { ref: 'surface:1' } },
    { key: 'inbox:b', item: 'b', at_ms: 0, stage: 'result', tab: null },
    { key: 'task:c', item: 'c', at_ms: 0, stage: 'working', tab: { ref: 'surface:3' } },
    { key: 'task:d', item: 'd', at_ms: 0, stage: 'working', tab: { ref: 'surface:4' } },
    { key: 'task:e', item: 'e', at_ms: now - 1000, stage: 'started', tab: null },
    { key: 'task:f', item: 'f', at_ms: 0, stage: 'started', tab: null },
  ]
  const tabs = [
    { ref: 'surface:1', state: 'waiting' },
    { ref: 'surface:3', state: 'needs-you' },
    { ref: 'surface:4', state: 'working' },
  ]
  const g = logic.aiGroups(returns, tabs, now)
  assert.deepEqual(g.check.map(r => r.key), ['inbox:a', 'inbox:b'])
  assert.deepEqual(g.asks.map(r => r.key), ['task:c'])
  assert.deepEqual(g.working.map(r => r.key), ['task:d', 'task:e'])
  assert.deepEqual(g.lost.map(r => r.key), ['task:f'])
  // the tab of a settled start is the one to close; a result that is not closed yet is not
  assert.deepEqual([...logic.settledRefs(returns, tabs, now)], ['surface:1'])
  // what waits on you there: the checks whose tab is still open, plus the questions
  assert.equal(logic.aiWaiting(returns, tabs, now), 2)
  assert.equal(logic.aiWaiting([], [], now), 0)
  // a tab settled on its own (its item or task closed, no start of the cockpit) counts once as well
  assert.equal(logic.aiWaiting(returns, [...tabs, { ref: 'surface:7', state: 'waiting', settled: 'item' },
    { ref: 'surface:1', state: 'waiting', settled: 'item' }].filter((x, i, a) => a.findIndex(y => y.ref === x.ref) === i), now), 3)
  assert.equal(logic.aiWaiting([], [{ ref: 'surface:8', state: 'working', settled: 'task' }], now), 0)
})

test('the sessions page leads with what the AI did, grouped by what it wants of you', () => {
  const src = fs.readFileSync(path.join(WEB, 'views', 'sessions.js'), 'utf8')
  const page = src.match(/export function SessionsPage\([\s\S]*?\n\}/)[0]
  assert.match(page, /<\$\{AiReturns\}/)
  const ai = src.match(/function AiReturns\([\s\S]*?\n\}/)[0]
  assert.match(ai, /aiGroups\(/)
  for (const g of ['check', 'asks', 'working', 'lost']) assert.match(ai, new RegExp(`'${g}'`))
  // a tab settled on its own (no start of the cockpit names it) stands under done as well
  assert.match(ai, /settled && /)
  assert.match(ai, /<\$\{TabCard\}/)
})

// The session card (the full tab from the tab list, its last line, settled, the slim controls), the
// return card (closing a settled tab), TabControls (settled reaches the next step) and the header's
// scratch hint are rendered against mock states in bridge_cockpit_render.test.mjs, which asserts on
// what they show and send instead of on their source.

test('the sessions tab counts what the AI left for you', () => {
  const src = fs.readFileSync(path.join(WEB, 'views', 'header.js'), 'utf8')
  assert.match(src, /aiWaiting\(/)
})

// ---------------------------------------------------------------- the model an agent tab starts with (launch)

const LAUNCH = {
  enabled: true, manual: true, auto: true, effort: true, models: ['haiku', 'sonnet', 'opus'], efforts: ['low', 'medium', 'high', 'xhigh'],
  default_model: 'sonnet', default_effort: null, router: 'jev',
}
const ROUTE = { model: 'sonnet', effort: 'high', routed_by: 'jev', level: 1.2, confidence: 0.8, why: 'a change in two files' }

test('launch: the start picker offers per switch, nothing while off or on an older server', () => {
  assert.equal(logic.launchOptions(undefined), null)
  assert.equal(logic.launchOptions(null), null)
  assert.equal(logic.launchOptions({ ...LAUNCH, enabled: false }), null)
  assert.deepEqual(logic.launchOptions(LAUNCH), { models: ['auto', 'haiku', 'sonnet', 'opus'], efforts: ['auto', 'standard', 'low', 'medium', 'high', 'xhigh'], readOnly: false })
  // without Auto: the models only, the effort without its own Auto
  assert.deepEqual(logic.launchOptions({ ...LAUNCH, auto: false }), { models: ['haiku', 'sonnet', 'opus'], efforts: ['standard', 'low', 'medium', 'high', 'xhigh'], readOnly: false })
  // without manual choice: Auto stands alone and read only
  assert.deepEqual(logic.launchOptions({ ...LAUNCH, manual: false, effort: false }), { models: ['auto'], efforts: [], readOnly: true })
  assert.deepEqual(logic.launchOptions({ ...LAUNCH, manual: false, auto: false, effort: false }), { models: [], efforts: [], readOnly: true })
  // the choice: Auto while Auto is on, else the default model; a stored choice the switches no longer offer falls back
  assert.deepEqual(logic.launchChoice(LAUNCH, {}), { model: 'auto', effort: 'auto' })
  assert.deepEqual(logic.launchChoice({ ...LAUNCH, auto: false }, {}), { model: 'sonnet', effort: 'standard' })
  assert.deepEqual(logic.launchChoice({ ...LAUNCH, auto: false, default_effort: 'high' }, {}), { model: 'sonnet', effort: 'high' })
  assert.deepEqual(logic.launchChoice(LAUNCH, { launchModel: 'opus', launchEffort: 'low' }), { model: 'opus', effort: 'low' })
  assert.deepEqual(logic.launchChoice({ ...LAUNCH, manual: false }, { launchModel: 'opus' }), { model: 'auto', effort: 'auto' })
  assert.deepEqual(logic.launchChoice({ ...LAUNCH, auto: false }, { launchModel: 'auto', launchEffort: 'auto' }), { model: 'sonnet', effort: 'standard' })
})

test('launch: start args stay exactly as before while off; on, the choice goes along, Auto as its cached recommendation', () => {
  const args = { keys: ['task:a'], target: 'tab' }
  // off, missing or not a start verb: the very same object, nothing added
  for (const launch of [undefined, null, { ...LAUNCH, enabled: false }]) {
    for (const verb of logic.START_VERBS) assert.equal(logic.withLaunch(verb, args, launch, { launchModel: 'opus' }, {}), args, verb)
  }
  assert.equal(logic.withLaunch('drop', { key: 'task:a' }, LAUNCH, {}, {}).model, undefined)
  assert.deepEqual(logic.START_VERBS, ['do_it', 'advise', 'start_agent', 'collect_context', 'team_role', 'session_resume', 'chat_tab', 'quick_handoff'])
  // Auto without a recommendation: the server decides
  assert.deepEqual(logic.withLaunch('do_it', args, LAUNCH, {}, {}), { ...args, model: 'auto', effort: 'auto' })
  // Auto with one cached: its concrete model and effort, so the server need not route again
  const routes = { 'task:a': { title: 'A', status: 'ok', route: ROUTE } }
  assert.deepEqual(logic.withLaunch('do_it', args, LAUNCH, {}, routes), { ...args, model: 'sonnet', effort: 'high' })
  assert.deepEqual(logic.withLaunch('collect_context', { key: 'task:a' }, LAUNCH, {}, routes), { key: 'task:a', model: 'sonnet', effort: 'high' })
  // still loading or failed: auto
  assert.deepEqual(logic.withLaunch('do_it', args, LAUNCH, {}, { 'task:a': { title: 'A', status: 'loading' } }), { ...args, model: 'auto', effort: 'auto' })
  assert.deepEqual(logic.withLaunch('do_it', args, LAUNCH, {}, { 'task:a': { title: 'A', status: 'error' } }), { ...args, model: 'auto', effort: 'auto' })
  // several rows at once: one model for all is no recommendation, the server routes each
  assert.deepEqual(logic.withLaunch('advise', { keys: ['task:a', 'task:b'] }, LAUNCH, {}, routes), { keys: ['task:a', 'task:b'], model: 'auto', effort: 'auto' })
  // a manual pick, Standard effort sent as such (the server drops the flag), the effort switch off sends none
  assert.deepEqual(logic.withLaunch('do_it', args, LAUNCH, { launchModel: 'opus', launchEffort: 'standard' }, routes), { ...args, model: 'opus', effort: 'standard' })
  assert.deepEqual(logic.withLaunch('chat_tab', { text: 'x' }, { ...LAUNCH, effort: false }, { launchModel: 'haiku' }, {}), { text: 'x', model: 'haiku' })
  assert.deepEqual(logic.withLaunch('session_resume', { session: 's1' }, { ...LAUNCH, effort: false }, {}, {}), { session: 's1', model: 'auto' })
  // a manual model with effort Auto: the recommendation's effort belongs to its model, so the server decides
  assert.deepEqual(logic.withLaunch('do_it', args, LAUNCH, { launchModel: 'haiku' }, routes), { ...args, model: 'haiku', effort: 'auto' })
  // Auto read only (manual off) still sends Auto
  assert.deepEqual(logic.withLaunch('do_it', args, { ...LAUNCH, manual: false, effort: false }, { launchModel: 'opus' }, {}), { ...args, model: 'auto' })
  // the controller sends every action through withLaunch, with the routes it cached
  const act = read('app.js').match(/async function act\(verb, args = \{\}\) \{[\s\S]*?\n\}/)[0]
  assert.match(act, /api\.action\(verb, withLaunch\(verb, p\.args, st\.launch, st\.ui, st\.launchRoutes\)\)/)
})

test('launch: the recommendation reads short in both languages, its reason as the tooltip', () => {
  for (const lang of ['en', 'de']) {
    const t = text.TABLES[lang]
    assert.equal(logic.routeText(ROUTE, t, lang), lang === 'de' ? 'Auto: Sonnet · hoch (Jev, Stufe 1,2)' : 'Auto: Sonnet · high (Jev, level 1.2)')
    assert.equal(logic.routeText({ ...ROUTE, routed_by: 'haiku', level: 2 }, t, lang), lang === 'de' ? 'Auto: Sonnet · hoch (Haiku)' : 'Auto: Sonnet · high (Haiku)')
    assert.equal(logic.routeText({ model: 'opus', effort: null, routed_by: 'default', level: null }, t, lang), lang === 'de' ? 'Auto: Opus (Standard)' : 'Auto: Opus (default)')
    assert.equal(logic.routeText(null, t, lang), null)
  }
})

test('launch: the route cache fetches once per key and again when the title changed, at most 20 at a time', () => {
  const items = [{ key: 'a', title: 'A' }, { key: 'b', title: 'B' }, { key: 'c', title: 'C' }]
  const cache = { a: { title: 'A', status: 'ok', route: ROUTE }, b: { title: 'old B', status: 'ok', route: ROUTE }, c: { title: 'C', status: 'error' } }
  assert.deepEqual(logic.routesToFetch(items, cache), ['b'])                      // a error stays quiet, no retry loop
  assert.deepEqual(logic.routesToFetch(items, {}), ['a', 'b', 'c'])
  assert.equal(logic.routesToFetch(Array.from({ length: 30 }, (_, i) => ({ key: `k${i}`, title: 'x' })), {}).length, 20)
  // the api posts the keys to /api/route with the token
  const calls = []
  const a = api.createApi({ get: async () => ({}), post: async (p, b, csrf) => { calls.push([p, b, csrf]); return { ok: true } }, events: () => ({}) })
  a.setCsrf('tok')
  a.route(['task:a'])
  assert.deepEqual(calls, [['/api/route', { keys: ['task:a'] }, 'tok']])
  const app = read('app.js')
  assert.match(app, /launchRoute: async items => \{/)
  assert.match(app, /routesToFetch\(items, store\.get\(\)\.launchRoutes\)/)
})

test('launch: the picker stands in every start block and only there through one shared component', () => {
  const comp = readComponents()
  const pick = read('views/launch.js')
  assert.match(pick, /export function LaunchPick\(\{ s, c, items = \[\] \}\)/)
  assert.match(pick, /const opts = launchOptions\(s\.launch\)/)
  assert.match(pick, /if \(!opts\) return null/)
  // one central choice, kept in this browser
  const app = read('app.js')
  assert.match(app, /launchModel: load\('bridge-cockpit\.launchModel', null\)/)
  assert.match(app, /launchEffort: load\('bridge-cockpit\.launchEffort', null\)/)
  assert.match(app, /setLaunchModel: m => \{ save\('bridge-cockpit\.launchModel', m\); setUi\(\{ launchModel: m \}\) \}/)
  assert.match(app, /launch: payload\.launch \?\? s\.launch/)
  // the detail's start block, the item drawer, the chat foot, both bulk bars
  for (const name of ['ActionsBlock', 'ItemDrawer', 'ChatFoot', 'SelectionBar']) {
    const body = comp.match(new RegExp(`function ${name}\\([\\s\\S]*?\\n\\}`))[0]
    assert.match(body, /<\$\{LaunchPick\}/, name)
  }
  assert.match(read('views/check.js'), /<\$\{LaunchPick\} s=\$\{s\} c=\$\{c\} items=/)
  for (const lang of ['en', 'de']) {
    const t = text.TABLES[lang]
    for (const m of ['auto', 'haiku', 'sonnet', 'opus']) assert.ok(t.launch.model[m], `${lang} ${m}`)
    for (const e of ['auto', 'standard', 'low', 'medium', 'high', 'xhigh']) assert.ok(t.launch.effort[e], `${lang} ${e}`)
  }
})

test('settings: a page of its own behind More, always there, with the launch group and room for more', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'bridge-cockpit-settings-'))
  try {
    fs.cpSync(WEB, path.join(dir, 'web'), { recursive: true })
    fs.writeFileSync(path.join(dir, 'web', 'package.json'), '{"type":"module"}')
    const comp = await import(pathToFileURL(path.join(dir, 'web', 'components.js')).href)
    assert.ok(comp.pageOrder({}).includes('@settings'))
    assert.ok(comp.morePages({}).has('@settings'))
    assert.equal(comp.pageOrder({ model: { pages: [{ id: 'z', group: 'more' }] } }).at(-1), '@settings')
    // its button in the start page's quick access carries its name, never the raw id
    const home = await import(pathToFileURL(path.join(dir, 'web', 'views', 'home.js')).href)
    const texts = await import(pathToFileURL(path.join(dir, 'web', 'text.js')).href)
    assert.equal(home.pageTitleOf({}, '@settings'), texts.T().settings.title)
    // the demo: the page works without a server, a save changes the settings, a reset puts the config back
    const mock = await import(pathToFileURL(path.join(dir, 'web', 'mock.js')).href)
    assert.equal(mock.buildState().launch.enabled, true)
    const tr = mock.createMockTransport({ lang: 'en' })
    let r = await tr.post('/api/action', { verb: 'launch_settings', args: { settings: { auto: false } } })
    assert.equal(r.ok, true)
    let st = (await tr.get('/api/state')).data
    assert.equal(st.launch.settings.auto, false)
    assert.equal(st.launch.auto, false)
    assert.deepEqual(st.launch.overridden, ['auto'])
    r = await tr.post('/api/route', { keys: ['task:demo'] })
    assert.equal(r.ok, false)
    assert.equal(r.error.code, 'launch_off')
    await tr.post('/api/action', { verb: 'launch_settings_reset', args: {} })
    st = (await tr.get('/api/state')).data
    assert.equal(st.launch.settings.auto, true)
    assert.deepEqual(st.launch.overridden, [])
    r = await tr.post('/api/route', { keys: ['task:demo'] })
    assert.equal(r.ok, true)
    assert.ok(['haiku', 'sonnet', 'opus'].includes(r.data.routes['task:demo'].model))
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
  const page = read('views/settings.js')
  assert.match(page, /export function SettingsPage\(\{ s, c \}\)/)
  assert.match(page, /const SECTIONS = \['start', 'look', 'launch', 'ticker'\]/)                   // the areas; a later one joins the list
  assert.match(page, /const AREAS = \{ start: StartArea, look: LookArea, launch: LaunchArea, ticker: TickerSettings \}/)
  // the ticker's group draws with the page's own parts, no copies of them
  for (const part of ['Switch', 'Card', 'Row']) assert.match(page, new RegExp(`^export function ${part}\\(`, 'm'), part)
  const tickerView = read('views/ticker.js')
  assert.match(tickerView, /^import \{ Card, Row, Switch \} from '\.\/settings\.js'/m)
  assert.doesNotMatch(tickerView, /function Ticker(Card|Row|Switch)\b/)
  assert.doesNotMatch(tickerView, /class="set-row|class=\$\{`panel set-card|role="switch"/)
  assert.match(page, /disabled=\$\{busy \|\| \(k !== 'enabled' && !on\)/)                  // the switches below the main one grey while it is off
  assert.match(page, /\$\{st\.auto \? html`/)                                               // Auto's details only while Auto is on
  assert.match(page, /import \{ TickerSettings \} from '\.\/ticker\.js'/)
  assert.match(page, /c\.resetLaunch\(\)/)
  assert.match(page, /overridden/)
  assert.match(read('components.js'), /s\.ui\.page === SETTINGS_PAGE\) return html`<\$\{SettingsPage\}/)
  const app = read('app.js')
  assert.match(app, /saveLaunch: async settings => \{\n\s+const r = await act\('launch_settings', \{ settings \}\)/)
  assert.match(app, /resetLaunch: async \(\) => \{\n\s+const r = await act\('launch_settings_reset', \{\}\)/)
})

test('settings: a change sends only what changed; Standard is no effort; the Jev name and bands are checked', () => {
  assert.deepEqual(logic.launchPatch('auto', false), { auto: false })
  assert.deepEqual(logic.launchPatch('default_effort', 'standard'), { default_effort: null })
  assert.deepEqual(logic.launchPatch('default_effort', 'high'), { default_effort: 'high' })
  assert.deepEqual(logic.launchPatch('jev_model', ' jev-1.14.0 '), { jev_model: 'jev-1.14.0' })
  for (const ok of ['jev-1.14.0', 'jev-2.0', 'jev-10.3.12']) assert.equal(logic.jevModelValid(ok), true, ok)
  for (const bad of ['jev', 'jev-1', 'Jev-1.2', 'jev-1.2.3.4', 'jev-1.x', '']) assert.equal(logic.jevModelValid(bad), false, bad)
  const bands = [{ below: 0.75, model: 'haiku', effort: 'medium' }, { below: 1.3, model: 'sonnet', effort: 'medium' }, { below: null, model: 'opus', effort: 'xhigh' }]
  assert.equal(logic.bandsProblem(bands), null)
  assert.equal(logic.bandsProblem([{ below: 1.3, model: 'sonnet' }, { below: 0.75, model: 'haiku' }, { below: null, model: 'opus' }]), 'order')
  assert.equal(logic.bandsProblem([{ below: 3.5, model: 'sonnet' }, { below: null, model: 'opus' }]), 'range')
  assert.equal(logic.bandsProblem([{ below: Number.NaN, model: 'sonnet' }, { below: null, model: 'opus' }]), 'range')
  assert.equal(logic.bandsProblem([{ below: 1, model: 'sonnet' }, { below: 2, model: 'opus' }]), 'last')
  for (const lang of ['en', 'de']) {
    const t = text.TABLES[lang]
    for (const k of ['title', 'launchTitle', 'reset', 'changed', 'jevModelBad', 'save']) assert.ok(t.settings[k], `${lang} ${k}`)
    for (const k of ['order', 'range', 'last']) assert.ok(t.settings.bandsBad[k], `${lang} ${k}`)
    for (const k of ['enabled', 'manual', 'auto', 'effort', 'default_model', 'default_effort', 'max_model', 'router', 'jev_model', 'jev_bands', 'haiku_map']) {
      assert.ok(t.settings.label[k], `${lang} label ${k}`)
      assert.ok(t.settings.explain[k], `${lang} explain ${k}`)
    }
  }
})

test('launch: Standard effort goes out explicitly; a missing effort only while the effort switch is off', () => {
  const args = { keys: ['task:a'] }
  const routes = { 'task:a': { title: 'A', status: 'ok', route: ROUTE } }
  assert.deepEqual(logic.withLaunch('do_it', args, LAUNCH, { launchModel: 'sonnet', launchEffort: 'standard' }, {}), { ...args, model: 'sonnet', effort: 'standard' })
  assert.deepEqual(logic.withLaunch('do_it', args, LAUNCH, { launchEffort: 'standard' }, routes), { ...args, model: 'sonnet', effort: 'standard' })
  assert.deepEqual(logic.withLaunch('do_it', args, { ...LAUNCH, auto: false }, {}, {}), { ...args, model: 'sonnet', effort: 'standard' })
  assert.equal('effort' in logic.withLaunch('do_it', args, { ...LAUNCH, effort: false }, { launchEffort: 'standard' }, {}), false)
})

test('launch: a launch event replaces the block and clears the recommendations', () => {
  assert.match(read('api.js'), /const EVENTS = \[[^\]]*'launch'/)
  const app = read('app.js')
  assert.match(app, /\n  launch\(l\) \{\n\s+clearRoutes\(l\)\n\s+\},/)
  assert.match(app, /function clearRoutes\(launch\) \{\n\s+routeGen \+= 1\n\s+store\.set\(s => \(\{ \.\.\.s, launch: launch \?\? s\.launch, launchRoutes: \{\} \}\)\)/)
  assert.match(app, /async function freshLaunch\(r\) \{[\s\S]*?clearRoutes\(launch\)/)
})

test('launch: an answer of /api/route that comes after the cache was cleared is dropped', () => {
  const route = read('app.js').match(/launchRoute: async items => \{[\s\S]*?\n  \},/)[0]
  // the generation is taken before the request and compared after it; nothing is written for an old one
  assert.ok(route.indexOf('const gen = routeGen') < route.indexOf('await api.route(keys)'))
  assert.match(route, /const res = await api\.route\(keys\)\n\s+if \(gen !== routeGen\) return/)
  assert.match(route, /put\(k => \(\{ title: titles\.get\(k\), status: 'loading' \}\)\)/)
})

// ---------------------------------------------------------------- the daily check names the model (triage)

const CHECK_SETTINGS = {
  triage_jev: false, max_model: 'opus',
  jev_bands: [{ below: 0.75, model: 'haiku', effort: 'medium' }, { below: 1.3, model: 'sonnet', effort: 'medium' },
    { below: 1.9, model: 'sonnet', effort: 'high' }, { below: 2.6, model: 'opus', effort: 'high' }, { below: null, model: 'opus', effort: 'xhigh' }],
  haiku_map: [{ model: 'haiku', effort: 'medium' }, { model: 'sonnet', effort: 'medium' }, { model: 'sonnet', effort: 'high' }, { model: 'opus', effort: 'high' }],
}
const CHECK_LAUNCH = { enabled: true, auto: true, manual: true, effort: true, settings: CHECK_SETTINGS }

test('triage: the model the check implies, as the server reckons it (model_route.from_check)', () => {
  const pick = (tri, launch = CHECK_LAUNCH) => logic.checkPick(tri, launch)
  // Haiku's level through the Haiku levels
  assert.deepEqual(pick({ doer: 'ai', level: 2, jev: 0.3 }), { model: 'sonnet', effort: 'high' })
  assert.deepEqual(pick({ doer: 'either', level: 0, jev: null }), { model: 'haiku', effort: 'medium' })
  // with triage_jev on, Jev's score through the bands; a level stands in where Jev gave nothing
  const jevOn = { ...CHECK_LAUNCH, settings: { ...CHECK_SETTINGS, triage_jev: true } }
  assert.deepEqual(pick({ doer: 'ai', level: 0, jev: 2.0 }, jevOn), { model: 'opus', effort: 'high' })
  assert.deepEqual(pick({ doer: 'ai', level: 0, jev: 2.6 }, jevOn), { model: 'opus', effort: 'xhigh' })
  assert.deepEqual(pick({ doer: 'ai', level: 1, jev: null }, jevOn), { model: 'sonnet', effort: 'medium' })
  assert.deepEqual(pick({ doer: 'ai', level: 1, jev: 3.5 }, jevOn), { model: 'sonnet', effort: 'medium' })
  // capped at max_model
  const capped = { ...jevOn, settings: { ...jevOn.settings, max_model: 'sonnet' } }
  assert.deepEqual(pick({ doer: 'ai', level: 0, jev: 2.9 }, capped), { model: 'sonnet', effort: 'xhigh' })
  assert.deepEqual(pick({ doer: 'ai', level: 3, jev: null }, { ...CHECK_LAUNCH, settings: { ...CHECK_SETTINGS, max_model: 'haiku' } }), { model: 'haiku', effort: 'high' })
  // effort only where the effort switch is on
  assert.deepEqual(pick({ doer: 'ai', level: 2 }, { ...CHECK_LAUNCH, effort: false }), { model: 'sonnet', effort: null })
  // nothing: you do it, no number, launch or Auto off, a level out of range or not whole
  for (const [tri, launch] of [[{ doer: 'you', level: 2 }], [{ doer: 'ai', level: null, jev: null }], [{ doer: 'ai' }],
    [{ doer: 'ai', level: 2 }, { ...CHECK_LAUNCH, enabled: false }], [{ doer: 'ai', level: 2 }, { ...CHECK_LAUNCH, auto: false }],
    [{ doer: 'ai', level: 2 }, null], [{ doer: 'ai', level: 4 }], [{ doer: 'ai', level: 1.5 }], [null]]) {
    assert.equal(pick(tri, launch === undefined ? CHECK_LAUNCH : launch), null, JSON.stringify([tri, launch]))
  }
  for (const lang of ['en', 'de']) {
    const t = text.TABLES[lang]
    assert.equal(logic.checkPickText({ model: 'sonnet', effort: 'high' }, t), lang === 'de' ? 'Sonnet · hoch' : 'Sonnet · high')
    assert.equal(logic.checkPickText({ model: 'opus', effort: null }, t), 'Opus')
    // the recommendation from the check and from a STATUS.md says so
    assert.equal(logic.routeText({ ...ROUTE, routed_by: 'check', level: 2 }, t, lang), lang === 'de' ? 'Auto: Sonnet · hoch (Prüfung)' : 'Auto: Sonnet · high (check)')
    assert.equal(logic.routeText({ ...ROUTE, routed_by: 'status', level: null }, t, lang), 'Auto: Sonnet · ' + (lang === 'de' ? 'hoch' : 'high') + ' (STATUS)')
  }
  // the hint stands on the triage marks of a row
  const gist = read('triage.js').match(/export function TriageGist\([\s\S]*?\n\}/)[0]
  assert.match(gist, /const pick = checkPick\(tri, s\.launch\)/)
  assert.match(gist, /checkPickText\(pick, t\)/)
})

test('settings: the daily check may ask Jev too, a switch below Auto, grey while launch or Auto is off', () => {
  const page = read('views/settings.js')
  assert.match(page, /changedMark\('auto', l\)[\s\S]*?<\$\{LRow\} k="triage_jev"/)
  assert.match(page, /\(k === 'triage_jev' && !st\.auto\)/)
  assert.match(page, /s\.jev\?\.ready \? null : html`<span class="muted small set-aside">\$\{w\.triageJevNeedsJev\}<\/span>`/)
  for (const lang of ['en', 'de']) {
    const t = text.TABLES[lang]
    assert.ok(t.settings.label.triage_jev && t.settings.explain.triage_jev && t.settings.triageJevNeedsJev, lang)
  }
  assert.equal(text.TABLES.de.settings.label.triage_jev, 'Jev bei der täglichen Prüfung mitbewerten')
  assert.equal(text.TABLES.en.settings.label.triage_jev, 'Also ask Jev in the daily check')
  assert.deepEqual(logic.launchPatch('triage_jev', true), { triage_jev: true })
})

// ---------------------------------------------------------------- the news ticker (work/tasks/cockpit-newsticker)

/** A start page store with nothing to report: every ticker rule stays quiet on it */
function quietStore(over = {}) {
  return {
    model: { pages: [], alarms: [], status: [], stale: false, returns: [], counts: { now: 0 },
      review: { running: null, error: null, last: null } },
    tabs: { tabs: [], error: null }, sessions: { sessions: [] }, agents: { peers: [], convs: [] },
    triage: { running: null, error: null }, loading: { pass: null, last_error: null },
    relay: { enabled: false, online: false }, jev: { enabled: false, ready: false }, notes: [], conn: 'open',
    workers: { status: 'idle', data: null },
    ticker: { enabled: true, settings: { status: { enabled: true, kinds: [...logic.TICKER_KINDS] } }, items: [],
      perf: { passes: [], outliers: [] }, limits: { timeout_ms: 120000 } },
    ...over,
  }
}

/** The one status item a store gives, by key */
const statusOf = (s, key) => logic.tickerStatus(s, NOW, logic.TICKER_KINDS).filter(x => x.key === key)

test('ticker: a quiet store says nothing; the kinds are the seven of the contract', () => {
  assert.deepEqual(logic.TICKER_KINDS, ['running', 'waiting', 'slow', 'failing', 'quota', 'offline', 'notes'])
  assert.deepEqual(logic.tickerStatus(quietStore(), NOW, logic.TICKER_KINDS), [])
})

test('ticker: each status rule names its kind, tone and where a click leads', () => {
  const mk = over => quietStore(over)
  const model = extra => ({ ...quietStore().model, ...extra })
  const one = (s, key) => { const l = statusOf(s, key); assert.equal(l.length, 1, key); return l[0] }
  const check = (s, key, cat, tone, target) => {
    const it = one(s, key)
    assert.equal(it.cat, cat, key); assert.equal(it.tone, tone, key)
    if (target !== undefined) assert.deepEqual(it.target, target, key)
    return it
  }
  // 1 alarms
  check(mk({ model: model({ alarms: [{ page_id: 'systems', page_title: 'Systems', section_title: 'Checks', count: 1 }] }) }),
    'alarm', 'failing', 'bad', { kind: 'page', id: 'systems' })
  // 2 quota meters: bad at the bad mark, warn at the warn mark or when the pace runs over
  const quota = (value, elapsed = 0.9) => model({ pages: [{ id: 'usage', sections: [{ id: 'quota',
    items: [{ title: 'Week: 1 %', meter: { value, max: 100, unit: '%', elapsed, warn: 80, bad: 95, window_h: 168 } }] }] }] })
  const qb = check(mk({ model: quota(96) }), 'quota', 'quota', 'bad')
  assert.equal(qb.target.kind, 'info'); assert.equal(qb.target.page, 'usage'); assert.equal(qb.target.section, 'quota')
  check(mk({ model: quota(82) }), 'quota', 'quota', 'warn')
  check(mk({ model: quota(40, 0.2) }), 'quota', 'quota', 'warn')          // 40 % after a fifth of the window runs over
  assert.equal(statusOf(mk({ model: quota(40, 0.6) }), 'quota').length, 0)
  // 3 token outliers
  check(mk({ ticker: { ...quietStore().ticker, perf: { passes: [], outliers: [{ source: 'subagent', today: 9, usual: 2, factor: 4.5 }] } } }),
    'outlier', 'quota', 'warn', { kind: 'page', id: '@sessions' })
  // 4 a failed pass, 5 a pass that runs far longer than its estimate
  check(mk({ loading: { pass: null, last_error: { message: 'boom' } } }), 'loadFailed', 'failing', 'bad', { kind: 'page', id: 'briefing' })
  check(mk({ loading: { pass: 'full', started_ms: NOW - 40000, eta_ms: 10000 } }), 'loadSlow', 'slow', 'warn', null)
  assert.equal(statusOf(mk({ loading: { pass: 'full', started_ms: NOW - 20000, eta_ms: 10000 } }), 'loadSlow').length, 0)
  // 6 the last pass: near the time limit bad, over a minute warn
  const pass = took => mk({ ticker: { ...quietStore().ticker, perf: { passes: [{ kind: 'full', took_ms: 1000, ok: true }, { kind: 'full', took_ms: took, ok: true }], outliers: [] } } })
  check(pass(110000), 'passSlow', 'slow', 'bad', { kind: 'page', id: 'briefing' })
  check(pass(95000), 'passSlow', 'slow', 'warn')
  assert.equal(statusOf(pass(30000), 'passSlow').length, 0)
  // 7 a source in error: slow when it ran out of time, else failing
  check(mk({ model: model({ status: [{ title: 'Mail', state: 'error', reason: 'took longer than 60 s' }] }) }), 'sourceSlow', 'slow', 'warn', { kind: 'page', id: 'briefing' })
  check(mk({ model: model({ status: [{ title: 'Mail', state: 'error', reason: 'token expired' }] }) }), 'sourceFailed', 'failing', 'bad')
  // 8 stale, 9 connection down, 10 tabs unreadable
  check(mk({ model: model({ stale: true }) }), 'stale', 'failing', 'warn', null)
  check(mk({ conn: 'down' }), 'connDown', 'offline', 'bad', null)
  check(mk({ tabs: { tabs: [], error: 'no cmux' } }), 'tabsError', 'failing', 'bad', { kind: 'drawer', id: 'tabs' })
  // 11 to 13 the agent tabs
  const tab = (ref, state, extra = {}) => ({ ref, name: ref, state, waiting: false, long: null, is_control: false, ...extra })
  check(mk({ tabs: { tabs: [tab('a', 'waiting', { long: 'waiting' })] } }), 'tabLong', 'slow', 'warn', { kind: 'tab', ref: 'a' })
  check(mk({ tabs: { tabs: [tab('a', 'needs-you', { waiting: true })] } }), 'tabWaits', 'waiting', 'warn', { kind: 'tab', ref: 'a' })
  const three = mk({ tabs: { tabs: ['a', 'b', 'c'].map(r => tab(r, 'working')) } })
  assert.equal(statusOf(three, 'tabWorks').length, 3)
  assert.deepEqual(statusOf(three, 'tabWorks')[0].target, { kind: 'tab', ref: 'a' })
  const four = mk({ tabs: { tabs: ['a', 'b', 'c', 'd'].map(r => tab(r, 'working')) } })
  assert.equal(statusOf(four, 'tabWorks').length, 0)
  const many = check(four, 'tabsWork', 'running', 'info', { kind: 'drawer', id: 'tabs' })
  assert.deepEqual(many.vars, [4])
  assert.equal(statusOf(mk({ tabs: { tabs: [tab('c', 'working', { is_control: true })] } }), 'tabWorks').length, 0)   // the control tab is not news
  // 14 sessions at work
  const ss = check(mk({ sessions: { sessions: [{ status: 'busy', agents: { running_count: 2 }, workflows: [{}] }, { status: 'idle' }] } }),
    'sessions', 'running', 'info', { kind: 'page', id: '@sessions' })
  assert.deepEqual(ss.vars, [1, 3])
  assert.equal(statusOf(mk({ sessions: { sessions: [{ status: 'idle' }] } }), 'sessions').length, 0)
  // 15 the return channel, by live stage
  const ret = (stage, extra = {}) => mk({ model: model({ returns: [{ key: 'task:x', title: 'X', stage, at_ms: NOW - 1000, item: 'x', ...extra }] }) })
  check(ret('started'), 'returnWorks', 'running', 'info', { kind: 'row', key: 'task:x' })
  check(ret('result'), 'returnResult', 'waiting', 'ok')
  check(mk({ ...ret('started', { tab: { ref: 't1' } }), tabs: { tabs: [tab('t1', 'needs-you')] } }), 'returnAsks', 'waiting', 'warn', { kind: 'tab', ref: 't1' })
  check(ret('started', { at_ms: NOW - 600000 }), 'returnLost', 'failing', 'warn')
  // a tab that is gone is no target: the row opens instead; an answer that is there opens the answer
  check(ret('started', { at_ms: NOW - 600000, tab: { ref: 'gone' } }), 'returnLost', 'failing', 'warn', { kind: 'row', key: 'task:x' })
  check(ret('result', { tab: { ref: 'gone' }, result: { key: 'inbox:a1', text: 'done' } }), 'returnResult', 'waiting', 'ok', { kind: 'item', key: 'inbox:a1' })
  check(mk({ ...ret('result', { tab: { ref: 't1' } }), tabs: { tabs: [tab('t1', 'waiting')] } }), 'returnResult', 'waiting', 'ok', { kind: 'tab', ref: 't1' })
  assert.equal(logic.tickerStatus(ret('done'), NOW, logic.TICKER_KINDS).length, 0)
  // 16 what waits on you
  check(mk({ model: model({ counts: { now: 2 } }) }), 'waitsForYou', 'waiting', 'warn', { kind: 'page', id: 'briefing' })
  // 17 the task check
  const rv = review => mk({ model: model({ review }) })
  check(rv({ running: { started_ms: NOW }, error: null, last: null }), 'reviewRuns', 'running', 'info', { kind: 'review' })
  check(rv({ running: null, error: 'boom', last: null }), 'reviewFailed', 'failing', 'bad', { kind: 'review' })
  check(rv({ running: null, error: null, last: { to_close: 2 } }), 'toClose', 'waiting', 'info', { kind: 'review' })
  // 18 the daily check
  check(mk({ triage: { running: { started_ms: NOW } } }), 'triageRuns', 'running', 'info', { kind: 'page', id: 'briefing' })
  check(mk({ triage: { running: null, error: 'boom' } }), 'triageFailed', 'failing', 'bad')
  // 19 and 20 the agents
  check(mk({ agents: { peers: [{ id: 'peer-a', name: 'Peer A', reach: 'unreachable' }], convs: [] } }), 'peerDown', 'offline', 'warn', { kind: 'page', id: '@agents' })
  assert.equal(statusOf(mk({ agents: { peers: [{ id: 'peer-a', reach: 'ok' }], convs: [] } }), 'peerDown').length, 0)
  check(mk({ agents: { peers: [], convs: [{ id: 'c1', peer: 'peer-a', running: true, started_ms: NOW - 200000, turns: [{ q: 'x', at_ms: NOW - 200000 }] }] } }),
    'convSlow', 'slow', 'warn', { kind: 'conv', id: 'c1' })
  check(mk({ agents: { peers: [], convs: [{ id: 'c1', peer: 'peer-a', running: false, turns: [{ q: 'x', waiting: true }] }] } }),
    'convWaits', 'waiting', 'warn', { kind: 'conv', id: 'c1' })
  // 21 background jobs
  const runs = list => mk({ workers: { status: 'ok', data: { runs: list } } })
  check(runs([{ id: 'j', title: 'j', state: 'absent', strip: [] }]), 'jobFailed', 'failing', 'bad', { kind: 'workers' })
  check(runs([{ id: 'j', title: 'j', state: 'in_sync', strip: [{ verdict: 'ok' }, { verdict: 'failed' }] }]), 'jobFailed', 'failing', 'bad')
  check(runs([{ id: 'j', title: 'j', state: 'drifted', strip: [] }]), 'jobWarn', 'failing', 'warn')
  assert.equal(statusOf(runs([{ id: 'j', title: 'j', state: 'in_sync', strip: [{ verdict: 'ok' }] }]), 'jobFailed').length, 0)
  // 22 machines, clouds and LLM sources that are down
  const items = list => mk({ model: model({ pages: [{ id: 'sys', sections: [{ id: 'res', items: list }] }] }) })
  const off = check(items([{ id: 'machine:box', title: 'box', tone: 'bad' }]), 'offline', 'offline', 'bad')
  assert.equal(off.target.kind, 'info')
  assert.equal(statusOf(items([{ id: 'llm:openai:error', title: 'OpenAI', tone: 'bad' }]), 'offline').length, 1)
  assert.equal(statusOf(items([{ id: 'machine:box', title: 'box', tone: 'ok' }, { id: 'other:x', title: 'x', tone: 'bad' }]), 'offline').length, 0)
  // 23 Jev, 24 the control session, 25 notes
  check(mk({ jev: { enabled: true, ready: false } }), 'jevNotReady', 'failing', 'warn', { kind: 'page', id: '@jev' })
  check(mk({ relay: { enabled: true, online: false } }), 'controlOffline', 'offline', 'warn', { kind: 'claude' })
  const fresh = NOW - 60000
  const notes = statusOf(mk({ notes: [{ text: 'a', tone: 'bad', ms: fresh }, { text: 'b', tone: 'ok', ms: fresh }, { text: 'c', tone: 'warn', ms: fresh },
    { text: 'd', tone: 'warn', ms: fresh }, { text: 'e', tone: 'bad', ms: fresh }] }), 'note')
  assert.deepEqual(notes.map(n => n.vars[0]), ['c', 'd', 'e'])
  // only recent notes are news: an old one, and a server note replayed with ms 0, stay out of the band
  const aged = statusOf(mk({ notes: [{ text: 'old', tone: 'bad', ms: NOW - 16 * 60000 }, { text: 'replayed', tone: 'bad', ms: 0 },
    { text: 'nomark', tone: 'warn' }, { text: 'new', tone: 'warn', ms: NOW - 14 * 60000 }] }), 'note')
  assert.deepEqual(aged.map(n => n.vars[0]), ['new'])
  assert.equal(notes[0].cat, 'notes'); assert.equal(notes[2].tone, 'bad'); assert.equal(notes[0].target, null)
  // the kinds filter leaves out whole categories
  const loud = mk({ conn: 'down', model: model({ counts: { now: 2 } }) })
  assert.deepEqual(logic.tickerStatus(loud, NOW, ['offline']).map(x => x.key), ['connDown'])
  assert.deepEqual(logic.tickerStatus(loud, NOW, []).map(x => x.key), [])
  // every key has a text in both languages, and the ids are unique
  const all = logic.tickerStatus(mk({ conn: 'down', model: model({ counts: { now: 2 }, stale: true }), notes: [{ text: 'n', tone: 'bad', ms: NOW }] }), NOW, logic.TICKER_KINDS)
  assert.equal(all.filter(x => x.key === 'note').length, 1)
  assert.equal(new Set(all.map(x => x.id)).size, all.length)
  for (const lang of ['en', 'de']) {
    for (const it of all) assert.ok(logic.tickerText(it, text.TABLES[lang]).length > 0, `${lang} ${it.key}`)
  }
})

test('ticker: a page target opens pages the controller routes itself, Today only for a name nowhere', () => {
  const s = quietStore({ model: { ...quietStore().model, pages: [{ id: 'work', group: 'work' }, { id: 'day1', group: 'day' }, { id: 'systems' }] } })
  const order = ['briefing', 'systems', '@sessions']
  assert.equal(logic.tickerPage(s, 'systems', order), 'systems')
  assert.equal(logic.tickerPage(s, 'work', order), 'work')         // a work page: setPage opens its view of the work tab
  assert.equal(logic.tickerPage(s, 'day1', order), 'day1')         // a day page: setPage opens Today itself
  assert.equal(logic.tickerPage(s, '@jev', order), '@jev')         // Jev, wherever it lives
  assert.equal(logic.tickerPage(s, '@sessions', order), '@sessions')
  assert.equal(logic.tickerPage(s, 'gone', order), 'briefing')
  assert.equal(logic.tickerPage({ model: null }, 'gone', []), 'briefing')
  const tk = read('views/ticker.js')
  assert.match(tk, /case 'page': return c\.setPage\(tickerPage\(s, target\.id, pageOrder\(s\)\)\)/)
  assert.match(tk, /case 'item': return c\.openItem\(target\.key, null\)/)
})

test('ticker: an older ticker state never replaces a newer one; refresh and edit answers leave the store to the event', () => {
  assert.equal(logic.newerTicker(null, { rev: 1 }), true)
  assert.equal(logic.newerTicker({ rev: 5 }, { rev: 4 }), false)
  assert.equal(logic.newerTicker({ rev: 5 }, { rev: 5 }), true)
  assert.equal(logic.newerTicker({ rev: 5 }, { rev: 6 }), true)
  assert.equal(logic.newerTicker({}, {}), true)                   // a server without rev: last one wins
  assert.equal(logic.newerTicker({ rev: 5 }, null), false)
  const app = read('app.js')
  assert.match(app, /ticker\(tk\) \{\n\s+store\.set\(s => \(newerTicker\(s\.ticker, tk\) \? \{ \.\.\.s, ticker: tk \} : s\)\)/)
  assert.match(app, /if \(newerTicker\(s\.ticker, r\?\.ticker\)\)/)
  // the answer of a refresh or an edit may arrive after the event that ended it: its state is not stored
  assert.match(app, /tickerRefresh: async \(\) => act\('ticker_refresh', \{\}\),/)
  assert.match(app, /tickerEdit: async \(\) => act\('ticker_edit', \{\}\),/)
})

test('ticker: items put bad before warn before info before ok, then the feeds; empty while off', () => {
  const feed = { id: 'f1', feed: 'demo', source: 'Demo', title: 'News', short: null, url: 'https://example.org/a', published_ms: NOW, fresh: false }
  const s = quietStore({ conn: 'down', model: { ...quietStore().model, counts: { now: 1 }, review: { running: { started_ms: NOW }, last: { to_close: 0 } },
    returns: [{ key: 'task:x', title: 'X', stage: 'result', at_ms: NOW }] } })
  s.ticker = { ...s.ticker, items: [feed, { ...feed, id: 'f2', url: 'javascript:alert(1)' }, feed] }
  const list = logic.tickerItems(s, NOW)
  assert.deepEqual(list.map(x => x.tone ?? 'feed'), ['bad', 'warn', 'info', 'ok', 'feed'])
  assert.equal(list.at(-1).kind, 'feed'); assert.equal(list[0].kind, 'status')
  assert.equal(list.filter(x => x.kind === 'feed').length, 1)                       // a bad link and a twin drop out
  assert.deepEqual(logic.tickerItems({ ...s, ticker: { ...s.ticker, enabled: false } }, NOW), [])
  assert.deepEqual(logic.tickerItems({ ...s, ticker: null }, NOW), [])
  const noStatus = { ...s, ticker: { ...s.ticker, settings: { status: { enabled: false, kinds: [...logic.TICKER_KINDS] } } } }
  assert.deepEqual(logic.tickerItems(noStatus, NOW).map(x => x.kind), ['feed'])
  const onlyWaiting = { ...s, ticker: { ...s.ticker, settings: { status: { enabled: true, kinds: ['waiting'] } } } }
  assert.ok(logic.tickerItems(onlyWaiting, NOW).filter(x => x.kind === 'status').every(x => x.cat === 'waiting'))
})

test('ticker: status and news split; the status list keeps the band order, the news only feeds', () => {
  const s = quietStore()
  s.conn = 'down'
  s.model = { ...s.model, counts: { now: 2 } }
  const feed = { id: 'f1', feed: 'demo-ai', source: 'Demo', title: 'T', url: 'https://example.org/a' }
  s.ticker = { ...s.ticker, items: [feed, { ...feed, id: 'f2', url: 'javascript:alert(1)' }] }
  const all = logic.tickerItems(s, NOW)
  assert.deepEqual(logic.tickerStatusItems(s, NOW), all.filter(x => x.kind === 'status'))
  assert.deepEqual(logic.tickerStatusItems(s, NOW).map(x => x.tone), ['bad', 'warn'])
  assert.deepEqual(logic.tickerFeedItems(s).map(x => x.id), ['f1'])
  assert.ok(logic.tickerFeedItems(s).every(x => x.kind === 'feed'))
  assert.deepEqual(logic.tickerStatusItems({ ...s, ticker: { ...s.ticker, enabled: false } }, NOW), [])
  assert.deepEqual(logic.tickerFeedItems({ ...s, ticker: { ...s.ticker, enabled: false } }), [])
  assert.deepEqual(logic.tickerStatusItems({ ...s, ticker: { ...s.ticker, settings: { status: { enabled: false } } } }, NOW), [])
  assert.deepEqual(logic.tickerStatusItems({ ...s, ticker: { ...s.ticker, settings: { status: { enabled: true, kinds: [] } } } }, NOW), [])
  assert.deepEqual(logic.tickerStatusItems({ ...s, ticker: null }, NOW), [])
})

/** The palette the server renders as /colors.css, resolved by design.py itself (fallback chain, dark set), so
 *  the test reads a DESIGN.md exactly as the page does. BRIDGE_DESIGN_MD points it at another DESIGN.md, e.g.
 *  the generic open-bridge one: BRIDGE_DESIGN_MD=/path/to/DESIGN.md node --test scripts/tests/<this file> */
function serverPalette() {
  const file = process.env.BRIDGE_DESIGN_MD || path.join(ROOT, 'DESIGN.md')
  const code = 'import json, sys\nfrom pathlib import Path\nfrom bridge_cockpit import design\n'
    + 'print(json.dumps(design.palette(design.front_matter(Path(sys.argv[1])))))'
  const out = execFileSync('python3', ['-c', code, file], {
    cwd: path.join(ROOT, 'scripts', 'lib'), encoding: 'utf8',
    env: { ...process.env, PYTHONPATH: path.join(ROOT, 'scripts', 'lib') },
  })
  return JSON.parse(out)
}

test('ticker: a feed keeps its source colour, one of three non-state tokens, the same on every load', () => {
  const ids = ['demo-ai', 'demo-research', 'demo-tools', 'openai', 'huggingface', 'tech-review', 'a', 'b']
  for (const id of ids) {
    assert.ok(logic.TICKER_SOURCE_TOKENS.includes(logic.tickerSourceToken(id)), id)
    assert.equal(logic.tickerSourceToken(id), logic.tickerSourceToken(id))
  }
  assert.ok(logic.TICKER_SOURCE_TOKENS.includes(logic.tickerSourceToken(undefined)))
  // the tokens look different in both modes once design.py has resolved the palette: a DESIGN.md that names
  // few keys (the generic open-bridge one has no colorsDark and no border-strong) falls back along CHAIN,
  // and two tokens that land on the same key would show one colour
  const pal = serverPalette()
  for (const mode of ['light', 'dark']) {
    const hex = logic.TICKER_SOURCE_TOKENS.map(k => pal[mode][k]?.toUpperCase())
    assert.ok(hex.every(Boolean), `${mode}: every token is in the palette`)
    assert.equal(new Set(hex).size, hex.length, `${mode}: the source tokens differ (${hex.join(', ')})`)
  }
  // no state tone (DESIGN.md: state colours only where the data IS a state): a source never reads as ok or a warning
  for (const k of logic.TICKER_SOURCE_TOKENS) assert.ok(!['danger', 'warning', 'success', 'info'].includes(k), k)
  // a palette may put secondary and accent close together, so each token tints its chip to a strength of its own
  const css = read('style.css')
  const mix = logic.TICKER_SOURCE_TOKENS.map(k => {
    const m = css.match(new RegExp(`\\.ticker-src\\.tk-${k} \\{ --tk: var\\(--${k}\\); --tk-mix: (\\d+)%; \\}`))
    assert.ok(m, k)
    return m[1]
  })
  assert.equal(new Set(mix).size, mix.length, 'each token its own tint strength')
  // the colour sits in a dot before the source's name, the name itself the surface's muted text
  assert.match(css, /\.ticker-src::before \{[^}]*background: var\(--tk, var\(--border-strong\)\)/)
  assert.match(read('views/ticker.js'), /ticker-src tk-\$\{tickerSourceToken\(it\.feed \?\? it\.source, order\)\}/)
})

test('ticker: the configured feeds take the source colours in turn, so the default feeds spread evenly', () => {
  // the ids the server ships when bridge-config.yaml names no feeds
  const py = fs.readFileSync(path.join(ROOT, 'scripts', 'lib', 'bridge_cockpit', 'ticker.py'), 'utf8')
  const defaults = py.slice(py.indexOf('DEFAULT_FEEDS = ['), py.indexOf(']', py.indexOf('DEFAULT_FEEDS = [')))
  const ids = [...defaults.matchAll(/"id": "([^"]+)"/g)].map(m => m[1])
  assert.ok(ids.length >= 4, ids.join(','))
  const n = logic.TICKER_SOURCE_TOKENS.length
  const tokens = ids.map(id => logic.tickerSourceToken(id, ids))
  // every round of n feeds uses every token once
  for (let i = 0; i + n <= ids.length; i += n) assert.equal(new Set(tokens.slice(i, i + n)).size, n, tokens.join(','))
  const counts = Object.values(tokens.reduce((a, k) => ({ ...a, [k]: (a[k] ?? 0) + 1 }), {}))
  assert.ok(Math.max(...counts) - Math.min(...counts) <= 1, tokens.join(','))
  // the same order gives the same colours, an id outside it keeps its plain hash
  assert.deepEqual(ids.map(id => logic.tickerSourceToken(id, [...ids])), tokens)
  assert.equal(logic.tickerSourceToken('elsewhere', ids), logic.tickerSourceToken('elsewhere'))
  // the demo's three feeds take three different colours
  const demo = ['demo-ai', 'demo-research', 'demo-tools']
  assert.equal(new Set(demo.map(id => logic.tickerSourceToken(id, demo))).size, 3)
  // the band passes the configured order, disabled feeds included, so switching one off moves no colour
  assert.match(read('views/ticker.js'), /const order = \(tk\?\.settings\?\.feeds \?\? \[\]\)\.map\(f => f\.id\)/)
})

test('ticker: duration clamps, a patch sends whole sub blocks, a feed is checked like the server does', () => {
  assert.equal(logic.tickerDuration(7000, 'normal'), 100)
  assert.equal(logic.tickerDuration(100, 'fast'), 20)
  assert.equal(logic.tickerDuration(1e6, 'slow'), 600)
  assert.equal(logic.tickerDuration(4000, 'slow'), 100)
  assert.equal(logic.tickerDuration(4000, 'unknown'), logic.tickerDuration(4000, 'normal'))
  const cur = { enabled: true, speed: 'normal', status: { enabled: true, kinds: ['running'] }, editor: { enabled: true, interests: '', max_picks: 12, shorten: true } }
  assert.deepEqual(logic.tickerPatch('enabled', false, cur), { enabled: false })
  assert.deepEqual(logic.tickerPatch('speed', 'fast', cur), { speed: 'fast' })
  assert.deepEqual(logic.tickerPatch('editor.interests', '  agents ', cur), { editor: { enabled: true, interests: 'agents', max_picks: 12, shorten: true } })
  assert.deepEqual(logic.tickerPatch('status.kinds', ['slow'], cur), { status: { enabled: true, kinds: ['slow'] } })
  assert.deepEqual(logic.tickerPatch('feeds', [{ id: ' a ', name: ' A ', url: ' https://example.org/f ', enabled: true }], cur),
    { feeds: [{ id: 'a', name: 'A', url: 'https://example.org/f', enabled: true }] })
  const ok = { id: 'demo-1', name: 'Demo', url: 'https://example.org/feed.xml', enabled: true }
  assert.equal(logic.tickerFeedValid(ok), true)
  assert.equal(logic.tickerFeedValid({ ...ok, url: 'http://example.org/rss' }), true)
  for (const url of ['javascript:alert(1)', 'ftp://example.org/x', 'https://user:pw@example.org/x', 'https://user@example.org/x',
    'file:///etc/passwd', 'https://exa mple.org/', '', 'not a url', `https://example.org/${'a'.repeat(500)}`]) {
    assert.equal(logic.tickerFeedValid({ ...ok, url }), false, url)
  }
  for (const id of ['', 'Demo', '-a', 'a_b', 'a'.repeat(41)]) assert.equal(logic.tickerFeedValid({ ...ok, id }), false, id)
  for (const name of ['', ' ', 'x'.repeat(61), 'a\u0007b']) assert.equal(logic.tickerFeedValid({ ...ok, name }), false, JSON.stringify(name))
  assert.equal(logic.tickerFeedValid(null), false)
})

/** The source of each call of fn(...) in src, its parentheses balanced */
function callBodies(src, fn) {
  const out = []
  for (const m of src.matchAll(new RegExp(`\\b${fn}\\(`, 'g'))) {
    let depth = 0
    let i = m.index + m[0].length - 1
    for (; i < src.length; i += 1) {
      if (src[i] === '(') depth += 1
      else if (src[i] === ')') { depth -= 1; if (depth === 0) break }
    }
    out.push(src.slice(m.index, i + 1))
  }
  return out
}

test('ticker: wired into both start page layouts, the store, the events; links open safely; Haiku only on a click', () => {
  const home = read('views/home.js')
  assert.match(home, /import \{ TickerBand, TickerStatusList \} from '\.\/ticker\.js'/)
  // on the stage the news run beside the greeting, inside .stage-term; nothing of the ticker under the circle
  const stage = read('views/stage.js')
  assert.match(stage, /import \{ TickerBand, TickerStatusList \} from '\.\/ticker\.js'/)
  const term = stage.slice(stage.indexOf('<div class="stage-term">'), stage.indexOf('<div class="stage-body">'))
  assert.ok(term.length > 0, 'stage-term stands before stage-body')
  assert.match(term, /<\$\{TickerBand\} s=\$\{s\} c=\$\{c\} only="news" \/>/)
  assert.match(term, /<div class="stage-greet">[\s\S]*?<\$\{StagePrompt\}/)
  assert.match(term, /<div class="stage-tools">/)
  assert.doesNotMatch(stage.slice(stage.indexOf('<div class="stage-body">')), /TickerBand/)
  // the status stands still in the live section of the side card, above the live feed
  assert.match(stage, /<div class="feed">\n\s+<h3 class="label-caps feed-head">[^\n]*<\/h3>\n\s+<\$\{TickerStatusList\} s=\$\{s\} c=\$\{c\} \/>\n\s+\$\{\(s\.feed/)
  // under status rows the live feed does not say "quiet": a short line of its own, the long one only when both are empty
  assert.match(stage, /: tickerStatusItems\(s, s\.now \|\| Date\.now\(\)\)\.length \? html`<p class="stage-row-sub">\$\{h\.liveQuiet\}<\/p>`\n\s+: html`<p class="stage-row-sub">\$\{h\.liveEmpty\}<\/p>`/)
  for (const lang of ['en', 'de']) {
    const q = text.TABLES[lang].home.liveQuiet
    assert.equal(typeof q, 'string', lang)
    assert.ok(q.length < text.TABLES[lang].home.liveEmpty.length / 2, lang)
    assert.doesNotMatch(q, /^(Quiet|Ruhig)/, lang)
  }
  // the tiles view: the news under the greeting, the status under the news
  assert.match(home, /<\/header>\n\s+<\$\{TickerBand\} s=\$\{s\} c=\$\{c\} only="news" \/>\n\s+<\$\{TickerStatusList\} s=\$\{s\} c=\$\{c\} \/>\n\s+\$\{chips\}/)
  assert.doesNotMatch(home, /home bridge-home`\}>\n\s+<\$\{TickerBand\}/)
  const tk = read('views/ticker.js')
  assert.match(tk, /export function TickerBand\(\{ s, c, only \}\)/)
  assert.match(tk, /export function TickerStatusList\(\{ s, c \}\)/)
  assert.match(tk, /const STATUS_MAX = 6\b/)
  assert.match(tk, /export function TickerSettings\(\{ s, c \}\)/)
  for (const a of tk.matchAll(/<a [^>]*>/g)) {
    assert.match(a[0], /target="_blank"/, a[0]); assert.match(a[0], /rel="noopener noreferrer"/, a[0])
  }
  assert.ok([...tk.matchAll(/<a [^>]*>/g)].length >= 1)
  assert.doesNotMatch(tk, /window\.open|style=/)
  assert.match(tk, /aria-hidden="true" inert/)
  assert.match(read('api.js'), /const EVENTS = \[[^\]]*'ticker'[^\]]*\]/)
  const app = read('app.js')
  assert.match(app, /ticker: payload\.ticker \?\? s\.ticker/)
  assert.match(app, /ticker: null,/)
  assert.match(app, /ticker\(tk\) \{/)
  for (const verb of ['ticker_settings', 'ticker_settings_reset', 'ticker_refresh', 'ticker_edit']) assert.match(app, new RegExp(`act\\('${verb}'`))
  for (const src of [tk, app]) {
    for (const fn of ['useEffect', 'setInterval', 'setTimeout']) {
      for (const body of callBodies(src, fn)) assert.doesNotMatch(body, /tickerEdit|ticker_edit|\/api\/ticker/, body.slice(0, 80))
    }
  }
  assert.match(tk, /onClick=\$\{\(\) => c\.tickerEdit\(\)\}/)
  const css = read('style.css')
  assert.match(css, /@keyframes ticker-run/)
  assert.doesNotMatch(css, /\.stage-body > \.ticker|\.stage-body > \.stage-side/)
  // two columns only where the stage is wide, by the home container, never the viewport
  assert.match(css, /@container home \(min-width: \d+px\) \{[^}]*\.stage-term \{[^}]*grid-template-columns/)
  assert.match(css, /\.stage-term > \.ticker \{[^}]*min-width: 0/)
  assert.match(css, /\.ticker-src::before \{[^}]*var\(--tk/)
  assert.match(css, /\.ticker-status-list \{/)
  assert.match(css, /@media \(prefers-reduced-motion: reduce\) \{[^}]*\.ticker-track \{[^}]*animation: none/)
  // hover, keyboard focus and the Pause button (WCAG 2.2.2) all stop the band
  assert.match(css, /\.ticker:hover \.ticker-track, \.ticker:focus-within \.ticker-track, \.ticker\.is-paused \.ticker-track \{ animation-play-state: paused; \}/)
  for (const lang of ['en', 'de']) {
    const t = text.TABLES[lang].ticker
    for (const k of ['label', 'edit', 'editing', 'refresh', 'refreshing', 'fresh', 'newsLabel', 'statusLabel', 'less']) assert.ok(t[k], `${lang} ${k}`)
    assert.match(t.more(3), /3/)
    assert.match(t.settings.explain.enabled, lang === 'de' ? /Begrüßung/ : /greeting/)
    for (const k of logic.TICKER_KINDS) assert.ok(t.settings.kind[k], `${lang} kind ${k}`)
    for (const k of ['enabled', 'speed', 'max_items', 'per_feed', 'refresh_minutes', 'feeds', 'status', 'kinds', 'interests', 'max_picks', 'shorten']) {
      assert.ok(t.settings.label[k], `${lang} label ${k}`); assert.ok(t.settings.explain[k], `${lang} explain ${k}`)
    }
  }
})

test('ticker: the demo saves and resets its settings, refreshes and edits with invented titles', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'bridge-cockpit-ticker-'))
  try {
    fs.cpSync(WEB, path.join(dir, 'web'), { recursive: true })
    fs.writeFileSync(path.join(dir, 'web', 'package.json'), '{"type":"module"}')
    const mock = await import(pathToFileURL(path.join(dir, 'web', 'mock.js')).href)
    const st0 = mock.buildState()
    assert.equal(st0.ticker.enabled, true)
    assert.ok(st0.ticker.items.length >= 3)
    assert.ok(st0.ticker.perf.passes.some(p => p.took_ms === 95000))
    assert.equal(typeof st0.ticker.rev, 'number')             // like the server: newerTicker compares it
    const revs = []
    const tr = mock.createMockTransport({ lang: 'en' })
    const events = []
    tr.events(new Proxy({}, { get: (_, name) => p => events.push([name, p]) }), () => {})
    let r = await tr.post('/api/action', { verb: 'ticker_settings', args: { settings: { speed: 'fast' } } })
    assert.equal(r.ok, true)
    assert.equal(r.data.ticker.settings.speed, 'fast')
    revs.push(r.data.ticker.rev)
    let st = (await tr.get('/api/state')).data
    assert.deepEqual(st.ticker.overridden, ['speed'])
    await tr.post('/api/action', { verb: 'ticker_settings_reset', args: {} })
    st = (await tr.get('/api/state')).data
    assert.deepEqual(st.ticker.overridden, [])
    assert.equal(st.ticker.settings.speed, 'normal')
    revs.push(st.ticker.rev)
    r = await tr.post('/api/action', { verb: 'ticker_refresh', args: {} })
    assert.equal(r.data.ticker.refreshing, true)
    revs.push(r.data.ticker.rev)
    r = await tr.post('/api/action', { verb: 'ticker_edit', args: {} })
    assert.ok(r.data.ticker.editor.running)
    revs.push(r.data.ticker.rev)
    await new Promise(res => setTimeout(res, 2800))
    const last = events.filter(([n]) => n === 'ticker').at(-1)?.[1]
    assert.ok(last, 'a ticker event came')
    assert.equal(last.editor.running, null)
    assert.ok(last.editor.last && last.editor.last.picked > 0)
    assert.ok(last.items.some(x => x.short))
    assert.equal(last.refreshing, false)
    revs.push(last.rev)
    assert.ok(revs.every((v, i) => typeof v === 'number' && (i === 0 || v > revs[i - 1])), revs.join(','))
    // each later state passes newerTicker over the earlier one, never the other way round
    assert.ok(logic.newerTicker({ rev: revs[0] }, { rev: revs.at(-1) }) && !logic.newerTicker({ rev: revs.at(-1) }, { rev: revs[0] }))
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
})

// Every route the server answers, read from its source: what the page may ask, the mock answers too.
// /api/events is the event stream (the transport's events()), /api/health is for scripts, never the page.
const MOCK_ROUTE_ALLOW = new Set(['GET /api/events', 'GET /api/health'])

// Reads the routes out of the handler source. A route the class misses would be skipped in silence,
// so every `path == "/api/` and every jev route literal must come out as a route, or the reader throws.
function extractRoutes(server, jev) {
  const postAt = server.indexOf('    def post(self)')
  assert.ok(postAt > 0, 'server.py has its post handler')
  const out = []
  for (const m of server.matchAll(/path == "(\/api\/[a-z0-9_/-]+)"/g)) out.push(`${m.index < postAt ? 'GET' : 'POST'} ${m[1]}`)
  const written = server.split('path == "/api/').length - 1
  assert.equal(out.length, written, `server.py has ${written} route comparisons, ${out.length} read: a route the reader cannot read`)
  const jevRoutes = jev.match(/if path not in \(([^)]*)\)/)
  assert.ok(jevRoutes, 'jev.py names its routes')
  const jevOut = [...jevRoutes[1].matchAll(/"(\/api\/jev\/[a-z0-9_/-]+)"/g)].map(m => `POST ${m[1]}`)
  const jevWritten = jevRoutes[1].split('"/api/').length - 1
  assert.equal(jevOut.length, jevWritten, `jev.py names ${jevWritten} routes, ${jevOut.length} read: a route the reader cannot read`)
  return [...new Set([...out, ...jevOut])]
}

function serverRoutes() {
  const server = fs.readFileSync(path.join(ROOT, 'scripts', 'lib', 'bridge_cockpit', 'server.py'), 'utf8')
  const jev = fs.readFileSync(path.join(ROOT, 'scripts', 'lib', 'bridge_cockpit', 'jev.py'), 'utf8')
  return extractRoutes(server, jev)
}

test('mock parity: the route reader sees every route spelling, and refuses one it cannot read', () => {
  const server = [
    '    def get(self):', '        if path == "/api/state":', '        elif path == "/api/new-thing2":',
    '    def post(self):', '        if path == "/api/do_it":',
  ].join('\n')
  const jev = 'if path not in ("/api/jev/run", "/api/jev/re-rank"):'
  assert.deepEqual(extractRoutes(server, jev).sort(),
    ['GET /api/new-thing2', 'GET /api/state', 'POST /api/do_it', 'POST /api/jev/re-rank', 'POST /api/jev/run'])
  assert.throws(() => extractRoutes(server + '\n        elif path == "/api/Odd.Name":', jev), /route the reader cannot read/)
})

test('mock parity: every server route has a well-formed mock answer, unless it is allowlisted', async () => {
  const routes = serverRoutes()
  for (const r of ['GET /api/usage', 'GET /api/graph', 'GET /api/graph/node', 'GET /api/history', 'GET /api/agents',
    'GET /api/ticker', 'POST /api/triage/run', 'POST /api/jev/run', 'POST /api/jev/rank']) assert.ok(routes.includes(r), `found ${r}`)
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'bridge-cockpit-parity-'))
  try {
    fs.cpSync(WEB, path.join(dir, 'web'), { recursive: true })
    fs.writeFileSync(path.join(dir, 'web', 'package.json'), '{"type":"module"}')
    const mock = await import(pathToFileURL(path.join(dir, 'web', 'mock.js')).href)
    const tr = mock.createMockTransport({ lang: 'en' })
    const st = (await tr.get('/api/state')).data
    const page = st.model.pages.find(p => p.sections.length)
    const jevPage = st.model.pages.find(p => p.jev)
    const node = (await tr.get('/api/graph')).data?.nodes?.[0]?.id ?? ''
    const inbox = st.model.sections.flatMap(s => s.rows).find(r => r.inbox_id)
    const query = {
      '/api/page': `page=${page.id}&section=${page.sections[0].id}`, '/api/tab/screen': `ref=${encodeURIComponent(st.tabs.tabs[0].ref)}`,
      '/api/task': 'slug=demo-task', '/api/inbox': `id=${inbox.inbox_id}`, '/api/github': `ref=${encodeURIComponent('example/repo#12')}`,
      '/api/graph/node': `id=${encodeURIComponent(node)}`,
    }
    const body = {
      '/api/action': { verb: 'snapshot_list', args: {} }, '/api/ask': { kind: 'free', args: { text: 'hi' }, via: 'quick' },
      '/api/route': { keys: ['task:demo-task'] }, '/api/reload': {}, '/api/triage/run': { fresh: false },
      '/api/jev/run': {}, '/api/jev/rank': { page: jevPage?.id ?? '', force: true },
    }
    for (const route of routes) {
      if (MOCK_ROUTE_ALLOW.has(route)) continue
      const [method, p] = route.split(' ')
      const res = method === 'GET' ? await tr.get(query[p] ? `${p}?${query[p]}` : p) : await tr.post(p, body[p] ?? {})
      assert.notEqual(res.error?.message, 'unknown path', `${route}: the mock has no answer; add one to mock.js or allowlist it here`)
      assert.equal(res.ok, true, `${route}: ${JSON.stringify(res.error)}`)
      assert.notEqual(res.data?.ok, false, route)
    }
    // the shapes the pages read: usage.view(), graph.view() and node(), history, agents, ticker, triage, a Jev order
    const usage = (await tr.get('/api/usage')).data.usage
    assert.equal(usage.days.length, 7)
    for (const d of usage.days) for (const k of ['session', 'subagent', 'worker']) assert.equal(typeof d.sources[k].output, 'number', `${d.day} ${k}`)
    assert.ok(logic.usageBars(usage).max > 0, 'the usage card draws bars')
    const graph = (await tr.get('/api/graph')).data
    const ids = new Set(graph.nodes.map(n => n.id))
    assert.ok(graph.nodes.length >= 8 && graph.edges.length >= 6)
    for (const n of graph.nodes) assert.ok(logic.GRAPH_GROUPS.includes(n.group), n.id)
    for (const e of graph.edges) assert.ok(ids.has(e.s) && ids.has(e.t), `${e.s} -> ${e.t}`)
    const detail = (await tr.get(`/api/graph/node?id=${encodeURIComponent(node)}`)).data
    assert.equal(detail.id, node)
    assert.equal(typeof detail.text, 'string')
    assert.ok(Array.isArray(detail.out) && Array.isArray(detail.in) && detail.out.length + detail.in.length > 0)
    assert.equal((await tr.get('/api/graph/node?id=nowhere.md')).error.code, 'not_found')
    const history = (await tr.get('/api/history')).data.entries
    assert.ok(history.length >= 2)
    for (const e of history) assert.ok(typeof e.at_ms === 'number' && e.items.length && e.items.every(it => it.title && it.kind && it.did), e.id)
    const agents = (await tr.get('/api/agents')).data
    assert.ok(agents.peers.length >= 1 && agents.peers.every(p => p.id && p.reach))
    assert.ok(agents.convs.every(c => agents.peers.some(p => p.id === c.peer) && c.turns.length))
    assert.deepEqual(st.agents.peers.map(p => p.id), agents.peers.map(p => p.id), 'the state carries the same peers')
    assert.ok((await tr.get('/api/ticker')).data.ticker.items.length >= 3)
    assert.ok(Object.keys(st.triage.items).length >= 3, 'the state carries a triage')
    const tri = await tr.post('/api/triage/run', { fresh: false })
    assert.equal(tri.status, 202)
    assert.ok(tri.data.triage.running)
    assert.ok(jevPage, 'a page with jev: in the mock')
    const order = (await tr.post('/api/jev/rank', { page: jevPage.id, force: true })).data.order
    assert.ok(order.items.length >= 1 && order.items.every((x, i) => x.rank === i + 1 && x.key))
    assert.equal(order.first, order.items[0].key)
    const kept = (await tr.post('/api/jev/rank', { page: jevPage.id, force: false })).data.order
    assert.equal(kept.at_ms, order.at_ms, 'without force the kept order comes back')
    assert.equal((await tr.post('/api/jev/rank', { page: 'nowhere' })).error.code, 'not_found')
    // a close lands in the history with its undo, and the undo takes it back
    await tr.post('/api/action', { verb: 'done', args: { key: inbox.key } })
    const top = (await tr.get('/api/history')).data.entries[0]
    assert.deepEqual([top.verb, top.items[0].key, top.items[0].undo], ['done', inbox.key, { verb: 'inbox_reopen', args: { id: inbox.inbox_id } }])
    await tr.post('/api/action', { verb: 'inbox_reopen', args: { id: inbox.inbox_id } })
    assert.equal(typeof (await tr.get('/api/history')).data.entries[0].items[0].undone_ms, 'number')
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
})

test('ticker names a token source as the usage page does, not by its raw id', () => {
  const it = { key: 'outlier', vars: ['worker', 6.9] }
  assert.match(logic.tickerText(it, text.TABLES.de), /Programme \(claude -p\)/)
  assert.match(logic.tickerText(it, text.TABLES.en), /Programs \(claude -p\)/)
  assert.doesNotMatch(logic.tickerText({ key: 'outlier', vars: ['subagent', 2] }, text.TABLES.de), /von subagent/)
})

test('settings: Customise opens a drawer beside the start page, every choice there is explained', () => {
  assert.match(read('components.js'), /s\.ui\.drawer === 'customize' \? html`<\$\{CustomizeDrawer\}/)
  assert.match(read('views/stage.js'), /onClick=\$\{\(\) => c\.setDrawer\('customize'\)\}/)
  assert.match(read('views/home.js'), /onClick=\$\{\(\) => c\.setDrawer\('customize'\)\}/)
  assert.doesNotMatch(read('views/home.js'), /HomeChooser/)
  assert.match(read('app.js'), /openSettings\(id\) \{/)
  const ids = logic.homeCatalog({ pages: [] }).filter(x => ['shelf', 'option', 'core'].includes(x.kind)).map(x => x.id)
  for (const lang of ['en', 'de']) {
    const w = text.TABLES[lang].settings
    for (const id of ['start', 'look', 'launch']) assert.ok(w.section[id].title && w.section[id].sub, `${lang} ${id}`)
    for (const id of ids.filter(x => x !== 'o:classic')) assert.ok(w.explainOption[id], `${lang} ${id}`)
    for (const k of ['quota', 'count', 'page']) assert.ok(w.kind[k], `${lang} ${k}`)
  }
})

test('ticker: a new duration keeps the band where it stands instead of jumping', () => {
  // half way through a 100 s pass stays half way through a 200 s one
  assert.equal(logic.tickerResume(50000, 100, 200), 100000)
  // past one pass it keeps only the part of the current pass
  assert.equal(logic.tickerResume(250000, 100, 100), 50000)
  // nothing known yet: start from the beginning
  assert.equal(logic.tickerResume(null, 100, 200), 0)
  assert.equal(logic.tickerResume(1000, 0, 200), 0)
  const tk = read('views/ticker.js')
  assert.match(tk, /tickerResume\(/)        // the band uses it when its duration changes
})

test('drop: the scope a reason mutes is the one inbox.py writes', () => {
  const item = { from: 'mini/daily-health', key: 'mini-health:crash:1a20', kind: 'finding' }
  assert.deepEqual(logic.muteScope(item, 'family'), { source: 'mini/daily-health', key_prefix: 'mini-health:crash:' })
  assert.deepEqual(logic.muteScope({ ...item, key: 'plain' }, 'family'), { source: 'mini/daily-health', kind: 'finding' })
  assert.deepEqual(logic.muteScope({ ...item, key: null }, 'family'), { source: 'mini/daily-health', kind: 'finding' })
  assert.deepEqual(logic.muteScope({ ...item, key: 'a:b:' }, 'family'), { source: 'mini/daily-health', key_prefix: 'a:' })
  assert.deepEqual(logic.muteScope(item, 'source'), { source: 'mini/daily-health', days: 30 })
  assert.equal(logic.muteScope(item, 'once'), null)
  assert.equal(logic.muteScope(item, 'duplicate'), null)
  assert.equal(logic.muteScope({ key: 'a:b' }, 'family'), null)   // no source, nothing to say
})

test('noise: only sources a person dropped from, most clicks first, at most eight', () => {
  const src = (source, filed, dropped, extra = {}) => ({ source, filed, dropped, muted: 0, done: 0, open: 0,
    share: filed ? Math.round(dropped / filed * 100) / 100 : 0, reasons: {}, ...extra })
  const noise = { days: 30, mutes: [], sources: [src('a', 4, 3), src('b', 30, 0), src('c', 2, 2), src('d', 10, 1, { muted: 4 })] }
  const rows = logic.noiseRows(noise)
  assert.deepEqual(rows.map(r => r.source), ['a', 'c', 'd'])
  assert.deepEqual(rows.map(r => r.percent), [75, 100, 10])
  const many = { days: 30, mutes: [], sources: Array.from({ length: 12 }, (_, i) => src(`s${i}`, 5, 1)) }
  assert.equal(logic.noiseRows(many).length, 8)
  assert.deepEqual(logic.noiseRows(null), [])
})

test('drop: an inbox row asks why, the command box and bulk drops stay one keystroke', () => {
  const app = read('app.js')
  const overlays = read('views/overlays.js')
  assert.match(app, /case 'drop':\s*\n\s*return row\.inbox_id \? ctl\.askDrop\(row\) : act\('drop', \{ key: row\.key \}\)/)
  assert.match(app, /for \(const \{ row \} of plan\.drop\) await act\('drop', \{ key: row\.key \}\)/)
  assert.match(app, /c\?\.kind === 'drop'/)
  assert.match(overlays, /conf\.kind === 'drop'\) return html`<\$\{DropDialog\}/)
  assert.match(read('views/detail.js'), /c\.askDrop\(row\)/)
  for (const lang of ['en', 'de']) {
    const t = text.TABLES[lang]
    for (const r of ['once', 'duplicate', 'family', 'source']) assert.ok(t.dropReason[r], `${lang} dropReason.${r}`)
  }
})

test('noise: the Betrieb page shows the noise card and lifts a mute through the action', () => {
  assert.match(read('components.js'), /page\.overview \? html`<\$\{NoiseCard\} page=\$\{page\} s=\$\{s\} c=\$\{c\} \/>`/)
  assert.match(read('views/pages.js'), /export function NoiseCard/)
  assert.match(read('app.js'), /api\.get\('\/api\/inbox\/noise'\)/)
  assert.match(read('app.js'), /act\('inbox_unmute', \{ id \}\)/)
})

test('github rows: the board priority shows as a chip and sorts P1 before P2 before P3 within a board', () => {
  const row = (n, priority, state = 'ready', changed = '2026-10-0' + n) => ({ index: n, gh: { priority, state, changed } })
  const rows = [row(1, 'P3'), row(2, null), row(3, 'P1'), row(4, 'P2'), row(5, 'P1', 'blocked')]
  // by priority: the lowest number first, a row without one last; equal ones in the work's order, then newest
  assert.deepEqual(logic.ghSortRows(rows, 'priority').map(r => r.index), [5, 3, 4, 1, 2])
  // the other orders stay as they were
  assert.deepEqual(logic.ghSortRows(rows, 'recent').map(r => r.index), [5, 4, 3, 2, 1])
  assert.deepEqual(logic.ghSortRows(rows, 'state').map(r => r.index), [5, 4, 3, 2, 1])
  assert.ok(logic.prioRank('P0') < logic.prioRank('P1') && logic.prioRank('P9') < logic.prioRank('High'))
  assert.ok(logic.prioRank('Low') < logic.prioRank(null))
  const gh = read('views/github.js')
  assert.match(gh, /<\$\{PrioChip\} priority=\$\{g\.priority\} \/>/)
  assert.match(gh, /ghSortRows\(/)
  for (const lang of ['en', 'de']) assert.ok(text.TABLES[lang].gh.sort.priority, lang)
})

// ---------------------------------------------------------------- the chat as cmux: roomsOf

test('roomsOf: workspaces in the terminal order, pinned first, with their tabs, the chats in the control one', () => {
  const tab = (ref, state, workspace, extra = {}) => ({ ref, state, workspace, name: ref, ...extra })
  const s = {
    rooms: { layout: 'workspaces', root: '/u/bridge', control: 'Bridge', bridges: [
      { id: 'kion', name: 'kion-bridge', path: '/u/k1/kion-bridge' }, { id: 'family', name: 'family', path: '/u/family' }] },
    tabs: {
      workspaces: [
        { ref: 'w:2', title: 'Stepstone', cwd: '/u/bridge', unread: 2, statuses: [{ name: 'claude_code', text: 'Idle' }] },
        { ref: 'w:1', title: 'Bridge', cwd: '/u/bridge', pinned: true, statuses: [{ name: 'claude_code', text: 'Waiting' }] },
        { ref: 'w:3', title: 'K1', cwd: '/u/k1/kion-bridge/sub' }],
      tabs: [tab('s:1', 'working', 'Bridge'), tab('s:2', 'needs-you', 'Bridge'), tab('s:3', 'waiting', 'Stepstone'),
        tab('s:4', 'waiting', 'Gone')],
    },
    quick: { convs: [{ id: 'q1', running: false, turns: [{ q: 'hi' }] }] },
    agents: { peers: [{ id: 'axel' }] },
  }
  const r = logic.roomsOf(s)
  assert.deepEqual(r.workspaces.map(w => w.title), ['Bridge', 'Stepstone', 'K1', 'Gone'])
  const [bridge, step, k1, gone] = r.workspaces
  assert.deepEqual(bridge.tabs.map(t => t.ref), ['s:2', 's:1'])        // needs-you first
  assert.equal(bridge.chats.length, 1)                                  // the chats live in the control workspace
  assert.equal(step.chats.length, 0)
  assert.equal(bridge.state, 'needs-you')                              // its most urgent tab
  assert.equal(k1.state, null)
  assert.equal(step.unread, 2)
  assert.equal(k1.bridge?.id, 'kion')                                   // a workspace in another Bridge says which
  assert.equal(bridge.bridge, null)
  assert.equal(gone.known, false)                                       // tabs of a workspace the list does not name still show
  assert.deepEqual(r.bridges.map(b => b.id), ['family'])                // a Bridge with a workspace is not listed twice
  assert.deepEqual(r.agents.map(a => a.id), ['axel'])
  assert.equal(r.waiting, 3)
})

test('roomsOf: without the workspace list the tabs still group, the chats get their own place', () => {
  const r = logic.roomsOf({ rooms: { control: 'Bridge' }, tabs: { workspaces: null, tabs: [{ ref: 's:1', state: 'waiting', workspace: 'Demo', name: 'x' }] },
    quick: { convs: [{ id: 'q1', turns: [] }] } })
  assert.deepEqual(r.workspaces.map(w => [w.title, w.known]), [['Demo', false]])
  assert.equal(r.chats.length, 1)                                       // no control workspace: the chats stand on their own
})

test('roomsOf: the page keeps state.rooms, so the chat layout reaches the router', () => {
  const app = read('app.js')
  assert.match(app, /rooms: payload\.rooms \?\? s\.rooms,/)
  assert.match(readComponents(), /s\.rooms\?\.layout === 'workspaces' \? html`<\$\{RoomsPage\}/)
})

test('roomsOf: the longest Bridge path wins, the real folder counts, workspaces go by ref', () => {
  const r = logic.roomsOf({
    rooms: { bridges: [{ id: 'outer', path: '/u/a' }, { id: 'inner', path: '/u/a/b' }, { id: 'linked', path: '/real/x' }] },
    tabs: { workspaces: [{ ref: 'w:1', title: 'Same', cwd: '/u/a/b/c' }, { ref: 'w:2', title: 'Same', cwd: '/link/x', cwd_real: '/real/x' }],
      tabs: [{ ref: 's:1', ws_ref: 'w:2', workspace: 'Same', state: 'waiting', name: 'one' }] },
  })
  assert.deepEqual(r.workspaces.map(w => [w.ref, w.bridge?.id, w.tabs.length]), [['w:1', 'inner', 0], ['w:2', 'linked', 1]])
  assert.deepEqual(r.workspaces.map(w => w.key), ['w:1', 'w:2'])
  assert.deepEqual(r.bridges.map(b => b.id), ['outer'])
})

test('rooms: every quick chat in the sidebar can be removed, by a button beside the row, never inside it', () => {
  const rooms = read('views/rooms.js')
  assert.match(rooms, /class="room-chat-row"/)
  assert.match(rooms, /class="room-x"[^`]*onClick=\$\{\(\) => c\.quickForget\(x\.id\)\}/)
  assert.match(rooms, /x\.running \? null : html`<button type="button" class="room-x"/)   // one still answering stays
  assert.match(read('style.css'), /\.room-chat-row:hover \.room-x/)
})

test('listedChats: the picture of the day and chats past keep_hours stay out of the lists', () => {
  const now = Date.UTC(2026, 9, 18, 20)
  const h = 3600000
  const convs = [{ id: 'q1', last_ms: now - h }, { id: 'q2', last_ms: now - 25 * h }, { id: 'q3', last_ms: now - h, place: 'core' },
    { id: 'q4', started_ms: now - 30 * h, last_ms: now - 30 * h, running: true }, { id: 'q5', started_ms: now - 2 * h }]
  assert.deepEqual(logic.listedChats(convs, 24, now).map(x => x.id), ['q1', 'q4', 'q5'])
  assert.deepEqual(logic.listedChats(convs, 0, now).map(x => x.id), ['q1', 'q2', 'q4', 'q5'])     // 0: no day limit
  assert.deepEqual(logic.listedChats(convs, undefined, now).map(x => x.id), ['q1', 'q2', 'q4', 'q5'])
  const r = logic.roomsOf({ rooms: { control: 'Bridge' }, now, tabs: { workspaces: [{ ref: 'w:1', title: 'Bridge' }], tabs: [] },
    quick: { keep_hours: 24, convs } })
  assert.deepEqual(r.workspaces[0].chats.map(x => x.id), ['q1', 'q4', 'q5'])
  assert.match(read('views/chat.js'), /listedChats\(q\.convs, q\.keep_hours, s\.now\)/)       // the Chat tab lists the same
})

test('rooms: a quick chat shows a speech bubble, not a question mark; the core asks with place core', () => {
  const rooms = read('views/rooms.js')
  assert.doesNotMatch(rooms, />\?<\/span>/)
  assert.match(rooms, /<\$\{Icon\} name="chat"/)
  assert.match(read('views/parts.js'), /\n  chat: '/)
  assert.match(read('app.js'), /askQuiet: [^\n]*\n[^\n]*api\.ask\('free', \{ text \}, \{ via: 'quick', place: 'core'/)
  assert.match(read('text.js'), /allChats: n => `alle \$\{n\} Chats`/)
})

test('rooms: the pane never jumps on its own, the header knows the rail is gone, the copy command is quoted', () => {
  const rooms = read('views/rooms.js')
  assert.doesNotMatch(rooms, /x\.state === 'waiting'\)\)/)                 // no auto pick of a waiting tab
  assert.match(read('views/header.js'), /railShown\(s\.ui\.page, s\.rooms\?\.layout, s\.ui\.railHidden\)/)
  assert.equal(logic.shellQuote("/u/it's here"), "'/u/it'\\''s here'")
  assert.match(rooms, /cd \$\{shellQuote\(b\.path\)\} && claude/)
})

test('hidden page: visibilitychange flags the stream so the server stops polling for it (#373)', async () => {
  const saved = globalThis.document
  const listeners = {}
  globalThis.document = { visibilityState: 'visible', addEventListener: (name, fn) => { listeners[name] = fn }, removeEventListener: () => {} }
  try {
    const calls = []
    let given = null
    const a = api.createApi({
      get: async () => ({}),
      post: async (p, b, csrf) => { calls.push([p, b, csrf]); return { ok: true } },
      events: handlers => { given = handlers; return { close() {} } },
    })
    a.setCsrf('tok')
    const seen = []
    a.events({ hello: p => seen.push(p) }, () => {})
    given.hello({ version: 'x', client: 'c1' })
    assert.equal(seen.length, 1, 'the page still gets its hello')
    assert.deepEqual(calls, [], 'a visible page says nothing')
    globalThis.document.visibilityState = 'hidden'
    listeners.visibilitychange()
    assert.deepEqual(calls.at(-1), ['/api/presence', { client: 'c1', visible: false }, 'tok'])
    globalThis.document.visibilityState = 'visible'
    listeners.visibilitychange()
    assert.deepEqual(calls.at(-1), ['/api/presence', { client: 'c1', visible: true }, 'tok'])
    // a reconnect while hidden (new client id) reports hidden at once
    globalThis.document.visibilityState = 'hidden'
    calls.length = 0
    given.hello({ version: 'x', client: 'c2' })
    assert.deepEqual(calls, [['/api/presence', { client: 'c2', visible: false }, 'tok']])
  } finally {
    globalThis.document = saved
  }
})

test('due dates: overdue, today, tomorrow, else the day itself', async () => {
  const logic = await import(pathToFileURL(path.join(WEB, 'logic.js')).href)
  const now = new Date(2026, 9, 18, 19, 0).getTime()
  assert.deepEqual(logic.dueWhen('2026-10-13', now), { kind: 'overdue', days: 5 })
  assert.deepEqual(logic.dueWhen('2026-10-17T09:00', now), { kind: 'overdue', days: 1 })
  assert.deepEqual(logic.dueWhen('2026-10-18', now), { kind: 'today', days: 0 })
  assert.deepEqual(logic.dueWhen('2026-10-19T15:00', now), { kind: 'tomorrow', days: 1 })
  assert.deepEqual(logic.dueWhen('2026-10-27', now), { kind: 'later', days: 9 })
  assert.equal(logic.dueWhen('', now), null)
  // a why that names the due date again is left out where the row shows the date itself
  assert.deepEqual(logic.whyWithoutDue(['due 13.10', 'only you', 'fällig 16.10 09:00', 'back on 19.10']), ['only you', 'back on 19.10'])
})

test('errorText: a missing quick-question CLI is named as such, not as cmux, in both languages', () => {
  for (const lang of ['en', 'de']) {
    text.setLanguage(lang)
    const t = text.T()
    for (const provider of ['claude', 'codex']) {
      const said = logic.errorText({ code: 'cli_unavailable', message: `the ${provider} CLI is not available` }, t)
      assert.match(said, new RegExp(`\\b${provider}\\b`), `${lang} ${provider}`)
      assert.match(said, /CLI/, lang)
      assert.doesNotMatch(said, /cmux/i, lang)
    }
    // without a readable provider the text still says what is missing
    const bare = logic.errorText({ code: 'cli_unavailable', message: '' }, t)
    assert.match(bare, /CLI/, lang)
    assert.doesNotMatch(bare, /cmux|undefined/i, lang)
    assert.equal(logic.errorText({ code: 'cmux_unavailable', message: 'x' }, t), t.errors.cmux_unavailable)
  }
  text.setLanguage('en')
})

test('style.css: every class selector is used by the page, or built from an allowed prefix', () => {
  // a rule nobody draws is dead weight that the next reader has to keep working; the leftovers of the
  // retired briefing-ui mod (ask box, its records, the skill list) were such rules
  const css = fs.readFileSync(path.join(WEB, 'style.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '')
  const classes = new Set()
  for (const m of css.matchAll(/([^{}]+)\{/g)) {
    const selector = m[1].trim()
    if (selector.startsWith('@')) continue
    for (const c of selector.replace(/\[[^\]]*\]/g, '').matchAll(/\.(-?[A-Za-z_][\w-]*)/g)) classes.add(c[1])
  }
  const files = []
  const walk = dir => {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, e.name)
      if (e.isDirectory()) { if (e.name !== 'vendor' && e.name !== 'fonts') walk(p) }
      else if (/\.(js|html)$/.test(e.name) && e.name !== 'mock.js') files.push(p)
    }
  }
  walk(WEB)
  // comment lines out, so a class only a comment names does not count as used
  const src = files.map(f => fs.readFileSync(f, 'utf8').split('\n')
    .filter(line => !/^\s*(\/\/|\/\*|\*)/.test(line)).join('\n')).join('\n')
  // prefixes a view completes at run time (`tk-${tone}`, `day-${b.id}`): each must still be built somewhere.
  // null takes any completion; a list names the only ones the view can build, so a dead rule there shows
  const DYNAMIC = {
    'btn-': null, 'day-': null, 'fdot-': null, 'g-': null, 'hist-': null, 'is-': null, 'lane-': null,
    'layout-': null, 'mc-': null, 'md-h': null, 'rdot-': null, 'rt-': null, 'sm-': null, 'st-': null, 'tk-': null,
    'tl-': null, 'us-': null, 'view-thumb-': null, 'vs-': null,
    'ticker-': ['slow', 'normal', 'fast'],
    'tri-': ['ai', 'either'],
  }
  for (const p of Object.keys(DYNAMIC)) assert.ok(src.includes(`${p}\${`), `allowed prefix ${p} is built nowhere any more`)
  const built = c => Object.entries(DYNAMIC).some(([p, ok]) => c.startsWith(p) && (ok === null || ok.includes(c.slice(p.length))))
  const used = c => new RegExp(`(^|[^\\w-])${c.replace(/[-]/g, '\\-')}($|[^\\w-])`).test(src)
  const dead = [...classes].filter(c => !used(c) && !built(c)).sort()
  assert.deepEqual(dead, [])
})

// ---------------------------------------------------------------- load errors (#389)

/** The loaders of logic.js against a fake store and api: what the page shows after each answer */
function loaderRig(answers) {
  let state = { boot: { status: 'ready' }, agents: null, history: [], triage: {}, ui: { busy: {} }, notes: [] }
  const posts = []
  const pending = {}
  const api = {
    get: async p => answers[p],
    post: (p, b) => { posts.push([p, b]); return pending.post ? pending.post : Promise.resolve(answers[p]) },
  }
  const set = f => { state = f(state) }
  const fail = logic.createFailNote(
    () => set(s => ({ ...s, boot: { ...s.boot, status: 'unauthorized' } })),
    res => set(s => ({ ...s, notes: [...s.notes, { text: logic.errorText(res.error, text.TABLES.en), tone: 'bad' }] })))
  const withBusy = logic.createWithBusy(() => state.ui.busy, f => set(s => ({ ...s, ui: { ...s.ui, busy: f(s.ui.busy) } })),
    () => set(s => ({ ...s, notes: [...s.notes, { text: 'busy', tone: 'warn' }] })))
  const loaders = logic.createLoaders({ api, set, fail, withBusy })
  return { loaders, posts, pending, get: () => state }
}

test('loaders: a failed agents, history or triage answer leaves an error note, never a silent empty list', async () => {
  const err = { ok: false, status: 500, error: { code: 'internal', message: 'boom' } }
  for (const name of ['loadAgents', 'loadHistory', 'triageRun']) {
    const r = loaderRig({ '/api/agents': err, '/api/history': err, '/api/triage/run': err })
    await r.loaders[name](false)
    assert.equal(r.get().notes.length, 1, name)
    assert.equal(r.get().notes[0].tone, 'bad', name)
    assert.equal(r.get().boot.status, 'ready', name)
  }
  // a network drop (no status at all) is an error note too
  const r = loaderRig({ '/api/triage/run': { ok: false, error: { code: 'network', message: 'offline' } } })
  await r.loaders.triageRun(false)
  assert.equal(r.get().notes.length, 1)
})

test('loaders: a 401 from any of them goes to the sign-in page, as a reload does', async () => {
  const unauth = { ok: false, status: 401, error: { code: 'unauthorized', message: 'no' } }
  for (const name of ['loadAgents', 'loadHistory', 'triageRun']) {
    const r = loaderRig({ '/api/agents': unauth, '/api/history': unauth, '/api/triage/run': unauth })
    await r.loaders[name](false)
    assert.equal(r.get().boot.status, 'unauthorized', name)
    assert.deepEqual(r.get().notes, [], name)
  }
})

test('loaders: a good answer fills the store as before', async () => {
  const r = loaderRig({
    '/api/agents': { ok: true, data: { peers: ['p'], convs: [{ id: 'c' }] } },
    '/api/history': { ok: true, data: { entries: [{ verb: 'task_close' }] } },
    '/api/triage/run': { ok: true, data: { triage: { running: true } } },
  })
  await r.loaders.loadAgents()
  await r.loaders.loadHistory()
  await r.loaders.triageRun(true)
  assert.deepEqual(r.get().agents, { peers: ['p'], convs: [{ id: 'c' }] })
  assert.deepEqual(r.get().history, [{ verb: 'task_close' }])
  assert.deepEqual(r.get().triage, { running: true })
  assert.deepEqual(r.posts, [['/api/triage/run', { fresh: true }]])
  assert.deepEqual(r.get().notes, [])
})

test('loaders: while a triage run is pending a second one sends no POST and the button reads as running', async () => {
  const r = loaderRig({})
  let release
  r.pending.post = new Promise(res => { release = res })
  const first = r.loaders.triageRun(false)
  assert.equal(r.get().ui.busy[logic.TRIAGE_BUSY], 'triage')
  assert.equal(logic.triageRunning(r.get()), true)
  assert.equal(await r.loaders.triageRun(false), null)
  assert.equal(r.posts.length, 1)
  release({ ok: true, data: { triage: { running: false } } })
  await first
  assert.deepEqual(r.get().ui.busy, {})
  assert.equal(logic.triageRunning(r.get()), false)
  assert.equal(logic.triageRunning({ triage: { running: true }, ui: { busy: {} } }), true)
  // the page wires them: app.js builds its failNote and loaders here, the button reads triageRunning
  const app = read('app.js')
  assert.match(app, /const failNote = createFailNote\(/)
  assert.match(app, /createLoaders\(\{ api: \{[^}]*\}, set: store\.set, fail: failNote, withBusy \}\)/)
  assert.doesNotMatch(app, /api\.post\('\/api\/triage\/run'/)
  assert.match(read('triage.js'), /const running = triageRunning\(s\)/)
})

test('loaders: a 409 for a triage run already on is an answer, not an error: its state is applied', async () => {
  const on = { running: { started_ms: 1, why: 'daily' } }
  const r = loaderRig({ '/api/triage/run': { status: 409, ok: false, data: { ok: false, triage: on }, error: { code: 'unknown', message: '' } } })
  await r.loaders.triageRun(false)
  assert.deepEqual(r.get().notes, [])
  assert.deepEqual(r.get().triage, on)
  assert.equal(logic.triageRunning(r.get()), true)
  // a 409 without a triage state stays an error
  const bare = loaderRig({ '/api/triage/run': { status: 409, ok: false, data: { ok: false }, error: { code: 'conflict', message: 'x' } } })
  await bare.loaders.triageRun(false)
  assert.equal(bare.get().notes.length, 1)
  assert.equal(bare.get().notes[0].tone, 'bad')
})

// ---------------------------------------------------------------- notes and toasts (#390)

// what pushNote in app.js does: pushNoteState decides, the toast's timer later drops it again
const failed = { text: 'The server does not answer.', tone: 'bad', at: '12:00' }
const dismiss = (s, id) => ({ ...s, toasts: s.toasts.filter(t => t.id !== id) })

test('notes: the same error twice within a second shows one toast and one note', () => {
  let s = { notes: [], toasts: [] }
  const first = logic.pushNoteState(s, failed, 0, 1)
  assert.equal(first.dup, false)
  assert.equal(first.toast.id, 1)
  s = first
  const again = logic.pushNoteState(s, failed, 800, 2)
  assert.equal(again.dup, true)
  assert.equal(again.toast, undefined)
  assert.equal(again.toasts.length, 1)
  assert.equal(again.notes.length, 1)
  // another tone is another message
  assert.equal(logic.pushNoteState(s, { ...failed, tone: 'warn' }, 900, 2).toasts.length, 2)
})

test('notes: the same error after its toast is gone shows a new toast and a new note', () => {
  let s = logic.pushNoteState({ notes: [], toasts: [] }, failed, 0, 1)
  s = dismiss(s, 1)                                   // the toast's own 6 s are over
  const retry = logic.pushNoteState(s, failed, 7000, 2)
  assert.equal(retry.dup, false)
  assert.equal(retry.toast.id, 2)
  assert.deepEqual(retry.toasts.map(t => t.text), [failed.text])
  assert.equal(retry.notes.length, 2)
  // while a toast stays up longer, the same text stays one, however late it comes
  const long = logic.pushNoteState({ notes: [], toasts: [] }, failed, 0, 1)
  assert.equal(logic.pushNoteState(long, failed, 15000, 2).dup, true)
})

test('notes: without a toast the note is kept, the newest four toasts stay up', () => {
  const quiet = logic.pushNoteState({ notes: [], toasts: [] }, failed, 0, 1, false)
  assert.equal(quiet.notes.length, 1)
  assert.equal(quiet.toasts.length, 0)
  let s = { notes: [], toasts: [] }
  for (let i = 0; i < 6; i++) s = logic.pushNoteState(s, { text: `n${i}`, tone: 'info', at: '12:00' }, i, i + 1)
  assert.deepEqual(s.toasts.map(t => t.id), [3, 4, 5, 6])
  assert.equal(s.notes.length, 6)
})

// ---------------------------------------------------------------- toasts that wait, row actions busy per row (#391)

/** A clock the test moves by hand: setTimer and clearTimer as createToastTimers takes them */
function handClock() {
  let at = 0
  let seq = 0
  const due = new Map()
  return {
    now: () => at,
    setTimer: (fn, ms) => { seq += 1; due.set(seq, { fn, when: at + ms }); return seq },
    clearTimer: id => { due.delete(id) },
    advance(ms) {
      at += ms
      for (const [id, d] of [...due].sort((a, b) => a[1].when - b[1].when)) {
        if (d.when > at) continue
        due.delete(id)
        d.fn()
      }
    },
  }
}

test('createToastTimers: a toast with focus inside it outlives its linger time and goes once focus leaves', () => {
  const clock = handClock()
  const gone = []
  const timers = logic.createToastTimers({ ...clock, expire: id => gone.push(id) })
  timers.start(1, 6000)
  timers.start(2, 6000)
  clock.advance(1000)
  timers.pause(1, 'focus')
  clock.advance(9000)
  assert.deepEqual(gone, [2], 'the toast without focus went on time, the focused one stays')
  timers.resume(1, 'focus')
  clock.advance(4999)
  assert.deepEqual(gone, [2], 'it keeps the 5 s it had left when the focus came')
  clock.advance(1)
  assert.deepEqual(gone, [2, 1])
})

test('createToastTimers: hover and focus each hold the toast, it runs again only when both have left', () => {
  const clock = handClock()
  const gone = []
  const timers = logic.createToastTimers({ ...clock, expire: id => gone.push(id) })
  timers.start(1, 6000)
  timers.pause(1, 'hover')
  timers.pause(1, 'focus')
  timers.resume(1, 'hover')
  clock.advance(60000)
  assert.deepEqual(gone, [])
  timers.resume(1, 'focus')
  clock.advance(6000)
  assert.deepEqual(gone, [1])
  // a dismissed toast leaves no timer behind, and a hover on it afterwards starts none
  timers.start(3, 6000)
  timers.stop(3)
  timers.pause(3, 'hover')
  timers.resume(3, 'hover')
  clock.advance(60000)
  assert.deepEqual(gone, [1])
})

test('toastLinger: a bad toast stays until dismissed, every other tone keeps its linger', () => {
  const clock = handClock()
  const gone = []
  const timers = logic.createToastTimers({ ...clock, expire: id => gone.push(id) })
  assert.equal(logic.toastLinger('bad', 6000), null)
  for (const tone of ['info', 'ok', 'warn']) assert.equal(logic.toastLinger(tone, 6000), 6000)
  timers.start(1, logic.toastLinger('bad', 6000))
  timers.pause(1, 'hover')
  timers.resume(1, 'hover')
  clock.advance(24 * 3600 * 1000)
  assert.deepEqual(gone, [], 'no timer ever takes a bad toast away')
})

test('busyKey: a row action is busy per row, other actions keep their key', () => {
  const at = index => logic.busyKey('row_action', { page: 'dates', section: 'cal', index, action: 'prep' })
  assert.equal(at(1), 'row_action:dates:cal:1')
  assert.notEqual(at(1), at(2))
  assert.notEqual(at(1), logic.busyKey('row_action', { page: 'dates', section: 'other', index: 1 }))
  assert.equal(logic.rowActionKey({ page: 'dates', section: 'cal', index: 1 }), at(1), 'the views read the same key')
  assert.equal(logic.planBusy('row_action', { page: 'dates', section: 'cal', index: 2, action: 'prep' }, {}).key, at(2))
  assert.equal(logic.busyKey('task_close', { key: 'task:a' }), 'task:a')
  assert.equal(logic.busyKey('home_tiles', { ids: ['a'] }), 'home_tiles')
})
