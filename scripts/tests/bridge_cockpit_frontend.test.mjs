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
// The page's .js files are ES modules without a package.json "type"; to run on every
// supported Node version they are copied to a temp directory as .mjs and imported there.
import { createHash } from 'node:crypto'
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
  assert.deepEqual(de.section, { now: 'Wartet auf dich', give: 'Kann die AI übernehmen', work: 'Aufgaben', later: 'Später' })
  assert.deepEqual(en.section, { now: 'Waiting for you', give: 'AI can take over', work: 'Tasks', later: 'Later' })
  // the same sections on the start board (home.sit) and in the assessment Claude reads (logic.situation)
  for (const id of ['now', 'give', 'work', 'later']) {
    assert.equal(de.logic.situation[id], de.section[id], id); assert.equal(en.logic.situation[id], en.section[id], id)
  }
  for (const id of ['now', 'give', 'later']) { assert.equal(de.home.sit[id], de.section[id], id); assert.equal(en.home.sit[id], en.section[id], id) }
  assert.equal(de.home.returnsTitle, 'Bei der AI'); assert.equal(en.home.returnsTitle, 'With AI')
  assert.equal(de.home.coreModes, 'Beim Klick auf Bridge'); assert.equal(en.home.coreModes, 'On a click on Bridge')
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
    'stale_tab', 'not_applicable', 'relay_offline', 'cmux_unavailable', 'internal']
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

test('notes are deduplicated for a few seconds and capped', () => {
  let notes = []
  notes = logic.addNote(notes, { text: 'x', tone: 'ok' }, 1000)
  notes = logic.addNote(notes, { text: 'x', tone: 'ok' }, 2000)
  assert.equal(notes.length, 1)
  notes = logic.addNote(notes, { text: 'x', tone: 'ok' }, 20000)
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
    assert.deepEqual(comp.pageOrder({ ...pages, jev: { enabled: false } }), ['@start', 'briefing', '@chat', 'x', '@sessions', '@workers', '@check'])
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
  const page = readComponents().match(/function AgentsPage\(\{ s, c \}\) \{[\s\S]*?\n\}/)[0]
  // the first click only arms the button, the second removes
  assert.match(page, /forgetArmed === conv\.id \? c\.agentForget\(conv\.id\) : setForgetArmed\(conv\.id\)/)
  assert.equal((read('text.js').match(/agentForgetSure:/g) ?? []).length, 2)
})

test('agents: a draft never travels to another agent, held answers show on the card', () => {
  const src = readComponents()
  const page = src.match(/function AgentsPage\(\{ s, c \}\) \{[\s\S]*?\n\}/)[0]
  assert.match(page, /useEffect\(\(\) => \{[^}]*setText\(''\)[^}]*\}, \[peer\?\.id\]\)/)
  assert.match(page, /held=\$\{convs\.filter\(x => x\.peer === p\.id && !x\.running && x\.turns\.at\(-1\)\?\.waiting\)\.length\}/)
})

test('history: a close offers undo at once and later; a task comes back open or as still to be done', () => {
  const app = read('app.js')
  const comp = readComponents()
  assert.match(app, /if \(r\.undo\?\.length && r\.ok\) \{\s*pushNote\(\{[^}]*action: 'undo', undo: r\.undo \}/)
  assert.match(app, /undo: async \(u, as = 'doing'\) =>/)
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
    assert.deepEqual(comp.pageOrder(s), ['@start', 'briefing', '@chat', 'inbox', 'tasks', '@sessions', '@workers', '@check', 'llm'])
    assert.deepEqual([...comp.morePages(s)], ['@sessions', '@workers', '@check', 'llm'])
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
  const col = comp.match(/function TabsColumn\([\s\S]*?\n\}/)[0]
  assert.match(col, /<\$\{TabCard\}[^>]*slim/)
  const card = comp.match(/function TabCard\([\s\S]*?\n\}/)[0]
  assert.match(card, /aria-expanded/)
  const ctl = comp.match(/function TabControls\([\s\S]*?\n\}/)[0]
  assert.match(ctl, /if \(slim\)[\s\S]*tabNextStep/)
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
    assert.deepEqual(comp.pageOrder(s), ['@start', 'briefing', '@chat', 'ops', '@sessions', '@workers', '@check'])
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
  // moving a tile one place in the order
  assert.deepEqual(logic.moveId(['a', 'b', 'c'], 'c', -1), ['a', 'c', 'b'])
  assert.deepEqual(logic.moveId(['a', 'b', 'c'], 'a', -1), ['a', 'b', 'c'])
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
