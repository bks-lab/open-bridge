// SPDX-License-Identifier: MIT
// Tests of the mod's pure functions (without Claude Code): the relay's pick, framing, mac, key path,
// config and surface, and its two text tables.
//
//   npx -y -p typescript@5.6.3 -c 'node mods/cockpit-relay/tests/pure.test.mjs'
//
// TypeScript comes from the tsc on PATH (npx puts it there) or from TS=<path to typescript.js>.
//
// The script compiles every file under hooks/ with TypeScript to .mjs in a temp directory,
// appends '.mjs' to relative imports, replaces the import from 'claude-code' with simple
// stand-ins and checks the exported functions with node:test.
import { execSync } from 'node:child_process'
import { createRequire } from 'node:module'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'
import test from 'node:test'
import assert from 'node:assert/strict'

const here = path.dirname(fileURLToPath(import.meta.url))
function findTypeScript() {
  if (process.env.TS) return process.env.TS
  let tsc = ''
  try {
    tsc = execSync('command -v tsc', { shell: '/bin/sh', stdio: ['ignore', 'pipe', 'ignore'] }).toString().trim()
  } catch { /* no tsc on PATH */ }
  const lib = tsc && path.join(path.dirname(fs.realpathSync(tsc)), '..', 'lib', 'typescript.js')
  if (lib && fs.existsSync(lib)) return lib
  console.error("cockpit-relay tests need TypeScript. Run them as: npx -y -p typescript@5.6.3 -c 'node mods/cockpit-relay/tests/pure.test.mjs'"
    + ' (or set TS to the path of typescript.js)')
  process.exit(2)
}
const ts = createRequire(import.meta.url)(findTypeScript())

const hooks = path.join(here, '..', 'hooks')
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cockpit-relay-'))
for (const name of fs.readdirSync(hooks).filter(f => /\.tsx?$/.test(f))) {
  let js = ts.transpileModule(fs.readFileSync(path.join(hooks, name), 'utf8'), {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext, jsx: ts.JsxEmit.React,
      jsxFactory: 'h', jsxFragmentFactory: 'Fragment' },
  }).outputText
  js = js.replace(/import \{[^}]*\} from 'claude-code';?/, 'const atom = (k, d) => ({ key: k.key, d }); const read = async () => null; const update = async () => {}')
  js = js.replace(/(from\s+'\.\/[\w-]+)'/g, "$1.mjs'")
  fs.writeFileSync(path.join(dir, name.replace(/\.tsx?$/, '.mjs')), js)
}
const load = name => import(pathToFileURL(path.join(dir, `${name}.mjs`)).href)
// loads the module itself: every import must resolve
await load('register')

// ---------------------------------------------------------------- relay: cockpit questions into this session

const relay = await load('relay')
const SESSION = 'a1b2c3d4-0000-4000-8000-00000000abcd'
const rid = n => `20261009T0800${String(n).padStart(2, '0')}-0000000${n}`
const rec = (n, extra = {}) => ({ v: 1, id: rid(n), created_ms: 1000, expires_ms: 601000, target_session: SESSION,
  kind: 'overview', text: `[web:${rid(n)}] From the local web dashboard: question ${n}`, chars: 40, ...extra })
const entry = (r, name = `${r.id}.json`, verified = true) => ({ name, record: r, verified })

test('relay: the first framed record of this session is submitted, in file name order', () => {
  const pick = relay.pickNext([entry(rec(3)), entry(rec(1)), entry(rec(2))], [], SESSION, 2000, false, null)
  assert.equal(pick.submit.id, rid(1))
  assert.deepEqual(pick.expire, [])
  assert.deepEqual(pick.reject, [])
})

test('relay: a record for another session is left alone, nothing written for it', () => {
  const pick = relay.pickNext([entry(rec(1, { target_session: 'other-session-0001' }))], [], SESSION, 2000, false, null)
  assert.equal(pick.submit, null)
  assert.deepEqual(pick.expire, [])
  assert.deepEqual(pick.reject, [])
})

test('relay: nothing is submitted while a turn runs or a question is in flight, expiry still applies', () => {
  const list = [entry(rec(1)), entry(rec(2, { expires_ms: 1500 }))]
  for (const [busy, flight] of [[true, null], [false, rid(9)]]) {
    const pick = relay.pickNext(list, [], SESSION, 2000, busy, flight)
    assert.equal(pick.submit, null)
    assert.deepEqual(pick.expire.map(r => r.id), [rid(2)])
  }
})

test('relay: an expired record is never submitted, even when it is the only one', () => {
  const pick = relay.pickNext([entry(rec(1, { expires_ms: 1999 }))], [], SESSION, 2000, false, null)
  assert.equal(pick.submit, null)
  assert.deepEqual(pick.expire.map(r => r.id), [rid(1)])
})

test('relay: handled ids (done file or store) and the one in flight are skipped', () => {
  const list = [entry(rec(1)), entry(rec(2)), entry(rec(3))]
  const pick = relay.pickNext(list, [rid(1)], SESSION, 2000, false, null)
  assert.equal(pick.submit.id, rid(2))
  assert.equal(relay.pickNext(list, [rid(1), rid(2), rid(3)], SESSION, 2000, false, null).submit, null)
})

test('relay: text without its own marker, another version or no expiry is rejected', () => {
  const bad = [
    rec(1, { text: 'From the local web dashboard: no marker' }),
    rec(2, { text: `[web:${rid(9)}] marker of another record` }),
    rec(3, { v: 2 }),
    rec(4, { expires_ms: undefined }),
    rec(5, { text: `[web:${rid(5)}] ${'x'.repeat(relay.TEXT_MAX)}` }),
  ]
  const pick = relay.pickNext(bad.map(r => entry(r)), [], SESSION, 2000, false, null)
  assert.deepEqual(pick.reject.map(r => r.id), bad.map(r => r.id))
  assert.equal(pick.submit, null)
})

test('relay: a file whose name is not its id, or an id that could be a path, is ignored', () => {
  const pick = relay.pickNext([entry(rec(1), 'renamed.json'), entry(rec(2, { id: '../../escape' }), '../../escape.json'),
    { name: 'broken.json', record: null }], [], SESSION, 2000, false, null)
  assert.deepEqual(pick, { expire: [], reject: [], submit: null })
})

test('relay: framing, marker, session ids', () => {
  assert.equal(relay.isFramed(`[web:${rid(1)}] text`, rid(1)), true)
  assert.equal(relay.isFramed(`text [web:${rid(1)}]`, rid(1)), false)
  assert.equal(relay.isFramed(undefined, rid(1)), false)
  assert.equal(relay.markerIn(`The plugin sent a message: [web:${rid(4)}] hi`), rid(4))
  assert.equal(relay.markerIn('2b'), null)
  assert.equal(relay.isSessionId(SESSION), true)
  assert.equal(relay.isSessionId('short'), false)
  assert.equal(relay.isSessionId('../../etc/passwd-0000'), false)
})

test('relay: the answer is cut at 20000 characters, empty is null', () => {
  assert.equal(relay.clipAnswer('x'.repeat(20001)).length, 20000)
  assert.equal(relay.clipAnswer('x'.repeat(20000)).length, 20000)
  assert.equal(relay.clipAnswer('short'), 'short')
  assert.equal(relay.clipAnswer('  '), null)
  assert.equal(relay.clipAnswer(undefined), null)
})

test('relay: turn.complete reasons map to done statuses', () => {
  assert.equal(relay.reasonToStatus('answer'), 'answered')
  assert.equal(relay.reasonToStatus('aborted'), 'aborted')
  assert.equal(relay.reasonToStatus('refusal'), 'error')
  assert.equal(relay.reasonToStatus('error'), 'error')
  assert.equal(relay.reasonToStatus('something new'), 'error')
})

test('relay: done record and heartbeat carry exactly the contract fields', () => {
  assert.deepEqual(relay.doneRecord(rid(1), SESSION, 'answered', 't-1', 'yes', 5),
    { v: 1, id: rid(1), session: SESSION, status: 'answered', turn_id: 't-1', answer: 'yes', at_ms: 5, mac: null })
  assert.deepEqual(relay.heartbeat(SESSION, '', 7, false, null),
    { v: 1, session: SESSION, surface: null, at_ms: 7, busy: false, in_flight: null, mod_version: relay.MOD_VERSION,
      mac: null })
})

test('relay: the heartbeat names the version of plugin.json', () => {
  const manifest = JSON.parse(fs.readFileSync(path.join(here, '..', '.claude-plugin', 'plugin.json'), 'utf8'))
  assert.equal(relay.MOD_VERSION, manifest.version)
})

test('relay: handled ids keep the newest 200, without duplicates', () => {
  let list = []
  for (let i = 0; i < 205; i++) list = relay.rememberId(list, `id-${i}`)
  assert.equal(list.length, 200)
  assert.equal(list[0], 'id-5')
  assert.deepEqual(relay.rememberId(['a', 'b'], 'a'), ['b', 'a'])
  assert.deepEqual(relay.rememberId(undefined, 'a'), ['a'])
  assert.deepEqual(relay.doneIdsOf([`${rid(1)}.json`, 'x.json', `${rid(2)}.tmp`]), [rid(1)])
})

test('relay: a record whose mac did not verify is rejected, never submitted (SEC-1)', () => {
  const pick = relay.pickNext([entry(rec(1), undefined, false), entry(rec(2))], [], SESSION, 2000, false, null)
  assert.deepEqual(pick.reject.map(r => r.id), [rid(1)])
  assert.equal(pick.submit.id, rid(2))
  const missing = relay.pickNext([{ name: `${rid(3)}.json`, record: rec(3) }], [], SESSION, 2000, false, null)
  assert.deepEqual(missing.reject.map(r => r.id), [rid(3)])
})

test('relay: sha256 matches node for empty, one block and several blocks', async () => {
  const { createHash } = await import('node:crypto')
  for (const text of ['', 'abc', 'x'.repeat(55), 'x'.repeat(56), 'x'.repeat(64), 'ä'.repeat(1000)]) {
    const bytes = new TextEncoder().encode(text)
    assert.equal(Buffer.from(relay.sha256(bytes)).toString('hex'), createHash('sha256').update(bytes).digest('hex'))
  }
})

test('relay: the mac is HMAC-SHA256 over inbox|id|session|expires_ms|text, as the server computes it (SEC-1)', async () => {
  const { createHmac } = await import('node:crypto')
  const key = 'ab'.repeat(32)
  const text = `[web:${rid(1)}] Sent from the local web dashboard: «Überblick» ${'x'.repeat(300)}`
  const want = createHmac('sha256', key).update(`inbox|${rid(1)}|${SESSION}|601000|${text}`, 'utf8').digest('hex')
  assert.equal(await relay.relayMac(key, rid(1), SESSION, 601000, text), want)
  assert.equal(await relay.verifyMac(key, rec(1, { text, mac: want })), true)
  assert.equal(await relay.verifyMac(key, rec(1, { text, mac: want.replace(/^./, c => (c === '0' ? '1' : '0')) })), false)
  assert.equal(await relay.verifyMac(key, rec(1, { text })), false)
  assert.equal(await relay.verifyMac(null, rec(1, { text, mac: want })), false)
  assert.equal(relay.isRelayKey(key), true)
  assert.equal(relay.isRelayKey('short'), false)
})

test('relay: the key lives outside the Bridge, where the server puts it (SEC-1)', () => {
  assert.equal(relay.relayKeyPath('/custom/dir', '/home/demo'), '/custom/dir/relay.key')
  assert.equal(relay.relayKeyPath(null, '/home/demo'), '/home/demo/.local/state/bridge-cockpit/relay.key')
  assert.equal(relay.relayKeyPath(null, null), null)
  assert.equal(relay.relayKeyPath('', ''), null)
})

test('relay: a turn with foreign text never carries the web question; an empty one may (R2)', () => {
  const at = 1000
  assert.equal(relay.isFlightTurn(`[web:${rid(1)}] question`, rid(1), at, at + 1), true)
  assert.equal(relay.isFlightTurn('', rid(1), at, at + 5000), true)
  assert.equal(relay.isFlightTurn('   ', rid(1), at, at + 5000), true)
  assert.equal(relay.isFlightTurn(undefined, rid(1), at, at + 5000), true)
  assert.equal(relay.isFlightTurn('what is the weather', rid(1), at, at + 5000), false)
  assert.equal(relay.isFlightTurn(`[web:${rid(2)}] other`, rid(1), at, at + 5000), false)
  assert.equal(relay.isFlightTurn('', rid(1), at, at + relay.CORRELATE_MS + 1), false)
})

test('relay: the fallback answer never reaches back past the last user message (R4)', () => {
  const u = text => ({ role: 'user', text })
  const a = text => ({ role: 'assistant', text })
  assert.equal(relay.answerSinceLastUser([u('earlier'), a('EARLIER ANSWER'), u(`[web:${rid(1)}] q`)]), '')
  assert.equal(relay.answerSinceLastUser([u(`[web:${rid(1)}] q`), a(''), a('the answer'), a('  ')]), 'the answer')
  assert.equal(relay.answerSinceLastUser([u('x'), a('From the transcript.')]), 'From the transcript.')
  assert.equal(relay.answerSinceLastUser([]), '')
})

// ---------------------------------------------------------------- cockpit-relay: paths, config, surface, words

test('relay: the files live where the cockpit server reads them (scripts/lib/bridge_cockpit/relay.py)', () => {
  assert.equal(relay.RELAY_INBOX, '.bridge/cockpit/relay/inbox')
  assert.equal(relay.RELAY_DONE, '.bridge/cockpit/relay/done')
  assert.equal(relay.RELAY_HEARTBEAT, '.bridge/cockpit/relay/heartbeat')
  assert.equal(relay.STORE_RELAY_DONE.startsWith('cockpit-relay:'), true)
  const server = fs.readFileSync(path.join(here, '..', '..', '..', 'scripts', 'lib', 'bridge_cockpit', 'relay.py'), 'utf8')
  assert.match(server, /BRIDGE_COCKPIT_KEY_DIR/)
  assert.match(server, /"\.local" \/ "state" \/ "bridge-cockpit"/)
  assert.match(server, new RegExp(`STUCK_MS = 30 \\* 60000`))
  assert.match(server, new RegExp(`ANSWER_MAX = ${relay.ANSWER_MAX}\\b`))
})

test('config: only the cockpit block counts, and the relay only when asked for', () => {
  // the relay is off unless asked for (relay: true), as the server reads it
  assert.deepEqual(relay.parseRelayConfig({ cockpit: { enabled: true, relay: true } }), { enabled: true, relay: true, language: 'en' })
  assert.deepEqual(relay.parseRelayConfig({ cockpit: { enabled: true } }), { enabled: true, relay: false, language: 'en' })
  // another block never switches it on
  assert.deepEqual(relay.parseRelayConfig({ web: { enabled: true, relay: true } }), { enabled: false, relay: false, language: 'en' })
  assert.deepEqual(relay.parseRelayConfig({ cockpit: true }), { enabled: false, relay: false, language: 'en' })
  assert.deepEqual(relay.parseRelayConfig({ cockpit: { enabled: 'yes' } }), { enabled: false, relay: false, language: 'en' })
  assert.deepEqual(relay.parseRelayConfig(undefined), { enabled: false, relay: false, language: 'en' })
  assert.deepEqual(relay.parseRelayConfig([true]), { enabled: false, relay: false, language: 'en' })
})

test('config: language from the block, else language.conversation; de... is German', () => {
  assert.equal(relay.parseRelayConfig({ cockpit: { language: 'de' }, language: 'en' }).language, 'de')
  assert.equal(relay.parseRelayConfig({ cockpit: {}, language: 'de-DE' }).language, 'de')
  assert.equal(relay.parseRelayConfig({ cockpit: {}, language: 'fr' }).language, 'en')
})

test('surface: cmux first, else a tmux pane id, else null', () => {
  assert.equal(relay.surfaceOf('uuid-1', '%3'), 'uuid-1')
  assert.equal(relay.surfaceOf(undefined, '%3'), '%3')
  assert.equal(relay.surfaceOf('', '%12'), '%12')
  assert.equal(relay.surfaceOf(null, 'nonsense'), null)
  assert.equal(relay.surfaceOf(undefined, '%'), null)
  assert.equal(relay.surfaceOf(undefined, undefined), null)
})

test('words: de and en have the same keys, nothing empty, no dash', () => {
  const { de, en } = relay.TABLES
  assert.deepEqual(Object.keys(de).sort(), Object.keys(en).sort())
  for (const table of [de, en]) {
    for (const v of Object.values(table)) {
      const s = typeof v === 'function' ? v(2) : v
      assert.ok(s.trim())
      assert.equal(/[\u2013\u2014]/.test(s), false)
    }
  }
})

test('config: the retired briefing block no longer sets the language', () => {
  assert.equal(relay.parseRelayConfig({ cockpit: {}, ui_language: 'de', language: 'en' }).language, 'en')
  assert.equal(relay.parseRelayConfig({ cockpit: {}, ui_language: 'en', language: 'de' }).language, 'de')
})

// ---------------------------------------------------------------- every direction signed

// One vector, the same in scripts/tests/test_bridge_cockpit.py: the mod and the server sign alike.
const SIGN_KEY = '0123456789abcdef'.repeat(4)

test('relay: inbox, heartbeat and done macs match the vector the server tests', () => {
  const id = '20261009T080001-00000001'
  assert.equal(relay.relayMac(SIGN_KEY, id, SESSION, 601000, `[web:${id}] q`),
    '1a99abe4212ff3504daf4b7d1e93e6026486b2405cd1c4710fd06ed0b1cfb026')
  assert.equal(relay.heartbeatMac(SIGN_KEY, SESSION, 1000, true, 'uuid-1'),
    'a2aefa70ac4a5889bb15bd1eb6466191376c72b6c922baf2756156eb6198400c')
  assert.equal(relay.heartbeatMac(SIGN_KEY, SESSION, 1000, false, null),
    '93068612ce3d648c9b50e223a6e0b39441b8b3db91eb0759b36cf29914303b74')
  assert.equal(relay.doneMac(SIGN_KEY, id, 'answered', 2000, 'the answer'),
    'd1b86d7d174f297313b46df531a53304ec9b506da4a4e1f37867e1d66a3be3f5')
  assert.equal(relay.doneMac(SIGN_KEY, id, 'submitted', 2000, null),
    '23228110fb4b9037d6fc3f1f602aa735c05615670055ff2a34da26eb976fca1e')
})

test('relay: an inbox record whose expires_ms changed after signing does not verify', () => {
  const r = rec(1)
  const signed = { ...r, mac: relay.relayMac(SIGN_KEY, r.id, r.target_session, r.expires_ms, r.text) }
  assert.equal(relay.verifyMac(SIGN_KEY, signed), true)
  assert.equal(relay.verifyMac(SIGN_KEY, { ...signed, expires_ms: r.expires_ms + 3600000 }), false)
  assert.equal(relay.verifyMac(SIGN_KEY, { ...signed, expires_ms: String(r.expires_ms) }), false)
})

test('relay: the heartbeat and the done file carry the mac of the key, null without one', () => {
  const hb = relay.heartbeat(SESSION, 'uuid-1', 1000.7, true, null, SIGN_KEY)
  assert.equal(hb.at_ms, 1000)
  assert.equal(hb.mac, relay.heartbeatMac(SIGN_KEY, SESSION, 1000, true, 'uuid-1'))
  assert.equal(relay.heartbeat(SESSION, null, 1000, false, null, null).mac, null)
  const d = relay.doneRecord(rid(1), SESSION, 'answered', 't1', 'the answer', 2000.2, SIGN_KEY)
  assert.equal(d.at_ms, 2000)
  assert.equal(d.mac, relay.doneMac(SIGN_KEY, rid(1), 'answered', 2000, 'the answer'))
  // the answer is signed as written: clipped, and an empty answer counts as none
  const blank = relay.doneRecord(rid(1), SESSION, 'answered', 't1', '   ', 2000, SIGN_KEY)
  assert.equal(blank.answer, null)
  assert.equal(blank.mac, relay.doneMac(SIGN_KEY, rid(1), 'answered', 2000, null))
  assert.equal(relay.doneRecord(rid(1), SESSION, 'expired', null, null, 2000, null).mac, null)
})

test('relay: the clip never ends on half a surrogate pair', () => {
  // 19999 characters, then an emoji (two UTF-16 units) across the 20000 mark: the high half goes too
  const cut = relay.clipAnswer('x'.repeat(19999) + '\u{1F600}' + 'tail')
  assert.equal(cut.length, 19999)
  assert.equal(cut.isWellFormed(), true)
  const whole = relay.clipAnswer('x'.repeat(19998) + '\u{1F600}' + 'tail')
  assert.equal(whole.length, 20000)
  assert.equal(whole.endsWith('\u{1F600}'), true)
})
